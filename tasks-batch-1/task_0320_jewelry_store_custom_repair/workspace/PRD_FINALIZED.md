# Jewelry Store Custom Repair API — Product Requirements Document

## 1. Introduction

This document specifies the back-office platform that runs a full-service jewelry store: an operation that simultaneously sells finished pieces from a display case, designs bespoke jewelry from scratch, repairs and resizes both store-owned and customer-owned pieces, finances purchases through layaway, buys precious metal and gemstones back from walk-in sellers, special-orders pieces from outside vendors, and issues the insurance-grade appraisal documents that customers need to schedule coverage. Each of these lines of business has its own paperwork, its own money flow, and its own sequence of physical handoffs between the front counter and the bench — yet they all share one customer ledger, one inventory of physical pieces, and one set of jewelers' workbenches that can only hold one job at a time.

The platform's central difficulty is reconciliation. A single piece of metal may be appraised, reserved on a layaway plan, pulled back into the repair queue under warranty, and finally sold — and every one of those steps moves money, changes the item's availability, and is observed by more than one staff member who may be acting on a stale view of the record. The system therefore treats every monetary figure as an integer count of cents, derives running balances rather than storing them as free-standing truth, and guards the handful of operations where two clerks could collide with explicit version checks. The sections that follow define the shared API contract first, then walk each business workflow in the order a real transaction unfolds.

The actors are the store's own staff — front-of-house sales associates, bench goldsmiths, and the store manager who signs off on money and quality — plus the end customer, who is given read-only visibility into their own records and the single ability to open a warranty claim.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH` (HTTP 401) before any other processing. If both headers are present and well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `X-User-Role` header must name exactly one of four roles: `SalesAssociate`, `Goldsmith`, `StoreManager`, or `Customer`.

- A `SalesAssociate` is front-of-house staff responsible for intake, quoting, customer and payment handling, pickups, and deliveries.
- A `Goldsmith` is a bench jeweler who performs design, production, and the physical repair work.
- A `StoreManager` owns inventory creation, appraisals, quality-control sign-off, cancellations, refunds, trade-in approvals, and the credit ledger.
- A `Customer` is the end customer, limited to read-only self-service plus the ability to submit a warranty claim.

For the three staff roles — `SalesAssociate`, `Goldsmith`, and `StoreManager` — the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may accept and record it but does not compare it to any entity's `id`; staff authorization is decided entirely by `X-User-Role`. When `X-User-Role` is `Customer`, by contrast, `X-User-ID` is the `id` of the acting `Customer` record; any ownership check on a resource that references a customer compares the resource's `customer_id` to `X-User-ID`.

The exact authorized roles for each operation are listed in the endpoint table of §4. Authorization (the role check) is evaluated before resource existence, and resource existence is evaluated before any request-body or business validation.

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

### 2.3. Pagination

All list (collection) endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and must be at least 0. Requests that supply values outside these bounds are treated as malformed requests under the request-validation rules described below.

List results are always returned sorted by `created_at` in ascending order (oldest first). Each list response reports its pagination state in the `meta` object via the fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Identity

Every resource is assigned an `id` that is a server-minted UUID. The `id` is opaque, carries no embedded type prefix, and is used only for identity. Clients never supply an `id`; it is generated by the server on creation.

Most resources also carry three system-managed fields. `created_at` is the ISO 8601 UTC timestamp (with three fractional digits) at which the record was created. `updated_at` is the timestamp of the most recent mutation. `version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation that changes the record; it is the basis for optimistic concurrency control described in §2.7.

Two record types are append-only and therefore do **not** carry `updated_at` or `version` — they expose only `id` and `created_at`. The first is the `Payment` record, which is written once and never mutated. The second is the `CreditLedgerEntry`, which is likewise an immutable line in the store-credit ledger. All other resources — customers, inventory items, workbenches, appraisals, custom-design orders, repair tickets, layaway plans, trade-in offers, special orders, and warranty claims — carry the full set of `created_at`, `updated_at`, and `version`.

### 2.5. Nested Retrieval and Foreign-Key Resolution

When an endpoint's URL embeds a resource identifier (for example, a specific appraisal, custom order, repair ticket, layaway plan, trade-in offer, special order, warranty claim, payment, or ledger entry), that identifier is resolved first; if it names no existing record, the request fails with `ERR_NOT_FOUND` (HTTP 404). Where a path contains more than one identifier, identifiers are validated left to right, so the leftmost missing segment determines the error.

Separately, several creation requests carry foreign keys inside the request body rather than the path — for instance a `customer_id`, an `inventory_item_id`, a `custom_order_id`, a `layaway_plan_id`, or a `special_order_id`. When a body foreign key points at a record that does not exist, the request fails with `ERR_FK_NOT_FOUND` (HTTP 404). This referential check applies to creating custom orders, repair tickets, layaway plans, trade-in offers, special orders, appraisals, warranty claims, payments, and ledger entries.

### 2.6. Monetary Precision and Rounding

All money in the system is stored and exchanged as an integer number of cents; there are no fractional-cent values and no floating-point currency fields in any response. Wherever a calculation produces a non-integer intermediate (for example, applying a percentage markup or a purity factor), the result is rounded to a whole number of cents using **round half up** — that is, a value whose fractional part is exactly one-half rounds away from zero to the next whole cent. Two computations in the system deliberately do not round half up: installment sizing uses a floor (truncation toward zero) so the schedule never over-collects, and the store-credit balance is an exact integer sum that needs no rounding. Where a calculation rounds at several named steps, each step's rounding is applied at that step rather than deferred — most consequentially, custom-order final totals round each line independently before the lines are summed.

### 2.7. Optimistic Concurrency Control

Because several staff may act on the same record, mutating operations are protected against lost updates with version checks. There are two distinct mechanisms.

First, most state-changing operations on a record require the caller to pass `expected_version`, carrying the `version` the client last read for *that same record*. If the supplied `expected_version` does not match the record's current `version`, the mutation is rejected as a stale write. If a mutation that requires a version field omits it entirely, the request fails with `ERR_VERSION_REQUIRED` (HTTP 422).

Second, two operations are guarded not against their own record's version but against the version of a *referenced inventory item*, because the real contention is over the physical piece. These operations require the field `expected_inventory_item_version`, which must carry the client's last observed `version` of the relevant `InventoryItem`:

- Finalizing an appraisal must carry `expected_inventory_item_version` matching the current `version` of the appraised `InventoryItem`. If another writer has finalized a competing appraisal — legitimately becoming the item's latest replacement value and advancing the item's `version` — since the client last read the item, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412), because this writer's view of the item is stale.
- Activating a layaway plan must carry `expected_inventory_item_version` matching the current `version` of the reserved `InventoryItem`. If another writer has reserved or sold the same item (advancing its `version`) since the client last read it, the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), because the reserve attempt is based on a stale view of the item.

If either of these two operations omits `expected_inventory_item_version`, the request fails with `ERR_VERSION_REQUIRED` (HTTP 422). Operations not listed among these version-guarded mutations take no version field at all.

### 2.8. Request Validation and Its Ordering

The system validates each request through a fixed priority pipeline; an earlier failing check determines the error and later checks are not reached. The order is: authentication headers first (`ERR_MISSING_AUTH`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of any path-referenced resource (`ERR_NOT_FOUND`), then existence of body foreign keys (`ERR_FK_NOT_FOUND`), then request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422 — required fields present, enum values legal, integers within their declared ranges), then uniqueness constraints (`ERR_DUPLICATE`, HTTP 409), then payment-target consistency (`ERR_PAYMENT_TARGET_MISMATCH`, HTTP 422), then state legality of the requested transition (`ERR_INVALID_STATE`, HTTP 409), then the cross-entity state guards (the item-availability, item-sold, customer-status, and coverage checks described in §3), then the remaining domain rules — revision caps, line-item presence, parts presence, scheduling overlaps, deposit sufficiency, balance clearance — and finally the version checks (`ERR_VERSION_REQUIRED` for a missing version field, then `ERR_STALE_VERSION` for a mismatched inventory-item version).

Two uniqueness constraints exist: a `Customer`'s `email` is unique across all customers, and an `InventoryItem`'s `sku` is unique across all inventory items. A second customer created with an email already on file, or a second item with an existing SKU, is rejected with `ERR_DUPLICATE`.

### 2.9. The Store-Credit Ledger

Store credit is never stored as a mutable number. Each `Customer` exposes a computed `store_credit_balance_cents`, which is defined as the exact sum of `amount_cents` over every `CreditLedgerEntry` for that customer whose `direction` is `CREDIT`, minus the exact sum of `amount_cents` over every entry whose `direction` is `DEBIT`. The balance starts at 0 for a new customer and is recomputed from the full ledger on every ledger write; the computation considers all ledger rows for the customer with no status filter and applies no rounding. Each ledger entry records the customer it moves (`customer_id`), its `direction` (`CREDIT` or `DEBIT`), its absolute `amount_cents` (which must be greater than 0), and a `reason` drawn from `TRADE_IN`, `LAYAWAY_REFUND`, `PURCHASE`, or `MANUAL_ADJUSTMENT`. Ledger entries are immutable once written.

### 2.10. Bench and Appraiser Scheduling — Two Overlap Disciplines

The store schedules two scarce resources, and they use deliberately different overlap rules.

A jeweler's `Workbench` can hold only one repair job in a given time window. When a repair ticket reserves a bench window, the reservation interval is **half-open**: it covers from `scheduled_start` up to but not including `scheduled_end`. Two windows on the same bench conflict only if the new window starts strictly before the other's end and the other starts strictly before the new window's end. Because the interval is half-open, adjacency is permitted — a window that ends exactly when another begins does not conflict. The set considered for conflict is every other repair ticket on the same `bench_id` that already has both a `scheduled_start` and `scheduled_end` set and whose status is neither `PICKED_UP` nor `CANCELLED`. Any conflict rejects the reservation with `ERR_BENCH_CONFLICT` (HTTP 409).

An appraiser's appointment slot uses the stricter discipline. The interval is **closed** — both `appointment_start` and `appointment_end` count as occupied — and in addition a 30-minute buffer must separate consecutive appointments for the same appraiser. Effectively, an existing appointment occupies the window from 30 minutes before its `appointment_start` to 30 minutes after its `appointment_end`. A new appointment conflicts with an existing one for the same `appraiser_name` if the new appointment's start is at or before the existing end plus the buffer, and the existing start minus the buffer is at or before the new appointment's end. Because the comparison is closed and buffered, appointments that merely touch endpoints do collide, and appointments within 30 minutes of each other collide. The set considered is existing appraisals with the same `appraiser_name` whose status is `DRAFT` or `FINALIZED` (`VOID` appraisals are excluded). Any conflict rejects creation with `ERR_APPRAISAL_SLOT_CONFLICT` (HTTP 409). All scheduling timestamps are compared as ISO 8601 UTC instants.

### 2.11. Cross-Entity Cascades and Version Semantics

Many operations in this system mutate more than the record named in the request. When an operation changes a second record — moving an inventory item's availability, posting a ledger entry, spawning or resolving a related ticket — that secondary record is itself a mutation: its `updated_at` is refreshed and its `version` is incremented by 1, exactly as a direct edit would. The specific cascades are described in the workflows of §3, but the rule is uniform: every record that an operation writes advances its own `version`. The custom-order, layaway, special-order, and trade-in cancellation and acceptance flows additionally write the store-credit ledger, which in turn forces a recomputation of the affected customer's `store_credit_balance_cents`.

## 3. Business Logic & Workflows

### 3.1. Customers, Inventory, and Workbenches — The Standing Records

A customer record is created from a `full_name`, an `email`, and a `phone`. On creation the customer's `status` is `ACTIVE` and the computed `store_credit_balance_cents` is 0. The only mutation to a customer (other than ledger-driven balance recomputation) is suspension: a manager may move a customer from `ACTIVE` to `SUSPENDED`, which requires the customer's current `version` via `expected_version`. A suspended customer is the reason a later trade-in acceptance can fail, as described in §3.6. Customers can be listed (optionally filtered by `email`) and fetched individually, where the fetch returns the freshly computed store-credit balance.

Inventory items are the physical pieces. An item is created with a `sku` (unique across all items), a `title` such as a display name, a `metal_karat` of `K14`, `K18`, or `K24`, and a `list_price_cents` that must be greater than 0. A new item begins life `IN_STOCK`. Over its life an item's `status` moves among `IN_STOCK`, `RESERVED`, `SOLD`, and `IN_REPAIR` as layaway, sales, and repair workflows drive it; these transitions are described where those workflows live. Each item also exposes `latest_appraised_value_cents`, a computed replacement value that stays null until an appraisal on the item is finalized; its derivation is covered in §3.2. Items can be listed (filtered by `sku` or `status`) and fetched individually.

A `Workbench` is a bench station identified by a `label` that is unique across all workbenches. A workbench is always created with `status` `ACTIVE`; there is no retirement flow in this version. Workbenches exist so repair tickets can reserve non-overlapping time windows against them, per the bench-scheduling discipline of §2.10.

### 3.2. Appraisals and the Insurance Document

An appraisal documents the assessed value of a single inventory item and, once finalized, becomes the insurance-grade paperwork a customer uses to schedule coverage. Creating an appraisal — a manager-only action — references the appraised piece by `inventory_item_id` and supplies the `appraiser_name`, an `appointment_start` and `appointment_end` (the end must be strictly later than the start), a `market_value_cents` greater than 0, and an optional `replacement_factor`. The replacement factor is a multiplier in the range 1.00 to 2.00 inclusive; when omitted it defaults to 1.30. On creation the appraisal is `DRAFT`, its `document_number` is null, and its `replacement_value_cents` is computed as the `market_value_cents` multiplied by the `replacement_factor`, rounded half up to whole cents. Booking the appointment runs the appraiser-slot overlap check of §2.10; a clashing slot is rejected with `ERR_APPRAISAL_SLOT_CONFLICT`.

Finalizing a draft appraisal, transitioning it `DRAFT → FINALIZED`, is the step that turns it into a numbered document. Finalize is permitted only from `DRAFT`; attempting it from any other state yields `ERR_INVALID_STATE`. It additionally requires that the referenced inventory item is not `SOLD` — a sold piece can no longer be appraised for the store, and the attempt fails with `ERR_ITEM_SOLD`. Because finalize is OCC-guarded on the item, the caller must pass `expected_inventory_item_version` matching the item's current `version`, failing with `ERR_VERSION_REQUIRED` if absent and `ERR_STALE_VERSION` if it no longer matches. On success the system assigns the `document_number` as the string `APR-` followed by the next zero-padded sequential number for the store, recomputes the item's `latest_appraised_value_cents`, increments the item's `version`, and increments the appraisal's own `version`. The item's `latest_appraised_value_cents` is defined as the `replacement_value_cents` of the item's most recent `FINALIZED` appraisal, selecting by `created_at` descending and taking the first; if the item has no finalized appraisal, the value is null.

An appraisal may also be voided, transitioning `DRAFT → VOID` or `FINALIZED → VOID`; void is legal from either `DRAFT` or `FINALIZED` and otherwise yields `ERR_INVALID_STATE`. Voiding requires the appraisal's own `expected_version`. If the voided appraisal happened to be the item's latest finalized appraisal, the item's `latest_appraised_value_cents` is recomputed from the next most recent finalized appraisal, or set to null if none remains. Voiding increments the appraisal's `version`. `VOID` is terminal.

### 3.3. The Custom-Design Order Lifecycle

A custom-design order captures a bespoke commission and runs the longest lifecycle in the system, including a bounded revision loop. The order is created — by a sales associate or manager — against a `customer_id`, with a free-text `description`, an `estimated_materials_cents` greater than 0 used for the early quote, and a flat `design_fee_cents` of at least 0 that is conceptually non-refundable. A new order is `DRAFT` with `deposit_paid_cents` of 0 and `revision_count` of 0.

**Quoting.** A sales associate quotes the order, transitioning `DRAFT → QUOTED` (legal only from `DRAFT`). Quoting computes the provisional figures: the `provisional_total_cents` is the `estimated_materials_cents` marked up by 20 percent — that is, the estimated materials multiplied by 1.20 and rounded half up — then the flat `design_fee_cents` added on top. From that, the `deposit_required_cents` is 30 percent of the provisional total, rounded half up. The order's `balance_due_cents` is then set to the provisional total minus whatever has been paid so far (`deposit_paid_cents`). Quoting requires the order's `expected_version`.

**Deposit and design.** Deposits arrive as payments (see §3.9). A payment against this order accumulates into `deposit_paid_cents` — the running sum of all `SUCCEEDED` payments targeting this custom order. The moment that accumulated deposit reaches or exceeds `deposit_required_cents`, the system itself advances the order `QUOTED → DEPOSIT_PAID` and refreshes `deposit_paid_cents` and `balance_due_cents`; no explicit call drives this transition. Once the deposit is in, a goldsmith begins work, moving `DEPOSIT_PAID → IN_DESIGN` (legal only from `DEPOSIT_PAID`). The goldsmith later submits the design for review, moving `IN_DESIGN → DESIGN_REVIEW`. Each of these goldsmith steps requires the order's `expected_version`.

**The revision loop.** From `DESIGN_REVIEW` a sales associate may either send the design back for changes or approve it. Requesting a revision transitions `DESIGN_REVIEW → IN_DESIGN` and increments `revision_count` by 1, reopening the design phase; this is the cyclic loop `DESIGN_REVIEW → IN_DESIGN → DESIGN_REVIEW`. The loop is capped at 3 revisions: a revision request is permitted only while `revision_count` is below 3, so the fourth request — made when `revision_count` already equals 3 — is rejected with `ERR_MAX_REVISIONS_REACHED`. Requesting a revision is legal only from `DESIGN_REVIEW` and requires the order's `expected_version`.

**Approval and the line items.** Approving the design transitions `DESIGN_REVIEW → APPROVED` (legal only from `DESIGN_REVIEW`) and is the point at which the actual bill of materials is locked in. The approval request supplies `line_items`, an array in which each element carries a `qty`, a `unit_price_cents`, and a `markup_pct`. The line items must be non-empty; an approval with empty line items is rejected with `ERR_LINE_ITEMS_REQUIRED`. The supplied line items are persisted on the order and will drive the final total. Approval requires the order's `expected_version`.

**Production and final totals.** A goldsmith starts production, moving `APPROVED → IN_PRODUCTION`, and later completes production, moving `IN_PRODUCTION → READY`. Completing production is where the `final_total_cents` is computed from the persisted line items. The final total is built by taking, for each line, the product of its `qty`, its `unit_price_cents`, and one plus its `markup_pct`, rounding that line to whole cents half up, and only then summing the rounded line totals; the flat `design_fee_cents` is added to that sum. Rounding is applied per line before the lines are added — not by summing first and rounding once — and the two approaches can legitimately differ by a cent. Completing production also recomputes the `balance_due_cents`: once production is complete the balance is the `final_total_cents` minus `deposit_paid_cents`, whereas before production completes the balance is the provisional total minus `deposit_paid_cents`. Both production steps require the order's `expected_version`.

**Completion.** Finally a sales associate completes the order, moving `READY → COMPLETED`. Completion is legal only from `READY` and additionally requires that the balance be cleared — `balance_due_cents` must be zero or less; an order with money still owed is rejected with `ERR_BALANCE_OUTSTANDING`. Completion requires the order's `expected_version`. `COMPLETED` is terminal.

**Cancellation.** A manager may cancel an order while it is still in any of `DRAFT`, `QUOTED`, `DEPOSIT_PAID`, `IN_DESIGN`, `DESIGN_REVIEW`, or `APPROVED`; cancellation is forbidden — and yields `ERR_INVALID_STATE` — once the order has reached `IN_PRODUCTION`, `READY`, `COMPLETED`, or is already `CANCELLED`. On cancellation, if any deposit has been collected (`deposit_paid_cents` greater than 0), the system refunds it to the customer's store credit by posting a `CreditLedgerEntry` with direction `CREDIT`, an `amount_cents` equal to `deposit_paid_cents`, and reason `LAYAWAY_REFUND`, then recomputes the customer's `store_credit_balance_cents`. Cancellation requires the order's `expected_version`. `CANCELLED` is terminal.

### 3.4. Repair Tickets — Intake, the Bench, and the Fork-Join Floor

Repair tickets cover resizing, stone resets, polishing, clasp repairs, and warranty work, and their lifecycle forks (parts vs. no-parts) and joins again before quality control. A ticket is created — by a sales associate or manager — against a `customer_id`, an optional `inventory_item_id` (set for store-owned pieces under resizing or warranty work, null for a customer's own piece), a `repair_kind` of `RESIZE`, `STONE_RESET`, `POLISH`, `CLASP_REPAIR`, or `WARRANTY`, an optional `rush` flag, and a `promised_at` turnaround timestamp. A new ticket begins `INTAKE` with `parts_cents` and `labor_cents` both 0. The `rush` flag defaults to false when omitted. Tickets can be listed (filtered by `customer_id`, `inventory_item_id`, `warranty_claim_id`, or `bench_id`) and fetched individually.

**Scheduling a bench.** Independently of the work lifecycle, a goldsmith or manager may reserve a bench window for the ticket by supplying a `bench_id`, a `scheduled_start`, and a `scheduled_end` (the end must be strictly later than the start, and the reservation interval is exclusive of the end). The reservation runs the half-open bench-overlap check of §2.10 against other active tickets on the same bench, rejecting a clash with `ERR_BENCH_CONFLICT`. Scheduling requires the ticket's `expected_version`. The `bench_id`, `scheduled_start`, and `scheduled_end` remain null until the ticket is scheduled.

**Assessment.** A goldsmith assesses the ticket, transitioning `INTAKE → ASSESSED`, and supplies the `parts_cents` and `labor_cents` for the job. For a `WARRANTY` ticket these costs are forced to 0 regardless of input. Assessment computes the surcharge and total: the subtotal is `parts_cents` plus `labor_cents`, evaluated first. A warranty ticket carries a `rush_surcharge_cents` of 0 and a `total_cents` of 0 and is done. For a non-warranty ticket, if `rush` is false the `rush_surcharge_cents` is 0; if `rush` is true a tiered percentage of the subtotal applies — 10 percent when the subtotal is below 10000 cents, 20 percent when the subtotal is from 10000 cents up to and including 50000 cents, and 30 percent when the subtotal exceeds 50000 cents (so a subtotal of exactly 50000 cents takes the 20-percent tier, and 50001 cents takes the 30-percent tier). The surcharge is that percentage of the subtotal rounded half up, and the `total_cents` is the subtotal plus the surcharge. Assessment also moves a store-owned piece into the shop: if `inventory_item_id` is set, the referenced item transitions to `IN_REPAIR`. Assessment requires the ticket's `expected_version`.

**The fork.** From `ASSESSED` the ticket forks. If the job needs parts, the goldsmith routes it `ASSESSED → AWAITING_PARTS`; this branch is permitted only when `parts_cents` is greater than 0, and ordering parts on a ticket that needs none is rejected with `ERR_NO_PARTS_NEEDED`. When parts arrive, the goldsmith moves `AWAITING_PARTS → IN_REPAIR`. Alternatively, if no parts are needed, the goldsmith starts work directly, moving `ASSESSED → IN_REPAIR` and skipping the parts branch. Both branches join at `IN_REPAIR`. Each of these steps requires the ticket's `expected_version`.

**The join and quality control.** From `IN_REPAIR` the goldsmith submits the finished work, moving `IN_REPAIR → QC`. A manager then signs off: passing QC moves `QC → READY`, while failing QC moves `QC → IN_REPAIR`, sending the piece back for rework (the rework loop). Each of these steps is legal only from the named source state and requires the ticket's `expected_version`.

**Pickup and cancellation.** A sales associate completes the ticket on customer pickup, moving `READY → PICKED_UP`. Pickup restores a store-owned piece: if `inventory_item_id` is set, that item transitions back to `IN_STOCK`. If the ticket was spawned from a warranty claim — that is, `warranty_claim_id` is set — pickup bubbles up to resolve the originating claim, moving that `WarrantyClaim` to `RESOLVED`. Pickup is legal only from `READY` and requires the ticket's `expected_version`. `PICKED_UP` is terminal. Separately, a manager may cancel a ticket from any of `INTAKE`, `ASSESSED`, `AWAITING_PARTS`, `IN_REPAIR`, or `QC` (cancellation is forbidden once the ticket is `READY`, `PICKED_UP`, or already `CANCELLED`, yielding `ERR_INVALID_STATE`). Cancellation likewise restores a set `inventory_item_id` back to `IN_STOCK`, but if the ticket was warranty-spawned it instead bubbles the originating `WarrantyClaim` to `REJECTED`. Cancellation requires the ticket's `expected_version`. `CANCELLED` is terminal.

### 3.5. Layaway Plans — Reserving, Paying Down, and Settling

A layaway plan lets a customer reserve a piece and pay it off over time. A plan is created — by a sales associate or manager — against a `customer_id`, an `inventory_item_id`, and an `installment_count` that must be an integer from 2 to 24 inclusive. A new plan is `PENDING` with `paid_to_date_cents` of 0.

**Activation.** A sales associate activates the plan, transitioning `PENDING → ACTIVE`. Activation is legal only from `PENDING`, and it additionally requires that the reserved item is currently `IN_STOCK`; an item that is not in stock rejects activation with `ERR_ITEM_NOT_AVAILABLE`. Activation is OCC-guarded on the item, so the caller passes `expected_inventory_item_version` matching the item's current `version` (absent → `ERR_VERSION_REQUIRED`; mismatched → `ERR_STALE_VERSION`). On activation the plan snapshots `item_price_cents` from the item's `list_price_cents` (which must be greater than 0) and computes its schedule. The `down_payment_cents` is 20 percent of the snapshot price, rounded half up. The remaining amount after the down payment is divided by the `installment_count` using floor (truncation) to give the `installment_amount_cents`, with the final installment absorbing any remainder so the schedule collects exactly the snapshot price. The `projected_payoff_cents` — what the customer pays if they complete the plan on schedule with no fees — equals the snapshot `item_price_cents` exactly. Activation sets `paid_to_date_cents` equal to the `down_payment_cents`, moves the inventory item to `RESERVED`, increments the item's `version`, and increments the plan's `version`.

**Paying it off.** Installments arrive as payments (see §3.9). The plan's `paid_to_date_cents` is the down payment plus the running sum of all `SUCCEEDED` payments targeting this plan. When `paid_to_date_cents` reaches or exceeds the snapshot `item_price_cents`, the system itself advances the plan `ACTIVE → PAID_IN_FULL` and refreshes `paid_to_date_cents`; no explicit call drives this. A sales associate then fulfills the paid plan, moving `PAID_IN_FULL → FULFILLED` (legal only from `PAID_IN_FULL`), which delivers the piece by moving the inventory item to `SOLD` and increments the plan's `version`. Fulfillment requires the plan's `expected_version`. `FULFILLED` is terminal.

**Settlement on cancellation.** A manager may cancel a plan from either `PENDING` or `ACTIVE` (otherwise `ERR_INVALID_STATE`). Cancellation computes the settlement. The `restocking_fee_cents` is the smaller of 50000 cents and 15 percent of the snapshot `item_price_cents` rounded half up — that is, the restocking fee is capped at 50000 cents. The `settlement_refund_cents` is whatever the customer has paid to date minus that restocking fee, but never below 0. If the plan was `ACTIVE`, cancellation releases the reserved item back to `IN_STOCK`. If the settlement refund is greater than 0, the system posts a `CreditLedgerEntry` with direction `CREDIT`, `amount_cents` equal to the settlement refund, and reason `LAYAWAY_REFUND`, then recomputes the customer's `store_credit_balance_cents`. Cancellation requires the plan's `expected_version`. `CANCELLED` is terminal.

### 3.6. Trade-Ins and Buyback Credit

A trade-in offer values a customer's metal-and-gemstone item for buyback. The offer is created — by a sales associate or manager — against a `customer_id`, with a `metal_karat` of `K14`, `K18`, or `K24`, a `metal_weight_grams` greater than 0, a `metal_spot_price_cents_per_gram` greater than 0 captured as a snapshot at offer time, an optional `gemstone_value_cents` of at least 0 (defaulting to 0), and a `condition` grade of `EXCELLENT`, `GOOD`, or `FAIR`. The valuation is computed at creation from these snapshot inputs and is never recomputed afterward. A new offer is `OFFERED`.

The valuation proceeds in named steps, each rounded half up where it produces a non-integer, with the clamp applied last. The `metal_value_cents` is the `metal_weight_grams` multiplied by the `metal_spot_price_cents_per_gram` multiplied by the purity factor for the karat, rounded half up; the purity factor is 0.585 for `K14`, 0.750 for `K18`, and 1.000 for `K24`. A raw credit is then formed by adding the `gemstone_value_cents` to the `metal_value_cents`, multiplying by the condition factor, and rounding half up; the condition factor is 0.90 for `EXCELLENT`, 0.75 for `GOOD`, and 0.55 for `FAIR`. The `buyback_credit_cents` is that raw credit clamped to the range from a 2500-cent floor to a 5000000-cent ceiling — that is, never less than 2500 cents and never more than 5000000 cents. Offers can be listed (filtered by `customer_id` or `credit_ledger_entry_id`) and fetched individually.

A manager accepts or declines an offer, both legal only from `OFFERED`. Accepting transitions `OFFERED → ACCEPTED` and additionally requires that the customer is `ACTIVE`; a suspended customer rejects acceptance with `ERR_CUSTOMER_SUSPENDED`. On acceptance the system posts a `CreditLedgerEntry` with direction `CREDIT`, `amount_cents` equal to the `buyback_credit_cents`, and reason `TRADE_IN`, sets the offer's `credit_ledger_entry_id` to the new entry, recomputes the customer's `store_credit_balance_cents`, and increments the offer's `version`. Declining transitions `OFFERED → DECLINED` with no ledger effect and increments the offer's `version`. Both acceptance and decline require the offer's `expected_version`. The `credit_ledger_entry_id` is null until accepted. Both `ACCEPTED` and `DECLINED` are terminal.

### 3.7. Special Orders — Sourcing From a Vendor

A special order sources a piece the store does not stock from an outside vendor. It is created — by a sales associate or manager — against a `customer_id`, a `vendor_name`, a `catalog_ref` (the vendor catalog reference), and a `quoted_price_cents` greater than 0. On creation the order is `REQUESTED`, its `deposit_paid_cents` is 0, and its `deposit_required_cents` is computed as the special-order deposit percentage applied to the quoted price, rounded half up. Special orders can be listed (filtered by `customer_id` or `received_inventory_item_id`) and fetched individually.

A sales associate places the order with the vendor, transitioning `REQUESTED → PLACED`. Placing is legal only from `REQUESTED` and additionally requires that the deposit be satisfied — `deposit_paid_cents` must be at least `deposit_required_cents`; an under-funded order is rejected with `ERR_DEPOSIT_REQUIRED`. (Deposits arrive as payments, per §3.9.) Placing requires the order's `expected_version`. When the piece arrives, a sales associate receives it, transitioning `PLACED → ARRIVED`; receiving supplies a `sku` and a `metal_karat` and creates a new `InventoryItem` with status `RESERVED`, `list_price_cents` equal to the `quoted_price_cents`, the supplied `sku`, a `title` taken from the `catalog_ref`, and the supplied `metal_karat`, then records that item on the order as `received_inventory_item_id`. Receiving requires the order's `expected_version`; the `received_inventory_item_id` is null until arrival. The associate then delivers the piece to the customer, transitioning `ARRIVED → DELIVERED`, which moves the received inventory item to `SOLD` and increments the order's `version`. Delivery is legal only from `ARRIVED` and requires the order's `expected_version`. `DELIVERED` is terminal.

A manager may cancel a special order while it is `REQUESTED` or `PLACED` (otherwise `ERR_INVALID_STATE`). On cancellation, if any deposit has been collected, the system refunds it by posting a `CreditLedgerEntry` with direction `CREDIT`, `amount_cents` equal to `deposit_paid_cents`, and reason `LAYAWAY_REFUND`, then recomputes the customer's `store_credit_balance_cents`. Cancellation requires the order's `expected_version`. `CANCELLED` is terminal.

### 3.8. Warranty Claims and the Spawned Repair

A warranty claim ties a covered piece back into the repair floor. A claim is submitted — by a sales associate, manager, or the customer themselves — against an `inventory_item_id`, a `customer_id`, and a free-text `defect_description`. A new claim is `SUBMITTED`. Claims can be listed (filtered by `inventory_item_id`, `customer_id`, or `spawned_repair_ticket_id`) and fetched individually.

A manager approves or rejects a submitted claim, both legal only from `SUBMITTED`. Approving transitions `SUBMITTED → APPROVED` and additionally requires proof of coverage: the covered inventory item must have a `FINALIZED` appraisal on file, and a claim on an un-appraised piece is rejected with `ERR_NO_COVERAGE`. On approval the system spawns a repair ticket — creating a `RepairTicket` with `repair_kind` `WARRANTY`, the claim's `customer_id` and `inventory_item_id`, `parts_cents` and `labor_cents` of 0, `rush` false, and its `warranty_claim_id` pointing back at this claim, beginning at `INTAKE` — and records that ticket on the claim as `spawned_repair_ticket_id`. Approval increments the claim's `version`. Rejecting transitions `SUBMITTED → REJECTED` with no repair spawned. Both approval and rejection require the claim's `expected_version`; the `spawned_repair_ticket_id` is null unless a repair was spawned.

The claim then tracks its spawned repair. When that warranty repair ticket is eventually picked up — reaching `PICKED_UP` — the claim bubbles up `APPROVED → RESOLVED`, as noted in §3.4; and if that ticket is instead cancelled, the claim bubbles to `REJECTED`. Both `REJECTED` and `RESOLVED` are terminal states of the claim.

### 3.9. Payments and the Money They Move

A payment records a `SUCCEEDED` charge against exactly one of three parent aggregates. A payment carries a `target_type` discriminator of `CUSTOM_ORDER`, `LAYAWAY`, or `SPECIAL_ORDER`, an `amount_cents` greater than 0, and the matching parent foreign key — `custom_order_id` when the target is a custom order, `layaway_plan_id` when it is a layaway plan, or `special_order_id` when it is a special order. Exactly the one foreign key matching `target_type` must be present and must reference an existing parent, and the other two must be absent; any other combination — wrong key populated, multiple keys populated, or the named parent missing — is rejected with `ERR_PAYMENT_TARGET_MISMATCH`. A payment is created by a sales associate or manager, its `outcome` is set to `SUCCEEDED`, and it is append-only — it carries no `version` and is never modified.

Recording a payment recomputes the parent's running total and can trigger an automatic state advance. A custom-order payment refreshes that order's `deposit_paid_cents` and `balance_due_cents` and, if the deposit now meets the requirement, drives the automatic `QUOTED → DEPOSIT_PAID` advance described in §3.3. A layaway payment refreshes that plan's `paid_to_date_cents` and, if it now meets the item price, drives the automatic `ACTIVE → PAID_IN_FULL` advance described in §3.5. A special-order payment accumulates into that order's `deposit_paid_cents`, which is what later satisfies the deposit requirement at placing. Payments can be listed (filtered by `custom_order_id`, `layaway_plan_id`, or `special_order_id`) and fetched individually.

### 3.10. The Credit Ledger as a Direct Operation

Beyond the ledger entries that workflows post automatically (trade-in credits, layaway and order refunds), a manager may post a manual ledger entry directly, supplying the `customer_id`, the `direction` (`CREDIT` or `DEBIT`), the `amount_cents` (greater than 0), and the `reason` (`TRADE_IN`, `LAYAWAY_REFUND`, `PURCHASE`, or `MANUAL_ADJUSTMENT`). Posting an entry recomputes the affected customer's `store_credit_balance_cents` as described in §2.9. Ledger entries can be listed (filtered by `customer_id`) and fetched individually. Like payments, ledger entries are immutable once written.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. A request that creates a new resource returns HTTP 201; a request that modifies an existing resource (including every state transition) returns HTTP 200; a successful read returns HTTP 200. The request body, computed effects, and side effects of each endpoint are governed by the narratives of §3 and the principles of §2 — the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /customers | Create a customer | SalesAssociate, StoreManager |
| GET | /customers | List customers (filter by email) | SalesAssociate, StoreManager, Goldsmith |
| GET | /customers/{id} | Get a customer with computed store credit balance | SalesAssociate, StoreManager, Goldsmith, Customer |
| POST | /customers/{id}/suspend | Suspend a customer | StoreManager |
| POST | /inventory-items | Create an inventory item | StoreManager |
| GET | /inventory-items | List inventory items (filter by sku, status) | SalesAssociate, StoreManager, Goldsmith, Customer |
| GET | /inventory-items/{id} | Get an inventory item | SalesAssociate, StoreManager, Goldsmith, Customer |
| POST | /workbenches | Create a workbench | StoreManager |
| GET | /workbenches | List workbenches | SalesAssociate, StoreManager, Goldsmith |
| GET | /workbenches/{id} | Get a workbench | SalesAssociate, StoreManager, Goldsmith |
| POST | /appraisals | Create a DRAFT appraisal and book an appraiser slot | StoreManager |
| GET | /appraisals | List appraisals (filter by inventory_item_id) | SalesAssociate, StoreManager, Customer |
| GET | /appraisals/{id} | Get an appraisal | SalesAssociate, StoreManager, Customer |
| POST | /appraisals/{id}/finalize | Finalize appraisal; assign document number; OCC-guarded on item | StoreManager |
| POST | /appraisals/{id}/void | Void an appraisal | StoreManager |
| POST | /custom-orders | Create a DRAFT custom-design order | SalesAssociate, StoreManager |
| GET | /custom-orders | List custom orders (filter by customer_id) | SalesAssociate, StoreManager, Goldsmith, Customer |
| GET | /custom-orders/{id} | Get a custom order | SalesAssociate, StoreManager, Goldsmith, Customer |
| POST | /custom-orders/{id}/quote | Quote the order (provisional totals and deposit) | SalesAssociate |
| POST | /custom-orders/{id}/start-design | Begin design after deposit paid | Goldsmith |
| POST | /custom-orders/{id}/submit-review | Submit design for review | Goldsmith |
| POST | /custom-orders/{id}/request-revision | Request a design revision | SalesAssociate |
| POST | /custom-orders/{id}/approve-design | Approve design and lock line items | SalesAssociate |
| POST | /custom-orders/{id}/start-production | Start production | Goldsmith |
| POST | /custom-orders/{id}/complete-production | Complete production and compute final totals | Goldsmith |
| POST | /custom-orders/{id}/complete | Complete the order (requires balance cleared) | SalesAssociate |
| POST | /custom-orders/{id}/cancel | Cancel the order (refunds deposit to store credit) | StoreManager |
| POST | /repair-tickets | Create a repair ticket | SalesAssociate, StoreManager |
| GET | /repair-tickets | List repair tickets (filter by customer_id, inventory_item_id, warranty_claim_id, bench_id) | SalesAssociate, StoreManager, Goldsmith, Customer |
| GET | /repair-tickets/{id} | Get a repair ticket | SalesAssociate, StoreManager, Goldsmith, Customer |
| POST | /repair-tickets/{id}/schedule | Reserve a bench time window (overlap-checked) | Goldsmith, StoreManager |
| POST | /repair-tickets/{id}/assess | Assess parts/labor and compute totals | Goldsmith |
| POST | /repair-tickets/{id}/order-parts | Route to awaiting parts | Goldsmith |
| POST | /repair-tickets/{id}/parts-received | Parts received; move to repair | Goldsmith |
| POST | /repair-tickets/{id}/start-repair | Start repair directly (no-parts branch) | Goldsmith |
| POST | /repair-tickets/{id}/submit-qc | Submit for QC | Goldsmith |
| POST | /repair-tickets/{id}/pass-qc | Pass QC | StoreManager |
| POST | /repair-tickets/{id}/fail-qc | Fail QC and return to repair | StoreManager |
| POST | /repair-tickets/{id}/pickup | Customer pickup | SalesAssociate |
| POST | /repair-tickets/{id}/cancel | Cancel a repair ticket | StoreManager |
| POST | /layaway-plans | Create a PENDING layaway plan | SalesAssociate, StoreManager |
| GET | /layaway-plans | List layaway plans (filter by customer_id, inventory_item_id) | SalesAssociate, StoreManager, Customer |
| GET | /layaway-plans/{id} | Get a layaway plan | SalesAssociate, StoreManager, Customer |
| POST | /layaway-plans/{id}/activate | Activate plan; collect down payment; reserve item; OCC-guarded on item | SalesAssociate |
| POST | /layaway-plans/{id}/fulfill | Fulfill paid-in-full plan | SalesAssociate |
| POST | /layaway-plans/{id}/cancel | Cancel plan (settlement refund to store credit) | StoreManager |
| POST | /trade-ins | Create a buyback/trade-in offer (computes credit) | SalesAssociate, StoreManager |
| GET | /trade-ins | List trade-in offers (filter by customer_id, credit_ledger_entry_id) | SalesAssociate, StoreManager, Customer |
| GET | /trade-ins/{id} | Get a trade-in offer | SalesAssociate, StoreManager, Customer |
| POST | /trade-ins/{id}/accept | Accept offer and post store credit | StoreManager |
| POST | /trade-ins/{id}/decline | Decline offer | StoreManager |
| POST | /special-orders | Create a special order | SalesAssociate, StoreManager |
| GET | /special-orders | List special orders (filter by customer_id, received_inventory_item_id) | SalesAssociate, StoreManager, Customer |
| GET | /special-orders/{id} | Get a special order | SalesAssociate, StoreManager, Customer |
| POST | /special-orders/{id}/place | Place order with vendor (requires deposit) | SalesAssociate |
| POST | /special-orders/{id}/receive | Receive item; creates inventory item | SalesAssociate |
| POST | /special-orders/{id}/deliver | Deliver to customer | SalesAssociate |
| POST | /special-orders/{id}/cancel | Cancel special order (refund deposit) | StoreManager |
| POST | /payments | Record a SUCCEEDED payment against an order/plan | SalesAssociate, StoreManager |
| GET | /payments | List payments (filter by custom_order_id, layaway_plan_id, special_order_id) | SalesAssociate, StoreManager, Customer |
| GET | /payments/{id} | Get a payment | SalesAssociate, StoreManager, Customer |
| POST | /warranty-claims | Submit a warranty claim | SalesAssociate, StoreManager, Customer |
| GET | /warranty-claims | List warranty claims (filter by inventory_item_id, customer_id, spawned_repair_ticket_id) | SalesAssociate, StoreManager, Customer |
| GET | /warranty-claims/{id} | Get a warranty claim | SalesAssociate, StoreManager, Customer |
| POST | /warranty-claims/{id}/approve | Approve claim and spawn a warranty repair ticket | StoreManager |
| POST | /warranty-claims/{id}/reject | Reject claim | StoreManager |
| POST | /credit-ledger | Post a manual store-credit ledger entry | StoreManager |
| GET | /credit-ledger | List ledger entries (filter by customer_id) | SalesAssociate, StoreManager, Customer |
| GET | /credit-ledger/{id} | Get a ledger entry | SalesAssociate, StoreManager, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_DUPLICATE | 409 |
| ERR_PAYMENT_TARGET_MISMATCH | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ITEM_NOT_AVAILABLE | 409 |
| ERR_ITEM_SOLD | 409 |
| ERR_CUSTOMER_SUSPENDED | 409 |
| ERR_NO_COVERAGE | 409 |
| ERR_MAX_REVISIONS_REACHED | 409 |
| ERR_LINE_ITEMS_REQUIRED | 422 |
| ERR_NO_PARTS_NEEDED | 409 |
| ERR_BENCH_CONFLICT | 409 |
| ERR_APPRAISAL_SLOT_CONFLICT | 409 |
| ERR_DEPOSIT_REQUIRED | 402 |
| ERR_BALANCE_OUTSTANDING | 402 |
| ERR_STALE_VERSION | 412 |
| ERR_VERSION_REQUIRED | 422 |

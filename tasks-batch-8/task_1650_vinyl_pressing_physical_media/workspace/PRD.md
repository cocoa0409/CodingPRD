# Vinyl Pressing API — Product Requirements Document

## 1. Introduction

A vinyl pressing plant lives and dies by two scarce resources: hours on its press lines and trust from the labels that book them. Every order passes through a long physical pipeline — lacquer cutting, galvanic plating, stamper production, test pressing approval, jacket and insert printing, the pressing run itself, quality control, and finally warehousing and drop-shipment to distributors — and each stage can loop back on an earlier one. A rejected test pressing sends the order back to the cutting room; a quality hold sends it back to the schedule queue; a cancelled order releases capacity that queued competitors are waiting to absorb. Meanwhile the commercial side runs in parallel: quotes must be priced against tiered marginal rates and variant surcharges, credit limits gate confirmation, cancellation fees scale with how far the order had progressed, and final invoices must reconcile quoted expectations against overruns, underruns, repress fault, and test-pressing revision fees.

This document specifies the Vinyl Pressing API, the system of record for that entire operation. It covers customer and credit management, release and press-order intake with color-variant configuration, quoting and confirmation, tooling and plating-bath booking, the test-pressing approval loop, print-job coordination, slot scheduling against finite line capacity with changeover buffering, quality-control reporting with segregation of duties, repress decisions, inventory lots and zone-based receiving, FIFO shipment allocation with backorder sweeps, delay communication driven by a release-risk projection, and the full invoicing lifecycle including payments and self-referential credit memos. All scheduling, lead-time, and risk arithmetic runs against a controllable logical clock rather than wall-clock time, so that capacity and date-risk behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted to use the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

The system recognizes nine roles, spelled exactly as follows: `PlatformAdmin`, `CustomerServiceRep`, `Customer`, `ProductionPlanner`, `PressOperator`, `QaInspector`, `ProductionManager`, `WarehouseManager`, and `BillingClerk`. A tenth name, `Any`, is a pseudo-role used in this document to mark read endpoints that any authenticated role may call.

The `PlatformAdmin` is a technical operator who drives the logical test clock and nothing else; when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The `CustomerServiceRep` handles intake, quotes, print coordination, shipments, cancellations, and date revisions; the `ProductionPlanner` plans capacity across press lines, plating baths, maintenance windows, tooling starts, schedule commits, and test-pressing shipments; the `PressOperator` works the floor, advancing tooling stages, producing test pressings, and firing press start/complete events; the `QaInspector` files quality-control reports; the `ProductionManager` decides those reports; the `WarehouseManager` runs lots, stock events, and shipment picking; the `BillingClerk` issues invoices, records payments and credit memos, and manages credit holds. For each of these seven staff roles — `PlatformAdmin`, `CustomerServiceRep`, `ProductionPlanner`, `PressOperator`, `QaInspector`, `ProductionManager`, `WarehouseManager`, and `BillingClerk` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `filed_by` on a quality report or `decided_by` on a quality decision) but never compares it against any entity's `id`.

The `Customer` role is different: it is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer account, and ownership checks on any resource that belongs to a customer compare the release's `customer_id` field to `X-User-ID`. A `Customer` may confirm an order, review a test pressing, or decide a print proof only when the parent order's release belongs to that customer; any attempt against another label's work is rejected with `ERR_UNAUTHORIZED_ROLE`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — Customer, Release, PressOrder, ToolingJob, TestPressing, PrintJob, PressLine, PressSlot, PlatingBath, QCReport, InventoryLot, Shipment, and Invoice — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation and never changed.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by exactly one on every mutation of the resource; it anchors optimistic concurrency control.

The DelayNotice resource is the single exception. Because it is an append-only event log entry, it carries `id` and `created_at` only — it has no `updated_at` and no `version`, and no operation ever mutates a DelayNotice after creation.

### 2.5. Money, Cents, and Rounding Discipline

All monetary values in the system are integer cents — quotes, invoice lines, credit limits, cancellation fees, and storage fees alike. There are no fractional cents anywhere in the API. Wherever a computation produces a fraction (a percentage discount, a prorated credit, an average), the value is rounded half-up at the point the specification names, and only there; the rounding order is part of the contract, because rounding a sum once and rounding each component separately yield different cents. Calendar and capacity arithmetic (backlog days, slack days) uses decimal arithmetic rather than binary floating point, and day-level results are rounded half-up to two decimal places wherever a fractional day figure is exposed. Dates are ISO 8601 calendar dates in `yyyy-mm-dd` form; slot and bath hours are whole-hour integers bounded by the owning line's bookable day.

### 2.6. The Logical Clock

All date-sensitive behavior — lead-time enforcement, press-start gating, slot-date comparisons, backlog windows, storage-fee windows, and release-risk projection — reads a server-held logical clock, never wall-clock time. At server startup, before any clock operation, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `PlatformAdmin` may advance it through a dedicated test-driving capability, supplying the target instant as `to_iso8601`; the clock then holds that value until the next such call. "Today" anywhere in this document means the calendar date of the logical clock.

### 2.7. Optimistic Concurrency Control on Superseding Writes

Three write operations in this API supersede an existing value without changing the parent resource's lifecycle state, so a client that has read the resource recently must prove it is not acting on a stale read. Each requires a dedicated expectation field, and each rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412):

- Re-quoting a press order requires `expected_press_order_version` carrying the order's current `version`. A re-quote legitimately supersedes the prior quote while the order remains `QUOTED`, so a second sequential re-quote faces no state precondition; instead, if another writer has advanced the order's `version` since the client last read it, the re-quote is rejected with `ERR_STALE_VERSION`, preventing the client from silently overwriting a quote it never observed.
- Revising a release's street date requires `expected_release_version` matching the release's current `version`. Date revisions supersede the prior date and are always permitted while the release is not `FULFILLED`; a revision whose `expected_release_version` lags the release's current `version` — advanced by prior revisions or by the first-confirm cascade that moves a release from `SETUP` to `IN_PRODUCTION` — is rejected with `ERR_STALE_VERSION`.
- Revising a customer's credit limit requires `expected_customer_version` matching the customer's current `version`. Such revisions supersede the prior limit and are always permitted for an existing customer; a revision carrying a stale `expected_customer_version` — the version having advanced through prior revisions or credit-status transitions — is rejected with `ERR_STALE_VERSION`.

The order-confirmation and explicit schedule-commit writes also require `expected_press_order_version`, as described in their workflow sections. Endpoints not named here or in those sections take no version-expectation field at all.

### 2.8. Nested Resource Retrieval and Existence Checking

When an endpoint path contains a resource identifier, the system validates that the identifier exists before doing any other work on it, and when a path chains identifiers — an order followed by one of its tooling jobs, test pressings, print jobs, quality reports, slots, delay notices, or inventory lots — existence is validated strictly left to right: the order is resolved before its children, and the first identifier that does not exist determines the error. Each resource type has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_PRESS_ORDER_NOT_FOUND`, `ERR_TOOLING_JOB_NOT_FOUND`, `ERR_TEST_PRESSING_NOT_FOUND`, `ERR_PRINT_JOB_NOT_FOUND`, `ERR_PRESS_LINE_NOT_FOUND`, `ERR_PLATING_BATH_NOT_FOUND`, `ERR_QC_REPORT_NOT_FOUND`, `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND`. Identifiers referenced in a request body — a `release_id`, a `customer_id`, a `distributor_customer_id`, or a `plating_bath_id` — must likewise exist and fail with the corresponding not-found error.

### 2.9. Request Validation Order

When several checks could reject the same request, the system evaluates them in a fixed priority order, and the first failure determines the error returned. The order is:

1. Authentication context — missing or invalid `X-User-ID` / `X-User-Role`, rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, on every endpoint.
2. Authorization — role not in the endpoint's permitted set, or an entity-backed `Customer` acting on a release it does not own, rejected with `ERR_UNAUTHORIZED_ROLE`, on every endpoint.
3. Existence — path identifiers left to right, then body-referenced identifiers, rejected with the matching not-found error.
4. Request shape — missing required fields, wrong types, invalid enum members, non-positive quantities, slot hours outside the owning line's bookable range, a `weight_gram` other than 140 or 180, or `sides` other than 1 or 2, rejected with `ERR_INVALID_REQUEST` on every write endpoint.
5. State preconditions — the target resource is not in the exact from-state the requested transition requires, rejected with `ERR_ORDER_INVALID_STATE`, `ERR_TOOLING_JOB_INVALID_STATE`, `ERR_TEST_PRESSING_INVALID_STATE`, `ERR_PRINT_JOB_INVALID_STATE`, `ERR_QC_REPORT_ALREADY_DECIDED`, `ERR_SHIPMENT_INVALID_STATE`, or `ERR_INVOICE_INVALID_STATE` as appropriate to the resource.
6. Segregation of duties — a quality decision attempted by the inspector who filed the report, rejected with `ERR_SEGREGATION_OF_DUTIES`; this check applies only to quality decisions.
7. Linked-entity status gates — a suspended customer on confirm or shipment creation (`ERR_CUSTOMER_SUSPENDED`), stampers not ready at test-pressing creation (`ERR_STAMPERS_NOT_READY`), undelivered print work or a HOLD outcome at quality acceptance (`ERR_PRINT_JOBS_NOT_DELIVERED`, `ERR_QC_HOLD_REQUIRES_REPRESS`). These gates guard exactly four operations: order confirmation, shipment creation, test-pressing creation, and the quality decision.
8. Order composition — order minimum, variant sum, per-variant minimums, and code uniqueness (`ERR_ORDER_BELOW_MINIMUM`, `ERR_VARIANT_SUM_MISMATCH`, `ERR_VARIANT_BELOW_MINIMUM`, `ERR_DUPLICATE_CODE`), applying to order creation, quoting, press-line registration, plating-bath registration, and release creation.
9. Interval occupation — press-slot conflicts and changeover buffering (`ERR_SLOT_OVERLAP`, `ERR_CHANGEOVER_BUFFER_VIOLATION`, `ERR_MAINTENANCE_WINDOW_CONFLICT`) and bath-booking conflicts (`ERR_BATH_TIME_CONFLICT`, `ERR_BATH_RINSE_GAP_VIOLATION`), applying to schedule commits, maintenance-window booking, and tooling advances into plating.
10. Temporal rules — lead time at order creation and press-start date gating (`ERR_LEAD_TIME_VIOLATION`, `ERR_PRESS_DATE_NOT_REACHED`), applying to order creation and production events.
11. Credit availability at confirmation — rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.
12. Capacity and balance quotas — line daily capacity, slot unit feasibility, zone receiving capacity, and payment/memo balance caps (`ERR_LINE_DAILY_CAPACITY_EXCEEDED`, `ERR_SLOT_UNITS_MISMATCH`, `ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED`, `ERR_PAYMENT_EXCEEDS_BALANCE`), applying to schedule commits, stock events, payments, and credit memos.

A quality decision therefore surfaces a segregation-of-duties failure before a HOLD-outcome mismatch, and a schedule commit surfaces a slot overlap before a daily-capacity breach; the ordering above is normative, not illustrative.

### 2.10. Cascading Consistency Across the Production Graph

A press order is the hub of a child graph — tooling jobs, test pressings, print jobs, quality reports, slots, delay notices, inventory receipts, and invoices — and the system keeps that graph consistent automatically. When a parent undergoes a transition that resolves its children (an order cancellation, a test-pressing revision that supersedes the current stamper job), the server performs the cascade itself: no client ever updates a child directly to compensate for a parent action. Every such cascade mutates each touched resource, refreshing its `updated_at` and incrementing its `version` where the resource carries one. Parent alignment runs in the other direction as well: a release's `status` is a compound of its orders' states, moving from `SETUP` to `IN_PRODUCTION` on the first order confirmation and from `IN_PRODUCTION` to `FULFILLED` once every order of the release is terminal. Slots released by a cancellation are retained for audit with `freed` set to true and are excluded from all capacity, conflict, and backlog mathematics.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts, Credit Holds, and Discount Tiers

A `CustomerServiceRep` onboards each label or distributor as a Customer by supplying a `name`, a `contact_email`, and a `credit_limit_cents` that may not be negative; the `discount_tier` (one of `STANDARD`, `SILVER`, `GOLD`, `PLATINUM`) and the `overrun_policy` (one of `EXACT_ONLY`, `ACCEPT_AND_BILL_10`, `ACCEPT_ALL_AND_BILL`) may be supplied at creation and default to `STANDARD` and `ACCEPT_AND_BILL_10` respectively. New customers begin with `status` `ACTIVE` and a `trailing_billed_cents` of zero. The customer list may be filtered by `status`, and both it and every other list accept the usual `limit` and `offset` parameters.

Discount tiers map to percentages: `STANDARD` earns nothing, `SILVER` three percent, `GOLD` five percent, and `PLATINUM` eight percent. A `BillingClerk` manages credit holds through a credit-status action: passing `action` as `SUSPEND` moves an `ACTIVE` customer to `SUSPENDED`, and `REINSTATE` returns it to `ACTIVE`; each flip increments the customer's `version`.

Credit limits change through superseding revisions rather than edits. A `CustomerServiceRep` posts a revision carrying `new_credit_limit_cents` and the OCC guard described in §2.7; the revision may optionally restate the customer's `discount_tier` at the same time. This is the only place staff assign tiers, and the governing principle is strict temporal order: a quote snapshots the customer's tier percentage at quote time (zero if the customer is `SUSPENDED` then), an invoice prices its lines from that snapshot — never from the customer's current tier — and only after an invoice is issued does its `net_cents` accrue into `trailing_billed_cents`. That trailing total informs future tier assignments made by staff; it never re-rates an existing quote or invoice, and no retroactive recomputation of any kind is performed.

### 3.2. Releases and Press Order Intake

Work begins when a `CustomerServiceRep` registers a Release for a customer, supplying `customer_id`, a `catalog_number` unique within that customer's catalog (a duplicate is rejected with `ERR_DUPLICATE_CODE`), a `title`, a `format` of `LP`, `EP`, or `SINGLE_7`, a `weight_gram` of exactly 140 or 180, and a `release_date` street date. The format also fixes the warehousing palletization used later: an `LP` packs 100 units per pallet, an `EP` 150, and a `SINGLE_7` 300. A new release starts in `SETUP` with `risk_level` `ON_TRACK`. The release list may be filtered by `customer_id`.

Against a release, the representative opens a press order by posting the `release_id`, the `quantity_ordered`, the record's `sides` (1 or 2, defaulting to 2), a `plating_route` of `TWO_STEP` or `THREE_STEP` (defaulting to `TWO_STEP`; the choice is informational and does not alter stamper mathematics), and a `variants` array whose entries each pair a `color_config` with a `quantity`. Five color configurations exist — `BLACK`, `SOLID_COLOR`, `SPLATTER`, `MARBLED`, and `PICTURE_DISC` — and they group into three families: `BLACK` and `SOLID_COLOR` form the `STANDARD` family, `SPLATTER` and `MARBLED` form `SPECIAL_EFFECT`, and `PICTURE_DISC` stands alone as `PICTURE`. Composition rules are strict: the order must be for at least 100 units (`ERR_ORDER_BELOW_MINIMUM`), the variant quantities must sum exactly to `quantity_ordered` (`ERR_VARIANT_SUM_MISMATCH`), and each variant must meet its configuration minimum — a single unit suffices for `BLACK`, while `SOLID_COLOR`, `SPLATTER`, and `MARBLED` each require at least 100 and `PICTURE_DISC` at least 200 (`ERR_VARIANT_BELOW_MINIMUM`). An optional `overrun_policy` on the order overrides the customer's default at invoice time; when absent (null), the customer's policy applies. An optional `requested_completion_date`, when present, must fall at least twenty-one days — three full weeks — after the current logical date, or intake is rejected with `ERR_LEAD_TIME_VIOLATION`.

Creation stamps the order with a plant-wide monotonic `intake_seq` beginning at 1, and derives two facts that govern later stages. The `tolerance_pct` is the strictest quality tolerance across the order's variants: `BLACK` tolerates 5.0 percent rejects, `SOLID_COLOR` 6.0, `SPLATTER` 8.0, `MARBLED` 8.0, and `PICTURE_DISC` 12.0, and the smallest applicable value wins. The `color_family` is the family of the largest-quantity variant, ties broken by the variant that appears first in the array; it later drives changeover buffering on the schedule. A fresh order holds `production_status` `DRAFT` and `billing_status` `UNBILLED` — two parallel dimensions on the same row, the first driven by the production pipeline and the second only by invoicing events. Orders may be listed with filters on `release_id` and `production_status`.

Each release carries a continuously recomputed risk projection, readable through its `risk_level`, `projected_completion_date`, and `slack_days`. Every order's projected completion is estimated from its pipeline position: an order that is `SCHEDULED` or further along projects to the day after its latest slot date; a `QUEUED` order that has never been repressed projects to today plus 21 days, while one that has been repressed at least once projects to today plus 21 days plus a further 10 days of repress delay; an order in `TOOLING` after a test-pressing revision projects to today plus 35 days plus 7 days for each revision round; and other pre-queue stages carry stage lead times of 45 days for `CONFIRMED`, 35 for `TOOLING`, 28 for `AWAITING_TP_APPROVAL`, 3 for `PRESSING`, and 2 for `QC_REVIEW`. An order's projection also waits on its print work: it is the later of the press projection and, across the order's non-`CANCELLED` print jobs, the latest `due_date` plus 3 days of print transit. The release's `projected_completion_date` is the latest projection across its non-terminal orders — null when none remain open — and `slack_days` is `release_date` minus that projection in whole days, negative when late. The `risk_level` is `ON_TRACK` when slack is at least 14 days, `AT_RISK` when slack is zero or more but under 14, and `LATE` when slack is negative. Whenever a recompute worsens the level, the system appends a DelayNotice recording the `release_id`, the `press_order_id` of the order whose recompute worsened the outlook, the `cause` (one of `TP_REVISION`, `REPRESS`, `SCHEDULE`, or `DATE_REVISION`), the `prior_level`, the strictly worse `new_level`, and a human-readable `message`; improvement never generates a notice. A street-date change is itself a superseding revision: the representative supplies `new_release_date`, a `reason`, and the OCC guard, the release's `version` increments, and the risk recompute runs with cause `DATE_REVISION`. Delay notices are retrievable per release or per order.

### 3.3. Quoting, Confirmation, and Order Cancellation

Quoting converts a `DRAFT` order into a priced offer. A `CustomerServiceRep` requests a quote with the OCC guard field `expected_press_order_version`; the request is rejected with `ERR_STALE_VERSION` when that value does not match the order's current `version` — the classic case being a re-quote of an already-`QUOTED` order that another writer has moved on. The variant composition rules of §3.2 are re-enforced at quote time. A successful quote moves the order `DRAFT` → `QUOTED`, snapshots `discount_pct_snapshot` from the customer's tier (zero if the customer is `SUSPENDED`), and computes seven quote components, each persisted on the order.

The price builds in four components plus a subtotal, discount, and total. The pressing component, `quote_pressing_cents`, prices the ordered quantity on marginal tiers: the first 299 units at 320 cents each, units 300 through 999 (the next 700 units) at 275 each, units 1000 through 4999 (the next 4000) at 240 each, and every unit from 5000 onward at 210. The surcharge component, `quote_surcharge_cents`, sums a per-variant charge and a weight charge: each variant line contributes the greater of its quantity times its per-unit color surcharge and a 5000-cent minimum — except `BLACK`, whose per-unit surcharge is zero and which never incurs the minimum — with per-unit surcharges of 0 for `BLACK`, 35 for `SOLID_COLOR`, 55 for `SPLATTER`, 65 for `MARBLED`, and 120 for `PICTURE_DISC`; the weight charge is the full ordered quantity times 0 cents for 140-gram pressings or 25 cents for 180-gram. The tooling component, `quote_tooling_cents`, is 17500 cents per side for lacquer cutting plus one stamper fee of 30000 cents per side for every 1000-unit stamper life the ordered quantity requires, with the stamper count rounded up to a whole stamper. The setup component, `quote_setup_cents`, is a flat 40000 cents per order plus 15000 cents for each variant whose configuration is not `BLACK`. The `quote_subtotal_cents` is the sum of those four components; the `quote_discount_cents` is the subtotal multiplied by the snapshotted tier percentage, rounded half-up to whole cents; and the `quote_total_cents` is the subtotal minus the discount. Re-quoting a `QUOTED` order recomputes every component and the snapshot, superseding the prior quote in place (`QUOTED` → `QUOTED`), and every quote or re-quote increments the order's `version`.

Confirmation belongs to the customer. A `Customer` confirms its own quoted order by presenting `expected_press_order_version`; the order must be `QUOTED` (otherwise `ERR_ORDER_INVALID_STATE`), the version must match (otherwise `ERR_STALE_VERSION`), the customer must be `ACTIVE` (otherwise `ERR_CUSTOMER_SUSPENDED`), and the confirmation must pass a credit check: the customer's outstanding balance — the sum, across the customer's invoices in `ISSUED` or `PARTIALLY_PAID` status, of `net_cents` less `paid_cents` less `credited_cents` — plus this order's `quote_total_cents` may not exceed `credit_limit_cents`, with equality permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. On success the order moves `QUOTED` → `CONFIRMED` and its `version` increments; the first confirmation on a release additionally flips the release `SETUP` → `IN_PRODUCTION` and increments the release's `version` as well.

Cancellation is a `CustomerServiceRep` action available from any pre-`PRESSING` state — attempting it once the order is `PRESSING`, `QC_REVIEW`, or beyond is rejected with `ERR_ORDER_INVALID_STATE`. The fee scales with sunk work, and the resulting `cancel_fee_cents` is recorded on the order: cancelling from `DRAFT` or `QUOTED` is free; from `CONFIRMED` the fee is ten percent of `quote_total_cents`, rounded half-up; from `TOOLING` or `AWAITING_TP_APPROVAL` it is twenty-five percent; from `QUEUED` or `SCHEDULED` it is fifty percent. Any positive fee automatically creates a `CANCELLATION_FEE` invoice in `ISSUED` status whose gross and net both equal the fee with zero discount, moving the order's billing dimension from `UNBILLED` to `INVOICED`. The cancellation also resolves the child graph: every non-terminal tooling job is moved to `CANCELLED`, every non-terminal test pressing to `SUPERSEDED`, and every non-terminal print job to `CANCELLED`. Cancelling a `SCHEDULED` order additionally releases its `PRODUCTION` slots — marked `freed` and excluded from all capacity math — and triggers the waitlist promotion waterfall described in §3.6. An optional `reason` may be recorded with the cancellation.

### 3.4. Tooling, Plating Baths, and the Test Pressing Loop

Once a `ProductionPlanner` starts tooling on a `CONFIRMED` order, the order moves `CONFIRMED` → `TOOLING` and the system creates the first ToolingJob: `round_number` equal to the order's `tp_round` plus one, `status` `QUEUED`, `attempt_count` zero. From there a `PressOperator` advances the job stage by stage, each advance call carrying an `event` name and incrementing the job's `version`: `START_CUT` moves `QUEUED` → `CUTTING`; `CUT_DONE` moves `CUTTING` → `AWAITING_BATH`; `START_PLATING` moves `AWAITING_BATH` → `PLATING` and books a plating bath; `PLATING_DONE` moves `PLATING` → `STAMPER_READY`. An advance event that does not match the job's current stage is rejected with `ERR_TOOLING_JOB_INVALID_STATE`.

Bath booking is its own protocol. Plating baths are registered by a `ProductionPlanner` with a unique `bath_code` (duplicates are `ERR_DUPLICATE_CODE`) and a `rinse_gap_minutes` that defaults to 30; despite the field's name, the rinse gap is expressed in hour units in this model, so the default means thirty hours. Starting plating requires a `plating_bath_id` that exists (`ERR_PLATING_BATH_NOT_FOUND`) plus `plating_start` and `plating_end` hour markers, which the job records. Bath bookings are closed intervals — both endpoints inclusive — and are checked against every other booking on the same bath held by a job currently in `PLATING`: if the new booking's start falls on or before an existing booking's end while the existing start falls on or before the new end, the booking is rejected with `ERR_BATH_TIME_CONFLICT`; even without overlap, the new booking must begin no earlier than one rinse gap after each existing booking's end, or end no later than one rinse gap before each existing booking's start, otherwise it is rejected with `ERR_BATH_RINSE_GAP_VIOLATION`. Touching endpoints count as conflicts here, and the rinse gap is unconditional — it applies after every booking regardless of job type.

A `MARK_FAILED` advance from `CUTTING` or `PLATING` moves the job to `FAILED`, increments `attempt_count`, and records the operator's `defect_note`; a plating-stage failure additionally releases the bath booking, clearing `plating_bath_id`, `plating_start`, and `plating_end`. While `attempt_count` remains below 3 the job automatically requeues itself `FAILED` → `QUEUED` for another try; a third failure leaves the job resting in `FAILED`. When a test-pressing revision calls for a re-cut, the system supersedes the whole job row — `STAMPER_READY` → `SUPERSEDED` — and an order cancellation cascades any job in `QUEUED`, `CUTTING`, `AWAITING_BATH`, `PLATING`, or `FAILED` to `CANCELLED`. The jobs of an order, and the jobs booked on a bath, are both listed through their respective parent resources.

With stampers ready, a `PressOperator` produces a test pressing of `quantity` between 1 and 20 copies. Creation requires the order to be in `TOOLING` with its latest tooling job in `STAMPER_READY` — otherwise `ERR_ORDER_INVALID_STATE` or `ERR_STAMPERS_NOT_READY` respectively — and it increments the order's `tp_round`, stamps the new TestPressing's `round_number` with that value, and supersedes any prior round still resting in `REVISION_REQUESTED`. A `ProductionPlanner` then ships the pressing to the customer, moving it `PRODUCED` → `UNDER_REVIEW` and the order `TOOLING` → `AWAITING_TP_APPROVAL` (shipping from any other state is `ERR_TEST_PRESSING_INVALID_STATE`).

The customer's review decides the loop. Supplying `decision` `APPROVE` moves the pressing `UNDER_REVIEW` → `APPROVED` and cascades the order `AWAITING_TP_APPROVAL` → `QUEUED`, followed by a risk recompute with cause `SCHEDULE` and a DelayNotice if the outlook worsened. Supplying `REQUEST_REVISION` moves the pressing to `REVISION_REQUESTED`, cascades the order back `AWAITING_TP_APPROVAL` → `TOOLING`, supersedes the current tooling job and opens a fresh re-cut job with `round_number` one higher in `QUEUED`, and recomputes risk with cause `TP_REVISION` — the seven-day-per-revision delay of §3.2 — appending a DelayNotice on worsening. Review remarks are captured in the pressing's `decision_notes`. Only the owning customer may review (ownership per §2.1), reviewing a pressing not in `UNDER_REVIEW` is rejected with `ERR_TEST_PRESSING_INVALID_STATE`, and rounds beyond the first each carry a revision fee at invoice time (§3.9).

### 3.5. Print Coordination for Jackets, Sleeves, Inserts, and Labels

Physical packaging runs on its own track. A `CustomerServiceRep` opens a PrintJob on an order with a `component` of `JACKET`, `INNER_SLEEVE`, `INSERT`, or `LABEL`, a print-run `quantity` that must be at least the parent order's `quantity_ordered`, the external vendor's `printer_name`, and the printer's committed `due_date`. The job begins in `CREATED`; plant-side progress advances it through an `event` of `DISPATCH` (`CREATED` → `AT_PRINTER`) or `PROOFS_IN` (`AT_PRINTER` → `PROOF_REVIEW`), while `DELIVER` moves a `PRINTING` job to `DELIVERED`. Events out of stage order are rejected with `ERR_PRINT_JOB_INVALID_STATE`.

Proofs belong to the customer. From `PROOF_REVIEW`, a `decision` of `APPROVE` — optionally annotated with `notes` — moves the job to `PRINTING`; `REQUEST_CHANGES` loops it back `PROOF_REVIEW` → `AT_PRINTER`, increments `proof_round`, and triggers a risk recompute with cause `SCHEDULE` so that slipping print dates surface through the release's `risk_level` and, on worsening, a DelayNotice. An order cancellation cascades any print job in `CREATED`, `AT_PRINTER`, or `PROOF_REVIEW` to `CANCELLED`. Print delivery gates completion of the whole order: quality acceptance (§3.7) refuses to complete an order while any non-`CANCELLED` print job remains undelivered.

### 3.6. Press Lines, Slot Booking, and Plant Capacity

Press capacity is modeled as lines and hours. A `ProductionPlanner` registers each PressLine with a unique `line_code` (duplicates rejected with `ERR_DUPLICATE_CODE`), a `tonnage_class` of `STANDARD` or `HEAVY`, the `hours_per_day` bookable each calendar day, and a `daily_unit_capacity` ceiling on planned units per line per day; the line's effective hourly rate is its `daily_unit_capacity` divided by its `hours_per_day`, rounded up to the next whole unit per hour. Maintenance windows are booked on a line as `MAINTENANCE` PressSlots — `press_order_id` left null, `planned_units` zero — by supplying `date`, `start_hour`, `end_hour`, and an optional `reason`. Slots on a line may be listed and filtered by `date`.

Committing a `QUEUED` order to the schedule is the plant's central constrained write. A `ProductionPlanner` presents `expected_press_order_version` (a mismatch is `ERR_STALE_VERSION`) and a `slots` array describing the requested production windows on chosen lines and dates. The commit must satisfy four families of rules. First, unit feasibility: each slot's `planned_units` may not exceed its length in hours multiplied by the line's hourly rate, and the committed slots must plan at least as many units as the order still lacks — `quantity_ordered` less any `accepted_units` already banked — so a repressed order may legitimately commit a top-up run covering only its shortfall; either failure is `ERR_SLOT_UNITS_MISMATCH`. Second, interval occupation on each line and date: `PRODUCTION` slots are half-open intervals — the end hour is exclusive — so two such slots conflict exactly when each starts strictly before the other ends (`ERR_SLOT_OVERLAP`); back-to-back slots are permitted only between slots of the same `color_family`, and slots of different families must leave a one-hour changeover gap between the earlier slot's end and the later slot's start (`ERR_CHANGEOVER_BUFFER_VIOLATION`); `MAINTENANCE` windows are closed intervals, and a production slot conflicts with a maintenance window whenever the production start falls on or before the maintenance end while the maintenance start falls strictly before the production end — merely touching a maintenance endpoint already conflicts (`ERR_MAINTENANCE_WINDOW_CONFLICT`). Hour bounds differ by kind: production hours must start at zero or later, end strictly after the start, and end no later than the line's `hours_per_day`, while maintenance hours may have equal start and end but must end strictly before `hours_per_day`; out-of-range hours are `ERR_INVALID_REQUEST`. Third, daily capacity: the sum of `planned_units` on a line and date may not exceed the line's `daily_unit_capacity` (`ERR_LINE_DAILY_CAPACITY_EXCEEDED`). Fourth, the order must actually be `QUEUED` (otherwise `ERR_ORDER_INVALID_STATE`). On success the system creates one `PRODUCTION` PressSlot per requested window — `slot_kind` `PRODUCTION`, `color_family` copied from the order, `freed` false — moves the order `QUEUED` → `SCHEDULED`, increments its `version`, and recomputes release risk with cause `SCHEDULE`.

Capacity pressure is visible through a per-line backlog read exposing `booked_hours`, `optimistic_backlog_days`, and `conservative_backlog_days` alongside the `press_line_id`. Booked hours total the lengths of the line's unfreed `PRODUCTION` slots dated today or later, plus one changeover hour for every adjacent pair of different-family slots on the same date. The optimistic figure divides booked hours by `hours_per_day`, rounded half-up to two decimal places, and backs customer-facing promise dates. The conservative figure inflates booked hours by twenty-five percent, adds a repress-queue term — the sum, over each order of this line currently `QUEUED` after at least one repress, of that order's `quantity_ordered` divided by the line's hourly rate and rounded up to whole hours — divides the total by `hours_per_day`, and rounds half-up to two decimals; identical slot data therefore yields two deliberately different backlog answers, one for promises and one for internal risk.

When a `SCHEDULED` order is cancelled, its freed windows do not simply vanish: the system runs a waitlist promotion waterfall. The candidate pool is every order in `QUEUED` — regardless of repress history — except the cancelled one. Candidates rank by customer tier weight descending (`PLATINUM` weighs 40, `GOLD` 30, `SILVER` 20, `STANDARD` 10), ties broken by the order's `created_at` ascending and then by `intake_seq` ascending, never by identifier. Scanning in that rank order, a candidate is promoted exactly when its required hours — its `quantity_ordered` divided by the hourly rate of the freed window's line, rounded up — fit inside one single freed window on that line and date; a promoted order receives a new `PRODUCTION` slot covering exactly those required hours from the window's start, the freed remainder shrinks accordingly, the candidate moves `QUEUED` → `SCHEDULED`, its release risk is recomputed with cause `SCHEDULE`, and the scan continues against the remaining windows. An empty candidate pool or a pool nothing fits is not an error — the capacity simply returns to free.

### 3.7. Pressing Runs, Quality Control, and the Repress Loop

Floor execution is driven by production events fired by a `PressOperator`, each call supplying an `event` of `START_PRESSING` or `COMPLETE_PRESSING`. `START_PRESSING` moves a `SCHEDULED` order to `PRESSING`, but only once the logical clock's date has reached the order's earliest slot date; an earlier attempt is rejected with `ERR_PRESS_DATE_NOT_REACHED`. `COMPLETE_PRESSING` moves a `PRESSING` order to `QC_REVIEW`. Each event increments the order's `version`, and firing either event from the wrong state is `ERR_ORDER_INVALID_STATE`.

Quality control is deliberately split across two roles. A `QaInspector` files a report against an order in `QC_REVIEW`, recording `units_pressed` (strictly positive) and `units_rejected` (no fewer than zero and no more than were pressed; shape violations are `ERR_INVALID_REQUEST`) along with optional `defect_notes`. The system records the filer's identity in `filed_by`, snapshots the order's current tolerance into `tolerance_pct_snapshot`, and computes the `reject_rate_pct` — one hundred times the rejected units divided by the pressed units, rounded half-up to two decimal places. The `outcome` is `HOLD` exactly when that rate is strictly greater than the snapshot tolerance; a rate equal to the tolerance still yields `PASS`. A fresh report is `FILED` with `decision` and `fault` both `NONE`.

The decision belongs to a `ProductionManager`, and never to the filer: if the deciding `X-User-ID` matches the report's `filed_by`, the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`, and the deciding identity is recorded as `decided_by`. Deciding a report already `DECIDED` is `ERR_QC_REPORT_ALREADY_DECIDED`. A `decision` of `ACCEPT` is lawful only when the outcome is `PASS` — accepting a `HOLD` report is rejected with `ERR_QC_HOLD_REQUIRES_REPRESS` — and only when every non-`CANCELLED` print job of the order is `DELIVERED` (`ERR_PRINT_JOBS_NOT_DELIVERED`). Acceptance completes the order (`QC_REVIEW` → `COMPLETED`) and triggers a wide cascade: the order's `accepted_units` grows by the run's good units (pressed minus rejected), while `pressed_units_total` and `rejected_units_total` grow by the run's pressed and rejected counts; the good units are credited to inventory by finding or creating the release's zone-`A` InventoryLot, incrementing its `on_hand_units` and `received_units_cum` by the accepted count and assigning it the next `receipt_seq`; a backorder sweep (§3.8) then promotes waiting `PLANNED` shipments of the release; release risk is recomputed; and the release moves to `FULFILLED` once every one of its orders is terminal.

A `decision` of `REPRESS` requires a `fault` of `PLANT` or `CUSTOMER` (an absent or other value fails request validation), and may be accompanied by a `note`. Repress loops the order `QC_REVIEW` → `QUEUED`: `repress_round` increments, `repress_fault` records the fault, the run's pressed and rejected totals accumulate as on acceptance, and the run's good units are banked into `accepted_units` — the repress re-covers only the rejected shortfall, never the good units. The risk recompute applies the ten-day repress delay with cause `REPRESS` and appends a DelayNotice on worsening. The fault attribution matters later: it steers both the stamper charges and the flat repress adjustment on the final invoice (§3.9).

### 3.8. Warehousing, Inventory Lots, and Distributor Shipments

Finished stock lives in InventoryLots. A `WarehouseManager` opens a lot for a release in a `zone` of `A`, `B`, or `C`; the lot is stamped with the release's next monotonic `receipt_seq` (beginning at 1, the FIFO tie-break after `created_at`), and its counters — `on_hand_units`, `allocated_units`, `shipped_units_cum`, `damaged_units_cum`, `received_units_cum` — all begin at zero. One invariant anchors the lot forever: units received always equal units on hand plus units allocated plus units shipped plus units damaged. Lots may be listed with filters on `release_id` and `zone`.

Stock events mutate a lot, each call naming an `event` of `RECEIVE` or `DAMAGE_WRITE_OFF`. A `RECEIVE` event adds `quantity` units to `on_hand_units` and `received_units_cum`, optionally dated by `event_date` (defaulting to the logical clock's date), and is subject to a zone receiving budget: the event's pallet count — its quantity divided by the release format's units-per-pallet, rounded up — plus the pallets of every other `RECEIVE` into the same zone on the same date may not exceed the zone's daily budget of 40 pallets for zone `A`, 25 for `B`, and 15 for `C`, or the event is rejected with `ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED`. A successful receive then runs the backorder sweep. A `DAMAGE_WRITE_OFF` event removes `quantity` units from `on_hand_units` into `damaged_units_cum` and may not exceed the units on hand (`ERR_INVALID_REQUEST`). Every read of a lot also exposes two deliberately divergent storage-fee figures computed over the trailing thirty days ending at the logical clock: `storage_daily_accrual_cents` sums, over each day in the window, that day's on-hand pallets — on-hand units divided by units-per-pallet, rounded up — times 55 cents; `storage_monthly_statement_cents` instead averages the daily pallet counts across the days in the month, rounds that average half-up to two decimals, multiplies by 1500 cents per pallet, and floors the result at a 5000-cent monthly minimum, taking the larger of the two.

Shipments move stock to distributors. A `CustomerServiceRep` creates a Shipment with the `release_id`, the receiving account's `distributor_customer_id`, a positive `quantity`, and an advisory `requested_ship_date`; the distributor must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`). Allocation is FIFO and all-or-nothing at creation: the candidate lots are the release's lots with positive `on_hand_units`, ordered by `created_at` ascending and then `receipt_seq` ascending — never by identifier — and if the total on hand across those lots is less than the shipment's quantity, the shipment stays `PLANNED` with empty `allocations`; otherwise the system builds the `allocations` array of lot-and-quantity pairs (splitting across lots as needed), moves the shipment straight to `ALLOCATED`, and shifts each allocated quantity from `on_hand_units` to `allocated_units` on its lot. The same allocator runs as a sweep whenever stock arrives or is freed: the release's `PLANNED` shipments are walked in `created_at` ascending, each is allocated in full while it fits, and shipments that do not fit are skipped without blocking later ones. A `WarehouseManager` then advances the shipment one step per call — `ALLOCATED` → `PICKED` → `SHIPPED` — and shipping settles the lots: each allocated quantity leaves `allocated_units` and accrues into `shipped_units_cum`. Cancellation is possible from `PLANNED` or `ALLOCATED`; cancelling an allocated shipment deallocates its quantities back to `on_hand_units` and runs the sweep again, and an optional `reason` may be supplied. Wrong-state advances or cancellations are `ERR_SHIPMENT_INVALID_STATE`. Shipments may be listed with filters on `release_id`, `distributor_customer_id`, and `status`.

### 3.9. Invoicing, Payments, and Credit Memos

Billing is the order's second, parallel dimension. Issuing the final invoice is a `BillingClerk` action on a `COMPLETED` order — any other production state is rejected with `ERR_INVOICE_INVALID_STATE`, and exactly one `STANDARD` invoice may ever exist for an order, a second attempt drawing `ERR_ORDER_INVALID_STATE`. Issuance moves the billing dimension `UNBILLED` → `INVOICED` and builds the invoice's `lines` — seven entries in the fixed order pressing, surcharge, tooling, setup, test-pressing revision, underrun, and repress, each carrying `label`, `gross_cents`, `discount_cents`, and `net_cents` — according to the final-price calculation below.

Billed units come first, governed by the overrun policy: the order's own `overrun_policy` when set, otherwise the customer's. Under `EXACT_ONLY` the billed quantity is the smaller of `accepted_units` and `quantity_ordered`. Under `ACCEPT_AND_BILL_10` the cap is `quantity_ordered` increased by ten percent and rounded down to a whole unit, and the billed quantity is the smaller of `accepted_units` and that cap. Under `ACCEPT_ALL_AND_BILL` the billed quantity is simply `accepted_units`. Overrun beyond a cap is neither billed nor shipped-invoiced — it remains in the inventory lot. The pressing gross prices those billed units on the same marginal tier table used at quote time. The surcharge gross is the billed quantity times the sum of two per-unit surcharges: the dominant variant's color surcharge — dominant meaning the largest-quantity variant, ties broken by the first variant in the array — and the release's weight surcharge. The tooling gross is the quoted `quote_tooling_cents`, plus, when the latest repress fault was `CUSTOMER`, one 30000-cent stamper fee per side for each repress round. The setup gross is the quoted `quote_setup_cents`. The test-pressing revision gross is 45000 cents for every round beyond the first — zero when `tp_round` is one or less. The underrun line credits the customer when accepted units fall short: if `accepted_units` is less than ninety percent of `quantity_ordered` rounded down, the shortfall is that floor minus `accepted_units`, and the line's gross is negative — the shortfall times the pressing gross divided by the billed quantity, rounded half-up, then negated (applicable when the billed quantity is positive). The repress line carries a flat 150000-cent adjustment per repress round, charged against the plant when `repress_fault` is `PLANT` (a negative line) and passed to the customer when it is `CUSTOMER` (a positive line); no repress, no line adjustment.

Rounding on the invoice is pinned per line and is not negotiable: for each of the seven lines in order, the line's discount is its gross multiplied by the order's `discount_pct_snapshot`, rounded half-up to whole cents, and the line's net is its gross minus its discount. The invoice's `gross_cents` is the sum of the line grosses, its `discount_cents` the sum of the line discounts, and its `net_cents` the sum of the line nets; computing one discount on the grand total instead is a different algorithm and yields different cents. Immediately after issuance — never before — the customer accrues the invoice's `net_cents` into `trailing_billed_cents`, which per §3.1 influences only future tier decisions and re-rates nothing retroactively.

Payments and credit memos settle the invoice. A payment of `amount_cents` against an `ISSUED` or `PARTIALLY_PAID` invoice (any other status is `ERR_INVOICE_INVALID_STATE`) adds to `paid_cents` and may not exceed the remaining balance — `net_cents` less `paid_cents` less `credited_cents` — on pain of `ERR_PAYMENT_EXCEEDS_BALANCE`; a payment short of the remaining balance moves the invoice `ISSUED` → `PARTIALLY_PAID` (mirroring the order's billing dimension `INVOICED` → `PARTIALLY_PAID`), and one that completes the balance moves it to `PAID` from either state (billing dimension to `PAID`). A credit memo of `amount_cents` with a `reason` posts a new self-referential Invoice row of `kind` `CREDIT_MEMO` whose `parent_invoice_id` names the invoice it credits, adds the amount to the parent's `credited_cents` under the same remaining-balance cap, and — when cumulative credits reach the invoice's `net_cents`, as a memo covering the full balance of an unpaid invoice does — moves the parent `ISSUED` or `PARTIALLY_PAID` to `CREDITED` and the order's billing dimension to `CREDIT_CLOSED`. Invoices carry a `kind` of `STANDARD`, `CANCELLATION_FEE`, or `CREDIT_MEMO` and may be listed with filters on `press_order_id`, `customer_id`, `parent_invoice_id`, and `status`; an order's billing dimension reaches its terminal states `PAID` or `CREDIT_CLOSED` only through these settlement events, independently of where production stands.

## 4. Endpoint Definitions

Operations that create a new resource — a customer, release, press order, test pressing, print job, press line, maintenance window, plating bath, quality report, inventory lot, shipment, invoice, or credit memo — return `201 Created`. Operations that modify an existing resource in place — quotes, confirmations, tooling starts, schedule commits, production events, cancellations, advances, reviews, decisions, stock events, payments, credit-limit revisions, credit-status changes, date revisions, and clock control — return `200 OK`. Successful responses return the created or modified resource in the envelope's `data` field, except the clock operation which carries no resource payload.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical test clock | PlatformAdmin |
| POST | `/customers` | Create a customer account | CustomerServiceRep |
| GET | `/customers` | List customers | Any |
| GET | `/customers/{id}` | Get a customer | Any |
| POST | `/customers/{id}/credit-limit-revisions` | Supersede the customer's credit limit (OCC-guarded) | CustomerServiceRep |
| POST | `/customers/{id}/credit-status` | Suspend or reinstate a credit hold | BillingClerk |
| POST | `/releases` | Create a release for a customer | CustomerServiceRep |
| GET | `/releases` | List releases | Any |
| GET | `/releases/{id}` | Get a release | Any |
| POST | `/releases/{id}/date-revisions` | Revise the street date (OCC-guarded) | CustomerServiceRep |
| GET | `/releases/{id}/risk` | Computed read of release-date risk | Any |
| GET | `/releases/{id}/delay-notices` | List delay notices of a release | Any |
| POST | `/press-orders` | Create a press order with variant configuration | CustomerServiceRep |
| GET | `/press-orders` | List press orders | Any |
| GET | `/press-orders/{id}` | Get a press order | Any |
| POST | `/press-orders/{id}/quotes` | Compute or supersede a price quote (OCC-guarded) | CustomerServiceRep |
| POST | `/press-orders/{id}/confirm` | Customer confirms the quoted order | Customer |
| POST | `/press-orders/{id}/start-tooling` | Begin tooling; creates ToolingJob round 1 | ProductionPlanner |
| POST | `/press-orders/{id}/schedule-commits` | Commit explicit press slots for a queued order (OCC-guarded) | ProductionPlanner |
| POST | `/press-orders/{id}/production-events` | START_PRESSING or COMPLETE_PRESSING | PressOperator |
| POST | `/press-orders/{id}/cancel` | Cancel a pre-pressing order; tiered fee and cascades | CustomerServiceRep |
| GET | `/press-orders/{id}/slots` | List slots of an order | Any |
| GET | `/press-orders/{id}/tooling-jobs` | List tooling jobs of an order | Any |
| GET | `/press-orders/{id}/test-pressings` | List test pressings of an order | Any |
| GET | `/press-orders/{id}/print-jobs` | List print jobs of an order | Any |
| GET | `/press-orders/{id}/qc-reports` | List quality reports of an order | Any |
| GET | `/press-orders/{id}/delay-notices` | List delay notices attributed to an order | Any |
| GET | `/press-orders/{id}/inventory-lots` | List inventory lots received from an order | Any |
| POST | `/tooling-jobs/{id}/advance` | Advance tooling stage or mark failure | PressOperator |
| POST | `/press-orders/{id}/test-pressings` | Produce a test pressing round | PressOperator |
| POST | `/test-pressings/{id}/ship` | Ship a test pressing for customer review | ProductionPlanner |
| POST | `/test-pressings/{id}/review` | Customer review: approve or request revision | Customer |
| POST | `/press-orders/{id}/print-jobs` | Create a jacket/sleeve/insert/label print job | CustomerServiceRep |
| POST | `/print-jobs/{id}/advance` | Plant-side print progress | CustomerServiceRep |
| POST | `/print-jobs/{id}/proof-decision` | Customer proof decision | Customer |
| POST | `/press-lines` | Register a press line | ProductionPlanner |
| GET | `/press-lines` | List press lines | Any |
| GET | `/press-lines/{id}` | Get a press line | Any |
| GET | `/press-lines/{id}/slots` | List slots on a line | Any |
| GET | `/press-lines/{id}/backlog` | Computed backlog: optimistic vs conservative | Any |
| POST | `/press-lines/{id}/maintenance-windows` | Book a maintenance window | ProductionPlanner |
| POST | `/plating-baths` | Register a plating bath | ProductionPlanner |
| GET | `/plating-baths` | List plating baths | Any |
| GET | `/plating-baths/{id}` | Get a plating bath | Any |
| GET | `/plating-baths/{id}/tooling-jobs` | List tooling jobs booked on a bath | Any |
| POST | `/press-orders/{id}/qc-reports` | File a quality report for the run | QaInspector |
| POST | `/qc-reports/{id}/decision` | Decide a quality report (segregated from filer) | ProductionManager |
| POST | `/inventory-lots` | Open an inventory lot for a release in a zone | WarehouseManager |
| GET | `/inventory-lots` | List inventory lots | Any |
| GET | `/inventory-lots/{id}` | Get an inventory lot | Any |
| POST | `/inventory-lots/{id}/stock-events` | Receive stock or write off damage | WarehouseManager |
| POST | `/shipments` | Create a distributor shipment with FIFO allocation | CustomerServiceRep |
| GET | `/shipments` | List shipments | Any |
| GET | `/shipments/{id}` | Get a shipment | Any |
| POST | `/shipments/{id}/advance` | Advance one step: allocated to picked to shipped | WarehouseManager |
| POST | `/shipments/{id}/cancel` | Cancel a planned or allocated shipment | CustomerServiceRep |
| POST | `/press-orders/{id}/invoices` | Issue the final standard invoice for a completed order | BillingClerk |
| GET | `/invoices` | List invoices | Any |
| GET | `/invoices/{id}` | Get an invoice | Any |
| POST | `/invoices/{id}/payments` | Record a payment against an invoice | BillingClerk |
| POST | `/invoices/{id}/credit-memos` | Issue a credit memo against an invoice | BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_RELEASE_NOT_FOUND` | 404 Not Found |
| `ERR_PRESS_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TOOLING_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_PRESSING_NOT_FOUND` | 404 Not Found |
| `ERR_PRINT_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_PRESS_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_PLATING_BATH_NOT_FOUND` | 404 Not Found |
| `ERR_QC_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVENTORY_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_TOOLING_JOB_INVALID_STATE` | 409 Conflict |
| `ERR_TEST_PRESSING_INVALID_STATE` | 409 Conflict |
| `ERR_PRINT_JOB_INVALID_STATE` | 409 Conflict |
| `ERR_QC_REPORT_ALREADY_DECIDED` | 409 Conflict |
| `ERR_SHIPMENT_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STAMPERS_NOT_READY` | 409 Conflict |
| `ERR_PRINT_JOBS_NOT_DELIVERED` | 409 Conflict |
| `ERR_QC_HOLD_REQUIRES_REPRESS` | 409 Conflict |
| `ERR_ORDER_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_VARIANT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_VARIANT_SUM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_CHANGEOVER_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_BATH_TIME_CONFLICT` | 409 Conflict |
| `ERR_BATH_RINSE_GAP_VIOLATION` | 409 Conflict |
| `ERR_SLOT_UNITS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LEAD_TIME_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PRESS_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_LINE_DAILY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 400 Bad Request |

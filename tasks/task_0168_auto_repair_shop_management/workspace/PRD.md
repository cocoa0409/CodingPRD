# Auto Repair Shop Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Auto Repair Shop Management API, a back-office platform that runs an automotive service center end to end — from the moment a customer's vehicle rolls into a bay through the final invoice and warranty follow-up. The system models the financial and operational reality of a working shop: labor is quoted against a flat-rate book, parts are priced through a tiered markup matrix, returnable cores carry refundable deposits, technicians clock real time against jobs so their efficiency can be measured, and recommended work surfaced by a multi-point inspection must be explicitly approved, declined, or deferred by the vehicle's owner before any charge attaches to the bill.

Two concerns dominate the design. The first is **pricing correctness**: every labor and parts charge must be reproducible to the cent, whether labor is billed at flat book hours or at the actual clocked time, and whether a part is marked up at a single bracket or sliced marginally across bands. The second is **authorization and lifecycle discipline**: a repair order moves through a strict status progression, a customer must sign off on an estimate snapshot before work begins, and warranty comebacks are honored only inside a defined time-and-mileage window. The narrative below first establishes the system-wide contracts that every endpoint shares (Section 2), then walks the business workflows where the detailed rules live (Section 3), and finally summarizes the endpoint surface (Section 4) and error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly five roles: `ServiceAdvisor`, `Technician`, `Customer`, `PartsManager`, and `ShopManager`. The `ServiceAdvisor` is the front-desk writer — creating customers, vehicles, repair orders, and labor operations, scheduling bays, managing lines, driving the simpler repair-order lifecycle moves, and reviewing inspections. The `Technician` performs the physical labor: clocking time, completing labor lines, running inspections, and completing repair orders. The `Customer` is the vehicle owner who approves, declines, or defers recommended work and authorizes the estimate. The `PartsManager` owns the parts catalog and markup matrix, adds part lines, and manages core charges. The `ShopManager` is an operational superset that performs technician and bay administration, holds warranty authority and control of the test clock, and may additionally perform any operation otherwise reserved to a `ServiceAdvisor`, `Technician`, or `PartsManager` as an override.

The way `X-User-ID` binds to data differs by role. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's technician foreign key to `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning-customer foreign key to `X-User-ID`. In particular, a customer may only authorize an estimate or decide a recommended job on a repair order whose vehicle they own — an ownership violation is reported as `ERR_FORBIDDEN_FOR_ROLE`. By contrast, when `X-User-Role` is `ServiceAdvisor`, `PartsManager`, or `ShopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list-based response includes the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on each mutation. Customer, Vehicle, Technician, ServiceBay, LaborOperation, MarkupTier, RepairOrder, LaborLine, PartLine, CoreCharge, Inspection, and RecommendedJob all carry the full set — `id`, `created_at`, `updated_at`, and `version`.

Relationships between resources are expressed through foreign-key identifiers carried in request bodies and surfaced on the stored resource. The system never exposes raw schema tables to the client; instead, the workflows in Section 3 describe which identifiers a given operation expects.

### 2.5. Nested Resource Retrieval and Referential Integrity

Many paths address a resource nested beneath a parent — for example a labor line, part line, core charge, inspection, or recommended job reached through its owning repair order or inspection. When a path contains more than one identifier, the system validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request that names a labor line under a repair order that does not exist therefore fails on the repair order before the labor line is ever consulted.

Existence of path-referenced resources is checked before any body content. Once the path resolves, the system validates that foreign keys carried in the body — such as `customer_id`, `vehicle_id`, `bay_id`, `comeback_of_ro_id`, `labor_operation_id`, and `technician_id` — point at resources that actually exist; an unresolved body foreign key is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND`.

### 2.6. Validation Ordering

When several checks could fail on a single request, the system evaluates them in a fixed priority so that the returned error is deterministic. The order is: first, the user-context headers must be present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, the role must be permitted for the endpoint and, for ownership-scoped customer actions, the customer must own the vehicle (`ERR_FORBIDDEN_FOR_ROLE`); third, all path-referenced resources must exist, validated left to right (`ERR_NOT_FOUND`); fourth, body-referenced foreign keys must resolve (`ERR_REFERENCED_ENTITY_NOT_FOUND`); fifth, the body must be well-formed with required fields present and numeric fields within range (`ERR_INVALID_REQUEST`); and sixth, the target resource must be in a state where the requested transition is permitted (`ERR_INVALID_STATE`). Only after these gates pass are the domain-specific business rules of Section 3 evaluated. Each business rule carries its own dedicated error and is described alongside the workflow it guards.

### 2.7. Monetary Values, Hours, and Precision

All monetary amounts are stored as whole integer cents. Wherever a rounding step is called for, the system uses the **round-half-up** method to the nearest whole cent. Labor hours — both the flat-rate `book_hours` and the clocked `actual_hours` — are carried to three decimal places. Technician efficiency is carried to one decimal place, also rounded half up.

A rounding-order convention is pinned across all totals: each individual line is rounded first, and only then are the rounded line amounts summed. Tax is the sole exception in that it is rounded exactly once, applied to the already-summed taxable subtotal, and the grand total is then formed by plain addition of the already-rounded components without any further rounding of the sum. Section 3 specifies exactly which amounts participate in each rounding step.

### 2.8. Hierarchical Consistency and Cascades

A repair order is the root of a small tree containing its labor lines, part lines, core charges, inspections, and recommended jobs. Operations on a child frequently ripple upward: adding or completing a line, returning a core, or approving a recommended job all trigger a recomputation of the owning repair order's totals. Conversely, a state change on the repair order can drive its children — placing an order on hold pauses its in-progress labor lines and auto-closes their open clock sessions, and cancelling an order forfeits its still-charged cores. Whenever the server mutates a resource as part of such a cascade — including refreshing a computed total — that resource's `updated_at` is refreshed and its `version` is incremented, exactly as for a direct client mutation. Where the server itself drives a transition without an explicit client request on that resource (for example, a labor line moving to `PAUSED` because its order went `ON_HOLD`), the same `updated_at` and `version` semantics apply.

### 2.9. Optimistic Concurrency on Estimate Authorization

Authorizing a repair order is the one operation guarded by optimistic concurrency control. When a customer signs the estimate, the request must carry `expected_repair_order_version`, a non-optional field holding the `version` of the repair order the customer last observed. The server compares it against the repair order's current `version`. If another writer has advanced that `version` since the customer last read the order — for instance by adding a line, returning a core, or approving recommended work — the customer's view of the estimate total is stale and the authorization is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects the customer from signing against a total that has been superseded; a fresh authorization legitimately re-snapshots the grand total only when the supplied version still matches. No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Shop: Customers, Vehicles, and Reference Catalogs

Before any work is written up, the shop's reference data must exist. A `ServiceAdvisor` or `ShopManager` registers a customer with a `full_name`, a `phone` number, and an `email`. Each customer's vehicles are recorded separately: a vehicle is created with the owning `customer_id`, its `vin`, its `make`, `model`, and `model_year`, and a current `odometer_miles` reading. The VIN must be unique across all vehicles in the shop — an attempt to register a vehicle whose `vin` already exists is rejected with `ERR_DUPLICATE_VIN`. The odometer reading must be a non-negative integer (zero or greater); a negative value is a malformed body and is rejected with `ERR_INVALID_REQUEST`. A customer's vehicles can be listed by walking back from the customer.

Technicians are administered by a `ShopManager`. A technician is created with a `full_name` and an optional `skill_level`, which is a grade of `A`, `B`, or `C` and defaults to `B` when omitted. A new technician starts with `banked_flat_hours` of 0, `banked_actual_hours` of 0, and an `efficiency_pct` of null, and is not clocked into anything (`clocked_labor_line_id` is null) with no recorded `last_clock_out_at`. Service bays, also created by a `ShopManager`, carry a `bay_name` that must be unique and an optional `bay_type` of `GENERAL`, `ALIGNMENT`, or `LIFT` that defaults to `GENERAL`; a duplicate `bay_name` is rejected as a malformed request with `ERR_INVALID_REQUEST`.

Two catalogs drive pricing. The flat-rate labor catalog holds **labor operations**, each created by a `ShopManager` or `ServiceAdvisor` with a unique `op_code`, a `description`, the flat-rate `book_hours` for the operation (which must be greater than zero), and a `default_rate_cents` giving the default shop labor rate in cents per hour (which must be greater than zero). A duplicate `op_code` or a non-positive `book_hours` is rejected with `ERR_INVALID_REQUEST`. The parts markup matrix is a set of **markup tiers**, created by a `PartsManager` or `ShopManager`. Each tier has a `tier_index` (a unique, non-negative integer giving its order within the matrix, ascending by lower bound), a `lower_bound_cents` giving the inclusive lower bound of per-unit part cost the tier covers, an optional `upper_bound_cents` giving the exclusive upper bound (omitted or null marks the unbounded top tier), and a `markup_pct` giving the markup applied to the cost in that band — for example 0.40 to mean a forty-percent markup. A duplicate `tier_index` or an overlapping band is rejected with `ERR_INVALID_REQUEST`. The matrix can be listed in `tier_index` order.

### 3.2. Opening a Repair Order and Scheduling a Bay

A `ServiceAdvisor` or `ShopManager` opens a **repair order** for a `customer_id` and a `vehicle_id`, optionally supplying a `tax_rate` (the sales tax rate applied to the taxable subtotal, such as 0.0825, defaulting to 0.0) and optionally a `comeback_of_ro_id` naming an earlier order this one reworks under warranty. A new order begins in `ESTIMATE` status. Its `is_comeback` flag is computed as true exactly when `comeback_of_ro_id` is set and false otherwise. When `comeback_of_ro_id` is supplied, the warranty window described in Section 3.8 is validated at creation time. Repair orders can be listed and filtered by `customer_id`, `vehicle_id`, `bay_id`, `comeback_of_ro_id`, or `status`.

Before work can begin, the order must be assigned a bay and a time window. Scheduling is performed by a `ServiceAdvisor` or `ShopManager` and supplies a `bay_id`, a `scheduled_start`, and a `scheduled_end`; the window end must be strictly after its start, otherwise the body is malformed (`ERR_INVALID_REQUEST`). The requested window is treated as a half-open interval that begins at `scheduled_start` and runs up to but not including `scheduled_end`. It may not overlap any other repair order's window on the same bay; two windows that merely touch at an endpoint do not overlap and are allowed, but any genuine overlap is rejected with `ERR_BAY_DOUBLE_BOOKED`. A successful schedule records `bay_id`, `scheduled_start`, and `scheduled_end` on the order.

The order also carries a set of computed totals that the workflows below keep current: `labor_total_cents`, `parts_total_cents`, `core_deposit_total_cents`, `tax_cents`, `grand_total_cents`, and `approved_work_value_cents`. These are described in Sections 3.5 and 3.6.

### 3.3. Estimate Authorization and the Repair Order Lifecycle

A repair order is the central workflow object, and its status progresses through `ESTIMATE`, `APPROVED`, `IN_PROGRESS`, `ON_HOLD`, `COMPLETED`, `INVOICED`, and `CLOSED`, with `CANCELLED` as the alternate terminal outcome; `CLOSED` and `CANCELLED` are terminal.

The transition from `ESTIMATE` to `APPROVED` is the customer's signature on the estimate and is the only customer-driven lifecycle move. It requires three things to hold. First, the order must have something to bill — at least one labor line or part line, or at least one recommended job already in `APPROVED` status — otherwise it is rejected with `ERR_NOTHING_TO_AUTHORIZE`. Second, the acting customer must own the order's vehicle, or the request fails with `ERR_FORBIDDEN_FOR_ROLE`. Third, the supplied `expected_repair_order_version` must match the order's current `version`, or the request fails with `ERR_STALE_VERSION` as described in Section 2.9. On success the server snapshots `authorized_total_cents` from the order's `grand_total_cents`, advances the order to `APPROVED`, increments `version`, and records `authorized_version` as the `version` value that results from this mutation. Both `authorized_total_cents` and `authorized_version` are null until the first authorization.

The remaining lifecycle moves are driven by a `ServiceAdvisor` (or a `ShopManager` acting as override) through a single transition operation that takes an `action`. Starting work advances an order from `APPROVED` to `IN_PROGRESS`; it requires the order to currently be `APPROVED` (else `ERR_INVALID_STATE`) and to have an assigned `bay_id` (else `ERR_BAY_NOT_ASSIGNED`). Placing work on hold advances an `IN_PROGRESS` order to `ON_HOLD` (else `ERR_INVALID_STATE`); as a side effect, each of the order's `IN_PROGRESS` labor lines is moved to `PAUSED`, and any such line with an open clock session has that session auto-closed exactly as a clock-out would — the elapsed time is accumulated into the line's `actual_hours`, its `open_clock_at` is cleared, and the technician who held it is freed by clearing that technician's `clocked_labor_line_id`. Resuming returns an `ON_HOLD` order to `IN_PROGRESS` (else `ERR_INVALID_STATE`). Invoicing advances a `COMPLETED` order to `INVOICED` (else `ERR_INVALID_STATE`), freezing `grand_total_cents` as the invoiced amount. Closing advances an `INVOICED` order to `CLOSED` (else `ERR_INVALID_STATE`); it is refused while any core charge on the order is still in `CHARGED` status (`ERR_CORE_OUTSTANDING`), and on success it sets `closed_at` to the current time and records `close_odometer_miles` from the vehicle's current `odometer_miles`, anchoring the warranty window. Cancelling moves an order that is in either `ESTIMATE` or `APPROVED` status to `CANCELLED` (any other state yields `ERR_INVALID_STATE`); every still-`CHARGED` core charge on the order is forfeited to `FORFEITED` as a side effect.

Completion is its own dedicated operation, performed by a `Technician` or `ShopManager`, and moves an order from `IN_PROGRESS` to `COMPLETED`. It enforces four conditions in addition to the state check. The order must be `IN_PROGRESS` (else `ERR_INVALID_STATE`). Every labor line on the order must be `COMPLETED`, or completion is refused with `ERR_LABOR_NOT_DONE`. If the order has an inspection, that inspection must be `SUBMITTED` or `REVIEWED`, or completion is refused with `ERR_INSPECTION_NOT_SUBMITTED`. And if any inspection item is `RED`, no `RED`-severity recommended job may still be `PENDING`, or completion is refused with `ERR_RED_WORK_UNRESOLVED`. The technician-crediting side effects of completion are detailed in Section 3.7.

### 3.4. Labor Lines, the Clock, and Billing Method

Labor is written onto an order as **labor lines**. A `ServiceAdvisor`, `ShopManager`, or `Technician` adds a labor line to an order by naming the `labor_operation_id` whose `book_hours` it draws on, optionally assigning a `technician_id`, optionally choosing a `billing_method` of `FLAT_RATE` or `TIME_AND_MATERIALS` (defaulting to `FLAT_RATE`), optionally overriding the `rate_cents` for the line (when omitted, the line uses the labor operation's `default_rate_cents`), and optionally marking the line `is_warranty` (defaulting to false). At creation the line snapshots its `book_hours` from the labor operation, starts in `NOT_STARTED` status with `actual_hours` of 0 and no `open_clock_at`, and has its `charge_cents` computed as described in Section 3.5. A line may not be added to an order that is `COMPLETED`, `INVOICED`, `CLOSED`, or `CANCELLED` — such an attempt is rejected with `ERR_RO_NOT_EDITABLE`. Adding a line recomputes the order's totals. Labor lines can be listed for an order or filtered by `technician_id`, `labor_operation_id`, or `repair_order_id`.

A labor line moves through `NOT_STARTED`, `IN_PROGRESS`, `PAUSED`, and `COMPLETED`, with `COMPLETED` terminal. A `Technician` clocks in to start the first session, supplying a `technician_id` and a `clock_in` timestamp; this opens a session by recording `open_clock_at`, moving the line to `IN_PROGRESS`, and pointing that technician's `clocked_labor_line_id` at the line. Clocking in requires the owning order to be `IN_PROGRESS` (else `ERR_INVALID_STATE`). Re-clocking a `PAUSED` line after a resume works identically and likewise requires the owning order to be `IN_PROGRESS`. The technician-conflict guards on clock-in are covered in Section 3.9.

Clocking out closes the open session: the elapsed time from `open_clock_at` to the supplied `clock_out`, expressed in hours, is added to the line's `actual_hours`; `open_clock_at` is cleared; the technician's `clocked_labor_line_id` is cleared; and that technician's `last_clock_out_at` is set to the `clock_out` instant. A clock-out requires an open session on the line (`open_clock_at` not null, else `ERR_INVALID_STATE`) and a `clock_out` strictly later than `open_clock_at` (else `ERR_INVALID_REQUEST`). For a time-and-materials line, a clock-out recomputes the line's `charge_cents` and the order's totals. Completing a labor line is performed by a `Technician` or `ShopManager`; it requires the line to be `IN_PROGRESS` or `PAUSED` (else `ERR_INVALID_STATE`) and no open session to remain (`open_clock_at` must be null, else `ERR_OPEN_TIME_ENTRY`). Completion sets the line to `COMPLETED`, computes its final `charge_cents`, and recomputes the order's totals.

### 3.5. Pricing Labor and Parts

The labor charge for a line is computed as follows, always rounded half up to whole cents. First, the effective rate is the line's own `rate_cents` when that was supplied, and otherwise the labor operation's `default_rate_cents`. If the line is a warranty line (`is_warranty` true), its `charge_cents` is zero regardless of anything else. Otherwise, for a `FLAT_RATE` line the charge is the line's snapshotted `book_hours` multiplied by the effective rate, then rounded half up — this charge is fixed at line creation, bills the book hours, and never depends on actual clocked time. For a `TIME_AND_MATERIALS` line the charge is instead the line's accumulated `actual_hours` multiplied by the effective rate, then rounded half up — it bills the actual clocked hours and ignores the book hours; it is zero until the first clock-out, provisional while work proceeds, and final at completion. The two billing methods thus produce different numbers from the same line: flat-rate bills book hours, time-and-materials bills actual hours.

A **part line** is added to an order by a `PartsManager`, `ServiceAdvisor`, or `ShopManager`, supplying the `part_number`, a `description`, the `quantity` (which must be greater than zero), the per-unit `unit_cost_cents` (which must be zero or greater), an optional `markup_mode` of `MARGINAL` or `FLAT_BRACKET` (defaulting to `MARGINAL`), an optional `has_core` flag (defaulting to false), an optional per-unit `core_deposit_cents` used when the part carries a core (zero or greater, defaulting to 0), and an optional `is_warranty` flag (defaulting to false). A part line starts in `QUOTED` status and may not be added to an order that is `COMPLETED`, `INVOICED`, `CLOSED`, or `CANCELLED` (`ERR_RO_NOT_EDITABLE`). The part's `extended_charge_cents` is computed at creation as described next, and adding the line recomputes the order's totals. Part lines can be listed for an order, and a single part line retrieved. A `Technician`, `PartsManager`, or `ShopManager` marks a part line installed, moving it from `QUOTED` to `INSTALLED`.

The marked-up charge on a part line is computed against the full markup matrix, with tier selection driven by the per-unit `unit_cost_cents`. If the line is a warranty line, its `extended_charge_cents` is zero and no further computation occurs. Otherwise, consider the tiers sorted ascending by `tier_index`. Under `FLAT_BRACKET` mode, the entire per-unit cost is marked up at the single tier whose band contains that cost — that is, the tier whose `lower_bound_cents` is less than or equal to the per-unit cost and whose `upper_bound_cents` (treated as positive infinity when null) is strictly greater than it; the per-unit sell price is the per-unit cost multiplied by one plus that tier's `markup_pct`, rounded half up. If no tier's band contains the cost, the request is rejected with `ERR_MARKUP_TIER_MISSING`. Under `MARGINAL` mode, the per-unit cost is instead sliced across the bands: for each tier in ascending order, the slice is the portion of the cost interval from zero up to the per-unit cost that overlaps the tier's band — concretely the amount by which the smaller of the per-unit cost and the band's upper bound exceeds the band's lower bound, floored at zero — and each positive slice contributes that slice multiplied by one plus the tier's `markup_pct`, rounded half up per slice, accumulated into the per-unit sell price. If the tiers do not collectively cover the interval from zero up to the per-unit cost, the request is rejected with `ERR_MARKUP_TIER_MISSING`. In both modes the line's `extended_charge_cents` is the resulting per-unit sell price multiplied by the line `quantity`. The same per-unit cost can therefore yield a different sell price under the two modes.

### 3.6. Repair Order Totals and Tax

Whenever a labor line, part line, or core charge changes, or a recommended job is approved, or the order completes, the order's totals are recomputed from scratch under a pinned rounding order: each line is rounded first, and the rounded amounts are then summed. The `labor_total_cents` is the sum of the already-rounded `charge_cents` over the order's labor lines. The `parts_total_cents` is the sum of the already-rounded `extended_charge_cents` over the order's part lines whose status is not `RETURNED`. The `core_deposit_total_cents` is the sum of the `deposit_cents` over the order's core charges that are in `CHARGED` status. The taxable subtotal is the sum of `labor_total_cents` and `parts_total_cents` — core deposits are not taxable. The `tax_cents` is that taxable subtotal multiplied by the order's `tax_rate`, rounded half up exactly once. Finally `grand_total_cents` is the plain sum of `labor_total_cents`, `parts_total_cents`, `core_deposit_total_cents`, and `tax_cents`, with no rounding applied to that sum. Separately, `approved_work_value_cents` is the sum of the `estimated_value_cents` over the recommended jobs in `APPROVED` status that target this order.

### 3.7. Technician Efficiency

Each technician accumulates two banked quantities that together yield an efficiency figure, and these are settled when a repair order completes. On completion of an order, for each of its `COMPLETED` non-warranty labor lines that has an assigned technician, that technician's `banked_flat_hours` is increased by the line's `book_hours` and their `banked_actual_hours` is increased by the line's `actual_hours`, after which that technician's `efficiency_pct` is recomputed. If the completing order is itself a comeback, then additionally, for each warranty labor line on it, the original order's assigned technician has their `banked_flat_hours` reduced by that line's `book_hours` as a warranty penalty, and that original technician's `efficiency_pct` is then recomputed.

A technician's `banked_flat_hours` is thus the sum of `book_hours` over their `COMPLETED` non-warranty labor lines minus the `book_hours` debited by warranty comebacks charged against them, and their `banked_actual_hours` is the sum of `actual_hours` over those same credited lines. The `efficiency_pct` is one hundred multiplied by `banked_flat_hours` divided by `banked_actual_hours`, rounded half up to one decimal place. As a boundary rule, when `banked_actual_hours` is zero the `efficiency_pct` is null rather than zero — there is no division by zero. Fetching a technician recomputes and returns the current `efficiency_pct` from the banked hours.

### 3.8. Warranty Comebacks

A comeback is a new repair order that reworks an earlier one under warranty, established by setting `comeback_of_ro_id` on the new order to the original order's `id`. The original order must be `CLOSED`, so its `closed_at` and `close_odometer_miles` are set. The comeback is honored only when both warranty bounds hold. The time bound holds when the current time is no later than the original order's `closed_at` plus the warranty period of 90 days — the boundary at exactly ninety days is inclusive. The mileage bound holds when the comeback vehicle's `odometer_miles` is no greater than the original order's `close_odometer_miles` plus the warranty allowance of 4,000 miles — also inclusive. If either bound is exceeded, the warranty claim is rejected with `ERR_WARRANTY_EXPIRED`. This same window check applies both when creating an order that carries `comeback_of_ro_id` and when adding any line marked `is_warranty` to an order.

A within-warranty comeback's warranty lines bill at zero, as described in Section 3.5, and on the comeback's completion they debit the original technician's banked hours, as described in Section 3.7. The current time used for the time bound, and for the clock checks in Section 3.9, is the server's logical clock. A `ShopManager` may set that clock for test-driving by supplying a `to_iso8601` instant; the server's notion of the current UTC time then returns that value until it is set again.

### 3.9. Technician Clock Conflicts

A technician may hold only one open clock session at a time. When a technician attempts to clock in, two conditions guard the action. First, that technician must not already be clocked in elsewhere — that is, their `clocked_labor_line_id` must be null; if it is not, the clock-in is rejected with `ERR_TECH_DOUBLE_CLOCKED`. Second, the supplied `clock_in` instant must fall at least a ten-minute cleanup buffer after the technician's `last_clock_out_at`; a clock-in earlier than ten minutes after their most recent clock-out is likewise rejected with `ERR_TECH_DOUBLE_CLOCKED`. These guards apply to every clock-in, whether it opens the first session on a `NOT_STARTED` line or re-opens a `PAUSED` line after a resume.

### 3.10. Inspections and Recommended Work

A `Technician` or `ShopManager` opens a **multi-point inspection** on an order by naming the performing `technician_id`. A new inspection starts in `DRAFT` status with an empty `items` list, a `worst_severity` of `GREEN`, and a `red_item_count` of 0. Inspection items are appended one at a time to a draft inspection, each carrying a `point_name`, an optional `severity` of `GREEN`, `YELLOW`, or `RED`, and an optional `note`; appending an item to an inspection that is not `DRAFT` is rejected with `ERR_INVALID_STATE`. Inspections can be listed for an order or filtered by `technician_id` or `repair_order_id`.

An inspection moves through `DRAFT`, `SUBMITTED`, and `REVIEWED`, with `REVIEWED` terminal. Submitting a draft inspection, by a `Technician` or `ShopManager`, requires the inspection to be `DRAFT` (else `ERR_INVALID_STATE`) and to have at least one item (else `ERR_INSPECTION_EMPTY`); it recomputes the severity rollups and advances the inspection to `SUBMITTED`. The `worst_severity` is `RED` if any item is `RED`, otherwise `YELLOW` if any item is `YELLOW`, otherwise `GREEN`; the `red_item_count` is the count of items whose severity is `RED`. Reviewing a submitted inspection, by a `ServiceAdvisor` or `ShopManager`, requires it to be `SUBMITTED` (else `ERR_INVALID_STATE`) and advances it to `REVIEWED`.

A finding that warrants additional work becomes a **recommended job**, created from an inspection by a `Technician`, `ServiceAdvisor`, or `ShopManager`. A recommended job names the `repair_order_id` the approved work will materialize onto, the `labor_operation_id` to perform, and — when the recommendation includes a part — an optional `part_number`, `part_quantity` (zero or greater, defaulting to 0), `part_unit_cost_cents` (zero or greater, defaulting to 0), `has_core` flag (defaulting to false), and per-unit `core_deposit_cents` (zero or greater, defaulting to 0); it also carries a `severity` of `YELLOW` or `RED` (defaulting to `YELLOW`) reflecting the urgency of the inspection point. The recommended job also carries an `inspection_id` identifying the inspection that surfaced it. At creation its `estimated_value_cents` is computed as an estimated sell price combining flat-rate labor for the operation with the flat-bracket-marked-up cost of the part, and the job starts in `PENDING` status. Recommended jobs can be listed for an inspection or filtered by `repair_order_id` or `labor_operation_id`.

### 3.11. Customer Decisions on Recommended Work

The vehicle owner decides each recommended job by submitting a `decision`, and is the only role permitted to do so; in every case the acting customer must own the order's vehicle or the decision is refused with `ERR_FORBIDDEN_FOR_ROLE`. A recommended job runs from `PENDING` and may branch to `APPROVED`, `DECLINED`, or `DEFERRED`; a `DEFERRED` job may later be revisited to `APPROVED` or `DECLINED`; `DECLINED` is terminal.

Declining moves a `PENDING` or `DEFERRED` job to `DECLINED` with no further effect. Deferring moves a `PENDING` job to `DEFERRED` with no further effect. Approving moves a `PENDING` or `DEFERRED` job to `APPROVED` and requires the owning order to be in `ESTIMATE`, `APPROVED`, `IN_PROGRESS`, or `ON_HOLD` status (else `ERR_INVALID_STATE`). Approval triggers a materialization cascade onto the order, and the same cascade runs whether the job was approved out of `PENDING` or out of `DEFERRED`. First, a labor line is created on the order from the job's `labor_operation_id`, and its identifier is recorded on the job as `created_labor_line_id`. Second, if the job carries a `part_number`, a part line is created on the order and its identifier is recorded on the job as `created_part_line_id`; this part line creation recomputes the order's parts total. Third, if that created part line carries a core (`has_core` true), its creation in turn cascades a core charge in `CHARGED` status, which adds its deposit to the order's `core_deposit_total_cents`. Finally the order's totals and its `approved_work_value_cents` are recomputed.

### 3.12. Core Charges

A returnable core generates a **core charge** whenever a part line with `has_core` set is created — including a part line materialized from an approved recommended job. The core charge is owned by the order through its `repair_order_id` and points at the originating part line through its `part_line_id`. Its `deposit_cents` is computed at creation as the part line's `quantity` multiplied by the part line's per-unit `core_deposit_cents`, and the core charge begins in `CHARGED` status with `refunded_cents` of 0. Creating it adds its deposit to the owning order's `core_deposit_total_cents`. Core charges can be retrieved individually, listed for an order, or filtered by `part_line_id`, `repair_order_id`, or `status`.

A core charge runs from `CHARGED` to either `CORE_RETURNED` or `FORFEITED`, both terminal. Recording the old core as returned, by a `PartsManager` or `ShopManager`, requires the core charge to be `CHARGED` (else `ERR_INVALID_STATE`) and the owning order not to be `CLOSED` or `CANCELLED` (else `ERR_INVALID_STATE`); it moves the core charge to `CORE_RETURNED`, sets `refunded_cents` equal to `deposit_cents`, subtracts that deposit from the order's `core_deposit_total_cents` to restore the core invariant, and recomputes the order's totals. Forfeiting a core, by a `PartsManager` or `ShopManager` (or driven by the system when the owning order is cancelled), requires the core charge to be `CHARGED` (else `ERR_INVALID_STATE`) and moves it to `FORFEITED`; a forfeited deposit is retained by the shop and remains billed, so `core_deposit_total_cents` is unchanged by a forfeit.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, drive a state transition, or append to a resource's internal collection return a `200 OK` status code. The request body, response body, and side effects of each endpoint are described in the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | ServiceAdvisor, ShopManager |
| GET | `/customers/{id}` | Get a customer | ServiceAdvisor, ShopManager, PartsManager, Technician, Customer |
| GET | `/customers/{id}/vehicles` | List a customer's vehicles | ServiceAdvisor, ShopManager, PartsManager, Technician, Customer |
| POST | `/vehicles` | Create a vehicle | ServiceAdvisor, ShopManager |
| GET | `/vehicles/{id}` | Get a vehicle | ServiceAdvisor, ShopManager, PartsManager, Technician, Customer |
| POST | `/technicians` | Create a technician | ShopManager |
| GET | `/technicians/{id}` | Get a technician (includes computed efficiency) | ServiceAdvisor, ShopManager, PartsManager, Technician |
| POST | `/service-bays` | Create a service bay | ShopManager |
| POST | `/labor-operations` | Create a flat-rate labor operation | ShopManager, ServiceAdvisor |
| POST | `/markup-tiers` | Create a parts markup matrix tier | PartsManager, ShopManager |
| GET | `/markup-tiers` | List the markup matrix, ordered by tier | PartsManager, ShopManager, ServiceAdvisor |
| POST | `/repair-orders` | Create a repair order | ServiceAdvisor, ShopManager |
| GET | `/repair-orders/{id}` | Get a repair order | ServiceAdvisor, ShopManager, PartsManager, Technician, Customer |
| GET | `/repair-orders` | List repair orders | ServiceAdvisor, ShopManager, PartsManager, Technician, Customer |
| POST | `/repair-orders/{id}/schedule` | Assign a bay and time window | ServiceAdvisor, ShopManager |
| POST | `/repair-orders/{id}/authorize` | Customer authorizes the estimate snapshot | Customer |
| POST | `/repair-orders/{id}/transition` | Drive lifecycle moves: START, HOLD, RESUME, INVOICE, CLOSE, CANCEL | ServiceAdvisor, ShopManager |
| POST | `/repair-orders/{id}/complete` | Complete the repair order | Technician, ShopManager |
| POST | `/repair-orders/{id}/labor-lines` | Add a labor line | ServiceAdvisor, ShopManager, Technician |
| GET | `/repair-orders/{id}/labor-lines` | List labor lines for a repair order | ServiceAdvisor, ShopManager, PartsManager, Technician, Customer |
| GET | `/labor-lines/{id}` | Get a labor line | ServiceAdvisor, ShopManager, Technician |
| GET | `/labor-lines` | List labor lines | ServiceAdvisor, ShopManager, Technician |
| POST | `/labor-lines/{id}/clock-in` | Clock in on a labor line | Technician |
| POST | `/labor-lines/{id}/clock-out` | Clock out of the open session | Technician |
| POST | `/labor-lines/{id}/complete` | Complete a labor line and compute its charge | Technician, ShopManager |
| POST | `/repair-orders/{id}/part-lines` | Add a part line | PartsManager, ServiceAdvisor, ShopManager |
| GET | `/repair-orders/{id}/part-lines` | List part lines for a repair order | ServiceAdvisor, ShopManager, PartsManager, Technician, Customer |
| GET | `/part-lines/{id}` | Get a part line | ServiceAdvisor, ShopManager, PartsManager |
| POST | `/part-lines/{id}/install` | Mark a part line installed | Technician, PartsManager, ShopManager |
| GET | `/repair-orders/{id}/core-charges` | List core charges for a repair order | ServiceAdvisor, ShopManager, PartsManager, Customer |
| GET | `/core-charges/{id}` | Get a core charge | ServiceAdvisor, ShopManager, PartsManager |
| GET | `/core-charges` | List core charges | ServiceAdvisor, ShopManager, PartsManager |
| POST | `/core-charges/{id}/return` | Record core returned; refund deposit | PartsManager, ShopManager |
| POST | `/core-charges/{id}/forfeit` | Forfeit the core deposit | PartsManager, ShopManager |
| POST | `/repair-orders/{id}/inspections` | Create a multi-point inspection | Technician, ShopManager |
| GET | `/repair-orders/{id}/inspections` | List inspections for a repair order | ServiceAdvisor, ShopManager, Technician, Customer |
| GET | `/inspections/{id}` | Get an inspection | ServiceAdvisor, ShopManager, Technician, Customer |
| GET | `/inspections` | List inspections | ServiceAdvisor, ShopManager, Technician, Customer |
| POST | `/inspections/{id}/items` | Append an item to a draft inspection | Technician, ShopManager |
| POST | `/inspections/{id}/submit` | Submit inspection; compute severity rollups | Technician, ShopManager |
| POST | `/inspections/{id}/review` | Review a submitted inspection | ServiceAdvisor, ShopManager |
| POST | `/inspections/{id}/recommended-jobs` | Create a recommended job from a finding | Technician, ServiceAdvisor, ShopManager |
| GET | `/inspections/{id}/recommended-jobs` | List recommended jobs for an inspection | ServiceAdvisor, ShopManager, Technician, Customer |
| GET | `/recommended-jobs/{id}` | Get a recommended job | ServiceAdvisor, ShopManager, Technician, Customer |
| GET | `/recommended-jobs` | List recommended jobs | ServiceAdvisor, ShopManager, Technician, Customer |
| POST | `/recommended-jobs/{id}/decision` | Approve, decline, or defer recommended work | Customer |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC time | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BAY_NOT_ASSIGNED` | 409 Conflict |
| `ERR_BAY_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_LABOR_NOT_DONE` | 409 Conflict |
| `ERR_INSPECTION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_RED_WORK_UNRESOLVED` | 409 Conflict |
| `ERR_CORE_OUTSTANDING` | 409 Conflict |
| `ERR_NOTHING_TO_AUTHORIZE` | 409 Conflict |
| `ERR_RO_NOT_EDITABLE` | 409 Conflict |
| `ERR_INSPECTION_EMPTY` | 409 Conflict |
| `ERR_MARKUP_TIER_MISSING` | 409 Conflict |
| `ERR_TECH_DOUBLE_CLOCKED` | 409 Conflict |
| `ERR_OPEN_TIME_ENTRY` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_DUPLICATE_VIN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

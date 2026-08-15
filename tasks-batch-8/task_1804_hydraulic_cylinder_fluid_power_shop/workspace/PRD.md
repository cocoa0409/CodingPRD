# Hydraulic Cylinder & Fluid-Power Shop API — Product Requirements Document

## 1. Introduction

A fluid-power distributor's service counter runs on turnaround promises. A disabled hydraulic cylinder arrives at intake; the shop tears it down, quotes the repair from the teardown findings, cuts chrome rod and honing tube from stock, reassembles under contamination control, pressure-tests the unit in a booked bay, and certifies it before the customer pays. Around that spine sit three adjacent businesses: a scrap path for units beyond economical repair, a remanufactured exchange pool that credits the customer's returned core against a replacement unit, and a field service crew that crimps hose assemblies on site. Each path prices differently and settles differently, and every dollar figure on a job exists in two variants — a provisional number quoted before the work and a final number settled after it.

This document specifies the API that orchestrates that shop. All resources are mounted under the `/fluid-power` prefix. The design rests on four commitments. First, segregation of duties: the technician who repairs a unit may never certify it, and an independent quality authority owns pressure testing, certification, and core grading. Second, version-pinned quoting: a quote is priced from an exact revision of the teardown findings and goes stale the moment those findings are revised. Third, optimistic concurrency on shared configuration and technician calendars, so that edits always build on the revision the client last observed. Fourth, exact money: every line item rounds half-up to integer cents in a pinned order, because a shop that cannot reproduce a quote to the cent cannot defend an invoice.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `ShopAdmin`, `ServiceAdvisor`, `Technician`, `QualityInspector`, and `Customer`. A request missing either header, or carrying a role outside this declared set, is rejected with an `ERR_UNAUTHENTICATED` error. Access to specific operations is further restricted by role per the endpoint matrix in §4; an attempt to perform an action outside the caller's designated role is rejected with an `ERR_FORBIDDEN` error. Where a role is entity-backed, an additional ownership check applies and failures surface as `ERR_NOT_OWNER`.

The five roles and their identities are defined as follows:

- `ShopAdmin` — the shop owner/operator. Owns configuration, the seal-kit catalog, technician onboarding, inventory, the test-bay registry, the exchange pool, and holds full operational override. One override is deliberately withheld: segregation of duties bars any operator from certifying work performed under the same user id as the assigned technician. When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `ServiceAdvisor` — the front-counter advisor. Handles intake, quoting, scheduling, and customer-facing administration. When `X-User-Role` is `ServiceAdvisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Technician` — a shop or field technician who performs teardown, repair, assembly, and assigned field work. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; ownership checks on any resource that references a technician compare the resource's technician foreign key — `assigned_technician_id` on a work order, `technician_id` on a field service job — to `X-User-ID`.
- `QualityInspector` — the independent quality authority. Owns pressure testing, result recording, certification, cleanliness verification alongside technicians, and core grading. When `X-User-Role` is `QualityInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `issued_by` on a certificate — but does not compare it to any entity's `id`, except in the segregation-of-duties check on certification described in §3.7.
- `Customer` — an external equipment owner. Approves quotes, directs scrap-or-exchange decisions, and books field service for its own assets. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks compare the resource's `customer_id` to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — the Shop, Customer, Technician, SealKit, Cylinder, WorkOrder, TeardownReport, Quote, InventoryItem, StockReservation, TestBay, PressureTest, Certificate, ExchangeUnit, and FieldServiceJob — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any change to the resource.
- `version` (integer): starts at 1 when the resource is created and increments by one with every modification.

Any mutation of a resource — including system-driven cascades that change its derived fields — refreshes its `updated_at` and increments its `version` by one. Four flows call this out explicitly because downstream rules depend on it: starting teardown increments the work order's `version` by one; revising a teardown report increments the report's `version` by one; updating shop configuration increments the shop's `version` by one; and scheduling a field service job increments the technician's `version` by one.

### 2.5. The Logical Clock

The system runs on a logical clock rather than wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`; before any clock-set call it continues to read this default and never falls back to wall-clock time. A `ShopAdmin`-only test-driving capability sets the clock by supplying a `to_iso8601` instant, and the operation returns an object carrying `current_utc`, the clock's new reading. Every temporal rule in this document — quote lifetime, scheduling windows, emergency-callout detection — is evaluated against this logical clock.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control. Each requires a non-optional expected-version field in the request body carrying the `version` of the parent entity as the client last observed it. If that value does not equal the parent entity's current `version` — because another write has advanced the entity since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A sequential retry carrying the current version succeeds: revisions legitimately build on one another, and several non-overlapping jobs legitimately share one technician's calendar.

- Revising a teardown report requires `expected_teardown_report_version`, compared against the `TeardownReport`'s current `version`. A rejection means the client's edits are based on a stale revision of the findings.
- Scheduling a field service job requires `expected_technician_version`, compared against the `Technician`'s current `version`. A rejection means the schedule view the client planned against is stale, even when the requested window itself is free.
- Updating shop configuration requires `expected_shop_version`, compared against the `Shop`'s current `version`. A rejection means rate and cutoff edits would not be building on the current configuration.

Endpoints not listed here do not take a version field.

### 2.7. Cascading State Consistency

Many operations mutate more than one resource atomically. When a work order advances, the resources hanging off it advance with it: sending a quote moves the work order from `QUOTE_DRAFT` to `QUOTE_SENT`; approval moves both quote and work order to `APPROVED` and cuts material reservations; a recorded test result moves the work order to `TEST_PASSED` or back to `IN_REPAIR`; revoking a certificate pushes the work order from `CERTIFIED` back to `TEST_PENDING` and voids the underlying test. Each resource touched by such a cascade is individually mutated — its `updated_at` refreshed and its `version` incremented per §2.4. The server performs these transitions automatically when the governing criteria are met, without requiring a separate client request on the affected resource.

State machines are enforced strictly. A resource sitting in a terminal state — `CLOSED`, `SCRAPPED`, or `CANCELLED` for a work order; `APPROVED`, `EXPIRED`, `SUPERSEDED`, or `REJECTED_SCRAP` for a quote; `CONSUMED` or `RELEASED` for a reservation; `PASSED`, `FAILED`, `VOIDED`, or `CANCELLED` for a pressure test; `REVOKED` for a certificate; `SETTLED` for an exchange unit; `DEPLETED` for an inventory item; `COMPLETED` or `CANCELLED` for a field service job; `RETIRED` or `EXCHANGED` for a cylinder — rejects every further transition with `ERR_ALREADY_TERMINAL`. A non-terminal resource addressed from the wrong from-state for the requested transition is rejected with `ERR_INVALID_STATE`.

### 2.8. Monetary Precision and Rounding Discipline

All monetary values are handled as integer cents. Every computed monetary line is rounded to integer cents using round-half-up, and every total is the sum of its already-rounded lines. The evaluation order is pinned: round each line first, then sum. Summing the raw unrounded lines and rounding once at the end is incorrect — the two orders disagree whenever two or more raw lines carry a fractional half-cent.

Exactly one quantity in the system rounds differently: the exchange core-credit cap, a percentage of the exchange unit price, is rounded half-down (truncated at the half-cent boundary) before being applied as the ceiling. Every other rounding in the system is half-up.

Non-monetary quantities keep their own integral precision: lengths and diameters are integer millimetres, pressures are integer psi, ISO 4406 cleanliness codes are integers, and multipliers and percentages (labor multipliers, discount percentages, the environmental fee percentage, the core-credit cap percentage) are decimal numbers applied exactly as configured.

### 2.9. Validation Order and Error Precedence

Validations are applied to every request in a fixed priority order, and an earlier failure masks every later one — the client always sees the first failing check's error, never a later check's. The order is:

1. **Request shape.** Required fields are present, and types and enum members are valid; failures are rejected with `ERR_INVALID_REQUEST`. This check runs first on every endpoint.
2. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is declared; failures are rejected with `ERR_UNAUTHENTICATED`.
3. **Role permission.** The role is permitted for this endpoint per the §4 matrix; failures are rejected with `ERR_FORBIDDEN`.
4. **Ownership.** For owner-scoped operations, the entity-backed caller owns the target — a `Customer` actor's `X-User-ID` must equal the resource's `customer_id` (quote approval, revision requests, scrap authorization, exchange selection, and cancelling as a customer), and a `Technician` actor's `X-User-ID` must equal the work order's `assigned_technician_id` or the job's `technician_id` (start-repair, complete-assembly, reservation consume, dispatch, and field completion); failures are rejected with `ERR_NOT_OWNER`.
5. **Existence.** Path identifiers and body foreign keys reference existing resources, validated left-to-right so the first missing reference in the path is the one reported; failures are rejected with `ERR_NOT_FOUND`.
6. **Optimistic concurrency.** The expected-version fields of §2.6 match the parent's current version; failures are rejected with `ERR_STALE_VERSION`.
7. **Transition legality.** The target resource is in a valid from-state for the requested transition; wrong-from-state requests are rejected with `ERR_INVALID_STATE`, and terminal resources reject everything with `ERR_ALREADY_TERMINAL`.
8. **Domain state guards.** The operation-specific state preconditions hold: the quote is approvable (`SENT`), no teardown report exists yet, the exchange unit is in the pool, the reservation is in its expected state, scrap has been authorized before it is completed, the unit is fulfilled before its core is received, the exchange deal is settled before the work order closes, the cylinder is active for a new work order, the customer is not suspended, and no scheduled test is outstanding when a re-test is booked. Failures surface respectively as `ERR_QUOTE_NOT_APPROVABLE`, `ERR_TEARDOWN_REPORT_EXISTS`, `ERR_UNIT_NOT_IN_POOL`, `ERR_RESERVATION_NOT_OPEN`, `ERR_SCRAP_NOT_AUTHORIZED`, `ERR_EXCHANGE_NOT_FULFILLED`, `ERR_CORE_NOT_RETURNED`, `ERR_CYLINDER_RETIRED`, `ERR_CUSTOMER_SUSPENDED`, or `ERR_INVALID_STATE`.
9. **Safety and compliance gates.** Cleanliness class within target for assembly completion, segregation of duties on certification, pass-record consistency against measured pressure, duration, and leakage, crimp tolerance on field completion, and seal-kit compatibility. Failures surface as `ERR_CLEANLINESS_CLASS_EXCEEDED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PRESSURE_HOLD_INSUFFICIENT`, `ERR_CRIMP_OUT_OF_TOLERANCE`, or `ERR_SEAL_KIT_INCOMPATIBLE`.
10. **Temporal rules.** Test-bay window overlap including the mandatory buffer, technician half-open window overlap, windows not starting in the past, quote lifetime, and turnaround-tier feasibility; failures surface as `ERR_TEST_BAY_WINDOW_OVERLAP`, `ERR_TECHNICIAN_WINDOW_OVERLAP`, `ERR_WINDOW_IN_PAST`, `ERR_QUOTE_EXPIRED`, or `ERR_PROMISE_INFEASIBLE`.
11. **Aggregate and structural constraints.** At most one draft-or-sent quote per work order, exchange-unit specification match, a stock piece exists that fits the cut, and at most one issued certificate per work order; failures surface as `ERR_ACTIVE_QUOTE_EXISTS`, `ERR_SPEC_MISMATCH`, `ERR_NO_STOCK_FITS`, or `ERR_CERTIFICATE_EXISTS`.
12. **Version pinning.** Sending a quote requires its pinned teardown version to equal the report's current version; failures are rejected with `ERR_TEARDOWN_STALE`.
13. **Fiscal exposure.** Quote approval requires the credit-exposure check of §3.4 to pass; failures are rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

Because of this ordering, a credit-limit failure is reported only when every shape, identity, state, safety, temporal, structural, and pinning check has already passed, and a stale-teardown rejection is reported only after all state and structural checks have passed.

### 2.10. Shop Configuration and the Rate Card

A single **Shop** resource carries the shop's configuration. Creating it requires only a `name`; every rate, cutoff, and threshold below has a documented default that applies when the creation payload does not override it. Creation accepts optional overrides for the labor rate, the two turnaround multipliers, both turnaround cutoffs, the honing pass fee, the cut fee, the saw kerf, the minimum remnant, the three cleanliness targets, the quote lifetime, and the bay buffer; all remaining configuration values are fixed at their documented defaults and are not settable through the create payload. A later configuration update accepts only `expected_shop_version` plus new values for the labor rate, the two multipliers, both cutoffs, the honing pass fee, the cut fee, the minimum remnant, the quote lifetime, and the bay buffer; other values cannot be patched. The configuration is readable by every role.

Labor and turnaround. The base shop labor rate is `labor_rate_cents_per_hour` (default 14500 cents per hour). The turnaround multipliers are `expedite_multiplier` (default 1.35) for the `EXPEDITE` tier and `emergency_multiplier` (default 1.75) for the `EMERGENCY` tier; the `STANDARD` tier always multiplies labor by 1.0. The cutoff `expedite_cutoff_hours` (default 48) is the promised-turnaround ceiling at or below which at least an expedite tier is required, and `emergency_cutoff_hours` (default 24) is the ceiling at or below which only the emergency tier suffices.

Cutting and materials. Each honing pass is billed `honing_pass_fee_cents` (default 4000). Each stock cut carries a flat `cut_fee_cents` (default 1500), the saw consumes `kerf_mm` (default 3 millimetres) per cut, and any stock remainder shorter than `min_remnant_mm` (default 300 millimetres) is scrapped and charged to the job. Provisional quotes estimate chrome rod at `default_chrome_rod_cost_per_mm_cents` (default 42 cents per millimetre) and honing tube at `default_honing_tube_cost_per_mm_cents` (default 65 cents per millimetre). The shop-supplies line is `supplies_pct_of_labor` (default 0.04) of the raw, unrounded labor line.

Cleanliness and pressure testing. The ISO 4406 cleanliness targets are `cleanliness_target_code4` (default 18) for the greater-than-4-micron channel, `cleanliness_target_code6` (default 16) for the greater-than-6-micron channel, and `cleanliness_target_code14` (default 13) for the greater-than-14-micron channel. The required hold pressure of a certification test is `pressure_test_factor` (default 1.5) times the cylinder class's rated working pressure, and a passing hold must last at least `test_hold_min_minutes` (default 10 minutes). Rated working pressures are `rated_pressure_class_3000_psi` (default 3000 psi) for `CLASS_3000` cylinders and `rated_pressure_class_5000_psi` (default 5000 psi) for `CLASS_5000` cylinders.

Quoting and scheduling. A sent quote lives for `quote_ttl_hours` (default 168 hours — one week). Successive bookings of the same pressure-test bay must keep `bay_buffer_minutes` (default 30 minutes) of clearance on both sides of each booking.

Settlement. Loyalty tiers are tested against the customer's pre-invoice year-to-date spend plus the pre-discount subtotal: at or above `loyalty_gold_threshold_cents` (default 500000) the tier is `GOLD`; otherwise, at or above `loyalty_silver_threshold_cents` (default 100000), the tier is `SILVER`; below that the customer holds no loyalty tier, denoted `NONE`. The discount is `loyalty_gold_pct` (default 0.10) of the subtotal for `GOLD` and `loyalty_silver_pct` (default 0.05) for `SILVER`. The environmental fee is `env_fee_pct` (default 0.02) of the discounted subtotal, floored at `env_fee_min_cents` (default 500).

Field service. A callout is billed `callout_base_cents` (default 25000); when the scheduled window starts within `emergency_callout_window_hours` (default 4 hours) of the job's creation the callout is multiplied by `emergency_callout_multiplier` (default 2.0). Travel beyond `mileage_free_km` (default 50 kilometres round-trip) is billed `mileage_rate_cents_per_km` (default 250 cents per kilometre). Each hose assembly carries a `crimp_fee_cents` charge (default 4500), and a measured crimp diameter may deviate from its specification by at most `crimp_tolerance_mm` (default 0.3 millimetres, inclusive). Hose sells per metre at `hose_price_wire_braid_2sn_cents_per_m` (default 3200) for `WIRE_BRAID_2SN`, `hose_price_spiral_4sh_cents_per_m` (default 5700) for `SPIRAL_4SH`, and `hose_price_thermoplastic_cents_per_m` (default 1800) for `THERMOPLASTIC`.

Exchange pool. The core credit never exceeds `exchange_credit_cap_pct` (default 0.30) of the exchange unit price. A core graded scrap earns no credit and instead incurs `core_disposal_fee_cents` (default 7500) at close. Core base values step with bore: `core_base_small_cents` (default 40000) when the bore is at most `core_bore_medium_max_mm` (default 100 millimetres), `core_base_medium_cents` (default 90000) when it is at most `core_bore_large_max_mm` (default 200 millimetres), and `core_base_large_cents` (default 160000) beyond that.

## 3. Business Logic & Workflows

### 3.1. Shop Onboarding, Customer Accounts, and the Seal-Kit Catalog

Before any repair can flow, a `ShopAdmin` brings up the shop's master data. The shop configuration itself is created once with a `name` and any desired overrides of the §2.10 defaults. Customers are registered by a `ShopAdmin` or `ServiceAdvisor` with a `full_name`, an `email`, and a `credit_limit_cents` bounding the customer's open approved-quote exposure; an optional `opening_ytd_spend_cents` books migrated year-to-date spend at account creation and defaults to zero. A new customer starts `ACTIVE`, and its `ytd_spend_cents` is initialized to the opening value; thereafter `ytd_spend_cents` is always the opening value plus the sum of `invoice_total_cents` over that customer's `CLOSED` work orders. A `ShopAdmin` may suspend a customer, moving it from `ACTIVE` to `SUSPENDED`, and later reactivate it back to `ACTIVE`; a suspended customer cannot open new work orders.

Technicians are onboarded by a `ShopAdmin` with a `full_name`, a non-empty `skills` array drawn from `CYLINDER_REPAIR` and `FIELD_SERVICE`, and an `active` flag that defaults to true. Only an active technician whose skills cover the work may be assigned to it.

The seal-kit catalog is maintained by a `ShopAdmin`. Each kit carries a `kit_code` that must be unique across all seal kits, an inclusive compatible bore range from `bore_min_mm` to `bore_max_mm`, a `pressure_class_max` of `CLASS_3000` or `CLASS_5000` naming the highest pressure class the kit supports, a `fluid_compat` array drawn from `MINERAL_OIL`, `PHOSPHATE_ESTER`, and `WATER_GLYCOL`, a `price_cents`, and a seal `material` of `NBR`, `VITON`, or `PU`.

A cylinder is registered by a `ShopAdmin`, a `ServiceAdvisor`, or the owning `Customer` with its `customer_id`, `serial_number`, `bore_mm`, `stroke_mm`, `rod_diameter_mm`, `pressure_class` (`CLASS_3000` or `CLASS_5000`), `fluid_type`, and configured `seal_kit_id`. A `Customer` actor must register with a `customer_id` equal to its own `X-User-ID`, failing which the request is rejected with `ERR_NOT_OWNER`. Registration validates seal-kit compatibility as a safety gate: the cylinder's `bore_mm` must fall within the kit's bore range with both bounds inclusive, the kit's `pressure_class_max` must cover the cylinder's `pressure_class` — a kit capped at `CLASS_3000` covers only `CLASS_3000` cylinders, while a `CLASS_5000` kit covers both classes — and the kit's `fluid_compat` must include the cylinder's `fluid_type`. A kit that fails any leg is rejected with `ERR_SEAL_KIT_INCOMPATIBLE`. A registered cylinder starts `ACTIVE` and later moves to `RETIRED` when scrapped or `EXCHANGED` when swapped for a remanufactured unit. The cylinder collection can be listed with filters on `customer_id`, `seal_kit_id`, and `status`.

### 3.2. Work-Order Intake and the Turnaround-Tier Gate

A repair begins when a `ShopAdmin`, a `ServiceAdvisor`, or the owning `Customer` opens a work order with the `cylinder_id` of the unit being serviced, a turnaround `tier` of `STANDARD`, `EXPEDITE`, or `EMERGENCY`, a `promised_hours` turnaround from intake, and a free-text `complaint` describing the reported fault. The system denormalizes the owning `customer_id` from the cylinder at creation, and the work order starts in `INTAKE` with `assigned_technician_id`, `actual_labor_hours`, `latest_cleanliness_code4`, `latest_cleanliness_code6`, `latest_cleanliness_code14`, `final_total_cents`, and `invoice_total_cents` all null, `cleanliness_passed` false, and `core_credit_applied_cents` zero.

Two intake guards apply before the tier gate. The referenced cylinder must be `ACTIVE`; opening a work order on a `RETIRED` or `EXCHANGED` unit is rejected with `ERR_CYLINDER_RETIRED`. The owning customer must not be `SUSPENDED`; attempting intake for one is rejected with `ERR_CUSTOMER_SUSPENDED`.

The turnaround-tier gate then checks the promise against the shop cutoffs, with both boundaries inclusive. When `promised_hours` is at most `emergency_cutoff_hours` — 24 hours by default — the `tier` must be `EMERGENCY`, so a promise of exactly 24 hours demands `EMERGENCY`. When `promised_hours` is greater than the emergency cutoff but at most `expedite_cutoff_hours` — 48 hours by default — the `tier` must be `EMERGENCY` or `EXPEDITE`, so a promise of exactly 48 hours accepts `EXPEDITE`. Beyond the expedite cutoff any tier is allowed. A request whose promised hours demand a faster tier than the one requested is rejected with `ERR_PROMISE_INFEASIBLE`.

Cancellation is an early-state privilege. A work order may be cancelled — with an optional `reason` — by a `ShopAdmin`, a `ServiceAdvisor`, or the owning `Customer` (whose `X-User-ID` must equal the work order's `customer_id`, else `ERR_NOT_OWNER`) while it is in `INTAKE`, `TEARDOWN`, `QUOTE_DRAFT`, `QUOTE_SENT`, or `REVISION_REQUESTED`, moving it to the terminal `CANCELLED` state. Cancelling from `QUOTE_DRAFT` supersedes the work order's `DRAFT` quote, and cancelling from `QUOTE_SENT` supersedes its `SENT` quote; cancelling from `INTAKE`, `TEARDOWN`, or `REVISION_REQUESTED` touches no quote. The work-order collection can be listed with filters on `cylinder_id`, `customer_id`, `status`, and `assigned_technician_id`.

### 3.3. Teardown Findings and Quote Drafting

From `INTAKE`, a `ShopAdmin` or `ServiceAdvisor` starts the teardown by naming a `technician_id`. The identifier must reference an existing technician — an unknown id is rejected with `ERR_NOT_FOUND` — and that technician must be `active` with `CYLINDER_REPAIR` among its `skills`, failing which the request is rejected with `ERR_INVALID_STATE`. Starting teardown sets `assigned_technician_id` to the named technician, moves the work order from `INTAKE` to `TEARDOWN`, and increments the work order's `version` by one.

The assigned `Technician` then files the teardown findings, supplying the `work_order_id`, whether `rod_needed` is set, the `rod_cut_length_mm` required when it is (mandatory exactly when `rod_needed` is true), whether `tube_needed` is set, the `tube_cut_length_mm` required when it is, a `honing_passes` count defaulting to zero, an optional `seal_kit_id` override that defaults to the cylinder's configured kit when omitted, an `estimated_labor_hours` figure, and free-text `findings_notes` defaulting to empty. When an override kit is named, its compatibility with the cylinder is re-validated under the same rules as registration, with `ERR_SEAL_KIT_INCOMPATIBLE` on failure. Exactly one teardown report exists per work order: a second filing for the same work order is rejected with `ERR_TEARDOWN_REPORT_EXISTS`. Filing creates the report at `version` 1 and cascades the work order from `TEARDOWN` to `QUOTE_DRAFT`.

Findings may be revised while the work order is in `QUOTE_DRAFT` or `REVISION_REQUESTED`; at any other stage the revision is rejected with `ERR_INVALID_STATE`. The revision payload carries `expected_teardown_report_version` per §2.6 plus any subset of the findings fields to change, increments the report's `version` by one, and has a deliberate downstream effect: any `DRAFT` quote pinned to an older report version is now stale, and sending it will fail with `ERR_TEARDOWN_STALE`. Teardown reports can be listed with filters on `work_order_id` and `seal_kit_id`.

A `ShopAdmin` or `ServiceAdvisor` drafts a quote against a work order by supplying its `work_order_id`. Drafting pins the teardown report current at that moment — the quote records it as `teardown_report_id` and its version as `pinned_teardown_version` — copies the work order's `tier` into `tier_snapshot` so that pricing always uses the snapshot even if the tier is later reinterpreted, computes the priced `line_items` and `provisional_total_cents` under the provisional pricing variant, and starts the quote in `DRAFT` with `sent_at` null. At most one quote per work order may be in `DRAFT` or `SENT`; drafting while another such quote exists is rejected with `ERR_ACTIVE_QUOTE_EXISTS`. Drafting while the work order is `REVISION_REQUESTED` is the revision loop: the prior `REVISION_REQUESTED` quote transitions to `SUPERSEDED` and the work order returns to `QUOTE_DRAFT`, completing the cycle `QUOTE_DRAFT` → `QUOTE_SENT` → `REVISION_REQUESTED` → `QUOTE_DRAFT`.

Provisional pricing at quote creation works as follows. The tier multiplier comes from `tier_snapshot`: 1.0 for `STANDARD`, the shop's `expedite_multiplier` for `EXPEDITE`, and `emergency_multiplier` for `EMERGENCY`. The seal-kit line is the `price_cents` of the kit named by the teardown's `seal_kit_id` when set, otherwise the cylinder's `seal_kit_id`. A rod line appears only when the teardown has `rod_needed` set: the `rod_cut_length_mm` multiplied by the shop's `default_chrome_rod_cost_per_mm_cents`, plus one flat `cut_fee_cents`. A tube line appears only when `tube_needed` is set, with the same shape — `tube_cut_length_mm` multiplied by `default_honing_tube_cost_per_mm_cents`, plus `cut_fee_cents`. The honing line is `honing_passes` multiplied by `honing_pass_fee_cents`. The labor line starts from a raw amount — `estimated_labor_hours` multiplied by `labor_rate_cents_per_hour` multiplied by the tier multiplier — and the line itself is that raw amount rounded half-up to integer cents. The supplies line is `supplies_pct_of_labor` multiplied by the raw, unrounded labor amount, rounded half-up to integer cents. Each entry of `line_items` carries a `kind` — one of `SEAL_KIT`, `ROD`, `TUBE`, `HONING`, `LABOR`, `SUPPLIES` — and an `amount_cents`. Per the pinned rounding order of §2.8, each line is rounded half-up to integer cents first and the lines are then summed into `provisional_total_cents`; the provisional variant prices materials at the shop's default per-millimetre estimates and carries no scrap line.

### 3.4. The Customer-Facing Quote Lifecycle

A `ShopAdmin` or `ServiceAdvisor` sends a drafted quote to the customer. Sending requires the work order to be in `QUOTE_DRAFT` — otherwise `ERR_INVALID_STATE` — and requires the quote's `pinned_teardown_version` to equal the teardown report's current `version`; a quote pinned to a superseded revision of the findings is rejected with `ERR_TEARDOWN_STALE`. Sending stamps `sent_at` with the current logical clock, moves the quote from `DRAFT` to `SENT`, and cascades the work order from `QUOTE_DRAFT` to `QUOTE_SENT`.

A sent quote lives for `quote_ttl_hours` — 168 hours, one week, by default — measured from `sent_at`. Expiry is lazy: there is no background sweep, but an approval attempt arriving after `sent_at` plus the lifetime flips the quote to `EXPIRED` and the attempt fails with `ERR_QUOTE_EXPIRED`.

Approval belongs to the owning `Customer` alone; a customer whose `X-User-ID` does not equal the work order's `customer_id` is rejected with `ERR_NOT_OWNER`, and an approval aimed at a quote that is not `SENT` — already approved, revised, superseded, expired, or rejected — is rejected with `ERR_QUOTE_NOT_APPROVABLE`. Approval then runs the fiscal exposure check: the open exposure is the sum of `provisional_total_cents` over the customer's `APPROVED` quotes whose work orders are not `CLOSED`, `CANCELLED`, or `SCRAPPED`, and that open exposure plus the provisional total of the quote being approved must not exceed the customer's `credit_limit_cents`. The boundary is inclusive — exposure exactly equal to the limit passes — and a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

An approved quote fires the material cascade. The quote moves from `SENT` to `APPROVED`, the work order moves from `QUOTE_SENT` to `APPROVED`, and the system automatically creates one `OPEN` stock reservation for the rod when the teardown's `rod_needed` is set — cut to `rod_cut_length_mm` from chrome-rod stock of the cylinder's `rod_diameter_mm` — and one for the tube when `tube_needed` is set — cut to `tube_cut_length_mm` from honing-tube stock of the cylinder's `bore_mm` — each allocated by the procedure in §3.5.

The owning `Customer` may instead request a revision, optionally attaching `notes`; this moves the quote from `SENT` to `REVISION_REQUESTED` and the work order from `QUOTE_SENT` to `REVISION_REQUESTED`, opening the revision loop of §3.3. Two other customer decisions end the quote from `SENT`: selecting an exchange unit supersedes it, and authorizing scrap moves it to `REJECTED_SCRAP`, both detailed in §3.8. Cancelling the work order supersedes its `SENT` quote as described in §3.2. Quotes can be listed with filters on `work_order_id`, `teardown_report_id`, and `status`.

### 3.5. Stock Cutting, Reservations, and Remnants

Chrome rod and honing tube are received into stock by a `ShopAdmin` or `ServiceAdvisor`, each length registered with a `material` of `CHROME_ROD` or `HONING_TUBE`, a `diameter_mm`, a `length_mm`, and a `cost_per_mm_cents`. New stock starts `AVAILABLE` with `origin` `RECEIVED`; pieces returned from released reservations carry `origin` `REMNANT`. The stock collection can be listed with filters on `material` and `status`.

Reservations are created two ways: automatically by the approval cascade of §3.4, or manually by a `ShopAdmin` or `ServiceAdvisor` supplying `work_order_id`, `material`, `diameter_mm`, and `cut_length_mm` (the required cut length, excluding kerf). Either way the same allocation procedure runs. The required length is the `cut_length_mm` plus the shop's `kerf_mm` — 3 millimetres of saw kerf per cut by default. Candidates are stock pieces of the requested material and diameter that are `AVAILABLE` with a `length_mm` of at least the required length. The selector picks the smallest sufficient piece — shortest `length_mm` first, ties broken by earliest `created_at` — and an empty candidate set is rejected with `ERR_NO_STOCK_FITS`. A created reservation records the shop's kerf as its own `kerf_mm`, starts `OPEN`, and begins with `scrap_length_mm` and `scrap_charge_cents` at zero and `consumed_length_mm` null.

Cutting depletes the selected piece and handles the remainder. The item's `length_mm` is reduced by the required length (cut plus kerf). When the remainder is shorter than `min_remnant_mm` — 300 millimetres by default — it is unusable: the remainder is recorded on the reservation as `scrap_length_mm`, charged as `scrap_charge_cents` equal to the scrap length multiplied by the item's `cost_per_mm_cents`, and the item is set to zero length and `DEPLETED`. The shop's stock ledger stays conservative throughout: the total millimetres ever received always equal the lengths still available, plus the cut lengths on `OPEN` and `CONSUMED` reservations, plus all recorded scrap, plus all kerf consumed.

The assigned `Technician` consumes a reservation when the material physically goes into the repair. Consuming requires the reservation to be `OPEN` — a reservation in any other state is rejected with `ERR_RESERVATION_NOT_OPEN` — and the linked work order to be `IN_REPAIR`, failing which the request is rejected with `ERR_INVALID_STATE`; a technician other than the assignee is rejected with `ERR_NOT_OWNER`. Consumption sets `consumed_length_mm` to the `cut_length_mm` and moves the reservation from `OPEN` to `CONSUMED`.

A `ShopAdmin` or `ServiceAdvisor` may instead release an `OPEN` reservation, moving it to `RELEASED`. When the reservation's `cut_length_mm` is at least `min_remnant_mm`, the cut piece returns to stock as a new `AVAILABLE` inventory item with `origin` `REMNANT`, a `length_mm` equal to the cut length, and the same material, diameter, and `cost_per_mm_cents` as the source piece. When the cut length is shorter than `min_remnant_mm`, the piece is scrapped instead: the reservation's `scrap_length_mm` is increased by the cut length and its `scrap_charge_cents` recomputed as the total scrap length multiplied by the source item's `cost_per_mm_cents`. Reservations can be listed with filters on `work_order_id`, `inventory_item_id`, and `status`.

### 3.6. Repair Execution and Contamination Control

Once the quote is `APPROVED`, the assigned `Technician` starts the physical repair, moving the work order from `APPROVED` to `IN_REPAIR`. The caller's `X-User-ID` must equal the work order's `assigned_technician_id`; anyone else is rejected with `ERR_NOT_OWNER`.

Contamination control runs throughout the repair. A `Technician` or `QualityInspector` records a fluid sample on the work order by supplying particle counts `c4_count`, `c6_count`, and `c14_count` for the three ISO 4406 channels. Each count maps to an ISO code: the code is zero when the count is zero, and otherwise the smallest whole-number code such that the count does not exceed two raised to the power of that code — the boundary is inclusive, so a count of exactly 8192 maps to code 13 while a count of 8193 maps to code 14. The sample passes when all three channels meet the shop targets: the code of `c4_count` at most `cleanliness_target_code4` (18 by default), the code of `c6_count` at most `cleanliness_target_code6` (16 by default), and the code of `c14_count` at most `cleanliness_target_code14` (13 by default). Recording a sample stores the three codes on the work order as `latest_cleanliness_code4`, `latest_cleanliness_code6`, and `latest_cleanliness_code14` and sets `cleanliness_passed` to whether the sample passed.

Marking assembly complete is gated hard. The caller must again be the assigned technician (`ERR_NOT_OWNER` otherwise). The work order's `cleanliness_passed` must be true — meaning a sample has been recorded and the latest sample met target on all three channels; with no sample on file the flag is false — otherwise the completion is rejected with `ERR_CLEANLINESS_CLASS_EXCEEDED`. Every stock reservation of the work order must be `CONSUMED`; any reservation not yet consumed is rejected with `ERR_RESERVATION_NOT_OPEN`. When all gates pass the work order moves from `IN_REPAIR` to `ASSEMBLED`.

### 3.7. Pressure Testing, Certification, and the Rework Loop

Pressure-test bays are registered by a `ShopAdmin`, each with a `name`. With the work order `ASSEMBLED`, a `QualityInspector` books a pressure test by supplying the `work_order_id`, the `test_bay_id`, and a booking `window_start` and `window_end`. Creation moves the work order from `ASSEMBLED` to `TEST_PENDING` and creates the test in `SCHEDULED` with its `required_hold_psi` computed at booking time: the shop's `pressure_test_factor` (1.5 by default) multiplied by the rated working pressure of the cylinder's pressure class — `rated_pressure_class_3000_psi` (3000 by default) for `CLASS_3000`, `rated_pressure_class_5000_psi` (5000 by default) for `CLASS_5000` — rounded half-up to a whole psi, which under the defaults yields a 4500 psi required hold for `CLASS_3000` and 7500 psi for `CLASS_5000`. The outcome fields `measured_hold_psi`, `duration_min`, and `leakage_drops` stay null until results are recorded. Tests can be listed with filters on `work_order_id`, `test_bay_id`, and `status`.

Bay bookings are closed intervals — both `window_start` and `window_end` are inclusive — and every booking additionally occupies the mandatory `bay_buffer_minutes` (30 minutes by default) of clearance on both sides of its window. A new booking whose buffer-extended interval collides with the buffer-extended interval of another booking of the same bay that is `SCHEDULED`, or that has passed but is still pending downstream resolution, is rejected with `ERR_TEST_BAY_WINDOW_OVERLAP`.

Re-entry into testing is the recovery path. A work order already in `TEST_PENDING` — because a scheduled test was cancelled or a certificate was revoked — may have a fresh test booked, provided no `SCHEDULED` test is currently outstanding for it; booking while one exists is rejected with `ERR_INVALID_STATE`. The re-test keeps the work order in `TEST_PENDING`.

Recording the result is a `QualityInspector` action carrying `measured_hold_psi`, `duration_min`, `leakage_drops`, and a `passed` flag. A pass claim is valid only when the measured hold pressure is at least `required_hold_psi` — the boundary is inclusive — the `duration_min` is at least `test_hold_min_minutes` (10 minutes by default), and `leakage_drops` is exactly zero; a `passed` claim that violates any leg is rejected with `ERR_PRESSURE_HOLD_INSUFFICIENT`. A valid pass moves the test from `SCHEDULED` to `PASSED` and the work order from `TEST_PENDING` to `TEST_PASSED`. A recorded failure moves the test to `FAILED` and loops the work order back from `TEST_PENDING` to `IN_REPAIR`, resetting `cleanliness_passed` to false while retaining the latest cleanliness codes for history; the rework cycle is then repair again, re-verify cleanliness, complete assembly again, and book a fresh test.

A scheduled test that will not run can be cancelled by a `QualityInspector` or `ShopAdmin`, moving it from `SCHEDULED` to `CANCELLED` and freeing its bay window.

Certification is the quality authority's signature on a passed test. A `QualityInspector` issues a certificate for a work order in `TEST_PASSED` by supplying its `work_order_id`. Segregation of duties is enforced: the issuing inspector's `X-User-ID` must differ from the work order's `assigned_technician_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. At most one `ISSUED` certificate may exist per work order; a second issuance is rejected with `ERR_CERTIFICATE_EXISTS`. The certificate is created `ISSUED`, its `pressure_test_id` set to the latest `PASSED` test of the work order and its `issued_by` set to the issuing inspector's `X-User-ID`; issuance cascades the work order from `TEST_PASSED` to `CERTIFIED`. Certificates can be listed with filters on `work_order_id`, `pressure_test_id`, and `status`.

Revocation unwinds certification. A `QualityInspector` revokes an `ISSUED` certificate by supplying a `reason`, which is recorded as `revoke_reason`, moving the certificate to the terminal `REVOKED` state. The revocation cascades: the work order falls back from `CERTIFIED` to `TEST_PENDING`, and the certificate's pressure test moves from `PASSED` to `VOIDED`. A fresh pressure test must then be booked and passed before the work order can be re-certified.

### 3.8. Scrap, the Exchange Pool, and Closing the Job

Two customer decisions divert a quoted repair. Authorizing scrap — available to the owning `Customer` while the work order is in `QUOTE_SENT` or `REVISION_REQUESTED` (`ERR_NOT_OWNER` for anyone else) — moves the work order to `SCRAP_AUTHORIZED`; when the decision comes from `QUOTE_SENT`, the `SENT` quote moves to `REJECTED_SCRAP`. Completing the scrap is then a `ShopAdmin` or `ServiceAdvisor` action that records a `disposal_method`; attempted before the customer's authorization it is rejected with `ERR_SCRAP_NOT_AUTHORIZED`, and on success the work order moves to the terminal `SCRAPPED` state and the cylinder cascades from `ACTIVE` to `RETIRED`.

The remanufactured exchange pool is stocked by a `ShopAdmin`, each unit registered with `bore_mm`, `stroke_mm`, `rod_diameter_mm`, `pressure_class`, and a `unit_price_cents`. A new unit starts `IN_POOL` with `work_order_id`, `provisional_credit_cents`, `condition`, `completeness`, and `final_credit_cents` all null. The pool can be listed with filters on `status`, `work_order_id`, and `bore_mm`.

While the work order is in `QUOTE_SENT`, the owning `Customer` may instead select an exchange unit by its `exchange_unit_id`. The unit must be `IN_POOL` — otherwise `ERR_UNIT_NOT_IN_POOL` — and its `bore_mm`, `stroke_mm`, `rod_diameter_mm`, and `pressure_class` must each exactly equal the cylinder's, otherwise `ERR_SPEC_MISMATCH`. Selection supersedes the `SENT` quote, moves the unit from `IN_POOL` to `RESERVED` with its `work_order_id` set to this work order, and moves the work order to `EXCHANGE_SELECTED`.

A reservation can be unwound: a `ShopAdmin` or `ServiceAdvisor` releases a `RESERVED` unit back to `IN_POOL`, clearing its `work_order_id` and `provisional_credit_cents`, while the linked work order remains `EXCHANGE_SELECTED` and may select another unit — the reserve-release cycle `IN_POOL` → `RESERVED` → `IN_POOL`. Fulfilment is the point of no return: a `ShopAdmin` or `ServiceAdvisor` fulfils a `RESERVED` unit, which requires the linked work order to be `EXCHANGE_SELECTED` for this unit (otherwise `ERR_INVALID_STATE`). Fulfilment moves the unit to `FULFILLED`, computes its `provisional_credit_cents` under the provisional core-credit variant — which assumes the returned core will grade `GOOD` and `COMPLETE` — cascades the cylinder from `ACTIVE` to `EXCHANGED`, and moves the work order from `EXCHANGE_SELECTED` to `EXCHANGE_FULFILLED`.

The customer's old unit then comes back as the core. A `ShopAdmin` or `ServiceAdvisor` logs its arrival, moving the deal from `FULFILLED` to `CORE_RECEIVED`; attempting to receive a core before fulfilment is rejected with `ERR_EXCHANGE_NOT_FULFILLED`. A `QualityInspector` grades the received core with a `condition` of `GOOD`, `WORN`, `DAMAGED`, or `SCRAP` and a `completeness` of `COMPLETE` or `MISSING_PARTS`, which settles the deal — the unit moves from `CORE_RECEIVED` to the terminal `SETTLED` state — and computes `final_credit_cents` under the final core-credit variant.

Core credit is computed the same way in both variants, differing only in the assumed grades. The base value steps with the unit's bore: `core_base_small_cents` (40000 by default) when the bore is at most `core_bore_medium_max_mm` (100 millimetres by default), `core_base_medium_cents` (90000 by default) when it is greater than that boundary but at most `core_bore_large_max_mm` (200 millimetres by default), and `core_base_large_cents` (160000 by default) beyond that — both boundaries inclusive. The condition factor is 1.0 for `GOOD`, 0.6 for `WORN`, 0.25 for `DAMAGED`, and 0.0 for `SCRAP`; the completeness factor is 1.0 for `COMPLETE` and 0.5 for `MISSING_PARTS`. The uncapped credit is the base multiplied by both factors, rounded half-up to integer cents. The cap is `exchange_credit_cap_pct` (0.30 by default) of the unit's `unit_price_cents`, rounded half-down — truncated at a half-cent — per §2.8. The credit is the lesser of the two, never below zero. The provisional variant at fulfilment assumes `GOOD` and `COMPLETE`; the final variant at grading uses the inspected values and may diverge arbitrarily from the provisional figure. A core graded `SCRAP` earns zero credit and instead adds a `core_disposal_fee_cents` charge (7500 by default) at the work order's close.

Closing is a `ShopAdmin` or `ServiceAdvisor` action that always carries `actual_labor_hours` and has exactly two legal from-states. On the repair path the work order must be `CERTIFIED`, and `actual_labor_hours` must be a positive number. Closing computes the final pricing variant: the same line structure and rounding order as the provisional variant of §3.3, but the labor line uses `actual_labor_hours` in place of the estimate, the rod and tube lines price the consumed reservation's `consumed_length_mm` at the consumed item's actual `cost_per_mm_cents` — still plus one flat `cut_fee_cents` each — and a scrap line is added summing `scrap_charge_cents` across all of the work order's reservations. Each line rounds half-up to integer cents before the lines sum into `final_total_cents`. The invoice then settles per the waterfall below, and the customer's `ytd_spend_cents` increases by the resulting `invoice_total_cents`.

On the exchange path the work order must be `EXCHANGE_FULFILLED` and its exchange unit must have reached `SETTLED`; closing before the core deal settles is rejected with `ERR_CORE_NOT_RETURNED`. The invoice is the unit's `unit_price_cents` minus its `final_credit_cents`, plus the `core_disposal_fee_cents` when the core's `condition` is `SCRAP`; `core_credit_applied_cents` records the `final_credit_cents` actually applied, and the customer's `ytd_spend_cents` again increases by `invoice_total_cents`. Either way the work order moves to the terminal `CLOSED` state, and only then are `final_total_cents` (repair path) and `invoice_total_cents` no longer null.

The repair-path invoice waterfall evaluates in a pinned order. The subtotal is the work order's `final_total_cents`. The loyalty tier is tested against the customer's `ytd_spend_cents` before this invoice plus the pre-discount subtotal: the tier is `GOLD` when that sum is at least `loyalty_gold_threshold_cents` (500000 by default), else `SILVER` when at least `loyalty_silver_threshold_cents` (100000 by default), else `NONE`. The discount is the subtotal multiplied by the tier's percentage — `loyalty_gold_pct` (0.10) for `GOLD`, `loyalty_silver_pct` (0.05) for `SILVER`, zero for `NONE` — rounded half-up to integer cents, and the discounted subtotal is the subtotal minus the discount. The environmental fee is the greater of `env_fee_min_cents` (500 by default) and the discounted subtotal multiplied by `env_fee_pct` (0.02 by default) rounded half-up to integer cents. The `invoice_total_cents` is the discounted subtotal plus the environmental fee.

### 3.9. Field Service and Hose Crimping

A field service job is booked by a `ShopAdmin`, a `ServiceAdvisor`, or the owning `Customer`, supplying the `customer_id`, the `site_address`, the round-trip `distance_km`, and an `assemblies` array. Each assembly entry carries a `hose_type` of `WIRE_BRAID_2SN`, `SPIRAL_4SH`, or `THERMOPLASTIC`, a `length_m`, a `fitting_price_cents`, a `crimp_spec_mm`, a `crimp_measured_mm` that stays null until measured on site, and an `assembly_result` that starts `PENDING` and later resolves to `PASS` or `FAIL`. A new job starts `REQUESTED` with `technician_id`, `window_start`, and `window_end` null, `emergency_callout` false, and `final_price_cents` null; its `provisional_price_cents` is computed at creation under the provisional field-pricing variant, which assumes a non-emergency callout. Jobs can be listed with filters on `customer_id`, `technician_id`, and `status`.

Field pricing aggregates three components. Each assembly bills `crimp_fee_cents` (4500 by default) plus a hose term plus twice its `fitting_price_cents`; the hose term is the assembly's `length_m` multiplied by the per-metre rate of its `hose_type` — `hose_price_wire_braid_2sn_cents_per_m` (3200 by default), `hose_price_spiral_4sh_cents_per_m` (5700 by default), or `hose_price_thermoplastic_cents_per_m` (1800 by default) — rounded half-up to integer cents before any summing. Mileage is the excess of `distance_km` over `mileage_free_km` (50 kilometres by default), floored at zero, multiplied by `mileage_rate_cents_per_km` (250 by default). The callout is `callout_base_cents` (25000 by default) multiplied by `emergency_callout_multiplier` (2.0 by default) when the job is an emergency callout, and unmultiplied otherwise. The total is the callout plus the sum of the per-assembly charges plus the mileage. The provisional variant at creation assumes a non-emergency callout; the final variant at completion uses the `emergency_callout` flag as computed at schedule time.

Scheduling is done by a `ShopAdmin` or `ServiceAdvisor` supplying the `technician_id`, the `window_start`, the `window_end`, and `expected_technician_version` per §2.6 — a stale technician version is rejected with `ERR_STALE_VERSION`. The named technician must be `active` with `FIELD_SERVICE` among its `skills`, otherwise `ERR_INVALID_STATE`. The `window_start` must not lie before the current logical clock — a window starting exactly now is acceptable — otherwise `ERR_WINDOW_IN_PAST`. Field windows are half-open intervals, including their start and excluding their end, so two windows that merely touch at an endpoint do not collide; any true overlap with another `SCHEDULED` or `DISPATCHED` job of the same technician is rejected with `ERR_TECHNICIAN_WINDOW_OVERLAP`. Scheduling moves the job from `REQUESTED` to `SCHEDULED`, sets `technician_id` and the window, computes `emergency_callout` — true exactly when the gap between the job's `created_at` and its `window_start` is at most `emergency_callout_window_hours` (4 hours by default), the boundary inclusive — and increments the technician's `version` by one.

The assigned `Technician` dispatches the job, moving it from `SCHEDULED` to `DISPATCHED`; a caller whose `X-User-ID` is not the job's `technician_id` is rejected with `ERR_NOT_OWNER`. On site, the same technician completes the job by submitting `crimp_measurements`. Each measurement is written to its assembly's `crimp_measured_mm` and judged against the assembly's `crimp_spec_mm`: a deviation of at most `crimp_tolerance_mm` (0.3 millimetres by default), inclusive, passes. When every assembly is within tolerance, the assemblies resolve to `PASS`, the job moves from `DISPATCHED` to the terminal `COMPLETED` state, and `final_price_cents` is computed under the final pricing variant. When any assembly is out of tolerance the completion is rejected with `ERR_CRIMP_OUT_OF_TOLERANCE` — and the measurements still persist, the out-of-tolerance assemblies are marked `FAIL`, and the job remains `DISPATCHED` for correction and a later completion attempt.

A job may be cancelled from `REQUESTED` or `SCHEDULED` by a `ShopAdmin`, a `ServiceAdvisor`, or the owning `Customer` (else `ERR_NOT_OWNER`), with an optional `reason`, moving it to the terminal `CANCELLED` state; cancelling a `SCHEDULED` job frees the technician's window.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a shop, customer, technician, seal kit, cylinder, work order, teardown report, quote, inventory item, stock reservation, test bay, pressure test, certificate, exchange unit, or field service job — return a `201 Created` status code. Operations that modify an existing resource in place, including every state-transition action, the shop and teardown-report updates, and the clock-set capability, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fluid-power/_clock/set_current_utc` | Set the logical clock | ShopAdmin |
| POST | `/fluid-power/shops` | Create the shop configuration | ShopAdmin |
| GET | `/fluid-power/shops/{id}` | Get the shop configuration | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| PATCH | `/fluid-power/shops/{id}` | Update the shop configuration (OCC-guarded) | ShopAdmin |
| POST | `/fluid-power/customers` | Register a customer | ShopAdmin, ServiceAdvisor |
| GET | `/fluid-power/customers/{id}` | Get a customer | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/customers/{id}/suspend` | Suspend a customer | ShopAdmin |
| POST | `/fluid-power/customers/{id}/reactivate` | Reactivate a suspended customer | ShopAdmin |
| POST | `/fluid-power/technicians` | Onboard a technician | ShopAdmin |
| GET | `/fluid-power/technicians/{id}` | Get a technician | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/seal-kits` | Create a seal-kit catalog entry | ShopAdmin |
| GET | `/fluid-power/seal-kits/{id}` | Get a seal kit | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/cylinders` | Register a cylinder with spec and seal-kit configuration | ShopAdmin, ServiceAdvisor, Customer |
| GET | `/fluid-power/cylinders/{id}` | Get a cylinder | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/cylinders` | List cylinders with filters | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/work-orders` | Open a repair work order | ShopAdmin, ServiceAdvisor, Customer |
| GET | `/fluid-power/work-orders/{id}` | Get a work order | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/work-orders` | List work orders with filters | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/work-orders/{id}/start-teardown` | Assign a technician and begin teardown | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/work-orders/{id}/cancel` | Cancel a work order (early states only) | ShopAdmin, ServiceAdvisor, Customer |
| POST | `/fluid-power/work-orders/{id}/authorize-scrap` | Customer authorizes scrapping instead of repair | Customer |
| POST | `/fluid-power/work-orders/{id}/complete-scrap` | Record disposal and close out the scrap | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/work-orders/{id}/start-repair` | Begin the physical repair after approval | Technician |
| POST | `/fluid-power/work-orders/{id}/complete-assembly` | Mark assembly complete | Technician |
| POST | `/fluid-power/work-orders/{id}/cleanliness-checks` | Record a contamination sample | Technician, QualityInspector |
| POST | `/fluid-power/work-orders/{id}/select-exchange` | Customer elects a remanufactured exchange unit | Customer |
| POST | `/fluid-power/work-orders/{id}/close` | Close a certified repair or a settled exchange | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/teardown-reports` | File teardown findings | Technician |
| GET | `/fluid-power/teardown-reports/{id}` | Get a teardown report | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/teardown-reports` | List teardown reports | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| PATCH | `/fluid-power/teardown-reports/{id}` | Revise teardown findings (OCC-guarded) | Technician |
| POST | `/fluid-power/quotes` | Draft a quote from the current teardown report | ShopAdmin, ServiceAdvisor |
| GET | `/fluid-power/quotes/{id}` | Get a quote | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/quotes` | List quotes | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/quotes/{id}/send` | Send the quote to the customer | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/quotes/{id}/approve` | Customer approves the quote | Customer |
| POST | `/fluid-power/quotes/{id}/request-revision` | Customer requests a quote revision | Customer |
| POST | `/fluid-power/inventory-items` | Receive a chrome-rod or honing-tube stock length | ShopAdmin, ServiceAdvisor |
| GET | `/fluid-power/inventory-items/{id}` | Get an inventory item | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/inventory-items` | List stock | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/stock-reservations` | Manually reserve and cut stock for a work order | ShopAdmin, ServiceAdvisor |
| GET | `/fluid-power/stock-reservations/{id}` | Get a reservation | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/stock-reservations` | List reservations | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/stock-reservations/{id}/consume` | Mark reserved material consumed by the repair | Technician |
| POST | `/fluid-power/stock-reservations/{id}/release` | Release a reservation back to stock or scrap | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/test-bays` | Register a pressure-test bay | ShopAdmin |
| GET | `/fluid-power/test-bays/{id}` | Get a test bay | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/pressure-tests` | Book and create a pressure test | QualityInspector |
| GET | `/fluid-power/pressure-tests/{id}` | Get a pressure test | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/pressure-tests` | List pressure tests | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/pressure-tests/{id}/record-result` | Record the test outcome | QualityInspector |
| POST | `/fluid-power/pressure-tests/{id}/cancel` | Cancel a scheduled test | QualityInspector, ShopAdmin |
| POST | `/fluid-power/certificates` | Issue a test certificate | QualityInspector |
| GET | `/fluid-power/certificates/{id}` | Get a certificate | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/certificates` | List certificates | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/certificates/{id}/revoke` | Revoke a certificate | QualityInspector |
| POST | `/fluid-power/exchange-units` | Add a remanufactured unit to the exchange pool | ShopAdmin |
| GET | `/fluid-power/exchange-units/{id}` | Get an exchange unit | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/exchange-units` | List exchange-pool units | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/exchange-units/{id}/release` | Unreserve a unit back into the pool | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/exchange-units/{id}/fulfill` | Hand the reserved unit to the customer | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/exchange-units/{id}/receive-core` | Log return of the customer's core unit | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/exchange-units/{id}/evaluate-core` | Grade the returned core and settle the deal | QualityInspector |
| POST | `/fluid-power/field-service-jobs` | Book an on-site hose-crimping job | ShopAdmin, ServiceAdvisor, Customer |
| GET | `/fluid-power/field-service-jobs/{id}` | Get a field service job | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| GET | `/fluid-power/field-service-jobs` | List field service jobs | ShopAdmin, ServiceAdvisor, Technician, QualityInspector, Customer |
| POST | `/fluid-power/field-service-jobs/{id}/schedule` | Assign a technician and window (OCC on the technician) | ShopAdmin, ServiceAdvisor |
| POST | `/fluid-power/field-service-jobs/{id}/dispatch` | Dispatch the assigned technician | Technician |
| POST | `/fluid-power/field-service-jobs/{id}/complete` | Record crimp measurements and complete | Technician |
| POST | `/fluid-power/field-service-jobs/{id}/cancel` | Cancel a field service job | ShopAdmin, ServiceAdvisor, Customer |

## 5. Error Code Catalogue

The catalogue below lists every error identifier with its HTTP status code. The conditions that trigger each error are specified in the narratives of §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_QUOTE_NOT_APPROVABLE` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_ACTIVE_QUOTE_EXISTS` | 409 Conflict |
| `ERR_TEARDOWN_REPORT_EXISTS` | 409 Conflict |
| `ERR_TEARDOWN_STALE` | 409 Conflict |
| `ERR_SCRAP_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_CYLINDER_RETIRED` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_CLEANLINESS_CLASS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_PRESSURE_HOLD_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CRIMP_OUT_OF_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_SEAL_KIT_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_TEST_BAY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TECHNICIAN_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_IN_PAST` | 409 Conflict |
| `ERR_PROMISE_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_SPEC_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_STOCK_FITS` | 409 Conflict |
| `ERR_UNIT_NOT_IN_POOL` | 409 Conflict |
| `ERR_RESERVATION_NOT_OPEN` | 409 Conflict |
| `ERR_CERTIFICATE_EXISTS` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_EXCHANGE_NOT_FULFILLED` | 409 Conflict |
| `ERR_CORE_NOT_RETURNED` | 409 Conflict |

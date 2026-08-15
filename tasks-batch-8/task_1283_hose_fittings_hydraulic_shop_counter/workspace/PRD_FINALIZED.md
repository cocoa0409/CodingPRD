# Hose Fittings Hydraulic Counter API — Product Requirements Document

## 1. Introduction

A hydraulic hose counter lives and dies by two things: how quickly a blown hose gets replaced, and how defensible the paperwork is when a replacement fails in the field. This document specifies the Hose Fittings Hydraulic Counter API, the system of record for a Parker Store-style operation that cuts bulk hose to length, crimps couplings onto each end, pressure-tests and tags every assembly, and dispatches mobile service vans for emergency field replacement. Every assembly that leaves the counter carries a certification trail — a measured crimp diameter checked against a die-chart specification, a pressure test at double the application's working pressure, and a serialized tag — because the shop's liability exposure depends on being able to prove exactly what was built and how it was verified.

Beyond the counter workflow itself, the system administers a customer hose-management program. Customers enroll their equipment fleets, the shop schedules periodic inspections of every asset, and a compliance score tracks how well each customer keeps up with inspection obligations. Customers in good standing earn a discount on assembly orders; customers who let inspections lapse slide into probation and lose it. The API therefore spans the full commercial and technical lifecycle: customer and fleet registration, bulk reel and coupling inventory with cut-length waste accounting, assembly orders with both quoted and final pricing, liability waivers for suspected customer misapplication, inspection scheduling protected by optimistic concurrency, and emergency dispatch booking with per-van window conflict enforcement. All endpoints are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled as follows: `ShopManager`, `CounterSales`, `ShopTechnician`, `FieldTechnician`, and `Customer`. Each endpoint admits a fixed set of roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role responsibilities divide the shop along natural lines. The `ShopManager` owns the catalog and the customer book: only a manager registers customers and updates their flags, receives and retires hose reels, registers couplings and posts stock receipts, decommissions equipment assets, and sets the logical clock. `CounterSales` runs the counter itself: drafting, confirming, completing, and cancelling assembly orders, registering equipment assets, booking emergency dispatches, and scheduling inspections. The `ShopTechnician` owns the build bench — completing builds, recording pressure tests, sending failed assemblies to rework, and attaching certification tags. The `FieldTechnician` works the road: advancing, completing, and aborting dispatches (the abort capability is shared with `ShopManager`) and performing inspections. For each of these four roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any resource's `id`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record, and ownership checks on any resource that references a customer compare the resource's `customer_id` field against `X-User-ID`. A portal customer reads only their own account record, their own equipment assets and those assets' inspections, and their own assembly orders with their order lines; reaching for a resource owned by another customer is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

Endpoints that return lists of resources paginate through two query parameters. The `limit` parameter caps how many items come back; it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every top-level resource in the system — customers, equipment assets, reels, couplings, assembly orders, inspections, and service dispatches — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed whenever the resource is modified.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource.

Assembly order lines are the sole exception: a line carries only `id` and `created_at`. Both `updated_at` and `version` are absent from lines, because a line never changes once the order that owns it has been created.

Side-effect cascades count as modifications. When one operation recomputes derived fields on a related resource — an inspection completion refreshing an asset's posture and the customer's scores, for instance — each resource so touched refreshes its own `updated_at` and increments its own `version`.

### 2.5. The Logical Clock

All time-dependent behavior in the system reads a single server-side logical clock rather than wall-clock time: due-date arithmetic on assets, compliance posture evaluation, the overdue flag stamped on completed inspections, the installation timestamp written when an assembly is completed onto an asset, and the forward-looking window check inside the projected compliance score. Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own.

A manager-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant, and the response reports the resulting `current_utc`. Every subsequent clock read returns the set instant until the clock is set again.

### 2.6. Money, Cents, and the Pinned Rounding Order

Every monetary value in the system is an integer number of cents: catalog prices, coupling line totals, the waste surcharge, the program discount, and both order totals. Where a computed component could land on a fraction of a cent, it is rounded half up to whole cents — and, critically, each component is rounded on its own before any summation takes place.

The rounding order is pinned. First, the hose material component is rounded to whole cents. Coupling line totals are exact integer cents by construction and require no rounding. Third, the labor component is rounded. Fourth, the waste surcharge is rounded. The subtotal is then the plain integer sum of those four components, with no further rounding. A program discount, when one applies, is computed from that subtotal and rounded half up as the very last rounding step; the order total is the subtotal minus the discount. Rounding only the final sum — skipping the per-component rounding — yields different cents whenever the hose and waste components both carry fractional cents, and that alternative is not permitted.

### 2.7. Reel Length Accounting and the Cut-Waste Policy

Reel inventory is a length ledger kept in integer millimeters, with no rounding anywhere in it. Two constants govern every cut a reel will ever see. A remnant shorter than 1,000 millimeters — one meter — is too short to sell again and must be scrapped. A reel whose remaining length falls below 20,000 millimeters — twenty meters — is considered to be running low and is flagged accordingly.

These constants define the reel's status ladder. A reel is `AVAILABLE` while its remaining length is at least twenty meters. It becomes `LOW` once the remainder drops below twenty meters but still reaches at least one meter. Below one meter it is `DEPLETED`, and no further order can be confirmed against it. `RETIRED` is a terminal state reached only through a manager's deliberate retire action, never through length arithmetic. Status moves are automatic in both directions: confirming an order can push a reel down the ladder, and cancelling a confirmed order can bring a `DEPLETED` reel back to `LOW` or even `AVAILABLE`.

### 2.8. Pressure Integrity, Crimp Certification, and Liability Waivers

Pressure integrity is the counter's first safety law: the application's working pressure may never exceed what the bulk hose is rated for, and the system enforces this at order confirmation time rather than at quoting time.

Certification testing doubles down on the same principle. Every recorded pressure test must apply a pressure of at least twice the order's required working pressure; a test run below that multiple proves nothing and is refused outright, whether the result being recorded is a pass or a fail.

Crimp certification works against a die-chart specification. Each order carries its required crimp diameter and an allowed tolerance on it, and the measured diameter of the finished crimp must land within that tolerance band in either direction before the build is accepted.

When the shop suspects the customer has misapplied the assembly — undersized hose for the duty, the wrong fitting geometry — the sale may still proceed, but only behind a signed liability waiver. The waiver captures the signer's name and a liability cap in cents, and confirmation of a flagged order is impossible without it.

### 2.9. Scheduling Windows and Conflict Arithmetic

Two kinds of scheduling windows exist in the system, with deliberately different overlap semantics.

A service dispatch books a **half-open** window on a van: the window's start is inclusive and its end is exclusive. A new dispatch conflicts with an existing one on the same van whenever the two windows genuinely overlap — the new window starts before the existing window ends and ends after the existing window starts — considering only existing dispatches that are still live. Because the intervals are half-open, touching endpoints are allowed: a window that begins exactly when another ends, or ends exactly when another begins, does not conflict.

An inspection window on an equipment asset is a **closed** interval, and its conflict check runs only against inspections currently in progress on that same asset. Here touching endpoints do count as overlap: a new window that begins exactly when an in-progress inspection's window ends is still a conflict.

For both kinds, the window's end must be strictly after its start; an empty or inverted window is rejected at booking time.

### 2.10. Optimistic Concurrency Control

Exactly one operation in the system is guarded by optimistic concurrency control: scheduling an inspection against an equipment asset. The request must carry `expected_equipment_asset_version`, holding the asset `version` the client last observed. If that value does not match the asset's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The reason this operation alone earns the guard is its blast radius. Creating an inspection legitimately rewrites the asset's inspection calendar — every still-scheduled prior inspection of the same asset is superseded atomically with the create — and the act of doing so increments the asset's `version` by one. A client carrying a previously observed version is therefore, by definition, looking at a stale calendar, and the rejection prevents it from unknowingly discarding someone else's scheduling work. No other endpoint takes a version field; requests elsewhere in the API carry no concurrency token at all.

### 2.11. The Validation Ladder and Nested Resource Retrieval

Every request walks a fixed ladder of checks, and the first failing rung produces the response — later rungs are never evaluated. Authentication comes first: missing or unrecognized credentials fail as `ERR_UNAUTHENTICATED`. Authorization follows: a role not admitted by the endpoint, or a portal customer reaching past their own account, fails as `ERR_FORBIDDEN`. Existence comes third, and then the state rungs: the assembly-order terminal lockdown (any action against a `COMPLETED` or `CANCELLED` order fails with `ERR_ORDER_TERMINAL`), general state-transition legality (`ERR_INVALID_STATE`), and the optimistic-concurrency check from §2.10 (`ERR_STALE_VERSION`).

Business rules occupy the lower rungs, evaluated in this relative order: the safety rules first (pressure rating, waiver presence, crimp tolerance, and test pressure — `ERR_PRESSURE_RATING_MISMATCH`, `ERR_WAIVER_REQUIRED`, `ERR_CRIMP_OUT_OF_TOLERANCE`, `ERR_TEST_PRESSURE_TOO_LOW`); then the temporal and uniqueness rules (`ERR_INVALID_WINDOW`, `ERR_VAN_WINDOW_CONFLICT`, `ERR_INSPECTION_WINDOW_CONFLICT`, `ERR_TAG_SERIAL_TAKEN`); then the referential rules (`ERR_REEL_NOT_USABLE`, `ERR_ASSET_NOT_ACTIVE`); then the fiscal rules (`ERR_CREDIT_HOLD`, `ERR_INSUFFICIENT_REEL_LENGTH`, `ERR_INSUFFICIENT_COUPLING_STOCK`). Dead last comes malformed-request validation — a missing required field, an invalid enum value, or an out-of-range numeric input — surfaced as `ERR_INVALID_REQUEST` (HTTP 400) only after every applicable business rule has passed.

Existence checking is hierarchical and ordered. For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`. A request for inspections under a non-existent asset therefore fails with `ERR_ASSET_NOT_FOUND` before any inspection-level rule is even considered. Foreign keys supplied in a request body — a `customer_id`, `reel_id`, `equipment_asset_id`, a line-level `coupling_id`, or an `installed_assembly_order_id` — receive the same treatment once the path identifiers have resolved.

## 3. Business Logic & Workflows

### 3.1. The Customer Book and Fleet Registration

Everything at the counter starts with the customer book. A `ShopManager` registers a customer with a `name` and four optional flags: `credit_hold`, which defaults to false and, while true, blocks both order confirmation and dispatch booking; `program_enrolled`, which defaults to false and marks membership in the hose-management program; `program_discount_pct`, a fractional discount rate such as 0.10 that defaults to 0; and `inspection_interval_days`, the number of days between required hose inspections for this customer's assets, which defaults to 365 and must be at least 1. A freshly registered customer starts with both compliance scores at 100.00, and its `program_status` is derived immediately. Updates follow the same shape: a manager may revise the `name` or any of the flags, and when enrollment or the inspection interval changes, `program_status` is re-derived — an interval change additionally recomputes the `next_due_date` on each of the customer's assets. Reading a customer returns the account together with its computed `compliance_score_strict`, `compliance_score_projected`, and `program_status`.

Fleet registration ties machines to the book. A `ShopManager` or `CounterSales` operator registers an equipment asset with a payload containing the owning `customer_id`, a customer-visible `asset_tag`, and a `machine_type` describing the machine class — an excavator, a press, and so on. The optional `installed_at` exists for program enrollment of an existing fleet, letting the shop backfill when the current hose was installed; the system overwrites it later if an assembly order naming this asset runs to completion. New assets begin life `ACTIVE`, and registration immediately computes the asset's `next_due_date` and `compliance_posture` and recomputes the owning customer's compliance scores. The asset list can be filtered by `customer_id`, by `status`, or by `installed_assembly_order_id` to find which machine a given order was installed onto.

Decommissioning is a manager-only, terminal move from `ACTIVE` to `DECOMMISSIONED`. A decommissioned asset drops out of the denominator of every compliance score and keeps the last compliance posture it computed, but it is barred from further use everywhere: scheduling a new inspection against it, starting an inspection on it, drafting an assembly order that names it, and completing an order onto it are all rejected with `ERR_ASSET_NOT_ACTIVE`.

### 3.2. Stocking the Shop: Reels and Couplings

Bulk hose arrives on reels, and receiving one is a manager-only action. The receipt registers the `hose_sku` product code, the `hose_diameter_in` inner diameter — which later selects the labor rate tier at pricing time — the rated `working_pressure_psi`, a `price_per_meter_cents` material price, and the `initial_length_mm` received, which must be at least 1. The reel's `remaining_length_mm` initializes to the full received length, `scrap_length_mm` starts at zero, and the fresh reel's `status` is assigned by applying the status ladder from §2.7 to the full received length — a reel received with at least twenty meters starts `AVAILABLE`, one below twenty meters but still reaching at least one meter starts `LOW`, and one below one meter starts `DEPLETED`.

Retiring a reel is the manager's terminal say-so, available from `AVAILABLE`, `LOW`, or `DEPLETED` alike. A `RETIRED` reel can no longer be confirmed against — confirmation attempts fail with `ERR_REEL_NOT_USABLE` — but orders already committed against the reel are unaffected and run their course.

Couplings enter the catalog with a `coupling_sku`, a `size_in` fitting size, a `unit_price_cents` sell price, and an `initial_on_hand_qty` that may be zero or more; the physical stock counter `on_hand_qty` seeds from that initial count. Additional stock arrives through receipts, each of which adds its `quantity` to `on_hand_qty`. Stock visibility runs through two derived counters: `reserved_qty` is the sum of line quantities across every assembly order currently in `CONFIRMED`, `BUILT`, `TEST_PASSED`, `TEST_FAILED`, `REWORK`, or `TAGGED` status, and `available_qty` is what remains of `on_hand_qty` after reservations are subtracted. Counter staff can read a coupling together with both derived counters, and can list the order lines referencing a given coupling to see exactly where its stock is committed.

### 3.3. Drafting, Quoting, and Confirming an Assembly Order

An assembly order is drafted by a `CounterSales` operator or the `ShopManager`. The payload names the `customer_id` and the source `reel_id`; an optional `equipment_asset_id` targets the assembly at a specific machine, and when it is present that asset must be `ACTIVE` or the create is rejected with `ERR_ASSET_NOT_ACTIVE`. The build specification carries the `cut_length_mm` requested (at least one millimeter), the application's `required_working_pressure_psi`, and the die-chart `crimp_diameter_spec_mm`, plus two overridable defaults: `crimp_tolerance_mm` at 0.2 millimeters and `crimp_count` at two crimped ends. The commercial inputs are the `estimated_labor_minutes` quote, the `is_emergency` flag for after-hours builds, and the `application_error_suspected` flag raised when the shop believes the customer is misapplying the hose; both flags default to false when omitted. An optional `lines` collection attaches couplings to the build, each line naming a `coupling_id` and a `quantity` of at least one. Every line snapshots the coupling's current `unit_price_cents` at the moment of creation, and each `line_total_cents` is the quantity multiplied by that snapshot — exact integer cents, no rounding required. Each line also records its owning order in `assembly_order_id`. The order list can be filtered by `customer_id`, `reel_id`, `equipment_asset_id`, or `status`, and the order's lines can be listed on their own.

Drafting fixes the quote. The hose material charge, `material_hose_cents`, converts the `cut_length_mm` to meters by dividing by one thousand, multiplies by the reel's `price_per_meter_cents`, and rounds half up to whole cents; it is computed once at creation. The coupling component, `material_couplings_cents`, is the exact sum of the order's line totals. The labor rate per minute comes off the reel's `hose_diameter_in`: 150 cents per minute when the diameter is no more than half an inch, 200 cents per minute when it is greater than half an inch but no more than one inch, and 260 cents per minute when it exceeds one inch. The labor component multiplies the minutes by that rate and, for an emergency build, additionally by one and a half, rounding half up to whole cents. The waste surcharge, `waste_surcharge_cents`, converts `scrap_charged_mm` to meters and multiplies by the reel's per-meter price, again rounding half up; it is zero at draft because nothing has been scrapped yet. Following the pinned order of §2.6, the subtotal sums these four components, and when the customer's `program_status` is `ACTIVE` a discount equal to the subtotal multiplied by the customer's `program_discount_pct`, rounded half up, comes off; otherwise the discount is zero. The result lands in `quoted_total_cents`, computed from `estimated_labor_minutes` and fixed at creation. Its sibling, `final_total_cents`, stays null until the order completes — it will use the same formula with `actual_labor_minutes` in place of the estimate, so the two totals diverge whenever the recorded labor differs from the quoted labor.

Confirmation is where a `DRAFT` order becomes a commitment, and it enforces its checks in a fixed sequence behind the generic ladder of §2.11 — an order in any state other than `DRAFT` fails with `ERR_INVALID_STATE`, and one already `COMPLETED` or `CANCELLED` fails with `ERR_ORDER_TERMINAL`. The application-pressure check runs first, so an over-pressure request surfaces `ERR_PRESSURE_RATING_MISMATCH` rather than being masked by a later failure: the order's `required_working_pressure_psi` must not exceed the reel's rated `working_pressure_psi`. Second comes the waiver rule: when the order was drafted with `application_error_suspected` set, the confirmation payload must supply both `waiver_signed_by` and `waiver_liability_cents`, and the request fails with `ERR_WAIVER_REQUIRED` if either is missing. Third, the reel must be usable — `AVAILABLE` or `LOW`, never `DEPLETED` or `RETIRED` — or the confirm is rejected with `ERR_REEL_NOT_USABLE`. Fourth, the customer's `credit_hold` must be false, with violations rejected as `ERR_CREDIT_HOLD` (HTTP 402). Fifth, the `cut_length_mm` must not exceed the reel's `remaining_length_mm` — a cut exactly equal to what remains is permitted — with shortfalls rejected as `ERR_INSUFFICIENT_REEL_LENGTH`. Sixth and last, every line's `quantity` must fit within its coupling's `available_qty` at confirm time, or the confirm fails with `ERR_INSUFFICIENT_COUPLING_STOCK`.

A successful confirm moves the order to `CONFIRMED` and commits inventory. The cut-waste policy of §2.7 runs against the reel: let the remnant be what would remain of `remaining_length_mm` after the `cut_length_mm` comes off. A remnant of exactly zero is a clean cut — nothing is scrapped and the reel drops to `DEPLETED`. A remnant greater than zero but shorter than one meter is written off in full: it is added to the reel's `scrap_length_mm`, recorded on the order as `scrap_charged_mm`, and billed through the waste surcharge, which is recomputed from the freshly recorded scrap. A remnant of at least one meter simply stays on the reel. The reel's `remaining_length_mm` is debited by the cut length plus whatever was scrapped, and its status is recomputed against the ladder — `DEPLETED` below one meter, `LOW` below twenty meters, otherwise `AVAILABLE`. Coupling reservations take effect at the same moment, so each line's quantity joins `reserved_qty` while the order lives in `CONFIRMED`. And whenever the confirmation payload carries the waiver fields, `waiver_signed` flips to true with both `waiver_signed_by` and `waiver_liability_cents` stored on the order.

### 3.4. The Build Bench: Crimping, Pressure Testing, Rework, and Tagging

Once an order is `CONFIRMED`, the work moves to the bench, and the bench belongs to the `ShopTechnician`. Completing a build records the measured crimp diameter `measured_crimp_diameter_mm` and the actual build time `actual_labor_minutes`. The build is accepted only when the measured diameter deviates from the order's `crimp_diameter_spec_mm` by no more than `crimp_tolerance_mm` in either direction; a crimp outside the band is rejected with `ERR_CRIMP_OUT_OF_TOLERANCE`. A successful completion moves a `CONFIRMED` order to `BUILT`. The same operation serves the rework loop: an order in `REWORK` returns to `BUILT` through the identical check, overwriting the previously recorded diameter and labor with the new measurements.

Pressure testing follows the build. From `BUILT`, the technician records a test by supplying `test_pressure_psi` and a `result` of `PASSED` or `FAILED`. Per §2.8, the applied pressure must reach at least twice the order's `required_working_pressure_psi`; a test below that multiple is rejected with `ERR_TEST_PRESSURE_TOO_LOW` no matter which result was being recorded. A recorded pass moves the order to `TEST_PASSED`; a recorded failure moves it to `TEST_FAILED`. Both values persist on the order as `test_pressure_psi` and `test_result`.

A failed test is not the end of the line. Sending the assembly to rework moves a `TEST_FAILED` order to `REWORK`, ready for another build attempt. Because the hose has already been cut and crimped, rework touches no inventory: reel lengths are not adjusted and coupling reservations stay exactly where they are.

Tagging is the last bench step. Attaching the certification tag moves a `TEST_PASSED` order to `TAGGED`, storing the supplied `tag_serial` on the order. The serial must be unique across every order that is not `CANCELLED`; a serial already present on another live order is rejected with `ERR_TAG_SERIAL_TAKEN`. A serial attached to an order that is later cancelled from `TAGGED` is freed for reuse.

### 3.5. Settlement and Cancellation: Where the Money and the Metal End Up

Completion settles every open account on an order. A `TAGGED` order moves to `COMPLETED` either at the counter — a `CounterSales` operator or the `ShopManager` ringing it out — or from the field through dispatch completion as described in §3.6. The moment of completion computes `final_total_cents` using the formula of §3.3 with `actual_labor_minutes` in place of the estimate, and the pinned rounding order applies unchanged. For each line, the coupling's `on_hand_qty` is decremented by the line's `quantity`, and the order's reservations are released so `reserved_qty` and `available_qty` recompute across the catalog. When the order names an `equipment_asset_id`, that asset must still be `ACTIVE` — completing onto a decommissioned machine is rejected with `ERR_ASSET_NOT_ACTIVE` — and completion then stamps the asset's `installed_assembly_order_id` with this order, overwrites its `installed_at` with the current logical clock, recomputes its `next_due_date` and `compliance_posture`, and finally recomputes the customer's `compliance_score_strict`, `compliance_score_projected`, and `program_status`.

Cancellation runs in the opposite direction, and what gets restored depends on how far the order had progressed. From `DRAFT`, nothing was ever committed, so nothing is restored. From `CONFIRMED`, the reel is made whole: its `remaining_length_mm` is credited back the cut length plus the order's `scrap_charged_mm`, its `scrap_length_mm` is reduced by that same scrapped amount, its status is recomputed — so even a `DEPLETED` reel can climb back to `LOW` or `AVAILABLE` — and every coupling reservation is released. From `BUILT`, the hose is already cut and crimped, so coupling reservations are released but reel lengths are not restored. From `TEST_PASSED`, the same rule applies: reservations released, reel untouched. From `TEST_FAILED`, identically: reservations released, reel untouched. From `REWORK`, the same again. From `TAGGED`, reservations are released and reel lengths stay committed, and in addition the order's `tag_serial` is freed for reuse by a later order. In every case the order lands in `CANCELLED` and locks terminally, joining `COMPLETED` orders under the `ERR_ORDER_TERMINAL` lockdown described in §2.11.

### 3.6. Emergency Mobile Service

When a customer's machine blows a hose in the field, the counter books an emergency service dispatch. Booking takes a `customer_id`, a `van_id` identifying the service van, a `window_start`, and a `window_end`, with an optional `equipment_asset_id` naming the machine that is down. Three checks guard the booking, evaluated in this order after the generic ladder: the window's end must be strictly after its start or the booking fails with `ERR_INVALID_WINDOW`; the van must be free per the half-open overlap arithmetic of §2.9 — considering only existing dispatches in `REQUESTED`, `DISPATCHED`, or `ON_SITE` status on the same van — with genuine overlaps rejected as `ERR_VAN_WINDOW_CONFLICT` (HTTP 409); and the customer's `credit_hold` must be false, with violations rejected as `ERR_CREDIT_HOLD`. A booked dispatch begins in `REQUESTED`. Dispatch listings can be filtered by `van_id`, `customer_id`, `equipment_asset_id`, `installed_assembly_order_id`, or `status`.

From there a `FieldTechnician` drives the call forward. Advancing moves the dispatch from `REQUESTED` to `DISPATCHED` and, with a second advance, from `DISPATCHED` to `ON_SITE`.

Completing the call is allowed from `ON_SITE` alone. The completion payload may carry an `installed_assembly_order_id` naming the assembly the technician installed; when supplied, that order must exist (an unknown reference fails with `ERR_ORDER_NOT_FOUND`), must belong to the same customer as the dispatch, and must currently be `TAGGED` — a reference that fails either of those conditions is rejected with `ERR_INVALID_STATE`. When the reference is valid, the referenced order is driven through its own `TAGGED` → `COMPLETED` transition with the full settlement cascade of §3.5: final pricing from actual labor, coupling stock decremented and reservations released, and — when the order names an equipment asset — the installation timestamps, due-date and posture recomputation, and customer score refresh.

A call can also be aborted from `REQUESTED` or `DISPATCHED`, by the `FieldTechnician` or the `ShopManager`. Aborting frees the van window: an `ABORTED` dispatch no longer participates in overlap checks, so its slot can be booked again immediately.

### 3.7. Inspections, Due Dates, and Compliance Scoring

The hose-management program runs on inspections. Scheduling one against an asset — a `ShopManager` or `CounterSales` action — takes a `scheduled_window_start`, a `scheduled_window_end`, an optional `inspector_name` naming the inspector of record, and the `expected_equipment_asset_version` concurrency token of §2.10. The checks run in a fixed order behind the generic ladder: the optimistic-concurrency check first, so a client holding a stale asset version hears `ERR_STALE_VERSION` before anything else; then the window's shape, with an end that is not strictly after the start rejected as `ERR_INVALID_WINDOW`; then the closed-interval conflict check of §2.9 against inspections currently `IN_PROGRESS` on the same asset, with touching endpoints counting as overlap and conflicts rejected as `ERR_INSPECTION_WINDOW_CONFLICT`; and finally the asset-active rule, with a `DECOMMISSIONED` asset rejected as `ERR_ASSET_NOT_ACTIVE`. A successful schedule creates the inspection in `SCHEDULED` status, moves every prior `SCHEDULED` inspection of the same asset to `SUPERSEDED` atomically with the create, and increments the asset's `version` by one. An asset's inspections can be listed, newest scheduling obligations included.

A `FieldTechnician` begins a scheduled inspection, moving it from `SCHEDULED` to `IN_PROGRESS`; the asset must be `ACTIVE` at that moment or the start is rejected with `ERR_ASSET_NOT_ACTIVE`. Completing the inspection requires a `result` of `PASSED` or `FAILED`. Either way, the system stamps `performed_at` from the logical clock and computes `was_overdue`: true only when the asset had a computable `next_due_date` and the completion happened strictly later than that date — a completion exactly on the due date counts as on time, and the flag starts from its default of false whenever no due date exists.

The two results diverge in what they write back. A `PASSED` inspection records the completion instant as the asset's `last_passed_inspection_at`, recomputes `next_due_date` with the just-recorded pass as its new base, recomputes the asset's `compliance_posture`, and recomputes the customer's scores and `program_status`. A `FAILED` inspection leaves `last_passed_inspection_at` untouched; the asset's posture becomes `NON_COMPLIANT` and stays there until a later inspection passes, and the customer's scores recompute — which can flip `program_status` to `PROBATION` when the strict score falls below the bar.

Due-date arithmetic itself is simple. An asset's `next_due_date` is its base date plus the customer's `inspection_interval_days`, where the base is `last_passed_inspection_at` when a pass exists and `installed_at` otherwise; when neither exists, the date is null. The asset's `compliance_posture` then derives as a chain: when the latest completed inspection is a failure with no later pass, the posture is `NON_COMPLIANT`; otherwise, when the logical clock has moved past the `next_due_date`, the posture is `OVERDUE`; otherwise, when the gap between `next_due_date` and the clock is no more than 30 days, the posture is `DUE_SOON`; and in every remaining case the posture is `COMPLIANT`.

Customer scoring aggregates the fleet. A customer's `compliance_score_strict` considers only assets in `ACTIVE` status and reports the percentage of them whose `compliance_posture` is `COMPLIANT` or `DUE_SOON`, expressed to two decimal places with half-up rounding — and reading 100.00 when the customer has no active assets at all. The lenient sibling, `compliance_score_projected`, additionally counts `OVERDUE` and `NON_COMPLIANT` assets as compliant when the asset holds at least one `SCHEDULED` inspection whose `scheduled_window_end` is at or after the current logical clock, so the projected score never falls below the strict one on identical data. Finally, `program_status` derives from enrollment and the strict score: `NONE` when the customer is not enrolled, `ACTIVE` when enrolled with a strict score of at least 70, and `PROBATION` otherwise. The discount of §3.3 flows only while `program_status` is `ACTIVE`, which makes the strict score — not the projected one — the number the customer's pricing depends on.

## 4. Endpoint Definitions

Operations that create new resources — a customer, an equipment asset, an inspection, a reel, a coupling, an assembly order, or a service dispatch — return a `201 Created` status code. Operations that modify an existing resource, including every state-transition action and the customer update, return a `200 OK` status code. The table below is a summary only; request payloads, response bodies, and side effects are defined by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/customers` | Create a customer | ShopManager |
| GET | `/api/customers/{id}` | Read a customer including computed compliance scores and program status | ShopManager, CounterSales, Customer |
| PATCH | `/api/customers/{id}` | Update customer flags (credit hold, program enrollment, discount, interval) | ShopManager |
| POST | `/api/equipment-assets` | Register a customer machine (optionally with `installed_at` for program enrollment of an existing fleet) | ShopManager, CounterSales |
| GET | `/api/equipment-assets` | List assets with filters | ShopManager, CounterSales, ShopTechnician, FieldTechnician, Customer |
| GET | `/api/equipment-assets/{id}` | Read one asset | ShopManager, CounterSales, ShopTechnician, FieldTechnician, Customer |
| POST | `/api/equipment-assets/{id}/decommission` | Decommission an asset (terminal) | ShopManager |
| POST | `/api/equipment-assets/{id}/inspections` | Schedule an inspection; supersedes existing scheduled inspections of the asset; OCC-guarded on the asset version | ShopManager, CounterSales |
| GET | `/api/equipment-assets/{id}/inspections` | List inspections of an asset | ShopManager, CounterSales, ShopTechnician, FieldTechnician, Customer |
| POST | `/api/inspections/{id}/start` | Begin an inspection (requires asset active) | FieldTechnician |
| POST | `/api/inspections/{id}/complete` | Complete an inspection with a result; performed timestamp stamped from the logical clock | FieldTechnician |
| POST | `/api/reels` | Receive a bulk hose reel | ShopManager |
| GET | `/api/reels/{id}` | Read one reel | ShopManager, CounterSales, ShopTechnician |
| POST | `/api/reels/{id}/retire` | Retire a reel (terminal) | ShopManager |
| POST | `/api/couplings` | Register a coupling SKU with initial stock | ShopManager |
| GET | `/api/couplings/{id}` | Read one coupling including reserved and available quantities | ShopManager, CounterSales, ShopTechnician |
| POST | `/api/couplings/{id}/receipts` | Receive additional stock | ShopManager |
| GET | `/api/couplings/{id}/assembly-lines` | List order lines referencing this coupling | ShopManager, CounterSales |
| POST | `/api/assembly-orders` | Create an assembly order in draft with optional coupling lines; provisional price computed | CounterSales, ShopManager |
| GET | `/api/assembly-orders` | List orders with filters | ShopManager, CounterSales, ShopTechnician, Customer |
| GET | `/api/assembly-orders/{id}` | Read one order | ShopManager, CounterSales, ShopTechnician, Customer |
| GET | `/api/assembly-orders/{id}/lines` | List the order's coupling lines | ShopManager, CounterSales, ShopTechnician, Customer |
| POST | `/api/assembly-orders/{id}/confirm` | Confirm a draft order: validates safety, waiver, referential, and fiscal rules; commits reel length with waste scrap; reserves couplings | CounterSales, ShopManager |
| POST | `/api/assembly-orders/{id}/complete-build` | Record measured crimp diameter and actual labor; confirmed or rework to built | ShopTechnician |
| POST | `/api/assembly-orders/{id}/record-pressure-test` | Record pressure test; built to test passed or test failed per result | ShopTechnician |
| POST | `/api/assembly-orders/{id}/rework` | Send a failed assembly back to build; test failed to rework | ShopTechnician |
| POST | `/api/assembly-orders/{id}/tag` | Attach the certification tag serial; test passed to tagged | ShopTechnician |
| POST | `/api/assembly-orders/{id}/complete` | Complete a tagged order: final pricing, coupling stock decrement, asset installation cascade | CounterSales, ShopManager |
| POST | `/api/assembly-orders/{id}/cancel` | Cancel a non-terminal order; inventory restoration depends on the from-state | CounterSales, ShopManager |
| POST | `/api/service-dispatches` | Book an emergency mobile service window on a van (half-open overlap per van) | CounterSales, ShopManager |
| GET | `/api/service-dispatches` | List dispatches with filters | ShopManager, CounterSales, FieldTechnician |
| GET | `/api/service-dispatches/{id}` | Read one dispatch | ShopManager, CounterSales, FieldTechnician |
| POST | `/api/service-dispatches/{id}/advance` | Advance requested to dispatched to on-site | FieldTechnician |
| POST | `/api/service-dispatches/{id}/complete` | Complete from on-site; optionally installs a tagged assembly order, transitioning it to completed | FieldTechnician |
| POST | `/api/service-dispatches/{id}/abort` | Abort from requested or dispatched; frees the van window | FieldTechnician, ShopManager |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (test-driving endpoint); before any call the clock reads exactly 2026-08-01T00:00:00Z | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ASSET_NOT_FOUND` | 404 |
| `ERR_REEL_NOT_FOUND` | 404 |
| `ERR_COUPLING_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PRESSURE_RATING_MISMATCH` | 422 |
| `ERR_WAIVER_REQUIRED` | 422 |
| `ERR_CRIMP_OUT_OF_TOLERANCE` | 422 |
| `ERR_TEST_PRESSURE_TOO_LOW` | 422 |
| `ERR_TAG_SERIAL_TAKEN` | 409 |
| `ERR_VAN_WINDOW_CONFLICT` | 409 |
| `ERR_INSPECTION_WINDOW_CONFLICT` | 409 |
| `ERR_REEL_NOT_USABLE` | 422 |
| `ERR_ASSET_NOT_ACTIVE` | 422 |
| `ERR_CREDIT_HOLD` | 402 |
| `ERR_INSUFFICIENT_REEL_LENGTH` | 422 |
| `ERR_INSUFFICIENT_COUPLING_STOCK` | 422 |

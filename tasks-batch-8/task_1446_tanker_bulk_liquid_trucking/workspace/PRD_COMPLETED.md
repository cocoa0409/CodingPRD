# Tanker & Bulk Liquid Trucking API — Product Requirements Document

## 1. Introduction

Bulk liquid tank carriers operate one of the most tightly regulated workflows in road freight: every load pairs a chemical product with a specialized tank trailer, and every hand-off — wash rack, loading rack, highway scale, consignee meter — creates a compliance artifact that must survive later audit. A single trailer that hauled caustic soda yesterday cannot load food-grade latex today without a certified wash of the correct level; a driver without a current hazmat endorsement cannot legally move a Class 3 flammable; and a shipment billed on rack-observed gallons must be reconciled against temperature-corrected delivered gallons before the customer's credit exposure is settled. This document specifies an API that manages that entire chain of custody for a bulk liquid tank carrier, all resources mounted under the `/bulk-liquid` path prefix.

The system governs product compatibility and prior-load restrictions, tank wash certificate booking and validity, loading rack access and custody-transfer meter tickets, hazmat placarding and driver endorsement enforcement, axle-weight and gross-weight compliance, delivery metering with retain samples, spill response plans and incident reporting, and a dedicated-trailer program with monthly shortfall settlement. It is written for the engineering team building the service: §2 fixes the wire-level contracts every endpoint shares, §3 walks the business workflows in the order a load actually moves, §4 summarizes the endpoint surface, and §5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly seven roles: `FleetAdmin`, `Dispatcher`, `TerminalOperator`, `WashOperator`, `SafetyOfficer`, `Driver`, and `CustomerRep`. An authenticated caller whose role is not authorized for the target endpoint — or whose entity-backed identity does not match the resource being acted on — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The roles divide the work along segregation-of-duties lines. A `FleetAdmin` is the carrier's back-office administrator: master data, fleet records, reconciliation, dedicated-trailer agreements, month-end settlement, and the logical clock. A `Dispatcher` plans loads and departs them. A `TerminalOperator` runs the loading rack: check-in, abort, close-meter, record-weights, and placard confirmation. A `WashOperator` books and certifies tank washes. A `SafetyOfficer` owns the HSE surface: spill plan approval, incident review, certificate revocation, sample disposal, and variance resolution. A `Driver` is a CDL driver who starts deliveries, closes delivery tickets, and reports spills. A `CustomerRep` is a shipper-side representative who creates shipment requests and spill response plans.

Identity semantics differ by role, and the distinction is contractual. When `X-User-Role` is `Driver`, the `X-User-ID` value is the `id` of the acting Driver entity; ownership checks on any resource that references a Driver compare the resource's foreign-key field — for example a shipment's `driver_id` — to `X-User-ID`. When `X-User-Role` is `CustomerRep`, the `X-User-ID` value is the `id` of the acting Customer entity, and ownership checks compare against resources' `customer_id`. When `X-User-Role` is `FleetAdmin`, `Dispatcher`, `TerminalOperator`, `WashOperator`, or `SafetyOfficer`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `closed_by_user_id` on a meter ticket closed by a `TerminalOperator`, or as `closed_by_user_id` on a spill incident closed by a `SafetyOfficer` — but never compares it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it reflects wall-clock receipt time, not the logical clock of §2.5, which governs only resource timestamps.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. Where one operation creates or mutates several resources at once, `data` carries the endpoint's primary resource: check-in, abort-loading, and start-delivery return the shipment (not the ticket each opens or voids), close-meter returns the closed MeterTicket (not the shipment), and delivery-ticket close returns the closed DeliveryTicket (not the shipment or the new RetainSample).
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

A request that matches no defined route is rejected with `ERR_NOT_FOUND` (404); a defined path with an unsupported method is likewise rejected with `ERR_NOT_FOUND`, carrying HTTP 405.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`; integer values outside the allowed range are clamped, not rejected — `limit` into [1, 100] and `offset` up to a floor of 0. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, with `has_more` true exactly when `offset` plus the number of returned items is less than `total_count`. Unless a more specific rule is stated, all list endpoints return resources sorted by `created_at` in ascending order, breaking ties by insertion (creation) order.

### 2.4. Common Resource Properties

Every resource in the system — Customer, Product, CompatibilityRule, TankTrailer, Driver, WashBay, TankWashCertificate, LoadingRack, Shipment, MeterTicket, DeliveryTicket, RetainSample, SpillResponsePlan, SpillIncident, and DedicatedTrailerAgreement — carries the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits. The `updated_at` timestamp follows the same format and refreshes on every mutation. The `version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of the resource; it is the anchor for optimistic concurrency control where that mechanism applies (§2.7). Cascading side effects count as mutations: when one operation advances a trailer, a certificate, and a customer exposure figure together, each affected resource's `updated_at` refreshes and its `version` increments.

### 2.5. The Logical Clock and Lazy Expiry

All timestamps the server assigns — certificate validity, ticket open and close times, approval dates, settlement windows — are drawn from a single server-side logical clock, never from wall-clock time. At startup, before any clock operation has run, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstance. A `FleetAdmin` may advance the clock through the clock-setting capability (`POST /bulk-liquid/_clock/set_current_utc`), supplying the target instant as `to_iso8601`. The endpoint accepts any well-formed ISO 8601 instant — no monotonicity is enforced, so the clock may also be set to an earlier reading — and answers 200 with an empty `data` object.

Two resource kinds expire lazily rather than by background job. A TankWashCertificate whose `expires_at` lies in the past transitions `CERTIFIED → EXPIRED` the next time it is read, and an APPROVED SpillResponsePlan whose `expires_at` has passed transitions to `EXPIRED` on read the same way. Because expiry is evaluated on read, advancing the logical clock causes pending lazy expirations to surface on subsequent reads. A plan-time attempt to use an already-expired certificate does not mutate the certificate; it simply fails as described in §3.3.

### 2.6. Units, Precision, and Rounding

Money is always integer cents. Gallonage figures derived from meter readings (`observed_gallons`, `net60_gallons`, `delivered_net60_gal`, `allowed_loss_gal`, `variance_gallons`) are carried to exactly 1 decimal place using round-half-up. Weight figures are integer pounds, with any computed product weight rounded half-up to a whole pound. Where a billing total is assembled from component lines, each line is individually rounded half-up to integer cents before the lines are summed; rounding the unrounded sum instead is incorrect and produces off-by-one-cent results. Distances are whole miles, temperatures are degrees Fahrenheit, and the reference temperature for all volumetric corrections is 60 °F.

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and both treat their version field as non-optional input. Revising a DRAFT shipment's commercial terms requires the request to carry `expected_shipment_version` holding the shipment's `version` as the client last observed it; if another writer has advanced the shipment since that read — for example through a prior accepted revision — the versions no longer match and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Revising a PENDING dedicated-trailer agreement's committed volume likewise requires `expected_agreement_version` matching the agreement's current `version`; a stale value means the client's base revision is out of date and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful revision of either resource increments that resource's `version` by one; a revision that supplies a matching expected version but changes no field still succeeds and still increments the version. No other endpoint accepts a version field.

### 2.8. Validation Pipeline, Ordering, and Resource Existence

Every request is evaluated against an ordered pipeline of validation categories, and a failure at any step short-circuits all later steps, so the error a caller receives always comes from the earliest failing category. The order is:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the seven declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Authorization and identity** — the role is permitted on the endpoint, and entity-backed identities match: a `Driver` caller must equal the shipment's `driver_id`, a `CustomerRep` caller must equal the relevant `customer_id` (`ERR_INSUFFICIENT_PERMISSIONS`, 403). Role membership is always checked before any resource lookup. An entity-identity comparison that needs only a request-body value (shipment and spill-plan creation) runs before the body-reference existence checks of step 3; one that depends on the loaded target resource (start-delivery, delivery-ticket close, shipment cancel, plan submit, incident report) is evaluated immediately after that resource loads, so an unknown path identifier yields its dedicated 404 even when the caller's identity would not have matched.
3. **Existence** — path identifiers are validated left-to-right, then identifiers referenced in the request body. The first unknown identifier yields that resource's dedicated 404: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_COMPATIBILITY_RULE_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_WASH_BAY_NOT_FOUND`, `ERR_WASH_CERT_NOT_FOUND`, `ERR_RACK_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_METER_TICKET_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND`, `ERR_RETAIN_SAMPLE_NOT_FOUND`, `ERR_SPILL_PLAN_NOT_FOUND`, `ERR_SPILL_INCIDENT_NOT_FOUND`, or `ERR_AGREEMENT_NOT_FOUND`.
4. **Request shape** — required fields are present, enum members are valid, scalar ranges are sane (a wash `window_end` must be later than its `window_start`, a rack's `close_hour` must exceed its `open_hour`, quantities must be positive — ordered gallons, route miles, rates, delivered and spilled gallonage, and retain-sample volumes strictly so, while meter readings and recorded axle weights may be zero), unknown body fields are rejected, and on trailer creation the three tare axle components must sum to the stated tare weight. Failures are `ERR_INVALID_REQUEST` (400), or `ERR_TARE_AXLE_MISMATCH` for the trailer tare-sum case.
5. **Optimistic concurrency** — on the two revision endpoints of §2.7, the expected version must match (`ERR_STALE_VERSION`, 412).
6. **State gates** — the target resource is in the required from-state, and referenced-entity state gates hold: customer ACTIVE, driver ACTIVE, trailer AVAILABLE, delivery ticket OPEN. All state errors carry HTTP 409.
7. **Business safety** — compatibility pairs, wash level sufficiency, driver endorsements, placard match, axle and weight compliance, and the approved spill plan required at departure (HTTP 422).
8. **Temporal rules** — rack operating hours, rack and wash-bay window conflicts (409), certificate and endorsement expiry, the active rack window at check-in, the spill report deadline, sample retention, agreement period overlap (409), and settlement month ordering (HTTP 422 unless noted).
9. **Uniqueness, capacity, dedication, and segregation** — duplicate unit numbers, CDL numbers, and compatibility pairs (409); capacity and dedication mismatches (422); segregation-of-duties violations (403).
10. **Cross-entity referential gates** — rack authorization for the product group (422) and the open-incident block at reconciliation (409).
11. **Fiscal credit gate** — the credit exposure check at planning time (`ERR_CREDIT_LIMIT_EXCEEDED`, 402). Because this gate runs last, a plan request that would fail both a safety check and the credit check is always rejected for the safety failure.

### 2.9. Cascading Consistency and Compensating Releases

Trailer assignment, certificate holds, and customer credit exposure form a web of derived state that the server keeps consistent without explicit client action on the secondary resources. Planning a shipment assigns its trailer (`AVAILABLE → ASSIGNED`), holds its wash certificate (`CERTIFIED → HELD`), and recomputes the customer's exposure in one atomic step. Unwinding operations are symmetrical compensating releases: unplanning or cancelling a planned shipment returns the trailer to `AVAILABLE`, returns the held certificate to `CERTIFIED` unchanged, clears the assignment fields, and recomputes exposure. The sharpest cascade is certificate revocation (§3.2): revoking a held certificate voids the certificate, reverts the holding shipment from `PLANNED` to `DRAFT` with all assignment fields cleared, and — because that revert releases the trailer — moves the trailer back to `AVAILABLE`. Delivery close releases the trailer regardless of outcome, and a variance outcome additionally increments the matching dedicated agreement's flag counter, which can itself trigger an agreement suspension (§3.5). Every one of these secondary mutations refreshes `updated_at` and increments `version` on the affected resource.

## 3. Business Logic & Workflows

### 3.1. Master Data: Customers, Products, Fleet, and Facilities

A `FleetAdmin` onboards a shipper by creating a Customer with a legal `name`, a `credit_limit_cents` ceiling on credit exposure, and an optional `dedicated_program_enrolled` flag that defaults to false. A new customer starts with `status` `ACTIVE` and an `exposure_cents` of zero; the exposure figure is computed, read-only, and maintained by the billing rules of §3.6. Suspending a customer requires it to be `ACTIVE` — a suspend against any other state is rejected with `ERR_CUSTOMER_NOT_ACTIVE` — and moves it to `SUSPENDED`; reactivation requires the customer to be `SUSPENDED` (otherwise `ERR_INVALID_REQUEST`) and returns it to `ACTIVE`.

Products capture the chemistry the safety rules depend on. Each Product is created with a `name` (for example, "Diesel ULSD"), a `compatibility_group` drawn from `PETROLEUM`, `SOLVENT`, `ACID`, `CAUSTIC`, `VEG_OIL`, `FOOD_GRADE`, or `LATEX`, a `hazmat_class` of `NONE`, `CLASS_3_FLAMMABLE`, `CLASS_8_CORROSIVE`, or `CLASS_6_TOXIC`, a `packing_group` of `NONE`, `I`, `II`, or `III`, a `density_lb_per_gal` measured at 60 °F, a `temp_coeff_per_degF` volumetric correction coefficient, and the DOT `placard_code` the load must display — the string `NONE` for non-hazmat products.

Fleet records are deliberately physical. A TankTrailer is registered with a fleet `unit_number` that must be unique across all trailers (a duplicate is rejected with `ERR_DUPLICATE_UNIT_NUMBER`), a `capacity_gallons` ceiling, and a full weight skeleton: `tare_weight_lb` decomposed into `tare_steer_lb`, `tare_drive_lb`, and `tare_trailer_lb`, where the three components must sum exactly to the stated tare weight or creation fails with `ERR_TARE_AXLE_MISMATCH`. Legal limits ride along as `steer_axle_rating_lb`, `drive_axle_rating_lb`, `trailer_axle_rating_lb`, and the overall `gvwr_lb`; each rating is an inclusive bound, meaning a measured load exactly equal to the rating is legal. A trailer's `last_product_group` starts null — the trailer has hauled nothing yet — and is stamped with each product's compatibility group when a meter ticket closes. Its `last_wash_cert_id` points at the most recent certificate to reach `CERTIFIED`, and its `dedicated_customer_id` is set and cleared only by the dedicated-trailer agreement lifecycle of §3.8. A new trailer is `AVAILABLE`; it reads `ASSIGNED` while any shipment from `PLANNED` through `DELIVERING` references it.

Drivers are registered with a `full_name`, a `cdl_number` unique across all drivers (`ERR_DUPLICATE_CDL_NUMBER` on collision), boolean flags for the N (tank vehicle) `tanker_endorsement` and the H (hazardous materials) `hazmat_endorsement`, and an `endorsement_expires_on` date in ISO `YYYY-MM-DD` form — endorsements remain valid through that date inclusive, and a date before the current logical date means expired. A new driver is `ACTIVE`; deactivation moves an `ACTIVE` driver to `INACTIVE` (any other state draws `ERR_DRIVER_NOT_ACTIVE`).

Two facility records complete the master data. A WashBay is created with a `bay_code` (no uniqueness is enforced on bay codes), a `supported_wash_levels` array naming the wash levels the bay can perform (a subset of `FLUSH`, `DETERGENT_WASH`, and `CHEMICAL_KOSHER`), and a `cleanup_buffer_minutes` turnaround gap — defaulting to 30 minutes — that is appended after every booking window on that bay when conflicts are evaluated. A LoadingRack carries a `rack_code` (likewise not uniqueness-constrained), a `terminal_name`, an `authorized_groups` array listing the compatibility groups the rack may load, an `open_hour` and `close_hour` (each 0–23 UTC, with `close_hour` required to exceed `open_hour` or creation fails with `ERR_INVALID_REQUEST`), and the custody-transfer `meter_id` of its meter.

### 3.2. Product Compatibility and Tank Wash Certification

Compatibility between consecutive loads is data, not judgment. A `FleetAdmin` authors CompatibilityRule records pairing a `prior_group` (the compatibility group of what the trailer last hauled) with a `next_group` (the group about to be loaded), declaring the `required_wash_level` — `NONE`, `FLUSH`, `DETERGENT_WASH`, or `CHEMICAL_KOSHER` — and a `forbidden` flag, defaulting to false, that marks a pair as never haulable consecutively regardless of washing. The (`prior_group`, `next_group`) pair is unique across all rules; a duplicate is rejected with `ERR_DUPLICATE_COMPATIBILITY_RULE`.

Wash capacity is scheduled per bay. A `WashOperator` books a TankWashCertificate by naming the `trailer_id`, the `wash_bay_id`, the `wash_level` (`FLUSH`, `DETERGENT_WASH`, or `CHEMICAL_KOSHER`), and a `window_start` / `window_end` pair whose end must be strictly later than its start (`ERR_INVALID_REQUEST` otherwise). Booking enforces the bay's turnaround discipline: a new booking is rejected with `ERR_WASH_BAY_WINDOW_CONFLICT` (409) whenever another booking on the same bay in `SCHEDULED` or `CERTIFIED` status satisfies both of these conditions — the new window starts before the existing window's end plus the bay's `cleanup_buffer_minutes`, and the existing window starts before the new window's end plus that same buffer. Booking does not validate the requested `wash_level` against the bay's `supported_wash_levels`; that list is descriptive master data, not a booking gate. A freshly booked certificate is `SCHEDULED`.

Completing the wash is a separate act: certifying a `SCHEDULED` certificate (any other state draws `ERR_CERT_INVALID_STATE`) moves it to `CERTIFIED`, stamps `certified_at` from the logical clock, and computes `expires_at` by adding the validity window for the wash level — 48 hours (two days) for `FLUSH`, 96 hours (four days) for `DETERGENT_WASH`, and 168 hours (seven days) for `CHEMICAL_KOSHER`. Certification also records the certificate as the trailer's `last_wash_cert_id`. A booking that will not happen can be cancelled while still `SCHEDULED`, moving it to `VOIDED` (again, any other state draws `ERR_CERT_INVALID_STATE`).

Revocation is the safety valve for discovered contamination and belongs to the `SafetyOfficer`. A certificate in `CERTIFIED` or `HELD` may be revoked to `VOIDED` (any other state draws `ERR_CERT_INVALID_STATE`). Revoking a `CERTIFIED` certificate simply removes it from the pool. Revoking a `HELD` one cascades in two hops: first, the shipment holding it — the `PLANNED` shipment whose `wash_cert_id` references this certificate — reverts `PLANNED → DRAFT` with `wash_cert_id`, `trailer_id`, `driver_id`, `rack_id`, `rack_window_start`, and `rack_window_end` all cleared; second, because that revert releases the trailer, the trailer transitions `ASSIGNED → AVAILABLE`.

Two system-driven transitions complete the lifecycle. When a planned shipment consumes its wash at close-meter (§3.4), the held certificate moves `HELD → CONSUMED` and records the consuming shipment in `consumed_by_shipment_id`. And a `CERTIFIED` certificate whose validity lapses transitions to `EXPIRED` lazily on read, per §2.5; attempting to attach an expired certificate at plan time fails instead with `ERR_WASH_CERT_EXPIRED` and leaves the certificate untouched. When a held certificate is released without being consumed — on unplan or cancel — it returns `HELD → CERTIFIED` as a compensating release and rejoins the available pool unchanged. `CONSUMED`, `VOIDED`, and `EXPIRED` are the certificate's terminal states.

### 3.3. Shipment Creation, Revision, and Planning

A shipment begins as a bare commercial request. A `Dispatcher` — or a `CustomerRep`, who must set `customer_id` to their own customer id or be rejected with `ERR_INSUFFICIENT_PERMISSIONS` — creates it with the `customer_id`, the `product_id`, the `ordered_gallons`, the one-way `route_miles` (which drives the allowed in-transit loss of §3.5), and the `rate_per_gal_cents` freight rate. The referenced customer must be `ACTIVE` or creation fails with `ERR_CUSTOMER_NOT_ACTIVE`. The new shipment is `DRAFT`: `trailer_id`, `driver_id`, `rack_id`, and `wash_cert_id` are null, no `rack_window_start` or `rack_window_end` is reserved, `weights_verified_at` and `reconciled_at` are null, `placards_confirmed` is false, `resolution_note` is null, and the two billing totals `provisional_total_cents` and `final_total_cents` are null.

While the shipment remains `DRAFT`, a `Dispatcher` may revise its commercial terms — any of `ordered_gallons`, `route_miles`, or `rate_per_gal_cents` — through the OCC-guarded revision endpoint of §2.7, which requires `expected_shipment_version` and increments the shipment's `version` by one on success. Once a shipment has left `DRAFT`, revision is no longer available and the attempt is rejected with `ERR_SHIPMENT_INVALID_STATE`.

Planning is the densest operation in the system: a `Dispatcher` supplies `trailer_id`, `driver_id`, `rack_id`, a reserved rack window `rack_window_start` and `rack_window_end`, and optionally a `wash_cert_id`, and the shipment moves `DRAFT → PLANNED`. The shipment must currently be `DRAFT` (`ERR_SHIPMENT_INVALID_STATE` otherwise), and the full validation chain then runs in the pipeline order of §2.8 — safety checks first, temporal checks next, then capacity and dedication, the rack authorization gate, and the fiscal credit gate last.

The safety checks begin with prior-load compatibility. If the trailer's `last_product_group` is null — it has never completed a load — no rule lookup occurs and the wash requirement is `NONE`. Otherwise the system looks up the CompatibilityRule pairing the trailer's `last_product_group` with the product's `compatibility_group`; if no such rule exists the plan fails with `ERR_COMPATIBILITY_RULE_MISSING`, and if the rule is marked `forbidden` it fails with `ERR_PRODUCT_INCOMPATIBILITY_FORBIDDEN`. Otherwise the rule's `required_wash_level` becomes the requirement. Wash levels are totally ordered by rank: `NONE` ranks 0, `FLUSH` 1, `DETERGENT_WASH` 2, and `CHEMICAL_KOSHER` 3. When the requirement is `NONE`, attaching a certificate is optional — but an attached certificate must still be `CERTIFIED` (else `ERR_CERT_INVALID_STATE`) and unexpired, with `expires_at` later than the logical clock (else `ERR_WASH_CERT_EXPIRED`). When the requirement is above `NONE`, a certificate is mandatory — omitting `wash_cert_id` entirely fails with `ERR_CERT_INVALID_STATE` — and must satisfy four conditions: its wash level ranks at least as high as the requirement (else `ERR_WASH_LEVEL_INSUFFICIENT`), it is `CERTIFIED` (else `ERR_CERT_INVALID_STATE`), it is unexpired at plan time (else `ERR_WASH_CERT_EXPIRED`), and it belongs to the same trailer the shipment is being planned onto. The same-trailer condition applies to any attached certificate regardless of the requirement; a certificate issued for a different trailer is rejected with `ERR_CERT_INVALID_STATE` even when the requirement is `NONE`.

Driver legality comes next. The driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), must hold the tanker endorsement, and must hold the hazmat endorsement whenever the product's `hazmat_class` is anything other than `NONE` — a missing endorsement is `ERR_DRIVER_ENDORSEMENT_MISSING`. Independently, `endorsement_expires_on` must not be before the current logical date, or the plan fails with `ERR_DRIVER_ENDORSEMENT_EXPIRED`.

Temporal checks follow. The reserved window must lie within the rack's operating hours on a single UTC calendar day — beginning no earlier than `open_hour` and ending no later than `close_hour` — or the plan is rejected with `ERR_WINDOW_OUTSIDE_OPERATING_HOURS`. The window must also not overlap any other shipment on the same rack in `PLANNED`, `LOADING`, or `LOADED` status, using half-open interval semantics with zero buffer: an overlap is `ERR_RACK_WINDOW_CONFLICT` (409).

Capacity and dedication come after that. The trailer must be `AVAILABLE` (`ERR_TRAILER_NOT_AVAILABLE`), the `ordered_gallons` must not exceed the trailer's `capacity_gallons` (`ERR_CAPACITY_EXCEEDED`), and dedication must match: if the trailer's `dedicated_customer_id` is set to a customer other than the shipment's, the plan is rejected with `ERR_TRAILER_DEDICATION_MISMATCH`. The referential gate then requires the product's `compatibility_group` to appear in the rack's `authorized_groups`, else `ERR_RACK_NOT_AUTHORIZED_FOR_PRODUCT`.

The fiscal gate runs last. The customer's current `exposure_cents` plus a plan-time estimate for the new shipment must not exceed the customer's `credit_limit_cents`, with equality allowed; a breach is `ERR_CREDIT_LIMIT_EXCEEDED` (402). The estimate mirrors the provisional billing formula of §3.6 with the ordered quantity as the basis: the product charge line is the ordered gallons times `rate_per_gal_cents` rounded half-up to integer cents, the fuel surcharge is 4% of that charge rounded half-up to integer cents, and a flat rack fee of 15000 cents ($150.00) is added.

A successful plan has three side effects beyond the state change: the trailer transitions `AVAILABLE → ASSIGNED`, the attached certificate (if any) transitions `CERTIFIED → HELD`, and the customer's `exposure_cents` is recomputed. Unwinding is symmetrical. Unplanning a `PLANNED` shipment (any other state draws `ERR_SHIPMENT_INVALID_STATE`) returns it to `DRAFT`, releases the trailer `ASSIGNED → AVAILABLE`, returns the held certificate `HELD → CERTIFIED`, clears the assignment fields, and recomputes exposure. Cancelling works from either `DRAFT` or `PLANNED` — both the `Dispatcher` and the owning `CustomerRep` may cancel — and lands in `CANCELLED`; a `DRAFT` cancel has no further effect, while a `PLANNED` cancel performs the same compensating releases as an unplan. Either source state attempted from elsewhere draws `ERR_SHIPMENT_INVALID_STATE`.

### 3.4. Loading at the Rack: Metering, Weights, and Placards

When the truck arrives, a `TerminalOperator` checks the shipment in. The shipment must be `PLANNED` (`ERR_SHIPMENT_INVALID_STATE` otherwise), the driver is re-validated at the gate — still `ACTIVE` and still holding valid endorsements (`ERR_DRIVER_NOT_ACTIVE`, `ERR_DRIVER_ENDORSEMENT_MISSING`, or `ERR_DRIVER_ENDORSEMENT_EXPIRED` as applicable) — and the logical clock must fall within the reserved rack window, at or after `rack_window_start` and strictly before `rack_window_end` (outside that half-open window the check-in is rejected with `ERR_RACK_WINDOW_NOT_ACTIVE`). Check-in moves the shipment `PLANNED → LOADING` and opens a MeterTicket: status `OPEN`, `opened_at` stamped from the clock, `rack_id` copied from the shipment, `shipment_id` pointing back. A shipment has at most one active meter ticket; tickets are never deleted, and voided tickets remain as history.

Loading can be aborted: aborting returns the shipment `LOADING → PLANNED` (any other state draws `ERR_SHIPMENT_INVALID_STATE`) and voids the open meter ticket `OPEN → VOIDED`, retaining it in history.

Closing the meter is the custody-transfer moment. A `TerminalOperator` supplies `meter_start_gal`, `meter_end_gal`, and the `observed_temp_F` at the rack; the shipment must be `LOADING` (`ERR_SHIPMENT_INVALID_STATE` otherwise), and the end reading must be strictly greater than the start reading (`ERR_INVALID_REQUEST` otherwise). On success the ticket closes `OPEN → CLOSED`: `closed_at` is stamped, the operator's `X-User-ID` is recorded as the ticket's `closed_by_user_id` (this becomes a segregation-of-duties anchor for weight verification below), and two gallonage figures are computed to 1 decimal place with round-half-up. The `observed_gallons` is simply the end reading minus the start reading. The `net60_gallons` applies the temperature correction: the observed gallons are multiplied by one minus the product of the product's `temp_coeff_per_degF` and the amount by which `observed_temp_F` exceeds the 60 °F reference temperature — that is, observed times (1 − coefficient × (observed temperature − 60)) — and the result is rounded half-up to 1 decimal place. At exactly 60 °F the two figures coincide; off 60 °F they diverge. The shipment then advances `LOADING → LOADED` with four side effects: the held wash certificate (if any) moves `HELD → CONSUMED` with `consumed_by_shipment_id` set, the trailer's `last_product_group` is stamped with the product's compatibility group, the `provisional_total_cents` billing figure is computed on the observed-gallon basis per §3.6, and the customer's `exposure_cents` is recomputed.

Before the truck may leave, two independent verifications happen while the shipment is `LOADED`. Weight verification is a self-transition that keeps the shipment `LOADED`: a `TerminalOperator` records the measured `steer_lb`, `drive_lb`, and `trailer_lb`. It can be performed only once — if `weights_verified_at` is already set, the attempt is rejected with `ERR_WEIGHTS_ALREADY_VERIFIED` — and segregation of duties forbids the operator who closed the meter from verifying the weights, so the caller's `X-User-ID` must differ from the meter ticket's `closed_by_user_id` (`ERR_SAME_OPERATOR_SEGREGATION`, 403). Per the §2.8 pipeline, which places axle and weight compliance in category 7 and segregation of duties in category 9, the axle checks run first, in a pinned order, and the segregation check is evaluated only after every axle and weight check passes — a request violating both draws the axle error. First, `steer_lb` must not exceed the trailer's `steer_axle_rating_lb`, with equality passing; then `drive_lb` against `drive_axle_rating_lb`, and `trailer_lb` against `trailer_axle_rating_lb` — any axle over its inclusive rating is `ERR_AXLE_LIMIT_EXCEEDED`. Fourth, the sum of the three measured axles must not exceed `gvwr_lb`, again with equality passing, else `ERR_GVWR_EXCEEDED`. Finally, the measured sum must be consistent with the expected gross weight: the expected gross is the trailer's `tare_weight_lb` plus the product weight, where the product weight is the ticket's `net60_gallons` multiplied by the product's `density_lb_per_gal` and rounded half-up to a whole pound; if the absolute difference between the measured sum and the expected gross exceeds 3% of the expected gross — the 3% boundary itself is inclusive and passes — the check fails with `ERR_WEIGHT_SUM_INCONSISTENT`. Success stamps `weights_verified_at` from the clock. Placard confirmation is the other self-transition: the operator reports the `observed_placard_code` actually hung on the vehicle, and it must equal the product's `placard_code` exactly or the confirmation fails with `ERR_PLACARD_MISMATCH`; success sets `placards_confirmed` to true. Confirmation may be repeated while the shipment is `LOADED`; each successful call re-mutates the shipment (refreshing `updated_at` and incrementing `version`).

Departure is the `Dispatcher`'s act and moves the shipment `LOADED → IN_TRANSIT`. Three gates must all hold: weights verified (`weights_verified_at` set, else `ERR_WEIGHTS_NOT_VERIFIED`), placards confirmed (`placards_confirmed` true, else `ERR_PLACARDS_NOT_CONFIRMED`), and an APPROVED SpillResponsePlan existing for the shipment's (`customer_id`, `product_id`) pair whose `expires_at` is later than the logical clock — a missing, unapproved, suspended, or expired plan means `ERR_SPILL_PLAN_NOT_APPROVED`.

### 3.5. Delivery, Variance Review, and Retain Samples

At the consignee, the assigned `Driver` starts the delivery: the shipment must be `IN_TRANSIT` (`ERR_SHIPMENT_INVALID_STATE` otherwise), and the caller's `X-User-ID` must equal the shipment's `driver_id` — any other caller, including a different driver, is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Starting delivery moves the shipment `IN_TRANSIT → DELIVERING` and opens a DeliveryTicket with status `OPEN` and `opened_at` stamped from the clock.

Closing the delivery ticket is likewise reserved to the assigned driver, and the ticket must still be `OPEN` (`ERR_DELIVERY_TICKET_NOT_OPEN` otherwise). The driver reports `delivered_observed_gal`, the `delivered_temp_F` at the delivery point, and the `retain_sample_ml` volume drawn for the retain sample. The server computes `delivered_net60_gal` with the same temperature correction used at the rack — the delivered observed gallons times (1 − coefficient × (delivered temperature − 60)), rounded half-up to 1 decimal place — and snapshots the meter ticket's `net60_gallons` into the ticket's `loaded_net60_gal`. The allowed in-transit loss is then the smaller of two quantities: a flat 50.0-gallon cap, or a base allowance of 5.0 gallons plus 0.02 gallons per mile of the shipment's `route_miles`; the result is carried to 1 decimal place with round-half-up and stored as `allowed_loss_gal`. The `variance_gallons` is `loaded_net60_gal` minus `delivered_net60_gal`, a positive figure meaning shortage. The comparison decides everything, and equality accepts: a variance less than or equal to `allowed_loss_gal` closes the ticket `CLOSED_ACCEPTED` and moves the shipment `DELIVERING → DELIVERED`; a variance strictly greater closes it `CLOSED_VARIANCE` and moves the shipment `DELIVERING → VARIANCE_REVIEW`. Either way, `closed_at` is stamped, the closing driver's `X-User-ID` is recorded as `closed_by_driver_id`, the trailer is released `ASSIGNED → AVAILABLE`, and a RetainSample is created in `RETAINED` status with `quantity_ml` taken from `retain_sample_ml`, `taken_at` from the clock, `retain_until` computed as `taken_at` plus 90 days, and links to the owning `shipment_id` and the `delivery_ticket_id` whose close created it.

The variance branch carries one further cascade. If a DedicatedTrailerAgreement matching the shipment's (`customer_id`, `trailer_id`) is `ACTIVE`, its `flagged_shipment_count` increments by one; the moment that counter reaches 2, the agreement itself suspends `ACTIVE → SUSPENDED`. The accepted branch performs no such increment.

A shipment in `VARIANCE_REVIEW` waits for a `SafetyOfficer`, who resolves it by supplying a `resolution_note`; the shipment moves `VARIANCE_REVIEW → DELIVERED` (any other state draws `ERR_SHIPMENT_INVALID_STATE`) and the note is recorded on the shipment.

Retain samples outlive the delivery. A sample may be disposed by a `SafetyOfficer` only while `RETAINED` (else `ERR_SAMPLE_NOT_RETAINED`) and only once the logical clock is strictly later than `retain_until` (disposing earlier fails with `ERR_SAMPLE_STILL_IN_RETENTION`); disposal moves it `RETAINED → DISPOSED`, and `DISPOSED` is terminal.

### 3.6. Billing Totals, Credit Exposure, and Reconciliation

Billing is computed twice per shipment, on two different gallonage bases, but always through the same pinned assembly order. Each line is rounded half-up to integer cents before any summing — rounding the unrounded total instead is wrong. First the product charge: the basis gallons times the shipment's `rate_per_gal_cents`, rounded half-up to integer cents. Second the fuel surcharge: 4% of that product charge, again rounded half-up to integer cents. Third the total: the product charge plus the fuel surcharge plus a flat rack fee of 15000 cents ($150.00), minus any shortage credit.

The provisional variant runs at close-meter. Its basis is the meter ticket's `observed_gallons` — raw rack gallons with no temperature correction — and its shortage credit is zero; the result is stored on the shipment as `provisional_total_cents`. The final variant runs at reconciliation. Its basis is the delivery ticket's `delivered_net60_gal`, and its shortage credit compensates the customer for proven loss beyond the allowed tolerance: take `loaded_net60_gal` minus `delivered_net60_gal` minus `allowed_loss_gal`, floor the result at zero, multiply by `rate_per_gal_cents`, and round half-up to integer cents. The final total lands in `final_total_cents`; for identical route data the two figures differ whenever temperature correction or a shortage credit is non-zero.

Reconciliation itself belongs to the `FleetAdmin` and moves the shipment `DELIVERED → RECONCILED` (any other state draws `ERR_SHIPMENT_INVALID_STATE`). It is blocked while any SpillIncident on this shipment remains in `REPORTED` or `UNDER_REVIEW` — the attempt fails with `ERR_OPEN_INCIDENT` (409) — so incident hygiene gates final billing. On success the final total is computed, `reconciled_at` is stamped from the clock, and the customer's `exposure_cents` is recomputed.

The exposure figure deserves its own statement, because it aggregates every live financial commitment a customer has. A customer's `exposure_cents` is the sum of `provisional_total_cents` across all of the customer's shipments in `PLANNED`, `LOADING`, `LOADED`, `IN_TRANSIT`, `DELIVERING`, `DELIVERED`, or `VARIANCE_REVIEW` — for `PLANNED` shipments, which have no meter ticket yet, the plan-time estimate of §3.3 stands in — plus the sum of `final_total_cents` across all `RECONCILED` shipments. `DRAFT` and `CANCELLED` shipments contribute zero. The server recomputes exposure at six moments: when a plan is created (where it also gates, as in §3.3), when a meter ticket closes, when a shipment reconciles, when a shipment is unplanned, when a planned shipment is cancelled, and when revocation of a held certificate reverts its shipment to `DRAFT` (§3.2).

### 3.7. Spill Response Plans and Incident Reporting

Every (customer, product) pair that will ship hazmat-relevant loads needs an approved spill response plan before departure, and the plan lifecycle lives with the shipper and the safety office. A `CustomerRep` — who must own the plan's `customer_id` or be rejected with `ERR_INSUFFICIENT_PERMISSIONS` — or a `FleetAdmin` creates a plan with the `customer_id`, the covered `product_id`, and an `equipment_checklist` array of strings describing the spill kit; the plan starts `DRAFT`. The owning `CustomerRep` then submits it, moving `DRAFT → SUBMITTED` — the submitter's `X-User-ID` must equal the plan's `customer_id` (`ERR_INSUFFICIENT_PERMISSIONS`), and any other starting state draws `ERR_SPILL_PLAN_INVALID_STATE`. A `SafetyOfficer` adjudicates: approving moves `SUBMITTED → APPROVED` and stamps `approved_at` from the clock with `expires_at` computed as 365 days after approval; rejecting — optionally with a `reason`, which is accepted but not stored on the plan — moves it to `REJECTED`, a terminal state. Both decisions require `SUBMITTED`, else `ERR_SPILL_PLAN_INVALID_STATE`. An approved plan can be suspended (`APPROVED → SUSPENDED`) and later reinstated (`SUSPENDED → APPROVED`); reinstatement restores approval with `expires_at` unchanged from the original approval, so suspension never extends a plan's life. Each of these transitions requires its stated from-state, else `ERR_SPILL_PLAN_INVALID_STATE`. Finally, an `APPROVED` plan whose `expires_at` has passed flips to `EXPIRED` lazily on read, per §2.5.

Incidents are reported from the road by the assigned `Driver` — the caller's identity must match the shipment's `driver_id` per §2.1 — and only while the shipment is `IN_TRANSIT` or `DELIVERING`; a report against a shipment in any other state is rejected with `ERR_SHIPMENT_INVALID_STATE`. The driver supplies `occurred_at` and the estimated `gallons_spilled`; the server stamps `reported_at` from the logical clock, records the caller as `reported_by_driver_id`, and classifies `severity` by volume: below 10.0 gallons is `MINOR`, at least 10.0 but below 100.0 is `MAJOR` (exactly 10.0 therefore classifies `MAJOR`), and 100.0 gallons or more is `REPORTABLE` (exactly 100.0 classifies `REPORTABLE`). A `REPORTABLE` incident carries a regulatory deadline: it must be reported within 12 hours of `occurred_at`, with the report exactly 12 hours after the occurrence still on time; a later report is rejected with `ERR_REPORT_DEADLINE_MISSED`. A new incident starts in `REPORTED`.

Review is a conversation with the safety office. Starting review moves `REPORTED → UNDER_REVIEW`; requesting more information returns it `UNDER_REVIEW → REPORTED`, and the cycle can repeat. Closing requires `UNDER_REVIEW` and additionally requires the underlying shipment to be past transit — in `DELIVERED`, `VARIANCE_REVIEW`, `RECONCILED`, or `CANCELLED` — else `ERR_SHIPMENT_NOT_DELIVERED`; a successful close records the acting `SafetyOfficer`'s `X-User-ID` in `closed_by_user_id`. Reopening a `CLOSED` incident is possible but segregated: the reopener's `X-User-ID` must differ from the recorded `closed_by_user_id` (`ERR_SAME_OPERATOR_SEGREGATION`, 403), and a successful reopen moves the incident `CLOSED → UNDER_REVIEW` and clears `closed_by_user_id`. Every incident transition attempted from the wrong state is rejected with `ERR_INCIDENT_INVALID_STATE`.

### 3.8. The Dedicated-Trailer Program

Large shippers can reserve dedicated trailer capacity under a monthly volume commitment. A `FleetAdmin` creates a DedicatedTrailerAgreement naming the `customer_id` — the customer must have `dedicated_program_enrolled` set to true, else `ERR_NOT_PROGRAM_ENROLLED` — the `trailer_id`, the `committed_loads_per_month`, and an inclusive period from `effective_from` to `effective_to`, both ISO 8601 datetimes (a bare date is read as midnight UTC) and serialized back as full timestamps, where the end must be on or after the start (`ERR_INVALID_REQUEST` otherwise). Two agreements on the same trailer may not overlap: if another agreement in `PENDING` or `ACTIVE` status has an inclusive period intersecting the new one — each agreement's `effective_from` falling on or before the other's `effective_to` — creation is rejected with `ERR_AGREEMENT_PERIOD_CONFLICT` (409). The overlap check runs before the enrollment check, so a creation failing both is rejected with `ERR_AGREEMENT_PERIOD_CONFLICT`. A new agreement is `PENDING`, with `flagged_shipment_count`, `shortfall_events`, and `shortfall_fees_total_cents` all zero and `last_settled_month` null.

While `PENDING`, a `FleetAdmin` may revise `committed_loads_per_month` through the OCC-guarded revision of §2.7, which requires `expected_agreement_version` and increments the agreement's `version` by one; any other state draws `ERR_AGREEMENT_INVALID_STATE`. Activation moves `PENDING → ACTIVE` (again, `ERR_AGREEMENT_INVALID_STATE` from elsewhere) and requires the trailer to be undedicated — if the trailer's `dedicated_customer_id` is already set, activation fails with `ERR_TRAILER_ALREADY_DEDICATED` (409). A successful activation stamps the trailer's `dedicated_customer_id` with the agreement's customer, and from then on the dedication gate of §3.3 keeps that trailer working only for its dedicated customer. Termination from either `ACTIVE` or `SUSPENDED` (else `ERR_AGREEMENT_INVALID_STATE`) moves the agreement to `TERMINATED` and clears the trailer's `dedicated_customer_id` as a compensating release. The `SUSPENDED` state itself is never entered by direct action: it is the cascade of §3.5, reached when the agreement's `flagged_shipment_count` climbs to 2.

Settlement runs monthly through the close-month capability, which requires an `ACTIVE` agreement (`ERR_AGREEMENT_INVALID_STATE` otherwise) and a `settlement_month` in `YYYY-MM` form. The month must be strictly before the month containing the current logical clock and strictly after the `last_settled_month` when one exists — violations are `ERR_MONTH_NOT_CLOSABLE`. The server counts the completed loads: shipments whose `customer_id` and `trailer_id` both match the agreement, whose status is `RECONCILED`, and whose `reconciled_at` falls within the half-open window from the first instant of the settlement month up to but not including the first instant of the following month. The compliance floor is the agreement's `committed_loads_per_month` multiplied by 0.8 and rounded up to a whole load. If the completed count is strictly below the floor, a shortfall fee is assessed: the shortfall — floor minus completed — times 25000 cents ($250.00) per missing load, added into `shortfall_fees_total_cents`, with `shortfall_events` incremented by one. A completed count exactly equal to the floor is compliant and draws no fee. Either way, `last_settled_month` is set to the settled `settlement_month`.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify, transition, or act on an existing resource return `200 OK`, as do all reads. Action endpoints that mint subordinate resources only as a side effect — check-in opening the meter ticket, start-delivery opening the delivery ticket, and delivery-ticket close creating the retain sample — are act-on-existing endpoints and return `200 OK`, not 201. All resources are addressed flat under the `/bulk-liquid` prefix. List endpoints accept the `limit` and `offset` pagination parameters of §2.3 plus resource-specific filters: customers and drivers filter by `status`; products by `compatibility_group`; compatibility rules by `prior_group` and `next_group`; trailers by `status`, `dedicated_customer_id`, and `last_wash_cert_id`; wash certificates by `trailer_id`, `wash_bay_id`, `consumed_by_shipment_id`, and `status`; shipments by `customer_id`, `product_id`, `trailer_id`, `driver_id`, `rack_id`, `wash_cert_id`, and `status`; meter tickets by `shipment_id` and `rack_id`; delivery tickets by `shipment_id`; retain samples by `shipment_id` and `delivery_ticket_id`; spill response plans by `customer_id`, `product_id`, and `status`; spill incidents by `shipment_id`, `reported_by_driver_id`, and `status`; and dedicated-trailer agreements by `customer_id`, `trailer_id`, and `status`. Request payloads, preconditions, computed fields, and side effects for each operation are specified in §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bulk-liquid/_clock/set_current_utc` | Set the server logical clock | FleetAdmin |
| POST | `/bulk-liquid/customers` | Create a customer | FleetAdmin |
| GET | `/bulk-liquid/customers` | List customers | Any |
| GET | `/bulk-liquid/customers/{customerId}` | Get a customer | Any |
| POST | `/bulk-liquid/customers/{customerId}/suspend` | Suspend an active customer | FleetAdmin |
| POST | `/bulk-liquid/customers/{customerId}/reactivate` | Reactivate a suspended customer | FleetAdmin |
| POST | `/bulk-liquid/products` | Create a product | FleetAdmin |
| GET | `/bulk-liquid/products` | List products | Any |
| GET | `/bulk-liquid/products/{productId}` | Get a product | Any |
| POST | `/bulk-liquid/compatibility-rules` | Create a prior-load compatibility rule | FleetAdmin |
| GET | `/bulk-liquid/compatibility-rules` | List compatibility rules | Any |
| GET | `/bulk-liquid/compatibility-rules/{ruleId}` | Get a compatibility rule | Any |
| POST | `/bulk-liquid/trailers` | Create a tank trailer | FleetAdmin |
| GET | `/bulk-liquid/trailers` | List trailers | Any |
| GET | `/bulk-liquid/trailers/{trailerId}` | Get a trailer | Any |
| POST | `/bulk-liquid/drivers` | Create a driver | FleetAdmin |
| GET | `/bulk-liquid/drivers` | List drivers | Any |
| GET | `/bulk-liquid/drivers/{driverId}` | Get a driver | Any |
| POST | `/bulk-liquid/drivers/{driverId}/deactivate` | Deactivate a driver | FleetAdmin |
| POST | `/bulk-liquid/wash-bays` | Create a wash bay | FleetAdmin |
| GET | `/bulk-liquid/wash-bays` | List wash bays | Any |
| GET | `/bulk-liquid/wash-bays/{washBayId}` | Get a wash bay | Any |
| POST | `/bulk-liquid/tank-wash-certificates` | Book a wash window on a bay | WashOperator |
| GET | `/bulk-liquid/tank-wash-certificates` | List wash certificates | Any |
| GET | `/bulk-liquid/tank-wash-certificates/{certId}` | Get a wash certificate | Any |
| POST | `/bulk-liquid/tank-wash-certificates/{certId}/certify` | Certify a completed wash | WashOperator |
| POST | `/bulk-liquid/tank-wash-certificates/{certId}/revoke` | Revoke a certified or held certificate | SafetyOfficer |
| POST | `/bulk-liquid/tank-wash-certificates/{certId}/cancel-booking` | Cancel a scheduled wash booking | WashOperator |
| POST | `/bulk-liquid/loading-racks` | Create a loading rack | FleetAdmin |
| GET | `/bulk-liquid/loading-racks` | List loading racks | Any |
| GET | `/bulk-liquid/loading-racks/{rackId}` | Get a loading rack | Any |
| POST | `/bulk-liquid/shipments` | Create a shipment request in DRAFT | Dispatcher, CustomerRep |
| GET | `/bulk-liquid/shipments` | List shipments | Any |
| GET | `/bulk-liquid/shipments/{shipmentId}` | Get a shipment | Any |
| PATCH | `/bulk-liquid/shipments/{shipmentId}` | Revise a DRAFT shipment's commercial terms (OCC) | Dispatcher |
| POST | `/bulk-liquid/shipments/{shipmentId}/plan` | Plan a shipment: trailer, driver, rack window, optional wash cert | Dispatcher |
| POST | `/bulk-liquid/shipments/{shipmentId}/unplan` | Return a PLANNED shipment to DRAFT with compensating releases | Dispatcher |
| POST | `/bulk-liquid/shipments/{shipmentId}/cancel` | Cancel a DRAFT or PLANNED shipment | Dispatcher, CustomerRep |
| POST | `/bulk-liquid/shipments/{shipmentId}/check-in` | Check in at the rack and open the meter ticket | TerminalOperator |
| POST | `/bulk-liquid/shipments/{shipmentId}/abort-loading` | Abort loading and return to PLANNED | TerminalOperator |
| POST | `/bulk-liquid/shipments/{shipmentId}/close-meter` | Close the meter ticket and compute provisional billing | TerminalOperator |
| POST | `/bulk-liquid/shipments/{shipmentId}/record-weights` | Record measured axle weights with SoD and compliance checks | TerminalOperator |
| POST | `/bulk-liquid/shipments/{shipmentId}/confirm-placards` | Confirm applied placards match the product | TerminalOperator |
| POST | `/bulk-liquid/shipments/{shipmentId}/depart` | Depart the terminal for delivery | Dispatcher |
| POST | `/bulk-liquid/shipments/{shipmentId}/start-delivery` | Begin delivery and open the delivery ticket | Driver |
| POST | `/bulk-liquid/shipments/{shipmentId}/resolve-variance` | Resolve a variance-reviewed delivery | SafetyOfficer |
| POST | `/bulk-liquid/shipments/{shipmentId}/reconcile` | Finalize billing and reconcile the shipment | FleetAdmin |
| GET | `/bulk-liquid/meter-tickets` | List meter tickets | Any |
| GET | `/bulk-liquid/meter-tickets/{ticketId}` | Get a meter ticket | Any |
| GET | `/bulk-liquid/delivery-tickets` | List delivery tickets | Any |
| GET | `/bulk-liquid/delivery-tickets/{ticketId}` | Get a delivery ticket | Any |
| POST | `/bulk-liquid/delivery-tickets/{ticketId}/close` | Close a delivery ticket with metered delivery and retain sample | Driver |
| GET | `/bulk-liquid/retain-samples` | List retain samples | Any |
| GET | `/bulk-liquid/retain-samples/{sampleId}` | Get a retain sample | Any |
| POST | `/bulk-liquid/retain-samples/{sampleId}/dispose` | Dispose of a sample past its retention period | SafetyOfficer |
| POST | `/bulk-liquid/spill-response-plans` | Create a spill response plan | CustomerRep, FleetAdmin |
| GET | `/bulk-liquid/spill-response-plans` | List spill response plans | Any |
| GET | `/bulk-liquid/spill-response-plans/{planId}` | Get a spill response plan | Any |
| POST | `/bulk-liquid/spill-response-plans/{planId}/submit` | Submit a plan for approval | CustomerRep |
| POST | `/bulk-liquid/spill-response-plans/{planId}/approve` | Approve a submitted plan | SafetyOfficer |
| POST | `/bulk-liquid/spill-response-plans/{planId}/reject` | Reject a submitted plan | SafetyOfficer |
| POST | `/bulk-liquid/spill-response-plans/{planId}/suspend` | Suspend an approved plan | SafetyOfficer |
| POST | `/bulk-liquid/spill-response-plans/{planId}/reinstate` | Reinstate a suspended plan | SafetyOfficer |
| POST | `/bulk-liquid/shipments/{shipmentId}/spill-incidents` | Report a spill during transit or delivery | Driver |
| GET | `/bulk-liquid/spill-incidents` | List spill incidents | Any |
| GET | `/bulk-liquid/spill-incidents/{incidentId}` | Get a spill incident | Any |
| POST | `/bulk-liquid/spill-incidents/{incidentId}/start-review` | Open incident review | SafetyOfficer |
| POST | `/bulk-liquid/spill-incidents/{incidentId}/request-info` | Return an incident to the reporter for more information | SafetyOfficer |
| POST | `/bulk-liquid/spill-incidents/{incidentId}/close` | Close an incident under review | SafetyOfficer |
| POST | `/bulk-liquid/spill-incidents/{incidentId}/reopen` | Reopen a closed incident (different officer than the closer) | SafetyOfficer |
| POST | `/bulk-liquid/dedicated-trailer-agreements` | Create a dedicated-trailer agreement | FleetAdmin |
| GET | `/bulk-liquid/dedicated-trailer-agreements` | List dedicated-trailer agreements | Any |
| GET | `/bulk-liquid/dedicated-trailer-agreements/{agreementId}` | Get a dedicated-trailer agreement | Any |
| PATCH | `/bulk-liquid/dedicated-trailer-agreements/{agreementId}` | Revise a PENDING agreement's committed volume (OCC) | FleetAdmin |
| POST | `/bulk-liquid/dedicated-trailer-agreements/{agreementId}/activate` | Activate an agreement and dedicate the trailer | FleetAdmin |
| POST | `/bulk-liquid/dedicated-trailer-agreements/{agreementId}/terminate` | Terminate an agreement and release the trailer | FleetAdmin |
| POST | `/bulk-liquid/dedicated-trailer-agreements/{agreementId}/close-month` | Settle a past calendar month and assess any shortfall fee | FleetAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the workflow narratives of §2 and §3; this table is the authoritative mapping of error identifier to HTTP status code.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_COMPATIBILITY_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_TRAILER_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_WASH_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_WASH_CERT_NOT_FOUND` | 404 Not Found |
| `ERR_RACK_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_METER_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_RETAIN_SAMPLE_NOT_FOUND` | 404 Not Found |
| `ERR_SPILL_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SPILL_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found (405 Method Not Allowed when the path exists but the method is unsupported) |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 Conflict |
| `ERR_TRAILER_NOT_AVAILABLE` | 409 Conflict |
| `ERR_DRIVER_NOT_ACTIVE` | 409 Conflict |
| `ERR_SHIPMENT_INVALID_STATE` | 409 Conflict |
| `ERR_CERT_INVALID_STATE` | 409 Conflict |
| `ERR_DELIVERY_TICKET_NOT_OPEN` | 409 Conflict |
| `ERR_SAMPLE_NOT_RETAINED` | 409 Conflict |
| `ERR_SPILL_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_WEIGHTS_ALREADY_VERIFIED` | 409 Conflict |
| `ERR_WEIGHTS_NOT_VERIFIED` | 409 Conflict |
| `ERR_PLACARDS_NOT_CONFIRMED` | 409 Conflict |
| `ERR_OPEN_INCIDENT` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 Conflict |
| `ERR_PRODUCT_INCOMPATIBILITY_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_COMPATIBILITY_RULE_MISSING` | 422 Unprocessable Entity |
| `ERR_WASH_LEVEL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_WASH_CERT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DRIVER_ENDORSEMENT_MISSING` | 422 Unprocessable Entity |
| `ERR_DRIVER_ENDORSEMENT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_PLACARD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AXLE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_GVWR_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WEIGHT_SUM_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_SPILL_PLAN_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_WINDOW_OUTSIDE_OPERATING_HOURS` | 422 Unprocessable Entity |
| `ERR_RACK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_WASH_BAY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_RACK_WINDOW_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_REPORT_DEADLINE_MISSED` | 422 Unprocessable Entity |
| `ERR_SAMPLE_STILL_IN_RETENTION` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_MONTH_NOT_CLOSABLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_CDL_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_COMPATIBILITY_RULE` | 409 Conflict |
| `ERR_TARE_AXLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRAILER_DEDICATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TRAILER_ALREADY_DEDICATED` | 409 Conflict |
| `ERR_SAME_OPERATOR_SEGREGATION` | 403 Forbidden |
| `ERR_NOT_PROGRAM_ENROLLED` | 422 Unprocessable Entity |
| `ERR_RACK_NOT_AUTHORIZED_FOR_PRODUCT` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |

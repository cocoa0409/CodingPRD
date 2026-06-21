# Auto Glass & Windshield Repair API — Product Requirements Document

## 1. Introduction

The Auto Glass & Windshield Repair API is the operational backbone of a glass-service shop that diagnoses windshield damage, decides whether a chip or crack can be repaired or whether the glass must be replaced, sources the correct part, schedules the work either at the customer's location or in the shop, recalibrates advanced driver-assistance (ADAS) cameras after a replacement, enforces adhesive cure time before the vehicle leaves, collects payment, and issues a warranty. The work order is the spine of the system: every assessment, part reservation, appointment, recalibration, payment, and warranty hangs off a single work order whose lifecycle the API drives forward through a branching set of states.

What makes the domain interesting is the way the branches diverge and rejoin. A damage assessment produces a deterministic repair-vs-replace recommendation from four physical measurements. Once accepted, that decision freezes a price quote. A repair is a short job that completes the moment the technician finishes. A replacement is longer: glass is pulled from reserved stock, adhesive must cure for a temperature- and humidity-dependent interval before the car is safe to drive, and if the windshield carries an ADAS camera the vehicle cannot leave until a recalibration passes. The API must keep the financial ledger, the physical inventory, and the safety gates all consistent as a job moves through these forks.

This document specifies the complete contract: the resource model, the state machines for the work order and its satellite entities, the pricing and cure-time calculations, the validation rules that protect safety and money, and the role-based access controls that separate the customer, the front-desk advisor, the field technician, and the shop manager.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The collections it governs are mounted root-relative: `/customers`, `/vehicles`, `/work-orders`, `/glass-parts`, `/part-orders`, `/service-appointments`, `/recalibration-jobs`, `/payments`, `/warranties`, `/technicians`, and `/service-bays`.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `ServiceAdvisor`, `Technician`, and `ShopManager`. A request that omits either header, or whose `X-User-Role` is not one of these four known roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not permitted to invoke the targeted endpoint per the access matrix in Section 4 is rejected with `ERR_FORBIDDEN`.

The four roles divide responsibility as follows. The `Customer` is the vehicle owner; they open work orders, make payments, and read their own resources. The `ServiceAdvisor` runs the front desk — recording assessments, accepting them, quoting, scheduling, ordering parts, booking and cancelling appointments, capturing payments, and cancelling work orders. The `Technician` performs field and shop work — starting service, finishing the install, checking customers in, and executing ADAS recalibration. The `ShopManager` owns the catalog and inventory and holds financial authority — creating parts, restocking, receiving backorders, creating technicians and bays, issuing refunds, voiding warranties, and driving the test clock.

Two of these roles are tied to a persisted entity, and ownership is enforced through `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. A `Customer` may open a work order only for their own `customer_id`, may pay only against their own work order, and may read only their own customer record, vehicles, work orders, and the sub-resources of those work orders; any attempt to act on another customer's resource is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; where a transition or recalibration is performed by a technician, the server identifies the actor by matching `X-User-ID` to a `Technician.id`. The remaining two roles are operator identities not bound to ownership: when `X-User-Role` is `ServiceAdvisor`, `X-User-ID` is an opaque front-desk operator identifier not tied to any persisted entity, and when `X-User-Role` is `ShopManager`, `X-User-ID` is likewise an opaque operator identifier; the server may record either value but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. An out-of-range `limit` is silently clamped into this range (a value below 1 becomes 1 and a value above 100 becomes 100) rather than rejected. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative `offset` is silently clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The echoed `limit` and `offset` in the response `meta` reflect the clamped values actually applied.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — the `Customer`, `Vehicle`, `WorkOrder`, `DamageAssessment`, `GlassPart`, `PartOrder`, `Technician`, `ServiceBay`, `ServiceAppointment`, `RecalibrationJob`, `Payment`, and `Warranty` — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification to the resource.
- **`version`** (integer): an integer that starts at the resource's creation value and increments by one on every mutation. It is the basis for the optimistic concurrency control described in Section 2.7.

All twelve resource types in this system carry the full set of these fields, including `updated_at` and `version`. When a computed field on a `WorkOrder` — such as `total_charge_cents`, `amount_paid_cents`, `service_decision`, `service_location`, `recalibration_required`, `assessment_version`, or `safe_drive_away_at` — changes as a side effect of any operation, that change is itself a mutation: it refreshes the work order's `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval and Reference Validation

Many endpoints address a resource through a path that nests it under a parent, and many request bodies reference other resources by their foreign-key fields. For any such request, the system validates the existence of each referenced resource in a strict left-to-right order along the path, and then validates the existence of each required foreign-key reference in the body. The request is rejected with `ERR_NOT_FOUND` for the first identifier — path segment or required reference — that does not correspond to an existing resource. For example, a request to list the assessments of a work order that does not exist fails with `ERR_NOT_FOUND` before any assessment is examined; a part-order create that names a `work_order_id` and a `glass_part_id` fails with `ERR_NOT_FOUND` if either does not exist. Existence validation precedes field validation, which in turn precedes state and business-rule validation.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts in this system are stored and exchanged as integer counts of cents — `total_charge_cents`, `amount_paid_cents`, `unit_price_cents`, `amount_cents`, and `refunded_amount_cents` are all integers. Wherever a calculation derives a fee as a percentage of another amount, the percentage is applied to the relevant base and the result is rounded to the nearest whole cent using the round-half-up convention (a fractional cent of exactly one-half rounds up). Each fee is rounded as a single, pinned step at the point the calculation specifies; intermediate sums are not pre-rounded per component except where a calculation explicitly states the rounding boundary. The cure-time calculation works in whole minutes and produces an instant expressed as an ISO 8601 UTC timestamp with three fractional digits. Damage measurements compare exactly: chip counts are integer comparisons and millimetre measurements are compared exactly to a tenth of a millimetre with no rounding.

### 2.7. Optimistic Concurrency Control on the Work Order

Two write operations require the client to prove it is acting on a fresh view of the parent work order by carrying the work order's expected version. Both use the field `expected_work_order_version`, which must equal the target `WorkOrder.version` at the moment the write is processed; a mismatch is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412).

The first is reserving a glass part. A request to create a part order must carry `expected_work_order_version` matching the target work order's current `version`. A successful reservation moves stock and increments the work order's `version`, so a prior view of the work order's part state is legitimately superseded; if a second create still carries the version observed before that first reservation, it is operating on a stale view and is refused with `ERR_STALE_WORK_ORDER_VERSION` so it cannot double-commit stock. The second is opening a recalibration job. A request to create a recalibration job must likewise carry `expected_work_order_version` matching the work order's current `version`; because each successful recalibration create — and the finish-install that earlier carried the work order into `AWAITING_RECALIBRATION` — increments that `version`, a create still carrying the older version is acting on a stale view and is rejected with the same `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412). No other endpoint takes a version field; only part-order create and recalibration-job create are OCC-guarded.

### 2.8. Validation Ordering

When a single request is subject to several checks, they are evaluated in a fixed priority order so that the rejection a client receives is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization including ownership for entity-backed roles (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then the presence and well-typedness of required input fields, including that enum fields carry a declared member and that any `end_at` is strictly after its `start_at` (`ERR_INVALID_REQUEST`). Only after these structural checks does the system evaluate whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then the optimistic-concurrency check on the work order version where it applies (`ERR_STALE_WORK_ORDER_VERSION`), and finally the domain-specific safety, scheduling, referential, and fiscal rules described throughout Section 3.

### 2.9. Inventory Integrity and Cascading State

The system holds physical stock consistent through every state change. Each `GlassPart` tracks `on_hand_qty`, the units physically in stock and unreserved, and `reserved_qty`, the units committed to open part orders but not yet consumed. Reserving a part moves units out of `on_hand_qty` and into `reserved_qty`; consuming the glass at install time draws down `reserved_qty`; cancelling a reserved order returns units to `on_hand_qty` and draws down `reserved_qty`; and receiving a backordered part moves arriving stock directly into `reserved_qty`. Whenever a parent work order reaches a terminal cancellation, its still-open satellites are resolved in the same operation: a booked appointment is cancelled and a reserved part order is cancelled with its stock released, so the system never strands a reservation or an appointment against a dead work order. These cascades, and the version bumps they imply on every touched resource, are detailed in the workflow narratives of Section 3.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Customer, the Vehicle, and the Catalog

Before any glass work can begin, the parties and the inventory must exist. A `ServiceAdvisor` or `ShopManager` registers a `Customer` with a `full_name`, an `email`, an optional `phone`, and a `service_address_state`. The `full_name` and `email` must be non-empty, the `email` must be unique across all customers, and the `service_address_state` is a two-letter uppercase US state code — validated structurally as exactly two uppercase ASCII letters, with no check against a roster of real US states — that will later govern mobile-service eligibility and trip pricing. The `phone` is optional and accepts any string; when it is omitted it is stored and returned as null. An attempt to register a customer whose `email` duplicates an existing one is rejected with `ERR_DUPLICATE`.

A vehicle is registered against an owning customer. The create body names the `customer_id` of the owner and supplies the `vin`, the `make`, the `model`, the `model_year`, the OEM windshield part number `glass_part_number` stamped on the vehicle, and optionally `adas_equipped`. The `vin` must be exactly seventeen characters and unique across all vehicles; a duplicate `vin` is rejected with `ERR_DUPLICATE`. The `model_year` must fall in the inclusive range from 1980 through 2027. The `adas_equipped` flag marks a vehicle whose windshield carries an ADAS camera that will require recalibration after a replacement; when the field is omitted at creation it defaults to false. Both a `Customer` and a `Vehicle` can be read back individually, and the system exposes reverse lookups that list all vehicles for a customer, all work orders for a customer, and all work orders for a vehicle.

The `ShopManager` owns the parts catalog. Creating a `GlassPart` supplies the `oem_part_number` it fulfils (which must be non-empty and is matched against a vehicle's `glass_part_number` during part lookup), an optional human-readable `description` (any string; stored and returned as null when omitted), the catalog `unit_price_cents` (which must be at least zero), an optional `adas_compatible` flag, and an optional opening `on_hand_qty` (which, when supplied, must be at least zero). When `adas_compatible` is omitted it defaults to false; when `on_hand_qty` is omitted the part opens with zero units, and `reserved_qty` always starts at zero. A part flagged `adas_compatible` carries the bracket and optics an ADAS camera needs. Parts can be fetched individually and listed; the list endpoint accepts an `oem_part_number` filter to find the SKU matching a vehicle's required part and an `adas_compatible` filter, alongside the standard `limit` and `offset`. To add stock to an existing SKU the manager submits an `add_qty` (a required integer of at least one), which increments `on_hand_qty` by that amount.

The `ShopManager` also stands up the workforce and the shop floor. A `Technician` is created with a `full_name`, a `home_state` (the two-letter uppercase US state code the technician is licensed to do mobile work in), and the optional flags `can_mobile` and `adas_certified`; `can_mobile` defaults to true and marks a technician who performs on-site jobs, while `adas_certified` defaults to false and marks one certified to perform ADAS recalibration. A `ServiceBay` is created with a `name`, a `bay_type`, and an optional `cleanroom` flag that defaults to false. The `bay_type` is either `INSTALL`, for bays that do glass replacement only, or `CALIBRATION`, for bays that support static ADAS recalibration against a fixed target board; a `cleanroom` bay is a controlled-temperature space. Technicians and bays can each be fetched by id.

### 3.2. Opening a Work Order and Assessing the Damage

A work order is the unit of work. A `Customer` (acting only for their own `customer_id`) or a `ServiceAdvisor` opens one by naming the `customer_id` and the `vehicle_id`. A new work order starts in `OPEN` status, with `service_decision` null, `service_location` null, `recalibration_required` false, `assessment_version` zero, `total_charge_cents` zero, `amount_paid_cents` zero, and `safe_drive_away_at` null. A work order can be fetched by id by the advisor, the manager, the owning customer, or a technician.

With a work order open, a `ServiceAdvisor` records a damage assessment against it. The assessment body reports the `chip_count` (a count of distinct chips, at least zero), the `longest_crack_mm` (the length in millimetres of the longest crack, at least zero), the `edge_distance_mm` (the millimetre distance from the nearest damage to the glass edge, at least zero), and an optional `in_driver_primary_view` flag that defaults to false and is true when any damage sits inside the driver's primary acuity area, the wiper-swept zone directly in front of the driver. From these four measurements the server computes a `recommendation` and stores the assessment in `DRAFT` status. The same work order may accumulate several assessments; they can be listed for review.

The `recommendation` is a deterministic repair-vs-replace decision over the single assessment row being created, with no aggregation across rows. The system evaluates four disqualifiers in a fixed order, and the first one that holds forces a `REPLACE` recommendation; if none hold, the recommendation is `REPAIR`. The disqualifiers, in order, are: first, the damage sits in the driver's primary view (`in_driver_primary_view` is true); second, the longest crack is strictly greater than 150 millimetres; third, the nearest damage is strictly less than 12 millimetres from the edge, where a crack near the edge propagates; and fourth, the chip count is strictly greater than three. The boundaries are deliberately one-sided: a crack of exactly 150 millimetres is repairable, an edge distance of exactly 12 millimetres is repairable, and a chip count of exactly three is repairable — only values past those thresholds force a replacement. A damage in the driver's primary view always forces a replacement regardless of the measured dimensions.

### 3.3. Accepting the Assessment and Freezing the Quote

When the advisor and customer agree on a course of action, the `ServiceAdvisor` accepts one draft assessment onto the work order by naming its `assessment_id` in the body. Acceptance is defined only from `OPEN`; the named assessment must exist for this work order and be in `DRAFT` status. Accepting it advances the work order from `OPEN` to `ASSESSED` and produces a tight cluster of side effects: the work order's `service_decision` is set to the accepted assessment's `recommendation`; that assessment moves to `ACCEPTED`, and any other assessment already in `ACCEPTED` on this work order is moved to `SUPERSEDED`; the work order's `assessment_version` increments by one to support re-assessment audit; the price is quoted into `total_charge_cents`; and the work order's `version` increments by one. If the work order is not in `OPEN`, the acceptance is rejected with `ERR_INVALID_STATE`.

The quote written into `total_charge_cents` is computed from the accepted `service_decision` and the vehicle's `adas_equipped` flag, in whole cents. For a `REPAIR`, the base is 8,900 cents and there is no ADAS fee. For a `REPLACE`, the base is 32,500 cents, and if the vehicle is ADAS-equipped an additional ADAS recalibration fee of 19,900 cents is added to the base; a `REPLACE` on a vehicle that is not ADAS-equipped carries no such fee. On top of the base (plus the ADAS fee when it applies) the system adds a shop fee equal to 8.5 percent of that combined base-plus-ADAS amount, computed by summing the base and the ADAS fee first and then rounding the percentage of that sum half-up to the nearest cent — the rounding is performed once on the summed base, never per component. The final `total_charge_cents` is the base, plus the ADAS fee when present, plus that rounded shop fee. No mobile trip fee is included at acceptance time, because the service location is not yet chosen; the trip fee is added later at scheduling, as described in Section 3.4, and it reads the value frozen here rather than recomputing it.

### 3.4. Sourcing the Part, Booking the Appointment, and Scheduling

A `REPLACE` cannot be scheduled until its glass is in hand. The `ServiceAdvisor` orders the part by naming the `work_order_id`, the `glass_part_id` of the chosen SKU, an optional `quantity` (which defaults to one — always one for a single windshield, and at least one), and the `expected_work_order_version` that guards against a stale view of the work order as described in Section 2.7. If the target vehicle is ADAS-equipped, the chosen `GlassPart` must be `adas_compatible`; ordering a non-compatible part for an ADAS vehicle is rejected with `ERR_ADAS_PART_INCOMPATIBLE`. When the part is created, the system checks stock: if `on_hand_qty` is at least the ordered `quantity`, the order is placed directly into `RESERVED`, which decrements that part's `on_hand_qty` by the quantity, increments its `reserved_qty` by the quantity, and increments the parent work order's `version` by one because the reservation changes the work order's part state; if `on_hand_qty` is below the ordered `quantity`, the order is placed into `BACKORDERED` with no stock movement, and the work order cannot be scheduled for a replacement until that part is received. A part order begins life in `PENDING` and immediately resolves to one of these two outcomes. A backordered order is later moved to `RESERVED` by the `ShopManager` when the stock arrives; receiving it increments the part's `reserved_qty` by the quantity (the arriving stock lands directly in reservation for this order) and increments the work order's `version` by one. Part orders can be fetched and listed, filtered by `glass_part_id` or `work_order_id`, and listed under a work order.

In parallel, the `ServiceAdvisor` books an appointment for the work order. The booking names the `work_order_id`, the assigned `technician_id`, an optional `service_bay_id` (required for in-shop jobs, null for mobile), the `service_location`, and the appointment window `start_at` and `end_at`, both UTC ISO 8601 instants where `end_at` must be strictly after `start_at`. The `service_location` is either `MOBILE`, performed at the customer's site, or `IN_SHOP`. A new appointment starts in `BOOKED`. The appointment must not collide with the assigned technician's existing schedule: an appointment's half-open window from `start_at` up to `end_at` may not overlap any other non-cancelled appointment for the same technician, where back-to-back appointments that share an instant (one ending exactly when the next begins) are allowed and only a true point of overlap collides; a violation is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`. For a `MOBILE` appointment, the assigned technician must have `can_mobile` true and a `home_state` matching the customer's `service_address_state`; otherwise the booking is rejected with `ERR_MOBILE_TECH_UNAVAILABLE`. A booked appointment can be cancelled by the advisor while it is still `BOOKED`, can be fetched, and can be listed with filters for `technician_id`, `service_bay_id`, or `work_order_id`.

Scheduling ties the appointment to the work order and moves it from `ASSESSED` to `SCHEDULED`. The `ServiceAdvisor` schedules by naming the `appointment_id` of a `BOOKED` appointment that references this work order. Several conditions guard the transition. The work order must be in `ASSESSED`. If the `service_decision` is `REPLACE`, a part order for this work order must already be in `RESERVED`; scheduling a replacement whose part is not yet reserved is rejected with `ERR_PART_NOT_READY`. A `REPLACE` work order whose recalibration is required — an ADAS vehicle — cannot be scheduled onto a `MOBILE` appointment because recalibration needs the shop; such an attempt is rejected with `ERR_MOBILE_NOT_ELIGIBLE`. When the transition succeeds, the work order's `service_location` is set from the appointment's `service_location`, its `recalibration_required` is set true exactly when the `service_decision` is `REPLACE` and the vehicle is ADAS-equipped (and false otherwise), the trip fee is added to `total_charge_cents`, and the work order's `version` increments by one.

The trip fee added at scheduling is tiered on the appointment's `service_location` and the customer's `service_address_state` relative to the shop home state, which is `CA`. It is computed as a percentage of the already-frozen `total_charge_cents` produced at acceptance — that frozen value is read as-is and never recomputed here, pinning the evaluation order so the quote is finalized first and the trip fee second. For an `IN_SHOP` appointment the trip fee is zero and the total is unchanged. For a `MOBILE` appointment whose customer `service_address_state` equals `CA`, the trip rate is 4 percent of the frozen total; for a `MOBILE` appointment whose customer state is anything other than `CA`, the trip rate is 9 percent of the frozen total. The trip fee is that rate applied to the frozen `total_charge_cents`, rounded half-up to the nearest cent, and the new `total_charge_cents` is the frozen total plus that trip fee.

### 3.5. Performing the Work: Start, Install, and Cure

Once a job is scheduled, the appointment is checked in and the work begins. A `Technician` checks an appointment in, moving it from `BOOKED` to `CHECKED_IN`; this is permitted only while the appointment is `BOOKED` and the linked work order is in `SCHEDULED`, and it increments the appointment's `version` by one. The same technician then starts service, advancing the work order from `SCHEDULED` to `IN_SERVICE`; this requires the work order to be `SCHEDULED` and its linked appointment to be `CHECKED_IN`, and it increments the work order's `version` by one.

How the job leaves `IN_SERVICE` depends entirely on the service decision. A `REPAIR` job has no adhesive cure and no recalibration: the `ServiceAdvisor` completes it directly out of `IN_SERVICE`, as described in Section 3.6. A `REPLACE` job goes through the install-finish step, in which the `Technician` reports the install environment by supplying the `temp_c` (the ambient temperature in Celsius) and the `humidity_pct` (the relative humidity percentage). Finishing the install is defined only when the work order is `IN_SERVICE` and the `service_decision` is `REPLACE`; it always stamps the work order's `safe_drive_away_at`, marks this work order's `RESERVED` part order as `CONSUMED` and decrements that part's `reserved_qty` by the quantity (the glass is now installed), and increments the work order's `version` by one. The destination state forks on recalibration: when `recalibration_required` is true the work order moves to `AWAITING_RECALIBRATION`, and when `recalibration_required` is false it moves to `CURING`. Both forks perform the same three side effects; they differ only in the resulting state.

The `safe_drive_away_at` is the earliest instant the customer may drive after a replacement, and it is computed from the reported install environment and the server's current clock at the moment the install finishes. A base cure interval in minutes is selected by temperature band: when `temp_c` is at least 24 the base is 60 minutes; when `temp_c` is at least 4 but below 24 the base is 120 minutes; and when `temp_c` is below 4 the base is 240 minutes. A humidity penalty is then added: when `humidity_pct` is strictly below 15 an extra 30 minutes is added, and otherwise nothing is added. The boundaries are one-sided: a temperature of exactly 24 falls in the warm 60-minute band, a temperature of exactly 4 falls in the mild 120-minute band, and a humidity of exactly 15 incurs no dry-air penalty because the penalty applies only below 15. The `safe_drive_away_at` is the current clock at install-finish advanced by the base minutes plus the humidity penalty minutes, expressed as an ISO 8601 UTC instant with three fractional digits. The system also exposes a conservative posted estimate ahead of the install: a computed read for a `REPLACE` work order returns `posted_sdat_minutes` and `posted_safe_drive_away_at` assuming the worst band for the day — the cold base of 240 minutes plus the dry penalty of 30 minutes, totaling 270 minutes regardless of any actual reading. The `posted_safe_drive_away_at` is the server's current clock at the moment of the read advanced by those 270 minutes, expressed as an ISO 8601 UTC instant with three fractional digits. The read returns these two fields directly in `data` (it carries no other work-order fields) with HTTP 200, and is not gated on the work order's `service_decision` or status — any existing work order the caller may read yields the same `posted_sdat_minutes` of 270 and the corresponding `posted_safe_drive_away_at`. This posted estimate is informational and does not stamp the work order.

### 3.6. ADAS Recalibration

A `REPLACE` on an ADAS vehicle cannot release the car until the camera is recalibrated. With the work order in `AWAITING_RECALIBRATION`, a `Technician` opens a recalibration job by naming the `work_order_id`, the `technician_id` performing the work, an optional `service_bay_id`, the `calibration_type`, the window `start_at` and `end_at` (UTC instants with `end_at` strictly after `start_at`), and the `expected_work_order_version` that guards against a stale view of the work order per Section 2.7. The `calibration_type` is either `STATIC`, which uses a fixed target board and requires a `CALIBRATION` bay (its `service_bay_id` must name one), or `DYNAMIC`, a road drive for which the bay is null. A recalibration job may only be created by a technician who is `adas_certified`; an attempt by an uncertified technician, or a `STATIC` calibration without a `CALIBRATION` bay, is rejected with `ERR_TECH_NOT_CERTIFIED`. A new recalibration job starts in `SCHEDULED`, and its creation increments the work order's `version` by one — which is why a second create still carrying the now-superseded version is refused as stale. A `STATIC` recalibration must not crowd another in the same `CALIBRATION` bay: its window plus a fifteen-minute clearance buffer on each side must not overlap any other non-cancelled recalibration in that bay, so two recalibrations collide when the gap between them is strictly less than fifteen minutes; a violation is rejected with `ERR_BAY_DOUBLE_BOOKED`. Recalibration jobs can be fetched and listed with filters for `technician_id`, `service_bay_id`, or `work_order_id`, and listed under a work order.

A recalibration runs to one of two outcomes. A `Technician` who is `adas_certified` passes it, moving it from `SCHEDULED` to `PASSED`; passing requires the job to be `SCHEDULED`, the linked work order to be in `AWAITING_RECALIBRATION`, and the acting technician to be `adas_certified` — an uncertified attempt to pass is rejected with `ERR_TECH_NOT_CERTIFIED`. Passing bubbles up to the parent: the work order advances from `AWAITING_RECALIBRATION` to `CURING`, and both the recalibration job's `version` and the work order's `version` increment by one. Alternatively a `Technician` fails the job, moving it from `SCHEDULED` to `FAILED` and incrementing its `version`; failing requires the job to be `SCHEDULED` and the work order to be `AWAITING_RECALIBRATION`. A failed job is not terminal: a `Technician` may retry it, moving it back from `FAILED` to `SCHEDULED` (requiring the job to be `FAILED` and the work order still in `AWAITING_RECALIBRATION`) and incrementing its `version`, so the job cycles through `SCHEDULED → FAILED → SCHEDULED` until it passes while the work order waits. A `ServiceAdvisor` may cancel a recalibration that is in either `SCHEDULED` or `FAILED`, moving it to `CANCELLED` and incrementing its `version`.

### 3.7. Payment, Completion, and Warranty

Money can be taken against a work order at any point in its life. A `Customer` (only for their own work order) or a `ServiceAdvisor` captures a payment by naming the `work_order_id`, the `amount_cents` (at least one), and the `method`, which is one of `CARD`, `CASH`, or `INSURANCE`. A captured payment begins in `CAPTURED` status. The system maintains the invariant that the work order's `amount_paid_cents` equals the sum of `amount_cents` over all `CAPTURED` payments for the work order minus the sum of all `refunded_amount_cents`, and it recomputes `amount_paid_cents` on every payment and refund. A payment whose `amount_cents` would push `amount_paid_cents` above `total_charge_cents` is an overpayment and is rejected with `ERR_OVERPAYMENT`. Payments can be fetched and listed under a work order.

The `ShopManager` may refund a `CAPTURED` payment. A refund computes a `refunded_amount_cents` for the payment, moves the payment from `CAPTURED` to `REFUNDED`, and recomputes the work order's `amount_paid_cents` to preserve the invariant above. A restocking fee applies only when the work order has reached `IN_SERVICE` or beyond — that is, its status is `IN_SERVICE`, `AWAITING_RECALIBRATION`, `CURING`, or `COMPLETED` — and the `service_decision` is `REPLACE`, because glass was opened from stock. In that case the restocking fee is 15 percent of the payment's `amount_cents`, rounded half-up to the nearest cent, and the `refunded_amount_cents` is the payment's `amount_cents` minus that fee. In every other case — the work order is still `OPEN`, `ASSESSED`, or `SCHEDULED`, or the `service_decision` is `REPAIR` — no restocking fee applies and the `refunded_amount_cents` is the full `amount_cents`. The payment's `refunded_amount_cents` is zero until it is refunded.

Completion finalizes the job. A `ServiceAdvisor` completes the work order, which issues a warranty and releases the appointment. A `REPLACE` job completes out of `CURING`: it requires the work order to be `CURING`, the server's current clock to be at or after the work order's `safe_drive_away_at` (the cure interval must have elapsed), and the work order to be fully paid. A `REPAIR` job, which never cures or recalibrates, completes directly out of `IN_SERVICE`: it requires the work order to be `IN_SERVICE`, the `service_decision` to be `REPAIR`, and the work order to be fully paid. In both paths "fully paid" means `amount_paid_cents` is at least `total_charge_cents`; an attempt to complete with an unpaid balance is rejected with `ERR_BALANCE_UNPAID` (HTTP 402). For a curing work order, an attempt to complete before `safe_drive_away_at` has elapsed is rejected with `ERR_CURE_NOT_ELAPSED`. Completion issues a `Warranty` whose `coverage_type` is `CHIP_REPAIR` for a `REPAIR` job and `LIFETIME_LEAK` for a `REPLACE` job, with `status` `ACTIVE` and `issued_at` set to the completion instant; it sets the linked appointment to `RELEASED`; and it increments the work order's `version` by one. A `Warranty` references its `work_order_id`, can be fetched and listed under a work order, and may be voided by the `ShopManager` while it is `ACTIVE`, moving it from `ACTIVE` to `VOID` and incrementing its `version`.

A work order may also be cancelled before service is performed. A `ServiceAdvisor` cancels a work order that is in `OPEN`, `ASSESSED`, or `SCHEDULED`, moving it to `CANCELLED`; later states require the refund path rather than cancellation. Cancellation cascades to the work order's open satellites: any `BOOKED` appointment for it is moved to `CANCELLED`, and any `RESERVED` part order for it is moved to `CANCELLED` with its stock released — the part's `on_hand_qty` is restored by the quantity and its `reserved_qty` is decremented by the quantity. The cancellation increments the work order's `version` by one.

### 3.8. The Test-Driving Clock

Because cure-elapsed checks at completion and the stamping of `safe_drive_away_at` both depend on wall-clock time, the system exposes an administrative capability that lets the `ShopManager` set the server's current UTC instant deterministically by supplying a `to_iso8601` value. Setting the clock fixes the instant used both for stamping `safe_drive_away_at` at install-finish and for evaluating whether the cure interval has elapsed at completion, so a test driver can advance time past a stamped safe-drive-away instant and then complete a curing work order. The `to_iso8601` value is required and must be a valid ISO 8601 datetime string; it is normalized to UTC. The call responds with HTTP 200 and a `data` object carrying a single field, `current_utc`, set to the newly pinned instant rendered as an ISO 8601 UTC timestamp with three fractional digits.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and computed reads — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | ServiceAdvisor, ShopManager |
| GET | `/customers/{id}` | Fetch a customer | ServiceAdvisor, ShopManager, Customer |
| GET | `/customers/{id}/vehicles` | List the customer's vehicles | ServiceAdvisor, ShopManager, Customer |
| GET | `/customers/{id}/work-orders` | List the customer's work orders | ServiceAdvisor, ShopManager, Customer |
| POST | `/vehicles` | Register a vehicle for a customer | ServiceAdvisor, ShopManager |
| GET | `/vehicles/{id}` | Fetch a vehicle | ServiceAdvisor, ShopManager, Customer |
| GET | `/vehicles/{id}/work-orders` | List work orders for a vehicle | ServiceAdvisor, ShopManager, Customer |
| POST | `/glass-parts` | Create a glass part SKU with initial stock | ShopManager |
| GET | `/glass-parts/{id}` | Fetch a glass part | ServiceAdvisor, ShopManager |
| GET | `/glass-parts` | List/lookup glass parts | ServiceAdvisor, ShopManager |
| PATCH | `/glass-parts/{id}/restock` | Add units to on-hand stock | ShopManager |
| POST | `/technicians` | Create a technician | ShopManager |
| GET | `/technicians/{id}` | Fetch a technician | ServiceAdvisor, ShopManager |
| POST | `/service-bays` | Create a service bay | ShopManager |
| GET | `/service-bays/{id}` | Fetch a service bay | ServiceAdvisor, ShopManager |
| POST | `/work-orders` | Open a work order for a customer and vehicle | ServiceAdvisor, Customer |
| GET | `/work-orders/{id}` | Fetch a work order | ServiceAdvisor, ShopManager, Customer, Technician |
| POST | `/work-orders/{id}/damage-assessments` | Record a chip/crack damage assessment | ServiceAdvisor |
| GET | `/work-orders/{id}/damage-assessments` | List assessments for a work order | ServiceAdvisor, ShopManager, Customer |
| POST | `/work-orders/{id}/accept-assessment` | Accept a draft assessment; freeze decision and quote | ServiceAdvisor |
| POST | `/work-orders/{id}/schedule` | Link a booked appointment; apply trip fee | ServiceAdvisor |
| POST | `/work-orders/{id}/start-service` | Begin work | Technician |
| POST | `/work-orders/{id}/finish-install` | Finish a replacement install; stamp safe-drive-away | Technician |
| POST | `/work-orders/{id}/complete` | Finalize the job; issue warranty, release appointment | ServiceAdvisor |
| POST | `/work-orders/{id}/cancel` | Cancel a pre-service work order; cascade to satellites | ServiceAdvisor |
| GET | `/work-orders/{id}/sdat-estimate` | Conservative posted safe-drive-away estimate | ServiceAdvisor, ShopManager, Customer, Technician |
| GET | `/work-orders/{id}/part-orders` | List part orders for a work order | ServiceAdvisor, ShopManager |
| GET | `/work-orders/{id}/payments` | List payments for a work order | ServiceAdvisor, ShopManager, Customer |
| GET | `/work-orders/{id}/appointments` | List appointments for a work order | ServiceAdvisor, ShopManager, Customer |
| GET | `/work-orders/{id}/recalibration-jobs` | List recalibration jobs for a work order | ServiceAdvisor, ShopManager, Technician |
| GET | `/work-orders/{id}/warranties` | List warranties for a work order | ServiceAdvisor, ShopManager, Customer |
| POST | `/part-orders` | Order/reserve a glass part for a replacement | ServiceAdvisor |
| GET | `/part-orders/{id}` | Fetch a part order | ServiceAdvisor, ShopManager |
| GET | `/part-orders` | List/filter part orders | ServiceAdvisor, ShopManager |
| POST | `/part-orders/{id}/receive` | Mark a backordered part received | ShopManager |
| POST | `/service-appointments` | Book a mobile or in-shop appointment | ServiceAdvisor |
| GET | `/service-appointments/{id}` | Fetch an appointment | ServiceAdvisor, ShopManager, Customer, Technician |
| GET | `/service-appointments` | List/filter appointments | ServiceAdvisor, ShopManager, Technician |
| POST | `/service-appointments/{id}/check-in` | Check the customer/vehicle in | Technician |
| POST | `/service-appointments/{id}/cancel` | Cancel a booked appointment | ServiceAdvisor |
| POST | `/recalibration-jobs` | Open an ADAS recalibration | Technician |
| GET | `/recalibration-jobs/{id}` | Fetch a recalibration job | ServiceAdvisor, ShopManager, Technician |
| GET | `/recalibration-jobs` | List/filter recalibration jobs | ServiceAdvisor, ShopManager, Technician |
| POST | `/recalibration-jobs/{id}/pass` | Mark recalibration passed; bubble the work order forward | Technician |
| POST | `/recalibration-jobs/{id}/fail` | Mark recalibration failed (retryable) | Technician |
| POST | `/recalibration-jobs/{id}/retry` | Reopen a failed recalibration | Technician |
| POST | `/recalibration-jobs/{id}/cancel` | Cancel a scheduled or failed recalibration | ServiceAdvisor |
| POST | `/payments` | Capture a payment against a work order | ServiceAdvisor, Customer |
| GET | `/payments/{id}` | Fetch a payment | ServiceAdvisor, ShopManager, Customer |
| POST | `/payments/{id}/refund` | Refund a captured payment; apply restock fee | ShopManager |
| GET | `/warranties/{id}` | Fetch a warranty | ServiceAdvisor, ShopManager, Customer |
| POST | `/warranties/{id}/void` | Void an active warranty | ShopManager |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC instant | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_ADAS_PART_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_MOBILE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_TECH_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_CURE_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_BAY_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_MOBILE_TECH_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_PART_NOT_READY` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_BALANCE_UNPAID` | 402 Payment Required |
| `ERR_DUPLICATE` | 409 Conflict |

# Seafood Wholesale & Dockside Purchase API — Product Requirements Document

## 1. Introduction

A regional seafood wholesaler earns its margin in two directions at once: it buys landings directly from fishing vessels at the dock, and it sells graded, traceable inventory on to wholesale buyers. This document specifies the API that runs that business end to end. It covers registering vessels, customers, catch areas, and species; recording dockside purchases against traceable catch areas; grading each landed line and converting yield-adjusted weight into saleable inventory; maintaining a daily market price board with a volatility guard; selling fresh and frozen lots under shelf-life clocks and customer credit limits; moving product through a chilled and frozen cold chain of truck and air freight; and enforcing the compliance overlay — import documentation, inspection holds, labeling rules, and segregation of duties — that regulators expect of a wholesale fish house.

Two commitments shape every workflow in this API. First, money and weight are never approximate: settlements, order totals, freight charges, and credit balances are all computed under pinned rounding rules so that two honest implementations produce identical cents and identical kilograms. Second, time is explicit: the system runs on a logical clock that drives quote expiry and shelf-life sweeps, so time-dependent behavior is deterministic rather than hostage to the wall clock. The remainder of this document defines the global contracts every endpoint honors, then walks each business workflow in narrative form, then closes with the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The declared roles are `OperationsManager`, `DockBuyer`, `VesselAgent`, `GradingInspector`, `InventoryPlanner`, `LogisticsCoordinator`, `ComplianceOfficer`, `Customer`, and `Any` — the last being a marker used in the endpoint catalogue to indicate that any authenticated role may perform read operations. A request whose role is valid but not permitted for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Two roles are entity-backed, and their identities carry ownership meaning. When `X-User-Role` is `VesselAgent`, `X-User-ID` is the `id` of the acting `Vessel`; ownership checks on any resource that references a vessel compare the resource's `vessel_id` foreign-key field to `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's `customer_id` foreign-key field to `X-User-ID`. Concretely, a `VesselAgent` may act only on dock tickets of its own vessel, and a `Customer` may act only on orders of its own account. The ownership guard covers six operations — creating a dock ticket, marking a ticket landed, creating a sales order, submitting an order, cancelling an order, and adding an order line — and a breach is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

For the remaining roles the identifier is opaque. When `X-User-Role` is `OperationsManager`, `DockBuyer`, `GradingInspector`, `InventoryPlanner`, `LogisticsCoordinator`, `ComplianceOfficer`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `created_by_user_id` on a market quote, `inspector_user_id` on a grade assessment, `submitted_by_user_id` on an import document, `placed_by_user_id` on an inspection hold, or `requested_by_user_id` on a substitution approval — but does not compare it to any entity's `id`.

Role responsibilities in brief. An `OperationsManager` runs the wholesale house: registers configuration entities, publishes and moderates quotes, settles and pays dock tickets, confirms and invoices orders, and drives the logical clock. A `DockBuyer` buys at the dock, creating tickets and landing lines and requesting re-grades. A `VesselAgent` represents a single vessel and may create and land only that vessel's dock tickets. A `GradingInspector` records and finalizes grade assessments, thereby creating inventory lots. An `InventoryPlanner` plans allocations, freezing, write-offs, and substitution requests and applications. A `LogisticsCoordinator` books and executes cold-chain shipments and air freight. A `ComplianceOfficer` is the regulatory gatekeeper for import documents, inspection holds, and substitution compliance, with segregation of duties applying to the submit/clear and place/release pairs. A `Customer` is a wholesale buyer acting on its own orders. Every declared role, including `Any`, may use all read endpoints.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, reading the logical clock of §2.6.
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
- Requests to paths this document does not declare, or carrying methods an endpoint does not support, are rejected with `ERR_INVALID_REQUEST` (400).

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it may not be lower than 1 or higher than 100. The `offset` parameter specifies the number of items to skip and defaults to 0, and it may not be negative. A non-integer or out-of-range value for either parameter is rejected with `ERR_INVALID_REQUEST` (400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp, `created_at`, in ascending order. Resources that share the same `created_at` — common under the frozen logical clock — are ordered among themselves by the order in which they were created, earliest created first.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in this API — Vessel, Customer, CatchArea, Species, MarketQuote, DockTicket, LandingLine, GradeAssessment, InventoryLot, SalesOrder, OrderLine, Allocation, Shipment, ImportDocument, InspectionHold, and SubstitutionApproval alike — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits refreshed upon any change to the resource's properties.
- **`version` (integer):** a system-managed integer that starts at 1 when the resource is created and increments by one with every modification to the resource.

"Modification" includes system-driven mutations, not just client-requested ones: when a cascade or sweep changes a resource, or when a cross-entity side effect bumps a parent's version (for example, adding a landing line advances the owning dock ticket's `version`), the affected resource's `updated_at` is refreshed and its `version` is incremented. This uniform bookkeeping is what makes the optimistic concurrency fields of §2.7 meaningful.

### 2.5. Cents, Kilograms, and Rounding Discipline

All monetary values are stored and returned as integer cents. Whenever a calculation produces a fractional cent, the value is rounded half up to whole cents at the step the workflow specifies; intermediate values never accumulate hidden precision beyond that step. Percentages, such as quote volatility, are rounded half up to two decimal places.

Weights are expressed in kilograms with exactly two decimal places, rounded half up. Quantities supplied by clients — landed weights, requested quantities, allocation quantities, booked weights — must be greater than zero.

Rounding order is pinned wherever a total aggregates per-line amounts: each line is rounded to whole cents first, and only then are the rounded line amounts summed. The alternative order — summing unrounded values and rounding once at the end — produces different cents and is forbidden.

### 2.6. The Logical Clock and Scheduled Sweeps

The server maintains a logical clock that governs every time-dependent rule in the system: remaining shelf life, quote expiry, and any reference to "now" or "the current date" anywhere in this document all read this clock. At startup, before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time.

An `OperationsManager` may set the logical clock through an admin-only capability that accepts a `to_iso8601` instant — any valid instant is accepted, with no requirement that it move the clock forward, and an instant supplied without an explicit offset is read as UTC; the response carries the submitted `to_iso8601` value echoed back as `current_utc`. Setting the clock fires two scheduled sweeps. First, every market quote in `PUBLISHED` status whose `quote_date` has passed transitions to `EXPIRED`. Second, every inventory lot in `ACTIVE` lifecycle whose expiry instant has been reached — the current logical time at or past the lot's `expires_at` — transitions to `EXPIRED`, firing the allocation-release and auto-substitution cascades described in §3.8.

### 2.7. Optimistic Concurrency Control on Shared Documents

Three write operations serialize their effect on a shared parent document through an expected-version field. Each field is a non-optional input carrying the client's last observed `version` of the parent; when the parent's current `version` no longer matches, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a state of the parent it has not observed.

- Adding a landing line to a dock ticket requires `expected_dock_ticket_version` matching the target dock ticket's current `version`. Because successfully adding a line itself advances the ticket's `version`, a second writer holding an older reading is rejected with `ERR_STALE_VERSION`.
- Publishing a market quote requires `expected_species_version` matching the quoted species' current `version`. Because publishing itself advances the species' `version`, a writer whose view of the species' quote series is stale is rejected with `ERR_STALE_VERSION`.
- Creating an allocation against a sales order requires `expected_sales_order_version` matching the order's current `version`. Because each successful allocation advances the order's `version`, a writer holding an older reading of the order's remaining quantities is rejected with `ERR_STALE_VERSION`.

Endpoints not named in this section do not take a version field of any kind.

### 2.8. Validation Precedence

Every request is validated in a fixed order, and the first failing check determines the error response. The ordering is part of the contract: a missing header surfaces before a permission failure, a stale version surfaces before an invalid-state failure, and a hold violation surfaces before a fiscal failure.

1. **Headers.** `X-User-ID` and `X-User-Role` are present and the role is a declared role, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Permission.** The role is permitted for the endpoint per the access matrix, else `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. **Ownership.** Entity-backed roles act only on their own resources, else `ERR_OWNERSHIP_MISMATCH` (403). The comparison needs the resource itself: when the guarded resource is named in the URL path and does not exist, the item-4 not-found error surfaces first, and a `Customer` adding an order line to a sales order that does not exist likewise draws `ERR_ORDER_NOT_FOUND` (404) rather than an ownership error.
4. **Shape and existence.** The request body is decoded first — required fields present, enum members in range, numeric bounds respected — else `ERR_INVALID_REQUEST` (400). Only then are identifiers resolved: identifiers appearing in the URL path are validated in left-to-right order, followed by foreign-key references in the request body (`species_id`, `vessel_id`, `catch_area_id`, `dock_ticket_id`, `landing_line_id`, `customer_id`, `sales_order_id`, `order_line_id`, `inventory_lot_id`, `substitute_species_id`). An unknown identifier yields the corresponding 404: `ERR_VESSEL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_CATCH_AREA_NOT_FOUND`, `ERR_SPECIES_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_IMPORT_DOC_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_SUBSTITUTION_NOT_FOUND`.
5. **Stale versions.** The optimistic-concurrency fields of §2.7 are verified, else `ERR_STALE_VERSION` (412).
6. **State.** The target resource is in a valid from-state for the requested transition, else the machine-specific state error: `ERR_TICKET_INVALID_STATE`, `ERR_QUOTE_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`, `ERR_LOT_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_ALLOCATION_INVALID_STATE`, `ERR_SHIPMENT_INVALID_STATE`, `ERR_IMPORT_DOC_INVALID_STATE`, `ERR_HOLD_INVALID_STATE`, or `ERR_SUBSTITUTION_INVALID_STATE` (all 409).
7. **Safety and compliance gates.** Hold blocks, segregation-of-duties pairs, labeling compliance, and import clearance are enforced, surfacing `ERR_LOT_ON_HOLD` (409), `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403), `ERR_LABELING_NONCOMPLIANT` (422), or `ERR_IMPORT_DOCS_NOT_CLEARED` (409). Two workflows pin their own finer order across this item and its neighbors, and those pins prevail: ticket settlement checks import clearance before the hold block (§3.5), and substitution approval applies the pinned sequence of §3.8 — group match, standing-quote resolution, and price ceiling (items 9 and 10) all before labeling compliance.
8. **Temporal rules.** Landing-window validity surfaces `ERR_INVALID_LANDING_WINDOW` (400), vessel landing-window overlap surfaces `ERR_VESSEL_LANDING_OVERLAP` (409), and the allocation shelf-life gate surfaces `ERR_SHELF_LIFE_INSUFFICIENT` (422).
9. **Constraint rules.** Flight capacity (`ERR_FLIGHT_CAPACITY_EXCEEDED`, 409), lot quantity (`ERR_INSUFFICIENT_LOT_QUANTITY`, 409), line over-allocation (`ERR_LINE_OVER_ALLOCATION`, 409), species matching (`ERR_SPECIES_MISMATCH`, 422), one active assessment per line (`ERR_ASSESSMENT_ALREADY_ACTIVE`, 409), one active hold per lot (`ERR_HOLD_ALREADY_ACTIVE`, 409), the re-grade cap (`ERR_REGRADE_LIMIT_EXCEEDED`, 409), uniqueness of registered codes (`ERR_DUPLICATE_UNIQUE_VALUE`, 409), yield bounds (`ERR_INVALID_YIELD`, 400), substitution group matching (`ERR_SUBSTITUTION_GROUP_MISMATCH`, 422), the substitution-permission flag (`ERR_SUBSTITUTION_NOT_ALLOWED`, 422), and the non-empty-order rule (`ERR_ORDER_EMPTY`, 422).
10. **Fiscal rules.** Quote resolution for pricing and settlement (`ERR_QUOTE_NOT_PUBLISHED`, 422), the customer credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`, 402), and the substitution price ceiling (`ERR_SUBSTITUTION_PRICE_INCREASE`, 422).

### 2.9. Lot Bookkeeping: Two Status Dimensions and Seven Weight Buckets

An inventory lot is tracked along two parallel status dimensions. The first, `lifecycle_status`, runs from `ACTIVE` to the terminal values `DEPLETED`, `EXPIRED`, and `RECALLED`. The second, `hold_status`, runs from `CLEAR` to `ON_HOLD` and on to either `CLEAR` again or the terminal `CONDEMNED`. A lot is born `ACTIVE` and `CLEAR`, and the two dimensions move independently except where a workflow in §3 ties them together.

Weight on a lot is accounted in seven buckets, each carrying two decimal places of kilograms. `received_weight_kg` records what entered inventory at creation. `available_weight_kg` is unreserved sellable weight. `reserved_weight_kg` is weight held by reservations not yet committed. `committed_weight_kg` is weight committed to orders but not yet shipped. `shipped_weight_kg` is weight actually delivered by shipments. `condemned_weight_kg` is weight condemned by inspection. `spoiled_weight_kg` is weight written off or lost to expiry. `recalled_weight_kg` is weight recalled by a ticket void or re-grade. Every workflow that moves weight names its source and destination buckets; reservations move weight from available to reserved, commits from reserved to committed, deliveries from committed to shipped, write-offs from available to spoiled, condemnations from available, reserved, and committed into condemned, and recalls from available, reserved, and committed into recalled.

A lot's `unit_cost_cents` is fixed at creation as its source line's final amount divided by the received weight, rounded half up to whole cents; when the received weight is zero, the unit cost is zero. The `DEPLETED` lifecycle test is automatic: after a delivery, a write-off, or a condemnation, when available, reserved, and committed weight have all reached zero and the received weight is greater than zero, the lot transitions to `DEPLETED`.

### 2.10. Segregation of Duties at Compliance Gates

Three approval gates split responsibility between two different operators, and the same user may not stand on both sides of any of them. A market quote routed through the volatility guard must be approved by an `OperationsManager` other than the user who created the quote, as recorded in its `created_by_user_id`. An import document must be cleared by a `ComplianceOfficer` other than the user who submitted it, as recorded in its `submitted_by_user_id`. An inspection hold must be released by a `ComplianceOfficer` other than the user who placed it, as recorded in its `placed_by_user_id`. In all three cases, a same-user attempt is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). The deciding officer's identity is recorded on the resource — the clearing officer as `reviewed_by_user_id` on the document, the releasing officer as `resolved_by_user_id` on the hold — so the audit trail always names both sides of the gate.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Trading Network: Vessels, Customers, Catch Areas, and Species

Before any fish changes hands, an `OperationsManager` provisions the trading network. A **Vessel** is registered with a `vessel_name`, a `registration_number`, and a `home_port`; the registration number is unique across vessels, and a duplicate is rejected with `ERR_DUPLICATE_UNIQUE_VALUE` (409). A new vessel's `payable_balance_cents` starts at zero — it is the running ledger of what the house owes the vessel, credited at settlement, debited at payment, and reversed on a void.

A **Customer** is a wholesale buyer registered with a `business_name`, a `credit_limit_cents` capping its permitted exposure, and an optional `discount_pct`, a fractional line discount such that 0.10 means ten percent, applied per line before rounding and defaulting to zero. A new customer's `credit_exposure_cents` starts at zero; §3.6 defines how it moves.

A **CatchArea** anchors traceability with a `fao_code` (the FAO major fishing area code, unique, duplicates rejected with `ERR_DUPLICATE_UNIQUE_VALUE`), a `name`, and a `region` description. A **Species** is registered with a unique `species_code` (same duplicate rule), a `common_name`, the legally required market `labeling_name`, a `substitution_group` key that governs which species may stand in for one another, the per-species shelf-life parameters `fresh_shelf_life_hours` and `frozen_shelf_life_days`, and two compliance flags: `is_import`, true when the species requires import documentation before settlement, and `requires_cites`, true when CITES documentation is required to use the species as a substitute; both flags default to false. Everywhere this API speaks of fish quality it uses the grade enumeration `GRADE_A`, `GRADE_B`, and `GRADE_C`.

### 3.2. The Daily Price Board: Quotes, Volatility, and Publication

An `OperationsManager` authors each day's price board as **MarketQuote** records, each carrying the quoted `species_id`, a `grade`, the `quote_date` calendar date in YYYY-MM-DD form it applies to, and a `price_per_kg_cents` that must be greater than zero. A new quote starts in `DRAFT`, and the system records its author in `created_by_user_id` for the segregation-of-duties gate described below.

Publishing is where the guard lives. When an `OperationsManager` publishes a quote that is no longer in `DRAFT`, the request is rejected with `ERR_QUOTE_INVALID_STATE` (409). Otherwise the publish request must carry `expected_species_version` per §2.7, with a stale reading rejected as `ERR_STALE_VERSION` (412). The volatility guard then compares the new price against the prior `PUBLISHED` quote for the same species and grade — the one with the greatest `quote_date`, ties broken by the latest `created_at`. The percentage change is the absolute difference between the new and prior prices, divided by the prior price, expressed as a percentage and rounded half up to two decimal places; the result is stored on the quote as `volatility_pct`. When no prior published quote exists for the species and grade, the guard is inert: the quote publishes directly and `volatility_pct` remains zero. A change below 10.00 percent publishes outright, transitioning the quote to `PUBLISHED`. A change of at least 10.00 percent — exactly 10.00 included — routes the quote to `PENDING_APPROVAL` instead; this routing is not an error. Either way, the publish action increments the species' `version` by one.

A quote parked in `PENDING_APPROVAL` resolves in one of two directions, both by an `OperationsManager`. Volatility approval moves it to `PUBLISHED`, but only when the approving user's `X-User-ID` differs from the quote's `created_by_user_id`; a same-user approval is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403), and acting on a quote that is not in `PENDING_APPROVAL` draws `ERR_QUOTE_INVALID_STATE`. Volatility rejection returns the quote to `DRAFT`. Whenever a quote reaches `PUBLISHED`, the prior `PUBLISHED` quote for the same species and grade is automatically superseded to `SUPERSEDED`. Publication is therefore a series: at most one quote per species and grade stands published at a time, and superseded quotes remain on record for historical pricing. `SUPERSEDED` and `EXPIRED` are terminal; expiry itself is a clock-driven transition from `PUBLISHED` described in §2.6.

Three workflows consult the price board, and they do so through two distinct selectors. The **standing price** selector — used by order confirmation, substitution repricing, and the substitute finder — picks the quote for a species and grade whose status is `PUBLISHED` and whose `quote_date` is on or before the current logical date, taking the greatest `quote_date` and breaking ties by the latest `created_at`; the quote's `id` is never used for selection. An empty candidate set surfaces `ERR_QUOTE_NOT_PUBLISHED` (422) at the point of use. The **settlement price** selector — used for provisional and final settlement of landing lines — is deliberately historical: it matches the species, the applicable grade, and a `quote_date` equal to the calendar date of the ticket's landing start, and it accepts quotes in `PUBLISHED`, `SUPERSEDED`, or `EXPIRED` status, because any quote that once reached publication remains valid pricing for landings that occurred on its date. When several match, the greatest `quote_date` wins, ties broken by the latest `created_at`; when none exists, settlement is rejected with `ERR_QUOTE_NOT_PUBLISHED`.

### 3.3. Buying at the Dock: Tickets, Landing Windows, and Landing Lines

A dockside purchase begins as a **DockTicket**, created by a `DockBuyer` or by a `VesselAgent` acting for the landing vessel, with the landing `vessel_id`, the `catch_area_id` for traceability, and a landing window bounded by `landing_start_at` and `landing_end_at`, both ISO 8601 UTC instants (an instant supplied without an explicit offset is read as UTC). The end of the window must be strictly after its start, else `ERR_INVALID_LANDING_WINDOW` (400). One vessel cannot be in two places at once: the new window must not overlap the window of any other non-`VOIDED` ticket of the same vessel, where overlap is judged on half-open intervals — the start inclusive, the end exclusive — so that a window beginning exactly when another ends is adjacency, not overlap. A genuine overlap is rejected with `ERR_VESSEL_LANDING_OVERLAP` (409). A new ticket starts in `DRAFT` with `regrade_count` at zero and both `provisional_total_cents` and `final_total_cents` at zero.

When the vessel comes alongside, the `DockBuyer` or the vessel's `VesselAgent` marks the ticket landed, transitioning it from `DRAFT` to `LANDED`; a ticket in any other state is rejected with `ERR_TICKET_INVALID_STATE` (409), and the transition increments the ticket's `version` by one.

Only a `LANDED` ticket accepts landing lines. A `DockBuyer` adds each **LandingLine** with its owning `dock_ticket_id`, the landed `species_id`, the `declared_grade` as declared at landing (`GRADE_A`, `GRADE_B`, or `GRADE_C`), the `landed_weight_kg` at two decimal places and greater than zero, and an optional `processing_type` of `WHOLE` or `FILLETED` that defaults to `WHOLE`. The request must also carry `expected_dock_ticket_version` per §2.7; adding a line recomputes the ticket's provisional total and increments the ticket's `version` by one, so a stale reading is rejected with `ERR_STALE_VERSION` (412). A ticket that is not `LANDED` rejects the line with `ERR_TICKET_INVALID_STATE`.

Each new line is provisionally settled on the spot. The settlement price selector of §3.2 resolves the quote for the line's species and `declared_grade` dated on the landing day — with `ERR_QUOTE_NOT_PUBLISHED` (422) when no qualifying quote exists — and the line's `provisional_amount_cents` is its `landed_weight_kg` multiplied by the quote's `price_per_kg_cents`, rounded half up to whole cents. The ticket's `provisional_total_cents` is the sum of `provisional_amount_cents` over its non-voided lines, recomputed as lines are added or voided. A landing line also carries `processed_weight_kg` and `final_amount_cents`, both zero until grading finalizes them, and a `voided` flag, false until the owning ticket is voided.

### 3.4. Grading and Yield: From Assessment to Inventory Lot

Grading turns declared landings into valued inventory. A `GradingInspector` records a **GradeAssessment** against a landing line of a `LANDED` ticket — a line whose owning ticket is in any other state is rejected with `ERR_TICKET_INVALID_STATE` (409) — supplying the `landing_line_id`, the `assessed_grade`, a `yield_pct` processing yield fraction, and optional free-text `notes` that default to empty. The yield fraction must be greater than zero and no more than one; anything outside that range is rejected with `ERR_INVALID_YIELD` (400). Each line supports only one active assessment: if a `DRAFT` or `FINAL` assessment already exists for the line, the new record is rejected with `ERR_ASSESSMENT_ALREADY_ACTIVE` (409). A new assessment starts in `DRAFT`, and the recording inspector's `X-User-ID` is stored as `inspector_user_id`.

Finalization is the value-creation step, performed by a `GradingInspector`. It requires the assessment to be in `DRAFT` — else `ERR_ASSESSMENT_INVALID_STATE` (409) — and the owning ticket to be in `LANDED` — else `ERR_TICKET_INVALID_STATE`. On finalize, the line's `processed_weight_kg` is computed as the smaller of the raw `landed_weight_kg` and the product of `landed_weight_kg` multiplied by the assessment's `yield_pct`, by a condition factor, and by a processing factor, the result rounded half up to two decimal places. The condition factor is 1.00 for an assessed `GRADE_A`, 0.97 for `GRADE_B`, and 0.92 for `GRADE_C`; the processing factor is 1.00 when the line's `processing_type` is `WHOLE` and 0.85 when it is `FILLETED`. The line's `final_amount_cents` is then settled on the assessed grade: the settlement price selector resolves the quote for the line's species and the `assessed_grade` dated on the landing day — `ERR_QUOTE_NOT_PUBLISHED` when none exists — and the final amount is the `processed_weight_kg` multiplied by that quote's `price_per_kg_cents`, rounded half up to whole cents. Because the final variant prices the assessed grade against the yield-adjusted weight while the provisional variant priced the declared grade against the raw landed weight, an unchanged landing can still settle for a different amount.

Finalization also births an **InventoryLot**. The lot traces back to its `landing_line_id`, denormalizes the line's `species_id`, copies the ticket's `landing_start_at` into `landed_at`, and starts with `storage_type` `FRESH` and `frozen_at` unset. Its `received_weight_kg` is the line's `processed_weight_kg`, its `available_weight_kg` equals the received weight, and every other weight bucket starts at zero; its `unit_cost_cents` is derived per §2.9. Being fresh, its shelf-life clock starts immediately: `expires_at` is the `landed_at` instant plus the species' `fresh_shelf_life_hours`, at hour granularity. Back on the ticket, `final_total_cents` — the sum of `final_amount_cents` over lines with a `FINAL` assessment — is recomputed, and when every non-voided line of a ticket holding at least one line has reached a `FINAL` assessment, the ticket itself transitions automatically from `LANDED` to `GRADED`.

Grading is not one-way. A `DockBuyer` or `OperationsManager` may request a re-grade of a `GRADED` ticket — a ticket in any other state draws `ERR_TICKET_INVALID_STATE` — returning it to `LANDED` for a fresh round of assessments. The privilege is capped: when the ticket's `regrade_count` has already reached two, the request is rejected with `ERR_REGRADE_LIMIT_EXCEEDED` (409); otherwise the count increments by one. The cascade is wide. Every `FINAL` assessment of the ticket's lines transitions to `SUPERSEDED` — since superseded assessments no longer count as active, each line may then receive a new assessment. Every inventory lot derived from the ticket's lines that is still in `ACTIVE` lifecycle transitions to `RECALLED`, with its remaining available, reserved, and committed weight moving into `recalled_weight_kg`; lots already in a terminal lifecycle (`DEPLETED`, `EXPIRED`, or `RECALLED`) are left untouched. Each `RESERVED` or `COMMITTED` allocation sitting on those recalled lots is released, and the affected order lines recompute their allocated and committed quantities while the affected orders re-evaluate the fulfillment regression of §3.6.

### 3.5. Settlement, Import Clearance, and Payment to the Vessel

Settlement is the house's promise to pay, and regulators get their say first. Imported species require **ImportDocument** records, created by a `ComplianceOfficer` with the `dock_ticket_id` and `species_id` the document covers, a `doc_type` of `HEALTH_CERT`, `CITES`, or `CUSTOMS_ENTRY`, and an external `reference_number`. A new document starts in `DRAFT` with `submitted_by_user_id` and `reviewed_by_user_id` empty and `resubmit_count` at zero. Submission by a `ComplianceOfficer` moves a document from `DRAFT` to `SUBMITTED`, stamping `submitted_by_user_id` with the submitter's `X-User-ID`; a document in any state other than `DRAFT` or `REJECTED` rejects submission with `ERR_IMPORT_DOC_INVALID_STATE` (409). A `REJECTED` document may be resubmitted through the same action, returning to `SUBMITTED` with `resubmit_count` incremented by one and the new submitter stamped. Clearance moves a `SUBMITTED` document to `CLEARED` and stamps the clearing officer as `reviewed_by_user_id`, but the clearing officer must differ from the submitter — a same-user clearance is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403), and a document not in `SUBMITTED` draws `ERR_IMPORT_DOC_INVALID_STATE`. Rejection moves a `SUBMITTED` document to `REJECTED`, from which the resubmission cycle may begin again. `CLEARED` is terminal.

With grading complete, an `OperationsManager` settles a `GRADED` ticket — any other state draws `ERR_TICKET_INVALID_STATE`. Two compliance gates stand in front of settlement. First, for every line whose species is flagged `is_import`, the required documents for that ticket and species must all be `CLEARED`: a health certificate always, and a CITES document additionally when the species is flagged `requires_cites`; missing clearances reject the settlement with `ERR_IMPORT_DOCS_NOT_CLEARED` (409). Second, no inventory lot derived from the ticket may be sitting `ON_HOLD`; such a lot rejects the settlement with `ERR_LOT_ON_HOLD` (409). A successful settlement moves the ticket to `SETTLED` and credits the vessel: the ticket's `final_total_cents` is added to the vessel's `payable_balance_cents`.

Payment is the mirror of settlement. An `OperationsManager` pays a `SETTLED` ticket — any other state draws `ERR_TICKET_INVALID_STATE` — moving it to the terminal `PAID` state and subtracting the ticket's `final_total_cents` from the vessel's `payable_balance_cents`.

A ticket may also be voided by an `OperationsManager` from any of `DRAFT`, `LANDED`, `GRADED`, or `SETTLED` — from `PAID` or an already-`VOIDED` ticket the request draws `ERR_TICKET_INVALID_STATE` — landing it in the terminal `VOIDED` state. Voiding unwinds everything the ticket created. Every landing line's `voided` flag is set to true, removing the line from the provisional-total sum. Every inventory lot derived from the ticket's lines that is still in `ACTIVE` lifecycle transitions to `RECALLED`, its remaining available, reserved, and committed weight moving into `recalled_weight_kg`; lots already in a terminal lifecycle are left untouched. Each `RESERVED` or `COMMITTED` allocation on the recalled lots is released, the affected order lines recompute their allocated and committed quantities, and the affected orders re-evaluate the fulfillment regression. And when the voided ticket had been `SETTLED`, the vessel's ledger is unwound too: the ticket's `final_total_cents` is subtracted from `payable_balance_cents`, the exact reversal of the settlement credit.

### 3.6. Selling to Wholesale Buyers: Orders, Pricing, and Credit

On the sales side, a `Customer` or an `OperationsManager` creates a **SalesOrder** with the ordering `customer_id` and a `required_delivery_date` in YYYY-MM-DD form; a `Customer` creating an order must be creating it for its own account per §2.1. The order starts in `DRAFT` with `total_cents` at zero and `confirmed_at` unset. Lines are added while the order is in `DRAFT` — an order in any other state rejects the addition with `ERR_ORDER_INVALID_STATE` (409) — by the owning `Customer` or an `OperationsManager`. Each **OrderLine** carries its owning `sales_order_id`, the requested `species_id`, a `requested_grade`, the `requested_qty_kg` at two decimal places and greater than zero, an optional `min_remaining_shelf_life_hours` floor that defaults to zero and must be non-negative, else `ERR_INVALID_REQUEST` (400), and an `allow_substitution` flag, defaulting to false, that licenses species substitution on the line. Before confirmation, a line's `unit_price_cents` and `line_total_cents` read zero, and its `allocated_qty_kg` and `committed_qty_kg` track reservations and commitments, both starting at zero.

Submission is the buyer's own act: only the owning `Customer` may submit, moving a `DRAFT` order to `SUBMITTED`. An order in any other state draws `ERR_ORDER_INVALID_STATE`, a non-owner draws `ERR_OWNERSHIP_MISMATCH` (403), and an order with no lines at all draws `ERR_ORDER_EMPTY` (422).

Confirmation is where pricing hardens, performed by an `OperationsManager` on a `SUBMITTED` order. Every line must resolve a standing price through the selector of §3.2 for its species and requested grade as of the confirmation date; any unresolvable line rejects the confirmation with `ERR_QUOTE_NOT_PUBLISHED` (422). Lines are priced in their creation order, earliest `created_at` first: each line locks its `unit_price_cents` from the selected quote, and its `line_total_cents` is the `requested_qty_kg` multiplied by the locked unit price, multiplied by one minus the customer's `discount_pct`, rounded half up to whole cents. The order's `total_cents` is the sum of the already-rounded line totals — the pinned rounding order of §2.5 forbids summing unrounded values. The credit gate then applies: the customer's current `credit_exposure_cents` plus the candidate order's `total_cents` must not exceed the customer's `credit_limit_cents`, and landing exactly on the limit is permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (402). A successful confirmation stamps `confirmed_at` with the current time, moves the order to `CONFIRMED`, and recomputes the customer's exposure.

A customer's `credit_exposure_cents` is the sum of `total_cents` over that customer's orders in `CONFIRMED`, `FULFILLED`, or `INVOICED` status; orders in `DRAFT`, `SUBMITTED`, or `CANCELLED` are excluded. Exposure is recomputed at confirmation, at cancellation, and at substitution application, so the figure always reflects the live book.

Fulfillment is automatic and reversible. When every line's `committed_qty_kg` reaches at least its `requested_qty_kg`, the order transitions from `CONFIRMED` to `FULFILLED` on its own. Conversely, whenever a release, condemnation, expiry, void, or re-grade cascade pushes any line's `committed_qty_kg` back below its `requested_qty_kg`, a `FULFILLED` order regresses to `CONFIRMED` — this regression is the system's way of keeping the order's promise honest as inventory evaporates. An `OperationsManager` may invoice a `FULFILLED` order — any other state draws `ERR_ORDER_INVALID_STATE` — moving it to the terminal `INVOICED` state; invoicing deliberately leaves the exposure figure untouched, because `INVOICED` remains in the exposure set.

Cancellation releases everything. The owning `Customer` or an `OperationsManager` may cancel an order from `DRAFT`, `SUBMITTED`, or `CONFIRMED` — from `FULFILLED`, `INVOICED`, or an already-`CANCELLED` order the request draws `ERR_ORDER_INVALID_STATE` — moving it to the terminal `CANCELLED` state. From `DRAFT` or `SUBMITTED` no allocations can yet encumber the order, so the transition is clean apart from the exposure recomputation. From `CONFIRMED`, every `RESERVED` or `COMMITTED` allocation of the order's lines is released, with the weight on each lot restored from the reserved or committed bucket back to available, and the exposure recomputation removes the order from the customer's exposure set.

### 3.7. Reservations, Shelf Life, and the Cold Chain

An `InventoryPlanner` puts stock behind an order by creating an **Allocation**, naming the `order_line_id`, the source `inventory_lot_id`, the `qty_kg` at two decimal places and greater than zero, and the planned `transit_hours` — a non-negative integer, else `ERR_INVALID_REQUEST` (400) — the product will spend in transit. The request must carry `expected_sales_order_version` per §2.7, with a stale reading rejected as `ERR_STALE_VERSION` (412). Business gates then apply in the §2.8 precedence order. First the state gates: the lot's lifecycle must be `ACTIVE`, else `ERR_LOT_INVALID_STATE` (409), and the order must be in `CONFIRMED`, else `ERR_ORDER_INVALID_STATE` (409). Then the hold gate: the lot must not be `ON_HOLD`, else `ERR_LOT_ON_HOLD` (409). Then the shelf-life gate: the hours between now and the lot's `expires_at` must be at least the sum of the line's `min_remaining_shelf_life_hours` and the allocation's `transit_hours`, with exact equality sufficient — otherwise `ERR_SHELF_LIFE_INSUFFICIENT` (422). Finally the constraint rules, in §2.8 item-9 order: the lot's `available_weight_kg` must be at least the requested quantity, else `ERR_INSUFFICIENT_LOT_QUANTITY` (409); the line's remaining quantity — its `requested_qty_kg` less its current `allocated_qty_kg` — must be at least the requested quantity, else `ERR_LINE_OVER_ALLOCATION` (409); and the lot's species must equal the line's species, else `ERR_SPECIES_MISMATCH` (422). A successful allocation starts in `RESERVED`, moves its quantity from the lot's available bucket to its reserved bucket, recomputes the line's `allocated_qty_kg` as the sum of quantities over its `RESERVED` and `COMMITTED` allocations, and increments the order's `version` by one.

Commitment firms a reservation into a promise. An `InventoryPlanner` commits a `RESERVED` allocation — any other state draws `ERR_ALLOCATION_INVALID_STATE` (409) — provided the lot's lifecycle is `ACTIVE` and its hold is `CLEAR` (surfacing `ERR_LOT_INVALID_STATE` or `ERR_LOT_ON_HOLD` respectively) and the order is in `CONFIRMED` (else `ERR_ORDER_INVALID_STATE`). The quantity moves from the lot's reserved bucket to its committed bucket, the line's `committed_qty_kg` — the sum over its `COMMITTED` allocations — is recomputed, and when every line of the order is fully committed the order fulfills automatically per §3.6. Releasing works in the other direction: an `InventoryPlanner` may release a `RESERVED` allocation, moving the weight from reserved back to available and recomputing the line's `allocated_qty_kg`. A direct release of a `COMMITTED` allocation is rejected with `ERR_ALLOCATION_INVALID_STATE`; committed weight is released only by the system cascades — condemnation, void, re-grade, and order cancellation — which return the weight to available unless the cascade itself directs it to the condemned or recalled bucket, and which re-evaluate the fulfillment regression after recomputing the line's quantities. `RELEASED` is terminal for an allocation.

Between reservation and shipment, the planner manages the shelf-life clock. Freezing a lot — again an `InventoryPlanner` act — requires the lot's lifecycle to be `ACTIVE` and its `storage_type` to be `FRESH`, anything else drawing `ERR_LOT_INVALID_STATE` (409), and is blocked while the lot is `ON_HOLD` with `ERR_LOT_ON_HOLD`; it converts `storage_type` from `FRESH` to `FROZEN`, stamps `frozen_at` with the current time, and resets the clock: `expires_at` becomes the `frozen_at` instant plus the species' `frozen_shelf_life_days`, at day granularity, so a lot frozen for N days expires exactly N days after freezing. Writing off spoilage moves a supplied `qty_kg` — required to be greater than zero, else `ERR_INVALID_REQUEST` (400) — from the available bucket into `spoiled_weight_kg`, with an optional `reason`; the lot's lifecycle must be `ACTIVE`, else `ERR_LOT_INVALID_STATE` (409), an `ON_HOLD` lot blocks write-offs with `ERR_LOT_ON_HOLD`, a write-off exceeding the available weight is rejected with `ERR_INSUFFICIENT_LOT_QUANTITY`, and a write-off that drains available, reserved, and committed to zero triggers the `DEPLETED` evaluation of §2.9.

The cold chain itself is run by a `LogisticsCoordinator`. A **Shipment** is created for a `CONFIRMED` or `FULFILLED` order — orders in any other state reject creation with `ERR_ORDER_INVALID_STATE` — naming the `sales_order_id`, a `mode` of `AIR` or `TRUCK`, the `temp_zone` cold-chain requirement of `CHILLED` or `FROZEN`, and a `booked_weight_kg` at two decimal places and greater than zero. Air freight additionally requires a `flight_number` and a `flight_date` in YYYY-MM-DD form; both default to empty and their absence on an air shipment is a request-shape failure, `ERR_INVALID_REQUEST` (400). On either mode, a `flight_date` that is supplied must be a valid YYYY-MM-DD date, else `ERR_INVALID_REQUEST` (400). A new shipment starts in `QUOTED` with `actual_weight_kg`, `volume_m3`, `chargeable_weight_kg`, `provisional_freight_cents`, and `final_freight_cents` all at zero.

Booking a `QUOTED` shipment — any other state draws `ERR_SHIPMENT_INVALID_STATE` (409) — reserves its space and prices it provisionally. For air freight, capacity is pooled per flight: the sum of `booked_weight_kg` over all shipments in `BOOKED`, `TENDERED`, or `IN_TRANSIT` sharing the same `flight_number` and `flight_date`, plus this booking's weight, must not exceed 1000 kilograms, else `ERR_FLIGHT_CAPACITY_EXCEEDED` (409). At booking, `chargeable_weight_kg` is set to the `booked_weight_kg` — the dimensional term is zero at this stage — and `provisional_freight_cents` is computed from it under the tariff below. Tendering a `BOOKED` shipment records the tendered `actual_weight_kg` — which must be greater than zero — and `volume_m3` — which must be non-negative — with violations rejected as `ERR_INVALID_REQUEST` (400), and reprices finally: `chargeable_weight_kg` becomes the greater of the actual weight and the dimensional weight, where the dimensional weight is the volume in cubic meters multiplied by 167 and rounded half up to two decimal places, and `final_freight_cents` overwrites the estimate. Because the provisional variant prices the booked mass while the final variant prices the greater of actual and dimensional weight, identical mass can price differently once volume is known.

The freight tariff's evaluation order is pinned, and both variants follow it. First the chargeable weight is fixed as above. Second, the subtotal is the mode's base charge plus the chargeable weight multiplied by the mode's per-kilogram rate, that product rounded half up to whole cents before being added: air freight carries a base of 5000 cents and a rate of 320 cents per kilogram, truck freight a base of 2500 cents and 140 cents per kilogram. Third, the discount test is keyed on the pre-discount subtotal: when that subtotal is at least 10000 cents, a five percent discount applies, and the tier still counts even when applying the discount would pull the result below the threshold; the discounted amount is the subtotal reduced by five percent, rounded half up to whole cents. Fourth, the fuel surcharge is twelve percent of the discounted amount — keyed on the discounted figure, not the original subtotal — rounded half up to whole cents. Fifth and last, the freight charge is the greater of 4000 cents and the sum of the discounted amount and the fuel surcharge: the minimum charge binds exactly there.

From `TENDERED`, departure moves the shipment to `IN_TRANSIT`. Delivery moves an `IN_TRANSIT` shipment to the terminal `DELIVERED` state and settles the physical flow: for every `COMMITTED` allocation on the shipment's order lines, the quantity moves from the lot's committed bucket into `shipped_weight_kg`, and lots whose available, reserved, and committed buckets all reach zero transition to `DEPLETED`. Cancellation by a `LogisticsCoordinator` is permitted from `QUOTED` or `BOOKED` — from any later state it draws `ERR_SHIPMENT_INVALID_STATE` — moves the shipment to the terminal `CANCELLED` state, and frees its claim on flight capacity.

### 3.8. Holds, Condemnation, Recalls, and Species Substitution

A `ComplianceOfficer` may place an **InspectionHold** on a lot whose lifecycle is `ACTIVE` and whose hold dimension is `CLEAR` — anything else draws `ERR_LOT_INVALID_STATE` (409) — and only when no other `PLACED` hold exists on that lot, else `ERR_HOLD_ALREADY_ACTIVE` (409). These two gates fire in the §2.8 order — the from-state check (priority 6) before the one-active-hold constraint (priority 9) — and because a lot carrying a `PLACED` hold always reads `ON_HOLD`, a second hold attempt on such a lot surfaces `ERR_LOT_INVALID_STATE` (409). The request names the `inventory_lot_id` and a `reason`; the hold starts in `PLACED`, stamps `placed_by_user_id` with the officer's `X-User-ID` and `placed_at` with the current time, leaves `resolved_by_user_id` empty and `resolved_at` unset, and flips the lot's `hold_status` to `ON_HOLD`. A lot on hold is quarantined: allocation, commitment, freezing, and write-off against it are all blocked with `ERR_LOT_ON_HOLD`, and settlement of any ticket with a derived lot on hold is likewise blocked.

Resolution comes in two forms, both by a `ComplianceOfficer` acting on a `PLACED` hold — anything else draws `ERR_HOLD_INVALID_STATE` (409). Release returns the lot's `hold_status` to `CLEAR` and stamps the releasing officer as `resolved_by_user_id` with `resolved_at` set, but the releasing officer must differ from the officer who placed the hold; a same-user release is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403). Condemnation is the heavy hammer. The hold transitions to the terminal `CONDEMNED` state, the lot's `hold_status` becomes `CONDEMNED`, and its available, reserved, and committed weight all move into `condemned_weight_kg`. Every `RESERVED` or `COMMITTED` allocation on the lot is released, the affected order lines recompute their allocated and committed quantities, and any affected order in `FULFILLED` whose lines are no longer fully committed regresses to `CONFIRMED`. Then the substitution cascade runs: for each order line left short whose `allow_substitution` flag is true, the system auto-creates a substitution request through the substitute selector below. Finally, the `DEPLETED` evaluation of §2.9 runs against the lot.

The expiry sweep of §2.6 condemns by time rather than by inspection, and its cascade differs in one deliberate way: when an `ACTIVE` lot reaches its `expires_at`, its lifecycle transitions to `EXPIRED`, its available and reserved weight move into `spoiled_weight_kg`, but committed weight stays put until its order resolves. Each `RESERVED` allocation on the lot is released, order lines recompute, orders regress as above, and the same auto-substitution cascade fires for shorted lines that permit substitution.

The **substitute selector** that both cascades share works as follows. Candidate species must differ from the line's current species, share its `substitution_group` key, have at least one inventory lot with lifecycle `ACTIVE` and hold `CLEAR`, and have a standing `PUBLISHED` quote for the line's `requested_grade` dated on or before the current logical date. Candidates are ranked by the selected quote's price, cheapest substitute first, with ties broken by the species' `created_at`, earliest first — never by `id`. When no candidate qualifies, no substitution record is created and the cascade continues silently. An auto-created **SubstitutionApproval** starts in `REQUESTED` with `auto_created` set to true, `requested_by_user_id` and `decided_by_user_id` left empty, `price_credit_cents` at zero, `original_species_id` captured from the shorted line, and `order_line_id` pointing at that line.

Substitution may also be requested manually: an `InventoryPlanner` requests one with the `order_line_id` and the proposed `substitute_species_id`, provided the line's `allow_substitution` flag is true — a line without that permission rejects the request with `ERR_SUBSTITUTION_NOT_ALLOWED` (422). The record starts in `REQUESTED`, captures the line's current species as `original_species_id`, stamps the requester as `requested_by_user_id`, sets `auto_created` to false, and starts with `price_credit_cents` at zero and `decided_by_user_id` empty.

Decision belongs to a `ComplianceOfficer` acting on a `REQUESTED` record — any other state draws `ERR_SUBSTITUTION_INVALID_STATE` (409). Approval enforces three rules in the narrative order the compliance team thinks about them. The proposed substitute must share the original species' `substitution_group`, else `ERR_SUBSTITUTION_GROUP_MISMATCH` (422). The substitute's standing price for the line's requested grade is then resolved through the selector of §3.2 — an unresolvable quote rejects the approval with `ERR_QUOTE_NOT_PUBLISHED` (422) — and it must not exceed the line's locked `unit_price_cents`, else `ERR_SUBSTITUTION_PRICE_INCREASE` (422): a substitution may save the house money, never cost it. And when the substitute species is flagged `requires_cites`, a `CLEARED` CITES import document for that species must already exist, else `ERR_LABELING_NONCOMPLIANT` (422), because the market `labeling_name` on the substitute is only lawful with its paperwork in place. Approval moves the record to `APPROVED`; rejection moves it to the terminal `REJECTED` state; either way the deciding officer is stamped as `decided_by_user_id`.

Application is the final step, performed by an `InventoryPlanner` on an `APPROVED` record — any other state draws `ERR_SUBSTITUTION_INVALID_STATE` — with the order in `CONFIRMED`, else `ERR_ORDER_INVALID_STATE`. Application rewrites the line: its `species_id` becomes the substitute species, and its `unit_price_cents` is replaced by the substitute's standing quote price selected per §3.2 as of the application date — an unresolvable standing quote rejects the application with `ERR_QUOTE_NOT_PUBLISHED` (422). The customer is credited for the difference: `price_credit_cents` is the old locked unit price less the new unit price, multiplied by the line's `requested_qty_kg`, rounded half up to whole cents. The line's `line_total_cents` is then recomputed under the per-line rounding rule — requested quantity times the new unit price times one minus the customer's `discount_pct`, rounded half up — and the order's `total_cents` is reduced by the credit. The customer's `credit_exposure_cents` is recomputed to match. The record lands in the terminal `APPLIED` state.

## 4. Endpoint Definitions

All paths are mounted at the service root. Operations that create a new resource — registering a configuration entity, opening a quote, ticket, line, assessment, order, order line, allocation, shipment, import document, hold, or substitution request — return `201 Created`. Operations that modify an existing resource, including every state-transition action, and all read operations return `200 OK`.

List endpoints accept the pagination parameters of §2.3 plus filter query parameters named after the resource's own fields: `species_id`, `grade`, `quote_date`, and `status` on quotes; `vessel_id`, `catch_area_id`, and `status` on dock tickets; `dock_ticket_id` and `species_id` on landing lines; `landing_line_id` and `status` on grade assessments; `landing_line_id`, `species_id`, `lifecycle_status`, and `hold_status` on inventory lots; `customer_id` and `status` on sales orders; `sales_order_id` and `species_id` on order lines; `order_line_id`, `inventory_lot_id`, and `status` on allocations; `sales_order_id` and `status` on shipments; `dock_ticket_id`, `species_id`, and `status` on import documents; `inventory_lot_id` and `status` on inspection holds; and `order_line_id`, `original_species_id`, `substitute_species_id`, and `status` on substitution approvals. Filters match on exact equality with the stored field value; query parameters that are neither pagination parameters nor named filters are ignored.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vessels` | Register a vessel | OperationsManager |
| GET | `/vessels/{id}` | Get a vessel | Any authenticated role |
| POST | `/customers` | Register a wholesale customer | OperationsManager |
| GET | `/customers/{id}` | Get a customer | Any authenticated role |
| POST | `/catch-areas` | Register an FAO catch area | OperationsManager |
| GET | `/catch-areas/{id}` | Get a catch area | Any authenticated role |
| POST | `/species` | Register a species | OperationsManager |
| GET | `/species/{id}` | Get a species | Any authenticated role |
| POST | `/market-quotes` | Create a daily quote (DRAFT) | OperationsManager |
| GET | `/market-quotes` | List quotes with filters | Any authenticated role |
| GET | `/market-quotes/{id}` | Get a quote | Any authenticated role |
| POST | `/market-quotes/{id}/publish` | Publish a quote; the volatility guard may route to PENDING_APPROVAL, and publication supersedes the prior published quote for the same species and grade | OperationsManager |
| POST | `/market-quotes/{id}/approve-volatility` | Approve a volatile quote; the approver must differ from the creator | OperationsManager |
| POST | `/market-quotes/{id}/reject-volatility` | Reject a volatile quote back to DRAFT | OperationsManager |
| POST | `/dock-tickets` | Create a dock ticket (DRAFT); per-vessel half-open landing-window overlap check | DockBuyer, VesselAgent |
| GET | `/dock-tickets` | List dock tickets with filters | Any authenticated role |
| GET | `/dock-tickets/{id}` | Get a dock ticket | Any authenticated role |
| POST | `/dock-tickets/{id}/land` | Mark a ticket landed (DRAFT to LANDED) | DockBuyer, VesselAgent |
| POST | `/dock-tickets/{id}/settle` | Settle a graded ticket; import-document and hold gates apply | OperationsManager |
| POST | `/dock-tickets/{id}/pay` | Pay a settled ticket (SETTLED to PAID) | OperationsManager |
| POST | `/dock-tickets/{id}/void` | Void a ticket from DRAFT, LANDED, GRADED, or SETTLED, with full cascade | OperationsManager |
| POST | `/dock-tickets/{id}/request-regrade` | Re-open grading; supersedes final assessments and recalls derived lots; at most two re-grades | DockBuyer, OperationsManager |
| POST | `/landing-lines` | Add a landing line to a LANDED ticket (optimistic concurrency on the ticket version) | DockBuyer |
| GET | `/landing-lines` | List landing lines with filters | Any authenticated role |
| GET | `/landing-lines/{id}` | Get a landing line | Any authenticated role |
| POST | `/grade-assessments` | Record a grade assessment (DRAFT) for a line of a LANDED ticket; one active assessment per line | GradingInspector |
| POST | `/grade-assessments/{id}/finalize` | Finalize an assessment; computes processed weight and final amount, creates the inventory lot, and may auto-grade the ticket | GradingInspector |
| GET | `/grade-assessments` | List grade assessments with filters | Any authenticated role |
| GET | `/grade-assessments/{id}` | Get a grade assessment | Any authenticated role |
| GET | `/inventory-lots` | List inventory lots with filters | Any authenticated role |
| GET | `/inventory-lots/{id}` | Get an inventory lot | Any authenticated role |
| POST | `/inventory-lots/{id}/freeze` | Convert a FRESH lot to FROZEN, resetting the shelf-life clock | InventoryPlanner |
| POST | `/inventory-lots/{id}/write-off` | Write off spoiled weight from the available bucket | InventoryPlanner |
| POST | `/sales-orders` | Create a sales order (DRAFT) | Customer, OperationsManager |
| GET | `/sales-orders` | List sales orders with filters | Any authenticated role |
| GET | `/sales-orders/{id}` | Get a sales order | Any authenticated role |
| POST | `/sales-orders/{id}/submit` | Submit an order (DRAFT to SUBMITTED); owning customer only | Customer |
| POST | `/sales-orders/{id}/confirm` | Confirm an order: locks line prices from the standing published quotes, computes totals, enforces the credit limit | OperationsManager |
| POST | `/sales-orders/{id}/cancel` | Cancel an order from DRAFT, SUBMITTED, or CONFIRMED; releases allocations | Customer, OperationsManager |
| POST | `/sales-orders/{id}/invoice` | Invoice a fulfilled order (FULFILLED to INVOICED) | OperationsManager |
| POST | `/order-lines` | Add a line to a DRAFT order | Customer, OperationsManager |
| GET | `/order-lines` | List order lines with filters | Any authenticated role |
| GET | `/order-lines/{id}` | Get an order line | Any authenticated role |
| POST | `/allocations` | Reserve weight from a lot against an order line (optimistic concurrency on the order version) | InventoryPlanner |
| POST | `/allocations/{id}/commit` | Commit a reservation (RESERVED to COMMITTED); may auto-fulfill the order | InventoryPlanner |
| POST | `/allocations/{id}/release` | Release a reservation; direct release of COMMITTED allocations is rejected | InventoryPlanner |
| GET | `/allocations` | List allocations with filters | Any authenticated role |
| GET | `/allocations/{id}` | Get an allocation | Any authenticated role |
| POST | `/shipments` | Create a shipment (QUOTED) for a CONFIRMED or FULFILLED order | LogisticsCoordinator |
| GET | `/shipments` | List shipments with filters | Any authenticated role |
| GET | `/shipments/{id}` | Get a shipment | Any authenticated role |
| POST | `/shipments/{id}/book` | Book a shipment (QUOTED to BOOKED); air capacity aggregate check and provisional freight | LogisticsCoordinator |
| POST | `/shipments/{id}/tender` | Tender a booked shipment with actual weight and volume; final freight | LogisticsCoordinator |
| POST | `/shipments/{id}/depart` | Depart a tendered shipment (TENDERED to IN_TRANSIT) | LogisticsCoordinator |
| POST | `/shipments/{id}/deliver` | Deliver an in-transit shipment; committed weight moves to shipped | LogisticsCoordinator |
| POST | `/shipments/{id}/cancel` | Cancel a QUOTED or BOOKED shipment; frees flight capacity | LogisticsCoordinator |
| POST | `/import-documents` | Create an import document (DRAFT) | ComplianceOfficer |
| GET | `/import-documents` | List import documents with filters | Any authenticated role |
| GET | `/import-documents/{id}` | Get an import document | Any authenticated role |
| POST | `/import-documents/{id}/submit` | Submit a document, or resubmit a REJECTED one | ComplianceOfficer |
| POST | `/import-documents/{id}/clear` | Clear a submitted document; the clearing officer must differ from the submitter | ComplianceOfficer |
| POST | `/import-documents/{id}/reject` | Reject a submitted document | ComplianceOfficer |
| POST | `/inspection-holds` | Place an inspection hold on an ACTIVE, CLEAR lot | ComplianceOfficer |
| GET | `/inspection-holds` | List inspection holds with filters | Any authenticated role |
| GET | `/inspection-holds/{id}` | Get an inspection hold | Any authenticated role |
| POST | `/inspection-holds/{id}/release` | Release a hold; the releasing officer must differ from the placing officer | ComplianceOfficer |
| POST | `/inspection-holds/{id}/condemn` | Condemn a held lot; fires the condemn cascade (lot, allocations, orders, auto-substitution) | ComplianceOfficer |
| POST | `/substitution-approvals` | Request a species substitution on an order line | InventoryPlanner |
| GET | `/substitution-approvals` | List substitution approvals with filters | Any authenticated role |
| GET | `/substitution-approvals/{id}` | Get a substitution approval | Any authenticated role |
| POST | `/substitution-approvals/{id}/approve` | Approve a substitution (group match, price non-increase, labeling and CITES compliance) | ComplianceOfficer |
| POST | `/substitution-approvals/{id}/reject` | Reject a substitution | ComplianceOfficer |
| POST | `/substitution-approvals/{id}/apply` | Apply an approved substitution: rewrites the line species, reprices, and credits the order | InventoryPlanner |
| POST | `/_clock/set_current_utc` | Set the logical clock; fires the quote-expiry and lot-expiry sweeps | OperationsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_LANDING_WINDOW` | 400 Bad Request |
| `ERR_INVALID_YIELD` | 400 Bad Request |
| `ERR_VESSEL_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_CATCH_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_SPECIES_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_IMPORT_DOC_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSTITUTION_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_INVALID_STATE` | 409 Conflict |
| `ERR_QUOTE_INVALID_STATE` | 409 Conflict |
| `ERR_ASSESSMENT_INVALID_STATE` | 409 Conflict |
| `ERR_LOT_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_ALLOCATION_INVALID_STATE` | 409 Conflict |
| `ERR_SHIPMENT_INVALID_STATE` | 409 Conflict |
| `ERR_IMPORT_DOC_INVALID_STATE` | 409 Conflict |
| `ERR_HOLD_INVALID_STATE` | 409 Conflict |
| `ERR_SUBSTITUTION_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_IMPORT_DOCS_NOT_CLEARED` | 409 Conflict |
| `ERR_LABELING_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_LOT_ON_HOLD` | 409 Conflict |
| `ERR_VESSEL_LANDING_OVERLAP` | 409 Conflict |
| `ERR_SHELF_LIFE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FLIGHT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 409 Conflict |
| `ERR_LINE_OVER_ALLOCATION` | 409 Conflict |
| `ERR_SPECIES_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_HOLD_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_REGRADE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_UNIQUE_VALUE` | 409 Conflict |
| `ERR_SUBSTITUTION_GROUP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_ORDER_EMPTY` | 422 Unprocessable Entity |
| `ERR_QUOTE_NOT_PUBLISHED` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_SUBSTITUTION_PRICE_INCREASE` | 422 Unprocessable Entity |

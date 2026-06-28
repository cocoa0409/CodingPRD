# Window-Tint & Vehicle-Wrap API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the back-office API that powers a window-tint and vehicle-wrap shop. The business sells four families of vehicle treatments — window tinting, paint-protection film (PPF), vinyl wraps, and ceramic coatings — and the lifecycle of a job runs from a customer asking for a price, through a legally-compliant quote, into a scheduled install on a physical bay with a certified installer, and finally into curing, warranty, and after-sales callbacks. The API exists to make every one of those steps deterministic and auditable, so that a price quoted to a customer can be reproduced exactly, a slot reserved on a bay cannot be double-booked, and a tint job that violates a state's legal light-transmission floor is rejected before any film is cut.

Several forces pull against one another in this domain, and the system is designed to reconcile them rather than hide them. State law caps how dark a front-side window or windshield strip may be, but a driver with a medical condition may be granted an exemption — and only in states that permit such exemptions. A rush job earns the shop a premium, yet the premium is larger for smaller jobs, not larger ones. Commercial fleet operators receive a volume discount and pay on credit, which means the shop must track how much of a fleet's credit line is provisionally tied up by open work versus how much has actually been invoiced. Vinyl wraps require the customer to approve a printed design proof, sometimes over several revision rounds, before any installer may begin. The sections that follow define the entities, the lifecycle state machines, the pricing and scheduling calculations, the validation order, and the full API surface that together encode these rules.

Because pricing, scheduling, curing, warranty, and quote-expiry all depend on the passage of time, the system never reads the real wall clock. Instead it maintains a single logical clock that test harnesses and operators advance explicitly, and every deadline-sensitive rule — cure completion, warranty expiry, quote time-to-live, and slot eligibility — reads that logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is syntactically valid but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognises exactly five roles: `ShopManager`, `Installer`, `Customer`, `FleetManager`, and `ComplianceOfficer`. Their identities bind to persisted data in different ways, and that binding is what gives ownership checks their meaning:

- When `X-User-Role` is `ShopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `Installer`, `X-User-ID` is the `installer_user_id` of the acting `Installer`; ownership checks on any resource that references an `Installer` compare the resource's installer principal to `X-User-ID`. In particular, starting or completing an install requires that `X-User-ID` equal the `installer_user_id` of the `Installer` assigned to that work order.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `customer_user_id` of the acting vehicle owner as recorded on the `VehicleProfile`; ownership checks on any resource that references a `VehicleProfile` (a quote, its lines, its proofs, its work orders) compare the vehicle's `customer_user_id` to `X-User-ID`.
- When `X-User-Role` is `FleetManager`, `X-User-ID` is the `fleet_manager_user_id` of the acting `FleetAccount`; ownership checks on any resource that references a `FleetAccount` compare the account's `fleet_manager_user_id` to `X-User-ID`.

When an entity-backed role acts on a resource it is supposed to own but whose owner field does not match `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This applies to `Customer` actions on vehicle-owned resources, `FleetManager` actions on their fleet account, and `Installer` self-actions on their assigned work.

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

Endpoints that return lists accept two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, and it must be between a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0; it may not be negative. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless an endpoint states otherwise, list results are ordered by their `created_at` timestamp ascending. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Most resources in this system are full first-class entities and carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value and increments by one on every mutation; it is the basis for the optimistic-concurrency checks described in §2.6.

`ShopLocation`, `FilmMaterial`, `ServicePackage`, `VehicleProfile`, `FleetAccount`, `Quote`, `QuoteLine`, `MedicalExemption`, `Bay`, `Installer`, `WorkOrder`, `WrapProof`, and `CallbackTicket` all carry the full set above. The one exception is `StateTintRegulation`: it is a reference record that carries only `id` and `created_at`. It has no `updated_at` and no `version` field, and operations never apply concurrency checks to it.

### 2.5. Hierarchical Consistency and Cascades

A single operation in this domain frequently mutates more than one entity, and every such cascade is part of the contract. Whenever a write changes a field on a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one; this holds even when the field changed is a server-computed value such as a fleet account's held credit or a bay's reserved minutes. Where one action reaches across aggregates — scheduling a work order that touches a quote, a bay, an installer, and possibly a fleet account — each affected entity is updated independently, and the specific increments and field changes are spelled out alongside the workflow that triggers them in §3. Cancellation in particular is a compensating cascade: releasing a work order returns reserved bay minutes, returns any held fleet credit, and re-opens the source quote so it can be scheduled again. These cascades are detailed where they occur.

### 2.6. Optimistic Concurrency Control

A small set of write operations require the client to prove it is acting on a current view of a parent resource. These operations take a mandatory version field in their request body, and the server compares it against the parent's live `version`. If the two differ — because some other writer advanced the parent's `version` since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the parent before retrying. Endpoints not named here do not accept a version field.

Two parents are guarded this way. First, four quote operations require `expected_quote_version` to match the target `Quote`'s current `version`: adding a line to a quote, pricing a quote, accepting a quote, and scheduling a work order from a quote. Second, cancelling a work order requires `expected_work_order_version` to match that `WorkOrder`'s current `version`. The precise business consequences of each stale-version rejection are described in §3 next to the relevant workflow.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents; there are no fractional cents and no floating-point money. Wherever a price computation produces a non-integer cents value, the system rounds it to a whole number of cents using the round-half-up convention (a value exactly on the half rounds up). The pricing rules in §3 state precisely where each rounding step is applied, because the order of rounding relative to addition is significant — for example, a per-line product is rounded before an integer surcharge is added, and a discount is computed on a summed subtotal rather than line by line.

### 2.8. The Logical Clock and Time Semantics

The server keeps a single logical clock expressed in UTC. Before any operator sets it, the clock reads `2026-04-01T00:00:00Z`; it is never the real wall-clock time. Every time-dependent rule — when a quote expires, when an install slot becomes startable, when curing is complete, and when a warranty lapses — reads this clock. An operator advances the clock by supplying a `to_iso8601` target instant. The clock may only move forward: a target earlier than the current logical clock is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422). All datetime arithmetic is performed in UTC and rendered in ISO 8601 with three fractional digits.

### 2.9. Tint Compliance and Medical Exemptions

Tint legality is governed per shop by the `StateTintRegulation` whose `state_code` matches the shop's `state_code`. A regulation fixes three things: the `front_side_min_vlt_pct` (the minimum legal Visible Light Transmission percentage for front-side windows), the `windshield_strip_max_inches` (the deepest a windshield tint strip may run, measured in inches from the top), and `medical_exemption_allowed` (whether the state lets a driver lower the front-side floor with a medical certificate). A `MedicalExemption` carries an `exempt_min_vlt_pct` — the reduced front-side floor it authorises once `APPROVED` — and only an `APPROVED` exemption has any effect. The exact comparisons, the priority in which they run, and the errors they raise are defined in the pricing workflow in §3.

### 2.10. Nested Resource Retrieval and Existence Order

Several paths nest a child under a parent — quote lines under a quote, wrap proofs under a work order. For any request, the system validates referenced resources left to right: path identifiers first, in the order they appear, then foreign-key references in the request body. The first identifier that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or business rule is considered.

### 2.11. Validation Order

When several checks could apply to one request, they are evaluated in a fixed priority order so that the error a client sees is deterministic. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_FORBIDDEN_ROLE`), then resource ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`). Next the system confirms every referenced resource exists (`ERR_NOT_FOUND`), then that the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then the optimistic-concurrency version check (`ERR_STALE_VERSION`), then quote-expiry (`ERR_QUOTE_EXPIRED`). Domain-specific business rules — compliance, proof gates, compatibility, certification, scheduling overlap, referential preconditions, and fiscal limits — run after those, and a generic request-shape check (`ERR_INVALID_REQUEST`, raised when a required field is missing, a type is wrong, or an enum value is invalid) is the lowest-priority guard that backstops everything. Where two business rules can both apply to the same endpoint, the workflow in §3 names which is evaluated first.

## 3. Business Logic & Workflows

### 3.1. Configuring the Shop, Catalog, and Compliance Reference Data

Before any vehicle is priced, a `ShopManager` stands up the shop's static configuration. A shop branch is created with a display `name` and a two-letter `state_code`; it begins life with `status` of `ACTIVE` and may later be `SUSPENDED`. The `state_code` is how a shop is tied to the legal regime that governs its work: it is an uppercase two-letter code, and at the point it is used for compliance it must match the `state_code` of an existing `StateTintRegulation`.

A `ComplianceOfficer` owns the legal reference data. Registering a state's regulation supplies its `state_code`, the `front_side_min_vlt_pct`, the `windshield_strip_max_inches`, and the `medical_exemption_allowed` flag. The `state_code` is unique across regulations; registering a second regulation for a state that already has one is rejected with `ERR_DUPLICATE_STATE_REGULATION` (HTTP 409).

The materials catalog is the `ShopManager`'s domain. A `FilmMaterial` is created with a `sku` that must be unique — a repeat is rejected with `ERR_DUPLICATE_SKU` (HTTP 409) — a `category` that is one of `TINT_FILM`, `PPF_FILM`, `WRAP_VINYL`, or `CERAMIC_COATING`, a `cure_hours` value giving the hours of curing the material needs after install, and a `price_multiplier_bps`, expressed in basis points where 10000 means a multiplier of exactly 1.00. A material's `status` defaults to `ACTIVE` and may become `DISCONTINUED`. A `ServicePackage` is created with a `name`, a `service_type` of `TINT`, `PPF`, `WRAP`, or `CERAMIC`, a `base_rate_cents`, a `duration_minutes` (which must be strictly greater than zero and gives the bay-and-installer occupancy length for a line of this package), a `cure_buffer_minutes` (extra minutes the bay stays occupied for in-bay curing after the install duration; zero for services that cure off the bay), a `warranty_days`, and a `requires_proof` flag that decides whether a design-proof approval cycle must complete before install may start.

### 3.2. Vehicles, Fleet Accounts, and Credit Standing

A vehicle is registered as a `VehicleProfile` by a `Customer` or a `ShopManager`, supplying the owner's `customer_user_id`, the `vin`, and a `size_class` of `SEDAN`, `SUV`, or `TRUCK`. The `vin` is unique across vehicles; a duplicate is rejected with `ERR_DUPLICATE_VIN` (HTTP 409). On creation the system computes the per-line `size_surcharge_cents` directly from the size class: a `SEDAN` carries a surcharge of 0 cents, an `SUV` carries 15000 cents, and a `TRUCK` carries 25000 cents.

A commercial relationship is modelled as a `FleetAccount`, created by a `ShopManager` with a `company_name`, the `fleet_manager_user_id` of the owning manager, a `discount_bps` volume discount in basis points (between 0 and 10000 inclusive), and a `credit_limit_cents` ceiling on outstanding credit. Its `status` defaults to `ACTIVE` and may be `SUSPENDED`. The account also exposes a computed `held_credit_cents`, which starts at 0 and represents credit provisionally tied up by open work.

When a fleet account is read, the system recomputes its credit standing two ways. The **provisional** view, `held_credit_cents`, is the sum of `total_due_cents` across every `WorkOrder` linked to the account whose `install_status` is `SCHEDULED`, `IN_PROGRESS`, `CURING`, or `COMPLETED`; provisional available credit is the `credit_limit_cents` minus that held amount. A scheduled-but-unpaid order still consumes provisional credit. The **settled** view counts differently: it consumes credit only for orders whose `payment_status` is `INVOICED` (invoiced but not yet settled), so settled available credit is the `credit_limit_cents` minus the sum of `total_due_cents` over those `INVOICED` orders. The two views diverge whenever orders are completed-but-uninvoiced or invoiced-but-unsettled, which is exactly the window the accounting team cares about.

### 3.3. Building and Pricing a Quote

A `Customer` (or a `ShopManager` acting on their behalf) opens a `Quote` for a vehicle at a shop, supplying the `vehicle_profile_id` and the `shop_location_id`, optionally a `fleet_account_id` to attach a commercial account, and optionally a `rushed` flag (defaulting to false). A new quote begins in `DRAFT`. Its computed money fields — `subtotal_cents`, `discount_cents`, `net_cents`, `rush_fee_cents`, `total_due_cents`, and `deposit_required_cents` — all start at 0 and stay there until the quote is priced.

Lines are added to a draft. Each `QuoteLine` names a `service_package_id`, a `film_material_id`, a `coverage` of `FULL`, `PARTIAL`, or `ACCENT`, and a `window_position` of `FRONT_SIDE`, `REAR_SIDE`, `REAR_WINDOW`, `WINDSHIELD`, or `BODY_PANEL`. Two further inputs are optional: `requested_vlt_pct`, the requested Visible Light Transmission percentage for the film (defaulting to 100, and required to fall between 0 and 100 inclusive — a value outside that range is rejected with `ERR_VLT_OUT_OF_RANGE`), and `strip_depth_inches`, the depth in inches of a windshield tint strip from the top (defaulting to 0, and never negative). A line records its parent `quote_id`, begins with `status` of `INCLUDED`, and carries a computed `line_total_cents` that is 0 until pricing. Adding a line requires `expected_quote_version` in the body. At the moment a line is added, the system checks that the chosen material's `category` is compatible with the package's `service_type` under the one-to-one mapping `TINT` with `TINT_FILM`, `PPF` with `PPF_FILM`, `WRAP` with `WRAP_VINYL`, and `CERAMIC` with `CERAMIC_COATING`; an incompatible pairing is rejected with `ERR_MATERIAL_INCOMPATIBLE` (HTTP 422).

A line may be withdrawn, which marks its `status` as `REMOVED`; removed lines are excluded from all pricing. Both adding a line and removing a line are edits to the priced basis of the quote, so if the quote was already `PRICED` the edit reverts it to `DRAFT`, resets all six computed money fields to 0 (the stale pricing is invalidated), and increments the quote's `version` by one. This is a deliberate cycle: editing the lines of a priced quote forces it to be priced again before it can be accepted.

Pricing a quote drives the transition from `DRAFT` to `PRICED`. It is permitted only when the quote is currently `DRAFT`, the supplied `expected_quote_version` matches the quote's `version`, and at least one `INCLUDED` line exists — pricing a quote with no included lines is rejected with `ERR_NO_INCLUDED_LINES` (HTTP 422). Pricing then runs the compliance and compatibility gates described in §3.4, recomputes every included line's `line_total_cents`, recomputes the quote-level money fields, and increments the quote's `version` by one.

Each included line is priced as follows. A coverage factor is selected from the line's `coverage`: `FULL` is 1.00, `PARTIAL` is 0.60, and `ACCENT` is 0.35. A material multiplier is the material's `price_multiplier_bps` divided by 10000, kept as an exact ratio. The system multiplies the package's `base_rate_cents` by the coverage factor and by the material multiplier to get a raw cents amount, rounds that product half-up to a whole number of cents, and only then adds the vehicle's integer `size_surcharge_cents`; the sum is the line's `line_total_cents`. The rounding is pinned to the product before the surcharge is added — the surcharge is never inside the rounding. The fleet discount, if any, never enters at the line level; line prices are identical whether or not the quote is attached to a fleet account.

The quote-level total is computed in a strictly pinned order. First, `subtotal_cents` is the sum of `line_total_cents` over the `INCLUDED` lines. Second, `discount_cents` is the fleet discount applied to that summed subtotal: it is the subtotal multiplied by the fleet account's `discount_bps` divided by 10000, rounded half-up — and computed once on the sum, never line by line. When no fleet account is attached the discount basis points are 0, so `discount_cents` is 0. Third, `net_cents` is `subtotal_cents` minus `discount_cents`. Fourth, a rush fee is keyed off the discounted `net_cents`: if the quote is not rushed the `rush_fee_cents` is 0 and `total_due_cents` equals `net_cents`; if the quote is rushed, a rush rate in basis points is chosen from the net tier — 500 basis points when `net_cents` is at least 100000, 800 basis points when `net_cents` is at least 50000 but below 100000, and 1200 basis points when `net_cents` is below 50000 — and `rush_fee_cents` is `net_cents` multiplied by that rate divided by 10000, rounded half-up. Note that the rush percentage is higher for smaller jobs. The `total_due_cents` is `net_cents` plus `rush_fee_cents`. Finally the `deposit_required_cents` is `net_cents` multiplied by 2500 basis points divided by 10000, rounded half-up — that is, a quarter of the net amount, rounded half-up. Every one of these rounding steps is applied to a sum, never per line, and the tier breakpoints are inclusive lower bounds.

Adding a line to a quote also carries the stale-version protection from §2.6: the request must carry `expected_quote_version` matching the target quote's current `version`. Because both pricing and line-edit reversion advance a quote's `version`, a writer adding a line from a stale snapshot is rejected with `ERR_STALE_VERSION` (HTTP 412), so a recomputed subtotal cannot silently drop or double-count a line the client never saw.

### 3.4. Tint Compliance, Exemptions, and the Order of Pricing Gates

Compliance is enforced when a quote is priced, and three guards run in a fixed order before the money is computed. Their inputs are scattered across the quote line (`window_position`, `requested_vlt_pct`, `strip_depth_inches`) and the governing `StateTintRegulation` (resolved from the shop's `state_code`).

The first guard concerns exemption applicability. A `MedicalExemption` is filed against a vehicle with a `certificate_ref` and an `exempt_min_vlt_pct`, beginning in `PENDING`; a `ComplianceOfficer` may move it to `APPROVED` or `REJECTED`, and an approved exemption may later be `REVOKED`. Only an `APPROVED` exemption covering the quoted vehicle can lower a floor. If a front-side line sits below the statutory floor and an approved exemption does cover the vehicle, but the shop's state has `medical_exemption_allowed` set to false, the exemption cannot be honoured in that state and pricing is rejected with `ERR_EXEMPTION_NOT_ALLOWED` (HTTP 422).

The second guard is the front-side VLT floor. For a line whose `window_position` is `FRONT_SIDE`, the requested `requested_vlt_pct` must be at least the effective floor. The effective floor is the regulation's `front_side_min_vlt_pct`, lowered to an approved exemption's `exempt_min_vlt_pct` only when the state's `medical_exemption_allowed` is true and an approved exemption covers the vehicle. A front-side line below its effective floor is rejected with `ERR_TINT_BELOW_LEGAL_VLT` (HTTP 422).

The third guard is the windshield strip limit. For a line whose `window_position` is `WINDSHIELD`, the `strip_depth_inches` must be at most the regulation's `windshield_strip_max_inches`. No medical exemption ever relaxes the windshield strip limit. A windshield line exceeding the allowed depth is rejected with `ERR_WINDSHIELD_STRIP_EXCEEDS_LIMIT` (HTTP 422). Material compatibility, already checked when a line is added, is re-verified at pricing time as well, again raising `ERR_MATERIAL_INCOMPATIBLE` for any included line whose material `category` does not match its package `service_type`.

### 3.5. Accepting and Voiding Quotes; Expiry

Once a quote is `PRICED`, the owning `Customer` may accept it, moving it from `PRICED` to `ACCEPTED`; acceptance requires `expected_quote_version` to match the quote's `version` and increments that `version`. A quote that is `DRAFT` or `PRICED` may instead be voided by the customer or a shop manager, moving it to the terminal `VOIDED` state and incrementing its `version`.

Quotes do not live forever. A `PRICED` quote that has aged past 30 days from its `created_at`, as measured against the logical clock, is treated as `EXPIRED`. The system observes this lazily: on the next read of such a quote, it transitions the quote to the terminal `EXPIRED` state (incrementing `version`). Attempting to accept or to schedule a work order from a priced quote that has passed its 30-day life is rejected with `ERR_QUOTE_EXPIRED` (HTTP 409). Acceptance from any state other than `PRICED`, like every other transition, is rejected by the state guard with `ERR_INVALID_STATE` (HTTP 409).

### 3.6. Scheduling a Work Order

A `ShopManager` realises an accepted quote by scheduling a `WorkOrder` onto a bay and an installer. The request supplies the `quote_id`, the `bay_id`, the `installer_id`, the `scheduled_start` (an ISO 8601 UTC instant), and `expected_quote_version`. Bays and installers are themselves shop configuration: a `Bay` is created with its `shop_location_id` and a `label`, defaults to `status` of `OPEN` (and may be `CLOSED`), and exposes a computed `reserved_minutes`; an `Installer` is created with a `shop_location_id`, the `installer_user_id` principal, a `full_name`, and a `certified_service_types` array drawn from `TINT`, `PPF`, `WRAP`, and `CERAMIC`, defaulting to `status` of `AVAILABLE` (and may be `OFF_DUTY`).

Scheduling runs a battery of preconditions. The source quote must be `ACCEPTED`; a quote in any other state is rejected with `ERR_QUOTE_NOT_ACCEPTED` (HTTP 409), and a priced-but-expired quote is rejected with `ERR_QUOTE_EXPIRED`. The supplied `expected_quote_version` must match the quote's current `version`, or the schedule is rejected with `ERR_STALE_VERSION` (HTTP 412): an accepted quote can legitimately be scheduled, but because cancelling a previously-scheduled order bumps the quote back to `ACCEPTED` and advances its `version`, a client still holding the old version is working from a stale view and must re-read before scheduling. The system derives the order's `primary_service_type` as the `service_type` of the source quote's `INCLUDED` line with the highest `line_total_cents`, breaking ties by the earliest line `created_at`. The assigned installer's `certified_service_types` must include that `primary_service_type`, or the request is rejected with `ERR_INSTALLER_NOT_CERTIFIED` (HTTP 422).

Two temporal guards then protect the schedule. The work order's bay occupancy runs over the half-open interval from `scheduled_start` to `scheduled_start` plus the order's `duration_minutes` plus its `cure_buffer_minutes`; adjacency is allowed, but if this interval overlaps any existing active work order on the same bay the request is rejected with `ERR_BAY_TIME_CONFLICT` (HTTP 409). The installer is protected by a front rest buffer: the installer occupancy runs over the half-open interval from 45 minutes before `scheduled_start` up to `scheduled_start` plus the order's `duration_minutes`; if this interval overlaps any existing active work order for the same installer the request is rejected with `ERR_INSTALLER_TIME_CONFLICT` (HTTP 409). The order's `duration_minutes` is the sum of `duration_minutes` over the source quote's `INCLUDED` lines' packages, and its `cure_buffer_minutes` is the maximum of `cure_buffer_minutes` over those same packages.

For a fleet quote, one more gate applies: scheduling must not push the account's provisional held credit above its limit. The provisional available credit (the `credit_limit_cents` minus the current `held_credit_cents`) must be at least the order's `total_due_cents` at schedule time, or the request is rejected with `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 409).

When all gates pass, a 201 work order is created. The order copies `fleet_account_id`, `total_due_cents`, `duration_minutes`, `cure_buffer_minutes`, and `primary_service_type` from the quote (the `fleet_account_id` is null for a retail order). Its `install_status` begins at `SCHEDULED` and its `payment_status` at `DEPOSIT_DUE`; these two dimensions evolve independently on the same row. The system sets the estimated `cure_complete_at` as described in §3.7, adds the order's `duration_minutes` plus `cure_buffer_minutes` to the chosen bay's `reserved_minutes`, and — if the order is on a fleet account — adds the order's `total_due_cents` to that account's `held_credit_cents`. Finally the source quote transitions from `ACCEPTED` to the terminal `CONVERTED` state and its `version` is incremented.

### 3.7. Install Execution, Curing, Warranty, and Release

The assigned `Installer` begins work, advancing the order from `SCHEDULED` to `IN_PROGRESS`. Starting requires that the order is `SCHEDULED`, that `X-User-ID` equal the assigned installer's `installer_user_id`, and that the logical clock has reached the `scheduled_start`. If the order's `primary_service_type` resolves to a package whose `requires_proof` is true, an `APPROVED` `WrapProof` must already exist for the order; otherwise the start is blocked with `ERR_PROOF_NOT_APPROVED` (HTTP 409). On a successful start the system records `actual_started_at` as the current clock and increments the order's `version`.

Completing the install advances the order from `IN_PROGRESS` to `CURING`. The system records `actual_completed_at` as the current clock and computes two derived instants from it. The curing deadline `cure_complete_at` is recomputed in its **actual** form: the cure hours added to `actual_completed_at`, where the cure hours are the maximum `cure_hours` over the materials on the source quote's `INCLUDED` lines. This actual figure supersedes the estimate that was set at scheduling — that estimate had anchored the same maximum cure hours onto the `scheduled_start` plus the order's `duration_minutes`. The warranty deadline `warranty_expires_at` is `actual_completed_at` plus the warranty length in days, where that length is the maximum `warranty_days` over the source quote's `INCLUDED` lines' packages — the maximum across packages, never the sum. Completing increments the order's `version`. The bay and installer remain reserved through the `CURING` phase to cover the cure buffer.

A `ShopManager` releases a cured order, advancing it from `CURING` to the `COMPLETED` state, which is permitted only once the logical clock has reached the order's `cure_complete_at`. Releasing frees the bay: the order's `duration_minutes` plus `cure_buffer_minutes` is subtracted from the bay's `reserved_minutes`. Note that bay capacity is freed at `COMPLETED`, but fleet credit stays held — a completed order still consumes provisional fleet credit until it is invoiced. Releasing increments the order's `version`.

### 3.8. Cancellation and Its Compensating Cascade

A `ShopManager` may cancel a work order while it is `SCHEDULED` or `IN_PROGRESS`, moving it to the terminal `CANCELLED` state; cancellation requires `expected_work_order_version` to match the order's current `version`. Cancellation reverses every commitment scheduling made. The order's `duration_minutes` plus `cure_buffer_minutes` is subtracted back from the bay's `reserved_minutes`. If the order is on a fleet account, the order's `total_due_cents` is subtracted from that account's `held_credit_cents`, releasing the held credit. The source quote is set back from `CONVERTED` to `ACCEPTED` so it can be scheduled afresh, and its `version` is incremented. The order's own `version` is incremented as well. Because the quote returns to `ACCEPTED` with an advanced `version`, any client still holding the pre-cancellation version must re-read before it can schedule again — the stale-version rejection on scheduling exists precisely to enforce this.

### 3.9. The Payment Dimension

Payment status evolves on the same work order row but independently of install status. A new order is `DEPOSIT_DUE`. The owning `Customer` pays the deposit by supplying an `amount_cents` that must equal the source quote's `deposit_required_cents` exactly; a mismatch is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH` (HTTP 422), and a successful payment advances the order from `DEPOSIT_DUE` to `DEPOSIT_PAID` and increments its `version`.

A `ShopManager` invoices a deposit-paid order, advancing it from `DEPOSIT_PAID` to `INVOICED`. Invoicing is gated across the two dimensions: it requires that the order's `install_status` be `COMPLETED`. On invoicing, a fleet account's `held_credit_cents` stays held provisionally, but the invoiced amount is now recorded so that the settled credit view counts this order; the order's `version` increments. Finally a `ShopManager` settles an invoiced order, advancing it from `INVOICED` to the terminal `SETTLED` state: on settlement, if the order is on a fleet account, the order's `total_due_cents` is subtracted from that account's `held_credit_cents`, releasing the credit for good, and the order's `version` increments.

### 3.10. Wrap Design Proofs and the Revision Loop

When a package requires a proof, an `Installer` uploads a design by supplying a `design_ref`, which creates a `WrapProof` against the work order in `PROOF_SUBMITTED` status with `revision_round` of 1. Submitting a proof for an order whose `primary_service_type` resolves to a package that does not require a proof is rejected with `ERR_PROOF_NOT_REQUIRED` (HTTP 409). The owning `Customer` reviews a submitted proof and may approve it (moving it from `PROOF_SUBMITTED` to the terminal `APPROVED` state), reject it (moving it to the terminal `REJECTED` state), or request changes (moving it from `PROOF_SUBMITTED` to `CHANGES_REQUESTED`); each of these increments the proof's `version`.

Requesting changes opens a revision round. The installer then resubmits a new design, which is permitted only when the order's primary package does in fact require a proof and when the order's latest proof — the one with the highest `revision_round`, breaking ties by the latest `created_at` — is currently in `CHANGES_REQUESTED` (so there is no already-`APPROVED` or `REJECTED` proof and no `PROOF_SUBMITTED` one still awaiting review). The resubmission creates a fresh `WrapProof` whose `revision_round` is one greater than that latest proof, in `PROOF_SUBMITTED` status, and the cycle of `PROOF_SUBMITTED` to `CHANGES_REQUESTED` to a new `PROOF_SUBMITTED` may repeat. The `revision_round` therefore counts the rounds, and the very first proof on an order is round 1.

### 3.11. After-Sales Callbacks and Free Rework

A completed job that develops a problem is handled through a `CallbackTicket`. A `Customer` or `ShopManager` opens one by supplying the `work_order_id` and a `reason` of `BUBBLING`, `PEELING`, `COLOR_MISMATCH`, or `MEASUREMENT_ERROR`. A callback may be opened only against an order whose `install_status` is `COMPLETED` and only while the logical clock is at or before that order's `warranty_expires_at`; otherwise it is rejected with `ERR_OUT_OF_WARRANTY` (HTTP 409). A new ticket starts in `OPEN` with no `outcome` yet recorded.

A `ShopManager` resolves an open ticket by supplying an `outcome` of either `REDO` or `DENIED`, which moves the ticket from `OPEN` to `RESOLVED` and increments its `version`. A `DENIED` outcome closes out the matter with no rework. A `REDO` outcome requires that the referenced work order be `COMPLETED` and triggers a free rework: the order's `duration_minutes` plus `cure_buffer_minutes` is added back onto that order's bay's `reserved_minutes`, re-reserving the same bay capacity for the redo, and the order's `total_due_cents` is not charged again. Because a redo re-reserves bay minutes, the bay-overlap check applies anew to any bookings that follow. A resolved ticket is finally closed by a `ShopManager`, moving it from `RESOLVED` to the terminal `CLOSED` state and incrementing its `version`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that read or that modify an existing resource (including state transitions) return `200 OK`. All endpoints require the `X-User-ID` and `X-User-Role` headers described in §2.1. List endpoints accept the `limit` and `offset` query parameters from §2.3 in addition to any filters noted in their description.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shop-locations` | Create a shop branch | ShopManager |
| GET | `/shop-locations/{id}` | Read a shop | ShopManager, Installer, Customer, FleetManager, ComplianceOfficer |
| POST | `/state-tint-regulations` | Register a state's tint regulation | ComplianceOfficer |
| GET | `/state-tint-regulations/{id}` | Read a state regulation | ComplianceOfficer, ShopManager, Customer |
| POST | `/film-materials` | Create a film/material catalog entry | ShopManager |
| GET | `/film-materials/{id}` | Read a film material | ShopManager, Installer, Customer |
| POST | `/service-packages` | Create a service package | ShopManager |
| GET | `/service-packages/{id}` | Read a service package | ShopManager, Installer, Customer |
| POST | `/vehicle-profiles` | Register a customer vehicle | Customer, ShopManager |
| GET | `/vehicle-profiles/{id}` | Read a vehicle profile | Customer, ShopManager, Installer |
| POST | `/fleet-accounts` | Create a commercial fleet account | ShopManager |
| GET | `/fleet-accounts/{id}` | Read a fleet account incl. provisional/settled available credit | FleetManager, ShopManager |
| POST | `/medical-exemptions` | File a medical exemption for a vehicle | Customer, ComplianceOfficer |
| GET | `/medical-exemptions/{id}` | Read a single medical exemption | ComplianceOfficer, Customer, ShopManager |
| POST | `/medical-exemptions/{id}/approve` | Approve a pending exemption | ComplianceOfficer |
| POST | `/medical-exemptions/{id}/reject` | Reject a pending exemption | ComplianceOfficer |
| GET | `/medical-exemptions` | List exemptions; filter by `vehicle_profile_id` | ComplianceOfficer, Customer, ShopManager |
| POST | `/bays` | Create an install bay at a shop | ShopManager |
| GET | `/bays/{id}` | Read a single bay incl. reserved minutes | ShopManager, Installer |
| GET | `/bays` | List bays; filter by `shop_location_id` | ShopManager, Installer |
| POST | `/installers` | Create an installer at a shop | ShopManager |
| GET | `/installers/{id}` | Read a single installer | ShopManager, Installer |
| GET | `/installers` | List installers; filter by `shop_location_id` | ShopManager |
| POST | `/quotes` | Create a draft quote for a vehicle at a shop | Customer, ShopManager |
| GET | `/quotes` | List quotes; filter by `vehicle_profile_id`, `shop_location_id`, or `fleet_account_id` | Customer, ShopManager, FleetManager |
| GET | `/quotes/{id}` | Read a quote (observes TTL expiry on read) | Customer, ShopManager, FleetManager |
| POST | `/quotes/{id}/lines` | Add a line to a quote (reverts PRICED to DRAFT) | Customer, ShopManager |
| GET | `/quotes/{id}/lines` | List the lines of a quote | Customer, ShopManager, FleetManager |
| DELETE | `/quote-lines/{id}` | Mark a line REMOVED (reverts PRICED to DRAFT) | Customer, ShopManager |
| GET | `/quote-lines/{id}` | Read a single quote line | Customer, ShopManager |
| GET | `/quote-lines` | List quote lines; filter by `quote_id`, `service_package_id`, or `film_material_id` | Customer, ShopManager |
| POST | `/quotes/{id}/price` | Price a quote (DRAFT to PRICED); runs compliance and computes totals | Customer, ShopManager |
| POST | `/quotes/{id}/accept` | Accept a priced quote (PRICED to ACCEPTED) | Customer |
| POST | `/quotes/{id}/void` | Void a quote (DRAFT/PRICED to VOIDED) | Customer, ShopManager |
| POST | `/work-orders` | Schedule a work order from an accepted quote onto a bay and installer | ShopManager |
| GET | `/work-orders` | List work orders; filter by `fleet_account_id`, `bay_id`, `installer_id`, `quote_id` | ShopManager, FleetManager, Installer |
| GET | `/work-orders/{id}` | Read a work order | ShopManager, Installer, Customer, FleetManager |
| POST | `/work-orders/{id}/start` | Begin install (SCHEDULED to IN_PROGRESS); proof gate enforced | Installer |
| POST | `/work-orders/{id}/complete-install` | Finish install (IN_PROGRESS to CURING); recompute actual cure and warranty | Installer |
| POST | `/work-orders/{id}/release` | Release a cured order (CURING to COMPLETED); frees bay capacity | ShopManager |
| POST | `/work-orders/{id}/cancel` | Cancel a scheduled/in-progress order; compensating release | ShopManager |
| POST | `/work-orders/{id}/pay-deposit` | Pay the deposit (DEPOSIT_DUE to DEPOSIT_PAID) | Customer |
| POST | `/work-orders/{id}/invoice` | Invoice a completed order (DEPOSIT_PAID to INVOICED) | ShopManager |
| POST | `/work-orders/{id}/settle` | Settle an invoiced order (INVOICED to SETTLED) | ShopManager |
| POST | `/work-orders/{id}/proofs` | Submit/resubmit a wrap design proof for an order | Installer |
| GET | `/work-orders/{id}/proofs` | List wrap proofs for an order | ShopManager, Installer, Customer |
| POST | `/wrap-proofs/{id}/approve` | Customer approves a submitted proof | Customer |
| POST | `/wrap-proofs/{id}/request-changes` | Customer requests changes | Customer |
| POST | `/wrap-proofs/{id}/reject` | Customer rejects a submitted proof | Customer |
| POST | `/callbacks` | Open a callback/redo ticket against a completed in-warranty order | Customer, ShopManager |
| GET | `/callbacks/{id}` | Read a single callback ticket | ShopManager, Customer |
| GET | `/callbacks` | List callbacks; filter by `work_order_id` | ShopManager, Customer |
| POST | `/callbacks/{id}/resolve` | Resolve a callback as REDO or DENIED | ShopManager |
| POST | `/callbacks/{id}/close` | Close a resolved callback (RESOLVED to CLOSED) | ShopManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_TINT_BELOW_LEGAL_VLT` | 422 |
| `ERR_WINDSHIELD_STRIP_EXCEEDS_LIMIT` | 422 |
| `ERR_PROOF_NOT_APPROVED` | 409 |
| `ERR_MATERIAL_INCOMPATIBLE` | 422 |
| `ERR_INSTALLER_NOT_CERTIFIED` | 422 |
| `ERR_BAY_TIME_CONFLICT` | 409 |
| `ERR_INSTALLER_TIME_CONFLICT` | 409 |
| `ERR_QUOTE_NOT_ACCEPTED` | 409 |
| `ERR_OUT_OF_WARRANTY` | 409 |
| `ERR_FLEET_CREDIT_EXCEEDED` | 409 |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NO_INCLUDED_LINES` | 422 |
| `ERR_VLT_OUT_OF_RANGE` | 422 |
| `ERR_DUPLICATE_VIN` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_DUPLICATE_STATE_REGULATION` | 409 |
| `ERR_EXEMPTION_NOT_ALLOWED` | 422 |
| `ERR_PROOF_NOT_REQUIRED` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 |

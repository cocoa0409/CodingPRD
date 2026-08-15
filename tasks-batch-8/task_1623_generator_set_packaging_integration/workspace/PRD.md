# Generator Set Packaging & Integration API — Product Requirements Document

## 1. Introduction

A generator-set packager sits between the engine and alternator manufacturers on one side and the building owner on the other, and its margin lives or dies on coordination. A single package order pulls together a sizing study that proves the selected engine/alternator pair can carry the site's load, an enclosure and fuel-tank configuration that satisfies runtime and ullage rules for the installation jurisdiction, an AHJ permit with its correction cycles, an emissions certificate whose required tier depends on where the unit will sit, a factory load-bank test witnessed under segregation of duties, a crane slot and freight booking, on-site startup with customer training, and an extended-warranty service contract. Each of these workstreams has its own lifecycle, its own acting role, and its own clock-relative deadlines — yet they all hang off one commercial order whose credit exposure must be tracked to the cent.

This document specifies the API for that packaging workflow. It is written for the engineers who will implement the service: it defines the resource model, the dual-dimension order state machine, the calculation rules for sizing, pricing, billing, and refunds, the validation cascade every request passes through, and the optimistic-concurrency guarantees that keep concurrent writers honest. The system enforces segregation of duties throughout — the engineer who records a load-bank test may not accept it, the compliance officer who files a permit may not act as the reviewing authority — because the packager's customers, insurers, and regulators all read these records.

All functionality is mounted under a single URL namespace rooted at `/genset-packaging`. Time itself is a controlled input: the service maintains a logical clock that all date-sensitive rules (permit expiry, dispatch eligibility, contract lapse) read, so that integrators and test harnesses can drive deterministic scenarios.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the named role is not permitted to invoke the requested operation — or when a role-specific ownership rule fails — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows:

- `PlatformAdmin` — packager operations administrator. Manages the customer accounts and the engine/alternator catalogs, creates test bays and crane slots, simulates the external authorities (the AHJ reviewer and the emissions authority), drives the logical clock, and runs contract lapse checks.
- `SalesEngineer` — owns the commercial lifecycle: creates and authorizes orders, cancels orders, approves or rejects sizing studies, and quotes, binds, activates, and cancels service contracts.
- `ApplicationEngineer` — owns the engineering definition: creates and submits sizing studies, creates/locks/unlocks package configurations, and designs, positions, programs, reworks, and verifies paralleling schemes.
- `ComplianceOfficer` — owns the regulatory artifacts: creates, submits, and withdraws permit cases; creates and submits emissions certificate applications. A `ComplianceOfficer` may never act as the reviewing authority on their own filings.
- `TestEngineer` — owns factory testing: schedules, starts, records, and accepts load-bank tests. The engineer who records a test may not accept that same test (see §2.10).
- `LogisticsCoordinator` — owns freight and lift planning: books, dispatches, delivers, and releases shipments.
- `FieldServiceManager` — owns startup commissioning: requests commissioning events, assigns field engineers, and starts and completes startup work.
- `CustomerContact` — the external customer representative, who accepts commissioning on behalf of their own account only.

Role identity is resolved in two distinct ways. When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a `CustomerAccount` compare the resource's foreign-key field to `X-User-ID` — concretely, a `CustomerContact` accepting a commissioning event must present an `X-User-ID` equal to the order's `customer_id`, and any other value is rejected with `ERR_FORBIDDEN_ROLE`. For `PlatformAdmin`, `SalesEngineer`, `ApplicationEngineer`, `ComplianceOfficer`, `TestEngineer`, `LogisticsCoordinator`, and `FieldServiceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for attribution — for example as `recorded_by_user_id` or `accepted_by_user_id` on a `FactoryTest`, or as `assigned_engineer_id` on a `CommissioningEvent` — but does not compare it to any entity's `id` except where an explicit ownership or segregation-of-duties rule says so.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a page returns: it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter says how many items to skip before the page begins and defaults to 0. Unless a more specific rule applies, every list endpoint returns its resources sorted by `created_at` ascending. The `meta` object of every paginated response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All date- and time-sensitive behavior in the system — permit submission and expiry, shipment dispatch eligibility, contract lapse and expiry — reads a single logical clock, never the host wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `PlatformAdmin` advances it by supplying a `to_iso8601` instant through the clock-setting capability; the clock never falls back to wall-clock time on its own. Business dates such as `submitted_on`, `expires_on`, `service_date`, `next_pm_due_date`, and `end_date` are expressed as `YYYY-MM-DD` calendar dates taken from this logical clock, and every comparison in §3 ("before", "on or before", "strictly past") is evaluated against it.

### 2.5. Common Resource Properties

Every resource in the system — `CustomerAccount`, `EngineModel`, `AlternatorModel`, `PackageOrder`, `SizingStudy`, `PackageConfiguration`, `PermitCase`, `EmissionsCertificate`, `ParallelingScheme`, `TestBay`, `FactoryTest`, `CraneSlot`, `Shipment`, `CommissioningEvent`, and `ServiceContract` — carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, generated at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at the value assigned at creation and increments by exactly 1 on every mutation of the resource, including mutations performed by the server itself as a cascade side effect.

The `version` field is the linchpin of the optimistic-concurrency rules in §2.7: clients read a resource, observe its `version`, and later present that observation back when writing against it.

### 2.6. The Order's Dual Posture: Build and Commercial Dimensions

A `PackageOrder` does not have one status; it has two that evolve independently on the same row. The `build_status` dimension tracks the physical pipeline — `SPEC`, `SIZING`, `CONFIGURING`, `PERMITTING`, `TESTING`, `READY_TO_SHIP`, `DELIVERED`, `COMMISSIONED`, `CANCELLED` — while the `commercial_status` dimension tracks the money — `QUOTE`, `AUTHORIZED`, `INVOICED`, `CLOSED`, `REFUNDED`. A new order is born at `build_status` `SPEC` with `commercial_status` `QUOTE`. Terminal postures are `build_status` `COMMISSIONED`, `build_status` `CANCELLED`, `commercial_status` `CLOSED`, and `commercial_status` `REFUNDED`.

Build-dimension advancement is entirely system-driven: the server moves the order forward when the right dependent artifact reaches the right state, and each such move increments the order's `version` by 1. Commercial movement happens through explicit sales actions (authorize, cancel) plus two automatic pivots — the delivery of a shipment turns an `AUTHORIZED` order `INVOICED`, and the acceptance of commissioning turns an `INVOICED` order `CLOSED`. Because the two dimensions are independent, rules in §3 always name the dimension they constrain: an operation gated on build state fails with `ERR_INVALID_BUILD_STATE` (HTTP 409), one gated on commercial state fails with `ERR_INVALID_COMMERCIAL_STATE` (HTTP 409).

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency checks on a parent resource; no other endpoint takes a version field.

Creating a sizing study requires the request to carry `expected_order_version`, holding the `version` of the target `PackageOrder` as the client last observed it. If the order's current `version` has advanced since that observation — for example because another writer created or approved a study against the same order in the meantime — the create is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), preventing the client from building on an order state it has not seen.

Booking a shipment requires the request to carry `expected_crane_slot_version`, holding the `version` of the target `CraneSlot` as the client last observed it. If the slot's current `version` no longer matches — because another booking or a release legitimately changed the slot's `free_hours` in the interim — the booking is rejected with `ERR_STALE_CRANE_SLOT_VERSION` (HTTP 412), so capacity decisions are never made against a stale view of the slot.

### 2.8. Nested Validation Order and Resource Lookup

Requests that reference several resources at once — path identifiers plus foreign keys in the payload — are validated in a fixed order, and the first failing check produces the response. Authentication comes first (headers present, role recognized), then authorization (role permitted for the endpoint, ownership rules satisfied), then existence (every referenced id is looked up; path-template identifiers are validated left-to-right so the leftmost missing id determines the `ERR_NOT_FOUND` (HTTP 404)), then optimistic-concurrency version matching, then state-machine from-state checks, then business rules in the order: emissions and locale safety, segregation of duties, capacity and overlap constraints, clock-relative temporal windows, cross-entity referential requirements, and finally fiscal gates such as the credit check. A payload that is malformed in its own right — a missing required field, an unknown enum member, an empty `readings` array, non-positive quantities, or a `start_hour` not strictly before `end_hour` — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Money, Energy, and Rounding Conventions

Monetary values are integer cents end to end — catalog `list_price_cents` figures, `enclosure_price_cents`, `amount_cents`, `freight_charge_cents`, permit fees, and computed totals are all whole cents. Whenever a multiplication would produce a fractional cent, the result is rounded half-up to the nearest whole cent; the per-rule rounding instructions in §3 state exactly where this happens. Electrical energy is handled at one decimal place of a kilowatt-hour, again rounding half-up, and measured power factor at four decimal places, half-up. Required capacity in a sizing study is carried at one decimal place of kVA, half-up. Hours of crane occupancy are decimal values at half-hour granularity and are not rounded.

### 2.10. Cascading Reconciliation and Segregation of Duties

The packager's records form a dependency web, and the server keeps that web consistent automatically. When an artifact deep in the web reaches a milestone — a study is approved, a configuration locks, a permit is submitted, a certificate is issued, a test is accepted, a shipment is delivered, a commissioning is accepted — the server advances the owning order's `build_status` or `commercial_status` itself, without any client call against the order, incrementing the order's `version` each time. The same principle runs in reverse: cancelling an order, or recording a failed load-bank test, unwinds dependent artifacts (configurations, permits, certificates, shipments, commissioning events, service contracts) through an explicit cascade described in §3.8 and §3.7, restoring any reserved capacity those artifacts held. Every resource touched by a cascade has its own `updated_at` refreshed and `version` incremented.

Two segregation-of-duties rules are enforced on operator identity. A factory test must be accepted by a `TestEngineer` whose `X-User-ID` differs from the `recorded_by_user_id` who recorded its readings; an attempt by the same operator is rejected with `ERR_SOD_VIOLATION` (HTTP 403). And the regulatory filings are split so that the `ComplianceOfficer` who prepares and submits a permit or certificate is never the authority that approves, corrects, rejects, issues, or expires it — those authority actions belong to `PlatformAdmin`, which simulates the external AHJ and emissions authority.

## 3. Business Logic & Workflows

### 3.1. Commercial Onboarding: Accounts, Catalogs, and the Order

Everything begins with the packager's book of business. A `PlatformAdmin` registers each customer as a `CustomerAccount` with a legal `name`, a `credit_limit_cents` ceiling on outstanding commitment (which may be zero but never negative), and a `primary_locale` naming the home jurisdiction — one of `US_CA`, `US_TX`, or `DE`. An account's `status` starts `ACTIVE` and may be set `SUSPENDED`; its `credit_utilized_cents` starts at 0 and thereafter tracks, exactly and at all times, the sum of `committed_amount_cents` across that customer's orders whose `commercial_status` is either `AUTHORIZED` or `INVOICED`. Authorization adds to this figure and cancellation subtracts it back out, so an authorize-then-cancel round trip returns utilization to its pre-authorize value.

The equipment catalog is likewise administrator-maintained. An `EngineModel` captures a `model_code`, the `manufacturer` name, a positive `rated_kw` nameplate standby rating, a positive `fuel_burn_gph_at_75` consumption in gallons per hour at three-quarters load, the `emissions_tier_capability` marking the highest tier that engine is certified for (`TIER_2`, `EPA_TIER_4`, `STAGE_V`, or `TIER_4_FINAL_CARB`), and a non-negative `list_price_cents`; catalog posture is `status`, beginning `ACTIVE` and later possibly `DISCONTINUED`. An `AlternatorModel` carries its own `model_code`, a positive `rated_kva`, an `efficiency_pct` that must be greater than zero and at most 100, and a non-negative `list_price_cents`.

With an account and catalog in place, a `SalesEngineer` opens a `PackageOrder` by naming the `customer_id` of the ordering account and three classifiers that drive nearly every downstream rule: the `site_locale` of the installation jurisdiction (`US_CA`, `US_TX`, or `DE`), the `occupancy_type` of the building (`STANDARD` or `HOSPITAL` — a hospital forces a 48-hour runtime floor), and the duty `application` (`STANDBY` or `PRIME` — a prime application forces an hour-log requirement on its emissions filing). The order arrives at `SPEC` / `QUOTE` with `authorized_amount_cents`, `committed_amount_cents`, `refunded_amount_cents`, `restocking_fee_cents`, and `freight_charge_cents` all zero.

Authorization is the commercial hinge. A `SalesEngineer` authorizes the order by supplying `amount_cents` (the committed contract value) and `freight_charge_cents` (the freight quote, which is stored verbatim and never discounted). Three gates are checked, in the priority order of §2.8: at least one sizing study for the order must already be `APPROVED` or the request fails with `ERR_SIZING_NOT_APPROVED`; the customer's `status` must be `ACTIVE` or it fails with `ERR_CUSTOMER_SUSPENDED`; and the customer's `credit_utilized_cents` plus the new `amount_cents` must not exceed `credit_limit_cents`, or the request fails with `ERR_CREDIT_LIMIT_EXCEEDED`. On success the order's `commercial_status` becomes `AUTHORIZED`, `authorized_amount_cents` and `committed_amount_cents` are both set to `amount_cents`, the supplied `freight_charge_cents` is stored, the customer's `credit_utilized_cents` grows by `amount_cents`, and the order's `version` increments.

### 3.2. Sizing the Unit: Load Studies and the Approval Gate

An `ApplicationEngineer` builds the engineering case with a `SizingStudy`. The create call names the `order_id` it sizes and the candidate equipment by `engine_model_id` and `alternator_model_id`, describes the load as a `load_steps` array — each entry a `description`, a `kva`, and a `duty` of either `CONTINUOUS` or `STANDBY_START` — and supplies `largest_motor_kva` for the largest single motor, the `starting_method` (`DOL` for direct-on-line or `SOFT_START`), the site's `altitude_m` (zero or greater) and `ambient_c` design temperature (from −40 up to and including 60 Celsius), and the sizing `method` variant, either `NAMEPLATE_SUM` or `DERATED_STOCHASTIC`. Because sizing commits the order's engineering baseline, the create also carries `expected_order_version` per §2.7, and creating the study increments the parent order's `version` by 1.

The `required_kva` is computed at creation. First, the running load `running_kva` is the sum of `kva` over exactly those `load_steps` whose `duty` is `CONTINUOUS`; steps marked `STANDBY_START` never enter this sum. The starting multiplier is 3.0 when `starting_method` is `DOL` and 1.6 when `starting_method` is `SOFT_START`, and the starting load is the running load with the largest motor removed and then re-added at the multiplied value — that is, `running_kva` minus `largest_motor_kva` plus `largest_motor_kva` times the multiplier. The base requirement is the larger of the running load and the starting load. Under `NAMEPLATE_SUM`, that base, rounded half-up to one decimal place, is the `required_kva`. Under `DERATED_STOCHASTIC`, two derates apply first: the altitude derate is 0.01 for every full 500-meter band by which `altitude_m` exceeds 1000 meters, and the ambient derate is 0.02 for every full 5-degree band by which `ambient_c` exceeds 40 degrees. The derate factor is one minus both derates, floored at 0.70; the base is divided by that factor and then multiplied by the 1.10 stochastic reserve, and the result, rounded half-up to one decimal place, is the `required_kva`. Identical inputs therefore always yield a strictly larger `required_kva` under `DERATED_STOCHASTIC` whenever any derate applies.

A study moves `DRAFT` → `SUBMITTED` when the `ApplicationEngineer` submits it; the only gate is that the owning order's `build_status` must not be `CANCELLED` (else `ERR_INVALID_BUILD_STATE`). Approval belongs to the `SalesEngineer` and carries the capacity gate, checked with the error `ERR_CAPACITY_UNDERSIZED`: the engine's `rated_kw` divided by 0.8 must be at least the study's `required_kva`, and the alternator's `rated_kva` must be at least the `required_kva`. On approval, any other study for the same order that is currently `APPROVED` is flipped to `SUPERSEDED` with its `superseded_by_id` set to the newly approved study's `id` (a study not yet superseded carries `superseded_by_id` null), and if this is the order's first approval the order's `build_status` moves `SPEC` → `SIZING`, incrementing the order's `version`; the study's own `version` increments as well. A `SalesEngineer` may instead reject a `SUBMITTED` study with a `reason`, which is stored as `rejection_reason`. Rejection is not the end: a `REJECTED` study may be submitted again (looping back to `SUBMITTED` under the same not-cancelled gate), which clears `rejection_reason` to null. Studies may be browsed filtered by `order_id`, `engine_model_id`, `alternator_model_id`, or `superseded_by_id`.

### 3.3. Package Configuration: Enclosure, Fuel, and the Price Lock

Once a study is approved, the `ApplicationEngineer` shapes the physical package as a `PackageConfiguration`, naming the owning `order_id` and the `sizing_study_id` of the approved study it realizes, then choosing the `enclosure_type` (`OPEN`, `WEATHERPROOF`, or `SOUND_ATTENUATED`) with its non-negative `enclosure_price_cents`, and the `fuel_tank_gallons` base capacity, which must be a positive whole number of gallons.

Three figures are computed immediately at creation and re-evaluated at lock. The ullage reserve depends on the order's `site_locale`: for `US_CA` the tank's unusable fraction is 12 percent, and for any other locale it is 10 percent, so `usable_gallons` is the tank size scaled by one minus that fraction. The `tank_price_cents` is the tank size in gallons multiplied by 150 cents per gallon. The engine's `fuel_burn_gph_at_75`, taken from the approved study's engine, divides into `usable_gallons` to give `runtime_hours`, rounded half-up to two decimal places. The runtime floor `min_runtime_hours` is 48 when the order's `occupancy_type` is `HOSPITAL` and 24 otherwise.

Locking is the point of no return for configuration editing. The `ApplicationEngineer` may lock a `DRAFT` configuration only when the order's `commercial_status` is `AUTHORIZED` (otherwise `ERR_INVALID_COMMERCIAL_STATE`), the linked study is `APPROVED` (otherwise `ERR_SIZING_NOT_APPROVED`), and `runtime_hours` is at least `min_runtime_hours` — an exactly-equal runtime passes, and a shortfall is rejected with `ERR_FUEL_RUNTIME_INSUFFICIENT`. Locking recomputes and persists the order's `total_price_cents` and `discount_tier`, moves the order's `build_status` `SIZING` → `CONFIGURING` when this is the order's first locked configuration (incrementing the order's `version`), and increments the configuration's `version`.

The order total is assembled in a pinned order that breaks the circularity between tier and total. The equipment subtotal is the engine's `list_price_cents` plus the alternator's `list_price_cents`, both taken from the approved study; the options subtotal is `enclosure_price_cents` plus `tank_price_cents`; their sum is the pre-discount subtotal. The `discount_tier` is keyed on that pre-discount subtotal, never on the discounted total: a pre-discount subtotal of at least 100000000 cents earns `TIER_12` at a 12 percent rate, a subtotal of at least 50000000 cents (but below the higher threshold) earns `TIER_8` at 8 percent, and anything lower earns `NONE` at zero. The discount itself is the pre-discount subtotal times the tier rate, rounded half-up to whole cents, and it applies to equipment and options only — freight is never discounted. The order's `total_price_cents` is then the pre-discount subtotal minus the discount plus the order's stored `freight_charge_cents`.

A `LOCKED` configuration can revert to `DRAFT` through unlocking, but only while no permit case for it sits in `SUBMITTED` or `APPROVED` (a live permit blocks the revert with `ERR_PERMIT_STATE_INVALID`); unlocking increments the configuration's `version`. Once a factory test is accepted for the configuration it moves `LOCKED` → `RELEASED` automatically. Configurations may be listed filtered by `order_id` or `sizing_study_id`.

### 3.4. Permitting: The AHJ Filing and Correction Cycle

The `ComplianceOfficer` opens a `PermitCase` against an order and configuration by supplying `order_id` and `configuration_id`. At creation the case copies the order's `site_locale` into its own `jurisdiction_locale`, and the fee schedule is derived from that jurisdiction: the `base_fee_cents` is 250000 for `US_CA`, 175000 for `DE`, and 100000 otherwise, and the `resubmission_fee_cents` is half the base fee rounded half-up to whole cents. The case starts in `DRAFT` with `total_fees_paid_cents` at 0, `revision_count` at 0, and `submitted_on` and `expires_on` both null.

Submitting from `DRAFT` requires the configuration to be `LOCKED` (else `ERR_CONFIG_STATE_INVALID`). A first submission stamps `submitted_on` with the current logical-clock date, sets `expires_on` to `submitted_on` plus the jurisdiction's expiry window — 60 days for `US_CA`, 90 days for `DE`, 45 days otherwise — and adds the `base_fee_cents` into `total_fees_paid_cents`. When this is the order's first submitted permit, the order's `build_status` moves `CONFIGURING` → `PERMITTING`, incrementing the order's `version`; the permit's `version` increments too.

The authority side of the desk is played by `PlatformAdmin`. From `SUBMITTED`, the authority may request corrections — the `SUBMITTED` → `CORRECTION_REQUESTED` move — or approve it, the `SUBMITTED` → `APPROVED` move; approval advances the order `PERMITTING` → `TESTING` when an emissions certificate is already `ISSUED` for the order, and increments the permit's `version`. A correction cycle is resubmitted by the `ComplianceOfficer`: resubmission from `CORRECTION_REQUESTED` is allowed only while the current logical-clock date is on or before `expires_on` — after that it is rejected with `ERR_PERMIT_EXPIRED` — and each such cycle increments `revision_count` by 1, restamps `submitted_on` and `expires_on` from the current clock, and adds the `resubmission_fee_cents` into `total_fees_paid_cents`. The authority may also expire a `SUBMITTED` case via an expiry check, which succeeds only when the logical-clock date is strictly greater than `expires_on` — a date equal to `expires_on` does not expire, and the check then fails with `ERR_PERMIT_NOT_EXPIRED`; a successful check moves the case to `EXPIRED`.

Withdrawal is available to the `ComplianceOfficer` from `DRAFT`, `SUBMITTED`, or `CORRECTION_REQUESTED`, moving the case to `WITHDRAWN`, and every withdrawal voids that configuration's emissions certificate if it is still in `APP_DRAFT`, `SUBMITTED`, or `REJECTED` — a cascade examined further in §3.5. Permits may be listed filtered by `order_id` or `configuration_id`.

### 3.5. Emissions Certification: Tier by Locale, Hour Logs by Duty

In parallel with permitting, the `ComplianceOfficer` files an `EmissionsCertificate` application naming the `order_id` and `configuration_id`, optionally flagging `hour_log_attached` (which defaults to false when omitted). Two facts are derived at creation. The `required_tier` follows the order's `site_locale`: `US_CA` demands `TIER_4_FINAL_CARB`, `DE` demands `STAGE_V`, and anything else demands `EPA_TIER_4`. The `engine_tier` is the `emissions_tier_capability` of the engine on the linked sizing study. The boolean `requires_hour_log` is true exactly when the order's `application` is `PRIME`.

Submission — by the `ComplianceOfficer`, from `APP_DRAFT`, and again from `REJECTED` after an authority rejection — requires the configuration to be `LOCKED` or `RELEASED` (otherwise `ERR_CONFIG_STATE_INVALID`), and when `requires_hour_log` is true the submission must carry `hour_log_attached` as true, else it is rejected with `ERR_HOUR_LOG_REQUIRED`; the submit call accepts an `hour_log_attached` value so the log can be attached at submit time. Resubmission after rejection also clears `rejection_reason` to null. Either way the certificate's `version` increments.

The authority (`PlatformAdmin`) then issues or rejects. Issuance applies the tier ladder — `TIER_2` ranks 1, `EPA_TIER_4` ranks 2, `STAGE_V` ranks 3, `TIER_4_FINAL_CARB` ranks 4 — and the engine's tier rank must be at least the required tier's rank, or issuance fails with `ERR_EMISSIONS_TIER_INSUFFICIENT`. When issuance succeeds and a permit for the order is already `APPROVED`, the order's `build_status` moves `PERMITTING` → `TESTING`; note the symmetric trigger on the permit side in §3.4 — the build advances on whichever of the two events completes the pair, and the certificate's `version` increments. Rejection stores the authority's `reason` as `rejection_reason`. Any withdrawal of the configuration's permit — whether filed by the `ComplianceOfficer` or forced by an order cancellation — voids a certificate still sitting in `APP_DRAFT`, `SUBMITTED`, or `REJECTED`, moving it to `VOIDED`. Certificates may be listed filtered by `order_id` or `configuration_id`.

### 3.6. Paralleling and Controls Programming

Units that must sync with the utility or with each other get a `ParallelingScheme`, created by an `ApplicationEngineer` with the `order_id`, a `sync_mode` of `ISOLATED`, `PARALLEL_WITH_UTILITY`, or `MULTI_UNIT`, and a `max_units` count between 1 and 8 inclusive. The scheme starts in `DESIGN` with an empty `positions` array and `control_program_version` null.

While in `DESIGN`, the engineer appends unit positions one at a time by supplying each position's `kw_rating`; the system assigns `position_no` values sequentially starting from 1, and each entry sits in `positions` as a `position_no`/`kw_rating` pair. The append is rejected with `ERR_PARALLEL_CAPACITY_EXCEEDED` when it would push the position count beyond `max_units`.

Programming the controls — the `DESIGN` → `PROGRAMMED` transition, performed by the `ApplicationEngineer` with a `program_version` input — requires the scheme to hold at least one position and no more than `max_units`: an empty `positions` array is rejected with `ERR_INVALID_REQUEST`, while a count above `max_units` is rejected with `ERR_PARALLEL_CAPACITY_EXCEEDED`. On success the supplied `program_version` is stored as `control_program_version` and the scheme's `version` increments. If the program is found wanting, a rework call sends the scheme from `PROGRAMMED` back to `DESIGN`, clearing `control_program_version` to null. Finally, verification moves a `PROGRAMMED` scheme to the terminal `VERIFIED` state, but only once the order's `build_status` has reached `TESTING`, `READY_TO_SHIP`, `DELIVERED`, or `COMMISSIONED` — any earlier build is rejected with `ERR_INVALID_BUILD_STATE`. Schemes may be listed filtered by `order_id`.

### 3.7. The Factory Witness Test: Load Bank, Billing, and Acceptance

The packager's proof point is the load-bank test. `PlatformAdmin` maintains the `TestBay` fleet — each bay has a `bay_code`, a positive `max_kw` load-bank capacity, and a `status` of `ACTIVE` or `OUT_OF_SERVICE` (defaulting to `ACTIVE`). A `TestEngineer` schedules a `FactoryTest` by naming the `order_id`, the `configuration_id` under test, the `bay_id`, a `service_date`, and a half-open reservation window from `start_hour` up to but not including `end_hour` (start must be at least 0 and strictly before end; end may be at most 24). For a retest after a failure, the optional `retest_of_id` links the new test to the prior `FAILED` test of the same order; a `retest_of_id` pointing at anything else is rejected with `ERR_INVALID_REQUEST`.

Creation is gated by several checks, applied in the §2.8 order. The configuration must exist under the named order and be `LOCKED` or `RELEASED` (otherwise `ERR_CONFIG_STATE_INVALID`), and an `EmissionsCertificate` for the order must already be `ISSUED` — this is the cross-entity precondition, and a certificate-less order fails with `ERR_CERT_NOT_ISSUED`. Notably there is no order `build_status` gate on creation: the issued-certificate rule is the gate, which is exactly what permits a post-acceptance retest to be scheduled while the order sits at `READY_TO_SHIP`. The bay must be `ACTIVE`, and the requested window must not intersect any existing non-terminal test's window on the same bay and date — windows are half-open, so a test ending at hour 12 and another starting at hour 12 do not conflict — with violations rejected as `ERR_TEST_BAY_OVERLAP`. The test is born `SCHEDULED` with an empty `readings` array.

Starting moves the test `SCHEDULED` → `IN_PROGRESS`. Recording is the heavy step: the `TestEngineer` supplies the `readings` array, where each step is a `kw`, an `hours` duration, and a `power_factor`. The array must be non-empty and every step's `hours` positive, or the record is rejected with `ERR_INVALID_REQUEST`. Billing and energy are computed with a pinned rounding order — round per step first, then sum, never sum-then-round. Each step's raw energy is its `kw` times its `hours`, rounded half-up to one decimal place of a kilowatt-hour; the `total_kwh` is the sum of those rounded per-step energies, itself rounded half-up to one decimal place. Each step's charge is its rounded step energy multiplied by 32 cents per kilowatt-hour, rounded half-up to whole cents, and the `invoice_total_cents` is the sum of those per-step charges. The `measured_avg_pf` is the hours-weighted mean power factor — the sum over steps of each `power_factor` times its `hours`, divided by the sum of `hours` — rounded half-up to four decimal places. The `verdict` is `PASS` if every step's `power_factor` is at least 0.80 (0.80 exactly passes; 0.79 fails) and `FAIL` otherwise, and it stays null until results are recorded. Recording stamps `recorded_by_user_id` with the recorder's `X-User-ID` and increments the test's `version`, and the test lands in `PASSED` or `FAILED` according to the verdict.

A `FAIL` has teeth. The order's `build_status` regresses — `TESTING` → `CONFIGURING`, or `READY_TO_SHIP` → `CONFIGURING` if the failure came from a post-acceptance retest — incrementing the order's `version`, and every `BOOKED` shipment for the order is released, returning its crane occupancy to the slot exactly as §3.8 describes. The failed row itself never leaves `FAILED`; the follow-up is a new test created with `retest_of_id` pointing back at it.

Acceptance is segregated: a `TestEngineer` accepts a `PASSED` test, but the accepting `X-User-ID` must differ from `recorded_by_user_id`, or the call fails with `ERR_SOD_VIOLATION`. Acceptance stamps `accepted_by_user_id`, moves the test to the terminal `ACCEPTED` state, and cascades outward: the order's `build_status` goes `TESTING` → `READY_TO_SHIP` with its `version` incremented, and the configuration under test goes `LOCKED` → `RELEASED`. Tests may be listed filtered by `order_id`, `configuration_id`, `bay_id`, or `retest_of_id`.

### 3.8. Freight, the Crane Window, and Cancellation's Long Shadow

Lifting a packaged genset onto a truck takes a crane, and crane time is a scarce, explicitly accounted resource. A `PlatformAdmin` opens a `CraneSlot` for a `service_date` with a `window_start_hour` and `window_end_hour` bounding the working window (start at least 0 and strictly before end; end at most 24), a `buffer_hours` setup allowance appended to every booking's occupancy (defaulting to 0.5), and a `status` of `OPEN` or `CLOSED` (defaulting to `OPEN`). The slot tracks `reserved_hours` — the sum, over its active bookings, of each booking's `lift_hours` plus the slot's `buffer_hours` — and `free_hours`, the window length minus the reserved figure; the invariant `free_hours` plus `reserved_hours` always equals `window_end_hour` minus `window_start_hour`.

A `LogisticsCoordinator` books a `Shipment` against a slot by supplying the `order_id`, the `crane_slot_id`, the `lift_start_hour` within the window, the positive `lift_hours` duration, the positive `gross_weight_kg`, the `freight_class` (`STANDARD`, `OVERSIZE`, or `HEAVY_HAUL`), and — per §2.7 — the `expected_crane_slot_version`. Booking requires the order's `build_status` to be `READY_TO_SHIP` (else `ERR_INVALID_BUILD_STATE`). The booking's occupancy is the half-open interval from `lift_start_hour` to `lift_start_hour` plus `lift_hours` plus the slot's `buffer_hours`; it may not intersect any other booking's occupancy on the same slot, though mere adjacency — one occupancy ending exactly where another begins — does not conflict. An overlap, or an occupancy that would push past the window, is rejected with `ERR_CRANE_WINDOW_OVERLAP`. On success the shipment is `BOOKED`, the slot's `reserved_hours` grows by `lift_hours` plus `buffer_hours`, `free_hours` is recomputed, and the slot's `version` increments.

Dispatch moves a `BOOKED` shipment to `DISPATCHED`, but only once the logical-clock date has reached the slot's `service_date` — an earlier dispatch is rejected with `ERR_SHIPMENT_DATE_NOT_REACHED`. Delivery moves `DISPATCHED` → `DELIVERED` and lands two cascades on the order: `build_status` `READY_TO_SHIP` → `DELIVERED`, and, if the order's `commercial_status` is currently `AUTHORIZED`, `AUTHORIZED` → `INVOICED`. A `BOOKED` shipment may instead be released by the `LogisticsCoordinator`, moving it to `RELEASED` and returning its occupancy — the slot's `reserved_hours` falls by `lift_hours` plus `buffer_hours`, `free_hours` is recomputed, and the slot's `version` increments. The same release happens automatically, with the same occupancy accounting, when an order cancellation or a failed factory test forces every `BOOKED` shipment on the order into `RELEASED`. Shipments may be listed filtered by `order_id` or `crane_slot_id`.

Cancelling the order itself is the workflow's wrecking ball, swung by a `SalesEngineer`. The one gate is that `build_status` must not already be `COMMISSIONED` or `CANCELLED` — otherwise `ERR_INVALID_BUILD_STATE`. The cascade then runs in hops. Hop 1 cancels every configuration of the order still in `DRAFT`, `LOCKED`, or `RELEASED`. Hop 2 follows from hop 1: each cancelled configuration's permit case in `DRAFT`, `SUBMITTED`, or `CORRECTION_REQUESTED` moves to `WITHDRAWN` — and, for a configuration with no live permit at all, that configuration's certificate in `APP_DRAFT`, `SUBMITTED`, or `REJECTED` is voided directly at this hop. Hop 3 follows from hop 2: each permit withdrawal voids that configuration's certificate in `APP_DRAFT`, `SUBMITTED`, or `REJECTED`, moving it to `VOIDED`. Independently of the hops, every `BOOKED` shipment on the order is released with crane occupancy returned as above, every commissioning event in `REQUESTED`, `ASSIGNED`, or `IN_PROGRESS` moves to `CANCELLED`, and every service contract in `QUOTED` or `BOUND` moves to `CANCELLED`.

The money unwinds too. If the order's `commercial_status` is `AUTHORIZED` or `INVOICED`, a refund is computed: the restocking fee is zero when the order was still at `SPEC` or `SIZING` at cancel time, and otherwise it is 10 percent of `committed_amount_cents` rounded half-up to whole cents; `refunded_amount_cents` is the committed amount minus that fee, the fee itself is recorded as `restocking_fee_cents`, `commercial_status` becomes `REFUNDED`, the customer's `credit_utilized_cents` falls by `committed_amount_cents`, and `committed_amount_cents` drops to 0. The order's `version` increments once for the cancellation.

### 3.9. Startup Commissioning and the Service Contract

After delivery, a `FieldServiceManager` requests a `CommissioningEvent` by naming the `order_id`, the `shipment_id` of the delivery this startup follows, and a `service_date`. Creation requires the order's `build_status` to be `DELIVERED` (otherwise `ERR_INVALID_BUILD_STATE`); the event starts at `REQUESTED` with `assigned_engineer_id` null.

Assignment puts a named engineer on the job: the manager supplies an `engineer_id`, which is stored as `assigned_engineer_id`. The capacity rule guards an engineer's day: the count of that engineer's commissioning events on the same `service_date` whose status is `ASSIGNED`, `IN_PROGRESS`, or `COMPLETED` must be below 2 before the assignment — so a second same-day assignment is allowed and a third is rejected with `ERR_ENGINEER_DAY_CAPACITY_EXCEEDED`. Reassignment is atomic: calling assign again on an `ASSIGNED` event with a different `engineer_id` passes the event through `REQUESTED` and immediately back to `ASSIGNED` under the new engineer within the same call, and the capacity check applies to the new engineer. Starting work moves `ASSIGNED` → `IN_PROGRESS`.

Completion records the deliverables — `training_hours` and the `checklist_completed` flag — and is gated three ways, all under `ERR_TRAINING_INCOMPLETE` where training is concerned: the linked shipment must be `DELIVERED` (else `ERR_SHIPMENT_NOT_DELIVERED`), `checklist_completed` must be true, and `training_hours` must be at least 2.0. On success both values are persisted and the event moves `IN_PROGRESS` → `COMPLETED`. The final word belongs to the customer: a `CustomerContact` accepts a `COMPLETED` event, and per §2.1 their `X-User-ID` must equal the order's `customer_id` or the call is rejected with `ERR_FORBIDDEN_ROLE`. Acceptance moves the event to the terminal `ACCEPTED` state and closes the order out — `build_status` `DELIVERED` → `COMMISSIONED`, and, if `commercial_status` is currently `INVOICED`, `INVOICED` → `CLOSED`. Events may be listed filtered by `order_id` or `shipment_id`.

The last artifact of the pipeline is the `ServiceContract`, quoted by a `SalesEngineer` with the covered `order_id`, a `pricing_variant` of `FLAT_RISK_PREMIUM` or `TIME_AND_MATERIALS_EV`, a `term_years` between 1 and 10 inclusive, the positive `nameplate_kw` pricing basis, and an optional `pm_interval_days` preventive-maintenance interval that defaults to 90 and must be at least 30. Pricing is computed at creation and depends on the variant. Under `FLAT_RISK_PREMIUM`, a locale multiplier applies — 1.25 for `US_CA`, 1.10 for `DE`, and 1.0 otherwise — and the `annual_price_cents` is 1200 cents per kW-year times `nameplate_kw` times that multiplier, rounded half-up to whole cents; the `total_price_cents` is the annual figure times `term_years`. Under `TIME_AND_MATERIALS_EV`, each preventive visit is priced as 6 hours of labor at 15000 cents per hour plus a 40000-cent parts allowance; the annual figure is that per-visit price times 4 visits per year times the 1.15 risk factor, rounded half-up to whole cents, and again `total_price_cents` is the annual figure times `term_years`. The contract is born `QUOTED` with `next_pm_due_date` and `end_date` both null.

Binding — `QUOTED` → `BOUND` — requires only that the order's `build_status` is not `CANCELLED` (else `ERR_INVALID_BUILD_STATE`). Activation — `BOUND` → `ACTIVE` — requires that a commissioning event for the order has reached `ACCEPTED` (else `ERR_COMMISSIONING_NOT_ACCEPTED`), and it stamps the schedule from the logical clock: `next_pm_due_date` becomes the current date plus `pm_interval_days`, and `end_date` becomes the current date plus `term_years` times 365 days. From `ACTIVE`, a `PlatformAdmin` runs the lapse check: when the logical-clock date is strictly past `next_pm_due_date` but not past `end_date`, the contract moves to `LAPSED`; when the date is strictly past `end_date`, it moves to `EXPIRED`; when neither condition holds, the check is rejected with `ERR_CONTRACT_NOT_LAPSABLE`. A contract in `QUOTED` or `BOUND` may be cancelled outright by a `SalesEngineer`, and the order-cancellation cascade of §3.8 cancels any contract still in `QUOTED` or `BOUND` without touching `ACTIVE` or later states. Contracts may be listed filtered by `order_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — every state transition, assignment, and record action — return `200 OK`. The one exception to the resource pattern is the logical-clock capability, which returns `200 OK`. Request payloads and success payloads are not repeated here; §3's narratives define them.

Path templates use one identifier variable per resource: `customerId` for a customer account, `engineModelId` and `alternatorModelId` for catalog models, `orderId` for a package order, `studyId` for a sizing study, `configurationId` for a package configuration, `permitId` for a permit case, `certificateId` for an emissions certificate, `schemeId` for a paralleling scheme, `testBayId` for a test bay, `testId` for a factory test, `craneSlotId` for a crane slot, `shipmentId` for a shipment, `eventId` for a commissioning event, and `contractId` for a service contract. Each binds the `id` of the named resource; an id that does not resolve is rejected per §2.8 with `ERR_NOT_FOUND`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/genset-packaging/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | PlatformAdmin |
| POST | `/genset-packaging/customers` | Create a customer account | PlatformAdmin |
| GET | `/genset-packaging/customers/{customerId}` | Get a customer account | Any |
| POST | `/genset-packaging/engine-models` | Create an engine catalog model | PlatformAdmin |
| GET | `/genset-packaging/engine-models/{engineModelId}` | Get an engine model | Any |
| POST | `/genset-packaging/alternator-models` | Create an alternator catalog model | PlatformAdmin |
| GET | `/genset-packaging/alternator-models/{alternatorModelId}` | Get an alternator model | Any |
| POST | `/genset-packaging/orders` | Create a package order (SPEC / QUOTE) | SalesEngineer |
| GET | `/genset-packaging/orders/{orderId}` | Get an order | Any |
| GET | `/genset-packaging/orders` | List orders (paginated, filterable) | Any |
| POST | `/genset-packaging/orders/{orderId}/authorize` | Authorize the order commercially with credit check | SalesEngineer |
| POST | `/genset-packaging/orders/{orderId}/cancel` | Cancel the order with full cascade and refund | SalesEngineer |
| POST | `/genset-packaging/sizing-studies` | Create a sizing study (OCC-guarded on order version) | ApplicationEngineer |
| GET | `/genset-packaging/sizing-studies/{studyId}` | Get a sizing study | Any |
| GET | `/genset-packaging/sizing-studies` | List sizing studies (paginated, filterable) | Any |
| POST | `/genset-packaging/sizing-studies/{studyId}/submit` | Submit a study for approval | ApplicationEngineer |
| POST | `/genset-packaging/sizing-studies/{studyId}/approve` | Approve a study; capacity gate; supersedes prior approval | SalesEngineer |
| POST | `/genset-packaging/sizing-studies/{studyId}/reject` | Reject a submitted study | SalesEngineer |
| POST | `/genset-packaging/configurations` | Create a package configuration | ApplicationEngineer |
| GET | `/genset-packaging/configurations/{configurationId}` | Get a configuration | Any |
| GET | `/genset-packaging/configurations` | List configurations (paginated, filterable) | Any |
| POST | `/genset-packaging/configurations/{configurationId}/lock` | Lock a configuration; runtime gate; prices the order | ApplicationEngineer |
| POST | `/genset-packaging/configurations/{configurationId}/unlock` | Unlock a LOCKED configuration when no live permit exists | ApplicationEngineer |
| POST | `/genset-packaging/permit-cases` | Create a permit case for a configuration | ComplianceOfficer |
| GET | `/genset-packaging/permit-cases/{permitId}` | Get a permit case | Any |
| GET | `/genset-packaging/permit-cases` | List permit cases (paginated, filterable) | Any |
| POST | `/genset-packaging/permit-cases/{permitId}/submit` | Submit or resubmit a permit to the AHJ | ComplianceOfficer |
| POST | `/genset-packaging/permit-cases/{permitId}/request-correction` | AHJ requests corrections | PlatformAdmin |
| POST | `/genset-packaging/permit-cases/{permitId}/approve-ahj` | AHJ approves the permit | PlatformAdmin |
| POST | `/genset-packaging/permit-cases/{permitId}/withdraw` | Withdraw a permit; voids the linked certificate | ComplianceOfficer |
| POST | `/genset-packaging/permit-cases/{permitId}/expire-check` | Expire a SUBMITTED permit past its expiry date | PlatformAdmin |
| POST | `/genset-packaging/emissions-certificates` | Create an emissions certificate application | ComplianceOfficer |
| GET | `/genset-packaging/emissions-certificates/{certificateId}` | Get an emissions certificate | Any |
| GET | `/genset-packaging/emissions-certificates` | List emissions certificates (paginated, filterable) | Any |
| POST | `/genset-packaging/emissions-certificates/{certificateId}/submit` | Submit or resubmit a certificate application | ComplianceOfficer |
| POST | `/genset-packaging/emissions-certificates/{certificateId}/issue` | Authority issues the certificate | PlatformAdmin |
| POST | `/genset-packaging/emissions-certificates/{certificateId}/reject` | Authority rejects the application | PlatformAdmin |
| POST | `/genset-packaging/paralleling-schemes` | Create a paralleling scheme | ApplicationEngineer |
| GET | `/genset-packaging/paralleling-schemes/{schemeId}` | Get a paralleling scheme | Any |
| GET | `/genset-packaging/paralleling-schemes` | List paralleling schemes (paginated, filterable) | Any |
| POST | `/genset-packaging/paralleling-schemes/{schemeId}/positions` | Append a unit position | ApplicationEngineer |
| POST | `/genset-packaging/paralleling-schemes/{schemeId}/program` | Program the scheme's controls | ApplicationEngineer |
| POST | `/genset-packaging/paralleling-schemes/{schemeId}/rework` | Send a programmed scheme back to design | ApplicationEngineer |
| POST | `/genset-packaging/paralleling-schemes/{schemeId}/verify` | Verify a programmed scheme | ApplicationEngineer |
| POST | `/genset-packaging/test-bays` | Create a test bay | PlatformAdmin |
| GET | `/genset-packaging/test-bays/{testBayId}` | Get a test bay | Any |
| POST | `/genset-packaging/factory-tests` | Schedule a factory load-bank test | TestEngineer |
| GET | `/genset-packaging/factory-tests/{testId}` | Get a factory test | Any |
| GET | `/genset-packaging/factory-tests` | List factory tests (paginated, filterable) | Any |
| POST | `/genset-packaging/factory-tests/{testId}/start` | Start a scheduled test | TestEngineer |
| POST | `/genset-packaging/factory-tests/{testId}/record` | Record load-bank readings; compute verdict and billing | TestEngineer |
| POST | `/genset-packaging/factory-tests/{testId}/accept` | Accept a PASSED test (segregation of duties) | TestEngineer |
| POST | `/genset-packaging/crane-slots` | Create a crane service slot | PlatformAdmin |
| GET | `/genset-packaging/crane-slots/{craneSlotId}` | Get a crane slot | Any |
| POST | `/genset-packaging/shipments` | Book a shipment against a crane slot (OCC-guarded) | LogisticsCoordinator |
| GET | `/genset-packaging/shipments/{shipmentId}` | Get a shipment | Any |
| GET | `/genset-packaging/shipments` | List shipments (paginated, filterable) | Any |
| POST | `/genset-packaging/shipments/{shipmentId}/dispatch` | Dispatch a booked shipment | LogisticsCoordinator |
| POST | `/genset-packaging/shipments/{shipmentId}/deliver` | Mark a shipment delivered | LogisticsCoordinator |
| POST | `/genset-packaging/shipments/{shipmentId}/release` | Release a booked shipment | LogisticsCoordinator |
| POST | `/genset-packaging/commissioning-events` | Request startup commissioning | FieldServiceManager |
| GET | `/genset-packaging/commissioning-events/{eventId}` | Get a commissioning event | Any |
| GET | `/genset-packaging/commissioning-events` | List commissioning events (paginated, filterable) | Any |
| POST | `/genset-packaging/commissioning-events/{eventId}/assign` | Assign or reassign a field engineer | FieldServiceManager |
| POST | `/genset-packaging/commissioning-events/{eventId}/start` | Begin startup work | FieldServiceManager |
| POST | `/genset-packaging/commissioning-events/{eventId}/complete` | Complete startup with training record | FieldServiceManager |
| POST | `/genset-packaging/commissioning-events/{eventId}/accept` | Customer accepts commissioning | CustomerContact |
| POST | `/genset-packaging/service-contracts` | Quote an extended-warranty/PM contract | SalesEngineer |
| GET | `/genset-packaging/service-contracts/{contractId}` | Get a service contract | Any |
| GET | `/genset-packaging/service-contracts` | List service contracts (paginated, filterable) | Any |
| POST | `/genset-packaging/service-contracts/{contractId}/bind` | Bind a quoted contract | SalesEngineer |
| POST | `/genset-packaging/service-contracts/{contractId}/activate` | Activate a bound contract | SalesEngineer |
| POST | `/genset-packaging/service-contracts/{contractId}/cancel` | Cancel a quoted or bound contract | SalesEngineer |
| POST | `/genset-packaging/service-contracts/{contractId}/lapse-check` | Lapse or expire an active contract per the clock | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error are defined in the narratives of §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_STALE_CRANE_SLOT_VERSION` | 412 |
| `ERR_INVALID_BUILD_STATE` | 409 |
| `ERR_INVALID_COMMERCIAL_STATE` | 409 |
| `ERR_STUDY_STATE_INVALID` | 409 |
| `ERR_CONFIG_STATE_INVALID` | 409 |
| `ERR_PERMIT_STATE_INVALID` | 409 |
| `ERR_CERT_STATE_INVALID` | 409 |
| `ERR_SCHEME_STATE_INVALID` | 409 |
| `ERR_TEST_STATE_INVALID` | 409 |
| `ERR_SHIPMENT_STATE_INVALID` | 409 |
| `ERR_EVENT_STATE_INVALID` | 409 |
| `ERR_CONTRACT_STATE_INVALID` | 409 |
| `ERR_EMISSIONS_TIER_INSUFFICIENT` | 422 |
| `ERR_HOUR_LOG_REQUIRED` | 422 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_CAPACITY_UNDERSIZED` | 409 |
| `ERR_PARALLEL_CAPACITY_EXCEEDED` | 409 |
| `ERR_CRANE_WINDOW_OVERLAP` | 409 |
| `ERR_TEST_BAY_OVERLAP` | 409 |
| `ERR_ENGINEER_DAY_CAPACITY_EXCEEDED` | 409 |
| `ERR_FUEL_RUNTIME_INSUFFICIENT` | 422 |
| `ERR_PERMIT_EXPIRED` | 422 |
| `ERR_PERMIT_NOT_EXPIRED` | 422 |
| `ERR_SHIPMENT_DATE_NOT_REACHED` | 422 |
| `ERR_CONTRACT_NOT_LAPSABLE` | 422 |
| `ERR_SIZING_NOT_APPROVED` | 409 |
| `ERR_CERT_NOT_ISSUED` | 409 |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 |
| `ERR_COMMISSIONING_NOT_ACCEPTED` | 409 |
| `ERR_CUSTOMER_SUSPENDED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_TRAINING_INCOMPLETE` | 422 |

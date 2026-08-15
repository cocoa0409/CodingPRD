# Temporary Power & Climate Rental API — Product Requirements Document

## 1. Introduction

Providers of temporary power and climate control run a business where engineering constraints, commercial terms, and regulatory obligations collide on every single contract. A customer calls with a load requirement — a construction compound, a planned plant outage, a festival, a disaster-recovery site — and the provider must size a fleet of mobile generators and chillers, kit it out with cable and distribution accessories, clear air-quality permits for the deployment jurisdiction, mobilize the equipment, keep it fueled and serviced, respond to emergencies under contractually guaranteed response times, absorb damage and environmental-spill liability, and finally invoice the whole engagement under tiered day, week, and month rates. This document specifies the REST API that operates that entire lifecycle end to end.

The system is, at its core, a pricing engine wrapped in a fleet-state machine. Two load-sizing variants translate a customer's nameplate load profile into a required capacity; a tiered accrual calculation converts time-on-rent into exact integer-cent charges at quote time and again at off-hire; an emissions screening rule decides, per jurisdiction, whether a permit gates mobilization; and a standby agreement determines who may request emergency dispatch and whether the response met its service-level target. All resources are mounted under the `/power-rental` path prefix, and an operator-only logical clock drives every time-dependent behavior deterministically. The API serves seven distinct roles with deliberately segregated duties: the sales desk quotes and invoices, the depot controls the fleet, dispatchers route technicians, technicians execute visits and log telemetry, and an independent assessor prices liability — with waivers requiring a second, different authority.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting disciplines that apply uniformly to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request with missing headers, or whose role value is not recognized, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorization list; a role that is not permitted for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly seven roles. `Customer` is the renting organization, which owns its contracts, sites, and incident reports. `SalesEngineer` is the rental provider's sales desk, owning customer and site onboarding, load sizing, quoting, revision, line assembly, contract closing, and the entire permit lifecycle including recording regulator decisions. `DepotManager` is the fleet and depot authority, owning equipment units, accessory kits, mobilization, rental start, maintenance completion, line returns, and liability waivers. `FleetDispatcher` schedules, assigns, and cancels technician and fuel-delivery visits. `FieldTechnician` executes assigned visits on site and appends telemetry. `ClaimsAssessor` is the independent liability assessor who sets damage and spill charges. `PlatformAdmin` is an operator role whose only capability is driving the test-only logical clock.

Role identity is bound to resources in two different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a customer — a contract, a site, an incident — compare the resource's customer foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). When `X-User-Role` is `FieldTechnician`, `X-User-ID` is an opaque technician identifier not tied to any persisted entity; the server records it as `assigned_technician_id` on a service visit and compares it against `X-User-ID` when the technician performs arrival or completion actions. When `X-User-Role` is `SalesEngineer`, `DepotManager`, `FleetDispatcher`, `ClaimsAssessor`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `assessed_by` on an incident where an assessment transition writes it — but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it may not be lower than 1 or greater than 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time as an ISO 8601 UTC value with three fractional digits, and `updated_at` records the last modification in the same format. The `version` is an integer that increments by exactly one on every mutation of the resource, including mutations driven by cascade from another resource's transition; `updated_at` refreshes on the same occasions.

Two resources are deliberately lighter. An accessory kit catalog entry and a telemetry event each carry only `id` and `created_at`: both `updated_at` and `version` are absent from these two resources, because both are immutable once created — a catalog entry is never edited after publication, and a telemetry event is an append-only record that is never modified after it is written.

### 2.5. The Logical Clock and Quote Expiry

All notions of "now" in the system — quote timestamps, rental start timestamps, arrival timestamps, off-hire timestamps — are drawn from a server-held logical clock, never from wall time. At startup the logical clock reads 2026-08-01T00:00:00Z, and it advances only when an operator moves it; it never falls back to wall-clock time. A `PlatformAdmin` advances the clock through the clock-setting capability mounted at `/_clock/set_current_utc`, passing the target instant as `to_iso8601`; the response echoes the new logical now as `current_utc`.

Every clock advance runs a quote-expiry sweep. Any contract still in `QUOTED` status whose `quoted_at` lies more than seven days before the new logical now transitions `QUOTED → EXPIRED`, and the sweep performs the release cascade described in §2.9: each of that contract's lines still `PENDING` moves to `RELEASED`, and each unit still `RESERVED` for the contract returns to `AVAILABLE`. The expired contract's `version` increments by one. A quote therefore has a seven-day validity window measured on the logical clock, and a client that needs a stale quote revived must have the contract revised and re-quoted rather than confirmed late.

### 2.6. Money, Rates, and Rounding Discipline

All monetary values in the API are integer cents, and all money arithmetic is exact integer arithmetic — no floating-point rounding occurs anywhere in pricing. Rental rates are held as three separate integer-cent snapshots on every line: a daily rate, a weekly rate covering a seven-day block, and a monthly rate covering a twenty-eight-day block, plus a flat demobilization fee.

Where a calculation genuinely produces a fraction, the rounding rule is stated with the calculation itself and is always one of two disciplines. Quantities that must err upward use ceiling: chargeable rental days, required kilowatts from load sizing, required amperes for accessory kits, and emergency response minutes are each rounded up to the next whole unit. Fractional money and physical averages use round-half-up: the per-line loyalty discount, the fuel buy-back credit, the capacity-weighted NOx aggregate, and the fuel-projection outputs are each rounded half-up, the latter three to exactly two decimal places. No calculation may round at any other point, and no monetary figure may carry more precision than whole cents once a rounding step is defined for it.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control: confirming a quote (`POST /power-rental/rental-contracts/{id}/confirm`) and adding a rental line (`POST /power-rental/rental-contracts/{id}/lines`). Each of these requests must carry the non-optional field `expected_rental_contract_version`, whose value is the contract `version` the client last observed. If the supplied value does not equal the contract's current `version` at the moment the write is evaluated, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no part of the write takes effect.

Because load-sizing recomputation, quoting, revision, and every successful line addition each advance the contract's `version`, a client holding a previously read contract should assume its observed version is stale after any such activity, re-read the contract, and retry with the fresh version. No endpoint other than the two named above accepts a version field; requests to all other endpoints must not include one.

### 2.8. Validation Pipeline and Error Precedence

Incoming writes are screened by a nine-tier validation pipeline, and the tiers are evaluated in strict priority order: a request that fails an earlier tier never surfaces an error from a later one. The first tier authenticates the caller, rejecting with `ERR_UNAUTHENTICATED`. The second tier authorizes: the role must be permitted for the endpoint (`ERR_FORBIDDEN`); where segregation of duties applies — waiving an assessed incident — the acting user must differ from the user recorded as the assessor (`ERR_SEGREGATION_OF_DUTIES`); and where ownership applies — a `Customer` touching a contract, site, or incident belonging to another customer, or a `FieldTechnician` performing an arrival or completion on a visit assigned to a different technician — the request is rejected with `ERR_NOT_OWNER`. The third tier checks existence: every identifier in the path must resolve (`ERR_NOT_FOUND`), and every foreign key in the body must reference an existing resource (`ERR_REFERENCE_NOT_FOUND`).

The fourth tier checks state: the target must stand in a valid from-state for the requested transition (`ERR_INVALID_STATE`), terminal resources reject all further mutation (`ERR_ALREADY_TERMINAL`), and the two OCC-guarded writes compare `expected_rental_contract_version` against the live version (`ERR_STALE_VERSION`). The fifth tier enforces business safety: emissions-tier compliance on line assembly (`ERR_EMISSIONS_TIER_NONCOMPLIANT`), the permit gate on mobilization (`ERR_PERMIT_REQUIRED`), and fuel-tank capacity on deliveries (`ERR_TANK_CAPACITY_EXCEEDED`). The sixth tier enforces temporal separation: equipment reservation windows may not overlap (`ERR_UNIT_RESERVED_CONFLICT`) and technician buffered windows may not intersect (`ERR_TECHNICIAN_SCHEDULE_CONFLICT`).

The seventh tier checks payload and constraint well-formedness: malformed payloads, invalid enumerations, wrong conditional fields, and duplicate catalog codes (`ERR_VALIDATION`); inverted date ranges and future telemetry timestamps (`ERR_INVALID_DATE_RANGE`); sizing an empty load profile (`ERR_LOAD_PROFILE_EMPTY`); quoting an undersized fleet (`ERR_UNDERSIZED_FLEET`); an accessory kit below the required ampacity (`ERR_KIT_UNDERSIZED`); resubmitting a permit whose review rounds are exhausted (`ERR_PERMIT_REVIEW_EXHAUSTED`); requesting emergency dispatch without a standby agreement (`ERR_STANDBY_CONTRACT_REQUIRED`); and pumping out more fuel than the tank holds (`ERR_INSUFFICIENT_TANK_FUEL`). The eighth tier enforces cross-entity referential rules: the named unit must sit on an active equipment line of the referenced contract (`ERR_UNIT_CONTRACT_MISMATCH`), and a contract may not close while an incident remains open (`ERR_OPEN_INCIDENTS`). The ninth and final tier is fiscal: the customer's credit posture is evaluated last, so a quote request, a quote confirmation, or a line addition against a credit-held customer fails with `ERR_CREDIT_HOLD` only after every earlier tier has passed.

### 2.9. Hierarchical Cascades and Fleet-State Consistency

Contracts, lines, and equipment units form a cascade hierarchy, and the server keeps the three levels mutually consistent without waiting for explicit client requests on the dependent resources. When a contract is cancelled or its quote expires, every one of its lines still `PENDING` moves to `RELEASED` and every unit still `RESERVED` for that contract is released back to `AVAILABLE` — a compensating release that restores the rentable pool. When a contract starts rent, its pending lines activate and its reserved units deploy to the contract's site. When a spill quarantines a unit, the suspension propagates upward to the contract and outward to its scheduled visits. Each hop of every cascade is a real mutation on the affected resource: its `version` increments by one and its `updated_at` refreshes, so downstream readers always observe a coherent, monotonically advancing fleet state.

Two disciplines keep cascades predictable. First, compensating releases apply only to non-terminal resources — a line already `OFF_HIRED` or `RETURNED` is untouched by a contract cancellation cascade, because cancellation is only reachable from `DRAFT`, `QUOTED`, or `CONFIRMED`, where lines can only be `PENDING`. Second, cascades never skip levels silently: if a single client action fans out to a unit, a contract, and a visit, each of those mutations is applied and each resource's version reflects it.

### 2.10. Nested Resource Retrieval

Requests that target resources beneath other resources are validated left to right along the path. Each `{id}` segment is resolved in order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before any later segment or any body validation is attempted. Body-supplied foreign keys — `customer_id`, `site_id`, `equipment_unit_id`, `accessory_kit_id`, and `contract_id` — are checked only after the path has fully resolved, and a body reference to a non-existent resource is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Customers, Sites, and Commercial Terms

A `SalesEngineer` onboards a new customer by supplying the organization's legal `name` and the `billing_email` to which invoices will be sent. Four optional commercial attributes shape everything downstream. The `credit_status` begins at `GOOD` unless explicitly set to `WATCH` or `HOLD`, and it gates fiscal operations: while a customer stands at `HOLD`, quoting, quote confirmation, and line addition are all rejected with `ERR_CREDIT_HOLD` (HTTP 402), and — per the pipeline in §2.8 — that rejection surfaces only after every other check has passed. The `standby_contract` flag, defaulting to false, records whether the customer holds a standby emergency-response agreement; it is the gate on emergency dispatch described in §3.7. For standby customers, `sla_response_minutes` states the guaranteed on-site response time in minutes, defaulting to 240 and required to be a positive integer. Finally, `loyalty_discount_pct` is a fractional discount, defaulting to 0, that must be at least 0 and strictly less than 1 — a value of 0.07 means seven percent — and it is applied per invoice line at contract close as described in §3.9.

Sites are registered under a customer by a `SalesEngineer`, who provides the owning `customer_id`, a display `name`, the `jurisdiction_code` identifying the permitting and emissions locale (for example CA-SCAQMD, TX-TCEQ, or FL-DEP; sites in unlisted jurisdictions fall back to a default emissions cap), and the `fuel_tank_capacity_liters` of the on-site tank, which must be positive. A site's `tank_level_liters` is never written directly: it is a computed figure that starts at zero and thereafter equals the sum of all fuel-delivery telemetry minus all pump-out telemetry recorded over every contract at that site. The two tank invariants — the level never rises above capacity and never drops below zero — are enforced at the moments fuel moves, in §3.6 and §3.7. A site read returns the live computed `tank_level_liters`; the site list may be narrowed with the `customer_id` query parameter.

Ownership scoping applies throughout: a caller in the `Customer` role may only read and act on contracts, sites, and incidents belonging to their own customer record, and any attempt to touch another customer's resource is rejected with `ERR_NOT_OWNER`.

### 3.2. Fleet and Accessory Catalog Management

A `DepotManager` grows the fleet one unit at a time. Each unit is registered with a `unit_type` of `GENERATOR` or `CHILLER`, a positive integer `capacity_kw` rating (chillers express cooling capacity as kilowatt-equivalent), a `fuel_type` of `DIESEL` or `NATURAL_GAS`, an `emissions_tier` of `TIER_2` or `TIER_4F`, a positive `nox_g_per_kwh` emission factor, and the depot identifier `home_depot_code`. Pricing is set at registration as three positive integer-cent rates — `day_rate_cents`, `week_rate_cents` for a seven-day block, and `month_rate_cents` for a twenty-eight-day block — plus a `demob_fee_cents` of zero or more that is charged once per equipment line at off-hire. A new unit enters the fleet in `AVAILABLE` status with no site assignment: `current_site_id` remains null until deployment, and the computed lifetime counters `runtime_hours_total` and `fuel_consumed_liters_total` both start at zero.

Units move through six fleet states — `AVAILABLE`, `RESERVED`, `DEPLOYED`, `OFF_RENT`, `QUARANTINED`, and `MAINTENANCE` — but with a single exception they never move on their own: every unit transition is a cascade from line, contract, or incident activity described in the following subsections. The one direct fleet action is maintenance completion, performed by a `DepotManager` on a unit standing in `MAINTENANCE`: the unit returns `MAINTENANCE → AVAILABLE`, its `version` increments by one, and it rejoins the rentable pool. The fleet list may be filtered by `status` or by `current_site_id`.

Cable runs and distribution panels are rented as accessory kits from an immutable catalog. A `DepotManager` publishes each catalog entry with a unique `kit_code` (such as CABLE-400A) — a duplicate code is rejected with `ERR_VALIDATION` — a free-text `description` of the kit contents, a positive `max_ampacity_a` stating the maximum ampacity one kit supports, and its own `day_rate_cents`, `week_rate_cents`, and `month_rate_cents`. Catalog entries are never edited after creation; as noted in §2.4, an accessory kit carries only `id` and `created_at`.

### 3.3. Contract Drafting, Load Sizing, and Line Assembly

A rental engagement begins as a contract in `DRAFT` status, created by a `SalesEngineer` — or by a `Customer`, who may create only for their own `customer_id` and is otherwise rejected with `ERR_NOT_OWNER`. The creation payload names the renting `customer_id` and the deployment `site_id` (the site's jurisdiction will drive emissions screening), describes the electrical requirement as a `load_profile` array whose entries each pair a `load_type` of `CONTINUOUS`, `INTERMITTENT`, or `STANDBY` with a `nameplate_kw`, and fixes the rental window with `start_date` and `expected_offhire_date`. The start must be strictly before the expected end; an inverted or empty window is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422). The window is a half-open interval, inclusive at the start and exclusive at the expected end, a convention that matters for the reservation conflict rule below. A new contract is born with `sized_kw`, `sizing_method`, `quoted_at`, `quoted_total_cents`, `on_rent_at`, `actual_offhire_at`, and `invoice_total_cents` all null, each waiting for the lifecycle moment that fills it.

Before a quote can be produced, a `SalesEngineer` runs load sizing against the draft. The sizing request carries a `sizing_method` of `NAMEPLATE_SUM` or `DIVERSIFIED_DEMAND`, and the contract must be in `DRAFT` with a non-empty `load_profile` — sizing an empty profile is rejected with `ERR_LOAD_PROFILE_EMPTY` (HTTP 400). Under the nameplate-sum variant, every entry's `nameplate_kw` is summed, the sum is multiplied by the safety factor 1.25, and the result is rounded up to the next whole kilowatt. Under the diversified-demand variant, each entry's `nameplate_kw` is first weighted by its demand factor — 1.0 for `CONTINUOUS`, 0.7 for `INTERMITTENT`, and 0.35 for `STANDBY` loads — the weighted entries are summed, the sum is multiplied by the same 1.25 safety factor, and the result is rounded up to the next whole kilowatt. Because the non-continuous demand factors fall below one, the diversified result is strictly smaller than the nameplate sum whenever the profile holds at least one `INTERMITTENT` or `STANDBY` entry. Either way, the outcome is written to the contract as `sized_kw`, the variant used is recorded in `sizing_method`, and the contract's `version` increments.

Lines are then assembled onto the draft. Each addition names a `line_type` of `EQUIPMENT` or `ACCESSORY_KIT`; an equipment line must carry an `equipment_unit_id` and a null `accessory_kit_id`, while a kit line must carry an `accessory_kit_id` and a null `equipment_unit_id`, and any payload that violates this conditional pairing — or supplies a quantity other than exactly 1 on an equipment line — is rejected with `ERR_VALIDATION` (HTTP 400). Kit lines take a `quantity` of one or more, defaulting to 1, which is the number of identical kits rented. Every line is born `PENDING`, pinned to its contract through `contract_id`, and priced by snapshot: at the moment a line is added, the referenced unit's or kit's three rates are copied onto the line as `day_rate_cents`, `week_rate_cents`, and `month_rate_cents`, along with `demob_fee_cents` — always 0 on kit lines — and those snapshots stay pinned for the life of the line regardless of later fleet repricing. The line's `final_charge_cents` and `offhired_at` remain null until the line is off-hired.

Three guards protect each line addition, and they interlock with the pipeline order in §2.8. First, the write is OCC-guarded per §2.7: the payload must carry `expected_rental_contract_version` equal to the contract's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) — worth remembering, since each successful addition itself advances the contract version, so two lines added in sequence require a re-read between them. Second, once state and staleness checks pass, the emissions-tier rule fires: a `TIER_2` unit may not be added to a contract whose site jurisdiction cap is 5.0 or lower — in practice the CA-SCAQMD locale — and the attempt is rejected with `ERR_EMISSIONS_TIER_NONCOMPLIANT` (HTTP 422). Third, the reservation-conflict rule fires: the named unit must have no other line in `PENDING` or `ON_RENT` whose contract window half-open-overlaps the new contract's window; because both windows are half-open, a new rental starting exactly when an existing reservation ends is adjacency, not overlap, and is allowed, while any true intersection is rejected with `ERR_UNIT_RESERVED_CONFLICT` (HTTP 409).

Kit lines face a sizing rule of their own, evaluated only after the contract has a `sized_kw`. The required ampacity is the contract's `sized_kw` multiplied by one thousand, divided by the product of 480 — the three-phase voltage — and 1.732 — the square-root-of-three factor — with the result rounded up to the next whole ampere. The line is adequate only when its `quantity` multiplied by the kit's `max_ampacity_a` is at least that required figure; an inadequate kit line is rejected with `ERR_KIT_UNDERSIZED` (HTTP 422).

A successful equipment-line addition reserves the unit: it cascades `AVAILABLE → RESERVED` and binds itself to the new line, so the unit is visibly committed to the contract's window until the line is released, deployed, or off-hired. Lines may be added only while the contract stands in `DRAFT`; against a contract in any other state the addition fails the state tier with `ERR_INVALID_STATE` (HTTP 409), which is why the revision path in §3.4 exists to reopen a quoted draft.

### 3.4. Quoting, Confirmation, and Quote Expiry

Quoting turns a sized, assembled draft into a priced offer. A `SalesEngineer` requests the quote on a `DRAFT` contract, and the request is evaluated against three prerequisites surfaced as one error: the contract must have a `sized_kw`, must hold at least one line, and must field enough equipment — the sum of `capacity_kw` across its equipment lines must be at least the `sized_kw`. Failing any leg is rejected with `ERR_UNDERSIZED_FLEET` (HTTP 422), and the fiscal tier still applies afterward, so a credit-held customer sees `ERR_CREDIT_HOLD` only once the fleet itself is quotable.

A successful quote transitions the contract `DRAFT → QUOTED` and computes `quoted_total_cents` as the provisional accrual over the whole engagement: the charge is figured per line over the window from `start_date` inclusive to `expected_offhire_date` exclusive, using the line's pinned snapshot rates, and the per-line results — each including its demobilization fee where the line is an equipment line — are summed into the contract total. The accrual works as follows. The chargeable duration in days is the number of seconds between window start and end divided by 86,400, rounded up to the next whole day, and is at least one day whenever the end is after the start. That duration decomposes into whole twenty-eight-day months, and the remainder decomposes into whole seven-day weeks and leftover days. The leftover-day block costs the lesser of the leftover days times the daily rate and the weekly rate, and contributes zero when there are no leftover days. The remainder charge is the lesser of the whole weeks times the weekly rate plus the leftover-day block, and the monthly rate. The time charge is the whole months times the monthly rate plus the remainder charge; the line charge is the time charge multiplied by the line `quantity`; and the line's `demob_fee_cents` is added once for each equipment line. All of this is exact integer-cent arithmetic with no rounding. The quote's timestamp is captured in `quoted_at` from the logical clock, and the contract `version` increments.

A quote is not a dead end. Revision moves the contract `QUOTED → DRAFT`, invalidating the quote — `quoted_at` and `quoted_total_cents` are cleared — and reopening line assembly; the version increments again. Confirmation moves it `QUOTED → CONFIRMED` and may be performed by a `SalesEngineer` or by the `Customer` on their own contract; it is the second OCC-guarded write, so the payload must carry `expected_rental_contract_version` matching the live version or the confirmation is rejected with `ERR_STALE_VERSION`, and the credit check still applies — a `HOLD` posture blocks confirmation with `ERR_CREDIT_HOLD`. Confirmation increments the version once more.

Two exits abandon the commercial phase entirely. Cancellation is reachable from `DRAFT`, `QUOTED`, or `CONFIRMED` — by a `SalesEngineer`, or by the owning `Customer` — and lands the contract in the terminal `CANCELLED` state with the compensating release cascade of §2.9: every `PENDING` line becomes `RELEASED`, and every `RESERVED` unit returns to `AVAILABLE`. The other exit is passive: the quote-expiry sweep of §2.5 moves a stale quote `QUOTED → EXPIRED` with the same release cascade. Both `CANCELLED` and `EXPIRED` are terminal.

### 3.5. Permitting and Emissions Compliance

Whether a contract may mobilize depends on the emissions profile of the fleet it will deploy, and the system answers that question with a computed screening read available to `SalesEngineer` and `DepotManager` for any site. The screening's input set is the equipment referenced by equipment lines in `PENDING` or `ON_RENT` status belonging to that site's contracts in `CONFIRMED`, `MOBILIZING`, `ON_RENT`, or `SUSPENDED` status. The aggregate NOx figure is the capacity-weighted average emission factor: each qualifying unit's `nox_g_per_kwh` is multiplied by its `capacity_kw`, the products are summed, the sum is divided by the sum of all qualifying `capacity_kw`, and the quotient is rounded half-up to two decimal places — or reported as 0.0 when no units qualify. The site's jurisdiction supplies the cap: 5.0 grams per kWh for CA-SCAQMD, 8.0 for TX-TCEQ, 12.0 for FL-DEP, and a default of 10.0 for any unlisted jurisdiction code. The response carries `aggregate_nox_g_per_kwh`, `jurisdiction_cap_g_per_kwh`, `permit_required`, and `input_unit_count`, and `permit_required` is true whenever the aggregate is greater than or equal to the cap — an aggregate landing exactly on the cap still requires the permit.

The same screening disciplines fleet composition earlier in the funnel through the tier rule of §3.3: because a jurisdiction cap at or below 5.0 bans `TIER_2` equipment outright, a sales engineer assembling lines for a CA-SCAQMD site must select `TIER_4F` units, and the line-add rejection `ERR_EMISSIONS_TIER_NONCOMPLIANT` enforces that selection before any reservation takes hold.

When a permit is needed, a `SalesEngineer` opens a permit application against the contract — permitted only while the contract is `CONFIRMED` or `MOBILIZING`, with other states rejected as `ERR_INVALID_STATE`. The application names its `contract_id` and a `permit_type` of `EMISSIONS` or `NOISE`; the system copies `jurisdiction_code` from the contract's site, starts the permit in `DRAFT` with `review_rounds` at zero, and leaves `submitted_at` and `decided_at` null. Submission moves the permit `DRAFT → SUBMITTED`, increments `review_rounds` by one, stamps `submitted_at` from the logical clock, and bumps the permit's `version`. While the permit stands in `SUBMITTED`, it awaits the regulator's answer. The regulator's answer is then recorded by a `SalesEngineer` carrying an `outcome` of `APPROVED` or `REJECTED`: a submitted permit moves `SUBMITTED → APPROVED` or `SUBMITTED → REJECTED` accordingly, `decided_at` is stamped, and the version increments. `APPROVED` is terminal. A rejected application may be resubmitted — `REJECTED → SUBMITTED`, again incrementing `review_rounds` and stamping `submitted_at` — but only while fewer than three review rounds have been consumed; a resubmission attempt at three rounds is rejected with `ERR_PERMIT_REVIEW_EXHAUSTED` (HTTP 422). The permit list may be filtered by `contract_id` or `status`.

The gate closes at mobilization. Moving a contract `CONFIRMED → MOBILIZING` is a `DepotManager` action whose single precondition is the emissions rule: either the site screening currently reports no permit requirement, or an `EMISSIONS` permit in `APPROVED` status exists for the contract. When neither holds, mobilization is rejected with `ERR_PERMIT_REQUIRED` (HTTP 422). A successful mobilization increments the contract `version`.

### 3.6. Mobilization, On-Rent Operations, and Telemetry

Starting rent is the moment the plan becomes physical. A `DepotManager` starts the rental on a `MOBILIZING` contract, and the transition `MOBILIZING → ON_RENT` fans out across the hierarchy: every line still `PENDING` activates to `ON_RENT`, every unit still `RESERVED` deploys to `DEPLOYED` with its `current_site_id` set to the contract's site, the contract's `on_rent_at` is stamped from the logical clock, and the contract `version` increments. From this point the fleet counters accumulate: `runtime_hours_total` and `fuel_consumed_liters_total` grow only through telemetry.

Telemetry is an append-only ledger written by `FieldTechnician` operators, one event at a time. Each event carries a `contract_id` for context — the site is derived from the contract — an `event_type` of `RUNTIME`, `FUEL_BURN`, `FUEL_DELIVERY`, or `FUEL_PUMP_OUT`, and a positive `value` measured in hours for runtime events and in liters for the three fuel kinds. The `recorded_at` timestamp defaults to the logical clock's now when omitted and may never lie in the future; a future timestamp is rejected with `ERR_INVALID_DATE_RANGE`. Equipment-facing events bind to a unit through `equipment_unit_id`, which is required for `RUNTIME` and `FUEL_BURN` and must be null for `FUEL_DELIVERY` and `FUEL_PUMP_OUT` — tank-level events belong to the site, not to any unit — with violations rejected as `ERR_VALIDATION`. Where a unit is named, it must sit on an equipment line in `PENDING` or `ON_RENT` status of the same contract, or the event is rejected with `ERR_UNIT_CONTRACT_MISMATCH` (HTTP 422). Once accepted, an event applies its effect immediately and immutably: runtime adds `value` to the unit's `runtime_hours_total`, fuel burn adds to `fuel_consumed_liters_total`, delivery raises the site's `tank_level_liters`, and pump-out lowers it.

Two tank guards bracket the fuel events. A delivery — whether posted directly as telemetry or generated by a completed fuel-delivery visit in §3.7 — must not raise the site level above its `fuel_tank_capacity_liters`, though landing exactly at capacity is allowed; an over-capacity delivery is rejected with `ERR_TANK_CAPACITY_EXCEEDED` (HTTP 422). A pump-out may not draw more than the current tank level; an overdraw is rejected with `ERR_INSUFFICIENT_TANK_FUEL` (HTTP 422). The telemetry list may be filtered by `equipment_unit_id`, `contract_id`, or `event_type`.

Fuel planning is served by a computed projection read on any unit, answering with `method`, `liters_per_hour`, `projected_liters_per_day`, `next_refuel_eta_hours`, and `telemetry_event_count`. The caller selects the variant with the `method` query parameter, `RATED_CURVE` or `METERED_AVG`, defaulting to `METERED_AVG`. The rated-curve variant computes the hourly burn as the unit's `capacity_kw` multiplied by a load factor of 0.75 and a specific consumption of 0.28 liters per kilowatt-hour, independent of any telemetry. The metered-average variant considers the unit's telemetry inside the trailing seven-day window — from seven days before the logical now through the logical now, both ends inclusive — and divides the total fuel-burn liters in that window by the total runtime hours in that window; when the window holds zero runtime hours, the variant falls back to the rated-curve result, so the two methods yield identical answers for an unrun unit and diverge exactly when the metered rate differs from the nameplate curve. Either way, the projected daily burn is the hourly rate multiplied by twenty-four, and the next-refuel estimate is the current `tank_level_liters` of the unit's site — resolved through `current_site_id` — divided by the hourly rate. Every output of this read is rounded half-up to two decimal places.

### 3.7. Service Visits and Emergency Response

On-site work is coordinated as service visits of three kinds: `TECHNICIAN` visits for maintenance work, `FUEL_DELIVERY` visits for refueling, and `EMERGENCY` visits for urgent dispatch. A `FleetDispatcher` schedules ordinary visits; a `Customer` may request an emergency dispatch, and only on their own contract. Every visit names its `contract_id`, and the planned window `scheduled_start` and `scheduled_end` is required for all but `EMERGENCY` visits; conversely `fuel_quantity_liters` is required exactly when the visit is a `FUEL_DELIVERY`. Violating either conditional requirement is rejected with `ERR_VALIDATION`, and a window whose start is not strictly before its end is rejected with `ERR_INVALID_DATE_RANGE`. An emergency request carries no window: instead it stamps `requested_at` from the logical clock, and it is gated twice — the customer must hold a standby agreement or the request is rejected with `ERR_STANDBY_CONTRACT_REQUIRED` (HTTP 422), and the contract must stand in `ON_RENT` or `SUSPENDED` or the request fails the state tier with `ERR_INVALID_STATE`. Every visit is born `SCHEDULED`, with `assigned_technician_id` set at creation when known or left null until dispatch, and with `dispatched_at`, `arrived_at`, `response_minutes`, and `sla_met` unset until the lifecycle moment that produces them — the latter two only ever materialize on emergency visits.

Technicians are protected from overcommitment by a buffered-overlap rule applied both at visit creation and again at dispatch. Each visit occupies a buffered window that begins sixty minutes before its scheduled start and ends sixty minutes after its scheduled end, exclusive at the upper edge. Two visits assigned to the same technician conflict when their buffered windows intersect — ignoring visits that have been cancelled — and the conflict is rejected with `ERR_TECHNICIAN_SCHEDULE_CONFLICT` (HTTP 409). Because the buffer's upper edge is exclusive, a gap of exactly two hours between one visit's scheduled end and the next visit's scheduled start leaves the buffered intervals merely touching and is permitted.

Dispatch moves a `SCHEDULED` visit to `DISPATCHED` and is a `FleetDispatcher` action: the payload must supply `assigned_technician_id`, which is written onto the visit, `dispatched_at` is stamped from the logical clock, and the visit `version` increments. Arrival and completion belong to the field. A `FieldTechnician` arrives a dispatched visit — `DISPATCHED → ON_SITE` — and completes an on-site visit — `ON_SITE → COMPLETED` — and for both actions the acting `X-User-ID` must equal the visit's `assigned_technician_id`, with any other technician rejected as `ERR_NOT_OWNER`. While a visit stands in `ON_SITE`, the assigned technician performs the work before completing it. Arrival stamps `arrived_at`, and on an emergency visit it also settles the service-level question: `response_minutes` is the number of seconds between `requested_at` and `arrived_at` divided by sixty and rounded up to whole minutes, and `sla_met` is true exactly when that figure is at most the customer's `sla_response_minutes` — a response landing precisely on the guarantee meets it. Completion of a fuel-delivery visit has a physical side effect: the system appends a `FUEL_DELIVERY` telemetry event whose `value` is the visit's `fuel_quantity_liters`, raising the site tank level under the same capacity guard as any other delivery — an over-capacity completion is rejected with `ERR_TANK_CAPACITY_EXCEEDED` and the visit is not completed. Both transitions increment the visit version, and `COMPLETED` is terminal.

A scheduled visit may be cancelled by a `FleetDispatcher` — `SCHEDULED → CANCELLED`, terminal, version incremented — and the same transition fires automatically as cascade link 3 of the spill sequence in §3.8 when the visit's contract is suspended. The visit list may be filtered by `contract_id`, `assigned_technician_id`, `status`, or `visit_type`.

### 3.8. Incidents, Spills, and Liability

Damage and environmental spills are reported as incidents by the owning `Customer` or by a `SalesEngineer`, against a contract standing in `ON_RENT` or `OFF_HIRE`. The report names the `contract_id`, the affected `equipment_unit_id`, an `incident_type` of `DAMAGE` or `SPILL`, and free-text `notes`; `spill_volume_liters` is required exactly when the type is `SPILL`, with violations of that conditional rule rejected as `ERR_VALIDATION`. The named unit must sit on an equipment line in `PENDING` or `ON_RENT` status of the same contract, or the report is rejected with `ERR_UNIT_CONTRACT_MISMATCH`. Every incident is born `REPORTED`, with `assessed_charge_cents` and `assessed_by` unset.

A spill report is never just paperwork. When a `SPILL` incident is recorded against a unit currently `DEPLOYED` on the referenced contract, a three-link cascade fires: link 1 quarantines the unit, moving it `DEPLOYED → QUARANTINED`; link 2 suspends the parent contract, moving it `ON_RENT → SUSPENDED` and incrementing its version; link 3 cancels every visit still `SCHEDULED` for that contract, moving each to `CANCELLED`. The site is thereby frozen — no further scheduled work proceeds — until the claim is assessed.

Assessment is reserved to the `ClaimsAssessor`, whose independence anchors the liability workflow. Assessing a `REPORTED` incident moves it to `ASSESSED`, writes the payload's `assessed_charge_cents` as the liability figure, records the acting `X-User-ID` in `assessed_by`, and increments the incident `version`. For a spill, assessment is also the resolution of the freeze: the quarantined unit moves `QUARANTINED → MAINTENANCE` into the decontamination queue, the unit's `ON_RENT` line moves to `OFF_HIRED` with its final charge computed to the assessment moment plus its demobilization fee — exactly the final accrual described in §3.9 — and the parent contract resumes `SUSPENDED → ON_RENT`, its version incrementing.

Two fates await an assessed charge. A `DepotManager` may waive it, moving the incident `ASSESSED → WAIVED`, but segregation of duties forbids the waver from being the assessor: when the acting `X-User-ID` equals the incident's `assessed_by`, the waiver is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A waived charge is excluded from the invoice's damage sum. Alternatively the charge stands until contract close, when the close cascade moves every `ASSESSED` incident on the contract to `CHARGED` and folds its `assessed_charge_cents` into the invoice. Both `CHARGED` and `WAIVED` are terminal. The incident list may be filtered by `contract_id`, `equipment_unit_id`, or `status`.

### 3.9. Off-Hire, Return, and Final Invoicing

Off-hire can happen line by line or for the whole contract. A partial off-hire — performed by a `SalesEngineer` or the owning `Customer` on a line standing in `ON_RENT` — is allowed while the parent contract is `ON_RENT` or `SUSPENDED`, and it finalizes that line alone: the line moves to `OFF_HIRED`, its `final_charge_cents` is computed by the final accrual below, its `offhired_at` is stamped from the logical clock, and its unit — if the line is an equipment line — flips `DEPLOYED → OFF_RENT` with `current_site_id` cleared. Contract-level off-hire, performed by the same two roles on an `ON_RENT` contract, applies the identical finalization to every line still `ON_RENT`: each such line moves to `OFF_HIRED` with its final charge and `offhired_at` set, each deployed unit moves to `OFF_RENT`, the contract stamps `actual_offhire_at`, and the contract lands in `OFF_HIRE` with its version incremented. Lines already `OFF_HIRED` — whether partially off-hired earlier or off-hired by a spill assessment — are untouched by the contract-level sweep.

The final accrual reuses the provisional tiered formula of §3.4 with one change of horizon: the window runs from the contract's `start_date` inclusive to the off-hire moment exclusive, so the chargeable days are the elapsed seconds divided by 86,400 and rounded up, decomposed into twenty-eight-day months, seven-day weeks, and leftover days, priced with the same two lesser-of caps on the day block and the remainder, multiplied by `quantity`, and closed out by adding the line's `demob_fee_cents` once for each equipment line. The result is written to the line's `final_charge_cents` and diverges from the provisional quote whenever the actual rental duration differs from the expected window.

Returns close the loop with the depot. A `DepotManager` returns a line standing in `OFF_HIRED` — allowed while the parent contract is `OFF_HIRE` or `CLOSED` — moving the line to the terminal `RETURNED` state and sending its unit `OFF_RENT → MAINTENANCE` for inspection at its home depot. From there the maintenance-completion action of §3.2 eventually restores the unit to `AVAILABLE`.

Closing is the contract's final act and belongs to the `SalesEngineer`. A contract in `OFF_HIRE` may close only when no incident on it remains `REPORTED` — an open incident blocks the close with `ERR_OPEN_INCIDENTS` (HTTP 422) — and when every line stands in `OFF_HIRED` or `RETURNED`. The close computes `invoice_total_cents` in a pinned order. First, each line's discounted charge is its `final_charge_cents` multiplied by one minus the customer's `loyalty_discount_pct`, rounded half-up to whole cents — the rounding happens per line before any summation, because summing first and rounding once would yield different cents. Second, those discounted lines are summed into a lines subtotal. Third, the damage component is the sum of `assessed_charge_cents` over the incidents transitioning `ASSESSED → CHARGED` on this close. Fourth, the fuel credit is the contract's total pump-out liters — the sum of its `FUEL_PUMP_OUT` telemetry values — multiplied by a buy-back rate of 180 cents per liter, rounded half-up to whole cents. Fifth, the service-level credit is 25,000 cents for each of the contract's emergency visits whose `sla_met` is false. The invoice total is the lines subtotal plus the damage component, minus the fuel credit, minus the service-level credit, all in exact integer cents with rounding only at the per-line discount and the fuel credit, in that order. The close stamps the total onto `invoice_total_cents`, cascades the assessed incidents to `CHARGED`, increments the contract version, and lands the contract in the terminal `CLOSED` state.

Terminal states lock everything down. A contract in `CLOSED`, `CANCELLED`, or `EXPIRED`, a visit in `COMPLETED` or `CANCELLED`, an incident in `CHARGED` or `WAIVED`, and a permit in `APPROVED` each reject any further mutation with `ERR_ALREADY_TERMINAL` (HTTP 409), and any action attempted against a resource standing in a state that does not source the requested transition is rejected with `ERR_INVALID_STATE`. The contract list may be filtered by `customer_id`, `site_id`, or `status`, and the line list by `contract_id`, `equipment_unit_id`, `accessory_kit_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a customer, registering a site, adding a unit or kit, drafting a contract, adding a line, opening a permit, scheduling a visit, appending telemetry, or reporting an incident — return `201 Created`. Operations that modify an existing resource, perform a state transition, run a computed read, or retrieve resources return `200 OK`. Request and response payloads are not repeated here; §3 defines every input field, and the response of a create or modify operation is the created or updated resource per §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/power-rental/customers` | Onboard a customer | SalesEngineer |
| GET | `/power-rental/customers/{id}` | Read a customer | SalesEngineer, DepotManager, Customer, FleetDispatcher, ClaimsAssessor |
| POST | `/power-rental/sites` | Register a deployment site | SalesEngineer |
| GET | `/power-rental/sites/{id}` | Read a site including computed tank level | SalesEngineer, DepotManager, Customer, FleetDispatcher, FieldTechnician |
| GET | `/power-rental/sites` | List sites | SalesEngineer, DepotManager, Customer |
| GET | `/power-rental/sites/{id}/emissions-screening` | Capacity-weighted NOx aggregate versus jurisdiction cap | SalesEngineer, DepotManager |
| POST | `/power-rental/equipment-units` | Add a generator or chiller to the fleet | DepotManager |
| GET | `/power-rental/equipment-units/{id}` | Read a unit | DepotManager, SalesEngineer, FleetDispatcher, FieldTechnician |
| GET | `/power-rental/equipment-units` | List units with filters | DepotManager, SalesEngineer, FleetDispatcher |
| POST | `/power-rental/equipment-units/{id}/complete-maintenance` | Return a unit from maintenance to available | DepotManager |
| GET | `/power-rental/equipment-units/{id}/fuel-projection` | Projected burn rate and next-refuel estimate | DepotManager, SalesEngineer, FleetDispatcher, FieldTechnician |
| POST | `/power-rental/accessory-kits` | Publish an immutable accessory kit catalog entry | DepotManager |
| GET | `/power-rental/accessory-kits/{id}` | Read a kit | DepotManager, SalesEngineer |
| POST | `/power-rental/rental-contracts` | Create a contract in DRAFT | SalesEngineer, Customer |
| GET | `/power-rental/rental-contracts/{id}` | Read a contract | SalesEngineer, Customer, DepotManager, FleetDispatcher, ClaimsAssessor, FieldTechnician |
| GET | `/power-rental/rental-contracts` | List contracts with filters | SalesEngineer, Customer, DepotManager |
| POST | `/power-rental/rental-contracts/{id}/size-load` | Run load sizing with the given variant | SalesEngineer |
| POST | `/power-rental/rental-contracts/{id}/quote` | Quote the contract and compute the provisional total | SalesEngineer |
| POST | `/power-rental/rental-contracts/{id}/revise` | Reopen a quoted contract for editing | SalesEngineer |
| POST | `/power-rental/rental-contracts/{id}/confirm` | Confirm a quote with optimistic concurrency | SalesEngineer, Customer |
| POST | `/power-rental/rental-contracts/{id}/cancel` | Cancel a contract and release reserved units | SalesEngineer, Customer |
| POST | `/power-rental/rental-contracts/{id}/mobilize` | Mobilize a confirmed contract, gated by emissions permit | DepotManager |
| POST | `/power-rental/rental-contracts/{id}/start-rental` | Start rent: deploy units and activate lines | DepotManager |
| POST | `/power-rental/rental-contracts/{id}/off-hire` | Off-hire the contract at actual duration | SalesEngineer, Customer |
| POST | `/power-rental/rental-contracts/{id}/close` | Close the contract and compute the final invoice | SalesEngineer |
| POST | `/power-rental/rental-contracts/{id}/lines` | Add an equipment or accessory-kit line with rate snapshot | SalesEngineer |
| GET | `/power-rental/rental-lines/{id}` | Read a rental line | SalesEngineer, DepotManager, Customer |
| GET | `/power-rental/rental-lines` | List rental lines with filters | SalesEngineer, DepotManager, Customer |
| POST | `/power-rental/rental-lines/{id}/off-hire` | Partially off-hire a single line | SalesEngineer, Customer |
| POST | `/power-rental/rental-lines/{id}/return` | Return an off-hired line to the depot | DepotManager |
| POST | `/power-rental/permits` | Open a permit application for a contract | SalesEngineer |
| GET | `/power-rental/permits/{id}` | Read a permit | SalesEngineer, DepotManager |
| GET | `/power-rental/permits` | List permits with filters | SalesEngineer, DepotManager |
| POST | `/power-rental/permits/{id}/submit` | Submit a permit for review | SalesEngineer |
| POST | `/power-rental/permits/{id}/record-decision` | Record the regulator's decision | SalesEngineer |
| POST | `/power-rental/permits/{id}/resubmit` | Resubmit a rejected permit | SalesEngineer |
| POST | `/power-rental/service-visits` | Schedule a visit or request emergency dispatch | FleetDispatcher, Customer |
| GET | `/power-rental/service-visits/{id}` | Read a service visit | FleetDispatcher, FieldTechnician, DepotManager, SalesEngineer, Customer |
| GET | `/power-rental/service-visits` | List service visits with filters | FleetDispatcher, FieldTechnician, DepotManager, SalesEngineer, Customer |
| POST | `/power-rental/service-visits/{id}/dispatch` | Dispatch a visit and assign its technician | FleetDispatcher |
| POST | `/power-rental/service-visits/{id}/arrive` | Record the assigned technician's arrival | FieldTechnician |
| POST | `/power-rental/service-visits/{id}/complete` | Complete the visit, posting fuel delivery telemetry where applicable | FieldTechnician |
| POST | `/power-rental/service-visits/{id}/cancel` | Cancel a scheduled visit | FleetDispatcher |
| POST | `/power-rental/telemetry-events` | Append an immutable runtime or fuel telemetry event | FieldTechnician |
| GET | `/power-rental/telemetry-events/{id}` | Read a telemetry event | FieldTechnician, FleetDispatcher, DepotManager, SalesEngineer |
| GET | `/power-rental/telemetry-events` | List telemetry events with filters | FieldTechnician, FleetDispatcher, DepotManager, SalesEngineer |
| POST | `/power-rental/incidents` | Report damage or a spill against a deployed unit | Customer, SalesEngineer |
| GET | `/power-rental/incidents/{id}` | Read an incident | ClaimsAssessor, DepotManager, SalesEngineer, Customer |
| GET | `/power-rental/incidents` | List incidents with filters | ClaimsAssessor, DepotManager, SalesEngineer, Customer |
| POST | `/power-rental/incidents/{id}/assess` | Assess liability; resolves spill quarantine | ClaimsAssessor |
| POST | `/power-rental/incidents/{id}/waive` | Waive an assessed charge under segregation of duties | DepotManager |
| POST | `/_clock/set_current_utc` | Advance the test-driving logical clock and run the quote-expiry sweep | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the workflow narratives of §2 and §3 rather than in this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_EMISSIONS_TIER_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_PERMIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_TANK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNIT_RESERVED_CONFLICT` | 409 Conflict |
| `ERR_TECHNICIAN_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_LOAD_PROFILE_EMPTY` | 400 Bad Request |
| `ERR_UNDERSIZED_FLEET` | 422 Unprocessable Entity |
| `ERR_KIT_UNDERSIZED` | 422 Unprocessable Entity |
| `ERR_PERMIT_REVIEW_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_STANDBY_CONTRACT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_TANK_FUEL` | 422 Unprocessable Entity |
| `ERR_UNIT_CONTRACT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OPEN_INCIDENTS` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 402 Payment Required |

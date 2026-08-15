# Hay Brokerage API — Product Requirements Document

## 1. Introduction

A hay brokerage sits at the intersection of agronomy, laboratory science, and freight logistics. Growers cut hay when weather windows allow; the broker stores the baled product, has it tested for feed value, quotes it to buyers with freight baked into the price, and then orchestrates partial truckloads across competing contracts — all while the calendar, the weather, and a drought-prone market constantly shift the ground underneath every participant. This document specifies the Hay Brokerage API, the system of record for that entire operation.

The platform serves five constituencies with sharply different needs. Platform administrators manage the master data — growers, buyers, weather reports, market indices, freight lanes, and storage sites — and wield the logical clock that drives every time-dependent computation in the system. Brokerage operations staff run the physical pipeline: creating bale lots from harvested cuttings, posting spoilage, moving lots between storage sites, building delivery loads, allocating tonnage across contracts, and settling grower proceeds. Lab technicians shepherd forage samples from collection through certified results under a strict segregation-of-duties regime. Growers manage their own fields and cutting schedules and hire the broker for custom baling. Buyers request freight-inclusive quotes, accept them into binding contracts, and watch their credit exposure.

Three design commitments shape everything that follows. First, time is a controlled input: a logical clock governs quote expiry, shrink accrual, weather-window evaluation, and commission tiering, so tests and operations are fully deterministic. Second, money and tonnage are computed with pinned evaluation orders — per-unit rounding before multiplication, commission tiers evaluated against year-to-date tonnage *before* each allocation's tons are added — because in a brokerage, the order of operations is the difference between a defensible settlement and a lawsuit. Third, quality is earned, never assumed: a bale lot is born `UNGRADED` and only acquires a sellable tier when a certified forage test says so, with a moisture cap that can drag even a premium sample back to `FAIR`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and invariants that apply to every endpoint and every entity in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `BrokerOps`, `Grower`, `Buyer`, and `LabTechnician`. A request whose headers are missing, or whose `X-User-Role` value is not one of these five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that authenticates successfully but targets an operation outside that role's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Two of the roles are entity-backed, meaning the `X-User-ID` header is compared against persisted resources to enforce ownership. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a `Grower` — directly or through a field or cutting — compare the resource's grower linkage to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks on any resource that references a `Buyer` compare the resource's `buyer_id` to `X-User-ID`, and a mismatch is likewise rejected with `ERR_FORBIDDEN_OWNERSHIP`.

The remaining three roles carry opaque identities. When `X-User-Role` is `PlatformAdmin`, `BrokerOps`, or `LabTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, a `ForageTest` records the acting technician's `X-User-ID` in `resulted_by_user_id` and `certified_by_user_id` — but it does not compare it to any entity's `id` for ownership purposes. The one deliberate exception is the laboratory's segregation-of-duties rule, which compares two such recorded identifiers to each other (see §3.4).

Role capabilities in brief: `PlatformAdmin` is the superset administrator and alone may advance the logical clock, post weather reports and market indices, define freight lanes and storage sites, create and suspend growers and buyers, and cancel or declare default on contracts. `BrokerOps` runs the physical operation — bale lots, spoilage, forage-test intake, delivery loads, allocations, and the execution of baling service orders. `Grower` manages its own fields and cuttings, marks cuttings cut, abandons them, and requests, disputes, and cancels custom baling. `Buyer` creates, edits, issues, revises, accepts, and declines its own quotes and views its own contracts. `LabTechnician` submits samples, records results, and certifies results recorded by a different technician.

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
- A request to a path the API does not define is rejected with `ERR_NOT_FOUND` (HTTP 404); a defined path called with an unsupported method is rejected with `ERR_METHOD_NOT_ALLOWED` (HTTP 405). Both use this same error envelope.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range integer values are clamped into that range rather than rejected, and a non-integer `limit` is a schema error (`ERR_INVALID_REQUEST`). The `offset` parameter specifies how many items to skip and defaults to 0; a negative integer is clamped to 0, and a non-integer `offset` is likewise `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Dependent Behavior

The system runs on a logical clock, not wall-clock time. At server startup the clock reads exactly `2026-08-01T00:00:00Z`, and before any administrative set call it continues to read that default — the server never silently falls back to wall-clock time. A `PlatformAdmin` advances the clock through an admin-only capability that accepts a target instant `to_iso8601` and returns the resulting `current_utc`.

The set call installs the supplied target instant as-is — the clock is never compared against its previous value, so it may be set to an earlier instant as readily as a later one — and responds `200 OK` with a body whose `data` carries the resulting `current_utc`.

Advancing the clock is a system-wide event with two immediate consequences. First, any quote still in `ISSUED` whose validity deadline has been passed by the new clock value is swept to `EXPIRED`. Second, every time-dependent derived quantity in the system — storage shrink on bale lots, storage-site occupancy, weather-window evaluations, year-to-date settlement tonnage, and quote expiry on reads — is recomputed against the new clock value on its next evaluation. Because shrink accrues monthly against the logical clock, identical inventory returns different tonnage figures before and after a clock advance; clients must treat computed tonnage fields as point-in-time readings.

### 2.5. Common Resource Properties

Most primary resources in the system — growers, fields, cuttings, storage sites, bale lots, forage tests, buyers, freight lanes, quotes, contracts, delivery loads, load allocations, and baling service orders — share a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at exactly 1 at creation and increments by one on every mutation to the resource, including mutations performed automatically by cascade side effects. This field anchors the optimistic concurrency controls described in §2.7.

Date-valued request fields (such as `planned_window_start`, `harvested_date`, `effective_date`, `report_date`, `event_date`, `sample_date`, `scheduled_date`, `requested_delivery_by`) accept a calendar date as `YYYY-MM-DD`; a full ISO 8601 datetime string is also accepted, in which case its date portion is used. Date-valued response fields are always rendered as `YYYY-MM-DD`.

Three resources are intentionally lighter-weight and carry only `id` and `created_at`: weather reports, spoilage events, and market indices. These records are append-only observations; both `updated_at` and `version` are absent from them, and no endpoint on those resources accepts a version field.

### 2.6. Validation Order and Error Precedence

When a request fails for more than one reason, the error the client receives is not arbitrary. Validations run in a strict priority order, and the first failing rule — the lowest priority number — wins the response. The ordering, from first to last, is:

1. Authentication: `X-User-ID` and `X-User-Role` headers are present and the role is one of the five declared roles (`ERR_UNAUTHENTICATED`).
2. Authorization: the acting role appears in the endpoint's authorized role list (`ERR_UNAUTHORIZED_ROLE`).
3. Request schema: all required fields are present, types are valid, and enum values fall within their declared membership (`ERR_INVALID_REQUEST`). Simple numeric domain constraints that carry no dedicated error code are also enforced at this layer with `ERR_INVALID_REQUEST`: `drying_index` within 0–100, `capacity_tons` of a storage site or delivery load greater than zero, field `acres` greater than zero, `bale_count` greater than zero, `credit_limit_cents` greater than zero, `price_per_ton_cents` greater than zero, `distance_miles` and `rate_per_mile_cents` greater than zero, `min_charge_cents` zero or greater, and `actual_bale_count` zero or greater. Dedicated tonnage-positivity failures instead surface as `ERR_TONS_NOT_POSITIVE` under rule 10.
4. Resource existence: every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error (`ERR_GROWER_NOT_FOUND`, `ERR_FIELD_NOT_FOUND`, `ERR_CUTTING_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, or `ERR_BSO_NOT_FOUND`).
5. Entity-backed ownership: an acting `Buyer` owns the target quote; an acting `Grower` owns the target field, cutting, or baling service order (`ERR_FORBIDDEN_OWNERSHIP`).
6. State-machine guards, including the optimistic-concurrency stale-version check: the from-state must match the attempted transition, and where an endpoint takes an expected-version field it must equal the parent entity's current `version` (`ERR_INVALID_STATE`, `ERR_CUTTING_NOT_OPEN`, `ERR_LOT_NOT_ACTIVE`, `ERR_TEST_WRONG_STATE`, `ERR_QUOTE_NOT_ISSUABLE`, `ERR_QUOTE_EXPIRED`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_LOAD_WRONG_STATE`, `ERR_BSO_WRONG_STATE`, `ERR_STALE_VERSION`).
7. Business safety: moisture safety at baling completion and the prohibition on shipping condemned hay (`ERR_MOISTURE_UNSAFE`, `ERR_LOT_CONDEMNED_UNSHIPPABLE`).
8. Business temporal rules: cutting-window overlap, the equipment buffer, cut-date window containment, and deadline passage (`ERR_FIELD_WINDOW_OVERLAP`, `ERR_EQUIPMENT_BUFFER_CONFLICT`, `ERR_CUTTING_WINDOW_RANGE`, `ERR_DEADLINE_NOT_PASSED`).
9. Business referential state: referenced growers and buyers must be `ACTIVE`, and a cutting must be `CUT` or `HARVESTED` before a lot is created from it (`ERR_GROWER_SUSPENDED`, `ERR_BUYER_SUSPENDED`, `ERR_CUTTING_NOT_CUT`).
10. Business constraints: uniqueness rules, tonnage positivity, sellable quote tiers, market-index and freight-lane availability, storage and load capacity, allocation limits, auto-allocation eligibility, and segregation of duties (`ERR_DUPLICATE_CUTTING_NUMBER`, `ERR_DUPLICATE_WEATHER_REPORT`, `ERR_DUPLICATE_MARKET_INDEX`, `ERR_DUPLICATE_FREIGHT_LANE`, `ERR_TONS_NOT_POSITIVE`, `ERR_UNGRADED_TIER`, `ERR_NO_MARKET_INDEX`, `ERR_NO_FREIGHT_LANE`, `ERR_CAPACITY_EXCEEDED`, `ERR_ALLOCATION_EXCEEDS_REMAINING`, `ERR_LOAD_CAPACITY_EXCEEDED`, `ERR_NO_ELIGIBLE_CONTRACT`, `ERR_NO_ELIGIBLE_LOT`, `ERR_SEGREGATION_OF_DUTIES`).
11. Business fiscal checks, evaluated last: the buyer credit-limit check at quote acceptance (`ERR_CREDIT_LIMIT_EXCEEDED`).

The practical consequence is that, for example, a quote-acceptance request that fails both ownership and the credit check reports the ownership failure; a lot-creation request against a nonexistent cutting and an over-capacity site reports the missing cutting; and a stale-version conflict surfaces before any tonnage arithmetic is evaluated.

### 2.7. Optimistic Concurrency Control

Four write operations require the client to prove it has observed the current state of a parent entity before mutating against it. Each such request must carry a non-optional expected-version field holding the client's last observed `version` of the parent entity; if that value does not match the parent entity's current `version` at the server, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The check is purely a stale-version rejection — it fires whenever the client has not observed the latest write, regardless of how the versions came to differ.

The four guarded operations are:

- Updating a draft quote's terms: the request must carry `expected_quote_version` matching the quote's current `version`. A prior update bumps the quote's `version` without leaving `DRAFT`, so a second update carrying the earlier version observes identical status yet works from stale pricing inputs.
- Accepting an issued quote: the request must carry `expected_quote_version` matching the quote's current `version`. The quote may have been revised and re-issued since the client read it — a revise-and-issue pair leaves the status `ISSUED` but advances the `version` and may change the pinned pricing — so a stale acceptance would contract against pricing the client never saw.
- Creating a load allocation: the request must carry `expected_delivery_load_version` matching the target delivery load's current `version`. Allocation creation bumps the load's `version` without leaving `PLANNED` or `LOADING`, so a sequential second allocation carrying the earlier version would succeed on capacity math computed from a stale `loaded_tons`.
- Transferring a bale lot to another storage site: the request must carry `expected_bale_lot_version` matching the lot's current `version`. Spoilage postings and allocations bump the lot's `version` while leaving it `ACTIVE`, so a stale transfer would run the destination capacity check against tonnage the client no longer holds.

Endpoints not named above do not take a version field. Returning an issued quote to draft (the revise operation) also requires `expected_quote_version` matching the quote's current `version`, enforced as a transition precondition with the same `ERR_STALE_VERSION` rejection.

### 2.8. Money, Precision, and Rounding

All monetary quantities in the system are integer cents: quote prices, contract reserves, freight charges, settlement lines, baling invoices, and buyer credit figures are all whole-cent integers, never fractional. Every calculation that produces cents uses exact decimal arithmetic internally — no binary floating-point drift — and rounds to whole cents using round-half-up (half away from zero) at each explicitly pinned step of the formula, never merely at the end. Where a formula pins the order "round the unit price first, then multiply by tonnage", that order is load-bearing: multiplying first and rounding after yields different totals and is non-conformant.

Tonnage quantities — harvested, shipped, spoiled, allocated, and the derived allocatable and physical figures — are numbers carried to 2 decimal places, rounded half-up after the full expression is evaluated. Percentage and index inputs (RFV, protein, moisture, precipitation, drying index) are compared exactly as given, at one-decimal precision, so a value of exactly `16.0` moisture does not trip a cap expressed as "greater than 16.0", and exactly `2.0` millimeters of precipitation does not make a day wet.

### 2.9. Dual Tonnage Accounting: Allocatable versus Physical

A bale lot's tonnage is tracked under two sanctioned but deliberately different shrink models, and confusing them is a category of bug the system is designed to expose rather than forgive. Both models start from the lot's `harvested_tonnage` and accrue shrink monthly from `harvested_date` to the current logical-clock date.

The **accounting variant** drives allocation decisions and the lot's `allocatable_tonnage` field. It applies simple, straight-line shrink: each full calendar month of storage consumes a fixed percentage of the *original* harvested tonnage — 1.5 percent per month in ordinary storage, halved to 0.75 percent per month while the lot's current storage site is moisture-controlled — capped so total shrink never exceeds 12 percent of the harvested tonnage. From that shrunken figure the system subtracts cumulative spoilage, cumulative shipped tonnage, and tonnage currently reserved by open allocations; the remainder, floored at zero, is what new allocations may draw against. A 100-ton lot stored for three full months in uncontrolled storage therefore reports 95.50 allocatable tons before any shipments or reservations.

The **physical variant** drives storage-capacity decisions and the lot's `physical_tonnage` field. It applies compound shrink: each full month multiplies the *remaining* tonnage by the shrink factor, so the same 100-ton lot after three uncontrolled months physically occupies 95.57 tons, floored so shrink never exceeds 12 percent of harvest. Cumulative spoilage and shipped tonnage are subtracted (open allocations are not — reserved hay still sits in the building), and the result is floored at zero. Because the two variants diverge, a lot can fit a site's remaining capacity by physical tonnage while its accounting tonnage tells a different story for allocation purposes.

A month counts only when it is complete: the elapsed-months figure is the number of whole calendar months between `harvested_date` and the current clock date, computed as the difference in years times twelve plus the difference in months, reduced by one when the clock's day-of-month is earlier than the harvest's day-of-month.

### 2.10. Storage-Site Occupancy and Capacity

A storage site's physical occupancy is the sum of the `physical_tonnage` of every bale lot currently assigned to that site whose status is `ACTIVE` or `DEPLETED`; lots that have been `CONDEMNED` are pulled from storage and contribute nothing. The site exposes a computed read returning `occupied_physical_tons`, `capacity_tons`, `available_tons` (capacity minus occupied, two-decimal), and `lot_count` (the count of those same contributing `ACTIVE`/`DEPLETED` lots), all evaluated at the current logical clock.

Two operations are gated against this occupancy: creating a bale lot into a site, and transferring a lot into a different site. In both cases the site's current occupancy plus the incoming lot's `physical_tonnage` must not exceed the site's `capacity_tons`; exact equality with capacity is allowed, and any excess is rejected with `ERR_CAPACITY_EXCEEDED`. Because occupancy uses the physical (compound-shrink) variant while allocations use the accounting variant, the two gates are independent and both must be satisfied where they apply.

### 2.11. Cascading State Propagation

The system maintains hierarchical consistency automatically: when a parent's state change invalidates dependent work, the dependent resources transition without requiring separate client calls, and each mutated resource refreshes its `updated_at` and increments its `version`. The principal cascades, detailed in §3, are: suspending a grower cancels their unstarted baling service orders; suspending a buyer suspends that buyer's active contracts without releasing the credit reserve; abandoning a cutting cancels baling orders still awaiting execution against it; condemning a bale lot releases its open allocations and reverts any affected loading-in-progress delivery load back to planned; canceling or defaulting a contract releases its open allocations and returns the buyer's credit reserve; and delivering a load ripples through allocations, contracts, lots, and buyer credit in a three-hop sequence. Automatic transitions of this kind — including the system-driven weather-window flips on cuttings and the expiry sweep on quotes — are first-class state changes, not bookkeeping annotations.

## 3. Business Logic & Workflows

### 3.1. Growers, Fields, and the Cutting Calendar

Everything in the brokerage begins with a grower. A `PlatformAdmin` creates a grower with a display `name` and a `region_code` — a code such as `OR-WILLAMETTE` that ties the grower to both the weather-window evaluation for their cuttings and the market-index lookup for their region. New growers are born `ACTIVE` with `settled_tons_ytd` at 0.0 and `outstanding_balance_cents` at 0. A grower's `settled_tons_ytd` is read-only, accumulates settled tonnage over the current calendar year of the logical clock, and drives the commission tier at settlement time; `outstanding_balance_cents` is likewise read-only and accumulates unpaid custom-baling invoices. A `PlatformAdmin` may suspend an `ACTIVE` grower — attempting the suspension from any other state is rejected with `ERR_INVALID_STATE` — and suspension carries a conditional cascade: every baling service order belonging to that grower still in `REQUESTED` or `SCHEDULED` status is cancelled outright.

Fields belong to growers. Creating a field requires the `grower_id` of an existing grower (a missing grower id yields `ERR_GROWER_NOT_FOUND`), a `name`, an acreage figure carried in the request field named `acres` that must be greater than zero, a `forage_type` of `ALFALFA`, `GRASS`, or `MIXED`, and an optional `irrigated` flag that defaults to false when omitted. Both `PlatformAdmin` and the owning `Grower` may create fields — an acting grower whose `X-User-ID` does not match the `grower_id` in the payload is stopped with `ERR_FORBIDDEN_OWNERSHIP` — and creation is refused with `ERR_GROWER_SUSPENDED` when the referenced grower is no longer `ACTIVE`. Fields may be listed with optional `grower_id` filtering — an acting `Grower` always sees only their own fields, any supplied `grower_id` filter being overridden by the acting grower's id — and fetched individually, with owner-only reads enforced for the `Grower` role.

Cuttings schedule the harvest. Creating a cutting against a field takes `field_id`, an ordinal `cutting_number` (1, 2, 3, and so on for the season), a `season_year` such as 2026, and a planned window given as `planned_window_start` and `planned_window_end`, both calendar dates, with the end required to be on or after the start. A new cutting starts `SCHEDULED`, and its `actual_cut_date` stays null until the crop is actually cut. Two integrity rules guard the calendar. First, within one field and one `season_year`, the combination of `cutting_number` must be unique among cuttings that have not been abandoned; a collision is rejected with `ERR_DUPLICATE_CUTTING_NUMBER`. Second, a new cutting's planned window must not overlap any non-abandoned cutting on the same field in the same season: windows are treated as half-open intervals — inclusive of the start, exclusive of the end — so back-to-back windows where the previous window's end equals the next window's start are permitted, while any true overlap is rejected with `ERR_FIELD_WINDOW_OVERLAP`. Cuttings may be listed with optional `field_id` and `status` filters; an acting `Grower` sees only cuttings on their own fields, and single-cutting fetches are owner-enforced for the `Grower` role.

A cutting's window opens and closes with the weather, and the weather enters the system as daily reports. A `PlatformAdmin` posts a weather report for a `region_code` and a calendar `report_date`, recording `precipitation_mm` and a `drying_index` from 0 to 100. Only one report may exist per region per date; a duplicate posting is rejected with `ERR_DUPLICATE_WEATHER_REPORT`. A day counts as dry when its precipitation is no more than 2.0 millimeters — exactly 2.0 still counts as dry — and drying-capable when its `drying_index` is at least 60, with exactly 60 qualifying. A day with no report at all counts as not dry.

Posting a weather report triggers a system-wide re-evaluation of every cutting whose field's grower has a matching `region_code`, provided the report date falls within the cutting's planned window (inclusive of both endpoints) or the cutting is currently in `WINDOW_OPEN`. For each affected cutting the system examines the trailing three calendar days ending on the report date, inclusive. If all three days have reports and each is both dry and drying-capable, a `SCHEDULED` cutting flips to `WINDOW_OPEN`. If any of the three days is wet, not drying-capable, or missing a report, a `WINDOW_OPEN` cutting reverts to `SCHEDULED` — the weather-slip revert. Both flips are genuine state transitions that increment the cutting's `version`, and the cyclic `SCHEDULED` ↔ `WINDOW_OPEN` dance can repeat as many times as the weather demands.

Once a cutting stands `WINDOW_OPEN`, the owning `Grower` (or a `PlatformAdmin`) marks it cut by supplying an `actual_cut_date`. Four guards apply, and their failure codes matter: the cutting must actually be `WINDOW_OPEN`, otherwise `ERR_CUTTING_NOT_OPEN`; the `actual_cut_date` must fall within the planned window, both endpoints inclusive, otherwise `ERR_CUTTING_WINDOW_RANGE`; the trailing three calendar days ending on the `actual_cut_date` must each have a report that is both dry and drying-capable, otherwise `ERR_CUTTING_NOT_OPEN` again; and an acting grower must own the cutting's field, otherwise `ERR_FORBIDDEN_OWNERSHIP`. A successful mark-cut sets `actual_cut_date` and moves the cutting to `CUT`.

The first bale lot successfully created from a `CUT` cutting automatically advances the cutting to `HARVESTED`; further lots may still be created while the cutting is `HARVESTED`, so a single cutting can yield many lots. A cutting in `SCHEDULED` or `WINDOW_OPEN` may instead be abandoned by the owning grower or an administrator, moving it to `ABANDONED`; abandonment cancels every baling service order for that cutting still in `REQUESTED` or `SCHEDULED`. Both `HARVESTED` and `ABANDONED` are terminal.

### 3.2. Inventory: Storage Sites, Bale Lots, Spoilage, and Condemnation

Storage sites are created by `PlatformAdmin` with a `name`, the `region_code` where the site sits, a `capacity_tons` ceiling that must be greater than zero, and an optional `moisture_controlled` flag (default false) that, when true, halves the monthly shrink rate applied to lots stored there. Sites may be listed and fetched, and the computed occupancy read described in §2.10 reports the site's current physical load.

A bale lot is created by `BrokerOps` or `PlatformAdmin` from a cutting that has reached `CUT` or `HARVESTED` — attempting it against a cutting in any earlier state is rejected with `ERR_CUTTING_NOT_CUT` — and only while the cutting's grower remains `ACTIVE`, since a suspended grower's inventory cannot be extended (`ERR_GROWER_SUSPENDED`). The creation payload carries `cutting_id`, `storage_site_id`, a `bale_type` of `SMALL_SQUARE`, `LARGE_SQUARE`, or `ROUND`, a `bale_count` greater than zero, the as-baled `harvested_tonnage` greater than zero, and the `harvested_date` from which shrink accrues. The destination site must exist (`ERR_SITE_NOT_FOUND`) and must have room for the lot by the physical-occupancy gate of §2.10 (`ERR_CAPACITY_EXCEEDED`). New lots are born `ACTIVE` and `UNGRADED`: `quality_tier` starts `UNGRADED`, `certified_protein_pct` stays null, and the three cumulative counters `shipped_tonnage`, `spoilage_tonnage`, and `open_allocated_tonnage` all start at 0.0. Lots may be listed with optional `cutting_id`, `storage_site_id`, `status`, and `quality_tier` filters, and fetching a lot returns its computed `allocatable_tonnage` and `physical_tonnage` evaluated at the current clock per §2.9.

Spoilage is recorded as append-only events: `BrokerOps` or `PlatformAdmin` posts a spoilage event with the `bale_lot_id`, an `event_date`, a positive `tons_lost` figure (a non-positive tonnage is refused with `ERR_TONS_NOT_POSITIVE`), and a `reason` of `MOLD`, `MOISTURE`, `PEST`, `FIRE`, or `OTHER`. Each event adds its `tons_lost` to the lot's cumulative `spoilage_tonnage`, and both derived tonnage fields are recomputed on the next read. A lot's spoilage history is retrievable as a list.

Two fates await a lot beyond ordinary depletion. `BrokerOps` (or `PlatformAdmin`) may condemn an `ACTIVE` lot — condemning from any other state is rejected with `ERR_LOT_NOT_ACTIVE`. Condemnation moves the lot to `CONDEMNED` and triggers a two-hop cascade: first, every open load allocation referencing the lot transitions from `OPEN` to `RELEASED`, so its reserved tonnage stops being held; second, each delivery load affected by those releases has its `loaded_tons` recomputed, and if such a load was in `LOADING` it reverts to `PLANNED`. Condemned hay can never ship: any later attempt to allocate a `CONDEMNED` lot to a load is rejected with `ERR_LOT_CONDEMNED_UNSHIPPABLE`. Note the deliberate asymmetry on the allocation path — a `DEPLETED` lot fails the earlier state guard with `ERR_LOT_NOT_ACTIVE`, while a `CONDEMNED` lot falls through to this priority-7 safety rule.

The other terminal state is earned rather than imposed: when a delivery completes and a lot's `allocatable_tonnage` reaches exactly 0.0 with `shipped_tonnage` greater than zero, the system automatically moves the lot to `DEPLETED`.

A lot may also be moved between storage sites. The transfer names a `dest_storage_site_id` and must carry `expected_bale_lot_version` matching the lot's current `version` per §2.7; a stale version is rejected with `ERR_STALE_VERSION`. The lot must be `ACTIVE` (`ERR_LOT_NOT_ACTIVE`), the destination site must exist (`ERR_SITE_NOT_FOUND`), and the destination's occupancy gate must admit the lot's physical tonnage (`ERR_CAPACITY_EXCEEDED`). The two priority-6 guards run state first, version second: a transfer against a non-`ACTIVE` lot reports `ERR_LOT_NOT_ACTIVE` even when the supplied version is also stale. A successful transfer updates the lot's `storage_site_id` and increments the lot's `version` by one — and because the shrink rate depends on the *current* site's `moisture_controlled` flag, moving a lot into or out of climate control changes its shrink trajectory from that point forward.

### 3.3. Market Indices and Freight Lanes

Market prices enter the system as indices posted by `PlatformAdmin`. Each index names a `region_code`, a `forage_type` (`ALFALFA`, `GRASS`, or `MIXED`), an `effective_date`, and a `price_per_ton_cents` that must be greater than zero. The triple of region, forage type, and effective date is unique; a duplicate posting is rejected with `ERR_DUPLICATE_MARKET_INDEX`. Indices may be listed with optional `region_code` and `forage_type` filters, and buyers may read them — a buyer watching the market sees the same indices the pricing engine uses.

Every newly posted index is immediately classified for drought regime by comparison against the most recent prior index for the same region and forage type whose effective date is strictly earlier than the new index's date but no more than 30 days before it. When no such prior index exists in that 30-day lookback, the new index's `drought_regime` is `STABLE`. Otherwise the system computes the percentage price change from the prior index's price to the new one, in exact decimal arithmetic. An increase of at least 15 percent — exactly plus 15 percent qualifies — classifies the new index as `DROUGHT`. Failing that, a move of at least 8 percent in either direction — exactly plus or minus 8 percent qualifies — classifies it as `VOLATILE`. Anything smaller is `STABLE`. The classification is derived once at creation and stored on the index.

Freight lanes are the other half of landed pricing. A `PlatformAdmin` creates a lane with an `origin_region_code` and `dest_region_code` — the ordered pair must be unique, with duplicates rejected as `ERR_DUPLICATE_FREIGHT_LANE` — plus a `distance_miles` greater than zero, a `rate_per_mile_cents` greater than zero, and a `min_charge_cents` that may be zero but never negative. The freight charge on a lane is computed as follows: the base charge is the lane's `min_charge_cents` or the per-mile rate multiplied by the distance rounded half-up to whole cents, whichever is greater. A fuel surcharge then applies by distance tier: no surcharge under 100 miles; 6 percent of the base when the distance is at least 100 but under 300 miles — the entire range 100 through 299 miles pays 6 percent; and 11 percent of the base at 300 miles or more. The surcharge itself is rounded half-up to whole cents, and the final freight charge is the sum of the two already-rounded components. This freight computation stands alone and is also reused inside quote pricing.

### 3.4. Forage Testing and Quality Certification

A bale lot is only as sellable as its lab results say it is. `BrokerOps` or `PlatformAdmin` collects a sample from a lot, creating a forage test with the lot's `bale_lot_id` and a `sample_date`; the test starts `COLLECTED` with `rfv`, `protein_pct`, `moisture_pct`, and `certified_by_user_id` all null. Tests may be listed with optional `bale_lot_id` and `status` filters.

From there a `LabTechnician` drives the sample through the lab pipeline, which is deliberately cyclic to accommodate retesting. Submission — supplying the lab's `lab_reference` — moves a test from `COLLECTED` to `SUBMITTED`; submission is permitted from `COLLECTED` or from `RESULTED` (the retest loop), and from any other state is rejected with `ERR_TEST_WRONG_STATE`. The referenced lot must not be `CONDEMNED` at submit time, otherwise `ERR_LOT_NOT_ACTIVE`. When a test is resubmitted from `RESULTED`, its prior result fields — `rfv`, `protein_pct`, `moisture_pct`, and `resulted_by_user_id` — are cleared to null, because the old numbers no longer describe a sample still at the lab.

Recording a result moves a `SUBMITTED` test to `RESULTED` (any other from-state draws `ERR_TEST_WRONG_STATE`): the acting technician supplies `rfv`, `protein_pct`, and `moisture_pct`, and the system stamps `resulted_by_user_id` with the acting `X-User-ID`. Certification then moves a `RESULTED` test to `CERTIFIED` under two further guards: the lot referenced by the test must be `ACTIVE` (`ERR_LOT_NOT_ACTIVE`), and the segregation-of-duties rule forbids the certifier from being the same user who recorded the result — the acting `X-User-ID` must differ from the test's `resulted_by_user_id`, otherwise the certification is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful certification stamps `certified_by_user_id` with the acting `X-User-ID` and, critically, writes the lot: the lot's `quality_tier` becomes the tier derived from the certified numbers, and its `certified_protein_pct` becomes the certified `protein_pct`. When several certified tests exist for one lot, last certify wins, ordered by the test's `updated_at` — never by id — so the most recently certified result always governs the lot's current tier.

The tier itself is assigned by threshold on the certified figures. A relative feed value of at least 185 yields a base tier of `SUPREME`; at least 170 but below 185 yields `PREMIUM`, with an `rfv` of exactly 170.0 landing on `PREMIUM`; at least 150 yields `GOOD`; at least 125 yields `FAIR`; and anything below 125 is unsellable and leaves the lot `UNGRADED`. A moisture cap then applies: when the certified `moisture_pct` exceeds 16.0 and the base tier was `SUPREME`, `PREMIUM`, or `GOOD`, the tier is dragged down to `FAIR` — a moisture of exactly 16.0 does not trigger the cap. Tests in `COLLECTED` or `SUBMITTED` may also be invalidated by a `LabTechnician` or `BrokerOps`, moving them to `INVALIDATED`; any other from-state draws `ERR_TEST_WRONG_STATE`. Both `CERTIFIED` and `INVALIDATED` are terminal.

### 3.5. Buyers, Credit, and the Quote Lifecycle

Buyers are created by `PlatformAdmin` with a display `name`, a home `region_code`, and a `credit_limit_cents` ceiling greater than zero. A new buyer is `ACTIVE` with `credit_used_cents` at 0; that figure is read-only and represents the cents currently reserved by the buyer's non-terminal contracts. Suspending a buyer — an administrator-only action that requires the buyer to be `ACTIVE`, otherwise `ERR_INVALID_STATE` — cascades: every contract of that buyer still `ACTIVE` becomes `SUSPENDED`, but the credit reserve is *not* released; the held reserve stays held against suspension.

Quotes are the buyer's instrument. A `Buyer` creates a quote in their own name — the payload's `buyer_id` must match the acting `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP`, and the buyer must be `ACTIVE`, else `ERR_BUYER_SUSPENDED` — by naming a `forage_type`, a `quality_tier`, the desired `tons` (greater than zero, else `ERR_TONS_NOT_POSITIVE`), an `origin_region_code` and `dest_region_code`, and a `requested_delivery_by` date that will become the delivery deadline of any resulting contract. The requested `quality_tier` must be a sellable tier — `SUPREME`, `PREMIUM`, `GOOD`, or `FAIR`; the value `UNGRADED` passes schema validation as a member of the enumeration but is rejected by the business rule with `ERR_UNGRADED_TIER`, since ungraded hay cannot be quoted. A new quote is born `DRAFT` with `pinned_market_index_id`, `issued_at`, and `expires_at` all null. Quotes may be listed with optional `buyer_id`, `status`, and `pinned_market_index_id` filters, though a `Buyer` sees only their own quotes; fetching a single quote is likewise owner-enforced for the `Buyer` role.

Quote pricing is freight-inclusive and has two variants pinned by state. Both variants price a ton by taking a market index price, multiplying by a tier multiplier — 1.30 for `SUPREME`, 1.15 for `PREMIUM`, 1.00 for `GOOD`, 0.85 for `FAIR` — and adding a 5 percent drought surcharge when the selected index carries a `DROUGHT` regime; the per-ton result is rounded half-up to whole cents *first*, yielding `unit_price_cents`, and only then multiplied by `tons` to give `commodity_cents` in integer math. The freight component follows the lane computation of §3.3 exactly, producing `freight_cents`, and `total_cents` is the sum of `commodity_cents` and `freight_cents`. Two lookups gate every pricing run: a market index effective on or before the pricing date must exist for the quote's origin region and forage type, otherwise `ERR_NO_MARKET_INDEX`; and a freight lane must exist for the origin-destination pair, otherwise `ERR_NO_FREIGHT_LANE`.

The **spot variant** governs `DRAFT` quotes — at creation, on any repricing update, and on any read of a `DRAFT` quote. Spot pricing selects the latest market index for the origin region and forage type whose `effective_date` is on or before the current logical-clock date, so a draft's displayed price moves as new indices post. Read-time repricing never changes the quote's `version`, and if a read finds the spot inputs unavailable (no effective index or no lane), the read succeeds with the quote's last stored pricing figures rather than failing. A buyer may update a `DRAFT` quote's `tons`, `dest_region_code`, or `requested_delivery_by`; such an update must carry `expected_quote_version` matching the quote's current `version` (stale versions draw `ERR_STALE_VERSION` per §2.7), is only permitted while the quote is `DRAFT` (otherwise `ERR_QUOTE_NOT_ISSUABLE`), and reprices the quote spot against the current clock, incrementing the quote's `version` by one.

Issuing is the pivot. A buyer issues their own `DRAFT` quote — wrong state draws `ERR_QUOTE_NOT_ISSUABLE`, another user's quote draws `ERR_FORBIDDEN_OWNERSHIP`, and a suspended buyer draws `ERR_BUYER_SUSPENDED`. Issue runs the **locked variant** of pricing: the system pins `pinned_market_index_id` to the latest market index for the origin region and forage type effective on or before the current clock date, recomputes and freezes `unit_price_cents`, `commodity_cents`, `freight_cents`, and `total_cents`, stamps `issued_at` with the current clock, and sets `expires_at` to exactly 72 hours after `issued_at`, advancing the quote to `ISSUED` and bumping its `version`. From `ISSUED` onward the pinned index governs: identical quote inputs yield different totals once a newer index posts, because a re-issued quote pins afresh while an untouched issued quote keeps its frozen numbers.

While `ISSUED`, three paths diverge. The buyer may revise the quote back to `DRAFT` — carrying `expected_quote_version` (`ERR_STALE_VERSION` on mismatch) and requiring ownership — which clears `pinned_market_index_id`, `issued_at`, and `expires_at` to null and returns pricing to the spot variant on the next read, with the `version` incremented. The buyer may decline, moving the quote to terminal `DECLINED` with no side effects. Or the quote may expire: the transition to `EXPIRED` is a lazy sweep, evaluated whenever the quote is read or acted upon — including a sweep of all quotes at the start of every quote-list call — and in bulk whenever the logical clock is advanced past `expires_at`; the precondition is simply that the current clock has passed `expires_at` (a clock reading exactly equal to `expires_at` does not expire the quote). The revise transition's guards run in this order: the from-state guard requires `ISSUED` (`ERR_QUOTE_NOT_ISSUABLE`), and only then is `expected_quote_version` compared (`ERR_STALE_VERSION`).

Acceptance is the most heavily guarded transition in the system, and its checks have a fixed order. First, if the current clock has passed `expires_at`, the quote auto-transitions to `EXPIRED` *before any other accept-time check*, and the acceptance fails with `ERR_QUOTE_EXPIRED` — the same error an acceptance attempt against an already-`EXPIRED` quote receives. The stale-version guard on `expected_quote_version` fires with `ERR_STALE_VERSION`; the from-state guard requires `ISSUED`, otherwise `ERR_QUOTE_NOT_ISSUABLE`; ownership requires the acting buyer to be the quote owner (`ERR_FORBIDDEN_OWNERSHIP`) and the buyer to be `ACTIVE` (`ERR_BUYER_SUSPENDED`); and finally the fiscal check, evaluated last of all, requires that the buyer's `credit_used_cents` plus the quote's `total_cents` not exceed the buyer's `credit_limit_cents` — exact equality with the limit is allowed — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). A successful acceptance moves the quote itself to `ACCEPTED` — a terminal state — and cascades in two hops: first a contract is created in `ACTIVE` status with its fields copied from the quote; then the buyer's `credit_used_cents` increases by the quote's `total_cents`, establishing the reserve.

### 3.6. Contracts: Reservations, Fulfillment, Default, and Cancellation

A contract is never created directly; it is born from quote acceptance. Its `quote_id` references the accepted quote; `buyer_id`, `quality_tier`, and `forage_type` are copied from the quote; `committed_tons` copies the quote's `tons`; `unit_price_cents` copies the quote's locked per-ton price and is never re-priced thereafter; `total_reserved_cents` equals the quote's `total_cents` at acceptance and represents the credit reserve held on the buyer; and `delivery_deadline` copies the quote's `requested_delivery_by`. A contract begins `ACTIVE` with `delivered_tons` and `open_allocated_tons` at 0.0; its read-only `remaining_tons` is the committed tonnage minus delivered tonnage minus open allocated tonnage. Contracts may be listed with optional `buyer_id`, `quote_id`, and `status` filters, and buyers may read their own.

Fulfillment is automatic: when a delivery completes and an `ACTIVE` contract's `delivered_tons` has reached or exceeded `committed_tons` — exact equality fulfills — the contract moves to `FULFILLED` and the buyer's credit reserve is released in full, subtracting `total_reserved_cents` from `credit_used_cents`. A contract in any other state (notably `SUSPENDED`, whose open allocations may still ride a delivered load) records delivered tonnage but does not fulfill and does not release its reserve on the delivery path.

Two administrative exits handle failure. A `PlatformAdmin` may declare default on a contract in `ACTIVE` or `SUSPENDED` — from any other state the attempt is rejected with `ERR_CONTRACT_NOT_ACTIVE`, which also covers the case of an already-fulfilled contract where delivered tonnage has reached the commitment — but only once the current clock date has passed the contract's `delivery_deadline`; declaring too early is rejected with `ERR_DEADLINE_NOT_PASSED`. Cancellation by a `PlatformAdmin` requires the same `ACTIVE`-or-`SUSPENDED` state guard (`ERR_CONTRACT_NOT_ACTIVE`) with no deadline condition. Both exits share the same two side effects: every open load allocation referencing the contract is released, and the buyer's `credit_used_cents` is reduced by `total_reserved_cents`, freeing the reserve. `FULFILLED`, `DEFAULTED`, and `CANCELLED` are all terminal.

### 3.7. Delivery Loads, Allocation, and the Delivery Cascade

Physical movement runs through delivery loads. `BrokerOps` or `PlatformAdmin` creates a load with a `carrier_name`, a truck `capacity_tons` greater than zero, and a `planned_ship_date`. A load carries two parallel status dimensions that evolve independently: `logistics_status` runs `PLANNED` → `LOADING` → `IN_TRANSIT` → `DELIVERED`, while `settlement_status` runs `OPEN` → `SETTLED`; the only coupling is that settlement requires the load to have been delivered. A new load is `PLANNED` on the logistics dimension and `OPEN` on the settlement dimension, with `loaded_tons` — the read-only sum of tons across its open allocations — at 0.0.

Allocations bind three things together: a delivery load, a contract, and a bale lot. Creating one manually takes `delivery_load_id`, `contract_id`, `bale_lot_id`, a positive `tons` figure, and `expected_delivery_load_version` matching the load's current `version` per §2.7 (`ERR_STALE_VERSION` on mismatch). The guards stack in the order of §2.6: the referenced load, contract, and lot must each resolve (`ERR_LOAD_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`); the contract must be `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`; the lot must be `ACTIVE` — a `DEPLETED` lot fails here with `ERR_LOT_NOT_ACTIVE` — while a `CONDEMNED` lot falls through to the safety rule and is rejected with `ERR_LOT_CONDEMNED_UNSHIPPABLE`; the requested `tons` must not exceed the contract's `remaining_tons` at creation time (`ERR_ALLOCATION_EXCEEDS_REMAINING`); and the load's `loaded_tons` plus the new tons must not exceed the load's `capacity_tons` (`ERR_LOAD_CAPACITY_EXCEEDED`). Success creates the allocation in `OPEN` status and applies its reservation in three places at once: the lot's `open_allocated_tonnage` increases by the allocated tons, the contract's `open_allocated_tons` increases by the same amount, and the load's `loaded_tons` increases likewise, with the load's `version` incremented by one. Allocations may be listed with optional `delivery_load_id`, `contract_id`, `bale_lot_id`, and `status` filters, sorted by creation ascending.

Rather than allocating by hand, `BrokerOps` or `PlatformAdmin` may ask the server to auto-allocate a load, a waterfall that fills available capacity across eligible contracts and lots. Eligible contracts are those `ACTIVE` with `remaining_tons` greater than zero, ranked by earliest `delivery_deadline` first, ties broken by earliest `created_at` (and then by creation sequence); when no eligible contract exists the attempt is rejected with `ERR_NO_ELIGIBLE_CONTRACT`. Eligible lots for a given contract are those `ACTIVE`, carrying a `quality_tier` equal to the contract's tier, and having `allocatable_tonnage` greater than zero, ranked by earliest `harvested_date` first, ties broken by earliest `created_at` (and then by creation sequence). The waterfall then works down the contract ranking while capacity remains: for each contract it takes the lesser of the contract's `remaining_tons` and the load's remaining capacity (`capacity_tons` minus `loaded_tons`), skipping the contract when that amount is zero or negative; within the contract it works down the lot ranking while tonnage remains to be placed, taking from each lot the lesser of its `allocatable_tonnage` and the amount still to be placed — skipping lots with nothing to give — and creating an allocation for each take. Partial fills are the norm: tonnage is carried to two decimals and a contract may be satisfied across several lots just as a lot may feed several contracts. If the waterfall runs to completion having created no allocation at all — whether because no active graded lot matched any eligible contract's tier or because every matching lot had nothing allocatable to give — the attempt is rejected with `ERR_NO_ELIGIBLE_LOT`. Each created allocation applies the same three-place reservation as a manual allocation, and the operation increments the load's `version` by one in total, regardless of how many allocations were created. A successful auto-allocation responds `200 OK` with `response_type` "array" and the created allocations (in creation order) as `data`.

An open allocation may be released by `BrokerOps` or `PlatformAdmin` — the transition from `OPEN` to `RELEASED` is rejected with `ERR_INVALID_STATE` when attempted from any state other than `OPEN`, and the owning load must still be `PLANNED` or `LOADING`, otherwise `ERR_LOAD_WRONG_STATE`. Release returns the reserved tonnage everywhere it was held: the lot's `open_allocated_tonnage`, the contract's `open_allocated_tons`, and the load's `loaded_tons` each decrease by the released tons, and if the load was `LOADING` and no open allocations remain, it automatically reverts to `PLANNED`.

On the logistics dimension, moving a `PLANNED` load to `LOADING` requires at least one open allocation against the load; an empty load cannot start loading, and any from-state mismatch draws `ERR_LOAD_WRONG_STATE`. Departing moves a `LOADING` load to `IN_TRANSIT`. Delivery — from `IN_TRANSIT` to `DELIVERED` — fires the system's three-hop cascade. Hop one: every open allocation on the load becomes `DELIVERED`; for each, the lot's `shipped_tonnage` increases by the allocated tons and its `open_allocated_tonnage` decreases by the same, the contract's `delivered_tons` increases by the allocated tons and its `open_allocated_tons` decreases by the same, the load's `loaded_tons` decreases by the allocated tons, and the derived tonnage fields recompute. Hop two: any still-`ACTIVE` contract whose `delivered_tons` now reaches or exceeds `committed_tons` transitions to `FULFILLED`, and any still-`ACTIVE` lot whose `allocatable_tonnage` has reached exactly 0.0 with `shipped_tonnage` greater than zero transitions to `DEPLETED`. Hop three: each contract that fulfilled in hop two releases its credit reserve, subtracting `total_reserved_cents` from the buyer's `credit_used_cents`.

Settlement is the financial close of a delivered load and moves `settlement_status` from `OPEN` to `SETTLED`; it requires the settlement dimension to be `OPEN` and the logistics dimension to be `DELIVERED`, with mismatches rejected as `ERR_LOAD_WRONG_STATE`. The settle operation writes the grower-proceeds lines described next and leaves `logistics_status` untouched at `DELIVERED`.

### 3.8. Grower Settlement: Commission Tiers and the Protein Bonus

Settlement converts delivered tonnage into grower proceeds, and its evaluation order is pinned because the commission tier depends on a running total. The load's `DELIVERED` allocations are processed in `created_at` ascending order — never by id. For each allocation, the grower is resolved by walking the chain from the bale lot to its cutting, to the cutting's field, to the field's grower. The commission rate is then read off the grower's `settled_tons_ytd` *before* the allocation's tons are added: while the year-to-date figure is below 500 tons the rate is 8 percent; once it has reached at least 500 but remains below 1500 tons the rate is 6 percent — a year-to-date of exactly 500 tons pays 6 percent; and at 1500 tons or more the rate is 4 percent.

The gross proceeds for an allocation are the allocation's tons multiplied by the contract's `unit_price_cents`, with a 2 percent protein bonus added when the lot's `certified_protein_pct` is at least 20.0, and the result rounded half-up to whole cents. The commission is then computed on the gross — never on the net — at the rate just determined, itself rounded half-up to whole cents. The net is the gross minus the commission. The system writes the allocation's `settled_gross_cents`, `settled_commission_cents`, and `settled_net_cents` — all three null until this moment — moves the allocation to `SETTLED`, and only then adds the allocation's tons to the grower's `settled_tons_ytd`, so the next allocation in the sequence is tiered against the updated cumulative figure.

### 3.9. Custom Baling: Service Orders from Request to Invoice

Beyond brokerage, the platform runs custom baling for growers. A `Grower` (or `PlatformAdmin`) requests a service order with a `grower_id` and the `cutting_id` to be baled; the referenced grower must be `ACTIVE` (`ERR_GROWER_SUSPENDED`), and the order begins `REQUESTED` with `scheduled_date`, `equipment_unit`, `actual_bale_count`, `baled_moisture_pct`, and `invoice_cents` all unset. Orders may be listed with optional `grower_id`, `cutting_id`, and `status` filters; an acting `Grower` always sees only their own orders, any supplied `grower_id` filter being overridden by the acting grower's id, and single-order fetches are owner-enforced for the `Grower` role.

`BrokerOps` schedules a `REQUESTED` order — from any other state, `ERR_BSO_WRONG_STATE` — by supplying a `scheduled_date` and an `equipment_unit`. Two conditions guard scheduling: the referenced cutting must be `WINDOW_OPEN` or `CUT` (again `ERR_BSO_WRONG_STATE`), since baling hay that is not yet in or past its window is pointless; and the equipment buffer requires that no other order on the same `equipment_unit` in `SCHEDULED` or `IN_PROGRESS` status have a scheduled date within less than two days of this one — the absolute difference between the two dates must be at least two days, guaranteeing one idle day between jobs — otherwise `ERR_EQUIPMENT_BUFFER_CONFLICT`. Scheduling stamps `scheduled_date` and `equipment_unit` and moves the order to `SCHEDULED`.

Starting a `SCHEDULED` order moves it to `IN_PROGRESS`. Completing an `IN_PROGRESS` order records the `actual_bale_count` and the `baled_moisture_pct`, subject to a hard safety gate: bale moisture above 20.0 is unsafe, and completion with such a reading is rejected outright with `ERR_MOISTURE_UNSAFE`; a reading of exactly 20.0 or below completes normally. The `actual_bale_count` must be a non-negative integer — zero is allowed, and a negative count fails schema validation with `ERR_INVALID_REQUEST`.

After completion the order can travel two roads. The grower who owns the order — ownership enforced, `ERR_FORBIDDEN_OWNERSHIP` — may dispute the count or the charges, moving a `COMPLETED` order to `DISPUTED`; `BrokerOps` then resolves the dispute, returning the order from `DISPUTED` to `COMPLETED`, and the dispute loop may repeat. Alternatively, `BrokerOps` invoices a `COMPLETED` order, which computes the bill, sets `invoice_cents`, adds that amount to the grower's `outstanding_balance_cents`, and moves the order to terminal `INVOICED`. Separately, an order in `REQUESTED` or `SCHEDULED` may be cancelled by the owning grower or an administrator — from any other state, `ERR_BSO_WRONG_STATE` — and orders in those two states are also cancelled automatically when their grower is suspended or their cutting is abandoned.

The invoice amount is computed by a marginal per-bale tier schedule with a pinned evaluation order. The subtotal prices each bale at its marginal rate: the first 500 bales at 1200 cents apiece, bales 501 through 1000 at 1050 cents apiece, and every bale beyond 1000 at 900 cents apiece. A wet surcharge of 15 percent of the subtotal, rounded half-up to whole cents, is added when the recorded `baled_moisture_pct` exceeds 18.0 — a reading of exactly 18.0 pays no surcharge. The invoice is then the subtotal plus any surcharge, but never less than the minimum charge of 600000 cents; the minimum is applied last, after the surcharge, so a small wet job still bills at least the floor. Recall the safety gate from completion: moisture above 20.0 never reaches invoicing at all, since such an order cannot complete.

## 4. Endpoint Definitions

All resources are mounted under the `/api` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state-transition actions, return `200 OK`. The table below is a summary only — request payloads, response bodies, side effects, and guard conditions are defined by the workflows in §3 and the principles in §2, and readers must reconstruct the complete contract from those sections.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock; sweeps expired quotes and re-dates shrink computations | PlatformAdmin |
| POST | `/api/growers` | Create a grower | PlatformAdmin |
| GET | `/api/growers/{id}` | Get a grower | PlatformAdmin, BrokerOps, Grower |
| POST | `/api/growers/{id}/suspend` | Suspend a grower; cancels their REQUESTED/SCHEDULED baling orders | PlatformAdmin |
| POST | `/api/fields` | Create a field for an ACTIVE grower | PlatformAdmin, Grower |
| GET | `/api/fields` | List fields, optionally by grower | PlatformAdmin, BrokerOps, Grower |
| GET | `/api/fields/{id}` | Get a field | PlatformAdmin, BrokerOps, Grower |
| POST | `/api/cuttings` | Schedule a cutting; planned windows on one field are half-open non-overlapping | PlatformAdmin, Grower |
| GET | `/api/cuttings` | List cuttings with filters | PlatformAdmin, BrokerOps, Grower |
| GET | `/api/cuttings/{id}` | Get a cutting | PlatformAdmin, BrokerOps, Grower |
| POST | `/api/cuttings/{id}/mark-cut` | Mark the cutting as cut on a supplied date (weather-window guarded) | PlatformAdmin, Grower |
| POST | `/api/cuttings/{id}/abandon` | Abandon a scheduled/open cutting; cancels dependent baling orders | PlatformAdmin, Grower |
| POST | `/api/weather-reports` | Post a daily weather report; re-evaluates cutting weather windows in the region | PlatformAdmin |
| POST | `/api/storage-sites` | Create a storage site | PlatformAdmin |
| GET | `/api/storage-sites` | List storage sites | PlatformAdmin, BrokerOps |
| GET | `/api/storage-sites/{id}` | Get a storage site | PlatformAdmin, BrokerOps |
| GET | `/api/storage-sites/{id}/occupancy` | Computed read: current physical occupancy of the site | PlatformAdmin, BrokerOps |
| POST | `/api/bale-lots` | Create a bale lot from a CUT/HARVESTED cutting into a storage site (capacity-checked) | BrokerOps, PlatformAdmin |
| GET | `/api/bale-lots` | List bale lots with filters | PlatformAdmin, BrokerOps |
| GET | `/api/bale-lots/{id}` | Get a bale lot (computed tonnages at current clock) | PlatformAdmin, BrokerOps |
| POST | `/api/bale-lots/{id}/condemn` | Condemn a lot; releases its open allocations and replans LOADING loads | BrokerOps, PlatformAdmin |
| POST | `/api/bale-lots/{id}/transfer` | Move a lot to another storage site (OCC-guarded; destination capacity-checked) | BrokerOps, PlatformAdmin |
| POST | `/api/spoilage-events` | Record a spoilage loss against a lot | BrokerOps, PlatformAdmin |
| GET | `/api/bale-lots/{id}/spoilage-events` | List spoilage events for a lot | PlatformAdmin, BrokerOps |
| POST | `/api/forage-tests` | Collect a sample from a lot (creates test in COLLECTED) | BrokerOps, PlatformAdmin |
| GET | `/api/forage-tests` | List forage tests with filters | PlatformAdmin, BrokerOps, LabTechnician |
| GET | `/api/forage-tests/{id}` | Get a forage test | PlatformAdmin, BrokerOps, LabTechnician |
| POST | `/api/forage-tests/{id}/submit` | Submit (or resubmit for retest) a sample to the lab | LabTechnician |
| POST | `/api/forage-tests/{id}/record-result` | Record RFV/protein/moisture results | LabTechnician |
| POST | `/api/forage-tests/{id}/certify` | Certify a result (segregation of duties); writes the lot's quality tier | LabTechnician |
| POST | `/api/forage-tests/{id}/invalidate` | Invalidate a COLLECTED/SUBMITTED test | LabTechnician, BrokerOps |
| POST | `/api/market-indices` | Post a market index; drought regime computed against the 30-day lookback | PlatformAdmin |
| GET | `/api/market-indices` | List market indices with filters | PlatformAdmin, BrokerOps, Buyer |
| POST | `/api/buyers` | Create a buyer | PlatformAdmin |
| GET | `/api/buyers/{id}` | Get a buyer | PlatformAdmin, BrokerOps, Buyer |
| POST | `/api/buyers/{id}/suspend` | Suspend a buyer; suspends their ACTIVE contracts | PlatformAdmin |
| POST | `/api/freight-lanes` | Create a freight lane | PlatformAdmin |
| POST | `/api/quotes` | Create a DRAFT freight-inclusive quote (spot pricing at current clock) | Buyer |
| GET | `/api/quotes` | List quotes (Buyers see only their own) with filters | PlatformAdmin, BrokerOps, Buyer |
| GET | `/api/quotes/{id}` | Get a quote (owner-enforced for Buyer role) | PlatformAdmin, BrokerOps, Buyer |
| PATCH | `/api/quotes/{id}` | Update a DRAFT quote's tons/destination/deadline (OCC-guarded); reprices spot | Buyer |
| POST | `/api/quotes/{id}/issue` | Issue a DRAFT quote: pins the current market index and starts the 72h validity window | Buyer |
| POST | `/api/quotes/{id}/revise` | Return an ISSUED quote to DRAFT for repricing (OCC-guarded) | Buyer |
| POST | `/api/quotes/{id}/accept` | Accept an ISSUED quote (OCC-guarded); creates the Contract and reserves buyer credit | Buyer |
| POST | `/api/quotes/{id}/decline` | Decline an ISSUED quote | Buyer |
| GET | `/api/contracts` | List contracts with filters | PlatformAdmin, BrokerOps, Buyer |
| GET | `/api/contracts/{id}` | Get a contract | PlatformAdmin, BrokerOps, Buyer |
| POST | `/api/contracts/{id}/cancel` | Cancel an ACTIVE/SUSPENDED contract; releases allocations and the credit reserve | PlatformAdmin |
| POST | `/api/contracts/{id}/declare-default` | Declare default on a past-deadline under-delivered contract | PlatformAdmin |
| POST | `/api/delivery-loads` | Create a delivery load | BrokerOps, PlatformAdmin |
| GET | `/api/delivery-loads/{id}` | Get a delivery load | PlatformAdmin, BrokerOps |
| POST | `/api/delivery-loads/{id}/start-loading` | PLANNED to LOADING (requires at least one OPEN allocation) | BrokerOps, PlatformAdmin |
| POST | `/api/delivery-loads/{id}/depart` | LOADING to IN_TRANSIT | BrokerOps, PlatformAdmin |
| POST | `/api/delivery-loads/{id}/deliver` | IN_TRANSIT to DELIVERED; runs the 3-hop delivery cascade | BrokerOps, PlatformAdmin |
| POST | `/api/delivery-loads/{id}/settle` | OPEN to SETTLED (requires DELIVERED); runs grower settlement | BrokerOps, PlatformAdmin |
| POST | `/api/delivery-loads/{id}/auto-allocate` | Waterfall partial-load allocation across eligible contracts and lots | BrokerOps, PlatformAdmin |
| POST | `/api/load-allocations` | Manually allocate lot tonnage to a contract on a load (OCC-guarded on the load) | BrokerOps, PlatformAdmin |
| GET | `/api/load-allocations` | List allocations with filters; results sorted by created_at ascending | PlatformAdmin, BrokerOps |
| GET | `/api/load-allocations/{id}` | Get an allocation | PlatformAdmin, BrokerOps |
| POST | `/api/load-allocations/{id}/release` | Release an OPEN allocation; reserved tonnage returns to the lot and contract | BrokerOps, PlatformAdmin |
| POST | `/api/baling-service-orders` | Request custom baling of a cutting | Grower, PlatformAdmin |
| GET | `/api/baling-service-orders` | List baling orders with filters | PlatformAdmin, BrokerOps, Grower |
| GET | `/api/baling-service-orders/{id}` | Get a baling order | PlatformAdmin, BrokerOps, Grower |
| POST | `/api/baling-service-orders/{id}/schedule` | Schedule the job on an equipment unit (buffer-day rule; cutting must be WINDOW_OPEN or CUT) | BrokerOps, PlatformAdmin |
| POST | `/api/baling-service-orders/{id}/start` | SCHEDULED to IN_PROGRESS | BrokerOps, PlatformAdmin |
| POST | `/api/baling-service-orders/{id}/complete` | IN_PROGRESS to COMPLETED (moisture safety gate) | BrokerOps, PlatformAdmin |
| POST | `/api/baling-service-orders/{id}/dispute` | COMPLETED to DISPUTED (grower disputes the count/charges) | Grower, PlatformAdmin |
| POST | `/api/baling-service-orders/{id}/resolve` | DISPUTED to COMPLETED (dispute resolved, billing may proceed) | BrokerOps, PlatformAdmin |
| POST | `/api/baling-service-orders/{id}/invoice` | COMPLETED to INVOICED; computes the bill and debits the grower | BrokerOps, PlatformAdmin |
| POST | `/api/baling-service-orders/{id}/cancel` | REQUESTED/SCHEDULED to CANCELLED | Grower, PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined where they arise in §2 and §3; this catalogue is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_GROWER_NOT_FOUND` | 404 |
| `ERR_FIELD_NOT_FOUND` | 404 |
| `ERR_CUTTING_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_TEST_NOT_FOUND` | 404 |
| `ERR_BUYER_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_LOAD_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_BSO_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CUTTING_NOT_OPEN` | 409 |
| `ERR_CUTTING_WINDOW_RANGE` | 422 |
| `ERR_LOT_NOT_ACTIVE` | 409 |
| `ERR_TEST_WRONG_STATE` | 409 |
| `ERR_QUOTE_NOT_ISSUABLE` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_LOAD_WRONG_STATE` | 409 |
| `ERR_BSO_WRONG_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_MOISTURE_UNSAFE` | 422 |
| `ERR_LOT_CONDEMNED_UNSHIPPABLE` | 422 |
| `ERR_FIELD_WINDOW_OVERLAP` | 409 |
| `ERR_EQUIPMENT_BUFFER_CONFLICT` | 409 |
| `ERR_DEADLINE_NOT_PASSED` | 422 |
| `ERR_DUPLICATE_CUTTING_NUMBER` | 409 |
| `ERR_DUPLICATE_WEATHER_REPORT` | 409 |
| `ERR_DUPLICATE_MARKET_INDEX` | 409 |
| `ERR_DUPLICATE_FREIGHT_LANE` | 409 |
| `ERR_TONS_NOT_POSITIVE` | 422 |
| `ERR_UNGRADED_TIER` | 422 |
| `ERR_NO_MARKET_INDEX` | 422 |
| `ERR_NO_FREIGHT_LANE` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_LOAD_CAPACITY_EXCEEDED` | 422 |
| `ERR_ALLOCATION_EXCEEDS_REMAINING` | 422 |
| `ERR_NO_ELIGIBLE_CONTRACT` | 422 |
| `ERR_NO_ELIGIBLE_LOT` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_GROWER_SUSPENDED` | 422 |
| `ERR_BUYER_SUSPENDED` | 422 |
| `ERR_CUTTING_NOT_CUT` | 422 |

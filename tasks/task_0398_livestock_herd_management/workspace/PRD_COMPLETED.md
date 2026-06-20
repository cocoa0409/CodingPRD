# Livestock Herd Management API — Product Requirements Document

## 1. Introduction

Modern livestock operations live and die by their records. A single animal accumulates a long paper trail over its lifetime — where it was born, who its dam and sire were, every pasture and pen it grazed, every vaccine and antibiotic it received, every weighing, and finally how it left the operation, whether through the sale ring, the cull pen, or the mortality book. When that trail is incomplete or inconsistent, the consequences are not merely administrative: an animal sold while a drug withdrawal period is still running can taint the human food supply, and a herd whose stocking density silently exceeds a pasture's carrying capacity invites both regulatory penalties and degraded land.

This document specifies the Livestock & Herd Management API, a system of record that ties identification, breeding, feeding, health, movement, and sale into one traceable whole. The API is organized around a flat set of peer aggregates — herds, pastures, drug products, and feed rations are configured independently, and animals together with their many event records (weights, treatments, movements, mortalities) and sale objects reference those aggregates. Two concerns dominate the design. The first is **compliance and traceability**: every life event appends to an append-only trace chain, and residue-safety rules block the sale or cull of any animal still under a meat withdrawal. The second is **temporal correctness**: withdrawal clearances, grazing rest periods, gestation windows, and a rolling mortality rate are all driven by a controllable system clock, so the same record can mean different things as time advances.

The intended operators are role-specialized. A herd manager owns the animal inventory, breeding, movement, and mortality books; a veterinarian owns the drug catalogue, treatments, and pregnancy confirmation; a sale clerk assembles lots and prices weight tickets; a feedlot operator maintains rations and records weights; and an auditor reads the whole trace surface without changing anything. The sections that follow define the global contract first, then the business workflows where the detailed rules live, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`; a header is treated as missing or malformed when it is absent, empty, or blank after trimming whitespace. The system recognizes exactly five roles, spelled precisely as follows: `HerdManager`, `Veterinarian`, `SaleClerk`, `FeedlotOperator`, and `Auditor`. An `X-User-Role` value that is not one of these five recognized roles is itself treated as malformed and likewise rejected with `ERR_UNAUTHENTICATED` (not `ERR_FORBIDDEN`). When an authenticated user — one presenting both headers with a recognized role — attempts an operation that their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN`.

The `HerdManager` owns animal registration, life-status changes, breeding records and their transitions, movement planning and application, mortality recording, and the setup of herds and pastures. The `Veterinarian` owns the drug-product catalogue, health treatments and their voiding, and the confirmation of pregnancy on a breeding record. The `SaleClerk` owns sale lots, weight tickets, and sale finalization or withdrawal. The `FeedlotOperator` owns feed rations and may also record animal weights. The `Auditor` is read-only and may read every collection, herd summary, and trace chain, but may write nothing.

For all five roles, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`; access control is governed entirely by `X-User-Role` together with the per-endpoint authorization in §4. There are no resource-ownership comparisons in this system — a `HerdManager` is any user presenting that role, regardless of which `HerdManager` first created a given herd.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the front of the result; it defaults to 0 and may not be negative. A `limit` outside the range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. The one deliberate exception is the per-animal trace chain, which is ordered by the business date of each event and then by creation timestamp, as described in §3.

List responses carry the pagination state in the `meta` object via the fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of matching items before the limit/offset window is applied and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties and Audit Trail

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that starts at its initial value of 1 on creation and increments by one on every mutation of the resource.

Two record types are immutable history and therefore deliberately lighter: a `WeightRecord` and a `TraceEvent` carry only `id` and `created_at` — they have no `updated_at` and no `version`, because once written they are never modified in place. Every other entity — herds, pastures, drug products, feed rations, animals, breeding records, health treatments, movement records, sale lots, weight tickets, and mortality records — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

The `version` field doubles as the concurrency token described in §2.6. Note carefully that derived (computed) fields participate in versioning exactly like input fields: when an animal's `latest_weight_kg` is recomputed because a new weight was recorded, or when a herd's `total_au_load` shifts because an animal changed life status, that animal or herd is considered mutated, its `updated_at` is refreshed, and its `version` increments.

### 2.5. Nested Resource Retrieval and Reference Validation

Several endpoints address a resource through a path that names a parent before a child — for example, listing the weight records, the trace chain, or the weight tickets that hang off a specific parent. For every such request, the system validates the path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. The same left-to-right existence discipline governs foreign-key fields supplied in a request body: before any business rule is evaluated, every referenced resource named in the path and in the body's foreign-key fields must exist, or the request fails with `ERR_NOT_FOUND`.

This ordering matters because it precedes — and can pre-empt — the deeper business validations. The relative priority of all checks is fixed: authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then role authorization (`ERR_FORBIDDEN`), then referenced-resource existence (`ERR_NOT_FOUND`), then request-shape validation of required fields, types, enum domains, and numeric ranges (`ERR_INVALID_REQUEST`), and only then the state-transition legality check (`ERR_INVALID_STATE`) for state-changing endpoints. The remaining domain-specific business rules described throughout §2 and §3 are evaluated after these foundational layers; where two domain rules could both apply to one request, the priority noted in their respective narratives governs which error surfaces.

### 2.6. Optimistic Concurrency on Lot and Animal Writes

Two write operations are protected by optimistic concurrency control, and only these two carry a version-expectation field; no other endpoint accepts one. Both reject a stale write with `ERR_STALE_VERSION` (HTTP 412).

The first is attaching a weight ticket to a sale lot. That request must carry `expected_sale_lot_version`, holding the `version` of the target sale lot as the client last observed it. If the lot's current `version` has advanced beyond that value — because another writer has already attached a ticket (legitimately changing `head_count` and the lot's pricing basis) or withdrawn the lot — the client's view of the lot is stale and the create is rejected with `ERR_STALE_VERSION`, so the new ticket is never committed against an out-of-date lot.

The second is applying a planned movement. That request must carry `expected_animal_version`, holding the `version` of the animal being moved as the client last observed it. If the animal's current `version` has advanced beyond that value — because another writer has already applied a different movement, changing the animal's `current_pasture_id` and the animal-unit attribution — then this client's intended location change was computed against a stale location and is rejected with `ERR_STALE_VERSION`. In both cases the rejection is framed purely in terms of a version mismatch against the parent's present `version`; the client must re-read the parent and retry.

### 2.7. Animal-Unit Load and Stocking Capacity

Stocking density across the operation is measured in **animal units (AU)**. A single animal's AU contribution is its `latest_weight_kg` divided by 454 (the kilograms-per-animal-unit constant), and this per-animal value is kept at full precision — it is never rounded on a per-animal basis. Only the aggregates are rounded.

A pasture's `current_au_load` is the sum of the AU contributions of all animals whose `current_pasture_id` equals that pasture and whose `life_status` is either `ACTIVE` or `SUSPENDED`, with the resulting sum rounded to three decimal places. A herd's `total_au_load` is the sum of the AU contributions of all animals in that herd whose `life_status` is `ACTIVE` or `SUSPENDED`, again summed first and then rounded to three decimal places. These loads are recomputed whenever an animal is created, a weight is recorded, a movement is applied or reverted, or an animal's life status changes.

The capacity gate that guards a movement application is computed differently from the stored loads, and the difference is deliberate: the gate uses the **unrounded** aggregate. When a movement is applied, the system projects the destination's load by summing the full-precision AU of every animal already occupying that destination during the overlap window and adding the moving animal's full-precision AU. The movement is rejected only when this projected aggregate is strictly greater than the pasture's `capacity_au`; a projection exactly equal to the capacity is allowed to proceed.

### 2.8. Withdrawal Residue Safety and the Clock

A defining safety concern of this system is the **meat withdrawal period**: the interval after a drug treatment during which an animal's meat may not enter the food chain. Each animal carries a residue dimension, `meat_clearance_status`, that evolves independently of its life status and toggles between `CLEAR` and `WITHHELD`, alongside a `meat_clear_on` date that records the latest clearance date currently in force. While any treatment imposes an unexpired withdrawal, the animal is `WITHHELD`; once the controlling clearance date has passed and no treatment still withholds, it returns to `CLEAR`.

Because clearances are date-driven, the system exposes a controllable logical clock. An administrative test-driving capability sets the current UTC instant to a supplied `to_iso8601` value, returning a `data` object of the shape `{ "current_utc": <the new instant as an ISO 8601 UTC timestamp with three fractional digits> }`, and setting the clock is the trigger that re-derives residue state: every health treatment in `WITHDRAWAL_ACTIVE` whose clearance date is on or before the new clock date auto-transitions to `CLEARED`, and any animal that no longer has a treatment withholding it past the clock returns to `CLEAR`. All date comparisons in this system are performed at date granularity in UTC; withdrawal arithmetic and gestation arithmetic are whole-day date arithmetic.

The residue rule has teeth at the point of disposition: an animal whose `meat_clearance_status` is `WITHHELD` may not be ticketed onto a sale lot, may not be sold, and may not be culled. All three of those rejections carry `ERR_WITHDRAWAL_NOT_CLEARED`.

### 2.9. Precision and Rounding

Unless a calculation states otherwise, every rounding in this system uses the round-half-up method. The decimal scale, however, varies by quantity and is fixed per field. Animal-unit loads (`total_au_load`, `current_au_load`) and the gain figures (`lifetime_adg_kg`, `interval_adg_kg`) are carried to three decimal places, as is a weight ticket's `net_weight_kg` and a ration's `as_fed_kg` allocations. Monetary amounts — a sale lot's `gross_sale_amount`, `commission_amount`, and `net_proceeds`, and a weight ticket's `price_per_100kg` and `gross_line_amount` — are carried to two decimal places, as is a herd's `mortality_rate_pct`. Date-derived quantities (clearance dates, expected calving dates) are whole-day dates with no fractional component.

### 2.10. Compensating Actions and Inventory Conservation

Several operations are compensating reversals whose purpose is to restore the world to its prior state without leaving the books unbalanced. Voiding a mortality record reactivates the animal and restores the herd counters it had decremented; reverting an applied movement restores the animal's prior location and undoes the AU attribution on both pastures; voiding a health treatment recomputes the animal's clearance date from the treatments that remain. In each case the invariant is conservation: the herd's `active_animal_count` and `total_au_load`, and each pasture's `current_au_load`, must return to values consistent with the set of live animals and applied movements after the reversal, exactly as if the reversed event had never occurred. The detailed cascades for each reversal are specified in §3 alongside the workflow they undo.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Operation: Herds, Pastures, Drugs, and Rations

Before any animal can be registered, a herd manager establishes the operating units. A **herd** is created with a display `name` of 1 to 120 characters, a `species` that is one of `CATTLE`, `SHEEP`, or `GOAT`, and a regulatory `premises_id` of 1 to 40 characters that must be unique across all herds and is later used in traceability exports; a duplicate `premises_id` is rejected with `ERR_INVALID_REQUEST` (not `ERR_DUPLICATE_IDENTIFIER`). The species is consequential: it fixes the gestation length used when projecting calving and informs weight-unit defaults. A freshly created herd initializes its computed inventory figures to zero — `active_animal_count` at 0, `total_au_load` at 0, and `mortality_rate_pct` at 0 — and these are recomputed as animals come and go. The `active_animal_count` is the count of animals in the herd whose `life_status` is `ACTIVE` or `SUSPENDED`, and it is recomputed on every life-status transition.

A **pasture** (which also models a confined pen) is created with a `name` of 1 to 80 characters, a `kind` that is either `PASTURE` or `PEN`, a `capacity_au` that must be greater than zero, and an optional `rest_days` integer that defaults to 0 and may not be negative. The `rest_days` value matters only for the `PASTURE` kind, where it is the mandatory grazing rest gap separating one occupancy from the next; for a `PEN` it is ignored. A pasture's `current_au_load` starts at 0 and is maintained as animals move in and out.

A **drug product** is registered by a veterinarian with a trade `name` of 1 to 120 characters, a `category` that is one of `VACCINE`, `ANTIBIOTIC`, `ANTIPARASITIC`, or `HORMONE`, a `route_withdrawals` map, and an optional `milk_withdrawal_hours` integer (defaulting to 0, never negative) that applies only to lactating dams. The `route_withdrawals` map associates each permitted administration route with a meat-withdrawal duration in whole days; its keys are drawn from the set `INJECTION_IM`, `INJECTION_SC`, `ORAL`, `TOPICAL_POUR_ON`, and `INTRAMAMMARY`, and its values are non-negative integers. The map is required and must be a non-empty object containing at least one route; a missing map, an empty map, a key outside the permitted set, or a value that is not a non-negative integer is rejected with `ERR_INVALID_REQUEST`. A route absent from the map is simply not permitted for that product — there is no fallback. As a rule of thumb, vaccines carry no meat withdrawal while antibiotics and antiparasitics typically do, but the authoritative withdrawal for any treatment is whatever the chosen route maps to.

A **feed ration** is created by a feedlot operator with a `name` of 1 to 80 characters, a `target_dmi_kg` (target dry-matter intake per head per day, in kilograms) that must be greater than zero, and an `ingredients` array of at least one entry. Each ingredient names a `feedstuff`, a `dry_matter_pct` in the half-open range above 0 and up to 1, a `max_inclusion_pct` likewise above 0 and up to 1, and a `cost_per_kg_as_fed` that is at least 0. The order of the ingredients is significant and is described in §3.7. A ration's `status` initializes to `ACTIVE` (the alternative being `ARCHIVED` once retired).

### 3.2. Registering Animals and Pedigree

An animal enters the system when a herd manager registers it. Registration supplies the owning `herd_id`, a visual `ear_tag` of 1 to 32 characters, an optional electronic `rfid`, a `sex` that is one of `MALE`, `FEMALE`, or `STEER`, a `birth_date` (an ISO 8601 date that may not be later than the current clock date; a future `birth_date` is rejected with `ERR_INVALID_REQUEST`), and a recorded `birth_weight_kg` greater than zero. Two identity rules guard registration: the `ear_tag` must be unique within its herd, so a duplicate ear tag inside the same `herd_id` is rejected with `ERR_DUPLICATE_IDENTIFIER`, and an `rfid`, when present, must be globally unique across every animal, with a collision likewise rejected as `ERR_DUPLICATE_IDENTIFIER`.

Pedigree is captured through two optional self-referential links: `dam_animal_id` points to the mother and `sire_animal_id` to the father. When supplied, the referenced animals must satisfy a sex constraint — a `dam_animal_id` must reference an animal whose `sex` is `FEMALE`, and a `sire_animal_id` must reference an animal whose `sex` is `MALE`. A pedigree link that violates either rule is rejected with `ERR_INVALID_PEDIGREE`. This same pedigree check governs breeding-record creation, where the named dam and sire are subject to the identical sex constraints, and it also governs calf creation, where the calf is linked to the dam's herd.

On registration the animal initializes both of its state dimensions: `life_status` to `ACTIVE` and `meat_clearance_status` to `CLEAR`. Its computed `latest_weight_kg` initializes to the `birth_weight_kg` and stays there until a weight record exists. Its `lifetime_adg_kg` initializes to `0.0` and remains `0.0` while the animal has no weight record (and likewise whenever the span between `birth_date` and the latest weighing date is zero whole days); the location pointer `current_pasture_id` is null until the first movement is applied, and `meat_clear_on` is null while the animal is clear. Creating an animal increments the herd's `active_animal_count` by one and adds the animal's AU to the herd's `total_au_load`, and appends a `BIRTH` event to the animal's trace chain. Animals can be listed and filtered by their `herd_id`, `dam_animal_id`, `sire_animal_id`, or `current_pasture_id`, which is how the pedigree and location relationships are navigated.

### 3.3. The Animal Life-Status Dimension

An animal's primary lifecycle dimension, `life_status`, moves through the states `ACTIVE`, `SUSPENDED`, `SOLD`, `DEAD`, and `CULLED`, of which `SOLD`, `DEAD`, and `CULLED` are terminal. A herd manager drives the manual transitions by supplying a `to_status` to the life-status operation; the sale and mortality cascades drive the rest. The only `to_status` values the life-status operation accepts are `SUSPENDED`, `ACTIVE`, and `CULLED` — the terminal `SOLD` and `DEAD` states are reachable only through their cascades, so a `to_status` of `SOLD` or `DEAD` (or any value outside this enum) is rejected at request-shape validation with `ERR_INVALID_REQUEST`.

Suspension and reinstatement form a revert cycle. Moving an `ACTIVE` animal to `SUSPENDED` requires that it currently be `ACTIVE`; a suspended animal remains part of inventory and continues to contribute to AU load, so the herd's `active_animal_count` is deliberately left unchanged on suspension (suspension is used for quarantine or hold, not removal). The transition appends a `SUSPEND` trace event. Moving a `SUSPENDED` animal back to `ACTIVE` requires that it currently be `SUSPENDED` and appends a `REINSTATE` trace event. If the animal is not in the state the requested transition starts from, the request is rejected with `ERR_INVALID_STATE`.

Culling is a terminal removal driven by a `to_status` of `CULLED` on an `ACTIVE` animal. It requires that the animal be `ACTIVE` and — as a residue-safety gate — that its `meat_clearance_status` be `CLEAR`; a withheld animal cannot be culled and is rejected with `ERR_WITHDRAWAL_NOT_CLEARED`. On a successful cull the animal's `life_status` becomes `CULLED`; if it had a `current_pasture_id`, that animal's AU is subtracted from the pasture's `current_au_load`; the herd's `active_animal_count` is decremented by one and the animal's AU is subtracted from the herd's `total_au_load`; and a `CULL` trace event is appended. An attempt to cull an animal that is not `ACTIVE` fails the state check with `ERR_INVALID_STATE`; more broadly, operations that require an `ACTIVE` animal but find it `SUSPENDED`, `SOLD`, `DEAD`, or `CULLED` raise `ERR_ANIMAL_NOT_ACTIVE`.

### 3.4. Weighing and Growth Rates

Either a herd manager or a feedlot operator may record a weight against an animal. A weight record supplies a `weighed_at` date, an observed `weight_kg` greater than zero, and an optional `source` that is one of `SCALE`, `TAPE`, or `ESTIMATE`, defaulting to `SCALE`. The `weighed_at` date must be strictly after the animal's `birth_date` and not in the future relative to the clock; a weighing date that is on or before the birth date, or in the future, is rejected with `ERR_WEIGH_DATE_INVALID`. A weight record is immutable history and so carries no version of its own.

Recording a weight updates the animal's computed `latest_weight_kg`, which is the weight from the most recent weight record ordered by `weighed_at` (breaking ties by `created_at` ascending). Because the latest weight drives AU, recording a weight also recomputes the animal's pasture `current_au_load` and the herd's `total_au_load`.

Two average-daily-gain figures are computed, both rounded to three decimal places with gaps measured in whole calendar days. The **lifetime** gain, stored on the animal as `lifetime_adg_kg`, is the latest recorded weight minus the animal's `birth_weight_kg`, divided by the number of whole days between the animal's `birth_date` and the latest weighing date. The **interval** gain, stored on each new weight record as `interval_adg_kg`, is this record's `weight_kg` minus the weight of the immediately prior record, divided by the number of whole days between that prior record's `weighed_at` and this record's `weighed_at`; the prior record is the closest record ordered ahead of this one by `weighed_at` and then by `created_at` ascending — that is, the record with the greatest `(weighed_at, created_at)` pair strictly less than this record's. For the very first weight record of an animal there is no prior record, so its `interval_adg_kg` is null; likewise, when the prior record shares this record's `weighed_at` so the whole-day gap between them is zero, the `interval_adg_kg` is also null (no division by a zero-day gap is performed).

### 3.5. Breeding and Calving

Breeding is tracked through a cyclic record opened by a herd manager. Opening a breeding record names the `dam_animal_id` of the female being bred, an optional `sire_animal_id` (artificial insemination may have no on-farm sire), and a `bred_on` service date that may not be in the future (a future `bred_on` is rejected with `ERR_INVALID_REQUEST`). The dam must be an animal whose `sex` is `FEMALE` and whose `life_status` is `ACTIVE`, and any named sire must be `MALE`. The two sex constraints — dam not `FEMALE` or sire not `MALE` — surface as `ERR_INVALID_PEDIGREE` and are checked first; a dam whose sex is correct but whose `life_status` is not `ACTIVE` is instead rejected with `ERR_ANIMAL_NOT_ACTIVE`. A new record initializes its `status` to `OPEN`. The breeding lifecycle states are `OPEN`, `BRED`, `CONFIRMED_PREGNANT`, `CALVED`, and `FAILED`, with `CALVED` and `FAILED` terminal, and the record is driven between them by a transition operation that carries a `to_status`.

The transitions form a cycle so that a failed conception can return a dam to breeding. The `to_status` carried by the transition operation must be one of `BRED`, `CONFIRMED_PREGNANT`, `OPEN`, `CALVED`, or `FAILED`; any other value is rejected at request-shape validation with `ERR_INVALID_REQUEST`. The `OPEN`-to-`BRED` transition — which requires the dam to be `ACTIVE` and `FEMALE` and `bred_on` to not be in the future, and which computes the record's `expected_calving_on` as the service date plus the species gestation length — is open to either a herd manager or a veterinarian (both roles authorized on the transition endpoint may drive it). On this `BRED` transition both the sex and the life-status requirements on the dam surface as `ERR_INVALID_PEDIGREE` (a dam that is not `FEMALE` or whose `life_status` is not `ACTIVE` is rejected with `ERR_INVALID_PEDIGREE`), and a `bred_on` in the future is rejected with `ERR_INVALID_REQUEST`. A veterinarian — and only a veterinarian — confirms pregnancy by moving a `BRED` record to `CONFIRMED_PREGNANT`; a herd manager attempting that confirmation is rejected with `ERR_FORBIDDEN`. From either `BRED` or `CONFIRMED_PREGNANT`, a herd manager — and only a herd manager — may return the record to `OPEN` (modelling a failed service or a loss), which clears `expected_calving_on`. A record may also be abandoned to `FAILED` from either `OPEN` or `BRED` by a herd manager only. The `CALVED` transition described below is likewise restricted to a herd manager; for these herd-manager-only transitions a veterinarian is rejected with `ERR_FORBIDDEN`, and that role check precedes the state-legality check. Each transition is legal only from the state the scaffold permits; an out-of-order transition is rejected with `ERR_INVALID_STATE`.

Calving is the productive terminal transition: a herd manager moves a `CONFIRMED_PREGNANT` record to `CALVED`, supplying the `calved_on` date (which must be on or after `bred_on` and not in the future; a `calved_on` before `bred_on` or in the future is rejected with `ERR_INVALID_REQUEST`) along with the new calf's `calf_ear_tag`, `calf_birth_weight_kg`, and `calf_sex`. A calf whose `calf_ear_tag` duplicates an existing ear tag in the dam's herd is rejected with `ERR_DUPLICATE_IDENTIFIER`. The transition records `calved_on`, then creates a new animal — the calf — in the same herd, with its `dam_animal_id` set to this dam, its `life_status` `ACTIVE`, and its `birth_date` equal to `calved_on`; the calf's identifier is recorded back onto the breeding record as `calf_animal_id`. Creating the calf increments the herd's `active_animal_count` by one and adds the calf's AU to the herd's `total_au_load`, and appends a `BIRTH` trace event for the calf. Breeding records can be listed and filtered by `dam_animal_id`, `sire_animal_id`, or `calf_animal_id`.

The species gestation lengths are fixed constants applied to the dam's herd species: cattle gestate 283 days, sheep 147 days, and goats 150 days. Thus `expected_calving_on` is the `bred_on` date advanced by 283, 147, or 150 whole days according to whether the herd's `species` is `CATTLE`, `SHEEP`, or `GOAT`.

### 3.6. Health Treatments, Withdrawal Clearance, and Voiding

A veterinarian records a health treatment against an animal whose `life_status` is `ACTIVE` or `SUSPENDED`. A treatment names the `animal_id`, the `drug_product_id` administered, the `route` of administration, an optional `dose_count` (defaulting to 1, at least 1), a `first_dose_on` date, and a `last_dose_on` date. The `route` must be one of the permitted route values and, crucially, must be a key present in that drug product's `route_withdrawals` map; a route that is not a key in the map is rejected with `ERR_ROUTE_NOT_PERMITTED`. The dose dates must be coherent: `last_dose_on` must be on or after `first_dose_on` and not in the future, and `first_dose_on` itself may not be in the future. For a single-dose treatment the two dates are equal. A treatment whose `last_dose_on` precedes `first_dose_on`, or whose dose dates lie in the future, is rejected with `ERR_DOSE_DATES_INVALID`.

The treatment's `clearance_date` is computed as the `last_dose_on` date advanced by the number of withdrawal days the route maps to in `route_withdrawals` — so clearance always counts from the last dose, which is what makes a multi-dose course clear later than a single dose given on the first date. The treatment's own `status` then follows from the withdrawal duration: if the route's withdrawal is zero days, the treatment is created already `CLEARED` and leaves the animal's residue status untouched; if the clearance date computed above is on or before the current clock date, it is likewise created `CLEARED` (the withdrawal is already in the past); otherwise the treatment is created `WITHDRAWAL_ACTIVE` and drives the animal's residue dimension toward `WITHHELD`. The treatment status enumeration is `WITHDRAWAL_ACTIVE`, `CLEARED`, and `VOIDED`. Treatments can be listed and filtered by `animal_id` or `drug_product_id`.

When a treatment's clearance date is genuinely in the future, the animal's residue dimension reacts. If the animal was `CLEAR`, it transitions to `WITHHELD`; either way the animal's `meat_clear_on` is set to the later of its existing `meat_clear_on` and this treatment's clearance date — so stacking a second treatment on an already-withheld animal pushes the clearance later but never earlier, and the residue dimension self-loops in `WITHHELD`. Recording a treatment appends a `TREATMENT` trace event regardless of whether that treatment withholds — a treatment created already `CLEARED` (zero-day withdrawal or a clearance date already in the past) appends a `TREATMENT` event just as a `WITHDRAWAL_ACTIVE` one does; the trace event's `occurred_on` is the treatment's `last_dose_on` date. The withhold lifts only by clock advance: when the clock is set to a date on or after the animal's `meat_clear_on` and no remaining treatment for that animal still has a clearance date beyond the clock, the residue dimension returns to `CLEAR` and `meat_clear_on` is cleared to null; at the same time every one of that animal's treatments still in `WITHDRAWAL_ACTIVE` whose clearance date has been reached is auto-transitioned to `CLEARED`.

Voiding is the compensating action for a mis-entered treatment. A veterinarian may void a treatment that is currently `WITHDRAWAL_ACTIVE`, moving it to `VOIDED`; voiding from any other status fails the state check with `ERR_INVALID_STATE`. After voiding, the animal's `meat_clear_on` is recomputed as the greatest clearance date over the animal's remaining non-voided treatments whose clearance date still lies beyond the clock, and if no such treatment remains, the animal's residue dimension is driven from `WITHHELD` back to `CLEAR`. This keeps the residue picture honest: a withhold that was created only by the now-voided treatment is released immediately.

### 3.7. Feeding: The Ration Waterfall

The computed-ration capability runs a **waterfall allocation** over a ration's ingredients in their declared order and returns a `data` object of the shape `{ "total_as_fed_kg": <number>, "allocations": [ { "feedstuff", "dm_alloc_kg", "as_fed_kg" }, ... ] }`, where `allocations` lists one entry per ingredient in declared order carrying its `feedstuff` name, the full-precision dry-matter allocated (`dm_alloc_kg`), and the per-ingredient `as_fed_kg`, alongside the top-level `total_as_fed_kg`. This computed-ration read is not a persisted resource and carries no `id`, `created_at`, `updated_at`, or `version`. The waterfall begins with a remaining dry-matter budget equal to the ration's `target_dmi_kg`. It then walks the ingredients in declared order. For every ingredient except the last, the dry-matter allocated to that ingredient is the smaller of two quantities: that ingredient's `max_inclusion_pct` multiplied by the ration's `target_dmi_kg`, and whatever dry-matter budget remains. The remaining budget is reduced by each allocation as it is made. The last ingredient is the filler: it absorbs whatever dry-matter budget remains after all earlier ingredients have taken their share, which is zero if the earlier caps already consumed the whole target.

For each ingredient the as-fed quantity, `as_fed_kg`, is the dry-matter allocated to it divided by its `dry_matter_pct`, rounded to three decimal places; the dry-matter allocation itself is kept at full precision before that division. The `total_as_fed_kg` is the sum of the per-ingredient as-fed quantities, rounded to three decimal places. Two regimes naturally arise: when the non-filler caps sum to less than the target, the filler receives a positive remainder; when the non-filler caps already cover or exceed the target, the filler receives zero dry-matter and the earlier ingredients clamp to the remaining budget. The remainder can never go negative, because each cap is applied against the remaining budget, which never drops below zero.

### 3.8. Movements, Capacity, and Rest Periods

Locating animals on the ground is a two-step affair: a movement is first planned, then applied. A herd manager plans a movement by naming the `animal_id` to move, the `to_pasture_id` destination, an `effective_from` instant (an ISO 8601 UTC datetime that may not be in the future; a future `effective_from` is rejected with `ERR_INVALID_REQUEST` and is compared at full-instant — not date — granularity against the clock), and an optional `effective_to` instant marking the planned end of occupancy. The occupancy interval is half-open, covering `effective_from` up to but not including `effective_to`; when `effective_to` is present it must be strictly after `effective_from` (an `effective_to` not strictly after `effective_from` is rejected with `ERR_INVALID_REQUEST`), and when it is omitted the occupancy is open-ended. A planned movement initializes its `status` to `PLANNED`; the movement states are `PLANNED`, `APPLIED`, and `REVERTED`, with `REVERTED` terminal. Movements can be listed and filtered by `animal_id`, `to_pasture_id`, or `from_pasture_id`.

Applying a planned movement is where the location and load actually change, and it is guarded by several checks. The animal must have `life_status` of `ACTIVE` or `SUSPENDED`. The application carries `expected_animal_version` for the optimistic-concurrency check of §2.6, but that version check is evaluated only after the rest-gap and capacity gates below pass — so when a request would fail more than one of these, a rest-period or over-capacity rejection surfaces ahead of `ERR_STALE_VERSION`. For a destination of `PASTURE` kind, the grazing rest gap is enforced: the new occupancy's `effective_from` must be at least the destination pasture's `rest_days` days after the prior occupancy's `effective_to` on that same pasture; a movement that begins too soon after the previous occupancy ended is rejected with `ERR_REST_PERIOD_VIOLATION` (this gap is not enforced for a `PEN`, nor when `rest_days` is 0). A prior occupancy with no `effective_to` (open-ended) is treated as never having ended, so any new occupancy whose `effective_from` falls within `rest_days` of that prior occupancy's `effective_from` violates the gap. The capacity gate of §2.7 is then applied over the overlap window: if the unrounded projected aggregate AU at the destination during `[effective_from, effective_to)` together with the moving animal's AU would exceed the pasture's `capacity_au`, the application is rejected with `ERR_PASTURE_OVER_CAPACITY`; a projection exactly equal to capacity is permitted. The occupants counted in this projection are exactly those whose own most-recent applied movement targets this destination and who are still currently located there (`current_pasture_id` equal to the destination), whose `life_status` is `ACTIVE` or `SUSPENDED`, and whose occupancy interval overlaps the moving animal's window; an animal that has since been moved away from the destination is not counted even if its earlier applied movement targeted it.

On a successful application the movement captures `from_pasture_id` as the animal's `current_pasture_id` at apply time (null if the animal had no prior location), sets the animal's `current_pasture_id` to the `to_pasture_id`, subtracts the animal's AU from the old pasture's `current_au_load` if there was one and adds it to the destination's `current_au_load`, and appends a `MOVEMENT` trace event. Reverting a movement is the compensating action and is restricted: a herd manager may revert a movement that is currently `APPLIED`, but only if it is the animal's most recently applied movement — "most recent" is judged by the order in which the movement records were created (the later-created applied movement is the more recent), and if any applied movement for that animal was created after this one, the revert is rejected with `ERR_NOT_LATEST_MOVEMENT`. The `APPLIED`-state check is evaluated before the latest-movement check, so a revert attempted on a non-`APPLIED` movement fails the state check with `ERR_INVALID_STATE`. A successful revert restores the animal's `current_pasture_id` to the captured `from_pasture_id` and reverses the AU attribution — subtracting the animal's AU from the destination pasture's `current_au_load` and adding it back to the from pasture's `current_au_load` if a from pasture was set.

### 3.9. Sale Lots, Weight Tickets, and Pricing

A sale clerk assembles animals for sale into a **sale lot**, opened by naming the consigning `herd_id`, the `channel` (either `AUCTION` or `PRIVATE_TREATY`), an optional `pencil_shrink_pct` fraction between 0 and 0.10 inclusive (defaulting to 0), and an optional `commission_pct` fraction between 0 and 0.20 inclusive (defaulting to 0). The pencil shrink is a deduction applied to gross weight before pricing; the commission is the sale-yard cut. A private-treaty sale takes no commission: if the `channel` is `PRIVATE_TREATY` and a non-zero `commission_pct` is supplied, the lot creation is rejected with `ERR_COMMISSION_NOT_ALLOWED`. A new lot initializes its `status` to `OPEN` and its `head_count` to 0; the lot lifecycle branches from `OPEN` to either `SOLD` or `WITHDRAWN`, both terminal. Lots can be listed and filtered by `herd_id`.

Animals are added to an open lot as **weight tickets**. Attaching a ticket names the `sale_lot_id`, the `animal_id` being sold, and a scale `gross_weight_kg` greater than zero, and carries `expected_sale_lot_version` for the optimistic-concurrency check of §2.6. The lot must be `OPEN`. The animal must be saleable: its `life_status` must be `ACTIVE` and its `meat_clearance_status` must be `CLEAR` at ticket time, so a withheld animal is rejected with `ERR_WITHDRAWAL_NOT_CLEARED` (this withdrawal check is evaluated before the life-status check) and a non-active animal with `ERR_ANIMAL_NOT_ACTIVE`. The ticketed animal must belong to the same herd as the lot's `herd_id`; a mismatch is rejected with `ERR_HERD_MISMATCH`. And an animal may sit on at most one open lot at a time — attempting to ticket an animal that is already attached to another open lot is rejected with `ERR_ANIMAL_ALREADY_LISTED`. These domain checks are evaluated in a fixed order: after the lot's `OPEN` state is confirmed, the withdrawal and life-status gates are checked, then the already-listed check, then the `expected_sale_lot_version` optimistic-concurrency check (`ERR_STALE_VERSION`), and finally the herd-match check (`ERR_HERD_MISMATCH`). Attaching a ticket increments the lot's `head_count` and its `version` by one. Weight tickets can be listed under their lot and can also be listed and filtered by `animal_id` or `sale_lot_id`.

Pricing is computed in two stages with a deliberately pinned rounding order. At ticket creation, the ticket's `net_weight_kg` is the `gross_weight_kg` multiplied by one minus the lot's `pencil_shrink_pct`, rounded to three decimal places. A per-head weight class then selects the price: a net weight below 250 kilograms is the light class priced at 520.00 per 100 kilograms; a net weight of at least 250 but below 400 kilograms is the medium class priced at 480.00 per 100 kilograms; and a net weight of 400 kilograms or more is the heavy class priced at 440.00 per 100 kilograms. The selected price is recorded as `price_per_100kg`. The ticket's `gross_line_amount` is its `net_weight_kg` divided by 100 and multiplied by `price_per_100kg`, rounded to two decimal places.

### 3.10. Finalizing and Withdrawing Sales

A sale clerk finalizes a sale by selling the lot, moving it from `OPEN` to `SOLD`. The sale requires at least one ticket — selling a lot whose `head_count` is 0 is rejected with `ERR_EMPTY_LOT` — and requires every linked animal to still satisfy the residue and life-status gates: each animal's `life_status` must be `ACTIVE` and its `meat_clearance_status` must be `CLEAR`, with a withheld animal blocking the sale under `ERR_WITHDRAWAL_NOT_CLEARED` and a non-`ACTIVE` animal under `ERR_ANIMAL_NOT_ACTIVE`. All linked animals are validated before any of them are transitioned, the empty-lot check precedes these per-animal gates, and for any single animal the withdrawal gate is checked before the life-status gate.

The lot totals are computed at the moment of sale, and the rounding order is pinned to sum-then-commission. The lot's `gross_sale_amount` is the sum of the already-rounded per-ticket `gross_line_amount` values, itself rounded to two decimal places. The `commission_amount` is that gross sale amount multiplied by the lot's `commission_pct`, rounded to two decimal places, and applied once at the lot level rather than per ticket. The `net_proceeds` is the gross sale amount minus the commission amount, rounded to two decimal places. For an auction lot the commission is positive and net proceeds fall below gross; for a private-treaty lot, where the commission percentage was forced to zero, the net proceeds equal the gross sale amount.

Selling the lot then cascades to its animals: each linked animal transitions from `ACTIVE` to `SOLD`, and that per-animal transition itself does the inventory bookkeeping — setting the animal's `life_status` to `SOLD`, subtracting its AU from its `current_pasture_id` pasture's `current_au_load` if it had a location, decrementing the herd's `active_animal_count` by one and subtracting the animal's AU from the herd's `total_au_load`, and appending a `SALE` trace event keyed to the animal's weight ticket. As an alternative branch, a sale clerk may withdraw an open lot, moving it from `OPEN` to `WITHDRAWN`; withdrawal changes no animal state and leaves the tickets attached for audit, with the animals remaining `ACTIVE`. A sell or withdraw requested on a lot that is not `OPEN` fails the state check with `ERR_INVALID_STATE`.

### 3.11. Mortality and Reactivation

When an animal dies, a herd manager records a mortality against an animal whose `life_status` is `ACTIVE` or `SUSPENDED`. The record names the `animal_id`, a `died_on` date (not in the future and on or after the animal's `birth_date`; a `died_on` in the future or before the `birth_date` is rejected with `ERR_INVALID_REQUEST`, and the animal's life-status gate is checked after this date validation), a `cause` that is one of `DISEASE`, `PREDATION`, `ACCIDENT`, `CALVING`, or `UNKNOWN`, and an optional `disposal_method` that is one of `RENDERING`, `BURIAL`, `INCINERATION`, or `COMPOST`, defaulting to `RENDERING`. A new mortality record initializes its `status` to `RECORDED`; the status enumeration is `RECORDED` and `VOIDED`.

Recording a death cascades to drive the animal to `DEAD`: the animal's `life_status` is set to `DEAD`; if it had a `current_pasture_id`, its AU is subtracted from that pasture's `current_au_load`; the herd's `active_animal_count` is decremented by one, the animal's AU is subtracted from the herd's `total_au_load`, and the herd's `mortality_rate_pct` is recomputed; and a `MORTALITY` trace event is appended.

Voiding is the compensating reversal for a death entered in error. A herd manager may void a `RECORDED` mortality record, moving it to `VOIDED`, which cascades to drive the animal from `DEAD` back to `ACTIVE`. The reactivation restores the animal's `life_status` to `ACTIVE` (an animal that was suspended at the moment of death also restores to `ACTIVE`), increments the herd's `active_animal_count` by one, adds the animal's AU back to the herd's `total_au_load`, recomputes the herd's `mortality_rate_pct`, and appends a `REINSTATE` trace event. The void requires the mortality record to be `RECORDED` and the animal to be `DEAD`; a void of an already-voided record fails the state check with `ERR_INVALID_STATE`.

The herd's `mortality_rate_pct` is a rolling figure computed over a trailing 365-day window (and surfaced when a herd is read, which recomputes it). The window starts 365 days before the current clock date. The numerator is the count of mortality records for animals in the herd whose `status` is `RECORDED` and whose `died_on` date falls on or after that window start — voided records are excluded. The denominator is the herd's current `active_animal_count` plus that death count, approximating the inventory at the window's start. The rate is the deaths divided by the denominator, multiplied by 100 and rounded to two decimal places; when the denominator is zero the rate is reported as 0.00 to avoid dividing by zero.

### 3.12. The Traceability Chain

Every consequential life event appends an entry to an animal's append-only **trace chain**, and reading that chain is how an auditor or any operator reconstructs an animal's history. Each trace event records the subject `animal_id`, an `event_type` drawn from `BIRTH`, `MOVEMENT`, `TREATMENT`, `SALE`, `MORTALITY`, `CULL`, `SUSPEND`, and `REINSTATE`, the originating entity type in `ref_entity` (for example the name of the movement or weight-ticket record type), the originating record's identifier in `ref_id`, the business date of the event in `occurred_on`, and a `detail` snapshot payload capturing context such as the from and to pasture, the drug and clearance date, or the sale amount at the time the event was appended. A trace event, like a weight record, is immutable history and carries only `id` and `created_at`. The chain for an animal is returned ordered by `occurred_on` ascending and then by `created_at` ascending, which is the one list ordering that departs from the default creation-time sort.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including state transitions, applications, reversals, and the clock-setting capability — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/herds` | Create a herd | HerdManager |
| GET | `/herds/{id}` | Get a herd with recomputed inventory figures | HerdManager, Veterinarian, SaleClerk, FeedlotOperator, Auditor |
| POST | `/pastures` | Create a pasture or pen | HerdManager |
| GET | `/pastures/{id}` | Get a pasture with computed load | HerdManager, Veterinarian, SaleClerk, FeedlotOperator, Auditor |
| POST | `/drug-products` | Create a drug/vaccine product | Veterinarian |
| POST | `/feed-rations` | Create a ration | FeedlotOperator |
| GET | `/feed-rations/{id}/computed-ration` | Computed waterfall allocation read | FeedlotOperator, HerdManager, Auditor |
| POST | `/animals` | Register an animal | HerdManager |
| GET | `/animals/{id}` | Get an animal | HerdManager, Veterinarian, SaleClerk, FeedlotOperator, Auditor |
| GET | `/animals` | List/filter animals | HerdManager, Veterinarian, SaleClerk, FeedlotOperator, Auditor |
| POST | `/animals/{id}/life-status` | Drive the animal life-status dimension | HerdManager |
| POST | `/animals/{id}/weights` | Record a weight | HerdManager, FeedlotOperator |
| GET | `/animals/{id}/weights` | List an animal's weight records | HerdManager, FeedlotOperator, Veterinarian, Auditor |
| GET | `/animals/{id}/trace` | Get the animal's traceability chain | HerdManager, Veterinarian, SaleClerk, FeedlotOperator, Auditor |
| POST | `/breeding-records` | Open a breeding record | HerdManager |
| GET | `/breeding-records/{id}` | Get a breeding record | HerdManager, Veterinarian, Auditor |
| GET | `/breeding-records` | List/filter breeding records | HerdManager, Veterinarian, Auditor |
| POST | `/breeding-records/{id}/transition` | Drive the breeding lifecycle | HerdManager, Veterinarian |
| POST | `/health-treatments` | Record a treatment/vaccination | Veterinarian |
| GET | `/health-treatments/{id}` | Get a treatment | Veterinarian, HerdManager, Auditor |
| GET | `/health-treatments` | List/filter health treatments | Veterinarian, HerdManager, Auditor |
| POST | `/health-treatments/{id}/void` | Void a mis-entered treatment | Veterinarian |
| POST | `/movement-records` | Plan a movement | HerdManager |
| GET | `/movement-records/{id}` | Get a movement record | HerdManager, Auditor |
| GET | `/movement-records` | List/filter movement records | HerdManager, Auditor |
| POST | `/movement-records/{id}/apply` | Apply a planned movement | HerdManager |
| POST | `/movement-records/{id}/revert` | Revert the most recent applied movement | HerdManager |
| POST | `/sale-lots` | Open a sale lot | SaleClerk |
| GET | `/sale-lots/{id}` | Get a sale lot with computed totals | SaleClerk, HerdManager, Auditor |
| GET | `/sale-lots` | List/filter sale lots | SaleClerk, HerdManager, Auditor |
| POST | `/sale-lots/{id}/tickets` | Attach a weight ticket to an open lot | SaleClerk |
| GET | `/sale-lots/{id}/tickets` | List weight tickets on a lot | SaleClerk, HerdManager, Auditor |
| POST | `/sale-lots/{id}/sell` | Finalize a sale | SaleClerk |
| POST | `/sale-lots/{id}/withdraw` | Withdraw an open lot | SaleClerk |
| GET | `/weight-tickets/{id}` | Get a weight ticket | SaleClerk, HerdManager, Auditor |
| GET | `/weight-tickets` | List/filter weight tickets | SaleClerk, HerdManager, Auditor |
| POST | `/mortality-records` | Record a death | HerdManager |
| GET | `/mortality-records/{id}` | Get a mortality record | HerdManager, Veterinarian, Auditor |
| GET | `/mortality-records` | List/filter mortality records | HerdManager, Veterinarian, Auditor |
| POST | `/mortality-records/{id}/void` | Void a mis-entered death | HerdManager |
| POST | `/_clock/set_current_utc` | Test-driving: set the system clock | HerdManager, Veterinarian, SaleClerk, FeedlotOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_PEDIGREE` | 422 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_WITHDRAWAL_NOT_CLEARED` | 409 |
| `ERR_ROUTE_NOT_PERMITTED` | 422 |
| `ERR_ANIMAL_ALREADY_LISTED` | 409 |
| `ERR_REST_PERIOD_VIOLATION` | 409 |
| `ERR_PASTURE_OVER_CAPACITY` | 409 |
| `ERR_COMMISSION_NOT_ALLOWED` | 422 |
| `ERR_WEIGH_DATE_INVALID` | 422 |
| `ERR_DOSE_DATES_INVALID` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_HERD_MISMATCH` | 409 |
| `ERR_NOT_LATEST_MOVEMENT` | 409 |
| `ERR_VALIDATION_LIMIT` | 422 |
| `ERR_ANIMAL_NOT_ACTIVE` | 409 |
| `ERR_EMPTY_LOT` | 409 |

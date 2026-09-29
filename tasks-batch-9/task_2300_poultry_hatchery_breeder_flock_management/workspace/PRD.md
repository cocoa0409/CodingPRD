# Poultry Hatchery & Breeder Flock API — Product Requirements Document

## 1. Introduction

A commercial poultry hatchery is a chain of perishable, time-boxed commitments. Breeder hens only lay well when their lighting and feeding programmes track their age; hatching eggs lose viability every hour they sit in a cooler; setters and hatchers hold exactly one load at a time and must be sanitised between them; and chicks, once pulled, must be counted, sexed, vaccinated, boxed and on a truck to a grower farm within hours. Today those commitments live in spreadsheets and paper logs, which means the hatchery cannot answer the two questions that matter most — *why did this set hatch badly?* and *which breeder flock is responsible?* — until months after the fact.

This document specifies the API for a system that closes that loop. It tracks a breeder flock from placement through photostimulation to depletion, forecasting the settable eggs it should produce each day from its age tier, its lighting programme and its nutrition programme. It tracks every hatching egg lot from collection through grading, cold storage and sanitation cycles, ageing each lot in *effective days* rather than calendar days so that a warm cooler or a repeated fumigation cycle is visible in the number that gates whether the eggs may still be set. It plans setter loads against machine occupancy windows, integrates probe readings into cumulative out-of-tolerance degree-hours, derives a hatch window from the weighted storage age of the eggs actually loaded, and grades the resulting chicks on a quality score that carries the incubation history forward. Finally it allocates boxed chicks to grower placement orders in whole boxes, confirms delivery, and feeds rolling hatchability back to the originating breeder flock so that an underperforming flock automatically acquires a corrective action.

Three cross-cutting concerns shape almost every rule that follows. **Biosecurity** is absolute: laboratory results drive holds, quarantines and condemnations that cascade across aggregates. **Segregation of duties** means that the person who raises a biosecurity hold is never the person who clears it. And **exact conservation of countable things** — eggs and chicks — must hold after every single write, because a hatchery that cannot reconcile its counts cannot be audited.

## 2. Global Specifications & System-Wide Principles

All resources are mounted at the root path; there is no additional API prefix.

### 2.1. Principals, Roles and the Duty Split

Every request carries two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity that principal is acting in. A request with a missing or empty `X-User-ID` is rejected with `ERR_UNAUTHENTICATED` (401) before its body is even parsed, so a request that is simultaneously unauthenticated and malformed reports `ERR_UNAUTHENTICATED` and nothing else. The single exception is the logical-clock endpoint, which is reachable without authentication. A request whose `X-User-Role` is missing, is not one of the six recognised role names, or is a recognised role that is not authorised for the addressed operation is rejected with `ERR_FORBIDDEN_ROLE` (403); an unrecognised role string is treated as unauthorised rather than as a malformed request.

The six roles are `HatcheryManager`, `FlockManager`, `IncubationOperator`, `ChickProcessor`, `Veterinarian` and `GrowerFarm`.

- A `HatcheryManager` administers the hatchery: it authors configuration (programmes, incubation profiles, machines, grower farms), aborts setter loads, confirms placement orders, runs the chick allocation waterfall, and confirms or reverses deliveries. It also has broad read access.
- A `FlockManager` places breeder flocks, photostimulates and depletes them, recomputes forecasts, records and grades hatching egg collections, and acknowledges and implements corrective actions.
- An `IncubationOperator` runs the egg cooler and the machines: sanitising units, storing lots and releasing them from sanitation, planning setter loads, drawing eggs into them, starting incubation, ingesting environment readings, candling, and transferring to a hatcher.
- A `ChickProcessor` handles take-off and chick processing: pulling a hatcher load, sexing, vaccinating and boxing.
- A `Veterinarian` owns biosecurity: registering and releasing laboratory tests, placing egg lots on sanitation hold, condemning lots, clearing grower farms, releasing a flock's egg hold, and verifying corrective actions.
- A `GrowerFarm` is the grower-side principal. It may place and read its own farm's placement orders and read its own deliveries, and nothing else.

Identity semantics differ between these roles, and the distinction matters. When `X-User-Role` is `HatcheryManager`, `FlockManager`, `IncubationOperator`, `ChickProcessor` or `Veterinarian`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it in audit fields where a rule says so — as `egg_hold_opened_by_user_id` on a `BreederFlock` driven into `EGG_HOLD`, and as `opened_by_user_id` on an auto-opened `CorrectiveAction` — but never compares it to any entity's `id`. When `X-User-Role` is `GrowerFarm`, `X-User-ID` is the identifier of the acting grower principal and is compared against the `operator_user_id` recorded on the `GrowerFarm` row: ownership checks on any farm, placement order or delivery assignment resolve the owning farm and require that farm's `operator_user_id` to equal `X-User-ID`, failing with `ERR_FARM_SCOPE_VIOLATION` (403) otherwise.

Two operations enforce **segregation of duties** against the opaque operator identifiers recorded above. The principal that drove a flock into `EGG_HOLD` may not be the principal that releases that hold, and the principal whose call caused a `CorrectiveAction` to be auto-opened may not be the principal that verifies it. In both cases a same-principal attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403).

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

### 2.3. Pagination and List Filtering

List endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100. `offset` is the number of records to skip; it defaults to 0 and its minimum accepted value is 0. A `limit` of 0, a `limit` of 101 or a negative `offset` is rejected with `ERR_INVALID_PAGINATION` (400).

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

Lists also accept optional equality filters, all of them independent and combinable. Breeder flock listings filter on `program_id`, `source_flock_id` and `status`. Egg lot listings filter on `flock_id` and `status`. Setter load listings filter on `unit_id`, `profile_id`, `status` and `environment_status`. The draw listings — both the one scoped to a setter load and the one scoped to an egg lot — filter on `item_status`, and the egg-lot-scoped listing deliberately includes voided draws so the full audit trail of a lot is visible. Hatcher load listings filter on `setter_load_id`, `unit_id`, `status` and `pull_class`. Chick batch listings filter on `hatcher_load_id`, `primary_flock_id` and `status`. Placement order listings filter on `farm_id`, `status` and `requested_breed`. Delivery assignment listings filter on `chick_batch_id`, `placement_order_id` and `status`. Laboratory test listings filter on `subject_type`, `subject_id`, `test_code` and `status`. Corrective action listings filter on `flock_id`, `status` and `trigger_reason`. Environment reading listings take no filter beyond pagination and are returned in `recorded_at` order.

### 2.4. The Logical Hatchery Clock

Every age, window, tolerance and deviation rule in this specification reads a server-held **logical clock** rather than wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. Any role — including `GrowerFarm` — may move the clock by supplying a `current_utc` instant; the call returns the `current_utc` now in force and mutates no entity whatsoever.

Because the clock is authoritative, several fields are recomputed on read rather than stored once. Reading a single breeder flock recomputes `age_weeks` and the whole forecast chain against the current clock without incrementing that flock's `version`. Reading a single egg lot likewise recomputes `effective_age_days` against the current clock without incrementing its `version`. Timestamps that the server itself stamps — `sanitized_at`, `cleared_at`, `stored_at`, `set_at`, `transferred_at`, `actual_pull_at`, `delivered_at`, `released_at`, `opened_at`, `egg_hold_opened_at` — are always taken from the logical clock at the moment of the write, never from the request body.

### 2.5. Record Identity, Audit Fields and Version Semantics

Every record the API creates carries an `id`: a server-minted UUID with no type prefix, opaque to the client and never used as a business ordering key. Every record also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at creation.

Almost every record additionally carries `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that record. The one exception is the **environment reading**, which is an append-only probe sample: an environment reading carries only `id` and `created_at`. It has no `updated_at` and no `version` at all. Its `created_at` has a second job beyond auditing: it is the only sanctioned tie-break when two readings of the same load happen to share a `recorded_at`.

When an operation mutates several records — and in this domain most operations do — every record it actually changes gets its own `updated_at` refresh and its own `version` increment. A cascade that touches a flock, three egg lots and a setter load bumps four versions.

### 2.6. Numeric Precision and Rounding Discipline

All rounding in this system is **round half up**, and every quantity has a fixed scale:

- Percentages — `production_rate_pct` at one decimal place; `fertility_pct`, `preliminary_yield_pct`, `final_yield_pct`, `hatchability_rolling_pct`, `hatchability_fertile_pct` and `observed_hatchability_pct` at two decimal places.
- Effective egg age — `effective_age_days` and its frozen snapshot `effective_age_days_at_set` at two decimal places.
- Temperature deviation — `abs_deviation_c` and `elapsed_hours` at two decimal places; `segment_degree_hours`, `deviation_degree_hours` and `inherited_degree_hours` at three decimal places.
- The two multiplier factors — `lighting_factor` and `nutrition_factor` at four decimal places, as is `weighted_age_days`.
- Quality scores — `quality_score_provisional` and `quality_score_final` at two decimal places.
- Counts are exact integers. Where a formula says a value is floored or ceilinged, that is a single truncation applied to the completed expression, not a rounding step.

Intermediate rounding is never implicit. Where a calculation pins the order of rounding — for example rounding the two multiplier factors *before* they multiply the hen count, or rounding each degree-hour segment *before* it joins the running total — that order is part of the contract and is stated with the calculation.

### 2.7. Cascade Discipline

The hatchery is a graph, not a tree: a single egg lot feeds several setter loads, a single setter load draws from several lots, and a chick batch reaches back to a breeder flock through the load that produced it. Writes therefore propagate, and they propagate **immediately and within the same request** that triggered them. There is no deferred reconciliation and no eventual consistency: by the time the response is serialised, every dependent record the write affects has already moved, been recomputed, had `updated_at` refreshed and had `version` incremented.

Three cascade families recur throughout §3 and are worth naming up front. **Biosecurity cascades** run outward from a released laboratory result to the flock, its stored and allocated egg lots, the machine or the farm. **Void-and-restore cascades** run when a draw is voided or an assignment reversed: the counterpart field is restored in the same request so that the conservation invariants of §2.10 never drift, even transiently. **Recompute cascades** run when a value that feeds a derived field changes — a new corrective action changes a flock's forecast, a completed sanitation cycle changes a lot's effective age, a voided draw changes a load's total and weighted age.

### 2.8. Addressing Nested Records

Where a path names more than one record — a load's draws, a load's environment readings, a lot's draws — identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the 404. A request for the readings of a setter load that does not exist returns `ERR_SETTER_LOAD_NOT_FOUND` and never looks for readings; a draw against a non-existent load likewise reports the load's absence rather than the egg lot's. Each entity has its own not-found code: `ERR_FLOCK_PROGRAM_NOT_FOUND`, `ERR_INCUBATION_PROFILE_NOT_FOUND`, `ERR_INCUBATION_UNIT_NOT_FOUND`, `ERR_BREEDER_FLOCK_NOT_FOUND`, `ERR_EGG_LOT_NOT_FOUND`, `ERR_SETTER_LOAD_NOT_FOUND`, `ERR_HATCHER_LOAD_NOT_FOUND`, `ERR_CHICK_BATCH_NOT_FOUND`, `ERR_GROWER_FARM_NOT_FOUND`, `ERR_PLACEMENT_ORDER_NOT_FOUND`, `ERR_DELIVERY_ASSIGNMENT_NOT_FOUND`, `ERR_LAB_TEST_NOT_FOUND` and `ERR_CORRECTIVE_ACTION_NOT_FOUND`, each returned with HTTP 404.

Foreign-key identifiers supplied in a request body are resolved after the path, in the order in which the fields are declared on the entity being created, and they use the code of the *parent* entity that failed to resolve. So a flock placement whose `program_id` is unknown reports `ERR_FLOCK_PROGRAM_NOT_FOUND`, and one whose `source_flock_id` is unknown reports `ERR_BREEDER_FLOCK_NOT_FOUND`. A laboratory sample's `subject_id` is resolved only against the table its `subject_type` selects.

### 2.9. Optimistic Concurrency on Egg Lots and Chick Batches

Two writes in this system move a countable resource out of a pool that other writers can also draw from, and both are protected by optimistic concurrency on the *parent* record rather than on the record being created.

Drawing eggs from a lot into a planned setter load requires a non-optional `expected_egg_lot_version` field carrying the `version` of the `EggLot` the caller last read. If that value does not equal the lot's current `version` when the write is applied, the draw is rejected with `ERR_STALE_VERSION` (HTTP 412) and no eggs move, no draw record is created, and no aggregate is recomputed. A successful draw increments the lot's `version` by 1, which means replaying the identical request with the same `expected_egg_lot_version` is rejected — the client cannot accidentally double-draw against a pool it has only observed once.

Running the allocation waterfall over a boxed chick batch requires a non-optional `expected_chick_batch_version` field carrying the `version` of the `ChickBatch` the caller last read. A mismatch against the batch's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) and no delivery assignment records are created at all. A successful run increments the batch's `version` by 1, so the same `expected_chick_batch_version` cannot be replayed to allocate the same chicks twice.

No other operation takes a version field, and supplying one elsewhere has no effect. Where an exact ordering fallback is needed to serialise records — ranking eligible orders, breaking ties among draws — `created_at` is the tie-break; `id` is never used for ordering.

### 2.10. Conservation of Eggs and Chicks

Two counting invariants must hold exactly, with no tolerance, immediately after every mutation that touches egg lots, draws, chick batches or delivery assignments — and they must already hold in the response that performed the mutation.

**Egg conservation.** For every egg lot, `settable_count` equals `eggs_remaining` plus the sum of `eggs_taken` across that lot's draws whose `item_status` is `ACTIVE`. Draws whose `item_status` is `VOIDED` drop out of the sum entirely, which is exactly why voiding a draw must return its eggs to the lot in the same request. A condemned lot is a special case worth stating explicitly: it retains `settable_count` for audit, but its `eggs_remaining` is 0 and it has no `ACTIVE` draws left.

**Chick conservation.** For every chick batch, `saleable_count` equals `unassigned_chicks` plus the sum of `chicks_assigned` across that batch's delivery assignments whose status is `ASSIGNED` or `DELIVERED`. A `REVERSED` assignment drops out of the sum, which is why reversal must return its chicks to `unassigned_chicks` in the same request.

Both invariants are exact integer equalities. Because every chick grant is an exact multiple of the standard box of 100 chicks — counted as `boxes_assigned` on the assignment and bounded by the batch's own `box_count` — a batch's `unassigned_chicks` can legitimately settle on a sub-box remainder that no allocation run will ever move.

### 2.11. Order of Rejection: The Validation Cascade

When a request violates several rules at once, the response is determined by the **first** violated rule in the strict priority order below, and no later rule may mask an earlier one. This ordering is a contract in its own right: it is what makes a stale version against an ineligible parent report `ERR_STALE_VERSION` rather than a state error, and an out-of-scope grower request report a scope violation rather than leaking whether the record exists.

1. `X-User-ID` present and non-empty — `ERR_UNAUTHENTICATED` (401), on every endpoint except the logical-clock setter, evaluated before the body is parsed.
2. `X-User-Role` present, a known role, and authorised for the endpoint — `ERR_FORBIDDEN_ROLE` (403), on every endpoint.
3. Grower-farm row scoping — `ERR_FARM_SCOPE_VIOLATION` (403). This applies to exactly six operations: placing a placement order, reading one placement order, listing placement orders, reading one delivery assignment, listing delivery assignments, and reading one grower farm. It is checked after role authorisation and *before* existence, so an out-of-scope identifier reports the scope violation rather than a 404.
4. Every `{id}` path parameter resolves to a live row of the addressed entity — the entity-specific not-found code (404), on every endpoint that addresses a record by path.
5. Every foreign-key field in the request body resolves to a live row of its parent — the parent's not-found code (404). This applies to flock placement, egg lot collection, setter load planning, egg draws, transfer, placement order creation and laboratory sample registration.
6. Required body fields present, of the declared type, with every enum value inside its declared set — `ERR_INVALID_REQUEST` (400), on every write endpoint. Unknown extra body fields are ignored rather than rejected, and fields the specification marks as computed or system-managed are ignored when a client supplies them.
7. `limit` within 1 through 100 and `offset` at least 0 — `ERR_INVALID_PAGINATION` (400), on every list endpoint.
8. Every count field at or above its declared minimum and never negative — `ERR_NON_POSITIVE_COUNT` (400). This applies to flock placement, egg lot collection, grading, egg draws, candling, chick pull, sexing, placement order creation, grower farm registration and machine registration. The distinction from rule 6 is semantic versus structural: an `eggs_taken` of 0 or −5 is `ERR_NON_POSITIVE_COUNT`, whereas an `eggs_taken` of `"many"` is `ERR_INVALID_REQUEST`. Zero-valued grading sub-counts other than `grade_a_count` are perfectly legal.
9. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403), on egg-hold release and corrective-action verification. Checked *before* state, so a same-principal call against a wrongly-stated record still reports the duty violation.
10. `expected_egg_lot_version` or `expected_chick_batch_version` equal to the parent's current `version` — `ERR_STALE_VERSION` (412), on egg draws and allocation runs. Evaluated before any state or business rule.
11. The breeder flock admits the requested transition — `ERR_FLOCK_INVALID_STATE` (409), on start-lay, deplete and release-hold. This covers repeat triggers such as photostimulating twice, and terminal lockdown: nothing leaves `DEPLETED`.
12. The egg lot admits the requested transition — `ERR_EGG_LOT_INVALID_STATE` (409), on grading, storing, sanitation hold, sanitation release, condemnation and egg draws. A lot in `CONSUMED` or `CONDEMNED` admits nothing; a `COLLECTED` lot cannot be stored; a `GRADED` lot cannot be drawn from.
13. The setter load admits the requested transition — `ERR_INCUBATION_INVALID_STATE` (409), on egg draws, start, candling, transfer, abort and reading ingestion. Draws only while `PLANNED`, readings only while `INCUBATING`, transfer only from `CANDLED`, nothing at all from `TRANSFERRED` or `ABORTED`.
14. The hatcher load admits the requested transition — also `ERR_INCUBATION_INVALID_STATE` (409), on chick pull. A hatcher load is pulled exactly once; a second pull from any of the three pulled states is rejected.
15. The chick batch admits the requested step — `ERR_CHICK_FLOW_INVALID_STATE` (409), on sexing, vaccination, boxing and allocation. The flow is strictly `PULLED` → `SEXED` → `VACCINATED` → `BOXED`; skipping vaccination or allocating before boxing is rejected.
16. The placement order admits confirmation — `ERR_ORDER_INVALID_STATE` (409), on confirmation only; an order may be confirmed only from `REQUESTED`.
17. The delivery assignment admits the requested transition — `ERR_ASSIGNMENT_INVALID_STATE` (409), on deliver and reverse. `DELIVERED` and `REVERSED` are both terminal and neither operation is possible from either.
18. The laboratory test has not been released — `ERR_LAB_TEST_ALREADY_RELEASED` (409), on result release. A released test is terminal and cannot be re-released, not even with the same result.
19. The corrective action admits the requested step — `ERR_CORRECTIVE_ACTION_INVALID_STATE` (409), on acknowledge, implement and verify. `VERIFIED` is terminal, and after a failed verification the action is back in `OPEN` and must be acknowledged again before it can be implemented.
20. The referenced configuration record is not retired — `ERR_PROGRAM_RETIRED` (409), on flock placement, photostimulation and setter load planning. A retired `FlockProgram` can neither back a new flock nor a photostimulation start; a retired `IncubationProfile` cannot back a new setter load.
21. Salmonella clearance on record — `ERR_LAB_CLEARANCE_MISSING` (422), on photostimulation and egg-hold release. A `PENDING` or `INVALID` test never clears a flock.
22. Machine sanitation, and the environment dimension at transfer — `ERR_UNIT_NOT_SANITIZED` (422), on setter start and transfer. This same priority rank also raises `ERR_ENVIRONMENT_DEVIATION_OPEN` (422) at transfer when the load's environment dimension is still `DEVIATION_OPEN`, with the sanitation check evaluated first of the two.
23. Farm clearance — `ERR_FARM_NOT_CLEARED` (422), on placement order confirmation and delivery confirmation.
24. The lot is young enough to set — `ERR_EGG_TOO_OLD` (422), on egg draws.
25. Client-supplied timestamps inside their admissible range relative to the logical clock — `ERR_TIMESTAMP_OUT_OF_RANGE` (422), on egg lot collection, flock placement, setter load planning, candling, reading ingestion, laboratory sample registration, placement order creation and delivery confirmation.
26. An early-pulled batch is not boxed before its hold expires — `ERR_EARLY_HOLD_ACTIVE` (422), on boxing.
27. Grading sub-counts reconcile — `ERR_GRADE_COUNT_MISMATCH` (422), on grading.
28. Grading yields at least one settable egg — `ERR_NO_SETTABLE_EGGS` (422), on grading.
29. Sexing counts reconcile — `ERR_SEX_COUNT_MISMATCH` (422), on sexing.
30. A derived count never exceeds its source — `ERR_COUNT_EXCEEDS_SOURCE` (422), on candling and chick pull.
31. A load has at least one active draw before it starts — `ERR_NO_EGGS_LOADED` (422), on setter start.
32. Machine occupancy, type and capacity at run time — `ERR_UNIT_OCCUPIED` (409) on setter start and transfer when the target machine is already holding a non-terminal load. At the same rank, `ERR_UNIT_CAPACITY_EXCEEDED` (422) is returned instead when the load's egg count exceeds the machine's `capacity_eggs`, and `ERR_UNIT_TYPE_MISMATCH` (422) when a hatcher machine is used as a setter or a setter machine is used as a transfer target.
33. The eggs' owning flock is not on egg hold — `ERR_FLOCK_EGG_HOLD` (422), on egg lot collection, storing and egg draws.
34. The flock is old enough to photostimulate — `ERR_FLOCK_NOT_MATURE` (422), on photostimulation.
35. Breed agreement across the reference chain — `ERR_BREED_MISMATCH` (422), on flock placement and egg draws.
36. A polymorphic laboratory subject resolves in the table its discriminator selects — `ERR_LAB_SUBJECT_INVALID` (422), on laboratory sample registration.
37. A draw never exceeds the lot's remaining settable eggs — `ERR_INSUFFICIENT_SETTABLE_EGGS` (422), on egg draws.
38. The planned machine window does not collide with another load's occupancy plus turnaround — `ERR_UNIT_WINDOW_CONFLICT` (409), on setter load planning.
39. Aggregate farm capacity, and allocatability — `ERR_FARM_CAPACITY_EXCEEDED` (422), on placement order confirmation. At the same rank, an allocation run that finds no eligible placement order at all is reported as `ERR_NO_ELIGIBLE_PLACEMENT_ORDER` (422).

## 3. Business Logic & Workflows

### 3.1. Hatchery Configuration: Programmes, Profiles and Machines

Configuration is authored by a `HatcheryManager` and is the reference data everything else hangs from. A **flock programme** captures how a breeder flock will be lit and fed. It is created with a `code` of 1 to 40 characters that must be unique among programmes that have not been retired, a `breed` that is one of `ROSS_308`, `COBB_500` or `HUBBARD_JA87`, a `stimulation_week` between 18 and 30 inclusive giving the flock age in weeks at which photostimulation may begin, and two step tables. The `lighting_steps` table holds 1 to 8 entries, each an `age_weeks` integer paired with a `photoperiod_hours` number between 8.0 and 17.0 inclusive, and its `age_weeks` values must be strictly ascending. The `feed_steps` table holds 1 to 8 entries, each an `age_weeks` integer paired with a `feed_grams_per_hen_day` number between 90.0 and 200.0 inclusive, again strictly ascending in `age_weeks`. Both tables are read with the same *last step wins* rule: the applicable entry for a flock is the last one whose `age_weeks` is less than or equal to the flock's current age in weeks, and when the flock is younger than the first entry no step applies at all. A programme is born with `retired` set to false; retiring it sets `retired` to true and increments the programme's `version`, after which it rejects new flock placements and new photostimulation attempts with `ERR_PROGRAM_RETIRED`.

An **incubation profile** captures the temperature and humidity curve a setter will run. It carries a `code` of 1 to 40 characters, a `breed` drawn from the same three-value set that must equal the breed of every egg lot loaded under it, a `transfer_hours` integer of at least 300 giving the elapsed incubation hours from set to the setter-to-hatcher transfer, and a `total_hours` integer of at most 600 giving the elapsed incubation hours from set to the nominal pull. The two must satisfy `transfer_hours` strictly less than `total_hours`. The `stages` table holds 2 to 6 entries, each an integer `from_hour`, an integer `to_hour`, a `temp_c` number between 36.0 and 39.0 inclusive and a `humidity_pct` number between 40.0 and 75.0 inclusive. The stages must tile the whole incubation contiguously: the first stage's `from_hour` is 0, the last stage's `to_hour` equals `total_hours`, and each stage's `from_hour` equals the previous stage's `to_hour`. Stage lookup uses a half-open interval — a given elapsed hour belongs to the stage whose range starts at or after its `from_hour` and ends strictly before its `to_hour`. A profile also has a `retired` flag defaulting to false; a retired profile rejects new setter loads.

An **incubation unit** is a physical machine. It is registered with a `code` of 1 to 40 characters, a `unit_type` of either `SETTER` or `HATCHER`, and a `capacity_eggs` integer between 1000 and 200000 inclusive giving the most eggs it may hold for one load. A `SETTER` machine accepts setter loads; a `HATCHER` machine accepts transfers; using one where the other is required is rejected with `ERR_UNIT_TYPE_MISMATCH`. A newly registered machine starts with `sanitation_status` of `DIRTY` and `occupancy_status` of `FREE`, and its `sanitized_at` is null until the first sanitation. An `IncubationOperator` sanitises a machine, which sets `sanitation_status` to `SANITIZED`, sets `sanitized_at` to the current logical clock and increments the machine's `version`. Sanitation is *consumed*, not persistent: the moment a load starts in the machine its `sanitation_status` drops back to `DIRTY`, so a second load in the same machine needs a fresh sanitation. `occupancy_status` is `OCCUPIED` while a non-terminal load holds the machine and is released back to `FREE` by transfer, by abort, or by the boxing that finishes a hatch.

### 3.2. Breeder Flock Placement and the Settable-Egg Forecast

A `FlockManager` places a breeder flock by supplying a `code` of 1 to 40 characters, the `program_id` of the flock programme that will govern its lighting and nutrition, a `breed`, a `house_code` of 1 to 20 characters identifying the breeder house, a `hatch_date` giving the UTC instant the flock itself hatched, a `placed_at` giving the UTC instant it entered the house, and a `hen_count` of at least 1. The `house_code` merely identifies the breeder house the flock occupies and takes no part in any calculation. An optional `source_flock_id` records the parent-stock lineage — the flock this flock's own eggs came from — and is left absent for imported grandparent stock; this self-reference is what later lets analytics attribute performance back up the lineage. The flock's `breed` must equal the breed of the programme named by `program_id`, or the placement is rejected with `ERR_BREED_MISMATCH`. The `hatch_date` must be strictly before `placed_at`, and `placed_at` must not be later than the current logical clock; both violations report `ERR_TIMESTAMP_OUT_OF_RANGE`. A newly placed flock has `status` of `PLACED`, `corrective_action_count` of 0, `late_pull_count` of 0, a null `egg_hold_opened_at` and a null `egg_hold_opened_by_user_id`, and its whole forecast chain is computed immediately.

That forecast chain is the flock's economic heart, and it is recomputed on placement, on photostimulation, on egg-hold release, whenever an explicit recompute is requested by a `FlockManager`, and whenever `corrective_action_count` changes. It runs in a pinned order.

First, `age_weeks` is the number of whole weeks between `hatch_date` and the current logical clock: take the elapsed time in days, divide by seven, and discard any fractional remainder. Next, `photoperiod_hours` is the `photoperiod_hours` of the applicable entry of the programme's `lighting_steps` — the last entry whose `age_weeks` is at most the flock's `age_weeks` — and when the flock is younger than the first lighting step it sits on the base photoperiod of 8.0 hours. Similarly `feed_grams_per_hen_day` is the `feed_grams_per_hen_day` of the applicable entry of `feed_steps`, and when no step applies yet the flock is fed the target ration of 160.0 grams per hen per day.

Then `production_rate_pct`, the hen-day production percentage, is read off an age tier and carries one decimal place: it is 0.0 for a flock younger than 21 weeks, 45.0 for a flock of 21 through 24 weeks inclusive, 82.0 for 25 through 30 weeks inclusive, 74.0 for 31 through 45 weeks inclusive, and 61.0 once the flock reaches 46 weeks or more.

The `lighting_factor` rewards a long day. Subtract eleven hours from `photoperiod_hours`; if that difference is negative, treat it as zero. Multiply the result by 0.03 and add 0.70. If the outcome exceeds 1.00, cap it at 1.00. Round the capped value half up to four decimal places. The `nutrition_factor` rewards feeding to target. Divide `feed_grams_per_hen_day` by the target ration of 160.0 grams, then clamp that ratio so it is never below 0.80 and never above 1.10, and round the clamped value half up to four decimal places.

A derate expresses open corrective action: it is 0.95 whenever the flock's `corrective_action_count` is 1 or more, and 1.0 when the count is 0.

Finally `settable_forecast`, the forecast settable hatching eggs per day, is produced by starting from `hen_count` and multiplying it in this exact order by `production_rate_pct` divided by 100, then by `lighting_factor`, then by `nutrition_factor`, then by the settable ratio of 0.94 that expresses the share of eggs laid that grade out as settable, then by the derate — and taking the floor of the final product to a whole number of eggs. Both factors are rounded to four decimal places *before* they enter the product; no other intermediate rounding occurs, and the floor is applied once, to the completed product.

A flock advances `PLACED → IN_LAY` when a `FlockManager` photostimulates it. Three gates guard that step beyond the state check itself: the flock's `age_weeks` must be at least the `stimulation_week` of its programme, and exactly equal is acceptable, otherwise `ERR_FLOCK_NOT_MATURE`; at least one laboratory test against this flock with a `test_code` of `SALMONELLA_PULLORUM` must have reached `NEGATIVE`, otherwise `ERR_LAB_CLEARANCE_MISSING`; and the programme must not be retired, otherwise `ERR_PROGRAM_RETIRED`. On success the whole forecast chain — `age_weeks`, `photoperiod_hours`, `feed_grams_per_hen_day`, `production_rate_pct`, `lighting_factor`, `nutrition_factor`, `settable_forecast` — is recomputed and the flock's `version` increments by 1.

End of lay is `DEPLETED`, and `DEPLETED` is terminal. A `FlockManager` may deplete a flock from `IN_LAY` or directly from `PLACED`; either way the flock's `settable_forecast` and `production_rate_pct` are both set to 0 and its `version` increments by 1. Depleting from `IN_LAY` carries one extra guard: no egg lot of the flock may still be in `ALLOCATED`, because those eggs are already committed to a planned setter load; such an attempt is rejected with `ERR_FLOCK_INVALID_STATE`. Depleting from `PLACED` has no such outstanding commitment to check.

### 3.3. Biosecurity: Laboratory Testing, Egg Holds and Farm Clearance

A `Veterinarian` registers a laboratory sample by supplying a `subject_type`, a `subject_id`, a `test_code` and a `collected_at`. The `subject_type` discriminator is `BREEDER_FLOCK`, `INCUBATION_UNIT` or `GROWER_FARM`, and it alone decides where `subject_id` is looked up: against breeder flocks, against incubation units, or against grower farms respectively. An identifier that fails to resolve in the discriminated table is rejected with `ERR_LAB_SUBJECT_INVALID` even when that same identifier happens to resolve in one of the other two tables — the discriminator is not a hint, it is the whole lookup. The `test_code` is one of `SALMONELLA_PULLORUM`, `MYCOPLASMA_GALLISEPTICUM`, `AVIAN_INFLUENZA` or `SHELL_HYGIENE`, and `collected_at` may not be later than the current logical clock. A registered sample has `status` of `PENDING`, a null `released_at` and a null `result`.

Releasing a result is a one-shot, terminal act. The `Veterinarian` supplies a `result` of `NEGATIVE`, `POSITIVE` or `INVALID`, the test moves from `PENDING` to the matching terminal status, `released_at` is stamped from the logical clock, `result` is stored and the test's `version` increments by 1. A second release attempt against a test in any of the three terminal states is rejected with `ERR_LAB_TEST_ALREADY_RELEASED`, including a release carrying the same result as before. An `INVALID` release has no subject side effects at all and — this matters — never satisfies a clearance precondition; only `NEGATIVE` clears.

A `POSITIVE` release fans out according to the subject discriminator, and the three branches are deliberately different in weight. When the subject is an `INCUBATION_UNIT`, the machine's `sanitation_status` is forced to `DIRTY`, so any load about to start in it must wait for a fresh sanitation. When the subject is a `GROWER_FARM`, the farm's `biosecurity_status` becomes `QUARANTINED`, which immediately drops its orders out of the allocation waterfall and blocks any pending delivery. When the subject is a `BREEDER_FLOCK`, the flock moves `IN_LAY → EGG_HOLD`, its `egg_hold_opened_at` is set to the current logical clock and its `egg_hold_opened_by_user_id` records the `X-User-ID` of the principal that made the release call — and then the egg condemnation cascade runs: **every** egg lot of that flock currently in `IN_STORAGE` or `ALLOCATED` moves to `CONDEMNED` with a `condemned_reason` of `FLOCK_EGG_HOLD`. Each condemned lot has its own `version` incremented, and the `ALLOCATED` ones additionally trigger the void-and-abort chain described in §3.4. The flock's own `version` increments as well.

While a flock sits in `EGG_HOLD` its eggs are frozen out of the production chain in three places: new collections against it, storing one of its graded lots, and drawing from one of its lots into a setter load are all rejected with `ERR_FLOCK_EGG_HOLD` — and the ban reaches lots that were already sitting in the cooler before the hold was raised, not just newly collected ones.

Coming off hold requires a clean re-test and a second pair of eyes. A `Veterinarian` releases the hold, moving the flock `EGG_HOLD → IN_LAY`, but only when the acting `X-User-ID` differs from the recorded `egg_hold_opened_by_user_id` — a same-principal attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` before the flock's state is even examined — and only when the flock's most recently *collected* `SALMONELLA_PULLORUM` test has reached `NEGATIVE`, otherwise `ERR_LAB_CLEARANCE_MISSING`. Note the ordering: it is the latest sample by collection instant that must be clean, not merely some clean sample somewhere in the history. On success both `egg_hold_opened_at` and `egg_hold_opened_by_user_id` are cleared to null, `settable_forecast` is recomputed, and the flock's `version` increments by 1.

Grower farms carry the same biosecurity discipline from the other end. A `HatcheryManager` registers a farm with a `code` of 1 to 40 characters, an `operator_user_id` naming the `GrowerFarm` principal that owns the farm's scope, and a `capacity_chicks` of at least 1000 giving the most chicks the farm may hold across all overlapping placement cycles. The farm starts at `biosecurity_status` of `PENDING` with a null `cleared_at`. Only a `Veterinarian` may clear it: clearance sets `biosecurity_status` to `CLEARED`, stamps `cleared_at` from the logical clock and increments the farm's `version`. Only a `CLEARED` farm may have an order confirmed or a delivery accepted; anything else reports `ERR_FARM_NOT_CLEARED`.

### 3.4. Hatching Egg Collection, Grading, Storage and Age-of-Egg

A `FlockManager` closes a collection by recording the `flock_id` of the laying flock, the `collected_at` instant at which collection closed, and a `collected_count` of at least 1 giving the eggs picked up before any grading. The `collected_at` instant may not be in the future relative to the logical clock. A new lot has `status` of `COLLECTED`, a `settable_count` of 0, an `eggs_remaining` of 0, a `sanitation_cycle_count` of 0, and null values for `grade_a_count`, `cracked_count`, `dirty_count`, `small_count`, `storage_temp_c`, `stored_at` and `condemned_reason`. Its `effective_age_days` is computed immediately, on the unstored factor.

**Age-of-egg** is the single most consequential derived number on a lot, because it gates whether the eggs may still be set and it delays the hatch of any load that includes them. It is expressed in *effective* days rather than calendar days. Start from the elapsed time between `collected_at` and the current logical clock expressed as a fractional number of days, with no rounding at this stage. Multiply that base by a storage factor: 2.0 while the lot has never been stored, meaning its `stored_at` is still null; 1.5 once it has been stored at a `storage_temp_c` strictly greater than 18.0 degrees Celsius; and 1.0 once it has been stored at 18.0 degrees or below. The boundary is exclusive on the warm side — a `storage_temp_c` of exactly 18.0 is cool and earns the 1.0 factor, while 18.01 is warm and earns 1.5. To the scaled base, add a penalty of 0.75 effective days — three-quarters of a day, or 18 hours — for **each** completed sanitation cycle recorded in `sanitation_cycle_count`. Round the whole sum half up to two decimal places once, after the penalty has been added. `effective_age_days` is recomputed at grading, at storage, at sanitation release and on every read of the lot.

Grading moves a lot `COLLECTED → GRADED` and is performed by a `FlockManager`, who supplies `grade_a_count`, `cracked_count`, `dirty_count` and `small_count`. The four sub-counts must sum to exactly `collected_count`, or the request is rejected with `ERR_GRADE_COUNT_MISMATCH`; and `grade_a_count` must be at least 1, or the request is rejected with `ERR_NO_SETTABLE_EGGS` — a lot that grades out to zero settable eggs cannot become `GRADED` and must be condemned instead. Zero is a legitimate value for the other three sub-counts. On success both `settable_count` and `eggs_remaining` are set to `grade_a_count`, `effective_age_days` is recomputed on the unstored factor, and the lot's `version` increments by 1.

An `IncubationOperator` moves a graded lot into the cooler, `GRADED → IN_STORAGE`, supplying the `storage_temp_c` at which it is held. The owning flock must be `IN_LAY` at that moment, otherwise `ERR_FLOCK_EGG_HOLD`. On success `stored_at` is stamped from the logical clock the *first* time the lot enters storage, `storage_temp_c` is recorded, `effective_age_days` is recomputed on the warm or cool factor that `storage_temp_c` selects, and the lot's `version` increments by 1.

Sanitation is a cycle, and it is deliberately costly. A `Veterinarian` pulls a stored lot for fumigation, moving it `IN_STORAGE → SANITATION_HOLD` and incrementing its `version`. An `IncubationOperator` returns it, moving it `SANITATION_HOLD → IN_STORAGE`, which adds 1 to `sanitation_cycle_count`, recomputes `effective_age_days` including the accumulated 18-hour penalty for every completed cycle, and increments the lot's `version`. A lot may go round this loop any number of times, and each completed cycle ages it permanently — three cycles cost it 2.25 effective days on top of its scaled calendar age, whether or not it is ever set.

Condemnation is terminal and is a `Veterinarian` act, taking a `reason` that is stored as the lot's `condemned_reason`. A lot may be condemned from `IN_STORAGE`, from `SANITATION_HOLD` or from `ALLOCATED`; a lot already in `CONSUMED` or `CONDEMNED` admits nothing further and reports `ERR_EGG_LOT_INVALID_STATE`. Condemning from `IN_STORAGE` or `SANITATION_HOLD` sets `eggs_remaining` to 0 while leaving `settable_count` untouched for audit. Condemning an `ALLOCATED` lot does considerably more, and the full cascade must be stated: every `ACTIVE` draw of that lot flips to `item_status` of `VOIDED`; each affected setter load has its `total_eggs_set` and `weighted_age_days` recomputed over the draws that remain active; and any load left with a `total_eggs_set` of 0 and still in `PLANNED` moves to `ABORTED` with an `abort_reason` of `EGG_LOTS_CONDEMNED` and releases its incubation unit's `occupancy_status` back to `FREE`. Each record touched in that chain has its own `version` incremented, alongside the lot's own.

The same cascade runs, unchanged, when the condemnation arrives indirectly — as the `FLOCK_EGG_HOLD` consequence of a positive breeder-flock laboratory result described in §3.3. That is the intended serialisation point between biosecurity and incubation: a hold raised while eggs sit in a planned load empties the load rather than letting the eggs be set.

### 3.5. Setter Loads: Planning, Egg Draws, Incubation Start and Environment Monitoring

An `IncubationOperator` plans a setter load by naming the `unit_id` of the machine, the `profile_id` of the incubation profile it will run, and a `planned_set_at` instant at which incubation is intended to begin. The machine must be of `unit_type` `SETTER`, the profile must not be retired, and `planned_set_at` may not be earlier than the current logical clock. A new load has `status` of `PLANNED`, `environment_status` of `NOMINAL`, `total_eggs_set` of 0, `deviation_degree_hours` of 0, and nulls for `set_at`, `weighted_age_days`, `storage_delay_hours`, `planned_transfer_at`, `planned_pull_at`, `pull_window_start_at`, `pull_window_end_at`, `fertile_count`, `fertility_pct`, `deviation_opened_at` and `abort_reason`.

Planning is where machine scheduling is enforced, and the interval semantics here are **closed**. Each existing load of the same machine occupies that machine from its own `planned_set_at` until its `planned_set_at` plus its profile's `total_hours` plus a sanitation turnaround of 12 hours. The load being planned occupies the machine over the same shape of interval computed from its own `planned_set_at` and its own profile's `total_hours`, again extended by the 12-hour turnaround. The two conflict when the new interval's start is at or before the existing interval's end **and** the existing interval's start is at or before the new interval's end. Touching endpoints therefore *do* conflict: a load planned to start at exactly the instant an existing occupancy ends is rejected with `ERR_UNIT_WINDOW_CONFLICT`. The check runs against every load of that machine in `PLANNED`, `INCUBATING` or `CANDLED`; loads in `ABORTED` or `TRANSFERRED` have released the machine and are ignored.

Drawing eggs into a planned load is the tightest write in the system. An `IncubationOperator` supplies the `egg_lot_id` of the source lot, an `eggs_taken` count of at least 1, and the `expected_egg_lot_version` demanded by §2.9. The draw is a many-to-many bridge: one lot may be drawn into several loads, and one load draws from several lots. Beyond the stale-version and state checks, the draw is guarded by four business rules. The lot's owning flock must not be in `EGG_HOLD`, or `ERR_FLOCK_EGG_HOLD`. The lot's `effective_age_days` at the instant of the draw must not exceed the maximum settable age of 10.00 effective days — exactly 10.00 is allowed, 10.01 is rejected with `ERR_EGG_TOO_OLD` — and because the sanitation penalty is part of `effective_age_days`, fumigation cycles count against this limit. The breed of the lot's flock must equal the breed of the load's profile, or `ERR_BREED_MISMATCH`. And `eggs_taken` must not exceed the lot's `eggs_remaining`, or `ERR_INSUFFICIENT_SETTABLE_EGGS`; egg conservation is what makes this exact, so two draws of 4000 eggs against a 6000-egg lot fail on the second, not the first.

A successful draw creates a draw record whose `setter_load_id` names the owning load and whose `egg_lot_id` names the source lot, with an `item_status` of `ACTIVE` and an `effective_age_days_at_set` that snapshots the lot's `effective_age_days` at that exact instant and is frozen forever after — later ageing of the lot never rewrites a draw that has already been taken. The lot's `eggs_remaining` is reduced by `eggs_taken`, the lot moves `IN_STORAGE → ALLOCATED` on the first draw and stays in `ALLOCATED` on every further draw into another planned load, the load's `total_eggs_set` and `weighted_age_days` are recomputed over its `ACTIVE` draws, and the lot's `version` increments by 1. Voided draws are excluded from every aggregate, and voiding one returns its `eggs_taken` to the lot's `eggs_remaining`.

Starting incubation moves the load `PLANNED → INCUBATING`. Five preconditions apply: the load must be `PLANNED`; at least one `ACTIVE` draw must exist, otherwise `ERR_NO_EGGS_LOADED`, which is exactly the situation a condemnation cascade leaves behind; the machine's `sanitation_status` must be `SANITIZED`, otherwise `ERR_UNIT_NOT_SANITIZED`; the machine's `occupancy_status` must be `FREE`, otherwise `ERR_UNIT_OCCUPIED`; and `total_eggs_set` must not exceed the machine's `capacity_eggs`, otherwise `ERR_UNIT_CAPACITY_EXCEEDED`. On success `set_at` is stamped from the logical clock, the machine's `occupancy_status` becomes `OCCUPIED` and its `sanitation_status` drops to `DIRTY`, every contributing egg lot moves `ALLOCATED → SET`, the load's `version` increments by 1, and the hatch window is derived.

Deriving that window is a two-step calculation whose order is pinned. First, `weighted_age_days` is the egg-count weighted mean storage age of the eggs actually loaded: multiply each `ACTIVE` draw's `eggs_taken` by its frozen `effective_age_days_at_set`, sum those products across all `ACTIVE` draws, divide by the sum of `eggs_taken` across the same draws, and round half up to four decimal places. Voided draws take no part. Second, `storage_delay_hours` is derived from that mean: subtract the free storage allowance of 3 days from `weighted_age_days`, treat a negative difference as zero, convert the remainder to hours at one hour of incubation delay per day of excess storage, and take the ceiling of that whole expression to a whole number of hours, never below zero. The order matters and reversing it is wrong: the weighted mean is computed and rounded to four decimal places *first*, then the allowance is subtracted, then a **single** ceiling is applied — ceilinging each draw's own delay and then weighting produces a different answer.

From there the schedule falls out. `planned_transfer_at` is `set_at` advanced by the profile's `transfer_hours` plus `storage_delay_hours`. `planned_pull_at` is `set_at` advanced by the profile's `total_hours` plus `storage_delay_hours`. The hatch window straddles the nominal pull symmetrically: `pull_window_start_at` is 6 hours before `planned_pull_at` and `pull_window_end_at` is 6 hours after it.

**Environment monitoring** runs on an independent dimension. A setter load carries `environment_status` — `NOMINAL`, `DEVIATION_OPEN` or `DEVIATION_RESOLVED` — that moves without ever affecting the load's incubation `status`. An `IncubationOperator` ingests a probe reading against a load that is `INCUBATING`, supplying a `recorded_at` instant, a `temp_c` dry-bulb temperature between 30.0 and 45.0 inclusive and a `humidity_pct` relative humidity between 20.0 and 90.0 inclusive. The `recorded_at` must be at or after the load's `set_at`, must not be later than the current logical clock, and must be strictly after the `recorded_at` of the load's latest existing reading; all three violations report `ERR_TIMESTAMP_OUT_OF_RANGE`. Readings are therefore strictly increasing per load.

Each reading derives three values of its own. Its `elapsed_hours` is the time from the load's `set_at` to its `recorded_at` expressed in hours and rounded half up to two decimal places, and that figure selects the applicable profile stage — the stage whose range starts at or before `elapsed_hours` and ends strictly after it. Its `target_temp_c` is that stage's `temp_c`. Its `abs_deviation_c` is the absolute difference between the measured `temp_c` and `target_temp_c`, rounded half up to two decimal places.

Degree-hours are then integrated as a **left-endpoint step function**, and this is the subtlest calculation in the specification. Readings of a load are processed in ascending `recorded_at` order, with ascending `created_at` as the only tie-break. Ingesting a reading closes the segment that runs from the *previous* reading's `recorded_at` up to this reading's `recorded_at`, and charges that whole segment at the **previous** reading's excess deviation held constant across it. Concretely: take the previous reading's `abs_deviation_c`, subtract the temperature tolerance of 0.30 degrees Celsius, and treat a negative result as zero — that is the excess. Take the span between the two readings' `recorded_at` instants expressed in hours. The segment's `segment_degree_hours` is the excess multiplied by the span, rounded half up to three decimal places. That figure is then added to the load's running `deviation_degree_hours`, which accumulates across the entire incubation and is never reset. Each segment is rounded before it joins the total. The first reading of a load closes no segment, so its `segment_degree_hours` is 0.

The environment dimension is evaluated after that accumulation, and the comparison is strict. If the segment just closed has `segment_degree_hours` strictly greater than the deviation-open threshold of 1.50 degree-hours, the load's `environment_status` becomes `DEVIATION_OPEN` and its `deviation_opened_at` is set to the ingested reading's `recorded_at` — a segment of exactly 1.500 degree-hours does **not** open a deviation. Otherwise, if the load is currently `DEVIATION_OPEN` and the uninterrupted run of within-tolerance segments ending at this reading spans at least 2.0 hours, the load's `environment_status` becomes `DEVIATION_RESOLVED`; a segment counts as within tolerance precisely when its `segment_degree_hours` is exactly 0. A resolved load can be re-opened: from `DEVIATION_RESOLVED` a further segment above the 1.50 threshold drives it back to `DEVIATION_OPEN` and re-stamps `deviation_opened_at`, and the degree-hour total continues to accumulate across cycles rather than restarting. A within-tolerance reading against a `NOMINAL` load leaves the dimension at `NOMINAL` and leaves `deviation_degree_hours` unchanged, because the segment contributed 0. Every ingested reading increments the load's `version` by 1 — but not the reading's own, since environment readings have no `version` field.

Candling closes the fertility question. An `IncubationOperator` records a `fertile_count` against an `INCUBATING` load, moving it `INCUBATING → CANDLED`. The `fertile_count` may not exceed `total_eggs_set`, or `ERR_COUNT_EXCEEDS_SOURCE`, and the current logical clock may not precede the load's `set_at`, or `ERR_TIMESTAMP_OUT_OF_RANGE`. On success `fertility_pct` is `fertile_count` divided by `total_eggs_set`, multiplied by 100 and rounded half up to two decimal places, and the load's `version` increments by 1.

Aborting a load is a `HatcheryManager` act taking a `reason` that is stored as `abort_reason`, and its consequences depend sharply on how far the load had progressed. From `PLANNED`, every `ACTIVE` draw flips to `VOIDED` and returns its `eggs_taken` to its lot's `eggs_remaining`, `total_eggs_set` is recomputed to 0, and every lot whose eggs are thereby fully restored steps back `ALLOCATED → IN_STORAGE` — the eggs live to be set another day. From `INCUBATING` or from `CANDLED` the outcome is harsher and identical between the two: every `ACTIVE` draw flips to `VOIDED`, every contributing lot then sitting in `SET` moves to `CONDEMNED` with a `condemned_reason` of `LOAD_ABORTED` because part-incubated eggs cannot go back in the cooler, and the machine's `occupancy_status` is released to `FREE`. In all three cases the load's `version` increments by 1, as does every record the cascade touches. `ABORTED` and `TRANSFERRED` are both terminal for a setter load.

### 3.6. Transfer, the Hatch Window and the Pull Branches

Transfer is the handover from setter to hatcher, and it is the last chance to stop a compromised set. An `IncubationOperator` transfers a `CANDLED` load by naming the `hatcher_unit_id` of the destination machine. Three gates apply: the load's `environment_status` must not be `DEVIATION_OPEN`, otherwise `ERR_ENVIRONMENT_DEVIATION_OPEN` — eggs whose temperature excursion has not yet cleared may not proceed; and the destination machine named by `hatcher_unit_id` must be of `unit_type` `HATCHER` (otherwise `ERR_UNIT_TYPE_MISMATCH`), must have `sanitation_status` of `SANITIZED` (otherwise `ERR_UNIT_NOT_SANITIZED`) and must have `occupancy_status` of `FREE` (otherwise `ERR_UNIT_OCCUPIED`).

A successful transfer moves the setter load `CANDLED → TRANSFERRED` and creates a **hatcher load** in `HATCHING`, whose `setter_load_id` names the load transferred in and whose `unit_id` names the hatcher machine. The new record freezes a snapshot of the incubation history at that instant: `transferred_at` from the logical clock, `eggs_transferred` copying the setter load's `total_eggs_set`, `planned_pull_at`, `pull_window_start_at` and `pull_window_end_at` copying the setter load's corresponding instants, and `inherited_degree_hours` copying the setter load's `deviation_degree_hours` to three decimal places. Those copies are frozen — later activity on the setter load never rewrites them, and `inherited_degree_hours` is the frozen input the chick quality score reads. The new hatcher load starts with `quality_flag` of `NONE` and nulls for `actual_pull_at`, `pull_offset_hours`, `pull_class` and `hold_release_at`. Meanwhile the setter machine's `occupancy_status` is released to `FREE`, the hatcher machine becomes `OCCUPIED` and `DIRTY`, and every contributing egg lot moves `SET → CONSUMED` with its `eggs_remaining` set to 0. Every record in that chain has its `version` incremented.

Pulling chicks is where **hatch window management** earns its keep, and the position of the logical clock relative to the frozen window selects one of three branches. A `ChickProcessor` supplies a `hatched_count` of at least 1 giving the live chicks counted at pull, which may not exceed `eggs_transferred` or the pull is rejected with `ERR_COUNT_EXCEEDS_SOURCE`. In all three branches `actual_pull_at` is stamped from the logical clock, `pull_offset_hours` records the signed hours by which the pull fell outside the window to two decimal places, and a chick batch is created in `PULLED` carrying a `hatcher_load_id` naming the pull that produced it, a `primary_flock_id`, a computed `breed`, the supplied `hatched_count`, and a provisional quality score. A hatcher load is pulled exactly once; a second pull from `EARLY_PULLED`, `WINDOW_PULLED` or `LATE_PULLED` is rejected with `ERR_INCUBATION_INVALID_STATE`.

The three branches are specified symmetrically and differ in exactly three things — the state reached, the quality consequence, and the follow-on effect:

- **Early.** When the logical clock is strictly before `pull_window_start_at`, the load moves `HATCHING → EARLY_PULLED`, `pull_class` is `EARLY` and `pull_offset_hours` is negative, being the hours from the pull instant back to `pull_window_start_at`. The `quality_flag` becomes `UNHEALED_NAVEL`, and `hold_release_at` is set to `actual_pull_at` advanced by the early hold of 4 hours; the chicks may not be boxed before that instant.
- **In window.** When the logical clock is at or after `pull_window_start_at` and at or before `pull_window_end_at`, the load moves `HATCHING → WINDOW_PULLED`, `pull_class` is `WINDOW` and `pull_offset_hours` is exactly 0. The `quality_flag` stays `NONE` and `hold_release_at` stays null.
- **Late.** When the logical clock is strictly after `pull_window_end_at`, the load moves `HATCHING → LATE_PULLED`, `pull_class` is `LATE` and `pull_offset_hours` is positive, being the hours from `pull_window_end_at` forward to the pull instant. The `quality_flag` becomes `DEHYDRATION`, `hold_release_at` stays null, and the batch's primary breeder flock has its `late_pull_count` incremented by 1 — the counter that lets analytics see a flock repeatedly missing its window.

The batch's `primary_flock_id` is the flock that contributed the most eggs to the originating setter load, measured by `eggs_taken` across the load's draws; when two flocks are tied, the flock of the contributing draw with the earliest `created_at` wins. The batch's `breed` is copied from that primary flock, and it is the value an order's `requested_breed` must match for the batch to be allocatable to it. Every record the pull touches — hatcher load, flock, new batch — has its `version` handled per §2.5.

The **chick quality score** is a score out of 100 that debits pull timing, inherited incubation deviation, culls and branch flags. It is computed in two variants at two different moments, and the difference between them is exact. Five penalties are defined:

- The early penalty applies only when `pull_class` is `EARLY`: multiply 1.80 by the absolute value of `pull_offset_hours` and round half up to two decimal places. It is 0.00 on the other two branches.
- The late penalty applies only when `pull_class` is `LATE`: multiply 2.40 by `pull_offset_hours` and round half up to two decimal places. It is 0.00 on the other two branches.
- The environment penalty multiplies 3.00 by `inherited_degree_hours`, rounds half up to two decimal places, and then caps the result at 25.00 — a badly deviating incubation cannot cost more than a quarter of the score.
- The cull penalty multiplies 0.90 by the cull rate expressed as a percentage, that is `cull_count` divided by `hatched_count` multiplied by 100, and rounds the product half up to two decimal places. The cull rate itself enters the multiplication unrounded.
- The flag penalty is a flat 4.00 whenever `quality_flag` is anything other than `NONE`, and 0.00 when it is `NONE`.

The score is 100.00 less the early penalty, less the late penalty, less the environment penalty, less the cull penalty, less the flag penalty, subtracted in that order, with each penalty rounded to two decimal places before it is subtracted and the final result rounded half up to two decimal places.

The **provisional** variant is computed at pull and stored as `quality_score_provisional`. Because no culls are known at that point, its cull penalty is forced to 0.00, and its flag penalty is forced to 0.00 as well — even on the early and late branches, which have already set `quality_flag`. Only the pull-timing penalty and the inherited environment penalty apply. The **final** variant is computed at boxing and stored as `quality_score_final`. It uses the resolved `cull_count`, meaning sexing culls plus vaccine culls, for the cull penalty, and it applies the flag penalty in full when `quality_flag` is `UNHEALED_NAVEL` or `DEHYDRATION`. Its pull-timing and environment penalties are identical to the provisional variant's, so the gap between the two scores is exactly the cull penalty plus the flag penalty.

### 3.7. Chick Processing: Sexing, Vaccination and Boxing

Chick processing is a strict three-step ladder run by a `ChickProcessor`: `PULLED → SEXED → VACCINATED → BOXED`. Skipping a rung — vaccinating an unsexed batch, boxing an unvaccinated one — is rejected with `ERR_CHICK_FLOW_INVALID_STATE`, and `BOXED` is terminal. The yield resolution that runs across these three steps is one calculation split into seven pinned steps, and the pinning exists to break an apparent circularity: the vaccine reject rate depends on the batch's yield, while the yield depends on the vaccine rejects. It is resolved by keying the tier on a **preliminary** yield that deliberately excludes vaccine culls.

Sexing supplies four counts — `male_count`, `female_count`, `unsexed_count` and `sexing_cull_count` — and they must sum to exactly `hatched_count` or the request is rejected with `ERR_SEX_COUNT_MISMATCH` (step 1). On success the four counts are stored and `preliminary_yield_pct` is computed (step 2): subtract `sexing_cull_count` from `hatched_count`, divide by `hatched_count`, multiply by 100, and round half up to two decimal places. The batch moves `PULLED → SEXED` and its `version` increments by 1. Only `sexing_cull_count` feeds the yield arithmetic; `male_count`, `female_count` and `unsexed_count` are recorded for the grower's information and enter no calculation.

Vaccination takes a `vaccine_code` naming the vaccine administered and moves the batch `SEXED → VACCINATED`, resolving steps 3 through 6. The `vaccine_reject_rate` is selected from a four-band tier on the **rounded** `preliminary_yield_pct` (step 3): 0.004 when the preliminary yield is 96.0 percent or above; 0.008 when it is at least 92.0 and below 96.0; 0.015 when it is at least 85.0 and below 92.0; and 0.028 when it is below 85.0. The lookup uses the rounded figure, so an unrounded preliminary yield of 95.996 rounds to 96.00 and therefore selects the 0.004 band. Then `vaccine_cull_count` is the ceiling of `hatched_count` less `sexing_cull_count`, multiplied by `vaccine_reject_rate` (step 4). Then `cull_count` is `sexing_cull_count` plus `vaccine_cull_count`, and `saleable_count` is `hatched_count` less `cull_count` (step 5). Then `final_yield_pct` is `saleable_count` divided by `hatched_count`, multiplied by 100 and rounded half up to two decimal places (step 6). The batch's `version` increments by 1. The `vaccine_code` records which vaccine was administered and has no bearing on the reject tier, which is keyed on `preliminary_yield_pct` alone.

Boxing is the busiest write in the system. It moves the batch `VACCINATED → BOXED` and is gated on one temporal rule: if the originating hatcher load has a non-null `hold_release_at` — which happens only on the early branch — the current logical clock must be at or after that instant, otherwise the request is rejected with `ERR_EARLY_HOLD_ACTIVE`. Boxing at exactly `hold_release_at` is allowed. When `hold_release_at` is null the gate does not apply at all.

On success, `box_count` is computed as the ceiling of `saleable_count` divided by the standard box of 100 chicks (step 7), `unassigned_chicks` is initialised to `saleable_count`, and `quality_score_final` is computed from the final variant of the quality score. The originating hatcher load then moves from whichever of `EARLY_PULLED`, `WINDOW_PULLED` or `LATE_PULLED` it was in to `PROCESSED`, and its hatcher machine's `occupancy_status` is released to `FREE` — the machine only comes free when the chicks actually leave it, not at pull. Both the batch's and the hatcher load's `version` increment by 1.

Boxing also closes the analytics loop back onto the breeder flock, which is covered in §3.9.

### 3.8. Placement Orders and the Whole-Box Allocation Waterfall

A placement order is a grower's standing request for chicks. It may be created either by a `HatcheryManager` or by the owning `GrowerFarm` principal, and it carries the `farm_id` of the destination farm, a `requested_breed`, a `requested_placement_date` giving the UTC date the grower wants the chicks placed, and a `requested_chicks` count that must be at least one full box of 100 chicks. The `requested_placement_date` may not fall before the current logical clock date. A new order starts at `status` of `REQUESTED` with `allocated_chicks` of 0 and `remaining_need` equal to `requested_chicks`; `remaining_need` is always `requested_chicks` less `allocated_chicks`, and `allocated_chicks` is always the sum of `chicks_assigned` across that order's delivery assignments in `ASSIGNED` or `DELIVERED`.

A `HatcheryManager` confirms an order, moving it `REQUESTED → CONFIRMED` and incrementing its `version`. Two gates apply beyond the state check. The destination farm's `biosecurity_status` must be `CLEARED`, otherwise `ERR_FARM_NOT_CLEARED`. And the farm's aggregate placement capacity must hold. The farm's placement cycle for an order is the **half-open** interval that starts at the order's `requested_placement_date` and ends 21 days later, excluding the end instant. Gather every other order of the same farm in `CONFIRMED`, `PARTIALLY_FULFILLED` or `FULFILLED` whose cycle intersects the new order's cycle, sum their `requested_chicks`, add the new order's `requested_chicks`, and reject with `ERR_FARM_CAPACITY_EXCEEDED` when that total is strictly greater than the farm's `capacity_chicks`. Because the interval is half-open, touching endpoints do **not** conflict: an order placed exactly 21 days after an existing one shares no time with it and consumes none of its capacity. Note the asymmetry with the machine window of §3.5, which is a closed interval where touching endpoints *do* conflict — the two overlap tests are deliberately different, and confusing them is the commonest way to get this wrong. Note also that orders which are individually well within capacity can still breach it together.

Allocation is run by a `HatcheryManager` against a boxed chick batch, under the optimistic concurrency described in §2.9 using `expected_chick_batch_version`. It is a **waterfall in whole boxes**, and it never splits a box.

An order qualifies for the run only when every one of five conditions holds: its `status` is `CONFIRMED` or `PARTIALLY_FULFILLED`; its `requested_breed` equals the batch's `breed`; its farm's `biosecurity_status` is `CLEARED`; the difference between its `requested_placement_date` and the current logical clock date, taken in absolute value, is at most the delivery tolerance of 2 days; and its `remaining_need` is strictly greater than 0. Qualifying orders are then ranked by `requested_placement_date` ascending, then by `remaining_need` descending, then by `created_at` ascending as the only remaining tie-break; `id` is never used for ranking.

The pool of chicks available to the run is the batch's `unassigned_chicks`. Walk the ranked orders in order. If the pool holds fewer than 100 chicks, stop immediately — nothing below a whole box can be granted. Otherwise take the smaller of the order's `remaining_need` and the pool, divide by 100 discarding the remainder, and multiply back by 100: that whole-box figure is the grant. A grant of zero means this order cannot absorb a full box and the walk moves on to the next order without creating anything. A non-zero grant creates a delivery assignment whose `chick_batch_id` names the batch, whose `placement_order_id` names the order, whose `chicks_assigned` is the grant, whose `boxes_assigned` is the grant divided by 100, and whose `scheduled_delivery_date` copies the order's `requested_placement_date` at that instant. The grant is then subtracted from the pool and the walk continues. Once the walk ends, the batch's `unassigned_chicks` is set to whatever remains in the pool, and any sub-box remainder simply stays there — it is never allocated. Earlier orders are filled to the whole box before any chicks reach a later order, even when that leaves a later order with nothing at all.

If no order qualified for the run in the first place, the entire call is rejected with `ERR_NO_ELIGIBLE_PLACEMENT_ORDER` and nothing is created. Each order the run served advances: from `CONFIRMED` to `PARTIALLY_FULFILLED` when the grant is less than its `remaining_need`, from `CONFIRMED` to `FULFILLED` when the grant exactly equals its `remaining_need`, from `PARTIALLY_FULFILLED` back to `PARTIALLY_FULFILLED` when a further grant still leaves need outstanding, and from `PARTIALLY_FULFILLED` to `FULFILLED` when the grant closes the remaining need. In every case the order's `allocated_chicks` grows by the grant and `remaining_need` is recomputed, reaching 0 exactly when the order becomes `FULFILLED`, at which point `allocated_chicks` equals `requested_chicks`. Every order the run touched has its `version` incremented, as does the batch. `FULFILLED` is terminal in the forward direction; the only way out of it is the compensating reversal of §3.9.

### 3.9. Delivery, Reversal, Flock Analytics and Corrective Action

Delivery confirmation is a `HatcheryManager` act moving an assignment `ASSIGNED → DELIVERED`. The destination farm's `biosecurity_status` must **still** be `CLEARED` at that moment, otherwise `ERR_FARM_NOT_CLEARED` — a farm quarantined by a positive laboratory result after its orders were confirmed can no longer take chicks. The delivery must also land near its plan: the absolute difference between the current logical clock date and the assignment's `scheduled_delivery_date` may be at most the delivery tolerance of 2 days, otherwise `ERR_TIMESTAMP_OUT_OF_RANGE`. On success `delivered_at` is stamped from the logical clock and the assignment's `version` increments by 1. `DELIVERED` is terminal.

Reversal is the compensating path, available to a `HatcheryManager` from `ASSIGNED` only and taking a `reason` that is stored as `reversal_reason`. It moves the assignment `ASSIGNED → REVERSED` and unwinds both sides of the allocation in the same request: the batch's `unassigned_chicks` grows back by `chicks_assigned`, and the served order's `allocated_chicks` shrinks by `chicks_assigned` with `remaining_need` recomputed. The order then steps *backwards* through its own lifecycle. From `FULFILLED` it becomes `PARTIALLY_FULFILLED` when some allocation survives the reversal, that is when `allocated_chicks` after the reversal is still greater than 0. From `FULFILLED` it returns all the way to `CONFIRMED` when the reversal drops `allocated_chicks` to 0, in which case `remaining_need` is restored to the full `requested_chicks`. From `PARTIALLY_FULFILLED` it likewise returns to `CONFIRMED` when `allocated_chicks` reaches 0, again with `remaining_need` restored to `requested_chicks`. Batch, order and assignment each have their `version` incremented, and the `reversal_reason` is retained on the assignment for audit. `REVERSED` is terminal, and neither delivery nor a second reversal is possible from it or from `DELIVERED`.

**Rolling hatchability** is recomputed on the primary breeder flock every time a chick batch is boxed, on two different denominators. The window is the flock's completed sets ordered by the setter load's `set_at` descending, with the setter load's `created_at` descending as the only tie-break, truncated to the 3 most recent entries. A set counts as completed when the hatcher load it produced has yielded a chick batch that has reached `BOXED`; aborted loads never enter the window; and a flock enters the window as a batch's `primary_flock_id`. Both variants are **pooled** ratios — the sum of numerators over the sum of denominators — and emphatically not the mean of the per-set percentages.

The set-basis variant is stored as `hatchability_rolling_pct`: sum `saleable_count` across the window's batches, divide by the sum of `total_eggs_set` across the window's setter loads, multiply by 100, and round half up to two decimal places. Because its denominator counts every egg set whether fertile or not, poor fertility depresses it. The fertile-basis variant is stored as `hatchability_fertile_pct`: the same numerator, divided by the sum of `fertile_count` across the window's setter loads from candling, multiplied by 100 and rounded half up to two decimal places. It isolates incubation performance from flock fertility, is therefore always at least as large as the set-basis figure, and is reported for analytics only. Both fields stay null until the flock's first chick batch is boxed. The ratio is rounded once, after both sums are complete.

Only the set-basis figure gates corrective action, and the comparison is strictly less than. When a boxing recomputation leaves `hatchability_rolling_pct` strictly below the hatchability threshold of 82.0 percent, the system automatically opens a **corrective action** against that flock. The new action carries the `flock_id` of the flock, a `trigger_reason` of `HATCHABILITY_BELOW_THRESHOLD`, an `observed_hatchability_pct` holding the set-basis figure that tripped the threshold, an `opened_at` from the logical clock, an `opened_by_user_id` recording the `X-User-ID` of the principal whose boxing call caused the auto-open, a `status` of `OPEN`, a `verification_round` of 1 and a null `implementation_note`. The flock's `corrective_action_count` is incremented and, because a count of 1 or more activates the 0.95 derate, its `settable_forecast` is recomputed on the spot — an underperforming flock's forecast drops the moment the underperformance is recognised. The `trigger_reason` enumeration also admits `REPEATED_LATE_PULL`, recorded on an action opened because a flock's `late_pull_count` has accumulated, and `LAB_POSITIVE`, recorded on an action opened off a positive laboratory result; `observed_hatchability_pct` is null for both of those non-hatchability reasons.

Working an action off is a four-state loop with a duty split at the end. A `FlockManager` acknowledges an `OPEN` action, moving it `OPEN → ACKNOWLEDGED` and incrementing its `version`. The same `FlockManager` role then records the measure taken by supplying a `note`, moving the action `ACKNOWLEDGED → IMPLEMENTED`, storing the note as `implementation_note` and incrementing `version`. Verification belongs to a `Veterinarian`, who supplies an `outcome`, and in both outcomes the acting `X-User-ID` must differ from the recorded `opened_by_user_id` or the call is rejected with `ERR_SEGREGATION_OF_DUTIES` before the action's state is examined. An outcome of `PASS` moves the action `IMPLEMENTED → VERIFIED`, decrements the flock's `corrective_action_count` by 1 and recomputes its `settable_forecast` — the 0.95 derate falls away only once the count returns to 0, so a flock carrying two open actions stays derated after the first is verified. An outcome of `FAIL` moves the action `IMPLEMENTED → OPEN`, adds 1 to `verification_round` and clears `implementation_note` back to null; the action then re-enters the acknowledge-implement-verify loop and must be acknowledged again before it can be implemented. `VERIFIED` is terminal, and any step attempted from it is rejected with `ERR_CORRECTIVE_ACTION_INVALID_STATE`. Both outcomes increment the action's `version` by 1.

## 4. Endpoint Definitions

Operations that create a new record — a programme, a profile, a machine, a flock, an egg lot, a setter load, a draw, an environment reading, a hatcher load produced by transfer, a chick batch produced by a pull, a farm, a placement order, a laboratory sample, or the delivery assignments produced by an allocation run — return `201 Created`. Operations that modify an existing record, including every state transition and every sanitation, clearance or recompute call, return `200 OK`. The logical-clock setter also returns `200 OK`. Request and response payloads are not repeated here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Sets the server's logical clock. Before any call the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. Every age, window, deviation and delivery-tolerance rule reads this clock. | HatcheryManager, FlockManager, IncubationOperator, ChickProcessor, Veterinarian, GrowerFarm |
| POST | `/flock-programs` | Creates a lighting and nutrition program | HatcheryManager |
| GET | `/flock-programs/{id}` | Reads one program | HatcheryManager, FlockManager, Veterinarian |
| POST | `/flock-programs/{id}/retire` | Retires a program so no new flock may be placed under it | HatcheryManager |
| POST | `/incubation-profiles` | Creates an incubation temperature and humidity profile | HatcheryManager |
| GET | `/incubation-profiles/{id}` | Reads one profile | HatcheryManager, IncubationOperator |
| POST | `/incubation-units` | Registers a setter or hatcher machine | HatcheryManager |
| GET | `/incubation-units/{id}` | Reads one machine | HatcheryManager, IncubationOperator, Veterinarian |
| POST | `/incubation-units/{id}/sanitize` | Records a sanitation cycle on a machine | IncubationOperator |
| POST | `/breeder-flocks` | Places a breeder flock under a lighting and nutrition program | FlockManager |
| GET | `/breeder-flocks/{id}` | Reads one flock with its recomputed age and forecast fields | HatcheryManager, FlockManager, Veterinarian |
| GET | `/breeder-flocks` | Lists flocks, filterable by program, lineage source and status | HatcheryManager, FlockManager, Veterinarian |
| POST | `/breeder-flocks/{id}/start-lay` | Photostimulates the flock into production | FlockManager |
| POST | `/breeder-flocks/{id}/deplete` | Retires the flock at end of lay | FlockManager |
| POST | `/breeder-flocks/{id}/release-hold` | Releases an EGG_HOLD after a clean re-test, by a different user than the one who opened it | Veterinarian |
| POST | `/breeder-flocks/{id}/recompute-forecast` | Recomputes the age tier, lighting and nutrition factors and settable forecast against the current clock | FlockManager |
| POST | `/egg-lots` | Records a hatching egg collection | FlockManager |
| GET | `/egg-lots/{id}` | Reads one lot with its recomputed effective age | HatcheryManager, FlockManager, IncubationOperator, Veterinarian |
| GET | `/egg-lots` | Lists lots, filterable by owning flock and status | HatcheryManager, FlockManager, IncubationOperator, Veterinarian |
| POST | `/egg-lots/{id}/grade` | Grades a collected lot into settable and rejected eggs | FlockManager |
| POST | `/egg-lots/{id}/store` | Moves a graded lot into the egg cooler at a recorded temperature | IncubationOperator |
| POST | `/egg-lots/{id}/sanitation-hold` | Pulls a stored lot for a sanitation cycle | Veterinarian |
| POST | `/egg-lots/{id}/sanitation-release` | Returns a sanitized lot to storage, permanently ageing it | IncubationOperator |
| POST | `/egg-lots/{id}/condemn` | Condemns a lot, voiding any outstanding setter draws | Veterinarian |
| GET | `/egg-lots/{id}/setter-load-items` | Lists every draw made against this lot, including voided ones | HatcheryManager, IncubationOperator |
| POST | `/setter-loads` | Plans a setter load in a machine under an incubation profile | IncubationOperator |
| GET | `/setter-loads/{id}` | Reads one load with both state dimensions and the derived window | HatcheryManager, IncubationOperator, Veterinarian |
| GET | `/setter-loads` | Lists loads, filterable by machine, profile and status | HatcheryManager, IncubationOperator, Veterinarian |
| POST | `/setter-loads/{id}/items` | Draws eggs from a stored lot into a planned load under optimistic concurrency on the lot | IncubationOperator |
| GET | `/setter-loads/{id}/items` | Lists the load's draws | HatcheryManager, IncubationOperator |
| POST | `/setter-loads/{id}/start` | Starts incubation, deriving the storage delay, transfer time and hatch window | IncubationOperator |
| POST | `/setter-loads/{id}/environment-readings` | Ingests one probe reading, closing the previous segment and updating the environment dimension | IncubationOperator |
| GET | `/setter-loads/{id}/environment-readings` | Lists the load's readings in recorded_at order | HatcheryManager, IncubationOperator, Veterinarian |
| POST | `/setter-loads/{id}/candle` | Records the fertile egg count at candling | IncubationOperator |
| POST | `/setter-loads/{id}/abort` | Aborts a load, voiding its draws and releasing its machine | HatcheryManager |
| POST | `/setter-loads/{id}/transfer` | Transfers a candled load into a hatcher machine | IncubationOperator |
| GET | `/hatcher-loads/{id}` | Reads one hatcher load with its window, pull class and quality flag | HatcheryManager, IncubationOperator, ChickProcessor |
| GET | `/hatcher-loads` | Lists hatcher loads, filterable by source load, machine and status | HatcheryManager, IncubationOperator, ChickProcessor |
| POST | `/hatcher-loads/{id}/pull` | Pulls chicks; the clock position relative to the hatch window selects the EARLY, WINDOW or LATE branch | ChickProcessor |
| GET | `/chick-batches/{id}` | Reads one chick batch with both quality scores and the allocation pool | HatcheryManager, ChickProcessor, Veterinarian |
| GET | `/chick-batches` | Lists chick batches, filterable by hatcher load and primary flock | HatcheryManager, ChickProcessor, Veterinarian |
| POST | `/chick-batches/{id}/sex` | Records sexing counts and the preliminary yield | ChickProcessor |
| POST | `/chick-batches/{id}/vaccinate` | Vaccinates the batch, resolving the reject tier, culls, saleable count and final yield | ChickProcessor |
| POST | `/chick-batches/{id}/box` | Boxes the batch, freezing the final quality score and driving the flock hatchability and corrective-action cascade | ChickProcessor |
| POST | `/chick-batches/{id}/allocations` | Runs the whole-box allocation waterfall over eligible placement orders under optimistic concurrency on the batch | HatcheryManager |
| POST | `/grower-farms` | Registers a grower farm and the operator principal that owns its scope | HatcheryManager |
| GET | `/grower-farms/{id}` | Reads one farm | HatcheryManager, Veterinarian, GrowerFarm |
| POST | `/grower-farms/{id}/clear` | Clears a farm for chick placement after biosecurity review | Veterinarian |
| POST | `/placement-orders` | Places a chick placement order for a farm | HatcheryManager, GrowerFarm |
| GET | `/placement-orders/{id}` | Reads one placement order | HatcheryManager, GrowerFarm |
| GET | `/placement-orders` | Lists placement orders, filterable by farm and status | HatcheryManager, GrowerFarm |
| POST | `/placement-orders/{id}/confirm` | Confirms an order against farm clearance and the aggregate 21-day cycle capacity | HatcheryManager |
| GET | `/delivery-assignments/{id}` | Reads one delivery assignment | HatcheryManager, GrowerFarm |
| GET | `/delivery-assignments` | Lists assignments, filterable by batch and order | HatcheryManager, GrowerFarm |
| POST | `/delivery-assignments/{id}/deliver` | Confirms delivery of the boxed chicks to the grower farm | HatcheryManager |
| POST | `/delivery-assignments/{id}/reverse` | Compensates an assignment, returning the chicks to the batch pool and stepping the order back | HatcheryManager |
| POST | `/lab-tests` | Registers a laboratory sample against a flock, machine or farm | Veterinarian |
| GET | `/lab-tests/{id}` | Reads one laboratory test | HatcheryManager, Veterinarian, FlockManager |
| GET | `/lab-tests` | Lists laboratory tests, filterable by polymorphic subject and status | HatcheryManager, Veterinarian, FlockManager |
| POST | `/lab-tests/{id}/release` | Releases a result; POSITIVE drives the subject-specific biosecurity cascade | Veterinarian |
| GET | `/corrective-actions/{id}` | Reads one breeder flock corrective action | HatcheryManager, FlockManager, Veterinarian |
| GET | `/corrective-actions` | Lists corrective actions, filterable by flock and status | HatcheryManager, FlockManager, Veterinarian |
| POST | `/corrective-actions/{id}/acknowledge` | Acknowledges an open corrective action | FlockManager |
| POST | `/corrective-actions/{id}/implement` | Records the implemented corrective measure | FlockManager |
| POST | `/corrective-actions/{id}/verify` | Verifies an implemented action; a FAIL outcome reopens it with an incremented verification round | Veterinarian |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_FARM_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_NON_POSITIVE_COUNT` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FLOCK_PROGRAM_NOT_FOUND` | 404 |
| `ERR_INCUBATION_PROFILE_NOT_FOUND` | 404 |
| `ERR_INCUBATION_UNIT_NOT_FOUND` | 404 |
| `ERR_BREEDER_FLOCK_NOT_FOUND` | 404 |
| `ERR_EGG_LOT_NOT_FOUND` | 404 |
| `ERR_SETTER_LOAD_NOT_FOUND` | 404 |
| `ERR_HATCHER_LOAD_NOT_FOUND` | 404 |
| `ERR_CHICK_BATCH_NOT_FOUND` | 404 |
| `ERR_GROWER_FARM_NOT_FOUND` | 404 |
| `ERR_PLACEMENT_ORDER_NOT_FOUND` | 404 |
| `ERR_DELIVERY_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_LAB_TEST_NOT_FOUND` | 404 |
| `ERR_CORRECTIVE_ACTION_NOT_FOUND` | 404 |
| `ERR_FLOCK_INVALID_STATE` | 409 |
| `ERR_EGG_LOT_INVALID_STATE` | 409 |
| `ERR_INCUBATION_INVALID_STATE` | 409 |
| `ERR_CHICK_FLOW_INVALID_STATE` | 409 |
| `ERR_ORDER_INVALID_STATE` | 409 |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 |
| `ERR_LAB_TEST_ALREADY_RELEASED` | 409 |
| `ERR_CORRECTIVE_ACTION_INVALID_STATE` | 409 |
| `ERR_PROGRAM_RETIRED` | 409 |
| `ERR_LAB_CLEARANCE_MISSING` | 422 |
| `ERR_UNIT_NOT_SANITIZED` | 422 |
| `ERR_ENVIRONMENT_DEVIATION_OPEN` | 422 |
| `ERR_FARM_NOT_CLEARED` | 422 |
| `ERR_EGG_TOO_OLD` | 422 |
| `ERR_TIMESTAMP_OUT_OF_RANGE` | 422 |
| `ERR_EARLY_HOLD_ACTIVE` | 422 |
| `ERR_GRADE_COUNT_MISMATCH` | 422 |
| `ERR_NO_SETTABLE_EGGS` | 422 |
| `ERR_SEX_COUNT_MISMATCH` | 422 |
| `ERR_COUNT_EXCEEDS_SOURCE` | 422 |
| `ERR_NO_EGGS_LOADED` | 422 |
| `ERR_UNIT_OCCUPIED` | 409 |
| `ERR_UNIT_TYPE_MISMATCH` | 422 |
| `ERR_UNIT_CAPACITY_EXCEEDED` | 422 |
| `ERR_FLOCK_EGG_HOLD` | 422 |
| `ERR_FLOCK_NOT_MATURE` | 422 |
| `ERR_BREED_MISMATCH` | 422 |
| `ERR_LAB_SUBJECT_INVALID` | 422 |
| `ERR_INSUFFICIENT_SETTABLE_EGGS` | 422 |
| `ERR_UNIT_WINDOW_CONFLICT` | 409 |
| `ERR_FARM_CAPACITY_EXCEEDED` | 422 |
| `ERR_NO_ELIGIBLE_PLACEMENT_ORDER` | 422 |

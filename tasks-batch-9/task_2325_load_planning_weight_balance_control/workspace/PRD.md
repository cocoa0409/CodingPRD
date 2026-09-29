# Load Control Weight And Balance API — Product Requirements Document

## 1. Introduction

An airline load control centre is the last place where a departure can still be stopped cheaply. Between the moment a flight is opened for planning and the moment a captain signs for the load, a controller must reconcile a structural airframe limit, a runway-and-weather performance limit, a centre-of-gravity envelope, a compartment-by-compartment stowage limit, a dangerous-goods segregation rule and a stream of late gate-checked bags — and must be able to prove afterwards, from documentation alone, which figures were used and why. Today that reconciliation happens across spreadsheets, printed performance tables and verbal handovers, which is precisely why load-sheet discrepancies are found after departure rather than before it.

This document specifies the Load Control Weight and Balance API: a single system of record for airframe and runway reference data, passenger weight programmes, load plans, load sheets, dangerous-goods declarations, last-minute changes and post-flight load audits. The API is deliberately opinionated about arithmetic. Every mass, index and centre-of-gravity figure it publishes is derived by a pinned evaluation order with a pinned rounding discipline, so that two controllers looking at the same flight see the same numbers to the last decimal, and so that an auditor recomputing a load sheet six weeks later arrives at the figure that was actually issued.

The system also encodes the segregation of duties that regulators expect. A controller may build and issue a load sheet but may never accept it as commander; an officer who accepted a dangerous-goods declaration on a flight may never be the inspector who closes that flight's load audit. These are not advisory guidelines in this API — they are enforced request-time rejections.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint: authentication, response shape, pagination, identity and revision semantics, arithmetic precision, the index system, reference-data posture, path resolution, cascade propagation, stale-version protection, the validation precedence ladder, and the logical clock.

### 2.1. Operating Roles and Request Authentication

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming that operator's capacity. Six roles exist, spelled exactly as follows: `LoadControlAdmin`, `LoadController`, `RampAgent`, `DangerousGoodsOfficer`, `Captain`, and `AuditInspector`. A request whose `X-User-Role` header is absent, or whose value is not one of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but is not among the roles authorised for the called endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

`LoadControlAdmin` is the load control centre supervisor: it maintains reference data (airframes, compartments, runways, performance bands, weight programmes), cancels and closes flights, and positions the logical clock. `LoadController` builds the distribution, computes the balance, applies offloads, issues the load sheet, records and reverses last-minute changes, revises departure conditions and records departure. `RampAgent` books consignments, accepts or refuses them, stows them, presents gate-checked bags and submits dangerous-goods declarations. `DangerousGoodsOfficer` accepts or rejects those declarations after the segregation check. `Captain` accepts or rejects the load sheet. `AuditInspector` opens, investigates and closes post-flight load audits. All six roles may perform every read.

Identity in this system is deliberately non-relational. When `X-User-Role` is `LoadControlAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same holds when `X-User-Role` is `LoadController`, when it is `RampAgent`, when it is `DangerousGoodsOfficer`, when it is `Captain`, and when it is `AuditInspector`. For all six roles the server never compares `X-User-ID` to any entity's `id` and never derives resource ownership from it. The server does, however, record the value where a scaffolded transition writes it: `issued_by_user_id` and `accepted_by_user_id` on a load sheet, `accepted_by_user_id` on a dangerous-goods declaration, and `closed_by_user_id` on a load audit. The two segregation-of-duties rules described later in this document compare those recorded strings against the incoming `X-User-ID` — string against string, never against an entity key.

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

Every list endpoint accepts two optional query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

List results are ordered by `created_at` ascending unless a specific endpoint narrative states otherwise. The `meta` object of a list response carries `limit`, `offset`, `total_count` — the count of rows matching the filters before the page window is applied — and `has_more`, which is true when rows remain beyond the current window.

### 2.4. Resource Identity, Timestamps and Revision Counters

Every resource in this API carries a server-minted `id` in UUID form. Identifiers never carry a type prefix; a load plan identifier and an aircraft identifier are distinguishable only by the collection they were read from. Clients never supply an `id`.

Every resource also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the row is created. `updated_at` is refreshed and `version` is incremented by exactly 1 on every mutation of that row, including mutations reached indirectly through a cascade from another entity's transition. Every entity in this system — `Aircraft`, `Compartment`, `Runway`, `PerformanceBand`, `WeightProgram`, `Flight`, `LoadPlan`, `PaxDistributionLine`, `BagAllocation`, `CargoItem`, `HazmatDeclaration`, `LoadSheet`, `LastMinuteChange` and `LoadAudit` — carries the full set of `id`, `created_at`, `updated_at` and `version`. There are no identity-only entities here.

The revision counters that matter operationally are `Flight.version` and `LoadPlan.version`, because those two are the anchors of the stale-version protection described in §2.10.

### 2.5. Mass, Index and Percent-MAC Arithmetic

Unless a rule below names a different discipline, every computed numeric figure in this system is rounded to 2 decimal places using round-half-up. That applies to masses in kilograms, to index units, and to centre-of-gravity figures expressed as a percentage of the mean aerodynamic chord.

Two deliberate exceptions exist and both are load-bearing. First, the performance-limited takeoff weight is not rounded at the end: it is taken *down* to the greatest multiple of 10 kilograms that does not exceed the raw figure — a conservative floor, never a round. Second, the allowed payload is floored at zero: if every candidate limit computes negative, the published allowed payload is 0 rather than a negative number.

Where a formula contains nested rounding steps, the order of those steps is pinned by the formula's own description and is never left to the implementer's discretion. The one place where a client may choose the order is the index accumulation of a load plan, governed by `rounding_mode` (see §2.6 and §3.6); the two permitted modes are allowed to disagree in the final decimal of the index and therefore in the final decimal of the percent-MAC figures.

### 2.6. The Index System, the Reference Arm and the Envelope

Balance in this system is tracked through **index units** rather than raw moments, so that all arithmetic stays in a small, positive numeric range. The index contribution of a mass is always computed the same way, whatever the mass represents: take the mass in kilograms, multiply it by the difference between the arm at which the mass sits and the airframe's reference arm `ref_arm_m`, and divide by the airframe's index scaling constant `index_c`. That single expression is used for crew and pantry mass at `crew_arm_m`, for passengers at their cabin zone's `arm_m`, for checked bags at their hold's `arm_m`, for cargo at its assigned hold's `arm_m`, for takeoff fuel at `fuel_arm_m`, and for the mass moved by a last-minute change at that change's compartment `arm_m`. The airframe additionally carries `index_k`, an offset constant that keeps published index values positive; `index_k` participates only in the back-conversion from an index to an arm, described in §3.6.

The airframe declares its centre-of-gravity envelope as four percent-MAC bounds plus a weight-dependent knee. `zfw_fwd_limit_pct_mac` is the inclusive forward bound and `zfw_aft_limit_pct_mac` the inclusive aft bound at zero-fuel weight. `tow_fwd_limit_pct_mac` is the inclusive forward bound at takeoff weight, and `tow_aft_limit_pct_mac` the inclusive aft bound at takeoff weight *below the envelope knee*. Above the knee the aft takeoff bound tightens: when takeoff weight is strictly greater than `tow_knee_weight_kg`, the signed adjustment `tow_aft_knee_adjust_pct_mac` — which is never positive — is added to `tow_aft_limit_pct_mac` to produce the effective aft bound. At or below the knee weight, no adjustment is applied. The geometry needed to turn an index back into a percent-MAC figure is `lemac_m`, the arm of the leading edge of the mean aerodynamic chord, and `mac_length_m`, the chord's length.

### 2.7. Reference-Data Posture and Configuration Gates

Three reference entities carry an availability posture that gates their use by new flights. An `Aircraft` is `IN_SERVICE` when registered and may be moved to `GROUNDED`; a `Runway` is `OPEN` when registered and may be moved to `CLOSED`; a `WeightProgram` is `ACTIVE` when published and may be moved to `WITHDRAWN`. These are the only two members of each posture enumeration, and the transition is one-way.

Posture is checked at flight creation only. Referencing a grounded airframe yields `ERR_AIRCRAFT_GROUNDED`, a closed runway yields `ERR_RUNWAY_CLOSED`, and a withdrawn programme yields `ERR_WEIGHT_PROGRAM_WITHDRAWN`, each with HTTP 409. Grounding an airframe, closing a runway or withdrawing a programme has no retroactive effect on flights already created against it: those flights continue through their lifecycle unchanged.

### 2.8. Nested Path Resolution and Reverse-Reachability Reads

Path parameters are resolved strictly left to right, and the first identifier that fails to resolve determines the error. A read of one airframe's compartments therefore reports `ERR_AIRCRAFT_NOT_FOUND` when the airframe identifier is unknown, and only descends to the compartment collection once the airframe exists. The full not-found family is `ERR_AIRCRAFT_NOT_FOUND`, `ERR_COMPARTMENT_NOT_FOUND`, `ERR_RUNWAY_NOT_FOUND`, `ERR_PERFORMANCE_BAND_NOT_FOUND`, `ERR_WEIGHT_PROGRAM_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`, `ERR_LOAD_PLAN_NOT_FOUND`, `ERR_PAX_LINE_NOT_FOUND`, `ERR_BAG_ALLOCATION_NOT_FOUND`, `ERR_CARGO_ITEM_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`, `ERR_LOAD_SHEET_NOT_FOUND`, `ERR_LAST_MINUTE_CHANGE_NOT_FOUND` and `ERR_AUDIT_NOT_FOUND`, all HTTP 404. The same family is used when a foreign key supplied in a request body fails to resolve.

Every parent-to-child relationship is readable in reverse. The compartments of an airframe are listed under that airframe and accept an optional `kind` filter; the performance bands of a runway are listed under that runway and accept an optional `aircraft_type_code` filter; the load plans, load audits of a flight and the load sheets of a plan are listed under their parent and accept an optional `status` filter; the declarations of a consignment are listed under that consignment and accept an optional `status` filter. Flat collections carry the corresponding foreign keys as filters instead: airframes filter on `status`, flights on `aircraft_id`, `departure_runway_id`, `weight_program_id` and `status`, passenger lines and bag allocations on `load_plan_id` and `compartment_id`, consignments on `flight_id`, `assigned_compartment_id`, `status` and `item_kind`, and last-minute changes on `load_sheet_id`, `compartment_id` and `status`. Every one of those filters is optional, and every one of those endpoints also accepts `limit` and `offset`.

### 2.9. Parallel State Dimensions and Cascade Propagation

A flight advances along two independent state dimensions that must never be conflated. The `status` dimension tracks the planning lifecycle through `PLANNING`, `LOAD_CONTROLLED`, `DEPARTED`, `CLOSED` and `CANCELLED`, of which `CLOSED` and `CANCELLED` are terminal, and starts at `PLANNING`. The `load_release_state` dimension tracks release of the load through `OPEN`, `HELD_FOR_DG` and `RELEASED`, starts at `OPEN`, and has `RELEASED` as its only terminal state. A dangerous-goods declaration can drive `load_release_state` from `OPEN` to `HELD_FOR_DG` while `status` sits at either `PLANNING` or `LOAD_CONTROLLED`, and it does not disturb `status` at all. Likewise, the release cycle `OPEN` → `HELD_FOR_DG` → `OPEN` may repeat any number of times before the load is finally released.

Several operations mutate more than one row. Where that happens, this document states every hop of the cascade explicitly, and every touched row has its own `updated_at` refreshed and its own `version` incremented by 1. The three multi-hop chains worth naming up front are: applying an offload, which offloads consignments, recomputes the plan and advances the flight's `status`; captain acceptance of a load sheet, which releases the load, loads the stowed consignments and stamps their dangerous-goods declarations as notified; and cancellation of a flight, which supersedes plans and sheets and offloads cargo. Each is described in full in §3.

### 2.10. Stale-Version Protection on Plan Creation and Sheet Issuance

Two write operations in this API legitimately supersede existing work, which means no state precondition can protect them; the only available signal that a caller is acting on an out-of-date view is an explicit version assertion. Both therefore require optimistic concurrency control.

A `POST /load-plans` request must carry `expected_flight_version` as a non-optional field of the body, holding the client's last observed `version` of the target `Flight`. If that value does not equal the flight's current `version`, the create is rejected with `ERR_STALE_FLIGHT_VERSION` (HTTP 412). The rejection protects the caller from opening a plan against an allowed payload, a set of departure conditions, or a prior plan that it has not observed.

A `POST /load-sheets` request must carry `expected_load_plan_version` as a non-optional field of the body, holding the client's last observed `version` of the target `LoadPlan`. If that value does not equal the plan's current `version`, issuance is rejected with `ERR_STALE_LOAD_PLAN_VERSION` (HTTP 412). The rejection protects the caller from snapshotting balance figures that are no longer the plan's current figures.

No other endpoint in this API takes a version field. In particular, computing a plan, applying an offload, presenting a gate bag, accepting or rejecting a sheet, amending a sheet, recording or reversing a last-minute change, and every load-audit operation are all unversioned.

### 2.11. Validation Precedence

When several checks could reject one request, they are evaluated in a fixed order and the first failure determines the response. The order is not a matter of implementation convenience: a caller must be able to predict which of two simultaneously-violated rules it will hear about. The ladder, from first evaluated to last, is:

1. Authentication — `X-User-Role` present and naming one of the six declared roles; otherwise `ERR_UNAUTHENTICATED`, 401. Applies to every endpoint.
2. Authorisation — the acting role appears in the called endpoint's authorised role list; otherwise `ERR_UNAUTHORIZED`, 403. Applies to every endpoint.
3. Request shape — every required input field present, every enum value a declared member, every weight, length and count field at least 0, with consignment `weight_kg` and compartment `length_m` required to be strictly greater than 0, and `limit` within 1 through 100 with `offset` at least 0 on list endpoints; otherwise `ERR_INVALID_REQUEST`, 400. Applies to every endpoint.
4. Path existence — every path-templated identifier resolves, checked left to right; otherwise the matching member of the not-found family from §2.8, 404. Applies to every endpoint with a path-templated identifier.
5. Body foreign-key existence — every foreign key in the request body resolves; otherwise the matching not-found error, 404. Applies to compartment creation, performance-band publication, flight creation, plan creation, passenger-line creation, bag-allocation creation, consignment booking, consignment stowage, declaration submission, sheet issuance, last-minute-change recording and audit creation.
6. Uniqueness — `Aircraft.registration` unique across airframes; `code` unique per `aircraft_id` on compartments; `designator` unique per `airport_code` on runways; `WeightProgram.code` unique across programmes; `awb_number` unique per `flight_id` on consignments; at most one `PaxDistributionLine` per plan-and-compartment pair; at most one `BagAllocation` per plan-and-compartment pair. Violation yields `ERR_DUPLICATE_KEY`, 409, on airframe, compartment, runway, weight-programme, consignment, passenger-line and bag-allocation creation.
7. Reference-data posture at flight creation — `ERR_AIRCRAFT_GROUNDED`, `ERR_RUNWAY_CLOSED` or `ERR_WEIGHT_PROGRAM_WITHDRAWN`, 409.
8. Flight planning state — `ERR_FLIGHT_INVALID_STATE`, 409. `PLANNING` is required to compute a plan and to apply an offload; `PLANNING` or `LOAD_CONTROLLED` is required to create a plan, create a passenger line, create a bag allocation, book a consignment, accept a consignment, stow a consignment and cancel a flight; `LOAD_CONTROLLED` is required to record departure; `DEPARTED` is required to close a flight and to amend a sheet; and `LOAD_CONTROLLED`, `DEPARTED` or `CLOSED` is required to open a load audit.
9. Flight load-release state — `ERR_LOAD_NOT_RELEASED`, 409. Departure requires `load_release_state` `RELEASED`; sheet acceptance requires `dg_hold_count` equal to 0. These are the only two operations this check guards.
10. Load-plan state — `ERR_PLAN_INVALID_STATE`, 409, on computing a plan, applying an offload, presenting a gate bag, issuing a sheet, creating a passenger line, creating a bag allocation, and deleting a passenger line.
11. Load-sheet state — `ERR_SHEET_INVALID_STATE`, 409, on sheet acceptance, sheet rejection, sheet amendment, and last-minute-change recording; recording a change requires the sheet to be `ISSUED` or `ACCEPTED`.
12. Consignment state — `ERR_CARGO_INVALID_STATE`, 409, on consignment acceptance, consignment refusal, consignment stowage, and declaration submission.
13. Declaration state — the declaration must be `SUBMITTED` for both acceptance and rejection; otherwise `ERR_DECLARATION_INVALID_STATE`, 409.
14. Audit state — `ERR_AUDIT_INVALID_STATE`, 409, on audit investigation and audit closure; investigation additionally requires `severity` to be `MAJOR` or `CRITICAL`.
15. Stale version — `expected_flight_version` must equal `Flight.version` on plan creation, and `expected_load_plan_version` must equal `LoadPlan.version` on sheet issuance; otherwise `ERR_STALE_FLIGHT_VERSION` or `ERR_STALE_LOAD_PLAN_VERSION`, 412.
16. Compartment belongs to the right airframe — the referenced compartment's `aircraft_id` must equal the `aircraft_id` of the flight owning the plan, consignment or sheet being modified; otherwise `ERR_COMPARTMENT_NOT_ON_AIRCRAFT`, 422, on passenger-line creation, bag-allocation creation, consignment stowage, gate-bag presentation and last-minute-change recording.
17. Compartment kind matches its use — a `CABIN_ZONE` compartment is required for a passenger line and for `PAX_ADD` or `PAX_REMOVE` changes; a `HOLD` compartment is required for a bag allocation, a consignment stowage, a gate bag and `BAG_ADD`, `BAG_REMOVE` or `CARGO_OFFLOAD` changes. Violation yields `ERR_COMPARTMENT_KIND_MISMATCH`, 422, on the same five operations as check 16.
18. Weight-programme field discipline on passenger-line creation — `ERR_ACTUAL_WEIGHT_REQUIRED` or `ERR_ACTUAL_WEIGHT_NOT_PERMITTED`, 422.
19. Performance-band coverage — exactly one band must cover the flight's runway, aircraft type and outside air temperature; otherwise `ERR_NO_PERFORMANCE_BAND`, 422, on flight creation and on revision of departure conditions.
20. Audit basis availability — a `FINAL_BASIS` audit requires an `ACCEPTED` or `AMENDED` sheet on the flight's highest-revision plan; otherwise `ERR_NO_ACCEPTED_SHEET`, 409.
21. Declaration eligibility — a declaration may only be submitted for a consignment flagged as dangerous goods; otherwise `ERR_NOT_DANGEROUS_GOODS`, 409.
22. Declared quantity — `quantity_kg` must not exceed the parent consignment's `weight_kg`; otherwise `ERR_DG_QUANTITY_EXCEEDS_ITEM`, 422.
23. Segregation compatibility on declaration acceptance — `ERR_DG_SEGREGATION_CONFLICT`, 409.
24. Dangerous-goods completeness before issuance — `ERR_DG_NOT_ACCEPTED`, 409, on sheet issuance.
25. Sheet segregation of duties — the `X-User-ID` accepting or rejecting a sheet must differ from that sheet's `issued_by_user_id`; otherwise `ERR_SEGREGATION_OF_DUTIES`, 409, on both sheet acceptance and sheet rejection.
26. Audit segregation of duties — the `X-User-ID` closing an audit must differ from every `accepted_by_user_id` recorded on any dangerous-goods declaration of that flight's cargo; otherwise `ERR_AUDIT_SEGREGATION_CONFLICT`, 409.
27. Seat capacity — `ERR_SEAT_CAPACITY_EXCEEDED`, 422, on passenger-line creation.
28. Compartment structural overload — `ERR_COMPARTMENT_OVERLOAD`, 422, on bag-allocation creation, consignment stowage and gate-bag presentation.
29. Compartment running load — `ERR_RUNNING_LOAD_EXCEEDED`, 422, on the same three operations as check 28.
30. Centre-of-gravity envelope — `ERR_CG_OUT_OF_ENVELOPE`, 422, on plan computation, offload application and gate-bag presentation.
31. Flight interval sanity — `scheduled_on_block_utc` strictly later than `scheduled_off_block_utc`; otherwise `ERR_INVALID_INTERVAL`, 422, on flight creation.
32. Airframe occupancy conflict — `ERR_AIRCRAFT_OCCUPANCY_CONFLICT`, 409, on flight creation.
33. Runway departure slot capacity — `ERR_RUNWAY_SLOT_FULL`, 409, on flight creation.
34. Fuel consistency — `ERR_FUEL_FIGURES_INCONSISTENT`, 422, on flight creation and on revision of departure conditions.
35. Offload sufficiency — `ERR_OFFLOAD_INSUFFICIENT`, 409, on offload application.
36. Last-minute-change allowance — `ERR_LMC_ALLOWANCE_EXCEEDED`, 422, on last-minute-change recording.
37. Finding note — closing a load audit requires a non-empty `finding_note`; otherwise `ERR_FINDING_NOTE_REQUIRED`, 422.

Two consequences of this ordering deserve emphasis. Because the flight-state check at position 8 precedes the plan-state check at position 10, a compute attempt on a flight that has already departed reports `ERR_FLIGHT_INVALID_STATE` and never `ERR_PLAN_INVALID_STATE`. And because the stale-version check at position 15 sits *after* every state check but *before* every business-safety check, a plan creation carrying a stale `expected_flight_version` against a cancelled flight reports `ERR_FLIGHT_INVALID_STATE`, while the same stale assertion against a healthy flight whose compartments would overload reports `ERR_STALE_FLIGHT_VERSION`.

### 2.12. The Logical Clock

All temporal reasoning in this system — scheduled off-block instants, runway slot windows, occupancy intervals and audit timestamps — is evaluated against a server-side logical clock, never against real wall-clock time. Before any client positions it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not fall back to the host's actual time under any circumstance.

A `LoadControlAdmin` may reposition the clock through `POST /_clock/set_current_utc`, supplying `to_iso8601` as the instant to move to. The response body reports the resulting `current_utc`. This capability exists so that departures, slot windows and post-departure amendments can be exercised deterministically.

## 3. Business Logic & Workflows

### 3.1. Establishing the Fleet and the Departure Environment

Before any flight can be planned, a `LoadControlAdmin` must populate four bodies of reference data. Registering an airframe records its `registration` — a mark of between 5 and 8 characters, unique across all airframes — together with its `type_code`, the ICAO type code that later joins to the `aircraft_type_code` of published performance bands. The airframe's mass baseline is `basic_empty_weight_kg`, which must be strictly greater than 0 and covers airframe and fixed equipment with no crew and no fuel, paired with `basic_index`, the index-unit expression of that mass's moment already normalised by the airframe's own `index_c` and `index_k`. Four structural ceilings are recorded: `max_takeoff_weight_kg`, `max_landing_weight_kg`, `max_zero_fuel_weight_kg` and `max_taxi_weight_kg`. The balance geometry is `ref_arm_m`, `lemac_m`, `mac_length_m`, `index_c`, `index_k` and `fuel_arm_m`, the last being a single-arm approximation of the usable fuel mass. The envelope is declared through `zfw_fwd_limit_pct_mac`, `zfw_aft_limit_pct_mac`, `tow_fwd_limit_pct_mac`, `tow_aft_limit_pct_mac`, `tow_knee_weight_kg` and `tow_aft_knee_adjust_pct_mac`, the last of which must not be positive. Finally `seat_count` records the certified passenger seat count; this figure is carried for documentation only and never limits a distribution — per-zone seating is limited exclusively by each compartment's `seat_capacity`. A newly registered airframe's `status` is `IN_SERVICE`; grounding it moves `status` to `GROUNDED`.

Each airframe is then subdivided into compartments. A compartment declares the `aircraft_id` it belongs to and a `code` unique within that airframe, such as OA, OB, H1 or H4. Its `kind` is either `CABIN_ZONE`, meaning it seats passengers, or `HOLD`, meaning it carries bags and cargo. Its centroid sits at `arm_m` metres from the datum; it may not carry more than `max_weight_kg`; its usable length is `length_m` metres; and its running-load ceiling is `running_load_limit_kg_per_m`, a limit in kilograms per metre that is meaningful for holds and ignored for cabin zones. `seat_capacity` defaults to 0 and is 0 for every hold.

Runways are registered with an `airport_code` and a `designator` unique within that airport, such as 04 or 22L. The threshold `elevation_ft` feeds the altitude penalty of the performance calculation; `length_m` records the takeoff run available and is documentation only. `slot_capacity_per_window` defaults to 2 and caps how many departures may share one departure slot window. A newly registered runway's `status` is `OPEN`; closing it moves `status` to `CLOSED`. Against each runway the administrator publishes performance bands: each band names the `runway_id` it applies to, the `aircraft_type_code` it covers, a temperature interval from `temp_lo_c` to `temp_hi_c`, and the `base_limit_weight_kg` that applies at sea level with zero wind on a dry runway. The interval is lower-inclusive and upper-exclusive: a band covers temperatures at or above `temp_lo_c` and strictly below `temp_hi_c`. Bands published for the same runway and type never overlap, so at most one band can ever match a given temperature.

The fourth body of reference data is the passenger weight programme. A programme has a `code` unique across all programmes and a `program_kind` of either `STANDARD` or `ACTUAL`. It carries table weights `male_kg`, `female_kg`, `child_kg` and `infant_kg` — an adult male, an adult female, a seated child and a lap infant respectively, each figure including hand baggage — plus `checked_bag_kg`, the per-bag figure used when a bag allocation supplies no weighed total. `documentation_ref` names the regulatory documentation substantiating the programme and is mandatory, because it is snapshotted onto every load sheet issued under the programme. A published programme's `status` is `ACTIVE`; withdrawing it moves `status` to `WITHDRAWN`.

### 3.2. Opening a Flight: Dry Operating Figures and the Performance-Limited Payload

A `LoadController` or a `LoadControlAdmin` opens a flight by supplying its `flight_number`, the `aircraft_id` operating it, the `departure_runway_id` whose performance bands will limit its takeoff weight, the `weight_program_id` in force, the `scheduled_off_block_utc` and `scheduled_on_block_utc` instants, the crew figures `crew_weight_kg` and `crew_arm_m` covering operating crew and pantry, the fuel figures `ramp_fuel_kg`, `taxi_fuel_kg` and `trip_fuel_kg`, and the departure conditions `outside_air_temp_c`, `headwind_component_kt` and `runway_condition`. `runway_condition` is one of `DRY`, `WET` or `CONTAMINATED`. The flight is created with `status` `PLANNING`, `load_release_state` `OPEN` and `dg_hold_count` 0.

Three temporal and fiscal gates guard creation. The on-block instant must be strictly later than the off-block instant, or the request is refused with `ERR_INVALID_INTERVAL`. Fuel figures must cohere: taxi fuel must not exceed ramp fuel, and trip fuel must not exceed ramp fuel less taxi fuel; a violation is `ERR_FUEL_FIGURES_INCONSISTENT`. And the airframe must be free. A flight occupies its airframe over a **closed** interval that begins at its off-block instant and ends 45 minutes — three quarters of an hour of turnaround buffer — after its on-block instant, inclusive at both ends. A new flight is refused with `ERR_AIRCRAFT_OCCUPANCY_CONFLICT` when its occupancy interval shares at least one instant with the occupancy interval of any existing flight on the same airframe whose `status` is `PLANNING`, `LOAD_CONTROLLED` or `DEPARTED`. Intervals that merely touch at a single endpoint do collide; back-to-back rotations must therefore be separated by more than the buffer, not exactly by it.

The runway slot check works on the opposite convention and it is worth reading twice. A departure at some instant belongs to the window that begins at that instant floored down to the nearest 10-minute boundary measured from the top of the hour, and that window is **half-open**: it includes its own start instant and excludes the instant exactly 10 minutes later. A new flight is refused with `ERR_RUNWAY_SLOT_FULL` when the number of existing flights on the same `departure_runway_id`, with `status` `PLANNING`, `LOAD_CONTROLLED` or `DEPARTED`, whose `scheduled_off_block_utc` falls inside that same window, already equals the runway's `slot_capacity_per_window`. A departure standing exactly on the next 10-minute boundary belongs to the following window and never collides with the current one.

Creation then derives three families of figures. The first is the **dry operating** pair. `dry_operating_weight_kg` is the airframe's `basic_empty_weight_kg` plus the flight's `crew_weight_kg`. `dry_operating_index` is obtained by taking the crew index delta — the crew weight multiplied by the difference between `crew_arm_m` and `ref_arm_m`, divided by `index_c`, that quotient rounded half-up to 2 decimals — and adding it to `basic_index`, the sum then rounded half-up to 2 decimals. The rounding of the crew delta happens before the addition, not after.

The second family is the **performance-limited takeoff weight**. The system first selects the single performance band whose `runway_id` matches the flight's `departure_runway_id`, whose `aircraft_type_code` matches the airframe's `type_code`, and whose temperature interval contains `outside_air_temp_c` under the lower-inclusive, upper-exclusive rule of §3.1. When no band matches, the flight cannot be created and the request fails with `ERR_NO_PERFORMANCE_BAND`. Given a band, three adjustments are computed and each is rounded half-up to 2 decimals before anything else happens to it. The altitude penalty is 220 kilograms for every 1000 feet of runway threshold elevation, prorated linearly — the elevation in feet multiplied by 220 and divided by 1000. The temperature penalty is 130 kilograms for each degree Celsius by which the flight's outside air temperature exceeds the band's `temp_lo_c`, and it is 0 when the temperature sits at or below that lower bound rather than becoming a credit. The wind credit is 90 kilograms per knot of headwind, computed from the headwind component with negative values — tailwinds — treated as zero knots, and then capped at 900 kilograms, so the credit saturates once the headwind reaches 10 knots and grows no further. The three rounded adjustments are combined with the band's `base_limit_weight_kg`: subtract the altitude penalty, subtract the temperature penalty, add the wind credit. That bracketed figure is then multiplied by the contamination factor of the reported `runway_condition` — 1.00 for `DRY`, 0.93 for `WET`, 0.85 for `CONTAMINATED` — and only then is the result floored down to the greatest multiple of 10 kilograms that does not exceed it. The evaluation order is pinned and must not be rearranged: adjustments and their rounding first, then the bracket, then the multiplicative factor, then the floor. The result is published as `performance_limited_takeoff_weight_kg`.

The third family is the **allowed payload**. Two intermediate fuel figures are needed: takeoff fuel is ramp fuel less taxi fuel, and landing fuel is takeoff fuel less trip fuel. Five candidate payloads are then evaluated, and none is ever skipped. The performance candidate is the performance-limited takeoff weight less the dry operating weight less takeoff fuel. The maximum-takeoff-weight candidate is the airframe's `max_takeoff_weight_kg` less the dry operating weight less takeoff fuel. The maximum-zero-fuel-weight candidate is `max_zero_fuel_weight_kg` less the dry operating weight, with no fuel term at all. The maximum-landing-weight candidate is `max_landing_weight_kg` less the dry operating weight less landing fuel. The maximum-taxi-weight candidate is `max_taxi_weight_kg` less the dry operating weight less the full ramp fuel. The smallest of those five is rounded half-up to 2 decimals, and `allowed_payload_kg` is that figure or 0, whichever is larger — the published allowed payload is never negative. `limiting_factor` names which limit bound the flight, and it is resolved by walking a fixed precedence order — `PERFORMANCE`, then `MTOW`, then `MZFW`, then `MLW`, then `MAX_TAXI` — and taking the first candidate equal to the minimum. Ties are broken by that order alone and never by row identity, so a flight where the performance and structural takeoff candidates are numerically identical reports `PERFORMANCE`.

Departure conditions are revisable while planning continues. A `LoadController` may revise any subset of `outside_air_temp_c`, `headwind_component_kt`, `runway_condition`, `ramp_fuel_kg`, `taxi_fuel_kg` and `trip_fuel_kg` on an existing flight; every field is optional in that request and omitted fields retain their current values. The revision re-runs band selection, so a temperature moved outside every published band fails with `ERR_NO_PERFORMANCE_BAND` and nothing is written; it re-checks fuel coherence, failing with `ERR_FUEL_FIGURES_INCONSISTENT`; and on success it re-derives the dry operating figures, `performance_limited_takeoff_weight_kg`, `allowed_payload_kg` and `limiting_factor`, and increments the flight's `version` by 1. That version bump is exactly the event that can invalidate a client's `expected_flight_version`.

### 3.3. Building the Distribution: Plans, Cabin Zones and Holds

A load plan is the working document of the distribution. A `LoadController` opens one against a flight by naming the `flight_id` and asserting `expected_flight_version`; the flight must be in `PLANNING` or `LOAD_CONTROLLED`. Three behavioural switches may be supplied and each has a contract default: `gate_bag_policy` is `ABSORB_INTO_UNDERLOAD` unless `DEFER_ALL` is requested, `offload_strategy` is `PRIORITY_FIRST` unless `FEWEST_PIECES` is requested, and `rounding_mode` is `PER_LINE_THEN_SUM` unless `SUM_THEN_ROUND` is requested. The new plan's `revision_no` is 1 when it is the flight's first plan and otherwise one more than the highest `revision_no` already present on that flight, and its `status` is `DRAFT`.

Opening a plan supersedes the flight's earlier work. Every prior plan on the flight whose `status` is `DRAFT`, `COMPUTED`, `RESTRICTED` or `SHEET_ISSUED` transitions to `SUPERSEDED`, provided no sheet on that plan is `ACCEPTED` or `AMENDED`; and every sheet on those plans whose `status` is `ISSUED` or `REJECTED_BY_CAPTAIN` transitions to `SUPERSEDED` alongside them. The flight's own `version` is incremented by 1 as part of the same operation, which means a client that opens two plans in succession must re-read the flight between them or its second `expected_flight_version` will be stale.

Seating is recorded one cabin zone at a time. A passenger distribution line names the `load_plan_id` it belongs to and the `compartment_id` it seats, and the compartment must be a `CABIN_ZONE` on the flight's airframe: a compartment belonging to a different airframe is `ERR_COMPARTMENT_NOT_ON_AIRCRAFT` and a hold used for passengers is `ERR_COMPARTMENT_KIND_MISMATCH`. The mix is given as `male_count`, `female_count`, `child_count` and `infant_count`, each defaulting to 0. Seats are consumed by adults and seated children only — the sum of `male_count`, `female_count` and `child_count` must not exceed the compartment's `seat_capacity`, or the line is refused with `ERR_SEAT_CAPACITY_EXCEEDED` — while `infant_count` is excluded from that sum entirely, because a lap infant occupies no seat. At most one line may exist per plan-and-compartment pair; a second attempt is `ERR_DUPLICATE_KEY`.

Whether the line may also carry `actual_weight_kg` is decided by the flight's weight programme, and the discipline is symmetric in both directions. Under a `STANDARD` programme the field is forbidden and supplying it is `ERR_ACTUAL_WEIGHT_NOT_PERMITTED`; under an `ACTUAL` programme the field is mandatory and omitting it is `ERR_ACTUAL_WEIGHT_REQUIRED`. The line's mass, published as `line_weight_kg`, follows from the same choice. Under `STANDARD`, the mass is the male count multiplied by the programme's `male_kg`, plus the female count multiplied by `female_kg`, plus the child count multiplied by `child_kg`, plus the infant count multiplied by `infant_kg` — so lap infants contribute mass even though they consume no seat. Under `ACTUAL`, the mass is the weighed `actual_weight_kg` taken verbatim, and the four counts contribute no mass at all; they exist only for the seat-capacity check. For an identical passenger mix the two programme kinds therefore yield a different `line_weight_kg`, a different `index_zfw` and a different `mac_zfw_pct`, which is exactly why the programme's `documentation_ref` is part of the audit trail. Alongside the mass, each line publishes `index_delta`: the line weight multiplied by the difference between the compartment's `arm_m` and the airframe's `ref_arm_m`, divided by `index_c`, rounded half-up to 2 decimals. Both figures are set when the line is created and re-evaluated when the plan is computed. A line may be removed from a plan that has not been sheeted; removal deletes the row outright, so a deleted line contributes nothing to any later computation.

Checked bags are allocated one hold at a time. A bag allocation names its `load_plan_id` and `compartment_id` — which must be a `HOLD` on the flight's airframe, under the same two referential errors as a passenger line — and its `bag_count`, defaulting to 0. `bag_weight_kg` is optional: when a weighed total is supplied it is used verbatim, and when it is omitted the allocation's mass is the bag count multiplied by the programme's `checked_bag_kg`. Either way the resolved figure is published as `effective_weight_kg`, and `index_delta` is that effective weight multiplied by the difference between the hold's `arm_m` and `ref_arm_m`, divided by `index_c`, rounded half-up to 2 decimals. As with passenger lines, at most one allocation may exist per plan-and-compartment pair, and a second attempt is `ERR_DUPLICATE_KEY`. Both allocation creation and passenger-line creation and deletion are refused with `ERR_PLAN_INVALID_STATE` when the plan's `status` does not permit the write, and both are refused with `ERR_FLIGHT_INVALID_STATE` when the flight is neither `PLANNING` nor `LOAD_CONTROLLED`.

Two structural ceilings guard every hold. Taken per hold, the allocation's `effective_weight_kg` plus the `weight_kg` of every consignment assigned to that hold in `ACCEPTED` or `LOADED` status must not exceed the hold's `max_weight_kg`, or the write is refused with `ERR_COMPARTMENT_OVERLOAD`. That same combined mass divided by the hold's `length_m` must not exceed `running_load_limit_kg_per_m`, or the write is refused with `ERR_RUNNING_LOAD_EXCEEDED`. Both checks are applied identically on bag-allocation creation, on consignment stowage and on gate-bag presentation.

Adding a passenger line, adding a bag allocation, deleting a passenger line or stowing a consignment against a plan that has already reached `COMPUTED` invalidates that computation. The plan is returned from `COMPUTED` to `DRAFT`, every computed balance field on it is reset to 0 with `envelope_ok` reset to false, and the flight is walked back from `LOAD_CONTROLLED` to `PLANNING`. This reversion is only permitted while no sheet on the plan is `ISSUED`, `ACCEPTED` or `AMENDED`; once a sheet exists in one of those three states the distribution is frozen and the write is refused with `ERR_PLAN_INVALID_STATE`. The `DRAFT` → `COMPUTED` → `DRAFT` loop is the ordinary plan revision cycle and may repeat any number of times.

### 3.4. Consignment Acceptance, Stowage and Compartment Limits

A `RampAgent` books a consignment against a flight by supplying the `flight_id`, an `awb_number` unique within that flight, an `item_kind`, the gross `weight_kg` and the footprint `length_m`, both of which must be strictly greater than 0, and optionally `is_dangerous_goods`, which defaults to false. `item_kind` is one of `GENERAL`, `MAIL`, `COMPANY` or `GATE_BAG`, and it fixes the consignment's `offload_priority_rank` at booking: `COMPANY` takes rank 1, `GENERAL` rank 2, `MAIL` rank 3 and `GATE_BAG` rank 4, where a lower rank is offloaded earlier. Booking is only permitted while the flight is `PLANNING` or `LOAD_CONTROLLED`.

Acceptance is sometimes automatic. A consignment that is neither a gate bag nor flagged as dangerous goods is created directly in `ACCEPTED` status — the system accepts it on the agent's behalf. Everything else is created in `BOOKED` status and must be accepted explicitly. Explicit acceptance requires the consignment to be `BOOKED` and the flight to be `PLANNING` or `LOAD_CONTROLLED`, and for a dangerous-goods consignment it additionally requires a declaration on that consignment already sitting in `ACCEPTED` status; a `BOOKED` consignment may instead be refused, which moves it to `REJECTED` and clears its `assigned_compartment_id`. Attempting either action from a status that does not permit it is `ERR_CARGO_INVALID_STATE`.

Stowage sets `assigned_compartment_id` to the hold the consignment will travel in, and is available to both a `RampAgent` and a `LoadController` while the flight is `PLANNING` or `LOAD_CONTROLLED`. The named hold must belong to the flight's airframe and must be of `kind` `HOLD`, and the two structural ceilings of §3.3 — `ERR_COMPARTMENT_OVERLOAD` and `ERR_RUNNING_LOAD_EXCEEDED` — are re-evaluated against the hold with this consignment included. Stowing a consignment against an already-computed plan returns that plan to `DRAFT` and the flight to `PLANNING`, exactly as adding a passenger line does. Until a consignment is stowed it contributes neither mass nor index to the plan, because both the payload and the balance chain count only stowed consignments; an unstowed consignment is therefore invisible to the arithmetic but still visible to the dangerous-goods completeness check described in §3.5.

The consignment lifecycle has three terminal states — `REJECTED`, `OFFLOADED` and `DEFERRED` — reached by distinct routes. `REJECTED` is reached only from `BOOKED`, by explicit refusal or by rejection of the consignment's dangerous-goods declaration. `OFFLOADED` is reached from `ACCEPTED` when the offload waterfall selects the consignment or when the flight is cancelled, and from `LOADED` only when a `LOAD_CONTROLLED` flight is cancelled; in every case the `assigned_compartment_id` is cleared on the way out. `DEFERRED` is reached from `BOOKED` when a gate bag cannot be absorbed, and from `ACCEPTED` at departure when the consignment was never stowed.

### 3.5. Dangerous Goods: Declaration, Segregation and the Load Release Hold

A `RampAgent` declares dangerous goods against a consignment by naming the `cargo_item_id`, the substance's `un_number`, its `imo_class` — one of `CLASS_1`, `CLASS_2`, `CLASS_3`, `CLASS_5` or `CLASS_8` — its `packing_group`, one of `I`, `II` or `III`, its `segregation_group`, one of `FLAMMABLE`, `OXIDISER`, `CORROSIVE` or `INERT`, and the net `quantity_kg`. Only a consignment whose `is_dangerous_goods` flag is true may be declared, and submitting against an ordinary consignment is refused with `ERR_NOT_DANGEROUS_GOODS`. The declared net quantity must not exceed the parent consignment's gross `weight_kg`, or the submission is refused with `ERR_DG_QUANTITY_EXCEEDS_ITEM`. Submission is permitted while the flight is `PLANNING` or `LOAD_CONTROLLED` and while the parent consignment's status permits it; otherwise `ERR_CARGO_INVALID_STATE` applies. The declaration is created with `status` `SUBMITTED` and `notoc_issued` false.

Submission immediately holds the flight's release. The flight's `dg_hold_count` is recomputed as the number of declarations in `SUBMITTED` status across that flight's cargo, its `load_release_state` moves from `OPEN` to `HELD_FOR_DG`, and its `version` is incremented by 1. A further declaration submitted while a hold is already in force leaves `load_release_state` at `HELD_FOR_DG` — the state re-enters itself — increments `dg_hold_count` by 1 and increments the flight's `version` by 1 again. Throughout, the flight's `status` dimension is untouched: a flight holds its dangerous goods while remaining in `PLANNING` or in `LOAD_CONTROLLED`, whichever it was already in.

A `DangerousGoodsOfficer` resolves each declaration, and only from `SUBMITTED`: acceptance or rejection of a declaration in any other status is `ERR_DECLARATION_INVALID_STATE`. Acceptance additionally requires the parent consignment to be `BOOKED` or `ACCEPTED`, and it must clear the segregation check. Segregation is compartment-scoped and pairwise: accepting a declaration whose `segregation_group` is `FLAMMABLE` is refused when some other consignment sharing the same `assigned_compartment_id` already carries a declaration in `ACCEPTED` status whose `segregation_group` is `OXIDISER`, and symmetrically accepting an `OXIDISER` declaration is refused when a `FLAMMABLE` one is already accepted in that hold. `CORROSIVE` and `INERT` are compatible with every group, including with each other and with themselves. A conflict is reported as `ERR_DG_SEGREGATION_CONFLICT`. On success the declaration moves `SUBMITTED` → `ACCEPTED`, `accepted_by_user_id` is set to the acting `X-User-ID`, the flight's `dg_hold_count` is decremented by 1, and the flight's `version` is incremented by 1.

Rejection is the mirror image and carries a cascade of its own. The declaration moves `SUBMITTED` → `REJECTED`, the parent consignment is walked from `BOOKED` to `REJECTED` with its `assigned_compartment_id` cleared, the flight's `dg_hold_count` is decremented by 1, and the flight's `version` is incremented by 1. In both directions, when the resolution takes `dg_hold_count` to 0 — that is, when the last outstanding declaration on the flight has been resolved either way — the flight's `load_release_state` returns from `HELD_FOR_DG` to `OPEN` and `dg_hold_count` reads 0. That cycle from `OPEN` to `HELD_FOR_DG` and back may repeat as often as the ramp needs it to, right up until the load is released.

Dangerous goods also gate documentation. A load sheet may not be issued while any consignment on the flight with `is_dangerous_goods` true and `status` `BOOKED`, `ACCEPTED` or `LOADED` lacks a declaration in `ACCEPTED` status; the refusal is `ERR_DG_NOT_ACCEPTED`. Note the deliberate breadth of that set: a still-undeclared consignment that has not even been stowed, and therefore contributes nothing to the payload, nonetheless blocks issuance. The completeness rule is about paperwork, not about mass.

### 3.6. Computing the Balance and Resolving Weight Restrictions

Computing a plan is the moment the distribution becomes a set of numbers. A `LoadController` may compute a plan whose `status` is `DRAFT` on a flight whose `status` is `PLANNING`, and every passenger line and bag allocation on that plan must reference a compartment on the flight's airframe. Computation re-evaluates each passenger line's `line_weight_kg` and `index_delta` and each bag allocation's `effective_weight_kg` and `index_delta` before doing anything else, so that a plan is always computed from freshly-derived per-row figures.

The **base payload** is then assembled from three collections and nothing else: every passenger line on the plan, contributing its `line_weight_kg`; every bag allocation on the plan, contributing its `effective_weight_kg`; and every consignment on the plan's flight whose `status` is `ACCEPTED` or `LOADED`, whose `assigned_compartment_id` is set, and whose `item_kind` is not `GATE_BAG`, contributing its `weight_kg`. Consignments in `BOOKED`, `REJECTED`, `OFFLOADED` or `DEFERRED` status are excluded, and every gate bag is excluded regardless of status. The order of summation is irrelevant because each per-row value has already been rounded. The sum is published as `base_payload_kg`, and `frozen_underload_kg` is the flight's `allowed_payload_kg` less that base payload, rounded half-up to 2 decimals. `restriction_status` is `WEIGHT_RESTRICTED` when the frozen underload is strictly negative and `UNRESTRICTED` otherwise.

Two figures shadow those two and behave differently: `planned_payload_kg` is the live payload — the base payload plus the total `weight_kg` of every gate bag on the flight now in `ACCEPTED` or `LOADED` status, less the total `weight_kg` of consignments that counted toward the base payload at compute time and have since moved to `OFFLOADED`, the result rounded half-up to 2 decimals — and `underload_kg` is the flight's `allowed_payload_kg` less that live payload, likewise rounded to 2 decimals. The distinction is deliberate and it is a common source of error: `base_payload_kg`, `frozen_underload_kg` and `restriction_status` are **frozen** at the compute transition and are never re-derived afterwards, while `planned_payload_kg` and `underload_kg` are **live** and move with every gate-bag absorption and every offload. A plan computed `UNRESTRICTED` whose gate bags subsequently drive `underload_kg` down to exactly 0 still reads `restriction_status` `UNRESTRICTED`.

The **balance chain** follows, in four pinned steps. Step one accumulates the zero-fuel index. The raw index contribution of any mass is that mass multiplied by the difference between its arm and `ref_arm_m`, divided by `index_c`. Under `PER_LINE_THEN_SUM` — the contract default — `index_zfw` is the flight's `dry_operating_index` plus the sum, over every passenger line, of that line's raw contribution rounded half-up to 2 decimals, plus the same per-row-rounded sum over every bag allocation, plus the same per-row-rounded sum over every counted consignment at its assigned hold's `arm_m`. Under `SUM_THEN_ROUND`, all of those raw contributions are instead summed at full precision together with `dry_operating_index` and the total is rounded half-up to 2 decimals exactly once. The two modes deliberately produce different values of `index_zfw` for the same distribution — the first retains accumulated per-row rounding, the second does not — and consequently different values of `mac_zfw_pct`. Unassigned consignments contribute no index, for the same reason they contribute no payload.

Step two derives the weights, each rounded half-up to 2 decimals. `zero_fuel_weight_kg` is the flight's `dry_operating_weight_kg` plus the plan's `planned_payload_kg`. Takeoff fuel is again ramp fuel less taxi fuel. `takeoff_weight_kg` is the zero-fuel weight plus takeoff fuel; `taxi_weight_kg` is the zero-fuel weight plus the full ramp fuel; `landing_weight_kg` is the takeoff weight less trip fuel. `index_tow` is the zero-fuel index plus the raw index contribution of the takeoff fuel mass at `fuel_arm_m`, that fuel contribution rounded half-up to 2 decimals first and the resulting sum rounded half-up to 2 decimals again.

Step three converts index back into a percentage of the mean aerodynamic chord, and it does so from index and weight only — never from a stored arm. For a given index and weight, the arm is `ref_arm_m` plus the quantity formed by subtracting `index_k` from the index, multiplying by `index_c` and dividing by the weight. The percent-MAC figure is then that arm less `lemac_m`, divided by `mac_length_m`, multiplied by 100, and rounded half-up to 2 decimals. Applying that conversion to the zero-fuel index at the zero-fuel weight gives `mac_zfw_pct`; applying it to the takeoff index at the takeoff weight gives `mac_tow_pct`.

Step four renders the verdict. The effective aft takeoff bound is `tow_aft_limit_pct_mac`, plus `tow_aft_knee_adjust_pct_mac` when `takeoff_weight_kg` is strictly greater than `tow_knee_weight_kg` and plus nothing otherwise. `envelope_ok` is true only when the zero-fuel percent-MAC figure sits at or above `zfw_fwd_limit_pct_mac` and at or below `zfw_aft_limit_pct_mac`, **and** the takeoff percent-MAC figure sits at or above `tow_fwd_limit_pct_mac` and at or below that effective aft bound. All four bounds are inclusive. A compute, an offload application or a gate-bag absorption that would leave either percent-MAC figure outside its weight-adjusted bound is refused with `ERR_CG_OUT_OF_ENVELOPE` and persists nothing at all.

A successful compute lands the plan in one of two states, and this is the branch point of the whole workflow. When the base payload fits — the frozen underload is 0 or positive — and the envelope verdict is true, the plan moves `DRAFT` → `COMPUTED`, and as the third hop of the same operation the flight moves `PLANNING` → `LOAD_CONTROLLED` with its `version` incremented by 1. When the frozen underload is strictly negative, the plan moves `DRAFT` → `RESTRICTED` instead: `restriction_status` is set to `WEIGHT_RESTRICTED`, the frozen underload records the negative figure, the balance chain is still computed against the un-offloaded distribution, and the flight's `status` is deliberately left at `PLANNING`. In both cases the plan's `version` is incremented by 1. A restricted plan is not a failed plan; it is a plan waiting for an offload decision.

The **offload waterfall** resolves a restriction. The excess to relieve is the negation of the frozen underload, or 0 if the frozen underload is not negative. The candidate set is every consignment on the plan's flight whose `status` is `ACCEPTED`, whose `assigned_compartment_id` is set, and whose `item_kind` is not `GATE_BAG`; consignments in `BOOKED`, `LOADED`, `OFFLOADED`, `DEFERRED` or `REJECTED` status never enter it. Candidates are ordered by the plan's `offload_strategy`. Under `PRIORITY_FIRST` the ordering is `offload_priority_rank` ascending — so `COMPANY` traffic at rank 1 leaves first, then `GENERAL` at rank 2, then `MAIL` at rank 3, then any gate bag at rank 4 — then `weight_kg` descending, then `created_at` ascending; the lowest-value traffic leaves first even when that means handling several pieces. Under `FEWEST_PIECES` the ordering is `weight_kg` descending, then `offload_priority_rank` ascending, then `created_at` ascending; the heaviest single piece leaves first so that as few pieces as possible are handled. For the same excess the two strategies can select different consignments, relieve a different total weight and leave a different `planned_payload_kg` behind.

Selection walks the ordered candidates with a running total that starts at 0. Before each candidate is considered, the running total is compared against the excess: if it already reaches or exceeds the excess, the walk stops. Otherwise the candidate is added to the selection and its `weight_kg` is added to the running total. The relieved weight is the running total when the walk ends, rounded half-up to 2 decimals, and the piece count is the number of selected consignments. If the walk exhausts the candidates while the running total is still strictly below the excess — including the degenerate case of an empty candidate set against a positive excess — the operation fails with `ERR_OFFLOAD_INSUFFICIENT` and nothing is written.

The selection is inspectable before it is committed. A read-only preview available to a `LoadControlAdmin` or a `LoadController` reports the plan's current `strategy`, the `excess_weight_kg` to relieve, the `offloaded_total_kg` the waterfall would relieve, the `offloaded_piece_count` it would touch, and `offloaded_awb_numbers`, the air waybill numbers of the selected consignments in selection order. The preview persists nothing.

Applying the offload commits it, and the cascade has three hops. First, each selected consignment transitions `ACCEPTED` → `OFFLOADED` with its `assigned_compartment_id` cleared and its own `version` incremented by 1. Second, the plan's `planned_payload_kg` and `underload_kg` are refreshed from the surviving distribution and the entire index and percent-MAC chain is recomputed against it — with `frozen_underload_kg` and `restriction_status` left untouched, since those are frozen. Third, the plan moves `RESTRICTED` → `COMPUTED` and the flight moves `PLANNING` → `LOAD_CONTROLLED`. Application requires the plan to be `RESTRICTED`, the flight to be `PLANNING`, the selection to relieve at least the excess, and the post-offload distribution to satisfy the envelope; the plan's `version` is incremented by 1. Because the plan can be driven from `COMPUTED` back to `DRAFT` and recomputed, the `COMPUTED` ↔ `RESTRICTED` cycle may be traversed repeatedly on one plan.

**Gate-checked bags** arrive after the plan is computed and are absorbed or deferred on the spot. A `RampAgent` or a `LoadController` presents one to a computed plan by supplying its `awb_number`, `weight_kg`, `length_m` and the `compartment_id` it would be stowed in; a consignment is created with `item_kind` `GATE_BAG` and `offload_priority_rank` 4. The named compartment must be a `HOLD` on the flight's airframe, and the hold's structural and running-load ceilings are checked with the bag included, yielding `ERR_COMPARTMENT_NOT_ON_AIRCRAFT`, `ERR_COMPARTMENT_KIND_MISMATCH`, `ERR_COMPARTMENT_OVERLOAD` or `ERR_RUNNING_LOAD_EXCEEDED` as applicable. When the plan's `gate_bag_policy` is `ABSORB_INTO_UNDERLOAD` and the bag's `weight_kg` is less than or equal to the plan's live `underload_kg`, the bag is set to `ACCEPTED`, `assigned_compartment_id` is set to the named hold, and both the live payload figures and the whole balance chain are re-run — so an absorbed bag can itself push the centre of gravity out of the envelope and be refused with `ERR_CG_OUT_OF_ENVELOPE`. Otherwise — either because the policy is `DEFER_ALL`, or because the bag is heavier than the live underload — the bag moves `BOOKED` → `DEFERRED` and the plan's `deferred_bag_weight_kg` increases by the bag's `weight_kg`. In both branches the plan's `restriction_status` and `frozen_underload_kg` are explicitly not re-derived, and the plan's `version` is incremented by 1.

### 3.7. Load Sheet Issuance, Captain Acceptance and Departure

Issuing a load sheet turns the plan into a document a commander can sign. A `LoadController` issues one against a plan whose `status` is `COMPUTED` and whose `envelope_ok` is true, naming the `load_plan_id` and asserting `expected_load_plan_version`; every dangerous-goods consignment on the flight must already hold an `ACCEPTED` declaration or issuance fails with `ERR_DG_NOT_ACCEPTED`. The sheet's `sheet_no` is 1 for the plan's first sheet and otherwise one more than the highest `sheet_no` already on that plan, and its `status` is `ISSUED`.

Issuance snapshots. `issued_by_user_id` records the issuing `X-User-ID`. `issued_takeoff_weight_kg`, `issued_index_tow` and `issued_payload_kg` capture the plan's `takeoff_weight_kg`, `index_tow` and `planned_payload_kg` as they stand at that instant, and `weight_program_documentation_ref` captures the flight's weight programme's `documentation_ref` for the audit trail. `notoc_reference` is populated with the notification-to-captain reference when — and only when — the flight carries at least one declaration in `ACCEPTED` status; a flight with no dangerous goods leaves it absent. The four final figures `final_takeoff_weight_kg`, `final_index_tow`, `final_mac_tow_pct` and `final_payload_kg` are seeded from the issued snapshots, so a sheet with no last-minute changes reads final figures identical to its issued ones. Issuance also computes the sheet's `lmc_allowance_kg`: the smaller of a hard cap of 500 kilograms and the plan's live `underload_kg`, with a negative underload treated as 0 — so a plan with 320 kilograms of spare capacity grants a 320-kilogram allowance, a plan with 4 tonnes of spare capacity grants the 500-kilogram cap, and a plan with no spare capacity grants none. Every prior sheet on the plan whose `status` is `ISSUED` or `REJECTED_BY_CAPTAIN` transitions to `SUPERSEDED`, the plan moves `COMPUTED` → `SHEET_ISSUED`, and the plan's `version` is incremented by 1 — which means a controller reissuing a sheet must re-read the plan first, or its second `expected_load_plan_version` will be stale.

The commander's decision branches, and the two arms are genuinely asymmetric. Both arms require the sheet to be `ISSUED` and both enforce the segregation-of-duties rule: the acting `Captain`'s `X-User-ID` must differ from the sheet's `issued_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`. Acceptance additionally requires the flight's `dg_hold_count` to be 0, and a hold still in force is reported as `ERR_LOAD_NOT_RELEASED`.

Acceptance cascades in three hops. The sheet moves `ISSUED` → `ACCEPTED` with `accepted_by_user_id` set to the acting `X-User-ID` and its `version` incremented by 1. The flight's `load_release_state` moves `OPEN` → `RELEASED` and the flight's `version` is incremented by 1. Then every consignment on the flight in `ACCEPTED` status with an `assigned_compartment_id` set transitions to `LOADED` with its own `version` incremented by 1, and for each of those consignments every declaration in `ACCEPTED` status has `notoc_issued` set to true — the paperwork record that the commander was notified of the dangerous goods aboard. Consignments left unstowed are untouched by acceptance and remain `ACCEPTED`.

Rejection cascades differently and touches no cargo at all. The sheet moves `ISSUED` → `REJECTED_BY_CAPTAIN` with its `version` incremented by 1, the parent plan is walked back `SHEET_ISSUED` → `COMPUTED` with its own `version` incremented by 1 so a corrected sheet can be issued, the flight's `load_release_state` is left exactly where it was at `OPEN`, and no consignment changes status. That is the second arm of the plan revision cycle, and it is why a plan can pass through `SHEET_ISSUED` more than once. When the corrected sheet is issued, the rejected sheet moves `REJECTED_BY_CAPTAIN` → `SUPERSEDED` and the new sheet takes the superseded sheet's `sheet_no` plus 1.

Departure is recorded by a `LoadController` and requires both flight dimensions to agree: `status` must be `LOAD_CONTROLLED`, reported as `ERR_FLIGHT_INVALID_STATE` when it is not, and `load_release_state` must be `RELEASED`, reported as `ERR_LOAD_NOT_RELEASED` when it is not. The flight moves `LOAD_CONTROLLED` → `DEPARTED` with its `version` incremented by 1, and as a side effect every consignment on the flight still in `ACCEPTED` status with no `assigned_compartment_id` transitions to `DEFERRED` — cargo that was accepted for carriage but never physically stowed rolls to a later flight rather than departing in limbo.

Cancellation is the alternative ending, available to a `LoadControlAdmin`. From `PLANNING`, cancellation moves the flight to `CANCELLED`, transitions every plan on it whose `status` is `DRAFT`, `COMPUTED` or `RESTRICTED` to `SUPERSEDED`, transitions every consignment whose `status` is `BOOKED` or `ACCEPTED` to `OFFLOADED`, and increments the flight's `version` by 1. From `LOAD_CONTROLLED`, cancellation is permitted only while no sheet on any plan of the flight is `ACCEPTED`; it then transitions every plan whose `status` is `DRAFT`, `COMPUTED`, `RESTRICTED` or `SHEET_ISSUED` to `SUPERSEDED`, transitions every sheet on those plans whose `status` is `ISSUED` or `REJECTED_BY_CAPTAIN` to `SUPERSEDED`, transitions every consignment whose `status` is `BOOKED`, `ACCEPTED` or `LOADED` to `OFFLOADED` with `assigned_compartment_id` cleared, and increments the flight's `version` by 1. `PLANNING` and `LOAD_CONTROLLED` are the only two states cancellation may be invoked from.

### 3.8. Last-Minute Changes and Post-Departure Amendment

Between issuance and closure the load is still allowed to move, but only within the allowance the sheet granted. A `LoadController` records a change against a sheet whose `status` is `ISSUED` or `ACCEPTED` — any other status is `ERR_SHEET_INVALID_STATE` — by naming the `load_sheet_id`, the `change_kind`, the `compartment_id` where the mass moves, and, according to the kind, either the counts `male_count` and `female_count` or the absolute `mass_kg`. All three of those quantity fields are optional and default to 0. `change_kind` is one of `PAX_ADD`, `PAX_REMOVE`, `BAG_ADD`, `BAG_REMOVE` or `CARGO_OFFLOAD`. A passenger change must name a `CABIN_ZONE` compartment on the flight's airframe and a bag or cargo change must name a `HOLD`, under `ERR_COMPARTMENT_KIND_MISMATCH` and `ERR_COMPARTMENT_NOT_ON_AIRCRAFT` respectively. A new change is created with `status` `APPLIED`.

The signed weight of a change follows from its kind. For `PAX_ADD` the signed mass is positive and equals the male count multiplied by the flight's weight programme's `male_kg` plus the female count multiplied by `female_kg`; for `PAX_REMOVE` it is the negation of that same figure. For `BAG_ADD` the signed mass is the positive `mass_kg`; for `BAG_REMOVE` and for `CARGO_OFFLOAD` it is the negation of `mass_kg`. Passenger changes ignore `mass_kg` and bag or cargo changes ignore the two counts. The signed figure is rounded half-up to 2 decimals and published as `weight_delta_kg`, and the change's `index_delta` is that signed weight multiplied by the difference between the named compartment's `arm_m` and the airframe's `ref_arm_m`, divided by `index_c`, rounded half-up to 2 decimals — so a removal at a forward zone and an addition at an aft zone both push the centre of gravity aft.

The sheet keeps two running totals over its changes in `APPLIED` status, accumulated in `created_at` ascending order; changes in `REVERSED` status contribute 0 to both. `lmc_net_weight_delta_kg` is the sum of the signed weight deltas, rounded half-up to 2 decimals. `lmc_absolute_weight_delta_kg` is the sum of the absolute values of those same deltas, likewise rounded. The allowance binds the absolute total, not the net one, which is the whole point: a 200-kilogram addition followed by a 200-kilogram removal nets to nothing but consumes 400 kilograms of allowance. Admission of a new change is tested *before* it is persisted — the sheet's current absolute total plus the absolute value of the new change's `weight_delta_kg` must be less than or equal to `lmc_allowance_kg`, and a violation is refused with `ERR_LMC_ALLOWANCE_EXCEEDED` with nothing written.

Whenever the running totals move, four final figures on the sheet are refreshed. `final_takeoff_weight_kg` is the `issued_takeoff_weight_kg` snapshot plus `lmc_net_weight_delta_kg`. `final_index_tow` is the `issued_index_tow` snapshot plus the signed sum of the `index_delta` values of the applied changes. `final_mac_tow_pct` is the takeoff percent-MAC figure recomputed from `final_takeoff_weight_kg` and `final_index_tow` by the same index-to-percent-MAC conversion described in §3.6. `final_payload_kg` is the `issued_payload_kg` snapshot plus `lmc_net_weight_delta_kg`. The sheet's `version` is incremented by 1 each time.

A change may be reversed by a `LoadController` while it is `APPLIED` and while its parent sheet is `ISSUED` or `ACCEPTED`. Reversal moves the change to `REVERSED` and increments its `version` by 1; the sheet's two running totals are then recomputed from scratch over the remaining `APPLIED` rows in `created_at` ascending order, and all four final figures are recomputed from them. Because the absolute total is recomputed rather than merely decremented, reversing a change returns both the sheet's index position and its allowance consumption to where they stood before the change was recorded, freeing that allowance for a different adjustment.

After the aircraft is off blocks the sheet is amended once to freeze the record. Amendment requires the sheet's `status` to be `ACCEPTED` and the flight's `status` to be `DEPARTED`; it moves the sheet `ACCEPTED` → `AMENDED`, recomputes `final_takeoff_weight_kg`, `final_index_tow`, `final_mac_tow_pct` and `final_payload_kg` from the applied changes one final time, and increments the sheet's `version` by 1. `AMENDED` is terminal, as is `SUPERSEDED`. Both a sheet that carried a dozen last-minute changes and a sheet that carried none converge on `AMENDED`, and in the latter case the final figures simply equal the issued snapshots.

### 3.9. Load Audit, Discrepancy Investigation and Flight Closure

Once a flight's load is under control, an `AuditInspector` may compare weighed actuals against the documented figures. Opening an audit is permitted while the flight's `status` is `LOAD_CONTROLLED`, `DEPARTED` or `CLOSED`, and requires the `flight_id`, the `basis` to compare against, and the three weighed totals `actual_pax_weight_kg`, `actual_bag_weight_kg` and `actual_cargo_weight_kg`. The audit is created with `status` `OPEN`.

The documented figures come from a single plan: the plan on that flight whose `status` is `SHEET_ISSUED` or `COMPUTED` and whose `revision_no` is highest, a choice that is never ambiguous because `revision_no` is unique per flight. The documented passenger figure is the sum of `line_weight_kg` over that plan's passenger lines; the documented bag figure is the sum of `effective_weight_kg` over its bag allocations; the documented cargo figure is the sum of `weight_kg` over the flight's consignments in `LOADED` status.

`basis` selects between two comparison bases, and the choice materially changes the outcome. Under `DOCUMENTED_BASIS` the three basis figures are exactly the documented figures above, ignoring every applied last-minute change — this asks "how good was the plan?". Under `FINAL_BASIS` each documented figure is adjusted by the last-minute changes of the matching class recorded on the accepted sheet: the passenger basis is the documented passenger figure plus the sum of `weight_delta_kg` over `APPLIED` changes whose `change_kind` is `PAX_ADD` or `PAX_REMOVE`; the bag basis is the documented bag figure plus the same sum restricted to `BAG_ADD` and `BAG_REMOVE`; the cargo basis is the documented cargo figure plus the same sum restricted to `CARGO_OFFLOAD`. This asks "how good was the final load sheet?". A `FINAL_BASIS` audit therefore needs a sheet in `ACCEPTED` or `AMENDED` status on that highest-revision plan, and is refused with `ERR_NO_ACCEPTED_SHEET` when none exists; `DOCUMENTED_BASIS` may be requested from any of the three permitted flight states without such a sheet. For identical weighed actuals the two bases produce different deltas and can land in different severity bands.

Each delta is the weighed actual less the corresponding basis figure, rounded half-up to 2 decimals: `pax_delta_kg`, `bag_delta_kg` and `cargo_delta_kg`, all signed, so an under-declared load reads positive and an over-declared one negative. `total_absolute_discrepancy_kg` is the sum of the absolute values of those three deltas, rounded half-up to 2 decimals — offsetting errors do not cancel. `severity` follows from that total against two thresholds, half a tonne and one tonne, with both band boundaries inclusive at their upper end: `NONE` when the total is exactly 0, `MINOR` when it is strictly above 0 and at most 500 kilograms, `MAJOR` when it is strictly above 500 kilograms and at most 1000 kilograms, and `CRITICAL` when it is strictly above 1000 kilograms. A total of exactly 500.00 is therefore `MINOR` while 500.01 is `MAJOR`, and 1000.00 is `MAJOR` while 1000.01 is `CRITICAL`.

Severity decides the route to closure. An audit whose `severity` is `MAJOR` or `CRITICAL` may be moved from `OPEN` to `INVESTIGATING`, and only from there to `CLOSED`; attempting to open an investigation on an audit whose `severity` is `NONE` or `MINOR` is refused with `ERR_AUDIT_INVALID_STATE`, as is attempting it on an audit that is not `OPEN`. An audit whose `severity` is `NONE` or `MINOR` closes directly from `OPEN` without an investigation stage. Either way, closure requires a non-empty `finding_note` recording the investigator's narrative — an empty or absent note is `ERR_FINDING_NOTE_REQUIRED` — and closure sets `closed_by_user_id` to the acting `X-User-ID` and increments the audit's `version` by 1. `CLOSED` is terminal.

Closure also enforces the second segregation-of-duties rule, and it reaches across entities to do so. The `X-User-ID` closing an audit must differ from every `accepted_by_user_id` recorded on any dangerous-goods declaration on that flight's cargo; if the closing inspector is the same operator who accepted any of those declarations, closure is refused with `ERR_AUDIT_SEGREGATION_CONFLICT`. Note that the comparison covers all such declarations on the flight, not merely those on consignments that ended up loaded.

The flight's own ending is the last step. A `LoadControlAdmin` closes a `DEPARTED` flight, moving `status` `DEPARTED` → `CLOSED` and incrementing the flight's `version` by 1, and may do so only once every load audit on that flight has `status` `CLOSED` — a flight with an outstanding `OPEN` or `INVESTIGATING` audit cannot be closed, while a flight with no audits at all satisfies the condition trivially. `CLOSED` and `CANCELLED` are the two terminal states of the flight planning lifecycle, and no operation moves a flight out of either.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — an airframe, a compartment, a runway, a performance band, a weight programme, a flight, a load plan, a passenger distribution line, a bag allocation, a consignment, a gate bag, a dangerous-goods declaration, a load sheet, a last-minute change or a load audit — return `201 Created`. Operations that modify an existing resource, including every state transition and every reference-data posture change, return `200 OK`. Deleting a passenger distribution line returns `204 No Content` with no body. In the table below, "Any" means all six roles: `LoadControlAdmin`, `LoadController`, `RampAgent`, `DangerousGoodsOfficer`, `Captain` and `AuditInspector`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/aircraft` | Register an airframe with its structural limits, index constants and CG envelope | LoadControlAdmin |
| GET | `/aircraft/{id}` | Read one airframe | Any |
| GET | `/aircraft` | List airframes | Any |
| POST | `/aircraft/{id}/ground` | Ground an airframe so it can no longer be assigned to new flights | LoadControlAdmin |
| POST | `/compartments` | Declare a cabin zone or hold on an airframe | LoadControlAdmin |
| GET | `/compartments/{id}` | Read one compartment | Any |
| GET | `/aircraft/{id}/compartments` | List the compartments of one airframe | Any |
| POST | `/runways` | Register a departure runway with its elevation and slot capacity | LoadControlAdmin |
| GET | `/runways/{id}` | Read one runway | Any |
| POST | `/runways/{id}/close` | Close a runway so it can no longer be selected for new flights | LoadControlAdmin |
| POST | `/performance-bands` | Publish a temperature band and its sea-level performance limit weight for one runway and aircraft type | LoadControlAdmin |
| GET | `/performance-bands/{id}` | Read one performance band | Any |
| GET | `/runways/{id}/performance-bands` | List the performance bands of one runway | Any |
| POST | `/weight-programs` | Publish a standard or actual passenger weight program with its regulatory documentation reference | LoadControlAdmin |
| GET | `/weight-programs/{id}` | Read one weight program | Any |
| POST | `/weight-programs/{id}/withdraw` | Withdraw a weight program so it can no longer be attached to new flights | LoadControlAdmin |
| POST | `/flights` | Create a flight, select its performance band and derive its dry operating figures and allowed payload | LoadController, LoadControlAdmin |
| GET | `/flights/{id}` | Read one flight with its derived weight limits | Any |
| GET | `/flights` | List flights filtered by airframe, runway, weight program or status | Any |
| PATCH | `/flights/{id}/conditions` | Revise the departure conditions or fuel figures of a flight and re-derive its weight limits | LoadController |
| POST | `/flights/{id}/depart` | Record off-block departure of a load-controlled, released flight | LoadController |
| POST | `/flights/{id}/close` | Close a departed flight once every load audit on it is closed | LoadControlAdmin |
| POST | `/flights/{id}/cancel` | Cancel a flight, superseding its plans and sheets and offloading its cargo | LoadControlAdmin |
| POST | `/load-plans` | Open a load plan on a flight; supersedes the flight's prior non-terminal plan | LoadController |
| GET | `/load-plans/{id}` | Read one load plan with its balance chain | Any |
| GET | `/flights/{id}/load-plans` | List the load plans of one flight | Any |
| POST | `/load-plans/{id}/compute` | Compute the plan: payload, underload, index chain, %MAC at zero-fuel and takeoff weight, and the envelope verdict | LoadController |
| POST | `/load-plans/{id}/apply-offload` | Apply the plan's offload strategy to relieve the weight restriction and recompute the balance chain | LoadController |
| GET | `/load-plans/{id}/offload-preview` | Read-only preview of the offload selection for the plan's current strategy; persists nothing | LoadControlAdmin, LoadController |
| POST | `/load-plans/{id}/gate-bags` | Present a gate-checked bag to a computed plan; it is absorbed into the live underload or deferred | RampAgent, LoadController |
| POST | `/pax-lines` | Seat a passenger mix in one cabin zone of a load plan | LoadController |
| GET | `/pax-lines/{id}` | Read one passenger distribution line | Any |
| GET | `/pax-lines` | List passenger distribution lines by plan or compartment | Any |
| DELETE | `/pax-lines/{id}` | Remove a passenger distribution line from a plan that has not been sheeted | LoadController |
| POST | `/bag-allocations` | Allocate checked bags to one hold of a load plan | LoadController, RampAgent |
| GET | `/bag-allocations/{id}` | Read one bag allocation | Any |
| GET | `/bag-allocations` | List bag allocations by plan or compartment | Any |
| POST | `/cargo-items` | Book a consignment onto a flight; non-dangerous, non-gate-bag consignments are auto-accepted | RampAgent |
| GET | `/cargo-items/{id}` | Read one consignment | Any |
| GET | `/cargo-items` | List consignments by flight, compartment, status or kind | Any |
| POST | `/cargo-items/{id}/assign` | Stow a consignment in a hold, subject to the compartment weight and running-load limits | RampAgent, LoadController |
| POST | `/cargo-items/{id}/accept` | Accept a booked consignment for carriage; dangerous goods require an accepted declaration first | RampAgent |
| POST | `/cargo-items/{id}/reject` | Refuse a booked consignment | RampAgent |
| POST | `/hazmat-declarations` | Declare dangerous goods on a consignment; places the flight's load release on hold | RampAgent |
| GET | `/hazmat-declarations/{id}` | Read one dangerous-goods declaration | Any |
| GET | `/cargo-items/{id}/hazmat-declarations` | List the declarations of one consignment | Any |
| POST | `/hazmat-declarations/{id}/accept` | Accept a dangerous-goods declaration after the segregation check | DangerousGoodsOfficer |
| POST | `/hazmat-declarations/{id}/reject` | Reject a dangerous-goods declaration and refuse its consignment | DangerousGoodsOfficer |
| POST | `/load-sheets` | Issue a load sheet snapshotting the plan's balance figures and the weight-program documentation | LoadController |
| GET | `/load-sheets/{id}` | Read one load sheet with its issued and final figures | Any |
| GET | `/load-plans/{id}/load-sheets` | List the load sheets of one plan | Any |
| POST | `/load-sheets/{id}/accept` | Captain acceptance of the load sheet; releases the load and loads the stowed cargo | Captain |
| POST | `/load-sheets/{id}/reject` | Captain rejection of the load sheet; reopens the plan for correction | Captain |
| POST | `/load-sheets/{id}/amend` | Post-departure amendment: freeze the sheet's final figures from the applied last-minute changes | LoadController |
| POST | `/last-minute-changes` | Record a last-minute change against an issued or accepted load sheet, within its allowance | LoadController |
| GET | `/last-minute-changes/{id}` | Read one last-minute change | Any |
| GET | `/last-minute-changes` | List last-minute changes by sheet or compartment | Any |
| POST | `/last-minute-changes/{id}/reverse` | Reverse an applied last-minute change, returning both the sheet's index and its allowance consumption to their prior values | LoadController |
| POST | `/load-audits` | Open a load audit on a flight, comparing weighed actuals against the chosen basis | AuditInspector |
| GET | `/load-audits/{id}` | Read one load audit | Any |
| GET | `/flights/{id}/load-audits` | List the load audits of one flight | Any |
| POST | `/load-audits/{id}/investigate` | Open an investigation on a major or critical discrepancy | AuditInspector |
| POST | `/load-audits/{id}/close` | Close a load audit with a finding note, subject to the audit segregation-of-duties rule | AuditInspector |
| POST | `/_clock/set_current_utc` | Position the server's logical clock | LoadControlAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_AIRCRAFT_NOT_FOUND` | 404 Not Found |
| `ERR_COMPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RUNWAY_NOT_FOUND` | 404 Not Found |
| `ERR_PERFORMANCE_BAND_NOT_FOUND` | 404 Not Found |
| `ERR_WEIGHT_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PAX_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_BAG_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_CARGO_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_DECLARATION_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_SHEET_NOT_FOUND` | 404 Not Found |
| `ERR_LAST_MINUTE_CHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_AIRCRAFT_GROUNDED` | 409 Conflict |
| `ERR_RUNWAY_CLOSED` | 409 Conflict |
| `ERR_WEIGHT_PROGRAM_WITHDRAWN` | 409 Conflict |
| `ERR_FLIGHT_INVALID_STATE` | 409 Conflict |
| `ERR_LOAD_NOT_RELEASED` | 409 Conflict |
| `ERR_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_SHEET_INVALID_STATE` | 409 Conflict |
| `ERR_CARGO_INVALID_STATE` | 409 Conflict |
| `ERR_DECLARATION_INVALID_STATE` | 409 Conflict |
| `ERR_AUDIT_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_FLIGHT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOAD_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_COMPARTMENT_NOT_ON_AIRCRAFT` | 422 Unprocessable Entity |
| `ERR_COMPARTMENT_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ACTUAL_WEIGHT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ACTUAL_WEIGHT_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_NO_PERFORMANCE_BAND` | 422 Unprocessable Entity |
| `ERR_NO_ACCEPTED_SHEET` | 409 Conflict |
| `ERR_NOT_DANGEROUS_GOODS` | 409 Conflict |
| `ERR_DG_QUANTITY_EXCEEDS_ITEM` | 422 Unprocessable Entity |
| `ERR_DG_SEGREGATION_CONFLICT` | 409 Conflict |
| `ERR_DG_NOT_ACCEPTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_AUDIT_SEGREGATION_CONFLICT` | 409 Conflict |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COMPARTMENT_OVERLOAD` | 422 Unprocessable Entity |
| `ERR_RUNNING_LOAD_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CG_OUT_OF_ENVELOPE` | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_AIRCRAFT_OCCUPANCY_CONFLICT` | 409 Conflict |
| `ERR_RUNWAY_SLOT_FULL` | 409 Conflict |
| `ERR_FUEL_FIGURES_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_OFFLOAD_INSUFFICIENT` | 409 Conflict |
| `ERR_LMC_ALLOWANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FINDING_NOTE_REQUIRED` | 422 Unprocessable Entity |

# Air Cargo ULD Management API — Product Requirements Document

## 1. Introduction

An air cargo handler's warehouse floor runs on tight coupling between three scarce resources: payload weight, cargo volume, and Unit Load Device (ULD) positions on each departing flight. Forwarders tender shipments against those resources, ramp crews build them into containers, and regulators layer dangerous-goods documentation and customs control on top. When any of these moving parts is tracked in spreadsheets or disconnected tools, the failure modes are expensive: flights depart over weight, ULDs sit unbilled at outstations, temperature-sensitive freight spoils without a defensible audit trail, and claims are settled against whatever number someone wrote down last.

This document specifies an API that manages that entire operating cycle under a single resource hierarchy mounted under `/cargo`. It covers flight capacity pools and booking acceptance, build-up planning and ULD assignment, dangerous-goods acceptance under segregation of duties, customs hold coordination, weight-restriction offloads, temperature monitoring, demurrage and repair charging, and damage or loss claims. Throughout, the design favors explicit state machines, deterministic charging rules, and optimistic concurrency on shared resources, so that two control desks acting on the same flight can never silently overwrite one another's decisions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting operator and `X-User-Role` to declare the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly six roles, spelled precisely as follows: `CapacityController`, `ForwarderAgent`, `RampOperator`, `DGInspector`, `CustomsOfficer`, and `ClaimsAdjuster`. Each endpoint declares the roles permitted to call it (see §4); a request whose `X-User-Role` is not among an endpoint's declared roles is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all six roles — `CapacityController`, `ForwarderAgent`, `RampOperator`, `DGInspector`, `CustomsOfficer`, and `ClaimsAdjuster` — `X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity. The server records it in well-defined places and compares it against those recorded values for ownership and segregation-of-duties decisions, but it never corresponds to any entity's own `id`. Concretely: when a `ForwarderAgent` creates a booking, the acting `X-User-ID` is stored as the booking's `created_by_user_id`, and later ownership checks compare a request's `X-User-ID` against that stored field; when a `DGInspector` accepts or rejects a dangerous-goods declaration, the acting `X-User-ID` is stored as the declaration's `checked_by_user_id`. `CapacityController`, `RampOperator`, `CustomsOfficer`, and `ClaimsAdjuster` identifiers are never persisted on any entity.

The roles' business mandates are: a `CapacityController` manages flights, accepts, rejects and rebooks bookings, and imposes weight restrictions; a `ForwarderAgent` creates and cancels their own bookings and files dangerous-goods declarations and claims against them; a `RampOperator` administers ULD types and units, builds and seals plans, logs temperatures, and processes ULD returns, damage, and repairs; a `DGInspector` accepts or rejects dangerous-goods declarations and may never check a booking they themselves created; a `CustomsOfficer` places and releases customs holds; and a `ClaimsAdjuster` approves, rejects, and settles claims.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. Several list endpoints additionally accept filters named in §4 and in the relevant workflow narratives — a `status` filter on flight, booking, build-up plan, ULD, and charge lists, a `uld_type_id` filter on the ULD list, and a `charge_type` filter on the charge list.

### 2.4. Common Resource Properties

Every primary resource — Flight, Booking, ULD, BuildUpPlan, DGDeclaration, CustomsHold, Claim, and ULDCharge — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

Any mutation of a resource — including system-driven changes to computed fields such as a flight's allocation totals or a plan's carried weight — refreshes that resource's `updated_at` and increments its `version`. Two resource kinds are deliberately lighter-weight: a ULDType and a TemperatureLog each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, since neither is ever modified after creation.

### 2.5. The Logical Clock

All timestamps the server records are read from a single logical clock, never from wall-clock time. Before any client has set it, the logical clock reads exactly `2026-08-01T00:00:00Z` — this is the server startup default, and the server never falls back to wall-clock time behind it. Every system-stamped instant flows from this clock: `created_at` and `updated_at` on all resources, a customs hold's `placed_at` and `released_at`, and a ULD's `dispatched_at` and `returned_at`.

An administrative, test-driving capability advances the logical clock: any authenticated role may set it by supplying a `to_iso8601` instant, and the response body reports the resulting time as `current_utc`. All subsequent system timestamps use the advanced clock.

### 2.6. Flight Capacity Accounting

Each Flight maintains three live capacity counters that the server derives from its dependent resources, plus an optional operating restriction:

- `allocated_weight_kg` is the sum of `gross_weight_kg` over the flight's bookings whose status is `ACCEPTED` or `BUILT_UP`, and nothing else — bookings in `REQUESTED`, `OFFLOADED`, `REJECTED`, `CANCELLED`, or `LOADED` status are excluded from the sum.
- `allocated_volume_m3` is the sum of `volume_m3` over exactly the same booking set.
- `reserved_positions` counts the flight's build-up plans whose status is `DRAFT` or `SEALED` — one ULD position per open plan.
- `weight_restriction_kg` records an active restricted payload imposed on the flight; it is `null` when no restriction is in force.

All three counters start at zero when a flight is registered, and each subsequent debit or release is applied immediately, within the same request that caused it — there is no eventual consistency window. Because the position pool is consumed by plan creation, a new build-up plan may only be created while `reserved_positions` is strictly less than the flight's `uld_position_count`; a flight with every position spoken for rejects the plan with `ERR_ULD_POSITION_UNAVAILABLE` (HTTP 422).

### 2.7. Request Validation and Precedence

Every request passes through an ordered ladder of validation rungs. A failure at any rung stops evaluation immediately and produces that rung's error, so an earlier failure always masks later ones. The ladder is:

1. **Header presence.** `X-User-ID` and `X-User-Role` must both be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The declared role must be among the endpoint's authorized roles, else `ERR_FORBIDDEN` (HTTP 403).
3. **Resource existence.** Resource identifiers in the path must exist and are validated left to right — a request naming a non-existent booking id and a non-existent declaration id fails on the booking first — and identifiers referenced in the request body (`flight_id`, `uld_type_id`, `uld_id`, `booking_id`) must likewise exist. Any miss yields `ERR_NOT_FOUND` (HTTP 404).
4. **Request shape.** Required fields must be present, types must be valid, and enum fields must be within their declared values; `pieces` must be at least 1; `gross_weight_kg` and `volume_m3` must each be greater than 0; `claimed_amount` must be greater than 0; a claim's `items` list must be non-empty with each entry's `weight_kg` greater than 0; a temperature range must set both of `temp_min_c` and `temp_max_c` or neither, with `temp_min_c` less than or equal to `temp_max_c`; `build_end` must be strictly later than `build_start`; and `restricted_payload_kg` must be greater than 0 and no more than the flight's `max_payload_kg`. Any violation yields `ERR_INVALID_REQUEST` (HTTP 400).
5. **Attribute authorization.** A `ForwarderAgent` may cancel a booking, file a declaration, or file a claim only on a booking whose `created_by_user_id` equals the request's `X-User-ID` (`ERR_BOOKING_NOT_OWNED`, HTTP 403); and a dangerous-goods check must be performed by someone other than the booking's creator (`ERR_SOD_VIOLATION`, HTTP 403).
6. **State preconditions.** Every state-transition operation verifies its target resources are in the required states, and the two version-guarded writes verify the supplied expected version against the parent's current `version` (see §2.8). This rung also enforces the two singleton guards: at most one `ACTIVE` customs hold per booking (`ERR_HOLD_ALREADY_ACTIVE`) and at most one `PENDING_CHECK` declaration per booking (`ERR_DG_CHECK_ALREADY_PENDING`). State failures carry HTTP 409, except the two stale-version errors, which carry HTTP 412.
7. **Dangerous-goods embargo.** A dangerous-goods booking may only be accepted or rebooked onto a `dg_certified` flight (`ERR_FLIGHT_NOT_DG_CERTIFIED`).
8. **Customs gate.** No customs hold with status `ACTIVE` may exist on a booking being built into a plan (`ERR_CUSTOMS_HOLD_ACTIVE`).
9. **Dangerous-goods documentation gate.** A dangerous-goods booking requires an `ACCEPTED` declaration before build-up (`ERR_DG_NOT_ACCEPTED`).
10. **Referential coherence.** The booking's flight must equal the plan's flight on assignment (`ERR_BOOKING_FLIGHT_MISMATCH`); a declaration may only be filed on a dangerous-goods booking (`ERR_DG_NOT_APPLICABLE`); a temperature reading may only be recorded on a booking with a defined range (`ERR_TEMP_RANGE_NOT_DEFINED`). These carry HTTP 422.
11. **Scheduling and uniqueness constraints.** Build windows on the same flight must respect the 30-minute separation buffer (`ERR_BUILD_WINDOW_CONFLICT`), and ULD type codes and serial codes must be unique (`ERR_DUPLICATE_ULD_CODE`). These carry HTTP 409.
12. **ULD capacity.** A plan's projected gross must fit within its ULD type's maximum (`ERR_ULD_PAYLOAD_EXCEEDED`), and a free ULD position must exist at plan creation (`ERR_ULD_POSITION_UNAVAILABLE`). These carry HTTP 422.
13. **Flight payload capacity.** Acceptance or rebooking must not push allocated weight strictly above `max_payload_kg` (`ERR_FLIGHT_PAYLOAD_EXCEEDED`, HTTP 422).
14. **Flight volume capacity.** Acceptance or rebooking must not push allocated volume strictly above `max_volume_m3` (`ERR_FLIGHT_VOLUME_EXCEEDED`, HTTP 422).

The rung ordering matters in practice: because the state rung precedes the business-safety rungs, an assignment attempt against a sealed plan surfaces `ERR_PLAN_NOT_DRAFT` rather than a customs or documentation error, and because attribute authorization precedes state checks, an ownership failure surfaces before any state complaint.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on their parent resource, and only these two take a version field:

- **Creating a build-up plan** requires the request to carry `expected_flight_version`, holding the client's last-observed `version` of the target Flight. If the flight's current `version` no longer matches — because allocations, restrictions, or reservations have moved it on since the client last read it — the create is rejected with `ERR_STALE_FLIGHT_VERSION` (HTTP 412), preventing the client from reserving a position against a capacity posture it has not observed.
- **Assigning a booking to a plan** requires the request to carry `expected_build_up_plan_version`, holding the client's last-observed `version` of the target BuildUpPlan. If the plan's current `version` has advanced since that observation — meaning its composition, and therefore its `total_weight_kg`, has changed — the assignment is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), so the client's payload calculation is never applied to a plan it has not seen.

Endpoints not named above do not take a version field.

### 2.9. Numeric Precision and Rounding

All monetary and weight figures produced by the server's calculations — chargeable weights, demurrage and repair charge amounts, and claim settlement figures — are stored and returned at exactly 2 decimal places, rounded half up. Pure threshold comparisons (flight capacity, ULD payload, temperature range) are performed on the raw 2-decimal inputs without any additional rounding. All such values are represented in API responses as standard JSON numbers, not strings.

## 3. Business Logic & Workflows

### 3.1. Flight Scheduling and the Booking Window

A `CapacityController` registers each flight by supplying its `flight_number` — unique per Flight row — together with the `origin` and `destination` IATA airport codes, the `scheduled_departure` and `scheduled_arrival` instants in ISO 8601 UTC, the cargo pools `max_payload_kg` and `max_volume_m3`, the number of `uld_position_count` positions on the aircraft, and a `dg_certified` flag declaring whether the flight may carry dangerous goods. A new flight starts in `SCHEDULED` status with its allocation counters at zero and no weight restriction.

Flights follow a one-way operating window: `SCHEDULED → OPEN_FOR_BOOKING → CLOSED → DEPARTED`. Opening the booking window is a `CapacityController` action that requires the flight to be `SCHEDULED`; a flight in any other state rejects the open with `ERR_FLIGHT_NOT_OPEN`. Closing the window requires the flight to be `OPEN_FOR_BOOKING` (again `ERR_FLIGHT_NOT_OPEN` otherwise) and additionally requires that no build-up plan on the flight remains in `DRAFT` — closing with an unfinished plan is rejected with `ERR_DRAFT_PLANS_EXIST`, since a plan must either be sealed or cancelled before the flight is frozen. Once `CLOSED`, the flight awaits departure; the departure itself and its cascade are described in §3.8. The flight list can be filtered by `status` for operational dashboards.

### 3.2. Booking Intake, Acceptance, and Rebooking

A `ForwarderAgent` tenders a shipment by creating a booking against a flight: the payload carries the target `flight_id` (which must reference an existing flight, else `ERR_NOT_FOUND`), the shipper's own `shipper_ref` house reference, a `commodity_code` such as GEN, PER, or AVI, a piece count `pieces` of at least 1, and the actual `gross_weight_kg` and `volume_m3`, each greater than 0. Optional details include `is_dangerous_goods` (defaulting to `false`), a temperature range for controlled cargo, and a `declared_value` for carriage. At creation the server computes the booking's `chargeable_weight_kg` once and immutably: the volumetric weight is the booking's `volume_m3` multiplied by the standard volumetric factor of 167.0 kilograms per cubic metre, and the chargeable weight is the greater of the actual `gross_weight_kg` and that volumetric weight, rounded half-up to two decimal places. The booking is stamped with `created_by_user_id` equal to the acting `X-User-ID`, begins life in `REQUESTED` status with `temp_excursion_count` at zero and `build_up_plan_id` unset, and its `temp_status` starts at `NOT_MONITORED`.

Acceptance is the moment capacity is committed, and it belongs to the `CapacityController`. The booking must be `REQUESTED` (any other state draws `ERR_BOOKING_INVALID_STATE`), and its flight must be `OPEN_FOR_BOOKING` (`ERR_FLIGHT_NOT_OPEN` otherwise). The dangerous-goods embargo of §3.3 applies next, and then the two capacity rungs in order — payload first, then volume. Only bookings in `ACCEPTED` or `BUILT_UP` status count toward a flight's committed totals; acceptance requires the committed weight plus the candidate's `gross_weight_kg` to be less than or equal to `max_payload_kg`, with equality accepted and only a strictly-greater result rejected as `ERR_FLIGHT_PAYLOAD_EXCEEDED`, and the committed volume plus the candidate's `volume_m3` to be less than or equal to `max_volume_m3`, likewise equality-accepted, with a strictly-greater overflow rejected as `ERR_FLIGHT_VOLUME_EXCEEDED`. On success the booking moves to `ACCEPTED`, its weight and volume are debited into `allocated_weight_kg` and `allocated_volume_m3`, and that mutation increments the flight's `version` — which is precisely what invalidates any stale `expected_flight_version` held by a ramp crew about to create a plan.

A `CapacityController` may instead reject a `REQUESTED` booking, optionally carrying a `reason`; rejection is terminal. The forwarder's own escape hatch is cancellation, restricted to the booking's owner — an `X-User-ID` that does not match `created_by_user_id` is refused with `ERR_BOOKING_NOT_OWNED` — and permitted only from `REQUESTED` or `ACCEPTED` (`ERR_BOOKING_INVALID_STATE` otherwise). Cancelling from `REQUESTED` touches nothing else; cancelling from `ACCEPTED` compensates the acceptance debit, subtracting the booking's weight and volume from the flight's allocation counters.

Offloaded cargo is not lost cargo. A booking in `OFFLOADED` status can be rebooked by a `CapacityController` onto a different flight named by `flight_id` in the request. The target flight must be `OPEN_FOR_BOOKING` (`ERR_FLIGHT_NOT_OPEN`), the dangerous-goods embargo applies exactly as at acceptance (`ERR_FLIGHT_NOT_DG_CERTIFIED`), and the same two capacity rungs are evaluated against the target flight in the same order with the same equality-accepted boundaries. A successful rebook moves the booking back to `ACCEPTED`, repoints its `flight_id` at the target flight, and debits the target flight's allocation counters; the original flight needs no adjustment because the offload already released its share. Attempting to rebook from any state other than `OFFLOADED` draws `ERR_BOOKING_INVALID_STATE`.

### 3.3. Dangerous Goods: Declaration and Segregated Acceptance

Dangerous goods travel under a two-key protocol: the forwarder declares, and an independent inspector checks. A booking flagged `is_dangerous_goods` at creation is subject to the **dangerous-goods embargo** throughout its life — it may be accepted or rebooked only onto a flight whose `dg_certified` flag is true; any attempt against an uncertified flight is rejected with `ERR_FLIGHT_NOT_DG_CERTIFIED` (HTTP 409).

The declaration itself is filed by the owning `ForwarderAgent` on the booking, carrying the `un_number` of the goods (for example UN1263), the IATA hazard `dg_class` label (for example "3" or "6.1"), a `packing_group` of exactly `I`, `II`, or `III`, and the `declaration_doc_ref` referencing the Shipper's Declaration for Dangerous Goods document. Filing presupposes the booking was actually tendered as dangerous goods — a declaration against a booking with `is_dangerous_goods` false is incoherent and rejected with `ERR_DG_NOT_APPLICABLE` (HTTP 422) — and that the booking is still in an early enough state: `REQUESTED`, `ACCEPTED`, or `BUILT_UP`, with anything later drawing `ERR_BOOKING_INVALID_STATE`. A booking may carry at most one declaration in `PENDING_CHECK` at a time; a second filing while a check is outstanding is refused with `ERR_DG_CHECK_ALREADY_PENDING`. A new declaration starts in `PENDING_CHECK` with `checked_by_user_id` unset.

The check is performed by a `DGInspector` and is bound by segregation of duties: the acting `X-User-ID` must differ from the booking's `created_by_user_id`, and a self-check is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Both the acceptance and the rejection of a declaration require it to be `PENDING_CHECK` (`ERR_DG_NOT_PENDING` otherwise). Acceptance moves the declaration to `ACCEPTED` and records the inspector in `checked_by_user_id`; rejection moves it to `REJECTED` and records both `checked_by_user_id` and a mandatory `rejection_reason`. A rejected declaration is terminal — the forwarder's remedy is to correct the paperwork and file a fresh declaration on the same booking, which is permitted once no `PENDING_CHECK` declaration remains.

The documentation gate closes the loop at build-up time: an `is_dangerous_goods` booking may only be assigned into a plan if an `ACCEPTED` declaration exists for it. Assigning one without that acceptance is rejected with `ERR_DG_NOT_ACCEPTED` (HTTP 409).

### 3.4. ULD Fleet Registration and Build-Up Operations

Before any cargo can be built, the `RampOperator` registers the container fleet. Each ULD type is registered with its IATA `type_code` (AKE, PMC, and so on), its `tare_weight_kg`, its `max_gross_weight_kg` ceiling for tare plus contents, and its usable `internal_volume_m3`; type codes are unique, and a duplicate `type_code` is rejected with `ERR_DUPLICATE_ULD_CODE`. Each physical unit is then registered with a serial `uld_code` (for example AKE12345CA), unique across all ULDs with duplicates likewise drawing `ERR_DUPLICATE_ULD_CODE`, and a `uld_type_id` naming its type, which must exist. A fresh unit starts `SERVICEABLE`, with `dispatched_at` and `returned_at` unset. The ULD list supports `status` and `uld_type_id` filters.

A build-up plan ties one flight to one unit over a build window. The `RampOperator` creates it by supplying the `flight_id`, the `uld_id`, a `build_start` and `build_end` pair with the end strictly later than the start, and the OCC token `expected_flight_version` described in §2.8. Validation walks the ladder: the referenced flight and unit must exist; the flight must be `OPEN_FOR_BOOKING` and the unit `SERVICEABLE` — a unit already committed elsewhere draws `ERR_ULD_NOT_SERVICEABLE`, while a flight outside its booking window draws `ERR_FLIGHT_NOT_OPEN`; the expected-version check fires at the same state rung. Scheduling discipline is enforced next: on the same flight, the new window must end at least 30 minutes before, or begin at least 30 minutes after, the window of every other plan in `DRAFT` or `SEALED` — a separation of exactly 30 minutes is permitted, anything tighter is rejected with `ERR_BUILD_WINDOW_CONFLICT`. Finally the position pool of §2.6 must have a slot free, else `ERR_ULD_POSITION_UNAVAILABLE`. Creating the plan leaves it in `DRAFT` with `total_weight_kg` at zero, moves the unit `SERVICEABLE → ASSIGNED`, increments the flight's `reserved_positions` by one, and increments the flight's `version`.

Building cargo into the plan is the assign operation, performed by a `RampOperator` with a payload naming the `booking_id` and the OCC token `expected_build_up_plan_version`. Its checks fire in ladder order: state first — the plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`), the booking must be `ACCEPTED` (`ERR_BOOKING_NOT_ACCEPTED`), and the plan's version must match the supplied expectation (`ERR_STALE_PLAN_VERSION`); then the safety gates — no `ACTIVE` customs hold on the booking (`ERR_CUSTOMS_HOLD_ACTIVE`), and for dangerous goods an `ACCEPTED` declaration (`ERR_DG_NOT_ACCEPTED`); then referential coherence — the booking's `flight_id` must equal the plan's `flight_id`, since cargo is never cross-loaded between flights, with a mismatch rejected as `ERR_BOOKING_FLIGHT_MISMATCH` (HTTP 422); and finally the ULD payload limit. That limit compares the projected gross — the unit type's `tare_weight_kg`, plus the plan's current `total_weight_kg`, plus the candidate's `gross_weight_kg` — against the type's `max_gross_weight_kg`: the assignment is allowed when the projection is less than or equal to the maximum, equality included, and only a strictly-greater projection is rejected with `ERR_ULD_PAYLOAD_EXCEEDED` (HTTP 422). A successful assignment moves the booking `ACCEPTED → BUILT_UP`, sets its `build_up_plan_id` to the plan, adds its `gross_weight_kg` into the plan's `total_weight_kg`, and increments the plan's `version`.

Once a plan holds cargo, the `RampOperator` seals it: sealing requires the plan to be `DRAFT` (`ERR_PLAN_NOT_DRAFT`) and to contain at least one `BUILT_UP` booking, since an empty plan must never reach the aircraft (`ERR_PLAN_EMPTY`). Sealing moves the plan `DRAFT → SEALED`. A plan that is no longer wanted can instead be cancelled from either `DRAFT` or `SEALED` — a plan in any later state is past the point of no return and draws `ERR_PLAN_NOT_CANCELLABLE`. Cancellation unwinds everything the plan held: every booking built into it returns from `BUILT_UP` to `ACCEPTED` with its `build_up_plan_id` cleared and its weight subtracted from the plan's `total_weight_kg`, the unit is released `ASSIGNED → SERVICEABLE`, and the flight's `reserved_positions` is decremented by one.

### 3.5. Temperature Monitoring for Special Cargo

Temperature-controlled cargo declares its envelope at booking time through `temp_min_c` and `temp_max_c`. The two are set together or not at all, and the minimum must not exceed the maximum; a booking created without the pair is never monitored, and its `temp_status` remains `NOT_MONITORED` for life.

While such cargo sits in the handler's custody, a `RampOperator` records readings against the booking, each carrying the `recorded_at` instant and the observed `temperature_c`. Readings are only meaningful once cargo is in the handler's operational flow, so the booking must be `ACCEPTED`, `BUILT_UP`, or `LOADED` (`ERR_BOOKING_INVALID_STATE` otherwise), and the booking must actually define a range — a reading against an unmonitored booking is rejected with `ERR_TEMP_RANGE_NOT_DEFINED` (HTTP 422).

Every recorded row gets a computed `in_range` flag: a reading is in range when `temperature_c` is greater than or equal to `temp_min_c` and less than or equal to `temp_max_c`, both bounds inclusive. The booking's monitoring posture follows from its readings. An in-range reading on a booking still `NOT_MONITORED` moves its `temp_status` to `IN_RANGE`. An out-of-range reading is harsher: the booking's `temp_excursion_count` — defined as the count of its readings with `in_range` false — increments by one, and its `temp_status` moves to `EXCURSION`, which is sticky: no later in-range reading ever returns the booking to `IN_RANGE`. The excursion history is thus preserved as a permanent, queryable record for claims and quality review.

### 3.6. Customs Holds and Release Coordination

A `CustomsOfficer` can freeze a shipment at any point before it is flown by placing a customs hold, supplying a `reason_code` such as DOC_CHECK or INSPECTION. The booking must still be in the handler's pre-departure pipeline — `REQUESTED`, `ACCEPTED`, or `BUILT_UP`, else `ERR_BOOKING_INVALID_STATE` — and a booking carries at most one `ACTIVE` hold: placing a second while one is outstanding is refused with `ERR_HOLD_ALREADY_ACTIVE`. The hold is stamped `placed_at` from the logical clock and starts `ACTIVE`.

The hold's teeth are the customs gate at build-up: any booking with an `ACTIVE` hold is refused at assignment with `ERR_CUSTOMS_HOLD_ACTIVE` (HTTP 409), keeping detained cargo off aircraft regardless of how otherwise ready it is. When the authority clears the shipment, the `CustomsOfficer` releases the hold — only an `ACTIVE` hold can be released, anything else drawing `ERR_HOLD_NOT_ACTIVE` — optionally recording a `release_note`; the release stamps `released_at` from the logical clock, stores the note, and moves the hold to `RELEASED`, its terminal state. With the hold no longer `ACTIVE`, the booking's path into a build-up plan reopens.

### 3.7. Weight Restrictions and Offload Prioritization

Operational reality sometimes shrinks an aircraft: a `CapacityController` can impose a restricted payload on a flight by supplying `restricted_payload_kg`, provided the flight is `OPEN_FOR_BOOKING` or `CLOSED` (any other state draws `ERR_FLIGHT_NOT_OPEN`) and the restriction is sensible — greater than 0 and no more than the flight's `max_payload_kg`, else `ERR_INVALID_REQUEST`. The restriction is recorded on the flight as `weight_restriction_kg`, and the offload selection then runs against the committed weight.

The selection begins by computing the required reduction: the flight's current `allocated_weight_kg` minus the restricted payload. If that reduction is zero or negative, the flight already fits and no booking is offloaded — only the restriction itself is recorded. Otherwise the candidate pool is every booking on the flight in `ACCEPTED` or `BUILT_UP` status, ranked by `created_at` descending so the most recently accepted cargo is sacrificed first, with ties broken by `gross_weight_kg` descending and then by `volume_m3` descending. Bookings are offloaded one at a time in exactly that order — each with its full cascade below — recomputing `allocated_weight_kg` after each removal, until the allocated weight is less than or equal to the restricted payload. Offloading is whole-booking only; a booking is never partially split. Because emptying the pool drives the allocated weight to zero, which satisfies any positive restriction, the selection never dead-ends.

Each offload moves its booking to `OFFLOADED` and releases the flight's allocation by the booking's weight and volume. When the victim was merely `ACCEPTED`, that release is the whole story, and the booking awaits rebooking per §3.2. When the victim was `BUILT_UP`, the cascade continues: the booking is removed from its plan — `build_up_plan_id` cleared and the plan's `total_weight_kg` reduced by the booking's `gross_weight_kg` — and if that removal empties a plan that is still `DRAFT` of its last `BUILT_UP` booking, the plan auto-transitions `DRAFT → CANCELLED`, which in turn releases its unit `ASSIGNED → SERVICEABLE` and decrements the flight's `reserved_positions` by one, exactly mirroring an operator-driven cancellation.

### 3.8. Departure Dispatch, Demurrage, and Repair Charges

Departure is the flight's terminal act and belongs to the `CapacityController`; it requires the flight to be `CLOSED`, with any other state rejected as `ERR_FLIGHT_NOT_CLOSED`. One departure fires a five-link cascade across every aggregate the flight touched. First, every `SEALED` build-up plan on the flight moves to `DEPARTED`. Second, each departed plan's unit moves `ASSIGNED → DISPATCHED`, its `dispatched_at` stamped from the logical clock. Third, each newly dispatched unit immediately accrues a demurrage charge: a `ULDCharge` of `charge_type` `DEMURRAGE` is created in `PROVISIONAL` status, priced by the provisional variant below with the end instant set to the flight's `scheduled_arrival`. Fourth, every booking `BUILT_UP` on a departed plan moves to `LOADED` — cargo that made the aircraft. Fifth, every `ACCEPTED` booking that was never built into a plan is left behind: it moves to `OFFLOADED`, its weight and volume are released from the flight's allocation counters, and it enters the rebookable pool of §3.2.

Demurrage is billed on whole days in use: the elapsed time between the unit's `dispatched_at` and the end instant is divided into whole 24-hour periods, rounding any partial day down. Chargeable days are the days in use minus a free allowance of three days, never falling below zero, so a unit returned within the allowance accrues nothing. The first four chargeable days are billed as `tier1_days` at 50.00 per unit per day; any remaining chargeable days are billed as `tier2_days` at 120.00 per unit per day. The charge `amount` is the sum of the two tier charges, rounded half-up to two decimal places. The provisional variant runs at dispatch with the end instant set to the flight's `scheduled_arrival` and stores the resulting `amount`, `tier1_days`, and `tier2_days` on a `PROVISIONAL` charge row; the final variant runs when the unit comes back, recomputing the same charge row with the end instant set to the unit's actual `returned_at` and moving the charge `PROVISIONAL → FINALIZED`.

A unit's homecoming is processed by a `RampOperator`. Returning requires the unit to be `DISPATCHED` (`ERR_ULD_INVALID_STATE` otherwise); it stamps `returned_at` from the logical clock, moves the unit to `RETURNED`, and finalizes its demurrage charge as described above. From `RETURNED`, an undamaged unit is released straight back to `SERVICEABLE`. A damaged unit instead has its damage reported — again only from `RETURNED`, else `ERR_ULD_INVALID_STATE` — with the operator supplying a `damage_description` and a `repair_cost_estimate`; the unit moves to `DAMAGE_REPORTED`, and a `ULDCharge` of `charge_type` `REPAIR` is created in `PROVISIONAL` status with `amount` set to the supplied estimate and the charge's `description` copied from the damage report. Completing the repair requires the unit to be `DAMAGE_REPORTED` (`ERR_ULD_INVALID_STATE` otherwise); the operator supplies the `final_repair_cost`, the unit returns to `SERVICEABLE`, and the repair charge is finalized with `amount` set to that final cost, status moving to `FINALIZED`.

Charges are therefore a per-unit ledger of `PROVISIONAL → FINALIZED` rows: demurrage rows carry `tier1_days` and `tier2_days` while repair rows carry a `description`, and every row is keyed to its unit via `uld_id`. Charges can be listed per unit with `charge_type` and `status` filters, and retrieved individually.

### 3.9. Damage and Loss Claims

When cargo that flew arrives harmed or fails to arrive whole, the owning `ForwarderAgent` files a claim against the booking. Filing requires the booking to be `LOADED` — cargo still in the pipeline draws `ERR_BOOKING_INVALID_STATE` — and ownership is enforced exactly as for cancellation: an `X-User-ID` other than the booking's `created_by_user_id` is refused with `ERR_BOOKING_NOT_OWNED`. The filing names the `booking_id`, a `claim_type` of exactly `DAMAGE` or `LOSS`, a `claimed_amount` greater than 0, a non-empty `items` list in which each entry carries a `weight_kg` greater than 0, and an optional free-text `description`. A new claim starts `SUBMITTED`, with `item_total`, `basis`, `approved_amount`, and `settlement_ref` all unset until adjudication.

Adjudication belongs to the `ClaimsAdjuster`. Approval requires the claim to be `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`) and runs the settlement calculation in full. The claim's `item_total` is computed by multiplying each item's `weight_kg` by the liability rate of 19.00 per kilogram, rounding each per-item product half-up to two decimal places first, and only then summing the rounded per-item amounts — this pinned order, per-item rounding strictly before summation, is part of the contract. The settlement `basis` then depends on the claimed-against booking: when the booking carries no `declared_value`, the basis is `LIABILITY` and the cap is the booking's `chargeable_weight_kg` multiplied by the same 19.00 per-kilogram rate, rounded half-up to two decimal places; when the booking does carry a `declared_value`, the basis is `DECLARED_VALUE` and the cap is that declared value itself, with weight playing no role in the cap. The `approved_amount` is the smallest of the three figures — `claimed_amount`, `item_total`, and the applicable cap — rounded half-up to two decimal places, and approval moves the claim to `APPROVED` with all three computed fields stored.

A `ClaimsAdjuster` may instead reject a `SUBMITTED` claim outright, supplying a `reason`; rejection is terminal. An approved claim is closed out by settlement, which requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_APPROVED` otherwise) and records the payment's `settlement_ref` on the claim as it moves to `SETTLED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a flight, booking, declaration, temperature reading, customs hold, ULD type, ULD unit, build-up plan, or claim — return `201 Created`. Operations that modify an existing resource's state, and all retrievals, return `200 OK`. Request and response payloads for every operation are specified by the narratives in §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cargo/flights` | Create a flight with its cargo capacity pools | CapacityController |
| GET | `/cargo/flights` | List flights, optionally filtered by status | All roles |
| GET | `/cargo/flights/{id}` | Get one flight | All roles |
| POST | `/cargo/flights/{id}/open` | Open a SCHEDULED flight for booking | CapacityController |
| POST | `/cargo/flights/{id}/close` | Close an OPEN_FOR_BOOKING flight; requires no DRAFT plans | CapacityController |
| POST | `/cargo/flights/{id}/depart` | Depart a CLOSED flight; fires the dispatch cascade | CapacityController |
| POST | `/cargo/flights/{id}/weight-restriction` | Impose a restricted payload; runs offload selection | CapacityController |
| GET | `/cargo/flights/{id}/bookings` | List bookings allocated to a flight | All roles |
| GET | `/cargo/flights/{id}/build-up-plans` | List build-up plans for a flight | All roles |
| POST | `/cargo/bookings` | Create a booking on a flight (REQUESTED) | ForwarderAgent |
| GET | `/cargo/bookings/{id}` | Get one booking | All roles |
| POST | `/cargo/bookings/{id}/accept` | Accept a REQUESTED booking, debiting flight capacity | CapacityController |
| POST | `/cargo/bookings/{id}/reject` | Reject a REQUESTED booking | CapacityController |
| POST | `/cargo/bookings/{id}/cancel` | Cancel a REQUESTED or ACCEPTED booking (owner only) | ForwarderAgent |
| POST | `/cargo/bookings/{id}/rebook` | Rebook an OFFLOADED booking onto another flight | CapacityController |
| GET | `/cargo/bookings/{id}/dg-declarations` | List DG declarations for a booking | All roles |
| POST | `/cargo/bookings/{id}/dg-declarations` | File a dangerous-goods declaration (PENDING_CHECK) | ForwarderAgent |
| GET | `/cargo/bookings/{id}/temperature-logs` | List temperature readings for a booking | All roles |
| POST | `/cargo/bookings/{id}/temperature-logs` | Record a temperature reading; runs the excursion check | RampOperator |
| GET | `/cargo/bookings/{id}/customs-holds` | List customs holds for a booking | All roles |
| POST | `/cargo/bookings/{id}/customs-holds` | Place a customs hold on a booking (ACTIVE) | CustomsOfficer |
| GET | `/cargo/bookings/{id}/claims` | List claims filed against a booking | All roles |
| POST | `/cargo/uld-types` | Register a ULD type | RampOperator |
| POST | `/cargo/ulds` | Register a ULD unit (SERVICEABLE) | RampOperator |
| GET | `/cargo/ulds` | List ULDs, optionally filtered by status and type | All roles |
| GET | `/cargo/ulds/{id}` | Get one ULD | All roles |
| POST | `/cargo/ulds/{id}/return` | Return a DISPATCHED ULD; finalizes demurrage | RampOperator |
| POST | `/cargo/ulds/{id}/report-damage` | Report damage on a RETURNED ULD; creates a PROVISIONAL repair charge | RampOperator |
| POST | `/cargo/ulds/{id}/complete-repair` | Complete repair; finalizes the repair charge and restores the unit | RampOperator |
| POST | `/cargo/ulds/{id}/release` | Release an undamaged RETURNED ULD to SERVICEABLE | RampOperator |
| GET | `/cargo/ulds/{id}/build-up-plans` | List build-up plans that used a ULD | All roles |
| GET | `/cargo/ulds/{id}/charges` | List charges for a ULD, filterable by type and status | All roles |
| POST | `/cargo/build-up-plans` | Create a build-up plan; OCC-guarded on the flight's version | RampOperator |
| GET | `/cargo/build-up-plans/{id}` | Get one build-up plan | All roles |
| GET | `/cargo/build-up-plans/{id}/bookings` | List bookings currently built into a plan | All roles |
| POST | `/cargo/build-up-plans/{id}/assign` | Assign an ACCEPTED booking to a DRAFT plan; OCC-guarded on the plan's version | RampOperator |
| POST | `/cargo/build-up-plans/{id}/seal` | Seal a DRAFT plan that contains at least one booking | RampOperator |
| POST | `/cargo/build-up-plans/{id}/cancel` | Cancel a DRAFT or SEALED plan; built bookings return to ACCEPTED | RampOperator |
| POST | `/cargo/dg-declarations/{id}/accept` | Accept a PENDING_CHECK declaration (segregated checker) | DGInspector |
| POST | `/cargo/dg-declarations/{id}/reject` | Reject a PENDING_CHECK declaration with a reason | DGInspector |
| POST | `/cargo/customs-holds/{id}/release` | Release an ACTIVE customs hold | CustomsOfficer |
| POST | `/cargo/claims` | File a damage or loss claim against a LOADED booking (owner only) | ForwarderAgent |
| GET | `/cargo/claims/{id}` | Get one claim | All roles |
| POST | `/cargo/claims/{id}/approve` | Approve a SUBMITTED claim; computes the settlement | ClaimsAdjuster |
| POST | `/cargo/claims/{id}/reject` | Reject a SUBMITTED claim | ClaimsAdjuster |
| POST | `/cargo/claims/{id}/settle` | Settle an APPROVED claim with a payment reference | ClaimsAdjuster |
| GET | `/cargo/uld-charges/{id}` | Get one ULD charge | All roles |
| POST | `/cargo/_clock/set_current_utc` | Set the server's logical clock | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is a reference summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_BOOKING_NOT_OWNED` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FLIGHT_NOT_OPEN` | 409 Conflict |
| `ERR_FLIGHT_NOT_CLOSED` | 409 Conflict |
| `ERR_DRAFT_PLANS_EXIST` | 409 Conflict |
| `ERR_BOOKING_NOT_ACCEPTED` | 409 Conflict |
| `ERR_BOOKING_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PLAN_EMPTY` | 409 Conflict |
| `ERR_ULD_NOT_SERVICEABLE` | 409 Conflict |
| `ERR_ULD_INVALID_STATE` | 409 Conflict |
| `ERR_DG_NOT_PENDING` | 409 Conflict |
| `ERR_DG_CHECK_ALREADY_PENDING` | 409 Conflict |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_HOLD_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_FLIGHT_NOT_DG_CERTIFIED` | 409 Conflict |
| `ERR_CUSTOMS_HOLD_ACTIVE` | 409 Conflict |
| `ERR_DG_NOT_ACCEPTED` | 409 Conflict |
| `ERR_DG_NOT_APPLICABLE` | 422 Unprocessable Entity |
| `ERR_BUILD_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_ULD_CODE` | 409 Conflict |
| `ERR_ULD_PAYLOAD_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ULD_POSITION_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_FLIGHT_PAYLOAD_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FLIGHT_VOLUME_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BOOKING_FLIGHT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TEMP_RANGE_NOT_DEFINED` | 422 Unprocessable Entity |
| `ERR_STALE_FLIGHT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |

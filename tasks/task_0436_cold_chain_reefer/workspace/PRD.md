# Cold-Chain Reefer Logistics API — Product Requirements Document

## 1. Introduction

Perishable freight lives or dies by the temperature it travels at. This document specifies the Cold-Chain & Reefer Logistics API, a backend platform that coordinates temperature-controlled shipments end to end: a shipper tenders a load, a carrier accepts it onto a refrigerated ("reefer") unit, a driver precools the equipment, hauls it under continuous sensor telemetry, and finally delivers it — at which point the platform adjudicates whether the cargo held its required temperature band the whole way.

The system exists to make cold-chain accountability mechanical rather than anecdotal. Every compartment runs on a named temperature lane with an inclusive set-point band; every degree-minute that the load spends outside that band is integrated from the raw sensor stream and accumulated against a per-lane tolerance. When the accumulated excursion crosses defined thresholds, the platform classifies each compartment's impairment and rolls those classifications up into a shipment-wide load-integrity posture that gates delivery and spoilage claims. Because the cargo here is food and pharmaceutical product subject to FSMA Sanitary Transport rules, the platform also enforces a set of regulatory gates at dispatch — sanitary-transport registration, current driver training, and documented washout — and computes the lumper and detention fees that accrue at each loading stop.

The remainder of this document defines the global contract that every endpoint honors (Section 2), the business logic and lifecycle workflows that the domain entities move through (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. When either header is absent, or when `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The one exception to the authentication rule is the logical-clock setter, which still requires the `PlatformAdmin` role.

The platform recognizes exactly five roles: `Shipper`, `Carrier`, `Driver`, `ComplianceOfficer`, and `PlatformAdmin`.

Most roles are operator identities not tied to any persisted record. When `X-User-Role` is `Shipper`, `X-User-ID` is an opaque shipper operator identifier; it is not a foreign key to any entity. The server records it where a workflow demands — for example, it is stamped onto a shipment's `shipper_user_id` when the shipment is tendered, and onto a claim's `filed_by_user_id` when a spoilage claim is filed — and ownership of shipper-only actions (cancelling a shipment, withdrawing a claim) is enforced by comparing the caller's `X-User-ID` against that stored field rather than against any record's `id`. When `X-User-Role` is `Driver`, `X-User-ID` is likewise an opaque operator identifier the server does not compare to any entity's `id`. The same is true for `ComplianceOfficer` and for `PlatformAdmin`: both are opaque operator identifiers, recorded if a workflow needs them but never matched against a persisted entity's `id`.

`Carrier` is the one entity-backed role. When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of the acting `Carrier` record; ownership checks on any resource that references a carrier compare that resource's carrier foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter skips a number of leading items and defaults to 0. A `limit` or `offset` outside these bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses populate four fields inside the response envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system — carriers, reefer units, temp lanes, shipments, compartments, product lots, spoilage claims, and stop events — carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation. The `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource; it is the value compared during optimistic concurrency control.

Sensor readings are the exception. A `SensorReading` is an append-only telemetry event: once written it is never modified. Such readings carry only `id` and `created_at` — they have no `updated_at` field and no `version` field.

When a derived or computed field on a resource changes as a side effect of some operation (for instance, a shipment's `load_integrity_posture`, `total_detention_fee_cents`, or `total_lumper_fee_cents` being recomputed), that recomputation is a mutation of the resource: it refreshes `updated_at` and increments `version`.

### 2.5. Nested Resource Retrieval and Referential Integrity

Several endpoints address resources through a path that names more than one identifier — for example, a stop nested beneath a shipment names both the shipment `id` and the `stopId`, and a reading is appended under a compartment `cid`. The platform validates these path identifiers strictly left to right. It first confirms the leftmost resource (the shipment) exists, then the next (the compartment or stop), and so on. The request fails with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve, before any deeper identifier or business rule is considered. Existence of every path-referenced resource is therefore checked ahead of referential and state checks.

Foreign keys carried in a request body are validated separately. When a create or accept request names a related resource by id — a `carrier_id`, a `reefer_unit_id`, a `temp_lane_id`, a `compartment_id`, or a `shipment_id` — and that id does not resolve to an existing resource of the correct type, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 422). Note the distinction in status: a missing resource named in the URL path yields 404, whereas a missing foreign key named in the body yields 422.

### 2.6. Validation Ordering

When several checks apply to a single request, the platform evaluates them in a fixed priority order so that the failure a client sees is deterministic. Authentication comes first: a request missing or carrying an unknown `X-User-Role`/`X-User-ID` fails with `ERR_UNAUTHENTICATED` before anything else. Role authorization is second: a recognized but unpermitted role fails with `ERR_FORBIDDEN_ROLE`. Third is path existence — every id named in the URL must resolve, failing with `ERR_NOT_FOUND`. Fourth is body-level referential integrity — foreign keys in the body must resolve, failing with `ERR_FK_NOT_FOUND`. Fifth is state legality: the target resource must currently be in a state from which the requested transition is allowed, failing with `ERR_INVALID_STATE` (HTTP 409).

After those five framework checks, the domain-specific business rules apply (the dispatch safety gates, the precool gate, the unit-sizing gate, uniqueness gates, the temporal and window gates, claim eligibility, and reading-shape rules described throughout Sections 2 and 3), each with its own error code. General request well-formedness — required fields present, enum values valid, numeric fields within their declared ranges, and pagination parameters within bounds — is enforced as `ERR_INVALID_REQUEST` (HTTP 400). For the accept operation specifically, the optimistic-concurrency version check is the final gate, described in Section 2.7.

### 2.7. Optimistic Concurrency Control on Accept

A carrier accepting a tendered shipment is the one operation guarded by optimistic concurrency control, because the shipment's structure (its set of compartments) can change between the moment a carrier reads it and the moment the carrier acts. The accept request must carry a non-optional `expected_shipment_version` field holding the `version` of the shipment that the carrier last observed. If that value does not equal the shipment's current `version`, the accept is rejected with `ERR_STALE_VERSION` (HTTP 412).

This is the intended serialization point between shipment editing and tender acceptance. Adding or removing a compartment increments the shipment's `version`; if the shipper added or removed a compartment after the carrier read the shipment, the carrier's `expected_shipment_version` is now behind the stored `version`, the accept is rejected, and the carrier is forced to re-read the (possibly larger) shipment before committing a unit to it. No other endpoint takes a version field; only accept performs this check.

### 2.8. Degree-Minutes, Tolerances, and Impairment Classification

The core integrity measure in this system is **out-of-band degree-minutes** — the area, in degree-Celsius times minutes, that a compartment's temperature spends outside its lane's set-point band. Each compartment runs on exactly one temperature lane, and that lane fixes an inclusive band between `setpoint_min_c` and `setpoint_max_c`. A temperature reading is "in band" when it is at or between those two bounds inclusive; otherwise it is out of band, and its out-of-band magnitude is how far it sits beyond the nearer bound (above the maximum or below the minimum). The full integration algorithm — how readings are ordered and how the area accumulates — is detailed in Section 3.6, and the accumulated total is carried on each compartment as `degree_minutes_out`.

Each lane also defines a free allowance, `tolerance_degree_minutes` (the per-lane tolerance, sometimes called the free tolerance), defaulting to 30 degree-minutes when not specified. A compartment's `impairment` is then classified from its `degree_minutes_out` against that tolerance using two boundaries. If the accumulated degree-minutes are at most the tolerance, the impairment is `NONE` (the cargo is sound). If they exceed the tolerance but are at most the tolerance plus a fixed partial span of 90 degree-minutes, the impairment is `PARTIAL` (impaired). If they exceed the tolerance plus 90 degree-minutes, the impairment is `TOTAL_LOSS` (spoiled). The boundaries are inclusive on the lower side: a compartment whose total lands exactly on the tolerance is `NONE`; one landing exactly on the tolerance plus 90 is `PARTIAL`; anything beyond — even fractionally, such as the tolerance plus 90.01 — is `TOTAL_LOSS`. Impairment is recomputed every time a sensor reading is appended and is finalized when the shipment is delivered.

### 2.9. Load-Integrity Posture

Above the per-compartment impairment sits a shipment-wide aggregate, `load_integrity_posture`, derived by taking the worst compartment. If any compartment's `impairment` is `TOTAL_LOSS`, the posture is `COMPROMISED`. Otherwise, if any compartment's `impairment` is `PARTIAL`, the posture is `AT_RISK`. Otherwise — when every compartment is `NONE` — the posture is `INTACT`. This posture is recomputed on every sensor reading and on every door event, and finalized at delivery. It is the gate that decides whether a spoilage claim may be filed: only an `AT_RISK` or `COMPROMISED` shipment is eligible.

### 2.10. Monetary Values, Degree-Minute Precision, and Rounding

All monetary amounts in the system are integer cents: carrier liability caps, declared lot values, claim figures, and the detention and lumper fees are all whole-cent integers, and intermediate fee math is carried in integer cents. Where a fee calculation rounds (specifically the per-lot spoilage payout described in Section 3.8), the rounding method is round-half-up to whole cents.

Degree-minutes are carried internally as an exact number. Where a degree-minute figure is reported to a client — for instance in the provisional excursion report — it is rounded half up to two decimal places. The load-integrity score described in Section 3.7 is rounded half up to a whole integer in the range 0 through 100 inclusive.

### 2.11. Fee Accrual and Reconciliation

Detention and lumper fees are computed per stop when a stop closes, and the shipment maintains running totals over its closed stops. When a `StopEvent` closes, the platform computes that stop's `detention_fee_cents` and `lumper_fee_cents` (Section 3.9), then recomputes the parent shipment's `total_detention_fee_cents` as the sum of `detention_fee_cents` over all of the shipment's closed stops, and likewise recomputes `total_lumper_fee_cents` as the sum of `lumper_fee_cents` over all closed stops. Both shipment totals default to 0 before any stop has closed. Because these are derived fields on the shipment, recomputing them is a mutation of the shipment and refreshes its `updated_at` and `version` per Section 2.4.

## 3. Business Logic & Workflows

### 3.1. Configuration: Carriers, Reefer Units, and Temperature Lanes

Before any freight moves, the platform's configuration entities must exist. A carrier is registered with its `legal_name` and three compliance attributes that gate later operations: `fsma_registered`, a boolean recording whether the carrier holds an active FSMA Sanitary Transport registration and defaulting to false; `sanitary_training_current`, a boolean recording whether driver sanitary-transport training is current and defaulting to false; and `liability_cap_cents`, the maximum the carrier will pay out on any single spoilage claim, defaulting to 5,000,000 cents (fifty thousand dollars). A carrier's compliance flags and liability cap can be amended after registration; each such amendment increments the carrier's `version`.

A reefer unit is registered under a carrier and carries the owning `carrier_id`, an `asset_tag`, a `compartment_count`, and an optional `last_sanitation_at` timestamp documenting its most recent washout. The `compartment_count` is the number of independently controllable temperature compartments the unit has and must be an integer from 1 through 4 inclusive — a value of 1 means a single-temperature unit and a value greater than 1 means a multi-temp unit. The `asset_tag` must be unique among that carrier's units that are not retired; registering a unit whose tag collides with an existing non-retired unit of the same carrier is rejected with `ERR_DUPLICATE_ASSET_TAG`. A unit begins life with `status` `AVAILABLE`. The carrier can later document a fresh washout by recording a new `last_sanitation_at` on the unit, which increments the unit's `version`.

A reefer unit moves through `AVAILABLE`, `ASSIGNED`, `IN_TRANSIT`, and the terminal `RETIRED` state. It is drawn from the available pool when a shipment is accepted (`AVAILABLE → ASSIGNED`), placed on the road when that shipment dispatches (`ASSIGNED → IN_TRANSIT`), and returned to the pool when the shipment delivers (`IN_TRANSIT → AVAILABLE`). It also returns to `AVAILABLE` from `ASSIGNED` when the shipment that reserved it is cancelled or rejected. An `AVAILABLE` unit may be retired; retiring a unit moves it to `RETIRED` and frees its `asset_tag` for reuse. Retirement is only permitted from `AVAILABLE`; attempting it from any other state fails the state check with `ERR_INVALID_STATE`.

Temperature lanes are platform-managed. A lane is created with a human-readable `code` (such as FROZEN, CHILLED, or PHARMA_CRT) that must be globally unique among lanes, an inclusive lower bound `setpoint_min_c` and inclusive upper bound `setpoint_max_c` in Celsius where the maximum must be greater than or equal to the minimum, a `regulated` flag (defaulting to true) marking the lane as carrying food or pharma cargo subject to FSMA Sanitary Transport rules, and the `tolerance_degree_minutes` free allowance (defaulting to 30) that drives impairment classification.

### 3.2. Tendering a Shipment and Assembling Its Structure

A shipper tenders a shipment by naming the `carrier_id` it is offered to and the `cargo_class`, which is one of `FOOD`, `PHARMA`, or `GENERAL`. On tender the server stamps the shipper's `X-User-ID` onto the shipment's `shipper_user_id`; this stored value, not any record id, is what later authorizes the shipper-only cancel and claim-withdraw actions. A freshly tendered shipment has `status` `TENDERED`, a null `reefer_unit_id`, a `precool_verified` flag of false, both fee totals at 0, and no assigned posture yet.

While the shipment is still `TENDERED`, the shipper builds out its structure. Each compartment is added by naming the `temp_lane_id` it will run on and its `ordinal` — a 1-based position within the reefer unit. The `ordinal` must be unique among the shipment's compartments and must fall within 1 through the reefer compartment count range; a duplicate or out-of-range ordinal is rejected with `ERR_DUPLICATE_ORDINAL`. Adding a compartment binds it to its owning `shipment_id` and increments the shipment's `version` — this version bump is exactly what the accept-time concurrency check (Section 2.7) keys on. A new compartment starts with `door_open_events` at 0, `degree_minutes_out` at 0, and `impairment` `NONE`.

Within a compartment, the shipper records the product it carries as one or more lots. Each lot names its owning `compartment_id` and carries a `sku` product code, a `pallet_count` of at least 0, and a `declared_value_cents` (the declared cargo value, the basis for any spoilage payout) of at least 0. A lot begins with `spoilage_status` `SOUND`; that classification is only ever set later, at the moment a spoilage claim is filed and again when it is approved.

### 3.3. Acceptance, Rejection, and Cancellation

A carrier responds to a tender either by accepting it onto a specific reefer unit or by rejecting it. Acceptance names the `reefer_unit_id` to use and the `expected_shipment_version` for the concurrency check. The shipment must currently be `TENDERED`, must have at least one compartment, and the carrier's view must be current (the `expected_shipment_version` must equal the shipment's `version`, else `ERR_STALE_VERSION`). The named unit must be `AVAILABLE` and must belong to the shipment's `carrier_id`, and its `compartment_count` must be greater than or equal to the number of compartments declared on the shipment — a unit with too few compartments is rejected with `ERR_UNIT_TOO_SMALL`. On a successful accept the shipment moves `TENDERED → ACCEPTED`, its `reefer_unit_id` is set to the named unit, that unit moves `AVAILABLE → ASSIGNED`, and the shipment's `version` increments by 1.

Rejection is simpler: a carrier rejects a `TENDERED` shipment, moving it `TENDERED → REJECTED`. This is terminal and no unit was ever assigned, so nothing is released.

A shipper may cancel a shipment after it has been accepted but before it dispatches — that is, while it is in `ACCEPTED` or in `PRECOOLED`. Cancellation requires that the caller's `X-User-ID` match the shipment's `shipper_user_id`. From either of those two states the shipment moves to `CANCELLED`; in both cases the reefer unit that was reserved transitions `ASSIGNED → AVAILABLE` and the shipment's `reefer_unit_id` is cleared back to null, returning the unit to the pool. Attempting to cancel from a state other than `ACCEPTED` or `PRECOOLED` fails the state check with `ERR_INVALID_STATE`.

### 3.4. Precool Verification

Before a load can roll, the equipment must be precooled into band. The driver or carrier appends precool readings (see Section 3.5), and the carrier then requests precool verification. This is permitted only from `ACCEPTED`, and it succeeds only when every compartment on the shipment has at least one `PRECOOL` sensor reading whose `temp_c` lies within that compartment's lane band — at or between `setpoint_min_c` and `setpoint_max_c` inclusive. If any compartment lacks such an in-band precool reading, verification is rejected with `ERR_PRECOOL_INCOMPLETE`. On success the shipment's `precool_verified` flag is set to true and the shipment moves `ACCEPTED → PRECOOLED`.

### 3.5. Sensor Telemetry and the Door Log

Telemetry is appended to a compartment as a stream of sensor readings. Each reading names its `compartment_id`, a `kind` that is one of `TEMP`, `DOOR_OPEN`, or `PRECOOL`, an `offset_min` (the minutes elapsed since the shipment's `IN_TRANSIT` start, which must be at least 0), and — for temperature-bearing kinds — a `temp_c`. The shape rule is strict: a `TEMP` or `PRECOOL` reading must carry a `temp_c`, and a `DOOR_OPEN` reading must omit `temp_c`; a violation of either half is rejected with `ERR_READING_SHAPE`. A negative `offset_min` is an invalid interval and is rejected with `ERR_INVALID_INTERVAL`.

Readings of the same kind form a strictly monotonic point-event series per compartment. When a reading is appended, its `offset_min` must be strictly greater than the maximum `offset_min` among that compartment's existing readings of the same `kind`; a reading whose offset is equal to or earlier than the latest same-kind offset collides and is rejected with `ERR_READING_OFFSET_DUPLICATE`. These are zero-width point events — equality alone collides, and there is no buffer.

Appending a reading drives several side effects. A `TEMP` reading whose `temp_c` falls outside the compartment's lane band has its computed `excursion_flagged` set to true on insert (an in-band `TEMP` reading leaves it false), and the shipment's posture is recomputed. A `DOOR_OPEN` reading increments the compartment's `door_open_events` count and recomputes posture. A `PRECOOL` reading that lands within band is what enables precool verification for that compartment. Because posture recomputation mutates the shipment, it refreshes the shipment's `updated_at` and `version`.

### 3.6. Dispatch and the Telemetry Clock

Dispatch is the regulatory choke point. A carrier dispatches a shipment only from `PRECOOLED`, and only when `precool_verified` is true. Three compliance gates then apply. First, if any compartment's lane is regulated (its `regulated` flag is true), the owning carrier's `fsma_registered` must be true, else the dispatch is rejected with `ERR_FSMA_NOT_REGISTERED`. Second, if the shipment's `cargo_class` is `FOOD` or `PHARMA`, the carrier's `sanitary_training_current` must be true, else `ERR_SANITARY_TRAINING_LAPSED`. Third, the assigned reefer unit's `last_sanitation_at` must be set (a washout must have been documented), else `ERR_SANITATION_UNDOCUMENTED`. When all three gates pass, the shipment moves `PRECOOLED → IN_TRANSIT`, the reefer unit moves `ASSIGNED → IN_TRANSIT`, and the moment of dispatch anchors the telemetry timeline so that `offset_min = 0` corresponds to the `IN_TRANSIT` start.

The platform keeps a logical clock used to make live excursion windows deterministic. Its startup default is 2026-01-01T00:00:00Z; before any call the clock reads exactly that default and never falls back to wall-clock time. A `PlatformAdmin` can advance it by supplying a target instant in `to_iso8601`, after which the clock reports the supplied `current_utc`.

The excursion measure itself integrates the temperature stream as a step function. Consider only the `TEMP` readings of a compartment — `DOOR_OPEN` and `PRECOOL` readings are excluded from this integration. Order those `TEMP` readings by `offset_min` ascending, breaking ties by `created_at` ascending. Walk them in order; each reading holds its observed temperature constant until the next reading. For each reading, the interval duration is the next reading's `offset_min` minus this reading's `offset_min` (and never less than 0), and the out-of-band magnitude is how far the reading's `temp_c` sits beyond the nearer bound — the greater of (the temperature minus `setpoint_max_c`), (`setpoint_min_c` minus the temperature), and 0. The reading's contribution is its duration multiplied by its out-of-band magnitude, and `degree_minutes_out` is the sum of those contributions over all the compartment's `TEMP` readings.

This measure has two variants that differ only in where the final reading's interval ends. The **provisional** variant, exposed as a live computed read while the shipment is `IN_TRANSIT`, ends the last reading's open trailing interval at the current logical-clock offset (now) — so as wall-time advances under a fixed clock, that trailing interval, and thus the provisional figure, grows. The **final** variant, computed at delivery, ends the last reading's interval at that last reading's own `offset_min`, closing the series with no open trailing interval so the result is fixed and replay-stable. The live excursion read returns the compartment's `provisional_degree_minutes_out`, an `excursion_flagged_count` of how many of its `TEMP` readings were flagged, and the `as_of_offset_min` clock offset the provisional figure was computed at.

### 3.7. Integrity Reporting

A computed integrity report gives a single 0-to-100 health score for a shipment alongside a per-compartment breakdown. The score is a worst-link aggregate. Each compartment is scored starting from 100. If the compartment was not precooled within band, 30 points are deducted. For door activity, 5 points are deducted for each door-open event beyond a free allowance of 2 — that is, the deduction applies to the number of `door_open_events` minus 2 when that difference is positive, and is zero otherwise. For thermal excursion, 10 points are deducted per degree-hour of accumulated excursion, where degree-hours are the compartment's `degree_minutes_out` divided by 60 (the compartment uses its final degree-minutes once the shipment is `DELIVERED`, and its provisional degree-minutes otherwise). Each compartment's score is clamped to the range 0 through 100. The shipment's `load_integrity_score` is the minimum of the per-compartment scores — the worst compartment — rounded half up to a whole integer. The report returns this score together with the shipment's `load_integrity_posture` and a `compartments` array carrying the per-compartment breakdown. Note that the posture itself is driven by per-compartment `impairment` as described in Section 2.9, not by this score.

### 3.8. Delivery, Spoilage Claims, and Settlement

Delivery is performed by a driver from `IN_TRANSIT`, and only when every delivery stop on the shipment is closed (every `StopEvent` of kind `DELIVERY` is in `CLOSED`). On delivery the platform finalizes `degree_minutes_out` for every compartment using the final variant, recomputes each compartment's `impairment` and the shipment's `load_integrity_posture` from those finalized figures, moves the shipment `IN_TRANSIT → DELIVERED`, and returns the reefer unit `IN_TRANSIT → AVAILABLE`.

Only after delivery can a shipper file a spoilage claim, and only when the cargo actually suffered. A claim names the `shipment_id` it is filed against. It is eligible only when that shipment is `DELIVERED` and its `load_integrity_posture` is `AT_RISK` or `COMPROMISED`, and only when there is no other claim already open against the same shipment — at most one claim in `FILED`, `UNDER_REVIEW`, or `APPROVED` status may exist per shipment at a time. A claim that targets a shipment that is not delivered, or whose posture is `INTACT`, or that would be a second concurrent open claim, is rejected with `ERR_CLAIM_NOT_ELIGIBLE`. On filing, the server stamps the filing shipper's identity onto the claim's `filed_by_user_id`, sets the claim's `status` to `FILED`, and snapshots the eligible payout into `claimed_value_cents` (the pre-cap eligible figure described below); the claim's `approved_payout_cents` is 0 at this point.

The eligible payout snapshot walks every product lot under the claim's shipment in a pinned order — compartments in `ordinal` ascending, and within each compartment its lots in `created_at` ascending. For each lot, the platform looks at that lot's compartment's final `degree_minutes_out` and derives a payout factor using the same boundaries as impairment classification: if the degree-minutes are at most the lane tolerance, the factor is 0.0 (the lot is sound); if they exceed the tolerance but are at most the tolerance plus 90 degree-minutes, the factor is 0.5 (impaired); otherwise the factor is 1.0 (spoiled). Each lot's eligible payout is its `declared_value_cents` multiplied by its factor, rounded half up to whole cents per lot. The lots' per-lot payouts are then summed in that pinned walk order to give `claimed_value_cents`. Rounding is applied per lot before the summation, not to the total.

A `ComplianceOfficer` adjudicates the claim. Opening review moves it `FILED → UNDER_REVIEW` and locks it from shipper withdrawal. From `UNDER_REVIEW` the officer may approve or deny. Approval is permitted only when the related shipment's `load_integrity_posture` is `AT_RISK` or `COMPROMISED`; on approval the platform sets `approved_payout_cents` to the lesser of the snapshotted `claimed_value_cents` and the carrier's `liability_cap_cents` (the cap can only shrink the figure, never raise it), moves the claim `UNDER_REVIEW → APPROVED`, and sets each impaired or spoiled lot's `spoilage_status` accordingly — `IMPAIRED` for a partially-impaired lot and `SPOILED` for a total-loss lot. Denial moves the claim `UNDER_REVIEW → DENIED` and leaves `approved_payout_cents` at 0. A shipper may withdraw a claim only while it is still `FILED` (not after review has opened) and only when the caller's `X-User-ID` matches the claim's `filed_by_user_id`; withdrawal moves it `FILED → WITHDRAWN` and is terminal with no payout. The claim's `status` therefore traverses `FILED → UNDER_REVIEW → APPROVED`, `FILED → UNDER_REVIEW → DENIED`, or `FILED → WITHDRAWN`.

### 3.9. Loading Stops, Detention, and Lumper Fees

A shipment's pickup and delivery appointments are modeled as stop events. A stop is scheduled by naming its `kind` (`PICKUP` or `DELIVERY`, which governs which fees apply) and its `appointment_min` — the scheduled appointment as a minute offset from the `IN_TRANSIT` start. The scheduler may also supply `pallets_handled` (defaulting to 0) and `compartments_touched` (defaulting to 1), though these can also be supplied later when the stop closes. Each stop names its owning `shipment_id`, begins with `status` `SCHEDULED`, and has both its fee fields at 0.

Scheduling enforces a window-separation rule. A candidate stop occupies a closed service window running from its `appointment_min` to its `appointment_min` plus a fixed service duration of 60 minutes. Each existing non-closed stop on the same shipment occupies an equivalent 60-minute window from its own appointment. The new window collides with an existing window unless they are cleanly separated by at least a 30-minute buffer — concretely, the candidate is allowed only when the candidate window's end plus 30 minutes is at most the existing window's start, or the existing window's end plus 30 minutes is at most the candidate window's start. Any closer spacing — including windows that merely touch, or that sit within the 30-minute buffer of each other — collides and is rejected with `ERR_STOP_WINDOW_OVERLAP`. Only non-closed stops are considered as obstacles.

A driver works a stop in two steps. Arrival is recorded from `SCHEDULED` while the shipment is `IN_TRANSIT`, supplying an `arrived_min` of at least 0, which moves the stop `SCHEDULED → ARRIVED`. Closing is recorded from `ARRIVED`, supplying a `departed_min` that must be at least the `arrived_min` (a `departed_min` earlier than `arrived_min` is rejected with `ERR_INVALID_INTERVAL`), and optionally refreshing `pallets_handled` and `compartments_touched`; closing moves the stop `ARRIVED → CLOSED`.

Closing a stop computes its two fees. The **detention fee** is tiered on dwell time. The dwell is `departed_min` minus `arrived_min`; the billable minutes are the dwell minus a free allowance of 120 minutes (never less than 0). Those billable minutes are converted to billable hours by rounding up to the next whole hour — any started hour is billed in full. The first 4 billable hours are tier-one hours billed at 5,000 cents each; every billable hour beyond the first 4 is a tier-two hour billed at 7,500 cents each. The stop's `detention_fee_cents` is the tier-one hours times 5,000 plus the tier-two hours times 7,500. The **lumper fee** is a base of 7,500 cents, plus 350 cents for each of the stop's `pallets_handled`, plus a multi-temp surcharge of 2,500 cents for each compartment beyond the first that was accessed — that is, the surcharge applies to `compartments_touched` minus 1 when that is positive, and contributes nothing when only a single compartment was touched. The stop's `lumper_fee_cents` is that sum. After both fees are computed, the shipment's `total_detention_fee_cents` and `total_lumper_fee_cents` are recomputed as the respective sums over all of the shipment's closed stops, as described in Section 2.11.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify, transition, retire, or read an existing resource return a `200 OK` status code. All endpoints require the `X-User-ID` and `X-User-Role` headers and honor the role authorizations below; request bodies, computed responses, and side effects are described in the Section 3 narratives rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/carriers` | Register a carrier | Carrier, PlatformAdmin |
| GET    | `/carriers/{id}` | Fetch a carrier | Carrier, Shipper, ComplianceOfficer, PlatformAdmin |
| PATCH  | `/carriers/{id}` | Update carrier compliance flags and liability cap | Carrier, PlatformAdmin |
| GET    | `/carriers` | List carriers | Carrier, Shipper, ComplianceOfficer, PlatformAdmin |
| POST   | `/reefer-units` | Register a reefer unit under a carrier | Carrier, PlatformAdmin |
| GET    | `/reefer-units/{id}` | Fetch a reefer unit | Carrier, ComplianceOfficer, PlatformAdmin |
| GET    | `/reefer-units` | List reefer units (filter by `carrier_id`, `status`) | Carrier, ComplianceOfficer, PlatformAdmin |
| PATCH  | `/reefer-units/{id}` | Document a washout/sanitation timestamp | Carrier, PlatformAdmin |
| DELETE | `/reefer-units/{id}` | Retire an AVAILABLE reefer unit | Carrier, PlatformAdmin |
| POST   | `/temp-lanes` | Create a temperature lane / set-point band | PlatformAdmin |
| GET    | `/temp-lanes/{id}` | Fetch a temp lane | Carrier, Shipper, ComplianceOfficer, PlatformAdmin |
| GET    | `/temp-lanes` | List temp lanes (filter by `regulated`) | Carrier, Shipper, ComplianceOfficer, PlatformAdmin |
| POST   | `/shipments` | Tender a new shipment | Shipper, PlatformAdmin |
| GET    | `/shipments/{id}` | Fetch a shipment with computed posture and fee totals | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| GET    | `/shipments` | List shipments (filter by `carrier_id`, `reefer_unit_id`, `shipper_user_id`, `status`) | Shipper, Carrier, ComplianceOfficer, PlatformAdmin |
| POST   | `/shipments/{id}/accept` | Carrier accepts the tender onto a named unit (OCC) | Carrier |
| POST   | `/shipments/{id}/reject` | Carrier rejects the tender | Carrier |
| POST   | `/shipments/{id}/precool-verify` | Verify all compartments precooled within band | Carrier |
| POST   | `/shipments/{id}/dispatch` | Dispatch the load through the compliance gates | Carrier |
| POST   | `/shipments/{id}/deliver` | Mark delivered; finalize integrity; release unit | Driver |
| POST   | `/shipments/{id}/cancel` | Shipper cancels before dispatch | Shipper |
| GET    | `/shipments/{id}/integrity-report` | Computed integrity score and breakdown | Shipper, Carrier, ComplianceOfficer, PlatformAdmin |
| POST   | `/shipments/{id}/compartments` | Add a compartment bound to a temp lane | Shipper, PlatformAdmin |
| GET    | `/compartments/{cid}` | Fetch a compartment with computed degree-minutes and impairment | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| GET    | `/compartments` | List compartments (filter by `shipment_id`, `temp_lane_id`, `impairment`) | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| GET    | `/compartments/{cid}/excursion-report` | Provisional degree-minutes at the current clock | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| POST   | `/compartments/{cid}/readings` | Append a sensor reading | Driver, Carrier |
| GET    | `/sensor-readings/{id}` | Fetch a single sensor reading | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| GET    | `/sensor-readings` | List sensor readings (filter by `compartment_id`, `kind`) | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| POST   | `/compartments/{cid}/lots` | Add a product lot to a compartment | Shipper, PlatformAdmin |
| GET    | `/product-lots/{id}` | Fetch a single product lot | Shipper, Carrier, ComplianceOfficer, PlatformAdmin |
| GET    | `/product-lots` | List product lots (filter by `compartment_id`) | Shipper, Carrier, ComplianceOfficer, PlatformAdmin |
| POST   | `/shipments/{id}/stops` | Schedule a pickup/delivery stop | Shipper, Carrier, PlatformAdmin |
| GET    | `/stops/{stopId}` | Fetch a single stop event | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| GET    | `/stops` | List stop events (filter by `shipment_id`, `kind`, `status`) | Shipper, Carrier, Driver, ComplianceOfficer, PlatformAdmin |
| POST   | `/shipments/{id}/stops/{stopId}/arrive` | Record arrival at a stop | Driver |
| POST   | `/shipments/{id}/stops/{stopId}/close` | Close a stop; compute detention and lumper fees | Driver |
| POST   | `/spoilage-claims` | File a spoilage claim against a delivered shipment | Shipper |
| GET    | `/spoilage-claims/{id}` | Fetch a spoilage claim | Shipper, Carrier, ComplianceOfficer, PlatformAdmin |
| GET    | `/spoilage-claims` | List spoilage claims (filter by `shipment_id`, `status`) | Shipper, Carrier, ComplianceOfficer, PlatformAdmin |
| POST   | `/spoilage-claims/{id}/review` | Open review on a claim | ComplianceOfficer |
| POST   | `/spoilage-claims/{id}/approve` | Approve a claim; apply liability cap | ComplianceOfficer |
| POST   | `/spoilage-claims/{id}/deny` | Deny a claim | ComplianceOfficer |
| POST   | `/spoilage-claims/{id}/withdraw` | Shipper withdraws a filed claim | Shipper |
| POST   | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_UNIT_TOO_SMALL` | 422 |
| `ERR_DUPLICATE_ORDINAL` | 422 |
| `ERR_PRECOOL_INCOMPLETE` | 422 |
| `ERR_FSMA_NOT_REGISTERED` | 422 |
| `ERR_SANITARY_TRAINING_LAPSED` | 422 |
| `ERR_SANITATION_UNDOCUMENTED` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_CLAIM_NOT_ELIGIBLE` | 422 |
| `ERR_READING_SHAPE` | 422 |
| `ERR_STOP_WINDOW_OVERLAP` | 409 |
| `ERR_READING_OFFSET_DUPLICATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_ASSET_TAG` | 422 |

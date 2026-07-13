# Airport Ground-Transport TNC API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Airport Ground-Transportation & TNC Permitting API, the regulatory backbone through which an airport authority licenses and polices the commercial ground-transport companies that serve its terminals. The system governs the full compliance arc of a fleet: an operator is registered and activated, its vehicles are permitted and decaled, those vehicles stage in geofenced holding lots and advance through a first-in-first-out queue before being dispatched to pick up passengers or reposition, and every completed trip accrues a fee that is eventually swept into a monthly settlement statement. Interwoven with this operational flow is an enforcement regime — staging, curb, transponder, and decal violations are cited, adjudicated, and scored, and an operator whose recent penalty burden crosses a threshold is automatically suspended, cascading that suspension down through its vehicles, permits, and in-flight trips.

The API serves three constituencies with distinct authority. The airport regulator both administers the credentialing lifecycle and adjudicates violations; the ground-transport operators run their own fleets and settle their own accounts; and curb-operations staff allocate scarce curb-frontage capacity across competing pickups. Because settlement is money-bearing and suspension is punitive, the system treats accounting precision, deterministic queue ordering, and consistent cascade behavior as first-class correctness concerns rather than incidental details. A separate wheelchair-accessibility mandate holds each operator to a self-pledged minimum share of accessible trips, checked at the close of every settlement period.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint of the API. Individual business workflows in Section 3 assume and build upon everything established here.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. If either header is absent, or if `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation — or an operator attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles:

- `AirportAuthority` — the airport ground-transport regulator. When `X-User-Role` is `AirportAuthority`, `X-User-ID` is an opaque administrative identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. This role registers operators, issues and manages permits, defines staging lots and curb zones, cites and adjudicates violations, opens and closes settlements, and drives the logical clock.
- `Operator` — a registered ground-transport company acting on its own fleet. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator`; ownership checks on any resource that references an operator (directly through an `operator_id`, or indirectly through a `vehicle_id` whose vehicle carries an `operator_id`, or through a `trip_id` or `violation_id` or settlement whose owning operator can be resolved) compare that owning operator to `X-User-ID`. An operator registering a vehicle must supply an `operator_id` equal to its own `X-User-ID`; an operator queuing, dispatching, or driving a trip must own the vehicle involved; an operator appealing, paying, or settling must own the underlying resource's operator.
- `CurbCoordinator` — ground-side curb-operations staff. When `X-User-Role` is `CurbCoordinator`, `X-User-ID` is an opaque operational identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. This role's sole write capability is allocating curb assignments.

All three roles may call every read (GET) endpoint. Write authority is otherwise partitioned as described above and enumerated in the Section 4 table.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and its minimum is 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

All persisted resources carry a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits. Every resource in this system additionally carries an `updated_at` timestamp — refreshed to the current logical-clock instant on any mutation of the resource — and an integer `version` that starts at 1 on creation and increments by one on every subsequent mutation. Whenever a resource's derived or computed fields are recomputed as a side effect of some operation (for example, an operator's penalty totals or outstanding-fee balance), that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the affected resource.

Identifiers appearing in a request path, and every foreign-key reference carried in a request body, are resolved left to right; the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier or business rule is evaluated.

### 2.5. The Logical Clock and Temporal Semantics

The system runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly moved it never advances on its own and never falls back to real time. An administrative test-driving capability sets the clock to an absolute UTC instant supplied as `to_iso8601`, which may move the clock forward or backward. Every timestamp the system records for itself — a queue entry's `enter_ts` and `exit_ts`, a trip's `dispatch_ts`, `pickup_ts`, and `complete_ts`, a violation's `assessed_at`, and a statement's `closed_at` and `settled_at` — is stamped from this logical clock at the moment of the corresponding event. All temporal comparisons in the business rules (rolling penalty windows, appeal windows, staging cooldowns, permit validity windows, settlement period boundaries) are evaluated against the logical clock.

### 2.6. Cascade Consistency Across the Credential Hierarchy

Operators, vehicles, permits, and trips form a suspension hierarchy that the system keeps internally consistent without requiring the client to touch each affected resource. When an operator leaves `ACTIVE` status through suspension or revocation, every one of its vehicles then in `ACTIVE` status is driven to `SUSPENDED`; each such vehicle in turn drives every one of its permits then in `permit_status` `ACTIVE` to `SUSPENDED` (recording `suspended_reason` `OPERATOR_SUSPENDED` on the permit), and drives every one of its trips then in `DISPATCHED` or `PICKED_UP` status to `CANCELLED`; and each cancelled trip releases any of its curb assignments still in `ACTIVE` status, moving them to `RELEASED`. Every resource touched along this cascade is a mutation and independently refreshes its `updated_at` and increments its `version`.

Reinstatement reverses the credential portion of the cascade but not the operational portion. When a suspended operator is reinstated to `ACTIVE`, its vehicles that were suspended return to `ACTIVE`, and the permits that were suspended with reason `OPERATOR_SUSPENDED` return to `permit_status` `ACTIVE` with their `suspended_reason` cleared to null — but trips that were cancelled by the suspension are never restored, and released curb assignments are never reactivated.

### 2.7. Optimistic Concurrency on Permit Issuance

Issuing a permit is guarded by an optimistic-concurrency check against the target vehicle. A request to the permit-issuance endpoint (a POST to the `/v1/permits` collection) must include a non-optional `expected_vehicle_version` field carrying the client's last observed `version` of the target `Vehicle`. If that value does not equal the vehicle's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a successful permit issuance increments the owning vehicle's `version` by one, a client whose view of the vehicle has gone stale — because another issuance has already advanced the vehicle's `version` since it last read the vehicle — is rejected on this check rather than silently minting a second, superseding credential against a vehicle it has not re-observed. No other endpoint takes a version field or performs this check.

### 2.8. Monetary Precision and Rounding

All money in the system is carried as an integer number of cents; there are no fractional-cent values in storage or in responses. Rounding, where a rule calls for it, uses the round-half-up convention (a value exactly at the half rounds away from zero, upward). Two calculations round: the per-trip fee rounds the product of the base fare and its peak multiplier once, and the settlement statement rounds the administrative fee once on the aggregated gross. Per-trip rounding of the administrative fee is explicitly forbidden — the administrative fee is computed by summing the exact integer trip fees first and rounding only the single aggregate product. Counts (trip counts, penalty points, queue positions) are exact integers and are never rounded.

## 3. Business Logic & Workflows

### 3.1. Operator Registration, Activation, and the Suspension Cycle

The regulator registers a ground-transport company by supplying its `legal_name`, its `operator_type` — one of `TNC`, `TAXI`, `LIMO`, or `SHUTTLE`, which selects the base trip fare — and a billing `contact_email`. An optional `wheelchair_pledge_pct` records the minimum fraction of the operator's monthly trips that the operator commits to serving with wheelchair-accessible vehicles, a value between 0.0 and 1.0 that defaults to 0.0 when omitted. A freshly registered operator begins in `PENDING` status with `suspended_reason` null. Its three computed accounting fields — `rolling_penalty_points`, `lifetime_penalty_points`, and `outstanding_fees_cents` — begin at zero and are recomputed on demand whenever the operator is read.

The regulator moves an operator from `PENDING` to `ACTIVE` by activating it. From `ACTIVE`, an operator may be administratively suspended (transitioning `ACTIVE → SUSPENDED` and setting `suspended_reason` to `ADMIN`), revoked (transitioning `ACTIVE → REVOKED`), or reinstated after suspension (`SUSPENDED → ACTIVE`). A suspended operator may also be revoked directly (`SUSPENDED → REVOKED`). `REVOKED` is terminal. The `SUSPENDED ↔ ACTIVE` pair forms the one cycle in the operator lifecycle. A suspension request — whether administrative, revocation, or reinstatement — is optionally accompanied by a `reason` note. Both an administrative suspension and a revocation trigger the downward cascade over vehicles, permits, trips, and curb assignments described in §2.6; a reinstatement triggers the credential-restoring reverse cascade, clearing `suspended_reason` back to null on the operator. Any transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

Suspension also arrives automatically through the enforcement path. When a violation assessment (or an appeal upheld against the operator) drives the operator's `rolling_penalty_points` to at least the suspension threshold of twelve points, and the operator is at that moment `ACTIVE`, the system suspends it on the spot, this time recording `suspended_reason` as `PENALTY_THRESHOLD`, and runs the same downward cascade as an administrative suspension. The rolling total, not the lifetime total, is authoritative for this automatic suspension.

### 3.2. Vehicles, Permits, and the Decal Lifecycle

An operator registers a vehicle into its own fleet by supplying the owning `operator_id`, the `plate` string, and an optional `is_wheelchair_accessible` flag that defaults to false and marks the vehicle as a wheelchair-accessible vehicle. A new vehicle starts in `ACTIVE` status; a vehicle's status is only ever `ACTIVE` or `SUSPENDED`, and it is toggled solely by the operator suspension and reinstatement cascade — there is no direct vehicle-status endpoint. Vehicles carry the standard `version`, which the permit-issuance concurrency check in §2.7 reads.

The regulator issues an operating permit for a vehicle by supplying the covered `vehicle_id`, the transponder's `avi_tag_id`, the validity window bounds `valid_from` and `valid_until` (ISO 8601 UTC instants), the issuance fee `fee_paid_cents`, and the `expected_vehicle_version` demanded by the concurrency guard. A newly issued permit begins in `permit_status` `ISSUED` with a null `decal_number` and null `suspended_reason`; the act of issuance increments the owning vehicle's `version` by one. The `avi_tag_id` must be globally unique across live permits: if the supplied tag is already held by another permit whose `permit_status` is `ISSUED`, `ACTIVE`, or `SUSPENDED`, the issuance is rejected with `ERR_DUPLICATE_AVI_TAG`. On the issuance endpoint the stale-version check is evaluated before the duplicate-tag check.

A permit walks its own lifecycle under the regulator's control. Activating an `ISSUED` permit (`ISSUED → ACTIVE`) is permitted only while the logical clock lies within the validity window — at or after `valid_from` and strictly before `valid_until` — and, on success, mints and assigns the physical `decal_number` serial. An `ACTIVE` permit may be renewed in place (`ACTIVE → ACTIVE`), which extends `valid_until` to a newly supplied `valid_until` value. An `ACTIVE` permit may be expired (`ACTIVE → EXPIRED`), and an `ISSUED` permit may be revoked (`ISSUED → REVOKED`); both `EXPIRED` and `REVOKED` are terminal. Separately from these operator-driven transitions, the vehicle-suspension cascade drives an `ACTIVE` permit to `SUSPENDED` (setting `suspended_reason` to `OPERATOR_SUSPENDED`) and the reinstatement cascade drives it back to `ACTIVE` (clearing `suspended_reason` to null). An action requested from an incompatible permit state is rejected with `ERR_INVALID_STATE`.

### 3.3. Staging Lots and the FIFO Queue

The regulator defines a geofenced staging lot with a human `name`, a geofence center given as `geofence_center_lat` and `geofence_center_lng` in decimal degrees, a `geofence_radius_m` in meters, and a `capacity` bounding how many entries may wait in the lot at once. A curb zone, by contrast, is defined with a `name`, a `terminal` identifier, and its own `capacity` (see §3.5).

An operator's vehicle joins a lot's queue by supplying the target `staging_lot_id`, the joining `vehicle_id`, and the vehicle's current location as `lat` and `lng`. A successful join creates a queue entry in `WAITING` status, stamps its `enter_ts` from the logical clock, and appends it to the tail of the lot's queue: its `position` is set to one more than the current count of `WAITING` entries in that lot, so positions form a contiguous block from 1 (the head) to N. When an entry leaves `WAITING` — whether it is released by a dispatch, exited, or cancelled — its `exit_ts` is stamped and every surviving `WAITING` entry in the same lot whose `position` is greater than the departed entry's decrements its `position` by one, keeping the remaining positions a contiguous block. Queue ordering is governed strictly by `position` (equivalently, ascending `enter_ts` with `created_at` as the tie-break); the UUID `id` is never used to order the queue.

Joining a queue passes a sequence of guards, evaluated in this order after authentication, body validation, and existence resolution. First, the joining vehicle must itself be `ACTIVE` — a vehicle suspended through the operator cascade is rejected with `ERR_VEHICLE_NOT_ACTIVE` (this vehicle-status check runs before the permit check, because a suspended vehicle necessarily also has a suspended permit). Second, the vehicle must currently hold a permit in `permit_status` `ACTIVE`; otherwise the join is rejected with `ERR_VEHICLE_PERMIT_INVALID`. Third, the supplied `lat`/`lng` must fall within `geofence_radius_m` meters of the lot's geofence center, or the join is rejected with `ERR_GEOFENCE_VIOLATION`. Fourth, the vehicle must not already have a `WAITING` entry in any lot, or the join is rejected with `ERR_ALREADY_IN_QUEUE`. Fifth, a staging cooldown applies: the logical clock must be at least 30 minutes past the `exit_ts` of the vehicle's most recent prior queue entry across the `RELEASED`, `EXITED`, and `CANCELLED` statuses, or the join is rejected with `ERR_STAGING_BUFFER_VIOLATION`. Finally, the lot must have room — the count of `WAITING` entries already in the lot must be below its `capacity`, or the join is rejected with `ERR_LOT_CAPACITY_EXCEEDED`.

An operator may withdraw one of its own waiting entries by cancelling it (`WAITING → CANCELLED`) or exiting it (`WAITING → EXITED`); either action stamps `exit_ts` and renumbers the positions behind it as described above. A queue entry may also reach `RELEASED` when the vehicle at the head is dispatched. Cancel, exit, or any transition from a non-`WAITING` state that does not permit the requested action is rejected with `ERR_INVALID_STATE`.

### 3.4. Dispatch and the Trip Lifecycle

An operator dispatches its head-of-queue vehicle by supplying the `vehicle_id` and the `staging_lot_id` it is staged in, together with an optional `trip_kind` — either `PICKUP` for a fare pickup or `DEADHEAD` for a repositioning move, defaulting to `PICKUP` — and an optional `is_wheelchair_trip` flag defaulting to false. Dispatch creates a trip in `DISPATCHED` status, copies the `operator_id` from the dispatched vehicle, stamps `dispatch_ts` from the logical clock, computes and stores the provisional fee in `provisional_fee_cents`, and releases the vehicle's head queue entry (`WAITING → RELEASED`) with the consequent FIFO renumber. The trip's `final_fee_cents`, `pickup_ts`, `complete_ts`, and `settlement_statement_id` are all null at this point.

Dispatch is guarded, after authentication, body validation, and existence resolution, in this order: the vehicle must be `ACTIVE` (else `ERR_VEHICLE_NOT_ACTIVE`); then the owning operator must be `ACTIVE` (else `ERR_OPERATOR_NOT_ACTIVE`); then the vehicle must hold an `ACTIVE` permit (else `ERR_VEHICLE_PERMIT_INVALID`); and finally the vehicle's `WAITING` queue entry must be at `position` 1, the head of its lot (else `ERR_NOT_QUEUE_HEAD`).

Once dispatched, a trip is driven by its operator. Picking up (`DISPATCHED → PICKED_UP`) stamps `pickup_ts` from the logical clock. Completing (`PICKED_UP → COMPLETED`) stamps `complete_ts`, computes and locks `final_fee_cents` using the final fee variant anchored on `pickup_ts`, adds that final fee into the operator's `outstanding_fees_cents`, and releases any of the trip's curb assignments still in `ACTIVE` status to `RELEASED`. An operator may cancel a still-dispatched trip (`DISPATCHED → CANCELLED`), which likewise releases any `ACTIVE` curb assignment of that trip. The system-driven cancellation caused by a vehicle suspension can strike a trip in either `DISPATCHED` or `PICKED_UP`, driving it to `CANCELLED` and releasing its `ACTIVE` curb assignments the same way. Separately, the regulator may void an already-`COMPLETED` trip (`COMPLETED → VOIDED`), but only while the trip has not yet been swept into a statement — that is, only while its `settlement_statement_id` is null; a void attempted on a swept trip is rejected with `ERR_TRIP_ALREADY_SETTLED`. Voiding compensates the ledger by recomputing the operator's `outstanding_fees_cents` to exclude that trip's final fee. `COMPLETED`, `CANCELLED`, and `VOIDED` are the terminal trip states; any action requested from an incompatible trip state is rejected with `ERR_INVALID_STATE`.

### 3.5. Trip-Fee Accounting: Provisional and Final

Every trip's fee is computed twice against the same tiered pricing rule, differing only in which timestamp anchors the calculation. The provisional variant runs at dispatch and is stored in `provisional_fee_cents`, taking its reference instant from `dispatch_ts`; the final variant runs at completion and is stored in `final_fee_cents`, taking its reference instant from `pickup_ts`. Because the actual pickup hour can cross a peak boundary the dispatch hour did not, the final fee can differ from the provisional fee for otherwise identical trip inputs.

The fee is derived as follows. A `DEADHEAD` trip is charged a flat 100 cents regardless of any other factor. A `PICKUP` trip starts from a base fare selected by the operator's `operator_type` — 350 cents for `TNC`, 300 cents for `TAXI`, 500 cents for `LIMO`, and 200 cents for `SHUTTLE`. That base is multiplied by a peak multiplier of 1.5 when the whole-hour UTC hour of the reference instant is one of 07, 08, 09, 16, 17, or 18, and by 1.0 in every other hour; the product of base and multiplier is rounded half-up to a whole number of cents. If the trip served a wheelchair passenger (`is_wheelchair_trip` true), a wheelchair discount of 100 cents is then subtracted from that rounded gross; otherwise nothing is subtracted. The resulting fee is finally raised, if necessary, to a floor of 200 cents — the fee charged is the greater of 200 cents and the discounted gross. The single rounding step is applied to base-times-multiplier before the wheelchair discount is subtracted; no other rounding occurs. Note the discount and floor apply only to the `PICKUP` path — a `DEADHEAD` trip is always exactly 100 cents.

### 3.6. Curb Zones and Assignments

Curb frontage is a shared, capacity-limited resource. A curb coordinator assigns a trip to a curb zone by supplying the `curb_zone_id`, the `trip_id` picking up there, and the occupation window as `start_ts` (inclusive) and `end_ts` (exclusive) — a half-open interval. A new assignment is created in `ACTIVE` status. Two guards apply, in order after existence resolution: the referenced trip must be operationally live, in `DISPATCHED` or `PICKED_UP` status (else `ERR_TRIP_NOT_ACTIVE`); and the zone must have room at the requested time — the number of `ACTIVE` assignments on that zone whose `[start_ts, end_ts)` half-open interval overlaps the requested `[start_ts, end_ts)` window must be strictly below the zone's `capacity`, or the assignment is rejected with `ERR_CURB_CONFLICT`. Because the interval is half-open, an existing assignment ending exactly when a new one begins does not count as an overlap.

An assignment leaves `ACTIVE` for `RELEASED` only as a side effect of the trip it belongs to — when that trip completes, is cancelled by its operator, or is cancelled by the vehicle-suspension cascade. There is no direct release endpoint.

### 3.7. Violations, Adjudication, and Penalty Scoring

The regulator cites an operator by issuing a violation that names the cited `operator_id`, a `violation_type` — one of `STAGING`, `CURB`, `AVI_MISMATCH`, `NO_DECAL`, or `WAV_SHORTFALL` — and an optional `trip_id` when the citation references a specific trip (null for operator-level citations). A manually issued citation carries `source` `MANUAL`; the settlement process can auto-issue a citation with `source` `SYSTEM` (see §3.8). On creation a violation is `OPEN` with a null `assessed_at`, and its `penalty_points` and `fine_cents` are looked up from the violation type rather than accepted from the request: the point schedule assigns 3 points to `STAGING`, 4 to `CURB`, 6 to `AVI_MISMATCH`, 6 to `NO_DECAL`, and 5 to `WAV_SHORTFALL`; the corresponding fine amounts are likewise fixed per type.

Adjudication is a branching workflow. The regulator assesses an `OPEN` violation (`OPEN → ASSESSED`), which stamps `assessed_at` from the logical clock, recomputes the cited operator's `rolling_penalty_points` and `lifetime_penalty_points`, and, if the operator was `ACTIVE` and its recomputed rolling total now stands at twelve points or more, auto-suspends the operator with `suspended_reason` `PENALTY_THRESHOLD` and its cascade. The regulator may instead dismiss an `OPEN` violation (`OPEN → DISMISSED`), which is terminal and affects no totals. An `ASSESSED` violation may be paid by the operator (`ASSESSED → PAID`) or waived by the regulator (`ASSESSED → WAIVED`); a waiver removes the violation from both the rolling and lifetime totals, recomputing the operator's points downward. The operator may appeal an `ASSESSED` violation (`ASSESSED → APPEALED`), but only while the logical clock is within 14 days of `assessed_at`; an appeal filed more than 14 days after assessment is rejected with `ERR_APPEAL_WINDOW_CLOSED`.

An appeal resolves into one of two divergent branches, and only one of them touches the operator's totals. If the regulator upholds the appeal outcome against the operator (`APPEALED → UPHELD`), the violation continues to count toward the rolling and lifetime totals exactly as before — no recomputation is needed. If the regulator overturns it (`APPEALED → OVERTURNED`), the violation stops counting and the operator's `rolling_penalty_points` and `lifetime_penalty_points` are recomputed downward; an operator already suspended is not automatically reinstated by an overturn. An `UPHELD` violation may subsequently be paid by the operator (`UPHELD → PAID`). `DISMISSED`, `PAID`, `OVERTURNED`, and `WAIVED` are terminal. Any adjudication action requested from an incompatible state is rejected with `ERR_INVALID_STATE`.

Penalty scoring itself walks every violation of the operator whose status is `ASSESSED` or `UPHELD`. Each such violation contributes its type's points to the lifetime total; it additionally contributes to the rolling total only if its `assessed_at` falls within the trailing 90-day window measured back from the current logical clock. The lifetime total therefore diverges from the rolling total once a counting violation ages past 90 days. These totals are recomputed on assessment, uphold, overturn, and waiver, and whenever an operator is read.

### 3.8. Monthly Settlement and the Wheelchair-Accessibility Mandate

The regulator opens a settlement statement for an operator and a period by supplying the `operator_id`, the `period_year`, and the `period_month` (1 through 12, UTC). A statement is created `OPEN` with all of its computed money and count fields — `gross_fees_cents`, `admin_fee_cents`, `wav_incentive_credit_cents`, `net_due_cents`, `total_trip_count`, `wav_trip_count` — at zero and its `closed_at` and `settled_at` null. At most one statement may exist per operator-year-month: a second open request for the same `operator_id`, `period_year`, and `period_month` is rejected with `ERR_DUPLICATE_SETTLEMENT_PERIOD`.

Closing the statement (`OPEN → CLOSED`) sweeps and accounts. The sweep selects the operator's trips that are `COMPLETED`, not yet attached to any statement (`settlement_statement_id` null), and whose `complete_ts` falls in the half-open month window running from the first instant of the period month (that year-month on the first day at `00:00:00Z`) up to but not including the first instant of the following month. Over the swept set the system computes `total_trip_count` as the number of swept trips, `wav_trip_count` as the number of those with `is_wheelchair_trip` true, `gross_fees_cents` as the exact integer sum of the swept trips' `final_fee_cents`, `admin_fee_cents` as the gross multiplied by the administrative rate of 0.025 and rounded half-up once on that aggregate product (never per trip), and `wav_incentive_credit_cents` as 50 cents times `wav_trip_count`. The amount owed, `net_due_cents`, is the gross plus the administrative fee minus the wheelchair incentive credit. Each swept trip has its `settlement_statement_id` set to this statement, which removes it from the operator's `outstanding_fees_cents`, and `closed_at` is stamped from the logical clock.

The wheelchair mandate is checked at close, immediately after the totals are known. If the operator ran no trips in the period (`total_trip_count` is zero), no shortfall can exist and nothing is issued. Otherwise the system compares the exact ratio of `wav_trip_count` to `total_trip_count` against the operator's `wheelchair_pledge_pct`; if that ratio is strictly less than the pledge, the system auto-issues a `WAV_SHORTFALL` violation against the operator with `source` `SYSTEM` in `OPEN` status. A ratio exactly equal to the pledge is compliant and issues nothing.

Settling a closed statement (`CLOSED → SETTLED`) is the operator's payment step: it must carry a `payment_amount_cents` exactly equal to the statement's `net_due_cents`, or it is rejected with `ERR_SETTLEMENT_AMOUNT_MISMATCH`. On success `settled_at` is stamped from the logical clock. `SETTLED` is terminal, and a close or settle requested from an incompatible statement state is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; state-transition operations and other modifications of an existing resource return `200 OK`, as does the clock-setting capability. Every read endpoint returns `200 OK` and is available to all three roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | AirportAuthority |
| POST | `/v1/operators` | Register a new ground-transport operator (starts PENDING) | AirportAuthority |
| GET | `/v1/operators/{operator_id}` | Fetch an operator with computed penalty points and outstanding fees | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/operators/{operator_id}/transitions` | ACTIVATE, SUSPEND, REINSTATE, or REVOKE the operator | AirportAuthority |
| POST | `/v1/vehicles` | Register a vehicle under an operator | Operator |
| GET | `/v1/vehicles/{vehicle_id}` | Fetch a vehicle | AirportAuthority, Operator, CurbCoordinator |
| GET | `/v1/vehicles` | List vehicles; filter by operator_id | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/permits` | Issue an operating permit for a vehicle (OCC on vehicle version) | AirportAuthority |
| GET | `/v1/permits/{permit_id}` | Fetch a permit | AirportAuthority, Operator, CurbCoordinator |
| GET | `/v1/permits` | List permits; filter by vehicle_id | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/permits/{permit_id}/transitions` | ACTIVATE, RENEW, EXPIRE, or REVOKE a permit | AirportAuthority |
| POST | `/v1/staging-lots` | Create a geofenced staging lot | AirportAuthority |
| POST | `/v1/queue-entries` | Join a staging lot's FIFO queue from inside the geofence | Operator |
| GET | `/v1/queue-entries/{queue_entry_id}` | Fetch a queue entry | AirportAuthority, Operator, CurbCoordinator |
| GET | `/v1/queue-entries` | List queue entries; filter by staging_lot_id, vehicle_id, status | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/queue-entries/{queue_entry_id}/transitions` | CANCEL or EXIT a WAITING queue entry | Operator |
| POST | `/v1/curb-zones` | Create a curb zone with an overlap capacity | AirportAuthority |
| POST | `/v1/curb-assignments` | Assign an active trip to a curb zone for a half-open window | CurbCoordinator |
| GET | `/v1/curb-assignments/{curb_assignment_id}` | Fetch a curb assignment | AirportAuthority, Operator, CurbCoordinator |
| GET | `/v1/curb-assignments` | List curb assignments; filter by curb_zone_id, trip_id, status | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/trips` | Dispatch the head-of-queue vehicle, creating a DISPATCHED trip | Operator |
| GET | `/v1/trips/{trip_id}` | Fetch a trip including provisional/final fees | AirportAuthority, Operator, CurbCoordinator |
| GET | `/v1/trips` | List trips; filter by operator_id, vehicle_id, settlement_statement_id, status | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/trips/{trip_id}/transitions` | PICKUP, COMPLETE, CANCEL (Operator) or VOID (AirportAuthority) | Operator, AirportAuthority |
| POST | `/v1/violations` | Issue a violation citation against an operator | AirportAuthority |
| GET | `/v1/violations/{violation_id}` | Fetch a violation | AirportAuthority, Operator, CurbCoordinator |
| GET | `/v1/violations` | List violations; filter by operator_id, trip_id, status | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/violations/{violation_id}/transitions` | ASSESS, DISMISS, UPHOLD, OVERTURN, WAIVE (AirportAuthority) or APPEAL, PAY (Operator) | AirportAuthority, Operator |
| POST | `/v1/settlements` | Open a monthly settlement statement for an operator+period | AirportAuthority |
| GET | `/v1/settlements/{settlement_id}` | Fetch a settlement statement with computed totals | AirportAuthority, Operator, CurbCoordinator |
| GET | `/v1/settlements` | List settlement statements; filter by operator_id | AirportAuthority, Operator, CurbCoordinator |
| POST | `/v1/settlements/{settlement_id}/transitions` | CLOSE (AirportAuthority) or SETTLE (Operator) | AirportAuthority, Operator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VEHICLE_PERMIT_INVALID` | 409 |
| `ERR_OPERATOR_NOT_ACTIVE` | 409 |
| `ERR_VEHICLE_NOT_ACTIVE` | 409 |
| `ERR_GEOFENCE_VIOLATION` | 422 |
| `ERR_ALREADY_IN_QUEUE` | 409 |
| `ERR_STAGING_BUFFER_VIOLATION` | 409 |
| `ERR_LOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_NOT_QUEUE_HEAD` | 409 |
| `ERR_TRIP_NOT_ACTIVE` | 409 |
| `ERR_CURB_CONFLICT` | 409 |
| `ERR_DUPLICATE_AVI_TAG` | 409 |
| `ERR_DUPLICATE_SETTLEMENT_PERIOD` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_TRIP_ALREADY_SETTLED` | 409 |
| `ERR_SETTLEMENT_AMOUNT_MISMATCH` | 402 |
</content>
</invoke>

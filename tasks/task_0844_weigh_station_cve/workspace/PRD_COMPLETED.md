# Weigh-Station & Commercial-Vehicle Enforcement API — Product Requirements Document

## 1. Introduction

Commercial-vehicle enforcement at a state weigh station is a compliance-audit problem wearing the clothes of a real-time operations problem. Every truck that rolls across a weigh-in-motion (WIM) sensor must be screened in a fraction of a second against its carrier's federal registration standing, its axle and gross weights, its hazardous-materials placarding, and the carrier's PRISM inspection-selection history — and then either waved through or pulled in for a physical inspection. This API is the system of record for that pipeline. It governs the motor carriers and their drivers, the weigh stations and their inspection bays, the screenings themselves, the CVSA-level inspections and the violations they surface, the out-of-service (OOS) orders that follow, the citations and fines that enforcement officers assess, and the PRISM/ISS scoring that feeds the next screening's decision.

The system is deliberately built around segregation of duties and cascading consistency. The officer who issues a citation may never be the one who adjudicates its contest; a single inspection finalized as out-of-service can ripple through a carrier's severity-point balance, flip the carrier into review or a federal out-of-service order, knock its driver out of service, and mint a fresh provisional score snapshot — all in one atomic operation. Fines are tracked to the cent, weights to the pound, and hours-of-service to the minute. Because the enforcement pipeline's outcomes feed back into future screening decisions, correctness of every intermediate balance is load-bearing, and this document specifies each rule with the precision the audit trail demands.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting enforcement principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `ComplianceAdmin`, `Screener`, `Inspector`, `EnforcementOfficer`, and `CarrierRep`. A request that omits either header, or that presents an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the targeted operation is rejected with `ERR_UNAUTHORIZED`.

Four of the five roles are opaque operator identities. When `X-User-Role` is `ComplianceAdmin`, `Screener`, `Inspector`, or `EnforcementOfficer`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The server does, however, record the operator identity where the workflow demands it — specifically, when an `EnforcementOfficer` issues a citation the server stores that officer's `X-User-ID` as the citation's `issued_by_user_id`, and when an officer adjudicates a contest the server stores the adjudicating officer's `X-User-ID` as `adjudicated_by_user_id`. These recorded identities drive the segregation-of-duties check described in §2.6 and §3.8.

The fifth role, `CarrierRep`, is entity-backed. When `X-User-Role` is `CarrierRep`, the `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any carrier-scoped resource compare that resource's carrier reference to `X-User-ID`. A `CarrierRep` who acts on a carrier, driver, or citation that does not belong to their own carrier is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, all list endpoints return resources sorted by their creation timestamp in ascending order; because the logical clock (§2.10) can leave many resources sharing an identical `created_at`, ties are broken by the order in which the server minted the resources (creation sequence), which is used as the stable total ordering. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on every mutation. Carriers, drivers, weigh stations, inspection bays, screenings, inspections, violations, citations, duty-log entries, and score snapshots all carry the full `id` / `created_at` / `updated_at` / `version` set.

When a derived field on a resource changes — for example when a carrier's `oos_points`, `iss_score`, `certified_iss_score`, `unpaid_fines_cents`, `prism_flagged`, `registration_hold`, or `status` is recomputed by a cascade — that recomputation is itself a mutation of the carrier: it refreshes the carrier's `updated_at` and increments its `version`. The same holds for a driver whose `hos_status`, `driving_minutes_window`, or `status` changes, and for an inspection bay whose `reserved_minutes` changes.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several endpoints address resources through nested paths that name a parent identifier before a child identifier or a body foreign key. The server validates existence left-to-right: the path parameters are checked in the order they appear, and only then are body-referenced foreign keys checked. The first identifier that resolves to nothing determines the error. A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation `ERR_CITATION_NOT_FOUND`. The list endpoints that hang off a parent — a carrier's drivers, a carrier's score snapshots, a station's bays, a driver's duty logs, an inspection's violations — exist so that a child can be reached from its parent; each honors the same left-to-right existence rule for the parent in its path.

### 2.6. Validation Precedence

When more than one rule could reject a request, the checks run in a fixed order, and the first failing check determines the error returned. The precedence, from first to last, is:

1. **Authentication** — headers present and `X-User-Role` is a known role; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the endpoint; otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence** — path-referenced and then body-referenced resources exist, validated left-to-right; otherwise the matching not-found error (404) from §2.5.
4. **Ownership** — a `CarrierRep` acting on a carrier-scoped resource must own it (`X-User-ID` equals the resource's carrier reference); otherwise `ERR_NOT_RESOURCE_OWNER` (403).
5. **Segregation of duties** — the officer adjudicating a contest must differ from the officer who issued the citation; otherwise `ERR_SOD_CONFLICT` (403).
6. **State** — the target resource is in a status that admits the requested transition; otherwise `ERR_SCREENING_NOT_REFERRED`, `ERR_INSPECTION_INVALID_STATE`, or `ERR_CITATION_INVALID_STATE` (409).
7. **Compliance basis** — the substantive basis for an out-of-service finalize, an overweight or hazmat citation, or a driving duty-log entry is present; otherwise `ERR_NO_OOS_BASIS`, `ERR_OVERWEIGHT_BASIS_MISSING`, `ERR_HAZMAT_BASIS_MISSING`, or `ERR_HOS_DRIVING_LIMIT` (422).
8. **Referential consistency** — a citation's carrier matches the carrier of its inspection's screening; otherwise `ERR_CARRIER_MISMATCH` (409).
9. **Temporal / interval** — bay-window, duty-log-overlap, and off-duty-buffer rules; otherwise `ERR_BAY_WINDOW_CONFLICT`, `ERR_HOS_RESET_REQUIRED`, or `ERR_DUTY_LOG_OVERLAP` (409).
10. **Field and constraint validity** — required fields, enum membership, ranges, USDOT uniqueness, and bay availability; otherwise `ERR_VALIDATION`, `ERR_DUPLICATE_USDOT`, or `ERR_BAY_UNAVAILABLE` (422 for the first, 409 for the latter two).
11. **Fiscal ceiling** — the fine cap at issuance and the settlement amount match; otherwise `ERR_FINE_CAP_EXCEEDED` or `ERR_SETTLEMENT_AMOUNT_MISMATCH` (422).
12. **Optimistic concurrency** — the carrier-version guard on certified score snapshots; otherwise `ERR_STALE_CARRIER_VERSION` (412).

A rule that sits lower in this list never masks a rule above it: for example, a request that would both fail the state check and the fiscal check surfaces the state error, because state precedes fiscal.

### 2.7. Cascading Consistency and the Enforcement Ledgers

The enforcement pipeline maintains several running balances on the carrier that are never set directly by clients; they are computed and adjusted as a side effect of inspection and citation activity, and every adjustment is immediately visible.

**Out-of-service severity points.** A carrier's `oos_points` is the accumulated severity of its out-of-service inspections, net of reinspection reversals. When an inspection is finalized as out-of-service, the sum of the `severity_weight` of that inspection's out-of-service violations is added to the carrier's `oos_points`, and that same amount is recorded on the inspection as `oos_points_applied` so it can be reversed later. When such an inspection is subsequently reinspected and cleared, exactly that recorded `oos_points_applied` amount is subtracted back from the carrier's `oos_points`, and the inspection's `oos_points_applied` is reset to zero.

**Unpaid fine balance.** A carrier's `unpaid_fines_cents` is the running total of assessed-but-unsettled citation fines, in integer cents. Issuing a citation adds its `assessed_fine_cents` to this balance; settling, dismissing, or reconciling a citation reduces or adjusts it as described in §3.7 and §3.8. Whenever this balance crosses `100000` cents (one thousand dollars) upward at issuance, the carrier's `registration_hold` flag is set to true.

**Inspection-selection score.** A carrier's provisional `iss_score` is recomputed whenever a violation is added to one of its inspections, whenever an inspection is finalized, and whenever an inspection is cancelled; its `certified_iss_score` is recomputed only when a certified score snapshot is run. The scoring formula and its two variants are specified in §3.6.

**Status propagation.** A carrier's `status` is a pure function of these balances against fixed thresholds. When the provisional `iss_score` reaches at least `10`, an `ACTIVE` carrier moves to `UNDER_REVIEW`. When `oos_points` reaches at least `20`, a carrier (whether `ACTIVE` or `UNDER_REVIEW`) moves to `OOS_ORDERED`. A certified snapshot that brings both `certified_iss_score` below `10` and `oos_points` below `20` returns an `UNDER_REVIEW` or `OOS_ORDERED` carrier to `ACTIVE`. These transitions are performed by the server itself as part of the triggering operation, never by an explicit client request on the carrier, and each such transition mutates the carrier (refreshing `updated_at`, incrementing `version`).

### 2.8. Monetary and Weight Precision

All monetary values in this system are integer cents; there are no fractional cents and therefore no rounding is applied to fines. Weights are integer pounds. The only place rounding occurs is in the inspection-selection score, whose per-inspection and averaged values are rounded to the nearest whole number using the round-half-up convention (a value exactly halfway between two integers rounds up); the exact ordering of those rounding steps is specified in §3.6 and is load-bearing.

### 2.9. Optimistic Concurrency Control on Certified Snapshots

Running a certified score snapshot for a carrier is the one operation guarded by optimistic concurrency control. The create request must carry `expected_carrier_version`, and its value must equal the carrier's current `version` at the moment the request is processed. If an intervening operation — for instance an inspection finalize that cascaded an `oos_points`, `iss_score`, or `version` bump onto the carrier — has advanced the carrier's `version` since the client last read it, the request is rejected with `ERR_STALE_CARRIER_VERSION` and HTTP status 412, preventing the client from computing a snapshot against a carrier view it has not actually observed. A certified snapshot legitimately supersedes the carrier's prior current snapshot and leaves the carrier's `status` otherwise governed by its balances, so the version guard is the sole mechanism that rejects a stale writer here. No other endpoint accepts or requires a version field.

### 2.10. Logical Clock

The server keeps a logical clock that supplies every `created_at`, `updated_at`, `computed_at`, and any other server timestamp. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly advanced it continues to read that default rather than any real wall-clock time. A `ComplianceAdmin` may advance the clock to a supplied instant, given as `to_iso8601`, through an administrative test-driving capability.

## 3. Business Logic & Workflows

### 3.1. Establishing Carriers, Drivers, Stations, and Bays

The enforcement domain is seeded by a `ComplianceAdmin`. Registering a motor carrier requires its `usdot_number`, its `legal_name`, and its three federal credential states — `irp_status` (apportioned registration), `ifta_status` (fuel-tax license), and `ucr_status` (unified carrier registration) — each of which is one of `ACTIVE`, `EXPIRED`, or `REVOKED`. The `usdot_number` must be unique across all carriers; a second registration reusing an existing number is rejected with `ERR_DUPLICATE_USDOT`. A freshly registered carrier begins in `status` `ACTIVE` with `oos_points`, `unpaid_fines_cents`, `iss_score`, and `certified_iss_score` all zero, `prism_flagged` and `registration_hold` both false, and `version` 1.

Drivers belong to a carrier. Registering a driver under a carrier — an action a `ComplianceAdmin` may perform for any carrier, and a `CarrierRep` may perform only for their own — takes the driver's `cdl_number` and `full_name`; the driver's `carrier_id` is taken from the path and need not be supplied in the body. A new driver starts `ACTIVE`, with `hos_status` `COMPLIANT` and `driving_minutes_window` zero.

Weigh stations are created by a `ComplianceAdmin` with a `name` and a two-letter `state_code`. Three limits may be supplied or left to their defaults: `gross_weight_limit_lbs` defaults to 80000, `single_axle_limit_lbs` defaults to 20000, and `iss_bypass_threshold` defaults to 50 (and, when supplied, must lie between 0 and 100 inclusive). The bypass threshold is the certified score at or above which a carrier is denied a WIM bypass at this station. Each station owns one or more inspection bays; creating a bay takes a `label` and an optional operational `status` that is one of `AVAILABLE` or `OUT_OF_ORDER` and defaults to `AVAILABLE`. A bay's `station_id` is taken from the path, and its `reserved_minutes` — the running sum of the scheduled-window minutes of the inspections currently occupying it — starts at zero.

### 3.2. Drivers, Duty Logs, and Hours-of-Service

A driver's hours-of-service standing is derived entirely from an append-only stream of duty-log entries. Each entry — posted by the driver's `CarrierRep` or by a `ComplianceAdmin` — carries an `entry_type` of `DRIVING`, `ON_DUTY`, `OFF_DUTY`, or `SLEEPER`, a `start_utc`, and an `end_utc` that must be strictly after `start_utc`. The entry's `driver_id` comes from the path. No two entries for the same driver may overlap in time; an overlapping entry is rejected with `ERR_DUTY_LOG_OVERLAP`. A new driving shift must be separated from the prior driving shift by an off-duty buffer of at least `600` minutes (ten hours); a driving entry that lacks that buffer is rejected with `ERR_HOS_RESET_REQUIRED`.

The system tracks `driving_minutes_window`, the cumulative count of `DRIVING` minutes since the end of the most recent qualifying reset (or since the driver's first entry if there has been no reset). A qualifying reset is an `OFF_DUTY` entry whose duration is at least `600` minutes. When a duty-log entry is posted, the prospective window is the prior `driving_minutes_window` plus the entry's duration if the entry is `DRIVING`, or the prior window unchanged for any other `entry_type`. If the entry is `DRIVING` and that prospective window would exceed `660` minutes (eleven hours), the entry is rejected with `ERR_HOS_DRIVING_LIMIT`, and as part of that rejection the driver's `hos_status` is set to `VIOLATION` and the driver transitions `ACTIVE → OOS`. The boundary is strict: a driving entry that brings the window to exactly `660` minutes is allowed. When an `OFF_DUTY` entry of at least `600` minutes is accepted, the driver's `driving_minutes_window` is reset to zero, `hos_status` returns to `COMPLIANT`, and a driver that was out of service transitions `OOS → ACTIVE`.

A driver can also be knocked out of service by an inspection rather than by their own logbook, as described in §3.5; the two paths into `OOS` are symmetric, and only a qualifying off-duty reset brings the driver back to `ACTIVE`.

### 3.3. WIM Screening and the Bypass / Pull-In Sort

A `Screener` records each weigh-in-motion screening. The submitted screening names the `station_id` performing the screening, the `carrier_id` and `driver_id` of the screened vehicle, its `vehicle_plate`, its `axle_count` (which must be at least 2), its WIM `gross_weight_lbs` and `heaviest_axle_lbs`, whether it is `hazmat_placarded`, and an optional `oversize` flag that defaults to false. At creation the server computes four derived fields and the screening's terminal-or-referred outcome in one shot.

The computed `overweight` flag is set to true when the screening's `gross_weight_lbs` is strictly greater than the station's `gross_weight_limit_lbs`, or its `heaviest_axle_lbs` is strictly greater than the station's `single_axle_limit_lbs`; a vehicle exactly at either limit is legal. Its `credentials_valid` flag is true only when all three of the carrier's `irp_status`, `ifta_status`, and `ucr_status` are `ACTIVE` at screening time.

The screening is pulled in — `decision` `PULL_IN`, `status` `REFERRED` — when any one of the following holds: the carrier's `status` is not `ACTIVE`; the carrier's `certified_iss_score` is at least the station's `iss_bypass_threshold`; the screening is overweight; the `oversize` flag is set; `credentials_valid` is false; or the vehicle is `hazmat_placarded`. If none of these holds, the screening bypasses — `decision` `BYPASS`, `status` `CLEARED`, `referral_reason` `NONE` — which additionally requires that the carrier be `ACTIVE` and its `certified_iss_score` be below the station's threshold (both already implied by the pull-in conditions). A carrier under a federal out-of-service order can therefore never bypass.

When a screening is pulled in, its `referral_reason` is set to the single highest-priority reason that applies, in this strict order: `PRISM_TARGET` if the carrier's `status` is not `ACTIVE` or its `certified_iss_score` is at least the threshold; otherwise `OVERWEIGHT` if overweight; otherwise `OVERSIZE` if the `oversize` flag is set; otherwise `CREDENTIAL` if `credentials_valid` is false; otherwise `HAZMAT` if `hazmat_placarded`. A bypassed screening records `referral_reason` `NONE`. A screening's `status` lives in `SCREENED` conceptually at the instant of computation and resolves immediately to `CLEARED` on bypass or `REFERRED` on pull-in; a referred screening later becomes `INSPECTED` when its inspection is finalized, and both `CLEARED` and `INSPECTED` are terminal.

### 3.4. Opening Inspections and Reserving Bay Windows

Only a `REFERRED` screening can be inspected. An `Inspector` opens an inspection by naming the `screening_id`, the `bay_id` that will host it, the CVSA `level` (one of `LEVEL_I`, `LEVEL_II`, or `LEVEL_III`), and the occupancy window `scheduled_start` and `scheduled_end` (which must be strictly after `scheduled_start`). Attempting to inspect a screening that is not in `REFERRED` status is rejected with `ERR_SCREENING_NOT_REFERRED`. The inspection copies its `driver_id` from the screening, starts in `status` `IN_PROGRESS` with `result` `NONE`, `oos_flag` false, `reinspection_count` zero, and `oos_points_applied` zero.

The chosen bay must be usable and free. A bay whose `status` is `OUT_OF_ORDER` cannot host an inspection and yields `ERR_BAY_UNAVAILABLE`. The requested window must not overlap any other active window already reserved on that same bay; overlap is judged on a half-open basis (two windows conflict when one starts strictly before the other ends and vice versa, so a window that begins exactly when another ends does not conflict), and a conflict is rejected with `ERR_BAY_WINDOW_CONFLICT`. When the inspection is opened, the bay's `reserved_minutes` is increased by the window's length in minutes (the difference between `scheduled_end` and `scheduled_start`). Releasing that reservation — on clear, out-of-service finalize, or cancellation — subtracts exactly the same window minutes back, so that an open-then-cancel or open-then-finalize pair leaves the bay's `reserved_minutes` unchanged from where it began.

An `Inspector` records each defect as a violation on an open inspection — one whose `status` is `IN_PROGRESS` or `REINSPECTION`; a violation posted against an inspection in any other status is rejected with `ERR_INSPECTION_INVALID_STATE` — supplying the FMCSA `code`, a `category` of `VEHICLE`, `DRIVER`, `HAZMAT`, `HOS`, `CREDENTIAL`, or `WEIGHT`, a `severity_weight` from 1 to 10 inclusive, an `oos` boolean marking whether the defect is itself out-of-service, and an optional free-text `description` that defaults to empty. Each recorded violation triggers a provisional recomputation of the carrier's inspection-selection score, and that recomputation propagates carrier status exactly as an inspection finalize does: if it lifts the provisional `iss_score` to at least `10`, an `ACTIVE` carrier moves to `UNDER_REVIEW`, its `prism_flagged` is set to true, and a provisional current snapshot is auto-created (superseding any prior current snapshot).

### 3.5. Finalizing Inspections, the OOS Cascade, and the Reinspection Cycle

An `Inspector` finalizes an open inspection by supplying a `result` of either `CLEAR` or `OOS`. Finalization is permitted only from `IN_PROGRESS` or, during a reinspection cycle, from `REINSPECTION`; an attempt from any other status is rejected with `ERR_INSPECTION_INVALID_STATE`.

**Clearing.** Finalizing with `result` `CLEAR` moves an `IN_PROGRESS` inspection to `CLEARED`, sets its `result` to `CLEAR`, releases the bay reservation, transitions the screening `REFERRED → INSPECTED`, and recomputes the carrier's provisional `iss_score`. If that recomputation is the event that first pushes an `ACTIVE` carrier into `UNDER_REVIEW`, a provisional current snapshot is auto-created as part of the same operation; otherwise no snapshot is minted on a clear.

**Out-of-service.** Finalizing with `result` `OOS` requires that the inspection already have at least one violation whose `oos` flag is true; with no such violation the finalize is rejected with `ERR_NO_OOS_BASIS`. When the basis exists, the inspection moves `IN_PROGRESS → OOS_ISSUED`, sets `result` `OOS` and `oos_flag` true, and drives the full cascade in order:

- The sum of the `severity_weight` of the inspection's out-of-service violations is added to the carrier's `oos_points`, and that amount is stored on the inspection as `oos_points_applied`.
- If any out-of-service violation has `category` `DRIVER` or `HOS`, the inspection's driver transitions `ACTIVE → OOS`.
- The bay reservation is released, and the screening transitions `REFERRED → INSPECTED`.
- The carrier's provisional `iss_score` is recomputed. If the recomputed score is at least `10`, an `ACTIVE` carrier moves to `UNDER_REVIEW`. If `oos_points` is at least `20`, the carrier moves to `OOS_ORDERED`.
- Whenever this operation drives the carrier into `UNDER_REVIEW`, the carrier's `prism_flagged` is set to true and a provisional current snapshot is auto-created: the new snapshot's `is_current` is true and the carrier's prior current snapshot has its `is_current` flipped to false. This carrier mutation increments the carrier's `version`.

Once a carrier reaches `OOS_ORDERED` it is federally out of service, and because its `status` is no longer `ACTIVE`, every subsequent screening for that carrier is pulled in with `referral_reason` `PRISM_TARGET`.

**Reinspection cycle.** An `OOS_ISSUED` inspection may be reopened by an `Inspector`, moving it `OOS_ISSUED → REINSPECTION`, incrementing its `reinspection_count`, and re-reserving the same bay window (the window must again be free, and the bay's `reserved_minutes` grows by the window minutes). From `REINSPECTION` the inspection can be finalized again. Finalizing a `REINSPECTION` as `CLEAR` moves it to `CLEARED`, and as compensation subtracts the inspection's recorded `oos_points_applied` back from the carrier's `oos_points` and then resets `oos_points_applied` to zero, releases the bay reservation, and recomputes the carrier's `iss_score`; if `oos_points` is now below `20` and `certified_iss_score` is below `10`, a carrier in `OOS_ORDERED` or `UNDER_REVIEW` may return to `ACTIVE` (this reinspection-clear return to `ACTIVE` leaves the carrier's `prism_flagged` unchanged; only a certified snapshot clears that flag). Finalizing a `REINSPECTION` as `OOS` again requires at least one out-of-service violation (else `ERR_NO_OOS_BASIS`), sets `result` `OOS` and `oos_flag` true, and releases the bay reservation — but does not re-add points already applied, since the original `oos_points_applied` remains booked.

**Cancellation.** An `IN_PROGRESS` inspection may instead be cancelled by an `Inspector`, moving it `IN_PROGRESS → CANCELLED` and releasing its bay reservation; the screening remains `REFERRED` so it can be inspected again. `CLEARED` and `CANCELLED` are the inspection's terminal states.

### 3.6. PRISM / ISS Scoring, Provisional and Certified

The inspection-selection (ISS) score summarizes a carrier's recent inspection history on a 0-to-100 scale, and it exists in two variants that differ only in which inspections they include. Both variants share the same arithmetic.

To score a carrier, gather the qualifying inspections for the variant, order them by `created_at` ascending — with inspections sharing a `created_at` ordered by the server's creation sequence — and take the most recent five (the last five in that ordering). If no inspection qualifies, the score is 0. Otherwise, for each included inspection compute a raw value equal to the sum of the `severity_weight` of that inspection's violations, multiplied by 1.5 when the inspection's `oos_flag` is true and by 1.0 otherwise; cap that raw value at 100; and round it to the nearest whole number using round-half-up. This per-inspection rounding happens first, before any averaging. Then sum the rounded per-inspection values, divide by the number of included inspections, and round that average to the nearest whole number using round-half-up. Finally clamp the result to the 0-to-100 range. The order of operations is fixed and load-bearing: rounding each inspection to an integer before averaging, then rounding the average, is not interchangeable with averaging the raw values and rounding once.

The **provisional** variant — which drives the carrier's live `iss_score` field and the auto-created snapshots — includes inspections whose `status` is `IN_PROGRESS`, `REINSPECTION`, `CLEARED`, or `OOS_ISSUED`, and excludes `CANCELLED` inspections. The **certified** variant — which drives a certified snapshot and the carrier's `certified_iss_score` — includes only finalized inspections, those whose `status` is `CLEARED` or `OOS_ISSUED`; a pending `IN_PROGRESS` inspection's violations are excluded, so the certified score can diverge from the provisional one.

A `ComplianceAdmin` runs a certified snapshot for a carrier (subject to the version guard of §2.9). The resulting `ScoreSnapshot` records `method` `CERTIFIED`, the computed `iss_score` under that method, the `inspection_count` of inspections that fed the score, `is_current` true, its `computed_at` from the logical clock, and its `carrier_id` from the path. Creating it flips the carrier's prior current snapshot's `is_current` to false, updates the carrier's `certified_iss_score`, may lift the carrier from `UNDER_REVIEW` or `OOS_ORDERED` back to `ACTIVE` when both `certified_iss_score` is below `10` and `oos_points` is below `20` (clearing `prism_flagged` to false in that case), and increments the carrier's `version` by one. Snapshots auto-created by an inspection finalize instead record `method` `PROVISIONAL`. Every snapshot carries `carrier_id`, `method`, `iss_score`, `inspection_count`, `is_current`, and `computed_at`.

### 3.7. Issuing Citations and Assessing Fines

An `EnforcementOfficer` issues a citation from a finalized inspection, supplying the `inspection_id`, the cited `carrier_id`, and the citation `kind` — one of `OVERWEIGHT`, `CREDENTIAL`, `HAZMAT`, `HOS`, or `EQUIPMENT`. The cited `carrier_id` must equal the carrier of the citation's inspection's screening; a mismatch is rejected with `ERR_CARRIER_MISMATCH`. Certain kinds require a substantive basis: an `OVERWEIGHT` citation requires that the inspection's screening was itself overweight, else `ERR_OVERWEIGHT_BASIS_MISSING`; a `HAZMAT` citation requires that the inspection carry at least one violation of `category` `HAZMAT`, else `ERR_HAZMAT_BASIS_MISSING`.

The citation's `assessed_fine_cents` is computed at issuance. For a `kind` of `CREDENTIAL`, `HAZMAT`, `HOS`, or `EQUIPMENT`, the fine is a flat amount by kind: `25000` cents for `CREDENTIAL`, `100000` cents for `HAZMAT`, `50000` cents for `HOS`, and `15000` cents for `EQUIPMENT`. For an `OVERWEIGHT` citation, the fine is computed from the screening's weigh-in-motion weights by a marginal, bracketed schedule. First determine two excess amounts: the gross excess is the screening's `gross_weight_lbs` minus the station's `gross_weight_limit_lbs`, floored at zero, and the axle excess is the screening's `heaviest_axle_lbs` minus the station's `single_axle_limit_lbs`, floored at zero. Convert an excess amount to cents by charging its first 2000 pounds at 10 cents per pound, the next 3000 pounds (that is, pounds 2001 through 5000) at 25 cents per pound, and every pound beyond 5000 at 50 cents per pound. Compute this bracketed charge separately for the gross excess and for the axle excess, and the `assessed_fine_cents` is the greater of the two. Because all inputs are integer pounds and integer rates, the result is exact integer cents.

Before the citation is created, the fine ceiling is checked: the carrier's current `unpaid_fines_cents` plus the new `assessed_fine_cents` must be strictly below `200000` cents (two thousand dollars). If that sum would reach or exceed the cap, issuance is rejected with `ERR_FINE_CAP_EXCEEDED`. On success the citation is created in `status` `ASSESSED`, its `issued_by_user_id` is set to the issuing officer's `X-User-ID`, its `final_fine_cents`, `certified_gross_lbs`, `certified_axle_lbs` all start at zero and its `adjudicated_by_user_id` and `contest_reason` empty, and the carrier's `unpaid_fines_cents` is increased by the `assessed_fine_cents`. If that increase crosses `100000` cents upward, the carrier's `registration_hold` becomes true.

### 3.8. Contesting, Adjudicating, and Settling Citations

A citation moves through a contest fork before it settles. A `CarrierRep` who owns the cited carrier may contest an `ASSESSED` citation, supplying a `contest_reason`; the citation moves `ASSESSED → CONTESTED`. A contest attempt against a citation that is not `ASSESSED` is rejected with `ERR_CITATION_INVALID_STATE`.

An `EnforcementOfficer` then adjudicates a `CONTESTED` citation, supplying a `result` of `UPHOLD` or `DISMISS`. Segregation of duties governs this step: the adjudicating officer's `X-User-ID` must differ from the citation's `issued_by_user_id`, and if they are the same the request is rejected with `ERR_SOD_CONFLICT`. On either outcome the adjudicating officer's `X-User-ID` is recorded as `adjudicated_by_user_id`. On `UPHOLD`, the officer records the certified static-scale weights `certified_gross_lbs` and `certified_axle_lbs`, and the `final_fine_cents` is recomputed: for an `OVERWEIGHT` citation it is the same bracketed overweight schedule of §3.7 applied to the certified weights (which, being from a static certified scale, are typically lower than the WIM weights and yield a smaller fine), and for any other kind it equals the already-assessed `assessed_fine_cents`. The carrier's `unpaid_fines_cents` is then reconciled by adding the difference between the new `final_fine_cents` and the original `assessed_fine_cents` (a negative difference lowers the balance), and the citation moves `CONTESTED → UPHELD`. On `DISMISS`, the `final_fine_cents` is set to zero, the carrier's `unpaid_fines_cents` is reduced by the original `assessed_fine_cents` as compensation, and the citation moves `CONTESTED → DISMISSED`. `DISMISSED` is terminal.

A `CarrierRep` who owns the carrier settles a citation by paying, supplying `payment_cents`. Settlement is allowed from `ASSESSED` (an uncontested citation) or from `UPHELD` (a contest that was upheld). For an `ASSESSED` citation the `payment_cents` must equal its `assessed_fine_cents`, and settlement records `final_fine_cents` equal to `assessed_fine_cents` and reduces the carrier's `unpaid_fines_cents` by that amount. For an `UPHELD` citation the `payment_cents` must equal its `final_fine_cents`, and settlement reduces the carrier's `unpaid_fines_cents` by that final amount. A payment that does not equal the outstanding fine is rejected with `ERR_SETTLEMENT_AMOUNT_MISMATCH`. A successful settlement moves the citation to `SETTLED`, which is terminal.

## 4. Endpoint Definitions

New, stand-alone resources and new members added to a parent collection return `201 Created`. Actions that transition or otherwise modify an existing resource, and the administrative clock capability, return `200 OK`. All list and get reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ComplianceAdmin |
| POST | `/carriers` | Register a motor carrier | ComplianceAdmin |
| GET | `/carriers` | List carriers (paginated) | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| GET | `/carriers/{carrierId}` | Get a carrier | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/carriers/{carrierId}/drivers` | Register a driver under a carrier | ComplianceAdmin, CarrierRep |
| GET | `/carriers/{carrierId}/drivers` | List a carrier's drivers | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/carriers/{carrierId}/score-snapshots` | Compute and record a certified PRISM/ISS score snapshot | ComplianceAdmin |
| GET | `/carriers/{carrierId}/score-snapshots` | List a carrier's score snapshots | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/stations` | Create a weigh station | ComplianceAdmin |
| GET | `/stations/{stationId}` | Get a weigh station | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/stations/{stationId}/bays` | Create an inspection bay under a station | ComplianceAdmin |
| GET | `/stations/{stationId}/bays` | List a station's bays | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| GET | `/drivers/{driverId}` | Get a driver | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/drivers/{driverId}/duty-logs` | Append an HOS duty-log entry | CarrierRep, ComplianceAdmin |
| GET | `/drivers/{driverId}/duty-logs` | List a driver's duty logs | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/screenings` | Record a WIM/scale screening | Screener |
| GET | `/screenings` | List screenings (filterable) | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| GET | `/screenings/{screeningId}` | Get a screening | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/inspections` | Open a Level I–III inspection on a referred screening | Inspector |
| GET | `/inspections` | List inspections (filterable) | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| GET | `/inspections/{inspectionId}` | Get an inspection | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/inspections/{inspectionId}/violations` | Record a violation on an open inspection | Inspector |
| GET | `/inspections/{inspectionId}/violations` | List an inspection's violations | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/inspections/{inspectionId}/finalize` | Finalize an inspection as CLEAR or OOS | Inspector |
| POST | `/inspections/{inspectionId}/reinspect` | Reopen an OOS inspection for reinspection | Inspector |
| POST | `/inspections/{inspectionId}/cancel` | Cancel an open inspection | Inspector |
| POST | `/citations` | Issue a citation from a finalized inspection | EnforcementOfficer |
| GET | `/citations` | List citations (filterable) | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| GET | `/citations/{citationId}` | Get a citation | ComplianceAdmin, Screener, Inspector, EnforcementOfficer, CarrierRep |
| POST | `/citations/{citationId}/contest` | Contest a citation | CarrierRep |
| POST | `/citations/{citationId}/adjudicate` | Rule on a contested citation (UPHOLD or DISMISS) | EnforcementOfficer |
| POST | `/citations/{citationId}/settle` | Settle a citation | CarrierRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SOD_CONFLICT` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CARRIER_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_BAY_NOT_FOUND` | 404 |
| `ERR_DRIVER_NOT_FOUND` | 404 |
| `ERR_SCREENING_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_CITATION_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_USDOT` | 409 |
| `ERR_SCREENING_NOT_REFERRED` | 409 |
| `ERR_INSPECTION_INVALID_STATE` | 409 |
| `ERR_CITATION_INVALID_STATE` | 409 |
| `ERR_BAY_UNAVAILABLE` | 409 |
| `ERR_NO_OOS_BASIS` | 422 |
| `ERR_OVERWEIGHT_BASIS_MISSING` | 422 |
| `ERR_HAZMAT_BASIS_MISSING` | 422 |
| `ERR_HOS_DRIVING_LIMIT` | 422 |
| `ERR_CARRIER_MISMATCH` | 409 |
| `ERR_BAY_WINDOW_CONFLICT` | 409 |
| `ERR_HOS_RESET_REQUIRED` | 409 |
| `ERR_DUTY_LOG_OVERLAP` | 409 |
| `ERR_SETTLEMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_FINE_CAP_EXCEEDED` | 422 |
| `ERR_STALE_CARRIER_VERSION` | 412 |

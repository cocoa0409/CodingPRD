# Boiler Room Steam Plant API — Product Requirements Document

## 1. Introduction

Campus and industrial steam plants operate under some of the most heavily regulated conditions in facility management: boiler operators must hold licenses issued by the plant's own state, every boiler carries a jurisdictional certificate that must be renewed through annual inspection, water chemistry must be held inside narrow treatment bands to prevent scale and carryover, and safety relief valves must be pop-tested against a stamped setpoint. Failures are not clerical — a lapsed certificate, an out-of-envelope relief valve, or a runaway cycles-of-concentration reading each has a defined operational consequence, from forced shutdown to plant-wide emergency posture. This document specifies an API that acts as the system of record for a single steam plant's operations: its boilers and their operators, the shift log entries that meter steam and fuel, the chemistry logs that drive blowdown control, the inspections that issue and suspend certificates, the steam-trap survey program that quantifies distribution losses, the load-dispatch schedule that sequences lead and lag boilers, and the incident workflow that governs trips, resets, and closure.

Two design commitments shape everything that follows. First, the system is built for audit: fuel and water are tracked as compensating ledgers that must always reconcile, log entries require segregation of duties between recorder and verifier, and every certificate-relevant event is traceable to an inspection record. Second, the system is posture-driven: each boiler carries three independent status dimensions — operational, certification, and water chemistry — and the gates on operator actions read across all three, while the plant itself derives a `posture` of `NORMAL`, `DEGRADED`, or `EMERGENCY` from the state of its boiler fleet and its open incidents. Because the same physical quantity is regulated differently by different jurisdictions, several calculations are defined in two variants and the plant's own `state_code` selects which one applies: Massachusetts plants report combustion efficiency by the ASME PTC 4.1 heat-loss method, and New York plants quantify steam-trap leaks by the empirical Grashof correlation. All time in the system is read from a single logical plant clock, so that expiry windows, dispatch activation, and certificate lapse are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled exactly as follows: `PlantManager`, `Operator`, and `Inspector`. A request with a missing or malformed header — a role that is absent or not one of the three declared values, or an absent user id — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity semantics differ by role. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator` entity; ownership checks on any resource that references an `Operator` — most importantly the segregation-of-duties comparison against a log entry's `recorded_by_operator_id`, and incident attribution against `raised_by_operator_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlantManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Inspector`, `X-User-ID` is likewise an opaque jurisdictional identifier not tied to any persisted entity and never compared to an entity `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Every list response is sorted by resource creation timestamp — `created_at` — in ascending order unless otherwise specified, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.


### 2.4. The Logical Plant Clock and the Operations Checkpoint

All temporal reasoning in the system — certificate expiry, license expiry, dispatch activation and completion, and any schedule comparison — reads from a single logical plant clock, never from wall-clock time. At server start, before any explicit set, the clock reads 2026-08-01T00:00:00Z. A `PlantManager` may advance the clock through an administrative clock-setting capability by supplying a target instant in the `to_iso8601` field; the capability responds with the new clock value in `current_utc`. Every subsequent time-dependent evaluation uses this logical time.

The operations checkpoint is the plant's periodic heartbeat, invoked by a `PlantManager`. Each checkpoint performs five things, in effect together: it increments the plant's `ops_run_index` by exactly one; it recomputes every operator's `license_status` against the plant clock; it recomputes every boiler's `cert_status` against the plant clock; it advances dispatch windows — activating `SCHEDULED` windows whose interval the clock has entered and completing `ACTIVE` windows whose end the clock has reached or passed; and it recomputes the plant's `posture`. Nothing in the checkpoint depends on wall time, so a test or an operator can replay an entire regulatory calendar by setting the clock and running checkpoints.

### 2.5. Common Resource Properties

Every resource in the system carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp formatted as ISO 8601 UTC with three fractional digits. Resources that are mutable additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification, and `version`, an integer that increments by one on every mutation of the resource, including mutations caused by automatic cascades and recomputations rather than by direct client writes. The full four-field set (`id`, `created_at`, `updated_at`, `version`) applies to Plant, Boiler, Operator, Inspection, SteamTrap, LoadDispatch, and Incident.

Three record types are append-only journal entries and deliberately carry a reduced property set: BoilerLogEntry, ChemistryLog, and FuelDelivery each have `id` and `created_at` only. Both `updated_at` and `version` are absent on these three types; their lifecycle state changes (such as verification or voiding) are recorded in their own status field rather than through a version counter.

### 2.6. Numeric Precision and Rounding

Stored and reported computed quantities — combustion efficiency, steam-trap leak rates and cost projections, blowdown recommendations, fuel ledger balances, and the water mass balance — are pinned to 2 decimal places using round-half-up. The blowdown recommendation additionally fixes an internal rounding point mid-chain, described in §3.3, and downstream steps must consume the rounded value rather than the raw intermediate. The lead/lag boiler selector retains four decimal places during score computation, with the final selection made by integer comparison. Timestamp comparisons throughout the system are made at second precision.

### 2.7. Validation Pipeline and Priority

Every request is validated in a fixed, global order, and a request that fails several checks surfaces the error from the earliest stage. The pipeline is:

1. **Authentication** — `X-User-Role` present and one of the declared roles, and `X-User-ID` present; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the endpoint per the RBAC matrix; otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence** — every identifier in the path template (`plantId`, `boilerId`, `entryId`, and so on) resolves to an existing entity within the correct scope; otherwise `ERR_NOT_FOUND` (404).
4. **State** — the target resource is in a valid from-state for the requested transition; otherwise `ERR_INVALID_STATE` (409).
5. **Water chemistry gates** — warming rejects a boiler whose `water_status` is `CRITICAL` with `ERR_WATER_CRITICAL` (422); bringing online rejects a boiler whose `water_status` is anything other than `IN_SPEC` with `ERR_WATER_OUT_OF_SPEC` (422).
6. **Certificate gate** — warming or bringing online a boiler whose `cert_status` is not `VALID` is rejected with `ERR_CERT_NOT_VALID` (422).
7. **Plant emergency gate** — warming any boiler while the plant `posture` is `EMERGENCY` is rejected with `ERR_PLANT_EMERGENCY` (422).
8. **Operator license gate** — every operator-initiated state transition requires the calling operator's `license_status` to be `ACTIVE`, and certain transitions additionally require an adequate `license_class`; violations are rejected with `ERR_OPERATOR_LICENSE_INVALID` (422).
9. **License jurisdiction gate** — the calling operator's `license_state` must equal the plant's `state_code`; this applies to warming, bringing online, recording boiler log entries, and recording chemistry logs, and violations are rejected with `ERR_LICENSE_WRONG_STATE` (422).
10. **Segregation of duties** — the operator verifying a log entry must not be the operator who recorded it; violations are rejected with `ERR_SOD_VERIFICATION` (422).
11. **Referential integrity** — foreign keys supplied in request bodies (`recorded_by_operator_id`, `triggered_boiler_id`, each element of `assigned_boiler_ids`) must resolve to existing entities; otherwise `ERR_REFERENCED_NOT_FOUND` (422).
12. **Dispatch window conflicts** — creating a dispatch window that assigns a boiler already assigned to an overlapping `SCHEDULED` or `ACTIVE` window is rejected with `ERR_DISPATCH_WINDOW_CONFLICT` (409).
13. **Inspection schedule conflicts** — scheduling an inspection whose buffered occupancy interval touches another `PENDING` inspection on the same boiler is rejected with `ERR_INSPECTION_SCHEDULE_CONFLICT` (409).
14. **Dispatch window shape** — a window whose `window_end_at` is not strictly after its `window_start_at` is rejected with `ERR_INVALID_REQUEST` (400).
15. **Relief-valve lift envelope** — recording a `PASSED` outcome on a pop test whose measured lift pressure falls outside the permitted envelope is rejected with `ERR_RELIEF_SETPOINT_EXCEEDED` (422) above the envelope or `ERR_RELIEF_NO_LIFT` (422) below it.
16. **Tag uniqueness** — boiler tags and steam-trap tags must be unique within their plant; duplicates are rejected with `ERR_DUPLICATE_TAG` (409).
17. **Duty segregation on log voids** — only a `PlantManager` may void a `VERIFIED` log entry, and only an `Operator` may verify; violations are rejected with `ERR_UNAUTHORIZED` (403).
18. **Fuel underflow** — voiding a verified log entry that would drive the plant's `fuel_inventory_gal` negative is rejected with `ERR_FUEL_INVENTORY_UNDERFLOW` (422).
19. **Lead-boiler banking restriction** — banking the current lead boiler while any other boiler is `ONLINE` is rejected with `ERR_LEAD_CANNOT_BANK` (422).
20. **Incident closure notes** — closing an incident without non-empty `resolution_notes` is rejected with `ERR_RESOLUTION_NOTES_REQUIRED` (422).
21. **Incident closure path** — an incident that is not `LOW` severity cannot close directly from `OPEN`; the attempt is rejected with `ERR_INCIDENT_NOT_CLOSABLE` (409).
22. **Optimistic concurrency** — a stale `expected_boiler_version` or `expected_inspection_version` is rejected with `ERR_STALE_VERSION` (412).

### 2.8. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and no others do. Verifying a boiler log entry requires the request to carry `expected_boiler_version`, holding the `version` of the parent boiler as the verifier last observed it; if the boiler's current `version` differs — for example because another writer has since verified a different log entry on the same boiler, which legitimately advances the boiler's totals, header pressure, efficiency, and version — the verification is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the verifier from acting on a boiler state it has not observed. Recording an inspection outcome requires `expected_inspection_version`, holding the inspection's `version` as last observed; a mismatch with the inspection's current `version` — for example because an earlier recording already advanced it, including a `CONDITIONAL` recording that also auto-created a follow-up inspection — is rejected with `ERR_STALE_VERSION` (HTTP 412). Both fields are non-optional on their respective endpoints. Endpoints not named here accept no version field at all.

### 2.9. Nested Resource Retrieval and Flat Aliases

Paths in this API are hierarchical: boilers live under plants, and log entries, chemistry logs, and inspections live under boilers. When a path contains multiple identifiers, the system resolves them left to right, rejecting the request with `ERR_NOT_FOUND` (404) at the first identifier that does not resolve within its parent's scope — a request addressed to a boiler under a nonexistent plant fails on the plant before the boiler is ever consulted, and a log entry addressed under the wrong boiler fails on the boiler scope.

For reverse foreign-key reachability, the API also exposes flat alias read endpoints for boilers, operators, boiler log entries, chemistry logs, inspections, steam traps, load dispatches, incidents, and fuel deliveries — each retrievable directly by id, and each listable with filters such as `plant_id`, `boiler_id`, `recorded_by_operator_id`, `raised_by_operator_id`, or `triggered_boiler_id` as applicable. These aliases are read-only; all writes flow through the nested paths.

### 2.10. The Fuel Ledger and the Water Mass Balance

The plant's fuel oil is a compensating ledger with a hard invariant: `fuel_inventory_gal` always equals `total_fuel_received_gal` minus `total_fuel_consumed_gal`, and it may never go negative. A recorded fuel delivery adds its `quantity_gal` to `total_fuel_received_gal`. Verifying a boiler log entry adds the entry's `fuel_burned_gal` to `total_fuel_consumed_gal`. Voiding a previously verified entry subtracts that same `fuel_burned_gal` back out — a compensating reversal rather than a deletion — and is refused with `ERR_FUEL_INVENTORY_UNDERFLOW` whenever the subtraction would push `fuel_inventory_gal` below zero. Draft entries touch nothing: a log entry has no ledger effect of any kind until it is verified. All ledger arithmetic is carried at 2 decimal places, round-half-up.

Water accountability follows a parallel invariant at boiler granularity: `total_feedwater_gal` must equal `total_blowdown_gal` plus `total_steam_lb` divided by 8.345 pounds per gallon, with the comparison pinned to 2 decimal places, round-half-up. The balance is re-evaluated whenever a log entry is verified or a verified entry is voided. If the absolute drift between the two sides exceeds 25.0 gallons, the system automatically raises an Incident of `kind` `CHEMISTRY_EXCURSION` at `severity` `MEDIUM`, so that unexplained water loss is investigated rather than silently absorbed.

### 2.11. Scheduling Interval Semantics

Dispatch windows and inspection bookings use deliberately different interval semantics, and implementations must not conflate them. A dispatch window is a half-open interval: `window_start_at` is inclusive, `window_end_at` is exclusive. Two windows conflict when the first begins before the second ends and the second begins before the first ends; windows that merely touch — one ending at exactly the instant the other begins — do not conflict. A single boiler may never be assigned to two conflicting `SCHEDULED` or `ACTIVE` windows.

An inspection booking, by contrast, occupies a closed interval with a cleanup buffer: each inspection occupies four hours beginning at its `scheduled_on`, plus a two-hour buffer on each side, so its effective occupancy runs from two hours before `scheduled_on` to six hours after it. Two `PENDING` inspections on the same boiler conflict whenever their effective occupancy intervals intersect, and because the comparison is closed, intervals whose endpoints merely touch do conflict — the opposite of the dispatch rule.


## 3. Business Logic & Workflows

### 3.1. Establishing the Plant, Its Boilers, and Its People

Everything begins when a `PlantManager` registers the plant itself, supplying a display `name`, the governing `state_code` — one of `MA`, `NY`, `CA`, or `TX`, a choice that later selects calculation variants and licensing jurisdiction — and the steam header's operating setpoint `header_pressure_psi`. A new plant starts clean: `posture` is `NORMAL`, `fuel_inventory_gal`, `total_fuel_received_gal`, and `total_fuel_consumed_gal` are all 0, `ops_run_index` is 0, and `lead_boiler_id` is null. The plant's `header_pressure_actual_psi` is a computed value: it reflects the `header_pressure_reading_psi` of the most recent non-voided boiler log entry taken across the plant's `ONLINE` boilers, and reads 0 when no such reading exists.

With a plant in place, the `PlantManager` registers boilers. Each boiler carries a `tag` (a human label such as B-101, unique within the plant — a duplicate is refused with `ERR_DUPLICATE_TAG`), an integer `rated_capacity_lb_hr` nameplate capacity, and a `relief_valve_setpoint_psi` that must exceed the parent plant's `header_pressure_psi`; a request violating that relationship is rejected with `ERR_INVALID_REQUEST`. The accumulation tolerance `relief_valve_tolerance_pct` may be supplied at registration and defaults to 3.0: the relief valve must lift at or above the setpoint and no higher than the setpoint grown by that percentage. A boiler is born with three independent status dimensions — `ops_status` beginning at `STANDBY`, `cert_status` beginning at `VALID`, and `water_status` beginning at `IN_SPEC` — plus `cycles_of_concentration` initialized to 1.0 and cumulative totals (`total_steam_lb`, `total_fuel_burned_gal`, `total_blowdown_gal`, `total_feedwater_gal`) at 0; `efficiency_pct` remains unset until the first efficiency calculation runs. The boiler collection can be listed with `ops_status` and `cert_status` filters, and each boiler record exposes its `plant_id` back-reference.

Operators are enrolled by the `PlantManager` with a `full_name`, a `license_class` of `CLASS_1`, `CLASS_2`, or `CLASS_3` — a higher class may supervise a lower — the issuing `license_state`, the `license_expires_on` date, and an optional `is_lead_qualified` flag that defaults to false. Enrollment starts every operator at `license_status` `ACTIVE`. The operator roster can be listed with a `license_status` filter. Fuel arrives through deliveries recorded by the `PlantManager` with a `delivered_at` timestamp, a `quantity_gal` that must be greater than zero (else `ERR_INVALID_REQUEST`), and a `supplier` name; each delivery adds its quantity to `total_fuel_received_gal` and recomputes `fuel_inventory_gal` per the ledger invariant in §2.10.

### 3.2. Operator Licensing, Jurisdiction, and Duty Segregation

Licensing is jurisdiction-bound: for warming a boiler, bringing one online, recording a boiler log entry, or recording a chemistry log, the acting operator's `license_state` must equal the plant's `state_code`, or the request is refused with `ERR_LICENSE_WRONG_STATE`. License freshness is evaluated at every operations checkpoint against the plant clock. An operator whose `license_expires_on` falls strictly before the plant clock becomes `EXPIRED`; an expiry exactly equal to the clock does not lapse. When the time remaining until expiry is sixty days or less — 5,184,000 seconds, with exactly sixty days remaining qualifying — the status becomes `EXPIRING`. Both `EXPIRING` to `EXPIRED` and a direct `ACTIVE` to `EXPIRED` transition are possible at a checkpoint, the latter covering operators whose checkpoint cadence skipped them past the warning window entirely.

An `EXPIRED` operator can no longer perform state-changing actions — every license-gated request fails with `ERR_OPERATOR_LICENSE_INVALID` — and any `DRAFT` log entries they recorded simply remain `DRAFT` until another operator verifies them, since an entry can never be self-verified. A `PlantManager` restores an `EXPIRING` or `EXPIRED` operator by renewing the license, supplying a `new_license_expires_on` that must lie strictly after the plant clock; renewal writes the new `license_expires_on` and returns the operator to `ACTIVE`. Revocation, also a `PlantManager` act, moves an `ACTIVE` or `EXPIRED` operator to the terminal `REVOKED` state, after which they may no longer act at all.

Two duty-segregation rules complete the picture. Verification of a boiler log entry is reserved for the `Operator` role, and the verifying operator must not be the entry's recorder — a self-verification attempt is refused with `ERR_SOD_VERIFICATION`. Voiding splits by entry state: a `DRAFT` entry may be voided by an `Operator`, but voiding a `VERIFIED` entry is reserved for a `PlantManager`, and any role confusion on either path draws `ERR_UNAUTHORIZED`.

### 3.3. Water Chemistry, Cycles of Concentration, and Blowdown Control

An `Operator` records a chemistry reading for a boiler with `recorded_by_operator_id` (which must reference an existing operator, else `ERR_REFERENCED_NOT_FOUND`), a `recorded_at` timestamp, the boiler-water conductivity `conductivity_boiler_umho`, the feedwater conductivity `conductivity_feedwater_umho` — which must be greater than zero, else `ERR_INVALID_REQUEST` — and the treatment residuals `sulfite_residual_ppm` and `phosphate_residual_ppm`. New logs are born in `RECORDED` status. Recording a log immediately recomputes the boiler's `cycles_of_concentration` — the boiler-water conductivity divided by the feedwater conductivity, taken from the latest non-`VOIDED` chemistry log — and re-evaluates the boiler's `water_status`, which can cascade into the operational dimension and even raise incidents. Chemistry logs can be listed with a `status` filter.

The `water_status` dimension moves automatically, never by direct request. A recorded log drives `IN_SPEC` to `OUT_OF_SPEC` when the cycles of concentration exceed the maximum of 10.0, when the sulfite residual falls below the configured oxygen-scavenger minimum `SULFITE_MIN_PPM`, or when the phosphate residual falls outside the configured band from `PHOSPHATE_MIN_PPM` to `PHOSPHATE_MAX_PPM`, inclusive at both ends; if the boiler was `ONLINE` at that moment, it is forced to `BANKING` to shed load. From `OUT_OF_SPEC`, the boiler deteriorates to `CRITICAL` when the count of consecutive out-of-spec readings reaches `CHEMISTRY_CRITICAL_COUNT`, or when a single reading's cycles exceed the product of the 10.0 maximum and `CRITICAL_CYCLES_FACTOR`; a boiler that is `ONLINE`, `BANKING`, or `WARMING` at that point is forced to `STANDBY`, and the system auto-creates an Incident at `severity` `HIGH`, `kind` `CHEMISTRY_EXCURSION`, naming the boiler in `triggered_boiler_id`. Recovery is equally automatic: a fully in-spec reading returns `OUT_OF_SPEC` to `IN_SPEC`, and `CRITICAL` returns to `IN_SPEC` after `CHEMISTRY_RECOVERY_COUNT` consecutive in-spec logs recorded following the critical entry. A `PlantManager` may void a chemistry log; voiding recomputes `water_status` from the remaining logs, recomputes `cycles_of_concentration` from the latest non-`VOIDED` log, and resets `water_status` to `IN_SPEC` outright if no non-`VOIDED` logs remain.

Every recorded chemistry log also triggers a fresh blowdown recommendation, computed as a pinned seven-step chain. Step one derives the actual cycles of concentration from the latest non-`VOIDED` log: `conductivity_boiler_umho` divided by `conductivity_feedwater_umho`. Step two converts that to a required blowdown percentage: take the amount by which the actual cycles exceed the 10.0-cycle target, divide it by the actual cycles minus one, multiply by one hundred, and floor the result at zero. Step three derives the current steam rate in pounds per hour: sum `steam_generated_lb` across the verified, non-voided boiler log entries whose readings fall within the most recent twenty-four hours, divide by twenty-four, and use zero when no such entries exist. Step four converts the percentage to a flow in gallons per hour: the required percentage expressed as a fraction, multiplied by the steam rate, multiplied by 8.345 pounds per gallon, divided by one minus the required percentage as a fraction. Step five rounds that flow half-up to 2 decimal places. Step six multiplies by twenty-four to get a daily volume — and it must use the rounded flow from step five, not the unrounded intermediate, because the two paths diverge at the cents level. Step seven clamps the daily volume to no less than 5.0 and no more than 5,000.0 gallons per day.

### 3.4. Boiler Operations and Lead/Lag Selection

The operational life of a boiler is a state machine over `ops_status`, with `DECOMMISSIONED` as its only terminal state; asking for a transition from any other state than a listed from-state is rejected with `ERR_INVALID_STATE`. An `Operator` warms a boiler, moving it `STANDBY` to `WARMING`. Warming is gated by five conditions, enforced through the validation pipeline of §2.7: the boiler's `cert_status` must be `VALID` (else `ERR_CERT_NOT_VALID`), its `water_status` must not be `CRITICAL` (else `ERR_WATER_CRITICAL`), the plant `posture` must not be `EMERGENCY` (else `ERR_PLANT_EMERGENCY`), the calling operator's `license_status` must be `ACTIVE` (else `ERR_OPERATOR_LICENSE_INVALID`), and the operator's `license_state` must match the plant's `state_code` (else `ERR_LICENSE_WRONG_STATE`). A successful warm refreshes the boiler's `updated_at` and increments its `version` by one.

Bringing a boiler online moves `WARMING` to `ONLINE`, and carries the strictest gate in the system: `cert_status` must be `VALID`, `water_status` must be exactly `IN_SPEC` (else `ERR_WATER_OUT_OF_SPEC`), at least one non-`VOIDED` chemistry log with cycles of concentration at or below the 10.0 maximum must exist for the boiler (else `ERR_NO_VALID_CHEMISTRY`), and the calling operator must be `ACTIVE` and hold `license_class` `CLASS_1` or `CLASS_2` (else `ERR_OPERATOR_LICENSE_INVALID`). The same bring-online action also returns a `BANKING` boiler to `ONLINE`, where the gate relaxes to just two conditions: `cert_status` `VALID` and `water_status` `IN_SPEC`. Either path re-evaluates the plant's lead boiler and recomputes `header_pressure_actual_psi` from the latest log entries across the now-`ONLINE` fleet.

Banking moves `ONLINE` to `BANKING`. The plant's current lead boiler may not bank while at least one other boiler is `ONLINE` — it must hand off first, and the attempt is refused with `ERR_LEAD_CANNOT_BANK`. When the lead does legitimately leave the `ONLINE` ranks — or when any boiler shuts down from `ONLINE` — the lead selector re-runs across the remaining `ONLINE` boilers and may leave `lead_boiler_id` null. Shutdown moves a boiler from `ONLINE`, `BANKING`, or `WARMING` back to `STANDBY` with no preconditions. Each of these transitions increments the boiler's `version` and refreshes `updated_at`.

The lead/lag selector is the plant's dispatch brain. A boiler is eligible to lead when it is `ONLINE`, its `cert_status` is `VALID`, and its `water_status` is not `CRITICAL`. Each eligible boiler is scored: start from its `rated_capacity_lb_hr`; multiply by one if its `efficiency_pct` has never been computed, otherwise by `efficiency_pct` divided by one hundred; multiply by one minus the product of 0.15 and the lesser of one and the ratio of the boiler's `cycles_of_concentration` to the 10.0 maximum, so the chemistry penalty saturates rather than growing without bound; then add an incumbency bonus of 5,000.0 if the boiler currently holds `lead_boiler_id`. Boilers rank by score descending; ties break by `rated_capacity_lb_hr` descending, then by `created_at` ascending. When no boiler is eligible, `lead_boiler_id` becomes null. Scores are carried at four decimal places during computation, and the final selection is made by integer comparison.

Resetting a tripped boiler — `TRIPPED` to `STANDBY`, performed by an `Operator` — is the recovery gate for the incident workflow of §3.9: every incident naming this boiler in `triggered_boiler_id` at `severity` `HIGH` or `CRITICAL` must already be `MITIGATED` or `CLOSED` (else `ERR_INCIDENT_UNRESOLVED`), and if the boiler's `cert_status` is `SUSPENDED`, a `POST_INCIDENT` inspection with `outcome` `PASSED` recorded after the boiler's most recent trip must exist (else `ERR_REINSPECTION_REQUIRED`). A successful reset recomputes `cert_status` from the latest inspection — which can carry the boiler from `SUSPENDED` back to `VALID` — and recomputes the plant `posture`. Finally, a `PlantManager` may decommission a `STANDBY` boiler, but only while no `SCHEDULED` or `ACTIVE` dispatch window references it (else `ERR_BOILER_IN_DISPATCH`); decommissioning is terminal, and no further transitions exist.

### 3.5. Boiler Log Entries, Verification, and the Efficiency Ledger

Shift metering flows through boiler log entries. An `Operator` records an entry with `recorded_by_operator_id` (which must exist, else `ERR_REFERENCED_NOT_FOUND`), the `recorded_at` timestamp, the observed `header_pressure_reading_psi`, and the interval's `steam_generated_lb`, `fuel_burned_gal`, `feedwater_intake_gal`, and `blowdown_gal`. The recorder's `license_state` must match the plant's `state_code` per §3.2. A new entry is born `DRAFT` and has no ledger effect whatsoever; the entry list supports a `status` filter. Entries carry the reduced property set of §2.5 — no `updated_at`, no `version`.

Verification is where the ledger moves. A second `Operator` — never the recorder, per §3.2 — verifies a `DRAFT` entry, provided the verifier's `license_status` is `ACTIVE` and the boiler's `ops_status` is one of `ONLINE`, `BANKING`, `STANDBY`, or `WARMING`; entries on a `TRIPPED` or `DECOMMISSIONED` boiler cannot be verified, and the attempt is rejected with `ERR_INVALID_STATE`. The request must also carry `expected_boiler_version` under the optimistic-concurrency rule of §2.8, with a stale value rejected as `ERR_STALE_VERSION` (412). On verification, the plant's `total_fuel_consumed_gal` grows by the entry's `fuel_burned_gal` and `fuel_inventory_gal` is recomputed; the boiler's `total_steam_lb`, `total_fuel_burned_gal`, `total_blowdown_gal`, and `total_feedwater_gal` each grow by the entry's corresponding figure; `header_pressure_actual_psi` adopts the entry's `header_pressure_reading_psi` whenever the entry's `recorded_at` is the latest among non-voided entries; the boiler's `efficiency_pct` is recomputed; and the boiler's `version` increments by one — which is precisely what strands any other verifier's stale `expected_boiler_version`.

Voiding unwinds. An `Operator` may void a `DRAFT` entry, provided the caller's license is `ACTIVE`; since draft entries were never applied, there is nothing to compensate and the entry simply falls out of every aggregate. Voiding a `VERIFIED` entry is the `PlantManager`-only compensating path: the plant's `total_fuel_consumed_gal` shrinks by the entry's `fuel_burned_gal`, the boiler's four totals shrink by the entry's figures, `header_pressure_actual_psi` is recomputed from the remaining non-voided entries, and `efficiency_pct` is recomputed — but only if the subtraction does not drive `fuel_inventory_gal` negative, which is refused with `ERR_FUEL_INVENTORY_UNDERFLOW`. Both `VERIFIED` and `VOIDED` are terminal states for an entry.

Verification and verified-voiding also re-run the boiler's combustion efficiency, whose variant is chosen by the plant's `state_code`. Outside Massachusetts, the input-output method applies: the boiler's cumulative `total_steam_lb` over verified, non-voided entries is multiplied by the difference between the steam enthalpy constant of 1,190.0 BTU per pound and the feedwater enthalpy constant of 180.0 BTU per pound to yield the steam enthalpy output; the cumulative `total_fuel_burned_gal` is multiplied by the fuel's higher heating value of 140,000.0 BTU per gallon to yield the fuel energy input; the efficiency percentage is the output divided by the input, multiplied by one hundred, rounded half-up to 2 decimal places. In Massachusetts (`state_code` `MA`), the ASME PTC 4.1 heat-loss method applies instead: the efficiency is one hundred minus the sum of four loss terms — a fixed dry-gas loss of 6.5 percent, a fixed moisture loss of 4.0 percent, a blowdown loss equal to the cumulative `total_blowdown_gal` divided by the cumulative `total_feedwater_gal` (with the denominator replaced by 0.000001 whenever the feedwater total is smaller than that epsilon), the ratio multiplied by 100.0, and a fixed radiation loss of 1.5 percent — again rounded half-up to 2 decimal places. The two methods deliberately disagree on identical inputs, because the heat-loss method charges blowdown independently of steam metering; the resulting percentage is cached on the boiler as `efficiency_pct` and feeds the lead/lag selector of §3.4.


### 3.6. Inspections, Relief-Valve Pop Tests, and Certificates

Inspections are scheduled by a `PlantManager` or an `Inspector`, with an `inspection_kind` of `ANNUAL_INTERNAL`, `ANNUAL_EXTERNAL`, `RELIEF_VALVE_POP`, or `POST_INCIDENT`; a `scheduled_on` date; the `inspector_name`; and the `inspector_license_no`. A pop test may also carry the measured `relief_valve_lift_pressure_psi`. Every new inspection is born with `outcome` `PENDING` and `posted_at` null. Scheduling obeys the closed, buffered interval rule of §2.11 — each inspection occupies four hours from its `scheduled_on`, extended two hours on each side, and any intersection (including mere endpoint contact) with another `PENDING` inspection on the same boiler is refused with `ERR_INSPECTION_SCHEDULE_CONFLICT`. The inspection list supports an `outcome` filter.

Recording an outcome is the act that moves an inspection out of `PENDING`, performed by a `PlantManager` or an `Inspector`. The request names the `outcome`, may carry `certificate_number`, `certificate_expires_on`, and `relief_valve_lift_pressure_psi`, and must carry `expected_inspection_version` per §2.8 — a stale value is rejected with `ERR_STALE_VERSION` (412). The recording increments the inspection's `version` by one, and when the outcome cascades into the boiler it may increment the boiler's `version` as well.

A `PASSED` recording has its own discipline. For the annual kinds (`ANNUAL_INTERNAL` and `ANNUAL_EXTERNAL`), a `certificate_number` is required and a missing one is rejected with `ERR_INVALID_REQUEST`; the accompanying `certificate_expires_on` records the certificate's expiry — conventionally one year from the pass for annual certificates — and remains null for non-annual kinds. For a `RELIEF_VALVE_POP` test, the measured lift pressure must sit inside a closed envelope: it must be at least the boiler's `relief_valve_setpoint_psi` — a lift below the setpoint means the valve failed to lift on demand and is rejected with `ERR_RELIEF_NO_LIFT` — and it must be no greater than the setpoint grown by `relief_valve_tolerance_pct` percent, with equality permitted, else `ERR_RELIEF_SETPOINT_EXCEEDED`. A pop test inside the envelope changes nothing in the certification dimension. A pop test whose measured lift falls outside the envelope — whether the recording arrives as an explicit `FAILED` or the envelope check forces it — ends as a `FAILED` outcome with two cascades: the boiler's `cert_status` becomes `SUSPENDED`, and its `ops_status` is forced to `TRIPPED`. Any explicitly recorded `FAILED` pop test carries the same two cascades. A `FAILED` annual inspection on a boiler whose certificate was `VALID` or `EXPIRING` leaves the certificate to lapse at the next operations checkpoint. A `CONDITIONAL` recording issues no certificate and leaves `cert_status` untouched, but the system automatically schedules a follow-up inspection of the same kind, with `scheduled_on` set `CONDITIONAL_FOLLOWUP_DAYS` days after the recording moment.

The `cert_status` dimension then moves on its own tracks. At each operations checkpoint, the certificate rule runs against the latest `PASSED` inspection of any kind: if no `PASSED` inspection exists for the boiler, or its `certificate_expires_on` is null, the status becomes `LAPSED`; otherwise an expiry strictly before the plant clock means `LAPSED`, while an expiry exactly equal to the clock does not; otherwise, when the time remaining to expiry is thirty days or less — 2,592,000 seconds, with exactly thirty days remaining qualifying — the status becomes `EXPIRING`; otherwise it holds `VALID`. Lapsing is an emergency auto-shutdown: a boiler that was `WARMING`, `ONLINE`, or `BANKING` when it lapsed is forced to `STANDBY`, and the plant `posture` is recomputed. Certification recovery is kind-specific and asymmetric: a boiler in `EXPIRING` returns to `VALID` when a new `ANNUAL_EXTERNAL` or `ANNUAL_INTERNAL` inspection passes with a `certificate_expires_on` beyond the plant clock; a boiler in `LAPSED` returns to `VALID` only on a passed `ANNUAL_EXTERNAL` with a future expiry — an internal inspection is not sufficient; and a boiler in `SUSPENDED` returns to `VALID` when a `POST_INCIDENT` inspection passes, recorded after the most recent suspension. A passed relief pop test by itself never restores a certificate. Once an annual certificate passes, a `PlantManager` posts it, which stamps `posted_at` with the current plant clock; until that explicit posting, `posted_at` remains null.

### 3.7. Steam Trap Surveys and Loss Projection

The distribution-loss program tracks steam traps registered under the plant by a `PlantManager` or an `Operator`, each with a plant-unique `tag` (duplicates refused with `ERR_DUPLICATE_TAG`), a free-text `location`, the `orifice_diameter_in` that drives the leak physics, and the trap's `design_pressure_psi`. A new trap starts with `condition` `UNKNOWN`, `status` `IN_SERVICE`, `leak_rate_lb_hr` at 0, and `last_surveyed_at` null; over its life a trap's `condition` moves among `UNKNOWN`, `OK`, `LEAKING`, `FAILED_OPEN`, `FAILED_CLOSED`, and `COLD`, and its `status` among `IN_SERVICE`, `ISOLATED`, and `REPLACED`. The trap list supports `condition` and `status` filters.

An `Operator` records a survey result by submitting the observed `condition`. The survey stamps `last_surveyed_at` with the current time and recomputes `leak_rate_lb_hr`: a trap found `LEAKING` or `FAILED_OPEN` gets a computed leak rate, and any other condition resets the rate to 0. The same computation backs the trap's loss-projection read, a computed view returning `leak_rate_lb_hr`, `annual_steam_loss_lb`, `annual_cost_usd`, and a `method` string naming the variant applied.

The variant is chosen by the plant's `state_code`. Outside New York, the Napier theoretical method applies — reported as `napier_theoretical`: the leak rate in pounds per hour is the Napier coefficient 51.45, multiplied by the square of `orifice_diameter_in`, multiplied by `design_pressure_psi`. In New York (`state_code` `NY`), the empirical Grashof correlation applies — reported as `grashof_empirical`: the coefficient 24.24, multiplied by the square of `orifice_diameter_in`, multiplied by the square root of `design_pressure_psi`. Grashof therefore prices high-pressure traps lower and low-pressure traps higher than Napier does for identical hardware. Either way, the annual steam loss is the leak rate multiplied by 8,760 hours per year, and the annual cost is that annual loss multiplied by the fuel price per gallon divided by the fuel's higher heating value of 140,000.0 BTU per gallon, then multiplied by the enthalpy difference of 1,190.0 minus 180.0 BTU per pound. The fuel price per gallon is taken from the plant's most recently recorded fuel delivery; when the plant has recorded no deliveries, a default of 3.50 per gallon applies. All reported figures are rounded half-up to 2 decimal places.

### 3.8. Load Dispatch and Lead/Lag Scheduling

Steam demand is scheduled in advance as dispatch windows, created by a `PlantManager` or an `Operator` with a `window_start_at` (inclusive), a `window_end_at` (exclusive, and required to be strictly after the start, else `ERR_INVALID_REQUEST`), a total demand `target_steam_lb_hr`, and an ordered `assigned_boiler_ids` list whose first element is the intended lead and whose remaining elements are lags in dispatch order; every element must reference an existing boiler, else `ERR_REFERENCED_NOT_FOUND`. Creation runs the half-open overlap rule of §2.11: if any assigned boiler already appears in a `SCHEDULED` or `ACTIVE` window whose interval conflicts — remember that touching windows do not conflict — the creation is refused with `ERR_DISPATCH_WINDOW_CONFLICT`. A new window is born `SCHEDULED`, and its `expected_lead_boiler_id` is stamped at creation time with the result of the lead/lag selector of §3.4. The dispatch list supports a `status` filter.

Windows activate and complete at operations checkpoints. When the plant clock enters a `SCHEDULED` window's half-open interval, the window activates — but only if every boiler in `assigned_boiler_ids` currently sits in `ONLINE`, `BANKING`, or `WARMING`; if any assigned boiler fails that test, the window does not activate and is instead `CANCELLED` outright, with the lead selector re-evaluated in its wake. On a successful activation the selector re-runs with a preference for the window's first assigned boiler when that boiler is `ONLINE`. When the clock reaches or passes `window_end_at`, an `ACTIVE` window moves to `COMPLETED`. Either a `PlantManager` or an `Operator` may cancel a window that is `SCHEDULED` or `ACTIVE`; cancelling an `ACTIVE` window issues no further dispatch orders to its boilers and leaves each boiler's current `ops_status` untouched. `COMPLETED` and `CANCELLED` are terminal.

### 3.9. Incidents, Trips, and Plant Posture

An `Operator` raises an incident with `raised_by_operator_id` (which must exist, else `ERR_REFERENCED_NOT_FOUND`), a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, a `kind` of `OVERPRESSURE`, `LOW_WATER`, `FLAME_FAILURE`, `RELIEF_VALVE_LIFT`, `CHEMISTRY_EXCURSION`, or `OTHER`, an optional `triggered_boiler_id` for boiler-specific events — which must reference an existing boiler when supplied — and the `raised_at` observation time. Every incident is born `OPEN`. The incident list supports `status` and `severity` filters.

A qualifying incident trips its boiler automatically: when `severity` is `HIGH` or `CRITICAL`, `kind` is one of `OVERPRESSURE`, `LOW_WATER`, `FLAME_FAILURE`, or `RELIEF_VALVE_LIFT`, and `triggered_boiler_id` names a boiler, that boiler moves to `TRIPPED` from wherever it stands — `STANDBY`, `WARMING`, `ONLINE`, or `BANKING`. The trip then cascades outward in three depths. Depth one: if the tripped boiler was the lead, `lead_boiler_id` is recomputed and may go null, and the plant `posture` becomes `DEGRADED` if at least one boiler remains `ONLINE`, otherwise `EMERGENCY`. Depth two: every `SCHEDULED` dispatch window that contains the tripped boiler and whose `window_start_at` lies after the current moment is `CANCELLED`. Depth three: each such cancellation triggers a lag-dispatch re-evaluation, and if any window thereby becomes eligible for activation within fifteen minutes, the system auto-creates a replacement dispatch window staffed by the remaining `ONLINE` boilers per the lead/lag selector. Two trip sources additionally suspend certification: when the trigger is a `RELIEF_VALVE_LIFT` incident, or when a relief pop test records a `FAILED` outcome against an `ONLINE` boiler, the boiler's `cert_status` becomes `SUSPENDED` on its own dimension alongside the operational trip.

Working an incident is a licensed sequence. An `Operator` with an `ACTIVE` license acknowledges an `OPEN` incident, moving it to `ACKNOWLEDGED`, and likewise mitigates an `ACKNOWLEDGED` incident, moving it to `MITIGATED`. Mitigation releases two gates: if the incident names a `triggered_boiler_id` and no other `OPEN` or `ACKNOWLEDGED` incident at `HIGH` or `CRITICAL` severity remains against that boiler, the boiler becomes eligible for the reset described in §3.4; and if the plant as a whole has no `OPEN` or `ACKNOWLEDGED` incident at `HIGH` or `CRITICAL`, the plant `posture` is recomputed and may leave `EMERGENCY`. Closure belongs to the `PlantManager` and always requires non-empty `resolution_notes`, else `ERR_RESOLUTION_NOTES_REQUIRED`. A `MITIGATED` incident of any severity closes to the terminal `CLOSED` state. An incident still `OPEN` may close directly only when its `severity` is `LOW`; a `HIGH` or `CRITICAL` incident must traverse `ACKNOWLEDGED` and then `MITIGATED` first, and a direct-close attempt is refused with `ERR_INCIDENT_NOT_CLOSABLE`.


## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — state transitions, verifications, voids, outcome recordings, certificate postings, surveys, cancellations, renewals, revocations, and the operations checkpoint — return a `200 OK` status code. The complete request payloads, preconditions, and side effects for each endpoint are specified by the narratives of §2 and §3; the table below is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plants` | Create a Plant | PlantManager |
| GET | `/plants/{plantId}` | Get a Plant | PlantManager, Operator, Inspector |
| POST | `/plants/{plantId}/run-ops` | Run the operations checkpoint (advance `ops_run_index`, recompute license and certificate status, advance dispatches, recompute posture) | PlantManager |
| POST | `/_clock/set_current_utc` | Set the logical plant clock | PlantManager |
| POST | `/plants/{plantId}/boilers` | Create a Boiler | PlantManager |
| GET | `/plants/{plantId}/boilers/{boilerId}` | Get a Boiler | PlantManager, Operator, Inspector |
| GET | `/plants/{plantId}/boilers` | List boilers in a plant | PlantManager, Operator, Inspector |
| POST | `/plants/{plantId}/boilers/{boilerId}/warm` | Warm a boiler (STANDBY → WARMING) | Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/bring-online` | Bring a boiler online (WARMING → ONLINE or BANKING → ONLINE) | Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/bank` | Bank a boiler (ONLINE → BANKING) | Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/shutdown` | Shut a boiler down (ONLINE / BANKING / WARMING → STANDBY) | Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/reset` | Reset a tripped boiler (TRIPPED → STANDBY) | Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/decommission` | Decommission a boiler (STANDBY → DECOMMISSIONED, terminal) | PlantManager |
| POST | `/plants/{plantId}/operators` | Create an Operator | PlantManager |
| GET | `/plants/{plantId}/operators/{operatorId}` | Get an Operator | PlantManager, Operator |
| GET | `/plants/{plantId}/operators` | List operators | PlantManager, Operator |
| POST | `/plants/{plantId}/operators/{operatorId}/renew-license` | Renew a license (EXPIRING / EXPIRED → ACTIVE) | PlantManager |
| POST | `/plants/{plantId}/operators/{operatorId}/revoke-license` | Revoke a license (terminal) | PlantManager |
| POST | `/plants/{plantId}/boilers/{boilerId}/log-entries` | Record a boiler log entry (status DRAFT) | Operator |
| GET | `/plants/{plantId}/boilers/{boilerId}/log-entries/{entryId}` | Get a log entry | PlantManager, Operator |
| GET | `/plants/{plantId}/boilers/{boilerId}/log-entries` | List log entries for a boiler | PlantManager, Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/log-entries/{entryId}/verify` | Verify a log entry (DRAFT → VERIFIED; applies ledger effects; OCC on boiler version) | Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/log-entries/{entryId}/void` | Void a log entry (DRAFT → VOIDED, or VERIFIED → VOIDED compensating) | Operator, PlantManager |
| POST | `/plants/{plantId}/boilers/{boilerId}/chemistry-logs` | Record a chemistry log | Operator |
| GET | `/plants/{plantId}/boilers/{boilerId}/chemistry-logs/{logId}` | Get a chemistry log | PlantManager, Operator |
| GET | `/plants/{plantId}/boilers/{boilerId}/chemistry-logs` | List chemistry logs | PlantManager, Operator |
| POST | `/plants/{plantId}/boilers/{boilerId}/chemistry-logs/{logId}/void` | Void a chemistry log (RECORDED → VOIDED) | PlantManager |
| POST | `/plants/{plantId}/boilers/{boilerId}/inspections` | Schedule an Inspection | PlantManager, Inspector |
| GET | `/plants/{plantId}/boilers/{boilerId}/inspections/{inspectionId}` | Get an Inspection | PlantManager, Operator, Inspector |
| GET | `/plants/{plantId}/boilers/{boilerId}/inspections` | List Inspections for a boiler | PlantManager, Operator, Inspector |
| POST | `/plants/{plantId}/boilers/{boilerId}/inspections/{inspectionId}/record-outcome` | Record an outcome (PENDING → PASSED / FAILED / CONDITIONAL; OCC on inspection version) | PlantManager, Inspector |
| POST | `/plants/{plantId}/boilers/{boilerId}/inspections/{inspectionId}/post` | Post the certificate (stamp `posted_at`) | PlantManager |
| POST | `/plants/{plantId}/steam-traps` | Create a SteamTrap | PlantManager, Operator |
| GET | `/plants/{plantId}/steam-traps/{trapId}` | Get a SteamTrap | PlantManager, Operator |
| GET | `/plants/{plantId}/steam-traps` | List SteamTraps | PlantManager, Operator |
| POST | `/plants/{plantId}/steam-traps/{trapId}/survey` | Record a survey result (updates condition, `last_surveyed_at`, `leak_rate_lb_hr`) | Operator |
| GET | `/plants/{plantId}/steam-traps/{trapId}/loss-projection` | Computed read: annual loss projection | PlantManager, Operator |
| POST | `/plants/{plantId}/load-dispatches` | Create a LoadDispatch window | PlantManager, Operator |
| GET | `/plants/{plantId}/load-dispatches/{dispatchId}` | Get a LoadDispatch | PlantManager, Operator |
| GET | `/plants/{plantId}/load-dispatches` | List LoadDispatches | PlantManager, Operator |
| POST | `/plants/{plantId}/load-dispatches/{dispatchId}/cancel` | Cancel a dispatch (SCHEDULED / ACTIVE → CANCELLED) | PlantManager, Operator |
| POST | `/plants/{plantId}/incidents` | Raise an Incident | Operator |
| GET | `/plants/{plantId}/incidents/{incidentId}` | Get an Incident | PlantManager, Operator |
| GET | `/plants/{plantId}/incidents` | List Incidents | PlantManager, Operator |
| POST | `/plants/{plantId}/incidents/{incidentId}/acknowledge` | Acknowledge an incident (OPEN → ACKNOWLEDGED) | Operator |
| POST | `/plants/{plantId}/incidents/{incidentId}/mitigate` | Mitigate an incident (ACKNOWLEDGED → MITIGATED) | Operator |
| POST | `/plants/{plantId}/incidents/{incidentId}/close` | Close an incident (MITIGATED → CLOSED, or OPEN → CLOSED for LOW severity) | PlantManager |
| POST | `/plants/{plantId}/fuel-deliveries` | Record a fuel delivery | PlantManager |
| GET | `/plants/{plantId}/fuel-deliveries/{deliveryId}` | Get a FuelDelivery | PlantManager, Operator |
| GET | `/plants/{plantId}/fuel-deliveries` | List FuelDeliveries | PlantManager, Operator |
| GET | `/plants/boilers/{boilerId}` | Flat alias: get a Boiler by id | PlantManager, Operator, Inspector |
| GET | `/plants/boilers` | Flat alias: list boilers with optional `plant_id` filter | PlantManager, Operator, Inspector |
| GET | `/plants/operators/{operatorId}` | Flat alias: get an Operator by id | PlantManager, Operator |
| GET | `/plants/operators` | Flat alias: list operators with optional `plant_id` filter | PlantManager, Operator |
| GET | `/plants/boiler-log-entries/{entryId}` | Flat alias: get a BoilerLogEntry by id | PlantManager, Operator |
| GET | `/plants/boiler-log-entries` | Flat alias: list log entries with optional `boiler_id` / `recorded_by_operator_id` filters | PlantManager, Operator |
| GET | `/plants/chemistry-logs/{logId}` | Flat alias: get a ChemistryLog by id | PlantManager, Operator |
| GET | `/plants/chemistry-logs` | Flat alias: list chemistry logs with optional `boiler_id` / `recorded_by_operator_id` filters | PlantManager, Operator |
| GET | `/plants/inspections/{inspectionId}` | Flat alias: get an Inspection by id | PlantManager, Operator, Inspector |
| GET | `/plants/inspections` | Flat alias: list inspections with optional `boiler_id` filter | PlantManager, Operator, Inspector |
| GET | `/plants/steam-traps/{trapId}` | Flat alias: get a SteamTrap by id | PlantManager, Operator |
| GET | `/plants/steam-traps` | Flat alias: list steam traps with optional `plant_id` filter | PlantManager, Operator |
| GET | `/plants/load-dispatches/{dispatchId}` | Flat alias: get a LoadDispatch by id | PlantManager, Operator |
| GET | `/plants/load-dispatches` | Flat alias: list dispatches with optional `plant_id` filter | PlantManager, Operator |
| GET | `/plants/incidents/{incidentId}` | Flat alias: get an Incident by id | PlantManager, Operator |
| GET | `/plants/incidents` | Flat alias: list incidents with optional `plant_id` / `raised_by_operator_id` / `triggered_boiler_id` filters | PlantManager, Operator |
| GET | `/plants/fuel-deliveries/{deliveryId}` | Flat alias: get a FuelDelivery by id | PlantManager, Operator |
| GET | `/plants/fuel-deliveries` | Flat alias: list fuel deliveries with optional `plant_id` filter | PlantManager, Operator |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_WATER_CRITICAL` | 422 |
| `ERR_WATER_OUT_OF_SPEC` | 422 |
| `ERR_NO_VALID_CHEMISTRY` | 422 |
| `ERR_CERT_NOT_VALID` | 422 |
| `ERR_PLANT_EMERGENCY` | 422 |
| `ERR_OPERATOR_LICENSE_INVALID` | 422 |
| `ERR_LICENSE_WRONG_STATE` | 422 |
| `ERR_SOD_VERIFICATION` | 422 |
| `ERR_REFERENCED_NOT_FOUND` | 422 |
| `ERR_DISPATCH_WINDOW_CONFLICT` | 409 |
| `ERR_INSPECTION_SCHEDULE_CONFLICT` | 409 |
| `ERR_RELIEF_SETPOINT_EXCEEDED` | 422 |
| `ERR_RELIEF_NO_LIFT` | 422 |
| `ERR_DUPLICATE_TAG` | 409 |
| `ERR_FUEL_INVENTORY_UNDERFLOW` | 422 |
| `ERR_LEAD_CANNOT_BANK` | 422 |
| `ERR_RESOLUTION_NOTES_REQUIRED` | 422 |
| `ERR_INCIDENT_NOT_CLOSABLE` | 409 |
| `ERR_INCIDENT_UNRESOLVED` | 422 |
| `ERR_REINSPECTION_REQUIRED` | 422 |
| `ERR_BOILER_IN_DISPATCH` | 422 |

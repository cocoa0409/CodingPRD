# Parking Structure Ops API — Product Requirements Document

## 1. Introduction

Operating a structured parking facility means running several businesses at once. A transient parker rolls up to a gate and expects a fair, tariff-driven price; a monthly parker expects a guaranteed stall and a credential that works every morning; the ownership group expects concrete, waterproofing, lighting, and drains to be maintained on evidence rather than anecdote; and the controller expects every dollar that passes through a cashier's drawer to reconcile at the end of the day. This document specifies the Parking Structure Ops API — the service contract through which a parking-garage operator supervises access and revenue-control equipment, publishes rate schedules, administers monthly parking agreements and the badges and transponders tied to them, plans structural inspections and capital repairs, schedules housekeeping and security rounds, operates EV charging infrastructure, runs event surges, and reconciles revenue against theft controls. All endpoints are mounted under the `/ops` prefix.

The design favors determinism and auditability over convenience. Every timestamp the system records is read from a logical clock rather than the host wall clock, so tariff boundaries, proration, utilization windows, and close-of-business runs are perfectly reproducible. Every monetary figure is an integer number of cents. Every lifecycle is an explicit state machine, and the transitions that carry financial or safety weight — publishing a tariff, activating an agreement, filing a structural report, approving a reconciliation — are gated by named checks with named error codes. Seven operator roles share the surface, with segregation of duties enforced between the attendants who handle cash and the auditors who reconcile it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming one of the seven declared roles: `FacilityManager`, `ParkingAttendant`, `RevenueAuditor`, `MaintenanceSupervisor`, `SecurityOfficer`, `GateDevice`, and `MonthlyParker`. A request missing either header, or carrying a role outside this list, is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400). Once identified, the caller's role must appear in the endpoint's authorized role list; a caller whose role is not listed is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `GateDevice`, `X-User-ID` is the `id` of the acting AccessDevice; ownership checks compare it against the device being acted upon — the device identifier in the path for heartbeat and fault reporting, and the `entry_device_id` supplied in the body when recording a gate entry — and a mismatch is rejected with `ERR_DEVICE_IDENTITY_MISMATCH` (HTTP 403). When `X-User-Role` is `MonthlyParker`, `X-User-ID` is the `id` of the acting ParkerAccount; ownership checks on any resource that references a parker compare that resource's parker-account foreign key against `X-User-ID`, so a parker attempting to report another parker's credential lost or withdraw another parker's waitlisted agreement is rejected with `ERR_NOT_OWNER` (HTTP 403).

When `X-User-Role` is `FacilityManager`, `ParkingAttendant`, `RevenueAuditor`, `MaintenanceSupervisor`, or `SecurityOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands an actor — as `attendant_user_id` on an opened shift, `officer_user_id` on a scheduled patrol round, or `auditor_user_id` on a submitted reconciliation — and later compares the caller's header against those recorded values for ownership and segregation checks; an attendant attempting to close another attendant's shift is rejected with `ERR_NOT_OWNER`. Segregation of duties runs through the revenue chain: the auditor who opens, submits, or approves a reconciliation must differ from the attendant whose drawer is under review, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Endpoints that return lists accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Interval Semantics

All time inside the system is logical time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to the host's wall clock; every `entry_at`, `exit_at`, `activated_at`, `created_at`, heartbeat stamp, and close-of-business business date is read from this clock. A `FacilityManager`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`.

Scheduled work is expressed as half-open intervals. A maintenance window or event booking occupies the time from its start up to but not including its end; two intervals that merely touch at an endpoint do not overlap, and an end must be strictly after its start. Elapsed durations discard sub-minute remainders — durations are measured in whole minutes.

### 2.5. Common Resource Properties

Every resource in the system — facilities, rate schedules, access devices, parker accounts, monthly agreements, credentials, parking sessions, attendant shifts, reconciliation records, structural inspections, repair projects, maintenance windows, patrol rounds, incident reports, EV chargers, charging sessions, and event bookings — carries the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` field records the creation instant as an ISO 8601 UTC timestamp with three fractional digits; `updated_at` follows the same format and refreshes on every mutation. The `version` field is an integer that increments by one on every mutation of the resource, including mutations driven by a cascade from another resource — wherever §3 states that a Facility's version advances, that bump accompanies the posture or counter change described there. Figures described as *derived on read* — a facility's `occupied_spaces`, its `monthly_allocated`, and the dashboard's `available_transient_spaces` — are computed when the resource is read and never themselves increment `version`.

### 2.6. Money, Rates, and Rounding Conventions

All monetary amounts are integer numbers of cents, carried in fields suffixed `_cents`; the API never emits fractional currency. Where a computation divides — prorating a first month, splitting a deposit, levying the day's collections — the quotient is rounded half-up to whole cents. Multi-component amounts are rounded per component first and only then summed; §3.4 pins this order for the prorated first invoice. Percentages, used only by EV utilization reporting, carry exactly two decimal places and are rounded half-up. Billed parking time rounds the opposite direction: a partial hour inside a capped segment always rounds up to the next whole hour.

### 2.7. Optimistic Concurrency Control

Two writes are version-guarded, and only these two. Publishing a rate schedule requires the request to carry `expected_facility_version`, the `version` of the owning Facility the client last observed. If that value does not match the facility's current `version` — because a prior publish, a posture transition, a close-of-business run, or a cascade has advanced the facility since the client's read — the publish is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412), protecting the client from superseding a tariff landscape it has not observed. Amending a monthly agreement likewise requires `expected_agreement_version` matching the agreement's current `version`; a stale value is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). Endpoints not named here do not accept a version field, and no version check is optional on the two that do.

### 2.8. The Enforcement Pipeline

Incoming requests are checked in a fixed pipeline order, and when several checks could fail, the earliest failure is the one reported. The pipeline runs as follows:

1. **Context headers** — `X-User-ID` and `X-User-Role` present and the role declared, else `ERR_MISSING_CONTEXT_HEADER`.
2. **Role authorization** — the caller's role listed for the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. **Identity bindings** — device identity on gate-device calls, parker ownership on parker self-service calls, shift ownership on shift close, else `ERR_DEVICE_IDENTITY_MISMATCH` or `ERR_NOT_OWNER`.
4. **Segregation of duties** — reconciliation open, submit, and approve by an auditor other than the shift's attendant, else `ERR_SEGREGATION_OF_DUTIES`.
5. **Path existence** — path identifiers resolve, validated left to right, else `ERR_NOT_FOUND`.
6. **Body references** — identifiers supplied in the payload resolve, else `ERR_REFERENCE_NOT_FOUND`.
7. **Field validation** — required fields present, enum values in range, numeric ranges respected (inspection ratings 1 through 5, strictly positive amounts where declared, and so on), else `ERR_VALIDATION`.
8. **Optimistic concurrency** — the two version guards of §2.7, else `ERR_STALE_FACILITY_VERSION` or `ERR_STALE_AGREEMENT_VERSION`.
9. **State legality** — the target resource's current state permits the requested transition; this covers wrong-from-state actions, terminal-state lockdown, and repeat runs such as a second close-of-business for one business date, else `ERR_INVALID_STATE_TRANSITION`.
10. **Posture gate** — the facility's posture admits the action, else `ERR_FACILITY_POSTURE_BLOCKS`.
11. **Manual posture legality** — release and decommission guards on posture transitions, else `ERR_POSTURE_TRANSITION_BLOCKED` or `ERR_STRUCTURAL_CRITICAL`.

Only after all eleven generic stages pass do endpoint-specific business checks fire — device-online and published-rate checks on entry, open-shift checks on cash operations, credential validity and issuability, the safety hold on housekeeping windows, time-range and overlap rules, the event-pool and staffing checks, capacity pools, fiscal bounds (the comp ceiling, the refund bound, reserve sufficiency), and referential guards (credentials outstanding, variance-incident linkage, inspection reported). Each workflow in §3 names its business checks in the order they are evaluated relative to one another; all of them sit behind the generic pipeline above.

### 2.9. Path Hierarchy and Reference Integrity

For any endpoint whose path contains resource identifiers, the server validates those identifiers left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource — later segments are never examined once an earlier one fails. Identifiers carried in the request body — `facility_id`, `shift_id`, `agreement_id`, `charger_id`, `credential_id`, `inspection_id`, `patrol_round_id`, `reconciliation_id`, `duplicate_of_incident_id`, `incident_id`, and `supersedes_schedule_id` — must each name an existing resource, or the request fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404); the mark-duplicate workflow additionally treats a self-reference or an already-`CLOSED` target under the same code.

## 3. Business Logic & Workflows

### 3.1. Facility Onboarding, Operating Posture, and the Daily Close

A `FacilityManager` onboards a structure by supplying its `name`, its `total_spaces` (greater than zero), its `monthly_capacity` (the maximum number of monthly agreements permitted to consume a slot while `ACTIVE` or `SUSPENDED`), and its `event_pool_spaces` (the ceiling on combined presale allocations across mutually overlapping confirmed or active events, per §3.9). An optional `levy_pct` sets the fraction of the day's collections credited to the capital reserve at close-of-business; it defaults to 0.1 — ten percent — and must lie between 0 and 1 inclusive. A new facility opens in posture `NORMAL` with `closed_spaces`, `capital_reserve_cents`, `deposit_liability_cents`, and `cumulative_collected_cents` at zero, and `last_close_date` null until the first close run completes. The facility list can be filtered by `posture`.

Every facility carries an operating posture drawn from `NORMAL`, `EVENT_SURGE`, `RESTRICTED`, `CLOSED_TEMPORARY`, and `DECOMMISSIONED`. `EVENT_SURGE` is never a manual target: the system enters it when an event activates (§3.9) and leaves it when the facility's last `ACTIVE` event completes, and a manual posture request naming `EVENT_SURGE` as its `target_posture` is rejected with `ERR_POSTURE_TRANSITION_BLOCKED`. The manual moves a `FacilityManager` may request are: `NORMAL` to `RESTRICTED`; `NORMAL` or `RESTRICTED` to `CLOSED_TEMPORARY`; release from `RESTRICTED` or `CLOSED_TEMPORARY` back to `NORMAL`; and decommissioning from `NORMAL`, `RESTRICTED`, or `CLOSED_TEMPORARY` to the terminal `DECOMMISSIONED`. Release to `NORMAL` is guarded twice — no inspection of the facility may stand `REPORTED` with a `condition_class` of `CRITICAL` (else `ERR_STRUCTURAL_CRITICAL`), and no incident of severity `CRITICAL` may stand `OPEN` or `INVESTIGATING` (else `ERR_POSTURE_TRANSITION_BLOCKED`). Decommissioning is guarded by workload: no session may be `PARKED`, no agreement may stand `APPROVED`, `ACTIVE`, or `SUSPENDED`, no repair project may stand `PROPOSED`, `FUNDED`, `SCHEDULED`, `IN_PROGRESS`, or `DEFERRED`, and no event may stand `CONFIRMED` or `ACTIVE` — any violation rejects the move with `ERR_POSTURE_TRANSITION_BLOCKED`. Every manual posture transition advances the facility's `version` by one. Two automatic escalations also land on `RESTRICTED`: the filing of a `CRITICAL` structural report (§3.6), and a close-of-business run that finds a `CRITICAL` incident still unresolved (below).

Posture gates the lane and the back office alike. A transient entry is admitted only while posture is `NORMAL` or `EVENT_SURGE`; a credentialed monthly entry is additionally admitted under `RESTRICTED`. Under `CLOSED_TEMPORARY` or `DECOMMISSIONED` every entry is refused, and monthly-agreement creation and activation as well as event confirmation and activation are refused alongside — all with `ERR_FACILITY_POSTURE_BLOCKS`.

A computed operational snapshot is available per facility, reporting `posture`, `occupied_spaces`, `closed_spaces`, `available_transient_spaces`, `monthly_allocated`, `monthly_capacity`, `capital_reserve_cents`, `deposit_liability_cents`, and `cumulative_collected_cents`. Occupancy pressure is pure derivation: `occupied_spaces` counts the facility's sessions standing `PARKED`, `monthly_allocated` counts its agreements standing `ACTIVE` or `SUSPENDED`, and `available_transient_spaces` is `total_spaces` minus `closed_spaces` minus `occupied_spaces`. Because these figures are derived at read time, reading a dashboard never mutates the facility and never advances its `version`.

Once per business date, a `FacilityManager` runs the close-of-business for the facility, keyed to the logical clock's current date. The run is refused with `ERR_INVALID_STATE_TRANSITION` when the facility is `DECOMMISSIONED`, and likewise when the business date is not strictly after `last_close_date` — a second close for an already-closed date is not a legal repeat. A successful run sweeps every operational corner of the facility in one pass. Shifts still `OPEN` are force-closed to `FORCE_CLOSED` with `closed_at` stamped, `counted_cash_cents` left null, and expected cash computed per §3.5. For each shift standing `CLOSED` or `FORCE_CLOSED` that lacks a non-terminal reconciliation — one still `DRAFT`, `SUBMITTED`, or `VARIANCE_REVIEW` — a fresh reconciliation is opened in `DRAFT`. The monthly waitlist promotes per §3.4. Housekeeping windows standing `SCHEDULED` or `IN_PROGRESS` whose `end_at` is strictly before the run instant flip to `MISSED`, and patrol rounds standing `SCHEDULED` whose `scheduled_start` is strictly before the run instant without ever completing flip to `MISSED` as well. Devices whose `last_heartbeat_at` is null, or older than twenty-four hours before the run time, fall from `ONLINE` or `DEGRADED` to `OFFLINE`. EV charger utilization is recomputed and review flags updated per §3.8. And if the facility stands `NORMAL` while any incident of severity `CRITICAL` remains `OPEN` or `INVESTIGATING`, posture escalates to `RESTRICTED`.

The same run settles the facility's capital levy. The day's gross collection is the sum of `settled_fee_cents` over sessions settled on that business date under any tender, minus the sum of `refunded_cents` over refunds issued on that date. The levy is the positive part of that gross — a negative-gross day levies zero — multiplied by the facility's `levy_pct`, rounded half-up to whole cents, and `capital_reserve_cents` grows by exactly that levy. The day's net revenue is then reported as gross minus levy; this net figure is derived after the levy is fixed and is never fed back into the levy's own computation. `last_close_date` is set to the run's business date, and the facility's `version` advances by one. The run answers with a summary whose `business_date` names the closed date and whose counters — `shifts_force_closed`, `reconciliations_created`, `agreements_promoted`, `windows_marked_missed`, `patrols_marked_missed`, `devices_marked_offline`, `levy_credited_cents`, and `chargers_flagged` — report how much work the sweep performed.

### 3.2. Rate Schedules and the Transient Fee Engine

Tariffs live on rate schedules. A `FacilityManager` drafts one against a `facility_id` with a human `label`, the lane parameters `grace_minutes`, `first_hour_cents`, `additional_hour_cents`, `daily_max_cents` (strictly positive; the other three at least zero), the flat `event_flat_cents`, the per-day `lost_ticket_daily_cents`, and an `effective_from` marking the earliest logical instant at which the schedule may be pinned at entry. An optional `cap_mode` chooses the daily-cap segmentation — `CALENDAR_DAY` when omitted, or `ROLLING_24H` — and an optional `supersedes_schedule_id` declares which earlier schedule this card replaces. A new schedule stands `DRAFT` with `published_at` null. The schedule list filters by `facility_id`, `schedule_status`, or `supersedes_schedule_id`.

Publishing is the version-guarded write of §2.7: the request must carry `expected_facility_version` matching the facility's current `version`, or it fails with `ERR_STALE_FACILITY_VERSION`. A successful publish moves the schedule from `DRAFT` to `PUBLISHED`, flips any other `PUBLISHED` schedule of the same facility to `SUPERSEDED`, stamps `published_at` with the logical now, and advances the facility's `version` by one — a facility therefore has at most one `PUBLISHED` schedule at a time. A schedule still `DRAFT` or currently `PUBLISHED` may be retired to `RETIRED`; both `SUPERSEDED` and `RETIRED` are terminal. Entry to the facility requires that some `PUBLISHED` schedule have `effective_from` at or before the logical now — otherwise the entry fails with `ERR_NO_PUBLISHED_RATE`. Once a session has entered, the schedule pinned at entry (recorded as the session's `rate_schedule_id`) governs that session for its entire life, even if the schedule is later `SUPERSEDED`; this version-pinning is deliberate, so a parker always pays against the tariff that was live when they pulled in.

The transient fee engine rates a session from three inputs: the session's `entry_at`, the rating moment (always the logical now), and the pinned schedule — modulated by the session's `fee_mode`. Four modes exist. Under `MONTHLY` — a session that entered on a monthly credential — the fee is zero regardless of duration. Under `EVENT_FLAT`, the fee is the schedule's `event_flat_cents`, duration-independent. Under `LOST_TICKET`, the fee is `lost_ticket_daily_cents` multiplied by the number of distinct calendar dates the stay touches between `entry_at` and the rating moment; even a stay contained within a single date counts one date, so the multiplier is at least one.

Under `STANDARD`, elapsed time is the whole minutes between `entry_at` and the rating moment. When that minute count is no greater than `grace_minutes` the fee is zero — a stay of exactly the grace length still exits free. Once grace is exceeded, billing starts from minute zero: the grace minutes are not subtracted from the stay. Billed time is then segmented by the pinned `cap_mode`. Under `CALENDAR_DAY`, the interval from entry to the rating moment is split at each local midnight into per-date segments; within a segment, billed hours are the segment's minutes divided by sixty and rounded up — any partial hour bills as a full hour — and the segment charge is `first_hour_cents` plus `additional_hour_cents` multiplied by the hours beyond the first (never fewer than zero additional hours), capped so the segment never exceeds `daily_max_cents`. The fee is the sum of segment charges. Under `ROLLING_24H`, the identical per-window formula applies, but the stay divides into consecutive twenty-four-hour windows anchored at the entry instant rather than at calendar midnights. All fee outputs are integer cents.

### 3.3. Gate Devices and the Parking Session Lifecycle

Access and revenue-control hardware is registered per facility with a `device_label` (for example, "Entry Lane 1") and a `device_kind` of `ENTRY_GATE`, `EXIT_GATE`, or `PAY_STATION`. A new device stands `OFFLINE` with `device_mode` `STANDARD` and `last_heartbeat_at` null until its first heartbeat. A device proves liveness by heartbeating on itself: the caller's `X-User-ID` must equal the device's own `id` — a mismatch fails with `ERR_DEVICE_IDENTITY_MISMATCH` — and a successful heartbeat moves the device from `OFFLINE` or `DEGRADED` to `ONLINE`, stamping `last_heartbeat_at` with the logical now. Fault reporting, by the device itself or by a `FacilityManager`, carries a free-text `fault_description` and moves an `ONLINE` device to `DEGRADED`. Decommissioning moves a device from `OFFLINE`, `ONLINE`, or `DEGRADED` to the terminal `DECOMMISSIONED` and forces its `device_mode` back to `STANDARD`. Two cascades also act on devices: an event surge flips every `ONLINE` device of the facility from `STANDARD` to `EVENT` mode and later back (§3.9), and the close-of-business sweep drops heartbeat-stale devices to `OFFLINE` (§3.1). The device list filters by `facility_id` or `device_status`.

A parking session begins when a `GateDevice` records an entry with the `facility_id`, its own `entry_device_id`, and a `ticket_barcode`, optionally presenting a monthly `credential_id`. Business checks fire in this order: the entry device must stand `ONLINE` and belong to the named facility (`ERR_DEVICE_NOT_ONLINE`); the posture gate of §3.1 must admit the entry (`ERR_FACILITY_POSTURE_BLOCKS`); a `PUBLISHED` rate schedule with `effective_from` at or before now must exist (`ERR_NO_PUBLISHED_RATE`); the barcode must not already be in use by another `PARKED` session of the same facility (`ERR_DUPLICATE_TICKET`); and when a credential is presented, that credential must stand `ACTIVE` and its agreement must stand `ACTIVE` (`ERR_CREDENTIAL_NOT_VALID`). A recorded entry stands `PARKED` with billing `OPEN`, `entry_at` read from the logical clock, the facility's effective `PUBLISHED` schedule pinned into `rate_schedule_id`, and `fee_mode` pinned by precedence — `MONTHLY` when a credential was presented, else `EVENT_FLAT` when the entry device stands in `EVENT` mode, else `STANDARD`. The facility's `occupied_spaces` reflects the new arrival immediately, being derived on read.

While the vehicle is inside, the two dimensions of a session move in parallel: `occupancy_state` (`PARKED`, then terminal `EXITED`) and `billing_state` (`OPEN`, `QUOTED`, `SETTLED`, `COMPED`, `REFUNDED`). Quoting asks the fee engine for the would-be charge at the logical now; it requires the session still `PARKED`, moves billing from `OPEN` to `QUOTED`, stores the figure on `quoted_fee_cents`, and answers with `fee_cents`, the rating instant `as_of`, and the session's `fee_mode`. Re-quoting a `QUOTED` session is legal and simply re-rates at the new now, refreshing `quoted_fee_cents`.

Settlement is chronological, not provisional: paying recomputes the fee at the pay moment from the pinned schedule rather than honoring an earlier quote. A `ParkingAttendant` settles a session still `PARKED` and still `OPEN` or `QUOTED` by naming a `tender_type` of `CASH` or `CARD`. Payment in `CASH` additionally requires a `shift_id` naming an `OPEN` shift at the same facility whose `attendant_user_id` equals the caller — otherwise `ERR_SHIFT_NOT_OPEN`. On settlement the billing moves to `SETTLED`, `settled_fee_cents` records the computed amount, `tender_type` is stored, the facility's `cumulative_collected_cents` grows by the settled amount, and for cash the session's `paid_in_shift_id` ties it to the collecting shift, whose expected-cash derivation gains the fee (§3.5).

An attendant may instead comp the session — waiving the fee entirely — by supplying a `reason` and a `shift_id` naming an `OPEN` shift at the facility owned by the caller (`ERR_SHIFT_NOT_OPEN` otherwise). Comping requires the session still `PARKED` and `OPEN` or `QUOTED`, and it is capped: the shift's `comp_total_cents` plus the fee being waived must not exceed a per-shift ceiling of 5,000 cents, or the request fails with `ERR_COMP_LIMIT_EXCEEDED` (HTTP 422). A comped session moves to the terminal `COMPED` with `settled_fee_cents` zero and `tender_type` `NONE`, while the shift's `comp_total_cents` grows by the waived fee's value.

Exit is the gate's act. A session may leave when its billing stands `SETTLED` or `COMPED`; it may also leave while billing is still `OPEN` or `QUOTED` when the fee computed at the exit moment is zero, in which case the exit itself auto-settles — billing moves to `SETTLED` with `settled_fee_cents` zero and `tender_type` `NONE`. Any other exit attempt, with a positive fee still outstanding, is refused with `ERR_EXIT_UNPAID`. A recorded exit moves occupancy to the terminal `EXITED`, stamps `exit_at`, and the derived `occupied_spaces` count falls by one.

When a transient parker loses their ticket, an attendant converts the session to lost-ticket rating: the session must still be `OPEN` or `QUOTED`, its `fee_mode` flips to `LOST_TICKET`, and `quoted_fee_cents` is recomputed at the logical now under the per-calendar-day rule of §3.2.

After settlement, a `RevenueAuditor` may refund a `SETTLED` session in full or in part by naming `amount_cents` and a `reason`. The amount must not exceed the session's `settled_fee_cents`, else the refund fails with `ERR_REFUND_EXCEEDS_COLLECTED` (HTTP 422). A recorded refund moves billing to the terminal `REFUNDED`, stores `refunded_cents` equal to the refunded amount, stamps `refunded_at`, and subtracts the amount from the facility's `cumulative_collected_cents` — the compensating pair to settlement. When the refunded session had been settled in `CASH` and the collecting shift is not yet `RECONCILED`, that shift's expected-cash derivation loses the refunded amount; once the shift stands `RECONCILED` its expected figure is frozen and the refund leaves it untouched (§3.5).

The session list filters by `facility_id`, `credential_id`, `rate_schedule_id`, `entry_device_id`, `paid_in_shift_id`, `occupancy_state`, or `billing_state`. Until settlement, `settled_fee_cents` and `tender_type` remain null; until a quote, `quoted_fee_cents` is null; until a refund, `refunded_cents` and `refunded_at` are null; `exit_at` is null while `PARKED`; `credential_id` is null for transient tickets; and `paid_in_shift_id` is null unless the session settled in cash.

### 3.4. Monthly Agreements, Waitlists, and Credentials

Monthly parkers are front-desk records first: a `FacilityManager` or `ParkingAttendant` creates a parker account with the parker's `full_name` and contact `email`, and `email` must be unique across all parker accounts; the account list filters by `email`. An agreement is then submitted against a `facility_id` and `parker_account_id` with a service `tier` of `STANDARD`, `PREMIUM`, or `EV`, a full-month `monthly_rate_cents` (strictly positive), and an optional `ev_surcharge_cents` defaulting to zero. Submission lands in `SUBMITTED` and is evaluated synchronously against the facility's monthly pool: when the number of the facility's agreements standing `ACTIVE` or `SUSPENDED` is strictly below `monthly_capacity`, the new agreement is `APPROVED` on the spot; otherwise it falls to `WAITLISTED`. Either outcome is already visible in the creation response at version 1. Each agreement receives an `application_seq`, a per-facility monotonic sequence starting at 1 that later serves as the waitlist tie-break and the demotion ordering. Agreement creation is subject to the posture gate of §3.1 — a `CLOSED_TEMPORARY` or `DECOMMISSIONED` facility refuses new agreements with `ERR_FACILITY_POSTURE_BLOCKS`. The agreement list filters by `facility_id`, `parker_account_id`, or `agreement_status`.

The monthly pool obeys one arithmetic everywhere. The *allocated* count is the agreements standing `ACTIVE` or `SUSPENDED`; the *committed* count adds those standing `APPROVED`. Creation approves while allocated is strictly below `monthly_capacity`. Activation — moving an `APPROVED` agreement to `ACTIVE` — requires the same strict headroom and refuses with `ERR_MONTHLY_POOL_EXHAUSTED` when the facility already holds exactly `monthly_capacity` allocated agreements; the boundary is exclusionary, so equality blocks. Activation also requires the facility posture not be `CLOSED_TEMPORARY` or `DECOMMISSIONED` (`ERR_FACILITY_POSTURE_BLOCKS`). A successful activation stamps `activated_at` with the logical now and computes `first_invoice_cents` by proration.

Proration pins its rounding order. Let the days-in-month be the length of the calendar month containing `activated_at`, and the remaining days be the days-in-month minus the day-of-month of activation plus one — the activation day itself counts. The prorated rent is `monthly_rate_cents` multiplied by the remaining days and divided by the days-in-month, rounded half-up to whole cents; the prorated EV portion applies the identical formula to `ev_surcharge_cents`, again rounded half-up to whole cents; `first_invoice_cents` is the sum of the two already-rounded components. Summing the unrounded components and rounding once is explicitly not the rule — with a rate of 19,999 cents and an EV surcharge of 2,999 cents activated with 18 of 31 days remaining, the per-component order yields 11,612 plus 1,741 equals 13,353 cents, where sum-then-round would yield 13,354.

An `ACTIVE` agreement may be suspended by a `FacilityManager` (`ACTIVE` to `SUSPENDED`) and later resumed (`SUSPENDED` back to `ACTIVE`); suspension leaves the agreement's credentials standing `ACTIVE` but entry with them is blocked for the duration, because credentialed entry requires an `ACTIVE` agreement (§3.3). Termination moves an agreement from `APPROVED`, `ACTIVE`, or `SUSPENDED` to the terminal `TERMINATED`, but only once no credential of the agreement still stands `ACTIVE` or `LOST_REPORTED` — outstanding media reject the termination with `ERR_CREDENTIALS_OUTSTANDING`. A `WAITLISTED` agreement may instead be withdrawn to the terminal `WITHDRAWN` by a `FacilityManager`, a `ParkingAttendant`, or the owning `MonthlyParker`; a parker may withdraw only their own agreement, with ownership checked against the agreement's `parker_account_id` (`ERR_NOT_OWNER`).

Rate changes on a live agreement go through the version-guarded amend of §2.7: the request carries `expected_agreement_version` matching the agreement's current `version` — else `ERR_STALE_AGREEMENT_VERSION` — together with a new `monthly_rate_cents`, a new `ev_surcharge_cents`, or both, and a successful amend advances the agreement's `version` by one.

The waitlist moves at close-of-business. While the committed count is strictly below `monthly_capacity` and the waitlist is non-empty, the top-ranked `WAITLISTED` agreement promotes to `APPROVED` and the ranking recomputes. Ranking is chronological — earliest `created_at` first — with exact `created_at` ties broken by the lower `application_seq`; the record `id` is never a tiebreaker. Demotion runs the other direction when a `CRITICAL` structural report shrinks effective capacity (§3.6): while committed exceeds the effective capacity — the smaller of `monthly_capacity` and `total_spaces` minus `closed_spaces` — the newest `APPROVED` agreement by descending `application_seq` is demoted back to `WAITLISTED`, and each demotion revokes that agreement's media as described below.

Credentials are the physical media of an agreement. A `ParkingAttendant` issues a `BADGE` or `TRANSPONDER` — the `credential_type` — against an `agreement_id` with a refundable `deposit_cents` (at least zero). Issuance requires the agreement to stand `APPROVED` or `ACTIVE` (else `ERR_AGREEMENT_NOT_ISSUABLE`), and an agreement may hold at most two credentials standing `ACTIVE` or `LOST_REPORTED` (else `ERR_CREDENTIAL_LIMIT`). A new credential stands `ACTIVE`, and the facility's `deposit_liability_cents` — the running sum of `deposit_cents` over all credentials standing `ACTIVE` or `LOST_REPORTED` — grows by the deposit. The credential list filters by `agreement_id`, `credential_status`, or `replaced_by_credential_id`.

The media lifecycle runs `ACTIVE` to `LOST_REPORTED` when the owning `MonthlyParker` or a `ParkingAttendant` reports the credential lost, and `LOST_REPORTED` back to `ACTIVE` when it is reported found; parker self-service is ownership-checked (`ERR_NOT_OWNER`). Replacement moves an `ACTIVE` or `LOST_REPORTED` credential to the terminal `REPLACED`: a successor credential is minted for the same agreement standing `ACTIVE` and carrying the same `deposit_cents` and the requested `credential_type`, the retired credential's `replaced_by_credential_id` points at its successor, the response presents the new credential, and the deposit liability is unchanged because the deposit carries over. Returning an `ACTIVE` or `LOST_REPORTED` credential moves it to the terminal `RETURNED` and refunds the deposit — `deposit_liability_cents` falls by `deposit_cents`. Revoking one — by a `ParkingAttendant`, a `FacilityManager`, or the system during the demotion cascade — moves it to the terminal `REVOKED` and forfeits the deposit, so `deposit_liability_cents` likewise falls by `deposit_cents`.

### 3.5. Shifts, Cash Control, and Reconciliation

Cash handling is shift-scoped. A `ParkingAttendant` opens a shift with a `facility_id` and an `opening_float_cents` (at least zero); the caller's `X-User-ID` is captured as `attendant_user_id`, `opened_at` is stamped from the logical clock, and the shift stands `OPEN` with `over_ring_cents`, `paid_out_cents`, and `comp_total_cents` at zero and `closed_at` null while the shift remains open. One attendant holds at most one `OPEN` shift per facility — a second open attempt fails with `ERR_SHIFT_ALREADY_OPEN`. The shift list filters by `facility_id`, `attendant_user_id`, or `shift_status`.

The drawer's expectation is a waterfall computed in a fixed order: start from `opening_float_cents`, add the `settled_fee_cents` of every session tied to the shift through `paid_in_shift_id` with `tender_type` `CASH` and billing standing `SETTLED` or `REFUNDED`, subtract the `refunded_cents` of those cash sessions that have been refunded — this subtraction applies only while the shift is not yet `RECONCILED` — then subtract `paid_out_cents`, and finally add `over_ring_cents`. The result is `expected_cash_cents`, computed at shift close, at a close-of-business force-close, at reconciliation submit, and whenever a cash-settled session is refunded. Comp grants never touch the drawer; they accumulate separately on `comp_total_cents` against the 5,000-cent ceiling of §3.3.

Closing a shift is the attendant's own act — the caller must be the shift's `attendant_user_id`, else `ERR_NOT_OWNER`. The attendant submits the declared drawer count `counted_cash_cents`, optionally with final `over_ring_cents` and `paid_out_cents` corrections; the shift moves to `CLOSED`, `closed_at` is stamped, and `expected_cash_cents` is computed. A shift abandoned `OPEN` is force-closed by the close-of-business run to `FORCE_CLOSED` with `closed_at` stamped, `counted_cash_cents` left null, and expectation still computed. Both `CLOSED` and `FORCE_CLOSED` reach the terminal `RECONCILED` only through an approved reconciliation.

Reconciliation is the auditor's counterweight, and segregation of duties (§2.1) applies at all three of its steps. A `RevenueAuditor` — never the attendant whose drawer is under review — opens a reconciliation against a `shift_id` for a `CLOSED` or `FORCE_CLOSED` shift that has no non-terminal record; the new record stands `DRAFT` with `auditor_user_id` and `variance_cents` still null. The reconciliation list filters by `shift_id` or `reconciliation_status`.

Submission computes the variance: `variance_cents` is the shift's `counted_cash_cents` minus its `expected_cash_cents`. A shift with no declared count cannot be submitted at all — the attempt fails field validation with `ERR_VALIDATION`. Thresholds route the outcome, and both thresholds are inclusive. A variance at or below a shortage of 2,000 cents — exactly −2,000 breaches — or at or above an overage of 5,000 cents — exactly +5,000 breaches — routes the record to `VARIANCE_REVIEW`; anything strictly between those lines lands in `SUBMITTED`. Either way `auditor_user_id` is captured from the caller. The `VARIANCE_REVIEW` route also auto-creates an incident: an `IncidentReport` of `incident_type` `CASH_VARIANCE` whose `reconciliation_id` names this record, `auto_created` true, standing `OPEN`, with severity `HIGH` when the absolute variance reaches 10,000 cents and `MEDIUM` below that.

Approval ends the loop. Approving a `SUBMITTED` record moves it to the terminal `APPROVED` and moves its shift from `CLOSED` or `FORCE_CLOSED` to `RECONCILED`. Approving from `VARIANCE_REVIEW` additionally requires an `incident_id` naming the linked incident — one whose `reconciliation_id` is this record, whose `incident_type` is `CASH_VARIANCE`, and whose `incident_status` stands `INVESTIGATING`; without it the approval fails with `ERR_VARIANCE_INCIDENT_REQUIRED`. That approval resolves the linked incident (`INVESTIGATING` to `RESOLVED`) in the same act and reconciles the shift. Segregation rejects any approval attempted by the shift's own attendant with `ERR_SEGREGATION_OF_DUTIES`.

### 3.6. Structural Inspections, Capital Reserve, and Repair Projects

Structural health begins with scheduled fieldwork. A `MaintenanceSupervisor` schedules an inspection with a `facility_id`, a `level_scope` naming the level or zone (for example, "L2"), and a `scheduled_for` field date; the inspection stands `SCHEDULED` with its ratings, `condition_index`, and `condition_class` all null and `closed_space_count` at zero. Beginning fieldwork moves it to `IN_FIELD`; either `SCHEDULED` or `IN_FIELD` may be cancelled to the terminal `CANCELLED`. The inspection list filters by `facility_id` or `inspection_status`.

Filing the report is the consequential act. The supervisor supplies three element ratings — `load_bearing_rating`, `waterproofing_rating`, and `surface_rating` — each a whole number from 1 to 5 inclusive (anything else fails `ERR_VALIDATION`), optionally with a `closed_space_count` of stalls the findings take out of service. The condition index is twenty times the weighted sum of the ratings — load-bearing at half weight, waterproofing at three-tenths, surface at one-fifth — rounded half-up to a whole number, so the index spans 20 to 100. The class follows: `CRITICAL` when the load-bearing rating is 2 or lower or the index falls below 40; otherwise `FAIR` when the index falls below 70; otherwise `SOUND`. The load-bearing override dominates the arithmetic — ratings of (2, 5, 5) produce an index of 70 yet classify `CRITICAL`, not `SOUND`. The report lands the inspection in the terminal `REPORTED` with `condition_index` and `condition_class` stored.

A `CRITICAL` report fires a three-link cascade. First, the facility's posture moves to `RESTRICTED`, its `closed_spaces` grows by the report's `closed_space_count`, and its `version` advances by one. Second, the effective monthly capacity shrinks to the smaller of `monthly_capacity` and `total_spaces` minus the new `closed_spaces`, and the demotion loop of §3.4 runs: while committed agreements exceed effective capacity, the newest `APPROVED` agreement by descending `application_seq` flips to `WAITLISTED`. Third, for each demoted agreement, every credential standing `ACTIVE` flips to `REVOKED` and its deposit is refunded out of `deposit_liability_cents`.

The capital reserve funds the response. Its `capital_reserve_cents` balance accumulates the daily levy of §3.1 and is drawn down by repair funding and restored by cancellation of funded work, as below. A `MaintenanceSupervisor` proposes a repair project with a `facility_id`, a `title` (for example, "L2 sealant replacement"), a `level_scope`, a strictly positive `estimated_cost_cents`, optionally the originating `inspection_id`, and optionally a `closed_space_count` of stalls the work will take out of service (default zero). The project stands `PROPOSED` with `funded_amount_cents` zero, `revision_count` zero, and both schedule stamps null. The project list filters by `facility_id`, `inspection_id`, or `project_status`.

Funding is the reserve draw. A `FacilityManager` funds a `PROPOSED` project with an `amount_cents`; when the project references an inspection, that inspection must already stand `REPORTED` (else `ERR_INSPECTION_NOT_REPORTED`), and the amount must not exceed the facility's current `capital_reserve_cents` (else `ERR_INSUFFICIENT_RESERVE`, HTTP 422). A funded project stands `FUNDED` with `funded_amount_cents` equal to the draw, and `capital_reserve_cents` falls by the same amount. A `MaintenanceSupervisor` then schedules the work with `start_at` and `end_at` — end strictly after start, else `ERR_INVALID_TIME_RANGE` — moving the project to `SCHEDULED` and stamping `scheduled_start_at` and `scheduled_end_at`. Starting the work moves it to `IN_PROGRESS`, grows the facility's `closed_spaces` by the project's `closed_space_count`, and advances the facility's `version`; closing out moves it to the terminal `CLOSED_OUT` and returns those spaces — `closed_spaces` falls by the same count and `version` advances again, the compensating pair to the start.

Two revision paths keep the pipeline honest. A `FacilityManager` may defer a `PROPOSED` project with a `reason`, moving it to `DEFERRED`; a `MaintenanceSupervisor` may later revise it back to `PROPOSED`, optionally restating `estimated_cost_cents`, and each revision increments `revision_count`. Cancellation from `PROPOSED`, `FUNDED`, or `DEFERRED` lands in the terminal `CANCELLED` — and when a `FUNDED` project is cancelled, its `funded_amount_cents` is returned to `capital_reserve_cents`, refunding the draw.

### 3.7. Housekeeping Windows, Patrol Rounds, and Incident Response

Routine upkeep is scheduled as maintenance windows. A `MaintenanceSupervisor` creates one with a `facility_id`, a `level`, a `window_type` of `SWEEPING`, `DRAIN_FLUSH`, `LIGHTING_REPAIR`, or `SEALANT_WORK`, and the half-open interval bounded by `start_at` and `end_at` — end strictly after start, else `ERR_INVALID_TIME_RANGE`. Windows on the same facility and level carry a thirty-minute hygiene buffer: a new window conflicts with any existing window standing `SCHEDULED` or `IN_PROGRESS` on that level unless the new start falls at or after thirty minutes past the existing window's end, or the existing window's start falls at or after thirty minutes past the new window's end; a conflict is rejected with `ERR_WINDOW_OVERLAP`. One more guard protects the public: when the facility has a `REPORTED` inspection classed `CRITICAL` whose `level_scope` matches the window's `level`, the window may be created only with `safety_authorized` explicitly true — otherwise the request fails with `ERR_SAFETY_HOLD`; the flag defaults to false. A created window stands `SCHEDULED`. Starting moves it to `IN_PROGRESS`, completing to the terminal `COMPLETED`, and a `SCHEDULED` window may be cancelled to the terminal `CANCELLED`; a window still `SCHEDULED` or `IN_PROGRESS` when its `end_at` falls strictly before a close-of-business run is swept to the terminal `MISSED` (§3.1). The window list filters by `facility_id`, `window_status`, or `level`.

Security and lighting patrols follow a lighter arc. A `SecurityOfficer` schedules a round with a `facility_id` and a `scheduled_start`; the caller's `X-User-ID` is captured as `officer_user_id` and the round stands `SCHEDULED`. Completing the round supplies `checkpoints_completed` and optionally `lighting_outages_found` (default zero), moves it to the terminal `COMPLETED`, and stamps `completed_at` — both counts null-free only from that point, with `checkpoints_completed` null while the round is unfinished. A round still `SCHEDULED` whose `scheduled_start` falls strictly before a close-of-business run, never having completed, is swept to the terminal `MISSED`. The round list filters by `facility_id` or `patrol_status`.

Incidents are the system of record for everything that goes wrong. A `SecurityOfficer`, `ParkingAttendant`, or `RevenueAuditor` files a report with a `facility_id`, an `incident_type` of `SECURITY`, `VEHICLE_DAMAGE`, `CASH_VARIANCE`, `VANDALISM`, or `SAFETY`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a free-text `description`, optionally tied to the observing `patrol_round_id` or a spawning `reconciliation_id`. A filed report stands `OPEN` with `auto_created` false — system-spawned variance incidents (§3.5) arrive with `auto_created` true. Investigation moves `OPEN` to `INVESTIGATING`; resolution moves `INVESTIGATING` to `RESOLVED` and records the `resolution_note` supplied with it; closing moves an `OPEN` or `RESOLVED` report to the terminal `CLOSED`. A report standing `OPEN` or `INVESTIGATING` may instead be marked a duplicate: the caller names a `duplicate_of_incident_id` that must resolve to a different report of the same facility not already `CLOSED` — a self-reference, an unknown id, or a `CLOSED` target fails with `ERR_REFERENCE_NOT_FOUND` — and the act both records the pointer and closes the reporting incident. The incident list filters by `facility_id`, `incident_status`, `severity`, `patrol_round_id`, `reconciliation_id`, or `duplicate_of_incident_id`. Severity carries operational weight beyond the ledger: an unresolved `CRITICAL` incident — standing `OPEN` or `INVESTIGATING` — blocks the manual posture release of §3.1 with `ERR_POSTURE_TRANSITION_BLOCKED`, and a close-of-business run that finds one escalates a `NORMAL` facility to `RESTRICTED`.

### 3.8. EV Charging Infrastructure and Utilization Review

Charging hardware follows a permit-to-retire pipeline under a `MaintenanceSupervisor`. A charger is proposed with a `facility_id`, a `charger_label` (for example, "EV-01"), and a nameplate `max_kw` strictly greater than zero, standing `PROPOSED`. Recording the electrical permit moves it to `PERMITTED`, physical installation to `INSTALLED`, and energizing to `COMMISSIONED` — the first commissioning stamps `commissioned_at` (null until that moment), and later recommissionings leave that original stamp untouched. A `COMMISSIONED` charger may be taken out of service (`COMMISSIONED` to `OUT_OF_SERVICE`) and returned (`OUT_OF_SERVICE` back to `COMMISSIONED`) as a cyclic pair; decommissioning to the terminal `DECOMMISSIONED` is permitted from `PROPOSED`, `PERMITTED`, `INSTALLED`, or `OUT_OF_SERVICE` — never directly from `COMMISSIONED`, so a live charger must be taken out of service first. The charger list filters by `facility_id` or `charger_status`.

A charging session begins on a charger named by `charger_id`, optionally billed to a monthly `agreement_id`. Three conditions gate the start, all reported as `ERR_CHARGER_UNAVAILABLE`: the charger must stand `COMMISSIONED`, it must have no other session standing `CHARGING`, and a supplied agreement must stand `ACTIVE`. A started session stands `CHARGING` with `started_at` stamped from the logical clock, `ended_at` and `kwh_delivered` still null, and `idle_minutes` zero. Completing the charge — by the parker, an attendant, or the supervisor — supplies the energy delivered `kwh_delivered` (strictly positive) and optionally the `idle_minutes` the vehicle stayed connected after charging finished (at least zero), moving the session to the terminal `COMPLETED` with `ended_at` stamped. Faulting the session, with a free-text `fault_description`, moves it to the terminal `FAULTED`, stamps `ended_at`, and cascades the charger from `COMMISSIONED` to `OUT_OF_SERVICE` in the same act. The session list filters by `charger_id`, `agreement_id`, or `session_status`.

Utilization is recomputed at every close-of-business for each charger that has ever commissioned — those with `commissioned_at` set, whether standing `COMMISSIONED` or `OUT_OF_SERVICE`. The measurement window opens at the later of the charger's `commissioned_at` and the business date minus twenty-eight days, and closes at the run instant; the whole minutes between them are the available minutes. Only `COMPLETED` sessions whose `ended_at` falls inside that window count — `FAULTED` sessions are excluded. The session-time basis, `utilization_session_pct`, is one hundred times the summed minutes from `started_at` to `ended_at` across those eligible sessions, divided by the available minutes, rounded half-up to two decimal places. The energy basis, `utilization_energy_pct`, is one hundred times the summed `kwh_delivered` across the same sessions, divided by the energy the nameplate could have delivered — `max_kw` multiplied by the available hours (available minutes divided by sixty) — again rounded half-up to two decimal places; identical raw data therefore yields two different percentages, one measuring occupied time and the other delivered energy. Both figures remain null until the first recompute. Bookkeeping rides on the session basis: when `utilization_session_pct` falls below five percent, the charger's `low_util_run_count` — initially zero — grows by one, and any run at or above five percent resets that count to zero; once the count reaches two consecutive low runs, `utilization_review_flag` — initially false — turns true and stays set, marking the charger for decommission review. The close-of-business summary's `chargers_flagged` reports how many chargers carry the flag.

### 3.9. Event Bookings and Surge Operations

Event parking is booked ahead against a dedicated pool. A `FacilityManager` requests a booking with a `facility_id`, an `event_name`, the half-open window bounded by `start_at` and `end_at` (end strictly after start, else `ERR_INVALID_TIME_RANGE`), a `presale_allocation` of presold stalls (at least zero) charged against the facility's event pool, and a `min_staff` staffing floor (at least zero); an optional `deposit_cents` (at least zero, default zero) is held against cancellation, and an optional `cancellation_policy` chooses `FORFEIT_DEPOSIT` or `SLIDING_NOTICE`, defaulting to `FORFEIT_DEPOSIT`. A new booking stands `REQUESTED` with an empty `staffing_assignments` roster and both cancellation figures null. The booking list filters by `facility_id` or `booking_status`. Confirmation and activation both sit behind the posture gate — a `CLOSED_TEMPORARY` or `DECOMMISSIONED` facility refuses them with `ERR_FACILITY_POSTURE_BLOCKS`.

Confirmation enforces capacity, then staffing, in that order. The pool charge is the candidate's `presale_allocation` plus the `presale_allocation` of every other booking of the same facility standing `CONFIRMED` or `ACTIVE` whose window overlaps the candidate's — overlap being strict and half-open, so the candidate's `start_at` falls strictly before the other's `end_at` and the other's `start_at` falls strictly before the candidate's `end_at`, and windows that merely touch at an endpoint do not overlap. The charge must not exceed the facility's `event_pool_spaces`, with equality permitted; an excess rejects the confirmation with `ERR_EVENT_POOL_EXCEEDED`. The roster supplied as `staffing_assignments` must then number at least `min_staff`, or confirmation fails with `ERR_STAFFING_INSUFFICIENT`. A confirmed booking stands `CONFIRMED` with the roster recorded.

Activation brings the surge. Within the event window — at or after `start_at` and strictly before `end_at`, else `ERR_INVALID_TIME_RANGE` — a `FacilityManager` activates the booking, moving it from `CONFIRMED` to `ACTIVE`. When the facility stands `NORMAL`, posture flips to `EVENT_SURGE` and the facility's `version` advances by one; every access device of the facility standing `ONLINE` then flips its `device_mode` from `STANDARD` to `EVENT`, so entries taken during the surge pin the `EVENT_FLAT` fee mode (§3.3). Completion moves an `ACTIVE` booking to the terminal `COMPLETED`, and the reversal is conditional: when the completing event leaves no other `ACTIVE` booking at the facility and posture stands `EVENT_SURGE`, posture returns to `NORMAL` and every device still in `EVENT` mode flips back to `STANDARD` — but while another event remains active, the surge persists.

Cancellation closes the books on a `REQUESTED` or `CONFIRMED` booking; the caller supplies a `reason`. From `REQUESTED`, the cancellation fee is zero. From `CONFIRMED`, the fee follows the booking's `cancellation_policy`: under `FORFEIT_DEPOSIT` the fee is the full `deposit_cents` regardless of notice; under `SLIDING_NOTICE`, the notice hours — the hours from the cancellation moment to the event's `start_at` — decide, with notice shorter than forty-eight hours forfeiting the full `deposit_cents` and notice of forty-eight hours or more halving it, rounded half-up to whole cents. Either way the cancelled booking stands in the terminal `CANCELLED` with `cancellation_fee_cents` storing the fee and `deposit_refund_cents` storing `deposit_cents` minus that fee.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify, transition, or act on an existing resource return `200 OK`, including the clock-setting capability. The request and response payloads for each operation are defined by the narratives of §2 and §3; this table is an index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ops/_clock/set_current_utc` | Advance the logical clock | FacilityManager |
| POST | `/ops/facilities` | Create a facility | FacilityManager |
| GET | `/ops/facilities/{facility_id}` | Get a facility | Any authenticated role |
| GET | `/ops/facilities` | List facilities (filter `posture`) | Any authenticated role |
| POST | `/ops/facilities/{facility_id}/transition-posture` | Manual posture transition (never to EVENT_SURGE) | FacilityManager |
| POST | `/ops/facilities/{facility_id}/close-of-business` | Run the daily close for the logical date | FacilityManager |
| GET | `/ops/facilities/{facility_id}/dashboard` | Computed operational snapshot | Any authenticated role |
| POST | `/ops/rate-schedules` | Create a DRAFT rate schedule | FacilityManager |
| GET | `/ops/rate-schedules/{rate_schedule_id}` | Get a rate schedule | Any authenticated role |
| GET | `/ops/rate-schedules` | List rate schedules | Any authenticated role |
| POST | `/ops/rate-schedules/{rate_schedule_id}/publish` | Publish a schedule (OCC on the facility); supersedes the current PUBLISHED | FacilityManager |
| POST | `/ops/rate-schedules/{rate_schedule_id}/retire` | Retire a DRAFT or PUBLISHED schedule | FacilityManager |
| POST | `/ops/access-devices` | Register a PARCS device | FacilityManager |
| GET | `/ops/access-devices/{access_device_id}` | Get a device | Any authenticated role |
| GET | `/ops/access-devices` | List devices | Any authenticated role |
| POST | `/ops/access-devices/{access_device_id}/heartbeat` | Device heartbeat; OFFLINE/DEGRADED to ONLINE | GateDevice |
| POST | `/ops/access-devices/{access_device_id}/report-fault` | Report a fault; ONLINE to DEGRADED | GateDevice, FacilityManager |
| POST | `/ops/access-devices/{access_device_id}/decommission` | Decommission a device; mode forced to STANDARD | FacilityManager |
| POST | `/ops/parker-accounts` | Create a parker account | FacilityManager, ParkingAttendant |
| GET | `/ops/parker-accounts/{parker_account_id}` | Get a parker account | Any authenticated role |
| GET | `/ops/parker-accounts` | List parker accounts | Any authenticated role |
| POST | `/ops/monthly-agreements` | Submit an agreement; auto-evaluates to APPROVED or WAITLISTED | FacilityManager, ParkingAttendant |
| GET | `/ops/monthly-agreements/{monthly_agreement_id}` | Get an agreement | Any authenticated role |
| GET | `/ops/monthly-agreements` | List agreements | Any authenticated role |
| POST | `/ops/monthly-agreements/{monthly_agreement_id}/activate` | Activate an APPROVED agreement; prorates the first invoice | ParkingAttendant, FacilityManager |
| POST | `/ops/monthly-agreements/{monthly_agreement_id}/suspend` | Suspend an ACTIVE agreement | FacilityManager |
| POST | `/ops/monthly-agreements/{monthly_agreement_id}/resume` | Resume a SUSPENDED agreement | FacilityManager |
| POST | `/ops/monthly-agreements/{monthly_agreement_id}/terminate` | Terminate an agreement; requires no outstanding credentials | FacilityManager, ParkingAttendant |
| POST | `/ops/monthly-agreements/{monthly_agreement_id}/amend` | Amend rate/surcharge (OCC on the agreement) | FacilityManager |
| POST | `/ops/monthly-agreements/{monthly_agreement_id}/withdraw` | Withdraw a WAITLISTED agreement | FacilityManager, ParkingAttendant, MonthlyParker |
| POST | `/ops/credentials` | Issue a badge/transponder for an APPROVED or ACTIVE agreement | ParkingAttendant |
| GET | `/ops/credentials/{credential_id}` | Get a credential | Any authenticated role |
| GET | `/ops/credentials` | List credentials | Any authenticated role |
| POST | `/ops/credentials/{credential_id}/report-lost` | Report a credential lost | MonthlyParker, ParkingAttendant |
| POST | `/ops/credentials/{credential_id}/report-found` | Report a lost credential found | MonthlyParker, ParkingAttendant |
| POST | `/ops/credentials/{credential_id}/replace` | Replace a credential; mints a successor carrying the deposit | ParkingAttendant |
| POST | `/ops/credentials/{credential_id}/return` | Return a credential; deposit refunded | ParkingAttendant |
| POST | `/ops/credentials/{credential_id}/revoke` | Revoke a credential; deposit forfeited | ParkingAttendant, FacilityManager |
| POST | `/ops/parking-sessions` | Record a gate entry; pins the rate schedule and fee mode | GateDevice |
| GET | `/ops/parking-sessions/{parking_session_id}` | Get a session | Any authenticated role |
| GET | `/ops/parking-sessions` | List sessions | Any authenticated role |
| POST | `/ops/parking-sessions/{parking_session_id}/quote` | Provisional fee quote at logical now; re-quote allowed | GateDevice, ParkingAttendant |
| POST | `/ops/parking-sessions/{parking_session_id}/pay` | Settle the session at logical now; CASH needs an owned OPEN shift | ParkingAttendant |
| POST | `/ops/parking-sessions/{parking_session_id}/comp` | Waive the fee against a shift's comp cap | ParkingAttendant |
| POST | `/ops/parking-sessions/{parking_session_id}/exit` | Record a gate exit; auto-settles zero-fee sessions | GateDevice |
| POST | `/ops/parking-sessions/{parking_session_id}/lost-ticket` | Convert an OPEN/QUOTED transient session to LOST_TICKET rating | ParkingAttendant |
| POST | `/ops/parking-sessions/{parking_session_id}/refund` | Refund a SETTLED session up to the settled amount | RevenueAuditor |
| POST | `/ops/shifts` | Open a cashier shift; attendant identity from X-User-ID | ParkingAttendant |
| GET | `/ops/shifts/{shift_id}` | Get a shift | Any authenticated role |
| GET | `/ops/shifts` | List shifts | Any authenticated role |
| POST | `/ops/shifts/{shift_id}/close` | Close a shift with the declared cash count | ParkingAttendant |
| POST | `/ops/reconciliations` | Open a reconciliation for a CLOSED/FORCE_CLOSED shift | RevenueAuditor |
| GET | `/ops/reconciliations/{reconciliation_id}` | Get a reconciliation | Any authenticated role |
| GET | `/ops/reconciliations` | List reconciliations | Any authenticated role |
| POST | `/ops/reconciliations/{reconciliation_id}/submit` | Submit; threshold breach routes to VARIANCE_REVIEW and opens an incident | RevenueAuditor |
| POST | `/ops/reconciliations/{reconciliation_id}/approve` | Approve; from VARIANCE_REVIEW requires the linked INVESTIGATING incident | RevenueAuditor |
| POST | `/ops/inspections` | Schedule a structural inspection | MaintenanceSupervisor |
| GET | `/ops/inspections/{inspection_id}` | Get an inspection | Any authenticated role |
| GET | `/ops/inspections` | List inspections | Any authenticated role |
| POST | `/ops/inspections/{inspection_id}/start` | Begin fieldwork | MaintenanceSupervisor |
| POST | `/ops/inspections/{inspection_id}/report` | File the condition report; CRITICAL fires the posture/capacity/credential cascade | MaintenanceSupervisor |
| POST | `/ops/inspections/{inspection_id}/cancel` | Cancel an inspection | MaintenanceSupervisor |
| POST | `/ops/repair-projects` | Propose a capital repair project | MaintenanceSupervisor |
| GET | `/ops/repair-projects/{repair_project_id}` | Get a repair project | Any authenticated role |
| GET | `/ops/repair-projects` | List repair projects | Any authenticated role |
| POST | `/ops/repair-projects/{repair_project_id}/fund` | Draw capital reserve to fund the project | FacilityManager |
| POST | `/ops/repair-projects/{repair_project_id}/schedule` | Set the work window | MaintenanceSupervisor |
| POST | `/ops/repair-projects/{repair_project_id}/start` | Begin work; closes the project's spaces | MaintenanceSupervisor |
| POST | `/ops/repair-projects/{repair_project_id}/close-out` | Complete work; reopens the project's spaces | MaintenanceSupervisor |
| POST | `/ops/repair-projects/{repair_project_id}/defer` | Defer a PROPOSED project | FacilityManager |
| POST | `/ops/repair-projects/{repair_project_id}/revise` | Revise a DEFERRED project back to PROPOSED | MaintenanceSupervisor |
| POST | `/ops/repair-projects/{repair_project_id}/cancel` | Cancel a project; FUNDED projects refund their draw | FacilityManager |
| POST | `/ops/maintenance-windows` | Schedule a window (30-minute buffer overlap rule per level) | MaintenanceSupervisor |
| GET | `/ops/maintenance-windows/{maintenance_window_id}` | Get a window | Any authenticated role |
| GET | `/ops/maintenance-windows` | List windows | Any authenticated role |
| POST | `/ops/maintenance-windows/{maintenance_window_id}/start` | Begin the window | MaintenanceSupervisor |
| POST | `/ops/maintenance-windows/{maintenance_window_id}/complete` | Complete the window | MaintenanceSupervisor |
| POST | `/ops/maintenance-windows/{maintenance_window_id}/cancel` | Cancel a SCHEDULED window | MaintenanceSupervisor |
| POST | `/ops/patrol-rounds` | Schedule a patrol; officer identity from X-User-ID | SecurityOfficer |
| GET | `/ops/patrol-rounds/{patrol_round_id}` | Get a patrol round | Any authenticated role |
| GET | `/ops/patrol-rounds` | List patrol rounds | Any authenticated role |
| POST | `/ops/patrol-rounds/{patrol_round_id}/complete` | Complete a patrol with checkpoint and outage counts | SecurityOfficer |
| POST | `/ops/incidents` | File an incident report | SecurityOfficer, ParkingAttendant, RevenueAuditor |
| GET | `/ops/incidents/{incident_id}` | Get an incident | Any authenticated role |
| GET | `/ops/incidents` | List incidents | Any authenticated role |
| POST | `/ops/incidents/{incident_id}/investigate` | Open an investigation | SecurityOfficer, RevenueAuditor |
| POST | `/ops/incidents/{incident_id}/resolve` | Resolve an investigated incident | SecurityOfficer, RevenueAuditor |
| POST | `/ops/incidents/{incident_id}/close` | Close an OPEN or RESOLVED incident | SecurityOfficer, RevenueAuditor, FacilityManager |
| POST | `/ops/incidents/{incident_id}/mark-duplicate` | Mark this incident a duplicate of another; closes it | SecurityOfficer |
| POST | `/ops/ev-chargers` | Propose an EV charger | MaintenanceSupervisor |
| GET | `/ops/ev-chargers/{ev_charger_id}` | Get a charger | Any authenticated role |
| GET | `/ops/ev-chargers` | List chargers | Any authenticated role |
| POST | `/ops/ev-chargers/{ev_charger_id}/permit` | Record the electrical permit | MaintenanceSupervisor |
| POST | `/ops/ev-chargers/{ev_charger_id}/install` | Record physical installation | MaintenanceSupervisor |
| POST | `/ops/ev-chargers/{ev_charger_id}/commission` | Energize and commission | MaintenanceSupervisor |
| POST | `/ops/ev-chargers/{ev_charger_id}/take-out-of-service` | Take a commissioned charger out of service | MaintenanceSupervisor |
| POST | `/ops/ev-chargers/{ev_charger_id}/return-to-service` | Return an out-of-service charger to service | MaintenanceSupervisor |
| POST | `/ops/ev-chargers/{ev_charger_id}/decommission` | Decommission a charger (not from COMMISSIONED) | MaintenanceSupervisor |
| POST | `/ops/charging-sessions` | Start a charging session on a COMMISSIONED charger | MonthlyParker, ParkingAttendant, MaintenanceSupervisor |
| GET | `/ops/charging-sessions/{charging_session_id}` | Get a charging session | Any authenticated role |
| GET | `/ops/charging-sessions` | List charging sessions | Any authenticated role |
| POST | `/ops/charging-sessions/{charging_session_id}/complete` | Complete a charge with delivered energy | MonthlyParker, ParkingAttendant, MaintenanceSupervisor |
| POST | `/ops/charging-sessions/{charging_session_id}/fault` | Fault a session; cascades the charger OUT_OF_SERVICE | ParkingAttendant, MaintenanceSupervisor |
| POST | `/ops/event-bookings` | Request an event parking booking | FacilityManager |
| GET | `/ops/event-bookings/{event_booking_id}` | Get an event booking | Any authenticated role |
| GET | `/ops/event-bookings` | List event bookings | Any authenticated role |
| POST | `/ops/event-bookings/{event_booking_id}/confirm` | Confirm with staffing roster; enforces pool aggregate capacity | FacilityManager |
| POST | `/ops/event-bookings/{event_booking_id}/activate` | Activate within the window; cascades EVENT_SURGE and device EVENT mode | FacilityManager |
| POST | `/ops/event-bookings/{event_booking_id}/complete` | Complete the event; posture reverses when it is the last ACTIVE event | FacilityManager |
| POST | `/ops/event-bookings/{event_booking_id}/cancel` | Cancel a REQUESTED or CONFIRMED event; fee per cancellation policy | FacilityManager |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_DEVICE_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_FACILITY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_FACILITY_POSTURE_BLOCKS` | 409 Conflict |
| `ERR_POSTURE_TRANSITION_BLOCKED` | 409 Conflict |
| `ERR_STRUCTURAL_CRITICAL` | 409 Conflict |
| `ERR_DEVICE_NOT_ONLINE` | 409 Conflict |
| `ERR_NO_PUBLISHED_RATE` | 409 Conflict |
| `ERR_SHIFT_NOT_OPEN` | 409 Conflict |
| `ERR_SHIFT_ALREADY_OPEN` | 409 Conflict |
| `ERR_EXIT_UNPAID` | 409 Conflict |
| `ERR_DUPLICATE_TICKET` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_VALID` | 409 Conflict |
| `ERR_CREDENTIAL_LIMIT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ISSUABLE` | 409 Conflict |
| `ERR_CREDENTIALS_OUTSTANDING` | 409 Conflict |
| `ERR_CHARGER_UNAVAILABLE` | 409 Conflict |
| `ERR_STAFFING_INSUFFICIENT` | 409 Conflict |
| `ERR_SAFETY_HOLD` | 409 Conflict |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EVENT_POOL_EXCEEDED` | 409 Conflict |
| `ERR_MONTHLY_POOL_EXHAUSTED` | 409 Conflict |
| `ERR_COMP_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_COLLECTED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_RESERVE` | 422 Unprocessable Entity |
| `ERR_VARIANCE_INCIDENT_REQUIRED` | 409 Conflict |
| `ERR_INSPECTION_NOT_REPORTED` | 409 Conflict |

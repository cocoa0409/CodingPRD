# Tugboat Harbor Assist API — Product Requirements Document

## 1. Introduction

Harbor assist is a choreography of scarce, expensive, and heavily regulated resources. A vessel's agent requests a docking, an undocking, a shift between berths, an escort, or an open-water tow; dispatchers marshal tugs whose pulling power matches the job; licensed pilots are booked against tight scheduling windows with mandatory turnaround buffers; and port authorities police weather, towing-gear integrity, and crew fatigue — all while every billable minute and every liability dollar must be defensible months later in a claims review. This document specifies the Tugboat Harbor Assist API, the system of record for that choreography in the style of a Moran Towing-style operator.

The API covers the full commercial and operational lifecycle of an assist job: job ordering against a published tariff schedule, tug assignment with bollard-pull matching, pilot coordination, crew watch rotation, gear inspection and failure cascades, incident reporting and resolution, weather-driven holds, two-stage invoicing with a provisional-then-final charge model, and damage claims settled under a limitation-of-liability regime. It is written for seven cooperating operator roles and is deliberately strict about three things: the exact order in which bad requests are rejected, the exact instant at which money is computed, and the cascades that keep the operational graph consistent when a tug fails an inspection or a gale shuts the port. All services are mounted under `/api`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The recognized roles are exactly seven: `PortAdmin`, `VesselAgent`, `PortDispatcher`, `Pilot`, `TugCaptain`, `MarineSurveyor`, and `ClaimsAdjuster`. Each operation declares the roles authorized to invoke it (§4); an authenticated caller whose role is not on that operation's list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three roles are entity-backed, meaning `X-User-ID` is the `id` of a persisted resource and ownership checks compare it against that resource's foreign keys. When `X-User-Role` is `VesselAgent`, `X-User-ID` is the `id` of the acting `Vessel`; job-order placement, amendment, and cancellation, and damage-claim filing, all compare the order's or claim's `vessel_id` against `X-User-ID`, and a mismatch is rejected with `ERR_JOB_NOT_OWNED` (HTTP 403). When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting `Pilot`; confirming or boarding a booking compares the booking's `pilot_id` against `X-User-ID`, and a mismatch is rejected with `ERR_BOOKING_NOT_OWNED` (HTTP 403). When `X-User-Role` is `TugCaptain`, `X-User-ID` is the `id` of the acting `Tug`; confirming an assignment compares the assignment's `tug_id`, reporting an incident compares the reported `tug_id`, and logging a watch compares the tug reached through the watch's assignment — mismatches are rejected with `ERR_ASSIGNMENT_NOT_OWNED` (HTTP 403).

The remaining four roles carry opaque operator identifiers not tied to any persisted entity. When `X-User-Role` is `PortAdmin`, `PortDispatcher`, `MarineSurveyor`, or `ClaimsAdjuster`, `X-User-ID` is never compared to any resource's `id`; the server simply authorizes the role against the operation.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, and any supplied value must be at least 1 and at most 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp, ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Half-Open Time Windows

The server keeps its own logical clock, and nothing in this API reads wall-clock time. Before it is ever set, the logical clock reads exactly 2026-05-01T00:00:00Z. A `PortAdmin` moves it through an administrative clock-setting capability that accepts a `to_iso8601` instant and answers with the new reading as `current_utc`. Every use of "now" in this document — stamping `actual_start` and `actual_end` on a job, deciding whether a proposed schedule lies in the past, judging whether a gear inspection is still current, and deciding which assignments count as future work when a tug is knocked out of service — resolves against this logical clock.

Every time window in the system is a half-open interval: the start instant is included, the end instant is excluded. Two windows overlap only when they share at least one instant under that convention; back-to-back windows, where one ends exactly when the other begins, do not overlap. This convention governs weather-restriction intersections, tug-calendar conflicts, and watch-overlap checks alike.

### 2.5. Common Resource Properties

Every resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. Every resource except one also carries `updated_at`, an ISO 8601 UTC timestamp refreshed on any change, and `version`, an integer that increments by one on every mutation of the resource — including mutations delivered by a cascade originating on another resource, so a job amendment that supersedes an assignment also advances that assignment's `version` and `updated_at`.

The single exception is the gear inspection record. An inspection is an immutable log entry: it carries only `id` and `created_at`, and it has neither `updated_at` nor `version`.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency, and each guards a specific parent resource. Amending a job order requires the request to carry `expected_job_order_version` equal to that job's current `version`; creating a tug assignment likewise requires `expected_job_order_version` equal to the current `version` of the job it attaches to; and finalizing an invoice requires `expected_invoice_version` equal to that invoice's current `version`. When the supplied value no longer matches — because another writer has advanced the parent's version since the client last read it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to proceed against a stale reading. The stakes are concrete: amending a job legitimately supersedes the schedule its confirmed assignments were planned against, and proposing an assignment itself advances the job's version (§3.3), so a client that has not re-read the job would otherwise build on sand. No endpoint other than these three accepts a version field.

### 2.7. Monetary Precision, Rounding, and Units

All money in the system is integer cents; no fractional cent ever appears in a stored or returned value. Charges are computed line by line, and every money line is rounded half-up to whole cents before any summation takes place — summing unrounded lines and rounding once at the end is a rejected alternative, and this rounding order is pinned for invoices. Within the tug-hire computation, each assignment's duration is converted to hours and rounded half-up to two decimal places before it is multiplied by the tug's hourly rate. A job's required bollard pull is rounded half-up to one decimal place. Crew-rest arithmetic is performed in whole minutes. Surcharge and fraction inputs, such as a tariff's weather surcharge rate, are supplied as plain decimal fractions — 0.15 means fifteen percent.

### 2.8. Validation Order and Error Precedence

Every request is screened against a fixed validation pipeline. A failure at any stage short-circuits all later stages, so the error a caller receives is always the earliest failing stage, never a later one. Only the stages scoped to a given endpoint apply to it, but their relative order is fixed system-wide:

1. **Authentication** — the headers are present and the role is recognized, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the role is on the operation's list, else `ERR_FORBIDDEN`.
3. **Ownership** — for entity-backed roles, the resource belongs to the caller: `ERR_JOB_NOT_OWNED` for vessel agents, `ERR_BOOKING_NOT_OWNED` for pilots, `ERR_ASSIGNMENT_NOT_OWNED` for tug captains.
4. **Existence** — every path identifier and every body foreign-key reference exists, checked left to right, else `ERR_NOT_FOUND`.
5. **Optimistic concurrency** — on the three version-guarded writes of §2.6, else `ERR_STALE_VERSION`.
6. **Terminal-state guard** — the target of a transition is not already in a terminal state, else `ERR_ALREADY_TERMINAL`.
7. **From-state validity** — the target's current state is a legitimate starting state for the attempted transition, and child-creation requests find their parent in a state that admits the child, else `ERR_INVALID_STATE`.
8. **Business safety** — tug availability (`ERR_TUG_UNAVAILABLE`), gear-inspection currency at confirmation (`ERR_GEAR_INSPECTION_OVERDUE`), and weather clearance (`ERR_WEATHER_RESTRICTED`).
9. **Temporal integrity** — tug window conflicts (`ERR_TUG_WINDOW_CONFLICT`), the pilot turnaround buffer (`ERR_PILOT_WINDOW_CONFLICT`), watch overlap (`ERR_WATCH_OVERLAP`), a schedule placed in the past (`ERR_WINDOW_IN_PAST`), malformed job windows (`ERR_JOB_WINDOW_INVALID`), and malformed restriction windows (`ERR_WEATHER_WINDOW_INVALID`).
10. **Business constraints and referential rules** — duplicate tugs on one job (`ERR_DUPLICATE_TUG_ASSIGNMENT`), insufficient pulling power at dispatch (`ERR_INSUFFICIENT_BOLLARD_PULL`), no confirmed pilot at dispatch (`ERR_PILOT_BOOKING_NOT_CONFIRMED`), pilot license adequacy (`ERR_PILOT_LICENSE_INSUFFICIENT`), crew rest (`ERR_CREW_REST_VIOLATION`), one claim per incident (`ERR_CLAIM_ALREADY_FILED`), claims only against open incidents (`ERR_INCIDENT_ALREADY_RESOLVED`), and tariff effectiveness (`ERR_TARIFF_NOT_EFFECTIVE`).
11. **Request shape** — required fields present and well-typed, else `ERR_INVALID_REQUEST`; and finally enum membership, else `ERR_INVALID_ENUM`. These two run deliberately last, after every business rule has had its say.

### 2.9. Cascading Consistency and Nested Retrieval

The harbor graph — vessels owning jobs, jobs gathering tug assignments and pilot bookings, assignments gathering watches — is kept consistent by cascades rather than by client discipline. When a lifecycle event fires, the server itself applies every derived transition: cancelling a job releases or cancels its open commitments; a failed gear inspection demotes the tug, strips its future confirmed assignments, and bounces the affected jobs back for re-planning; completing a job releases the tugs, settles the pilot bookings, and mints the provisional invoice in a single step. Each resource touched by a cascade is individually mutated — its `version` increments and its `updated_at` refreshes, per §2.5.

Where a request addresses resources through other resources, existence is validated strictly left to right — path identifiers first, then foreign-key references in the body — and the first missing reference aborts the request with `ERR_NOT_FOUND` (HTTP 404). This ordering, fixed at stage 4 of the pipeline in §2.8, guarantees that a caller is never told a business rule failed on a resource that does not exist.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Fleet, Vessels, Pilots, Crew, and the Tariff Schedule

Before the first job can be ordered, a `PortAdmin` populates the reference data. A tug is registered with a display `name`, its rated `bollard_pull_tons`, installed `horsepower`, charter `hourly_rate_cents`, `insured_value_cents` (the hull value that later anchors liability caps, §3.9), and an optional `home_port`. Bollard pull and horsepower must be positive; the hourly rate may be zero but never negative. A newly registered tug enters service with `operational_status` `AVAILABLE`; the other two lifecycle states, `RESTRICTED` and `OUT_OF_SERVICE`, are reached only through the safety cascades of §3.6. The tug roster can be listed with an optional `operational_status` filter.

A vessel is registered with a display `name`, an `imo_number` that must be unique across the fleet, its `deadweight_tonnage`, and its `loa_meters` (length overall); both numeric measures must be positive. Every vessel also carries `outstanding_billed_cents`, a computed running balance with the port that starts at zero and is maintained entirely by the billing and claims events of §3.8 and §3.9 — it is never written directly.

Harbor pilots are registered with a `name` and a `license_class` of `CLASS_I`, `CLASS_II`, or `CLASS_III`, where `CLASS_I` is the highest grade and `CLASS_III` the lowest. Each pilot record carries an `active` flag, defaulting to true, indicating whether the pilot is available for booking. Crew members are registered with a `full_name`, a `crew_role` of `CAPTAIN`, `MATE`, `ENGINEER`, or `DECKHAND`, and an optional `max_watch_hours` — the maximum continuous watch the member is permitted to stand — which defaults to 12 when omitted.

The tariff schedule is a set of published rate entries, each identified by a unique `tariff_code` and pricing exactly one `maneuver_type`: `DOCKING`, `UNDOCKING`, `SHIFTING`, `ESCORT`, or `TOWAGE`. An entry fixes the flat `base_fee_cents` charged per job together with the standby economics: `free_standby_minutes` of grace before standby billing starts (30 unless the entry says otherwise), the `standby_block_minutes` block size (15 by default), and the `standby_block_rate_cents` charged per block. An optional `weather_surcharge_pct` — a fractional rate such as 0.15 for a fifteen percent surcharge — applies when a job suffers a weather hold, and defaults to zero. Every entry is effective over an inclusive window from `effective_from` to `effective_to`: a job priced against the entry must have its scheduled start on or after `effective_from` and on or before `effective_to`.

### 3.2. Placing and Amending a Job Order

A job begins when a `VesselAgent` places an order for their own vessel: the request's `vessel_id` must equal the caller's `X-User-ID`, or the order is refused with `ERR_JOB_NOT_OWNED` (§2.1). Alongside the vessel, the agent supplies the `tariff_rate_id` of the tariff entry that will price the job, the requested `maneuver_type`, and the scheduled window `scheduled_start` to `scheduled_end`. The scheduled end must be strictly after the scheduled start — a malformed window is rejected with `ERR_JOB_WINDOW_INVALID` — and at placement time the scheduled start must not lie strictly before the current logical-clock reading: a start exactly at the current instant is acceptable, anything earlier is rejected with `ERR_WINDOW_IN_PAST`. The referenced tariff entry must be in force at the scheduled start, else `ERR_TARIFF_NOT_EFFECTIVE`. Orders can be listed filtered by `vessel_id`, `tariff_rate_id`, or `status`.

At placement, and again after every successful amendment, the system computes the pulling power the job demands and stores it on the order as `required_bollard_pull_tons`. The computation starts from the vessel's `deadweight_tonnage`, scaled by a maneuver factor per thousand tons of deadweight: 1.5 for `DOCKING`, 1.2 for `UNDOCKING`, 1.0 for `SHIFTING`, 0.8 for `ESCORT`, and 2.0 for `TOWAGE`. If the vessel's `loa_meters` exceeds 200 meters, the intermediate figure is then multiplied by 1.25 to account for the larger hull. The result is rounded half-up to one decimal place, and the requirement is never allowed to fall below 20.0 tons, even when the formula would yield less. The new order enters life in `REQUESTED` status.

Confirmation is the dispatcher's act: when a `PortDispatcher` confirms a `REQUESTED` job it becomes `CONFIRMED`. Two gates apply here even though placement checked them, because the world may have changed in between: no `ACTIVE` weather restriction may overlap the scheduled window (§3.7), else `ERR_WEATHER_RESTRICTED`; and the tariff entry must still be effective at the scheduled start, else `ERR_TARIFF_NOT_EFFECTIVE`.

Plans change, and the ordering agent may amend a job while it is `REQUESTED` or `CONFIRMED`. Amendment is guarded by optimistic concurrency: the request must carry `expected_job_order_version` equal to the job's current `version`, and a mismatch means another writer has moved the job since the caller last read it — the amendment is refused with `ERR_STALE_VERSION` (§2.6). Any of `scheduled_start`, `scheduled_end`, `maneuver_type`, and `tariff_rate_id` may be updated; the window-shape and tariff-effectiveness rules above are re-applied to the new values, and `required_bollard_pull_tons` is recomputed. Amending a `REQUESTED` job leaves it `REQUESTED`. Amending a `CONFIRMED` job is more disruptive: the job falls back to `REQUESTED`, every `CONFIRMED` tug assignment on it becomes `SUPERSEDED` (§3.3), and every still-open pilot booking — one in `REQUESTED` or `CONFIRMED` status — becomes `SUPERSEDED` as well (§3.4), because the schedule those commitments were made against no longer exists.

Either the ordering agent or a dispatcher may cancel a job while it is `REQUESTED`, `CONFIRMED`, `DISPATCHED`, or `ON_HOLD`; the same cancellation semantics apply from each of the four states. An optional `cancel_reason` is recorded when supplied. Cancellation releases the job's open tug assignments — every one in `PROPOSED` or `CONFIRMED` status becomes `RELEASED` — and cancels its open pilot bookings — every one in `REQUESTED` or `CONFIRMED` status becomes `CANCELLED`. A job that has started cannot be cancelled: from `IN_PROGRESS` or `COMPLETED` the attempt fails the from-state check with `ERR_INVALID_STATE`, and once the job is `INVOICED` or `CANCELLED` — its two terminal states — the terminal guard answers `ERR_ALREADY_TERMINAL`.

### 3.3. Building the Tow Plan: Tug Assignments

A dispatcher assembles pulling power by proposing tug assignments against the job. Each proposal names the `job_order_id`, the `tug_id`, and the occupation window `window_start` to `window_end` for which the tug will be committed; the window end must be strictly after its start. Because the proposal is planned against a particular reading of the job, it must also carry `expected_job_order_version` matching the job's current `version`, failing which it is rejected with `ERR_STALE_VERSION`. The job must be `REQUESTED` or `CONFIRMED` — a proposal against a job in any other state fails with `ERR_INVALID_STATE` — and the named tug must be `AVAILABLE`, failing which `ERR_TUG_UNAVAILABLE`. A successful proposal creates the assignment in `PROPOSED` status and increments the owning job's `version` by one, so a dispatcher staging several proposals must re-read the job between them; that version bump is the deliberate serialization point that keeps each proposal honest about the job it attaches to.

Two conflict rules protect the tug's calendar and the job's tug list. First, the proposed window must not overlap — under the half-open convention of §2.4 — any existing assignment of the same tug in `PROPOSED`, `CONFIRMED`, or `ACTIVE` status; strict adjacency, where the new window starts exactly when an existing one ends, is allowed. A clash is rejected with `ERR_TUG_WINDOW_CONFLICT`. Second, the job must not already hold a `PROPOSED`, `CONFIRMED`, or `ACTIVE` assignment for the same tug; the duplicate is rejected with `ERR_DUPLICATE_TUG_ASSIGNMENT`. Assignments can be listed filtered by `job_order_id`, `tug_id`, or `status`.

A proposal becomes firm when the tug's own captain confirms it — the caller's `X-User-ID` must equal the assignment's `tug_id`, or the attempt is refused with `ERR_ASSIGNMENT_NOT_OWNED`. Confirmation re-verifies that the tug is `AVAILABLE` (else `ERR_TUG_UNAVAILABLE`) and then applies the gear-currency gate: the tug's most recent gear inspection — the latest by `inspected_at`, ties broken by later `created_at` — must show `outcome` `PASSED`, and its `next_due_at` must lie strictly after the current logical-clock reading. A tug whose latest inspection failed, or whose inspection has lapsed past its due instant, cannot be confirmed; the rejection is `ERR_GEAR_INSPECTION_OVERDUE`. A confirmed assignment moves `PROPOSED` → `CONFIRMED`.

Dispatch is the go/no-go decision: a dispatcher moves a `CONFIRMED` job to `DISPATCHED` only when three conditions hold. The tow must have enough muscle — the `bollard_pull_tons` of the tugs on the job's `CONFIRMED` assignments must sum to at least the job's `required_bollard_pull_tons`, with exact equality sufficient, else `ERR_INSUFFICIENT_BOLLARD_PULL`. At least one pilot booking on the job must be `CONFIRMED`, else `ERR_PILOT_BOOKING_NOT_CONFIRMED`. And the weather gate of §3.7 must be clear — no `ACTIVE` restriction overlapping the scheduled window — else `ERR_WEATHER_RESTRICTED`. A successful dispatch clears the job's `needs_reassignment` flag, which the safety cascades of §3.6 may have set.

After dispatch, assignments move with the job. When the job starts, each `CONFIRMED` assignment becomes `ACTIVE` with `participated` set true — only participating assignments are billed (§3.8). When the job completes, each `ACTIVE` assignment becomes `RELEASED`. A dispatcher may also release a `CONFIRMED` assignment manually before the job starts, and job cancellation releases both `PROPOSED` and `CONFIRMED` assignments (§3.2). Finally, a `CONFIRMED` assignment can be superseded without any client action: amending the owning job out of `CONFIRMED` supersedes it (§3.2), and so does its tug entering `RESTRICTED` or `OUT_OF_SERVICE` while the assignment's `window_start` is still strictly after the current logical-clock reading (§3.6). `RELEASED` and `SUPERSEDED` are terminal.

### 3.4. Pilot Coordination and Scheduling Windows

No assist job moves without a pilot, and bookings mirror the assignment flow. A dispatcher books a pilot with the `job_order_id`, the `pilot_id`, and the booking window `window_start` to `window_end`, the end strictly after the start. The job must be `REQUESTED` or `CONFIRMED`, else `ERR_INVALID_STATE`. The pilot's license must suffice for the maneuver: `TOWAGE` and `ESCORT` demand `CLASS_I`; `DOCKING` and `UNDOCKING` accept `CLASS_I` or `CLASS_II`; `SHIFTING` is open to any class. An under-licensed booking is rejected with `ERR_PILOT_LICENSE_INSUFFICIENT`. A new booking enters as `REQUESTED`.

Pilots need turnaround time between jobs, so a booking must leave a sixty-minute buffer against every other booking of the same pilot in `REQUESTED`, `CONFIRMED`, or `BOARDED` status: the new window must start at least sixty minutes after the existing window ends, or end at least sixty minutes before the existing window starts. A booking that crowds that buffer is rejected with `ERR_PILOT_WINDOW_CONFLICT`. Bookings are listed with optional `job_order_id`, `pilot_id`, and `status` filters.

The pilot confirms their own booking, moving it `REQUESTED` → `CONFIRMED`, and later marks themselves boarded — `CONFIRMED` → `BOARDED` — once the owning job is `DISPATCHED` or `IN_PROGRESS`; boarding while the job is in any other state is refused with `ERR_INVALID_STATE`. Both actions are personal: the caller's `X-User-ID` must equal the booking's `pilot_id`, else `ERR_BOOKING_NOT_OWNED`. Job completion separates the committed from the absent: a `BOARDED` booking becomes `COMPLETED`, while a booking still merely `CONFIRMED` is marked `NO_SHOW`. Job cancellation cancels bookings in `REQUESTED` or `CONFIRMED` status, and an amendment out of `CONFIRMED` supersedes them (§3.2). `COMPLETED`, `NO_SHOW`, `CANCELLED`, and `SUPERSEDED` are the terminal states.

### 3.5. Crew Watches and Rest Discipline

On an assigned tug, the captain logs who stood watch and when. A watch rotation names the `tug_assignment_id` it serves, the `crew_member_id` standing watch, and the span `watch_start` to `watch_end`, the end strictly after the start. Logging is restricted to the captain of the tug the assignment belongs to — the caller's `X-User-ID` must match the tug reached through the referenced assignment, else `ERR_ASSIGNMENT_NOT_OWNED` — and the assignment must be `CONFIRMED` or `ACTIVE`, else `ERR_INVALID_STATE`. Watches are listed filtered by `tug_assignment_id` or `crew_member_id`.

Two fatigue rules guard every logged watch. A new watch may not overlap any existing watch of the same crew member under the half-open convention of §2.4; an overlapping entry is rejected with `ERR_WATCH_OVERLAP`. And the member must be adequately rested: looking back over the twenty-four hours immediately preceding the new watch's start, the system totals the member's worked minutes — the overlap of each of their existing watches, on any assignment, with that lookback window — accumulating in chronological order of watch start, with creation time breaking ties. The remainder of the day, 1,440 minutes minus the worked minutes, is the member's rest, and it must come to at least ten hours. A watch that would leave the member with less rest is rejected with `ERR_CREW_REST_VIOLATION`.

### 3.6. Gear Integrity, Incidents, and Tug Availability

Two independent safety signals drive a tug's `operational_status`: gear inspection results and casualty incidents. A `MarineSurveyor` records an inspection of one item of towing gear — `TOWING_HOOK`, `TOW_LINE`, `WINCH`, or `BITTS` — supplying the inspected `tug_id`, the `inspection_item`, the `outcome` (`PASSED` or `FAILED`), the `inspected_at` instant, the `next_due_at` instant after which the inspection lapses, and optional `deficiency_notes`. Inspection records are immutable log entries carrying only `id` and `created_at` (§2.5), and they can be listed filtered by `tug_id` or `outcome`.

A `FAILED` outcome restricts the tug immediately: an `AVAILABLE` tug becomes `RESTRICTED`, and the failure cascades outward. Every `CONFIRMED` assignment of that tug whose `window_start` lies strictly after the current logical-clock reading becomes `SUPERSEDED` — work already underway is not retroactively disturbed — and each job stripped of a confirmed tug in this way, if itself still `CONFIRMED`, is demoted to `REQUESTED` with `needs_reassignment` set true, flagging it for the dispatcher to rebuild the tow plan; until that re-planning happens, dispatch is unreachable because the bollard-pull sum no longer reaches the requirement. A later `PASSED` inspection restores a `RESTRICTED` tug to `AVAILABLE`, but only once the latest inspection of every gear item is `PASSED` and the tug carries no unresolved `MAJOR` or `CRITICAL` incident.

Incidents are reported by the captain of the tug involved — the caller's `X-User-ID` must equal the reported `tug_id`, else `ERR_ASSIGNMENT_NOT_OWNED`. The report captures the `incident_type` (`GEAR_FAILURE`, `CONTACT_DAMAGE`, `POLLUTION`, or `PERSONAL_INJURY`), the `severity` (`MINOR`, `MAJOR`, or `CRITICAL`), the `occurred_at` instant, a free-text `description`, and optionally the `job_order_id` being worked when it happened. A new incident stands in `REPORTED` status. Incidents are listed with optional `tug_id`, `job_order_id`, and `status` filters.

Severity decides the tug's fate. A `MAJOR` or `CRITICAL` report knocks the tug `OUT_OF_SERVICE` — from `AVAILABLE` or from `RESTRICTED` alike — and triggers the same supersede-and-demote cascade as a failed inspection: future-window `CONFIRMED` assignments become `SUPERSEDED`, and their still-`CONFIRMED` jobs fall back to `REQUESTED` with `needs_reassignment` true. A `MINOR` report leaves the tug's status untouched.

Resolution belongs to the surveyor, who closes an incident — from `REPORTED` or `UNDER_INVESTIGATION` alike — by recording `resolution_notes`; the incident becomes `RESOLVED`, which is terminal. Closing the tug's last unresolved `MAJOR` or `CRITICAL` incident reopens the question of its availability: if the latest inspection of every gear item is `PASSED`, the tug returns directly from `OUT_OF_SERVICE` to `AVAILABLE`; if any item's latest inspection is `FAILED`, it returns only to `RESTRICTED`, pending a clean re-inspection. The claim process of §3.9 also moves an incident: filing the first damage claim against a `REPORTED` incident escalates it to `UNDER_INVESTIGATION`.

### 3.7. Weather and Current Restrictions

When conditions deteriorate, a `PortAdmin` declares a restriction over a `port_area`, naming the `restriction_type` — `WIND`, `CURRENT`, or `VISIBILITY` — the measured `threshold_value` that motivated it (knots for wind and current, meters for visibility), and the effective span `effective_start` to `effective_end`, the end strictly after the start else `ERR_WEATHER_WINDOW_INVALID`. A new restriction stands `ACTIVE`, and restrictions are listed with an optional `status` filter.

A restriction bites immediately. Every job in `DISPATCHED` status whose scheduled window overlaps the restriction's effective span — a half-open intersection per §2.4 — is placed `ON_HOLD` at the moment the restriction is declared, and each such job's `had_weather_hold` flag is set true. That flag is sticky: it survives the hold and later drives the weather surcharge on the final invoice (§3.8). The same overlap gate also guards the forward path: confirming a `REQUESTED` job, or dispatching a `CONFIRMED` one, is refused with `ERR_WEATHER_RESTRICTED` while any `ACTIVE` restriction overlaps the scheduled window.

Lifting a restriction moves it `ACTIVE` → `LIFTED`, which is terminal, and releases the holds conservatively: each `ON_HOLD` job returns to `DISPATCHED` only if, after the lift, no remaining `ACTIVE` restriction still overlaps its scheduled window. A job caught by two overlapping restrictions therefore stays on hold until the second one lifts.

### 3.8. From Completion to Invoice: Provisional and Final Charges

Starting a dispatched job is the dispatcher's signal that work has begun: the job moves `DISPATCHED` → `IN_PROGRESS`, `actual_start` is stamped from the logical clock, and every `CONFIRMED` assignment becomes `ACTIVE` with `participated` set true (§3.3). Completion closes the execution phase: the job moves `IN_PROGRESS` → `COMPLETED`, `actual_end` is stamped from the logical clock, each `ACTIVE` assignment is released, boarded pilots are completed and no-shows recorded (§3.4), and — in the same step — the system mints the job's invoice and recomputes the vessel's outstanding balance (defined in §3.9). An invoice records the `job_order_id` it bills and is born `PROVISIONAL` with `variant_basis` `SCHEDULED`. Invoices are listed filtered by `job_order_id` or `status`.

Every invoice is built from one charge model applied under one of two bases. The lines are the tariff's `base_fee_cents`; the tug-hire line `tug_hire_cents`; the standby line `standby_cents`, with the recognized minutes kept alongside as `standby_minutes`; and the weather line `weather_surcharge_cents`. Their sum is `total_cents`. Tug hire sums one line per participating assignment — those with `participated` true: the assignment's window duration is converted from seconds to hours and rounded half-up to two decimal places, then multiplied by that tug's `hourly_rate_cents`, and the product is itself rounded half-up to whole cents before being added into `tug_hire_cents`. This per-line rounding order is pinned — round every line to whole cents first, then sum; never sum first and round once (§2.7).

Standby is where the two bases diverge. Under the `SCHEDULED` basis — used by the provisional invoice minted at completion — the scheduled times stand in for execution and `standby_minutes` is zero. Under the `ACTUAL` basis — used when the invoice is finalized — standby is the elapsed minutes from `scheduled_start` to `actual_start`, floored at zero so an early start bills nothing. Only standby beyond the tariff's `free_standby_minutes` is billable: subtract the free allowance, floor at zero, divide the remainder into `standby_block_minutes` blocks rounding up to a whole block, and charge `standby_block_rate_cents` per block. Standby exactly equal to the free allowance therefore bills nothing; only standby strictly greater than the allowance bills. Finally, if the job's `had_weather_hold` flag is set, a surcharge of the tariff's `weather_surcharge_pct` times the running subtotal — base fee plus tug hire plus standby — is added, rounded half-up to whole cents; without a weather hold the surcharge line is zero. `total_cents` is the subtotal plus the surcharge.

Finalization converts the provisional bill into the final one and belongs to the dispatcher. It is guarded by optimistic concurrency: the request must carry `expected_invoice_version` matching the invoice's current `version`, else `ERR_STALE_VERSION`. The invoice must still be `PROVISIONAL` and its owning job still `COMPLETED` — once the job has moved on to `INVOICED` the terminal guard refuses further transitions. Finalization recomputes every charge line under the `ACTUAL` basis, flips `variant_basis` to `ACTUAL`, moves the invoice `PROVISIONAL` → `FINALIZED`, advances the owning job `COMPLETED` → `INVOICED` (the job's terminal state), and recomputes the vessel's outstanding balance. `FINALIZED` and `VOID` are the invoice's terminal states.

A `PortAdmin` may void an invoice from either `PROVISIONAL` or `FINALIZED`, optionally noting a `void_reason`. Voiding excludes the invoice from the vessel's outstanding balance, which is recomputed accordingly.

### 3.9. Damage Claims and the Limitation of Liability

When an assist goes wrong, the vessel's agent files a damage claim naming the `incident_id`, their own `vessel_id` — ownership-checked per §2.1, else `ERR_JOB_NOT_OWNED` — and the `claimed_amount_cents`, which must be a positive amount. Two referential guards apply: an incident may carry at most one claim, a second filing rejected with `ERR_CLAIM_ALREADY_FILED`; and the incident must still be open — `REPORTED` or `UNDER_INVESTIGATION` — with a claim against a `RESOLVED` incident rejected as `ERR_INCIDENT_ALREADY_RESOLVED`. Filing against a `REPORTED` incident escalates it to `UNDER_INVESTIGATION`; filing against one already `UNDER_INVESTIGATION` leaves its status unchanged. Claims are listed filtered by `incident_id`, `vessel_id`, or `status`.

The moment a claim is filed, the system fixes the economics of the settlement and stores them on the claim. First it chooses the liability regime, recorded as `liability_variant`: if the incident's linked job already has a `FINALIZED` invoice at filing time, the regime is `PER_VOYAGE`; otherwise — including incidents with no linked job — it is `PER_INCIDENT`. The cap follows the regime: under `PER_VOYAGE`, the raw cap is twenty times the finalized invoice's `total_cents`, rounded half-up to whole cents; under `PER_INCIDENT`, it is one half of the involved tug's `insured_value_cents`, likewise rounded half-up. In either regime the resulting `liability_cap_cents` is never less than 10,000,000 cents. The `deductible_cents` is ten percent of the smaller of the claimed amount and the cap, rounded half-up to whole cents, and the `payout_cents` is that same capped amount minus the deductible. The evaluation order is pinned — cap first, then the lesser of claim and cap, then the deductible on the capped figure, then the subtraction — and the computed fields never change afterward.

Review belongs to the `ClaimsAdjuster`, a role deliberately segregated from dispatch. The review takes an `action` code with optional `reviewer_notes`, recorded when supplied: `START_REVIEW` opens the file, moving `FILED` → `UNDER_REVIEW`; `REQUEST_INFO` sends it back for more evidence, `UNDER_REVIEW` → `FILED`; `ACCEPT` approves liability, `UNDER_REVIEW` → `ACCEPTED`; `DENY` rejects it outright, `UNDER_REVIEW` → `DENIED`. Settlement closes the loop: settling an `ACCEPTED` claim moves it to `SETTLED` and recomputes the vessel's outstanding balance, because a settled payout now counts against what the vessel owes. `SETTLED` and `DENIED` are terminal.

That balance — the vessel's `outstanding_billed_cents` — is its ledger position with the port: the sum of `total_cents` over every invoice of the vessel's jobs in `PROVISIONAL` or `FINALIZED` status, minus the sum of `payout_cents` over the vessel's `SETTLED` claims, floored at zero. It is recomputed at exactly the four events that can move it: provisional invoice creation at job completion, invoice finalization, invoice voiding, and claim settlement.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, amendments, releases, cancellations, finalizations, voids, reviews, settlements, lifts, and the clock set — return `200 OK`. The table below fixes only the HTTP contract and the authorized roles; the request payloads, computed fields, preconditions, and side effects of each operation are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/tugs` | Register a tug | PortAdmin |
| GET | `/api/tugs` | List tugs, optionally filtered | All authenticated roles |
| GET | `/api/tugs/{id}` | Get one tug | All authenticated roles |
| POST | `/api/vessels` | Register a vessel | PortAdmin |
| GET | `/api/vessels/{id}` | Get one vessel | All authenticated roles |
| POST | `/api/pilots` | Register a harbor pilot | PortAdmin |
| GET | `/api/pilots/{id}` | Get one pilot | All authenticated roles |
| POST | `/api/crew-members` | Register a crew member | PortAdmin |
| GET | `/api/crew-members/{id}` | Get one crew member | All authenticated roles |
| POST | `/api/tariff-rates` | Publish a tariff rate schedule entry | PortAdmin |
| GET | `/api/tariff-rates/{id}` | Get one tariff rate | All authenticated roles |
| POST | `/api/job-orders` | Place a job order for the caller's vessel | VesselAgent |
| GET | `/api/job-orders` | List job orders with optional filters | All authenticated roles |
| GET | `/api/job-orders/{id}` | Get one job order | All authenticated roles |
| POST | `/api/job-orders/{id}/amend` | Amend a requested or confirmed job's schedule, tariff, or maneuver | VesselAgent |
| POST | `/api/job-orders/{id}/confirm` | Confirm a requested job | PortDispatcher |
| POST | `/api/job-orders/{id}/dispatch` | Dispatch a confirmed job after bollard-pull and pilot checks | PortDispatcher |
| POST | `/api/job-orders/{id}/start` | Mark a dispatched job started; stamps actual start from the logical clock | PortDispatcher |
| POST | `/api/job-orders/{id}/complete` | Complete an in-progress job; releases assignments, settles bookings, auto-creates the provisional invoice | PortDispatcher |
| POST | `/api/job-orders/{id}/cancel` | Cancel a non-terminal, non-started job with compensation cascades | VesselAgent, PortDispatcher |
| POST | `/api/tug-assignments` | Propose a tug assignment against a job (version-guarded on the job) | PortDispatcher |
| GET | `/api/tug-assignments` | List tug assignments with optional filters | All authenticated roles |
| GET | `/api/tug-assignments/{id}` | Get one tug assignment | All authenticated roles |
| POST | `/api/tug-assignments/{id}/confirm` | Tug captain confirms a proposed assignment for their own tug | TugCaptain |
| POST | `/api/tug-assignments/{id}/release` | Manually release a confirmed assignment before job start | PortDispatcher |
| POST | `/api/pilot-bookings` | Book a pilot for a job | PortDispatcher |
| GET | `/api/pilot-bookings` | List pilot bookings with optional filters | All authenticated roles |
| GET | `/api/pilot-bookings/{id}` | Get one pilot booking | All authenticated roles |
| POST | `/api/pilot-bookings/{id}/confirm` | Pilot confirms their own booking | Pilot |
| POST | `/api/pilot-bookings/{id}/board` | Pilot marks themselves boarded once the owning job is dispatched or in progress | Pilot |
| POST | `/api/watch-rotations` | Log a crew watch on an assignment of the captain's own tug | TugCaptain |
| GET | `/api/watch-rotations` | List watch rotations with optional filters | All authenticated roles |
| GET | `/api/watch-rotations/{id}` | Get one watch rotation | All authenticated roles |
| POST | `/api/gear-inspections` | Record a towing-gear inspection; a failed outcome cascades tug restriction and assignment/job demotion | MarineSurveyor |
| GET | `/api/gear-inspections` | List gear inspections with optional filters | All authenticated roles |
| GET | `/api/gear-inspections/{id}` | Get one gear inspection | All authenticated roles |
| POST | `/api/incidents` | Report an incident involving the captain's own tug | TugCaptain |
| GET | `/api/incidents` | List incidents with optional filters | All authenticated roles |
| GET | `/api/incidents/{id}` | Get one incident | All authenticated roles |
| POST | `/api/incidents/{id}/resolve` | Resolve an open incident; recomputes tug operational status | MarineSurveyor |
| POST | `/api/weather-restrictions` | Declare a weather or current restriction; overlapping dispatched jobs are put on hold | PortAdmin |
| GET | `/api/weather-restrictions` | List weather restrictions | All authenticated roles |
| POST | `/api/weather-restrictions/{id}/lift` | Lift an active restriction; held jobs with no remaining overlapping active restriction resume | PortAdmin |
| GET | `/api/invoices` | List invoices with optional filters | All authenticated roles |
| GET | `/api/invoices/{id}` | Get one invoice | All authenticated roles |
| POST | `/api/invoices/{id}/finalize` | Finalize a provisional invoice; recomputes all lines under the actual basis (version-guarded) | PortDispatcher |
| POST | `/api/invoices/{id}/void` | Void a provisional or finalized invoice | PortAdmin |
| POST | `/api/damage-claims` | File a damage claim for the caller's vessel against an unresolved incident | VesselAgent |
| GET | `/api/damage-claims` | List damage claims with optional filters | All authenticated roles |
| GET | `/api/damage-claims/{id}` | Get one damage claim | All authenticated roles |
| POST | `/api/damage-claims/{id}/review` | Adjuster review action: start review, request information, accept, or deny | ClaimsAdjuster |
| POST | `/api/damage-claims/{id}/settle` | Settle an accepted claim; the payout subtracts from the vessel's outstanding balance | ClaimsAdjuster |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | PortAdmin |

## 5. Error Code Catalogue

The catalogue below fixes each error's identifier and HTTP status. The conditions under which each error is raised are defined by the narratives of §2 and §3, not by this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_JOB_NOT_OWNED` | 403 Forbidden |
| `ERR_BOOKING_NOT_OWNED` | 403 Forbidden |
| `ERR_ASSIGNMENT_NOT_OWNED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TUG_UNAVAILABLE` | 409 Conflict |
| `ERR_GEAR_INSPECTION_OVERDUE` | 409 Conflict |
| `ERR_WEATHER_RESTRICTED` | 409 Conflict |
| `ERR_TUG_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_PILOT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_WATCH_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_JOB_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_WEATHER_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_TUG_ASSIGNMENT` | 409 Conflict |
| `ERR_INSUFFICIENT_BOLLARD_PULL` | 422 Unprocessable Entity |
| `ERR_PILOT_BOOKING_NOT_CONFIRMED` | 409 Conflict |
| `ERR_PILOT_LICENSE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CREW_REST_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CLAIM_ALREADY_FILED` | 409 Conflict |
| `ERR_INCIDENT_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_TARIFF_NOT_EFFECTIVE` | 422 Unprocessable Entity |

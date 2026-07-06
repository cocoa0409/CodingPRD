# Volunteer Fire & EMS Department Management API — Product Requirements Document

## 1. Introduction

Small volunteer fire and EMS departments juggle a surprising amount of interlocking recordkeeping with almost no back-office staff. The same handful of people who answer alarms also maintain the member roster, chase down lapsing certifications, keep apparatus in service, publish the duty roster, file National Fire Incident Reporting System (NFIRS) reports after every run, count service points toward year-end stipends, and run the pancake breakfast that pays for it all. When those records live in disconnected spreadsheets, a firefighter whose EMT certification quietly expired can still be rostered onto an ambulance, an engine with a dead SCBA can still headline a published shift, and the points ledger that decides who gets paid drifts out of balance every time a run is voided.

This document specifies a single REST API that unifies those concerns behind one consistent contract. The system tracks members and their certifications and training hours, the stations and apparatus they staff, the duty shifts they sign up for, the incidents they respond to, the equipment and maintenance that governs whether an apparatus is fit for service, and the fundraising campaigns that fund the department. Its central purpose is **posture-driven gating**: response eligibility, apparatus readiness, and shift staffing are all computed from underlying facts, and the API refuses operations that would violate readiness or safety. A secondary theme is **compliance and audit** — certification cycles, NFIRS report revisions, and a conserved points ledger must all reconcile exactly, with no silent drift.

Because the department operates around the clock and against real expiry deadlines, the system reads a single server-controlled logical clock rather than wall-clock time; all expiry, windowing, and overlap decisions are evaluated against that clock. The sections below define the global contract every endpoint honors, the business workflows that scatter across the domain, the full endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, or `X-User-Role` does not name one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When the headers are well-formed but the named role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are exactly three roles, spelled precisely as follows: `Chief`, `Officer`, and `Member`. They form a hierarchical authority ladder in which higher roles own broader concerns, but authority is scoped by operation rather than blanket-inherited, so each endpoint's authorized roles are listed explicitly in §4.

- When `X-User-Role` is `Chief`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The Chief holds superset administrative authority — membership lifecycle, stations, apparatus, equipment, maintenance, certification revocation, fundraising, and running the sweeps — but the server does not compare `X-User-ID` to any entity's `id`; the Chief never acts as a specific persisted member for ownership checks.
- When `X-User-Role` is `Officer`, `X-User-ID` is the `id` of the acting `Member` (an officer is themselves a member). Officers own certification management, training and points logging, scheduling, incidents and NFIRS reporting, and turnout tracking. Ownership checks on any resource that references a `Member` compare the resource's member foreign key to `X-User-ID`.
- When `X-User-Role` is `Member`, `X-User-ID` is likewise the `id` of the acting `Member`. A rank-and-file member may read records and may check in to their **own** duty assignment; for the check-in operation `X-User-ID` must equal the assignment's `member_id`, otherwise the attempt is rejected with `ERR_FORBIDDEN`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are always ordered by `created_at` ascending — that is, oldest first. Each list response echoes `limit` and `offset` in the `meta` block and additionally reports `total_count` (the total number of records matching the filter, before pagination) and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and Versioning

Most resources carry four server-managed common properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC values with three fractional digits; `created_at` is stamped once at creation, and `updated_at` is refreshed on every mutation. The `version` is an integer that begins at 1 and increments by one on every mutation of the resource; it is the value clients echo back for optimistic concurrency control (§2.7).

Two resources are append-only event logs and therefore carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: the `TrainingRecord` and the `PointAdjustment`. Once written, these rows are never mutated in place; corrections are expressed by writing further events (for example, reversing a point adjustment). Every other resource — `Member`, `Certification`, `Station`, `Apparatus`, `Equipment`, `MaintenanceWindow`, `DutyShift`, `DutyAssignment`, `Incident`, `TurnoutResponse`, `FundraisingCampaign`, and `Donation` — carries the full set of four common properties.

### 2.5. The Server Logical Clock

Every temporal decision in the system — certification expiry, the expiring-soon window, rest-buffer and maintenance overlap checks, shift start and end, and all `*_at` system timestamps — reads a single server-controlled logical clock, never the host wall clock. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any set call it stays fixed at that default rather than advancing on its own. An administrative test-driving capability sets the clock to an arbitrary ISO 8601 UTC instant supplied as `to_iso8601`; from that point forward all clock reads return the most recently set instant.

### 2.6. Validation Ordering and Precedence

When several checks could reject one request, they are evaluated in a fixed priority order, and the **first** failing check determines the error returned. This ordering matters because a later, more specific rejection must never mask an earlier, more general one. The order is:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is permitted for the operation, and, where required, the entity-backed ownership check passes (for example, a `Member` checking in their own assignment), else `ERR_FORBIDDEN`.
3. **Field validity** — required body fields are present, enum fields hold in-range values, numbers that must be positive are positive, and any `end_at` is strictly later than its `start_at`, else `ERR_VALIDATION`.
4. **Existence** — every resource id referenced in the path or body (as a foreign key) must exist, validated left to right, else the corresponding not-found error.
5. **State** — the target resource is in a state from which the requested transition is legal, else `ERR_INVALID_STATE`.
6. **Response-eligibility (safety)** — for duty-assignment creation, the member being rostered must be response-eligible, else `ERR_MEMBER_NOT_RESPONSE_ELIGIBLE`.
7. **Station–apparatus referential integrity** — the referenced apparatus belongs to the referenced station, else `ERR_APPARATUS_NOT_AT_STATION`.
8. **Temporal windowing** — rest-buffer conflicts on duty-assignment creation (`ERR_SHIFT_OVERLAP`) and maintenance-window overlaps (`ERR_MAINTENANCE_OVERLAP`).
9. **Capacity and compliance** — apparatus posture on publish (`ERR_APPARATUS_OUT_OF_SERVICE`), crew ceiling on assignment (`ERR_SHIFT_FULL`), training-hour floors on certification issue and renew (`ERR_INSUFFICIENT_TRAINING_HOURS`), and NFIRS completeness on report lock and amend (`ERR_NFIRS_INCOMPLETE`).
10. **Fiscal** — a member with an outstanding dues balance cannot be rostered (`ERR_DUES_OVERDUE`).
11. **Optimistic concurrency** — the supplied expected version matches the parent's current version (`ERR_STALE_VERSION`).

Where a single operation is subject to several of these bands (duty-assignment creation is subject to all of existence, state, safety, temporal, capacity, fiscal, and concurrency), each band is still applied in the order above, so the earliest-numbered failure is the one reported.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on the version of a parent resource it most recently observed. In each case the request carries an expected-version field, and if that value does not match the parent's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). This is a stale-version guard, not a timing guard: it fires whenever the parent's version has advanced since the client last read it, regardless of when the two writes occur.

- Creating a duty assignment against a shift requires `expected_duty_shift_version` matching that `DutyShift`'s current `version`. If another writer has already added an assignment — which legitimately changes the roster composition and the number of remaining crew slots — the shift's version has advanced, the current writer's view of the roster is stale, and the create is rejected with `ERR_STALE_VERSION`.
- Amending a NFIRS report requires `expected_incident_version` matching that `Incident`'s current `version`. Because each lock or amend produces a new revision that supersedes the prior one, a client whose version is behind is editing a revision that has already been superseded; the stale amend is rejected with `ERR_STALE_VERSION` so a client never overwrites a revision it never saw.

No other endpoint takes an expected-version field.

### 2.8. Nested Retrieval and Left-to-Right Existence

The topology is flat: resources are peer top-level collections linked by explicit foreign keys, and child collections are reached by filtered list queries rather than deep URL nesting. Wherever an endpoint's path or body names more than one resource id, those ids are validated left to right, and the **first** id that does not resolve determines the not-found error returned. The specific not-found errors are `ERR_MEMBER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_APPARATUS_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_DUTY_SHIFT_NOT_FOUND`, `ERR_DUTY_ASSIGNMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_TURNOUT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, and `ERR_DONATION_NOT_FOUND`. List endpoints support reverse reachability through optional filter parameters — for instance, certifications and training records filter by `member_id`, apparatus filters by `station_id`, equipment and maintenance windows filter by `apparatus_id`, assignments filter by `duty_shift_id` and `member_id`, turnouts filter by `incident_id` and `member_id`, donations filter by `campaign_id`, and training records may additionally filter by `certification_id`. Collections whose resources carry a lifecycle `status` — certifications, maintenance windows, duty shifts, duty assignments, turnouts, campaigns, and donations — additionally accept a `status` filter that restricts the list to resources in the named state.

### 2.9. Precision, Rounding, and Points Conservation

Monetary amounts are always integer cents; where a rule halves a cents amount, the result is floored to a whole cent. Training hours are numbers carried to one decimal place, and hour comparisons against required thresholds are exact. Point-scoring values are integers; wherever a scored value is computed from a fractional product, it is rounded half up to the nearest whole point before being combined with any other component.

The department's points ledger is a **conserved quantity**. A member's year-to-date points is, at all times, the sum of the points from that member's released turnouts, plus the points from that member's verified duty assignments, plus the signed values of that member's non-reversed point adjustments. This identity must hold exactly after every forward action and after every compensation — when a turnout is voided its previously awarded points are removed, and when an adjustment is reversed it drops out of the sum — leaving zero drift. Likewise, a campaign's raised total is a conserved quantity: it equals, at all times, the sum of the amounts of that campaign's posted donations, so refunding a donation subtracts exactly its amount and leaves no residue.

### 2.10. Apparatus Posture and Service Consistency

An apparatus's readiness is never set directly; its `posture` is a derived field recomputed from its equipment and maintenance whenever either changes. When these facts change, a cascade propagates outward to the shifts the apparatus was scheduled to staff. Two cascades govern hierarchical consistency across the domain — one triggered by certification expiry and one triggered by equipment or maintenance changes — and both are detailed in §3. Every entity a cascade touches has its `updated_at` refreshed and, for versioned entities, its `version` incremented, exactly as any other mutation would.

## 3. Business Logic & Workflows

### 3.1. Members, Membership Lifecycle, and Dues

A member record is created by a Chief and captures the member's `full_name`, `email`, their response `role_class` — one of `OFFICER`, `PARAMEDIC`, `EMT`, `FIREFIGHTER`, or `PROBATIONARY` — and their `join_date`. A new member always begins with `membership_status` of `PROBATIONARY`, is not response-eligible, has zero year-to-date points, and, unless an opening `dues_balance_cents` is supplied, a dues balance of zero. The dues balance is outstanding membership dues in cents and is reduced by dues payments; a paid-through date, `dues_paid_through`, is advanced by those payments.

Membership follows a lifecycle the Chief drives. A probationary member becomes `ACTIVE` only once they hold at least one required certification in `CURRENT` status; attempting activation without one is rejected with `ERR_INVALID_STATE`. An active member may be placed on leave of absence, transitioning `ACTIVE → LOA`; going on leave makes the member no longer response-eligible and, additionally, cancels every one of that member's future duty assignments — those in `ASSIGNED` or `CHECKED_IN` on shifts whose `start_at` is later than the current clock are set to `CANCELLED`, and each affected shift recomputes its staffing. A member returns from leave with `LOA → ACTIVE`. A member may be retired from either `ACTIVE` or `LOA`, reaching the terminal `RETIRED` state, or expelled from `ACTIVE`, reaching the terminal `EXPELLED` state; both retirement and expulsion clear response eligibility. `RETIRED` and `EXPELLED` are terminal.

Recording a dues payment reduces `dues_balance_cents` by the supplied `amount_cents`, never dropping below zero (the balance is floored at zero), and if a `paid_through` value is provided it advances `dues_paid_through`. A member's computed summary is available on demand and reflects the member's `training_hours_ytd` (the sum of that member's training hours in the current calendar year), `points_ytd`, `points_tier`, and `stipend_cents`; the summary accepts a `basis` selector described in §3.6.

Whether a member is **response-eligible** — the `response_eligible` flag — is derived and recomputed on every membership transition and on every certification change that could affect it. A member is response-eligible when, and only when, their `membership_status` is `ACTIVE` and none of their required certifications is in `EXPIRED`, `SUSPENDED`, or `REVOKED` status. A member who is `PROBATIONARY`, `LOA`, `RETIRED`, or `EXPELLED` is never response-eligible, regardless of their certifications.

### 3.2. Certifications, Training, and the Recertification Cycle

A certification is created against a member — by a Chief or Officer — and records its `cert_type` (one of `FIREFIGHTER_1`, `EMT_BASIC`, `PARAMEDIC`, `HAZMAT`, `DRIVER_OPERATOR`, or `CPR`), the training `category` counted toward it (one of `FIRE`, `EMS`, `HAZMAT`, `DRIVER`, or `CPR`), and whether it is a required certification via `is_required`, which defaults to true and determines whether the certification gates response eligibility. A new certification starts in `PENDING`, and its `cycle_start_at` is stamped to the current clock at creation. Its `member_id` ties it to its member.

Training is logged as append-only `TrainingRecord` events against a member, each carrying a `category`, a positive number of `hours` (which must be greater than zero), a `training_date`, an optional free-text `description`, and an optional `certification_id` linking it to the certification it counts toward. Logging training refreshes the member's `training_hours_ytd`.

Two computed hour totals accompany every certification and decide whether it may be issued or renewed: `completed_hours_strict` and `completed_hours_carryover`. Both count only training records belonging to the certification's member whose `category` matches the certification's `category`. The **strict** total is the sum of the hours of those matching records whose `training_date` falls on or after the certification's `cycle_start_at` and on or before the current clock. The **carryover** total takes that same in-cycle sum and adds a capped contribution from the 90 days immediately before the cycle began: the sum of matching-category hours whose `training_date` is on or after the point 90 days before `cycle_start_at` and strictly before `cycle_start_at`, but that pre-cycle contribution is added only up to a maximum of 8 hours (if the pre-cycle window holds more than 8 qualifying hours, exactly 8 are carried). Hours are compared exactly against the required threshold.

Each certification type demands a specific number of qualifying hours: `FIREFIGHTER_1` requires 24 hours, `EMT_BASIC` requires 20, `PARAMEDIC` requires 40, `HAZMAT` requires 16, `DRIVER_OPERATOR` requires 12, and `CPR` requires 4. An Officer **issues** a pending certification, transitioning `PENDING → CURRENT`, only when the certification's strict completed hours are at least the required hours for its type; otherwise the issue is rejected with `ERR_INSUFFICIENT_TRAINING_HOURS`. On issue, `issued_at` is set to the current clock and `expires_at` is set to 365 days after `issued_at`; the `cycle_start_at` is left unchanged because it was already fixed at creation. Issuing recomputes the member's response eligibility.

Certifications live on a cyclic lifecycle thereafter. A certification sweep evaluates every certification against the current clock: a `CURRENT` certification whose expiry is within the coming 30 days — that is, the current clock is on or after the instant 30 days before `expires_at` and still before `expires_at` — moves `CURRENT → EXPIRING`, and a member holding an expiring certification remains eligible because `EXPIRING` still counts as valid. Once the current clock reaches or passes `expires_at`, the certification expires: an `EXPIRING` certification moves `EXPIRING → EXPIRED`, and a certification that was still `CURRENT` when its expiry passed (the expiring window was skipped over) moves `CURRENT → EXPIRED` directly. Both expiry paths run the same cascade — **Cascade 1** — described at the end of this subsection with equal force.

An expired certification is brought back with a **renewal**, `EXPIRED → CURRENT`, and an expiring certification may be renewed early, `EXPIRING → CURRENT`; both renewals require the certification's carryover completed hours to be at least the required hours for its type, failing with `ERR_INSUFFICIENT_TRAINING_HOURS` otherwise. A renewal resets the cycle: `cycle_start_at` and `issued_at` are both set to the current clock and `expires_at` becomes 365 days after the new `issued_at`. An Officer may also **suspend** a certification from either `CURRENT` or `EXPIRING`, reaching `SUSPENDED`, and each of those two suspension paths clears the member's eligibility identically if the certification is required. A suspended certification is **reinstated** with `SUSPENDED → CURRENT`, permitted only while the current clock is still before `expires_at`; reinstating a certification whose expiry has already passed is rejected with `ERR_INVALID_STATE`. A Chief may **revoke** a suspended certification, `SUSPENDED → REVOKED`, which is terminal. Every one of these transitions recomputes the member's response eligibility.

**Cascade 1** fires whenever a required certification expires through the sweep. Its first hop recomputes the member's response eligibility, which flips to false when the expiring certification is required. Its second hop cancels that member's forward duty commitments: every duty assignment of that member in `ASSIGNED` or `CHECKED_IN` on a shift whose `start_at` is later than the current clock is set to `CANCELLED`. Its third hop reconciles each affected shift — the shift's assigned count is recomputed and its staffing status is recomputed, dropping to `UNDERSTAFFED` when the count falls below the shift's crew floor.

### 3.3. Stations, Apparatus, Equipment, and Maintenance

Stations are created by a Chief with a `name` and optional `address`. Under a station, a Chief creates apparatus, each carrying its `station_id`, a `unit_designation` such as an engine or medic number, an `apparatus_type` (one of `ENGINE`, `LADDER`, `AMBULANCE`, `RESCUE`, or `TANKER`), and a `min_crew`, the minimum crew required to staff a duty shift on that apparatus, which must be greater than zero. A newly created apparatus has a `posture` of `IN_SERVICE`.

Equipment and personal protective equipment are added to an apparatus by a Chief, each with a `name`, its owning `apparatus_id`, and an `is_critical` flag defaulting to false. Equipment begins `OPERATIONAL`. A Chief may take a piece of equipment out of service, transitioning `OPERATIONAL → OUT_OF_SERVICE`, and later return it, `OUT_OF_SERVICE → OPERATIONAL`. The `is_critical` flag decides the blast radius: a critical item down forces its apparatus fully out of service, while a non-critical item down only downgrades the apparatus to reserve.

An apparatus's `posture` is derived from its equipment and maintenance and recomputed whenever either changes. The rule is evaluated in order: if the apparatus has any maintenance window currently `IN_PROGRESS`, or any critical equipment (an item whose `is_critical` is true) currently `OUT_OF_SERVICE`, the posture is `OUT_OF_SERVICE`; otherwise, if the apparatus has any non-critical equipment currently `OUT_OF_SERVICE`, the posture is `RESERVE`; otherwise the posture is `IN_SERVICE`.

Maintenance is scheduled against an apparatus by a Chief as a `MaintenanceWindow` with a `start_at`, an `end_at` that must be strictly later than `start_at`, and an optional `reason`. The window's occupancy is a half-open interval running from `start_at` up to but not including `end_at`. A new window is rejected with `ERR_MAINTENANCE_OVERLAP` if any other window on the same apparatus in `SCHEDULED` or `IN_PROGRESS` status has a half-open interval that overlaps it; back-to-back windows that merely touch (one ending exactly when the next begins) are allowed, and there is no separation buffer. A new window begins `SCHEDULED`. A Chief starts a window, `SCHEDULED → IN_PROGRESS`, or cancels a scheduled window, `SCHEDULED → CANCELLED` (terminal), and completes an in-progress window, `IN_PROGRESS → COMPLETED` (terminal).

**Cascade 2** ties equipment and maintenance back to the duty roster. When an equipment item goes out of service or a maintenance window is started, the apparatus's posture is recomputed; if it becomes `OUT_OF_SERVICE`, every duty shift on that apparatus that is currently `PUBLISHED` with a `start_at` later than the current clock is suspended, `PUBLISHED → SUSPENDED`. Starting a maintenance window drives the posture to `OUT_OF_SERVICE` directly, suspending those same future published shifts. When the equipment returns to service or the maintenance window completes, the posture is recomputed, and if it recovers to anything other than `OUT_OF_SERVICE`, the shifts that were suspended by the outage are restored, `SUSPENDED → PUBLISHED`, and each recomputes its staffing.

### 3.4. Duty Scheduling: Shifts, Assignments, Check-In, and Verification

An Officer drafts a duty shift naming its `station_id` and `apparatus_id`, where the apparatus must belong to the station or the create is rejected with `ERR_APPARATUS_NOT_AT_STATION`. The shift declares its `start_at`, an `end_at` strictly later than `start_at`, and a `max_crew` crew ceiling that must be greater than zero and at least the crew floor. The crew floor, `min_crew`, may be supplied explicitly; if omitted, it defaults from the apparatus's own `min_crew` at creation. A shift's occupancy, like a maintenance window's, is the half-open interval from `start_at` up to but not including `end_at`. A new shift begins `DRAFT`, and its `assigned_count` starts at zero.

A shift's `staffing_status` is derived from its non-terminal assignments. The assigned count is the number of that shift's assignments in `ASSIGNED`, `CHECKED_IN`, or `VERIFIED`. If that count is zero, or is below the shift's `min_crew`, the staffing is `UNDERSTAFFED`; if the count is at or above `max_crew`, the staffing is `FULL`; otherwise it is `STAFFED`. The empty roster is therefore always understaffed, and the full boundary is inclusive at the ceiling.

An Officer publishes a draft shift, `DRAFT → PUBLISHED`, but only when the apparatus's posture is `IN_SERVICE` or `RESERVE`; publishing a shift whose apparatus posture is `OUT_OF_SERVICE` is rejected with `ERR_APPARATUS_OUT_OF_SERVICE`. As described in §3.3, a published future shift may be system-suspended, `PUBLISHED → SUSPENDED`, when its apparatus loses posture, and restored, `SUSPENDED → PUBLISHED`, when posture recovers. The shift lifecycle is advanced against the clock by a shift sweep: a published shift whose `start_at` has arrived but whose `end_at` has not yet passed moves `PUBLISHED → IN_PROGRESS`, and a shift whose `end_at` has passed moves `IN_PROGRESS → COMPLETED` (terminal). An Officer may cancel a shift from `DRAFT`, `PUBLISHED`, or `SUSPENDED`, reaching `CANCELLED` (terminal); cancelling a published or suspended shift also cancels its assignments still in `ASSIGNED` or `CHECKED_IN`.

Assigning a member to a shift is the most heavily gated operation in the system. An Officer submits the `member_id` to roster together with `expected_duty_shift_version`, and the request must clear, in the priority order of §2.6: the shift and member must exist; the shift must be in a state that accepts assignments; the member must be response-eligible, else `ERR_MEMBER_NOT_RESPONSE_ELIGIBLE`; the member must have no rest-buffer conflict, else `ERR_SHIFT_OVERLAP`; the shift must have room, else `ERR_SHIFT_FULL`; the member must owe no back dues, else `ERR_DUES_OVERDUE`; and the supplied version must match, else `ERR_STALE_VERSION`. The **rest-buffer** rule protects members from being double-booked or worked without rest: a new assignment is rejected if the member holds any other assignment in `ASSIGNED` or `CHECKED_IN` whose shift interval overlaps the new shift's interval, or is separated from it by less than 8 hours — at least 8 hours of separation is required between the two half-open intervals, so overlapping, exactly-adjacent, and merely-close shifts are all rejected. The **capacity** rule rejects an assignment that would raise the assigned count above `max_crew`; equivalently, an assignment is admitted only while the current assigned count is below the ceiling. The **fiscal** rule rejects any member whose `dues_balance_cents` is greater than zero. A successful assignment starts in `ASSIGNED`, increments the shift's `assigned_count`, advances the shift's `version`, and recomputes staffing.

A member checks in to their own assignment, `ASSIGNED → CHECKED_IN`; this is the one action a rank-and-file member performs directly, and the acting member's `X-User-ID` must equal the assignment's `member_id` or it is rejected with `ERR_FORBIDDEN` (an Officer may also perform check-in). Check-in is permitted only while the assignment's shift is `PUBLISHED` or `IN_PROGRESS`, else `ERR_INVALID_STATE`, and it stamps `checked_in_at` to the current clock. An Officer may cancel an assignment from `ASSIGNED` or `CHECKED_IN`, reaching `CANCELLED`; a cancellation — whether direct, or driven by Cascade 1, by a member going on leave, retiring, or being expelled, or by the shift itself being cancelled — recomputes the shift's assigned count and staffing.

When a shift sweep completes a shift, the roster is settled: every assignment still `CHECKED_IN` is verified, `CHECKED_IN → VERIFIED`, and every assignment still merely `ASSIGNED` — a member who never checked in — is marked `NO_SHOW` (both terminal, along with `CANCELLED`). Verification awards the assignment its `duty_points` and credits them to the member's points ledger. The duty points for an assignment are computed from the shift's length: take the shift's duration in hours (the seconds between `start_at` and `end_at` divided by 3600), multiply by half a point per hour, round the product half up to a whole number, and then take the larger of that value and a floor of 2 points — so every verified duty is worth at least 2 points. Each newly verified assignment adds its duty points to the member's year-to-date points.

### 3.5. Incident Response and NFIRS Reporting

An incident carries two independent status dimensions that advance separately: a response dimension and a report dimension. An Officer logs an incident naming its `station_id` and `apparatus_id` — again the apparatus must belong to the station, else `ERR_APPARATUS_NOT_AT_STATION` — its `incident_type` (one of `STRUCTURE_FIRE`, `MVA`, `EMS`, `ALARM`, or `OTHER`), and the `alarm_at` dispatch time. A new incident begins with `response_status` of `DISPATCHED` and `report_status` of `NONE`, and its `report_revision` counter starts at zero.

The response dimension is a strict sequence, each step guarded by the requirement that the incident currently sit in the immediately preceding response state, failing with `ERR_INVALID_STATE` otherwise. Marking the apparatus en route advances `DISPATCHED → ENROUTE` and stamps `enroute_at` to the current clock. Marking arrival advances `ENROUTE → ONSCENE` and stamps `onscene_at`. Clearing the incident advances `ONSCENE → CLEARED` and stamps `cleared_at`; clearing is also the moment turnout credit is settled, as described in §3.6.

The report dimension captures the NFIRS filing and cannot begin until the response is complete. Drafting a report advances `report_status` from `NONE` to `DRAFT`, permitted only when `response_status` is `CLEARED`, else `ERR_INVALID_STATE`; drafting saves the supplied `nfirs_property_use` and `nfirs_actions_taken` codes. Locking a report advances `DRAFT → LOCKED` and requires that both `nfirs_property_use` and `nfirs_actions_taken` be present, else `ERR_NFIRS_INCOMPLETE`; locking increments `report_revision` by one and increments the incident's `version` by one. Amending advances a locked or already-amended report to `AMENDED`: a first amendment from `LOCKED → AMENDED`, and re-amendments `AMENDED → AMENDED`. Every amendment carries `expected_incident_version` and is rejected with `ERR_STALE_VERSION` when that value does not match the incident's current `version` (§2.7); an amendment must also have both NFIRS codes present, else `ERR_NFIRS_INCOMPLETE`, and any newly supplied `nfirs_property_use` and `nfirs_actions_taken` values supersede those of the prior revision. Each amendment increments `report_revision` by one and increments the incident's `version` by one.

### 3.6. Turnout Tracking, Points, Tiers, and Stipends

A turnout records that a member responded to an incident. An Officer creates a `TurnoutResponse` naming the `member_id`, which begins in `RESPONDED` with `responded_at` stamped to the current clock and `turnout_points` of zero. When the incident is cleared (§3.5), every turnout on that incident still in `RESPONDED` is released, `RESPONDED → RELEASED`, its turnout points are computed, and those points are credited to the responding member's ledger.

A turnout's points reward the type of call, the responder's role, and time on scene. The **base** is selected by the incident's type: 5 for `STRUCTURE_FIRE`, 4 for `MVA`, 3 for `EMS`, 2 for `ALARM`, and 1 for `OTHER`. The **role multiplier** is selected by the member's `role_class`: 1.5 for `OFFICER`, 1.4 for `PARAMEDIC`, 1.2 for `EMT`, 1.0 for `FIREFIGHTER`, and 0.5 for `PROBATIONARY`. Scene time is measured from `onscene_at` to `cleared_at`: take that duration in seconds, divide by 3600, and round **up** to the next whole hour to get the scene hours; the **scene component** is the smaller of the scene hours and a cap of 6, multiplied by 1 point per hour. An **officer bonus** of 2 points is added when, and only when, the member's `role_class` is `OFFICER`; otherwise it is zero. The turnout points are the base multiplied by the role multiplier and rounded half up to a whole number, plus the scene component, plus the officer bonus.

A released turnout may be voided by an Officer, `RELEASED → VOIDED` (terminal); voiding a released turnout removes its awarded points from the member's ledger and resets that turnout's `turnout_points` to zero, so the conserved ledger identity of §2.9 still holds. A turnout may also be voided before its incident is cleared, `RESPONDED → VOIDED`; since no points were awarded yet, the member's points are unchanged.

A member's year-to-date points, `points_ytd`, is the conserved sum defined in §2.9 — released turnouts, verified duties, and non-reversed adjustments. Points may be adjusted directly: an Officer records an append-only `PointAdjustment` against a member with a signed `points` delta (which may be negative) and a `reason`. Each adjustment carries a `reversed` flag, false by default; a reversed adjustment drops out of the member's points sum. Recording or reversing an adjustment recomputes the member's points and derived tier and stipend.

The member's **points tier**, `points_tier`, is a threshold over points: the tier is `GOLD` when points are at least 20, `SILVER` when points are at least 10 (but below 20), and `BRONZE` otherwise — so exactly 20 points is `GOLD` and exactly 19 points is `SILVER`.

The member's **stipend**, `stipend_cents`, is computed in a pinned order to resolve the interplay between tier and dues waiver. First establish the points basis P (see the two bases below). Second, determine the tier from P using the same thresholds as `points_tier`: `GOLD` if P is at least 20, `SILVER` if P is at least 10, otherwise `BRONZE`. Third, compute a gross stipend as P multiplied by the tier's per-point rate — 0 cents per point for `BRONZE`, 150 cents per point for `SILVER`, and 250 cents per point for `GOLD`. Fourth, compute a dues waiver: the member's entire `dues_balance_cents` is waived at `GOLD`, half of it (the balance divided by two, floored to a whole cent) is waived at `SILVER`, and nothing is waived at `BRONZE`. Fifth, the net stipend is the gross stipend minus the portion of the dues balance that was **not** waived (that is, minus the balance less the waiver), and never less than zero — the net is the larger of zero and that difference. The tier is fixed from P before the waiver is applied, and the waiver never re-upgrades the tier.

The member summary's `basis` selector chooses which points feed both the reported `points_ytd` and the stipend basis P, defaulting to the final basis. Under the **FINAL** basis (the default, and the basis stamped onto the member's stored `stipend_cents`), P counts only released turnout points, verified duty points, and non-reversed point adjustments; it excludes duty that is scheduled but not yet verified. Under the **PROVISIONAL** basis, P additionally counts scheduled duty that has not yet been verified — assignments in `ASSIGNED` or `CHECKED_IN` are scored as if they will be verified — so a member can preview the points and stipend an upcoming shift would earn.

### 3.7. Fundraising Campaigns and Donations

A Chief creates a fundraising campaign with a `name` and a `goal_cents` target that must be greater than zero; the campaign begins in `DRAFT` with a `raised_cents` total of zero. A Chief opens a campaign, `DRAFT → ACTIVE`, and later closes it, `ACTIVE → CLOSED` (terminal). Donations may be recorded only while a campaign is `ACTIVE`.

A donation is recorded by a Chief or Officer against a campaign with a `donor_name` and an `amount_cents` amount that must be greater than zero; it begins `POSTED`, and posting adds its amount to the campaign's raised total. As established in §2.9, a campaign's `raised_cents` is the conserved sum of its posted donations. A Chief may refund a posted donation, `POSTED → REFUNDED` (terminal), provided the campaign is not `CLOSED`; refunding against a closed campaign is rejected with `ERR_INVALID_STATE`. A refund subtracts exactly the donation's `amount_cents` from the campaign's raised total, preserving the conservation identity.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2 and the authentication rules of §2.1. Creating a new resource returns HTTP 201; state transitions, computed reads, sweeps, and other modifications return HTTP 200; plain reads return HTTP 200. Request bodies, response payloads, and side effects are not restated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an ISO 8601 UTC instant | Chief, Officer |
| POST | `/members` | Create a member (starts PROBATIONARY) | Chief |
| GET | `/members/{memberId}` | Get a member | Chief, Officer, Member |
| GET | `/members` | List members (filter by membership_status) | Chief, Officer, Member |
| GET | `/members/{memberId}/summary` | Computed member summary (basis PROVISIONAL or FINAL) | Chief, Officer, Member |
| POST | `/members/{memberId}/activate` | PROBATIONARY → ACTIVE | Chief |
| POST | `/members/{memberId}/leave` | ACTIVE → LOA | Chief |
| POST | `/members/{memberId}/return` | LOA → ACTIVE | Chief |
| POST | `/members/{memberId}/retire` | ACTIVE or LOA → RETIRED | Chief |
| POST | `/members/{memberId}/expel` | ACTIVE → EXPELLED | Chief |
| POST | `/members/{memberId}/dues-payments` | Record a dues payment | Chief, Officer |
| POST | `/members/{memberId}/certifications` | Create a certification (PENDING) | Chief, Officer |
| GET | `/certifications/{certId}` | Get a certification (incl. completed hours) | Chief, Officer, Member |
| GET | `/certifications` | List certifications (filter by member_id, status) | Chief, Officer, Member |
| POST | `/certifications/{certId}/issue` | PENDING → CURRENT | Officer |
| POST | `/certifications/{certId}/renew` | EXPIRED or EXPIRING → CURRENT | Officer |
| POST | `/certifications/{certId}/suspend` | CURRENT or EXPIRING → SUSPENDED | Officer |
| POST | `/certifications/{certId}/reinstate` | SUSPENDED → CURRENT | Officer |
| POST | `/certifications/{certId}/revoke` | SUSPENDED → REVOKED | Chief |
| POST | `/certifications/sweep` | Evaluate all certifications against the clock | Chief, Officer |
| POST | `/members/{memberId}/training-records` | Append a training record | Chief, Officer |
| GET | `/training-records/{recordId}` | Get a training record | Chief, Officer, Member |
| GET | `/training-records` | List training records (filter by member_id, certification_id) | Chief, Officer, Member |
| POST | `/members/{memberId}/point-adjustments` | Award or deduct points | Officer |
| GET | `/point-adjustments/{adjustmentId}` | Get a point adjustment | Chief, Officer, Member |
| GET | `/point-adjustments` | List point adjustments (filter by member_id) | Chief, Officer, Member |
| POST | `/stations` | Create a station | Chief |
| GET | `/stations/{stationId}` | Get a station | Chief, Officer, Member |
| POST | `/stations/{stationId}/apparatus` | Create apparatus under a station | Chief |
| GET | `/apparatus/{apparatusId}` | Get apparatus (incl. computed posture) | Chief, Officer, Member |
| GET | `/apparatus` | List apparatus (filter by station_id) | Chief, Officer, Member |
| POST | `/apparatus/{apparatusId}/equipment` | Add equipment or PPE | Chief |
| GET | `/equipment/{equipmentId}` | Get equipment | Chief, Officer, Member |
| GET | `/equipment` | List equipment (filter by apparatus_id) | Chief, Officer, Member |
| POST | `/equipment/{equipmentId}/out-of-service` | OPERATIONAL → OUT_OF_SERVICE | Chief |
| POST | `/equipment/{equipmentId}/return-to-service` | OUT_OF_SERVICE → OPERATIONAL | Chief |
| POST | `/apparatus/{apparatusId}/maintenance-windows` | Schedule a maintenance window | Chief |
| GET | `/maintenance-windows/{windowId}` | Get a maintenance window | Chief, Officer, Member |
| GET | `/maintenance-windows` | List maintenance windows (filter by apparatus_id, status) | Chief, Officer, Member |
| POST | `/maintenance-windows/{windowId}/start` | SCHEDULED → IN_PROGRESS | Chief |
| POST | `/maintenance-windows/{windowId}/complete` | IN_PROGRESS → COMPLETED | Chief |
| POST | `/maintenance-windows/{windowId}/cancel` | SCHEDULED → CANCELLED | Chief |
| POST | `/duty-shifts` | Create a duty shift (DRAFT) | Officer |
| GET | `/duty-shifts/{shiftId}` | Get a duty shift | Chief, Officer, Member |
| GET | `/duty-shifts` | List duty shifts (filter by station_id, apparatus_id, status) | Chief, Officer, Member |
| POST | `/duty-shifts/{shiftId}/publish` | DRAFT → PUBLISHED | Officer |
| POST | `/duty-shifts/{shiftId}/cancel` | DRAFT, PUBLISHED, or SUSPENDED → CANCELLED | Officer |
| POST | `/duty-shifts/sweep` | Advance shift lifecycle against the clock | Chief, Officer |
| POST | `/duty-shifts/{shiftId}/assignments` | Assign a member to a shift (OCC on shift version) | Officer |
| GET | `/duty-assignments/{assignmentId}` | Get a duty assignment | Chief, Officer, Member |
| GET | `/duty-assignments` | List duty assignments (filter by duty_shift_id, member_id, status) | Chief, Officer, Member |
| POST | `/duty-assignments/{assignmentId}/check-in` | ASSIGNED → CHECKED_IN (own assignment) | Member, Officer |
| POST | `/duty-assignments/{assignmentId}/cancel` | ASSIGNED or CHECKED_IN → CANCELLED | Officer |
| POST | `/incidents` | Log an incident (DISPATCHED, report NONE) | Officer |
| GET | `/incidents/{incidentId}` | Get an incident | Chief, Officer, Member |
| GET | `/incidents` | List incidents (filter by station_id, apparatus_id) | Chief, Officer, Member |
| POST | `/incidents/{incidentId}/enroute` | response DISPATCHED → ENROUTE | Officer |
| POST | `/incidents/{incidentId}/arrive` | response ENROUTE → ONSCENE | Officer |
| POST | `/incidents/{incidentId}/clear` | response ONSCENE → CLEARED; release turnouts | Officer |
| POST | `/incidents/{incidentId}/report` | report NONE → DRAFT | Officer |
| POST | `/incidents/{incidentId}/report/lock` | report DRAFT → LOCKED | Officer |
| POST | `/incidents/{incidentId}/report/amend` | report LOCKED or AMENDED → AMENDED (OCC) | Officer |
| POST | `/incidents/{incidentId}/turnouts` | Record a member turnout (RESPONDED) | Officer |
| GET | `/turnouts/{turnoutId}` | Get a turnout response | Chief, Officer, Member |
| GET | `/turnouts` | List turnouts (filter by incident_id, member_id, status) | Chief, Officer, Member |
| POST | `/turnouts/{turnoutId}/void` | RESPONDED or RELEASED → VOIDED | Officer |
| POST | `/campaigns` | Create a fundraising campaign (DRAFT) | Chief |
| GET | `/campaigns/{campaignId}` | Get a campaign | Chief, Officer, Member |
| GET | `/campaigns` | List campaigns (filter by status) | Chief, Officer, Member |
| POST | `/campaigns/{campaignId}/open` | DRAFT → ACTIVE | Chief |
| POST | `/campaigns/{campaignId}/close` | ACTIVE → CLOSED | Chief |
| POST | `/campaigns/{campaignId}/donations` | Record a donation (POSTED) | Chief, Officer |
| GET | `/donations/{donationId}` | Get a donation | Chief, Officer, Member |
| GET | `/donations` | List donations (filter by campaign_id, status) | Chief, Officer, Member |
| POST | `/donations/{donationId}/refund` | POSTED → REFUNDED | Chief |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_APPARATUS_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_MAINTENANCE_WINDOW_NOT_FOUND` | 404 |
| `ERR_DUTY_SHIFT_NOT_FOUND` | 404 |
| `ERR_DUTY_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_TURNOUT_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_DONATION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_NOT_RESPONSE_ELIGIBLE` | 409 |
| `ERR_APPARATUS_NOT_AT_STATION` | 409 |
| `ERR_APPARATUS_OUT_OF_SERVICE` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_MAINTENANCE_OVERLAP` | 409 |
| `ERR_SHIFT_FULL` | 409 |
| `ERR_INSUFFICIENT_TRAINING_HOURS` | 422 |
| `ERR_NFIRS_INCOMPLETE` | 422 |
| `ERR_DUES_OVERDUE` | 402 |
| `ERR_STALE_VERSION` | 412 |

# Airport Noise Abatement API — Product Requirements Document

## 1. Introduction

An airport noise office operates a continuing dialogue with its neighboring communities: residents file disturbance reports, analysts match those reports against radar-derived flight tracks and a network of permanent noise monitors, carriers answer formal inquiries, and a Part 150 noise compatibility study converts measured and modeled exposure into land-use findings and a federally funded sound insulation program. This document specifies the API that serves as the system of record for that entire loop — complaint intake and flight correlation, monitor evidence and event classification, voluntary curfew compliance scoring, operator notification and escalation, repeat-complainant outreach, study and parcel management, grant obligation accounting, and the quarterly report the airport board approves and publishes.

Two design pressures shape every requirement below. The first is evidentiary discipline: a complaint may only be substantiated against measured or correlated evidence, a monitor with poor uptime cannot anchor a verified event, and a published quarter is locked against late filings. The second is fiduciary discipline: the insulation fund is a ledger whose reservations, disbursements and forecasted pipeline must reconcile to the cent at all times, and the individuals who draft a quarterly report are not the individuals who approve it. All API resources are mounted under `/noise-program`, and every temporal rule in the program is evaluated against a server-side logical clock rather than the host wall clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes seven roles: `NoiseOfficeAdmin`, `NoiseAnalyst`, `CommunityLiaison`, `StudyCoordinator`, `BoardMember`, `OperatorRep`, and `Complainant`. Access to each operation is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_UNAUTHORIZED_ROLE`.

Five of the seven roles carry opaque identifiers. When `X-User-Role` is `NoiseOfficeAdmin`, `NoiseAnalyst`, `CommunityLiaison`, `StudyCoordinator`, or `BoardMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `created_by_user_id` or `approved_by_user_id` on a quarterly report — but it never compares that value to any entity's `id`. The remaining two roles are entity-backed. When `X-User-Role` is `OperatorRep`, `X-User-ID` is the `id` of the acting Operator; ownership checks on any resource that references an operator compare the resource's `operator_id` field to `X-User-ID`. When `X-User-Role` is `Complainant`, `X-User-ID` is the `id` of the acting Complainant; ownership checks compare the resource's `complainant_id` field to `X-User-ID`. An entity-backed caller acting on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Lazy Sweeps

Every temporal rule in this document — complaint filing windows, reopen and appeal deadlines, fund intake windows, offer expirations, operator response deadlines, trailing 30-day and 90-day measurement windows, and quarter boundaries — is evaluated against a server-side logical clock, never the host wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An administrator-only, test-driving capability advances the logical clock to a supplied `to_iso8601` instant and echoes the new value back as `current_utc` in its response.

Advancing the clock fires exactly one automatic sweep: any operator notification whose response deadline has passed while it sits unanswered is escalated, with the full escalation cascade that implies (see §3.5). Offer expirations are deliberately not swept by the clock. An expired offer is retracted lazily — only when the application holding it is next read, whether individually or through a list — and the details of that lazy sweep live with the grant program in §3.8. Reading a notification likewise re-evaluates whether its deadline has passed and escalates it if so.

### 2.5. Common Resource Properties

All primary resources (complainants, complaints, flight operations, operators, monitors, noise events, curfew rules, operator notifications, noise studies, land-use parcels, sound insulation applications, insulation funds, outreach cases, and quarterly reports) include a standard set of system-managed fields:

- **`id`** (string): a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp, maintained with the same format, indicating when the resource was last modified; it refreshes upon any change to the resource's properties.
- **`version`** (integer): a system-managed integer that increments by exactly one on every modification to the resource, including modifications caused by system-driven transitions, cascades, and counter recomputations performed on that resource.

The single exception is the **MonitorOutage** record. An outage is an append-only interval and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, because an outage is never mutated after it is recorded.

### 2.6. Optimistic Concurrency Control

Exactly three write operations in the system are guarded by optimistic concurrency control; no other endpoint accepts a version field.

First, editing the narrative of a quarterly report — the report-editing endpoint (`PATCH /noise-program/quarterly-reports/{reportId}`) — requires the request to carry `expected_report_version` holding the report `version` the client last observed. If the report's current `version` no longer matches, another edit has advanced the report since the client last read it, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client's change, which is based on a stale view, is not applied.

Second, correlating a complaint to flight or event evidence — the correlate endpoint (`POST /noise-program/noise-complaints/{complaintId}/correlate`) — requires `expected_complaint_version` matching the complaint's current `version`. A mismatch means a prior correlation or another mutation has advanced the complaint's version, and the new correlation would supersede data the client never saw; the request is rejected with `ERR_STALE_CORRELATION_VERSION` (HTTP 412).

Third, issuing an insulation offer directly — the issue-offer endpoint (`POST /noise-program/sound-insulation-applications/{applicationId}/issue-offer`) — requires `expected_fund_version` matching the target fund's current `version`. The reservation arithmetic must be based on the fund's current `available_cents`, not a snapshot the client read earlier; a mismatch is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412).

### 2.7. Units, Precision and Rounding Discipline

All decibel quantities, percentages, and scores reported by the system are carried at one decimal place using round-half-up: this covers `correlation_confidence`, `classification_confidence`, a monitor's `uptime_pct_30d`, a parcel's `dnl_db_effective` (and the measured and modeled inputs `dnl_db_measured` and `dnl_db_modeled`, which are supplied at one decimal), computed day-evening-night levels, per-operator curfew compliance scores, and the community annoyance index. Counts — complaints, events, movements, notifications, contact attempts — are integers.

Monetary values are always integers denominated in whole cents: `total_allocation_cents`, `available_cents`, `reserved_cents`, `disbursed_cents`, `est_cost_cents`, `actual_cost_cents`, `offered_amount_cents`, `tier_cap_cents`, and the fund's `projected_pipeline_cents`. Grant obligations follow a pinned rounding order described in §3.8: each component of an obligation is rounded half-up to whole cents first, and only then are the components summed. Summing unrounded components and rounding the total is forbidden.

### 2.8. Community Zones: The Geographic Spine

A `zone_code` labels a community zone around the airport and threads through nearly every aggregate the program produces. Complainants declare the zone of their address at registration; monitors are sited in a zone; flight operations record the corridor zone they overfly; land-use parcels belong to a zone. The zone drives the distance penalty in complaint-to-flight correlation scoring (§3.4), scopes the complaints, substantiations, and curfew violations that feed the community annoyance index (§3.6), and organizes list filtering across complaints, monitors, and complainants.

### 2.9. Cascading Side Effects and Cross-Entity Consistency

Many single operations mutate more than one resource, and the system treats those cascades as part of the operation's atomic contract rather than as background jobs. Four named cascades recur throughout §3. **Cascade A** fires when a noise study is adopted: every parcel of the study recomputes its exposure under the final variant, insulation applications whose eligibility evaporates are revoked by the system, priority scores refresh, and the active fund's pipeline forecast is recomputed. **Cascade B** fires when a noise event is classified as aircraft: the linked flight's event counter advances, complaints already correlated to that event recompute their confidence with event corroboration, and a threshold crossing can draft an advisory notification to the operator. **Cascade C** fires on notification escalation: the operator's compliance standing is demoted, and a landing on `PROBATION` revokes the operator's curfew grace band entirely. **Cascade D** fires when a complaint is withdrawn: draft notifications linked to the complaint close automatically and the affected operators' notification counters are recomputed.

Counter fields on complainants, operators, flights, monitors, and funds are maintained by these cascades and by the lifecycle transitions that feed them; they are never accepted from clients. Whenever a transition's side effects touch another entity's stored counters or flags, that touch is part of the same consistent update, and the primary resource undergoing the transition always increments its own `version` by one.

### 2.10. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — for example an outage beneath a monitor, or a parcel beneath a study — the system validates the existence of each identifier in sequential, left-to-right order. The request is rejected immediately with a `404 Not Found` error carrying `ERR_NOT_FOUND` for the *first* identifier in the path that does not resolve, before any later segment or business rule is examined. A request to record an outage under a non-existent monitor therefore fails on the monitor identifier before the outage payload is ever considered.

### 2.11. Validation Order and Request-Shape Discipline

Every request is checked against a fixed sequence of gates, and the first gate that fails determines the error returned; later gates are not evaluated for that request. The ordering is deliberate — authentication outranks shape, shape outranks authorization, existence outranks state, and fiscal guards are evaluated last:

1. **Presence of credentials** — both `X-User-ID` and `X-User-Role` headers are present and the role is one of the seven declared roles, else `ERR_UNAUTHENTICATED`.
2. **Request shape** — required fields are present, types and enum members are valid, `quarter_label` matches the `YYYY-Qn` pattern, and numeric ranges hold: `rooms_count` is at least 1, `est_cost_cents` is at least 1, curfew window minutes lie between 0 and 1439 inclusive with `window_end_minute` strictly after `window_start_minute`, an outage's `end_at` is strictly after its `start_at`, `effective_to` is on or after `effective_from`, `intake_closes_at` is strictly after `intake_opens_at`, and `duration_seconds` is at least 5. Failures are rejected with `ERR_VALIDATION`. Unknown fields, and system-managed or computed fields sent in the request body, are ignored — never rejected.
3. **Role authorization** — the caller's role appears in the endpoint's authorized role list, else `ERR_UNAUTHORIZED_ROLE`.
4. **Entity-backed ownership** — a `Complainant` caller may only act on resources whose `complainant_id` equals `X-User-ID`, and an `OperatorRep` caller only on resources of the operator whose `operator_id` equals `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER`.
5. **Segregation of duties** — the approver of a quarterly report must not be the report's creator, else `ERR_SEGREGATION_OF_DUTIES`.
6. **Path existence** — path identifiers resolve, left to right, else `ERR_NOT_FOUND`.
7. **Body foreign-key existence** — a `complainant_id` in the body must resolve (else `ERR_COMPLAINANT_NOT_FOUND`), a `flight_id` (else `ERR_FLIGHT_NOT_FOUND`), a `noise_event_id` (else `ERR_EVENT_NOT_FOUND`), a `parcel_id` (else `ERR_PARCEL_NOT_FOUND`), an `operator_id` (else `ERR_OPERATOR_NOT_FOUND`), and a study reference in `supersedes_study_id` (else `ERR_STUDY_NOT_FOUND`).
8. **State-machine legality** — the target resource sits in a valid from-state for the attempted transition (else the entity-specific invalid-state error such as `ERR_INVALID_COMPLAINT_STATE` or `ERR_INVALID_EVENT_STATE`), and any optimistic-concurrency field matches the parent's current `version` (else the corresponding stale-version error).
9. **Data-integrity guards** — the regulatory guards of §3: the published-quarter lock, the event-during-outage prohibition, and the monitor uptime floor.
10. **Temporal windows** — submission intake windows, offer expiry, reopen and appeal windows, and quarter closure.
11. **Conflicts, uniqueness, and thresholds** — duplicate identifiers, overlapping windows, active-application conflicts, response-length minimums, confidence thresholds, retry limits, and the like.
12. **Cross-entity state guards** — parcel eligibility, study adoption, linked-complaint finality, unclassified-event gates, and correlation target state.
13. **Fiscal guards** — the existence of an active fund and the sufficiency of its available balance, evaluated after everything else.

## 3. Business Logic & Workflows

### 3.1. Enrollment and Standing: Operators and the Complainant Registry

Before any noise data flows, the office registers the program's participants. A `NoiseOfficeAdmin` registers each carrier as an **Operator** with its legal `name`, a two-to-three-letter `iata_code`, and a noise-office `contact_email`. The `iata_code` is unique across all operators; a duplicate registration is rejected with `ERR_DUPLICATE_IATA_CODE`. A new operator begins with `compliance_standing` of `GOOD` and a `curfew_grace_minutes` allowance of 15 minutes — the grace band applied inside curfew windows, described in §3.2. Its `compliance_score_latest` starts empty, and its notification counters (`notifications_sent_total`, `notifications_open`, `notifications_closed`, `notifications_draft`) start at zero.

A **Complainant** is registered by a `CommunityLiaison` or a `NoiseOfficeAdmin` with `full_name`, `email`, an optional `phone`, `address_line`, the community `zone_code`, and an `outreach_opt_in` flag that defaults to `true` when omitted. Staff may later update these contact details through the complainant update operation, which increments the complainant's `version` by one. Every complainant carries a `standing` classification that the system derives automatically — never accepts from clients — together with a family of counters: `filed_total` (every complaint ever filed, regardless of outcome), `complaints_90d` (the trailing-window count defined below), `open_count`, `closed_count`, `withdrawn_count`, and `substantiated_count`. At registration the standing is `GOOD_STANDING` and all counters are zero.

The standing machine re-evaluates after every complaint creation, closure, reopening, or withdrawal, and after any outreach case resolution. The driving metric, `complaints_90d`, counts the complainant's complaints whose `created_at` falls inside the window from the later of (ninety days before now) and (the complainant's `repeat_baseline_at`, when one is set) up to and including now, excluding complaints in `WITHDRAWN`. When the recomputed count reaches ten while remaining below twenty-five, standing moves from `GOOD_STANDING` to `REPEAT`; at twenty-five or more it moves from `REPEAT` to `RESTRICTED`, with both thresholds inclusive. The boundaries are equally precise in the downward direction: a `RESTRICTED` complainant whose count falls back into the ten-to-twenty-four range returns to `REPEAT`, and one whose count falls to nine or fewer returns to `GOOD_STANDING`, as does a `REPEAT` complainant whose count drops below ten. Aging alone can cause this decay — filings older than ninety days simply fall out of the window — as can the outreach baseline reset described in §3.6.

While a complainant is `RESTRICTED`, their `low_priority_flag` is `true`, and their complaints never trigger automatic operator notifications — the correlation cascade of §3.4 suppresses the draft it would otherwise create. The flag returns to `false` the moment standing leaves `RESTRICTED`. Staff can read any complainant record; a `Complainant` caller may read only the record whose `id` equals their `X-User-ID`. The complainant list supports `standing` and `zone_code` filters, and each complainant's complaints and outreach cases are browsable through nested list endpoints that accept a `status` filter.

### 3.2. Flight Operations and the Voluntary Curfew Program

Flight records anchor both complaint correlation and curfew compliance. A `NoiseOfficeAdmin` registers each **FlightOperation** with its `flight_number`, the operating carrier's `operator_id`, an `aircraft_type` code such as B738, an `engine_class` of `STAGE_3`, `STAGE_4`, or `STAGE_5`, an `operation_type` of `ARRIVAL`, `DEPARTURE`, or `RUNUP`, the `runway_code` designator, the `scheduled_at` time in UTC, and the community `zone_code` the flight overflies. New flights are `SCHEDULED`. When the outcome is known, the administrator records it through the flight update operation: a flight that flew becomes `OPERATED` and must carry its `actual_at` time in the same update — omitting it is a shape failure rejected with `ERR_VALIDATION` — while one that did not becomes `CANCELLED` or `DIVERTED`. All three outcomes are terminal, and recording any outcome against a flight that is no longer `SCHEDULED` is rejected with `ERR_INVALID_FLIGHT_STATE`. The update may also record an `exemption_code` of `NONE` (the default), `EMERGENCY`, `WEATHER_DIVERT`, or `ATC_DELAY`.

The voluntary curfew program is expressed through **CurfewRule** records created by a `NoiseOfficeAdmin`. Each rule names its `runway_code`, a `season` of `SUMMER` (calendar months four through nine), `WINTER` (months ten through three, spanning the year boundary), or `YEAR_ROUND`, and a closed minute-of-day window from `window_start_minute` through `window_end_minute`, both between 0 and 1439 inclusive, with the end strictly after the start — cross-midnight windows are not expressible. The `applies_to` scope is `ARRIVAL`, `DEPARTURE`, or `BOTH`; `BOTH` matches any operation type, while a `RUNUP` operation matches only rules scoped `BOTH`. A per-rule `grace_minutes` defaults to 15 when omitted, and `effective_from` / `effective_to` bound the rule's effective dates, both inclusive. A new rule conflicts with an existing `ACTIVE` rule — rejected with `ERR_CURFEW_WINDOW_OVERLAP` — when they share the same runway, their seasons intersect, their `applies_to` scopes intersect, their effective date ranges intersect, and their minute windows intersect *or touch*: because the minute intervals are closed, a rule ending at minute 1380 conflicts with one starting at 1380. Rules are created `ACTIVE`; an administrator may suspend a rule, moving it to `SUSPENDED`, and suspended rules are ignored both by curfew matching and by the overlap check. Suspending a rule that is not `ACTIVE` is rejected with `ERR_INVALID_CURFEW_RULE_STATE`. The rule list supports `runway_code`, `season`, and `status` filters.

The moment a flight becomes `OPERATED`, the system computes two flags exactly once and never recomputes them: `curfew_movement` and `curfew_violation`, both starting from a default of `false`. The flight is a curfew movement when its `actual_at` UTC minute-of-day falls inside the window — both boundary minutes included — of at least one matching `ACTIVE` rule: matching means the rule's runway equals the flight's `runway_code`, the rule's season covers the month of `actual_at`, the rule's `applies_to` covers the flight's `operation_type`, and the calendar date of `actual_at` lies between `effective_from` and `effective_to` inclusive. A curfew movement is additionally a violation when two conditions hold: the minute-of-day lies inside the grace-trimmed interior of the window — from the window start plus the effective grace through the window end minus the effective grace, with those boundary minutes themselves counting as violations — and the flight's recorded `exemption_code` is `NONE`. The effective grace is the smaller of the rule's `grace_minutes` and the operator's current `curfew_grace_minutes`; an operator whose grace has been revoked to zero therefore faces the untrimmed window. Once written, both flags are immutable.

Curfew compliance is scored per operator per quarter. The movements considered are the operator's `OPERATED` flights whose `actual_at` falls in the quarter's half-open window and whose `curfew_movement` flag is set; violations are the subset whose `curfew_violation` flag is set — exempt movements (`EMERGENCY`, `WEATHER_DIVERT`, `ATC_DELAY`) were already excluded when the flag was computed. Each violation costs one hundred base points multiplied by an engine-class multiplier — one and a half for `STAGE_3`, one for `STAGE_4`, one half for `STAGE_5` — and by a standing multiplier of 1.25 when the operator is on `PROBATION`, otherwise 1.0. The evaluation order is pinned: the standing multiplier always uses the operator's currently stored `compliance_standing` *before* this recalculation, so a freshly computed score never feeds back into its own arithmetic. The score itself is one thousand minus the summed points, floored at zero and rounded half-up to one decimal place. Standing bands follow from the score: 900 or above is `GOOD`, at least 700 but below 900 is `WATCH`, and below 700 is `PROBATION`.

The compliance-summary read computes this score for a requested `quarter` and returns an object with the `quarter` label, the `curfew_movements` and `curfew_violations` counts, the `score`, and the resulting `standing`; computing it also stores the score on the operator's `compliance_score_latest` and updates the operator's stored `compliance_standing` to the band the score implies. An `OperatorRep` caller may request only their own operator's summary, may read only their own operator record, and sees the flight list forced to their own operator — staff roles see the full list with `operator_id`, `status`, `runway_code`, and `quarter` filters. Each flight also carries two maintained counters: `linked_complaint_count`, the complaints currently correlated to it, and `linked_event_count`, the classified noise events linked to it; both move through the cascades of §3.3 and §3.4.

### 3.3. Monitoring the Soundscape: Stations, Outages and Noise Events

A `NoiseOfficeAdmin` registers each **NoiseMonitor** with a unique `station_code` (a duplicate is rejected with `ERR_DUPLICATE_STATION_CODE`), the `zone_code` it covers, its `latitude` and `longitude`, and a `commissioned_at` timestamp. Monitors are born `ONLINE` and are eventually retired: decommissioning moves a monitor to `DECOMMISSIONED`, is only valid from `ONLINE`, and otherwise fails with `ERR_MONITOR_NOT_ONLINE` — the same error that rejects event ingestion into a decommissioned station. The monitor list supports `status` and `zone_code` filters.

Stations go quiet for known reasons, recorded as **MonitorOutage** intervals: each outage carries the `monitor_id` of the affected station, a `start_at` and an `end_at` bounding the outage as a half-open interval — the start is inclusive, the end is exclusive, and the end must be strictly after the start — an `outage_type` of `CALIBRATION`, `MAINTENANCE`, or `FAULT`, and an optional free-text `reason`. Two outages on the same monitor may touch but never overlap: an existing outage ending exactly when the new one begins is permitted, while any positive intersection of the half-open intervals is rejected with `ERR_OUTAGE_OVERLAP`. Outages feed the monitor's `uptime_pct_30d`: over the trailing 30-day window — 43,200 minutes, half-open from thirty days ago up to now — the system sums each outage's overlap with that window, clipped to the window's edges, subtracts the total from 43,200, divides by 43,200, and multiplies by 100, rounding half-up to one decimal place. The percentage is recomputed whenever an outage is recorded and is consulted as a hard gate during event verification.

A `NoiseOfficeAdmin` ingests each **NoiseEvent** against its capturing monitor with the event's `started_at`, a `duration_seconds` of at least 5, the maximum A-weighted level `lmax_db`, and the sound exposure level `sel_db`. Ingestion is refused with `ERR_EVENT_DURING_OUTAGE` when the event's own half-open interval — from `started_at` through `started_at` plus its duration — overlaps any recorded outage on the same monitor. A new event is `CAPTURED`; the system immediately computes its `exceeds_threshold` flag (`true` when `lmax_db` is at least 65.0 dB), derives its `quarter_key` label such as `2026-Q3` from `started_at`, and increments the monitor's `events_captured_total`, which counts every event ever ingested on the station — including ones later discarded. The event list supports `monitor_id`, `flight_id`, `status`, and `quarter` filters.

An analyst then walks the event through screening. Beginning screening moves `CAPTURED` to `SCREENING`. Classification records the analyst's `classification` choice — `AIRCRAFT`, `COMMUNITY`, or `MIXED` — along with an optional `classification_basis` note, and moves the event to `CLASSIFIED_AIRCRAFT`, `CLASSIFIED_COMMUNITY`, or `CLASSIFIED_MIXED` respectively. An aircraft classification requires a `flight_id` that resolves (else `ERR_FLIGHT_NOT_FOUND`); a community classification forbids one (supplying `flight_id` is rejected with `ERR_VALIDATION`); a mixed classification accepts one optionally. Classification computes the event's `classification_confidence`: start from 40, add twice the amount by which `lmax_db` exceeds 65.0 (a negative contribution when the level is below the threshold), add 20 when `duration_seconds` is at least 30, add 20 when a flight is linked, cap the result at 100, and round half-up to one decimal place; before its first classification the field reads 0.

Classifying an event as aircraft fires **cascade B** in three hops. First, the linked flight's `linked_event_count` increments by one. Second, every complaint currently holding this event as its correlated evidence and sitting in `CORRELATED` recomputes its `correlation_confidence` *with* the event-corroboration bonus of §3.4 applied, refreshing `substantiation_eligible` accordingly. Third, if the flight's event count crosses the threshold of three — reaching three from below — the system drafts an advisory operator notification to the flight's operator. A mixed classification with a flight linked performs only the first hop: the event count increments, but no complaint recompute and no automatic notification follow. Moving an event backward is also possible: reclassification returns any classified event to `SCREENING`, clears its `flight_id`, increments `reclassify_count` (at most two reclassifications are permitted — a third attempt is rejected with `ERR_RECLASSIFY_LIMIT_REACHED`), decrements the previously linked flight's `linked_event_count` as compensation when one was attached, and recomputes correlated complaints' confidence *without* the corroboration bonus.

Verification is the evidentiary seal: from any of the three classified states an analyst may verify the event, moving it to `VERIFIED`, but only when its `classification_confidence` is at least 70.0 (else `ERR_CONFIDENCE_BELOW_THRESHOLD`) and the capturing monitor's `uptime_pct_30d` is at least 80.0 percent, boundary inclusive (else `ERR_UPTIME_BELOW_FLOOR`). An event still in `SCREENING` may instead be discarded with a `reason`, moving it to `DISCARDED`. Both `VERIFIED` and `DISCARDED` are terminal, and any transition attempted from an impermissible state is rejected with `ERR_INVALID_EVENT_STATE`.

Finally, the monitor's day-evening-night average level is available as a computed read for a given UTC `date`. The inclusion set is the monitor's events whose `started_at` falls inside that calendar date and whose status is `CLASSIFIED_AIRCRAFT`, `CLASSIFIED_MIXED`, or `VERIFIED`; `CAPTURED`, `SCREENING`, `CLASSIFIED_COMMUNITY`, and `DISCARDED` events are excluded. A night event — one whose `started_at` hour falls from 22:00 up to midnight or from midnight up to but not including 07:00 UTC — contributes its `sel_db` plus a 10 dB penalty; day events contribute `sel_db` unadjusted. Each included event contributes ten raised to the power of its adjusted level divided by ten; those powers are summed, divided by the 86,400 seconds of a day, and the result is ten times the base-10 logarithm of that quotient, rounded half-up to one decimal place. When no events qualify, the level reads 0.0. The response carries the requested `date`, the computed `dnl_db`, and the `day_event_count` and `night_event_count` behind it.

### 3.4. Complaint Intake, Flight Correlation and Closure

Anyone in the community can disturb the noise office, but the system requires a registered complainant. A complaint is filed either by a `Complainant` caller for themselves — the body's `complainant_id` must equal their `X-User-ID` — or by a `CommunityLiaison` on the complainant's behalf. The filing carries `complainant_id`, the `occurred_at` instant of the disturbance in UTC, a `channel` of `WEB`, `PHONE`, `APP`, or `EMAIL`, a `disturbance_type` of `LOUD_EVENT`, `SLEEP_DISTURBANCE`, `LOW_FLYING`, `GROUND_RUNUP`, `VIBRATION`, or `OTHER`, and an optional free-text `narrative`. A `complainant_id` that does not resolve is rejected with `ERR_COMPLAINANT_NOT_FOUND`, and a filing whose `occurred_at` falls inside a quarter whose report has been published is rejected with `ERR_REPORT_QUARTER_LOCKED` — the published-quarter lock of §3.9. A new complaint is `RECEIVED`; filing also refreshes the complainant's counters and trailing-window count, re-evaluating standing per §3.1 and auto-creating an outreach case when the standing crosses into `REPEAT` or `RESTRICTED`.

The complaint's counter family is maintained continuously. `open_count` tracks complaints in `RECEIVED`, `UNDER_REVIEW`, `AWAITING_COMPLAINANT`, `CORRELATED`, or `REOPENED`; `closed_count` tracks `CLOSED_SUBSTANTIATED` and `CLOSED_UNSUBSTANTIATED`; `withdrawn_count` tracks `WITHDRAWN`; and `substantiated_count` tracks those currently `CLOSED_SUBSTANTIATED`.

Analysts work the complaint through its review loop. Beginning review moves `RECEIVED` to `UNDER_REVIEW`. Requesting more information moves `UNDER_REVIEW` to `AWAITING_COMPLAINANT` and records the analyst's `info_request_note`. Providing information — by the complainant-owner or by a `CommunityLiaison` — moves the complaint back to `UNDER_REVIEW` with the supplied `narrative` appended to the record. Any of these transitions attempted from the wrong state is rejected with `ERR_INVALID_COMPLAINT_STATE`, and a `Complainant` acting on someone else's complaint is rejected with `ERR_NOT_RESOURCE_OWNER`.

Correlation attaches evidence. From `UNDER_REVIEW` — or again from `CORRELATED`, where re-correlation supersedes the prior attachment — a `NoiseAnalyst` correlates the complaint, supplying a `flight_id`, a `noise_event_id`, or both; supplying neither is rejected with `ERR_CORRELATION_TARGET_REQUIRED`. The request must also carry `expected_complaint_version` per the optimistic concurrency rule of §2.6. A supplied flight must be `OPERATED` (else `ERR_FLIGHT_NOT_OPERATED`), and a supplied event must be `CLASSIFIED_AIRCRAFT`, `CLASSIFIED_MIXED`, or `VERIFIED` (else `ERR_EVENT_NOT_CLASSIFIED`).

When a flight is supplied, the confidence score is computed under two variants. Let the elapsed time be the absolute difference, in seconds, between the complaint's `occurred_at` and the flight's `actual_at`. The `STRICT` variant is tried first and applies when the elapsed time is at most 300 seconds: the score starts at 100, decays by 40 points proportionally across the 300-second window, subtracts a 10-point penalty when the flight's `zone_code` differs from the complainant's, and adds a 15-point bonus when a linked event is `CLASSIFIED_AIRCRAFT` or `VERIFIED`. When no `STRICT`-eligible flight exists, the `RELAXED` variant applies while the elapsed time is at most 1200 seconds: the score starts at 85, decays by 55 points proportionally across the 1200-second window, subtracts a 15-point zone penalty, and adds a 10-point event bonus under the same condition. Either way the score is clamped to the range from 0 to 100 and rounded half-up to one decimal place, and `correlation_variant_used` records which variant produced it. An event-only correlation — no flight supplied — scores a flat 70.0 when the event is `VERIFIED` and 55.0 otherwise. If neither variant yields an eligible correlation, the request is rejected with `ERR_CORRELATION_WINDOW_EXCEEDED`. A complaint that has never been correlated reads `correlation_confidence` 0.0 with variant `NONE`.

A successful correlation writes `correlated_flight_id` and `correlated_event_id`, sets `substantiation_eligible` to `true` exactly when the confidence is at least 60.0, and maintains the flights' counters: a superseded prior flight's `linked_complaint_count` decrements as compensation, and the newly linked flight's increments by one. When that increment carries the new flight's count across the threshold of five — from below five to five or more — the system automatically drafts an advisory notification to that operator; complaints filed by a complainant whose `low_priority_flag` is set never trigger this automatic notification.

Closure comes in two flavors, both via the analyst's close action carrying an `outcome`. Closing with `outcome` `SUBSTANTIATED` requires the complaint to be `CORRELATED` and its `correlation_confidence` to be at least 60.0 (else `ERR_CONFIDENCE_BELOW_THRESHOLD`); the complaint becomes `CLOSED_SUBSTANTIATED` with `closure_outcome` `SUBSTANTIATED` and `closed_at` set to now, and the complainant's counters shift — `open_count` down one, `closed_count` and `substantiated_count` up one each — followed by the standing re-evaluation. Closing with `outcome` `UNSUBSTANTIATED` is permitted from `UNDER_REVIEW` or from `CORRELATED`; the complaint becomes `CLOSED_UNSUBSTANTIATED`, and when it had been correlated the linked flight's `linked_complaint_count` decrements as compensation. A substantiated close never releases the flight link — the correlation stands as the record of a verified disturbance.

A closed complaint is not necessarily finished. The complainant-owner or a `CommunityLiaison` may reopen it, with a `reason`, within thirty days of `closed_at` — later is rejected with `ERR_REOPEN_WINDOW_EXPIRED` — and at most three times in its life; a fourth attempt is rejected with `ERR_REOPEN_LIMIT_REACHED`. Reopening moves the complaint to `REOPENED`, increments `reopen_count`, clears `closed_at`, and compensates the complainant's counters (`closed_count` down, `open_count` up, and `substantiated_count` down one when the closure had been substantiated), again followed by standing re-evaluation. An analyst then resumes review, moving `REOPENED` back to `UNDER_REVIEW` for another pass through the loop.

Withdrawal ends everything. From any state other than `WITHDRAWN`, the complainant-owner or a `CommunityLiaison` may withdraw the complaint, moving it to the terminal `WITHDRAWN`. Withdrawal fires **cascade D**: any linked operator notification still in `DRAFT` closes automatically to `AUTO_CLOSED` with `closed_outcome` `COMPLAINT_WITHDRAWN`, and the affected operators' notification counters are recomputed; a correlated flight's `linked_complaint_count` decrements; and the complainant's counters recompute — the complaint leaves `open_count` or `closed_count` as appropriate and enters `withdrawn_count` — with standing re-evaluated. The complaint list supports `complainant_id`, `status`, `quarter`, `correlated_flight_id`, and `correlated_event_id` filters.

### 3.5. Operator Notification, Response Deadlines and Escalation

An **OperatorNotification** is the formal channel to a carrier. A `NoiseAnalyst` drafts one with the target `operator_id` (which must resolve, else `ERR_OPERATOR_NOT_FOUND`), at least one of `complaint_id` or `noise_event_id` as the subject matter — supplying neither is rejected with `ERR_NOTIFICATION_TARGET_REQUIRED`, and a `noise_event_id` must resolve (else `ERR_EVENT_NOT_FOUND`) — a `severity` of `ADVISORY` or `FORMAL`, a `subject` line, and a `body`. The draft sits in `DRAFT` and counts toward the operator's `notifications_draft`. The notification list supports `operator_id`, `complaint_id`, `noise_event_id`, and `status` filters.

Sending moves `DRAFT` to `SENT`: `sent_at` is stamped, `due_at` is set to exactly ten days after `sent_at` — the response SLA — and the operator's `notifications_sent_total` and `notifications_open` each increment. The `notifications_sent_total` counter is a lifetime count of notifications that reached `SENT` or beyond; a draft that is auto-closed without ever being sent never joins it. From `SENT`, the operator's own representative — an `OperatorRep` whose `X-User-ID` equals the notification operator's `id` — acknowledges the notification, stamping `acknowledged_at` and moving to `ACKNOWLEDGED`. The representative then responds: the `response_text` must be at least twenty characters long (else `ERR_RESPONSE_TOO_SHORT`), and a valid response stamps `responded_at` and moves the notification to `RESPONSE_RECEIVED`. Acting on another operator's notification is rejected with `ERR_NOT_RESOURCE_OWNER`; acting from the wrong state is rejected with `ERR_INVALID_NOTIFICATION_STATE`.

Closure is the analyst's. From `RESPONSE_RECEIVED`, closing requires any linked complaint to be in a terminal state — `CLOSED_SUBSTANTIATED`, `CLOSED_UNSUBSTANTIATED`, or `WITHDRAWN` — else `ERR_LINKED_COMPLAINT_OPEN`; the notification becomes `CLOSED` with `closed_at` stamped and `closed_outcome` recorded as `RESOLVED`. The operator's counters shift (`notifications_open` down, `notifications_closed` up), and when `closed_at` is at or before `due_at` the operator's `on_time_responses_90d` — the count of notifications closed on time within the trailing ninety days — increments.

Escalation is the program's enforcement lever, and it arrives by two paths. A `NoiseOfficeAdmin` may escalate manually at any time while the notification is `SENT` or `ACKNOWLEDGED`, supplying an `escalation_reason`. The system also escalates automatically whenever the notification's `due_at` has passed while it remains `SENT` or `ACKNOWLEDGED` — a sweep evaluated every time the logical clock advances and every time the notification is read. Either path moves the notification to `ESCALATED`, raises its `severity` to `ESCALATION`, records the `escalation_reason`, and fires **cascade C**: the operator's `compliance_standing` is demoted one level (`GOOD` to `WATCH`, `WATCH` to `PROBATION`, while `PROBATION` stays), and an operator landing on `PROBATION` through escalation has its `curfew_grace_minutes` revoked to 0 and its future violation points weighted by the 1.25 standing multiplier. An escalated notification can still close: closing from `ESCALATED` requires either that a response exists — `responded_at` recorded — or that the close carries `closed_outcome` `OVERRIDE`; a linked complaint must again be terminal, and an escalated close earns no on-time credit regardless of timing. `CLOSED` and `AUTO_CLOSED` are terminal. Throughout, the operator's `notifications_open` counts `SENT`, `ACKNOWLEDGED`, `RESPONSE_RECEIVED`, and `ESCALATED`; `notifications_closed` counts `CLOSED` and `AUTO_CLOSED`; and the invariant `notifications_draft` + `notifications_open` + `notifications_closed` equals the total notifications ever created for the operator holds at all times.

### 3.6. Repeat-Complainant Outreach and the Community Annoyance Index

The office manages its most frequent callers through **OutreachCase** records. A case carries the subject `complainant_id`, a `trigger_reason` of `REPEAT_THRESHOLD`, `RESTRICTED_THRESHOLD`, or `MANUAL`, a `contact_attempts` counter starting at zero, and an `opened_at` stamp. Cases arrive in two ways. The system auto-creates one — `OPEN`, with the matching threshold trigger — whenever a complainant's standing crosses into `REPEAT` or `RESTRICTED`, but only when that complainant has no case currently `OPEN`, `CONTACT_ATTEMPTED`, or `ENGAGED`; an existing active case absorbs the threshold event. A `CommunityLiaison` may also open one manually, but only for a complainant whose standing is currently `REPEAT` or `RESTRICTED` — opening a manual case for someone in `GOOD_STANDING` is rejected with `ERR_STANDING_NOT_ELEVATED`.

The liaison then works the case. Logging a contact with `outcome` `NO_ANSWER` moves an `OPEN` case to `CONTACT_ATTEMPTED` and increments `contact_attempts`; the same `NO_ANSWER` outcome on a `CONTACT_ATTEMPTED` case keeps it there, still counting the attempt. Logging `REACHED` moves an `OPEN` or `CONTACT_ATTEMPTED` case to `ENGAGED`, again counting the attempt. From `ENGAGED`, the liaison resolves the case with a `resolution_summary`: the case becomes `RESOLVED` with `resolved_at` stamped, and — the decisive side effect — the complainant's `repeat_baseline_at` is set to that instant. Because `complaints_90d` only counts filings at or after the baseline, resolution shrinks the trailing window immediately, the count is recomputed, and standing is re-evaluated — successful outreach is how a `REPEAT` or `RESTRICTED` complainant earns their way back to `GOOD_STANDING` without waiting ninety days. Alternatively, an `ENGAGED` case may go `DORMANT`, and a `DORMANT` case may be reactivated to `OPEN`. `RESOLVED` is terminal, and any out-of-state transition is rejected with `ERR_INVALID_OUTREACH_STATE`. The case list supports `complainant_id` and `status` filters.

Zone-level temperature is measured by the community annoyance index, a computed read per `zone_code`. Three inputs feed it: the number of distinct complainants in the zone who filed at least one complaint in the trailing thirty days; the count of the zone's complaints that reached `CLOSED_SUBSTANTIATED` with a `closed_at` in the trailing ninety days; and the count of `OPERATED` flights flagged `curfew_violation` whose `actual_at` falls in the trailing ninety days and whose corridor `zone_code` is the zone. The base index is two and a half times the distinct-complainant count, plus four times the square root of the substantiated count, plus one and a half times the violation count, rounded half-up to one decimal place. The tier is keyed on the base alone — below 20 is `LOW`, at least 20 but below 40 is `MODERATE`, and 40 or above is `HIGH` — and the final index adds a tier bonus: nothing for `LOW`, 6 for `MODERATE`, 15 for `HIGH`. The tier is never re-keyed after the bonus: a base of 34.5 is `MODERATE`, and its final index of 40.5 remains `MODERATE` even though it crosses the 40 line. The response carries the `zone_code`, the `base_index`, the `tier`, and the `final_index`.

### 3.7. Part 150 Studies and Land-Use Compatibility

The Part 150 process is represented by the **NoiseStudy** lifecycle. A `StudyCoordinator` creates a study with a `title`, a `baseline_year`, an optional `description`, and optionally a `supersedes_study_id` naming the currently adopted study this one will replace — a reference that must resolve, else `ERR_STUDY_NOT_FOUND`. New studies are `SCOPING`. The coordinator advances the study through `DATA_COLLECTION` (starting data collection), `DRAFTED` (releasing the draft), and `PUBLIC_REVIEW` (opening public comment); from `PUBLIC_REVIEW` the study may return to `DATA_COLLECTION` for another pass — each such request, carrying a `reason`, increments `revision_count` — or proceed to adoption. Adoption is reserved for a `NoiseOfficeAdmin`: it stamps `adopted_at`, and when `supersedes_study_id` is set, the named study must currently be `ADOPTED` (else `ERR_INVALID_STUDY_STATE`) and moves to `SUPERSEDED`, which is terminal. Every out-of-state transition along the way is rejected with `ERR_INVALID_STUDY_STATE`. The study list supports `status` and `supersedes_study_id` filters.

Adoption fires **cascade A**, and its hops are the reason the whole subsection exists. Hop one: every **LandUseParcel** of the adopted study recomputes its exposure under the final variant. Hop two: applications on parcels whose eligibility evaporated are revoked by the system, and every non-withdrawn application on the study's parcels has its `priority_score` recomputed. Hop three: the active fund's `projected_pipeline_cents` is recomputed. The mechanics of hops two and three live in §3.8.

A `StudyCoordinator` adds each parcel beneath its study, so the new parcel's `study_id` points at the owning study, with a `parcel_ref` assessor reference — unique within the owning study — a `land_use` of `RESIDENTIAL`, `SCHOOL`, `HOSPITAL`, `COMMERCIAL`, `INDUSTRIAL`, or `OPEN_SPACE`, a measured level `dnl_db_measured`, a modeled level `dnl_db_modeled` (both at one decimal), and the community `zone_code`. Creation computes the parcel's exposure and increments the study's `parcels_assessed_count`; the same computation re-runs on the coordinator's reassess action (which stamps `reassessed_at`) and under cascade A. The exposure calculation is dual-variant. While the owning study is not yet `ADOPTED`, the `PRELIMINARY` variant applies: `dnl_db_effective` is the modeled level minus a conservative 1.5 dB adjustment, rounded half-up to one decimal. Once the study is `ADOPTED`, the `FINAL` variant applies: `dnl_db_effective` is the measured level taken verbatim. Because the two variants read different inputs, identical parcel data can flip a parcel's eligibility across adoption — which is precisely what drives the cascade. The `dnl_band` is the greatest multiple of five decibels not exceeding the effective level (67.3 dB lands in band 65). Compatibility then follows land use: for `RESIDENTIAL`, `SCHOOL`, and `HOSPITAL` parcels, an effective level of at least 65.0 is `INCOMPATIBLE_RESIDENTIAL`, at least 60.0 but below 65.0 is `COMPATIBLE_WITH_MEASURES`, and below 60.0 is `COMPATIBLE`; for `COMMERCIAL` and `INDUSTRIAL` parcels, at least 75.0 is `INCOMPATIBLE_NONRES` and anything below is `COMPATIBLE`; `OPEN_SPACE` is always `COMPATIBLE`. The `insulation_eligible` flag is `true` exactly when the compatibility status is `INCOMPATIBLE_RESIDENTIAL`, and `compatibility_status`, `dnl_db_effective`, `dnl_band`, and the flag are all system-computed.

### 3.8. The Sound Insulation Grant Program

The grant program pairs a fiscal-year **InsulationFund** with per-property **SoundInsulationApplication** records. A `NoiseOfficeAdmin` creates a fund with a `fiscal_year` label such as FY2026 — unique across all funds, with duplicates rejected as `ERR_DUPLICATE_FISCAL_YEAR_FUND` — a `total_allocation_cents` budget of at least 1, and an intake window from `intake_opens_at` (inclusive) to `intake_closes_at` (exclusive). At most one fund may be `ACTIVE` at a time: creating a second while one is active is rejected with `ERR_ACTIVE_FUND_EXISTS`. A new fund starts `ACTIVE` with `available_cents` equal to the total allocation and `reserved_cents` and `disbursed_cents` at zero. The fund is a ledger: the invariant `available_cents` + `reserved_cents` + `disbursed_cents` = `total_allocation_cents` holds at all times, with reservations and disbursements moving money between the buckets. The fund also forecasts: `projected_pipeline_cents` sums the provisional obligations — each computed on the application's `est_cost_cents` — of every `UNFUNDED` application currently at either eligibility tier, and is recomputed whenever eligibility decisions or study cascades change the pipeline. A `NoiseOfficeAdmin` may close an `ACTIVE` fund, moving it to `CLOSED`, only when `reserved_cents` is exactly zero (else `ERR_FUND_HAS_RESERVED`); operations that require an active fund against a closed one are rejected with `ERR_INVALID_FUND_STATE`.

A `CommunityLiaison` creates an application against a `parcel_id` that must resolve (else `ERR_PARCEL_NOT_FOUND`), optionally naming a known `complainant_id` as the owner or resident, with a `dwelling_type` of `SINGLE_FAMILY`, `MULTI_FAMILY`, or `MOBILE_HOME`, a `rooms_count` of at least 1, and an `est_cost_cents` estimate of at least 1. Two gates guard creation: the parcel's `insulation_eligible` must be `true` (else `ERR_PARCEL_NOT_INCOMPATIBLE`), and no other application for the same parcel may currently sit in `NEW`, `SUBMITTED`, `SCREENING`, `ELIGIBLE_TIER1`, `ELIGIBLE_TIER2`, or `APPEALED` (else `ERR_ACTIVE_APPLICATION_EXISTS`). A new application is `NEW` on its eligibility dimension (`eligibility_status`) and `UNFUNDED` on its funding dimension (`funding_status`) — the two dimensions evolve independently, and the funding machine's guards read the eligibility dimension. `tier_cap_cents` reads 0 before an eligibility decision.

Submitting moves `NEW` to `SUBMITTED`, stamps `submitted_at`, and requires that an `ACTIVE` fund exists whose intake window covers now (else `ERR_SUBMISSION_WINDOW_CLOSED`). A `StudyCoordinator` then begins screening, moving `SUBMITTED` — or, after an appeal, `APPEALED` — to `SCREENING`. Recording a decision carries a `decision` value: `ELIGIBLE_TIER1` requires the parcel's `dnl_db_effective` to be at least 70.0 or its `land_use` to be `SCHOOL` or `HOSPITAL` (else `ERR_TIER_NOT_PERMITTED`); `ELIGIBLE_TIER2` needs no extra gate; `INELIGIBLE` declines the application. Each decision stamps `decided_at` and, for the two eligible tiers, computes the application's `priority_score` and its `tier_cap_cents` — 8,000,000 cents for tier one, 4,000,000 for tier two — and recomputes the fund pipeline. The priority score is an integer sum: a `dnl_band` of at least 75 contributes 80 points, at least 70 but below 75 contributes 60, at least 65 but below 70 contributes 40, and lower bands contribute nothing; `SCHOOL` or `HOSPITAL` land use contributes 20, `RESIDENTIAL` 10, and other uses none; a linked complainant whose `substantiated_count` is at least five contributes 10; and a dwelling with at least eight rooms contributes 5.

An `INELIGIBLE` decision is not final. Within thirty days of `decided_at` (later is `ERR_APPEAL_WINDOW_EXPIRED`) and at most twice per application (a third attempt is `ERR_APPEAL_LIMIT_REACHED`), a `CommunityLiaison` may appeal with a `reason`, moving the application to `APPEALED` and incrementing `appeal_count`; from there, screening begins again. A `CommunityLiaison` may also withdraw the application from any eligibility state, moving it to the terminal `WITHDRAWN`; withdrawal releases any held reservation back to the fund's available bucket and returns the funding dimension to `UNFUNDED`. Every out-of-state transition on either dimension is rejected with `ERR_INVALID_APPLICATION_STATE`. The application list supports `parcel_id`, `complainant_id`, `fund_id`, `eligibility_status`, and `funding_status` filters.

Grant money is obligated through a pinned split, computed in a provisional variant at offer time against `est_cost_cents` and in a final variant at disbursement against `actual_cost_cents`. For a tier-one application, the structure component is the cost basis capped at 8,000,000 cents; for tier two, the covered amount is 80 percent of the cost basis rounded half-up to whole cents, and the structure component is that amount capped at 4,000,000 cents. The contingency component is 10 percent of the structure, rounded half-up to whole cents. The administration component is 5 percent of the structure, rounded half-up to whole cents and capped at 250,000 cents. The rounding order is pinned — each component is rounded to whole cents *first*, and only then are the three summed — so an estimated cost of 1,111,115 cents at tier one obligates exactly 1,277,783 cents (structure 1,111,115, contingency 111,112, administration 55,556), one cent more than a naive sum-then-round would produce.

Issuing an offer directly is a `NoiseOfficeAdmin` action guarded in layers: the funding dimension must be `UNFUNDED` and the eligibility dimension must be `ELIGIBLE_TIER1` or `ELIGIBLE_TIER2` — the cross-dimension guard, both failures surfacing as `ERR_INVALID_APPLICATION_STATE`; the parcel's study must be `ADOPTED` (else `ERR_STUDY_NOT_ADOPTED`); an `ACTIVE` fund must exist (else `ERR_NO_ACTIVE_FUND`); the request must carry `expected_fund_version` per §2.6 (else `ERR_STALE_FUND_VERSION`); and the fund's `available_cents` must cover at least half of the provisional obligation, boundary inclusive (else `ERR_INSUFFICIENT_FUNDS`). The offer is full when the fund covers the entire obligation and partial otherwise, with `offered_amount_cents` set to the smaller of the obligation and the fund's availability. The fund moves that amount from available to reserved — incrementing the fund's `version` — the application records the reserving fund on `fund_id`, stamps `offer_issued_at`, computes `offer_expires_at` as exactly 45 days after issuance, and moves to `OFFER_ISSUED`; the pipeline forecast is recomputed.

Alternatively, a `NoiseOfficeAdmin` may run the waterfall allocation over an `ACTIVE` fund. Candidates are applications at `ELIGIBLE_TIER1` or `ELIGIBLE_TIER2` with funding `UNFUNDED`, visited in descending `priority_score` order, ties broken by earlier `submitted_at` and then by earlier `created_at` — never by identifier. Each candidate's provisional obligation is computed; when the fund's availability covers the whole obligation, a full offer is issued and reserved; when it covers at least half, boundary inclusive, a partial offer equal to the entire remaining availability is issued and reserved; otherwise the candidate is skipped and recorded in the run's `skipped_application_ids`. The run's response reports `offers_issued`, `total_reserved_cents`, and `skipped_application_ids`, and each application it touches increments its own `version`, as does the fund.

The household responds through the liaison. Accepting the offer moves `OFFER_ISSUED` to `GRANT_COMMITTED` and is only valid strictly before `offer_expires_at`; at or after expiry the request is rejected with `ERR_OFFER_EXPIRED`. Determinism here is deliberate: the auto-expire sweep fires first, because offer expiry is evaluated lazily on *read* of the application — never on clock advance — so any read of an application whose `offer_expires_at` has passed moves it from `OFFER_ISSUED` back to `UNFUNDED`, stamps `last_offer_expired_at`, and releases the reservation back to available (bumping the fund's `version`) before the accept attempt is even evaluated. Declining the offer moves it to `OFFER_DECLINED`, releases the reservation in the same manner, and immediately re-queues the application to `UNFUNDED` within the same request, leaving it eligible for a future offer.

Disbursement settles the grant. A `NoiseOfficeAdmin` disburses against a `GRANT_COMMITTED` application with the `actual_cost_cents` incurred, which must be at least 1. The final obligation is computed with the same pinned split on the actual basis; `disbursed_cents` records the final total; the fund moves that amount from reserved to disbursed, and when the final total is smaller than the provisional reservation the surplus flows from reserved back to available. The application becomes `REIMBURSED`, terminal on the funding dimension. One systematic revocation remains: when cascade A flips a parcel's `insulation_eligible` from true to false, any application on that parcel sitting in `SUBMITTED`, `SCREENING`, `ELIGIBLE_TIER1`, or `ELIGIBLE_TIER2` with funding still `UNFUNDED` is moved by the system to `INELIGIBLE` with `decided_at` stamped and its `priority_score` recomputed — applications holding offers or committed grants are never auto-revoked, because their reservations are live money.

### 3.9. Quarterly Reporting and Board Governance

The program reports quarterly to the airport board through the **QuarterlyReport**. A `NoiseAnalyst` creates a report with a `quarter_label` in the `YYYY-Qn` format — unique across all reports, with duplicates rejected as `ERR_DUPLICATE_QUARTER_REPORT` — and optional `notes`. Creation derives the reporting window from the label: `period_start` inclusive and `period_end` exclusive, with Q1 running from January 1 up to April 1, Q2 from April 1 up to July 1, Q3 from July 1 up to October 1, and Q4 from October 1 up to the following January 1. Creation also computes the frozen rollup snapshot: `complaints_received_count` (complaints created in the period, any status), `complaints_substantiated_count` (those reaching `CLOSED_SUBSTANTIATED` with `closed_at` in the period), `distinct_complainants_count` (distinct filers in the period), `events_aircraft_count` (events started in the period now `CLASSIFIED_AIRCRAFT` or `VERIFIED`), `events_community_count` (`CLASSIFIED_COMMUNITY`), `events_mixed_count` (`CLASSIFIED_MIXED`), `curfew_movements_count` and `curfew_violations_count` (`OPERATED` flights with `actual_at` in the period carrying the respective flags), and `avg_operator_compliance_score` (the mean of per-operator curfew compliance scores over operators with at least one `OPERATED` flight in the period, rounded half-up to one decimal, reading 0.0 when there are none). The window is half-open: records falling exactly at `period_end` are excluded. The snapshot is frozen at creation and never recomputed; the creator's `X-User-ID` is stored on `created_by_user_id`.

While the report is `DRAFT`, the analyst may revise its `notes` through the report-editing operation, which carries the `expected_report_version` guard of §2.6 and is rejected in any other state with `ERR_INVALID_REPORT_STATE`. When the quarter has fully closed — `period_end` at or before now, else `ERR_QUARTER_NOT_CLOSED` — and no events with `started_at` in the period remain `CAPTURED` or `SCREENING` (else `ERR_UNCLASSIFIED_EVENTS_REMAIN`), the analyst submits the report for review, moving it to `UNDER_REVIEW`.

A `BoardMember` then acts. Approval moves `UNDER_REVIEW` to `APPROVED` and records the approver on `approved_by_user_id`, but the approver must differ from the report's creator — a segregation-of-duties rule whose violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Alternatively the board member returns the report for revision with a `reason`, moving it back to `DRAFT` and incrementing `revision_round_count`. Publishing is the administrator's act: an `APPROVED` report becomes `PUBLISHED`, stamps `published_at`, and locks the quarter — from that moment, any complaint filing whose `occurred_at` falls inside the published period is rejected with `ERR_REPORT_QUARTER_LOCKED`. `PUBLISHED` is terminal. The report list supports a `status` filter.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; all other successful operations — reads, updates, and lifecycle actions that mutate an existing resource — return `200 OK`. The complete request and response shapes for each endpoint are defined by the workflows of §3; the table below is a navigational summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/noise-program/complainants` | Register a complainant | CommunityLiaison, NoiseOfficeAdmin |
| GET | `/noise-program/complainants` | List complainants | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/complainants/{complainantId}` | Get a complainant (Complainant: self only) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, Complainant |
| PATCH | `/noise-program/complainants/{complainantId}` | Update contact info / opt-in | CommunityLiaison, NoiseOfficeAdmin |
| GET | `/noise-program/complainants/{id}/noise-complaints` | Complaints of a complainant | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, Complainant |
| GET | `/noise-program/complainants/{id}/outreach-cases` | Outreach cases of a complainant | CommunityLiaison, NoiseOfficeAdmin |
| POST | `/noise-program/noise-complaints` | File a complaint (Complainant: own only) | Complainant, CommunityLiaison |
| GET | `/noise-program/noise-complaints` | List complaints with filters | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/noise-complaints/{complaintId}` | Get a complaint (Complainant: owner only) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, Complainant |
| POST | `/noise-program/noise-complaints/{complaintId}/begin-review` | Move RECEIVED to UNDER_REVIEW | NoiseAnalyst |
| POST | `/noise-program/noise-complaints/{complaintId}/request-info` | Move UNDER_REVIEW to AWAITING_COMPLAINANT | NoiseAnalyst |
| POST | `/noise-program/noise-complaints/{complaintId}/provide-info` | Move AWAITING_COMPLAINANT to UNDER_REVIEW | Complainant, CommunityLiaison |
| POST | `/noise-program/noise-complaints/{complaintId}/correlate` | Correlate to flight/event evidence (OCC on complaint version; supersedes prior correlation) | NoiseAnalyst |
| POST | `/noise-program/noise-complaints/{complaintId}/close` | Close SUBSTANTIATED (CORRELATED, confidence at least 60.0) or UNSUBSTANTIATED (UNDER_REVIEW or CORRELATED) | NoiseAnalyst |
| POST | `/noise-program/noise-complaints/{complaintId}/reopen` | Reopen a closed complaint within 30 days, at most 3 times | Complainant, CommunityLiaison |
| POST | `/noise-program/noise-complaints/{complaintId}/resume-review` | Move REOPENED to UNDER_REVIEW | NoiseAnalyst |
| POST | `/noise-program/noise-complaints/{complaintId}/withdraw` | Withdraw from any non-terminal state (cascade D) | Complainant, CommunityLiaison |
| POST | `/noise-program/flight-operations` | Register a scheduled flight | NoiseOfficeAdmin |
| GET | `/noise-program/flight-operations` | List flights (OperatorRep: forced to own operator) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, OperatorRep |
| GET | `/noise-program/flight-operations/{flightId}` | Get a flight (OperatorRep: own operator only) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, OperatorRep |
| PATCH | `/noise-program/flight-operations/{flightId}` | Record outcome: OPERATED (actual_at required), CANCELLED, or DIVERTED; computes curfew flags once | NoiseOfficeAdmin |
| POST | `/noise-program/operators` | Register an operator | NoiseOfficeAdmin |
| GET | `/noise-program/operators` | List operators | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/operators/{operatorId}` | Get an operator (OperatorRep: self only) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, OperatorRep |
| GET | `/noise-program/operators/{id}/operator-notifications` | Notifications of an operator (OperatorRep: own only) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, OperatorRep |
| GET | `/noise-program/operators/{operatorId}/compliance-summary` | Computed curfew compliance for a quarter (OperatorRep: own only) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, OperatorRep |
| POST | `/noise-program/noise-monitors` | Register a monitor | NoiseOfficeAdmin |
| GET | `/noise-program/noise-monitors` | List monitors | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/noise-monitors/{monitorId}` | Get a monitor | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/noise-monitors/{id}/outages` | Record an outage window (half-open; adjacency allowed) | NoiseOfficeAdmin |
| GET | `/noise-program/noise-monitors/{id}/outages` | List outages of a monitor | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/noise-monitors/{monitorId}/decommission` | Decommission an ONLINE monitor | NoiseOfficeAdmin |
| POST | `/noise-program/noise-monitors/{monitorId}/events` | Ingest a noise event | NoiseOfficeAdmin |
| GET | `/noise-program/noise-monitors/{monitorId}/dnl` | Computed DNL for a UTC date from classified events | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/noise-events` | List events with filters | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/noise-events/{eventId}` | Get an event | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/noise-events/{eventId}/begin-screening` | Move CAPTURED to SCREENING | NoiseAnalyst |
| POST | `/noise-program/noise-events/{eventId}/classify` | Classify as AIRCRAFT, COMMUNITY, or MIXED (cascade B) | NoiseAnalyst |
| POST | `/noise-program/noise-events/{eventId}/verify` | Verify a classified event (confidence at least 70.0, uptime at least 80.0) | NoiseAnalyst |
| POST | `/noise-program/noise-events/{eventId}/discard` | Discard a SCREENING event | NoiseAnalyst |
| POST | `/noise-program/noise-events/{eventId}/reclassify` | Return a classified event to SCREENING (max 2) | NoiseAnalyst |
| POST | `/noise-program/curfew-rules` | Create a curfew rule (closed minute windows; touching conflicts) | NoiseOfficeAdmin |
| GET | `/noise-program/curfew-rules` | List curfew rules | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/curfew-rules/{curfewRuleId}` | Get a curfew rule | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/curfew-rules/{curfewRuleId}/suspend` | Suspend an ACTIVE rule | NoiseOfficeAdmin |
| POST | `/noise-program/operator-notifications` | Draft a notification (needs complaint_id or noise_event_id) | NoiseAnalyst |
| GET | `/noise-program/operator-notifications` | List notifications with filters | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/operator-notifications/{notificationId}` | Get a notification (OperatorRep: own operator only) | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember, OperatorRep |
| POST | `/noise-program/operator-notifications/{notificationId}/send` | Send a DRAFT (due_at = sent_at + 10 days) | NoiseAnalyst |
| POST | `/noise-program/operator-notifications/{notificationId}/acknowledge` | Acknowledge a SENT notification (own operator) | OperatorRep |
| POST | `/noise-program/operator-notifications/{notificationId}/respond` | Respond to an ACKNOWLEDGED notification (own operator; at least 20 characters) | OperatorRep |
| POST | `/noise-program/operator-notifications/{notificationId}/close` | Close from RESPONSE_RECEIVED or ESCALATED (linked complaint must be terminal) | NoiseAnalyst |
| POST | `/noise-program/operator-notifications/{notificationId}/escalate` | Escalate a SENT or ACKNOWLEDGED notification (cascade C) | NoiseOfficeAdmin |
| POST | `/noise-program/noise-studies` | Create a Part 150 study | StudyCoordinator |
| GET | `/noise-program/noise-studies` | List studies | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/noise-studies/{studyId}` | Get a study | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/noise-studies/{studyId}/start-data-collection` | Move SCOPING to DATA_COLLECTION | StudyCoordinator |
| POST | `/noise-program/noise-studies/{studyId}/release-draft` | Move DATA_COLLECTION to DRAFTED | StudyCoordinator |
| POST | `/noise-program/noise-studies/{studyId}/open-public-comment` | Move DRAFTED to PUBLIC_REVIEW | StudyCoordinator |
| POST | `/noise-program/noise-studies/{studyId}/request-revision` | Return PUBLIC_REVIEW to DATA_COLLECTION | StudyCoordinator |
| POST | `/noise-program/noise-studies/{studyId}/adopt` | Adopt a PUBLIC_REVIEW study (cascade A; supersedes prior study) | NoiseOfficeAdmin |
| POST | `/noise-program/noise-studies/{id}/parcels` | Add a land-use parcel to a study | StudyCoordinator |
| GET | `/noise-program/noise-studies/{id}/parcels` | List parcels of a study | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/land-use-parcels/{parcelId}` | Get a parcel | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/land-use-parcels/{parcelId}/reassess` | Recompute parcel exposure from current study status | StudyCoordinator |
| POST | `/noise-program/insulation-funds` | Create a fiscal-year fund (unique FY; single ACTIVE) | NoiseOfficeAdmin |
| GET | `/noise-program/insulation-funds` | List funds | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/insulation-funds/{fundId}` | Get a fund | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/insulation-funds/{fundId}/allocate` | Run waterfall allocation over UNFUNDED eligible applications | NoiseOfficeAdmin |
| POST | `/noise-program/insulation-funds/{fundId}/close` | Close an ACTIVE fund (requires zero reserved) | NoiseOfficeAdmin |
| POST | `/noise-program/sound-insulation-applications` | Create an application (parcel must be insulation-eligible; one active per parcel) | CommunityLiaison |
| GET | `/noise-program/sound-insulation-applications` | List applications with filters | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/sound-insulation-applications/{applicationId}` | Get an application | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/submit` | Submit a NEW application (intake window of the ACTIVE fund must cover now) | CommunityLiaison |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/begin-screening` | Move SUBMITTED or APPEALED to SCREENING | StudyCoordinator |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/record-decision` | Record ELIGIBLE_TIER1, ELIGIBLE_TIER2, or INELIGIBLE | StudyCoordinator |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/appeal` | Appeal an INELIGIBLE decision (max 2, within 30 days) | CommunityLiaison |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/issue-offer` | Issue an offer against the ACTIVE fund (OCC on fund version) | NoiseOfficeAdmin |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/accept-offer` | Accept an issued offer before expiry | CommunityLiaison |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/decline-offer` | Decline an issued offer; releases the reservation | CommunityLiaison |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/disburse` | Disburse a committed grant; final split on actual cost | NoiseOfficeAdmin |
| POST | `/noise-program/sound-insulation-applications/{applicationId}/withdraw` | Withdraw from any eligibility state; releases the reservation | CommunityLiaison |
| POST | `/noise-program/outreach-cases` | Open a manual outreach case (standing must be REPEAT or RESTRICTED) | CommunityLiaison |
| GET | `/noise-program/outreach-cases` | List outreach cases | CommunityLiaison, NoiseOfficeAdmin |
| GET | `/noise-program/outreach-cases/{caseId}` | Get an outreach case | CommunityLiaison, NoiseOfficeAdmin |
| POST | `/noise-program/outreach-cases/{caseId}/log-contact` | Log a contact attempt; outcome drives the state | CommunityLiaison |
| POST | `/noise-program/outreach-cases/{caseId}/resolve` | Resolve an ENGAGED case; resets the complainant's repeat baseline | CommunityLiaison |
| POST | `/noise-program/outreach-cases/{caseId}/mark-dormant` | Move ENGAGED to DORMANT | CommunityLiaison |
| POST | `/noise-program/outreach-cases/{caseId}/reactivate` | Move DORMANT back to OPEN | CommunityLiaison |
| POST | `/noise-program/quarterly-reports` | Create a DRAFT report with the frozen quarterly rollup snapshot | NoiseAnalyst |
| GET | `/noise-program/quarterly-reports` | List reports | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| GET | `/noise-program/quarterly-reports/{reportId}` | Get a report | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| PATCH | `/noise-program/quarterly-reports/{reportId}` | Edit notes while DRAFT (OCC expected_report_version) | NoiseAnalyst |
| POST | `/noise-program/quarterly-reports/{reportId}/submit-for-review` | Move DRAFT to UNDER_REVIEW (period closed; no unclassified events) | NoiseAnalyst |
| POST | `/noise-program/quarterly-reports/{reportId}/approve` | Approve an UNDER_REVIEW report (approver differs from creator) | BoardMember |
| POST | `/noise-program/quarterly-reports/{reportId}/return-for-revision` | Return UNDER_REVIEW to DRAFT | BoardMember |
| POST | `/noise-program/quarterly-reports/{reportId}/publish` | Publish an APPROVED report; locks the quarter | NoiseOfficeAdmin |
| GET | `/noise-program/community-zones/{zoneCode}/annoyance-index` | Computed community annoyance index for a zone | NoiseOfficeAdmin, NoiseAnalyst, CommunityLiaison, StudyCoordinator, BoardMember |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving; fires the notification overdue sweep only) | NoiseOfficeAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_COMPLAINANT_NOT_FOUND` | 404 |
| `ERR_FLIGHT_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_OPERATOR_NOT_FOUND` | 404 |
| `ERR_STUDY_NOT_FOUND` | 404 |
| `ERR_INVALID_COMPLAINT_STATE` | 409 |
| `ERR_INVALID_EVENT_STATE` | 409 |
| `ERR_INVALID_NOTIFICATION_STATE` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_STUDY_STATE` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_INVALID_OUTREACH_STATE` | 409 |
| `ERR_INVALID_FLIGHT_STATE` | 409 |
| `ERR_INVALID_FUND_STATE` | 409 |
| `ERR_INVALID_CURFEW_RULE_STATE` | 409 |
| `ERR_MONITOR_NOT_ONLINE` | 409 |
| `ERR_REPORT_QUARTER_LOCKED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_OUTAGE_OVERLAP` | 409 |
| `ERR_CURFEW_WINDOW_OVERLAP` | 409 |
| `ERR_ACTIVE_APPLICATION_EXISTS` | 409 |
| `ERR_DUPLICATE_QUARTER_REPORT` | 409 |
| `ERR_DUPLICATE_FISCAL_YEAR_FUND` | 409 |
| `ERR_ACTIVE_FUND_EXISTS` | 409 |
| `ERR_DUPLICATE_STATION_CODE` | 409 |
| `ERR_DUPLICATE_IATA_CODE` | 409 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_REOPEN_LIMIT_REACHED` | 409 |
| `ERR_RECLASSIFY_LIMIT_REACHED` | 409 |
| `ERR_FUND_HAS_RESERVED` | 409 |
| `ERR_STANDING_NOT_ELEVATED` | 409 |
| `ERR_STUDY_NOT_ADOPTED` | 409 |
| `ERR_LINKED_COMPLAINT_OPEN` | 409 |
| `ERR_UNCLASSIFIED_EVENTS_REMAIN` | 409 |
| `ERR_FLIGHT_NOT_OPERATED` | 409 |
| `ERR_EVENT_NOT_CLASSIFIED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STALE_CORRELATION_VERSION` | 412 |
| `ERR_STALE_FUND_VERSION` | 412 |
| `ERR_EVENT_DURING_OUTAGE` | 422 |
| `ERR_UPTIME_BELOW_FLOOR` | 422 |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 422 |
| `ERR_REOPEN_WINDOW_EXPIRED` | 422 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 |
| `ERR_QUARTER_NOT_CLOSED` | 422 |
| `ERR_CORRELATION_TARGET_REQUIRED` | 422 |
| `ERR_NOTIFICATION_TARGET_REQUIRED` | 422 |
| `ERR_RESPONSE_TOO_SHORT` | 422 |
| `ERR_CONFIDENCE_BELOW_THRESHOLD` | 422 |
| `ERR_CORRELATION_WINDOW_EXCEEDED` | 422 |
| `ERR_TIER_NOT_PERMITTED` | 422 |
| `ERR_PARCEL_NOT_INCOMPATIBLE` | 422 |
| `ERR_NO_ACTIVE_FUND` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 422 |

# Air Ambulance Operations API — Product Requirements Document

## 1. Introduction

An air medical operator running an Air Methods-style program lives inside a hard triangle of constraints: clinical acuity that changes by the minute, aviation weather minimums that cannot be negotiated, and a revenue cycle split between insurer authorization, emergency-transport billing, and a membership program that shields subscribers from balance bills. Every transport is a bed-to-bed commitment — rotor-wing and fixed-wing aircraft, flight nurses and paramedics, ground ambulances at both ends, and receiving-facility beds that must be held, confirmed, and sometimes released mid-flight when a divert is called.

This document specifies the API that coordinates that operation end to end. It governs mission request intake and clinical triage, acceptance and dispatch of an aircraft with a legally rested and credentialed crew, weather assessment and the launch gate, en-route progression with divert and abort handling, ground transport and bed coordination, international repatriation documentation, insurance authorization, provisional and final invoicing with membership write-off protection, and the clinical patient care record with its quality-assurance cascade. All resources are served beneath a single API mount rooted at `/air-ambulance`.

The system is built around segregation of duties. The person who accepts a flight never bills it; the person who writes a clinical record never reviews it; and the dispatcher who launches a mission cannot override the medical director's triage. Readers should keep that separation in mind throughout: many rules below exist precisely so that no single role can push a mission from phone call to paid claim alone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role is checked against the endpoint's authorized role list; a caller whose role is not listed is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles are recognized, spelled exactly as follows: `OpsAdmin`, `Dispatcher`, `MedicalDirector`, `FlightCrew`, `BillingSpecialist`, and `QaReviewer`.

- An `OpsAdmin` is the operations administrator who maintains the base, fleet, and crew registries, manages crew member status, and drives the server's logical clock.
- A `Dispatcher` staffs the communications center: patient registration, mission intake, acceptance logistics, crew rostering on missions, ground and bed coordination, and repatriation paperwork.
- A `MedicalDirector` is the physician responsible for clinical triage, declines, the emergency override, and repatriation document verification.
- A `FlightCrew` caller is a pilot, flight nurse, or flight paramedic acting as a persisted crew member. When `X-User-Role` is `FlightCrew`, `X-User-ID` is the `id` of the acting `CrewMember`; ownership checks on any resource that references a `CrewMember` compare the resource's foreign-key field to `X-User-ID`. Concretely, clinical-record create, submit, and amend require the record's `author_crew_id` to equal `X-User-ID`, and shift create and close require the shift's `crew_member_id` to equal `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN`.
- A `BillingSpecialist` runs the revenue cycle: memberships, insurance authorizations, invoices, payer responses, appeals, and membership write-offs.
- A `QaReviewer` performs clinical quality-assurance review and may never review a record they authored; when a `QaReviewer` caller's `X-User-ID` equals the record's `author_crew_id`, the review is rejected with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403) rather than the generic `ERR_FORBIDDEN`.

For `OpsAdmin`, `Dispatcher`, `MedicalDirector`, `BillingSpecialist`, and `QaReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and any supplied value must be at least 1 and at most 100. The `offset` parameter controls how many items are skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. In addition to the paging pair, each list endpoint accepts resource-matched filter parameters — for example the aircraft list filters by `base_id` and `status`, the mission list by `mission_request_id`, `aircraft_id`, and `status`, the invoice list by `mission_id`, `membership_id`, `claim_status`, and `member_adjustment_status`, and the weather assessment list by `mission_id` and `decision`.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification; and `version`, an integer that increments by exactly one on every mutation of the resource. Any change to a resource — an explicit client write, a computed-field refresh, or a system-driven cascade hop — counts as a mutation and therefore bumps `version` and refreshes `updated_at`.

One resource is deliberately exempt. A `WeatherAssessment` is an immutable observation: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent. Because assessments themselves never mutate, the concurrency protocol for weather filing keys on the parent mission's `version` instead (see §2.6).

All temporal rules in this document — freshness windows, filing deadlines, rolling duty windows, document validity — are evaluated against the server's logical clock, never against wall-clock time. At startup, before any clock-setting call has been made, the logical clock reads 2026-08-01T00:00:00Z; it never silently falls back to wall-clock time thereafter. An `OpsAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`.

### 2.5. Monetary Precision and Scoring Precision

All money in the system is integer cents; no fractional cents exist anywhere. Every charge line on an invoice is rounded half-up to whole cents *before* the lines are summed, and the total is the sum of already-rounded lines. The fuel surcharge is computed from the already-rounded mileage line, and the logistics surcharge is computed from the already-rounded pre-logistics subtotal. Summing unrounded values and rounding once at the end is forbidden: the two orders can differ by a cent, and the pinned per-line order is the only correct one.

Acuity scores are carried to exactly 2 decimal places with round-half-up rounding; the deterioration bonus, when it applies, is added after the weighted sum has been rounded. Weather visibility is compared at one decimal place of statute miles, while ceiling is an integer number of feet. Duty, rest, and shift-duration arithmetic is performed in whole minutes. Quality-assurance deficiency points are integers.

### 2.6. Optimistic Concurrency Control

Two write endpoints — and only these two — require the caller to prove it has observed the current state of the parent entity before writing.

First, filing a weather assessment against a mission requires the request to carry `expected_mission_version`, equal to the mission's current `version` as last observed by the client. Each filed assessment itself mutates the mission (it rewrites `last_weather_decision` and bumps the mission's `version`), so a writer holding a stale observed version must re-read the mission before filing; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Second, amending a quality-flagged clinical record requires the request to carry `expected_patient_care_report_version`, equal to the record's current `version`. A successful amend leaves the record in `AMENDED` and bumps its `version`, so the version arithmetic is the only staleness signal on sequential amends; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above take no version field at all.

### 2.7. Cascading Consistency Across the Operations Graph

The resource graph is flat — children reference parents by foreign key in the request body rather than by nested URL — but state consistency is maintained across that graph by cascades. When a mission diverts, beds held at facilities that no longer match the destination are released, ground legs pointing at those beds are cancelled, and the mission's ground-coordination indicator is recomputed, all as one operation. When a mission aborts or is cancelled, the tail returns to service, the crew is released, and pending ground arrangements are torn down. When a mission completes, the tail is released, the crew's assignments close out, and held beds are consumed. When a quality review flags a record, the author's rolling deficiency tally is recomputed and, past the remediation threshold, the member is pulled from duty and their pending assignments released. Each hop of each cascade independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version` per §2.4; cascades fire automatically when their criteria are met, without any explicit client request on the affected resource.

### 2.8. Resource Addressing and Validation Order

Identifiers arrive either as path variables or as foreign keys in the request body. Every referenced identifier must exist: the system validates existence of path and body identifiers in a logical left-to-right order, and the first missing reference rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any business rule runs.

Across a request's checks, the failure-reporting order is fixed, and a lower-priority-numbered check always masks a higher-numbered one. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization and ownership checks (`ERR_FORBIDDEN`, or `ERR_SELF_REVIEW_FORBIDDEN` on quality review), then identifier existence (`ERR_NOT_FOUND`), then request shape — required fields present, types correct, enum members valid, ranges respected, which covers the clinical subscales within 0 to 10, mile figures greater than zero, cent amounts positive, and a shift's planned end strictly after its planned start — reported as `ERR_VALIDATION` (HTTP 400). Only after those four rung pass does the generic state guard fire: a transition requested from a state that does not support it is rejected with `ERR_INVALID_STATE` (HTTP 409). Endpoint-specific business rules run last, in the orders given with each workflow in §3; where several business checks fail on the same request, the one whose rule is listed earlier in that workflow's stated order is the one reported. Optimistic-concurrency rejection (`ERR_STALE_VERSION`, HTTP 412) sits at the tail of the business-rule ladder, after the domain checks.

### 2.9. Duty-Time Governance: Two Duty Ledgers

Crew fatigue is tracked on two independent ledgers, and they answer different questions. The dispatch legality gate counts duty minutes inside a rolling 24-hour window anchored to the candidate shift's planned end; this rolling figure is the only one that accepts or rejects a shift at planning time. Separately, each crew member carries `duty_minutes_calendar_day`, a compliance reporting view that counts the member's minutes per UTC calendar date — the minutes of their shifts, `OPEN` or `CLOSED`, that fall on the calendar date of the logical now. A shift crossing midnight splits its minutes across two dates, so the same history yields different numbers on the two ledgers: a 20:00–08:00 shift counts 240 minutes against the first date and 480 against the second on the calendar view, but 720 contiguous minutes on the rolling window. Neither figure is derived from the other, and the calendar-day view never gates dispatch.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Operation: Bases, Fleet, and the Duty Roster

Operations begin with geography. An `OpsAdmin` registers each operations base with a `name` and a `region` code (for example `SW-US`). Aircraft are then registered against a home base: the registration payload names the `base_id`, the `tail_number` (the registration number, unique across the entire fleet), the `aircraft_class` — exactly one of `ROTOR_WING` or `FIXED_WING` — and the `medical_config`, which declares the highest clinical capability the tail is outfitted for: `BLS_CAPABLE`, `ALS_CAPABLE`, or `CCT_CAPABLE`, with a strict capability rank in that order (basic life support below advanced life support below critical care transport). A newly registered aircraft enters service as `AVAILABLE`.

An aircraft's `status` moves among `AVAILABLE`, `ASSIGNED`, and `MAINTENANCE`. Only the two ends of that set are under manual control: an `OpsAdmin` may set an `AVAILABLE` tail to `MAINTENANCE` and return a `MAINTENANCE` tail to `AVAILABLE`, and attempting either change while the tail is `ASSIGNED` to a mission is rejected with `ERR_INVALID_STATE` — the `ASSIGNED` state is system-owned, entered when a mission binds the tail and left when the mission resolves (see §3.4 and §3.6). Every manual status change bumps the aircraft's `version`.

Crew onboarding follows the same pattern. An `OpsAdmin` enrolls a crew member with their home `base_id`, `full_name`, and `crew_role` — one of `PILOT`, `NURSE`, or `PARAMEDIC`. A new member starts `ACTIVE`, with `deficiency_points_90d` and `duty_minutes_calendar_day` both at zero. From `ACTIVE`, an `OpsAdmin` may move a member to `INACTIVE` (long-term removal) and back to `ACTIVE`; each of those transitions requires the corresponding from-state and is otherwise rejected with `ERR_INVALID_STATE`. The third state, `REMEDIATION_HOLD`, is reached only through the quality-assurance cascade of §3.9 — never by direct command — and an `OpsAdmin` clears it by returning the member to `ACTIVE`, a transition valid only from `REMEDIATION_HOLD`. Manual status changes bump the member's `version`.

Duty shifts are the unit of fatigue accounting. Planning a shift takes the `crew_member_id`, a `planned_start_iso`, and a `planned_end_iso` that must fall strictly after the start; the system derives `planned_minutes` as the whole-minute length of the interval, and the shift opens in `OPEN` status. Either an `OpsAdmin` or a `FlightCrew` caller may plan a shift, but a `FlightCrew` caller may only plan their own — the shift's `crew_member_id` must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN`. Three fatigue rules guard every new shift, and when several fail at once the duty-projection breach is reported first, then the rest breach, then the overlap breach:

- **Overlap.** If any existing shift of the same member, `OPEN` or `CLOSED`, intersects the candidate window by at least one minute, the create is rejected with `ERR_SHIFT_OVERLAP`. Two windows that merely touch end-to-start are not an overlap; that adjacency is governed by the rest rule below.
- **Rest buffer.** The candidate's planned start must fall at least 600 minutes (ten hours) after the end of the member's most recent prior shift — where "end" means the later of the shift's planned and actual end, considering only shifts ending at or before the candidate's start. A gap of exactly 600 minutes passes; anything less is rejected with `ERR_INSUFFICIENT_REST`.
- **Duty projection.** Consider the rolling window running from 24 hours before the candidate's planned end through that planned end. Sum the minutes of all of the member's shifts, `OPEN` or `CLOSED`, that intersect the window — shifts are processed in ascending planned-start order, ties broken by ascending creation order — and add the candidate's own `planned_minutes`. A projection of 840 minutes (fourteen hours) or less passes; 841 or more is rejected with `ERR_DUTY_LIMIT_EXCEEDED`.

Closing a shift moves it from `OPEN` to `CLOSED`, stamps `actual_end_iso` with the logical now, and bumps the shift's `version`; any other from-state is `ERR_INVALID_STATE`. An `OpsAdmin` may close anyone's shift, while a `FlightCrew` caller may close only their own (same ownership comparison as creation).

### 3.2. From Call Intake to Clinical Acceptance

Before any request can reference a patient, a `Dispatcher` registers them with a `full_name`, a `date_of_birth` in ISO `YYYY-MM-DD` form, and a `weight_kg` that must be greater than zero.

The membership program is the operator's balance-billing shield. A `BillingSpecialist` enrolls a patient by supplying the `patient_id`, a `tier` of `STANDARD` or `FAMILY`, and an `effective_from` date; the subscription is born `ACTIVE`, and it covers transports completed on or after `effective_from`. When a subscriber stops paying, the specialist lapses the subscription: `ACTIVE` to `LAPSED`, which stamps `lapsed_at` with the logical now. Reinstatement — `LAPSED` back to `ACTIVE` — is permitted only within 30 days of the lapse, counted inclusively so that exactly 30 days after `lapsed_at` still passes; a later attempt is rejected with `ERR_REINSTATE_WINDOW_EXPIRED`, and a successful reinstatement clears `lapsed_at` back to null. Termination is final: from either `ACTIVE` or `LAPSED` the subscription moves to `TERMINATED`, its terminal state; any other from-state is `ERR_INVALID_STATE`. Each of these writes bumps the subscription's `version`.

A transport request enters the system when a `Dispatcher` intakes it with the `patient_id`, a `transport_class` of `EMERGENCY_SCENE`, `EMERGENCY_INTERFACILITY`, `SCHEDULED_INTERFACILITY`, or `INTERNATIONAL_REPATRIATION`, the `origin_facility` and requested `destination_facility`, four requester-reported clinical subscales — `reported_cardio`, `reported_resp`, `reported_neuro`, and `reported_interventions`, each an integer from 0 to 10 — and the `onset_iso` timestamp of symptom or event onset. A `destination_country` is required exactly when the class is `INTERNATIONAL_REPATRIATION` and is otherwise optional; its absence on a repatriation request is a shape failure under `ERR_VALIDATION`, as is any subscale outside the 0-to-10 range. Intake computes the request's `triage_acuity_score`: a weighted sum that weights the cardio subscale at 0.30, respiratory at 0.30, neuro at 0.20, and interventions at 0.20, rounded half-up to two decimal places. The request lands in `RECEIVED`.

Clinical triage belongs to the `MedicalDirector`. Acting on a `RECEIVED` request (anything else is `ERR_INVALID_STATE`), the director supplies clinician-verified subscales — `verified_cardio`, `verified_resp`, `verified_neuro`, `verified_interventions` — and may set `emergency_override`, a boolean defaulting to `false` that formally declares an emergency and, downstream, bypasses the payer-authorization launch gate (`ERR_AUTH_REQUIRED`). Triage computes the `acceptance_acuity_score`: the same four-subscale structure but with acceptance weights — cardio 0.25, respiratory 0.35, neuro 0.25, interventions 0.15 — applied to the verified values, the weighted sum rounded half-up to two decimal places, and then, when the interval between the recorded `onset_iso` and the scoring instant is strictly less than 120 minutes (two hours), a deterioration bonus of 2.0 points added on top of the rounded figure. An onset exactly 120 minutes before scoring earns no bonus. The acceptance score fixes the request's `acuity_tier`: a score of at least 7.0 is `CCT`, at least 4.0 but below 7.0 is `ALS`, and anything below 4.0 is `BLS`, with both breaks inclusive. Because the intake and acceptance variants use different weights — and only acceptance adds the bonus — identical patient data yields a different number in `triage_acuity_score` than in `acceptance_acuity_score`; the two fields are both kept. The request advances to `TRIAGED`.

When the clinical picture is incomplete, the director sends the request back: from `TRIAGED` to `PENDING_INFO`, carrying an `info_note` describing what is needed. A `Dispatcher` answers with updated clinicals — `updated_cardio`, `updated_resp`, `updated_neuro`, `updated_interventions` — plus an `info_note`, which returns the request from `PENDING_INFO` to `TRIAGED` and recomputes the acceptance score and tier from the updated values under the same acceptance variant, deterioration bonus included. Decline is available to the `MedicalDirector` from either `TRIAGED` or `PENDING_INFO` (any other state is `ERR_INVALID_STATE`), moves the request to its terminal `DECLINED` state, and records a `reason`.

### 3.3. Dispatch Commitment: Binding Tail and Crew to an Accepted Request

Acceptance converts a triaged request into a flying commitment. A `Dispatcher` accepts a request by naming the `aircraft_id` of the tail to fly it, a `crew` roster whose entries each pair a `crew_member_id` with a `role_in_mission`, the dispatch estimate `estimated_loaded_miles` of patient-loaded miles, which must be greater than zero, the `planned_launch_iso` wheels-up instant, and the `planned_duration_min` flight length, with an optional `alternate_destination` that becomes significant at the launch gate when weather is marginal.

Acceptance enforces its checks in a fixed order, and an early failure masks later ones. The request must currently be `TRIAGED` — anything else is rejected with `ERR_REQUEST_NOT_TRIAGED`. Then the tail's `medical_config` rank must meet or exceed the request's `acuity_tier` rank: a `CCT` request needs a `CCT_CAPABLE` aircraft, an `ALS` request needs `ALS_CAPABLE` or better; a shortfall is `ERR_ACUITY_EXCEEDS_CONFIG`. Next the roster must cover the tier's composition minimum — every tier requires exactly one `PILOT` and one `NURSE`, and `CCT` additionally requires exactly one `PARAMEDIC` — with each role filled by exactly one assignment and no role duplicated; a gap or a duplicate is `ERR_CREW_COMPOSITION_INCOMPLETE`. Each referenced crew member must individually be `ACTIVE`, else `ERR_CREW_UNAVAILABLE`. The aircraft itself must not be in `MAINTENANCE` — `AVAILABLE` or `ASSIGNED` both pass, because a tail may hold multiple non-overlapping future bookings — and a `MAINTENANCE` tail is rejected with `ERR_AIRCRAFT_NOT_AVAILABLE`. Finally, the schedule is checked: the new mission occupies the half-open window starting at `planned_launch_iso` and running for `planned_duration_min` minutes — the end instant itself is not part of the window — and if any other non-terminal mission on the same tail has a window overlapping it, the acceptance is rejected with `ERR_AIRCRAFT_SCHEDULE_CONFLICT`. Windows that touch endpoint-to-startpoint — one ending exactly when the other begins — are expressly allowed. Acceptance performs no fiscal check; for `SCHEDULED_INTERFACILITY` and `INTERNATIONAL_REPATRIATION` requests, payer authorization is validated later, at the launch gate, not here.

A successful acceptance writes several records at once. The request moves `TRIAGED` to `ACCEPTED`. Exactly one `Mission` is created per request, carrying the `mission_request_id` back-reference, born in `PLANNING`, and snapshotting `transport_class`, `acuity_tier`, and `destination_facility` from the request at that moment. The tail transitions `AVAILABLE` to `ASSIGNED` and its `version` bumps. One `CrewAssignment` per roster entry is created in `ASSIGNED` status. Because acceptance requires `TRIAGED`, a second acceptance attempt against an already-accepted request finds the request in `ACCEPTED` and is rejected with `ERR_REQUEST_NOT_TRIAGED` — this is how one-mission-per-request uniqueness is enforced.

The roster can also be adjusted afterward, one entry at a time: a `Dispatcher` adds a member to a mission by supplying `mission_id`, `crew_member_id`, and `role_in_mission`. The mission must still be `PLANNING` (else `ERR_INVALID_STATE`), the member must be `ACTIVE` (else `ERR_CREW_UNAVAILABLE`), and the supplied `role_in_mission` must not duplicate a role already `ASSIGNED` on that mission (else `ERR_CREW_COMPOSITION_INCOMPLETE`). The new assignment is born `ASSIGNED`. Assignment end-states are never set directly: an assignment moves to `RELEASED` or `COMPLETED` only by cascade — mission abort, mission cancel, the remediation cascade of §3.9, or mission completion.

### 3.4. Weather Decision-Making and the Launch Gate

Weather is filed by the people who will fly in it. A `FlightCrew` caller files an assessment against a mission with `mission_id`, the observed `ceiling_ft` (cloud ceiling in feet above ground level, an integer no less than zero), `visibility_sm` in statute miles (no less than zero, compared at one decimal place), the `wind_kt` crosswind component in knots (an integer no less than zero), `precip` as one of `NONE`, `LIGHT`, `HEAVY`, or `ICE`, `day_night` as `DAY` or `NIGHT`, and `terrain` as `FLAT` or `MOUNTAINOUS`. Because filing mutates the mission, the payload must also carry `expected_mission_version` per §2.6. The system stamps `assessed_at` with the logical now, computes the `decision` — `GO`, `MARGINAL`, or `NO_GO` — copies that decision onto the mission's `last_weather_decision`, and increments the mission's `version` by one.

The decision is deterministic. The required ceiling is the base ceiling for the assigned tail's class and the light condition — 500 feet for a rotor-wing by day, 800 for a rotor-wing by night, 800 for a fixed-wing by day, 1,200 for a fixed-wing by night — plus a further 500 feet when the `terrain` is `MOUNTAINOUS`. The required visibility is 1.0 statute mile for a rotor-wing by day, 3.0 for a rotor-wing by night, 2.0 for a fixed-wing by day, and 3.0 for a fixed-wing by night. The maximum crosswind is 25 knots for rotor-wing and 30 knots for fixed-wing. The decision is `NO_GO` when any of the following holds: the `precip` is `ICE`; the crosswind strictly exceeds the maximum; the ceiling is strictly below the required ceiling; or the visibility is strictly below the required visibility. Otherwise the decision is `MARGINAL` when any of the following holds: the `precip` is `HEAVY`; the ceiling is strictly below 1.2 times the required ceiling; the visibility is strictly below the required visibility plus one-half statute mile; or the crosswind strictly exceeds five knots below the maximum. Otherwise the decision is `GO`. The boundaries are pinned: a ceiling exactly equal to the requirement passes, as does visibility exactly equal to the requirement; a ceiling exactly 1.2 times the requirement is `GO`, not `MARGINAL`; and a crosswind exactly equal to the maximum passes, because the violation test is strict.

Assessments go stale. The newest assessment for a mission is the one with the latest `created_at`; ties on `created_at` are broken by server receipt sequence, never by identifier. At launch and at resume-from-hold, the newest assessment must be fresh — the logical now must be no later than `assessed_at` plus 60 minutes, so an assessment exactly one hour old is still fresh — and an older newest-assessment is rejected with `ERR_WEATHER_ASSESSMENT_STALE`.

Launch itself moves the mission from `PLANNING` to `LAUNCHED` and may be invoked by a `Dispatcher` or a `FlightCrew` caller. Its gate evaluates in a fixed order: first the roster check — every `ASSIGNED` assignment must reference a crew member who is still `ACTIVE`, else `ERR_CREW_UNAVAILABLE`; then the weather block — the newest assessment must exist and carry decision `GO` (a `NO_GO` decision, or no assessment at all, is `ERR_BELOW_WEATHER_MINIMUMS`), a `MARGINAL` decision is flyable only when an `alternate_destination` has been filed on the mission (otherwise `ERR_ALTERNATE_REQUIRED`), and staleness is reported as `ERR_WEATHER_ASSESSMENT_STALE`; then aircraft binding — the mission's tail must still be bound to this mission and reading `ASSIGNED`, else `ERR_AIRCRAFT_NOT_AVAILABLE`; then, for `INTERNATIONAL_REPATRIATION` missions, repatriation readiness — the case must be `READY_TO_FLY`, else `ERR_REPATRIATION_NOT_READY`, and at this gate the case's documents are re-validated, so a fit-to-fly statement more than 72 hours old or an expired passport or visa demotes the case back to `COLLECTING` and fails the launch with `ERR_DOC_EXPIRED`; and finally the fiscal gate — for `SCHEDULED_INTERFACILITY` and `INTERNATIONAL_REPATRIATION` missions where the request's `emergency_override` is false, an insurance authorization on this mission in `APPROVED` or `PARTIAL` status must exist, else `ERR_AUTH_REQUIRED`. A clean gate stamps `launched_at` with the logical now.

Weather can also park a mission mid-flight. From `LAUNCHED`, a `Dispatcher` or `FlightCrew` caller may move the mission to `WEATHER_HOLD`, and from `WEATHER_HOLD` back to `LAUNCHED`; the loop may repeat. Resuming consumes a fresh `GO`: the newest assessment must be no more than 60 minutes old and must read `GO` — anything else, including a `MARGINAL` decision, is rejected with `ERR_BELOW_WEATHER_MINIMUMS`. No alternate-destination rescue exists on resume.

### 3.5. Flying the Mission: Progression, Diversion, Abort, and Arrival

Once airborne, a `FlightCrew` caller walks the mission through its flight states by naming each `to_state`: `LAUNCHED` to `AT_PATIENT` when the crew reaches the patient, `AT_PATIENT` to `IN_TRANSIT` once loaded, and `IN_TRANSIT` to `AT_DESTINATION` on arrival; each step requires exactly its from-state, else `ERR_INVALID_STATE`.

A divert re-plans the destination in flight. From `IN_TRANSIT`, a `FlightCrew` caller supplies a `new_destination_facility` and a `reason`, moving the mission to `DIVERTED`; from `DIVERTED`, the normal advance to `AT_DESTINATION` resumes the chain. Divert fires a three-hop cascade: hop one releases every bed reservation on this mission whose `facility_name` does not match the `new_destination_facility` and whose status is `HELD` or `CONFIRMED`, moving each to `RELEASED`; hop two cancels every ground leg whose `bed_reservation_id` points at a bed released in hop one and whose status is `SCHEDULED` or `ENROUTE`, moving each to `CANCELLED`; hop three recomputes the mission's `ground_coordination_status`, which typically becomes `NEEDS_REPLAN` when a destination leg was cancelled without replacement. The mission's `destination_facility` field itself is rewritten to the divert target.

Abort and cancel share one capability keyed by `reason_code`, and their cascades are identical; only the label differs. From `PLANNING`, the mission moves to `CANCELLED`. From any of `LAUNCHED`, `WEATHER_HOLD`, `AT_PATIENT`, or `IN_TRANSIT`, it moves to `ABORTED`. Any other from-state is `ERR_INVALID_STATE`. Either way, the cascade releases the aircraft (subject to the last-booking rule below), moves every `ASSIGNED` crew assignment on the mission to `RELEASED`, cancels every ground leg in `SCHEDULED` or `ENROUTE`, and — as a second hop caused by each cancelled destination leg — releases that leg's linked bed reservation if it is `HELD` or `CONFIRMED`.

An aircraft returns to `AVAILABLE` only when the last non-terminal mission bound to it reaches `COMPLETED`, `ABORTED`, or `CANCELLED`; a tail holding several non-overlapping future bookings stays `ASSIGNED` until its final open mission resolves. That transition bumps the aircraft's `version`.

Arrival paperwork is a completion gate. Moving from `AT_DESTINATION` to `COMPLETED` requires every non-`CANCELLED` ground leg on the mission to be `COMPLETED`; a straggler rejects the completion with `ERR_GROUND_LEGS_PENDING`. Completion stamps `completed_at` with the logical now, releases the aircraft per the rule above, moves all `ASSIGNED` crew assignments to `COMPLETED`, and moves every bed reservation on the mission still in `HELD` or `CONFIRMED` to `CONSUMED`.

### 3.6. Bed-to-Bed: Ground Legs and Receiving-Facility Beds

Air transport is only the middle mile. A `Dispatcher` coordinates each ground ambulance leg against a mission by supplying the `mission_id`, a `leg_type` of `ORIGIN` (scene or sending facility to the aircraft) or `DESTINATION` (arrival airport to the receiving facility), the `provider_name` of the ground EMS agency, and the `scheduled_pickup_iso` instant; `estimated_ground_miles` is optional, and a `DESTINATION` leg may additionally carry a `bed_reservation_id` linking it to the bed it will deliver to. The owning mission must be non-terminal — not `COMPLETED`, `ABORTED`, or `CANCELLED` — and the leg is born `SCHEDULED`. Creating a leg recomputes the mission's ground-coordination indicator.

Each leg walks a simple chain, advanced by a `Dispatcher`: `SCHEDULED` to `ENROUTE` (which again requires the owning mission to be non-terminal, else `ERR_INVALID_STATE`), `ENROUTE` to `AT_BEDSIDE`, and `AT_BEDSIDE` to `COMPLETED`; every step requires its from-state, else `ERR_INVALID_STATE`, and reaching `COMPLETED` recomputes the mission's ground-coordination indicator. A leg may be cancelled from `SCHEDULED` or `ENROUTE` — by the dispatcher directly or by the mission-level cascades of §3.5 — moving it to `CANCELLED`. Cancelling a `DESTINATION` leg that carries a `bed_reservation_id` releases that bed if it is still `HELD` or `CONFIRMED`, and any leg cancellation recomputes the mission's indicator.

A bed reservation holds a receiving-facility bed for the mission. The `Dispatcher` opens one with the `mission_id`, the `facility_name` holding the bed, a `bed_type` of `ICU`, `CCU`, `MED_SURGE`, or `NICU`, and a `hold_until_iso` expiry instant; the mission must be non-terminal, and the reservation is born `HELD`. The dispatcher confirms a hold — `HELD` to `CONFIRMED` — or releases one from either `HELD` or `CONFIRMED` to `RELEASED`; any other from-state is `ERR_INVALID_STATE`, and each of these writes bumps the reservation's `version`. Reservations are also moved by cascade: divert releases the mismatched ones, abort and leg-cancellation release the linked ones, and mission completion consumes the surviving `HELD` or `CONFIRMED` ones into `CONSUMED`. `RELEASED` and `CONSUMED` are terminal.

The mission's `ground_coordination_status` summarizes all of this for the read view, and it is recomputed on every relevant change. It reads `NEEDS_REPLAN` when a `CANCELLED` `DESTINATION` leg exists for which no later-created `DESTINATION` leg remains non-`CANCELLED`. Otherwise it reads `PENDING` when any non-`CANCELLED` leg has not yet reached `COMPLETED`. Otherwise — every surviving leg completed, and no orphaned cancellation — it reads `COORDINATED`.

### 3.7. International Repatriation Documentation

A repatriation adds a paper trail to the flight. A `Dispatcher` opens exactly one documentation case per mission — a second case for the same mission is rejected with `ERR_DUPLICATE_REPATRIATION_CASE` — by supplying the `mission_id`, the `destination_country` of the receiving facility, and the `receiving_facility` itself; the case is born `COLLECTING`.

The case carries a `documents` collection that accumulates entries one at a time. Each append, performed by a `Dispatcher`, records a `doc_type` of `PASSPORT`, `VISA`, `FIT_TO_FLY`, or `CUSTOMS_PRECLEARANCE`, the `document_number`, and an `issued_iso` instant; `expires_iso` is optional, though passports and visas in practice carry one. Every append bumps the case's `version`.

When the folder looks complete, a `MedicalDirector` verifies the case, moving it from `COLLECTING` to `READY_TO_FLY` — any other from-state is `ERR_INVALID_STATE`. Verification runs the validity check before the completeness check, so an expired document surfaces ahead of a missing one. Validity requires every `PASSPORT` and `VISA` entry to have an `expires_iso` strictly later than the logical now, and the `FIT_TO_FLY` entry to have been issued no more than 72 hours before the logical now — exactly 72 hours old still passes; any breach is `ERR_DOC_EXPIRED`. Completeness then requires all four document types to be present among the case's entries; a gap is `ERR_DOCS_INCOMPLETE`.

`READY_TO_FLY` is not a permanent condition. The launch gate of §3.4 re-validates the case's documents at wheels-up time, and if the fit-to-fly statement has aged past 72 hours or a passport or visa has expired since verification, the case is lazily demoted back to `COLLECTING` and the launch fails with `ERR_DOC_EXPIRED`. The cycle from `COLLECTING` to `READY_TO_FLY` and back can repeat as documents expire and are replaced.

### 3.8. The Revenue Cycle: Authorization, Invoicing, and the Membership Waterfall

For scheduled work, the payer conversation starts before wheels-up. A `BillingSpecialist` requests an insurance authorization for a mission with the `mission_id`, the `payer_name`, and the member's `policy_number`; the authorization is born `REQUESTED`. The specialist then records the payer's decision: `REQUESTED` to `APPROVED`; `REQUESTED` to `PARTIAL`, which requires an `approved_amount_cents` that is present and greater than zero (missing or non-positive is `ERR_VALIDATION`); or `REQUESTED` to `DENIED`. A `DENIED` authorization may be pushed to `APPEALED`, and an `APPEALED` one may settle to `APPROVED` or back to `DENIED`. Every decision other than appeal itself requires the authorization to be in `REQUESTED` or `APPEALED`, and appeal requires `DENIED`; any other from-state is `ERR_INVALID_STATE`. Each decision bumps the authorization's `version`. Recall from §3.4 that `APPROVED` and `PARTIAL` are the two states that satisfy the launch gate.

The invoice is created as soon as the mission exists and money can be estimated. A `BillingSpecialist` creates it with nothing but the `mission_id`; exactly one invoice may exist per mission, and a second attempt is rejected with `ERR_DUPLICATE_INVOICE`. Creation computes the provisional quote and stores it in `provisional_total_cents`, snapshots the mission's `estimated_loaded_miles` onto the invoice, and opens the ledger: `claim_status` begins `DRAFT`, `member_adjustment_status` begins `UNEVALUATED`, `membership_id` is null, `insurer_paid_cents`, `contractual_adjustment_cents`, and `member_writeoff_cents` all begin at zero, and `appeal_count` begins at zero.

The charge itself is built in a pinned evaluation order: mileage line, then fuel line, then the pre-logistics subtotal, then the logistics tier keyed on that pre-logistics subtotal, then the logistics line, then the ground line, then the total. In detail: the `base_line_cents` liftoff fee is 1,800,000 cents (an $18,000.00 base) for a `ROTOR_WING` tail and 950,000 cents ($9,500.00) for a `FIXED_WING` tail, keyed on the class of the assigned aircraft. The `mileage_line_cents` is the mile figure multiplied by the per-mile rate — 16,000 cents ($160.00) per loaded mile for rotor-wing, 4,500 cents ($45.00) for fixed-wing — rounded half-up to whole cents. The `fuel_line_cents` is 7% of the already-rounded mileage line, itself rounded half-up to whole cents. The `acuity_line_cents` follows the tier snapshot: 0 for `BLS`, 120,000 cents ($1,200.00) for `ALS`, and 350,000 cents ($3,500.00) for `CCT`. The pre-logistics subtotal is the sum of those four rounded lines. The `logistics_line_cents` is 4% of that subtotal, rounded half-up to whole cents, but only when the subtotal reaches the 2,500,000-cent ($25,000.00) threshold — a subtotal of exactly 2,500,000 cents triggers the surcharge, and the tier test reads the pre-logistics subtotal, never the post-surcharge total, so no circularity arises. The `ground_line_cents` is a flat 45,000 cents ($450.00) per included ground leg. The total is subtotal plus logistics line plus ground line.

Two variants of the mile figure and the ground-leg count pin the quote to what is known at each moment. The provisional quote, computed at creation while actuals are unknown, takes the mission's `estimated_loaded_miles`, multiplies it by a 1.15 pad factor, and rounds up to the next whole mile; it counts every ground leg in `SCHEDULED`, `ENROUTE`, `AT_BEDSIDE`, or `COMPLETED`. The final settlement, computed at finalize, takes `actual_loaded_miles` exactly as entered from the flight log — no pad factor, and fractional miles are allowed — and counts only `COMPLETED` ground legs.

The rounding order is not a nicety. Consider a rotor-wing mission finalized with `actual_loaded_miles` of 16.6666 and no acuity or logistics exposure: the pinned order rounds the mileage line to 266,666 cents, derives the fuel line as 18,667 cents from that rounded figure, and totals 2,085,333 cents with the base line; summing the unrounded products and rounding once at the end yields 2,085,332 cents and is forbidden. Per §2.5, every line rounds half-up to whole cents before any summation.

Finalize is the pivot from estimate to settlement, performed by a `BillingSpecialist` who enters the flight-log `actual_loaded_miles`. The invoice must be `DRAFT` (else `ERR_INVALID_STATE`) and the owning mission must be `COMPLETED` (else `ERR_MISSION_NOT_COMPLETED`). Finalize recomputes every line and stores the settlement in `final_total_cents`, moves `claim_status` to `FINALIZED`, and evaluates the member dimension for the first and only time: if a membership subscription exists for the mission's patient with status `ACTIVE` and an `effective_from` on or before the date of the mission's `completed_at`, the invoice is `MEMBER_PROTECTED` and `membership_id` is bound to that subscription; otherwise it is `NON_MEMBER`.

Submitting the claim moves `FINALIZED` to `SUBMITTED` — or, after an appeal, `APPEALED` to `RESUBMITTED`; from any other claim state it is `ERR_INVALID_STATE`. Two gates guard submission, checked in this order so a clinical-record gap surfaces before a deadline one: the mission's patient care report must be `QA_APPROVED`, else `ERR_PCR_NOT_APPROVED`; and the submission date must fall no later than 90 days after the mission's completion date, counted inclusively so that exactly 90 days still files, else `ERR_TIMELY_FILING_EXPIRED`.

The payer's adjudication arrives as a payer response carrying an `outcome` of `PAID`, `PARTIALLY_PAID`, or `DENIED`, plus `paid_cents` and `contractual_adjustment_cents`. It is accepted only from `SUBMITTED` or `RESUBMITTED` (else `ERR_INVALID_STATE`), and the posting must respect the ledger guard: `paid_cents` plus `contractual_adjustment_cents` must not exceed `final_total_cents`, else `ERR_LEDGER_IMBALANCE`. A clean posting applies the waterfall: `insurer_paid_cents` is set to `paid_cents`, `contractual_adjustment_cents` is set to the posted adjustment, and `patient_responsibility_cents` is recomputed as `final_total_cents` minus insurer paid, minus contractual adjustment, minus member write-off. The `claim_status` becomes `PAID`, `PARTIALLY_PAID`, or `DENIED` to match the outcome. On a `PAID` or `PARTIALLY_PAID` response posted while the member dimension reads `NON_MEMBER`, the dimension moves to `BALANCE_BILLED`; a `DENIED` response applies the waterfall but leaves the member dimension unchanged.

A denial can be appealed, at most twice. The appeal requires `claim_status` of `DENIED` (else `ERR_INVALID_STATE`) and an `appeal_count` below 2 — the cap means at most two appeals per invoice, and an attempt beyond the cap is `ERR_APPEAL_LIMIT`. Appealing increments `appeal_count` by one and, as compensation for the denied posting, resets `insurer_paid_cents` and `contractual_adjustment_cents` to zero so the ledger invariant survives the reversal; `member_writeoff_cents` is expressly not reset, since a write-off requires a claim response to exist against. The claim moves to `APPEALED`, from which resubmission produces `RESUBMITTED` and the payer-response cycle repeats.

Balance-billing protection is the program's payoff. While the member dimension reads `MEMBER_PROTECTED` and the claim has seen a payer response — `claim_status` of `PAID`, `PARTIALLY_PAID`, or `DENIED`; anything else is `ERR_INVALID_STATE` — a `BillingSpecialist` may post the member write-off. If the dimension is anything other than `MEMBER_PROTECTED` — the patient was a non-member, the membership had lapsed, or its `effective_from` fell after the completion date — the attempt is `ERR_MEMBERSHIP_NOT_ELIGIBLE`. The write-off moves the entire residual: `member_writeoff_cents` is set to the current `patient_responsibility_cents`, `patient_responsibility_cents` becomes zero, and the dimension advances to `WRITEOFF_POSTED`. After every posting, appeal, and write-off, one conserved invariant holds: insurer paid plus contractual adjustment plus member write-off plus patient responsibility always equals `final_total_cents`.

### 3.9. The Clinical Record and Quality Assurance

Every mission produces exactly one patient care report, authored by the crew who flew it. A `FlightCrew` caller opens the record with the `mission_id`, an `author_crew_id` that must equal the caller's `X-User-ID` (else `ERR_FORBIDDEN`), and three narratives: `vitals_summary`, `interventions_summary`, and `meds_summary`. A second record for the same mission is rejected with `ERR_DUPLICATE_PCR`. The record is born `DRAFT`, with `last_review_points` at zero.

Submission sends the record to quality review. The author — and only the author, again by the `X-User-ID` ownership comparison — submits from `DRAFT` or `AMENDED`; any other state is `ERR_INVALID_STATE`. Two gates guard submission, evaluated in this order: the owning mission must be `COMPLETED`, else `ERR_MISSION_NOT_COMPLETED`; and the logical now must fall no later than 24 hours after the mission's `completed_at`, counted inclusively so that exactly 24 hours still submits, else `ERR_PCR_WINDOW_EXPIRED`. A clean submit stamps `submitted_at` with the logical now and moves the record to `SUBMITTED`.

A `QaReviewer` adjudicates a `SUBMITTED` record — any other state is `ERR_INVALID_STATE` — with an `outcome` of `APPROVED` or `FLAGGED` and an integer `deficiency_points`. Segregation of duties is absolute: the reviewer's `X-User-ID` must differ from the record's `author_crew_id`, else `ERR_SELF_REVIEW_FORBIDDEN`. An approval moves the record to `QA_APPROVED`, its terminal state, and sets `last_review_points` from the submitted `deficiency_points`, which is expected to be zero.

A flag is heavier. The record moves to `QA_FLAGGED`, `last_review_points` records the assessed `deficiency_points`, and a three-hop cascade fires. Hop one adds the points to the author's rolling tally: `deficiency_points_90d` is the sum of `deficiency_points` across every flagged review of this author's records whose review instant falls inside the rolling 90-day window ending at the logical now, reviews processed in ascending creation order. Hop two flips the member from `ACTIVE` to `REMEDIATION_HOLD` the moment that tally reaches 15 points — exactly 15 triggers the hold. Hop three, caused by the hold itself, releases every `ASSIGNED` crew assignment that member holds on missions still in `PLANNING`, moving each to `RELEASED`.

The author answers a flag by amending. From `QA_FLAGGED` — or from `AMENDED`, for further edits before resubmission — the author posts the amendment carrying `expected_patient_care_report_version` per the concurrency rule of §2.6, plus any revised `vitals_summary`, `interventions_summary`, or `meds_summary`. A version mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412); on the `AMENDED` self-loop in particular, the state guard passes and the version guard is what fires. A successful amend increments the record's `version` by one and lands it in `AMENDED`, from which resubmission re-enters the cycle. The loop from `SUBMITTED` to `QA_FLAGGED` to `AMENDED` and back to `SUBMITTED` may repeat until the record is approved.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or modify an existing resource — including the action endpoints that drive state transitions — return `200 OK`. The narratives of §3 define each operation's request payload, preconditions, and side effects; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/air-ambulance/bases` | Create an operations base | OpsAdmin |
| GET | `/air-ambulance/bases/{id}` | Read a base | All roles |
| POST | `/air-ambulance/aircraft` | Register an aircraft at a base | OpsAdmin |
| GET | `/air-ambulance/aircraft/{id}` | Read an aircraft | All roles |
| GET | `/air-ambulance/aircraft` | List aircraft with filters and pagination | All roles |
| PUT | `/air-ambulance/aircraft/{id}` | Set aircraft status between MAINTENANCE and AVAILABLE (ASSIGNED is system-owned) | OpsAdmin |
| POST | `/air-ambulance/crew-members` | Onboard a crew member | OpsAdmin |
| GET | `/air-ambulance/crew-members/{id}` | Read a crew member | All roles |
| GET | `/air-ambulance/crew-members` | List crew members with filters and pagination | All roles |
| PUT | `/air-ambulance/crew-members/{id}` | Set crew member status (clear REMEDIATION_HOLD to ACTIVE; ACTIVE to and from INACTIVE) | OpsAdmin |
| POST | `/air-ambulance/crew-shifts` | Plan a duty shift; runs the overlap, rest, and duty-projection checks | OpsAdmin, FlightCrew |
| GET | `/air-ambulance/crew-shifts/{id}` | Read a crew shift | All roles |
| GET | `/air-ambulance/crew-shifts` | List crew shifts with filters and pagination | All roles |
| PUT | `/air-ambulance/crew-shifts/{id}` | Close an open shift; stamps actual end | OpsAdmin, FlightCrew |
| POST | `/air-ambulance/patients` | Register a patient | Dispatcher |
| GET | `/air-ambulance/patients/{id}` | Read a patient | All roles |
| POST | `/air-ambulance/memberships` | Enroll a patient in the membership program | BillingSpecialist |
| GET | `/air-ambulance/memberships/{id}` | Read a membership | All roles |
| GET | `/air-ambulance/memberships` | List memberships with filters and pagination | All roles |
| PUT | `/air-ambulance/memberships/{id}` | Lapse, reinstate, or terminate a membership | BillingSpecialist |
| POST | `/air-ambulance/mission-requests` | Intake a transport request; computes the intake acuity score | Dispatcher |
| GET | `/air-ambulance/mission-requests/{id}` | Read a mission request | All roles |
| GET | `/air-ambulance/mission-requests` | List mission requests with filters and pagination | All roles |
| POST | `/air-ambulance/mission-requests/{id}/triage` | Clinical triage; computes the acceptance score and acuity tier | MedicalDirector |
| POST | `/air-ambulance/mission-requests/{id}/request-info` | Send the request back for more information | MedicalDirector |
| POST | `/air-ambulance/mission-requests/{id}/provide-info` | Supply updated clinicals; recomputes the acceptance score | Dispatcher |
| POST | `/air-ambulance/mission-requests/{id}/accept` | Accept a triaged request: creates the mission and binds aircraft and crew | Dispatcher |
| POST | `/air-ambulance/mission-requests/{id}/decline` | Decline a request on clinical grounds | MedicalDirector |
| GET | `/air-ambulance/missions/{id}` | Read a mission, including its computed ground-coordination status | All roles |
| GET | `/air-ambulance/missions` | List missions with filters and pagination | All roles |
| POST | `/air-ambulance/missions/{id}/advance` | Advance the flight state per the mission gates (launch, hold, resume, patient, transit, arrival, completion) | Dispatcher, FlightCrew |
| POST | `/air-ambulance/missions/{id}/abort` | Abort post-launch or cancel while planning; fires the release cascades | Dispatcher, FlightCrew |
| POST | `/air-ambulance/missions/{id}/divert` | Divert to an alternate facility; fires the bed and ground-leg cascades | FlightCrew |
| POST | `/air-ambulance/weather-assessments` | File a weather assessment for a mission; computes the GO/MARGINAL/NO_GO decision | FlightCrew |
| GET | `/air-ambulance/weather-assessments/{id}` | Read a weather assessment | All roles |
| GET | `/air-ambulance/weather-assessments` | List weather assessments with filters and pagination | All roles |
| POST | `/air-ambulance/crew-assignments` | Add a crew member to a planning mission | Dispatcher |
| GET | `/air-ambulance/crew-assignments/{id}` | Read a crew assignment | All roles |
| GET | `/air-ambulance/crew-assignments` | List crew assignments with filters and pagination | All roles |
| POST | `/air-ambulance/ground-legs` | Coordinate a ground ambulance leg for a mission | Dispatcher |
| GET | `/air-ambulance/ground-legs/{id}` | Read a ground leg | All roles |
| GET | `/air-ambulance/ground-legs` | List ground legs with filters and pagination | All roles |
| PUT | `/air-ambulance/ground-legs/{id}` | Advance or cancel a ground leg | Dispatcher |
| POST | `/air-ambulance/bed-reservations` | Hold a receiving-facility bed for a mission | Dispatcher |
| GET | `/air-ambulance/bed-reservations/{id}` | Read a bed reservation | All roles |
| GET | `/air-ambulance/bed-reservations` | List bed reservations with filters and pagination | All roles |
| PUT | `/air-ambulance/bed-reservations/{id}` | Confirm or release a bed hold | Dispatcher |
| POST | `/air-ambulance/insurance-authorizations` | Request payer authorization for a mission | BillingSpecialist |
| GET | `/air-ambulance/insurance-authorizations/{id}` | Read an authorization | All roles |
| GET | `/air-ambulance/insurance-authorizations` | List authorizations with filters and pagination | All roles |
| PUT | `/air-ambulance/insurance-authorizations/{id}` | Decide or appeal an authorization | BillingSpecialist |
| POST | `/air-ambulance/invoices` | Create the mission invoice; computes the provisional totals | BillingSpecialist |
| GET | `/air-ambulance/invoices/{id}` | Read an invoice with all lines, totals, and ledger fields | All roles |
| GET | `/air-ambulance/invoices` | List invoices with filters and pagination | All roles |
| POST | `/air-ambulance/invoices/{id}/finalize` | Enter actual loaded miles; computes final totals and evaluates the member dimension | BillingSpecialist |
| POST | `/air-ambulance/invoices/{id}/submit` | Submit the claim to the payer; also resubmits an appealed claim | BillingSpecialist |
| POST | `/air-ambulance/invoices/{id}/payer-response` | Post payer adjudication; applies the ledger waterfall | BillingSpecialist |
| POST | `/air-ambulance/invoices/{id}/appeal` | Appeal a denial; capped at two; zeroes the paid and adjustment postings | BillingSpecialist |
| POST | `/air-ambulance/invoices/{id}/member-writeoff` | Apply membership balance-billing protection to the residual | BillingSpecialist |
| POST | `/air-ambulance/repatriation-cases` | Open a repatriation documentation case for a mission | Dispatcher |
| GET | `/air-ambulance/repatriation-cases/{id}` | Read a repatriation case | All roles |
| GET | `/air-ambulance/repatriation-cases` | List repatriation cases with filters and pagination | All roles |
| POST | `/air-ambulance/repatriation-cases/{id}/documents` | Append a travel or clinical document to the case | Dispatcher |
| POST | `/air-ambulance/repatriation-cases/{id}/verify` | Verify document completeness and validity | MedicalDirector |
| POST | `/air-ambulance/patient-care-reports` | Author the mission's clinical record | FlightCrew |
| GET | `/air-ambulance/patient-care-reports/{id}` | Read a clinical record | All roles |
| GET | `/air-ambulance/patient-care-reports` | List clinical records with filters and pagination | All roles |
| POST | `/air-ambulance/patient-care-reports/{id}/submit` | Submit the record for quality assurance | FlightCrew |
| POST | `/air-ambulance/patient-care-reports/{id}/qa-review` | QA adjudication with deficiency points; segregation of duties enforced | QaReviewer |
| POST | `/air-ambulance/patient-care-reports/{id}/amend` | Amend a quality-flagged record under optimistic concurrency | FlightCrew |
| POST | `/air-ambulance/_clock/set_current_utc` | Set the server's logical clock (test-driving capability) | OpsAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SELF_REVIEW_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_REQUEST_NOT_TRIAGED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ACUITY_EXCEEDS_CONFIG` | 422 Unprocessable Entity |
| `ERR_CREW_COMPOSITION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_CREW_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_DUTY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_REST` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_BELOW_WEATHER_MINIMUMS` | 422 Unprocessable Entity |
| `ERR_ALTERNATE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_WEATHER_ASSESSMENT_STALE` | 422 Unprocessable Entity |
| `ERR_AIRCRAFT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_AIRCRAFT_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_AUTH_REQUIRED` | 422 Unprocessable Entity |
| `ERR_REPATRIATION_NOT_READY` | 422 Unprocessable Entity |
| `ERR_MISSION_NOT_COMPLETED` | 409 Conflict |
| `ERR_PCR_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_PCR_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_TIMELY_FILING_EXPIRED` | 422 Unprocessable Entity |
| `ERR_LEDGER_IMBALANCE` | 422 Unprocessable Entity |
| `ERR_APPEAL_LIMIT` | 422 Unprocessable Entity |
| `ERR_MEMBERSHIP_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_REINSTATE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DOCS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DOC_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_INVOICE` | 409 Conflict |
| `ERR_DUPLICATE_REPATRIATION_CASE` | 409 Conflict |
| `ERR_DUPLICATE_PCR` | 409 Conflict |
| `ERR_GROUND_LEGS_PENDING` | 409 Conflict |

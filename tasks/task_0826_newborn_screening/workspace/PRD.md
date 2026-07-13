# Newborn Screening API — Product Requirements Document

## 1. Introduction

State newborn screening programs shoulder a time-critical public-health mandate: every infant born within the jurisdiction must have a dried-blood-spot specimen collected, transported to the state laboratory, tested across a panel of conditions, and — where a result is abnormal — followed to a confirmed diagnosis or a documented normal. This API is the system of record that orchestrates that end-to-end journey. It coordinates four operational domains that historically live in separate silos: the birthing facility that collects specimens and performs point-of-care screening, the state laboratory that receives cards and reports metabolic results, the follow-up program that chases abnormal results into confirmatory diagnosis, and the specialty clinics that render those confirmations.

The program's core obligations are timeliness and completeness. A specimen collected too early or transported too slowly is scientifically unreliable and must be recollected; a flagged result that is never followed up is a missed diagnosis. Accordingly, the system treats timeliness as a first-class, measured quantity, enforces acceptability rules at the moment a card is received, and mechanically opens and tracks follow-up cases the instant a screen is flagged. Because the same infant record is touched concurrently by facility staff, laboratory technicians, and follow-up coordinators, the system also protects against lost updates through optimistic concurrency control on the infant aggregate.

This document specifies the API's global contracts (Section 2), the business logic and workflows that make up the screening lifecycle (Section 3), the complete endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply across every endpoint. All resources are mounted under the `/nbs` path prefix, with the sole exception of the logical-clock control endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles: `BirthFacilityUser`, `LabTechnician`, `FollowUpCoordinator`, `SpecialtyClinician`, and `ProgramAdmin`.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is an actual persisted resource identifier that drives ownership checks:

- When `X-User-Role` is `BirthFacilityUser`, `X-User-ID` is the `id` of the acting `Facility`; ownership checks on any resource that references a facility compare that facility linkage to `X-User-ID`. Concretely, a birth-facility user may register an infant only when the supplied `facility_id` equals `X-User-ID`, and may act on a specimen, consent record, or point-of-care screen only when the owning infant's registering facility equals `X-User-ID`. A mismatch is rejected with `ERR_NOT_OWNER`.
- When `X-User-Role` is `SpecialtyClinician`, `X-User-ID` is the `id` of the acting `SpecialtyClinic`; completing a confirmatory appointment is permitted only when that appointment's `specialty_clinic_id` equals `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER`.

The remaining three roles are **opaque**: when `X-User-Role` is `LabTechnician`, `FollowUpCoordinator`, or `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any resource's `id`; these roles are authorized purely by role membership per the endpoint table in Section 4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

List endpoints also accept domain filters that narrow the result set. Infants may be filtered by `facility_id` and `consent_status`; specimens by `infant_id`, `status`, and `specimen_type`; screens by `specimen_id`; follow-up cases by `infant_id`, `screen_id`, and `status`; referrals by `follow_up_case_id`, `specialty_clinic_id`, and `status`; and assay runs by `facility_id`, `instrument_code`, and `status`. These filters are the intended mechanism for reverse-lookup discovery of a foreign-key relationship (for example, finding every specimen belonging to an infant).

### 2.4. Common Resource Properties and Versioning

Every resource in this system — `Facility`, `Infant`, `Specimen`, `Screen`, `RecollectionOrder`, `FollowUpCase`, `SpecialtyClinic`, `Referral`, `ConfirmatoryAppointment`, and `AssayRun` — carries a common set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation to the resource.
- `version` — an integer that begins at its initial value on creation and increments by one on every mutation. It is the basis for optimistic concurrency control (see Section 2.8).

Whenever the server mutates a resource — including changes to derived or computed fields such as an infant's `open_case_count` or a facility's `total_booked_minutes` — that mutation refreshes `updated_at` and increments `version` on the mutated resource.

### 2.5. The Logical Clock

All temporal calculations in this system are anchored to a **logical clock** rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly advanced it holds that instant and never falls back to real time. A `ProgramAdmin` advances it by supplying a `to_iso8601` instant; the response echoes the new clock as `current_utc`. The logical clock is the source of truth for the `reported_datetime` stamped at metabolic reporting, for the `deadline_datetime` recorded on a recollection order, for the `opened_at_clock` captured when a follow-up case opens, and for every repeat-window and recollection-window deadline comparison.

### 2.6. Nested Resource Retrieval and Existence Ordering

When a request references resources — whether by path variable or by body foreign key — the server validates their existence strictly left to right, and returns the not-found error for the *first* referenced resource that does not exist before considering any later reference or any business rule. Each resource kind has its own not-found error: a missing infant yields `ERR_INFANT_NOT_FOUND`, a missing facility `ERR_FACILITY_NOT_FOUND`, a missing specimen `ERR_SPECIMEN_NOT_FOUND`, a missing screen `ERR_SCREEN_NOT_FOUND`, a missing follow-up case `ERR_FOLLOWUP_CASE_NOT_FOUND`, a missing referral `ERR_REFERRAL_NOT_FOUND`, a missing specialty clinic `ERR_SPECIALTY_CLINIC_NOT_FOUND`, a missing confirmatory appointment `ERR_APPOINTMENT_NOT_FOUND`, and a missing assay run `ERR_ASSAY_RUN_NOT_FOUND`. Two retrieval paths take the sub-resource form: the recollection orders of a specimen, and the confirmatory appointments of a referral; both validate the parent's existence before listing children.

### 2.7. Cascade Consistency and Conserved Counters

Several counters on the `Infant` and `Facility` records are **conserved quantities** — the server maintains them as exact running totals, never as ad-hoc estimates, and mutates them only through the cascades described in Section 3.

- An infant's `open_recollection_count` is the number of that infant's recollection orders currently in `ORDERED` state. It is incremented when an unsatisfactory specimen spawns a recollection order and decremented when that order is collected or cancelled.
- An infant's `open_case_count` is the number of that infant's follow-up cases whose `status` is neither `RESOLVED_NORMAL` nor `CLOSED`. It is incremented when a case opens and decremented when a case resolves or closes.
- An infant's `followup_status` is derived directly from that count: it reads `ACTIVE` while `open_case_count` is greater than zero and `CLEAR` otherwise.
- A facility's `total_booked_minutes` is the sum of `duration_minutes` across that facility's assay runs whose `status` is not `CANCELLED`, recomputed on every assay-run creation and cancellation.

When one operation must mutate more than one resource, every affected resource is mutated (each refreshing its own `updated_at` and `version`). Because these cascades change the infant's `version`, they interact with optimistic concurrency control as described next.

### 2.8. Optimistic Concurrency Control on the Infant Aggregate

Logging a specimen is an optimistic-concurrency-protected write against the parent `Infant`. A request to create a specimen must carry `expected_infant_version` as a mandatory field holding the `version` of the infant the client last observed. If that value does not equal the infant's current `version`, the create is rejected with `ERR_STALE_INFANT_VERSION` (HTTP 412), because the client is acting on a stale view of the infant. This matters precisely because a repeat card legitimately supersedes the prior `current_specimen_id` pointer: under natural product semantics a second create would succeed, so the only reason to reject it is that the caller's view is stale. Cascades that touch the infant — a change to `open_recollection_count`, a change to `open_case_count`, or a consent change — each advance the infant's `version` between the caller's read and this write, making a mismatched `expected_infant_version` the deterministic signal that the caller must re-read before writing. No other endpoint takes a version field.

### 2.9. Timeliness Measurement, Precision, and Rounding

Timeliness is computed from durations expressed in hours. A specimen's `collection_age_hours` is the elapsed time from the infant's `birth_datetime` to the specimen's `collection_datetime`, expressed in hours and rounded half-up to two decimal places. Its `transit_time_hours` is the elapsed time from `collection_datetime` to `received_datetime`, likewise in hours to two decimals; it is null until the specimen is received. All hour-valued durations use round-half-up to two decimals.

The follow-up priority score is an integer quantity computed from integer weights and is never rounded. The program timeliness rate is expressed as a percentage to one decimal place using round-half-up, with a specific rounding order defined in Section 3.9. Pulse-oximetry values and blood-spot counts are integers. Enum-valued classifications (acceptability, timeliness class, dispositions, and all lifecycle states) are exact strings.

### 2.10. Validation Ordering and Error Precedence

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned error is deterministic:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may call this endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Ownership** — for entity-backed roles, the acting `X-User-ID` owns the target, else `ERR_NOT_OWNER` (403).
4. **Existence** — every path- and body-referenced resource exists, validated left to right, else the corresponding not-found error (404).
5. **Request shape** — required body fields are present and correctly typed, else `ERR_INVALID_REQUEST` (400); enum-valued body fields hold a declared member, else `ERR_INVALID_ENUM` (422).
6. **State** — the target is in a state that permits the transition, else `ERR_INVALID_STATE` (409); a target already in a terminal state yields `ERR_ALREADY_TERMINAL` (409); specific state guards such as `ERR_SPECIMEN_NOT_SATISFACTORY` and `ERR_REFERRAL_NOT_SCHEDULED` apply here.
7. **Consent safety** — an operation on an infant whose consent is refused is blocked with `ERR_CONSENT_REFUSED` (409).
8. **Referential business rules** — clinic-specialty match, appointment-completion, and referral-resolution prerequisites.
9. **Duplication guards** — duplicate pending repeat and duplicate open referral.
10. **Temporal rules** — chronology and window deadlines.
11. **Capacity rules** — clinic aggregate capacity and instrument exclusivity.
12. **Optimistic concurrency** — `expected_infant_version` match, evaluated last, yielding `ERR_STALE_INFANT_VERSION` (412).

A representative consequence: on a specimen create, authentication precedes authorization, which precedes the ownership check, which precedes the infant-existence check, which precedes body-shape validation, which precedes the consent-refused guard, which precedes the collection-before-birth chronology check, which precedes the stale-version check. The earliest failing gate is the one reported.

## 3. Business Logic & Workflows

### 3.1. Program Setup: Facilities and Specialty Clinics

The program's static topology is established by a `ProgramAdmin`. Registering a `Facility` supplies its `name`, its `facility_type` — one of `HOSPITAL`, `BIRTHING_CENTER`, or `LAB` — and its `state_region`, the two-letter code under which the facility reports and by which the program timeliness summary groups results. A newly registered facility starts with `total_booked_minutes` at zero. Facility records are readable by lab technicians and program administrators; the facility read deliberately exposes `total_booked_minutes` so that the assay-scheduling invariant can be inspected.

Registering a `SpecialtyClinic` supplies its `name`, its `specialty` — one of `METABOLIC_GENETICS`, `AUDIOLOGY`, or `CARDIOLOGY` — and its `concurrent_capacity`, the maximum number of mutually overlapping scheduled confirmatory appointments the clinic can hold at any instant, which must be at least 1.

### 3.2. Registering Newborns and Recording Consent

A `BirthFacilityUser` (or a `ProgramAdmin`) registers each newborn. Registration supplies the `facility_id` of the birthing facility, the `birth_datetime` (the ISO 8601 UTC instant of birth that anchors all timeliness math), the `gestational_age_weeks` completed at birth, the `birth_weight_grams`, the recorded `sex` — one of `M`, `F`, or `U` — and an optional `multiple_birth` flag that defaults to false. When the acting user is a birth-facility user, the supplied `facility_id` must equal their `X-User-ID`. A freshly registered infant starts with `consent_status` at `PENDING`, `open_recollection_count` and `open_case_count` at zero, and `followup_status` at `CLEAR`.

Parental consent is recorded separately by a `BirthFacilityUser` against the infant, carrying a `decision` of either `CONSENT` or `REFUSAL`, the `recorded_by` identity of the person capturing it, and an optional `religious_exemption` flag. A `CONSENT` decision moves `consent_status` to `CONSENTED`; a `REFUSAL` decision moves it to `REFUSED` and triggers the refusal cascade detailed in Section 3.8. The `gestational_age_weeks` and `birth_weight_grams` recorded here feed the follow-up priority calculation later in the infant's journey.

### 3.3. Specimen Collection, Receipt, and Acceptability

A `BirthFacilityUser` logs a collected dried-blood-spot card as a `Specimen` against an infant. The payload declares the `infant_id`, the `specimen_type` — `INITIAL` for the first card or `REPEAT` for a recollection card — the `collection_datetime` of the heel-stick, and the `expected_infant_version` for the concurrency check. The `collection_datetime` must be at or after the infant's `birth_datetime`; an earlier collection is rejected with `ERR_COLLECTION_BEFORE_BIRTH`. On success the specimen is created in `COLLECTED` state, its `collection_age_hours` is computed, the infant's `current_specimen_id` pointer is set to the new specimen (a repeat card supersedes the prior pointer), and the infant's `version` is incremented by one. If the new card's `specimen_type` is `REPEAT`, every one of that infant's recollection orders still in `ORDERED` state transitions to `COLLECTED`, and the infant's `open_recollection_count` is decremented by one for each. Logging a specimen for an infant whose `consent_status` is `REFUSED` is blocked with `ERR_CONSENT_REFUSED`.

Receipt at the laboratory is logged by a `LabTechnician`, who supplies the `received_datetime` and the `blood_spot_count` — the number of adequately saturated spots on the card. The `received_datetime` must be at or after the specimen's `collection_datetime`, else `ERR_RECEIVED_BEFORE_COLLECTION`. Receipt is permitted only from the `COLLECTED` state and only when the infant's consent has not been refused (`ERR_CONSENT_REFUSED`). Receiving records `received_datetime` and `blood_spot_count`, computes `transit_time_hours`, and runs the **acceptability determination**, which advances the specimen from `RECEIVED` to either `SATISFACTORY` or `UNSATISFACTORY` within the same request.

The acceptability determination evaluates four conditions strictly top to bottom, and the first one that matches wins:

1. If `blood_spot_count` is fewer than 4 spots, `acceptability` is `UNSAT_QUANTITY`.
2. Otherwise, if the `collection_age_hours` is under 24 hours **and** the infant's `gestational_age_weeks` is at least 37 (a term infant), `acceptability` is `UNSAT_EARLY`. Preterm infants — those below 37 completed weeks — are exempt from this early-collection rule and never fail on it.
3. Otherwise, if the `transit_time_hours` exceeds 96 hours, `acceptability` is `UNSAT_TRANSIT`.
4. Otherwise, `acceptability` is `SATISFACTORY`.

When the outcome is `SATISFACTORY`, the specimen auto-transitions from `RECEIVED` to `SATISFACTORY` and its provisional timeliness is computed (Section 3.4). When the outcome is anything other than satisfactory, the specimen auto-transitions from `RECEIVED` to `UNSATISFACTORY`, which is a terminal state, and the recollection cascade fires: a `RecollectionOrder` is created in `ORDERED` state, with its `reason` copied from the specimen's `acceptability` determination and a `deadline_datetime` set to the current logical clock plus a 30-day recollection window; and that order's creation increments the infant's `open_recollection_count` by one. A recollection order is never advanced by a direct write — it is created only by this cascade and moves to `COLLECTED` when a repeat card is logged, or to `CANCELLED` by the refusal cascade. The recollection orders belonging to a specimen are discoverable through the specimen's sub-resource listing.

### 3.4. The Screening Panel: Three Independent Dimensions

Once a specimen is `SATISFACTORY`, a `LabTechnician` opens a `Screen` on it by supplying the `specimen_id`. The screen may be opened only when the specimen is in `SATISFACTORY` state, else the create is rejected with `ERR_SPECIMEN_NOT_SATISFACTORY`; opening it links the screen to the specimen and moves the specimen from `SATISFACTORY` to `IN_TESTING`. A screen carries three independent status axes that evolve on the same record: a metabolic axis (`metabolic_status`, starting `PENDING`), a hearing axis (`hearing_status`, starting `NOT_DONE`), and a critical-congenital-heart-disease axis (`cchd_status`, starting `NOT_DONE`). Its `overall_disposition` is derived from all three: it reads `FLAGGED` if any dimension is `PRESUMPTIVE_POSITIVE`, `REFER`, or `FAIL`; `CLEARED` when all three axes have reached a terminal-normal result; `CANCELLED` when the metabolic axis is `CANCELLED`; and `PENDING` otherwise. Every point-of-care or metabolic report recomputes `overall_disposition`.

**Metabolic reporting.** A `LabTechnician` reports the metabolic dimension by supplying a `metabolic_result` and, optionally, a `critical_analyte_count`. Reporting is permitted only while the screen's `metabolic_status` is `PENDING` and its specimen is `IN_TESTING`. Reporting stamps the specimen's `reported_datetime` from the logical clock, moves the specimen from `IN_TESTING` to `TESTED`, and computes the specimen's final timeliness. A `metabolic_result` of `NORMAL` sets `metabolic_status` to `REPORTED_NORMAL`; `BORDERLINE` sets it to `BORDERLINE`; and `PRESUMPTIVE_POSITIVE` sets it to `PRESUMPTIVE_POSITIVE`. A presumptive-positive result additionally records the reported `critical_analyte_count` on the screen, sets `overall_disposition` to `FLAGGED`, and opens a follow-up case: a `SHORT_TERM` `FollowUpCase` is created in `OPEN` state, linked to this screen and the specimen's infant, with `critical_flag_count` copied from the screen's `critical_analyte_count` and `opened_at_clock` set to the current clock; that open increments the infant's `open_case_count` and sets `followup_status` to `ACTIVE`; and the case's INITIAL priority score is computed. If instead the specimen being reported is a `REPEAT` card and a follow-up case for that infant is currently `REPEAT_REQUESTED`, the act of that repeat specimen reaching `TESTED` moves the case from `REPEAT_REQUESTED` to `REPEAT_RECEIVED`, readying it for re-triage.

**Point-of-care reporting.** A `BirthFacilityUser` reports a point-of-care dimension by supplying a `component` of either `HEARING` or `CCHD`. For a hearing report, a `hearing_result` of `PASS` or `REFER` is supplied, and the report is permitted only while `hearing_status` is `NOT_DONE`. A `PASS` moves the hearing axis from `NOT_DONE` to `PASS`. A `REFER` moves it from `NOT_DONE` to `REFER` and sets `overall_disposition` to `FLAGGED`; in addition, if no follow-up case is currently open for this screen, a `SHORT_TERM` `FollowUpCase` is opened in `OPEN` state with `critical_flag_count` of zero and `opened_at_clock` at the current clock, the infant's `open_case_count` is incremented, `followup_status` becomes `ACTIVE`, and an INITIAL priority score is computed — but the specimen is not moved out of `IN_TESTING` and the metabolic axis stays `PENDING`.

For a CCHD report, the `spo2_right_hand` (pre-ductal, right hand) and `spo2_foot` (post-ductal, either foot) percentages are supplied, and the report is permitted only while `cchd_status` is `NOT_DONE`. The two readings are recorded and the **CCHD interpretation** selects the target state. Let the lower reading be the smaller of `spo2_right_hand` and `spo2_foot`, and the difference be the absolute gap between them. If the lower reading is below 90, the interpretation is `FAIL`. Otherwise, if the lower reading is at least 95 and the difference is at most 3, the interpretation is `PASS`. In every other case — a lower reading from 90 through 94, or a lower reading of at least 95 with a difference greater than 3 — the interpretation is `RETEST`. The boundaries are exact: exactly 90 is not below 90 (so it is not a fail on the lower-reading test), and exactly 95 is eligible for a pass. A `PASS` moves the CCHD axis to `PASS`; a `RETEST` moves it to `RETEST`. A `FAIL` moves it to `FAIL`, sets `overall_disposition` to `FLAGGED`, and — exactly as with a hearing refer — opens a `SHORT_TERM` follow-up case for this screen if none is open (with `critical_flag_count` of zero, `opened_at_clock` at the current clock, incrementing `open_case_count`, setting `followup_status` to `ACTIVE`, and computing an INITIAL priority score), again without moving the specimen out of `IN_TESTING`.

### 3.5. Follow-Up Cases, Priority Scoring, and the Repeat Loop

Each `FollowUpCase` records its `infant_id`, the `screen_id` whose flag opened it, its `case_type` (`SHORT_TERM` or `LONG_TERM`), its `critical_flag_count`, a `repeat_count` that starts at zero, the `opened_at_clock` instant, a `priority_variant`, and a `priority_score`. The case lifecycle is cyclic through a repeat loop and runs through the states `OPEN`, `REPEAT_REQUESTED`, `REPEAT_RECEIVED`, `CONFIRMED_POSITIVE`, `LONG_TERM_MONITORING`, `RESOLVED_NORMAL`, and `CLOSED`.

**Priority scoring.** The triage `priority_score` is an integer with two variants. Both build on a base value: 50 points for each critical analyte flagged (the case's `critical_flag_count`), plus 20 points if the infant is preterm — meaning `gestational_age_weeks` is below 34 — plus 15 points if the infant is low-birth-weight, meaning `birth_weight_grams` is below 1500 grams. The **INITIAL** variant, computed when the case opens, is exactly that base. The **REVISED** variant, computed when the case is resolved, starts from the same base and then adds 40 points if the resolving outcome is a confirmation, or subtracts 30 points if the resolving outcome is a normal repeat result; only one of those adjustments applies, according to the outcome. Because a case opened from a hearing refer or a CCHD fail carries `critical_flag_count` of zero, its base reflects only the preterm and low-birth-weight contributions.

**The repeat loop.** A `FollowUpCoordinator` requests a repeat specimen on a case, optionally attaching a `note`. A repeat may be requested when the case is in `OPEN` or `REPEAT_RECEIVED` state; a case already in `REPEAT_REQUESTED` cannot receive another pending request and is rejected with `ERR_DUPLICATE_REPEAT_PENDING`. The request is also gated by the repeat window: the current logical clock must be at or before the case's `opened_at_clock` plus 30 days, otherwise the request is rejected with `ERR_REPEAT_WINDOW_EXPIRED`. A successful request moves the case to `REPEAT_REQUESTED` and increments `repeat_count` by one. The case then advances to `REPEAT_RECEIVED` automatically when a repeat specimen for that infant reaches `TESTED` (Section 3.4). From `REPEAT_RECEIVED`, the coordinator may request yet another repeat — again subject only to the 30-day window from `opened_at_clock` — looping back to `REPEAT_REQUESTED` and incrementing `repeat_count`; this loop may run any number of times.

**Resolution.** A `FollowUpCoordinator` resolves a case by supplying an `outcome`, permitted while the case is in `OPEN` or `REPEAT_RECEIVED`. A `NORMAL` outcome moves the case to `RESOLVED_NORMAL`, flips `priority_variant` to `REVISED` and recomputes the score in its revised form, and — as a compensating adjustment — decrements the infant's `open_case_count` by one, setting `followup_status` back to `CLEAR` if the count reaches zero. A `CONFIRMED` outcome requires that at least one referral belonging to the case has reached `COMPLETED`; if none has, resolution is rejected with `ERR_REFERRALS_UNRESOLVED`. When it is allowed, a confirmation flips `priority_variant` to `REVISED` and recomputes the score in its revised, confirmatory form, changes `case_type` to `LONG_TERM`, moves the case to `CONFIRMED_POSITIVE`, and immediately auto-transitions it to `LONG_TERM_MONITORING`; a long-term-monitoring case remains counted in the infant's `open_case_count`.

### 3.6. Confirmatory Referrals, Appointments, and Completion

To pursue a confirmatory diagnosis, a `FollowUpCoordinator` creates a `Referral` for a case, supplying the `follow_up_case_id`, the receiving `specialty_clinic_id`, and the `referral_reason` — one of `METABOLIC_GENETICS`, `AUDIOLOGY`, or `CARDIOLOGY`. The `referral_reason` must equal the receiving clinic's `specialty`, otherwise the create is rejected with `ERR_CLINIC_SPECIALTY_MISMATCH`. A case may hold at most one open referral at a time: if the case already has a referral in `REQUESTED` or `SCHEDULED` state, the create is rejected with `ERR_DUPLICATE_OPEN_REFERRAL`. A new referral starts in `REQUESTED` state.

Booking a `ConfirmatoryAppointment` against a referral is also a coordinator action, supplying the `referral_id`, a `start_datetime`, and an `end_datetime` that must be strictly after the start, else `ERR_INTERVAL_END_BEFORE_START`. Booking copies the clinic identity onto the appointment's `specialty_clinic_id` from the referral, creates the appointment in `SCHEDULED` state, and moves the referral to `SCHEDULED` — this advance applies whether the referral was in `REQUESTED` or in `NO_SHOW`, so a booked appointment reschedules a previously no-showed referral. Booking is subject to the clinic's aggregate capacity: the number of `SCHEDULED` appointments at the same clinic whose interval overlaps the requested half-open interval must be strictly fewer than the clinic's `concurrent_capacity`; a booking that would meet or exceed that capacity is rejected with `ERR_CLINIC_CAPACITY_EXCEEDED`. Overlap is measured on half-open intervals, so an appointment ending exactly when another begins does not overlap. The appointments belonging to a referral are discoverable through the referral's sub-resource listing.

A `SpecialtyClinician` marks an appointment attended, optionally supplying an `attended` flag; the appointment moves from `SCHEDULED` to `COMPLETED`. This is an ownership-gated action: the acting clinic's `X-User-ID` must equal the appointment's `specialty_clinic_id`, else `ERR_NOT_OWNER`.

Resolving a referral is a coordinator action carrying an `outcome`. A `COMPLETED` outcome requires the referral to be in `SCHEDULED` state (else `ERR_REFERRAL_NOT_SCHEDULED`) and requires at least one of its confirmatory appointments to be in `COMPLETED` state (else `ERR_APPOINTMENT_NOT_COMPLETED`); it moves the referral to `COMPLETED`, which is what unlocks the case's confirmed resolution. A `NO_SHOW` outcome, also requiring the referral to be `SCHEDULED`, moves the referral to `NO_SHOW` and marks its scheduled appointment `NO_SHOW`. A `DECLINED` outcome is permitted while the referral is still `REQUESTED` and moves it to `DECLINED`, recording that the family declined the referral.

### 3.7. Laboratory Assay Runs and Instrument Exclusivity

A `LabTechnician` schedules an `AssayRun` on a laboratory instrument by supplying the `facility_id` of the lab, the `instrument_code`, a `start_datetime`, and an `end_datetime` that must be strictly after the start, else `ERR_INTERVAL_END_BEFORE_START`. Scheduling computes the run's `duration_minutes` as the whole minutes between start and end, creates the run in `SCHEDULED` state, and adds that duration to the facility's `total_booked_minutes`. Instrument time is exclusive with a buffer: a new run is rejected with `ERR_INSTRUMENT_BUSY` if any non-cancelled run on the same facility-and-instrument pair falls within 30 minutes of the new run's interval. Cancelling a run — permitted only from `SCHEDULED` — moves it to `CANCELLED` and, as a compensating adjustment, subtracts that run's `duration_minutes` from the facility's `total_booked_minutes`, restoring the pre-create total. A cancellation may carry an optional `reason`.

### 3.8. The Parental Refusal Cascade

Recording a `REFUSAL` decision against an infant moves its `consent_status` to `REFUSED` and unwinds that infant's in-flight screening work in a single cascade. Every non-terminal specimen of the infant is voided: a specimen in `COLLECTED`, `RECEIVED`, `SATISFACTORY`, or `IN_TESTING` moves to `VOIDED`. When a `RECEIVED` specimen is voided, any recollection order for it still in `ORDERED` state is `CANCELLED`, and each such cancellation decrements the infant's `open_recollection_count` by one. When an `IN_TESTING` specimen is voided, its screen's `metabolic_status` is set to `CANCELLED`, which drives that screen's `overall_disposition` to `CANCELLED`; and any follow-up case for that screen still in `OPEN` or `REPEAT_REQUESTED` state is `CLOSED`, each such closure decrementing the infant's `open_case_count` by one and, if the count reaches zero, resetting `followup_status` to `CLEAR`. Specimens already in a terminal state (`TESTED`, `UNSATISFACTORY`, or already `VOIDED`) are left untouched. Because the refusal cascade mutates the infant and its dependents, it advances the infant's `version`, which is exactly why a subsequently attempted specimen create with a now-stale `expected_infant_version` is rejected.

### 3.9. Program Timeliness Reporting

A `ProgramAdmin` retrieves the program timeliness summary, optionally scoped to a `state_region`. The metric is computed only over **eligible** specimens: those whose `specimen_type` is `INITIAL` and whose `timeliness_final` has been reported (is not null). When a `state_region` is supplied, only facilities reporting under that region contribute. The provisional timeliness on a specimen, recorded as `timeliness_provisional` and computed at receipt, classifies it `ON_TIME` when its `collection_age_hours` is at least 24 and at most 48 and its `transit_time_hours` is at most 24, and `LATE` otherwise. The final timeliness, computed at metabolic reporting, classifies the specimen `TIMELY` when the total birth-to-report turnaround — the elapsed hours from the infant's `birth_datetime` to the specimen's `reported_datetime` — is at most 120 hours (five days), and `DELAYED` otherwise; the two classifications can disagree for the same specimen.

The summary applies a pinned rounding order: **round each facility first, then average, then round.** For each facility with at least one eligible specimen, the per-facility rate is 100 times the count of that facility's eligible specimens classified `TIMELY`, divided by that facility's total eligible specimen count, rounded half-up to one decimal place. The `program_rate` is then the mean of those already-rounded per-facility rates, itself rounded half-up to one decimal place. The alternative of dividing summed timely counts by summed totals is explicitly not used. If no facility has any eligible specimen, the `program_rate` is null — not zero, and not an error. The response also reports `facility_count`, the number of facilities that contributed at least one eligible specimen, and `eligible_specimen_count`, the total number of eligible specimens counted.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource — including lifecycle transitions and point-of-care or metabolic reports — return `200 OK`. Reads return `200 OK`. Request and response payloads for each endpoint are reconstructed from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nbs/facilities` | Register a facility (hospital, birthing center, or state lab) | ProgramAdmin |
| GET | `/nbs/facilities/{id}` | Fetch one facility (exposes total_booked_minutes) | LabTechnician, ProgramAdmin |
| POST | `/nbs/infants` | Register a newborn at the acting facility | BirthFacilityUser, ProgramAdmin |
| GET | `/nbs/infants/{id}` | Fetch one infant | BirthFacilityUser, LabTechnician, FollowUpCoordinator, ProgramAdmin |
| GET | `/nbs/infants` | List infants, optionally filtered by facility or consent | BirthFacilityUser, LabTechnician, FollowUpCoordinator, ProgramAdmin |
| POST | `/nbs/infants/{id}/consent` | Record parental consent or refusal | BirthFacilityUser |
| POST | `/nbs/specimens` | Log a collected specimen (OCC on the infant) | BirthFacilityUser |
| GET | `/nbs/specimens/{id}` | Fetch one specimen | BirthFacilityUser, LabTechnician, FollowUpCoordinator, ProgramAdmin |
| GET | `/nbs/specimens` | List specimens, optionally filtered by infant, status, or type | BirthFacilityUser, LabTechnician, FollowUpCoordinator, ProgramAdmin |
| POST | `/nbs/specimens/{id}/receive` | Log lab receipt; run acceptability and auto-sort | LabTechnician |
| POST | `/nbs/screens` | Open a screening panel on a satisfactory specimen | LabTechnician |
| GET | `/nbs/screens/{id}` | Fetch one screen | BirthFacilityUser, LabTechnician, FollowUpCoordinator, ProgramAdmin |
| GET | `/nbs/screens` | List screens, optionally filtered by specimen | BirthFacilityUser, LabTechnician, FollowUpCoordinator, ProgramAdmin |
| POST | `/nbs/screens/{id}/report-metabolic` | Report the metabolic dimension | LabTechnician |
| POST | `/nbs/screens/{id}/point-of-care` | Report a hearing or CCHD dimension | BirthFacilityUser |
| GET | `/nbs/specimens/{id}/recollection-orders` | List recollection orders for a specimen | BirthFacilityUser, LabTechnician, FollowUpCoordinator, ProgramAdmin |
| GET | `/nbs/follow-up-cases/{id}` | Fetch one follow-up case | FollowUpCoordinator, LabTechnician, ProgramAdmin |
| GET | `/nbs/follow-up-cases` | List follow-up cases, filterable by infant or screen | FollowUpCoordinator, LabTechnician, ProgramAdmin |
| POST | `/nbs/follow-up-cases/{id}/request-repeat` | Request a repeat specimen (cyclic) | FollowUpCoordinator |
| POST | `/nbs/follow-up-cases/{id}/resolve` | Resolve a case (NORMAL or CONFIRMED) | FollowUpCoordinator |
| POST | `/nbs/referrals` | Create a confirmatory/specialty referral for a case | FollowUpCoordinator |
| GET | `/nbs/referrals/{id}` | Fetch one referral | FollowUpCoordinator, SpecialtyClinician, ProgramAdmin |
| GET | `/nbs/referrals` | List referrals, filterable by case or clinic | FollowUpCoordinator, SpecialtyClinician, ProgramAdmin |
| POST | `/nbs/referrals/{id}/resolve` | Resolve a referral (COMPLETED / NO_SHOW / DECLINED) | FollowUpCoordinator |
| POST | `/nbs/specialty-clinics` | Register a specialty clinic with a concurrent capacity | ProgramAdmin |
| POST | `/nbs/confirmatory-appointments` | Book a confirmatory appointment against a referral | FollowUpCoordinator |
| GET | `/nbs/referrals/{id}/confirmatory-appointments` | List confirmatory appointments for a referral | FollowUpCoordinator, SpecialtyClinician, ProgramAdmin |
| POST | `/nbs/confirmatory-appointments/{id}/complete` | Mark an appointment attended (clinic owns it) | SpecialtyClinician |
| POST | `/nbs/assay-runs` | Schedule a lab assay run on a facility instrument | LabTechnician |
| GET | `/nbs/assay-runs/{id}` | Fetch one assay run | LabTechnician, ProgramAdmin |
| GET | `/nbs/assay-runs` | List assay runs, filterable by facility | LabTechnician, ProgramAdmin |
| POST | `/nbs/assay-runs/{id}/cancel` | Cancel an assay run (restores booked minutes) | LabTechnician |
| GET | `/nbs/program/timeliness-summary` | Program timeliness rate (round-per-facility then average) | ProgramAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_INFANT_NOT_FOUND` | 404 |
| `ERR_SPECIMEN_NOT_FOUND` | 404 |
| `ERR_SCREEN_NOT_FOUND` | 404 |
| `ERR_FOLLOWUP_CASE_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_SPECIALTY_CLINIC_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_ASSAY_RUN_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_SPECIMEN_NOT_SATISFACTORY` | 409 |
| `ERR_REFERRAL_NOT_SCHEDULED` | 409 |
| `ERR_CONSENT_REFUSED` | 409 |
| `ERR_CLINIC_SPECIALTY_MISMATCH` | 422 |
| `ERR_APPOINTMENT_NOT_COMPLETED` | 409 |
| `ERR_REFERRALS_UNRESOLVED` | 409 |
| `ERR_DUPLICATE_REPEAT_PENDING` | 409 |
| `ERR_DUPLICATE_OPEN_REFERRAL` | 409 |
| `ERR_COLLECTION_BEFORE_BIRTH` | 422 |
| `ERR_RECEIVED_BEFORE_COLLECTION` | 422 |
| `ERR_REPEAT_WINDOW_EXPIRED` | 409 |
| `ERR_INTERVAL_END_BEFORE_START` | 422 |
| `ERR_CLINIC_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSTRUMENT_BUSY` | 409 |
| `ERR_STALE_INFANT_VERSION` | 412 |

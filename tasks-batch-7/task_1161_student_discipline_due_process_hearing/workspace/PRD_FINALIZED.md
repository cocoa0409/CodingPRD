# Student Discipline Due Process API — Product Requirements Document

## 1. Introduction

Public school districts carry a legal obligation that most software systems never face: when a student is removed from class, the removal itself is a deprivation of an educational entitlement, and every step from the first incident referral to the final expungement of the record is bound by due-process timelines, progressive-discipline policy, and — for students protected under IDEA or Section 504 — federal safeguards that can halt the process outright. This document specifies the Student Discipline Due Process API, the system of record by which a district student-services office runs that pipeline: incident referral and offense-code classification, a progressive sanction matrix bounded by administrator discretion, suspension notice with parent conference and appeal windows, expulsion hearings with officer-ruled evidence packets, manifestation determinations, alternative-education placement with re-entry planning, and the disproportionality analysis that audits the whole apparatus for bias.

Two design commitments shape everything that follows. First, time in this system is a governed resource: every deadline — the one-day notice window, the three-day conference deadline, the five-day appeal window, the ten-day hearing and manifestation deadlines, the two-year expungement wait — is evaluated against a district-controlled logical clock so that policy windows can be exercised deterministically. Second, authority is deliberately fragmented: the administrator who refers an incident may not classify it, the officer who decides an expulsion may not have referred or classified the underlying case, and only a guardian may appeal. The API encodes these segregation-of-duties rules, the cascading state changes they guard, and the ledger of suspension days that accumulates against each student.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles:

- `DistrictAdmin` — district student-services administrator: configures the offense matrix, schedules hearings, decides appeals and expungements, creates alternative-education sites, runs disproportionality reports, and controls the logical clock.
- `SchoolAdministrator` — school-level administrator: refers incidents, classifies offenses, proposes sanctions, issues notices, confirms and closes cases, manages conferences, and submits and serves evidence.
- `HearingOfficer` — independent hearing officer: rules on evidence admissibility, convenes hearings, and issues expulsion decisions.
- `ParentGuardian` — parent or guardian of a student: files appeals and expungement requests and reads their own student's records.
- `StudentServicesDirector` — district student-services director: runs manifestation determinations, alternative-education placements, and re-entry plans.

Access to each operation is restricted to the roles listed for it in §4; an authenticated user attempting an operation outside their role is rejected with `ERR_UNAUTHORIZED` (HTTP 403). All five roles treat `X-User-ID` as an opaque operator identifier not tied to the `id` of any persisted entity, with two comparison duties layered on top of that opacity. When `X-User-Role` is `SchoolAdministrator`, the server records the identifier on the cases that administrator touches — as `referrer_id` at referral and as `classified_by` at classification — and later compares those recorded anchors during segregation-of-duties checks rather than comparing the identifier to any entity `id`. When `X-User-Role` is `DistrictAdmin` or `StudentServicesDirector`, the identifier is likewise opaque; the server may record it (for example, as `requested_by` or a deciding official's stamp) but never compares it to an entity `id`. When `X-User-Role` is `ParentGuardian`, the opaque identifier is compared against the `guardian_id` stored on the student for every guardian-scoped operation — filing an appeal, requesting an expungement, or reading a student, case, notice, conference, appeal, or expungement record belonging to that student — and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `HearingOfficer`, the opaque identifier is compared against a hearing's `hearing_officer_id` for evidence rulings, convening, and decisions, with mismatches likewise rejected as `ERR_OWNERSHIP_MISMATCH`. A fourth auth rule, segregation of duties, forbids one person from performing two separated steps of the same matter and is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the specific pairings are enumerated in §2.9 and at the workflows they guard in §3.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every deadline, window, and day count in this document is evaluated against a server-held logical clock, never against wall-clock time. At startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it holds that value until a district administrator moves it. A `DistrictAdmin`-only capability sets the clock to a supplied `to_iso8601` instant and answers with the new `current_utc`; before the first such call the logical clock keeps reading the startup default and never falls back to wall-clock time. Advancing the clock is itself a mutation of system state: all subsequent deadline and window checks — the one-day notice window, the conference and appeal deadlines, the ten-day hearing and manifestation windows, the evidence-service deadline, placement start dates, and the 730-day expungement wait — are evaluated against the new value.

### 2.5. Common Resource Properties

Most resources in the system — students, discipline cases, suspension notices, conferences, appeals, expulsion hearings, evidence items, manifestation determinations, alternative-education sites, placements, re-entry plans, and expungement requests — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every mutation of the resource and serves optimistic concurrency control where §2.8 applies it.

Two configuration resources are deliberately lighter. An offense code and a sanction band carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, since they are static policy definitions. For all other entities, any change — including system-side cascades such as the version bump a classification applies to its case — refreshes `updated_at` and increments `version`.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated strictly from left to right along the path. The system confirms each identifier in path order — a case before its conference, a hearing before its evidence, a placement before its re-entry plan — and rejects the request at the first identifier that does not resolve to an existing resource, answering `ERR_NOT_FOUND` (HTTP 404). Body-carried references, such as the offense code named at classification or the site named at placement, are checked at the same rung. Existence is therefore always established before any state, window, or capacity rule is consulted.

### 2.7. The Suspension-Day Ledger

Each student carries a running ledger of suspension days in `cumulative_suspension_days`. Its value is defined, at any moment, as the sum of `sanction_days_final` over exactly the student's cases whose status is `CONFIRMED` or `CLOSED`. Cases in any earlier state contribute nothing — no final day count exists for them yet — and `EXPUNGED` cases are excluded entirely. The ledger is debited at confirmation, is recomputed when an appeal reversal touches an already-confirmed case, and is recomputed again as compensation when an expungement is approved. This definition yields the system's central ledger invariant: confirming a case, then closing it, then approving an expungement restores the student's `cumulative_suspension_days` to precisely the value it held before the confirmation. Every ten-day threshold elsewhere in this document — the manifestation-determination trigger and the IDEA day cap — reads this ledger and nothing else.

### 2.8. Optimistic Concurrency Control

Two write operations on a discipline case are guarded by optimistic concurrency control: classification (including the reclassification self-loop) and sanction proposal (including the proposal-adjustment self-loop). Each such request must carry `expected_case_version`, a non-optional field holding the `version` of the case as the client last observed it. When the presented value does not match the case's current `version` — because another write, such as an earlier classification or proposal, has advanced the version since the client last read the case — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting changes it never observed. Endpoints other than these two take no version field at all.

### 2.9. Validation Precedence

Every request traverses a fixed ladder of checks, and a failure at any rung stops the evaluation with that rung's error. The ladder, in order, is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is a declared role — otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The acting role is listed for the endpoint — otherwise `ERR_UNAUTHORIZED`.
3. **Ownership.** Guardian-scoped operations compare `X-User-ID` to the student's `guardian_id`; officer-scoped operations compare it to the hearing's `hearing_officer_id` — otherwise `ERR_OWNERSHIP_MISMATCH`.
4. **Segregation of duties.** Classification forbids the classifier from being the case's referrer; appeal decisions and hearing decisions forbid the decider from being the case's referrer or classifier — otherwise `ERR_SEGREGATION_OF_DUTIES`.
5. **Existence.** Path identifiers and body-carried references exist, validated left to right — otherwise `ERR_NOT_FOUND`.
6. **Request schema.** Required fields are present, enum members are valid, and numeric ranges hold (grade 6 through 12, severity 1 through 4, band bounds with the low end at least zero and the high end at most ten and the low end no greater than the high end, hearing end strictly after start, placement planned end on or after start) — otherwise `ERR_INVALID_REQUEST`.
7. **Optimistic concurrency.** `expected_case_version` matches the case's current `version` on classification and sanction writes — otherwise `ERR_STALE_VERSION`.
8. **State guards.** The entity stands in a valid from-state for the requested transition, and state-guarded child creation is honored: evidence only while its hearing is `SCHEDULED`, a conference or an appeal only while its case is `NOTICE_ISSUED`, a placement only while its case is `EXPULSION_ACTIVE`, a re-entry plan only while its placement is `PLACED` or `ACTIVE`, and a manual manifestation determination only on an applicable track. Violations are rejected with `ERR_INVALID_STATE`, except the re-entry-plan activation gate, which requires the placement to be `ACTIVE` and is reported as `ERR_PLACEMENT_NOT_ACTIVE`.
9. **IDEA/504 safety gate.** Notice issuance and placement creation require that no manifestation determination for the case is `PENDING` or `SCHEDULED`, and placement for a student with disability status additionally requires a `COMPLETED` determination for the case — otherwise `ERR_MDR_INCOMPLETE`.
10. **Due-process windows.** Temporal rules, whose relative order within this rung is pinned as listed: the one-day notice window (`ERR_NOTICE_WINDOW_PASSED`), the conference scheduling deadline (`ERR_CONFERENCE_DEADLINE_PASSED`), the confirmation gates evaluated conference-first and appeal-second (`ERR_CONFERENCE_WINDOW_OPEN` surfaces before `ERR_APPEAL_WINDOW_OPEN`), the appeal filing window (`ERR_APPEAL_WINDOW_CLOSED`), the ten-day hearing scheduling window (`ERR_HEARING_WINDOW_PASSED`), the evidence-service deadline (`ERR_EVIDENCE_DEADLINE_PASSED`), the manifestation completion deadline (`ERR_MDR_DEADLINE_PASSED`), placement activation before its start date (`ERR_PLACEMENT_NOT_STARTED`), and the expungement waiting period (`ERR_EXPUNGEMENT_NOT_ELIGIBLE`).
11. **Uniqueness, capacity, and overlap.** Offense-code uniqueness; one band per offense code and occurrence index (`ERR_DUPLICATE_BAND`); a defined band for the lookup index (`ERR_BAND_NOT_DEFINED`); the absolute ten-day suspension cap (`ERR_SANCTION_EXCEEDS_CAP`) checked before the band range (`ERR_SANCTION_OUT_OF_RANGE`); the expellable-offense gate (`ERR_OFFENSE_NOT_EXPELLABLE`); one open appeal per case (`ERR_APPEAL_ALREADY_OPEN`); one open hearing per case (`ERR_HEARING_ALREADY_OPEN`); officer-calendar overlap (`ERR_HEARING_OVERLAP`); a non-empty evidence packet (`ERR_EVIDENCE_PACKET_EMPTY`); site capacity (`ERR_SITE_CAPACITY_EXCEEDED`); one open placement per case (`ERR_PLACEMENT_ALREADY_ACTIVE`); one open re-entry plan per placement (`ERR_REENTRY_OPEN`); the two-attempt conference cap (`ERR_CONFERENCE_ATTEMPT_LIMIT`); and manual-determination applicability (`ERR_MDR_NOT_APPLICABLE`) with uniqueness (`ERR_MDR_ALREADY_OPEN`).

### 2.10. Numeric Precision and Rounding

Day counts are whole numbers throughout the system: sanction lengths, occurrence indices, attempt numbers, and ledger totals are integers to which no rounding applies. Where thresholds compare day counts, comparisons are exact — a strictly-greater threshold is not met by equality, and an inclusive deadline is met by equality; each rule in §3 states which it is. Report metrics are the sole exception to the no-rounding rule: they are rounded half-up, and every division entering them is performed at full precision before any rounding occurs. The per-group displayed `risk` and each `share_gap` are rounded half-up to four decimal places; each `risk_ratio` is rounded half-up to two decimal places. All timestamps in request and response bodies are ISO 8601 UTC. Except where three fractional digits are explicitly required — the envelope's `api_request_timestamp` (§2.2) and each resource's `created_at` (§2.5) — the server renders every timestamp at second granularity, as in `2026-05-01T00:00:00Z`; this covers `updated_at`, every business timestamp such as `proposed_at`, `issued_at`, `scheduled_at`, `filed_at`, `decided_at`, `confirmed_at`, `closed_at`, and all deadline fields, and the clock capability's `current_utc` answer. Day-granularity fields such as a student's birth date and placement start and end dates are stored at midnight (00:00:00Z).

## 3. Business Logic & Workflows

### 3.1. Enrollment and the Progressive Sanction Matrix

A district enrolls a student by supplying `full_name`, `date_of_birth` (recorded as a date at midnight UTC), `grade_level` as an integer from 6 through 12, the federal-style reporting group `demographic_group` — one of `ASIAN`, `BLACK`, `HISPANIC`, `WHITE`, `MULTIRACIAL`, or `OTHER` — and an opaque `guardian_id` identifying the primary parent or guardian. A student protected under IDEA or Section 504 is enrolled with `disability_status` of `IEP` or `SECTION_504`; when the field is omitted it defaults to `NONE`. New students begin with `enrollment_status` `ENROLLED`, a flag that later cycles through `ALT_ED_PENDING` and `IN_ALT_ED` under the expulsion and placement cascades and returns to `ENROLLED` when a placement ends. The suspension-day ledger behind `cumulative_suspension_days` starts at zero, and `last_case_closed_at` stays empty until the student's first case closes. Either a `DistrictAdmin` or a `SchoolAdministrator` may enroll students. The roster can be listed with optional filters on `demographic_group`, `disability_status`, and `enrollment_status`; staff roles may read any student, while a `ParentGuardian` may read only the student whose `guardian_id` equals their own `X-User-ID`.

The progressive discipline matrix is configured by a `DistrictAdmin` as a catalog of offense codes. Each code carries a unique `code` string such as FITE-01 — a duplicate code is rejected with `ERR_INVALID_REQUEST` — a human-readable `title`, a `category` of `DRUGS`, `WEAPONS`, `VIOLENCE`, `PROPERTY`, `DISRUPTION`, `ATTENDANCE`, or `TECHNOLOGY` that drives occurrence counting, a `severity_level` from 1 (minor) to 4 (most severe), and an `expellable` flag marking whether the offense may be referred to an expulsion hearing. Administrators may read the catalog when classifying cases.

Each offense code is refined by up to three sanction bands, one per `occurrence_index` value: 1 prices a first offense, 2 a second, and 3 a third-or-subsequent offense. A band specifies an inclusive day range from `min_days` to `max_days`; the range must keep the low end at zero or above, the low end no greater than the high end, and the high end at ten days or below, with violations rejected as `ERR_INVALID_REQUEST`. Every band belongs to its offense code through `offense_code_id`, and only one band may exist for a given code-and-index pair — a second band for the same pair is rejected with `ERR_DUPLICATE_BAND`. Bands are created and listed per offense code by district administrators, and are readable by school administrators pricing a sanction.

### 3.2. Incident Referral and Offense Classification

Discipline workflow begins when a `SchoolAdministrator` refers an incident, naming the student through `student_id`, the `incident_date` on which it occurred, and a free-text `description`. The referral creates a discipline case in `SUBMITTED` status and stamps `referrer_id` with the acting administrator's `X-User-ID`; this recorded identity becomes a segregation-of-duties anchor for everything that follows. The case register can be listed with reverse-lookup filters on `student_id`, `offense_code_id`, and `status`, and individual cases are readable by staff roles; a `ParentGuardian` may read only cases belonging to their own student.

Classification assigns the offense. A school administrator classifies a `SUBMITTED` case by presenting an `offense_code_id` together with the OCC token `expected_case_version`, moving the case `SUBMITTED` → `CLASSIFIED`. The referenced offense code must exist, or the write fails with `ERR_NOT_FOUND`; the classifier must not be the administrator who referred the incident, so a request whose `X-User-ID` equals the case's `referrer_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`; and the version token is checked per §2.8, so a stale token is refused with `ERR_STALE_VERSION`. A successful classification records the offense code on the case, stamps `classified_by` with the classifier's `X-User-ID`, computes both occurrence indices described below, and increments the case `version` by one.

Classification is where the progressive matrix learns the incident's position in the student's history. The prior set comprises every other case of the same student — the case being classified never counts itself — whose status is one of `CLASSIFIED`, `SANCTION_PROPOSED`, `NOTICE_ISSUED`, `CONFIRMED`, `EXPULSION_REFERRED`, `EXPULSION_ACTIVE`, or `CLOSED`, and whose assigned offense code belongs to the same `category` as the offense code now being assigned; cases still `SUBMITTED` and cases already `EXPUNGED` never contribute. Two counts are computed and stored on the case. The canonical rolling-window count looks back 365 days from the case's `incident_date`: priors whose own `incident_date` falls inside the window that begins 365 days before the incident and ends the day the incident occurred (the incident day itself excluded) are tallied, and the case's `occurrence_index` is that tally plus one. The index is stored uncapped — only the matrix lookup clamps it, using the lesser of the index and three. The reporting count buckets by academic year instead: the academic year of any date runs from July 1 of year Y through June 30 of year Y+1, where Y is the date's own calendar year when its month is July or later and the prior calendar year otherwise, and `occurrence_index_ay` is the number of priors sharing the incident's academic year, again plus one. A prior incident from June of the preceding academic year can therefore still count under the rolling window while falling outside the academic-year bucket.

Classification is not one-shot. While a case remains `CLASSIFIED`, an administrator may reclassify it through the same write — the `CLASSIFIED` → `CLASSIFIED` self-loop — replacing `offense_code_id` and `classified_by` and recomputing both occurrence indices against the new category. Each reclassification increments `version` again, which is what makes the OCC token meaningful here: a client holding a version captured before another administrator's reclassification finds its `expected_case_version` rejected with `ERR_STALE_VERSION`.

### 3.3. Sanction Proposal and Administrator Discretion

With a case classified, a school administrator proposes the sanction, presenting `sanction_days`, a `sanction_type` of `IN_SCHOOL` or `OUT_OF_SCHOOL`, and the OCC token `expected_case_version`; an optional `override_justification` accompanies out-of-band proposals. The proposal moves the case `CLASSIFIED` → `SANCTION_PROPOSED` and is guarded by the matrix in a fixed order. First, the band applied is the one belonging to the case's offense code whose `occurrence_index` equals the lesser of the case's stored index and three; if no such band exists the proposal is rejected with `ERR_BAND_NOT_DEFINED`. Next, the district's absolute cap applies: any proposal of more than ten days is rejected with `ERR_SANCTION_EXCEEDS_CAP`, and this cap is evaluated before the band range so that an over-cap day count surfaces the cap error rather than a range error. Within the cap, the proposed days are compared to the band's inclusive range from `min_days` to `max_days`. Days inside the range clear the check with `sanction_override` recorded as false. Days outside the range are the matrix's concession to administrator discretion: the request is rejected with `ERR_SANCTION_OUT_OF_RANGE` unless a non-empty `override_justification` accompanies it, in which case the proposal stands with `sanction_override` set to true and the justification retained on the case.

A successful proposal stamps `proposed_sanction_days` and `proposed_sanction_type` onto the case and records `proposed_at` at the current clock, anchoring the one-day notice window of §3.4. The same write evaluates the federal ten-day rule: `mdr_required` is true exactly when the student's `disability_status` is `IEP` or `SECTION_504` and the sum of the student's `cumulative_suspension_days` and the proposed days is strictly greater than ten — a combined total of exactly ten does not trigger it. When the flag comes out true and no manifestation determination for the case currently stands `PENDING` or `SCHEDULED`, the proposal automatically opens one with `origin` `AUTO_THRESHOLD`, status `PENDING`, and a `due_at` ten days after its creation. The case `version` increments by one with each accepted proposal.

While the case remains `SANCTION_PROPOSED`, the same write serves as the adjustment self-loop (`SANCTION_PROPOSED` → `SANCTION_PROPOSED`): it replaces `proposed_sanction_days`, `proposed_sanction_type`, `sanction_override`, and `proposed_at`, recomputes `mdr_required` against the new numbers, and opens an `AUTO_THRESHOLD` determination under the same uniqueness rule when the flag flips on. Adjustment runs the identical band, cap, and override checks and the identical OCC guard, so an administrator iterating on a proposal against a stale `expected_case_version` is refused with `ERR_STALE_VERSION`.

### 3.4. Notice, Conference, and Appeal — the Due-Process Window

A proposed sanction becomes enforceable only through notice. A school administrator issues the suspension notice, choosing a `delivery_method` of `EMAIL`, `CERTIFIED_MAIL`, or `IN_PORTAL`. Two gates guard issuance, IDEA safety before the clock per the ladder in §2.9: no manifestation determination for the case may stand `PENDING` or `SCHEDULED` (`ERR_MDR_INCOMPLETE`), and the clock must sit no later than one day after `proposed_at`, a late attempt drawing `ERR_NOTICE_WINDOW_PASSED`. A lawful issuance creates the notice in `ISSUED` status with `issued_at` stamped at the clock, an `appeal_deadline` five days after issuance inclusive, and a `conference_deadline` three days after issuance inclusive, and advances the case `SANCTION_PROPOSED` → `NOTICE_ISSUED`. A case's notices can be listed by district and school staff and by the student's guardian.

The district then offers a parent conference before the sanction is confirmed. Scheduling is possible only while the case is `NOTICE_ISSUED`, and the chosen `scheduled_at` must fall on or before the notice's `conference_deadline`, otherwise `ERR_CONFERENCE_DEADLINE_PASSED`. The conference begins `SCHEDULED` with `attempt_number` 1. Recording an `outcome` of `HELD` or `WAIVED` closes the conference successfully from `SCHEDULED`; an outcome of `NO_SHOW` leaves it eligible for exactly one retry: rescheduling a no-show returns it to `SCHEDULED`, replaces `scheduled_at`, and increments `attempt_number`, but only while `attempt_number` is still below the hard cap of 2 — a second reschedule is rejected with `ERR_CONFERENCE_ATTEMPT_LIMIT` — and only while the new time still fits the conference deadline (`ERR_CONFERENCE_DEADLINE_PASSED`). Conferences are listed alongside the case for staff and the guardian.

The family may contest the sanction. A `ParentGuardian` files an appeal with `grounds` while the case is `NOTICE_ISSUED`; the filing is stamped `filed_at` at the clock and `filed_by` with the guardian's `X-User-ID`, which must equal the student's `guardian_id` or the filing is rejected with `ERR_OWNERSHIP_MISMATCH`. The filing window closes at the inclusive `appeal_deadline` — filing after it draws `ERR_APPEAL_WINDOW_CLOSED` — and only one appeal may stand `FILED` per case at a time, a second drawing `ERR_APPEAL_ALREADY_OPEN`. A new appeal begins `FILED`, and a case's appeals can be listed by staff and the guardian.

A `DistrictAdmin` decides the appeal, presenting an `outcome` of `UPHELD`, `REVERSED`, or `REMANDED` plus an optional `rationale` that is recorded on the appeal as `decision_rationale`; `decided_at` is stamped at decision time. Segregation of duties forbids the decider from being the case's `referrer_id` or its `classified_by`, with violations rejected as `ERR_SEGREGATION_OF_DUTIES`. The three branches diverge sharply. An `UPHELD` decision leaves the case untouched. A `REVERSED` decision unwinds the sanction: the case drops `NOTICE_ISSUED` → `SANCTION_PROPOSED`, its sanction fields `proposed_sanction_days`, `proposed_sanction_type`, `sanction_override`, `override_justification`, and `proposed_at` are cleared back to empty or false, `sanction_days_final` remains unset, the case's `ISSUED` notice is voided to `VOIDED`, and that voiding cascades one link further — every conference of the case still `SCHEDULED` or `NO_SHOW` is `CANCELLED`, while conferences already `HELD` or `WAIVED` are untouched. A `REMANDED` decision sends the case `NOTICE_ISSUED` → `CLASSIFIED` instead: the sanction fields are cleared in the same way, but the assigned offense code is retained so the case can be reclassified through the classification self-loop, and the same notice-void and conference-cancel cascade fires.

Confirmation is the last step of the ordinary track, moving the case `NOTICE_ISSUED` → `CONFIRMED` behind two due-process gates evaluated in a pinned order, conference first and appeal second. The conference gate requires that at least one conference of the case stands `HELD` or `WAIVED`, or that the clock has passed the notice's `conference_deadline`; otherwise the confirm is rejected with `ERR_CONFERENCE_WINDOW_OPEN`. The appeal gate then requires that no appeal of the case stands `FILED` and that either the `appeal_deadline` has passed or at least one appeal has reached a terminal decision; otherwise the confirm is rejected with `ERR_APPEAL_WINDOW_OPEN`. On success, `sanction_days_final` takes the proposed day count, `confirmed_at` is stamped at the clock, and the final days are debited into the student's `cumulative_suspension_days` ledger per §2.7.

### 3.5. Expulsion Hearings and the Evidence Packet

For the gravest offenses, an administrator may refer a `CLASSIFIED` case to the expulsion track. Referral is lawful only when the offense code's `expellable` flag is true; for a non-expellable offense it is rejected with `ERR_OFFENSE_NOT_EXPELLABLE`. A successful referral stamps `referred_to_expulsion_at` at the clock and moves the case to `EXPULSION_REFERRED`, and that timestamp anchors the scheduling window that follows.

A `DistrictAdmin` schedules the hearing, presenting `case_id`, the `hearing_officer_id` of the assigned officer, `scheduled_start`, and `scheduled_end`. The end must fall strictly after the start, and the hearing occupies the half-open interval that includes its start and excludes its end. The start must fall no later than ten days after `referred_to_expulsion_at`, or scheduling is rejected with `ERR_HEARING_WINDOW_PASSED`. A case may carry only one open hearing — one in `SCHEDULED`, `EVIDENCE_SERVED`, or `HELD` status — so a second hearing for the same case draws `ERR_HEARING_ALREADY_OPEN`. The officer's calendar is an overlap-checked resource across those same three open statuses: the new hearing conflicts with any of the officer's existing hearings whose interval interleaves with it, which under the half-open convention means the new start falls before the existing hearing's end and the existing start falls before the new end; two hearings that merely touch at an endpoint, one ending exactly when the other begins, do not conflict. A conflicting assignment is rejected with `ERR_HEARING_OVERLAP`. A new hearing begins `SCHEDULED`, and the hearing register supports reverse-lookup filters on `case_id`, `hearing_officer_id`, and `status`.

While the hearing remains `SCHEDULED`, a school administrator builds the evidence packet item by item. Each item carries an `item_type` of `WITNESS_STATEMENT`, `DOCUMENT`, `VIDEO`, or `OTHER` with a `description`, records `submitted_by` from the submitting administrator's `X-User-ID`, attaches to its hearing through `hearing_id`, and begins `SUBMITTED`. The assigned officer then rules on each `SUBMITTED` item: a `ruling` of `ADMITTED` or `EXCLUDED` is accepted only while the hearing is still `SCHEDULED` and only from the officer whose `X-User-ID` equals the hearing's `hearing_officer_id`, any other officer drawing `ERR_OWNERSHIP_MISMATCH`. The packet — the hearing's evidence list — is readable by district staff, school administrators, and hearing officers.

Serving the packet locks it. An administrator serves the packet once at least one item stands `ADMITTED` — an empty packet is rejected with `ERR_EVIDENCE_PACKET_EMPTY` — and no later than two days before the scheduled start, a later service drawing `ERR_EVIDENCE_DEADLINE_PASSED`. Service stamps `packet_served_at` at the clock, moves the hearing `SCHEDULED` → `EVIDENCE_SERVED`, and forecloses any further evidence creation for that hearing. Once the clock has reached `scheduled_end`, the assigned officer convenes the hearing — an attempt before the end fails with `ERR_INVALID_STATE`, and again only the assigned officer passes ownership — moving it `EVIDENCE_SERVED` → `HELD`. The decision then rests with the same officer: an `outcome` of `EXPULSION_ORDERED` or `NOT_EXPELLED`, with an optional `rationale` saved as `decision_rationale` and `decided_at` stamped at the clock. Ownership is enforced once more, and segregation of duties bars a decider who served as the case's referrer or classifier (`ERR_SEGREGATION_OF_DUTIES`). The branches carry the system's heaviest cascade. Ordering expulsion fires two links: the case moves `EXPULSION_REFERRED` → `EXPULSION_ACTIVE`, and the student's `enrollment_status` moves `ENROLLED` → `ALT_ED_PENDING` in the same motion. A finding of `NOT_EXPELLED` instead reverts the case `EXPULSION_REFERRED` → `CLASSIFIED`, clears `referred_to_expulsion_at` back to empty, and lets the case resume the ordinary discipline track.

### 3.6. Manifestation Determination and the IDEA/504 Safety Gate

A manifestation determination asks whether a student's disability caused the conduct, and it reaches the workflow through two doors. The automatic door opened in §3.3 — a sanction proposal that pushes a protected student past ten cumulative days — creates the determination with `origin` `AUTO_THRESHOLD`. The manual door belongs to the `StudentServicesDirector`, who may open a determination for an expulsion-track case whose student carries `IEP` or `SECTION_504` status. The manual door is refused with `ERR_MDR_NOT_APPLICABLE` when the student's `disability_status` is `NONE` or the case is not on an applicable track, and with `ERR_MDR_ALREADY_OPEN` when a determination already stands `PENDING` or `SCHEDULED` for the case. A manually opened determination carries `origin` `MANUAL`, status `PENDING`, and a `due_at` ten days after its creation — the same inclusive completion deadline the automatic variant receives. A case's determinations can be listed by district and school staff and the director, which is also the discovery channel for an auto-created one.

Scheduling sets `meeting_at` and moves the determination `PENDING` → `SCHEDULED`. Completion is lawful only from `SCHEDULED` and only on or before `due_at` — a late completion is rejected with `ERR_MDR_DEADLINE_PASSED` — and records an `outcome` of `MANIFESTATION_YES` or `MANIFESTATION_NO`, stamping `completed_at` at the clock. When the outcome is `MANIFESTATION_YES` and the case sits at `SANCTION_PROPOSED`, the IDEA ten-day cap bites immediately: the case's `proposed_sanction_days` is reduced to the lesser of its current value and the greater of zero and ten minus the student's `cumulative_suspension_days`, so the proposal can never push the student past ten total days and never below zero. A `MANIFESTATION_YES` outcome is also what unlocks notice issuance and, later, alternative-education placement for students with disabilities, since both gates of §2.9's ninth rung demand a determination that is no longer open.

### 3.7. Alternative Education Placement and Re-Entry

The district's alternative-education capacity is modeled as sites, each created by a `DistrictAdmin` with a `name` and a `capacity` of at least one. A site's live `seats_occupied` is computed on every read as the number of its placements in `PLACED` or `ACTIVE` status whose closed date interval — `start_date` through `planned_end_date`, both ends inclusive — covers the current clock day; a freshly created site reads zero. Sites and placements are readable by district administrators and the director.

Once a case stands `EXPULSION_ACTIVE`, the `StudentServicesDirector` places the student, presenting `case_id`, `site_id`, `start_date`, and `planned_end_date`. Both dates are day-granularity values at midnight UTC, and the planned end must fall on or after the start or the request fails schema validation with `ERR_INVALID_REQUEST`. The IDEA gate applies in full: placement is refused with `ERR_MDR_INCOMPLETE` while any determination for the case stands `PENDING` or `SCHEDULED`, and for a student with disability status the case must show a `COMPLETED` determination. Capacity is enforced in aggregate over closed intervals: counting the new placement, the site's overlapping placements in `PLACED` or `ACTIVE` status may not exceed its `capacity`, on pain of `ERR_SITE_CAPACITY_EXCEEDED`. One open placement per case is the rule, so a second placement while one stands `PLACED` or `ACTIVE` draws `ERR_PLACEMENT_ALREADY_ACTIVE`. A new placement begins `PLACED`, and the placement register supports filters on `case_id`, `site_id`, and `status`.

Activation waits for the placement's first day: the clock must have reached `start_date`, and an earlier attempt fails with `ERR_PLACEMENT_NOT_STARTED`. Activation moves the placement `PLACED` → `ACTIVE` and the student's `enrollment_status` `ALT_ED_PENDING` → `IN_ALT_ED`, with the site's `seats_occupied` reflecting the activation on subsequent reads. Completion, from `ACTIVE`, records an `outcome` of `COMPLETED` or `EXITED_EARLY`, stamps `actual_end_date` at the clock, and returns the student from `IN_ALT_ED` to `ENROLLED`.

Re-entry planning runs alongside the placement. While a placement stands `PLACED` or `ACTIVE`, the director creates a plan with an ordered list of `conditions` strings and a `conference_date`; the plan begins `DRAFT`, attached to its placement through `placement_id`, and only one open plan may exist per placement — a second draws `ERR_REENTRY_OPEN`. Activation is guarded across entities: the plan can leave `DRAFT` for `ACTIVE` only while its placement is `ACTIVE`, failing otherwise with `ERR_PLACEMENT_NOT_ACTIVE`. The plan's `outcome` is later recorded from `ACTIVE` as `COMPLETED` or `VIOLATED`, and a placement's plans can be listed by district staff and the director.

### 3.8. Case Closure and Expungement

Closure takes different testimony depending on how the case arrived. An ordinary confirmed case closes once its days are served: the clock must have reached the day falling `sanction_days_final` days after `confirmed_at`, and an earlier close is rejected with `ERR_INVALID_STATE`. An expulsion case closes only when every placement of the case stands `COMPLETED` or `EXITED_EARLY` — otherwise `ERR_INVALID_STATE` — and, for each placement carrying at least one re-entry plan, the most recently created plan (plans ordered by creation time, the latest winning) stands `COMPLETED`, an uncompleted latest plan blocking closure with `ERR_REENTRY_OPEN`. Either closure moves the case to `CLOSED`, stamps `closed_at` at the clock, and rolls the student's `last_case_closed_at` forward to the later of its existing value and this closure.

Families may petition to clear the record. A `ParentGuardian` submits an expungement request naming `student_id`; `requested_by` is stamped from the guardian's `X-User-ID` and must equal the student's `guardian_id` (`ERR_OWNERSHIP_MISMATCH`). Eligibility is strict and threefold: the student must have at least one case in `CLOSED` status, every case of the student must stand `CLOSED` or `EXPUNGED`, and the clock must have reached at least the day 730 days after `last_case_closed_at` — the two-year boundary is inclusive, so a request filed exactly 730 days after the last closure qualifies. Any shortfall is rejected with `ERR_EXPUNGEMENT_NOT_ELIGIBLE`. A new request begins `SUBMITTED`, and a student's requests can be listed by district staff and the guardian.

A `DistrictAdmin` decides the request from `SUBMITTED`, presenting an `outcome` of `APPROVED` or `DENIED` with an optional `rationale` kept as `decision_rationale`; `decided_at` is stamped either way. Approval cascades through the student's record: every `CLOSED` case of the student becomes `EXPUNGED`, and the student's `cumulative_suspension_days` is recomputed with the expunged rows excluded — the ledger compensation of §2.7, which is what makes an expunged record stop counting toward the ten-day thresholds. Denial changes nothing beyond the request itself.

### 3.9. Disproportionality Reporting

The district audits its own discipline patterns through a `DistrictAdmin`-only report. The caller supplies an `academic_year` as a string of the form YYYY-YYYY and a `reference_group` drawn from the `demographic_group` enumeration; the window evaluated runs from July 1 of the first year through June 30 of the second. For each group, the system counts the enrolled students carrying that `demographic_group` and the group's disciplined students — those with at least one case in `CONFIRMED` or `CLOSED` status whose `incident_date` falls inside the window, `EXPUNGED` cases excluded. Groups with zero enrolled students are dropped from the results entirely rather than reported with an undefined risk.

Each surviving group reports a displayed `risk`: the quotient of its disciplined students over its enrolled students, computed at full precision and rounded half-up to four decimal places. Two comparison measures accompany it. The `risk_ratio` divides the group's risk by the reference group's risk — the division is performed at full precision and only the resulting ratio is rounded half-up to two decimal places; rounding either group's risk before dividing is forbidden. The `share_gap` subtracts the group's share of total enrollment from its share of all disciplined students and rounds the difference half-up to four decimal places, a composition measure whose magnitude and sign structure differ from the ratio's for identical data. The reference group must itself have both enrolled and disciplined students above zero in the requested year, or the report is rejected with `ERR_INVALID_REFERENCE_GROUP`. The response echoes the `academic_year` and `reference_group`, reports the number of groups evaluated as `groups_evaluated`, and carries the per-group rows in `results`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection — enrolling a student, opening a case, issuing a notice, scheduling a conference, hearing, or placement — return `201 Created`. Operations that modify an existing resource, record a decision or outcome, or advance a state machine return `200 OK`; the clock-setting capability also returns `200 OK`. Request and response bodies are deliberately omitted from the table below — §3 narrates each operation's inputs, gates, and side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | DistrictAdmin |
| POST | `/students` | Enroll a student | DistrictAdmin, SchoolAdministrator |
| GET | `/students/{id}` | Read a student | DistrictAdmin, SchoolAdministrator, StudentServicesDirector, HearingOfficer, ParentGuardian |
| GET | `/students` | List students with filters and pagination | DistrictAdmin, SchoolAdministrator, StudentServicesDirector |
| POST | `/offense-codes` | Create an offense code | DistrictAdmin |
| GET | `/offense-codes/{id}` | Read an offense code | DistrictAdmin, SchoolAdministrator |
| POST | `/offense-codes/{id}/sanction-bands` | Add a progressive-matrix sanction band to an offense code | DistrictAdmin |
| GET | `/offense-codes/{id}/sanction-bands` | List bands of an offense code | DistrictAdmin, SchoolAdministrator |
| POST | `/cases` | Create an incident referral | SchoolAdministrator |
| GET | `/cases/{id}` | Read a case | DistrictAdmin, SchoolAdministrator, StudentServicesDirector, HearingOfficer, ParentGuardian |
| GET | `/cases` | List cases with filters and pagination | DistrictAdmin, SchoolAdministrator, StudentServicesDirector |
| POST | `/cases/{id}/classify` | Classify or reclassify the offense code (OCC-guarded) | SchoolAdministrator |
| POST | `/cases/{id}/sanction` | Propose or adjust the sanction (OCC-guarded; may auto-create an MDR) | SchoolAdministrator |
| POST | `/cases/{id}/notices` | Issue the suspension notice | SchoolAdministrator |
| GET | `/cases/{id}/notices` | List notices of a case | DistrictAdmin, SchoolAdministrator, ParentGuardian |
| POST | `/cases/{id}/confirm` | Confirm the sanction after the conference and appeal gates | SchoolAdministrator |
| POST | `/cases/{id}/close` | Close a case | SchoolAdministrator |
| POST | `/cases/{id}/refer-expulsion` | Refer a case to the expulsion track | SchoolAdministrator |
| POST | `/cases/{id}/conferences` | Schedule a parent conference | SchoolAdministrator |
| GET | `/cases/{id}/conferences` | List conferences of a case | DistrictAdmin, SchoolAdministrator, ParentGuardian |
| POST | `/conferences/{id}/outcome` | Record a conference outcome | SchoolAdministrator |
| POST | `/conferences/{id}/reschedule` | Reschedule a no-show conference | SchoolAdministrator |
| POST | `/cases/{id}/appeals` | Guardian files an appeal | ParentGuardian |
| GET | `/cases/{id}/appeals` | List appeals of a case | DistrictAdmin, SchoolAdministrator, ParentGuardian |
| POST | `/appeals/{id}/decision` | Decide an appeal | DistrictAdmin |
| POST | `/hearings` | Schedule an expulsion hearing | DistrictAdmin |
| GET | `/hearings/{id}` | Read a hearing | DistrictAdmin, HearingOfficer, SchoolAdministrator |
| GET | `/hearings` | List hearings with filters and pagination | DistrictAdmin, HearingOfficer |
| POST | `/hearings/{id}/evidence` | Submit an evidence item | SchoolAdministrator |
| GET | `/hearings/{id}/evidence` | List evidence of a hearing (the packet) | DistrictAdmin, HearingOfficer, SchoolAdministrator |
| POST | `/evidence-items/{id}/rule` | Rule on evidence admissibility | HearingOfficer |
| POST | `/hearings/{id}/serve-packet` | Serve the evidence packet | SchoolAdministrator |
| POST | `/hearings/{id}/convene` | Convene the hearing | HearingOfficer |
| POST | `/hearings/{id}/decision` | Issue the expulsion decision | HearingOfficer |
| POST | `/cases/{id}/manifestation-determinations` | Manually open a manifestation determination | StudentServicesDirector |
| GET | `/cases/{id}/manifestation-determinations` | List manifestation determinations of a case | DistrictAdmin, SchoolAdministrator, StudentServicesDirector |
| POST | `/manifestation-determinations/{id}/schedule` | Schedule the determination meeting | StudentServicesDirector |
| POST | `/manifestation-determinations/{id}/complete` | Complete the determination with an outcome | StudentServicesDirector |
| POST | `/alt-ed-sites` | Create an alternative-education site | DistrictAdmin |
| GET | `/alt-ed-sites/{id}` | Read a site (including live seat occupancy) | DistrictAdmin, StudentServicesDirector |
| POST | `/placements` | Create an alternative-education placement | StudentServicesDirector |
| GET | `/placements/{id}` | Read a placement | DistrictAdmin, StudentServicesDirector |
| GET | `/placements` | List placements with filters and pagination | DistrictAdmin, StudentServicesDirector |
| POST | `/placements/{id}/activate` | Activate a placement | StudentServicesDirector |
| POST | `/placements/{id}/complete` | Complete or early-exit a placement | StudentServicesDirector |
| POST | `/placements/{id}/re-entry-plans` | Create a re-entry plan for a placement | StudentServicesDirector |
| GET | `/placements/{id}/re-entry-plans` | List re-entry plans of a placement | DistrictAdmin, StudentServicesDirector |
| POST | `/re-entry-plans/{id}/activate` | Activate a re-entry plan | StudentServicesDirector |
| POST | `/re-entry-plans/{id}/outcome` | Record a re-entry plan outcome | StudentServicesDirector |
| POST | `/expungement-requests` | Guardian requests record expungement | ParentGuardian |
| GET | `/students/{id}/expungement-requests` | List expungement requests of a student | DistrictAdmin, ParentGuardian |
| POST | `/expungement-requests/{id}/decision` | Decide an expungement request | DistrictAdmin |
| GET | `/reports/disproportionality` | Disproportionality analysis for an academic year | DistrictAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are narrated where the rule lives in §2 and §3; the catalogue below is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MDR_INCOMPLETE` | 409 |
| `ERR_MDR_NOT_APPLICABLE` | 409 |
| `ERR_MDR_ALREADY_OPEN` | 409 |
| `ERR_MDR_DEADLINE_PASSED` | 409 |
| `ERR_NOTICE_WINDOW_PASSED` | 409 |
| `ERR_CONFERENCE_DEADLINE_PASSED` | 409 |
| `ERR_CONFERENCE_WINDOW_OPEN` | 409 |
| `ERR_CONFERENCE_ATTEMPT_LIMIT` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_WINDOW_OPEN` | 409 |
| `ERR_APPEAL_ALREADY_OPEN` | 409 |
| `ERR_HEARING_WINDOW_PASSED` | 409 |
| `ERR_HEARING_ALREADY_OPEN` | 409 |
| `ERR_HEARING_OVERLAP` | 409 |
| `ERR_EVIDENCE_DEADLINE_PASSED` | 409 |
| `ERR_EVIDENCE_PACKET_EMPTY` | 409 |
| `ERR_SITE_CAPACITY_EXCEEDED` | 409 |
| `ERR_PLACEMENT_ALREADY_ACTIVE` | 409 |
| `ERR_PLACEMENT_NOT_STARTED` | 409 |
| `ERR_PLACEMENT_NOT_ACTIVE` | 409 |
| `ERR_REENTRY_OPEN` | 409 |
| `ERR_EXPUNGEMENT_NOT_ELIGIBLE` | 409 |
| `ERR_DUPLICATE_BAND` | 409 |
| `ERR_BAND_NOT_DEFINED` | 409 |
| `ERR_SANCTION_OUT_OF_RANGE` | 422 |
| `ERR_SANCTION_EXCEEDS_CAP` | 422 |
| `ERR_OFFENSE_NOT_EXPELLABLE` | 409 |
| `ERR_INVALID_REFERENCE_GROUP` | 422 |

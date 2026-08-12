# Hospitalist Census API — Product Requirements Document

## 1. Introduction

A hospitalist group lives or dies by balance: too many admissions piled onto one physician and care quality degrades, too few and the group leaves capacity — and revenue — on the table. Day to day, the group's coordinators juggle an inbound stream of admissions from the emergency department, direct referrals, and transfers; physicians round on their panels, write discharge orders against a morning throughput target, sign out to colleagues at shift change, and route consults to specialists who answer under a service-level clock. Overnight, a smaller bench of providers covers the whole census, with cross-cover shifts carrying a measurably heavier load. All the while, utilization staff watch two clocks on every patient — calendar midnights and elapsed 24-hour blocks — because observation stays that run past forty-eight hours must convert to inpatient, and length-of-stay outliers need flagging before they become denials.

This document specifies the API that operationalizes that balancing act. It covers the provider roster and shift schedule; a weighted admission-distribution selector that levels census across eligible, on-shift physicians while rewarding continuity of care; the assignment lifecycle including transfer handshake and discharge cascades; signout handoffs with completeness gating; consult routing with priority-based response deadlines; encounter capture and productivity reporting with two deliberately different rounding disciplines; night coverage windows with capacity pools and cross-cover load scoring; and a single operations checkpoint that advances all time-driven transitions at the group's logical clock. Every mutation and its cascaded side effects are immediately consistent — visible in the triggering response and in any subsequent read.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the caller's role. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint — or whose `X-User-ID` fails a resource ownership rule — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Three roles exist, spelled exactly as follows: `GroupAdmin`, `Hospitalist`, and `ConsultingSpecialist`.

A `GroupAdmin` is the group's operations administrator, owning the roster, the schedule, admission intake, coverage windows, productivity reports, the operations checkpoint, and the logical clock. When `X-User-Role` is `GroupAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.

A `Hospitalist` is a group physician who accepts admissions, rounds on assigned patients, orders and executes discharges, authors and receives signouts, requests consults, records encounters, and enrolls in night coverage. When `X-User-Role` is `Hospitalist`, `X-User-ID` is the `id` of the acting `Hospitalist`; ownership checks on any resource that references a hospitalist compare the resource's foreign-key field — for example `hospitalist_id` on a shift, assignment, or encounter, `ordering_hospitalist_id` on a discharge order, `requesting_hospitalist_id` on a consult, or `receiving_hospitalist_id` on a handoff — to `X-User-ID`.

A `ConsultingSpecialist` answers routed consult requests. When `X-User-Role` is `ConsultingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0; a non-integer value, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list response orders its rows by `created_at` ascending, and its `meta` object carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, Versioning, and the Logical Clock

Every resource in this API carries a server-minted `id` formatted as a bare UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that starts at 1 on creation and increments by exactly one on every mutation of the resource — including mutations driven by cascaded side effects on a related resource. All timestamps are ISO 8601 UTC with three fractional digits.

All server-stamped time derives from a single **logical clock**, never from wall-clock time. At server startup the logical clock reads 2026-05-01T00:00:00Z, and it advances only through an admin-only test-driving capability, `POST /_clock/set_current_utc`, which moves the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Every timestamp the server stamps after that call — admission and offer times, order and execution times, signout submissions, consult acknowledgements, report generation — draws from the logical clock.

### 2.5. Census Accounting and Capacity Thresholds

Each hospitalist carries three computed census fields, refreshed on the mutations that affect them. `current_census` is the count of that hospitalist's assignments in status `ACTIVE`, refreshed on every assignment mutation. `pending_offers` is the count of admissions in status `OFFERED` whose `offered_to_hospitalist_id` names this hospitalist. `distribution_eligible` begins as true when `employment_status` is `ACTIVE` — false already at creation otherwise — and is recomputed on every census or employment mutation: it is false whenever `employment_status` is anything other than `ACTIVE`, and false whenever `current_census` has reached `max_census_cap`.

Capacity flips are threshold events, not gradual ones. When an acceptance raises a hospitalist's `current_census` to exactly equal `max_census_cap`, `distribution_eligible` flips to false in the same mutation; when a closure drops `current_census` back below the cap, `distribution_eligible` is recomputed and flips back to true. The same recomputation applies symmetrically on the source and target sides of a transfer.

One conservation invariant governs the whole assignment book and is asserted after every assignment mutation — acceptance, transfer acceptance, transfer cancellation, and discharge closure alike: the group-wide total of `ACTIVE` assignments always equals the number of distinct patients holding an `ACTIVE` assignment, no patient ever holds more than one `ACTIVE` assignment, a transfer acceptance conserves the group-wide total by closing exactly one `ACTIVE` assignment and creating exactly one in the same mutation, and a discharge closure decrements the total by exactly one in the same mutation that flips the patient to `DISCHARGED`.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Revising a handoff requires the request to carry `expected_handoff_version` holding the handoff's `version` as the client last observed it; initiating an assignment transfer requires `expected_assignment_version` holding the assignment's `version` as last observed. In both cases the field is non-optional, and a value that no longer matches the entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

The stale-version check exists because status alone cannot distinguish a stale write in either flow. A handoff may remain legitimately in `DRAFT` or `RETURNED` while another revision — or a submit-then-return cycle — has advanced its version; a stale revision would silently discard the intervening change. Likewise, an assignment may complete a full initiate-then-cancel cycle between a client's read and its transfer initiation, returning the status to `ACTIVE` while the version has moved; only the version check catches it. The version comparison is evaluated at the state-check tier of the validation pipeline, immediately after existence checks. Endpoints not named here take no version field at all.

### 2.7. Validation Pipeline and Error Semantics

Every request passes through a nine-tier validation pipeline, and the tiers run in a fixed relative order — an earlier tier's failure masks later tiers, so callers always see the earliest applicable rejection.

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is declared — `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization and ownership.** The role is permitted for the endpoint and `X-User-ID` satisfies the resource's ownership rule where one is stated — `ERR_UNAUTHORIZED_ROLE` (HTTP 403). An ownership rule that must read the target resource is evaluated once that resource's path identifier has been resolved, so a missing path resource surfaces `ERR_NOT_FOUND` rather than `ERR_UNAUTHORIZED_ROLE`.
3. **Request shape.** Required fields are present, types are valid, enum members are known, date and datetime formats parse, and a transfer's target differs from the current holder — `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence.** Identifiers referenced in the path and in the body exist, validated left-to-right along the request — the first missing id yields `ERR_NOT_FOUND` (HTTP 404). For nested creation paths, the parent path identifier is resolved before any identifier appearing in the body.
5. **State preconditions and version checks.** Each state-transition endpoint enforces its own resource's current state, surfacing the entity-specific invalid-state error — `ERR_ADMISSION_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_DISCHARGE_ORDER_INVALID_STATE`, `ERR_HANDOFF_INVALID_STATE`, `ERR_CONSULT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, `ERR_COVERAGE_WINDOW_NOT_OPEN`, or `ERR_ENCOUNTER_ALREADY_VOIDED`, all HTTP 409 — and the optimistic-concurrency fields named in §2.6 are compared here, immediately after existence, surfacing `ERR_STALE_VERSION` (HTTP 412).
6. **Business safety.** A discharge execution colliding with an unresolved `STAT` consult is refused — `ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE` (HTTP 422) — and a handoff accepted by the same hospitalist who submitted it is refused — `ERR_HANDOFF_SELF_ACCEPT` (HTTP 409).
7. **Temporal rules.** Shift windows must end strictly after they start — `ERR_SHIFT_INVALID_WINDOW` (HTTP 422) — and must not overlap an existing shift of the same hospitalist — `ERR_SHIFT_OVERLAP` (HTTP 409); acceptance paths require a covering active shift — `ERR_NO_ACTIVE_SHIFT` (HTTP 422); consult reopens must fall inside their window — `ERR_CONSULT_REOPEN_WINDOW_EXPIRED` (HTTP 422); enrollment must not collide with the caller's own overlapping shift — `ERR_ENROLL_SHIFT_CONFLICT` (HTTP 409).
8. **Cross-entity and uniqueness rules.** The patient must currently be admitted — `ERR_PATIENT_NOT_ADMITTED` (HTTP 409); no patient may hold a second active assignment — `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` (HTTP 409); a signout must cover every required patient — `ERR_HANDOFF_INCOMPLETE` (HTTP 422); duplicate enrollment is refused — `ERR_ALREADY_ENROLLED` (HTTP 409); the accepting hospitalist must be employed and active — `ERR_HOSPITALIST_NOT_ACTIVE` (HTTP 422); the caller must be the hospitalist the admission was offered to — `ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST` (HTTP 409); the caller must be the named transfer target — `ERR_TRANSFER_TARGET_MISMATCH` (HTTP 409); a shift may close only with an accepted signout on record — `ERR_SHIFT_HANDOFF_MISSING` (HTTP 409).
9. **Capacity and quota — always last.** The accepting hospitalist's census must be strictly below `max_census_cap`, with equality rejecting — `ERR_CENSUS_CAP_REACHED` (HTTP 422) — and a coverage window at capacity refuses further enrollment — `ERR_COVERAGE_WINDOW_FULL` (HTTP 422). Note the deliberate split for coverage windows: a window in status `LOCKED` or `CLOSED` rejects enrollment and withdrawal at tier 5 as a state violation, while a window in status `FULL` rejects enrollment here at tier 9 as a capacity violation.

### 2.8. Precision, Rounding, and Time Comparisons

Monetary and workload figures — encounter estimates, report totals and variances, cross-cover load scores, consult response minutes — are rounded half up to two decimal places. Selector scores, leveling deviations, and handoff completeness scores are rounded half up to four decimal places, and selector comparisons run on the rounded value. Rounding order is pinned where it matters and is stated with each calculation in §3; it is not interchangeable.

Shift and coverage-window intervals are half-open: an interval covers the logical time when `start_at` is at or before that time and `end_at` is strictly after it. Pure adjacency — one interval's `end_at` equal to another's `start_at` — never counts as an overlap. Consult deadlines and the discharge throughput cutoff compare timestamps at millisecond precision; length-of-stay and observation-threshold computations work at second precision. Boundary rules are stated per rule and are strict about direction: the discharge cutoff and the observation conversion threshold admit equality, while the consult breach test and the length-of-stay alert test are strictly-greater comparisons.

### 2.9. The Operations Monitor Checkpoint

Time-driven transitions do not fire on their own; they advance in a single admin-only operations checkpoint, `POST /ops/monitor-run`, evaluated at the logical clock. One run sweeps, in whatever order the server chooses but in one consistent pass: observation-status conversions for observation patients past their threshold, consult escalations for unanswered requests past deadline, consult auto-closures past the reopen window, coverage-window locks and closures at their boundaries, a length-of-stay refresh across admitted patients, and a cross-cover load recomputation on locked windows. Each swept mutation increments the affected entity's `version` and refreshes its `updated_at`, and every effect is visible in the same response's aftermath and in subsequent reads.

The checkpoint answers with `evaluated_at` — the logical instant of evaluation — plus five arrays naming what moved: `obs_converted_patient_ids`, `escalated_consult_ids`, `closed_consult_ids`, `locked_window_ids`, and `closed_window_ids`.

## 3. Business Logic & Workflows

### 3.1. Provider Roster and Shift Scheduling

A `GroupAdmin` builds the roster one provider at a time. Creating a hospitalist takes `full_name`; a `specialty` of `INTERNAL_MEDICINE`, `FAMILY_MEDICINE`, or `ICU`; an optional `employment_status` defaulting to `ACTIVE` (the other values being `ON_LEAVE` and `INACTIVE`); an optional `max_census_cap` defaulting to 16 and never below 1; and an optional `night_eligible` flag, defaulting to true, recording whether the provider may enroll in night coverage windows. Reads of a hospitalist expose the computed census trio described in §2.5, and the roster list filters by `employment_status`.

With providers on the roster, scheduling creates a shift by naming `hospitalist_id`, a `shift_type` of `DAY` or `NIGHT`, and the half-open bounds `start_at` and `end_at`. Two temporal rules guard creation, both at the pipeline's temporal tier: `end_at` must be strictly later than `start_at`, failing with `ERR_SHIFT_INVALID_WINDOW` (HTTP 422); and the new interval must not intersect any existing non-closed shift of the same hospitalist, failing with `ERR_SHIFT_OVERLAP` (HTTP 409) — pure adjacency, where the new `start_at` equals an existing shift's `end_at`, is permitted. The shift list answers reverse lookups by `hospitalist_id` and `state`.

A new shift begins `SCHEDULED`. Activation moves it `SCHEDULED` → `ACTIVE` and is performed by a `GroupAdmin` or by the hospitalist who owns the shift; activating anything not currently `SCHEDULED` fails with `ERR_SHIFT_INVALID_STATE`. Closing moves `ACTIVE` → `CLOSED`, the terminal state, under the same actors — but only once an `ACCEPTED` handoff exists for that shift; without one the close is refused with `ERR_SHIFT_HANDOFF_MISSING` (HTTP 409), and closing from any state other than `ACTIVE` again fails with `ERR_SHIFT_INVALID_STATE`. Both transitions increment the shift's `version` by one. Closing a shift deliberately does not close the hospitalist's assignments: the census is unaffected by shift closure, and patients remain assigned until discharge or transfer moves them.

### 3.2. Patient Registration, Observation Status, and Length-of-Stay Monitoring

Registration is a `GroupAdmin` act capturing `mrn` — the medical record number, unique across all patients, with a duplicate registration rejected as `ERR_INVALID_REQUEST` (HTTP 400) — plus `acuity` (`HIGH`, `MEDIUM`, or `LOW`), `admit_source` (`ED`, `DIRECT`, or `TRANSFER`), and `stay_type` (`INPATIENT` or `OBSERVATION`). When `admitted_at` is omitted it defaults to the logical clock at creation.

Every patient carries two independent state dimensions on one row. The admission axis, `admission_status`, begins at `ADMITTED` and ends at `DISCHARGED`. The observation axis, `observation_status`, begins at `OBS_ACTIVE` when `stay_type` is `OBSERVATION` and at `NONE` otherwise; `observation_started_at` equals `admitted_at` for observation patients and is null for inpatients. From `OBS_ACTIVE` there are two exits: a discharge carries the axis to `OBS_CLOSED` (terminal for the axis), and the operations checkpoint carries it to `OBS_CONVERTED`, flipping `stay_type` to `INPATIENT` in the same mutation, once the elapsed time since `observation_started_at` reaches at least 48.0 hours — equality converts, evaluated at second precision, so 47:59:59 elapsed does not convert while exactly 48:00:00 does. A patient whose axis is `NONE` keeps it through discharge untouched.

Length-of-stay monitoring refreshes three computed fields on every patient whose `admission_status` is `ADMITTED` each time the operations checkpoint runs; the refresh rewrites the fields and bumps the patient's `updated_at` and `version` on every run for every such patient, even when none of the three values change. `los_midnights` counts the UTC calendar dates strictly after the date of `admitted_at` and on or before the current date — a midnight-census view, so a patient admitted at 23:00 and measured the next day at 01:00 shows 1. `los_blocks` instead counts whole 24-hour blocks fully elapsed since `admitted_at` — the same 23:00-to-01:00 measurement yields 0. `los_alert_flag` turns true when `los_midnights` strictly exceeds the expected stay for the patient's current `stay_type` and `acuity` multiplied by 1.5 — equality is not an alert. Expected stays, in days: for `INPATIENT`, 6 at `HIGH`, 4 at `MEDIUM`, 2 at `LOW`; for `OBSERVATION`, 2 at `HIGH`, 2 at `MEDIUM`, 1 at `LOW`. The patient list filters by `admission_status`, by `stay_type`, and by `los_alert` to surface flagged outliers.

### 3.3. Admission Intake and the Distribution Selector

Admissions enter through a `GroupAdmin` queueing act that names only `patient_id`. The new row starts `QUEUED` with `offered_to_hospitalist_id` null, `declined_hospitalist_ids` empty, `distribution_score` null, and `assignment_id` null. When the referenced patient currently sits at `DISCHARGED`, queueing doubles as a readmission: `admission_status` flips back to `ADMITTED`, the observation axis resets to `NONE`, `stay_type` is left unchanged, `observation_started_at` is left unchanged, `admitted_at` is re-stamped to the readmission instant so every length-of-stay field anchors to the new stay, and the patient's `version` increments. The admission list supports reverse lookups by `patient_id`, `offered_to_hospitalist_id`, `assignment_id`, and `status`.

Immediately after the row is created — and again after every decline — the distribution selector runs. A hospitalist enters the candidate pool only when all of these hold: `employment_status` is `ACTIVE`; `distribution_eligible` is true; `current_census` is strictly below `max_census_cap`; the hospitalist owns a shift in state `ACTIVE` whose half-open interval covers the current logical time; the hospitalist's id does not appear in this admission's `declined_hospitalist_ids`; and no other admission in status `OFFERED` currently names this hospitalist as its target — one outstanding offer per hospitalist at a time.

Scoring rewards spare capacity and continuity while taxing night load. Start with the candidate's remaining-capacity fraction: `max_census_cap` minus `current_census`, divided by `max_census_cap`. Add a continuity bonus of 0.25 when the continuity predicate holds — that is, when a `CLOSED` assignment exists pairing this candidate with this patient whose `closed_at` lies within 30 days of now. Take the smaller of that sum and 1.0. Then subtract a night penalty of 0.10 when the candidate's covering shift is a `NIGHT` shift and the candidate's `pending_offers` is greater than zero. The result, rounded half up to four decimal places with comparisons made on the rounded value, becomes the admission's `distribution_score` for the winning candidate.

Candidates rank by score descending; ties break toward the lower `current_census`, then toward the candidate whose covering shift has the earlier `start_at`, then toward the candidate whose covering shift has the earlier `created_at` — never by hospitalist id. The winner moves the admission `QUEUED` → `OFFERED`: `offered_to_hospitalist_id` and `offered_at` are stamped, `distribution_score` records the winning score, the winner's `pending_offers` increments by one, and the admission's `version` increments. When the pool is empty the admission simply remains `QUEUED` with a null `offered_to_hospitalist_id` — a documented fallback, not an error — and waits for capacity, a shift change, or a decline elsewhere to change the picture.

Acceptance belongs to the offered hospitalist alone, and its checks fire in pipeline order. The admission must currently be `OFFERED`, else `ERR_ADMISSION_INVALID_STATE` (HTTP 409). The temporal tier then requires the offered hospitalist to hold an `ACTIVE` shift covering now, else `ERR_NO_ACTIVE_SHIFT` (HTTP 422). The cross-entity tier follows: the caller must equal `offered_to_hospitalist_id`, else `ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST` (HTTP 409); the patient must not already hold an `ACTIVE` assignment, else `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` (HTTP 409); and the offered hospitalist's `employment_status` must be `ACTIVE`, else `ERR_HOSPITALIST_NOT_ACTIVE` (HTTP 422). Capacity comes last: `current_census` strictly below `max_census_cap`, with equality rejecting as `ERR_CENSUS_CAP_REACHED` (HTTP 422).

A successful acceptance is a fan-out of effects in one mutation. A new assignment is born `ACTIVE` for the patient and the offered hospitalist, its `assigned_at` stamped and its `continuity_flag` set from the same 30-day continuity predicate the selector uses. The admission becomes terminally `ACCEPTED`, recording `assignment_id` and `decided_at`. The hospitalist's `pending_offers` decrements by one and `current_census` increments by one — and when that increment lands exactly on `max_census_cap`, the threshold trigger flips `distribution_eligible` to false. Both the admission's and the hospitalist's `version` increment.

Decline is the offered hospitalist's other move, guarded by the same state and target checks (`ERR_ADMISSION_INVALID_STATE`, then `ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST`). The caller's id is appended to `declined_hospitalist_ids`, `offered_to_hospitalist_id` and `distribution_score` are cleared (`offered_at` is not cleared; a later offer re-stamps it), the decliner's `pending_offers` decrements, and the admission returns `OFFERED` → `QUEUED` — at which point the selector immediately re-runs, excluding every decliner, so a `QUEUED` → `OFFERED` hop to the next candidate may land inside the very same request.

### 3.4. Assignment Lifecycle, Transfers, and Continuity of Care

An assignment binds one patient to one hospitalist. Alongside `patient_id` and `hospitalist_id` it carries `status`, the `continuity_flag` described by the selector's 30-day pairing predicate, `assigned_at`, a `closed_at` that stays null while the assignment is open, a `close_reason` of `DISCHARGE` or `TRANSFER` that likewise stays null while open, and `transfer_target_hospitalist_id`, populated only while a transfer is pending. Assignments list with reverse lookups by `patient_id`, `hospitalist_id`, `transfer_target_hospitalist_id`, and `status`.

A transfer begins when the current holder — or a `GroupAdmin` — initiates one, naming `target_hospitalist_id` and presenting `expected_assignment_version` per §2.6. The request-shape tier rejects a target equal to the current holder with `ERR_INVALID_REQUEST` (HTTP 400); the existence tier rejects an unknown target with `ERR_NOT_FOUND` (HTTP 404); the state tier then requires the assignment to be `ACTIVE`, else `ERR_ASSIGNMENT_INVALID_STATE` (HTTP 409), and compares the version, else `ERR_STALE_VERSION` (HTTP 412). Success moves the assignment `ACTIVE` → `PENDING_TRANSFER`, records the target, and increments the assignment's `version`.

The named target completes the handshake. Accepting requires the assignment to be `PENDING_TRANSFER` (else `ERR_ASSIGNMENT_INVALID_STATE`), then — at the temporal tier — a covering `ACTIVE` shift for the target, else `ERR_NO_ACTIVE_SHIFT`; then the cross-entity tier, where the caller must equal `transfer_target_hospitalist_id` (else `ERR_TRANSFER_TARGET_MISMATCH`, HTTP 409) and the target's employment must be `ACTIVE` (else `ERR_HOSPITALIST_NOT_ACTIVE`); and finally capacity, with the target's `current_census` strictly below their cap, equality rejecting as `ERR_CENSUS_CAP_REACHED`. The completion fans out: the pending assignment closes with `close_reason` `TRANSFER` and `closed_at` stamped; the source hospitalist's `current_census` decrements and their `distribution_eligible` recomputes — dropping below cap flips it back to true; a brand-new assignment springs up `ACTIVE` for the same patient and the target, with `continuity_flag` true exactly when a `CLOSED` assignment pairing this patient with this target closed within the 30-day window; the target's `current_census` increments and caps flips apply symmetrically; and the group-wide `ACTIVE` total is unchanged, one closed and one created, per the conservation invariant in §2.5. The assignment's `version` and both hospitalists' versions increment.

The holder or a `GroupAdmin` may also abandon a pending transfer: cancelling requires the assignment to be `PENDING_TRANSFER` (else `ERR_ASSIGNMENT_INVALID_STATE`), moves `PENDING_TRANSFER` → `ACTIVE` again, clears `transfer_target_hospitalist_id`, increments the assignment's `version`, and leaves both hospitalists' census fields untouched — the cycle that makes the transfer's optimistic-concurrency guard meaningful, since the status returns to `ACTIVE` while the version has moved.

The fourth transition is not user-driven at all: executing a discharge order closes the patient's `ACTIVE` assignment with `close_reason` `DISCHARGE`, as told in §3.5.

Census balance is measured, not just enforced, through a census-leveling report computed on read at the logical clock. Its evaluation order is pinned. First, each hospitalist's current census is the count of their `ACTIVE` assignments. Second, the eligible set is the hospitalists whose `employment_status` is `ACTIVE` and who hold an `ACTIVE` shift covering now; `group_avg_census` is the sum of current census across that set divided by the larger of 1 and the set's size — computed from current census only, never from projections. Third, each eligible hospitalist's projected census adds their outstanding offers — admissions in status `OFFERED` naming them — to current census, and subtracts their impending discharges: orders in status `PLANNED` or `ORDERED` whose patient sits on one of their `ACTIVE` assignments and whose `target_discharge_at` falls at or before the instant 24 hours from now — an already-past target still counts, the horizon bounding only the future side. Fourth, each deviation is the projected census minus `group_avg_census`, divided by the larger of 1 and `group_avg_census`, rounded half up to four decimals. `leveling_needed` is true when the largest absolute deviation across the group exceeds 0.15.

Each row of the report's `rows` array — one per eligible hospitalist, in hospitalist creation order — carries `hospitalist_id`, `current_census`, `projected_census`, and two variants side by side: `deviation_forward`, computed on the projected census, and `deviation_chronological`, computed on the raw current census — identical inputs yield different values whenever outstanding offers or horizon-window discharge orders exist, which is precisely the signal the forward-looking variant adds. The report envelope returns `generated_at`, `group_avg_census`, `leveling_needed`, and `rows`. The report carries no separate discharge-throughput aggregate; the throughput signal of §3.5 lives on each order's `meets_throughput_target`.

### 3.5. Discharge Planning and the Morning Throughput Target

A discharge order begins as a plan. The hospitalist holding the patient's `ACTIVE` assignment creates it under the patient — a caller without that assignment fails ownership with `ERR_UNAUTHORIZED_ROLE` (HTTP 403), and a patient whose `admission_status` is not `ADMITTED` fails with `ERR_PATIENT_NOT_ADMITTED` (HTTP 409). The request names `target_discharge_at`, the planned discharge instant; the row is born `PLANNED`, with `patient_id` taken from the path and `ordering_hospitalist_id` fixed to the caller. Orders list by `patient_id`, `ordering_hospitalist_id`, and `status`.

Ordering moves `PLANNED` → `ORDERED`, stamps `ordered_at`, and increments the order's `version`; only the ordering hospitalist may do it (`ERR_UNAUTHORIZED_ROLE` otherwise), and only from `PLANNED` (else `ERR_DISCHARGE_ORDER_INVALID_STATE`, HTTP 409). Execution moves `ORDERED` → `EXECUTED` under the same ownership rule and only from `ORDERED` (else `ERR_DISCHARGE_ORDER_INVALID_STATE`), plus two further gates: the patient must still be `ADMITTED` (else `ERR_PATIENT_NOT_ADMITTED`), and — at the safety tier, after state checks — no `STAT`-priority consult for this patient may sit in `OPEN`, `ESCALATED`, `ACKNOWLEDGED`, or `REOPENED`, else `ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE` (HTTP 422). A `STAT` consult that has reached `COMPLETED` or `CLOSED` does not block; lower priorities never do.

Execution is the widest cascade in the system, all in one mutation. `executed_at` is stamped and `meets_throughput_target` is computed: true when `executed_at` falls at or before 11:00:00Z on the calendar date of `target_discharge_at` — equality meets the target, compared at millisecond precision — and null at all times before execution. The patient flips `ADMITTED` → `DISCHARGED`, and the observation axis moves `OBS_ACTIVE` → `OBS_CLOSED` in the same stroke while `NONE` stays `NONE`. The patient's `ACTIVE` assignment closes with `close_reason` `DISCHARGE` and `closed_at` stamped; the responsible hospitalist's `current_census` decrements by one and `distribution_eligible` recomputes; and the group-wide active total drops by exactly one, in step with the patient's discharge, per the conservation invariant. The versions of the discharge order, the patient, the assignment, and the hospitalist each increment by one.

### 3.6. Shift Handoffs and Signout Completeness

At shift change the outgoing hospitalist — the owner of the shift being signed out — drafts a handoff under that shift, naming `receiving_hospitalist_id` and the `patient_ids` the signout covers; authorship by anyone but the shift's owner fails ownership with `ERR_UNAUTHORIZED_ROLE`. `patient_ids` is shape-checked only (an array of strings): its entries are not individually existence-checked, and ids not naming a patient on the author's `ACTIVE` assignments are simply ignored by the completeness arithmetic. The draft is born `DRAFT` with its completeness fields computed, and handoffs list by `shift_id`, `receiving_hospitalist_id`, and `status`.

Completeness is arithmetic over the outgoing hospitalist's open book. At submit time the server takes the set of patients on that hospitalist's `ACTIVE` assignments: `required_patient_count` is its size; `covered_patient_count` counts how many of those patients appear in `patient_ids`; `open_item_count` is the difference; `completeness_score` is the covered count divided by the required count, rounded half up to four decimals — and defined as 1.0 when the required count is zero, so a hospitalist with no open assignments submits a complete signout trivially.

While the handoff sits in `DRAFT` or `RETURNED`, the author may revise it — replacing `patient_ids` (again shape-checked only) or `receiving_hospitalist_id`, recomputing the counts, leaving the state untouched, and incrementing `version`. Revision from any other state fails with `ERR_HANDOFF_INVALID_STATE` (HTTP 409), and every revision must present `expected_handoff_version` per §2.6, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412).

Submission moves `DRAFT` → `SUBMITTED` — or, on a later cycle, `RETURNED` → `SUBMITTED` — and is gated on coverage: `open_item_count` must be zero, meaning `patient_ids` cover every `ACTIVE` assignment of the shift's hospitalist, else `ERR_HANDOFF_INCOMPLETE` (HTTP 422). A submission from a state other than `DRAFT` or `RETURNED` fails with `ERR_HANDOFF_INVALID_STATE`. Submitting recomputes all four completeness fields at that instant, stamps `submitted_at` with the latest submission, and increments `version`.

Review belongs to the receiver. Acceptance requires the handoff to be `SUBMITTED` (else `ERR_HANDOFF_INVALID_STATE`), requires the caller to equal `receiving_hospitalist_id` (else `ERR_UNAUTHORIZED_ROLE`, HTTP 403), and — at the safety tier, after the state check — forbids the shift's own owner from accepting their own signout, `ERR_HANDOFF_SELF_ACCEPT` (HTTP 409). Acceptance moves `SUBMITTED` → `ACCEPTED`, terminal, stamping `reviewed_at` and incrementing `version`; it also makes the outgoing shift closable, satisfying the shift-close precondition of §3.1. Returning instead moves `SUBMITTED` → `RETURNED` under the same receiver checks and the same state gate — a return from anything but `SUBMITTED` fails with `ERR_HANDOFF_INVALID_STATE` — storing the required `return_reason` on the handoff and incrementing `version`, after which the author revises and resubmits, and the cycle repeats.

### 3.7. Consult Requests and Response-Time Agreements

A hospitalist requests a consult under one of their own patients: the caller must hold the patient's `ACTIVE` assignment (ownership, else `ERR_UNAUTHORIZED_ROLE`), the patient must be `ADMITTED` (else `ERR_PATIENT_NOT_ADMITTED`), and the request carries `specialty` — one of `CARDIOLOGY`, `NEUROLOGY`, `SURGERY`, `INFECTIOUS_DISEASE`, `NEPHROLOGY` — plus `priority` (`STAT`, `URGENT`, or `ROUTINE`) and a free-text `reason`, the clinical question. The request is born `OPEN`; `requesting_hospitalist_id` is fixed to the caller, `requested_at` is stamped, `escalation_count` starts at zero, and `sla_breached` starts false. Consults list by `patient_id`, `requesting_hospitalist_id`, `status`, and `priority`.

The service-level clock starts at creation. `sla_deadline` is `requested_at` plus fifteen minutes for `STAT`, thirty for `URGENT`, or two hours for `ROUTINE`, and it is never recomputed — a reopen leaves the original deadline governing. Acknowledgement is the `ConsultingSpecialist`'s first move and is legal from `OPEN`, from `ESCALATED`, or from `REOPENED` alike — any other state fails with `ERR_CONSULT_INVALID_STATE` (HTTP 409). Each acknowledge stamps `acknowledged_at`, increments `version`, and evaluates `sla_breached`: true when `acknowledged_at` is strictly later than `sla_deadline`, with equality not a breach, compared at millisecond precision. An acknowledge out of `REOPENED` plays by the same rule against the unchanged original deadline.

Completion moves `ACKNOWLEDGED` → `COMPLETED` — from no other state, else `ERR_CONSULT_INVALID_STATE` — accepting an optional `summary` (accepted but not persisted; the consult carries no summary field), stamping `completed_at`, and computing `response_minutes` as the elapsed minutes from `requested_at` to `completed_at`, rounded half up to two decimals and null until completion exists.

Reopening belongs to the requesting hospitalist and only within a 24-hour window: the consult must be `COMPLETED` (else `ERR_CONSULT_INVALID_STATE`), and the current logical time must fall at or before `completed_at` plus 24 hours, else `ERR_CONSULT_REOPEN_WINDOW_EXPIRED` (HTTP 422). The request may carry an optional `reason` (accepted but not persisted); success moves `COMPLETED` → `REOPENED` and increments `version`, after which the acknowledge-and-complete cycle runs again.

The operations checkpoint supplies the two time-driven moves. Any consult still `OPEN` with the logical clock strictly past `sla_deadline` escalates — `OPEN` → `ESCALATED`, `escalation_count` incrementing by one, `version` incrementing. Any consult `COMPLETED` with the clock strictly past `completed_at` plus 24 hours auto-closes — `COMPLETED` → `CLOSED`, terminal, `version` incrementing.

### 3.8. Encounters, Productivity Reports, and wRVU Accounting

Rounds become revenue through encounters. The recording hospitalist — `hospitalist_id` is fixed to the caller — submits `patient_id`, an `encounter_type` of `ADMISSION_HCP`, `SUBSEQUENT_VISIT`, `DISCHARGE_DAY`, or `CONSULT_NOTE`, the service date `occurred_on` in YYYY-MM-DD form, and `wrvu_value`, the actual billed work RVU. At creation the server computes `estimated_wrvu`: the encounter type's standard estimate — 2.5 for `ADMISSION_HCP`, 1.2 for `SUBSEQUENT_VISIT`, 1.8 for `DISCHARGE_DAY`, 1.5 for `CONSULT_NOTE` — multiplied by the adjustment factor 1.06, the product rounded half up to two decimals, per line, and stored on the encounter. Encounters are born `RECORDED` and list by `hospitalist_id`, `patient_id`, `productivity_report_id`, and `status`.

Voiding moves `RECORDED` → `VOIDED`, terminal, and may be done by the owning hospitalist or a `GroupAdmin`; voiding an already-`VOIDED` encounter fails with `ERR_ENCOUNTER_ALREADY_VOIDED` (HTTP 409). The void ripples into any linked report: when `productivity_report_id` names a `FINALIZED` report, the report drops `FINALIZED` → `REOPENED` and its totals recompute excluding the voided line, with the report's `version` incrementing alongside the encounter's; when the linked report is `PROVISIONAL` or `REOPENED`, the totals likewise recompute but the status holds — with the caveat that outside finalization `total_wrvu_final` and `wrvu_variance` are recomputed only once a first finalize has set them, so on a never-finalized `PROVISIONAL` report they remain null through such recomputation.

Reporting itself is a `GroupAdmin` function. Generating a report names `hospitalist_id` and the inclusive period bounds `period_start` and `period_end` (YYYY-MM-DD); the report is born `PROVISIONAL`, links every `RECORDED` encounter of that hospitalist whose `occurred_on` falls inside the period by stamping their `productivity_report_id`, and computes its provisional view: `encounter_count`, the size of the linked set, and `total_wrvu_provisional`, the sum of the per-line `estimated_wrvu` values — per-line rounding first, summation second. `generated_at` is stamped; `total_wrvu_final` and `wrvu_variance` remain null until the first finalize. Reports list by `hospitalist_id` and `status`.

Finalization moves `PROVISIONAL` → `FINALIZED` — or, after a reopen, `REOPENED` → `FINALIZED` — and from any other state fails with `ERR_REPORT_INVALID_STATE` (HTTP 409). The final variant follows the opposite rounding discipline: the raw `wrvu_value` figures across the linked `RECORDED` set are summed first and the total is rounded once, half up to two decimals, yielding `total_wrvu_final`; `wrvu_variance` is that final total minus the provisional total, again at two decimals. Identical encounter sets generally produce a different final than provisional total — the pinned rounding orders are the whole point. Finalizing also re-links the set: on a `REOPENED` → `FINALIZED` pass, every currently `RECORDED` in-period encounter is linked, including any recorded after the first finalize, and `finalized_at` stamps the latest finalization. `FINALIZED` is a soft terminal, not an end state.

A `GroupAdmin` may reopen a finalized report manually — `FINALIZED` → `REOPENED` only, with any other source state failing as `ERR_REPORT_INVALID_STATE` (HTTP 409); totals recompute over the hospitalist's currently `RECORDED` in-period encounters (the same set a refinalize would link, whether or not each line is currently linked) and `version` increments — joining the void-induced reopen of the encounter flow. Across the full compensating sequence one conservation property holds: for a `FINALIZED` report, voiding an encounter, re-recording an identical one (same `encounter_type`, `occurred_on`, and `wrvu_value`), and refinalizing leaves both `total_wrvu_final` and `total_wrvu_provisional` equal to their pre-void values.

### 3.9. Night Coverage Windows and Cross-Cover Load

Night staffing runs through coverage windows. A `GroupAdmin` creates one with `window_date` (the YYYY-MM-DD service date), a `window_type` of `NIGHT_PRIMARY` or `NIGHT_CROSS_COVER` — cross-cover carrying double load weight, as below — the half-open bounds `start_at` and `end_at` with the end strictly after the start (a violation rejected at the request-shape tier with `ERR_INVALID_REQUEST`, HTTP 400), and `capacity`, the maximum enrolled hospitalists, at least 1. The window is born `OPEN` with `enrolled_hospitalist_ids` an empty ordered list, `enrolled_count` zero, and `current_load` zero; windows list by `window_type` and `status`.

Enrollment is self-service: the calling hospitalist adds themself, and the checks run in pipeline order. A window in `LOCKED` or `CLOSED` rejects at the state tier with `ERR_COVERAGE_WINDOW_NOT_OPEN` (HTTP 409). The temporal tier then rejects a caller who owns a non-`CLOSED` shift whose half-open interval overlaps the window's with `ERR_ENROLL_SHIFT_CONFLICT` (HTTP 409), adjacency permitted. The cross-entity tier rejects a caller already present in `enrolled_hospitalist_ids` with `ERR_ALREADY_ENROLLED` (HTTP 409). Capacity, as always, comes last: a window at `enrolled_count` equal to `capacity` — status `FULL` — rejects with `ERR_COVERAGE_WINDOW_FULL` (HTTP 422). A successful enrollment appends the caller to `enrolled_hospitalist_ids` in enrollment order, increments `enrolled_count`, and flips the window `OPEN` → `FULL` the moment the count reaches capacity.

Withdrawal is equally self-service while the window remains `OPEN` or `FULL`: the caller is removed from `enrolled_hospitalist_ids`, `enrolled_count` decrements, and a `FULL` window relaxes back to `OPEN`. A caller not present in `enrolled_hospitalist_ids` succeeds idempotently — the window is returned unchanged, with no `version` increment. From `LOCKED` or `CLOSED`, withdrawal meets the same `ERR_COVERAGE_WINDOW_NOT_OPEN` as enrollment.

The operations checkpoint drives the window's time boundaries: a window in `OPEN` or `FULL` locks — moving to `LOCKED` — once the logical clock reaches `start_at`, and a `LOCKED` window closes — `CLOSED`, terminal — once the clock reaches `end_at`. A window whose `start_at` and `end_at` have both passed by evaluation time locks and closes within the same run, appearing in both `locked_window_ids` and `closed_window_ids`. While a window is `LOCKED`, each checkpoint also recomputes its `current_load`: take the group-wide count of `ACTIVE` assignments, weighted double for a `NIGHT_CROSS_COVER` window and single for `NIGHT_PRIMARY`; add the group-wide count of consults in `OPEN` or `ESCALATED` at one point each; add the group-wide count of handoffs in `SUBMITTED` at two points each; round half up to two decimals; and clamp the result at a maximum of 40, the clamp applied last.

## 4. Endpoint Definitions

All endpoints speak the envelope of §2.2 and the pagination of §2.3. Resource creation returns HTTP 201; reads and every modification — including state transitions, revisions, and the operations checkpoint — return HTTP 200. Request bodies, side effects, and computed fields are specified in the narratives of §2 and §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /hospitalists | Create a hospitalist | GroupAdmin |
| GET | /hospitalists | List hospitalists, filterable by employment status | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /hospitalists/{id} | Read one hospitalist including computed census fields | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /patients | Register an admitted patient; an OBSERVATION stay initializes the observation axis | GroupAdmin |
| GET | /patients | List patients, filterable | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /patients/{id} | Read one patient | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /shifts | Schedule a shift; half-open overlap rejected, adjacency allowed | GroupAdmin |
| GET | /shifts | List shifts, with reverse lookup by owning hospitalist | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /shifts/{id} | Read one shift | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /shifts/{id}/activate | Move a shift SCHEDULED to ACTIVE | GroupAdmin, Hospitalist |
| POST | /shifts/{id}/close | Move a shift ACTIVE to CLOSED; requires an accepted handoff | GroupAdmin, Hospitalist |
| POST | /admissions | Queue an admission; the selector runs immediately; readmits a discharged patient | GroupAdmin |
| GET | /admissions | List admissions, with reverse lookups | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /admissions/{id} | Read one admission | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /admissions/{id}/accept | Offered hospitalist accepts; creates the active assignment | Hospitalist |
| POST | /admissions/{id}/decline | Offered hospitalist declines; requeues and re-runs the selector | Hospitalist |
| GET | /assignments | List assignments, with reverse lookups | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /assignments/{id} | Read one assignment | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /assignments/{id}/transfer | Move ACTIVE to PENDING_TRANSFER toward a target; OCC-guarded | Hospitalist, GroupAdmin |
| POST | /assignments/{id}/accept-transfer | Target accepts; source closes as TRANSFER and a successor assignment activates | Hospitalist |
| POST | /assignments/{id}/cancel-transfer | Abandon a pending transfer, returning to ACTIVE | Hospitalist, GroupAdmin |
| POST | /patients/{patient_id}/discharge-orders | Create a planned discharge order for the patient | Hospitalist |
| GET | /discharge-orders | List discharge orders, with reverse lookups | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /discharge-orders/{id} | Read one discharge order | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /discharge-orders/{id}/order | Move PLANNED to ORDERED | Hospitalist |
| POST | /discharge-orders/{id}/execute | Move ORDERED to EXECUTED; cascades discharge, assignment closure, census recompute | Hospitalist |
| POST | /shifts/{shift_id}/handoffs | Draft a signout handoff for the outgoing shift | Hospitalist |
| GET | /handoffs | List handoffs, with reverse lookups | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /handoffs/{id} | Read one handoff | GroupAdmin, Hospitalist, ConsultingSpecialist |
| PUT | /handoffs/{id} | Revise a DRAFT or RETURNED handoff; OCC-guarded; no state change | Hospitalist |
| POST | /handoffs/{id}/submit | Submit a DRAFT or RETURNED handoff; requires complete coverage | Hospitalist |
| POST | /handoffs/{id}/accept | Receiving hospitalist accepts a submitted handoff | Hospitalist |
| POST | /handoffs/{id}/return | Receiving hospitalist returns a submitted handoff with a reason | Hospitalist |
| POST | /patients/{patient_id}/consult-requests | Open a consult request for the patient | Hospitalist |
| GET | /consult-requests | List consult requests, with reverse lookups | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /consult-requests/{id} | Read one consult request | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /consult-requests/{id}/acknowledge | Specialist acknowledges; evaluates the SLA breach flag | ConsultingSpecialist |
| POST | /consult-requests/{id}/complete | Specialist completes an acknowledged consult | ConsultingSpecialist |
| POST | /consult-requests/{id}/reopen | Requesting hospitalist reopens within the reopen window | Hospitalist |
| POST | /encounters | Record a billable encounter for the calling hospitalist | Hospitalist |
| GET | /encounters | List encounters, with reverse lookups | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /encounters/{id} | Read one encounter | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /encounters/{id}/void | Void a recorded encounter; may reopen a finalized report | Hospitalist, GroupAdmin |
| POST | /productivity-reports/generate | Generate a provisional productivity report for a hospitalist and period | GroupAdmin |
| GET | /productivity-reports | List productivity reports | GroupAdmin, Hospitalist |
| GET | /productivity-reports/{id} | Read one productivity report | GroupAdmin, Hospitalist |
| POST | /productivity-reports/{id}/finalize | Finalize a provisional or reopened report; computes final totals | GroupAdmin |
| POST | /productivity-reports/{id}/reopen | Reopen a finalized report; totals recompute | GroupAdmin |
| POST | /coverage-windows | Create a night coverage or cross-cover window with a capacity pool | GroupAdmin |
| GET | /coverage-windows | List coverage windows | GroupAdmin, Hospitalist, ConsultingSpecialist |
| GET | /coverage-windows/{id} | Read one window including roster and load | GroupAdmin, Hospitalist, ConsultingSpecialist |
| POST | /coverage-windows/{id}/enroll | Calling hospitalist enrolls in the window | Hospitalist |
| POST | /coverage-windows/{id}/withdraw | Calling hospitalist withdraws while the window is open | Hospitalist |
| POST | /ops/monitor-run | Operations checkpoint at the logical clock: conversions, escalations, closures, locks, refreshes | GroupAdmin |
| GET | /reports/census-leveling | Computed census-leveling report with forward and chronological deviations | GroupAdmin, Hospitalist |
| POST | /_clock/set_current_utc | Set the logical clock | GroupAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_ADMISSION_INVALID_STATE | 409 |
| ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST | 409 |
| ERR_ASSIGNMENT_INVALID_STATE | 409 |
| ERR_TRANSFER_TARGET_MISMATCH | 409 |
| ERR_DISCHARGE_ORDER_INVALID_STATE | 409 |
| ERR_HANDOFF_INVALID_STATE | 409 |
| ERR_HANDOFF_SELF_ACCEPT | 409 |
| ERR_HANDOFF_INCOMPLETE | 422 |
| ERR_SHIFT_HANDOFF_MISSING | 409 |
| ERR_SHIFT_INVALID_STATE | 409 |
| ERR_CONSULT_INVALID_STATE | 409 |
| ERR_CONSULT_REOPEN_WINDOW_EXPIRED | 422 |
| ERR_PATIENT_NOT_ADMITTED | 409 |
| ERR_CENSUS_CAP_REACHED | 422 |
| ERR_NO_ACTIVE_SHIFT | 422 |
| ERR_HOSPITALIST_NOT_ACTIVE | 422 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_SHIFT_INVALID_WINDOW | 422 |
| ERR_COVERAGE_WINDOW_FULL | 422 |
| ERR_ALREADY_ENROLLED | 409 |
| ERR_COVERAGE_WINDOW_NOT_OPEN | 409 |
| ERR_ENROLL_SHIFT_CONFLICT | 409 |
| ERR_REPORT_INVALID_STATE | 409 |
| ERR_ENCOUNTER_ALREADY_VOIDED | 409 |
| ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE | 422 |
| ERR_DUPLICATE_ACTIVE_ASSIGNMENT | 409 |

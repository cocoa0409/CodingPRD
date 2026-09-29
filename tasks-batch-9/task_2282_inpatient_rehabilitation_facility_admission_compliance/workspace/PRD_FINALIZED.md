# IRF Admission & Compliance API — Product Requirements Document

## 1. Introduction

An inpatient rehabilitation facility (IRF) lives or dies by the paper trail behind every stay. Before a patient may be admitted, a nurse or physician must screen them inside a narrow pre-admission window and a rehabilitation physician must concur; once admitted, the patient must receive an intensive therapy programme that is documented minute by minute; every week of the stay must be reviewed by an interdisciplinary team; and at discharge the facility must complete and transmit an assessment instrument inside a statutory deadline. On top of the individual case sits a population-level test: a sufficient percentage of the facility's discharged cohort must qualify as genuine rehabilitation cases, or the facility loses its IRF designation and is paid as an ordinary acute hospital.

This API is the system of record for that machinery. It tracks each stay's documentation state independently of its clinical state and its payment state, so that a stay can be clinically discharged, fiscally reopened and documentarily incomplete at the same instant without the three notions interfering. It continuously recomputes a provisional compliance percentage over the facility's own review period and translates the result into an operational posture that can throttle or halt further admissions before a formal review is ever opened. It prices each stay through a waterfall that consolidates interrupted stays into a single payment, applies a short-stay reduction, caps transfer cases at a per-diem equivalent and finally applies whatever quality-reporting penalty was in force on the day the patient was admitted — not the day the bill was cut.

Two design commitments run through everything that follows. First, **time is explicit**: every deadline, window and expiry is measured against a server-held logical UTC clock that operators advance deliberately, so that lateness and expiry are reproducible rather than incidental. Second, **duties are segregated**: the clinician who screens may not concur, the coder who completes an assessment may not transmit it, and the officer who opens a compliance review may not certify it. Implementations that collapse either commitment will pass individual happy paths and fail the audit trail the product exists to produce.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts and cross-cutting principles that hold for every endpoint in the system. All resources are mounted at the top level of the API — there are no nested collection paths — and parentage between resources is carried entirely by identifier fields in request bodies.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the five recognised role names, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well formed but the declared role is not authorised for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE`.

The five roles are `ComplianceOfficer`, `NurseCaseManager`, `RehabPhysician`, `TherapyLead`, and `HimCoder`.

- A `ComplianceOfficer` is the facility compliance and reimbursement operator. They register facilities and clinicians, deactivate clinicians, correct interrupted-stay linkage, open, compute and certify compliance reviews, score the quality reporting programme, and control the logical clock.
- A `NurseCaseManager` owns patient medical records, preadmission screenings, the admission and discharge events, and the weekly team conference record.
- A `RehabPhysician` reviews preadmission screenings, denies unsuitable admissions, signs the overall plan of care, and grants documented three-hour-rule exceptions.
- A `TherapyLead` opens therapy measurement weeks, schedules and documents therapy sessions, voids erroneous sessions, and evaluates the three-hour rule.
- A `HimCoder` opens, completes and transmits IRF patient assessment instruments.

All read endpoints are available to all five roles. Write endpoints are restricted as shown in §4.

**Acting identity.** When `X-User-Role` is `NurseCaseManager`, `RehabPhysician`, `TherapyLead`, or `HimCoder`, `X-User-ID` is the `id` of the acting `Clinician` record; ownership and duty checks on any resource that references a clinician compare that resource's clinician identifier field to `X-User-ID`. For those four clinician-backed roles two additional gates apply before any business rule is evaluated. First, the clinician the header resolves to must hold the credential that matches the asserted role: `RehabPhysician` requires credential `REHAB_PHYSICIAN`, `NurseCaseManager` requires `NURSE`, `TherapyLead` requires any of `THERAPIST_PT`, `THERAPIST_OT` or `THERAPIST_SLP`, and `HimCoder` requires `CODER`; a mismatch is `ERR_ROLE_CREDENTIAL_MISMATCH`. Second, that clinician's `status` must be `ACTIVE`; an acting clinician whose status is `INACTIVE` is refused with `ERR_ACTING_CLINICIAN_INACTIVE`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands it — as `created_by_user_id` and `certified_by_user_id` on a compliance review — but never compares it to any entity's `id`, and neither the credential nor the active-status gate applies to it.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is read from real wall-clock time and is deliberately independent of the logical clock of §2.4: only domain instants stored on resources come from the logical clock, while this envelope field records when the request was actually served.
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

List endpoints accept two query parameters. `limit` is the maximum number of records to return; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` is the number of records to skip before the first returned record; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the filters before pagination is applied and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in this system — facilities, clinicians, patients, screenings, admissions, plans of care, therapy weeks, therapy sessions, team conferences, assessment instruments, compliance reviews and QRP assessments alike — carries the same four system-managed properties:

- **`id`** (string): a server-minted UUID. No type prefix or other decoration is applied.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits (for example `2026-08-01T00:00:00.000Z`) recording when the record was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp, in the same format, recording the last modification. A recomputation that actually moves a derived field counts as a modification; a recomputation that lands on the value the field already held does not (§2.11).
- **`version`** (integer): starts at 1 on creation and increases by exactly 1 on every mutation of the resource, including mutations the server performs on its own initiative as part of a cascade.

There is no resource in this system that omits `updated_at` or `version`.

**The logical clock.** All server-stamped instants — a screening's `conducted_at`, a plan's `signed_at`, a session's `documented_at`, an assessment's `completed_at` and `transmitted_at`, a review's `computed_at` and `certified_at`, a QRP assessment's `finalized_at` — are read from a single server-held logical UTC clock, never from wall-clock time. Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `ComplianceOfficer` moves it by supplying a `to_iso8601` instant to the clock-setting capability described in §4; the response reports the resulting `current_utc` together with `expired_screening_count` and `missed_assessment_count`, the number of records swept into a terminal state by that movement. Two sweeps run on every clock movement and are described in §3.2 and §3.9.

### 2.5. Order of Rejection: the Validation Ladder

Many endpoints are guarded by several checks at once, and the *first* failure decides the response. Implementations must evaluate checks in the following fixed order, so that an early failure masks every later one; a request that violates three rules reports only the highest-ranked violation.

1. **Header presence and role recognition** — `ERR_UNAUTHENTICATED` (401), on every endpoint.
2. **Role authorisation for the endpoint** — `ERR_FORBIDDEN_ROLE` (403), on every endpoint.
3. **Credential match for clinician-backed roles** — `ERR_ROLE_CREDENTIAL_MISMATCH` (403), on every endpoint whose authorised roles include a clinician-backed role.
4. **Acting clinician is `ACTIVE`** — `ERR_ACTING_CLINICIAN_INACTIVE` (403), on the same set of endpoints.
5. **Request shape** — required body fields present; enum values recognised; timestamps ISO 8601 UTC; dates written as `YYYY-MM-DD`; `end_at` later than `start_at`; a period's end not earlier than its start; `limit` within 1 through 100 and `offset` not negative; `discharged_at` not later than the logical clock. Any violation is `ERR_INVALID_REQUEST` (400), on every endpoint. Two of those shape facts are claimed by a more specific rank below, and there the specific error wins so that it stays reachable: the `end_at`-after-`start_at` fact belongs to rank 6 on session scheduling (the only endpoint that carries `start_at` and `end_at`), and the period-ordering fact belongs to rank 8 on facility registration, compliance-review opening and QRP-assessment opening (the only endpoints that carry a period). A value that is not a well-formed timestamp or date at all is still `ERR_INVALID_REQUEST` at this rank on those endpoints.
6. **Session interval sanity** — on session scheduling only: `end_at` strictly later than `start_at` and the resulting whole-minute duration at least 1, else `ERR_INVALID_SESSION_INTERVAL` (400).
7. **Modality and group size coherence** — on session scheduling only, else `ERR_GROUP_SIZE_INVALID` (400).
8. **Period ordering** — on facility registration, compliance-review opening and QRP-assessment opening: the period's end date must not be earlier than its start date, else `ERR_INVALID_PERIOD` (400).
9. **Path identifiers exist**, validated left to right — `ERR_NOT_FOUND` (404), on every endpoint carrying identifiers in its path.
10. **Body identifiers exist** — every `facility_id`, `patient_id`, `screening_id`, `admission_id`, `clinician_id`, `therapy_week_id`, `coder_clinician_id`, `led_by_clinician_id`, member of `participant_clinician_ids`, and `predecessor_admission_id` supplied in a body must resolve to an existing record, else `ERR_NOT_FOUND` (404).
11. **Screening/predecessor patient coherence** — on admission opening and on admit, else `ERR_SCREENING_PATIENT_MISMATCH` (409). This rank owns only the patient-identity comparison; week-to-admission coherence belongs to rank 12 alone.
12. **Therapy-week to admission coherence** — on team-conference recording: the supplied `therapy_week_id` must belong to the same `admission_id`, else `ERR_WEEK_ADMISSION_MISMATCH` (409).
13. **Facility boundary** — on screening creation, session scheduling, team-conference recording, assessment opening and plan-of-care signing, every referenced clinician and patient must belong to the same facility as the target resource, else `ERR_CROSS_FACILITY_MISMATCH` (409).
14. **Segregation of duties** — on screening review, assessment transmission and review certification, else `ERR_SEGREGATION_OF_DUTIES` (403). See §2.9.
15. **Version pinning** — on plan-of-care signing and compliance-review opening, else the corresponding stale-version rejection at 412. See §2.7.
16. **Declared transition** — the target resource must currently be in a state from which the requested transition is declared, else `ERR_INVALID_STATE` (409), on every transition endpoint.
17. **Admission is `ADMITTED`** — required by plan-of-care signing, therapy-week opening, session scheduling, session delivery and team-conference recording, else `ERR_ADMISSION_NOT_ACTIVE` (409).
18. **Admission is `DISCHARGED`** — required by assessment opening (for a `DISCHARGE` assessment) and by assessment transmission, else `ERR_ADMISSION_NOT_DISCHARGED` (409).
19. **Exception eligibility** — a three-hour-rule exception requires the week to be `NOT_MET`, else `ERR_EXCEPTION_NOT_ALLOWED` (409).
20. **Interruption present** — rescinding an interruption requires `interrupted_stay_flag` to be true, else `ERR_NOT_INTERRUPTED_STAY` (409).
21. **Admission gate** — admitting requires the facility's `posture` to be `OPEN` or `THRESHOLD_WATCH`, else `ERR_FACILITY_ADMISSION_FROZEN` (403).
22. **Concurred screening** — on admission opening and on admit, else `ERR_SCREENING_NOT_CONCURRED` (422).
23. **Screening window** — on admit, else `ERR_SCREENING_WINDOW_EXPIRED` (422).
24. **Screening documentation completeness** — on screening submission, else `ERR_SCREENING_DOCUMENTATION_INCOMPLETE` (422).
25. **Screener credential** — on screening creation, else `ERR_SCREENER_CREDENTIAL_INVALID` (422).
26. **Active plan of care exists** — on therapy-week opening, session scheduling and week evaluation, else `ERR_PLAN_OF_CARE_MISSING` (422).
27. **Discipline is in the plan** — on session scheduling, else `ERR_DISCIPLINE_NOT_IN_PLAN` (422).
28. **Treating clinician's credential matches the discipline** — on session scheduling, else `ERR_CLINICIAN_DISCIPLINE_MISMATCH` (422).
29. **Conference lead is a rehabilitation physician** — on team-conference recording, else `ERR_CONFERENCE_LEAD_NOT_PHYSICIAN` (422).
30. **Conference participation is complete** — on team-conference recording, else `ERR_CONFERENCE_PARTICIPANTS_INCOMPLETE` (422).
31. **Item set attested** — on assessment completion, else `ERR_PAI_ITEM_SET_INCOMPLETE` (422).
32. **Treating clinician not double-booked** — on session scheduling, else `ERR_CLINICIAN_SCHEDULE_CONFLICT` (409).
33. **Patient rest buffer** — on session scheduling, else `ERR_PATIENT_REST_BUFFER_VIOLATION` (409).
34. **Session lands in a week window** — on session scheduling, else `ERR_NO_OPEN_THERAPY_WEEK` (422).
35. **Week windows do not overlap** — on therapy-week opening, else `ERR_THERAPY_WEEK_OVERLAP` (409).
36. **Week not before admission** — on therapy-week opening, else `ERR_WEEK_BEFORE_ADMISSION` (422).
37. **Conference held inside the week** — on team-conference recording, else `ERR_CONFERENCE_OUTSIDE_WEEK` (409).
38. **One recorded conference per week** — on team-conference recording, else `ERR_CONFERENCE_ALREADY_RECORDED` (409).
39. **Week index unique per admission** — on therapy-week opening, else `ERR_WEEK_INDEX_DUPLICATE` (409).
40. **Medical record number and provider number uniqueness** — on patient registration and clinician registration, else `ERR_MRN_DUPLICATE` (409).
41. **Certification number uniqueness** — on facility registration, else `ERR_CCN_DUPLICATE` (409).
42. **One live assessment per type** — on assessment opening, else `ERR_ASSESSMENT_TYPE_DUPLICATE` (409).
43. **Interrupted-stay linkage window** — on admit, else `ERR_INTERRUPTION_WINDOW_EXCEEDED` (422). This rank owns only the predecessor's discharge state and gap; duplicate continuations belong to rank 44 alone.
44. **Predecessor not already continued** — on admit, else `ERR_PREDECESSOR_ALREADY_CONTINUED` (409).
45. **Linkage required when a recent discharge exists** — on admit, else `ERR_INTERRUPTED_STAY_LINK_REQUIRED` (422).
46. **Daily therapy cap** — on session scheduling, else `ERR_DAILY_THERAPY_CAP_EXCEEDED` (409).
47. **Non-empty compliance cohort** — on review computation, else `ERR_EMPTY_COMPLIANCE_COHORT` (422).
48. **Cohort payment settled** — on review certification, else `ERR_COHORT_PAYMENT_UNSETTLED` (422).

### 2.6. Precision: Minutes, Percentages and Cents

Three numeric regimes coexist and must not be mixed.

**Minutes are integers, floored per session.** A session's raw duration is the number of whole minutes obtained by taking the elapsed seconds between its start and end instants, dividing by 60, and discarding any fractional part. Modality division is then applied to that integer and the result is floored again, *per session*, before any summation. Summing raw durations and dividing once at the end is wrong and produces different totals; §3.6 works the arithmetic through in detail.

**Percentages carry exactly two decimal places and are rounded half up.** This applies to `provisional_compliance_pct`, `certified_compliance_pct`, `compliance_pct`, `data_completeness_pct`, and to the derived `screening_window_hours`, which is likewise held to two decimals. Where a percentage is defined over a cohort that turns out to be empty, the specification names the literal result (`0.00`) and no division is performed.

**Money is integer cents, rounded half up at each named step.** The stay-pricing waterfall in §3.8 rounds half up at the comorbidity-uplift step, at the short-stay-factor step, at both transfer per-diem lines and at the final penalty step — never once at the end. `total_payment_cents` and `settled_payment_cents` are therefore always whole cents.

Threshold comparisons in this system are deliberately mixed between inclusive and strict, and the direction matters: the screening window, the qualifying-day minute test, the weekly minute test, the compliance pass test and the data-completeness pass test are all inclusive, while the two posture comparisons are strict. Each is stated at the point of use.

### 2.7. Version Pinning and Stale-Write Rejection

Two write operations pin the `version` of a parent record they do not themselves address in the path, because both legitimately supersede state the client may not have seen.

A `POST /plans-of-care` request — signing an overall plan of care — must carry `expected_admission_version`, a non-optional field holding the client's last observed `version` of the admission named by `admission_id`. If that value differs from the admission's current `version`, the request is rejected with `ERR_STALE_ADMISSION_VERSION` and HTTP 412. The protection is not incidental: a new plan supersedes the prior active plan and repins the three-hour-rule mode for weeks opened afterwards, so a writer holding a stale view of the admission would silently discard a plan it never read.

A `POST /compliance-reviews` request — opening a compliance review — must carry `expected_facility_version`, a non-optional field holding the client's last observed `version` of the facility named by `facility_id`. A mismatch with the facility's current `version` is rejected with `ERR_STALE_FACILITY_VERSION` and HTTP 412. Certification moves `certified_compliance_pct` and can flip `posture`, so a stale-version writer would open a review against a compliance state that no longer exists.

No other endpoint accepts a version field, and no other endpoint performs a version check. Note that both endpoints are themselves version-advancing: signing a plan increments the admission's `version` by 1, and opening a review increments the facility's `version` by 1, so two consecutive writes from the same client must re-read the parent in between.

### 2.8. Facility Compliance Posture and the Admission Gate

Each facility carries a derived `posture` with three possible values — `OPEN`, `THRESHOLD_WATCH`, and `ADMISSION_FREEZE` — that expresses how close the facility is to failing its compliance threshold. Posture is never set by a client. It is re-derived immediately after the provisional cohort figures are recomputed, and again after any compliance review is certified, from exactly two inputs: the facility's current provisional cohort figures, and the single most recently certified compliance review (the one with the greatest `certified_at`, resolving ties in favour of the greatest `created_at`). Reviews in `COMPUTED` or `STALE` status never gate posture.

The derivation is an ordered ladder. If a certified review exists and its `outcome` is `FAIL`, the posture is `ADMISSION_FREEZE`. Otherwise, if the provisional cohort holds at least two admissions and the provisional compliance percentage is strictly below the facility's threshold reduced by a twenty-percentage-point freeze margin, the posture is again `ADMISSION_FREEZE`. Otherwise, if the provisional cohort holds at least two admissions and the provisional compliance percentage is strictly below the threshold itself, the posture is `THRESHOLD_WATCH`. In every other case — including any facility whose provisional cohort holds fewer than two admissions — the posture is `OPEN`. Because both percentage comparisons are strict, a provisional percentage exactly equal to the threshold leaves the posture `OPEN`.

Posture has two consequences. A facility whose posture is `ADMISSION_FREEZE` refuses admissions outright; only `OPEN` and `THRESHOLD_WATCH` allow a patient through the gate, and an attempt against a frozen facility is `ERR_FACILITY_ADMISSION_FROZEN`. And posture propagates: at the moment a facility's posture becomes `ADMISSION_FREEZE`, every preadmission screening of that facility currently in `SUBMITTED` is placed `ON_HOLD`, so that no screening can reach physician concurrence while the facility is frozen; when the posture later leaves `ADMISSION_FREEZE`, every screening of that facility in `ON_HOLD` returns to `SUBMITTED`. This propagation is strictly edge-triggered on the posture value: a re-derivation that lands on the posture the facility already held touches no screening at all, so a screening submitted while the facility is already frozen stays `SUBMITTED` until the posture actually moves.

### 2.9. Segregation of Duties

Three pairs of actions in this system must be performed by two different people, and all three are enforced with the same rejection, `ERR_SEGREGATION_OF_DUTIES`. The rehabilitation physician recording a review decision on a screening must not be the clinician named as `conducted_by_clinician_id` on that screening. The coder transmitting an assessment instrument must not be the clinician named as `coder_clinician_id` on it. And the officer certifying a compliance review must not be the operator recorded in `created_by_user_id` when the review was opened. In each case the comparison is between `X-User-ID` and the stored identifier.

### 2.10. Referential Scope: Path Identifiers, Body Identifiers and Facility Boundaries

Identifiers reach the server by two routes and are checked in a fixed order. Identifiers embedded in the URL path are resolved first, left to right, and the first one that does not resolve produces `ERR_NOT_FOUND` — a request naming a therapy week that does not exist fails on the week before any body field is inspected. Only once every path identifier resolves are body identifiers resolved, and any unresolvable body identifier produces the same `ERR_NOT_FOUND`.

Existence is not sufficiency. Clinical records in this system are facility-scoped, and a referenced clinician or patient must belong to the same facility as the resource being written; a cross-facility reference is a conflict, reported as `ERR_CROSS_FACILITY_MISMATCH`, and it is checked on screening creation, therapy-session scheduling, team-conference recording, assessment opening and plan-of-care signing. Beyond the facility boundary two narrower coherence rules apply: a screening attached to an admission must belong to the same patient as that admission (and a named predecessor stay must belong to the same patient as the continuation), reported as `ERR_SCREENING_PATIENT_MISMATCH`; and a therapy week named on a team conference must belong to the same admission as the conference, reported as `ERR_WEEK_ADMISSION_MISMATCH`.

### 2.11. Cascades and Derived-Field Recomputation

A large fraction of this system's state is derived, and the server maintains it without being asked. Whenever a therapy session's minutes change hands, its week's counters are refreshed and the week may change status; whenever a week's status changes, the owning admission's therapy and conference flags — and, once the stay is discharged, its compliance verdict — are recomputed; whenever an admission's compliance verdict changes, the facility's cohort counts, provisional percentage and posture are recomputed; and whenever posture reaches or leaves `ADMISSION_FREEZE`, the facility's submitted screenings are frozen or released. These chains run to completion within the request that triggered them: a client that reads the facility immediately after a discharge sees the new posture, not a stale one.

A hop of such a chain is a real mutation of the resource it touches exactly when the recomputation moves at least one of the values that hop recomputes. When it does, the touched resource's `updated_at` is refreshed and its `version` increases by 1, whether or not the client named that resource in the request; when the recomputation reproduces the values the resource already held, the hop is silent and neither `updated_at` nor `version` moves. The values compared are the ones the hop itself maintains: on a therapy week its `delivered_credited_minutes`, `qualifying_days_count` and `status`; on an admission its `therapy_weeks_satisfied`, `conference_compliant`, `poc_signed_within_deadline`, `total_credited_minutes` and `compliance_class`; on a facility its `cohort_total_count`, `cohort_qualifying_count`, `provisional_compliance_pct`, `posture`, `settled_payment_cents` and `certified_compliance_pct`. So documenting a session that credits minutes advances the admission, while recording a `LATE_RECORDED` conference that changes no flag leaves the admission's `version` alone, and a week evaluation whose verdict shifts nothing at the facility leaves `Facility.version` alone.

Independently of that test, a bump this document states outright for an endpoint is unconditional. On the admission itself, admitting, denying, discharging, rescinding an interruption, and signing a plan of care always advance `Admission.version`. On the facility, opening a compliance review, certifying one, finalising a QRP assessment, any discharge, any rescission of an interruption, and any admit that reopens an already priced chain head always advance `Facility.version` — even when every derived figure listed above turns out unchanged. This is what makes the version pinning of §2.7 meaningful: a discharge or a QRP finalisation elsewhere in the facility can advance `Facility.version`, and a plan of care signed on an admission advances `Admission.version`, so any client caching a version must re-read before its next pinned write.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Facility: Staff, Thresholds and Medical Records

A `ComplianceOfficer` brings a facility into the system by supplying its legal `name` (between 1 and 120 characters), its CMS certification number as `cms_ccn` (exactly six digits, and unique across all facilities — a repeat is `ERR_CCN_DUPLICATE`), and the two dates `review_period_start` and `review_period_end` that bound the compliance review period used for provisional tracking. Both dates are inclusive calendar dates written as `YYYY-MM-DD`, and the end may not precede the start; a reversed pair is `ERR_INVALID_PERIOD`. Two further inputs are optional. `compliance_threshold_pct` is the percentage of the discharged cohort that must qualify for the facility to pass a compliance review; it accepts values from 0.01 through 100.00 with two decimals and defaults to 60.00 when omitted. `daily_therapy_cap_minutes` is the ceiling on credited therapy minutes one admission may accumulate on a single calendar date; it accepts values from 60 through 600 and defaults to 300 — five hours of credited therapy in one day.

A newly registered facility starts fully derived-clean: `posture` is `OPEN`, `cohort_total_count` and `cohort_qualifying_count` are 0, `provisional_compliance_pct` is 0.00, `certified_compliance_pct` is null, `settled_payment_cents` is 0, `active_qrp_penalty_pct` is 0.00 with `qrp_penalty_effective_at` null, and `version` is 1. Those derived fields are described where they are produced: the cohort figures in §3.8, the certified percentage and the penalty in §3.9. `settled_payment_cents` is always the sum of `total_payment_cents` over the facility's admissions whose `payment_status` is `PRICED`; stays that are reopened, consolidated into another stay, or not yet priced contribute nothing to it.

Clinicians are registered by the same officer against a `facility_id`, with a `full_name`, a `credential`, and an `npi` — the ten-digit national provider identifier, unique across all clinicians. A duplicate `npi`, like a duplicate medical record number, is reported as `ERR_MRN_DUPLICATE`. The credential is one of `REHAB_PHYSICIAN`, `NURSE`, `THERAPIST_PT`, `THERAPIST_OT`, `THERAPIST_SLP`, or `CODER`, and it is the single fact that determines what the clinician may do: §2.1 maps credentials to roles, and the therapy and conference rules below map them to disciplines. A clinician's `status` is `ACTIVE` from creation. The officer may retire a clinician, moving `status` from `ACTIVE` to `INACTIVE`, after which the clinician can neither act (§2.1) nor be named on new records. Clinicians can be listed with filters on `facility_id`, `credential` and `status`.

Patient medical records are opened by a `NurseCaseManager` against a `facility_id`, with the medical record number `mrn` — unique within that facility, a repeat being `ERR_MRN_DUPLICATE` — the patient's `full_name` and `birth_date`, the four-digit `impairment_group_code` from the IRF assessment instrument, the ICD-10 `etiologic_diagnosis_code`, and a `comorbidity_tier` of `NONE`, `TIER_3`, `TIER_2`, or `TIER_1`. These three clinical descriptors are not decoration: the impairment group code selects the payment tier and participates in presumptive compliance, the etiologic diagnosis code drives the secondary presumptive test, and the comorbidity tier both uplifts payment and participates in that same secondary test. Patients are listed with filters on `facility_id` and `mrn`.

### 3.2. Preadmission Screening and the 48-Hour Window

Every stay begins with a preadmission screening opened by a `NurseCaseManager`. The payload names the `patient_id` being screened, the `conducted_by_clinician_id` who performed the screening, the `expected_admission_at` instant the screener plans for, and four documentation attestations: `intensive_therapy_documented`, `expected_functional_improvement_documented`, `prior_functional_level_documented`, and `medical_supervision_documented`. The screener must hold either the `NURSE` or the `REHAB_PHYSICIAN` credential; any other credential is `ERR_SCREENER_CREDENTIAL_INVALID`. On creation the record enters `DRAFT`, its `revision_count` is 0, and `conducted_at` is stamped from the logical clock. That stamp is the anchor of the whole preadmission timeline: it starts the 48-hour window inside which the patient must be admitted, and it starts the 48-hour countdown to the screening's own expiry.

Submitting the screening for physician review moves it from `DRAFT` to `SUBMITTED`. Submission requires all four documentation attestations to be true — if any one of them is false the submission is refused with `ERR_SCREENING_DOCUMENTATION_INCOMPLETE` — and requires the clinician named as `conducted_by_clinician_id` to still be `ACTIVE`, an inactive screener producing `ERR_ACTING_CLINICIAN_INACTIVE`.

Review is a `RehabPhysician` action carrying a `decision` and an optional `reviewer_note`, and it has two symmetric outcomes. A `decision` of `CONCUR` advances the screening from `SUBMITTED` to `PHYSICIAN_CONCURRED`, storing `reviewed_by_clinician_id` as the acting user and `reviewed_at` as the current logical clock. A `decision` of `REQUEST_CHANGES` moves it from `SUBMITTED` to `CHANGES_REQUESTED`, storing the same `reviewed_by_clinician_id` and `reviewed_at` and additionally retaining the supplied `reviewer_note` (the note is null when omitted). In both branches the reviewing physician must be a different clinician from the screener, per §2.9, and must hold credential `REHAB_PHYSICIAN` with status `ACTIVE`.

Revision closes the loop. A `NurseCaseManager` may edit `expected_admission_at` and any of the four documentation attestations. Editing a screening that sits in `DRAFT` changes the fields without changing state. Editing a screening in `CHANGES_REQUESTED` returns it to `DRAFT`, increases `revision_count` by 1, and clears both `reviewed_by_clinician_id` and `reviewed_at` back to null — the revision loop `DRAFT` → `SUBMITTED` → `CHANGES_REQUESTED` → `DRAFT` may repeat as often as the window allows.

Two things cut the loop short. A facility that enters `ADMISSION_FREEZE` places all its `SUBMITTED` screenings `ON_HOLD` and releases them back to `SUBMITTED` when the freeze lifts, as described in §2.8; a screening `ON_HOLD` cannot be concurred. And the clock expires screenings absolutely: whenever the logical clock is advanced, every screening in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, or `ON_HOLD` whose `conducted_at` plus 48 hours is at or before the new clock value becomes `EXPIRED`, and the count of screenings swept this way is reported as `expired_screening_count`. `PHYSICIAN_CONCURRED` and `EXPIRED` are the terminal states of a screening; nothing moves out of either. Screenings can be listed with filters on `patient_id`, `conducted_by_clinician_id`, `reviewed_by_clinician_id`, and `status`.

### 3.3. Opening the Admission and Crossing the Admission Gate

A `NurseCaseManager` opens an admission by naming the `patient_id`, the `screening_id` that authorises it, and optionally the `predecessor_admission_id` of a prior stay this one continues. The screening must belong to the same patient as the admission, and it must already be `PHYSICIAN_CONCURRED` with a `reviewed_at` no later than the eventual admission instant — a screening in any other state is `ERR_SCREENING_NOT_CONCURRED`. The new record copies `facility_id` from the patient's own facility and never changes it thereafter, and it starts with all three of its independent status dimensions at their initial values: `stay_status` is `PENDING`, `payment_status` is `NOT_PRICED`, `documentation_status` is `INCOMPLETE`, and `compliance_class` is `PENDING_EVALUATION`.

Those three dimensions are genuinely independent and evolve on their own timetables. `stay_status` runs `PENDING` → `ADMITTED` → `DISCHARGED`, with `ADMISSION_DENIED` as the alternative terminal from `PENDING`. `payment_status` runs `NOT_PRICED` → `PRICED` and then, if a continuation is attached, `PRICED` → `REOPENED` and back to `PRICED`, or `NOT_PRICED` → `CONSOLIDATED` and, on rescission, `CONSOLIDATED` → `NOT_PRICED`. `documentation_status` runs `INCOMPLETE` → `POC_SIGNED` → `PAI_TRANSMITTED`. A stay that is `DISCHARGED`, `REOPENED` and `POC_SIGNED` simultaneously is an entirely ordinary state of affairs.

Admitting the patient is the moment the window closes. The request supplies `admitted_at`, and the facility's `posture` must be `OPEN` or `THRESHOLD_WATCH` (§2.8). `admitted_at` may not be later than the current logical clock and may not be earlier than the screening's `conducted_at`; either violation is `ERR_INVALID_REQUEST`. The elapsed time from the screening's `conducted_at` to `admitted_at` must be at most 48 hours, or the attempt fails with `ERR_SCREENING_WINDOW_EXPIRED`. And the physician's `reviewed_at` must be at or before `admitted_at`, or the attempt fails with `ERR_SCREENING_NOT_CONCURRED` — concurrence recorded after the patient was already in the bed does not count.

A successful admit moves `stay_status` from `PENDING` to `ADMITTED`, stores `admitted_at` — which is null for as long as the stay is `PENDING` — and derives three things. `screening_window_hours` is the number of hours between the screening's `conducted_at` and `admitted_at`, held to two decimals; it too is null while the stay is `PENDING`. `screening_compliant` is true when that figure is at most 48.00 *and* the screening's `status` is `PHYSICIAN_CONCURRED` *and* the screening's `reviewed_at` is at or before `admitted_at`; it defaults to false and stays false whenever any of the three conditions fails. `qrp_penalty_pct_snapshot` is pinned from the facility's `active_qrp_penalty_pct` at that instant, defaulting to 0.00 when no penalty is in force, and is never repinned — a quality-reporting penalty finalised tomorrow does not reach a patient admitted today. Finally, `cmg_tier` is resolved from the patient's `impairment_group_code`: code `0008` maps to `TIER_B`, code `0110` to `TIER_C`, codes `0704` and `1101` to `TIER_A`, and any other impairment group code falls back to `TIER_A`.

A `RehabPhysician` may instead deny a pending admission, supplying a `denial_reason`. Denial moves `stay_status` from `PENDING` to `ADMISSION_DENIED`, stores the reason, and sets `compliance_class` to `EXCLUDED` — a denied stay never enters any compliance cohort. Admissions can be listed with filters on `facility_id`, `patient_id`, `screening_id`, `predecessor_admission_id`, `payment_consolidated_into_admission_id`, `stay_status`, `payment_status`, and `compliance_class`.

### 3.4. Interrupted Stays: Consolidation, Reopening and Rescission

When a patient leaves an IRF and returns within a short window, the two stays are one episode for payment purposes. The rule is symmetric and mandatory in both directions. If the admit request names a `predecessor_admission_id`, that stay must belong to the same patient (else `ERR_SCREENING_PATIENT_MISMATCH`), must already be `DISCHARGED`, and the gap — the number of whole calendar days from the predecessor's discharge date to this admission's admit date — must be at least 0 and at most 3; a predecessor that is not discharged or a gap beyond three days is `ERR_INTERRUPTION_WINDOW_EXCEEDED`. That predecessor must also not already be named by some other admission, or the attach fails with `ERR_PREDECESSOR_ALREADY_CONTINUED`. Conversely, if the admit request names no predecessor at all but the same patient has a `DISCHARGED` admission whose discharge date falls within the three calendar days before this admission's admit date, the omission is itself an error: `ERR_INTERRUPTED_STAY_LINK_REQUIRED`. Continuations may chain, each link obeying the same three-day rule.

Attaching a continuation sets `interrupted_stay_flag` to true (it is false by default), records the computed gap in `interruption_gap_days` (null on any stay that is not a continuation), and points `payment_consolidated_into_admission_id` at the head of the chain — the admission whose own `predecessor_admission_id` is null — which is where the single consolidated payment will live. The continuation's own `payment_status` moves from `NOT_PRICED` to `CONSOLIDATED` and its `total_payment_cents` is fixed at 0.

The attach then cascades. If the chain head had already been priced, its `payment_status` moves from `PRICED` to `REOPENED`, its `total_payment_cents` returns to 0 and its `effective_los_days` returns to null pending reconsolidation — its `stay_status` is untouched and remains `DISCHARGED`. Because the head no longer counts as settled, the facility's `settled_payment_cents` is recomputed over its `PRICED` admissions and the facility's `version` increases by 1. And because a reopened stay's numbers are provisional, every compliance review of that facility currently in `COMPUTED` whose cohort contains the head is invalidated to `STALE`, with `stale_reason` set to `INTERRUPTED_STAY_RECONSOLIDATION`. A stale review keeps its `compliance_pct` and `outcome` for audit but can no longer be certified.

Mistakes happen, and a `ComplianceOfficer` can unwind one. Rescinding an interruption requires the admission to carry `interrupted_stay_flag` true — otherwise `ERR_NOT_INTERRUPTED_STAY` — and requires that continuation to still be `ADMITTED`; a continuation that has already been discharged may not be unlinked, and the attempt is refused with `ERR_INVALID_STATE`. The request carries a `rescind_reason`. Rescission sets `interrupted_stay_flag` back to false, clears `interruption_gap_days`, `payment_consolidated_into_admission_id` and `predecessor_admission_id` to null, and moves the continuation's `payment_status` from `CONSOLIDATED` back to `NOT_PRICED`. The chain head is made whole in the same breath: its `payment_status` moves from `REOPENED` back to `PRICED` with its standalone `effective_los_days` and `total_payment_cents` restored, and the facility's `settled_payment_cents` is recomputed to exactly the value it held before the erroneous attach.

### 3.5. The Individualized Overall Plan of Care

Within 96 hours of admission — four days — a `RehabPhysician` must sign an individualized overall plan of care. The request names the `admission_id`, pins `expected_admission_version` per §2.7, and declares `target_los_days` (a target length of stay from 1 through 120 days), `weekly_minutes_target` (planned credited therapy minutes per seven-day week, from 60 through 2400), and `disciplines`, a non-empty list drawn from `PT`, `OT`, and `SLP` with no duplicates. One optional field, `three_hour_rule_mode`, selects how therapy weeks opened while this plan is active will be judged; it is either `DAILY_3HR` or `WEEKLY_15HR` and defaults to `DAILY_3HR`. The admission must be `ADMITTED` at the time of signing, or the request is refused with `ERR_ADMISSION_NOT_ACTIVE`.

On creation the plan's `status` is `ACTIVE`, its `authored_by_clinician_id` is taken from the acting user, and its `signed_at` is stamped from the logical clock — the signature instant and the creation instant are the same. Signing also advances the admission: `documentation_status` moves from `INCOMPLETE` to `POC_SIGNED`, `poc_signed_within_deadline` is recomputed, and the admission's `version` increases by 1.

`poc_signed_within_deadline` defaults to false and is true only when the *earliest* plan of care for the admission — earliest by `created_at` ascending, when several exist — carries a `signed_at` no later than 96 hours after `admitted_at`. A second plan signed on day nine cannot repair a first plan signed on day five.

A second plan for the same admission is legitimate and does not replace history: the prior `ACTIVE` plan moves to `SUPERSEDED` and the new one becomes `ACTIVE`. Supersession is deliberately not retroactive for therapy measurement. Therapy weeks that already exist keep the `evaluation_mode` they pinned at their own creation; only weeks opened after the new plan takes effect pin the new plan's `three_hour_rule_mode`. Plans can be listed with filters on `admission_id`, `authored_by_clinician_id`, and `status`.

### 3.6. Measuring Therapy: Weeks, Sessions and the Three-Hour Rule

Therapy compliance is measured in seven-day windows. A `TherapyLead` opens one by naming the `admission_id`, a `week_index`, and a `week_start_date`. The index is a 1-based ordinal of the window within the stay, from 1 through 26, unique per admission — a repeat is `ERR_WEEK_INDEX_DUPLICATE`. The `week_end_date` is derived as the `week_start_date` plus six days, so the window covers seven inclusive calendar dates. The window may not start before the day the patient was admitted (`ERR_WEEK_BEFORE_ADMISSION`) and may not overlap any existing window of the same admission, although windows that merely touch — where the previous window's `week_end_date` plus one day equals the new `week_start_date` — are perfectly legal; an actual overlap is `ERR_THERAPY_WEEK_OVERLAP`. Opening a week requires an `ACTIVE` plan of care to exist for the admission (`ERR_PLAN_OF_CARE_MISSING`) and requires the admission to be `ADMITTED`. The new week's `status` is `OPEN`, its `delivered_credited_minutes` and `qualifying_days_count` start at 0, its `exception_reason` and `exception_granted_by_clinician_id` are null, and its `evaluation_mode` is pinned from the active plan's `three_hour_rule_mode` at that instant.

A session is scheduled by the same `TherapyLead`, naming the `admission_id`, the treating `clinician_id`, the `discipline` (`PT`, `OT`, or `SLP`), the `modality` (`INDIVIDUAL`, `CONCURRENT`, or `GROUP`), the `start_at` instant (inclusive) and the `end_at` instant (exclusive), plus an optional `group_size` that defaults to 1. Group size and modality must agree: `INDIVIDUAL` requires exactly 1, `CONCURRENT` requires exactly 2, and `GROUP` requires between 3 and 6 inclusive; anything else is `ERR_GROUP_SIZE_INVALID`. `end_at` must be strictly after `start_at` and the interval must be at least one whole minute long, or the request is `ERR_INVALID_SESSION_INTERVAL`. The declared `discipline` must appear in the active plan's `disciplines` (`ERR_DISCIPLINE_NOT_IN_PLAN`), and the treating clinician's credential must match it exactly — `THERAPIST_PT` for `PT`, `THERAPIST_OT` for `OT`, `THERAPIST_SLP` for `SLP` — with a mismatch reported as `ERR_CLINICIAN_DISCIPLINE_MISMATCH`. As with weeks, an `ACTIVE` plan must exist and the admission must be `ADMITTED`.

Scheduling then resolves the session into a week and derives its minutes. `session_date` is the UTC calendar date of `start_at`, and it is the bucket used for both the daily cap and the qualifying-day test. `therapy_week_id` is resolved to the one week of that admission whose window contains `session_date` — candidates are the admission's weeks in `OPEN`, `MET`, `NOT_MET`, or `EXCEPTION_GRANTED` whose `week_start_date` is at or before the session date and whose `week_end_date` is at or after it, resolving ties in favour of the earliest `created_at`; when no candidate week exists the request fails with `ERR_NO_OPEN_THERAPY_WEEK`. `raw_minutes` is the elapsed time from `start_at` to `end_at` expressed in whole minutes, obtained by dividing the elapsed seconds by 60 and discarding any fraction. `credited_minutes` is then derived from `raw_minutes` by modality: an `INDIVIDUAL` session credits its raw minutes in full; a `CONCURRENT` session credits its raw minutes divided by two with any fraction discarded; a `GROUP` session credits its raw minutes divided by `group_size` with any fraction discarded. The new session's `status` is `SCHEDULED` and its `documented_at` and `void_reason` are null.

The flooring order is pinned and consequential: division happens once per session, on that session's own raw minutes, and the floored per-session results are added together afterwards. Three 50-minute `GROUP` sessions with a `group_size` of 3 therefore credit 16 minutes each for a total of 48 credited minutes — not the 50 that would result from adding the raw minutes first and dividing once.

Three temporal guards protect the schedule, and each is evaluated on scheduling. A treating clinician may not be double-booked: the new session's half-open interval from `start_at` up to but excluding `end_at` must not intersect the interval of any other `SCHEDULED` or `DELIVERED` session of the same `clinician_id`, though exact adjacency — where a previous session's `end_at` equals the new `start_at` — is allowed; an intersection is `ERR_CLINICIAN_SCHEDULE_CONFLICT`. The patient is owed a rest buffer: across the `SCHEDULED` and `DELIVERED` sessions of the same `admission_id`, the new session is refused when its `start_at` falls earlier than another session's `end_at` plus ten minutes while that other session's `start_at` falls earlier than the new session's `end_at` plus ten minutes; exactly ten minutes of separation is acceptable, and a violation is `ERR_PATIENT_REST_BUFFER_VIOLATION`. And the facility's daily ceiling binds: the credited minutes already booked for that admission on the same `session_date`, counting both `SCHEDULED` and `DELIVERED` sessions, plus the new session's own `credited_minutes`, must not exceed the facility's `daily_therapy_cap_minutes`; exceeding it is `ERR_DAILY_THERAPY_CAP_EXCEEDED`.

Only delivered therapy counts. Documenting a session as delivered moves it from `SCHEDULED` to `DELIVERED`, requires the admission to still be `ADMITTED` (`ERR_ADMISSION_NOT_ACTIVE`) and the treating clinician to still be `ACTIVE`, and stamps `documented_at` from the logical clock. The session's `credited_minutes` are added to its week's `delivered_credited_minutes` and the week's `qualifying_days_count` is refreshed; if the week is already `MET` or `NOT_MET` it is re-evaluated on the spot, which can carry a week from `NOT_MET` to `MET`. The admission's `total_credited_minutes` — the sum of `delivered_credited_minutes` across all of its weeks — is recomputed.

Voiding runs the same machinery backwards. A void requires a `void_reason`, without which the request is `ERR_INVALID_REQUEST`. Voiding a `DELIVERED` session moves it to `VOIDED`, subtracts exactly that session's `credited_minutes` from its week's `delivered_credited_minutes`, refreshes `qualifying_days_count`, re-evaluates the week when it is `MET` or `NOT_MET` — which can carry a week from `MET` back to `NOT_MET` — and recomputes the admission's `total_credited_minutes`. Voiding a `SCHEDULED` session also moves it to `VOIDED` but adjusts no minutes at all, because a scheduled session never contributed any; what it does release is the clinician interval and the patient rest-buffer interval the session had been occupying, freeing that slot for a replacement booking. `MET` and `NOT_MET` are thus a genuine cycle driven by delivery and voiding, and neither is terminal. Sessions can be listed with filters on `admission_id`, `therapy_week_id`, `clinician_id`, `status`, and `session_date`.

**Evaluating the rule.** A `TherapyLead` may evaluate a week explicitly, and the discharge cascade evaluates every still-open week automatically. Evaluation requires an `ACTIVE` plan of care for the admission (`ERR_PLAN_OF_CARE_MISSING`). It first refreshes the week's counters from the window's seven inclusive dates: for each date, the credited minutes of that week's `DELIVERED` sessions bearing that `session_date` are totalled; `delivered_credited_minutes` is the sum of those seven daily totals, and `qualifying_days_count` is the number of those dates whose daily total is at least 180 credited minutes — three hours of therapy in one day. The verdict then depends on the week's pinned `evaluation_mode`, and the two variants disagree by design:

- Under `DAILY_3HR`, the week is `MET` when `qualifying_days_count` is at least 5 — five of the seven dates each reaching 180 credited minutes — and `NOT_MET` otherwise. Total weekly volume is irrelevant under this mode.
- Under `WEEKLY_15HR`, the week is `MET` when `delivered_credited_minutes` is at least 900 — fifteen hours anywhere inside the window — and `NOT_MET` otherwise. Distribution across dates is irrelevant under this mode.

Both comparisons are inclusive: exactly 180 credited minutes makes a qualifying day, and exactly 900 credited minutes satisfies the weekly variant. The two modes genuinely diverge — three dates of 300 credited minutes total 900 and so satisfy `WEEKLY_15HR`, while yielding only three qualifying days and therefore failing `DAILY_3HR`. A week with no delivered sessions at all yields `delivered_credited_minutes` of 0 and `qualifying_days_count` of 0 and is `NOT_MET` under either mode; no division is performed, so an empty week is not an error.

Either verdict refreshes the counters and recomputes the admission's `therapy_weeks_satisfied` and `total_credited_minutes`, but the two branches then diverge. A verdict of `MET` leaves the admission's `compliance_class` free to be recomputed as `QUALIFYING`. A verdict of `NOT_MET` forces `therapy_weeks_satisfied` to false and, when the admission is already `DISCHARGED`, forces its `compliance_class` to `NON_QUALIFYING`, which in turn drags the facility's provisional percentage and `posture` with it.

A week that failed the rule is not necessarily lost. A `RehabPhysician` may grant a documented exception, supplying an `exception_reason`. The week must be in `NOT_MET` — an exception requested for a week in any other status is `ERR_EXCEPTION_NOT_ALLOWED` — and the granting physician must hold credential `REHAB_PHYSICIAN` with status `ACTIVE`. The week moves from `NOT_MET` to the terminal `EXCEPTION_GRANTED`, storing the `exception_reason` and recording the grantor in `exception_granted_by_clinician_id`. The admission's `therapy_weeks_satisfied` is recomputed with `EXCEPTION_GRANTED` counting as satisfied, and when the admission is already `DISCHARGED` its `compliance_class` and the facility's `provisional_compliance_pct` and `posture` are recomputed too. `therapy_weeks_satisfied` — false by default — is true only when the admission has at least one therapy week and every one of them is either `MET` or `EXCEPTION_GRANTED`. Weeks can be listed with filters on `admission_id`, `exception_granted_by_clinician_id`, `status`, and `week_index`.

### 3.7. The Weekly Interdisciplinary Team Conference

Each therapy week must be discussed by the interdisciplinary team, and a `NurseCaseManager` records that discussion by naming the `admission_id`, the `therapy_week_id` it documents, the `led_by_clinician_id` who chaired it, the `participant_clinician_ids` who attended, and the `held_at` instant. The participant list holds between 1 and 12 clinician identifiers with no duplicates, all employed by the same facility. The chair must hold credential `REHAB_PHYSICIAN` and be `ACTIVE`; any other credential is `ERR_CONFERENCE_LEAD_NOT_PHYSICIAN`. The attendance itself must be clinically complete: the participants must include at least one clinician with the `NURSE` credential and, for every discipline named in the admission's `ACTIVE` plan of care, at least one therapist holding the matching credential — a gap on either count is `ERR_CONFERENCE_PARTICIPANTS_INCOMPLETE`. The admission must be `ADMITTED`, and the named week must belong to that same admission (§2.10).

Two temporal facts govern the record. The UTC calendar date of `held_at` must fall inside the week's window, from `week_start_date` through `week_end_date` inclusive; a conference held outside its own week is `ERR_CONFERENCE_OUTSIDE_WEEK`. Separately, the *recording* time decides timeliness: the conference's `status` is `RECORDED` when the logical clock's calendar date at the moment of recording is at or before the week's `week_end_date`, and `LATE_RECORDED` when it is after. Only a `RECORDED` conference counts toward compliance, and at most one `RECORDED` conference may exist per therapy week — a second attempt where one already exists is `ERR_CONFERENCE_ALREADY_RECORDED`.

Recording a conference recomputes the admission's `conference_compliant`, which is false by default and true only when every therapy week of the admission has at least one `RECORDED` conference. A `LATE_RECORDED` conference never satisfies that test, so a week documented after its window closed leaves the whole admission short. Conferences can be listed with filters on `admission_id`, `therapy_week_id`, `led_by_clinician_id`, and `status`.

### 3.8. Discharge: Compliance Verdict, Cascade and Stay Pricing

Discharge is the single heaviest operation in the system. A `NurseCaseManager` triggers it by supplying `discharged_at`, the `discharge_destination`, and the boolean `discharge_planned` recording whether the discharge was planned. The destination is one of `COMMUNITY`, `SNF`, `ACUTE_CARE`, `LTCH`, `ANOTHER_IRF`, `EXPIRED`, or `AGAINST_MEDICAL_ADVICE`, and all three fields are null until the stay is discharged. `discharged_at` must be at or after `admitted_at` and at or before the current logical clock; either violation is `ERR_INVALID_REQUEST`. The stay's `stay_status` moves from `ADMITTED` to the terminal `DISCHARGED`; `documentation_status` is deliberately untouched, since a discharged stay may still be documentarily incomplete.

**The compliance cascade.** Four hops then run to completion, each caused by the one before it.

The first hop closes out therapy measurement: every therapy week of this admission still in `OPEN` is evaluated exactly as §3.6 describes, under its own pinned `evaluation_mode`, and becomes either `MET` or `NOT_MET`.

The second hop, caused by the first, finalises the stay's verdict: `therapy_weeks_satisfied`, `conference_compliant` and `compliance_class` are recomputed on this admission. `compliance_class` is decided by an ordered ladder. A stay whose `stay_status` is `ADMISSION_DENIED` is `EXCLUDED`. A stay that is not `DISCHARGED` is `PENDING_EVALUATION`. A discharged stay whose `discharge_destination` is `EXPIRED` is `EXCLUDED` — deaths never count for or against a facility. Otherwise the stay is `QUALIFYING` when all four documentation tests pass simultaneously — `screening_compliant`, `poc_signed_within_deadline`, `therapy_weeks_satisfied`, and `conference_compliant` all true — and `NON_QUALIFYING` when any one of them fails. The four tests are those defined in §3.3, §3.5, §3.6 and §3.7 respectively; taken together they are the medical-review notion of qualification.

The third hop, caused by the second, lifts the verdict to the facility. `cohort_total_count`, `cohort_qualifying_count` and `provisional_compliance_pct` are recomputed over the facility's *provisional cohort*: the facility's admissions that are `DISCHARGED`, whose discharge calendar date falls between the facility's own `review_period_start` and `review_period_end` inclusive, and whose `compliance_class` is not `EXCLUDED`. `cohort_total_count` is the size of that cohort, `cohort_qualifying_count` is the number of its members whose `compliance_class` is `QUALIFYING`, and `provisional_compliance_pct` is the qualifying count multiplied by 100, divided by the total count, rounded half up to two decimals — or exactly 0.00 when the cohort is empty, in which case no division is performed. The facility's `posture` is then re-derived per §2.8. The same recomputation runs after any event that can change an admission's `compliance_class`: a discharge, a week evaluation, a week exception, or a denial.

The fourth hop, caused by the third, propagates posture to screenings: if the posture became `ADMISSION_FREEZE`, every screening of that facility in `SUBMITTED` becomes `ON_HOLD`; if the posture left `ADMISSION_FREEZE`, every screening in `ON_HOLD` returns to `SUBMITTED`.

**Pricing the stay.** In the same operation the stay is priced. An ordinary stay moves `payment_status` from `NOT_PRICED` to `PRICED` and receives its `effective_los_days` — null on any stay that has not been priced — and its `total_payment_cents`, which is 0 for as long as the stay is `NOT_PRICED`, `REOPENED`, or `CONSOLIDATED`. A continuation stays `CONSOLIDATED` with `total_payment_cents` at 0 and instead pushes its chain head from `REOPENED` back to `PRICED`, which requires every admission in the chain to be `DISCHARGED`; the head is then repriced over the whole chain. Either way the facility's `settled_payment_cents` is recomputed and the facility's `version` increases by 1.

The payment itself is a five-step waterfall, and each step rounds where it is told to.

*Step one — the chain and its effective length of stay.* The chain is the head (the admission whose `predecessor_admission_id` is null) followed by its continuations ordered by `admitted_at` ascending. The span is the inclusive count of calendar days from the head's admit date to the last chain member's discharge date. The interruption total is the sum, over each consecutive pair in the chain, of the whole calendar days between the earlier member's discharge date and the later member's admit date. `effective_los_days` is the span minus that interruption total. For a single stay with no continuations the interruption total is 0, so the effective length of stay is simply the inclusive calendar-day count from admit date to discharge date — a stay admitted and discharged on the same date is 1 day.

*Step two — base rate with comorbidity uplift.* Each payment tier has a base amount in cents: `TIER_A` is 1800000 cents, `TIER_B` is 2450000 cents, and `TIER_C` is 3120000 cents. The head patient's `comorbidity_tier` uplifts that base — `NONE` adds nothing, `TIER_3` adds 3 percent, `TIER_2` adds 6 percent, and `TIER_1` adds 12 percent. The uplifted base is the tier base multiplied by one plus that uplift fraction, rounded half up to whole cents *at this step*.

*Step three — the short-stay factor.* When `effective_los_days` is at most 3, the uplifted base is multiplied by a short-stay factor of 0.35; when it is 4 days or more the factor is 1.00. The adjusted base is that product, again rounded half up to whole cents at this step.

*Step four — the transfer per-diem cap.* Each tier also carries an average length of stay: 9 days for `TIER_A`, 12 days for `TIER_B`, and 15 days for `TIER_C`. The transfer rule applies when the *last* chain member's `discharge_destination` is one of `SNF`, `ACUTE_CARE`, `LTCH`, or `ANOTHER_IRF`, *and* `effective_los_days` is strictly less than the tier's average length of stay. When it applies, a per-diem amount is the adjusted base divided by the tier's average length of stay, rounded half up to whole cents; the transfer amount is that per-diem multiplied by the effective length of stay plus one half, again rounded half up to whole cents; and the gross amount is the smaller of the adjusted base and that transfer amount. When the transfer rule does not apply, the gross amount is simply the adjusted base.

*Step five — the quality-reporting reduction, applied last.* `total_payment_cents` is the gross amount multiplied by one minus the head's `qrp_penalty_pct_snapshot` divided by 100, rounded half up to whole cents. The penalty percentage is read from the head's admit-time snapshot and never from the facility's current `active_qrp_penalty_pct`, because the facility's live penalty is itself derived from the transmitted assessments of already-priced discharges — reading it at pricing time would feed a stay's own outputs back into its inputs.

The payment tier and the comorbidity uplift are always taken from the *head's* patient, while the transfer test is always taken from the *last* discharge destination in the chain. The head carries the entire amount; every continuation keeps `total_payment_cents` at 0 for as long as its `payment_status` is `CONSOLIDATED`.

### 3.9. Assessment Transmission, Compliance Review and Quality Reporting

**The patient assessment instrument.** A `HimCoder` opens an IRF patient assessment instrument by naming the `admission_id`, the `assessment_type` — either `ADMISSION` or `DISCHARGE` — and the `coder_clinician_id` who will complete the item set, who must hold the `CODER` credential. At most one instrument per admission per type may exist in any status other than `MISSED`; a duplicate is `ERR_ASSESSMENT_TYPE_DUPLICATE`. Opening a `DISCHARGE` instrument requires the admission to already be `DISCHARGED`, or the request is refused with `ERR_ADMISSION_NOT_DISCHARGED`. An `ADMISSION` instrument anchors its dates on the admit date, so it requires a stay that has actually been admitted: a stay whose `admitted_at` is still null — one still `PENDING`, or one that was `ADMISSION_DENIED` — is refused with `ERR_INVALID_STATE`, and that refusal is evaluated last, after the one-live-instrument-per-type duplicate test stated just above. On creation the `status` is `DRAFT`, `item_set_complete` is the attestation still to be supplied and is therefore null — not false — until completion supplies it, and three dates are derived at once. The `assessment_reference_date` is the admit date plus three days for an `ADMISSION` instrument, and the discharge date itself for a `DISCHARGE` instrument. The `completion_deadline_at` is midnight — `00:00:00.000Z` — on the reference date plus four days for an `ADMISSION` instrument, or on the reference date plus five days for a `DISCHARGE` instrument. The `transmission_deadline_at` is midnight on the completion deadline's date plus a further 17 days.

Completing the item set requires `item_set_complete` to be supplied as true; supplying false is `ERR_PAI_ITEM_SET_INCOMPLETE`. The acting coder must hold credential `CODER` with status `ACTIVE`. Completion moves the instrument from `DRAFT` to `COMPLETED`, stamps `completed_at` from the logical clock, and sets `completion_late` — false by default — to true exactly when `completed_at` is at or after `completion_deadline_at`.

Transmission is where the branch happens, and the branch selector is purely the clock's position relative to `transmission_deadline_at`. In both branches the admission must be `DISCHARGED` (`ERR_ADMISSION_NOT_DISCHARGED`) and the transmitting coder must differ from `coder_clinician_id` (§2.9). When the clock is strictly earlier than `transmission_deadline_at`, the instrument moves from `COMPLETED` to `TRANSMITTED`, `transmitted_at` is stamped from the clock, `late_days` is 0, and `transmitted_by_clinician_id` records the acting coder. When the clock is at or after `transmission_deadline_at` but strictly earlier than 30 days past it, the instrument moves from `COMPLETED` to `LATE_TRANSMITTED` instead, `transmitted_at` is stamped from the clock, `transmitted_by_clinician_id` records the acting coder, and `late_days` becomes the elapsed time from `transmission_deadline_at` to `transmitted_at` divided by 24 hours and rounded *up* to a whole number of days. Equality lands on the late branch: a transmission at exactly the deadline instant is `LATE_TRANSMITTED`. Either branch, when the `assessment_type` is `DISCHARGE`, advances the admission's `documentation_status` from `POC_SIGNED` to `PAI_TRANSMITTED`. The difference between the two branches shows up later, in quality reporting: a `LATE_TRANSMITTED` discharge instrument stops its admission from counting as timely.

Instruments that are never transmitted are swept. Whenever the logical clock is advanced to 30 days past an instrument's `transmission_deadline_at` or beyond, every instrument still in `DRAFT` or `COMPLETED` becomes `MISSED`, and the number swept is reported as `missed_assessment_count`. `TRANSMITTED`, `LATE_TRANSMITTED` and `MISSED` are the three terminal states of an instrument. Instruments can be listed with filters on `admission_id`, `coder_clinician_id`, `transmitted_by_clinician_id`, `assessment_type`, and `status`.

**The compliance review.** A `ComplianceOfficer` opens a review by naming the `facility_id` under review, pinning `expected_facility_version` per §2.7, choosing a `method` of `PRESUMPTIVE` or `MEDICAL_REVIEW`, and bounding the reviewed cohort with `period_start` and `period_end` — inclusive discharge dates, the end not earlier than the start. The review starts in `DRAFT` with `created_by_user_id` recorded from the acting operator, `certified_by_user_id` null, `total_cases` and `qualifying_cases` at 0, and `compliance_pct`, `outcome`, `computed_at`, `certified_at` and `stale_reason` all null. Opening a review increments the facility's `version` by 1.

Computing the review assembles its cohort: the facility's admissions that are `DISCHARGED`, whose discharge calendar date falls between `period_start` and `period_end` inclusive, and whose `compliance_class` is not `EXCLUDED`. Admissions still `PENDING` or `ADMITTED`, and admissions discharged to `EXPIRED`, never enter the cohort under either method. `total_cases` is the cohort size, and an empty cohort is refused outright with `ERR_EMPTY_COMPLIANCE_COHORT`. Qualification is then decided by the review's `method`, and the two variants are materially different tests:

- Under `PRESUMPTIVE`, an admission qualifies when its patient's `impairment_group_code` is one of `0008`, `0110`, `0704`, or `1101`; or when its patient's `etiologic_diagnosis_code` is one of `I63.9` or `S72.001A` **and** that patient's `comorbidity_tier` is `TIER_1` or `TIER_2`. Documentation completeness is ignored entirely under this method.
- Under `MEDICAL_REVIEW`, an admission qualifies exactly when its `compliance_class` is `QUALIFYING` — that is, when all four documentation tests of §3.8 passed. The same cohort can therefore score materially lower here than under `PRESUMPTIVE`: a stroke patient with a presumptive impairment group code but no plan of care signed inside the deadline qualifies presumptively and fails medical review.

`qualifying_cases` is the count of qualifying cohort members, and `compliance_pct` is that count multiplied by 100, divided by `total_cases`, rounded half up to two decimals. The `outcome` is `PASS` when `compliance_pct` is greater than or equal to the facility's `compliance_threshold_pct`, and `FAIL` otherwise — the pass test is inclusive, so a percentage exactly equal to the threshold passes. `computed_at` is stamped from the logical clock, and the review moves from `DRAFT` to `COMPUTED`.

A computed result is not permanent. As §3.4 describes, reconsolidating a cohort member invalidates the review to `STALE` with a `stale_reason`, retaining `compliance_pct` and `outcome` for audit while making the review uncertifiable, and clearing the facility's `certified_compliance_pct` to null if this review was its source. Recomputing a `STALE` review returns it to `COMPUTED`, clears `stale_reason` back to null, and recomputes the totals and outcome against the current cohort — after which a later reconsolidation may invalidate it all over again.

Certification is terminal and doubly guarded. The certifying officer must differ from `created_by_user_id` (§2.9), and no member of the cohort may have a `payment_status` of `REOPENED` at that moment — an unsettled cohort is refused with `ERR_COHORT_PAYMENT_UNSETTLED`. On success the review moves from `COMPUTED` to `CERTIFIED`, stamping `certified_at` and recording `certified_by_user_id`. The facility's `certified_compliance_pct` is set to the review's `compliance_pct`; the facility's `posture` is re-derived, so a certified review whose `outcome` is `FAIL` forces `ADMISSION_FREEZE`, and if the posture becomes `ADMISSION_FREEZE` the facility's `SUBMITTED` screenings are placed `ON_HOLD`; and the facility's `version` increases by 1. Reviews can be listed with filters on `facility_id`, `method`, and `status`.

**Quality reporting and the payment penalty.** A `ComplianceOfficer` opens a quality reporting programme assessment by naming the `facility_id` being scored, the `fiscal_year` the penalty would apply to (from 2020 through 2100), and the inclusive discharge dates `reporting_period_start` and `reporting_period_end`. The record starts in `DRAFT` with `finalized_at` null, and its metrics are computed from current data straight away; they are recomputed again at finalisation.

The reporting cohort is every `DISCHARGED` admission of the facility whose discharge calendar date falls inside the reporting period — including admissions discharged to `EXPIRED`, unlike the compliance cohorts, which exclude them. `cohort_count` is that cohort's size. `timely_count` is the number of cohort members holding a `DISCHARGE` assessment instrument whose `status` is `TRANSMITTED`; instruments in `LATE_TRANSMITTED`, `MISSED`, `COMPLETED` or `DRAFT` do not count. `data_completeness_pct` is the timely count multiplied by 100, divided by `cohort_count`, rounded half up to two decimals — or exactly 0.00 when the cohort is empty. `penalty_pct` is 0.00 when `data_completeness_pct` is greater than or equal to 95.00, and 2.00 otherwise; the pass test is inclusive, so exactly 95.00 percent completeness avoids the penalty.

Finalisation recomputes all four metrics, stamps `finalized_at` from the logical clock, and moves the record from `DRAFT` to the terminal `FINALIZED`. It then puts the reduction into force: the facility's `active_qrp_penalty_pct` becomes this assessment's `penalty_pct`, the facility's `qrp_penalty_effective_at` becomes `finalized_at`, and the facility's `version` increases by 1. Admissions already `ADMITTED` keep the `qrp_penalty_pct_snapshot` they pinned at their own admit instant; only patients admitted after this finalisation instant pin the new value. QRP assessments can be listed with filters on `facility_id`, `fiscal_year`, and `status`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — including every state transition, every cascade trigger and the logical-clock control — return `200 OK`. Read operations return `200 OK`. The "All roles" entry in the table below means all five of `ComplianceOfficer`, `NurseCaseManager`, `RehabPhysician`, `TherapyLead`, and `HimCoder`.

| Method | Path                                             | Description                                                                                                                                | Authorized Role(s) |
| ------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------ |
| POST   | `/facilities`                                    | Register an inpatient rehabilitation facility with its compliance review period and thresholds                                             | ComplianceOfficer  |
| GET    | `/facilities/{facilityId}`                       | Read a facility with its derived compliance posture and percentages                                                                        | All roles          |
| POST   | `/clinicians`                                    | Register a clinician at a facility                                                                                                         | ComplianceOfficer  |
| GET    | `/clinicians/{clinicianId}`                      | Read one clinician                                                                                                                         | All roles          |
| GET    | `/clinicians`                                    | List clinicians, filterable by employing facility, credential and status                                                                   | All roles          |
| POST   | `/clinicians/{clinicianId}/deactivate`           | Deactivate a clinician so they can no longer act or be referenced by new records                                                           | ComplianceOfficer  |
| POST   | `/patients`                                      | Register a patient medical record at a facility                                                                                            | NurseCaseManager   |
| GET    | `/patients/{patientId}`                          | Read one patient                                                                                                                           | All roles          |
| GET    | `/patients`                                      | List patients, filterable by facility and medical record number                                                                            | All roles          |
| POST   | `/screenings`                                    | Open a preadmission screening; conducted_at is stamped from the logical clock and anchors the 48-hour window                               | NurseCaseManager   |
| GET    | `/screenings/{screeningId}`                      | Read one preadmission screening                                                                                                            | All roles          |
| GET    | `/screenings`                                    | List preadmission screenings, filterable by patient, screener, reviewer and status                                                         | All roles          |
| PATCH  | `/screenings/{screeningId}`                      | Revise a screening; a screening in CHANGES_REQUESTED returns to DRAFT and increments revision_count                                        | NurseCaseManager   |
| POST   | `/screenings/{screeningId}/submit`               | Submit a screening for rehab physician review                                                                                              | NurseCaseManager   |
| POST   | `/screenings/{screeningId}/review`               | Record the rehab physician review decision (concurrence or change request)                                                                 | RehabPhysician     |
| POST   | `/admissions`                                    | Open a pending admission bound to a concurred screening                                                                                    | NurseCaseManager   |
| GET    | `/admissions/{admissionId}`                      | Read one admission with its three status dimensions and derived compliance fields                                                          | All roles          |
| GET    | `/admissions`                                    | List admissions, filterable by facility, patient, screening, interrupted-stay linkage and status dimensions                                | All roles          |
| POST   | `/admissions/{admissionId}/admit`                | Admit the patient; enforces the 48-hour screening window, facility posture and interrupted-stay linkage, and pins the QRP penalty snapshot | NurseCaseManager   |
| POST   | `/admissions/{admissionId}/deny`                 | Deny a pending admission after physician review                                                                                            | RehabPhysician     |
| POST   | `/admissions/{admissionId}/discharge`            | Discharge the patient to a destination; runs the four-hop compliance cascade and prices the stay                                           | NurseCaseManager   |
| POST   | `/admissions/{admissionId}/rescind-interruption` | Unlink an interrupted-stay continuation that was attached in error and restore both stays' standalone pricing                              | ComplianceOfficer  |
| POST   | `/plans-of-care`                                 | Sign an individualized overall plan of care; supersedes any earlier plan for the admission (OCC on Admission.version)                      | RehabPhysician     |
| GET    | `/plans-of-care/{planId}`                        | Read one plan of care                                                                                                                      | All roles          |
| GET    | `/plans-of-care`                                 | List plans of care, filterable by admission, author and status                                                                             | All roles          |
| POST   | `/therapy-weeks`                                 | Open a 7-day therapy measurement window; pins evaluation_mode from the ACTIVE plan of care                                                 | TherapyLead        |
| GET    | `/therapy-weeks/{weekId}`                        | Read one therapy week with its delivered minutes and qualifying-day count                                                                  | All roles          |
| GET    | `/therapy-weeks`                                 | List therapy weeks, filterable by admission, status, index and exception grantor                                                           | All roles          |
| POST   | `/therapy-weeks/{weekId}/evaluate`               | Evaluate the three-hour rule for the week under its pinned mode                                                                            | TherapyLead        |
| POST   | `/therapy-weeks/{weekId}/exception`              | Grant a documented physician exception to a week that failed the three-hour rule                                                           | RehabPhysician     |
| POST   | `/therapy-sessions`                              | Schedule a therapy session; resolves its therapy week, credits minutes by modality and enforces overlap, rest-buffer and daily-cap rules   | TherapyLead        |
| GET    | `/therapy-sessions/{sessionId}`                  | Read one therapy session with its credited minutes                                                                                         | All roles          |
| GET    | `/therapy-sessions`                              | List therapy sessions, filterable by admission, week, clinician, status and calendar date                                                  | All roles          |
| POST   | `/therapy-sessions/{sessionId}/deliver`          | Document a scheduled session as delivered, crediting its minutes to the week                                                               | TherapyLead        |
| POST   | `/therapy-sessions/{sessionId}/void`             | Void a session; a delivered session's minutes are removed from the week exactly                                                            | TherapyLead        |
| POST   | `/team-conferences`                              | Record the weekly interdisciplinary team conference for a therapy week                                                                     | NurseCaseManager   |
| GET    | `/team-conferences/{conferenceId}`               | Read one team conference record                                                                                                            | All roles          |
| GET    | `/team-conferences`                              | List team conferences, filterable by admission, therapy week, lead physician and status                                                    | All roles          |
| POST   | `/assessments`                                   | Open an IRF patient assessment instrument and compute its completion and transmission deadlines                                            | HimCoder           |
| GET    | `/assessments/{assessmentId}`                    | Read one assessment with its deadlines and lateness                                                                                        | All roles          |
| GET    | `/assessments`                                   | List assessments, filterable by admission, coder, transmitter, type and status                                                             | All roles          |
| POST   | `/assessments/{assessmentId}/complete`           | Complete the assessment item set                                                                                                           | HimCoder           |
| POST   | `/assessments/{assessmentId}/transmit`           | Transmit the assessment; timeliness is decided by the clock against transmission_deadline_at                                               | HimCoder           |
| POST   | `/compliance-reviews`                            | Open a compliance review for a facility period under a chosen method (OCC on Facility.version)                                             | ComplianceOfficer  |
| GET    | `/compliance-reviews/{reviewId}`                 | Read one compliance review with its cohort counts, percentage and outcome                                                                  | All roles          |
| GET    | `/compliance-reviews`                            | List compliance reviews, filterable by facility, method and status                                                                         | All roles          |
| POST   | `/compliance-reviews/{reviewId}/compute`         | Compute the compliance percentage for the review's cohort under its method                                                                 | ComplianceOfficer  |
| POST   | `/compliance-reviews/{reviewId}/certify`         | Certify a computed review; a FAIL outcome freezes admissions at the facility                                                               | ComplianceOfficer  |
| POST   | `/qrp-assessments`                               | Open a quality reporting program assessment for a facility reporting period                                                                | ComplianceOfficer  |
| GET    | `/qrp-assessments/{qrpId}`                       | Read one QRP assessment with its completeness percentage and penalty                                                                       | All roles          |
| GET    | `/qrp-assessments`                               | List QRP assessments, filterable by facility, fiscal year and status                                                                       | All roles          |
| POST   | `/qrp-assessments/{qrpId}/finalize`              | Finalize the QRP assessment and put its payment reduction into force for future admissions                                                 | ComplianceOfficer  |
| POST   | `/_clock/set_current_utc`                        | Set the server's logical UTC clock                                                                                                         | ComplianceOfficer  |

## 5. Error Code Catalogue

| Error ID                                 | HTTP Status Code         |
| ---------------------------------------- | ------------------------ |
| `ERR_UNAUTHENTICATED`                    | 401 Unauthorized         |
| `ERR_FORBIDDEN_ROLE`                     | 403 Forbidden            |
| `ERR_ROLE_CREDENTIAL_MISMATCH`           | 403 Forbidden            |
| `ERR_ACTING_CLINICIAN_INACTIVE`          | 403 Forbidden            |
| `ERR_SEGREGATION_OF_DUTIES`              | 403 Forbidden            |
| `ERR_FACILITY_ADMISSION_FROZEN`          | 403 Forbidden            |
| `ERR_INVALID_REQUEST`                    | 400 Bad Request          |
| `ERR_INVALID_SESSION_INTERVAL`           | 400 Bad Request          |
| `ERR_GROUP_SIZE_INVALID`                 | 400 Bad Request          |
| `ERR_INVALID_PERIOD`                     | 400 Bad Request          |
| `ERR_NOT_FOUND`                          | 404 Not Found            |
| `ERR_SCREENING_PATIENT_MISMATCH`         | 409 Conflict             |
| `ERR_WEEK_ADMISSION_MISMATCH`            | 409 Conflict             |
| `ERR_CROSS_FACILITY_MISMATCH`            | 409 Conflict             |
| `ERR_STALE_ADMISSION_VERSION`            | 412 Precondition Failed  |
| `ERR_STALE_FACILITY_VERSION`             | 412 Precondition Failed  |
| `ERR_INVALID_STATE`                      | 409 Conflict             |
| `ERR_ADMISSION_NOT_ACTIVE`               | 409 Conflict             |
| `ERR_ADMISSION_NOT_DISCHARGED`           | 409 Conflict             |
| `ERR_EXCEPTION_NOT_ALLOWED`              | 409 Conflict             |
| `ERR_NOT_INTERRUPTED_STAY`               | 409 Conflict             |
| `ERR_SCREENING_NOT_CONCURRED`            | 422 Unprocessable Entity |
| `ERR_SCREENING_WINDOW_EXPIRED`           | 422 Unprocessable Entity |
| `ERR_SCREENING_DOCUMENTATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SCREENER_CREDENTIAL_INVALID`        | 422 Unprocessable Entity |
| `ERR_PLAN_OF_CARE_MISSING`               | 422 Unprocessable Entity |
| `ERR_DISCIPLINE_NOT_IN_PLAN`             | 422 Unprocessable Entity |
| `ERR_CLINICIAN_DISCIPLINE_MISMATCH`      | 422 Unprocessable Entity |
| `ERR_CONFERENCE_LEAD_NOT_PHYSICIAN`      | 422 Unprocessable Entity |
| `ERR_CONFERENCE_PARTICIPANTS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_CONFERENCE_OUTSIDE_WEEK`            | 409 Conflict             |
| `ERR_CONFERENCE_ALREADY_RECORDED`        | 409 Conflict             |
| `ERR_PAI_ITEM_SET_INCOMPLETE`            | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_TYPE_DUPLICATE`          | 409 Conflict             |
| `ERR_CLINICIAN_SCHEDULE_CONFLICT`        | 409 Conflict             |
| `ERR_PATIENT_REST_BUFFER_VIOLATION`      | 409 Conflict             |
| `ERR_NO_OPEN_THERAPY_WEEK`               | 422 Unprocessable Entity |
| `ERR_THERAPY_WEEK_OVERLAP`               | 409 Conflict             |
| `ERR_WEEK_BEFORE_ADMISSION`              | 422 Unprocessable Entity |
| `ERR_WEEK_INDEX_DUPLICATE`               | 409 Conflict             |
| `ERR_DAILY_THERAPY_CAP_EXCEEDED`         | 409 Conflict             |
| `ERR_MRN_DUPLICATE`                      | 409 Conflict             |
| `ERR_CCN_DUPLICATE`                      | 409 Conflict             |
| `ERR_INTERRUPTION_WINDOW_EXCEEDED`       | 422 Unprocessable Entity |
| `ERR_PREDECESSOR_ALREADY_CONTINUED`      | 409 Conflict             |
| `ERR_INTERRUPTED_STAY_LINK_REQUIRED`     | 422 Unprocessable Entity |
| `ERR_EMPTY_COMPLIANCE_COHORT`            | 422 Unprocessable Entity |
| `ERR_COHORT_PAYMENT_UNSETTLED`           | 422 Unprocessable Entity |

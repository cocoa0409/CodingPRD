# Pretrial Services & Electronic Monitoring API — Product Requirements Document

## 1. Introduction

Pretrial services agencies sit at the intersection of judicial discretion and public safety: between arrest and trial, a defendant may be released into the community under a set of supervision conditions calibrated to their assessed risk. This document specifies the API for a pretrial-services and electronic-monitoring platform that governs that entire arc — booking a defendant, scoring their risk, converting a judicial release decision into an active supervision regime, and then operating the day-to-day machinery of that regime: scheduled check-ins, GPS/EM enrollment with curfew zones and location pings, drug and alcohol testing, court-date reminders and failure-to-appear tracking, violation review and sanction, supervision-level escalation, and the fee ledger that funds the program.

The platform serves four operational staff roles plus the defendant themselves, and it is deliberately built around segregation of duties: the officer who authors an assessment or reports a violation may never be the same person who approves or adjudicates it. Much of the system's behavior is time-sensitive and clock-driven — a check-in can only be marked missed after it comes due, a court event can only be recorded as a failure-to-appear once a grace period has elapsed — so the system runs on an explicit, settable logical clock rather than wall-clock time. Money (supervision fees) and physical inventory (electronic-monitoring devices) are both treated as strictly conserved quantities backed by append-only reasoning, and concurrent edits to a defendant's supervision level or an enrollment's curfew schedule are guarded by optimistic concurrency control.

This specification is the sole contract for implementers. It defines the response envelope, the role model, every entity's fields, every state machine and its side effects, every calculation and its constants, and the full error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `IntakeOfficer`, `SupervisingOfficer`, `JudicialOfficer`, `ProgramAdmin`, and `Defendant`.

- An `IntakeOfficer` books defendants and authors risk assessments.
- A `SupervisingOfficer` runs ongoing supervision — check-ins, electronic monitoring, testing, violations, fees, and level adjustments.
- A `JudicialOfficer` adjudicates assessments, release orders, and violations.
- A `ProgramAdmin` configures testing sites, device pools, and the logical clock, and processes ledger payments.
- A `Defendant` is a self-service actor who may complete their own check-ins and view their own record.

The first four roles carry an **opaque** identity: when `X-User-Role` is `IntakeOfficer`, `SupervisingOfficer`, `JudicialOfficer`, or `ProgramAdmin`, the `X-User-ID` value is an operator identifier not tied to any persisted entity. The server records it where a workflow demands provenance — for example as `submitted_by_user_id` on an assessment, `reported_by_user_id` and `adjudicated_by_user_id` on a violation, or `adjusted_by_user_id` on a level adjustment — but it never compares that identifier to any entity's `id`.

The `Defendant` role is **entity-backed**: when `X-User-Role` is `Defendant`, `X-User-ID` is the `id` of the acting `Defendant` record. Ownership checks on any resource that references a defendant compare that resource's `defendant_id` to `X-User-ID`. A defendant may retrieve their own defendant record, their own check-ins, and their own court events, and may complete a check-in only when that check-in's `defendant_id` equals their `X-User-ID`.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0.

Unless a specific workflow states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Two Property Tiers

Most top-level resources — `Defendant`, `RiskAssessment`, `ReleaseOrder`, `CheckIn`, `EMDevice`, `EMEnrollment`, `ViolationEvent`, `CourtEvent`, `DrugTest`, and `TestingSite` — carry the full set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp (three fractional digits) recording when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.7).

Four resources are **records rather than mutable resources** and carry only `id` and `created_at` — they have no `updated_at` and no `version` field: `CurfewWindow`, `LocationPing`, `LedgerEntry`, and `LevelAdjustment`. These are effectively append-only entries; once written they are not versioned or revised.

Whenever a derived field is recomputed as a side effect of some operation — a defendant's `cumulative_violation_score`, `balance_owed_cents`, `supervision_level`, `risk_tier`, or a device pool's `available_units` — that recomputation counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments.

### 2.5. The Logical Clock and Temporal Gating

The server keeps an explicit logical clock. On startup the clock reads exactly `2026-05-01T00:00:00Z`; before any clock-setting call it holds that default and never falls back to real wall-clock time. An admin-only test-driving capability advances the clock to a supplied `to_iso8601` instant, and the call responds with the new clock value as a single `current_utc` field in `data`. All "current clock" comparisons in this document — completion timestamps, adjudication timestamps, result timestamps, and every time-gated precondition — read this logical clock.

Several transitions are gated on the clock and may only proceed once their instant has passed. Marking a check-in missed requires the current clock to be strictly after its `due_at`. Recording a court event as a failure-to-appear requires the current clock to be strictly after the hearing instant plus the failure-to-appear grace period. Marking a drug test missed requires the current clock to be strictly after the test's `slot_end`. If any of these transitions is attempted before its clock precondition is met, it is rejected with `ERR_PRECONDITION_TIME_NOT_REACHED` (HTTP 409).

### 2.6. Money, Precision, and Ledger Conservation

All monetary amounts are integer counts of cents. Fee computations apply an administrative surcharge and round each line to whole cents using **round half up** — halves round upward — and the pinned order is to round each line **first** and only then sum the rounded lines; the system never sums the raw un-rounded lines and rounds once at the end. The precise fee formula, its rates, and its two variants live in §3.8.

A defendant's `balance_owed_cents` is a strictly conserved quantity: it always equals the signed sum of that defendant's `LedgerEntry.amount_cents`. A `CHARGE` contributes a positive amount; a `PAYMENT` and a `WAIVER` each contribute a negative amount; a `REVERSAL` contributes exactly the negation of the entry it reverses. Consequently a charge and its reversal net to zero, and no operation may make the running balance diverge from that signed sum.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent resource's `version`, and for those two the version field is a required, non-optional input.

Recording a manual supervision-level adjustment against a defendant requires `expected_defendant_version` in the request body, carrying the client's last-observed `version` of that `Defendant`. If it does not match the defendant's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). A prior adjustment — or an automatic escalation cascade that raised the supervision level — legitimately advances the defendant's `version`, so a stale-version write is refused rather than silently overwriting the newer level.

Adding a curfew window to an enrollment requires `expected_enrollment_version` in the request body, carrying the client's last-observed `version` of that `EMEnrollment`. If it does not match the enrollment's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). Another curfew edit or a lifecycle transition on the enrollment moves its `version`, so the client's window set is treated as stale.

No other endpoint takes a version field; endpoints not named here perform no OCC check.

### 2.8. Segregation of Duties

Two review workflows enforce a strict four-eyes rule. For a risk assessment, the actor who moved it from `DRAFT` to `SUBMITTED` (recorded in `submitted_by_user_id`) may not be the actor who approves or rejects it: an approve or reject whose `X-User-ID` equals `submitted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). For a violation, the reporting officer (recorded in `reported_by_user_id`) may not be the actor who adjudicates it: an adjudication — whether to sanction or to dismiss — whose `X-User-ID` equals `reported_by_user_id` is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.9. Cascades, Auto-Created Records, and State Consistency

Several transitions produce cascading side effects that create or mutate other entities in the same operation. Marking a check-in missed, recording a court failure-to-appear, and recording a positive drug-test result each auto-create a `ViolationEvent` in `REPORTED` status, stamping the originating record's `id` into the new violation's `source_ref` (a free provenance identifier, not a validated foreign key); every cascade-created violation carries a null `reported_by_user_id` (so any adjudicator satisfies segregation of duties), a `severity_points` of 0, and both adjudication fields null. Recording a location ping that is out of compliance auto-creates a `CURFEW` violation the same way. Sanctioning a violation may, in turn, escalate the defendant's supervision level, which itself creates both a `LevelAdjustment` and an escalation check-in. Each of these cascades is described in full within the workflow that triggers it (§3). Every entity a cascade mutates has its `updated_at` refreshed and its `version` incremented.

### 2.10. Nested Resource Retrieval and Validation Ordering

Many paths address a resource nested under a defendant, an enrollment, a site, or an assessment. Path identifiers are validated left to right, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any deeper identifier or body rule is considered.

Across all endpoints, validation is evaluated in a fixed priority order, and the first failing check determines the error returned:

1. Authentication — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the acting role is permitted for the operation, else `ERR_UNAUTHORIZED` (403).
3. Existence — every path-referenced resource resolves, else `ERR_NOT_FOUND` (404).
4. State legality — the target is in a state permitting the operation, else `ERR_INVALID_STATE` (409).
5. Defendant-active gate (EM activation only) — the enrollment's defendant is `ACTIVE`, else `ERR_DEFENDANT_NOT_ACTIVE` (409).
6. Segregation of duties (assessment and violation adjudication) — actor differs from the originator, else `ERR_SEGREGATION_OF_DUTIES` (409).
7. Required ordered condition (drug-test scheduling, EM activation) — the governing release order carries the needed condition, else `ERR_CONDITION_NOT_ORDERED` (409).
8. Assessment-approved gate (release-order ordering) — the linked assessment is `APPROVED`, else `ERR_ASSESSMENT_NOT_APPROVED` (409).
9. Curfew-window overlap — the new window does not overlap an existing one, else `ERR_CURFEW_WINDOW_OVERLAP` (409).
10. Testing-site capacity — the requested slot fits within site capacity, else `ERR_SLOT_CAPACITY_EXCEEDED` (409).
11. Time-gated precondition — the clock precondition for a missed/FTA transition is met, else `ERR_PRECONDITION_TIME_NOT_REACHED` (409).
12. Device availability (EM activation) — the device pool has a free unit, else `ERR_NO_DEVICE_AVAILABLE` (409).
13. Optimistic concurrency — the expected version matches, else `ERR_STALE_VERSION` (412).
14. Body validation — required fields present, types and ranges valid, else `ERR_VALIDATION` (400).
15. Enum membership — every enum field value is a member of its declared set, else `ERR_INVALID_ENUM` (422).

### 2.11. Device Unit Conservation

An `EMDevice` represents an inventory pool. Its `available_units` is a strictly conserved count: it always equals `total_units` minus the number of `EMEnrollment` rows referencing that pool whose status is `ACTIVE` or `SUSPENDED`. Activating an enrollment consumes one unit; terminating an active or suspended enrollment returns one unit; a suspended enrollment continues to hold its unit. An activate paired with its later terminate therefore leaves `available_units` unchanged.

## 3. Business Logic & Workflows

### 3.1. Defendant Intake and Risk Assessment

An `IntakeOfficer` books a defendant into the system, supplying a `case_number` (a court case identifier that must be non-empty and unique across defendants), the defendant's `full_name`, their `date_of_birth` as an ISO 8601 date, and an optional `indigent` flag that defaults to false. A new defendant begins with `supervision_status` of `PRETRIAL_PENDING`. Their `supervision_level` and `risk_tier` both begin null, `cumulative_violation_score` begins at 0, and `balance_owed_cents` begins at 0.

The same intake officer authors a **risk assessment** for a defendant by submitting the target `defendant_id`, an `instrument_type`, the counts `prior_failures` and `pending_charges_count` (each a non-negative integer), an optional `pending_violent_charge` flag defaulting to false, an `employment_status`, a `residence_stability`, and an optional `substance_flag` defaulting to false. A new assessment is created in `DRAFT` status with `raw_score` and `recommended_level` both null and `submitted_by_user_id` null.

The assessment lifecycle is `DRAFT → SUBMITTED`, then `SUBMITTED` either loops back to `DRAFT` (a revision kickback) or advances to the terminal `APPROVED` or `REJECTED`. Submission is performed by the authoring intake officer; approval, rejection, and kickback to draft are performed by a `JudicialOfficer`. Any transition attempted from a status that does not permit it is rejected with `ERR_INVALID_STATE`.

**Submission** (`DRAFT → SUBMITTED`) requires the assessment to be in `DRAFT` and requires all scoring inputs for the chosen instrument to be present. On submission the system computes `raw_score` and then `recommended_level` (§3.2 states both formulas), and stamps `submitted_by_user_id` with the submitting actor's `X-User-ID`.

**Kickback** (`SUBMITTED → DRAFT`) requires the assessment to be in `SUBMITTED` and clears `submitted_by_user_id` so the assessment can be resubmitted, possibly by a different author; this revision loop is the reason the assessment lifecycle is cyclic.

**Approval** (`SUBMITTED → APPROVED`) requires the assessment to be in `SUBMITTED` and requires the approving `X-User-ID` to differ from `submitted_by_user_id` (segregation of duties, §2.8). On approval, the defendant's `risk_tier` is set from the assessment's `recommended_level` by the mapping `MINIMUM → LOW`, `MEDIUM → MODERATE`, `MAXIMUM → HIGH`.

**Rejection** (`SUBMITTED → REJECTED`) requires the assessment to be in `SUBMITTED` and likewise requires the rejecting `X-User-ID` to differ from `submitted_by_user_id`. Rejection carries no further side effect.

### 3.2. Scoring the Assessment: Raw Score and Recommended Level

The **raw score** is computed on submission from the single assessment being submitted, using no other entities. Two instrument variants exist. The `SCREENING` instrument uses only two factors: it adds four points per prior failure-to-appear (`prior_failures`) and two points per pending charge (`pending_charges_count`). The `FULL` instrument adds three more factors on top of those two: an additional three points if `employment_status` is `UNEMPLOYED`, an additional three points if `residence_stability` is `UNSTABLE`, and an additional five points if `substance_flag` is true. Because the `FULL` instrument only ever adds non-negative terms to the same base, its score is always greater than or equal to the `SCREENING` score on identical inputs. The score is an integer point total.

The **recommended level** is then computed from the raw score and the `pending_violent_charge` flag, and is evaluated as a strict ladder with inclusive thresholds. If `pending_violent_charge` is true, the recommended level is `MAXIMUM` regardless of the score — this violent-charge override supersedes the numeric ladder entirely. Otherwise, a raw score of at least 16 yields `MAXIMUM`; a raw score of at least 8 (but below 16) yields `MEDIUM`; and any lower score yields `MINIMUM`. Both threshold comparisons are inclusive (a score exactly equal to a threshold lands in the higher band).

### 3.3. Judicial Review and Release Orders

A `JudicialOfficer` proposes a **release order** for a defendant by submitting the `defendant_id`, the `assessment_id` the order relies upon, a `decision` of either `RELEASE` or `DETAIN`, and an `ordered_conditions` array drawn from the set `CURFEW`, `NO_CONTACT`, `GPS_MONITORING`, `DRUG_TESTING`, and `CHECK_IN`. A new order is created in `PROPOSED` status. The release-order lifecycle is `PROPOSED → ORDERED`, with `PROPOSED → DENIED` and `ORDERED → VACATED` as the other transitions; `DENIED` and `VACATED` are terminal. All release-order transitions are performed by a `JudicialOfficer`.

**Ordering** (`PROPOSED → ORDERED`) requires the order to be in `PROPOSED` and requires the linked risk assessment to be in `APPROVED` status; if the linked assessment is not approved, the transition is rejected with `ERR_ASSESSMENT_NOT_APPROVED`. When the order is granted and its `decision` is `RELEASE`, the defendant's supervision is activated: `supervision_status` moves from `PRETRIAL_PENDING` to `ACTIVE`, and `supervision_level` is set from the linked assessment's `recommended_level`. When the decision is `DETAIN`, ordering the release order does not activate the defendant.

**Denial** (`PROPOSED → DENIED`) requires the order to be in `PROPOSED` and carries no side effect. **Vacatur** (`ORDERED → VACATED`) requires the order to be in `ORDERED` and sets the defendant's `supervision_status` to `TERMINATED`.

Independently, a defendant's own supervision status can be advanced from `ACTIVE` to the terminal `DISCHARGED` or `TERMINATED` by a `JudicialOfficer` or `SupervisingOfficer`, via a defendant transition carrying `to_status`; each of those requires the defendant to currently be `ACTIVE`.

### 3.4. Supervision Conditions: Check-Ins

A `SupervisingOfficer` schedules a **check-in** for a defendant by submitting the `defendant_id` and a `due_at` instant. A scheduled check-in starts in `SCHEDULED` status with `origin` of `MANUAL` and `completed_at` null. Check-ins reach either the terminal `COMPLETED` or `MISSED`.

**Completion** (`SCHEDULED → COMPLETED`) may be performed by the owning defendant themselves — where the acting `X-User-ID` equals the check-in's `defendant_id` — or by a `SupervisingOfficer` on the defendant's behalf. It requires the check-in to be in `SCHEDULED`, and on success stamps `completed_at` with the current clock.

**Marking missed** (`SCHEDULED → MISSED`) is performed by a `SupervisingOfficer`, requires the check-in to be in `SCHEDULED`, and requires the current clock to be strictly after `due_at` (otherwise `ERR_PRECONDITION_TIME_NOT_REACHED`). Marking a check-in missed cascades the automatic creation of a `ViolationEvent` with `violation_type` `MISSED_CHECK_IN` and `severity` `MODERATE`, in `REPORTED` status, with the check-in's `id` recorded as its `source_ref`.

Some check-ins are not scheduled by an officer at all: the supervision-level escalation cascade (§3.7) auto-creates a check-in whose `origin` is `ESCALATION`. Callers can filter a defendant's check-ins by `status` and by `origin`.

### 3.5. Electronic Monitoring: Enrollment, Curfew Windows, and Location Pings

Before any monitoring can begin, a `ProgramAdmin` stands up an **EM device pool** with a `model_name` and a `total_units` count (non-negative); the pool's `available_units` starts equal to `total_units`. A `SupervisingOfficer` then creates an **EM enrollment** linking a defendant to a pool by submitting the `defendant_id` and the `device_id`. A new enrollment begins in `PENDING` status with `activated_at` null.

The enrollment lifecycle is cyclic: `PENDING → ACTIVE`, `ACTIVE ↔ SUSPENDED`, and either `ACTIVE → TERMINATED` or `SUSPENDED → TERMINATED`; `TERMINATED` is terminal. All enrollment transitions are performed by a `SupervisingOfficer`.

**Activation** (`PENDING → ACTIVE`) has four preconditions, checked after state legality: the enrollment must be `PENDING`; the enrollment's defendant must be in `supervision_status` `ACTIVE` (otherwise `ERR_DEFENDANT_NOT_ACTIVE`); the defendant must have a release order in `ORDERED` status whose `ordered_conditions` include `GPS_MONITORING` (otherwise `ERR_CONDITION_NOT_ORDERED`); and the referenced device pool must have at least one free unit, meaning `available_units` of 1 or more (otherwise `ERR_NO_DEVICE_AVAILABLE`). On activation, one unit is assigned — the pool's `available_units` is decremented by one — and `activated_at` is stamped with the current clock.

**Suspension** (`ACTIVE → SUSPENDED`) requires the enrollment to be `ACTIVE` and leaves the assigned unit in place. **Resumption** (`SUSPENDED → ACTIVE`) requires the enrollment to be `SUSPENDED`, assigns no new unit, and is what makes the enrollment machine cyclic. **Termination** from either `ACTIVE` or `SUSPENDED` returns the held unit — the pool's `available_units` is incremented by one.

**Curfew windows.** A `SupervisingOfficer` attaches a **curfew window** to an enrollment. The window is defined by `day_of_week` (an integer 0 through 6, where 0 is Monday and 6 is Sunday), a `start_minute` (0 through 1439, minutes from local midnight, inclusive), and an `end_minute` (1 through 1440, exclusive, and strictly greater than `start_minute`); the window is the half-open interval from `start_minute` up to but not including `end_minute`. Because a curfew window write is guarded by optimistic concurrency, the request must also carry `expected_enrollment_version` matching the enrollment's current `version`, or it is refused with `ERR_STALE_VERSION` (§2.7). A new window may not overlap an existing window on the same enrollment and the same `day_of_week`; overlap is judged on the half-open intervals, so two windows that merely touch end-to-start are adjacent and allowed, while any true overlap is rejected with `ERR_CURFEW_WINDOW_OVERLAP`. Curfew windows are append-only records and carry only `id` and `created_at`; each window references its owning enrollment through `enrollment_id`, derived from the path. Windows can be listed and filtered by `day_of_week`.

**Location pings.** A `SupervisingOfficer` or a `ProgramAdmin` records a **GPS ping** on an enrollment by submitting the `pinged_at` instant and an `at_home` boolean stating whether the device was at the approved residence at ping time. The system computes `is_curfew_violation`: it takes the ping's minute-of-day and day-of-week from `pinged_at` in UTC (day 0 being Monday), and the ping is a curfew violation exactly when `at_home` is false **and** the enrollment has a curfew window whose `day_of_week` matches the ping's day and whose half-open interval contains the ping's minute-of-day (that is, the minute is at least the window's `start_minute` and strictly less than its `end_minute`). When the ping is a curfew violation, the system auto-creates a `ViolationEvent` with `violation_type` `CURFEW` and `severity` `MINOR`, in `REPORTED` status, recording the ping's `id` as its `source_ref`. Location pings are append-only records carrying only `id` and `created_at`.

### 3.6. Court Dates, Reminders, and Failure-to-Appear

An `IntakeOfficer` or `SupervisingOfficer` schedules a **court event** for a defendant by submitting the `defendant_id`, the scheduled `hearing_at` instant, and an optional `reminder_lead_days` (a non-negative integer; a negative value is rejected with `ERR_VALIDATION`) that defaults to 3. On creation the system computes `reminder_due_at` as the hearing instant minus that whole number of lead days. A court event starts in `SCHEDULED` status and reaches one of the terminal outcomes `APPEARED`, `FTA`, or `CONTINUED`. A `SupervisingOfficer` records the outcome.

Recording an **appearance** (`SCHEDULED → APPEARED`) and recording a **continuance** (`SCHEDULED → CONTINUED`) each require the event to be `SCHEDULED` and carry no side effect. Recording a **failure-to-appear** (`SCHEDULED → FTA`) requires the event to be `SCHEDULED` and requires the current clock to be strictly after the hearing instant plus a failure-to-appear grace period of 2 hours; before that grace period elapses the transition is rejected with `ERR_PRECONDITION_TIME_NOT_REACHED`. Recording a failure-to-appear cascades the automatic creation of a `ViolationEvent` with `violation_type` `FTA` and `severity` `MAJOR`, in `REPORTED` status, with the court event's `id` as its `source_ref`.

### 3.7. Violations, Adjudication, and Supervision-Level Escalation

A `SupervisingOfficer` files a **violation** directly by submitting the `defendant_id`, a `violation_type` (one of `CURFEW`, `MISSED_CHECK_IN`, `POSITIVE_TEST`, `FTA`, `NEW_ARREST`, `OTHER`), and a `severity` band (`MINOR`, `MODERATE`, or `MAJOR`). The violation is created in `REPORTED` status with `reported_by_user_id` stamped from the reporting officer's `X-User-ID`; `severity_points` begins at 0. Violations may also arrive by cascade from missed check-ins, failures-to-appear, positive drug results, and curfew pings, as described in the surrounding sections.

The violation lifecycle is a review fork-join: `REPORTED → UNDER_REVIEW`, then `UNDER_REVIEW` diverges to either the terminal `ADJUDICATED_SANCTION` or the terminal `ADJUDICATED_DISMISS`. All violation transitions are performed by a `JudicialOfficer`. Moving a violation to `UNDER_REVIEW` requires it to be `REPORTED` and has no side effect. Both adjudication branches require the violation to be `UNDER_REVIEW` and require the adjudicating `X-User-ID` to differ from `reported_by_user_id` (segregation of duties, else `ERR_SEGREGATION_OF_DUTIES`), and both stamp `adjudicated_by_user_id` and `adjudicated_at` (the current clock).

The two branches then diverge. A **dismissal** (`UNDER_REVIEW → ADJUDICATED_DISMISS`) leaves `severity_points` at 0 and triggers no escalation. A **sanction** (`UNDER_REVIEW → ADJUDICATED_SANCTION`) sets `severity_points` from the severity band — `MINOR` is 3 points, `MODERATE` is 6 points, `MAJOR` is 10 points — and then recomputes the defendant's `cumulative_violation_score`.

The **cumulative violation score** is the sum of `severity_points` across the defendant's violations that are in `ADJUDICATED_SANCTION` status and whose `adjudicated_at` falls within a rolling 90-day window ending at the current clock (that is, `adjudicated_at` is at or after the current clock minus 90 days). Ordering and ties are irrelevant; it is a pure sum of integer points.

**Escalation cascade.** If, after a sanction, the recomputed `cumulative_violation_score` is at least 10, the defendant's supervision level escalates one step along the ladder `MINIMUM → MEDIUM → MAXIMUM` (a defendant already at `MAXIMUM` stays there). This escalation is itself a two-part cascade: it creates a `LevelAdjustment` recording the change with `source` `AUTO_ESCALATION` and `adjusted_by_user_id` null (its `from_level` is the level before the step and its `to_level` is the level after), **and** it creates an escalation check-in — a `CheckIn` with `origin` `ESCALATION`, in `SCHEDULED` status, whose `due_at` is the current clock plus 7 days. Raising `supervision_level` mutates the defendant, so its `version` advances (which is why a client holding a pre-escalation version will later be refused under OCC, §2.7). The entire sanction operation — recomputing `cumulative_violation_score` together with any level escalation — increments the defendant's `version` exactly once in total, not once per recomputed derived field. If the defendant's `supervision_level` is currently null, no escalation occurs and neither the `LevelAdjustment` nor the escalation check-in is created, even when the recomputed score reaches the threshold.

### 3.8. Drug and Alcohol Testing

Testing runs at collection **sites**. A `ProgramAdmin` creates a `TestingSite` with a `name` and a `slot_capacity` (at least 1), where capacity is the maximum number of tests whose slots may overlap a single instant at that site. A `SupervisingOfficer` schedules a **drug test** by submitting the `defendant_id`, the `site_id`, a `test_kind` of `DRUG` or `ALCOHOL`, and a `slot_start` instant. The system computes `slot_end` as `slot_start` plus 30 minutes, so the slot occupies the half-open interval from `slot_start` up to but not including `slot_end`. Scheduling requires that the defendant have the `DRUG_TESTING` condition on an ordered release order, or it is rejected with `ERR_CONDITION_NOT_ORDERED`. Scheduling also enforces site capacity: the count of existing tests at that site in `SCHEDULED` or `COLLECTED` status whose half-open slots overlap the requested slot must be strictly less than the site's `slot_capacity`, otherwise `ERR_SLOT_CAPACITY_EXCEEDED`. A new test starts in `SCHEDULED` status with `result_recorded_at` null.

The test lifecycle is `SCHEDULED → COLLECTED`, then `COLLECTED` to either `RESULT_POSITIVE` or `RESULT_NEGATIVE`, or `SCHEDULED → MISSED`; the three result states and `MISSED` are terminal. All drug-test transitions are performed by a `SupervisingOfficer`. **Collection** (`SCHEDULED → COLLECTED`) requires the test to be `SCHEDULED`. Recording a **negative result** (`COLLECTED → RESULT_NEGATIVE`) requires the test to be `COLLECTED` and stamps `result_recorded_at` with the current clock. Recording a **positive result** (`COLLECTED → RESULT_POSITIVE`) requires the test to be `COLLECTED`, stamps `result_recorded_at`, and cascades the automatic creation of a `ViolationEvent` with `violation_type` `POSITIVE_TEST` and `severity` `MODERATE`, in `REPORTED` status, recording the drug test's `id` as its `source_ref`. **Marking missed** (`SCHEDULED → MISSED`) requires the test to be `SCHEDULED` and requires the current clock to be strictly after `slot_end`, else `ERR_PRECONDITION_TIME_NOT_REACHED`. Drug tests at a site can be listed and filtered by `status`.

### 3.9. Supervision Fees, the Ledger, and Level Adjustments

**Fee assessment.** A `SupervisingOfficer` or `ProgramAdmin` assesses a supervision fee for a defendant by submitting `supervision_days`, `em_days`, and `scheduled_test_count` (each a required non-negative integer). The fee is built from three lines, each rounded to whole cents (round half up) **before** any summation. The supervision line is the daily supervision rate of 300 cents times `supervision_days`, then multiplied by one plus a 7.5 percent administrative surcharge (a factor of 1.075), rounded. The EM line is the EM daily rate of 650 cents times `em_days`, times 1.075, rounded. The testing line is the per-test rate of 2500 cents times `scheduled_test_count`, times 1.075, rounded.

Which lines are charged depends on the defendant's `indigent` flag, giving two variants. For a non-indigent defendant (the `ASSESSED` variant), the charged amount is the sum of all three rounded lines — supervision, EM, and testing. For an indigent defendant (the `ADJUSTED` variant), the supervision and EM lines are waived entirely and only the rounded testing line is charged. Because each line is rounded before summing, the `ASSESSED` total can differ by a cent from a sum-then-round computation; the per-line-first order is the pinned, required behavior. Assessing a fee creates a `LedgerEntry` with `entry_type` `CHARGE` and `source` `SUPERVISION_FEE`, whose `amount_cents` is the positive charge, and then recomputes the defendant's `balance_owed_cents`. The response returns the newly created `CHARGE` `LedgerEntry` with HTTP 201.

**Other ledger entries.** A `SupervisingOfficer` or `ProgramAdmin` posts a `PAYMENT`, `WAIVER`, or `REVERSAL` ledger entry by submitting the `entry_type` and the fields its variant requires. Posting `entry_type` `CHARGE` to this endpoint is rejected with `ERR_VALIDATION`, since charges are created only through the fee endpoint. For a `PAYMENT` or a `WAIVER`, `amount_cents` is required; the system takes its absolute value and records the entry's `amount_cents` as that value negated — always a negative number reducing the balance, regardless of the sign the client supplied. For a `REVERSAL`, any supplied `amount_cents` is ignored; the client instead provides the `reverses_entry_id` of the prior entry being reversed (a self-reference within the defendant's ledger, not a validated cross-entity foreign key), which must resolve to an existing ledger entry belonging to this same defendant or the post is rejected with `ERR_VALIDATION`, and the system sets this entry's `amount_cents` to the exact negation of the referenced entry's amount. Every ledger entry carries a `source` that defaults to `MANUAL` (fee charges carry `SUPERVISION_FEE`). Ledger entries are append-only records carrying only `id` and `created_at`, and every post recomputes `balance_owed_cents` as the signed sum of the defendant's entries. Ledger entries can be listed and filtered by `entry_type`.

**Manual level adjustments.** A `SupervisingOfficer` or `JudicialOfficer` records a manual supervision-level adjustment by submitting `expected_defendant_version`, a target `to_level` (`MINIMUM`, `MEDIUM`, or `MAXIMUM`), and an optional `reason`. This write is guarded by optimistic concurrency: `expected_defendant_version` must match the defendant's current `version`, or the request is refused with `ERR_STALE_VERSION` (§2.7). On success the system sets the defendant's `supervision_level` to `to_level`, creates a `LevelAdjustment` whose `from_level` is the level immediately before the change, whose `source` is `MANUAL`, and whose `adjusted_by_user_id` is the acting `X-User-ID`, and increments the defendant's `version` by one; the response returns the created `LevelAdjustment` with HTTP 201. Level adjustments are append-only records carrying only `id` and `created_at`, and can be listed and filtered by `source`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, and the clock-setting capability, return `200 OK`. All list and retrieval operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/testing-sites` | Create a testing site | ProgramAdmin |
| GET | `/testing-sites/{id}` | Get a testing site | ProgramAdmin, SupervisingOfficer, IntakeOfficer, JudicialOfficer |
| GET | `/testing-sites/{id}/drug-tests` | List drug tests at a site | ProgramAdmin, SupervisingOfficer, IntakeOfficer, JudicialOfficer |
| POST | `/em-devices` | Create an EM device pool | ProgramAdmin |
| GET | `/em-devices/{id}` | Get an EM device pool | ProgramAdmin, SupervisingOfficer, IntakeOfficer, JudicialOfficer |
| GET | `/em-devices/{id}/enrollments` | List enrollments on a device pool | ProgramAdmin, SupervisingOfficer, IntakeOfficer, JudicialOfficer |
| POST | `/defendants` | Create a defendant | IntakeOfficer |
| GET | `/defendants/{id}` | Get a defendant | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin, Defendant |
| GET | `/defendants` | List defendants | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/defendants/{id}/transition` | Discharge or terminate a defendant | JudicialOfficer, SupervisingOfficer |
| POST | `/defendants/{id}/level-adjustments` | Record a manual level adjustment (OCC) | SupervisingOfficer, JudicialOfficer |
| GET | `/defendants/{id}/level-adjustments` | List a defendant's level adjustments | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/defendants/{id}/fees` | Assess a supervision fee | SupervisingOfficer, ProgramAdmin |
| POST | `/defendants/{id}/ledger-entries` | Post a payment, waiver, or reversal | SupervisingOfficer, ProgramAdmin |
| GET | `/defendants/{id}/ledger` | List a defendant's ledger entries | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/assessments` | Create a risk assessment (DRAFT) | IntakeOfficer |
| POST | `/assessments/{id}/transition` | Advance a risk assessment | IntakeOfficer, JudicialOfficer |
| GET | `/assessments/{id}` | Get a risk assessment | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| GET | `/defendants/{id}/assessments` | List a defendant's assessments | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/release-orders` | Propose a release order | JudicialOfficer |
| POST | `/release-orders/{id}/transition` | Order, deny, or vacate a release order | JudicialOfficer |
| GET | `/defendants/{id}/release-orders` | List a defendant's release orders | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| GET | `/assessments/{id}/release-orders` | List release orders relying on an assessment | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/check-ins` | Schedule a check-in | SupervisingOfficer |
| POST | `/check-ins/{id}/transition` | Complete or mark-missed a check-in | Defendant, SupervisingOfficer |
| GET | `/defendants/{id}/check-ins` | List a defendant's check-ins | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin, Defendant |
| POST | `/em-enrollments` | Create an EM enrollment (PENDING) | SupervisingOfficer |
| POST | `/em-enrollments/{id}/transition` | Activate, suspend, resume, or terminate an enrollment | SupervisingOfficer |
| GET | `/em-enrollments/{id}` | Get an EM enrollment | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| GET | `/defendants/{id}/em-enrollments` | List a defendant's enrollments | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/em-enrollments/{id}/curfew-windows` | Add a curfew window (OCC, overlap-checked) | SupervisingOfficer |
| GET | `/em-enrollments/{id}/curfew-windows` | List curfew windows on an enrollment | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/em-enrollments/{id}/pings` | Record a GPS location ping | SupervisingOfficer, ProgramAdmin |
| GET | `/em-enrollments/{id}/pings` | List pings on an enrollment | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/violations` | File a violation (REPORTED) | SupervisingOfficer |
| POST | `/violations/{id}/transition` | Review and adjudicate a violation | JudicialOfficer |
| GET | `/violations/{id}` | Get a violation | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| GET | `/defendants/{id}/violations` | List a defendant's violations | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |
| POST | `/court-events` | Schedule a court event | IntakeOfficer, SupervisingOfficer |
| POST | `/court-events/{id}/transition` | Record appearance, FTA, or continuance | SupervisingOfficer |
| GET | `/defendants/{id}/court-events` | List a defendant's court events | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin, Defendant |
| POST | `/drug-tests` | Schedule a drug/alcohol test | SupervisingOfficer |
| POST | `/drug-tests/{id}/transition` | Collect, record result, or mark-missed a test | SupervisingOfficer |
| GET | `/defendants/{id}/drug-tests` | List a defendant's drug tests | IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEFENDANT_NOT_ACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CONDITION_NOT_ORDERED` | 409 |
| `ERR_ASSESSMENT_NOT_APPROVED` | 409 |
| `ERR_CURFEW_WINDOW_OVERLAP` | 409 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_PRECONDITION_TIME_NOT_REACHED` | 409 |
| `ERR_NO_DEVICE_AVAILABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |

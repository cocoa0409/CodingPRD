# Nurse-Family Home Visiting API — Product Requirements Document

## 1. Introduction

The Nurse-Family Home Visiting program pairs first-time mothers with registered home-visiting nurses from pregnancy through the child's second birthday. This API is the system of record for the whole arc of that relationship: registering a prospective mother at intake, capturing her informed consent, confirming her eligibility, enrolling her, assigning a nurse, planning and conducting the schedule of home visits, administering developmental and maternal screenings, linking families to community benefits, tracking whether families are receiving the intended "dosage" of visits, supervising nurse caseloads, and rolling everything up into the outcome and MIECHV (Maternal, Infant, and Early Childhood Home Visiting) reports that the program is accountable for.

The program's central operational tension is that a home-visiting model only works when families actually receive visits on schedule. The system therefore treats visit completion as a first-class signal: every completed, missed, canceled, or rescheduled visit feeds a running dosage calculation, and when a family's dosage falls below the program floor the system raises an alert that cascades into the responsible nurse's caseload and pulls the case into supervisory review. Because caseloads, eligibility windows, and reporting periods are all bounded in time, the platform runs on a controllable logical clock rather than wall-clock time, so that dosage gating, on-time determinations, and period-based reporting are deterministic and auditable.

This document specifies the complete contract: the shared response and pagination envelope, the role model and its ownership semantics, the entity lifecycles and their state machines, the calculations (caseload weighting, dosage in two variants, risk tiering, assessment banding, on-time determination, and pooled program rates), the validation rules and their precedence, and the full endpoint and error catalogues. Everything an implementer needs is here; nothing outside this document is assumed.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (with the sole exception of no request — there are no anonymous endpoints) must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are well-formed but the named role is not permitted to invoke the requested endpoint per the access matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly four roles, spelled exactly as follows: `IntakeCoordinator`, `HomeVisitNurse`, `Supervisor`, and `ProgramAdmin`.

- `IntakeCoordinator` handles intake, consent, the enrollment lifecycle, and visit cancellation. When `X-User-Role` is `IntakeCoordinator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept and record it but does not compare it to any entity's `id`.
- `HomeVisitNurse` conducts home visits, records assessments, and manages referrals for their own caseload. When `X-User-Role` is `HomeVisitNurse`, `X-User-ID` is the `id` of the acting `Nurse`; ownership checks on any resource that references a nurse compare the resource's `nurse_id` to `X-User-ID`. In particular, the nurse-driven visit transitions require that `X-User-ID` equal the visit's `nurse_id`, and a mismatch is rejected with `ERR_NOT_VISIT_OWNER` (HTTP 403).
- `Supervisor` assigns nurses, manages caseloads, and runs supervision sessions. When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting `Supervisor`; ownership checks on any resource that references a supervisor compare the resource's `supervisor_id` to `X-User-ID`. Signing a supervision session requires that `X-User-ID` equal the session's `supervisor_id`, and a mismatch is rejected with `ERR_NOT_SESSION_OWNER` (HTTP 403).
- `ProgramAdmin` manages staff records, outcome measures, MIECHV reporting, and the logical clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are always returned sorted by `created_at` in ascending order (oldest first) — and because many records can share the same logical-clock `created_at`, ties are broken by ascending creation (insertion) order so the ordering is stable and deterministic — and any additional filters an endpoint offers are applied before pagination.

For every list response, the `meta` object carries the pagination bookkeeping fields: `limit` and `offset` echo the values in effect, `total_count` reports the number of records matching the filters before the limit/offset window is applied, and `has_more` is true when records remain beyond the current window.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp (same format as `created_at`) and an integer `version`. The `version` begins at 1 when the resource is created and increments by 1 on every mutation that changes the resource; whenever a resource is mutated, its `updated_at` is refreshed to the current logical clock time. When a computed or system field on a resource changes as a side effect of another operation — for example a nurse's `current_caseload_weight` changing because an assignment was created or ended — that counts as a mutation of the affected resource and advances its `version` and `updated_at` accordingly.

### 2.5. The Logical Clock and Temporal Gating

The system does not read wall-clock time. Instead it maintains a single logical clock whose server-startup default is exactly `2026-03-01T00:00:00Z`; before any clock-setting call is made, reads of the clock return exactly this default and never fall back to real time. A `ProgramAdmin` may advance (or otherwise set) the clock by supplying a `to_iso8601` instant, and the response echoes the new value as `current_utc`. The logical clock governs every time-sensitive computation in the system: the "to-date" gating of dosage (which visits have come due), the on-time determination at visit completion, the `connected_at` stamp written when a referral is connected, the `updated_at` stamp on every mutation, and the freezing of pooled metrics when a MIECHV report is finalized.

### 2.6. Numeric Precision and Rounding

Monetary-style and rate computations in this system are carried to two decimal places using round-half-up. This applies to caseload weights (both the per-assignment weight and the nurse's summed `current_caseload_weight`), to the dosage percentages, to outcome-measure `rate_pct`, and to the pooled program on-time rate. Where a calculation is defined as a ratio and its denominator is zero, the resulting percentage is null rather than zero. Flag counts, score sums, gestational-age comparisons, and whole-day date differences are integer computations and are not rounded to decimals.

### 2.7. Optimistic Concurrency on Nurse Reassignment

Creating an assignment is the one write in this system guarded by optimistic concurrency control, because an assignment supersedes any assignment already active on the same enrollment (a reassignment) and therefore depends on the caller having an up-to-date picture of that enrollment. A create-assignment request must include `expected_enrollment_version`, carrying the client's last observed `version` of the target `Enrollment`. If `expected_enrollment_version` does not match the enrollment's current `version` — because another writer has already advanced it since the caller last read it — the request is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412), preventing the caller from overwriting an assignment state it never observed. This is the only endpoint that takes an expected-version field; no other write accepts or requires one.

### 2.8. Referential Integrity and Validation Precedence

When multiple checks could reject the same request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. Authentication is checked first: a missing or malformed `X-User-ID`/`X-User-Role` yields `ERR_UNAUTHENTICATED` (401). Authorization is checked next: a role not permitted for the endpoint yields `ERR_UNAUTHORIZED` (403). Existence is checked third: every path id and every foreign key supplied in the body must resolve to an existing entity, validated left-to-right in the order they appear in the path and then the body, and the first unresolved reference yields `ERR_NOT_FOUND` (404). Only after those three gates pass does the system evaluate state-machine legality, then the domain-specific business rules described in Section 3. A required body field that is missing, or a field value that violates its declared type or enum constraint, yields `ERR_VALIDATION` (HTTP 422); this structural validation of the request body is performed before the existence of any foreign key named in that body is resolved, so a body that is both malformed and references a missing entity surfaces `ERR_VALIDATION` ahead of `ERR_NOT_FOUND` (a missing or malformed path id is still resolved first). The relative ordering of the remaining business rules is spelled out alongside the workflows they guard in Section 3; the guiding principle is that state legality and structural existence are resolved before value-level business constraints.

## 3. Business Logic & Workflows

### 3.1. Client Intake, Consent, and Risk Classification

Intake begins when an `IntakeCoordinator` registers a prospective mother. Registration captures her `full_name`, her `mother_dob` (conventionally an ISO date, but stored verbatim as a non-empty string and not parsed or format-validated), the boolean `first_time_mother` eligibility flag, and her `gestational_age_weeks` — the completed weeks of gestation at intake, which must be zero or greater. Two further attributes are managed by the system rather than supplied at registration: `consent_signed`, which starts false and can be flipped to true only through the dedicated consent-capture action, and `child_dob`, the infant's date of birth, which starts null and remains null until the birth is recorded against the mother's enrollment.

Consent is captured by an `IntakeCoordinator` through a distinct action that sets `consent_signed` to true on the client; the action is idempotent, so re-recording consent on a client whose flag is already true succeeds with HTTP 200 and returns the client unchanged, without raising an error or advancing its `version`. No other operation may set this flag, and downstream steps — activating an enrollment and opening a referral — depend on it.

Every client carries a computed `risk_tier`, one of `LOW`, `MODERATE`, or `HIGH`, defaulting to `LOW` before any screening exists. The tier is derived from the number of screening "flags" the mother has accumulated, where a flag is a single entry in an assessment's `domain_flags`. There are two variants of the count. The comprehensive count sums the flags across every assessment belonging to the client's enrollment regardless of instrument, and this is the value persisted to `risk_tier`. The provisional count is narrower: it sums flags only from assessments whose `instrument_type` is `INTAKE`, and it is intended for use at intake before the full battery of instruments has been recorded. Whichever count `n` is in play, the tier is `HIGH` when `n` is at least 3, `MODERATE` when `n` is at least 1 but below 3, and `LOW` when `n` is 0. The persisted `risk_tier` is recomputed (using the comprehensive count) whenever a new assessment is created for the client's enrollment. A read of a client's risk classification returns the current `tier` together with both `provisional_flags` and `comprehensive_flags`, and accepts an optional `basis` selector: the default basis is comprehensive, while `basis` set to provisional bases the returned `tier` on the INTAKE-only count. Because the comprehensive count can only be greater than or equal to the provisional count, the comprehensive basis can produce a higher tier than the provisional basis but never a lower one.

### 3.2. Enrollment Lifecycle and Eligibility

An `IntakeCoordinator` opens an enrollment by referencing the mother through a payload carrying her `client_id`. A new enrollment starts in `PROSPECT` status and immediately snapshots the mother's current `gestational_age_weeks` into `gestational_age_at_enrollment`; this snapshot, not the live client value, governs later eligibility re-checks. At creation the system enforces two eligibility gates and one uniqueness gate. The mother must be a first-time mother — if her `first_time_mother` flag is false the creation is rejected with `ERR_NOT_FIRST_TIME_MOTHER`. Her gestational age must not exceed the program's intake ceiling of 28 completed weeks — a value of exactly 28 weeks is eligible and 29 weeks is not; exceeding the ceiling is rejected with `ERR_GESTATIONAL_AGE_INELIGIBLE`. And a client may hold at most one enrollment that has not been exited: if the client already has an enrollment in any status other than `EXITED`, creation is rejected with `ERR_ENROLLMENT_EXISTS`.

Enrollment status moves through `PROSPECT`, `ENROLLED`, `ACTIVE`, and then one of the terminal states `GRADUATED` or `EXITED`. Activation advances an enrollment from `PROSPECT` to `ENROLLED` and is where eligibility is re-checked, this time against the snapshot taken at creation. Activation requires that consent has been recorded — a client whose `consent_signed` is still false yields `ERR_CONSENT_REQUIRED`; that the mother is still marked a first-time mother, else `ERR_NOT_FIRST_TIME_MOTHER`; and that `gestational_age_at_enrollment` does not exceed the 28-week ceiling, else `ERR_GESTATIONAL_AGE_INELIGIBLE`. The advance from `ENROLLED` to `ACTIVE` is not a direct operation: it happens as a side effect of the first active nurse assignment being created for the enrollment, as described in Section 3.4.

Graduation advances an `ACTIVE` enrollment to `GRADUATED` and is permitted only once the family has reached the final program phase: the enrollment's `program_phase` must be `TODDLERHOOD`, otherwise the request is rejected with `ERR_GRADUATION_TOO_EARLY`. Graduation cascades program closure: every `ACTIVE` assignment on the enrollment transitions to `ENDED`, and as each ends it releases its `caseload_weight` from the assigned nurse's `current_caseload_weight`; and every visit still in `SCHEDULED` status for the enrollment transitions to `CANCELED`.

Disenrollment exits an enrollment from any non-terminal status — `PROSPECT`, `ENROLLED`, or `ACTIVE` — moving it to `EXITED` with no precondition. When the enrollment being disenrolled was `ACTIVE`, disenrollment drives the same closure cascade as graduation: its `ACTIVE` assignments transition to `ENDED`, each ended assignment subtracts its `caseload_weight` from the nurse's `current_caseload_weight` (which is then recomputed over the nurse's remaining active assignments), and every `SCHEDULED` visit for the enrollment transitions to `CANCELED`. Attempting any of these lifecycle transitions from a status where it is not defined — for instance graduating an enrollment that is not `ACTIVE` — yields `ERR_INVALID_STATE`.

Two additional enrollment attributes are informational. `completed_visit_count` starts at 0 and is kept exactly in step with the number of this enrollment's visits currently in `COMPLETED` status (see Section 3.6). `risk_tier_at_enrollment` starts at `LOW` and mirrors the client's `risk_tier` as of the latest assessment; it is a snapshot for reporting and does not itself gate anything. The boolean `dosage_alert` starts false and is driven entirely by the dosage machinery of Section 3.6.

### 3.3. Program Phases and Birth Recording

Each enrollment carries a `program_phase` that tracks the child's developmental stage, one of `PREGNANCY`, `INFANCY`, or `TODDLERHOOD`, and it begins at `PREGNANCY`. Recording the birth is an `IntakeCoordinator` action that supplies the infant's `child_dob`: it writes that date onto the client and advances the enrollment's `program_phase` from `PREGNANCY` to `INFANCY`. Later, when the child reaches twelve months, a further advance-phase action moves the `program_phase` from `INFANCY` to `TODDLERHOOD`. Reaching `TODDLERHOOD` is the precondition that later unlocks graduation. Phase matters operationally because, as Section 3.4 explains, the phase in effect at the moment a nurse assignment is created fixes that assignment's caseload weight tier.

### 3.4. Staff Records, Nurse Assignment, and Caseload Weighting

A `ProgramAdmin` creates the staff records. A nurse record captures `full_name`, a `credential_type` that must be one of `RN`, `BSN`, or `APRN`, and a `status` governing whether new assignments may target the nurse — one of `ACTIVE`, `ON_LEAVE`, or `INACTIVE`, defaulting to `ACTIVE`. A nurse also carries a `max_caseload_weight`, the per-nurse cap on total active weighted caseload, which must be zero or greater and defaults to 25.0 when omitted. Two further nurse attributes are maintained by the system: `current_caseload_weight`, the computed sum of caseload weight across the nurse's active assignments, starting at 0.0; and `pending_supervision_count`, the number of open dosage-alert reviews awaiting a supervision session, starting at 0. A supervisor record, also created by a `ProgramAdmin`, captures `full_name` and a `status` of either `ACTIVE` or `INACTIVE`, defaulting to `ACTIVE`.

A `Supervisor` assigns a nurse to an enrollment by supplying the `enrollment_id`, the `nurse_id`, the `expected_enrollment_version` required by the concurrency rule in Section 2.7, and an optional `high_needs` flag that defaults to false and marks an intensive caseload slot. When the assignment is created the system snapshots the enrollment's current `program_phase` into `phase_at_assignment`; this snapshot, not the enrollment's live phase, fixes the weight tier for the life of the assignment. The assignment's `status` begins `ACTIVE` (the only other value being `ENDED`), and its `review_required` flag begins false.

The assignment's `caseload_weight` is computed from the phase tier and the high-needs flag. Each phase carries a base weight: `PREGNANCY` weighs 1.0, `INFANCY` weighs 0.8, and `TODDLERHOOD` weighs 0.6. The base weight for the assignment's `phase_at_assignment` is multiplied by 1.25 when `high_needs` is true, or by 1.0 when it is false, and the product is rounded half-up to two decimal places to yield the assignment's `caseload_weight`. A nurse's `current_caseload_weight` is then the sum of the per-assignment `caseload_weight` values across all of the nurse's `ACTIVE` assignments, with each per-assignment weight rounded first and the pinned sum then rounded half-up to two decimal places.

Creating an assignment enforces a fixed sequence of checks after the shared authentication, authorization, and existence gates. First, the target enrollment must be assignable — its status must be `ENROLLED` or `ACTIVE`; any other status yields `ERR_ENROLLMENT_NOT_ASSIGNABLE`. Next, the target nurse must be employable — `Nurse.status` must be `ACTIVE`, otherwise `ERR_NURSE_NOT_ACTIVE`. Next comes the caseload cap: the system computes what the nurse's weight would become by adding the new assignment's weight to the nurse's current weight, and rejects with `ERR_CASELOAD_EXCEEDED` only when that projected total would be strictly greater than the nurse's `max_caseload_weight` — a projected total exactly equal to the cap is allowed. Finally, the optimistic-concurrency check on `expected_enrollment_version` is evaluated last; a mismatch with the enrollment's current `version` yields `ERR_STALE_ENROLLMENT_VERSION`. This ordering means an unassignable-state error is surfaced ahead of a stale-version error even when both conditions hold.

A successful assignment has several coordinated effects. Its computed `caseload_weight` is added to the nurse's `current_caseload_weight`. Because a new assignment supersedes any assignment already `ACTIVE` on the same enrollment, that prior assignment is transitioned to `ENDED` and its weight released from its nurse's `current_caseload_weight`. If the enrollment was in `ENROLLED` status, creating its first active assignment advances it to `ACTIVE`. And the enrollment's `version` is incremented by 1 — the mutation that a subsequent stale `expected_enrollment_version` would collide with.

Ending an assignment directly is a `Supervisor` action that moves an `ACTIVE` assignment to `ENDED`; it requires the assignment to currently be `ACTIVE`. Ending subtracts the assignment's `caseload_weight` from the nurse's `current_caseload_weight` (recomputed over the nurse's remaining active assignments), and — if the assignment's `review_required` was true at the time it ends — additionally decrements that nurse's `pending_supervision_count` by 1. The same end-of-assignment effects apply when an assignment is ended by a cascade from enrollment graduation or disenrollment, or when it is superseded by a newer assignment.

### 3.5. Visit Scheduling and Nurse Conflict Detection

A `HomeVisitNurse` schedules a visit against an enrollment. The scheduling payload names the `enrollment_id` the visit serves, the `nurse_id` who will conduct it, the `phase` the visit belongs to (one of `PREGNANCY`, `INFANCY`, or `TODDLERHOOD`), the `target_date` on which the visit is due (an ISO date, used by dosage to-date gating), and the planned window given by `scheduled_start` and `scheduled_end` (ISO 8601 UTC datetimes used for double-booking detection). A visit's `status` begins `SCHEDULED` and may become `COMPLETED`, `MISSED`, `CANCELED`, or `RESCHEDULED`, of which `MISSED`, `CANCELED`, and `RESCHEDULED` are terminal. Three further fields are system-managed: `completed_date` starts null and is only set when the visit completes; `on_time` starts false and is computed at completion; and `rescheduled_from_visit_id` starts null and is set only on a replacement visit born of a reschedule, pointing back at the visit it supersedes.

The scheduling window must be coherent: `scheduled_end` must be strictly after `scheduled_start`, and a window where it is not is rejected with `ERR_SCHEDULE_WINDOW_INVALID`.

Two scheduling constraints protect the calendar. The first prevents double-booking a nurse. A candidate visit's window is compared against every existing visit of the same nurse that is in a non-terminal-for-scheduling status — that is, every visit of that nurse whose `status` is `SCHEDULED` or `COMPLETED`. Each visit's window is treated as extended by a 30-minute travel buffer on its end side only, and the two windows are said to conflict when the candidate's `scheduled_start` falls before the existing visit's `scheduled_end` plus the 30-minute buffer, and simultaneously the existing visit's `scheduled_start` falls before the candidate's `scheduled_end` plus the 30-minute buffer. Because the geometry is half-open on the end side, two back-to-back visits separated by a gap of at least the full 30 minutes do not conflict. A conflict is rejected with `ERR_VISIT_OVERLAP`. The second constraint prevents redundant visits on the same day for the same family: no two non-terminal visits of the same enrollment may share the same `target_date`, and a collision is rejected with `ERR_DUPLICATE_TARGET_DATE`.

Cancellation is an `IntakeCoordinator` action that moves a `SCHEDULED` visit to `CANCELED`; it recomputes the enrollment's dosage afterward. A `CANCELED` visit contributes to neither the numerator nor the denominator of dosage.

Rescheduling is a nurse action, permitted only by the visit's owning nurse (`X-User-ID` must equal the visit's `nurse_id`, else `ERR_NOT_VISIT_OWNER`), that moves a `SCHEDULED` visit to `RESCHEDULED` and, in the same operation, creates and returns a replacement visit in `SCHEDULED` status. The reschedule payload supplies a new `target_date`, `scheduled_start`, and `scheduled_end`; the replacement copies the `enrollment_id`, `nurse_id`, and `phase` of the original and adopts the new dates, and its `rescheduled_from_visit_id` is set to the superseded visit's `id`. The same conflict and duplicate-`target_date` checks that guard scheduling — `ERR_VISIT_OVERLAP` and `ERR_DUPLICATE_TARGET_DATE` — are re-applied to the replacement's proposed window and date. The superseded visit, now `RESCHEDULED`, leaves the dosage denominator entirely. Because the replacement is itself `SCHEDULED`, it may in turn be rescheduled again, forming a reschedule loop.

### 3.6. Visit Completion, Dosage Tracking, and the Escalation Cascade

Completing a visit is the pivotal operation in the program. It is performed by the visit's owning `HomeVisitNurse` — `X-User-ID` must equal the visit's `nurse_id`, else `ERR_NOT_VISIT_OWNER`. The visit must be `SCHEDULED` and its enrollment must be `ACTIVE`; an enrollment that is not `ACTIVE` yields `ERR_ENROLLMENT_NOT_ACTIVE`. The payload supplies a `completed_date`, which must fall on the current logical-clock day or earlier. Completion writes `completed_date`, computes `on_time`, moves the visit's `status` to `COMPLETED`, increments the enrollment's `completed_visit_count` by 1, and recomputes dosage. The `on_time` determination compares the whole-day distance between `completed_date` and the visit's `target_date`: the visit is on time when that distance is at most 7 days in either direction, with exactly 7 days early or late still counting as on time.

**Dosage** measures the fraction of due visits a family has actually received, and it is computed in two variants that differ only in what counts toward the denominator. Both variants exclude visits in `RESCHEDULED` and `CANCELED` status entirely. The **to-date** variant is the default and is the one that drives alerts: its denominator counts the enrollment's visits whose `status` is `COMPLETED` or `MISSED` and whose `target_date` is on or before the current logical-clock day, and its numerator counts those same due visits whose `status` is `COMPLETED`. The to-date percentage, `dosage_to_date_pct`, is null when that denominator is zero; otherwise it is 100 multiplied by the completed-to-date count and divided by the expected-to-date count, rounded half-up to two decimal places. The **full-program** variant ignores the clock and looks at the whole planned schedule: its denominator counts the enrollment's visits whose `status` is `COMPLETED`, `MISSED`, or `SCHEDULED` regardless of `target_date`, and its numerator counts those in `COMPLETED`. The full-program percentage, `dosage_full_pct`, is null when its denominator is zero; otherwise it is 100 multiplied by the completed count and divided by the full expected count, rounded half-up to two decimal places. The two diverge whenever future-dated `SCHEDULED` visits exist. A read of an enrollment's dosage always returns all of `dosage_to_date_pct`, `dosage_full_pct`, `completed_to_date`, `expected_to_date`, and `dosage_alert` in a single fixed-shape response; the read does not consume a `basis` selector, and any such query parameter is ignored (both variants are reported unconditionally). As an invariant, an enrollment's `completed_visit_count` always equals the number of its visits currently in `COMPLETED` status.

The alert threshold is a dosage floor of 60 percent, and `dosage_alert` is true exactly when the to-date percentage is non-null and strictly below 60 percent. Because completion raises dosage, it can only ever clear an alert, never raise one: after a completion, if the recomputed `dosage_to_date_pct` is at least 60 percent and `dosage_alert` had been true, the system clears `dosage_alert`, clears `review_required` on each of the enrollment's `ACTIVE` assignments, and decrements each such assignment's nurse's `pending_supervision_count` by 1, never letting that counter fall below 0.

**Marking a visit missed** is the primary escalation cascade and is performed by the visit's owning nurse (`X-User-ID` must equal the visit's `nurse_id`, else `ERR_NOT_VISIT_OWNER`). It advances a `SCHEDULED` visit to `MISSED` and then propagates in strict hops, each caused only by the mutation the previous hop made. The first hop marks the visit `MISSED` and recomputes dosage; because a `MISSED` visit enters the to-date denominator but not the numerator, the to-date percentage drops. The second hop fires only if the recomputed `dosage_to_date_pct` is now below 60 percent: it sets the enrollment's `dosage_alert` to true. The third hop fires only when the second hop actually flipped `dosage_alert` from false to true: it sets `review_required` to true on every `ACTIVE` assignment of the enrollment. The fourth hop fires only when the third hop fired: for each such assignment, it increments that assignment's nurse's `pending_supervision_count` by 1.

**Reverting a completion** undoes a completion exactly. It is performed by the visit's owning nurse (`X-User-ID` must equal the visit's `nurse_id`, else `ERR_NOT_VISIT_OWNER`), and the visit must currently be `COMPLETED`. Reversion moves the visit from `COMPLETED` back to `SCHEDULED`, clears `completed_date` and `on_time`, decrements the enrollment's `completed_visit_count` by 1, and recomputes dosage. As the compensating inverse of completion, if dosage recovers to at least 60 percent, it clears `dosage_alert` and unwinds the `review_required` flags and `pending_supervision_count` increments that this enrollment had contributed.

### 3.7. Assessments and Developmental Screening

A `HomeVisitNurse` records a screening or milestone assessment against a completed visit. The assessment payload names the `visit_id` at which the screening was administered, the `enrollment_id` that owns it, the `instrument_type` administered (one of `INTAKE`, `ASQ`, `EDINBURGH`, or `ASQ_SE`), and a `raw_scores` map from domain name to an integer subscore. The `raw_scores` map must be a non-empty object whose every value is an integer (booleans are rejected), otherwise `ERR_VALIDATION`. Two referential checks guard creation. The referenced visit must be in `COMPLETED` status; recording an assessment against a visit that is not completed is rejected with `ERR_VISIT_NOT_COMPLETED`. And the `enrollment_id` supplied in the body must equal the referenced visit's own `enrollment_id`; a mismatch is rejected with `ERR_ASSESSMENT_VISIT_MISMATCH`.

Two attributes are computed from `raw_scores` at creation. The overall `result_band` is derived from the total of all subscores: it is `ON_TRACK` when that total is at least 85, `MONITOR` when the total is at least 70 but below 85, and `REFER` when the total is below 70. The `domain_flags` array lists every domain whose subscore falls below the domain flag threshold of 10, and the flagged domains are ordered by their domain key in ascending order for determinism. Creating an assessment then recomputes the client's `risk_tier` using the comprehensive count described in Section 3.1, and refreshes the enrollment's `risk_tier_at_enrollment` snapshot to mirror it.

### 3.8. Benefit Referrals

A `HomeVisitNurse` opens a referral to link an enrollment to a community benefit. The referral payload names the `enrollment_id` and the `benefit_type`, which must be one of `WIC`, `MEDICAID`, `HOUSING`, `CHILDCARE`, or `MENTAL_HEALTH`. Opening a referral requires that the mother's consent has been recorded — if the client's `consent_signed` is false the request is rejected with `ERR_CONSENT_REQUIRED` — and it also requires that no non-terminal referral of the same `benefit_type` already exists for the enrollment, else `ERR_DUPLICATE_REFERRAL`. A referral's `status` begins `OPEN` and may move through `CONTACTED` to one of the terminal states `CONNECTED`, `DECLINED`, or `CLOSED`. Its `attempts` counter begins at 0, and `connected_at` begins null.

Working a referral is a sequence of nurse actions, each defined only from a specific status. Contacting the benefit provider advances the referral from `OPEN` to `CONTACTED` and increments `attempts` by 1. From `CONTACTED`, connecting the family advances the referral to `CONNECTED` and stamps `connected_at` with the current logical-clock time. Also from `CONTACTED`, declining advances the referral to `DECLINED`. Reopening moves a `CONTACTED` referral back to `OPEN` for another attempt; the next contact from that reopened state increments `attempts` again, forming a re-attempt loop. Closing an unresolved referral moves it to `CLOSED` and is defined from either `OPEN` or `CONTACTED`. Any of these transitions attempted from a status where it is not defined yields `ERR_INVALID_STATE`.

### 3.9. Supervision, Outcome Measures, and MIECHV Reporting

A `Supervisor` opens a supervision session to review a nurse's caseload over a window. The session payload names the `nurse_id` under review, the `supervisor_id` conducting the review, the inclusive review window `period_start` and `period_end` (ISO dates), and `reviewed_enrollment_ids`, the list of enrollment ids whose dosage alerts the session dispositions. A session's `status` begins `DRAFT` and terminates at `SIGNED`. Signing is restricted to the session's owning supervisor — `X-User-ID` must equal the session's `supervisor_id`, else `ERR_NOT_SESSION_OWNER` — and additionally requires that the acting supervisor's own `status` be `ACTIVE`, an inactive supervisor being rejected with `ERR_INVALID_STATE` (checked after the DRAFT-status check, which also yields `ERR_INVALID_STATE`). Signing advances the session from `DRAFT` to `SIGNED` and dispositions alerts: for each enrollment id in `reviewed_enrollment_ids` that currently carries a `dosage_alert` and has an `ACTIVE` assignment to this session's nurse, the system clears that assignment's `review_required` and decrements the nurse's `pending_supervision_count` by 1, never dropping it below 0.

A `ProgramAdmin` snapshots an outcome measure for an enrollment over a window. The payload names the `enrollment_id`, the `measure_type` (one of `ON_TIME_VISIT_RATE`, `DOSAGE_TO_DATE`, or `BREASTFEEDING_INITIATED`), and the inclusive window `period_start` and `period_end`. At snapshot time the system captures the measure's `numerator` and `denominator` and derives `rate_pct` as 100 multiplied by the numerator and divided by the denominator, rounded half-up to two decimal places; when the denominator is 0 the `rate_pct` is null. The numerator and denominator depend on `measure_type`. For `ON_TIME_VISIT_RATE`, the denominator is the count of the enrollment's `COMPLETED` visits whose `completed_date` falls on or after `period_start` and on or before `period_end`, and the numerator is those among them whose `on_time` is true. For `DOSAGE_TO_DATE`, the denominator is the count of the enrollment's visits in `COMPLETED` or `MISSED` status whose `target_date` falls within that same inclusive window, and the numerator is those of them in `COMPLETED` status. For `BREASTFEEDING_INITIATED`, the data model carries no source signal, so both `numerator` and `denominator` are 0 and `rate_pct` is therefore null.

A `ProgramAdmin` also creates and finalizes MIECHV reports. Creating a report names the reporting period through `period_start` and `period_end` and starts it in `DRAFT` status (the terminal status being `FINALIZED`). While in draft, its pooled metrics are unset: `program_on_time_rate_pct` is null, and `enrolled_count` and `dosage_alert_count` are 0. Finalizing advances a `DRAFT` report to `FINALIZED` and freezes three figures as of the current logical clock. The `enrolled_count` becomes the number of enrollments whose status is `ACTIVE` or `GRADUATED` at the moment of finalization (the system keeps no status history, so current status — not membership at any point during the period — defines this scope). The `dosage_alert_count` becomes the number of enrollments whose `dosage_alert` is true at the moment of finalization. The `program_on_time_rate_pct` is the pooled program-wide on-time visit rate, computed over the same scope of enrollments whose status is `ACTIVE` or `GRADUATED` at finalization: gather every `COMPLETED` visit of those enrollments whose `completed_date` falls on or after `period_start` and on or before `period_end`; the denominator is the count of those completed visits, and the numerator is the count of them whose `on_time` is true. The pooled rate is null when that denominator is 0; otherwise the numerator and denominator are pooled across all in-scope enrollments first and the rate is computed exactly once as 100 multiplied by the numerator and divided by the denominator, rounded half-up to two decimal places. This pooled-then-rounded order is required; averaging per-enrollment rounded rates is not an acceptable substitute.

## 4. Endpoint Definitions

The following table summarizes every endpoint. Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful call — reads, list retrievals, state transitions, and other modifications — returns HTTP 200. Request and response bodies, input fields, and side effects are not repeated here; reconstruct them from the workflow narratives in Section 3. All list endpoints additionally accept the `limit` and `offset` query parameters described in Section 2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant; returns the new `current_utc`. | ProgramAdmin |
| POST | `/nurses` | Create a home-visiting nurse. | ProgramAdmin |
| GET | `/nurses/{id}` | Read a nurse including `current_caseload_weight` and `pending_supervision_count`. | ProgramAdmin, Supervisor |
| POST | `/supervisors` | Create a supervisor. | ProgramAdmin |
| POST | `/clients` | Register a prospective client (first-time mother). | IntakeCoordinator |
| GET | `/clients/{id}` | Read a client including computed `risk_tier`. | IntakeCoordinator, Supervisor |
| GET | `/clients` | List clients. | IntakeCoordinator, Supervisor |
| POST | `/clients/{id}/consent` | Record informed consent; sets `consent_signed` true. | IntakeCoordinator |
| GET | `/clients/{id}/risk` | Read risk classification; `basis` selects provisional or comprehensive. | IntakeCoordinator, Supervisor |
| POST | `/enrollments` | Create a PROSPECT enrollment for a client; snapshots gestational age. | IntakeCoordinator |
| GET | `/enrollments/{id}` | Read an enrollment. | IntakeCoordinator, Supervisor, HomeVisitNurse |
| GET | `/enrollments` | List enrollments; filter by `client_id` or `status`. | IntakeCoordinator, Supervisor |
| POST | `/enrollments/{id}/activate-enrollment` | Advance PROSPECT to ENROLLED after consent and eligibility re-check. | IntakeCoordinator |
| POST | `/enrollments/{id}/record-birth` | Record infant birth; set `child_dob` and advance phase to INFANCY. | IntakeCoordinator |
| POST | `/enrollments/{id}/advance-phase` | Advance program phase INFANCY to TODDLERHOOD. | IntakeCoordinator |
| POST | `/enrollments/{id}/graduate` | Advance ACTIVE to GRADUATED; cascades assignment and visit closure. | IntakeCoordinator |
| POST | `/enrollments/{id}/disenroll` | Exit the enrollment from any non-terminal state; cascades closure. | IntakeCoordinator |
| GET | `/enrollments/{id}/dosage` | Read dosage; returns both the to-date and full-program variants (no `basis` selector). | IntakeCoordinator, Supervisor, HomeVisitNurse |
| POST | `/assignments` | Assign a nurse to an enrollment; supersedes any active assignment (OCC on enrollment version). | Supervisor |
| GET | `/assignments/{id}` | Read an assignment. | Supervisor, ProgramAdmin |
| GET | `/assignments` | List assignments; filter by `enrollment_id`, `nurse_id`, or `status`. | Supervisor, ProgramAdmin |
| POST | `/assignments/{id}/end` | End an ACTIVE assignment; releases its caseload weight. | Supervisor |
| POST | `/visits` | Schedule a visit for an enrollment. | HomeVisitNurse |
| GET | `/visits/{id}` | Read a visit. | HomeVisitNurse, Supervisor, IntakeCoordinator |
| GET | `/visits` | List visits; filter by `enrollment_id`, `nurse_id`, `rescheduled_from_visit_id`, or `status`. | HomeVisitNurse, Supervisor, IntakeCoordinator |
| POST | `/visits/{id}/complete` | Advance SCHEDULED to COMPLETED; drives the dosage cascade. | HomeVisitNurse |
| POST | `/visits/{id}/revert-completion` | Advance COMPLETED back to SCHEDULED; inverse of completion. | HomeVisitNurse |
| POST | `/visits/{id}/mark-missed` | Advance SCHEDULED to MISSED; drives the escalation cascade. | HomeVisitNurse |
| POST | `/visits/{id}/cancel` | Advance SCHEDULED to CANCELED. | IntakeCoordinator |
| POST | `/visits/{id}/reschedule` | Advance SCHEDULED to RESCHEDULED; creates and returns a replacement visit. | HomeVisitNurse |
| POST | `/assessments` | Record a screening/milestone assessment against a completed visit. | HomeVisitNurse |
| GET | `/assessments/{id}` | Read an assessment. | HomeVisitNurse, Supervisor |
| GET | `/assessments` | List assessments; filter by `visit_id` or `enrollment_id`. | HomeVisitNurse, Supervisor |
| POST | `/referrals` | Open a benefit-linkage referral for an enrollment. | HomeVisitNurse |
| GET | `/referrals/{id}` | Read a referral. | HomeVisitNurse, Supervisor |
| GET | `/referrals` | List referrals; filter by `enrollment_id` or `status`. | HomeVisitNurse, Supervisor |
| POST | `/referrals/{id}/contact` | Advance OPEN to CONTACTED; increments attempts. | HomeVisitNurse |
| POST | `/referrals/{id}/connect` | Advance CONTACTED to CONNECTED; stamps `connected_at`. | HomeVisitNurse |
| POST | `/referrals/{id}/decline` | Advance CONTACTED to DECLINED. | HomeVisitNurse |
| POST | `/referrals/{id}/reopen` | Advance CONTACTED to OPEN (re-attempt loop). | HomeVisitNurse |
| POST | `/referrals/{id}/close` | Advance OPEN or CONTACTED to CLOSED. | HomeVisitNurse |
| POST | `/supervision-sessions` | Open a caseload supervision session for a nurse over a period. | Supervisor |
| GET | `/supervision-sessions/{id}` | Read a supervision session. | Supervisor, ProgramAdmin |
| GET | `/supervision-sessions` | List supervision sessions; filter by `nurse_id`, `supervisor_id`, or `status`. | Supervisor, ProgramAdmin |
| POST | `/supervision-sessions/{id}/sign` | Advance DRAFT to SIGNED; dispositions dosage alerts for reviewed enrollments. | Supervisor |
| POST | `/outcome-measures` | Snapshot an outcome measure for an enrollment over a period. | ProgramAdmin |
| GET | `/outcome-measures/{id}` | Read an outcome measure. | ProgramAdmin, Supervisor |
| GET | `/outcome-measures` | List outcome measures; filter by `enrollment_id`. | ProgramAdmin, Supervisor |
| POST | `/miechv-reports` | Create a DRAFT MIECHV report for a period. | ProgramAdmin |
| GET | `/miechv-reports/{id}` | Read a MIECHV report. | ProgramAdmin |
| POST | `/miechv-reports/{id}/finalize` | Advance DRAFT to FINALIZED; freezes pooled program metrics. | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ENROLLMENT_NOT_ASSIGNABLE | 409 |
| ERR_ENROLLMENT_NOT_ACTIVE | 409 |
| ERR_VISIT_NOT_COMPLETED | 409 |
| ERR_NOT_VISIT_OWNER | 403 |
| ERR_NOT_SESSION_OWNER | 403 |
| ERR_CONSENT_REQUIRED | 422 |
| ERR_NOT_FIRST_TIME_MOTHER | 422 |
| ERR_VISIT_OVERLAP | 409 |
| ERR_DUPLICATE_TARGET_DATE | 409 |
| ERR_GESTATIONAL_AGE_INELIGIBLE | 422 |
| ERR_ENROLLMENT_EXISTS | 409 |
| ERR_GRADUATION_TOO_EARLY | 409 |
| ERR_DUPLICATE_REFERRAL | 409 |
| ERR_ASSESSMENT_VISIT_MISMATCH | 422 |
| ERR_NURSE_NOT_ACTIVE | 422 |
| ERR_CASELOAD_EXCEEDED | 422 |
| ERR_STALE_ENROLLMENT_VERSION | 412 |
| ERR_VALIDATION | 422 |
| ERR_SCHEDULE_WINDOW_INVALID | 422 |

# Exam Anti-Cheating API — Product Requirements Document

## 1. Introduction

The Exam Anti-Cheating platform is the back-office system of record for high-stakes online assessments where the integrity of each candidate's score must be defensible long after the test session ends. It orchestrates everything from the moment an exam is configured by an administrator through paper composition, multi-factor identity binding, in-session monitoring, double-blind subjective grading, score publication, and the appeal window — and it captures, as an append-only audit trail, every adjustment that materially affects a candidate's final score.

Two long-standing pain points motivate the design. First, paper composition for online exams is rarely truly random: candidates collude to share answers when papers repeat across sittings, and proctors lack confidence that the version of the paper a candidate received was sampled fairly. The system addresses this by binding each candidate's paper to a deterministic seed derived from their attempt and freezing it as an immutable archival hash. Second, real-time anti-cheating signals — face leaving the camera frame, multiple persons detected, suspicious window switches, external devices — must be evaluated against a documented severity policy rather than ad-hoc proctor judgment. The platform encodes that policy in a deterministic formula, classifies each event into one of three buckets, and either escalates the candidate's status or forces an in-exam re-verification, depending on the rule code and the channel that detected it.

Because the platform is the source of truth for both score adjustments and disqualifications, every cross-aggregate effect is captured immediately and synchronously. There are no deferred consistency windows: when a `CRITICAL` event disqualifies a candidate, the cascade to their grading assignments, their registration, and their final score is observable on the very next read, and the audit log row that records the change is written before the originating request returns.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which names the role the principal is acting under. If either header is missing or empty, the server rejects the request with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the role is recognised but lacks permission for the requested operation under the RBAC matrix, the server returns `ERR_INSUFFICIENT_PERMISSIONS`.

Six roles are supported, spelled exactly as follows: `ExamAdmin`, `Proctor`, `Candidate`, `Marker`, `AppealOfficer`, and `TestHarness`. A pseudo-role `Any` is used for endpoints that any authenticated role may call.

- When `X-User-Role` is `Candidate`, `X-User-ID` is the `candidate_id` of the acting `CandidateRegistration`. Ownership checks on any `ExamAttempt` traverse the attempt's `registration_id` to the underlying `CandidateRegistration` and compare its `candidate_id` to `X-User-ID`; appeals are likewise filtered to those whose underlying attempt belongs to the acting candidate.
- When `X-User-Role` is `ExamAdmin`, `Proctor`, `Marker`, `AppealOfficer`, or `TestHarness`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `marker_id` on a `GradingAssignment` written by a scoring transition, or as `actor_id` on an `AuditLogEntry`) but does not compare it to the `id` of any entity.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100 inclusive. The default `offset` is 0, and any negative value is rejected. A request whose `limit` falls outside the range from 1 to 100 inclusive, or whose `offset` is below 0, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS`. Results are always sorted by `created_at` in ascending order. Each list response surfaces, inside its `meta` envelope, the four pagination fields `limit`, `offset`, `total_count`, and `has_more`; the last is true when more rows exist beyond the current window.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every resource that survives mutation carries the four common fields `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix and no human-readable embedding. Both `created_at` and `updated_at` are ISO 8601 UTC strings with three fractional digits; `created_at` is fixed at the instant of resource birth and `updated_at` is refreshed on every successful mutation. The `version` field is an integer that starts at 1 on creation and increments by 1 on every successful mutation.

Two entity classes are append-only archives and therefore omit `updated_at` and `version` entirely, carrying only `id` and `created_at`: `IdentityVerificationRecord`, `AbnormalEvent`, and `AuditLogEntry`. Once written, rows of these types are never updated — the only legitimate way to amend the record is by appending another row.

Optimistic concurrency control is applied to mutating endpoints on entities that carry `version`. A request body may include an integer `version` field; when present, the server requires it to equal the resource's current `version` before applying the mutation, and on mismatch returns `ERR_INVALID_STATE`. When the `version` field is omitted from the body, the concurrency check is skipped and the mutation proceeds against whatever the latest persisted state happens to be.

### 2.5. Server Time and the Test-Driven Clock

Time-gated transitions in this system are evaluated against a single server-side logical clock, not against the client's wall clock. An admin-only test-driving capability advances that logical clock to a supplied `to_unix_seconds` instant; reaching that instant fires every automatic transition whose precondition has now become true (an `Exam` entering `IN_SESSION` once its `start_time` is reached, entering `GRADING` once its `end_time` is reached, entering `APPEAL_WINDOW` one second after publication, entering `ARCHIVED` once `appeal_window_seconds` after publication have elapsed, and forced submission of every still-`ACTIVE` or `SUSPENDED` attempt at `end_time`). All candidate-initiated mutations also evaluate their timing preconditions against this clock rather than wall-time. Whenever the prose below speaks of "the current instant" it refers to this server clock.

### 2.6. Nested Resource Path Resolution

Every nested URL is resolved left-to-right. A request against an attempt-scoped path first verifies the parent exam exists (`ERR_EXAM_NOT_FOUND`), then the attempt (`ERR_ATTEMPT_NOT_FOUND`), and only then evaluates business-state preconditions. The same left-to-right walk applies for `Question` under `Exam` (`ERR_QUESTION_NOT_FOUND`), for `CandidateRegistration` under `Exam` (`ERR_REGISTRATION_NOT_FOUND`), for `GradingAssignment` under `Exam` (`ERR_GRADING_ASSIGNMENT_NOT_FOUND`), and for `Appeal` under `Exam` (`ERR_APPEAL_NOT_FOUND`). A missing intermediate id always shadows any state or business-rule failure that would otherwise apply downstream.

### 2.7. Validation Ordering

When multiple checks apply to the same request, they are evaluated in a fixed priority order so that the same precondition failure always produces the same error code regardless of which other constraints are also violated. Header authentication is checked first, then role-based authorisation, then existence of every path resource left-to-right, then `Exam` lifecycle state, then per-resource state. Identity-verification outcome is evaluated next so that a `MISMATCH` always surfaces as `ERR_IDENTITY_MISMATCH` rather than as a downstream state error. The forced-submit override at `end_time` then preempts any candidate-initiated mutation on `ACTIVE` or `SUSPENDED` attempts, so that a network-resume, submit, or in-exam recheck arriving after `end_time` is rejected with `ERR_EXAM_WINDOW_CLOSED` rather than being mistaken for a stale-state error. The double-blind invariant on `Marker` claims and the segregation-of-duties invariant on `AppealOfficer` claims are evaluated next; then come the business-constraint validations covering paper composition, rubric integrity, point ranges, appeal scope, appeal timing, secondary-marking range, and evidence requirements; and finally pagination parameter ranges on list endpoints. The relative ordering of these classes is load-bearing — for instance, a `CRITICAL` `AbnormalEvent` that has emitted a forced recheck is still subject to the `ERR_EXAM_WINDOW_CLOSED` priority, meaning the candidate cannot satisfy the recheck after `end_time`.

### 2.8. Precision, Rounding, and Score Aggregation Discipline

All monetary-style and proportional values in this system are reported with the rounding policy "round half up to two decimal places". Severity scores, per-question subjective averages, and grading progress percentages are each rounded half up to two decimal places at the per-step boundary specified for their respective formula; sums over rounded per-question values are computed exactly, without re-rounding the total. The disqualification override is applied last: when an attempt is `DISQUALIFIED`, its `final_score` and `provisional_score` are both forced to zero regardless of any accumulated subjective or objective contribution.

### 2.9. Audit Trail Discipline

Every score-affecting cascade emits an `AuditLogEntry` row. Each row records the polymorphic `subject_type` (`EXAM_ATTEMPT`, `ABNORMAL_EVENT`, `APPEAL`, or `SCORE_ADJUSTMENT`), the `subject_id` of the affected instance, the `actor_role` that triggered the change, the `actor_id` (the `X-User-ID` of the actor), the `action_code` (`ABNORMAL_EVENT_RECORDED`, `IDENTITY_MISMATCH`, `FORCED_SUBMIT`, `APPEAL_APPROVED`, or `SCORE_ADJUSTED`), and a free-form `delta` object whose pinned shape is a `before` / `after` pair appropriate to the `action_code`. The audit log is strictly append-only — no row is ever updated or deleted — and it inherits the append-only field rule from §2.4 (only `id` and `created_at`). The audit log is readable only by an `ExamAdmin`.

## 3. Business Logic & Workflows

### 3.1. Exam Configuration and the Question Bank

An exam begins life as a `DRAFT` shell created by an `ExamAdmin`. Creation requires a `title`, a `start_time` and an `end_time` expressed in unix seconds, and the sampling policy: a `sampling_rule_type` of `RANDOM`, `STRATIFIED`, or `BLUEPRINT`, together with a `sampling_rule_spec` object whose shape depends on the chosen mode. Three optional parameters tune the experience further: `appeal_window_seconds` defaults to 86400 (one day) and governs how long the exam remains in `APPEAL_WINDOW` after scores are published, `per_question_time_limit_seconds` defaults to 0 (no per-question cap, only the overall window applies), and `option_shuffle` defaults to true. The newly created exam starts with `status` set to `DRAFT`, `max_score` and `grading_progress_pct` both at 0.

While the exam is still `DRAFT`, the administrator populates the question bank. Each `Question` carries its `exam_id`, a `question_type` drawn from the five values `SINGLE_CHOICE`, `MULTI_CHOICE`, `TRUE_FALSE`, `SHORT_ANSWER`, and `ESSAY` — where the first three are objective (auto-gradable) and the last two are subjective (require human marking) — a `difficulty` of `EASY`, `MEDIUM`, or `HARD`, a `topic` string that serves as a blueprint slot key, a `stem`, an `options` array of `{ option_key, text }` pairs for the two choice types (ignored for `SHORT_ANSWER` and `ESSAY`), a `correct_answer` array (option keys for objective questions, optional rubric keypoint ids for subjective hints), and a strictly positive `max_points`. Subjective questions additionally require a `rubric` array of `{ keypoint, points }` entries whose `points` must sum exactly to `max_points`; objective questions must carry no rubric at all. A violation of either rubric rule rejects the question creation with `ERR_RUBRIC_INVALID`.

Once the bank is populated, the administrator opens registration. This transition `DRAFT → OPEN_REGISTRATION` is gated by two business-constraint checks evaluated together at the moment of the call: the bank must contain at least one question (otherwise `ERR_QUESTION_BANK_EMPTY`), and `sampling_rule_spec` must be feasible against the bank in its current shape (otherwise `ERR_SAMPLING_INFEASIBLE`). Feasibility means that for `RANDOM` mode the total question count is at least the spec's `target_count`; for `STRATIFIED` mode every entry in the spec's `difficulty_buckets` map (with keys `EASY`, `MEDIUM`, `HARD`) is bounded by the number of bank questions of that difficulty; and for `BLUEPRINT` mode every ordered slot in the spec's `slots` list — each carrying a `topic`, a `question_type`, a `difficulty`, and a `count` — finds at least `count` matching questions in the bank. As a side effect of this transition the exam's `max_score` is recomputed as the sum of `max_points` over every question now in the bank. The subsequent close-registration transition `OPEN_REGISTRATION → READY` is unconditional; it merely freezes the registration roster.

Registration itself is performed during `OPEN_REGISTRATION`: the administrator submits a candidate's `candidate_id` and `id_card_number` against the exam, producing a `CandidateRegistration` in status `REGISTERED`. The `enrolled_at` instant is stamped from the server clock at the moment of registration creation.

### 3.2. Attempt Lifecycle: from Enrolment through Active Examination

When the server clock reaches the exam's `start_time`, the exam transitions automatically `READY → IN_SESSION`, and only then may a `Candidate` open an attempt. Creating an attempt requires the candidate to supply the `registration_id` of their own `CandidateRegistration`; the server mirrors the registration's `candidate_id` onto the attempt as a computed field and creates the row in status `ENROLLED`. Exactly one attempt is allowed per registration.

The candidate next initiates identity verification: a transition `ENROLLED → IDENTITY_PENDING` that requires the exam to be `IN_SESSION` (otherwise `ERR_EXAM_NOT_IN_SESSION`) and has no other preconditions or side effects. They then submit an `IdentityVerificationRecord` with `verification_phase` set to `PRE_EXAM` and a `factor_results` object whose three boolean factors — `id_card`, `face`, and `live_detection` — must each be supplied. The `triggered_by_event_id` field on a `PRE_EXAM` record is null. The record's `outcome` is computed: it is `PASS` when all three factors are true, and `MISMATCH` if any factor is false. A `PASS` outcome transitions the attempt `IDENTITY_PENDING → ACTIVE`, stamps `started_at` from the server clock, runs the paper composition described in §3.3, and increments `identity_verification_count` by 1. A `MISMATCH` outcome instead transitions the attempt `IDENTITY_PENDING → DISQUALIFIED`, cascades the registration to `DISQUALIFIED`, appends an `AuditLogEntry` with `action_code` `IDENTITY_MISMATCH`, and likewise increments `identity_verification_count`. The state precondition is checked before identity-outcome evaluation; an exam that has already advanced past `IN_SESSION` rejects identity submissions with `ERR_EXAM_NOT_IN_SESSION`. A valid `PASS` against a non-`IN_SESSION` exam still fails for the same reason — the identity outcome does not bypass exam-state gating.

The aggregate `identity_verification_count` carried on the attempt is required to equal at every observation the number of `IdentityVerificationRecord` rows whose `attempt_id` is this attempt's `id`. This invariant must hold after every `PRE_EXAM` creation, after every `IN_EXAM_RECHECK` creation, and after every disqualification cascade — the cascade does not delete records, so the count is preserved across it.

During the `ACTIVE` interval the candidate may transiently lose connectivity: a network-disconnect call transitions the attempt `ACTIVE → SUSPENDED` and stamps `current_suspend_started_at` from the server clock. The reciprocal network-resume transition `SUSPENDED → ACTIVE` requires the exam to still be `IN_SESSION` (otherwise `ERR_EXAM_NOT_IN_SESSION`) and the current instant to be strictly before `end_time` (otherwise `ERR_EXAM_WINDOW_CLOSED`, because forced submission owns that transition); on success it adds the elapsed suspension interval — the current instant minus `current_suspend_started_at` — to `suspended_total_seconds`, and clears `current_suspend_started_at` back to null. This accumulation is the basis on which per-question and overall caps are enforced: elapsed time is taken as the current instant minus `started_at` minus `suspended_total_seconds`.

### 3.3. Paper Composition: Deterministic, Per-Candidate, Archived

At the moment the attempt transitions `IDENTITY_PENDING → ACTIVE`, the server composes the candidate's paper. The algorithm is deterministic and per-candidate: a 64-bit unsigned integer seed is derived from the first 16 hex characters of the SHA-256 of the attempt's `id`. The chosen `sampling_rule_type` then selects the branch.

In `RANDOM` mode the spec carries a `target_count`; the eligible pool is every `Question` under the exam. If the pool size is less than `target_count`, the composition fails with `ERR_SAMPLING_INFEASIBLE`. Otherwise the pool is shuffled with the seeded Fisher–Yates algorithm and the first `target_count` entries are taken.

In `STRATIFIED` mode the spec carries a `difficulty_buckets` object whose keys are `EASY`, `MEDIUM`, and `HARD`, each mapped to a required integer count. For each bucket the eligible pool is every question of that difficulty; if any bucket's eligible size falls short of the requested count, composition fails with `ERR_SAMPLING_INFEASIBLE`. Each bucket is shuffled independently with its own seeded stream, the requested count is taken from the front, and the three bucket outputs are concatenated in the fixed order `EASY` first, then `MEDIUM`, then `HARD`.

In `BLUEPRINT` mode the spec carries an ordered `slots` list; each slot is an object with a `topic`, a `question_type`, a `difficulty`, and a `count`. The slots are processed in declared order; for each, the eligible pool consists of questions matching all three filters, and a shortfall against `count` raises `ERR_SAMPLING_INFEASIBLE`. Each slot's pool is shuffled with its own seeded stream, the requested `count` is taken from the front, and the slot outputs are concatenated in the declared slot order.

After question selection, each chosen question of type `SINGLE_CHOICE` or `MULTI_CHOICE` has its options reordered: if the exam's `option_shuffle` is true, the options are shuffled using a fresh seed derived from the first 16 hex characters of the SHA-256 of the concatenation of the attempt's `id` and the question's `id`; otherwise the options retain their original order. The resulting key sequence is recorded against the question id in the attempt's `paper_option_order` map. The selected ids are persisted in declared order as `paper_question_ids`. Finally, a `paper_version_hash` is computed as the SHA-256 of the canonical JSON of the object `{ ids: paper_question_ids, opts: paper_option_order, exam_version: exam.version }` and archived on the attempt. All three of `paper_question_ids`, `paper_option_order`, and `paper_version_hash` are immutable from this point onward — they form the audit anchor that proves what the candidate actually saw. The composition is exact and uses no floating-point arithmetic.

### 3.4. Abnormal Behaviour Detection, Severity, and the Forced Recheck

A `Proctor` records suspicious behaviour by appending an `AbnormalEvent` against an `ExamAttempt`. The payload carries `detected_at` in unix seconds (which the server clamps to the attempt's `ACTIVE` interval), a `monitoring_channel` drawn from `SCREEN`, `CAMERA`, `AUDIO`, `PROCESS`, or `NETWORK`, a `behavior_rule_code` drawn from `FACE_LEAVE`, `MULTI_PERSON`, `WINDOW_SWITCH`, or `EXTERNAL_DEVICE`, a `marking_mode` of either `REALTIME_ALERT` (the channel emitted the alert during the live session) or `AFTER_THE_FACT` (a proctor flagged it during post-hoc review), and an `evidence_clip_uri` referencing the archived clip. Whenever the computed severity is anything other than `INFO`, the evidence URI is mandatory; omitting it rejects the call with `ERR_EVIDENCE_REQUIRED`. The event row is append-only.

Severity is computed as a single rounded scalar. The base score is determined by the rule code: `FACE_LEAVE` contributes 30, `WINDOW_SWITCH` contributes 40, `MULTI_PERSON` contributes 70, and `EXTERNAL_DEVICE` contributes 80. The base is then multiplied by a channel coefficient — `SCREEN` and `NETWORK` use a coefficient of 1.0, `PROCESS` uses 1.1, and `CAMERA` and `AUDIO` use 1.2 — and then by a marking-mode coefficient: `REALTIME_ALERT` uses 1.0 and `AFTER_THE_FACT` uses 0.5, halving the penalty when the event is discovered after the fact. The product is rounded half up to two decimal places to yield `severity_score`. The score is then bucketed into `severity`: a score strictly less than 35 is `INFO`; a score at least 35 and strictly less than 70 is `WARNING`; a score at least 70 is `CRITICAL`.

Two distinct cascades fire on `CRITICAL` severity while the attempt is still `ACTIVE`. The first is the forced recheck: when the rule code is in the set `FACE_LEAVE` or `MULTI_PERSON`, the event's `forced_recheck_emitted` is set to true, and the candidate must satisfy an `IN_EXAM_RECHECK` identity verification before any other state-changing call against the attempt will succeed. The second is the disqualification cascade: when the rule code is in the set `MULTI_PERSON` or `EXTERNAL_DEVICE` (note that `MULTI_PERSON` triggers both cascades simultaneously when it reaches `CRITICAL`), the attempt transitions `ACTIVE → DISQUALIFIED`, the candidate's registration cascades to `DISQUALIFIED`, every `PENDING` or `IN_PROGRESS` `GradingAssignment` for the attempt is moved to `DISCARDED`, both `provisional_score` and `final_score` are forced to 0, and the exam's `grading_progress_pct` is recomputed (a depth-three cascade: attempt → score zeroing → progress recomputation). An `AuditLogEntry` row is appended with `action_code` `SCORE_ADJUSTED` and the before/after final score captured in `delta`. The two variants of severity classification behave differently against the forced-recheck flag: a `REALTIME_ALERT` event uses the full 1.0 marking-mode coefficient and may trigger the recheck; an `AFTER_THE_FACT` event uses the 0.5 coefficient and never triggers a recheck, because the attempt is no longer `ACTIVE` by the time the event is recorded.

The `IN_EXAM_RECHECK` itself is submitted on the same identity-verifications endpoint as the `PRE_EXAM` step, but with `verification_phase` set to `IN_EXAM_RECHECK` and `triggered_by_event_id` referencing the `AbnormalEvent.id` of the `CRITICAL` event that emitted the recheck. The transition is admitted only when at least one such event exists for the attempt with `forced_recheck_emitted` true and no later `IdentityVerificationRecord` already settles it; otherwise the call is rejected with `ERR_NO_PENDING_RECHECK`. A `PASS` outcome is a self-loop — the attempt remains `ACTIVE` — and increments `identity_verification_count`. A `MISMATCH` outcome transitions `ACTIVE → DISQUALIFIED`, cascading registration disqualification, `AuditLogEntry` of `IDENTITY_MISMATCH`, demotion of every still-`PENDING` or `IN_PROGRESS` grading assignment for the attempt to `DISCARDED`, and the score-zeroing override; the identity-verification count is still incremented.

### 3.5. Submission, Forced Submission, and the End-of-Window Race

A candidate-initiated submit transitions the attempt `ACTIVE → SUBMITTED` while the exam remains `IN_SESSION` (otherwise `ERR_EXAM_NOT_IN_SESSION`). On success the server stamps `submitted_at` from the current instant, auto-grades every objective question against the candidate's responses (single-choice and true-false use scalar equality against `correct_answer`; multi-choice uses set equality), and creates two `PENDING` `GradingAssignment` rows for every subjective question — one with `blind_slot` `BLIND_A` and one with `blind_slot` `BLIND_B`. At creation each row's `candidate_answer_snapshot` is frozen from the candidate's response and is immutable thereafter; `marker_id` and `awarded_points` are left empty until a marker claims and scores. The optional `answers` field of the submit payload is the candidate's final answer set; the server accepts it as a complete replacement of any incrementally-staged answers.

Forced submission is the server's response to the exam end_time. When the server clock advances to at least `end_time`, every attempt still in `ACTIVE` or `SUSPENDED` is forced to `SUBMITTED`: `submitted_at` is stamped at `end_time` (not at the actual clock instant), objective questions are auto-graded, the same `BLIND_A` / `BLIND_B` `GradingAssignment` rows are created for the subjective questions, and an `AuditLogEntry` row with `action_code` `FORCED_SUBMIT` is appended for every attempt affected. The exam itself simultaneously transitions `IN_SESSION → GRADING`. The priority rules in §2.7 make this clock-driven cascade pre-empt every other candidate-initiated mutation: a network-resume, submit, or in-exam recheck arriving on or after `end_time` is rejected with `ERR_EXAM_WINDOW_CLOSED`, even if its other preconditions are valid. When a candidate's submit and the forced-submit fire effectively at the same instant, exactly one transition to `SUBMITTED` is recorded; the loser of that race receives `ERR_INVALID_STATE` because the attempt is no longer `ACTIVE` by the time its mutation is applied. Two concurrent `CRITICAL` `AbnormalEvent` inserts against the same `ACTIVE` attempt likewise both persist, but only one cascade to `DISQUALIFIED` is applied (the score-zeroing is idempotent); the second cascade attempt is rejected with `ERR_INVALID_STATE` because the attempt is no longer `ACTIVE`.

### 3.6. Double-Blind Grading, Arbitration, and Score Aggregation

Each subjective question's two `PENDING` `GradingAssignment` rows live in a shared pool until a `Marker` claims one. The claim transition `PENDING → IN_PROGRESS` requires that the acting marker has not previously claimed the sibling `blind_slot` for the same `(attempt_id, question_id)` pair; the server enforces this as a non-equality check on prior `marker_id` values for that pair. A violation rejects the claim with `ERR_DOUBLE_BLIND_VIOLATION`. Two markers concurrently attempting the same row resolve by first-writer-wins: exactly one claim succeeds and is recorded with `marker_id` set to the winner's `X-User-ID`; the loser receives `ERR_GRADING_ALREADY_CLAIMED`. The same marker concurrently attempting both slots of one pair likewise serialises to at most one success — the other claim is rejected with `ERR_DOUBLE_BLIND_VIOLATION` to preserve double-blind.

Once `IN_PROGRESS`, the marker scores the assignment by supplying `awarded_points` and a `rubric_breakdown` array of per-keypoint sub-points. Two business-constraint checks must hold: `awarded_points` must lie between 0 and the question's `max_points` inclusive (otherwise `ERR_AWARDED_OUT_OF_RANGE`), and the sum of points in `rubric_breakdown` must equal `awarded_points` exactly (otherwise `ERR_RUBRIC_SUM_MISMATCH`). On success the assignment transitions `IN_PROGRESS → SUBMITTED`. When both sibling slots reach `SUBMITTED`, the server compares the absolute value of their difference against the arbitration threshold of 2.0: if the gap is at most 2.0, the two rows transition together to `RESOLVED` and the attempt's `provisional_score` is recomputed; if the gap strictly exceeds 2.0, a third `GradingAssignment` row is spawned with `blind_slot` `ARBITRATION`, `status` `PENDING`, and `marker_id` left null, while the two existing `SUBMITTED` rows remain `SUBMITTED` pending the arbitrator's decision. Once the arbitrator claims and scores that third row, all three rows transition to `RESOLVED` together; the two blind rows remain RESOLVED for audit purposes but their values do not contribute further to the score.

Score aggregation runs in two pieces. Objective points accumulate at submission: for every objective question in `paper_question_ids` (type in the set `SINGLE_CHOICE`, `MULTI_CHOICE`, or `TRUE_FALSE`), the server awards the question's `max_points` when the candidate's answer matches `correct_answer` exactly, and zero otherwise. For multi-choice the comparison is set equality on the option keys; for single-choice and true-false it is scalar equality. The objective sum is exact.

Subjective points accumulate per question from `RESOLVED` rows only. For a question whose two blind rows resolved without arbitration, the per-question value is the arithmetic mean of `BLIND_A.awarded_points` and `BLIND_B.awarded_points` rounded half up to two decimal places — this is the round-per-question-first step, and the ordering is pinned. For a question whose blind pair triggered arbitration, the per-question value is the arbitrator's `awarded_points` rounded half up to two decimal places, and the two blind awards no longer contribute. A subjective question with no `RESOLVED` row yet contributes zero. The per-question values are then summed exactly without further rounding to produce `subjective_points`. The provisional score is the exact sum `objective_points + subjective_points`. Rows in `PENDING`, `IN_PROGRESS`, `SUBMITTED`, or `DISCARDED` are excluded from this calculation; their existence is the source of the gap between provisional and final scores during the `GRADING` phase. The provisional variant treats unresolved questions as zero and is therefore an underestimate; the final variant runs the same formula at the moment the attempt enters `GRADED`, where every subjective question has a `RESOLVED` row, and the result equals the final score prior to any appeal adjustments.

Once every `GradingAssignment` row for the attempt is in `RESOLVED` or `DISCARDED`, the attempt transitions automatically `SUBMITTED → GRADED`, the `final_score` is recomputed by the same formula, and the exam's `grading_progress_pct` is recomputed. The progress percentage itself is computed across the exam: `total_slots` is the count of `GradingAssignment` rows under non-`DISQUALIFIED` attempts of this exam; `done_slots` is the subset whose status is `RESOLVED` or `DISCARDED`. When `total_slots` is zero the percentage is reported as 100; otherwise it is 100 multiplied by `done_slots`, divided by `total_slots`, rounded half up to two decimal places.

### 3.7. Publication, Appeals, and the Window Close

Once every attempt has reached `GRADED`, the administrator may publish scores. The transition `GRADING → SCORES_PUBLISHED` is gated on `grading_progress_pct` reaching exactly 100; calling it earlier rejects with `ERR_GRADING_INCOMPLETE`. On success, every non-`DISQUALIFIED` attempt has its `final_score` frozen and is moved to `FINALIZED`. One server-clock tick later the exam transitions automatically `SCORES_PUBLISHED → APPEAL_WINDOW`, and remains there until the clock reaches publication time plus `appeal_window_seconds`, at which point the automatic transition `APPEAL_WINDOW → ARCHIVED` fires. At that moment every `Appeal` row still in `SUBMITTED`, `UNDER_REVIEW`, or `DECISION_PENDING` is forcibly transitioned to `REJECTED` with no score adjustment and no `AuditLogEntry` row (the terminal cascade is documented in the timeline itself).

A candidate may submit an `Appeal` only while the exam is in `APPEAL_WINDOW` (otherwise `ERR_EXAM_NOT_IN_APPEAL_WINDOW`). The payload references a `question_id` and a `candidate_reason`. The referenced question must appear in the attempt's `paper_question_ids` — you can only appeal a question you actually saw — and a violation rejects with `ERR_QUESTION_NOT_ON_PAPER`. An appeal that is `SUBMITTED` before the window closes survives even if its decision lands later (the window-close cascade rejects only those that have not yet been decided at that instant). Newly submitted appeals start in status `SUBMITTED`.

Claiming an appeal requires the acting `AppealOfficer` to have never marked the same `(attempt_id, question_id)` pair as a `Marker`. The server enforces this by checking that the officer's `X-User-ID` does not appear as `marker_id` on any `GradingAssignment` for that pair; a violation rejects with `ERR_APPEAL_OFFICER_WAS_MARKER`. The claim must also occur while the exam remains in `APPEAL_WINDOW` (otherwise `ERR_EXAM_NOT_IN_APPEAL_WINDOW`). When two officers try to claim the same `SUBMITTED` appeal at the same instant, the first writer wins and the loser receives `ERR_INVALID_STATE` because the appeal is no longer in `SUBMITTED`. A successful claim transitions the appeal `SUBMITTED → UNDER_REVIEW`.

Secondary marking is the officer's substantive review. The officer supplies `secondary_awarded_points`, which must lie between 0 and the question's `max_points` inclusive (otherwise `ERR_AWARDED_OUT_OF_RANGE`). On success the appeal transitions `UNDER_REVIEW → DECISION_PENDING` and the server computes `score_delta` as `secondary_awarded_points` minus the prior per-question subjective value used in the most recent `final_score_calculation` for that question; the delta can be negative. The officer then issues the decision. With `decision` set to `APPROVED` the appeal transitions `DECISION_PENDING → APPROVED`, the attempt's `final_score` is updated to its prior value plus `score_delta` (a depth-two cascade: appeal decision → attempt final score → audit log), and an `AuditLogEntry` row is appended with `action_code` `APPEAL_APPROVED` and the before/after final score recorded in `delta`. With `decision` set to `REJECTED` the appeal transitions `DECISION_PENDING → REJECTED` and no score adjustment occurs; an audit row is written for traceability but no score-adjustment delta is recorded. Once an appeal reaches either terminal state, it is final.

The two variants of the final score calculation reflect this appeal flow: the pre-appeal variant equals the provisional formula evaluated with the full `RESOLVED` set at the moment the attempt enters `GRADED` (no `APPROVED` appeals applied), and the post-appeal variant equals the pre-appeal value plus the algebraic sum of `score_delta` values across every `APPROVED` appeal applied to the attempt. The disqualification override remains supreme: if at any point the attempt is or becomes `DISQUALIFIED`, the final score is zero regardless of any other accumulated value.

## 4. Endpoint Definitions

For every endpoint described in §3, the table below summarises the HTTP method, path, a one-line description, and the role or roles authorised to call it. New resource creations return HTTP 201; all other mutations and reads return HTTP 200. The full request and response payloads for each endpoint must be reconstructed from the workflow narratives in §3 — the table intentionally omits payload structure so that implementers anchor field names against business context rather than schema tables.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/advance` | Advance the server logical clock; drives all time-gated automatic transitions and forced-submit cascades | `TestHarness` |
| POST | `/exams` | Create a new exam in `DRAFT` | `ExamAdmin` |
| GET | `/exams` | List exams | `Any` |
| GET | `/exams/{examId}` | Get an exam | `Any` |
| POST | `/exams/{examId}/open-registration` | Transition `DRAFT → OPEN_REGISTRATION`; checks question bank and sampling feasibility | `ExamAdmin` |
| POST | `/exams/{examId}/close-registration` | Transition `OPEN_REGISTRATION → READY` | `ExamAdmin` |
| POST | `/exams/{examId}/publish-scores` | Transition `GRADING → SCORES_PUBLISHED`; gated by full grading progress | `ExamAdmin` |
| POST | `/exams/{examId}/questions` | Add a question to the bank | `ExamAdmin` |
| GET | `/exams/{examId}/questions` | List questions for an exam | `ExamAdmin`, `Proctor` |
| GET | `/exams/{examId}/questions/{questionId}` | Get a question | `ExamAdmin`, `Proctor` |
| POST | `/exams/{examId}/registrations` | Register a candidate (only during `OPEN_REGISTRATION`) | `ExamAdmin` |
| GET | `/exams/{examId}/registrations` | List registrations for an exam | `ExamAdmin` |
| POST | `/exams/{examId}/attempts` | Create an attempt for a registration (one per registration; exam must be `IN_SESSION`) | `Candidate` |
| GET | `/exams/{examId}/attempts/{attemptId}` | Get an attempt (own attempt for `Candidate`; any for `ExamAdmin`/`Proctor`) | `Candidate`, `ExamAdmin`, `Proctor` |
| POST | `/exams/{examId}/attempts/{attemptId}/begin-identity-check` | Transition `ENROLLED → IDENTITY_PENDING` | `Candidate` |
| POST | `/exams/{examId}/attempts/{attemptId}/identity-verifications` | Append an identity verification record; drives `IDENTITY_PENDING`/`ACTIVE` and forced rechecks | `Candidate` |
| POST | `/exams/{examId}/attempts/{attemptId}/network-disconnect` | Transition `ACTIVE → SUSPENDED` | `Candidate` |
| POST | `/exams/{examId}/attempts/{attemptId}/network-resume` | Transition `SUSPENDED → ACTIVE` (rejected after `end_time`) | `Candidate` |
| POST | `/exams/{examId}/attempts/{attemptId}/abnormal-events` | Record an abnormal behaviour event | `Proctor` |
| GET | `/exams/{examId}/attempts/{attemptId}/abnormal-events` | List abnormal events for an attempt | `Proctor`, `ExamAdmin` |
| POST | `/exams/{examId}/attempts/{attemptId}/submit` | Transition `ACTIVE → SUBMITTED`; auto-grades objective; creates blind grading rows | `Candidate` |
| GET | `/exams/{examId}/grading-assignments` | List grading assignments | `Marker`, `ExamAdmin` |
| POST | `/exams/{examId}/grading-assignments/{assignmentId}/claim` | Transition `PENDING → IN_PROGRESS`; enforces double-blind invariant | `Marker` |
| POST | `/exams/{examId}/grading-assignments/{assignmentId}/score` | Transition `IN_PROGRESS → SUBMITTED`; sibling auto-resolves or spawns arbitration | `Marker` |
| POST | `/exams/{examId}/attempts/{attemptId}/appeals` | Submit an appeal for a specific question | `Candidate` |
| POST | `/exams/{examId}/appeals/{appealId}/claim` | Transition `SUBMITTED → UNDER_REVIEW`; segregation-of-duties enforced | `AppealOfficer` |
| POST | `/exams/{examId}/appeals/{appealId}/secondary-mark` | Transition `UNDER_REVIEW → DECISION_PENDING`; computes `score_delta` | `AppealOfficer` |
| POST | `/exams/{examId}/appeals/{appealId}/decide` | Transition `DECISION_PENDING → APPROVED` or `REJECTED`; cascades score on approval | `AppealOfficer` |
| GET | `/exams/{examId}/appeals` | List appeals (Candidate: own; AppealOfficer: `SUBMITTED`/`UNDER_REVIEW`; ExamAdmin: all) | `Candidate`, `AppealOfficer`, `ExamAdmin` |
| GET | `/audit-log` | List audit log entries | `ExamAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_EXAM_NOT_FOUND` | 404 |
| `ERR_QUESTION_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_ATTEMPT_NOT_FOUND` | 404 |
| `ERR_GRADING_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EXAM_NOT_IN_SESSION` | 409 |
| `ERR_EXAM_NOT_GRADING` | 409 |
| `ERR_EXAM_NOT_IN_APPEAL_WINDOW` | 409 |
| `ERR_GRADING_INCOMPLETE` | 409 |
| `ERR_EXAM_WINDOW_CLOSED` | 409 |
| `ERR_NO_PENDING_RECHECK` | 409 |
| `ERR_GRADING_ALREADY_CLAIMED` | 409 |
| `ERR_DOUBLE_BLIND_VIOLATION` | 409 |
| `ERR_APPEAL_OFFICER_WAS_MARKER` | 409 |
| `ERR_IDENTITY_MISMATCH` | 422 |
| `ERR_EVIDENCE_REQUIRED` | 422 |
| `ERR_AWARDED_OUT_OF_RANGE` | 422 |
| `ERR_RUBRIC_SUM_MISMATCH` | 422 |
| `ERR_RUBRIC_INVALID` | 422 |
| `ERR_QUESTION_NOT_ON_PAPER` | 422 |
| `ERR_QUESTION_BANK_EMPTY` | 422 |
| `ERR_SAMPLING_INFEASIBLE` | 422 |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 |

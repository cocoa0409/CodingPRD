# Teacher Certification Licensure API — Product Requirements Document

## 1. Introduction

A state education agency is modernizing how it credentials classroom teachers. Today the work of determining whether an applicant may teach — reviewing transcripts, verifying examination scores, running background and moral-character checks, mapping out-of-state licenses onto in-state equivalents, tracking deficiency remediation, auditing continuing-education hours at renewal, and disciplining license holders who violate professional standards — is fragmented across paper files and disconnected spreadsheets. This document specifies a single REST API, mounted under `/licensure`, through which agency staff and educators themselves execute the entire certification and licensure lifecycle.

The system serves two broad constituencies. Educators register, submit credential applications along with their transcripts and examination scores, pay fees, hold emergency permits while they remediate deficiencies, renew and reinstate their licenses, log continuing-education credits, and request additional endorsements. Agency staff — intake officers, credential evaluators, background investigators, legal officers, program-approval officers, and administrators — shepherd each application through intake, evaluation, background review, and final decision; approve or withdraw approval for educator-preparation programs; adjudicate flagged background checks and misconduct cases; issue discipline; and drive the logical clock that governs every time-based transition in the system. Because certification decisions carry legal weight, the API enforces strict segregation of duties, optimistic concurrency control on version-sensitive writes, deterministic fee and deficiency calculations, and cascading state propagation when a program loses approval, a background check is denied, or a license is revoked.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting individual, and `X-User-Role`, naming the role under which that individual acts. A request missing either header, or presenting a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized role list — or, for entity-backed roles, whose identity does not own the target resource — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as the API expects them, are: `Anonymous`, `Applicant`, `IntakeOfficer`, `CredentialEvaluator`, `BackgroundInvestigator`, `LegalOfficer`, `ProgramApprovalOfficer`, and `AgencyAdmin`.

`Anonymous` is the unauthenticated public caller; it may only self-register a new applicant record and can do nothing else. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` record; ownership checks on any resource that chains back to an applicant — an application, its transcripts, test scores, background checks, reciprocity evaluations, deficiency plans, emergency permits, and any license, endorsement, or CE credit derived from that applicant — compare the resource's applicant foreign key to `X-User-ID`, and a mismatch yields `ERR_FORBIDDEN`. An `Applicant` may read only its own resources. When `X-User-Role` is `IntakeOfficer`, `CredentialEvaluator`, `BackgroundInvestigator`, `LegalOfficer`, `ProgramApprovalOfficer`, or `AgencyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `investigator_user_id` on a `MisconductCase` when the case moves from `OPENED` to `INVESTIGATING` — but never compares it to an entity's `id` for ownership purposes. `AgencyAdmin` additionally drives the logical clock and reads all resources.

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

### 2.3. Pagination and List Filtering

Every list endpoint accepts two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100; the `offset` parameter defaults to 0. Results are always sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more` so clients can page deterministically.

Several list endpoints accept additional equality filters expressed as query parameters. The applicant list accepts an optional `status` filter. The application list accepts `applicant_id`, `program_id`, and `status`. The license list accepts `applicant_id`, `application_id`, and `status`. The emergency-permit list accepts `application_id`, `applicant_id`, and `status`. The disciplinary-action list accepts `case_id`, `license_id`, and `status`. All filters combine with pagination rather than replacing it.

### 2.4. Resource Identity and Common Properties

Every resource carries an `id` minted by the server as a UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Because every entity in this system participates in optimistic concurrency or audit review, every resource additionally carries an `updated_at` timestamp of the same format and an integer `version` that increments by exactly 1 on every mutation of that resource. Cascading mutations count: when an application is approved and its emergency permits convert, the application's `version` increments, and each mutated entity refreshes its own `updated_at`.

### 2.5. Validation Pipeline and Error Precedence

Incoming requests are validated against an ordered pipeline; a failure at an earlier stage masks all later checks, and the error returned is always the first one that fires. The order is fixed:

1. **Authentication.** Both headers must be present and the role must be one of the declared roles, else `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership.** The acting role must appear in the endpoint's authorized role list, and an `Applicant` may act only on resources whose applicant chain resolves to its own `X-User-ID`, else `ERR_FORBIDDEN`.
3. **Path existence.** Every identifier in the URL path must resolve to an existing resource, validated left to right, else `ERR_NOT_FOUND`.
4. **Body shape.** Required fields must be present, enum members must be valid, and numeric ranges must hold — `ssn_last4` is exactly four digits, `raw_score` is an integer from 0 to 100 inclusive, CE credit `hours` are greater than zero, and `suspension_end` is no earlier than `suspension_start` — else `ERR_VALIDATION`.
5. **State validity.** The target entity must be in a state from which the requested transition exists, and terminal states reject every transition, else `ERR_INVALID_STATE`.
6. **Safety gates.** A `BARRED` applicant cannot create applications or advance past intake (`ERR_APPLICANT_BARRED`); leaving `SUBMITTED` requires the moral-character attestation (`ERR_MORAL_ATTESTATION_REQUIRED`); renewal and surrender are blocked while a misconduct case is open (`ERR_OPEN_MISCONDUCT_CASE`); and an emergency permit cannot be issued while any of the applicant's background checks is `FLAGGED` or in `ADJUDICATION` (`ERR_BACKGROUND_HOLD`).
7. **Uniqueness and overlap constraints.** Duplicate open applications, duplicate endorsement subjects, overlapping permit intervals, overlapping suspension intervals, a second open CE audit, a second non-terminal background check, and adjudicator-equals-investigator are rejected here with the corresponding error from the catalogue.
8. **Pathway referential integrity.** Program attachment rules and reciprocity finalization are enforced at intake advance and endorsement activation.
9. **Temporal windows.** Renewal windows, reinstatement grace, permit duration, plan deadlines, and optimistic-concurrency version freshness are checked here.
10. **Fiscal rules.** Fee payment state, double payment, and reinstatement amount equality are checked here.
11. **Evaluation gates.** The four conditions guarding the advance from `EVALUATION` to `BACKGROUND_REVIEW`, plus the audit-hours check guarding an audit's passage, come last. Within this final stage, ties break in a fixed inner order: transcripts verified first (`ERR_TRANSCRIPTS_UNVERIFIED`), then required exams passed (`ERR_EXAM_REQUIREMENT_UNMET`), then deficiency cleared (`ERR_DEFICIENCY_OUTSTANDING`), then background cleared (`ERR_BACKGROUND_NOT_CLEARED`); the audit-hours check (`ERR_AUDIT_HOURS_INSUFFICIENT`) applies to the audit review transition.

### 2.6. Monetary Values, Rounding, and Numeric Precision

All monetary amounts are integer cents — never fractional — and every monetary rounding is round-half-up. Application fees, reinstatement fees, and the expedite surcharge all follow this rule. Where a calculation produces a rate applied to a subtotal, the product is rounded half-up to a whole cent before being added. Non-monetary calculations keep their own stated precision: the scaled GPA and the background risk score are each rounded half-up to two decimal places, deficiency hours are whole hours, and scaled test scores are whole points.

### 2.7. Optimistic Concurrency Control

Two write operations are version-guarded, and each requires a non-optional expected-version field in its request body.

Creating a deficiency plan against an application requires `expected_application_version`, carrying the `version` of the application as the client last observed it. If the application's current `version` has advanced since that read — for example because another evaluator has just created a plan that superseded the prior `PROPOSED` plan — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Posting a determination against a CE audit requires `expected_ce_audit_version`, carrying the audit's last observed `version`; because a newer determination legitimately supersedes earlier totals, a stale write is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.8. The Logical Clock and Time-Based Sweeps

The system runs on a logical clock, not the wall clock. At server startup the clock reads exactly 2026-08-01T00:00:00Z, and before any administrative set call the clock continues to read that default regardless of real elapsed time. An `AgencyAdmin` advances the clock through an admin-only capability whose request body carries `to_iso8601`, the instant the clock should move to.

Setting the clock triggers a sweep of every time-based transition in the system: licenses whose `expires_on` has been reached move from `ACTIVE` to `EXPIRED`; emergency permits whose validity window has opened move from `ISSUED` to `ACTIVE`, and permits whose window has closed move from `ISSUED` or `ACTIVE` to `EXPIRED`; deficiency plans whose `deadline` has passed with hours still outstanding move from `IN_PROGRESS` to `DEFAULTED`; and issued suspension actions whose `suspension_end` has been reached move from `ISSUED` to `SERVED`, restoring the license when no other issued suspension remains. These sweeps are described in full in §3 alongside the entities they govern.

### 2.9. Nested Resources and Path Validation

Many resources live beneath a parent in the URL hierarchy — transcripts, test scores, background checks, reciprocity evaluations, deficiency plans, and emergency permits beneath an application; endorsements, CE credits, CE audits, and misconduct cases beneath a license; disciplinary actions beneath a misconduct case. Path identifiers — `applicantId`, `programId`, `applicationId`, `id`, `transcriptId`, `testScoreId`, `checkId`, `evaluationId`, `planId`, `licenseId`, `endorsementId`, `permitId`, `creditId`, `auditId`, `caseId`, and `actionId` — are validated strictly left to right: each segment must exist before the next is examined, and the first missing identifier short-circuits the request with `ERR_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Applicant Registration and Credential Application Intake

A prospective educator enters the system through self-registration performed as `Anonymous`. Registration captures `full_name`, `email`, `date_of_birth`, `ssn_last4`, and `moral_character_attestation`. The `ssn_last4` value must be exactly four digits, and `email` must be unique across all applicants. The new applicant record starts in `REGISTERED` status; its lifecycle thereafter runs `REGISTERED` → `APPLICATION_IN_PROGRESS` → `LICENSED`, with `BARRED` as the disciplinary terminal.

With a registration in hand, the `Applicant` opens a credential application by supplying `applicant_id`, a `pathway` of `TRADITIONAL`, `ALTERNATIVE`, `RECIPROCITY`, or `REINSTATEMENT`, a `subject_area` of `ELEMENTARY`, `MATHEMATICS`, `SCIENCE`, or `SPECIAL_EDUCATION`, and a `grade_band` of `PK_6`, `G5_8`, or `G7_12`. Two optional inputs ride along: `program_id`, identifying the educator-preparation program the applicant completed, and `expedite_requested`, a boolean defaulting to false that asks for expedited handling at a surcharge. The program attachment rule is strict — `program_id` is required when the pathway is `TRADITIONAL` and forbidden for every other pathway; either violation is rejected with `ERR_PATHWAY_PROGRAM_REQUIRED`. An applicant who has been `BARRED` cannot open an application at all (`ERR_APPLICANT_BARRED`), and an applicant may hold at most one non-terminal application per subject area: a second application for the same applicant and `subject_area` while the first is still in flight is rejected with `ERR_DUPLICATE_OPEN_APPLICATION`.

Creation lands the application in `SUBMITTED` with `fee_status` of `UNPAID`, computes its `fee_cents`, and advances the applicant from `REGISTERED` to `APPLICATION_IN_PROGRESS`. The fee is an aggregation with a fixed recipe. The base fee depends on pathway: 10,000 cents for `TRADITIONAL`, 15,000 cents for `ALTERNATIVE`, 20,000 cents for `RECIPROCITY`, and 15,000 cents for `REINSTATEMENT`. To the base the system adds a transcript evaluation fee of 2,500 cents for each transcript currently attached to the application, counting every transcript regardless of its verification status; the sum of base and evaluation fees is the subtotal. When `expedite_requested` is true, a surcharge of 20 percent of the subtotal, rounded half-up to a whole cent, is added on top; otherwise the surcharge is zero. The final `fee_cents` is the subtotal plus the surcharge. This figure is recomputed at application creation, again every time a transcript is added, and again whenever the expedite flag changes.

The `Applicant` settles the fee through the fee-payment capability, which carries a `payment_token`. Paying moves `fee_status` from `UNPAID` to `PAID` and increments the application's `version` by 1; attempting to pay an application whose `fee_status` is already `PAID` is rejected with `ERR_FEE_ALREADY_PAID`.

An `IntakeOfficer` then advances the application from `SUBMITTED` to `INTAKE_REVIEW`. Every state-advance request in the API follows one shape: the request body carries a single target field, `to_status`, naming the desired next state, and the transition's preconditions decide whether the move is allowed. This first gate has three preconditions: `fee_status` must be `PAID` (else `ERR_FEE_UNPAID`, HTTP 402), the applicant's `moral_character_attestation` must be true (else `ERR_MORAL_ATTESTATION_REQUIRED`), and the applicant must not be `BARRED` (else `ERR_APPLICANT_BARRED`). A successful advance increments the application's `version` by 1. The same officer pushes the application from `INTAKE_REVIEW` to `EVALUATION`. For a `TRADITIONAL` application this second gate re-verifies that `program_id` is present (else `ERR_PATHWAY_PROGRAM_REQUIRED`), that the named program's `approval_status` is `APPROVED`, and that the application's `subject_area` appears in the program's `approved_subject_areas` — a failure of either program condition yields `ERR_PROGRAM_NOT_APPROVED`. For a `RECIPROCITY` application the gate instead requires a finalized reciprocity evaluation whose `outcome` is not `DENIED` (else `ERR_RECIPROCITY_NOT_FINALIZED`). Crossing into `EVALUATION` recomputes `deficiency_hours_required` (§3.4) and increments the application's `version` by 1.

Withdrawal is the applicant's own escape hatch, available from `SUBMITTED`, `INTAKE_REVIEW`, `EVALUATION`, or `DEFICIENCY_PENDING` to the owning `Applicant` only. Withdrawing from any of these states refunds the fee by setting `fee_status` to `REFUNDED` when it was `PAID` and increments `version` by 1. Withdrawal from `EVALUATION` or `DEFICIENCY_PENDING` additionally tears down in-flight artifacts: every emergency permit of the application in `ISSUED` or `ACTIVE` status moves to `REVOKED`, and every deficiency plan of the application in `PROPOSED`, `ACCEPTED`, `IN_PROGRESS`, or `EXTENDED` status moves to `SUPERSEDED`.

### 3.2. Educator-Preparation Program Approval

A `ProgramApprovalOfficer` registers each educator-preparation program with its `institution_name`, a unique `program_code`, and the list `approved_subject_areas` naming which subject-area values the program covers. A new program begins as a `CANDIDATE`. The officer moves it to `UNDER_REVIEW`, and from there either grants `APPROVED` or withdraws the candidacy entirely into `APPROVAL_WITHDRAWN`. An approved program may be placed on `PROBATION`, and probation may be lifted back to `APPROVED` — that cycle may repeat as often as oversight requires.

Withdrawal of approval from a program on probation is the system's sharpest cross-entity cascade. When a program moves `PROBATION` → `APPROVAL_WITHDRAWN`, every credential application that names the program via `program_id`, follows the `TRADITIONAL` pathway, and currently sits in `EVALUATION` is forced back into `DEFICIENCY_PENDING`, with its `deficiency_hours_required` raised by 12 hours but capped at 30 — the increment is the lesser of 30 and the current value plus 12 — and each affected application's `version` increments by 1. Thereafter the intake gate refuses to advance any application naming a withdrawn program, because the program is no longer `APPROVED`.

### 3.3. Transcripts, Coursework GPA, and Test Scores

The `Applicant` attaches evidence to an application in flight. Each transcript upload carries `institution_name`, a `degree_level` of `BACHELORS`, `MASTERS`, or `DOCTORATE`, `total_semester_hours`, and a `courses` array whose entries each name a `course_code`, `credit_hours`, and a `letter_grade` drawn from `A`, `A_MINUS`, `B`, `C`, `D`, or `F`. The transcript lands with `verification_status` of `UNVERIFIED`, its `application_id` bound to the owning application, and its arrival immediately triggers a recomputation of the application's `fee_cents` as described in §3.1.

Verification belongs to the `CredentialEvaluator`, who submits a target `verification_status` and, when verifying, the attested `subject_relevant_hours` — the number of semester hours on that transcript relevant to the application's subject area. Rejecting a transcript moves it to `REJECTED`, a terminal state, with no further computation. Verifying it runs the coursework GPA scaling, whose rounding order is pinned: each course is rounded first, then the results are summed. For every course, the quality points are the course's `credit_hours` multiplied by the grade points of its `letter_grade` — 4.0 for `A`, 3.7 for `A_MINUS`, 3.0 for `B`, 2.0 for `C`, 1.0 for `D`, and 0.0 for `F` — with each course's product rounded half-up to two decimal places. The transcript's `scaled_gpa` is then the sum of those per-course quality points divided by the sum of all `credit_hours`, the quotient rounded half-up to two decimal places. (Summing unrounded products and rounding once at the end yields different results and is expressly not the algorithm.) Verification stores `subject_relevant_hours`, flips the transcript to `VERIFIED`, and recomputes the application's `deficiency_hours_required`.

Test scores follow the same shape. The applicant reports an `exam_code` of `PRAXIS_CORE`, `PRAXIS_SUBJECT`, or `PEDAGOGY`, an integer `raw_score` between 0 and 100 inclusive, and the administration date `tested_on`; the report lands with `verification_status` of `REPORTED`. On verification the evaluator supplies the target `verification_status`; a rejection is terminal as `REJECTED`. A verification computes the `scaled_score` from the exam's scaling rule — each exam has an offset, a factor, and a passing threshold: for `PRAXIS_CORE` the scaled score is 100 plus the raw score times 1, and a result of at least 150 passes; for `PRAXIS_SUBJECT` it is 100 plus the raw score times 1, with at least 157 passing; for `PEDAGOGY` it is 100 plus the raw score times 2, with at least 160 passing. The comparison is inclusive — a scaled score exactly equal to the threshold passes — and the boolean outcome is stored in `passing`. Verifying a test score also recomputes the application's `deficiency_hours_required`, because exam results feed the deficiency formula's test-gap penalty.

Which exams an application must pass depends on its pathway and, for reciprocity, on the finalized outcome. `TRADITIONAL` and `ALTERNATIVE` applications each require a verified passing score on both `PRAXIS_SUBJECT` and `PEDAGOGY`. A `RECIPROCITY` application requires nothing when its finalized outcome is `FULL`, and requires a verified passing `PRAXIS_SUBJECT` score otherwise. A `REINSTATEMENT` application requires no exams at all.

### 3.4. Deficiency Determination and Deficiency Plans

The deficiency computation runs at three moments: when an application crosses from `INTAKE_REVIEW` to `EVALUATION`, whenever a transcript is verified, and whenever a test score is verified. It combines three inputs with a clamp applied last.

First, recognized subject hours are the sum of `subject_relevant_hours` across the application's `VERIFIED` transcripts, capped at 18 — the recognized figure is the lesser of that sum and 18. Second, the subject gap depends on pathway. For a `RECIPROCITY` application the gap is taken directly from the finalized evaluation's `deficiency_subject_hours`. For every other pathway the gap is the greater of zero and the difference between the subject's base requirement and the recognized hours; the base requirement is 24 hours for `ELEMENTARY`, 30 for `MATHEMATICS`, 30 for `SCIENCE`, and 27 for `SPECIAL_EDUCATION`. Third, a test-gap penalty of 6 hours applies whenever any required exam lacks a verified passing score, and a pathway addon of 6 hours applies when the pathway is `ALTERNATIVE`. The resulting `deficiency_hours_required` is the lesser of 30 and the sum of subject gap, test-gap penalty, and pathway addon. One override sits above the whole computation: if a deficiency plan with `COMPLETED` status exists for the application, `deficiency_hours_required` is 0 regardless of what the formula would produce.

When `deficiency_hours_required` is greater than zero, a `CredentialEvaluator` may move the application from `EVALUATION` to `DEFICIENCY_PENDING` — attempting that move when no deficiency exists is rejected with `ERR_DEFICIENCY_NOT_PRESENT`. The evaluator then creates a deficiency plan, a version-guarded write that must carry `expected_application_version` matching the application's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The new plan snapshots `required_hours` from the application's current `deficiency_hours_required`, stamps its `deadline` as the creation clock time plus 730 days, and starts in `PROPOSED` with `extension_used` false and `completed_hours` at zero. Creating a plan has two side effects beyond itself: any existing `PROPOSED` plan for the same application is superseded to `SUPERSEDED`, and the application's `version` increments by 1.

The evaluator accepts a plan by moving it `PROPOSED` → `ACCEPTED`. Evidence of completed coursework arrives through evidence postings, each carrying the `hours` completed; the evaluator posts them. The first posting against an `ACCEPTED` plan moves it to `IN_PROGRESS`, and each posting — against an `IN_PROGRESS` plan or an `EXTENDED` one — adds its `hours` to `completed_hours`. The moment `completed_hours` reaches or exceeds `required_hours`, the plan completes automatically to `COMPLETED`, and the linked application becomes eligible to return from `DEFICIENCY_PENDING` to `EVALUATION`. That return, executed by the evaluator, requires a `COMPLETED` plan for the application (else `ERR_DEFICIENCY_OUTSTANDING`); it zeroes `deficiency_hours_required` — the plan is satisfied — and increments the application's `version`. The cycle `EVALUATION` → `DEFICIENCY_PENDING` → `EVALUATION` may repeat as new deficiencies surface.

Time is the plan's enemy. A clock sweep that finds the current instant later than the plan's `deadline` while `completed_hours` remains below `required_hours` moves the plan from `IN_PROGRESS` to `DEFAULTED`. If the defaulted plan has never used its extension, the evaluator may move it `DEFAULTED` → `EXTENDED`, which flips `extension_used` to true and pushes `deadline` out by another 365 days; a plan whose extension was already consumed cannot be extended again, and the attempt is rejected with `ERR_PLAN_DEADLINE_PASSED`. Default is fatal once the extension is spent: when a plan defaults while `extension_used` is already true, a linked application sitting in `DEFICIENCY_PENDING` is forced to `DENIED`.

### 3.5. Reciprocity Evaluation for Out-of-State Educators

An application on the `RECIPROCITY` pathway requires a reciprocity evaluation before it can leave intake. The `CredentialEvaluator` opens the evaluation with the `source_state` — the two-letter state code of the out-of-state license — the `source_license_type` of `STANDARD`, `PROFESSIONAL`, or `PROVISIONAL`, and the verified `years_teaching` out of state. The evaluation opens with `finalized` false and its `outcome` null until finalization.

Finalization takes a `mapping_mode` of `DETERMINISTIC` or `COMMITTEE` and computes both `outcome` — one of `FULL`, `PARTIAL`, or `DENIED` — and `deficiency_subject_hours`, after which `finalized` is true and the chosen `mapping_mode` is recorded. Both variants begin from the same table keyed on the pair of source state and license type: a `STANDARD` license from Texas maps to `FULL` with zero deficiency hours; a `PROFESSIONAL` license from Florida maps to `PARTIAL` with 6 deficiency hours; a `PROVISIONAL` license from Nevada maps to `DENIED` with zero hours; and any pair absent from the table maps to `PARTIAL` with 12 deficiency hours.

The variants diverge on experience. Under `DETERMINISTIC`, the table result stands and `years_teaching` is ignored. Under `COMMITTEE`, an applicant with at least 3 years of teaching earns a one-level upgrade applied to the table result: a table `DENIED` becomes `PARTIAL` with 12 deficiency hours; a table `PARTIAL` becomes `FULL` with its deficiency hours reduced by 6, never below zero; and a table `FULL` is unchanged. An applicant with fewer than 3 years keeps the table result. Identical inputs can therefore produce different outcomes under the two modes, and the intake gate accepts the evaluation only once it is finalized with an `outcome` other than `DENIED` (else `ERR_RECIPROCITY_NOT_FINALIZED` at the advance).

### 3.6. Background Checks and Moral Character Review

Every application must clear a background check before it can be decided. A `BackgroundInvestigator` opens the check with the `adverse_findings` array, each finding recording an `offense_category` of `FELONY_VIOLENT`, `FELONY_OTHER`, `MISDEMEANOR_DRUG`, `MISDEMEANOR_OTHER`, or `INFRACTION`, an `offense_date`, and a `disposition` of `CONVICTION`, `DISMISSED`, or `PENDING`. The check opens in `INITIATED`, and only one non-terminal check may exist per application — opening a second while the first is still in flight is rejected with `ERR_BACKGROUND_CHECK_OPEN`.

Fingerprints move the check forward. When the investigator submits the transition toward `PRINTS_SUBMITTED`, the request must carry `fingerprint_submitted_at`, the timestamp the prints were taken (a missing timestamp is `ERR_VALIDATION`). `PRINTS_SUBMITTED` is transient — the request never rests there. Submitting prints computes the check's `risk_score` and immediately lands the check in `CLEARED` or `FLAGGED`.

The risk score weights each finding by category: 100 for `FELONY_VIOLENT`, 60 for `FELONY_OTHER`, 40 for `MISDEMEANOR_DRUG`, 25 for `MISDEMEANOR_OTHER`, and 10 for `INFRACTION`. Each finding's age in years is the number of days between its `offense_date` and `fingerprint_submitted_at` divided by 365.0, and age applies a decay factor: findings aged at most 3 years count at full weight, findings older than 3 years and at most 7 years count at half weight, and findings older than 7 years count at one quarter. Disposition then scales the weighted value: a `CONVICTION` contributes its full decayed weight, a `PENDING` finding contributes half of its decayed weight, and a `DISMISSED` finding contributes nothing. The `risk_score` is the sum across all findings, rounded half-up to two decimal places. Separately, a forced-flag disqualifier applies whenever any finding is a `FELONY_VIOLENT` `CONVICTION` aged at most 10 years. A check whose `risk_score` is below 40 and carries no forced flag clears automatically; anything else lands in `FLAGGED`.

A `LegalOfficer` adjudicates flagged checks, moving them `FLAGGED` → `ADJUDICATION` and then to a final `CLEARED` or `DENIED`. Denial cascades twice: the linked application, if sitting in `BACKGROUND_REVIEW`, transitions to `DENIED`, and that denial in turn revokes every emergency permit of the application still `ISSUED` or `ACTIVE`. The background status also guards the application's own gates — advancing from `EVALUATION` to `BACKGROUND_REVIEW` requires that a background check exists for the application and that its status is not `DENIED` (else `ERR_BACKGROUND_NOT_CLEARED`), and the investigator's advance from `BACKGROUND_REVIEW` to `PENDING_DECISION` requires the check to be fully `CLEARED` (else `ERR_BACKGROUND_NOT_CLEARED`).

### 3.7. Application Decisions, License Issuance, and Emergency Permits

When the evidence record is complete, the `CredentialEvaluator` advances the application from `EVALUATION` to `BACKGROUND_REVIEW`. Four preconditions guard the move, evaluated in the fixed inner order of §2.5: at least one transcript exists for the application and every transcript's `verification_status` is `VERIFIED` (else `ERR_TRANSCRIPTS_UNVERIFIED`); every exam the pathway requires — per the rules of §3.3 — has a `VERIFIED` test score with `passing` true (else `ERR_EXAM_REQUIREMENT_UNMET`); `deficiency_hours_required` is zero (else `ERR_DEFICIENCY_OUTSTANDING`); and a background check exists for the application whose status is not `DENIED` (else `ERR_BACKGROUND_NOT_CLEARED`). A successful advance increments the application's `version` by 1.

From `PENDING_DECISION` the `CredentialEvaluator` renders the final decision. Approval creates the license: `status` `ACTIVE`, a server-minted sequential `license_number` used for identity only, `issued_on` set to the current clock time, `expires_on` set exactly 60 months after issuance, and `subject_area`, `grade_band`, and `applicant_id` copied from the application. Approval also flips the applicant to `LICENSED`, converts every emergency permit of the application still `ISSUED` or `ACTIVE` to `CONVERTED`, and increments the application's `version`. Denial from `PENDING_DECISION` revokes every `ISSUED` or `ACTIVE` emergency permit of the application and increments `version`. `APPROVED`, `DENIED`, and `WITHDRAWN` are the application's terminal states.

An emergency permit lets a district employ the educator while a deficiency is being remediated. The evaluator issues one against an application by supplying the employing `district_code` and a validity window from `valid_from` to `valid_until`. Issuance is gated on several conditions: the application must be in `DEFICIENCY_PENDING` with a deficiency plan in `ACCEPTED` or `IN_PROGRESS` (else `ERR_INVALID_STATE`); no background check of the applicant may be `FLAGGED` or in `ADJUDICATION` (else `ERR_BACKGROUND_HOLD`); the window length may not exceed 365 days (else `ERR_PERMIT_DURATION_EXCEEDED`); and the half-open interval from `valid_from` up to but not including `valid_until` must not collide with any `ISSUED` or `ACTIVE` permit held by the same applicant in the same district — touching endpoints, where the new `valid_from` equals a prior permit's `valid_until`, do not collide and are allowed, while any genuine overlap is rejected with `ERR_PERMIT_INTERVAL_OVERLAP`. A new permit starts in `ISSUED` with `applicant_id` copied from the application.

The clock sweep manages the permit's calendar life: an `ISSUED` permit whose `valid_from` has been reached while `valid_until` is still in the future becomes `ACTIVE`; a permit whose `valid_until` has passed moves to `EXPIRED` from either `ISSUED` or `ACTIVE`. Beyond the calendar, a permit converts to `CONVERTED` when its application is approved, and a `LegalOfficer` or `CredentialEvaluator` may revoke a permit outright to `REVOKED`. Revocation also arrives by cascade — application denial, application withdrawal, and the applicant becoming `BARRED` each revoke every `ISSUED` or `ACTIVE` permit tied to that application or applicant.

### 3.8. License Lifecycle: Renewal, Reinstatement, and Continuing-Education Audits

A license lives on a 60-month term. When the clock reaches `expires_on`, the sweep moves an `ACTIVE` license to `EXPIRED`. Before that happens, the licensee may renew: the owning `Applicant` submits the renewal with a `payment_token`, and three preconditions apply — the current clock time must fall within the renewal window that opens 180 days before `expires_on` and closes when `expires_on` arrives, inclusive of the opening instant and exclusive of expiry (outside the window the request is rejected with `ERR_RENEWAL_WINDOW_CLOSED`); a CE audit of `audit_variant` `STANDARD` with `PASSED` status must exist for the license's current cycle (else `ERR_AUDIT_NOT_PASSED`); and no misconduct case on the license may be in `OPENED`, `INVESTIGATING`, or `HEARING` (else `ERR_OPEN_MISCONDUCT_CASE`). Renewal is a self-loop that keeps the license `ACTIVE`, extends `expires_on` by another 60 months, and increments the license's `version` by 1.

An expired license is not dead. Within a grace period ending 730 days after `expires_on` — a request after that instant is rejected with `ERR_REINSTATE_GRACE_EXPIRED` — the owner may reinstate by paying the computed reinstatement fee in `pays_amount_cents`; any amount other than the computed figure is rejected with `ERR_FEE_AMOUNT_MISMATCH`, and a `PASSED` audit of `audit_variant` `RESTORATION` must exist (else `ERR_AUDIT_NOT_PASSED`). When several of these gates fail in the same request, they fire in a fixed order: the grace window first (`ERR_REINSTATE_GRACE_EXPIRED`), then the restoration-audit gate (`ERR_AUDIT_NOT_PASSED`), and the amount-equality check (`ERR_FEE_AMOUNT_MISMATCH`) last. The reinstatement fee is computed in a pinned order. The days overdue are the whole days between `expires_on` and the current clock time, at least one by the license's `EXPIRED` state. The late fee tiers on those days: at most 365 days overdue costs 5,000 cents, and from 366 up to 730 days overdue costs 15,000 cents. The subtotal is 15,000 cents of base renewal plus the late fee. The surcharge rate is selected by that subtotal: a subtotal below 25,000 cents pays no surcharge, a subtotal from 25,000 through 39,999 cents pays 10 percent, and a subtotal of 40,000 cents or more pays 20 percent. The surcharge is the subtotal times its rate, rounded half-up to a whole cent, and the fee due is subtotal plus surcharge. Successful reinstatement returns the license to `ACTIVE`, resets `expires_on` to the current clock time plus 60 months, and increments `version`.

Continuing education feeds both gates. The licensee submits each credit with `provider_name`, a `category` of `PEDAGOGY`, `CONTENT`, `ETHICS`, or `TECHNOLOGY`, the `hours` earned — which must be greater than zero — and the completion date `earned_on`; the credit lands in `SUBMITTED`. A `CredentialEvaluator` verifies credits to `VERIFIED`, voids them to `VOIDED`, and reinstates a voided credit back to `VERIFIED` after appeal — the `VERIFIED` → `VOIDED` → `VERIFIED` cycle preserves pair-invariant audited totals, because open audits are never recomputed mid-flight when a credit changes; they wait for the next determination.

An audit opens when the evaluator requests one for the license, choosing the `audit_variant`. Opening stamps `cycle_start` as the license's `issued_on` for the current term and `cycle_end` as its `expires_on`, computes the initial totals, and lands the audit in `INITIATED`; only one audit may be open at a time per license, where open means `INITIATED`, `UNDER_REVIEW`, or `REMEDIATION` — a second open audit is rejected with `ERR_AUDIT_ALREADY_OPEN`. The audit's `required_hours` are 60 for a `STANDARD` audit and 90 for a `RESTORATION` audit.

The audit total is computed chronologically with a whole-credit fit-or-skip rule. Candidate credits are the license's `VERIFIED` credits whose `earned_on` falls at or after `cycle_start` and strictly before `cycle_end`; a `RESTORATION` audit additionally admits credits earned in the 12 months before `cycle_start`. Candidates are processed in `earned_on` ascending order, ties broken by `created_at` ascending, and each credit counts only if it fits entirely within the remaining cap of its category — otherwise it counts zero rather than partially. The category caps for a `STANDARD` audit are 30 hours of `PEDAGOGY`, 60 of `CONTENT`, 5 of `ETHICS`, and 10 of `TECHNOLOGY`; a `RESTORATION` audit raises them to 45, 90, 8, and 15 respectively. The audit's `verified_hours` are the sum of the counted hours, and because processing order changes which credits fit, the same credit set can total differently between variants.

Totals are refreshed through determinations, a version-guarded write requiring `expected_ce_audit_version` equal to the audit's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Each determination recomputes `verified_hours` and `required_hours` under the rules above and increments the audit's `version`, so the latest determination supersedes all earlier totals. The evaluator walks the audit `INITIATED` → `UNDER_REVIEW` and then renders the outcome: passing requires `verified_hours` of at least `required_hours` per the latest determination (else `ERR_AUDIT_HOURS_INSUFFICIENT`) and lands the audit in `PASSED`, its terminal state; failing moves it to `FAILED`. A failed audit enters `REMEDIATION`, and after makeup credits the evaluator returns it to `UNDER_REVIEW` — the `FAILED` → `REMEDIATION` → `UNDER_REVIEW` loop may repeat until the audit passes.

The license holder may also walk away: surrender by the owning `Applicant` moves an `ACTIVE` license to `SURRENDERED`, provided no misconduct case is in `OPENED`, `INVESTIGATING`, or `HEARING` (else `ERR_OPEN_MISCONDUCT_CASE`), and removes every endorsement of the license in `PENDING_EVALUATION` or `ACTIVE` to `REMOVED` while incrementing the license's `version`.

### 3.9. Endorsements, Misconduct Investigations, and Discipline

A licensee broadens a license through endorsements. The owning `Applicant` requests an endorsement with the desired `subject_area` and `grade_band`; the request is rejected with `ERR_ENDORSEMENT_DUPLICATE` when the license already carries that `subject_area` as its base subject or as an endorsement in `PENDING_EVALUATION` or `ACTIVE`. A new endorsement starts in `PENDING_EVALUATION`. The evaluator activates it to `ACTIVE` — activation requires the license itself to be `ACTIVE` (else `ERR_INVALID_STATE`) — or denies it to `DENIED`. The licensee removes an `ACTIVE` endorsement to `REMOVED`. And when the license is revoked, every endorsement in `PENDING_EVALUATION` or `ACTIVE` cascades to `REVOKED`. `DENIED`, `REMOVED`, and `REVOKED` are terminal.

Professional discipline begins when a `LegalOfficer` opens a misconduct case against a license, naming the `allegation_category` — `BOUNDARY_VIOLATION`, `FINANCIAL_MISCONDUCT`, `INCOMPETENCE`, or `CRIMINAL_CONDUCT`. The case opens in `OPENED`. A `BackgroundInvestigator` takes it to `INVESTIGATING`, and that move records the acting `X-User-ID` as the case's `investigator_user_id`. The officer may dismiss an unfounded case directly from `OPENED` to `DISMISSED`. Once investigation concludes, a `LegalOfficer` moves the case to `HEARING`, and from `HEARING` to `ADJUDICATED` — adjudication requires the request to carry the `finding`, either `SUBSTANTIATED` or `UNSUBSTANTIATED` (a missing finding is rejected with `ERR_CASE_FINDING_REQUIRED`), and segregation of duties forbids the adjudicating officer from being the recorded investigator: if the acting `X-User-ID` equals the case's `investigator_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Sanctions are proposed as disciplinary actions on an adjudicated case, each carrying a `sanction_type` of `REPRIMAND`, `SUSPENSION`, `REVOCATION`, or `FINE`, with the action's `license_id` copied from its case. A `SUSPENSION` proposal must carry `suspension_start` and `suspension_end`, with `suspension_end` no earlier than `suspension_start` (a range violation is `ERR_VALIDATION`), and its closed interval — both endpoints included — must not overlap any `PROPOSED` or `ISSUED` suspension on the same license; under closed-interval semantics two suspensions that merely touch at an endpoint do overlap, and any such collision is rejected with `ERR_SUSPENSION_INTERVAL_OVERLAP`. A `FINE` proposal must carry `fine_cents`. Every proposal starts in `PROPOSED`.

Issuing an action requires its case to be `ADJUDICATED` with a `SUBSTANTIATED` finding (else `ERR_INVALID_STATE`), and issuance cascades according to the sanction. Issuing a `SUSPENSION` moves an `ACTIVE` license to `SUSPENDED`, incrementing the license's `version`. Issuing a `REVOCATION` moves a license in `ACTIVE` or `SUSPENDED` to `REVOKED` and then cascades three links deep: the applicant becomes `BARRED`; every endorsement of the license in `PENDING_EVALUATION` or `ACTIVE` moves to `REVOKED`; and the applicant's new `BARRED` status revokes every emergency permit of that applicant in `ISSUED` or `ACTIVE` — each with the license's `version` incremented. In both cases the linked case moves from `ADJUDICATED` to `SANCTION_ISSUED`. A `LegalOfficer` may instead vacate a `PROPOSED` action to `VACATED`, and dismissing an adjudicated case — allowed only when the `finding` is `UNSUBSTANTIATED` (else `ERR_INVALID_STATE`) — vacates every `PROPOSED` action on the case as it moves to `DISMISSED`. `SANCTION_ISSUED` and `DISMISSED` are the case's terminal states.

Time serves suspensions automatically: a clock sweep moves an `ISSUED` action whose sanction is `SUSPENSION` to `SERVED` once the clock reaches `suspension_end`, and when no other `ISSUED` suspension remains on the license, the license returns from `SUSPENDED` to `ACTIVE` with its `version` incremented. `SERVED` and `VACATED` are the action's terminal states.

## 4. Endpoint Definitions

All endpoints live under the `/licensure` mount, except the administrative clock. Creating a new resource returns HTTP 201; operations that modify an existing resource, list, or read return HTTP 200. Request and response bodies, side effects, and preconditions are specified in §3; this table is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /licensure/applicants | Register an applicant | Anonymous |
| GET | /licensure/applicants/{applicantId} | Get one applicant | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/applicants | List applicants | IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/educator-prep-programs | Create educator-preparation program | ProgramApprovalOfficer |
| GET | /licensure/educator-prep-programs/{programId} | Get one program | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/educator-prep-programs/{programId}/state | Advance program approval state | ProgramApprovalOfficer |
| POST | /licensure/applications | Create credential application | Applicant |
| GET | /licensure/applications/{applicationId} | Get one application | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/applications | List applications | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/applications/{applicationId}/fee-payment | Pay application fee | Applicant |
| POST | /licensure/applications/{applicationId}/state | Advance, withdraw, or deny application per state machine | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator |
| POST | /licensure/applications/{id}/transcripts | Upload a transcript | Applicant |
| GET | /licensure/applications/{id}/transcripts | List transcripts of an application | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/transcripts/{transcriptId} | Get one transcript | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/transcripts/{transcriptId}/verify | Verify or reject a transcript; computes scaled GPA | CredentialEvaluator |
| POST | /licensure/applications/{id}/test-scores | Report a test score | Applicant |
| GET | /licensure/applications/{id}/test-scores | List test scores of an application | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/test-scores/{testScoreId} | Get one test score | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/test-scores/{testScoreId}/verify | Verify or reject a test score; computes scaled score and passing | CredentialEvaluator |
| POST | /licensure/applications/{id}/background-checks | Open a background check | BackgroundInvestigator |
| GET | /licensure/applications/{id}/background-checks | List background checks of an application | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/background-checks/{checkId} | Get one background check | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/background-checks/{checkId}/state | Advance background check; prints submission auto-resolves to cleared or flagged | BackgroundInvestigator, LegalOfficer |
| POST | /licensure/applications/{id}/reciprocity-evaluations | Open a reciprocity evaluation (RECIPROCITY pathway only) | CredentialEvaluator |
| GET | /licensure/applications/{id}/reciprocity-evaluations | List reciprocity evaluations of an application | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/reciprocity-evaluations/{evaluationId} | Get one reciprocity evaluation | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/reciprocity-evaluations/{evaluationId}/finalize | Finalize with a mapping mode; computes outcome and deficiency hours | CredentialEvaluator |
| POST | /licensure/applications/{id}/deficiency-plans | Create a deficiency plan (supersedes an existing proposed plan; OCC on application version) | CredentialEvaluator |
| GET | /licensure/applications/{id}/deficiency-plans | List deficiency plans of an application | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/deficiency-plans/{planId} | Get one deficiency plan | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/deficiency-plans/{planId}/state | Accept or extend a plan | CredentialEvaluator |
| POST | /licensure/deficiency-plans/{planId}/evidence | Post completed deficiency hours | CredentialEvaluator |
| GET | /licensure/licenses/{licenseId} | Get one license | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/licenses | List licenses | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/licenses/{licenseId}/renew | Renew an active license inside the renewal window | Applicant |
| POST | /licensure/licenses/{licenseId}/reinstate | Reinstate an expired license within grace with restoration audit and computed fee | Applicant |
| POST | /licensure/licenses/{licenseId}/surrender | Voluntarily surrender an active license | Applicant |
| POST | /licensure/licenses/{id}/endorsements | Request an endorsement on a license | Applicant |
| GET | /licensure/licenses/{id}/endorsements | List endorsements of a license | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/endorsements/{endorsementId} | Get one endorsement | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/endorsements/{endorsementId}/state | Activate or deny (evaluator) or remove (applicant) an endorsement | CredentialEvaluator, Applicant |
| POST | /licensure/applications/{applicationId}/emergency-permits | Issue an emergency permit while a deficiency plan is active | CredentialEvaluator |
| GET | /licensure/emergency-permits/{permitId} | Get one permit | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/emergency-permits | List permits | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/emergency-permits/{permitId}/state | Revoke a permit | LegalOfficer, CredentialEvaluator |
| POST | /licensure/licenses/{id}/ce-credits | Submit a CE credit | Applicant |
| GET | /licensure/licenses/{id}/ce-credits | List CE credits of a license | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/ce-credits/{creditId} | Get one CE credit | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/ce-credits/{creditId}/state | Verify, void, or reinstate a CE credit | CredentialEvaluator |
| POST | /licensure/licenses/{id}/ce-audits | Open a CE audit for the license's current cycle | CredentialEvaluator |
| GET | /licensure/licenses/{id}/ce-audits | List CE audits of a license | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/ce-audits/{auditId} | Get one CE audit | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/ce-audits/{auditId}/state | Advance audit review state | CredentialEvaluator |
| POST | /licensure/ce-audits/{auditId}/determinations | Recompute audit totals (OCC on audit version); latest determination supersedes earlier totals | CredentialEvaluator |
| POST | /licensure/licenses/{id}/misconduct-cases | Open a misconduct case | LegalOfficer |
| GET | /licensure/licenses/{id}/misconduct-cases | List misconduct cases of a license | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/misconduct-cases/{caseId} | Get one misconduct case | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/misconduct-cases/{caseId}/state | Advance case; adjudication enforces segregation of duties | LegalOfficer, BackgroundInvestigator |
| POST | /licensure/misconduct-cases/{caseId}/disciplinary-actions | Propose a disciplinary action | LegalOfficer |
| GET | /licensure/disciplinary-actions/{actionId} | Get one disciplinary action | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| GET | /licensure/disciplinary-actions | List disciplinary actions | Applicant, IntakeOfficer, CredentialEvaluator, BackgroundInvestigator, LegalOfficer, ProgramApprovalOfficer, AgencyAdmin |
| POST | /licensure/disciplinary-actions/{actionId}/state | Issue or vacate a disciplinary action; issuance cascades to license, applicant, endorsements, permits | LegalOfficer |
| POST | /_clock/set_current_utc | Set the logical clock; sweeps time-based transitions (license expiry, permit activation/expiry, plan default, suspension served) | AgencyAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status summary.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_APPLICANT_BARRED | 409 |
| ERR_MORAL_ATTESTATION_REQUIRED | 409 |
| ERR_OPEN_MISCONDUCT_CASE | 409 |
| ERR_BACKGROUND_HOLD | 409 |
| ERR_DUPLICATE_OPEN_APPLICATION | 409 |
| ERR_ENDORSEMENT_DUPLICATE | 409 |
| ERR_PERMIT_INTERVAL_OVERLAP | 409 |
| ERR_SUSPENSION_INTERVAL_OVERLAP | 409 |
| ERR_AUDIT_ALREADY_OPEN | 409 |
| ERR_BACKGROUND_CHECK_OPEN | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_PATHWAY_PROGRAM_REQUIRED | 409 |
| ERR_PROGRAM_NOT_APPROVED | 409 |
| ERR_RECIPROCITY_NOT_FINALIZED | 409 |
| ERR_RENEWAL_WINDOW_CLOSED | 409 |
| ERR_REINSTATE_GRACE_EXPIRED | 409 |
| ERR_PERMIT_DURATION_EXCEEDED | 409 |
| ERR_PLAN_DEADLINE_PASSED | 409 |
| ERR_FEE_UNPAID | 402 |
| ERR_FEE_ALREADY_PAID | 409 |
| ERR_FEE_AMOUNT_MISMATCH | 409 |
| ERR_DEFICIENCY_OUTSTANDING | 409 |
| ERR_TRANSCRIPTS_UNVERIFIED | 409 |
| ERR_EXAM_REQUIREMENT_UNMET | 409 |
| ERR_BACKGROUND_NOT_CLEARED | 409 |
| ERR_AUDIT_NOT_PASSED | 409 |
| ERR_AUDIT_HOURS_INSUFFICIENT | 409 |
| ERR_CASE_FINDING_REQUIRED | 409 |

# University Application Platform API — Product Requirements Document

## 1. Introduction

Applying to college today involves juggling a small fleet of half-aligned systems: a profile somewhere, essays tailored to each school, recommendation letters chased down from busy teachers, financial-aid forms in two competing formats, and rolling waitlist movement that nobody can predict. This document specifies a single back-end service — the University Application Platform — that draws all of these workflows into one coherent API. A prospective student maintains one applicant profile, submits multi-school joint applications, and tracks the state of every essay, letter, and aid package from a unified vantage point. Universities, in parallel, register their programs, run admission reviews, and operate the yield-management machinery that converts a roster of admitted candidates into an enrolled class.

The platform is opinionated about three things in particular. First, **fairness gates are non-negotiable**: an Early Decision binding is enforced server-side, weak recommendation letters and under-customized essays cannot be papered over, and Program capacity is the final arbiter of an admission decision. Second, **time is a first-class input**: deadlines for Early Decision, Regular Decision, rolling admission, recommendation invitations, waitlist offers, and post-admission enrollment all participate in transition preconditions, and a test-driving clock endpoint exists precisely so deadline behaviour can be exercised deterministically. Third, **yield management is a coordinated sweep, not a series of ad-hoc nudges** — a single university-scoped operation re-evaluates every waitlist entry, every open admission slot, and every expired offer in one consistent pass.

The API operates on an immediate-consistency model: every effect of a successful request — including multi-hop cascades — is visible to the very next call. Operations are exposed over HTTP/JSON under the path prefix `/applications` and its sibling collections (`/applicants`, `/universities`, `/programs`, `/essays`, `/recommendations`, `/financial-aid`, `/waitlist`, and a `/_clock` test hook).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. Both must be present and non-empty; otherwise the request is rejected with `ERR_AUTH_MISSING`. The `X-User-Role` value must be one of the five declared roles below; any other string yields `ERR_AUTH_INVALID_ROLE`. Even with a valid role, attempting an operation the role is not permitted to invoke (per §4 and the workflows in §3) yields `ERR_FORBIDDEN`.

The five roles are:

- **`Applicant`** — a prospective student acting on their own behalf. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that references an `Applicant` (an `Application`'s `applicant_id`, an `EssaySubmission` reached through its `Application`, a `RecommendationRequest` reached through its `Application`, a `FinancialAidPackage` reached through its `Application`, a `WaitlistEntry` reached through its `Application`) compare the resource's foreign-key chain to `X-User-ID`.
- **`Recommender`** — a teacher or advisor invited to submit a recommendation letter. When `X-User-Role` is `Recommender`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform does not maintain a Recommender table. A recommender may read or act on a `RecommendationRequest` only when the value of `X-User-ID` matches the `recommender_email` recorded on the request.
- **`AdmissionsOfficer`** — a university staff member who reviews applications and renders decisions. When `X-User-Role` is `AdmissionsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The officer's per-university scope is asserted through a separate referential check at the validation layer (the officer must be associated with the same `university_id` as the target `Program`), not via entity identity.
- **`FinancialAidOfficer`** — a university staff member who computes and issues aid packages. When `X-User-Role` is `FinancialAidOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`PlatformAdmin`** — system operator with full read access and clock/lifecycle controls. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

All collection endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, the maximum is 100; values outside that range fail input validation with `ERR_VALIDATION`. The default `offset` is 0; negative offsets fail input validation. List responses surface the four pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`, with `has_more` set to true when more records remain beyond the current page. List endpoints sort by `created_at` ascending unless an endpoint description in §4 explicitly states otherwise.

### 2.4. Common Resource Properties and the Versioning Contract

Every persisted resource is keyed by an `id`, which is a server-minted UUID string with no type prefix. Resources record their birth time in `created_at` and the moment of their most recent mutation in `updated_at`; both are ISO 8601 UTC timestamps with three fractional digits. A monotonic integer `version` starts at 1 on creation and increments by one on every successful mutation of that resource. Two entity tables are exceptions to this last pair: `EssaySubmission` and `YieldSweep` carry only `id` and `created_at` — neither `updated_at` nor `version` is present on those resources. An essay's body is replaced rather than versioned (edits are governed by the linked `Application`'s lifecycle), and a yield sweep is an immutable audit record.

### 2.5. Optimistic Concurrency Control

Any endpoint whose request body may include a `version` field treats it as an optimistic-concurrency guard. When `version` is supplied, the server compares it to the entity's current `version` before performing the mutation and rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409) when the two differ. When `version` is omitted, the OCC check is skipped and the mutation proceeds against the current row state. A successful mutation increments `version` by one and refreshes `updated_at`.

### 2.6. Path Resolution and Nested Resource Lookup

Path parameters are resolved left to right. The system first verifies the existence of the leftmost referenced entity, then the next, then the next; the first missing entity terminates resolution. Missing `Applicant`, `University`, `Program`, or `Application` records produce `ERR_APPLICANT_NOT_FOUND`, `ERR_UNIVERSITY_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, or `ERR_APPLICATION_NOT_FOUND` respectively. A missing `EssaySubmission`, `RecommendationRequest`, `FinancialAidPackage`, or `WaitlistEntry` produces the generic `ERR_RESOURCE_NOT_FOUND`. When a body or path further references entities that exist but are not consistent with the request (for example, an `Application` whose `program_id` belongs to a different `University` than expected), the appropriate state or referential error from §3 applies.

### 2.7. Validation Ordering

For every endpoint, validations are evaluated in a fixed priority order so that the error a client sees is the one closest to the root cause. Authentication checks run first: the headers-present check (`ERR_AUTH_MISSING`) precedes the role-valid check (`ERR_AUTH_INVALID_ROLE`), which precedes the per-endpoint permission check (`ERR_FORBIDDEN`). Existence checks for path entities run next, left to right as described in §2.6. After that comes body-shape and range validation — required fields and basic types yielding `ERR_VALIDATION`, applicant numeric ranges yielding `ERR_VALIDATION`, essay body length outside the allowed window yielding `ERR_ESSAY_LENGTH`, and the `round` and `required_recommendation_count` enumeration check on application create yielding `ERR_VALIDATION`. State preconditions follow: a state-machine endpoint invoked on an entity outside the legal `from` state yields `ERR_INVALID_STATE`, and any optimistic-concurrency mismatch yields `ERR_VERSION_CONFLICT`. After state, business safety and fairness gates run — Early Decision binding, the Early Decision window, and the officer-university scope check — followed by referential business checks against linked entities (essay customization, recommendation counts, weak-letter checks, and EFC presence), and finally capacity-and-fiscal checks (program capacity, enrollment deadline, waitlist offer expiry, round-dependent submission deadlines, and the one-Application-enrolled rule).

In particular, the submit endpoint runs its Early Decision binding check before any referential check, so an applicant who would also fail an essay-customization or recommendation-count check still sees `ERR_ED_ALREADY_BOUND` rather than `ERR_ESSAY_NOT_CUSTOMIZED` or `ERR_INSUFFICIENT_RECOMMENDATIONS` when the binding is the more fundamental obstacle. Similarly, on the decision endpoint the officer-university scope check (priority `ERR_FORBIDDEN`) runs before the program-capacity check, and on enroll the temporal `ERR_ENROLLMENT_DEADLINE_PASSED` check runs before the `ERR_ALREADY_ENROLLED_ELSEWHERE` check.

### 2.8. Cascade Semantics and Hierarchical Consistency

Several state transitions propagate to child or sibling resources. Whenever a cascade fires, every entity it touches has its `updated_at` refreshed and (where the entity carries one) its `version` incremented by one. Specifically, an Early Decision admission cascades a withdrawal to every other in-flight application of the same applicant; an enrollment cascades a withdrawal to all other live applications of that applicant and then, in a second hop, releases their waitlist entries and revokes their aid packages; a rejection or withdrawal cascades waitlist-entry releases and aid-package revocations. The system applies cascades synchronously inside the originating request — by the time the response is sent, all cascade hops are persisted.

### 2.9. Numeric Precision

Monetary fields are stored as integer cents. Scores expressed as decimals — `customization_score`, `rank_score`, and `high_school_gpa` — use two decimal places and the round-half-up rule. Where a calculation in §3 prescribes per-component rounding followed by summation, that ordering is binding: a single-expression rewrite that rounds only the final sum is not equivalent and is incorrect. Where a yield-management computation rounds to whole offers, the round-half-up rule still applies.

### 2.10. Concurrency Serialization

Five concurrency races are explicitly serialized. When two Early Decision submissions land for the same applicant at the same instant, the first to acquire the row lock on `Applicant.ed_commitment_application_id` wins; the loser receives `ERR_ED_ALREADY_BOUND` (HTTP 409). When two admissions officers race to decide the same application — say, one ADMIT against one REJECT — the first writer wins on the `status` field; the loser receives `ERR_INVALID_STATE` (HTTP 409). When two applicants race to accept the last waitlist offer for a program whose admitted-count is one short of capacity, an atomic compare-and-increment on `admitted_count` against `capacity` lets exactly one acceptance through; the loser receives `ERR_PROGRAM_AT_CAPACITY` (HTTP 409). When an applicant fires a simultaneous accept and decline on the same financial-aid package, the first writer on `status` wins and the loser receives `ERR_INVALID_STATE` (HTTP 409). Finally, a yield sweep takes an advisory university-scoped lock; an enroll call submitted while the sweep is mid-flight is rejected with `ERR_SWEEP_IN_PROGRESS` (HTTP 409) — the lock is released when the sweep completes.

## 3. Business Logic & Workflows

### 3.1. Applicant Onboarding and the Profile of Record

An applicant joins the platform by self-registering a profile, supplying `full_name` (1 to 200 characters), an `email` address conforming to RFC 5322 and unique across applicants, a `date_of_birth` formatted YYYY-MM-DD that lies at least 14 years before the current server clock, a `high_school_gpa` reported on a 4.00 scale with two decimal places, and an annual `household_income_cents` expressed as a non-negative integer count of cents. Two further fields — `fafsa_efc_cents` and `css_profile_efc_cents` — are optional on creation and default to null; both record an Expected Family Contribution measured in integer cents and become mandatory only when a financial-aid package is later issued under their respective methodologies. A ninth applicant field, `ed_commitment_application_id`, is system-managed and starts as null; it carries the `id` of the single application currently bound by Early Decision and is set, cleared, and re-set as that application moves through the lifecycle described later in this section. An applicant may later update their `high_school_gpa`, `household_income_cents`, `fafsa_efc_cents`, or `css_profile_efc_cents`, optionally supplying `version` to guard the edit; the `email`, `full_name`, and `date_of_birth` fields are immutable post-creation. Applicant numeric ranges (`high_school_gpa` between 0.00 and 4.00 inclusive, `household_income_cents` at least zero) are enforced on both create and update with `ERR_VALIDATION`; a `date_of_birth` younger than 14 years before now also fails as `ERR_VALIDATION`.

### 3.2. Universities, Programs, and Capacity

A platform administrator registers each university with a unique `name`, a `yield_target_count` of at least one (the total enrolled-class size the admissions office targets across all programs), a `regular_decision_deadline` and an `early_decision_deadline` as ISO datetimes, and a boolean `rolling_admission_enabled` flag that defaults to false. A university also exposes a running `enrolled_count` that begins at zero and is updated by every application transition into or out of `ENROLLED`, plus refreshed at the end of each yield sweep. Admissions officers (and platform administrators) then add programs under their university; each `Program` references its owning `university_id`, has a `name` unique within that university, and a `capacity` of at least one applications that may sit in `ADMITTED` or `ENROLLED` simultaneously. A program also surfaces a computed `admitted_count`, the running sum of applications in `ADMITTED` or `ENROLLED` for that program, kept incrementally consistent on every relevant state change.

### 3.3. Drafting an Application

An applicant starts a new application by supplying their own `applicant_id`, the target `program_id`, and a `round` chosen from `EARLY_DECISION`, `REGULAR_DECISION`, or `ROLLING`; an optional `required_recommendation_count` defaults to 2 and must be either 2 or 3. The request is rejected with `ERR_VALIDATION` when `round` is not one of the three named values or when `required_recommendation_count` is anything other than 2 or 3. A successful creation produces an `Application` in `DRAFT` with `essay_id` null, `submitted_at` null, `admission_decision_at` null, `enrollment_deadline` null, and `status` set to `DRAFT`.

While in `DRAFT`, the applicant must do three things before submitting: attach a sufficiently customized essay, accumulate the right number of submitted recommendation letters, and respect the ED-binding and deadline rules. The applicant withdraws an in-flight application at any time before terminal closure; the transition out of `DRAFT` or `SUBMITTED` to `WITHDRAWN` is unconditional from the state machine's perspective, but if the application is an Early Decision binding (`round` equals `EARLY_DECISION` and the applicant's `ed_commitment_application_id` equals this application's `id`), withdrawing also clears `ed_commitment_application_id` on the applicant, releasing the binding.

### 3.4. Essays and the Customization Score

An essay is attached to an application via a body payload carrying `prompt_code` (an identifier for the university-specific prompt the essay answers) and `body` (the essay text itself). The body length must lie in the inclusive range from 250 to 6500 characters; outside that window the request is rejected with `ERR_ESSAY_LENGTH`. A successful attachment creates an `EssaySubmission`, populates its `word_count` by whitespace-tokenizing `body` and counting the resulting tokens, computes its `customization_score`, and writes the new submission's `id` back onto the application's `essay_id`. The applicant may later edit `body` or `prompt_code` (optionally guarded by `version`) while the linked application remains in `DRAFT`; attempting an essay edit once the application has left `DRAFT` is rejected with `ERR_INVALID_STATE`. Essay records carry only `id` and `created_at` — they do not maintain `updated_at` or `version`; the linked application's lifecycle and the essay's recomputed `customization_score` are the only signals downstream consumers need.

The customization score is a heuristic in the closed range 0.00 to 1.00, with two decimal places and round-half-up rounding. It has two variants — one for essays whose linked application is still in `DRAFT`, the other for essays whose application has reached `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, or `WAITLISTED`. Essays attached to applications in `WITHDRAWN` or `REJECTED` are excluded from recomputation. Both variants build from four inputs: the token count of `body` (the same whitespace tokenization used for `word_count`), the number of case-insensitive whole-word occurrences of the target university's `name` in `body`, the number of case-insensitive whole-word occurrences of the target program's `name` in `body`, and a prompt-match indicator that is 1.0 when `prompt_code` begins with the target university's id-prefix code and 0.0 otherwise.

The **draft variant** computes a length factor as the minimum of 1.0 and the token count divided by 500.0, a university mention factor as the minimum of 1.0 and the university-name match count divided by 2.0, a program mention factor as the minimum of 1.0 and the program-name match count divided by 2.0, and a prompt-match factor equal to the prompt-match indicator. It combines them with weights of 0.40 on length, 0.20 on the university mention factor, 0.20 on the program mention factor, and 0.20 on the prompt match. The weighted sum is then rounded half-up to two decimal places.

The **submitted-or-later variant** uses the same four factors but with a stricter length saturation — the token count is divided by 650.0 rather than 500.0 — and a different weight distribution: 0.35 on length, 0.175 on the university mention factor, 0.175 on the program mention factor, and 0.30 on the prompt match. The weighted sum is again rounded half-up to two decimal places. Because the divisor is larger and the prompt-match weight is heavier, the same essay text typically scores lower (and sometimes higher, when the prompt match contributes) after submission than it did in draft — this is intended; the bar to clear after submission is meaningfully harder.

The customization threshold for submission is 0.30. An application whose `essay_id` is null, or whose linked essay's `customization_score` is below 0.30, cannot leave `DRAFT`; the submit attempt is rejected with `ERR_ESSAY_NOT_CUSTOMIZED`.

### 3.5. Recommendation Letters

An applicant solicits a recommendation by creating a `RecommendationRequest` under their application with a single field, `recommender_email`. The request starts in `REQUESTED`, with `invitation_expires_at` set to the moment of creation plus 21 days; `letter_body` and `letter_word_count` are null. A successful invitation establishes the recommender's identity on this request: a caller acting as `Recommender` may interact with the request only when `X-User-ID` matches `recommender_email`.

The recommender accepts (transitioning the request `REQUESTED → ACCEPTED`) or declines (transitioning `REQUESTED → DECLINED`). Acceptance is rejected with `ERR_INVALID_STATE` when the current server clock has passed `invitation_expires_at`, or when the linked application is no longer in `DRAFT` or `SUBMITTED`. The system also auto-expires stalled invitations: a request that is still in `REQUESTED` or `ACCEPTED` when the clock crosses `invitation_expires_at` transitions to `EXPIRED` (terminal). When the recommender has declined, the applicant may re-solicit a different teacher by reassigning the request — supplying a new `recommender_email` while the linked application is in `DRAFT` returns the request to `REQUESTED`, refreshes `invitation_expires_at` to the current clock plus 21 days, and writes the new `recommender_email`. The reassignment loop has no fixed maximum count; an applicant may swap recommenders until a successful letter lands.

To submit the letter itself, the recommender supplies `letter_body` while the request is in `ACCEPTED` and the linked application is in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW`. A submit without `letter_body` fails with `ERR_VALIDATION`. The transition `ACCEPTED → SUBMITTED` computes `letter_word_count` by whitespace-tokenizing `letter_body` and counting tokens. A letter whose `letter_word_count` is below 200 is recorded — the transition still completes — but the submit-letter request is rejected with `ERR_WEAK_LETTER` (HTTP 422), and the letter does not count toward the application's recommendation requirement; the recommender must resubmit a longer letter. The application's submission gate is the count of letters whose status is `SUBMITTED` and whose `letter_word_count` is at least 200; this count must equal the application's `required_recommendation_count` exactly, otherwise submission fails with `ERR_INSUFFICIENT_RECOMMENDATIONS`.

### 3.6. Submitting an Application, and the Early Decision Binding

When the applicant is ready, they submit the application — driving the transition `DRAFT → SUBMITTED` — optionally supplying `version` for the OCC guard. The system evaluates the gating conditions in the order specified by §2.7. Beyond authentication, existence, and basic validation, the gates are: the application must have an attached essay (`essay_id` not null) whose `customization_score` is at least 0.30 (otherwise `ERR_ESSAY_NOT_CUSTOMIZED`); the count of qualifying submitted recommendation letters must equal `required_recommendation_count` (otherwise `ERR_INSUFFICIENT_RECOMMENDATIONS`); for an `EARLY_DECISION` application, the applicant's `ed_commitment_application_id` must be either null or equal to this application's `id` (otherwise `ERR_ED_ALREADY_BOUND`); for an `EARLY_DECISION` application, the current server clock must not have passed the target university's `early_decision_deadline` (otherwise `ERR_ED_DEADLINE_PASSED`); for a `REGULAR_DECISION` application, the current server clock must not have passed `regular_decision_deadline` (otherwise `ERR_DEADLINE_PASSED`); for a `ROLLING` application, `rolling_admission_enabled` on the target university must be true (otherwise `ERR_DEADLINE_PASSED`).

On success, `submitted_at` is set to the current clock, `status` becomes `SUBMITTED`, and — if `round` equals `EARLY_DECISION` — the applicant's `ed_commitment_application_id` is set to this application's `id` under a row lock. Two simultaneous Early Decision submissions for the same applicant therefore serialize: the first wins and binds the applicant, and the second sees the lock and is rejected with `ERR_ED_ALREADY_BOUND`.

The applicant may pull a submitted application back to `DRAFT` while it has not yet entered review — the revision loop `SUBMITTED → DRAFT`. This transition is rejected with `ERR_INVALID_STATE` when an admissions officer has already begun review; for an Early Decision application, it is additionally rejected with `ERR_ED_DEADLINE_PASSED` when the early-decision window has closed. On a successful revision-withdraw, `submitted_at` is cleared and — if this application was the Early Decision binding — the applicant's `ed_commitment_application_id` is cleared too, freeing the applicant to submit elsewhere.

### 3.7. Admissions Review and Decisioning

An admissions officer transitions a submitted application into review via `SUBMITTED → UNDER_REVIEW`. The officer's `university_id` must equal the target program's `university_id`; the mismatch is rejected with `ERR_FORBIDDEN`. The application moves to `UNDER_REVIEW` with no other side effects.

From `UNDER_REVIEW`, the officer renders one of three decisions by supplying `decision` in the request body — `ADMIT`, `REJECT`, or `WAITLIST`. The officer-university scope check applies to all three decisions; any of them by an officer scoped to a different university is rejected with `ERR_FORBIDDEN`.

**Admit** (`UNDER_REVIEW → ADMITTED`). The admit decision is gated on program capacity: `admitted_count + 1` for the target program must not exceed `capacity` (otherwise `ERR_PROGRAM_AT_CAPACITY`). On success, `admission_decision_at` is set to the current clock, `admitted_count` is incremented by one, and `enrollment_deadline` is set to `admission_decision_at` plus 30 days for `REGULAR_DECISION` or `ROLLING` applications, or `admission_decision_at` plus 14 days for `EARLY_DECISION` applications. When the admitted application is an Early Decision admit, the system cascades: every other in-flight application of the same applicant — those in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `WAITLISTED`, or `ADMITTED` (per the binding contract, the only in-flight statuses possible at this point are `DRAFT` and `SUBMITTED`) — transitions to `WITHDRAWN`. Each cascaded withdrawal refreshes the target's `updated_at` and increments its `version`; the applicant's `ed_commitment_application_id` is retained at this step — it will only be cleared if this admitted application later moves to `ENROLLED` (the binding is closed by enrollment, not by admission).

**Waitlist** (`UNDER_REVIEW → WAITLISTED`). No precondition beyond state. On success, `admission_decision_at` is set to the current clock and a new `WaitlistEntry` is created with `application_id` set to this application's `id`, `program_id` denormalized from this application's program, `status` initialized to `ACTIVE`, and `rank_score` computed by the formula in §3.9.

**Reject** (`UNDER_REVIEW → REJECTED`). No precondition beyond state. On success, `admission_decision_at` is set to the current clock. If this application was the applicant's Early Decision binding (`round` equals `EARLY_DECISION` and `ed_commitment_application_id` equals this application's `id`), the binding is cleared, freeing the applicant to apply elsewhere. If a `FinancialAidPackage` exists for this application, it cascades to `REVOKED` regardless of whether its current status is `REQUESTED` or `OFFERED`.

Two officers racing to decide the same application — one issuing `ADMIT` and another `REJECT`, or any pair — serialize on the `status` field: exactly one decision wins, and the loser receives `ERR_INVALID_STATE` (HTTP 409) because the application has already left `UNDER_REVIEW` by the time their write lands.

### 3.8. Financial Aid

After an admit, the applicant may request a financial-aid package — a single body payload supplying `aid_method` (either `FEDERAL_METHODOLOGY` or `INSTITUTIONAL_METHODOLOGY`) and `cost_of_attendance_cents` (the sticker price for the program in non-negative integer cents). The system creates a `FinancialAidPackage` with `application_id` set to the host application, `status` initialized to `REQUESTED`, and the four computed monetary fields `grant_cents`, `loan_cents`, `work_study_cents`, and `total_award_cents` all initialized to zero. An applicant may hold at most one package per application.

A financial-aid officer then issues the offer (`REQUESTED → OFFERED`). Issuance is gated on the linked application being `ADMITTED`. It is further gated on the applicant carrying the EFC field demanded by the chosen methodology: a `FEDERAL_METHODOLOGY` package demands a non-null `fafsa_efc_cents`, and an `INSTITUTIONAL_METHODOLOGY` package demands a non-null `css_profile_efc_cents`; either gap fails with `ERR_MISSING_EFC`. On success, the four computed monetary fields are recomputed using the dual-variant award formula described next, and `total_award_cents` is stored as the sum of `grant_cents`, `loan_cents`, and `work_study_cents`.

The **federal methodology variant** treats the package as a loan-first waterfall. The applicant's need is the greater of zero and `cost_of_attendance_cents` minus `fafsa_efc_cents`. The federal loan is the lesser of that need and the federal loan cap of 5,500 US dollars (550000 cents). After the loan is allocated, the remaining need is the greater of zero and need minus loan; the federal work-study award is the lesser of that remaining need and the federal work-study cap of 2,500 US dollars (250000 cents). The grant absorbs whatever residual need remains — the greater of zero and need minus loan minus work-study. Each per-step multiplication or subtraction is in integer cents; any intermediate multiplication is rounded half-up to the cent at the named step.

The **institutional methodology variant** is grant-first. The applicant's need is the greater of zero and `cost_of_attendance_cents` minus `css_profile_efc_cents`. The grant is computed as need multiplied by the institutional grant percentage of 0.70, rounded half-up to the cent. The institutional loan is the lesser of need minus grant and the institutional loan cap of 3,500 US dollars (350000 cents). Work-study absorbs the remainder — the greater of zero and need minus grant minus loan. Again each per-step multiplication is rounded half-up to the cent.

Once the offer is `OFFERED`, the applicant either accepts it (`OFFERED → ACCEPTED`) or declines it (`OFFERED → DECLINED`); both transitions accept an optional `version` for OCC. Acceptance requires the linked application's `status` to still be `ADMITTED` and the current clock to not have passed `enrollment_deadline`; otherwise the transition is rejected with `ERR_INVALID_STATE` (note: the temporal check here uses the same comparison rule as enrollment — strictly past the deadline rejects; equality is still accepted). A simultaneous accept-and-decline race on the same package serializes on the `status` column: exactly one terminal-status transition wins, and the loser sees `ERR_INVALID_STATE`. A package may also reach `REVOKED` as a cascade — from `REQUESTED` or `OFFERED` — when its linked application transitions to `REJECTED` or `WITHDRAWN` (whether the withdrawal is applicant-initiated or system-initiated by the auto-revoke described in §3.9).

### 3.9. Waitlists, Yield Management, and the Sweep

When an application is waitlisted, the system seeds a `WaitlistEntry` in `ACTIVE` with a computed `rank_score`. The rank is on a 0.00 to 100.00 scale with two decimal places, and it follows a **pinned per-component-rounding order**: each of four components is computed and rounded half-up to two decimal places, then summed, then the sum is rounded half-up to two decimal places once more.

- The **GPA component** is the applicant's `high_school_gpa` divided by 4.00, multiplied by the GPA weight of 40.00, then rounded half-up to two decimal places. It ranges from 0 to 40.00.
- The **essay component** is the linked essay's `customization_score` multiplied by the essay weight of 30.00, then rounded half-up to two decimal places. It ranges from 0 to 30.00.
- The **tenure component** is the lesser of the number of whole days since the entry's `created_at` and the tenure-day cap of 30, multiplied by the tenure day value of 0.50, then rounded half-up to two decimal places. It ranges from 0 to 15.00. The number of whole days is the floor of the elapsed time in days.
- The **demonstrated-interest component** is the lesser of demonstrated interest and the interest program cap of 3, multiplied by the interest-per-program value of 5.00, then rounded half-up to two decimal places. It ranges from 0 to 15.00. Demonstrated interest is the count of distinct applications by this applicant to programs of **this same university** currently in `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, or `ENROLLED`; applications in `DRAFT`, `REJECTED`, or `WITHDRAWN` are excluded from the count.

The rank is the sum of the four rounded components, rounded half-up to two decimal places. Computing the entire rank as a single expression (rounding only the final sum) is explicitly the wrong order; per-component rounding before summation is binding, and at edge inputs the two orders disagree by a cent.

Yield management runs as a single university-scoped operation that an admissions officer or platform administrator triggers. A sweep takes an advisory university-scoped lock for its duration. Any concurrent application-enrollment call against the same university is rejected with `ERR_SWEEP_IN_PROGRESS`. The sweep proceeds in four stages.

First, the sweep auto-expires any admitted application whose `enrollment_deadline` has been crossed by the current clock — driving `ADMITTED → WITHDRAWN`. Each such auto-revoke decrements the program's `admitted_count` by one and cascades a `REVOKED` transition on any associated `FinancialAidPackage`.

Second, the sweep recycles any expired waitlist offer: an entry whose `status` is `OFFERED` and whose `offer_expires_at` has been crossed by the clock returns to `ACTIVE`, with `offered_at` and `offer_expires_at` cleared and `rank_score` recomputed for the next batch.

Third, the sweep sizes the batch of waitlist promotions for this run. With `target` denoting `yield_target_count`, `enrolled` denoting `enrolled_count`, and `admitted_open` denoting the sum across all this university's programs of the greater of zero and `capacity` minus `admitted_count`, the sweep computes the gap as the greater of zero and target minus enrolled. The expected melt — the number of admitted candidates the platform expects to drop out before enrollment — is the product of `admitted_open` and the melt-rate constant of 0.15, rounded half-up to the nearest whole offer. The raw batch is the greater of zero and gap minus expected melt. The actual batch size is the lesser of three values: the raw batch, the capacity cap (`admitted_open`), and the maximum batch per sweep of 50.

Fourth, the sweep promotes that batch. It sorts all `ACTIVE` waitlist entries across all programs of this university by `rank_score` descending, with ties broken first by oldest `created_at` and then by lexicographic `id`, and walks the sorted list in order. For each entry, it checks the entry's program — if that program's `admitted_count` is strictly less than its `capacity`, the entry is promoted to `OFFERED`, `offered_at` is set to the current clock, `offer_expires_at` is set to the current clock plus 7 days, and the program's `admitted_count` is provisionally incremented by one (a reservation against the offered seat). The sweep continues down the list until it has either promoted exactly `batch_size` entries or exhausted the candidate pool. The provisional increment is reverted when an offer subsequently expires unaccepted (the offer recycle in the next sweep returns the entry to `ACTIVE`); if the offer is accepted, the increment becomes permanent through the cascade described next.

The sweep records its outcome as a `YieldSweep` audit row: `university_id` of the swept university, `epoch` as a monotonically increasing per-university counter starting at one for the first sweep, `enrolled_count_at_start` as a snapshot of the university's `enrolled_count` at the moment of the sweep, `offers_extended` as the number of waitlist promotions actually performed in this run, and `ran_at` as the server-clock instant the sweep executed. `YieldSweep` records carry only `id` and `created_at` from the common-fields set — they have no `updated_at` and no `version`.

An applicant accepts a waitlist offer by transitioning the entry `OFFERED → ACCEPTED`, optionally supplying `version` for OCC. The transition is rejected with `ERR_OFFER_EXPIRED` when the current clock has passed `offer_expires_at`, and with `ERR_INVALID_STATE` when the linked application is no longer in `WAITLISTED`. On success, the linked application cascades `WAITLISTED → ADMITTED` (a system-driven hop): `admission_decision_at` is set to the current clock, `enrollment_deadline` is set to that instant plus 30 days, and the program's `admitted_count` is incremented by one (consuming the provisional reservation). If a second applicant attempts to accept the last waitlist offer for a program whose admitted-count is one short of capacity at the same instant, the program's atomic compare-and-increment against `capacity` lets exactly one acceptance through; the loser receives `ERR_PROGRAM_AT_CAPACITY`. A waitlist entry can also reach `RELEASED` (terminal) as a cascade — from `ACTIVE` or `OFFERED` — when its linked application transitions to `WITHDRAWN` or `REJECTED`.

### 3.10. Enrollment and the Closing Cascade

Enrollment closes the loop. An applicant enrolls in an admitted application — driving `ADMITTED → ENROLLED` — optionally supplying `version`. Three gates apply, evaluated in the order described in §2.7. First, the current clock must not have passed `enrollment_deadline`; strictly past the deadline rejects with `ERR_ENROLLMENT_DEADLINE_PASSED`, while equality (the moment of the deadline) is still accepted. Second, if a financial-aid package exists for this application, its `status` must be `ACCEPTED` or `DECLINED` — the applicant must have responded to the offer; otherwise the request is rejected with `ERR_INVALID_STATE`. Third, the applicant must not have another application already in `ENROLLED` (otherwise `ERR_ALREADY_ENROLLED_ELSEWHERE`).

A successful enrollment triggers a three-hop cascade. **Hop 1**: the university's `enrolled_count` is incremented by one. **Hop 2**: every other application of this applicant in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, or `WAITLISTED` transitions to `WITHDRAWN`; each such target has its `updated_at` refreshed and its `version` incremented. **Hop 3**: any `WaitlistEntry` tied to a withdrawn-as-side-effect application transitions to `RELEASED`, and any `FinancialAidPackage` tied to such an application transitions to `REVOKED`; both side-effect entities have their `updated_at` and `version` updated. If the enrolled application was an Early Decision binding, the cascade chain also clears the applicant's `ed_commitment_application_id` (the binding has now been fulfilled by enrollment).

### 3.11. Test-Driving the Clock

Because so much of the platform's behaviour pivots on deadlines — Early Decision and Regular Decision submission windows, recommendation-invitation expiry, waitlist-offer expiry, and enrollment-deadline auto-revoke — a clock-advance capability exists for test-driving. A platform administrator advances the server clock by a given number of `seconds`. The advance is applied immediately; subsequent reads of the clock — and every deadline comparison performed on transitions evaluated after the advance — observe the new clock value. The capability is administrator-only.

## 4. Endpoint Definitions

All endpoints obey the response-envelope and error-envelope contracts of §2.2. Endpoints that create a brand-new resource return HTTP 201 Created; endpoints that read, list, or mutate an existing resource return HTTP 200 OK. The table below lists each endpoint's HTTP method, path, one-line description, and the roles authorized to invoke it. Request payloads, response payloads, and side effects are not duplicated here — they are specified in the §3 workflow that owns each operation.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /applicants | Create an applicant profile. | Applicant, PlatformAdmin |
| GET | /applicants/{id} | Read an applicant profile. | Applicant, AdmissionsOfficer, FinancialAidOfficer, PlatformAdmin |
| PATCH | /applicants/{id} | Update applicant numeric fields. | Applicant, PlatformAdmin |
| POST | /universities | Register a university. | PlatformAdmin |
| GET | /universities/{id} | Read a university record. | Applicant, AdmissionsOfficer, FinancialAidOfficer, PlatformAdmin |
| POST | /universities/{id}/programs | Add a program under a university. | AdmissionsOfficer, PlatformAdmin |
| GET | /programs/{id} | Read a program record. | Applicant, AdmissionsOfficer, FinancialAidOfficer, PlatformAdmin |
| POST | /applications | Start a new application in DRAFT. | Applicant |
| GET | /applications/{id} | Read an application detail. | Applicant, AdmissionsOfficer, PlatformAdmin |
| GET | /applications | List applications with filters. | Applicant, AdmissionsOfficer, PlatformAdmin |
| POST | /applications/{id}/submit | Submit a draft application. | Applicant |
| POST | /applications/{id}/withdraw-submission | Pull a submitted application back to DRAFT. | Applicant |
| POST | /applications/{id}/withdraw | Withdraw a DRAFT or SUBMITTED application. | Applicant |
| POST | /applications/{id}/begin-review | Move a submitted application into review. | AdmissionsOfficer |
| POST | /applications/{id}/decide | Render an admission decision (ADMIT, REJECT, or WAITLIST). | AdmissionsOfficer |
| POST | /applications/{id}/enroll | Enroll in an admitted application. | Applicant |
| POST | /applications/{id}/essays | Attach an essay to an application. | Applicant |
| PATCH | /essays/{id} | Edit an essay while the application is in DRAFT. | Applicant |
| GET | /essays/{id} | Read an essay. | Applicant, AdmissionsOfficer, PlatformAdmin |
| POST | /applications/{id}/recommendations | Create a recommendation request under an application. | Applicant |
| GET | /recommendations/{id} | Read a recommendation request. | Applicant, Recommender, AdmissionsOfficer, PlatformAdmin |
| POST | /recommendations/{id}/accept | Recommender accepts an invitation. | Recommender |
| POST | /recommendations/{id}/decline | Recommender declines an invitation. | Recommender |
| POST | /recommendations/{id}/reassign | Applicant reassigns to a different recommender. | Applicant |
| POST | /recommendations/{id}/submit-letter | Recommender submits the letter. | Recommender |
| POST | /applications/{id}/financial-aid | Request a financial-aid package. | Applicant |
| GET | /financial-aid/{id} | Read an aid package. | Applicant, FinancialAidOfficer, PlatformAdmin |
| POST | /financial-aid/{id}/issue-offer | Compute and issue the aid offer. | FinancialAidOfficer |
| POST | /financial-aid/{id}/accept | Applicant accepts the aid offer. | Applicant |
| POST | /financial-aid/{id}/decline | Applicant declines the aid offer. | Applicant |
| GET | /waitlist/{id} | Read a waitlist entry. | Applicant, AdmissionsOfficer, PlatformAdmin |
| POST | /waitlist/{id}/accept-offer | Applicant accepts a waitlist offer. | Applicant |
| POST | /universities/{id}/yield-sweep | Run a yield sweep on a university. | AdmissionsOfficer, PlatformAdmin |
| GET | /universities/{id}/yield-sweeps | List yield-sweep history for a university. | AdmissionsOfficer, PlatformAdmin |
| POST | /_clock/advance | Advance the server clock by the given seconds. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_MISSING | 401 |
| ERR_AUTH_INVALID_ROLE | 403 |
| ERR_FORBIDDEN | 403 |
| ERR_APPLICANT_NOT_FOUND | 404 |
| ERR_UNIVERSITY_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_ESSAY_LENGTH | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_SWEEP_IN_PROGRESS | 409 |
| ERR_ED_ALREADY_BOUND | 409 |
| ERR_ED_DEADLINE_PASSED | 409 |
| ERR_DEADLINE_PASSED | 409 |
| ERR_ESSAY_NOT_CUSTOMIZED | 422 |
| ERR_INSUFFICIENT_RECOMMENDATIONS | 422 |
| ERR_WEAK_LETTER | 422 |
| ERR_MISSING_EFC | 422 |
| ERR_PROGRAM_AT_CAPACITY | 409 |
| ERR_ENROLLMENT_DEADLINE_PASSED | 409 |
| ERR_OFFER_EXPIRED | 409 |
| ERR_ALREADY_ENROLLED_ELSEWHERE | 409 |

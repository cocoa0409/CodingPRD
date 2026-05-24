# University Application Platform API — Product Requirements Document

## 1. Introduction

The University Application Platform is a multi-school joint application system in the spirit of a Common App. A single applicant authors one profile, invites recommenders, drafts essays per school, and submits applications under four distinct admission plans — Early Decision, Early Action, Regular Decision, and Rolling — to any number of participating institutions. Around that core flow the platform layers a recommendation-letter chain, federal and institutional financial aid, a waitlist with deterministic ranking, and a yield-management ops checkpoint that admissions offices use to backfill open seats.

The API exists to coordinate four user populations whose actions are tightly interleaved across calendar deadlines, capacity ceilings, and binding commitments. Applicants accept at most one offer; recommenders work under aggregate-capacity limits across all the applicants they serve; admissions officers must render decisions against a moving applicant version; financial aid officers must compute need against profiles that may or may not include CSS data. The product brief is to keep these populations consistent with one another through a small, explicit set of state machines, calculations, and validations rather than through ad hoc business rules embedded in each endpoint.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that every endpoint inherits — authentication, response envelope, pagination, common resource shape, precision, hierarchical consistency, and concurrency control. All endpoint paths in this document are mounted under the top-level prefix `/api`.

### 2.1. User and Role-Based Access Control

Every request — except the three explicitly public endpoints (applicant self-registration, recommender acceptance of an invitation, and recommender decline of an invitation) — must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which selects that principal's operational capacity. Five roles are recognized, spelled exactly as follows: `Applicant`, `Recommender`, `AdmissionsOfficer`, `FinancialAidOfficer`, and `PlatformAdmin`. A sixth label, `Anonymous`, is reserved for unauthenticated traffic to the three public endpoints and is never sent in `X-User-Role`.

When either header is missing on a non-public endpoint, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). When `X-User-Role` is present but is not one of the five recognized values, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401). When the role is recognized but is not permitted to invoke the requested endpoint per the per-endpoint authorization table in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). When a request is correctly authenticated but the actor does not own the targeted resource (for example, an applicant trying to submit another applicant's application), the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Role identity binds to persisted entities for two roles and is opaque for the other three. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an applicant (an `Application`, an `EssaySubmission` through its application, a `RecommendationLetter` through its application, a `FinancialAidProfile`, or an `AidOffer` through its application) compare the resource's applicant foreign key to `X-User-ID`. When `X-User-Role` is `Recommender`, `X-User-ID` is the `id` of the acting `Recommender`; ownership checks on a `RecommendationLetter` compare the letter's `recommender_id` to `X-User-ID`. When `X-User-Role` is `AdmissionsOfficer`, `FinancialAidOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may record it for audit purposes but does not compare it to any entity's `id`.

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

List endpoints accept two optional query parameters. The `limit` parameter caps the number of items returned in a single page; its default is 10, minimum is 1, and maximum is 100. The `offset` parameter skips that many items from the beginning of the result set; its default is 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. The `meta` object on a list response carries `limit`, `offset`, `total_count`, and `has_more` so clients can determine whether to request a subsequent page.

### 2.4. Common Resource Properties

Every entity in the system — `Applicant`, `Recommender`, `School`, `Application`, `EssaySubmission`, `RecommendationLetter`, `FinancialAidProfile`, `AidOffer`, and `AdmissionCycle` — exposes a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp formatted as an ISO 8601 UTC instant with three fractional digits. All nine of these entities additionally expose an `updated_at` timestamp and an integer `version` field that increments by one on every mutation of the row; the `updated_at` value is refreshed to the server clock on every such mutation. No entity in this system is restricted to creation-time fields only — every row participates in versioned mutation.

Foreign-key references appear in the request body as the unsuffixed name of the referenced entity (for example, `applicant_id`, `school_id`, `application_id`, `recommender_id`); the request omits any envelope wrapping. When a foreign-key field in a request body does not resolve to an existing row, the server rejects with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.5. Nested Resource and Path Parameter Validation

When an endpoint path contains one or more identifiers (the `{id}` segments on application, school, recommender, letter, profile, aid-offer, and admission-cycle paths), the server validates each identifier in left-to-right order. The first identifier that does not resolve to an existing row produces an immediate `ERR_RESOURCE_NOT_FOUND` (HTTP 404); the server does not continue validating downstream segments. Request-body field validation — required fields present, types correct, enum members within their declared set, numeric ranges respected — is `ERR_INVALID_REQUEST` (HTTP 422), evaluated after the path has resolved and after foreign-key fields in the body have been confirmed. Uniqueness conflicts (a duplicate `Applicant.email`, a second `Application` for the same `(applicant_id, school_id)` pair, a second `EssaySubmission` for the same `application_id`, a duplicate `(application_id, recommender_id)` `RecommendationLetter`, a second `FinancialAidProfile` for the same applicant, a second `AidOffer` for the same application, or a duplicate `School.name`) are rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409).

### 2.6. Validation Priority Ordering

When a single request would trip more than one validation, the server returns the rejection from the lowest-numbered priority in this ordering — the priority decides which error the client sees first, irrespective of the order in which the checks happen to be coded. Priority 1 is the auth-header presence check (`ERR_MISSING_AUTH_HEADERS`). Priority 2 is role recognition (`ERR_UNKNOWN_ROLE`). Priority 3 is per-endpoint role authorization (`ERR_FORBIDDEN_ROLE`). Priority 4 is left-to-right path resolution (`ERR_RESOURCE_NOT_FOUND`). Priority 5 is foreign-key resolution in the request body (`ERR_FK_NOT_FOUND`). Priority 6 is ownership of the targeted resource (`ERR_NOT_RESOURCE_OWNER`). Priority 7 is request-body shape and range validation (`ERR_INVALID_REQUEST`). Priority 8 is uniqueness (`ERR_DUPLICATE_RESOURCE`). Priority 9 is the optimistic-concurrency stale-version check (`ERR_STALE_APPLICATION_VERSION`). Priority 10 is the state-machine from-state precondition (`ERR_INVALID_STATE`). Domain-specific safety, temporal, and fiscal rules then follow in this order: Early-Decision binding (priority 11, `ERR_ED_BINDING_VIOLATION`); plan-deadline window (priority 12, `ERR_DEADLINE_PASSED`); single-enrollment (priority 13, `ERR_ALREADY_ENROLLED`); essay word count (priority 14, `ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE`); Early-Decision letter requirement (priority 15, `ERR_ED_REQUIRES_LETTER`); institutional-variant eligibility (priority 16, `ERR_INSTITUTIONAL_VARIANT_INELIGIBLE`); grant cap against demonstrated need (priority 17, `ERR_GRANT_EXCEEDS_NEED`); open-seats precondition for yield runs (priority 18, `ERR_NO_OPEN_SEATS`); yield-run cooldown (priority 19, `ERR_YIELD_COOLDOWN_ACTIVE`); recommender aggregate capacity (priority 20, `ERR_RECOMMENDER_OVER_CAPACITY`); and school deadline ordering at creation (priority 21, `ERR_SCHOOL_DEADLINE_ORDER`).

### 2.7. Hierarchical Consistency and Cascade Semantics

Several operations in this system mutate more than one row. Every cascade described below is part of the same logical transaction as the operation that triggered it: every affected row has its `updated_at` refreshed and its `version` incremented in the same call.

When an applicant accepts an offer on an admitted application, the owning school's `confirmed_enrollment_count` is incremented by one and the school's `posture` is recomputed in the same transaction (a first-order cascade). If the accepted application's plan is Early Decision, every other application owned by the same applicant whose status is `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, or `DEFERRED` auto-transitions to `WITHDRAWN` (a second-order cascade — the binding-ED commitment retires every other open candidacy). For each such cascaded withdrawal whose prior status was `WAITLISTED`, the freed school's remaining waitlisted applications have their `waitlist_rank` recomputed in the same call (a third-order cascade — the queue closes up behind the departing applicant). Revoking an enrollment back to `DECLINED_OFFER` is the compensating action for accept-offer: the school's `confirmed_enrollment_count` is decremented by one and `posture` is recomputed so the invariant *"`confirmed_enrollment_count` equals the count of applications at this school whose status is `ENROLLED`"* is restored. Revocation does NOT auto-undo any Early-Decision cascade withdrawals on sibling applications — those remain `WITHDRAWN`, because by the time the applicant revokes, the reply windows for those sibling schools have already passed.

When a recommender declines an invitation, every `RecommendationLetter` row pointing at that recommender whose status is `REQUESTED` is deleted as a first-order cascade. For each owning application, if the deletion removes the last `Recommender` row associated with that applicant and the applicant's `profile_status` was `READY`, the profile is re-evaluated and may flip back to `DRAFT` as a second-order cascade — the readiness invariant is *"all required profile fields present and at least one `Recommender` row exists for this applicant."*

When an application transitions to `WAITLISTED`, that school's full set of waitlisted applications has `waitlist_rank` recomputed; the same recomputation runs when a waitlisted application withdraws and when a waitlisted application is promoted by the yield-management run. Ranking is one-based and ordered by `waitlist_added_at` ascending, with `created_at` ascending as the deterministic tie-breaker; the `id` field is never used as a sort key.

### 2.8. Optimistic Concurrency Control

Two write endpoints are gated by an explicit optimistic-concurrency check against the parent `Application`'s `version`. Both rules are framed around stale reads, not around physical request overlap.

A `POST` to the aid-offers collection must carry `expected_application_version` as a non-optional input field, matching the target application's current `version` at the moment the server processes the create. If another writer has advanced the application's `version` since the financial aid officer last read it — the canonical case is that the officer reads `Application` `v=5` in `ADMITTED`, then between the read and the create the applicant accepts the offer (advancing `version` to `6` and the status to `ENROLLED`) — the create is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), so the officer can re-read the now-enrolled application and decide whether to proceed.

The admissions-decision endpoint at `/applications/{id}/decide` likewise requires `expected_application_version` as a non-optional input field, matching the application's current `version`. If two admissions officers both pull `Application` `v=2` in `UNDER_REVIEW`, the first writes `decision=ADMIT` (advancing `version` to `v=3` and status to `ADMITTED`), and the second sends `decision=WAITLIST` still carrying `expected_application_version=2`, the second request is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). Under the natural product semantics the late decision would legitimately supersede the first, so the system forces the officer to re-read the now-decided application before overriding.

No other endpoint takes a version field. Endpoints not listed in either of these two rules do not accept `expected_application_version` and do not perform any OCC check.

### 2.9. Precision and Rounding

Monetary fields — `cost_of_attendance_cents`, `fafsa_efc_cents`, `css_efc_cents`, `family_income_cents`, `grant_cents`, `loan_cents`, `work_study_cents`, `demonstrated_need_cents`, and `net_price_cents` — are integer cent values and require no decimal rounding; arithmetic on these fields stays in integer cents throughout. The admission probability score is an integer in the range 0 through 100 inclusive, with rounding applied per component before summation (see §3.5). The school yield rate is a real number in the range 0 through 1 inclusive, rounded half up to four decimal places when reported, and is null when no application at the school has yet reached the admitted, enrolled, or declined-offer states. All server-generated timestamps (`created_at`, `updated_at`, `submitted_at`, `decision_at`, `waitlist_added_at`, `last_yield_run_at`, and `clock_iso`) are ISO 8601 UTC instants with three fractional digits.

### 2.10. The Test Clock

Plan deadlines and Early-Decision rules are clock-sensitive, so the platform exposes the server clock as a writable, test-driven facility. Each school carries a companion `AdmissionCycle` row, created automatically when the school is created. That row's `clock_iso` field holds the current server time as visible to all timestamp comparisons; it is initialized to the school's creation time and may be advanced by a platform administrator. The administrator-only clock-advance capability takes a `to_iso8601` value in the request body and mutates the global clock that every subsequent timestamp comparison reads from. The cycle row also carries `last_yield_run_at`, `yield_run_count`, and `cooldown_ms`; these are explained in §3.7.

## 3. Business Logic & Workflows

### 3.1. Applicant Onboarding and Profile Readiness

A new applicant joins the platform through the public self-registration capability, which takes the applicant's `email`, `full_name`, `gpa`, and optionally `sat_total`. The `email` is globally unique and is normalized to lowercase before the uniqueness check; the `gpa` must be in the range from 0.0 through 4.0 inclusive; the `sat_total` is either null or an integer from 400 through 1600 inclusive. The newly created applicant starts with `profile_status` of `DRAFT`.

A `DRAFT` applicant cannot yet submit applications. The profile flips from `DRAFT` to `READY` once two conditions hold together: the applicant's `full_name` and `gpa` are both present, and at least one `Recommender` row exists for this applicant. The flip happens automatically — either when the applicant updates their own profile (mutating one of `full_name`, `gpa`, or `sat_total` through the owner-only profile-update capability) and the new state satisfies both conditions, or when the applicant invites a first recommender and the existing profile fields already satisfy the field-completeness half of the condition. The profile may also flip back from `READY` to `DRAFT` if a recommender declines their invitation and the deletion of the resulting requested letters leaves the applicant with no remaining recommender rows; see §3.2.

### 3.2. Recommenders and the Letter Chain

An applicant invites a recommender by supplying the inviter's `applicant_id`, the recommender's contact `email`, the recommender's `full_name`, and a `relationship` value drawn from the set `TEACHER`, `COUNSELOR`, or `OTHER`. The pair `(applicant_id, email)` is unique — an applicant cannot invite the same address twice. The new recommender starts with `invite_status` of `INVITED`.

The recommender responds to the invitation through one of two public capabilities, available without auth headers because the recipient has only the link sent by email. Accepting transitions `invite_status` from `INVITED` to `ACCEPTED`. Declining transitions `invite_status` from `INVITED` to `DECLINED`; the decline is terminal and triggers the cascade described in §2.7 — every `REQUESTED` letter pointing at this recommender is deleted, and any owning applicant whose `profile_status` was `READY` is re-evaluated.

After acceptance, the applicant requests a letter for a specific application by supplying the `application_id` and the `recommender_id`. The pair `(application_id, recommender_id)` is unique. The new letter starts with `status` of `REQUESTED`, with `body` null and `submitted_at` null. The recommender then begins drafting, transitioning the letter from `REQUESTED` to `IN_PROGRESS`; this transition requires that the recommender's `invite_status` be `ACCEPTED` and that the owning application's `status` still be `DRAFT` (a letter cannot be drafted once the application is locked). The transition is also subject to the recommender aggregate-capacity rule: the count of `RecommendationLetter` rows pointing at this recommender whose `status` is `IN_PROGRESS` must remain at or below five after the transition. Five active drafts is permitted; a sixth `REQUESTED → IN_PROGRESS` transition is rejected with `ERR_RECOMMENDER_OVER_CAPACITY`.

Submitting the letter transitions it from `IN_PROGRESS` to `SUBMITTED`. The request must carry the `body`, and the transition requires that the supplied `body` be non-null with length of at least 200 characters; it also requires that the owning application still be in `DRAFT`. On success the server sets `submitted_at` to the server clock. The applicant may also waive a letter, transitioning it from `REQUESTED` or `IN_PROGRESS` to `WAIVED`; waiving is disallowed when the application's `plan` is `EARLY_DECISION`, because Early Decision requires at least one `SUBMITTED` letter (see §3.4).

### 3.3. Schools and the Admission Cycle

A platform administrator creates a school by supplying its `name`, its `target_class_size` (at least one seat), the three plan deadlines `ed_deadline_iso`, `ea_deadline_iso`, and `rd_deadline_iso` as ISO 8601 UTC instants, an optional `rolling_open` flag (defaulting to false), an optional `requires_css_profile` flag (defaulting to false), and an optional `cooldown_ms` value for the yield-run cooldown (defaulting to 86,400,000 milliseconds — that is, twenty-four hours). The three deadlines must satisfy a strict ordering: the Early-Decision deadline is earlier than the Early-Action deadline, which is earlier than the Regular-Decision deadline. The intervals are half-open — each plan's submission window ends exclusively at its deadline — and a school whose Early-Decision deadline equals its Early-Action deadline at the same instant (a zero-width overlap) is rejected with `ERR_SCHOOL_DEADLINE_ORDER`. Creating the school also creates a companion `AdmissionCycle` row whose `school_id` equals the new school's `id`, whose `clock_iso` is initialized to the creation time, whose `last_yield_run_at` is null, whose `yield_run_count` is zero, and whose `cooldown_ms` matches the school's value.

The school exposes two derived fields. The `confirmed_enrollment_count` is the integer count of applications at this school whose status is `ENROLLED`; it starts at zero, is recomputed whenever an application transitions into or out of `ENROLLED` (accept-offer, revoke-enrollment, or a waitlist promotion that ultimately leads to enrollment), and is the load-bearing input to the school's `posture`. The `posture` is `OPEN` whenever `confirmed_enrollment_count` is strictly less than `target_class_size`, `AT_TARGET` when the two are equal, and `OVER_TARGET` when `confirmed_enrollment_count` is strictly greater than `target_class_size` — a possible condition because the system permits enrollment beyond target if cascades and revocations interleave unfavorably. The `posture` gates whether waitlist promotions may proceed: only an `OPEN` posture admits further promotions through the yield run (see §3.7).

### 3.4. The Application Lifecycle

An applicant creates an application by supplying the `applicant_id`, the `school_id`, and the chosen `plan`, drawn from the set `EARLY_DECISION`, `EARLY_ACTION`, `REGULAR`, or `ROLLING`. The pair `(applicant_id, school_id)` is unique — an applicant cannot create two applications to the same school. A `plan` of `ROLLING` is permitted only when the target school's `rolling_open` is true. The application is created with `status` of `DRAFT`, `submitted_at` null, `decision_at` null, `waitlist_rank` null, and `waitlist_added_at` null.

The Early-Decision binding rule applies at creation and again at submission: an applicant may have at most one application with `plan` equal to `EARLY_DECISION` in any non-terminal status. A second Early-Decision application is rejected with `ERR_ED_BINDING_VIOLATION`. The non-terminal statuses for the purpose of this rule are `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, and `DEFERRED`; the terminal statuses are `WITHDRAWN`, `DENIED`, and `DECLINED_OFFER`. The terminal set is intentionally chosen so an applicant whose Early-Decision application has been denied or withdrawn may immediately file a fresh Early-Decision elsewhere.

A `DRAFT` application is submitted through the applicant-only submit capability. The transition from `DRAFT` to `SUBMITTED` carries several preconditions. The applicant's `profile_status` must be `READY`. Exactly one `EssaySubmission` must exist for this application, with `word_count` in the range from 1 through 650 words inclusive (see §3.5). All `RecommendationLetter` rows for this application must be in `SUBMITTED` status — though zero letters is permitted, except when the plan is `EARLY_DECISION`, in which case at least one `SUBMITTED` letter is required and the missing-letter case rejects with `ERR_ED_REQUIRES_LETTER`. The deadline window must hold: for an Early-Decision submission the server clock must be at or before `ed_deadline_iso` and no other application by this applicant may have `plan` equal to `EARLY_DECISION` (the binding single-ED rule, re-checked here); for an Early-Action submission the server clock must be at or before `ea_deadline_iso`; for a Regular-Decision submission the server clock must be at or before `rd_deadline_iso`; for a Rolling submission the target school's `rolling_open` must be true. A submission that violates any deadline window is rejected with `ERR_DEADLINE_PASSED`. On successful submission the server sets `submitted_at` to the server clock and flips the application's `EssaySubmission` to `locked = true`, making the essay read-only.

A `SUBMITTED` application moves to `UNDER_REVIEW` when an admissions officer takes it up through the start-review capability; the precondition is simply that the application's `status` be `SUBMITTED`. The same capability is also used to re-open a `DEFERRED` application: a `DEFERRED → UNDER_REVIEW` transition requires that the application's `status` be `DEFERRED` and that the server clock be strictly later than the school's `ed_deadline_iso`, ensuring that deferred applications only re-enter the pool once the regular-pool window has begun.

An `UNDER_REVIEW` application receives a decision through the admissions decide capability, whose request body carries `decision` (one of `ADMIT`, `WAITLIST`, `DENY`, or `DEFER`) and the OCC field `expected_application_version`. The four outcomes correspond to four transitions out of `UNDER_REVIEW`. `ADMIT` transitions to `ADMITTED` and sets `decision_at` to the server clock. `WAITLIST` transitions to `WAITLISTED`, sets `decision_at` to the server clock, sets `waitlist_added_at` to the server clock, and recomputes `waitlist_rank` for every `WAITLISTED` application at this school (ordered by `waitlist_added_at` ascending with `created_at` ascending as tie-break). `DENY` transitions to `DENIED` and sets `decision_at` to the server clock. `DEFER` is permitted only when the application's `plan` is `EARLY_DECISION` or `EARLY_ACTION` — defer is meaningful only for early plans rolled into the regular pool — and on success the application's `status` becomes `DEFERRED`, `decision_at` is set to the server clock, and the application's `plan` is set to `REGULAR` (rolling it into the regular pool for later review). Each of these four decision transitions also enforces the optimistic-concurrency check from §2.8. Sending any decision against a from-state other than `UNDER_REVIEW` is rejected with `ERR_INVALID_STATE`.

An applicant accepts an admission offer through the applicant-only accept-offer capability, transitioning from `ADMITTED` to `ENROLLED`. The preconditions are that the application's `status` be `ADMITTED`, the applicant owns the application, and no other application by this applicant is in `ENROLLED` status — the single-enrollment rule, rejected with `ERR_ALREADY_ENROLLED` on violation. The cascade on success is described in §2.7: the school's `confirmed_enrollment_count` is incremented and `posture` is recomputed; for an Early-Decision plan, every other non-terminal application by this applicant auto-transitions to `WITHDRAWN`, and each waitlisted cascade-withdrawal triggers a `waitlist_rank` recompute on its school.

An applicant may instead decline an admission offer through the applicant-only decline-offer capability, transitioning from `ADMITTED` to `DECLINED_OFFER`; the preconditions are that the application's `status` be `ADMITTED` and that the applicant owns the application. After enrollment, an applicant may revoke their acceptance through the applicant-only revoke-enrollment capability, transitioning from `ENROLLED` to `DECLINED_OFFER`; the preconditions are that the application's `status` be `ENROLLED` and that the applicant owns the application. The compensating side effect — decrement of `confirmed_enrollment_count` and recompute of `posture` — is described in §2.7.

An applicant withdraws from a school through the applicant-only withdraw capability, transitioning to `WITHDRAWN`. The withdraw capability accepts the application in any of the non-terminal statuses `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, or `DEFERRED`. When the from-state is `WAITLISTED`, the withdrawal also recomputes `waitlist_rank` for the remaining waitlisted applications at this school; from any other from-state the rank-recompute step does not run, because there is no rank to renumber.

The application read endpoint surfaces `admission_probability_score` on every response. The score is parameterized by an optional `score_variant` query parameter, which selects between two variants: `PROVISIONAL` and `FINAL`. When `score_variant` is not supplied, the default is `PROVISIONAL` while the application's `status` is `DRAFT` or `SUBMITTED`, and `FINAL` once the status is `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, `DENIED`, `DEFERRED`, `ENROLLED`, `WITHDRAWN`, or `DECLINED_OFFER`. The two variants differ in which letters count toward the letters factor (see §3.5).

### 3.5. Essays and the Admission Probability Score

An applicant creates an essay for a `DRAFT` application by supplying the `application_id`, the chosen `prompt_code`, and the essay `body`. Exactly one essay is permitted per application — the `application_id` is unique among `EssaySubmission` rows. The server computes `word_count` as the number of whitespace-separated tokens in `body`, and `word_count` must fall in the range from 1 through 650 words inclusive; a `word_count` outside that range is rejected with `ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE`. The new essay is created with `locked` false. The essay may be edited through the applicant-only essay-update capability — supplying either `prompt_code` or `body` — but only while `locked` is false; once the owning application transitions to `SUBMITTED` or beyond, the essay is locked and the update is rejected.

The admission probability score is an integer in the range 0 through 100 and is computed from four components combined under one critical rounding rule. The rule, which the implementer must honor verbatim, is that rounding is applied at the per-component step before summation, never at the end. The components are:

- The GPA component takes the applicant's `gpa`, multiplies by ten, rounds the resulting real value half up to the nearest integer, and then caps the result at a maximum of forty. The cap and the rounding both belong to the per-component step.
- The SAT component is zero when the applicant's `sat_total` is null. Otherwise it is computed by subtracting four hundred from `sat_total`, dividing by forty, applying the floor function (rounding down toward negative infinity to a whole number), and then capping the result at a maximum of thirty.
- The plan bonus is a fixed integer that depends on the application's `plan`: fifteen for `EARLY_DECISION`, eight for `EARLY_ACTION`, five for `ROLLING`, and zero for `REGULAR`.
- The letters factor counts qualifying `RecommendationLetter` rows for this application, multiplies that count by five, and caps the result at a maximum of fifteen — that is, the letters factor saturates after the third qualifying letter, so additional letters beyond three contribute nothing.

The total score is the integer sum of the four components, with no additional rounding applied to the sum. Because the per-component rounding rule pins the order, a GPA of 3.85 (whose pre-cap real value is 38.5) rounds to 39 at the GPA-component step and contributes 39 to the sum; an implementation that defers rounding to a single final round would produce a different integer here. The score is always in the range zero through one hundred — the per-component caps of forty plus thirty plus fifteen plus fifteen sum to one hundred.

The two variants of the score differ only in which letter statuses qualify for the letters factor. The `PROVISIONAL` variant counts letters whose `status` is `REQUESTED`, `IN_PROGRESS`, or `SUBMITTED` — the optimistic projection used while admissions has not yet begun reviewing, on the theory that pending letters will likely arrive. The `FINAL` variant counts only letters whose `status` is `SUBMITTED` — the conservative projection used once admissions has begun review. Whenever an application has any `REQUESTED` or `IN_PROGRESS` letters on it, the `PROVISIONAL` variant produces a higher or equal score to `FINAL`; when every letter is already `SUBMITTED`, the two variants agree exactly.

### 3.6. Financial Aid Profiles and Offers

An applicant creates a financial aid profile by supplying the `applicant_id`, the FAFSA-derived `fafsa_efc_cents` (a non-negative integer in cents), an optional `css_efc_cents` (null or a non-negative integer in cents, populated only when the applicant has filed a CSS Profile), and the household's `family_income_cents` (a non-negative integer in cents). The profile is unique per applicant — only one `FinancialAidProfile` may exist per `Applicant`. The newly created profile starts with `status` of `DRAFT`. The applicant submits the profile through the applicant-only profile-submit capability, transitioning `status` from `DRAFT` to `SUBMITTED`; the transition requires that the profile's current `status` be `DRAFT` and that both `fafsa_efc_cents` and `family_income_cents` be non-null.

A financial aid officer issues an aid offer against an `ADMITTED` application by supplying the `application_id`, the published `cost_of_attendance_cents` for the school, the offer `variant`, the `grant_cents` (institutional grant), the `loan_cents` (federal loan), the `work_study_cents` (work-study award), and the OCC field `expected_application_version` (see §2.8). The `application_id` is unique among `AidOffer` rows — only one aid offer may exist per application. All four monetary input fields are non-negative integers in cents; the `grant_cents` is additionally capped at the computed `demonstrated_need_cents` (see below), so a request whose grant exceeds demonstrated need is rejected with `ERR_GRANT_EXCEEDS_NEED`. The `variant` is one of `FEDERAL` or `INSTITUTIONAL`; `INSTITUTIONAL` is permitted only when the target school's `requires_css_profile` is true AND the applicant's `FinancialAidProfile.css_efc_cents` is not null, and a violation of either condition is rejected with `ERR_INSTITUTIONAL_VARIANT_INELIGIBLE`.

On every create and on every update of the offer through the officer-only offer-update capability (which adjusts `grant_cents`, `loan_cents`, and `work_study_cents`), the server computes two derived fields. The `demonstrated_need_cents` is the maximum of zero and the difference between `cost_of_attendance_cents` and the applicable EFC; the applicable EFC is `fafsa_efc_cents` from the linked `FinancialAidProfile` when `variant` is `FEDERAL`, and `css_efc_cents` from the linked profile when `variant` is `INSTITUTIONAL`. The linked profile is resolved from the offer's `application_id` to the application's owning applicant and must have its `status` equal to `SUBMITTED` — `DRAFT` profiles are excluded from the demonstrated-need computation. The `net_price_cents` is the maximum of zero and the value of `cost_of_attendance_cents` minus `grant_cents` minus `loan_cents` minus `work_study_cents`. Both calculations are entirely in integer cents and require no rounding.

A practical consequence of the variant rule is that the same applicant typically receives a lower `demonstrated_need_cents` under `INSTITUTIONAL` than under `FEDERAL`, because the CSS Profile counts more household assets and so produces a higher EFC than the FAFSA — a smaller need number means a smaller maximum allowable `grant_cents`.

### 3.7. Waitlists and the Yield-Management Run

When admissions waitlists an application, the platform stamps `waitlist_added_at` with the server clock and recomputes `waitlist_rank` across the school's full set of waitlisted applications (see §3.4 and §2.7). The rank is one-based and the ordering is by `waitlist_added_at` ascending with `created_at` ascending as a deterministic tie-breaker; the `id` field is never used as a sort key. The same recompute runs when a waitlisted application withdraws, and again when the yield-management run promotes the top-ranked application.

The yield-management run is an admissions-officer or platform-admin capability scoped to an `AdmissionCycle`. Each invocation evaluates two precondition rules before allocating any seats. First, the open-seats rule: the school's `posture` must be `OPEN` (that is, `confirmed_enrollment_count` is strictly less than `target_class_size`) AND there must be at least one application at this school in `WAITLISTED` status; a run against an `AT_TARGET` or `OVER_TARGET` school, or against a school with no waitlist, is rejected with `ERR_NO_OPEN_SEATS`. Second, the cooldown rule: the server clock must satisfy server-clock at or after the value of `last_yield_run_at` plus 86,400,000 milliseconds (the rule's lower boundary is inclusive — a run at exactly twenty-four hours after the prior run is permitted). If `last_yield_run_at` is null (no prior run), the cooldown is vacuously satisfied. A run that violates the cooldown is rejected with `ERR_YIELD_COOLDOWN_ACTIVE`.

When both preconditions hold, the run computes the number of open seats as the maximum of zero and the difference between `target_class_size` and `confirmed_enrollment_count`, takes the school's waitlisted applications ordered by `waitlist_rank` ascending, and promotes the top applications until the open-seats counter is exhausted. The number of promotions is the smaller of the two values: the open-seats count and the length of the eligible waitlist. Each promotion transitions an application from `WAITLISTED` to `ADMITTED`, sets `decision_at` to the server clock, and nulls out `waitlist_rank`. Crucially, a promotion does not itself fill a seat — the school's `confirmed_enrollment_count` only changes when the promoted applicant subsequently accepts. So a single run may promote up to the open-seats count of applicants — no more — pouring waitlisted applications into open seats and stopping when the pour is dry. The run also recomputes `waitlist_rank` for any applications that remain on the waitlist after the promotions, increments the `AdmissionCycle`'s `yield_run_count` by one, and sets `last_yield_run_at` to the server clock.

The school's yield rate is exposed through a separate yield-report read on the school, available to admissions officers and platform administrators. The rate is the ratio of enrolled applications to admitted applications at this school, where admitted applications are those whose `status` is in the set `ADMITTED`, `ENROLLED`, or `DECLINED_OFFER`, and enrolled applications are those whose `status` is `ENROLLED`. Waitlisted applications are excluded from both numerator and denominator until they promote out of `WAITLISTED`; withdrawn applications are excluded altogether. When the admitted count is zero, the yield rate is reported as null; otherwise the rate is the enrolled count divided by the admitted count, rounded half up to four decimal places. The rate is recomputed eagerly whenever an application transitions into `ENROLLED`.

### 3.8. Listing and Reading

Applicants list and read their own applications; admissions officers may additionally filter the application list by `school_id`, by `status`, or by `plan` (any combination is permitted) and may page the result through `limit` and `offset`. School lists are public to all authenticated roles and accept `limit` and `offset` for pagination. The application read endpoint accepts the optional `score_variant` query parameter described in §3.4. The school yield-report read, the financial aid profile read, the aid offer read, the recommender read, the applicant read, and the admission-cycle read each return the single targeted row with no additional query parameters.

## 4. Endpoint Definitions

All paths below are relative to the `/api` prefix described in §2. Operations that create a stand-alone resource return `201 Created`; operations that modify or read a resource return `200 OK`. Every endpoint inherits the validation-priority ordering described in §2.6.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/applicants/register` | Public registration of a new Applicant | Anonymous |
| GET    | `/applicants/{id}` | Fetch an Applicant profile | Applicant, PlatformAdmin |
| PATCH  | `/applicants/{id}` | Update mutable Applicant fields (owner only) | Applicant |
| POST   | `/recommenders` | Applicant invites a Recommender | Applicant |
| GET    | `/recommenders/{id}` | Fetch a Recommender record | Applicant, Recommender, PlatformAdmin |
| POST   | `/recommenders/{id}/accept` | Recommender accepts the invitation (public link) | Anonymous |
| POST   | `/recommenders/{id}/decline` | Recommender declines the invitation (public link) | Anonymous |
| POST   | `/schools` | Create a School and its companion AdmissionCycle | PlatformAdmin |
| GET    | `/schools/{id}` | Fetch a School record | Applicant, AdmissionsOfficer, FinancialAidOfficer, PlatformAdmin |
| GET    | `/schools` | List Schools with pagination | Applicant, AdmissionsOfficer, FinancialAidOfficer, PlatformAdmin |
| GET    | `/schools/{id}/yield-report` | Computed yield rate, confirmed enrollment count, and waitlist depth | AdmissionsOfficer, PlatformAdmin |
| POST   | `/applications` | Create a draft Application | Applicant |
| GET    | `/applications/{id}` | Fetch an Application (includes admission_probability_score per score_variant) | Applicant, AdmissionsOfficer, PlatformAdmin |
| GET    | `/applications` | List Applications | Applicant, AdmissionsOfficer, PlatformAdmin |
| POST   | `/applications/{id}/submit` | Applicant submits a DRAFT application | Applicant |
| POST   | `/applications/{id}/withdraw` | Applicant withdraws from any non-terminal state | Applicant |
| POST   | `/applications/{id}/start-review` | Admissions begins reviewing a SUBMITTED or DEFERRED application | AdmissionsOfficer |
| POST   | `/applications/{id}/decide` | Admissions renders a decision (ADMIT, WAITLIST, DENY, or DEFER) | AdmissionsOfficer |
| POST   | `/applications/{id}/accept-offer` | Applicant accepts an admission offer | Applicant |
| POST   | `/applications/{id}/decline-offer` | Applicant declines an admission offer | Applicant |
| POST   | `/applications/{id}/revoke-enrollment` | Applicant revokes a prior acceptance | Applicant |
| POST   | `/essay-submissions` | Create the essay for a DRAFT Application | Applicant |
| PATCH  | `/essay-submissions/{id}` | Edit essay text or prompt while unlocked | Applicant |
| POST   | `/recommendation-letters` | Applicant requests a letter from a Recommender | Applicant |
| POST   | `/recommendation-letters/{id}/start` | Recommender begins drafting a letter | Recommender |
| POST   | `/recommendation-letters/{id}/submit` | Recommender submits the letter | Recommender |
| POST   | `/recommendation-letters/{id}/waive` | Applicant waives the letter requirement | Applicant |
| POST   | `/financial-aid-profiles` | Applicant creates a financial aid profile | Applicant |
| POST   | `/financial-aid-profiles/{id}/submit` | Submit the financial aid profile | Applicant |
| GET    | `/financial-aid-profiles/{id}` | Read a financial aid profile | Applicant, FinancialAidOfficer, PlatformAdmin |
| POST   | `/aid-offers` | Issue an AidOffer for an ADMITTED Application | FinancialAidOfficer |
| PATCH  | `/aid-offers/{id}` | Adjust grant, loan, or work-study; recomputes net price | FinancialAidOfficer |
| GET    | `/aid-offers/{id}` | Read an AidOffer | Applicant, FinancialAidOfficer, PlatformAdmin |
| POST   | `/admission-cycles/{id}/run-yield` | Run the yield-management ops checkpoint | AdmissionsOfficer, PlatformAdmin |
| GET    | `/admission-cycles/{id}` | Read admission cycle metadata | AdmissionsOfficer, PlatformAdmin |
| POST   | `/_clock/advance` | Test-driving capability: advance the global server clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ED_BINDING_VIOLATION` | 409 |
| `ERR_ED_REQUIRES_LETTER` | 409 |
| `ERR_DEADLINE_PASSED` | 409 |
| `ERR_ALREADY_ENROLLED` | 409 |
| `ERR_INSTITUTIONAL_VARIANT_INELIGIBLE` | 409 |
| `ERR_GRANT_EXCEEDS_NEED` | 409 |
| `ERR_NO_OPEN_SEATS` | 409 |
| `ERR_YIELD_COOLDOWN_ACTIVE` | 409 |
| `ERR_RECOMMENDER_OVER_CAPACITY` | 409 |
| `ERR_SCHOOL_DEADLINE_ORDER` | 422 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |

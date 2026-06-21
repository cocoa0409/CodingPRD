# University Application API — Product Requirements Document

## 1. Introduction

The University Application API is a Common-App-style platform that lets a single applicant assemble one profile, attach essays and recommendation letters to it, and submit parallel applications to many schools under several admission regimes — Early Decision, Early Action, Regular, and Rolling. Each side of the marketplace operates with conflicting incentives that the platform must reconcile: applicants want maximum optionality and the latest possible commitment, admissions offices want predictable yield against a fixed class size, financial-aid offices want every package to balance against tuition, and recommenders want to submit once and have the letter count toward every relevant school in a single sweep. The platform's job is to make those incentives interlock without anyone being able to game the rules.

Because the same applicant data feeds many parallel decisions, the platform is designed around **immediate consistency with optimistic concurrency**. An applicant's GPA, SAT score, and residency become immutable the moment they submit their first application, because every downstream calculation — composite score, expected family contribution, net cost, yield posture — must be reproducible from a stable snapshot. Aid packages, recommendation letters, and yield-management counters propagate through cascades that fire synchronously; readers never see intermediate states. The system also exposes a test-driving clock so the deterministic deadlines around Early Decision, Regular, and Rolling tracks can be exercised end-to-end without waiting for real wall time.

This document specifies the API contract — auth, response envelope, pagination, the cross-cutting consistency model — followed by the per-role workflows (§3), the endpoint summary (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the two explicit anonymous endpoints (applicant self-registration and the test-driving clock setter — see §2.1.1 below) must carry two HTTP headers: `X-User-ID` and `X-User-Role`. `X-User-Role` must be exactly one of `Applicant`, `AdmissionsOfficer`, `FinancialAidOfficer`, `PlatformAdmin`, or — for the two anonymous endpoints — `Anonymous`. Any missing header, malformed header, or role string outside that enumeration is rejected with `ERR_UNAUTHENTICATED`. Once authentication succeeds, the server checks whether the role is permitted for the requested operation per §1.7 of this contract (reflected in the Authorized Role column of §4); a role that authenticates but is not on the endpoint's allow-list is rejected with `ERR_UNAUTHORIZED`.

The four authenticated roles bind to `X-User-ID` in two different ways. When `X-User-Role` is `Applicant`, the value of `X-User-ID` is the `id` of the acting `Applicant` record; every ownership check on a resource that references an applicant — an `Application` via its `applicant_id`, an `Essay` via the `application_id` chain back to its applicant, a `RecommendationRequest` via its `applicant_id`, a `FinancialAidProfile` via its `applicant_id`, an `AidPackage` via the `application_id` chain — compares the relevant foreign-key field to `X-User-ID` and rejects a mismatch with `ERR_FORBIDDEN_OWNER_MISMATCH`. The other three roles (`AdmissionsOfficer`, `FinancialAidOfficer`, `PlatformAdmin`) carry `identity: opaque`: `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`. School-affiliation checks for officer roles (e.g., an `AdmissionsOfficer` may only act on an `Application` whose `school_id` is the school they are assigned to) are enforced through out-of-band assignment, not through `X-User-ID`.

#### 2.1.1. Anonymous Endpoints

Two endpoints are explicitly anonymous and do not require the auth headers: applicant self-registration (the `POST` that creates an `Applicant`) and the test-driving clock setter (the `POST` against `/_clock/set_current_utc`). The clock setter is gated to `PlatformAdmin` in normal operation but, as a test-driving capability, the implementation skips the auth-header requirement for it.

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

Every list endpoint accepts two optional query parameters: `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; values outside that range are rejected as malformed input. `offset` defaults to 0 and has no upper bound beyond the underlying result-set size. Results are always ordered by `created_at` ascending unless an endpoint's narrative in §3 specifies a different ordering (the waitlist listing, which orders by `rank` ascending, is the only exception). The response `meta` block for list endpoints carries `limit`, `offset`, `total_count`, and `has_more` so the client can drive pagination without state.

### 2.4. Common Resource Properties

Every persisted entity except the singleton system clock carries four server-managed fields. The `id` is a server-minted UUID with no type prefix; clients never construct ids. `created_at` is set when the row is inserted and never changes; `updated_at` is refreshed on every mutation. Both timestamps are ISO 8601 UTC with three fractional digits. `version` is an integer that starts at 1 at creation and increments by exactly one on every server-acknowledged mutation of the row (including cascaded mutations triggered by another entity's state transition). The `SystemClock` singleton is the sole exception: it carries `id` and `created_at` but does not expose `updated_at` or `version` — its only mutable field is `current_utc`, which the clock setter overwrites without participating in optimistic-concurrency bookkeeping.

The applicant-facing entities (`Applicant`, `School`, `Application`, `Essay`, `RecommendationRequest`, `FinancialAidProfile`, `AidPackage`, `WaitlistEntry`) all carry the full four-field set. Status codes follow a uniform rule: a new resource creation returns HTTP 201, every successful modification (including the workflow-action endpoints that drive state machines) returns HTTP 200.

### 2.5. Nested Resource Resolution

URL paths are resolved left to right. Whenever a path contains an `{id}` segment, the server first verifies that the referenced row exists; if not, the request is rejected with `ERR_NOT_FOUND` before any body validation runs. Body fields that are foreign keys (for example, the `applicant_id` and `school_id` carried in an application create, or the `application_id` carried in an essay create) are then validated left-to-right in declaration order. Existence checks always precede semantic checks, so a request that violates both existence and a state-machine precondition surfaces the existence failure first.

### 2.6. Validation Priority and Ordering

When a single request would fail multiple checks, the server reports the failure of the first applicable check using this fixed priority ordering. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first; then role authorization (`ERR_UNAUTHORIZED`); then path-parameter and body foreign-key existence (`ERR_NOT_FOUND`); then applicant ownership for applicant-scoped endpoints (`ERR_FORBIDDEN_OWNER_MISMATCH`); then state-machine eligibility (`ERR_INVALID_STATE`); then the application-submit-only deadline check (`ERR_DEADLINE_PASSED`); then the Early-Decision exclusivity check at submit (`ERR_ED_EXCLUSIVITY_VIOLATED`); then the application-submit completeness bundle (`ERR_APPLICATION_INCOMPLETE`); then the Early-Decision binding check at decline (`ERR_ED_BINDING_VIOLATION`); then the aggregate-enrollment check at enroll (`ERR_ENROLLMENT_ALREADY_DECLARED`); then the aid-package tuition cap (`ERR_AID_EXCEEDS_TUITION`); then the waitlist yield-target gate (`ERR_YIELD_TARGET_REACHED`); then the essay word-count check (`ERR_WORD_COUNT_MISMATCH`); then the FAFSA-asset prohibition (`ERR_FAFSA_DISALLOWS_ASSETS`); then the locked-profile field-immutability check (`ERR_PROFILE_LOCKED`); then optimistic-concurrency stale-version detection (`ERR_STALE_VERSION`); and finally generic input validation (`ERR_INVALID_REQUEST`) for missing required fields, type mismatches, and out-of-bounds numerics. The ordering matters because several endpoints can simultaneously violate two or more rules, and the test suite asserts the specific code returned — for example, on an attempt to admit a non-`UNDER_REVIEW` application with a stale version, the state failure is reported, not the OCC failure.

### 2.7. Optimistic Concurrency Control

A single write endpoint participates in optimistic concurrency: the admission decision that drives an `Application` from `UNDER_REVIEW` to `ADMITTED`. That request must include a non-optional input field named `expected_application_version` whose value is the `version` integer the writer last observed on the target `Application`. If the value does not equal the row's current `version` at the moment the server processes the request, the operation is rejected with `ERR_STALE_VERSION` and HTTP status 412. The intended scenario is straightforward: another admissions officer (or any cascading side-effect) may have transitioned the same `Application` from `UNDER_REVIEW` to `WAITLISTED` in the interim — both decisions can legitimately leave `UNDER_REVIEW` per §1.2, so the version mismatch signals that the writer is acting on a stale view. The rejection is framed in stale-version terms, not as a parallel-arrival race. No other endpoint takes a `version` input field.

### 2.8. Hierarchical Consistency, Cascades, and `version` Semantics

Several workflows mutate more than one row in a single request. The platform's contract is that all cascaded mutations are committed synchronously and atomically with the primary mutation, and every cascaded row's `updated_at` is refreshed and its `version` is incremented exactly once. The four cascade families are: (a) the applicant's profile locking on first application submit, which flips `profile_status` from `DRAFT` to `LOCKED` and bumps the applicant's `version`; (b) aid-package revocation when its linked application transitions to `DENIED` or `DECLINED` from `ADMITTED`, driving any `FINALIZED` `AidPackage` to `REVOKED`; (c) waitlist-entry release when a waitlisted application is declined, driving the corresponding `PENDING` `WaitlistEntry` to `RELEASED`; and (d) the multi-school decline sweep when an applicant enrolls, which cascades every other `ADMITTED` or `WAITLISTED` application of that applicant to `DECLINED` — and each of those cascaded decline transitions in turn fires its own side effects (aid-package revocation, waitlist-entry release, the linked school's `declined_count` increment, and `admitted_count` decrement only when cascading from `ADMITTED`). School-level counters (`admitted_count`, `enrolled_count`, `declined_count`, `denied_count`) and the derived `yield_posture` are refreshed in the same transaction.

### 2.9. Cents-Based Money and Precision Rules

All monetary fields are integers denominated in USD cents — there are no fractional cents, no floating-point money on the wire, and no rounding step inside `net_cost_cents` (which is integer subtraction). The Expected Family Contribution calculation has a pinned rounding contract: when both an income component and an asset component contribute, the income component is rounded first to a whole cent using round-half-up, the asset component is rounded second to a whole cent using round-half-up, and only then are the two rounded integers summed. Summing the un-rounded floats first and rounding once at the end is incorrect and can produce a one-cent difference for some inputs. The composite-score calculation likewise uses per-component rounding to two decimal places (round-half-up) followed by a final round-half-up to two decimal places on the sum — described in detail in §3.

### 2.10. The Logical Clock

The platform maintains a singleton logical clock used for every deadline comparison. The clock's only mutable field is `current_utc`, an ISO 8601 UTC timestamp. A `PlatformAdmin` test-driving capability accepts a request body containing a `to_iso8601` field and overwrites `current_utc` with that value; a read capability returns the singleton's current value. All deadline comparisons (Application submit against `School.deadline_iso`, the begin-review gate against the same deadline, the decision-release expectation against `decision_release_iso`) consult this clock rather than the host's wall time, so the system is deterministic under test.

## 3. Business Logic & Workflows

### 3.1. The Applicant Profile and Its Locking

A prospective student becomes a citizen of the platform by self-registering: they provide a `full_name`, a unique lowercase `email` (validated against an RFC-5322-minimal pattern; uniqueness is enforced across the entire `Applicant` table), an unweighted GPA on the 4.00 scale carried in `gpa_unweighted` (two decimals, between 0.00 and 4.00 inclusive), an optional `sat_total` (an integer between 400 and 1600 inclusive, or `null` when the student is applying test-optional), and a `residency` value drawn from `IN_STATE`, `OUT_OF_STATE`, or `INTERNATIONAL` — the residency category that downstream cost calculations key off of. On creation the new `Applicant` is in `profile_status` `DRAFT` and the `submitted_application_count` is 0.

While the profile is `DRAFT`, the applicant may freely amend their own row, sending updates to any subset of `full_name`, `gpa_unweighted`, `sat_total`, and `residency`. The moment they submit their first application, however, the profile is auto-promoted to `LOCKED` — and from that point forward, attempts to mutate `gpa_unweighted`, `sat_total`, or `residency` are rejected with `ERR_PROFILE_LOCKED`. The `full_name` field remains editable in either state. The locking transition is automatic and not directly triggerable: it is a side effect of the first application's `DRAFT → SUBMITTED` transition, and the same transaction refreshes the applicant's `updated_at` and increments the applicant's `version`. The lock exists so that every downstream calculation that consumes `gpa_unweighted`, `sat_total`, or `residency` (composite score, net cost) draws from a snapshot the applicant cannot retroactively rewrite.

The `submitted_application_count` is a server-maintained tally of how many of the applicant's applications currently sit in the "live" status set — `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, `DENIED`, `ENROLLED`, or `DECLINED` (everything except `DRAFT` and `WITHDRAWN`). It is recomputed only at the boundary crossings: incremented when an application transitions from `DRAFT` to `SUBMITTED`, decremented when an application transitions from `SUBMITTED` back to `WITHDRAWN`. Movements internal to the live set (e.g., `SUBMITTED → UNDER_REVIEW → ADMITTED → DECLINED`) leave the count unchanged.

### 3.2. Schools, Their Tuition Schedule, and the Yield Posture

A `PlatformAdmin` operator stocks the catalogue. Each `School` carries a unique `name`, a `state_code` (a two-letter US code, or the literal `INTL` for foreign campuses), an `admission_track` drawn from `EARLY_DECISION`, `EARLY_ACTION`, `REGULAR`, and `ROLLING`, a `deadline_iso` for the submission cut-off, and a `decision_release_iso` by which the school's `AdmissionsOfficer` must have published decisions — the contract requires `decision_release_iso` to be strictly later than `deadline_iso`. The school also declares its enrollment-management posture up front: `target_class_size` (the headcount it is trying to fill, an integer between 1 and 10000 inclusive) and `assumed_yield_rate` (the fraction of admitted applicants the school expects will end up enrolling, between 0.05 and 1.00 inclusive). Finally, the school publishes its tuition schedule as three integer cent values — `in_state_tuition_cents`, `out_of_state_tuition_cents`, and `international_tuition_cents` — with the contract that each tier is at least as expensive as the previous one (in-state ≤ out-of-state ≤ international) and none may be negative.

The school also carries four server-maintained counters and a derived posture. `admitted_count` is the number of the school's applications currently in `ADMITTED` status (it excludes both `ENROLLED` and `DECLINED`, so an admit that becomes an enrollment decrements `admitted_count` and increments `enrolled_count` in the same transaction). `enrolled_count` is the number currently `ENROLLED`. `declined_count` is the number whose status equals `DECLINED`; `denied_count` is the number whose status equals `DENIED` — both are monotonically non-decreasing in normal operation because `DENIED` and `DECLINED` are terminal. The derived `yield_posture` takes one of three values: `OPEN`, `ON_TARGET`, or `OVER_TARGET`. Its computation projects the eventual enrolled headcount by taking the school's current `admitted_count`, multiplying by the school's `assumed_yield_rate`, adding the current `enrolled_count`, and rounding to a whole person using round-half-up. That projected yield is divided by `target_class_size` to produce a ratio. If the ratio is at least 1.00, the posture is `OVER_TARGET`; otherwise, if the ratio is at least 0.85, the posture is `ON_TARGET`; otherwise the posture is `OPEN`. The thresholds are inclusive — a ratio of exactly 1.00 maps to `OVER_TARGET`, a ratio of exactly 0.85 maps to `ON_TARGET` — and the posture is recomputed every time `admitted_count` or `enrolled_count` changes, which in practice means every Application status transition into or out of `ADMITTED` or `ENROLLED`.

The posture gates exactly one operation: waitlist promotion. A school whose posture is `ON_TARGET` or `OVER_TARGET` cannot promote any more candidates off its waitlist (see §3.6).

### 3.3. Drafting an Application Bundle

Applying to a school begins with a draft. The applicant creates an `Application` by supplying just two foreign keys in the payload — the `applicant_id` (which must equal the caller's `X-User-ID`) and the `school_id` — and the server creates the row with `status` set to `DRAFT`, a fresh UUID `id`, `version` of 1, and `submitted_at`, `decision_at`, `enrollment_decision_at`, `composite_score`, and `admission_track_snapshot` all unset. The draft is the workspace where the applicant assembles the three artifacts that gate submission: essays, recommendation letters, and a financial-aid profile.

Essays attach to a specific application. To create one, the applicant sends a payload containing the `application_id` they are writing for, a `prompt_code` short identifier (e.g., `PERSONAL`, `WHY_X`, `DIVERSITY`) that must be unique among the essays of that single application, an integer `word_count` between 1 and 650 inclusive, the essay `text` itself, and an optional `completed` boolean that defaults to false. The server independently re-counts the words in `text` and rejects the create or update with `ERR_WORD_COUNT_MISMATCH` whenever the declared `word_count` differs from the server count by more than 5 words in either direction. The same word-count guard applies to essay updates, which may carry any combination of `word_count`, `text`, and `completed`. Marking an essay `completed` is a one-flag commitment; before submitting the parent application, every essay attached to it must have `completed` set to true.

Recommendation letters are arranged through invitations. The applicant initiates one with a payload containing the `applicant_id` (must match `X-User-ID`), the target `school_id`, and the `recommender_email` of the external party they are inviting; the triplet `(applicant_id, school_id, recommender_email)` must be unique, so the applicant cannot double-invite the same recommender for the same school. The invitation is created in `status` `INVITED` and has `submitted_at` and `rating` both unset. The recommender themselves is not a platform user; the actual letter submission is performed by a `PlatformAdmin` operator who records the recommender's outcome — a `rating` integer between 1 and 5 inclusive — using the workflow described in §3.7. Before the parent application is submitted, the applicant may waive an invitation if circumstances change: the waive is allowed only while no application of the same applicant against the same school is in `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, or `ENROLLED` status. The waive transitions the request from `INVITED` to `WAIVED`.

The applicant also produces exactly one `FinancialAidProfile` for themselves — the `applicant_id` foreign key is unique across the table. The payload picks a `profile_type` of either `FAFSA` or `CSS_PROFILE`, declares `household_income_cents` (a non-negative integer in cents), `household_size` (an integer between 1 and 20 inclusive), and an optional `declared_assets_cents` (non-negative cents). The `declared_assets_cents` field is reserved for the CSS Profile variant: any FAFSA profile that arrives with a non-zero `declared_assets_cents` (whether on create or on update) is rejected with `ERR_FAFSA_DISALLOWS_ASSETS`. The server computes a derived `expected_family_contribution_cents` value from these inputs, as detailed in §3.4.

### 3.4. Computing the Expected Family Contribution

The expected family contribution is recomputed on every create and every update of a `FinancialAidProfile`. The first step is identical for both profile types: the server subtracts a per-person shelter allowance — 8000 dollars, or 800,000 cents, per person in the household — from `household_income_cents`, multiplied by `household_size`. If the result is negative, it is floored to zero, producing an adjusted income in cents. The adjusted income is then multiplied by a 22 % income-assessment rate (0.22) to produce a base contribution; the multiplication's result is rounded to a whole cent using round-half-up. This rounded base is what a `FAFSA` profile reports as its `expected_family_contribution_cents` — even if the FAFSA row somehow carried a positive `declared_assets_cents` (which the validation in §3.3 should already have rejected), the FAFSA variant ignores it and contributes zero from assets.

The `CSS_PROFILE` variant adds an asset component on top. The server multiplies `declared_assets_cents` by a 5 % asset-assessment rate (0.05), rounds that product to a whole cent using round-half-up, and sums the rounded asset contribution with the already-rounded base. The rounding order is pinned: the income component is rounded first, the asset component is rounded second, and the sum of two integers is the final `expected_family_contribution_cents`. Summing the un-rounded floats and rounding once at the end produces a different cent for certain inputs and is not the contract. A CSS Profile applicant with identical income and household size always reports a strictly higher contribution than a FAFSA applicant whenever `declared_assets_cents` is greater than zero.

### 3.5. Submitting an Application and the Composite Score

When the bundle is ready, the applicant submits — driving the application from `DRAFT` to `SUBMITTED`. The submission is only honored if all of the following are true at the moment the request is processed: the caller's `X-User-ID` equals the application's `applicant_id`; the platform's logical clock (see §2.10) reads a value no later than the target school's `deadline_iso`; every `Essay` whose `application_id` equals this application has `completed` set to true; at least two `RecommendationRequest` rows exist where the `applicant_id` and `school_id` match this application and the `status` is `SUBMITTED`; and a `FinancialAidProfile` for this `applicant_id` exists (any `profile_type` is acceptable). If the school's `admission_track` is `EARLY_DECISION`, one further constraint applies: the applicant must not already have another Application whose `admission_track_snapshot` is `EARLY_DECISION` and whose status is any of `SUBMITTED`, `UNDER_REVIEW`, `ADMITTED`, `WAITLISTED`, or `ENROLLED` — only one Early-Decision commitment may live at a time, enforced by `ERR_ED_EXCLUSIVITY_VIOLATED`. A deadline miss yields `ERR_DEADLINE_PASSED`; missing essays, recommendations, or financial-aid profile yield the bundled `ERR_APPLICATION_INCOMPLETE`.

When all preconditions hold, the submit transitions the application's `status` to `SUBMITTED`, server-stamps `submitted_at` with the logical clock's `current_utc`, snapshots the school's current `admission_track` into the immutable `admission_track_snapshot` field on the application (so a later school-side change cannot retroactively re-classify a pinned commitment), increments the applicant's `submitted_application_count` by one, refreshes the application's `updated_at`, and bumps the application's `version` by one. If this is the applicant's first submit and the applicant's `profile_status` is still `DRAFT`, the cascade described in §3.1 fires in the same transaction. The same transaction also computes the application's initial `composite_score`.

The composite score is a 0–100 weighted blend of four normalized components. The first component normalizes the applicant's `gpa_unweighted` against the 4.00 scale: divide by 4.00, multiply by 100, and round half-up to two decimal places to produce a GPA normalized score in the 0.00 to 100.00 range. The second component normalizes the applicant's `sat_total`: if `sat_total` is null (the test-optional path), the SAT normalized value defaults to the neutral 50.00; otherwise the server subtracts 400, divides by 1200, multiplies by 100, and rounds half-up to two decimal places, yielding a value in the 0.00 to 100.00 range. The third component is essay-based: the server counts the number of `Essay` rows belonging to the application whose `completed` is true, multiplies that count by 20.00, and takes the smaller of the product and 100.00 — so five or more completed essays maxes the essay score. The fourth component is recommendation-based: the server averages the `rating` values across all `RecommendationRequest` rows whose `(applicant_id, school_id)` matches and whose `status` is `SUBMITTED`; if no such rows exist, the average is treated as zero; the average is then divided by 5.00, multiplied by 100, and rounded half-up to two decimal places to produce a recommendation score in the 0.00 to 100.00 range.

The four normalized scores are blended with fixed weights: the GPA normalized score is weighted 0.40, the SAT normalized score is weighted 0.20, the essay score is weighted 0.15, and the recommendation score is weighted 0.25. Per-component rounding precedes summation in a pinned order: each component is multiplied by its weight and the product is rounded half-up to two decimal places to yield that component's term; the four terms are then summed; and the sum itself is rounded half-up to two decimal places to produce the final `composite_score`. Summing the unrounded weighted products first and rounding once at the end produces a different second decimal in some inputs and is not the contract. The test-optional variant — where `sat_total` is null and the SAT component takes the neutral 50.00 — produces a different `composite_score` than a real SAT for the same applicant unless the applicant's hypothetical SAT would normalize to exactly 50.00; a 1400 SAT yields an SAT normalized of 83.33 and an SAT term of 16.67, where a null `sat_total` yields an SAT term of 10.00, a 6.67-point swing on the same applicant.

The `composite_score` is recomputed not only at submit but at four other moments: when a recommendation for the matching `(applicant_id, school_id)` flips from `INVITED` to `SUBMITTED` (the recommender's `rating` enters the average); when an `AidPackage` linked to the application is finalized while the application is in `ADMITTED`; when an `Essay` is created or updated while the parent application is in `SUBMITTED` or `UNDER_REVIEW`; and when the applicant patches `gpa_unweighted` or `sat_total` on their own row (which is allowed only while the profile is `DRAFT`, so this last recomputation is rare but specified). In all four cases the recomputation is scoped to applications currently in `SUBMITTED` or `UNDER_REVIEW` (and `ADMITTED`, for the aid-finalize trigger).

### 3.6. The Admissions Workflow

An application sitting in `SUBMITTED` enters the admissions office's queue. An `AdmissionsOfficer` whose school assignment matches the application's `school_id` begins review, transitioning the application from `SUBMITTED` to `UNDER_REVIEW`. Begin-review is gated on the deadline for all tracks except `ROLLING`: for non-rolling schools, review may only begin once the logical clock has advanced past the school's `deadline_iso`; for rolling schools the gate is waived and review may begin any time after submit. The transition refreshes the application's `updated_at` and increments its `version`.

From `UNDER_REVIEW` an officer drives one of three decisions: admit, waitlist, or deny. Admitting transitions the application from `UNDER_REVIEW` to `ADMITTED`, stamps `decision_at` with the logical clock, increments the linked school's `admitted_count` by one, recomputes the school's `yield_posture` as described in §3.2, refreshes the application's `updated_at`, and bumps its `version`. The admit endpoint participates in optimistic concurrency: the request body must include `expected_application_version` carrying the writer's last observed `version` of the application; if another writer (for example, a peer officer who waitlisted the same application a moment earlier — `UNDER_REVIEW` can legitimately depart to either `ADMITTED` or `WAITLISTED`) has advanced the row's `version`, the admit is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection is framed in stale-version terms; it does not depend on the two requests arriving simultaneously, only on the writer's observed `version` being out of date.

Waitlisting transitions the application from `UNDER_REVIEW` to `WAITLISTED`, but only if its `admission_track_snapshot` is not `EARLY_DECISION` — Early-Decision applications cannot be waitlisted. The transition stamps `decision_at`, refreshes `updated_at`, bumps `version`, and creates a new `WaitlistEntry` row whose `application_id` is the application's `id`, whose `status` is `PENDING`, and whose `rank` is the next unused integer for the school, computed by ordering all already-`PENDING` entries of that school by their parent application's `composite_score` descending and `submitted_at` ascending — a higher composite score (and, as tiebreaker, an earlier submission) lands a lower rank number, where rank 1 means "first to be promoted". Ranks are stable and never renumbered after a promotion or release.

Denying transitions the application from `UNDER_REVIEW` to `DENIED`, stamps `decision_at`, increments the school's `denied_count` by one, and cascades: if an `AidPackage` for this `application_id` exists in `FINALIZED` status, that aid package is cascaded from `FINALIZED` to `REVOKED` in the same transaction, refreshing the aid package's `updated_at` and incrementing its `version`.

Off the waitlist, an officer may promote the lowest-rank `PENDING` entry to admitted, but only when the school's `yield_posture` equals `OPEN`. A waitlist promote attempt against a school whose posture is `ON_TARGET` or `OVER_TARGET` is rejected with `ERR_YIELD_TARGET_REACHED` — the posture gate exists so a school cannot over-admit once its projected yield has caught up with its `target_class_size`. The promote acts on the single `PENDING` entry for the school with the minimum `rank` (if more than one `PENDING` entry exists, the lowest `rank` integer wins); it transitions the parent application from `WAITLISTED` to `ADMITTED`, overwrites `decision_at` with the current logical clock, cascades the `WaitlistEntry` from `PENDING` to `PROMOTED` and stamps `promoted_at`, increments the school's `admitted_count`, and recomputes `yield_posture`. The other `PENDING` entries are not renumbered.

### 3.7. The Recommendation Submission Loop

Recommenders do not log in. A `PlatformAdmin` operator records the recommender's letter by acting on the corresponding `RecommendationRequest`: the operator supplies the recommender's `rating` (an integer between 1 and 5 inclusive) in the request body, and the server transitions the request from `INVITED` to `SUBMITTED`, stamps `submitted_at` with the logical clock, persists the supplied `rating` onto the row (it stays null while `status` is `INVITED` and only becomes non-null on the `SUBMITTED` transition), refreshes `updated_at`, and bumps `version`. If the recommender's `(applicant_id, school_id)` matches an `Application` whose status is `SUBMITTED` or `UNDER_REVIEW`, that application's `composite_score` is recomputed in the same transaction, picking up the new rating in the recommendation average.

### 3.8. Financial Aid Offers and the Tuition Cap

A `FinancialAidOfficer` at the admitting school drafts a financial offer once an application has reached `ADMITTED`. The offer is created with a payload containing the `application_id`, an integer `grant_cents` (non-negative), an integer `loan_cents` (non-negative), and an integer `work_study_cents` (non-negative). The `AidPackage` is uniquely keyed by its `application_id` — one package per application — and starts in `status` `DRAFT`. Finalization is the operative transition: it moves the package from `DRAFT` to `FINALIZED`, but only if the linked application is in `ADMITTED`, a `FinancialAidProfile` exists for the application's owning applicant, and the sum `grant_cents + loan_cents + work_study_cents` does not exceed the residency-appropriate tuition on the linked school — `in_state_tuition_cents` for an `IN_STATE` applicant, `out_of_state_tuition_cents` for an `OUT_OF_STATE` applicant, `international_tuition_cents` for an `INTERNATIONAL` applicant. A sum that exceeds the cap is rejected with `ERR_AID_EXCEEDS_TUITION`.

Finalization computes and persists `net_cost_cents`. The server picks the residency-appropriate tuition exactly as above; computes the total award by summing in this fixed order — grant first, then loan, then work-study — to produce the total award in cents; and subtracts the total award from the tuition to produce `net_cost_cents`. The arithmetic is integer-cent only and requires no rounding; a negative `net_cost_cents` is mathematically possible only when the cap is also satisfied (it isn't, because the cap is the same comparison), so in practice `net_cost_cents` is non-negative whenever finalize succeeds. Finalize also refreshes the aid package's `updated_at`, bumps its `version`, and recomputes the linked application's `composite_score` if the application is currently in `ADMITTED`.

The cascade direction matters: a finalized aid package becomes `REVOKED` automatically whenever the linked application transitions to `DENIED` (officer deny) or to `DECLINED` (applicant decline from `ADMITTED`, or the cascaded decline that fires when the applicant enrolls elsewhere). `REVOKED` is terminal — there is no reactivation path.

### 3.9. Applicant Decisions: Enroll and Decline

Once an application sits in `ADMITTED`, the applicant chooses. Enrolling transitions the application from `ADMITTED` to `ENROLLED` and is gated on three preconditions: the caller's `X-User-ID` equals the application's `applicant_id`; an `AidPackage` for this `application_id` exists in `FINALIZED` status; and the applicant does not already have another `Application` in `ENROLLED` status — the aggregate-capacity rule, enforced by `ERR_ENROLLMENT_ALREADY_DECLARED`, says an applicant can be enrolled in at most one school across the lifetime of their account (an open-ended occupation interval starting at the enroll instant). The transition stamps `enrollment_decision_at`, decrements the school's `admitted_count` (the application leaves `ADMITTED`), increments the school's `enrolled_count`, recomputes the school's `yield_posture`, refreshes the application's `updated_at`, and bumps its `version`.

The enroll then sweeps every other live application of the same applicant: for every other `Application` of this `applicant_id` whose status is either `ADMITTED` or `WAITLISTED`, the application is cascaded to `DECLINED`. Each cascaded decline transition fires its full side-effect set in the same transaction — the linked school's `declined_count` is incremented, the linked school's `admitted_count` is decremented (only when the cascade source was `ADMITTED`, since a `WAITLISTED` row's count is held by the waitlist, not by `admitted_count`), the linked school's `yield_posture` is recomputed, any `FINALIZED` `AidPackage` on the cascaded application is cascaded to `REVOKED`, any `PENDING` `WaitlistEntry` on the cascaded application is cascaded to `RELEASED`, and the cascaded application's `enrollment_decision_at` is stamped, `updated_at` refreshed, and `version` bumped. The applicant's other commitments are settled atomically with the enrollment.

Declining is the applicant's other terminal choice and is allowed from either `ADMITTED` or `WAITLISTED`. A decline from `ADMITTED` is rejected when the application's `admission_track_snapshot` is `EARLY_DECISION` — Early-Decision admits are binding, and the attempt surfaces `ERR_ED_BINDING_VIOLATION`. The transition stamps `enrollment_decision_at`, increments the school's `declined_count`, and, when the source was `ADMITTED`, decrements the school's `admitted_count` and recomputes `yield_posture`, and cascades any `FINALIZED` `AidPackage` to `REVOKED`; when the source was `WAITLISTED`, the corresponding `PENDING` `WaitlistEntry` cascades to `RELEASED`. In both cases the application's `updated_at` is refreshed and `version` is bumped.

Withdrawing is the applicant's escape hatch before any decision has been issued. It is allowed only from `DRAFT` or `SUBMITTED` (not from `UNDER_REVIEW` or later — once the officer has begun review, the only paths out are admit, waitlist, or deny). The transition refreshes `updated_at` and bumps `version`. Withdrawing from `SUBMITTED` additionally decrements the applicant's `submitted_application_count` by one; withdrawing from `DRAFT` does not (the application was never counted).

### 3.10. Application Listing, Read Access, and Cross-Role Visibility

Application listing supports filtering by `applicant_id`, `school_id`, and `status` in addition to the universal `limit` and `offset`. Applicant listing accepts an optional `residency` filter; school listing accepts an optional `admission_track` filter; essay, recommendation, financial-aid-profile, and aid-package listings accept the relevant scoping foreign-key filter (`application_id` for essays and aid packages, `applicant_id` and `school_id` for recommendation requests, `applicant_id` for financial-aid profiles). Waitlist listings — both the global `WaitlistEntry` list and the per-school waitlist view — accept an optional `status` filter. The per-school waitlist view is the one exception to the default `created_at` ascending order: it returns its `PENDING` entries sorted by `rank` ascending so the next-to-promote candidate is always at the head. Read access on individual rows follows the §1.7 RBAC matrix reflected in §4 — an applicant may read their own resources and the platform's public catalogue (schools, the clock), an admissions officer may read their school's applications and the broader catalogue, a financial-aid officer may read what they need to draft and finalize packages, and a platform admin may read everything.

## 4. Endpoint Definitions

Resource creation endpoints (POSTs that mint a new row) return HTTP 201 on success. All other successful endpoints — including reads, list endpoints, updates, and every workflow-action POST that drives a state machine — return HTTP 200. Error responses use the HTTP status codes listed in §5; request bodies and the resulting resource shapes are described in the §3 workflow narratives, not in this table.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/applicants` | Create an applicant (self-registration) | `Anonymous` |
| GET | `/applicants/{id}` | Read an applicant | `Applicant`, `AdmissionsOfficer`, `FinancialAidOfficer`, `PlatformAdmin` |
| PATCH | `/applicants/{id}` | Update mutable applicant fields | `Applicant` |
| GET | `/applicants` | List applicants (paginated) | `AdmissionsOfficer`, `FinancialAidOfficer`, `PlatformAdmin` |
| POST | `/schools` | Create a school | `PlatformAdmin` |
| GET | `/schools/{id}` | Read a school | `Applicant`, `AdmissionsOfficer`, `FinancialAidOfficer`, `PlatformAdmin` |
| GET | `/schools` | List schools | `Applicant`, `AdmissionsOfficer`, `FinancialAidOfficer`, `PlatformAdmin` |
| POST | `/applications` | Create a draft application | `Applicant` |
| GET | `/applications/{id}` | Read an application | `Applicant`, `AdmissionsOfficer`, `PlatformAdmin` |
| GET | `/applications` | List applications | `Applicant`, `AdmissionsOfficer`, `FinancialAidOfficer`, `PlatformAdmin` |
| POST | `/applications/{id}/submit` | Applicant submits a draft application | `Applicant` |
| POST | `/applications/{id}/withdraw` | Applicant withdraws an own application | `Applicant` |
| POST | `/applications/{id}/begin-review` | AdmissionsOfficer begins reviewing a submitted application | `AdmissionsOfficer` |
| POST | `/applications/{id}/admit` | AdmissionsOfficer admits an application | `AdmissionsOfficer` |
| POST | `/applications/{id}/waitlist` | AdmissionsOfficer waitlists an application | `AdmissionsOfficer` |
| POST | `/applications/{id}/deny` | AdmissionsOfficer denies an application | `AdmissionsOfficer` |
| POST | `/applications/{id}/enroll` | Applicant enrolls in an admitted school | `Applicant` |
| POST | `/applications/{id}/decline` | Applicant declines an admitted or waitlisted application | `Applicant` |
| POST | `/essays` | Create an essay | `Applicant` |
| PATCH | `/essays/{id}` | Update an essay's fields | `Applicant` |
| GET | `/essays/{id}` | Read an essay | `Applicant`, `AdmissionsOfficer`, `PlatformAdmin` |
| GET | `/essays` | List essays | `Applicant`, `AdmissionsOfficer`, `PlatformAdmin` |
| POST | `/recommendation-requests` | Applicant invites a recommender | `Applicant` |
| POST | `/recommendation-requests/{id}/submit` | PlatformAdmin records a submitted recommendation | `PlatformAdmin` |
| POST | `/recommendation-requests/{id}/waive` | Applicant waives a recommendation invite | `Applicant` |
| GET | `/recommendation-requests/{id}` | Read a recommendation request | `Applicant`, `AdmissionsOfficer`, `PlatformAdmin` |
| GET | `/recommendation-requests` | List recommendation requests | `Applicant`, `AdmissionsOfficer`, `PlatformAdmin` |
| POST | `/financial-aid-profiles` | Create a financial aid profile | `Applicant` |
| GET | `/financial-aid-profiles/{id}` | Read a financial aid profile | `Applicant`, `FinancialAidOfficer`, `PlatformAdmin` |
| GET | `/financial-aid-profiles` | List financial-aid profiles | `Applicant`, `FinancialAidOfficer`, `PlatformAdmin` |
| PATCH | `/financial-aid-profiles/{id}` | Update a financial aid profile | `Applicant` |
| POST | `/aid-packages` | Draft an aid package for an ADMITTED Application | `FinancialAidOfficer` |
| POST | `/aid-packages/{id}/finalize` | Finalize an aid package; computes net cost | `FinancialAidOfficer` |
| GET | `/aid-packages/{id}` | Read an aid package | `Applicant`, `FinancialAidOfficer`, `PlatformAdmin` |
| GET | `/aid-packages` | List aid packages | `Applicant`, `FinancialAidOfficer`, `PlatformAdmin` |
| GET | `/schools/{id}/waitlist` | List PENDING waitlist entries for a school (ordered by rank ASC) | `AdmissionsOfficer`, `PlatformAdmin` |
| GET | `/waitlist-entries/{id}` | Read a waitlist entry | `Applicant`, `AdmissionsOfficer`, `PlatformAdmin` |
| GET | `/waitlist-entries` | List waitlist entries | `Applicant`, `AdmissionsOfficer`, `PlatformAdmin` |
| POST | `/schools/{id}/waitlist/promote` | Promote the lowest-rank PENDING WaitlistEntry to ADMITTED | `AdmissionsOfficer` |
| POST | `/_clock/set_current_utc` | Test-driving: set the logical system clock | `PlatformAdmin` |
| GET | `/_clock` | Read the current logical system clock | `PlatformAdmin`, `Applicant`, `AdmissionsOfficer`, `FinancialAidOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNER_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEADLINE_PASSED` | 409 |
| `ERR_ED_EXCLUSIVITY_VIOLATED` | 409 |
| `ERR_APPLICATION_INCOMPLETE` | 422 |
| `ERR_ED_BINDING_VIOLATION` | 409 |
| `ERR_AID_EXCEEDS_TUITION` | 422 |
| `ERR_YIELD_TARGET_REACHED` | 409 |
| `ERR_WORD_COUNT_MISMATCH` | 422 |
| `ERR_FAFSA_DISALLOWS_ASSETS` | 422 |
| `ERR_PROFILE_LOCKED` | 409 |
| `ERR_ENROLLMENT_ALREADY_DECLARED` | 409 |
| `ERR_STALE_VERSION` | 412 |

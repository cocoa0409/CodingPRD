# Infant & Child Sleep Consulting API — Product Requirements Document

## 1. Introduction

A certified infant and child sleep consulting practice sells structured engagements, not one-off advice: a family opens a case for a child, completes an intake questionnaire and sleep-history assessment, receives an age-appropriate sleep plan from an assigned consultant, and then works through a time-boxed support package of phone calls and messaging with a firm first-response-time promise. Nightly sleep logs give the consultant the evidence to confirm progress or to declare a regression and adjust the plan; regression and travel troubleshooting sessions handle the inevitable bumps; and a published guarantee plus a refund policy define what happens when outcomes fall short. The practice also runs scheduled group courses as an alternative to one-on-one delivery, and it courts repeat business through follow-up packages offered to families whose earlier case completed.

This document specifies the REST API that runs that practice, mounted under `/sleep-consulting`. The product is built on a small set of enforceable commitments: finite call and message entitlements tracked as a conserving ledger, tier-and-age-band pricing with a repeat-client discount and an exact rounding order, a service-level promise whose breaches automatically compensate the family, a money-back guarantee adjudicated from reviewed nightly logs, and a deterministic logical clock that drives package expiry, follow-up windows, and every age computation so that time-dependent behavior is fully reproducible. Three roles share the workload — parents act on their own family's cases, consultants perform the clinical work on cases assigned to them, and a practice administrator runs operations (consultant roster, courses, refunds, and the clock) without touching clinical decisions.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. The recognized role values are exactly `Anonymous`, `Parent`, `Consultant`, and `PracticeAdmin`. A request missing either header, or presenting a role value outside that set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the endpoint, or whose identity fails the ownership check below, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting ClientFamily; ownership checks on any resource that references a family compare the resource's `family_id` field to `X-User-ID` (on direct family reads, the `familyId` path segment must equal `X-User-ID`). When `X-User-Role` is `Consultant`, `X-User-ID` is the `id` of the acting Consultant; the clinical actions — questionnaire review, plan creation and plan resume, nightly-log review, message first response, session completion, and case completion — compare the target case's `consultant_id` field to `X-User-ID` and reject a mismatch. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque visitor identifier not tied to any persisted entity; the role exists solely so a family can self-register from the client portal. When `X-User-Role` is `PracticeAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it, but it never compares it to any entity's `id`.

Ownership scoping also shapes reads. A `Parent` listing cases sees only their own family's cases, and a `Parent` reading a family record may read only their own. For resources nested beneath a case — questionnaire, plans, packages and their child lists, logs, sessions, messages, refund requests, and the case's enrollments — a `Parent`'s ownership is evaluated against the owning case's `family_id`; course-level reads (the course list, a course record, a course's enrollment list) carry no parent scoping. `Consultant` and `PracticeAdmin` share broad read access across consultants, families, cases, and child resources, but only the consultant assigned to a case may perform that case's clinical actions, and only a `PracticeAdmin` may decide refunds, create consultants and courses, or advance the clock.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.5 — never from wall-clock time — so it advances only when the clock is advanced.
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

List endpoints accept two query parameters: `limit`, which defaults to 10 and must lie between 1 and 100 inclusive, and `offset`, which defaults to 0; a non-integer, negative, or out-of-range value for either is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Responses for list endpoints carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the full filtered count before pagination and `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries the same four bookkeeping properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource, and several workflows below pin their concurrency behavior or their cascade bookkeeping to it. Because the logical clock can stamp two rows with identical `created_at` values, every ordering this document pins on `created_at` breaks any remaining tie by creation (insertion) order. All twelve entity types — consultants, families, cases, questionnaires, plans, packages, nightly logs, troubleshooting sessions, messages, refund requests, courses, and enrollments — share this shape.

A number of properties are derived rather than stored, and each is recomputed on every read of its owning resource and again whenever the underlying rows change: a consultant's `active_case_count`, a case's `child_age_months` and `age_band`, a course's `enrolled_count`, and a family's `credit_balance_cents` and `is_repeat_client`. A package's `remaining_calls` and `remaining_messages` are likewise always current on read, but they are maintained as stored ledger counters by the entitlement operations of §3.4 — not recomputed from session and message rows — and are clamped at zero when rendered. Reads therefore always reflect the current logical clock and the current ledger state, never a cached snapshot.

### 2.5. The Logical Clock

Time inside the practice is governed by a server-held logical clock, never by wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never silently falls back to the host's real time. The server holds all state in memory only, so every boot starts with an empty store and the clock at that instant. A `PracticeAdmin` may set the clock to a supplied instant via the `to_iso8601` input of the admin-only clock capability; the response reports the resulting `current_utc` together with the `expired_package_ids` of any packages the move expired, listed in ascending package `created_at` (creation order). Advancing the clock past a package's `expires_on` transitions that package from `ACTIVE` to `EXPIRED`, and that transition is permanent — expiry never reverts on later clock moves, in either direction. The logical clock is the single reference for child-age computation, package coverage windows, the cooling-off and follow-up windows, course enrollment closure, session start checks, message SLA measurement, and the rule that a nightly log cannot describe a future date.

### 2.6. Monetary Precision, Rounding, and the Family Credit Ledger

All monetary values are integer cents. Wherever a computation produces a fractional cent, the result is rounded half up to a whole cent, and the order of operations is part of the contract: in package pricing the repeat-client discount is rounded half up to whole cents first and only then subtracted from the gross price, because rounding after the subtraction would yield a different cent.

Each family carries a credit ledger, `credit_balance_cents`, which starts at zero. Two events add to it: an SLA breach credit granted on a first response, and the approved amount of a refund. One event draws it down: applying credit to a package purchase. The balance can never go negative, because purchases validate that the requested credit does not exceed the available balance before accepting it. Ledger movements adjust the stored balance in place and do not by themselves increment the family record's `version` or refresh its `updated_at`.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both reject a stale writer with the same error. Creating a sleep plan for a case requires the request to carry `expected_case_version`, holding the `version` of the case as the client last observed it; if the case's current `version` no longer matches that value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because a writer holding an outdated case version would unknowingly supersede a plan it never saw. Booking a troubleshooting session requires the request to carry `expected_package_version`, holding the `version` of the support package as the client last observed it; if the selected package's current `version` no longer matches, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412), because the package's entitlement ledger mutates on every booking, cancellation, and message, so a mismatched version means the caller's view of the remaining call entitlement is out of date. No endpoint other than these two accepts a version field. Within the pipeline of §2.8, the version check runs after the guarded resource's existence and ownership have resolved — for session booking that is after the consumable package has been selected, since the guard targets that package's version — and before the state, method-age, temporal, and quota checks; a request that omits the version field or carries a non-integer value fails stage 3 with `ERR_INVALID_REQUEST`.

### 2.8. Validation Pipeline and Priority Order

Every request passes through a fixed ten-stage validation pipeline, and the order is contractual: when several checks would fail, the earliest stage determines the error returned, so a caller always sees, for example, an authentication failure rather than a downstream not-found. The stages, in evaluation order, are:

1. **User context.** Both headers are present and the role is recognized; failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) on every endpoint.
2. **Authorization and ownership.** The role is permitted for the endpoint and the `Parent`/`Consultant` identity matches the target resource's owner or assignee as described in §2.1; failures yield `ERR_FORBIDDEN` (HTTP 403). Except at case opening — where a `Parent`'s body-supplied `family_id` is checked before the family lookup — every ownership check runs against the already-resolved resource, so an unresolvable path or body identifier yields its stage-4 404 rather than a 403 even when the caller could never own the target.
3. **Request-body shape.** The body must be a JSON object; required fields are present, enum members are valid, and integer and range constraints hold — `max_active_cases` at least 1, course `capacity` at least 1, all counts at least 0, `adjustment_points` between −30 and +30 inclusive, `scheduled_start` strictly after the logical clock with `scheduled_end` after `scheduled_start` and the session lasting between 15 and 120 minutes inclusive, `log_date` not in the future, and `apply_credit_cents` at least 0; failures yield `ERR_INVALID_REQUEST` (HTTP 400). The remaining bound on `apply_credit_cents` — no more than the smaller of the family balance and the gross-minus-discount remainder — is evaluated during purchase processing, after the case and family have resolved and after the `FOLLOW_UP` state check, so on a request failing several stages it surfaces after stage-4 and stage-5 errors rather than here.
4. **Existence.** Path identifiers resolve to real resources, validated left to right along the URL, and body foreign keys resolve as well; failures yield the resource-specific 404 of the first missing resource (see §2.9).
5. **State.** The target resource is in a status that permits the operation; failures yield the appropriate 409 state error (`ERR_CASE_INVALID_STATE`, `ERR_PLAN_INVALID_STATE`, `ERR_PACKAGE_NOT_ACTIVE`, `ERR_SESSION_INVALID_STATE`, `ERR_REFUND_INVALID_STATE`, `ERR_MESSAGE_ALREADY_RESPONDED`, `ERR_ENROLLMENT_INVALID_STATE`, `ERR_QUESTIONNAIRE_ALREADY_REVIEWED`, or `ERR_LOG_ALREADY_REVIEWED`). The one-questionnaire-per-case invariant is enforced here, structurally: submission requires the case to be in `INTAKE`, and the first submission moves the case out of `INTAKE`.
6. **Method-age safety.** On plan creation only, the requested method must belong to the allowed set for the case's current age band; failures yield `ERR_METHOD_NOT_AGE_APPROPRIATE` (HTTP 422).
7. **Temporal rules.** Consultant-calendar overlap on session booking yields `ERR_SCHEDULING_CONFLICT` (HTTP 409); a follow-up purchase past its window yields `ERR_FOLLOW_UP_WINDOW_CLOSED` (HTTP 422); enrolling on or after a course's start date yields `ERR_ENROLLMENT_CLOSED` (HTTP 422).
8. **Uniqueness and coverage.** One log per case and date (`ERR_DUPLICATE_LOG`, HTTP 409), no live enrollment for the same course and case (`ERR_ALREADY_ENROLLED`, HTTP 409), no overlapping active package coverage (`ERR_PACKAGE_WINDOW_OVERLAP`, HTTP 409), and at most one pending refund per case (`ERR_REFUND_ALREADY_PENDING`, HTTP 409).
9. **Quota.** Consultant capacity at case opening yields `ERR_CONSULTANT_AT_CAPACITY` (HTTP 409); exhausted call or message entitlements at booking or sending yield `ERR_ENTITLEMENT_EXHAUSTED` (HTTP 422).
10. **Refund eligibility and delivery-mode match.** The eligibility predicate for the requested refund type yields `ERR_REFUND_NOT_ELIGIBLE` (HTTP 422); a package purchase on a group-course case, or a course enrollment for a one-on-one case, yields `ERR_DELIVERY_MODE_MISMATCH` (HTTP 422).

### 2.9. Nested Resource Resolution and Not-Found Codes

When a URL nests one resource beneath another, path identifiers are validated left to right — the case segment (`caseId`, spelled `id` on some routes) before the child segment (`questionnaireId`, `planId`, `packageId`, `logId`, `sessionId`, `messageId`, `refundId`, `courseId`, `enrollmentId`, `consultantId`, `familyId`) — and the first identifier that fails to resolve determines the response. Each resource has its own code: an unknown `consultantId` or `consultant_id` yields `ERR_CONSULTANT_NOT_FOUND`; `familyId` or `family_id` yields `ERR_FAMILY_NOT_FOUND`; `caseId` or `case_id` yields `ERR_CASE_NOT_FOUND`; `questionnaireId` yields `ERR_QUESTIONNAIRE_NOT_FOUND`; `planId` yields `ERR_PLAN_NOT_FOUND`; `packageId` yields `ERR_PACKAGE_NOT_FOUND`; `logId` yields `ERR_LOG_NOT_FOUND`; `sessionId` yields `ERR_SESSION_NOT_FOUND`; `messageId` yields `ERR_MESSAGE_NOT_FOUND`; `refundId` yields `ERR_REFUND_REQUEST_NOT_FOUND`; `courseId` yields `ERR_COURSE_NOT_FOUND`; and `enrollmentId` yields `ERR_ENROLLMENT_NOT_FOUND`. All are HTTP 404. Body-supplied foreign keys such as `family_id`, `consultant_id`, `case_id`, and `course_id` are resolved under the same stage; a body carrying several of them is validated in the order the workflow names them — at case opening, `family_id` before `consultant_id`.

## 3. Business Logic & Workflows

### 3.1. Practice Setup, Family Registration, and Opening a Case

A `PracticeAdmin` onboards each certified sleep consultant with a display `full_name`, a `certification_no`, and a `max_active_cases` cap of at least 1. A new consultant's `active_case_count` is zero; thereafter it is defined as the number of that consultant's cases currently in `ACTIVE_SUPPORT` status — cases in `NEEDS_ATTENTION` and every other status are excluded — and it is recomputed on every read and on every case status mutation, which is why the workflows below repeatedly describe it moving up or down by one.

Families self-register from the client portal under the `Anonymous` role, supplying a primary-parent `full_name` and a contact `email` that is free-form and deliberately not unique. A freshly registered family has a `credit_balance_cents` of zero and `is_repeat_client` false; the repeat flag later becomes true as soon as the family has at least one case in `COMPLETED` status, and it too is recomputed on every read and at case completion.

With both sides registered, a `Parent` opens a case for their own family (a `PracticeAdmin` may also open one), supplying `family_id`, `consultant_id`, the child's `child_birth_date` as an ISO date, the `delivery_mode` — `ONE_ON_ONE` or `GROUP_COURSE`, a choice that later gates package purchases versus course enrollment — and the `guarantee_goal_night_wakings`, the maximum acceptable number of night wakings per night under the guarantee, zero or more. The new case starts in `INTAKE` with `completed_at` null. Before the case is accepted, the assigned consultant's capacity is checked: if the consultant's `active_case_count` has already reached `max_active_cases`, the request is rejected with `ERR_CONSULTANT_AT_CAPACITY`; one below the cap still accepts, while exactly at the cap rejects.

Two derived descriptors travel with every case. `child_age_months` is the number of whole months between `child_birth_date` and the logical clock date: twelve times the difference in years plus the difference in months, minus one when the clock's day-of-month is earlier than the birth day-of-month, and never below zero. `age_band` is then `NEWBORN` at three months or younger, `INFANT` from four through eleven months, `TODDLER` from twelve through thirty-five months, and `PRESCHOOL` at thirty-six months or older; band boundaries are inclusive at the lower edge, so a child exactly four months old is `INFANT`. Both are recomputed against the logical clock on every case read. The case list accepts optional `family_id`, `consultant_id`, and `status` filters, with parents always restricted to their own family's cases.

### 3.2. The Intake Questionnaire and Severity Assessment

Once a case exists, the `Parent` completes the intake questionnaire and sleep history by submitting an `answers` object. It must contain the integer keys `night_wakings`, `night_feeds`, `bedtime_resistance_minutes`, and `nap_total_minutes` — each zero or more — and the boolean keys `medical_flags` and `preterm_birth`; keys beyond those six are accepted and stored verbatim, and only the six named keys are validated. Exactly one questionnaire may ever exist for a case, and the invariant needs no separate uniqueness check: submission requires the case to be in `INTAKE`, and the act of submitting moves the case out of `INTAKE` forever. A successful submission creates the questionnaire in `SUBMITTED` status, computes its `provisional_severity_score`, moves the case from `INTAKE` to `ASSESSMENT`, and increments the case `version` by one. Reading a case's questionnaire returns an array of length zero or one.

The provisional severity score, on a scale from 0 to 100, is computed from the answers alone. Start with ten points per night waking, add four points per night feed, add one point for each full three minutes of bedtime resistance (the minutes divided by three, rounded down), and add a nap-deficit term: the shortfall of the day's `nap_total_minutes` against a 150-minute baseline, divided by fifteen and rounded up, never less than zero. If `medical_flags` is set, subtract twenty points; if `preterm_birth` is set, subtract a further ten. The result is then clamped into the range from 0 to 100 inclusive.

A `Consultant` — specifically the one assigned to the case — then reviews the questionnaire. The review requires the questionnaire to still be `SUBMITTED` (a second review is rejected with `ERR_QUESTIONNAIRE_ALREADY_REVIEWED`) and the case to be in `ASSESSMENT`. The consultant supplies `adjustment_points`, an integer from −30 to +30 inclusive, and may attach an optional `review_note`. The `reviewed_severity_score` is the provisional score plus `adjustment_points` plus an age-band modifier taken from the case's age band at review time — `NEWBORN` contributes −5, `INFANT` contributes 0, `TODDLER` contributes +5, and `PRESCHOOL` contributes +10 — with the total clamped into the range from 0 to 100 inclusive. Because of the adjustment and the modifier, identical questionnaire answers yield a different score once reviewed. The review marks the questionnaire `REVIEWED`, records the score, and moves the case from `ASSESSMENT` to `PLANNING`, again incrementing the case `version`. Until a review happens, `adjustment_points`, `reviewed_severity_score`, and `review_note` remain null.

### 3.3. Sleep Plan Authoring and the Adjustment Loop

With the case in `PLANNING`, the assigned `Consultant` authors the sleep plan. Plan creation is permitted whenever the case is in `PLANNING`, `ACTIVE_SUPPORT`, or `NEEDS_ATTENTION` — any other case status is rejected with `ERR_CASE_INVALID_STATE` — and it is concurrency-guarded by `expected_case_version` as described in §2.7. The consultant specifies the `method` (`GENTLE_NO_CRY`, `FERBER_GRADUATED`, `CHAIR_METHOD`, or `EXTINCTION`), the `target_night_wake_count` (zero or more), the `target_longest_stretch_minutes` (strictly greater than zero), and optional free-form `notes`.

Safety comes before everything else: the requested method must be appropriate for the case's current age band. A `NEWBORN` permits only `GENTLE_NO_CRY`. An `INFANT` additionally permits `FERBER_GRADUATED` and `CHAIR_METHOD`. `TODDLER` and `PRESCHOOL` permit all four methods, including `EXTINCTION`. A request outside the allowed set is rejected with `ERR_METHOD_NOT_AGE_APPROPRIATE`.

Each plan carries a `plan_sequence`, a per-case ordinal that starts at 1 for the first plan and takes the highest existing `plan_sequence` of the case plus one thereafter. The new plan snapshots the case's current `age_band` onto itself and starts life `ACTIVE`. Any plan of the same case currently in `ACTIVE` or `NEEDS_ADJUSTMENT` is superseded by the creation, moving to `SUPERSEDED` and ceasing to be current. The case itself reacts to where it stood: from `PLANNING` — the first plan — the case moves to `ACTIVE_SUPPORT` and the consultant's `active_case_count` grows by one; from `NEEDS_ATTENTION` the superseding plan resolves the attention state, returning the case to `ACTIVE_SUPPORT` and growing the count by one again; from `ACTIVE_SUPPORT` the case simply stays put. In all three paths the case `version` increments by one.

Adjustment need not mean replacement. A plan sitting in `NEEDS_ADJUSTMENT` can be resumed in place by the assigned consultant — resuming any other plan status is rejected with `ERR_PLAN_INVALID_STATE`. The plan returns to `ACTIVE`, and when that plan is the case's latest non-`SUPERSEDED` plan, the case moves from `NEEDS_ATTENTION` back to `ACTIVE_SUPPORT` with the consultant's count recomputed upward by one. A plan's remaining exits are systemic rather than consultant-driven: when the case completes, its current `ACTIVE` plan becomes `COMPLETED`, and when a paid refund closes the case, every plan in `ACTIVE` or `NEEDS_ADJUSTMENT` becomes `CANCELLED` (§3.8).

### 3.4. Support Packages: Tiers, Pricing, and the Entitlement Ledger

One-on-one support is sold as packages. A `Parent` purchases for their own case (a `PracticeAdmin` may also do so), and the case's `delivery_mode` must be `ONE_ON_ONE` — a group-course case is rejected with `ERR_DELIVERY_MODE_MISMATCH`. The purchase names a `tier` (`BASIC`, `STANDARD`, or `PREMIUM`) and a `kind` (`INITIAL` or `FOLLOW_UP`), and may optionally pin `starts_on` — defaulting to the logical clock date when omitted, and accepted even when it lies in the past — and an `apply_credit_cents` amount, defaulting to zero. Only a `FOLLOW_UP` purchase constrains the case's status (below); an `INITIAL` purchase is accepted whatever status the case stands in.

The tier determines the package's shape. `BASIC` runs for two weeks with one included call, five included messages, and a 48-hour first-response promise. `STANDARD` runs four weeks with three calls, fifteen messages, and a 24-hour promise. `PREMIUM` runs six weeks with six calls, forty messages, and a 12-hour promise. These appear on the package as `duration_weeks`, `included_calls`, `included_messages`, and `response_sla_hours`. Coverage is a closed date interval: `expires_on` falls one day before the date `duration_weeks` weeks after `starts_on`, so both `starts_on` and `expires_on` are inside the coverage window. The purchase is stamped `purchased_at` from the logical clock, and the package begins `ACTIVE`.

Pricing is exact to the cent. The tier base is 29,900 cents for `BASIC`, 54,900 for `STANDARD`, and 89,900 for `PREMIUM`; when the case's age band is `NEWBORN`, a 4,950-cent newborn surcharge is added, and the sum is the `gross_price_cents`. A family that `is_repeat_client` at the moment of purchase earns a `repeat_discount_cents` of fifteen percent of the gross, rounded half up to whole cents first and then subtracted — the pinned order matters, since rounding after subtraction would give a different cent — while a first-time family's discount is zero. The requested `apply_credit_cents` becomes the `credit_applied_cents`, and it must lie between zero and the smaller of the family's current `credit_balance_cents` and the gross-minus-discount remainder; anything else is rejected with `ERR_INVALID_REQUEST`, and the applied amount is debited from the family's balance at purchase. The `net_price_cents` is the gross minus the repeat discount minus the applied credit, so two purchases of the same tier for the same age band price differently when one family is a repeat client.

An `INITIAL` purchase must not double-cover the case: its closed coverage interval conflicts with any other `ACTIVE` package of the case unless the new interval ends entirely before the existing one begins or begins entirely after the existing one ends. Touching boundaries do conflict — a new `starts_on` equal to an existing package's `expires_on` overlaps on that shared date — and a conflicting purchase is rejected with `ERR_PACKAGE_WINDOW_OVERLAP`. Packages in `DEPLETED`, `EXPIRED`, or `CLOSED_EARLY` no longer participate in this check.

A `FOLLOW_UP` purchase instead re-opens a finished engagement: the case must be `COMPLETED`, and the logical clock must be no later than `completed_at` plus 180 days — a later attempt is rejected with `ERR_FOLLOW_UP_WINDOW_CLOSED`. Because completion made the family a repeat client, follow-up pricing always includes the repeat discount. The purchase moves the case from `COMPLETED` back to `ACTIVE_SUPPORT` — the consultant's count and the case `version` react accordingly — and the new package starts `ACTIVE`, while `is_repeat_client` stays true.

Entitlements are a conserving ledger, tracked as stored counters on the package. `remaining_calls` starts at `included_calls`, drops by one on every booking, and rises by one on a cancellation; `remaining_messages` starts at `included_messages`, drops by one on every sent message, and never rises. Releases are the compensating half of the ledger: cancelling a session returns one call only while the charged package is still `ACTIVE`, and packages in `DEPLETED`, `EXPIRED`, or `CLOSED_EARLY` receive no releases — so once a cancellation lands on a non-`ACTIVE` package, `remaining_calls` no longer equals `included_calls` minus the count of `SCHEDULED` or `COMPLETED` sessions. Reads clamp the counters at zero — they never render negative — and a `CLOSED_EARLY` package always reports both counters as zero. Two terminal drifts end a package's useful life. Whenever a consumption leaves both `remaining_calls` and `remaining_messages` at zero, the package moves from `ACTIVE` to `DEPLETED` and its `version` increments. And whenever the logical clock advances past `expires_on`, an `ACTIVE` package becomes `EXPIRED` — permanently, and with its `version` incremented — which is precisely the moment when guarantee-eligibility evaluation (§3.8) becomes possible. Separately, the package accumulates SLA breach credits in `sla_credit_total_cents`, capped at ten percent of its `gross_price_cents` rounded half up (§3.6).

Because several operations "charge the current package," the selection rule is pinned: the consumable package is the case's package that is `ACTIVE` and whose closed coverage interval contains the logical clock date; if no such package exists, the operation is rejected with `ERR_PACKAGE_NOT_ACTIVE`. Should more than one candidate remain, the earliest `starts_on` wins, then the earliest `created_at` — the window-overlap guard makes a window-membership tie among `ACTIVE` packages impossible, but the ordering is pinned regardless. Refund subject selection intentionally uses a different rule, given in §3.8. Packages also expose their usage: the sessions charged to a package, the messages charged to a package, and the refund requests targeting a package are each listable, and the full package list of a case is readable by all three authenticated roles.

### 3.5. Nightly Sleep Logs and the Regression Cascade

During active support the `Parent` keeps a nightly diary. Submitting a log requires the case to be in `ACTIVE_SUPPORT` or `NEEDS_ATTENTION` — any other case status is rejected with `ERR_CASE_INVALID_STATE`. The entry names its `log_date`, which must not be later than the logical clock date (a future date is rejected with `ERR_INVALID_REQUEST`) and must be unique within the case (a second log for the same date is rejected with `ERR_DUPLICATE_LOG`). It records `night_wake_count`, `longest_stretch_minutes`, `nap_count`, and `nap_total_minutes`, each zero or more, plus optional `notes`. Every new log starts with `review_status` set to `PENDING_REVIEW`, and the case's log list can be filtered by `log_date` and `review_status`.

The assigned `Consultant` reviews each pending log with an `outcome` of `ON_TRACK` or `REGRESSION` and an optional `review_note`; reviewing anything other than a `PENDING_REVIEW` log is rejected with `ERR_LOG_ALREADY_REVIEWED`. An `ON_TRACK` outcome simply moves the log to `REVIEWED_ON_TRACK`. A `REGRESSION` outcome moves it to `REVIEWED_REGRESSION` and fires the three-link regression cascade, with each link conditional on current state — a link already sitting in its target state is a no-op. Link one: the case's current plan, if `ACTIVE`, becomes `NEEDS_ADJUSTMENT`. Link two: the case, if `ACTIVE_SUPPORT`, becomes `NEEDS_ATTENTION`, incrementing the case `version`. Link three: the consultant's `active_case_count` is recomputed and drops by one, because a case in `NEEDS_ATTENTION` no longer counts against the cap. From there the adjustment loop of §3.3 — resume the plan in place or author a superseding one — carries the case back to `ACTIVE_SUPPORT`.

### 3.6. Messaging, the Response-Time SLA, and Breach Credits

Between calls, the `Parent` reaches the consultant by sending a support message carrying a free-text `body`. No case-status requirement applies — the send only needs a consumable package. The server selects the case's consumable package under the rule of §3.4 — none available means `ERR_PACKAGE_NOT_ACTIVE` — records the selection in the message's `package_id`, decrements the package's `remaining_messages` by one, and re-evaluates whether the package is now depleted. Sending with a `remaining_messages` of zero is rejected with `ERR_ENTITLEMENT_EXHAUSTED`. The new message starts `AWAITING_RESPONSE`, with `response_body`, `first_responded_at`, `sla_breached`, and `credit_granted_cents` all null until the consultant replies.

The assigned `Consultant` answers with a `response_body`; the reply requires the message to still be `AWAITING_RESPONSE`, and a second response is rejected with `ERR_MESSAGE_ALREADY_RESPONDED`. The first response stamps `first_responded_at` from the logical clock and moves the message to `RESPONDED`. The service-level promise is then measured: `sla_breached` is true only when the elapsed time between the message's `created_at` and `first_responded_at` is strictly greater than the package's `response_sla_hours` — a response landing exactly on the boundary counts as on time. A breach compensates the family automatically, subject to the per-package cap: when the package's `sla_credit_total_cents` plus a further 1,000 cents still fits within ten percent of the package's `gross_price_cents` (rounded half up), the `credit_granted_cents` is 1000, and that amount is added both to the family's `credit_balance_cents` and to the package's `sla_credit_total_cents`. Once the cap has been reached, later breaches are still recorded with `sla_breached` true but grant zero credit. Because the message entitlement was consumed at send time, the response flow also re-evaluates whether the package should now flip to `DEPLETED`.

### 3.7. Troubleshooting Sessions and the Consultant Calendar

Regressions and travel disruptions are worked through live sessions, booked by the owning `Parent` or by any `Consultant` — booking does not check consultant assignment. The booking names the `session_type` — `REGRESSION` or `TRAVEL` — a `scheduled_start` strictly after the logical clock, and a `scheduled_end` such that the session lasts between 15 and 120 minutes inclusive. Booking is concurrency-guarded by `expected_package_version` as described in §2.7. No case-status requirement applies: the server selects the consumable package and records it in the session's `package_id`; with no active in-window package the booking is rejected with `ERR_PACKAGE_NOT_ACTIVE`, and with `remaining_calls` at zero it is rejected with `ERR_ENTITLEMENT_EXHAUSTED`.

The consultant's calendar carries a buffer rule. A fifteen-minute gap is required between the new session and every existing `SCHEDULED` session belonging to the same consultant — the consultant assigned to this case. A conflict exists whenever the new session's start falls before an existing session's end plus fifteen minutes and that existing session's start falls before the new session's end plus fifteen minutes; a gap of exactly fifteen minutes is allowed, a gap of fourteen is not, and direct adjacency conflicts. Violations are rejected with `ERR_SCHEDULING_CONFLICT`. A successful booking creates the session `SCHEDULED`, consumes one call entitlement (the package's `remaining_calls` drops by one), increments the package `version` by one, and re-evaluates depletion.

Sessions end in one of two ways. The assigned consultant marks a session completed, which requires it to be `SCHEDULED` — anything else is rejected with `ERR_SESSION_INVALID_STATE` — and moves it to `COMPLETED`; the call entitlement stays consumed, with no release on completion. Alternatively the owning parent or any consultant cancels the session, which likewise requires `SCHEDULED` and additionally requires the logical clock to be strictly before `scheduled_start` — either failure is rejected with `ERR_SESSION_INVALID_STATE`. Cancellation moves the session to `CANCELLED` and performs the ledger's compensating release: the charged package's `remaining_calls` increases by one and its `version` increments, but only when that package is still `ACTIVE`; sessions charged to `DEPLETED`, `EXPIRED`, or `CLOSED_EARLY` packages release nothing.

### 3.8. Refunds, Guarantee Eligibility, and Case Closure

When a family is dissatisfied, the `Parent` files a refund request naming a `refund_type` — `COOLING_OFF`, `GUARANTEE`, or `PRO_RATA` — and an optional free-form `reason`. The case must be in `ACTIVE_SUPPORT`, `NEEDS_ATTENTION`, or `COMPLETED` (anything else is rejected with `ERR_CASE_INVALID_STATE`), and at most one refund per case may be pending at a time: a second request while one is `REQUESTED` or `APPROVED` is rejected with `ERR_REFUND_ALREADY_PENDING`. The family does not choose the refund's subject; the server selects it as the case's package in `ACTIVE`, `DEPLETED`, or `EXPIRED` status having the latest `starts_on`, breaking ties by the later `created_at`, and records it in `package_id`. When the case has no package in any of those three statuses, the request is rejected with `ERR_REFUND_NOT_ELIGIBLE` (HTTP 422). A new request starts `REQUESTED`, with `amount_cents` and `denial_reason` null.

Eligibility is evaluated per refund type, and an ineligible request is rejected with `ERR_REFUND_NOT_ELIGIBLE`. `COOLING_OFF` requires that the logical clock be no later than the package's `purchased_at` plus 48 hours, that the package have zero completed sessions, that it have zero sent messages, and that the case have zero reviewed logs — logs still `PENDING_REVIEW` do not count. `GUARANTEE` requires the subject package to be `EXPIRED`, the case to have at least fourteen reviewed logs (in either `REVIEWED_ON_TRACK` or `REVIEWED_REGRESSION` state), and — among the seven most recent reviewed logs ordered by `log_date` descending, which cannot tie because log dates are unique per case — at least four entries whose `night_wake_count` is strictly greater than the case's `guarantee_goal_night_wakings`; three misses out of seven are not enough. `PRO_RATA` requires the subject package to be `ACTIVE`, the clock to be later than `purchased_at` plus 48 hours, and the computed pro-rata amount to be greater than zero.

Decisions belong to the `PracticeAdmin`. Approval requires the request to be `REQUESTED` — approving in any other state is rejected with `ERR_REFUND_INVALID_STATE` — and it computes the `amount_cents` according to the type, with the evaluation order pinned to break the apparent circle: consumption counts are read from the session, message, and log rows first, the amount is computed second, and only afterwards may the refund-paid cascade zero the packages' remaining-entitlement fields. A `COOLING_OFF` approval refunds the full `net_price_cents`. A `GUARANTEE` approval refunds fifty percent of `net_price_cents`, rounded half up. A `PRO_RATA` approval values each completed session at 7,500 cents and each sent message at 1,200 cents, subtracts that consumed total from `net_price_cents`, and floors the result at zero; identical package data therefore yields a different amount under each variant. The approved amount is credited to the family's `credit_balance_cents` at approval time. Denial likewise requires `REQUESTED`, records the mandatory `denial_reason`, and moves the request to `DENIED`.

Paying an approved request requires it to be `APPROVED` — again, any other state meets `ERR_REFUND_INVALID_STATE` — moves it to `PAID`, and fires the two-link refund-paid cascade. Link one: the case itself, whether it stood in `ACTIVE_SUPPORT` or `NEEDS_ATTENTION`, moves to `CLOSED_REFUNDED`, its terminal state, with its `version` incremented; a case paid out while `COMPLETED` keeps that status, and only the child sweep below runs. Link two sweeps the case's children: every plan in `ACTIVE` or `NEEDS_ADJUSTMENT` becomes `CANCELLED`; every package in `ACTIVE` or `DEPLETED` becomes `CLOSED_EARLY` with `remaining_calls` and `remaining_messages` frozen at zero and no possibility of later entitlement release; and every session still `SCHEDULED` becomes `CANCELLED` without releasing its call entitlement, because its package is no longer `ACTIVE`. The consultant's `active_case_count` is recomputed downward as the case leaves active support.

The non-refund ending is case completion, performed by the assigned `Consultant`. Completion requires the case to be in `ACTIVE_SUPPORT` with clean children: no package of the case in `ACTIVE` status, no session in `SCHEDULED` status, no refund request in `REQUESTED` or `APPROVED` status, and at least one plan in existence — every one of these failures is rejected with `ERR_CASE_INVALID_STATE`. On completion the case moves to `COMPLETED`, its current `ACTIVE` plan becomes `COMPLETED`, `completed_at` is stamped from the logical clock, the family's `is_repeat_client` is recomputed and becomes true, the consultant's count is recomputed downward, and the case `version` increments. Completion is also what starts the 180-day follow-up clock of §3.4.

### 3.9. Group Courses, Enrollment, and the Waitlist

Alongside one-on-one work, a `PracticeAdmin` schedules group courses, each led by a consultant identified by `consultant_id` and described by a `title`, a `starts_on` date for the first session — enrollment closes at 00:00:00Z on that date — a `capacity` of at least one seat, and a `price_cents` of zero or more that is merely recorded, with no payment flow behind it. A course's `enrolled_count` starts at zero and counts only `ENROLLED` enrollments, recomputed on every read and on every enrollment mutation. The course list can be filtered by `consultant_id`.

A `Parent` enrolls a case by its `case_id`. The case must have `delivery_mode` `GROUP_COURSE` — a one-on-one case is rejected with `ERR_DELIVERY_MODE_MISMATCH` — the logical clock date must be strictly before the course's `starts_on` (enrolling on or after the start date is rejected with `ERR_ENROLLMENT_CLOSED`), and no live enrollment may already exist for the same course and case: an existing `ENROLLED` or `WAITLISTED` row triggers `ERR_ALREADY_ENROLLED`, while `CANCELLED` and `WITHDRAWN` rows do not block a fresh enrollment. Capacity decides the outcome: when the course's `enrolled_count` is below `capacity`, the enrollment is created `ENROLLED` and the count grows by one; when the course is full, the enrollment is created `WAITLISTED` instead, holding the family's place in line.

Cancellation, available to the `Parent` or a `PracticeAdmin`, behaves differently per state, and terminal enrollments reject the attempt with `ERR_ENROLLMENT_INVALID_STATE`. Cancelling an `ENROLLED` enrollment moves it to `CANCELLED`, decrements the course's `enrolled_count` by one, and immediately runs waitlist promotion: exactly one waitlisted row — the earliest-created `WAITLISTED` enrollment of the course — is promoted to `ENROLLED` with `promoted_at` stamped from the logical clock, bringing the count back up by one; when nobody is waiting, the freed seat simply stays open. Cancelling a `WAITLISTED` enrollment moves it to `WITHDRAWN` and frees no seat, so no promotion runs. `promoted_at` remains null on any enrollment that was never promoted. Enrollments are listable per course — optionally filtered by `status` — and per case, so both the practice and the family can see the full picture.

## 4. Endpoint Definitions

All endpoints live under the `/sleep-consulting` mount. Status codes follow one convention: creating a new resource returns 201, while reads, state transitions, and other modifications return 200. Request and response payloads are not repeated here; each operation's inputs, effects, and error behavior are defined by the workflows in §3 and the cross-cutting rules in §2.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /sleep-consulting/consultants | Create a Consultant | PracticeAdmin |
| GET | /sleep-consulting/consultants/{consultantId} | Get a Consultant (recomputes `active_case_count`) | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/families | Register a ClientFamily (client-portal self-registration) | Anonymous |
| GET | /sleep-consulting/families | List ClientFamilies | PracticeAdmin, Consultant |
| GET | /sleep-consulting/families/{familyId} | Get a ClientFamily (Parent may read only their own id) | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/cases | Open a ClientCase (capacity-checked on the consultant) | Parent, PracticeAdmin |
| GET | /sleep-consulting/cases | List ClientCases with optional filters (Parent sees only their own family's) | PracticeAdmin, Consultant, Parent |
| GET | /sleep-consulting/cases/{caseId} | Get a ClientCase (recomputes `child_age_months` and `age_band`) | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/cases/{caseId}/complete | Complete a case | Consultant |
| POST | /sleep-consulting/cases/{id}/questionnaire | Submit the intake questionnaire and sleep history (one per case) | Parent |
| GET | /sleep-consulting/cases/{id}/questionnaire | Get the case's questionnaire (array of length 0 or 1) | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/questionnaires/{questionnaireId}/review | Review the questionnaire with a clinical adjustment | Consultant |
| POST | /sleep-consulting/cases/{id}/plans | Create a SleepPlan (supersedes the current plan; OCC-guarded) | Consultant |
| GET | /sleep-consulting/cases/{id}/plans | List SleepPlans of a case | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/plans/{planId}/resume | Resume a `NEEDS_ADJUSTMENT` plan without superseding it | Consultant |
| POST | /sleep-consulting/cases/{id}/packages | Purchase a support package (`INITIAL` or `FOLLOW_UP`) | Parent, PracticeAdmin |
| GET | /sleep-consulting/cases/{id}/packages | List SupportPackages of a case | PracticeAdmin, Consultant, Parent |
| GET | /sleep-consulting/packages/{packageId} | Get a SupportPackage (recomputes remaining entitlements) | PracticeAdmin, Consultant, Parent |
| GET | /sleep-consulting/packages/{id}/troubleshooting-sessions | List TroubleshootingSessions charged to a package | PracticeAdmin, Consultant, Parent |
| GET | /sleep-consulting/packages/{id}/messages | List Messages charged to a package | PracticeAdmin, Consultant, Parent |
| GET | /sleep-consulting/packages/{id}/refund-requests | List RefundRequests whose subject is this package | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/cases/{id}/logs | Submit a nightly sleep log (unique per case and date) | Parent |
| GET | /sleep-consulting/cases/{id}/logs | List NightlySleepLogs of a case | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/logs/{logId}/review | Review a log; `REGRESSION` fires the regression cascade | Consultant |
| POST | /sleep-consulting/cases/{id}/troubleshooting-sessions | Book a regression/travel session (consumes one call; OCC-guarded) | Parent, Consultant |
| GET | /sleep-consulting/cases/{id}/troubleshooting-sessions | List TroubleshootingSessions of a case | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/troubleshooting-sessions/{sessionId}/complete | Mark a session completed | Consultant |
| POST | /sleep-consulting/troubleshooting-sessions/{sessionId}/cancel | Cancel a session before it starts (releases the call if the package is `ACTIVE`) | Parent, Consultant |
| POST | /sleep-consulting/cases/{id}/messages | Send a support message (consumes one message entitlement) | Parent |
| GET | /sleep-consulting/cases/{id}/messages | List Messages of a case | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/messages/{messageId}/respond | Consultant first response; computes SLA breach and credit | Consultant |
| POST | /sleep-consulting/cases/{id}/refund-requests | Request a refund (subject package server-selected) | Parent |
| GET | /sleep-consulting/cases/{id}/refund-requests | List RefundRequests of a case | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/refund-requests/{refundId}/approve | Approve a refund; computes the amount and grants family credit | PracticeAdmin |
| POST | /sleep-consulting/refund-requests/{refundId}/deny | Deny a refund with a reason | PracticeAdmin |
| POST | /sleep-consulting/refund-requests/{refundId}/pay | Pay an approved refund; fires the refund-paid cascade | PracticeAdmin |
| POST | /sleep-consulting/group-courses | Create a GroupCourse | PracticeAdmin |
| GET | /sleep-consulting/group-courses | List GroupCourses | PracticeAdmin, Consultant, Parent |
| GET | /sleep-consulting/group-courses/{courseId} | Get a GroupCourse (recomputes `enrolled_count`) | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/group-courses/{id}/enrollments | Enroll a group-course case (waitlists when full) | Parent |
| GET | /sleep-consulting/group-courses/{id}/enrollments | List enrollments of a course | PracticeAdmin, Consultant, Parent |
| GET | /sleep-consulting/cases/{id}/enrollments | List enrollments of a case | PracticeAdmin, Consultant, Parent |
| POST | /sleep-consulting/enrollments/{enrollmentId}/cancel | Cancel an enrollment (with waitlist promotion when a seat frees) | Parent, PracticeAdmin |
| POST | /sleep-consulting/_clock/set_current_utc | Set the logical clock; expires packages whose coverage has passed | PracticeAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, alongside the workflows they guard.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CONSULTANT_NOT_FOUND | 404 |
| ERR_FAMILY_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_QUESTIONNAIRE_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_LOG_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_MESSAGE_NOT_FOUND | 404 |
| ERR_REFUND_REQUEST_NOT_FOUND | 404 |
| ERR_COURSE_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_CASE_INVALID_STATE | 409 |
| ERR_PLAN_INVALID_STATE | 409 |
| ERR_PACKAGE_NOT_ACTIVE | 409 |
| ERR_SESSION_INVALID_STATE | 409 |
| ERR_REFUND_INVALID_STATE | 409 |
| ERR_MESSAGE_ALREADY_RESPONDED | 409 |
| ERR_ENROLLMENT_INVALID_STATE | 409 |
| ERR_QUESTIONNAIRE_ALREADY_REVIEWED | 409 |
| ERR_LOG_ALREADY_REVIEWED | 409 |
| ERR_METHOD_NOT_AGE_APPROPRIATE | 422 |
| ERR_SCHEDULING_CONFLICT | 409 |
| ERR_FOLLOW_UP_WINDOW_CLOSED | 422 |
| ERR_ENROLLMENT_CLOSED | 422 |
| ERR_DUPLICATE_LOG | 409 |
| ERR_ALREADY_ENROLLED | 409 |
| ERR_PACKAGE_WINDOW_OVERLAP | 409 |
| ERR_REFUND_ALREADY_PENDING | 409 |
| ERR_CONSULTANT_AT_CAPACITY | 409 |
| ERR_ENTITLEMENT_EXHAUSTED | 422 |
| ERR_REFUND_NOT_ELIGIBLE | 422 |
| ERR_DELIVERY_MODE_MISMATCH | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_FOUND | 404 |
| ERR_METHOD_NOT_ALLOWED | 405 |
| ERR_INTERNAL | 500 |

The final three identifiers come from the routing layer rather than from any workflow of §2–§3: a request whose path matches no endpoint yields `ERR_NOT_FOUND`, a matched path with an unsupported method yields `ERR_METHOD_NOT_ALLOWED`, and an unexpected server failure yields `ERR_INTERNAL`.

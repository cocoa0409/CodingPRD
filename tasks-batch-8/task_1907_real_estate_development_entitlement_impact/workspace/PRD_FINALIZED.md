# Real Estate Entitlement API — Product Requirements Document

## 1. Introduction

Entitlement work lives and dies on statutory time. A development team assembling a land-use application must coordinate submittal packages, staff review comment cycles, public hearing logistics, and community outreach while a permit-streamlining clock runs in the background; a single missed deadline or an improperly sequenced permit can void months of work. On the municipal side of the table, staff must calculate impact fees defensibly, credit prior uses and in-lieu improvements without double-counting, honor fee-schedule vesting granted through development agreements, and survive appeals and referendum petitions without losing the thread of what was decided, when, and by whom.

This document specifies the Real Estate Entitlement API, mounted under `/entitlement`, which governs that entire lifecycle: project intake and application assembly, submittal with fee-schedule vesting pins, review rounds and opposition scoring, hearing scheduling under statutory notice rules, decision rendering under segregation of duties, provisional and final impact-fee assessment with payment, deferral, and refund handling, development-agreement vesting and referendum exposure, appeal processing with remand, conditions of approval, and rank-ordered permit issuance. The API is the system of record for every state transition, dollar amount, and deadline in the process, and it is written for the engineers who will implement it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party acts. A request missing either header, or declaring a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (401). Once authenticated, the declared role must be authorized for the target operation; otherwise the request fails with `ERR_FORBIDDEN` (403). Four roles are recognized, spelled exactly as follows: `PlatformAdmin`, `Applicant`, `StaffReviewer`, and `DecisionAuthority`.

- A `PlatformAdmin` is the system operator: it registers reference data (fee schedules, applicants, staff reviewers, and decision authorities), drives the logical clock, may create projects on behalf of an applicant, and may file referendum petitions or appeals on behalf of any party. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- An `Applicant` is a developer entity that owns projects through `applicant_id` and acts on its own applications: creating and submitting applications, responding to review comments, recording outreach, paying and deferring fees, and requesting permit slots. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting Applicant; ownership checks on any resource that references an Applicant compare the resource's foreign-key field to `X-User-ID`.
- A `StaffReviewer` is planning staff: opening review, authoring review comments, scheduling and managing hearings, advancing applications toward decision, and issuing permits. When `X-User-Role` is `StaffReviewer`, `X-User-ID` is the `id` of the acting StaffReviewer, and any resource that references a StaffReviewer compares that foreign-key field to `X-User-ID`.
- A `DecisionAuthority` is the planning commission, city council, or staff director: rendering decisions, drafting and adopting development agreements, certifying referendum petitions, adding and waiving conditions of approval, and resolving appeals. When `X-User-Role` is `DecisionAuthority`, `X-User-ID` is the `id` of the acting DecisionAuthority, and references to a DecisionAuthority compare against `X-User-ID`.

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

### 2.3. Pagination and Collection Filtering

List endpoints accept two pagination query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Most collections also expose filters that mirror their foreign keys or workflow state. Fee schedules filter by `status`; projects filter by `applicant_id`; applications filter by `project_id`, `status`, or `pinned_fee_schedule_id`; review comments filter by `status`, `severity`, `application_id`, `reviewer_id`, or `revises_comment_id`; conditions filter by `status`, `required_before`, or `application_id`; assessments filter by `variant`, `status`, `application_id`, or `fee_schedule_id`; payments filter by `assessment_id`; outreach events, hearings, development agreements, appeals, and permit sequences each filter by `application_id`; referendum petitions filter by `development_agreement_id`; and decisions filter by `application_id` or `decided_by`. Filters combine with pagination rather than replacing it.

### 2.4. Resource Identity, Timestamps, and Change Tracking

Every resource in this API — fee schedules, applicants, reviewers, authorities, projects, applications, comments, outreach events, hearings, conditions, assessments, payments, development agreements, petitions, appeals, decisions, and permit sequence rows — carries the same four system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource.

No entity in this domain is exempt: all seventeen resource types carry the full quadruple. Mutations performed automatically by the server — for example the version bump a project receives when it gains an application, or the `updated_at` refresh an application receives when a review comment is posted against it — count as modifications and follow the same rules.

### 2.5. Hierarchical Path Resolution

Nested endpoints validate their path identifiers strictly from left to right. A request to `/entitlement/applications/{appId}/hearings` first confirms that the application identified by `appId` exists, and only then proceeds; a request that chains further, such as one resolving a payment under `/entitlement/assessments/{assessmentId}/payments`, validates the assessment before considering any child. The first identifier that does not resolve to an existing resource aborts the request with `ERR_NOT_FOUND` (404), and no later identifier is examined. This ordering is deliberate: an unknown parent masks everything beneath it, and clients can rely on the leftmost failure being reported first.

### 2.6. Monetary Precision and Rounding Discipline

All fee arithmetic uses decimal math, and every dollar figure the API stores or returns — fee rates, category gross and credit amounts, assessment totals, payment amounts, late fees, outstanding balances — is expressed with exactly 2 decimal places using round-half-up rounding. One rule deserves emphasis because it changes totals: impact-fee assessments round each category's net to cents first and only then sum the rounded category nets into the assessment total. Summing unrounded nets and rounding once at the end is not equivalent and is not acceptable. Rate fields supplied on a fee schedule are preserved at input precision, and all monetary values appear in responses as JSON numbers, never strings.

### 2.7. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, each keyed to the version of a parent entity the client last observed.

Creating an application requires the request to carry `expected_project_version`, the client's last observed `version` of the parent project. If the project's current `version` has advanced since that observation — perhaps because another writer changed the unit counts or the land-use type — the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), forcing the client to re-read the project and base the new application on its current definition.

Rendering a decision requires the request to carry `expected_application_version`, the decision-maker's last observed `version` of the application. If the application's version has advanced in the meantime — a new blocking comment, a posture flip from fresh outreach — the render is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), forcing re-review of the record as it now stands.

No other endpoint accepts a version field. Endpoints not named above must not receive `expected_project_version`, `expected_application_version`, or any analogous parameter.

### 2.8. The Logical Clock and Statutory Time

Statutory deadlines in this domain — notice periods, appeal windows, referendum windows, the decision deadline, vesting expiry — are all evaluated against a server-side logical clock, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and an unset clock continues to read exactly that default. A `PlatformAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant; advancing the clock also advances any system transitions that depend on it, such as a development agreement's vesting maturing once the referendum window lapses, or a rendered decision becoming final once its appeal deadline has passed.

### 2.9. Validation Order of Precedence

Malformed request bodies — a missing required field, a type mismatch, or an enum value outside its declared set — are rejected with `ERR_INVALID_REQUEST` (400). Beyond request shape, every operation passes through eight ordered validation gates, and a failure at an earlier gate masks every later check:

1. **Authentication.** `X-User-ID` and `X-User-Role` are present and the role is declared, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The role is permitted on this endpoint per the role matrix, else `ERR_FORBIDDEN` (403).
3. **Existence.** Path identifiers resolve left to right, else `ERR_NOT_FOUND` (404).
4. **State.** The target entity sits in a state from which the requested transition is declared, else `ERR_INVALID_STATE` (409); an entity already in a terminal state accepts no further transitions and reports `ERR_ALREADY_TERMINAL` (409).
5. **Statutory and temporal windows.** Notice lead, appeal window, referendum window, decision deadline, and vesting window checks on hearing scheduling and re-notice, appeal filing and resolution, referendum filing and certification, decision rendering, and permit issuance. Violations report `ERR_TEMPORAL_WINDOW_VIOLATION` (422), refined per endpoint by `ERR_INSUFFICIENT_NOTICE`, `ERR_APPEAL_WINDOW_CLOSED`, `ERR_REFERENDUM_WINDOW_CLOSED`, `ERR_DECISION_DEADLINE_PASSED`, and `ERR_VESTING_LAPSED`.
6. **Cross-entity referential preconditions.** Reviewer-discipline match, revision targets, segregation of duties, and ownership checks on review comments, decisions, payments, and withdrawals. Violations report `ERR_REFERENTIAL_VIOLATION` (422), refined by `ERR_SEGREGATION_OF_DUTIES`, `ERR_DISCIPLINE_MISMATCH`, `ERR_REVISION_MISMATCH`, and `ERR_NOT_PROJECT_OWNER`.
7. **Aggregate and structural constraints.** Open blocking comments, pending hearings, permit sequence ranks, and unsatisfied conditions on advancement and permit issuance. Violations report `ERR_CONSTRAINT_VIOLATION` (409).
8. **Fiscal checks.** Assessments settled or deferred before permit issuance, and payment amounts held within the outstanding balance. Violations report `ERR_FEES_UNPAID` (402).

## 3. Business Logic & Workflows

### 3.1. Reference Data: Fee Schedules and the Municipal Registry

Everything downstream depends on reference data that a `PlatformAdmin` registers up front. A **fee schedule** is created in `DRAFT` status with a human-readable `schedule_label` such as "FY2026 Adopted", an `effective_date` marking when the schedule takes effect, and ten rates: five residential rates expressed as dollars per dwelling unit — `rate_transportation_res`, `rate_parks_res`, `rate_fire_res`, `rate_water_res`, and `rate_sewer_res` — and five commercial rates expressed as dollars per 1,000 square feet of floor area — `rate_transportation_com`, `rate_parks_com`, `rate_fire_com`, `rate_water_com`, and `rate_sewer_com`. Adoption moves a schedule from `DRAFT` to `ADOPTED`, and the act of adopting automatically moves whatever schedule was previously `ADOPTED` to `SUPERSEDED`, preserving it in the historical record while clearing the way for the new incumbent.

Three registries support the workflow's actors. An applicant is registered with its `legal_name` and `contact_email`. A staff reviewer is registered with a `full_name` and a `disciplines` array listing every discipline in which that reviewer may author comments. A decision authority is registered with a `full_name` and a `body` of `PLANNING_COMMISSION`, `CITY_COUNCIL`, or `STAFF_DIRECTOR`.

### 3.2. Projects and Application Assembly

A development engagement begins with an **entitlement project**, created by an `Applicant` — or by a `PlatformAdmin` acting on the applicant's behalf — with a `project_name`, the owning `applicant_id`, and a `land_use_type` of `RESIDENTIAL` or `COMMERCIAL`. The project's physical program follows its type: a residential project declares `dwelling_units` and may designate some of them as `affordable_units` (never negative, never more than the total unit count), while a commercial project declares its gross `floor_area_sqft`; the inapplicable measure is simply zero — a commercial project reports zero dwelling units and a residential project reports zero floor area. The project may also carry a `prior_use_basis`, a per-category record of prior demand on the site (for example, twenty TRANSPORTATION trips' worth of previous use) whose units match the project's land-use type, which later grounds fee credits. A new project starts in `ACTIVE` status; its declared status vocabulary also includes `WITHDRAWN` and `COMPLETE`.

Against an active project, an `Applicant` assembles an **entitlement application** by naming the `project_id`, choosing an `application_type` of `REZONE`, `CONDITIONAL_USE`, or `PLANNED_DEVELOPMENT`, and supplying the `submittal_package` — the array of required document keys, such as SITE_PLAN, TRAFFIC_STUDY, and ENVIRONMENTAL, that constitutes a complete filing. Because the application must be drafted against the project as the client last saw it, the create call carries `expected_project_version` under the optimistic-concurrency rule of §2.7; a stale observation is refused with `ERR_STALE_PROJECT_VERSION`. Successfully adding an application is itself a modification of the project: the project's `version` increments by one. Applications are born in `DRAFT` status, free to be revised until formally submitted.

### 3.3. Submittal: The Vesting Pin and the Provisional Assessment

Submission is the moment the statutory machinery engages. When an `Applicant` submits a `DRAFT` application, three preconditions guard the transition to `SUBMITTED`: the `submittal_package` must be non-empty and contain its required document keys, else `ERR_INCOMPLETE_PACKAGE`; the parent project must still be `ACTIVE`, else `ERR_PROJECT_NOT_ACTIVE`; and at least one fee schedule must be `ADOPTED` at that moment, else `ERR_NO_ADOPTED_FEE_SCHEDULE`.

A successful submission pins the fee schedule. The application records as `pinned_fee_schedule_id` the `ADOPTED` schedule with the latest `effective_date`, breaking any tie by earliest `created_at` — this pin is the application's vesting anchor. The same event stamps `decision_due_date` as 90 days after the submission instant, the permit-streamlining deadline staff must beat, and initializes `opposition_score` to zero with `opposition_posture` at `LOW`.

Submission also produces the application's first **impact fee assessment**, a `PROVISIONAL`-variant record whose totals are mirrored back onto the application as `provisional_fee_total`. The assessment works category by category across the five fee categories — TRANSPORTATION, PARKS, FIRE, WATER, and SEWER — using the pinned schedule. For each category, the demand basis derives from the parent project: a `RESIDENTIAL` project contributes its `dwelling_units`, while a `COMMERCIAL` project contributes its `floor_area_sqft` divided by 1,000, matching the per-thousand-square-feet basis of the commercial rates. The applicable rate is the schedule's rate for that category and that land-use type. Residential projects receive an affordable-housing exemption in exactly two categories, TRANSPORTATION and PARKS, where the effective basis is `dwelling_units` minus `affordable_units` rather than the full unit count. Each category's gross fee is its effective basis multiplied by its rate.

Two credits then stack, in a fixed order. The prior-use credit for a category is the smaller of two quantities: the project's `prior_use_basis` entry for that category multiplied by the category rate, or the category gross itself — and a category absent from `prior_use_basis` contributes a basis of zero. The improvement credit for a category is the smaller of the application's `improvement_credits` entry for that category — the dollar value of approved in-lieu improvements, which an applicant may optionally declare on the application — or the gross that remains after the prior-use credit, so the two credits together can never exceed the gross; a category absent from `improvement_credits` contributes zero. Each category's net is its gross minus both credits, rounded half-up to two decimal places, and — per §2.6 — the category nets are rounded first and only then summed into `net_total`. The assessment exposes the per-category arithmetic as `category_lines`, each line carrying its `category`, `gross`, `prior_use_credit`, `improvement_credit`, and `net`, and sums the columns into `gross_total`, `prior_use_credit_total`, and `improvement_credit_total`. Every assessment carries the `fee_schedule_id` actually used, a `due_date` — for the provisional variant, the instant the application was submitted — an `outstanding_balance` of `net_total` minus the sum of `applied_amount` across payments that have not been refunded, and a `status` that begins at `OPEN`.

### 3.4. Staff Review and Comment Cycles

A `StaffReviewer` opens the review, moving the application from `SUBMITTED` to `UNDER_REVIEW`; attempting to open review from any other state is `ERR_INVALID_STATE`. Review then proceeds in comment rounds. A reviewer authors a **review comment** by supplying their `reviewer_id`, a `discipline` of TRANSPORTATION, PARKS, FIRE, WATER, SEWER, or PLANNING, the `comment_text`, and a `severity` of `INFO`, `REQUIRED`, or `BLOCKING`. Two referential guards apply at authoring time: the comment's `discipline` must appear in the authoring reviewer's registered `disciplines`, else `ERR_DISCIPLINE_MISMATCH`; and an optional `revises_comment_id` may mark the new comment as superseding an earlier one, but only when the target belongs to the same application and the same discipline — a cross-application or cross-discipline target is refused with `ERR_REVISION_MISMATCH`. Comments may only be posted while the application is `UNDER_REVIEW`, and posting keeps it there: each new batch of comments is a fresh round, recorded on the new comments as an incremented `round_number`, and the application's `updated_at` is bumped on each posting. Every comment is born `OPEN`.

Disposition of a comment is shared between the parties. While the application remains `UNDER_REVIEW`, the applicant answers a comment by marking it `ADDRESSED`. The authoring reviewer — and only that reviewer — then either verifies an `ADDRESSED` comment, moving it to `VERIFIED`, or waives an `OPEN` comment outright, moving it to `WAIVED`. `VERIFIED` and `WAIVED` are terminal; `OPEN` and `ADDRESSED` comments still demand resolution.

### 3.5. Community Outreach, Opposition Posture, and Public Hearings

Community sentiment is tracked as an append-only log of **outreach events**, which either a `StaffReviewer` or the `Applicant` may record with an `event_date`, a `disposition` of `SUPPORT`, `NEUTRAL`, `OPPOSE`, or `ORGANIZED_OPPOSITION`, and an informational `attendee_count` of at least one. Each event's disposition maps to a `weight`: `SUPPORT` contributes −2, `NEUTRAL` contributes 0, `OPPOSE` contributes +5, and `ORGANIZED_OPPOSITION` contributes +12. Recording an event immediately recomputes the application's `opposition_score` — the sum of weights across every event ever recorded for it — and its `opposition_posture`: the posture is `LOW` when the score is below 10, `ELEVATED` when the score is at least 10 but below 30, and `HIGH` when the score reaches 30. The thresholds are inclusive at their lower bound, so a score of exactly 10 is `ELEVATED` and exactly 30 is `HIGH`. Posture is not cosmetic: an application whose posture stands at `HIGH` cannot be decided administratively and must pass through a held public hearing before approval.

Hearings are scheduled by a `StaffReviewer` against an application in `UNDER_REVIEW`, and the act of scheduling moves the application to `HEARING_SCHEDULED`. Scheduling is refused while any `BLOCKING` review comment remains `OPEN` — `ERR_BLOCKING_COMMENTS_OPEN` — and the new hearing must satisfy the statutory notice lead: its `hearing_date` must fall at least 20 days after its `notice_posted_date`, where exactly 20 days satisfies the rule and 19 days is rejected with `ERR_INSUFFICIENT_NOTICE`. The hearing is also assigned a `hearing_body` of `PLANNING_COMMISSION` or `CITY_COUNCIL` and begins life `SCHEDULED`.

From `SCHEDULED`, a hearing has three exits. Once the logical clock reaches the `hearing_date` — the boundary instant itself counts — staff mark the hearing `HELD`; attempting to mark it held before that date fails with `ERR_HEARING_NOT_YET`, and marking a hearing held leaves the application parked in `HEARING_SCHEDULED` until someone advances it. Alternatively staff may continue the hearing to a `new_hearing_date`, moving it to `CONTINUED`; a continued hearing is not terminal, and its notice must be re-validated against the new date. Returning a `CONTINUED` hearing to `SCHEDULED` requires a re-notice carrying a fresh `hearing_date` and `notice_posted_date` pair that again satisfies the 20-day lead. Finally, staff may cancel a `SCHEDULED` hearing outright, moving it to `CANCELLED`.

### 3.6. Advancement, the Decision, and the Final Assessment

Advancement to `DECISION_PENDING` is the gate that clears the record for a ruling, and a `StaffReviewer` may advance the application from either `UNDER_REVIEW` or `HEARING_SCHEDULED`. From either origin, every `BLOCKING` review comment must stand in `VERIFIED` or `WAIVED` — a comment merely `ADDRESSED` but not yet verified still blocks, and the rejection is `ERR_BLOCKING_COMMENTS_OPEN`. From either origin, no hearing may remain `SCHEDULED`: any scheduled hearing must first be held or cancelled, else `ERR_HEARING_PENDING`. And from either origin, an application whose `opposition_posture` is `HIGH` must already have at least one hearing in `HELD` status, else `ERR_HEARING_REQUIRED`.

The decision itself is rendered by a `DecisionAuthority` supplying a `decision` of `APPROVE` or `DENY` and a `decided_by` naming the rendering authority, under the application's optimistic-concurrency rule — `expected_application_version` must match the application's current `version`, else `ERR_STALE_APPLICATION_VERSION`. Rendering is only possible from `DECISION_PENDING`, else `ERR_INVALID_STATE`. Two further guards apply regardless of which way the ruling goes: segregation of duties forbids the rendering authority from being any staff reviewer who authored a review comment on this application — a violation is `ERR_SEGREGATION_OF_DUTIES` — and the statutory clock forbids rendering after `decision_due_date`. A render attempted after that deadline is rejected with `ERR_DECISION_DEADLINE_PASSED`; rendering exactly on the deadline remains permitted, and although entitlement practice tolls the deadline while a development agreement stands in `DRAFT` or `ADOPTED`, this API pins the stricter contract — a late render is simply rejected, and an applicant seeking approval-by-operation-of-law must pursue it through the appeal path. Approval carries one additional precondition of its own: when `opposition_posture` is `HIGH`, the decision must come through a hearing — `via_hearing` must be true — else `ERR_HEARING_REQUIRED`.

A rendered decision is recorded as an **entitlement decision** in `RENDERED` status, stamped with its `decision_effective_date` — the date the ruling takes effect and the appeal window opens — and its `appeal_deadline`, computed as the effective date plus the `APPEAL_WINDOW_DAYS` window. The decision's `via_hearing` flag records whether the ruling followed a `HELD` public hearing (true) or was administrative (false). Rendering a decision is a modification of the application: its `version` increments by one.

The two rulings diverge in their consequences. On `APPROVE`, the application moves to `APPROVED`, and the system computes `final_fee_total` by running the impact-fee assessment a second time with variant `FINAL`, creating (or updating) a `FINAL` assessment whose `due_date` is the decision's effective date. Schedule selection for the final run follows the vesting rule: if a development agreement with `vesting_status` of `VESTED` covers the application and the logical clock is on or before its `vesting_expires_at` — the boundary instant itself remains vested — the final assessment still uses the pinned schedule; otherwise it uses the `ADOPTED` schedule with the latest `effective_date` at computation time, which may differ from the pinned schedule and produce a different `net_total` for identical project data, and requesting vested treatment after the vesting window has closed is rejected with `ERR_VESTING_LAPSED`. Approval creates no conditions automatically; each condition of approval is added explicitly by a `DecisionAuthority`. On `DENY`, the application moves to `DENIED`, the recorded decision carries the denial, and every fee assessment still `OPEN` or `PARTIALLY_PAID` is moved to `REFUNDED` — the provisional assessment is voided and its payments refunded.

### 3.7. Fee Payment, Late Charges, Deferral, and Refund

Payment is an applicant activity against a specific assessment: the applicant tenders an `amount` — strictly greater than zero — and a `paid_at` timestamp, and the system records a **fee payment**. A payment may not exceed the assessment's outstanding balance; an overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`. Each payment carries two computed figures. The `applied_amount` always equals the tendered `amount` — principal is never reduced by fees — and the `late_fee` compensates the city for tardiness: when `paid_at` falls after the assessment's `due_date`, the days late are the whole-day difference between the two instants, floored at zero; the full months late are the whole 30-day months contained in that span; and the late fee is the tendered `amount` multiplied by 1.5 percent for each full month, rounded half-up to two decimal places. A payment 29 days late therefore incurs no late fee at all, while a payment 30 days late incurs 1.5 percent of that payment's amount. The late fee is charged in addition to the amount tendered, never netted from it.

Payments drive the assessment's lifecycle. While the cumulative applied total remains below `net_total`, a payment moves the assessment from `OPEN` to `PARTIALLY_PAID` and recomputes the `outstanding_balance`; when a payment brings the cumulative `applied_amount` to or above `net_total`, the assessment moves from `PARTIALLY_PAID` to `PAID`. Reaching `PAID` matters beyond bookkeeping: once the application stands `APPROVED` and every `PERMIT_ISSUANCE` condition is satisfied, a paid final assessment is what makes the first permit slot eligible to unblock.

Deferral reschedules rather than settles. An applicant may defer an assessment from `OPEN`, `PARTIALLY_PAID`, or even `PAID` to `DEFERRED`, moving its payment due date to the certificate-of-occupancy milestone; where the assessment was previously `PAID`, the prior payments remain recorded as credit toward the deferred balance. Deferral's two preconditions are checked in a fixed order — the permit check first, then the variant check: if any permit sequence row for the application already stands `ISSUED`, the request is refused with `ERR_PERMIT_ALREADY_ISSUED` (so a premature permit surfaces that error rather than being masked by a variant complaint), and only then does the variant rule apply, under which a `PROVISIONAL` assessment can never be deferred — attempting it is `ERR_INVALID_STATE`. Refund, finally, is never a client action: when an application is denied or withdrawn, every assessment of that application standing `OPEN` or `PARTIALLY_PAID` is moved to `REFUNDED` by the system, and every payment against it is marked refunded with its `applied_amount` reversed.

### 3.8. Development Agreements, Vesting, and Referendum Risk

A **development agreement** is the instrument that trades public commitments for fee certainty. A `DecisionAuthority` drafts one on an approved application — the parent application must stand `APPROVED` at drafting time, else `ERR_APPLICATION_NOT_APPROVED` — by supplying an `agreement_number` — the ordinance or resolution number — an `adoption_date`, a `vesting_term_years` of at least 1 and at most 15, and the `registered_voters` count recorded at adoption, which must be greater than zero and later grounds the referendum threshold. The agreement is born in `DRAFT`. Adoption, again by a `DecisionAuthority`, requires the parent application to stand `APPROVED` — else `ERR_APPLICATION_NOT_APPROVED` — and moves the agreement to `ADOPTED`, setting its `vesting_status` to `PENDING_REFERENDUM` and fixing its `referendum_deadline` at the `adoption_date` plus the `REFERENDUM_WINDOW_DAYS` window. The agreement's `vesting_expires_at` is the `adoption_date` plus `vesting_term_years` years, and the vested fee schedule governs only while `vesting_status` is `VESTED` and the logical clock has not passed `vesting_expires_at` — the expiry instant itself still counts as vested. The full `vesting_status` vocabulary is `PENDING_REFERENDUM`, `VESTED`, `LAPSED`, and `INVALIDATED`.

The referendum window is the agreement's period of maximum exposure. While it runs, any party — an `Applicant`, or a `PlatformAdmin` filing on someone's behalf — may file a **referendum petition** against the agreement, recording its `filed_at` and the certified `valid_signature_count` (zero or more). A petition begins in `FILED` status and ends in one of `CERTIFIED_QUALIFIED`, `CERTIFIED_INSUFFICIENT`, or `REJECTED_UNTIMELY`. The petition's `required_signature_count` is computed from the parent agreement as ten percent of `registered_voters`, with the raw decimal product rounded up to a whole signature before any comparison, and its `qualifies` flag is true exactly when `valid_signature_count` reaches the requirement — a count equal to the requirement qualifies, one short does not. A petition whose `filed_at` falls on or after the `referendum_deadline` is outside the window and the filing is refused with `ERR_REFERENDUM_WINDOW_CLOSED`.

Certification, performed by a `DecisionAuthority`, disposes of a filed petition in one of three ways. A petition whose `filed_at` is on or after the referendum deadline is disposed as `REJECTED_UNTIMELY`. A timely petition whose valid signatures reach the requirement is disposed as `CERTIFIED_QUALIFIED`, and qualification detonates the agreement: the parent development agreement moves to `REPEALED` and its `vesting_status` to `INVALIDATED`. A timely petition whose count falls short is disposed as `CERTIFIED_INSUFFICIENT`; the certification request itself fails with `ERR_INSUFFICIENT_SIGNATURES` (422), and the disposition is applied all the same — the petition stands `CERTIFIED_INSUFFICIENT` after the failed request.

Should the window lapse with no qualifying petition, the agreement matures to `EFFECTIVE` — either automatically when the logical clock reaches the `referendum_deadline`, or at the hand of a `DecisionAuthority` finalizing vesting — provided the clock has in fact reached the deadline and no petition stands `CERTIFIED_QUALIFIED`; maturation sets `vesting_status` to `VESTED`. From that point the application's final fee obligations are computed against the pinned schedule for the remainder of the vesting term.

### 3.9. Appeals, Conditions of Approval, and Permit Sequencing

A rendered decision may be appealed. An **appeal** is filed by an `Applicant` — or a `PlatformAdmin` on a party's behalf — with an `appellant_name`, a `filed_at`, and the `grounds` for relief. Filing inside the window moves the decision from `RENDERED` to `STAYED_ON_APPEAL`; a filing whose `filed_at` falls on or after the decision's `appeal_deadline` is refused with `ERR_APPEAL_WINDOW_CLOSED`. A decision with no appeal pending also finalizes on its own: once the logical clock reaches the `appeal_deadline` and no appeal for the application stands `FILED`, the decision moves from `RENDERED` to `FINAL`.

Resolution of an appeal lies with a `DecisionAuthority`, who supplies a `ruling`. A timely appeal ruled `UPHELD` moves the appeal to `UPHELD` and exhausts the challenge — the decision moves to `FINAL`. A timely appeal ruled `REVERSED` moves the appeal to `REVERSED`, drives the decision to `REVERSED_ON_APPEAL`, and remands the application to `DECISION_PENDING` for re-decision; when the remanded application is approved again, its `FINAL` assessment is recomputed under the vesting rule then in force. An appeal whose `filed_at` was on or after the appeal deadline is resolved as `DISMISSED_UNTIMELY`, and the decision likewise moves to `FINAL`.

Approval's obligations are tracked as **conditions of approval**, each added explicitly by a `DecisionAuthority` at or after approval with its `condition_text`, a `category` of `FEE`, `IMPROVEMENT`, `DESIGN`, or `ENVIRONMENTAL`, and a `required_before` milestone of `PERMIT_ISSUANCE`, `CERTIFICATE_OF_OCCUPANCY`, or `FINAL_INSPECTION`. A condition begins `PENDING`. The applicant satisfies it — permitted only while the parent application stands `APPROVED` — which stamps `satisfied_at` with the current instant and moves the condition to `SATISFIED`; a `DecisionAuthority` may instead waive a `PENDING` condition to `WAIVED`. Should a permit ever be issued while a `PERMIT_ISSUANCE` condition still stands `PENDING`, the system marks that condition `BREACHED` and flags the application for enforcement action.

Permit issuance is the last gate. The applicant requests a **permit sequence** slot by naming a `permit_type` of `GRADING`, `BUILDING`, `UTILITY`, or `OCCUPANCY`; the system stamps `requested_at`, derives the `sequence_rank` from the type — `GRADING` ranks 1, `BUILDING` and `UTILITY` both rank 2, and `OCCUPANCY` ranks 3 — and records the request as `REQUESTED`, or as `BLOCKED` when the issuance preconditions already fail at request time. Issuance itself is performed by a `StaffReviewer` and runs its checks in order: the parent application must stand `APPROVED`, else `ERR_APPLICATION_NOT_APPROVED`; the parent decision must stand `FINAL` — the appeal window lapsed or the appeal resolved — else `ERR_APPEAL_WINDOW_OPEN`; every permit sequence row of lower `sequence_rank` for the same application must already be `ISSUED` — so `BUILDING` and `UTILITY`, sharing rank 2, do not order against each other but each requires `GRADING`, and `OCCUPANCY` requires all of ranks 1 and 2 — else `ERR_SEQUENCE_VIOLATION`; no condition with `required_before` of `PERMIT_ISSUANCE` may still stand `PENDING`, else `ERR_CONDITIONS_PENDING`; and the `FINAL` assessment must stand `PAID` or `DEFERRED`, else `ERR_FEES_UNPAID`. Deferral carries one caveat at this gate: it excuses payment only until the occupancy milestone, so `GRADING`, `BUILDING`, and `UTILITY` may issue against a `DEFERRED` assessment, but an `OCCUPANCY` permit requires the assessment actually `PAID` — requesting occupancy issuance while the deferred balance stands unpaid is again `ERR_FEES_UNPAID`. A successful issuance stamps `issued_at` and moves the slot to `ISSUED`.

Withdrawal is the applicant's exit. From `SUBMITTED`, `UNDER_REVIEW`, `HEARING_SCHEDULED`, or `DECISION_PENDING`, the applicant may withdraw the application — but only the applicant who owns the parent project: the `X-User-ID` must equal the project's `applicant_id`, else `ERR_NOT_PROJECT_OWNER`. Withdrawal cascades: every assessment standing `OPEN` or `PARTIALLY_PAID` is refunded under the rule of §3.7, every `SCHEDULED` hearing is moved to `CANCELLED`, and every `PENDING` condition of approval is moved to `WAIVED` as moot. `APPROVED`, `DENIED`, and `WITHDRAWN` are the application's terminal states.

## 4. Endpoint Definitions

Operations that create a new resource — a project, an application, a comment, an outreach event, a hearing, a decision, a condition, a payment, a development agreement, a petition, an appeal, a permit sequence request, or any registry entry — return `201 Created`. Operations that transition or otherwise modify an existing resource return `200 OK`, as does the clock-setting capability. The narratives of §3 carry the request fields and side effects for each operation; this table is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/entitlement/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/entitlement/fee-schedules` | Create a fee schedule (DRAFT) | PlatformAdmin |
| POST | `/entitlement/fee-schedules/{fsId}/adopt` | Adopt a fee schedule; supersedes the incumbent | PlatformAdmin |
| GET | `/entitlement/fee-schedules/{fsId}` | Get a fee schedule | All roles |
| GET | `/entitlement/fee-schedules` | List fee schedules | All roles |
| POST | `/entitlement/applicants` | Register an applicant | PlatformAdmin |
| GET | `/entitlement/applicants/{applicantId}` | Get an applicant | All roles |
| POST | `/entitlement/staff-reviewers` | Register a staff reviewer | PlatformAdmin |
| GET | `/entitlement/staff-reviewers/{reviewerId}` | Get a staff reviewer | PlatformAdmin, StaffReviewer, DecisionAuthority |
| POST | `/entitlement/decision-authorities` | Register a decision authority | PlatformAdmin |
| GET | `/entitlement/decision-authorities/{authorityId}` | Get a decision authority | PlatformAdmin, StaffReviewer, DecisionAuthority |
| POST | `/entitlement/projects` | Create an entitlement project | Applicant, PlatformAdmin |
| GET | `/entitlement/projects/{projectId}` | Get a project | All roles |
| GET | `/entitlement/projects` | List projects | All roles |
| POST | `/entitlement/applications` | Create an application (DRAFT); OCC on project version | Applicant |
| GET | `/entitlement/applications/{appId}` | Get an application | All roles |
| GET | `/entitlement/applications` | List applications (filterable) | All roles |
| POST | `/entitlement/applications/{appId}/submit` | Submit; pins fee schedule, computes provisional fee, stamps deadline | Applicant |
| POST | `/entitlement/applications/{appId}/open-review` | Open staff review (SUBMITTED → UNDER_REVIEW) | StaffReviewer |
| POST | `/entitlement/applications/{appId}/advance-to-decision` | Advance to DECISION_PENDING once blockers clear | StaffReviewer |
| POST | `/entitlement/applications/{appId}/withdraw` | Withdraw; cascades to assessments, hearings, conditions | Applicant |
| POST | `/entitlement/applications/{appId}/review-comments` | Post a review comment (new review round) | StaffReviewer |
| GET | `/entitlement/applications/{appId}/review-comments` | List an application's review comments | All roles |
| GET | `/entitlement/review-comments/{commentId}` | Get a review comment | All roles |
| POST | `/entitlement/review-comments/{commentId}/address` | Applicant marks a comment addressed | Applicant |
| POST | `/entitlement/review-comments/{commentId}/verify` | Authoring reviewer verifies an addressed comment | StaffReviewer |
| POST | `/entitlement/review-comments/{commentId}/waive` | Authoring reviewer waives an open comment | StaffReviewer |
| POST | `/entitlement/applications/{appId}/outreach-events` | Record an outreach event; recomputes opposition posture | StaffReviewer, Applicant |
| GET | `/entitlement/applications/{appId}/outreach-events` | List an application's outreach events | All roles |
| GET | `/entitlement/outreach-events/{eventId}` | Get an outreach event | All roles |
| POST | `/entitlement/applications/{appId}/hearings` | Schedule a public hearing | StaffReviewer |
| GET | `/entitlement/applications/{appId}/hearings` | List an application's hearings | All roles |
| GET | `/entitlement/hearings/{hearingId}` | Get a hearing | All roles |
| POST | `/entitlement/hearings/{hearingId}/mark-held` | Mark a hearing held | StaffReviewer |
| POST | `/entitlement/hearings/{hearingId}/continue` | Continue a hearing to a new date | StaffReviewer |
| POST | `/entitlement/hearings/{hearingId}/renotice` | Re-notice a continued hearing | StaffReviewer |
| POST | `/entitlement/hearings/{hearingId}/cancel` | Cancel a hearing | StaffReviewer |
| POST | `/entitlement/applications/{appId}/decisions` | Render a decision; OCC on application version; segregation of duties | DecisionAuthority |
| GET | `/entitlement/applications/{appId}/decisions` | List an application's decisions | All roles |
| GET | `/entitlement/decisions/{decisionId}` | Get a decision | All roles |
| POST | `/entitlement/applications/{appId}/conditions` | Add a condition of approval | DecisionAuthority |
| GET | `/entitlement/applications/{appId}/conditions` | List an application's conditions | All roles |
| GET | `/entitlement/conditions/{conditionId}` | Get a condition | All roles |
| POST | `/entitlement/conditions/{conditionId}/satisfy` | Mark a condition satisfied | Applicant |
| POST | `/entitlement/conditions/{conditionId}/waive` | Waive a condition | DecisionAuthority |
| GET | `/entitlement/applications/{appId}/assessments` | List an application's fee assessments | All roles |
| GET | `/entitlement/assessments/{assessmentId}` | Get an assessment | All roles |
| POST | `/entitlement/assessments/{assessmentId}/payments` | Record a fee payment | Applicant |
| GET | `/entitlement/assessments/{assessmentId}/payments` | List an assessment's payments | All roles |
| GET | `/entitlement/payments/{paymentId}` | Get a fee payment | All roles |
| POST | `/entitlement/assessments/{assessmentId}/defer` | Defer a FINAL assessment to certificate-of-occupancy | Applicant |
| POST | `/entitlement/applications/{appId}/development-agreements` | Draft a development agreement | DecisionAuthority |
| GET | `/entitlement/development-agreements/{daId}` | Get a development agreement | All roles |
| GET | `/entitlement/applications/{appId}/development-agreements` | List an application's development agreements | All roles |
| POST | `/entitlement/development-agreements/{daId}/adopt` | Adopt a development agreement; opens the referendum window | DecisionAuthority |
| POST | `/entitlement/development-agreements/{daId}/finalize-vesting` | Finalize vesting after the referendum window lapses | DecisionAuthority |
| POST | `/entitlement/development-agreements/{daId}/referendum-petitions` | File a referendum petition | Applicant, PlatformAdmin |
| GET | `/entitlement/development-agreements/{daId}/referendum-petitions` | List a development agreement's petitions | All roles |
| GET | `/entitlement/referendum-petitions/{petitionId}` | Get a referendum petition | All roles |
| POST | `/entitlement/referendum-petitions/{petitionId}/certify` | Certify a referendum petition | DecisionAuthority |
| POST | `/entitlement/applications/{appId}/appeals` | File an appeal against a rendered decision | Applicant, PlatformAdmin |
| GET | `/entitlement/applications/{appId}/appeals` | List an application's appeals | All roles |
| GET | `/entitlement/appeals/{appealId}` | Get an appeal | All roles |
| POST | `/entitlement/appeals/{appealId}/resolve` | Resolve an appeal | DecisionAuthority |
| POST | `/entitlement/applications/{appId}/permit-sequences` | Request a permit issuance slot | Applicant |
| GET | `/entitlement/applications/{appId}/permit-sequences` | List an application's permit sequences | All roles |
| GET | `/entitlement/permit-sequences/{seqId}` | Get a permit sequence row | All roles |
| POST | `/entitlement/permit-sequences/{seqId}/issue` | Issue a permit; enforces sequencing, conditions, fees, finality | StaffReviewer |
| GET | `/entitlement/review-comments` | Filtered list of review comments | All roles |
| GET | `/entitlement/outreach-events` | Filtered list of outreach events | All roles |
| GET | `/entitlement/hearings` | Filtered list of hearings | All roles |
| GET | `/entitlement/conditions` | Filtered list of conditions | All roles |
| GET | `/entitlement/assessments` | Filtered list of fee assessments | All roles |
| GET | `/entitlement/payments` | Filtered list of fee payments | All roles |
| GET | `/entitlement/development-agreements` | Filtered list of development agreements | All roles |
| GET | `/entitlement/referendum-petitions` | Filtered list of referendum petitions | All roles |
| GET | `/entitlement/appeals` | Filtered list of appeals | All roles |
| GET | `/entitlement/decisions` | Filtered list of decisions | All roles |
| GET | `/entitlement/permit-sequences` | Filtered list of permit sequences | All roles |

## 5. Error Code Catalogue

Trigger conditions for each code live in the narratives of §2 and §3, next to the workflow they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INCOMPLETE_PACKAGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROJECT_NOT_ACTIVE` | 409 |
| `ERR_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_TEMPORAL_WINDOW_VIOLATION` | 422 |
| `ERR_INSUFFICIENT_NOTICE` | 422 |
| `ERR_HEARING_NOT_YET` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_REFERENDUM_WINDOW_CLOSED` | 422 |
| `ERR_DECISION_DEADLINE_PASSED` | 422 |
| `ERR_VESTING_LAPSED` | 422 |
| `ERR_REFERENTIAL_VIOLATION` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_DISCIPLINE_MISMATCH` | 422 |
| `ERR_REVISION_MISMATCH` | 422 |
| `ERR_NOT_PROJECT_OWNER` | 403 |
| `ERR_CONSTRAINT_VIOLATION` | 409 |
| `ERR_BLOCKING_COMMENTS_OPEN` | 409 |
| `ERR_HEARING_REQUIRED` | 409 |
| `ERR_HEARING_PENDING` | 409 |
| `ERR_SEQUENCE_VIOLATION` | 409 |
| `ERR_CONDITIONS_PENDING` | 409 |
| `ERR_APPEAL_WINDOW_OPEN` | 409 |
| `ERR_PERMIT_ALREADY_ISSUED` | 409 |
| `ERR_INSUFFICIENT_SIGNATURES` | 422 |
| `ERR_FEES_UNPAID` | 402 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 402 |
| `ERR_NO_ADOPTED_FEE_SCHEDULE` | 422 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |

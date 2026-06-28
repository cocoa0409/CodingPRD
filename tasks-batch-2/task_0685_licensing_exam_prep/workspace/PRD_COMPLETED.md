# Licensing Exam Prep API — Product Requirements Document

## 1. Introduction

Candidates preparing for high-stakes professional licensure — the CPA exam, the NCLEX nursing boards, real-estate salesperson licensing, and similar credentials — rarely struggle for lack of content. They struggle to know whether they are *ready*. This API powers a licensing-exam-prep platform whose core promise is a defensible, data-driven readiness signal coupled with the commercial machinery that makes such preparation affordable: tiered subscriptions, interest-free financing, continuing-education bundles, live-review cohorts, and a money-back or retake "pass guarantee" for learners who study diligently yet fall short.

The platform is organized around the **enrollment** — a single learner's purchase of one subscription plan against one licensing program. An enrollment accumulates study activity (adaptive practice batches and full-length mock exams), tracks per-blueprint-domain mastery, derives two distinct readiness figures (a conservative gating score and an optimistic projected score), carries a financing ledger of installments, and ultimately receives an official exam outcome certified by a proctor. The guarantee, the refund arithmetic, the cohort scheduling, and the catalog governance all hang off this aggregate.

This document specifies the system's entities, their state machines, the calculations that keep derived figures consistent, the validation order that governs every mutating request, and the full endpoint and error contracts. Because correctness here has financial and reputational consequences — a misfired refund or an incorrectly granted guarantee is a real liability — the rules below are exact, and the reader is expected to implement them precisely as written rather than approximately.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `Learner`, `ContentAdmin`, `ExamProctor`, and `PlatformOps`.

When `X-User-Role` is `Learner`, `X-User-ID` is the `id` of the acting `Learner`; this role is entity-backed. Ownership checks on any resource that references a `Learner` compare the resource's owning learner to `X-User-ID`. Concretely, for any learner-scoped action on an enrollment or on resources nested beneath it — installments, practice sessions, mock exams, CE awards, cohort memberships — the `learner_id` of the owning `Enrollment` (or the `id` of the `Learner` itself for learner-record reads) must equal `X-User-ID`; otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`. A learner acting on someone else's enrollment is forbidden even though the role itself is permitted.

When `X-User-Role` is `ContentAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same is true when `X-User-Role` is `ExamProctor` and when `X-User-Role` is `PlatformOps`: both are opaque operator identifiers, recorded if useful but never matched against a stored entity id. `ContentAdmin` owns the catalog (programs, question items, plans, CE bundles, cohorts and their sessions). `ExamProctor` certifies official exam outcomes and decides pass-guarantee claims. `PlatformOps` exists solely to drive the logical clock used for deterministic test-driving.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless an endpoint explicitly states a different ordering, list results are sorted by their creation timestamp in ascending order. (The installment listing is the notable exception, and is always ordered by `sequence_no` ascending — see the financing narrative in §3.) Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (also ISO 8601 UTC, three fractional digits), refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by one on each subsequent mutation.

One entity is deliberately immutable and therefore carries *only* `id` and `created_at`: a `QuestionItem`. A question item has no `updated_at` and no `version` — its `correct_choice` and other content fields are fixed once written, so there is nothing to re-version. Every other entity in this system — programs, plans, CE bundles, cohorts, cohort sessions, learners, enrollments, installments, study-plan domains, practice sessions, mock exams, pass-guarantee claims, CE credit awards, and cohort memberships — carries the full `id`/`created_at`/`updated_at`/`version` quartet.

Recomputation of a derived field counts as a mutation. When an installment payment recomputes an enrollment's financing figures, or a practice session updates a domain's mastery and the enrollment's readiness, the affected resource's `updated_at` is refreshed and its `version` is incremented.

### 2.5. Validation Order

When a request could fail several checks at once, the system evaluates them in a fixed priority order and returns the first failure encountered. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role permission for the endpoint (`ERR_FORBIDDEN_ROLE`); third, existence of every resource named in the path or body, validated left-to-right along the path (`ERR_NOT_FOUND`); fourth, for learner-scoped actions, ownership of the targeted resource (`ERR_NOT_RESOURCE_OWNER`); fifth, well-formedness of the request body — required fields present, enum values legal, numeric ranges respected (`ERR_INVALID_REQUEST`); sixth, on the financing-restructure endpoint only, the optimistic-concurrency version match (`ERR_STALE_ENROLLMENT_VERSION`); and seventh, that the target resource is in a legal state for the requested transition (`ERR_INVALID_STATE`).

Beyond that shared prefix, each business operation layers on its own domain checks — referential compatibility, scheduling-window conflicts, guarantee eligibility, the outstanding-balance gate, cohort capacity, the empty-batch rejection, and CE-module monotonicity. Each is described with the workflow it guards in §3, and each maps to a specific error documented in §5. Where two such checks could both apply to one request, the relative order is called out alongside the workflow.

### 2.6. Nested Resource Retrieval

Many resources live beneath a parent in the URL hierarchy — installments, practice sessions, mock exams, CE awards, and study-plan domains beneath an enrollment; sessions and memberships beneath a cohort. For any such nested request, the server validates each identifier in the path from left to right and rejects with `ERR_NOT_FOUND` at the *first* identifier that does not resolve. A practice-session request under a non-existent enrollment fails on the enrollment before the session is ever consulted; a membership-drop under a missing cohort fails on the cohort first. The same left-to-right precedence governs creation and modification, so an operation never proceeds inside a container that does not exist.

### 2.7. Hierarchical Consistency and Cascades

The `Enrollment` is the aggregate root, and several of its lifecycle transitions cascade into the resources nested beneath it and into the cohorts it has joined. Whenever such a cascade fires, each entity it touches is independently mutated: the entity's status is updated, its `updated_at` is refreshed, and its `version` is incremented. A cohort that loses a member recomputes its `seats_taken` and may flip its own derived status. These cascades are specified in full alongside the transitions that trigger them in §3; the governing principle is that the system never leaves a parent and its dependents in mutually inconsistent states, and it performs the necessary downstream mutations itself without a separate client request on each affected resource.

### 2.8. Monetary Precision, Counts, and Rounding

All monetary amounts in this system are integer cents — `total_price_cents`, `amount_cents`, `financing_total_due_cents`, `financing_paid_cents`, `financing_balance_cents`, and `refund_amount_cents` are whole numbers of cents, never fractional. Scores and counts (`readiness_score`, `projected_readiness_score`, `scaled_score`, `batch_pct`, `mastery`, `cumulative_credits`, `credits_awarded`, and the various tallies) are likewise integers.

Wherever a calculation produces a non-integer intermediate that must be stored as an integer, the system rounds half up — a fractional part of exactly one-half rounds away from zero to the next whole unit. This applies to the down-payment computation, to scaled and batch percentages, to the EWMA mastery update, to per-installment refund amounts, and to cumulative CE credits. The exact point in each formula at which rounding occurs is pinned in the §3 calculation narratives, because in several places the *order* of rounding versus summation is observable and must be honored as written. A balance is never allowed to go negative: the financing balance is floored at zero.

### 2.9. Optimistic Concurrency on Financing Restructure

Exactly one operation in this system is guarded by optimistic concurrency control: restructuring an enrollment's financing schedule. The restructure operation rebuilds the enrollment's entire set of installments, superseding whatever schedule existed before. Because that wholesale replacement is destructive, the request must carry an `expected_enrollment_version` field — a non-optional input — holding the `version` of the `Enrollment` the client last observed. If that value does not match the enrollment's current `version` at the moment the server processes the request, the restructure is rejected with `ERR_STALE_ENROLLMENT_VERSION` and HTTP status 412. The interpretation is strictly stale-data, not timing: if any prior writer has already advanced the enrollment's version since the client read it, the client's picture of the schedule it intends to replace is out of date, and the platform refuses to let it overwrite a schedule it never saw. No other endpoint takes a version field, and no other mutation performs this check.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Programs, Items, Plans, and CE Bundles

The catalog is governed entirely by a `ContentAdmin`. Everything a learner can buy or study against originates here.

A **license program** is the blueprint for one credential. The admin creates it with a `license_code` (a unique identifier among programs, such as `CPA-FAR`, `NCLEX-RN`, or `RE-SALES`; a `license_code` that duplicates an existing program's is rejected as request well-formedness with `ERR_INVALID_REQUEST`), a human-readable `title`, an official `passing_scaled_score` integer that must lie between 0 and 100 inclusive, and a `domain_weights` array. Each entry of `domain_weights` pairs a `domain_code` with a `weight`, where every `weight` is a fraction strictly greater than zero, there is at least one entry, and the weights sum to exactly 1.00 measured to two decimals. These `domain_weights` constraints are enforced as request well-formedness at create time (per §2.5): a `domain_weights` value that is not a non-empty array, an entry that is not an object or lacks a non-empty `domain_code`, a `weight` that is not a number or is not strictly greater than zero, or a set of weights that does not sum to exactly 1.00 measured to two decimals is rejected with `ERR_INVALID_REQUEST`. A freshly created program is in `DRAFT` status. Only `PUBLISHED` programs accept new enrollments; `RETIRED` is the program's terminal status.

Before a program can serve learners, the admin populates its question bank. Each **question item** added to a program carries the program reference, a `domain_code` that must be one of the program's blueprint domain codes, a `difficulty` band of `EASY`, `MEDIUM`, or `HARD`, and the `correct_choice` answer key. A question item's `domain_code` that is not among the program's blueprint codes is a referential mismatch and is rejected with `ERR_REFERENCE_INCOMPATIBLE`. Question items are immutable content and, as noted in §2.4, carry no version. The full set of items belonging to a program can be listed back, optionally filtered by `domain_code`, which is also how a program's items are reached in reverse from a known `license_program_id`.

Publishing a `DRAFT` program advances it to `PUBLISHED` and increments the program's `version`. Two preconditions guard the transition. First, the `domain_weights` must be non-empty and sum to exactly 1.00; otherwise the publish is rejected with `ERR_BLUEPRINT_WEIGHTS_INVALID`. Second, at least one question item must exist for the program; a program with an empty bank is rejected with `ERR_PROGRAM_HAS_NO_ITEMS`. Retiring a program moves it from `PUBLISHED` to `RETIRED` and increments its `version`, but only when no enrollment that references the program is currently in `ACTIVE` status; if any active enrollment still depends on it, the retire is rejected with `ERR_PROGRAM_HAS_ACTIVE_ENROLLMENTS`.

A **subscription plan** is a purchasable tier. The admin sets its `tier` (`BASIC`, `PLUS`, or `PRO`), its `total_price_cents` (a non-negative integer), the `down_payment_pct` fraction due up front when the plan is financed (between 0.00 and 1.00 inclusive, two decimals), the `financing_months` count of monthly installments for the financed remainder (at least 1 and at most 24, interest-free), the `included_mock_credits` count of mock attempts included before per-attempt overage applies (non-negative), a `pass_guarantee` boolean indicating whether the tier carries the guarantee policy (default false), a `guarantee_refund_pct` fraction of amount-paid refunded on an approved money-back claim (between 0.00 and 1.00 inclusive, two decimals, default 0.0), and an `includes_ce` boolean indicating whether the tier bundles a CE package (default false). A new plan is `ACTIVE`; archiving it moves it to `ARCHIVED`, after which it rejects new enrollments.

A **CE bundle** ties continuing-education credit to a program. The admin creates it with the program reference (`license_program_id`), a `ce_credits_total` count of whole credits granted when every module is completed (at least 1), and a `modules_total` count of modules across which those credits accrue cumulatively (at least 1). Bundles can be listed and filtered by `license_program_id`, which is the reverse path from a program to its bundles, and the awards drawn from a given bundle can be listed by walking from the bundle's `id`.

### 3.2. Learners, Enrollment, and the Financing Schedule

A **learner** self-registers with a unique `email` and a `full_name`; an `email` that duplicates an existing learner's is rejected as request well-formedness with `ERR_INVALID_REQUEST`. The learner is then the principal behind every enrollment they own.

Creating an **enrollment** is the learner's commitment to one program under one plan. The create payload names the `learner_id`, the `license_program_id`, the `subscription_plan_id`, a `financed` boolean (default false), and, when the chosen plan bundles CE, a `ce_bundle_id`. A new enrollment begins in `DRAFT` status with `exam_outcome` of `PENDING`, `guarantee_eligible` false, and its activity counters (`questions_answered_total`, `completed_mock_count`) and both readiness scores at zero. At creation the system records `financing_total_due_cents` equal to the plan's `total_price_cents`, sets `financing_paid_cents` to zero and `financing_balance_cents` to the same `total_price_cents`, and materializes the installment schedule. Referential compatibility is enforced at create time: whenever a `ce_bundle_id` is supplied it is first existence-checked (a missing bundle yields `ERR_NOT_FOUND`) and then its `license_program_id` must match the enrollment's program — any supplied CE bundle whose program differs is rejected with `ERR_REFERENCE_INCOMPATIBLE` — and this existence and referential check runs on any supplied bundle regardless of whether the plan bundles CE. After those checks pass, when the plan does not include CE the supplied bundle is discarded and `ce_bundle_id` is stored as null; `ce_bundle_id` likewise stays null when none is supplied.

The **financing schedule** is built as follows. Let the plan's price be `total_price_cents`, the up-front fraction be `down_payment_pct`, and the number of monthly installments be `financing_months`. The down payment is the price multiplied by the down-payment fraction, rounded half up to whole cents. The financed remainder is the price minus that down payment. The base monthly amount is the financed remainder divided by the number of financing months, taking the integer floor in cents. The leftover remainder is the financed remainder minus the base amount multiplied by the number of months. The schedule then has one more installment than there are financing months: the first installment, `sequence_no` 1, carries the down-payment amount; installments `sequence_no` 2 through the number of financing months each carry the base amount; and the final installment, whose `sequence_no` is the number of financing months plus one, carries the base amount plus the leftover remainder. Each installment records its `enrollment_id`, its `sequence_no`, its `amount_cents`, and a `status` of `DUE`. Folding the remainder into the last installment guarantees that the sum of all installment amounts equals `total_price_cents` exactly. When `financed` is false, the schedule is instead a single installment, `sequence_no` 1, whose `amount_cents` equals the full `total_price_cents` with no remainder split.

A learner pays a `DUE` installment one at a time, moving it to `PAID` and incrementing that installment's `version`. Paying is permitted only while the owning enrollment is in `DRAFT` or `ACTIVE`; in any other enrollment state the payment is rejected with `ERR_INVALID_STATE`. Each payment recomputes the enrollment's ledger: `financing_paid_cents` becomes the sum of `amount_cents` over installments in `PAID` status, and `financing_balance_cents` becomes `financing_total_due_cents` minus `financing_paid_cents`, floored at zero. Installments in `VOID` status contribute to neither the paid sum nor the balance. Installments for an enrollment are always listed in `sequence_no` ascending order and may be filtered by `status`.

A learner may **restructure** the financing of an enrollment, supplying a `new_financing_months` value and an `expected_enrollment_version`. As described in §2.9, the supplied version must match the enrollment's current `version` or the request is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412). A successful restructure voids the prior `DUE` installments (each moves to `VOID`) while leaving any already-`PAID` installments untouched, regenerates the schedule with the same waterfall arithmetic as above — honoring the enrollment's existing `financed` flag, so a non-financed enrollment is rebuilt as the single full-price installment regardless of `new_financing_months` and only a financed one consumes the new month count — leaves `financing_total_due_cents` unchanged, recomputes the financing ledger (`financing_paid_cents` and `financing_balance_cents`) from the surviving `PAID` installments, and increments the enrollment's `version`.

### 3.3. Activation and the Study Plan

A learner **activates** a `DRAFT` enrollment to begin studying, transitioning it to `ACTIVE`. Three preconditions guard activation. The referenced license program must be `PUBLISHED`, or the activation is rejected with `ERR_PROGRAM_NOT_PUBLISHED`. The referenced subscription plan must be `ACTIVE`, or it is rejected with `ERR_PLAN_ARCHIVED`. And if the enrollment is financed, the down-payment installment — the one at `sequence_no` 1 — must already be `PAID`, or the activation is rejected with `ERR_DOWN_PAYMENT_UNPAID`.

Activation has four side effects. It materializes one **study-plan domain** for each entry in the program's `domain_weights`, copying the `domain_code` and `weight` onto each `StudyPlanDomain` and setting its initial `mastery` to 50. It sets `financing_total_due_cents` to the plan's price. It recomputes the enrollment's two readiness scores (described in §3.4). And it advances `status` to `ACTIVE` and increments the enrollment's `version`. A study-plan domain records its `enrollment_id`, its `domain_code`, its `weight`, and its evolving `mastery`; the domains of an enrollment can be listed back.

### 3.4. Studying: Practice Batches, Mock Exams, Mastery, and Readiness

Once active, a learner studies by recording two kinds of activity, both scored the instant they are submitted.

A **practice session** records one adaptive batch against a single domain. The payload names the `domain_code` the batch targets, an `answered_count` of items answered (non-negative), and a `correct_count` of those answered correctly (at least zero and no greater than the answered count). The targeted `domain_code` must match a study-plan domain of the enrollment, or the session is rejected with `ERR_REFERENCE_INCOMPATIBLE`. A batch with an `answered_count` of zero has no defined percentage and is rejected with `ERR_EMPTY_SESSION`. A session is created already `COMPLETED` — there is a single scoring event and no later transition. On acceptance the system computes the batch percentage `batch_pct` as one hundred times the correct count divided by the answered count, rounded half up to an integer.

The session then drives an exponentially-weighted mastery update for the matching domain. The new mastery is the smoothing coefficient of 0.40 multiplied by the batch percentage, plus the complement 0.60 multiplied by the domain's prior mastery, the whole sum rounded half up to an integer and then clamped to the range 0 through 100. Because this is an EWMA, the order in which sessions are recorded matters — each update folds into the running value. The enrollment's `questions_answered_total` is increased by the batch's `answered_count` (it is, equivalently, the sum of `answered_count` over all completed sessions), the readiness scores are recomputed, and the enrollment is re-versioned. Practice sessions can be listed, filtered by `domain_code`.

A **mock exam** records one full-length attempt. The payload names a `raw_score` of items correct (non-negative) and an `item_count` of items on the mock (at least 1). The mock is created already `COMPLETED` and is scored on submission: `scaled_score` is one hundred times the raw score divided by the item count, rounded half up to an integer on a 0-to-100 scale, and `completed_at` is stamped with the current logical-clock time so the latest attempt can later be identified. The system also marks `is_overage`: counting the mock exams already in `COMPLETED` status for the enrollment *before* this attempt, the attempt is an overage when that prior count is greater than or equal to the plan's `included_mock_credits`. In other words, with N included credits, attempts 1 through N are included and attempt N+1 is the first overage. Recording a mock increases the enrollment's `completed_mock_count`, recomputes readiness, and re-versions the enrollment. Mock exams can be listed.

The two **readiness scores** are computed from the same domain-mastery base but differ in how they treat mocks. First, the weighted domain mastery is the sum, over every study-plan domain of the enrollment, of that domain's `weight` multiplied by its `mastery`. The conservative, gating `readiness_score` blends 0.60 of that weighted domain mastery with 0.40 of the single latest mock's `scaled_score`, the final blend rounded half up to an integer; the "latest mock" is the `COMPLETED` mock with the greatest `completed_at`, breaking ties by earliest `created_at` and then by creation order, and the mock component is zero when no completed mock exists. The optimistic `projected_readiness_score` instead blends the same 0.60 of weighted domain mastery with 0.40 of the average mock score, where the average is the mean of `scaled_score` across *all* completed mocks, that mean itself rounded half up to an integer before blending, and zero when there are no mocks; the final projected blend is likewise rounded half up. The conservative figure is the one used for every gating decision and for readiness display; the projected figure is the forward-looking analytics view, and the two diverge whenever the latest mock differs from the running mean. The analytics view (`GET /enrollments/{id}/analytics`) returns exactly the enrollment record itself — both scores, the activity counters (`questions_answered_total`, `completed_mock_count`), and the financing figures are carried as fields on that record; the per-domain mastery is not embedded in this response and is read separately through the domains listing (`GET /enrollments/{id}/domains`).

### 3.5. Certification, the Pass Guarantee, and Refunds

When a candidate sits the real exam, an `ExamProctor` **certifies** the outcome on the `ACTIVE` enrollment, supplying an `outcome` of either PASS or FAIL. Certification is permitted only while `exam_outcome` is still `PENDING`; a second certification attempt is rejected with `ERR_EXAM_ALREADY_CERTIFIED`. This already-certified check is evaluated before the requirement that the enrollment be `ACTIVE`: when the `exam_outcome` is not `PENDING` the request is rejected with `ERR_EXAM_ALREADY_CERTIFIED` regardless of the enrollment's current status (so a repeat certification on a `FAILED` enrollment surfaces `ERR_EXAM_ALREADY_CERTIFIED` rather than the generic state error), and only when `exam_outcome` is still `PENDING` but the enrollment is not `ACTIVE` is the request rejected with `ERR_INVALID_STATE`.

A PASS certification additionally requires that the enrollment owe nothing: if `financing_balance_cents` is greater than zero, the PASS is rejected with `ERR_BALANCE_OUTSTANDING`. When PASS succeeds, `exam_outcome` becomes `PASS`, the enrollment moves from `ACTIVE` to `PASSED` (a terminal status), and as a cascade every `JOINED` cohort membership of this enrollment is dropped to `DROPPED` — each affected cohort decrements its `seats_taken`, recomputes its derived status, and is re-versioned, and each membership is itself re-versioned. The enrollment's `version` increments.

A FAIL certification has no balance precondition. On FAIL the system snapshots `guarantee_eligible` — recording, at that instant, whether the activity-and-readiness thresholds described below were met — then sets `exam_outcome` to `FAIL`, moves the enrollment from `ACTIVE` to `FAILED`, and increments the enrollment's `version`. `FAILED` is deliberately *not* terminal: it is the only state from which a learner may file a pass-guarantee claim.

**Guarantee eligibility** is a four-part threshold evaluated against the conservative readiness figure. An enrollment is eligible only when all of the following hold: the plan's `pass_guarantee` flag is true; the `questions_answered_total` is at least 200; the `completed_mock_count` is at least 2; and the conservative `readiness_score` is at least 75, where the boundary is inclusive so that exactly 75 qualifies and 74 does not. This same predicate is evaluated twice in the lifecycle — once at FAIL certification to populate the `guarantee_eligible` snapshot, and again as a precondition when a claim is approved.

A learner files a **pass-guarantee claim** against a `FAILED` enrollment, naming the `enrollment_id` and a requested `remedy` of either `RETAKE_EXTENSION` or `MONEY_BACK`; an attempt to file against an enrollment that is not in `FAILED` status is rejected with `ERR_INVALID_STATE`. A new claim is in `SUBMITTED` status. Claims can be fetched and listed, filtered by `enrollment_id`; when the lister acts as a `Learner` the list is additionally restricted to claims whose owning enrollment belongs to that learner (an `ExamProctor` sees all), and a `Learner` fetching a single claim that belongs to another learner's enrollment is rejected with `ERR_NOT_RESOURCE_OWNER`.

An `ExamProctor` then **decides** a `SUBMITTED` claim, supplying a `decision` of APPROVE or DENY. The claim itself must be in `SUBMITTED` status — a decision on a claim that is already `APPROVED` or `DENIED` is rejected with `ERR_INVALID_STATE`, and this claim-state check is evaluated before the enrollment-state check below. Either decision then requires the owning enrollment to be in `FAILED` status, or the decision is rejected with `ERR_INVALID_STATE`. Approval additionally requires that the owning enrollment's `guarantee_eligible` be true; an attempt to approve an ineligible claim is rejected with `ERR_GUARANTEE_NOT_ELIGIBLE`. A denial requires only the `FAILED`-state check and then sets the claim to `DENIED`, re-versioning the claim. An approval sets the claim to `APPROVED`, re-versions it, and then branches on the remedy.

When the approved remedy is `RETAKE_EXTENSION`, the claim's `refund_amount_cents` is zero and the enrollment stays in `FAILED` (its retake window is extended). When the approved remedy is `MONEY_BACK`, the system computes the refund and then drives the enrollment from `FAILED` to `REFUNDED` as a cascade. The **refund** is the sum of per-installment refunds taken over the enrollment's installments currently in `PAID` status, processed in `sequence_no` ascending order: for each paid installment, multiply its `amount_cents` by the plan's `guarantee_refund_pct` and round that product half up to whole cents, then sum those per-installment amounts. The rounding order is pinned — each installment is rounded first and the rounded figures are summed, never summed-then-rounded — because when individual products land on a half-cent the two orders can differ and the per-installment order is the observable one. Driving the enrollment to `REFUNDED` voids every remaining `DUE` installment (each moves to `VOID`, bringing `financing_balance_cents` to zero), drops every `JOINED` cohort membership of the enrollment to `DROPPED` with the same cohort seat-recompute and re-versioning cascade described above, sets the enrollment `status` to `REFUNDED` (a terminal status), and increments the enrollment's `version`.

### 3.6. Withdrawal

A learner may **withdraw** an enrollment that is in `DRAFT` or in `ACTIVE`, moving it to the terminal `WITHDRAWN` status. From `DRAFT` there are no preconditions. From `ACTIVE`, withdrawal is permitted only while `exam_outcome` is still `PENDING`; once an outcome has been certified the withdraw is rejected with `ERR_EXAM_ALREADY_CERTIFIED`. In both cases the side effects void all `DUE` installments (each to `VOID`) and increment the enrollment's `version`. When the enrollment being withdrawn was `ACTIVE`, the withdrawal additionally drops every `JOINED` cohort membership to `DROPPED`, with each affected cohort decrementing `seats_taken`, recomputing its status, and re-versioning, exactly as the other terminal cascades do.

### 3.7. Continuing-Education Credit Accrual

When an enrollment's plan bundles CE, the learner records **CE credit awards** as they finish modules. Each award names the cumulative `modules_completed` claimed complete at that point, and the system derives both the cumulative and the delta credit figures, recording the `enrollment_id` and the drawing `ce_bundle_id` on the award; the drawing bundle is the enrollment's own `ce_bundle_id`, so an award against an enrollment that carries no linked CE bundle is rejected with `ERR_REFERENCE_INCOMPATIBLE`. The `modules_completed` value must be at least 1, must not exceed the bundle's `modules_total`, and must be strictly greater than the `modules_completed` of the prior award for the enrollment; an award whose module count does not strictly increase, or that exceeds the bundle total, is rejected with `ERR_CE_MODULE_REGRESSION`.

The arithmetic conserves the bundle's total. The `cumulative_credits` for an award is the bundle's `ce_credits_total` multiplied by the award's `modules_completed`, divided by the bundle's `modules_total`, rounded half up to a whole credit. The `credits_awarded` by this particular award is its cumulative credits minus the cumulative credits of the most recent prior award (ordered by `modules_completed`), or minus zero when there is no prior award. Because each award's cumulative figure is derived from the same rounded formula and the deltas are taken between successive cumulatives, when `modules_completed` finally reaches `modules_total` the sum of all `credits_awarded` equals the bundle's `ce_credits_total` exactly. CE awards for an enrollment can be listed, and the awards drawn from a bundle can be listed by the bundle path.

### 3.8. Live-Review Cohorts, Sessions, and Membership

A `ContentAdmin` creates a **cohort** for live review, naming the `license_program_id` the cohort serves, a `title`, and a `capacity` of at least one confirmed membership. A cohort tracks `seats_taken` — the count of memberships currently `JOINED` — and a derived `status`. A new cohort is `OPEN` with `seats_taken` of zero. `FULL` is derived: as soon as a join brings `seats_taken` up to `capacity`, the cohort flips from `OPEN` to `FULL`; when a drop later brings `seats_taken` back below `capacity`, it flips from `FULL` back to `OPEN`. An admin may also explicitly close a cohort, moving it from either `OPEN` or `FULL` to the terminal `CLOSED` status (a cohort in any other status is rejected with `ERR_INVALID_STATE`), after which it rejects new joins. Cohorts can be listed and filtered by `license_program_id`.

An admin schedules **cohort sessions** of live review on a cohort, each with a `topic`, a `session_start_utc`, and a `session_end_utc` that must be strictly after the start. A session records the owning `cohort_id`. Sessions are spaced by a buffer: a new session must keep a gap of at least thirty minutes from every other session of the *same* cohort, measured under closed-interval semantics with a symmetric buffer on both sides. Concretely, if the new session starts at or after an existing session's end, the gap is the new start minus the existing end; if the new session ends at or before an existing session's start, the gap is the existing start minus the new end; and if neither holds, the two windows themselves overlap and there is no gap. A gap of exactly thirty minutes is allowed; any gap of less than thirty minutes — including a true overlap — is rejected with `ERR_SESSION_BUFFER_CONFLICT`. A cohort's sessions can be listed.

A learner **joins** a cohort by creating a **cohort membership**, supplying the `enrollment_id` and the personal live-review window they intend to attend as `session_start_utc` and `session_end_utc`. The membership records the `cohort_id` and `enrollment_id` and starts in `JOINED` status. Several checks guard the join, evaluated in this order: referential compatibility, then window collision, then capacity. The cohort's `license_program_id` must match the program of the joining enrollment, or the join is rejected as a referential mismatch with `ERR_REFERENCE_INCOMPATIBLE`. Next, the requested window must not collide with the learner's other commitments: the new window is checked against every *other* `JOINED` membership of the *same* enrollment, across all cohorts, under half-open interval semantics — the new window `[new_start, new_end)` conflicts with an existing window `[existing_start, existing_end)` exactly when the new start is before the existing end and the existing start is before the new end. Abutting windows, where one ends precisely as the next begins, do not conflict. A conflicting window is rejected with `ERR_SESSION_WINDOW_CONFLICT`. Finally, the cohort must have room: a join is rejected with `ERR_COHORT_FULL` when `seats_taken` is already at or above `capacity`, or when the cohort status is `CLOSED`. (The well-formedness check that `session_end_utc` be strictly after `session_start_utc` precedes all three of these and is rejected with `ERR_INVALID_REQUEST`.) A successful join sets the membership to `JOINED`, increments the cohort's `seats_taken`, and flips the cohort to `FULL` if the join brings `seats_taken` up to `capacity`.

A learner **drops** a membership, moving it from `JOINED` to the terminal `DROPPED` status; a drop attempt on a membership that is not `JOINED` (already `DROPPED`) is rejected with `ERR_INVALID_STATE`. The same drop is what fires as a cascade from an enrollment's PASS, REFUNDED, or ACTIVE-withdrawal transitions. Dropping decrements the owning cohort's `seats_taken`, recomputes the cohort (flipping `FULL` back to `OPEN` when `seats_taken` falls below `capacity`), increments the membership's `version`, and sets its `status` to `DROPPED`. Memberships can be listed under a cohort (filterable by `status`), fetched individually, or listed across cohorts filtered by `enrollment_id`; on the cross-cohort listing and on an individual fetch, a `Learner` is restricted to memberships whose owning enrollment belongs to that learner (the cross-cohort list silently excludes others' memberships and an individual fetch of another learner's membership is rejected with `ERR_NOT_RESOURCE_OWNER`), while `ContentAdmin` and `ExamProctor` see all.

### 3.9. Deterministic Time

The platform runs on a logical clock so that `completed_at` stamps and cohort-session windows behave deterministically under test. The server starts with its clock fixed at `2026-04-01T00:00:00Z`, and before any set call the clock reads exactly that default rather than wall-clock time. A `PlatformOps`-only test-driving capability advances the clock to a supplied `to_iso8601` instant (which must be a well-formed datetime, else `ERR_INVALID_REQUEST`); every subsequent `completed_at` stamp and time-based comparison reads from this logical clock. The logical clock governs only `completed_at` stamps and time-based comparisons; the `created_at`, `updated_at`, and `api_request_timestamp` fields are stamped from the server's wall clock and are unaffected by the logical clock. The set-clock call returns `200 OK` with an empty data object.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify or transition an existing resource, that perform a computed read, or that drive the clock return `200 OK`. The request body, response body, and side effects of each endpoint are described in the §3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/license-programs` | Create a license program (DRAFT) | ContentAdmin |
| GET | `/license-programs` | List license programs (filter by status) | ContentAdmin, Learner, ExamProctor |
| GET | `/license-programs/{id}` | Fetch a license program | ContentAdmin, Learner, ExamProctor |
| POST | `/license-programs/{id}/items` | Add a question item to a program | ContentAdmin |
| GET | `/license-programs/{id}/items` | List a program's question items | ContentAdmin, Learner, ExamProctor |
| POST | `/license-programs/{id}/publish` | Publish a DRAFT program | ContentAdmin |
| POST | `/license-programs/{id}/retire` | Retire a PUBLISHED program | ContentAdmin |
| POST | `/subscription-plans` | Create a subscription plan/tier | ContentAdmin |
| GET | `/subscription-plans/{id}` | Fetch a subscription plan | ContentAdmin, Learner |
| POST | `/subscription-plans/{id}/archive` | Archive a plan | ContentAdmin |
| POST | `/ce-bundles` | Create a CE bundle for a program | ContentAdmin |
| GET | `/ce-bundles` | List CE bundles (filter by license_program_id) | ContentAdmin, Learner |
| GET | `/ce-bundles/{id}` | Fetch a CE bundle | ContentAdmin, Learner |
| GET | `/ce-bundles/{id}/ce-awards` | List CE awards drawn from a bundle | ContentAdmin, Learner |
| POST | `/learners` | Register a learner | Learner |
| GET | `/learners/{id}` | Fetch a learner | Learner, ContentAdmin |
| POST | `/enrollments` | Create an enrollment (DRAFT); build financing schedule | Learner |
| GET | `/enrollments` | List enrollments (filter by learner_id, license_program_id, subscription_plan_id, ce_bundle_id) | Learner, ContentAdmin, ExamProctor |
| GET | `/enrollments/{id}` | Fetch an enrollment | Learner, ContentAdmin, ExamProctor |
| GET | `/enrollments/{id}/analytics` | Computed progress analytics read | Learner, ContentAdmin, ExamProctor |
| POST | `/enrollments/{id}/activate` | Activate a DRAFT enrollment | Learner |
| POST | `/enrollments/{id}/restructure-financing` | OCC-guarded financing rebuild | Learner |
| POST | `/enrollments/{id}/withdraw` | Withdraw a DRAFT or ACTIVE enrollment | Learner |
| POST | `/enrollments/{id}/certify-exam` | Certify the official exam outcome (PASS/FAIL) | ExamProctor |
| GET | `/enrollments/{id}/installments` | List installments (ordered by sequence_no ASC; filter by status) | Learner, ContentAdmin |
| POST | `/enrollments/{id}/installments/{installmentId}/pay` | Pay a DUE installment | Learner |
| GET | `/enrollments/{id}/domains` | List study-plan domains | Learner, ContentAdmin, ExamProctor |
| POST | `/enrollments/{id}/practice-sessions` | Record an adaptive practice batch | Learner |
| GET | `/enrollments/{id}/practice-sessions` | List practice sessions (filter by domain_code) | Learner, ContentAdmin, ExamProctor |
| POST | `/enrollments/{id}/mock-exams` | Record a mock exam attempt | Learner |
| GET | `/enrollments/{id}/mock-exams` | List mock exams | Learner, ContentAdmin, ExamProctor |
| POST | `/enrollments/{id}/ce-awards` | Record cumulative CE module completion | Learner |
| GET | `/enrollments/{id}/ce-awards` | List CE credit awards | Learner, ContentAdmin |
| POST | `/pass-guarantee-claims` | File a pass-guarantee claim | Learner |
| GET | `/pass-guarantee-claims` | List pass-guarantee claims (filter by enrollment_id) | Learner, ExamProctor |
| GET | `/pass-guarantee-claims/{id}` | Fetch a pass-guarantee claim | Learner, ExamProctor |
| POST | `/pass-guarantee-claims/{id}/decide` | Approve or deny a claim | ExamProctor |
| POST | `/cohorts` | Create a live-review cohort | ContentAdmin |
| GET | `/cohorts` | List cohorts (filter by license_program_id) | ContentAdmin, Learner |
| GET | `/cohorts/{id}` | Fetch a cohort | ContentAdmin, Learner |
| POST | `/cohorts/{id}/close` | Close a cohort to new joins | ContentAdmin |
| POST | `/cohorts/{id}/sessions` | Schedule a live-review session | ContentAdmin |
| GET | `/cohorts/{id}/sessions` | List a cohort's sessions | ContentAdmin, Learner |
| POST | `/cohorts/{id}/memberships` | Join a cohort with a session window | Learner |
| GET | `/cohorts/{id}/memberships` | List a cohort's memberships (filter by status) | ContentAdmin, Learner |
| DELETE | `/cohorts/{id}/memberships/{membershipId}` | Drop a cohort membership | Learner |
| GET | `/cohort-memberships/{id}` | Fetch a cohort membership | ContentAdmin, Learner, ExamProctor |
| GET | `/cohort-memberships` | List cohort memberships (filter by enrollment_id) | ContentAdmin, Learner, ExamProctor |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ENROLLMENT_VERSION` | 412 |
| `ERR_PROGRAM_NOT_PUBLISHED` | 409 |
| `ERR_PLAN_ARCHIVED` | 409 |
| `ERR_DOWN_PAYMENT_UNPAID` | 409 |
| `ERR_BLUEPRINT_WEIGHTS_INVALID` | 409 |
| `ERR_PROGRAM_HAS_NO_ITEMS` | 409 |
| `ERR_PROGRAM_HAS_ACTIVE_ENROLLMENTS` | 409 |
| `ERR_REFERENCE_INCOMPATIBLE` | 409 |
| `ERR_EXAM_ALREADY_CERTIFIED` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_GUARANTEE_NOT_ELIGIBLE` | 409 |
| `ERR_EMPTY_SESSION` | 422 |
| `ERR_COHORT_FULL` | 409 |
| `ERR_SESSION_WINDOW_CONFLICT` | 409 |
| `ERR_SESSION_BUFFER_CONFLICT` | 409 |
| `ERR_CE_MODULE_REGRESSION` | 409 |

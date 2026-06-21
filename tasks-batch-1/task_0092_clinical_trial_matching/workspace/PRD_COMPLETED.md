# Clinical Trial Matching API — Product Requirements Document

## 1. Introduction

Running a regulated clinical trial means holding several independent concerns in lockstep at once: a participant must objectively meet the trial's inclusion and exclusion criteria, must sign the exact consent wording the ethics board approved, must be randomized into a treatment arm by a defensible scheme, and must be protected by a safety apparatus that can freeze the trial the instant a serious adverse event is judged related to the intervention. This API is the system of record that binds those concerns together. It governs trials and the participants matched against them, the eligibility predicates and randomization arms that define a trial, the versioned consent documents and the independent ethics reviews that gate them, the enrollment lifecycle that carries a participant from a screening match through randomization and active follow-up, the study visits with their blood-draw windows, the adverse-event reporting and adjudication chain, and the compensation payments owed to participants.

Two design themes recur throughout. First, **segregation of duties**: the sponsor who owns a trial cannot also approve its own ethics review, and the investigator who reports an adverse event cannot also adjudicate it — different human actors must hold different keys. Second, **derived state that must always reconcile**: a trial's operational posture, its enrolled headcount, and its count of active safety holds are never set directly by a client; they are recomputed from the underlying reviews, enrollments, and adverse events every time one of those changes. An enrollment additionally tracks two completely independent dimensions — where it sits in the consent-to-completion lifecycle, and whether it is safe to proceed — and the two evolve on separate tracks. The sections below define the precise contracts every client and implementer must honor, then narrate the business workflows in which the individual rules live.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles: `Sponsor`, `IRBReviewer`, `CoordinatorStaff`, `Investigator`, and `SafetyOfficer`. When a request carries valid headers but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All five roles are **opaque operator identities**: in each case `X-User-ID` is an operator identifier that is not tied to any persisted entity, and the server never compares it to an entity's `id`. It does, however, record it where the workflow demands an audit anchor. When `X-User-Role` is `Sponsor`, the `X-User-ID` of the operator who creates a trial is written to that trial's `sponsor_user_id`; this recorded value becomes the comparison point for segregation-of-duties checks but is never matched against any `id`. When `X-User-Role` is `Investigator`, the `X-User-ID` of the operator who reports an adverse event is written to that event's `reporter_user_id` as the segregation anchor. When `X-User-Role` is `IRBReviewer`, the `X-User-ID` of the operator who decides a review is written to that review's `reviewer_user_id`. When `X-User-Role` is `SafetyOfficer`, the `X-User-ID` of the operator who adjudicates an adverse event is written to that event's `adjudicator_user_id`. When `X-User-Role` is `CoordinatorStaff`, the operator drives screening, enrollment, visit, and participant operations; the server does not persist this identity on any entity. In none of these cases is `X-User-ID` compared to an entity's `id` — the comparisons that matter are between the recorded operator identifiers (a reviewer versus a `sponsor_user_id`, an adjudicator versus a `reporter_user_id`).

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped before the page begins and defaults to 0. Out-of-range or malformed values are not rejected but coerced to the valid range: a `limit` below 1 is clamped to 1, a `limit` above 100 is clamped to 100, and a non-integer `limit` falls back to the default of 10; a negative or non-integer `offset` falls back to 0.

Unless an endpoint states otherwise, all list responses are sorted by the creation timestamp (`created_at`) in ascending order. The list-returning endpoints that accept these parameters — the screenings and enrollments collections — include the four pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in this system carries a `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp formatted as an ISO 8601 UTC instant with three fractional digits. All eleven entity types — `Trial`, `EligibilityCriterion`, `RandomizationArm`, `ConsentDocument`, `IRBReview`, `Participant`, `Screening`, `Enrollment`, `Visit`, `AdverseEvent`, and `CompensationPayment` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every mutation, and an integer `version` that begins at its initial value of 1 and increments by one on every mutation of that resource. The `version` field is the anchor for the optimistic-concurrency checks described in §2.6 as well as the per-entity version bumps narrated throughout §3.

### 2.5. Derived State and Hierarchical Reconciliation

A number of fields are **computed** and must never be set directly by a client; the server recomputes them whenever an underlying fact changes and treats each recomputation as a mutation that refreshes `updated_at` and increments the owning resource's `version`. On a `Trial`, four fields are derived: `irb_status` mirrors the latest decided PROTOCOL review outcome; `posture` is the operational gate over child operations; `enrolled_count` is the number of this trial's enrollments whose `enrollment_status` is `RANDOMIZED`, `ACTIVE`, or `COMPLETED`; and `active_safety_holds` is the number of this trial's enrollments whose `safety_status` is `HOLD`. On a `RandomizationArm`, `assigned_count` is the number of enrollments randomized to that arm whose `enrollment_status` is `RANDOMIZED`, `ACTIVE`, or `COMPLETED`. On an `Enrollment`, `completed_visits_count` is the number of that enrollment's visits whose `status` is `COMPLETED`.

The trial's `posture` is the central derived gate and takes one of three values: `SETUP`, `OPEN`, or `FROZEN`. A freshly created trial begins `SETUP`. It becomes `OPEN` once the protocol review has been approved (`irb_status` is `APPROVED`), the trial has at least one randomization arm, an `ACTIVE` consent document exists, and there are no active safety holds. It becomes `FROZEN` while at least one enrollment is on a safety hold (that is, whenever `active_safety_holds` is one or more). Posture is recomputed every time an IRB decision lands, a consent document is activated, an enrollment is randomized or withdrawn, a safety hold is placed, or a safety hold is lifted.

Many operations in this system mutate more than one resource. When that happens, the server performs every cascade as part of the same logical operation and bumps the `version` of each resource it touches. The specific cascades — consent supersession triggering reconsent, randomization incrementing arm and trial counters, adverse-event adjudication freezing a trial — are described in their workflow homes in §3; the governing principle here is that no derived field is ever left stale, and every resource the cascade touches has its `updated_at` refreshed and its `version` incremented.

### 2.6. Optimistic Concurrency on Trial Version

Two write operations are guarded by optimistic concurrency control keyed on the trial's `version`, and both require a non-optional `expected_trial_version` field carrying the client's last observed `Trial.version`.

The first is **consent activation**. Activating an IRB-approved consent document supersedes whichever consent document was previously `ACTIVE` for the trial and recomputes the trial's `posture`. The activation request must carry `expected_trial_version` equal to the trial's current `version`. If the trial's `version` has advanced since the client last read it — because another activation already superseded the prior consent, or because a protocol decision moved the posture — the client's view is stale and the activation is rejected with `ERR_STALE_TRIAL_VERSION` (HTTP 412).

The second is the **randomization transition**. Advancing an enrollment from `CONSENTED` to `RANDOMIZED` consumes one slot of the trial's finite target enrollment and bumps both the trial's `enrolled_count` and the chosen arm's `assigned_count`. The randomize request must carry `expected_trial_version` equal to the trial's current `version`. If the trial's `version` has advanced since the client read it — because another randomization already consumed a slot, or because a safety hold froze the trial — the client's capacity view is stale and the transition is rejected with `ERR_STALE_TRIAL_VERSION` (HTTP 412). No other operation takes a version field; only consent activation and the randomize transition are version-guarded.

### 2.7. Nested Resource Retrieval and Reference Validation

Many resources are addressed through nested paths — a criterion, arm, consent document, or review under a trial; a visit, adverse event, or payment under an enrollment. For any path that names more than one resource, the server validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. A review under a non-existent trial fails on the trial before the review is ever consulted.

Beyond path identifiers, several request bodies carry references to other resources — a `participant_id` when screening, a `screening_id` when enrolling, a `consent_document_id` when consenting or opening a consent-scope review. Each such reference must resolve to an existing resource of the correct type; if it does not, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). This existence-of-references check is distinct from, and evaluated after, the path-existence check.

### 2.8. Request Validation Ordering

When several validations apply to one request, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`); then existence of every path-named resource, left to right (`ERR_NOT_FOUND`); then existence of every body reference (`ERR_REFERENCE_NOT_FOUND`); then structural validity of the body — required fields present and well-typed, enum values in range, and numbers within their declared bounds, such as a trial's `target_enrollment` being at least 1 or a visit's `draw_window_minutes` being at least 0 (`ERR_INVALID_REQUEST`); then, on the action endpoints, validity of the action discriminator (`ERR_INVALID_ACTION`); then presence of the fields a given action requires (`ERR_MISSING_ACTION_FIELD`); then that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). The remaining business, safety, referential, temporal, and fiscal checks are evaluated after these and are described alongside the workflows they guard in §3. The practical consequence is that, for example, a malformed action value surfaces as `ERR_INVALID_ACTION` before any state check runs, and a missing header is reported before any role or existence check.

The two action-shape checks deserve naming up front. The action discriminator must be valid for the endpoint it is sent to: an enrollment transition's `action` must be one of `CONSENT`, `RANDOMIZE`, `ACTIVATE`, `COMPLETE`, or `WITHDRAW`; an adverse-event review's `action` must be `TRIAGE` or `ADJUDICATE`, and an `ADJUDICATE` must carry a `relation` of `RELATED` or `UNRELATED`; an IRB decision's `action` must be `APPROVE`, `REJECT`, or `REVISE`. Anything outside these sets yields `ERR_INVALID_ACTION`. Separately, certain actions require specific body fields: a `CONSENT` transition requires `consent_document_id`, a `RANDOMIZE` transition requires `expected_trial_version`, an IRB review opened with `scope` of `CONSENT` requires `consent_document_id` while one opened with `scope` of `PROTOCOL` must omit it — a violation of any of these yields `ERR_MISSING_ACTION_FIELD`.

### 2.9. Precision and Rounding

Several calculations produce rational results that must be rounded deterministically. Two precisions are in use. The eligibility match score is rounded to four decimal places using the round-half-up method. All monetary calculations are performed in integer cents and rounded, where rounding is required, to whole cents using the round-half-up method. Where a calculation pins the order of rounding (for example, summing exact per-visit cents before applying a single withholding rounding), that order is part of the contract and is stated with the calculation in §3.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Trial: Configuration in SETUP

A `Sponsor` creates a trial by supplying its `title`, the `target_enrollment` it intends to randomize (which must be at least 1), and a `randomization_method`. The method is one of `SIMPLE` or `PERMUTED_BLOCK`; choosing `PERMUTED_BLOCK` additionally requires a `block_size`, which must be a positive integer of at least 1 (no multiple-of-arms relationship is enforced at creation, since arms are added later in SETUP), while `SIMPLE` leaves `block_size` null even when a value is supplied in the request. On creation the server records the creating operator as `sponsor_user_id`, sets the trial's `posture` to `SETUP`, sets its `irb_status` to `NONE`, and initializes `enrolled_count` and `active_safety_holds` to 0.

A trial is configured entirely while its `posture` is `SETUP`. During this phase the `Sponsor` adds the eligibility criteria and randomization arms. Adding either a criterion or an arm is permitted only while `posture` is `SETUP`; once the trial has left setup, an attempt to add either is rejected with `ERR_TRIAL_NOT_IN_SETUP` (HTTP 409).

Each **eligibility criterion** belongs to its trial through `trial_id` and is described by four inputs. Its `kind` is either `INCLUSION` (the participant must satisfy the predicate to qualify) or `EXCLUSION` (satisfying the predicate disqualifies the participant). Its `attribute` names the participant field the predicate reads and is one of `age_years`, `weight_kg`, `hba1c`, `prior_trials_count`, or `biomarker_positive`. Its `comparator` is one of `GE`, `GT`, `LE`, `LT`, or `EQ` — meaning, respectively, that the attribute value is greater than or equal to, strictly greater than, less than or equal to, strictly less than, or exactly equal to the criterion's `threshold`. The `threshold` is the right-hand side of the comparison; for a `biomarker_positive` predicate, use 1 to mean true and 0 to mean false.

Each **randomization arm** also belongs to its trial through `trial_id` and carries a human-readable `name` (such as TREATMENT or PLACEBO) and an `allocation_weight` that is at least 1 and serves as the numerator of the arm's allocation ratio. An arm's `assigned_count` starts at 0 and is maintained by the system.

### 3.2. Consent Versioning and Independent Ethics Review

Consent and protocol approval are governed by the independent ethics board. A `Sponsor` creates a **consent document** by supplying a `body_hash` that identifies the exact wording; the server assigns its `version_number` monotonically per trial, so the first document for a trial is version 1 and each subsequent document increments the version by one. A new consent document begins life with `status` `DRAFT` and a null `irb_review_id`.

The `Sponsor` opens an **IRB review** by declaring its `scope`, which is either `PROTOCOL` or `CONSENT`. A `CONSENT`-scope review must name the `consent_document_id` under review; a `PROTOCOL`-scope review must not carry one. Opening a `PROTOCOL`-scope review sets the trial's `irb_status` to `PENDING` and increments the trial's `version` by one. At most one `PENDING` `PROTOCOL` review may exist for a trial at a time; opening a second while one is still pending is rejected with `ERR_REVIEW_ALREADY_OPEN` (HTTP 409). A review begins with `decision` `PENDING`, a null `reviewer_user_id`, and a null `decided_at`. The `consent_document_id` named on a review is a soft reference — reviews for a document are found by listing the trial's reviews and consent documents, not by a forward-owned key.

Only an `IRBReviewer` decides a review, and the decision is a three-way fork driven by the review's `action`. In every branch the review must currently be `PENDING`, and the deciding reviewer's `X-User-ID` must not equal the trial's `sponsor_user_id` — a sponsor deciding their own trial's review is a segregation-of-duties violation rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Every branch sets the review's `reviewer_user_id` to the deciding operator, sets `decided_at` to the server clock, and increments the trial's `version` by one.

- **Approve** moves the review from `PENDING` to `APPROVED`. For a `PROTOCOL`-scope review, this additionally sets the trial's `irb_status` to `APPROVED` and recomputes the trial's `posture` (it becomes `OPEN` once an `ACTIVE` consent exists and at least one arm is present and there are no safety holds). For a `CONSENT`-scope review, approval additionally requires that the referenced consent document currently be in `DRAFT` status — otherwise the approval is rejected with `ERR_INVALID_STATE` (HTTP 409) — and it cascades to transition that document from `DRAFT` to `IRB_APPROVED` and set the document's `irb_review_id` to this review.
- **Reject** moves the review from `PENDING` to `REJECTED`. For a `PROTOCOL`-scope review, this sets the trial's `irb_status` to `REJECTED` and the `posture` stays `SETUP`.
- **Revise** moves the review from `PENDING` to `REVISE_REQUESTED`. For a `PROTOCOL`-scope review, the `irb_status` stays `PENDING`. `REVISE_REQUESTED` is a terminal branch: the review can no longer be decided, and the sponsor must open a fresh review.

Because `APPROVED`, `REJECTED`, and `REVISE_REQUESTED` are all terminal, any attempt to decide a review that is no longer `PENDING` is rejected with `ERR_REVISE_NOT_DECIDABLE` (HTTP 409).

A consent document moves through its own lifecycle. It starts `DRAFT`. When the consent-scope review approves it, the system transitions it `DRAFT → IRB_APPROVED`, sets its `irb_review_id` to the approving review, and increments the document's `version` by one. From `IRB_APPROVED`, the `Sponsor` activates it. Activation requires the document to be in `IRB_APPROVED` status, the trial's `irb_status` to be `APPROVED`, and the trial to have at least one randomization arm; if any of these preconditions is unmet, the activation is rejected with `ERR_TRIAL_NOT_CONFIGURED` (HTTP 409). Activation is also the version-guarded write described in §2.6: it requires `expected_trial_version` matching the trial's current `version`, failing with `ERR_STALE_TRIAL_VERSION` otherwise. The `expected_trial_version` field is required; if it is absent the request fails with `ERR_INVALID_REQUEST` (HTTP 400). The version-staleness check is evaluated before the configuration preconditions above, so a stale `expected_trial_version` surfaces as `ERR_STALE_TRIAL_VERSION` even when the document is not in `IRB_APPROVED` status (for example, re-activating an already-`ACTIVE` document with a stale version yields `ERR_STALE_TRIAL_VERSION`, not a configuration error).

Activation is the revision-loop edge and drives a three-hop cascade. First, the newly activated document moves `IRB_APPROVED → ACTIVE`. Second, if a prior `ACTIVE` consent document already exists for the trial, that prior document is transitioned `ACTIVE → SUPERSEDED` (and its `version` incremented). Third, for every enrollment whose `signed_consent_document_id` equals the now-superseded document and whose `enrollment_status` is `CONSENTED`, the system fires the reconsent edge that returns that enrollment from `CONSENTED` to `SCREENED`. The activation itself recomputes the trial's `posture` and increments the trial's `version` by one. `SUPERSEDED` is terminal for a consent document.

### 3.3. Participants and the Matching Engine

A `CoordinatorStaff` registers a **participant** with a `full_name`, an `age_years` (a non-negative integer of completed years), a `weight_kg`, and an `hba1c` (the glycated-hemoglobin percentage that eligibility predicates read). Two further attributes have defaults: `prior_trials_count`, the number of prior trials joined, defaults to 0, and `biomarker_positive`, whether the target biomarker is present, defaults to false. Coordinator staff may later update the mutable attributes — `age_years`, `weight_kg`, `hba1c`, `prior_trials_count`, and `biomarker_positive` — and each such update increments the participant's `version` by one. Updating a participant's fields is precisely how eligibility can drift between screening and enrollment.

Screening runs the matching engine. A `CoordinatorStaff` screens a participant against a trial by supplying the `participant_id`; the server creates a **Screening** that records the `trial_id` and `participant_id` and freezes three computed outcomes: `match_result`, `failed_criteria_count`, and `match_score`.

The **eligibility match** evaluates every eligibility criterion of the trial against the participant. For each criterion, the left-hand value is the participant's value for that criterion's `attribute` — and for a `biomarker_positive` attribute, true reads as 1 and false reads as 0 — and the right-hand value is the criterion's `threshold`. The predicate is the comparison named by `comparator`: `GE` is left greater than or equal to right, `GT` is left strictly greater than right, `LE` is left less than or equal to right, `LT` is left strictly less than right, and `EQ` is left equal to right. The engine counts failures: an `INCLUSION` criterion fails when its predicate does not hold, and an `EXCLUSION` criterion fails when its predicate does hold. The running total of failures is stored as `failed_criteria_count`. The `match_result` is `ELIGIBLE` when the failure count is exactly 0, and `INELIGIBLE` otherwise. The criteria set evaluated is every `EligibilityCriterion` row whose `trial_id` is this trial; criteria are never soft-deleted and there is no status filter, and the evaluation order has no observable effect on the result. Integer comparisons are exact, and numeric attributes are compared at full double precision with no rounding before the comparison.

The **match score** is a weighted measure of fit in the closed interval from 0 to 1, computed during the screening evaluation and stored on the screening. Partition the trial's criteria into the inclusion set and the exclusion set. If both sets are empty, the score is exactly 1.0. Otherwise, let the inclusion pass fraction be the number of inclusion criteria whose predicate holds divided by the count of inclusion criteria, and let the exclusion clear fraction be the number of exclusion criteria whose predicate does not hold divided by the count of exclusion criteria. When both sets are non-empty, the raw score is the inclusion pass fraction weighted by 0.6 plus the exclusion clear fraction weighted by 0.4. When only the inclusion set is non-empty, the raw score is the inclusion pass fraction alone (the lone present category takes full weight); when only the exclusion set is non-empty, the raw score is the exclusion clear fraction alone. The stored `match_score` is the raw score clamped to a maximum of 1.0 and then rounded to four decimal places using round-half-up — the clamp to 1.0 is applied before the rounding.

### 3.4. From Screening to an Active Enrollment

A `CoordinatorStaff` creates an **Enrollment** from an eligible screening by supplying the `screening_id`. The referenced screening must have `match_result` of `ELIGIBLE` for the trial in question; otherwise the creation is rejected with `ERR_SCREENING_NOT_ELIGIBLE` (HTTP 409). The enrollment copies its `trial_id` and `participant_id` from the screening and begins with `enrollment_status` `SCREENED` and `safety_status` `CLEAR`, with a null `arm_id`, a null `signed_consent_document_id`, a null `signed_consent_version`, and a `completed_visits_count` of 0.

Enrollment creation re-runs the eligibility match live. The same predicates are re-evaluated against the participant's field values at enrollment time. If the participant's fields have changed since screening so that the live evaluation now yields `INELIGIBLE` even though the stored screening said `ELIGIBLE`, the enrollment is rejected with `ERR_ELIGIBILITY_DRIFTED` (HTTP 409) — the frozen snapshot and the live value have diverged.

The enrollment's primary lifecycle dimension, `enrollment_status`, advances through `SCREENED`, `CONSENTED`, `RANDOMIZED`, `ACTIVE`, and `COMPLETED`, with `WITHDRAWN` as an alternate terminal state. A `CoordinatorStaff` drives these transitions, each by naming an action.

**Consent** advances `SCREENED → CONSENTED`. It requires the enrollment to be `SCREENED`, the trial's `posture` to be `OPEN`, and a `consent_document_id` naming a consent document that is `ACTIVE`, belongs to this trial, and whose `version_number` equals the trial's current `ACTIVE` consent version. A consent document that is not the trial's current active version — wrong status, wrong trial, or stale version number — is rejected with `ERR_CONSENT_VERSION_MISMATCH` (HTTP 409). On success the server sets `signed_consent_document_id` to the named document and `signed_consent_version` to that document's `version_number`, sets `enrollment_status` to `CONSENTED`, and increments the enrollment's `version` by one. Because consent requires `posture` to be `OPEN`, an attempt while the trial is `SETUP` or `FROZEN` is rejected with `ERR_TRIAL_NOT_OPEN` (HTTP 409).

**Randomize** advances `CONSENTED → RANDOMIZED`. It requires the enrollment to be `CONSENTED`, the enrollment's `safety_status` to be `CLEAR`, the trial's `posture` to be `OPEN`, the trial's `enrolled_count` to be strictly less than its `target_enrollment`, and the `expected_trial_version` to match the trial's current `version`. A trial that is not `OPEN` rejects with `ERR_TRIAL_NOT_OPEN`; a trial whose `enrolled_count` has reached `target_enrollment` rejects with `ERR_TRIAL_AT_CAPACITY` (HTTP 409); a stale `expected_trial_version` rejects with `ERR_STALE_TRIAL_VERSION`. On success the system selects a randomization arm by the allocation policy described below, sets the enrollment's `arm_id`, sets `enrollment_status` to `RANDOMIZED`, increments the chosen arm's `assigned_count` by one, increments the trial's `enrolled_count` by one, recomputes the trial's `posture`, increments the enrollment's `version` by one, and increments the trial's `version` by one.

The **arm selection policy** is deterministic — there is no random number generator, so the assignment is reproducible. From all randomization arms of the trial, the system picks the arm most under its fair share. An arm's fair share is the trial's `target_enrollment` multiplied by that arm's `allocation_weight` divided by the sum of all arms' `allocation_weight`. An arm's deficit is its fair share minus its current `assigned_count`. The system chooses the arm with the largest deficit. For a `PERMUTED_BLOCK` trial, the fair share is computed within the current block of size `block_size`, where the block index is the trial's `enrolled_count` divided by `block_size` and rounded down to a whole number, and deficits reset at each block boundary. When two arms tie on deficit, the system picks the arm with the smaller `created_at`; ties are never broken by `id`. If randomization is somehow reached with a trial that has zero arms, it is rejected with `ERR_TRIAL_NOT_CONFIGURED` (HTTP 409).

**Activate** advances `RANDOMIZED → ACTIVE`. It requires the enrollment to be `RANDOMIZED` and its `safety_status` not to be `HOLD`, then sets `enrollment_status` to `ACTIVE` and increments the enrollment's `version` by one. **Complete** advances `ACTIVE → COMPLETED`. It requires the enrollment to be `ACTIVE`, no visit of the enrollment to remain in `SCHEDULED` status (all visits resolved), and the enrollment's `safety_status` not to be `HOLD`; it then sets `enrollment_status` to `COMPLETED` and increments the enrollment's `version` by one. An enrollment on a safety hold cannot be randomized, activated, completed, or have a visit completed — any of those is rejected with `ERR_ENROLLMENT_ON_HOLD` (HTTP 409).

**Withdraw** moves the enrollment to `WITHDRAWN`. Although it is framed as the `SCREENED → WITHDRAWN` edge, withdrawal is permitted from any of the four non-terminal states — `SCREENED`, `CONSENTED`, `RANDOMIZED`, or `ACTIVE`. On withdrawal the server sets `enrollment_status` to `WITHDRAWN`; if the enrollment was in `RANDOMIZED` or `ACTIVE`, it also decrements that enrollment's randomization arm's `assigned_count` by one and decrements the trial's `enrolled_count` by one as a compensating cascade; it cancels every visit of the enrollment that is still `SCHEDULED` (setting their `status` to `CANCELLED`); it recomputes the trial's `posture`; and it increments the enrollment's `version` by one. The arm and count compensation fires only for enrollments that had reached `RANDOMIZED` or `ACTIVE`.

Finally, the reconsent edge: when the consent document an enrollment signed is superseded (see §3.2), an enrollment that is currently `CONSENTED` is returned `CONSENTED → SCREENED`. That reconsent clears both `signed_consent_document_id` and `signed_consent_version` (setting them null), sets `enrollment_status` back to `SCREENED`, and increments the enrollment's `version` by one. The participant must consent again to the new active version.

### 3.5. Safety: Adverse Events and the Independent Hold

An enrollment's `safety_status` is a second, fully independent dimension that evolves on its own track through `CLEAR`, `FLAGGED`, and `HOLD`, driven entirely by adverse events rather than by the lifecycle transitions of §3.4.

An `Investigator` reports an **adverse event** against an enrollment by supplying the `severity` — one of `MILD`, `MODERATE`, `SEVERE`, or `LIFE_THREATENING` — the `occurred_at` instant, and an optional `is_serious` flag (whether the event meets the regulatory serious-adverse-event definition) that defaults to false. The server records the reporting operator as `reporter_user_id` and begins the event with `report_status` `REPORTED` and a null `adjudicator_user_id`.

A `SafetyOfficer` — never the investigator who reported it — reviews the event. The reviewing officer's `X-User-ID` must not equal the event's `reporter_user_id`; otherwise the review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The review endpoint takes an `action`. **Triage** moves the event `REPORTED → UNDER_REVIEW`; as a cascade, if the parent enrollment's `safety_status` is `CLEAR`, the enrollment transitions `CLEAR → FLAGGED`. **Adjudicate** moves the event from `UNDER_REVIEW` to one of two terminal states according to its `relation`. With `relation` `RELATED`, the event becomes `ADJUDICATED_RELATED` and the adjudicating officer is recorded as `adjudicator_user_id`; if the event's `severity` is `SEVERE` or `LIFE_THREATENING`, this further cascades the enrollment `FLAGGED → HOLD`. With `relation` `UNRELATED`, the event becomes `ADJUDICATED_UNRELATED`, the adjudicator is recorded, and if no other adverse event on the enrollment remains in `REPORTED` or `UNDER_REVIEW`, the enrollment transitions `FLAGGED → CLEAR`. Every triage and adjudication increments the adverse event's `version` by one.

The hold cascade reaches all the way to the trial. When an enrollment goes `FLAGGED → HOLD`, the system increments the trial's `active_safety_holds` by one and recomputes the trial's `posture`, which becomes `FROZEN` because at least one hold is now active. This is a depth-three chain: adjudicating a related severe or life-threatening event places the enrollment on hold, which increments the trial's hold count, which freezes the trial — and a `FROZEN` trial blocks new consent and randomization transitions across all its enrollments, the same `ERR_TRIAL_NOT_OPEN` gate from §3.4.

A `SafetyOfficer` lifts a hold once the danger has been adjudicated. Lifting requires the enrollment's `safety_status` to be `HOLD` and every adverse event on that enrollment to be in `ADJUDICATED_RELATED` or `ADJUDICATED_UNRELATED` (none still `REPORTED` or `UNDER_REVIEW`). Lifting sets `safety_status` back to `CLEAR`, decrements the trial's `active_safety_holds` by one as a compensating cascade, recomputes the trial's `posture` (which returns to `OPEN` when the hold count reaches 0 and `irb_status` is `APPROVED` and an `ACTIVE` consent exists), and increments the enrollment's `version` by one. Separately, the system itself clears a flag without a hold: when an adverse event is adjudicated unrelated and no other event keeps the enrollment flagged, the enrollment returns `FLAGGED → CLEAR` and its `version` increments.

### 3.6. Study Visits and the Blood-Draw Window

A `CoordinatorStaff` schedules a **visit** under an enrollment by supplying a `sequence_index` (a one-based ordinal of at least 1 that must be unique within the enrollment), a `scheduled_at` instant that is the center of the blood-draw window, and a `draw_window_minutes` half-width (at least 0). The visit records the enrollment it belongs to as `enrollment_id`, the same back-pointer that ties adverse events and compensation payments to their enrollment. A visit begins with `status` `SCHEDULED`, a null `drawn_at`, a `draw_in_window` of false, a null `draw_deviation_minutes`, and a `payable_amount_cents` of 0.

Two constraints guard scheduling. A `sequence_index` that already exists for the enrollment is rejected with `ERR_DUPLICATE_VISIT_INDEX` (HTTP 409). And no two visits of the same enrollment may have overlapping blood-draw windows: for any two visits, the absolute difference between their `scheduled_at` instants, measured in minutes, must be at least the sum of their two `draw_window_minutes` half-widths — windows are permitted to touch exactly at the boundary, but any closer overlap is rejected with `ERR_VISIT_WINDOW_OVERLAP` (HTTP 409).

A `CoordinatorStaff` completes a `SCHEDULED` visit by supplying the actual `drawn_at` blood-draw time. Completion requires the visit to be `SCHEDULED`, the parent enrollment's `enrollment_status` to be `ACTIVE`, the parent enrollment's `safety_status` not to be `HOLD` (otherwise `ERR_ENROLLMENT_ON_HOLD`), and the supplied `drawn_at` to fall inside the blood-draw window. The window is half-open: with the scheduled time as center and the half-width `w` equal to `draw_window_minutes`, the acceptable interval runs from `scheduled_at` minus `w` minutes inclusive up to `scheduled_at` plus `w` minutes exclusive. A draw exactly at the lower bound is in the window; a draw exactly at the upper bound is out of it. A draw outside this half-open window is rejected with `ERR_DRAW_OUT_OF_WINDOW` (HTTP 409). On completion the server records `drawn_at`, computes `draw_in_window` as whether the draw fell inside that half-open interval, and computes `draw_deviation_minutes` as the absolute difference between `drawn_at` and `scheduled_at` expressed in whole minutes with any fraction floored. It then sets `status` to `COMPLETED`, sets `payable_amount_cents` by the compensation rule below, increments the parent enrollment's `completed_visits_count` by one, and increments the visit's `version` by one. A visit may also be cancelled — set to `CANCELLED` — by the system when its parent enrollment withdraws; its `version` increments on that change.

The **visit compensation** owed for a completed visit is an exact integer amount in cents with no rounding at this level. It is the sum of three parts. The base is 7500 cents per completed visit. A timeliness bonus depends on the visit's `draw_deviation_minutes`: when the deviation is at most 15 minutes the bonus is the full 2500 cents; when the deviation is greater than 15 minutes but at most 60 minutes the bonus is the reduced 1000 cents; when the deviation exceeds 60 minutes there is no bonus. A mileage component adds 1200 cents for each visit beyond the first, computed as 1200 multiplied by the greater of 0 and the visit's `sequence_index` minus 1. The stored `payable_amount_cents` is the sum of base, bonus, and mileage.

### 3.7. Compensation Payments

A `Sponsor` sweeps a participant's completed, previously-unpaid visits into a **compensation payment**. The sweep gathers every visit of the enrollment whose `status` is `COMPLETED` and whose `id` is not already attached to any prior compensation payment (in either `PENDING` or `PAID` status). If no such visit exists, the sweep is rejected with `ERR_NO_PAYABLE_VISITS` (HTTP 409). The swept visits are processed in ascending `sequence_index` order (which is unique per enrollment, so there are no ties), and their identifiers are recorded on the payment as `visit_ids`.

The payment's `gross_cents` is the sum of the `payable_amount_cents` of the swept visits — summed first, because each per-visit value is already exact. The withholding tier is then keyed on that gross subtotal: when `gross_cents` is at least the threshold of 30000 cents, the withholding is the gross multiplied by the high rate of 0.10; below the threshold the withholding is the gross multiplied by the low rate of 0.0. Either way the withholding is the gross-times-rate product rounded to whole cents using round-half-up — the rounding is applied once to that product, never per visit. The payment's `amount_cents` is then `gross_cents` minus the withholding. The evaluation order is fixed: compute the gross, then select the tier from the gross, then compute the net. A new payment begins with `status` `PENDING`.

A withdrawn participant's residual compensation is never withheld. When the enrollment being swept is `WITHDRAWN`, the same visit set and the same gross apply, but the withholding rate is forced to the low rate of 0.0 regardless of the gross — diverging from the standard sweep precisely at a gross that would otherwise meet or exceed the threshold. For an enrollment that is `ACTIVE` or `COMPLETED`, the standard tiering by gross applies.

A `Sponsor` marks a `PENDING` payment as `PAID`. This applies only to a payment currently in `PENDING`; an attempt to pay a payment that is not pending is rejected with `ERR_PAYMENT_NOT_PENDING` (HTTP 409). Paying sets the payment's `status` to `PAID` and increments the payment's `version` by one.

### 3.8. The Test-Driving Clock

Because the window and temporal checks depend on the current time, an administrative capability lets any of the five roles set the server's logical UTC clock to a supplied instant, named `to_iso8601`. This clock is the reference the blood-draw window and other temporal evaluations read; setting it has no effect on stored resources beyond moving the reference clock.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — every transition, decision, review, activation, completion, lift, or payment action — return `200 OK`. The clock-setting capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | Sponsor, CoordinatorStaff, IRBReviewer, SafetyOfficer, Investigator |
| POST | `/trials` | Create a trial | Sponsor |
| GET | `/trials/{id}` | Fetch a trial with its computed fields | Sponsor, CoordinatorStaff, IRBReviewer, SafetyOfficer |
| POST | `/trials/{id}/criteria` | Add an eligibility criterion | Sponsor |
| GET | `/trials/{id}/criteria` | List the trial's eligibility criteria | Sponsor, CoordinatorStaff, IRBReviewer, SafetyOfficer |
| POST | `/trials/{id}/arms` | Add a randomization arm | Sponsor |
| GET | `/trials/{id}/arms` | List the trial's arms | Sponsor, CoordinatorStaff, IRBReviewer, SafetyOfficer |
| POST | `/trials/{id}/consent-documents` | Create a DRAFT consent document | Sponsor |
| GET | `/trials/{id}/consent-documents` | List the trial's consent documents | Sponsor, CoordinatorStaff, IRBReviewer, SafetyOfficer |
| POST | `/trials/{id}/consent-documents/{docId}/activate` | Activate an IRB-approved consent version | Sponsor |
| POST | `/trials/{id}/irb-reviews` | Open an IRB review | Sponsor |
| GET | `/trials/{id}/irb-reviews` | List the trial's IRB reviews | Sponsor, CoordinatorStaff, IRBReviewer, SafetyOfficer |
| POST | `/trials/{id}/irb-reviews/{reviewId}/decide` | Decide a pending IRB review | IRBReviewer |
| POST | `/participants` | Register a participant | CoordinatorStaff |
| PATCH | `/participants/{id}` | Update mutable participant attributes | CoordinatorStaff |
| POST | `/trials/{id}/screen-participant` | Screen a participant against the trial | CoordinatorStaff |
| GET | `/screenings/{id}` | Fetch a single screening | CoordinatorStaff, Sponsor |
| GET | `/screenings` | List screenings | CoordinatorStaff, Sponsor |
| POST | `/enrollments` | Create an enrollment from an eligible screening | CoordinatorStaff |
| GET | `/enrollments/{id}` | Fetch an enrollment | CoordinatorStaff, Sponsor, SafetyOfficer |
| GET | `/enrollments` | List enrollments | CoordinatorStaff, Sponsor, SafetyOfficer |
| POST | `/enrollments/{id}/transition` | Drive the enrollment lifecycle | CoordinatorStaff |
| POST | `/enrollments/{id}/lift-hold` | Lift a safety hold | SafetyOfficer |
| POST | `/enrollments/{id}/visits` | Schedule a visit | CoordinatorStaff |
| GET | `/enrollments/{id}/visits` | List the enrollment's visits | CoordinatorStaff, Sponsor, SafetyOfficer |
| POST | `/visits/{id}/complete` | Complete a scheduled visit | CoordinatorStaff |
| POST | `/enrollments/{id}/adverse-events` | Report an adverse event | Investigator |
| GET | `/enrollments/{id}/adverse-events` | List the enrollment's adverse events | CoordinatorStaff, Sponsor, SafetyOfficer, Investigator |
| POST | `/adverse-events/{id}/review` | Triage or adjudicate an adverse event | SafetyOfficer |
| POST | `/enrollments/{id}/payments` | Sweep completed visits into a payment | Sponsor |
| GET | `/enrollments/{id}/payments` | List the enrollment's payments | Sponsor, CoordinatorStaff |
| POST | `/payments/{id}/pay` | Mark a pending payment paid | Sponsor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ACTION` | 400 |
| `ERR_MISSING_ACTION_FIELD` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REVISE_NOT_DECIDABLE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_TRIAL_NOT_OPEN` | 409 |
| `ERR_ENROLLMENT_ON_HOLD` | 409 |
| `ERR_CONSENT_VERSION_MISMATCH` | 409 |
| `ERR_ELIGIBILITY_DRIFTED` | 409 |
| `ERR_SCREENING_NOT_ELIGIBLE` | 409 |
| `ERR_TRIAL_NOT_CONFIGURED` | 409 |
| `ERR_DRAW_OUT_OF_WINDOW` | 409 |
| `ERR_VISIT_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_VISIT_INDEX` | 409 |
| `ERR_REVIEW_ALREADY_OPEN` | 409 |
| `ERR_TRIAL_AT_CAPACITY` | 409 |
| `ERR_STALE_TRIAL_VERSION` | 412 |
| `ERR_NO_PAYABLE_VISITS` | 409 |
| `ERR_PAYMENT_NOT_PENDING` | 409 |
| `ERR_TRIAL_NOT_IN_SETUP` | 409 |

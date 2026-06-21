# Foundation Scholarship Management API — Product Requirements Document

## 1. Introduction

Charitable foundations that endow scholarships sit at the intersection of three pressures: a finite pool of endowment money that must never be over-committed, a fairness mandate that demands every applicant be measured against the same published criteria and the same scoring rubric, and a stewardship obligation that ties each disbursed dollar back to a named recipient and a documented thank-you. This document specifies the Foundation Scholarship Management API, the back-office system that carries a scholarship program end to end: standing up a fund and its eligibility rules, intake of student applications with recommendation letters and registrar transcripts, committee review under a weighted rubric, the award decision, disbursement of money to the recipient's institution, GPA-conditioned renewal across academic terms, and the closing-the-loop stewardship record.

The system serves four distinct constituencies whose authority is deliberately partitioned. Foundation staff shape the fund, drive the review lifecycle, and make award and renewal decisions. Students register, assemble, and submit their own applications and later acknowledge the awards they receive. Committee members review only the applications assigned to them and record rubric scores. A finance operator moves committed money to institutions and reconciles settlements and returns. Underpinning all of this is a fund ledger that is the single arithmetic source of truth for what has been committed versus what remains available, and an optimistic-concurrency guard that prevents two award decisions from each spending budget the other assumed was free. The sections that follow define the global contract first, then the business workflows, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing or invalid, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`. The system recognizes exactly four roles, spelled precisely as follows: `FoundationAdmin`, `Applicant`, `CommitteeMember`, and `DisbursementOfficer`. When a syntactically valid request is made by a role that is not permitted to perform the operation, the system responds with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an applicant compare the resource's `applicant_id` foreign key to `X-User-ID`. Because applications own their uploads (recommendations, transcripts) and their stewardship records, an applicant's ownership of those child resources is established transitively through the owning application's `applicant_id`. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the acting `CommitteeMember`; ownership checks on a rubric score or a committee assignment compare the resource's `committee_member_id` foreign key to `X-User-ID`. By contrast, when `X-User-Role` is `FoundationAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `DisbursementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.

Ownership violations are surfaced with role-specific codes. An applicant acting on an application or its child resource they do not own is rejected with `ERR_NOT_APPLICATION_OWNER`. A committee member acting on a rubric score they do not own is rejected with `ERR_NOT_SCORE_OWNER`, and on a committee assignment they do not own with `ERR_NOT_ASSIGNMENT_OWNER`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Request-Ordering Discipline

Most resources in this system carry a standard set of system-managed fields. Every such resource exposes an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording first creation, an `updated_at` timestamp (same format) recording the last modification, and a `version` integer that begins at 1 and increments by one on every mutation. These four fields appear on scholarship funds, eligibility criteria, applicants, applications, committee members, committee assignments, rubric scores, awards, disbursements, renewal reviews, and stewardship records.

Two entity types are exceptions: recommendation and transcript records are immutable upload artifacts. Each carries only an `id` and a `created_at`; neither `updated_at` nor `version` is present on a recommendation or a transcript, because once uploaded they are never modified.

Many operations resolve foreign keys through the request path or body. When a request targets a resource by an identifier — whether in the URL path or as a foreign key in the body — the system validates existence left to right and rejects the request at the first identifier that does not resolve. A path resource that does not exist yields a not-found error specific to its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, or `ERR_STEWARDSHIP_NOT_FOUND`. Body foreign keys on create endpoints are subject to the same existence check: an unresolved `fund_id` raises `ERR_FUND_NOT_FOUND`, an unresolved `applicant_id` raises `ERR_APPLICANT_NOT_FOUND`, an unresolved `application_id` raises `ERR_APPLICATION_NOT_FOUND`, an unresolved `award_id` raises `ERR_AWARD_NOT_FOUND`, and an unresolved `committee_member_id` raises `ERR_COMMITTEE_MEMBER_NOT_FOUND`.

### 2.5. The Order in Which Checks Are Applied

When several conditions could each reject a request, they are evaluated in a fixed priority so that the returned `error_id` is deterministic. Authentication comes first: a missing or invalid user context (`ERR_MISSING_OR_INVALID_USER_CONTEXT`) is detected before anything else. Role authorization is second: a role not permitted for the operation (`ERR_FORBIDDEN_ROLE`) is rejected before any resource is loaded. Third, path resource existence is checked left to right, yielding the relevant not-found code. Fourth, body foreign keys are checked for existence. Fifth, ownership is enforced for entity-backed roles — an applicant must own the target application or its child resource, and a committee member must own the target rubric score or assignment, failing with `ERR_NOT_APPLICATION_OWNER`, `ERR_NOT_SCORE_OWNER`, or `ERR_NOT_ASSIGNMENT_OWNER` respectively. Sixth, the parent scholarship fund must be in the lifecycle state the operation requires (`ERR_FUND_NOT_OPEN`, `ERR_FUND_NOT_IN_REVIEW`, `ERR_FUND_NOT_AWARDING`, or `ERR_FUND_STATE_INVALID`). Seventh, the target resource's own state is checked. Only after all of these structural gates do the domain-specific business constraints, fiscal checks, the optimistic-concurrency check, and finally field-level input validation apply, in the order described in the workflow sections below. Field-level input validation — required fields present, correct types, numeric ranges, enum membership, and pagination bounds — is the lowest-priority class and raises `ERR_INVALID_REQUEST` (or `ERR_INVALID_PAGINATION` for out-of-range pagination parameters).

### 2.6. Hierarchical Consistency and Cascades

Several operations mutate more than one resource in a single logical step. Whenever a transition advances or reverts an entity, that entity's `updated_at` is refreshed and its `version` increments by one. When an operation also touches a second entity — for example, an award that debits its fund, or a finalize-scoring step that completes the committee assignments attached to an application — every affected entity is independently mutated, so each one's `updated_at` and `version` move accordingly. These cascades are described in full within the workflow narratives of §3; the governing rule here is that no secondary effect is silent: if a transition is documented as changing a sibling or parent resource, that change actually occurs and is reflected in the affected resource's audit fields. The fund's derived monetary fields (`committed_cents`, `disbursed_cents`, `available_cents`) are recomputed as part of any ledger-affecting cascade and are never set directly by a client.

### 2.7. The Fund Ledger Principle

Each scholarship fund maintains three read-only derived monetary fields that together form its ledger, all expressed in integer cents. The `committed_cents` field is the sum of `provisional_award_cents` over every award on the fund whose status is `COMMITTED`, `ACTIVE`, or `RENEWAL_PENDING`. The `disbursed_cents` field is the sum of `amount_cents` over every disbursement on the fund whose status is `SETTLED`. The `available_cents` field equals the fund's `endowment_cents` minus its `committed_cents`. Evaluation order matters: `committed_cents` is computed first, and `available_cents` is derived from it. These are pure sums over integer cents with no rounding — the inputs are already integers and the result is exact. The ledger is fully recomputed on each triggering side effect: an award commitment, an award revoke, a renewal approval, a renewal denial, and a disbursement settle or return all force a recomputation. A core invariant holds: a forward award followed by its revoke leaves `committed_cents` exactly as it was before, and a settle followed by its return leaves both `disbursed_cents` and `committed_cents` exactly as they were before.

### 2.8. Monetary and GPA Precision

All money is stored and computed in integer cents. Where a calculation multiplies an integer-cent amount by a fractional multiplier or factor, the result is rounded half up to the nearest whole cent before any subsequent capping step is applied. There is no sub-cent representation in any response.

GPA values are decimal numbers in the range from 0.00 to 4.00 and are compared at two decimal places. All GPA threshold comparisons in this system are inclusive at the boundary: an applicant whose GPA exactly equals the relevant floor satisfies that floor.

### 2.9. Optimistic Concurrency Control on Award Commitment

Awarding an application debits the owning fund's `committed_cents` and therefore advances that fund's `version`. To prevent a writer from spending budget that an earlier award already consumed, the award operation is guarded by optimistic concurrency control on the scholarship fund. The award request must carry `expected_fund_version` as a non-optional input field, holding the `version` of the fund that the client last observed. If `expected_fund_version` does not equal the fund's current `version`, the award is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412). The intent is precise: if another award has advanced the fund's version since the client last read it, the `available_cents` figure the client reasoned about no longer reflects the true committed total, so the stale request must be refused rather than allowed to overwrite a commitment it never observed. No other endpoint in the system takes a version field; the award endpoint is the only optimistic-concurrency-guarded write.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Fund and Its Eligibility Criteria

A `FoundationAdmin` begins by creating a scholarship fund, supplying a `fund_name` and an `endowment_cents` total (which must be at least 0). The disbursement term label `award_term` may be supplied; it is one of `FALL`, `SPRING`, or `SUMMER`, and defaults to `FALL` when omitted. A freshly created fund opens in `DRAFT` status with `committed_cents` set to 0, `disbursed_cents` set to 0, `available_cents` equal to the full `endowment_cents`, and `version` at 1.

While the fund is still in `DRAFT`, the administrator attaches its eligibility rule set by creating an eligibility-criteria record that references the fund through `fund_id`. The criteria carry a `min_gpa` (a GPA between 0.00 and 4.00 at two decimals), a `required_residency_state` (a two-letter state code the applicant must match exactly, or the sentinel `ANY`), a `required_field_of_study` (a field the applicant must match exactly, or `ANY`), and a `max_award_cents` ceiling (which must be greater than 0) capping any single award drawn from this fund. A fund may have at most one criteria record: an attempt to attach a second criteria to a fund that already has one is rejected with `ERR_DUPLICATE_CRITERIA`.

The fund's lifecycle then advances through four administrator-driven transitions. Opening the fund moves it from `DRAFT` to `OPEN`; this requires the fund to currently be in `DRAFT` (otherwise `ERR_FUND_STATE_INVALID`) and requires that exactly one eligibility criteria is attached (otherwise `ERR_CRITERIA_REQUIRED`). Beginning review moves the fund from `OPEN` to `REVIEW` and requires the fund to be `OPEN` (otherwise `ERR_FUND_NOT_OPEN`). Beginning awarding moves the fund from `REVIEW` to `AWARDING` and requires the fund to be in `REVIEW` (otherwise `ERR_FUND_NOT_IN_REVIEW`). Closing the fund moves it from `AWARDING` to the terminal `CLOSED` state and requires the fund to be in `AWARDING` (otherwise `ERR_FUND_NOT_AWARDING`); closing is additionally blocked while any application on the fund remains in `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_REVISION`, or `SCORED`, in which case the request fails with `ERR_OPEN_APPLICATIONS_EXIST`.

### 3.2. Applicants, Committee Members, and Application Intake

Anyone registering as an `Applicant` (or a `FoundationAdmin` acting on their behalf) creates an applicant record with a `full_name`, an `email`, a `self_reported_gpa` (between 0.00 and 4.00), a `residency_state` two-letter code, a declared `field_of_study`, and an `institution_id` identifying the school they attend. The self-reported GPA captured here is not the figure used for eligibility — that comes from the registrar transcript, as described below.

Committee members register with a `full_name`, an `email`, and an `expertise_field`. Each committee member carries a read-only `active_assignment_count` that starts at 0 on registration and reflects, at all times, the number of that member's committee assignments currently in `ASSIGNED` status.

An application is created against a fund that must currently be `OPEN`. The creator (an applicant for their own application, or a `FoundationAdmin` on their behalf) supplies the `fund_id`, the `applicant_id`, and a `requested_amount_cents` (which must be greater than 0). A new application opens in `DRAFT` with `revision_round` at 0; its `eligibility_matched` is null and its `eligibility_failures`, `rubric_total`, are not yet computed until the relevant later steps. While the application is still in `DRAFT`, supporting documents are uploaded: a recommendation references its application via `application_id` and carries a `recommender_name` and a `document_uri`; a transcript references its application via `application_id` and carries a `document_uri` together with the registrar-verified `verified_gpa` (between 0.00 and 4.00, two decimals). An application may hold many recommendations but at most one transcript — uploading a second transcript for the same application is rejected with `ERR_DUPLICATE_TRANSCRIPT`.

### 3.3. Submitting an Application and the Eligibility Match

Submission is performed by the owning applicant and moves the application from `DRAFT` to `SUBMITTED`. Following the global check ordering of §2.5, the system first requires that the acting applicant owns it — that is, `X-User-ID` equals the application's `applicant_id` (otherwise `ERR_NOT_APPLICATION_OWNER`); then that the owning fund is `OPEN` at submission time (otherwise `ERR_FUND_NOT_OPEN`); and only then that the application is in `DRAFT` (otherwise `ERR_APPLICATION_STATE_INVALID`). Thus the fund-state gate takes precedence over the application's own state gate, so a request on a non-`DRAFT` application whose fund is not `OPEN` yields `ERR_FUND_NOT_OPEN`. The application must carry at least one recommendation (otherwise `ERR_RECOMMENDATION_REQUIRED`) and must carry exactly one transcript (otherwise `ERR_TRANSCRIPT_REQUIRED`).

Upon a successful submission, the system computes the application's eligibility against the fund's single eligibility criteria, evaluating three independent criteria and recording any failures. Critically, the GPA test uses the registrar-verified GPA from the transcript (`verified_gpa`), never the applicant's `self_reported_gpa`. The GPA criterion passes when the transcript's `verified_gpa` is at least the criteria's `min_gpa` (an inclusive comparison at the boundary). The residency criterion passes when the criteria's `required_residency_state` is `ANY`, or when the applicant's `residency_state` exactly equals `required_residency_state`. The field criterion passes when the criteria's `required_field_of_study` is `ANY`, or when the applicant's `field_of_study` exactly equals `required_field_of_study`. The read-only `eligibility_failures` array lists the codes of the failing criteria — drawn from `GPA`, `RESIDENCY`, and `FIELD` — appended in that fixed order: a GPA failure is listed before a residency failure, which is listed before a field failure. The read-only `eligibility_matched` flag is set to true exactly when `eligibility_failures` is empty, and false otherwise.

An applicant may withdraw their own application while it is in `DRAFT`, `SUBMITTED`, or `NEEDS_REVISION`, moving it to the terminal `WITHDRAWN` state; any other current state yields `ERR_APPLICATION_STATE_INVALID`, and a non-owner is refused with `ERR_NOT_APPLICATION_OWNER`. Withdrawing an application cascades to its committee assignments: every assignment on it that is in `ASSIGNED` status transitions to `REVOKED`, and each affected member's `active_assignment_count` is recomputed downward to reflect the removed assignment.

### 3.4. Committee Assignment and Rubric Scoring

A `FoundationAdmin` assigns reviewers by creating committee assignments, each referencing an `application_id` and a `committee_member_id`; a new assignment opens in `ASSIGNED` status, and the assigned member's `active_assignment_count` is recomputed upward. Two guards apply at assignment time: a member who already holds an `ASSIGNED` assignment on the same application cannot be assigned again, which is rejected with `ERR_DUPLICATE_ASSIGNMENT`; and a member who already holds the maximum number of concurrent `ASSIGNED` assignments across all applications — a cap of three concurrent assignments — cannot take on another, which is rejected with `ERR_MEMBER_OVERLOADED`. A committee member may decline their own assignment while it is `ASSIGNED`, moving it to the terminal `DECLINED` state; this requires that the assignment is `ASSIGNED` (otherwise `ERR_ASSIGNMENT_STATE_INVALID`) and that the acting member owns it, meaning `X-User-ID` equals the assignment's `committee_member_id` (otherwise `ERR_NOT_ASSIGNMENT_OWNER`), and it recomputes the member's `active_assignment_count` downward.

A committee member records scores by creating a rubric score that references the `application_id` and the member's own `committee_member_id` and carries three integer raw scores, each in the range from 0 to 100: an `academic_score` for academic merit, a `need_score` for financial need, and an `essay_score`. A rubric score opens in `DRAFT`. Creating a rubric score requires that the acting member holds an `ASSIGNED` committee assignment on the same application; without one the create is rejected with `ERR_NO_ASSIGNMENT_FOR_SCORE`.

Submitting a rubric score moves it from `DRAFT` to `SUBMITTED`. The submit requires that the score is in `DRAFT` (otherwise `ERR_SCORE_STATE_INVALID`), that the acting member owns it — `X-User-ID` equals the score's `committee_member_id` (otherwise `ERR_NOT_SCORE_OWNER`) — and that the parent application is in `UNDER_REVIEW` (otherwise `ERR_APPLICATION_NOT_UNDER_REVIEW`). On submission the system computes the score's read-only `weighted_value`: the `academic_score` is weighted at one half, the `need_score` at three tenths, and the `essay_score` at two tenths (these three weights sum to one), and the weighted sum is rounded half up to two decimal places. Because each raw input is an integer from 0 to 100, the resulting `weighted_value` lies between 0.00 and 100.00. A rubric score's `status` may also become `RETRACTED` automatically, as described in the review-loop narrative below.

### 3.5. The Review Loop: Start, Revise, and Finalize Scoring

A `FoundationAdmin` starts review of a submitted application, advancing it from `SUBMITTED` to `UNDER_REVIEW`. This requires that the application is currently in `SUBMITTED` (otherwise `ERR_APPLICATION_STATE_INVALID`), that the owning fund is in `REVIEW` (otherwise `ERR_FUND_NOT_IN_REVIEW`), that the application's `eligibility_matched` is true (otherwise `ERR_NOT_ELIGIBLE`), and that the application has at least one committee assignment in `ASSIGNED` status (otherwise `ERR_NO_COMMITTEE_ASSIGNED`).

During review the administrator may send the application back, moving it from `UNDER_REVIEW` to `NEEDS_REVISION`. This requires that the application is currently in `UNDER_REVIEW` (otherwise `ERR_APPLICATION_STATE_INVALID`). Two side effects accompany a revision request: the application's read-only `revision_round` counter is increased by one, and every rubric score on the application that is in `SUBMITTED` status is automatically transitioned to `RETRACTED` so that those scores leave the scoring pool. The application's `rubric_total` remains null through this step.

The same start-review action resumes a returned application, advancing it from `NEEDS_REVISION` back to `UNDER_REVIEW`. The resume requires that the application is in `NEEDS_REVISION` (otherwise `ERR_APPLICATION_STATE_INVALID`), that the owning fund is in `REVIEW` (otherwise `ERR_FUND_NOT_IN_REVIEW`), and that the `revision_round` count has not gone past the permitted ceiling of two revision rounds — resumption is allowed only while `revision_round` is at most two, and once it exceeds that ceiling the resume is blocked with `ERR_REVISION_LIMIT_REACHED`.

Finalizing scoring moves the application from `UNDER_REVIEW` to `SCORED`. It requires that the application is currently `UNDER_REVIEW` (otherwise `ERR_APPLICATION_STATE_INVALID`) and that the count of rubric scores in `SUBMITTED` status meets the scoring quorum of at least two submitted scores (otherwise `ERR_QUORUM_NOT_MET`). On success the system computes the application's `rubric_total` as the mean of `weighted_value` over the rubric scores in `SUBMITTED` status: the submitted weighted values are summed, that sum is divided by the count of submitted scores, and the quotient is rounded half up to two decimal places — a single rounding applied only at the very end, after the division. Retracted scores are excluded from this pool; the quorum precondition guarantees the count is never zero, so the division is always defined. Finalize-scoring also cascades to the committee: every committee assignment on the application that is in `ASSIGNED` status is transitioned to `COMPLETED`, and each affected member's `active_assignment_count` is recomputed downward.

### 3.6. The Award Decision and the Provisional Commitment

Once an application is `SCORED`, a `FoundationAdmin` may either reject it or award it. Rejection moves the application from `SCORED` to the terminal `REJECTED` state and requires that the application is currently `SCORED` (otherwise `ERR_APPLICATION_STATE_INVALID`).

Awarding moves the application from `SCORED` to the terminal `AWARDED` state and is the most heavily guarded operation in the system. The application must be `SCORED` (otherwise `ERR_APPLICATION_STATE_INVALID`); the owning fund must be in `AWARDING` (otherwise `ERR_FUND_NOT_AWARDING`); the application's `rubric_total` must clear the award score floor of 60, meaning a `rubric_total` of at least 60 (otherwise `ERR_SCORE_BELOW_FLOOR`); the amount about to be committed must not exceed the fund's current `available_cents` (otherwise `ERR_FUND_INSUFFICIENT`); and the supplied `expected_fund_version` must match the fund's current `version` (otherwise `ERR_STALE_FUND_VERSION`, HTTP 412, as detailed in §2.9).

The amount committed at award time is forward-looking — it projects merit from the rubric score and is computed before any disbursement occurs. The system selects a score-tier multiplier from the application's `rubric_total`: a `rubric_total` of at least 90 selects the high multiplier of 1.00; a `rubric_total` of at least 75 but below 90 selects the mid multiplier of 0.80; and a `rubric_total` of at least 60 but below 75 selects the low multiplier of 0.60. The applicant's `requested_amount_cents` is multiplied by the selected multiplier and the product is rounded half up to whole cents; that rounded raw amount is then capped at the fund criteria's `max_award_cents`, taking the smaller of the two. The result is recorded as the award's read-only `provisional_award_cents`. The available-budget comparison against `available_cents` is a separate precondition (`ERR_FUND_INSUFFICIENT`), not part of this amount computation.

A successful award creates an award record in `COMMITTED` status that references the awarded `application_id` and the funding `fund_id`. The award captures `provisional_award_cents` as just computed, copies the criteria's `min_gpa` into the award's read-only `renewal_gpa_floor` (freezing the renewal threshold so that later edits to the fund's criteria never move it), sets the read-only renewal counter `term_index` to 1, and leaves `final_award_cents` null until disbursement. As a cascade, the fund's `committed_cents` is increased by the award's `provisional_award_cents`, `available_cents` is recomputed, and the fund's `version` is incremented by one — the very increment that the optimistic-concurrency guard protects.

### 3.7. Stewardship and Disbursement to the Institution

Before money can move, the recipient must close the stewardship loop. A stewardship record is created for an award, referencing the `award_id` and carrying the recipient's `thank_you_text`; it opens in `DRAFT`. The owning applicant acknowledges it, moving it from `DRAFT` to the terminal `ACKNOWLEDGED` state; acknowledgement requires that the record is in `DRAFT` (otherwise `ERR_STEWARDSHIP_STATE_INVALID`) and that the acting applicant owns the parent application, meaning `X-User-ID` equals that application's `applicant_id` (otherwise `ERR_NOT_APPLICATION_OWNER`).

A `DisbursementOfficer` disburses a committed award, moving the award from `COMMITTED` to `ACTIVE`. The award must be `COMMITTED` (otherwise `ERR_AWARD_STATE_INVALID`), and the award must have exactly one stewardship record in `ACKNOWLEDGED` status (otherwise `ERR_STEWARDSHIP_REQUIRED`). The disbursement request supplies the `institution_id` of the school receiving the funds. At this moment the system computes the award's `final_award_cents` using a chronological, verified-GPA recalculation that differs deliberately from the provisional figure: where the provisional amount keyed off the rubric tier, the final amount keys off the registrar's verified GPA, which only becomes decision-relevant at disbursement. The system selects a GPA factor from the transcript's `verified_gpa`: a `verified_gpa` of at least 3.50 selects the high factor of 1.00; a `verified_gpa` of at least 3.00 but below 3.50 selects the mid factor of 0.90; and a `verified_gpa` below 3.00 selects the low factor of 0.80. The award's already-committed `provisional_award_cents` is multiplied by the selected factor, the product is rounded half up to whole cents, and the rounded raw amount is then capped at the fund criteria's `max_award_cents`, taking the smaller of the two; the result becomes `final_award_cents`. A disbursement record is created in `PENDING` status, referencing the `award_id`, the paying `fund_id`, and the `institution_id`, with its read-only `amount_cents` equal to the award's `final_award_cents` at this moment.

Settling a disbursement moves it from `PENDING` to the terminal `SETTLED` state and requires the disbursement to be `PENDING` (otherwise `ERR_DISBURSEMENT_STATE_INVALID`); on settle the paying fund's `disbursed_cents` is increased by the disbursement's `amount_cents` and the ledger is resynced. Returning a disbursement moves it to the terminal `RETURNED` state and behaves differently depending on the state it leaves. Returning a `PENDING` disbursement reverts its parent award from `ACTIVE` back to `COMMITTED` as a compensation that undoes the disburse transition, and resets the award's `final_award_cents` back to null; the commitment on the fund is unchanged. Returning a `SETTLED` disbursement is a deeper compensation: the fund's `disbursed_cents` is decreased by the disbursement's `amount_cents`, the fund's `committed_cents` is decreased by the award's `provisional_award_cents`, `available_cents` is recomputed, and the parent award cascades to the terminal `REVOKED` state. In both cases the return requires the disbursement to be in `PENDING` or in `SETTLED` respectively (otherwise `ERR_DISBURSEMENT_STATE_INVALID`).

### 3.8. GPA-Conditioned Renewal Across Terms

An active award can be renewed term over term, each renewal re-committing a term's worth of money subject to a sustained-GPA condition. A `FoundationAdmin` opens a renewal review, which moves the award from `ACTIVE` to `RENEWAL_PENDING`; this requires the award to be `ACTIVE` (otherwise `ERR_AWARD_NOT_ACTIVE`). The renewal review request supplies the `award_id` and the latest `reported_gpa` (between 0.00 and 4.00). On creation the review opens in `PENDING` and the system computes its read-only `meets_floor` flag, which is true exactly when the `reported_gpa` is at least the award's frozen `renewal_gpa_floor` (an inclusive comparison at the boundary) and false otherwise.

Approving a renewal review moves the award from `RENEWAL_PENDING` back to `ACTIVE` and re-commits a term. Approval requires that the award is in `RENEWAL_PENDING` (otherwise `ERR_AWARD_STATE_INVALID`), that the review's `meets_floor` is true (otherwise `ERR_GPA_BELOW_FLOOR`), and that the fund's `available_cents` is at least the award's `provisional_award_cents` (otherwise `ERR_FUND_INSUFFICIENT`). On approval the review's status becomes `APPROVED`, the award's `term_index` is increased by one, and the fund's `committed_cents` is increased by the award's `provisional_award_cents` with `available_cents` recomputed — the renewal re-commitment. Denying a renewal review moves the award from `RENEWAL_PENDING` to the terminal `LAPSED` state; denial requires the award to be in `RENEWAL_PENDING` (otherwise `ERR_AWARD_STATE_INVALID`). On denial the review's status becomes `DENIED`, and the fund's `committed_cents` is decreased by the award's `provisional_award_cents` with `available_cents` recomputed, releasing the current term's commitment.

Separately, a `FoundationAdmin` may complete an active award, moving it from `ACTIVE` to the terminal `COMPLETED` state; completion requires the award to be `ACTIVE` (otherwise `ERR_AWARD_STATE_INVALID`) and carries no ledger effect. An administrator may also revoke a committed award that has not yet been paid, moving it from `COMMITTED` to the terminal `REVOKED` state; revocation requires the award to be `COMMITTED` (otherwise `ERR_AWARD_STATE_INVALID`) and that no disbursement on the award is in `SETTLED` status (otherwise `ERR_AWARD_ALREADY_DISBURSED`). On revoke, the fund's `committed_cents` is decreased by the award's `provisional_award_cents` and `available_cents` is recomputed, releasing the commitment — the compensation that, paired with the original award, leaves the committed total unchanged.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example, creating a fund, attaching eligibility criteria, registering an actor, creating an application, uploading a recommendation or transcript, creating a committee assignment, creating a rubric score, awarding an application, disbursing an award, opening a renewal review, or creating a stewardship record) return a `201 Created` status code. Operations that modify an existing resource — including all lifecycle transitions driven by an action endpoint — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/scholarship-funds` | Create a scholarship fund | FoundationAdmin |
| GET | `/scholarship-funds` | List scholarship funds | FoundationAdmin, Applicant, CommitteeMember, DisbursementOfficer |
| GET | `/scholarship-funds/{fundId}` | Get a scholarship fund | FoundationAdmin, Applicant, CommitteeMember, DisbursementOfficer |
| POST | `/scholarship-funds/{fundId}/open` | Open fund for applications | FoundationAdmin |
| POST | `/scholarship-funds/{fundId}/begin-review` | Move fund to REVIEW | FoundationAdmin |
| POST | `/scholarship-funds/{fundId}/begin-awarding` | Move fund to AWARDING | FoundationAdmin |
| POST | `/scholarship-funds/{fundId}/close` | Close fund | FoundationAdmin |
| POST | `/eligibility-criteria` | Attach eligibility criteria to a fund | FoundationAdmin |
| GET | `/eligibility-criteria` | List eligibility criteria (filter by fund_id) | FoundationAdmin, Applicant, CommitteeMember, DisbursementOfficer |
| GET | `/eligibility-criteria/{criteriaId}` | Get an eligibility criteria | FoundationAdmin, Applicant, CommitteeMember, DisbursementOfficer |
| POST | `/applicants` | Register an applicant | FoundationAdmin, Applicant |
| GET | `/applicants` | List applicants | FoundationAdmin, CommitteeMember |
| GET | `/applicants/{applicantId}` | Get an applicant | FoundationAdmin, Applicant, CommitteeMember |
| POST | `/committee-members` | Register a committee member | FoundationAdmin, CommitteeMember |
| GET | `/committee-members` | List committee members | FoundationAdmin, CommitteeMember |
| GET | `/committee-members/{memberId}` | Get a committee member | FoundationAdmin, CommitteeMember |
| POST | `/applications` | Create an application against a fund | FoundationAdmin, Applicant |
| GET | `/applications` | List applications (filter by fund_id and/or applicant_id) | FoundationAdmin, Applicant, CommitteeMember |
| GET | `/applications/{applicationId}` | Get an application | FoundationAdmin, Applicant, CommitteeMember |
| POST | `/applications/{applicationId}/submit` | Submit an application | Applicant |
| POST | `/applications/{applicationId}/start-review` | Start or resume review | FoundationAdmin |
| POST | `/applications/{applicationId}/request-revision` | Send application back for revision | FoundationAdmin |
| POST | `/applications/{applicationId}/finalize-scoring` | Finalize scoring | FoundationAdmin |
| POST | `/applications/{applicationId}/award` | Award the application; creates an Award and debits the fund | FoundationAdmin |
| POST | `/applications/{applicationId}/reject` | Reject the application | FoundationAdmin |
| POST | `/applications/{applicationId}/withdraw` | Withdraw an application | Applicant |
| POST | `/recommendations` | Upload a recommendation | FoundationAdmin, Applicant |
| GET | `/recommendations` | List recommendations (filter by application_id) | FoundationAdmin, Applicant, CommitteeMember |
| GET | `/recommendations/{recommendationId}` | Get a recommendation | FoundationAdmin, Applicant, CommitteeMember |
| POST | `/transcripts` | Upload a transcript | FoundationAdmin, Applicant |
| GET | `/transcripts` | List transcripts (filter by application_id) | FoundationAdmin, Applicant, CommitteeMember |
| GET | `/transcripts/{transcriptId}` | Get a transcript | FoundationAdmin, Applicant, CommitteeMember |
| POST | `/committee-assignments` | Assign a committee member to an application | FoundationAdmin |
| GET | `/committee-assignments` | List committee assignments (filter by application_id and/or committee_member_id) | FoundationAdmin, CommitteeMember |
| GET | `/committee-assignments/{assignmentId}` | Get a committee assignment | FoundationAdmin, CommitteeMember |
| POST | `/committee-assignments/{assignmentId}/decline` | Committee member declines an assignment | CommitteeMember |
| POST | `/rubric-scores` | Create a draft rubric score | CommitteeMember |
| GET | `/rubric-scores` | List rubric scores (filter by application_id and/or committee_member_id) | FoundationAdmin, CommitteeMember |
| GET | `/rubric-scores/{scoreId}` | Get a rubric score | FoundationAdmin, CommitteeMember |
| POST | `/rubric-scores/{scoreId}/submit` | Submit a rubric score | CommitteeMember |
| GET | `/awards` | List awards (filter by fund_id and/or application_id) | FoundationAdmin, Applicant, DisbursementOfficer |
| GET | `/awards/{awardId}` | Get an award | FoundationAdmin, Applicant, DisbursementOfficer |
| POST | `/awards/{awardId}/disburse` | Disburse an award; creates a PENDING Disbursement | DisbursementOfficer |
| POST | `/awards/{awardId}/complete` | Mark award complete | FoundationAdmin |
| POST | `/awards/{awardId}/revoke` | Revoke a committed award; releases commitment | FoundationAdmin |
| GET | `/disbursements` | List disbursements (filter by award_id and/or fund_id) | FoundationAdmin, DisbursementOfficer |
| GET | `/disbursements/{disbursementId}` | Get a disbursement | FoundationAdmin, DisbursementOfficer |
| POST | `/disbursements/{disbursementId}/settle` | Settle a disbursement | DisbursementOfficer |
| POST | `/disbursements/{disbursementId}/return` | Return a disbursement; reverses ledgers | DisbursementOfficer |
| POST | `/renewal-reviews` | Open a GPA-conditioned renewal review | FoundationAdmin |
| GET | `/renewal-reviews` | List renewal reviews (filter by award_id) | FoundationAdmin, Applicant |
| GET | `/renewal-reviews/{reviewId}` | Get a renewal review | FoundationAdmin, Applicant |
| POST | `/renewal-reviews/{reviewId}/approve` | Approve renewal; re-commits a term | FoundationAdmin |
| POST | `/renewal-reviews/{reviewId}/deny` | Deny renewal; releases commitment | FoundationAdmin |
| POST | `/stewardship-records` | Create a stewardship / thank-you record for an award | FoundationAdmin, Applicant |
| GET | `/stewardship-records` | List stewardship records (filter by award_id) | FoundationAdmin, Applicant, DisbursementOfficer |
| GET | `/stewardship-records/{stewardshipId}` | Get a stewardship record | FoundationAdmin, Applicant, DisbursementOfficer |
| POST | `/stewardship-records/{stewardshipId}/acknowledge` | Acknowledge a stewardship record | Applicant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_APPLICATION_OWNER` | 403 Forbidden |
| `ERR_NOT_SCORE_OWNER` | 403 Forbidden |
| `ERR_NOT_ASSIGNMENT_OWNER` | 403 Forbidden |
| `ERR_FUND_NOT_FOUND` | 404 Not Found |
| `ERR_CRITERIA_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITTEE_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SCORE_NOT_FOUND` | 404 Not Found |
| `ERR_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RENEWAL_NOT_FOUND` | 404 Not Found |
| `ERR_STEWARDSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_FUND_NOT_OPEN` | 409 Conflict |
| `ERR_FUND_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_FUND_NOT_AWARDING` | 409 Conflict |
| `ERR_FUND_STATE_INVALID` | 409 Conflict |
| `ERR_CRITERIA_REQUIRED` | 409 Conflict |
| `ERR_DUPLICATE_CRITERIA` | 409 Conflict |
| `ERR_OPEN_APPLICATIONS_EXIST` | 409 Conflict |
| `ERR_APPLICATION_STATE_INVALID` | 409 Conflict |
| `ERR_RECOMMENDATION_REQUIRED` | 409 Conflict |
| `ERR_TRANSCRIPT_REQUIRED` | 409 Conflict |
| `ERR_DUPLICATE_TRANSCRIPT` | 409 Conflict |
| `ERR_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_NO_COMMITTEE_ASSIGNED` | 409 Conflict |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_ASSIGNMENT_STATE_INVALID` | 409 Conflict |
| `ERR_MEMBER_OVERLOADED` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_SCORE_STATE_INVALID` | 409 Conflict |
| `ERR_APPLICATION_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_NO_ASSIGNMENT_FOR_SCORE` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_SCORE_BELOW_FLOOR` | 409 Conflict |
| `ERR_AWARD_STATE_INVALID` | 409 Conflict |
| `ERR_AWARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_AWARD_ALREADY_DISBURSED` | 409 Conflict |
| `ERR_STEWARDSHIP_REQUIRED` | 409 Conflict |
| `ERR_STEWARDSHIP_STATE_INVALID` | 409 Conflict |
| `ERR_DISBURSEMENT_STATE_INVALID` | 409 Conflict |
| `ERR_GPA_BELOW_FLOOR` | 409 Conflict |
| `ERR_FUND_INSUFFICIENT` | 409 Conflict |
| `ERR_STALE_FUND_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |

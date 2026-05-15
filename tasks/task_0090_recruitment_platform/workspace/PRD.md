# Recruitment Platform API — Product Requirements Document

## 1. Introduction

The Recruitment Platform is a vertical hiring marketplace that links verified employers, screened job seekers, and contracted headhunters across the full lifecycle of an opening — from company verification through job posting, application, interviewing, offer negotiation, onboarding, and post-hire commission settlement. The product manager perspective treats the platform as a workflow orchestrator: each visible artefact (a `Company` profile, a job posting, an `Application`, an `InterviewRound`, an `Offer`, an `Onboarding` record, a `CommissionRecord`) is the materialisation of a multi-party negotiation whose intermediate decisions must be auditable, reversible where the business permits, and locked once a downstream party has relied upon them.

Three forces shape the design. First, **trust** — companies post jobs only after a platform-side verification of their business license, and that verification is periodically refreshed; candidates expose resume contents only to companies they have whitelisted; headhunter commissions accrue but settle on a holdback so that early departures can be clawed back. Second, **safety of content** — job postings pass through a review that screens for discriminatory wording, illegal terms, and duplicate-listing manipulation, and a per-tier posting quota prevents a single employer from saturating the marketplace. Third, **segregation of duties** — an offer is approved by three distinct people (hiring manager, HR, finance) before it is issued, and that three-person rule is enforced at the data layer rather than left to organisational policy.

This document is the contract between the product specification and the implementation. It defines the user roles, the standard request/response envelope, every business workflow, every numeric threshold, every state transition, every error condition, and every cascade. The implementer should treat the prose as authoritative — when the prose names a state, that string is the exact persisted value; when the prose names a field, that string is the exact JSON key; when the prose names an error identifier, that string is the exact value returned in the response body.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API call carries two request headers: `X-User-ID` (a string identifying the caller) and `X-User-Role` (a string naming the caller's role). If either header is missing or empty, the request is rejected with `ERR_AUTH_MISSING`. If `X-User-Role` is set to a value that is not one of the seven roles enumerated below, the request is rejected with `ERR_AUTH_INVALID_ROLE`. If the role is recognised but the operation is not permitted for that role, the rejection code is `ERR_FORBIDDEN`.

The seven roles, spelled exactly as the `X-User-Role` header must carry them, are: `HrUser`, `HiringManager`, `HrApprover`, `FinanceApprover`, `Candidate`, `HeadhunterUser`, and `PlatformAdmin`.

The semantics of `X-User-ID` depend on the role:

- When `X-User-Role` is `HrUser`, `X-User-ID` is the `id` of the acting `HrUser` row. Ownership checks on any resource that references an `HrUser` (for example, an `Offer`'s `hm_approver_user_id`, `hr_approver_user_id`, or `finance_approver_user_id`, or an `InterviewRound`'s `interviewer_user_ids` membership) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `HiringManager`, `HrApprover`, or `FinanceApprover`, `X-User-ID` is the `id` of the acting `HrUser` row in exactly the same way. These three roles are not separate persisted entities — they are RBAC tags attached to the same `HrUser` rows that the HR-side workforce uses. The role header selects which approval stage the caller is asserting; the identity check still resolves to a single `HrUser.id`.
- When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` row. Ownership checks on `Application`, `InterviewRound`, `Offer`, and `Onboarding` resources compare the chain of foreign keys back to a `Candidate.id` and match it against `X-User-ID`.
- When `X-User-Role` is `HeadhunterUser`, `X-User-ID` is the `id` of a `HeadhunterContract` row. The headhunter acts under a specific contract, not as a free-standing person; a commission-record read compares `CommissionRecord.headhunter_contract_id` to `X-User-ID`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_user_id` on an `AuditEvent` row that a scaffold transition writes) but does not compare it to any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10 when omitted, has a minimum of 1, and a maximum of 100; any value outside that range yields `ERR_VALIDATION`. `offset` defaults to 0 and may not be negative. The default ordering across all list endpoints is by `created_at` ascending. The `meta` block on a list response carries `limit`, `offset`, `total_count` (the total number of rows matching the filter, ignoring pagination), and `has_more` (true when more rows exist beyond the returned window).

Beyond pagination, the list endpoints accept the resource-specific filters documented in §3 — for postings, the optional `company_id`, `posting_status`, and `industry` query parameters; for commission records, the optional `headhunter_contract_id` and `settlement_status` query parameters; for audit events, the optional `subject_entity`, `subject_id`, and `event_kind` query parameters.

### 2.4. Common Resource Properties and Status Codes

Every persisted resource carries a server-minted `id`, which is a UUID v4 with no type prefix. Resources whose definition declares `common_fields` also expose `created_at` and `updated_at` (both ISO 8601 UTC timestamps with three fractional digits) and a `version` field (a monotonically increasing integer that starts at 1 on creation and increments by one on every persisted mutation). Resources whose definition does not declare common fields — specifically `CommissionRecord` and `AuditEvent` — expose only `id` and `created_at`; they do not expose `updated_at` or `version` because their lifecycle treats every state change as an immutable new row or as a one-way terminal transition. State changes on `CommissionRecord` still happen (`ACCRUED` to `SETTLED`, `ACCRUED` to `CLAWED_BACK`), but the API surface for that entity does not expose an `updated_at` or `version` field.

Successful creation of a new resource returns HTTP status 201. Successful modification of an existing resource (state transitions, field updates, action endpoints) returns HTTP status 200. Successful reads return 200. Status codes 401, 403, 404, 409, 422, and 429 carry the meanings described by the validation table in §2.7 and reach the client only via the error envelope of §2.2.

### 2.5. Optimistic Concurrency Control

Any mutation endpoint that updates an existing resource accepts an optional `version` field in the request body (or, where the endpoint description explicitly says so, as a `version` query parameter). When `version` is supplied, the server compares it to the resource's current `version`; if they differ, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server skips the check and applies the mutation against the current row. A successful mutation increments `version` by one and refreshes `updated_at`.

### 2.6. Hierarchical Consistency and Cascading Side Effects

Several entities have one or more parents in the workflow graph, and state changes propagate downward. When a `Company` moves to `EXPIRED` (because its current verification expired), every `JobPosting` owned by that company that is in the `LIVE` state moves to `OFF_SHELF`. When a `Company` moves to `BLACKLISTED`, every `JobPosting` owned by that company that is in any of `DRAFT`, `UNDER_REVIEW`, or `LIVE` moves to `OFF_SHELF`, and every `HeadhunterContract` for that company that is in `ACTIVE` moves to `TERMINATED`. When a `JobPosting` moves to `OFF_SHELF` or `EXPIRED`, every `Application` referencing that posting whose `application_status` is in `SUBMITTED`, `READ`, or `FORWARDED` moves to `CLOSED`, and that closure itself cancels any `InterviewRound` whose `round_status` is in `DRAFT`, `AWAITING_CANDIDATE`, `SCHEDULED`, or `FEEDBACK_PENDING` — a three-link transitive chain. When an `Application` moves to `REJECTED`, the same cancellation cascade fires on its `InterviewRound` rows. Every cascade step also bumps `version`, refreshes `updated_at`, and writes an `AuditEvent` row with `event_kind` equal to `STATE_TRANSITION`.

The chronological view of every state change is preserved in the `AuditEvent` log. Each `AuditEvent` carries `subject_entity`, `subject_id`, `event_kind`, `from_state`, `to_state`, `actor_role`, and `actor_user_id`. For state-transition events, `from_state` and `to_state` are the pre- and post-transition state strings; for commission lifecycle events (`COMMISSION_ACCRUED`, `COMMISSION_SETTLED`, `COMMISSION_CLAWBACK`), `from_state` and `to_state` are null. For system-driven transitions, `actor_role` is the string `"system"` and `actor_user_id` is the string `"system"`.

### 2.7. Validation Ordering and Priority

Every request runs through validations in a fixed priority order. The check at the lowest-priority number that fires is the one whose error is returned; later checks are not evaluated. The order is:

1. Authentication header presence — missing or empty `X-User-Role` or `X-User-ID` yields `ERR_AUTH_MISSING` (401).
2. Authentication role validity — `X-User-Role` not in the seven-role list yields `ERR_AUTH_INVALID_ROLE` (401).
3. RBAC — the acting role lacks permission for this operation yields `ERR_FORBIDDEN` (403).
4. Path existence (left-to-right) — any path-referenced resource missing yields `ERR_NOT_FOUND` (404). Path parameters are validated in the order they appear in the URL; a missing earlier parameter is reported before a missing later one.
5. Body foreign-key existence — any body-referenced foreign key (for example, `company_id`, `candidate_id`, `job_posting_id`, `headhunter_contract_id`, `application_id`, `offer_id`) that does not refer to an existing row yields `ERR_REFERENCE_NOT_FOUND` (404). Applies to all POST and PATCH endpoints.
6. HR-binding referential integrity — for any HR-actor endpoint, the acting `HrUser` must have `binding_status` equal to `ACTIVE` against the target `Company`; otherwise `ERR_HR_NOT_BOUND` (403).
7. Candidate visibility gating — on `GET /recruitment/candidates/{id}` (when called by an HR-side caller), on the application-forward action, and on the creation of an `InterviewRound` for an `Application`, the candidate's `visibility_mode` must permit the acting Company: `PUBLIC` always passes; `COMPANY_ONLY` requires the company's `id` to be in the candidate's `visible_to_company_ids`; `HIDDEN` blocks all HR reads and writes that touch `resume_attachment_url`. Failure yields `ERR_RESUME_NOT_VISIBLE` (403).
8. State machine — the target resource must be in a state from which the requested transition is declared; otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint.
9. Prohibited-content review — a job posting whose body contains discriminatory wording or illegal terms (matched against the platform's prohibited-content dictionary) is rejected at posting-approval time with `ERR_PROHIBITED_CONTENT` (422).
10. Duplicate-posting detection — at posting-approval time, no other `JobPosting` with `posting_status` equal to `LIVE` may share the same `content_fingerprint` for the same `company_id`; otherwise `ERR_DUPLICATE_POSTING` (409).
11. Offer approval segregation of duties — `hm_approver_user_id`, `hr_approver_user_id`, and `finance_approver_user_id` must be three distinct `HrUser` ids; a repeat at the approve action yields `ERR_SEGREGATION_VIOLATION` (422).
12. Offer acceptance window — on offer accept, the current instant must be strictly less than `acceptance_deadline_at`; equality means the offer has already expired and yields `ERR_OFFER_EXPIRED` (409).
13. Slot proposals in the future — on interview-round publish, every entry in `candidate_time_slot_options` must be strictly greater than the current instant; any slot at or before now yields `ERR_SLOT_IN_PAST` (422).
14. Interviewer availability — on interview-round publish and on candidate confirm, no proposed or selected slot may collide with any interviewer's existing `SCHEDULED` round; otherwise `ERR_INTERVIEWER_BUSY` (409).
15. Candidate anti-spam — at most five `Application` rows per `Candidate` may exist in the half-open window from sixty seconds ago up to but not including the current instant; the sixth attempt (i.e. the attempt that would carry the count from five to six) is rejected with `ERR_CANDIDATE_RATE_LIMIT` (429).
16. Posting quota — at posting-approval time, the owning `Company.active_job_posting_count` must be strictly less than its `posting_quota_limit`; equality (or any value above) means the quota is exhausted and the rejection code is `ERR_POSTING_QUOTA_EXCEEDED` (409).
17. Offer financial amounts — `base_salary_cents` must be strictly greater than zero, and `sign_on_bonus_cents` must be at least zero; otherwise `ERR_INVALID_AMOUNT` (422). Applies to offer creation and to submit-approval.
18. Salary range sanity — `salary_min_cents` must be less than or equal to `salary_max_cents`, and both must be strictly greater than zero; otherwise `ERR_INVALID_SALARY_RANGE` (422). Applies to job-posting creation and to submit-review.
19. Onboarding uniqueness — at most one `Onboarding` may exist per `Offer`; a second creation yields `ERR_ONBOARDING_ALREADY_EXISTS` (409).
20. OCC version mismatch — on any mutation whose request body or query string supplies `version`, a value that does not equal the resource's current `version` yields `ERR_VERSION_CONFLICT` (409).

Bodies that fail schema parsing or type checks in ways not captured above are rejected with the generic `ERR_VALIDATION` (422). Two domain-specific generic errors carry their own ids: `ERR_FEEDBACK_INVALID` (422) when `feedback_decision` on an interview round is not one of `PASS`, `FAIL`, or `HOLD`, and `ERR_CHECK_INVALID` (422) when the onboarding record-check call supplies an unknown `check_kind` or `outcome`.

### 2.8. Precision, Rounding, and Monetary Conventions

All monetary fields are integer cents. There are no floating-point amounts persisted anywhere in the system. Where the calculation rules produce intermediate fractional cents (the success-fee slices, the bonus share, the tax withholding), the rounding rule is **round half up to the nearest integer cent**, applied exactly once at the end of the sum — never per intermediate part. Integer count fields (`application_count`, `active_job_posting_count`, `applications_last_60s_count`, `posting_quota_limit`) are exact integers. Datetime comparisons distinguish strict-less-than from less-than-or-equal — see §2.7 items 12, 13, 14, and 15 for the exact boundaries.

### 2.9. Concurrency Serialisation

Six concurrency scenarios are guaranteed to serialise deterministically rather than producing inconsistent reads:

- Two candidates simultaneously confirm the same interview slot where confirming both would create overlapping schedules for a shared interviewer. At most one round transitions to `SCHEDULED`; the loser receives `ERR_INTERVIEWER_BUSY` (409). The serialisation point is first-writer-wins on the `round_status` transition into `SCHEDULED`.
- Two approvers attempt to approve the same `Offer` at the same approval stage simultaneously. Exactly one succeeds; the loser is rejected because the offer has already advanced out of that pending state, with `ERR_INVALID_STATE` (409). The serialisation point is first-writer-wins on `offer_status`.
- A candidate accepts and HR rescinds the same `ISSUED` offer simultaneously. Exactly one of the two write paths succeeds based on `offer_status` at write time; the loser receives `ERR_INVALID_STATE` (409).
- Two HR users attempt to create a second `Onboarding` for the same `Offer`. At most one `Onboarding` per offer; the second creation is rejected with `ERR_ONBOARDING_ALREADY_EXISTS` (409). The serialisation point is uniqueness on `Onboarding.offer_id`.
- Two HR users approve, simultaneously, two `JobPosting` rows that produce the same `content_fingerprint` for the same `Company`. Only one posting can be `LIVE` with a given fingerprint per company; the loser receives `ERR_DUPLICATE_POSTING` (409). The serialisation point is first-writer-wins on the tuple of `company_id`, `content_fingerprint`, and `posting_status` equal to `LIVE`.
- Two postings race to occupy the last available slot under a company's `posting_quota_limit`. Approval succeeds only while `active_job_posting_count` is strictly less than `posting_quota_limit`; the loser receives `ERR_POSTING_QUOTA_EXCEEDED` (409). The serialisation point is read-then-write under serialisable isolation on `Company.active_job_posting_count`.

### 2.10. Nested Resource Retrieval

URLs that nest one resource beneath another (for example, `/recruitment/applications/{id}/interview-rounds`) are validated left-to-right: the outer path parameter is checked first, and a missing outer resource is reported as `ERR_NOT_FOUND` before any inner identifier is touched. List filters that scope a response by a foreign key (`company_id` on the postings list, `headhunter_contract_id` on the commission-records list, `subject_entity` and `subject_id` on the audit-events list) do not constitute path nesting and do not require the foreign key to exist — an unknown filter value returns an empty list rather than a 404.

### 2.11. External Synchronisation

Several state transitions emit synchronisation events to external systems: an interview-round `SCHEDULED` transition emits a calendar-plus-IM-plus-video-conferencing event; a `SCHEDULED` round cancelled by upstream cascade emits the corresponding cancellation event; an onboarding moving to `CHECKS_RUNNING` emits a background-check-service event. The platform exposes a test-driver endpoint that simulates an inbound external event so that idempotency and replay can be exercised; receiving a duplicate of an event already processed must not regress the subject's state.

## 3. Business Logic & Workflows

### 3.1. Company Verification and HR Binding

A new `Company` is registered by an HR caller supplying `legal_name`, `business_license_number`, `industry`, `size_band`, and the desired `verification_tier`. The `business_license_number` must be unique across all companies; the `industry` is one of `TECH`, `FINANCE`, `MANUFACTURING`, `RETAIL`, `HEALTHCARE`, `EDUCATION`, or `OTHER`; the `size_band` is one of `SMALL`, `MEDIUM`, `LARGE`, or `ENTERPRISE`; the `verification_tier` is one of `BASIC` or `PREMIUM`, defaulting to `BASIC` when the field is absent. The row starts in `verification_status` `DRAFT`. The HR caller submitting the company for review (which requires `business_license_number` to be set, `industry` and `size_band` to be set, and `verification_tier` to be set) advances the row from `DRAFT` (or `EXPIRED`, for an already-known company whose previous verification has lapsed) to `PENDING`.

A `PlatformAdmin` then reviews the submission. Approving the verification transitions the company from `PENDING` to `VERIFIED`, sets `verified_at` to the current instant, sets `reverification_due_at` to three hundred and sixty-five days after `verified_at`, and recomputes the `posting_quota_limit`. The quota derivation is a three-branch function of `verification_status` and `verification_tier`: if `verification_status` is anything other than `VERIFIED`, `posting_quota_limit` is zero; otherwise, a `BASIC` tier yields a `posting_quota_limit` of five, and a `PREMIUM` tier yields a `posting_quota_limit` of twenty-five. Rejecting the verification transitions the company back to `DRAFT` so the HR side can correct the submission and retry — a cyclic loop between `DRAFT`, `PENDING`, and (on failure) back to `DRAFT`.

Once `VERIFIED`, the verification is valid for three hundred and sixty-five days, after which the platform's test-driving capability to advance the logical clock (which the implementer must expose so that automated tests can exercise time-based transitions) triggers the automatic transition to `EXPIRED` once the current instant is at or after `reverification_due_at`. The expiration cascades: every job posting owned by this company that is currently `LIVE` moves to `OFF_SHELF`, which itself runs the OFF_SHELF side-effect chain described in §3.2. An expired company can re-enter the verification workflow by re-submitting (going from `EXPIRED` back to `PENDING`).

A `PlatformAdmin` may also blacklist a company at any non-terminal state — from `DRAFT`, `PENDING`, or `VERIFIED` — by supplying a `blacklist_reason`. The blacklist transition is terminal: a blacklisted company never returns to any other status. When the source state was `VERIFIED`, blacklisting cascades to every job posting in `DRAFT`, `UNDER_REVIEW`, or `LIVE` (moving them to `OFF_SHELF` and chaining downward), and to every `HeadhunterContract` for this company whose `contract_status` is `ACTIVE` (moving them to `TERMINATED`). When the source state was `DRAFT` or `PENDING`, no cascade fires because no postings or contracts can yet exist that reference the company. Every transition above writes an audit event of kind `STATE_TRANSITION`.

The HR-side workforce attaches to the company through `HrUser` rows. A `PlatformAdmin` creates a binding by supplying the new HR user's `email` (which must be unique across all `HrUser` rows) and `display_name`; in this scaffold's surface, the binding is created directly in `ACTIVE` state, though the persisted enumeration recognises `PENDING`, `ACTIVE`, and `REVOKED` for the underlying `binding_status` field. The `company_id` foreign key carried by every `HrUser` row records the company the account is bound to, and the company's `authorized_hr_user_ids` is the current list of `HrUser` ids whose binding is in `ACTIVE` state. Any HR-side operation against the company must be performed by an HR user whose binding is `ACTIVE`; otherwise the request is rejected with `ERR_HR_NOT_BOUND`.

### 3.2. Job Posting Lifecycle and Quota Governance

An HR user creates a `JobPosting` in `DRAFT` state by supplying the owning `company_id`, the `title`, the `description`, the `salary_min_cents`, the `salary_max_cents`, and an array of `benefits` tags (each benefit is a string such as `MEAL`, `HOUSING`, or `EQUITY`). Posting creation enforces the salary range sanity check immediately, rejecting submissions where `salary_min_cents` is greater than `salary_max_cents`, or where either bound is at or below zero, with `ERR_INVALID_SALARY_RANGE`.

Submitting the posting for review requires the owning company to be in `VERIFIED` status and re-enforces the salary range sanity rule. On success the row advances from `DRAFT` to `UNDER_REVIEW` and the platform computes the `content_fingerprint`: a string composed of the lowercased `title`, a literal pipe character, and the SHA-256 hex digest of the lowercased `description`. The fingerprint is the deduplication primitive used at approval time.

A `PlatformAdmin` then either approves or rejects the under-review posting. Approval advances `UNDER_REVIEW` to `LIVE`. Approval has two distinct guards. The prohibited-content guard scans the posting body against a discriminatory-wording and illegal-terms dictionary; a hit yields `ERR_PROHIBITED_CONTENT`. The duplicate-posting guard then checks that no other `JobPosting` with `posting_status` equal to `LIVE` for the same `company_id` shares this row's `content_fingerprint`; if such a row exists, the approval is rejected with `ERR_DUPLICATE_POSTING`. Approval also gates on the company's posting quota: `active_job_posting_count` must be strictly less than `posting_quota_limit`, where the strict inequality means that equality already means the quota is exhausted and yields `ERR_POSTING_QUOTA_EXCEEDED`. On a successful approval, `listed_at` is set to the current instant and `active_job_posting_count` is incremented by one (a derived-field reconciliation: the persistent counter on the company is kept in lockstep with the count of `LIVE` postings under it).

Rejection advances `UNDER_REVIEW` to `REJECTED` and records a categorised `review_rejection_reason` (one of `DISCRIMINATORY_WORDING`, `ILLEGAL_TERMS`, `DUPLICATE`, or `OTHER`). An HR user may then revise the posting, transitioning from `REJECTED` back to `DRAFT` and clearing `review_rejection_reason`; the same `REJECTED → DRAFT → UNDER_REVIEW` loop may repeat until the posting either is approved or is abandoned.

A `LIVE` posting can leave the live state in three ways. The HR user can voluntarily take it off shelf, advancing `LIVE` to `OFF_SHELF`. The clock-advance capability auto-expires the posting once the current instant is at or after `listed_at` plus thirty days, advancing `LIVE` to `EXPIRED`. Both transitions set `off_shelf_at` to the current instant, decrement the owning company's `active_job_posting_count`, and run a cascade — every `Application` referencing this posting whose `application_status` is in `SUBMITTED`, `READ`, or `FORWARDED` moves to `CLOSED`. The application-closure cascade itself cancels any `InterviewRound` rows on those applications whose `round_status` is not yet terminal, producing a depth-three transitive chain originating at the job-posting off-shelf transition. Finally, the upstream cascade from a `Company` reaching `EXPIRED` or `BLACKLISTED` also drives postings into `OFF_SHELF` along the same path.

The list endpoint over postings accepts optional `company_id`, `posting_status`, and `industry` filters. The `posting_status` query parameter is matched against the posting's `posting_status`, whose declared enumeration is `DRAFT`, `UNDER_REVIEW`, `REJECTED`, `LIVE`, `OFF_SHELF`, and `EXPIRED`. The `application_count` field on a posting reflects the current count of `Application` rows that reference this posting.

### 3.3. Candidate Profiles and Resume Visibility

A candidate registers by supplying `full_name`, `email`, `resume_attachment_url`, and a `visibility_mode` (one of `PUBLIC`, `COMPANY_ONLY`, `HIDDEN`, defaulting to `PUBLIC`). When `visibility_mode` is `COMPANY_ONLY`, the candidate also supplies `visible_to_company_ids`, an array of `Company.id` values that may see the resume. The `email` is unique across all candidates. The candidate may update these fields later through the candidate-update capability, which accepts `visibility_mode`, `visible_to_company_ids`, and `resume_attachment_url` in any combination, along with an optional `version` parameter for optimistic concurrency.

The visibility rule applies wherever an HR-side actor crosses from a posting-or-application context into the candidate's resume. Reading a candidate row, forwarding an application, and creating an interview round all check the rule. `PUBLIC` always passes. `COMPANY_ONLY` requires the acting company's `id` to appear in the candidate's `visible_to_company_ids`. `HIDDEN` blocks every HR-side read or write that touches `resume_attachment_url`. Any failure yields `ERR_RESUME_NOT_VISIBLE`.

Two computed candidate fields support downstream logic: `last_application_at` records the timestamp of the candidate's most recent `Application` creation, and `applications_last_60s_count` reflects the rolling count of applications by this candidate in the most recent sixty-second window.

### 3.4. Application Lifecycle and Anti-Spam

A candidate submits an application by supplying the `candidate_id`, the `job_posting_id`, a `source_channel` (one of `DIRECT`, `ONE_CLICK`, or `HEADHUNTER`, defaulting to `DIRECT`), and — only when the `source_channel` is `HEADHUNTER` — the originating `headhunter_contract_id`. The application starts in `application_status` `SUBMITTED`, the `company_id` is denormalised from the job posting at creation time (and never recomputed thereafter, even if the posting later changes ownership), and an `AuditEvent` row of kind `STATE_TRANSITION` is written.

Before the row is persisted, the anti-spam guard fires. Consider a scenario in which a single candidate floods the platform with applications in rapid succession: the platform counts the candidate's `Application` rows whose `created_at` falls in the half-open window starting sixty seconds before the current instant and ending strictly before the current instant. If that count is already five at the time of evaluation — so that persisting the new row would carry the count to six — the request is rejected with `ERR_CANDIDATE_RATE_LIMIT`. The boundary uses the at-or-above-five rule, so an exact count of five is itself the trigger. The window is rolling rather than aligned to wall-clock minutes.

Three HR-driven actions advance the application down the funnel. Marking the application as read transitions `SUBMITTED` to `READ`, sets `read_at` to the current instant, and requires the parent `JobPosting` to still be in `posting_status` `LIVE`. Forwarding the application internally transitions `READ` to `FORWARDED`, sets `forwarded_at` to the current instant, and re-runs the visibility rule against the candidate. Creating the first `InterviewRound` for the application advances `FORWARDED` to `INTERVIEW`, requires no existing `InterviewRound` to be attached to this application, and emits an audit event for the application-status change in addition to the round-creation event.

Two terminal transitions exist on the HR side. Rejecting the application transitions any non-terminal state to `REJECTED` and cascades to every `InterviewRound` on this application whose status is `DRAFT`, `AWAITING_CANDIDATE`, `SCHEDULED`, or `FEEDBACK_PENDING`, moving each to `CANCELLED`. The system-driven `CLOSED` transition fires when the parent posting is taken off shelf or expires: applications in `SUBMITTED`, `READ`, or `FORWARDED` move to `CLOSED`, and a `FORWARDED → CLOSED` step also runs the interview-round cancellation cascade because rounds may already have been scheduled by that point. All audit events for these transitions carry `actor_role` `"system"` when the transition is the system-driven cascade rather than an HR-initiated action.

### 3.5. Interview Round Scheduling and Feedback

An interview round is created with a `mode` (one of `ONSITE`, `PHONE`, or `VIDEO`) and an `interviewer_user_ids` array (the HR user ids comprising the panel). The `round_index` is auto-assigned: the first round on the application is index 1, the second index 2, and so on; the tuple of `application_id` and `round_index` is unique. The round starts in `round_status` `DRAFT`.

Before candidate visibility, the HR user publishes a set of selectable time slots. Publishing requires `mode` to be set, `interviewer_user_ids` to contain at least one entry, and `candidate_time_slot_options` to contain at least one ISO 8601 datetime string whose value is strictly greater than the current instant — any slot at or before now yields `ERR_SLOT_IN_PAST`. The published slots are then checked for interviewer-availability collisions: for each interviewer in `interviewer_user_ids`, the set of half-open candidate windows (each spanning sixty minutes from the proposed start) is compared against every existing `SCHEDULED` `InterviewRound` whose interviewers include that user; two windows collide if and only if the start of the first is strictly less than the end of the second and the start of the second is strictly less than the end of the first. Touching exactly at a boundary (the end of one round equals the start of the next) is not a collision under this half-open rule. Any collision rejects the request with `ERR_INTERVIEWER_BUSY`. On success the round advances from `DRAFT` to `AWAITING_CANDIDATE`.

The candidate then selects one of the offered slots through the candidate-confirm capability. The `selected_slot` must be one of the entries previously published in `candidate_time_slot_options`, and it must not collide — under the same half-open rule — with any interviewer's existing `SCHEDULED` round. A successful confirmation advances the round from `AWAITING_CANDIDATE` to `SCHEDULED`, sets `scheduled_start_at` to the selected slot, sets `scheduled_end_at` to exactly sixty minutes later regardless of the round's `mode`, and emits a synchronisation event to the calendar, IM, and video-conferencing systems. The serialisation rule for two candidates racing on the same shared-interviewer slot was described in §2.9: at most one transitions to `SCHEDULED`; the loser receives `ERR_INTERVIEWER_BUSY`.

Once the current instant is at or after `scheduled_end_at`, the clock-advance capability auto-transitions the round from `SCHEDULED` to `FEEDBACK_PENDING`. The HR panel then submits feedback, supplying a `feedback_decision` of `PASS`, `FAIL`, or `HOLD` (any other value yields `ERR_FEEDBACK_INVALID`). A `PASS` decision advances the round to `PASSED` and persists `feedback_decision` accordingly. A `FAIL` decision is more consequential: it advances the round to `FAILED`, persists `feedback_decision`, and cascades — the parent `Application` moves to `REJECTED`, which itself cancels any other non-terminal `InterviewRound` rows on that application. A `HOLD` decision is recognised by the validation but does not by itself advance the round to either terminal; further HR action is needed.

Cancellation cascades can reach any non-terminal round from above: a parent `Application` moving to `REJECTED` or `CLOSED` cancels rounds in `DRAFT`, `AWAITING_CANDIDATE`, `SCHEDULED`, or `FEEDBACK_PENDING`; the `SCHEDULED → CANCELLED` step additionally emits a cancellation synchronisation event to the calendar, IM, and video-conferencing systems. Round-level audit events fire on every transition above.

### 3.6. Offer Creation, Three-Way Approval, and Acceptance Window

An HR user creates an `Offer` by supplying the `application_id` (which must be unique across all offers, so each application gets at most one offer), the `base_salary_cents`, and the `sign_on_bonus_cents`. The `company_id` is denormalised from the application at creation. Both money fields are validated: `base_salary_cents` must be strictly greater than zero and `sign_on_bonus_cents` must be at least zero, else `ERR_INVALID_AMOUNT`. The offer starts in `offer_status` `DRAFT`.

Submitting the offer for approval advances `DRAFT` to `PENDING_HM`. The submit guards re-check the money fields and additionally require that the parent `Application` be in `application_status` `INTERVIEW` and that at least one `InterviewRound` on that application has `round_status` `PASSED`. The approval pipeline then runs in three stages, each driven by a distinct role:

1. A `HiringManager` calls the approve action, transitioning `PENDING_HM` to `PENDING_HR`. The acting `HrUser` must be bound (`binding_status` `ACTIVE`) to the offer's company. On success, `hm_approver_user_id` is set to the actor's `X-User-ID`.
2. An `HrApprover` then calls the approve action, transitioning `PENDING_HR` to `PENDING_FINANCE`. The acting `HrUser` must be bound to the offer's company, and the actor must not be the same `HrUser` who served as the hiring manager — segregation of duties is enforced at this step. A repeat yields `ERR_SEGREGATION_VIOLATION`. On success, `hr_approver_user_id` is set.
3. A `FinanceApprover` then calls the approve action, transitioning `PENDING_FINANCE` to `ISSUED`. The actor must be bound to the offer's company and must differ from both `hm_approver_user_id` and `hr_approver_user_id`. On success, `finance_approver_user_id` is set, `issued_at` is set to the current instant, and `acceptance_deadline_at` is set to one hundred and sixty-eight hours (which equals seven days) after `issued_at`.

Any of the three roles may instead call the reject-approval action at their stage. From `PENDING_HM`, rejecting returns the offer to `DRAFT` and leaves both approver fields cleared. From `PENDING_HR`, rejecting returns the offer to `DRAFT` and clears `hm_approver_user_id`. From `PENDING_FINANCE`, rejecting returns the offer to `DRAFT` and clears both `hm_approver_user_id` and `hr_approver_user_id` (so the entire pipeline must restart). The four parallel branches at this stage carry equal specification density — the loser-clearing semantics are not symmetrical; the reset depth grows with the stage at which the rejection occurs.

Once the offer is `ISSUED`, the candidate has a fixed acceptance window. The accept capability transitions `ISSUED` to `ACCEPTED` and is gated on the current instant being strictly less than `acceptance_deadline_at`; equality means the deadline has already arrived and the request must be rejected with `ERR_OFFER_EXPIRED`. The candidate may optionally supply a `competing_offer_note`. On a successful accept, `accepted_at` is set to the current instant; if the application's `source_channel` is `HEADHUNTER` and the originating `HeadhunterContract.trigger_event` is `OFFER_ACCEPTED`, a `CommissionRecord` is created (see §3.8). The decline capability transitions `ISSUED` to `DECLINED` and is unconditional. The clock-advance capability auto-expires an `ISSUED` offer when the current instant reaches or surpasses `acceptance_deadline_at`, transitioning to `EXPIRED`. The single-resource read on an `ISSUED` offer projects a forward-looking `seconds_remaining` derived from `acceptance_deadline_at` minus the current instant, clamped at zero; once the offer reaches any of the terminal states `ACCEPTED`, `DECLINED`, or `EXPIRED`, this projected value freezes at the chronological figure `terminal_event_time` minus `issued_at`, which may be smaller than the live projection ever showed.

HR can rescind an issued or accepted offer. Rescission from `ISSUED` requires a categorised `rescission_reason` (one of `BUSINESS_NEED`, `BACKGROUND_FAIL`, `CANDIDATE_MISREP`, or `OTHER`). Rescission from `ACCEPTED` requires the same `rescission_reason` and additionally requires that no `Onboarding` row yet exists for this offer; once onboarding has begun, the offer can no longer be rescinded through this path. A rescission from `ACCEPTED` runs a second-link cascade: if a `CommissionRecord` already exists for this application with `settlement_status` `ACCRUED` and `trigger_kind` `OFFER_ACCEPTED`, that record flips to `CLAWED_BACK`, its `clawback_amount_cents` is set to `gross_commission_cents` minus `tax_withheld_cents`, and `net_settlement_cents` is set to zero. A commission-clawback audit event is written in addition to the state-transition event for the offer itself.

### 3.7. Onboarding, Checks, and Probation

An HR user creates an `Onboarding` for an `ACCEPTED` offer by supplying the `offer_id` (unique across all onboardings) and the confirmed `start_date`. The onboarding starts with `onboarding_status` equal to `SCHEDULED`, with `background_check_status` and `medical_check_status` both `PENDING`. The declared enumeration for `onboarding_status` is `SCHEDULED`, `CHECKS_RUNNING`, `READY`, `ONBOARDED`, `NO_SHOW`, `PROBATION_PASSED`, and `PROBATION_FAILED`. Initiating the checks advances `SCHEDULED` to `CHECKS_RUNNING` and emits a synchronisation event to the external background-check service.

The HR user records check outcomes through the record-check capability, supplying `check_kind` (`BACKGROUND` or `MEDICAL`) and `outcome` (one of `PENDING`, `PASSED`, `FAILED`, or `WAIVED`). An unknown `check_kind` or `outcome` yields `ERR_CHECK_INVALID`. Once `background_check_status` is in `PASSED` or `WAIVED` and `medical_check_status` is likewise in `PASSED` or `WAIVED`, the platform advances the onboarding from `CHECKS_RUNNING` to `READY` on the next record-check call that produces this state.

The HR user then confirms onboarding through the confirm-onboarded capability, transitioning `READY` to `ONBOARDED` on or after `start_date` (i.e. the current instant must be at or after `start_date`). On the `ONBOARDED` transition, `probation_end_at` is set to ninety days after `start_date`; and if the application's `source_channel` is `HEADHUNTER` and the `HeadhunterContract.trigger_event` is `ONBOARDED`, a `CommissionRecord` is created with `settlement_status` `ACCRUED` and `trigger_kind` `ONBOARDED`.

The no-show path covers two source states. From `CHECKS_RUNNING`, the record-no-show capability transitions to `NO_SHOW` once the current instant is at or after `start_date`; the parent `Offer` is cascaded to `RESCINDED` with `rescission_reason` `BACKGROUND_FAIL` when a check returned `FAILED`, or `OTHER` for a no-show without a failed check. From `READY`, the same capability also transitions to `NO_SHOW` once the current instant is at or after `start_date`; the parent `Offer` cascades to `RESCINDED` with `rescission_reason` `OTHER`. Either way, the rescission cascade itself may trigger commission clawback per §3.6.

Probation lasts ninety days, and the conversion-decision capability records the outcome with `decision` of `PASS` or `FAIL`. A `PASS` decision is allowed up to thirty days before `probation_end_at` (so the current instant must be at or after `probation_end_at` minus thirty days), advancing the onboarding to `PROBATION_PASSED`; if the contract's `trigger_event` is `PROBATION_PASSED`, a `CommissionRecord` is created at this moment. A `FAIL` decision advances the onboarding to `PROBATION_FAILED` and runs the chronological clawback cascade: every `CommissionRecord` on the same `application_id` with `settlement_status` `ACCRUED` whose age (current instant minus the record's `created_at`) is strictly less than the contract's `clawback_window_days` flips to `CLAWED_BACK`; records older than the window keep their `ACCRUED` status. For each flipped record, `clawback_amount_cents` is set to `gross_commission_cents` minus `tax_withheld_cents`, `net_settlement_cents` is set to zero, and a commission-clawback audit event is written.

The feedback capability accepts a `side` (`CANDIDATE` or `EMPLOYER`) and a `score` (an integer 1 through 5) and records `candidate_feedback_score` or `employer_feedback_score` accordingly.

### 3.8. Headhunter Contracts and Commission Settlement

A `PlatformAdmin` creates a `HeadhunterContract` by supplying the `headhunter_user_id` (which becomes the `id` the headhunter authenticates against in their `X-User-ID`), the `company_id`, the `fee_model` (`SUCCESS_FEE`, `RETAINER`, or `HYBRID`), the `success_fee_pct_bps` (basis points, where a value of 2000 means twenty percent — used by `SUCCESS_FEE` and `HYBRID` only), the `retainer_amount_cents` (a flat retainer in integer cents — used by `RETAINER` and `HYBRID` only), the `trigger_event` (`OFFER_ACCEPTED`, `ONBOARDED`, or `PROBATION_PASSED`), the `clawback_window_days` (defaulting to ninety days), and the `tax_withholding_pct_bps` (defaulting to 1000 basis points, i.e. ten percent). The contract starts in `contract_status` `ACTIVE` and may move to `SUSPENDED` or `TERMINATED` over its lifetime (the cascade from a company blacklist drives it to `TERMINATED`).

Commission accrues at the configured trigger event. The accrual side-effects in §3.6 and §3.7 create a `CommissionRecord` whose `headhunter_contract_id` and `application_id` are pinned at creation, whose `settlement_status` is `ACCRUED`, and whose `trigger_kind` echoes the contract's `trigger_event` at the moment of accrual. The `gross_commission_cents` is computed as follows. The inputs are snapshotted at creation time — the offer's `base_salary_cents`, the offer's `sign_on_bonus_cents`, and the contract's `fee_model`, `success_fee_pct_bps`, and `retainer_amount_cents`. If the contract terms later change, no retroactive recomputation occurs.

The success-fee component is split into two slices on the base salary so that per-tier rounding is well-defined. The first slice is the smaller of the offer's `base_salary_cents` and the cap of 10,000,000 cents (which equals 100,000.00 monetary units), multiplied by `success_fee_pct_bps`, divided by 10,000. The remainder slice is the offer's `base_salary_cents` minus the cap (clamped at zero, i.e. zero whenever `base_salary_cents` is at or below the cap), multiplied by `success_fee_pct_bps`, divided by 10,000, and then multiplied by 0.5 — the marginal rate above the cap is exactly half the headline rate. The bonus share is the offer's `sign_on_bonus_cents` multiplied by `success_fee_pct_bps`, divided by 10,000, and multiplied by 0.25 — a quarter of the headline rate.

The three branches of the fee model combine these slices and the retainer differently. For a `SUCCESS_FEE` contract, the first slice, remainder slice, and bonus share contribute as defined above and the retainer part is zero. For a `RETAINER` contract, the first slice, remainder slice, and bonus share are all zero and the retainer part equals the contract's `retainer_amount_cents`. For a `HYBRID` contract, all four components contribute: the three fractional success slices plus the integer retainer. The branches are parallel in specification density — each lists which of the four parts is zero and which carries a value.

The raw total is the sum of the four raw parts: first slice plus remainder slice plus bonus share plus retainer part. The rounding rule is then applied exactly once, at the end of this sum, using the round-half-up convention to yield `gross_commission_cents` as an integer cent value. The evaluation order is fixed: compute all four raw parts (keeping fractional precision), sum them, and then round half up. An implementation that rounds each of the four raw parts individually to integer cents before summing — per-part-then-sum — produces a different integer for any inputs where the three success-fee slices do not all carry the same sign past the half-cent boundary, and that divergence is a defect.

The tax withholding is computed alongside the gross amount: `tax_withheld_cents` equals `gross_commission_cents` (the already-rounded value) multiplied by the contract's `tax_withholding_pct_bps`, divided by 10,000, then rounded half up to an integer cent. The accrual audit event of kind `COMMISSION_ACCRUED` is written at the moment of `CommissionRecord` creation.

Settlement runs on a deferred sweep. The platform exposes an admin-only test-driving capability that runs the settlement sweep: each `CommissionRecord` in `ACCRUED` status whose age (current instant minus the record's `created_at`) is at least thirty days, and against which no clawback condition is active, transitions to `SETTLED`. The sweep sets `settled_at` to the current instant and computes `net_settlement_cents` as `gross_commission_cents` minus `tax_withheld_cents` (with `clawback_amount_cents` remaining zero because the record never moved to `CLAWED_BACK`). A `COMMISSION_SETTLED` audit event is written.

The settlement view depends on the moment of observation, so the single-record read on a commission row in `ACCRUED` status returns a forward-looking projected net derived as `gross_commission_cents` minus `tax_withheld_cents` (assuming no clawback). That projected figure may differ from the eventual final net if a clawback intervenes between the moment of read and the moment of sweep. Once the record transitions to `SETTLED`, the read returns the chronological figure locked at sweep time. If a clawback flipped the record to `CLAWED_BACK` between accrual and sweep, the record ends up at `CLAWED_BACK` with `net_settlement_cents` zero rather than `SETTLED`, demonstrating that the same gross-and-tax inputs can produce two different final nets depending on whether processing happens at sweep time (chronological) or projected forward at accrual time (forward-looking). At any terminal state, the invariant `net_settlement_cents` plus `clawback_amount_cents` equals `gross_commission_cents` minus `tax_withheld_cents` holds by construction.

The list capability over commission records supports filtering by `headhunter_contract_id` and `settlement_status`. The settlement_status enumeration is `ACCRUED`, `SETTLED`, or `CLAWED_BACK`. A `HeadhunterUser` reading commission records may see only those rows whose `headhunter_contract_id` equals their `X-User-ID`; a `PlatformAdmin` may see all rows.

### 3.9. Audit Logging and Test-Driver Capabilities

Every state transition in §3.1 through §3.8 writes a row into the audit log carrying `subject_entity` (one of `Company`, `JobPosting`, `Application`, `InterviewRound`, `Offer`, `Onboarding`, or `CommissionRecord`), `subject_id`, `event_kind` (`STATE_TRANSITION`, `COMMISSION_ACCRUED`, `COMMISSION_SETTLED`, or `COMMISSION_CLAWBACK`), `from_state` and `to_state` for state-transition events (null otherwise), `actor_role`, and `actor_user_id`. The audit listing capability filters by `subject_entity`, `subject_id`, and `event_kind`.

Three admin-only test-driving capabilities are exposed so that automated tests can exercise time-based behaviour deterministically. The clock-advance capability advances the logical clock to a supplied `to_iso8601` instant and runs every auto-transition whose precondition is now satisfied: `Company` rows in `VERIFIED` whose `reverification_due_at` has been reached move to `EXPIRED`; `JobPosting` rows in `LIVE` whose `listed_at` plus thirty days has been reached move to `EXPIRED`; `InterviewRound` rows in `SCHEDULED` whose `scheduled_end_at` has been reached move to `FEEDBACK_PENDING`; `Offer` rows in `ISSUED` whose `acceptance_deadline_at` has been reached move to `EXPIRED`. The settlement-sweep capability runs the periodic commission sweep described in §3.8. The external-event capability accepts a `system`, `kind`, and `subject_id` and simulates an inbound synchronisation event from the calendar, IM, video-conferencing, or background-check systems; a duplicate event already processed must not regress the subject's state.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2 and the validation order of §2.7. Successful creation of a new resource returns HTTP 201; all other successful responses return HTTP 200. The table below lists each endpoint's verb, path, summary, and authorised roles. Request and response bodies, side effects, and state preconditions are described in the §3 workflow that owns the operation.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /recruitment/companies | Create a Company in DRAFT state. | HrUser |
| GET | /recruitment/companies/{id} | Read a Company. | HrUser, PlatformAdmin |
| POST | /recruitment/companies/{id}/submit-verification | Submit Company for platform verification. | HrUser |
| POST | /recruitment/companies/{id}/approve-verification | Admin approves company verification. | PlatformAdmin |
| POST | /recruitment/companies/{id}/reject-verification | Admin rejects company verification. | PlatformAdmin |
| POST | /recruitment/companies/{id}/blacklist | Admin blacklists a Company; cascades to postings and contracts. | PlatformAdmin |
| POST | /recruitment/companies/{id}/hr-bindings | Bind a new HrUser to a Company. | PlatformAdmin |
| POST | /recruitment/job-postings | Create a JobPosting in DRAFT. | HrUser |
| GET | /recruitment/job-postings/{id} | Read a JobPosting. | HrUser, PlatformAdmin, Candidate |
| GET | /recruitment/job-postings | List job postings with filters. | HrUser, PlatformAdmin, Candidate |
| POST | /recruitment/job-postings/{id}/submit-review | Submit posting for review. | HrUser |
| POST | /recruitment/job-postings/{id}/approve | Admin approves a posting. | PlatformAdmin |
| POST | /recruitment/job-postings/{id}/reject | Admin rejects a posting. | PlatformAdmin |
| POST | /recruitment/job-postings/{id}/revise | HR moves a rejected posting back to DRAFT. | HrUser |
| POST | /recruitment/job-postings/{id}/take-off-shelf | HR takes a LIVE posting off shelf. | HrUser |
| POST | /recruitment/candidates | Register a Candidate. | Candidate |
| PATCH | /recruitment/candidates/{id} | Update Candidate fields. Supports OCC. | Candidate |
| GET | /recruitment/candidates/{id} | Read a Candidate (visibility-gated for HR callers). | Candidate, HrUser |
| POST | /recruitment/applications | Submit a job application. Subject to anti-spam rate limit. | Candidate |
| GET | /recruitment/applications/{id} | Read an Application. | HrUser, Candidate |
| POST | /recruitment/applications/{id}/mark-read | HR marks application as read. | HrUser |
| POST | /recruitment/applications/{id}/forward | HR forwards application internally. | HrUser |
| POST | /recruitment/applications/{id}/reject | HR rejects an application. | HrUser |
| POST | /recruitment/applications/{id}/interview-rounds | Create a new InterviewRound on an Application. | HrUser |
| POST | /recruitment/interview-rounds/{id}/publish-slots | HR publishes candidate-selectable time slots. | HrUser |
| POST | /recruitment/interview-rounds/{id}/candidate-confirm | Candidate picks one of the offered slots. | Candidate |
| POST | /recruitment/interview-rounds/{id}/submit-feedback | HR submits per-round feedback. | HrUser |
| GET | /recruitment/interview-rounds/{id} | Read an InterviewRound. | HrUser, Candidate |
| POST | /recruitment/offers | Create a DRAFT Offer for an Application. | HrUser |
| POST | /recruitment/offers/{id}/submit-approval | Move an Offer into the approval pipeline. | HrUser |
| POST | /recruitment/offers/{id}/approve | Advance one approval stage. | HiringManager, HrApprover, FinanceApprover |
| POST | /recruitment/offers/{id}/reject-approval | Reject at the current approval stage. | HiringManager, HrApprover, FinanceApprover |
| POST | /recruitment/offers/{id}/accept | Candidate accepts an issued offer. | Candidate |
| POST | /recruitment/offers/{id}/decline | Candidate declines an issued offer. | Candidate |
| POST | /recruitment/offers/{id}/rescind | HR rescinds an ISSUED or ACCEPTED offer. | HrUser |
| GET | /recruitment/offers/{id} | Read an Offer. | HrUser, Candidate |
| POST | /recruitment/onboardings | Create Onboarding for an ACCEPTED Offer. | HrUser |
| POST | /recruitment/onboardings/{id}/start-checks | Move onboarding into checks-running. | HrUser |
| POST | /recruitment/onboardings/{id}/record-check | Record background or medical check outcome. | HrUser |
| POST | /recruitment/onboardings/{id}/confirm-onboarded | Move READY to ONBOARDED on or after start date. | HrUser |
| POST | /recruitment/onboardings/{id}/record-no-show | Mark candidate no-show; cascades to Offer. | HrUser |
| POST | /recruitment/onboardings/{id}/conversion-decision | Record probation conversion decision. | HrUser |
| POST | /recruitment/onboardings/{id}/feedback | Submit candidate-side or employer-side feedback score. | HrUser, Candidate |
| GET | /recruitment/onboardings/{id} | Read an Onboarding. | HrUser, Candidate |
| POST | /recruitment/headhunter-contracts | Create a HeadhunterContract. | PlatformAdmin |
| GET | /recruitment/commission-records/{id} | Read a CommissionRecord. | PlatformAdmin, HeadhunterUser |
| GET | /recruitment/commission-records | List CommissionRecords with filters. | PlatformAdmin, HeadhunterUser |
| GET | /recruitment/audit-events | List AuditEvent rows with filters. | PlatformAdmin |
| POST | /recruitment/_clock/advance | Test-driver — advance wall clock. | PlatformAdmin |
| POST | /recruitment/_settlement-sweep/run | Test-driver — run the periodic settlement sweep. | PlatformAdmin |
| POST | /recruitment/_events/emit | Test-driver — emit an external synchronisation event. | PlatformAdmin |

## 5. Error Code Catalogue

The trigger conditions for each error are described in §2 and §3 narratives; this table lists only the identifier and HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_MISSING | 401 |
| ERR_AUTH_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_HR_NOT_BOUND | 403 |
| ERR_RESUME_NOT_VISIBLE | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_PROHIBITED_CONTENT | 422 |
| ERR_DUPLICATE_POSTING | 409 |
| ERR_SEGREGATION_VIOLATION | 422 |
| ERR_OFFER_EXPIRED | 409 |
| ERR_SLOT_IN_PAST | 422 |
| ERR_INTERVIEWER_BUSY | 409 |
| ERR_CANDIDATE_RATE_LIMIT | 429 |
| ERR_POSTING_QUOTA_EXCEEDED | 409 |
| ERR_INVALID_AMOUNT | 422 |
| ERR_INVALID_SALARY_RANGE | 422 |
| ERR_ONBOARDING_ALREADY_EXISTS | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_VALIDATION | 422 |
| ERR_FEEDBACK_INVALID | 422 |
| ERR_CHECK_INVALID | 422 |

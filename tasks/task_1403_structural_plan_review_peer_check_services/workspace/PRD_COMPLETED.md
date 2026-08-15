# Structural Plan Review & Peer Check Services API — Product Requirements Document

## 1. Introduction

Third-party structural plan review firms occupy a regulated niche between design teams and building departments: a jurisdiction delegates plan examination to the firm, and the firm's sealed review record becomes part of the permanent permit file. That position creates a distinctive set of obligations. The firm must apply the *correct* code editions — the ones the jurisdiction had adopted when the engagement was registered, not whatever edition is current today — verify load path and lateral system design before any approval is uttered, run disciplined deficiency-comment cycles with the applicant, honor state-by-state seal rules (including the stricter Structural Engineer seal some states demand), track deferred submittals such as trusses and anchors through to resolution, and produce an auditable record the building department can accept without further question.

This document specifies the Structural Plan Review & Peer Check Services API, mounted under `/plan-review`. It governs the full engagement lifecycle: scope and code-edition applicability pinned at registration, review cycles with turnaround deadlines and expedite handling, reviewer assignment under licensing and capacity constraints, deficiency comment generation and response rounds, chief-reviewer waivers under segregation of duties, deferred submittal coordination, and the sealing and transmittal of the review record together with the final fee. The API is the system of record for every one of those steps; every state change, timestamp, and fee figure described here is produced and persisted by the server.

A word on reading this document: §2 states the global contracts that hold for every endpoint, §3 walks the business workflows in narrative form, §4 is the endpoint index, and §5 is the error catalogue. Trigger conditions live with the workflows they guard; §5 deliberately carries no condition column.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty or whitespace-only value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If the role is valid but not among the roles authorized for the targeted endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles, spelled as follows: `PlatformAdmin`, `ReviewCoordinator`, `Reviewer`, `ChiefReviewer`, and `Applicant`. A role value outside these five appears in no endpoint's role list and is therefore rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The meaning of `X-User-ID` differs by role, and the distinction is load-bearing:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.
- When `X-User-Role` is `ReviewCoordinator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting `Reviewer`; ownership checks on any resource that references a `Reviewer` — the reviewer on a cycle's `ACTIVE` assignment, an engagement's `reviewer_of_record_id`, a comment's `raised_by_reviewer_id` — compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `ChiefReviewer`, `X-User-ID` is also the `id` of the acting `Reviewer`; this is what allows the waiver segregation rule (§3.5) to compare the caller against the engagement's `reviewer_of_record_id`.
- When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque design-firm contact identifier not tied to any persisted entity, but it is recorded on each engagement as `applicant_contact_id` at registration, and every applicant-scoped action compares `X-User-ID` against that field.

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

Requests to undefined routes, requests using an unsupported method on a defined route, and any unexpected server failure are likewise answered in this envelope, with `ERR_INVALID_REQUEST` and HTTP 400.

### 2.3. Pagination

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0, and must never be negative. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS`, as is a `limit` or `offset` value that does not parse as an integer.

All list endpoints sort by `created_at` ascending, breaking ties by `id` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

### 2.4. Request Validation Pipeline

Every request passes through a fixed sequence of validation layers, and the order is part of the contract: a failure at an earlier layer masks every later check, so the caller always sees the error from the highest-priority failing layer.

1. **User context headers** — `X-User-ID` and `X-User-Role` must be present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — `X-User-Role` must appear in the endpoint's declared role list (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Request body shape** — required fields present, enum values valid, types correct (`ERR_INVALID_REQUEST`). A body field the endpoint does not declare is rejected with `ERR_INVALID_REQUEST`; endpoints that declare no body fields accept and ignore any body sent. On partial-update payloads (the two PUT endpoints), a field explicitly set to null is treated as omitted.
4. **Pagination parameters** — on list endpoints, `limit` within 1 to 100 and `offset` at least 0 (`ERR_INVALID_PAGINATION_PARAMETERS`).
5. **Existence** — resource identifiers in the path are validated left to right, then identifier fields in the body (`jurisdiction_id`, `reviewer_of_record_id`, `engagement_id`, `cycle_id`, `raised_in_cycle_id`, `reviewer_id`) must each resolve to an existing resource. The not-found error matches the resource type: `ERR_JURISDICTION_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_DEFERRED_SUBMITTAL_NOT_FOUND`, or `ERR_RECORD_NOT_FOUND`.
6. **Ownership and identity** — applicant-scoped actions require `X-User-ID` to equal the engagement's `applicant_contact_id` (`ERR_NOT_ENGAGEMENT_APPLICANT`); cycle review actions require `X-User-ID` to equal the reviewer on the relevant cycle's `ACTIVE` assignment (`ERR_NOT_ASSIGNED_REVIEWER`); seal and deferred approve/reject require `X-User-ID` to equal the engagement's `reviewer_of_record_id` (`ERR_NOT_RESPONSIBLE_CHARGE`). For comment verify and reopen, the "relevant cycle" is the engagement's current non-terminal cycle, so their `ERR_NO_ACTIVE_REVIEW_CYCLE` precondition (§3.5) is necessarily evaluated before this identity check.
7. **State preconditions** — the target entity must be in a state from which the requested transition is defined; this layer also hosts the optimistic-concurrency check of §2.9 (`ERR_ENGAGEMENT_NOT_ACTIVE`, `ERR_ENGAGEMENT_NOT_AMENDABLE`, `ERR_CYCLE_STILL_ACTIVE`, `ERR_RECORD_ALREADY_SEALED`, `ERR_CYCLE_NOT_IN_REVIEW`, `ERR_CYCLE_NOT_ASSIGNABLE`, `ERR_NO_COMMENTS_TO_ISSUE`, `ERR_COMMENT_NOT_AWAITING_RESPONSE`, `ERR_COMMENT_NOT_ADDRESSED`, `ERR_NO_ACTIVE_REVIEW_CYCLE`, `ERR_ENGAGEMENT_NOT_APPROVED`, `ERR_RECORD_INVALID_STATE`, `ERR_INVALID_STATE_TRANSITION`, and the OCC-specific `ERR_STALE_CYCLE_VERSION`).
8. **Regulatory and licensing** — license state coverage, license expiry windows, SE-seal requirements, the CRITICAL-comment waiver bar, and waiver segregation of duties (`ERR_LICENSE_STATE_MISMATCH`, `ERR_LICENSE_WINDOW_INSUFFICIENT`, `ERR_SE_SEAL_REQUIRED`, `ERR_CRITICAL_COMMENT_NOT_WAIVERABLE`, `ERR_WAIVER_SEGREGATION_VIOLATION`).
9. **Business constraints** — jurisdiction `state_code` uniqueness, reviewer capacity, code-edition match on comments, approval gates on unresolved comments and verification booleans, and the deferred-submittal permission flag (`ERR_DUPLICATE_JURISDICTION_STATE`, `ERR_REVIEWER_CAPACITY_EXCEEDED`, `ERR_CODE_EDITION_MISMATCH`, `ERR_UNRESOLVED_COMMENTS_REMAIN`, `ERR_VERIFICATION_INCOMPLETE`, `ERR_DEFERRED_NOT_PERMITTED`).
10. **Referential completeness** — record seal requires every deferred submittal on the engagement to be resolved (`ERR_DEFERRED_SUBMITTALS_OUTSTANDING`).

### 2.5. Common Resource Properties

Every primary resource — `Jurisdiction`, `Reviewer`, `Engagement`, `ReviewCycle`, `ReviewAssignment`, `DeficiencyComment`, `DeferredSubmittal`, and `ReviewRecord` — carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer starting at 1 at creation and incrementing by 1 on every mutation of that resource, used for optimistic concurrency control.

`CommentResponse` is the deliberate exception. As an immutable ledger entry it carries only `id` and `created_at`; both `updated_at` and `version` are absent, because a response is never modified once posted.

Cascading mutations count as mutations on each entity they touch: when an operation updates a parent or child, that entity's `updated_at` refreshes and its `version` increments, exactly as if it had been written directly.

### 2.6. Pinned Jurisdiction Rule Snapshots

Jurisdictions are living configuration: a state adopts a new IBC edition, changes its fee method, or tightens its seal requirements at any time. An engagement, however, must be reviewed against the rules in force when it was registered. At engagement creation the server therefore copies a snapshot of the governing jurisdiction onto the engagement: `pinned_state_code`, `pinned_ibc_edition`, `pinned_asce7_edition`, `pinned_fee_method`, `pinned_turnaround_days`, `pinned_sla_mode`, `pinned_free_resubmittal_cycles`, `pinned_requires_se_seal`, and `pinned_allows_deferred_submittals`. These pinned fields never change afterwards, even when the jurisdiction itself is later updated; jurisdiction updates apply only to engagements created afterwards. Every downstream rule — fee computation, turnaround computation, comment edition checks, seal licensing, deferred-submittal permission — reads the pinned snapshot, never the live jurisdiction row.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer cents; there are no fractional cents anywhere in the system. Tier arithmetic is exact in cents. Rounding, where the fee schedule calls for it, is always round half up to whole cents, and it is applied at exactly the pinned steps named in §3.2 and §3.7 — rounding is not applied anywhere else, and it is never applied to a sum after the fact. This discipline matters because the estimated fee and the final fee are both auditable figures that a building department or an applicant can recompute by hand.

### 2.8. Turnaround Timekeeping and the Logical Clock

The server keeps a logical clock rather than reading wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `PlatformAdmin` may advance it through an admin-only test-driving capability that accepts a target instant in the `to_iso8601` field and reports the new reading back as `current_utc`. A `to_iso8601` value without an explicit timezone offset is read as UTC; a value that does not parse as an ISO 8601 timestamp is rejected with `ERR_INVALID_REQUEST`. Every system timestamp in this document — `received_at`, `due_at`, `completed_at`, `assigned_at`, `ended_at`, `sealed_at`, `transmitted_at`, and the date used for license-expiry comparisons — is read from this logical clock. Deadline arithmetic is performed at millisecond precision, and business-day deadlines always land at end-of-day `23:59:59.999Z` (§3.3).

### 2.9. Optimistic Concurrency Control on Cycle Assignment

Creating a review assignment is the one write operation guarded by optimistic concurrency control, because creating an assignment legitimately supersedes any existing `ACTIVE` assignment on the same cycle — a writer holding a stale view of the cycle would silently release an assignment it never observed. A request to `POST /plan-review/assignments` must therefore carry `expected_cycle_version`, set to the value of the target cycle's `version` the client last observed. If that value does not equal the cycle's current `version` — because another writer has advanced it since — the creation is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). This check runs at the state-precondition layer (layer 7 of §2.4), before any business validation. No other endpoint takes a version field.

### 2.10. Licensing and Segregation of Duties

Three licensing invariants run through the whole lifecycle, and §3 references them at each point of enforcement. First, the reviewer of record must hold a license for the state governing the engagement at the moment the engagement is registered. Second, any reviewer assigned to a cycle must hold a license covering the engagement's pinned state whose validity extends at least to the cycle's due date. Third, the reviewer who seals the record must hold a license for the pinned state that is unexpired on the seal date — and where the jurisdiction's pinned rules demand a Structural Engineer seal, that license must be an SE license rather than a PE. Separately, waiver authority is segregated: a chief reviewer may never waive a deficiency comment on an engagement where they themselves are the reviewer of record. Reviewer capacity is likewise a standing invariant — no reviewer may hold more `ACTIVE` assignments than their registered maximum.

## 3. Business Logic & Workflows

### 3.1. Firm Setup: Jurisdictions and the Reviewer Registry

Before the first engagement can be registered, a `PlatformAdmin` builds the firm's configuration. Each jurisdiction is registered with its two-letter `state_code` (exactly two uppercase ASCII letters — anything else is an `ERR_INVALID_REQUEST` — and unique across all jurisdictions, a duplicate registration being rejected with `ERR_DUPLICATE_JURISDICTION_STATE`), its adopted building code edition `ibc_edition` (one of `IBC_2018`, `IBC_2021`, `IBC_2024`), its adopted loads standard `asce7_edition` (`ASCE7_16` or `ASCE7_22`), its `fee_method` (`VALUATION` for a schedule tiered on declared construction valuation, or `SQUARE_FOOTAGE` for a per-square-foot schedule by building type), its base `turnaround_days`, and its `sla_mode` (`BUSINESS` or `CALENDAR`). Three optional knobs carry defaults when omitted: `free_resubmittal_cycles` defaults to 2, `requires_se_seal` defaults to false, and `allows_deferred_submittals` defaults to true. A jurisdiction's rule parameters may later be updated in part — any subset of `ibc_edition`, `asce7_edition`, `fee_method`, `turnaround_days`, `sla_mode`, `free_resubmittal_cycles`, `requires_se_seal`, and `allows_deferred_submittals` — but per §2.6 such an update touches only engagements registered afterwards and increments the jurisdiction's `version` by 1.

Reviewers are registered with a `full_name`, a `licenses` array in which each entry records a `state_code`, a `license_type` (`PE` or `SE`), a `license_number`, and an `expires_on` date in `YYYY-MM-DD` form, and an optional `max_concurrent_assignments` defaulting to 3. A license entry missing any of its four fields, carrying a `license_type` outside `PE`/`SE`, or carrying an unparseable `expires_on` is rejected with `ERR_INVALID_REQUEST`. A reviewer's `active_assignment_count` starts at 0 on registration and is thereafter a computed figure: the count of that reviewer's assignments currently in `ACTIVE` status.

### 3.2. Engagement Registration, Amendment, and the Estimated Fee

A `ReviewCoordinator` opens a plan review engagement by supplying the `project_name`, the governing `jurisdiction_id`, the design-firm contact `applicant_contact_id`, the engineer in responsible charge `reviewer_of_record_id`, the `building_type` (`RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`, or `ESSENTIAL_FACILITY`), the ASCE 7 `risk_category` (`I`, `II`, `III`, or `IV`), the review `scope` (`FULL_REVIEW`, `LATERAL_ONLY`, or `PEER_REVIEW`), the `declared_valuation_cents`, the gross `floor_area_sqft`, and optionally `requested_expedite` (default false). The named reviewer of record must hold a license whose `state_code` equals the state of the jurisdiction being pinned; otherwise registration fails with `ERR_LICENSE_STATE_MISMATCH`. The new engagement is born `REGISTERED` with `cycle_count`, `unresolved_comment_count`, and `deferred_pending_count` all at 0, the pinned snapshot of §2.6 copied from its jurisdiction, and `final_fee_cents` null — it stays null until the record is sealed.

Registration is also when the **estimated fee** is computed, and it is never recomputed afterwards, even if valuation, area, or expedite are later amended. Under the `VALUATION` fee method, the base fee tiers the declared valuation: the portion up to one hundred thousand dollars is priced at one percent; the portion above one hundred thousand dollars, up to a cumulative five hundred thousand dollars, at three-quarters of one percent; and any remainder above five hundred thousand dollars at one-half of one percent. Under the `SQUARE_FOOTAGE` method, the base fee is the gross floor area multiplied by the per-square-foot rate for the building type — 40 cents for `RESIDENTIAL`, 55 for `COMMERCIAL`, 45 for `INDUSTRIAL`, and 70 for `ESSENTIAL_FACILITY`. Either way, the base is then raised to a five-hundred-dollar minimum if it falls short. The scoped base is the base multiplied by the scope factor — full rate for `FULL_REVIEW`, sixty percent for `LATERAL_ONLY`, eighty percent for `PEER_REVIEW` — rounded half up to whole cents; this is the first of the two pinned rounding steps of §2.7. If expedited turnaround was requested, an expedite component of half the *rounded* scoped base is itself rounded half up to whole cents — the second pinned rounding step — and added; otherwise the expedite component is zero. The `estimated_fee_cents` recorded on the engagement is the scoped base plus the expedite component. Because registration implies zero cycles used and no deferred items, the resubmittal and deferred components described in §3.7 are always zero here.

While an engagement remains `REGISTERED` or `IN_PROGRESS`, the coordinator may amend `declared_valuation_cents`, `floor_area_sqft`, and `requested_expedite`; each amendment increments the engagement's `version`. Once the engagement reaches `APPROVED`, `COMPLETED`, or `CANCELLED`, amendment is rejected with `ERR_ENGAGEMENT_NOT_AMENDABLE`. Amendments matter at seal time: the final fee of §3.7 reads the *current*, possibly amended, values — one of the two reasons the final fee can diverge from the estimate. The engagement listing supports optional `jurisdiction_id`, `reviewer_of_record_id`, and `status` filters alongside `limit` and `offset`.

### 3.3. Review Cycles: Opening, Supersession, and Turnaround

Work on an engagement proceeds through review cycles, each wrapping one submitted plan set. A cycle may be opened by the `ReviewCoordinator` or by the `Applicant` who owns the engagement — an applicant caller whose `X-User-ID` does not equal the engagement's `applicant_contact_id` is turned away with `ERR_NOT_ENGAGEMENT_APPLICANT`. The request names the `engagement_id` and the `documents_ref` URI of the plan set. The engagement must be `REGISTERED`, `IN_PROGRESS`, or `APPROVED`; from any other status the request fails with `ERR_ENGAGEMENT_NOT_ACTIVE`, and from `APPROVED` there is a further gate — the engagement's review record must still be `DRAFT`, because revision is impossible once the record is `SEALED` or `TRANSMITTED` (`ERR_RECORD_ALREADY_SEALED`).

Cycles are strictly single-slot. If the engagement already has an `OPEN` or `IN_REVIEW` cycle, opening another is rejected with `ERR_CYCLE_STILL_ACTIVE`. If the previous cycle rests at `COMMENTS_ISSUED`, the new cycle supersedes it: the old cycle moves `COMMENTS_ISSUED → SUPERSEDED` — a terminal state, like `APPROVED` and `CANCELLED` — and any `ACTIVE` assignments on it move to `COMPLETED`. Cycle numbering is 1-based and monotonic per engagement — the engagement's `cycle_count` increments and the new cycle's `cycle_number` takes that value — and numbers are never reused, even after cancellations. Opening the first cycle walks the engagement `REGISTERED → IN_PROGRESS`; opening a revision cycle on an `APPROVED` engagement walks it `APPROVED → IN_PROGRESS`. Either way the engagement's `version` increments by 1. The cycle's `received_at` is stamped from the logical clock at creation, and the new cycle is born `OPEN` with `load_path_confirmed` and `lateral_system_confirmed` both false. The cycles listing accepts optional `engagement_id` and `status` filters.

The cycle's `due_at` is computed at creation from the pinned turnaround policy and the engagement's expedite flag, in a pinned order: first the effective day count is derived — when `requested_expedite` is set, half of `pinned_turnaround_days` rounded *up* to a whole number of days; otherwise `pinned_turnaround_days` unchanged — and only then is the day-counting mode applied. Under the `CALENDAR` mode, `due_at` is simply `received_at` plus the effective number of 24-hour periods, preserving the time of day. Under the `BUSINESS` mode, the count starts from the calendar date of `received_at` — the received day itself is never counted — and advances one calendar day at a time, skipping over every Saturday and Sunday, until the effective number of business days has been counted; `due_at` is then end-of-day `23:59:59.999Z` on that final day, at millisecond precision. Business mode therefore always yields a strictly later deadline than calendar mode for the same receipt instant and day count.

A cycle completes when the reviewer either issues the comment letter or approves the plans (§3.5, §3.7). At completion, `completed_at` is stamped from the logical clock and `is_on_time` is computed as whether `completed_at` is no later than `due_at` — an exact tie counts as on time. Until completion, both `completed_at` and `is_on_time` are null.

### 3.4. Assignments and Reviewer Capacity

A `ReviewCoordinator` places work by creating a review assignment naming the `cycle_id` and `reviewer_id`, and — per §2.9 — carrying `expected_cycle_version`; a value that no longer matches the cycle's current `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), and a successful creation increments the cycle's `version` by 1. The target cycle must be `OPEN` or `IN_REVIEW`; any other state fails with `ERR_CYCLE_NOT_ASSIGNABLE`. Two regulatory checks follow. The named reviewer must hold a license whose `state_code` covers the engagement's `pinned_state_code` (`ERR_LICENSE_STATE_MISMATCH`), and that license's `expires_on` must be on or after the date of the cycle's `due_at` (`ERR_LICENSE_WINDOW_INSUFFICIENT`). Then the capacity gate: the reviewer's `active_assignment_count` must be below their `max_concurrent_assignments` — the comparison is inclusive at the boundary, so a reviewer already at their maximum is rejected with `ERR_REVIEWER_CAPACITY_EXCEEDED`, while one slot below maximum is admitted.

Creating an assignment is also the reassignment mechanism: any existing `ACTIVE` assignment on the same cycle moves to `RELEASED`, its `ended_at` is stamped, and its reviewer's `active_assignment_count` is decremented. The new assignment is born `ACTIVE` with `assigned_at` stamped from the logical clock and `ended_at` null; the assignee's `active_assignment_count` increments. The very first assignment on a cycle walks the cycle `OPEN → IN_REVIEW`. A coordinator may also release an `ACTIVE` assignment outright as the compensating action for assignment creation — same effects: `ACTIVE → RELEASED`, `ended_at` stamped, count decremented. Releasing an assignment that is not `ACTIVE` is rejected with `ERR_INVALID_STATE_TRANSITION`. When a cycle ends — approved, superseded, or cancelled — its remaining `ACTIVE` assignments complete or release by cascade as described in §3.5, §3.7, and §3.8, each recording `ended_at` and decrementing its reviewer's count. The assignments listing accepts optional `cycle_id`, `reviewer_id`, and `status` filters.

### 3.5. Deficiency Comments, Response Rounds, and Waiver

While a cycle is `IN_REVIEW`, the assigned reviewer raises deficiency comments against it. Each comment carries the `raised_in_cycle_id` of its cycle, a `code_section_ref` citation such as `1604.3` or `2308.6.1`, the `reference_edition` of the code being cited, a `severity` (`MINOR`, `MAJOR`, or `CRITICAL`), a `category` (`LOAD_PATH`, `LATERAL_SYSTEM`, `CALCULATION`, `DETAILING`, or `DEFERRED_COORDINATION`), and the `comment_text` itself. Raising on a cycle that is not `IN_REVIEW` fails with `ERR_CYCLE_NOT_IN_REVIEW`; a caller who is not the reviewer on that cycle's `ACTIVE` assignment fails with `ERR_NOT_ASSIGNED_REVIEWER`. Because the engagement is reviewed against its pinned editions, the `reference_edition` must equal the engagement's `pinned_ibc_edition`; a mismatch is rejected with `ERR_CODE_EDITION_MISMATCH`. The new comment's `engagement_id` is copied from its cycle, `raised_by_reviewer_id` is set from the caller's `X-User-ID`, `response_count` starts at 0, and the comment is born `OPEN` — and the engagement's `unresolved_comment_count` increments by 1. The comments listing accepts optional `engagement_id`, `raised_in_cycle_id`, `raised_by_reviewer_id`, and `status` filters.

When the review pass is finished, the assigned reviewer issues the comment letter, moving the cycle `IN_REVIEW → COMMENTS_ISSUED`. Issuance requires something to say: at least one comment raised in this cycle, or at least one comment of the engagement currently `REOPENED` and awaiting a new response round; otherwise the request fails with `ERR_NO_COMMENTS_TO_ISSUE`. A caller who is not the cycle's assigned reviewer is rejected with `ERR_NOT_ASSIGNED_REVIEWER`, and a cycle not in `IN_REVIEW` rejects with `ERR_CYCLE_NOT_IN_REVIEW`. Issuance completes the cycle per §3.3: `completed_at` is stamped and `is_on_time` computed.

The applicant then answers, comment by comment. Posting a response with `response_text` requires the comment to be `OPEN` or `REOPENED` and the engagement's current non-terminal cycle to be `COMMENTS_ISSUED`; a violation of either condition is rejected with `ERR_COMMENT_NOT_AWAITING_RESPONSE`. As with all applicant-scoped actions, `X-User-ID` must equal the engagement's `applicant_contact_id` (`ERR_NOT_ENGAGEMENT_APPLICANT`). A successful response creates an immutable `CommentResponse` recording the `comment_id` and the `responder_contact_id` taken from the caller, increments the comment's `response_count` by 1, and moves the comment to `ADDRESSED` — from `OPEN` or from `REOPENED` alike. Note what does *not* happen: the engagement's `unresolved_comment_count` is unchanged, because `ADDRESSED` still counts as unresolved. The engagement's `unresolved_comment_count` is defined as the number of its deficiency comments in `OPEN`, `ADDRESSED`, or `REOPENED` status; only `VERIFIED` and `WAIVED` leave the unresolved set. Responses to a comment can be listed in chronological order with `limit` and `offset`.

Resolution happens in a later cycle, while the engagement's current non-terminal cycle is `IN_REVIEW`. The reviewer on *that current* cycle's `ACTIVE` assignment — not necessarily the original raiser — evaluates each `ADDRESSED` comment. Verifying a response moves the comment `ADDRESSED → VERIFIED` and decrements the engagement's `unresolved_comment_count` by 1. Reopening instead moves it `ADDRESSED → REOPENED`, leaves the count unchanged (a `REOPENED` comment is still unresolved), and requires a `reopen_note` in the payload — its absence is an `ERR_INVALID_REQUEST`. Both actions demand the current-cycle `IN_REVIEW` condition (`ERR_NO_ACTIVE_REVIEW_CYCLE` otherwise), the assigned-reviewer identity check (`ERR_NOT_ASSIGNED_REVIEWER`), and a comment actually sitting in `ADDRESSED` (`ERR_COMMENT_NOT_ADDRESSED` on any other state); the checks fire in that order, the current-cycle condition first, because the relevant cycle must be identified before its assignee can be compared.

A `ChiefReviewer` holds a parallel resolution path: waiver. Waiving moves a comment from `OPEN`, `ADDRESSED`, or `REOPENED` to `WAIVED` and decrements `unresolved_comment_count` by 1; the payload carries a `justification`. A comment in any other status (`VERIFIED`, or already `WAIVED`) is rejected with `ERR_INVALID_REQUEST`. Two bars apply with equal force on all three source states: a `CRITICAL` comment can never be waived (`ERR_CRITICAL_COMMENT_NOT_WAIVERABLE`), and the acting chief reviewer must not be the engagement's `reviewer_of_record_id` — segregation of duties forbids engineers from waiving findings on their own engagements (`ERR_WAIVER_SEGREGATION_VIOLATION`). Where several waiver checks fail at once, they fire in the order given: state, then the CRITICAL bar, then segregation.

### 3.6. Deferred Submittals

Trusses, anchors, and other delegated-design items are often engineered after the main plan set. Where the pinned rules allow it, the applicant registers a deferred submittal on the engagement with an `item_type` (`TRUSS`, `ANCHOR`, `STEEL_CONNECTION`, `CURTAIN_WALL`, or `OTHER_DELEGATED`) and a `description`, naming the `engagement_id`. Registration is applicant-scoped (`ERR_NOT_ENGAGEMENT_APPLICANT`), requires the engagement to be `IN_PROGRESS` or `APPROVED` (`ERR_ENGAGEMENT_NOT_ACTIVE`), and requires the engagement's `pinned_allows_deferred_submittals` to be true (`ERR_DEFERRED_NOT_PERMITTED`). The item is born `REGISTERED` with its `documents_ref` and `rejection_reason` both null, and the engagement's `deferred_pending_count` increments by 1. That count is defined as the number of the engagement's deferred submittals in `REGISTERED`, `SUBMITTED`, or `REJECTED` status; only `APPROVED` items leave the pending set. The deferred-submittals listing accepts optional `engagement_id` and `status` filters.

The applicant then submits the deferred design documents by supplying the `documents_ref` URI, moving the item to `SUBMITTED` — from `REGISTERED` on first submission, or from `REJECTED` on resubmission, in which case the stored `rejection_reason` is cleared back to null; from any other status the submission is rejected with `ERR_INVALID_STATE_TRANSITION`. The pending count is unchanged either way, since `SUBMITTED` is still pending. Ownership is checked as usual (`ERR_NOT_ENGAGEMENT_APPLICANT`).

Judgment belongs to the reviewer of record personally. Approving moves a `SUBMITTED` item to `APPROVED` and decrements `deferred_pending_count` by 1; rejecting moves it to `REJECTED`, stores the supplied `rejection_reason` (its absence is an `ERR_INVALID_REQUEST`), and leaves the count unchanged, since `REJECTED` remains pending while awaiting resubmittal. Either action attempted on an item not currently `SUBMITTED` is rejected with `ERR_INVALID_STATE_TRANSITION`. Both actions require `X-User-ID` to equal the engagement's `reviewer_of_record_id`; anyone else — including the assigned cycle reviewer — is rejected with `ERR_NOT_RESPONSIBLE_CHARGE`.

### 3.7. Approval, the Sealed Record, and the Final Fee

The assigned reviewer approves a cycle with an attestation payload: `load_path_confirmed` and `lateral_system_confirmed` must both be true — anything less is rejected with `ERR_VERIFICATION_INCOMPLETE`. Approval also requires the engagement's `unresolved_comment_count` to be exactly zero (`ERR_UNRESOLVED_COMMENTS_REMAIN` while any comment remains `OPEN`, `ADDRESSED`, or `REOPENED`), the assigned-reviewer identity check (`ERR_NOT_ASSIGNED_REVIEWER`), and a cycle in `IN_REVIEW` (`ERR_CYCLE_NOT_IN_REVIEW`). On success the cycle moves `IN_REVIEW → APPROVED`; `completed_at` is stamped and `is_on_time` computed per §3.3; both attestation booleans are stored on the cycle; the cycle's `ACTIVE` assignments move to `COMPLETED` with `ended_at` stamped and reviewer counts decremented; and the engagement cascades `IN_PROGRESS → APPROVED`.

That engagement cascade is where the **review record** enters. If no record exists yet for the engagement, one is created in `DRAFT` carrying snapshots of the engagement's `pinned_ibc_edition` and `pinned_asce7_edition` and a `cycle_count_snapshot` equal to the engagement's `cycle_count` at that moment; its human-readable `record_number` is composed of the literal prefix `RR-`, the engagement's `pinned_state_code`, a hyphen, and the engagement's `cycle_count` at creation rendered zero-padded to (at least) two digits, as in `RR-WA-03`. Its `sealed_by_reviewer_id`, `sealed_at`, and `transmitted_at` are all null. If a `DRAFT` record already exists — this is a re-approval after a revision cycle — its pinned edition snapshots and `cycle_count_snapshot` are refreshed to the current values instead. Either way the engagement's `version` increments by 1. Exactly one record ever exists per engagement; the records listing accepts optional `engagement_id`, `sealed_by_reviewer_id`, and `status` filters.

Sealing is the regulatory climax, performed by the reviewer of record through the record's seal action. The record must be `DRAFT` (`ERR_RECORD_INVALID_STATE` otherwise). The engagement must currently be `APPROVED` — an engagement reopened to `IN_PROGRESS` by a revision cycle cannot have its record sealed (`ERR_ENGAGEMENT_NOT_APPROVED`). The caller must be the engagement's `reviewer_of_record_id` (`ERR_NOT_RESPONSIBLE_CHARGE`). The sealer must hold a license whose `state_code` equals the engagement's `pinned_state_code` (`ERR_LICENSE_STATE_MISMATCH`), that license's `expires_on` must be on or after the current logical date (`ERR_LICENSE_WINDOW_INSUFFICIENT`), and where the engagement's `pinned_requires_se_seal` is true the license's `license_type` must be `SE` rather than `PE` (`ERR_SE_SEAL_REQUIRED`). Finally — the referential-completeness layer — the engagement's `deferred_pending_count` must be exactly zero: every deferred item approved, none outstanding (`ERR_DEFERRED_SUBMITTALS_OUTSTANDING`). On success the record moves `DRAFT → SEALED`, `sealed_by_reviewer_id` is set from the caller, `sealed_at` is stamped, and the engagement's `version` increments by 1.

Sealing is also when the **final fee** is computed and stored in `final_fee_cents`. The base, scoped base, and expedite component are computed exactly as in §3.2 — same tiers, same per-square-foot rates, same five-hundred-dollar floor, same scope factors, same two pinned round-half-up steps — but reading the engagement's *current* `declared_valuation_cents`, `floor_area_sqft`, and `requested_expedite`, so amendments made along the way flow into the final figure. Two further components join. The resubmittal component charges seventy-five thousand cents for every cycle beyond the free allowance: the engagement's `cycle_count` minus its `pinned_free_resubmittal_cycles`, floored at zero, multiplied by 75,000. The deferred component charges, for each deferred submittal of the engagement currently `APPROVED`, five percent of the rounded scoped base — each per-item fee rounded half up to whole cents *first*, and the rounded per-item fees then summed; this per-item-then-sum order is pinned and observable. The `final_fee_cents` is the scoped base plus the expedite, resubmittal, and deferred components, all integer cents with no further rounding. It diverges from the estimate whenever cycles exceeded the free allowance, deferred items were approved, or the fee inputs were amended.

A `ReviewCoordinator` closes the loop by transmitting the sealed record to the building department. The record must be `SEALED` (`ERR_RECORD_INVALID_STATE` otherwise); on success it moves `SEALED → TRANSMITTED`, `transmitted_at` is stamped, and the engagement cascades `APPROVED → COMPLETED`, its terminal resting state.

### 3.8. Cancellation

A `ReviewCoordinator` may cancel an engagement while it is `REGISTERED` or `IN_PROGRESS`; from `APPROVED`, `COMPLETED`, or `CANCELLED` the attempt is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`. Cancellation cascades downward to keep the hierarchy consistent: every non-terminal cycle of the engagement — `OPEN`, `IN_REVIEW`, or `COMMENTS_ISSUED` — moves to `CANCELLED`, and every `ACTIVE` assignment on those cycles moves to `RELEASED`, with `ended_at` stamped and the affected reviewers' `active_assignment_count` decremented, freeing their capacity. Cancellation is terminal; the engagement's cycle numbers, comment history, and deferred items remain on the record for audit.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, amendments, seal and transmit actions, the clock advance — return `200 OK`, as do all reads. Error responses use the status codes catalogued in §5. Each action endpoint returns the resource its path names: cycle actions (`issue-comments`, `approve`) return the cycle, comment resolution actions (`verify`, `reopen`, `waive`) return the comment, deferred-submittal actions (`submit`, `approve`, `reject`) return the submittal, record actions (`seal`, `transmit`) return the record, assignment `release` returns the assignment, and engagement `cancel` returns the engagement; posting a comment response returns the newly created `CommentResponse`, and the clock endpoint returns an object carrying `current_utc`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plan-review/jurisdictions` | Register a jurisdiction (state) with its adopted code editions, fee method, and turnaround policy | PlatformAdmin |
| GET | `/plan-review/jurisdictions/{id}` | Get a jurisdiction | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| PUT | `/plan-review/jurisdictions/{id}` | Update jurisdiction rule parameters; existing engagements keep their pinned snapshots | PlatformAdmin |
| POST | `/plan-review/reviewers` | Register a reviewer with licenses and capacity limit | PlatformAdmin |
| GET | `/plan-review/reviewers/{id}` | Get a reviewer, including computed active assignment count | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| POST | `/plan-review/engagements` | Register a plan review engagement; pins the jurisdiction rule snapshot and computes the estimated fee | ReviewCoordinator |
| GET | `/plan-review/engagements` | List engagements with optional filters | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| GET | `/plan-review/engagements/{id}` | Get an engagement, including fees, counts, and the pinned snapshot | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| PUT | `/plan-review/engagements/{id}` | Amend valuation, area, or expedite while the engagement is amendable | ReviewCoordinator |
| POST | `/plan-review/engagements/{id}/cancel` | Cancel an engagement and cascade to its cycles and assignments | ReviewCoordinator |
| POST | `/plan-review/cycles` | Open a review cycle (initial submittal or resubmittal); supersedes a comments-issued prior cycle | ReviewCoordinator, Applicant |
| GET | `/plan-review/cycles` | List review cycles with optional filters | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| GET | `/plan-review/cycles/{id}` | Get a review cycle, including deadline and on-time status | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| POST | `/plan-review/cycles/{id}/issue-comments` | Issue the deficiency comment letter to the applicant; completes the review pass | Reviewer |
| POST | `/plan-review/cycles/{id}/approve` | Approve the cycle; cascades to engagement approval and record creation or refresh | Reviewer |
| POST | `/plan-review/assignments` | Assign a reviewer to a cycle (OCC-guarded; supersedes any active assignment on that cycle) | ReviewCoordinator |
| GET | `/plan-review/assignments` | List assignments with optional filters | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| GET | `/plan-review/assignments/{id}` | Get an assignment | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| POST | `/plan-review/assignments/{id}/release` | Release an active assignment | ReviewCoordinator |
| POST | `/plan-review/comments` | Raise a deficiency comment during an in-review cycle | Reviewer |
| GET | `/plan-review/comments` | List deficiency comments with optional filters | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| GET | `/plan-review/comments/{id}` | Get a deficiency comment | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| POST | `/plan-review/comments/{id}/responses` | Applicant responds to a deficiency comment | Applicant |
| GET | `/plan-review/comments/{id}/responses` | List responses for a comment in chronological order | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| POST | `/plan-review/comments/{id}/verify` | Assigned reviewer of the current in-review cycle accepts the response | Reviewer |
| POST | `/plan-review/comments/{id}/reopen` | Assigned reviewer rejects the response | Reviewer |
| POST | `/plan-review/comments/{id}/waive` | Chief reviewer waives a non-critical comment (never the reviewer of record) | ChiefReviewer |
| POST | `/plan-review/deferred-submittals` | Register a deferred submittal item on an engagement | Applicant |
| GET | `/plan-review/deferred-submittals` | List deferred submittals with optional filters | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| GET | `/plan-review/deferred-submittals/{id}` | Get a deferred submittal | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| POST | `/plan-review/deferred-submittals/{id}/submit` | Applicant submits (or resubmits after rejection) deferred design documents | Applicant |
| POST | `/plan-review/deferred-submittals/{id}/approve` | Reviewer of record approves a submitted deferred item | Reviewer |
| POST | `/plan-review/deferred-submittals/{id}/reject` | Reviewer of record rejects a submitted deferred item | Reviewer |
| GET | `/plan-review/records` | List review records with optional filters (at most one per engagement) | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| GET | `/plan-review/records/{id}` | Get a review record | PlatformAdmin, ReviewCoordinator, Reviewer, ChiefReviewer, Applicant |
| POST | `/plan-review/records/{id}/seal` | Reviewer of record seals the record; computes the engagement's final fee | Reviewer |
| POST | `/plan-review/records/{id}/transmit` | Transmit the sealed record to the building department; completes the engagement | ReviewCoordinator |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_REVIEWER_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_COMMENT_NOT_FOUND` | 404 |
| `ERR_DEFERRED_SUBMITTAL_NOT_FOUND` | 404 |
| `ERR_RECORD_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_JURISDICTION_STATE` | 409 |
| `ERR_LICENSE_STATE_MISMATCH` | 422 |
| `ERR_LICENSE_WINDOW_INSUFFICIENT` | 422 |
| `ERR_SE_SEAL_REQUIRED` | 422 |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 |
| `ERR_ENGAGEMENT_NOT_AMENDABLE` | 409 |
| `ERR_CYCLE_STILL_ACTIVE` | 409 |
| `ERR_RECORD_ALREADY_SEALED` | 409 |
| `ERR_CYCLE_NOT_IN_REVIEW` | 409 |
| `ERR_CYCLE_NOT_ASSIGNABLE` | 409 |
| `ERR_NO_COMMENTS_TO_ISSUE` | 409 |
| `ERR_UNRESOLVED_COMMENTS_REMAIN` | 409 |
| `ERR_VERIFICATION_INCOMPLETE` | 422 |
| `ERR_CODE_EDITION_MISMATCH` | 422 |
| `ERR_COMMENT_NOT_AWAITING_RESPONSE` | 409 |
| `ERR_COMMENT_NOT_ADDRESSED` | 409 |
| `ERR_NO_ACTIVE_REVIEW_CYCLE` | 409 |
| `ERR_NOT_ENGAGEMENT_APPLICANT` | 403 |
| `ERR_NOT_ASSIGNED_REVIEWER` | 403 |
| `ERR_NOT_RESPONSIBLE_CHARGE` | 403 |
| `ERR_WAIVER_SEGREGATION_VIOLATION` | 403 |
| `ERR_CRITICAL_COMMENT_NOT_WAIVERABLE` | 422 |
| `ERR_DEFERRED_NOT_PERMITTED` | 422 |
| `ERR_DEFERRED_SUBMITTALS_OUTSTANDING` | 409 |
| `ERR_ENGAGEMENT_NOT_APPROVED` | 409 |
| `ERR_RECORD_INVALID_STATE` | 409 |
| `ERR_REVIEWER_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |

# Assessment Item Bank API — Product Requirements Document

## 1. Introduction

State assessment vendors live and die by the defensibility of their item banks. Every test question must survive a gauntlet of content review, bias and sensitivity screening, statistical field testing, and controlled assembly into scored forms — and at each step the vendor must be able to prove, often years later in a state audit or a contract dispute, exactly who touched an item, which committee approved it, how it performed statistically, and how widely it has been exposed. Today these records are typically scattered across spreadsheets, shared drives, and ad-hoc databases, which makes it impossible to enforce segregation of duties between content and bias reviewers, to cap item exposure before a form goes to print, or to reconstruct the evidence trail behind a published test.

This document specifies the Assessment Item Bank API, a system that manages the complete lifecycle of assessment content for one or more assessment programs. It governs item authoring and alignment to content standards, dual committee review (content and bias/sensitivity) with quorum-based verdict tallying, field-test windows and the computation of item difficulty and discrimination statistics, blueprint-driven form assembly with depth-of-knowledge balancing, statistical equating across forms, item exposure control and retirement, secure storage with scoped access grants, translation and accommodation variants, and the validity documentation that must exist before any form may be published. The API is the single source of truth for all of these concerns, and every rule in this document is a hard requirement.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, principles, and cross-cutting rules that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the named role is not among the roles an endpoint admits, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `ProgramDirector`, `ItemWriter`, `ContentReviewer`, `BiasSensitivityReviewer`, `Psychometrician`, `TestAssembler`, `SecurityOfficer`, and `TranslationSpecialist`. For each of these eight roles — `ProgramDirector`, `ItemWriter`, `ContentReviewer`, `BiasSensitivityReviewer`, `Psychometrician`, `TestAssembler`, `SecurityOfficer`, and `TranslationSpecialist` alike — `X-User-ID` is an opaque operator identifier that is not tied to the `id` of any persisted entity. The server may record it (for example, as `author_user_id` on an Item at creation time, or as `reviewer_user_id` on a ReviewVerdict when a verdict is cast), and ownership-style checks compare the recorded field against the caller's `X-User-ID`, but no role's identity resolves to a stored entity.

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

List endpoints accept two query parameters to page through results. The `limit` parameter caps the number of resources returned in one response; it defaults to 10 when omitted, and any supplied value must be at least 1 and no more than 100. The `offset` parameter skips a number of resources from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order.

The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource in the system carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp, which records when the resource was first created as an ISO 8601 UTC timestamp with three fractional digits. With one exception, every resource also carries `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification, and `version`, a system-managed integer that increments by one on every mutation of the resource and that anchors the optimistic concurrency mechanism described in §2.7. Any change to a resource — including changes the server applies as a side effect of some other operation — refreshes that resource's `updated_at` and increments its `version`.

The sole exception is the ItemResponse resource. An ingested response is an immutable measurement record: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it. Even when a psychometrician later invalidates a response by setting its `excluded` flag, no `updated_at` or `version` is maintained on the record.

### 2.5. The Program Logical Clock

Each assessment program runs on its own logical clock, exposed as `current_period_utc` on the program resource. The clock is initialized to exactly `2026-08-01T00:00:00Z` when the program is created and never moves on its own. A `ProgramDirector` advances it through a clock-advance capability that takes a `by_seconds` argument and adds that many seconds to `current_period_utc`.

The logical clock is the single time source for everything the system stamps or checks. System-set timestamps — `started_at` and `closed_at` on review sessions, `submitted_at` on verdicts, `finalized_at` on final statistics, `assembled_at` and `published_at` on forms, `equated_at` on equating links, `retired_at` on items, `revoked_at` on access grants, and `published_at` on dossiers — all read from the owning program's `current_period_utc`. Temporal guards, such as whether a review session may open, whether a field-test window is within its bounds, whether an access grant currently covers an operation, and whether a form is old enough to archive, are likewise evaluated against `current_period_utc`, never against wall-clock time.

### 2.6. Statistical Precision and Rounding

All computed item statistics — `p_value` and `point_biserial` on an ItemStatistic row, and their mirrored counterparts `p_value_provisional`, `p_value_final`, `point_biserial_provisional`, and `point_biserial_final` on the Item — are rounded to exactly 4 decimal places using round-half-up. Equating coefficients (`scaling_slope` and `scaling_intercept`) are rounded to exactly 6 decimal places, also round-half-up. Exposure accounting is exact integer arithmetic: `operational_exposure_count` is a whole-number count that is never fractional and never negative.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are version-guarded, and each requires its version field as a non-optional input. Submitting an item for review requires the request to carry `expected_item_version`, holding the item's `version` as the client last observed it. Assembling a test form requires `expected_form_version`, holding the form's `version` as the client last observed it. In both cases, if the supplied value does not equal the resource's current `version` — because another write, such as a content edit or a slot addition, has advanced the resource since the client's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on state it has not observed. No other endpoint accepts a version field.

### 2.8. Validation Pipeline and Error Precedence

When several checks could fail on the same request, the system evaluates them in a fixed order and returns the error of the first failing check. Requests with a missing required field, a type mismatch, or an unrecognized enum value are structurally invalid and fail with `ERR_INVALID_REQUEST` (HTTP 400).

The precedence order is as follows. Header presence and parseability are checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role admissibility for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`). Path parameters are resolved next, left to right (`ERR_NOT_FOUND`). On the two version-guarded writes, the optimistic concurrency check follows (`ERR_STALE_VERSION`), ahead of entity state preconditions, which reject with the most specific state error available, falling back to the generic `ERR_INVALID_STATE` (HTTP 409) when no dedicated error exists. Business-safety gates come after state checks, in this sequence: scoped access-grant coverage (`ERR_NO_ACTIVE_GRANT`), then reviewer segregation of duties (`ERR_SOD_REVIEWER_CONFLICT`), then the bias gate (`ERR_BIAS_GATE_NOT_PASSED`). Uniqueness collisions (`ERR_DUPLICATE_CODE`) are detected before temporal validation of windows (`ERR_WINDOW_TIME_INVALID`) and session readiness (`ERR_SESSION_NOT_READY`), which in turn precede referential checks on ingested responses (`ERR_ITEM_NOT_FIELD_TESTABLE`) and slot additions (`ERR_SLOT_ITEM_INVALID`). Anchor-set validity (`ERR_ANCHOR_SET_INVALID`) is checked before the over-exposure guard (`ERR_WOULD_OVER_EXPOSE`), variant-kind consistency (`ERR_VARIANT_KIND_MISMATCH`) before the verdict rationale requirement (`ERR_RATIONALE_REQUIRED`), and the grant-overlap (`ERR_GRANT_OVERLAP`) and dossier-content (`ERR_DOSSIER_INVALID`) checks close out the pipeline.

### 2.9. Hierarchical Consistency and Cascading Effects

State changes propagate through the entity hierarchy to keep the bank internally consistent, and the server performs these propagations automatically when their criteria are met, without an explicit client request on the affected resource. The cascading families in this system are: an item that becomes `REJECTED` or `RETIRED` drags every non-terminal variant of that item into `REJECTED`; an item marked `COMPROMISED` has its slots stripped from every non-archived form, and the affected forms are forced back into rework; cancelling an open review session soft-deletes its verdicts; closing a field-test window pushes every tested item forward into statistics review; and creating an equating link advances its target form. Each such reconciliation mutates the affected resources in the ordinary way, refreshing `updated_at` and incrementing `version` where those fields exist. Section 3 details each cascade alongside the workflow that triggers it.

### 2.10. Nested Resource Retrieval

Requests that target nested resources are validated strictly from left to right across the path. Each identifier in the path must resolve to an existing resource before the next identifier is examined, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. A verdict submission under a review session that does not exist, for example, fails on the session identifier before the system ever considers the verdict's payload. Existence checks precede every state, grant, and business-rule evaluation on the resolved resources. Throughout the endpoint table of §4, path variables name the addressed resource at each hierarchy level: `pid` for a program, `csid` for a content standard, `itemId` for an item, `cid` for a committee, `sid` for a session, statistic, or slot as context dictates, `vid` for a variant, verdict, or dossier, `wid` for a field-test window, `rid` for an item response, `bid` for a blueprint, `fid` for a form, `eid` for an equating link, and `gid` for an access grant.

### 2.11. Secure Bank Access Grants

Once items enter the secure bank, day-to-day roles alone do not authorize sensitive operations; the caller must additionally hold a scoped AccessGrant issued by a `SecurityOfficer`. A grant binds a `grantee_user_id` to a `grant_scope` — one of `ITEM_READ`, `ITEM_WRITE`, `STATS_READ`, `FORM_ASSEMBLE`, or `GRANT_ADMIN` — within a program, and is valid over the closed interval from `valid_from` through `valid_until`, where `valid_until` must be strictly later than `valid_from`. A grant counts as active only while its `revoked_at` is unset and the program's `current_period_utc` falls inside its validity interval. An operation that requires a scope the caller does not actively hold is rejected with `ERR_NO_ACTIVE_GRANT` (HTTP 403).

The scopes guard specific capabilities. Mutating an item requires an active `ITEM_WRITE` grant. Reading an individual item whose `security_posture` is `SECURED` requires an active `ITEM_READ` grant, and item list responses silently exclude `SECURED` items from callers who lack `ITEM_READ`. Reading item statistics requires `STATS_READ`. Adding a slot to a form requires `FORM_ASSEMBLE`. Issuing a new grant requires the caller to hold `GRANT_ADMIN`. A `SecurityOfficer` revokes a grant through the revocation capability, which stamps `revoked_at` with the program clock and immediately ends its effect. A new grant whose validity interval would fully overlap an existing active grant for the same grantee and scope is rejected with `ERR_GRANT_OVERLAP` (HTTP 409). Grant collections may be filtered by `program_id`, `grantee_user_id`, and `grant_scope`.

### 2.12. Segregation of Review Duties

Content judgment and bias judgment must come from different people. The same `X-User-ID` may not cast a verdict on the same item in both a `CONTENT` committee session and a `BIAS_SENSITIVITY` committee session within the same revision cycle; an attempt to do so is rejected with `ERR_SOD_REVIEWER_CONFLICT` (HTTP 403). A revision cycle is bounded by the item's returns to `DRAFT`: each bounce back to draft starts a new cycle in which a previously conflicted reviewer may participate again.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program and Its Standards Library

A `ProgramDirector` brings a new assessment program into existence by supplying a `program_code` that uniquely identifies it, a `subject` of `MATH`, `ELA`, `SCIENCE`, or `SOCIAL_STUDIES`, a `grade_level` between grade 3 and grade 12 inclusive, and the `admin_year` of the administration. The new program begins with `status` set to `ACTIVE` — its full status vocabulary is `ACTIVE`, `SUSPENDED`, and `ARCHIVED` — and its logical clock initialized as described in §2.5.

Within a program, the `ProgramDirector` registers the ContentStandards against which items will be aligned. Each standard carries the owning `program_id`, a `standard_code` such as `CCSS.MATH.8.EE.B.5`, the top-level `strand` it belongs to, the full `description` text, and a `depth_of_knowledge` rating from 1 through 4 inclusive. A standard's `status` is `ACTIVE` or `DEPRECATED`, and only an `ACTIVE` standard in the same program may anchor a new item submission. Standard codes are unique within their program: creating a standard whose `standard_code` collides with an existing one in the same program is rejected with `ERR_DUPLICATE_CODE` (HTTP 409). The standards collection may be listed with `program_id` and `strand` filters.

### 3.2. Item Authorship and the Item's Two State Dimensions

An `ItemWriter` authors a new item by providing the owning `program_id`, a vendor-wide unique `item_code`, a `primary_standard_id` naming the item's primary alignment, an optional `secondary_standard_ids` list carrying up to three additional standard alignments (the list may also be omitted or empty), an `item_type` of `MC`, `MS`, `EBSR`, `TE`, or `CR`, the item's `stimulus_html` prompt and its `options_json` payload holding choices, correct keys, and distractor rationales, a `max_score_points` value from 1 through 6 inclusive, and an optional `exposure_cap` that defaults to 3 when not supplied. At creation the server stamps `author_user_id` with the caller's `X-User-ID`, sets `status` to `DRAFT` and `security_posture` to `UNSECURED`, initializes both `content_review_outcome` and `bias_review_outcome` to `PENDING`, and starts `revision_cycle_count`, `field_test_attempt_count`, and `operational_exposure_count` at zero. Item codes are unique within their program, and a colliding `item_code` is rejected with `ERR_DUPLICATE_CODE`.

Every item lives on two parallel state dimensions. The lifecycle `status` walks through `DRAFT`, `SUBMITTED`, `CONTENT_REVIEW`, `BIAS_REVIEW`, `FIELD_TEST_ELIGIBLE`, `FIELD_TESTING`, `STATS_REVIEW`, and `OPERATIONAL`, ending at either `RETIRED` or `REJECTED`. The `security_posture` dimension independently walks `UNSECURED`, `SECURED`, `EXPOSED`, and `COMPROMISED`. A transition on one dimension never changes the other unless the transition's stated effects say so.

While an item remains in `DRAFT`, its author — and only its author — may revise its `stimulus_html`, `options_json`, `max_score_points`, `primary_standard_id`, or `secondary_standard_ids`; each edit increments the item's `version` and refreshes `updated_at`. An edit by anyone other than the recorded `author_user_id` is rejected with `ERR_NOT_ITEM_AUTHOR` (HTTP 403), and an edit attempted once the item has left `DRAFT` is rejected with `ERR_ITEM_NOT_IN_DRAFT` (HTTP 409). Item mutations additionally require an active `ITEM_WRITE` grant under §2.11, failing with `ERR_NO_ACTIVE_GRANT` when the caller lacks one.

Submitting an item moves it from `DRAFT` to `SUBMITTED`, from which the system immediately and automatically promotes it to `CONTENT_REVIEW`. Submission is the author's act and is version-guarded under §2.7: the request must carry `expected_item_version` matching the item's current `version`, or it fails with `ERR_STALE_VERSION`. The submit is rejected with `ERR_ITEM_NOT_IN_DRAFT` when the item is not in `DRAFT`, with `ERR_NOT_ITEM_AUTHOR` when the caller did not author it, and with `ERR_STANDARD_NOT_ACTIVE` (HTTP 409) when its `primary_standard_id` points at a `DEPRECATED` standard or one outside the item's program. A successful submission resets both `content_review_outcome` and `bias_review_outcome` to `PENDING` and increments the item's `version`. An author may also discard a `DRAFT` item outright, moving it to `REJECTED` with `retirement_reason` recorded as `MANUAL`.

The items collection may be filtered by `program_id`, `primary_standard_id`, `status`, `security_posture`, and `include_archived`.

### 3.3. Review Committees, Sessions, and the Quorum Tally

Review work is performed by committees. A `ProgramDirector` constitutes a ReviewCommittee under a program by naming its `committee_kind` — `CONTENT` for content review or `BIAS_SENSITIVITY` for bias and sensitivity review — along with a display `name` and a `quorum_size` between 2 and 7 inclusive, the minimum number of like verdicts required to close an agenda item. A committee's `status` is `ACTIVE` or `DISSOLVED`.

The `ProgramDirector` convenes a ReviewSession under a committee by supplying the `committee_id`, a planned `scheduled_at` start time, and an ordered `agenda_item_ids` list of the items to be heard. The agenda must be non-empty and may hold at most 25 items; violations surface as `ERR_SESSION_NOT_READY` (HTTP 422), checked both at creation and again at opening. The session records its `program_id`, denormalized from its committee for query purposes, and begins `SCHEDULED`; its full status vocabulary is `SCHEDULED`, `OPEN`, `CLOSED`, and `CANCELLED`. Sessions may be listed filtered by `committee_id` or `program_id`.

Opening a session requires it to be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED` otherwise), requires the program clock to have reached `scheduled_at` (a session whose scheduled time is still in the future is rejected with `ERR_SESSION_NOT_READY`), and requires a non-empty agenda (`ERR_EMPTY_AGENDA`, HTTP 422). A successful opening stamps `started_at` from the program clock.

While a session is `OPEN`, reviewers cast ReviewVerdicts against items on its agenda. A `ContentReviewer` casts verdicts in `CONTENT` sessions and a `BiasSensitivityReviewer` in `BIAS_SENSITIVITY` sessions, with the segregation-of-duties rule of §2.12 enforced across the two kinds. Each verdict names the `item_id` being judged — which must be on the session's agenda — and a `verdict` of `ACCEPT`, `REJECT`, or `REVISE`. A `REJECT` or `REVISE` verdict must carry a `rationale` of at least 20 characters; a missing or too-short rationale is rejected with `ERR_RATIONALE_REQUIRED` (HTTP 400), while an `ACCEPT` verdict needs none. The server stamps `reviewer_user_id` from the caller's `X-User-ID` and `submitted_at` from the program clock. Verdicts may be listed filtered by `session_id` or `item_id`.

Closing a session requires it to be `OPEN` (`ERR_SESSION_NOT_OPEN` otherwise), and two agenda-wide gates apply in turn: every item on the agenda must have at least one verdict (`ERR_INCOMPLETE_AGENDA`, HTTP 409), and every item must reach quorum as described below (`ERR_NO_QUORUM_REACHED`, HTTP 409, aborting the entire close). On a successful close, `closed_at` is stamped from the program clock, and the tally is applied to each agenda item.

The quorum tally for each item counts only verdicts cast in the closing session that have not been soft-deleted, producing counts of `ACCEPT`, `REJECT`, and `REVISE` verdicts, and evaluates them in a strict order. If the `ACCEPT` count reaches the committee's `quorum_size`, the outcome is acceptance. Otherwise, if the `REJECT` count reaches quorum and is at least the sum of the `ACCEPT` and `REVISE` counts, the outcome is rejection. Otherwise, if the `REVISE` count reaches quorum, the outcome is revision. A contested rejection — `REJECT` at quorum but falling short of the combined `ACCEPT` and `REVISE` counts — de-escalates to a revision outcome. If none of these conditions holds, no quorum exists for that item and the close itself is rejected with `ERR_NO_QUORUM_REACHED`. Acceptance moves an item out of review toward its next stage, revision bounces it back to `DRAFT`, and rejection terminates it; §3.2's lifecycle and the review-outcome effects below give the exact target states per committee kind.

When a `CONTENT` session closes, each agenda item in `CONTENT_REVIEW` transitions according to the tally: quorum acceptance advances it `CONTENT_REVIEW → BIAS_REVIEW` and marks `content_review_outcome` as `PASSED`; a revision outcome returns it to `DRAFT`, marks `content_review_outcome` as `REVISE`, and increments `revision_cycle_count` — and if a revision would push `revision_cycle_count` beyond 3, the item instead moves to `REJECTED`, its revision chances exhausted; a rejection outcome moves it to `REJECTED`, marks `content_review_outcome` as `FAILED`, records `retirement_reason` as `CONTENT_DEPRECATED`, and rejects all of its non-terminal variants. When a `BIAS_SENSITIVITY` session closes, each agenda item in `BIAS_REVIEW` transitions similarly: quorum acceptance advances it `BIAS_REVIEW → FIELD_TEST_ELIGIBLE`, marks `bias_review_outcome` as `PASSED`, and moves `security_posture` to `SECURED` as the item enters the secure bank; a revision outcome returns it to `DRAFT` with `bias_review_outcome` marked `REVISE` and `revision_cycle_count` incremented; a rejection outcome moves it to `REJECTED` with `bias_review_outcome` marked `FAILED`, `retirement_reason` recorded as `BIAS_CONFIRMED`, and all non-terminal variants rejected.

A `ProgramDirector` may cancel a session instead. A `SCHEDULED` session moves to `CANCELLED` freely — one already in a terminal state is rejected with `ERR_SESSION_NOT_CANCELLABLE` — and cancelling an `OPEN` session additionally soft-deletes every verdict cast in it by setting `soft_deleted`, so those verdicts are excluded from the quorum tally of any subsequent session that hears the same items.

### 3.4. Field Testing and Item Statistics

Field testing is organized into windows. A `ProgramDirector` creates a FieldTestWindow with a `window_label` such as `SPRING-2026-FT1`, an inclusive `start_utc` and `end_utc` bounding the administration, and a `target_sample_size` between 50 and 10,000 inclusive — the minimum number of responses each item needs before its statistics can finalize. The end must be strictly later than the start, or creation fails with `ERR_WINDOW_TIME_INVALID` (HTTP 422). A window's `status` vocabulary is `SCHEDULED`, `OPEN`, and `CLOSED`, and windows may be listed filtered by `program_id`.

Opening a window requires it to be `SCHEDULED` (`ERR_WINDOW_NOT_SCHEDULED` otherwise) and requires the program clock to sit inside the window's bounds — at or after `start_utc` and at or before `end_utc` — with violations rejected as `ERR_WINDOW_TIME_INVALID`.

While a window is `OPEN`, a `Psychometrician` ingests ItemResponses into it. Each response names the `item_id` answered, a pseudonymous `student_anon_id`, the client-supplied `response_timestamp`, the `attempt_duration_seconds` spent on the item (which may not be negative), and the `raw_score` awarded, which must fall between zero and the item's `max_score_points` inclusive. Ingest is refused with `ERR_ITEM_NOT_FIELD_TESTABLE` (HTTP 409) unless the item is in `FIELD_TEST_ELIGIBLE` or `FIELD_TESTING`, and the same error applies when the item already holds a `FINAL` statistic from a different, earlier-closed window of the same program cycle. The bias gate guards the same path: an item still sitting in `BIAS_REVIEW` cannot be field tested until its `bias_review_outcome` is `PASSED` and its posture has moved to `SECURED`, and an attempt to feed responses for such an item is rejected with `ERR_BIAS_GATE_NOT_PASSED` (HTTP 403). The first response an item receives in an open window advances it `FIELD_TEST_ELIGIBLE → FIELD_TESTING` and increments its `field_test_attempt_count`. Responses may be listed filtered by `window_id`, `item_id`, or `excluded`.

A `Psychometrician` may invalidate a response by excluding it, which sets `excluded` to true and removes it from every statistical computation; exclusion is the only mutation a response record ever undergoes.

Closing a window requires it to be `OPEN` (`ERR_WINDOW_NOT_OPEN` otherwise) and requires the program clock to have reached `end_utc` (`ERR_WINDOW_STILL_RUNNING`, HTTP 409). The close drives the entire statistics pipeline. Every item with at least one response in the window moves `FIELD_TESTING → STATS_REVIEW`, and for every item-and-window pair with responses the system computes statistics.

The provisional computation always runs. Over the set of the item's non-excluded responses in the window — with no timestamp filter and no duration filter — `n_responses` counts the set, and the provisional difficulty is the sum of the responses' `raw_score` values divided by the product of `n_responses` and the item's `max_score_points`, rounded to 4 decimal places half-up. The provisional discrimination is the Pearson correlation, over the same response set, between each response's normalized item score — its `raw_score` divided by `max_score_points` — and that student's mean normalized score across all other items they answered in the window; if the set holds fewer than two responses, or every normalized item score is identical, or every student mean is identical, the correlation is undefined and the value is recorded as 0.0000. These results are written to an ItemStatistic row whose `stats_kind` is `PROVISIONAL`, and mirrored onto the item as `p_value_provisional` and `point_biserial_provisional`. A pair with no non-excluded responses gets no row at all.

The final computation runs only when `n_responses` meets or exceeds the window's `target_sample_size`. It recomputes both measures over a stricter set: non-excluded responses whose `response_timestamp` falls within the closed interval from `start_utc` through `end_utc` and whose `attempt_duration_seconds` is at least 30 seconds. The final difficulty and discrimination are written to a second ItemStatistic row whose `stats_kind` is `FINAL`, mirrored onto the item as `p_value_final` and `point_biserial_final`, and the row's `finalized_at` is stamped from the program clock. Because the final filter can exclude responses the provisional set included, the two difficulty values for the same window may legitimately differ.

Writing a `FINAL` row also derives its `pass_flag`. When the final discrimination falls strictly below 0.10, the flag is `FAIL_SEVERE`. Otherwise, when the final discrimination falls strictly below 0.20, or the final difficulty falls strictly below 0.30, or the final difficulty rises strictly above 0.85, the flag is `FAIL_BORDERLINE`. Otherwise the flag is `PASS`. The comparisons are strict at every boundary: a final difficulty of exactly 0.30 satisfies the lower bound, and a final discrimination of exactly 0.20 satisfies its threshold. Statistic rows may be listed filtered by `item_id`, `window_id`, or `stats_kind`, and reading them requires an active `STATS_READ` grant under §2.11.

### 3.5. Operational Approval and the Retirement Paths

A `Psychometrician` promotes an item to operational status only after its statistics pass. Approval requires the item to be in `STATS_REVIEW` (`ERR_ITEM_NOT_IN_STATS_REVIEW` otherwise), requires at least one `FINAL` ItemStatistic row to exist for the item (`ERR_NO_FINAL_STATS`, HTTP 409), and requires the most recent `FINAL` row — most recent by its window's `end_utc` — to carry a `pass_flag` of `PASS` (`ERR_ITEM_STATS_NOT_PASSING`, HTTP 409). Approval moves the item `STATS_REVIEW → OPERATIONAL`, and the item remains `SECURED`.

Retirement terminates the lifecycle from two directions. When the statistics disappoint, a `Psychometrician` retires the item from `STATS_REVIEW` — permitted when its most recent `FINAL` row's `pass_flag` is `FAIL_BORDERLINE` or `FAIL_SEVERE` — recording `retirement_reason` as `STATISTICAL_FAIL`, stamping `retired_at` from the program clock, and dropping `security_posture` to `UNSECURED`. When an operational item must leave service, a `SecurityOfficer` retires it from `OPERATIONAL`; the request fails with `ERR_ITEM_NOT_OPERATIONAL` if the item is not `OPERATIONAL`, and with `ERR_ITEM_ON_ACTIVE_FORM` (HTTP 409) while any slot still references the item on a form in `ASSEMBLED`, `EQUATED`, or `PUBLISHED` status. This path stamps `retired_at`, drops the posture to `UNSECURED`, records `retirement_reason` as `MANUAL` — or as `OVER_EXPOSED` when the item's `operational_exposure_count` has already reached its `exposure_cap` — and rejects all of the item's non-terminal variants. Retirement may also arrive without any human act: the moment an item's `operational_exposure_count` reaches its `exposure_cap` through slot creation, the system retires it automatically with `retirement_reason` `OVER_EXPOSED`, the same timestamp and posture effects, and the same variant cascade. The full `retirement_reason` vocabulary is `STATISTICAL_FAIL`, `BIAS_CONFIRMED`, `OVER_EXPOSED`, `CONTENT_DEPRECATED`, and `MANUAL`, and `retired_at` stays unset until retirement occurs.

### 3.6. Blueprints, Forms, Slots, and Controlled Assembly

Forms are built against blueprints. A `TestAssembler` drafts a TestBlueprint by supplying the owning `program_id`, a `blueprint_code` that is unique within the program (`ERR_DUPLICATE_CODE` on collision), and a `sections` array of one to eight entries, each naming a `strand`, an `item_count`, and the `dok_min` and `dok_max` bounds for that section. The blueprint's `total_items_required` is computed as the sum of the sections' item counts, and it begins in `DRAFT`. A `ProgramDirector` locks a blueprint once its design is settled: locking requires `DRAFT` status (`ERR_BLUEPRINT_NOT_DRAFT` otherwise), at least one section (`ERR_EMPTY_BLUEPRINT`, HTTP 422), and an `item_count` of at least 1 in every section (`ERR_INVALID_SECTION_SIZE`, HTTP 422), and moves the blueprint `DRAFT → LOCKED`. Much later, when every form under a locked blueprint has reached a terminal or `ARCHIVED` state, the `ProgramDirector` may supersede the blueprint (`ERR_BLUEPRINT_NOT_LOCKED` if it is not `LOCKED`; `ERR_FORMS_STILL_ACTIVE`, HTTP 409, while any of its forms remain live), moving it `LOCKED → SUPERSEDED`. Blueprints may be listed filtered by `program_id`.

Under a `LOCKED` blueprint, a `TestAssembler` creates a TestForm with a `form_code` unique within the blueprint (`ERR_DUPLICATE_CODE` on collision) and an `intended_admin_date`; the form denormalizes its `program_id` from the blueprint and begins `ASSEMBLING`. Its status vocabulary is `ASSEMBLING`, `ASSEMBLED`, `EQUATED`, `PUBLISHED`, and `ARCHIVED`.

The assembler then fills the form with FormItemSlots, each naming an `item_id`, a zero-based `section_index` into the blueprint's sections, a one-based `position_in_section`, and an optional `is_anchor` flag that defaults to false and marks the slot as part of an equating anchor set. Slot creation copies the item's `max_score_points` into the slot's `points_possible`, requires an active `FORM_ASSEMBLE` grant under §2.11, and is rejected with `ERR_SLOT_ITEM_INVALID` (HTTP 409) unless the item is `OPERATIONAL` with a `security_posture` of `SECURED` or `EXPOSED` and does not already appear on the same form. Every slot addition and every slot removal increments the parent form's `version`; removal returns no resource payload. Slots may be listed filtered by `form_id`, `item_id`, or `section_index`.

Assembly is the gate that turns a draft form into a real one, and it is version-guarded under §2.7: the request must carry `expected_form_version` equal to the form's current `version`, failing with `ERR_STALE_VERSION` on a mismatch. Assembly then validates, in order, that the form is `ASSEMBLING` (`ERR_FORM_NOT_ASSEMBLING`), that its blueprint is `LOCKED` (`ERR_BLUEPRINT_NOT_LOCKED`), that each section holds exactly its blueprinted number of slots (`ERR_BLUEPRINT_MISMATCH`, HTTP 422), that every slotted item is `OPERATIONAL` (`ERR_SLOT_ITEM_NOT_OPERATIONAL`), that every slotted item's posture is `SECURED` or `EXPOSED` (`ERR_SLOT_ITEM_INSECURE`), and that no item appears twice on the form (`ERR_DUPLICATE_ITEM_ON_FORM`). The depth-of-knowledge balance is then checked per section: the sum of the slotted items' `depth_of_knowledge` ratings — each looked up through the item's `primary_standard_id` to its standard — must lie between the section's `dok_min` and `dok_max` inclusive on both ends, failing with `ERR_DOK_OUT_OF_RANGE` (HTTP 422) when even one section falls outside. Finally, the exposure guard runs: assembly increments each slotted item's `operational_exposure_count` by one, and if any item's resulting count would exceed its `exposure_cap`, the entire assembly rolls back — no status change, no increments, no posture changes — with `ERR_WOULD_OVER_EXPOSE` (HTTP 422).

A successful assembly stamps `assembled_at` from the program clock, moves the form `ASSEMBLING → ASSEMBLED`, increments the form's `version`, adds one to every slotted item's `operational_exposure_count`, and flips every slotted item whose posture was `SECURED` to `EXPOSED` — the first appearance of an item on an assembled form is what exposes it. Exposure accounting is a strict invariant: `operational_exposure_count` equals the number of slots referencing the item across forms in `ASSEMBLED`, `EQUATED`, or `PUBLISHED` status, it is never decremented below zero, and every forced-rework compensation subtracts exactly the count of deleted slots so the metric stays consistent.

Once a form is `ASSEMBLED`, equating advances it as described in §3.7. A `ProgramDirector` publishes an `EQUATED` form — `ERR_FORM_NOT_EQUATED` when it is not `EQUATED` — only when at least one ValidityDossier documenting the form has itself been published (`ERR_NO_PUBLISHED_DOSSIER` otherwise); dossiers still in `DRAFT` or already `SUPERSEDED` do not count. Publishing stamps `published_at` and moves the form `EQUATED → PUBLISHED`. After administration, the `ProgramDirector` archives a `PUBLISHED` form (`ERR_FORM_NOT_PUBLISHED` otherwise), but only once the program clock has advanced strictly more than 90 days past the form's `intended_admin_date` (`ERR_ARCHIVE_TOO_EARLY`, HTTP 409). An archived form leaves the default listings and is queryable only by passing `include_archived` as true; form listings may also be filtered by `blueprint_id`, `program_id`, and `status`.

### 3.7. Equating Across Forms and Compromise Response

A `Psychometrician` links two assembled forms for equating by creating an EquatingLink with the owning `program_id`, the earlier form as `source_form_id`, the later form as `target_form_id`, and an `anchor_item_ids` list naming the common anchor set. Every anchor must appear as a slot flagged `is_anchor` on both the source and the target form, and the set must hold between 3 and 10 items inclusive; violations are rejected with `ERR_ANCHOR_SET_INVALID` (HTTP 422).

The link's scaling coefficients use the mean-and-sigma method. For each anchor item the system takes that item's most recent `FINAL` statistic whose window's `end_utc` is on or before the program clock, once for the source form's window and once for the target form's window, collecting each anchor's `p_value_final` into a source set and a target set. It computes the mean and the population standard deviation of each set. When fewer than two usable anchors exist, or when either set's standard deviation is zero — statistically homogeneous anchors carry no equating signal — creation is rejected with `ERR_ANCHOR_SET_TOO_HOMOGENEOUS` (HTTP 422). Otherwise `scaling_slope` is the target set's standard deviation divided by the source set's, and `scaling_intercept` is the target set's mean minus the slope times the source set's mean, both rounded to 6 decimal places half-up. Creation stamps `equated_at` from the program clock and advances the target form `ASSEMBLED → EQUATED`. Links may be listed filtered by `program_id`, `source_form_id`, or `target_form_id`.

The security posture dimension has its own transition logic. An item enters the bank `UNSECURED`, becomes `SECURED` automatically upon reaching `FIELD_TEST_ELIGIBLE`, and becomes `EXPOSED` automatically when the first form carrying it assembles. A `SecurityOfficer` marks an exposed item as compromised; the mark requires the posture to be `EXPOSED` (`ERR_ITEM_NOT_EXPOSED` otherwise) and the lifecycle status to be `OPERATIONAL`. The compromise cascade is severe: every slot referencing the item on a non-archived form is deleted; each affected form in `ASSEMBLED` or `EQUATED` is forced back into `ASSEMBLING` for rework, and a forced-back `EQUATED` form additionally loses every equating link that targeted it; the remaining slotted items on each reworked form have their `operational_exposure_count` decremented as compensation; and the compromised item's own `operational_exposure_count` is reset to zero. When a `COMPROMISED` item is later retired, its posture returns to `UNSECURED`.

### 3.8. Translation and Accommodation Variants

An `ItemWriter` or a `TranslationSpecialist` derives an ItemVariant from a source item by naming the source `item_id`, a `variant_kind` of `TRANSLATION` or `ACCOMMODATION`, and the variant's own `stimulus_html` and `options_json`. The kind disciplines the remaining fields: a `TRANSLATION` variant must carry a two-letter ISO `language_code` such as `es` or `vi` and must leave `accommodation_code` unset, while an `ACCOMMODATION` variant must carry an `accommodation_code` of `LARGE_PRINT`, `SCREEN_READER`, `BRAILLE`, `READ_ALOUD`, or `EXTENDED_TIME` and must leave `language_code` unset. Supplying the wrong field for the kind — or both fields at once — is rejected with `ERR_VARIANT_KIND_MISMATCH` (HTTP 422). A new variant begins in `DRAFT`.

A `ContentReviewer` adjudicates each variant. Approval requires the variant to be in `DRAFT` (`ERR_VARIANT_NOT_DRAFT` otherwise) and requires its source item to be in `OPERATIONAL`, `FIELD_TESTING`, or `STATS_REVIEW` (`ERR_VARIANT_SOURCE_NOT_READY`, HTTP 409), moving the variant to `APPROVED`. Rejection moves a `DRAFT` variant to `REJECTED`. Variants also follow their source's fate: when the source item becomes `REJECTED` or `RETIRED` — by committee rejection, statistical failure, manual retirement, or over-exposure — every non-terminal variant of that item is rejected automatically. Variants may be listed filtered by `item_id`.

### 3.9. Validity Dossiers and Technical Documentation

Before a form may be published, its evidence base must exist. A `Psychometrician` authors a ValidityDossier for a form by supplying the owning `program_id`, the documented `form_id`, a `dossier_kind` of `TECHNICAL_MANUAL`, `VALIDITY_EVIDENCE`, or `RELIABILITY_REPORT`, and a `content_md` markdown body of at least 200 characters. A dossier whose body is too short, whose kind is not a valid value, or whose form does not exist is rejected with `ERR_DOSSIER_INVALID` (HTTP 422). The dossier begins in `DRAFT`.

Publishing a dossier requires it to be in `DRAFT` (`ERR_DOSSIER_NOT_DRAFT` otherwise) and requires the documented form to have reached a final-ish stage — `ASSEMBLED`, `EQUATED`, or `PUBLISHED` — failing with `ERR_DOSSIER_FORM_NOT_FINAL` (HTTP 409) for a form still `ASSEMBLING` or already `ARCHIVED`. A successful publish stamps `published_at` from the program clock and moves the dossier `DRAFT → PUBLISHED`. When a dossier's contents are replaced by newer evidence, the `Psychometrician` supersedes it — permitted only from `PUBLISHED` (`ERR_DOSSIER_NOT_PUBLISHED` otherwise) — moving it to `SUPERSEDED`, from which it no longer satisfies the form-publication gate of §3.6. Dossiers may be listed filtered by `program_id`, `form_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Slot removal is the sole deletion and returns `204 No Content` with no resource payload. All resources are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/assessment-programs` | Create an assessment program (logical clock initialized) | ProgramDirector |
| GET | `/api/assessment-programs` | List assessment programs | All roles |
| GET | `/api/assessment-programs/{pid}` | Get one assessment program | All roles |
| POST | `/api/assessment-programs/{pid}/clock/advance` | Advance the program logical clock | ProgramDirector |
| POST | `/api/content-standards` | Register a content standard under a program | ProgramDirector |
| GET | `/api/content-standards` | List content standards | All roles |
| GET | `/api/content-standards/{csid}` | Get one content standard | All roles |
| POST | `/api/items` | Create an item in `DRAFT` / `UNSECURED` | ItemWriter |
| GET | `/api/items` | List items (`SECURED` items hidden without `ITEM_READ`) | All roles |
| GET | `/api/items/{itemId}` | Get one item (`SECURED` requires `ITEM_READ`) | All roles |
| PUT | `/api/items/{itemId}` | Edit item content while in `DRAFT` | ItemWriter |
| POST | `/api/items/{itemId}/submit` | Submit an item for review (version-guarded) | ItemWriter |
| POST | `/api/items/{itemId}/discard` | Discard a `DRAFT` item | ItemWriter |
| POST | `/api/items/{itemId}/approve-operational` | Promote a passing item to `OPERATIONAL` | Psychometrician |
| POST | `/api/items/{itemId}/retire` | Retire an item (stats-fail or manual) | Psychometrician, SecurityOfficer |
| POST | `/api/items/{itemId}/mark-compromised` | Mark an exposed item compromised; cascades rework | SecurityOfficer |
| POST | `/api/item-variants` | Create a translation or accommodation variant | TranslationSpecialist, ItemWriter |
| GET | `/api/item-variants` | List item variants | All roles |
| GET | `/api/item-variants/{vid}` | Get one item variant | All roles |
| POST | `/api/item-variants/{vid}/approve` | Approve a `DRAFT` variant | ContentReviewer |
| POST | `/api/item-variants/{vid}/reject` | Reject a `DRAFT` variant | ContentReviewer |
| POST | `/api/review-committees` | Constitute a review committee | ProgramDirector |
| GET | `/api/review-committees` | List review committees | ProgramDirector, ContentReviewer, BiasSensitivityReviewer |
| GET | `/api/review-committees/{cid}` | Get one review committee | ProgramDirector, ContentReviewer, BiasSensitivityReviewer |
| POST | `/api/review-sessions` | Convene a review session with an agenda | ProgramDirector |
| GET | `/api/review-sessions` | List review sessions | ProgramDirector, ContentReviewer, BiasSensitivityReviewer |
| GET | `/api/review-sessions/{sid}` | Get one review session | ProgramDirector, ContentReviewer, BiasSensitivityReviewer |
| POST | `/api/review-sessions/{sid}/open` | Open a `SCHEDULED` session | ProgramDirector |
| POST | `/api/review-sessions/{sid}/close` | Close an `OPEN` session; tally and fire item transitions | ProgramDirector |
| POST | `/api/review-sessions/{sid}/cancel` | Cancel a session; soft-deletes its verdicts | ProgramDirector |
| POST | `/api/review-sessions/{sid}/verdicts` | Cast a verdict on an agenda item | ContentReviewer, BiasSensitivityReviewer |
| GET | `/api/review-verdicts` | List review verdicts | ProgramDirector, ContentReviewer, BiasSensitivityReviewer |
| GET | `/api/review-verdicts/{vid}` | Get one review verdict | ProgramDirector, ContentReviewer, BiasSensitivityReviewer |
| POST | `/api/field-test-windows` | Create a field-test window | ProgramDirector |
| GET | `/api/field-test-windows` | List field-test windows | ProgramDirector, Psychometrician, TestAssembler |
| GET | `/api/field-test-windows/{wid}` | Get one field-test window | ProgramDirector, Psychometrician, TestAssembler |
| POST | `/api/field-test-windows/{wid}/open` | Open a `SCHEDULED` window | ProgramDirector |
| POST | `/api/field-test-windows/{wid}/close` | Close an `OPEN` window; compute statistics | ProgramDirector |
| POST | `/api/field-test-windows/{wid}/responses` | Ingest an item response into an `OPEN` window | Psychometrician |
| GET | `/api/item-responses` | List item responses | ProgramDirector, Psychometrician |
| GET | `/api/item-responses/{rid}` | Get one item response | ProgramDirector, Psychometrician |
| POST | `/api/item-responses/{rid}/exclude` | Exclude a response from statistics | Psychometrician |
| GET | `/api/item-statistics` | List item statistic rows | ProgramDirector, Psychometrician |
| GET | `/api/item-statistics/{sid}` | Get one item statistic row | ProgramDirector, Psychometrician |
| POST | `/api/test-blueprints` | Draft a test blueprint | TestAssembler |
| GET | `/api/test-blueprints` | List test blueprints | ProgramDirector, TestAssembler, Psychometrician |
| GET | `/api/test-blueprints/{bid}` | Get one test blueprint | ProgramDirector, TestAssembler, Psychometrician |
| POST | `/api/test-blueprints/{bid}/lock` | Lock a `DRAFT` blueprint | ProgramDirector |
| POST | `/api/test-blueprints/{bid}/supersede` | Supersede a `LOCKED` blueprint | ProgramDirector |
| POST | `/api/test-forms` | Create a form under a `LOCKED` blueprint | TestAssembler |
| GET | `/api/test-forms` | List test forms | ProgramDirector, TestAssembler, Psychometrician |
| GET | `/api/test-forms/{fid}` | Get one test form | ProgramDirector, TestAssembler, Psychometrician |
| POST | `/api/test-forms/{fid}/assemble` | Assemble a form (version-guarded) | TestAssembler |
| POST | `/api/test-forms/{fid}/publish` | Publish an `EQUATED` form | ProgramDirector |
| POST | `/api/test-forms/{fid}/archive` | Archive a `PUBLISHED` form | ProgramDirector |
| POST | `/api/test-forms/{fid}/slots` | Add a slot to an `ASSEMBLING` form | TestAssembler |
| GET | `/api/form-item-slots` | List form item slots | ProgramDirector, TestAssembler, Psychometrician |
| GET | `/api/form-item-slots/{sid}` | Get one form item slot | ProgramDirector, TestAssembler, Psychometrician |
| DELETE | `/api/form-item-slots/{sid}` | Remove a slot from an `ASSEMBLING` form | TestAssembler |
| POST | `/api/equating-links` | Create an equating link; compute scaling coefficients | Psychometrician |
| GET | `/api/equating-links` | List equating links | ProgramDirector, Psychometrician |
| GET | `/api/equating-links/{eid}` | Get one equating link | ProgramDirector, Psychometrician |
| POST | `/api/access-grants` | Issue a scoped access grant | SecurityOfficer |
| GET | `/api/access-grants` | List access grants | ProgramDirector, SecurityOfficer |
| GET | `/api/access-grants/{gid}` | Get one access grant | ProgramDirector, SecurityOfficer |
| POST | `/api/access-grants/{gid}/revoke` | Revoke an active access grant | SecurityOfficer |
| POST | `/api/validity-dossiers` | Author a validity dossier for a form | Psychometrician |
| GET | `/api/validity-dossiers` | List validity dossiers | ProgramDirector, Psychometrician, TestAssembler |
| GET | `/api/validity-dossiers/{vid}` | Get one validity dossier | ProgramDirector, Psychometrician, TestAssembler |
| POST | `/api/validity-dossiers/{vid}/publish` | Publish a `DRAFT` dossier | Psychometrician |
| POST | `/api/validity-dossiers/{vid}/supersede` | Supersede a `PUBLISHED` dossier | Psychometrician |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_RATIONALE_REQUIRED` | 400 Bad Request |
| `ERR_VARIANT_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ITEM_NOT_IN_DRAFT` | 409 Conflict |
| `ERR_NOT_ITEM_AUTHOR` | 403 Forbidden |
| `ERR_ITEM_NOT_IN_STATS_REVIEW` | 409 Conflict |
| `ERR_ITEM_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_ITEM_NOT_EXPOSED` | 409 Conflict |
| `ERR_ITEM_NOT_FIELD_TESTABLE` | 409 Conflict |
| `ERR_ITEM_ON_ACTIVE_FORM` | 409 Conflict |
| `ERR_SLOT_ITEM_INVALID` | 409 Conflict |
| `ERR_SLOT_ITEM_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_SLOT_ITEM_INSECURE` | 409 Conflict |
| `ERR_DUPLICATE_ITEM_ON_FORM` | 409 Conflict |
| `ERR_SESSION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_SESSION_NOT_OPEN` | 409 Conflict |
| `ERR_SESSION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SESSION_NOT_READY` | 422 Unprocessable Entity |
| `ERR_EMPTY_AGENDA` | 422 Unprocessable Entity |
| `ERR_INCOMPLETE_AGENDA` | 409 Conflict |
| `ERR_NO_QUORUM_REACHED` | 409 Conflict |
| `ERR_SOD_REVIEWER_CONFLICT` | 403 Forbidden |
| `ERR_WINDOW_NOT_SCHEDULED` | 409 Conflict |
| `ERR_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_WINDOW_TIME_INVALID` | 422 Unprocessable Entity |
| `ERR_WINDOW_STILL_RUNNING` | 409 Conflict |
| `ERR_STANDARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_BLUEPRINT_NOT_DRAFT` | 409 Conflict |
| `ERR_BLUEPRINT_NOT_LOCKED` | 409 Conflict |
| `ERR_EMPTY_BLUEPRINT` | 422 Unprocessable Entity |
| `ERR_INVALID_SECTION_SIZE` | 422 Unprocessable Entity |
| `ERR_FORMS_STILL_ACTIVE` | 409 Conflict |
| `ERR_FORM_NOT_ASSEMBLING` | 409 Conflict |
| `ERR_FORM_NOT_EQUATED` | 409 Conflict |
| `ERR_FORM_NOT_PUBLISHED` | 409 Conflict |
| `ERR_BLUEPRINT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DOK_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_WOULD_OVER_EXPOSE` | 422 Unprocessable Entity |
| `ERR_ARCHIVE_TOO_EARLY` | 409 Conflict |
| `ERR_ANCHOR_SET_INVALID` | 422 Unprocessable Entity |
| `ERR_ANCHOR_SET_TOO_HOMOGENEOUS` | 422 Unprocessable Entity |
| `ERR_NO_FINAL_STATS` | 409 Conflict |
| `ERR_ITEM_STATS_NOT_PASSING` | 409 Conflict |
| `ERR_NO_ACTIVE_GRANT` | 403 Forbidden |
| `ERR_GRANT_OVERLAP` | 409 Conflict |
| `ERR_DOSSIER_INVALID` | 422 Unprocessable Entity |
| `ERR_DOSSIER_NOT_DRAFT` | 409 Conflict |
| `ERR_DOSSIER_NOT_PUBLISHED` | 409 Conflict |
| `ERR_DOSSIER_FORM_NOT_FINAL` | 409 Conflict |
| `ERR_NO_PUBLISHED_DOSSIER` | 409 Conflict |
| `ERR_VARIANT_NOT_DRAFT` | 409 Conflict |
| `ERR_VARIANT_SOURCE_NOT_READY` | 409 Conflict |
| `ERR_BIAS_GATE_NOT_PASSED` | 403 Forbidden |

# Construction Submittal & RFI Management API — Product Requirements Document

## 1. Introduction

General-contractor project engineering teams live between two clocks: the design team's review calendar and the procurement calendar of the materials being reviewed. A submittal that comes back "revise and resubmit" three weeks before its long-lead equipment must ship is not a paperwork problem — it is a schedule and cost problem. This document specifies an API that manages that intersection for a construction project: the submittal register generated from specification sections and their procurement lead times, the architect/engineer review cycle with resubmittals, the expediting posture of long-lead items, and the requests for information (RFIs) whose answers can carry cost and schedule consequences.

The system tracks RFIs from opening through routing, answer, clarification reopens, and distribution to affected subcontractors, and it prices cost impacts against an owner change-order contingency ledger with segregated duties between the engineer who prices an impact and the manager who accepts it. Accepted schedule impacts cascade into installation windows, submittal required dates, and long-lead expediting scores. A daily operations scan advances overdue markers, escalation tiers, and subcontractor standing, and owner-facing reports freeze period metrics for the owner representative. The API is the single source of truth for register state, RFI state, contingency balances, and the escalation event log.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request with either header missing or blank, or whose role value is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes six roles:

- `PlatformAdmin` — the platform operator; owns project creation, project settings, and the logical clock.
- `ProjectManager` — the GC project manager; drives project lifecycle transitions, expediting, impact acceptance and waiver, the daily scan, voids, and installation release.
- `ProjectEngineer` — the GC project engineer; builds the submittal register, routes reviews and RFIs, distributes answered RFIs, prices impacts, and publishes owner reports.
- `Reviewer` — a design-team reviewer (architect or engineer); returns submittal revisions and answers RFIs assigned to them.
- `SubcontractorRep` — a subcontractor representative; submits revisions for their own sections, raises RFIs, and acknowledges distributions addressed to their company.
- `OwnerRep` — the owner representative; receives reports and disputes priced impacts.

Identity semantics differ by role. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting Reviewer entity; ownership checks on any resource that references a Reviewer compare the resource's reviewer foreign-key field to `X-User-ID` — concretely, returning a revision requires the header to equal that revision's assigned reviewer, and answering an RFI requires it to equal the RFI's routed reviewer, with a mismatch rejected as `ERR_REVIEWER_NOT_ASSIGNED` (HTTP 403). When `X-User-Role` is `SubcontractorRep`, `X-User-ID` is the `id` of the acting Subcontractor entity; ownership checks compare the resource's subcontractor foreign-key field to `X-User-ID` — concretely, submitting a revision requires the header to equal the governing spec section's responsible subcontractor, and acknowledging a distribution requires it to equal the record's addressed subcontractor, with a mismatch rejected as `ERR_WRONG_SUBCONTRACTOR` (HTTP 403).

When `X-User-Role` is `PlatformAdmin`, `ProjectManager`, `ProjectEngineer`, or `OwnerRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `priced_by_user_id` or `decided_by_user_id` on an ImpactAssessment where a transition writes it — but it does not compare the header to any entity's `id` for those roles.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order; the one exception is a submittal's revision list, which sorts by `revision_number` ascending (see §3.2).

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Twelve of the thirteen primary resources — Project, SpecSection, Subcontractor, Reviewer, Submittal, SubmittalRevision, LongLeadItem, RFI, ImpactAssessment, DistributionRecord, InstallationActivity, and OwnerReport — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including system-driven cascade mutations. For example, a ledger move on an ImpactAssessment bumps the parent Project's `version`, and returning a revision bumps both the revision's and the submittal's `version`.

The thirteenth resource, EscalationEvent, is an append-only log entry and carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and it is never modified after creation.

Calendar-date fields use `YYYY-MM-DD` granularity throughout the API. Every such date stamped by the system (submission dates, routing dates, return dates, answer dates, procurement actuals, event dates) derives from the server's logical clock — specifically its UTC date — as described in §2.11.

### 2.5. The Project Posture Gate

Every Project carries a `posture` that governs what may happen inside it: `SETUP`, `ACTIVE`, `SUSPENDED`, `CLOSEOUT`, or the terminal `CLOSED`. A new project begins in `SETUP`. A `ProjectManager` activates it (`SETUP` → `ACTIVE`), may suspend it (`ACTIVE` → `SUSPENDED`) and later resume it (`SUSPENDED` → `ACTIVE`), begins closeout (`ACTIVE` → `CLOSEOUT`), and finally closes it (`CLOSEOUT` → `CLOSED`). Invoking one of these transitions from any other posture is rejected with `ERR_INVALID_PROJECT_STATE` (HTTP 409); editing project settings is likewise permitted only while the project is in `SETUP` and otherwise fails with `ERR_INVALID_PROJECT_STATE`.

The posture gate is the system's master switch for child mutations. With two carve-outs, every operation that creates or mutates a child resource — submittal date changes, deferral requests and decisions, releases and voids and closes, revision submission, routing, and return, RFI creation, routing, answering, reopening, distribution, and closure, impact pricing, repricing, acceptance, waiver, and dispute, distribution sends and acknowledgements, installation activity creation, release, completion, and cancellation, long-lead advances and manual expedites, owner-report creation and publication, and the daily scan — requires the project to be `ACTIVE` and is otherwise rejected with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409). The first carve-out favors setup work: creating a spec section and activating it (which generates the submittal register) are permitted while the project is in `SETUP` or `ACTIVE`. The second carve-out favors closeout reporting: creating and publishing an owner report are permitted while the project is in `ACTIVE` or `CLOSEOUT`.

### 2.6. Business-Day Calendar Arithmetic

Several deadlines in the system are expressed in business days. A business day is a Monday through Friday whose `YYYY-MM-DD` date does not appear in the project's `holiday_dates` array; holidays and weekends are simply skipped when counting.

Two directions of arithmetic exist. A forward pass advances a number of business days from a base date where the base date itself is day zero and is never counted; this pass computes an RFI's `due_date` from its opened or reopened date over `rfi_response_days`, a revision's `review_due_date` from its `routed_date` over the section's `review_days`, and a distribution record's `ack_due_date` from its `sent_date` over `ack_required_days`. A backward pass steps a number of business days earlier than a base date, again without counting the base date itself; this pass computes a submittal's required approval and submission dates (§3.1). All such dates are calendar dates at `YYYY-MM-DD` granularity with no rounding.

### 2.7. The Contingency Ledger

Each Project carries an owner change-order contingency expressed in whole cents. `initial_contingency_cents` seeds the fund at creation (default zero, never negative). Three computed balances track its disposition: `contingency_reserved_cents` is the sum of `final_delta_cents` over the project's ImpactAssessments currently in `PRICED` or `DISPUTED` status; `contingency_spent_cents` is the sum of `final_delta_cents` over those in `ACCEPTED`; and `contingency_available_cents` is always the seed minus the reserved and spent balances. The ledger obeys a conservation invariant: at all times, the available, reserved, and spent balances sum exactly to the seed. At project creation the reserved and spent balances start at zero and the available balance equals the seed.

The ledger moves only through the ImpactAssessment pricing operations described in §3.6 — price, reprice, accept, and waive — and every such move also bumps the Project's `version` and refreshes its `updated_at`. A separate threshold, `gc_tier_threshold_cents` (default 1000000 cents, i.e. ten thousand dollars; never negative), selects the general-contractor markup tier: whenever the spent balance is at least the threshold, the upper tier applies to new pricing.

### 2.8. Money, Precision, and Rounding

All monetary amounts are integers of whole cents; no fractional cents exist anywhere in the API. Every markup layer in an impact calculation is rounded to whole cents using round-half-up before the next layer is applied (§3.6). Calendar dates carry day granularity. Reported averages are rounded to two decimal places with round-half-up, and the first-pass yield percentage to one decimal place with round-half-up (§3.9). The expediting priority score is an integer, halved with floor division when a deferral discount applies (§3.4).

### 2.9. Optimistic Concurrency Control

Three creation endpoints are optimistic-concurrency guarded against a parent resource's version. In each case the request must carry a field containing the parent version the client last observed; if the parent's current `version` has advanced since that observation, the create is rejected because the client would otherwise overwrite a history it has not seen.

- Creating an RFI (`POST /v1/projects/{projectId}/rfis`) requires `expected_project_version`. Creating a second RFI legitimately mints the next `rfi_number` and advances the project's `version`; a create carrying a previously observed version is therefore stale and is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).
- Creating a submittal revision (`POST /v1/submittals/{submittalId}/revisions`) requires `expected_submittal_version`. A new revision legitimately supersedes a returned predecessor and advances the submittal's `version`; a create carrying a previously observed version is stale and is rejected with `ERR_STALE_SUBMITTAL_VERSION` (HTTP 412).
- Creating an owner report (`POST /v1/projects/{projectId}/owner-reports`) requires `expected_project_version`. A new report whose period overlaps a published report legitimately supersedes it and advances the project's `version`; a create carrying a previously observed version is stale and is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

Endpoints not listed here do not accept a version field at all.

### 2.10. Request Validation Order and Nested Resource Retrieval

Every request is validated in a fixed order, and an earlier failure masks all later checks. First, the identity headers are verified (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the endpoint's authorized roles (`ERR_FORBIDDEN_ROLE`). Third, entity-backed ownership is enforced where the endpoint demands it — `ERR_WRONG_SUBCONTRACTOR` on revision submission and distribution acknowledgement, `ERR_REVIEWER_NOT_ASSIGNED` on revision return and RFI answer. Fourth, existence: every resource identifier in the URL path is validated in left-to-right order, and the request is rejected with the 404 error of the first identifier that does not resolve — `ERR_PROJECT_NOT_FOUND`, `ERR_SPEC_SECTION_NOT_FOUND`, `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, `ERR_REVISION_NOT_FOUND`, `ERR_RFI_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ACTIVITY_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_LONG_LEAD_ITEM_NOT_FOUND`, or `ERR_DISTRIBUTION_NOT_FOUND` — after which identifiers supplied in the request body (`spec_section_id`, `submittal_id`, `reviewer_id`, `subcontractor_id`) must also exist within the same project, failing with the corresponding 404. Fifth, request shape: required fields must be present, types must be correct, enum members must be valid, and array members must be valid and free of duplicates (notably within `required_submittal_kinds`); violations fail with `ERR_INVALID_REQUEST` (HTTP 400).

Sixth, optimistic-concurrency version matching on the three guarded creations (`ERR_STALE_PROJECT_VERSION`, `ERR_STALE_SUBMITTAL_VERSION`, HTTP 412). Seventh, the project posture gate (`ERR_PROJECT_NOT_ACTIVE`). Eighth, the target entity must stand in the from-state of the requested transition, failing with the state-specific 409 error (`ERR_INVALID_PROJECT_STATE`, `ERR_SPEC_SECTION_NOT_DRAFT`, `ERR_SPEC_SECTION_NOT_ACTIVE`, `ERR_SUBMITTAL_NOT_ACCEPTING_REVISIONS`, `ERR_SUBMITTAL_NOT_APPROVED`, `ERR_SUBMITTAL_NOT_DISTRIBUTED`, `ERR_SUBMITTAL_TERMINAL`, `ERR_REVISION_NOT_SUBMITTED`, `ERR_REVISION_NOT_UNDER_REVIEW`, `ERR_RFI_INVALID_STATE`, `ERR_ASSESSMENT_NOT_ESTIMATED`, `ERR_ASSESSMENT_NOT_PRICED`, `ERR_DISTRIBUTION_NOT_QUEUED`, `ERR_DISTRIBUTION_NOT_SENT`, `ERR_ACTIVITY_NOT_PLANNED`, `ERR_ACTIVITY_NOT_RELEASED`, `ERR_REPORT_NOT_DRAFT`, `ERR_DEFERRAL_NOT_PENDING`, or `ERR_LLI_INVALID_ADVANCE`). Ninth, segregation of duties on impact acceptance (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). Tenth, routing and standing constraints — discipline match (`ERR_DISCIPLINE_MISMATCH`), reviewer capacity (`ERR_REVIEWER_AT_CAPACITY`), an empty selector pool (`ERR_NO_ELIGIBLE_REVIEWER`), a suspended subcontractor submitting (`ERR_SUBCONTRACTOR_SUSPENDED`), a repeated distribution (`ERR_ALREADY_DISTRIBUTED`), and an empty distribution target set (`ERR_NO_DISTRIBUTION_TARGETS`). Eleventh, temporal rules — the activity date range (`ERR_INVALID_DATE_RANGE`) and the crew window conflict check (`ERR_CREW_WINDOW_CONFLICT`). Twelfth, the referential release and close gates (`ERR_SUBMITTAL_NOT_RELEASED`, `ERR_OPEN_RFI_BLOCKS_RELEASE`, `ERR_LONG_LEAD_NOT_DELIVERED`, `ERR_OPEN_RFI_BLOCKS_CLOSE`, `ERR_ASSESSMENT_OPEN_ON_CLOSE`, `ERR_REOPEN_BLOCKED_BY_PRICED_ASSESSMENT`, `ERR_CLOSEOUT_BLOCKED`). Thirteenth and last, the fiscal check that a contingency reservation fits the available balance (`ERR_CONTINGENCY_EXHAUSTED`, HTTP 402).

This ordering has observable consequences: an unknown resource id surfaces as a 404 before any state or business rule runs, a stale version surfaces before the posture gate, and a pricing request on an assessment in the wrong state fails with its state error before the contingency balance is ever consulted.

### 2.11. The Logical Clock and the Daily Scan Checkpoint

The server maintains a logical clock rather than consulting wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and until it is explicitly set it continues to read that default — it never falls back to wall-clock time. A `PlatformAdmin` advances it through a test-driving capability (`POST /_clock/set_current_utc`) carrying a `to_iso8601` timestamp. Every `YYYY-MM-DD` value the system stamps derives from this clock's UTC date.

Time-driven behavior — overdue flags, escalation tiers, expediting windows, subcontractor standing — does not move on its own. It advances only through the daily scan, an ops-run checkpoint invoked by a `ProjectManager` while the project is `ACTIVE`. Each successful scan increments the project's `ops_scan_index`, a monotonic counter starting at zero, by exactly one and bumps the Project's `version`. The scan's per-item effects are specified in §3.8.

## 3. Business Logic & Workflows

### 3.1. Project Setup, Posture Lifecycle, and the Submittal Register

A `PlatformAdmin` opens a project by supplying a `project_name`; the project is born in `SETUP` posture. The remaining creation inputs tune the project's calendars and thresholds, and all of them may be adjusted later — but only while the project remains in `SETUP`, and any attempt to edit them after activation fails with `ERR_INVALID_PROJECT_STATE`. The contractual `rfi_response_days` sets the RFI answer window in business days (default ten, at least one). The `ack_required_days` sets how many business days a subcontractor has to acknowledge a distribution (default five, at least one). The `mobilization_buffer_days` sets the required calendar-day gap between two installation windows of the same subcontractor (default two, and zero is permitted). The `long_lead_threshold_days` marks the boundary at which a procurement becomes long-lead (default thirty business days, at least one). The `expedite_window_days` sets how close a required on-site date may loom — in calendar days — before the system begins expediting on its own (default ten, zero permitted). The `holiday_dates` array lists non-working days excluded from business-day math and defaults to empty. `initial_contingency_cents` seeds the owner contingency (default zero) and `gc_tier_threshold_cents` sets the markup tier breakpoint (default 1000000 cents, i.e. ten thousand dollars). An optional `contract_start_date` may be recorded for information; it defaults to null and drives no computation.

With the project underway, a `ProjectManager` walks its posture forward. Activation requires `SETUP`; suspension requires `ACTIVE`; resumption requires `SUSPENDED`; closing requires `CLOSEOUT` — each invoked from the wrong posture fails with `ERR_INVALID_PROJECT_STATE`, and each successful transition bumps the Project's `version`. Beginning closeout is the consequential step: it moves the project from `ACTIVE` to `CLOSEOUT` only when the project is fully drained of open work, and otherwise fails with `ERR_CLOSEOUT_BLOCKED`. The gate demands that every submittal has a `review_status` of `CLOSED` or `VOID` — or, failing that, holds a `deferral_status` of `DEFERRED_APPROVED`; that every RFI is `CLOSED` or `VOID`; that every ImpactAssessment is `ACCEPTED` or `WAIVED`; that every DistributionRecord is `ACKNOWLEDGED`; that every InstallationActivity is `COMPLETED` or `CANCELLED`; and that no OwnerReport remains in `DRAFT`.

While the project is in `SETUP` or `ACTIVE`, a `ProjectEngineer` authors spec sections. Each section carries a `section_number` that must be unique within the project, a `title` (default empty), a procurement `lead_time_days` in business days (default fourteen, zero permitted), a design-team `review_days` window per revision in business days (default ten, at least one), a `required_discipline` of `ARCH`, `STRUCT`, `MEP`, or `CIVIL` (default `ARCH`) that governs reviewer routing, an optional `default_need_date` stamped onto generated submittals (default null), an optional `responsible_subcontractor_id` naming the subcontractor allowed to submit revisions (default null), and a `required_submittal_kinds` array drawn from `PRODUCT_DATA`, `SHOP_DRAWINGS`, `SAMPLES`, `MOCKUP`, `CERTIFICATES`, and `O_AND_M_MANUALS` (default a single `PRODUCT_DATA` entry; duplicate kinds in the array are rejected with `ERR_INVALID_REQUEST`). A section's `status` begins at `DRAFT`, and its attributes may be edited only while `DRAFT` — later edits fail with `ERR_SPEC_SECTION_NOT_DRAFT`.

Activating a section — permitted only from `DRAFT` (otherwise `ERR_SPEC_SECTION_NOT_DRAFT`) and only while the project is in `SETUP` or `ACTIVE` (otherwise `ERR_PROJECT_NOT_ACTIVE`) — generates the submittal register. For each kind in `required_submittal_kinds`, taken in array order, the system creates one Submittal whose `submittal_kind` records that kind and whose `item_number` is the section's `section_number` followed by a hyphen and the kind's one-based index zero-padded to two digits (so a section `03 30 00` requiring two kinds yields `03 30 00-01` and `03 30 00-02`). Each generated submittal starts with `review_status` `REGISTERED`, `expediting_status` `NOT_REQUIRED`, `deferral_status` `NONE`, `revision_count` zero, and a `required_on_site_date` initialized from the section's `default_need_date`. Its required dates derive from a backward business-day pass with a pinned evaluation order: first `required_approval_date` steps back the section's `lead_time_days` business days from the `required_on_site_date` (the on-site date itself is not counted), then `required_submission_date` steps back the section's `review_days` business days from the `required_approval_date` — submission always derives from approval, never the reverse. A generated submittal whose section `lead_time_days` is at least the project's `long_lead_threshold_days` is flagged `is_long_lead`; for each such submittal the system additionally creates exactly one linked LongLeadItem in `IDENTIFIED` status, mirrors the submittal's `required_on_site_date` onto it, computes its `escalation_level` and `priority_score` against the current clock date, and moves the submittal's `expediting_status` to `MONITORING`. Activation bumps the section's `version`.

Locking a section (`ACTIVE` → `LOCKED`, failing with `ERR_SPEC_SECTION_NOT_ACTIVE` from any other status) freezes register generation only; submittals already generated continue their lifecycle undisturbed.

The project roster fills in alongside the register. A `ProjectEngineer` registers each subcontractor with a `company_name`, a free-text `trade` label, and an optional `contact_email` (default empty); a new subcontractor starts with `standing` `GOOD` and a `late_ack_count` of zero. A `ProjectManager` registers each design-team reviewer with a `display_name`, a `discipline` of `ARCH`, `STRUCT`, `MEP`, or `CIVIL`, and an optional `review_capacity` (default three, at least one); a new reviewer starts with `reviewer_status` `ACTIVE` and an `open_review_count` of zero.

### 3.2. The Submittal Review Cycle: Revisions, Routing, and Returns

A submittal accepts a new revision only while its `review_status` is `REGISTERED` or `RETURNED_NEEDS_RESUBMIT`; attempts against a submittal in any other non-terminal state fail with `ERR_SUBMITTAL_NOT_ACCEPTING_REVISIONS`, while attempts against a `VOID` or `CLOSED` submittal fail with `ERR_SUBMITTAL_TERMINAL`. The submission comes from a `SubcontractorRep` carrying a `document_ref`, optional `notes` (default empty), and — because creation is optimistic-concurrency guarded — an `expected_submittal_version` equal to the submittal's current `version`; if another writer has advanced the submittal since the client last read it, the create is rejected with `ERR_STALE_SUBMITTAL_VERSION` (HTTP 412), since a new revision legitimately supersedes a returned predecessor and advances the submittal. The acting representative must be the section's responsible subcontractor — the `X-User-ID` is compared to the section's `responsible_subcontractor_id`, and a mismatch is `ERR_WRONG_SUBCONTRACTOR` — and a subcontractor whose `standing` has fallen to `SUSPENDED` is blocked from submitting new revisions at all with `ERR_SUBCONTRACTOR_SUSPENDED`.

On acceptance the revision takes `revision_number` equal to the submittal's current `revision_count`, which is then incremented by one (so the first revision is number zero). The revision is stamped `SUBMITTED` with `submitted_date` set to the clock date; any prior revision of the same submittal in `RETURNED` status with action code `C` or `D` is moved to `SUPERSEDED` — only `RETURNED` revisions carrying `C` or `D` may be superseded. The submittal's `review_status` moves to `IN_REVIEW`, whether from `REGISTERED` on first submission or from `RETURNED_NEEDS_RESUBMIT` on a resubmittal cycle, and the submittal's `version` bumps. A submittal's revision list is returned ordered by `revision_number` ascending rather than by creation time.

Routing, performed by a `ProjectEngineer` while the project is `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE` otherwise), requires the revision to be `SUBMITTED` (otherwise `ERR_REVISION_NOT_SUBMITTED`). The request may name a `reviewer_id` explicitly or omit it. An explicit reviewer must exist within the project, hold `reviewer_status` `ACTIVE`, match the section's `required_discipline` (a mismatch is `ERR_DISCIPLINE_MISMATCH`), and have an `open_review_count` strictly below their `review_capacity` — a reviewer already at capacity is rejected with `ERR_REVIEWER_AT_CAPACITY`. When `reviewer_id` is omitted, a deterministic selector runs: candidates are the project's reviewers who are `ACTIVE`, whose `discipline` equals the section's `required_discipline`, and whose `open_review_count` is strictly below `review_capacity`; they are ranked by `open_review_count` ascending with `created_at` ascending as the only tie-break (never the id), and the first candidate is selected. An empty candidate set fails with `ERR_NO_ELIGIBLE_REVIEWER`; there is no fallback assignment. Until routing, the revision's `reviewer_id`, `routed_date`, and `review_due_date` are null; routing stamps the revision's `reviewer_id`, sets `routed_date` to the clock date, computes `review_due_date` as the section's `review_days` business days after the routed date (the routed date itself is day zero), increments the reviewer's `open_review_count` by one, and moves the revision to `UNDER_REVIEW`. A reviewer's `review_capacity` defaults to three and must be at least one; a `ProjectManager` may later patch `reviewer_status` (to `INACTIVE`) or `review_capacity`, and deactivating a reviewer does not release reviews they already hold.

Returning a revision belongs to the assigned `Reviewer` alone: the revision must be `UNDER_REVIEW` (otherwise `ERR_REVISION_NOT_UNDER_REVIEW`), and the acting `X-User-ID` must equal the revision's `reviewer_id` (otherwise `ERR_REVIEWER_NOT_ASSIGNED`). The return payload carries an `action_code` — `A` for approved, `B` for approved as noted, `C` for revise and resubmit, `D` for rejected (null until returned) — and optional `comments`, which are stored on the revision as `return_comments` (default empty). The return stamps `returned_date` with the clock date and computes `is_late_return`, which is true when the return lands after the `review_due_date` and false whenever either date is absent. The reviewer's `open_review_count` decrements by one, floored at zero. The return also settles the parent submittal: an `A` or `B` action moves `review_status` from `IN_REVIEW` to `APPROVED`, while a `C` or `D` action moves it to `RETURNED_NEEDS_RESUBMIT`, priming the resubmittal loop; both the revision's and the submittal's `version` increment.

### 3.3. Release for Construction, Distribution, and Submittal Closeout

Once a submittal stands `APPROVED`, a `ProjectEngineer` may release it for construction while the project is `ACTIVE` — a release against a project in any other posture is `ERR_PROJECT_NOT_ACTIVE`, and against a submittal not `APPROVED` is `ERR_SUBMITTAL_NOT_APPROVED`. Release computes the affected-subcontractor set: the section's `responsible_subcontractor_id` if one is set, unioned with the `subcontractor_id` of every InstallationActivity that references this submittal and is not `CANCELLED`. The set is ordered by subcontractor `created_at` ascending, one `QUEUED` DistributionRecord with `source_type` `SUBMITTAL` is created per member, and the set is fixed at release — installation activities created afterward do not retroactively add records. When the affected set is empty, the submittal passes directly to `DISTRIBUTED`, the all-acknowledged condition being vacuously satisfied. Release bumps the submittal's `version`.

Distribution records move `QUEUED` → `SENT` → `ACKNOWLEDGED`. A fresh record is `QUEUED` with `sent_date`, `ack_due_date`, and `acknowledged_date` all null and `is_overdue` false. Sending, by a `ProjectEngineer`, requires `QUEUED` (otherwise `ERR_DISTRIBUTION_NOT_QUEUED`) and stamps `sent_date` with the clock date while computing `ack_due_date` as the project's `ack_required_days` business days later. Acknowledgement belongs to the addressed subcontractor: a `SubcontractorRep` whose `X-User-ID` equals the record's `subcontractor_id` (otherwise `ERR_WRONG_SUBCONTRACTOR`), against a record that is `SENT` (otherwise `ERR_DISTRIBUTION_NOT_SENT`). Acknowledgement stamps `acknowledged_date` and, when the record's `source_type` is `SUBMITTAL` and every sibling record sharing its `source_id` has reached `ACKNOWLEDGED`, advances the parent submittal from `RELEASED` to `DISTRIBUTED`, bumping the submittal's `version`.

A `ProjectEngineer` closes a submittal only from `DISTRIBUTED` (otherwise `ERR_SUBMITTAL_NOT_DISTRIBUTED`), and only while no RFI referencing the submittal remains `OPEN` or `ROUTED` (otherwise `ERR_OPEN_RFI_BLOCKS_CLOSE`). A `ProjectManager` may instead void a submittal — optionally recording a `reason` — but only from `REGISTERED`, `IN_REVIEW`, or `RETURNED_NEEDS_RESUBMIT`: voiding a `CLOSED` or `VOID` submittal fails with `ERR_SUBMITTAL_TERMINAL`, and voiding a `RELEASED` or `DISTRIBUTED` submittal fails with a 409 state-class rejection. Voiding cascades: every revision still `SUBMITTED` or `UNDER_REVIEW` becomes `SUPERSEDED`, with the holding reviewer's `open_review_count` decremented for each `UNDER_REVIEW` revision voided; the linked LongLeadItem, if any exists and is not yet terminal, becomes `CANCELLED`; the submittal's `expediting_status` falls back to `NOT_REQUIRED`; and the submittal's `version` bumps.

Separately, while a submittal's `review_status` is anything other than `CLOSED` or `VOID`, a `ProjectEngineer` may patch its `required_on_site_date`. Doing so recomputes `required_approval_date` and `required_submission_date` through the same pinned backward pass, mirrors the new date onto the linked LongLeadItem — whose `days_late`, `escalation_level`, and `priority_score` recompute in turn — and bumps the submittal's `version`.

### 3.4. Deferrals, Long-Lead Procurement, and Expediting

A submittal that cannot or need not finish review before closeout may be deferred. A `ProjectEngineer` requests a deferral — the request carries a `reason` — only while the submittal's `deferral_status` is `NONE` (otherwise `ERR_DEFERRAL_NOT_PENDING`) and its `review_status` is `REGISTERED` or `RETURNED_NEEDS_RESUBMIT` (a submittal in any other state earns a 409 rejection). The submittal moves to `DEFERRAL_REQUESTED`. A `ProjectManager` then decides: a `decision` of `APPROVE` moves the submittal to `DEFERRED_APPROVED`, while `REJECT` returns it to `NONE`; deciding without a pending request fails with `ERR_DEFERRAL_NOT_PENDING`. Approval has two lasting consequences: a `DEFERRED_APPROVED` submittal is exempt from the begin-closeout gate described in §3.1, and the linked long-lead item's `priority_score` is halved — floor division — on every recompute for as long as the deferral stands approved. Both the request and the decision bump the submittal's `version`.

Each LongLeadItem is the procurement shadow of one long-lead submittal, created one-for-one at register generation. It carries a free-text `description` (default empty) and a `criticality` of `CRITICAL`, `HIGH`, or `STANDARD` (default `STANDARD`), both patchable by a `ProjectEngineer` with an immediate `priority_score` recompute. Its `required_on_site_date` is not an independent input: it mirrors the governing submittal's date and recomputes whenever that date shifts. Procurement advances along a fixed single-file chain — `IDENTIFIED` → `QUOTED` → `PO_ISSUED` → `IN_PRODUCTION` → `SHIPPED` → `DELIVERED` — one step at a time. Each advance names its target as `to_status` and records an `actual_date`; any target that is not exactly the next step is rejected with `ERR_LLI_INVALID_ADVANCE`. Advancing to `QUOTED` stamps `quoted_date`, to `PO_ISSUED` stamps `po_issued_date`, and to `SHIPPED` stamps `shipped_date`, each from the supplied `actual_date`; the `IN_PRODUCTION` step records no date. Advancing to `DELIVERED` stamps `delivered_date`, forces `days_late` and `escalation_level` to zero, recomputes the score, and sets the parent submittal's `expediting_status` to `CLEAR`. Every advance recomputes `priority_score` and bumps the item's `version`. When the parent submittal is voided, a non-terminal item is cancelled outright (`CANCELLED`). Fetching the long-lead item of a submittal returns an array of zero or one element.

Two computed quantities drive expediting attention. `days_late` is zero while the item is `DELIVERED` or the clock date is on or before its `required_on_site_date`; otherwise it is the number of calendar days the clock has passed that date. `escalation_level` tiers on `days_late` with lower-inclusive boundaries: level 0 when nothing is late, level 1 for one to six days late, level 2 for seven to thirteen, and level 3 at fourteen or more — exactly seven days late is level 2, exactly fourteen is level 3. The `priority_score` itself is a weighted sum: three points per calendar day of lateness, counting at most twenty days of lateness; plus criticality points — forty for `CRITICAL`, twenty for `HIGH`, zero for `STANDARD`; plus two points for every calendar day by which the clock date has passed the item's `required_on_site_date`, with no contribution while that date still lies in the future. When the parent submittal's `deferral_status` is `DEFERRED_APPROVED`, the raw total is halved with floor division; the result is then clamped to lie between zero and one hundred inclusive.

The submittal's `expediting_status` rides alongside as a parallel dimension, independent of `review_status`. It is born `NOT_REQUIRED` and moves to `MONITORING` at register generation when the submittal is long-lead. From `MONITORING` it advances to `EXPEDITING` either when the daily scan finds the clock date within `expedite_window_days` calendar days of the `required_on_site_date`, or when a `ProjectManager` manually expedites the long-lead item (which also recomputes its `priority_score` and bumps the item's `version`). From `EXPEDITING` it rises to `ESCALATED` whenever the linked item's `escalation_level` reaches at least 2, and it subsides back to `EXPEDITING` when the level drops below 2 — as happens, for example, when an accepted schedule impact pushes the `required_on_site_date` later. From any of `MONITORING`, `EXPEDITING`, or `ESCALATED`, delivery of the item settles the dimension at `CLEAR`.

### 3.5. The RFI Cycle: Questions, Answers, Reopens, and Distribution

An RFI is raised by a `ProjectEngineer` or a `SubcontractorRep` with a `subject` and a `question_text`. Optional cross-references — a `spec_section_id` and a `submittal_id`, both nullable — tie the question into the register; linking a `VOID` or `CLOSED` submittal is rejected with `ERR_SUBMITTAL_TERMINAL`. A `priority` of `LOW`, `NORMAL`, `HIGH`, or `CRITICAL` (default `NORMAL`) and a `required_discipline` of `ARCH`, `STRUCT`, `MEP`, or `CIVIL` (default `ARCH`) complete the routing profile. Because creation is optimistic-concurrency guarded, the payload must carry `expected_project_version` equal to the project's current `version`; every RFI creation legitimately mints the next `rfi_number` and advances the project, so a create carrying a previously observed version is stale and refused with `ERR_STALE_PROJECT_VERSION` (HTTP 412). When the creator is a `SubcontractorRep`, their `X-User-ID` must identify a subcontractor belonging to the same project. Creation stamps the RFI `OPEN`, assigns `rfi_number` as `RFI-` followed by a one-based per-project sequence zero-padded to four digits (`RFI-0001`, `RFI-0002`, …), records `opened_date` from the clock, computes `due_date` by advancing `rfi_response_days` business days from the opened date with the opened day itself counted as day zero, initializes `cycle_count` to zero and `is_overdue` to false, and bumps the Project's `version`.

Routing moves the RFI from `OPEN` to `ROUTED`. A `ProjectEngineer` routes while the project is `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE` otherwise) and only from `OPEN` (`ERR_RFI_INVALID_STATE` otherwise). The request may name a `reviewer_id`: the named reviewer must hold `reviewer_status` `ACTIVE` and match the RFI's `required_discipline` (a mismatch is `ERR_DISCIPLINE_MISMATCH`). When `reviewer_id` is omitted, the same capacity-aware selector as in §3.2 runs against the RFI's `required_discipline` — `ACTIVE` reviewers of the discipline with `open_review_count` strictly below `review_capacity`, ranked by `open_review_count` then `created_at` — and an empty pool fails with `ERR_NO_ELIGIBLE_REVIEWER`. Until this point the RFI's `routed_reviewer_id`, `routed_date`, and the answer fields are null; routing sets `routed_reviewer_id` and `routed_date` and bumps the RFI's `version`.

Answering belongs to the routed reviewer: the RFI must be `ROUTED` (otherwise `ERR_RFI_INVALID_STATE`), the project must be `ACTIVE`, and the acting `X-User-ID` must equal `routed_reviewer_id` (otherwise `ERR_REVIEWER_NOT_ASSIGNED`). The answer payload carries `answer_text` plus two declarations: `cost_impact_flag` and `schedule_impact_flag`. A true cost flag requires `estimated_cost_cents` to be present, and a true schedule flag requires `estimated_schedule_days` — the calendar days of slip being claimed — to be present; a missing conditionally-required estimate fails with `ERR_INVALID_REQUEST`. The answer stamps `answered_date` and `answered_by_reviewer_id`, and computes `is_late_answer`: an answer recorded on or before the `due_date` is on time — the boundary is inclusive — and a later answer is late. When the cost flag is true, the system immediately creates an ImpactAssessment in `ESTIMATED` status carrying the answer's `estimated_cost_cents` and a `provisional_delta_cents` computed by the provisional pricing variant of §3.6. Answering bumps the RFI's `version` and moves it to `ANSWERED`.

An answered RFI may be reopened for clarification by a `ProjectEngineer`, returning it to `ROUTED` — but not while any ImpactAssessment of this RFI stands in `PRICED` or `DISPUTED`, since those statuses hold a contingency reservation; such a reopen is refused with `ERR_REOPEN_BLOCKED_BY_PRICED_ASSESSMENT`, and the held reservation must first be waived or accepted. Reopening increments `cycle_count`, clears the answer fields (`answer_text`, `answered_date`, `answered_by_reviewer_id`, both impact flags, and `estimated_schedule_days` return to null or false), clears `is_overdue`, recomputes `due_date` from the current clock date over another `rfi_response_days` business days, and bumps the RFI's `version`. If an assessment of this RFI is still sitting in `ESTIMATED`, reopening auto-voids it to `WAIVED`; because no reservation exists while an assessment is `ESTIMATED`, the ledger is untouched. An RFI carries at most one non-terminal assessment at any moment.

Closing an RFI, also by a `ProjectEngineer`, requires `ANSWERED` (otherwise `ERR_RFI_INVALID_STATE`) and is refused with `ERR_ASSESSMENT_OPEN_ON_CLOSE` while any of its assessments remains in `ESTIMATED`, `PRICED`, or `DISPUTED`. A `ProjectManager` may void an RFI — optionally with a `reason` — from `OPEN`, `ROUTED`, or `ANSWERED`; a `CLOSED` or `VOID` RFI rejects the attempt with `ERR_RFI_INVALID_STATE`.

Distribution pushes an answered RFI to the subcontractors it affects; the RFI must be `ANSWERED`, and distributing from any other status fails with `ERR_RFI_INVALID_STATE`. The affected set is the responsible subcontractor of the linked spec section, when one is linked, unioned with the `subcontractor_id` of every non-`CANCELLED` InstallationActivity referencing the RFI's linked submittal. Distributing against an empty set fails with `ERR_NO_DISTRIBUTION_TARGETS`, and distributing an RFI that already has distribution records fails with `ERR_ALREADY_DISTRIBUTED`. Like the release path, distribution creates one `QUEUED` DistributionRecord per affected subcontractor — here with `source_type` `RFI` — ordered by subcontractor `created_at` ascending, and those records then flow through the send and acknowledge cycle of §3.3.

### 3.6. Pricing Impacts Against the Contingency Ledger

An ImpactAssessment is born `ESTIMATED` from an RFI answer that declares cost impact, carrying the source RFI's id as its `rfi_id` together with the answer's `estimated_cost_cents` and a `provisional_delta_cents` computed at once. Its `sub_quote_cents`, `gc_markup_tier`, and `final_delta_cents` stay null until pricing, `priced_by_user_id` and `decided_by_user_id` stay null until someone prices or decides, and `price_cycle` starts at zero.

Both delta variants share a layered markup in which every layer is rounded to whole cents, round-half-up, before the next layer applies. First the base grows by a subcontractor markup of ten percent and rounds; that result grows by the general-contractor markup — five percent in tier 1, seven percent in tier 2 — and rounds; the provisional variant alone then grows by a contingency allowance of fifteen percent and rounds, while the final variant skips the allowance layer entirely; finally the result grows by a two percent bond and rounds to produce the delta. The provisional variant always prices at tier 1 off `estimated_cost_cents`. The final variant prices off `sub_quote_cents` at a tier selected from the ledger: tier 2 when the project's `contingency_spent_cents`, observed before this pricing's reservation is applied, is at least `gc_tier_threshold_cents`, and tier 1 otherwise. Because the provisional variant carries the allowance layer and the final variant does not, the two diverge even for numerically identical bases: a base of 100000 cents yields a provisional delta of 135482 cents but a final tier-1 delta of 117810 cents.

Pricing is a `ProjectEngineer` action that moves an assessment from `ESTIMATED` to `PRICED` on the strength of a firm `sub_quote_cents`. The state check comes first — pricing an assessment that is not `ESTIMATED` fails with `ERR_ASSESSMENT_NOT_ESTIMATED` — and only then does the fiscal check run: the computed `final_delta_cents` must fit within `contingency_available_cents`, otherwise the request fails with `ERR_CONTINGENCY_EXHAUSTED` (HTTP 402). On success the selected `gc_markup_tier` is recorded, `contingency_reserved_cents` grows by `final_delta_cents` (with `contingency_available_cents` recomputed and the Project's `version` bumped), `priced_by_user_id` captures the acting `X-User-ID`, `price_cycle` becomes one, and the assessment's `version` bumps.

Three decisions resolve a `PRICED` assessment, and each requires `PRICED` (otherwise `ERR_ASSESSMENT_NOT_PRICED`). Acceptance is a `ProjectManager` action guarded by segregation of duties: the acting `X-User-ID` must differ from the assessment's `priced_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). Acceptance converts the reservation to spend — `contingency_reserved_cents` falls by `final_delta_cents` while `contingency_spent_cents` rises by the same amount, leaving the available balance unchanged — records `decided_by_user_id`, and bumps both the Project's and the assessment's `version`. Waiver, also a `ProjectManager` action, is the compensating move: it releases the reservation entirely, so `contingency_reserved_cents` falls by `final_delta_cents` and the available balance grows, again recording `decided_by_user_id`. Dispute belongs to the `OwnerRep`: the assessment moves to `DISPUTED`, `decided_by_user_id` is recorded, and — critically — the reservation is held, not released, for the duration of the dispute.

A disputed assessment can be repriced by a `ProjectEngineer` submitting a new `sub_quote_cents`, moving it from `DISPUTED` back to `PRICED`; repricing from any other state fails with the not-priced class of state error (`ERR_ASSESSMENT_NOT_PRICED`). Repricing re-derives the tier from the spent balance observed before the operation, computes a new final delta, and adjusts `contingency_reserved_cents` by the difference between the new and old deltas; when that difference is positive it must fit within `contingency_available_cents` (otherwise `ERR_CONTINGENCY_EXHAUSTED`), while a negative difference simply frees reservation. The `priced_by_user_id` is overwritten with the acting user and `price_cycle` increments by one.

Acceptance additionally fires the schedule cascade whenever the source RFI declared `schedule_impact_flag` with `estimated_schedule_days` d greater than zero and the RFI references a submittal. Every `PLANNED` InstallationActivity whose `submittal_id` matches the RFI's linked submittal shifts later by d calendar days — both `start_date` and `end_date` move, and each activity's `shift_applied_days` accumulates d. The linked submittal's `required_on_site_date` shifts later by the same d calendar days, its `required_approval_date` and `required_submission_date` recompute through the pinned backward pass, and its `version` bumps. The linked LongLeadItem then recomputes `days_late`, `escalation_level`, and `priority_score` against the new date with its own version bump, appending an `LLI_ESCALATION_RAISED` or `LLI_ESCALATION_CLEARED` event when its tier changes, and the submittal's `expediting_status` re-evaluates — an `ESCALATED` submittal whose item drops below escalation level 2 subsides to `EXPEDITING`, per §3.4.

### 3.7. Installation Activities and Crew Window Conflicts

An InstallationActivity schedules a crew against a governing submittal. A `ProjectEngineer` creates one by naming the `submittal_id` whose release will govern the work, the `subcontractor_id` whose crew performs it, a `start_date` that begins the window inclusively, an `end_date` that ends it exclusively, and an optional `description` (default empty). The `end_date` must be strictly later than the `start_date`, failing with `ERR_INVALID_DATE_RANGE` (HTTP 400). New activities are born `PLANNED` with `shift_applied_days` at zero.

Creation already enforces the crew-window conflict rule, and release enforces it again. Installation windows are half-open intervals — the `start_date` counts, the `end_date` does not. A candidate window conflicts with any other activity of the same `subcontractor_id` — excluding `CANCELLED` activities and excluding the candidate itself — when the candidate's start falls before the other window's end extended by the project's `mobilization_buffer_days` calendar days, and the other window's start falls before the candidate's end extended by the same buffer. Put differently, a calendar gap of exactly `mobilization_buffer_days` between two windows is allowed, while any shorter gap conflicts and is rejected with `ERR_CREW_WINDOW_CONFLICT`.

Releasing an activity to work is a `ProjectManager` action with a strict gate order: state first, then temporal, then referential. The project must be `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE`) and the activity must be `PLANNED` (`ERR_ACTIVITY_NOT_PLANNED`). The crew-window conflict check then re-runs against the subcontractor's current committed windows (`ERR_CREW_WINDOW_CONFLICT`). The referential gates follow: the governing submittal's `review_status` must be `RELEASED`, `DISTRIBUTED`, or `CLOSED` (otherwise `ERR_SUBMITTAL_NOT_RELEASED`); no RFI referencing that submittal may be `OPEN` or `ROUTED` (otherwise `ERR_OPEN_RFI_BLOCKS_RELEASE`); and when the governing submittal is long-lead, its linked LongLeadItem must stand at `DELIVERED` (otherwise `ERR_LONG_LEAD_NOT_DELIVERED`). A released activity is marked `COMPLETED` by a `ProjectEngineer` (from anything else, `ERR_ACTIVITY_NOT_RELEASED`), or withdrawn by a `ProjectManager` — cancellation is allowed from `PLANNED` or `RELEASED`, after which the window no longer participates in crew-window conflict checks. Each transition bumps the activity's `version`.

### 3.8. The Daily Scan, Escalation Events, and Subcontractor Standing

All time-driven movement flows through one batch mover: the daily scan, invoked by a `ProjectManager` while the project is `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE` otherwise). A successful scan bumps the Project's `version` and advances `ops_scan_index` by one. Four families of effects run per scan.

First, overdue RFIs: every RFI in `OPEN` or `ROUTED` whose `due_date` has passed relative to the clock date is flagged `is_overdue`, and an `RFI_OVERDUE` escalation event is appended — at most once per RFI per current answer cycle, so a reopened RFI can fire the event again in its new cycle. Second, long-lead recomputation: every LongLeadItem not yet `DELIVERED` or `CANCELLED` recomputes `days_late`, `escalation_level`, and `priority_score` against the clock; an `LLI_ESCALATION_RAISED` or `LLI_ESCALATION_CLEARED` event is appended only when the tier actually changes, and the parent submittal's `expediting_status` re-evaluates per §3.4 — rising from `EXPEDITING` to `ESCALATED` at level 2 or above, subsiding below it. Third, the scan auto-advances expediting: a submittal in `MONITORING` whose `required_on_site_date` now lies within `expedite_window_days` calendar days of the clock date moves to `EXPEDITING`. Fourth, acknowledgement policing: every DistributionRecord still `SENT` whose `ack_due_date` has passed is latched `is_overdue` exactly once, a `DIST_ACK_OVERDUE` event is appended, and the addressed subcontractor's `late_ack_count` increments by one.

`late_ack_count` never decreases, and every increment recomputes the subcontractor's `standing`. At three or more late acknowledgements the standing moves from `GOOD` to `WATCH` and a `SUBCONTRACTOR_WATCH` event is appended; at six or more it falls to `SUSPENDED` with a `SUBCONTRACTOR_SUSPENDED` event. There are no downward transitions. A `SUSPENDED` subcontractor is blocked from submitting new revisions, failing with `ERR_SUBCONTRACTOR_SUSPENDED` as described in §3.2.

Every escalation event is an append-only EscalationEvent record — `id` and `created_at` only, per §2.4 — carrying the `project_id`, an `event_type` of `RFI_OVERDUE`, `LLI_ESCALATION_RAISED`, `LLI_ESCALATION_CLEARED`, `DIST_ACK_OVERDUE`, `SUBCONTRACTOR_WATCH`, or `SUBCONTRACTOR_SUSPENDED`, a polymorphic `source_type` of `RFI`, `LONG_LEAD_ITEM`, `DISTRIBUTION_RECORD`, or `SUBCONTRACTOR` paired with the referenced `source_id`, a human-readable `detail` (for example, the old and new escalation level on a tier change), and the `event_date` taken from the clock.

### 3.9. Owner Reporting

Owner reports package a period for the `OwnerRep`. A `ProjectEngineer` creates one by supplying `period_start` and `period_end` — both inclusive calendar dates, with `period_end` required to fall on or after `period_start` (otherwise `ERR_INVALID_DATE_RANGE`) — and, because creation is optimistic-concurrency guarded, an `expected_project_version` equal to the project's current `version`: a new report whose period overlaps a published report legitimately supersedes it and advances the project, so a create carrying a previously observed version is stale and is refused with `ERR_STALE_PROJECT_VERSION` (HTTP 412). Report creation is one of the closeout carve-outs, permitted while the project is `ACTIVE` or `CLOSEOUT` (`ERR_PROJECT_NOT_ACTIVE` otherwise). The new report is born `DRAFT`, and its creation immediately supersedes any `PUBLISHED` report whose inclusive period interval overlaps its own: the older report moves to `SUPERSEDED` with its `superseded_by_report_id` set to the new report's id. Creation bumps the Project's `version`.

Publishing, by a `ProjectEngineer`, requires `DRAFT` (otherwise `ERR_REPORT_NOT_DRAFT`). At publish the system freezes the report's `snapshot_metrics` — the SNAPSHOT variant of the period metrics, reflecting the database exactly as it stood at publish time and never changing afterward — stamps `published_at` with the clock timestamp, moves the report to `PUBLISHED`, and bumps its `version`. A separate computed read serves the metrics: the `view` parameter selects `published` (the default), which returns the frozen `snapshot_metrics` fields, or `live`, which recomputes the same five metrics from current data and therefore diverges from the snapshot once the underlying entities mutate after publish. Either way the response carries `view`, `open_submittals`, `overdue_rfis`, `avg_rfi_response_days`, `first_pass_yield_pct`, and `open_escalation_events`.

The five metrics are defined as follows. `open_submittals` counts the project's submittals whose `review_status` is neither `CLOSED` nor `VOID`. `overdue_rfis` counts the project's RFIs whose `is_overdue` flag is set. `avg_rfi_response_days` averages the business-day response duration over RFIs in `ANSWERED` or `CLOSED` whose `answered_date` falls within the report period inclusive, where a single RFI's duration counts the business days strictly after its `opened_date` up to and including its `answered_date` — so an answer on the opening day itself counts zero; the mean is rounded half-up to two decimal places, and an empty set reports 0.00. `first_pass_yield_pct` looks at submittals whose revision number zero has a `returned_date` within the period inclusive, and computes one hundred times the count of those returned with `action_code` `A` or `B` divided by the count returned, rounded half-up to one decimal place; an empty set reports 0.0. `open_escalation_events` counts the project's EscalationEvents whose `event_date` falls on or before `period_end`.

## 4. Endpoint Definitions

Operations that create a new resource — a project, spec section, subcontractor, reviewer, revision, RFI, installation activity, or owner report — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`. All request and response bodies follow the envelope of §2.2, and list endpoints paginate per §2.3. Request payloads, side effects, and preconditions for each endpoint are specified in the narratives of §2 and §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/projects` | Create a project in `SETUP` posture | PlatformAdmin |
| GET | `/v1/projects` | List projects | Any |
| GET | `/v1/projects/{projectId}` | Get one project | Any |
| PATCH | `/v1/projects/{projectId}` | Update project settings while `SETUP` | PlatformAdmin |
| POST | `/v1/projects/{projectId}/activate` | Activate a project (`SETUP` → `ACTIVE`) | ProjectManager |
| POST | `/v1/projects/{projectId}/suspend` | Suspend a project (`ACTIVE` → `SUSPENDED`) | ProjectManager |
| POST | `/v1/projects/{projectId}/resume` | Resume a project (`SUSPENDED` → `ACTIVE`) | ProjectManager |
| POST | `/v1/projects/{projectId}/begin-closeout` | Begin closeout (`ACTIVE` → `CLOSEOUT`) behind the open-item gate | ProjectManager |
| POST | `/v1/projects/{projectId}/close` | Close a project (`CLOSEOUT` → `CLOSED`) | ProjectManager |
| POST | `/v1/projects/{projectId}/run-daily-scan` | Run the daily ops scan (overdue flags, escalations, standing) | ProjectManager |
| POST | `/v1/projects/{projectId}/spec-sections` | Create a spec section in `DRAFT` | ProjectEngineer |
| GET | `/v1/projects/{projectId}/spec-sections` | List a project's spec sections | Any |
| GET | `/v1/spec-sections` | Filtered list of spec sections | Any |
| GET | `/v1/spec-sections/{sectionId}` | Get one spec section | Any |
| PATCH | `/v1/spec-sections/{sectionId}` | Edit a spec section while `DRAFT` | ProjectEngineer |
| POST | `/v1/spec-sections/{sectionId}/activate` | Activate a section and generate its submittal register | ProjectEngineer |
| POST | `/v1/spec-sections/{sectionId}/lock` | Lock a section (`ACTIVE` → `LOCKED`) | ProjectEngineer |
| POST | `/v1/projects/{projectId}/subcontractors` | Create a subcontractor | ProjectEngineer |
| GET | `/v1/projects/{projectId}/subcontractors` | List a project's subcontractors | Any |
| GET | `/v1/subcontractors` | Filtered list of subcontractors | Any |
| GET | `/v1/subcontractors/{subcontractorId}` | Get one subcontractor | Any |
| POST | `/v1/projects/{projectId}/reviewers` | Create a design-team reviewer | ProjectManager |
| GET | `/v1/projects/{projectId}/reviewers` | List a project's reviewers | Any |
| GET | `/v1/reviewers` | Filtered list of reviewers | Any |
| GET | `/v1/reviewers/{reviewerId}` | Get one reviewer | Any |
| PATCH | `/v1/reviewers/{reviewerId}` | Update a reviewer's status or capacity | ProjectManager |
| GET | `/v1/projects/{projectId}/submittals` | List a project's submittals | Any |
| GET | `/v1/submittals` | Filtered list of submittals | Any |
| GET | `/v1/submittals/{submittalId}` | Get one submittal | Any |
| PATCH | `/v1/submittals/{submittalId}` | Change a submittal's required on-site date | ProjectEngineer |
| POST | `/v1/submittals/{submittalId}/request-deferral` | Request a deferral for a submittal | ProjectEngineer |
| POST | `/v1/submittals/{submittalId}/decide-deferral` | Approve or reject a requested deferral | ProjectManager |
| POST | `/v1/submittals/{submittalId}/release-for-construction` | Release an approved submittal for construction | ProjectEngineer |
| POST | `/v1/submittals/{submittalId}/void` | Void a submittal | ProjectManager |
| POST | `/v1/submittals/{submittalId}/close` | Close a distributed submittal | ProjectEngineer |
| POST | `/v1/submittals/{submittalId}/revisions` | Submit a revision (OCC on the submittal) | SubcontractorRep |
| GET | `/v1/submittals/{submittalId}/revisions` | List a submittal's revisions by `revision_number` | Any |
| GET | `/v1/revisions` | Filtered list of revisions | Any |
| GET | `/v1/revisions/{revisionId}` | Get one revision | Any |
| POST | `/v1/revisions/{revisionId}/route` | Route a submitted revision to a reviewer | ProjectEngineer |
| POST | `/v1/revisions/{revisionId}/return` | Return a revision with an action code | Reviewer |
| GET | `/v1/projects/{projectId}/long-lead-items` | List a project's long-lead items | Any |
| GET | `/v1/long-lead-items` | Filtered list of long-lead items | Any |
| GET | `/v1/long-lead-items/{itemId}` | Get one long-lead item | Any |
| GET | `/v1/submittals/{submittalId}/long-lead-item` | Get the long-lead item of a submittal (zero or one) | Any |
| PATCH | `/v1/long-lead-items/{itemId}` | Update an item's criticality or description | ProjectEngineer |
| POST | `/v1/long-lead-items/{itemId}/advance` | Advance procurement exactly one step | ProjectEngineer |
| POST | `/v1/long-lead-items/{itemId}/expedite` | Manually expedite the parent submittal | ProjectManager |
| POST | `/v1/projects/{projectId}/rfis` | Create an RFI (OCC on the project) | ProjectEngineer, SubcontractorRep |
| GET | `/v1/projects/{projectId}/rfis` | List a project's RFIs | Any |
| GET | `/v1/rfis` | Filtered list of RFIs | Any |
| GET | `/v1/rfis/{rfiId}` | Get one RFI | Any |
| POST | `/v1/rfis/{rfiId}/route` | Route an open RFI to a reviewer | ProjectEngineer |
| POST | `/v1/rfis/{rfiId}/answer` | Answer a routed RFI | Reviewer |
| POST | `/v1/rfis/{rfiId}/reopen` | Reopen an answered RFI for clarification | ProjectEngineer |
| POST | `/v1/rfis/{rfiId}/distribute` | Distribute an answered RFI to affected subcontractors | ProjectEngineer |
| POST | `/v1/rfis/{rfiId}/close` | Close an answered RFI | ProjectEngineer |
| POST | `/v1/rfis/{rfiId}/void` | Void an RFI | ProjectManager |
| GET | `/v1/projects/{projectId}/impact-assessments` | List a project's impact assessments | Any |
| GET | `/v1/impact-assessments` | Filtered list of impact assessments | Any |
| GET | `/v1/impact-assessments/{assessmentId}` | Get one impact assessment | Any |
| POST | `/v1/impact-assessments/{assessmentId}/price` | Price an estimated assessment | ProjectEngineer |
| POST | `/v1/impact-assessments/{assessmentId}/reprice` | Reprice a disputed assessment | ProjectEngineer |
| POST | `/v1/impact-assessments/{assessmentId}/accept` | Accept a priced assessment | ProjectManager |
| POST | `/v1/impact-assessments/{assessmentId}/waive` | Waive a priced assessment | ProjectManager |
| POST | `/v1/impact-assessments/{assessmentId}/dispute` | Dispute a priced assessment | OwnerRep |
| GET | `/v1/projects/{projectId}/distribution-records` | List a project's distribution records | Any |
| GET | `/v1/distribution-records` | Filtered list of distribution records | Any |
| GET | `/v1/distribution-records/{recordId}` | Get one distribution record | Any |
| POST | `/v1/distribution-records/{recordId}/send` | Send a queued distribution record | ProjectEngineer |
| POST | `/v1/distribution-records/{recordId}/acknowledge` | Acknowledge a sent distribution record | SubcontractorRep |
| POST | `/v1/projects/{projectId}/installation-activities` | Create a planned installation activity | ProjectEngineer |
| GET | `/v1/projects/{projectId}/installation-activities` | List a project's installation activities | Any |
| GET | `/v1/installation-activities` | Filtered list of installation activities | Any |
| GET | `/v1/installation-activities/{activityId}` | Get one installation activity | Any |
| POST | `/v1/installation-activities/{activityId}/release` | Release a planned activity for work | ProjectManager |
| POST | `/v1/installation-activities/{activityId}/complete` | Mark a released activity completed | ProjectEngineer |
| POST | `/v1/installation-activities/{activityId}/cancel` | Cancel a planned or released activity | ProjectManager |
| POST | `/v1/projects/{projectId}/owner-reports` | Create a draft owner report (OCC on the project) | ProjectEngineer |
| GET | `/v1/projects/{projectId}/owner-reports` | List a project's owner reports | Any |
| GET | `/v1/owner-reports` | Filtered list of owner reports | Any |
| GET | `/v1/owner-reports/{reportId}` | Get one owner report | Any |
| POST | `/v1/owner-reports/{reportId}/publish` | Publish a draft report, freezing its metrics | ProjectEngineer |
| GET | `/v1/owner-reports/{reportId}/metrics` | Read a report's metrics (published or live view) | Any |
| GET | `/v1/escalation-events` | Filtered list of escalation events | Any |
| GET | `/v1/escalation-events/{eventId}` | Get one escalation event | Any |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_WRONG_SUBCONTRACTOR` | 403 Forbidden |
| `ERR_REVIEWER_NOT_ASSIGNED` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_SPEC_SECTION_NOT_FOUND` | 404 Not Found |
| `ERR_SUBCONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEWER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMITTAL_NOT_FOUND` | 404 Not Found |
| `ERR_REVISION_NOT_FOUND` | 404 Not Found |
| `ERR_RFI_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ACTIVITY_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_LONG_LEAD_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SUBMITTAL_VERSION` | 412 Precondition Failed |
| `ERR_PROJECT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_PROJECT_STATE` | 409 Conflict |
| `ERR_SPEC_SECTION_NOT_DRAFT` | 409 Conflict |
| `ERR_SPEC_SECTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_SUBMITTAL_NOT_ACCEPTING_REVISIONS` | 409 Conflict |
| `ERR_SUBMITTAL_NOT_APPROVED` | 409 Conflict |
| `ERR_SUBMITTAL_NOT_DISTRIBUTED` | 409 Conflict |
| `ERR_SUBMITTAL_TERMINAL` | 409 Conflict |
| `ERR_REVISION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_REVISION_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_RFI_INVALID_STATE` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_ESTIMATED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_PRICED` | 409 Conflict |
| `ERR_DISTRIBUTION_NOT_QUEUED` | 409 Conflict |
| `ERR_DISTRIBUTION_NOT_SENT` | 409 Conflict |
| `ERR_ACTIVITY_NOT_PLANNED` | 409 Conflict |
| `ERR_ACTIVITY_NOT_RELEASED` | 409 Conflict |
| `ERR_REPORT_NOT_DRAFT` | 409 Conflict |
| `ERR_DEFERRAL_NOT_PENDING` | 409 Conflict |
| `ERR_LLI_INVALID_ADVANCE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_SUBCONTRACTOR_SUSPENDED` | 409 Conflict |
| `ERR_DISCIPLINE_MISMATCH` | 409 Conflict |
| `ERR_REVIEWER_AT_CAPACITY` | 409 Conflict |
| `ERR_NO_ELIGIBLE_REVIEWER` | 409 Conflict |
| `ERR_ALREADY_DISTRIBUTED` | 409 Conflict |
| `ERR_NO_DISTRIBUTION_TARGETS` | 409 Conflict |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SUBMITTAL_NOT_RELEASED` | 409 Conflict |
| `ERR_OPEN_RFI_BLOCKS_RELEASE` | 409 Conflict |
| `ERR_OPEN_RFI_BLOCKS_CLOSE` | 409 Conflict |
| `ERR_LONG_LEAD_NOT_DELIVERED` | 409 Conflict |
| `ERR_CLOSEOUT_BLOCKED` | 409 Conflict |
| `ERR_ASSESSMENT_OPEN_ON_CLOSE` | 409 Conflict |
| `ERR_REOPEN_BLOCKED_BY_PRICED_ASSESSMENT` | 409 Conflict |
| `ERR_CONTINGENCY_EXHAUSTED` | 402 Payment Required |

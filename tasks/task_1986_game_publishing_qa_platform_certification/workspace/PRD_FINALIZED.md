# Game Publishing QA & Platform Certification API — Product Requirements Document

## 1. Introduction

Shipping a game through first-party certification is one of the most expensive and failure-prone phases of publishing. Every platform holder imposes its own technical requirements checklist, its own submission fees, blackout periods during which the certification queue is frozen, and strict resubmission economics when a package is rejected. At the same time, the publisher's QA organization must coordinate external testing vendors against weekly capacity contracts, triage incoming defects against severity-based service levels, prove localization and age-rating readiness, and hold a disciplined line on which build is allowed to become a release candidate. When any of these threads slip, launch dates move and certification budget evaporates.

This document specifies the Game Publishing QA & Platform Certification API, the system of record for that entire process. It governs the title lifecycle from concept through launch to sunset; the planning of test coverage as a platform-by-feature matrix; the onboarding and weekly settlement of external QA vendors; the intake, triage, and regression tracking of bug reports; the assembly, submission, and remediation cycle of platform certification packages with their embedded compliance checklists and waivers; age-rating filings and localization readiness as submission gates; release-window reservation under demand-based pricing; and the post-launch expedited hotfix process with its rolling quota and automatic embargo protection. All resource endpoints are mounted under the `/qa-cert` prefix, with the logical-clock control mounted at the server root.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven acting roles plus one read marker: `ReleaseManager`, `QALead`, `VendorManager`, `CertificationLead`, `PlatformReviewer`, `ComplianceManager`, `PlatformAdmin`, and the marker role `Any` used in this document to indicate read-only endpoints open to every declared role. A request missing either header, or carrying a role string outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When a declared role attempts an operation reserved for a different role — including the per-transition role restrictions on lifecycle endpoints — the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For every role in this system, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. This applies individually to `ReleaseManager`, `QALead`, `VendorManager`, `CertificationLead`, `PlatformReviewer`, `ComplianceManager`, and `PlatformAdmin`: the server may record the identifier where a workflow requires an actor anchor — for example as `submitted_by_user_id` and `decided_by_user_id` on a submission package, or as `waiver_requested_by_user_id` on a checklist item — but it never compares the header value to any entity's `id`. Segregation-of-duties comparisons are made between two recorded `X-User-ID` values, never between a header and a resource identifier.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Operations

The server maintains a logical clock that is the sole time source for every time-dependent rule. Before any call is made, the clock reads exactly 2026-08-01T00:00:00Z — a fixed startup default; it never follows wall-clock time. Submission timestamps, bug-report SLA age evaluation, blackout-interval tests, the hotfix rolling quota, release-window expiry, and the notion of the "current ISO week" for vendor capacity all read this clock.

A `PlatformAdmin`-only capability sets the logical clock to a supplied `to_iso8601` instant, after which all later time-dependent evaluations use the new reading. A second `PlatformAdmin`-only capability performs an ops-run checkpoint sweep over the logical clock: every release window still in `RESERVED` or `CONFIRMED` whose end has passed is moved to `EXPIRED` (a confirmed window forfeits its fee on expiry), and every bug report still `OPEN` past its severity's triage SLA is flagged as breached. The sweep is the only mechanism that applies these two time-driven effects.

### 2.5. Common Resource Properties

Every resource in this system — titles, vendors, test plans, assignments, builds, bug reports, submission packages, compliance checklists, certification findings, age-rating filings, localization packs, release windows, blackout windows, and hotfixes — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (for example, 2026-08-01T09:15:00.123Z) recording when the resource was created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp in the same format, refreshed on any change to the resource's properties.
- **`version` (integer):** A system-managed integer that starts at 1 on creation and increments with every modification to the resource, including mutations driven by system cascades. It anchors the optimistic concurrency rules of §2.6.

This timestamp format is the house format for every instant the API serializes, not only `created_at` and `updated_at`: fields stamped from the logical clock by a workflow — `submitted_at` on a submission package (§3.5), `filed_at` on an age-rating filing (§3.8), and `expedited_cert_entered_at` on a hotfix (§3.9) — are rendered in the same ISO 8601 UTC format with three fractional digits, and caller-supplied instants echoed back on release windows and blackout windows (`start_utc`, `end_utc`) are likewise re-serialized in that format.

### 2.6. Optimistic Concurrency Control

Exactly two write operations in this API carry an optimistic concurrency contract; no other endpoint accepts a version field.

First, assembling a new submission package for a title requires the request to carry `expected_title_version`, the caller's last-observed `version` of the title. If the title's current `version` no longer matches — because another writer advanced it since the client last read the title, for example by completing a superseding package assembly — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rule exists because assembling a package legitimately supersedes any existing `ASSEMBLING` sibling for the same title and platform, and a supersede decision made against a stale view of the title must not be allowed to land.

Second, requesting a waiver for a checklist item requires the request to carry `expected_checklist_version`, the caller's last-observed `version` of the compliance checklist. A mismatch with the checklist's current `version` — the checklist has been mutated by item verifications or by a superseding waiver since the caller read it — is rejected with `ERR_STALE_VERSION` (HTTP 412). A waiver request legitimately supersedes an existing pending waiver on the same item, discarding the old justification, so the same stale-view protection applies.

### 2.7. Certification Budgets and Monetary Precision

Every game title carries a certification budget expressed in integer cents. The budget is partitioned into three funds: `cert_budget_escrow_cents` holds fees provisionally committed — the sum of `fee_cents` over the title's submission packages currently in `SUBMITTED` or `IN_REVIEW`; `cert_budget_spent_cents` accumulates irrevocable charges — decided package fees (whether the package was approved or rejected), age-rating fees charged at filing, release-window fees charged at confirmation, and expedited hotfix certification fees charged when a hotfix enters expedited review; and `cert_budget_available_cents` is what remains. The three partitions are defined so that available equals `cert_budget_total_cents` minus escrow minus spent, and the conserved invariant is that available, escrow, and spent always sum exactly to `cert_budget_total_cents`. A withdrawal refunds escrow to available in full; a review decision converts escrow to spent one-for-one; neither operation leaks cents.

All monetary values in the system are integer cents. Where a calculation produces a fractional cent, it is rounded half-up to whole cents at the step the relevant workflow specifies — no calculation ever rounds twice at the same step, and percentage coverage figures are the only values stored with two decimal places (also rounded half-up). A charge that would exceed `cert_budget_available_cents` at the moment it is evaluated is rejected with `ERR_CERT_BUDGET_EXCEEDED` (HTTP 402). Budget sufficiency is always the last gate evaluated, after every structural and referential check has passed.

### 2.8. Validation Cascade and Priority Ordering

When several rules could reject the same request, the server evaluates checks in a fixed order so that the surfaced error is deterministic. The order is:

1. **Authentication context.** The `X-User-ID` and `X-User-Role` headers are present and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization.** The role is permitted for this endpoint and, on transition endpoints, for this specific action — otherwise `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Existence.** Path identifiers are validated left to right, then body foreign-key references (vendor, plan, build, regression target), then resolution of an embedded plan entry by feature area — otherwise `ERR_NOT_FOUND` or `ERR_ENTRY_NOT_FOUND` (both HTTP 404).
4. **Optimistic concurrency.** Immediately after existence and before all business rules, the version fields of §2.6 are compared — otherwise `ERR_STALE_VERSION` (HTTP 412).
5. **State legality.** The target entity is in a legal from-state for the requested transition — otherwise `ERR_INVALID_STATE` (or `ERR_PACKAGE_NOT_ASSEMBLING` for package submission).
6. **Embargo safety.** The title is not under a compliance embargo for the two operations the embargo gates — otherwise `ERR_TITLE_UNDER_EMBARGO` (HTTP 403).
7. **Temporal rules.** Buffered blackout exclusion at submission, release-window start strictly in the future, the S1 rolling hotfix quota, and finding fix-build recency — otherwise `ERR_SUBMISSION_BLACKOUT_ACTIVE`, `ERR_WINDOW_IN_PAST` (HTTP 400), `ERR_HOTFIX_QUOTA_EXCEEDED`, or `ERR_FINDING_BUILD_NOT_NEWER` (HTTP 422).
8. **Cross-entity referential consistency.** The referenced build belongs to the title and targets the right platform, a regression target is closed, and a consumed week starts on a Monday — otherwise `ERR_BUILD_TITLE_MISMATCH`, `ERR_BUILD_PLATFORM_MISMATCH`, `ERR_REGRESSION_TARGET_NOT_CLOSED`, or `ERR_WEEK_START_NOT_MONDAY` (all HTTP 422).
9. **Structural business gates.** Checklist completeness, open blockers, open category-A findings, age-rating grant, localization lock, plan coverage, build qualification, uniqueness rules, waiver rules, window overlap, coverage thresholds — the HTTP 409 conflict family catalogued in §5, plus `ERR_NA_NOT_ALLOWED_FOR_REQUIRED` (HTTP 400) for not-applicable results on required items.
10. **Money and capacity, always last.** The certification budget covers the fee being charged — `ERR_CERT_BUDGET_EXCEEDED` (HTTP 402) — and the vendor's weekly capacity covers a new reservation — `ERR_VENDOR_CAPACITY_EXCEEDED` (HTTP 409).

Malformed requests — a missing required field, an unknown enum value, a wrong-typed value, an out-of-range scalar, or a window whose end is not strictly after its start — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) at the point the malformation is detected.

### 2.9. Interval Semantics: Half-Open Windows and Buffered Blackouts

Two different interval regimes coexist in this system, and confusing them is a classic source of certification failures.

Release windows use **half-open** semantics: a window occupies the span from its `start_utc` inclusive to its `end_utc` exclusive. Two windows on the same platform conflict only when each starts strictly before the other ends; windows that merely touch — the existing window's end exactly equals the new window's start, or vice versa — do not conflict. Only windows in `RESERVED` or `CONFIRMED` participate in overlap detection; expired, released, and consumed windows never block anything, and no buffer is applied to release windows. A colliding reservation is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409).

Certification blackout windows use **closed-interval-with-buffer** semantics, deliberately stricter. A blackout declares a closed interval from `start_utc` to `end_utc` — both ends inclusive — and a `buffer_hours` cooling margin applied on both sides. A package submission at logical time *t* is blocked whenever *t* is no earlier than the blackout's start minus its buffer and no later than its end plus its buffer; a submission exactly at the buffered boundary instant is still blocked, and only one second past it is allowed. A blocked submission is rejected with `ERR_SUBMISSION_BLACKOUT_ACTIVE`.

### 2.10. Cascading State Propagation and Hierarchical Consistency

The system maintains alignment between related resources through automatic cascades; operators never edit a child into consistency by hand. Three cascades exist. The **blocker cascade** fires when a blocker-severity bug enters the open set against a candidate build: the build is demoted out of candidacy, every in-flight submission package referencing it is withdrawn by the system, and the title's launch windows are released. The **vendor-termination cascade** fires when a vendor is terminated: its live assignments are cancelled, the freed hours are released, and any approved test plan whose required coverage collapses is demoted back to draft. The **rollback embargo cascade** fires when a title's second hotfix rolls back: the title is automatically embargoed, which in turn gates new submissions and new hotfixes. Each cascade mutates every resource it touches, refreshing `updated_at` and incrementing `version` on each. Conversely, when the condition that forced a system state clears — for example when every package referencing a locked test plan reaches a terminal state — the system restores the prior state on its own.

### 2.11. Nested Resource Retrieval

The API enforces strict left-to-right validation on every request that addresses a nested resource. When a path contains more than one identifier — for example a submission package created beneath a title — the server confirms the parent identifier first and rejects immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not resolve to an existing resource, before examining anything to its right. Body-supplied references are checked only after the path has fully resolved. Path parameters throughout the API are named after their resource: `{titleId}`, `{vendorId}`, `{planId}`, `{assignmentId}`, `{buildId}`, `{bugId}`, `{packageId}`, `{checklistId}`, `{findingId}`, `{filingId}`, `{packId}`, `{windowId}`, and `{hotfixId}`.

## 3. Business Logic & Workflows

### 3.1. Title Onboarding and the Release Lifecycle

Everything begins with the **game title**. A `ReleaseManager` registers a title with a unique `title_code` (a publisher-assigned code such as AURORA-7), a display `name`, the set of `platform_codes` it targets — a non-empty subset of `PS5`, `XSX`, `SWITCH2`, and `PC` — a `target_launch_date` expressed as an ISO 8601 date, and a `cert_budget_total_cents` that may be zero but never negative. A new title starts in `CONCEPT` with `embargoed` false, `embargo_reason` null, `hotfix_rollback_count` zero, and `version` 1. The title list can be filtered by `title_code` and by `status`.

From there the `ReleaseManager` walks the title down a strictly linear release track: `CONCEPT` → `IN_DEVELOPMENT` → `CERTIFICATION` → `CERT_APPROVED` → `LAUNCHED` → `SUNSET`, the only terminal state. Each step requires the title to sit in exactly the preceding state, otherwise `ERR_INVALID_STATE`. Two steps carry business gates. Promotion from `CERTIFICATION` to `CERT_APPROVED` requires that at least one of the title's submission packages has reached `APPROVED`; without one the transition is rejected with `ERR_NO_APPROVED_PACKAGE`. Promotion from `CERT_APPROVED` to `LAUNCHED` requires the title's `open_blocker_count` — the number of its own bug reports with severity `BLOCKER` sitting in `OPEN`, `TRIAGED`, `IN_PROGRESS`, or `REOPENED` — to be zero; otherwise `ERR_OPEN_BLOCKERS_EXIST`.

The compliance **embargo** is an orthogonal flag rather than a status. A `ComplianceManager` sets or clears it through the embargo capability, supplying `embargoed` and a `reason`; whatever reason the last embargo action recorded is preserved on `embargo_reason`. The flag is also written automatically by the rollback cascade of §3.9. While a title is embargoed, two operations are forbidden: submitting a submission package and declaring a hotfix — both are rejected with `ERR_TITLE_UNDER_EMBARGO` (HTTP 403).

### 3.2. Test Plans and the Feature Coverage Matrix

A `QALead` plans certification work as a **test plan**: a platform-by-feature matrix for one title. Creating a plan names the `title_id` and the `platform_code`; at most one non-archived plan may exist for a given title and platform, and a conflicting create is rejected with `ERR_DUPLICATE_TEST_PLAN`. A new plan starts in `DRAFT`. The plan list supports filtering by `title_id`, `platform_code`, and `status`.

While the plan is `DRAFT`, the `QALead` appends feature-matrix rows to its `entries` collection one at a time; appending to a plan in any other state is rejected with `ERR_PLAN_NOT_DRAFT`. Each entry carries a `feature_area` — unique within the plan, with duplicates rejected as `ERR_DUPLICATE_FEATURE_AREA` — a `platform_layer` describing which platform layer the feature exercises, an `is_cert_blocker` flag marking entries that gate approval, and a `required_coverage_hours` budget. The system derives two further values per entry: `assigned_hours`, the sum of `reserved_hours` over the assignments keyed to that plan and feature area whose status is `SCHEDULED`, `IN_PROGRESS`, or `DONE` — a cancelled assignment stops counting toward coverage, while a completed one keeps counting even though it no longer consumes vendor capacity — and `coverage_status`, which reads `COVERED` when assigned hours reach the required coverage, `PARTIAL` when some hours are assigned but fewer than required, and `UNCOVERED` when nothing is assigned. On the plan itself, `required_entries_total` counts the entries flagged as cert blockers and `covered_required_count` counts how many of those are currently `COVERED`.

The plan lifecycle is a review loop with system-driven lock transitions. A `QALead` sends `DRAFT` → `IN_REVIEW`, which requires at least one entry (`ERR_NO_PLAN_ENTRIES`). Approval moves `IN_REVIEW` → `APPROVED` and is granted only when every cert-blocker entry is `COVERED` — otherwise `ERR_REQUIRED_COVERAGE_MISSING`. A reviewer send-back moves `IN_REVIEW` → `DRAFT`, and a plan can be shelved from either `DRAFT` or `IN_REVIEW` into the terminal `ARCHIVED` state. Once a submission package references the plan, the system locks it — `APPROVED` → `LOCKED` — making it read-only: no entries can be added and no new assignments may reference it. When every submission package referencing the plan reaches `APPROVED`, `WITHDRAWN`, `SUPERSEDED`, or `CLOSED`, the system unlocks it — `LOCKED` → `APPROVED`. Finally, coverage loss is also system-driven: if a cancellation drops a cert-blocker entry below `COVERED` on an `APPROVED` plan, the plan is demoted `APPROVED` → `DRAFT` as part of the cancellation cascade.

### 3.3. Vendor Engagements, Weekly Capacity, and Invoice Settlement

External QA capacity is contracted through **vendors**. A `VendorManager` onboards a vendor with a unique legal `name`, a `weekly_capacity_hours` contract between 1 and 10000 tester-hours per ISO week, and a `cost_rate_cents_per_hour` billing rate of at least one cent. Vendors start `ACTIVE` and may move `ACTIVE` → `SUSPENDED` and back again freely; either state may move to the terminal `TERMINATED`. The vendor list can be filtered by `status`.

Each vendor exposes a live view of the current week: `committed_hours_current_week` is the sum of `reserved_hours` over the vendor's assignments whose `week_start_date` is the Monday of the logical clock's current ISO week and whose status is `SCHEDULED` or `IN_PROGRESS`; `available_hours_current_week` is the contracted capacity minus that commitment. The weekly ledger obeys a conservation invariant — committed plus available always equals `weekly_capacity_hours` — across every forward action (reserving hours) and every compensating action (cancellation, completion, or the termination cascade). A vendor's `escapes_count` is the number of bug reports attributed to that vendor via `found_by_vendor_id` that were found post-launch and are not in `DUPLICATE` or `WONT_FIX`; it feeds the settlement clawback below.

Work is reserved as **assignments**. A `VendorManager` creates one by naming the `vendor_id`, the `plan_id`, the `feature_area`, the `week_start_date`, and the `reserved_hours` (an integer from 1 to 168). Creation enforces, in cascade order: the vendor exists and is `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`); the plan exists and is neither `LOCKED` nor `ARCHIVED` (`ERR_INVALID_STATE`); the feature area resolves to an embedded entry of that plan (`ERR_ENTRY_NOT_FOUND`); the consumed week starts on a Monday (`ERR_WEEK_START_NOT_MONDAY`); and — as the fiscal-last check — the reservation does not push the week's committed total above `weekly_capacity_hours` (`ERR_VENDOR_CAPACITY_EXCEEDED`, HTTP 409), where a reservation landing exactly at the cap is allowed. A new assignment starts `SCHEDULED` and immediately consumes weekly capacity; the plan list of assignments can be filtered by `vendor_id`, `plan_id`, `week_start_date`, and `status`.

The `VendorManager` then drives `SCHEDULED` → `IN_PROGRESS` → `DONE`. The `actual_hours` field stays null until completion; completing an assignment requires the reported `actual_hours` — a non-negative integer, its absence or invalidity rejected as `ERR_INVALID_REQUEST` — which is recorded on the assignment. Completion frees the weekly reservation (a `DONE` assignment stops consuming capacity) while the hours continue to count toward plan-entry coverage. Cancelling from `SCHEDULED` or `IN_PROGRESS` moves the assignment to `CANCELLED`, releases its `reserved_hours` from the vendor's weekly commitment, and recomputes entry coverage; if the plan was `APPROVED` and a cert-blocker entry falls below `COVERED` as a result, the plan demotes to `DRAFT`. Terminating a vendor fires the same cancellation cascade across every one of its `SCHEDULED` or `IN_PROGRESS` assignments automatically.

Settlement is a computed read: the vendor invoice, requested with an optional `week_start_date` (defaulting to the Monday of the logical clock's current ISO week) and an optional `variant` (defaulting to `FINAL`), returns `week_start_date`, `variant`, `line_count`, `subtotal_cents`, `clawback_cents`, and `total_cents`. The two variants price identical underlying data differently whenever any completed assignment's actual hours differ from its reservation or any escape exists.

- Under `PROVISIONAL` — the as-billed estimate — the invoice includes the vendor's assignments for the requested week in `SCHEDULED`, `IN_PROGRESS`, or `DONE`. Each line bills the `reserved_hours` at the vendor's rate as an exact integer product; the subtotal is the sum of lines, the clawback is zero, and the total equals the subtotal.
- Under `FINAL` — the settlement reading — only `DONE` assignments for the week are included. Each line is computed in two parts with per-line rounding, then summed: the regular hours are the lesser of `actual_hours` and `reserved_hours`, billed at the rate and rounded half-up to whole cents; the overtime hours are the amount by which `actual_hours` exceeds `reserved_hours` (zero when it does not), billed at one and a half times the rate and itself rounded half-up to whole cents. Summing first and rounding once is a rejected alternative — rounding happens per line, then the per-line values are summed into the subtotal. The escape count is the number of bug reports with `found_by_vendor_id` equal to this vendor, `found_post_launch` true, a status other than `DUPLICATE` or `WONT_FIX`, and a creation time no later than the logical clock at evaluation. The clawback percentage is ten percent per escape, capped at fifty percent. The `clawback_cents` is the subtotal times that percentage divided by one hundred, rounded half-up to whole cents in a second rounding performed after the summation; the `total_cents` is the subtotal minus the clawback.

### 3.4. Builds, Bug Intake, Triage, and Regression Tracking

A `QALead` registers each **build** against a title and platform, giving a `version_string` that must be unique for that title-and-platform pair (`ERR_DUPLICATE_BUILD_VERSION`) and an optional `patch_class` of `BASE`, `DAY_ONE_PATCH`, or `HOTFIX` that defaults to `BASE`. Builds start `RECEIVED`. The build list filters by `title_id`, `platform_code`, and `status`.

The build lifecycle is a test loop with a guarded candidacy gate. A `QALead` moves `RECEIVED` → `IN_TEST`, and a failed build can re-enter testing — `TEST_FAILED` → `IN_TEST` is the retest loop. From `IN_TEST` the build goes to `TEST_PASSED` or back to `TEST_FAILED`. Promotion `TEST_PASSED` → `CANDIDATE` is allowed only when no bug report on this build carries severity `BLOCKER` in `OPEN`, `TRIAGED`, `IN_PROGRESS`, or `REOPENED` — otherwise `ERR_OPEN_BLOCKERS_EXIST`. From candidacy, four exits exist: the system moves `CANDIDATE` → `CONSUMED` when a submission package referencing the build is approved; a `QALead` may retire a candidate — `CANDIDATE` → `RETIRED`; a `QALead` may also manually send a candidate back into testing — `CANDIDATE` → `IN_TEST`, legal only from `CANDIDATE` (`ERR_INVALID_STATE` otherwise); and the blocker cascade demotes `CANDIDATE` → `IN_TEST` automatically. Retirement, manual send-back, and automatic demotion all fire the same downstream cascade described below.

**Bug intake** is also the `QALead`'s responsibility. A report names the `title_id`, the `build_id` it was found on — the build must belong to that title (`ERR_BUILD_TITLE_MISMATCH`) — a `severity` of `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, or `TRIVIAL`, and a `category` of `GAMEPLAY`, `AUDIO`, `GRAPHICS`, `NETWORK`, `COMPLIANCE`, `LOCALIZATION`, or `PERFORMANCE`. Optional fields attribute the find and link regressions: `found_by_vendor_id` records the vendor that found it and defaults to null for internal finds, `found_post_launch` marks defects discovered after the title launched and defaults to false, and `regression_of_id` — also null when omitted — links the report to an earlier bug of the same title that is `RESOLVED`, `VERIFIED`, or `CLOSED` at creation; a target in any other state is rejected with `ERR_REGRESSION_TARGET_NOT_CLOSED`. The computed `is_regression` flag is true exactly when a regression link is present. New reports start `OPEN` with `sla_breached` false and `reopened_count` zero, and the title's `open_blocker_count` is recomputed. The bug list filters by `title_id`, `build_id`, `severity`, `status`, `found_by_vendor_id`, and `regression_of_id`.

Triage moves `OPEN` → `TRIAGED` and replaces the severity with the triage value (optionally re-categorizing via `category`). From `TRIAGED` — and from `REOPENED`, since a reopened bug re-enters the work stream — work advances to `IN_PROGRESS`, then `RESOLVED`, then `VERIFIED`, and finally the terminal `CLOSED`. A bug in `RESOLVED` or `VERIFIED` can be reopened: the transition increments `reopened_count`, applies an optional severity re-triage first — the effective severity is the payload's `severity` when present, otherwise the current one — and recomputes the title's blocker count. Two terminal dispositions exist short of a fix: `TRIAGED` or `IN_PROGRESS` may move to `WONT_FIX`, and `TRIAGED` may move to `DUPLICATE`; both require a `resolution` note (`ERR_INVALID_REQUEST` when absent), and both recompute the blocker count.

The **blocker cascade** is the system's guard against certifying a compromised candidate. Whenever a blocker enters the open set against a `CANDIDATE` build — created with severity `BLOCKER`, triaged up to `BLOCKER`, or reopened with an effective severity of `BLOCKER` — hop one demotes the build `CANDIDATE` → `IN_TEST`. Hop two then withdraws every submission package referencing that build that sits in `ASSEMBLING`, `SUBMITTED`, or `IN_REVIEW`: each moves to `WITHDRAWN` with `withdrawn_cause` recorded as `SYSTEM_BUILD_INVALIDATED`, and each withdrawn package that had a fee in escrow moves that fee from the title's escrow back to available. Hop three, which fires only for these system-caused withdrawals, releases the title's launch windows: every `LAUNCH`-kind release window of the same title and platform in `RESERVED` or `CONFIRMED` moves to `RELEASED`, and a confirmed window's fee is not refunded.

Separately from transitions, the ops-run checkpoint of §2.4 applies the triage SLA. Only bugs still `OPEN` are examined; each severity carries a triage allowance — 24 hours for `BLOCKER`, 72 for `CRITICAL`, 168 for `MAJOR`, and 720 for `MINOR`, while `TRIVIAL` carries no SLA and never breaches. A bug breaches when the logical clock reads strictly later than its `created_at` plus the allowance; a bug sitting exactly at that boundary instant has not breached. Breaching sets `sla_breached` true, and the flag is sticky — no later transition unsets it.

### 3.5. Assembling and Submitting the Certification Package

The **submission package** is the unit of platform certification. A `CertificationLead` assembles one beneath a title, supplying the `platform_code`, the `build_id`, the `test_plan_id`, an optional `expedited` flag defaulting to false, and the OCC field `expected_title_version` described in §2.6. Assembly enforces: the title is `IN_DEVELOPMENT` or `CERTIFICATION` (`ERR_INVALID_STATE`); the platform is one of the title's `platform_codes` (`ERR_INVALID_REQUEST`); the build belongs to the title (`ERR_BUILD_TITLE_MISMATCH`), targets the same platform (`ERR_BUILD_PLATFORM_MISMATCH`), and is currently `CANDIDATE` (`ERR_BUILD_NOT_CANDIDATE`); and the test plan matches the title and platform and is `APPROVED` or `LOCKED` (`ERR_INVALID_STATE`).

Assembly has five side effects. The new package starts `ASSEMBLING` with its `round` computed as one plus the count of prior non-superseded packages for the same title and platform; the count is evaluated over the packages that exist before this assembly's own supersession side effect runs, so a prior `ASSEMBLING` sibling that this very assembly is about to supersede is still counted — a second package assembled over a still-`ASSEMBLING` sibling therefore starts at `round` 2. A compliance checklist is seeded automatically from the platform's requirements catalog (§3.6) and its identifier is recorded on the package as `checklist_id`; the checklist is retrievable by listing checklists with the `submission_package_id` query parameter. Any prior `ASSEMBLING` package for the same title and platform is moved to `SUPERSEDED` — and that system supersession, like every system terminal transition, runs the plan-unlock check. The referenced test plan moves `APPROVED` → `LOCKED` (or remains `LOCKED`). The title's `version` increments by one — the mutation that stale `expected_title_version` values are measured against. Both readiness readings, `readiness_optimistic_pct` and `readiness_strict_pct`, are computed over the seeded checklist. The package list filters by `title_id`, `platform_code`, `build_id`, `test_plan_id`, and `status`.

**Submission** — the `CertificationLead` moving `ASSEMBLING` → `SUBMITTED` — is the most heavily gated operation in the system. The package must be `ASSEMBLING` (submitting from anywhere else is `ERR_PACKAGE_NOT_ASSEMBLING`). The title must not be embargoed (`ERR_TITLE_UNDER_EMBARGO`). The submit instant, read from the logical clock, must fall outside every buffered blackout interval for the platform per §2.9 (`ERR_SUBMISSION_BLACKOUT_ACTIVE`). Every checklist item must be in `PASSED`, `WAIVED`, or `NA` (`ERR_CHECKLIST_INCOMPLETE`). The title's `open_blocker_count` must be zero (`ERR_OPEN_BLOCKERS_EXIST`). No rejected package for the same title and platform may still carry a `CATEGORY_A` finding in `OPEN` or `FIXED_IN_BUILD` (`ERR_OPEN_CATEGORY_A_FINDINGS`). An age-rating filing for the territory mapped from the package's platform must be `GRANTED` (`ERR_AGE_RATING_NOT_GRANTED`). Every localization pack of the title flagged `is_required` must be `LOCKED` on the translation axis and `SIGNED` on the signoff axis (`ERR_LOCALIZATION_NOT_LOCKED`). And finally — money last — `cert_budget_available_cents` must cover the fee computed at this moment (`ERR_CERT_BUDGET_EXCEEDED`).

The submission fee is computed from the package's platform, round, expedite flag, and the logical clock's UTC weekday. The base fee is 120000 cents for `PS5`, 120000 for `XSX`, 90000 for `SWITCH2`, and 60000 for `PC`. The base is multiplied by a round factor — 1.00 on round one, 0.50 on round two, and 0.25 on round three and every later round — then by an expedite factor of 1.75 when `expedited` is true (1.00 otherwise), then by a weekend factor of 1.20 when the submit instant falls on a Saturday or Sunday in UTC (1.00 otherwise). The product is rounded half-up to whole cents exactly once, after all multipliers have been applied, and the charged `fee_cents` is the lesser of that rounded product and the platform cap — 250000 cents for `PS5`, 250000 for `XSX`, 200000 for `SWITCH2`, and 150000 for `PC`. On a successful submit, `fee_cents` is recorded (it is null until then), `submitted_at` — likewise null until this moment — is stamped from the logical clock, `submitted_by_user_id` is recorded from the request header, and the fee moves into the title's escrow partition. The `decided_by_user_id` and `withdrawn_cause` fields remain null until a review decision and a withdrawal respectively set them.

Review is the platform holder's turn. A `PlatformReviewer` moves `SUBMITTED` → `IN_REVIEW` to begin, then decides: `IN_REVIEW` → `APPROVED` or `IN_REVIEW` → `REJECTED`. Segregation of duties binds the decision — the deciding `X-User-ID` must differ from `submitted_by_user_id`, otherwise `ERR_SELF_CERT_DECISION` (HTTP 403) — and the decider is recorded as `decided_by_user_id`. Either decision converts the escrowed fee to spent one-for-one; the platform holder keeps rejected-review fees. Approval additionally consumes the referenced build (`CANDIDATE` → `CONSUMED`) and runs the plan-unlock check. Rejection leaves the plan `LOCKED` — remediation continues on the same plan — and findings may be filed while the package is `IN_REVIEW` or `REJECTED`.

Withdrawal has two shapes. A `CertificationLead` may withdraw manually from `SUBMITTED` or `IN_REVIEW` (any other state is `ERR_INVALID_STATE`), or abandon an `ASSEMBLING` package; both record `withdrawn_cause` as `MANUAL`, and a package withdrawn after submission receives a full refund — its fee moves from escrow back to available — while an abandoned assembly never had escrow and refunds nothing. The system withdraws packages through the blocker cascade with `withdrawn_cause` `SYSTEM_BUILD_INVALIDATED`, and only that system cause additionally releases the title's `RESERVED` or `CONFIRMED` `LAUNCH` windows. Every withdrawal — manual or system, from any state — runs the plan-unlock check: when no other non-terminal package references the test plan, the plan returns `LOCKED` → `APPROVED`.

### 3.6. Compliance Checklist Verification and the Waiver Protocol

Every submission package owns exactly one **compliance checklist**, whose `items` array is seeded at assembly from the platform's fixed requirements catalog. For `PS5` the catalog seeds four items: `TRC-PS-01` (`REQUIRED`, auto-verifiable), `TRC-PS-02` (`REQUIRED`, manual), `TRC-PS-03` (`REQUIRED`, manual), and `TRC-PS-04` (`RECOMMENDED`, manual). For `XSX` three items: `XR-XB-01` (`REQUIRED`, auto-verifiable), `XR-XB-02` (`REQUIRED`, manual), and `XR-XB-03` (`RECOMMENDED`, manual). For `SWITCH2` two items: `LOT-NS-01` (`REQUIRED`, manual) and `LOT-NS-02` (`REQUIRED`, manual). For `PC` two items: `ST-PC-01` (`REQUIRED`, auto-verifiable) and `ST-PC-02` (`RECOMMENDED`, manual). Every item starts `UNVERIFIED` with `waiver_status` `NONE`, and each item records its `requirement_code`, its `severity` (`REQUIRED` or `RECOMMENDED`), its `auto_verifiable` flag, its verification `status`, its `waiver_status`, and — once a waiver exists — a `waiver_justification` and the `waiver_requested_by_user_id`. The checklist copies `platform_code` from its owning package and maintains live counters: `total_items`, `passed_count`, `waived_count`, `na_count`, `failed_count`, and `unverified_count`.

A `ComplianceManager` records verification results item by item, identifying the item by `requirement_code` and supplying a `result` of `PASSED`, `FAILED`, or `NA`. Item edits are only possible while the owning package is `ASSEMBLING` — attempts after submission are rejected with `ERR_CHECKLIST_NOT_EDITABLE`. The item must currently be `UNVERIFIED` or `FAILED`; anything else is `ERR_INVALID_STATE`. Per the cascade of §2.8, the item's from-state check is a level-5 state-legality rule while the editability freeze is a level-9 structural gate, so when both would reject the same verification call — an item already in `PASSED`, `WAIVED`, or `NA` on a package that has left `ASSEMBLING` — the surfaced error is `ERR_INVALID_STATE`; `ERR_CHECKLIST_NOT_EDITABLE` surfaces only when the item's from-state is legal. A result of `NA` is accepted only for `RECOMMENDED` items — marking a `REQUIRED` item not-applicable is rejected with `ERR_NA_NOT_ALLOWED_FOR_REQUIRED` (HTTP 400). Re-verifying a `FAILED` item to `PASSED` has an extra effect: if the item had a `PENDING` waiver, that waiver is voided to `SUPERSEDED`. Every item edit recomputes the checklist counters and the owning package's readiness fields, and increments the checklist's `version`.

The package carries two readiness readings over its checklist, both rounded half-up to two decimal places. The strict reading, `readiness_strict_pct`, is one hundred times the number of items in `PASSED`, `WAIVED`, or `NA`, divided by the total item count — the compliance-final reading enforced at submission. The optimistic reading, `readiness_optimistic_pct`, additionally counts `UNVERIFIED` items whose `auto_verifiable` flag is true as if they had passed — the planning reading used during assembly. The catalog always seeds at least one item per platform, so the divisor is never zero.

When a requirement genuinely cannot be met, a `CertificationLead` requests a **waiver** for a `FAILED` item, supplying its `requirement_code`, a `justification`, and the OCC field `expected_checklist_version` of §2.6. Requesting a waiver for an item in any state other than `FAILED` is rejected with `ERR_WAIVER_REQUIRES_FAILED_ITEM`. The request supersedes: any existing `PENDING` waiver on the item moves to `SUPERSEDED` and its justification is discarded, then the item's `waiver_status` becomes `PENDING` with the new justification and `waiver_requested_by_user_id` recorded from the request header, and the checklist's `version` increments.

The decision belongs to a `ComplianceManager`, who supplies the `requirement_code` and a `decision` of `APPROVED` or `REJECTED`. The decision requires the item's `waiver_status` to be `PENDING` (`ERR_WAIVER_NOT_PENDING`), and segregation of duties binds here too: the decider's `X-User-ID` must differ from `waiver_requested_by_user_id` (`ERR_SELF_WAIVER_DECISION`, HTTP 403). Approving moves the item to `WAIVED` with `waiver_status` `APPROVED`; rejecting leaves the item `FAILED` with `waiver_status` `REJECTED`. Either decision recomputes counters and readiness and increments the checklist `version`.

### 3.7. Certification Findings and the Remediation Cycle

During review the `PlatformReviewer` files **certification findings** on the package — each with a `severity` of `CATEGORY_A` (cert-blocking) or `CATEGORY_B` (advisory), the violated `requirement_code`, and a free-text `description`. Findings may only be filed while the package is `IN_REVIEW` or `REJECTED`; any other state is rejected with `ERR_PACKAGE_NOT_REVIEWABLE`. A new finding starts `OPEN` with `reopen_count` zero and `fixed_in_build_id` null. The findings list filters by `submission_package_id`, `status`, `severity`, and `fixed_in_build_id`.

Remediation is a cross-instance cycle. A `CertificationLead` marks an `OPEN` finding fixed in a specific build by supplying its `build_id`: the build must belong to the package's title (`ERR_BUILD_TITLE_MISMATCH`), target the package's platform (`ERR_BUILD_PLATFORM_MISMATCH`), have been created strictly after the rejected package's build (`ERR_FINDING_BUILD_NOT_NEWER`, HTTP 422), and be `TEST_PASSED` or `CANDIDATE` (`ERR_FIX_BUILD_NOT_QUALIFIED`). Success moves the finding to `FIXED_IN_BUILD` with `fixed_in_build_id` recorded. The `PlatformReviewer` then verifies, supplying a `passed` outcome: when `passed` is true the finding moves `FIXED_IN_BUILD` → `VERIFIED`, and when that was the owning package's last non-verified finding — with at least one finding existing — the system closes the package `REJECTED` → `CLOSED`. When `passed` is false, verification failure reopens the finding `FIXED_IN_BUILD` → `OPEN`, increments `reopen_count`, and clears `fixed_in_build_id`.

The remediation cycle spans package instances. Because a rejected round's `CATEGORY_A` findings gate the next round's submission (`ERR_OPEN_CATEGORY_A_FINDINGS` in §3.5), the publisher must carry every cert-blocking finding through fix and verification before resubmitting; each new package for the same title and platform increments `round`, and the round drives the resubmission fee tier of §3.5 — second rounds bill at half the base fee, third and later rounds at a quarter. `CATEGORY_B` findings are advisory and gate nothing.

### 3.8. Age-Rating Filings and Localization Readiness

Two independent readiness tracks feed the submission gate. The first is the **age-rating filing**. A `ReleaseManager` creates a filing naming the `title_id`, a `territory` of `ESRB`, `PEGI`, `CERO`, or `USK`, and a non-empty `content_descriptors` list. At most one `DRAFT` or `FILED` filing may exist per title and territory (`ERR_DUPLICATE_FILING`), and a new filing starts `DRAFT` with `fee_cents` and `filed_at` null. The filings list filters by `title_id`, `territory`, and `status`.

Filing moves `DRAFT` → `FILED` and is performed by the `ReleaseManager`; it requires the title to be in any state other than `SUNSET` (`ERR_INVALID_STATE`) and the budget to cover the fee being charged (`ERR_CERT_BUDGET_EXCEEDED`). The fee starts from a territory base — 40000 cents for `ESRB`, 25000 for `PEGI`, 18000 for `CERO`, and 15000 for `USK` — with a bundle discount of ten percent when the title already has at least two other filings in `FILED` or `GRANTED` at the instant of filing; the discount count is taken on the pre-filing state, and the charged `fee_cents` is the base times one minus the discount, rounded half-up to whole cents. The fee charges directly to the title's spent partition and `filed_at` is stamped from the logical clock. The `PlatformReviewer` then decides `FILED` → `GRANTED` or `FILED` → `CHALLENGED`. A challenged filing can be amended — `CHALLENGED` → `DRAFT` by the `ReleaseManager` with a fresh, non-empty `content_descriptors` (`ERR_INVALID_REQUEST` when absent or empty); the amendment replaces the descriptors and resets `fee_cents` to null, so re-filing charges a fresh fee with the bundle discount recomputed at that time. The submission gate maps each platform to its rating territory: `PS5` and `XSX` file under `ESRB`, `SWITCH2` under `CERO`, and `PC` under `USK`.

The second track is the **localization pack**. A `ReleaseManager` creates a pack per locale, naming the `title_id`, a BCP-47 `locale` tag (unique per title — duplicates are `ERR_DUPLICATE_LOCALE`), an `is_required` flag marking locales that gate submission, and the asset totals `text_asset_total` and `audio_asset_total` (each zero or greater). A pack starts with `translation_status` `DRAFT` and `signoff_status` `UNSIGNED`, both translated counts at zero. The pack list filters by `title_id` and `translation_status`.

Localization progress runs on **two independent axes**. Every transition request names an `axis` selector — `TRANSLATION` or `SIGNOFF` — together with the target status. On the translation axis, the `ReleaseManager` walks `DRAFT` → `TRANSLATING` → `LQA` → `LOCKED`, with a fail-back `LQA` → `TRANSLATING` when linguistic QA rejects the work; each translation-axis call may carry updated `translated_text_assets` and `translated_audio_assets` counts, which are applied before any gate is evaluated. Locking requires coverage: after applying the call's counts, `text_coverage_pct` must be at least 98.00 and `audio_coverage_pct` at least 95.00, otherwise the transition is rejected with `ERR_COVERAGE_BELOW_LOCK_THRESHOLD`. Coverage is computed as one hundred times the translated count divided by the corresponding total, rounded half-up to two decimal places — and reads exactly 100.00 whenever the corresponding asset total is zero. On the signoff axis, a `QALead` moves `UNSIGNED` → `SIGNED`. The axes evolve independently — signoff does not require the pack to be `LOCKED`, and locking does not require signoff; only the package submission gate of §3.5 couples them, demanding `LOCKED` and `SIGNED` on every required pack.

### 3.9. Release Windows, Hotfix Deployment, and Post-Launch Incident Response

Launch logistics are scheduled as **release windows**. A `ReleaseManager` reserves a window naming the `title_id`, the `platform_code`, a `kind` of `LAUNCH`, `DAY_ONE_PATCH`, or `HOTFIX_DEPLOY`, and the half-open span `start_utc` to `end_utc`. The start must be strictly after the logical clock at creation (`ERR_WINDOW_IN_PAST`, HTTP 400), the end must be strictly after the start (`ERR_INVALID_REQUEST`), and the half-open overlap rule of §2.9 applies against the platform's other `RESERVED` and `CONFIRMED` windows (`ERR_WINDOW_OVERLAP`). A new window starts `RESERVED` with `fee_cents` null. The windows list filters by `title_id`, `platform_code`, `kind`, and `status`.

Confirming a window — `RESERVED` → `CONFIRMED` — carries both a title-state gate and a demand-priced fee. `LAUNCH` and `DAY_ONE_PATCH` windows confirm only for a `CERT_APPROVED` title (`ERR_TITLE_NOT_CERT_APPROVED`); `HOTFIX_DEPLOY` windows confirm only for a `LAUNCHED` title (`ERR_TITLE_NOT_LAUNCHED`). The fee is computed in a pinned order: the window's own length in whole hours is taken first (inputs are whole-hour instants); the ISO week containing the window's start — the span from a Monday 00:00:00Z to the next Monday 00:00:00Z — is identified; every other window on the same platform in `RESERVED` or `CONFIRMED` whose start falls in that week contributes its whole-hour length; the new window's own length is added, so the demand tier keys on the total including the window itself. Below 40 total hours the tier is LOW with multiplier 1.00; from 40 up to but not including 100 hours the tier is MEDIUM with multiplier 1.25; at 100 hours or more the tier is HIGH with multiplier 1.50. The charged `fee_cents` is the window's own whole-hour length times 5000 cents per hour times the tier multiplier, rounded half-up to whole cents, and the budget must cover it (`ERR_CERT_BUDGET_EXCEEDED`); the fee charges directly to the title's spent partition.

Consumption, release, and expiry close the window lifecycle. A `ReleaseManager` consumes a `CONFIRMED` window once the logical clock has reached its `start_utc` (earlier attempts are `ERR_INVALID_STATE`); a deploying hotfix consumes its covering window automatically. A window in `RESERVED` or `CONFIRMED` may be released manually, and releasing a `CONFIRMED` window forfeits its fee with no refund; the system release that accompanies a package's auto-withdrawal (§3.4, §3.5) also forfeits confirmed fees. The ops-run checkpoint expires any `RESERVED` or `CONFIRMED` window whose end has passed, moving it to `EXPIRED` — confirmed windows forfeit their fee on expiry as well. `CONSUMED`, `RELEASED`, and `EXPIRED` are all terminal.

Platform freeze periods are declared as **certification blackout windows** by a `PlatformAdmin`, with the `platform_code`, a closed `start_utc`-to-`end_utc` interval (the end may equal the start but never precede it), a `buffer_hours` margin from 0 to 168 applied on both sides, and a `reason`. Blackouts gate submissions per the buffered-exclusion rule of §2.9; a blackout may be removed by deletion, and the blackout list filters by `platform_code`.

Once a title is `LAUNCHED`, incidents are handled as **hotfixes**. A `ReleaseManager` declares one for a launched, non-embargoed title — `ERR_TITLE_NOT_LAUNCHED` when the title has not launched, `ERR_TITLE_UNDER_EMBARGO` while an embargo is active — naming the `platform_code`, the fixing `build_id` (which must belong to the title, `ERR_BUILD_TITLE_MISMATCH`, and match the platform, `ERR_BUILD_PLATFORM_MISMATCH`), a `severity` of `S1` (outage-class, consuming expedited quota) or `S2` (contained), and an `incident_summary`. A new hotfix starts `DECLARED` with `fee_cents` and `expedited_cert_entered_at` null. The hotfix list filters by `title_id`, `status`, and `build_id`.

The `ReleaseManager` drives `DECLARED` → `IN_DEV` → `READY_FOR_CERT`; entering readiness requires the fixing build to be `TEST_PASSED` or `CANDIDATE` (`ERR_FIX_BUILD_NOT_QUALIFIED`). Expedited certification — `READY_FOR_CERT` → `EXPEDITED_CERT` — belongs to the `PlatformReviewer` and carries three gates. For `S1` hotfixes, the rolling quota counts the title's `S1` hotfixes whose `expedited_cert_entered_at` falls within the rolling thirty-day window — half-open, so an entry exactly thirty days old is excluded while the most recent instant is included — and when that count is already two the transition is rejected with `ERR_HOTFIX_QUOTA_EXCEEDED`; `S2` hotfixes never count and are never blocked. A `CONFIRMED` `HOTFIX_DEPLOY` window for the title and platform must cover the current logical time — its start at or before now and its end strictly after now — otherwise `ERR_NO_HOTFIX_WINDOW`. And the budget must cover the flat expedited fee of 50000 cents (`ERR_CERT_BUDGET_EXCEEDED`). Success charges that fee directly to the title's spent partition and stamps `expedited_cert_entered_at` from the logical clock — the quota's anchor. Deployment — `EXPEDITED_CERT` → `DEPLOYED` by the `ReleaseManager` — consumes the covering window. Rolling back — `DEPLOYED` → `ROLLED_BACK` — increments the title's `hotfix_rollback_count`, and when that count reaches two the system sets `embargoed` true with `embargo_reason` `AUTO_ROLLBACK_THRESHOLD`, the contagion gate on future submissions and hotfixes described in §3.1.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — lifecycle transitions, checklist item operations, the embargo toggle, the ops-run checkpoint, and the logical-clock control — return `200 OK`, as do all reads including the computed invoice. The blackout-window deletion returns `204 No Content`. All resource endpoints are mounted under the `/qa-cert` prefix; the logical-clock control lives at the server root. Every lifecycle-transition endpoint shares a uniform request shape: a `to_status` field naming the target state, supplemented by the action-specific fields narrated in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/qa-cert/ops/run` | Ops-run checkpoint: expire windows, flag SLA breaches | PlatformAdmin |
| POST | `/qa-cert/titles` | Register a game title | ReleaseManager |
| GET | `/qa-cert/titles` | List titles | Any |
| GET | `/qa-cert/titles/{titleId}` | Get a title | Any |
| POST | `/qa-cert/titles/{titleId}/transition` | Advance the title lifecycle | ReleaseManager |
| POST | `/qa-cert/titles/{titleId}/embargo` | Set or clear the compliance embargo flag | ComplianceManager |
| POST | `/qa-cert/vendors` | Onboard an external QA vendor | VendorManager |
| GET | `/qa-cert/vendors` | List vendors | Any |
| GET | `/qa-cert/vendors/{vendorId}` | Get a vendor with current-week capacity | Any |
| POST | `/qa-cert/vendors/{vendorId}/transition` | Vendor lifecycle: suspend, reinstate, terminate | VendorManager |
| GET | `/qa-cert/vendors/{vendorId}/invoice` | Computed weekly invoice under the requested variant | VendorManager |
| POST | `/qa-cert/test-plans` | Create a test plan for a title and platform | QALead |
| GET | `/qa-cert/test-plans` | List test plans | Any |
| GET | `/qa-cert/test-plans/{planId}` | Get a test plan with its entries | Any |
| POST | `/qa-cert/test-plans/{planId}/entries` | Append a feature-matrix entry to a draft plan | QALead |
| POST | `/qa-cert/test-plans/{planId}/transition` | Plan lifecycle: review, approve, send back, archive | QALead |
| POST | `/qa-cert/assignments` | Reserve vendor tester-hours against a plan entry | VendorManager |
| GET | `/qa-cert/assignments` | List assignments | Any |
| GET | `/qa-cert/assignments/{assignmentId}` | Get an assignment | Any |
| POST | `/qa-cert/assignments/{assignmentId}/transition` | Start, complete, or cancel an assignment | VendorManager |
| POST | `/qa-cert/builds` | Register a build for a title and platform | QALead |
| GET | `/qa-cert/builds` | List builds | Any |
| GET | `/qa-cert/builds/{buildId}` | Get a build | Any |
| POST | `/qa-cert/builds/{buildId}/transition` | Build lifecycle: test loop, candidacy, retire | QALead |
| POST | `/qa-cert/bugs` | Bug intake | QALead |
| GET | `/qa-cert/bugs` | List bugs with filters | Any |
| GET | `/qa-cert/bugs/{bugId}` | Get a bug | Any |
| POST | `/qa-cert/bugs/{bugId}/triage` | Triage an open bug with a (possibly new) severity | QALead |
| POST | `/qa-cert/bugs/{bugId}/transition` | Bug lifecycle: progress, reopen, wont-fix, duplicate | QALead |
| POST | `/qa-cert/titles/{titleId}/submission-packages` | Assemble a submission package (OCC on the title) | CertificationLead |
| GET | `/qa-cert/submission-packages` | List submission packages | Any |
| GET | `/qa-cert/submission-packages/{packageId}` | Get a submission package | Any |
| POST | `/qa-cert/submission-packages/{packageId}/transition` | Submit, review, decide, or withdraw a package | CertificationLead, PlatformReviewer |
| GET | `/qa-cert/compliance-checklists` | List checklists (find a package's checklist) | Any |
| GET | `/qa-cert/compliance-checklists/{checklistId}` | Get a checklist with items and counters | Any |
| POST | `/qa-cert/compliance-checklists/{checklistId}/items/verify` | Record a verification result for one item | ComplianceManager |
| POST | `/qa-cert/compliance-checklists/{checklistId}/items/waive` | Request a waiver for a failed item (OCC on the checklist) | CertificationLead |
| POST | `/qa-cert/compliance-checklists/{checklistId}/items/waiver-decision` | Approve or reject a pending waiver | ComplianceManager |
| POST | `/qa-cert/submission-packages/{packageId}/findings` | File a certification finding on a package | PlatformReviewer |
| GET | `/qa-cert/cert-findings` | List findings | Any |
| GET | `/qa-cert/cert-findings/{findingId}` | Get a finding | Any |
| POST | `/qa-cert/cert-findings/{findingId}/transition` | Mark a finding fixed in a newer build; verify or reopen | CertificationLead, PlatformReviewer |
| POST | `/qa-cert/age-rating-filings` | Create an age-rating filing for a territory | ReleaseManager |
| GET | `/qa-cert/age-rating-filings` | List filings | Any |
| GET | `/qa-cert/age-rating-filings/{filingId}` | Get a filing | Any |
| POST | `/qa-cert/age-rating-filings/{filingId}/transition` | File, decide, or amend an age-rating filing | ReleaseManager, PlatformReviewer |
| POST | `/qa-cert/localization-packs` | Create a localization pack for a locale | ReleaseManager |
| GET | `/qa-cert/localization-packs` | List localization packs | Any |
| GET | `/qa-cert/localization-packs/{packId}` | Get a localization pack | Any |
| POST | `/qa-cert/localization-packs/{packId}/transition` | Advance translation or signoff axis of a pack | ReleaseManager, QALead |
| POST | `/qa-cert/release-windows` | Reserve a release window (half-open overlap check) | ReleaseManager |
| GET | `/qa-cert/release-windows` | List release windows | Any |
| GET | `/qa-cert/release-windows/{windowId}` | Get a release window | Any |
| POST | `/qa-cert/release-windows/{windowId}/transition` | Confirm, consume, or release a window | ReleaseManager |
| POST | `/qa-cert/cert-blackout-windows` | Declare a platform certification freeze | PlatformAdmin |
| GET | `/qa-cert/cert-blackout-windows` | List blackout windows | Any |
| GET | `/qa-cert/cert-blackout-windows/{windowId}` | Get a blackout window | Any |
| DELETE | `/qa-cert/cert-blackout-windows/{windowId}` | Remove a blackout window | PlatformAdmin |
| POST | `/qa-cert/hotfixes` | Declare a post-launch hotfix | ReleaseManager |
| GET | `/qa-cert/hotfixes` | List hotfixes | Any |
| GET | `/qa-cert/hotfixes/{hotfixId}` | Get a hotfix | Any |
| POST | `/qa-cert/hotfixes/{hotfixId}/transition` | Hotfix lifecycle: develop, expedite, deploy, roll back | ReleaseManager, PlatformReviewer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PACKAGE_NOT_ASSEMBLING` | 409 Conflict |
| `ERR_PACKAGE_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_CHECKLIST_NOT_EDITABLE` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_BUILD_NOT_CANDIDATE` | 409 Conflict |
| `ERR_FIX_BUILD_NOT_QUALIFIED` | 409 Conflict |
| `ERR_NO_PLAN_ENTRIES` | 409 Conflict |
| `ERR_NO_APPROVED_PACKAGE` | 409 Conflict |
| `ERR_TITLE_NOT_CERT_APPROVED` | 409 Conflict |
| `ERR_TITLE_NOT_LAUNCHED` | 409 Conflict |
| `ERR_VENDOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_WAIVER_REQUIRES_FAILED_ITEM` | 409 Conflict |
| `ERR_WAIVER_NOT_PENDING` | 409 Conflict |
| `ERR_TITLE_UNDER_EMBARGO` | 403 Forbidden |
| `ERR_SELF_CERT_DECISION` | 403 Forbidden |
| `ERR_SELF_WAIVER_DECISION` | 403 Forbidden |
| `ERR_SUBMISSION_BLACKOUT_ACTIVE` | 409 Conflict |
| `ERR_WINDOW_IN_PAST` | 400 Bad Request |
| `ERR_HOTFIX_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_FINDING_BUILD_NOT_NEWER` | 422 Unprocessable Entity |
| `ERR_BUILD_TITLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BUILD_PLATFORM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REGRESSION_TARGET_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_WEEK_START_NOT_MONDAY` | 422 Unprocessable Entity |
| `ERR_CHECKLIST_INCOMPLETE` | 409 Conflict |
| `ERR_OPEN_BLOCKERS_EXIST` | 409 Conflict |
| `ERR_OPEN_CATEGORY_A_FINDINGS` | 409 Conflict |
| `ERR_AGE_RATING_NOT_GRANTED` | 409 Conflict |
| `ERR_LOCALIZATION_NOT_LOCKED` | 409 Conflict |
| `ERR_REQUIRED_COVERAGE_MISSING` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_COVERAGE_BELOW_LOCK_THRESHOLD` | 409 Conflict |
| `ERR_NO_HOTFIX_WINDOW` | 409 Conflict |
| `ERR_DUPLICATE_TEST_PLAN` | 409 Conflict |
| `ERR_DUPLICATE_FEATURE_AREA` | 409 Conflict |
| `ERR_DUPLICATE_BUILD_VERSION` | 409 Conflict |
| `ERR_DUPLICATE_FILING` | 409 Conflict |
| `ERR_DUPLICATE_LOCALE` | 409 Conflict |
| `ERR_CERT_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_NA_NOT_ALLOWED_FOR_REQUIRED` | 400 Bad Request |

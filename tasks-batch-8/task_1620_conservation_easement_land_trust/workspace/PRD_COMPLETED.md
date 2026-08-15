# Conservation Easement Stewardship API — Product Requirements Document

## 1. Introduction

A land trust that accepts a conservation easement takes on a perpetual obligation. Every encumbered parcel must be documented against a baseline, visited on a recurring monitoring cycle, defended when its terms are violated, and — when ownership changes hands or conservation practice evolves — amended through a defensible review process. Donors, accreditation bodies, and tax authorities each demand their own paper trail: appraisals delivered inside statutory substantiation windows, segregated duties between those who prepare work and those who approve it, and a stewardship endowment whose draws against restricted principal are accounted for to the cent.

This document specifies the Conservation Easement Stewardship API, the system of record for that obligation. The business surface is mounted under `/stewardship` and governs the full lifecycle — easement drafting and recordation, baseline documentation, monitoring visits, violations and enforcement, discretionary use authorizations, amendments, landowner succession, appraisals for tax-deduction substantiation, and a unitized stewardship endowment with a spending-policy drawdown rule. A six-role access model keeps preparation, approval, execution, and verification in different hands, while a server-owned logical clock drives time-based behavior such as cure-deadline escalation and notice expiry, so every rule in this document can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or naming a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Six roles are declared:

- `TrustAdmin` — the land trust administrator. Owns easement, landowner, and endowment-fund setup, recordation, succession acknowledgment and recording, ledger contributions and investment returns, and the test clock.
- `StewardshipCoordinator` — stewardship staff. Runs baseline reports, monitoring scheduling, violations, amendments, use-authorization decisions, enforcement completion and renegotiation, appraisal engagement and certification, and routine endowment draws.
- `FieldMonitor` — field staff assigned to monitoring visits; may complete only visits assigned to them.
- `Landowner` — the easement's current `ACTIVE` landowner; requests discretionary uses, begins cure on noticed violations, and gives succession notice.
- `TrustBoardReviewer` — board reviewer. Accepts baseline reports, approves board-path amendments, executes and breaches enforcement agreements, closes the endowment fiscal year, and authorizes principal-invasion draws.
- `Appraiser` — an engaged appraiser; delivers valuations only on their own engagements.

Role identity is resolved as follows. When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of the acting `Landowner` record; ownership checks on any resource that references a landowner compare the resource's foreign-key field (for example, the easement's `current_landowner_id`) to `X-User-ID`. When `X-User-Role` is `TrustAdmin`, `StewardshipCoordinator`, `FieldMonitor`, `TrustBoardReviewer`, or `Appraiser`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `prepared_by_user_id` on a baseline report or `executed_by_user_id` on an enforcement action) but never compares it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the server's logical clock (§2.10).
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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; when not provided it defaults to 10, and accepted values run from a minimum of 1 to a maximum of 100. `offset` sets how many items are skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1-to-100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400). Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by insertion order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, read from the server's logical clock (§2.10); `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of the resource — including mutations caused by cascades that originate on another resource. For example, a completed monitoring visit that recomputes its easement's monitoring schedule advances the easement's `version` by one and refreshes its `updated_at`, even though the request targeted the visit.

One resource breaks this pattern deliberately. An `EndowmentTransaction` is an immutable, append-only ledger event: it carries `id` and `created_at` only. It has no `updated_at` and no `version`, and it is never modified after posting.

### 2.5. The Easement Posture Gate

Each easement exposes a derived `posture` that summarizes its compliance position. Posture is recomputed relentlessly and is evaluated in a strict precedence order, highest tier first. It is `ENFORCEMENT_ACTIVE` when any enforcement action on the easement is `PROPOSED`, `EXECUTED`, or `BREACHED`. Failing that, it is `VIOLATION_OPEN` when any violation on the easement is `OPEN`, `NOTICE_SENT`, `CURE_IN_PROGRESS`, or `ESCALATED`. Failing that, it is `MONITORING_DUE` when the logical clock's date is strictly later than `next_monitoring_due_on` — on the due date itself the easement is not yet due. Otherwise it is `GOOD_STANDING`. A `COMPLETED` enforcement action therefore relaxes the top tier, and an easement whose violations have all resolved and whose monitoring is current settles back to `GOOD_STANDING`.

Posture — and, where relevant, `open_violation_count` — is recomputed whenever a violation opens or resolves, when an escalation spawns an enforcement action, when an enforcement action completes, when a monitoring visit completes, at recordation, and during the clock sweep. Each such recomputation is a mutation of the easement in its own right: `updated_at` refreshes and `version` increments by exactly one per triggering operation. During the clock sweep specifically, an easement is mutated only when its computed posture actually changes between the old and the new clock date, and an easement already mutated by an escalation earlier in the same sweep is not advanced again for the posture recomputation.

### 2.6. The Permitted-Use Matrix

Every easement carries a `permitted_use_matrix`, a map from use type to one of three levels: `PERMITTED`, `DISCRETIONARY`, or `PROHIBITED`. At least one use-type entry is required at creation. The matrix is the single authority on what may happen on the parcel: a `PERMITTED` use needs no one's approval and can never ground a violation; a `DISCRETIONARY` use requires an approved use authorization before the landowner proceeds; a `PROHIBITED` use is never authorizable. The matrix is mutated in exactly one way — by an approved amendment request — so its evolution is always traceable to a decided request, and any check that consults the matrix reads the easement's current version of it.

### 2.7. Money, Units, and Precision

All monetary amounts are integer cents: remediation budgets, stewardship visit costs, appraised values, the endowment's market value, and every ledger amount. Endowment `units` and the fund's `unit_value_cents` are decimal numbers carried to exactly four decimal places, rounded half-up at every step where a rounding is specified. The amendment materiality score is an integer from 0 to 100. Business dates such as `recorded_on`, `detected_on`, and `effective_on` are ISO 8601 calendar dates in `YYYY-MM-DD` form; timestamps are full ISO 8601 UTC with three fractional digits. The endowment spending policy is expressed in basis points, so a `spending_rate_bps` of 100 means one percent per year and the policy ceiling of 800 means eight percent.

### 2.8. Optimistic Concurrency Control

Three write operations guard against stale reads through optimistic concurrency control; no other endpoint accepts a version field.

- Creating an amendment request requires `expected_easement_version` equal to the easement's current `version`. A client prices its requested changes against a permitted-use matrix the server may since have replaced — a prior amendment approval legitimately rewrites the matrix while leaving no amendment in flight — so a mismatch is rejected with `ERR_STALE_EASEMENT_VERSION` (HTTP 412).
- Recording an acknowledged succession notice requires `expected_easement_version` equal to the easement's current `version`. A previously recorded succession legitimately transfers ownership again — a second notice can remain `ACKNOWLEDGED` and would otherwise record cleanly — so the only sound basis for rejection is a stale easement version, reported as `ERR_STALE_EASEMENT_VERSION` (HTTP 412).
- Posting an endowment draw requires `expected_fund_version` equal to the fund's current `version`. The caller computed its allocation against a snapshot of `market_value_cents`, `unit_value_cents`, and the draw allowance that a prior write may already have moved, and a fresh draw would otherwise still pass every balance check against the new state; a mismatch is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412).

### 2.9. Validation Pipeline and Error Precedence

Validations run in a fixed order, and an earlier failure masks every later check. The pipeline:

1. Header presence and role declaration — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role permission for the endpoint — `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. Existence — path identifiers are validated left to right, and the first identifier that does not resolve yields its typed 404: `ERR_EASEMENT_NOT_FOUND` for `easementId`, `ERR_LANDOWNER_NOT_FOUND` for `landownerId`, `ERR_BASELINE_REPORT_NOT_FOUND` for `baselineReportId`, `ERR_MONITORING_VISIT_NOT_FOUND` for `monitoringVisitId`, `ERR_VIOLATION_NOT_FOUND` for `violationId`, `ERR_AMENDMENT_REQUEST_NOT_FOUND` for `amendmentRequestId`, `ERR_USE_AUTHORIZATION_NOT_FOUND` for `useAuthorizationId`, `ERR_ENFORCEMENT_ACTION_NOT_FOUND` for `enforcementActionId`, `ERR_SUCCESSION_NOTICE_NOT_FOUND` for `successionNoticeId`, `ERR_APPRAISAL_NOT_FOUND` for `appraisalId`, and `ERR_ENDOWMENT_FUND_NOT_FOUND` for `endowmentFundId`. Foreign keys carried in the request body must resolve as well.
4. State — the target resource must be in a state from which the requested transition exists: `ERR_INVALID_BASELINE_STATE`, `ERR_INVALID_VISIT_STATE`, `ERR_INVALID_VIOLATION_STATE`, `ERR_INVALID_AMENDMENT_STATE`, `ERR_INVALID_USE_AUTHORIZATION_STATE`, `ERR_INVALID_ENFORCEMENT_STATE`, `ERR_INVALID_NOTICE_STATE`, or `ERR_INVALID_APPRAISAL_STATE` (all 409).
5. Cross-entity gates — child operational creates require a `RECORDED` easement (`ERR_EASEMENT_NOT_RECORDED`); recordation requires an `ACCEPTED` baseline and an `ACTIVE` landowner (`ERR_BASELINE_NOT_ACCEPTED`, `ERR_OPEN_OBLIGATIONS_EXIST`); investment returns, draws, and fiscal-year close require an `ACTIVE` fund (`ERR_FUND_NOT_ACTIVE`).
6. Optimistic concurrency — `ERR_STALE_EASEMENT_VERSION` or `ERR_STALE_FUND_VERSION` (412), per §2.8.
7. Segregation of duties and assignment identity — `ERR_SEGREGATION_OF_DUTIES`, `ERR_NOT_ASSIGNED_MONITOR`, `ERR_NOT_ENGAGED_APPRAISER` (403), per §2.11.
8. Uniqueness — `ERR_BASELINE_ALREADY_EXISTS`, `ERR_AMENDMENT_ALREADY_IN_FLIGHT`, `ERR_FUND_ALREADY_EXISTS`, `ERR_USE_CURRENTLY_AUTHORIZED`, `ERR_OPEN_OBLIGATIONS_EXIST` (409).
9. Domain rules — malformed payloads (`ERR_INVALID_REQUEST`), baseline photo-point completeness (`ERR_INCOMPLETE_BASELINE`), the discretionary-cell and violable-cell rules (`ERR_USE_NOT_DISCRETIONARY`, `ERR_USE_PERMITTED_NOT_VIOLABLE`), the visit window (`ERR_VISIT_OUTSIDE_WINDOW`), staff-approval materiality (`ERR_MATERIALITY_REQUIRES_BOARD`), the amendment freeze (`ERR_AMENDMENT_FREEZE_CONFLICT`), and positive-deduction certification (`ERR_NON_POSITIVE_DEDUCTION`).
10. Temporal windows — `ERR_MONITOR_WINDOW_OVERLAP` and `ERR_APPRAISAL_ENGAGEMENT_OVERLAP` (409); `ERR_NOTICE_WINDOW_VIOLATION` and `ERR_SUBSTANTIATION_WINDOW_EXPIRED` (422).
11. Referential independence — `ERR_APPRAISER_CONFLICT` (422) and `ERR_NOT_CURRENT_LANDOWNER` (403).
12. Draw authority — `ERR_PRINCIPAL_INVASION_REQUIRES_BOARD` and `ERR_DRAW_EXCEEDS_AUTHORITY` (402).

### 2.10. The Logical Clock and Scheduled Sweeps

The server owns a logical clock that supplies every "clock date" and "clock time" named in this document — system-stamped fields such as `notice_served_on`, `submitted_on`, and `posted_on` all read it. At startup the clock reads exactly 2026-08-01T00:00:00Z, and before any explicit set it continues to read that default; it never consults the wall clock. An admin-only test-driving capability accepts a `to_iso8601` instant and sets the clock. A date-only value is read as midnight UTC, instants carrying an offset and naive instants are normalized to UTC, and an unparseable value is rejected with `ERR_INVALID_REQUEST` (400); the response's `data` carries the new reading as `current_utc`. Setting the clock runs a sweep with three effects: any violation in `NOTICE_SENT` or `CURE_IN_PROGRESS` whose cure deadline has passed escalates, spawning enforcement and flipping easement posture as described in §3.3; any succession notice still `NOTICE_GIVEN` past its acknowledgment deadline expires as described in §3.7; and every easement's monitoring posture is recomputed against the new date per §2.5.

### 2.11. Segregation of Duties and Identity-Anchored Operations

Four prepare-and-approve pairs are segregated, and crossing any of them with a single identity is rejected with `ERR_SEGREGATION_OF_DUTIES` (403): the staffer who prepared a baseline report (`prepared_by_user_id`) may not accept it; the staffer who detected a violation (`detected_by_user_id`) may not verify its resolution; the board reviewer who executed an enforcement agreement (`executed_by_user_id`) may not complete it; and the submitter of an amendment (`submitted_by_user_id`) may not approve it.

Two operations are anchored to an assignment rather than segregated: completing a monitoring visit is restricted to the visit's assigned `monitor_user_id` (`ERR_NOT_ASSIGNED_MONITOR`, 403), and delivering an appraisal is restricted to the engagement's `appraiser_user_id` (`ERR_NOT_ENGAGED_APPRAISER`, 403). Separately, landowner-actor operations require the caller to be the easement's current landowner — `X-User-ID` must equal the easement's `current_landowner_id` — enforced on use-authorization requests, succession notices, and the start of cure, with violations reported as `ERR_NOT_CURRENT_LANDOWNER` (403).

## 3. Business Logic & Workflows

### 3.1. Drafting, Baseline Documentation, and Recordation

A `TrustAdmin` opens a new easement record with its `easement_name`, the `grantor_name` of the granting landowner at recordation, the encumbered `parcel_acreage` as a whole number of acres (which must be greater than zero), and the initial `permitted_use_matrix` carrying at least one use-type entry. The `monitoring_interval_months` may be supplied to override the default of 12; any whole value from 6 to 36 months is acceptable. A malformed payload — a missing required field, a value of the wrong type, an out-of-range interval, an empty matrix, or non-positive acreage — is rejected with `ERR_INVALID_REQUEST`. The easement is born in `DRAFT` with `posture` `GOOD_STANDING` and `version` 1; `recorded_on`, `last_monitoring_completed_on`, and `next_monitoring_due_on` are null, and `open_violation_count` and `amendment_count` read zero.

While the easement is `DRAFT`, a `TrustAdmin` registers the initial landowner by supplying the easement's `easement_id`, the `owner_name`, and a `contact_email` used for notices. This succeeds only while the easement is `DRAFT` and no landowner exists yet; attempting it on a recorded easement, or when a landowner already exists, is rejected with `ERR_OPEN_OBLIGATIONS_EXIST`. The initial landowner is created `ACTIVE` with `acquired_on` set to the clock date and `predecessor_landowner_id` null; the easement's `current_landowner_id` is set to the new record and the easement's `version` advances by one. Landowners can be browsed with filters on `easement_id`, `predecessor_landowner_id`, and `status`.

Before the easement can be recorded, its baseline documentation must pass review. A `StewardshipCoordinator` creates the easement's single baseline report — a second one for the same easement is rejected with `ERR_BASELINE_ALREADY_EXISTS` — supplying `easement_id`, the `prepared_by_user_id` of the staffer who documented the property, a `condition_narrative` describing the conservation values, and the `photo_point_count` of georeferenced photo points (zero or more). The report starts in `DRAFT` with `review_round` zero.

Submission — whether the first submit from `DRAFT` or a resubmission from `REVISION_REQUESTED` — requires the documented photo points to cover the terrain: `photo_point_count` must be at least `required_photo_points`, where `required_photo_points` is the larger of 4 and the parcel's acreage divided by 100 rounded up to a whole number, recomputed from the easement's current acreage at submit time. Submitting short of that bar is rejected with `ERR_INCOMPLETE_BASELINE` (422), and submitting from any state other than `DRAFT` or `REVISION_REQUESTED` is rejected with `ERR_INVALID_BASELINE_STATE` (409). Each successful submission moves the report to `SUBMITTED`, increments `review_round` by one, and stamps `submitted_on` with the clock date.

A `TrustBoardReviewer` then disposes of the `SUBMITTED` report. Acceptance moves it to `ACCEPTED` and stamps `accepted_on` with the clock date; the acceptor must not be the preparer — an `X-User-ID` matching `prepared_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Requesting revision returns the report to `REVISION_REQUESTED` and captures the reviewer's `revision_notes`, which is required — a missing or non-string `revision_notes` is rejected with `ERR_INVALID_REQUEST`; the coordinator revises and submits again, and the cycle can repeat. Either disposition attempted on a report that is not `SUBMITTED` is rejected with `ERR_INVALID_BASELINE_STATE`. Baseline reports can be browsed with filters on `easement_id` and `status`.

Recordation itself is a `TrustAdmin` act with three gates. The easement must still be `DRAFT` — attempting to record an already `RECORDED` easement is rejected with `ERR_INVALID_REQUEST`, because recordation is a no-op there. The easement's baseline report must be `ACCEPTED`, else `ERR_BASELINE_NOT_ACCEPTED`. And `current_landowner_id` must reference an `ACTIVE` landowner, else `ERR_OPEN_OBLIGATIONS_EXIST`. On success the easement becomes `RECORDED`, `recorded_on` is set to the clock date, `next_monitoring_due_on` is computed from the recordation date plus `monitoring_interval_months` months under the month-end clamping rule of §3.2, posture is computed (`GOOD_STANDING`), and `version` advances by one. Once `RECORDED`, the easement admits child operational records — monitoring visits, violations, amendments, use authorizations, succession notices, and appraisals; attempting any of those creates against a `DRAFT` easement is rejected with `ERR_EASEMENT_NOT_RECORDED`. Easements can be browsed with filters on `current_landowner_id`, `status`, and `posture` (the derived value of §2.5).

### 3.2. The Monitoring Calendar and Field Visits

Once an easement is `RECORDED`, a `StewardshipCoordinator` schedules monitoring visits. Creating a visit takes `easement_id`, the `monitor_user_id` of the `FieldMonitor` who will walk the parcel, and a planned field window from `window_start_on` (inclusive) to `window_end_on` (exclusive); an end date that is not later than the start date is rejected with `ERR_INVALID_REQUEST`. A monitor may not hold overlapping commitments: if the new window intersects another `SCHEDULED` or `COMPLETED` visit assigned to the same `monitor_user_id`, creation is rejected with `ERR_MONITOR_WINDOW_OVERLAP` (409). Windows use half-open semantics, so one visit ending on the day another begins — the end of one equal to the start of the next — does not count as an overlap, and cancelled visits do not participate in the check at all. A new visit is born `SCHEDULED`.

The assigned monitor — and only the assigned monitor — completes the visit, supplying the `actual_visit_on` date, a `findings_summary`, and the `stewardship_cost_cents` of the visit (zero or more cents). Completion enforces its checks in pipeline order: the visit must be `SCHEDULED`, else `ERR_INVALID_VISIT_STATE`; the caller's `X-User-ID` must equal the visit's `monitor_user_id`, else `ERR_NOT_ASSIGNED_MONITOR`; and `actual_visit_on` must fall inside the planned window — on or after `window_start_on` and strictly before `window_end_on` — else `ERR_VISIT_OUTSIDE_WINDOW` (422).

Completion cascades into the easement's calendar. The visit's `on_time` flag is computed against the due date in force before this completion: the visit is on time when `actual_visit_on` is on or before the easement's `next_monitoring_due_on` — completing on the due date itself counts as on time, while completing one day later does not. The easement's `last_monitoring_completed_on` then becomes `actual_visit_on`, and `next_monitoring_due_on` is recomputed as that completion date plus `monitoring_interval_months` months. Month arithmetic keeps the day of month where possible; when the target month lacks that day, the due date clamps to the month's last day. The same rule produced the initial due date at recordation from `recorded_on`, and in general the base is `last_monitoring_completed_on` when present, else `recorded_on`; while the easement is `DRAFT`, the due date is null. The completion finally recomputes the easement's `posture` and advances the easement's `version` by one, per §2.5.

A coordinator may also cancel a `SCHEDULED` visit, moving it to `CANCELLED`; attempting cancellation from any other state is rejected with `ERR_INVALID_VISIT_STATE`. Visits can be browsed with filters on `easement_id`, `monitor_user_id`, and `status`. When the logical clock runs past an unmet `next_monitoring_due_on`, the sweep flips the easement's posture to `MONITORING_DUE` under the precedence rules of §2.5 — and, again, the due date itself still reads `GOOD_STANDING`.

### 3.3. Violations: Detection, Notice, Cure, and Escalation

A `StewardshipCoordinator` opens a violation against a `RECORDED` easement, supplying `easement_id`, the `detected_by_user_id` of the staffer who found the condition, a `violation_type`, a `severity` of `MINOR`, `MATERIAL`, or `IRREPARABLE`, and the `detected_on` date. An optional `monitoring_visit_id` ties the finding to a field visit; when supplied, the referenced visit must be `COMPLETED`, else `ERR_INVALID_REQUEST`. The `violation_type` must be a key of the easement's current `permitted_use_matrix` — an unknown key is rejected with `ERR_INVALID_REQUEST` — and the matrix cell must be `PROHIBITED` or `DISCRETIONARY`: opening a violation against a `PERMITTED` cell is rejected with `ERR_USE_PERMITTED_NOT_VIOLABLE` (422). A new violation is born `OPEN`. Creation immediately recomputes the easement's `open_violation_count` — the count of violations in `OPEN`, `NOTICE_SENT`, `CURE_IN_PROGRESS`, or `ESCALATED` — refreshes `posture`, and advances the easement's `version` by one. If an active use authorization (one still `REQUESTED`, `APPROVED`, or `APPROVED_WITH_CONDITIONS`) covers the same use type on the same easement, its `conditions_breached` flag is set to true.

Serving notice is a coordinator act that moves the violation from `OPEN` to `NOTICE_SENT`; from any other state it is rejected with `ERR_INVALID_VIOLATION_STATE`. Notice can only be served while the easement's `current_landowner_id` references an `ACTIVE` landowner, else `ERR_NOT_CURRENT_LANDOWNER`. Serving stamps `notice_served_on` with the clock date and sets the cure clock: `cure_deadline_on` is the notice date plus the cure period for the severity — ninety days for `MINOR`, thirty days for `MATERIAL`, and seven days for `IRREPARABLE`.

The current landowner begins curing by moving the violation from `NOTICE_SENT` to `CURE_IN_PROGRESS`; the caller's `X-User-ID` must equal the easement's `current_landowner_id`, else `ERR_NOT_CURRENT_LANDOWNER`, and any other starting state yields `ERR_INVALID_VIOLATION_STATE`. A coordinator then verifies the cure, moving the violation from `CURE_IN_PROGRESS` to `RESOLVED`; the verifier must not be the detector — an `X-User-ID` matching `detected_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Resolution stamps `resolved_on` with the clock date, records the verifier in `resolution_verified_by_user_id`, recomputes `open_violation_count` and `posture`, and advances the easement's `version` by one.

Escalation converts an un cured violation into an enforcement matter, and it arrives by one of two routes. A coordinator may manually escalate a `NOTICE_SENT` violation, recording `escalated_by` as `MANUAL`. Independently, the clock sweep escalates any violation in `NOTICE_SENT` or `CURE_IN_PROGRESS` once the clock date is strictly later than `cure_deadline_on` — the deadline day itself is still curable — recording `escalated_by` as `CLOCK_SWEEP`. Either route runs the same three-link cascade: the violation moves to `ESCALATED`; a new enforcement action is created in `PROPOSED` carrying this violation's `violation_id` and its `easement_id` denormalized from the violation; and that creation flips the easement's `posture` to `ENFORCEMENT_ACTIVE` and advances the easement's `version` by one. Manual escalation from any state other than `NOTICE_SENT` is rejected with `ERR_INVALID_VIOLATION_STATE`. Violations can be browsed with filters on `easement_id`, `monitoring_visit_id`, `status`, and `severity`.

### 3.4. Enforcement Actions and Remediation Agreements

Enforcement actions are never created directly; each one is born in `PROPOSED` from a violation escalation, linked to its `violation_id` and `easement_id`. A `TrustBoardReviewer` executes the remediation agreement, moving the action from `PROPOSED` to `EXECUTED`; any other starting state is rejected with `ERR_INVALID_ENFORCEMENT_STATE`. Execution records the negotiated `agreement_terms` and the agreed `remediation_cost_cents` budget (zero or more cents) — both are required, and a missing or ill-typed value is rejected with `ERR_INVALID_REQUEST` — and stamps `executed_by_user_id` with the caller's `X-User-ID`.

Completion is a coordinator act that moves the action from `EXECUTED` to `COMPLETED`. The completer must not be the executor — an `X-User-ID` matching `executed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Completion stamps `completed_by_user_id`, then resolves the linked violation from `ESCALATED` to `RESOLVED`, stamping its `resolved_on` with the clock date and its `resolution_verified_by_user_id` with the completer's identity; the easement's `open_violation_count` and `posture` are recomputed and the easement's `version` advances by one.

When an agreement fails, a `TrustBoardReviewer` declares the breach, moving the action from `EXECUTED` to `BREACHED` and capturing optional `breach_notes`. A coordinator can then renegotiate, moving the action from `BREACHED` back to `PROPOSED`: fresh `agreement_terms` and `remediation_cost_cents` — both required, else `ERR_INVALID_REQUEST` — replace the old ones, `executed_by_user_id` is cleared to null so the renegotiated agreement requires a fresh board execution, and `breach_notes` is retained from the breached cycle. Breach or renegotiate attempted from any state where they are not defined is rejected with `ERR_INVALID_ENFORCEMENT_STATE`. Note what the posture gate in §2.5 implies for this loop: a `BREACHED` action still holds the easement at `ENFORCEMENT_ACTIVE`, and only completion of every open enforcement matter lets the easement's posture relax. Enforcement actions can be browsed with filters on `violation_id`, `easement_id`, and `status`.

### 3.5. Discretionary Use Authorizations

A `DISCRETIONARY` cell in the matrix means "ask first." The current landowner requests a use authorization with the `easement_id`, the `use_type` they intend, and a `justification` making the case. Creation enforces its checks in pipeline order: the easement must exist and be `RECORDED`; no active authorization — one in `REQUESTED`, `APPROVED`, or `APPROVED_WITH_CONDITIONS` — may already cover the same use type on the same easement, else `ERR_USE_CURRENTLY_AUTHORIZED` (409); the matrix cell must be `DISCRETIONARY` at request time, because a `PERMITTED` use needs no approval and a `PROHIBITED` use is never authorizable, either case drawing `ERR_USE_NOT_DISCRETIONARY` (422) — while a `use_type` that is not a key of the matrix at all is rejected with `ERR_INVALID_REQUEST`; and the caller's `X-User-ID` must equal the easement's `current_landowner_id`, else `ERR_NOT_CURRENT_LANDOWNER`. The authorization is born `REQUESTED` with `decision` null, `requested_by_landowner_id` set from the caller's `X-User-ID`, and `conditions_breached` false.

A `StewardshipCoordinator` decides a `REQUESTED` authorization; deciding from any other state is rejected with `ERR_INVALID_USE_AUTHORIZATION_STATE`. Before any decision, a freeze check applies: if any amendment request of the same easement is in flight — `SUBMITTED`, `STAFF_REVIEW`, `REVISION_REQUESTED`, or `BOARD_REVIEW` — and its `requested_changes` include this authorization's `use_type`, the decide is rejected with `ERR_AMENDMENT_FREEZE_CONFLICT` (409), because the cell's very meaning is under review. Three outcomes then stand with equal standing. A `decision` of `APPROVED` moves the authorization to `APPROVED`. A `decision` of `APPROVED_WITH_CONDITIONS` moves it to `APPROVED_WITH_CONDITIONS` and requires `conditions` to be a non-empty array — omitting it, sending a non-array, or sending an empty array is rejected with `ERR_INVALID_REQUEST`; the array's elements are not individually validated. A `decision` of `DENIED` moves it to `DENIED`. `conditions` is stored only for `APPROVED_WITH_CONDITIONS`; for the other two outcomes it reads null. In all three outcomes the free-text `decision_reason` is stored when supplied.

Two system-driven fates can overtake a live authorization. When an amendment approval rewrites a cell, every still-`REQUESTED` authorization on that easement whose `use_type` appears among the amendment's changes is set to `DENIED` with `decision_reason` `AMENDMENT_SUPERSEDES` — the freeze's mirror image, described in §3.6. And when a violation is opened against a covered use type, an active authorization's `conditions_breached` flag flips to true, as described in §3.3. Authorizations can be browsed with filters on `easement_id`, `requested_by_landowner_id`, `use_type`, and `status`.

### 3.6. Amending the Easement: Materiality, Routing, and the Approval Cascade

A `StewardshipCoordinator` submits an amendment request against a `RECORDED` easement, carrying `easement_id`, the OCC field `expected_easement_version`, the `submitted_by_user_id`, the `requested_changes`, and the `affected_acreage`. The checks run in pipeline order. The easement must exist and be `RECORDED`, else `ERR_EASEMENT_NOT_FOUND` or `ERR_EASEMENT_NOT_RECORDED`. The `expected_easement_version` must match the easement's current `version`, else `ERR_STALE_EASEMENT_VERSION` (412) per §2.8. No other amendment of the same easement may be in flight — `SUBMITTED`, `STAFF_REVIEW`, `REVISION_REQUESTED`, or `BOARD_REVIEW` — else `ERR_AMENDMENT_ALREADY_IN_FLIGHT` (409). Then the payload shape rules: `requested_changes` is a non-empty array of entries each pairing a `use_type` with a `new_level`; every `use_type` must already exist as a key in the easement's current matrix; every `new_level` must be one of `PERMITTED`, `DISCRETIONARY`, or `PROHIBITED` and must differ from the cell's current level; and `affected_acreage` must be at least one acre and no more than the easement's full `parcel_acreage`. Violations of any of these are rejected with `ERR_INVALID_REQUEST`. A created request is born `SUBMITTED`, its `materiality_score` and `review_path` are computed, and the easement's `version` advances by one.

The materiality score combines three components. Acreage points: the share of the parcel affected — `affected_acreage` divided by the easement's `parcel_acreage` — multiplied by fifty and rounded half-up to a whole number. Change points: ten points per requested change. Downgrade points: thirty when any change moves a cell from `PROHIBITED` to `PERMITTED`; otherwise fifteen when any change moves a cell from `DISCRETIONARY` to `PERMITTED`; otherwise zero — only the single largest downgrade contributes, never a sum across changes. The `materiality_score` is the sum of the three components, capped at 100. The `review_path` is `BOARD` when the score is 70 or higher — a score of exactly 70 routes to the board, while 69 stays with staff — and `STAFF` otherwise. Both fields are recomputed on every resubmission.

Review proceeds as a loop with two decision lanes. Starting review moves a `SUBMITTED` request to `STAFF_REVIEW`. From there a coordinator may request revision, moving it to `REVISION_REQUESTED` and capturing `revision_notes` — required, with a missing or non-string value rejected as `ERR_INVALID_REQUEST`; the coordinator's resubmission moves it back to `SUBMITTED`, replacing `requested_changes` and `affected_acreage` wholesale and recomputing `materiality_score` and `review_path`. A coordinator may instead escalate the request from `STAFF_REVIEW` to `BOARD_REVIEW` — the practical route whenever the score bars staff approval, though available for any staff-review request.

Approval has two lanes with matching density. On the staff lane, a `StewardshipCoordinator` approves from `STAFF_REVIEW` — permitted only when the request's `review_path` is `STAFF`, that is, a `materiality_score` below 70; attempting staff approval at 70 or above is rejected with `ERR_MATERIALITY_REQUIRES_BOARD` (403). On the board lane, a `TrustBoardReviewer` approves from `BOARD_REVIEW`. In both lanes the approver must not be the submitter — an `X-User-ID` matching `submitted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` — and `decided_by_user_id` records the approver. Approval fires a two-link cascade. Link one: the easement's `permitted_use_matrix` is mutated per `requested_changes`, `amendment_count` increments by one, and the easement's `version` advances by one. Link two: every use authorization of this easement still in `REQUESTED` whose `use_type` appears among the requested changes is set to `DENIED` — both `status` and `decision` — with `decision_reason` `AMENDMENT_SUPERSEDES`.

Rejection and withdrawal are quieter exits. Rejection applies from `STAFF_REVIEW` or `BOARD_REVIEW` — a coordinator rejects from staff review, a board reviewer from board review — moving the request to `REJECTED` with `decided_by_user_id` recorded. A coordinator may withdraw the request from any non-terminal state — `SUBMITTED`, `STAFF_REVIEW`, `REVISION_REQUESTED`, or `BOARD_REVIEW` — moving it to `WITHDRAWN`. Any transition attempted from a state where it is not defined is rejected with `ERR_INVALID_AMENDMENT_STATE` (409). Amendment requests can be browsed with filters on `easement_id` and `status`.

### 3.7. Landowner Succession

When an encumbered parcel changes hands, the outgoing landowner gives notice. The current landowner creates a succession notice with the `easement_id`, the successor's `successor_owner_name` and `successor_contact_email`, and the planned `transfer_on` date. The easement must be `RECORDED`, the caller's `X-User-ID` must equal the easement's `current_landowner_id` (else `ERR_NOT_CURRENT_LANDOWNER`), and `transfer_on` must fall at least thirty days after the clock date — a shorter runway is rejected with `ERR_NOTICE_WINDOW_VIOLATION` (422), while exactly thirty days out is acceptable. Creation stamps `notice_given_on` with the clock date, sets `ack_deadline_on` to forty-five days after the notice date, and creates the successor landowner row in `PENDING_SUCCESSION` — its `owner_name` and `contact_email` taken from the successor fields, its `predecessor_landowner_id` set to the current landowner. The notice records both parties in `successor_landowner_id` and `predecessor_landowner_id` and is born `NOTICE_GIVEN`. Creation does not check for other in-flight notices on the same easement; any number of notices may be concurrently `NOTICE_GIVEN` or `ACKNOWLEDGED`.

A `TrustAdmin` acknowledges receipt, moving the notice from `NOTICE_GIVEN` to `ACKNOWLEDGED`; acknowledging from any other state — including after the clock sweep has expired the notice — is rejected with `ERR_INVALID_NOTICE_STATE`. Recording the transfer is likewise a `TrustAdmin` act, from `ACKNOWLEDGED` to `RECORDED`, and it carries the OCC guard of §2.8: the request must present `expected_easement_version` matching the easement's current `version`, else `ERR_STALE_EASEMENT_VERSION` (412). Recording stamps the notice's `recorded_on` with the clock date, activates the successor from `PENDING_SUCCESSION` to `ACTIVE` with `acquired_on` set, retires the predecessor from `ACTIVE` to `SUPERSEDED`, flips the easement's `current_landowner_id` to the successor, and advances the easement's `version` by one — all as one mutation.

Time can kill a notice instead. When the clock sweep finds a notice still `NOTICE_GIVEN` with the clock date later than `ack_deadline_on`, the notice moves to `EXPIRED`, and its successor row is stranded in `PENDING_SUCCESSION`, never activating. Notices can be browsed with filters on `easement_id`, `successor_landowner_id`, `predecessor_landowner_id`, and `status`.

### 3.8. Appraisals and Deduction Substantiation

A `StewardshipCoordinator` engages an appraisal on a `RECORDED` easement, supplying `easement_id`, the `appraiser_user_id` of the engaged appraiser, the valuation's `effective_on` date, the `gift_on` date of the easement contribution, and the `contiguous_enhancement_applies` flag that selects the deduction variant. One appraiser may not hold overlapping engagements on the same easement: if another appraisal with the same `appraiser_user_id` and `easement_id` is `ENGAGED` or `DELIVERED` and its `effective_on` lies less than 365 days from the new one, creation is rejected with `ERR_APPRAISAL_ENGAGEMENT_OVERLAP` (409); a gap of exactly 365 days is allowed. The appraisal is born `ENGAGED`.

Delivery belongs to the engaged appraiser alone: a caller whose `X-User-ID` does not match `appraiser_user_id` is rejected with `ERR_NOT_ENGAGED_APPRAISER`, and delivery from any state other than `ENGAGED` is rejected with `ERR_INVALID_APPRAISAL_STATE`. Delivery records the `before_value_cents` (the parcel's fair market value before the easement, which must be greater than zero), the `after_value_cents` (the value with the easement in place, zero or more), and the optional `enhancement_value_cents` (the value the gift adds to contiguous retained land, defaulting to 0; a negative value is rejected with `ERR_INVALID_REQUEST`), and moves the appraisal to `DELIVERED`.

Certification, a coordinator act from `DELIVERED`, enforces four checks in the pipeline's order. The appraisal must be `DELIVERED`, else `ERR_INVALID_APPRAISAL_STATE`. The computed deduction must be positive, else `ERR_NON_POSITIVE_DEDUCTION` (422). The substantiation window must hold — `effective_on` no earlier than sixty days before `gift_on`, and the clock date no later than 240 days after `gift_on`, both boundaries inclusive — else `ERR_SUBSTANTIATION_WINDOW_EXPIRED` (422). And the appraiser must be independent of the baseline: an `appraiser_user_id` matching the easement baseline report's `prepared_by_user_id` is rejected with `ERR_APPRAISER_CONFLICT` (422).

The deductible itself has two variants. Under the standard variant — `contiguous_enhancement_applies` false — `deductible_value_cents` is simply the before value less the after value, and `enhancement_value_cents` is ignored entirely; a difference of zero or less fails the positive-deduction check. Under the enhancement-adjusted variant — the flag true — the enhancement value is subtracted as well, with the result floored at zero; here the positive-deduction check fails whenever the before value less the after value less the enhancement comes to zero or less, so the floor is never actually stored. The same delivered numbers can therefore legitimately produce different deductibles under the two variants. On certification the computed `deductible_value_cents` is frozen onto the appraisal and the status becomes `CERTIFIED`. A coordinator may withdraw an appraisal from `ENGAGED` or `DELIVERED`, moving it to `WITHDRAWN`; withdrawal from any other state is rejected with `ERR_INVALID_APPRAISAL_STATE`. Appraisals can be browsed with filters on `easement_id`, `appraiser_user_id`, and `status`.

### 3.9. The Stewardship Endowment: Unitization, Draws, and the Fiscal-Year Close

Each easement may be backed by a single stewardship endowment — a second fund for the same easement is rejected with `ERR_FUND_ALREADY_EXISTS`. A `TrustAdmin` creates it with the `easement_id`, the annual `spending_rate_bps` (a whole number of basis points from 100 to 800), and the restricted `principal_floor_cents` (zero or more). The fund is born `INITIALIZING` with `market_value_cents` zero, `units_outstanding` zero, `fiscal_year` 1, `prior_year_close_mv_cents` zero, and `carryover_allowance_cents` zero. Fund creation is not among the child operational creates of §3.1 — the easement need not be `RECORDED`. Endowment funds can be browsed with filters on `easement_id` and `status`.

The fund's books are an append-only ledger of `EndowmentTransaction` entries, processed strictly in posting order — by `posted_on`, then by `created_at` — and the fund's transaction listing returns entries in that same order, supporting an optional `txn_type` filter. Every posting follows a pinned three-step rounding order. First, the units delta is computed as the posting's absolute `amount_cents` divided by the current `unit_value_cents`, rounded half-up to four decimal places. Second, the aggregates are applied per `txn_type`: a `CONTRIBUTION` adds its units delta to `units_outstanding` and its amount to `market_value_cents`; a `DRAW` subtracts its units delta and its absolute amount; an `INVESTMENT_RETURN` leaves units untouched and adds its signed amount to market value. Third, `unit_value_cents` is recomputed as market value divided by units outstanding, rounded half-up to four decimal places — a step skipped while `units_outstanding` is zero, when the unit value reads null. Before any posting, the unit value is anchored at exactly 100.0000 cents (one dollar), and the first contribution activates the fund from `INITIALIZING` to `ACTIVE` at that anchor. The rounding order is pinned because computing units from an unrounded intermediate unit value — rather than the rounded value carried from the previous posting — yields different fourth-decimal units.

Contributions and returns are `TrustAdmin` postings taking an `amount_cents`. Contributions must be positive amounts, and the first one flips the fund to `ACTIVE`; investment returns are signed — any integer amount, positive, negative, or zero, is accepted — but returns (like draws and the fiscal-year close) require an `ACTIVE` fund — against an `INITIALIZING` fund they are rejected with `ERR_FUND_NOT_ACTIVE` (409). Each posting appends its ledger entry — recording the entry's `fund_id`, `txn_type`, signed `amount_cents`, computed `units` (zero for investment returns), the fund's `fiscal_year` at posting time, and the clock date as `posted_on` — and advances the fund's `version` by one. On `CONTRIBUTION` and `INVESTMENT_RETURN` entries, `purpose` and the three draw-bucket fields read null.

Draws fund the stewardship work itself. A `StewardshipCoordinator` or `TrustBoardReviewer` posts a draw with a positive `amount_cents`, a `purpose` of `MONITORING`, `ENFORCEMENT`, or `GENERAL_STEWARDSHIP`, and the OCC field `expected_fund_version`; a stale version is rejected with `ERR_STALE_FUND_VERSION` (412), and a draw against an `INITIALIZING` fund with `ERR_FUND_NOT_ACTIVE`. The draw amount is then allocated across three buckets in a fixed order. Bucket one is the spending-policy allowance: the remaining allowance is `policy_draw_allowance_cents` less `provisional_draws_ytd_cents`, floored at zero, and `from_policy_allowance_cents` absorbs the draw up to that remainder. Bucket two is excess over the principal floor: `from_excess_cents` absorbs the smaller of the remaining draw amount and the unitized capacity — `market_value_cents` less `principal_floor_cents`, floored at zero — less what the first bucket already absorbed. Whatever still remains after both buckets is principal invasion: it is rejected with `ERR_PRINCIPAL_INVASION_REQUIRES_BOARD` (402) unless the actor is a `TrustBoardReviewer`, and even for the board a draw larger than the fund's entire `market_value_cents` is rejected with `ERR_DRAW_EXCEEDS_AUTHORITY` (402). An authorized invasion is recorded in `from_principal_invasion_cents`; otherwise that field is zero. The posted `DRAW` transaction records all three bucket fields along with its `purpose`, carries an `amount_cents` equal to the negated draw amount, and redeems units under the pinned unitization order; `provisional_draws_ytd_cents` — the running total of absolute draw amounts posted in the current `fiscal_year` — is recomputed, and the fund's `version` advances by one.

Two capacity lenses frame every draw, and they legitimately disagree. `unitized_draw_capacity_cents` is instantaneous: the fund's market value less the principal floor, floored at zero, blind to spending policy. `policy_draw_allowance_cents` is the policy lens: the current-year policy amount — frozen at the last fiscal-year close — plus `carryover_allowance_cents`. In `fiscal_year` 1 both components are zero, so first-year draws draw entirely on the excess bucket. For illustration, a fund with a market value of 500000 cents and a floor of 100000 cents shows 400000 cents of unitized capacity, while immediately after its first close-year its policy allowance might be only 20000 cents; a draw must fit under both ceilings, the allowance capping bucket one and the unitized capacity bounding bucket two.

The fiscal-year close is a `TrustBoardReviewer` act on an `ACTIVE` fund, and its four steps are pinned in order because the draw total feeds the underuse figure while next year's policy feeds nothing yet. Step one determines the policy amount that governed the year just closed — in `fiscal_year` 1 this is zero, because `prior_year_close_mv_cents` starts at zero. Step two computes the year's underuse: the closed year's policy amount plus `carryover_allowance_cents`, less `provisional_draws_ytd_cents`, floored at zero. Step three sets the new `carryover_allowance_cents` to the smaller of that underuse and the closed year's policy amount — capped by the closed year's policy, never by next year's; substituting next year's amount here is the forbidden evaluation order and produces a different carryover whenever market value shrank during the closed year. Step four snapshots `prior_year_close_mv_cents` as the current `market_value_cents`, freezes next year's policy amount as that snapshot multiplied by `spending_rate_bps` and divided by ten thousand, rounded half-up to whole cents, resets `provisional_draws_ytd_cents` to zero, and increments `fiscal_year` by one; the fund's `version` advances by one. From that moment the new `policy_draw_allowance_cents` reads as the freshly frozen policy amount plus the new carryover.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. Request payloads, response content, and side effects for each operation are governed by the narratives in §3; the table below is the addressing and authorization contract only. The test-driving clock endpoint sits outside the `/stewardship` mount.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stewardship/easements` | Create an easement in `DRAFT` | TrustAdmin |
| GET | `/stewardship/easements` | List easements with filters | Any |
| GET | `/stewardship/easements/{easementId}` | Get one easement including computed posture and due date | Any |
| POST | `/stewardship/easements/{easementId}/record` | Record a `DRAFT` easement (requires accepted baseline and active landowner) | TrustAdmin |
| POST | `/stewardship/landowners` | Create the initial `ACTIVE` landowner | TrustAdmin |
| GET | `/stewardship/landowners` | List landowners | Any |
| GET | `/stewardship/landowners/{landownerId}` | Get one landowner | Any |
| POST | `/stewardship/baseline-reports` | Create the easement's single baseline report in `DRAFT` | StewardshipCoordinator |
| GET | `/stewardship/baseline-reports` | List baseline reports | Any |
| GET | `/stewardship/baseline-reports/{baselineReportId}` | Get one baseline report | Any |
| POST | `/stewardship/baseline-reports/{baselineReportId}/submit` | Submit from `DRAFT` or resubmit from `REVISION_REQUESTED` | StewardshipCoordinator |
| POST | `/stewardship/baseline-reports/{baselineReportId}/accept` | Accept a `SUBMITTED` baseline (acceptor must differ from preparer) | TrustBoardReviewer |
| POST | `/stewardship/baseline-reports/{baselineReportId}/request-revision` | Send a `SUBMITTED` baseline back for revision | TrustBoardReviewer |
| POST | `/stewardship/monitoring-visits` | Schedule a monitoring visit with a per-monitor overlap check | StewardshipCoordinator |
| GET | `/stewardship/monitoring-visits` | List monitoring visits | Any |
| GET | `/stewardship/monitoring-visits/{monitoringVisitId}` | Get one monitoring visit | Any |
| POST | `/stewardship/monitoring-visits/{monitoringVisitId}/complete` | Complete a visit (assigned monitor only); updates easement due date and posture | FieldMonitor |
| POST | `/stewardship/monitoring-visits/{monitoringVisitId}/cancel` | Cancel a `SCHEDULED` visit | StewardshipCoordinator |
| POST | `/stewardship/violations` | Open a violation against a `PROHIBITED` or `DISCRETIONARY` matrix cell | StewardshipCoordinator |
| GET | `/stewardship/violations` | List violations | Any |
| GET | `/stewardship/violations/{violationId}` | Get one violation | Any |
| POST | `/stewardship/violations/{violationId}/send-notice` | Serve notice to the current landowner; starts the cure clock | StewardshipCoordinator |
| POST | `/stewardship/violations/{violationId}/start-cure` | Current landowner begins curing | Landowner |
| POST | `/stewardship/violations/{violationId}/resolve` | Verify cure and resolve (verifier must differ from detector) | StewardshipCoordinator |
| POST | `/stewardship/violations/{violationId}/escalate` | Manually escalate a `NOTICE_SENT` violation, spawning enforcement | StewardshipCoordinator |
| GET | `/stewardship/enforcement-actions` | List enforcement actions | Any |
| GET | `/stewardship/enforcement-actions/{enforcementActionId}` | Get one enforcement action | Any |
| POST | `/stewardship/enforcement-actions/{enforcementActionId}/execute` | Board executes the remediation agreement | TrustBoardReviewer |
| POST | `/stewardship/enforcement-actions/{enforcementActionId}/complete` | Verify remediation complete; resolves the linked violation | StewardshipCoordinator |
| POST | `/stewardship/enforcement-actions/{enforcementActionId}/breach` | Declare the agreement breached | TrustBoardReviewer |
| POST | `/stewardship/enforcement-actions/{enforcementActionId}/renegotiate` | Renegotiate a breached agreement back to `PROPOSED` | StewardshipCoordinator |
| POST | `/stewardship/amendment-requests` | Submit an amendment (OCC on easement version; one in flight per easement) | StewardshipCoordinator |
| GET | `/stewardship/amendment-requests` | List amendment requests | Any |
| GET | `/stewardship/amendment-requests/{amendmentRequestId}` | Get one amendment request | Any |
| POST | `/stewardship/amendment-requests/{amendmentRequestId}/start-review` | Move `SUBMITTED` to `STAFF_REVIEW` | StewardshipCoordinator |
| POST | `/stewardship/amendment-requests/{amendmentRequestId}/request-revision` | Move `STAFF_REVIEW` to `REVISION_REQUESTED` | StewardshipCoordinator |
| POST | `/stewardship/amendment-requests/{amendmentRequestId}/resubmit` | Resubmit from `REVISION_REQUESTED` with replacement changes | StewardshipCoordinator |
| POST | `/stewardship/amendment-requests/{amendmentRequestId}/escalate-board` | Move `STAFF_REVIEW` to `BOARD_REVIEW` | StewardshipCoordinator |
| POST | `/stewardship/amendment-requests/{amendmentRequestId}/approve` | Approve (staff lane below materiality 70; board lane from `BOARD_REVIEW`) | StewardshipCoordinator, TrustBoardReviewer |
| POST | `/stewardship/amendment-requests/{amendmentRequestId}/reject` | Reject from `STAFF_REVIEW` or `BOARD_REVIEW` | StewardshipCoordinator, TrustBoardReviewer |
| POST | `/stewardship/amendment-requests/{amendmentRequestId}/withdraw` | Withdraw from any non-terminal state | StewardshipCoordinator |
| POST | `/stewardship/use-authorizations` | Current landowner requests a discretionary use | Landowner |
| GET | `/stewardship/use-authorizations` | List use authorizations | Any |
| GET | `/stewardship/use-authorizations/{useAuthorizationId}` | Get one use authorization | Any |
| POST | `/stewardship/use-authorizations/{useAuthorizationId}/decide` | Approve, approve with conditions, or deny a `REQUESTED` authorization | StewardshipCoordinator |
| POST | `/stewardship/succession-notices` | Current landowner gives notice of transfer; creates the pending successor | Landowner |
| GET | `/stewardship/succession-notices` | List succession notices | Any |
| GET | `/stewardship/succession-notices/{successionNoticeId}` | Get one succession notice | Any |
| POST | `/stewardship/succession-notices/{successionNoticeId}/acknowledge` | Trust acknowledges receipt within the 45-day window | TrustAdmin |
| POST | `/stewardship/succession-notices/{successionNoticeId}/record` | Record the transfer (OCC on easement version); flips current landowner | TrustAdmin |
| POST | `/stewardship/appraisals` | Engage an appraisal; 365-day engagement buffer per appraiser and easement | StewardshipCoordinator |
| GET | `/stewardship/appraisals` | List appraisals | Any |
| GET | `/stewardship/appraisals/{appraisalId}` | Get one appraisal | Any |
| POST | `/stewardship/appraisals/{appraisalId}/deliver` | Engaged appraiser delivers valuations | Appraiser |
| POST | `/stewardship/appraisals/{appraisalId}/certify` | Certify for tax substantiation; computes and freezes the deductible | StewardshipCoordinator |
| POST | `/stewardship/appraisals/{appraisalId}/withdraw` | Withdraw an `ENGAGED` or `DELIVERED` appraisal | StewardshipCoordinator |
| POST | `/stewardship/endowment-funds` | Create the easement's single stewardship endowment | TrustAdmin |
| GET | `/stewardship/endowment-funds` | List endowment funds | Any |
| GET | `/stewardship/endowment-funds/{endowmentFundId}` | Get one fund with all computed fields | Any |
| POST | `/stewardship/endowment-funds/{endowmentFundId}/contributions` | Post a contribution; first contribution activates the fund | TrustAdmin |
| POST | `/stewardship/endowment-funds/{endowmentFundId}/returns` | Post a signed investment return | TrustAdmin |
| POST | `/stewardship/endowment-funds/{endowmentFundId}/draws` | Post a stewardship draw (OCC on fund version; waterfall allocation) | StewardshipCoordinator, TrustBoardReviewer |
| POST | `/stewardship/endowment-funds/{endowmentFundId}/close-year` | Close the fiscal year; freeze next-year policy and compute carryover | TrustBoardReviewer |
| GET | `/stewardship/endowment-funds/{endowmentFundId}/transactions` | List the fund's append-only ledger in posting order | Any |
| POST | `/_clock/set_current_utc` | Set the server's logical clock and run the time-driven sweep | TrustAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows and principles that raise them (§2 and §3); this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_EASEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LANDOWNER_NOT_FOUND` | 404 Not Found |
| `ERR_BASELINE_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_MONITORING_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_AMENDMENT_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_USE_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_ENFORCEMENT_ACTION_NOT_FOUND` | 404 Not Found |
| `ERR_SUCCESSION_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_APPRAISAL_NOT_FOUND` | 404 Not Found |
| `ERR_ENDOWMENT_FUND_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_BASELINE_STATE` | 409 Conflict |
| `ERR_INVALID_VISIT_STATE` | 409 Conflict |
| `ERR_INVALID_VIOLATION_STATE` | 409 Conflict |
| `ERR_INVALID_AMENDMENT_STATE` | 409 Conflict |
| `ERR_INVALID_USE_AUTHORIZATION_STATE` | 409 Conflict |
| `ERR_INVALID_ENFORCEMENT_STATE` | 409 Conflict |
| `ERR_INVALID_NOTICE_STATE` | 409 Conflict |
| `ERR_INVALID_APPRAISAL_STATE` | 409 Conflict |
| `ERR_EASEMENT_NOT_RECORDED` | 409 Conflict |
| `ERR_BASELINE_NOT_ACCEPTED` | 409 Conflict |
| `ERR_OPEN_OBLIGATIONS_EXIST` | 409 Conflict |
| `ERR_FUND_NOT_ACTIVE` | 409 Conflict |
| `ERR_BASELINE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_AMENDMENT_ALREADY_IN_FLIGHT` | 409 Conflict |
| `ERR_FUND_ALREADY_EXISTS` | 409 Conflict |
| `ERR_USE_CURRENTLY_AUTHORIZED` | 409 Conflict |
| `ERR_MONITOR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_APPRAISAL_ENGAGEMENT_OVERLAP` | 409 Conflict |
| `ERR_AMENDMENT_FREEZE_CONFLICT` | 409 Conflict |
| `ERR_INCOMPLETE_BASELINE` | 422 Unprocessable Entity |
| `ERR_USE_NOT_DISCRETIONARY` | 422 Unprocessable Entity |
| `ERR_USE_PERMITTED_NOT_VIOLABLE` | 422 Unprocessable Entity |
| `ERR_VISIT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_NOTICE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SUBSTANTIATION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_NON_POSITIVE_DEDUCTION` | 422 Unprocessable Entity |
| `ERR_APPRAISER_CONFLICT` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_CURRENT_LANDOWNER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_MONITOR` | 403 Forbidden |
| `ERR_NOT_ENGAGED_APPRAISER` | 403 Forbidden |
| `ERR_MATERIALITY_REQUIRES_BOARD` | 403 Forbidden |
| `ERR_DRAW_EXCEEDS_AUTHORITY` | 402 Payment Required |
| `ERR_PRINCIPAL_INVASION_REQUIRES_BOARD` | 402 Payment Required |
| `ERR_STALE_EASEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FUND_VERSION` | 412 Precondition Failed |





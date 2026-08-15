# School Safety Drills API — Product Requirements Document

## 1. Introduction

School districts operate under statutory mandates that require campuses to conduct a minimum number of safety drills per academic year — fire drills, lockdown drills, evacuation drills, shelter-in-place drills, and earthquake drills — with documented evidence that each drill met timing standards and that every student was accounted for. Districts must also maintain current emergency operations plans, up-to-date site floor-plan documents, and active coordination with first-responder agencies. Compliance reporting to the state depends on accurate, auditable records of all these activities.

This document specifies the requirements for the School Safety Drills API, a system that manages the full lifecycle of drill scheduling, execution, accountability, after-action review, corrective action tracking, and statutory compliance reporting for every campus in a district. The system serves district safety coordinators who configure requirements and approve plans, site-level safety officers who schedule and execute drills, principals who adjudicate after-action reviews, first responders who record walkthrough findings, and state auditors who accept or reject compliance reports. Every workflow is gated by role, guarded by optimistic concurrency where staleness matters, and reconciled continuously so that site-level compliance posture always reflects the latest drill outcomes and corrective-action status.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API is expected to carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying the operational capacity in which that user acts. Of the two, only `X-User-Role` is strictly enforced: the `X-User-ID` header may be absent or blank, in which case the request still proceeds and any user-id field recorded for it is stored as null. The system recognizes five roles, spelled exactly as follows: `DistrictSafetyCoordinator`, `SchoolSafetyOfficer`, `Principal`, `FirstResponder`, and `StateAuditor`.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` on an EmergencyOperationsPlan or AfterActionReview at submit time, as `conducted_by_user_id` on a DrillEvent at start time, as `decided_by_user_id` on an AfterActionReview or ComplianceReport at decide time, or as `verified_by_user_id` on a CorrectiveAction at verify time — but it does not compare the value to any entity's `id` for ownership purposes. Because a missing or blank `X-User-ID` is treated as null, a decide request carried out with no `X-User-ID` against a review whose `submitted_by_user_id` is also null counts as self-approval and is rejected.

A request missing a valid `X-User-Role` header, or carrying a role value not among the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed as authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). These two checks are evaluated first, before any existence, validation, state, or business-rule checks, on every endpoint without exception.

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

List endpoints accept two query parameters for pagination. The `limit` parameter controls the maximum number of items returned in a single response; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter controls how many items are skipped before the first returned item; it defaults to 0. A `limit` or `offset` value that is not an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_VALIDATION`.

All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified; because many resources can share the same logical timestamp, ties on `created_at` are broken by creation (insertion) order. The `meta` object of every list response includes four fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

Beyond the drill-list filters described in Section 3.4, list endpoints accept optional equality-filter query parameters: the drill-requirement list filters by `drill_type`; the emergency-operations-plan, site-plan-document, roster-entry, corrective-action, and compliance-report lists filter by `status`; the walkthrough list filters by `status` and `agency`; and the accommodation-plan list filters by `status` and `student_ref`. Any date-valued filter parameter that is not a valid ISO 8601 date is rejected with `ERR_VALIDATION`.

### 2.4. Common Resource Properties

Every entity in the system carries a standard set of system-managed fields. The `id` is a server-generated UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation to the resource, and at creation `created_at` and `updated_at` are identical. The `version` field is an integer that starts at 1 on creation and increments by exactly 1 on every mutation. All eleven entity types — SchoolSite, DrillTypeRequirement, EmergencyOperationsPlan, SitePlanDocument, FirstResponderWalkthrough, DrillEvent, RosterEntry, AfterActionReview, CorrectiveAction, AccommodationPlan, and ComplianceReport — carry all four common fields.

When a side effect causes a resource to be mutated (for example, a superseded SitePlanDocument or a ComplianceReport transitioning to `STALE`), that resource's `updated_at` is refreshed and its `version` is incremented, even though the mutation was triggered indirectly.

### 2.5. Logical Clock and Date Semantics

The system does not use wall-clock time — the sole exception is the informational `api_request_timestamp` in the response `meta`, which reflects the server's real wall clock and feeds no comparison. A logical clock governs all date and timestamp comparisons and stamps every entity timestamp (`created_at`, `updated_at`, `actual_start_at`, `all_clear_at`, and the like). At server startup, before any clock-advance call, the logical clock reads 2026-08-01T00:00:00Z. A `DistrictSafetyCoordinator` may advance the logical clock by supplying a `to_iso8601` timestamp; the logical clock never falls back to wall-clock time. Supplying a `to_iso8601` earlier than the current logical-clock reading is rejected with `ERR_VALIDATION`; supplying a timestamp equal to the current reading is accepted and still fires the sweep. The logical date ("logical today") is the calendar date portion of the logical clock.

Advancing the logical clock fires a system sweep with these effects, applied in a single pass: every DrillEvent in `SCHEDULED` or `IN_PROGRESS` status whose `scheduled_date` falls before logical today transitions to `MISSED`; every FirstResponderWalkthrough in `SCHEDULED` status whose `scheduled_date` falls before logical today transitions to `MISSED`; every SitePlanDocument in `CURRENT` status whose `review_by_date` falls before logical today transitions to `EXPIRED`; every EmergencyOperationsPlan in `ACTIVE` status whose `review_due_date` falls before logical today transitions to `EXPIRED`; and every CorrectiveAction whose `is_overdue` flag needs flipping is recomputed, along with each site's `compliance_posture`.

All date comparisons in the system — academic year boundaries, report period windows, spacing gaps, walkthrough currency, review-by expiry — operate at day granularity using this logical date.

### 2.6. Nested Resource Retrieval

Several endpoints address resources nested under a parent via URL path, such as listing roster entries for a drill or corrective actions for a review. For any request whose path contains multiple resource identifiers, the system validates existence from left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before any subsequent validation occurs. Body-referenced foreign keys — such as `site_id` on a creation payload — must also reference an existing resource; a nonexistent reference is rejected with `ERR_NOT_FOUND`.

### 2.7. Optimistic Concurrency Control

The update endpoint for a DrillTypeRequirement — the only OCC-guarded endpoint in the system — requires the client to include `expected_requirement_version` as a non-optional field in the request body. This field must carry the value of the requirement's `version` as the client last observed it. If another writer has since modified the requirement, advancing its `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a statutory configuration it has not observed. No other endpoint in the system takes a version field.

### 2.8. Precision and Rounding

All evacuation timing is measured and stored as integer seconds. The unannounced-drill allowance is computed using a ceiling operation: 25 percent of the target, rounded up to the nearest whole second. The per-type compliance ratio used in the overall score is rounded half-up to 4 decimal places before averaging; the final score is rounded half-up to 1 decimal place. All counts (drill counters, roster counters, corrective-action counters, recommendation counts) are integers.

### 2.9. Validation Priority Ordering

When multiple validation rules apply to a single request, the system evaluates them in a strict priority order, and the first failing rule determines the error response. The order is: (1) authentication — the `X-User-Role` header must be present and carry a declared role, else `ERR_UNAUTHENTICATED`; (2) authorization — the role must be permitted on this endpoint, else `ERR_FORBIDDEN`; (3) existence — path ids and body-referenced foreign keys must exist, validated left-to-right, else `ERR_NOT_FOUND`; (4) input validation — required fields present (a required string field whose value is empty or whitespace-only counts as missing), types correct, enum members valid, date and datetime formats valid, unknown top-level fields rejected, and conditional requirements enforced (such as `return_reason` required when `decision` is `RETURN`), else `ERR_VALIDATION`; (5) state validity — the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE`; (6) safety gates — active-EOP, accommodation-plan, pickup-verification, and roster-completeness gates, each with its own error ID; (7) temporal gates — academic-year containment and day-of-drill checks; (8) referential gates — site-plan currency, walkthrough currency, and requirement-configuration checks; (9) uniqueness and conflict constraints — duplicate requirements, drill overlaps, walkthrough-drill date conflicts, duplicate roster entries, duplicate reviews, report period overlaps, and self-approval; and (10) OCC stale-version rejection. Within priority 8, the three referential checks are evaluated in pinned order: site-plan currency first, then walkthrough currency, then requirement configuration.

## 3. Business Logic & Workflows

### 3.1. Campus Onboarding and Statutory Configuration

A `DistrictSafetyCoordinator` begins by creating a **SchoolSite**, providing a `name` for the campus, an `enrollment_count` (a non-negative integer, purely informational and feeding no gate), and the academic year boundaries `academic_year_start` and `academic_year_end`. The end date must not precede the start date; a violation is rejected with `ERR_VALIDATION`. Upon creation the site's `compliance_posture` is set to `ON_TRACK` and all four drill counters — `drills_scheduled_count`, `drills_completed_count`, `drills_missed_count`, and `drills_cancelled_count` — initialize to zero.

With the campus established, the coordinator configures **DrillTypeRequirement** entries, one per drill type. Each requirement specifies the `site_id` it applies to, the `drill_type` (one of `FIRE`, `LOCKDOWN`, `EVACUATION`, `SHELTER_IN_PLACE`, or `EARTHQUAKE`), the `required_per_year` count (at least 1), the `min_spacing_days` between consecutive completed drills of that type (at least 0), the `target_evac_seconds` benchmark (at least 1), and optionally `notes` for a statutory citation. Only one requirement may exist per campus and drill type combination; a duplicate creation is rejected with `ERR_REQUIREMENT_EXISTS`.

Creating or updating a requirement has system-wide ripple effects: the site's `compliance_posture` is recomputed, and every ComplianceReport at that site still in `DRAFT` status transitions to `STALE`, since the statutory baseline has shifted. An update may change any subset of `required_per_year`, `min_spacing_days`, `target_evac_seconds`, and `notes`; `site_id` and `drill_type` are immutable, and passing them in an update body is rejected as an unknown field with `ERR_VALIDATION`. Updating a requirement additionally requires OCC — the request must carry `expected_requirement_version` matching the requirement's current `version`, else the update is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful update increments the requirement's `version` by 1 and refreshes its `updated_at`, even when the payload changes no field value.

### 3.2. Site Plan Documents and First-Responder Walkthroughs

Before any EmergencyOperationsPlan can be submitted, two prerequisites must be in place at the campus: a current site plan document and a recent first-responder walkthrough.

A `SchoolSafetyOfficer` publishes a **SitePlanDocument** by providing the `site_id`, a `document_title`, the `issued_on` date, a `review_by_date` that must be later than logical today (otherwise `ERR_VALIDATION`), and `coverage_tags` — a subset of `FLOOR_PLANS`, `ACCESS_POINTS`, `UTILITY_SHUTOFFS`, and `ASSEMBLY_AREAS` that must include both `FLOOR_PLANS` and `ACCESS_POINTS` (omission of either is rejected with `ERR_INCOMPLETE_COVERAGE`, HTTP 400). Within creation-time input validation these checks land in a pinned order: an unrecognized coverage-tag value is rejected with `ERR_VALIDATION` first, the `FLOOR_PLANS`/`ACCESS_POINTS` subset rule is evaluated next (`ERR_INCOMPLETE_COVERAGE`), and the later-than-logical-today rule on `review_by_date` is evaluated last. Upon creation the document's `status` is set to `CURRENT`. If a prior document at the same site was `CURRENT`, that prior document transitions to `SUPERSEDED` — its `updated_at` refreshes and its `version` increments by 1.

Independently, the officer schedules a **FirstResponderWalkthrough**, specifying the `site_id`, the responding `agency` (`FIRE`, `POLICE`, or `EMS`), and a `scheduled_date`. A walkthrough may not share a calendar date with any drill at the same site that is in `SCHEDULED` or `IN_PROGRESS` status — this is a whole-day exclusion checked in both directions, so scheduling a walkthrough on a drill day is rejected with `ERR_WALKTHROUGH_DRILL_CONFLICT`, and conversely scheduling a drill on a walkthrough's `scheduled_date` (when the walkthrough is `SCHEDULED`) is likewise rejected. The walkthrough begins in `SCHEDULED` status.

A `FirstResponder` records completion by supplying the `completed_date`, a `findings_summary`, and a `recommendations_count` (a non-negative integer). The completed date must not precede the `scheduled_date` and must not be later than logical today; either violation is `ERR_VALIDATION`. Completion moves the walkthrough from `SCHEDULED` to `COMPLETED`.

When the system clock sweep fires and logical today passes a `SCHEDULED` walkthrough's `scheduled_date`, the walkthrough transitions to `MISSED` — a terminal state. Similarly, when logical today passes a `CURRENT` SitePlanDocument's `review_by_date`, the document transitions to `EXPIRED` (terminal), and from that point the campus no longer satisfies the site-plan gate for EOP submission until a new document is published.

### 3.3. Emergency Operations Plan Lifecycle

A `SchoolSafetyOfficer` drafts an **EmergencyOperationsPlan** by providing the `site_id`, a `title`, a `plan_version_label` (an author-assigned label such as "v2026.1"), a `content_summary` describing procedures, and a `review_due_date` after which the plan must be reviewed. The plan begins in `DRAFT` status.

When the officer submits the plan — transitioning it from `DRAFT` to `SUBMITTED` — the system enforces two referential gates, evaluated in pinned order: first, the site must have a SitePlanDocument in `CURRENT` status (else `ERR_SITE_PLAN_REQUIRED`, HTTP 409); second, the site must have a FirstResponderWalkthrough in `COMPLETED` status whose `completed_date` falls within the trailing 365-day window ending at logical today, inclusive of the boundary (a walkthrough completed exactly 365 days before today is eligible; else `ERR_WALKTHROUGH_REQUIRED`, HTTP 409). On successful submit, the system records `submitted_by_user_id` from the `X-User-ID` header.

A `DistrictSafetyCoordinator` then decides the plan's fate. The decide request carries a `decision` field. If the decision is `APPROVE`, the plan transitions from `SUBMITTED` to `APPROVED`. If the decision is `RETURN`, the plan transitions from `SUBMITTED` to `RETURNED` — but a `return_reason` must be present in the request (else `ERR_VALIDATION`), and the provided reason is recorded on the plan. A returned plan may be resubmitted: the submit endpoint accepts both `DRAFT` and `RETURNED` plans, and resubmission from `RETURNED` clears the previously recorded `return_reason` while again enforcing both the site-plan and walkthrough gates.

Activation is the final step: a `DistrictSafetyCoordinator` activates an `APPROVED` plan, moving it to `ACTIVE`. Activation cascades — any other plan at the same site currently in `ACTIVE` status transitions to `SUPERSEDED` (with its `updated_at` refreshed and `version` incremented), and the newly activated plan's `activated_at` is stamped with the logical timestamp.

The system clock sweep handles expiry: when logical today passes an `ACTIVE` plan's `review_due_date`, the plan transitions to `EXPIRED` (terminal). Once no plan remains `ACTIVE` at a site, the drill-start gate `ERR_NO_ACTIVE_EOP` begins applying.

### 3.4. Drill Scheduling and Execution

A `SchoolSafetyOfficer` schedules a **DrillEvent** by specifying the `site_id`, the `drill_type`, a `scheduled_date` that must lie within the site's academic year (bounded by `academic_year_start` and `academic_year_end`, inclusive; a date outside is rejected with `ERR_OUTSIDE_ACADEMIC_YEAR`), a `scheduled_start_time` in 24-hour HH:MM format, and a `duration_minutes` (at least 1) defining the planned length. An optional `announcement_mode` may be set to `ANNOUNCED` or `UNANNOUNCED`; when omitted it defaults to `ANNOUNCED`.

Two preconditions guard drill creation. First, a DrillTypeRequirement must exist for the combination of site and drill type; otherwise the creation is rejected with `ERR_REQUIREMENT_NOT_CONFIGURED`. Second, the drill's half-open time interval — beginning at `scheduled_start_time` and extending `duration_minutes` — must not overlap any other drill at the same site that is in `SCHEDULED` or `IN_PROGRESS` status. Intervals are compared as absolute date-and-time intervals, so a drill whose duration carries it past midnight can overlap a drill scheduled on the following calendar date. Two drills whose intervals merely touch (one ends exactly when the other begins) do not overlap. An actual overlap is rejected with `ERR_DRILL_OVERLAP`. Additionally, the `scheduled_date` must not coincide with the `scheduled_date` of any `SCHEDULED` walkthrough at the same site — the whole-day exclusion enforced as `ERR_WALKTHROUGH_DRILL_CONFLICT`.

Upon creation the drill's `status` is set to `SCHEDULED`, all roster counters (`roster_total`, `unaccounted_count`, `accounted_count`, `released_count`) initialize to zero, the site's drill counters recompute, and any ComplianceReport at the site in `DRAFT` status whose period contains the drill's `scheduled_date` transitions to `STALE`.

On the day of the drill, the officer starts it. Starting requires that logical today equals the drill's `scheduled_date` (else `ERR_DRILL_NOT_TODAY`) and that the site has an EmergencyOperationsPlan in `ACTIVE` status (else `ERR_NO_ACTIVE_EOP`). Starting moves the drill from `SCHEDULED` to `IN_PROGRESS`, stamps `actual_start_at` with the logical timestamp, and records `conducted_by_user_id` from the `X-User-ID` header.

The drill list for a site supports filtering by `status` and `drill_type`, as well as date-range filtering via `scheduled_date_from` and `scheduled_date_to` to narrow results to drills whose `scheduled_date` falls within the supplied bounds.

Cancellation is available while a drill is `SCHEDULED`. Cancelling moves it to `CANCELLED` (terminal); the request accepts an optional `reason` string, which is validated when present but not persisted on the drill. The site's drill counters recompute, and any covering `DRAFT` ComplianceReport transitions to `STALE`.

The clock sweep also guards drills: if logical today passes a drill's `scheduled_date` while the drill is still `SCHEDULED` or `IN_PROGRESS`, the drill transitions to `MISSED`. Both variants — never started, or started but never completed — produce the same side effects: site drill counters recompute, `compliance_posture` recomputes (a `MISSED` drill in the current academic year forces at least `AT_RISK`), and covering `DRAFT` reports transition to `STALE`.

### 3.5. Roster Accountability and Reunification

While a drill is `SCHEDULED` or `IN_PROGRESS`, the officer builds its accountability roster. Adding a **RosterEntry** to a drill requires the `student_ref` — an opaque student identifier used by the school — and an optional `accommodation_required` flag that defaults to `false`. Only one roster entry per student per drill is permitted; a duplicate `student_ref` on the same drill is rejected with `ERR_DUPLICATE_ROSTER_ENTRY`. When `accommodation_required` is `true`, an **AccommodationPlan** in `ACTIVE` status must exist for that site and student; absence of one is rejected with `ERR_ACCOMMODATION_MISSING`. Each new roster entry begins in `UNACCOUNTED` status, and the drill's roster counters recompute.

During execution — while the drill is `IN_PROGRESS` — the officer marks students accounted for. Marking a roster entry moves it from `UNACCOUNTED` to `ACCOUNTED`, stamps `accounted_at` with the logical timestamp, and recomputes the drill's roster counters. If a mark was made in error, the officer may undo it: unaccounting moves the entry from `ACCOUNTED` back to `UNACCOUNTED` and clears `accounted_at`, with the counters recomputing. An optional `reason` may accompany the undo. Both account and unaccount require the parent drill to be `IN_PROGRESS`; attempting either on a drill in any other status is rejected with `ERR_INVALID_STATE`.

The reunification release moves an entry from `ACCOUNTED` to `RELEASED` — the terminal roster state. The release request must include `guardian_name` (the receiving guardian's name) and `released_to_verified`, a boolean confirming identity verification. Releasing with `released_to_verified` not set to `true` is rejected with `ERR_PICKUP_NOT_VERIFIED`. A successful release stamps `released_at` with the logical timestamp and recomputes the drill's roster counters. Release, like account and unaccount, requires the parent drill to be `IN_PROGRESS`.

### 3.6. Drill Completion and Timing Assessment

Completing a drill — moving it from `IN_PROGRESS` to `COMPLETED` — requires every roster entry to be resolved: each must be in `ACCOUNTED` or `RELEASED` status. If any entry remains `UNACCOUNTED`, the completion is rejected with `ERR_ROSTER_INCOMPLETE`. This check is vacuously satisfied when the roster is empty. The officer may attach `completion_notes` at this point.

Completion triggers the evacuation timing assessment. The system stamps `all_clear_at` with the logical timestamp and computes two timing values. First, `provisional_evac_seconds` is the raw elapsed time from `actual_start_at` to `all_clear_at` in integer seconds, with any sub-second fraction truncated toward zero. Second, the system determines `last_accountability_at` — the maximum timestamp across all roster entries, using each entry's `released_at` if the entry is `RELEASED` and its `accounted_at` otherwise. When the roster is empty, `last_accountability_at` is set equal to `all_clear_at`. The `official_evac_seconds` is then the elapsed time from `actual_start_at` to `last_accountability_at` in integer seconds, again truncated toward zero; when the roster is empty it equals `provisional_evac_seconds`.

The assessment then evaluates two met-target flags. The standard flag, `met_target_standard`, is true when `official_evac_seconds` is less than or equal to the `target_evac_seconds` from the DrillTypeRequirement matching the drill's site and type. The adjusted flag, `met_target_adjusted`, applies only when the drill's `announcement_mode` is `UNANNOUNCED`: in that case the target is increased by a 25 percent allowance — computed as `target_evac_seconds` multiplied by 0.25, with the result rounded up to the nearest whole second — and `met_target_adjusted` is true when `official_evac_seconds` is less than or equal to the adjusted target. When `announcement_mode` is `ANNOUNCED`, `met_target_adjusted` mirrors `met_target_standard` exactly.

Completion also cascades: the site's drill counters recompute (this drill moves from the scheduled bucket to the completed bucket), `compliance_posture` recomputes, and every ComplianceReport at the site in `DRAFT` status whose period contains the drill's `scheduled_date` transitions to `STALE`.

### 3.7. After-Action Review and Corrective Actions

Once a drill is `COMPLETED`, the officer opens its **AfterActionReview** — at most one review per drill. Creating a review requires `findings_summary` (the review narrative), an `overall_rating` (one of `EXCEEDS`, `MEETS`, `NEEDS_IMPROVEMENT`, or `UNSATISFACTORY`), and an `evacuation_assessment` (one of `MET_STANDARD`, `MET_ADJUSTED`, or `NOT_MET`). A second review on the same drill is rejected with `ERR_AAR_EXISTS`. The review begins in `DRAFT` status with `ca_total_count` and `ca_verified_count` both at zero.

The officer submits the review — from `DRAFT` or from `RETURNED` — moving it to `SUBMITTED` and recording `submitted_by_user_id`. Resubmission from `RETURNED` clears the prior `return_reason`.

A `Principal` decides the review. The decide request carries a `decision` and, when the decision is `RETURN`, a `return_reason`. The decider's `X-User-ID` must differ from the review's `submitted_by_user_id` — a self-approval is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. An `ACCEPT` decision moves the review from `SUBMITTED` to `ACCEPTED` and records `decided_by_user_id`. A `RETURN` decision moves it to `RETURNED`, records both `decided_by_user_id` and `return_reason`, and requires `return_reason` to be present (else `ERR_VALIDATION`).

Corrective actions are opened on an `ACCEPTED` review. Creating a **CorrectiveAction** requires `description`, `priority` (one of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`), a `due_date`, and an `assignee_name`. Attempting to create a corrective action on a review not in `ACCEPTED` status is rejected with `ERR_INVALID_STATE`. The action begins in `OPEN` status, the review's `ca_total_count` increments, and the site's `compliance_posture` recomputes.

The officer submits verification by providing an `evidence_note`, moving the action from `OPEN` (or `REOPENED`) to `PENDING_VERIFICATION`. The coordinator then decides: a `decision` of `VERIFY` moves the action to `VERIFIED` (terminal), records `verified_by_user_id`, and increments the review's `ca_verified_count`. An optional `note` may accompany the verify decision. When a verification causes an `ACCEPTED` review to have `ca_total_count` at least 1 and every one of its corrective actions in `VERIFIED` status, the review auto-transitions from `ACCEPTED` to `CLOSED`. That closure cascades further: the parent drill (in `COMPLETED` status) transitions to `CLOSED`, and the site's drill counters and `compliance_posture` recompute. A `decision` of `REOPEN` moves the action from `PENDING_VERIFICATION` to `REOPENED`, and the site's `compliance_posture` recomputes (the action remains non-verified and may be overdue).

Every corrective action carries a computed `is_overdue` flag: true when logical today has passed the action's `due_date` and the action's `status` is not `VERIFIED`.

### 3.8. Accommodation Plans

A `SchoolSafetyOfficer` creates an **AccommodationPlan** for a student with special needs by providing the `site_id`, the `student_ref`, a `need_type` (one of `MOBILITY`, `VISUAL`, `AUDITORY`, `SENSORY`, or `COGNITIVE`), `instructions` for staff, and a `review_by_date` for the next review (informational only). The plan begins in `ACTIVE` status.

Deactivating an accommodation plan moves it from `ACTIVE` to `INACTIVE` (terminal). From that point, the roster-entry gate `ERR_ACCOMMODATION_MISSING` applies to subsequent roster additions for that site and student — any new roster entry flagged `accommodation_required` as `true` will be rejected once no `ACTIVE` plan remains for the pair.

### 3.9. Compliance Reporting

A `DistrictSafetyCoordinator` generates a **ComplianceReport** by specifying the `site_id`, a `period_start`, and a `period_end` — both inclusive closed-interval boundaries, with `period_end` not preceding `period_start` (else `ERR_VALIDATION`). Generation requires at least one DrillTypeRequirement configured at the site; otherwise the request is rejected with `ERR_REQUIREMENT_NOT_CONFIGURED`. Report periods may not overlap: the closed interval from `period_start` through `period_end` must not intersect any other report at the same site that is in `DRAFT`, `STALE`, `SUBMITTED`, or `ACCEPTED` status. Two periods sharing even a single boundary date do overlap. A violation is rejected with `ERR_REPORT_PERIOD_OVERLAP`.

Upon generation the report's `status` is set to `DRAFT` and `snapshot_generated_at` is stamped with the logical timestamp. The system computes the statutory attainment snapshot: for each DrillTypeRequirement configured at the site, it counts the drills with matching `drill_type`, in `COMPLETED` or `CLOSED` status, whose `scheduled_date` falls within the closed interval from `period_start` through `period_end`. This count is the `completed_count` for that type. Each entry in `type_attainments` records the `drill_type`, the `required_count` (from `required_per_year`), the `completed_count`, a `spacing_compliant` flag, an `attainment_count_only` flag, and an `attainment_strict` flag. Entries appear in requirement-creation order: requirements are walked in `created_at` ascending order, with ties broken by creation order.

The `attainment_count_only` flag is true when the completed count is at least the required count. The `spacing_compliant` flag checks ordering: the counted drills are ordered by `scheduled_date` ascending (with ties broken by `created_at` ascending, and any remaining ties broken by creation order), and for every consecutive pair the number of whole calendar days between their scheduled dates must be at least the requirement's `min_spacing_days`. When fewer than 2 drills are counted, spacing compliance is vacuously true. The `attainment_strict` flag is true when both the count threshold is met and spacing is compliant.

The report also computes two overall flags. `overall_compliant_count_only` is the conjunction of `attainment_count_only` across all configured types — true only when every configured type meets its count threshold. `overall_compliant_strict` is the conjunction of `attainment_strict` across all configured types — true only when every type meets both count and spacing.

The `overall_score_pct` is a composite score. For each configured type, a per-type ratio is computed as the lesser of 1.0 and the quotient of completed count divided by required count, rounded half-up to 4 decimal places. These rounded ratios are then summed and divided by the number of configured types, the result multiplied by 100, and the product rounded half-up to 1 decimal place. The per-type ratios must be rounded to 4 decimal places before averaging; averaging raw ratios and rounding once at the end produces a different, non-compliant result.

Reports are living documents subject to staleness. A report in `DRAFT` transitions to `STALE` whenever any drill at the same site whose `scheduled_date` lies within the report's period is created or changes status after `snapshot_generated_at`, or whenever any DrillTypeRequirement at the site is created or updated.

A `DistrictSafetyCoordinator` submits a `DRAFT` report to the state, moving it to `SUBMITTED` and stamping `submitted_at` with the logical timestamp. A `StateAuditor` then decides: an `ACCEPT` decision moves the report to `ACCEPTED` (terminal), while a `REJECT` decision moves it to `REJECTED`. Both decisions record `decided_by_user_id` and an optional `auditor_comment`.

Regeneration is available from either `STALE` or `REJECTED`: the coordinator regenerates the report, which recomputes the full snapshot (statutory attainment and overall score), stamps `snapshot_generated_at` anew, and moves the report back to `DRAFT`. When regenerating from `REJECTED`, the `auditor_comment` and `decided_by_user_id` are cleared. Regeneration does not touch `submitted_at` — a report regenerated from `REJECTED` retains the `submitted_at` stamped by its prior submission until it is submitted again.

### 3.10. Compliance Posture Derivation

Each site's `compliance_posture` is a derived field recomputed on every drill status transition, corrective-action creation, verify, or reopen, requirement creation or update, and clock sweep. The derivation follows a three-tier threshold.

First, count the overdue corrective actions reachable through the site: every CorrectiveAction whose chain leads back to this site (via the action's `aar_id` to the review's `drill_event_id` to the drill's `site_id`), whose `status` is not `VERIFIED`, and whose `due_date` falls before logical today.

The posture is `NON_COMPLIANT` when either of two conditions holds: logical today has passed the site's `academic_year_end` and any configured requirement's completed-drill count for the current academic year (drills in `COMPLETED` or `CLOSED` status with `scheduled_date` inside the academic year) falls below that requirement's `required_per_year`; or the number of overdue corrective actions reaches 3 or more.

Otherwise, the posture is `AT_RISK` when either of two conditions holds: any drill at the site has `MISSED` status with a `scheduled_date` inside the current academic year; or at least 1 overdue corrective action exists.

If neither `NON_COMPLIANT` nor `AT_RISK` conditions are met, the posture is `ON_TRACK`.

### 3.11. Drill Counter Reconciliation

The four drill counters on each SchoolSite are continuously reconciled. The scope is all DrillEvent rows at the site whose `scheduled_date` falls within the current academic year (between `academic_year_start` and `academic_year_end`, inclusive). `drills_scheduled_count` counts drills in `SCHEDULED` or `IN_PROGRESS` status. `drills_completed_count` counts drills in `COMPLETED` or `CLOSED` status. `drills_missed_count` counts drills in `MISSED` status. `drills_cancelled_count` counts drills in `CANCELLED` status. The four counters always sum to the total number of drills ever created in scope — no delete endpoint exists, so scheduling then cancelling moves one unit between buckets without drift. Reconciliation fires on drill create, start, complete, cancel, the auto-missed sweep, and the completed-to-closed transition.

### 3.12. Roster Counter Reconciliation

The roster counters on each DrillEvent are similarly reconciled on every roster entry create, account, unaccount, or release. `roster_total` counts all roster entries for the drill. `unaccounted_count`, `accounted_count`, and `released_count` count entries in `UNACCOUNTED`, `ACCOUNTED`, and `RELEASED` respectively. The invariant `unaccounted_count` plus `accounted_count` plus `released_count` always equals `roster_total` holds at all times. An account followed by its compensating unaccount returns every bucket to its prior value — `accounted_at` is cleared and no count drifts.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`. Operations that modify an existing resource — including all state transitions — return `200 OK`. Requests to a path defined below with an unsupported method, or to no defined path at all, are rejected with `ERR_NOT_FOUND` (HTTP 404); this routing-level rejection happens before any header check, so it applies even when authentication headers are absent.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock and fire the system sweep | DistrictSafetyCoordinator |
| POST | `/sites` | Create a school campus | DistrictSafetyCoordinator |
| GET | `/sites/{id}` | Fetch one site including computed posture and counters | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/drill-requirements` | Configure the statutory requirement for one drill type at a site | DistrictSafetyCoordinator |
| GET | `/sites/{id}/drill-requirements` | List drill requirements configured for a site | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| PUT | `/drill-requirements/{id}` | Update a drill requirement (OCC-guarded) | DistrictSafetyCoordinator |
| POST | `/emergency-operations-plans` | Create a plan in DRAFT | SchoolSafetyOfficer |
| GET | `/sites/{id}/emergency-operations-plans` | List plans for a site | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/emergency-operations-plans/{id}/submit` | Submit a DRAFT or RETURNED plan for district approval | SchoolSafetyOfficer |
| POST | `/emergency-operations-plans/{id}/decide` | District decision on a SUBMITTED plan | DistrictSafetyCoordinator |
| POST | `/emergency-operations-plans/{id}/activate` | Activate an APPROVED plan; supersedes the site's currently ACTIVE plan | DistrictSafetyCoordinator |
| POST | `/site-plan-documents` | Publish a floor-plan/access document; supersedes the site's CURRENT document | SchoolSafetyOfficer |
| GET | `/sites/{id}/site-plan-documents` | List site plan documents for a site | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/walkthroughs` | Schedule a first-responder site walkthrough | SchoolSafetyOfficer |
| GET | `/sites/{id}/walkthroughs` | List walkthroughs for a site | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/walkthroughs/{id}/complete` | Record a completed walkthrough | FirstResponder |
| POST | `/drill-events` | Schedule a drill | SchoolSafetyOfficer |
| GET | `/sites/{id}/drill-events` | List drills for a site with filters | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| GET | `/drill-events/{id}` | Fetch one drill including computed timing fields and roster counters | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/drill-events/{id}/start` | Begin execution of a scheduled drill | SchoolSafetyOfficer |
| POST | `/drill-events/{id}/complete` | Close out execution: all-clear timestamp + timing assessment | SchoolSafetyOfficer |
| POST | `/drill-events/{id}/cancel` | Cancel a scheduled drill | SchoolSafetyOfficer |
| POST | `/drill-events/{id}/roster-entries` | Add a student to a drill's accountability roster | SchoolSafetyOfficer |
| GET | `/drill-events/{id}/roster-entries` | List roster entries for a drill | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/roster-entries/{id}/account` | Mark a student accounted-for at the assembly area | SchoolSafetyOfficer |
| POST | `/roster-entries/{id}/unaccount` | Undo a mistaken accountability mark | SchoolSafetyOfficer |
| POST | `/roster-entries/{id}/release` | Reunification release to a verified guardian | SchoolSafetyOfficer |
| POST | `/drill-events/{id}/after-action-reviews` | Open the after-action review for a COMPLETED drill | SchoolSafetyOfficer |
| GET | `/drill-events/{id}/after-action-reviews` | List reviews for a drill | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| GET | `/after-action-reviews/{id}` | Fetch one review including corrective-action counters | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/after-action-reviews/{id}/submit` | Submit a DRAFT or RETURNED review to the principal | SchoolSafetyOfficer |
| POST | `/after-action-reviews/{id}/decide` | Principal accepts or returns a submitted review | Principal |
| POST | `/after-action-reviews/{id}/corrective-actions` | Open a corrective action on an ACCEPTED review | SchoolSafetyOfficer |
| GET | `/after-action-reviews/{id}/corrective-actions` | List corrective actions for a review | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/corrective-actions/{id}/submit-verification` | Mark remediation done and request district verification | SchoolSafetyOfficer |
| POST | `/corrective-actions/{id}/verify` | District verifies or reopens a submitted corrective action | DistrictSafetyCoordinator |
| POST | `/accommodation-plans` | Create a special-needs drill accommodation plan | SchoolSafetyOfficer |
| GET | `/sites/{id}/accommodation-plans` | List accommodation plans for a site | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/accommodation-plans/{id}/deactivate` | Deactivate an accommodation plan | SchoolSafetyOfficer |
| POST | `/compliance-reports` | Generate a compliance report snapshot for a closed-interval period | DistrictSafetyCoordinator |
| GET | `/sites/{id}/compliance-reports` | List compliance reports for a site | DistrictSafetyCoordinator, SchoolSafetyOfficer, Principal, FirstResponder, StateAuditor |
| POST | `/compliance-reports/{id}/submit` | Submit a DRAFT report to the state | DistrictSafetyCoordinator |
| POST | `/compliance-reports/{id}/decide` | State auditor accepts or rejects a submitted report | StateAuditor |
| POST | `/compliance-reports/{id}/regenerate` | Recompute a STALE or REJECTED report's snapshot back into DRAFT | DistrictSafetyCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INCOMPLETE_COVERAGE` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NO_ACTIVE_EOP` | 409 |
| `ERR_ACCOMMODATION_MISSING` | 409 |
| `ERR_PICKUP_NOT_VERIFIED` | 409 |
| `ERR_ROSTER_INCOMPLETE` | 409 |
| `ERR_OUTSIDE_ACADEMIC_YEAR` | 409 |
| `ERR_DRILL_NOT_TODAY` | 409 |
| `ERR_WALKTHROUGH_REQUIRED` | 409 |
| `ERR_SITE_PLAN_REQUIRED` | 409 |
| `ERR_REQUIREMENT_NOT_CONFIGURED` | 409 |
| `ERR_REQUIREMENT_EXISTS` | 409 |
| `ERR_DRILL_OVERLAP` | 409 |
| `ERR_WALKTHROUGH_DRILL_CONFLICT` | 409 |
| `ERR_DUPLICATE_ROSTER_ENTRY` | 409 |
| `ERR_AAR_EXISTS` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 409 |

# Hospital Emergency Preparedness Surge API — Product Requirements Document

## 1. Introduction

Hospitals do not get to choose when a mass-casualty event, a hazmat spill, or an infectious-disease wave arrives; they only get to choose how prepared they are when it does. This document specifies the Hospital Emergency Preparedness & Surge Plan API, the system of record for a hospital's emergency management program. It governs the full preparedness cycle — hazard vulnerability analysis, emergency-operations-plan maintenance, drills, and after-action improvement — and the full response cycle: incident declaration, incident command staffing, surge capacity assessment, personnel call-back, supply and PPE burn-rate management, alternate care site activation, patient tracking, family reunification, and coalition and regulatory reporting.

Two design commitments shape everything that follows. First, the API is **posture-driven**: nearly every response-time operation is gated on exactly one incident being `ACTIVATED`, and demobilization unwinds that posture through a deterministic cascade that touches staffing, site capacity, surge tiering, and supply projections. Second, the API is **audit-driven**: plan revisions, after-action reports, and regulatory filings all carry segregation-of-duties controls, lateness tracking, and immutable submission semantics so that a surveyor or coalition auditor can reconstruct who knew what, and when. All resources are mounted under the `/emergency` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes nine roles, spelled exactly as follows: `EmergencyManager`, `IncidentCommander`, `PlanningChief`, `LogisticsChief`, `PublicInformationOfficer`, `LiaisonOfficer`, `HospitalAdministrator`, `OnCallStaff`, and `PlatformAdmin`. A request missing either header, or presenting a role string outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is authenticated but whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The roles divide the emergency program's duties. An `EmergencyManager` directs the preparedness program: hazard analysis, plan drafts, exercises, after-action reports, and improvement tasks. An `IncidentCommander` declares, assesses, demobilizes, and reactivates incidents, fills command roles, and commits, activates, and demobilizes alternate care sites. A `PlanningChief` runs staffing call-back and patient tracking and co-owns surge assessment with the `IncidentCommander`. A `LogisticsChief` owns the supply cache, the stock ledger, and site registration. A `PublicInformationOfficer` staffs the family reunification desk. A `LiaisonOfficer` drafts coalition and regulatory reports. A `HospitalAdministrator` maintains the staff roster and serves as the executive approver and segregation-of-duties counterpart for plan approvals, after-action approvals, and report submission. An `OnCallStaff` member responds to their own call-back requests. A `PlatformAdmin` operates the test-driving logical clock. Read access is broad: every authenticated role may use the list and get-by-id endpoints.

For the eight operational roles, identity is anchored in the staff roster. When `X-User-Role` is `EmergencyManager`, `IncidentCommander`, `PlanningChief`, `LogisticsChief`, `PublicInformationOfficer`, `LiaisonOfficer`, `HospitalAdministrator`, or `OnCallStaff`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare the resource's foreign-key field to `X-User-ID` — for example, a call-back request's `staff_member_id`, or a compliance document's `created_by_id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. In no case does the server perform a roster lookup on `X-User-ID` itself: the header is used only in ownership comparisons and authorship stamps, and a request is never rejected merely because its `X-User-ID` does not resolve to an existing `StaffMember`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, generated from the logical clock of §2.5 rather than wall-clock time.
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

Requests outside the documented surface are also enveloped: a request to an undefined path is rejected with `ERR_NOT_FOUND` (HTTP 404); a defined path reached with an unsupported HTTP method is rejected with the `ERR_NOT_FOUND` error envelope at HTTP 405; and an unexpected server failure is reported with `error_id` `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it must lie between 1 and 100 inclusive. The `offset` parameter sets how many items to skip and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order; resources created at the same logical-clock instant share a `created_at` and retain their creation order relative to one another. Boolean-valued list filters (`is_active`, `callback_eligible`, `below_reorder_level`) accept `true`/`1` for true and `false`/`0` for false, case-insensitively, and any other value is rejected with `ERR_INVALID_REQUEST`.

Paginated list responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `total_count` counts all resources passing the supplied filters, and `has_more` is true exactly when `offset` plus the number of items returned is still less than `total_count`.

### 2.4. Common Resource Properties and the Append-Only Ledger Exception

Every primary resource in the system — staff members, hazard assessments, plan revisions, exercises, after-action reports, improvement tasks, incidents, command assignments, call-back requests, supply items, alternate care sites, patient records, family inquiries, and external reports — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a bare UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, equal to `created_at` at creation and refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created, increments by one on every mutation of the resource, and which backs the optimistic concurrency control described in §2.8.

Every state transition and every content mutation described in §3 — submit, approve, reject, finalize, start, complete, cancel, assess, respond, transfer, discharge, match, reunite, close, commit, activate, and demobilize — advances the mutated resource's `version` by one and refreshes its `updated_at`.

The single exception is the `StockTransaction` ledger. Ledger entries are immutable and append-only: a stock transaction carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it. The effect of a ledger entry is reflected on its parent supply item instead, whose own `updated_at` refreshes and whose `version` advances by one with every appended transaction.

### 2.5. The Logical Clock and Scheduled Sweeps

All time-dependent behavior in the system — call-back response-window expiry, improvement-task overdue marking, burn-rate windows, filing deadlines, and lateness — is evaluated against a single server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `PlatformAdmin` advances it through an admin-only test-driving capability that accepts a `to_iso8601` instant and sets the logical clock to that instant.

Setting the clock triggers two sweeps. Every call-back request still in `PENDING` whose `expires_at` lies strictly before the new clock time transitions to `EXPIRED`, and every improvement task in `OPEN` or `IN_PROGRESS` whose `due_date` lies strictly before the new clock time transitions to `OVERDUE`. Equality is not enough in either sweep — a request expiring exactly at the new clock time, or a task due exactly at it, survives the sweep. The capability's response reports the new `current_utc` along with the counts `swept_callbacks` and `swept_tasks`.

Because business timestamps are validated against this clock, a stock transaction's `occurred_at` may be backdated but must never be later than the current logical clock time; a future-dated `occurred_at` is rejected with `ERR_INVALID_REQUEST`.

### 2.6. Incident Posture: One Active Incident and the Activation Gate

The hospital operates under a single-incident posture model: at most one `IncidentEvent` may hold `status` `ACTIVATED` at any time. Declaring a new incident while another is active, or reactivating a demobilized incident while another is active, is rejected with `ERR_INCIDENT_ALREADY_ACTIVE` (HTTP 409).

The active posture is a hard gate on response operations. Each of the following requires the incident it references to be `ACTIVATED`, and is otherwise rejected with `ERR_INCIDENT_NOT_ACTIVATED` (HTTP 409): registering a patient record, opening a family inquiry, creating a call-back request, creating a command role assignment, recording a surge assessment on the incident, committing an activation window at an alternate care site, activating an alternate care site, and appending a stock transaction that carries an `incident_id` linkage. Stock transactions with no incident linkage are exempt from the gate — routine receiving and counting continue in peacetime.

### 2.7. Segregation of Duties in the Compliance Workflow

Three compliance artifacts enforce a rule that the author may not finalize their own work, and the server records both sides of the transaction. A plan revision records its author's identity in `created_by_id`; approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the approver's `X-User-ID` equals that `created_by_id`. An after-action report likewise records `created_by_id`, and its approval is rejected the same way. An external report records `created_by_id`, and its submission is rejected with `ERR_SEGREGATION_OF_DUTIES` when the submitter is the author — a `LiaisonOfficer` who drafted a report may not submit it, and neither may a `HospitalAdministrator` who drafted one on another's behalf.

A related ownership rule guards the call-back desk: responding to a call-back request requires the responder's `X-User-ID` to equal the request's `staff_member_id`; anyone else is rejected with `ERR_NOT_CALLBACK_OWNER` (HTTP 403).

### 2.8. Optimistic Concurrency Control on Command Assignments

Exactly one write operation in the API is protected by optimistic concurrency control: creating a command role assignment. The request must carry `expected_incident_version`, set to the target incident's `version` as the client last observed it. If the incident's current `version` no longer matches the supplied value — because another writer has advanced it since the client last read the incident, for instance by creating a command assignment of their own — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and no assignment is written. No other endpoint accepts a version field; clients must not send one anywhere else.

### 2.9. Derived Fields, Cascades, and Read-Your-Writes

The consistency model is immediate: every derived field named in this document — hazard risk scores, surge capacities, surge tiers, burn rates, days of supply, reorder flags, committed staffing counts, site censuses, reunification flags, filing deadlines, and lateness figures — is recomputed synchronously within the request that invalidates it, and a subsequent read observes the new values. Several operations mutate more than one resource in a single cascade; §3 names each cascade's links in order.

Where a path contains resource identifiers, existence is validated left to right, and the first identifier that fails to resolve rejects the request with `ERR_NOT_FOUND` (HTTP 404). The same error results when a request body references an identifier — an `incident_id`, `staff_member_id`, `plan_revision_id`, `site_id`, `patient_record_id`, `supply_item_id`, `after_action_report_id`, `supersedes_revision_id`, `source_hva_id`, or `subject_id` — that does not resolve to an existing resource.

### 2.10. Numeric Precision and Rounding

Hazard risk scoring uses integer arithmetic throughout, with no rounding. Burn rates — `observed_daily_burn_rate` and `projected_daily_burn_rate` — are carried to four decimal places using round-half-up. The `days_of_supply` figure is an integer obtained by discarding any fractional remainder (a floor). Filing lateness in `hours_late` is carried to two decimal places using round-half-up. Surge tier boundaries are evaluated by exact integer cross-multiplication — comparing one hundred times the projected census against the boundary percentage times the operational capacity — so no floating-point rounding ever occurs at a tier boundary, and a ratio falling exactly on a boundary belongs to the higher tier.

### 2.11. Validation Pipeline and Evaluation Order

When several validations apply to one request, the server evaluates them in a fixed order, and the first failure determines the response. The evaluation order is:

1. Header authentication (§2.1): failures yield `ERR_UNAUTHENTICATED`.
2. Role authorization against the endpoint's role list: `ERR_FORBIDDEN_ROLE`.
3. Path identifier resolution, validated left to right: `ERR_NOT_FOUND`.
4. Request body shape — required fields present, types and enum membership valid, integer ranges respected (`quantity` strictly positive, `bed_capacity` strictly positive, `staffed_bed_count` and `projected_census` non-negative, hazard `probability`, `severity`, and `preparedness` each between 0 and 3 inclusive, `auto_select_count` at least 1), `occurred_at` not after the current clock time, and a call-back create carrying exactly one of `staff_member_id` or `auto_select_count`: `ERR_INVALID_REQUEST`.
5. Body-referenced identifier resolution (§2.9): `ERR_NOT_FOUND`.
6. Identity and ownership — segregation of duties and call-back ownership (§2.7): `ERR_SEGREGATION_OF_DUTIES` or `ERR_NOT_CALLBACK_OWNER`.
7. Optimistic concurrency (§2.8): `ERR_STALE_VERSION`.
8. State-transition legality on the target resource — the generic guard that rejects any action whose target's current state does not permit it: `ERR_INVALID_STATE`.
9. Incident posture gating (§2.6): `ERR_INCIDENT_NOT_ACTIVATED`. One exception is forced by the data model: at alternate-care-site activation the gated incident is known only after the containing commitment window is located, so there the window check of rule 12 (`ERR_OUTSIDE_COMMIT_WINDOW`) fires before this posture check.
10. Business safety checks — site capacity at transfer and stock sufficiency at issue: `ERR_ACS_AT_CAPACITY` or `ERR_INSUFFICIENT_STOCK`.
11. Cross-incident consistency between the referenced resources: `ERR_CROSS_INCIDENT_REFERENCE`.
12. Temporal well-formedness and overlap: `ERR_INVALID_TIME_RANGE`, `ERR_EXERCISE_TIME_CONFLICT`, `ERR_SITE_WINDOW_CONFLICT`, or `ERR_OUTSIDE_COMMIT_WINDOW`.
13. Uniqueness, aggregate, and qualification constraints — the long tail from `ERR_BADGE_NUMBER_EXISTS` through `ERR_PATIENTS_STILL_ON_SITE` catalogued in §5, each named in §3 beside the workflow that enforces it.

## 3. Business Logic & Workflows

### 3.1. Hazard Vulnerability Analysis and Risk Scoring

The preparedness year opens with the hazard vulnerability analysis. An `EmergencyManager` creates a `HazardAssessment` cycle with a `fiscal_year` label such as FY2026 and a `scoring_model` of either `TWO_FACTOR` or `THREE_FACTOR_MITIGATION`, optionally seeding it with initial `hazard_entries`. Each hazard entry carries an `entry_key`, a `hazard_name`, a `category` of `NATURAL`, `TECHNOLOGICAL`, `HUMAN`, or `HAZMAT`, and three integer factor ratings — `probability`, `severity`, and `preparedness` — each between 0 and 3 inclusive. A cycle is created in `DRAFT` status, and while it remains `DRAFT` the manager may replace its `hazard_entries` wholesale via a patch, which recomputes every score and advances the assessment's `version`.

Every entry's `risk_score` is computed by the server on every write — at creation, on each entry-replacing patch, and again at finalization — and any client-supplied `risk_score` is ignored. Under the `TWO_FACTOR` model, an entry's `risk_score` is its `probability` multiplied by its `severity`, yielding a range of 0 to 9. Under the `THREE_FACTOR_MITIGATION` model, an entry's `risk_score` is its `probability` multiplied by the sum of its `severity` and the amount by which its `preparedness` falls short of three, yielding a range of 0 to 18; for identical inputs, the three-factor model scores strictly higher whenever `preparedness` is below 3. The cycle's `max_risk_score` is the largest `risk_score` across its entries, or zero when the cycle has no entries.

Finalizing the cycle — the `DRAFT` → `FINALIZED` transition — requires at least one hazard entry; finalizing an empty cycle is rejected with `ERR_HVA_NO_ENTRIES`. Finalization recomputes every score one last time, freezes the entries (further patches are then rejected as an illegal state with `ERR_INVALID_STATE`), advances the assessment's `version`, and sets `plan_review_triggered` to true when `max_risk_score` is at least 6 and to false otherwise. `FINALIZED` is terminal. A triggered review is the signal that starts the plan update cycle of §3.2.

### 3.2. The Plan Update Cycle: Drafting, Review, and Supersession

The emergency operations plan is versioned through `PlanRevision` documents. An `EmergencyManager` drafts a revision with a `revision_label` such as EOP-2026-B, a `change_summary`, and the `effective_date` on which it takes effect once approved. Two optional links give the revision context: `source_hva_id` points back to the hazard assessment cycle that motivated the rewrite, and `supersedes_revision_id` names the currently approved revision this draft intends to replace; when present, the supersede target must currently be `APPROVED`, otherwise the create is rejected with `ERR_SUPERSEDE_TARGET_NOT_APPROVED`. The author is recorded in `created_by_id`, and the draft enters `DRAFT`. The revisions list supports optional `supersedes_revision_id`, `source_hva_id`, and `status` filters.

Submitting a draft moves it `DRAFT` → `IN_REVIEW`. A `HospitalAdministrator` then decides. Rejection returns the revision `IN_REVIEW` → `DRAFT`, and the same draft may be edited and resubmitted — the reject loop has no limit. Approval moves it `IN_REVIEW` → `APPROVED` subject to two guards, evaluated in the pipeline order of §2.11: the segregation-of-duties rule of §2.7 (an approver who authored the draft is rejected with `ERR_SEGREGATION_OF_DUTIES`), and the single-approved-plan invariant — no other revision may currently be `APPROVED` except the one named by this draft's `supersedes_revision_id`, otherwise approval fails with `ERR_OTHER_PLAN_APPROVED`. On a successful approval the server stamps `approved_by_id` and `approved_at`, and the superseded predecessor — if any — automatically transitions `APPROVED` → `SUPERSEDED`, preserving the invariant that at most one plan revision is ever `APPROVED` at a time. `SUPERSEDED` is terminal, and each of these transitions advances the revision's `version`.

### 3.3. Exercises, After-Action Review, and Improvement Tracking

Preparedness is rehearsed through exercises. An `EmergencyManager` schedules an `ExerciseEvent` with an `exercise_name`, an `exercise_type` of `TABLETOP`, `FUNCTIONAL`, or `FULL_SCALE`, a `scenario_category` of `NATURAL`, `TECHNOLOGICAL`, `HUMAN`, or `HAZMAT`, a `scheduled_start`, a `scheduled_end`, and the `plan_revision_id` of the plan version under test, which must resolve to an existing revision at creation. The scheduled end must be strictly after the scheduled start, else the create is rejected with `ERR_INVALID_TIME_RANGE`. Scheduling treats each exercise as a half-open interval that includes its start and excludes its end: the new exercise is rejected with `ERR_EXERCISE_TIME_CONFLICT` when its interval overlaps any existing exercise in `SCHEDULED` or `IN_PROGRESS` — overlap meaning the new start falls strictly before the other's end and the new end falls strictly after the other's start. Back-to-back exercises, where one's end equals another's start, do not overlap and are permitted. The exercises list supports optional `plan_revision_id`, `status`, and `exercise_type` filters.

A `SCHEDULED` exercise can be cancelled, moving it to `CANCELLED`, or started. Starting requires the referenced plan revision to be `APPROVED` at start time — exercising against an unapproved plan is rejected with `ERR_PLAN_NOT_APPROVED` — and moves the exercise `SCHEDULED` → `IN_PROGRESS`, stamping `started_at`. Completion moves `IN_PROGRESS` → `COMPLETED` and stamps `completed_at`. An exercise already underway cannot be cancelled; the attempt is rejected with `ERR_INVALID_STATE`. `COMPLETED` and `CANCELLED` are terminal, and each transition advances the exercise's `version`.

Every exercise that completes, and every incident that demobilizes, feeds the after-action process. An `AfterActionReport` names its subject polymorphically: `subject_type` is `EXERCISE` or `INCIDENT`, and `subject_id` references a `COMPLETED` exercise or a `DEACTIVATED` incident accordingly; a create whose subject is not in the required state fails the generic state guard with `ERR_INVALID_STATE`. At most one report may exist per subject; a duplicate create against the same `subject_type` and `subject_id` is rejected with `ERR_AAR_ALREADY_EXISTS`. The author — an `EmergencyManager` or an `IncidentCommander` — is recorded in `created_by_id`, and the report opens in `DRAFT` carrying a narrative `summary`. Submission moves it `DRAFT` → `SUBMITTED` and stamps `submitted_at`; approval by a `HospitalAdministrator` moves it `SUBMITTED` → `APPROVED`, stamps `approved_by_id` and `approved_at`, and is bound by the segregation-of-duties rule of §2.7. `APPROVED` is terminal, and both transitions advance the report's `version`.

Findings become work through `ImprovementTask` items. An `EmergencyManager` attaches a task to a report via `after_action_report_id`, with a `description`, a `priority` of `HIGH`, `MEDIUM`, or `LOW`, a `due_date`, and an `assigned_department` drawn from the same department enumeration as the staff roster. Tasks may be added only while the owning report is `DRAFT` or `SUBMITTED`; once the report is `APPROVED`, task creation against it is rejected with `ERR_INVALID_STATE`. A task opens in `OPEN`. Progression is driven by patching `target_status`: `OPEN` → `IN_PROGRESS`, then `IN_PROGRESS` → `VERIFIED_COMPLETE`, which is terminal, each patch advancing the task's `version`. The logical-clock sweep of §2.5 moves `OPEN` and `IN_PROGRESS` tasks to `OVERDUE` when the clock passes their `due_date`. An overdue task is not stuck — patching `target_status` to `IN_PROGRESS` resumes it (`OVERDUE` → `IN_PROGRESS`) with its original `due_date` intact. The task list supports optional `after_action_report_id` and `status` filters.

### 3.4. Incident Activation, Surge Assessment, and Demobilization

When the hospital moves to response footing, an `IncidentCommander` declares an incident with an `incident_name`, an `incident_type` of `NATURAL`, `TECHNOLOGICAL`, `HUMAN`, `HAZMAT`, or `INFECTIOUS`, and the informational `declared_at` timestamp of the field declaration. Creation is itself the first activation: the incident enters `ACTIVATED` with `activation_count` set to 1 and `activated_at` stamped. Only one incident may be `ACTIVATED` at a time (§2.6). Because an activation changes the surge-multiplier context for the supply cache, every supply item's `projected_daily_burn_rate` is recomputed at declaration; with the new incident's `current_surge_tier` not yet assessed, the multiplier is 1.0 until the first assessment lands.

Surge posture is quantified by the surge assessment, recorded by an `IncidentCommander` or a `PlanningChief`, which writes `staffed_bed_count` and `projected_census` onto the incident. Assessment is posture-gated: it is permitted only while the incident is `ACTIVATED`, and is otherwise rejected with `ERR_INCIDENT_NOT_ACTIVATED`. From these inputs the server derives and stores two capacity variants. `licensed_surge_capacity`, the regulatory-reporting variant surfaced to coalition and government audiences, equals `staffed_bed_count` alone. `operational_surge_capacity`, the operational-planning variant, equals `staffed_bed_count` plus the `bed_capacity` of every alternate care site currently `ACTIVATED` in service of this incident (§3.7); the two variants diverge whenever at least one site is serving the incident, and operational capacity is then the larger figure.

The incident's `current_surge_tier` is derived by comparing the projected census against operational capacity using exact integer cross-multiplication (§2.10). When operational capacity is zero, the tier is `RED` if any census is projected and `GREEN` otherwise. Otherwise, the tier is `GREEN` when the census is below 85 percent of capacity, `YELLOW` when the census is at least 85 percent but below 100 percent of capacity, `ORANGE` when the census is at least 100 percent but below 115 percent of capacity, and `RED` when the census is at least 115 percent of capacity — a census exactly on a boundary takes the higher tier, so exactly 85 percent is `YELLOW`, exactly 100 percent is `ORANGE`, and exactly 115 percent is `RED`. Until the first assessment, `staffed_bed_count`, `projected_census`, and `current_surge_tier` are null. Every assessment re-derives and stores the tier, advances the incident's `version`, and recomputes every supply item's burn projections (§3.6); the same re-derivation runs on every capacity-affecting site transition.

Demobilization — `ACTIVATED` → `DEACTIVATED` — is an `IncidentCommander` decision with two safety preconditions: no patient record of this incident may still be `TRACKED` (`ERR_PATIENTS_STILL_TRACKED`), and no patient may still be `TRANSFERRED` at a site serving this incident (`ERR_PATIENTS_STILL_ON_SITE`). Demobilization then runs a four-step cascade in order. First, every call-back request of this incident still `PENDING` transitions to `EXPIRED`, and every one `ACCEPTED` transitions to `COMPLETED` — the duty tour ends — with `committed_staff_count` rederived accordingly. Second, every alternate care site `ACTIVATED` in service of this incident demobilizes per §3.7, and each such site transition recomputes the incident's `operational_surge_capacity` without that site's beds, re-derives `current_surge_tier` from the new capacity, and recomputes every supply item's projections. Third, the incident's `status` becomes `DEACTIVATED` and `deactivated_at` is stamped. Fourth, with no incident active anywhere, the surge multiplier falls back to 1.0 and every supply item's `projected_daily_burn_rate` is recomputed once more. The incident's `version` advances.

Surges come in waves, so the incident machine is cyclic. A `DEACTIVATED` incident may be reactivated — `DEACTIVATED` → `ACTIVATED` — provided no other incident is currently active (`ERR_INCIDENT_ALREADY_ACTIVE`). Reactivation increments `activation_count` by one, refreshes `activated_at`, retains the prior `deactivated_at` stamp (reactivation does not clear it), advances the incident's `version`, and recomputes every supply item's projected burn using the incident's retained `current_surge_tier` — the multiplier resumes, at 1.0 if the tier is null — so the cache immediately reflects the restored posture.

### 3.5. Staff Roster, Command Assignments, and Call-Back Operations

A `HospitalAdministrator` maintains the staff roster. Registering a `StaffMember` records `full_name`, `badge_number`, a home `department` of `EMERGENCY`, `ICU`, `SURGERY`, `NURSING`, `PHARMACY`, `LOGISTICS`, or `ADMINISTRATION`, and `role_qualifications` — the incident command roles the person is qualified to hold, each drawn from `INCIDENT_COMMANDER`, `PLANNING_CHIEF`, `LOGISTICS_CHIEF`, `PUBLIC_INFORMATION_OFFICER`, `LIAISON_OFFICER`, `SAFETY_OFFICER`, and `MEDICAL_BRANCH_DIRECTOR`. Three call-back attributes complete the profile: `is_active`, defaulting to true, marks current employment; `callback_eligible`, defaulting to false, marks whether the member may receive surge call-backs; and `callback_seniority_score`, defaulting to 0, ranks the member for automated selection, higher scores being called earlier. Badge numbers are unique across the roster; registering a member with a `badge_number` already in use is rejected with `ERR_BADGE_NUMBER_EXISTS`. The administrator may later patch `department`, `role_qualifications`, `is_active`, `callback_eligible`, or `callback_seniority_score`, each patch advancing the member's `version`. The roster list supports optional `department`, `is_active`, and `callback_eligible` filters.

Command staffing runs through `CommandRoleAssignment` records. An `IncidentCommander` creates one against an `ACTIVATED` incident by naming `incident_id`, `staff_member_id`, the `command_role` being filled, and — per §2.8 — `expected_incident_version` carrying the incident's `version` as last observed; a stale value is rejected with `ERR_STALE_VERSION`. The assignee must hold the named role in `role_qualifications`, otherwise the create is rejected with `ERR_STAFF_NOT_QUALIFIED`. Assignment is relieve-and-reassign: creating a new assignment for the same incident and command role automatically transitions any existing `ACTIVE` assignment for that pairing to `RELIEVED`, so exactly one holder is ever `ACTIVE` per role per incident. The new assignment stamps `assigned_at` and opens in `ACTIVE`, and the incident's `version` advances by one — which is precisely what invalidates any other commander's stale `expected_incident_version`. The assignments list supports optional `incident_id`, `staff_member_id`, and `status` filters.

Surge staffing runs through `CallBackRequest` records, created by a `PlanningChief` against an `ACTIVATED` incident in exactly one of two modes. Explicit mode names a `staff_member_id`; the member must be both `is_active` and `callback_eligible` (`ERR_STAFF_NOT_CALLBACK_ELIGIBLE`), and must not already hold a `PENDING` or `ACCEPTED` request for this incident (`ERR_DUPLICATE_CALLBACK`). Auto-select mode instead names `auto_select_count` and optionally a `required_department`; the server builds the eligible pool — members who are active, call-back eligible, in the required department when one is given, and holding no `PENDING` or `ACCEPTED` request for this incident — ranks it by `callback_seniority_score` from highest to lowest, ties broken by the member's `created_at` from earliest to latest and then by `badge_number` in ascending order, and creates requests for the top-ranked members. When the pool is smaller than `auto_select_count`, the create is rejected with `ERR_INSUFFICIENT_CALLBACK_POOL` and nothing is created — the check is atomic. A create carrying both modes, or neither, is rejected with `ERR_INVALID_REQUEST`. On each created request, `response_window_hours` defaults to 2 when omitted, and `expires_at` is the request's creation time plus that many hours. The create response is always an array, ordered by selection rank. The call-back list supports optional `incident_id`, `staff_member_id`, and `status` filters.

Requests open in `PENDING`. The addressed member — acting as `OnCallStaff`, and only the addressed member per the ownership rule of §2.7 — responds with an `outcome` of `ACCEPT` or `DECLINE`. Acceptance moves `PENDING` → `ACCEPTED`, stamps `responded_at`, and increases the incident's `committed_staff_count` by one as the count is rederived. Declining moves `PENDING` → `DECLINED`, stamps `responded_at`, and leaves the count unchanged. `committed_staff_count` is always the count of the incident's call-back requests currently in `ACCEPTED` — requests that are `PENDING`, `DECLINED`, `EXPIRED`, `CANCELLED`, or `COMPLETED` never contribute. A `PlanningChief` may cancel a `PENDING` or `ACCEPTED` request; the cancellation records no `reason` or other field; cancelling an `ACCEPTED` request compensates by decreasing `committed_staff_count` by one, returning it to its pre-accept value. Responding is legal only from `PENDING`, and cancelling only from `PENDING` or `ACCEPTED`; acting on a request already in a terminal state is rejected with `ERR_INVALID_STATE`. Both responding and cancelling advance the request's `version`. The clock sweep of §2.5 expires `PENDING` requests whose window has passed, and incident demobilization per §3.4 expires the pending and completes the accepted. `DECLINED`, `EXPIRED`, `CANCELLED`, and `COMPLETED` are terminal.

### 3.6. Supply Cache Ledger and Burn-Rate Projections

A `LogisticsChief` registers each cache item as a `SupplyItem` with an `item_name`, a `category` of `PPE`, `MEDICATION`, `OXYGEN`, or `OTHER_SUPPLY`, a `unit` of measure such as box, each, or case, and `reorder_min_days`, the minimum acceptable days-of-supply floor. New items start with `quantity_on_hand` at zero. The supply list supports optional `category` and `below_reorder_level` filters.

All stock movement flows through the append-only `StockTransaction` ledger (§2.4). Each entry names its `supply_item_id`, a `transaction_type` of `RECEIVE`, `ISSUE`, `RETURN`, or `ADJUST`, a strictly positive `quantity`, and the business timestamp `occurred_at` under the backdating rule of §2.5, with an optional `incident_id` linkage — posture-gated per §2.6 — and an optional free-text `note`. The item's `quantity_on_hand` is recomputed synchronously on every entry: a receipt adds the quantity, an issue subtracts it, a return adds it back, and an adjustment resets the on-hand figure to the stated absolute value. An issue whose `quantity` exceeds the item's current `quantity_on_hand` is rejected with `ERR_INSUFFICIENT_STOCK`. Every appended entry advances the item's `version`. The ledger list supports optional `supply_item_id`, `incident_id`, and `transaction_type` filters.

Two burn rates are maintained per item, recomputed synchronously on every ledger write, on every surge-tier change — whether from an assessment or a capacity cascade — and on every read of the item. The backward-looking `observed_daily_burn_rate` uses a trailing window of 168 hours, that is, seven days, ending at the current logical clock: sum the `quantity` of every `ISSUE` entry for the item whose `occurred_at` falls at or after the instant 168 hours before now and strictly before now, subtract the summed `quantity` of every `RETURN` entry in the same window — receipts and adjustments never enter the window — divide the net by seven, and round half-up to four decimal places. The forward-looking `projected_daily_burn_rate` then applies the surge multiplier keyed to the active incident's `current_surge_tier`: 1.0 when no incident is `ACTIVATED` or the active incident's tier is null, and otherwise 1.0 for `GREEN`, 1.25 for `YELLOW`, 1.5 for `ORANGE`, and 2.0 for `RED`. The rounding order is pinned — the observed rate is rounded first, then multiplied by the multiplier, then the product is rounded half-up to four decimal places — so an identical ledger under a `YELLOW` or worse posture always yields a strictly higher projected rate than observed.

Availability follows from the projection. `days_of_supply` is `quantity_on_hand` divided by `projected_daily_burn_rate`, floored to a whole number of days, and is null whenever the projected rate is zero. `below_reorder_level` is true exactly when `days_of_supply` is not null and is strictly less than `reorder_min_days` — an item sitting precisely at its floor is not below reorder — and is false whenever `days_of_supply` is null.

### 3.7. Alternate Care Sites and Patient Movement

When the main campus cannot absorb the surge, registered alternate care sites take the overflow. A `LogisticsChief` registers an `AlternateCareSite` with a `site_name`, an `address`, and a strictly positive `bed_capacity`; a site begins in `STANDBY` with an empty `commitments` list, a null `activated_incident_id`, and a `current_census` of zero. The site list supports optional `activated_incident_id` and `status` filters.

An `IncidentCommander` reserves future capacity by committing an activation window — supplying `incident_id`, `window_start`, and `window_end` — against an `ACTIVATED` incident. The window must be well formed, with `window_start` strictly before `window_end`, otherwise `ERR_INVALID_TIME_RANGE`; and it must clear a buffered-overlap check against every existing commitment, which pads each reserved window by a four-hour turnaround buffer on both sides. A proposed window conflicts — and is rejected with `ERR_SITE_WINDOW_CONFLICT` — whenever its start falls earlier than four hours after an existing window's end and, at the same time, its end falls later than four hours before that existing window's start. A successful commit appends the reserved window — its `incident_id`, `window_start`, and `window_end` — to the site's `commitments`. Committing moves a `STANDBY` site to `COMMITTED` on its first reservation, leaves the `status` of a `COMMITTED` or `ACTIVATED` site unchanged when further future windows are added, and brings a `DEMOBILIZED` site back to `COMMITTED` — the re-commitment loop that lets a site serve wave after wave. Each commit advances the site's `version`.

Activation turns a reservation into beds. An `IncidentCommander` activates a `COMMITTED` site when the current clock time falls inside one of its commitment windows, inclusive on both ends — when no commitment contains the current time, the activation is rejected with `ERR_OUTSIDE_COMMIT_WINDOW` — and when the incident named by that containing commitment is `ACTIVATED` (`ERR_INCIDENT_NOT_ACTIVATED`). Activation moves the site `COMMITTED` → `ACTIVATED`, sets `activated_incident_id` from the containing commitment, advances the site's `version`, and cascades: the served incident's `operational_surge_capacity` is recomputed to include this site's `bed_capacity`, its `current_surge_tier` is re-derived, and every supply item's burn projections are recomputed per §3.6.

Demobilizing a site — `ACTIVATED` → `DEMOBILIZED` — requires the site's `current_census` to be zero, and is otherwise rejected with `ERR_PATIENTS_STILL_ON_SITE`. Demobilization clears `activated_incident_id` to null, advances the site's `version`, and cascades in order: the previously served incident's `operational_surge_capacity` is recomputed without this site's beds, its `current_surge_tier` is re-derived from the new capacity, and every supply item's `projected_daily_burn_rate`, `days_of_supply`, and `below_reorder_level` are recomputed under the new surge-multiplier context. The same per-site cascade runs for each serving site when the incident itself demobilizes (§3.4).

Patients enter the tracking system when a `PlanningChief` registers a `PatientTrackRecord` against an `ACTIVATED` incident, with a de-identified `patient_ref`, a START `triage_category` of `IMMEDIATE`, `DELAYED`, `MINOR`, or `EXPECTANT`, and an `arrival_at` timestamp. The reference is unique within the incident — a second record with the same `patient_ref` on the same incident is rejected with `ERR_DUPLICATE_PATIENT_REF` — and the record opens `TRACKED`, with `transfer_site_id`, `transferred_at`, and `discharged_at` null and `reunified` false. The patient list supports optional `incident_id`, `transfer_site_id`, `status`, and `triage_category` filters.

Transfer moves a `TRACKED` patient to an alternate care site by naming `site_id`, under four guards, evaluated in the pipeline order of §2.11: the site must exist (`ERR_NOT_FOUND`); the site must be `ACTIVATED` (`ERR_SITE_NOT_ACTIVATED`); the site must have a free bed, its `current_census` strictly below its `bed_capacity` (`ERR_ACS_AT_CAPACITY`) — a census one below capacity succeeds, while a census equal to capacity fails; and the site must be serving this patient's incident, its `activated_incident_id` equal to the record's `incident_id` (`ERR_CROSS_INCIDENT_REFERENCE`). A successful transfer moves the record `TRACKED` → `TRANSFERRED`, sets `transfer_site_id`, stamps `transferred_at`, advances the record's `version`, and raises the target site's `current_census` by one as it is rederived.

Discharge ends tracking from either `TRACKED` or `TRANSFERRED`, moving the record to `DISCHARGED` and stamping `discharged_at`. Discharging a `TRANSFERRED` patient lowers the site's `current_census` by one — a site's census is always the count of patient records referencing it in `transfer_site_id` that remain in `TRANSFERRED` — which is how beds free up for the next transfer and how a site becomes eligible to demobilize. `DISCHARGED` is terminal.

### 3.8. Family Reunification and the Inquiry Desk

The `PublicInformationOfficer` staffs the reunification desk. Each call opens a `FamilyInquiry` against an `ACTIVATED` incident, recording `inquirer_name`, `inquirer_phone`, and the `sought_patient_ref` the family is asking about; the inquiry opens in `OPEN`. The inquiry list supports optional `incident_id`, `matched_patient_record_id`, and `status` filters.

Matching an `OPEN` inquiry to a patient record — by naming `patient_record_id` — runs five guards: the record must exist (`ERR_NOT_FOUND`); it must belong to the same incident as the inquiry (`ERR_CROSS_INCIDENT_REFERENCE`); its `patient_ref` must equal the inquiry's `sought_patient_ref` (`ERR_PATIENT_REF_MISMATCH`); it must still be `TRACKED` (`ERR_PATIENT_NOT_TRACKED`); and it must not already be referenced by another inquiry in `MATCHED` status (`ERR_PATIENT_ALREADY_MATCHED`). A successful match moves the inquiry `OPEN` → `MATCHED`, sets `matched_patient_record_id`, stamps `matched_at`, and advances the inquiry's `version`.

Two outcomes close the desk's loop. Reunification moves a `MATCHED` inquiry to `REUNITED`, stamps `reunited_at`, and flips the matched patient record's `reunified` flag to true — the record's only path to that value; the flip is a cascade side effect that does not advance the patient record's `version` or refresh its `updated_at`. Where no match is possible, closing moves an `OPEN` inquiry to `CLOSED_NO_MATCH`. `REUNITED` and `CLOSED_NO_MATCH` are terminal.

### 3.9. Coalition Reporting and Regulatory Deadlines

External communication runs through `ExternalReport` drafts, created by a `LiaisonOfficer` with an `audience` of `REGIONAL_COALITION`, `STATE_DOH`, `CMS`, or `LOCAL_EMA`; a `report_type` of `SITREP`, `SURGE_CAPACITY`, `AAR_SUMMARY`, or `RESOURCE_REQUEST`; a reporting `period_start` and `period_end`; a `body_summary`; and an optional `incident_id` linkage. The author is recorded in `created_by_id`, and the draft opens in `DRAFT`. The filing deadline is computed at creation from the report type: `due_at` is `period_end` plus 24 hours for `SITREP` and `RESOURCE_REQUEST`, plus 72 hours for `SURGE_CAPACITY`, and plus 720 hours — thirty days — for `AAR_SUMMARY`. The report list supports optional `incident_id`, `audience`, `report_type`, and `status` filters.

Submission — `DRAFT` → `SUBMITTED`, terminal and immutable thereafter — may be performed by a `LiaisonOfficer` or a `HospitalAdministrator`, but never by the draft's own author (§2.7, `ERR_SEGREGATION_OF_DUTIES`). Submission stamps `submitted_at`, advances the report's `version`, and scores lateness: `submitted_late` is true exactly when `submitted_at` falls strictly after `due_at` — filing precisely at the deadline is on time — and `hours_late` is the number of seconds between `due_at` and `submitted_at`, floored at zero, divided by 3600, and rounded half-up to two decimal places. Both fields remain null until submission. Late filings are accepted and flagged, never rejected — a regulator would rather see a late report than no report.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a staff member, hazard assessment, plan revision, exercise, after-action report, improvement task, incident, command assignment, call-back request, supply item, stock transaction, alternate care site, patient record, family inquiry, or external report — return a `201 Created` status code. Operations that modify an existing resource or drive one of its state transitions, including the logical-clock capability, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/emergency/staff-members` | Register a staff member | HospitalAdministrator |
| GET | `/emergency/staff-members` | List staff with optional filters; paginated | Any authenticated role |
| GET | `/emergency/staff-members/{id}` | Get one staff member | Any authenticated role |
| PATCH | `/emergency/staff-members/{id}` | Update mutable staff attributes | HospitalAdministrator |
| POST | `/emergency/hazard-assessments` | Create an HVA cycle with optional initial hazard entries | EmergencyManager |
| GET | `/emergency/hazard-assessments/{id}` | Get one HVA cycle with scored entries | Any authenticated role |
| PATCH | `/emergency/hazard-assessments/{id}` | Replace hazard entries while DRAFT; recomputes scores | EmergencyManager |
| POST | `/emergency/hazard-assessments/{id}/finalize` | Freeze scores and compute the plan-review trigger | EmergencyManager |
| POST | `/emergency/plan-revisions` | Create a plan revision draft, optionally superseding the current APPROVED revision | EmergencyManager |
| GET | `/emergency/plan-revisions` | List plan revisions with optional filters; paginated | Any authenticated role |
| GET | `/emergency/plan-revisions/{id}` | Get one plan revision | Any authenticated role |
| POST | `/emergency/plan-revisions/{id}/submit-review` | Submit a DRAFT revision for approval | EmergencyManager |
| POST | `/emergency/plan-revisions/{id}/approve` | Approve an IN_REVIEW revision; supersedes its predecessor | HospitalAdministrator |
| POST | `/emergency/plan-revisions/{id}/reject` | Reject an IN_REVIEW revision back to DRAFT | HospitalAdministrator |
| POST | `/emergency/exercises` | Schedule an exercise under a plan revision | EmergencyManager |
| GET | `/emergency/exercises` | List exercises with optional filters; paginated | Any authenticated role |
| GET | `/emergency/exercises/{id}` | Get one exercise | Any authenticated role |
| POST | `/emergency/exercises/{id}/start` | Start a SCHEDULED exercise | EmergencyManager |
| POST | `/emergency/exercises/{id}/complete` | Complete an IN_PROGRESS exercise | EmergencyManager |
| POST | `/emergency/exercises/{id}/cancel` | Cancel a SCHEDULED exercise | EmergencyManager |
| POST | `/emergency/after-action-reports` | Create an AAR for a COMPLETED exercise or DEACTIVATED incident | EmergencyManager, IncidentCommander |
| GET | `/emergency/after-action-reports/{id}` | Get one AAR | Any authenticated role |
| POST | `/emergency/after-action-reports/{id}/submit` | Submit a DRAFT AAR | EmergencyManager, IncidentCommander |
| POST | `/emergency/after-action-reports/{id}/approve` | Approve a SUBMITTED AAR | HospitalAdministrator |
| POST | `/emergency/improvement-tasks` | Add a corrective-action task to a DRAFT or SUBMITTED AAR | EmergencyManager |
| GET | `/emergency/improvement-tasks` | List improvement tasks with optional filters; paginated | Any authenticated role |
| GET | `/emergency/improvement-tasks/{id}` | Get one improvement task | Any authenticated role |
| PATCH | `/emergency/improvement-tasks/{id}` | Advance task status per the task state machine | EmergencyManager |
| POST | `/emergency/incidents` | Declare and activate an incident | IncidentCommander |
| GET | `/emergency/incidents/{id}` | Get one incident with surge fields and committed staffing | Any authenticated role |
| POST | `/emergency/incidents/{id}/assess-surge` | Record staffed beds and projected census; compute capacity and tier | IncidentCommander, PlanningChief |
| POST | `/emergency/incidents/{id}/demobilize` | Demobilize an ACTIVATED incident; cascades to callbacks, sites, capacity, tier, burn rates | IncidentCommander |
| POST | `/emergency/incidents/{id}/reactivate` | Reactivate a DEACTIVATED incident | IncidentCommander |
| POST | `/emergency/command-assignments` | Assign or relieve-and-reassign an ICS command role; OCC-guarded | IncidentCommander |
| GET | `/emergency/command-assignments` | List command assignments with optional filters; paginated | Any authenticated role |
| GET | `/emergency/command-assignments/{id}` | Get one command assignment | Any authenticated role |
| POST | `/emergency/callback-requests` | Create call-back request(s), explicit or auto-select | PlanningChief |
| GET | `/emergency/callback-requests` | List call-back requests with optional filters; paginated | Any authenticated role |
| GET | `/emergency/callback-requests/{id}` | Get one call-back request | Any authenticated role |
| POST | `/emergency/callback-requests/{id}/respond` | Respond to your own PENDING call-back request | OnCallStaff |
| POST | `/emergency/callback-requests/{id}/cancel` | Cancel a PENDING or ACCEPTED call-back request | PlanningChief |
| POST | `/emergency/supply-items` | Register a supply/PPE cache item | LogisticsChief |
| GET | `/emergency/supply-items` | List supply items with optional filters; paginated | Any authenticated role |
| GET | `/emergency/supply-items/{id}` | Get one supply item with burn-rate fields | Any authenticated role |
| POST | `/emergency/stock-transactions` | Append a ledger transaction | LogisticsChief |
| GET | `/emergency/stock-transactions` | List ledger transactions with optional filters; paginated | Any authenticated role |
| GET | `/emergency/stock-transactions/{id}` | Get one ledger transaction | Any authenticated role |
| POST | `/emergency/alternate-care-sites` | Register an alternate care site | LogisticsChief |
| GET | `/emergency/alternate-care-sites` | List sites with optional filters; paginated | Any authenticated role |
| GET | `/emergency/alternate-care-sites/{id}` | Get one site with commitments and census | Any authenticated role |
| POST | `/emergency/alternate-care-sites/{id}/commit` | Reserve an activation window for an ACTIVATED incident | IncidentCommander |
| POST | `/emergency/alternate-care-sites/{id}/activate` | Activate a COMMITTED site inside a commitment window | IncidentCommander |
| POST | `/emergency/alternate-care-sites/{id}/demobilize` | Demobilize an ACTIVATED site with zero census | IncidentCommander |
| POST | `/emergency/patient-records` | Register a tracked patient on an ACTIVATED incident | PlanningChief |
| GET | `/emergency/patient-records` | List patient records with optional filters; paginated | Any authenticated role |
| GET | `/emergency/patient-records/{id}` | Get one patient record | Any authenticated role |
| POST | `/emergency/patient-records/{id}/transfer` | Transfer a TRACKED patient to an ACTIVATED site serving the same incident | PlanningChief |
| POST | `/emergency/patient-records/{id}/discharge` | Discharge a TRACKED or TRANSFERRED patient | PlanningChief |
| POST | `/emergency/family-inquiries` | Open a family reunification inquiry on an ACTIVATED incident | PublicInformationOfficer |
| GET | `/emergency/family-inquiries` | List inquiries with optional filters; paginated | Any authenticated role |
| GET | `/emergency/family-inquiries/{id}` | Get one inquiry | Any authenticated role |
| POST | `/emergency/family-inquiries/{id}/match` | Match an OPEN inquiry to a TRACKED patient record | PublicInformationOfficer |
| POST | `/emergency/family-inquiries/{id}/reunite` | Mark a MATCHED inquiry reunified | PublicInformationOfficer |
| POST | `/emergency/family-inquiries/{id}/close-no-match` | Close an OPEN inquiry with no match | PublicInformationOfficer |
| POST | `/emergency/external-reports` | Draft a coalition/regulatory report | LiaisonOfficer |
| GET | `/emergency/external-reports` | List reports with optional filters; paginated | Any authenticated role |
| GET | `/emergency/external-reports/{id}` | Get one report | Any authenticated role |
| POST | `/emergency/external-reports/{id}/submit` | Submit a DRAFT report; late submissions accepted and flagged | LiaisonOfficer, HospitalAdministrator |
| POST | `/emergency/_clock/set_current_utc` | Set the logical clock; sweeps callback expiry and task overdue marking | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_CALLBACK_OWNER` | 403 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INCIDENT_NOT_ACTIVATED` | 409 |
| `ERR_INCIDENT_ALREADY_ACTIVE` | 409 |
| `ERR_PLAN_NOT_APPROVED` | 422 |
| `ERR_OTHER_PLAN_APPROVED` | 409 |
| `ERR_SUPERSEDE_TARGET_NOT_APPROVED` | 422 |
| `ERR_AAR_ALREADY_EXISTS` | 409 |
| `ERR_HVA_NO_ENTRIES` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_EXERCISE_TIME_CONFLICT` | 409 |
| `ERR_SITE_WINDOW_CONFLICT` | 409 |
| `ERR_OUTSIDE_COMMIT_WINDOW` | 422 |
| `ERR_SITE_NOT_ACTIVATED` | 409 |
| `ERR_PATIENTS_STILL_TRACKED` | 409 |
| `ERR_PATIENTS_STILL_ON_SITE` | 409 |
| `ERR_ACS_AT_CAPACITY` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 422 |
| `ERR_DUPLICATE_PATIENT_REF` | 409 |
| `ERR_PATIENT_ALREADY_MATCHED` | 409 |
| `ERR_PATIENT_REF_MISMATCH` | 422 |
| `ERR_PATIENT_NOT_TRACKED` | 422 |
| `ERR_CROSS_INCIDENT_REFERENCE` | 422 |
| `ERR_DUPLICATE_CALLBACK` | 409 |
| `ERR_STAFF_NOT_CALLBACK_ELIGIBLE` | 422 |
| `ERR_INSUFFICIENT_CALLBACK_POOL` | 422 |
| `ERR_STAFF_NOT_QUALIFIED` | 422 |
| `ERR_BADGE_NUMBER_EXISTS` | 409 |
| `ERR_INTERNAL` | 500 |

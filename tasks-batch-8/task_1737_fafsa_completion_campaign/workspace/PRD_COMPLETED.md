# FAFSA Completion Campaign API — Product Requirements Document

## 1. Introduction

Every aid year, states pour grant money on the table and then watch a stubborn fraction of graduating seniors never file the federal form that unlocks it. The gap is rarely eligibility; it is process failure — families who cannot assemble documents, students selected for verification who quietly give up, counselors who learn about a missed state priority deadline after it passes. A state-level FAFSA completion initiative exists to close that gap, and it needs an operational backbone that is part data-matching engine, part event-staffing coordinator, part casework tracker, and part privacy-guarded reporting service.

This document specifies the FAFSA Completion Campaign API. A `CampaignAdmin` at the state agency stands up a campaign for an aid year, invites schools, and vets volunteers and financial-aid experts. A `SchoolCoordinator` at each participating school loads the senior list, records family consent, runs completion events, and refers students who need individualized help. A `DataImporter` feeds completion-status records from the state aid agency into the system, where a `MatchReviewer` reconciles them against school rosters. `Specialist` caseworkers shepherd verification-selected and special-circumstance students to resolution, and published completion reports — privacy-suppressed and deadline-aware — drive school recognition. Underneath all of it sit two hard requirements: student status data is consent-gated at every read and every report, and the campaign's own deadlines, budgets, and caseload limits are enforced by the system rather than by operator vigilance.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and contracts that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly six roles: `CampaignAdmin`, `SchoolCoordinator`, `StaffMember`, `Specialist`, `MatchReviewer`, and `DataImporter`. A request missing either header, or presenting a role value outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not on the endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE`.

The meaning of `X-User-ID` depends on the role, and the binding is part of the access-control contract:

- When `X-User-Role` is `SchoolCoordinator`, `X-User-ID` is the `id` of the acting `School`. Every write the coordinator performs must target resources of their own school: whenever a resource carries a `school_id` (directly or through its parent chain, such as an event's school or a senior's school), the server compares that field to `X-User-ID`, and a mismatch is rejected with `ERR_SCHOOL_SCOPE_VIOLATION`.
- When `X-User-Role` is `StaffMember`, `X-User-ID` is the `id` of the acting `StaffProfile`; an assignment response is only valid when the assignment's `staff_profile_id` equals `X-User-ID`, otherwise the request fails with `ERR_OWNERSHIP_VIOLATION`.
- When `X-User-Role` is `Specialist`, `X-User-ID` is likewise the `id` of the acting `StaffProfile`; case actions are only valid when the case's `assigned_specialist_id` equals `X-User-ID`, otherwise the request fails with `ERR_OWNERSHIP_VIOLATION`.
- When `X-User-Role` is `CampaignAdmin`, `MatchReviewer`, or `DataImporter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; these three roles act across the whole campaign space subject only to the endpoint's role list.

Read scoping mirrors these bindings. A `SchoolCoordinator`'s list reads of senior records, consent records, document checklists, event registrations, and support cases return only their own school's resources, and a coordinator's single-record read of a senior record, consent record, document checklist (including its item list), or event registration belonging to another school fails with `ERR_SCHOOL_SCOPE_VIOLATION`; the coordinator's remaining reads — campaigns, schools, staff profiles, events, staff assignments, single support cases, and completion reports — are not school-scoped. `StaffMember` and `Specialist` list reads of staff assignments return only their own assignments, and a `Specialist`'s list read of support cases returns only cases assigned to them; single-record staff-assignment and support-case reads are not ownership-scoped.

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

The envelope's `api_request_timestamp` reflects the server's wall clock; it is independent of the logical campaign clock of §2.5. A request to an undefined path, or to an unsupported method on a defined path, is answered with `ERR_INVALID_REQUEST` carrying HTTP 404 or 405 respectively.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter says how many items to skip and defaults to 0. Both parameters appear in the `meta` object of list responses alongside `total_count` (the full count of matching resources) and `has_more` (whether further pages exist beyond the returned window). A non-integer or out-of-range `limit`, or a non-integer or negative `offset`, is rejected with `ERR_INVALID_REQUEST`. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order, with equal timestamps broken by creation order (earlier-created first).

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time as ISO 8601 UTC with three fractional digits; `updated_at` follows the same format and refreshes on any mutation of the resource. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation of the resource — including mutations driven by cascades from other resources, so a senior whose match status changes as a side effect of a reviewer action will observe a `version` bump and an `updated_at` refresh on the senior record itself.

The single exception is the `AidStatusEvent` resource, which is an immutable append-only log entry: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

### 2.5. The Logical Campaign Clock

Time in this system is logical, not wall-clock. A `CampaignAdmin`-only test-driving capability advances the logical clock to a supplied instant: the request carries `to_iso8601`, and the response body reports the resulting `now`. Before any such call, the logical clock starts at `2026-08-01T00:00:00Z`.

Advancing the clock is the trigger for every time-driven transition in the system, applied immediately as part of the same call:

- A campaign in `OPEN` moves to `STATE_GRACE` once the clock reaches or passes its `state_grant_deadline`, provided the clock has not yet reached its `federal_deadline`.
- A campaign in `OPEN` or `STATE_GRACE` moves to `CLOSED` once the clock reaches or passes its `federal_deadline`, firing the full close cascade described in §3.1.
- A published completion event moves from `PUBLISHED` to `IN_PROGRESS` once the clock reaches or passes its `start_time`.
- A consent record in `GRANTED` moves to `EXPIRED` once the clock reaches or passes its non-null `expires_at`, firing the same cascade as a manual revocation (§3.6).

The clock is set unconditionally to the supplied instant — moving it backward is allowed and never reverses a transition already taken. Within one call the transitions fire in a fixed order: consent expiries first, then campaign state transitions (firing the close cascade where applicable), then event starts — so a published event whose `start_time` is reached in the same call that closes its campaign is cancelled by the close cascade while still `PUBLISHED` and never reaches `IN_PROGRESS`.

Datetime comparisons that name a "deadline" are evaluated at day granularity: a datetime is first truncated to its UTC calendar date before comparison.

### 2.6. Consent-Gated Privacy and Data Visibility

Student completion-status data is personal data, and access to it is consent-driven rather than role-driven. Each senior's `data_visibility` is a computed value: it is `NORMAL` if and only if a `GRANTED` consent record carrying the `STATUS_DETAIL` scope exists for that senior, and `RESTRICTED` otherwise. A senior record starts `RESTRICTED` at creation, before any consent exists.

Visibility has teeth at the read layer. When a senior's `data_visibility` is `RESTRICTED`, any retrieval of that senior — whether a single-record read or an entry in a list — returns `fafsa_status`, `submitted_at`, `deadline_classification`, and `current_match_link_id` as `null`, regardless of the caller's role. Identity and roster fields (name, school, language, tags) remain visible; only the aid-status quartet is masked. Masking governs what a returned senior entry reveals, not which entries match a query: list filters on `fafsa_status` and the other masked fields match against the stored values before masking is applied.

Consent scopes are a non-empty subset of `STATUS_DETAIL`, `OUTREACH`, and `DATA_SHARE`, and each scope unlocks a distinct capability: `STATUS_DETAIL` governs status visibility as above, `OUTREACH` is required before a senior may be registered for a completion event, and `DATA_SHARE` admits the senior into completion-report eligibility (§3.9). Lacking the required scope is a business refusal surfaced as `ERR_CONSENT_REQUIRED`, not an authentication failure.

### 2.7. Numeric Precision and Monetary Conventions

All monetary amounts — budgets, event cost estimates, actual costs — are integers denominated in cents; no fractional cents exist anywhere in the system, and no non-negativity constraint is imposed on any monetary field. Where a computation produces a ratio or a rate, the rounding rule is fixed: percentages in completion reporting are rounded half-up to one decimal place, staffing ratios and assignment durations are rounded half-up to two decimal places, and the match score is computed with exact decimal arithmetic in tenths so that its four weights total exactly one whole. Deadline classification compares dates at day granularity, truncating datetimes to their UTC date, and treats upper bounds as inclusive. Interval arithmetic (event windows, booking overlaps) operates on half-open intervals at exact parsed precision. Datetime inputs are ISO 8601; the parser accepts a `T` or space date-time separator and an optional `Z` or numeric zone offset, normalizing every value to UTC.

### 2.8. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and no others are.

Proposing a match link requires the client to send `expected_senior_record_version` carrying the `version` of the senior record as the client last observed it. Because creating a link mutates the senior — advancing its match axis and incrementing its `version` — a reviewer working from a stale view (for instance, one read before an earlier auto-rejected proposal already advanced the version) must be stopped from building on it: when the supplied value does not equal the senior's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Publishing a completion report requires the client to send `expected_campaign_version` carrying the `version` of the campaign as last observed. Publication supersedes whatever report is currently published, and that supersede decision must rest on the current campaign view — budget commits, status flips, and prior publishes all advance `Campaign.version` — so a mismatch between the supplied value and the campaign's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field.

### 2.9. Validation Precedence

When a request violates several rules at once, the error it receives is deterministic. The server evaluates checks in the following fixed order, and the first failure wins:

1. Header context: `X-User-ID` and `X-User-Role` are present and the role is a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization and scope: the acting role appears in the endpoint's role list (`ERR_UNAUTHORIZED_ROLE`); scope and ownership rules — coordinator school scope, staff and specialist ownership — hold (`ERR_SCHOOL_SCOPE_VIOLATION` or `ERR_OWNERSHIP_VIOLATION`).
3. Request shape: required fields are present and required strings non-empty, no unknown fields appear, enum values are valid, and datetime, date, and integer formats parse (`ERR_INVALID_REQUEST`).
4. Existence: path identifiers and body foreign-key references resolve to existing resources, validated left to right (the per-resource not-found family: `ERR_CAMPAIGN_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_STAFF_PROFILE_NOT_FOUND`, `ERR_SENIOR_RECORD_NOT_FOUND`, `ERR_AID_RECORD_NOT_FOUND`, `ERR_MATCH_LINK_NOT_FOUND`, `ERR_CONSENT_RECORD_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`, `ERR_EVENT_REGISTRATION_NOT_FOUND`, `ERR_CHECKLIST_NOT_FOUND`, `ERR_CHECKLIST_ITEM_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND`, `ERR_COMPLETION_REPORT_NOT_FOUND`).
5. State permission: the target entity is in a state that permits the operation — the state-error family such as `ERR_CAMPAIGN_NOT_DRAFT`, `ERR_CAMPAIGN_NOT_OPEN`, `ERR_SCHOOL_NOT_INVITED`, `ERR_SCHOOL_NOT_ENROLLED`, `ERR_EVENT_NOT_DRAFT`, `ERR_MATCH_LINK_NOT_SUGGESTED`, `ERR_CASE_NOT_ACTIONABLE`, and their siblings — including the campaign-level and school-level gates described in §3.
6. Business safety: consent scope for the operation (`ERR_CONSENT_REQUIRED`) and background-check clearance before confirming staff (`ERR_BACKGROUND_CHECK_NOT_CLEARED`).
7. Cross-campaign referential integrity: referenced entities belong to one campaign (`ERR_CROSS_CAMPAIGN_REFERENCE`).
8. Temporal sanity and overlap: event window well-formedness (`ERR_EVENT_WINDOW_INVALID`), future-start requirements (`ERR_EVENT_IN_PAST`), staff double-booking (`ERR_STAFF_DOUBLE_BOOKED`), and the venue buffer (`ERR_EVENT_OVERLAP_BUFFER`).
9. Uniqueness, capacity, and aggregate constraints: the constraint family — `ERR_DUPLICATE_STUDENT_REF`, `ERR_DUPLICATE_EXTERNAL_REF`, `ERR_LINK_ALREADY_EXISTS`, `ERR_DUPLICATE_ASSIGNMENT`, `ERR_CONSENT_ALREADY_ACTIVE`, `ERR_CASE_ALREADY_OPEN`, `ERR_DUPLICATE_REGISTRATION`, `ERR_EVENT_FULL`, `ERR_STAFFING_INVARIANT_NOT_MET`, `ERR_STAFF_LACKS_CAPABILITY`, `ERR_ITEM_NOT_WAIVABLE`, `ERR_CASE_NOT_FOUND_FOR_SPECIALIST`, `ERR_CHECKLIST_NOT_COMPLETE`, `ERR_DETERMINATION_REQUIRED`.
10. Fiscal gates last: budget checks on publish and completion (`ERR_BUDGET_EXCEEDED`).

The ordering matters to callers: a request that would breach the budget but also targets a non-existent school receives the not-found error, and a match proposal on a senior in the wrong state fails before its score band is ever examined. Optimistic-concurrency rejections (`ERR_STALE_VERSION`, §2.8) are evaluated with the existence-and-state checks for the guarded entity, before business rules run. Scope and ownership comparisons need the governing resource in hand, so the not-found error for the resource whose school or owner is being compared always precedes its scope or ownership error. Where a section in §3 names an explicit check order for an endpoint, that order governs over the generic numbering above.

### 2.10. Cascading Consistency Across the Campaign Graph

The entity graph is flat — every collection is addressable under the campaign API — but behavior is deeply cascaded. State changes on one aggregate routinely mutate others: closing a campaign cancels events, assignments, registrations, and cases; revoking a consent pauses cases and cancels registrations; completing an event marks no-shows and can suspend a staff member, whose suspension in turn cancels their future assignments. Every such secondary mutation is a real mutation of the affected resource: its `updated_at` refreshes and its `version` increments. Computed counters on staff profiles (`confirmed_hours_total`, `no_show_count`, `active_case_count`) and computed budget fields on the campaign (`committed_budget_cents`, `spent_budget_cents`, `budget_balance_cents`) are reconciled immediately and exactly at each triggering event — never lazily, never approximately — and the compensating operations are designed so that a forward action followed by its natural undo (publish then cancel, confirm then cancel, revoke then regrant) returns the affected aggregate to its exact prior value.

Nested reads and writes that carry multiple identifiers in the path validate existence strictly left to right: a status-event listing under a non-existent aid record fails with `ERR_AID_RECORD_NOT_FOUND` before any inner identifier is considered.

## 3. Business Logic & Workflows

### 3.1. Campaign Setup and the Deadline Calendar

A `CampaignAdmin` opens a season by creating a campaign with a display `name`, an `academic_year` label such as `2027-2028`, the two governing deadlines — `state_grant_deadline` (the state grant priority cutoff) and `federal_deadline` (the federal FAFSA cutoff) — and a `total_budget_cents` purse for completion events. Six tuning knobs ship with documented defaults and may be overridden at creation: `auto_confirm_threshold` (default 0.90) and `review_floor` (default 0.60) govern the matching bands of §3.5; `min_subgroup_size` (default 5) is the k-anonymity floor for report rows; `max_caseload` (default 25) is the specialist overload threshold; `no_show_limit` (default 3) is the staffing suspension threshold; and `min_recognition_seniors` (default 10) is the minimum senior base for school recognition. Overrides are validated only for type plus these minimums — `min_subgroup_size` at least 1, `max_caseload` at least 0, `no_show_limit` at least 1, `min_recognition_seniors` at least 0 — while the two thresholds accept any JSON number and `total_budget_cents` any integer. A new campaign is `DRAFT` with all budget counters at zero.

Activation moves the campaign from `DRAFT` to `OPEN`; attempting activation from any other state is refused with `ERR_CAMPAIGN_NOT_DRAFT`. Only an `OPEN` campaign admits school enrollment (including reinstatement), senior-list loading, event creation, event publication, and report generation and publication — a write in this gated set aimed at a campaign that is not `OPEN` (or, where a rule explicitly allows it, `STATE_GRACE`) fails with `ERR_CAMPAIGN_NOT_OPEN`. Every other write is gated by its own preconditions alone, not by campaign state: school and staff-profile creation, consent, match-link, checklist, case, and aid-record writes carry no campaign-state gate (so, for example, an aid record can be imported and a consent revoked on a `CLOSED` campaign), and an event left `IN_PROGRESS` at close can still be checked into and completed. Once the logical clock reaches the `state_grant_deadline` while the campaign is `OPEN`, the campaign slides into `STATE_GRACE`: the state priority window has closed, but federal time remains, and the grace state continues to admit the writes that creation rules mark as valid in `STATE_GRACE`. When the clock reaches the `federal_deadline`, the campaign closes from either `OPEN` or `STATE_GRACE` to the terminal `CLOSED` state, and the close cascade fires: every `DRAFT` or `PUBLISHED` completion event of the campaign is cancelled (each cancellation releasing its budget commitment, cancelling non-terminal staff assignments with hours release, and cancelling registered family sign-ups, exactly as §3.7 describes), while events already `IN_PROGRESS` are deliberately left standing for manual completion rather than cancelled mid-stream; and every support case of the campaign's seniors in `OPEN`, `IN_REVIEW`, `AWAITING_FAMILY`, `ESCALATED`, or `PAUSED` is cancelled with its `previous_status` cleared to `null`, decrementing each assigned specialist's `active_case_count` — cases already `PAUSED` were decremented when they paused, so only the active statuses decrement — with overload recovery re-evaluated.

A campaign exposes three computed budget readings at all times: `committed_budget_cents`, the sum of `cost_estimate_cents` over its events currently `PUBLISHED` or `IN_PROGRESS`; `spent_budget_cents`, the sum of `actual_cost_cents` over its `COMPLETED` events; and `budget_balance_cents`, the remainder of `total_budget_cents` after subtracting committed and spent. These three fields are maintained eagerly as events publish, unpublish, cancel, and complete (§3.7).

### 3.2. Schools, Rosters, and the Staff Registry

Schools join by invitation. The `CampaignAdmin` creates each school under a `campaign_id` — the campaign must exist (`ERR_CAMPAIGN_NOT_FOUND`) but may be in any state — with a display `name`, a `district_code`, and a `school_code` — the two codes matter later, because matching and reporting key on them. A school is born `INVITED`; enrollment moves it to `ENROLLED` and is only valid while the school is `INVITED` (otherwise `ERR_SCHOOL_NOT_INVITED`) and the parent campaign is `OPEN` (otherwise `ERR_CAMPAIGN_NOT_OPEN`). Suspension reverses participation: suspending an `ENROLLED` school (any other state draws `ERR_SCHOOL_NOT_ENROLLED`) cancels every `DRAFT` or `PUBLISHED` event of that school with the full assignment, registration, and budget cascades of §3.7, while `COMPLETED` and `IN_PROGRESS` events are untouched; suspension itself carries no campaign-state gate. A suspended school can be reinstated to `ENROLLED` — reinstatement requires the school to be `SUSPENDED` (`ERR_SCHOOL_NOT_SUSPENDED`) and the campaign `OPEN`. Each school also carries a computed `recognition_tier`, one of `GOLD`, `SILVER`, `BRONZE`, or `UNRATED`, starting at `UNRATED` and recomputed only when a completion report is published (§3.10).

The staff registry holds the campaign's volunteers and experts. A `CampaignAdmin` creates each profile under a `campaign_id` — the campaign must exist (`ERR_CAMPAIGN_NOT_FOUND`) but may be in any state — with a `full_name`, a `capabilities` list drawn from `EVENT_STAFF`, `AID_EXPERT`, and `CASE_SPECIALIST` (any other capability value is `ERR_INVALID_REQUEST`), and the `languages` the person can support as ISO language codes (stored as given, without format validation). Profiles start with `background_check_status` of `PENDING` and `status` of `ACTIVE`; the administrator records vetting outcomes through the background-check action, whose `result` payload sets `background_check_status` to `CLEARED` or `EXPIRED` — the action has no profile-state or campaign-state precondition and may be recorded at any time. Three computed counters ride on every profile: `confirmed_hours_total`, the sum of `duration_hours` across the person's own assignments in `CONFIRMED` or `CHECKED_IN`; `no_show_count`, the tally of assignments marked `NO_SHOW`; and `active_case_count`, the tally of support cases assigned to the person in `OPEN`, `IN_REVIEW`, `AWAITING_FAMILY`, or `ESCALATED`.

Two threshold machines govern a profile's standing without any human action. When a case assignment pushes `active_case_count` strictly above the campaign's `max_caseload`, the profile flips from `ACTIVE` to `OVERLOADED` and is excluded from the specialist selector pool while overloaded; when resolutions, cancellations, or pauses bring the count back down to `max_caseload` or below, the profile returns to `ACTIVE`. Separately, when an event completion marks a no-show that brings `no_show_count` to the campaign's `no_show_limit` or more, the profile flips from `ACTIVE` — or directly from `OVERLOADED` — to `SUSPENDED`, and the suspension is contagious: every `INVITED`, `ACCEPTED`, or `CONFIRMED` assignment that staff member holds on events whose `start_time` is still in the future is cancelled, with confirmed hours released. The hours invariant holds exactly: confirming an assignment adds its `duration_hours`, and cancelling that same confirmed assignment subtracts the identical amount, returning `confirmed_hours_total` to its pre-confirm value to the cent of an hour.

### 3.3. Loading Seniors and Importing Aid Records

With a school `ENROLLED` and the campaign `OPEN` or `STATE_GRACE`, the school's coordinator builds the senior list — a non-`ENROLLED` school fails with `ERR_SCHOOL_NOT_ENROLLED` and a campaign outside `OPEN`/`STATE_GRACE` with `ERR_CAMPAIGN_NOT_OPEN`. Each record carries the school's own `student_ref` (unique within the school — a reuse attempt is `ERR_DUPLICATE_STUDENT_REF`), the student's `full_name`, date of birth `dob` as an ISO date, `home_language` as an ISO code, optional `subgroup_tags` used for reporting (for example `FOSTER_YOUTH`, `ELL`, `LOW_INCOME`, defaulting to an empty list), and an optional `efc_band` of `LOW`, `MID`, or `HIGH` (defaulting to `MID`). New seniors arrive with `dependency_status` of `DEPENDENT`, `match_status` of `UNMATCHED`, and `fafsa_status` of `NO_RECORD`. The senior list can be browsed with filters on `school_id`, `match_status`, `fafsa_status`, and `subgroup_tag`; coordinator listings are scoped to the coordinator's own school, and consent masking (§2.6) applies to both list and detail reads.

In parallel, the `DataImporter` lands the state aid agency's data. Each aid record is imported under a `campaign_id` — the campaign must exist (`ERR_CAMPAIGN_NOT_FOUND`) but may be in any state — with the agency's student key `external_ref` (unique per campaign — duplicates draw `ERR_DUPLICATE_EXTERNAL_REF`), the `full_name` and `dob` as reported on the aid record (both plain values, `dob` as an ISO date), the `school_code` and `district_code` the agency has on file, and two values that seed the record's status history: `initial_status` and its `effective_date`, an ISO date. Import creates the record's first status event from those two values, and the projection rules of §3.4 apply from that very first event. Each subsequent status event appends an entry naming the aid record (`aid_record_id`), a `fafsa_status` of `STARTED`, `SUBMITTED`, `VERIFICATION_SELECTED`, or `COMPLETE`, the `effective_date` (an ISO date) on which the status took effect at the source agency, and an optional free-form `source` batch label (defaulting to `IMPORT`). Aid records and their events are browsable with filters on `campaign_id` and `current_status`; events list chronologically — `effective_date` ascending, ties broken by `created_at`.

### 3.4. The Aid-Status Projection and Deadline Classification

An aid record's `current_status` is never written directly; it is a projection over its event stream. When a new status event arrives, it is always stored, but it moves the projection only when its `effective_date` is on or after the record's current `last_effective_date` — an older-dated event is retained in the log yet leaves the projection untouched. The winning event is the one with the greatest `effective_date`, with ties broken in favor of the later `created_at`; the winner's status becomes `current_status` and its date becomes `last_effective_date`.

The projection matters because it propagates. Whenever the winning event changes `current_status` on an aid record that a `CONFIRMED` or `AUTO_CONFIRMED` match link points at, the linked senior's `fafsa_status` follows the same value — the senior axis mirrors the confirmed link's record — and each such transition recomputes `submitted_at` and `deadline_classification` and may fire the verification or auto-resolution cascades below. Once a link is invalidated, the senior's last known `fafsa_status` is retained as history, but later agency events no longer propagate.

The `submitted_at` of a senior is the earliest `effective_date` among the linked aid record's events whose status is `SUBMITTED`, `VERIFICATION_SELECTED`, or `COMPLETE`; it stays `null` when the senior has no confirmed link or no such event. From it, `deadline_classification` is derived at day granularity with inclusive upper bounds: `null` submission means `NOT_SUBMITTED`; a submission on or before the campaign's `state_grant_deadline` is `ON_TRACK_STATE`; a submission after the state deadline but on or before the `federal_deadline` is `STATE_MISSED_FEDERAL_OPEN`; anything later is `LATE`.

Two cascades ride the senior axis. Whenever a senior's status becomes `VERIFICATION_SELECTED` — whether arriving from `NO_RECORD`, `STARTED`, or `SUBMITTED` — the verification cascade fires: unless that senior already has a non-terminal verification case, the system opens a support case of type `VERIFICATION_FOLLOWUP` and runs the specialist selector (§3.9); if the senior lacks a `GRANTED` consent with `STATUS_DETAIL` scope at that moment, the new case starts `PAUSED` with `previous_status` of `OPEN` rather than actionable. And whenever a senior's status becomes `COMPLETE` from `SUBMITTED` or `VERIFICATION_SELECTED`, the auto-resolution cascade fires: any verification case of that senior in `OPEN`, `IN_REVIEW`, `AWAITING_FAMILY`, or `ESCALATED` is resolved on the spot with `resolution_outcome` of `VERIFICATION_COMPLETED`, and the assigned specialist's `active_case_count` is decremented. The remaining axis transitions are simple bookkeeping: any advance among `NO_RECORD`, `STARTED`, `SUBMITTED`, and `COMPLETE` — including the agency-correction retreat from `VERIFICATION_SELECTED` back to `SUBMITTED` — recomputes `submitted_at` and `deadline_classification` without firing either cascade, and an event that leaves the senior's status unchanged (a repeat of the current value) mutates nothing at all.

### 3.5. Match Review: Scoring, Bands, and Link Decisions

Reconciling the school roster with agency data is the `MatchReviewer`'s job. Proposing a match names a `senior_record_id` and an `aid_record_id` and must carry `expected_senior_record_version` per §2.8. The two records must belong to the same campaign — the senior's school's campaign must equal the aid record's campaign — or the proposal fails with `ERR_CROSS_CAMPAIGN_REFERENCE`; and a senior may have at most one non-terminal link at a time, so proposing while a `SUGGESTED`, `AUTO_CONFIRMED`, or `CONFIRMED` link still stands is refused with `ERR_LINK_ALREADY_EXISTS`. These two checks run in a pinned order for this endpoint: the one-non-terminal-link rule is evaluated before the cross-campaign rule, so a proposal that violates both draws `ERR_LINK_ALREADY_EXISTS`.

Scoring is deterministic and happens once, at creation, then freezes. Four boolean components are evaluated and recorded in the link's `score_components`: `dob_exact` compares the senior's `dob` to the aid record's `dob` exactly; `name_exact` compares `full_name` values case-insensitively after trimming; `school_code_match` compares the senior's school's `school_code` to the aid record's `school_code`; and `district_match` compares the school's `district_code` to the aid record's `district_code`. The `match_score` is the sum of the weights of the true components — 0.40 for an exact date of birth, 0.35 for an exact name, 0.15 for a school-code match, 0.10 for a district match — computed in exact tenths arithmetic so the score lands on a value from 0.00 to 1.00 with the weights summing to exactly 1.00. The parent campaign's thresholds then assign the link's initial `status`: a score at or above `auto_confirm_threshold` starts `AUTO_CONFIRMED`; a score at or above `review_floor` but below the auto-confirm threshold starts `SUGGESTED`; anything below `review_floor` starts `AUTO_REJECTED` and is terminal on arrival.

Every link creation mutates the senior record's `version` — by one for an `AUTO_REJECTED` proposal, and by two for a `SUGGESTED` or `AUTO_CONFIRMED` proposal (one increment for the creation bookkeeping, one for the match-axis advance) — which is exactly why the OCC rule of §2.8 exists. The band decides what else happens. An `AUTO_CONFIRMED` link immediately drives the senior's match axis from `UNMATCHED` to `MATCHED` with the full matched cascade: `current_match_link_id` is set to the link, `fafsa_status` initializes from the linked aid record's `current_status`, `submitted_at` and `deadline_classification` recompute, the verification cascade fires if that initial status is `VERIFICATION_SELECTED` and differs from the senior's status immediately before the link, and a document checklist is generated (§3.9). A `SUGGESTED` link merely moves the senior's match axis to `SUGGESTED` and awaits human judgment: the reviewer may confirm it, moving the link from `SUGGESTED` to `CONFIRMED` and firing the identical matched cascade, or reject it, moving the link from `SUGGESTED` to the terminal `REJECTED` and returning the senior's match axis to `UNMATCHED`. Acting on a link that is not `SUGGESTED` draws `ERR_MATCH_LINK_NOT_SUGGESTED`. Finally, a reviewer may invalidate a link in `CONFIRMED` or `AUTO_CONFIRMED` — any other state draws `ERR_MATCH_LINK_NOT_CONFIRMED` — moving it to the terminal `INVALIDATED` and unwinding the senior: `current_match_link_id` clears to `null`, the match axis returns to `UNMATCHED`, the senior's document checklist is archived with its items frozen, and the retained `fafsa_status` stops following the agency stream per §3.4.

### 3.6. Consent Records and Their Cascades

Consent is the campaign's privacy keystroke, recorded by the student's own school coordinator. Creating a consent names a `senior_record_id`, a non-empty `scopes` list (an empty list or an unknown scope value is `ERR_INVALID_REQUEST`), and the `granted_by` party — `PARENT` or `ADULT_STUDENT` — with an optional `expires_at` that defaults to `null` for no expiry. The record starts `GRANTED`, and at most one consent may be `GRANTED` for a senior at any time: creating a second while one is active, or regranting while another is active, is refused with `ERR_CONSENT_ALREADY_ACTIVE`. A successful grant recomputes `data_visibility` and may flip the senior from `RESTRICTED` to `NORMAL`; when it does flip — including on a first-time grant carrying `STATUS_DETAIL` — the resume half of the regrant cascade below fires as well: each `PAUSED` case of the senior returns to its captured `previous_status` with the specialist's `active_case_count` re-incremented, while cancelled registrations stay cancelled.

Revocation is where the cascade lives. Revoking requires the consent to be `GRANTED` (otherwise `ERR_CONSENT_NOT_GRANTED`) and sets it to `REVOKED`; the same cascade fires when the clock passes a consent's `expires_at` and flips it to `EXPIRED`. The senior's `data_visibility` drops to `RESTRICTED`, and that flip propagates: every support case of the senior in `OPEN`, `IN_REVIEW`, `AWAITING_FAMILY`, or `ESCALATED` moves to `PAUSED` with its prior state captured in `previous_status`, and each pause decrements the assigned specialist's `active_case_count` with overload recovery re-evaluated; and every `REGISTERED` event registration of the senior is cancelled, freeing capacity.

Regranting is the mirror, but an asymmetric one. It requires the consent to be `REVOKED` (`ERR_CONSENT_NOT_REVOKED`) and no other `GRANTED` consent to exist for the senior (`ERR_CONSENT_ALREADY_ACTIVE`). Visibility returns to `NORMAL`, and each `PAUSED` case of the senior resumes to its captured `previous_status` — which is then cleared to `null` — while the specialist's `active_case_count` re-increments with overload re-evaluated; the caseload invariant guarantees a revoke-then-regrant round trip returns the count to its exact pre-revoke value. Cancelled event registrations, however, are not restored — a family that was signed up must be registered again.

### 3.7. Completion Events: Scheduling, Staffing, and Budget

A coordinator mobilizes families through completion events, created for their own school while the school is `ENROLLED` (else `ERR_SCHOOL_NOT_ENROLLED`) and the campaign is `OPEN` or `STATE_GRACE` (else `ERR_CAMPAIGN_NOT_OPEN`). An event is defined by its `school_id`, a `title`, a half-open window from `start_time` to `end_time` (the end must be strictly after the start, else `ERR_EVENT_WINDOW_INVALID`; the start must be strictly in the future, both at creation and again at publish, else `ERR_EVENT_IN_PAST`), a `capacity` of at least one for family registrations, a `cost_estimate_cents`, a `required_expert_count` of zero or more aid experts the event must field, and the `supported_languages` the event promises to cover (possibly empty). Events are born `DRAFT`, and `actual_cost_cents` stays `null` until completion.

Publishing an event is the campaign's heaviest gate. Six preconditions must all hold, evaluated in this order, and they interlock with the campaign ledger: the parent campaign is `OPEN` or `STATE_GRACE` (`ERR_CAMPAIGN_NOT_OPEN`); the event is `DRAFT` (`ERR_EVENT_NOT_DRAFT`); its `start_time` is still in the future (`ERR_EVENT_IN_PAST`); no other `PUBLISHED` or `IN_PROGRESS` event at the same school sits within a thirty-minute venue buffer — windows that overlap or leave a gap of less than thirty minutes conflict, while a gap of exactly thirty minutes is allowed — (`ERR_EVENT_OVERLAP_BUFFER`); the committed staffing invariant holds (`ERR_STAFFING_INVARIANT_NOT_MET`); and the budget check passes — committed budget plus this event's `cost_estimate_cents` must not exceed `total_budget_cents` (`ERR_BUDGET_EXCEEDED`, HTTP 402). On success, the campaign's `committed_budget_cents` rises by the estimate, and the campaign's `version` increments.

The staffing invariant deserves its own paragraph because it is evaluated twice, differently. An event exposes a computed `staffing_coverage` object on every read with two blocks over the same assignments: the `committed` block counts only `CONFIRMED` assignments, while the `pipeline` block optimistically counts `ACCEPTED` and `CONFIRMED` together. Each block reports `expert_ratio` — confirmed (or pipeline) `EXPERT` assignments divided by the larger of `required_expert_count` and one, rounded half-up to two decimals — `staff_count` of qualifying assignments of any role, and `language_complete`, true when every language in `supported_languages` is held by at least one qualifying assignee. Publishing consults the committed view only: the count of `CONFIRMED` `EXPERT` assignments must be at least `required_expert_count`, and every supported language must be covered by at least one `CONFIRMED` assignee. When `required_expert_count` is zero and `supported_languages` is empty, the invariant is trivially satisfied, and the ratio fields remain display-only.

Unpublishing returns a `PUBLISHED` event to `DRAFT` (`ERR_EVENT_NOT_PUBLISHED` otherwise): the budget commitment is released and the campaign's `version` increments again, all `REGISTERED` registrations are cancelled, and staff assignments are left unchanged. When the clock reaches `start_time`, a `PUBLISHED` event slides into `IN_PROGRESS` on its own. Cancelling is allowed from `DRAFT` or `PUBLISHED` (anything else is `ERR_EVENT_NOT_CANCELLABLE`): every non-terminal assignment — `INVITED`, `ACCEPTED`, or `CONFIRMED` — is cancelled with confirmed hours released, every `REGISTERED` registration is cancelled, and a published event additionally releases its commitment; the publish-then-cancel round trip returns `budget_balance_cents` to its exact pre-publish value.

Completion is the fiscal and attendance reckoning. Only an `IN_PROGRESS` event can complete (`ERR_EVENT_NOT_IN_PROGRESS`), and the coordinator submits the `actual_cost_cents` spent. The fiscal gate runs first: spent budget plus this actual cost must not exceed `total_budget_cents` (`ERR_BUDGET_EXCEEDED`). On success the ledger shifts — `committed_budget_cents` falls by the estimate while `spent_budget_cents` rises by the actual — and attendance is settled: assignments still `INVITED` or `ACCEPTED` are cancelled, while every `CONFIRMED` assignment that never checked in is marked `NO_SHOW`, releasing its hours from `confirmed_hours_total`, incrementing the staff member's `no_show_count`, and firing the suspension contagion of §3.2 when the campaign's `no_show_limit` is reached.

### 3.8. Staffing Events and Registering Families

Filling an event starts with invitations: the coordinator creates a staff assignment naming an `event_id`, a `staff_profile_id`, and an `assigned_role` of `VOLUNTEER` or `EXPERT`. The event must be `DRAFT` or `PUBLISHED` (`ERR_EVENT_NOT_CANCELLABLE` otherwise); the staff member and event must belong to the same campaign (`ERR_CROSS_CAMPAIGN_REFERENCE`); an `EXPERT` assignment requires the `AID_EXPERT` capability (`ERR_STAFF_LACKS_CAPABILITY`); only one non-terminal assignment may exist for a given event-and-staff pair (`ERR_DUPLICATE_ASSIGNMENT`); and a pre-check rejects a staff member whose existing `CONFIRMED` or `CHECKED_IN` commitments overlap the event's window (`ERR_STAFF_DOUBLE_BOOKED`). These checks are evaluated in the order named here — event state, cross-campaign membership, capability, duplicate, then the double-booking pre-check — notwithstanding the generic step numbering of §2.9. Overlap is judged on half-open windows: two windows conflict when each starts before the other ends, and windows that merely touch endpoints do not conflict.

The invitation lifecycle is a partnership between coordinator and staff member. The staff member answers their own invitation — the assignment's `staff_profile_id` must equal the caller's `X-User-ID`, else `ERR_OWNERSHIP_VIOLATION` — accepting from `INVITED` to `ACCEPTED` or declining to the terminal `DECLINED`; acting on a non-`INVITED` assignment draws `ERR_ASSIGNMENT_NOT_INVITED`. The coordinator then confirms an `ACCEPTED` assignment (otherwise `ERR_ASSIGNMENT_NOT_ACCEPTED`) after two gates: the member's `background_check_status` must be `CLEARED` (`ERR_BACKGROUND_CHECK_NOT_CLEARED`), and the double-booking check runs again against the member's current `CONFIRMED` and `CHECKED_IN` commitments, since schedules may have moved since the invitation. Confirmation accrues `duration_hours` — the event's window length in hours, computed as the difference between `end_time` and `start_time` in seconds divided by 3600 and rounded half-up to two decimal places — onto `confirmed_hours_total`. Once the parent event is `IN_PROGRESS`, the coordinator checks confirmed staff in, moving `CONFIRMED` to the terminal `CHECKED_IN` (wrong assignment state: `ERR_ASSIGNMENT_NOT_CONFIRMED`; event not running: `ERR_EVENT_NOT_IN_PROGRESS`). The coordinator may cancel an assignment in `INVITED`, `ACCEPTED`, or `CONFIRMED` (else `ERR_ASSIGNMENT_NOT_CANCELLABLE`); cancelling a confirmed one releases its hours exactly.

Families sign up through event registrations naming an `event_id` and a `senior_record_id`. Registration requires the event to be `PUBLISHED`, the senior's school to be `ENROLLED`, a `GRANTED` consent carrying the `OUTREACH` scope for that senior (`ERR_CONSENT_REQUIRED`), no existing `REGISTERED` registration for the same event and senior (`ERR_DUPLICATE_REGISTRATION`), and room within `capacity` — a registration arriving when the event's count of `REGISTERED` registrations already equals or exceeds `capacity` is refused with `ERR_EVENT_FULL` (a registration that takes the final open seat succeeds). A registration lives as `REGISTERED` until the coordinator cancels it (any other state: `ERR_REGISTRATION_NOT_ACTIVE`) or a cascade — event cancel, unpublish, consent loss, or campaign close — cancels it first; `CANCELLED` is terminal.

### 3.9. Document Checklists, Support Cases, and Resolution

The matched cascade of §3.5 generates each senior's document checklist automatically. The checklist copies its `language` from the senior's `home_language` at generation, and its `template_key` is keyed on the senior's `dependency_status` at that moment: `DEPENDENT_STANDARD` — items in the order `STUDENT_ID`, `STUDENT_TAX_RETURN`, `PARENT_TAX_RETURN`, `BANK_STATEMENT` — for dependent students, or `INDEPENDENT_STANDARD` — `STUDENT_ID`, `STUDENT_TAX_RETURN`, `DEPENDENCY_OVERRIDE_FORM` — for independents, with items created in template order. Each item is addressed by its `checklist_id`, carries its `doc_type`, and starts `PENDING`; an item's `waivable` flag is computed as true exactly when its `doc_type` is `BANK_STATEMENT` or `DEPENDENCY_OVERRIDE_FORM`.

The checklist's own status is derived from its items: it starts `GENERATED`, moves to `IN_PROGRESS` when the first item leaves `PENDING`, reaches `COMPLETE` when every item stands in `VERIFIED` or `WAIVED`, and can fall back from `COMPLETE` to `IN_PROGRESS` if regeneration appends new `PENDING` items. Item work is coordinator-driven: receiving moves an item from `PENDING` — or from `REJECTED`, giving families a second chance — to `RECEIVED` (any other item state draws `ERR_ITEM_NOT_PENDING`, and any item operation against an `ARCHIVED` checklist draws `ERR_CHECKLIST_ARCHIVED`); from `RECEIVED` the coordinator verifies to `VERIFIED` or rejects to `REJECTED` (either action on a non-`RECEIVED` item draws `ERR_ITEM_NOT_RECEIVED`); every item mutation re-evaluates the checklist status. Waiving is specialist work: a specialist moves a `PENDING` item to `WAIVED` only if the item is `waivable` (else `ERR_ITEM_NOT_WAIVABLE`, HTTP 422) and the acting specialist holds a non-terminal support case for that senior (else `ERR_CASE_NOT_FOUND_FOR_SPECIALIST`). If the senior's match link is ever invalidated, the checklist — whatever its state — is archived and its items freeze.

Support cases come in two `case_type` flavors. Verification cases are auto-created by the cascade of §3.4; a coordinator may also open a case manually with a `senior_record_id`, a `case_type`, and optional free-form `notes` — opening a `SPECIAL_CIRCUMSTANCE` referral moves a `DEPENDENT` senior's `dependency_status` to `PENDING_REVIEW` (an already `PENDING_REVIEW` or `INDEPENDENT` senior is unchanged). One non-terminal case per senior-and-type pair is the limit (`ERR_CASE_ALREADY_OPEN`). Either way, creation runs the specialist selector, and the consent-gated start of §3.4 applies to manual openings too: when the senior lacks a `GRANTED` consent with `STATUS_DETAIL` scope at creation, the new case starts `PAUSED` with `previous_status` of `OPEN` and does not yet count toward its assignee's caseload. The candidate pool is the campaign's staff profiles holding the `CASE_SPECIALIST` capability and currently `ACTIVE`; ranking prefers a language match on the senior's `home_language`, then the lower `active_case_count`, then the earlier `created_at` as the final tie-break (equal timestamps broken by creation order) — never any identifier. The winner's `assigned_specialist_id` is recorded on the case, its `active_case_count` increments when the case starts in an active status, and crossing strictly above `max_caseload` flips the winner to `OVERLOADED` per §3.2. An empty pool leaves `assigned_specialist_id` as `null` and the case in `OPEN` until a `CampaignAdmin` assigns a `specialist_id` manually — the assignee must be `ACTIVE` with the `CASE_SPECIALIST` capability (`ERR_STAFF_LACKS_CAPABILITY`), and reassignment shifts caseload counters between the old and new specialists with overload re-evaluated. The assign action carries no case-state precondition — even a terminal case may be (re)assigned — and the counters shift only while the case stands in an active (`OPEN`, `IN_REVIEW`, `AWAITING_FAMILY`, `ESCALATED`) status.

Case work belongs to the assigned specialist and nobody else (every action verifies the caller against `assigned_specialist_id`, else `ERR_OWNERSHIP_VIOLATION`). Accepting moves `OPEN` to `IN_REVIEW` and requires a non-null assignee (`ERR_CASE_UNASSIGNED`); requesting documents moves `IN_REVIEW` to `AWAITING_FAMILY`; documents arriving move `AWAITING_FAMILY` back to `IN_REVIEW`; escalation lifts either `IN_REVIEW` or `AWAITING_FAMILY` to `ESCALATED`. Every case action requires the case to be in the state the action expects — acting on a `PAUSED`, terminal, or otherwise wrong-state case draws `ERR_CASE_NOT_ACTIONABLE` — and each specialist case action evaluates its checks in a pinned order: case state first (`ERR_CASE_NOT_ACTIONABLE`), then the presence of an assignee (`ERR_CASE_UNASSIGNED`), then the ownership comparison (`ERR_OWNERSHIP_VIOLATION`). Resolution is possible from `IN_REVIEW` or `ESCALATED`, and its preconditions are polymorphic on `case_type`: a `VERIFICATION_FOLLOWUP` case resolves only when the senior's checklist stands `COMPLETE` (`ERR_CHECKLIST_NOT_COMPLETE` — a senior with no non-archived checklist at all fails the same way), and its `resolution_outcome` is forced to `VERIFICATION_COMPLETED`; a `SPECIAL_CIRCUMSTANCE` case requires the caller to supply a `resolution_outcome` of `INDEPENDENT_CONFIRMED` or `NOT_QUALIFIED` (`ERR_DETERMINATION_REQUIRED` when absent or invalid). Resolving decrements the specialist's `active_case_count` with overload recovery re-evaluated.

A special-circumstance determination lands on the senior record. `INDEPENDENT_CONFIRMED` moves `dependency_status` from `DEPENDENT` or `PENDING_REVIEW` to `INDEPENDENT` and regenerates the checklist to the `INDEPENDENT_STANDARD` template: items whose `doc_type` has no place in the new template and that still sit in `PENDING` or `REJECTED` are auto-waived, items already `RECEIVED` or `VERIFIED` are kept, any new-template items not yet present are appended in `PENDING`, and the checklist status is re-evaluated — a `COMPLETE` checklist can legitimately fall back to `IN_PROGRESS`. If the senior has no non-archived checklist at all (for example a `SPECIAL_CIRCUMSTANCE` case opened before any match), the regeneration is a no-op and no checklist is created. `NOT_QUALIFIED` instead returns a `PENDING_REVIEW` senior to `DEPENDENT`, leaving the checklist alone. The pause-and-resume machinery of §3.6 completes the case lifecycle: `PAUSED` cases remember `previous_status` and restore it on regrant, and cases swept up in a campaign close move to `CANCELLED`, which like `RESOLVED` is terminal.

### 3.10. Completion Reporting and School Recognition

The `CampaignAdmin` measures the initiative through completion reports, generated while the campaign is `OPEN` or `STATE_GRACE` (`ERR_CAMPAIGN_NOT_OPEN` otherwise) by naming a `campaign_id` and a `variant` — `SUBMISSION_BASED` or `PROCESSED_BASED`. Generation freezes everything: rows and totals are computed once and stored, never recomputed on read. A new report starts `GENERATED`.

Eligibility is consent-first. A senior counts as eligible for a report when all three hold: the senior's `match_status` is `MATCHED`; a `GRANTED` consent carrying the `DATA_SHARE` scope exists for the senior; and the senior's school is `ENROLLED`. Completion depends on the variant: `SUBMISSION_BASED` counts a senior whose `fafsa_status` is `SUBMITTED`, `VERIFICATION_SELECTED`, or `COMPLETE` — intent to file is enough — while `PROCESSED_BASED` counts only `COMPLETE`, fully processed filings. Separately, a senior met the state deadline when `submitted_at` is non-null and falls on or before the `state_grant_deadline`.

The report's `rows` array breaks eligible seniors down along three dimensions — `LANGUAGE` keyed on `home_language`, `EFC_BAND`, and `SCHOOL` keyed on the school's id and name joined by a single space — with each surviving row carrying `dimension`, `key`, `eligible_count`, `completed_count`, `state_deadline_met_count`, and a `rate` computed as the row's completed count divided by its eligible count, multiplied by 1000, rounded half-up, then divided by 10 — yielding a one-decimal percentage. Privacy suppression is strict less-than: a row whose `eligible_count` is below the campaign's `min_subgroup_size` is omitted from `rows` entirely, while a row exactly at the floor survives. Surviving rows are ordered by `dimension`, then `key`, both ascending. Campaign-wide totals are computed from unsuppressed data — suppressed students still count in the totals — and appear as `eligible_count` and `completed_count` on the report, with `overall_rate` derived from those totals by the same multiply-round-divide recipe, or `null` when the campaign has zero eligible seniors. The rounding order is pinned: the overall rate always comes from the totals, never from averaging the rounded row rates.

Publishing is the campaign's second OCC-guarded write. The report must be `GENERATED` (`ERR_REPORT_NOT_GENERATED`), the campaign must be `OPEN` or `STATE_GRACE` (`ERR_CAMPAIGN_NOT_OPEN`), and the request must carry `expected_campaign_version` matching the campaign's current `version` (`ERR_STALE_VERSION`). Publication supersedes: whichever report of the same campaign currently stands `PUBLISHED` flips to `SUPERSEDED`, the campaign's `version` increments by one, and recognition tiers are recomputed for every school of the campaign.

Recognition ranking is deliberately self-referential but pinned to a strict evaluation order. First, each `ENROLLED` school's raw rate is computed exactly as a `SUBMISSION_BASED` completion rate for that school's own eligible seniors, to one decimal. Second, the ranking pool is cut to schools whose eligible-senior count is at least the campaign's `min_recognition_seniors`; a school with zero eligible seniors has no defined rate and never enters the pool, and every school outside the pool is stamped `UNRATED` and excluded from the distribution. Third, the pool's rates are sorted ascending, and two cutoffs are read by nearest-rank: the gold cutoff is the value at the one-based index of the pool size multiplied by 0.70 rounded up, and the silver cutoff is the value at the one-based index of the pool size multiplied by 0.40 rounded up. Finally each ranked school takes `GOLD` when its rate is at least the gold cutoff, `SILVER` when at least the silver cutoff, and `BRONZE` otherwise — boundaries are inclusive, so a rate exactly equal to a cutoff takes the higher tier. A school's own rate participates in setting its cutoffs; the fixed order of rates, then cutoffs, then tiers keeps the result well-defined.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions, background-check recording, and the clock advance — return `200 OK`. Request payloads, preconditions, and side effects for each operation are specified in §2 and §3; this table is the address map and authorization matrix only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; fires time-driven transitions | CampaignAdmin |
| POST | `/fafsa/campaigns` | Create a campaign in `DRAFT` | CampaignAdmin |
| GET | `/fafsa/campaigns` | List campaigns (paginated) | All six roles |
| GET | `/fafsa/campaigns/{id}` | Get a campaign including computed budget fields | All six roles |
| POST | `/fafsa/campaigns/{id}/activate` | Activate a `DRAFT` campaign to `OPEN` | CampaignAdmin |
| POST | `/fafsa/schools` | Create a school in `INVITED` | CampaignAdmin |
| GET | `/fafsa/schools` | List schools, filterable by `campaign_id` and `status` | All six roles |
| GET | `/fafsa/schools/{id}` | Get a school including `recognition_tier` | All six roles |
| POST | `/fafsa/schools/{id}/enroll` | Enroll an `INVITED` school | CampaignAdmin |
| POST | `/fafsa/schools/{id}/suspend` | Suspend an `ENROLLED` school with event cascades | CampaignAdmin |
| POST | `/fafsa/schools/{id}/reinstate` | Reinstate a `SUSPENDED` school | CampaignAdmin |
| POST | `/fafsa/staff-profiles` | Create a staff profile (`ACTIVE`, vetting `PENDING`) | CampaignAdmin |
| GET | `/fafsa/staff-profiles` | List staff profiles, filterable by `campaign_id` and `status` | All six roles |
| GET | `/fafsa/staff-profiles/{id}` | Get a staff profile including computed counters | All six roles |
| POST | `/fafsa/staff-profiles/{id}/background-check` | Record a background-check outcome | CampaignAdmin |
| POST | `/fafsa/senior-records` | Add a senior to the school list | SchoolCoordinator |
| GET | `/fafsa/senior-records` | List seniors, filterable; coordinator-scoped; consent-masked | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer |
| GET | `/fafsa/senior-records/{id}` | Get a senior; status quartet masked without `STATUS_DETAIL` consent | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer |
| POST | `/fafsa/aid-records` | Import an aid record with its initial status event | DataImporter |
| GET | `/fafsa/aid-records` | List aid records, filterable by `campaign_id` and `current_status` | CampaignAdmin, MatchReviewer, DataImporter |
| GET | `/fafsa/aid-records/{id}` | Get an aid record including projection fields | CampaignAdmin, MatchReviewer, DataImporter |
| POST | `/fafsa/aid-records/{id}/status-events` | Append a status event; projection and cascades may fire | DataImporter |
| GET | `/fafsa/aid-records/{id}/status-events` | List an aid record's status events chronologically | CampaignAdmin, MatchReviewer, DataImporter |
| POST | `/fafsa/match-links` | Propose a match link; score computed; OCC on the senior | MatchReviewer |
| GET | `/fafsa/match-links` | List match links, filterable by `senior_record_id`, `aid_record_id`, `status` | CampaignAdmin, MatchReviewer, DataImporter |
| GET | `/fafsa/match-links/{id}` | Get a match link including `score_components` | CampaignAdmin, MatchReviewer, DataImporter |
| POST | `/fafsa/match-links/{id}/confirm` | Confirm a `SUGGESTED` link; fires the matched cascade | MatchReviewer |
| POST | `/fafsa/match-links/{id}/reject` | Reject a `SUGGESTED` link | MatchReviewer |
| POST | `/fafsa/match-links/{id}/invalidate` | Invalidate a `CONFIRMED`/`AUTO_CONFIRMED` link | MatchReviewer |
| POST | `/fafsa/consent-records` | Grant consent for a senior | SchoolCoordinator |
| GET | `/fafsa/consent-records` | List consents, filterable by `senior_record_id` and `status` | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer |
| GET | `/fafsa/consent-records/{id}` | Get a consent record | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer |
| POST | `/fafsa/consent-records/{id}/revoke` | Revoke a `GRANTED` consent with pause/cancel cascade | SchoolCoordinator |
| POST | `/fafsa/consent-records/{id}/regrant` | Regrant a `REVOKED` consent; resumes paused cases | SchoolCoordinator |
| POST | `/fafsa/events` | Create a completion event in `DRAFT` | SchoolCoordinator |
| GET | `/fafsa/events` | List events, filterable by `school_id` and `status` | All six roles |
| GET | `/fafsa/events/{id}` | Get an event including `staffing_coverage` | All six roles |
| POST | `/fafsa/events/{id}/publish` | Publish a `DRAFT` event; commits budget | SchoolCoordinator |
| POST | `/fafsa/events/{id}/unpublish` | Return a `PUBLISHED` event to `DRAFT`; releases budget | SchoolCoordinator |
| POST | `/fafsa/events/{id}/cancel` | Cancel a `DRAFT`/`PUBLISHED` event with cascades | SchoolCoordinator |
| POST | `/fafsa/events/{id}/complete` | Complete an `IN_PROGRESS` event; records actual cost and no-shows | SchoolCoordinator |
| POST | `/fafsa/staff-assignments` | Invite staff to an event | SchoolCoordinator |
| GET | `/fafsa/staff-assignments` | List assignments, filterable by `event_id`, `staff_profile_id`, `status` | CampaignAdmin, SchoolCoordinator, StaffMember, Specialist |
| GET | `/fafsa/staff-assignments/{id}` | Get an assignment | CampaignAdmin, SchoolCoordinator, StaffMember, Specialist |
| POST | `/fafsa/staff-assignments/{id}/accept` | Accept an invitation (self only) | StaffMember |
| POST | `/fafsa/staff-assignments/{id}/decline` | Decline an invitation (self only) | StaffMember |
| POST | `/fafsa/staff-assignments/{id}/confirm` | Confirm an `ACCEPTED` assignment; vetting and booking gates | SchoolCoordinator |
| POST | `/fafsa/staff-assignments/{id}/cancel` | Cancel a non-terminal assignment; releases hours | SchoolCoordinator |
| POST | `/fafsa/staff-assignments/{id}/check-in` | Check in a `CONFIRMED` assignment on a running event | SchoolCoordinator |
| POST | `/fafsa/event-registrations` | Register a senior for a published event | SchoolCoordinator |
| GET | `/fafsa/event-registrations` | List registrations, filterable by `event_id`, `senior_record_id`, `status` | CampaignAdmin, SchoolCoordinator, Specialist |
| GET | `/fafsa/event-registrations/{id}` | Get a registration | CampaignAdmin, SchoolCoordinator, Specialist |
| POST | `/fafsa/event-registrations/{id}/cancel` | Cancel a `REGISTERED` registration | SchoolCoordinator |
| GET | `/fafsa/document-checklists` | List checklists, filterable by `senior_record_id` and `status` | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer |
| GET | `/fafsa/document-checklists/{id}` | Get a checklist | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer |
| GET | `/fafsa/document-checklists/{id}/items` | List a checklist's items in template order | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer |
| POST | `/fafsa/checklist-items/{id}/receive` | Mark a `PENDING`/`REJECTED` item `RECEIVED` | SchoolCoordinator |
| POST | `/fafsa/checklist-items/{id}/verify` | Verify a `RECEIVED` item | SchoolCoordinator |
| POST | `/fafsa/checklist-items/{id}/reject` | Reject a `RECEIVED` item | SchoolCoordinator |
| POST | `/fafsa/checklist-items/{id}/waive` | Waive a waivable `PENDING` item (case-holding specialist) | Specialist |
| POST | `/fafsa/support-cases` | Open a support case; selector auto-assigns | SchoolCoordinator |
| GET | `/fafsa/support-cases` | List cases, filterable by `senior_record_id`, `assigned_specialist_id`, `status`, `case_type` | CampaignAdmin, SchoolCoordinator, Specialist |
| GET | `/fafsa/support-cases/{id}` | Get a support case | CampaignAdmin, SchoolCoordinator, Specialist |
| POST | `/fafsa/support-cases/{id}/assign` | Assign or reassign the specialist | CampaignAdmin |
| POST | `/fafsa/support-cases/{id}/accept` | Accept an `OPEN` case (assigned specialist only) | Specialist |
| POST | `/fafsa/support-cases/{id}/request-documents` | Move an `IN_REVIEW` case to `AWAITING_FAMILY` | Specialist |
| POST | `/fafsa/support-cases/{id}/documents-received` | Return an `AWAITING_FAMILY` case to `IN_REVIEW` | Specialist |
| POST | `/fafsa/support-cases/{id}/escalate` | Escalate an `IN_REVIEW`/`AWAITING_FAMILY` case | Specialist |
| POST | `/fafsa/support-cases/{id}/resolve` | Resolve an `IN_REVIEW`/`ESCALATED` case with per-type gates | Specialist |
| POST | `/fafsa/completion-reports` | Generate a report with frozen rows and totals | CampaignAdmin |
| GET | `/fafsa/completion-reports` | List reports, filterable by `campaign_id` and `status` | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer, DataImporter |
| GET | `/fafsa/completion-reports/{id}` | Get a report including its `rows` | CampaignAdmin, SchoolCoordinator, Specialist, MatchReviewer, DataImporter |
| POST | `/fafsa/completion-reports/{id}/publish` | Publish a `GENERATED` report; OCC on the campaign; supersedes and re-tiers | CampaignAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status map only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_SCHOOL_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_SCHOOL_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_PROFILE_NOT_FOUND` | 404 Not Found |
| `ERR_SENIOR_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_AID_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_MATCH_LINK_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKLIST_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKLIST_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPORT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLETION_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CAMPAIGN_NOT_DRAFT` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 Conflict |
| `ERR_SCHOOL_NOT_INVITED` | 409 Conflict |
| `ERR_SCHOOL_NOT_ENROLLED` | 409 Conflict |
| `ERR_SCHOOL_NOT_SUSPENDED` | 409 Conflict |
| `ERR_EVENT_NOT_DRAFT` | 409 Conflict |
| `ERR_EVENT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_EVENT_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_EVENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_INVITED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_MATCH_LINK_NOT_SUGGESTED` | 409 Conflict |
| `ERR_MATCH_LINK_NOT_CONFIRMED` | 409 Conflict |
| `ERR_CASE_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_CASE_UNASSIGNED` | 409 Conflict |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_ITEM_NOT_PENDING` | 409 Conflict |
| `ERR_ITEM_NOT_RECEIVED` | 409 Conflict |
| `ERR_CHECKLIST_ARCHIVED` | 409 Conflict |
| `ERR_REPORT_NOT_GENERATED` | 409 Conflict |
| `ERR_CONSENT_NOT_GRANTED` | 409 Conflict |
| `ERR_CONSENT_NOT_REVOKED` | 409 Conflict |
| `ERR_CONSENT_REQUIRED` | 403 Forbidden |
| `ERR_BACKGROUND_CHECK_NOT_CLEARED` | 409 Conflict |
| `ERR_CROSS_CAMPAIGN_REFERENCE` | 422 Unprocessable Entity |
| `ERR_EVENT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_EVENT_IN_PAST` | 409 Conflict |
| `ERR_STAFF_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_EVENT_OVERLAP_BUFFER` | 409 Conflict |
| `ERR_DUPLICATE_STUDENT_REF` | 409 Conflict |
| `ERR_DUPLICATE_EXTERNAL_REF` | 409 Conflict |
| `ERR_LINK_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_CONSENT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CASE_ALREADY_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_EVENT_FULL` | 409 Conflict |
| `ERR_STAFFING_INVARIANT_NOT_MET` | 409 Conflict |
| `ERR_STAFF_LACKS_CAPABILITY` | 409 Conflict |
| `ERR_ITEM_NOT_WAIVABLE` | 422 Unprocessable Entity |
| `ERR_CASE_NOT_FOUND_FOR_SPECIALIST` | 409 Conflict |
| `ERR_CHECKLIST_NOT_COMPLETE` | 409 Conflict |
| `ERR_DETERMINATION_REQUIRED` | 400 Bad Request |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

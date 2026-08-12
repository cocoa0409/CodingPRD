# Campus Recruiting API — Product Requirements Document

## 1. Introduction

Corporate university recruiting runs on a yearly rhythm that looks simple from the outside and is anything but: pick the schools, show up on campus, collect a flood of applications, screen them down, run interview days, get offers out before competing employers do, and then convert the best interns into full-time hires. Each stage has its own failure modes — interviewers assigned to their own alma mater's candidates, offers that linger past their deadline and sour the school's trust, housing stipends promised against a budget nobody is tracking, mentors quietly overloaded past the number of interns they can actually support.

This document specifies the Campus Recruiting API, a service that manages one full pass through that rhythm per **recruiting season**: the school target list and campus event calendar, application intake and screening at scale, interview-day logistics with evaluator governance, offer drafting under a dual-variant exploding-deadline policy, a housing and relocation stipend ledger with reservation and release semantics, intern project staffing with mentor pairing, mid and final intern evaluations that drive the return-offer decision, and a conversion funnel that reports how the season performed. All endpoints are mounted under `/campus-recruiting`. The intended reader is an engineer implementing the service; every behavioral rule in this document is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity. The system recognizes exactly six roles, spelled as follows: `RecruitingAdmin`, `Recruiter`, `Candidate`, `Evaluator`, `Mentor`, and `Anonymous`. A request whose headers are missing, or whose `X-User-Role` is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403), as is any failed entity-backed ownership check described below.

Three roles are **entity-backed**, meaning `X-User-ID` is the `id` of a persisted record and ownership checks compare resource fields against it:

- When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting Candidate record. Ownership checks on any resource that references a candidate compare the resource's candidate foreign key to `X-User-ID`: submitting an application requires the payload's `candidate_id` to equal `X-User-ID`; withdrawing an application and accepting or declining an offer require `X-User-ID` to equal the underlying application's `candidate_id`; and a `Candidate` may read only its own candidate record, applications, offers, interview slots, and project assignments.
- When `X-User-Role` is `Evaluator`, `X-User-ID` is the `id` of the acting Employee record. An evaluator may submit or revise an interview evaluation only for a slot whose `evaluator_id` equals `X-User-ID`, and may read only its own employee record, its own interview slots, and the evaluations tied to those slots.
- When `X-User-Role` is `Mentor`, `X-User-ID` is the `id` of the acting Employee record. A mentor may submit an intern evaluation only for a project assignment whose `mentor_id` equals `X-User-ID`; the server records that identity on the evaluation as `submitted_by_mentor_id`. A mentor may read only its own employee record, its own project assignments, and the intern evaluations of those assignments.

The remaining three roles carry an **opaque** operator identifier not tied to any persisted entity. When `X-User-Role` is `RecruitingAdmin` (the program administrator who owns season configuration, the school target list, exploding-offer exceptions, and the logical clock) or `Recruiter` (the university-recruiting operator who runs screening, interview logistics, offers, projects, and conversion recording), `X-User-ID` is not compared against any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise opaque; the `Anonymous` role is admitted on exactly one operation, candidate self-registration, and nowhere else.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the host wall clock (never the logical clock of §2.5).
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

Requests to an unknown path, and requests to a known path with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404); any otherwise-unhandled internal failure surfaces as `ERR_VALIDATION` (HTTP 400).

---

### 2.3. Pagination and List Conventions

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. A `limit` that is not an integer or falls outside 1..100, or an `offset` that is not an integer or is negative, is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order; resources that share a creation timestamp retain their creation (insertion) order. The `meta` object of a list response includes `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

Several list endpoints accept optional filters that narrow the result set: the season list filters by `status`; a season's school targets filter by `tier` and `status`; a season's campus events filter by `school_target_id`, `event_type`, and `status`, while a single school's events filter by `status`; a candidate's application history filters by `season_id` and `status`; a season's applications filter by `school_target_id` and `status`, and a single school's applications by `status`; an evaluator's interview slots, a mentor's project assignments, and a season's intern projects and interview days each filter by `status`; a day's or an application's interview slots filter by `status`. All other list endpoints paginate without filters. Filter values are matched literally against the stored field; an unrecognized filter value simply yields an empty page rather than an error.

### 2.4. Season Epochs and the Posture Gate

A recruiting season moves through six statuses — `DRAFT`, `OPEN`, `SELECTION`, `OFFER_PERIOD`, `INTERN_ACTIVE`, and `CLOSED` — and the season's current status acts as a global posture gate: most write operations are only permitted while the season occupies a specific epoch, and a request made under the wrong posture is rejected with `ERR_SEASON_POSTURE_FORBIDDEN` (HTTP 409). The posture map is fixed:

- Application submission requires the season to be `OPEN`.
- Screening decisions, interview-day creation, day locking, slot booking, slot cancellation, no-show marking, and interview-evaluation submission and revision require `SELECTION`.
- Campus event scheduling, completion, and cancellation require `OPEN` or `SELECTION`.
- Dropping a school from the target list requires `DRAFT`, `OPEN`, or `SELECTION`.
- Offer creation and recruiter rejection of a decision-pending application require `SELECTION` or `OFFER_PERIOD`.
- Offer extension, candidate acceptance and decline, and admin-granted deadline extensions require `OFFER_PERIOD` or `INTERN_ACTIVE`.
- Stipend disbursement, project-assignment creation, unassignment, and completion, intern-evaluation submission, and return-offer-outcome recording require `INTERN_ACTIVE`.

Operations absent from this map — candidate withdrawal, offer rescission and expiry, interview-day completion, project closure, offer terms revision, school-target patching, school-target creation, employee registration, and intern-project creation — are not posture-gated; they are governed by their own state and temporal rules. Season advancement and closure carry their own epoch gates (§3.1, §3.8).

### 2.5. The Logical Clock

All temporal rules in this document — application and offer windows, screening as-of instants, exploding-offer deadlines — read a server-maintained **logical clock**, never the host wall clock. Before it has ever been set, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `RecruitingAdmin` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`; once set, the clock reads the supplied instant and never falls back to wall-clock time on its own.

### 2.6. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. Creation timestamps — and the initial `updated_at` — are stamped from the logical clock of §2.5.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any modification of the resource. Refreshes after creation are stamped from the host wall clock.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource, and that anchors the optimistic concurrency rules of §2.9.

The same rendering — ISO 8601 UTC with exactly three fractional digits — applies to every other timestamp the server emits, including the season's application, interview, and offer window bounds, the interview day's `window_start_at`/`window_end_at`, campus-event and interview-slot `start_at`/`end_at`, the candidate's `expected_graduation_date`, the offer's `extended_at` and `deadline_at`, and the clock endpoint's `current_utc`.

The **InternEvaluation** resource is the single exception: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.7. Nested Resource Retrieval

Requests that address nested resources — a school target, application, or interview day beneath a season; a slot beneath a day; an evaluation beneath a slot — are validated strictly left-to-right along the path: the season's existence is confirmed before the school target's, which is confirmed before any child resource beneath it. The first path identifier that does not correspond to an existing resource aborts the request with `ERR_NOT_FOUND` (HTTP 404), and no later segment is examined after a failure. Creation and modification of a child resource therefore never proceed against a parent that does not exist.

### 2.8. Precision, Rounding, and Monetary Representation

All monetary amounts — the season stipend pool, stipend disbursements, offer pay terms, and computed total compensation — are integer numbers of cents; the stipend and ledger arithmetic is pure integer arithmetic with no rounding at any step. The screening score is likewise integer arithmetic with no rounding. Exploding-offer deadline arithmetic operates at second precision with no sub-second rounding. Two computations use decimal rounding: the return-offer weighted score is rounded half-up to two decimal places, and the conversion rates are rounded half-up to four decimal places. Total compensation rounds each component half-up to integer cents individually before summing (§3.6); the two roundings are deliberately per-component rather than applied once to the final sum.

### 2.9. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, and both require a version field as a non-optional input.

Revising an offer's terms through `PUT /campus-recruiting/offers/{id}` requires the request to carry `expected_offer_version` holding the `version` of the offer as the client last observed it. If the value does not match the offer's current `version` — because another writer has already revised the terms, or a decline-and-revise cycle has advanced the version since the client's last read — the request is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412), preventing the client from silently superseding terms it has not observed.

Patching a school target's configuration through `PATCH /campus-recruiting/school-targets/{id}` requires `expected_school_target_version` to match the school target's current `version`. Tier edits feed the final variant of the screening score, so a stale read-modify-write would clobber a configuration change that screening decisions have already observed; a mismatched version is rejected with `ERR_STALE_SCHOOL_TARGET_VERSION` (HTTP 412). Endpoints not named in this section do not take a version field.

### 2.10. Stored Counters, Seat Ledgers, and Derived Invariants

Rather than recounting history on every read, the server maintains a set of stored counters and ledger totals, updated transactionally as side effects of the operations that change them:

- On the season: `applications_total_count` (incremented by one on every application created in the season), `offers_extended_count` (incremented by one whenever an offer enters `EXTENDED`), `offers_accepted_count` (incremented by one whenever an offer enters `ACCEPTED`), `completed_assignments_count` (incremented by one whenever a project assignment enters `COMPLETED`), `return_offers_extended_count` (incremented by one whenever a final intern evaluation computes a return-offer decision of `EXTENDED`), and `return_offers_accepted_count` (incremented by one whenever a return-offer outcome of `ACCEPTED` is recorded).
- The season's stipend ledger keeps two totals with strict invariants: `stipend_reserved_cents` always equals the sum of `amount_cents` over all stipend disbursements of the season in `RESERVED` status, and `stipend_disbursed_cents` always equals the same sum over disbursements in `DISBURSED` status. Both start at zero.
- On an interview day, `booked_count` always equals the number of its slots in `BOOKED`, `COMPLETED`, or `NO_SHOW` status — a no-show continues to consume its seat.
- On an intern project, `assigned_count` always equals the number of its project assignments in `ACTIVE` or `COMPLETED` status; on an employee acting as mentor, `assigned_intern_count` is the same count over assignments they mentor.
- On a candidate, `is_alumnus` is a derived flag: it begins `false` and becomes `true` once any project assignment tied to one of the candidate's applications has reached `COMPLETED`.

Every one of these counters and totals starts at zero (or `false`) when its owning resource is created.

### 2.11. Evaluation Order of Validation Rules

When several rules apply to a single request, the server evaluates them in a fixed order and reports the first failure: (1) authentication of the `X-User-ID` and `X-User-Role` headers; (2) role authorization for the endpoint; (3) entity-backed ownership; (4) left-to-right path existence; (5) request body shape — required fields present, types valid, enum members recognized, and ranges honored (interview scores and intern ratings are integers between 1 and 5 inclusive; capacities and hour fields are at least 1; cent amounts are at least 0 with the weekly pay rate strictly positive; an interval's end is strictly later than its start — the interval rule applies to campus-event, interview-day, and interview-slot intervals, while the season's six window bounds are accepted as supplied with no cross-check between them; relocation distance and prior-internship counts are at least 0; required string fields must be non-empty, and a field explicitly set to null counts as absent), with violations rejected as `ERR_VALIDATION` (HTTP 400); (6) the optimistic-concurrency version checks of §2.9; (7) the season posture gate of §2.4; (8) the season advance and close gates; (9) entity state gates (application, offer, interview day, slot, campus event, disbursement, project, assignment); (10) the business-safety rules — conflict of interest before calibration before segregation of duties before capability flags; (11) temporal window rules; (12) business constraints — uniqueness, caps, and overlaps; and finally (13) the fiscal stipend-budget check, which is always evaluated last. An earlier failure masks every later check: the response carries the error of the first failed rule only. Three concretizations pin how this skeleton meets a concrete request. First, a path-addressed resource's existence (rule 4) is confirmed at the moment that resource is loaded, so an ownership rule over a path resource is evaluated immediately after that resource loads — a nonexistent path identifier reports `ERR_NOT_FOUND` even when ownership would also fail. Second, the identifying payload fields of the three submission operations — application submission, interview-evaluation submission, and intern-evaluation submission — are shape-validated as the body is parsed, ahead of the ownership comparison, so a missing or mistyped field there reports `ERR_VALIDATION` even when ownership would also fail; the existence of payload-referenced entities (the candidate and school target of an application submission, the application and evaluator of a slot booking, the application and mentor of an assignment creation) is confirmed after the ownership comparison and before the posture gate. Third, on the revision operations the gates named for the endpoint fire before the individual edit fields are validated and applied: on school-target patching the version match precedes edit-field validation, and on evaluation revision the ownership, season-posture, and day-state guards precede validation of the new score or recommendation.

## 3. Business Logic & Workflows

### 3.1. Season Configuration and the School Target List

A `RecruitingAdmin` opens a recruiting cycle by creating a season with a human-readable `name` (for example, "2027 Summer Internship Season") and its full temporal skeleton: `application_open_at` and `application_close_at` bound the application window at both ends inclusively; `interview_window_start_at` and `interview_window_end_at` bound where interview days may be placed; `offer_window_open_at` and `offer_window_close_at` bound when offers may be extended, again inclusively. The administrator also sets `shortlist_score_threshold` (an integer between 0 and 100 inclusive, the minimum final screening score that a shortlist decision requires) and `stipend_budget_cents` (the season's total housing and relocation stipend pool, at least 0). Three policy fields carry defaults: `exploding_offer_hours_default` is the offer lifetime in hours applied when a school has no override and defaults to 72; `deadline_policy_mode` selects the deadline variant and defaults to `WALL_CLOCK`, with `BUSINESS_HOURS` as the alternative; `max_extension_hours` caps the cumulative deadline-extension hours any single offer may receive and defaults to 72. All three must be at least 1 when supplied.

A new season begins in `DRAFT`. Advancing it is an explicit, admin-only action that moves the season one epoch per call along the chain `DRAFT → OPEN → SELECTION → OFFER_PERIOD → INTERN_ACTIVE`, incrementing the season's `version` each time, and each step has its own gate, enforced with `ERR_SEASON_ADVANCE_BLOCKED` (HTTP 409): leaving `DRAFT` requires at least one school target in `ACTIVE` status; leaving `OPEN` requires the logical clock to read strictly later than `application_close_at`; leaving `SELECTION` requires that no application in the season still sits in `SUBMITTED`; and leaving `OFFER_PERIOD` requires that no offer belonging to the season remains `EXTENDED`. There is no skipping and no going back. Attempting to advance from `INTERN_ACTIVE` or `CLOSED`, where the chain has no next epoch, is likewise rejected with `ERR_SEASON_ADVANCE_BLOCKED` (HTTP 409).

Against that skeleton, the administrator builds the **school target list**. Each target names a `school_name` — unique within the season, with case-sensitive comparison, a duplicate rejected with `ERR_VALIDATION` (HTTP 400) — and declares a `tier` of `CORE`, `TARGET`, or `EXPLORATORY` (which feeds the screening score), an `application_cap` of at least 1 (the maximum number of in-flight applications the school may hold), a `stipend_region` of `METRO`, `REGIONAL`, or `REMOTE` (which feeds both the stipend amount and the offer's compensation multiplier), and optionally an `exploding_offer_hours_override` — a per-school offer lifetime of at least 1 hour that, when set, replaces the season default for offers made to that school's applicants; when left unset, the season default applies. A school target starts `ACTIVE` and records its owning season as `season_id`, taken from the path.

Configuration of a target — its tier, cap, region, or override — is revised through the patching capability under the optimistic concurrency rule of §2.9: the request must carry `expected_school_target_version`, a mismatch is rejected with `ERR_STALE_SCHOOL_TARGET_VERSION`, the version match is evaluated before the individual edit fields are validated and applied, and a successful patch applies the supplied edits — supplying `null` for `exploding_offer_hours_override` clears the override and restores the season default — and increments the target's `version`. Tier edits deserve special care: the final screening variant reads the school's *current* tier at screening time, so a mid-season edit shifts the scores of applications not yet screened.

A school target's `status` is always one of `ACTIVE` or `DROPPED`. When a school leaves the target list, dropping it transitions the target `ACTIVE → DROPPED` and increments its `version`; the move is permitted only while the season is `DRAFT`, `OPEN`, or `SELECTION` and is otherwise rejected with `ERR_SEASON_POSTURE_FORBIDDEN`. Dropping a target that is not `ACTIVE` is rejected with `ERR_APPLICATION_STATE_FORBIDDEN` (HTTP 409). The drop cascades: every campus event of that school still in `SCHEDULED` status is cancelled. Because only completed events contribute to screening, cancelling the school's remaining scheduled events shrinks the engagement pool that future final-variant screening scores can draw on — a cancelled event can never complete — while provisional score snapshots already stored on applications are deliberately not recomputed.

### 3.2. Campus Events and the Engagement Record

Campus events are the season's top-of-funnel: a `RecruitingAdmin` or `Recruiter` schedules one under a season by supplying the hosting `school_target_id`, an `event_type` of `CAREER_FAIR`, `INFO_SESSION`, or `RESUME_DROP`, and a `start_at` and `end_at` bracketing the event, with `end_at` strictly later than `start_at`. Scheduling requires the season to be `OPEN` or `SELECTION`; the referenced school target is then resolved — an unknown `school_target_id`, or one belonging to a different season than the path's, is rejected with `ERR_NOT_FOUND` (HTTP 404) — and it must still be `ACTIVE`; scheduling against a dropped school is rejected with `ERR_SCHOOL_DROPPED` (HTTP 422).

Events of the same school may not overlap. Treating each event as the half-open interval from its `start_at` up to but not including its `end_at`, a new event is rejected with `ERR_EVENT_TIME_OVERLAP` (HTTP 409) when its interval intersects any existing event of the same school target in `SCHEDULED` or `COMPLETED` status. Two events that merely touch — one ending at exactly the instant the other begins — do not intersect and are allowed, and cancelled events never block anything.

After the event happens, marking it complete moves it `SCHEDULED → COMPLETED` and records the number of resumes collected from the payload's `resume_count` — a required integer of at least 0 in the completion payload; the field reads 0 until completion. Cancelling moves it `SCHEDULED → CANCELLED`. Both actions require the season to be `OPEN` or `SELECTION`, both require the event to still be `SCHEDULED` — acting on an already-terminal event is rejected with `ERR_EVENT_STATE_FORBIDDEN` (HTTP 409) — and each increments the event's `version`. Completion is what feeds screening: the screening score counts only events that have reached `COMPLETED`, so the engagement record builds up event by event as the season progresses.

### 3.3. Candidates and Application Intake

Candidates register themselves — the platform's one public operation, open to the `Anonymous` role — with an `email`, a `full_name`, and an `expected_graduation_date`. The email is globally unique across the platform, compared case-insensitively; a duplicate registration is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). The record carries an `is_alumnus` flag that begins `false` and later turns `true` when the candidate completes an internship assignment (§3.7), marking the alumni pipeline.

Once the season is `OPEN`, a candidate applies by submitting a payload containing their own `candidate_id` — which must equal the `X-User-ID` header, failing with `ERR_FORBIDDEN` otherwise — the `school_target_id` of the school they are applying from, and their one-way `relocation_distance_miles` (at least 0), which later feeds the stipend distance band. Two optional inputs shape the screening score: `prior_internship_count` (defaulting to 0) and a `referral_flag` (defaulting to `false`) marking an employee referral.

Submission is guarded by an ordered chain of checks. After the generic authentication, ownership, existence, and body-shape validation, the season posture must be `OPEN`; then the logical clock must read within the application window — at or after `application_open_at` and at or before `application_close_at`, both bounds inclusive — failing with `ERR_APPLICATION_WINDOW_CLOSED` (HTTP 422) outside it; then the candidate must not already hold an application in this season (`ERR_DUPLICATE_APPLICATION`, HTTP 409); then the school's cap is checked — counting every application of that school in this season whose status is anything other than `SCREENED_OUT` or `WITHDRAWN`, a count already equal to `application_cap` rejects the submission with `ERR_SCHOOL_APPLICATION_CAP_REACHED` (HTTP 422), so screened-out and withdrawn applications free their place but rejected, expired, and accepted ones keep counting; and finally the referenced school must still be `ACTIVE` (`ERR_SCHOOL_DROPPED`). A `candidate_id` or `school_target_id` that resolves to no existing record, or a school target belonging to a season other than the path's, is rejected with `ERR_NOT_FOUND` (HTTP 404).

A successful submission creates the application in `SUBMITTED` status, stamps its owning `season_id` from the path, computes the provisional screening score, and increments the season's `applications_total_count` by one.

The **screening score** is a weighted sum capped at 100 points: a tier weight of 40 for a `CORE` school, 25 for `TARGET`, or 10 for `EXPLORATORY`; plus 5 points for each qualifying completed campus event; plus 15 points when the application's `referral_flag` is set; plus 10 points per prior internship recorded in `prior_internship_count`. Qualifying events are those of the application's own school, in the same season, with status `COMPLETED`, whose `end_at` falls at or before the as-of instant; events still `SCHEDULED` and events `CANCELLED` (including those cancelled by a school drop) are excluded. The provisional variant, computed at submission and stored in `screening_score_provisional`, takes the application's own creation timestamp as its as-of instant and the school's tier as it then stood; it is a snapshot and is never recomputed afterwards. The final variant, computed at screening time, takes the current logical clock as its as-of instant and the school's *current* tier — so it diverges from the provisional snapshot whenever events completed, or the tier was edited, between submission and screening.

### 3.4. Screening Decisions and Application Movement

Screening happens in the `SELECTION` epoch, after the application window has closed. A `Recruiter` screens a `SUBMITTED` application by supplying a `decision` of `SHORTLIST` or `REJECT`; screening an application in any other status is rejected with `ERR_APPLICATION_STATE_FORBIDDEN` (HTTP 409), and the posture check fires before the status check. Either way, the final screening variant is computed and stored in `screening_score_final` — the field reads `null` until the first screening — but the two branches differ in what happens next, and the threshold check applies only to the shortlist branch. A `SHORTLIST` decision succeeds only when the freshly computed final score is at least the season's `shortlist_score_threshold` — below the bar it fails with `ERR_SCREENING_THRESHOLD_NOT_MET` (HTTP 422), yet the failed attempt still stores the computed final score and increments the application's `version` — and moves the application `SUBMITTED → SHORTLISTED`. A `REJECT` decision carries no threshold requirement and moves the application `SUBMITTED → SCREENED_OUT`, with the final score still computed and stored.

Later in the pipeline, a `Recruiter` may reject outright an application sitting in `DECISION_PENDING` — for instance after interviews conclude without an offer — moving it to `REJECTED`; this rejection is permitted while the season is in `SELECTION` or `OFFER_PERIOD`, and rejecting an application in any other status is rejected with `ERR_APPLICATION_STATE_FORBIDDEN` (HTTP 409).

The candidate, meanwhile, may withdraw their own application at any non-terminal point. Withdrawal requires `X-User-ID` to equal the application's `candidate_id` (`ERR_FORBIDDEN` otherwise) and is available from `SUBMITTED`, `SHORTLISTED`, `INTERVIEW_SCHEDULED`, `DECISION_PENDING`, and `OFFER_PENDING`; from the terminal statuses and from `ACCEPTED` it is rejected with `ERR_APPLICATION_STATE_FORBIDDEN`. Withdrawing from `SUBMITTED`, `SHORTLISTED`, or `DECISION_PENDING` simply sets `WITHDRAWN`. Withdrawing from `INTERVIEW_SCHEDULED` runs an ordered cascade: each of the application's `BOOKED` interview slots is first moved to `CANCELLED`, decrementing the owning day's `booked_count` by one apiece, with the auto-flip rule of §3.5 suppressed for the duration of the cascade; the application's status is set to `WITHDRAWN` only after the cancellations complete. Withdrawing from `OFFER_PENDING` runs the longest cascade: the `EXTENDED` offer is first moved to `DECLINED` with its usual application-flip side effect suppressed; then each `BOOKED` slot is cancelled with its `booked_count` decrement, again with auto-flip suppressed; and the application is set `WITHDRAWN` last.

### 3.5. Interview Logistics: Days, Slots, and Evaluations

Staffing comes first. A `RecruitingAdmin` registers each season's interviewers and mentors as employee records carrying a `full_name`, an `email` unique within the season under case-sensitive comparison — a duplicate rejected with `ERR_VALIDATION` (HTTP 400) — and an optional `alma_mater_school_name` used for conflict-of-interest screening. Capability and capacity knobs all carry defaults: `daily_slot_limit` (at least 1, default 6) caps how many slots an evaluator may hold per day; `max_interns` (at least 1, default 2) caps concurrent mentored interns; `can_evaluate` (default `true`) and `can_mentor` (default `true`) gate the two duties; and `calibrated` (default `false`) marks an evaluator cleared to interview `CORE`-tier candidates. Each employee's `assigned_intern_count` starts at 0.

Interview days are then carved out of the season's interview window: a `RecruitingAdmin` or `Recruiter` creates a day with `window_start_at`, `window_end_at` (strictly later than the start), and a seat `capacity` of at least 1. The day's window must be contained in the season's — `window_start_at` at or after the season's `interview_window_start_at`, and `window_end_at` at or before the season's `interview_window_end_at` — failing with `ERR_DAY_OUTSIDE_WINDOW` (HTTP 422) otherwise. Creation requires the `SELECTION` posture. A day begins `OPEN` with `booked_count` at 0, and each slot booked, cancelled, or marked no-show on the day drives that counter per the invariant of §2.10.

Booking a slot is the most heavily guarded write in the system. A `Recruiter` supplies the `application_id`, the `evaluator_id`, and the slot's `start_at` and `end_at`; the slot records its owning day as `interview_day_id` from the path. The application and evaluator are resolved by identifier alone; no rule requires them to belong to the day's season. After the generic checks, the guards fire in a fixed order: the season must be in `SELECTION`; the application must be `SHORTLISTED` or `INTERVIEW_SCHEDULED` (`ERR_APPLICATION_STATE_FORBIDDEN`); the day must still be `OPEN` (`ERR_DAY_STATE_FORBIDDEN`, HTTP 409); then the evaluator-governance trio — the evaluator's `alma_mater_school_name` must not equal the applicant school's `school_name`, compared case-insensitively with surrounding whitespace trimmed, and an evaluator with no `alma_mater_school_name` never conflicts (`ERR_EVALUATOR_CONFLICT_OF_INTEREST`, HTTP 422); an applicant from a `CORE`-tier school may only be assigned to a `calibrated` evaluator (`ERR_EVALUATOR_NOT_CALIBRATED`, HTTP 422); and the evaluator's `can_evaluate` flag must be set (`ERR_CAPABILITY_MISSING`, HTTP 422). Temporal checks follow: the slot must be contained in the day's window, starting at or after `window_start_at` and ending at or before `window_end_at` (`ERR_SLOT_OUTSIDE_DAY_WINDOW`, HTTP 422). Then the two conflict checks: the candidate's own schedule first — the new slot's half-open interval must not intersect any existing `BOOKED` slot of the same application on any day, touching boundaries permitted, else `ERR_CANDIDATE_SCHEDULE_CONFLICT` (HTTP 409) — and the evaluator's buffered schedule second: measured against the evaluator's `BOOKED` or `COMPLETED` slots on the same day, where the gap between two intervals is zero when they intersect and otherwise the time separating the earlier interval's end from the later interval's start, a gap of strictly less than 15 minutes rejects the booking with `ERR_EVALUATOR_SCHEDULE_CONFLICT` (HTTP 409), while a gap of exactly 15 minutes is allowed. Last come the two capacity checks, both reported as `ERR_DAY_AT_CAPACITY` (HTTP 422): the day's `booked_count` must still be below its `capacity`, and the evaluator's load on that day — their `BOOKED` and `COMPLETED` slots — must still be below their `daily_slot_limit`.

A successfully booked slot starts in `BOOKED`, the day's `booked_count` increments by one, and the first slot booked for an application moves it `SHORTLISTED → INTERVIEW_SCHEDULED`. From there, two slot dispositions exist, and both of them — like evaluation submission below — require the slot to still be `BOOKED`, failing with `ERR_SLOT_STATE_FORBIDDEN` (HTTP 409) once it has left that status. Cancelling a slot — the season-posture, day-state, and slot-state guards firing in that order, permitted only while the season is in `SELECTION` and the day is `OPEN` — moves it `BOOKED → CANCELLED` and decrements the day's `booked_count` by one, the compensating action of the booking. Marking a no-show — the same guard order, permitted while the season is in `SELECTION` and the day is `OPEN` or `LOCKED` — moves it `BOOKED → NO_SHOW` and leaves `booked_count` unchanged: a no-show consumes the seat.

Every slot status mutation re-evaluates the **auto-flip rule** for the slot's application: when the application is in `INTERVIEW_SCHEDULED` and every one of its slots has reached a terminal status (`COMPLETED`, `CANCELLED`, or `NO_SHOW`), the application flips back to `SHORTLISTED` if not a single slot completed, or forward to `DECISION_PENDING` if at least one did. Booking followed by cancelling every slot therefore cycles an application `SHORTLISTED → INTERVIEW_SCHEDULED → SHORTLISTED` without recruiter intervention.

A day is locked — `OPEN → LOCKED`, by a `Recruiter`, only while the season is in `SELECTION`, and locking a day that is not `OPEN` is rejected with `ERR_DAY_STATE_FORBIDDEN` (HTTP 409) — to freeze its book: no further bookings or cancellations are accepted once locked, though no-shows and evaluations still are. Completing a day requires it to be `LOCKED` and every one of its slots terminal (`COMPLETED`, `CANCELLED`, or `NO_SHOW`); the move to `COMPLETED` is otherwise rejected with `ERR_DAY_STATE_FORBIDDEN`. Locking and completing each increment the day's `version`.

Scoring belongs to the assigned evaluator alone. After the interview, the evaluator — whose `X-User-ID` must equal the slot's `evaluator_id` — submits an evaluation with an integer `score` between 1 and 5 inclusive and a `recommendation` of `STRONG_HIRE`, `HIRE`, `LEAN_NO`, or `NO_HIRE`. Submission requires the `SELECTION` posture, a day in `OPEN` or `LOCKED` status, and a slot still `BOOKED`. The evaluation records the slot as `interview_slot_id` (taken from the path) and denormalizes `evaluator_id` from the slot at submission; there is at most one evaluation per slot, so a slot's evaluation listing holds zero or one element. Submission moves the slot `BOOKED → COMPLETED` and re-evaluates the auto-flip rule. While the day remains `OPEN`, the evaluator may still revise the evaluation's `score` or `recommendation` — revision against a day that has left `OPEN` is rejected with `ERR_DAY_STATE_FORBIDDEN`, and the ownership, season-posture, and day-state guards fire before the revised values are themselves validated — and each revision increments the evaluation's `version`.

### 3.6. Offers, Exploding-Deadline Policy, and the Stipend Ledger

When interviews conclude, a `Recruiter` drafts an offer against a `DECISION_PENDING` application — drafting against any other application status is rejected with `ERR_APPLICATION_STATE_FORBIDDEN` — under a season posture of `SELECTION` or `OFFER_PERIOD`. There is at most one offer per application: a second drafting attempt fails with `ERR_OFFER_ALREADY_EXISTS` (HTTP 409), and the per-application offer listing therefore holds zero or one element. The draft carries `weekly_rate_cents` (strictly positive), `duration_weeks` (at least 1), and an optional `sign_on_bonus_cents` (at least 0, default 0), starts in `DRAFT` status, and computes its `total_comp_cents` at creation. Four fields stay `null` until the offer is extended — `policy_hours_snapshot`, `extended_at`, `deadline_at`, and `stipend_amount_cents` — while `extension_hours_granted` starts at 0.

Total compensation applies a region multiplier taken from the school target's current `stipend_region`: 1.25 for `METRO`, 1.10 for `REGIONAL`, and 1.00 for `REMOTE`. The salary component is the weekly rate multiplied by the number of weeks multiplied by the multiplier, rounded half-up to integer cents; the bonus component is the sign-on bonus multiplied by the multiplier, likewise rounded half-up to integer cents. `total_comp_cents` is then the sum of the two already-rounded components — the rounding is pinned per component first and the two integer-cent results are summed, never rounded once at the end. The figure is recomputed on every terms revision and again at extension.

Terms are revised while the offer is `DRAFT` or `DECLINED` — any other status is rejected with `ERR_OFFER_STATE_FORBIDDEN` (HTTP 409) — under the optimistic concurrency rule of §2.9: the request must carry `expected_offer_version`, a mismatch fails with `ERR_STALE_OFFER_VERSION`, and a successful revision updates the supplied terms, recomputes `total_comp_cents`, increments the offer's `version`, and, when the offer was `DECLINED`, returns it to `DRAFT`. The cycle `DRAFT → EXTENDED → DECLINED → DRAFT` is what makes re-negotiation possible after a candidate balks.

Extending the offer is the pivotal act, and its four guards fire in order: the season posture must be `OFFER_PERIOD` or `INTERN_ACTIVE`; the offer must be `DRAFT`; the application must be `DECISION_PENDING`; and the logical clock must read within the offer window — at or after `offer_window_open_at` and at or before `offer_window_close_at`, both inclusive — failing with `ERR_OFFER_WINDOW_CLOSED` (HTTP 422) outside it. Extension then pins `policy_hours_snapshot` to the school's `exploding_offer_hours_override` when one is set, and to the season's `exploding_offer_hours_default` otherwise; stamps `extended_at` with the current instant; computes `deadline_at` from the deadline policy; computes `stipend_amount_cents`; re-stores `total_comp_cents`; moves the application `DECISION_PENDING → OFFER_PENDING`; and increments the season's `offers_extended_count` by one.

The **exploding deadline** has two variants selected by the season's `deadline_policy_mode`. Under `WALL_CLOCK`, `deadline_at` is simply `extended_at` plus the pinned policy hours — nights and weekends count. Under `BUSINESS_HOURS`, `deadline_at` is the earliest instant such that the number of whole seconds in the half-open interval from `extended_at` up to but not including `deadline_at` whose starting instant falls inside business hours equals the pinned hours expressed in seconds, where business hours are Monday through Friday, from 09:00:00 UTC up to but not including 17:00:00 UTC; seconds outside that window do not count, so identical inputs yield a strictly later deadline than the wall-clock variant whenever the interval crosses any non-business second. The accept boundary is inclusive in both variants: acceptance succeeds when it arrives at or before `deadline_at`.

The **stipend amount** computed at extension combines three parts against a ceiling. The regional base is 300000 cents for a `METRO` school, 200000 for `REGIONAL`, and 100000 for `REMOTE`. A distance bonus of 150000 cents applies when the application's `relocation_distance_miles` is at least 1500 miles; failing that, 75000 cents when it is at least 500 miles; otherwise nothing. A surcharge of 50000 cents applies when the school is both `METRO` and `CORE` tier. `stipend_amount_cents` is the sum of base, distance bonus, and surcharge, capped at 400000 cents — the school's region and tier are read as they stand at extension time.

Every post-draft disposition of an offer — acceptance, decline, rescission, expiry, and deadline extension — requires the offer to be `EXTENDED`; attempting any of them against an offer in any other status is rejected with `ERR_OFFER_STATE_FORBIDDEN`. The candidate's answer arrives through two self-service actions, each requiring `X-User-ID` to equal the application's `candidate_id` and each permitted only in the `OFFER_PERIOD` or `INTERN_ACTIVE` posture. **Acceptance** runs its checks in order — ownership, posture, offer status, then the deadline: if the clock reads strictly later than `deadline_at`, the offer first flips `EXTENDED → EXPIRED` (with the conditional application cascade described below) and the request fails with `ERR_OFFER_EXPIRED` (HTTP 422); and finally the fiscal gate, evaluated last of all: the season's `stipend_reserved_cents` plus the offer's `stipend_amount_cents` must not exceed `stipend_budget_cents`, with equality permitted, else `ERR_STIPEND_BUDGET_EXCEEDED` (HTTP 422). A successful acceptance moves the offer `EXTENDED → ACCEPTED` and fires a two-level cascade: a stipend disbursement is created in `RESERVED` status with its `amount_cents` copied from the offer's `stipend_amount_cents` — immutable thereafter, and unique per offer, so the per-offer disbursement listing holds zero or one element and the disbursement's `offer_id` ties it back — and the season's `stipend_reserved_cents` increments by that amount; meanwhile the application moves `OFFER_PENDING → ACCEPTED`, which increments the season's `offers_accepted_count` by one. **Decline** moves the offer `EXTENDED → DECLINED` and conditionally cascades the application `OFFER_PENDING → DECISION_PENDING` — only when the application is currently `OFFER_PENDING`.

Two recruiter-facing dispositions mirror these. Rescinding — available to `Recruiter` and `RecruitingAdmin` alike, and not posture-gated — moves an `EXTENDED` offer to `RESCINDED` with the same conditional application cascade back to `DECISION_PENDING`; decline or rescind followed by revision and re-extension cycles the application between `DECISION_PENDING` and `OFFER_PENDING`. Expiring is a manual sweep: against an `EXTENDED` offer whose deadline has strictly passed, it moves the offer to `EXPIRED` and conditionally cascades the application `OFFER_PENDING → EXPIRED`; calling the sweep while the deadline has not yet passed — the clock reading at or before `deadline_at` — is rejected with `ERR_OFFER_NOT_YET_EXPIRED` (HTTP 422). Independently of the sweep, the system applies a lazy flip on the operations that observe the deadline: reading an offer — directly or through its application's offer listing — and the decline and rescind actions first move an `EXTENDED` offer whose `deadline_at` the clock reads strictly later than to `EXPIRED`, with the same conditional application cascade; the decline or rescind then fails with `ERR_OFFER_STATE_FORBIDDEN` (HTTP 409). The deadline-extension grant performs no such observation — an `EXTENDED` offer whose deadline has already passed may still be granted hours.

When a candidate asks for more time, a `RecruitingAdmin` may grant a deadline extension by supplying `additional_hours` of at least 1, under the `OFFER_PERIOD` or `INTERN_ACTIVE` posture against an `EXTENDED` offer. The grant accumulates into `extension_hours_granted`, and the running total plus the new grant must not exceed the season's `max_extension_hours` — equality is permitted — failing with `ERR_EXTENSION_CAP_EXCEEDED` (HTTP 422) beyond the cap. The granted hours shift `deadline_at` later by exactly that many whole hours on the wall clock, regardless of whether the season's policy mode is `WALL_CLOCK` or `BUSINESS_HOURS`.

The stipend ledger closes the loop. A `RESERVED` disbursement is paid out once interns are on site: disbursing — available to `Recruiter` and `RecruitingAdmin`, only while the season is `INTERN_ACTIVE`, and only against a disbursement still `RESERVED` (`ERR_DISBURSEMENT_STATE_FORBIDDEN`, HTTP 409, otherwise) — moves it `RESERVED → DISBURSED`, decrementing the season's `stipend_reserved_cents` by the disbursement's `amount_cents` and incrementing `stipend_disbursed_cents` by the same amount. The budget gate of acceptance therefore measures only currently reserved funds against the pool.

### 3.7. Intern Projects, Mentoring, and Return-Offer Decisions

Accepted interns are staffed onto **intern projects**, which a `RecruitingAdmin` or `Recruiter` creates under a season with a `title` and a seat `capacity` of at least 1. A project begins `OPEN` with `assigned_count` at 0; a `Recruiter` may later close it to new assignments — `OPEN → CLOSED`, incrementing its `version` — which has no effect on assignments already made.

Assignment creation is a `Recruiter` action in the `INTERN_ACTIVE` epoch whose payload names the intern's `application_id` and the proposed `mentor_id`; the assignment records its project as `intern_project_id` from the path. Its guards fire in order: the posture gate; the application must be `ACCEPTED` (`ERR_APPLICATION_STATE_FORBIDDEN`); the application and the mentor must belong to the project's season — cross-season references are rejected with `ERR_NOT_FOUND` (HTTP 404); the project must still be `OPEN` (`ERR_PROJECT_STATE_FORBIDDEN`, HTTP 409); then segregation of duties — the proposed mentor must not have submitted an evaluation on any interview slot of that application, failing with `ERR_MENTOR_CONFLICT_OF_INTEREST` (HTTP 422) — then the mentor's `can_mentor` capability (`ERR_CAPABILITY_MISSING`); then the two capacity checks, project first and mentor second: a project whose `assigned_count` has reached its `capacity` rejects with `ERR_PROJECT_AT_CAPACITY` (HTTP 422), and a mentor whose `assigned_intern_count` has reached their `max_interns` rejects with `ERR_MENTOR_AT_CAPACITY` (HTTP 422); and finally uniqueness — an application may hold at most one project assignment, so a second attempt fails with `ERR_ASSIGNMENT_EXISTS` (HTTP 409) and the per-application assignment listing holds zero or one element. A successful assignment starts `ACTIVE` with `return_offer_decision` and `return_offer_outcome` both `NONE`, and increments both the project's `assigned_count` and the mentor's `assigned_intern_count` by one.

Two exits exist from `ACTIVE`, both gated to the `INTERN_ACTIVE` posture and both rejecting a non-`ACTIVE` assignment with `ERR_ASSIGNMENT_STATE_FORBIDDEN` (HTTP 409). Unassigning moves the assignment to `UNASSIGNED`, decrements the project's `assigned_count` and the mentor's `assigned_intern_count` by one apiece — the compensating actions of the assignment — and freezes `return_offer_decision` and `return_offer_outcome` at whatever values they currently hold. Completing the internship requires a final intern evaluation to already exist for the assignment (`ERR_FINAL_EVALUATION_REQUIRED`, HTTP 422, otherwise); it moves the assignment to `COMPLETED`, increments the season's `completed_assignments_count` by one, leaves the capacity counts untouched — `assigned_count` and `assigned_intern_count` keep counting `COMPLETED` assignments — and flips the candidate's `is_alumnus` flag to `true`.

Intern evaluations belong to the assigned mentor: the `Mentor`'s `X-User-ID` must equal the assignment's `mentor_id`, and the server stamps it onto the evaluation as `submitted_by_mentor_id`. Each evaluation carries an `eval_type` of `MID` or `FINAL`, an integer `rating` between 1 and 5 inclusive, and a `would_rehire` flag, and references its assignment as `project_assignment_id` from the path. At most one evaluation of each type exists per assignment — a duplicate type is rejected with `ERR_EVALUATION_ALREADY_SUBMITTED` (HTTP 409) — and the assignment must still be `ACTIVE` when either is submitted. The two types are ordered: submitting the `FINAL` evaluation requires a `MID` evaluation to already exist on the same assignment, failing with `ERR_MID_EVALUATION_REQUIRED` (HTTP 422) otherwise, while the `MID` itself has no such prerequisite.

The `FINAL` evaluation is where the return-offer decision is computed. The weighted score combines the assignment's `MID` rating counted once with the just-submitted `FINAL` rating counted twice, divided by three, and the result is rounded half-up to two decimal places. The assignment's `return_offer_decision` becomes `EXTENDED` when that weighted score is at least 4.00 and the final evaluation's `would_rehire` is `true`; otherwise it becomes `NO_OFFER`. Whenever the decision lands on `EXTENDED`, the season's `return_offers_extended_count` increments by one.

Once a return offer has been extended, a `Recruiter` records the candidate's answer by supplying an `outcome` of `ACCEPTED` or `DECLINED`. Recording is permitted while the assignment is `ACTIVE` or `COMPLETED`, but only when `return_offer_decision` is `EXTENDED` and `return_offer_outcome` is still `NONE` — any other combination is rejected with `ERR_ASSIGNMENT_STATE_FORBIDDEN`. The outcome is written once to `return_offer_outcome`, and an `ACCEPTED` outcome increments the season's `return_offers_accepted_count` by one.

### 3.8. Season Close-Out and the Conversion Funnel

Closing the season is the final epoch transition, `INTERN_ACTIVE → CLOSED`, an admin-only action with a single gate: every project assignment in the season must have left `ACTIVE` — completed or unassigned — otherwise the close is rejected with `ERR_SEASON_CLOSE_BLOCKED` (HTTP 409). Closing a season whose status is not `INTERN_ACTIVE` is rejected with the same `ERR_SEASON_CLOSE_BLOCKED` (HTTP 409). A successful close increments the season's `version` and runs a two-front sweep. Every offer belonging to the season that is still `EXTENDED` moves to `EXPIRED`, and each such flip conditionally moves its application `OFFER_PENDING → EXPIRED` (only when the application is currently `OFFER_PENDING`). In parallel, every stipend disbursement of the season still in `RESERVED` status moves to `RELEASED`, and each release decrements the season's `stipend_reserved_cents` by the disbursement's `amount_cents` — reserved-but-undisbursed stipend money returns to the pool at close.

At any point in the lifecycle, a `RecruitingAdmin` or `Recruiter` may read the season's **conversion summary**, a computed funnel that reports the six stored counters — `applications_total_count`, `offers_extended_count`, `offers_accepted_count`, `completed_assignments_count`, `return_offers_extended_count`, and `return_offers_accepted_count` — together with the stipend ledger positions `stipend_budget_cents`, `stipend_reserved_cents`, and `stipend_disbursed_cents`, and two rates. The `conversion_rate_provisional` is the season's `return_offers_accepted_count` divided by its `offers_accepted_count`, rounded half-up to four decimal places; the `conversion_rate_final` divides the same numerator by `completed_assignments_count` instead, likewise rounded half-up to four decimal places. Either rate reports 0 when its own denominator is 0. Because the final rate's denominator counts only interns who finished their assignments — never more than the set of all accepted offers — the final rate is always at least the provisional one, and the two differ whenever any accepted intern has not yet completed an assignment.

## 4. Endpoint Definitions

Operations that create a new resource — a season, school target, campus event, candidate, application, employee, interview day, interview slot, evaluation, offer, intern project, project assignment, or intern evaluation — return `201 Created`. All other successful operations, including reads, state transitions, revisions, and the clock setter, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/campus-recruiting/_clock/set_current_utc` | Set the server's logical clock | RecruitingAdmin |
| POST | `/campus-recruiting/seasons` | Create a recruiting season (starts `DRAFT`) | RecruitingAdmin |
| GET | `/campus-recruiting/seasons` | List seasons (paginated, filterable by status) | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/seasons/{id}` | Get one season including ledger and counters | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/seasons/{id}/advance` | Advance the season one epoch | RecruitingAdmin |
| POST | `/campus-recruiting/seasons/{id}/close` | Close the season with offer-expiry and stipend-release cascades | RecruitingAdmin |
| GET | `/campus-recruiting/seasons/{id}/conversion-summary` | Computed conversion funnel and rates | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/seasons/{id}/school-targets` | Add a school to the season target list | RecruitingAdmin |
| GET | `/campus-recruiting/seasons/{id}/school-targets` | List school targets of a season | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/school-targets/{id}` | Get one school target | RecruitingAdmin, Recruiter |
| PATCH | `/campus-recruiting/school-targets/{id}` | Edit tier/cap/region/override with OCC | RecruitingAdmin |
| POST | `/campus-recruiting/school-targets/{id}/drop` | Drop a school; cancels its scheduled events | RecruitingAdmin |
| POST | `/campus-recruiting/seasons/{id}/campus-events` | Schedule a campus event | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/campus-events/{id}` | Get one campus event | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/seasons/{id}/campus-events` | List campus events of a season | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/school-targets/{id}/campus-events` | List campus events of one school target | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/campus-events/{id}/complete` | Mark an event completed and record resumes | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/campus-events/{id}/cancel` | Cancel a scheduled event | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/candidates` | Register a candidate | Anonymous |
| GET | `/campus-recruiting/candidates/{id}` | Get one candidate (Candidate reads only its own) | RecruitingAdmin, Recruiter, Candidate |
| GET | `/campus-recruiting/candidates/{id}/applications` | List a candidate's applications across seasons | RecruitingAdmin, Recruiter, Candidate |
| POST | `/campus-recruiting/seasons/{id}/applications` | Submit an application; computes the provisional score | Candidate |
| GET | `/campus-recruiting/applications/{id}` | Get one application | RecruitingAdmin, Recruiter, Candidate |
| GET | `/campus-recruiting/seasons/{id}/applications` | List applications of a season | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/school-targets/{id}/applications` | List applications from one school target | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/applications/{id}/screen` | Screening decision; computes the final score | Recruiter |
| POST | `/campus-recruiting/applications/{id}/reject` | Reject a decision-pending application | Recruiter |
| POST | `/campus-recruiting/applications/{id}/withdraw` | Candidate withdraws; cascades slots and offers | Candidate |
| POST | `/campus-recruiting/seasons/{id}/employees` | Register a staff member for the season | RecruitingAdmin |
| GET | `/campus-recruiting/seasons/{id}/employees` | List staff of a season | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/employees/{id}` | Get one staff member | RecruitingAdmin, Recruiter, Evaluator, Mentor |
| GET | `/campus-recruiting/employees/{id}/interview-slots` | List interview slots assigned to this evaluator | RecruitingAdmin, Recruiter, Evaluator |
| GET | `/campus-recruiting/employees/{id}/project-assignments` | List assignments mentored by this staff member | RecruitingAdmin, Recruiter, Mentor |
| GET | `/campus-recruiting/employees/{id}/evaluations` | List evaluations submitted by this evaluator | RecruitingAdmin, Recruiter, Evaluator |
| POST | `/campus-recruiting/seasons/{id}/interview-days` | Create an interview day within the season window | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/interview-days/{id}` | Get one interview day | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/seasons/{id}/interview-days` | List interview days of a season | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/interview-days/{id}/lock` | Lock a day to further bookings and cancels | Recruiter |
| POST | `/campus-recruiting/interview-days/{id}/complete` | Complete a locked day once all slots are terminal | Recruiter |
| GET | `/campus-recruiting/interview-days/{id}/interview-slots` | List slots of an interview day | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/interview-days/{id}/interview-slots` | Book an interview slot | Recruiter |
| GET | `/campus-recruiting/interview-slots/{id}` | Get one interview slot | RecruitingAdmin, Recruiter, Evaluator |
| POST | `/campus-recruiting/interview-slots/{id}/cancel` | Cancel a booked slot (frees the seat) | Recruiter |
| POST | `/campus-recruiting/interview-slots/{id}/no-show` | Mark a booked slot as no-show (seat stays consumed) | Recruiter |
| GET | `/campus-recruiting/applications/{id}/interview-slots` | List interview slots of an application | RecruitingAdmin, Recruiter, Candidate |
| POST | `/campus-recruiting/interview-slots/{id}/evaluations` | Submit the evaluation for a slot; completes the slot | Evaluator |
| PUT | `/campus-recruiting/evaluations/{id}` | Revise an evaluation while its day is still open | Evaluator |
| GET | `/campus-recruiting/evaluations/{id}` | Get one evaluation | RecruitingAdmin, Recruiter, Evaluator |
| GET | `/campus-recruiting/interview-slots/{id}/evaluations` | List evaluations of a slot (zero or one element) | RecruitingAdmin, Recruiter, Evaluator |
| POST | `/campus-recruiting/applications/{id}/offers` | Create a draft offer for a decision-pending application | Recruiter |
| GET | `/campus-recruiting/offers/{id}` | Get one offer | RecruitingAdmin, Recruiter, Candidate |
| GET | `/campus-recruiting/applications/{id}/offers` | List offers of an application (zero or one element) | RecruitingAdmin, Recruiter, Candidate |
| PUT | `/campus-recruiting/offers/{id}` | Revise offer terms with OCC on the offer version | Recruiter |
| POST | `/campus-recruiting/offers/{id}/extend` | Extend the offer; pins policy, deadline, stipend, comp | Recruiter |
| POST | `/campus-recruiting/offers/{id}/accept` | Candidate accepts; creates the reserved disbursement | Candidate |
| POST | `/campus-recruiting/offers/{id}/decline` | Candidate declines; application returns to decision-pending | Candidate |
| POST | `/campus-recruiting/offers/{id}/rescind` | Rescind an extended offer | Recruiter, RecruitingAdmin |
| POST | `/campus-recruiting/offers/{id}/expire` | Expire an extended offer past its deadline | Recruiter, RecruitingAdmin |
| POST | `/campus-recruiting/offers/{id}/extend-deadline` | Grant additional hours on an exploding offer | RecruitingAdmin |
| GET | `/campus-recruiting/offers/{id}/stipend-disbursements` | List disbursements of an offer (zero or one element) | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/stipend-disbursements/{id}` | Get one stipend disbursement | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/stipend-disbursements/{id}/disburse` | Disburse a reserved stipend | Recruiter, RecruitingAdmin |
| POST | `/campus-recruiting/seasons/{id}/intern-projects` | Create an intern project with a seat capacity | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/seasons/{id}/intern-projects` | List intern projects of a season | RecruitingAdmin, Recruiter |
| GET | `/campus-recruiting/intern-projects/{id}` | Get one intern project | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/intern-projects/{id}/close` | Close a project to new assignments | Recruiter |
| GET | `/campus-recruiting/intern-projects/{id}/project-assignments` | List assignments of a project | RecruitingAdmin, Recruiter |
| POST | `/campus-recruiting/intern-projects/{id}/project-assignments` | Assign an intern to a project with a mentor | Recruiter |
| GET | `/campus-recruiting/project-assignments/{id}` | Get one project assignment | RecruitingAdmin, Recruiter, Mentor |
| GET | `/campus-recruiting/applications/{id}/project-assignments` | List assignments of an application (zero or one element) | RecruitingAdmin, Recruiter, Candidate |
| POST | `/campus-recruiting/project-assignments/{id}/unassign` | Unassign an intern; frees project and mentor capacity | Recruiter |
| POST | `/campus-recruiting/project-assignments/{id}/complete` | Complete an internship once the final evaluation exists | Recruiter |
| POST | `/campus-recruiting/project-assignments/{id}/intern-evaluations` | Mentor submits a mid or final intern evaluation | Mentor |
| GET | `/campus-recruiting/project-assignments/{id}/intern-evaluations` | List intern evaluations of an assignment | RecruitingAdmin, Recruiter, Mentor |
| GET | `/campus-recruiting/intern-evaluations/{id}` | Get one intern evaluation | RecruitingAdmin, Recruiter, Mentor |
| POST | `/campus-recruiting/project-assignments/{id}/record-return-offer-outcome` | Record the candidate's response to a return offer | Recruiter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_SCHOOL_TARGET_VERSION` | 412 Precondition Failed |
| `ERR_STALE_OFFER_VERSION` | 412 Precondition Failed |
| `ERR_SEASON_POSTURE_FORBIDDEN` | 409 Conflict |
| `ERR_SEASON_ADVANCE_BLOCKED` | 409 Conflict |
| `ERR_SEASON_CLOSE_BLOCKED` | 409 Conflict |
| `ERR_APPLICATION_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_OFFER_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_DAY_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_SLOT_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_EVENT_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_DISBURSEMENT_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_PROJECT_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_ASSIGNMENT_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_EVALUATOR_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_EVALUATOR_NOT_CALIBRATED` | 422 Unprocessable Entity |
| `ERR_MENTOR_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_CAPABILITY_MISSING` | 422 Unprocessable Entity |
| `ERR_APPLICATION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DAY_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_SLOT_OUTSIDE_DAY_WINDOW` | 422 Unprocessable Entity |
| `ERR_OFFER_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_OFFER_NOT_YET_EXPIRED` | 422 Unprocessable Entity |
| `ERR_MID_EVALUATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_FINAL_EVALUATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_SCHOOL_APPLICATION_CAP_REACHED` | 422 Unprocessable Entity |
| `ERR_SCHOOL_DROPPED` | 422 Unprocessable Entity |
| `ERR_SCREENING_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_EVENT_TIME_OVERLAP` | 409 Conflict |
| `ERR_CANDIDATE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_EVALUATOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_DAY_AT_CAPACITY` | 422 Unprocessable Entity |
| `ERR_OFFER_ALREADY_EXISTS` | 409 Conflict |
| `ERR_EXTENSION_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROJECT_AT_CAPACITY` | 422 Unprocessable Entity |
| `ERR_MENTOR_AT_CAPACITY` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_EXISTS` | 409 Conflict |
| `ERR_EVALUATION_ALREADY_SUBMITTED` | 409 Conflict |
| `ERR_STIPEND_BUDGET_EXCEEDED` | 422 Unprocessable Entity |

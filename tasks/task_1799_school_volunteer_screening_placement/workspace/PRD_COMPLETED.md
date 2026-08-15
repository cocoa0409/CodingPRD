# School Volunteer Screening & Placement API — Product Requirements Document

## 1. Introduction

Public school districts rely on community volunteers — tutors, mentors, chaperones, drivers — and every hour those volunteers spend near students carries a compliance obligation. The depth of background screening must match the intensity of student contact, clearances must lapse and be renewed on a fixed cycle, orientation and safety training must be complete before service begins, campuses must know exactly who is inside the building at any moment, and the district must be able to act decisively when an incident is reported. Today the district volunteer office reconciles these obligations by hand, which makes expiry dates, training prerequisites, and restricted-role determinations easy to miss.

This document specifies a compliance-first REST API that runs the entire volunteer lifecycle for the district: application intake, background-check initiation and adjudication with restricted-role determination, training tracking, opportunity publishing and placement, campus check-in with daily badge issuance, service-hour logging and verification, a recognition and retention program, and incident-driven suspension, reinstatement, and removal. All time-dependent behavior — clearance expiry, training validity, opportunity windows, check-in windows — is evaluated against a controllable logical clock so that compliance transitions are deterministic and auditable. The API serves three acting roles: the district volunteer office, school-level campus administrators, and the volunteers themselves.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly three roles: `DistrictCoordinator`, `CampusAdmin`, and `Volunteer`. A request with missing or malformed headers, or whose declared role is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the targeted endpoint — or that fails a Volunteer-role ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three identities are bound to the request context differently. When `X-User-Role` is `DistrictCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `CampusAdmin`: an opaque staff identifier with no entity backing. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks on any resource that references a Volunteer compare the resource's foreign-key field — `volunteer_id` on placements, hour entries, and check-ins — to `X-User-ID`.

A `DistrictCoordinator` is district volunteer office staff and holds a superset of `CampusAdmin` powers, plus exclusive control over screening and district configuration: creating campuses, creating volunteer applications, initiating and adjudicating background checks and reading them, creating training modules, running the opportunity matching selector, revoking verified hour entries, adjudicating incident reports, granting manual recognition awards, and driving the logical clock. A `CampusAdmin` is a school-level administrator who manages opportunities (create, publish, cancel), confirms, cancels, and completes placements, records training completions, verifies or rejects hour entries, files incident reports, administers check-ins and check-outs, and reads the shared list endpoints. A `Volunteer` is a screened community member limited to self-service: requesting placements for themselves, logging hours against their own placements, cancelling their own placements, checking themselves in and out of campuses, and reading their own volunteer record, placements, hour entries, and check-ins, alongside browsing opportunities, campuses, and training modules.

Volunteer-role ownership is enforced on the following operations, and a caller whose `X-User-ID` does not match the volunteer that owns the target resource is rejected with `ERR_FORBIDDEN`: reading a volunteer record, requesting a placement (the payload `volunteer_id`), reading a placement, logging hours against a placement (the placement must belong to the caller), reading an hour entry, checking in at a campus (the payload `volunteer_id`, when supplied), reading a check-in, checking out a check-in, and cancelling a placement.

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

Requests to an undeclared path, or to a declared path with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it may not be less than 1 or greater than 100. The `offset` parameter says how many items to skip and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` broken by `id` ascending. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

### 2.4. Common Resource Properties and Derived-Field Reconciliation

Every primary resource is assigned an `id` at creation: a server-minted UUID with no type prefix. Every resource also records a `created_at` timestamp — an ISO 8601 UTC instant with three fractional digits. Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on any change to the resource's properties, and `version`, a system-managed integer that starts at 1 at creation — when `updated_at` equals `created_at` — and increments by one on every mutation. The full four-field set applies to the Volunteer, BackgroundCheck, Opportunity, Placement, HourEntry, VisitCheckIn, and IncidentReport resources. Configuration and append-only resources — Campus, TrainingModule, TrainingRecord, and RecognitionAward — carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. Client-supplied datetimes that the server persists — an opportunity's `starts_at` and `ends_at`, and a training record's `completed_at` — are normalized to the same UTC three-fractional-digit form rather than echoed verbatim.

Many fields in this system are derived rather than supplied: a volunteer's `clearance_expires_at`, `restriction_flags`, service-hour totals, `recognition_points`, and `recognition_tier`, and an opportunity's fill counts, among others. Derived fields are reconciled immediately, as part of the same operation that invalidates them — never lazily and never by a separate client call. When a write to one resource changes another resource (for example, verifying an hour entry changes the volunteer's totals, or a suspension cascade cancels placements), each affected resource is mutated independently: its own `updated_at` is refreshed and its own `version` is incremented by one. Several cascades in this document terminate at the Volunteer aggregate, and each such cascade increments the volunteer's `version` even though the triggering write targeted a different resource.

### 2.5. The Logical Clock and Scheduled Sweeps

All server-minted timestamps and all time-window comparisons in this system read a single logical clock, never the host's wall clock. This governs adjudication timestamps (`decided_at`), placement confirmation (`confirmed_at`), check-in and check-out instants (`checked_in_at`, `checked_out_at`), badge-day determination, clearance and training expiry evaluation, and every opportunity window comparison. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z; before any set call the clock continues to read this default and never falls back to wall-clock time.

A `DistrictCoordinator`-only, test-driving capability sets the logical clock to a supplied `to_iso8601` instant — any well-formed ISO 8601 instant is accepted, with no requirement that the new reading be later than the current one. Setting the clock runs a three-part sweep. First, every background check in `CLEARED` or `CLEARED_WITH_FLAGS` whose `expires_at` is at or before the new current time transitions to `EXPIRED`. Second, each affected volunteer's `clearance_expires_at` is recomputed, and every `ACTIVE` volunteer left without a valid clearance — meaning the recomputed value is null or is at or before the new current time — is demoted from `ACTIVE` to `RESCREEN_REQUIRED`, with each demoted volunteer's `version` incremented by one; an `ACTIVE` volunteer whose recomputed clearance remains valid is otherwise untouched, with no `version` increment. Third, every opportunity in `OPEN` whose `ends_at` is at or before the new current time transitions to `COMPLETED`. The capability responds with the new `current_utc` plus three sweep counters: `expired_check_count`, `volunteers_rescreened_count`, and `opportunities_completed_count`.

### 2.6. Clearance Levels and the Screening Decision Matrix

Background checks come in two depths: `BASIC`, which carries rank one, and `ENHANCED`, which carries rank two. A held check level is **adequate** for a required level whenever its rank is at least the rank of the required level — so an `ENHANCED` check satisfies either requirement, while a `BASIC` check satisfies only a `BASIC` requirement. A volunteer's required level, recorded at intake as `required_check_level`, is `BASIC` for a `SUPERVISED` contact type and `ENHANCED` for an `UNSUPERVISED` contact type. The same rank comparison decides opportunity gating: the volunteer's latest cleared check level must be adequate for the level implied by the opportunity's `required_contact_type`. For this gate, the latest cleared check is chosen from all of the volunteer's checks in `CLEARED` or `CLEARED_WITH_FLAGS` — regardless of level, and excluding any check that has since moved to `EXPIRED` — as the one with the latest `decided_at`, with ties broken in favor of the later-created check; a volunteer holding no such check has no latest cleared check and cannot pass this gate.

Adjudication resolves a pending check through a fixed decision matrix over the recorded `findings`. A finding of `DISQUALIFYING` always decides the check as `DENIED` with no restriction flags, regardless of level. A finding of `NONE` decides the check as `CLEARED` with an empty flag set. A finding of `MINOR` decides the check as `CLEARED_WITH_FLAGS` and assigns the flag `NO_TRANSPORT`, plus the additional flag `NO_ONE_ON_ONE` when the volunteer's `contact_type` is `UNSUPERVISED`. The volunteer's own branch is then decided by adequacy crossed with training compliance: an adequate cleared outcome with training complete activates the volunteer; an adequate cleared outcome with training incomplete grants clearance pending training; an outcome whose level is not adequate leaves the volunteer in its current screening state — the check still records `CLEARED` or `CLEARED_WITH_FLAGS`, but it does not advance the volunteer's clearance and it never feeds the volunteer's clearance expiry, because clearance expiry is computed only from adequate cleared checks. Whatever flags the matrix yields are stored on the volunteer's `restriction_flags` as a sorted array, a subset of `NO_TRANSPORT` and `NO_ONE_ON_ONE`, with an empty array when the findings are `NONE`.

A cleared check's `expires_at` is its `decided_at` plus the validity window for its `level`, measured as whole-day durations of twenty-four hours: seven hundred thirty days for a `BASIC` check — two years — and three hundred sixty-five days for an `ENHANCED` check — one year. The field stays null while the check is `PENDING`, and stays null permanently for a `DENIED` check. The volunteer-level `clearance_expires_at` is selected from the volunteer's checks that are in `CLEARED` or `CLEARED_WITH_FLAGS` with an adequate level: among that set the check with the latest `decided_at` wins, ties are broken in favor of the later-created check, and the winning check's `expires_at` becomes the volunteer's value. If the winning check has itself moved to `EXPIRED`, or the adequate cleared set is empty, the volunteer's `clearance_expires_at` is null.


### 2.7. Request Evaluation Pipeline and Validation Ordering

Every request is evaluated against a fixed, ordered pipeline of validation stages, and the first stage that fails determines the error returned — later stages are never consulted once an earlier one has rejected the request.

1. **Authentication.** Both headers are present and well formed, and the declared role is one of the three recognized roles; failures yield `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership.** The caller's role appears in the endpoint's role list, and every Volunteer-role ownership rule of §2.1 holds; failures yield `ERR_FORBIDDEN`.
3. **Existence.** Every identifier in the URL path resolves to an existing entity, validated strictly left to right, and then every foreign-key identifier in the request body resolves, validated in payload field order; the first unresolvable identifier yields `ERR_NOT_FOUND`.
4. **State preconditions.** The target resource sits in a status that permits the requested transition. Each entity family has its own rejection code: `ERR_VOLUNTEER_INVALID_STATE`, `ERR_CHECK_INVALID_STATE`, `ERR_OPPORTUNITY_INVALID_STATE`, `ERR_PLACEMENT_INVALID_STATE`, `ERR_HOUR_ENTRY_INVALID_STATE`, `ERR_CHECKIN_INVALID_STATE`, and `ERR_INCIDENT_INVALID_STATE`.
5. **Screening safety gates.** Placement confirmation and the opportunity matching selector apply three gates in this exact order: first clearance-level adequacy for the opportunity's required contact intensity, rejected as `ERR_CLEARANCE_LEVEL_INSUFFICIENT`; then restriction-flag compatibility with the opportunity's restricted category, rejected as `ERR_RESTRICTED_ROLE`; then training compliance, rejected as `ERR_TRAINING_INCOMPLETE`. Clearance expiry is deliberately not a stage-five gate: expiry is enforced by the clock sweep demoting `ACTIVE` volunteers to `RESCREEN_REQUIRED`, which then fails as a stage-four state precondition instead.
6. **Body referential coherence.** Cross-resource claims in the payload must hold: hour logging references a placement owned by the acting volunteer (`ERR_PLACEMENT_VOLUNTEER_MISMATCH`), and a placement-linked check-in requires that the placement belong to the check-in's volunteer (`ERR_PLACEMENT_VOLUNTEER_MISMATCH`) and that the placement's opportunity be hosted at the campus named in the payload (`ERR_PLACEMENT_CAMPUS_MISMATCH`).
7. **Temporal windows**, evaluated in endpoint order: the hour-entry `worked_date` must fall inside the placement's opportunity window (`ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW`); a placement-linked check-in must occur inside the check-in window (`ERR_OUTSIDE_CHECKIN_WINDOW`); placement confirmation must not create a scheduling overlap (`ERR_PLACEMENT_TIME_CONFLICT`); publishing requires the opportunity window to still lie ahead (`ERR_OPPORTUNITY_WINDOW_PASSED`); placement completion requires the window to have ended (`ERR_PLACEMENT_WINDOW_OPEN`).
8. **Capacity, uniqueness, and shape constraints.** Confirmation and matching require a free seat (`ERR_OPPORTUNITY_FULL`); placement requests reject duplicate open placements (`ERR_DUPLICATE_PLACEMENT`); check initiation rejects a volunteer who already has a pending check (`ERR_CHECK_ALREADY_PENDING`); check-in rejects a volunteer with a visit still open (`ERR_OPEN_CHECKIN_EXISTS`); a single hour entry declaring more than twelve hours is rejected (`ERR_HOURS_EXCEED_LIMIT`); placement completion requires at least one closed check-in (`ERR_NO_CHECKIN_FOR_PLACEMENT`); a manual award duplicates an existing tier (`ERR_DUPLICATE_AWARD`); and create-time uniqueness rejects a taken volunteer `email` (`ERR_EMAIL_TAKEN`), `campus_code` (`ERR_CAMPUS_CODE_TAKEN`), or `module_code` (`ERR_MODULE_CODE_TAKEN`).
9. **Optimistic concurrency.** Where an endpoint is OCC-guarded (§2.8), a stale `expected_volunteer_version` is rejected with `ERR_STALE_VERSION`.
10. **Request shape.** Required fields are present, enum values fall inside their declared sets, and numeric and date shapes hold — `hours` positive and carrying at most two decimal places, `capacity` at least one, `starts_at` strictly before `ends_at`, well-formed ISO 8601 datetimes. A request carrying no JSON body, or a body that is not parseable JSON, is evaluated as if the body were an empty object. Failures yield `ERR_INVALID_REQUEST`. Schema-level malformedness is deliberately reported after all stateful checks so that stateful error identifiers stay deterministic when a request fails in two ways at once.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency on the Volunteer aggregate, and both treat `expected_volunteer_version` as a non-optional request field carrying the client's last observed `version` of the target volunteer:

- **Initiating a background check.** The request must carry `expected_volunteer_version` matching the volunteer's current `version`. If another writer has advanced the volunteer's version since the client last read it — for example, a check was created that supersedes the client's view of the screening posture — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from initiating screening against a volunteer record it has not observed.
- **Granting a manual recognition award.** The request must carry `expected_volunteer_version` matching the volunteer's current `version`. If the volunteer's version has advanced since the client last read it — for example, an automated tier award or an hour verification has just changed the volunteer's recognition posture — the grant is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field at all. On the two guarded endpoints the supplied value is coerced to an integer for the comparison — a value that cannot be coerced to an integer is ignored rather than treated as stale — while an absent or null `expected_volunteer_version` is a missing required field and fails stage ten with `ERR_INVALID_REQUEST`.

### 2.9. Numeric Precision and Rounding

Service-hour totals are stored at two decimal places, rounded half up: both `total_verified_hours` and `total_provisional_hours` follow this rule on every recompute. Recognition points are rounded per entry, not per aggregate: each hour entry's `points` value is rounded half up to one decimal place at creation, and the volunteer's `recognition_points` aggregate is the exact sum of those already-rounded per-entry values. Summing raw products first and rounding once at the end is not permitted — the two orders produce different results. Tier thresholds are compared against the two-decimal verified-hours total with inclusive boundaries. Opportunity fill counts (`committed_count`, `projected_count`) are plain integers. Clearance validity arithmetic uses whole-day durations on ISO 8601 UTC timestamps, and badge sequences are integers scoped per campus per UTC day.

## 3. Business Logic & Workflows

### 3.1. District Configuration: Campuses and the Training Catalogue

Before any volunteer can serve, the district office configures its campuses. A `DistrictCoordinator` creates each Campus with a display `name`, a district-wide unique `campus_code` — rejected as a duplicate with `ERR_CAMPUS_CODE_TAKEN` and immutable once created — and a `badge_prefix` of one to eight uppercase alphanumeric characters that anchors the campus's daily badge codes; a campus whose prefix is LNC, for example, issues badges of the form LNC-0001. A single campus can be read back by any role.

The training catalogue is likewise district-managed. A `DistrictCoordinator` creates each TrainingModule with a unique `module_code` (a duplicate is rejected with `ERR_MODULE_CODE_TAKEN`), a human-readable `title`, and a non-empty `required_contact_types` list drawn from the contact-type enums `SUPERVISED` and `UNSUPERVISED` that declares which volunteer populations must complete the module. The optional `validity_days` declares how long a completion remains valid: an integer of at least one, or null — the default — meaning completions of this module never expire. Modules are readable by all roles.

Completion evidence is recorded as a TrainingRecord by a `DistrictCoordinator` or `CampusAdmin`, supplying the `volunteer_id`, the `module_id`, and the `completed_at` instant. The record's `expires_at` is computed as `completed_at` plus the module's `validity_days`, and stays null when the module never expires. Training records are append-only events; the record list can be filtered by `volunteer_id` and `module_id`.

Training compliance is a derived yes-or-no verdict evaluated against the logical clock. The required set for a given volunteer is every module whose `required_contact_types` contains that volunteer's `contact_type`. The volunteer is compliant exactly when every module in that required set has at least one completion record that is currently valid — meaning the module never expires, or the record's `expires_at` is strictly after the current time. This verdict is consulted at three moments: during adjudication branch selection, whenever a new completion record is created, and at placement confirmation. When a newly recorded completion makes a `CLEARANCE_GRANTED` volunteer's training compliance complete, the volunteer transitions automatically from `CLEARANCE_GRANTED` to `ACTIVE`, and the volunteer's `version` is incremented by one.

### 3.2. Application Intake and Background Screening

Every volunteer journey begins at intake. A `DistrictCoordinator` creates the application with the applicant's `full_name`, a contact `email`, and the intended `contact_type` — `SUPERVISED` for roles always performed within sight of staff, `UNSUPERVISED` for roles that may involve sole access to students. The email must be unique across all volunteers in any status; a taken email is rejected with `ERR_EMAIL_TAKEN`. The contact type is immutable after creation, and it fixes the volunteer's `required_check_level` per §2.6. A new application starts in `APPLIED` status with an empty `restriction_flags` array, zeroed service-hour totals and `recognition_points`, a `recognition_tier` of `NONE`, null `clearance_expires_at`, null `prior_status`, and null `suspension_incident_id`. The volunteer list — available to coordinators and campus administrators — can be filtered by `status`, `contact_type`, and `recognition_tier`, and a single volunteer record exposes all computed clearance, hours, and recognition fields.

Screening begins when a `DistrictCoordinator` initiates a BackgroundCheck for the volunteer, supplying the `volunteer_id`, the screening depth `level` (`BASIC` or `ENHANCED`), and the OCC guard field `expected_volunteer_version` described in §2.8. Check initiation is permitted only while the volunteer is in `APPLIED`, `ACTIVE`, or `RESCREEN_REQUIRED` status; any other status is rejected with `ERR_VOLUNTEER_INVALID_STATE`. A volunteer may have at most one unresolved check at a time: initiating while another check is still `PENDING` is rejected with `ERR_CHECK_ALREADY_PENDING`. The new check starts in `PENDING` with null `findings`, null `decided_at`, and null `expires_at`. When this is the volunteer's first check, the volunteer moves from `APPLIED` to `UNDER_SCREENING`; in all cases the initiation increments the volunteer's `version` by one. Background checks are visible to the district office alone, and the check list supports filtering by `volunteer_id` and `status`.

Adjudication by a `DistrictCoordinator` records the `findings` — `NONE`, `MINOR`, or `DISQUALIFYING` — on a check that must still be `PENDING`; adjudicating an already-decided check is rejected with `ERR_CHECK_INVALID_STATE`. The adjudication stamps `decided_at` from the logical clock, computes `expires_at` per the §2.6 validity window (a `DENIED` check keeps `expires_at` null), and resolves the check to `CLEARED`, `CLEARED_WITH_FLAGS`, or `DENIED` per the decision matrix, incrementing the check's `version` by one.

The volunteer-side consequences of a non-denied decision depend on where the volunteer stood. A volunteer in `UNDER_SCREENING` with an adequate cleared outcome moves to `ACTIVE` when training compliance is complete at that moment, or to `CLEARANCE_GRANTED` when it is not; the same two branches apply to a volunteer adjudicated out of `RESCREEN_REQUIRED`. When the decided check's level is not adequate for the volunteer's `required_check_level`, the volunteer remains in `UNDER_SCREENING` or `RESCREEN_REQUIRED` unchanged — the check still records its cleared outcome, but status, flags, and clearance expiry are untouched. A volunteer who is still `ACTIVE` may also be re-screened early: adjudicating a non-denied decision for such a volunteer is a self-loop that leaves the status at `ACTIVE` while recomputing `clearance_expires_at` and overwriting `restriction_flags` from the latest decision. Should those new flags block the `restricted_category` of any opportunity where the volunteer holds a `CONFIRMED` placement, those placements are cancelled with `cancel_reason` `SYSTEM_RESTRICTION` and their opportunities' fill counts are recomputed. Every one of these adjudication branches increments the volunteer's `version` by one. A non-denied adjudication can also land while the volunteer is in a status outside these branches — for example when a `HIGH`-severity incident has suspended the volunteer while a check was still `PENDING`: the decision is recorded on the check and the volunteer's `version` is incremented by one, but the volunteer's status, `restriction_flags`, and `clearance_expires_at` are left unchanged.

A `DISQUALIFYING` finding is the severe path: the volunteer transitions to the terminal `DENIED` status, and the system runs the full removal cascade described in §3.7. All of the volunteer's placements in `REQUESTED` or `CONFIRMED` are cancelled with `cancel_reason` `SYSTEM_REMOVAL`, each affected opportunity's fill counts are recomputed, every open campus visit of the volunteer is force-closed with `close_reason` `SYSTEM_REMOVAL`, and the volunteer's `version` is incremented by one.

### 3.3. Clearance Expiry and the Re-Screening Cycle

Clearances do not last forever, and expiry is enforced passively rather than at each gate. When the logical clock is advanced, the sweep of §2.5 expires every `CLEARED` or `CLEARED_WITH_FLAGS` check whose validity window has closed, recomputes each affected volunteer's `clearance_expires_at`, and demotes any `ACTIVE` volunteer left without a valid clearance to `RESCREEN_REQUIRED`. Because confirmation, check-in, and other service operations require the `ACTIVE` status as a stage-four precondition, a demoted volunteer is automatically locked out of further service — expiry never needs to be re-checked inside the safety gates themselves.

Recovery runs through the same machinery as initial screening. The district office initiates a fresh check for the `RESCREEN_REQUIRED` volunteer — permitted from that status — and adjudication then follows the §3.2 branches: an adequate cleared outcome returns the volunteer to `ACTIVE` when training compliance is complete, or to `CLEARANCE_GRANTED` when retraining is still owed, while an inadequate outcome leaves the volunteer in `RESCREEN_REQUIRED`. A `DISQUALIFYING` finding at re-screening moves the volunteer to `DENIED` with the full removal cascade. Re-screening may also be initiated proactively while the volunteer is still `ACTIVE`, producing the self-loop branch of §3.2 with no service interruption unless the new flags cancel affected placements.

### 3.4. Opportunities and the Placement Pipeline

Campus administrators and the district office advertise volunteer work through Opportunities. Creating one takes the hosting `campus_id`, a `title`, an optional free-text `description` that defaults to an empty string, the role's `required_contact_type` (`SUPERVISED` or `UNSUPERVISED`), a `restricted_category` of `NONE`, `TRANSPORT`, or `ONE_ON_ONE`, a `capacity` of at least one confirmed seat, and the service window as `starts_at` and `ends_at`, where `starts_at` must be strictly before `ends_at`. The restricted category interacts with screening flags: the flag `NO_TRANSPORT` blocks `TRANSPORT` roles, and the flag `NO_ONE_ON_ONE` blocks `ONE_ON_ONE` roles. A new opportunity starts in `DRAFT` with both `committed_count` and `projected_count` at zero. The opportunity list — visible to all roles — filters by `campus_id`, `status`, and `required_contact_type`.

Publishing moves an opportunity from `DRAFT` to `OPEN`. Publishing requires the opportunity to still be in `DRAFT` (otherwise `ERR_OPPORTUNITY_INVALID_STATE`) and requires its `starts_at` to lie strictly after the current logical time — a window that has already begun or passed is rejected with `ERR_OPPORTUNITY_WINDOW_PASSED`. Cancelling is permitted from either `DRAFT` or `OPEN` and moves the opportunity to the terminal `CANCELLED` status; the cancellation cascades to every placement in `REQUESTED` or `CONFIRMED`, cancelling each with `cancel_reason` `OPPORTUNITY_CANCELLED`, and the fill counts are recomputed. Both transitions increment the opportunity's `version` by one. Once the window closes, the clock sweep of §2.5 moves an `OPEN` opportunity whose `ends_at` has been reached to the terminal `COMPLETED` status.

Volunteers come onto an opportunity in two ways. The self-service path lets a `Volunteer` request a placement — the payload's `volunteer_id` is forced to the caller's own identity, and supplying someone else's id is an ownership violation — while a `DistrictCoordinator` may request on a volunteer's behalf by supplying `volunteer_id` explicitly. A request requires the opportunity to be `OPEN` (else `ERR_OPPORTUNITY_INVALID_STATE`) and the volunteer to be `ACTIVE` (else `ERR_VOLUNTEER_INVALID_STATE`), and it rejects a duplicate: if the same volunteer already holds a placement in `REQUESTED` or `CONFIRMED` on that opportunity, the request fails with `ERR_DUPLICATE_PLACEMENT`. Deliberately, no screening gates run at request time — clearance, restriction, and training checks are all deferred to confirmation. The new placement starts in `REQUESTED` with null `confirmed_at` and null `cancel_reason`, and the opportunity's `projected_count` is recomputed. Placement lists filter by `volunteer_id`, `opportunity_id`, and `status`; a volunteer may read only their own placements.

Confirmation is the compliance chokepoint, performed by a `CampusAdmin` or `DistrictCoordinator`. The full pipeline of §2.7 applies: the placement must be `REQUESTED` (else `ERR_PLACEMENT_INVALID_STATE`), its opportunity `OPEN` (else `ERR_OPPORTUNITY_INVALID_STATE`), and the volunteer `ACTIVE` (else `ERR_VOLUNTEER_INVALID_STATE`); then the three screening gates run in order — the volunteer's latest cleared check level (§2.6) adequate for the level implied by the opportunity's `required_contact_type` (`ERR_CLEARANCE_LEVEL_INSUFFICIENT`), no restriction flag blocking the opportunity's `restricted_category` (`ERR_RESTRICTED_ROLE`), and training compliance complete at confirm time (`ERR_TRAINING_INCOMPLETE`); then the temporal rule: the new placement's window must not overlap, under half-open semantics, any other `CONFIRMED` placement the volunteer holds — an overlap is rejected with `ERR_PLACEMENT_TIME_CONFLICT`, while two placements that merely touch, one's `ends_at` equal to the other's `starts_at`, are allowed; finally capacity: confirmation while `committed_count` has already reached `capacity` fails with `ERR_OPPORTUNITY_FULL`. A successful confirmation stamps `confirmed_at` from the logical clock, moves the placement to `CONFIRMED`, recomputes the opportunity's `committed_count` and `projected_count`, and increments the placement's `version` by one.

The district office can also fill an opportunity in bulk through the matching selector. The selector's eligibility pool is every volunteer who is `ACTIVE`, whose latest cleared check level is adequate for the opportunity's `required_contact_type`, whose required trainings are all currently valid, whose `restriction_flags` do not block the opportunity's `restricted_category`, who has no overlapping `CONFIRMED` placement under the same half-open overlap rule, and who holds no existing placement on this opportunity. The same three screening gates that confirmation enforces as rejections act here as silent filters — ineligible volunteers are simply excluded from the pool. Eligible volunteers are ranked by `total_verified_hours` ascending, ties broken by the volunteer's `created_at` ascending and any remaining ties by the volunteer's `id` ascending, and placements are created directly in `CONFIRMED` — `confirmed_at` stamped — in ranking order until the remaining capacity is exhausted or, when the caller supplies `max_placements` — which, when supplied, must be a non-negative integer, otherwise `ERR_INVALID_REQUEST` — that cap is reached. The opportunity must be `OPEN` (else `ERR_OPPORTUNITY_INVALID_STATE`), and an empty pool simply yields a `matched_count` of zero. The response reports `matched_count`, the `created_placement_ids`, the resulting `committed_count`, and the `remaining_capacity`; the opportunity's fill counts are recomputed accordingly, and the opportunity's `version` is incremented by one on every selector call, including an empty match that creates nothing.

Placements unwind in two ways. Cancellation is available from either `REQUESTED` or `CONFIRMED` (any other status is rejected with `ERR_PLACEMENT_INVALID_STATE`) and moves the placement to the terminal `CANCELLED` status: when the owning volunteer cancels, `cancel_reason` records `VOLUNTEER_WITHDRAW`; when a `CampusAdmin` or `DistrictCoordinator` cancels, it records `ADMIN_CANCEL`. Releasing a `CONFIRMED` seat recomputes the opportunity's `committed_count` and `projected_count`, and the placement's `version` increments by one. Completion, performed by a `CampusAdmin` or `DistrictCoordinator`, moves a `CONFIRMED` placement to the terminal `COMPLETED` status and requires two things: the current logical time must be at or after the opportunity's `ends_at` (completing earlier is rejected with `ERR_PLACEMENT_WINDOW_OPEN`), and at least one check-in linked to this placement must already be `CLOSED` (otherwise `ERR_NO_CHECKIN_FOR_PLACEMENT`). Completion removes the placement from the confirmed set, so the opportunity's fill counts are recomputed, and the placement's `version` increments by one.


### 3.5. Campus Check-In and Daily Badge Issuance

Whenever a volunteer enters a campus, a VisitCheckIn records the visit and a badge is issued. A `Volunteer` checks themselves in — the record's `volunteer_id` is forced to the caller's own identity, and supplying someone else's id is an ownership violation — while a `CampusAdmin` or `DistrictCoordinator` checking someone in must supply `volunteer_id` explicitly in the payload. The target `campus_id` names the campus being entered. Only an `ACTIVE` volunteer may check in; any other volunteer status is rejected with `ERR_VOLUNTEER_INVALID_STATE`. A volunteer may hold at most one open visit at a time, across all campuses: checking in while another check-in is still `OPEN` fails with `ERR_OPEN_CHECKIN_EXISTS`.

A check-in may optionally reference the placement being served via `placement_id`; when it does, three additional rules bind. The placement must be `CONFIRMED` (else `ERR_PLACEMENT_INVALID_STATE`); the placement must belong to the check-in's volunteer (else `ERR_PLACEMENT_VOLUNTEER_MISMATCH`); and the placement's opportunity must be hosted at the campus named in the payload (else `ERR_PLACEMENT_CAMPUS_MISMATCH`). Timing is also enforced: the current logical time must fall within the closed interval running from thirty minutes before the opportunity's `starts_at` through its `ends_at`, inclusive at both ends, or the check-in is rejected with `ERR_OUTSIDE_CHECKIN_WINDOW`. When `placement_id` is omitted — the default is null — the visit is a walk-in, open to any `ACTIVE` volunteer without placement or window checks.

Badge issuance is deterministic. The badge day is the UTC calendar date of the `checked_in_at` instant, which the server stamps from the logical clock at creation. The sequence number for a new check-in is one plus the count of existing check-ins at the same campus on the same UTC day, in any status, with equal timestamps ordered by `created_at` ascending; the sequence resets each day and is scoped per campus. The resulting `badge_code` is the campus's `badge_prefix`, a hyphen, and the sequence number zero-padded to four digits — the third check-in of the day at a campus with prefix LNC receives LNC-0003. A fresh visit starts in `OPEN` status with null `checked_out_at` and null `close_reason`. The check-in list filters by `volunteer_id`, `campus_id`, `placement_id`, and `status`, and a volunteer may read only their own check-ins.

Checking out moves a visit from `OPEN` to `CLOSED`; acting on a visit that is not `OPEN` is rejected with `ERR_CHECKIN_INVALID_STATE`. The server stamps `checked_out_at` from the logical clock and records a `close_reason`: `SELF` when the owning volunteer checks out, `ADMIN` when a `CampusAdmin` or `DistrictCoordinator` does it. A volunteer may check out only their own visits. Each check-out increments the visit's `version` by one. Visits can also be closed without anyone at the door: the suspension and removal cascades of §3.7 force-close every `OPEN` visit of the affected volunteer, stamping `checked_out_at` and recording `close_reason` as `SYSTEM_SUSPENSION` or `SYSTEM_REMOVAL`, and each such forced close increments the visit's `version` by one.

### 3.6. Service Hours, Verification, and the Recognition Program

Volunteered time is logged as HourEntries. A `Volunteer` logs hours against their own placements, and a `DistrictCoordinator` may log on a volunteer's behalf; when the caller has the Volunteer role and the referenced placement belongs to someone else, the write is an ownership violation (`ERR_FORBIDDEN`, and the referential stage restates the same rule as `ERR_PLACEMENT_VOLUNTEER_MISMATCH`). Each entry carries the `placement_id`, the calendar `worked_date` in year-month-day form, the `hours` worked, and an `activity_category` of `STANDARD`, `TUTORING`, or `MENTORING`. The referenced placement must be `CONFIRMED` or `COMPLETED` (otherwise `ERR_PLACEMENT_INVALID_STATE`), and the `worked_date` must fall on or between the calendar date of the opportunity's `starts_at` and the calendar date of its `ends_at` (otherwise `ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW`). A single entry may declare at most twelve hours — anything above twelve is rejected with `ERR_HOURS_EXCEED_LIMIT` — and must declare a positive amount with no more than two decimal places (otherwise `ERR_INVALID_REQUEST`). At creation the entry's `volunteer_id` is copied from the placement, its status starts at `PENDING`, and its `points` are computed immediately: the `hours` multiplied by the category multiplier — one for `STANDARD`, one and a half for `TUTORING`, two for `MENTORING` — rounded half up to one decimal place. Creating an entry recomputes the volunteer's `total_provisional_hours` and increments the volunteer's `version` by one. The hour-entry list filters by `placement_id`, `volunteer_id`, and `status`, and a volunteer may read only their own entries.

Two running totals track each volunteer's engagement. The official figure, `total_verified_hours`, sums the `hours` of entries in `VERIFIED` status only and feeds tier evaluation and reporting. The pipeline figure, `total_provisional_hours`, sums entries in `PENDING` or `VERIFIED`, giving an optimistic view that sits strictly above the verified total whenever unverified entries are outstanding. Entries in `REJECTED` or `REVOKED` count toward neither. Both stored sums are rounded half up to two decimal places.

Verification is the campus administrator's daily ritual. A `CampusAdmin` or `DistrictCoordinator` verifies an entry that is still `PENDING` — any other status yields `ERR_HOUR_ENTRY_INVALID_STATE` — moving it to `VERIFIED`. Verification recomputes both hour totals, recomputes the volunteer's `recognition_points` as the exact sum of the per-entry `points` over all `VERIFIED` entries, and re-evaluates the `recognition_tier`. The rounding order is pinned: each entry was rounded first, and only then are the rounded values summed. Consider a 2.5-hour `TUTORING` entry and a 1.25-hour `STANDARD` entry: they contribute 3.8 and 1.3 points respectively, raising the aggregate by 5.1, whereas summing the raw products and rounding once would wrongly yield 5.0. Rejection, available to the same two roles, moves a `PENDING` entry to the terminal `REJECTED` status; the entry leaves the provisional set, `total_provisional_hours` is recomputed, and both the entry's and the volunteer's `version` increment by one — as they also do on verification. Revocation is a district-office exclusive: a `DistrictCoordinator` moves a `VERIFIED` entry to the terminal `REVOKED` status, recomputing both totals and the recognition points in compensation, and the tier may downgrade as a result. Awards already granted are never retracted, whatever happens to the tier afterwards.

The recognition ladder has three rungs above `NONE`: `BRONZE` at twenty verified hours, `SILVER` at fifty, and `GOLD` at one hundred. Boundaries are inclusive — a volunteer at exactly 50.0 verified hours holds `SILVER` — and the comparison runs against the two-decimal `total_verified_hours`. Whenever a recompute raises the tier, the system automatically creates a RecognitionAward with `source` `AUTO` for every newly reached tier — each rung above the old tier and at or below the new one — skipping any tier for which an award already exists for that volunteer; a recompute that climbs several rungs at once therefore creates one award per newly reached rung, and tier decreases create nothing. Automatically created awards carry an empty `note`. Awards are append-only: once granted, an award exists forever, even if the underlying hours are later revoked.

The district office may also grant an award by hand. A `DistrictCoordinator` supplies the `volunteer_id`, the `tier` (`BRONZE`, `SILVER`, or `GOLD`), an optional `note` for the citation that defaults to an empty string, and the OCC guard field `expected_volunteer_version` of §2.8 — a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Manual grants are refused for volunteers in the terminal `DENIED` or `REMOVED` statuses (`ERR_VOLUNTEER_INVALID_STATE`), and at most one award per tier may ever exist for a volunteer, automatic or manual; a second grant of the same tier is rejected with `ERR_DUPLICATE_AWARD`. A manually created award records `source` `MANUAL`, and because the award attaches to the volunteer aggregate, its creation increments the volunteer's `version` by one. The award list filters by `volunteer_id` and `tier` and is readable by coordinators and campus administrators.

### 3.7. Incident Reporting, Suspension, and Removal

When something goes wrong on campus, a `CampusAdmin` or `DistrictCoordinator` files an IncidentReport naming the `volunteer_id` it concerns, an optional `placement_id` for context (null when omitted), a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and a free-text `description` of what happened. Filing is permitted while the volunteer is `ACTIVE`, `RESCREEN_REQUIRED`, `CLEARANCE_GRANTED`, or `SUSPENDED`; against any other status it is rejected with `ERR_VOLUNTEER_INVALID_STATE`. The report itself starts in `OPEN` status. Incident lists filter by `volunteer_id`, `placement_id`, and `status`, and incidents are visible only to coordinators and campus administrators — never to volunteers.

Severity decides the immediate blast radius. A `LOW` or `MEDIUM` report simply enters the queue and the volunteer continues serving. Filing a `HIGH` report against a volunteer in `ACTIVE`, `RESCREEN_REQUIRED`, or `CLEARANCE_GRANTED` suspends them on the spot: the volunteer's status becomes `SUSPENDED`, `prior_status` records the status held at the moment of suspension, and `suspension_incident_id` records the new report's `id` so the system remembers which incident caused the suspension. The suspension cascade then releases the volunteer's commitments — every `CONFIRMED` placement is cancelled with `cancel_reason` `SYSTEM_SUSPENSION` and each affected opportunity's `committed_count` and `projected_count` are recomputed — and force-closes every `OPEN` campus visit with `close_reason` `SYSTEM_SUSPENSION`. The volunteer's `version` increments by one when the suspension fires. Note the asymmetry with removal: suspension cancels only confirmed placements, leaving mere requests in place, and the request side is handled later if the incident is substantiated.

Adjudication by a `DistrictCoordinator` resolves an `OPEN` report through the payload's `outcome`; acting on a report that is no longer `OPEN` is rejected with `ERR_INCIDENT_INVALID_STATE`. An outcome of `SUBSTANTIATED` removes the volunteer: the status becomes the terminal `REMOVED`, the full removal cascade runs — every placement in `REQUESTED` or `CONFIRMED` is cancelled with `cancel_reason` `SYSTEM_REMOVAL`, each affected opportunity's fill counts are recomputed, and every `OPEN` visit is force-closed with `close_reason` `SYSTEM_REMOVAL` — and `prior_status` and `suspension_incident_id` are cleared back to null. This path applies whether or not the volunteer was suspended: a substantiated report that had been filed at `LOW` or `MEDIUM` severity, and so never suspended anyone, removes an `ACTIVE`, `RESCREEN_REQUIRED`, or `CLEARANCE_GRANTED` volunteer just as surely as a substantiated `HIGH` report removes a `SUSPENDED` one. If the volunteer has already reached `DENIED` or `REMOVED` by the time the report is adjudicated — for example through an intervening background-check denial or another substantiated report — the volunteer record is left unchanged and no cascade runs, though the report itself still resolves to `SUBSTANTIATED`.

An outcome of `UNFOUNDED` instead looks at reinstatement, but only when the report being resolved is the one that caused the current suspension — that is, when the volunteer's `suspension_incident_id` equals this report's `id`. Reinstatement follows the recorded `prior_status` together with current clearance validity: a volunteer whose `prior_status` was `ACTIVE` returns to `ACTIVE` when `clearance_expires_at` is still strictly after the current time, but drops to `RESCREEN_REQUIRED` when the clearance has lapsed (null, or at or before now); a volunteer whose `prior_status` was `CLEARANCE_GRANTED` returns to `CLEARANCE_GRANTED`; a volunteer whose `prior_status` was `RESCREEN_REQUIRED` returns to `RESCREEN_REQUIRED`. In each reinstatement branch `prior_status` and `suspension_incident_id` are nulled and the volunteer's `version` increments by one. When the resolved report did not cause the volunteer's suspension — or the volunteer was never suspended — the volunteer record is left unchanged. Any volunteer mutation arising from adjudication also increments the report's own `version` by one, and the report always transitions to its terminal `SUBSTANTIATED` or `UNFOUNDED` status with its `version` incremented.

## 4. Endpoint Definitions

Operations that create a new resource — a campus, volunteer, background check, training module, training record, opportunity, placement, hour entry, check-in, incident report, or recognition award — return `201 Created`. Operations that read resources or modify existing ones — publishes, cancels, confirmations, completions, adjudications, verifications, rejections, revocations, check-outs, the matching selector, and the clock set — return `200 OK`. Request and response bodies are not repeated here; the narrative of §3 defines them, and this table is only the map.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/campuses` | Create a campus | DistrictCoordinator |
| GET | `/campuses/{id}` | Read one campus | DistrictCoordinator, CampusAdmin, Volunteer |
| POST | `/volunteers` | Intake: create a volunteer application in APPLIED | DistrictCoordinator |
| GET | `/volunteers` | List volunteers with pagination and filters | DistrictCoordinator, CampusAdmin |
| GET | `/volunteers/{id}` | Read one volunteer including computed clearance/hours/recognition fields; Volunteer role reads own record only | DistrictCoordinator, CampusAdmin, Volunteer |
| POST | `/background-checks` | Initiate a background check for a volunteer; OCC-guarded on the volunteer's version | DistrictCoordinator |
| GET | `/background-checks` | List background checks, filterable by volunteer and status | DistrictCoordinator |
| GET | `/background-checks/{id}` | Read one background check | DistrictCoordinator |
| POST | `/background-checks/{id}/adjudicate` | Record findings and resolve the check; cascades to the volunteer per the screening decision matrix | DistrictCoordinator |
| POST | `/training-modules` | Create a training module | DistrictCoordinator |
| GET | `/training-modules` | List training modules | DistrictCoordinator, CampusAdmin, Volunteer |
| POST | `/training-records` | Record a module completion; may auto-activate a CLEARANCE_GRANTED volunteer | DistrictCoordinator, CampusAdmin |
| GET | `/training-records` | List training records, filterable by volunteer and module | DistrictCoordinator, CampusAdmin |
| GET | `/training-records/{id}` | Read one training record | DistrictCoordinator, CampusAdmin |
| POST | `/opportunities` | Create an opportunity in DRAFT | CampusAdmin, DistrictCoordinator |
| GET | `/opportunities` | List opportunities, filterable by campus, status, and contact type | DistrictCoordinator, CampusAdmin, Volunteer |
| GET | `/opportunities/{id}` | Read one opportunity including fill counts | DistrictCoordinator, CampusAdmin, Volunteer |
| POST | `/opportunities/{id}/publish` | Publish an opportunity: DRAFT to OPEN | CampusAdmin, DistrictCoordinator |
| POST | `/opportunities/{id}/cancel` | Cancel an opportunity from DRAFT or OPEN; cancels its open placements | CampusAdmin, DistrictCoordinator |
| POST | `/opportunities/{id}/match` | Auto-place eligible volunteers into CONFIRMED placements up to capacity | DistrictCoordinator |
| POST | `/placements` | Request a placement; Volunteer role requests only for self | Volunteer, DistrictCoordinator |
| GET | `/placements` | List placements, filterable by volunteer, opportunity, and status | DistrictCoordinator, CampusAdmin |
| GET | `/placements/{id}` | Read one placement; Volunteer role reads own placements only | DistrictCoordinator, CampusAdmin, Volunteer |
| POST | `/placements/{id}/confirm` | Confirm a REQUESTED placement through the full safety/temporal/capacity gate stack | CampusAdmin, DistrictCoordinator |
| POST | `/placements/{id}/cancel` | Cancel a REQUESTED or CONFIRMED placement, releasing the seat; Volunteer role cancels own only | Volunteer, CampusAdmin, DistrictCoordinator |
| POST | `/placements/{id}/complete` | Complete a CONFIRMED placement after its window ends; requires a closed check-in | CampusAdmin, DistrictCoordinator |
| POST | `/hour-entries` | Log volunteer hours against a placement | Volunteer, DistrictCoordinator |
| GET | `/hour-entries` | List hour entries, filterable by placement, volunteer, and status | DistrictCoordinator, CampusAdmin |
| GET | `/hour-entries/{id}` | Read one hour entry; Volunteer role reads own entries only | DistrictCoordinator, CampusAdmin, Volunteer |
| POST | `/hour-entries/{id}/verify` | Verify a PENDING entry; drives totals, points, tier, and auto-award cascade | CampusAdmin, DistrictCoordinator |
| POST | `/hour-entries/{id}/reject` | Reject a PENDING entry; it leaves the provisional set | CampusAdmin, DistrictCoordinator |
| POST | `/hour-entries/{id}/revoke` | Revoke a VERIFIED entry; compensates totals and points, may downgrade tier | DistrictCoordinator |
| POST | `/check-ins` | Campus check-in with badge issuance; supports placement-linked and walk-in visits | Volunteer, CampusAdmin, DistrictCoordinator |
| GET | `/check-ins` | List check-ins, filterable by volunteer, campus, placement, and status | DistrictCoordinator, CampusAdmin |
| GET | `/check-ins/{id}` | Read one check-in; Volunteer role reads own check-ins only | DistrictCoordinator, CampusAdmin, Volunteer |
| POST | `/check-ins/{id}/check-out` | Close an OPEN visit; Volunteer role checks out own visits only | Volunteer, CampusAdmin, DistrictCoordinator |
| POST | `/incident-reports` | File an incident against a volunteer; HIGH severity auto-suspends with cascade | CampusAdmin, DistrictCoordinator |
| GET | `/incident-reports` | List incident reports, filterable by volunteer, placement, and status | DistrictCoordinator, CampusAdmin |
| GET | `/incident-reports/{id}` | Read one incident report | DistrictCoordinator, CampusAdmin |
| POST | `/incident-reports/{id}/adjudicate` | Resolve an OPEN report as SUBSTANTIATED (removal cascade) or UNFOUNDED (reinstatement) | DistrictCoordinator |
| POST | `/recognition-awards` | Manually grant a recognition award; OCC-guarded on the volunteer's version | DistrictCoordinator |
| GET | `/recognition-awards` | List recognition awards, filterable by volunteer and tier | DistrictCoordinator, CampusAdmin |
| GET | `/recognition-awards/{id}` | Read one recognition award | DistrictCoordinator, CampusAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the expiry/completion sweep | DistrictCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the corresponding rule is defined; this table is only the identifier-to-status map.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VOLUNTEER_INVALID_STATE` | 409 Conflict |
| `ERR_CHECK_INVALID_STATE` | 409 Conflict |
| `ERR_CHECK_ALREADY_PENDING` | 409 Conflict |
| `ERR_OPPORTUNITY_INVALID_STATE` | 409 Conflict |
| `ERR_OPPORTUNITY_WINDOW_PASSED` | 422 Unprocessable Entity |
| `ERR_OPPORTUNITY_FULL` | 409 Conflict |
| `ERR_PLACEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_PLACEMENT_TIME_CONFLICT` | 422 Unprocessable Entity |
| `ERR_PLACEMENT_WINDOW_OPEN` | 422 Unprocessable Entity |
| `ERR_PLACEMENT_VOLUNTEER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PLACEMENT_CAMPUS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLEARANCE_LEVEL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_RESTRICTED_ROLE` | 422 Unprocessable Entity |
| `ERR_TRAINING_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_HOURS_EXCEED_LIMIT` | 422 Unprocessable Entity |
| `ERR_HOUR_ENTRY_INVALID_STATE` | 409 Conflict |
| `ERR_OUTSIDE_CHECKIN_WINDOW` | 422 Unprocessable Entity |
| `ERR_OPEN_CHECKIN_EXISTS` | 409 Conflict |
| `ERR_CHECKIN_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_PLACEMENT` | 409 Conflict |
| `ERR_DUPLICATE_AWARD` | 409 Conflict |
| `ERR_NO_CHECKIN_FOR_PLACEMENT` | 422 Unprocessable Entity |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_CAMPUS_CODE_TAKEN` | 409 Conflict |
| `ERR_MODULE_CODE_TAKEN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

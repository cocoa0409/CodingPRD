# Sorna Registrant Compliance API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Sex-Offender & Registrant Compliance (SORNA) API. The system is the system of record for the full compliance lifecycle of registered subjects: it captures each subject's qualifying offenses and derives a statutory tier from them, schedules and records periodic verifications, tracks residence, employment, school, and temporary addresses against enforced exclusion zones, opens and resolves non-compliance flags, adjudicates travel and inter-jurisdiction movement, dispatches community notifications, and processes petitions to deregister or reduce tier.

Because compliance obligations are inherently time-driven — verification intervals, travel windows, decay of risk over open flags, and multi-year deregistration eligibility all depend on the passage of time — the system runs on an explicit logical clock rather than wall-clock time. Every schedule, window, and eligibility computation reads that clock, and an administrative capability advances it so that time-dependent behavior can be exercised deterministically. The remainder of this document describes the global contract every endpoint honors (Section 2), the domain workflows and the calculations that back them (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which the user is acting. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows:

- `RegistryAdmin` — owns configuration: creating jurisdictions and their exclusion zones, and advancing the logical clock.
- `RegistrationOfficer` — the front-line officer who registers subjects, records offenses, activates registrants, records addresses and verifications, opens and resolves flags, decides travel notices, and dispatches notifications.
- `ComplianceReviewer` — adjudicates petitions and reads compliance rosters and flags. Under segregation of duties, this role cannot open flags or record verifications.
- `Registrant` — the self-service subject, permitted to read its own record and to submit address updates, travel notices, and petitions on its own record only.

`RegistryAdmin`, `RegistrationOfficer`, and `ComplianceReviewer` are opaque operator roles: for each, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier as a descriptive attribute where a workflow calls for it (for example, as the `officer_ref` on a verification or the `reviewer_ref` on a petition decision), but it never compares that identifier to any entity's `id`. The `Registrant` role is entity-backed: when `X-User-Role` is `Registrant`, `X-User-ID` is the `id` of the acting `Registrant` entity. Every ownership check on a resource that references a registrant compares that resource's `registrant_id` (or, for the registrant record itself, its `id`) to `X-User-ID`; a `Registrant` acting on any record other than its own is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific workflow states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control (Section 2.8).

`Jurisdiction`, `ExclusionZone`, `Registrant`, `Address`, `ComplianceFlag`, `TravelNotice`, and `Petition` all carry the full set above. Three resources are lightweight audit records that carry only `id` and `created_at` and deliberately omit both `updated_at` and `version`: `Offense`, `VerificationEvent`, and `NotificationRecord`. These three are never mutated after creation, so no version or modified-at field is exposed for them.

When a computation refreshes a derived field on a resource — for example when a registrant's `risk_score`, `tier`, `status`, `last_verified_date`, `next_verification_due`, or `current_residence_address_id` changes — that is a mutation of the resource: its `updated_at` is refreshed and its `version` is incremented. Likewise, a jurisdiction's `active_travel_hold_count` and `active_registrant_count` are derived roster figures maintained on the jurisdiction as its underlying population changes.

### 2.5. The Logical Clock and Temporal Semantics

The system keeps a single logical clock, and every time-dependent rule — verification schedules, travel windows, flag decay, and deregistration duration — reads it rather than the host wall clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before it is ever set it holds precisely that value and never falls back to real-world time. An administrative test-driving capability, restricted to `RegistryAdmin`, sets the clock to a supplied `to_iso8601` instant and returns the new value as `current_utc`; authentication is still required for this call.

All timestamps the system stamps onto resources — `initial_registration_date`, `completed_date`, `opened_date`, `resolved_date`, `dispatched_date`, `filed_date`, and `decided_date` — are read from this clock at the moment of the recording action. These clock-derived timestamps — together with the derived `next_verification_due` and a non-temporary address's defaulted `effective_from` — are serialized in ISO 8601 UTC mirroring the clock instant's own precision: a whole-second instant renders with no fractional-second part (for example `2026-05-01T00:00:00Z`) rather than being padded to the three fractional digits used for `created_at`/`updated_at`. Duration and window comparisons are evaluated in whole days (and, for deregistration, whole years) as described in the workflows.

### 2.6. Nested Resource Retrieval and Path Validation

Many resources are addressed beneath a parent in the URL — exclusion zones beneath a jurisdiction; offenses, addresses, verifications, flags, travel notices, notifications, and petitions beneath a registrant. For any such path the system validates the identifiers left to right and rejects at the first one that does not resolve to an existing resource. A jurisdiction that does not exist yields `ERR_JURISDICTION_NOT_FOUND`; a registrant that does not exist yields `ERR_REGISTRANT_NOT_FOUND`; and likewise `ERR_ADDRESS_NOT_FOUND`, `ERR_EXCLUSION_ZONE_NOT_FOUND`, `ERR_FLAG_NOT_FOUND`, `ERR_TRAVEL_NOTICE_NOT_FOUND`, and `ERR_PETITION_NOT_FOUND` for the corresponding resource identifiers. The parent is always checked before the child, so a missing registrant is reported before the system attempts to locate an address, flag, travel notice, or petition beneath it.

### 2.7. Validation Ordering and Precedence

When a single request could fail several checks, the system evaluates them in a fixed order and reports the first failure it reaches. The order is:

1. Authentication — both headers present and the role recognized, otherwise `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role is permitted for the operation, and an entity-backed `Registrant` is acting on its own record, otherwise `ERR_UNAUTHORIZED`.
3. Path existence — every identifier in the path resolves, left to right, otherwise the matching not-found error from Section 2.6.
4. State — the target resource is in a state that permits the requested transition, otherwise a 409 state error (for example `ERR_REGISTRANT_NOT_PENDING`, `ERR_REGISTRANT_NOT_ACTIVE`, or `ERR_INVALID_STATE`).
5. Referential body checks — foreign keys supplied in the body resolve; specifically the `destination_jurisdiction_id` on a travel notice must resolve, otherwise `ERR_JURISDICTION_NOT_FOUND`.
6. Temporal checks — date ordering and not-in-past rules on travel and address windows, otherwise `ERR_INVALID_TRAVEL_DATES` (with the missing-window case reported as `ERR_MISSING_TRAVEL_RETURN`).
7. Safety — a residence address must not fall inside any active exclusion zone, otherwise `ERR_EXCLUSION_ZONE_VIOLATION`.
8. Constraint — window-overlap and duplicate-record conflicts, otherwise the matching 409 conflict error.
9. Optimistic concurrency — the supplied `expected_registrant_version` matches the registrant's current `version` on an address create, otherwise `ERR_STALE_VERSION`.

Field-shape validation is orthogonal to this ordering: a missing required field or a malformed value is rejected with `ERR_VALIDATION`, and an enum field carrying a value outside its declared set is rejected with `ERR_INVALID_ENUM`.

### 2.8. Optimistic Concurrency Control

Adding an address to a registrant is the one mutation guarded by optimistic concurrency, because a new residence supersedes the prior residence and repoints the registrant's `current_residence_address_id` — a genuine mutation of the registrant record. A request to record an address must therefore carry `expected_registrant_version`, a non-optional field carrying the `version` of the registrant the client last observed. If that value does not equal the registrant's current `version` — meaning another residence update has already advanced the registrant record since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a residence state it never saw. No other endpoint takes a version field, and no other endpoint performs this check.

### 2.9. Precision and Rounding

Several calculations round intermediate results, and the rounding point matters. The rounding method throughout is round half up.

- Per-offense tier points are rounded half up at the per-offense multiply step, and the registrant's `tier_score` is then the integer sum of those rounded per-offense values.
- Flag risk contributions are rounded half up per flag first, and the registrant's `risk_score` is then the integer sum of those per-flag rounded contributions.
- Recipient counts, tier scores, base points, and radii are whole integers.
- Verification and travel-window durations are evaluated in whole days; deregistration duration is evaluated in whole years.
- Exclusion-zone proximity is computed on exact real distances, and the prohibition test compares that exact distance against an integer threshold.

## 3. Business Logic & Workflows

### 3.1. Jurisdictions and Exclusion Zones

A `RegistryAdmin` establishes the operating geography. Creating a jurisdiction requires a `name` and a two-letter `state_code`. Two optional knobs may be supplied at creation: `verification_grace_days`, the number of days past a registrant's due date before the registrant is deemed overdue, which defaults to 3; and `est_households_per_notification`, the baseline household count that feeds the forward-looking community-notification estimate, which defaults to 100. A jurisdiction's `status` may optionally be seeded at creation and otherwise defaults to `ACTIVE`; the only other value is `INACTIVE`, and an `INACTIVE` jurisdiction cannot receive inbound travel or relocation. A newly created jurisdiction reports `active_registrant_count` and `active_travel_hold_count` of 0. The former is the running count of registrants whose `jurisdiction_id` points at this jurisdiction and whose `status` is `ACTIVE` or `DELINQUENT`; the latter is the running count of inbound travel notices — those whose `destination_jurisdiction_id` points here — currently in `APPROVED` or `ACTIVE` status.

A compliance roster report is available for a jurisdiction to a `ComplianceReviewer` or `RegistrationOfficer`. It is a computed read that returns `total_registrants` for the jurisdiction alongside a breakdown by status: `active_count`, `delinquent_count`, `absconder_count`, and `deregistered_count`. A jurisdiction's registrants can also be listed, optionally narrowed by an exact-match `status` query filter.

Within a jurisdiction, a `RegistryAdmin` defines exclusion zones. An `ExclusionZone` carries a `name`, a `zone_type` of `SCHOOL`, `PARK`, or `DAYCARE`, an integer center given by `center_x` and `center_y` in meters on the jurisdiction grid, and a protected `radius_meters`. An optional `buffer_meters`, defaulting to 100, is the additional statutory buffer added to the radius. Zones carry a `jurisdiction_id` identifying the owning jurisdiction, and a `status` that is `ACTIVE` from creation; there is no deactivation path in this version, so every zone is enforced for the life of the system. Zones can be listed for a jurisdiction and read individually.

### 3.2. Registrant Intake, Offenses, and Tiering

A `RegistrationOfficer` registers a new subject by supplying the `jurisdiction_id` of registration, the subject's `full_name`, and `date_of_birth`. A freshly registered subject begins in `PENDING` status with no tier, score, or verification schedule yet assigned.

Before activation, the officer records one or more qualifying offenses on the registrant. Each `Offense` carries a `statute_code`, an `offense_class` of `CLASS_A`, `CLASS_B`, or `CLASS_C`, an optional `is_aggravated` flag (default false), an optional `victim_minor` flag (default false), and a `conviction_date`. Each offense is owned by its registrant through `registrant_id`.

Every offense contributes `offense_points`, computed and stored on the offense as follows. Start from a class base: 30 points for `CLASS_A`, 20 for `CLASS_B`, 10 for `CLASS_C`. If the offense is aggravated, add an aggravating bonus of 10 points to that base. Multiply the resulting sum by 1.5 when the victim was a minor, or by 1 otherwise, and round the product half up to a whole number; that rounded value is the offense's `offense_points`. The registrant's `tier_score` is then the integer sum of every offense's `offense_points`, plus a prior-conviction bonus of 5 points for each offense beyond the first — that is, 5 points multiplied by the offense count minus one, never less than zero. From the resulting `tier_score` the registrant's `tier` is derived: `TIER_3` when the score is at least 60, otherwise `TIER_2` when the score is at least 30, otherwise `TIER_1`. The tier fixes the periodic `verification_interval_days`: 365 days for `TIER_1`, 180 for `TIER_2`, and 90 for `TIER_3`. Recording an offense recomputes the registrant's `tier`, `tier_score`, and `verification_interval_days` immediately.

Activation is performed by a `RegistrationOfficer` and is permitted only while the registrant is `PENDING`; activating a registrant in any other state is rejected with `ERR_REGISTRANT_NOT_PENDING`. Activation requires at least one offense on record; with none, it is rejected with `ERR_NO_OFFENSES`. On success the registrant transitions `PENDING → ACTIVE`: its `initial_registration_date` is set to the clock, its tier and interval are (re)computed from its offenses, its `last_verified_date` is set to null, and its `next_verification_due` is set to the initial registration date plus the verification interval, expressed in days.

### 3.3. Addresses, Residence Supersession, and Exclusion-Zone Proximity

Both a `RegistrationOfficer` and the owning `Registrant` may record an address. An `Address` carries an `address_type` of `RESIDENCE`, `EMPLOYMENT`, `SCHOOL`, or `TEMPORARY`; the postal fields `line1`, `city`, `state_code`, and `postal_code`; an integer location given by `grid_x` and `grid_y` in meters on the jurisdiction grid; and an occupancy window given by `effective_from` and `effective_to`. For a `TEMPORARY` address both window ends are required, and `effective_to` must be strictly later than `effective_from`; an out-of-order window is rejected with `ERR_INVALID_TRAVEL_DATES`, and a `TEMPORARY` address submitted without its `effective_to` is rejected with `ERR_MISSING_TRAVEL_RETURN`. For non-temporary addresses `effective_from` defaults to the clock at creation and `effective_to` is null. Every address is owned through `registrant_id`.

A residence carries additional obligations. When a `RESIDENCE` address is recorded, the system screens it against every `ACTIVE` exclusion zone in the registrant's jurisdiction. For each such zone it computes the straight-line distance between the address point and the zone center — the square root of the sum of the squared differences of the x and y coordinates — and treats the address as prohibited when that distance is less than or equal to the zone's `radius_meters` plus its `buffer_meters`. If any zone prohibits the point, the address is rejected with `ERR_EXCLUSION_ZONE_VIOLATION`. When the residence clears the screen, it becomes the registrant's current residence: the prior `RESIDENCE` address, if any, transitions from `VERIFIED` to `HISTORICAL`, the new one is `VERIFIED`, and the registrant's `current_residence_address_id` is repointed to the new address. A new address defaults to `VERIFIED` status. Because recording a residence mutates the registrant, this endpoint is the one guarded by optimistic concurrency: the caller supplies `expected_registrant_version` and a mismatch yields `ERR_STALE_VERSION` as described in Section 2.8; on success the registrant's `version` is incremented by one. Only recording a `RESIDENCE` address mutates the registrant in this way; recording a non-residence address (`EMPLOYMENT`, `SCHOOL`, or `TEMPORARY`) leaves the registrant record untouched and does not increment its `version`, even though every address create — regardless of `address_type` — still carries `expected_registrant_version` and is rejected with `ERR_STALE_VERSION` on a mismatch.

Temporary occupancy windows may not overlap. A new `TEMPORARY` address whose window overlaps an existing `TEMPORARY` window for the same registrant is rejected with `ERR_ADDRESS_PERIOD_CONFLICT`; these windows are treated as closed intervals, so windows that merely touch at an endpoint are considered to conflict. Addresses can be listed for a registrant, optionally narrowed by an `address_type` query filter.

### 3.4. Verification Schedule and the Verification Check

Keeping registrants on their verification cadence is the core recurring obligation. A `RegistrationOfficer` records a verification by supplying a `verification_type` of `INITIAL`, `PERIODIC`, or `ADDRESS_CHANGE`; an optional `method` of `IN_PERSON` or `MAIL`, defaulting to `IN_PERSON`; and an `officer_ref` identifying the recording officer. On recording, the event's `completed_date` is set to the clock and its `result` is `VERIFIED` (the only result value in this version). Recording a verification resets the schedule: the registrant's `last_verified_date` becomes that completed date, and `next_verification_due` is recomputed. Verification events are owned through `registrant_id` and can be listed for a registrant.

The schedule is defined as follows. Let the anchor be the `completed_date` of the most recent `VERIFIED` verification event, or, when none exists, the registrant's `initial_registration_date`. The `next_verification_due` is that anchor plus the registrant's `verification_interval_days`. A registrant is overdue once the clock reaches or passes the due date plus the owning jurisdiction's `verification_grace_days` — that is, the overdue condition holds when the clock is greater than or equal to `next_verification_due` plus the grace days.

A `RegistrationOfficer` may invoke a verification check that re-evaluates the registrant against the current clock and advances any pending schedule and travel state. If the registrant is `ACTIVE` or `DELINQUENT` and overdue by the rule above (the overdue evaluation is performed only for registrants in those two states), the check opens a `MAJOR` `LATE_VERIFICATION` compliance flag, which recomputes `risk_score` and may drive the registrant from `ACTIVE` to `DELINQUENT` (and, as a consequence, deny any pending petition) exactly as described in Section 3.5. In the same pass, the check advances that registrant's travel notices against their windows: an `APPROVED` notice whose departure date has arrived (the clock is at or past `departure_date`) advances to `ACTIVE`; an `ACTIVE` `TEMPORARY` notice whose return date has arrived (the clock is at or past `return_date`) advances to `COMPLETED`, decrementing the destination jurisdiction's `active_travel_hold_count` by one; and an `ACTIVE` `TEMPORARY` notice still not completed once the clock has passed more than two days beyond its return date advances to `OVERDUE`, which opens a `MAJOR` `TRAVEL_VIOLATION` flag on the registrant.

### 3.5. Compliance Flags, Risk Scoring, Delinquency, and Absconding

Non-compliance is captured as flags. A `RegistrationOfficer` opens a flag by supplying a `flag_type` and an optional free-text `note`; the flag is owned through `registrant_id`, records its `opened_date` from the clock, begins `OPEN`, and its `resolved_date` is null until resolution. The flag type determines both a `severity` and a base weight `base_points`: `LATE_VERIFICATION` and `UNREPORTED_MOVE` are `MAJOR` and worth 15 points; `TRAVEL_VIOLATION` is `MINOR` and worth 5 points; `EXCLUSION_VIOLATION` and `ABSCONDED` are `CRITICAL` and worth 40 points. (These are the same weights used everywhere: a `MINOR` flag is 5, a `MAJOR` flag 15, and a `CRITICAL` flag 40 undecayed points.)

The registrant's live `risk_score` is a decayed sum over the flags currently `OPEN`. For each open flag, let the number of whole days it has been open be the floored day-count from its `opened_date` to the clock, never less than zero. Its decay factor is one minus one one-hundredth per day open, but never allowed to fall below a floor of one half — that is, the larger of 0.5 and (1.0 minus 0.01 times the days open). Each flag's contribution is its `base_points` multiplied by that decay factor, rounded half up to a whole number, and the `risk_score` is the integer sum of those per-flag contributions. A registrant is delinquent once this score reaches or exceeds the delinquency threshold of 15.

Opening a flag recomputes the score. If the recomputed `risk_score` reaches or passes 15 while the registrant is `ACTIVE`, the registrant transitions `ACTIVE → DELINQUENT`; as a cascade, any petition of that registrant still in `PENDING` decision is transitioned to `DENIED` (its deregistration eligibility is lost) with its `decided_date` set to the clock. Resolving a flag is the compensating action: a `RegistrationOfficer` resolves an `OPEN` flag, which sets its `status` to `RESOLVED` and its `resolved_date` to the clock and recomputes `risk_score`. Resolving a flag that is not `OPEN` is rejected with `ERR_INVALID_STATE`. When, after a resolution, the registrant has no `OPEN` flags remaining and the recomputed score is below 15 and the registrant is not an absconder, the registrant transitions `DELINQUENT → ACTIVE` with the score recomputed to zero.

Absconding is handled as a distinct branch. Opening a flag of type `ABSCONDED` moves the registrant into `ABSCONDER` (whether it was `ACTIVE` or `DELINQUENT`): a `CRITICAL` `ABSCONDED` flag is opened, the score is recomputed, and every travel notice of that registrant still in `SUBMITTED`, `APPROVED`, or `ACTIVE` is cancelled, with the destination jurisdiction's `active_travel_hold_count` decremented by one for each notice that had been `APPROVED` or `ACTIVE` at the time. A registrant leaves `ABSCONDER` only when the `ABSCONDED` flag is resolved and no other `OPEN` flag remains: resolving that flag transitions `ABSCONDER → ACTIVE` and recomputes the score. Flags can be listed for a registrant, optionally narrowed by a `status` query filter.

### 3.6. Travel and Inter-Jurisdiction Notices

Movement between jurisdictions is governed by travel notices. A `RegistrationOfficer` or the owning `Registrant` submits a notice giving the `destination_jurisdiction_id`, a `travel_type` of `TEMPORARY` or `RELOCATION`, a `departure_date`, and, for temporary travel, a `return_date`. The submitting registrant must be `ACTIVE`; a travel action on a registrant that is not `ACTIVE` is rejected with `ERR_REGISTRANT_NOT_ACTIVE`. The destination must resolve, otherwise `ERR_JURISDICTION_NOT_FOUND`. For `TEMPORARY` travel the `return_date` is required — its absence is rejected with `ERR_MISSING_TRAVEL_RETURN` — and it must be strictly later than the `departure_date`, while the `departure_date` must not be in the past (the clock must be at or before it); a violation of either date rule is rejected with `ERR_INVALID_TRAVEL_DATES`. A `RELOCATION` notice carries no return date. The notice is owned through `registrant_id` and begins in `SUBMITTED`.

Travel windows for the same registrant may not overlap. The overlap test treats each window as half-open — spanning from its departure date up to but not including its return date — and a new window that overlaps any existing non-terminal window is rejected with `ERR_TRAVEL_WINDOW_CONFLICT`.

A `RegistrationOfficer` decides a submitted notice by supplying a `decision` and an optional `decision_note`. An approval requires the owning registrant to still be `ACTIVE` (otherwise `ERR_REGISTRANT_NOT_ACTIVE`) and the destination jurisdiction to be `ACTIVE` (otherwise `ERR_JURISDICTION_INACTIVE`); on approval the notice moves `SUBMITTED → APPROVED` and the destination jurisdiction's `active_travel_hold_count` is incremented by one. A denial moves the notice `SUBMITTED → DENIED`, recording the `decision_note` and leaving hold counts unchanged; denial is terminal. Deciding a notice that is not in `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

Once approved, a notice's later life is driven by the verification check against travel windows (Section 3.4): `APPROVED → ACTIVE` at departure, `ACTIVE → COMPLETED` at return for temporary travel, and `ACTIVE → OVERDUE` when a temporary trip runs more than two days past its return without completing. At any point while a notice is `APPROVED` or `ACTIVE`, a `RegistrationOfficer` or the owning `Registrant` may cancel it: the notice moves to `CANCELLED` and, because the approval had raised the destination's hold, the destination jurisdiction's `active_travel_hold_count` is decremented by one to restore the pre-approval value. Cancelling a notice that is already terminal is rejected with `ERR_INVALID_STATE`. Notices can be listed per registrant (optionally by `status`), and a jurisdiction's inbound notices can be listed from the destination side.

### 3.7. Community Notification

A `RegistrationOfficer` dispatches a community notification for a registrant by supplying only the `audience_scope`, one of `LAW_ENFORCEMENT`, `SCHOOLS_ONLY`, or `PUBLIC`. The record is owned through `registrant_id` and stamps its `dispatched_date` from the clock; the remaining fields are computed at dispatch.

The notification `radius_meters` follows the registrant's tier: 0 meters for `TIER_1`, 500 meters for `TIER_2`, and 1500 meters for `TIER_3`. Two recipient figures are produced. The forward-looking `estimated_recipients` is the owning jurisdiction's `est_households_per_notification` multiplied by a tier multiplier of 0 for `TIER_1`, 3 for `TIER_2`, and 10 for `TIER_3`; it ignores actual addresses. The measured `actual_recipients` is the count of `VERIFIED` `RESIDENCE` addresses belonging to other registrants whose straight-line grid distance to the subject registrant's current residence is less than or equal to the notification radius. Both figures are whole integers. Notifications can be listed for a registrant.

### 3.8. Petitions to Deregister or Reduce Tier

A registrant may seek relief. The owning `Registrant` or a `RegistrationOfficer` files a petition giving only the `petition_type`, either `DEREGISTER` or `TIER_REDUCTION`. The petition is owned through `registrant_id`, stamps its `filed_date` from the clock, begins with `decision` `PENDING`, and its `decided_date` is null until decided. Filing requires the registrant to be `ACTIVE`; otherwise the filing is rejected with `ERR_REGISTRANT_NOT_ACTIVE`. Only one open petition is allowed at a time: filing while a `PENDING` petition already exists is rejected with `ERR_DUPLICATE_ACTIVE_PETITION`.

At filing the system records two derived figures. The `adjudicated_risk_score` is a lifetime risk figure computed over all of the registrant's flags ever opened — both `OPEN` and `RESOLVED` — using each flag's full `base_points` with no time decay, summed as whole integers. The boolean `eligibility_met` records whether deregistration eligibility holds at filing. Eligibility requires all of the following: the petition type is `DEREGISTER`; the registrant's tier is not `TIER_3`; the registrant has been registered long enough; and the record is clean. The minimum registered duration depends on tier — at least 10 years for `TIER_1` and at least 25 years for `TIER_2`, while `TIER_3` uses a lifetime minimum of 999 years and is therefore never eligible — and the duration is met when the clock has reached or passed the `initial_registration_date` plus that many whole years. The record is clean when the registrant has zero `OPEN` flags, has never had any flag of `CRITICAL` severity, and its `adjudicated_risk_score` is strictly below 30.

A `ComplianceReviewer`, and only a `ComplianceReviewer`, decides a petition — this is the segregation-of-duties boundary — by supplying a `decision` and an optional `reviewer_ref` recording the deciding reviewer. Deciding a petition that is not `PENDING` is rejected with `ERR_INVALID_STATE`. A withdraw decision moves the petition `PENDING → WITHDRAWN`, leaving its `decided_date` null. A deny decision moves it `PENDING → DENIED` and sets `decided_date` to the clock. A grant decision re-checks eligibility at decision time: it requires the petition to be a `PENDING` `DEREGISTER`, the registrant to be `ACTIVE` with zero `OPEN` flags, and deregistration eligibility to still hold; if any of these fails, the grant is rejected with `ERR_PETITION_NOT_ELIGIBLE`. On a successful grant the petition moves `PENDING → GRANTED` with `decided_date` set to the clock, and the registrant cascades `ACTIVE → DEREGISTERED`: every `VERIFIED` address of that registrant transitions to `HISTORICAL` and its `current_residence_address_id` is cleared to null. Petitions can be listed per registrant and read individually.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource, list a collection, or drive a state transition or other mutation on an existing resource return `200 OK`. Every endpoint requires the authentication headers of Section 2.1, and access is limited to the authorized roles below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sorna/jurisdictions` | Create a jurisdiction | RegistryAdmin |
| GET | `/sorna/jurisdictions/{id}` | Read a jurisdiction | RegistryAdmin, RegistrationOfficer, ComplianceReviewer |
| POST | `/sorna/jurisdictions/{id}/exclusion-zones` | Create an exclusion zone in a jurisdiction | RegistryAdmin |
| GET | `/sorna/jurisdictions/{id}/exclusion-zones` | List a jurisdiction's exclusion zones | RegistryAdmin, RegistrationOfficer |
| GET | `/sorna/exclusion-zones/{id}` | Read an exclusion zone | RegistryAdmin, RegistrationOfficer |
| GET | `/sorna/jurisdictions/{id}/registrants` | List a jurisdiction's registrants | RegistrationOfficer, ComplianceReviewer |
| GET | `/sorna/jurisdictions/{id}/inbound-travel-notices` | List inbound travel notices for a jurisdiction | RegistrationOfficer, ComplianceReviewer |
| GET | `/sorna/jurisdictions/{id}/compliance-report` | Roster report of registrant counts by status | ComplianceReviewer, RegistrationOfficer |
| POST | `/sorna/registrants` | Register a new subject | RegistrationOfficer |
| GET | `/sorna/registrants/{id}` | Read a registrant | RegistrationOfficer, ComplianceReviewer, Registrant |
| POST | `/sorna/registrants/{id}/offenses` | Add an offense and recompute tier | RegistrationOfficer |
| GET | `/sorna/registrants/{id}/offenses` | List a registrant's offenses | RegistrationOfficer |
| POST | `/sorna/registrants/{id}/activate` | Activate a PENDING registrant | RegistrationOfficer |
| POST | `/sorna/registrants/{id}/addresses` | Add or update an address | RegistrationOfficer, Registrant |
| GET | `/sorna/registrants/{id}/addresses` | List a registrant's addresses | RegistrationOfficer, Registrant |
| POST | `/sorna/registrants/{id}/verifications` | Record a verification and reset the schedule | RegistrationOfficer |
| GET | `/sorna/registrants/{id}/verifications` | List a registrant's verification events | RegistrationOfficer |
| POST | `/sorna/registrants/{id}/verification-check` | Re-evaluate schedule and travel windows | RegistrationOfficer |
| POST | `/sorna/registrants/{id}/flags` | Open a compliance flag | RegistrationOfficer |
| GET | `/sorna/registrants/{id}/flags` | List a registrant's compliance flags | RegistrationOfficer, ComplianceReviewer |
| POST | `/sorna/compliance-flags/{id}/resolve` | Resolve an OPEN compliance flag | RegistrationOfficer |
| POST | `/sorna/registrants/{id}/travel-notices` | Submit a travel or relocation notice | RegistrationOfficer, Registrant |
| GET | `/sorna/registrants/{id}/travel-notices` | List a registrant's travel notices | RegistrationOfficer, Registrant |
| POST | `/sorna/travel-notices/{id}/decision` | Approve or deny a submitted travel notice | RegistrationOfficer |
| POST | `/sorna/travel-notices/{id}/cancel` | Cancel an approved or active travel notice | RegistrationOfficer, Registrant |
| POST | `/sorna/registrants/{id}/notifications` | Dispatch a community notification | RegistrationOfficer |
| GET | `/sorna/registrants/{id}/notifications` | List a registrant's notifications | RegistrationOfficer, ComplianceReviewer |
| POST | `/sorna/registrants/{id}/petitions` | File a petition to deregister or reduce tier | Registrant, RegistrationOfficer |
| GET | `/sorna/registrants/{id}/petitions` | List a registrant's petitions | RegistrationOfficer, ComplianceReviewer, Registrant |
| GET | `/sorna/petitions/{id}` | Read a petition | RegistrationOfficer, ComplianceReviewer, Registrant |
| POST | `/sorna/petitions/{id}/decision` | Grant, deny, or withdraw a petition | ComplianceReviewer |
| POST | `/sorna/_clock/set_current_utc` | Set the logical clock | RegistryAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_REGISTRANT_NOT_FOUND` | 404 |
| `ERR_ADDRESS_NOT_FOUND` | 404 |
| `ERR_EXCLUSION_ZONE_NOT_FOUND` | 404 |
| `ERR_FLAG_NOT_FOUND` | 404 |
| `ERR_TRAVEL_NOTICE_NOT_FOUND` | 404 |
| `ERR_PETITION_NOT_FOUND` | 404 |
| `ERR_REGISTRANT_NOT_PENDING` | 409 |
| `ERR_NO_OFFENSES` | 409 |
| `ERR_REGISTRANT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_EXCLUSION_ZONE_VIOLATION` | 409 |
| `ERR_INVALID_TRAVEL_DATES` | 422 |
| `ERR_MISSING_TRAVEL_RETURN` | 422 |
| `ERR_TRAVEL_WINDOW_CONFLICT` | 409 |
| `ERR_ADDRESS_PERIOD_CONFLICT` | 409 |
| `ERR_JURISDICTION_INACTIVE` | 409 |
| `ERR_DUPLICATE_ACTIVE_PETITION` | 409 |
| `ERR_PETITION_NOT_ELIGIBLE` | 409 |

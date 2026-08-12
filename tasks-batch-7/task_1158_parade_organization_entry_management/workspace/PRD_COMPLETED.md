# Parade Organization API — Product Requirements Document

## 1. Introduction

Organizing a civic parade is an exercise in multi-party coordination. A single organizing committee must win permits from four municipal agencies at once, vet dozens of marching organizations, certify every float and vehicle that enters the route, place each approved entry into a staging lot on a minute-precise schedule, blanket the route with volunteer marshals, run a judged competition, honor sponsor commitments in the announcer's script, and still guarantee that an emergency lane stays open end to end. This document specifies the Parade Organization API, the system of record through which a parade organizing committee runs that entire lifecycle — from the first draft of a parade edition through route and staging design, the agency permit filing, entry application review and category assignment, float safety inspection, lineup construction, judging and award presentation, sponsor recognition, and the final dispersal of the crowd.

Two design commitments shape every endpoint in this API. First, a derived **event posture** gates all productive work: the moment a permit is denied or revoked, or the parade is cancelled, the whole edition freezes and every downstream mutation is rejected, with cascading pull-backs of confirmed lineup slots and announcer script items. Second, authority is strictly segregated — the committee requests, the agencies decide; one inspector records a failure, a different inspector must re-inspect; judges submit scores, only the committee finalizes them. A server-owned logical clock, rather than wall-clock time, decides every deadline, window, and no-show determination, so the entire workflow is reproducible under test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply uniformly to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or presenting a role string the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, a caller may only exercise the operations granted to their role, and certain operations additionally demand ownership of the target resource; a role or ownership failure is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles. `CommitteeAdmin` is the parade organizing committee administrator and drives the parade, route, staging, entry-review, lineup, marshal-roster, script, sponsorship, and award lifecycle. `AgencyReviewer` is an external agency officer (police, fire, transit, or sanitation) who decides endorsements, permit outcomes, and dispersal-plan approval. `SafetyInspector` is a certified float and vehicle inspector who schedules inspections and records their outcomes. `Entrant` is the representative of a marching organization and owns its entry applications. `Judge` is a panel judge who owns score sheets. `Marshal` is a route volunteer who owns marshal assignments.

All six roles use opaque identity: the value of `X-User-ID` is an opaque operator identifier that is never compared to any persisted entity's `id`. The server does, however, record the identifier on resources at creation time and later compares it for ownership. When `X-User-Role` is `Entrant`, the identifier is copied onto the entry application as `applicant_user_id`, and ownership checks on that entry compare `X-User-ID` against `applicant_user_id`. When `X-User-Role` is `Judge`, the identifier is copied onto the score sheet as `judge_user_id` and governs who may submit or reopen it. When `X-User-Role` is `SafetyInspector`, the identifier is recorded as `inspector_user_id` on the scheduled inspection. When `X-User-Role` is `Marshal`, the identifier named on the assignment, `marshal_user_id`, governs who may confirm or complete it. When `X-User-Role` is `CommitteeAdmin` or `AgencyReviewer`, the identifier authorizes the operation but is recorded on no entity.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer value, a `limit` outside 1 to 100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation sequence (earliest created first). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Parade Posture: The Event-Wide Operational Gate

Every parade edition carries a computed `posture` in addition to its lifecycle `status`, and the posture — not the status — is what gates most productive mutations. The posture is `FROZEN` whenever the parade has been `CANCELLED` or the latest permit application of the parade is in `DENIED` or `REVOKED` status. Otherwise, the posture is `OPERATIONAL` exactly when three conditions hold together: the permit is `GRANTED`, a dispersal plan of the parade is `APPROVED`, and the parade's own status is one of `PERMIT_GRANTED`, `LOCKED`, or `LINEUP_PUBLISHED`. In every remaining situation the posture is `RESTRICTED`. Posture is recomputed immediately whenever the permit changes state, whenever a dispersal plan is approved or rejected, and whenever the parade itself is cancelled; a brand-new parade always starts in `RESTRICTED` posture.

A `FROZEN` posture is a hard stop. While a parade is frozen, the following mutations are all rejected with `ERR_EVENT_FROZEN` (HTTP 409): starting review on an entry, approving, rejecting, or requesting revision on an entry, an entrant's resubmission of an entry, confirming a lineup assignment, checking a lineup assignment in, submitting a score sheet, finalizing a score sheet, activating a sponsor package, approving a script item, announcing or presenting an award, and publishing the lineup. Freezing never deletes anything by itself; it blocks forward progress until the underlying cause is repaired — a denied permit can be refiled, which recomputes the posture and lets the parade leave `FROZEN`.

### 2.5. Common Resource Properties and Versioned Mutation

Every resource in this API — parade, route segment, permit application, agency endorsement, entry application, float, safety inspection, staging area, lineup assignment, marshal assignment, score sheet, award, sponsor package, script item, and dispersal plan — carries the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records the creation instant as an ISO 8601 UTC value with three fractional digits. The `updated_at` timestamp, in the same format, refreshes on every modification. The `version` is an integer that starts at 1 when the resource is created and increments by exactly one on every mutation, including state transitions, attribute replacements, and cascade-driven changes.

Derived counters and aggregates follow an immediate-consistency model: a change that affects a derived value recomputes that value as part of the same write, never asynchronously. This governs `approved_entry_count` on the parade (the count of its entries in `APPROVED` status), `sponsor_seconds_allocated` on the parade, `endorsed_count` on the permit (the count of its endorsements in `ENDORSED` status), `reserved_slots` on each staging area, and `allocated_seconds` on each sponsor package, as well as computed monetary, score, and duration fields described later.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. The server first resolves the parade identifier, then the intermediate resource identifier (permit, entry, float, and so on), then the child identifier; the request is rejected at the first path segment whose `{id}` does not resolve, with the not-found error that corresponds to that segment's resource type. The per-resource identifiers are `ERR_PARADE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_FLOAT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_STAGING_AREA_NOT_FOUND`, `ERR_ROUTE_SEGMENT_NOT_FOUND`, `ERR_LINEUP_ASSIGNMENT_NOT_FOUND`, `ERR_MARSHAL_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_SHEET_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_SCRIPT_ITEM_NOT_FOUND`, and `ERR_DISPERSAL_PLAN_NOT_FOUND`, each with HTTP status 404. A request to schedule an inspection under a float that does not exist therefore fails as `ERR_FLOAT_NOT_FOUND` before the inspection itself is ever considered.

### 2.7. The Logical Clock

All time-sensitive decisions in this API — deadline enforcement, window containment, no-show determination, and the `submitted_at`, `decided_at`, and `announced_at` instants stamped by transitions — read a server-owned **logical clock**, never the host wall clock. At startup, before any client intervention, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `CommitteeAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant (a missing `to_iso8601` is `ERR_VALIDATION`) and returns the resulting `current_utc`; once set, the clock holds the assigned value and never falls back to wall-clock time.

### 2.8. Money, Precision, and Rounding

All monetary amounts are integer cents; no fractional cents ever appear. Where a percentage surcharge applies to a cent amount — the late-entry surcharge and the permit expedite surcharge — the surcharge itself is rounded half-up to a whole cent before being added. Judging scores are the one non-integer quantity: both `provisional_score` and `final_score` are expressed with exactly 2 decimal places, rounded half-up. Script timing works in whole seconds, with each script item's duration rounded half-up individually before any summation. Instant comparisons are exact for marshal shifts, and are made at minute granularity after buffer expansion for staging windows.

### 2.9. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and they are the only two endpoints in the API that accept a version field.

Publishing the lineup of a parade requires the request to carry `expected_parade_version`, holding the parade `version` the client last observed. If the parade's current `version` has advanced past that value — because another committee write has landed since the client read the parade — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from publishing over a parade state it never observed.

Requesting an agency endorsement against a permit application requires the request to carry `expected_permit_version`, holding the permit `version` the client last observed. Each endorsement creation legitimately succeeds on its own and advances the permit's version, so a creation carrying an earlier observed version is stale: it is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these two accepts an expected-version field.

### 2.10. Validation Discipline and Check Ordering

When several checks could reject the same request, the server evaluates them in a fixed priority order and returns the first failure encountered. The order, from first to last, is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is declared (`ERR_UNAUTHENTICATED`).
2. **Authorization and ownership** — the role is permitted on the endpoint, and where the endpoint demands the owner, `X-User-ID` matches the recorded `applicant_user_id`, `marshal_user_id`, or `judge_user_id` (`ERR_FORBIDDEN`).
3. **Path existence** — every path identifier resolves, validated left to right (the per-resource 404 family of §2.6).
4. **Request-body schema** — required fields are present, types are valid, enum members are valid, numeric ranges hold (`estimated_participants` at least 1, `capacity` at least 1, `checklist_score` within 0 to 100 inclusive, the end strictly after the start for time pairs), and conditional references are present when required — `sponsor_id` when the item type is `SPONSOR_READ`, `entry_id` when the item type is `ENTRY_INTRO` (`ERR_VALIDATION`, HTTP 400).
5. **State eligibility** — the target resource stands in a valid from-state for the requested transition. Specialized state failures carry their own codes — a frozen parade surfaces `ERR_EVENT_FROZEN`, an entry that is not approved surfaces `ERR_ENTRY_NOT_APPROVED`, a parade whose lineup is not published surfaces `ERR_LINEUP_NOT_PUBLISHED`, a lock attempted without a granted permit surfaces `ERR_PERMIT_NOT_GRANTED` — while all other from-state mismatches use the generic `ERR_INVALID_STATE` (HTTP 409). Within this tier, the endpoint's own from-state and specialized state checks are evaluated before the frozen-parade check, so a transition attempted from a wrong from-state on a frozen parade reports the from-state failure, not `ERR_EVENT_FROZEN`.
6. **Safety gates** — the float-certification gate on lineup confirmation (`ERR_FLOAT_UNCERTIFIED`), the re-inspection segregation-of-duties rule (`ERR_REINSPECTION_SOD`), and the emergency-lane minimum width at dispersal submit (`ERR_EMERGENCY_LANE_TOO_NARROW`).
7. **Uniqueness and capacity constraints** — one permit per parade (`ERR_PERMIT_ALREADY_EXISTS`), one dispersal plan per parade (`ERR_PLAN_ALREADY_EXISTS`), one live endorsement per agency on a permit (`ERR_DUPLICATE_AGENCY_ENDORSEMENT`), one score sheet per judge on an entry (`ERR_DUPLICATE_SCORE_SHEET`), lineup position uniqueness (`ERR_LINEUP_POSITION_TAKEN`), staging capacity (`ERR_STAGING_CAPACITY_FULL`), and the float-category rule (`ERR_CATEGORY_WITHOUT_FLOAT`).
8. **Temporal-window rules** — the staging expanded-window conflict (`ERR_STAGING_WINDOW_CONFLICT`), staging-hours containment (`ERR_WINDOW_OUTSIDE_STAGING_HOURS`), marshal shift overlap (`ERR_MARSHAL_WINDOW_OVERLAP`), the entry-submission deadline (`ERR_ENTRY_DEADLINE_PASSED`), and check-in, no-show, and marshal-completion windows (`ERR_CHECKIN_WINDOW_NOT_OPEN`).
9. **Fiscal gates** — the entry fee must be paid before confirmation (`ERR_ENTRY_FEE_OUTSTANDING`, HTTP 402) and every active sponsor must meet its tier minimum before the script can be finalized (`ERR_SPONSOR_MINUTES_UNMET`).
10. **Referential-pool rules** — the award winner pool must be non-empty (`ERR_NO_ELIGIBLE_WINNER`), and script-item references must point at live resources of the same parade: an active sponsor for `SPONSOR_READ`, an entry of the parade for `ENTRY_INTRO` (both surfaced as `ERR_INVALID_STATE`).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Parade Edition

A `CommitteeAdmin` opens a new parade edition by supplying its public `name`, the scheduled `parade_date`, and the `entry_deadline` past which no new entry applications are accepted. The edition is born with `status` set to `DRAFT`, `posture` computed as `RESTRICTED`, `script_finalized` false, both derived counters `approved_entry_count` and `sponsor_seconds_allocated` at zero, and `version` 1. The parade catalogue can be listed with pagination and filtered by `status` or `posture`, so a committee dashboard can watch several editions at once.

With the edition standing, the committee lays out the route. Each **route segment** is recorded against its parade via `parade_id` and carries an `order_index` fixing its position along the route — a plain integer with no uniqueness constraint — a street `name`, a `length_meters` greater than zero, an `emergency_lane_width_m` reserving the segment's emergency lane at no less than 3.0 meters, and the planned traversal window `segment_window_start` to `segment_window_end`, where the end must fall strictly after the start.

Staging logistics come next. Each **staging area** belongs to a parade and is created with a lot `name`, a `capacity` of at least one simultaneous active lineup assignment, and trading hours from `open_time` to `close_time`, the close strictly after the open. A fresh lot's `reserved_slots` counter starts at zero and later tracks how many of its assignments stand confirmed or checked in.

Only when the edition has both structure and somewhere to stage can the permit process begin. Submitting the permit step moves the parade from `DRAFT` to `PERMIT_PENDING` and demands that at least one route segment and at least one staging area already exist for the parade; without them the request fails with `ERR_INVALID_STATE`.

### 3.2. Agency Coordination: Permits, Endorsements, and the Dispersal Plan

A parade files at most one permit application; a second attempt is rejected with `ERR_PERMIT_ALREADY_EXISTS`. The application is created in `DRAFT` status with a flat provisional estimate: `provisional_fee_cents` is 75,000 cents plus 5,000 cents per required agency, and since `required_agency_count` is always four — the fixed agency set `POLICE`, `FIRE`, `TRANSIT`, and `SANITATION` — every new application estimates at exactly 95,000 cents. While the application remains in `DRAFT`, both `final_fee_cents` and `submitted_at` stay null, and `endorsed_count` reads zero. Because a parade has at most one permit, fetching a parade's permit returns an array of zero or one element rather than a single object.

Before the filing can go out, the committee must request an endorsement from each agency. Creating an endorsement names the `agency_type` and carries the OCC field `expected_permit_version` described in §2.9 — a stale observed version is rejected with `ERR_STALE_VERSION`, and this staleness check runs before the duplicate-agency check. At most one endorsement in `PENDING` or `ENDORSED` status may exist per agency type on a permit; a duplicate request is rejected with `ERR_DUPLICATE_AGENCY_ENDORSEMENT`. Every endorsement creation advances the permit's version by one, and the new endorsement records that post-creation value in its own `permit_version` field as a read-back of where the permit stood immediately after the request landed. An `AgencyReviewer` then decides each request: endorsing moves it from `PENDING` to `ENDORSED`, rejecting moves it from `PENDING` to `REJECTED`, and either decision stamps `decided_at` from the logical clock and recomputes the permit's `endorsed_count`. The endorsement list of a permit paginates and can be filtered by `status`.

Submitting the permit moves it from `DRAFT` to `AGENCY_REVIEW`. Two preconditions guard the submission, both enforced as `ERR_INVALID_STATE`: the parade itself must stand in `PERMIT_PENDING`, and each of the four agency types must have at least one `PENDING` endorsement on file. A successful submission stamps `submitted_at` from the logical clock and settles the real filing cost into `final_fee_cents`: the per-agency table charges 30,000 cents for `POLICE`, 25,000 for `FIRE`, 20,000 for `TRANSIT`, and 15,000 for `SANITATION`, a base of 90,000 cents, and when the submission instant falls later than the instant fourteen days before `parade_date`, an expedite surcharge of twenty percent of that base, rounded half-up to whole cents, is added — 108,000 cents in the expedited case.

The agency decision then resolves the filing. Granting requires that each of the four agency types hold at least one `ENDORSED` endorsement — otherwise `ERR_INVALID_STATE` — and moves the permit from `AGENCY_REVIEW` to `GRANTED`; the same write flips the parade from `PERMIT_PENDING` to `PERMIT_GRANTED` and recomputes its posture. Denying moves the permit to `DENIED` and recomputes the posture, which turns `FROZEN` and halts the edition. A denial is not the end: refiling moves the permit from `DENIED` back to `DRAFT`, resets `final_fee_cents` and `submitted_at` to null, and recomputes the posture so the parade leaves `FROZEN`.

Revocation is the most destructive agency action and fires a four-hop cascade. Hop one moves the permit from `GRANTED` to `REVOKED`. Hop two forces a posture recompute on the parade, which becomes `FROZEN`. Hop three pulls every lineup assignment of the parade standing in `CONFIRMED` or `CHECKED_IN` to `PULLED`; `TENTATIVE` assignments are left in place, though they cannot be confirmed while the parade remains frozen. Hop four disposes of each pulled assignment's footprint: its staging slot is released (the lot's `reserved_slots` is recomputed) and every announcer script item of type `ENTRY_INTRO` naming the pulled assignment's entry, still in `APPROVED` status, is cancelled. Sponsor recognition is untouched by this cascade — only `SPONSOR_READ` items count toward a sponsor's `allocated_seconds`, and intro cancellations never move that number.

The fourth agency touchpoint is the **dispersal plan**. A parade carries at most one — a second creation is rejected with `ERR_PLAN_ALREADY_EXISTS` — drafted with a guaranteed `emergency_lane_width_m`, an ordered, non-empty-at-submit list of `dispersal_corridors`, and optional free-text `evacuation_notes`. Submitting the plan moves it from `DRAFT` to `SUBMITTED` and enforces two gates: the guaranteed emergency lane width must be at least 3.0 meters, or the submission fails with `ERR_EMERGENCY_LANE_TOO_NARROW` (HTTP 422), and the corridor list must be non-empty, or it fails with `ERR_VALIDATION`. An `AgencyReviewer` then approves or rejects the submission — both outcomes recompute the parade's posture, because an `APPROVED` plan is one leg of the `OPERATIONAL` posture — and a rejected plan returns from `REJECTED` to `DRAFT` through the committee's revise action, ready for another attempt. Like the permit, a parade's dispersal plan is fetched as an array of zero or one element.

### 3.3. Entry Applications and the Review Cycle

A marching organization joins the parade when an `Entrant` submits an entry application carrying the organization's `org_name`, a `requested_category` of `FLOAT`, `BAND`, `WALKING_GROUP`, `VEHICLE`, or `EQUESTRIAN`, and an `estimated_participants` count of at least one. The server copies the caller's header into `applicant_user_id` at creation, and every later ownership check on the entry compares `X-User-ID` against that recorded value. Creation is only accepted while the logical clock reads at or before the parade's `entry_deadline`; a late submission is rejected with `ERR_ENTRY_DEADLINE_PASSED` (HTTP 422). A new application is born `SUBMITTED` with `revision_count` zero, `assigned_category` still null, `fee_paid` false, and both `provisional_score` and `final_score` null until judging produces them.

The participation fee, `fee_cents`, is computed at creation, again at approval, and again at every resubmission. The calculation starts from a category base — 50,000 cents for `FLOAT`, 30,000 for `BAND`, 15,000 for `WALKING_GROUP`, 40,000 for `VEHICLE`, and 35,000 for `EQUESTRIAN` — where the category basis is the entry's `assigned_category` once the committee has set it and its `requested_category` before that. The base is then grown by a participant-scaled amount evaluated in a pinned order: first, 300 cents for each of the first 50 estimated participants; then 200 cents for each of the next 150, covering participants 51 through 200; then 100 cents for every participant beyond 200. Finally, if the submission instant falls later than the instant seven days before the parade's `entry_deadline`, a late surcharge of twenty-five percent of the running subtotal, rounded half-up to whole cents, is added. The submission instant used for that late branch is the entry's `created_at` at creation time and again at approval time, and the current logical clock at resubmission time. Because all tier rates are whole cents, no rounding occurs before the surcharge step.

Committee review begins when a `CommitteeAdmin` starts review, moving the entry from `SUBMITTED` to `UNDER_REVIEW`. From there the committee has three exits, each requiring the parade's posture to be unfrozen (`ERR_EVENT_FROZEN` applies otherwise). Approval moves the entry to `APPROVED`, sets `assigned_category` from the request payload, recomputes `fee_cents` on the newly assigned category basis, and refreshes the parade's `approved_entry_count`. Rejection moves the entry to `REJECTED`, a terminal state, and may carry an optional `reason`. A revision request moves the entry to `REVISION_REQUESTED`, records the committee's `revision_notes`, and increments `revision_count` by one.

The revision loop belongs to the entrant. Resubmitting moves the entry from `REVISION_REQUESTED` back to `SUBMITTED` and is restricted to the owning entrant — a caller whose `X-User-ID` does not match the entry's `applicant_user_id` is refused with `ERR_FORBIDDEN` — and to an unfrozen parade. When the resubmission payload carries a fresh `org_name` or `estimated_participants`, those values replace the stored ones, and `fee_cents` is recomputed with the current category basis and the current logical clock for the late-surcharge branch.

Withdrawal likewise belongs to the owning entrant and is permitted from either `SUBMITTED` or `APPROVED`. Withdrawing an approved entry is the heavier operation: every lineup assignment of that entry standing in `CONFIRMED` or `CHECKED_IN` is pulled, and each pull releases its staging slot and cancels the entry's approved `ENTRY_INTRO` script items; the parade's `approved_entry_count` is then recomputed. Either way the entry lands in `WITHDRAWN`, terminal. Separately, the owning entrant may settle the participation fee at any time through the pay-fee action, which sets `fee_paid` to true — a flag that later gates lineup confirmation. The entries of a parade can be listed with pagination and filtered by `status` or `assigned_category`.

### 3.4. Floats and Safety Inspection

An entry whose parade presence involves a vehicle must register it. Float registration is open to the owning entrant only once the entry stands `APPROVED`, and only when its `assigned_category` is `FLOAT` or `VEHICLE`; an attempt for any other category — or for an entry not currently `APPROVED` — is rejected with `ERR_CATEGORY_WITHOUT_FLOAT` (HTTP 422). The registration payload carries `length_m`, `width_m`, `height_m`, and `weight_kg`, each greater than zero, plus a `vehicle_class` of `SELF_PROPELLED`, `TOWED`, or `PUSHED` and a `fuel_type` of `GASOLINE`, `DIESEL`, `ELECTRIC`, or `NONE`. A freshly registered float waits in `PENDING_INSPECTION` compliance.

A `SafetyInspector` schedules an inspection by proposing a `scheduled_at` instant; the server records the caller as `inspector_user_id` from the header. A float may hold at most one `SCHEDULED` inspection at a time — scheduling a second is rejected with `ERR_INVALID_STATE` — and scheduling one against a float currently in `FAILED` compliance returns the float to `PENDING_INSPECTION` so the cycle can restart. Segregation of duties governs re-inspection: the inspector of a new inspection must differ from the inspector who recorded the float's latest `FAILED` inspection, and a violation is rejected with `ERR_REINSPECTION_SOD` (HTTP 422).

The inspection's outcome is decided against a recorded `checklist_score` between 0 and 100. The score-to-outcome consistency rules are validated before the inspection's from-state: a pass attempted with a score below 70 fails with `ERR_VALIDATION` even when the inspection is no longer `SCHEDULED`, and likewise for a fail attempted at 70 or above. Passing stamps `decided_at` from the logical clock; the float then transitions from `PENDING_INSPECTION` to `CERTIFIED` — a pass recorded against a float already `CERTIFIED` (a spot re-inspection that passes) leaves it `CERTIFIED` — and if the parent entry had been sitting in `SUSPENDED`, it is compensated back to `APPROVED` with the parade's `approved_entry_count` recomputed. Failing requires a score strictly below 70 — a fail attempted at 70 or above is `ERR_VALIDATION` — and fires a four-hop cascade of its own: the float's `compliance_status` becomes `FAILED`; the parent entry, if `APPROVED`, drops to `SUSPENDED`; that suspension pulls the entry's `CONFIRMED` and `CHECKED_IN` lineup assignments to `PULLED`; and each pull releases its staging slot and cancels the entry's approved `ENTRY_INTRO` script items. A certified float is not immune: a spot re-inspection that fails moves the float from `CERTIFIED` to `FAILED` and fires the identical suspension cascade. An inspection that will not happen can be cancelled, moving it from `SCHEDULED` to `CANCELLED`, terminal, with no further effects. Decided inspections — `PASSED`, `FAILED`, or `CANCELLED` — are all terminal.

### 3.5. Lineup Construction and Staging Operations

With entries approved, the committee builds the running order. Creating a lineup assignment names the `entry_id`, the `staging_area_id` that will host the entry before step-off, the `position_number` it will occupy in the parade, and the staging window `arrive_at` to `depart_at`. A body-referenced `entry_id` that does not resolve to an entry of this parade is rejected with `ERR_ENTRY_NOT_FOUND`, and a body-referenced `staging_area_id` that does not resolve to a staging area of this parade is rejected with `ERR_STAGING_AREA_NOT_FOUND`; the entry reference is resolved before the staging reference. Creation then requires the referenced entry to be `APPROVED` (`ERR_ENTRY_NOT_APPROVED` otherwise) and the parade to stand in `PERMIT_GRANTED` or `LOCKED` status (`ERR_INVALID_STATE` otherwise). The window must sit inside the staging lot's trading hours — `arrive_at` at or after the lot's `open_time`, `depart_at` at or before its `close_time`, and `depart_at` strictly after `arrive_at` — a rule checked both at creation and again at confirmation, with violations surfaced as `ERR_WINDOW_OUTSIDE_STAGING_HOURS` (HTTP 422). New assignments are born `TENTATIVE` and occupy no slot yet.

Confirmation is the most heavily gated transition in the system, and its checks run in a fixed order so that the first failure is the one reported. First the assignment itself must stand in `TENTATIVE` (`ERR_INVALID_STATE` otherwise). Then the parade's posture must not be `FROZEN` (`ERR_EVENT_FROZEN`), and the entry must stand `APPROVED` (`ERR_ENTRY_NOT_APPROVED`). Next, the safety gate: if the entry has any floats at all, every one of them must be `CERTIFIED`, else `ERR_FLOAT_UNCERTIFIED` (HTTP 422). Then come the two constraint checks — the requested `position_number` must not already be held by another assignment of the same parade in `TENTATIVE`, `CONFIRMED`, or `CHECKED_IN` status (`ERR_LINEUP_POSITION_TAKEN`), and the staging lot must have room (`ERR_STAGING_CAPACITY_FULL`, HTTP 422). Capacity is aggregate and inclusive at the boundary: a lot whose `reserved_slots` already equals its `capacity` rejects the confirmation, while a lot with exactly one free slot accepts it. After capacity come the two temporal checks in this order — first the expanded-window conflict (`ERR_STAGING_WINDOW_CONFLICT`), then the staging-hours containment re-check (`ERR_WINDOW_OUTSIDE_STAGING_HOURS`) — and only at the very end the fiscal gate: the entry's `fee_paid` must be true, or the confirmation fails with `ERR_ENTRY_FEE_OUTSTANDING` (HTTP 402).

The temporal check deserves its own paragraph because its semantics differ from the marshal rule in §3.6. Every assignment occupies an expanded window on its staging lot, running from fifteen minutes before `arrive_at` to fifteen minutes after `depart_at`, inclusive at both ends. A confirmation is rejected with `ERR_STAGING_WINDOW_CONFLICT` when that expanded window intersects the expanded window of any other assignment on the same lot in `CONFIRMED` or `CHECKED_IN` status — and because the intervals are closed, merely touching endpoints count as an intersection: a candidate arriving at exactly the minute another assignment's expanded window ends is a conflict. Instants are compared at minute granularity after the buffer is applied. A successful confirmation recomputes the lot's `reserved_slots` upward by one, since the counter tracks assignments in `CONFIRMED` or `CHECKED_IN` status.

On parade day, an assignment is checked in — moving it from `CONFIRMED` to `CHECKED_IN` — only after the lineup has been published (`ERR_LINEUP_NOT_PUBLISHED` while the parade is in any earlier status), only while the parade is unfrozen, and only while the logical clock reads within the assignment's own arrival-to-departure window, inclusive at both ends; outside that window the attempt fails with `ERR_CHECKIN_WINDOW_NOT_OPEN` (HTTP 422). From `CHECKED_IN`, the committee releases the entry once it has stepped off: the assignment moves to `RELEASED`, terminal, and the lot's `reserved_slots` drops by one.

Two failure exits mirror the happy path. Marking a no-show moves a `CONFIRMED` assignment to `NO_SHOW` and is only legal once the logical clock has passed `depart_at`; earlier attempts fail with `ERR_CHECKIN_WINDOW_NOT_OPEN`. A no-show releases the staging slot and cancels every approved `ENTRY_INTRO` script item naming the entry. Pulling an assignment — by explicit committee action from `TENTATIVE` or `CONFIRMED`, or by system cascade from `CHECKED_IN` — moves it to `PULLED`, terminal; a pull from `CONFIRMED` or `CHECKED_IN` releases the slot, a pull from `TENTATIVE` does not touch the counter, and every pull regardless of origin cancels the entry's approved `ENTRY_INTRO` items. The assignment book can be listed with pagination and filtered by `parade_id`, `entry_id`, `staging_area_id`, or `status`.

### 3.6. Marshal Coverage Along the Route

Marshals keep the route itself safe. The committee assigns a marshal by naming the `route_segment_id` to cover, the `marshal_user_id` being rostered, and a shift window from `shift_start` to `shift_end`, the end strictly after the start. A body-referenced `route_segment_id` that does not resolve to a route segment of this parade is rejected with `ERR_ROUTE_SEGMENT_NOT_FOUND`. The overlap rule here is the mirror image of the staging rule: marshal shifts are half-open intervals, so a new shift is rejected with `ERR_MARSHAL_WINDOW_OVERLAP` only when some existing assignment of the same `marshal_user_id` in `ASSIGNED` or `CONFIRMED` status starts before the new shift ends and ends after the new shift starts. Adjacency is expressly allowed — a new shift starting at the exact instant another of the marshal's shifts ends does not overlap it. Instants are compared exactly, with no buffer. A new assignment stands in `ASSIGNED` status.

From there the lifecycle belongs partly to the volunteer. Confirming moves an assignment from `ASSIGNED` to `CONFIRMED` and may only be performed by the marshal named on it — any other caller is refused with `ERR_FORBIDDEN`. Completing moves it from `CONFIRMED` to `COMPLETED`, again only by the named marshal, and only once the logical clock reads at or after `shift_end`; an early completion fails with `ERR_CHECKIN_WINDOW_NOT_OPEN`. The committee holds the negative exit: marking a no-show moves an assignment from either `ASSIGNED` or `CONFIRMED` to `NO_SHOW`, terminal, with no further preconditions. The marshal roster lists with pagination and filters on `parade_id`, `route_segment_id`, `marshal_user_id`, and `status`.

### 3.7. Judging and Awards

Scoring begins once an entry stands `APPROVED` or `SUSPENDED`; a judge who tries to open a sheet against an entry in any other status is rejected with `ERR_INVALID_STATE`. Each `Judge` opens at most one sheet per entry — a second sheet for the same pairing is rejected with `ERR_DUPLICATE_SCORE_SHEET` — and the server records the caller as `judge_user_id` from the header. The sheet scores four criteria, `creativity`, `craftsmanship`, `theme`, and `crowd_appeal`, each an integer from 0 to 25, and the system derives `sheet_total` as their sum, a value from 0 to 100. A new sheet is a private working document in `DRAFT`.

Submitting a sheet — an action reserved to the owning judge, with `ERR_FORBIDDEN` for anyone else, and blocked while the parade is frozen — moves it from `DRAFT` to `SUBMITTED` and immediately recomputes the entry's `provisional_score`: the plain mean of `sheet_total` across all of the entry's sheets in `SUBMITTED` or `FINALIZED` status, or null while no such sheet exists. Reopening, also reserved to the owning judge, moves a sheet from `SUBMITTED` back to `DRAFT` for revision and recomputes the provisional score as the sheet leaves the submitted set; reopening is refused once the parade has reached `COMPLETED` (`ERR_INVALID_STATE`).

Final authority over scores is segregated from judging itself: only a `CommitteeAdmin` finalizes a sheet, moving it from `SUBMITTED` to `FINALIZED` while the parade is unfrozen. Each finalization recomputes the entry's `final_score` over `FINALIZED` sheets alone — when at least three sheets are finalized, the single highest and the single lowest `sheet_total` are each dropped once before averaging (a trimmed mean), while with one or two finalized sheets the score is their plain mean, and with none the score stays null. Both score variants round half-up to 2 decimal places. An entry's sheets can be listed with pagination and filtered by `status`.

Awards close the competitive loop. The committee defines each award with an `award_category` of `BEST_FLOAT`, `BEST_BAND`, `BEST_WALKING`, or `GRAND_PRIZE`, and an `eligible_entry_category` naming one of the five entry categories or `ANY`. A new award is `PENDING`, with `winner_entry_id` and `announced_at` both null. Announcing the winner requires the parade to stand in `LINEUP_PUBLISHED` (`ERR_LINEUP_NOT_PUBLISHED` otherwise) and unfrozen, and builds its pool from the parade's entries that are `APPROVED`, whose `assigned_category` equals the award's eligible category — or any category when the award declares `ANY` — and that hold at least one `FINALIZED` sheet. An empty pool is rejected with `ERR_NO_ELIGIBLE_WINNER` (HTTP 422). Otherwise the winner is resolved deterministically: entries are ranked by `final_score`, highest first; ties break toward the entry with more finalized sheets; further ties break toward the alphabetically earlier `org_name`; any remaining tie breaks toward the earlier `created_at`; and entries still tied after that break toward the earliest creation sequence. The announcement records the resolved `winner_entry_id` and stamps `announced_at` from the logical clock. Presentation moves an announced award from `ANNOUNCED` to `PRESENTED` while the parade is unfrozen, and cancellation moves a `PENDING` award to `CANCELLED`; both `PRESENTED` and `CANCELLED` are terminal. Awards can be browsed per parade, or through a filtered cross-parade list keyed on `parade_id`, `winner_entry_id`, or `status`.

### 3.8. Sponsorship and the Announcer Script

Sponsor money underwrites the production, and the announcer's script is how it is repaid. The committee registers a sponsor package with a `sponsor_name`, a `tier` of `GOLD`, `SILVER`, or `BRONZE`, and a `contribution_cents` pledge greater than zero. Packages are born `PLEDGED` with `allocated_seconds` at zero, and activation — moving a package from `PLEDGED` to `ACTIVE`, permitted only while the parade is unfrozen — is what makes a sponsor referenceable by the script. The sponsor book of a parade lists with pagination and a `status` filter.

The script itself is a sequence of items, each created with an `item_type` of `SPONSOR_READ`, `ENTRY_INTRO`, `SAFETY_ANNOUNCEMENT`, or `AWARD_ANNOUNCEMENT`, a `sequence_index` fixing its reading order, and a planned `duration_minutes` greater than zero. Two conditional references apply: a `SPONSOR_READ` item must carry a `sponsor_id` naming an `ACTIVE` sponsor package of the same parade, and an `ENTRY_INTRO` item must carry an `entry_id` naming an entry of the same parade — omitting the required reference is a schema failure (`ERR_VALIDATION`), while pointing it at the wrong target is a state failure (`ERR_INVALID_STATE`). Every item's `duration_seconds` is derived by multiplying its `duration_minutes` by sixty and rounding half-up to a whole second, per item. Totals are then built by summing those already-rounded item values; rounding the summed minutes once instead is forbidden, because the two orders produce different totals. The sponsor-level aggregate `allocated_seconds` sums `duration_seconds` over the package's `SPONSOR_READ` items in `APPROVED` or `LOCKED` status, and the parade-level `sponsor_seconds_allocated` does the same across the whole edition.

Script items carry a small lifecycle of their own. Approving moves an item from `DRAFT` to `APPROVED` — only while the parade is unfrozen — and recomputes both second counters when the item is a `SPONSOR_READ`. Reopening moves an `APPROVED` item back to `DRAFT`, but only before the lineup has been published: once the parade stands in `LINEUP_PUBLISHED` or `COMPLETED`, reopening fails with `ERR_INVALID_STATE`. Cancelling moves an item from `DRAFT` or `APPROVED` to `CANCELLED`, terminal, and likewise recomputes the counters for sponsor reads. Publishing the lineup locks every `APPROVED` item of the parade into `LOCKED`, from which no further edits are possible.

Before the show goes on, the committee finalizes the script — a gate that verifies every `ACTIVE` sponsor package of the parade has accumulated at least its tier minimum of recognized airtime: 120 seconds for `GOLD`, 60 for `SILVER`, and 30 for `BRONZE`, with the boundary inclusive so that exactly the minimum passes. Any shortfall rejects the finalization with `ERR_SPONSOR_MINUTES_UNMET` (HTTP 422); success sets the parade's `script_finalized` flag to true. Script items can be listed per parade with `status` and `item_type` filters, or across parades through a filtered list keyed on `parade_id`, `sponsor_id`, `entry_id`, or `status`.

### 3.9. Publication, Completion, and Cancellation

Three final acts close the parade's own state machine. Locking moves the parade from `PERMIT_GRANTED` to `LOCKED` and demands an `OPERATIONAL` posture — which, per §2.4, means the permit is granted, the dispersal plan approved, and the parade in the right status band. When the permit is not `GRANTED`, the lock attempt is rejected with `ERR_PERMIT_NOT_GRANTED`; other from-state mismatches surface `ERR_INVALID_STATE`.

Publishing the lineup moves the parade from `LOCKED` to `LINEUP_PUBLISHED`. The parade must not be `FROZEN` — a frozen parade is rejected with `ERR_EVENT_FROZEN` — at least one lineup assignment must stand in `TENTATIVE`, `CONFIRMED`, or `CHECKED_IN` status (`ERR_INVALID_STATE` when the running order is empty), the request must carry `expected_parade_version` matching the parade's current `version` under the OCC rule of §2.9, with `ERR_STALE_VERSION` (HTTP 412) on a mismatch, and the parade must stand in `LOCKED` (`ERR_INVALID_STATE` otherwise); these gates run in the order stated, after request-body schema validation of `expected_parade_version`. Publication has a broadcast side effect: every announcer script item of the parade still in `APPROVED` status locks to `LOCKED` in the same write.

Completion moves the parade from `LINEUP_PUBLISHED` to `COMPLETED` once every lineup assignment of the parade has reached a terminal state — `RELEASED`, `PULLED`, or `NO_SHOW` — with `ERR_INVALID_STATE` while any assignment remains live. Completion is also the sponsor reckoning: every `ACTIVE` package whose `allocated_seconds` meets its tier minimum transitions to `FULFILLED`, and every one that falls short transitions to `DEFAULTED`.

Cancellation is available from every non-terminal status — `DRAFT`, `PERMIT_PENDING`, `PERMIT_GRANTED`, `LOCKED`, and `LINEUP_PUBLISHED` alike — and lands the parade in `CANCELLED`, terminal alongside `COMPLETED`. The cancel cascade resolves the whole edition in one write: every entry application in `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, or `SUSPENDED` moves to `WITHDRAWN`; every lineup assignment in `TENTATIVE`, `CONFIRMED`, or `CHECKED_IN` moves to `PULLED`, with each pull firing its own slot-release and script-cancellation side effects exactly as a manual pull would; every `ACTIVE` sponsor package moves to `DEFAULTED`; and the parade's posture recomputes to `FROZEN`.

## 4. Endpoint Definitions

Throughout the API, operations that create a new, distinct resource return `201 Created`, while operations that read, modify, or drive a state transition on an existing resource return `200 OK`. All responses use the envelope of §2.2, and list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parades` | Create a parade edition | CommitteeAdmin |
| GET | `/parades` | List parades with pagination and filters | All six roles |
| GET | `/parades/{id}` | Get one parade incl. computed posture and counters | All six roles |
| POST | `/parades/{id}/submit-permit` | Move DRAFT to PERMIT_PENDING | CommitteeAdmin |
| POST | `/parades/{id}/lock` | Move PERMIT_GRANTED to LOCKED | CommitteeAdmin |
| POST | `/parades/{id}/publish-lineup` | Move LOCKED to LINEUP_PUBLISHED under OCC; locks approved script items | CommitteeAdmin |
| POST | `/parades/{id}/complete` | Move LINEUP_PUBLISHED to COMPLETED; resolves active sponsors | CommitteeAdmin |
| POST | `/parades/{id}/cancel` | Cancel from any non-terminal state with full cascades | CommitteeAdmin |
| POST | `/parades/{id}/route-segments` | Add a route segment | CommitteeAdmin |
| GET | `/parades/{id}/route-segments` | List route segments of a parade | All six roles |
| GET | `/route-segments/{id}` | Get one route segment | CommitteeAdmin, AgencyReviewer, Marshal |
| POST | `/parades/{id}/permit` | Create the parade's permit application | CommitteeAdmin |
| GET | `/parades/{id}/permit` | Fetch the permit of a parade (array of 0-1) | CommitteeAdmin, AgencyReviewer |
| GET | `/permits/{id}` | Get one permit incl. fee variants and endorsement counts | CommitteeAdmin, AgencyReviewer |
| POST | `/permits/{id}/submit` | Move DRAFT to AGENCY_REVIEW; computes the final fee | CommitteeAdmin |
| POST | `/permits/{id}/grant` | Move AGENCY_REVIEW to GRANTED; flips the parade | AgencyReviewer |
| POST | `/permits/{id}/deny` | Move AGENCY_REVIEW to DENIED; freezes the parade | AgencyReviewer |
| POST | `/permits/{id}/revoke` | Move GRANTED to REVOKED; fires the freeze cascade | AgencyReviewer |
| POST | `/permits/{id}/refile` | Move DENIED back to DRAFT; resets fee and submission stamp | CommitteeAdmin |
| POST | `/permits/{id}/endorsements` | Request an agency endorsement (OCC on the permit version) | CommitteeAdmin |
| GET | `/permits/{id}/endorsements` | List endorsements of a permit | CommitteeAdmin, AgencyReviewer |
| GET | `/endorsements/{id}` | Get one endorsement | CommitteeAdmin, AgencyReviewer |
| POST | `/endorsements/{id}/endorse` | Move PENDING to ENDORSED | AgencyReviewer |
| POST | `/endorsements/{id}/reject` | Move PENDING to REJECTED | AgencyReviewer |
| POST | `/parades/{id}/entries` | Submit an entry application | Entrant |
| GET | `/parades/{id}/entries` | List entries of a parade | CommitteeAdmin, AgencyReviewer, Judge, Entrant |
| GET | `/entries/{id}` | Get one entry incl. fee and scores | CommitteeAdmin, AgencyReviewer, Judge, Entrant |
| POST | `/entries/{id}/start-review` | Move SUBMITTED to UNDER_REVIEW | CommitteeAdmin |
| POST | `/entries/{id}/approve` | Move UNDER_REVIEW to APPROVED with category assignment | CommitteeAdmin |
| POST | `/entries/{id}/reject` | Move UNDER_REVIEW to REJECTED | CommitteeAdmin |
| POST | `/entries/{id}/request-revision` | Move UNDER_REVIEW to REVISION_REQUESTED | CommitteeAdmin |
| POST | `/entries/{id}/resubmit` | Move REVISION_REQUESTED to SUBMITTED by the owning entrant | Entrant |
| POST | `/entries/{id}/withdraw` | Move SUBMITTED or APPROVED to WITHDRAWN by the owning entrant | Entrant |
| POST | `/entries/{id}/pay-fee` | Mark the entry fee paid by the owning entrant | Entrant |
| POST | `/entries/{id}/floats` | Register a float for an approved FLOAT or VEHICLE entry | Entrant |
| GET | `/entries/{id}/floats` | List floats of an entry | CommitteeAdmin, SafetyInspector, Entrant |
| GET | `/floats/{id}` | Get one float | CommitteeAdmin, SafetyInspector, Entrant |
| POST | `/floats/{id}/inspections` | Schedule an inspection under segregation of duties | SafetyInspector |
| GET | `/floats/{id}/inspections` | List inspections of a float | CommitteeAdmin, SafetyInspector, Entrant |
| GET | `/inspections/{id}` | Get one inspection | CommitteeAdmin, SafetyInspector |
| POST | `/inspections/{id}/pass` | Move SCHEDULED to PASSED; certifies the float | SafetyInspector |
| POST | `/inspections/{id}/fail` | Move SCHEDULED to FAILED; fires the suspension cascade | SafetyInspector |
| POST | `/inspections/{id}/cancel` | Move SCHEDULED to CANCELLED | SafetyInspector |
| POST | `/parades/{id}/staging-areas` | Create a staging area | CommitteeAdmin |
| GET | `/parades/{id}/staging-areas` | List staging areas of a parade | CommitteeAdmin, AgencyReviewer, Entrant |
| GET | `/staging-areas/{id}` | Get one staging area incl. reserved slots | CommitteeAdmin, AgencyReviewer, Entrant |
| POST | `/parades/{id}/lineup-assignments` | Create a TENTATIVE lineup assignment | CommitteeAdmin |
| GET | `/lineup-assignments` | Filtered list of lineup assignments | CommitteeAdmin, AgencyReviewer, Entrant |
| GET | `/lineup-assignments/{id}` | Get one lineup assignment | CommitteeAdmin, AgencyReviewer, Entrant |
| POST | `/lineup-assignments/{id}/confirm` | Move TENTATIVE to CONFIRMED under the full gate chain | CommitteeAdmin |
| POST | `/lineup-assignments/{id}/check-in` | Move CONFIRMED to CHECKED_IN within the arrival window | CommitteeAdmin |
| POST | `/lineup-assignments/{id}/release` | Move CHECKED_IN to RELEASED; frees the slot | CommitteeAdmin |
| POST | `/lineup-assignments/{id}/no-show` | Move CONFIRMED to NO_SHOW after departure | CommitteeAdmin |
| POST | `/lineup-assignments/{id}/pull` | Move TENTATIVE or CONFIRMED to PULLED | CommitteeAdmin |
| POST | `/parades/{id}/marshal-assignments` | Assign a marshal to a route-segment shift | CommitteeAdmin |
| GET | `/marshal-assignments` | Filtered list of marshal assignments | CommitteeAdmin, AgencyReviewer, Marshal |
| GET | `/marshal-assignments/{id}` | Get one marshal assignment | CommitteeAdmin, AgencyReviewer, Marshal |
| POST | `/marshal-assignments/{id}/confirm` | Move ASSIGNED to CONFIRMED by the named marshal | Marshal |
| POST | `/marshal-assignments/{id}/complete` | Move CONFIRMED to COMPLETED at or after shift end | Marshal |
| POST | `/marshal-assignments/{id}/no-show` | Move ASSIGNED or CONFIRMED to NO_SHOW | CommitteeAdmin |
| POST | `/entries/{id}/score-sheets` | Open a DRAFT score sheet for an entry | Judge |
| GET | `/entries/{id}/score-sheets` | List score sheets of an entry | CommitteeAdmin, Judge |
| GET | `/score-sheets/{id}` | Get one score sheet | CommitteeAdmin, Judge |
| POST | `/score-sheets/{id}/submit` | Move DRAFT to SUBMITTED by the owning judge | Judge |
| POST | `/score-sheets/{id}/reopen` | Move SUBMITTED back to DRAFT by the owning judge | Judge |
| POST | `/score-sheets/{id}/finalize` | Move SUBMITTED to FINALIZED by the committee | CommitteeAdmin |
| POST | `/parades/{id}/awards` | Define an award and its eligible category | CommitteeAdmin |
| GET | `/parades/{id}/awards` | List awards of a parade | CommitteeAdmin, AgencyReviewer, Judge, Entrant |
| GET | `/awards` | Filtered cross-parade list of awards | CommitteeAdmin, AgencyReviewer, Judge, Entrant |
| GET | `/awards/{id}` | Get one award | CommitteeAdmin, AgencyReviewer, Judge, Entrant |
| POST | `/awards/{id}/announce` | Move PENDING to ANNOUNCED; resolves the winner | CommitteeAdmin |
| POST | `/awards/{id}/present` | Move ANNOUNCED to PRESENTED | CommitteeAdmin |
| POST | `/awards/{id}/cancel` | Move PENDING to CANCELLED | CommitteeAdmin |
| POST | `/parades/{id}/sponsors` | Register a sponsor package | CommitteeAdmin |
| GET | `/parades/{id}/sponsors` | List sponsors of a parade | CommitteeAdmin, AgencyReviewer |
| GET | `/sponsors/{id}` | Get one sponsor incl. allocated seconds | CommitteeAdmin, AgencyReviewer |
| POST | `/sponsors/{id}/activate` | Move PLEDGED to ACTIVE | CommitteeAdmin |
| POST | `/parades/{id}/script-items` | Add an announcer script item | CommitteeAdmin |
| GET | `/parades/{id}/script-items` | List script items of a parade | CommitteeAdmin, AgencyReviewer |
| GET | `/script-items` | Filtered cross-parade list of script items | CommitteeAdmin, AgencyReviewer |
| GET | `/script-items/{id}` | Get one script item | CommitteeAdmin, AgencyReviewer |
| POST | `/script-items/{id}/approve` | Move DRAFT to APPROVED; recomputes airtime counters | CommitteeAdmin |
| POST | `/script-items/{id}/reopen` | Move APPROVED back to DRAFT before publication | CommitteeAdmin |
| POST | `/script-items/{id}/cancel` | Move DRAFT or APPROVED to CANCELLED | CommitteeAdmin |
| POST | `/parades/{id}/finalize-script` | Verify sponsor tier minimums; finalize the script | CommitteeAdmin |
| POST | `/parades/{id}/dispersal-plan` | Create the parade's dispersal plan | CommitteeAdmin |
| GET | `/parades/{id}/dispersal-plan` | Fetch the dispersal plan of a parade (array of 0-1) | CommitteeAdmin, AgencyReviewer |
| GET | `/dispersal-plans/{id}` | Get one dispersal plan | CommitteeAdmin, AgencyReviewer |
| POST | `/dispersal-plans/{id}/submit` | Move DRAFT to SUBMITTED under the lane-width gate | CommitteeAdmin |
| POST | `/dispersal-plans/{id}/approve` | Move SUBMITTED to APPROVED; recomputes posture | AgencyReviewer |
| POST | `/dispersal-plans/{id}/reject` | Move SUBMITTED to REJECTED; recomputes posture | AgencyReviewer |
| POST | `/dispersal-plans/{id}/revise` | Move REJECTED back to DRAFT | CommitteeAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CommitteeAdmin |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_PARADE_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_ENDORSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_FLOAT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_STAGING_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_SEGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LINEUP_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MARSHAL_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SCORE_SHEET_NOT_FOUND` | 404 Not Found |
| `ERR_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSOR_NOT_FOUND` | 404 Not Found |
| `ERR_SCRIPT_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_DISPERSAL_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EVENT_FROZEN` | 409 Conflict |
| `ERR_ENTRY_NOT_APPROVED` | 409 Conflict |
| `ERR_PERMIT_NOT_GRANTED` | 409 Conflict |
| `ERR_LINEUP_NOT_PUBLISHED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PERMIT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PLAN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_AGENCY_ENDORSEMENT` | 409 Conflict |
| `ERR_DUPLICATE_SCORE_SHEET` | 409 Conflict |
| `ERR_LINEUP_POSITION_TAKEN` | 409 Conflict |
| `ERR_CATEGORY_WITHOUT_FLOAT` | 422 Unprocessable Entity |
| `ERR_STAGING_CAPACITY_FULL` | 422 Unprocessable Entity |
| `ERR_WINDOW_OUTSIDE_STAGING_HOURS` | 422 Unprocessable Entity |
| `ERR_FLOAT_UNCERTIFIED` | 422 Unprocessable Entity |
| `ERR_REINSPECTION_SOD` | 422 Unprocessable Entity |
| `ERR_EMERGENCY_LANE_TOO_NARROW` | 422 Unprocessable Entity |
| `ERR_STAGING_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MARSHAL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ENTRY_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_CHECKIN_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_ENTRY_FEE_OUTSTANDING` | 402 Payment Required |
| `ERR_SPONSOR_MINUTES_UNMET` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_WINNER` | 422 Unprocessable Entity |

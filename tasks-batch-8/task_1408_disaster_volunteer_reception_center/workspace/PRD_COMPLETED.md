# Disaster Volunteer Reception Center API — Product Requirements Document

## 1. Introduction

When a county activates a Volunteer Reception Center after a flood, wildfire, or comparable disaster, hundreds of spontaneous, unaffiliated volunteers arrive with unknown skills, unverified credentials, and no organizational sponsor. This document specifies the API that runs such a center end to end: intake and registration of walk-up volunteers, verification of claimed skill credentials and adjudication of background checks, safety briefings, liability waivers, and protective-equipment issuance, matching of ready volunteers to the support requests filed by requesting agencies, transportation and shift scheduling to work sites, hour tracking that supports federal cost-share documentation, and finally demobilization, risk management, and volunteer recognition.

Two concerns shape every rule that follows. The first is life-safety: gate documents, hazard-tiered credentialing, and a quantitative risk model decide who may set foot on which site, while a computed operational posture can restrict — or entirely freeze — matching activity center-wide when conditions deteriorate. The second is auditability: segregation-of-duties rules separate the operator who registers a volunteer from the one who clears their background check, the worker who submits hours from the supervisor who verifies them, and the reporter of a safety incident from its adjudicator, so the cost-share ledger the county submits for reimbursement can withstand a federal audit. All resources are exposed under the `/vrc` URL prefix.

## 2. Global Specifications & System-Wide Principles

This section fixes the structural contracts and system-wide rules that apply uniformly to every endpoint; §3 then walks the business workflows that rely on them.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or whose `X-User-Role` is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Each endpoint declares the roles permitted to call it; an authenticated caller whose role is not on that list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Read endpoints are open to every authenticated role.

The system recognizes eight roles. `VRCManager` is the county reception-center manager and owns the incident lifecycle, demobilization, and the logical clock. `IntakeCoordinator` is front-desk intake staff: registering volunteers, recording briefings and waivers, proposing and confirming assignments, and running auto-match. `VettingOfficer` is the credentialing specialist who verifies skill credentials and adjudicates background checks, deliberately segregated from intake. `LogisticsCoordinator` owns site shifts, transport trips, seat bookings, and PPE stock. `SiteSupervisor` works the sites: checking volunteers in and out, boarding vehicles, and verifying or disputing hours. `RiskOfficer` adjudicates risk reports and suspends, reinstates, or recalls volunteers. `AgencyCoordinator` is the requesting-agency liaison who files and manages support requests. `Volunteer` is the spontaneous unaffiliated volunteer who self-registers, accepts or declines assignments, and reports their own hours.

For seven of these roles — `VRCManager`, `IntakeCoordinator`, `VettingOfficer`, `LogisticsCoordinator`, `SiteSupervisor`, `RiskOfficer`, and `AgencyCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example as `registered_by_user_id` on a volunteer, `verified_by_user_id` on a credential, `adjudicated_by_user_id` on a background check or a risk report, `submitted_by_user_id` on an hour entry, or `reporter_user_id` on a risk report) but never compares it to any entity's `id`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting volunteer record, and ownership checks on any operation that targets a specific volunteer or one of their assignments compare the target's volunteer reference to `X-User-ID` (see §2.8).

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
- A request to an unknown path, or to a known path with an unsupported method, is answered in this same envelope with `ERR_RESOURCE_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination and List Filtering

Endpoints that return lists paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100; a supplied value outside those bounds is clamped to the nearest bound, and a non-numeric value falls back to the default. The `offset` parameter sets the number of items skipped and defaults to 0, with a negative or non-numeric value likewise falling back to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with records sharing a `created_at` instant ordered by creation (insertion) sequence — an `id` is never consulted. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is smaller than `total_count`.

Collections also accept optional equality filters that narrow the result set. Most collections take `status`; support requests additionally take `criticality`; shifts take `hazard_level` and `site_name`; clearances take `clearance_type`; risk reports take `severity`; and the reverse-channel collections accept the foreign-key filters `incident_id`, `volunteer_id`, `support_request_id`, `site_shift_id`, `trip_id`, `assignment_id`, and `vehicle_id` as listed per endpoint in §4. Filters match by exact equality; a filter value that matches nothing simply yields an empty page, and unrecognized query parameters are ignored.

### 2.4. The Logical Clock

All time in the system comes from a single logical clock; the server never falls back to wall-clock time. Before any operator intervention, the logical clock reads exactly 2026-08-01T00:00:00Z. A `VRCManager`-only test-driving capability sets the clock to a supplied `to_iso8601` instant (ISO 8601 UTC) — any valid instant is accepted, including one earlier than the current reading — and answers with the resulting `current_utc`. Everywhere this document says "now", it means this logical clock.

Setting the clock does more than answer time reads: it triggers an expiry sweep and its consequences. Every `VERIFIED` skill credential whose `expires_at` lies at or before the new instant flips to `EXPIRED`; every `CLEARED` background check whose `expires_at` lies at or before the new instant flips to `EXPIRED`; every `ACTIVE` safety-briefing clearance whose `valid_until` lies at or before the new instant flips to `EXPIRED` (liability waivers never expire). Volunteers whose cleared standing depended on the expired records regress automatically as described in §3.2, and every incident's operational posture is re-derived per §2.7 — because the 24-hour substantiation window moves with the clock, a posture can thaw on a clock-set even when no record expired.

### 2.5. Common Resource Properties

Every resource in the system carries four system-managed fields. `id` is a server-minted UUID with no type prefix, rendered in the canonical 36-character hyphenated form — five groups of 8, 4, 4, 4, and 12 lowercase hexadecimal digits separated by hyphens (for example, `3f6b8f2e-4c1a-4f7b-9c2d-1a2b3c4d5e6f`); it serves identity only and is never used for business decisions — in particular, no selection, ranking, or tie-break rule may ever consult an `id`. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits marking creation and last modification. `version` is an integer starting at 1 at creation and incrementing by exactly 1 on every mutation of the resource, including mutations produced by cascades and derived-field recomputes, with `updated_at` refreshed alongside; within a single API call a resource's `version` rises by at most 1, however many mutations — direct, cascaded, or derived — touch it during that call.

### 2.6. Derived Counters and Automatic State Reconciliation

Several fields are server-maintained derivations that clients never write directly: a support request's `filled_count` (its assignments in `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`), a shift's `rostered_count` (its assignments in those same states), a trip's `booked_seats` (its seat bookings in `BOOKED` or `BOARDED`), a volunteer's `committed_hours` (the summed `duration_hours` of the shifts behind their `CONFIRMED` or `CHECKED_IN` assignments, held at two decimal places) and `verified_hours_total`, an incident's cost-share fields, and a volunteer's risk scores. Each such recompute is a mutation of the owning resource and therefore bumps its `version` and `updated_at` like any other write.

Derived state moves in both directions without any client call on the affected resource. A shift whose `rostered_count` reaches `capacity` locks itself, moving from `OPEN_FOR_ROSTER` to `LOCKED`, and reopens the moment the roster falls back below capacity. A support request promotes from `OPEN` or `MATCHING` to `FILLED` the moment `filled_count` reaches `headcount_needed`, slides from `OPEN` to `MATCHING` when proposal activity leaves it at least one non-terminal assignment, regresses from `MATCHING` to `OPEN` when its `filled_count` is zero and no `PROPOSED` or `ACCEPTED` assignments remain, and falls back from `FILLED` to `MATCHING` when fills are lost below the needed headcount. A volunteer flips from `READY` to `DEPLOYED` on their first check-in and back to `READY` when their last checked-in assignment closes. The incident's `operational_posture` is likewise re-derived on every relevant event: risk-report substantiation, support-request publication, fill-level changes, request cancellation and completion, shift roster openings and cancellations, and every clock-set sweep.

### 2.7. Incident Lifecycle Gating and Operational Posture

An incident's `lifecycle_status` runs from `ACTIVATION` to `ACTIVE` to `DEMOBILIZATION` to `CLOSED`. Writes that create or modify operational data require the incident to be `ACTIVE`; attempts while it is in `ACTIVATION` or `CLOSED` fail with `ERR_INCIDENT_NOT_ACTIVE` (HTTP 409). During `DEMOBILIZATION` the center winds down: only volunteer demobilization, hour-entry creation, verification, dispute, and resubmission, support-request completion and cancellation, PPE close-out, risk-report substantiation and dismissal, and trip arrival remain permitted. Any other incident-scoped write — volunteer registration, credential claims, request creation or publication, shift creation or roster opening, assignment creation, auto-match, check-in, trip creation or departure, seat booking, or PPE issuance — is rejected with `ERR_INCIDENT_DEMOBILIZING` (HTTP 409). A `CLOSED` incident rejects every write.

Orthogonal to the lifecycle, the incident's `operational_posture` is a computed gate with three values. It is `FROZEN` whenever any volunteer of the incident has a `SUBSTANTIATED` risk report of `CRITICAL` severity whose adjudication instant is later than the instant exactly 24 hours before now. Otherwise it is `RESTRICTED` when at least 3 of the incident's `CRITICAL` support requests stand unfilled in `OPEN` or `MATCHING`, or when any `RED`-hazard shift of the incident is `OPEN_FOR_ROSTER` or `LOCKED`. Otherwise it is `OPEN`. The frozen condition is evaluated strictly before the restricted condition, so a recent critical substantiation always wins over the restricted inputs, and posture is only ever evaluated while the lifecycle is `ACTIVE`.

Posture blocks specific operations. While `FROZEN`, assignment creation and confirmation, auto-match, check-in, and trip departure are rejected with `ERR_POSTURE_FROZEN` (HTTP 409). While `RESTRICTED`, auto-match alone is rejected with `ERR_POSTURE_RESTRICTED` (HTTP 409). At final close-out the posture is frozen at its final value and the incident becomes read-only.

### 2.8. Segregation of Duties and Volunteer Ownership

Three adjudication pairs are segregated by design. The operator who clears or flags a volunteer's background check must not be the operator whose identifier was recorded in that volunteer's `registered_by_user_id`; a violation is rejected with `ERR_SOD_CLEARANCE_VIOLATION` (HTTP 403). The operator who verifies or disputes an hour entry must not be the one recorded as its `submitted_by_user_id`; a violation is `ERR_SOD_HOUR_VERIFICATION` (HTTP 403) — and because resubmission never rewrites `submitted_by_user_id`, the original submitter remains the segregation target for the life of the entry. The operator who substantiates or dismisses a risk report must not be its `reporter_user_id`; a violation is `ERR_SOD_RISK_ADJUDICATION` (HTTP 403).

When the caller's role is `Volunteer`, ownership rules apply: accepting or declining an assignment, resubmitting an hour entry, withdrawing from the center, editing the volunteer profile through the OCC-guarded edit of §2.9, claiming a credential, and creating an hour entry each require `X-User-ID` to equal the subject volunteer's `id` — for assignment actions and hour entries, the assignment's `volunteer_id`. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

### 2.9. Optimistic Concurrency Control

Exactly two writes are guarded by optimistic concurrency control, and for each the version field is a non-optional input. A volunteer profile edit must carry `expected_volunteer_version` matching the volunteer's current `version`; a support-request edit must carry `expected_support_request_version` matching the request's current `version`. If the supplied value does not match — because another writer has mutated the record since the client last read it, whether by a profile edit, a status change, or a cascaded recompute such as `filled_count` — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed. A successful edit call increments the resource's `version` even when the payload changes no editable field. Endpoints other than these two do not take a version field.

### 2.10. Money, Hours, and Rounding Precision

All monetary amounts are integer cents; fractional cents exist nowhere in the system. Durations and hour totals are numbers with exactly two decimal places, rounded half-up. An hour entry's cost-share value is rounded half-up to whole cents once, at the moment the entry is created, and again on each resubmission — always before any summation takes place; incident-level rollups then sum whole cents only. The incident's three reimbursement shares are computed in a pinned order, federal first, state second, and local last by subtraction, and the local share is never independently rounded (§3.5). Timestamp comparisons throughout the system are instant-exact.

### 2.11. Validation Pipeline Ordering and Resource Resolution

Every request is validated against an ordered pipeline, and a request that would fail several checks reports the earliest failing stage. The stages, in order, are:

1. Header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Existence of every referenced resource: path identifiers are validated left to right, then body references in their declared input order, with the first miss yielding `ERR_RESOURCE_NOT_FOUND` (HTTP 404). For nested paths this means the parent is resolved before the child, so a request naming a missing incident never reports on a child beneath it.
4. Request-body shape: required fields present, required strings non-empty, types correct (a boolean never satisfies an integer field), enum members valid, `quantity` and `headcount_needed` at least 1, hours positive, at most 16, and a multiple of 0.25, end instants strictly after start instants, the PPE stock object carrying exactly its five keys — any violation is `ERR_INVALID_REQUEST` (HTTP 400), as is a headcount edit below the current `filled_count`. A body that parses as JSON but is not an object is likewise `ERR_INVALID_REQUEST`, while an absent or unparseable body is treated as an empty object. On endpoints that declare a request payload, any field outside the declared set is an unknown payload field and fails as `ERR_INVALID_REQUEST`; action endpoints that declare no payload ignore extra body fields.
5. The incident lifecycle gate of §2.7 (`ERR_INCIDENT_NOT_ACTIVE` or `ERR_INCIDENT_DEMOBILIZING`).
6. The posture gate of §2.7 (`ERR_POSTURE_FROZEN` or `ERR_POSTURE_RESTRICTED`).
7. Resource state preconditions for the requested transition or creation (`ERR_INVALID_STATE`), including the OCC version match of §2.9 (`ERR_STALE_VERSION`).
8. Segregation-of-duties and ownership checks (`ERR_SOD_CLEARANCE_VIOLATION`, `ERR_SOD_HOUR_VERIFICATION`, `ERR_SOD_RISK_ADJUDICATION`, `ERR_NOT_RESOURCE_OWNER`).
9. Assignment safety checks: readiness, skill match, credential class, hazard gating, and background-check freshness (§3.3).
10. Gate-document checks: briefing currency, waiver presence, and PPE issuance (§3.4).
11. Referential coherence across linked resources (§3.3 and §3.4), including the hour-entry rules tying `work_date` to the shift's start date and capping `hours` at the shift's `duration_hours` (§3.5).
12. Temporal interval rules: double-booking, vehicle turnaround, the check-in window, no-show timing, and roster-opening timing (§3.3 and §3.4).
13. Uniqueness constraints: one pending background check per volunteer, one active clearance per volunteer and type, one live hour entry per assignment and work date, one live seat booking per assignment and trip.
14. Capacity and quota rules: shift roster, vehicle seats, PPE stock, and the weekly committed-hour cap.
15. For auto-match only, the requirement that at least one placement be produced (`ERR_NO_ELIGIBLE_PLACEMENTS`).

## 3. Business Logic & Workflows

### 3.1. Standing Up and Closing Down an Incident

A `VRCManager` opens a new incident by supplying its human-readable `name` (for example, "Riverton Flood 2026") and the starting `ppe_stock`, a map whose keys are exactly the five item types `GLOVES`, `MASK`, `HARD_HAT`, `VEST`, and `GOGGLES`, each mapped to a non-negative integer on-hand count. The incident begins in `ACTIVATION` with `operational_posture` `OPEN` and every cost-share field — `provisional_cost_share_cents`, `verified_cost_share_cents`, `federal_share_cents`, `state_share_cents`, and `local_share_cents` — at zero. Activation, again by a `VRCManager` and only from `ACTIVATION` (otherwise `ERR_INVALID_STATE`), moves `lifecycle_status` to `ACTIVE`, stamps `activated_at` from the logical clock, and re-derives posture; intake and matching writes are impossible before this step.

When operations wind down, the manager begins demobilization — only from `ACTIVE` (otherwise `ERR_INVALID_STATE`) and only while no assignment of the incident remains `CHECKED_IN`, since a checked-in volunteer still on a site blocks the move with `ERR_OPEN_ASSIGNMENTS`. The transition stamps `demobilized_at` and invokes the wind-down write restrictions of §2.7. Final closure runs only from `DEMOBILIZATION` and is the strictest gate in the system: every volunteer of the incident must be `DEMOBILIZED`, `WITHDRAWN`, or `REJECTED`; every support request `COMPLETED` or `CANCELLED`; every hour entry `VERIFIED` or `REJECTED_FINAL`; every PPE issuance `RETURNED`, `DAMAGED`, or `LOST`; every trip `ARRIVED` or `CANCELLED`; and every site shift `CANCELLED`. Any unmet condition rejects the closure with `ERR_INCIDENT_CLOSING_BLOCKED`. A successful closure stamps `closed_at`, freezes `operational_posture` at its final value, and renders the incident permanently read-only.

### 3.2. Intake, Credentialing, and the Readiness Pipeline

Registration creates a volunteer in `REGISTERED` status from `incident_id`, `full_name`, `phone`, `email`, and `home_locality` — the city or town of residence, which drives local-versus-spontaneous reporting. An `IntakeCoordinator` registers walk-ups at the front desk; a `Volunteer` caller self-registers. The server records `registered_by_user_id` as the creating call's `X-User-ID`, or, for self-registration, the newly minted volunteer's own `id`, and this value later anchors the clearance segregation rule of §2.8. While the volunteer stands in `REGISTERED`, `VETTING`, `CLEARED`, or `READY`, their profile — `phone`, `email`, and `home_locality` — can be corrected through the OCC-guarded edit of §2.9; edits attempted from `DEPLOYED`, `SUSPENDED`, `DEMOBILIZED`, `WITHDRAWN`, or `REJECTED` are refused with `ERR_INVALID_STATE`.

Credentials come next. A claim names the `volunteer_id`, a `skill_code` drawn from `GENERAL_LABOR`, `CHAINSAW`, `MEDICAL`, `CDL`, `SHELTER_OPS`, and `TRANSLATION`, a `credential_class` of `STANDARD` or `ADVANCED`, a required `expires_at` marking the credential's expiry, and optional `evidence_notes` such as a license number or issuer; a `Volunteer` caller claims on their own record. The claim enters `CLAIMED`. Submitting the volunteer for vetting, an `IntakeCoordinator` action, requires an `ACTIVE` incident and at least one credential record of any status — with zero claimed credentials the call fails with `ERR_NO_CREDENTIALS_CLAIMED` — and moves the volunteer from `REGISTERED` to `VETTING`.

A `VettingOfficer` then opens a background check, permitted only while the volunteer is `VETTING` or `SUSPENDED` and with at most one `REQUESTED` check per volunteer at a time; a second concurrent request fails with `ERR_CHECK_ALREADY_PENDING`. Clearing a `REQUESTED` check stamps `adjudicated_by_user_id` and `adjudicated_at` and sets the check's `expires_at` to exactly 720 hours (thirty days) after adjudication; flagging it stamps the same adjudication fields without an expiry. Both adjudications honor the registrar segregation rule of §2.8. Two automatic rules then govern the volunteer's standing: promotion from `VETTING` to `CLEARED` occurs as soon as the volunteer holds both a `CLEARED` background check whose `expires_at` is still in the future and at least one `VERIFIED` credential; regression from `CLEARED` back to `VETTING` occurs automatically the moment that combination stops holding — for instance when the clock sweep expires the last cleared check or the last verified credential. Flagging cuts sharper: a `VETTING` volunteer is rejected outright into terminal `REJECTED`, while a `CLEARED`, `READY`, or `DEPLOYED` volunteer is suspended with the full suspension cascade of §3.6, and the incident's posture is re-derived. Flagging the pending check of a volunteer in any other status — notably one already `SUSPENDED` — changes no volunteer status, and only the posture re-derivation runs.

Credential adjudication mirrors this shape. Verification by a `VettingOfficer` moves a `CLAIMED` credential to `VERIFIED`, stamps `verified_by_user_id` and `verified_at`, and re-evaluates the volunteer's promotion rule; the same verification also renews an `EXPIRED` credential back to `VERIFIED`, which is the credential-renewal loop; renewal changes only the status and the verification stamps, leaving the credential's `expires_at` untouched. Rejection moves a `CLAIMED` or `EXPIRED` credential to terminal `REJECTED`. Neither action is permitted once the parent volunteer is `WITHDRAWN`, `REJECTED`, or `DEMOBILIZED`; the attempt fails with `ERR_INVALID_STATE`. Independently, the clock sweep of §2.4 expires `VERIFIED` credentials whose `expires_at` has been reached.

Two gate documents complete readiness. Recording a clearance takes a `volunteer_id` and a `clearance_type` — `SAFETY_BRIEFING` or `LIABILITY_WAIVER` — and creates an `ACTIVE` clearance stamped with `completed_at` at the logical now; a clearance may be recorded for a volunteer in any status. A briefing remains valid strictly before its `valid_until`, set 72 hours after completion, and is expired at or past that instant; a waiver's `valid_until` is null because it never expires. Only one `ACTIVE` clearance per type per volunteer may exist, and a duplicate attempt fails with `ERR_CLEARANCE_ALREADY_ACTIVE`. Marking a volunteer ready, an `IntakeCoordinator` action from `CLEARED`, requires all four prerequisites to hold at once: an `ACTIVE` briefing whose `valid_until` is still in the future, an `ACTIVE` waiver, a `CLEARED` background check whose `expires_at` is still in the future, and at least one `VERIFIED` credential. Any missing item fails the call with `ERR_READINESS_INCOMPLETE`, whose message names each missing item; success moves the volunteer from `CLEARED` to `READY`.

### 3.3. Support Requests, Site Shifts, and Assignment Matching

Work enters the system when an `AgencyCoordinator` files a support request with `incident_id`, the free-form `requesting_agency`, the `site_name` where the work happens, the `required_skill`, a `min_credential_class`, a `headcount_needed` of at least 1, a `criticality` of `STANDARD` or `CRITICAL`, and an acceptance window from `window_start` to `window_end`, the end strictly after the start. The request is born `DRAFT` with `filled_count` zero. While `DRAFT` or `OPEN` — and only then, otherwise `ERR_INVALID_STATE` — the coordinator may still edit `headcount_needed`, `window_start`, `window_end`, `criticality`, or `min_credential_class` through the OCC-guarded edit of §2.9, except that `headcount_needed` may never be lowered below the current `filled_count`, which fails with `ERR_INVALID_REQUEST`; the rule that the window end lie strictly after its start is re-validated against the merged window the edit would produce. Publishing moves the request from `DRAFT` to `OPEN` under an `ACTIVE` incident and re-derives posture; `CRITICAL` requests standing in `OPEN` or `MATCHING` are exactly the unfilled-critical input to the posture rule of §2.7.

Logistics defines where and when work occurs by scheduling site shifts with `incident_id`, a `site_name` matched case-sensitively against the request's `site_name`, a `hazard_level` of `GREEN`, `AMBER`, or `RED`, `start_at` and `end_at`, and a `capacity` of at least 1. The server derives `duration_hours` as the window's length in hours at exactly two decimal places, rounded half-up; the window must end strictly after it begins, and the rounded `duration_hours` must be at least 0.25 — the minimum is evaluated against the rounded value. A new shift is `SCHEDULED` with `rostered_count` zero, and opening the roster — permitted only before `end_at`, at or after which the call fails with `ERR_SHIFT_WINDOW_PASSED` — moves it to `OPEN_FOR_ROSTER` and re-derives posture. From there the shift locks and reopens automatically per §2.6, and `RED` shifts sitting in `OPEN_FOR_ROSTER` or `LOCKED` feed the posture rule. Cancelling a shift, a `LogisticsCoordinator` action possible from `SCHEDULED`, `OPEN_FOR_ROSTER`, or `LOCKED` (otherwise `ERR_INVALID_STATE`), releases everything built on it in an exact order: first, each of its assignments in `PROPOSED`, `ACCEPTED`, or `CONFIRMED` is cancelled and each `CHECKED_IN` assignment is recalled, releasing committed hours and recomputing `filled_count` and `rostered_count` with the usual regressions; second, every `SCHEDULED` trip ferrying to that shift is cancelled, while `DEPARTED` trips run on unaffected; third, every `BOOKED` or `BOARDED` seat booking on those trips is cancelled with each trip's `booked_seats` recomputed; fourth, the incident's posture is re-derived. The shift's own passage to `CANCELLED` is stamped only after this cascade completes, so the fourth step's posture re-derivation still observes the shift's pre-cancellation status.

With a request open and a shift rostering, an `IntakeCoordinator` proposes an assignment from a `volunteer_id`, a `support_request_id`, and a `site_shift_id`. Proposal runs the validation pipeline of §2.11. The request must stand in `OPEN` or `MATCHING` — any other status fails with `ERR_INVALID_STATE` — while the proposal itself imposes no shift-state precondition: shift state is enforced only at confirmation. A shift or volunteer belonging to a different incident than the request fails with `ERR_SITE_WINDOW_MISMATCH`. The volunteer must be `READY` (`ERR_VOLUNTEER_NOT_READY`); must hold a `VERIFIED` credential whose `skill_code` equals the request's `required_skill` (`ERR_SKILL_MISMATCH`) at a class meeting the `min_credential_class`, where `ADVANCED` satisfies a `STANDARD` minimum (`ERR_CREDENTIAL_CLASS_INSUFFICIENT`); a `RED` shift demands an `ADVANCED` qualifying credential (`ERR_HAZARD_CREDENTIAL_REQUIRED`); and a `CLEARED` background check whose `expires_at` remains in the future must exist (`ERR_BACKGROUND_CHECK_LAPSED`). The shift's `site_name` must equal the request's exactly, and the shift window must sit entirely inside the request window — starting no earlier than `window_start` and ending no later than `window_end` — or the proposal fails with `ERR_SITE_WINDOW_MISMATCH`. Finally, the candidate shift must not collide with the volunteer's existing commitments: each of the volunteer's `CONFIRMED` or `CHECKED_IN` assignments occupies the half-open interval from its shift's `start_at` up to but not including its `end_at`, and a candidate conflicts — `ERR_DOUBLE_BOOKED_SHIFT` — whenever its start falls strictly before an occupied interval's end while that interval's start falls strictly before the candidate's end. A shift starting exactly at another's end is merely adjacent, and adjacency is legal. A successful proposal is born `PROPOSED` with `origin` `MANUAL` and its `incident_id` copied from the request; the first non-terminal assignment on an `OPEN` request nudges it to `MATCHING`, and posture is re-derived.

The volunteer then answers: accepting moves `PROPOSED` to `ACCEPTED`, and declining moves it to terminal `DECLINED`, which can empty a `MATCHING` request back to `OPEN` when no fills and no `PROPOSED` or `ACCEPTED` assignments remain; both actions are ownership-checked per §2.8. Confirmation by an `IntakeCoordinator` is the point where capacity is committed. It requires the assignment `ACCEPTED`, the posture not `FROZEN`, the shift in `OPEN_FOR_ROSTER` — a `LOCKED` shift fails with `ERR_SHIFT_CAPACITY_REACHED`, a `SCHEDULED` or `CANCELLED` shift with `ERR_INVALID_STATE` — with `rostered_count` still below `capacity`, a full re-run of the safety checks above (readiness, skill match, class minimum, hazard gating, and background-check freshness), a re-run of the double-booking check against the volunteer's other `CONFIRMED` and `CHECKED_IN` assignments, and the weekly cap: the volunteer's `committed_hours` plus the shift's `duration_hours` must not exceed 40.00 hours, with a projection of exactly 40.00 allowed and anything strictly above rejected with `ERR_WEEKLY_HOUR_CAP`; these preconditions are evaluated in the order listed here, which places the shift-state and roster-capacity checks ahead of the safety re-run for this endpoint. Confirming adds the shift's `duration_hours` to the volunteer's `committed_hours`, increments the shift's `rostered_count` (locking it the moment the roster reaches `capacity`), increments the request's `filled_count` (promoting the request to `FILLED` the moment it reaches `headcount_needed`, or from `OPEN` to `MATCHING` below it), and re-derives posture. The confirm and cancel pair is compensating: confirming and then cancelling the same assignment returns `committed_hours` to exactly its pre-confirm value.

Alternatively, the coordinator may run auto-match against a request — blocked while posture is `RESTRICTED` or `FROZEN`, and requiring the request to stand in `OPEN` or `MATCHING`, with any other status failing as `ERR_INVALID_STATE`. Auto-match filters the incident's volunteers to eligible candidates, all of whose conditions must hold: status `READY`; a `VERIFIED` credential matching the `required_skill` at a sufficient class; a fresh `CLEARED` background check; a current briefing and an active waiver; no existing assignment for this same request in `PROPOSED`, `ACCEPTED`, `CONFIRMED`, or `CHECKED_IN`; room under the 40.00-hour weekly cap for the candidate shift; and no overlap with the volunteer's committed shifts under the half-open rule above. For each candidate it selects among the incident's shifts whose `site_name` matches the request's exactly, whose status is `OPEN_FOR_ROSTER`, whose `rostered_count` is below `capacity`, whose window is fully contained in the request window, and which — when `RED` — the candidate's `ADVANCED` qualifying credential permits, picking the shift with the earliest `start_at` and breaking ties by `created_at` ascending. Candidates are ranked by `verified_hours_total` ascending, then `created_at` ascending, then last name and first name in ascending lexicographic order — the last and first whitespace-delimited tokens of `full_name` respectively; an `id` is never consulted. The matcher then walks the ranked list, placing each candidate on their selected shift as a `PROPOSED` assignment with `origin` `AUTO_MATCH`, recomputing the shift's remaining capacity after every placement, skipping a candidate whose selected shift has no room and continuing with the next, until the request's live assignments — those in `PROPOSED`, `ACCEPTED`, `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` — number `headcount_needed`, or the candidates or shifts run out; pre-existing live assignments therefore count against the quota and auto-match merely tops the request up. If not a single placement can be made, the whole call is rejected with `ERR_NO_ELIGIBLE_PLACEMENTS` (HTTP 422) and the request is left untouched. Otherwise the response carries `created_assignment_ids`, `proposed_count`, `remaining_need` — `headcount_needed` minus the live-assignment count after placement — and the resulting `request_status`; at least one placement moves an `OPEN` request to `MATCHING`, and posture is re-derived.

Cancelling a request — an `AgencyCoordinator` action possible from `OPEN`, `MATCHING`, or `FILLED` (otherwise `ERR_INVALID_STATE`) — releases everything it holds: each of its assignments in `PROPOSED`, `ACCEPTED`, or `CONFIRMED` is cancelled and each `CHECKED_IN` assignment is recalled, with per-assignment release of committed hours and recomputation of `filled_count` and `rostered_count` under the regressions of §2.6; seat bookings in `BOOKED` or `BOARDED` on those assignments are cancelled with their trips' `booked_seats` recomputed; and posture is re-derived. Completing a request — from `MATCHING` or `FILLED` — demands that none of its assignments remain in `PROPOSED`, `ACCEPTED`, `CONFIRMED`, or `CHECKED_IN` (`ERR_OPEN_ASSIGNMENTS`) and that no hour entry on those assignments sit in `SUBMITTED` or `DISPUTED` (`ERR_HOURS_UNRESOLVED`); completion stamps the request `COMPLETED` and re-derives posture.

### 3.4. Field Operations: Check-in, Transport, and Protective Equipment

A `CONFIRMED` volunteer reports to the site, where a `SiteSupervisor` checks them in. Check-in requires the assignment `CONFIRMED` (otherwise `ERR_INVALID_STATE`), the posture not `FROZEN`, the shift in `OPEN_FOR_ROSTER` or `LOCKED`, and the logical now inside the check-in window, which opens 30 minutes before the shift's `start_at` and closes at its `end_at` — inclusive at both ends, so check-in exactly at the opening or closing instant succeeds; outside that window the call fails with `ERR_OUTSIDE_CHECKIN_WINDOW`. Three gate documents must also hold: a current briefing (`ERR_BRIEFING_NOT_CURRENT`), an active waiver (`ERR_WAIVER_NOT_SIGNED`), and at least one PPE issuance still `ISSUED` for the volunteer (`ERR_PPE_NOT_ISSUED`). A successful check-in stamps `checked_in_at` and, when the volunteer was `READY`, promotes them to `DEPLOYED`. Completing a checked-in assignment stamps `completed_at`, releases the shift's `duration_hours` from the volunteer's `committed_hours`, and returns the volunteer from `DEPLOYED` to `READY` once their last checked-in assignment closes.

Two unhappy paths release the same commitments with the same automatic regressions. A no-show may be recorded only at or after the shift's `end_at` — earlier attempts fail with `ERR_TOO_EARLY_FOR_NO_SHOW` — and it releases `committed_hours`, decrements `rostered_count` (reopening a `LOCKED` shift that falls below capacity), decrements `filled_count` (regressing `FILLED` to `MATCHING`, and `MATCHING` to `OPEN` when emptied of fills and proposals), records 10 no-show risk points timed at the shift's `end_at` (see §3.6), and re-derives posture. A safety recall by a `RiskOfficer` moves a `CHECKED_IN` assignment to `RECALLED` with the same releases and regressions, plus the `DEPLOYED`-to-`READY` return when the volunteer's last checked-in assignment closes. Plain cancellation — by an `IntakeCoordinator` or a `VRCManager`, or arriving by cascade — applies from `PROPOSED`, `ACCEPTED`, or `CONFIRMED` (otherwise `ERR_INVALID_STATE`): a cancelled `CONFIRMED` assignment releases hours, roster, and fill with the regressions above, while a cancelled `PROPOSED` or `ACCEPTED` assignment only regresses a `MATCHING` request to `OPEN` if it leaves the request empty; either way the assignment's `BOOKED` or `BOARDED` seat bookings are cancelled with their trips' `booked_seats` recomputed, and posture is re-derived.

Getting volunteers to the site is the trip pipeline. A `LogisticsCoordinator` schedules a trip with `incident_id`, the `site_shift_id` it ferries volunteers to — the shift must exist and belong to the same incident, with a cross-incident shift rejected as `ERR_RESOURCE_NOT_FOUND` — a free-form `vehicle_id`, a `seat_capacity` of at least 1, a `depart_at`, and an `arrive_estimate_at` strictly after the departure. Vehicles turn around slowly: for the same `vehicle_id` within the same incident, any existing trip in `SCHEDULED` or `DEPARTED` (cancelled and arrived trips free the vehicle, as do trips of other incidents) conflicts with the new one when the new departure falls strictly before the existing trip's estimated arrival plus a 45-minute buffer and, symmetrically, the existing departure falls strictly before the new trip's estimated arrival plus the same buffer; a conflict is rejected with `ERR_VEHICLE_TURNAROUND_CONFLICT`. Unlike the shift-adjacency rule, plain adjacency is not enough here: a gap of exactly 45 minutes between one trip's estimated arrival and the other's departure is required and sufficient, and anything shorter is illegal. The trip begins `SCHEDULED` with `booked_seats` zero; departure — blocked while posture is `FROZEN` — moves it to `DEPARTED`, and arrival moves it to `ARRIVED`. Cancelling is possible only while `SCHEDULED`, since a `DEPARTED` trip cannot be cancelled (`ERR_INVALID_STATE`), and it cancels every `BOOKED` or `BOARDED` seat booking on the trip, driving `booked_seats` to zero.

Seats are booked per assignment: the booking names a `trip_id` and an `assignment_id`, requiring the trip still `SCHEDULED` and the assignment in `CONFIRMED` or `CHECKED_IN` (otherwise `ERR_INVALID_STATE`), and the server copies the booking's `volunteer_id` from the assignment; no incident-coherence check is applied between the trip and the assignment. At most one non-`CANCELLED` booking may exist for the same assignment on the same trip, with a duplicate refused as `ERR_INVALID_REQUEST`. The trip must still have a free seat — a booking that takes the last seat is allowed, while one beyond it fails with `ERR_SEAT_CAPACITY_REACHED` — and the volunteer must not already hold a non-`CANCELLED` booking on another trip whose half-open interval from `depart_at` to `arrive_estimate_at` intersects the candidate trip's, which fails with `ERR_DOUBLE_BOOKED_TRIP`. A created booking is `BOOKED` and increments the trip's `booked_seats`. Boarding, performed by a `SiteSupervisor` while the trip is still `SCHEDULED` (otherwise `ERR_INVALID_STATE`), re-checks briefing currency and waiver presence with the same `ERR_BRIEFING_NOT_CURRENT` and `ERR_WAIVER_NOT_SIGNED` failures as check-in. Once the trip has `DEPARTED`, a `BOOKED` seat can be marked `NO_SHOW`, freeing the seat by decrementing `booked_seats`; a plain cancellation by a `LogisticsCoordinator` frees it the same way. A `BOARDED` booking, however, leaves the manifest only by cascade — when the volunteer is suspended or withdraws — never by direct call.

Protective equipment draws down the incident's stock. Issuing PPE requires the volunteer to be `READY` or `DEPLOYED` (otherwise `ERR_INVALID_STATE`) and to hold an `ACTIVE` waiver (`ERR_WAIVER_NOT_SIGNED`). The request names a `volunteer_id`, an `item_type` among the five stock keys, and a `quantity` of at least 1, which may not exceed the incident's remaining `ppe_stock` for that item: issuing exactly the remaining units is allowed, while one unit more fails with `ERR_PPE_STOCK_INSUFFICIENT`. The stock is decremented at once, and the issuance stands `ISSUED`. Closing an issuance takes an `outcome` of `RETURNED`, `DAMAGED`, or `LOST`: `RETURNED` restores the issued quantity to the incident's stock as a compensating credit, while `DAMAGED` and `LOST` do not restore it; all three stamp `closed_at` and are terminal.

### 3.5. Hour Accounting and Federal Cost-Share Documentation

After an assignment reaches `COMPLETED` — entries against assignments in any other state fail with `ERR_INVALID_STATE` — hours are reported with an `assignment_id`, a `work_date` in `YYYY-MM-DD` form that must equal the UTC calendar date of the assignment's shift `start_at`, and `hours` that must be positive, at most 16, a multiple of 0.25, and no more than the shift's `duration_hours`. A `Volunteer` caller may report only on their own assignments under the ownership rule of §2.8; a `SiteSupervisor` may report for anyone. At most one entry not in `REJECTED_FINAL` may exist for the same assignment and work date, with a duplicate refused as `ERR_DUPLICATE_HOUR_ENTRY`. Creation stamps `submitted_by_user_id` from the caller, computes `entry_value_cents` as below, adds that value into the incident's `provisional_cost_share_cents`, and sets the entry `SUBMITTED`.

The entry's value prices the qualifying credential — the volunteer's `VERIFIED` credential whose `skill_code` matches the assignment request's `required_skill`; when several qualify, the highest `credential_class` wins with ties broken by earliest `created_at`, and if no `VERIFIED` credential matches at pricing time the same selection falls back to any matching credential record, with the `STANDARD` rate applying when no matching credential exists at all. Its `credential_class` fixes the hourly rate: 2800 cents per hour for `STANDARD`, 4600 cents for `ADVANCED`. Hours up to a threshold of 8.0 are normal hours and any remainder is overtime. The value is the normal hours times the rate, plus the overtime hours times the rate times one and a half, rounded half-up to a whole cent — computed once per entry at creation and recomputed on each resubmission, before any summation.

Verification and dispute form the audit loop, both segregated from the submitter per §2.8. Verifying a `SUBMITTED` entry — a `SiteSupervisor` action — stamps `verified_by_user_id`, adds the entry's `hours` to the volunteer's `verified_hours_total`, and recomputes the incident rollups as the entry joins the verified-only input set it was already provisionally inside. A first dispute moves the entry to `DISPUTED`, increments `dispute_count` to 1, records the supplied `reason` in `dispute_reason`, and leaves the provisional total unchanged, because a disputed entry still counts provisionally. The submitter, or a supervisor, resubmits from `DISPUTED` with corrected `hours` that must satisfy the same shape rules as creation: the entry returns to `SUBMITTED`, `resubmit_count` increments, `entry_value_cents` is recomputed, the provisional total is adjusted by the delta, and `submitted_by_user_id` deliberately stays with the original submitter. A second dispute — possible only on a resubmitted entry, one whose `dispute_count` already stands at 1 — settles the matter: the entry flips to terminal `REJECTED_FINAL`, `dispute_count` becomes 2, the latest `reason` is kept, and the entry's value leaves the provisional total, `REJECTED_FINAL` being the only status excluded from it.

The incident's cost-share ledger rolls these entries up in two views. The provisional view, `provisional_cost_share_cents`, sums `entry_value_cents` over every hour entry of the incident's assignments in `SUBMITTED`, `DISPUTED`, or `VERIFIED` — the documentation-in-progress view used during the incident. The audited view, `verified_cost_share_cents`, sums only `VERIFIED` entries and underpins federal documentation and close-out; it is strictly smaller than the provisional view whenever an unverified, non-final entry exists. The reimbursement split is evaluated in pinned order: `federal_share_cents` is the verified total multiplied by 0.75 and rounded half-up to whole cents; `state_share_cents` is the verified total multiplied by 0.125 and rounded half-up; and `local_share_cents` is whatever remains — the verified total minus the federal share minus the state share — absorbing the rounding remainder rather than being independently rounded. Because per-entry values are rounded before any summation, the two views diverge exactly when a non-`VERIFIED`, non-`REJECTED_FINAL` entry exists.

### 3.6. Risk Management, Suspension, and Volunteer Demobilization

Conduct and safety concerns enter as risk reports, filed by a `SiteSupervisor`, `IntakeCoordinator`, or `LogisticsCoordinator` with a `subject_volunteer_id`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, a `category` of `SAFETY_VIOLATION`, `MISCONDUCT`, `NO_SHOW_PATTERN`, or `OTHER`, a free-text `description`, and the `occurred_at` instant of the conduct. The server records `reporter_user_id` from the caller and files the report as `FILED`; a report may be filed against a volunteer in any status. A `RiskOfficer` — never the reporter, per §2.8 — then substantiates or dismisses it. Substantiation stamps `adjudicated_by_user_id` and `adjudicated_at`, awards points by severity into `points_awarded` (5 for `LOW`, 15 for `MEDIUM`, 30 for `HIGH`, 60 for `CRITICAL`), recomputes the volunteer's two risk scores, may trigger automatic suspension as below, and re-derives posture — remember that a `CRITICAL` substantiation adjudicated within the trailing 24 hours freezes the incident per §2.7. Dismissal stamps the same adjudication fields and nothing more.

Risk scores combine two point sources, each with an event time: substantiated reports timed at their `adjudicated_at`, and no-show assignments worth 10 points timed at their shift's `end_at`. The `current_risk_score` decays in steps: a source counts in full while its age is under 168 hours (seven days), counts at half — computed by floor division of its points by two — from 168 hours up to but not including 720 hours (thirty days), and counts as zero at or beyond 720 hours, with the total never falling below zero. The `lifetime_risk_score` sums the same sources with no decay, forever; identical inputs therefore always leave the lifetime score at least the current one, strictly greater once any source passes 168 hours. The current score drives operational decisions, and immediately after a substantiation, if it has reached at least 50 while the volunteer is `CLEARED`, `READY`, or `DEPLOYED`, the system suspends the volunteer automatically.

Suspension — whether automatic at the 50-point threshold, by a `RiskOfficer`'s direct call from `VETTING`, `CLEARED`, `READY`, or `DEPLOYED` (any other state fails with `ERR_INVALID_STATE`), or by a flagged background check — runs one cascade in an exact order. First, every assignment of the volunteer in `PROPOSED`, `ACCEPTED`, or `CONFIRMED` is cancelled, and every `CHECKED_IN` assignment is recalled. Second, for each cancelled or recalled assignment the volunteer's `committed_hours` are released and the parent request's `filled_count` and the shift's `rostered_count` are recomputed with the usual regressions — `FILLED` to `MATCHING` when fills drop below headcount, `MATCHING` to `OPEN` when no fills and no `PROPOSED` or `ACCEPTED` assignments remain, and a `LOCKED` shift reopening below capacity. Third, every `BOOKED` or `BOARDED` seat booking of the volunteer is cancelled and each owning trip's `booked_seats` recomputed. Fourth, the incident's posture is re-derived. Reinstatement returns a `SUSPENDED` volunteer to `VETTING` for fresh vetting: it requires a background check already standing in `REQUESTED` for the volunteer (otherwise `ERR_INVALID_STATE`) and a `lifetime_risk_score` below 100 — at 100 or more the volunteer is blacklisted and reinstatement fails with `ERR_VOLUNTEER_BLACKLISTED` (HTTP 403); the blacklist check is enforced first, so a blacklisted volunteer fails with `ERR_VOLUNTEER_BLACKLISTED` even when no `REQUESTED` check exists.

Two further levers move volunteers out of the pipeline. Withdrawal — by an `IntakeCoordinator`, or by the volunteer themselves under the ownership rule of §2.8 — applies from `REGISTERED`, `VETTING`, `CLEARED`, or `READY` (otherwise `ERR_INVALID_STATE`) and releases commitments exactly like the suspension cascade above — assignment cancellations with their releases and regressions, seat-booking cancellations, and the posture re-derivation; because those states never carry checked-in work, no recalls occur, and the volunteer lands in terminal `WITHDRAWN`. Separately, revoking a clearance — a `RiskOfficer` or `VRCManager` action from `ACTIVE` — records the supplied `reason` in `revoked_reason`; revoking a liability waiver while the volunteer is `READY` regresses them to `CLEARED`, while revoking it during `DEPLOYED` suspends them with the full cascade above; revoking a waiver in any other volunteer status, and revoking a briefing in any status, carries no volunteer-level consequence.

Demobilization is the honorable exit, performed by a `VRCManager` from `CLEARED`, `READY`, or `SUSPENDED` (otherwise `ERR_INVALID_STATE`) while the incident is `ACTIVE` or `DEMOBILIZATION` — in any other lifecycle state the attempt fails with `ERR_INCIDENT_NOT_ACTIVE`. It requires that no assignment of the volunteer remain in `PROPOSED`, `ACCEPTED`, `CONFIRMED`, or `CHECKED_IN` (`ERR_OPEN_ASSIGNMENTS`) and that no PPE issuance of the volunteer still be `ISSUED` (`ERR_UNRETURNED_PPE`). At that single moment the volunteer's `recognition_tier` is computed and stored: a base tier of `GOLD` for at least 60.00 verified hours, `SILVER` for at least 24.00, and `BRONZE` for at least 8.00, with `NONE` below that and inclusive boundaries throughout — exactly 24.00 hours earns `SILVER` — except that a base tier of `GOLD` is capped down to `SILVER` whenever the `lifetime_risk_score` is 20 or more. The volunteer's `demobilized_at` is stamped from the logical clock, replacing the default `NONE` tier carried since registration.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`. The table below is deliberately minimal — request payloads, response payloads, and side effects are specified by the workflow narratives of §3 and the system-wide rules of §2, not here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vrc/incidents` | Create an incident in `ACTIVATION` with posture `OPEN` | VRCManager |
| GET | `/vrc/incidents/{incidentId}` | Get one incident, including posture and cost-share fields | All roles |
| POST | `/vrc/incidents/{incidentId}/activate` | Move the incident from `ACTIVATION` to `ACTIVE` | VRCManager |
| POST | `/vrc/incidents/{incidentId}/begin-demobilization` | Move the incident from `ACTIVE` to `DEMOBILIZATION` | VRCManager |
| POST | `/vrc/incidents/{incidentId}/close` | Move the incident from `DEMOBILIZATION` to `CLOSED` after close-out preconditions | VRCManager |
| GET | `/vrc/incidents/{id}/volunteers` | List volunteers of an incident | All roles |
| GET | `/vrc/incidents/{id}/support-requests` | List support requests of an incident | All roles |
| GET | `/vrc/incidents/{id}/shifts` | List site shifts of an incident | All roles |
| POST | `/vrc/volunteers` | Register a spontaneous volunteer in `REGISTERED` | IntakeCoordinator, Volunteer |
| GET | `/vrc/volunteers/{volunteerId}` | Get one volunteer, including committed hours, risk scores, and recognition tier | All roles |
| PATCH | `/vrc/volunteers/{volunteerId}` | OCC-guarded edit of `phone`, `email`, `home_locality` | IntakeCoordinator, Volunteer |
| POST | `/vrc/volunteers/{volunteerId}/submit-for-vetting` | Move the volunteer from `REGISTERED` to `VETTING` | IntakeCoordinator |
| POST | `/vrc/volunteers/{volunteerId}/mark-ready` | Move the volunteer from `CLEARED` to `READY` after the readiness gate | IntakeCoordinator |
| POST | `/vrc/volunteers/{volunteerId}/suspend` | Suspend the volunteer with the full suspension cascade | RiskOfficer |
| POST | `/vrc/volunteers/{volunteerId}/reinstate` | Return a `SUSPENDED` volunteer to `VETTING` | RiskOfficer |
| POST | `/vrc/volunteers/{volunteerId}/withdraw` | Withdraw the volunteer with the release cascade | IntakeCoordinator, Volunteer |
| POST | `/vrc/volunteers/{volunteerId}/demobilize` | Demobilize the volunteer, computing the recognition tier | VRCManager |
| GET | `/vrc/volunteers/{id}/credentials` | List a volunteer's skill credentials | All roles |
| GET | `/vrc/volunteers/{id}/background-checks` | List a volunteer's background checks | All roles |
| GET | `/vrc/volunteers/{id}/clearances` | List a volunteer's clearances | All roles |
| GET | `/vrc/volunteers/{id}/ppe-issuances` | List a volunteer's PPE issuances | All roles |
| GET | `/vrc/volunteers/{id}/risk-reports` | List risk reports whose subject is the volunteer | All roles |
| POST | `/vrc/credentials` | Claim a skill credential in `CLAIMED` | IntakeCoordinator, Volunteer |
| POST | `/vrc/credentials/{credentialId}/verify` | Verify a `CLAIMED` or `EXPIRED` credential (the renewal loop) | VettingOfficer |
| POST | `/vrc/credentials/{credentialId}/reject` | Reject a `CLAIMED` or `EXPIRED` credential | VettingOfficer |
| POST | `/vrc/background-checks` | Open a background check for a `VETTING` or `SUSPENDED` volunteer | VettingOfficer |
| POST | `/vrc/background-checks/{checkId}/clear` | Clear a `REQUESTED` check, setting a 720-hour expiry | VettingOfficer |
| POST | `/vrc/background-checks/{checkId}/flag` | Flag a `REQUESTED` check, cascading the volunteer | VettingOfficer |
| POST | `/vrc/clearances` | Record a completed safety briefing or signed liability waiver | IntakeCoordinator |
| POST | `/vrc/clearances/{clearanceId}/revoke` | Revoke an `ACTIVE` clearance with a reason | RiskOfficer, VRCManager |
| POST | `/vrc/support-requests` | File a support request in `DRAFT` | AgencyCoordinator |
| GET | `/vrc/support-requests/{requestId}` | Get one support request, including `filled_count` and `version` | All roles |
| PUT | `/vrc/support-requests/{requestId}` | OCC-guarded edit of a `DRAFT` or `OPEN` request | AgencyCoordinator |
| POST | `/vrc/support-requests/{requestId}/publish` | Move the request from `DRAFT` to `OPEN` | AgencyCoordinator |
| POST | `/vrc/support-requests/{requestId}/auto-match` | Ranked selector creating `PROPOSED` assignments up to `headcount_needed` | IntakeCoordinator |
| POST | `/vrc/support-requests/{requestId}/cancel` | Cancel the request with the assignment and seat release cascade | AgencyCoordinator |
| POST | `/vrc/support-requests/{requestId}/complete` | Complete the request once assignments and hours are resolved | AgencyCoordinator |
| POST | `/vrc/shifts` | Schedule a site shift in `SCHEDULED` | LogisticsCoordinator |
| GET | `/vrc/shifts/{shiftId}` | Get one site shift | All roles |
| POST | `/vrc/shifts/{shiftId}/open-roster` | Move the shift from `SCHEDULED` to `OPEN_FOR_ROSTER` | LogisticsCoordinator |
| POST | `/vrc/shifts/{shiftId}/cancel` | Cancel the shift with the shift cancellation cascade | LogisticsCoordinator |
| POST | `/vrc/assignments` | Manually propose an assignment in `PROPOSED` | IntakeCoordinator |
| GET | `/vrc/assignments/{assignmentId}` | Get one assignment | All roles |
| GET | `/vrc/assignments` | Filtered assignment list | All roles |
| POST | `/vrc/assignments/{assignmentId}/accept` | Volunteer accepts a `PROPOSED` assignment | Volunteer |
| POST | `/vrc/assignments/{assignmentId}/decline` | Volunteer declines a `PROPOSED` assignment | Volunteer |
| POST | `/vrc/assignments/{assignmentId}/confirm` | Confirm an `ACCEPTED` assignment, debiting committed hours | IntakeCoordinator |
| POST | `/vrc/assignments/{assignmentId}/cancel` | Cancel an assignment with compensating release | IntakeCoordinator, VRCManager |
| POST | `/vrc/assignments/{assignmentId}/check-in` | Check a `CONFIRMED` volunteer in within the check-in window | SiteSupervisor |
| POST | `/vrc/assignments/{assignmentId}/complete` | Complete a `CHECKED_IN` assignment | SiteSupervisor |
| POST | `/vrc/assignments/{assignmentId}/no-show` | Mark a `CONFIRMED` assignment as no-show at or after shift end | SiteSupervisor |
| POST | `/vrc/assignments/{assignmentId}/recall` | Recall a `CHECKED_IN` assignment for safety | RiskOfficer |
| POST | `/vrc/trips` | Schedule a vehicle trip to a shift site | LogisticsCoordinator |
| GET | `/vrc/trips/{tripId}` | Get one trip | All roles |
| GET | `/vrc/trips` | Filtered trip list | All roles |
| POST | `/vrc/trips/{tripId}/depart` | Move the trip from `SCHEDULED` to `DEPARTED` | LogisticsCoordinator |
| POST | `/vrc/trips/{tripId}/arrive` | Move the trip from `DEPARTED` to `ARRIVED` | LogisticsCoordinator |
| POST | `/vrc/trips/{tripId}/cancel` | Cancel a `SCHEDULED` trip and its seat bookings | LogisticsCoordinator |
| POST | `/vrc/seat-bookings` | Book a seat for a `CONFIRMED` or `CHECKED_IN` assignment | LogisticsCoordinator |
| GET | `/vrc/seat-bookings/{bookingId}` | Get one seat booking | All roles |
| GET | `/vrc/seat-bookings` | Filtered seat-booking list | All roles |
| POST | `/vrc/seat-bookings/{bookingId}/board` | Board a `BOOKED` seat while the trip is `SCHEDULED` | SiteSupervisor |
| POST | `/vrc/seat-bookings/{bookingId}/cancel` | Cancel a `BOOKED` seat, freeing it | LogisticsCoordinator |
| POST | `/vrc/seat-bookings/{bookingId}/mark-no-show` | Mark a `BOOKED` seat as no-show after departure | SiteSupervisor |
| POST | `/vrc/ppe-issuances` | Issue PPE to a `READY` or `DEPLOYED` volunteer, decrementing stock | LogisticsCoordinator |
| POST | `/vrc/ppe-issuances/{issuanceId}/close` | Close an issuance as `RETURNED`, `DAMAGED`, or `LOST` | LogisticsCoordinator |
| POST | `/vrc/hour-entries` | Report worked hours for a `COMPLETED` assignment | Volunteer, SiteSupervisor |
| POST | `/vrc/hour-entries/{entryId}/verify` | Verify a `SUBMITTED` entry | SiteSupervisor |
| POST | `/vrc/hour-entries/{entryId}/dispute` | Dispute a `SUBMITTED` entry; a second dispute finalizes rejection | SiteSupervisor |
| POST | `/vrc/hour-entries/{entryId}/resubmit` | Resubmit a `DISPUTED` entry with corrected hours | Volunteer, SiteSupervisor |
| GET | `/vrc/assignments/{id}/hour-entries` | List hour entries of an assignment | All roles |
| POST | `/vrc/risk-reports` | File a conduct or safety report against a volunteer | SiteSupervisor, IntakeCoordinator, LogisticsCoordinator |
| POST | `/vrc/risk-reports/{reportId}/substantiate` | Substantiate a `FILED` report, awarding points | RiskOfficer |
| POST | `/vrc/risk-reports/{reportId}/dismiss` | Dismiss a `FILED` report | RiskOfficer |
| POST | `/vrc/_clock/set_current_utc` | Set the server's logical clock, triggering expiry sweeps and a posture recompute | VRCManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INCIDENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INCIDENT_DEMOBILIZING` | 409 Conflict |
| `ERR_INCIDENT_CLOSING_BLOCKED` | 409 Conflict |
| `ERR_POSTURE_FROZEN` | 409 Conflict |
| `ERR_POSTURE_RESTRICTED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_CREDENTIALS_CLAIMED` | 409 Conflict |
| `ERR_READINESS_INCOMPLETE` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_READY` | 409 Conflict |
| `ERR_VOLUNTEER_BLACKLISTED` | 403 Forbidden |
| `ERR_CHECK_ALREADY_PENDING` | 409 Conflict |
| `ERR_BACKGROUND_CHECK_LAPSED` | 422 Unprocessable Entity |
| `ERR_SOD_CLEARANCE_VIOLATION` | 403 Forbidden |
| `ERR_SOD_HOUR_VERIFICATION` | 403 Forbidden |
| `ERR_SOD_RISK_ADJUDICATION` | 403 Forbidden |
| `ERR_SKILL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREDENTIAL_CLASS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_HAZARD_CREDENTIAL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BRIEFING_NOT_CURRENT` | 422 Unprocessable Entity |
| `ERR_WAIVER_NOT_SIGNED` | 422 Unprocessable Entity |
| `ERR_PPE_NOT_ISSUED` | 422 Unprocessable Entity |
| `ERR_SITE_WINDOW_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DOUBLE_BOOKED_SHIFT` | 409 Conflict |
| `ERR_DOUBLE_BOOKED_TRIP` | 409 Conflict |
| `ERR_VEHICLE_TURNAROUND_CONFLICT` | 409 Conflict |
| `ERR_OUTSIDE_CHECKIN_WINDOW` | 409 Conflict |
| `ERR_TOO_EARLY_FOR_NO_SHOW` | 409 Conflict |
| `ERR_SHIFT_WINDOW_PASSED` | 409 Conflict |
| `ERR_CLEARANCE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_HOUR_ENTRY` | 409 Conflict |
| `ERR_SHIFT_CAPACITY_REACHED` | 409 Conflict |
| `ERR_SEAT_CAPACITY_REACHED` | 409 Conflict |
| `ERR_PPE_STOCK_INSUFFICIENT` | 409 Conflict |
| `ERR_WEEKLY_HOUR_CAP` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_PLACEMENTS` | 422 Unprocessable Entity |
| `ERR_OPEN_ASSIGNMENTS` | 409 Conflict |
| `ERR_UNRETURNED_PPE` | 409 Conflict |
| `ERR_HOURS_UNRESOLVED` | 409 Conflict |

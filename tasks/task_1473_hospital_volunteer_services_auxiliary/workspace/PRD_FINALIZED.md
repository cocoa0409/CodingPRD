# Hospital Volunteer Services API — Product Requirements Document

## 1. Introduction

A hospital auxiliary runs on people who are not employees. Teenagers file paperwork after school, retirees staff the gift shop, community groups run fundraising campaigns — and every one of them must be screened, trained, badged, scheduled, and recognized without ever appearing on payroll. The office that coordinates this work today juggles paper application forms, spreadsheets of tuberculosis-test expiry dates, and a corkboard of shift sign-up sheets. This document specifies a single API, mounted under `/auxiliary`, through which the volunteer services office manages the entire lifecycle: application intake and review, background and health clearances, department staffing requests and placement negotiation, orientation and annual training, shift scheduling with junior supervision rules, hour logging and recognition, gift shop sales, and fundraising campaign proceeds.

Two properties make this domain harder than a generic scheduling system. First, everything is compliance-gated: a volunteer's fitness to serve is a live, derived fact built from three expiring clearances, and it must gate placement, scheduling, and badging the moment evidence lapses — not at the next monthly audit. Second, the money side demands segregation of duties worthy of an audit committee: the screener who submits clearance evidence may not adjudicate it, and the treasurer who creates a campaign may not disburse its proceeds. The auxiliary also owes its volunteers fairness guarantees — a deterministic waitlist, a transparent recognition points system, and a firm weekly cap protecting junior volunteers from overcommitment.

Because the system's time rules (expiry, grace windows, signup deadlines, cooling-off periods, age evaluations) must be reproducible in test and operations alike, the server keeps its own logical clock rather than trusting wall-clock time. And because a handful of records attract competing writers — the volunteer profile and the shift chief among them — the API uses explicit optimistic concurrency on exactly those writes rather than locking. The rest of this document is the contract: §2 covers system-wide structure and cross-cutting rules, §3 walks the business workflows, §4 locates every endpoint, and §5 catalogs every error code.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which that user acts. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the named role is not among the roles authorized for the target endpoint (see §4), the request is rejected with `ERR_UNAUTHORIZED_ROLE`.

Six roles exist, spelled exactly as follows:

- `VolunteerServicesDirector` — the director of volunteer services. Owns admission decisions on applications, organization configuration (departments and volunteer roles), separations, and the annual compliance review.
- `VolunteerCoordinator` — the day-to-day operator: application intake and review workflow, clearance intake, volunteer activation and profile maintenance, shift scheduling, assignment confirmation, hour adjudication, badge operations, and placement offers.
- `Screener` — the HR / employee-health screener. Submits, adjudicates, and revokes clearance evidence, and is barred by segregation of duties from adjudicating evidence they submitted.
- `DepartmentHead` — a hospital department head. Creates and manages staffing requests and negotiates placements, but only for departments they head.
- `AuxiliaryTreasurer` — the auxiliary's treasurer. Owns fundraising campaigns end to end, maintains the gift shop catalog, and may ring and void sales; barred by segregation of duties from disbursing a campaign they created.
- `Volunteer` — the volunteer themself, self-service only: read their own record, sign up for and cancel their own shifts, log their own hours, answer their own placement offers, and ring gift shop sales as their own cashier.

The `X-User-ID` header means different things depending on the role, and this difference is part of the contract. When `X-User-Role` is `VolunteerServicesDirector`, `VolunteerCoordinator`, `Screener`, or `AuxiliaryTreasurer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by_user_id` on a decided application, as `submitted_by_user_id` or `adjudicated_by_user_id` on a clearance, as `created_by_user_id` on a campaign, or as `voided_by_user_id` on a voided sale — but it never compares the value to any entity's `id`. When `X-User-Role` is `DepartmentHead`, `X-User-ID` is likewise an opaque operator identifier, but with one scoping consequence: ownership checks on department-scoped resources compare the department's `head_user_id` to `X-User-ID`, and a `DepartmentHead` may manage requests only for a department whose `head_user_id` equals their `X-User-ID`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting volunteer record itself; ownership checks on any resource that references a volunteer compare that resource's volunteer foreign key to `X-User-ID`.

Ownership violations are rejected with `ERR_NOT_RESOURCE_OWNER`. A `Volunteer` may only act on rows whose volunteer foreign key equals their own `X-User-ID`: reading their own volunteer record and summary, signing themselves up, cancelling their own assignments, logging their own hours, accepting or declining or countering their own placements, and listing or ringing their own sales. A `DepartmentHead` may only manage the requests of a department they head.

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

List endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Within a list, resources are always sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically without re-deriving counts.

### 2.4. The Logical Clock

The server maintains a **logical clock** that is deliberately decoupled from wall-clock time. At startup, before it has ever been set, the logical clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time at any point afterward. Every rule in this document that says "now" — clearance and training expiry, the posture grace windows, signup and cancellation deadlines, the sale void window, the disbursement cooling-off period, and every age evaluation — reads this clock. A test-driving capability sets the clock: the caller supplies a target instant in the `to_iso8601` field, and the response returns the resulting `current_utc`. Setting the clock is restricted to the five staff roles (`VolunteerServicesDirector`, `VolunteerCoordinator`, `Screener`, `DepartmentHead`, `AuxiliaryTreasurer`); it is not available to `Volunteer`.

### 2.5. Common Resource Properties, Timestamps, and Versioning

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp fixed at creation. Every resource except the recognition event log additionally carries `updated_at` and an integer `version`. Timestamps are ISO 8601 UTC with three fractional digits. `updated_at` refreshes on every mutation of the record. `version` increments by exactly one on every mutation, including mutations driven by cascades and side effects — a profile edit, an hour approval that recomputes totals, an activation, a suspension, a separation — so two readers who observe the same `version` have observed the same record.

The one exception is the recognition event log. Recognition event rows are append-only: they carry `id` and `created_at` only, with no `updated_at` and no `version`, and no endpoint ever modifies them.

### 2.6. Precision, Rounding, and Monetary Representation

Service time and recognition arithmetic use **two decimal places with round-half-up rounding**. Wherever a total is built from parts, the rounding order is pinned: each part is rounded to two decimal places first, and the rounded parts are then summed exactly. Summing unrounded parts and rounding once at the end is a different algorithm and produces different results; it is non-conforming.

Money is represented as integer cents throughout — never fractional currency. Sale lines are rounded half-up to whole cents per line before the per-line amounts are summed.

Date-time comparisons are evaluated at second precision, and every boundary is inclusive or exclusive exactly as stated at the rule that uses it. Clearance and training validity periods use calendar-month arithmetic on UTC datetimes, not fixed day counts.

### 2.7. Optimistic Concurrency Control

Exactly three write operations carry an optimistic concurrency pin; no other endpoint accepts a version field of any kind.

- **Updating a volunteer profile** (`PUT /auxiliary/volunteers/{id}`) requires the `expected_volunteer_version` field, carrying the client's last observed `version` of the volunteer. If that value no longer matches the volunteer's current `version` — because another writer has mutated the record since the client last read it, whether by a profile edit, an hour approval, or a suspension cascade — the update is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Rescheduling or resizing a shift** (`PUT /auxiliary/shifts/{id}`) requires the `expected_shift_version` field, matched against the shift's current `version`. A second reschedule request sent after a first reschedule completed observes an unchanged business state — the shift is still `SCHEDULED` or `PUBLISHED` and still has no live assignments — and would legitimately succeed; only the stale version pin rejects it, again with `ERR_STALE_VERSION` (HTTP 412).
- **Approving an hour entry** requires the `expected_volunteer_version` field, because approval mutates the volunteer's derived totals (`total_service_hours`, `recognition_points`, `recognition_tier`) and bumps the volunteer's `version`. A second approval of a different pending entry that still carries the pre-approval version is rejected with `ERR_STALE_VERSION` (HTTP 412): the entry itself is legitimately approvable — only the client-pinned volunteer version is stale.

In all three cases the rule is the same shape: the client pins the version it last read, the server compares that pin against the record's current `version` at write time, and a mismatch rejects the write so the client re-reads before retrying.

### 2.8. Validation Order and Error Precedence

When several checks would fail on the same request, the server does not report them arbitrarily. Checks are evaluated in a fixed thirteen-tier order, and the earliest failing tier wins — an earlier failure masks later ones, so the client always sees the same error for the same doubly-invalid request.

1. **Header presence.** `X-User-ID` and `X-User-Role` present and non-empty — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Body well-formedness.** Required fields present, types valid, enum members valid, quantities at least 1, amounts non-negative, a shift's `start_at` strictly before its `end_at`, a campaign's `end_at` strictly after its `start_at` — `ERR_INVALID_REQUEST`.
3. **Role authorization.** The caller's role appears in the endpoint's authorized role list — `ERR_UNAUTHORIZED_ROLE`.
4. **Resource existence.** Path identifiers are validated first, left to right, then body-referenced foreign keys in their declared order; any missing reference is `ERR_NOT_FOUND`. This same left-to-right rule governs nested paths: an invalid identifier earlier in the path masks everything after it.
5. **Ownership.** Volunteer self-scope and department-head department scope — `ERR_NOT_RESOURCE_OWNER`.
6. **Segregation of duties.** The clearance adjudicator differs from the submitter, and the disbursing treasurer differs from the campaign creator — `ERR_SOD_CLEARANCE_ADJUDICATION` and `ERR_SOD_CAMPAIGN_DISBURSEMENT`.
7. **Optimistic concurrency.** The three version pins of §2.7 — `ERR_STALE_VERSION`.
8. **State preconditions.** The per-machine state gates of §3 — the family of invalid-state errors such as `ERR_APPLICATION_NOT_ACTIONABLE`, `ERR_VOLUNTEER_INVALID_STATE`, `ERR_CLEARANCE_INVALID_STATE`, `ERR_REQUEST_INVALID_STATE`, `ERR_PLACEMENT_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_HOUR_ENTRY_INVALID_STATE`, `ERR_TRAINING_RECORD_INVALID_STATE`, `ERR_BADGE_INVALID_STATE`, `ERR_CAMPAIGN_INVALID_STATE`, and `ERR_SALE_ALREADY_VOIDED`, together with the posture gates `ERR_POSTURE_FROZEN` and `ERR_POSTURE_NOT_CLEAR`.
9. **Minor-protection and training gates.** Age floors, junior department restrictions, the junior weekly cap, supervision requirements, and activation prerequisites — `ERR_ROLE_MIN_AGE_NOT_MET`, `ERR_DEPARTMENT_JUNIOR_RESTRICTED`, `ERR_JUNIOR_WEEKLY_HOUR_CAP_EXCEEDED`, `ERR_SUPERVISION_REQUIRED`, `ERR_SUPERVISOR_INELIGIBLE`, `ERR_SUPERVISOR_RATIO_EXCEEDED`, `ERR_TRAINING_REQUIREMENT_UNMET`, `ERR_ORIENTATION_INCOMPLETE`, `ERR_CLEARANCE_REQUIREMENTS_UNMET`.
10. **Uniqueness, capacity, and graph constraints.** Duplicates, slot and seat limits, overlaps, and graph blocks — `ERR_DUPLICATE_ACTIVE_CLEARANCE`, `ERR_DUPLICATE_PLACEMENT`, `ERR_PLACEMENT_LIMIT_EXCEEDED`, `ERR_DUPLICATE_SHIFT_ASSIGNMENT`, `ERR_SHIFT_TIME_OVERLAP`, `ERR_SHIFT_AT_CAPACITY`, `ERR_COUNTER_ROUND_EXHAUSTED`, `ERR_SHIFT_HAS_ASSIGNMENTS`, `ERR_ITEM_INACTIVE`, `ERR_HOURS_EXCEED_SHIFT`, `ERR_NO_ACCEPTED_PLACEMENT`.
11. **Temporal windows and deadlines.** Signup and cancellation windows, shift completion timing, the void window, campaign windows, the disbursement cooling-off, and the service-date range — `ERR_SIGNUP_WINDOW_CLOSED`, `ERR_CANCEL_WINDOW_CLOSED`, `ERR_SHIFT_NOT_ENDED`, `ERR_VOID_WINDOW_ELAPSED`, `ERR_CAMPAIGN_WINDOW_MISMATCH`, `ERR_DISBURSEMENT_COOLING_OFF`, `ERR_SERVICE_DATE_OUT_OF_RANGE`.
12. **Cross-entity reference consistency.** Linked-record ownership and cashier placement checks — `ERR_ASSIGNMENT_OWNERSHIP_MISMATCH`, `ERR_CASHIER_NOT_GIFT_SHOP_PLACED`, and the campaign-state check for sale attribution.
13. **Money and stock, last of all.** `ERR_INSUFFICIENT_STOCK`, `ERR_INSUFFICIENT_TENDER`, `ERR_DISBURSEMENT_EXCEEDS_BALANCE`.

The ordering is observable behavior. A sale request whose item is inactive (tier 10) and whose quantity also exceeds stock (tier 13) reports `ERR_ITEM_INACTIVE`, never `ERR_INSUFFICIENT_STOCK`; an approval whose pinned version is stale (tier 7) reports `ERR_STALE_VERSION` even if the entry's state would also fail tier 8.

### 2.9. The Volunteer Compliance Posture

A volunteer's `compliance_posture` is never written by any client; it is **derived live** from the volunteer's clearance records against the logical clock, computed on every read of the volunteer and recomputed after any clearance mutation and after the annual-review sweep. Three clearance types are required of every volunteer: `BACKGROUND`, `HEALTH_TB`, and `HEALTH_FLU`. For each type, only the volunteer's clearance of that type with the latest `created_at` is considered; older records of the same type are history.

Each type receives a verdict:

- **Hard failure** — no clearance of that type has ever been recorded for the volunteer, or the latest-created one is `SUBMITTED`, `REJECTED`, or `REVOKED`.
- When the latest-created clearance of the type is `CLEARED` or `EXPIRED`, its `expires_at` is compared against now:
  - Strictly more than 30 days past `expires_at` — **hard failure**.
  - Past `expires_at` but by no more than 30 days (exactly 30 days past still qualifies) — **grace**, meaning expired but inside the grace window.
  - From exactly 30 days before `expires_at` up to and including the expiry instant itself — **grace**, meaning expiring soon.
  - More than 30 days before `expires_at` — **in order**.

The posture is `FROZEN` when any one of the three types hard-fails. It is `RESTRICTED` when no type hard-fails but at least one type is in grace. It is `CLEAR` only when all three types are in order. Because posture derives live from `expires_at`, a volunteer can already read as `RESTRICTED` or `FROZEN` before the annual-review sweep flips any stored clearance status to `EXPIRED` — the sweep is bookkeeping, not discovery.

Posture is a gate, not a label. A posture of `FROZEN` blocks shift signup, placement creation, placement acceptance, and reinstatement, each rejected with `ERR_POSTURE_FROZEN`. Shift-assignment confirmation is stricter still: it requires a fully `CLEAR` posture and rejects `RESTRICTED` or `FROZEN` with `ERR_POSTURE_NOT_CLEAR`. Individual workflows in §3 repeat the gate that guards them.

## 3. Business Logic & Workflows

### 3.1. Application Intake, Review, and Admission Decisions

Admission begins on paper; the office keys the form in. A `VolunteerCoordinator`, or the `VolunteerServicesDirector`, creates the application with the applicant's `full_name`, `date_of_birth` (an ISO 8601 calendar date — the value every later junior-versus-adult evaluation reads), `email`, `phone`, and an optional free-text `notes`. A fresh application lands in `SUBMITTED` with its `volunteer_id` null: no volunteer record exists yet. The applications list can be filtered by `status` or by `volunteer_id`, which is how the office answers "does this person have an application on file?"

Review is a coordinator workflow. Starting review moves a `SUBMITTED` application to `IN_REVIEW`; acting on an application that is not in the state a transition requires is rejected with `ERR_APPLICATION_NOT_ACTIONABLE`. When the office needs more from the applicant, a request-for-information moves `IN_REVIEW` to `NEEDS_INFO` and records the supplied `info_request_note`. Once the applicant answers, resubmission returns the application from `NEEDS_INFO` to `IN_REVIEW`, optionally updating `notes`. This information-request loop — `IN_REVIEW` → `NEEDS_INFO` → `IN_REVIEW` — may repeat without bound. At any point while the application stands `SUBMITTED`, `IN_REVIEW`, or `NEEDS_INFO`, a coordinator may withdraw it, moving it to `WITHDRAWN`.

Decisions belong to the `VolunteerServicesDirector` alone, and only an application sitting in `IN_REVIEW` is decidable. The decision action carries a `decision` of `APPROVE` or `REJECT`. A rejection is incomplete without a `rejection_reason`; omitting it is a malformed request, `ERR_INVALID_REQUEST`. Either way the server stamps `decided_by_user_id` with the director's `X-User-ID` and `decided_at` from the logical clock. `APPROVED`, `REJECTED`, and `WITHDRAWN` are terminal: the application never moves again.

Approval is never just a status flip. For a **fresh application** — one whose `volunteer_id` is null — approval creates the volunteer record with `service_status` `ONBOARDING` and `joined_at` stamped from the logical clock, then points the application's `volunteer_id` at the new volunteer. For a **reapply-linked application**, approval instead walks the linked volunteer from `SEPARATED` back to `ONBOARDING`: `joined_at` resets to now, and `separated_at`, `separation_reason`, and `suspension_reason` are all cleared. In both cases, approval also mints a badge for the volunteer in `PENDING` — the standing invariant is exactly one non-`REVOKED` badge per volunteer at all times — and enrolls the volunteer in a `PENDING` training record for training code `ORIENTATION` with recurrence `ONE_TIME`.

A separated volunteer returns only through the front door. A coordinator creates a reapply application against a `SEPARATED` volunteer; it lands in `SUBMITTED` like any other application, except that its `volunteer_id` is set at creation. From there it flows through the same review loop, and its approval is the only exit from `SEPARATED` — the reactivation path of §3.4.

### 3.2. Clearances, Adjudication, and the Renewal Cycle

Three clearance types gate every volunteer's service: `BACKGROUND`, valid for 24 calendar months once cleared, and `HEALTH_TB` and `HEALTH_FLU`, each valid for 12 calendar months. A `Screener` or `VolunteerCoordinator` submits evidence by creating a clearance with `volunteer_id`, `clearance_type`, and a `document_ref` pointing at the submitted evidence document. The server records the caller's `X-User-ID` as `submitted_by_user_id`, and the record lands in `SUBMITTED`. At most one clearance per volunteer-and-type pair may exist outside the terminal `REVOKED` state: creating a second record while one stands `SUBMITTED`, `CLEARED`, `REJECTED`, or `EXPIRED` is rejected with `ERR_DUPLICATE_ACTIVE_CLEARANCE`. Renewals therefore reuse the existing record rather than adding a new one — that is what keeps the pair unique.

Adjudication belongs to the `Screener` role, under a hard segregation-of-duties rule: the adjudicator's `X-User-ID` must differ from the record's `submitted_by_user_id`, or the call fails with `ERR_SOD_CLEARANCE_ADJUDICATION`. Only a `SUBMITTED` record is adjudicable — anything else draws `ERR_CLEARANCE_INVALID_STATE`. The `decision` is `CLEARED` or `REJECTED`, with optional `adjudication_notes`, and the server stamps `adjudicated_by_user_id` and `adjudicated_at` from the logical clock. A `CLEARED` decision additionally sets `expires_at` to `adjudicated_at` plus the type's validity in calendar months — 24 for `BACKGROUND`, 12 for `HEALTH_TB`, 12 for `HEALTH_FLU`. A `REJECTED` decision sets only the adjudication fields; `expires_at` stays empty.

A `REJECTED` or `EXPIRED` clearance is renewed in place. Resubmission with a fresh `document_ref` returns the same record to `SUBMITTED`, resets `submitted_by_user_id` to the resubmitting caller's `X-User-ID`, and clears `adjudicated_by_user_id`, `adjudicated_at`, and `expires_at`. Attempting resubmission on a record in any other state is `ERR_CLEARANCE_INVALID_STATE`. The cycle `SUBMITTED` → `CLEARED` → `EXPIRED` → `SUBMITTED` (and the detour through `REJECTED`) is how a volunteer stays compliant across years of service.

Two forces move a `CLEARED` clearance out of good standing. The gentler one is time: the annual-review sweep of §3.6 flips a `CLEARED` record whose `expires_at` is at or before now to `EXPIRED`. The sharper one is revocation, available to a `Screener` or the `VolunteerServicesDirector`: the request carries a `reason`, and a `CLEARED` record moves to the terminal `REVOKED` (any other state, `ERR_CLEARANCE_INVALID_STATE`). Revocation leaves the volunteer with no cleared record of that type, so the `compliance_posture` of §2.9 recomputes to `FROZEN` — and a posture that has flipped to `FROZEN` cascades immediately: every assignment of the volunteer in `SIGNED_UP`, `CONFIRMED`, or `WAITLISTED` whose shift starts after now is cancelled, and each such cancellation on a `PUBLISHED` shift runs the waitlist promotion of §3.5. One revocation can therefore empty a volunteer's calendar and refill it from the waitlist in a single atomic request.

### 3.3. Departments, Roles, and the Placement Negotiation

The director configures the organization. A **department** has a unique `name`, a `head_user_id` naming the `DepartmentHead` who owns its staffing requests, and a `junior_allowed` flag that defaults to true — a department created with `junior_allowed` false refuses junior volunteers at both placement and shift assignment. A **volunteer role** has a unique `name`; a `category` of `PATIENT_FACING`, `GIFT_SHOP`, `CLERICAL`, `FUNDRAISING`, or `COMMUNITY` (the category drives the hour weighting of §3.6); a `minimum_age` in years, defaulting to 16 and evaluated at the relevant offer or service date; a `can_supervise_juniors` flag, defaulting to false; and `required_training_codes`, defaulting to an empty list — the `ANNUAL` training codes that must be `VALID` before a shift of this role can be confirmed.

A `DepartmentHead` staffs a department by creating a request with `department_id`, `role_id`, `slots_needed` of at least 1, and optional `notes`; the caller must head the named department, or the create fails with `ERR_NOT_RESOURCE_OWNER`. Requests are born `DRAFT`, and opening moves `DRAFT` → `OPEN` — from any other state, `ERR_REQUEST_INVALID_STATE`. The request's `slots_filled` starts at zero and is maintained incrementally under a standing invariant: at all times, `slots_filled` equals the count of this request's placements in `ACCEPTED`.

With a request `OPEN`, a coordinator offers a placement by creating one with `request_id`, `volunteer_id`, and an optional `offer_note`; the placement lands `OFFERED`. The volunteer must be `ONBOARDING` or `ACTIVE` (`ERR_VOLUNTEER_INVALID_STATE`) with a posture other than `FROZEN` (`ERR_POSTURE_FROZEN`). One volunteer may hold only one live placement per request — a second offer while one stands `OFFERED`, `COUNTERED`, or `ACCEPTED` is `ERR_DUPLICATE_PLACEMENT`. Minor protection applies at offer time, evaluated as of the offer date: a volunteer younger than the role's `minimum_age` is rejected with `ERR_ROLE_MIN_AGE_NOT_MET`, and a junior may not be offered into a department whose `junior_allowed` is false (`ERR_DEPARTMENT_JUNIOR_RESTRICTED`).

Acceptance is the volunteer's call — the `Volunteer` role acting on their own placement, or a coordinator acting on their behalf. Five gates stand in front of it. The placement must be `OFFERED` (`ERR_PLACEMENT_INVALID_STATE`); the volunteer must be `ONBOARDING` or `ACTIVE` (`ERR_VOLUNTEER_INVALID_STATE`); posture must not be `FROZEN` (`ERR_POSTURE_FROZEN`); the minor-protection gates of the offer are re-evaluated at acceptance (`ERR_ROLE_MIN_AGE_NOT_MET`, `ERR_DEPARTMENT_JUNIOR_RESTRICTED`); and the volunteer must hold fewer than two `ACCEPTED` placements already — a third concurrent acceptance is `ERR_PLACEMENT_LIMIT_EXCEEDED`. The request check has a pinned evaluation order: the request must be `OPEN` (`ERR_REQUEST_NOT_OPEN`) **evaluated against the pre-increment `slots_filled`**, so a request one acceptance away from full is still open for this acceptance; only then does `slots_filled` increment by one; and only then, if `slots_filled` has reached `slots_needed`, does the request auto-transition `OPEN` → `FILLED`, stamping `filled_at` from the clock. The placement itself stamps `accepted_at`.

Rather than accept or walk away, the volunteer may counter. The placement's own volunteer — and only that volunteer — moves `OFFERED` → `COUNTERED`, recording a `counter_note` and incrementing `counter_rounds`. Negotiation is bounded: once `counter_rounds` reaches 2, a further counter attempt is rejected with `ERR_COUNTER_ROUND_EXHAUSTED`. The department answers through its head: a reoffer moves `COUNTERED` back to `OFFERED`, records a fresh `offer_note`, and requires the request still `OPEN` (`ERR_REQUEST_NOT_OPEN`); the head must own the requesting department (`ERR_NOT_RESOURCE_OWNER`). Declining is available from `OFFERED` or `COUNTERED` and lands the placement in the terminal `DECLINED`. The loop `OFFERED` → `COUNTERED` → `OFFERED` is the negotiation cycle, bounded by the two-counter budget.

Any non-terminal placement — `OFFERED`, `COUNTERED`, or `ACCEPTED` — can be rescinded by a coordinator or by the head of the requesting department, optionally carrying a `reason`; the placement lands in the terminal `RESCINDED` with `rescinded_at` stamped. Rescinding an `ACCEPTED` placement is a compensating action: `slots_filled` decrements by one first, and if the request was `FILLED` it auto-reverts to `OPEN` with `filled_at` cleared. The one exception is when the rescission is part of the request's own cancellation cascade, where the request lands `CANCELLED` regardless of the transient flip.

The request itself has two soft landings and one hard one. A department head closes an `OPEN` or `FILLED` request — from anything else, `ERR_REQUEST_INVALID_STATE` — which rescinds the placements still `OFFERED` or `COUNTERED` while leaving `ACCEPTED` placements untouched, and the request lands `CLOSED`. Cancellation, available to the head or the director from `OPEN` or `FILLED`, is heavier: every non-terminal placement, `ACCEPTED` included, is rescinded with per-acceptance slot compensation, and the request lands `CANCELLED` no matter how the transient counts flip. `CLOSED` and `CANCELLED` are terminal. The inverse flip is automatic in the other direction as well: any compensating decrement that drops a `FILLED` request's `slots_filled` below `slots_needed` returns it to `OPEN` and clears `filled_at`, unless the decrement belongs to the request's own cancellation.

### 3.4. The Volunteer Service Lifecycle: Training, Activation, Badges, Suspension, and Separation

A volunteer record holds `full_name`, `date_of_birth`, `email`, `phone`, and coordinator `notes`. Of these, the contact and profile fields — `full_name`, `email`, `phone`, and `notes` — are editable later by a coordinator through the profile update, one of the three OCC-guarded writes of §2.7, carrying `expected_volunteer_version`; `date_of_birth` is fixed at creation, since every age rule in the system reads it. Alongside the profile fields sit system and derived fields: `service_status` (the state machine of this section), `compliance_posture` (§2.9), `total_service_hours` and `recognition_points` and `recognition_tier` (§3.6 — all three start at zero or `NONE`), `joined_at`, `current_service_year_start`, and the separation and suspension bookkeeping fields. `current_service_year_start` is the most recent anniversary of `joined_at` that is on or before today's logical-clock date — the `joined_at` date itself while the first year is still incomplete. `is_junior_today` is true exactly when the volunteer's age at today's date is under 18.

Age arithmetic is calendar-precise. Age at a date is the whole years between `date_of_birth` and that date, with a birthday falling on the date counting as reached — a volunteer whose 18th birthday is the shift's start date is an adult for that shift. "Junior" always means under 18 at the relevant date: the offer date for placements, the shift's start date for signup, confirmation, and supervision, today's date for `is_junior_today`, and the service-year-end date at annual review.

Training runs on records a coordinator creates with `volunteer_id`, a `training_code` such as `ORIENTATION`, `HIPAA_ANNUAL`, or `SAFETY_ANNUAL`, and a `recurrence` of `ONE_TIME` or `ANNUAL`. New records are `PENDING`. Completion — allowed from `PENDING` or `EXPIRED`, and rejected from anywhere else with `ERR_TRAINING_RECORD_INVALID_STATE` — stamps `completed_at` from the logical clock; for an `ANNUAL` record it also sets `expires_at` twelve calendar months after completion, while a `ONE_TIME` record's `expires_at` stays null forever. Completing an `EXPIRED` record is the recertification cycle. The annual-review sweep flips a `VALID` `ANNUAL` record whose `expires_at` is at or before now to `EXPIRED`.

Activation turns an onboarding volunteer into a working one, and it is gated hard. A coordinator may activate only an `ONBOARDING` volunteer (`ERR_VOLUNTEER_INVALID_STATE`). Beyond the state gate, four requirements stand: the `ORIENTATION` training record exists and is `VALID` (`ERR_ORIENTATION_INCOMPLETE`); for each of the three clearance types, the volunteer's latest-created clearance of that type is `CLEARED` with `expires_at` strictly after now (`ERR_CLEARANCE_REQUIREMENTS_UNMET`); at least one placement stands `ACCEPTED` (`ERR_NO_ACCEPTED_PLACEMENT`); and a badge in `PENDING` exists for the volunteer (`ERR_BADGE_INVALID_STATE`). Success flips `service_status` to `ACTIVE`, issues the badge — `PENDING` → `ISSUED`, with `issued_at` stamped — and bumps the volunteer's `version`.

Suspension freezes a volunteer out of service without unwinding their commitments. A coordinator or the director suspends an `ACTIVE` volunteer (`ERR_VOLUNTEER_INVALID_STATE` from any other state), supplying a `reason`; `suspension_reason` records `MANUAL` for a manual suspension, while the annual review of §3.6 sets `COMPLIANCE_LAPSE` or `HOURS_SHORTFALL`. The volunteer's `ISSUED` badge flips to `SUSPENDED`, and the volunteer's `version` bumps. Existing shift assignments are deliberately **not** cancelled by suspension — the contrast with the posture-freeze cascade of §3.2 is intentional, since a suspension is expected to be cured. Reinstatement returns a `SUSPENDED` volunteer to `ACTIVE`, but only once the underlying lapse is cured: a volunteer whose posture is `FROZEN` cannot be reinstated (`ERR_POSTURE_FROZEN`). Success flips the `SUSPENDED` badge back to `ISSUED`, clears `suspension_reason`, and bumps `version`.

Badges deserve their own paragraph because they are the audit anchor. Every badge carries a server-minted `badge_number`: the literal prefix `BDG-` followed by a six-digit zero-padded sequence equal to one plus the count of badge rows ever created. Numbers are deterministic by creation order, are never reused even after revocation, and are never derived from the badge's `id`. Exactly one badge per volunteer exists in `PENDING`, `ISSUED`, or `SUSPENDED` at any moment. Beyond the lifecycle flips above, a coordinator may revoke a live badge directly — the request carries a `reason`, `revoked_at` is stamped, and `revoke_reason` records `MANUAL`; acting on a badge that is not in one of the three live states is `ERR_BADGE_INVALID_STATE`. Replacement handles the lost-badge case against an `ACTIVE` volunteer: the request, again carrying a `reason`, drives the volunteer's live badge — `ISSUED` or `SUSPENDED` — to `REVOKED` with `revoke_reason` `LOST_REPLACED` and mints a brand-new badge directly in `ISSUED` bearing the next sequential `badge_number`, returning the new badge. The revoked row stays `REVOKED` forever; `REVOKED` is terminal.

Separation is the director's heaviest cascade, available from `ONBOARDING`, `ACTIVE`, or `SUSPENDED` — from anywhere else, `ERR_VOLUNTEER_INVALID_STATE`. The request carries a `separation_reason` of `VOLUNTARY`, `INVOLUNTARY`, `DECEASED`, `MOVED`, or `OTHER`, plus optional `notes`. Its effects land atomically within the request. The volunteer's badge, whatever its live state (`PENDING`, `ISSUED`, or `SUSPENDED`), is `REVOKED` with `revoke_reason` `SEPARATION`. Every assignment of the volunteer in `SIGNED_UP`, `CONFIRMED`, or `WAITLISTED` whose shift starts after now is cancelled, and each such cancellation on a `PUBLISHED` shift runs the waitlist promotion of §3.5. Every placement in `OFFERED` or `COUNTERED` is rescinded. Every placement in `ACCEPTED` is rescinded with slot compensation: its request's `slots_filled` decrements by one, and a request that was `FILLED` reverts to `OPEN` with `filled_at` cleared. Finally `separated_at` is stamped from the clock, `separation_reason` is recorded, and the volunteer's `version` bumps. `SEPARATED` is semi-terminal: the only exit is the reapply-and-approve path of §3.1, which returns the volunteer to `ONBOARDING` with `joined_at` reset and the separation and suspension fields cleared.

### 3.5. Shift Scheduling, Signup, Waitlists, and Junior Supervision

A coordinator schedules a shift with `department_id`, `role_id`, `start_at` and `end_at` in ISO 8601 UTC — the start must be strictly before the end — a `capacity` of at least 1 (the maximum number of assignments allowed in `SIGNED_UP` or `CONFIRMED`), and `allow_waitlist`, which defaults to false. Shifts are born `SCHEDULED` with `filled_count` zero; the shift list can be filtered by `department_id`, `role_id`, or `status`. Publication moves `SCHEDULED` → `PUBLISHED`, and from any other state the attempt is `ERR_SHIFT_INVALID_STATE`.

A shift can be rescheduled or resized only while it has no live assignments and only from `SCHEDULED` or `PUBLISHED`. Any assignment in `WAITLISTED`, `SIGNED_UP`, or `CONFIRMED` blocks the update with `ERR_SHIFT_HAS_ASSIGNMENTS`; a shift in any other state draws `ERR_SHIFT_INVALID_STATE`. The update is the shift's OCC-guarded write (§2.7): it carries `expected_shift_version`, accepts optional new `start_at`, `end_at`, and `capacity` values, and bumps the shift's `version`.

Signup — by the volunteer themself or by a coordinator — names `shift_id` and `volunteer_id` and runs the full gate stack in the validation order of §2.8. The shift must be `PUBLISHED` (`ERR_SHIFT_INVALID_STATE`). The volunteer must be `ACTIVE` (`ERR_VOLUNTEER_INVALID_STATE`) with a posture other than `FROZEN` (`ERR_POSTURE_FROZEN`). Signup closes 24 hours before the shift starts: now must be strictly earlier than `start_at` minus 24 hours, and at or after that cutoff the signup is `ERR_SIGNUP_WINDOW_CLOSED`. The volunteer's age at the shift's start date must meet the role's `minimum_age` (`ERR_ROLE_MIN_AGE_NOT_MET`), and a junior at that date may not sign up into a department whose `junior_allowed` is false (`ERR_DEPARTMENT_JUNIOR_RESTRICTED`). No duplicate assignment may exist for the same volunteer and shift in `WAITLISTED`, `SIGNED_UP`, or `CONFIRMED` (`ERR_DUPLICATE_SHIFT_ASSIGNMENT`). And the new shift's window may not half-open-overlap the volunteer's other `SIGNED_UP` or `CONFIRMED` shifts (`ERR_SHIFT_TIME_OVERLAP`) — adjacency, where one shift's end equals the other's start, is allowed.

Juniors carry a weekly workload cap, evaluated at signup whenever the volunteer is junior at the shift's start date. Take the ISO week containing the shift's start — Monday 00:00:00Z inclusive through the following Monday 00:00:00Z exclusive. Sum the durations of the volunteer's shifts whose assignments stand `SIGNED_UP` or `CONFIRMED` with shift starts inside that week; `WAITLISTED` assignments are not counted, because a waitlist seat is not an occupation. Add the new shift's duration — the difference between `end_at` and `start_at` in minutes, divided by 60, at two decimal places. If the projection exceeds 16.0 hours, the signup is rejected with `ERR_JUNIOR_WEEKLY_HOUR_CAP_EXCEEDED`; a projection of exactly 16.0 hours is allowed.

Capacity decides the landing state. While `filled_count` is below `capacity`, the assignment lands `SIGNED_UP`, `signed_up_at` is stamped from the logical clock, and `filled_count` increments by one. When the shift is full, a shift with `allow_waitlist` true accepts the assignment as `WAITLISTED`; a shift without it rejects the signup with `ERR_SHIFT_AT_CAPACITY`. The assignment list can be filtered by `shift_id`, `volunteer_id`, `supervisor_assignment_id`, or `status`.

Waitlist promotion is the fairness mechanism. Whenever a `SIGNED_UP` or `CONFIRMED` assignment on a `PUBLISHED` shift is cancelled — by manual cancellation, by the separation cascade, or by the posture-freeze cascade — the server looks at the shift's `WAITLISTED` rows. Eligible candidates are those whose volunteer is `ACTIVE`, whose posture is not `FROZEN`, and whose other `SIGNED_UP` or `CONFIRMED` assignments do not half-open-overlap this shift. The earliest-created eligible candidate wins; an ineligible top candidate is skipped in favor of the next eligible one; and if nobody qualifies, the slot simply stays open — finding no one to promote is not an error. Promotion flips the chosen row to `SIGNED_UP`, stamps `signed_up_at` at promotion time, and increments `filled_count`. Selection is deterministic and never orders by volunteer id.

Confirmation is the coordinator's final gate before service, moving `SIGNED_UP` → `CONFIRMED` — any other assignment state is `ERR_ASSIGNMENT_INVALID_STATE`. The volunteer must be `ACTIVE` (`ERR_VOLUNTEER_INVALID_STATE`); posture must be fully `CLEAR`, since `RESTRICTED` is not good enough for confirmed service (`ERR_POSTURE_NOT_CLEAR`); and the volunteer must hold an `ISSUED` badge (`ERR_BADGE_INVALID_STATE`). Every code in the shift role's `required_training_codes` must have a `VALID` training record for the volunteer (`ERR_TRAINING_REQUIREMENT_UNMET`). When the assignee is a junior at the shift's start date, supervision rules engage: the request must carry `supervisor_assignment_id` (`ERR_SUPERVISION_REQUIRED`), and that identifier must reference a `CONFIRMED` assignment on the same shift whose volunteer is at least 21 years old at the shift date and whose role has `can_supervise_juniors` true (`ERR_SUPERVISOR_INELIGIBLE`); counting this confirmation, that supervisor may not exceed three junior supervisees on the shift (`ERR_SUPERVISOR_RATIO_EXCEEDED`). Success stamps `confirmed_at` from the clock and stores the `supervisor_assignment_id` when one was provided.

Cancellation is open from `SIGNED_UP`, `CONFIRMED`, or `WAITLISTED` — anything else is `ERR_ASSIGNMENT_INVALID_STATE`. A volunteer cancelling their own assignment faces the same 24-hour window as signup: now must be strictly earlier than `start_at` minus 24 hours, or the attempt is `ERR_CANCEL_WINDOW_CLOSED`; staff roles bypass the window. Cancelling a `SIGNED_UP` or `CONFIRMED` assignment decrements `filled_count` and, on a `PUBLISHED` shift, runs waitlist promotion. Cancelling a `WAITLISTED` row changes no count and triggers no promotion.

Two transitions close a shift out. Cancellation — from `SCHEDULED` or `PUBLISHED`, else `ERR_SHIFT_INVALID_STATE` — lands the shift in `CANCELLED` and, when the shift was published, cancels every assignment in `WAITLISTED`, `SIGNED_UP`, or `CONFIRMED` with no waitlist promotion: the shift itself is gone, so there is nothing to promote into. Completion reconciles attendance after service: the shift must be `PUBLISHED` (`ERR_SHIFT_INVALID_STATE`), and now must be at or past `end_at` (`ERR_SHIFT_NOT_ENDED`). On completion, each `CONFIRMED` assignment with no `APPROVED` hour entry referencing it flips to `NO_SHOW`, feeding the two-hour service-year penalty of §3.6, and each `SIGNED_UP` or `WAITLISTED` assignment is cancelled outright — again with no promotion, because the shift is over. `COMPLETED` and `CANCELLED` are terminal for a shift, as are `COMPLETED`, `NO_SHOW`, and `CANCELLED` for an assignment. The one remaining assignment transition lives in §3.6: approving an hour entry that references a `CONFIRMED` assignment flips it to `COMPLETED`.

### 3.6. Hour Logging, Recognition, and the Annual Compliance Review

Hours are logged against a volunteer by the volunteer themself or by a coordinator, in an entry carrying `volunteer_id`, `service_date`, `minutes` between 1 and 960, a `service_category` drawn from the five role categories, optional `notes`, and an optional `shift_assignment_id` linking the entry to a confirmed assignment. The volunteer must be `ACTIVE` or `SUSPENDED` (`ERR_VOLUNTEER_INVALID_STATE`) — a suspended volunteer can still bank hours already worked. The `service_date` may not lie in the future and may not precede the volunteer's `joined_at` date (`ERR_SERVICE_DATE_OUT_OF_RANGE`). When a link is present, three more rules engage: the linked assignment must belong to the same volunteer (`ERR_ASSIGNMENT_OWNERSHIP_MISMATCH`); the entry's `service_date` must equal the linked shift's calendar date (also `ERR_SERVICE_DATE_OUT_OF_RANGE`); and `minutes` may not exceed the shift's duration in minutes (`ERR_HOURS_EXCEED_SHIFT`). A linked entry's supplied `service_category` is ignored — the server copies the shift role's category instead. Entries are born `PENDING`.

Approval is a coordinator action and the third OCC-guarded write of §2.7: the request carries `expected_volunteer_version`, because approval mutates the volunteer's derived totals, and a stale pin is `ERR_STALE_VERSION`. Only a `PENDING` entry is approvable (`ERR_HOUR_ENTRY_INVALID_STATE`). Approval adds the entry's hours — `minutes` divided by 60, at two decimal places — into `total_service_hours`; adds the weighted recognition points described below into `recognition_points` and recomputes `recognition_tier`, appending a recognition event if the tier rose; stamps `approved_at`; bumps the volunteer's `version`; and, when the entry references a `CONFIRMED` assignment, flips that assignment to `COMPLETED`.

Rejection is the quiet path: a `PENDING` entry (`ERR_HOUR_ENTRY_INVALID_STATE` otherwise) plus a mandatory `decision_reason` (omitting it is `ERR_INVALID_REQUEST`) lands the entry in the terminal `REJECTED`. Reversal is the compensating path for an `APPROVED` entry — again `ERR_HOUR_ENTRY_INVALID_STATE` from any other state, again requiring a `decision_reason`. Reversal subtracts from `total_service_hours` exactly the hours that approval added, subtracts from `recognition_points` exactly the same per-entry rounded points that approval added, and recomputes the tier, appending a `TIER_DECREASED` recognition event if it fell. One asymmetry is documented and deliberate: the linked assignment is **not** reverted out of `COMPLETED`. `REVERSED` is terminal.

Recognition points are category-weighted. Each `APPROVED` entry contributes its hours — `minutes` over 60 — multiplied by the category multiplier: 1.5 for `PATIENT_FACING`, 1.2 for `FUNDRAISING`, 1.0 for `GIFT_SHOP`, 1.0 for `COMMUNITY`, and 0.8 for `CLERICAL`. The per-entry product is rounded half-up to two decimal places **first**, and `recognition_points` is then the exact sum of those rounded per-entry values. The rounding order is pinned: per-entry first, then sum. Summing raw products and rounding once at the end is a different, non-conforming algorithm — three 25-minute `CLERICAL` entries contribute 0.33 + 0.33 + 0.33 = 0.99 points under the pinned order, where sum-then-round would yield 1.00. Only `APPROVED` entries count; `PENDING`, `REJECTED`, and `REVERSED` entries are excluded. `total_service_hours` is the unweighted companion over the same input set — the sum of `minutes` over `APPROVED` entries, divided by 60, at two decimal places — and the two figures disagree whenever any entry carries a multiplier other than 1.0.

The `recognition_tier` recomputes after every points change — approval, reversal, or the annual-review sweep — against inclusive thresholds: `PRESIDENT` at 1000.00 points or more, `GOLD` at 600.00 or more, `SILVER` at 300.00 or more, `BRONZE` at 100.00 or more (exactly 100.00 is `BRONZE`), and `NONE` below that. A tier change appends a row to the recognition event log recording `volunteer_id`, an `event_type` of `TIER_INCREASED` or `TIER_DECREASED`, the `tier` moved into, and a `points_snapshot` holding `recognition_points` at that instant to two decimal places. The log is append-only (§2.5) and can be listed filtered by `volunteer_id`.

Service years anchor to `joined_at`. A volunteer's first service year begins on the `joined_at` date (inclusive) and runs to its first anniversary (exclusive); each subsequent year runs from one anniversary of `joined_at`, inclusive, to the next, exclusive. The service-year hours figure is computed in a pinned order. First, approved hours: the sum of `minutes` over the volunteer's `APPROVED` entries whose `service_date` falls inside the window — start inclusive, end exclusive — divided by 60. Second, the penalty: 2.0 hours for each of the volunteer's `NO_SHOW` assignments whose shift's `end_at` falls inside the same window. Third, the difference, floored at zero so the figure never goes negative. Annual minimums are evaluated against the volunteer's age at the year-end date: an adult — 18 or older at that date — owes 100.0 hours for the completed year; a junior owes 40.0. The volunteer summary read exposes the current service year's figure as `service_year_hours`, alongside `compliance_posture`, `total_service_hours`, `recognition_points`, `recognition_tier`, `is_junior_today`, the `accepted_placement_count`, and the `live_badge_status`.

Once per compliance epoch, the director runs the **annual review** — an ops-run checkpoint that is idempotent at a fixed logical clock. Four sweeps execute atomically in one request. Every `CLEARED` clearance whose `expires_at` is at or before now flips to `EXPIRED`. Every `VALID` `ANNUAL` training record whose `expires_at` is at or before now flips to `EXPIRED`. Every `ACTIVE` volunteer whose posture is now `FROZEN` is suspended with `suspension_reason` `COMPLIANCE_LAPSE`, badge flipping `ISSUED` → `SUSPENDED`. And every `ACTIVE` volunteer whose most recently completed service year fell below the age-appropriate minimum is suspended with `suspension_reason` `HOURS_SHORTFALL`, with the same badge cascade. Recognition tiers are then recomputed, appending recognition events wherever a tier moved. The response reports four counts: `clearances_expired`, `trainings_expired`, `volunteers_suspended`, and `recognition_events_created`.

### 3.7. Gift Shop Catalog and Point of Sale

The treasurer maintains the gift shop catalog. An item carries a unique `sku`, a `name`, a `unit_price_cents` of zero or more, a `unit_cost_cents` of zero or more and never above the price, a `stock_on_hand` that defaults to zero and never goes negative, a `reorder_level` restock hint that defaults to zero and is informational only, and an `is_active` flag defaulting to true. Catalog updates can change the price, restock — a `restock_qty` in the update adds to `stock_on_hand` — adjust `reorder_level`, or toggle `is_active`. An inactive item cannot be sold (`ERR_ITEM_INACTIVE`) but remains queryable, and the item list can be filtered by `is_active`, which is how the soft-disable stays reversible.

Ringing a sale is a staff action by the treasurer, or a self-service action by a volunteer acting as their own cashier. The request names `cashier_volunteer_id`, the `lines` being bought, and `tendered_cents`, with optional `buyer_volunteer_id` and `campaign_id`. The cashier must be an `ACTIVE` volunteer holding an `ACCEPTED` placement whose role category is `GIFT_SHOP` (`ERR_CASHIER_NOT_GIFT_SHOP_PLACED`). Each line pairs an `item_id` with a `qty` of at least 1, and the sale must contain at least one line; a line quantity above the item's `stock_on_hand` fails with `ERR_INSUFFICIENT_STOCK`.

Discounts never stack — the single largest eligible candidate wins, and the winner is recorded as `discount_pct_applied`. Three candidates compete. The tier discount applies when the buyer is a volunteer, scaled by the buyer's `recognition_tier`: 5 percent for `BRONZE`, 10 for `SILVER`, 15 for `GOLD`, 20 for `PRESIDENT`, and nothing otherwise. The junior discount is 5 percent, applying when the buyer is a volunteer and junior today. The promotional discount is the attributed campaign's `promo_discount_pct`, applying when `campaign_id` is present. A null `buyer_volunteer_id` means a public sale — no tier or junior candidate is even considered. Attribution itself is only valid into an `ACTIVE` campaign (`ERR_CAMPAIGN_INVALID_STATE`) whose window currently contains now — `start_at` at or before now and now strictly before `end_at` (`ERR_CAMPAIGN_WINDOW_MISMATCH`).

Totals are computed per line and rounded per line. Each line amounts to its quantity times the item's `unit_price_cents`, scaled by the winning discount — multiplied by 100 minus the discount percent, then divided by 100 — rounded half-up to whole cents; `total_cents` is the sum of the rounded line amounts. `tendered_cents` must cover the total (`ERR_INSUFFICIENT_TENDER`), and `change_cents` is the tendered amount minus the total. The sale lands `COMPLETED`; each line decrements its item's `stock_on_hand` by the line quantity, and an attributed sale feeds the campaign totals of §3.8.

A completed sale can be voided by the treasurer or a coordinator, but only within 24 hours of its creation — after that, `ERR_VOID_WINDOW_ELAPSED` — and only while it stands `COMPLETED` (a repeat void is `ERR_SALE_ALREADY_VOIDED`). The request must carry a `void_reason` (`ERR_INVALID_REQUEST` without one); the server stamps `voided_at` and records the caller as `voided_by_user_id`. Voiding restores each line's quantity to its item's `stock_on_hand` — the exact compensation of the sale — and, for an attributed sale, subtracts the sale's `total_cents` from the campaign's `raised_cents` and the sale's margin (total minus the lines' cost of goods) from `net_proceeds_cents`. The campaign's `gross_receipts_cents` — the everything-ever-rung figure — is deliberately left unchanged by a void. `VOIDED` is terminal.

### 3.8. Fundraising Campaigns, Proceeds, and Disbursements

Fundraising campaigns belong to the treasurer. Creation names the campaign (`name`), sets a `goal_cents` target of zero or more, fixes the window — `start_at` inclusive, `end_at` exclusive, with the end strictly after the start — and optionally a `promo_discount_pct` between 0 and 50 inclusive, defaulting to 0. The creator's `X-User-ID` is recorded as `created_by_user_id`, which later anchors the disbursement segregation of duties, and the campaign is born `DRAFT`. Activation moves `DRAFT` → `ACTIVE` and is only valid inside the window — `start_at` at or before now, and now strictly before `end_at` — otherwise `ERR_CAMPAIGN_WINDOW_MISMATCH`; a campaign not in `DRAFT` draws `ERR_CAMPAIGN_INVALID_STATE`. Closing requires the campaign `ACTIVE` and now at or past `end_at`, and stamps `closed_at` from the clock. Reconciliation moves `CLOSED` → `RECONCILED`, the terminal state.

Four computed figures track campaign money, and they answer different questions. `gross_receipts_cents` sums `total_cents` over every attributed sale, voided ones included — the audit view of everything ever rung for the campaign. `raised_cents` sums `total_cents` over attributed sales in `COMPLETED` only — voids excluded. `net_proceeds_cents` is `raised_cents` minus the cost of goods of the non-voided attributed lines, where each line contributes its quantity times its item's `unit_cost_cents`. `disbursed_cents` accumulates completed disbursements. For identical data, gross is never below raised and raised is never below net, and all three differ whenever a void or a nonzero cost exists; the disbursement capacity is `net_proceeds_cents` minus `disbursed_cents`.

Disbursement pays money out of a `RECONCILED` campaign — any other state is `ERR_CAMPAIGN_INVALID_STATE` — under three guards. The cooling-off period: now must be at least seven days after `closed_at`, or the request is `ERR_DISBURSEMENT_COOLING_OFF`. Segregation of duties: the disbursing treasurer's `X-User-ID` must differ from the campaign's `created_by_user_id`, or the request is `ERR_SOD_CAMPAIGN_DISBURSEMENT`. Capacity: `amount_cents` may not exceed `net_proceeds_cents` minus `disbursed_cents`, or the request is `ERR_DISBURSEMENT_EXCEEDS_BALANCE`. The request names `amount_cents` and `recipient`, with optional `notes`; success adds the amount into `disbursed_cents`, and the campaign can be disbursed repeatedly until the net proceeds are exhausted.

## 4. Endpoint Definitions

All endpoints are mounted at the paths shown; the business semantics of each are specified in §2 and §3, and this table is a locator and authorization reference only. Creating a new resource returns HTTP 201 with the created resource in `data`; reads, modifications, and action-style state transitions return HTTP 200 with the affected resource. Failures carry the error codes of §5 under the precedence order of §2.8.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the server's logical clock (§2.4); returns the resulting `current_utc` | VolunteerServicesDirector, VolunteerCoordinator, Screener, DepartmentHead, AuxiliaryTreasurer |
| POST | /auxiliary/volunteer-applications | Intake a volunteer application (lands `SUBMITTED`) | VolunteerCoordinator, VolunteerServicesDirector |
| GET | /auxiliary/volunteer-applications | List applications; filter by `status`, `volunteer_id` | VolunteerServicesDirector, VolunteerCoordinator, Screener |
| GET | /auxiliary/volunteer-applications/{id} | Get one application | VolunteerServicesDirector, VolunteerCoordinator, Screener |
| POST | /auxiliary/volunteer-applications/{id}/start-review | Move `SUBMITTED` → `IN_REVIEW` | VolunteerCoordinator |
| POST | /auxiliary/volunteer-applications/{id}/request-info | Move `IN_REVIEW` → `NEEDS_INFO`, recording `info_request_note` | VolunteerCoordinator |
| POST | /auxiliary/volunteer-applications/{id}/resubmit | Move `NEEDS_INFO` → `IN_REVIEW` | VolunteerCoordinator |
| POST | /auxiliary/volunteer-applications/{id}/decide | Director decision: `APPROVE` (creates/reactivates volunteer, badge, orientation record) or `REJECT` | VolunteerServicesDirector |
| POST | /auxiliary/volunteer-applications/{id}/withdraw | Move `SUBMITTED`/`IN_REVIEW`/`NEEDS_INFO` → `WITHDRAWN` | VolunteerCoordinator |
| GET | /auxiliary/volunteers | List volunteers; filter by `service_status`, `compliance_posture`, `recognition_tier` | VolunteerServicesDirector, VolunteerCoordinator, Screener, DepartmentHead, AuxiliaryTreasurer |
| GET | /auxiliary/volunteers/{id} | Get one volunteer (`Volunteer` role: self only) | VolunteerServicesDirector, VolunteerCoordinator, Screener, DepartmentHead, AuxiliaryTreasurer, Volunteer |
| GET | /auxiliary/volunteers/{id}/summary | Computed read: posture, hours, points, tier, counts (§3.6) | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| PUT | /auxiliary/volunteers/{id} | Update volunteer profile; OCC via `expected_volunteer_version` | VolunteerCoordinator |
| POST | /auxiliary/volunteers/{id}/activate | Move `ONBOARDING` → `ACTIVE`; issues the `PENDING` badge | VolunteerCoordinator |
| POST | /auxiliary/volunteers/{id}/suspend | Move `ACTIVE` → `SUSPENDED` (manual; badge suspends too) | VolunteerCoordinator, VolunteerServicesDirector |
| POST | /auxiliary/volunteers/{id}/reinstate | Move `SUSPENDED` → `ACTIVE`; requires posture not `FROZEN` | VolunteerCoordinator, VolunteerServicesDirector |
| POST | /auxiliary/volunteers/{id}/separate | Move to `SEPARATED`; deep cascade (badge revoke, assignment cancel + promotion, placement rescind + request reopen) | VolunteerServicesDirector |
| POST | /auxiliary/volunteers/{id}/reapply | Create a reapply-linked application (`SUBMITTED`) for a `SEPARATED` volunteer | VolunteerCoordinator |
| POST | /auxiliary/clearances | Submit clearance evidence (lands `SUBMITTED`); one non-terminal record per volunteer-and-type | Screener, VolunteerCoordinator |
| GET | /auxiliary/clearances | List clearances; filter by `volunteer_id`, `clearance_type`, `status` | VolunteerServicesDirector, VolunteerCoordinator, Screener, Volunteer |
| GET | /auxiliary/clearances/{id} | Get one clearance | VolunteerServicesDirector, VolunteerCoordinator, Screener |
| POST | /auxiliary/clearances/{id}/adjudicate | Move `SUBMITTED` → `CLEARED` (sets `expires_at`) or `REJECTED`; adjudicator differs from submitter | Screener |
| POST | /auxiliary/clearances/{id}/resubmit | Move `REJECTED`/`EXPIRED` → `SUBMITTED` on the same record | Screener, VolunteerCoordinator |
| POST | /auxiliary/clearances/{id}/revoke | Move `CLEARED` → `REVOKED`; posture-freeze cascade cancels future assignments and promotes waitlists | Screener, VolunteerServicesDirector |
| POST | /auxiliary/departments | Create a department | VolunteerServicesDirector |
| GET | /auxiliary/departments | List departments | VolunteerServicesDirector, VolunteerCoordinator, Screener, DepartmentHead, AuxiliaryTreasurer, Volunteer |
| GET | /auxiliary/departments/{id} | Get one department | VolunteerServicesDirector, VolunteerCoordinator, Screener, DepartmentHead, AuxiliaryTreasurer, Volunteer |
| POST | /auxiliary/volunteer-roles | Create a volunteer role | VolunteerServicesDirector |
| GET | /auxiliary/volunteer-roles | List volunteer roles | VolunteerServicesDirector, VolunteerCoordinator, Screener, DepartmentHead, AuxiliaryTreasurer, Volunteer |
| GET | /auxiliary/volunteer-roles/{id} | Get one volunteer role | VolunteerServicesDirector, VolunteerCoordinator, Screener, DepartmentHead, AuxiliaryTreasurer, Volunteer |
| POST | /auxiliary/department-requests | Create a staffing request (lands `DRAFT`); caller must head the department | DepartmentHead |
| GET | /auxiliary/department-requests | List requests; filter by `department_id`, `role_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead |
| GET | /auxiliary/department-requests/{id} | Get one request | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead |
| POST | /auxiliary/department-requests/{id}/open | Move `DRAFT` → `OPEN` | DepartmentHead |
| POST | /auxiliary/department-requests/{id}/close | Move `OPEN`/`FILLED` → `CLOSED`; open offers rescinded | DepartmentHead |
| POST | /auxiliary/department-requests/{id}/cancel | Move `OPEN`/`FILLED` → `CANCELLED`; all non-terminal placements rescinded with slot compensation | DepartmentHead, VolunteerServicesDirector |
| POST | /auxiliary/placements | Offer a placement against an `OPEN` request (lands `OFFERED`) | VolunteerCoordinator |
| GET | /auxiliary/placements | List placements; filter by `request_id`, `volunteer_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead, Volunteer |
| GET | /auxiliary/placements/{id} | Get one placement | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead, Volunteer |
| POST | /auxiliary/placements/{id}/accept | Move `OFFERED` → `ACCEPTED`; slot-fill evaluation (pre-increment `OPEN` check, then increment, then maybe `FILLED`) | Volunteer, VolunteerCoordinator |
| POST | /auxiliary/placements/{id}/decline | Move `OFFERED`/`COUNTERED` → `DECLINED` | Volunteer, VolunteerCoordinator |
| POST | /auxiliary/placements/{id}/counter | Move `OFFERED` → `COUNTERED` (two-round budget) | Volunteer |
| POST | /auxiliary/placements/{id}/reoffer | Move `COUNTERED` → `OFFERED`; caller must head the request's department | DepartmentHead |
| POST | /auxiliary/placements/{id}/rescind | Move `OFFERED`/`COUNTERED`/`ACCEPTED` → `RESCINDED`; `ACCEPTED` rescind decrements slots and may reopen a `FILLED` request | VolunteerCoordinator, DepartmentHead |
| POST | /auxiliary/training-records | Enroll a volunteer in a training code (lands `PENDING`) | VolunteerCoordinator |
| GET | /auxiliary/training-records | List training records; filter by `volunteer_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| GET | /auxiliary/training-records/{id} | Get one training record | VolunteerServicesDirector, VolunteerCoordinator |
| POST | /auxiliary/training-records/{id}/complete | Move `PENDING`/`EXPIRED` → `VALID`; `ANNUAL` sets `expires_at` twelve months out | VolunteerCoordinator |
| POST | /auxiliary/shifts | Create a shift (lands `SCHEDULED`) | VolunteerCoordinator |
| GET | /auxiliary/shifts | List shifts; filter by `department_id`, `role_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead, Volunteer |
| GET | /auxiliary/shifts/{id} | Get one shift | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead, Volunteer |
| PUT | /auxiliary/shifts/{id} | Reschedule/resize a shift with zero live assignments; OCC via `expected_shift_version` | VolunteerCoordinator |
| POST | /auxiliary/shifts/{id}/publish | Move `SCHEDULED` → `PUBLISHED` | VolunteerCoordinator |
| POST | /auxiliary/shifts/{id}/cancel | Move `SCHEDULED`/`PUBLISHED` → `CANCELLED`; cancels live assignments without promotion | VolunteerCoordinator |
| POST | /auxiliary/shifts/{id}/complete | Move `PUBLISHED` → `COMPLETED` after `end_at`; no-show reconciliation | VolunteerCoordinator |
| POST | /auxiliary/shift-assignments | Sign up (lands `SIGNED_UP`, or `WAITLISTED` when full and waitlist-enabled); full gate stack of §3.5 | Volunteer, VolunteerCoordinator |
| GET | /auxiliary/shift-assignments | List assignments; filter by `shift_id`, `volunteer_id`, `supervisor_assignment_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead, Volunteer |
| GET | /auxiliary/shift-assignments/{id} | Get one assignment | VolunteerServicesDirector, VolunteerCoordinator, DepartmentHead, Volunteer |
| POST | /auxiliary/shift-assignments/{id}/confirm | Move `SIGNED_UP` → `CONFIRMED`; posture `CLEAR`, badge `ISSUED`, training, junior supervision gates | VolunteerCoordinator |
| POST | /auxiliary/shift-assignments/{id}/cancel | Move `SIGNED_UP`/`CONFIRMED`/`WAITLISTED` → `CANCELLED`; volunteer self-cancel windowed; waitlist promotion on `PUBLISHED` shifts | Volunteer, VolunteerCoordinator, VolunteerServicesDirector |
| POST | /auxiliary/hour-entries | Log service hours (lands `PENDING`); optional link to a confirmed assignment | Volunteer, VolunteerCoordinator |
| GET | /auxiliary/hour-entries | List hour entries; filter by `volunteer_id`, `shift_assignment_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| GET | /auxiliary/hour-entries/{id} | Get one hour entry | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| POST | /auxiliary/hour-entries/{id}/approve | Move `PENDING` → `APPROVED`; OCC via `expected_volunteer_version`; recomputes totals/points/tier; may complete the linked assignment | VolunteerCoordinator |
| POST | /auxiliary/hour-entries/{id}/reject | Move `PENDING` → `REJECTED`; requires `decision_reason` | VolunteerCoordinator |
| POST | /auxiliary/hour-entries/{id}/reverse | Move `APPROVED` → `REVERSED`; compensates totals/points/tier exactly | VolunteerCoordinator |
| GET | /auxiliary/badges | List badges; filter by `volunteer_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| GET | /auxiliary/badges/{id} | Get one badge | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| POST | /auxiliary/badges/{id}/revoke | Revoke a live badge (`revoke_reason` `MANUAL`) | VolunteerCoordinator |
| POST | /auxiliary/badges/{id}/replace | Revoke a live badge (`LOST_REPLACED`) and mint a new badge directly in `ISSUED`; volunteer must be `ACTIVE` | VolunteerCoordinator |
| POST | /auxiliary/fundraising-campaigns | Create a campaign (lands `DRAFT`) | AuxiliaryTreasurer |
| GET | /auxiliary/fundraising-campaigns | List campaigns; filter by `status` | VolunteerServicesDirector, VolunteerCoordinator, AuxiliaryTreasurer |
| GET | /auxiliary/fundraising-campaigns/{id} | Get one campaign (includes the computed proceeds figures) | VolunteerServicesDirector, VolunteerCoordinator, AuxiliaryTreasurer |
| POST | /auxiliary/fundraising-campaigns/{id}/activate | Move `DRAFT` → `ACTIVE`; requires now inside the campaign window | AuxiliaryTreasurer |
| POST | /auxiliary/fundraising-campaigns/{id}/close | Move `ACTIVE` → `CLOSED`; requires now at or past `end_at`; sets `closed_at` | AuxiliaryTreasurer |
| POST | /auxiliary/fundraising-campaigns/{id}/reconcile | Move `CLOSED` → `RECONCILED` | AuxiliaryTreasurer |
| POST | /auxiliary/fundraising-campaigns/{id}/disburse | Disburse from a `RECONCILED` campaign; seven-day cooling-off; caller differs from creator; amount within net proceeds | AuxiliaryTreasurer |
| POST | /auxiliary/gift-shop-items | Create a gift shop item | AuxiliaryTreasurer |
| GET | /auxiliary/gift-shop-items | List items; filter by `is_active` | VolunteerServicesDirector, VolunteerCoordinator, AuxiliaryTreasurer, Volunteer |
| GET | /auxiliary/gift-shop-items/{id} | Get one item | VolunteerServicesDirector, VolunteerCoordinator, AuxiliaryTreasurer, Volunteer |
| PUT | /auxiliary/gift-shop-items/{id} | Update price, restock (`restock_qty`), reorder hint, or active flag | AuxiliaryTreasurer |
| POST | /auxiliary/gift-shop-sales | Ring a sale (lands `COMPLETED`); max-discount rule, per-line rounding, stock decrement, campaign attribution | Volunteer, AuxiliaryTreasurer |
| GET | /auxiliary/gift-shop-sales | List sales; filter by `cashier_volunteer_id`, `campaign_id`, `buyer_volunteer_id`, `status` | VolunteerServicesDirector, VolunteerCoordinator, AuxiliaryTreasurer, Volunteer |
| GET | /auxiliary/gift-shop-sales/{id} | Get one sale | VolunteerServicesDirector, VolunteerCoordinator, AuxiliaryTreasurer, Volunteer |
| POST | /auxiliary/gift-shop-sales/{id}/void | Move `COMPLETED` → `VOIDED` within 24 hours; restores stock and unwinds campaign raised/net (gross unchanged) | AuxiliaryTreasurer, VolunteerCoordinator |
| GET | /auxiliary/recognition-events | List recognition events; filter by `volunteer_id` | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| GET | /auxiliary/recognition-events/{id} | Get one recognition event | VolunteerServicesDirector, VolunteerCoordinator, Volunteer |
| POST | /auxiliary/compliance/annual-review | Run the compliance epoch sweep (§3.6); idempotent at a fixed clock | VolunteerServicesDirector |

## 5. Error Code Catalogue

The catalogue below lists every error identifier with its HTTP status. Trigger conditions are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_SOD_CLEARANCE_ADJUDICATION | 403 |
| ERR_SOD_CAMPAIGN_DISBURSEMENT | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_APPLICATION_NOT_ACTIONABLE | 409 |
| ERR_VOLUNTEER_INVALID_STATE | 409 |
| ERR_POSTURE_FROZEN | 409 |
| ERR_POSTURE_NOT_CLEAR | 409 |
| ERR_CLEARANCE_INVALID_STATE | 409 |
| ERR_REQUEST_INVALID_STATE | 409 |
| ERR_REQUEST_NOT_OPEN | 409 |
| ERR_PLACEMENT_INVALID_STATE | 409 |
| ERR_SHIFT_INVALID_STATE | 409 |
| ERR_ASSIGNMENT_INVALID_STATE | 409 |
| ERR_HOUR_ENTRY_INVALID_STATE | 409 |
| ERR_TRAINING_RECORD_INVALID_STATE | 409 |
| ERR_BADGE_INVALID_STATE | 409 |
| ERR_CAMPAIGN_INVALID_STATE | 409 |
| ERR_SALE_ALREADY_VOIDED | 409 |
| ERR_ROLE_MIN_AGE_NOT_MET | 422 |
| ERR_DEPARTMENT_JUNIOR_RESTRICTED | 422 |
| ERR_JUNIOR_WEEKLY_HOUR_CAP_EXCEEDED | 422 |
| ERR_SUPERVISION_REQUIRED | 422 |
| ERR_SUPERVISOR_INELIGIBLE | 422 |
| ERR_SUPERVISOR_RATIO_EXCEEDED | 422 |
| ERR_TRAINING_REQUIREMENT_UNMET | 422 |
| ERR_ORIENTATION_INCOMPLETE | 422 |
| ERR_CLEARANCE_REQUIREMENTS_UNMET | 422 |
| ERR_NO_ACCEPTED_PLACEMENT | 409 |
| ERR_DUPLICATE_ACTIVE_CLEARANCE | 409 |
| ERR_DUPLICATE_PLACEMENT | 409 |
| ERR_PLACEMENT_LIMIT_EXCEEDED | 409 |
| ERR_DUPLICATE_SHIFT_ASSIGNMENT | 409 |
| ERR_SHIFT_TIME_OVERLAP | 409 |
| ERR_SHIFT_AT_CAPACITY | 409 |
| ERR_COUNTER_ROUND_EXHAUSTED | 409 |
| ERR_SHIFT_HAS_ASSIGNMENTS | 409 |
| ERR_ITEM_INACTIVE | 409 |
| ERR_HOURS_EXCEED_SHIFT | 422 |
| ERR_SIGNUP_WINDOW_CLOSED | 409 |
| ERR_CANCEL_WINDOW_CLOSED | 409 |
| ERR_SHIFT_NOT_ENDED | 409 |
| ERR_VOID_WINDOW_ELAPSED | 409 |
| ERR_CAMPAIGN_WINDOW_MISMATCH | 422 |
| ERR_DISBURSEMENT_COOLING_OFF | 409 |
| ERR_SERVICE_DATE_OUT_OF_RANGE | 422 |
| ERR_ASSIGNMENT_OWNERSHIP_MISMATCH | 422 |
| ERR_CASHIER_NOT_GIFT_SHOP_PLACED | 422 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_INSUFFICIENT_TENDER | 402 |
| ERR_DISBURSEMENT_EXCEEDS_BALANCE | 402 |

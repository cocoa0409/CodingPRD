# Confined Space Rescue Standby API — Product Requirements Document

## 1. Introduction

Industrial facilities routinely require work inside tanks, vessels, sewers, and other confined spaces where atmospheric hazards, engulfment risk, or restricted egress make self-rescue impossible. A specialist rescue contractor coordinates the permits, the attendant and entrant roster, the standby rescue team, the isolation evidence, and the post-incident billing that together make such work lawful and survivable. This document specifies the Confined Space Rescue Standby API: a compliance-first system that tracks the full lifecycle from space classification through entry permit issuance, continuous atmospheric monitoring, rescue-team standby staffing, incident escalation, and final statement settlement.

Two concerns dominate the design. The first is safety-critical serialization: permit activation must never proceed without an approved rescue plan, unexpired isolation verifications, a fresh pre-entry atmosphere check, and adequate standby coverage, and any out-of-limits reading during entry must trigger an automatic evacuation cascade. The second is fiscal fidelity: the same operational events (permits activated, standby hours released, deployments, cancellations) must be swept into per-account billing statements under one of two billing variants, with a pinned rounding order and a strict ledger invariant tying every statement back to the client's outstanding balance.

The API is consumed by six distinct operator roles. Segregation of duties is enforced structurally: the supervisor who issues a permit may not verify its isolations, and the person who reports an incident may not resolve it. Time itself is a first-class input — the system runs on a logical clock that test tooling can advance, and all staleness, no-show, expiry, and monitoring-gap rules are evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. The system recognizes exactly six roles: `OperationsManager`, `EntrySupervisor`, `Attendant`, `RescueTeamLead`, `SafetyOfficer`, and `BillingClerk`. A request missing either header, or carrying a role value outside this enumeration, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Beyond header presence, each endpoint permits only a declared subset of roles; a request whose role is not authorized for that endpoint is rejected with `ERR_FORBIDDEN`.

Four of the roles are **entity-backed**: they resolve `X-User-ID` against the `Personnel` registry. When `X-User-Role` is `EntrySupervisor`, `Attendant`, `RescueTeamLead`, or `SafetyOfficer`, `X-User-ID` is the `id` of the acting `Personnel` row; ownership and qualification checks compare resource foreign-key fields (for example a permit's `issued_by` or an incident's `reported_by`) against `X-User-ID`. Each entity-backed role carries a required qualification that the resolved `Personnel` row must hold in its `role_qualifications` array — `ENTRY_SUPERVISOR` for `EntrySupervisor`, `ATTENDANT` for `Attendant`, `RESCUE_LEAD` for `RescueTeamLead`, and `SAFETY_OFFICER` for `SafetyOfficer` — and the row must be in `ACTIVE` status. An `X-User-ID` that does not resolve to an `ACTIVE` `Personnel` row holding the role's required qualification is rejected with `ERR_IDENTITY_NOT_QUALIFIED`.

The remaining two roles are opaque. When `X-User-Role` is `OperationsManager` or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Only `ACTIVE` personnel may be scheduled onto rosters or standby windows, or act through entity-backed roles.

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

List endpoints accept two query parameters controlling pagination. The `limit` parameter specifies the maximum number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Every paginated list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed fields: an `id` formatted as a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits recording creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and a `version` integer that increments on every mutation. Two resource kinds are exempt from the full set: `AtmosphericReading` and `StatementLine` are append-only ledger-style records and carry only `id` and `created_at` — both `updated_at` and `version` are absent on these two resources, and any request that supplies them is rejected as an unknown-field violation.

All time-dependent rules in the system — staleness of pre-entry readings, expiry of isolation verifications, no-show marking, monitoring-gap detection, check-in windows — are evaluated against a **logical clock**, never against wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; once set it never falls back to wall-clock time. An `OperationsManager`-only test-driving capability accepts a target instant `to_iso8601` and advances the logical clock to it, returning the new `current_utc`. Every such advance runs the system sweeps against the new logical time: roster entries and standby assignments still `SCHEDULED` past their no-show grace are flipped to `NO_SHOW`, verified isolations whose validity window has closed are flipped to `EXPIRED`, monitoring-gap suspensions fire, and exposure classifications are recomputed for every on-duty roster entry.

### 2.5. Nested Resource Retrieval

Requests targeting nested resources are validated left-to-right along the path. A path such as `/rescue-ops/client-accounts/{accountId}/confined-spaces` or `/rescue-ops/entry-permits/{permitId}/roster-entries` resolves each identifier in order, and the request is rejected immediately with the `404` error corresponding to the first identifier that does not exist — `ERR_ACCOUNT_NOT_FOUND` before `ERR_SPACE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND` before `ERR_ROSTER_ENTRY_NOT_FOUND`, and so on through `ERR_PERSONNEL_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_VERIFICATION_NOT_FOUND`, `ERR_READING_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`. A nested child must belong to the parent named in its path; a roster entry addressed under the wrong permit is not found. Body-supplied foreign-key references — `personnel_id` on a roster entry, `rescuer_id` on a standby assignment, `relief_of_entry_id` on a relief rotation — must also resolve to existing resources or the request fails with the matching not-found error.

### 2.6. Validation Ordering and Request Shape

Every mutation request passes through a fixed pipeline of validation categories, evaluated in priority order so that earlier failures mask later ones. Authentication comes first: header presence and role declaration, then role-per-endpoint authorization, then entity-backed identity resolution. Existence checks follow — path identifiers resolved left-to-right, then body-supplied foreign keys. Request-shape validation comes next: required fields must be present, unknown fields are rejected (this includes client-supplied system or computed fields such as `within_limits`, `balance_cents`, or `id`, which are never accepted from clients), enum values must belong to their declared enumerations, and numeric values must fall inside sane ranges, all reported as `ERR_INVALID_REQUEST`. Time-range shape is enforced here as well: `planned_end_at` strictly after `planned_start_at` on permits, `scheduled_end_at` strictly after `scheduled_start_at` on roster entries, `standby_end_at` strictly after `standby_start_at` on standby assignments, and `period_end` strictly after `period_start` on billing statements — any violation is `ERR_INVALID_TIME_RANGE`. Only after these come optimistic-concurrency checks, state-transition legality, and then the domain safety, capacity, temporal, qualification, and fiscal gates described throughout §3.

### 2.7. Optimistic Concurrency Control on Confined Spaces

Four write operations serialize against the owning `ConfinedSpace` through optimistic concurrency. Creating a rescue plan for a space, approving a rescue plan, creating an entry permit on a space, and updating a space's record each require the request body to carry `expected_space_version` holding the client's last-observed `version` of that space; the field is non-optional on these four endpoints. If the supplied value does not match the space's current `version` — because a plan creation, a plan approval, a permit creation, or a space update has advanced the space since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). All four of these operations themselves increment the space's `version` by one on success. Endpoints other than these four do not accept a version field.

### 2.8. Monetary Precision and Rounding Order

All monetary values are integer cents. Wherever a monetary product is computed — an hourly standby charge, a statement line amount, a cancellation fee — the final figure is rounded to integer cents using round-half-up. The entrant exposure classification is the one non-monetary calculation with its own precision rule: exposure values are rounded to 2 decimal places using round-half-up, and threshold comparisons happen **after** rounding.

The statement aggregation rule pins a strict rounding order: each `StatementLine`'s `amount_cents` is rounded to integer cents **first**, and only then are the per-line amounts summed into the statement's `total_cents`. Sum-then-round is forbidden. For example, two lines whose raw products are 4999.5 cents each produce a statement total of 10000 cents (5000 plus 5000), not 9999.

### 2.9. The Account Ledger Invariant and Credit Hold

Every `ClientAccount` maintains a `balance_cents` that always equals the sum of `billed_balance_contribution_cents` over all of the account's `BillingStatement` records — this ledger invariant must hold after every mutation. An account's `on_credit_hold` flag is recomputed whenever `balance_cents` changes: the flag is true exactly when `balance_cents` is greater than or equal to `credit_limit_cents`, with the boundary inclusive, so an account whose balance equals its credit limit is on hold. Credit hold is a fiscal gate on new work: creating an entry permit for a space owned by an account on credit hold is rejected with `ERR_CLIENT_CREDIT_HOLD`.

## 3. Business Logic & Workflows

### 3.1. Registries: Personnel, Client Accounts, and Confined Spaces

Before any fieldwork can occur, an `OperationsManager` populates three registries. The **Personnel** registry records every worker by `full_name`, the `role_qualifications` they hold (drawn from `ENTRY_SUPERVISOR`, `ATTENDANT`, `RESCUE_LEAD`, `SAFETY_OFFICER`, `RESCUER`), and any `certifications` they carry (drawn from `CONFINED_SPACE_RESCUE`, `HIGH_ANGLE`, `HAZMAT`, `MEDIC`, defaulting to an empty list). Each worker's `max_duty_hours` caps the length of any single scheduled roster shift, defaulting to 12 hours when omitted. New personnel start `ACTIVE` with `committed_standby_minutes` at zero; an `OperationsManager` may later toggle `status` between `ACTIVE` and `INACTIVE`, and only `ACTIVE` personnel may be scheduled or act through entity-backed roles. The personnel list endpoint supports filtering by `role_qualification` and `status`.

The **ClientAccount** registry captures each facility operator by `name` together with the full rate configuration that drives billing: the `billing_mode` selecting `HOURLY_STANDBY` or `EVENT`, the `hourly_standby_rate_cents` base rate, the flat `event_base_fee_cents` per activated permit, the `event_per_rescuer_cents` fee per standby rescuer, the `credit_limit_cents` ceiling, and five defaulted knobs — `deployment_surcharge_cents` (default 50000), `minimum_billable_hours` (default 4), `tier1_hours_threshold` (default 8), `tier2_multiplier` (default 1.5), `after_hours_multiplier` (default 1.5), and `weekend_multiplier` (default 2.0). New accounts begin with `balance_cents` at zero and `on_credit_hold` false. The account list endpoint supports filtering by `billing_mode` and `on_credit_hold`.

The **ConfinedSpace** registry sits beneath client accounts: an `OperationsManager` registers each space under its owning account with a client-side `space_code`, a `classification` of `NON_PERMIT`, `PERMIT_REQUIRED`, or `PERMIT_REQUIRED_HAZARDOUS`, and a safety profile comprising `requires_continuous_monitoring`, `max_entrants`, `ventilation_required`, `blind_flange_required`, and an `exposure_standard` of `TWA8` or `PEAK_CEILING`. New spaces start with `status` `AVAILABLE`. Space records can later be updated — reclassification, capacity changes, monitoring-flag changes, or a status toggle — by an `OperationsManager` or `SafetyOfficer` carrying `expected_space_version`, and each successful update increments the space's `version`. Two guardrails protect in-flight work: downgrading a space's `classification` to `NON_PERMIT`, or setting its `status` to `OUT_OF_SERVICE`, is rejected with `ERR_PERMITS_STILL_OPEN` while any of the space's permits is non-terminal. The space list endpoint supports filtering by `client_account_id`, `classification`, and `status`.

### 3.2. Rescue Plans and Revision Lineage

Every permit-required space must have an approved rescue plan before entry can be authorized. A `RescueTeamLead` drafts a plan for a space by supplying `required_team_size` (the minimum number of standby rescuers whose windows must cover the activation instant), an optional list of `required_certifications` that every standby rescuer on the space must hold, and a `retrieval_system_type` of `MECHANICAL_RETRIEVAL`, `TRIPOD`, `HORIZONTAL_HAUL`, or `ENTRY_RESCUE`. The creation request must carry `expected_space_version` matching the space's current `version`; a mismatch is rejected with `ERR_STALE_VERSION`.

Each plan receives a per-space monotonically increasing `plan_revision` — the first plan created for a space is revision 1, and each subsequent creation takes the prior maximum revision plus one. Creating a new plan supersedes any existing `DRAFT` plans of the same space, moving them to `SUPERSEDED`, and increments the space's `version`. A plan begins in `DRAFT` and becomes effective only when a `RescueTeamLead` approves it — again carrying `expected_space_version`, again rejected with `ERR_STALE_VERSION` on mismatch. Approval sets `approved_by` to the acting personnel id and `approved_at` to the current logical time, supersedes any *other* `APPROVED` plan of the same space, and increments the space's `version`. Approving a plan that is not in `DRAFT` is rejected with `ERR_PLAN_INVALID_STATE`. Because a superseding creation leaves the space without an `APPROVED` plan until the new draft is itself approved, permits in `ISSUED` or `SUSPENDED` that attempt activation or resume during that gap observe no approved plan and fail — this is deliberate. The plan list endpoint supports filtering by `space_id`, `status`, and `approved_by`.

### 3.3. The Entry Permit Lifecycle

An **EntryPermit** authorizes one window of work inside one space. An `EntrySupervisor` creates a permit on a space by supplying the `purpose` plus a planned window — `planned_start_at` strictly before `planned_end_at` — and the request must carry `expected_space_version` matching the space's current `version` (`ERR_STALE_VERSION` on mismatch). Creation is gated: the space must be classified `PERMIT_REQUIRED` or `PERMIT_REQUIRED_HAZARDOUS` — a permit on a `NON_PERMIT` space is rejected with `ERR_SPACE_NOT_PERMIT_REQUIRED`; the space must be `AVAILABLE`, otherwise `ERR_SPACE_OUT_OF_SERVICE`; no other permit of the same space may currently be in `ISSUED`, `ACTIVE`, or `SUSPENDED`, otherwise `ERR_SPACE_OCCUPIED`; and the owning account must not be on credit hold, otherwise `ERR_CLIENT_CREDIT_HOLD`. A new permit starts in `DRAFT`, denormalizes the space's owning account onto `client_account_id` for billing sweeps, auto-cancels any existing `DRAFT` permits of the same space (supersede semantics, closing them with `close_reason` `CANCELLED`), and increments the space's `version`. The permit list endpoint supports filtering by `space_id`, `client_account_id`, `status`, and `issued_by`.

Issuance moves `DRAFT` to `ISSUED`, recording `issued_by` as the acting supervisor and `issued_at` as the current logical time; issuing a permit not in `DRAFT` fails with `ERR_PERMIT_INVALID_STATE`.

Activation moves `ISSUED` to `ACTIVE` and is the most heavily guarded transition in the system. The safety chain is evaluated in a fixed order: first, an `APPROVED` rescue plan must exist for the space (`ERR_RESCUE_PLAN_NOT_APPROVED`); second, each isolation type the space requires — `VENTILATION` when `ventilation_required` is true, `BLIND_FLANGE` when `blind_flange_required` is true — must have a verification in `VERIFIED` status whose `expires_at` is still in the future (`ERR_ISOLATION_NOT_VERIFIED`); third, the latest `PRE_ENTRY` reading for the permit must exist and be within limits (`ERR_ATMOSPHERE_OUT_OF_LIMITS`); fourth, that reading must be fresh — recorded no more than 30 minutes before now, with exactly 30 minutes acceptable and 30 minutes plus one second failing (`ERR_PRE_ENTRY_READING_STALE`); fifth, standby coverage at the activation instant — assignments in `SCHEDULED` or `ON_STANDBY` whose half-open window `[standby_start_at, standby_end_at)` contains now — must be at least the approved plan's `required_team_size` (`ERR_RESCUE_TEAM_UNDERSTAFFED`); sixth, now must fall within the planned window, at or after `planned_start_at` and at or before `planned_end_at` (`ERR_OUTSIDE_PLANNED_WINDOW`). The space must also still be `AVAILABLE` (`ERR_SPACE_OUT_OF_SERVICE`). Successful activation stamps `actual_entry_at` with the current logical time and increments the permit's `version`.

Suspension, resumption, closure, and cancellation complete the cycle; each is detailed in §3.5 alongside the emergency paths that share their cascades.

### 3.4. Isolation Verifications

A `SafetyOfficer` submits an **IsolationVerification** against a permit, supplying an `isolation_type` of `VENTILATION`, `BLIND_FLANGE`, or `LOCKOUT_TAGOUT` and a free-text `evidence_ref` such as a photo id or lock serial. The parent permit must be in `ISSUED` or `SUSPENDED` (`ERR_PERMIT_INVALID_STATE` otherwise), and the new record starts `PENDING` with `created_by` set from the submitter's identity.

Verification is a second-person control: a `SafetyOfficer` verifies a `PENDING` record, which sets `verified_by`, stamps `verified_at` with the current logical time, and computes `expires_at` as exactly 12 hours after `verified_at`. Segregation of duties forbids the permit's issuer from verifying its isolations — when the verifier's identity equals the permit's `issued_by`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Verifying a record not in `PENDING` is `ERR_VERIFICATION_INVALID_STATE`. A `VERIFIED` verification remains valid strictly until its `expires_at`; at the exact instant now equals `expires_at`, the clock sweep moves it to `EXPIRED`, and an expired verification no longer satisfies the activation or resume chain. Either a `PENDING` or a `VERIFIED` record may be voided explicitly by a `SafetyOfficer` (optionally with a `reason`), moving it to `VOIDED`, and both are also moved to `VOIDED` automatically when the parent permit closes or is cancelled; voiding a record in any other state is `ERR_VERIFICATION_INVALID_STATE`. The verification list endpoint supports filtering by `permit_id`, `isolation_type`, `status`, and `verified_by`.

### 3.5. Roster, Standby Staffing, and the Permit End-Game

**Roster scheduling.** An `EntrySupervisor` schedules workers onto a permit in `ISSUED` or `ACTIVE` by creating roster entries, each naming a `personnel_id`, an `assignment_role` of `ENTRANT` or `ATTENDANT`, and a shift window with `scheduled_start_at` strictly before `scheduled_end_at`. The shift length must not exceed the worker's `max_duty_hours`, else `ERR_SHIFT_DURATION_EXCEEDS`. Slots with `assignment_role` `ATTENDANT` require personnel holding the `ATTENDANT` qualification (`ERR_PERSONNEL_NOT_QUALIFIED`). A worker may not be scheduled with inadequate rest: a new entry conflicts with any existing `SCHEDULED` or `ON_DUTY` entry of the same personnel when the new shift starts before 8 hours after the existing shift ends **and** the existing shift starts before 8 hours after the new shift ends — a gap of exactly 8 hours is legal — and violations are rejected with `ERR_INSUFFICIENT_REST`. An entry may optionally declare itself a relief rotation by naming `relief_of_entry_id`, a self-reference to another entry on the same permit with the same `assignment_role`. New entries start `SCHEDULED`. The roster list endpoint supports filtering by `permit_id`, `personnel_id`, `status`, `assignment_role`, and `relief_of_entry_id`.

**Roster check-in and rotation.** Checking a rostered worker in requires the entry to be `SCHEDULED` (`ERR_ROSTER_INVALID_STATE`), the parent permit to be `ACTIVE` (`ERR_PERMIT_INVALID_STATE`), and the current time to fall inside the check-in window: no earlier than 15 minutes before `scheduled_start_at` (`ERR_CHECKIN_WINDOW_NOT_OPEN`) and no later than `scheduled_end_at` (`ERR_CHECKIN_WINDOW_EXPIRED`). The worker must not already be `ON_DUTY` on any other roster entry (`ERR_PERSONNEL_ALREADY_ON_DUTY`). An entrant may only check in while at least one attendant of the same permit is `ON_DUTY` (`ERR_NO_ATTENDANT_ON_DUTY`), and while the count of on-duty entrant entries on the permit remains below the space's `max_entrants` — a check-in arriving when the count already equals `max_entrants` is rejected with `ERR_MAX_ENTRANTS_EXCEEDED`. When `relief_of_entry_id` is set, the named target must currently be `ON_DUTY` (`ERR_RELIEF_TARGET_NOT_ON_DUTY`); on success the target transitions from `ON_DUTY` to `RELIEVED` with its `checked_out_at` set to the relieving entry's `checked_in_at`. A successful check-in stamps `checked_in_at` and moves the entry to `ON_DUTY`.

**Check-out, no-show, and exposure.** An `EntrySupervisor` checks an `ON_DUTY` worker out, moving the entry to `COMPLETED` with `checked_out_at` stamped — except that an attendant may not check out while any entrant of the same permit remains `ON_DUTY` (`ERR_ENTRANTS_STILL_INSIDE`). Entries still `SCHEDULED` when the logical clock passes 15 minutes beyond their `scheduled_start_at` are swept to `NO_SHOW`; exactly 15 minutes past does not flip them, only strictly later. Every roster entry also accumulates exposure data during its duty window — `exposure_twa_ppm`, `exposure_peak_ppm`, and a computed `exposure_class` — per the classification rules in §3.7; when an entry's class becomes `EXCEEDANCE` it is auto-relieved, moving `ON_DUTY` to `RELIEVED` with `checked_out_at` set to the trigger timestamp.

**Standby staffing.** A `RescueTeamLead` schedules the rescue team's standby windows on a permit in `ISSUED`, `ACTIVE`, or `SUSPENDED`. Scheduling requires an `APPROVED` rescue plan for the space (`ERR_RESCUE_PLAN_NOT_APPROVED`), and each assignment names a `rescuer_id` and a window with `standby_start_at` strictly before `standby_end_at`. The rescuer must hold the `RESCUER` qualification and certifications covering the approved plan's `required_certifications` (`ERR_PERSONNEL_NOT_QUALIFIED`). Standby windows follow half-open overlap semantics: a new assignment conflicts with any existing `SCHEDULED`, `ON_STANDBY`, or `DEPLOYED` assignment of the same rescuer when the new window starts before the existing window ends **and** the existing window starts before the new window ends — touching windows, where the new start equals the existing end, are legal, and unlike roster scheduling no rest buffer applies — with violations rejected as `ERR_STANDBY_OVERLAP`. A new assignment starts `SCHEDULED`, and its window minutes are added to the rescuer's `committed_standby_minutes`, which sums window lengths across the rescuer's assignments in `SCHEDULED`, `ON_STANDBY`, or `DEPLOYED` status; `RELEASED`, `CANCELLED`, and `NO_SHOW` assignments contribute zero. The standby list endpoint supports filtering by `permit_id`, `rescuer_id`, and `status`.

**Standby check-in, release, and cancellation.** Checking a standby rescuer in requires the assignment to be `SCHEDULED` (`ERR_ASSIGNMENT_INVALID_STATE`), the parent permit in `ISSUED`, `ACTIVE`, or `SUSPENDED` (`ERR_PERMIT_INVALID_STATE`), and now within the check-in window — no earlier than 30 minutes before `standby_start_at` (`ERR_CHECKIN_WINDOW_NOT_OPEN`) and no later than `standby_end_at` (`ERR_CHECKIN_WINDOW_EXPIRED`). Check-in stamps `checked_in_at`, moves the assignment to `ON_STANDBY`, and leaves `committed_standby_minutes` unchanged because window minutes stay committed while on standby. Releasing an `ON_STANDBY` or `DEPLOYED` assignment (a `RescueTeamLead` action, also fired by permit close and manual-cancel cascades) stamps `checked_out_at`, moves the assignment to `RELEASED`, computes its `billable_minutes` and `line_amount_cents`, and subtracts the assignment's window minutes from the rescuer's `committed_standby_minutes`; releasing from `DEPLOYED` additionally makes a `DEPLOYMENT_SURCHARGE` line billable. Cancelling a `SCHEDULED` assignment — explicitly or via cascade from a permit cancellation — moves it to `CANCELLED`, accrues no charge, and subtracts the window minutes from `committed_standby_minutes`. Assignments still `SCHEDULED` more than 15 minutes past `standby_start_at` are swept to `NO_SHOW`, likewise releasing their committed minutes.

**Closing and cancelling permits.** Orderly closure moves a permit from `ACTIVE` or `SUSPENDED` to `CLOSED` with `close_reason` `COMPLETED` and `closed_at` stamped. It requires no on-duty roster entries (`ERR_ENTRANTS_STILL_INSIDE`) and no open incidents — any incident of the permit in `REPORTED`, `TRIAGED`, `ESCALATED`, or `REOPENED` blocks closure with `ERR_OPEN_INCIDENTS_EXIST`. Closure cascades: standby assignments in `ON_STANDBY` are released with billable fields computed, assignments in `SCHEDULED` are cancelled, assignments in `DEPLOYED` are left unchanged and must be released explicitly, roster entries in `SCHEDULED` are cancelled, and verifications in `PENDING` or `VERIFIED` are voided.

Manual cancellation is available from `DRAFT`, `ISSUED`, `ACTIVE`, or `SUSPENDED` (any other state is `ERR_PERMIT_INVALID_STATE`), optionally carrying a `reason`, and requires no on-duty roster entries when cancelling from `ACTIVE` (`ERR_ENTRANTS_STILL_INSIDE`). Cancellation sets `close_reason` `CANCELLED`, stamps `closed_at`, and cascades: roster entries in `SCHEDULED` are cancelled, standby assignments in `SCHEDULED` are cancelled and those in `ON_STANDBY` are released to bill actual time, and verifications in `PENDING` or `VERIFIED` are voided. When the cancelled permit had `actual_entry_at` set, a `CANCELLATION_FEE` line becomes billable, swept at statement generation. Orderly manual suspension from `ACTIVE` — available to an `EntrySupervisor` or `SafetyOfficer`, optionally with a `reason` — requires the space to be empty of on-duty entrants (`ERR_ENTRANTS_STILL_INSIDE`); it increments `suspension_count` and stamps `last_suspended_at`. Manual suspension is distinct from the emergency paths of §3.6, which evacuate automatically.

Resumption — re-entry authorization from `SUSPENDED` back to `ACTIVE` by an `EntrySupervisor` — reruns the safety chain in order: an `APPROVED` rescue plan must exist (a plan superseded while the permit was suspended fails with `ERR_RESCUE_PLAN_NOT_APPROVED`); required isolation types must hold unexpired `VERIFIED` verifications (`ERR_ISOLATION_NOT_VERIFIED`); a `PRE_ENTRY` reading recorded **after** `last_suspended_at` must exist and be within limits (`ERR_ATMOSPHERE_OUT_OF_LIMITS`); that reading must be no more than 30 minutes old (`ERR_PRE_ENTRY_READING_STALE`); and no open incidents may exist on the permit (`ERR_OPEN_INCIDENTS_EXIST`). Successful resumption increments `reentry_count`.

### 3.6. Atmospheric Monitoring, Alarms, and Incidents

**The continuous log.** An `Attendant` records atmospheric readings against a permit, supplying a `reading_kind` of `PRE_ENTRY` or `CONTINUOUS` and four measured values: `o2_pct` (oxygen percent, plausibly 0.0 to 30.0), `lel_pct` (percent of lower explosive limit, 0 to 100), `h2s_ppm` (hydrogen sulfide, 0 to 500), and `co_ppm` (carbon monoxide, 0 to 2000). Values outside these plausibility ranges are rejected with `ERR_READING_OUT_OF_RANGE`. The reading kind is gated by permit state: `PRE_ENTRY` readings are allowed only while the permit is `ISSUED` or `SUSPENDED`, and `CONTINUOUS` readings only while `ACTIVE` — otherwise `ERR_READING_KIND_NOT_ALLOWED`. Each reading stamps `recorded_at` from the logical clock, records the attendant as `recorded_by`, and computes `within_limits`: true exactly when `o2_pct` is at least 19.5 and at most 23.5, `lel_pct` is at most 10, `h2s_ppm` is at most 10, and `co_ppm` is at most 35 — all bounds inclusive. The readings list endpoint supports filtering by `permit_id`, `reading_kind`, `within_limits`, and `recorded_by`.

**The alarm cascade.** When a `CONTINUOUS` reading arrives out of limits on an `ACTIVE` permit, a three-link cascade fires automatically. Link one: the permit transitions `ACTIVE` to `SUSPENDED`, incrementing `suspension_count` and stamping `last_suspended_at`. Link two: every on-duty roster entry of the permit is evacuated — `ON_DUTY` to `EVACUATED` with `checked_out_at` stamped and exposure finalized. Link three: when any entry becomes `EVACUATED`, that permit's standby assignments in `ON_STANDBY` move to `DEPLOYED` with `deployed_at` stamped. The alarm path additionally auto-creates an `Incident` with `kind` `ATMOSPHERE`, `reported_by` taken from the reading's `recorded_by`, and `severity` `CRITICAL` when any of the following holds — oxygen below 16 percent, oxygen above 25 percent, LEL at or above 25, hydrogen sulfide at or above 20 ppm, or carbon monoxide at or above 100 ppm — and `SERIOUS` otherwise.

**Monitoring-gap suspension.** Separately, the clock sweep watches every `ACTIVE` permit whose space has `requires_continuous_monitoring`: when the gap since the latest `CONTINUOUS` reading's `recorded_at` — or since `actual_entry_at` if no continuous reading exists — is **strictly greater** than 15 minutes, the permit is suspended with the same emergency cascade (roster evacuated, standby deployed). A gap of exactly 15 minutes does not suspend, and unlike the alarm path no incident is auto-created by the gap path.

**Manual incident reporting and workflow.** An `EntrySupervisor`, `SafetyOfficer`, or `RescueTeamLead` may report an incident on a permit in `ACTIVE` or `SUSPENDED`, supplying `severity` (`MINOR`, `SERIOUS`, or `CRITICAL`), `kind` (`ENTRAPMENT`, `ATMOSPHERE`, `MEDICAL`, or `EQUIPMENT`), and a free-text `description`. The new incident starts `REPORTED` with `reported_by` from the reporter's identity; reporting on an `ACTIVE` permit forces an emergency suspension of that permit with the evacuation/deployment cascade described above. The incident list endpoint supports filtering by `permit_id`, `status`, `severity`, and `reported_by`.

A `SafetyOfficer` then triages a `REPORTED` or `REOPENED` incident (any other state is `ERR_INCIDENT_INVALID_STATE`), stamping `triaged_by` and optionally reclassifying `severity` via an optional input. Escalating a `TRIAGED` incident moves it to `ESCALATED`, increments `escalation_level` by one, and fires the escalation cascade: the parent permit, if in `DRAFT`, `ISSUED`, `ACTIVE`, or `SUSPENDED`, is cancelled with `close_reason` `INCIDENT`, and the cancellation's own side effects fire as the second link — on-duty roster entries are evacuated with `checked_out_at` stamped, scheduled roster entries are cancelled, on-standby assignments are deployed with `deployed_at` stamped, scheduled assignments are cancelled, verifications in `PENDING` or `VERIFIED` are voided, and a `CANCELLATION_FEE` line becomes billable when the permit had `actual_entry_at` set. When the incident's `severity` is `CRITICAL`, the parent space itself moves to `OUT_OF_SERVICE`.

Resolution moves a `TRIAGED` or `ESCALATED` incident to `RESOLVED`, capturing `resolution_notes` and `resolved_by` — but segregation of duties forbids the reporter from resolving: when the resolver's identity equals `reported_by`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `RESOLVED` incident may later be reopened by a `SafetyOfficer` supplying a `reason`, moving it to `REOPENED`, from which triage may begin again.

### 3.7. Entrant Exposure Classification

Every on-duty roster entry on a permit is continuously scored for hydrogen-sulfide exposure over its duty window — the interval from the entry's `checked_in_at` to the current logical time. Each `CONTINUOUS` reading applies its `h2s_ppm` value forward from its own `recorded_at` until the next reading's `recorded_at` or the end of the window, and time in the window before the first reading counts as zero ppm. The time-weighted average, `exposure_twa_ppm`, is the sum over all intervals of each reading's ppm multiplied by its interval length in minutes, divided by 480 — normalizing the dose to an eight-hour shift. The peak, `exposure_peak_ppm`, is the maximum `h2s_ppm` among readings whose `recorded_at` falls inside the window, or zero when none do. Both values are rounded to 2 decimal places with round-half-up, and thresholds are compared after rounding. Classification is recomputed after every `CONTINUOUS` reading posted on the permit (for every on-duty entry of that permit) and again by the clock sweep.

Which thresholds apply is selected by the space's `exposure_standard`, one variant per space. Under the `TWA8` variant — which accumulates dose over time — an entry is `EXCEEDANCE` when its rounded time-weighted average is at least 10 ppm, `ACTION` when at least 5 ppm, and otherwise `OK`. Under the `PEAK_CEILING` variant — which reacts only to the maximum instantaneous reading — an entry is `EXCEEDANCE` when its peak is at least 15 ppm, `ACTION` when at least 10 ppm, and otherwise `OK`. All thresholds are inclusive. The same reading stream can classify differently under the two variants: readings of 8 ppm for 240 minutes followed by 2 ppm for 240 minutes yield a time-weighted average of exactly 5.0 ppm (`ACTION` under `TWA8`) while the peak is 8 (`OK` under `PEAK_CEILING`). Whenever an entry's class becomes `EXCEEDANCE`, the entry is auto-relieved: `ON_DUTY` to `RELIEVED` with `checked_out_at` set to the trigger timestamp, and exposure fields finalized for the duty window.

### 3.8. Billing: Two Variants, One Ledger

**Statement generation.** A `BillingClerk` generates a statement for an account by supplying `period_start` (inclusive) and `period_end` (exclusive, strictly after `period_start`). When an `OPEN` statement with an identical period already exists, generation returns that statement and tops it up with newly billable items rather than creating a duplicate. A requested period that intersects an existing `FINALIZED`, `DISPUTED`, or `PAID` statement of the same account is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`. Generation sweeps the account's unbilled billable items according to the account's `billing_mode`, appending `StatementLine` records and marking swept items billed; `total_cents` and `line_count` are then recomputed under the pinned rounding order of §2.8. Every line records its `statement_id`, a `line_kind`, optional plain references `reference_permit_id` and `reference_assignment_id` to the originating permit or assignment, a `quantity`, a `unit_rate_cents`, the computed `amount_cents`, and a human-readable `description`. The statement list endpoint supports filtering by `client_account_id` and `status`; lines of a statement are listed through the statement's lines sub-resource.

**Hourly-standby variant.** For accounts in `HOURLY_STANDBY` mode, each standby assignment computes its charge at release time, stored on the assignment as `billable_minutes` and `line_amount_cents`, and the generation sweep appends one `STANDBY_HOURLY` line per released assignment with `checked_out_at` inside the period and `billed` still false. The charge builds in steps. The actual minutes between `checked_in_at` and `checked_out_at` are rounded up to the next quarter-hour — any partial 15-minute block bills as a full block — yielding `billable_minutes`; dividing by 60 yields billable hours. Chargeable hours are the greater of the account's `minimum_billable_hours` and the billable hours. The chargeable hours split at the account's `tier1_hours_threshold`: hours up to the threshold bill at the account's `hourly_standby_rate_cents`, and hours beyond it bill at that rate multiplied by `tier2_multiplier`. A day-type multiplier then applies to the whole assignment, non-stacking with explicit precedence: when `checked_in_at` falls on a Saturday or Sunday in UTC, the `weekend_multiplier` applies and takes precedence; otherwise, when `checked_in_at`'s UTC hour is before 7 or at or after 19, the `after_hours_multiplier` applies; otherwise the multiplier is 1.0. The final `line_amount_cents` is the base amount multiplied by the day multiplier, rounded half-up once at the end to integer cents.

**Event variant.** For accounts in `EVENT` mode, duration is irrelevant — a 30-minute standby and a nine-hour standby bill identically. The sweep appends, for each permit of the account with `actual_entry_at` inside the period and `event_base_billed` still false, an `EVENT_BASE` line with `quantity` 1 and `unit_rate_cents` equal to the account's `event_base_fee_cents`, then sets `event_base_billed` true. It likewise appends, for each released standby assignment of the account's permits with `checked_out_at` inside the period and `billed` still false, an `EVENT_RESCUER` line with `quantity` 1 at `event_per_rescuer_cents`, setting `billed` true. An account's `billing_mode` selects exactly one variant: `HOURLY_STANDBY` produces per-assignment `STANDBY_HOURLY` lines and no `EVENT_BASE` or `EVENT_RESCUER` lines, while `EVENT` produces exactly the reverse, and identical standby activity yields different totals under the two variants.

**Cross-mode lines.** Two line kinds apply in both modes. When a permit with `actual_entry_at` set is cancelled on any path, a `CANCELLATION_FEE` line becomes billable; at generation, if the permit's `closed_at` falls inside the period and `cancellation_fee_billed` is still false, the line is appended with `quantity` 1 and a `unit_rate_cents` equal to half the account's `event_base_fee_cents` rounded half-up to integer cents, and `cancellation_fee_billed` is set true. When a standby assignment reached `DEPLOYED` before release, a `DEPLOYMENT_SURCHARGE` line with `quantity` 1 at the account's `deployment_surcharge_cents` is swept together with the assignment's mode-specific line once `checked_out_at` falls inside the period.

**Finalization, dispute, void, and payment.** A `BillingClerk` finalizes a statement in `OPEN` or `DISPUTED` (any other state is `ERR_STATEMENT_INVALID_STATE`). Finalization is blocked while any permit of the account is `ACTIVE` or `SUSPENDED` with `actual_entry_at` inside the statement's period (`ERR_PERMITS_STILL_OPEN`). On finalize, `total_cents` is recomputed as the sum of per-line rounded amounts, the account's `balance_cents` is increased by the delta between `total_cents` and the statement's previous `billed_balance_contribution_cents`, the contribution is then set to `total_cents`, `finalized_at` is stamped, and `on_credit_hold` is recomputed. A `FINALIZED` statement may be disputed by a `BillingClerk` supplying a `reason`, moving it to `DISPUTED` with no balance effect; re-finalizing a disputed statement applies the same delta-adjust rule. While `DISPUTED`, a clerk may append a `CREDIT_ADJUSTMENT` line by supplying `credit_amount_cents` and a `reason`; the line's `amount_cents` is the negation of `credit_amount_cents`, and `total_cents` and `line_count` are recomputed.

Voiding a `FINALIZED` or `DISPUTED` statement moves it to `VOID`, subtracts the statement's `billed_balance_contribution_cents` from the account's `balance_cents`, zeroes the contribution, and recomputes the hold — a finalize followed by a void leaves `balance_cents` unchanged, forming a compensating pair. Payment of a `FINALIZED` statement requires `payment_cents` to equal `total_cents` exactly; any other amount is rejected with `ERR_PARTIAL_PAYMENT`. A successful payment moves the statement to `PAID`, subtracts `payment_cents` from `balance_cents`, zeroes the contribution, and recomputes the hold. After every one of these mutations the ledger invariant of §2.9 holds.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`. The logical-clock endpoint returns `200 OK`. All endpoints are mounted under the `/rescue-ops` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rescue-ops/_clock/set_current_utc` | Set the logical clock; runs all time-based sweeps | OperationsManager |
| POST | `/rescue-ops/personnel` | Create a Personnel record | OperationsManager |
| GET | `/rescue-ops/personnel` | List Personnel | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/personnel/{id}` | Get one Personnel record | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| PATCH | `/rescue-ops/personnel/{id}` | Update Personnel (activate/deactivate) | OperationsManager |
| POST | `/rescue-ops/client-accounts` | Create a ClientAccount with rate configuration | OperationsManager |
| GET | `/rescue-ops/client-accounts` | List ClientAccounts | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/client-accounts/{id}` | Get one ClientAccount | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/client-accounts/{accountId}/confined-spaces` | Register a ConfinedSpace under an account | OperationsManager |
| GET | `/rescue-ops/confined-spaces` | List ConfinedSpaces | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/confined-spaces/{id}` | Get one ConfinedSpace | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| PATCH | `/rescue-ops/confined-spaces/{id}` | Update a ConfinedSpace (classification, capacity, monitoring, status) | OperationsManager, SafetyOfficer |
| POST | `/rescue-ops/confined-spaces/{spaceId}/rescue-plans` | Create a RescuePlan (DRAFT) for a space | RescueTeamLead |
| GET | `/rescue-ops/rescue-plans` | List RescuePlans | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/rescue-plans/{id}` | Get one RescuePlan | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/rescue-plans/{id}/approve` | Approve a DRAFT plan; supersedes other APPROVED plans | RescueTeamLead |
| POST | `/rescue-ops/confined-spaces/{spaceId}/entry-permits` | Create an EntryPermit (DRAFT) | EntrySupervisor |
| GET | `/rescue-ops/entry-permits` | List EntryPermits | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/entry-permits/{id}` | Get one EntryPermit | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/entry-permits/{id}/issue` | Issue a DRAFT permit | EntrySupervisor |
| POST | `/rescue-ops/entry-permits/{id}/activate` | Activate an ISSUED permit (full safety chain) | EntrySupervisor |
| POST | `/rescue-ops/entry-permits/{id}/suspend` | Orderly manual suspension of an ACTIVE permit | EntrySupervisor, SafetyOfficer |
| POST | `/rescue-ops/entry-permits/{id}/resume` | Resume a SUSPENDED permit (re-entry authorization) | EntrySupervisor |
| POST | `/rescue-ops/entry-permits/{id}/close` | Close an ACTIVE or SUSPENDED permit | EntrySupervisor |
| POST | `/rescue-ops/entry-permits/{id}/cancel` | Cancel a non-terminal permit | EntrySupervisor |
| POST | `/rescue-ops/entry-permits/{permitId}/isolation-verifications` | Submit an isolation verification (PENDING) | SafetyOfficer |
| GET | `/rescue-ops/isolation-verifications` | List IsolationVerifications | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/isolation-verifications/{id}` | Get one IsolationVerification | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/isolation-verifications/{id}/verify` | Verify a PENDING verification | SafetyOfficer |
| POST | `/rescue-ops/isolation-verifications/{id}/void` | Void a PENDING or VERIFIED verification | SafetyOfficer |
| POST | `/rescue-ops/entry-permits/{permitId}/roster-entries` | Schedule a roster entry | EntrySupervisor |
| GET | `/rescue-ops/roster-entries` | List RosterEntries | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/roster-entries/{id}` | Get one RosterEntry | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/roster-entries/{id}/check-in` | Check a rostered worker in | EntrySupervisor |
| POST | `/rescue-ops/roster-entries/{id}/check-out` | Check an ON_DUTY worker out | EntrySupervisor |
| POST | `/rescue-ops/entry-permits/{permitId}/atmospheric-readings` | Record an atmospheric reading | Attendant |
| GET | `/rescue-ops/atmospheric-readings` | List AtmosphericReadings | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/atmospheric-readings/{id}` | Get one AtmosphericReading | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/entry-permits/{permitId}/standby-assignments` | Schedule a standby window | RescueTeamLead |
| GET | `/rescue-ops/standby-assignments` | List StandbyAssignments | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/standby-assignments/{id}` | Get one StandbyAssignment | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/standby-assignments/{id}/check-in` | Check a standby rescuer in | RescueTeamLead |
| POST | `/rescue-ops/standby-assignments/{id}/release` | Release an ON_STANDBY or DEPLOYED assignment | RescueTeamLead |
| POST | `/rescue-ops/standby-assignments/{id}/cancel` | Cancel a SCHEDULED assignment | RescueTeamLead |
| POST | `/rescue-ops/entry-permits/{permitId}/incidents` | Report an incident | EntrySupervisor, SafetyOfficer, RescueTeamLead |
| GET | `/rescue-ops/incidents` | List Incidents | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/incidents/{id}` | Get one Incident | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/incidents/{id}/triage` | Triage a REPORTED or REOPENED incident | SafetyOfficer |
| POST | `/rescue-ops/incidents/{id}/escalate` | Escalate a TRIAGED incident | SafetyOfficer |
| POST | `/rescue-ops/incidents/{id}/resolve` | Resolve a TRIAGED or ESCALATED incident | SafetyOfficer |
| POST | `/rescue-ops/incidents/{id}/reopen` | Reopen a RESOLVED incident | SafetyOfficer |
| POST | `/rescue-ops/client-accounts/{accountId}/statements/generate` | Generate (or top up an identical-period OPEN) statement | BillingClerk |
| GET | `/rescue-ops/statements` | List BillingStatements | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| GET | `/rescue-ops/statements/{id}` | Get one BillingStatement | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |
| POST | `/rescue-ops/statements/{id}/finalize` | Finalize an OPEN or DISPUTED statement | BillingClerk |
| POST | `/rescue-ops/statements/{id}/dispute` | Dispute a FINALIZED statement | BillingClerk |
| POST | `/rescue-ops/statements/{id}/adjustments` | Append a CREDIT_ADJUSTMENT line to a DISPUTED statement | BillingClerk |
| POST | `/rescue-ops/statements/{id}/void` | Void a FINALIZED or DISPUTED statement | BillingClerk |
| POST | `/rescue-ops/statements/{id}/pay` | Pay a FINALIZED statement (exact amount only) | BillingClerk |
| GET | `/rescue-ops/statements/{id}/lines` | List StatementLines of a statement | OperationsManager, EntrySupervisor, Attendant, RescueTeamLead, SafetyOfficer, BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_IDENTITY_NOT_QUALIFIED` | 403 |
| `ERR_PERSONNEL_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_SPACE_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_VERIFICATION_NOT_FOUND` | 404 |
| `ERR_ROSTER_ENTRY_NOT_FOUND` | 404 |
| `ERR_READING_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_TIME_RANGE` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PERMIT_INVALID_STATE` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_VERIFICATION_INVALID_STATE` | 409 |
| `ERR_ROSTER_INVALID_STATE` | 409 |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 |
| `ERR_INCIDENT_INVALID_STATE` | 409 |
| `ERR_STATEMENT_INVALID_STATE` | 409 |
| `ERR_READING_KIND_NOT_ALLOWED` | 409 |
| `ERR_READING_OUT_OF_RANGE` | 422 |
| `ERR_RESCUE_PLAN_NOT_APPROVED` | 409 |
| `ERR_ISOLATION_NOT_VERIFIED` | 409 |
| `ERR_ATMOSPHERE_OUT_OF_LIMITS` | 409 |
| `ERR_PRE_ENTRY_READING_STALE` | 409 |
| `ERR_RESCUE_TEAM_UNDERSTAFFED` | 409 |
| `ERR_OUTSIDE_PLANNED_WINDOW` | 409 |
| `ERR_OPEN_INCIDENTS_EXIST` | 409 |
| `ERR_ENTRANTS_STILL_INSIDE` | 409 |
| `ERR_NO_ATTENDANT_ON_DUTY` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_MAX_ENTRANTS_EXCEEDED` | 409 |
| `ERR_PERSONNEL_ALREADY_ON_DUTY` | 409 |
| `ERR_RELIEF_TARGET_NOT_ON_DUTY` | 409 |
| `ERR_SPACE_OUT_OF_SERVICE` | 409 |
| `ERR_SPACE_OCCUPIED` | 409 |
| `ERR_CHECKIN_WINDOW_NOT_OPEN` | 409 |
| `ERR_CHECKIN_WINDOW_EXPIRED` | 409 |
| `ERR_INSUFFICIENT_REST` | 409 |
| `ERR_STANDBY_OVERLAP` | 409 |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 |
| `ERR_PERSONNEL_NOT_QUALIFIED` | 422 |
| `ERR_SHIFT_DURATION_EXCEEDS` | 422 |
| `ERR_SPACE_NOT_PERMIT_REQUIRED` | 422 |
| `ERR_CLIENT_CREDIT_HOLD` | 402 |
| `ERR_PERMITS_STILL_OPEN` | 409 |
| `ERR_PARTIAL_PAYMENT` | 422 |

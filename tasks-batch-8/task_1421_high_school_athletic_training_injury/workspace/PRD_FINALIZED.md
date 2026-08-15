# Athletic Training Injury Management API — Product Requirements Document

## 1. Introduction

A high-school athletic trainer carries an unusual operational burden: they are simultaneously the compliance gatekeeper who decides whether a student may practice at all, the logistics coordinator who staffs simultaneous events across several venues, the safety officer who enforces heat and lightning policy in real time, the clinician who documents injuries and steers athletes through graduated return-to-play, the liaison who keeps physicians and families informed, and the quartermaster who stretches a fixed annual supply budget. Each of these duties generates records that athletic associations, school districts, and insurers may later inspect, so the data behind them must be complete, attributable, and internally consistent.

This document specifies the API for a High School Athletic Training & Injury Management system — the system of record for that entire workflow. Several design pillars recur throughout. An athlete's clearance to participate is never a hand-set flag: it is a derived posture the server recomputes after every relevant change, from a newly verified physical to an expiring baseline concussion test. The system runs on a logical clock so that every time-dependent rule — expirations, dwell windows, escalation timers — behaves deterministically. Duties are segregated: the staff member who records a physical may not verify it, the author of an emergency plan may not approve it, and the requester of a purchase may not approve the spend. The stockroom is an append-only ledger whose balances are always derivable from history. And the two workflows where one record legitimately supersedes another — emergency-plan activation and return-to-play protocol replacement — are guarded by optimistic concurrency so that a client working from a stale view cannot silently overwrite a newer one.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven roles: `SystemAdmin`, `AthleticTrainer`, `AthleticDirector`, `SchoolNurse`, `Physician`, `TeamCoach`, and `ParentGuardian`. A request missing either header, or presenting a role string outside that set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the caller's role is not among the roles an endpoint authorizes, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

What `X-User-ID` means depends on the role. When `X-User-Role` is `AthleticTrainer`, `AthleticDirector`, `SchoolNurse`, `Physician`, or `TeamCoach`, `X-User-ID` is the `id` of the acting `Staff` record; ownership checks on any resource that references a `Staff` member compare the resource's staff foreign-key field to `X-User-ID`. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `recorded_by_staff_id` on an inventory ledger entry the admin posts) but never compares it to any entity's `id`. When `X-User-Role` is `ParentGuardian`, `X-User-ID` is likewise an opaque string — it is matched against the `guardian_user_id` field stored on the athlete record, and that comparison is the entire basis of guardian ownership.

Three ownership rules are enforced on top of role checks, each rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). A `ParentGuardian` may read an athlete's detail, list guardian notifications, and acknowledge a notification only for the athlete whose `guardian_user_id` equals the caller's `X-User-ID`. An `AthleticTrainer` acknowledging, declining, or checking into a coverage assignment must be the assignee — the assignment's `staff_id` must equal `X-User-ID`. A `Physician` filing a referral report must be the physician named on that referral — the referral's `physician_staff_id` must equal `X-User-ID`.

The `TeamCoach` role is deliberately read-only and excluded from medical records: coaches may read staff, athletes, clearance summaries, venues, venue activity status, events, coverage status, coverage assignments, emergency action plans, supply items, and weather readings, but requests to injury, referral, return-to-play, physical, baseline-test, or guardian-notification resources are rejected with `ERR_FORBIDDEN_ROLE`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Automated Time Sweeps

Every rule in this document that says "now" or "the current time" refers to the server's **logical clock**, never to wall-clock time. At startup, before any explicit adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never silently falls back to wall-clock time thereafter.

A `SystemAdmin`-only test-driving capability moves the clock: the caller supplies a `to_iso8601` instant and receives the resulting `current_utc` back. Every such adjustment runs an **auto-transition sweep** across time-gated records before the response returns:

- Recorded and verified pre-participation physicals whose validity has run out move to `EXPIRED` — the boundary is inclusive, so a physical expires the moment the clock reaches its `expires_on`.
- `CURRENT` baseline concussion tests move to `EXPIRED` the moment the clock reaches `valid_until` (also inclusive).
- Physician referrals still waiting in `REQUESTED` or `SCHEDULED` move to `EXPIRED` once the clock is strictly later than `due_by` — at the exact `due_by` instant the referral is still actionable.
- Guardian notifications in `SENT` move to `ESCALATED` once the clock reaches twenty-four hours after `sent_at` (inclusive) without an acknowledgement.
- After the sweep, every affected athlete's `participation_posture` is recomputed per §3.1.

### 2.5. Common Resource Properties

All primary resources — staff, athletes, physicals, baseline tests, venues, emergency action plans, events, coverage assignments, injury evaluations, referrals, return-to-play protocols, guardian notifications, supply items, restock orders, and supply budgets — carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-01T12:00:00.000Z`) recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp in the same format, refreshed on every change to the resource's properties.
- **`version` (integer):** a system-managed integer that increments with every modification to the resource, including modifications the server makes itself while reconciling derived state.

Two record types are deliberately leaner. An `EnvironmentalReading` and an `InventoryTransaction` are immutable observations: each carries only `id` and `created_at` — both `updated_at` and `version` are absent, and neither resource can be edited after creation.

### 2.6. Derived State and System Reconciliation

Several resources carry fields that clients never write directly: an athlete's `participation_posture` and `posture_reasons`, an event's `required_trainer_count` and `active_assignment_count`, a venue's `active_eap_id`, a supply item's `current_stock` and `stock_status`, and a budget's `realized_spend_cents`, `committed_spend_cents`, and `available_cents`. The server recomputes these immediately whenever a triggering mutation occurs — recording a physical, declining an assignment, appending a ledger entry, approving an order — and during the clock sweep of §2.4.

Reconciliation cascades across entity boundaries and may hop more than once: suspending an event holds its assignments and queues family notifications; filing a physician report of `NOT_CLEARED` terminates a return-to-play protocol, which drops the injury back to treatment, which recomputes the athlete's posture. Each reconciliation that changes a resource's stored properties is itself a mutation of that resource: it refreshes `updated_at` and increments `version` on every entity that carries those fields. State alignment is never left to the client — when a bubble-up criterion becomes satisfied or stops being satisfied, the server moves the affected resource on its own.

### 2.7. Optimistic Concurrency Control

Two write operations require an explicit optimistic-concurrency field, because each of them legitimately supersedes an existing record and therefore cannot rely on a state conflict to detect staleness.

Creating a return-to-play protocol on an injury requires the request body to carry `expected_injury_version` equal to the injury's current `version`. If another writer has advanced the injury's version since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The injury row is the concurrency anchor precisely because a new protocol may lawfully supersede an `ACTIVE` one: protocol creation bumps `InjuryEvaluation.version`, so a stale `expected_injury_version` proves the caller's view of the injury is old.

Activating an emergency action plan works the same way against its venue: the request must carry `expected_venue_version` matching the venue's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Activation lawfully supersedes the venue's currently `ACTIVE` plan and bumps `Venue.version`, so the venue row anchors the check.

Endpoints not named in this section do not take a version field; the version check, where it exists, runs before all business logic.

### 2.8. Nested Resource Retrieval and Missing References

The API enforces strict, left-to-right validation of every identifier in a request path. When a path nests one resource beneath another, the parent identifier is resolved first; the request is rejected immediately with the 404 error that corresponds to the *first* identifier that does not match an existing record, before any later identifier is even examined. Each resource family has its own not-found error so the caller learns exactly what was missing: `ERR_ATHLETE_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_INJURY_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`, `ERR_EAP_NOT_FOUND`, `ERR_PHYSICAL_NOT_FOUND`, `ERR_BASELINE_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_SUPPLY_ITEM_NOT_FOUND`, `ERR_RESTOCK_ORDER_NOT_FOUND`, and `ERR_BUDGET_NOT_FOUND`. A path identifier that cannot be parsed as a UUID at all — the `id` format §2.5 pins — draws the generic `ERR_NOT_FOUND` rather than the family-specific one, and so does a path identifier addressing a resource family with no more specific error of its own (coverage assignments, environmental readings, and inventory transactions have none). References supplied in request bodies — an `athlete_id` on a new physical, a `venue_id` on a new event, a `supply_item_id` on a ledger entry — are validated for existence with the same family-specific errors before business rules run; the parse screen is a path-identifier rule only, so a malformed body reference draws its family's not-found error, never the generic one.

### 2.9. Validation Priority Ordering

Every request flows through a fixed validation pipeline, and the earliest failing stage determines which error the caller receives. The stages, in order:

1. **User context.** Both headers are present and the role is recognized — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The caller's role is authorized for the endpoint — otherwise `ERR_FORBIDDEN_ROLE`.
3. **Ownership scope.** The guardian, assignee, and named-physician rules of §2.1 — otherwise `ERR_OWNERSHIP_MISMATCH`.
4. **Existence.** Path identifiers resolve left-to-right, then body references resolve — otherwise the appropriate 404 from §2.8.
5. **Optimistic concurrency.** Where §2.7 applies, the expected-version field must match the parent's current `version` — otherwise `ERR_STALE_VERSION`. This check runs before all business logic.
6. **State.** The target resource is in a from-state the requested transition allows, including terminal-state lockdown, duplicate-action attempts, and the creation-time state requirements of §3 (an event must be `SCHEDULED` or `COVERED` to accept a coverage assignment; an injury must be `OPEN`, `UNDER_CARE`, or `RTP_IN_PROGRESS` to accept a referral; an injury must be `UNDER_CARE` or `RTP_IN_PROGRESS` to accept a new protocol) — otherwise `ERR_INVALID_STATE`.
7. **Safety gates.** Venue emergency-plan presence, heat-tier and lightning-hold blocks, return-to-play clearance authority, segregation of duties, symptom checks, physician-review requirements, guardian contact availability, and physical eligibility for protocol work.
8. **Temporal gates.** Coverage overlap for a trainer, venue double-booking buffers, the twenty-four-hour stage dwell, and the thirty-day injury close window.
9. **Reference quality.** Staff role and active-status requirements, discontinued items, reopen targets that are closed and same-athlete, and active venues for new events.
10. **Aggregate constraints.** Stock floors, fiscal-year uniqueness, one current baseline per athlete, and positive-quantity rules.
11. **Fiscal coverage.** Budget availability for order approval — otherwise `ERR_BUDGET_EXCEEDED`.

Field-shape validation — required fields present, enum values valid, date ranges sane — is listed last only for readability: malformed payloads and missing required fields short-circuit with `ERR_INVALID_REQUEST` before any business rule runs. When several business rules could reject the same request, the ordering that decides the surfaced error is: state before safety, safety before temporal, temporal before reference quality, and all of those before fiscal coverage.

### 2.10. Money, Measurement, and Precision

All monetary amounts in the system are integer cents — `unit_cost_cents`, `extended_cost_cents`, `total_budget_cents`, and the budget spend fields are whole numbers with no fractional part. Derived monetary values are exact: an order's extended cost is the plain integer product of quantity and unit cost, and inventory valuations are reported as exact integer cents. Where a valuation policy must round an intermediate unit cost, it rounds half-up at the step the policy defines (§3.9), never with floating-point drift.

Environmental heat readings are recorded and compared at one decimal place, with tier lower bounds inclusive. All other quantities are integers with the bounds stated where each field is introduced. Temporal comparisons are made to whole-second precision, and every boundary is labeled inclusive or exclusive at the rule that uses it; date arithmetic (validity windows, due dates) is performed in UTC on the logical clock of §2.4.

## 3. Business Logic & Workflows

### 3.1. Athletes and the Road to Clearance

Everything begins with the athlete record. An `AthleticTrainer` — or a `SystemAdmin` performing initial data load — registers a student-athlete with a `full_name`, a `date_of_birth` as an ISO calendar date, a `grade` that must be an integer from 9 through 12 inclusive, a `sex` of `M` or `F`, a `primary_sport` drawn from the fourteen recognized sports (`FOOTBALL`, `SOCCER`, `BASKETBALL`, `BASEBALL`, `SOFTBALL`, `VOLLEYBALL`, `WRESTLING`, `LACROSSE`, `FIELD_HOCKEY`, `CROSS_COUNTRY`, `TRACK`, `SWIMMING`, `TENNIS`, `GOLF`), and a `team_level` of `VARSITY`, `JV`, or `FRESHMAN`. The guardian block — `guardian_name`, `guardian_user_id`, and optionally `guardian_email` and `guardian_phone` — anchors all later family communication: `guardian_user_id` is the opaque login string a `ParentGuardian` presents as `X-User-ID`, while `guardian_email` and `guardian_phone` determine which delivery channels are open (§3.8). A newly registered athlete starts with `participation_posture` set to `NOT_CLEARED` and `posture_reasons` holding the single code `NO_VERIFIED_PHYSICAL`. The athlete roster can be filtered by `primary_sport`, `team_level`, or `participation_posture` when staff need a scoped view.

**Pre-participation physicals** are recorded by a trainer or the school nurse. The record captures the `athlete_id`, the `exam_date` (which may not lie in the future relative to the logical clock — a later date is rejected with `ERR_INVALID_DATE_RANGE`), the free-text `examining_physician_name` (often an external provider), the `outcome` (`CLEARED`, `CLEARED_WITH_RESTRICTIONS`, `NOT_CLEARED`, or `DEFERRED`), and the `validity_policy` the district applies — `DISTRICT_13MO` or `STATE_SCHOOL_YEAR`. When the outcome is `CLEARED_WITH_RESTRICTIONS`, the detail belongs in `restriction_notes`, which is otherwise nullable. The server stamps `recorded_by_staff_id` from the caller's identity and computes `expires_on` from the exam date and policy: under `DISTRICT_13MO`, expiry falls thirteen calendar months after the `exam_date`, at the stroke of 00:00:00Z that day; under `STATE_SCHOOL_YEAR`, the physical remains valid through the end of the school year and expires at 00:00:00Z on August 1 — of the same calendar year when the exam month is January through July, or of the following calendar year when the exam month is August through December. The expiry boundary is inclusive: the moment the clock reaches `expires_on`, the physical is out of validity.

A recorded physical sits in `RECORDED` until a `SchoolNurse` verifies it. Verification requires the physical to still be `RECORDED` (any other status draws `ERR_INVALID_STATE`) and — this is the first segregation-of-duties rule — the verifying nurse may not be the staff member who recorded it: when `X-User-ID` equals the record's `recorded_by_staff_id`, the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful verification stamps `verified_by_staff_id` with the nurse's identity, moves the physical to `VERIFIED`, and recomputes the athlete's posture. A trainer who discovers a data-entry error can void a `RECORDED` physical, moving it to `VOIDED` and again recomputing posture. Physicals in either `RECORDED` or `VERIFIED` expire to `EXPIRED` during the clock sweep once the clock reaches `expires_on`; `EXPIRED` and `VOIDED` are terminal. Staff reviewing the paperwork can filter the physical list by `athlete_id`, `recorded_by_staff_id`, `verified_by_staff_id`, or `status`.

**Baseline concussion tests** follow a parallel intake. A trainer or nurse records the `athlete_id`, the `test_date` (no later than the logical clock, else `ERR_INVALID_DATE_RANGE`), the `instrument` used (`SCAT6`, `IMPACT`, or `SWAY`), and the four scores: `symptom_score` (an integer from 0 to 132), `memory_index` (0 to 100), `reaction_time_ms` (strictly positive milliseconds), and `balance_errors` (0 to 60). The server stamps `administered_by_staff_id` from the caller, computes `valid_until` as twenty-four calendar months after the `test_date` at 00:00:00Z that day, and starts the record in `CURRENT`. One athlete has at most one `CURRENT` baseline: recording a newer test for the same athlete moves the previously `CURRENT` test to `SUPERSEDED`, and — as §3.5 details — documenting a concussion for the athlete supersedes the current baseline as well. The clock sweep moves a `CURRENT` test to `EXPIRED` once the clock reaches `valid_until`, boundary inclusive. The baseline list filters by `athlete_id`, `administered_by_staff_id`, and `status`.

**The participation posture** is the system's answer to "may this athlete take the field today?" It is recomputed after every mutation to the athlete's physicals, baselines, injuries, return-to-play protocols, or referral reports, and during every clock sweep; no client endpoint moves it directly. The recompute walks five gates in strict order, and the first gate that matches wins:

1. `NOT_CLEARED` — no `VERIFIED` physical has ever existed for the athlete. `posture_reasons` becomes `[NO_VERIFIED_PHYSICAL]`.
2. `INELIGIBLE` — the latest `VERIFIED` physical has expired (the clock is at or past its `expires_on`), or that physical's outcome is `NOT_CLEARED` or `DEFERRED`, or the athlete has no `CURRENT` baseline whose `valid_until` lies in the future. Each failed condition is recorded in `posture_reasons`, drawn from `PHYSICAL_EXPIRED`, `PHYSICAL_OUTCOME_BLOCKS`, and `NO_CURRENT_BASELINE`.
3. `MEDICAL_HOLD` — the physical and baseline gates pass, but the athlete has an injury in `OPEN` or `REFERRED`, or has an `ACTIVE` concussion-type return-to-play protocol whose `recurrence_count` has reached two without a `COMPLETED` or `CLOSED` physician referral carrying a `report_clearance` of `CLEARED_FULL` or `CLEARED_RESTRICTED`. Reasons include `ACUTE_INJURY_OPEN` and/or `PHYSICIAN_REVIEW_PENDING` as applicable.
4. `CLEARED_WITH_RESTRICTIONS` — the higher gates pass, but the athlete has an injury in `UNDER_CARE` or `RTP_IN_PROGRESS`, or the latest `VERIFIED` physical's outcome is `CLEARED_WITH_RESTRICTIONS`. Reasons include `INJURY_RESTRICTIONS` and/or `PHYSICAL_RESTRICTIONS`.
5. `CLEARED` — every gate above passes, with no injury in `OPEN`, `UNDER_CARE`, `REFERRED`, or `RTP_IN_PROGRESS`. `posture_reasons` is empty.

The clearance detail view for an athlete exposes this computation directly: `athlete_id`, `participation_posture`, the ordered `posture_reasons`, the governing physical's `physical_expires_on`, and the governing baseline's `baseline_valid_until`.

### 3.2. Venues and Emergency Action Plans

A `SystemAdmin` registers each **venue** with a `venue_name`, a `venue_type` of `INDOOR` or `OUTDOOR`, a playing `surface` (`GRASS`, `TURF`, `COURT`, `TRACK`, `POOL`, or `GYM_FLOOR`), and the street `address` emergency medical services should use. Two fields configure lightning policy: `lightning_detection` (whether the venue has on-site detection; defaults to false) and `lightning_radius_miles`, the strike distance that triggers suspension, which must be strictly positive and defaults to 8.0 miles. `is_active` defaults to true; an inactive venue rejects new events with `ERR_VENUE_INACTIVE`. The computed `active_eap_id` is a nullable pointer to the venue's currently `ACTIVE` emergency action plan — null until one is activated — and the venue list can be filtered by `is_active` or `active_eap_id`.

**Emergency action plans** follow a deliberate draft–review–activate cycle. A trainer or the athletic director drafts a plan for a venue, supplying the `venue_id`, a human `version_label` that must be unique per venue (such as a season-and-revision tag), the `evacuation_route`, the `aed_location`, the `ems_contact` instructions, the `nearest_hospital`, and optionally a `supersedes_eap_id` declaring which earlier plan at the same venue this version replaces. The server stamps `authored_by_staff_id` from the caller and starts the plan in `DRAFT`. When the draft is ready, a trainer submits it, moving the plan from `DRAFT` to `PENDING_APPROVAL`; submission from any other state is rejected with `ERR_INVALID_STATE`.

Approval belongs to the `AthleticDirector` alone, and the second segregation-of-duties rule applies here: the approver may not be the plan's author, so when `X-User-ID` equals `authored_by_staff_id` the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. A clean approval stamps `approved_by_staff_id` and moves the plan from `PENDING_APPROVAL` to `APPROVED`; a rejection sends it back from `PENDING_APPROVAL` to `DRAFT` for revision — a loop that may repeat as many times as review requires. Both actions require the plan to actually be `PENDING_APPROVAL`, else `ERR_INVALID_STATE`.

Activation is the final step and carries the venue-level optimistic-concurrency contract of §2.7: the director activating an `APPROVED` plan must present `expected_venue_version` matching the venue's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the plan becomes `ACTIVE`, the venue's previously `ACTIVE` plan (if any) is moved to `SUPERSEDED` as a direct consequence of the activation, the venue's `active_eap_id` is re-pointed at the newly active plan, and `Venue.version` increments by one. `SUPERSEDED` is terminal; supersession is otherwise automatic — a plan never leaves `ACTIVE` except by being superseded. Plans can be listed with filters on `venue_id`, `supersedes_eap_id`, `authored_by_staff_id`, `approved_by_staff_id`, and `status`.

### 3.3. Scheduling Events and Staffing Coverage

Before any scheduling happens, a `SystemAdmin` maintains the staff registry: each record carries a `full_name`, a `role_type` drawn from `ATHLETIC_TRAINER`, `TEAM_COACH`, `PHYSICIAN`, `ATHLETIC_DIRECTOR`, and `SCHOOL_NURSE` — fixed at creation and immutable thereafter — a `sport_certifications` list naming the sports that staff member is certified to cover (empty by default), and an `is_active` flag (true by default) that the administrator flips to deactivate; inactive staff cannot be newly assigned to anything. The registry can be listed with `role_type` and `is_active` filters.

Trainers and the athletic director schedule **athletic events** by naming the event (`event_name`), its `sport` (the same fourteen-value sport enum as athletes), its `team_level`, its `event_type` (`PRACTICE`, `SCRIMMAGE`, `HOME_GAME`, `AWAY_GAME`, or `TOURNAMENT`), the `venue_id`, the `scheduled_start` and `scheduled_end` as ISO 8601 UTC instants, and the `expected_attendance` (zero or more). The end must be strictly after the start — a non-later end is rejected with `ERR_INVALID_DATE_RANGE`. The venue must be active (else `ERR_VENUE_INACTIVE`) and free of scheduling conflicts: if the venue already hosts a non-`CANCELLED` event whose scheduled window, padded by a thirty-minute buffer, collides with the proposed window, the new event is rejected with `ERR_VENUE_OVERLAP`. A created event starts in `SCHEDULED` with `active_assignment_count` at zero and its `required_trainer_count` computed as follows.

**How many trainers does an event need?** Every sport carries a contact level: `FOOTBALL`, `WRESTLING`, and `LACROSSE` are high-contact; `SOCCER`, `BASKETBALL`, `BASEBALL`, `SOFTBALL`, `FIELD_HOCKEY`, and `VOLLEYBALL` are medium-contact; `CROSS_COUNTRY`, `TRACK`, `SWIMMING`, `TENNIS`, and `GOLF` are low-contact. The base requirement for a high-contact sport is one trainer for a `PRACTICE` and two trainers for a `SCRIMMAGE`, `HOME_GAME`, `AWAY_GAME`, or `TOURNAMENT`; medium- and low-contact sports need one trainer regardless of event type. Three modifiers then apply, in this order: add one if the event is a `TOURNAMENT`; add one if the restricted-roster count — athletes whose `primary_sport` and `team_level` match the event and whose posture is `CLEARED_WITH_RESTRICTIONS` — is at least four; add one if `expected_attendance` is at least one thousand. The requirement is the base plus the modifiers, clamped so it never falls below one and never exceeds four. Because the restricted-roster count depends on athlete postures, the requirement is re-derived when posture changes alter that count.

**Coverage assignments** put a named trainer on an event. A trainer or the director creates one with the `event_id`, the `staff_id`, and a `coverage_role` of `PRIMARY` or `SECONDARY`. The event must be in `SCHEDULED` or `COVERED` — assigning to an event in any other state is rejected with `ERR_INVALID_STATE`. The referenced staff member must carry `role_type` `ATHLETIC_TRAINER` and be active; anyone else is rejected with `ERR_STAFF_ROLE_MISMATCH`. A trainer may not hold a `PRIMARY` assignment on another event whose half-open scheduled window overlaps the new event's — the overlap test treats each window as including its start and excluding its end, so back-to-back events where one ends exactly as the other begins do not conflict — and a violation is rejected with `ERR_COVERAGE_OVERLAP`. A created assignment starts in `ASSIGNED`, increments the event's `active_assignment_count` by one, and when that count reaches `required_trainer_count` the event bubbles up from `SCHEDULED` to `COVERED` on its own. An assignment counts toward `active_assignment_count` while it is `ASSIGNED`, `ACKNOWLEDGED`, `ON_SITE`, or `ON_HOLD`.

The assignee then works the assignment through its life. **Acknowledging** moves `ASSIGNED` to `ACKNOWLEDGED` and stamps `acknowledged_at`; **declining** moves `ASSIGNED` to `DECLINED`; **checking in** on the day moves `ACKNOWLEDGED` to `ON_SITE` and stamps `checked_in_at`. All three are self-service actions: the caller must be the assignment's `staff_id`, otherwise `ERR_OWNERSHIP_MISMATCH`, and each requires the stated from-state, otherwise `ERR_INVALID_STATE`. A decline also subtracts one from the event's `active_assignment_count`, and if the event was `COVERED` and the decrement drops the count below `required_trainer_count`, the event bubbles back down from `COVERED` to `SCHEDULED`. After the event, a trainer completes an assignment that is `ON_SITE` or `ACKNOWLEDGED`, moving it to `COMPLETED`; an assignment sitting in `ON_HOLD` reaches `COMPLETED` only through the event-completion cascade of §3.4. A trainer or the director can also cancel an assignment that is `ASSIGNED` or `ACKNOWLEDGED`, moving it to `CANCELLED` with the same count decrement and bubble-down effect as a decline. `COMPLETED`, `DECLINED`, and `CANCELLED` are terminal. The assignment list filters by `event_id`, `staff_id`, and `status`, and the per-event coverage view reports `event_id`, `required_trainer_count`, `active_assignment_count`, and `is_covered` — the last being true exactly when the active count meets the requirement.

**Completing and cancelling events.** A trainer completes an `IN_PROGRESS` event, moving it to `COMPLETED`; every assignment of that event in `ON_SITE`, `ACKNOWLEDGED`, or `ON_HOLD` moves to `COMPLETED` with it. A trainer or the director cancels an event from `SCHEDULED`, `COVERED`, or `SUSPENDED_WEATHER` — the request is rejected with `ERR_INVALID_STATE` from any other state — moving the event to `CANCELLED` and cascading every assignment in `ASSIGNED`, `ACKNOWLEDGED`, or `ON_HOLD` to `CANCELLED`. Both outcomes are terminal. The event list filters by `venue_id`, `status`, and `sport`.

### 3.4. Heat Policy, Lightning Holds, and Weather Suspensions

Environmental observations enter the system as **weather readings**, posted by a trainer or a `SystemAdmin`. Each reading names the `venue_id`, the `reading_type` (`HEAT_WBGT` or `LIGHTNING_STRIKE`), the `recorded_at` instant the phenomenon was observed (no later than the logical clock, else `ERR_INVALID_DATE_RANGE`), and the `source` (`ON_SITE_SENSOR`, `WEATHER_SERVICE`, or `MANUAL`). The measurement itself is type-specific: a `HEAT_WBGT` reading must carry `value_wbgt_f` — the wet-bulb globe temperature in degrees Fahrenheit, recorded at one decimal place — while a `LIGHTNING_STRIKE` reading must carry `strike_distance_miles`, zero or greater. Posting a reading whose type-specific value is absent is rejected with `ERR_INVALID_REQUEST`. The reading history filters by `venue_id` and `reading_type`.

**Heat tiers** translate a WBGT value into an activity restriction level, and the breakpoint set depends on context: `TOURNAMENT` events use the state-association table, everything else — including venue-level status checks — uses the district table. Under the district table, a reading below 80.0 degrees is `NORMAL`; 80.0 up to but not including 84.0 is `CAUTION`; 84.0 up to but not including 87.0 is `MODERATE`; 87.0 up to but not including 90.0 is `SEVERE`; and 90.0 or above is `EXTREME`. Under the state-association table the same five tiers begin at 82.0, 86.0, 89.0, and 92.0 degrees respectively. Tier lower bounds are inclusive — a district reading of exactly 84.0 degrees is `MODERATE`, not `CAUTION`. The current tier at a venue is the tier of the `HEAT_WBGT` reading with the latest `recorded_at`; if several readings share that timestamp, the most recently created one governs, and a venue with no heat readings at all is treated as `NORMAL`. Indoor venues ignore heat tiers entirely. An `EXTREME` tier at an `OUTDOOR` venue is a hard stop: it suspends every in-progress outdoor event there (reason `HEAT`) and blocks any outdoor start or resume with `ERR_HEAT_TIER_EXTREME`.

**Lightning holds** work on a countdown that each new strike resets. A strike *counts* at a venue when its `strike_distance_miles` is no greater than the venue's `lightning_radius_miles` — a strike at exactly the radius counts. The hold runs until the latest `recorded_at` among counting strikes plus the hold window: thirty minutes in ordinary district contexts, forty-five minutes for `TOURNAMENT` events (the state-association rule). Every new counting strike re-raises the hold from its own observation time. The hold is active while the clock is strictly before that all-clear instant; at the exact all-clear instant, starting and resuming are allowed again. While a hold is active, event starts and resumes at the venue are rejected with `ERR_LIGHTNING_HOLD_ACTIVE`.

**Starting an event** is therefore a gated act. A trainer starts an event only from `COVERED` (any other state draws `ERR_INVALID_STATE`), only while the venue has an `ACTIVE` emergency action plan — a null `active_eap_id` draws `ERR_NO_ACTIVE_EAP` — only while the venue's current heat tier is not `EXTREME` for an `OUTDOOR` event, and only while no lightning hold is active at the venue. Success moves the event from `COVERED` to `IN_PROGRESS`.

**Suspension** strikes an in-progress event in two ways. A trainer may suspend manually, which records the `suspension_reason` `MANUAL`. The system suspends automatically when a newly posted reading pushes the venue into an `EXTREME` heat tier (reason `HEAT`) or lands a counting lightning strike (reason `LIGHTNING`). Either way the event moves from `IN_PROGRESS` to `SUSPENDED_WEATHER` with `suspension_reason` set, and two cascades follow: every coverage assignment of the event in `ACKNOWLEDGED` or `ON_SITE` moves to `ON_HOLD` with its pre-hold status snapshotted into `pre_hold_status`, and an `EVENT_SUSPENSION` guardian notification is queued for every athlete on the event roster — athletes whose `primary_sport` and `team_level` match the event — who carries an injury in `OPEN`, `UNDER_CARE`, `REFERRED`, or `RTP_IN_PROGRESS`.

**Resuming** is gated by whatever caused the stop. The event must be `SUSPENDED_WEATHER` (else `ERR_INVALID_STATE`); a `LIGHTNING` suspension may resume only once the clock has reached the lightning all-clear instant (earlier attempts draw `ERR_LIGHTNING_HOLD_ACTIVE`); a `HEAT` suspension may resume only while the venue's latest heat tier is no longer `EXTREME` (otherwise `ERR_HEAT_TIER_EXTREME`); a `MANUAL` suspension carries no environmental gate. On resumption the event returns to `IN_PROGRESS`, `suspension_reason` is cleared to null, and each `ON_HOLD` assignment returns to its snapshotted `pre_hold_status` — `ACKNOWLEDGED` or `ON_SITE` — after which `pre_hold_status` is cleared. This in-and-out weather loop can repeat across a long afternoon. Anyone with read access can check a venue's environmental gate view, which reports the `venue_id`, the `current_heat_tier` (computed on the district table at venue level), whether a `lightning_hold_active` flag is set, and the `lightning_hold_until` instant.

### 3.5. Documenting Injuries and Managing Care

When an athlete is hurt, the evaluating `AthleticTrainer` documents an **injury evaluation**: the `athlete_id`, optionally the `event_id` where it happened, the `body_region` (`HEAD_NECK`, `SHOULDER`, `ARM_HAND`, `TRUNK`, `HIP_PELVIS`, `KNEE`, `LOWER_LEG`, `ANKLE_FOOT`, or `SYSTEMIC`), the `injury_type` (`CONCUSSION`, `FRACTURE`, `SPRAIN`, `STRAIN`, `LACERATION`, `HEAT_ILLNESS`, `CARDIAC`, or `OTHER`), the `severity` (`MINOR`, `MODERATE`, `SEVERE`, or `CRITICAL`), a free-text `mechanism`, the `evaluated_at` instant (no later than the logical clock, else `ERR_INVALID_DATE_RANGE`), and optionally a `restricted_activities` list drawn from `PRACTICE`, `CONTACT`, `GAME`, `CONDITIONING`, and `WEIGHTS` (empty by default). The server stamps `evaluated_by_staff_id` from the caller and opens the record in `OPEN`.

A new injury may document the recurrence of an old one: supplying `reopen_of_id` links the new evaluation to a prior injury, which must be `CLOSED` and must belong to the same athlete — anything else is rejected with `ERR_REFERENCED_INJURY_NOT_CLOSED`. A plain first injury carries `recurrence_count` zero; a recurrence carries the referenced injury's `recurrence_count` plus one.

Documenting an injury has immediate ripple effects. An `INJURY_INITIAL` guardian notification is queued for the athlete (channel selection per §3.8). If the `injury_type` is `CONCUSSION`, the athlete's `CURRENT` baseline test — whose scores predate the injury and can no longer serve as a comparison — moves to `SUPERSEDED`. And the athlete's posture is recomputed; an `OPEN` injury ordinarily drives it to `MEDICAL_HOLD`. The injury register filters by `athlete_id`, `event_id`, `evaluated_by_staff_id`, `reopen_of_id`, `status`, and `injury_type`.

From `OPEN`, the care continuum is trainer-driven. **Beginning care** moves an injury from `OPEN` — or from `REFERRED` once the physician loop of §3.6 has run — into `UNDER_CARE`; either from-state is accepted, anything else draws `ERR_INVALID_STATE`, and the athlete's posture is recomputed (typically easing to `CLEARED_WITH_RESTRICTIONS`). **Resolving** moves an injury from `UNDER_CARE` to `RESOLVED`, stamps `resolved_at`, and recomputes posture — the athlete may finally reach `CLEARED` — but resolution is refused while an `ACTIVE` return-to-play protocol still exists for the injury (the refusal is `ERR_INVALID_STATE`; the protocol must first be cleared or terminated per §3.7).

Resolution is not necessarily the end. If symptoms recur, a trainer **reopens** the injury — supplying a free-text `reason` — moving it from `RESOLVED` back to `OPEN`, clearing `resolved_at` to null, and recomputing the posture back into hold territory. When a resolution holds, the trainer **closes** the injury once the clock has reached thirty days past `resolved_at`; the boundary is inclusive, and an earlier attempt is rejected with `ERR_CLOSE_WINDOW_NOT_MET`. `CLOSED` is terminal — and, per the recurrence rule above, is the only status a future injury may reference as its `reopen_of_id` predecessor.

### 3.6. Physician Referrals and Clearance Reports

Injuries that need more than the training room are referred out. A trainer creates a **physician referral** with the `injury_id`, the `physician_staff_id` of the consulting physician — which must reference a staff member whose `role_type` is `PHYSICIAN`, otherwise `ERR_STAFF_ROLE_MISMATCH` — a free-text `reason`, and an `urgency` of `ROUTINE`, `URGENT`, or `EMERGENT`. The injury must be in `OPEN`, `UNDER_CARE`, or `RTP_IN_PROGRESS`; any other status is rejected with `ERR_INVALID_STATE`. The referral copies its `athlete_id` from the injury, starts in `REQUESTED`, and computes its `due_by` from the creation timestamp: fourteen days out for `ROUTINE`, three days for `URGENT`, one day for `EMERGENT`. Creation also moves the injury — an injury in `OPEN` or `UNDER_CARE` advances to `REFERRED`, while an injury already in `RTP_IN_PROGRESS` keeps its status — and queues a `REFERRAL_REQUEST` guardian notification. The referral list filters by `injury_id`, `athlete_id`, `physician_staff_id`, and `status`.

A trainer then **schedules** the appointment, moving `REQUESTED` to `SCHEDULED` and recording the supplied `appointment_at`. The physician **completes** the referral by filing the report — `report_diagnosis` as free text and `report_clearance` as `CLEARED_FULL`, `CLEARED_RESTRICTED`, or `NOT_CLEARED` — which moves the referral from `SCHEDULED` to `COMPLETED` and stamps `reported_at`. Completion is personal: the caller's `X-User-ID` must equal the referral's `physician_staff_id`, else `ERR_OWNERSHIP_MISMATCH`.

The report can cascade. When `report_clearance` is `NOT_CLEARED` and an `ACTIVE` return-to-play protocol exists for the injury, the protocol moves to `TERMINATED` as a direct consequence of the report; that termination drops the injury from `RTP_IN_PROGRESS` back to `UNDER_CARE`; and the injury change recomputes the athlete's posture — three hops from one physician signature. When the clearance is `CLEARED_FULL` or `CLEARED_RESTRICTED`, a `CLEARANCE_GRANTED` guardian notification is queued.

A completed report can be questioned: the trainer requests an addendum, supplying the `question` to be answered, which moves the referral from `COMPLETED` to `ADDENDUM_REQUESTED`. The physician's next completion — allowed from `SCHEDULED` or `ADDENDUM_REQUESTED`, subject to the same ownership rule — files the amended report: the report fields are overwritten, `reported_at` is refreshed, and the same cascades as a fresh completion apply. This addendum loop may repeat. Once the matter is settled, the trainer **closes** the referral (`COMPLETED` to `CLOSED`) or, earlier in the life cycle, **cancels** it (from `REQUESTED` or `SCHEDULED` to `CANCELLED`); both actions enforce their from-states with `ERR_INVALID_STATE`. Finally, the clock sweep expires any referral still in `REQUESTED` or `SCHEDULED` once the clock is strictly later than `due_by` — at exactly `due_by` the referral remains actionable — moving it to `EXPIRED`.

### 3.7. The Graduated Return-to-Play Protocol

An injury that needs structured reconditioning gets a **return-to-play protocol**. A trainer activates one on an injury in `UNDER_CARE` or `RTP_IN_PROGRESS` — any other injury state is rejected with `ERR_INVALID_STATE` — supplying the `protocol_type` (currently always `GRADUATED_6_STAGE`) and the `expected_injury_version` required by §2.7; a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). Activation starts the protocol `ACTIVE` at `current_stage` 1 with `stage_entered_at` set to the current clock and `recurrence_count` at zero, copies `athlete_id` from the injury, and derives `clearance_authority_required`: `PHYSICIAN` when the injury is a `CONCUSSION` or its severity is `SEVERE` or `CRITICAL`, otherwise `TRAINER`. Because product semantics allow a fresh protocol to replace an abandoned one, activation supersedes: any previously `ACTIVE` protocol on the same injury moves to `TERMINATED` with a corresponding `stage_history` entry. The injury itself moves from `UNDER_CARE` (or from `RTP_IN_PROGRESS`, when a replacement supersedes) into `RTP_IN_PROGRESS`, and `InjuryEvaluation.version` increments by one — the bump that invalidates any other client's stale view. The athlete's posture is recomputed. Protocols filter by `injury_id`, `athlete_id`, `cleared_by_staff_id`, and `status`.

Progress through the six stages is journaled in `stage_history`, an append-only log of stage exits. Activation opens the log empty — entering stage 1 appends nothing — and the log grows only when the protocol leaves a stage: each advance, regress, clearance, or termination, including the automatic terminations of the supersede and `NOT_CLEARED`-report cascades, appends exactly one entry, already closed at append time, recording the `stage` being exited, that stage's `entered_at` and `exited_at` instants, and the `exit_reason` — `ADVANCED`, `REGRESSED`, `CLEARED`, or `TERMINATED`.

**Advancing** one stage (from N to N+1, where N runs 1 through 5) is a trainer action with five gates, applied under the global ordering of §2.9 — state first, then the safety gates, then the temporal dwell. The protocol must be `ACTIVE` with `current_stage` at most 5, else `ERR_INVALID_STATE`. The athlete must have dwelt in the current stage for at least twenty-four hours — exactly twenty-four hours qualifies, anything less draws `ERR_RTP_STAGE_DWELL_NOT_MET`. The athlete must be symptom-free: the request's `symptom_check_passed` must be true, and a false value is rejected with `ERR_SYMPTOMS_REPORTED` (HTTP 422). The athlete's posture must not be `INELIGIBLE` or `NOT_CLEARED` — a lapse in physical or baseline validity mid-protocol blocks advancement with `ERR_PHYSICAL_EXPIRED`. And two physician-review gates protect the high-risk cases: when the advance would carry a `CONCUSSION` protocol into stage 5, a `COMPLETED` or `CLOSED` referral for this injury carrying a `report_clearance` of `CLEARED_FULL` or `CLEARED_RESTRICTED` must exist, else `ERR_RTP_PHYSICIAN_REVIEW_REQUIRED`; the identical requirement applies to any injury type once the protocol's `recurrence_count` reaches two. A successful advance increments `current_stage`, resets `stage_entered_at` to now, and appends an `ADVANCED` history entry; if the injury had fallen back to `UNDER_CARE` after a regression, the advance returns it to `RTP_IN_PROGRESS` and recomputes posture.

**Regressing** is how recurrent symptoms are handled: the trainer reports the recurrence (with optional `notes`), and the protocol — which must be `ACTIVE` — appends a `REGRESSED` history entry, returns `current_stage` to 1, resets `stage_entered_at`, and increments `recurrence_count` by one. The injury falls from `RTP_IN_PROGRESS` back to `UNDER_CARE`, the posture recompute that follows lands the athlete in `CLEARED_WITH_RESTRICTIONS`, and an `RTP_REGRESSION` guardian notification is queued. The injury returns to `RTP_IN_PROGRESS` only through the next successful advance.

**Clearing** finishes the protocol. The protocol must be `ACTIVE` and sitting at `current_stage` 6 with the same twenty-four-hour dwell met (else `ERR_INVALID_STATE`, then `ERR_RTP_STAGE_DWELL_NOT_MET`), and the same posture gate as advancement applies (`ERR_PHYSICAL_EXPIRED`). Authority is per `clearance_authority_required`: when it is `PHYSICIAN`, only a `Physician` caller may clear — a trainer's attempt is rejected with `ERR_CLEARANCE_AUTHORITY_INSUFFICIENT` (HTTP 403); when it is `TRAINER`, either an `AthleticTrainer` or a `Physician` may clear. The caller's `clearance_notes` accompany the act. Clearance stamps `cleared_by_staff_id` and `cleared_at`, appends a `CLEARED` history entry for stage 6, moves the protocol to `CLEARED`, moves the injury from `RTP_IN_PROGRESS` to `RESOLVED` with `resolved_at` set, recomputes the athlete's posture, and queues a `CLEARANCE_GRANTED` guardian notification.

**Terminating** ends a protocol without clearance: a trainer or physician terminates an `ACTIVE` protocol (with an optional `reason`), and termination also happens automatically when a physician's `NOT_CLEARED` report lands (§3.6) and when a replacement protocol supersedes it. Termination appends a `TERMINATED` history entry; if the injury is in `RTP_IN_PROGRESS` and no other `ACTIVE` protocol remains for it, the injury returns to `UNDER_CARE` and the athlete's posture is recomputed. `CLEARED` and `TERMINATED` are terminal.

### 3.8. Notifying and Hearing Back from Guardians

Guardian notifications are created by the system, never drafted by hand: `INJURY_INITIAL` when an injury is documented, `REFERRAL_REQUEST` when a referral is created, `RTP_REGRESSION` when a protocol regresses, `CLEARANCE_GRANTED` when a physician report or a protocol clearance grants clearance, and `EVENT_SUSPENSION` when weather stops an event. Each notification records the `athlete_id`, the relevant `injury_id` or `referral_id` where one exists (both nullable), its `notification_type`, a rendered `subject`, an `attempts` counter starting at zero, and a `channel` chosen at creation: `EMAIL` when the athlete's `guardian_email` is present, otherwise `PHONE`. Every notification starts `QUEUED`.

A trainer sends what is queued. Sending requires the notification to be `QUEUED` or `FAILED` (any other state draws `ERR_INVALID_STATE`) and requires the channel's contact point to exist on the athlete record — `guardian_email` for an `EMAIL` notification, `guardian_phone` for a `PHONE` one — otherwise the send is rejected with `ERR_GUARDIAN_CONTACT_MISSING`. A successful delivery moves the notification to `SENT`, stamps `sent_at`, and increments `attempts`. A transient carrier failure — surfaced in this environment as a `PHONE`-channel notification whose `guardian_phone` is the literal string `UNREACHABLE` — moves the notification to `FAILED` instead, still incrementing `attempts`. A trainer requeues a `FAILED` notification with the retry action, moving it back to `QUEUED`; the queue–fail–retry loop can repeat until delivery succeeds.

Delivery is not the end of the story: families must acknowledge. The clock sweep moves a `SENT` notification to `ESCALATED` once the clock reaches twenty-four hours after `sent_at` (the boundary is inclusive) with no acknowledgement recorded. Escalation does not close the loop — a `ParentGuardian` may acknowledge a notification in either `SENT` or `ESCALATED`, moving it to `ACKNOWLEDGED` and stamping `acknowledged_at`, provided the caller's `X-User-ID` equals the athlete's `guardian_user_id` (otherwise `ERR_OWNERSHIP_MISMATCH`). `ACKNOWLEDGED` is terminal. When guardians list notifications they see only their own child's; the list filters by `athlete_id`, `injury_id`, `referral_id`, `status`, and `notification_type`.

### 3.9. Supplies: Stockroom Ledger, Valuation, and Purchasing

The supply room starts with its catalog. A `SystemAdmin` creates each **supply item** with an `item_name`, a `category` (`TAPE`, `FIRST_AID`, `HYDRATION`, `EQUIPMENT`, or `MEDICATION`), a `unit` of measure (`ROLL`, `EACH`, `CASE`, `LITER`, or `BOX`), a `par_level` (the desired shelf quantity, at least 1), a `reorder_threshold` (zero or more but strictly below `par_level`), a `unit_cost_cents` standard cost (strictly positive integer cents), and `is_discontinued` (default false). A new item has `current_stock` zero and `stock_status` `OUT_OF_STOCK`. A `SystemAdmin` may later adjust `par_level`, `reorder_threshold`, `unit_cost_cents`, or `is_discontinued`; when the threshold changes, `stock_status` is recomputed against the unchanged stock figure. The catalog filters by `category` and `stock_status`.

Every physical movement of stock is an **inventory transaction**, and the ledger is append-only — there is no update and no delete. A trainer or a `SystemAdmin` appends an entry with the `supply_item_id`, the `txn_type` (`RESTOCK`, `USAGE`, `WASTE`, or `ADJUSTMENT`), a `quantity` that is always strictly positive (zero or negative draws `ERR_QUANTITY_NONPOSITIVE`) — the sign comes from the type, with `RESTOCK` and `ADJUSTMENT` adding and `USAGE` and `WASTE` subtracting — the `occurred_at` instant (no later than the logical clock), and optionally an `event_id` linking consumption to an event. Two fields are conditionally required: `unit_cost_cents` must be present on a `RESTOCK` and is ignored for every other type, and a free-text `reason` is mandatory on `ADJUSTMENT` and `WASTE` — omitting either where required is rejected with `ERR_INVALID_REQUEST`. When the entry is created by an order receipt (below), the server sets its `restock_order_id`; otherwise that field stays null. The server stamps `recorded_by_staff_id` from the caller. A `USAGE` or `WASTE` entry that would drive the item's stock below zero is rejected with `ERR_INSUFFICIENT_STOCK`. The item's `current_stock` is always the signed sum over its whole ledger, and `stock_status` follows: zero is `OUT_OF_STOCK`, from one up to `reorder_threshold` is `LOW_STOCK`, and anything above the threshold is `IN_STOCK`. Ledger views filter by `supply_item_id`, `recorded_by_staff_id`, `restock_order_id`, `event_id`, and `txn_type`.

**Valuation** replays the ledger in chronological order — `occurred_at` ascending, ties broken by creation order — under one of three policies selected by the `policy` parameter. Under `FIFO`, the replay maintains cost layers: each `RESTOCK` pushes a layer of quantity and unit cost; each `USAGE` or `WASTE` consumes layers oldest-first; each `ADJUSTMENT` pushes a layer priced at the most recent `RESTOCK` unit cost — or zero cents if the item was never restocked; the valuation is the sum over remaining layers of quantity times unit cost, an exact integer number of cents. Under `WAC_RUNNING`, a running unit cost is maintained: after every transaction the unit cost is recomputed as the running value divided by the running quantity, rounded half-up to a whole cent (the recompute applies only while the running quantity is positive; a usage that empties the stock resets the running value to zero), a `RESTOCK` adds its quantity times its unit cost to the running value, and a `USAGE` or `WASTE` subtracts its quantity times the freshly recomputed unit cost; the valuation is the running value itself. Under `WAC_EXACT`, the same flow is computed with exact rational arithmetic and a single round-half-up applied once at the very end. The canonical policy for display is `WAC_RUNNING`. The valuation response reports the `supply_item_id`, the `policy` used, the `quantity_on_hand`, and the `valuation_cents`.

**Reorder suggestions** answer "how much can we responsibly buy?" with a pinned seven-step evaluation, because the quantity depends on budget, budget depends on committed spend, and committed spend depends on open orders. First, take `current_stock` from the ledger. Second, take the inbound quantity as the sum of `quantity` over this item's `APPROVED` restock orders. Third, the deficit is `par_level` minus stock minus inbound, floored at zero. Fourth, find the `SupplyBudget` whose `fiscal_year` matches the logical clock's current year; if none exists, treat available budget as zero. Fifth, available budget is the budget's `total_budget_cents` minus its realized spend minus its committed spend — where committed spend already includes the `APPROVED` orders counted in step two. Sixth, the most the budget can afford is that available amount divided by the item's `unit_cost_cents`, rounded down to a whole unit. Seventh, the suggestion is the smaller of the deficit and the affordable quantity, again floored at zero. The response exposes every intermediate: `supply_item_id`, `current_stock`, `inbound_qty`, `deficit_qty`, `available_budget_cents`, `max_affordable_qty`, and `suggested_qty`.

**Budgets and purchase orders** close the loop. A `SystemAdmin` creates one `SupplyBudget` per year: the `fiscal_year` must be unique across budgets (a duplicate is rejected with `ERR_DUPLICATE_BUDGET_YEAR`) and `total_budget_cents` must be strictly positive. Each budget derives three figures: `realized_spend_cents`, the sum of `extended_cost_cents` over the year's `RECEIVED` orders; `committed_spend_cents`, the sum over orders still `APPROVED` but not yet received or cancelled; and `available_cents`, the total minus realized minus committed. The budget list filters by `fiscal_year`.

A trainer or the director drafts a **restock order** with the `supply_item_id`, the `quantity` (strictly positive, else `ERR_QUANTITY_NONPOSITIVE`), the quoted `unit_cost_cents` (strictly positive), and the `fiscal_year` to charge; ordering a discontinued item is rejected with `ERR_ITEM_DISCONTINUED`. The server computes `extended_cost_cents` as the quantity times the unit cost, stamps `requested_by_staff_id` from the caller, and starts the order in `DRAFT`. Submission — by the trainer or the director — moves `DRAFT` to `SUBMITTED`.

Approval is the director's, and the checks run in the global order of §2.9: the order must be `SUBMITTED` (else `ERR_INVALID_STATE`); the approver may not be the requester — `X-User-ID` equal to `requested_by_staff_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`, the third segregation rule; a `SupplyBudget` must exist for the order's `fiscal_year` (else `ERR_BUDGET_NOT_FOUND`); and that budget's `available_cents` must cover the order's `extended_cost_cents` (else `ERR_BUDGET_EXCEEDED`, HTTP 402). Approval stamps `approved_by_staff_id`, moves the order to `APPROVED`, and commits the spend: the budget's `committed_spend_cents` grows by the extended cost and `available_cents` is recomputed. A director may instead reject a `SUBMITTED` order to `REJECTED`.

Receipt converts commitment into stock. A trainer receives an `APPROVED` order (any other state: `ERR_INVALID_STATE`), moving it to `RECEIVED` and appending a `RESTOCK` ledger entry that carries the order's quantity and unit cost, a `restock_order_id` back-reference, the current clock as `occurred_at`, and the receiver as `recorded_by_staff_id`. That ledger append recomputes the item's `current_stock` and `stock_status`, while on the budget the extended cost leaves `committed_spend_cents` and lands in `realized_spend_cents`, with `available_cents` recomputed. Finally, a trainer may cancel an order from `DRAFT`, `SUBMITTED`, or `APPROVED` into `CANCELLED`; cancelling an `APPROVED` order releases its committed amount back to the budget — `committed_spend_cents` shrinks by the extended cost and `available_cents` is recomputed — as compensation for the earlier commit. `RECEIVED`, `REJECTED`, and `CANCELLED` are terminal. Order lists filter by `supply_item_id`, `requested_by_staff_id`, `approved_by_staff_id`, `status`, and `fiscal_year`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including every lifecycle action such as verify, approve, start, advance, or receive — and all read operations return a `200 OK` status code. Request payloads, response fields, and side effects for each operation are defined by the narratives of §2 and §3; this table is the address map, not the contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/staff` | Create a staff member | SystemAdmin |
| GET | `/staff` | List staff (filters: `role_type`, `is_active`) | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/staff/{staffId}` | Get one staff member | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| PATCH | `/staff/{staffId}` | Activate or deactivate a staff member | SystemAdmin |
| POST | `/athletes` | Register a student-athlete | AthleticTrainer, SystemAdmin |
| GET | `/athletes` | List athletes | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/athletes/{athleteId}` | Get one athlete (guardians restricted to their own child) | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach, ParentGuardian |
| GET | `/athletes/{athleteId}/clearance` | Computed participation-posture detail | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| POST | `/physicals` | Record a pre-participation physical | AthleticTrainer, SchoolNurse |
| GET | `/physicals` | List physicals | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| GET | `/physicals/{physicalId}` | Get one physical | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| POST | `/physicals/{physicalId}/verify` | Verify a recorded physical (verifier differs from recorder) | SchoolNurse |
| POST | `/physicals/{physicalId}/void` | Void a recorded physical | AthleticTrainer |
| POST | `/baseline-tests` | Record a baseline concussion test | AthleticTrainer, SchoolNurse |
| GET | `/baseline-tests` | List baseline tests | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| GET | `/baseline-tests/{testId}` | Get one baseline test | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| POST | `/venues` | Create a venue | SystemAdmin |
| GET | `/venues` | List venues | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/venues/{venueId}` | Get one venue | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/venues/{venueId}/activity-status` | Computed environmental gate view for a venue | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| POST | `/emergency-action-plans` | Draft an emergency action plan | AthleticTrainer, AthleticDirector |
| GET | `/emergency-action-plans` | List emergency action plans | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/emergency-action-plans/{eapId}` | Get one emergency action plan | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| POST | `/emergency-action-plans/{eapId}/submit` | Submit a draft plan for approval | AthleticTrainer |
| POST | `/emergency-action-plans/{eapId}/approve` | Approve a pending plan (approver differs from author) | AthleticDirector |
| POST | `/emergency-action-plans/{eapId}/reject` | Reject a pending plan back to draft | AthleticDirector |
| POST | `/emergency-action-plans/{eapId}/activate` | Activate an approved plan, superseding the venue's active plan (OCC) | AthleticDirector |
| POST | `/events` | Schedule an athletic event | AthleticTrainer, AthleticDirector |
| GET | `/events` | List events | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/events/{eventId}` | Get one event | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/events/{eventId}/coverage-status` | Computed coverage view for an event | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| POST | `/events/{eventId}/start` | Start a covered event (EAP and weather gates) | AthleticTrainer |
| POST | `/events/{eventId}/suspend` | Manually suspend an in-progress event | AthleticTrainer |
| POST | `/events/{eventId}/resume` | Resume a suspended event after all-clear | AthleticTrainer |
| POST | `/events/{eventId}/complete` | Complete an in-progress event | AthleticTrainer |
| POST | `/events/{eventId}/cancel` | Cancel a non-terminal event | AthleticTrainer, AthleticDirector |
| POST | `/coverage-assignments` | Assign a trainer to an event | AthleticTrainer, AthleticDirector |
| GET | `/coverage-assignments` | List coverage assignments | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/coverage-assignments/{assignmentId}` | Get one coverage assignment | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| POST | `/coverage-assignments/{assignmentId}/acknowledge` | Assignee acknowledges the assignment | AthleticTrainer |
| POST | `/coverage-assignments/{assignmentId}/decline` | Assignee declines the assignment | AthleticTrainer |
| POST | `/coverage-assignments/{assignmentId}/check-in` | Assignee checks in on-site | AthleticTrainer |
| POST | `/coverage-assignments/{assignmentId}/complete` | Complete an assignment after the event | AthleticTrainer |
| POST | `/coverage-assignments/{assignmentId}/cancel` | Cancel a non-terminal assignment | AthleticTrainer, AthleticDirector |
| POST | `/weather-readings` | Post an environmental reading (triggers heat/lightning cascades) | AthleticTrainer, SystemAdmin |
| GET | `/weather-readings` | List environmental readings | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/weather-readings/{readingId}` | Get one environmental reading | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| POST | `/injuries` | Document an injury evaluation | AthleticTrainer |
| GET | `/injuries` | List injury evaluations | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| GET | `/injuries/{injuryId}` | Get one injury evaluation | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| POST | `/injuries/{injuryId}/begin-care` | Move an injury into treatment | AthleticTrainer |
| POST | `/injuries/{injuryId}/resolve` | Resolve an injury under care | AthleticTrainer |
| POST | `/injuries/{injuryId}/reopen` | Reopen a resolved injury | AthleticTrainer |
| POST | `/injuries/{injuryId}/close` | Close an injury resolved at least thirty days | AthleticTrainer |
| POST | `/referrals` | Refer an injury to a physician | AthleticTrainer |
| GET | `/referrals` | List physician referrals | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| GET | `/referrals/{referralId}` | Get one physician referral | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| POST | `/referrals/{referralId}/schedule` | Schedule the referral appointment | AthleticTrainer |
| POST | `/referrals/{referralId}/complete` | Physician files the report or an amended report | Physician |
| POST | `/referrals/{referralId}/request-addendum` | Ask the physician for a report addendum | AthleticTrainer |
| POST | `/referrals/{referralId}/close` | Close a completed referral | AthleticTrainer |
| POST | `/referrals/{referralId}/cancel` | Cancel a pending referral | AthleticTrainer |
| POST | `/injuries/{injuryId}/rtp-protocols` | Activate a return-to-play protocol on an injury (OCC; supersedes any active protocol) | AthleticTrainer |
| GET | `/rtp-protocols` | List return-to-play protocols | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| GET | `/rtp-protocols/{protocolId}` | Get one return-to-play protocol | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician |
| POST | `/rtp-protocols/{protocolId}/advance` | Advance the protocol one stage | AthleticTrainer |
| POST | `/rtp-protocols/{protocolId}/regress` | Record a symptom recurrence (back to stage 1) | AthleticTrainer |
| POST | `/rtp-protocols/{protocolId}/clear` | Grant final clearance from stage 6 | AthleticTrainer, Physician |
| POST | `/rtp-protocols/{protocolId}/terminate` | Terminate an active protocol | AthleticTrainer, Physician |
| GET | `/guardian-notifications` | List guardian notifications (guardians see only their own child's) | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, ParentGuardian |
| GET | `/guardian-notifications/{notificationId}` | Get one guardian notification | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, ParentGuardian |
| POST | `/guardian-notifications/{notificationId}/send` | Send a queued or failed notification | AthleticTrainer |
| POST | `/guardian-notifications/{notificationId}/acknowledge` | Guardian acknowledges receipt | ParentGuardian |
| POST | `/guardian-notifications/{notificationId}/retry` | Requeue a failed notification | AthleticTrainer |
| POST | `/supply-items` | Create a supply item | SystemAdmin |
| GET | `/supply-items` | List supply items | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| GET | `/supply-items/{itemId}` | Get one supply item | SystemAdmin, AthleticTrainer, AthleticDirector, SchoolNurse, Physician, TeamCoach |
| PATCH | `/supply-items/{itemId}` | Update thresholds, cost, or discontinued flag | SystemAdmin |
| GET | `/supply-items/{itemId}/valuation` | Inventory valuation under the selected policy | SystemAdmin, AthleticTrainer, AthleticDirector |
| GET | `/supply-items/{itemId}/reorder-suggestion` | Budget-clamped reorder suggestion | SystemAdmin, AthleticTrainer, AthleticDirector |
| POST | `/inventory-transactions` | Append an inventory ledger entry | AthleticTrainer, SystemAdmin |
| GET | `/inventory-transactions` | List inventory transactions | SystemAdmin, AthleticTrainer, AthleticDirector |
| GET | `/inventory-transactions/{txnId}` | Get one inventory transaction | SystemAdmin, AthleticTrainer, AthleticDirector |
| POST | `/restock-orders` | Draft a restock order | AthleticTrainer, AthleticDirector |
| GET | `/restock-orders` | List restock orders | SystemAdmin, AthleticTrainer, AthleticDirector |
| GET | `/restock-orders/{orderId}` | Get one restock order | SystemAdmin, AthleticTrainer, AthleticDirector |
| POST | `/restock-orders/{orderId}/submit` | Submit a draft order | AthleticTrainer, AthleticDirector |
| POST | `/restock-orders/{orderId}/approve` | Approve a submitted order (approver differs from requester; budget check) | AthleticDirector |
| POST | `/restock-orders/{orderId}/reject` | Reject a submitted order | AthleticDirector |
| POST | `/restock-orders/{orderId}/receive` | Receive an approved order (appends the restock ledger entry) | AthleticTrainer |
| POST | `/restock-orders/{orderId}/cancel` | Cancel a non-terminal order (releases committed budget when approved) | AthleticTrainer |
| POST | `/supply-budgets` | Create a fiscal-year supply budget | SystemAdmin |
| GET | `/supply-budgets` | List supply budgets | SystemAdmin, AthleticTrainer, AthleticDirector |
| GET | `/supply-budgets/{budgetId}` | Get one budget with computed spend fields | SystemAdmin, AthleticTrainer, AthleticDirector |
| POST | `/_clock/set_current_utc` | Set the server's logical clock and run the auto-transition sweep | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the identifier-to-status map.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_ATHLETE_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_VENUE_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INJURY_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_PROTOCOL_NOT_FOUND` | 404 Not Found |
| `ERR_EAP_NOT_FOUND` | 404 Not Found |
| `ERR_PHYSICAL_NOT_FOUND` | 404 Not Found |
| `ERR_BASELINE_NOT_FOUND` | 404 Not Found |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLY_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_RESTOCK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_BUDGET_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_QUANTITY_NONPOSITIVE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NO_ACTIVE_EAP` | 409 Conflict |
| `ERR_HEAT_TIER_EXTREME` | 409 Conflict |
| `ERR_LIGHTNING_HOLD_ACTIVE` | 409 Conflict |
| `ERR_CLEARANCE_AUTHORITY_INSUFFICIENT` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SYMPTOMS_REPORTED` | 422 Unprocessable Entity |
| `ERR_RTP_PHYSICIAN_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_GUARDIAN_CONTACT_MISSING` | 409 Conflict |
| `ERR_PHYSICAL_EXPIRED` | 409 Conflict |
| `ERR_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_VENUE_OVERLAP` | 409 Conflict |
| `ERR_RTP_STAGE_DWELL_NOT_MET` | 409 Conflict |
| `ERR_CLOSE_WINDOW_NOT_MET` | 409 Conflict |
| `ERR_STAFF_ROLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ITEM_DISCONTINUED` | 422 Unprocessable Entity |
| `ERR_REFERENCED_INJURY_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_VENUE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_DUPLICATE_BUDGET_YEAR` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |

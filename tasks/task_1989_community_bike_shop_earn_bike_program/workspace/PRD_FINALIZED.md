# Community Bike Shop API — Product Requirements Document

## 1. Introduction

A nonprofit community bike shop runs on donated bicycles, volunteer labor, and a promise: anyone who puts in the hours can earn a bike. The shop accepts donated frames, triages them by condition, routes them into refurbishment or parts harvest or the scrap stream, and sells or gives away the finished bikes. Volunteer mechanics staff the workbenches; an earn-a-bike program tracks participant hours toward graduation; a tool-access membership program opens the shop's stands to the public; and helmets go out the door with every bike that leaves with a new rider.

This document specifies the API that backs the shop's operations. It covers the full lifecycle of a donated bicycle from intake through disposition, the parts inventory that refurbishment consumes and harvest replenishes, the training and shift machinery that grows volunteer mechanics from first-day trainees into lead mechanics, the earn-a-bike hour ledger with its approval workflow and deadline sweep, low-cost sales with member discounts and round-up donations, partner-referred giveaways under a monthly quota, tool-stand membership billing, and the scrap pipeline that closes out unrepairable frames with a recycler payout.

Two cross-cutting concerns shape everything below. First, money is always integer cents and every priced or paid figure is computed by pinned formulas with explicit rounding — the register never invents a number. Second, the shop is deliberate about who may do what: the person who logs hours is never the person who approves them, the mechanic who refurbishes a bike is never the inspector who certifies it, and the director who approves a giveaway is never the coordinator who hands the bike over. Segregation of duties is a hard rule, not a convention.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. The role header must contain exactly one of the five role names — `ShopCoordinator`, `ProgramDirector`, `Volunteer`, `Participant`, or `Member`. A request with either header missing, or with a role value outside that set, is rejected with `ERR_UNAUTHENTICATED`. A request whose authenticated role is not in the endpoint's authorized list, or whose entity-backed identity does not own the targeted resource, is rejected with `ERR_FORBIDDEN`.

The `ShopCoordinator` role is the front-of-shop staff identity. When `X-User-Role` is `ShopCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `harvested_by_user_id` on a `PartHarvest`, `logged_by_user_id` on a `PartUsage`, `created_by_user_id` on an `HourLog`, or `distributed_by_user_id` on a `HelmetDistribution` — but it never compares that value to any entity's `id`. The `ProgramDirector` role is likewise opaque: `X-User-ID` identifies the acting director for audit fields such as `decided_by_user_id` on a `GiveawayAward`, `fulfilled_by_user_id` comparisons, and `reviewed_by_user_id` on hour logs, but it is not a foreign key into any table.

The remaining three roles are entity-backed. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer` record; ownership checks on any resource that references a `Volunteer` — most importantly a `VolunteerShift` at check-in or cancel time, and the safety-inspection path where the caller's volunteer id becomes `inspector_volunteer_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `EarnABikeParticipant`; a `Participant` may read only their own record and touch only their own hour logs, reservation, and withdrawal. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `ToolMembership`; a `Member` may act only on sessions and billing belonging to that membership.

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

List endpoints accept two query parameters. `limit` controls page size: it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. `offset` controls how many records are skipped and defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside its `meta` object. Unless a filter narrows the result set, list endpoints return records sorted by `created_at` in ascending order.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Most resources also carry `created_at` (an ISO 8601 UTC timestamp with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version` (an integer that starts at its initial value on creation and increments by exactly 1 on every mutation of that record). Lifecycle-bearing entities additionally expose a `status` field whose exact enumeration is defined in the workflow narratives of §3 — the bike pipeline alone spans `RECEIVED`, `TRIAGED`, `IN_REFURBISHMENT`, `SAFETY_REVIEW`, `READY_FOR_DISPOSITION`, `RESERVED_FOR_GRADUATE`, `SOLD`, `GIFTED`, `HARVEST_QUEUE`, `HARVESTED`, `SCRAP_PENDING`, and `SCRAPPED`, and the participant, hour-log, shift, session, membership, sale, award, attendance, training-session, and scrap-ticket lifecycles each define their own. Four event-style resources — `PartHarvest`, `PartUsage`, `SafetyInspection`, and `HelmetDistribution` — are immutable once recorded and therefore carry only `id` and `created_at`; both `updated_at` and `version` are absent on those four entities.

The shop runs on a logical clock rather than wall-clock time. At server startup the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall time afterward. A `ShopCoordinator` advances it through an admin test-driving capability that accepts a `to_iso8601` instant and sets the clock to that value. Every deadline, window, quota month, billing month, and sweep described below reads this logical clock. Every timestamp the server stamps from this clock — `enrolled_at`, `enrollment_deadline`, `graduated_at`, `checked_in_at`, `started_at`, `closed_at`, `completed_at`, `decided_at`, `picked_up_at`, and the reported `current_utc` — is rendered as an ISO 8601 UTC timestamp with three fractional digits, in the same format as `created_at` and `updated_at`; the one clock-derived calendar date, a membership's `start_date`, remains a plain `YYYY-MM-DD` date. The response of the clock-set operation reports the new `current_utc`.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer cents. Wherever a formula below produces a fractional cent, the value is rounded half up to the nearest whole cent at the step the formula designates — and only there. Two rules recur throughout: per-line values are rounded before they are summed (never sum-then-round), and multi-step formulas evaluate in the exact written order. Hours, minutes, and counts are whole integers.

### 2.6. Optimistic Concurrency Control

Two write operations carry an explicit optimistic-concurrency guard, and no other endpoint takes a version field.

Logging a part usage requires the request to carry `expected_part_version`, equal to the `Part` record's `version` the caller last observed. If the part's current `version` has advanced past that value — because an earlier usage, restock, harvest, helmet distribution, or usage void has already moved `quantity_on_hand` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The caller must re-read the part and resubmit against the fresh version.

Approving an hour log requires the request to carry `expected_participant_version`, equal to the `EarnABikeParticipant` record's `version` the caller last observed. If the participant's `version` has advanced — through a prior approval, a void, a quiz update, a reservation, or a cascaded demotion — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), since the caller's view of `hours_earned` is no longer current.

### 2.7. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order and returns the first failure encountered. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED` (HTTP 401), then role and ownership failures yield `ERR_FORBIDDEN` (HTTP 403). Request well-formedness — required fields present, JSON types valid, enum members recognized, fixed numeric ranges such as the 1-to-6-hour claim bound — runs alongside the envelope and auth checks, before any resource lookup, and fails with `ERR_VALIDATION` (HTTP 400). Existence comes next: path identifiers are resolved left to right, then body foreign keys (`donor_id`, `part_id`, `bike_id`, `volunteer_id`, `buyer_membership_id`, `helmet_part_id`, the helmet recipient references, `shift_id`), and any missing record yields `ERR_NOT_FOUND` (HTTP 404).

Only after all of that does state checking begin. The optimistic-concurrency comparison runs first among the state checks (`ERR_STALE_VERSION`, HTTP 412). Then come the state-machine from-state guards and their specialized siblings: `ERR_INVALID_STATE` when no more specific code applies, plus `ERR_BIKE_NOT_AVAILABLE`, `ERR_AWARD_NOT_APPROVED`, `ERR_SALE_NOT_PENDING`, `ERR_TICKET_NOT_OPEN`, `ERR_MEMBERSHIP_NOT_ACTIVE`, `ERR_PARTICIPANT_NOT_ACTIVE`, and `ERR_USAGE_NOT_COMMITTED` where their conditions are met (all HTTP 409). After state checks pass, the safety and segregation-of-duties rules run: `ERR_INSPECTOR_IS_REFURB_LEAD`, `ERR_CHECKLIST_INCONSISTENT`, `ERR_HELMET_REQUIRED` (all HTTP 422), and the two HTTP 403 duty-segregation codes `ERR_REVIEWER_IS_LOGGER` and `ERR_FULFILLER_IS_APPROVER`. Business constraints come next — uniqueness, grade routing, eligibility, capacity, enrollment, reservation, and quantity rules (detailed in §3). Temporal rules follow: shift overlap and duration, check-in windows, stand buffers and session duration, work-date windows, the daily hours cap, and the session-ended rule. Fiscal checks (`ERR_INSUFFICIENT_STOCK`, `ERR_HELMET_OUT_OF_STOCK`, `ERR_GIVEAWAY_QUOTA_EXCEEDED`, `ERR_WEIGHT_INVALID`) come after temporal, and referential checks (`ERR_RECIPIENT_REFERENCE_MISMATCH`, `ERR_NOT_A_HELMET_SKU`, `ERR_SHIFT_NOT_CREDITABLE`) run last.

### 2.8. Derived and Snapshot Fields

Several fields are computed rather than supplied, and the shop reconciles them on every mutation of their inputs. A donor's `donated_bike_count` counts their donated bikes, and `lifetime_receipt_value_cents` aggregates receipt value across all of the donor's triaged bikes under the donor's chosen valuation variant. A bike's `parts_cost_cents` rolls up committed part usages at their frozen snapshot costs; `latest_inspection_result` reflects the most recent inspection and stays null until the first one. A part's `quantity_on_hand` nets restocks and harvests against committed usages and helmet distributions and never goes negative; `low_stock` is true whenever `quantity_on_hand` is less than or equal to `reorder_threshold` — equality counts as low. A volunteer's `training_hours`, `sessions_attended`, `inspections_conducted`, and `shift_minutes` are all recomputed from their source events. A participant's `hours_earned` sums approved hour logs only. A session's `enrolled_count` counts its enrolled attendances.

Snapshots matter most in the parts ledger: when a usage is logged, the part's current `unit_cost_cents` is frozen onto the usage row, and later restocks that replace the part's `unit_cost_cents` never rewrite existing usage rows. Restoring a voided usage credits stock back at the frozen snapshot cost.

### 2.9. Segregation of Duties

Three duty pairs are enforced server-side. The reviewer of an hour log — approver, rejecter, or voider — must not be the person who created it; equality of the reviewer's `X-User-ID` with the log's `created_by_user_id` is rejected with `ERR_REVIEWER_IS_LOGGER`. The inspector of a bike must not be the mechanic who led its refurbishment; an inspection whose `inspector_volunteer_id` equals the bike's `refurb_lead_volunteer_id` is rejected with `ERR_INSPECTOR_IS_REFURB_LEAD`. The fulfiller of a giveaway must not be the director who approved it; equality of the fulfiller's `X-User-ID` with the award's `decided_by_user_id` is rejected with `ERR_FULFILLER_IS_APPROVER`.

### 2.10. The Operations Sweep

A coordinator-triggered operations checkpoint advances the shop's periodic bookkeeping in one run. It expires earn-a-bike participants whose `enrollment_deadline` has passed (releasing any reserved bike back to the floor), marks past-due scheduled shifts as no-shows once the clock is at least 30 minutes past a shift's scheduled end (feeding the no-show strike cascade), marks past-due booked stand sessions as no-shows once the clock is at least 30 minutes past the session's `start_time`, and expires memberships whose `end_date` has passed. The checkpoint reports four counts in its response: `participants_expired`, `shifts_marked_no_show`, `sessions_marked_no_show`, and `memberships_expired`.

## 3. Business Logic & Workflows

### 3.1. Donor Registration and Bike Intake

A `ShopCoordinator` registers a donor with a `display_name`, a `donor_type` of `INDIVIDUAL` or `ORGANIZATION`, a contact `email`, and an optional `receipt_method` selecting how donation receipts are valued. The receipt method is either `FLAT_SCHEDULE` or `FMV_COMPARABLE` and defaults to `FLAT_SCHEDULE` when omitted.

Intake of a donated bicycle records the `donor_id` of the donating party, a `serial_number` that must be unique across every bike the shop has ever taken in (a duplicate is rejected with `ERR_SERIAL_NUMBER_CONFLICT`), a `bike_type` drawn from `ROAD`, `MTB`, `HYBRID`, `KIDS`, `BMX`, or `CARGO`, and the `wheel_size_inches`. The new bike enters at `RECEIVED` with `condition_grade` and `frame_damage` both null, `parts_cost_cents` at 0, and `rework_count` at 0; registering the bike also increments the donor's `donated_bike_count`.

### 3.2. Triage and Routing: the Fork in the Pipeline

Triage is the pivotal moment in a bike's life. A `ShopCoordinator` grades a `RECEIVED` bike, supplying a `condition_grade` of `A`, `B`, `C`, or `D` and the structural `frame_damage` flag. Triage moves the bike `RECEIVED → TRIAGED`, stamps both fields, bumps the bike's `version`, and — because the bike now carries a grade — triggers a recompute of the donor's receipt fields. A bike that never reaches triage contributes nothing to any receipt.

From `TRIAGED`, the coordinator routes the bike to one of three destinations, and the grade gates each branch. Routing with `destination` set to refurbish moves the bike `TRIAGED → IN_REFURBISHMENT` and is allowed only when the grade is `A`, `B`, or `C`; a grade-`D` bike routed to refurbishment is rejected with `ERR_GRADE_NOT_REFURBISHABLE`. The refurbish branch also requires a `refurb_lead_volunteer_id` naming the accountable mechanic, and that volunteer must hold a `skill_level` of at least `APPRENTICE` — `APPRENTICE`, `JOURNEYMAN`, or `LEAD_MECHANIC` — with `engagement_status` `ACTIVE`; otherwise the routing fails with `ERR_LEAD_INELIGIBLE`. A successful refurbish routing stamps the lead onto the bike and bumps `version`.

Routing to harvest moves the bike `TRIAGED → HARVEST_QUEUE` and requires grade `C` or `D`; routing an `A` or `B` grade bike to harvest is rejected with `ERR_GRADE_NOT_HARVESTABLE`. Routing to scrap moves the bike `TRIAGED → SCRAP_PENDING` and is the strictest branch: the grade must be exactly `D` and `frame_damage` must be true, or the request fails with `ERR_SCRAP_CRITERIA_NOT_MET`. Both branches bump the bike's `version`.

There is one escape hatch after refurbishment has begun. When a bike in `IN_REFURBISHMENT` proves uneconomical to repair, the coordinator may redirect it to harvest — but only if no passing safety inspection exists for it yet; if one does, the redirect is rejected with `ERR_INVALID_STATE`. This mid-refurb redirect moves the bike `IN_REFURBISHMENT → HARVEST_QUEUE`, clears `refurb_lead_volunteer_id` to null, and leaves every committed part usage in place: parts already consumed on the bike are not returned to stock by the redirect.

### 3.3. The Parts Ledger: Restock, Harvest, Usage, and Void

Parts are the shop's consumable inventory. Creating a SKU requires a globally unique `name` (a duplicate is rejected with `ERR_PART_NAME_CONFLICT`), a `category` from `DRIVETRAIN`, `BRAKES`, `WHEELS`, `FRAME`, `COCKPIT`, `SADDLE`, `TIRES`, `HELMET`, or `MISC`, and optionally a starting `unit_cost_cents` (default 0) and `reorder_threshold` (default 0). Helmet SKUs carry a discipline of their own: when `category` is `HELMET`, a `helmet_size` of `XS`, `S`, `M`, `L`, or `XL` is required, and when the category is anything else, `helmet_size` must be absent — either violation is rejected with `ERR_HELMET_SIZE_REQUIRED`.

Restocking a part adds the purchased `quantity` — which must be at least 1, else `ERR_QUANTITY_INVALID` — to `quantity_on_hand`, replaces `unit_cost_cents` when a new cost is supplied, bumps the part's `version`, and recomputes `low_stock`. Existing usage rows keep their frozen snapshot costs; a restock never rewrites history.

Harvest moves parts the other way: from donor bikes back into stock. A volunteer with `engagement_status` `ACTIVE` — a suspended volunteer's attempt is rejected with `ERR_VOLUNTEER_SUSPENDED` — logs a harvest against a bike in `HARVEST_QUEUE`, naming the `part_id` credited, a `quantity` of at least 1 (else `ERR_QUANTITY_INVALID`), and an optional `note`. One category is off-limits: helmets are purchased stock only, never stripped from donor bikes, so harvesting a `HELMET` SKU is rejected with `ERR_NOT_HARVESTABLE_CATEGORY`. Each logged harvest adds the quantity to the part's `quantity_on_hand`, bumps the part's `version`, and recomputes `low_stock`. The harvest row itself records the acting user's opaque id as `harvested_by_user_id`. When at least one harvest row exists for a queued bike — attempting harvest-completion without one is rejected with `ERR_NO_HARVEST_RECORDED` — a coordinator may complete the harvest, moving the bike `HARVEST_QUEUE → HARVESTED`.

Usage consumes stock against a bike under refurbishment. A volunteer logging a usage names the `part_id`, a `quantity` of at least 1 (else `ERR_QUANTITY_INVALID`) and no more than the part's current `quantity_on_hand` (an overdraw is rejected with `ERR_INSUFFICIENT_STOCK`), and carries the OCC field `expected_part_version` described in §2.6. The logging volunteer must be `ACTIVE` (else `ERR_VOLUNTEER_SUSPENDED`) and hold at least `APPRENTICE` skill; a `TRAINEE`'s usage log is rejected with `ERR_USAGE_SKILL_INSUFFICIENT`. A successful usage snapshots the part's current `unit_cost_cents` onto the row — that frozen cost survives all later restocks — decrements `quantity_on_hand`, bumps the part's `version`, recomputes the bike's `parts_cost_cents` as the sum over its committed usages of each row's quantity times its snapshot cost, and recomputes `low_stock`. The row is born `COMMITTED` and records the logger as `logged_by_user_id`.

Voiding is the compensating action, reserved for a `ProgramDirector`. Voiding requires the row to still be `COMMITTED`; voiding an already-voided row is rejected with `ERR_USAGE_NOT_COMMITTED`. A void flips the row to `VOIDED`, records the optional `reason` as `void_reason`, adds the quantity back to the part's `quantity_on_hand`, bumps the part's `version`, decrements the bike's `parts_cost_cents` by the voided row's quantity times its snapshot cost, and recomputes `low_stock`.

### 3.4. Refurbishment, Safety Inspection, and the Rework Loop

When the accountable mechanic judges a bike finished, an `ACTIVE` volunteer submits it for safety review — but only if at least one committed usage row exists against the bike, since a submission with no recorded work is rejected with `ERR_NO_WORK_RECORDED`. Submission moves the bike `IN_REFURBISHMENT → SAFETY_REVIEW` and bumps its `version`; the `refurb_lead_volunteer_id` is retained for audit even after the bike leaves refurbishment.

Inspection is performed by a volunteer caller whose own id becomes `inspector_volunteer_id`. The inspector must hold `JOURNEYMAN` or `LEAD_MECHANIC` skill — anything less is rejected with `ERR_INSPECTOR_SKILL_INSUFFICIENT` — must be `ACTIVE` (else `ERR_VOLUNTEER_SUSPENDED`), and must not be the bike's refurb lead (else `ERR_INSPECTOR_IS_REFURB_LEAD`, per §2.9). The inspection payload carries a `result` of `PASS` or `FAIL`, a `checklist` object with five boolean items — `brakes`, `steering`, `tires`, `drivetrain`, and `reflectors` — and an optional `note`. A `PASS` result requires every checklist item to be true; a passing claim with any item false is rejected with `ERR_CHECKLIST_INCONSISTENT`.

The two outcomes fork. On `PASS`, the bike moves `SAFETY_REVIEW → READY_FOR_DISPOSITION`, its `latest_inspection_result` becomes `PASS`, and its `version` bumps. On `FAIL`, the bike loops back `SAFETY_REVIEW → IN_REFURBISHMENT` for rework: `latest_inspection_result` becomes `FAIL`, `rework_count` increments by 1, and `version` bumps — and the bike may be resubmitted after further work. Either way, the inspector's `inspections_conducted` count increases by 1.

### 3.5. Volunteer Growth: Training, Promotion, and Accountability

Volunteers register with a `full_name` and `email`, entering at `TRAINEE` skill with `engagement_status` `ACTIVE` and a `no_show_count` of 0. Skill and engagement are independent dimensions on the same record: a journeyman can be suspended, and a trainee can be in perfect standing.

Training classes carry a `topic`, a `level` of `BASIC`, `ADVANCED`, or `LEAD_CERT`, a `scheduled_start` and `scheduled_end` in ISO 8601 UTC (the end must be after the start, else `ERR_VALIDATION`), a whole number of `credit_hours` of at least 1, and a `capacity` of at least 1. A new session is `SCHEDULED` with `enrolled_count` 0. Enrollment adds an `ACTIVE` volunteer (a suspended one is rejected with `ERR_VOLUNTEER_SUSPENDED`) to a session, creating an attendance row that carries the `session_id` from the path and the `volunteer_id` from the payload: one attendance row per (session, volunteer) pair — a second enrollment of the same volunteer in the same session is rejected with `ERR_ALREADY_ENROLLED` — and only while `enrolled_count` remains below `capacity`; an enrollment into a full session is rejected with `ERR_TRAINING_FULL`. Each enrollment increments `enrolled_count` and bumps the session's `version`.

Completion closes the books on a class. A coordinator may complete a session only once the logical clock has reached its `scheduled_end` — completing early is rejected with `ERR_SESSION_NOT_ENDED` — and the completion must mark every enrolled attendance exactly once, each as `ATTENDED` or `NO_SHOW`, via the `marks` payload; missing or duplicate marks are rejected with `ERR_ATTENDANCE_MARKS_INCOMPLETE`. Every attendance marked `ATTENDED` credits its volunteer: `training_hours` increases by the session's `credit_hours`, `sessions_attended` increases by 1, and the volunteer's `version` bumps. Attendances marked `NO_SHOW` accrue nothing. Cancelling a scheduled session instead drops every enrolled attendance to `DROPPED` and bumps the session's `version`.

Promotion advances a volunteer exactly one level per call, and the thresholds are inclusive — meeting the exact boundary is eligible. `TRAINEE → APPRENTICE` requires at least 8 `training_hours` and at least 2 `sessions_attended`. `APPRENTICE → JOURNEYMAN` requires at least 24 training hours and at least 5 sessions. `JOURNEYMAN → LEAD_MECHANIC` requires at least 60 training hours, at least 12 sessions, and at least 10 `inspections_conducted`. Falling short on any leg is rejected with `ERR_PROMOTION_CRITERIA_NOT_MET`, and promoting a suspended volunteer is rejected with `ERR_VOLUNTEER_SUSPENDED`. Only a `ProgramDirector` promotes.

Accountability runs through shifts and the no-show strike rule. When the ops sweep marks a scheduled shift `NO_SHOW`, the volunteer's `no_show_count` increments by 1; sweep processing walks the affected shifts in `scheduled_start` ascending order, breaking ties by `created_at` ascending. When the count reaches 3 — the third strike suspends — the volunteer's `engagement_status` flips to `SUSPENDED` and every remaining `SCHEDULED` shift of that volunteer is cancelled. A `ProgramDirector` may also suspend a volunteer manually (optionally recording a `reason`), which applies the same shift-cancellation cascade. Reinstatement by a director flips the volunteer back to `ACTIVE`, resets `no_show_count` to 0, and preserves `skill_level` exactly as it was.

### 3.6. Shifts: Scheduling, Check-in, and Credit

A coordinator schedules a shift for a volunteer, naming the `volunteer_id`, a `shift_role` of `MECHANIC`, `INTAKE`, or `FLOOR`, and a `scheduled_start` and `scheduled_end`. The shift's duration must fall between 30 and 480 minutes inclusive, else `ERR_SHIFT_DURATION_INVALID`, and the volunteer must be `ACTIVE`, else `ERR_VOLUNTEER_SUSPENDED`. Overlap is policed per volunteer under half-open interval semantics: the new shift's span must not intersect any existing `SCHEDULED` or `CHECKED_IN` shift of the same volunteer, but two shifts that merely touch — one ending exactly when the other begins — are allowed. An intersecting booking is rejected with `ERR_SHIFT_OVERLAP`.

Check-in belongs to the owning volunteer alone: the caller's `X-User-ID` must equal the shift's `volunteer_id`, else `ERR_NOT_YOUR_SHIFT`. The volunteer must be `ACTIVE` (else `ERR_VOLUNTEER_SUSPENDED`), and the logical clock must fall within the check-in window — from 15 minutes before `scheduled_start` through `scheduled_end` — else `ERR_CHECKIN_WINDOW_CLOSED`. A successful check-in moves the shift `SCHEDULED → CHECKED_IN`, stamps `checked_in_at`, and bumps `version`.

Completion is confirmed by a coordinator and moves the shift `CHECKED_IN → COMPLETED`. Completion stamps `credited_minutes` as the scheduled duration in whole minutes, capped at 480 — a shift scheduled longer than eight hours still credits exactly 480 — and adds those minutes to the volunteer's `shift_minutes`. Cancelling a scheduled shift is open to a coordinator or to the owning volunteer (anyone else is rejected with `ERR_NOT_YOUR_SHIFT`) and moves it `SCHEDULED → CANCELLED`.

### 3.7. Earn-a-Bike: Enrollment, Hours, and the Approval Desk

Enrolling a participant captures `full_name`, `contact_email`, and an `age_group` of `YOUTH` or `ADULT`. The record enters at `ENROLLED` with `enrolled_at` stamped from the logical clock, an `enrollment_deadline` exactly 90 days after enrollment, a `required_hours` of 8 for `YOUTH` and 12 for `ADULT`, `hours_earned` at 0, `safety_quiz_passed` false, and no reserved bike.

Hour logging is shared between the participant — who may log only against their own record — and coordinators logging on their behalf. Each log carries a `work_date` as a calendar date, a whole number of `hours` claimed between 1 and 6 (outside that range is `ERR_VALIDATION`), an `activity_type` of `REFURB_WORK`, `SHOP_HELP`, `OUTREACH`, or `TRAINING_ASSIST`, and optionally a `shift_id` linking the work to a shop shift plus a free-text `description`. The participant must be `ENROLLED` or `HOURS_MET` at logging time, else `ERR_PARTICIPANT_NOT_ACTIVE`. Two temporal guards apply at creation. The `work_date` must fall within the participation window — on or after the enrollment date and no later than the earlier of the current clock date and the deadline date — else `ERR_WORK_DATE_OUT_OF_WINDOW`. And the daily cap: across a single `work_date`, the sum of `hours` over the participant's logs in `PENDING` or `APPROVED` status, including the new log, must not exceed 6, else `ERR_DAILY_HOURS_EXCEEDED`; rejected and voided rows free their hours. When `shift_id` is present it must reference a `COMPLETED` shift, else `ERR_SHIFT_NOT_CREDITABLE`. Every new log is born `PENDING` and records its creator as `created_by_user_id`.

Approval is the coordinator's desk and is OCC-guarded by `expected_participant_version` per §2.6. The approver must differ from the log's creator (else `ERR_REVIEWER_IS_LOGGER`), and the participant must still be `ENROLLED` or `HOURS_MET` (else `ERR_PARTICIPANT_NOT_ACTIVE`). Approval flips the log `PENDING → APPROVED`, stamps `reviewed_by_user_id`, recomputes the participant's `hours_earned` as the sum of hours across all approved logs — pending, rejected, and voided rows never count — and bumps the participant's `version`. When a recompute lifts an `ENROLLED` participant's `hours_earned` to at least their `required_hours` — equality triggers — the participant auto-advances `ENROLLED → HOURS_MET`. Rejection flips the log `PENDING → REJECTED` under the same reviewer-differs-from-logger rule and stamps `reviewed_by_user_id`, but touches nothing else.

Voiding is the director's compensating action against an `APPROVED` log, and it is sealed after graduation: voiding a log whose participant has `GRADUATED` is rejected with `ERR_INVALID_STATE`. A void flips the log to `VOIDED`, stamps `reviewed_by_user_id` and the optional `reason` as the log's `void_reason`, decrements `hours_earned` through the recompute, and bumps the participant's `version`. If the participant was `HOURS_MET` and the recompute drops them below their required hours, they demote `HOURS_MET → ENROLLED` — and if they were holding a reserved bike, that reservation is force-released: the bike returns `RESERVED_FOR_GRADUATE → READY_FOR_DISPOSITION` and `reserved_bike_id` clears to null, with both records' versions bumping.

### 3.8. Reservation and Graduation

A participant whose hours are met may reserve one bike from the floor — an action open to the participant themselves or a coordinator. Reservation requires the participant to be exactly `HOURS_MET` (else `ERR_HOURS_NOT_MET`), to hold no existing reservation (else `ERR_RESERVATION_EXISTS`), and to name a `bike_id` currently `READY_FOR_DISPOSITION` (else `ERR_BIKE_NOT_AVAILABLE`). Success moves the bike `READY_FOR_DISPOSITION → RESERVED_FOR_GRADUATE`, stamps the participant's `reserved_bike_id`, and bumps both records' versions. Releasing a reservation — again by the participant or a coordinator — reverses it: the bike returns to `READY_FOR_DISPOSITION`, `reserved_bike_id` clears, and both versions bump. Withdrawal and the expiry sweep apply the same release cascade whenever a participant leaving the program holds a bike.

Graduation is the program's ceremony and belongs to the `ProgramDirector`. It requires the participant to be `HOURS_MET` (else `ERR_INVALID_STATE`), to hold a reserved bike (else `ERR_NO_BIKE_RESERVED`), to have `safety_quiz_passed` set true — a coordinator records quiz outcomes through the quiz-recording action, whose `passed` input stamps the flag and bumps the participant's `version` — else `ERR_QUIZ_NOT_PASSED`, and to have a helmet already distributed to them as an `EARN_A_BIKE_GRADUATE` recipient, else `ERR_HELMET_REQUIRED`. Graduation moves the participant `HOURS_MET → GRADUATED`, stamps `graduated_at` from the logical clock, moves the reserved bike `RESERVED_FOR_GRADUATE → GIFTED`, and bumps both records. The gifted bike is safety-certified by construction: `RESERVED_FOR_GRADUATE` is reachable only from `READY_FOR_DISPOSITION`, which itself requires a passing latest inspection, and no inspection can run while a bike is reserved.

Withdrawal is available from either `ENROLLED` or `HOURS_MET` — from any other status it is rejected with `ERR_INVALID_STATE` — and moves the participant to `WITHDRAWN`, releasing any reserved bike as above. The ops sweep moves an `ENROLLED` or `HOURS_MET` participant to `EXPIRED` once the logical clock passes `enrollment_deadline`, applying the same bike-release cascade.

### 3.9. Sales: Quoting, Settlement, and the Round-Up

Opening a sale requires a `bike_id` in `READY_FOR_DISPOSITION` (else `ERR_BIKE_NOT_AVAILABLE`), a `buyer_name` and `buyer_email`, and optionally a `buyer_membership_id` referencing a tool membership — which, when present, must be `ACTIVE` (else `ERR_MEMBERSHIP_NOT_ACTIVE`) and earns the buyer a ten percent discount. At most one pending sale may exist per bike; opening a second is rejected with `ERR_SALE_ALREADY_PENDING`. The new sale is `PENDING`, and creation computes `quoted_price_cents` under the pricing formula below, evaluated against the bike's data and the membership's status at creation; the quote is stored and never rewritten.

The price ladder runs in pinned order. The base price depends on `bike_type`: `KIDS` 4000 cents, `BMX` 6000, `HYBRID` 9000, `ROAD` 12000, `MTB` 12000, `CARGO` 18000. The condition grade scales that base: grade `A` at full value, `B` at 0.80, `C` at 0.40 — grade-`D` bikes never reach the sales floor. The first step rounds that product half up to whole cents. Next comes the parts surcharge: half of the bike's current `parts_cost_cents`, rounded half up, capped at 3000 cents. The surcharge adds to the first step. Then the member discount: if the buyer's membership references an `ACTIVE` membership, ten percent of the running total, rounded half up, is subtracted; otherwise the discount is zero. Finally, the price is floored at 2000 cents — if the running total falls below the floor, the floor wins.

Completing a sale re-evaluates everything. Completion requires the sale still `PENDING` (else `ERR_SALE_NOT_PENDING`), the bike still `READY_FOR_DISPOSITION` (else `ERR_BIKE_NOT_AVAILABLE`), and a helmet already distributed to this sale's buyer — a `SALE_BUYER` distribution referencing this sale — else `ERR_HELMET_REQUIRED`. At completion the final price is recomputed against the bike's current `parts_cost_cents` and the membership's current status, following the same ladder; because membership status is read at evaluation time, a membership suspended after creation loses its discount and the final price can exceed the quote. Completion collects a `payment_method` of `CASH`, `CARD`, or `VOUCHER` and the buyer's `round_up` election (default false, settable at completion). When `round_up` is false, `grand_total_cents` equals the final price and `donation_cents` is 0. When true, the grand total is the smallest multiple of 500 cents greater than or equal to the final price — an exact multiple yields a zero donation — and `donation_cents` is the difference between the grand total and the final price. The round-up tier is selected only after the final price is fully evaluated, floor included. Completion stamps `final_price_cents`, `grand_total_cents`, `donation_cents`, `payment_method`, and `completed_at`, moves the bike `READY_FOR_DISPOSITION → SOLD`, and bumps both records' versions.

Voiding a sale is a director's action against a `PENDING` sale (anything else is `ERR_SALE_NOT_PENDING`), records an optional `reason`, and flips the sale to `VOIDED`. The bike was never transitioned by the pending sale, so it stays `READY_FOR_DISPOSITION`, and any helmet distributions recorded against the sale remain on the books — events are immutable.

### 3.10. Giveaways: Partner Referrals Under a Monthly Quota

A giveaway begins when a coordinator requests an award for a `bike_id` in `READY_FOR_DISPOSITION` (else `ERR_BIKE_NOT_AVAILABLE`), naming the referring `partner_org`, the partner's `referral_code`, and a `recipient_age_group` of `YOUTH` or `ADULT`. The award is born `REQUESTED`.

Approval and denial belong to the `ProgramDirector`. Approval re-verifies the bike is still `READY_FOR_DISPOSITION` (else `ERR_BIKE_NOT_AVAILABLE`) and enforces the monthly quota: counting awards in `APPROVED` or `FULFILLED` status whose `decided_at` falls within the current logical-clock calendar month — `REQUESTED`, `DENIED`, and `CANCELLED` rows are excluded — that count must be below 4 at the moment of approval. The fourth approval of a month succeeds; the fifth is rejected with `ERR_GIVEAWAY_QUOTA_EXCEEDED`. Approval stamps `decided_by_user_id` and `decided_at` and bumps `version`. Denial stamps the same two fields and moves the award to `DENIED`.

Fulfillment is the coordinator's hand-over. The award must be `APPROVED` (else `ERR_AWARD_NOT_APPROVED`), the fulfiller's `X-User-ID` must differ from `decided_by_user_id` (else `ERR_FULFILLER_IS_APPROVER`, per §2.9), the bike must still be `READY_FOR_DISPOSITION` (else `ERR_BIKE_NOT_AVAILABLE`), and no `PENDING` sale may reference the bike — a pending sale blocks fulfillment with `ERR_SALE_PENDING_CONFLICT`. A `YOUTH` recipient additionally requires a helmet distributed as `GIVEAWAY_RECIPIENT` referencing this award, else `ERR_HELMET_REQUIRED`; adult recipients carry no helmet precondition. Fulfillment stamps `fulfilled_by_user_id`, moves the award to `FULFILLED`, moves the bike to `GIFTED`, and bumps both records' versions.

A director may cancel an `APPROVED` award — recording an optional `reason` — moving it to `CANCELLED`. Cancellation frees the monthly quota slot, because cancelled awards are excluded from the quota count.

### 3.11. Helmets: Distribution as a Compliance Gate

Helmet distribution is how the shop proves a rider left with head protection. Each distribution names a `helmet_part_id` referencing a part whose `category` is `HELMET` — any other SKU is rejected with `ERR_NOT_A_HELMET_SKU` — and decrements that SKU's `quantity_on_hand` by 1, bumping the part's `version` and recomputing `low_stock`. A distribution when the SKU's stock is zero is rejected with `ERR_HELMET_OUT_OF_STOCK`.

The recipient discipline is exact and is what ties helmets to the three compliance gates above. The `recipient_kind` field is one of `EARN_A_BIKE_GRADUATE`, `SALE_BUYER`, `GIVEAWAY_RECIPIENT`, or `COMMUNITY`, and exactly the matching reference must be present with the others absent, else `ERR_RECIPIENT_REFERENCE_MISMATCH`: an earn-a-bike graduate distribution carries `participant_id` (and the participant must be `HOURS_MET`, else `ERR_INVALID_STATE`); a sale-buyer distribution carries `sale_id` (and the sale must be `PENDING`, else `ERR_SALE_NOT_PENDING`); a giveaway-recipient distribution carries `giveaway_id` (and the award must be `APPROVED`, else `ERR_AWARD_NOT_APPROVED`); and a community distribution carries a free-text `recipient_name` with no reference at all. Each row records the distributor's opaque id as `distributed_by_user_id`. Because distributions are recorded before the gated event — graduation, fulfillment, or completion — the gates in §3.8, §3.9, and §3.10 are simple existence checks over this ledger.

### 3.12. Tool Memberships and Stand Sessions

A tool-access membership opens with a `member_name`, `member_email`, a `tier` of `BASIC` or `PRO`, and an `end_date` given as an inclusive calendar date. The record enters `ACTIVE` with `start_date` stamped from the logical clock. A coordinator may suspend a membership — recording an optional `suspended_reason` — and later reinstate it; the `ACTIVE → SUSPENDED → ACTIVE` cycle may repeat freely. The ops sweep expires a membership from either `ACTIVE` or `SUSPENDED` once the clock's date passes `end_date`, moving it to `EXPIRED`.

Stand sessions book one of the shop's four work stands. Booking — by a coordinator, or by the member for their own membership, with a member booking for any other membership rejected with `ERR_FORBIDDEN` per §2.1 — requires the membership `ACTIVE` (else `ERR_MEMBERSHIP_NOT_ACTIVE`), a `stand_number` between 1 and 4 inclusive (else `ERR_STAND_NUMBER_INVALID`), and a `start_time` and `end_time` whose span runs 30 to 180 minutes inclusive (else `ERR_SESSION_DURATION_INVALID`). The shop enforces a 15-minute cleanup buffer per stand: against every `BOOKED` or `IN_USE` session on the same stand, the new session must either begin at least 15 minutes after the existing session ends or end at least 15 minutes before the existing one begins; mere adjacency with a shorter gap is rejected with `ERR_STAND_BUFFER_CONFLICT`. A booked session is `BOOKED`.

Starting belongs to the owning member: the caller's `X-User-ID` must equal the session's `membership_id`, else `ERR_MEMBER_NOT_OWNER`. The membership must still be `ACTIVE` (else `ERR_MEMBERSHIP_NOT_ACTIVE`), and the clock must have reached 10 minutes before `start_time` — starting earlier is rejected with `ERR_START_TOO_EARLY`. Starting moves the session `BOOKED → IN_USE` and stamps `started_at`. Closing an in-use session — by the owning member (else `ERR_MEMBER_NOT_OWNER`) or a coordinator — moves it to `CLOSED`, stamps `closed_at`, and makes the session billable. Cancelling a booked session — same ownership rule — moves it to `CANCELLED`. The ops sweep marks a `BOOKED` session `NO_SHOW` once the clock is at least 30 minutes past `start_time`; no-show sessions are never billable.

Monthly billing reads the tier. Billable sessions are the membership's sessions in `IN_USE` or `CLOSED` status whose `start_time` falls within the calendar month, from the first instant of the month up to but not including the first instant of the next month; `BOOKED`, `CANCELLED`, and `NO_SHOW` sessions never bill. Under the `BASIC` tier's per-session variant, the bill is 400 cents per billable session, capped at 3000 cents for the month. Under the `PRO` tier's flat-monthly variant, the bill is 2500 cents regardless of session count. The billing read reports the `membership_id`, the `month`, the `tier`, the `session_count`, and the computed `amount_cents`; the `month` parameter defaults to the clock's current month.

### 3.13. Scrap: Tickets, Pickup, and the Recycler Statement

A bike reaches the scrap stream two ways: routed directly from triage when it is grade `D` with frame damage, or after harvest when everything reusable has been stripped. Opening a scrap ticket — against a bike that is `HARVESTED` or already `SCRAP_PENDING` — requires that no other open ticket exist for the bike, else `ERR_SCRAP_TICKET_OPEN`. The ticket captures the frame `material` (`STEEL`, `ALUMINUM`, or `MIXED`), the `weight_kg` (greater than 0 and at most 100, else `ERR_WEIGHT_INVALID`), and the `recycler_name`. Opening the ticket from a `HARVESTED` bike moves it to `SCRAP_PENDING` and bumps the bike's `version`.

The payout is fixed per ticket: weight times the material rate — 15 cents per kilogram for steel, 85 for aluminum, 10 for mixed — rounded half up to whole cents at creation. Confirming pickup is a director's action against an `OPEN` ticket (anything else is rejected with `ERR_TICKET_NOT_OPEN`): the ticket moves to `PICKED_UP` with `picked_up_at` stamped from the clock, the bike moves `SCRAP_PENDING → SCRAPPED`, and both records' versions bump.

The recycler statement aggregates a calendar month: the sum of `payout_cents` over tickets picked up within that month. Because each ticket's payout was rounded at creation, the statement sums already-rounded values — never re-rounding a month of raw weights. The statement read reports the `month` (defaulting to the clock's current month), the `ticket_count`, and the `total_payout_cents`.

### 3.14. Donation Receipts: Two Valuation Variants

A donor's annual receipt is computed on read, and the computation deliberately reports both valuation variants side by side. The input set is the donor's donated bikes whose `created_at` falls in the requested calendar year and whose `condition_grade` is set — ungraded bikes still in `RECEIVED` are excluded. The `year` parameter defaults to the clock's current year.

Under the flat schedule, each bike contributes by grade: `A` 15000 cents, `B` 9000, `C` 4000, `D` 1000, regardless of bike type. Under the comparable-value variant, a grade-`A`, `B`, or `C` bike contributes 60 percent of its pricing base scaled by the grade multiplier — the same base-by-type and grade factors used for sales — rounded half up to whole cents; a grade-`D` bike contributes 10 percent of its pricing base, rounded half up. Rounding is pinned per bike: each per-bike value is rounded to whole cents first, and only then are the rounded values summed.

The receipt response reports the `donor_id`, the `year`, the counted `bike_count`, both totals (`flat_total_cents` and `fmv_total_cents`), the donor's `receipt_method`, and the `effective_total_cents` — the flat total when the method is `FLAT_SCHEDULE`, the comparable total when it is `FMV_COMPARABLE`. The donor's `lifetime_receipt_value_cents` is the same effective variant evaluated across all years, and it recomputes whenever a bike of theirs is triaged.

## 4. Endpoint Definitions

All endpoints return 201 when a new resource is created and 200 when an existing resource is modified or read. The table below is a summary; request payloads, response bodies, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /_clock/set_current_utc | Advance the logical clock | ShopCoordinator |
| POST | /ops/run-sweep | Run the operations sweep checkpoint | ShopCoordinator |
| POST | /donors | Register a donor | ShopCoordinator |
| GET | /donors/{id} | Fetch donor | ShopCoordinator, ProgramDirector |
| GET | /donors | List donors | ShopCoordinator, ProgramDirector |
| GET | /donors/{id}/receipt | Annual donation receipt under both variants | ShopCoordinator, ProgramDirector |
| POST | /bikes | Donated bike intake | ShopCoordinator |
| GET | /bikes/{id} | Fetch bike | ShopCoordinator, ProgramDirector, Volunteer, Participant, Member |
| GET | /bikes | List/filter bikes | ShopCoordinator, ProgramDirector, Volunteer, Participant, Member |
| POST | /bikes/{id}/triage | Grade the bike (RECEIVED to TRIAGED) | ShopCoordinator |
| POST | /bikes/{id}/route | Route triaged/refurb bike to a destination | ShopCoordinator |
| POST | /bikes/{id}/submit-safety | Submit refurbished bike for safety review | Volunteer |
| POST | /bikes/{id}/safety-inspections | Record a safety inspection | Volunteer |
| GET | /safety-inspections/{id} | Fetch inspection | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /safety-inspections | List/filter inspections | ShopCoordinator, ProgramDirector, Volunteer |
| POST | /bikes/{id}/harvest-logs | Log a harvested part into stock | Volunteer |
| GET | /harvest-logs/{id} | Fetch harvest log | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /harvest-logs | List/filter harvest logs | ShopCoordinator, ProgramDirector, Volunteer |
| POST | /bikes/{id}/harvest-complete | Complete harvest of a queued bike | ShopCoordinator |
| POST | /bikes/{id}/usage-logs | Consume a part on a bike under refurbishment | Volunteer |
| GET | /usage-logs/{id} | Fetch usage log | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /usage-logs | List/filter usage logs | ShopCoordinator, ProgramDirector, Volunteer |
| POST | /usage-logs/{id}/void | Void a committed usage | ProgramDirector |
| POST | /bikes/{id}/scrap-tickets | Open a scrap ticket | ShopCoordinator |
| GET | /scrap-tickets/{id} | Fetch scrap ticket | ShopCoordinator, ProgramDirector |
| GET | /scrap-tickets | List/filter scrap tickets | ShopCoordinator, ProgramDirector |
| GET | /scrap-tickets/statement | Monthly recycler statement | ShopCoordinator, ProgramDirector |
| POST | /scrap-tickets/{id}/pick-up | Confirm recycler pickup | ProgramDirector |
| POST | /parts | Create a parts SKU | ShopCoordinator |
| GET | /parts/{id} | Fetch part | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /parts | List/filter parts | ShopCoordinator, ProgramDirector, Volunteer |
| POST | /parts/{id}/restock | Purchase stock | ShopCoordinator |
| POST | /volunteers | Register volunteer | ShopCoordinator |
| GET | /volunteers/{id} | Fetch volunteer | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /volunteers | List/filter volunteers | ShopCoordinator, ProgramDirector |
| POST | /volunteers/{id}/promote | Advance skill one level | ProgramDirector |
| POST | /volunteers/{id}/suspend | Suspend engagement | ProgramDirector |
| POST | /volunteers/{id}/reinstate | Reinstate a suspended volunteer | ProgramDirector |
| POST | /training-sessions | Schedule a training class | ShopCoordinator |
| GET | /training-sessions/{id} | Fetch session | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /training-sessions | List/filter sessions | ShopCoordinator, ProgramDirector, Volunteer |
| POST | /training-sessions/{id}/enroll | Enroll a volunteer in a session | ShopCoordinator |
| POST | /training-sessions/{id}/complete | Complete a session with attendance marks | ShopCoordinator |
| POST | /training-sessions/{id}/cancel | Cancel a scheduled session | ShopCoordinator |
| GET | /attendances/{id} | Fetch attendance | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /attendances | List/filter attendances | ShopCoordinator, ProgramDirector, Volunteer |
| POST | /shifts | Schedule a volunteer shift | ShopCoordinator |
| GET | /shifts/{id} | Fetch shift | ShopCoordinator, ProgramDirector, Volunteer |
| GET | /shifts | List/filter shifts | ShopCoordinator, ProgramDirector, Volunteer |
| POST | /shifts/{id}/check-in | Owning volunteer checks in | Volunteer |
| POST | /shifts/{id}/complete | Confirm shift completion and credit minutes | ShopCoordinator |
| POST | /shifts/{id}/cancel | Cancel a scheduled shift | ShopCoordinator, Volunteer |
| POST | /participants | Enroll an earn-a-bike participant | ShopCoordinator |
| GET | /participants/{id} | Fetch participant | ShopCoordinator, ProgramDirector, Participant |
| GET | /participants | List/filter participants | ShopCoordinator, ProgramDirector |
| POST | /participants/{id}/record-quiz | Record safety quiz outcome | ShopCoordinator |
| POST | /participants/{id}/hour-logs | Log earn-a-bike hours | ShopCoordinator, Participant |
| GET | /hour-logs/{id} | Fetch hour log | ShopCoordinator, ProgramDirector, Participant |
| GET | /hour-logs | List/filter hour logs | ShopCoordinator, ProgramDirector |
| POST | /hour-logs/{id}/approve | Approve pending hours | ShopCoordinator |
| POST | /hour-logs/{id}/reject | Reject pending hours | ShopCoordinator |
| POST | /hour-logs/{id}/void | Void approved hours | ProgramDirector |
| POST | /participants/{id}/reserve-bike | Reserve a bike for graduation | ShopCoordinator, Participant |
| POST | /participants/{id}/release-bike | Release the reserved bike | ShopCoordinator, Participant |
| POST | /participants/{id}/graduate | Graduate a participant | ProgramDirector |
| POST | /participants/{id}/withdraw | Withdraw a participant | ShopCoordinator, Participant |
| POST | /sales | Open a pending sale | ShopCoordinator |
| GET | /sales/{id} | Fetch sale | ShopCoordinator, ProgramDirector |
| GET | /sales | List/filter sales | ShopCoordinator, ProgramDirector |
| POST | /sales/{id}/complete | Complete a sale | ShopCoordinator |
| POST | /sales/{id}/void | Void a pending sale | ProgramDirector |
| POST | /giveaways | Request a giveaway award | ShopCoordinator |
| GET | /giveaways/{id} | Fetch award | ShopCoordinator, ProgramDirector |
| GET | /giveaways | List/filter awards | ShopCoordinator, ProgramDirector |
| POST | /giveaways/{id}/approve | Approve an award (quota-enforced) | ProgramDirector |
| POST | /giveaways/{id}/deny | Deny an award | ProgramDirector |
| POST | /giveaways/{id}/fulfill | Fulfill an approved award | ShopCoordinator |
| POST | /giveaways/{id}/cancel | Cancel an approved award | ProgramDirector |
| POST | /memberships | Open a tool-access membership | ShopCoordinator |
| GET | /memberships/{id} | Fetch membership | ShopCoordinator, ProgramDirector, Member |
| GET | /memberships | List/filter memberships | ShopCoordinator, ProgramDirector |
| POST | /memberships/{id}/suspend | Suspend a membership | ShopCoordinator |
| POST | /memberships/{id}/reinstate | Reinstate a membership | ShopCoordinator |
| GET | /memberships/{id}/billing | Monthly membership bill | ShopCoordinator, ProgramDirector, Member |
| POST | /memberships/{id}/sessions | Book a stand session | ShopCoordinator, Member |
| GET | /sessions/{id} | Fetch session | ShopCoordinator, ProgramDirector, Member |
| GET | /sessions | List/filter sessions | ShopCoordinator, ProgramDirector |
| POST | /sessions/{id}/start | Start a booked session | Member |
| POST | /sessions/{id}/close | Close an in-use session | ShopCoordinator, Member |
| POST | /sessions/{id}/cancel | Cancel a booked session | ShopCoordinator, Member |
| POST | /helmet-distributions | Distribute one helmet | ShopCoordinator |
| GET | /helmet-distributions/{id} | Fetch distribution | ShopCoordinator, ProgramDirector |
| GET | /helmet-distributions | List/filter distributions | ShopCoordinator, ProgramDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_BIKE_NOT_AVAILABLE | 409 |
| ERR_AWARD_NOT_APPROVED | 409 |
| ERR_SALE_NOT_PENDING | 409 |
| ERR_TICKET_NOT_OPEN | 409 |
| ERR_MEMBERSHIP_NOT_ACTIVE | 409 |
| ERR_PARTICIPANT_NOT_ACTIVE | 409 |
| ERR_USAGE_NOT_COMMITTED | 409 |
| ERR_NOT_YOUR_SHIFT | 403 |
| ERR_MEMBER_NOT_OWNER | 403 |
| ERR_REVIEWER_IS_LOGGER | 403 |
| ERR_FULFILLER_IS_APPROVER | 403 |
| ERR_INSPECTOR_IS_REFURB_LEAD | 422 |
| ERR_CHECKLIST_INCONSISTENT | 422 |
| ERR_HELMET_REQUIRED | 422 |
| ERR_HELMET_OUT_OF_STOCK | 422 |
| ERR_NOT_A_HELMET_SKU | 422 |
| ERR_HELMET_SIZE_REQUIRED | 422 |
| ERR_RECIPIENT_REFERENCE_MISMATCH | 422 |
| ERR_SERIAL_NUMBER_CONFLICT | 409 |
| ERR_PART_NAME_CONFLICT | 409 |
| ERR_GRADE_NOT_REFURBISHABLE | 422 |
| ERR_GRADE_NOT_HARVESTABLE | 422 |
| ERR_SCRAP_CRITERIA_NOT_MET | 422 |
| ERR_LEAD_INELIGIBLE | 422 |
| ERR_VOLUNTEER_SUSPENDED | 422 |
| ERR_USAGE_SKILL_INSUFFICIENT | 422 |
| ERR_INSPECTOR_SKILL_INSUFFICIENT | 422 |
| ERR_NO_WORK_RECORDED | 422 |
| ERR_NO_HARVEST_RECORDED | 422 |
| ERR_SCRAP_TICKET_OPEN | 409 |
| ERR_SALE_ALREADY_PENDING | 409 |
| ERR_SALE_PENDING_CONFLICT | 409 |
| ERR_ALREADY_ENROLLED | 409 |
| ERR_TRAINING_FULL | 422 |
| ERR_PROMOTION_CRITERIA_NOT_MET | 422 |
| ERR_RESERVATION_EXISTS | 409 |
| ERR_NO_BIKE_RESERVED | 422 |
| ERR_QUIZ_NOT_PASSED | 422 |
| ERR_HOURS_NOT_MET | 422 |
| ERR_NOT_HARVESTABLE_CATEGORY | 422 |
| ERR_ATTENDANCE_MARKS_INCOMPLETE | 422 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_SHIFT_DURATION_INVALID | 422 |
| ERR_CHECKIN_WINDOW_CLOSED | 422 |
| ERR_STAND_BUFFER_CONFLICT | 409 |
| ERR_SESSION_DURATION_INVALID | 422 |
| ERR_STAND_NUMBER_INVALID | 422 |
| ERR_START_TOO_EARLY | 422 |
| ERR_WORK_DATE_OUT_OF_WINDOW | 422 |
| ERR_DAILY_HOURS_EXCEEDED | 422 |
| ERR_SESSION_NOT_ENDED | 422 |
| ERR_INSUFFICIENT_STOCK | 422 |
| ERR_GIVEAWAY_QUOTA_EXCEEDED | 422 |
| ERR_QUANTITY_INVALID | 422 |
| ERR_WEIGHT_INVALID | 422 |
| ERR_SHIFT_NOT_CREDITABLE | 422 |

# Financial Empowerment Center API — Product Requirements Document

## 1. Introduction

A financial empowerment center runs on a simple promise: show up, do the work, and leave with a stronger balance sheet than you arrived with. Delivering on that promise at scale means coordinating a published curriculum of multi-session workshop modules, a calendar of seat-limited workshops, attendance-based cash incentives, one-on-one coaching engagements with budget and credit goals, a matched-savings program with funder-imposed tiers and caps, a referral network to outside lenders and assistance programs, and periodic outcome reporting back to the funders who bankroll the whole operation. This document specifies the API that underpins all of it.

The system serves three constituencies with sharply different powers: program administrators who run the center, certified coaches who carry caseloads of participants, and the participants themselves, who self-register for workshops and record their own savings deposits. Several concerns cut across every workflow — coach certification gating, a no-show strike policy, waitlist promotion with travel-time buffering, optimistic concurrency on the two records most often edited from stale screens, and an exact conservation invariant over every matched-savings dollar. All temporal behavior in the system is evaluated against a controllable logical clock rather than wall-clock time, so that certification lapses, referral expirations, and reporting windows behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly three roles: `ProgramAdmin`, `Coach`, and `Participant`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`. The `ProgramAdmin` role is the unrestricted operational superset: it alone may create and retire curriculum modules, create coaches and drive certification, suspension, and reinstatement, create participants and clear restrictions or exit them, schedule, reschedule, and cancel workshops, create and close match pools, execute payouts and forfeits, compute and read funder reports, and set the logical clock.

When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting Coach record, and ownership checks on any resource that references a coach compare the resource's coach field to `X-User-ID`. A coach may mark attendance only on workshops assigned to them (the workshop's `coach_id` must equal `X-User-ID`), may open a coaching case only under their own id, may drive transitions only on their own cases, may create goal plans only for their own cases, and may create and manage only referrals where they are the referring coach. Coaches may read most resources in the system — including match pools — but may never read funder reports, and a `Coach` may never perform participant administration, pool administration, payouts, forfeits, or clock control.

When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting Participant record, and ownership checks compare the resource's participant field to `X-User-ID`. A participant may register only for themselves (the `participant_id` in the registration payload must equal `X-User-ID`), may cancel only their own registrations, may record deposits only against their own match enrollments, and may read only their own participant record and incentive summary plus their own registrations, coaching cases, goal plans, outcome snapshots, match enrollments, and referrals. A `Participant` may never append an outcome snapshot or create a referral. On list endpoints this scoping is silent — the participant simply never sees others' records — but an explicit filter parameter that would select another participant's records (a `participant_id` unequal to `X-User-ID`, or, on the goal-plan list, a `case_id` naming a case that is not theirs) is rejected with `ERR_FORBIDDEN`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A supplied `limit` outside the 1-to-100 range is clamped to the nearest bound, and a negative `offset` is clamped to 0; a `limit` or `offset` that does not parse as an integer is malformed (`ERR_INVALID_REQUEST`).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties on the creation timestamp — common under the frozen logical clock — broken by creation (insertion) order. One list overrides this default: the outcome-snapshot log is ordered by measurement time rather than creation time, as described in §3.6.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept resource-specific filter parameters alongside `limit` and `offset`. Depending on the collection these include `status`, `module_id`, `coach_id`, `participant_id`, `workshop_id`, `case_id`, `pool_id`, and `goal_plan_id`, each narrowing the list to records matching the supplied value.

### 2.4. The Logical Clock and Lazy State Sweeps

Every temporal rule in the system — workshop start comparisons, certification expiry, referral expiry, reporting windows — is evaluated against a server-held logical clock, never against wall-clock time. At server start the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An admin-only test-driving capability advances the clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`; advancing the clock applies any lazy auto-transitions that have come due, including their cascades. The setter performs no monotonicity check: the clock may be set to any supplied instant, including one earlier than its current reading. Everywhere the API accepts an ISO 8601 timestamp (`to_iso8601`, `start_at`, `end_at`, `recorded_at`, `deposited_at`), a value without an explicit offset is interpreted as UTC.

Two lazy sweeps run against this clock. First, a `CERTIFIED` coach whose `certification_expires_at` has been reached or passed is transitioned to `LAPSED` the next time that coach record is read or written, with the full stall cascade of §3.5. Second, a `SENT` referral whose `expires_at` has been reached or passed is transitioned to `EXPIRED` the next time that referral is read or written. Both sweeps apply before the triggering request is otherwise processed, so a client never observes an overdue record in its pre-sweep state.

### 2.5. Common Resource Properties

All primary resources — curriculum modules, coaches, participants, workshops, registrations, coaching cases, goal plans, match pools, match enrollments, and referrals — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification to the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments with every modification to the resource and anchors the optimistic concurrency checks of §2.8.

Both `created_at` and `updated_at` are stamped from the logical clock of §2.4 (so a record created before any clock advance carries `2026-08-01T00:00:00.000Z`), whereas the envelope's `api_request_timestamp` is wall-clock.

Two resources are exceptions. An outcome snapshot is an append-only event log entry and carries only `id` and `created_at`; both `updated_at` and `version` are absent. A funder report is computed once at creation and frozen forever; it likewise carries only `id` and `created_at`, with no `updated_at` and no `version`.

### 2.6. Money, Measurement, and Rounding

All monetary values are represented as integer cents — incentive rates, completion bonuses, incomes, pool funds, deposit amounts, accruals, and payouts alike. Where a multiplication produces a fractional cent, the result is rounded half up to the nearest integer cent. Two rounding schedules are pinned and must not be reordered. Attendance incentives are rounded per session line first — each attended session's line is rounded half up to integer cents on its own — and only then summed; summing first and rounding once is a different, incorrect algorithm. Match accrual rounds exactly once: the match ratio is multiplied by the deposit amount, the product is rounded half up to integer cents, and that rounded figure is what the cap and solvency guards compare against.

Funder report averages follow their own precision rules: the credit-score average is expressed with exactly one decimal place, rounded half up, while the savings average is rounded half up to whole integer cents.

### 2.7. Request Evaluation Pipeline

Every request is validated in a fixed global order, and the first failing check determines the error returned. The tiers, earliest to latest, are:

1. **Authentication.** Presence and validity of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization and ownership.** Role permission for the endpoint and the entity-backed ownership rules of §2.1 (`ERR_FORBIDDEN`, 403).
3. **Well-formedness.** Required fields present, types correct, enum values valid, `end_at` strictly after `start_at`, `amount_cents` greater than zero, credit scores within the 300-to-850 range, `period_end` after `period_start`, and `completion_threshold` no greater than `session_count` (`ERR_INVALID_REQUEST`, 400). A malformed request is rejected before any existence or state check runs. (The one well-formedness check that needs the target record in hand — `new_coach_id` present on a stall reassignment — runs after existence instead; see §3.4.)
4. **Existence.** Path identifiers and body foreign-key references are resolved left to right; the first unresolvable reference yields `ERR_NOT_FOUND` (404).
5. **Staleness.** The optimistic concurrency checks of §2.8 (`ERR_STALE_VERSION`, 412), evaluated before any state or business rule on the two endpoints that carry them.
6. **State legality.** The target entity must be in a valid state for the operation (`ERR_INVALID_STATE`, 409); transition-style operations additionally require the requested target state to be reachable from the current state (`ERR_INVALID_TRANSITION`, 409); deposits require an `ACTIVE` enrollment (`ERR_ENROLLMENT_NOT_ACTIVE`, 409); payout requires a `GOAL_MET` enrollment (`ERR_GOAL_NOT_MET`, 409).
7. **Business rules**, in this relative order: the coach-certification gate (`ERR_COACH_NOT_CERTIFIED`); the temporal guards (`ERR_WORKSHOP_STARTED` on registration, `ERR_WORKSHOP_NOT_STARTED` on attendance marking); scheduling conflicts (`ERR_COACH_SCHEDULE_CONFLICT`, then the participant's buffered-window check `ERR_PARTICIPANT_SCHEDULE_CONFLICT`, and — on workshop reschedule — the capacity floor `ERR_CAPACITY_BELOW_CONFIRMED`); duplicate registration (`ERR_ALREADY_REGISTERED`); an existing open case (`ERR_OPEN_CASE_EXISTS`); participant restriction (`ERR_PARTICIPANT_RESTRICTED`); uniqueness (`ERR_DUPLICATE_EMAIL`, `ERR_MODULE_CODE_TAKEN`); referential integrity (`ERR_MODULE_RETIRED`, `ERR_PLAN_REQUIRED`, `ERR_PLAN_NOT_ACTIVE`, `ERR_OUTCOME_REQUIRED`); caseload capacity (`ERR_CASELOAD_FULL`); and finally the fiscal guards — pool solvency (`ERR_POOL_INSUFFICIENT`, 402) before the per-participant match cap (`ERR_MATCH_CAP_EXCEEDED`, 409) — and the pool-close guard (`ERR_POOL_HAS_OPEN_ENROLLMENTS`).

Because earlier tiers mask later ones, a single request can only ever surface the first violation in this order: a registration attempt by a restricted participant whose payload is malformed fails at well-formedness, and a deposit that would breach both the pool's uncommitted funds and the participant's cap reports the pool-solvency failure.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry optimistic concurrency protection, and on both the version field is a non-optional part of the request body.

Creating a goal plan requires `expected_case_version`, carrying the client's last observed `version` of the parent coaching case. If the case's version has advanced since that observation — for example because another plan was created against it, or a transition moved it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before superseding a plan it has not seen. Rescheduling or re-capacitating a workshop requires `expected_workshop_version`, carrying the client's last observed `version` of the workshop; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). A reschedule is otherwise always state-legal while the workshop is `SCHEDULED`, so this version check is the sole guard against editing from a stale view.

No other endpoint accepts a version field. Successful goal-plan creation itself increments the parent case's `version` by 1, every successful case transition increments the case's `version` by 1, and every successful workshop reschedule increments the workshop's `version` by 1.

### 2.9. Conservation Invariants: Seats, Caseloads, and Pool Funds

Three derived quantities are reconciled continuously and must hold exactly after every mutation. The seat and caseload counts are computed on read rather than stored, so their movement never by itself increments a workshop's or coach's `version` or refreshes its `updated_at`; likewise the enrollment, deposit, payout, and forfeit flows rewrite a pool's `uncommitted_cents` and `paid_out_cents` in place without incrementing the pool's `version` or refreshing its `updated_at` — a pool's system-managed fields move only on pool creation and pool close.

**Workshop seats.** A workshop's `confirmed_count` always equals the number of registrations on that workshop currently in `REGISTERED` status, and it never leaves the range from zero up to the workshop's `capacity`. A registration that books a seat adds one; a later cancellation of that same registration removes one; a cancellation that triggers a waitlist promotion nets to zero, because the freed seat is immediately refilled.

**Coach caseloads.** A coach's `active_caseload` always equals the count of their coaching cases in the four open statuses `INTAKE`, `PLAN_DRAFT`, `PLAN_ACTIVE`, and `ON_HOLD`. Cases in `PLAN_STALLED`, `COMPLETED`, or `EXITED` are excluded, so a case that stalls frees a caseload seat immediately. Creation and reassignment of a case are gated on the receiving coach's `active_caseload` being strictly below their `max_caseload`.

**Pool funds.** For every match pool, the identity `total_funded_cents` equals `uncommitted_cents` plus the sum of `accrued_unpaid_cents` over that pool's non-terminal enrollments (those in `ACTIVE`, `MATCH_PAUSED`, or `GOAL_MET`) plus `paid_out_cents` must hold exactly after every deposit, payout, and forfeit. A deposit moves funds from uncommitted to accrued; a payout moves them from accrued to paid out; a forfeit moves them from accrued back to uncommitted. The pool's `total_funded_cents` never changes after pool creation.

### 2.10. Resource References and Existence Checks

The resource topology is flat: every entity is a top-level collection, and relationships are expressed through identifiers carried in request bodies — a payload containing the `module_id`, a payload containing the `case_id` — rather than through nested URLs. Existence validation covers both path identifiers and these body-carried references, resolved left to right. The first identifier or reference that does not resolve to an existing resource aborts the request with `ERR_NOT_FOUND` (HTTP 404), before any state or business rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Curriculum Modules and the Workshop Calendar

Everything participants attend is built from a **curriculum module**. A `ProgramAdmin` authors a module by supplying a `module_code` (unique across all modules; a reuse is rejected with `ERR_MODULE_CODE_TAKEN`), a human-readable `title`, a `session_count` of at least 1 describing how many sessions the full series spans, an `incentive_cents_per_hour` rate of at least 0 that prices attendance, a `completion_bonus_cents` of at least 0 paid once when a participant finishes the series, and a `completion_threshold` of at least 1 and no greater than `session_count` naming how many attended sessions of this module earn that bonus. A new module begins `ACTIVE`. Retiring a module — permitted only while it is `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise — moves it to the terminal `RETIRED` status. Retirement leaves already-scheduled workshops untouched, but any later attempt to schedule a workshop against the retired module is rejected with `ERR_MODULE_RETIRED`.

With a module in place, a `ProgramAdmin` schedules a **workshop** via a payload containing the `module_id`, the `coach_id` of the delivering coach, a `location` label, a `start_at` and `end_at` in ISO 8601 UTC, and a `capacity` of at least 1. An `end_at` that is not strictly after `start_at` is malformed (`ERR_INVALID_REQUEST`). Three business guards then apply in order: the named coach must be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`); the new session must not collide with the coach's existing commitments (`ERR_COACH_SCHEDULE_CONFLICT`, see below); and the referenced module must still be `ACTIVE` (`ERR_MODULE_RETIRED`). A scheduled workshop begins `SCHEDULED` with `confirmed_count` at 0.

The coach collision rule uses half-open intervals. A conflict exists whenever another workshop assigned to the same coach is still `SCHEDULED`, is a different workshop, and the two time ranges genuinely overlap — the new session's start falls before the other's end, and the other's start falls before the new session's end. Because the intervals are half-open, back-to-back sessions, where one session's `end_at` exactly equals the other's `start_at`, do not conflict.

While a workshop remains `SCHEDULED`, a `ProgramAdmin` may reschedule it or change its capacity, supplying any of `start_at`, `end_at`, or `capacity` together with the mandatory `expected_workshop_version` (§2.8); attempting this on a cancelled workshop fails with `ERR_INVALID_STATE`, and a stale version fails with `ERR_STALE_VERSION` before any state or business check (well-formedness and existence still precede it, per §2.7). When only one of `start_at`/`end_at` is supplied, the other keeps its current value and the `end_at`-strictly-after-`start_at` rule is enforced against that merged effective window; a supplied `capacity` must still be at least 1. When the times change, the coach collision rule is re-evaluated against the new window. Lowering `capacity` below the workshop's current `confirmed_count` is rejected with `ERR_CAPACITY_BELOW_CONFIRMED`. A successful edit — even one supplying no changed fields — increments the workshop's `version` by 1 and refreshes its `updated_at`.

Cancelling a workshop — again `ProgramAdmin`-only, and only from `SCHEDULED` on pain of `ERR_INVALID_STATE` — moves it to the terminal `CANCELLED` status and cancels every registration still sitting in `REGISTERED` or `WAITLISTED`, driving `confirmed_count` to 0. No waitlist promotion runs, because the workshop itself is gone.

### 3.2. Registration, Waitlists, and Attendance

Registration is the participant-facing heart of the workshop calendar. A `ProgramAdmin` may register anyone; a `Participant` may register only themselves, submitting a payload with the `workshop_id` and their own `participant_id`. Once the references resolve, the guards run in a fixed order: the workshop must still be `SCHEDULED` (`ERR_INVALID_STATE`); the logical clock must read strictly before the workshop's `start_at` (`ERR_WORKSHOP_STARTED`); the participant must have no buffered schedule collision (`ERR_PARTICIPANT_SCHEDULE_CONFLICT`); the participant must not already hold a `REGISTERED` or `WAITLISTED` entry on this workshop (`ERR_ALREADY_REGISTERED`); and the participant must not be `RESTRICTED` (`ERR_PARTICIPANT_RESTRICTED`).

The buffered collision rule protects travel time. Each of the participant's existing `REGISTERED` registrations is treated as if its workshop ran 30 minutes longer on both ends — starting 30 minutes earlier and ending 30 minutes later. The new registration conflicts when its start falls before an existing session's buffered end and that session's start falls before the new session's buffered end. The comparison is strict: a gap of exactly 30 minutes does not conflict, while any smaller positive gap does. Registrations in `WAITLISTED`, `ATTENDED`, `NO_SHOW`, or `CANCELLED` are ignored by this check.

Capacity decides the outcome. If the workshop's `confirmed_count` is below its `capacity`, the registration is created `REGISTERED` and `confirmed_count` rises by 1. Otherwise the registration is created `WAITLISTED` and receives a `waitlist_position` one greater than the highest position currently held on that workshop — position 1 when the waitlist is empty. The `waitlist_position` stays null while a registration is `REGISTERED`.

Cancellation is available to a `ProgramAdmin` or to the participant who owns the registration, and only from `REGISTERED` or `WAITLISTED` (anything else is `ERR_INVALID_STATE`). Cancelling a `WAITLISTED` entry changes nothing else: `confirmed_count` is untouched and the remaining waitlist positions are not renumbered. Cancelling a `REGISTERED` entry frees a seat — `confirmed_count` drops by 1 — and that freed seat immediately triggers the promotion scan, provided the workshop is still `SCHEDULED` and the logical clock still reads before its `start_at`. The scan walks the workshop's `WAITLISTED` registrations from the lowest `waitlist_position` upward, skipping any entry whose participant is no longer `ACTIVE` and any entry whose promotion would violate the buffered collision rule against that participant's other `REGISTERED` commitments; skipped entries remain `WAITLISTED`. The first eligible entry is promoted to `REGISTERED`, its `waitlist_position` is cleared, `confirmed_count` rises back by 1, and the scan stops. Promotion never depends on record ids or randomness — lowest eligible position always wins.

Once the logical clock reaches a workshop's `start_at`, attendance may be marked by a `ProgramAdmin` or by the coach assigned to that workshop, submitting an `outcome` of `ATTENDED` or `NO_SHOW`. Marking before the start is rejected with `ERR_WORKSHOP_NOT_STARTED`; marking a registration no longer `REGISTERED`, or one on a workshop no longer `SCHEDULED`, is rejected with `ERR_INVALID_STATE`; an unrecognized `outcome` is malformed (`ERR_INVALID_REQUEST`). An `ATTENDED` mark prices the session: the workshop's duration in hours is computed exactly from its `end_at` minus its `start_at`, and `incentive_earned_cents` is set to the module's `incentive_cents_per_hour` multiplied by that duration, rounded half up to integer cents. Client-supplied values for this field are always ignored; it defaults to 0 until earned. A `NO_SHOW` mark instead adds a strike, per §3.3.

Participants and staff can read a participant's **incentive summary** at any time. It reports `earned_cents` — the sum of the per-session lines over all `ATTENDED` registrations, plus the `completion_bonus_cents` of each module where the participant's attended sessions of that module have reached the module's `completion_threshold` (the bonus counts once per module) — and `provisional_cents`, a forward-looking projection that adds to `earned_cents` the per-session lines for registrations still in `REGISTERED` status plus the projected bonus for any module where attended plus registered sessions together reach the `completion_threshold` and the bonus has not yet been earned. Entries in `WAITLISTED`, `NO_SHOW`, or `CANCELLED` never contribute. The summary also reports `attended_sessions`, `registered_sessions`, and `completion_bonuses_earned_cents`. The pinned rounding order of §2.6 applies throughout: every per-session line is rounded half up to integer cents before any summation.

### 3.3. Participant Standing: No-Show Strikes, Restriction, and Exit

A `ProgramAdmin` enrolls a new **participant** with a `full_name`, an `email` unique among participants (a duplicate is rejected with `ERR_DUPLICATE_EMAIL`), and an `annual_income_cents` of at least 0 — the figure that later determines which match-rate tier applies. New participants begin `ACTIVE` with `no_show_count` at 0.

The strike policy is automatic. Every `NO_SHOW` attendance mark increments the participant's `no_show_count` by 1, and the moment that count reaches 3 the participant flips from `ACTIVE` to `RESTRICTED`; the boundary is exact, so two strikes do nothing and the third strikes. A `RESTRICTED` participant is blocked from new registrations with `ERR_PARTICIPANT_RESTRICTED`, while their existing registrations are unaffected. Restriction is reversible: a `ProgramAdmin` may clear it, which requires the participant to currently be `RESTRICTED` (`ERR_INVALID_STATE` otherwise) and returns them to `ACTIVE` with `no_show_count` reset to 0.

Exiting the program is terminal. A `ProgramAdmin` may exit a participant from either `ACTIVE` or `RESTRICTED`, moving them to `EXITED`. Every coaching case the participant still holds in a non-terminal status transitions to `EXITED` along with them, with the plan-supersession side effects described in §3.4.

### 3.4. Coaching Cases and Goal Plans

One-on-one work happens inside a **coaching case**. A `ProgramAdmin`, or a `Coach` opening a case under their own id, submits the `participant_id`, the `coach_id`, and an `intake_date` in YYYY-MM-DD form — the date that later anchors funder-report cohort membership. Three business guards apply in order: the assigned coach must be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`); the participant must not already hold a case in any non-terminal status — `INTAKE`, `PLAN_DRAFT`, `PLAN_ACTIVE`, `ON_HOLD`, or `PLAN_STALLED` (`ERR_OPEN_CASE_EXISTS`); and the coach's `active_caseload` must be strictly below their `max_caseload` (`ERR_CASELOAD_FULL`). A new case opens in `INTAKE`, and the coach's `active_caseload` is recomputed upward by 1.

Cases move through a branching state machine whose terminal states are `COMPLETED` and `EXITED`. Transitions are driven by a `ProgramAdmin` or by the coach who owns the case — a stall reassignment may also be performed by the coach taking over, and the takeover exception is judged purely from the payload: any request naming `target_state` `INTAKE` with a `new_coach_id` equal to the acting coach's id is treated as that coach's to drive, whatever the case's current state — through a payload naming a `target_state` and, for reassignment only, a `new_coach_id`. The drivable targets are exactly `INTAKE`, `PLAN_DRAFT`, `PLAN_ACTIVE`, `ON_HOLD`, `COMPLETED`, and `EXITED`; any other `target_state` value — including `PLAN_STALLED`, which is entered only through the stall cascade — is malformed (`ERR_INVALID_REQUEST`). A supplied `new_coach_id` is existence-validated like any other body reference (`ERR_NOT_FOUND`) but leaves the case's `coach_id` unchanged outside the `PLAN_STALLED` → `INTAKE` branch. A target that is not reachable from the case's current state is rejected with `ERR_INVALID_TRANSITION`, and every successful transition increments the case's `version` by 1. The full machine:

- `INTAKE` → `PLAN_DRAFT`: requires the assigned coach to still be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`).
- `PLAN_DRAFT` → `INTAKE`: the revision loop; any existing `DRAFT` goal plans simply remain `DRAFT`.
- `PLAN_DRAFT` → `PLAN_ACTIVE`: requires a goal plan for the case in `DRAFT` status to exist (`ERR_PLAN_REQUIRED`); that plan is activated, moving `DRAFT` → `ACTIVE`.
- `PLAN_ACTIVE` → `ON_HOLD`: the case's `ACTIVE` goal plan freezes to `FROZEN`, and that freeze pauses the linked match enrollment — the one whose `goal_plan_id` names this plan, while it is `ACTIVE` — moving it to `MATCH_PAUSED`.
- `ON_HOLD` → `PLAN_ACTIVE`: requires the assigned coach to be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`); the case's `FROZEN` plan returns to `ACTIVE`, and the paused enrollment resumes to `ACTIVE`.
- `PLAN_ACTIVE` → `COMPLETED`: requires at least one outcome snapshot to exist for the participant (`ERR_OUTCOME_REQUIRED`); the case's `ACTIVE` plan transitions to `ACHIEVED`.
- `EXITED` is reachable from `INTAKE`, `PLAN_DRAFT`, `PLAN_ACTIVE`, `ON_HOLD`, and `PLAN_STALLED` alike; in every one of those branches the case's `ACTIVE` or `FROZEN` goal plan transitions to `SUPERSEDED`, and any linked non-terminal match enrollment is deliberately left unchanged.
- `PLAN_STALLED` → `INTAKE` is the reassignment path. The request must carry `new_coach_id` — its absence is malformed (`ERR_INVALID_REQUEST`), evaluated once the case (and any supplied `new_coach_id`) has been resolved, before transition legality is considered — the new coach must be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`), and the new coach's `active_caseload` must be strictly below `max_caseload` (`ERR_CASELOAD_FULL`). The case's `coach_id` is reassigned, and a `FROZEN` goal plan stays `FROZEN` until the case again reaches `PLAN_ACTIVE`.

A **goal plan** captures the budget and credit targets of the engagement. A `ProgramAdmin`, or the coach owning the case, creates one with the `case_id`, a `monthly_savings_goal_cents` greater than 0, a `credit_score_target` within the 300-to-850 range, and the mandatory `expected_case_version` (§2.8) — the staleness check runs before any state evaluation, so a writer holding an outdated view of the case is stopped with `ERR_STALE_VERSION` rather than silently superseding a plan it never saw. The named case must be in `PLAN_DRAFT` (`ERR_INVALID_STATE` otherwise). The new plan begins `DRAFT`, receives a `plan_sequence` equal to 1 plus the count of prior plans ever created for the case — monotonic per case — and its creation supersedes any existing `DRAFT` plans of the same case, moving them to `SUPERSEDED`; the parent case's `version` rises by 1.

Beyond creation, a plan's lifecycle is entirely system-driven by the case around it: `DRAFT` → `ACTIVE` when the case enters `PLAN_ACTIVE`; `ACTIVE` → `FROZEN` when the case goes `ON_HOLD` or stalls; `FROZEN` → `ACTIVE` when the case resumes from `ON_HOLD`; `ACTIVE` → `ACHIEVED` when the case completes; and `ACTIVE` or `FROZEN` → `SUPERSEDED` when the case exits. `SUPERSEDED` and `ACHIEVED` are terminal.

### 3.5. Coach Certification, Suspension, and the Stall Cascade

A `ProgramAdmin` adds a **coach** with a `full_name`, an `email` unique among coaches (duplicates fail with `ERR_DUPLICATE_EMAIL`), and a `max_caseload` of at least 1 capping how many open cases the coach may hold. A new coach starts as a `CANDIDATE` with `active_caseload` 0 and a null `certification_expires_at`.

Certification is the gate to all delivery work. A `ProgramAdmin` certifies a coach — only from `CANDIDATE`, otherwise `ERR_INVALID_STATE` — moving them to `CERTIFIED` and stamping `certification_expires_at` at exactly 365 days after the current logical-clock reading. Certification decays: the first read or write of the coach record at or after that expiry lazily sweeps the coach from `CERTIFIED` to `LAPSED`, and the sweep carries the same cascade as a suspension.

Suspension is explicit. A `ProgramAdmin` suspends a coach — only from `CERTIFIED`, otherwise `ERR_INVALID_STATE` — moving them to `SUSPENDED` and setting off a three-link cascade. Link 1: every coaching case assigned to this coach in `INTAKE`, `PLAN_DRAFT`, or `PLAN_ACTIVE` transitions to `PLAN_STALLED`. Link 2: each case entering `PLAN_STALLED` freezes its `ACTIVE` goal plan to `FROZEN`. Link 3: each plan entering `FROZEN` pauses the match enrollment linked to it by `goal_plan_id` while that enrollment is `ACTIVE`, moving it to `MATCH_PAUSED` — and deposits against a paused enrollment are rejected with `ERR_ENROLLMENT_NOT_ACTIVE` until it resumes. Finally the coach's `active_caseload` is recomputed; because `PLAN_STALLED` is excluded from the caseload count, it drops by exactly the number of stalled cases.

A `ProgramAdmin` may reinstate a coach from either `SUSPENDED` or `LAPSED` — from any other state the call fails with `ERR_INVALID_STATE` — returning them to `CERTIFIED` with `certification_expires_at` refreshed to 365 days after the current logical-clock reading. Reinstatement deliberately does not resurrect stalled cases: each one must be explicitly reassigned through the `PLAN_STALLED` → `INTAKE` transition of §3.4.

### 3.6. Outcome Snapshots

Progress evidence accumulates as **outcome snapshots**, an append-only log. A `ProgramAdmin` or `Coach` — never a `Participant` — appends an entry naming the `participant_id`, the `recorded_at` instant the measurement was taken (ISO 8601 UTC), and at least one of the two metrics: a `credit_score` within the 300-to-850 range, or a `savings_balance_cents` of at least 0. An entry carrying neither metric is malformed (`ERR_INVALID_REQUEST`); each metric may also be omitted on its own, and an omitted metric is serialized as null on read. Being append-only, a snapshot carries only `id` and `created_at` as system fields — no `updated_at`, no `version` (§2.5).

Snapshots are always read in measurement order: the list is sorted by `recorded_at` ascending, with ties broken by `created_at` ascending and any remaining ties by creation (insertion) order — an explicit override of the default list ordering in §2.3. Two workflows consume the log. Case completion requires at least one snapshot for the participant (`ERR_OUTCOME_REQUIRED`, §3.4), and funder aggregation draws its deltas from in-period snapshots (§3.9).

### 3.7. Matched Savings: Pools, Enrollments, and Deposits

The matched-savings program is funded through **match pools**. A `ProgramAdmin` creates a pool with a `name` (the program-cohort label), a `total_funded_cents` greater than 0 that fixes the pool's lifetime funding, an `income_threshold_cents` dividing the two match tiers, a `match_ratio_below` multiplier for participants whose income is under the threshold, a `match_ratio_above` multiplier for those at or above it, and a `per_participant_cap_cents` greater than 0 capping what any single enrollment may accrue. `income_threshold_cents` is accepted as any integer and both ratios as any JSON number — no range validation applies to them. A new pool is `ACTIVE` with `uncommitted_cents` equal to `total_funded_cents` and `paid_out_cents` at 0.

A `ProgramAdmin` or `Coach` enrolls a participant by naming the `participant_id`, the `pool_id`, the `goal_plan_id` the savings are anchored to, and a `savings_goal_cents` greater than 0. The referenced goal plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`), and that check runs first; the pool must then be `ACTIVE` with `uncommitted_cents` of at least the pool's `per_participant_cap_cents` — enough to fully back the new enrollment's cap — failing which the enrollment is rejected with `ERR_POOL_INSUFFICIENT` (HTTP 402). A new enrollment starts `ACTIVE` with `total_deposited_cents` and `accrued_unpaid_cents` at 0.

Deposits are the everyday act of the program, open to a `ProgramAdmin`, a `Coach`, or the owning `Participant`. The payload carries an `amount_cents` greater than 0 — anything else is `ERR_INVALID_REQUEST` — and may optionally carry a `deposited_at` timestamp, which is validated as ISO 8601 when present but neither persisted nor echoed in any response. The enrollment must be `ACTIVE`: deposits against a `MATCH_PAUSED`, `GOAL_MET`, or terminal enrollment are rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. The match accrual then prices the deposit. The applicable ratio is the pool's `match_ratio_below` when the participant's `annual_income_cents` is strictly below the pool's `income_threshold_cents`, and `match_ratio_above` when it is at or above the threshold. The accrual candidate is that ratio multiplied by `amount_cents`, rounded half up to integer cents — exactly once, before any guard comparison. Two fiscal guards can each reject the deposit in full, with pool solvency evaluated before the per-participant cap (§2.7): a candidate exceeding the pool's current `uncommitted_cents` fails with `ERR_POOL_INSUFFICIENT` (HTTP 402), and a candidate exceeding the cap room remaining — the pool's `per_participant_cap_cents` minus the enrollment's current `accrued_unpaid_cents` — fails with `ERR_MATCH_CAP_EXCEEDED`. An accepted deposit adds `amount_cents` to the enrollment's `total_deposited_cents`, adds the candidate to its `accrued_unpaid_cents`, and draws the candidate down from the pool's `uncommitted_cents`. When `total_deposited_cents` reaches or exceeds the enrollment's `savings_goal_cents`, the enrollment advances automatically from `ACTIVE` to `GOAL_MET`.

Settlement has two doors, both `ProgramAdmin`-only. Payout requires the enrollment to be `GOAL_MET` — any other status, including the terminal `PAID_OUT` and `FORFEITED`, fails with `ERR_GOAL_NOT_MET` — and moves it to `PAID_OUT`, adding the full `accrued_unpaid_cents` to the pool's `paid_out_cents` and zeroing the accrual. Forfeiture is permitted from `ACTIVE`, `MATCH_PAUSED`, or `GOAL_MET` (otherwise `ERR_INVALID_STATE`) and moves the enrollment to `FORFEITED`, returning the full `accrued_unpaid_cents` to the pool's `uncommitted_cents` and zeroing the accrual. Both doors preserve the conservation identity of §2.9 exactly.

Closing a pool is the final administrative act: the pool must be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and must hold no enrollment still in `ACTIVE`, `MATCH_PAUSED`, or `GOAL_MET` — any such straggler blocks the close with `ERR_POOL_HAS_OPEN_ENROLLMENTS`. A `CLOSED` pool accepts no new enrollments, and `PAID_OUT` and `FORFEITED` are terminal for the enrollments themselves.

### 3.8. Referrals to Lenders and Assistance Programs

Coaches routinely hand participants off to outside partners. A `ProgramAdmin` or `Coach` creates a **referral** with the `participant_id`, the referring `coach_id`, a `partner_name`, and a `partner_type` of either `LENDER` or `ASSISTANCE_PROGRAM` — any other value is `ERR_INVALID_REQUEST`, and a coach may create only referrals under their own id. The referral is born `SENT`, with `sent_at` stamped from the logical clock and `expires_at` computed as exactly 30 days after `sent_at`; both `sent_at` and `expires_at` are serialized in responses as ISO 8601 UTC timestamps with three fractional digits, in the same format as the system-managed timestamps of §2.5.

From `SENT`, a `ProgramAdmin` or the coach who created the referral may drive it to `ACCEPTED` or to `DECLINED` by naming the `target_state`. The only recognized `target_state` values are `ACCEPTED`, `DECLINED`, and `COMPLETED`; any other value — including `SENT` and `EXPIRED` — is malformed (`ERR_INVALID_REQUEST`). A recognized but unreachable target — including any move out of an already-terminal referral — is rejected with `ERR_INVALID_TRANSITION`. Acceptance has an extra temporal guard: it is only possible strictly before `expires_at`, because a referral whose expiry has passed is swept to `EXPIRED` before the request is otherwise processed. An `ACCEPTED` referral may later be driven to `COMPLETED` when the engagement with the partner concludes. `DECLINED`, `COMPLETED`, and `EXPIRED` are terminal. The lazy expiry sweep of §2.4 applies to every referral read and write — including list operations — so a `SENT` referral is never observed past its 30-day life.

### 3.9. Funder Outcome Reporting

Funders receive their evidence as an immutable **outcome report**, computed once by a `ProgramAdmin` and never altered thereafter. The request names a `period_start` (YYYY-MM-DD, inclusive), a `period_end` (YYYY-MM-DD, exclusive; not after `period_start` is `ERR_INVALID_REQUEST`), and a `variant` of `COHORT` or `ROLLING` selecting the inclusion set. Read-back of a report is restricted to `ProgramAdmin`.

The variant decides who is measured. `COHORT` — new-entrant reporting — includes only participants whose earliest coaching case by `intake_date` has its `intake_date` inside the window from `period_start` up to but not including `period_end`. `ROLLING` — all-served reporting — includes every participant with at least one coaching case of any status whose `intake_date` falls before `period_end`.

Within the inclusion set, deltas are computed per participant from in-period snapshots — those whose `recorded_at` date falls inside the same window — ordered by `recorded_at` ascending with ties broken by `created_at` ascending. A participant's credit delta is their latest in-period `credit_score` minus their earliest, and their savings delta is their latest in-period `savings_balance_cents` minus their earliest; a snapshot lacking a metric is simply skipped for that metric, and a participant enters a metric's average only when at least two in-period snapshots carry that metric. The report's `avg_credit_delta_points` is the mean of the qualifying credit deltas, expressed with one decimal place and rounded half up, or null when no participant qualifies; its `avg_savings_delta_cents` is the mean of the qualifying savings deltas rounded half up to integer cents, likewise null when empty. `participants_measured` counts the qualifying participants — those contributing at least two in-period snapshots for the credit metric, or, for the savings average, the savings metric. Finally, `completions_count` tallies the coaching cases whose transition to `COMPLETED` happened at a logical-clock time whose date falls inside the reporting window.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code: modules, coaches, participants, workshops, registrations, coaching cases, goal plans, outcome snapshots, match pools, match enrollments, deposits, referrals, and funder reports. Operations that modify an existing resource, drive a state transition, or perform a read return `200 OK`. The table below is a summary only; the full request and response semantics of each operation are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; applies due lazy sweeps | ProgramAdmin |
| POST | `/curriculum-modules` | Create a curriculum module | ProgramAdmin |
| GET | `/curriculum-modules/{id}` | Get a module | ProgramAdmin, Coach, Participant |
| POST | `/curriculum-modules/{id}/retire` | Retire a module | ProgramAdmin |
| POST | `/coaches` | Create a coach (starts CANDIDATE) | ProgramAdmin |
| GET | `/coaches/{id}` | Get a coach (certification lazy sweep applies first) | ProgramAdmin, Coach, Participant |
| POST | `/coaches/{id}/certify` | Certify a CANDIDATE coach | ProgramAdmin |
| POST | `/coaches/{id}/suspend` | Suspend a CERTIFIED coach (runs the stall cascade) | ProgramAdmin |
| POST | `/coaches/{id}/reinstate` | Reinstate a SUSPENDED or LAPSED coach | ProgramAdmin |
| POST | `/participants` | Create a participant | ProgramAdmin |
| GET | `/participants/{id}` | Get a participant (Participant role: self only) | ProgramAdmin, Coach, Participant |
| POST | `/participants/{id}/clear-restriction` | Clear a no-show restriction (strikes reset) | ProgramAdmin |
| POST | `/participants/{id}/exit` | Exit a participant from the program | ProgramAdmin |
| GET | `/participants/{id}/incentive-summary` | Earned vs provisional incentive accrual (self only for Participant) | ProgramAdmin, Coach, Participant |
| POST | `/workshops` | Schedule a workshop | ProgramAdmin |
| GET | `/workshops` | List workshops with filters | ProgramAdmin, Coach, Participant |
| GET | `/workshops/{id}` | Get a workshop | ProgramAdmin, Coach, Participant |
| PATCH | `/workshops/{id}` | Reschedule / re-capacitate a SCHEDULED workshop (OCC-guarded) | ProgramAdmin |
| POST | `/workshops/{id}/cancel` | Cancel a workshop; cancels all non-terminal registrations without promotion | ProgramAdmin |
| POST | `/registrations` | Register a participant for a workshop (REGISTERED or WAITLISTED) | ProgramAdmin, Participant |
| GET | `/registrations` | List registrations with filters | ProgramAdmin, Coach, Participant |
| GET | `/registrations/{id}` | Get a registration | ProgramAdmin, Coach, Participant |
| POST | `/registrations/{id}/cancel` | Cancel a registration; freeing a seat promotes the waitlist | ProgramAdmin, Participant |
| POST | `/registrations/{id}/mark-attendance` | Mark the attendance outcome for a started workshop | ProgramAdmin, Coach |
| POST | `/coaching-cases` | Open a coaching case (intake) | ProgramAdmin, Coach |
| GET | `/coaching-cases` | List coaching cases with filters | ProgramAdmin, Coach, Participant |
| GET | `/coaching-cases/{id}` | Get a coaching case | ProgramAdmin, Coach, Participant |
| POST | `/coaching-cases/{id}/transition` | Drive the case state machine (new_coach_id required from PLAN_STALLED) | ProgramAdmin, Coach |
| POST | `/goal-plans` | Create a goal plan for a PLAN_DRAFT case (OCC-guarded on the case) | ProgramAdmin, Coach |
| GET | `/goal-plans` | List goal plans with filters | ProgramAdmin, Coach, Participant |
| GET | `/goal-plans/{id}` | Get a goal plan | ProgramAdmin, Coach, Participant |
| POST | `/outcome-snapshots` | Append a credit-score and/or savings-balance measurement | ProgramAdmin, Coach |
| GET | `/outcome-snapshots` | List snapshots in measurement order | ProgramAdmin, Coach, Participant |
| GET | `/outcome-snapshots/{id}` | Get a single snapshot | ProgramAdmin, Coach, Participant |
| POST | `/match-pools` | Create a matched-savings pool | ProgramAdmin |
| GET | `/match-pools/{id}` | Get a pool | ProgramAdmin, Coach |
| POST | `/match-pools/{id}/close` | Close a pool with no open enrollments | ProgramAdmin |
| POST | `/match-enrollments` | Enroll a participant in a pool against an ACTIVE goal plan | ProgramAdmin, Coach |
| GET | `/match-enrollments` | List enrollments with filters | ProgramAdmin, Coach, Participant |
| GET | `/match-enrollments/{id}` | Get an enrollment | ProgramAdmin, Coach, Participant |
| POST | `/match-enrollments/{id}/deposits` | Record a savings deposit; accrues match per the tier rules | ProgramAdmin, Coach, Participant |
| POST | `/match-enrollments/{id}/payout` | Pay out the accrued match once GOAL_MET | ProgramAdmin |
| POST | `/match-enrollments/{id}/forfeit` | Forfeit the accrued match back to the pool | ProgramAdmin |
| POST | `/referrals` | Refer a participant to a lender or assistance program | ProgramAdmin, Coach |
| GET | `/referrals` | List referrals with filters (expiry lazy sweep applies first) | ProgramAdmin, Coach, Participant |
| GET | `/referrals/{id}` | Get a referral (expiry lazy sweep applies first) | ProgramAdmin, Coach, Participant |
| POST | `/referrals/{id}/transition` | Drive the referral state machine (ACCEPTED, DECLINED, COMPLETED) | ProgramAdmin, Coach |
| POST | `/funder-reports` | Compute an immutable outcome report for a period and variant | ProgramAdmin |
| GET | `/funder-reports/{id}` | Get a report | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_GOAL_NOT_MET` | 409 Conflict |
| `ERR_COACH_NOT_CERTIFIED` | 409 Conflict |
| `ERR_WORKSHOP_STARTED` | 409 Conflict |
| `ERR_WORKSHOP_NOT_STARTED` | 409 Conflict |
| `ERR_COACH_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_PARTICIPANT_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_ALREADY_REGISTERED` | 409 Conflict |
| `ERR_OPEN_CASE_EXISTS` | 409 Conflict |
| `ERR_PARTICIPANT_RESTRICTED` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_MODULE_CODE_TAKEN` | 409 Conflict |
| `ERR_MODULE_RETIRED` | 409 Conflict |
| `ERR_PLAN_REQUIRED` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_OUTCOME_REQUIRED` | 409 Conflict |
| `ERR_CASELOAD_FULL` | 409 Conflict |
| `ERR_POOL_INSUFFICIENT` | 402 Payment Required |
| `ERR_MATCH_CAP_EXCEEDED` | 409 Conflict |
| `ERR_POOL_HAS_OPEN_ENROLLMENTS` | 409 Conflict |
| `ERR_CAPACITY_BELOW_CONFIRMED` | 409 Conflict |

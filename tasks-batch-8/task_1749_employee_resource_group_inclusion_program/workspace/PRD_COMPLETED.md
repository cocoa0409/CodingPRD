# Employee Resource Group Inclusion API — Product Requirements Document

## 1. Introduction

Corporate Diversity, Equity & Inclusion offices run Employee Resource Group (ERG) programs that coordinate dozens of employee-led affinity groups, each operating under an executive sponsor's oversight and each drawing from a shared fiscal-year budget pool. Today's process is a patchwork of spreadsheets, email approvals, and disconnected calendar invites: budget commitments go unrecorded until reconciliation surprises surface at year-end, leadership transitions inside groups leave funding requests orphaned without a clear succession chain, and the DEI office cannot quantify program impact without manual data assembly.

This document specifies the Employee Resource Group Inclusion API, a single REST service that gives the DEI office a governed operating platform for the full program lifecycle. The system supports chartering new groups under executive sponsorship, running a largest-remainder budget allocation waterfall across active groups, operating a negotiation-based funding request workflow (leader submits, sponsor endorses or counters, DEI approves with a tiered external-matching top-up), tracking event participation and waitlists against venue capacity, rotating group leadership through succession-chained terms, measuring organizational climate through scored surveys that can automatically halt new chartering, and pairing mentees with sponsors under capacity and buffered-window constraints.

The API is mounted under `/v1`. A logical clock drives all time-dependent behavior — term expiry, survey windows, event scheduling, tenure gates — so operators and tests can advance time deterministically without waiting on wall-clock progression.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` (the acting party's identifier) and `X-User-Role` (the acting party's role). A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A caller whose role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Four roles are recognized, spelled exactly as follows:

- `DeiAdmin` — the corporate DEI office operator. When `X-User-Role` is `DeiAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on resources it creates but does not compare it to any entity's `id`.
- `ExecutiveSponsor` — an executive sponsor of one or more groups who endorses charters and funding requests and mentors employees. When `X-User-Role` is `ExecutiveSponsor`, `X-User-ID` is the `id` of the acting `ExecutiveSponsor` entity; sponsor-matching checks compare the group's `sponsor_id` or the engagement's `sponsor_id` field to `X-User-ID`.
- `GroupLeader` — the charter owner before activation (the employee recorded as `created_by_employee_id` on the group) and the current `ACTIVE`-term leader after activation. When `X-User-Role` is `GroupLeader`, `X-User-ID` is an opaque employee identifier not tied to any persisted entity; it is compared to `created_by_employee_id`, to the `leader_employee_id` of the group's `ACTIVE` leadership term, or to a funding request's `created_by_employee_id` depending on the operation, never to an entity `id`.
- `Employee` — any employee (an opaque HRIS identifier). When `X-User-Role` is `Employee`, `X-User-ID` is an opaque employee identifier not tied to any persisted entity; it is recorded as the `employee_id` of memberships, RSVPs, survey responses, and mentoring engagements the employee initiates for themselves, but the server does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.5).
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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0); values outside those bounds are clamped to the nearest bound, while a non-integer value is rejected with `ERR_INVALID_REQUEST`. Results are sorted by `created_at` ascending, with ties broken by creation order (earliest-created first). List responses include `limit`, `offset`, `total_count`, and `has_more` in `meta`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted entity carries a server-minted `id` formatted as a bare UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities except `SurveyResponse` additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer that starts at 1 and increments by 1 on every mutation of that entity). `SurveyResponse` carries only `id` and `created_at` — both `updated_at` and `version` are absent from it. All server-recorded timestamps, including `created_at` and `updated_at`, read the logical clock (§2.5).

### 2.5. The Logical Clock and Scheduled Sweeps

All temporal rules in this document — term expiry, survey windows, check-in gates, completion gates, tenure requirements — evaluate against a server-held logical clock, never against wall-clock time. At server startup, before any clock-setting call, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `DeiAdmin` advances the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` instant; the new value may be any valid instant — no monotonic increase over the previous value is enforced. Advancing the clock runs a term-expiry sweep: every `LeadershipTerm` in `ACTIVE` status whose `ends_at` is at or before the new clock value flips to `EXPIRED`, and each such expiry fires the leadership-gap cascade described in §3.6.

### 2.6. Validation Order Across All Endpoints

Every request passes through the same ordered validation pipeline, and when several checks could fail the earliest one determines the error surfaced. The order is:

1. **Authentication context** — `X-User-ID` and `X-User-Role` present, role value recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization** — the caller's role is in the endpoint's authorized list (`ERR_FORBIDDEN_ROLE`, 403).
3. **Request schema** — required fields present, types and enum values valid, numeric ranges valid such as `capacity` greater than zero, `ends_at` strictly after `starts_at`, survey scores inside the 1-to-5 range (`ERR_INVALID_REQUEST`, 400).
4. **Existence** — path and body-referenced resource ids exist, validated left-to-right (`ERR_NOT_FOUND`, 404).
5. **Optimistic concurrency** — on the two version-guarded writes (sponsor assignment and event reschedule), the expected-version field must match the entity's current `version` (`ERR_STALE_GROUP_VERSION` or `ERR_STALE_EVENT_VERSION`, 412).
6. **Lifecycle state gates** — the target resource's current state permits the transition, including terminal-state lockdown (state-category errors such as `ERR_INVALID_STATE_TRANSITION`, `ERR_GROUP_NOT_ACTIVE`, `ERR_PROGRAM_NOT_OPEN`, `ERR_PROGRAM_IN_CLIMATE_REVIEW`, `ERR_ALLOCATION_NOT_LOCKED`, `ERR_SURVEY_NOT_OPEN`, `ERR_EVENT_NOT_PUBLISHED`, `ERR_SPONSOR_NOT_ACTIVE`, `ERR_LEADERSHIP_GAP`, 409).
7. **Cross-referential integrity** — sponsor assignment matches, charter has a sponsor, event funding request belongs to the same group and is `APPROVED`, predecessor chain integrity (409 family).
8. **Temporal rules** — venue overlap, mentoring buffered windows, survey response windows, check-in and completion gates, single active term (409 family).
9. **Uniqueness and aggregate constraints** — name uniqueness, single membership, single RSVP, single response, term limits, tenure, founding-member minimums, minimum responses, single mentee engagement, self-pairing and self-endorsement prohibitions (409, except `ERR_MENTORING_SELF_PAIRING` at 400 and `ERR_SPONSOR_SELF_ENDORSEMENT` at 403).
10. **Capacity and budget** — available-budget ceiling, sponsor load caps, venue capacity ceilings (`ERR_INSUFFICIENT_GROUP_BUDGET` at 402; `ERR_SPONSOR_CAPACITY_EXCEEDED` and `ERR_VENUE_CAPACITY_EXCEEDED` at 409).

Actor-ownership checks that raise `ERR_NOT_GROUP_LEADER` are evaluated immediately after the step-6 lifecycle state gates and before the step-7 cross-referential checks. A sponsor self-endorsement attempt is therefore reported as 403 even though it is conceptually a business constraint, and an over-budget approval surfaces as 402 only after every earlier gate has passed.

### 2.7. Optimistic Concurrency Control

Two write operations are version-guarded; no other endpoint takes a version field.

Sponsor assignment on a group requires a non-optional `expected_group_version` carrying the client's last observed `version` of that `ErgGroup`. If the group's version has advanced since the client last read it, the assignment is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412). Reassignment legitimately supersedes the prior assignment while the group is in `CHARTER_DRAFT`, `CHANGES_REQUESTED`, or `ACTIVE`, so the stale-write guard is expressed purely as a version check: a second assignment carrying the previously observed version must fail.

Event rescheduling requires a non-optional `expected_event_version` carrying the client's last observed `version` of that `ErgEvent`. If the event's version has advanced since the client last read it, the reschedule is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). A reschedule legitimately supersedes the prior schedule while the event is `PLANNED` or `PUBLISHED`, so again the guard is purely a version check: a second reschedule carrying the previously observed version must fail.

### 2.8. Monetary Precision and Rounding

All money is integer cents. Percentages and scores are numbers carried at 2 decimal places with round-half-up rounding. The allocation waterfall rounds each group's share down to whole cents first and then distributes the remainder; the matching top-up rounds its match amount half-up to whole cents; standing scores, engagement percentages, and climate indices are all rounded half-up to 2 decimal places.

### 2.9. Program Posture as a Parallel Dimension

An `InclusionProgram` carries two independent state dimensions. `status` walks `SETUP` → `OPEN` → `ALLOCATION_LOCKED` and never reverses. `posture` cycles freely between `NORMAL` and `CLIMATE_REVIEW` and gates new group chartering: while a program's `posture` is `CLIMATE_REVIEW`, creating a new `ErgGroup` in that program is rejected with `ERR_PROGRAM_IN_CLIMATE_REVIEW` (HTTP 409). Posture flips to `CLIMATE_REVIEW` automatically when a climate survey of that program closes with a `final_index` strictly below 3.00, and returns to `NORMAL` only through an explicit `DeiAdmin` clear action carrying a `remediation_note` (the clear is rejected with `ERR_INVALID_STATE_TRANSITION` when the posture is not `CLIMATE_REVIEW`). A `final_index` of exactly 3.00 leaves posture untouched.

### 2.10. The Group Budget Ledger

Each `ErgGroup` carries a conserved three-way partition of its allocation: `allocated_cents` always equals the sum of `available_cents`, `reserved_cents`, and `spent_cents`. Of these, `available_cents` is always derived, never stored independently. At program level the pool is likewise conserved: `pool_total_cents` always equals `unallocated_pool_cents` plus the sum of `allocated_cents` over all groups of the program. Four operations move money between these buckets and are detailed in §3.4 and §3.5: approval moves funds from available to reserved; disbursement moves them from reserved to spent; reconciliation refunds the unspent remainder by reducing spent and allocated and returning the refund to the program's `unallocated_pool_cents`; dissolution of a group with `APPROVED`-but-undisbursed requests releases the reserve back to available-in-name-only by subtracting `approved_cents` from `reserved_cents`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program Year

A `DeiAdmin` begins a program year by creating an `InclusionProgram` with a `fiscal_year` label (an integer such as 2027), a `pool_total_cents` budget in cents (zero or more), and optionally a `goals` list (defaulting to an empty list when omitted). Each goal pairs a `metric` with a `target_value`; the recognized metrics are `TOTAL_ACTIVE_MEMBERS`, `EVENTS_COMPLETED`, `AVG_CAPACITY_UTILIZATION`, `LATEST_CLIMATE_INDEX`, and `MENTORING_COMPLETED_COUNT` — a goal with an unrecognized `metric` or a non-numeric `target_value` is rejected with `ERR_INVALID_REQUEST`. A new program starts in `status` `SETUP` with `posture` `NORMAL`, and its `unallocated_pool_cents` is the full pool since no group has been allocated anything yet.

Opening the program transitions `status` from `SETUP` to `OPEN` and increments the program's `version` by 1; attempting to open a program not in `SETUP` is rejected with `ERR_INVALID_STATE_TRANSITION`. Chartering, membership, and funding activity all require the program to be `OPEN` (or `ALLOCATION_LOCKED` for some flows, noted where relevant), and operations that require one of those two statuses reject a `SETUP` program with `ERR_PROGRAM_NOT_OPEN`.

The DEI office also appoints executive sponsors up front. Appointing a sponsor records the sponsor's opaque `employee_id` (expected unique across sponsors, though the server does not enforce this), a `max_groups` load cap (at least 1), and a `max_mentees` load cap (at least 1); a new sponsor starts in `status` `ACTIVE`. A sponsor's `status` may later be moved among `ACTIVE`, `ON_LEAVE`, and `INACTIVE` by a `DeiAdmin` supplying `to_status`; any sponsor-facing duty — assignment to a group, charter endorsement, mentoring acceptance — requires the sponsor to be `ACTIVE` and otherwise fails with `ERR_SPONSOR_NOT_ACTIVE`.

### 3.2. Chartering a Group

A `GroupLeader` (or a `DeiAdmin` acting on someone's behalf) drafts a charter by creating an `ErgGroup` inside a program that is `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN` otherwise, alongside the posture gate of §2.9): the payload carries the `program_id`, a `name` that must be unique within the program case-sensitively across non-terminal groups (violations surface as `ERR_GROUP_NAME_NOT_UNIQUE`), a `mission_statement`, and a `category` of `AFFINITY`, `PROFESSIONAL`, or `COMMUNITY_OUTREACH`. When a `DeiAdmin` creates the draft, an `owner_employee_id` may be supplied to name the charter owner; otherwise the creator's own `X-User-ID` becomes `created_by_employee_id`. The group starts in `CHARTER_DRAFT` with `allocated_cents`, `reserved_cents`, and `spent_cents` all zero, with `founding_member_count` and `certified_standing_score` null, and with `sponsor_id` null.

Before a charter can be submitted, a `DeiAdmin` must assign an executive sponsor. The assignment payload carries the `sponsor_id` and the OCC field `expected_group_version` (see §2.7). Three gates apply after the version check, in this order: the group must currently be in `CHARTER_DRAFT`, `CHANGES_REQUESTED`, or `ACTIVE` (from any other state the assignment is rejected with `ERR_INVALID_STATE_TRANSITION`); the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`); and the sponsor's current load — the count of groups assigned to that sponsor in any of `CHARTER_DRAFT`, `SUBMITTED`, `SPONSOR_ENDORSED`, `CHANGES_REQUESTED`, `ACTIVE`, or `SUSPENDED` status — must be strictly below the sponsor's `max_groups` (`ERR_SPONSOR_CAPACITY_EXCEEDED`). Assignment writes `sponsor_id`, superseding any prior assignment, leaves the group's status unchanged, and increments the group's `version` by 1.

Submitting the charter is the charter owner's act: the caller's `X-User-ID` must equal the group's `created_by_employee_id` (`ERR_NOT_GROUP_LEADER` otherwise). Submission requires three conditions — the group has an assigned sponsor (`ERR_CHARTER_NO_SPONSOR` if `sponsor_id` is still null), the group has at least 10 active members (`ERR_CHARTER_INSUFFICIENT_FOUNDING_MEMBERS` when `active_member_count` is below 10), and the group is in `CHARTER_DRAFT` or `CHANGES_REQUESTED` — and moves the group to `SUBMITTED`, incrementing `version` by 1.

The assigned sponsor then decides. The sponsor's `X-User-ID` must match the group's `sponsor_id` (`ERR_SPONSOR_NOT_ASSIGNED`) and the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`). A `decision` of `ENDORSE` moves the group `SUBMITTED` → `SPONSOR_ENDORSED`; a `decision` of `REQUEST_CHANGES`, optionally annotated with a `change_note`, moves it `SUBMITTED` → `CHANGES_REQUESTED`. Either decision increments `version` by 1. The revision loop `SUBMITTED` → `CHANGES_REQUESTED` → `SUBMITTED` may repeat without bound while the owner refines the charter.

Final authority rests with the DEI office. On an endorsed charter, a `DeiAdmin` `decision` of `APPROVE` moves the group `SPONSOR_ENDORSED` → `ACTIVE` and snapshots `founding_member_count` to the group's `active_member_count` at that moment; a `decision` of `REJECT` moves it `SPONSOR_ENDORSED` → `CHARTER_REJECTED`, a terminal state. Both decisions increment `version` by 1.

### 3.3. Membership

An `Employee` joins a group by creating a membership carrying the target `group_id`; the server records the caller's `X-User-ID` as the membership's `employee_id`. A `DeiAdmin` may instead enroll any employee by supplying `employee_id` explicitly (when `employee_id` is omitted, the caller's own `X-User-ID` is recorded). The group must be in one of `CHARTER_DRAFT`, `SUBMITTED`, `SPONSOR_ENDORSED`, `CHANGES_REQUESTED`, or `ACTIVE` — a group in any other status rejects joins with `ERR_GROUP_NOT_ACCEPTING_MEMBERS`. Joining is an upsert keyed on the (group, employee) pair: if an `INACTIVE` row already exists for the pair it is reactivated in place (status back to `ACTIVE`, `joined_at` set to the current logical time, `left_at` cleared to null); otherwise a new row is created in `ACTIVE` status with `joined_at` set and `left_at` null. Either way the group's `active_member_count` — the count of that group's memberships in `ACTIVE` status — rises by 1, and both the fresh join and the in-place reactivation return HTTP 201 with the membership. If an `ACTIVE` row already exists for the pair, the join is rejected with `ERR_ALREADY_MEMBER`.

Leaving moves a membership `ACTIVE` → `INACTIVE`, stamps `left_at` with the current logical time, and drops `active_member_count` by 1. An `Employee` may leave their own row; a `GroupLeader` may remove any row of a group they currently lead; a `DeiAdmin` may remove any row. Leaving a row that is not `ACTIVE` is rejected with `ERR_INVALID_STATE_TRANSITION`.

### 3.4. The Fiscal Year: Allocation, Funding Negotiation, Disbursement, Reconciliation

Once groups are active, the DEI office locks the year's allocation. Locking requires the program to be in `OPEN` (`ERR_INVALID_STATE_TRANSITION` otherwise) and moves it to `ALLOCATION_LOCKED`, incrementing the program's `version` by 1. The lock runs the allocation waterfall over every group of the program whose status is `ACTIVE` at lock time:

- Each eligible group's weight is its `active_member_count` multiplied by its category weight in tenths — 10 for `AFFINITY`, 12 for `PROFESSIONAL`, 15 for `COMMUNITY_OUTREACH`.
- Each group's raw share is `pool_total_cents` multiplied by its weight and divided by the sum of weights over all eligible groups.
- Each group's `allocated_cents` is its raw share rounded down to a whole cent.
- The remainder — `pool_total_cents` minus the sum of the floored allocations — is distributed one cent at a time to groups in order of descending fractional part of their raw share, breaking ties by earlier `created_at` and then by `name` ascending.
- When no eligible groups exist, the entire pool remains unallocated; likewise, if the eligible groups' weights sum to zero (no eligible group has any active members), every eligible group allocates zero cents and the pool remains entirely unallocated.

The lock also freezes each eligible group's `certified_standing_score` to the standing score computed from the aggregates as of the lock (see §3.8), and sets the program's `unallocated_pool_cents` to `pool_total_cents` minus the sum of allocated amounts. Membership growth or event completions after the lock change the live `provisional_standing_score` but never the frozen `certified_standing_score`.

With allocation locked, groups spend through funding requests. A `GroupLeader` submits a request with the `group_id`, a `category` of `EVENT`, `TRAINING`, `COMMUNITY_OUTREACH`, `RECRUITING`, or `OTHER`, a free-text `purpose`, a `requested_cents` amount (strictly positive), and optionally an `external_matching_cents` amount (zero or more, defaulting to 0) representing externally raised funds eligible for a matching top-up. Submission requires the group to be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), the program to be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`), and the caller to be the leader of the group's `ACTIVE` leadership term — a group with no active leader rejects with `ERR_LEADERSHIP_GAP`, and a caller who is not that leader rejects with `ERR_NOT_GROUP_LEADER`. The request starts in `SUBMITTED` with `created_by_employee_id` set to the caller's `X-User-ID`, and `counter_amount_cents`, `approved_cents`, `disbursed_cents`, and `actual_spend_cents` all null.

The assigned sponsor reviews the request. As with charters, the sponsor's `X-User-ID` must match the group's `sponsor_id` (`ERR_SPONSOR_NOT_ASSIGNED`) and the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`). Segregation of duties applies: a sponsor whose own `employee_id` equals the request's `created_by_employee_id` may not endorse or counter it and is refused with `ERR_SPONSOR_SELF_ENDORSEMENT` (HTTP 403). A `decision` of `ENDORSE` moves the request `SUBMITTED` → `ENDORSED`. A `decision` of `COUNTER` requires a `counter_amount_cents` greater than zero (its absence or a non-positive value is `ERR_INVALID_REQUEST`), records that amount on the request, and moves it `SUBMITTED` → `COUNTERED`. An `ENDORSE` decision accepts and ignores any supplied `counter_amount_cents`.

A countered request returns to the leader, who revises it by supplying a new `requested_cents` (strictly positive). The caller must be the request's original submitter (`ERR_NOT_GROUP_LEADER`). Revision moves the request `COUNTERED` → `SUBMITTED` and replaces `requested_cents` with the new amount (the previously recorded `counter_amount_cents` is retained); this negotiation cycle between `COUNTERED` and `SUBMITTED` is unbounded.

Approval belongs to the DEI office and requires the request to be `ENDORSED` (an approval attempt on a request in any other status is `ERR_INVALID_STATE_TRANSITION`); it is only possible once the program's allocation is locked — an approval attempt on an `ENDORSED` request while the program is not in `ALLOCATION_LOCKED` is rejected with `ERR_ALLOCATION_NOT_LOCKED`. On approval the system computes the award using the matching top-up, in a pinned evaluation order because the tier depends on a provisional total that itself includes a scouting match:

1. A provisional total is formed as `requested_cents` plus 10% of `external_matching_cents`.
2. If that provisional total is at most 1,000,000 cents, the match rate is 20%; otherwise it is 5%.
3. The match amount is the match rate multiplied by `external_matching_cents`, rounded half-up to whole cents.
4. `approved_cents` is `requested_cents` plus the match amount.

The award must not exceed the group's `available_cents` — equality is allowed, and a shortfall is rejected with `ERR_INSUFFICIENT_GROUP_BUDGET` (HTTP 402). On success the request moves `ENDORSED` → `APPROVED`, `approved_cents` is written, and the group reserves the money: `reserved_cents` rises by `approved_cents`, dropping `available_cents` correspondingly. A `DeiAdmin` may instead decline a request from either `SUBMITTED` or `ENDORSED` with a `decision` of `DECLINE`, moving it to the terminal `DECLINED` state with no ledger effect.

Disbursement by a `DeiAdmin` moves an `APPROVED` request to `DISBURSED`, sets `disbursed_cents` to `approved_cents`, and moves the money on the group ledger: `reserved_cents` falls by `approved_cents` and `spent_cents` rises by `approved_cents`.

Reconciliation closes the loop. The original submitter reports `actual_spend_cents`, which must be at least 0 and at most `disbursed_cents` (`ERR_INVALID_REQUEST` outside that range; a caller other than the submitter is `ERR_NOT_GROUP_LEADER`, and the caller-identity check is applied before the `disbursed_cents` upper bound). The refund is `disbursed_cents` minus `actual_spend_cents`; the group's `spent_cents` and `allocated_cents` each fall by the refund, and the program's `unallocated_pool_cents` rises by the refund. The request moves to the terminal `RECONCILED` state.

### 3.5. Group Status Management and Its Cascades

A `DeiAdmin` may suspend, reinstate, or dissolve a group by setting `to_status` (with an optional `reason`) to one of `SUSPENDED`, `ACTIVE`, or `DISSOLVED`. Suspension moves `ACTIVE` → `SUSPENDED`; reinstatement moves `SUSPENDED` → `ACTIVE`; dissolution moves either `ACTIVE` or `SUSPENDED` → `DISSOLVED`, which is terminal; any other (from, to) pair is rejected with `ERR_INVALID_STATE_TRANSITION`. Each of these transitions increments the group's `version` by 1.

Suspension cascades. Every event of the group in `PLANNED` or `PUBLISHED` status is cancelled, and each such cancellation fires the event's own cancellation side effects in turn: the event's RSVPs in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` flip to `CANCELLED` with no waitlist promotion, and an event whose `funding_status` was `RESERVED` flips to `RELEASED`.

Dissolution runs the same event cascade and then goes further: every membership of the group in `ACTIVE` status flips to `INACTIVE` with `left_at` stamped; every funding request of the group in `SUBMITTED`, `COUNTERED`, or `ENDORSED` status moves to `WITHDRAWN`; and every request in `APPROVED` status also moves to `WITHDRAWN`, releasing its reserve by subtracting its `approved_cents` from the group's `reserved_cents`.

### 3.6. Leadership Terms, Succession, and the Gap Cascade

An `ACTIVE` group gets its leaders through leadership terms created by a `DeiAdmin`. Creation carries the `group_id`, the leader's opaque `leader_employee_id`, an `ends_at` expiry that must be strictly after the current logical time (`ERR_INVALID_REQUEST` otherwise), and — once any prior term exists for the group — a `predecessor_term_id` chaining the succession. The chain rule is strict: `predecessor_term_id` must identify the prior term with the latest `ends_at`, breaking ties by the latest `created_at` and then by the later creation order; a mismatched, missing, or unexpectedly supplied predecessor (including supplying one for the group's very first term) is rejected with `ERR_PREDECESSOR_MISMATCH`. Three further gates apply: the group must be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`); no other term of the group may be `ACTIVE` (`ERR_ACTIVE_TERM_EXISTS`); and the prospective leader must hold an `ACTIVE` membership in the group whose `joined_at` is at least 90 days in the past relative to the current logical time (`ERR_TERM_TENURE_NOT_MET`). An employee may hold at most 2 terms in the same group across all statuses — a third appointment is rejected with `ERR_TERM_LIMIT_EXCEEDED`. A new term starts `ACTIVE` with `starts_at` stamped to the current logical time, and the group's `has_active_leader` flag recomputes to true.

A term ends in two ways. The leader may resign (a `GroupLeader` caller whose `X-User-ID` equals the term's `leader_employee_id`, or a `DeiAdmin`), moving the term `ACTIVE` → `RESIGNED`; resigning a term that is not `ACTIVE` is `ERR_INVALID_STATE_TRANSITION`. Or the logical-clock sweep expires it: any term still `ACTIVE` whose `ends_at` is at or before the new clock value flips to `EXPIRED`. Both endings fire the same gap cascade when they leave the group with no remaining `ACTIVE` term: `has_active_leader` flips to false and every funding request of the group in `SUBMITTED` or `COUNTERED` status moves to `WITHDRAWN`. This cascade is the serialization point that strands in-flight negotiations when leadership lapses, and it explains why a group without an active leader cannot submit new funding requests (`ERR_LEADERSHIP_GAP`).

### 3.7. Venues, Events, and RSVPs

The DEI office registers venues with a `name` (not required to be unique — duplicate venue names are accepted) and a strictly positive `capacity`.

An `ACTIVE` group plans events through its current `ACTIVE`-term leader or a `DeiAdmin` (any other caller is `ERR_NOT_GROUP_LEADER`; a non-active group is `ERR_GROUP_NOT_ACTIVE`). The plan carries the `group_id`, a `venue_id`, a `title`, a `category` of `WORKSHOP`, `SOCIAL`, `RECRUITING`, or `COMMUNITY`, a `starts_at` that must be strictly after the current logical time and an `ends_at` strictly after `starts_at` (violations are `ERR_INVALID_REQUEST`), and a `capacity` that must be strictly positive and no greater than the venue's `capacity` (`ERR_VENUE_CAPACITY_EXCEEDED`). Optionally the plan links a `funding_request_id`; when supplied, that request must belong to the same group (`ERR_FUNDING_REQUEST_WRONG_GROUP`) and must be in `APPROVED` status (`ERR_FUNDING_REQUEST_NOT_APPROVED`). Venue exclusivity uses half-open interval semantics: the venue must have no other event in `PLANNED` or `PUBLISHED` status whose time range overlaps the new event's, where two events conflict exactly when the new event starts before the existing one ends and the existing one starts before the new one ends; touching endpoints — one event ending exactly when the other starts — do not conflict. An overlap is rejected with `ERR_VENUE_DOUBLE_BOOKED`. A new event starts in `PLANNED` status with `funding_status` `RESERVED` when an approved funding request was linked, otherwise `UNFUNDED`, and with `registered_count` and `checked_in_count` both zero.

Publishing moves an event `PLANNED` → `PUBLISHED` and re-checks that the group is still `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), incrementing the event's `version` by 1.

Rescheduling works from both `PLANNED` and `PUBLISHED` and leaves the event in the same status. The request carries new `starts_at` and `ends_at` values (still strictly after now and strictly ordered), optionally a new `venue_id`, and the OCC field `expected_event_version` (see §2.7) — a stale version is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). The venue overlap check is re-evaluated excluding the event itself (`ERR_VENUE_DOUBLE_BOOKED`), a venue change re-applies the capacity ceiling (`ERR_VENUE_CAPACITY_EXCEEDED`), and a successful reschedule supersedes the prior schedule and increments `version` by 1.

Cancellation — by the leader, a `DeiAdmin`, or the system cascade from suspension or dissolution — moves an event from `PLANNED` or `PUBLISHED` to the terminal `CANCELLED` state. Every RSVP of the event in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` flips to `CANCELLED` with no waitlist promotion, and a `RESERVED` `funding_status` flips to `RELEASED` (`UNFUNDED` is unchanged).

Employees RSVP to a `PUBLISHED` event (any other status is `ERR_EVENT_NOT_PUBLISHED`) with a payload naming the `event_id`; the server records the caller's `X-User-ID` as the RSVP's `employee_id`. One live RSVP per (event, employee) pair is allowed: an existing RSVP in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` blocks a new one with `ERR_ALREADY_RSVPED`. When the event's `registered_count` is strictly below its `capacity` the new RSVP lands `REGISTERED` and `registered_count` rises by 1; when `registered_count` has reached `capacity` — the boundary is inclusive, a full event waitlists — the RSVP lands `WAITLISTED` and receives a `waitlist_position` equal to 1 plus the highest existing `waitlist_position` on the event (or 1 when none exists). `waitlist_position` is null for `REGISTERED` rows and is retained for audit even after promotion.

Cancelling an RSVP is available to the owning employee, the leader of the event's group, or a `DeiAdmin`. Manual cancellation is valid only from `REGISTERED` or `WAITLISTED` (`ERR_INVALID_STATE_TRANSITION` otherwise), though the system cascade may also cancel `CHECKED_IN` rows. Cancelling a `REGISTERED` row manually decrements `registered_count` by 1 and immediately promotes the waitlist: the `WAITLISTED` RSVP with the lowest `waitlist_position` flips to `REGISTERED` and `registered_count` rises back by 1, leaving the count unchanged overall; if no one is waiting, the seat simply stays free. Cancelling a `WAITLISTED` row changes no seat accounting.

Check-in is performed by the leader of the event's group or a `DeiAdmin`, moving a `REGISTERED` RSVP to `CHECKED_IN`. The event must still be `PUBLISHED` (any other event status is `ERR_INVALID_STATE_TRANSITION`) and the current logical time must be at or after the event's `starts_at` (early check-in is `ERR_CHECKIN_TOO_EARLY`); checking in a non-`REGISTERED` RSVP is `ERR_INVALID_STATE_TRANSITION`. Check-in increments `checked_in_count` by 1 while `registered_count` is unchanged — a checked-in attendee still holds the seat.

Once the current logical time reaches the event's `ends_at` (completing earlier is `ERR_EVENT_NOT_ENDED`), the leader or a `DeiAdmin` completes the event, moving `PUBLISHED` → `COMPLETED`. Completion freezes the participation metrics: `capacity_utilization_pct` is the percentage of checked-in attendees against the event's `capacity`, and `member_engagement_pct` is the percentage of checked-in attendees against the group's `active_member_count` at completion time (taken as 0 when the group has no active members at completion), both rounded half-up to 2 decimal places. `impact_points` are computed as described in §3.8, `low_attendance_flag` is set true when `capacity_utilization_pct` is below 25.00, and a `RESERVED` `funding_status` flips to `SPENT`. Both percentages — and likewise `impact_points` and `low_attendance_flag` — remain null until completion.

### 3.8. Standing Scores, Impact Points, and Program Goals

A group's standing score blends engagement with growth. The engagement half is the mean of `member_engagement_pct` over the group's `COMPLETED` events, counting as 0 when the group has none. The growth half is capped: `member_growth_pct` is the percentage by which `active_member_count` exceeds the `founding_member_count` snapshot relative to that snapshot, and the capped contribution is the lesser of 100 and that percentage. The standing score is the sum of half the engagement mean and half the capped growth percentage, rounded half-up to 2 decimal places. Every group read recomputes this live as `provisional_standing_score` from the current aggregates — null while `founding_member_count` is still null, i.e., before the group has been activated; the allocation lock freezes the same computation into `certified_standing_score`, which later activity cannot move.

Event impact points reward well-attended, sponsor-visible events. The base points depend on category — 20 for `WORKSHOP`, 10 for `SOCIAL`, 80 for `RECRUITING`, 40 for `COMMUNITY` — and are scaled by a utilization tier: half when `capacity_utilization_pct` is below 25, full when it is at least 25 and below 75, and one-and-a-half when it is at least 75. A sponsor bonus of 10 points is added when any RSVP of the event is `CHECKED_IN` with an `employee_id` matching the assigned sponsor's `employee_id`. The total is capped at 100, and the result is an integer.

The program's impact report evaluates each declared goal against live data: `TOTAL_ACTIVE_MEMBERS` sums `active_member_count` over the program's groups in `ACTIVE` or `SUSPENDED` status; `EVENTS_COMPLETED` counts the program's groups' events in `COMPLETED` status; `AVG_CAPACITY_UTILIZATION` averages `capacity_utilization_pct` over those completed events, rounded half-up to 2 decimal places and counting as 0 when there are none; `LATEST_CLIMATE_INDEX` takes the `final_index` of the program's `CLOSED` survey with the latest `closes_at` (ties break to the survey created later), or null when none exists; `MENTORING_COMPLETED_COUNT` counts the program's engagements in `COMPLETED` status. A goal attains `ACHIEVED` when the actual value is at least its `target_value` (equality achieves) and `MISSED` otherwise; a null actual always misses. The report response carries the `program_id`, the program's current `posture` as `program_posture`, a `goal_results` array, and a `generated_at` timestamp read from the logical clock; each `goal_results` entry carries the goal's `metric`, its `target_value`, the computed `actual_value` (null when the metric yields no value, as above), and the `attainment` verdict (`ACHIEVED` or `MISSED`).

### 3.9. Climate Surveys

A `DeiAdmin` creates a climate survey for a program with a `title`, an inclusive `opens_at`, an exclusive `closes_at` that must be strictly after `opens_at`, and a `min_responses` threshold of at least 1. The survey starts in `DRAFT` with `response_count` zero and both indices null.

Opening a survey requires the program to be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`) and that no other survey of the same program is already `OPEN` (`ERR_SURVEY_ALREADY_OPEN`); opening moves `DRAFT` → `OPEN`.

Employees respond while the survey is `OPEN` (`ERR_SURVEY_NOT_OPEN` otherwise) and while the current logical time is inside the window — at or after `opens_at` and strictly before `closes_at` (`ERR_SURVEY_WINDOW_CLOSED` outside). The payload carries the `survey_id` and four dimension scores — `belonging_score`, `growth_score`, `fairness_score`, and `safety_score` — each an integer from 1 to 5 inclusive. The server records the caller's `X-User-ID` as the response's `respondent_employee_id`. One response per respondent per survey: a repeat submission from the same `X-User-ID` is rejected with `ERR_DUPLICATE_RESPONSE`. Each response's `response_score` is the weighted blend — 30% belonging, 30% growth, 20% fairness, 20% safety — rounded half-up to 2 decimal places, and the survey's `response_count` rises by 1.

While a survey is `OPEN`, every read exposes `provisional_index`, the mean of `response_score` over the responses received so far, rounded half-up to 2 decimal places — null when there are no responses yet and null again after the survey closes.

Closing requires `response_count` to be at least `min_responses`, with equality allowed (`ERR_MIN_RESPONSES_NOT_MET` below the threshold). Closing moves the survey to the terminal `CLOSED` state, freezes `final_index` as the mean of `response_score` over all responses rounded half-up to 2 decimal places, and clears `provisional_index` to null. When the frozen `final_index` is strictly below 3.00, the program's `posture` automatically flips to `CLIMATE_REVIEW`, blocking new group chartering (§2.9) until a `DeiAdmin` clears the review.

### 3.10. Mentoring Engagements

An `Employee` proposes a mentoring engagement as their own mentee (the server records `X-User-ID` as `mentee_employee_id`), or a `DeiAdmin` proposes one for any employee by supplying `mentee_employee_id` (when it is omitted, the caller's own `X-User-ID` is recorded). The payload names the `program_id`, the mentoring `sponsor_id`, and a window from `starts_at` to `ends_at` with `ends_at` strictly after `starts_at`. The program must be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`) and the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`). The remaining gates then run in the §2.6 pipeline order — temporal before uniqueness before capacity. First, a buffered-window conflict check runs per sponsor over their `PROPOSED` and `ACTIVE` engagements: a new engagement conflicts when it starts before the existing engagement's `ends_at` plus 14 days and the existing engagement starts before the new one's `ends_at` plus 14 days — a start exactly 14 days after an existing engagement's end is allowed — and a conflict is rejected with `ERR_MENTORING_WINDOW_CONFLICT`. Next, self-pairing is forbidden: a sponsor whose `employee_id` equals the mentee's is rejected with `ERR_MENTORING_SELF_PAIRING` (HTTP 400), and the mentee must have no engagement in `PROPOSED` or `ACTIVE` status at all (`ERR_MENTEE_ALREADY_ENGAGED`). Last, the capacity gate: the sponsor's count of engagements in `PROPOSED` or `ACTIVE` status must be strictly below their `max_mentees` (`ERR_SPONSOR_CAPACITY_EXCEEDED`). A new engagement starts in `PROPOSED`.

The named sponsor decides: a `decision` of `ACCEPT` moves `PROPOSED` → `ACTIVE`, and a `decision` of `DECLINE` moves `PROPOSED` → `DECLINED`. The caller's `X-User-ID` must match the engagement's `sponsor_id` (`ERR_SPONSOR_NOT_ASSIGNED`), and acceptance additionally requires the sponsor to still be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`).

An `ACTIVE` engagement closes with an `outcome` of `COMPLETED` or `EARLY_TERMINATED`, recorded by the sponsoring sponsor or a `DeiAdmin`, landing in the corresponding terminal state.

## 4. Endpoint Definitions

All endpoints are mounted under `/v1`. Creating a new resource returns HTTP 201; all other successful operations, including state transitions, return HTTP 200. Errors carry the HTTP status given in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/programs | Create an inclusion program | DeiAdmin |
| GET | /v1/programs/{id} | Get program | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/programs/{id}/open | Open program for chartering | DeiAdmin |
| POST | /v1/programs/{id}/lock-allocation | Lock allocation: runs the allocation waterfall over ACTIVE groups | DeiAdmin |
| POST | /v1/programs/{id}/clear-climate-review | Clear CLIMATE_REVIEW posture | DeiAdmin |
| GET | /v1/programs/{id}/impact-report | Computed goal-attainment report | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/sponsors | Appoint an executive sponsor | DeiAdmin |
| GET | /v1/sponsors/{id} | Get sponsor | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/sponsors/{id}/set-status | Set sponsor status | DeiAdmin |
| POST | /v1/groups | Create ERG charter draft | GroupLeader, DeiAdmin |
| GET | /v1/groups/{id} | Get group (including computed budget and standing fields) | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/groups | List groups with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/groups/{id}/assign-sponsor | Assign or supersede executive sponsor (OCC on group version) | DeiAdmin |
| POST | /v1/groups/{id}/submit-charter | Submit (or resubmit) charter for review | GroupLeader |
| POST | /v1/groups/{id}/sponsor-decision | Sponsor endorses charter or requests changes | ExecutiveSponsor |
| POST | /v1/groups/{id}/dei-decision | DEI office approves or rejects an endorsed charter | DeiAdmin |
| POST | /v1/groups/{id}/set-status | Suspend, reinstate, or dissolve a group | DeiAdmin |
| POST | /v1/memberships | Join a group (upsert: reactivates an INACTIVE row for the pair) | Employee, DeiAdmin |
| GET | /v1/memberships/{id} | Get membership | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/memberships | List memberships with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/memberships/{id}/leave | Leave or remove a member | Employee, GroupLeader, DeiAdmin |
| POST | /v1/leadership-terms | Appoint a group leader (succession chain) | DeiAdmin |
| GET | /v1/leadership-terms/{id} | Get leadership term | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/leadership-terms | List leadership terms with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/leadership-terms/{id}/resign | Leader resigns (or admin removes) | GroupLeader, DeiAdmin |
| POST | /v1/funding-requests | Submit a funding request | GroupLeader |
| GET | /v1/funding-requests/{id} | Get funding request | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/funding-requests | List funding requests with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/funding-requests/{id}/sponsor-decision | Sponsor endorses or counters | ExecutiveSponsor |
| POST | /v1/funding-requests/{id}/revise | Leader revises a countered request (negotiation cycle) | GroupLeader |
| POST | /v1/funding-requests/{id}/dei-decision | DEI office approves (computes matching top-up, reserves budget) or declines | DeiAdmin |
| POST | /v1/funding-requests/{id}/disburse | Disburse an approved request | DeiAdmin |
| POST | /v1/funding-requests/{id}/reconcile | Report actual spend; refund remainder to program pool | GroupLeader |
| POST | /v1/venues | Register a venue | DeiAdmin |
| GET | /v1/venues/{id} | Get venue | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/events | Plan an event (venue overlap and funding linkage checks) | GroupLeader, DeiAdmin |
| GET | /v1/events/{id} | Get event (including computed participation fields) | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/events | List events with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/events/{id}/publish | Publish event (re-checks group ACTIVE) | GroupLeader, DeiAdmin |
| POST | /v1/events/{id}/reschedule | Reschedule or move venue (OCC on event version) | GroupLeader, DeiAdmin |
| POST | /v1/events/{id}/cancel | Cancel event; cascades RSVPs, releases funding hold | GroupLeader, DeiAdmin |
| POST | /v1/events/{id}/complete | Complete event after ends_at; freezes participation metrics and impact points | GroupLeader, DeiAdmin |
| POST | /v1/rsvps | RSVP to a published event (REGISTERED if seat free else WAITLISTED) | Employee |
| GET | /v1/rsvps/{id} | Get RSVP | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/rsvps | List RSVPs with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/rsvps/{id}/cancel | Cancel RSVP; frees seat and promotes waitlist head (manual cancel only) | Employee, GroupLeader, DeiAdmin |
| POST | /v1/rsvps/{id}/check-in | Check in an attendee at or after event start | GroupLeader, DeiAdmin |
| POST | /v1/climate-surveys | Create a climate survey | DeiAdmin |
| GET | /v1/climate-surveys/{id} | Get survey (including provisional and final index) | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/climate-surveys | List surveys with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/climate-surveys/{id}/open | Open survey for responses (one OPEN per program) | DeiAdmin |
| POST | /v1/climate-surveys/{id}/close | Close survey; computes final index and posture cascade | DeiAdmin |
| POST | /v1/survey-responses | Submit a survey response (one per respondent per survey) | Employee |
| GET | /v1/survey-responses/{id} | Get survey response | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/survey-responses | List survey responses with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/mentoring-engagements | Propose a mentoring engagement (buffered-window and capacity checks) | Employee, DeiAdmin |
| GET | /v1/mentoring-engagements/{id} | Get mentoring engagement | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| GET | /v1/mentoring-engagements | List mentoring engagements with filters + pagination | DeiAdmin, ExecutiveSponsor, GroupLeader, Employee |
| POST | /v1/mentoring-engagements/{id}/sponsor-decision | Sponsor accepts or declines a proposed engagement | ExecutiveSponsor |
| POST | /v1/mentoring-engagements/{id}/complete | Complete or early-terminate an engagement | ExecutiveSponsor, DeiAdmin |
| POST | /v1/_clock/set_current_utc | Set the logical clock and run the term-expiry sweep | DeiAdmin |

List endpoints accept optional filter query parameters that exact-match the named fields: groups by `program_id`, `sponsor_id`, `status`; memberships by `group_id`, `employee_id`, `status`; leadership terms by `group_id`, `employee_id` (matching `leader_employee_id`), `predecessor_term_id`, `status`; funding requests by `group_id`, `status`; events by `group_id`, `venue_id`, `funding_request_id`, `status`; RSVPs by `event_id`, `employee_id`, `status`; climate surveys by `program_id`, `status`; survey responses by `survey_id`, `employee_id` (matching `respondent_employee_id`); mentoring engagements by `program_id`, `sponsor_id`, `mentee_employee_id`, `status`. All list endpoints accept `limit` and `offset` per §2.3.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_GROUP_VERSION | 412 |
| ERR_STALE_EVENT_VERSION | 412 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_PROGRAM_NOT_OPEN | 409 |
| ERR_PROGRAM_IN_CLIMATE_REVIEW | 409 |
| ERR_ALLOCATION_NOT_LOCKED | 409 |
| ERR_GROUP_NOT_ACTIVE | 409 |
| ERR_GROUP_NOT_ACCEPTING_MEMBERS | 409 |
| ERR_EVENT_NOT_PUBLISHED | 409 |
| ERR_SURVEY_NOT_OPEN | 409 |
| ERR_SURVEY_ALREADY_OPEN | 409 |
| ERR_SPONSOR_NOT_ACTIVE | 409 |
| ERR_LEADERSHIP_GAP | 409 |
| ERR_CHARTER_NO_SPONSOR | 409 |
| ERR_SPONSOR_NOT_ASSIGNED | 409 |
| ERR_FUNDING_REQUEST_WRONG_GROUP | 409 |
| ERR_FUNDING_REQUEST_NOT_APPROVED | 409 |
| ERR_PREDECESSOR_MISMATCH | 409 |
| ERR_VENUE_DOUBLE_BOOKED | 409 |
| ERR_MENTORING_WINDOW_CONFLICT | 409 |
| ERR_SURVEY_WINDOW_CLOSED | 409 |
| ERR_CHECKIN_TOO_EARLY | 409 |
| ERR_EVENT_NOT_ENDED | 409 |
| ERR_ACTIVE_TERM_EXISTS | 409 |
| ERR_GROUP_NAME_NOT_UNIQUE | 409 |
| ERR_ALREADY_MEMBER | 409 |
| ERR_ALREADY_RSVPED | 409 |
| ERR_DUPLICATE_RESPONSE | 409 |
| ERR_TERM_LIMIT_EXCEEDED | 409 |
| ERR_TERM_TENURE_NOT_MET | 409 |
| ERR_CHARTER_INSUFFICIENT_FOUNDING_MEMBERS | 409 |
| ERR_MIN_RESPONSES_NOT_MET | 409 |
| ERR_MENTEE_ALREADY_ENGAGED | 409 |
| ERR_MENTORING_SELF_PAIRING | 400 |
| ERR_SPONSOR_SELF_ENDORSEMENT | 403 |
| ERR_INSUFFICIENT_GROUP_BUDGET | 402 |
| ERR_SPONSOR_CAPACITY_EXCEEDED | 409 |
| ERR_VENUE_CAPACITY_EXCEEDED | 409 |
| ERR_NOT_GROUP_LEADER | 403 |

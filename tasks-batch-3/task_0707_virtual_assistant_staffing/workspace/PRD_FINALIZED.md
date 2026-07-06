# Va-Staffing API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a Virtual Assistant & Outsourced-Admin Staffing platform. The platform connects client organizations that need ongoing administrative help with a pool of virtual assistants (VAs), and it carries each relationship through its full commercial arc: client intake and scoping, VA matching and onboarding, a contracted hour-bank (retainer) that meters consumption cycle by cycle with rollover, a task queue governed by service-level agreements (SLAs), time tracking with client approval, escalation and VA replacement, specialized-skill add-ons, and finally billing and utilization reporting.

Three constituencies share the system. The **StaffingManager** is the platform operator who configures skills and SLA tiers, registers VAs, proposes and onboards engagements, closes retainer cycles, runs escalations and replacements, and issues invoices. The **Client** is the customer organization: it scopes its own contract, accepts or rejects proposed VAs, requests add-ons, creates and cancels tasks, and approves or rejects the hours its VA logs. The **VA** is the matched assistant who works tasks and records time against them. The hard parts of this domain are not the individual screens but the couplings between them — a single retainer cycle is a finite hour-bank that many time entries compete for, a replacement ripples through three entities at once, and the bill that a client ultimately pays depends on whether it is drawn mid-cycle or after the cycle is sealed.

Because much of the behavior is time-driven (SLA due dates, breach detection, cycle boundaries), the service runs on a **logical clock** rather than wall-clock time. Tests advance this clock explicitly; the system reads SLA standing and stamps lifecycle timestamps from it. Every monetary and hour figure in the platform is derived deterministically from the entities described below, so the same inputs always reproduce the same invoice.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. The role value must be exactly one of `StaffingManager`, `Client`, or `VA`. If `X-User-Role` is missing or is not one of these three recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation — or is an ownership-bound role acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two of the three roles are bound to a persisted entity, which is how `X-User-ID` ties to resource ownership. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare that resource's `client_id` to `X-User-ID` (and for a resource reached through an engagement, task, cycle, entry, escalation, add-on, or invoice, the owning client is resolved transitively). When `X-User-Role` is `VA`, `X-User-ID` is the `id` of the acting `VirtualAssistant`; ownership checks on a task or time entry compare the VA of that resource's engagement to `X-User-ID`. By contrast, when `X-User-Role` is `StaffingManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. A `Client` may only read and act within its own client tree, and a `VA` may only work and log time on tasks of engagements it currently holds; violations surface as `ERR_FORBIDDEN`.

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

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may not be negative. A request whose `limit` falls outside the range 1 through 100 inclusive, or whose `offset` is negative, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422). Within any list, results are ordered by `created_at` ascending (oldest first). Each list response reports `limit`, `offset`, `total_count` (the count of all matching records before the page window is applied), and `has_more` (true when records remain beyond the current window) in the `meta` block.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix; the `id` is an identity handle only and is never an input to any business decision (matching, ranking, and tie-breaks never consult it). Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, set when the resource is first persisted.

Most entities additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increments by 1 on each mutation. These full-lifecycle entities are `Client`, `VirtualAssistant`, `Engagement`, `RetainerCycle`, `Task`, `TimeEntry`, `AddOn`, `Escalation`, and `Invoice`. Three entities are immutable reference records and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: `SkillTag`, `SlaPolicy`, and the singleton `Clock`. Implementers must not emit `updated_at` or `version` for those three.

### 2.5. The Logical Clock

The platform keeps a single logical clock whose value, `current_utc`, drives every time-sensitive rule: SLA due dates, breach detection, and the timestamps stamped on lifecycle transitions. At startup the clock reads exactly `2026-03-01T00:00:00Z`; before any clock-setting call it returns precisely this default and never falls back to the host's wall-clock time. A StaffingManager may advance the clock to a supplied instant; doing so does not retroactively rewrite stamped timestamps, but every subsequent read of a task re-evaluates that task's SLA standing against the new clock value. The `Clock` resource exposes `id`, `created_at`, and `current_utc`.

The logical clock's value and every value derived from it are rendered at **second precision** — an ISO 8601 UTC string with no fractional digits, of the canonical form `2026-03-01T00:00:00Z` shown above. This applies to `current_utc` (any sub-second component of a supplied clock instant is dropped when the clock value is read back), to the SLA due dates `response_due_iso` and `resolution_due_iso`, and to every clock-derived lifecycle stamp — `assigned_at_iso`, `first_action_at_iso`, `completed_at_iso`, `approved_at_iso`, `opened_at_iso`, and `closed_at_iso`. This second-precision form is distinct from the three-fractional-digit audit timestamps `created_at`, `updated_at`, and `api_request_timestamp` of §2.2 and §2.4, which keep their three fractional digits.

### 2.6. Nested Reference Resolution and Path Validation

Resources live as peer collections; relationships are expressed by foreign-key fields carried in request bodies, not by URL nesting. For any endpoint that addresses a resource by an id in its path, that id is validated first: an unresolved path id (a `client_id`, `va_id`, `engagement_id`, `cycle_id`, `task_id`, `entry_id`, `escalation_id`, `addon_id`, `invoice_id`, `skill_tag_id`, or `sla_policy_id` that names no existing record) yields `ERR_NOT_FOUND` (HTTP 404). Distinct from path ids, foreign keys supplied in a request body — `client_id`, `va_id`, `required_skill_tag_id`, `skill_tag_id`, `cycle_id`, `task_id`, and each element of `required_skill_tag_ids` — are validated against existing records and, if any references a non-existent entity, the request is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422).

### 2.7. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order, and the **first** failing check determines the error returned. The ordering is: (1) authentication of `X-User-Role` — `ERR_UNAUTHENTICATED`; (2) authorization, including ownership for entity-backed roles — `ERR_FORBIDDEN`; (3) existence of every path id — `ERR_NOT_FOUND`; (4) existence of every body foreign key — `ERR_REFERENCED_ENTITY_NOT_FOUND`; (5) well-formedness of the body, meaning required fields are present and numeric fields lie within their declared ranges (`raw_minutes` at least 1, hours at least 0, rates at least 0) — `ERR_INVALID_REQUEST`; (6) the dedicated range guards (`breach_penalty_pct` between 0 and 1 inclusive, `rollover_cap_hours` not negative, `weekly_capacity_hours` at least 1.0, `rating` between 0 and 5 inclusive) — `ERR_VALIDATION_RANGE`; (7) pagination bounds on list endpoints — `ERR_PAGINATION_INVALID`; (8) that the target resource is in a state from which the requested transition is defined — `ERR_INVALID_STATE`; and then the operation-specific business gates of priorities 9 through 22, described where each workflow is narrated. The practical consequence is that authentication and authorization always precede a "not found", a missing or malformed body is reported before any state check, and a state-machine violation (priority 8) is reported before the deeper business gates that assume the transition is at least structurally legal.

### 2.8. Monetary and Hour Precision

Money is always represented in **integer cents**. Where a charge is computed from hours times a per-hour cents rate, the product is rounded **half-up** to a whole cent. When a total is assembled from several tier charges (a within-bank charge, an overage charge, a surcharge), each tier is rounded to whole cents **before** the tiers are summed — rounding per tier and then summing is mandatory and is not interchangeable with summing first and rounding once. Hour quantities exposed on cycles are carried to two decimal places, rounded half-up, after each contributing time entry has itself been rounded onto the quarter-hour grid (see §3.4). Utilization is carried to four decimal places, rounded half-up, as a fraction. The VA match score is likewise carried to four decimal places, rounded half-up.

### 2.9. Optimistic Concurrency on Cycle Close

The retainer cycle is the one place where two legitimate operations contend for the same record, so closing a cycle is guarded by optimistic concurrency control. The request that closes an open cycle must include `expected_cycle_version`, carrying the `version` of the target `RetainerCycle` as the operator last observed it. Approving a time entry against that cycle legitimately advances the cycle's `version` (it recomputes the bank balance), so a close request still presenting the pre-approval value is operating on a stale view of the bank. When `expected_cycle_version` does not equal the cycle's current `version`, the close is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), forcing the operator to re-read the true `consumed_hours` before sealing the cycle for invoicing. The cycle-close operation is the only write in the platform that takes a version field; no other endpoint accepts or requires one.

### 2.10. State-Driven Consistency and Cascades

Mutations are atomic: a single request either applies all of its effects — including effects that fan out to other entities — or none of them, and every entity it touches has its `updated_at` refreshed and its `version` incremented. The platform leans heavily on cascades: closing a client cancels its open tasks and rejects their pending hours; replacing a VA mints one engagement, ends another, and re-homes a set of tasks; closing a cycle mints its successor. Each of these multi-entity effects is specified in §3 at the workflow that triggers it. Computed back-pointers and counters — `active_engagement_id` and `open_task_count` on a client, `active_engagement_count` on a VA, `superseded_by_engagement_id` on an engagement, `replacement_engagement_id` on an escalation — are maintained by the system as side effects of these transitions and are never set directly by a caller.

## 3. Business Logic & Workflows

### 3.1. Configuring Skills and SLA Tiers

Before any client can be served, the StaffingManager seeds two kinds of configuration. A **skill tag** records a stable `code` (uppercase snake form, unique across all skill tags, e.g. `BOOKKEEPING` or `CRM_ADMIN`), a human-readable `name`, and a flag `is_specialized` that defaults to false. A skill tag whose `is_specialized` is true is a gated competency: a task requiring it cannot be assigned unless the serving engagement holds an active add-on for that skill (see §3.6). Attempting to register a second skill tag with a `code` that already exists is rejected with `ERR_DUPLICATE`.

An **SLA policy** binds a priority `tier` — one of `STANDARD`, `PRIORITY`, or `URGENT`, unique across all policies — to two deadlines and a penalty. `response_minutes` is the number of minutes, counted from the moment a task becomes `ASSIGNED`, within which the VA must take a first action; it must be at least 1. `resolution_hours` is the number of hours, again from assignment, within which the task must reach `DONE`; it must be at least 1. `breach_penalty_pct` is the fraction of a breached task's billed charge that is credited back to the client, and it must lie between 0.0 and 1.0 inclusive; a value outside that band is rejected with `ERR_VALIDATION_RANGE`. A duplicate `tier` is rejected with `ERR_DUPLICATE`. Both skill tags and SLA policies are immutable once created and can be retrieved individually or listed (skill tags filterable by `is_specialized`, policies by `tier`).

### 3.2. Client Intake, Scoping, and the Suspension Cycle

A client enters the platform through intake, supplying a `company_name` and a `contact_email` (unique across all clients; a collision is `ERR_DUPLICATE`). At intake the client is born `PENDING`, with `open_task_count` initialized to 0, and no commercial terms yet. The client itself then **scopes** the contract, moving from `PENDING` to `SCOPED`. Scoping captures a free-text `scope_summary`, an optional `required_skill_tag_ids` array (each element must resolve to an existing skill tag, validated at scope time), the contracted hour-bank size `monthly_retainer_hours` (at least 1.0), the in-bank price `base_rate_cents` and the beyond-bank price `overage_rate_cents` (each a non-negative integer number of cents), and an optional `rollover_cap_hours` (not negative; defaulting to 0) capping how many unused hours may carry forward. Scoping requires `monthly_retainer_hours`, `base_rate_cents`, and `overage_rate_cents` to be present, and persists all of these fields onto the client.

A scoped client does not become `ACTIVE` on its own. The `SCOPED → ACTIVE` transition is driven by the system when an engagement for this client completes onboarding and activates (see §3.3); that activation is what opens the client's first retainer cycle. Once a client is `ACTIVE`, the StaffingManager may **suspend** it (`ACTIVE → SUSPENDED`). Suspension moves every `QUEUED` or `ASSIGNED` task of that client into `BLOCKED`, stamping each one's `blocked_reason` to the value `CLIENT_SUSPENDED`. **Resuming** a suspended client (`SUSPENDED → ACTIVE`) reverts exactly those tasks: a task blocked for the suspension reason that had previously been assigned returns to `ASSIGNED`, one that had never been assigned returns to `QUEUED`, and the `blocked_reason` is cleared in both cases. Tasks a VA blocked for some other reason are untouched by resume.

A client may be **closed** from `SCOPED`, `ACTIVE`, or `SUSPENDED`, but only when none of its tasks is currently `IN_PROGRESS`; an attempt while work is in flight is an invalid transition. Closing is a three-hop cascade. First, every non-terminal task of the client (anything not already `DONE` or `CANCELLED`) is moved to `CANCELLED`. Second — as a consequence of each of those task cancellations — every `LOGGED` time entry on those tasks is moved to `REJECTED`, so it never charges a cycle. Third, the client's currently `OPEN` retainer cycle, if any, is moved to `CLOSED` with its `closed_at_iso` stamped from the clock, and crucially **no successor cycle is minted** because the client is closing. Finally, any `ACTIVE` engagement of the client is ended: that VA's `active_engagement_count` is decremented and, if it reaches 0, the VA returns to `AVAILABLE`.

### 3.3. Matching a VA and Onboarding the Engagement

The VA pool is seeded by the StaffingManager, who registers each assistant with a `full_name`, an `email` (unique across all VAs; a collision is `ERR_DUPLICATE`), an optional `skill_tag_ids` array of held skills, a `weekly_capacity_hours` figure (at least 1.0), and an optional `rating` between 0 and 5 inclusive (defaulting to 3.0). A newly registered VA starts `AVAILABLE` with an `active_engagement_count` of 0. A `rating` outside the 0-to-5 band or a `weekly_capacity_hours` below 1.0 is rejected with `ERR_VALIDATION_RANGE`.

An **engagement** is the durable pairing of one client with one VA. The StaffingManager proposes an engagement by naming the `client_id`; the VA may be named explicitly via `va_id`, or, if `va_id` is omitted, the server auto-matches the best eligible VA and records the resulting `match_score`. A freshly proposed engagement is `PROPOSED`.

Auto-matching first builds an eligibility set: a VA is eligible only if its `status` is `AVAILABLE` or `ENGAGED` (a `BENCHED` VA is never eligible) **and** every skill id in the client's `required_skill_tag_ids` is present in that VA's `skill_tag_ids` (full coverage, no partial credit). Each eligible candidate is scored on three normalized components. Skill coverage is the count of the client's required skills the VA holds divided by the greater of 1 and the number of required skills — for any eligible VA this fraction is 1.0. Rating contribution is the VA's `rating` divided by 5.0. Capacity contribution is the VA's `weekly_capacity_hours` divided by 40.0, capped at 1.0. The `match_score` is the skill-coverage component weighted by 0.5, plus the rating component weighted by 0.3, plus the capacity component weighted by 0.2, with the weighted sum rounded half-up to four decimal places. The server selects the candidate with the highest `match_score`; if two candidates tie, the one whose `created_at` is earlier (the earlier-registered VA) wins, and the resource `id` is never consulted as a tie-break. If the eligibility set is empty, the proposal is rejected with `ERR_NO_ELIGIBLE_VA`.

The client then decides. **Accepting** a proposal advances `PROPOSED → ONBOARDING` and may only happen while the VA's `status` is `AVAILABLE` or `ENGAGED` (not `BENCHED`); acceptance sets that VA to `ENGAGED`. **Rejecting** a proposal advances `PROPOSED → REJECTED` and has no further effect. During onboarding the StaffingManager may **return the engagement to proposed** (`ONBOARDING → PROPOSED`), but only while `onboarding_checklist_done` is still false; if returning leaves the VA holding no other active engagement, the VA reverts to `AVAILABLE`. The StaffingManager **activates** an onboarded engagement (`ONBOARDING → ACTIVE`) by supplying `onboarding_checklist_done` as true, and only while the client is `SCOPED` or `ACTIVE`. Activation sets the client's `active_engagement_id` to this engagement and increments the VA's `active_engagement_count` by 1; and if the client was `SCOPED`, this same activation drives the client to `ACTIVE`, which in turn opens retainer cycle number 1 — granting `granted_hours` equal to the client's `monthly_retainer_hours`, `rolled_in_hours` of 0, `status` `OPEN`, and `opened_at_iso` from the clock. An `ACTIVE` engagement may be **ended** by the StaffingManager (and is also ended by the system when an escalation results in replacement or when its client closes). Ending decrements the VA's `active_engagement_count` and returns the VA to `AVAILABLE` if that count reaches 0; clears the client's `active_engagement_id` if it pointed at this engagement; and re-queues the engagement's non-terminal tasks (`QUEUED`, `ASSIGNED`, `IN_PROGRESS`, or `BLOCKED`) that no replacement re-homes — each such task returns to `QUEUED` with its `engagement_id` cleared and its SLA timers reset.

### 3.4. The Task Queue, SLA Clock, and Work Lifecycle

A **task** is one unit of admin work. It is created against a `client_id` with a `title`, an optional `priority` (one of `STANDARD`, `PRIORITY`, `URGENT`, defaulting to `STANDARD`), an optional `required_skill_tag_id` naming the skill the work needs, and an optional `estimated_hours` (a non-negative client estimate, defaulting to 0). A new task is `QUEUED`, and creating it recomputes the client's `open_task_count` — the number of that client's tasks not in a terminal state.

**Assigning** a queued task (`QUEUED → ASSIGNED`) routes it to the client's active engagement, setting the task's `engagement_id` to the client's `active_engagement_id`. Assignment may proceed only when the client is `ACTIVE` and has a non-null `active_engagement_id` (otherwise `ERR_CLIENT_NOT_ACTIVE`); when an SLA policy exists for the task's `priority` tier (otherwise `ERR_SLA_POLICY_MISSING`); and, when the task's `required_skill_tag_id` names a specialized skill, when the active engagement holds an `ACTIVE` add-on for that skill (otherwise `ERR_ADDON_REQUIRED`). On assignment the task's `assigned_at_iso` is stamped from the clock, its `sla_state` is set to `ON_TRACK`, and its two due dates are computed: `response_due_iso` is `assigned_at_iso` advanced by the policy's `response_minutes` minutes, and `resolution_due_iso` is `assigned_at_iso` advanced by the policy's `resolution_hours` hours.

The task's `sla_state` is re-evaluated on every read and on every transition, against the current clock, using a strict greater-than boundary — a clock value exactly equal to a due instant is still `ON_TRACK`, and only one second past it counts as breached. The evaluation is priority-ordered. If the task has reached `DONE`, the standing is latched: it is `RESOLUTION_BREACHED` when its `completed_at_iso` fell strictly after `resolution_due_iso`, otherwise `ON_TRACK`. Otherwise, if the clock now stands strictly after `resolution_due_iso`, the standing is `RESOLUTION_BREACHED`; else if the task has not yet taken a first action (its `first_action_at_iso` is still null) and the clock stands strictly after `response_due_iso`, the standing is `RESPONSE_BREACHED`; otherwise it is `ON_TRACK`. Resolution breach therefore dominates response breach when both windows have elapsed.

Work proceeds inside the engagement. The engagement's VA **starts** an assigned task (`ASSIGNED → IN_PROGRESS`), which stamps `first_action_at_iso` from the clock if it is still null. From either `ASSIGNED` or `IN_PROGRESS` the VA may **block** the task (`→ BLOCKED`), capturing a `blocked_reason` from the request and likewise stamping `first_action_at_iso` if it is still null. A blocked task is **unblocked** by the VA (`BLOCKED → IN_PROGRESS`), which clears `blocked_reason`, but only while the client is `ACTIVE` (not `SUSPENDED`). The VA **completes** an in-progress task (`IN_PROGRESS → DONE`), which is allowed only if the task already has at least one `APPROVED` time entry (otherwise `ERR_NO_APPROVED_TIME`); completion stamps `completed_at_iso`, latches `sla_state` as described above, and recomputes the client's `open_task_count`. All four work transitions (start, block, unblock, complete) require the acting VA to be the engagement's VA. A non-terminal task may also be **cancelled** (`QUEUED`, `ASSIGNED`, `IN_PROGRESS`, or `BLOCKED` → `CANCELLED`) by the client or StaffingManager, or by the system during a client close; cancellation moves the task's `LOGGED` time entries to `REJECTED` so they never charge a cycle, and recomputes `open_task_count`. Any transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.5. Logging, Approving, and Pricing Time Onto the Hour-Bank

Hours flow into the platform as **time entries** and only count against the retainer once a client has approved them. A VA logs an entry by naming the `task_id`, the wall-time `raw_minutes` spent (at least 1), and an optional `note`. An entry may be logged only on a task that is `ASSIGNED` or `IN_PROGRESS`, and only by the VA of that task's active engagement (otherwise `ERR_TASK_NOT_WORKABLE`); and only when the client currently has an `OPEN` retainer cycle to pin against (otherwise `ERR_CYCLE_NOT_OPEN`). On creation the entry is `LOGGED`, its `va_id` is set to the engagement's VA, its `cycle_id` is pinned to the client's current open cycle, and its `billable_hours` is computed. Billable hours round the raw wall-time **up** onto a 15-minute grid: the raw minutes are divided by 15 and rounded up to the next whole number of quarter-hours, and that quarter-hour count is multiplied by 0.25 to yield hours. Thus 1 minute and 15 minutes both bill as 0.25 hour, while 16 minutes bills as 0.5 hour.

A logged entry sits inert until the **client approves** it (`LOGGED → APPROVED`). Approval is permitted only while the client still has an `OPEN` retainer cycle (otherwise `ERR_NO_OPEN_CYCLE`) and only by the client that owns the task. Approving stamps `approved_at_iso` from the clock, pins `cycle_id` to the client's current open cycle, and then recomputes the cycle's balances and the task's `billed_hours`. The cycle balance is an aggregation over **only** the `APPROVED` entries pinned to that cycle (`LOGGED` and `REJECTED` entries are excluded): `consumed_hours` is the sum of those entries' `billable_hours`; the cycle's notional bank is its `granted_hours` plus its `rolled_in_hours`; `available_hours` is the bank minus `consumed_hours` but never below 0; and `overage_hours` is `consumed_hours` minus the bank but never below 0. These hour figures are carried to two decimals, rounded half-up, after the per-entry quarter-hour rounding. Approving an entry also **increments the cycle's `version` by 1** — this is the version bump that the cycle-close concurrency guard in §2.9 watches for. The task's `billed_hours` is the sum of `billable_hours` over its `APPROVED` entries. Alternatively the client may **reject** a logged entry (`LOGGED → REJECTED`), after which it never charges a cycle; the system also rejects an entry automatically when its task is cancelled.

### 3.6. Specialized-Skill Add-Ons

Some work needs a competency that is gated behind a paid surcharge. A client requests an **add-on** on a specific engagement by naming the `engagement_id`, the `skill_tag_id` of the specialized skill, and a `surcharge_rate_cents` (a non-negative per-hour cents surcharge applied to billed hours on tasks requiring that skill). The referenced skill must be one whose `is_specialized` is true; requesting an add-on against a non-specialized skill is rejected with `ERR_NOT_SPECIALIZED`. A new add-on is `REQUESTED`. The StaffingManager **activates** it (`REQUESTED → ACTIVE`), after which the engagement may take tasks requiring that specialized skill, and the surcharge becomes billable. An add-on may also be `REVOKED`. The link between an add-on and the assign-time gate of §3.4 is the heart of the specialized-skill rule: a task whose `required_skill_tag_id` is specialized can be assigned only while an `ACTIVE` add-on for exactly that skill exists on the active engagement.

### 3.7. Escalation and VA Replacement

When a relationship sours — through an SLA breach, a quality concern, an availability problem, or some other cause — a client or StaffingManager opens an **escalation** against the client's active engagement by naming the `client_id` and a `reason` (one of `SLA_BREACH`, `QUALITY`, `AVAILABILITY`, or `OTHER`). The escalation is born `OPEN`, with its `engagement_id` set to the client's `active_engagement_id` and its `client_id` carried for scoping. The StaffingManager either **resolves** it (`OPEN → RESOLVED`), leaving the original engagement running unchanged, or **replaces** the VA (`OPEN → REPLACED`).

Replacement is the platform's most consequential cascade and runs in three hops. It is permitted only when a replacement `va_id` is supplied whose VA is `AVAILABLE` or `ENGAGED` (not `BENCHED`) and when the original engagement is `ACTIVE`; otherwise the request is rejected with `ERR_REPLACEMENT_INELIGIBLE`. First, the system mints a brand-new engagement in `ACTIVE` status for the same client with the replacement VA, points the client's `active_engagement_id` at it, and increments the new VA's `active_engagement_count` by 1. Second — because that new engagement is now active — the original engagement is moved to `ENDED`: the old VA's `active_engagement_count` is decremented and the old VA returns to `AVAILABLE` if it reaches 0, and the original engagement's `superseded_by_engagement_id` is set to the new engagement's id. Third — as the engagement-end side effect fires — the original engagement's non-terminal tasks are re-pointed to the new `engagement_id`, and any that were `ASSIGNED` or `IN_PROGRESS` have their SLA due dates re-stamped against the moment of re-pointing. Finally the escalation's `replacement_engagement_id` is set to the new engagement's id and the escalation itself rests in `REPLACED`.

### 3.8. Closing a Cycle, Rolling Hours Forward, and Invoicing

The StaffingManager **closes** an open retainer cycle once its work is settled. A close is permitted only when the cycle is `OPEN`, when no `LOGGED` (un-approved) time entry still charges it (otherwise `ERR_CYCLE_HAS_PENDING_ENTRIES` — every entry must be approved or rejected first), and when the supplied `expected_cycle_version` matches the cycle's current `version` per the concurrency guard of §2.9 (otherwise `ERR_STALE_CYCLE_VERSION`, HTTP 412). On close the cycle moves to `CLOSED`, its `closed_at_iso` is stamped from the clock, and its `version` increments by 1. Unless the owning client is itself `CLOSED`, the close then mints a successor cycle: its `sequence_no` is the closing cycle's plus one, its `status` is `OPEN`, its `granted_hours` is the client's current `monthly_retainer_hours`, its `opened_at_iso` is the clock, and its `rolled_in_hours` is the rollover carry.

The **rollover carry** is computed from the closing cycle. Its unused hours are its bank (`granted_hours` plus `rolled_in_hours`) minus its `consumed_hours`, floored at 0. The amount that carries forward is the smaller of that unused figure and the client's `rollover_cap_hours`: when unused exceeds the cap, only the cap carries and the surplus above the cap is forfeited; when unused is at most the cap, the entire remainder carries and nothing is forfeited. Carry hours are computed to two decimals, rounded half-up, from approved entries only.

An **invoice** bills a cycle in one of two variants, and the variant determines both which hours are counted and which cycle state is legal. A `PROVISIONAL` invoice is drawn mid-cycle to project the bill and requires the cycle to be `OPEN`; a `FINAL` invoice is drawn after the cycle is sealed to actually bill the client and requires the cycle to be `CLOSED`. Drawing the wrong variant for the cycle's state is rejected with `ERR_INVOICE_VARIANT_STATE`. The two variants differ only in the billed-hour set: `PROVISIONAL` counts every time entry on the cycle whose status is either `LOGGED` or `APPROVED` (it optimistically counts hours not yet approved, so with any logged entry present a provisional total is at least the final total for the same data), whereas `FINAL` counts only `APPROVED` entries. An invoice is created by naming the `client_id`, the `cycle_id`, and the `variant`; it is born `ISSUED` and may later be `VOID`.

Invoice pricing follows a pinned evaluation order. First the billed-hour set is fixed per variant. Then those hours are split into a within-bank tier and an overage tier: within-bank hours are the lesser of billed hours and the cycle's bank (`granted_hours` plus `rolled_in_hours`), and overage hours are billed hours minus the bank, floored at 0. Each tier is then priced and rounded half-up to whole cents before any summing: `base_charge_cents` is within-bank hours times the client's `base_rate_cents`, and `overage_charge_cents` is overage hours times the client's `overage_rate_cents`. Next, `surcharge_cents` is computed: for each counted entry whose task's `required_skill_tag_id` matches the `skill_tag_id` of an `ACTIVE` add-on on the engagement, that entry's `billable_hours` is multiplied by that add-on's `surcharge_rate_cents`, the products are summed, and the sum is rounded half-up to whole cents. Then `sla_credit_cents` is the SLA breach credit. The credit aggregates, over every task of the client that has at least one `APPROVED` time entry charged to the billed cycle and whose `sla_state` is `RESOLUTION_BREACHED`, the product of that task's `billed_hours`, the client's `base_rate_cents`, and the breach penalty fraction from the SLA policy for that task's priority; the sum is rounded half-up to whole cents. The `total_cents` is `base_charge_cents` plus `overage_charge_cents` plus `surcharge_cents` minus `sla_credit_cents`, floored at 0. Finally `utilization_pct` is the billed hours divided by the bank, rounded half-up to four decimal places.

## 4. Endpoint Definitions

All endpoints are mounted under the `/va-staffing` prefix. Creating a new resource returns HTTP 201 with the created resource in `data`; reads, list operations, and state-changing actions on an existing resource return HTTP 200 with the affected (or retrieved) resource. Error responses carry the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/va-staffing/_clock/set_current_utc` | Set the logical clock (`to_iso8601`); startup default `2026-03-01T00:00:00Z` | StaffingManager |
| GET | `/va-staffing/_clock` | Read the current logical clock value | StaffingManager, Client, VA |
| POST | `/va-staffing/skill-tags` | Create a skill tag | StaffingManager |
| GET | `/va-staffing/skill-tags/{skill_tag_id}` | Get a skill tag | StaffingManager, Client, VA |
| GET | `/va-staffing/skill-tags` | List skill tags (filter by `is_specialized`) | StaffingManager, Client, VA |
| POST | `/va-staffing/sla-policies` | Create an SLA policy for a tier | StaffingManager |
| GET | `/va-staffing/sla-policies/{sla_policy_id}` | Get an SLA policy | StaffingManager, Client, VA |
| GET | `/va-staffing/sla-policies` | List SLA policies (filter by `tier`) | StaffingManager, Client, VA |
| POST | `/va-staffing/virtual-assistants` | Register a VA in the pool | StaffingManager |
| GET | `/va-staffing/virtual-assistants/{va_id}` | Get a VA | StaffingManager, Client, VA |
| GET | `/va-staffing/virtual-assistants` | List VAs (filter by `skill_tag_id`, `status`) | StaffingManager, Client |
| POST | `/va-staffing/clients` | Create a client (intake) | StaffingManager, Client |
| GET | `/va-staffing/clients/{client_id}` | Get a client | StaffingManager, Client |
| GET | `/va-staffing/clients` | List clients (filter by `status`) | StaffingManager |
| PATCH | `/va-staffing/clients/{client_id}/scope` | Scope a client | Client |
| POST | `/va-staffing/clients/{client_id}/suspend` | Suspend an active client | StaffingManager |
| POST | `/va-staffing/clients/{client_id}/resume` | Resume a suspended client | StaffingManager |
| POST | `/va-staffing/clients/{client_id}/close` | Close a client (cascade) | StaffingManager |
| POST | `/va-staffing/engagements` | Propose an engagement (auto-match if `va_id` omitted) | StaffingManager |
| GET | `/va-staffing/engagements/{engagement_id}` | Get an engagement | StaffingManager, Client |
| GET | `/va-staffing/engagements` | List engagements (filter by `client_id`, `va_id`, `status`) | StaffingManager, Client |
| POST | `/va-staffing/engagements/{engagement_id}/accept` | Accept a proposed engagement | Client |
| POST | `/va-staffing/engagements/{engagement_id}/reject` | Reject a proposed engagement | Client |
| POST | `/va-staffing/engagements/{engagement_id}/return-to-proposed` | Return an onboarding engagement to proposed | StaffingManager |
| POST | `/va-staffing/engagements/{engagement_id}/activate` | Activate an onboarded engagement | StaffingManager |
| POST | `/va-staffing/engagements/{engagement_id}/end` | End an active engagement | StaffingManager |
| POST | `/va-staffing/addons` | Request a specialized-skill add-on | Client |
| GET | `/va-staffing/addons/{addon_id}` | Get an add-on | StaffingManager, Client |
| GET | `/va-staffing/addons` | List add-ons (filter by `engagement_id`, `skill_tag_id`, `status`) | StaffingManager, Client |
| POST | `/va-staffing/addons/{addon_id}/activate` | Activate a requested add-on | StaffingManager |
| GET | `/va-staffing/cycles/{cycle_id}` | Get a retainer cycle with computed balances | StaffingManager, Client |
| GET | `/va-staffing/cycles` | List retainer cycles (filter by `client_id`, `status`) | StaffingManager, Client |
| POST | `/va-staffing/cycles/{cycle_id}/close` | Close an open cycle (OCC-guarded; mints successor) | StaffingManager |
| POST | `/va-staffing/tasks` | Create a task in the queue | Client, StaffingManager |
| GET | `/va-staffing/tasks/{task_id}` | Get a task (SLA standing re-evaluated) | StaffingManager, Client, VA |
| GET | `/va-staffing/tasks` | List tasks (filter by `client_id`, `engagement_id`, `required_skill_tag_id`, `status`, `priority`) | StaffingManager, Client, VA |
| POST | `/va-staffing/tasks/{task_id}/assign` | Assign a queued task to the active engagement | StaffingManager |
| POST | `/va-staffing/tasks/{task_id}/start` | VA starts an assigned task | VA |
| POST | `/va-staffing/tasks/{task_id}/block` | VA blocks a task (`blocked_reason`) | VA |
| POST | `/va-staffing/tasks/{task_id}/unblock` | VA unblocks a task | VA |
| POST | `/va-staffing/tasks/{task_id}/complete` | VA completes a task | VA |
| POST | `/va-staffing/tasks/{task_id}/cancel` | Cancel a non-terminal task | Client, StaffingManager |
| POST | `/va-staffing/time-entries` | VA logs time on a task | VA |
| GET | `/va-staffing/time-entries/{entry_id}` | Get a time entry | StaffingManager, Client, VA |
| GET | `/va-staffing/time-entries` | List time entries (filter by `task_id`, `cycle_id`, `va_id`, `status`) | StaffingManager, Client, VA |
| POST | `/va-staffing/time-entries/{entry_id}/approve` | Client approves a logged entry | Client |
| POST | `/va-staffing/time-entries/{entry_id}/reject` | Client rejects a logged entry | Client |
| POST | `/va-staffing/escalations` | Open an escalation on the active engagement | Client, StaffingManager |
| GET | `/va-staffing/escalations/{escalation_id}` | Get an escalation | StaffingManager, Client |
| GET | `/va-staffing/escalations` | List escalations (filter by `client_id`, `engagement_id`, `status`) | StaffingManager, Client |
| POST | `/va-staffing/escalations/{escalation_id}/resolve` | Resolve an escalation without replacement | StaffingManager |
| POST | `/va-staffing/escalations/{escalation_id}/replace` | Replace the VA (`va_id`); mint new engagement | StaffingManager |
| POST | `/va-staffing/invoices` | Generate an invoice (`variant`) for a cycle | StaffingManager |
| GET | `/va-staffing/invoices/{invoice_id}` | Get an invoice | StaffingManager, Client |
| GET | `/va-staffing/invoices` | List invoices (filter by `client_id`, `cycle_id`, `variant`, `status`) | StaffingManager, Client |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_VALIDATION_RANGE` | 422 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_SLA_POLICY_MISSING` | 409 |
| `ERR_ADDON_REQUIRED` | 409 |
| `ERR_NOT_SPECIALIZED` | 422 |
| `ERR_NO_ELIGIBLE_VA` | 422 |
| `ERR_TASK_NOT_WORKABLE` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_NO_OPEN_CYCLE` | 409 |
| `ERR_CYCLE_HAS_PENDING_ENTRIES` | 409 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_INVOICE_VARIANT_STATE` | 409 |
| `ERR_NO_APPROVED_TIME` | 409 |
| `ERR_REPLACEMENT_INELIGIBLE` | 409 |
| `ERR_DUPLICATE` | 409 |

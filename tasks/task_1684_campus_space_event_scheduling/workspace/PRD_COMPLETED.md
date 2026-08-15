# Campus Space & Event Scheduling API — Product Requirements Document

## 1. Introduction

A university's scheduling office sits between two demand streams that permanently compete for the same finite room inventory. Academic departments need recurring weekly placements for courses across an entire term, and those placements deserve protected priority during a defined scheduling window. At the same time, internal departments, student groups, and external clients file ad-hoc event requests that carry real operational weight: capacity and equipment constraints, setup and teardown occupancy, service orders for audiovisual, catering, custodial, and security crews, insurance gates for outside organizations, key and card access provisioning, and a rate structure that differs sharply by requester type.

This document specifies the Campus Space & Event Scheduling API, exposed under the `/campus` path prefix. The system manages the full lifecycle from room and term administration through academic placement runs, event approval and confirmation, service fulfillment, invoicing and payment, access-grant custody, and utilization analytics. Conflict detection, bumping rules, tiered cancellation fees, no-show tracking with escalating standing sanctions, and deposit forfeiture are all first-class behaviors. Every deadline, window, and recurrence rule in the system reads a single controllable logical clock rather than wall-clock time, and a daily-close checkpoint drives all clock-based state transitions in a pinned order.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `OrgRequester`, `Scheduler`, `ServiceCoordinator`, `FacilitiesManager`, and `FinanceAdmin`. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN`.

Role identity semantics differ across the five roles and are normative. When `X-User-Role` is `OrgRequester`, `X-User-ID` is the `id` of the acting Organization; ownership checks on any resource that references an Organization compare the resource's foreign-key field to `X-User-ID` — `requester_org_id` on an event reservation, `org_id` on an invoice, and the parent event's owning organization for service orders and access grants. When `X-User-Role` is `Scheduler`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `approved_by_user_id` on an event reservation) but does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `ServiceCoordinator`, when it is `FacilitiesManager`, and when it is `FinanceAdmin`: the identifier names an operator, never a stored entity. The finance segregation-of-duties rule in §3.6 compares one such recorded operator identifier against another; it is not an entity-ownership check.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty uppercase alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 rather than wall-clock time.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range or unparsable values are clamped rather than rejected: an unparsable `limit` falls back to the default of 10, a `limit` below 1 or above 100 is clamped to the nearest bound, and an unparsable or negative `offset` falls back to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by creation order — the earlier-created resource first.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock and the Daily-Close Checkpoint

Time in this system is a test-driving logical clock, not the host's wall clock. Before any adjustment, the server clock starts at exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time. A `Scheduler`-only capability advances the clock to a supplied `to_iso8601` instant; the target must be strictly later than the current value — the clock never moves backwards — and an unparsable or not-strictly-later target is rejected with `ERR_INVALID_REQUEST`. The response reports the resulting `current_utc`, echoing the supplied `to_iso8601` string verbatim. Every temporal rule in this document reads this clock: request decision deadlines, confirmation windows, check-in windows, cancellation notice tiers, bump shields, key return deadlines, term opening instants, outage end instants, no-show marking, and completion.

All clock-driven state transitions are applied by a single `Scheduler`-invoked operations checkpoint, the daily-close. The checkpoint executes its transitions in a pinned order:

1. Term statuses advance (`DRAFT` to `SCHEDULING`, `SCHEDULING` to `GENERAL`, any open term to `CLOSED`).
2. Rooms whose outage window has ended auto-return to service.
3. Event requests still `REQUESTED` past their decision deadline expire.
4. Approved events still `APPROVED` past their confirmation deadline expire, voiding their provisional invoices.
5. Confirmed events past their check-in deadline without a recorded check-in are marked as no-shows, applying the strike, the standing recomputation, and any resulting suspension cascade.
6. In-progress events whose end has passed complete, finalizing their invoices.
7. Issued access grants past their return deadline are marked overdue.
8. Organization balances are recomputed.

The checkpoint response reports per-step counters: `terms_advanced`, `rooms_returned`, `requests_expired`, `approvals_expired`, `no_shows_marked`, `events_completed`, `grants_overdue`, and `orgs_suspended`. Each counter counts affected resources, not individual transitions: a term that advances two phases within a single run still counts once in `terms_advanced`. Because the order is pinned, a single checkpoint can, for example, mark a no-show, push an organization to `SUSPENDED`, and cascade that suspension onto the organization's other events within one run.

### 2.5. Common Resource Properties

Every resource in the system — organizations, rooms, term windows, academic blocks, scheduling runs, event reservations, service orders, service crews, invoices, and access grants — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed integer that starts at 1 at creation — when `updated_at` equals `created_at` — and increments by one with every modification to the resource.

Any mutation counts as a modification, whether it is invoked by a client or driven by the system itself through a cascade or the daily-close checkpoint; each such mutation refreshes `updated_at` and increments `version` on every resource it touches. Both timestamps read the logical clock of §2.4. A resource touched several times within a single request — for example by a cascade that sweeps it alongside other changes — refreshes `updated_at` and increments `version` exactly once for that request. Server-written instants beyond these two fields (`decision_deadline`, `confirm_deadline`, `checked_in_at`, `return_deadline`, `returned_at`, `finalized_at`) render in the same three-fractional-digit UTC format, while caller-supplied instants (such as an event's `start_at` or a term's dates) are stored and echoed back verbatim as the request string; a bare `YYYY-MM-DD` value is accepted wherever an instant is expected and is read as UTC midnight.

### 2.6. Occupancy Intervals, Turnaround Buffers, and Conflict Semantics

Room availability is governed by occupancy intervals. An event occupies its room from `setup_minutes` before its `start_at` until `teardown_minutes` after its `end_at`, further extended by the room's `turnaround_buffer_minutes`. The buffer is asymmetric: it is appended after teardown only, never before setup. Occupancy intervals are half-open — the start instant is included and the end instant is excluded — so two intervals conflict only when each begins strictly before the other ends. An occupancy that ends at exactly the instant another begins does not conflict with it.

Only events in `APPROVED`, `CONFIRMED`, or `IN_PROGRESS` status occupy their rooms; a `REQUESTED` event blocks nothing. Conflict checks also consider the room's recorded outage windows and — during academic placement, and at event approval or rebooking — the instances of `PLACED` academic blocks on the same room; the creation-time conflict check screens committed events and outage windows only. A conflict surfaced at event creation, approval, or rebooking is rejected with `ERR_ROOM_NOT_AVAILABLE`.

An academic block recurs: it produces one instance on every date from the term's `term_start_date` through its `term_end_date`, both dates inclusive, whose UTC weekday appears in the block's `days_of_week`, occupying the span from the block's `start_time` to its `end_time` on each such date. Block instances carry no buffer of any kind.

### 2.7. Money, Rates, and Rounding

All monetary values are integers denominated in cents. Every rounding performed by the system uses the round-half-up method applied to whole cents, and each calculation states precisely where rounding is applied.

Rooms carry three rate cards: `internal_hourly_rate_cents` for `INTERNAL_DEPARTMENT` requesters, `student_hourly_rate_cents` for `STUDENT_GROUP` requesters, and `external_hourly_rate_cents` for `EXTERNAL` requesters. Peak pricing multiplies the applicable rate by the room's `peak_multiplier_bps`, expressed in basis points so that 12500 represents a 1.25x multiplier. An hour bucket is peak when its starting clock hour is 18:00 UTC or later, or when its date falls on a Saturday or Sunday in UTC. Rates are pinned onto each event at approval or rebooking time (§3.4), so later edits to a room's rate card never reprice an already-approved event.

### 2.8. Optimistic Concurrency Control

Two creation endpoints carry an optimistic concurrency check, and they are the only endpoints that accept a version field. Creating a scheduling run requires `expected_term_version` carrying the client's last observed `version` of the target term window; if the term's current `version` has advanced beyond that observation, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating an event reservation requires `expected_room_version` carrying the client's last observed `version` of the target room; a mismatch with the room's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Both creations themselves advance the parent's `version` by one — a successful run creation repoints the term's live draft, and a successful event creation records demand against the room — so a request built on an older read is reliably detected as stale. Endpoints not named here take no version field.

### 2.9. Validation Priority Order

Every request is evaluated against ten validation tiers in a fixed relative order, and the ordering is normative: a failure in an earlier tier surfaces its error and masks any failures in later tiers.

1. Authentication: the `X-User-Role` and `X-User-ID` headers are present and the role is recognized (`ERR_UNAUTHENTICATED`).
2. Authorization: the role is permitted for this endpoint (`ERR_FORBIDDEN`).
3. Existence: path identifiers are resolved left to right, then body foreign-key identifiers are resolved (`ERR_NOT_FOUND`); an `OrgRequester` addressing a resource owned by another organization is masked as not found at this tier.
4. Request shape: required fields, enum membership, and types (`ERR_INVALID_REQUEST`), together with the shape-family range checks `ERR_INVALID_TIME_RANGE`, `ERR_DURATION_OUT_OF_RANGE`, `ERR_SERVICE_WINDOW_OUT_OF_RANGE`, and `ERR_BLOCK_WINDOW_OUT_OF_TERM`.
5. Staleness: the optimistic-concurrency fields `expected_term_version` and `expected_room_version` match the parent's current `version` (`ERR_STALE_VERSION`).
6. State validity: the target resource is in a valid from-state for the requested transition, including the rule that approval cannot occur after the decision deadline (`ERR_INVALID_STATE`).
7. Compliance holds: external-client insurance validity at confirmation (`ERR_INSURANCE_INVALID`), the waiver segregation-of-duties rule (`ERR_SEGREGATION_OF_DUTIES`), and the suspended-organization bar on event creation and approval (`ERR_ORG_SUSPENDED`).
8. Temporal windows: the term priority lock on approval and rebooking (`ERR_TERM_PRIORITY_LOCKED`), the confirmation window (`ERR_CONFIRM_WINDOW_EXPIRED`), and the check-in window (`ERR_CHECKIN_WINDOW_CLOSED`).
9. Resource constraints: occupancy and outage conflicts (`ERR_ROOM_NOT_AVAILABLE`), capacity (`ERR_CAPACITY_EXCEEDED`), feature supersets (`ERR_FEATURE_MISMATCH`), crew category, shift, and capacity (`ERR_CREW_CATEGORY_MISMATCH`, `ERR_CREW_SHIFT_MISMATCH`, `ERR_CREW_CAPACITY_EXCEEDED`), key inventory (`ERR_NO_KEYS_AVAILABLE`), outstanding grants on cancellation (`ERR_ACCESS_GRANTS_OUTSTANDING`), shielded events blocking room edits and outages (`ERR_ROOM_EDIT_BLOCKED`, `ERR_ROOM_BLOCKED`), and duplicate term finalization (`ERR_TERM_ALREADY_FINALIZED`).
10. Money rules, always last: probation prepayment at confirmation (`ERR_PREPAYMENT_REQUIRED`), payment or waiver amounts exceeding the remaining balance (`ERR_OVERPAYMENT`), and refunds exceeding what was actually paid (`ERR_REFUND_EXCEEDS_PAID`).

### 2.10. Nested Resource Retrieval and Ownership Masking

Requests that address resources by identifier validate those identifiers in a strict left-to-right order along the path, before any body foreign keys are resolved. The request is rejected with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. Ownership masking composes with this rule: when an `OrgRequester` addresses a resource owned by a different organization — an event, a service order, an invoice, or an access grant — the system responds with `ERR_NOT_FOUND` exactly as if the resource did not exist, and list endpoints silently scope an `OrgRequester`'s results to their own organization. List endpoints additionally accept exact-match equality filters as query parameters: academic blocks filter by `term_id`, `assigned_room_id`, `scheduling_run_id`, and `status`; scheduling runs by `term_id` and `status`; event reservations by `room_id`, `requester_org_id`, and `status`; service orders by `event_id`, `crew_id`, `category`, and `status`; invoices by `event_id`, `org_id`, and `status`; and access grants by `event_id`, `room_id`, and `status`. Filtering happens before pagination, so `total_count` reflects the filtered set; a filter value that matches no row yields an empty page, and unrecognized query parameters are ignored.

## 3. Business Logic & Workflows

### 3.1. Organizations, Standing, and Client Eligibility

A `Scheduler` registers each client organization with a `name`, an `org_type` of `INTERNAL_DEPARTMENT`, `STUDENT_GROUP`, or `EXTERNAL`, and a `contact_email`. Liability insurance fields — `insurance_certificate_expiry` and `insurance_coverage_cents` — are optional at registration and may remain null; they become decisive only when an external client confirms an event. New organizations begin with `standing` of `GOOD`, a `no_show_count` of zero, and zero balances. A `Scheduler` may later update the contact and insurance fields; each update increments the organization's `version` by one.

The `org_type` follows the organization into every booking. It determines the `precedence_tier` stamped onto each event at creation — 200 for `INTERNAL_DEPARTMENT`, 100 for `STUDENT_GROUP`, and 50 for `EXTERNAL` — and it selects which of a room's three rate cards applies to that requester. Academic placements outrank every event precedence tier during a term's placement run.

Standing is derived from accumulated no-show strikes and is recomputed inside the same daily-close run that increments the count. An organization with a `no_show_count` of exactly two moves from `GOOD` to `PROBATION`; one whose count reaches three or more moves from `PROBATION` to `SUSPENDED`; a count of one or zero keeps the organization `GOOD`. While an organization is on `PROBATION`, every future confirmation by that organization requires the provisional invoice to be fully covered by payments and waivers before the confirmation is accepted. Suspension is harsher: a `SUSPENDED` organization cannot create new event requests and its events cannot be approved, both rejected with `ERR_ORG_SUSPENDED`, and the suspension cascade resolves its in-flight bookings. The organization's events still in `REQUESTED` move to `DECLINED` with `decline_reason` recording `ORG_SUSPENDED`; its events in `APPROVED` move to `CANCELLED` with `cancel_reason` recording `ORG_SUSPENDED`, a cancellation fee of zero, their `PROVISIONAL` invoices voided, and their non-terminal service orders — fulfilled ones included — cancelled with `fee_waived` set true; its access grants still in `REQUESTED` are revoked. Events already `CONFIRMED` or `IN_PROGRESS` are deliberately not touched. A `Scheduler` may reinstate a suspended organization, which requires the organization to be `SUSPENDED`, resets its `no_show_count` to zero, returns `standing` to `GOOD`, and increments the organization's `version` by one.

Two computed balances summarize each organization's posture. `deposit_held_cents` is the sum of `deposit_cents` over the organization's access grants currently in `ISSUED` or `OVERDUE` status. `outstanding_balance_cents` is the sum, over the organization's invoices in `PROVISIONAL`, `FINALIZED`, or `PARTIALLY_PAID` status, of each invoice's `total_cents` less its `paid_cents` and `waived_cents`; voided invoices contribute nothing.

### 3.2. Room Inventory, Rate Cards, and Outages

A `FacilitiesManager` builds the room inventory. Each room records a `name`, a `building_code`, a `capacity` giving its maximum legal occupancy, and the three hourly rate cards described in §2.7. Optional creation fields include `features`, a subset of the fixed equipment vocabulary — `PROJECTOR`, `VIDEO_CONF`, `SOUND_SYSTEM`, `STAGE`, `PIANO`, `LAB_BENCHES`, `KITCHEN_ACCESS`, and `ADA_LIFT` — defaulting to empty; `turnaround_buffer_minutes`, defaulting to 30; `peak_multiplier_bps`, defaulting to 12500; and `key_count`, the number of physical key inventory slots, defaulting to zero. Rooms are created in `ACTIVE` status with `keys_issued` and `keys_lost_total` at zero. The `keys_issued` counter is computed as the number of the room's physical-key grants currently `ISSUED` or `OVERDUE`, and `keys_lost_total` accumulates physical keys marked lost; the sum of `key_count` and `keys_lost_total` is invariant over the room's life, shrinking and growing in lockstep as slots are retired.

Room edits follow the same role and cover any of `capacity`, `features`, `turnaround_buffer_minutes`, the three rate fields, `peak_multiplier_bps`, or `key_count`, incrementing the room's `version` by one. A capacity reduction is a booking event in its own right: events in `REQUESTED` or `APPROVED` whose `expected_attendance` exceeds the new capacity are automatically bumped with the full bump cascade described in §3.4. If a `CONFIRMED` or `IN_PROGRESS` event would exceed the new capacity, the edit is rejected outright with `ERR_ROOM_EDIT_BLOCKED`.

Taking a room out of service requires an `outage_start_at` and an `outage_end_at`, with the end later than the start or the request fails with `ERR_INVALID_TIME_RANGE`, and the room must be `ACTIVE` — an already `OUT_OF_SERVICE` room rejects a further outage with `ERR_INVALID_STATE`. The room refuses the outage with `ERR_ROOM_BLOCKED` whenever the window overlaps non-bumpable occupancy — a `CONFIRMED` event whose start is less than 72 hours away or that holds any `ISSUED` or `OVERDUE` access grant, or any `IN_PROGRESS` event. Otherwise the room moves to `OUT_OF_SERVICE`, `outage_start_at` and `outage_end_at` are set, the window is appended to the append-only `outage_windows` history, each entry recording the supplied `start_at` and `end_at`, every bumpable overlapping event is bumped with the full cascade, and the room's `version` increments by one. Bumpable here means any overlapping `REQUESTED` or `APPROVED` event, plus a `CONFIRMED` event only when at least 72 hours remain before its start and it holds no `ISSUED` or `OVERDUE` grants. The daily-close checkpoint returns the room to `ACTIVE` once the clock reaches `outage_end_at`, clearing the two current-outage fields while the history in `outage_windows` is retained.

Utilization analytics are a computed read available to `Scheduler` and `FacilitiesManager` over a `window_start` and `window_end` supplied as query parameters; a missing or unparsable bound is rejected with `ERR_INVALID_REQUEST`, and an end not later than the start is rejected with `ERR_INVALID_TIME_RANGE`. Each contributing event books the interval from `setup_minutes` before its `start_at` to `teardown_minutes` after its `end_at` — the turnaround buffer is never counted — clamped to the window. The scheduled variant counts events in `APPROVED`, `CONFIRMED`, `IN_PROGRESS`, or `COMPLETED`; the realized variant counts `COMPLETED` events only. Overlapping booked intervals are merged before summing so nothing is double counted. The denominator is the window's length in minutes minus the minutes of the room's outage windows overlapping the window, themselves merged. Each utilization figure is ten thousand times the booked duration divided by the denominator duration — computed on the exact durations before any minute conversion — rounded half-up to a whole basis point, while the minute fields report whole minutes with any sub-minute remainder discarded. When the denominator is zero or negative, both basis-point fields are null while the minute fields are still reported. The response carries `window_minutes`, `outage_minutes`, `scheduled_minutes`, `realized_minutes`, `scheduled_utilization_bps`, and `realized_utilization_bps`.

### 3.3. Terms, Academic Blocks, and the Placement Run

A `Scheduler` opens each academic term with a `name`, a `term_start_date` and `term_end_date` marking the first and last instructional dates inclusive, a `priority_open_at` instant when academic priority scheduling opens, and a `general_open_at` instant when general ad-hoc approval opens. Terms begin in `DRAFT` with `current_draft_run_id` null, since no live draft run exists yet. The daily-close checkpoint advances a term from `DRAFT` to `SCHEDULING` once the clock reaches `priority_open_at`, from `SCHEDULING` to `GENERAL` once the clock reaches `general_open_at`, and from any of `DRAFT`, `SCHEDULING`, or `GENERAL` to the terminal `CLOSED` once the clock passes one full day beyond `term_end_date`. A closed term accepts no new academic blocks and no new scheduling runs; either attempt is rejected with `ERR_INVALID_STATE`.

The `SCHEDULING` phase is the academic priority window. While a term is in `SCHEDULING`, approval or rebooking of any ad-hoc event whose span from `start_at` to `end_at` intersects that term's instructional dates is rejected with `ERR_TERM_PRIORITY_LOCKED` until the term reaches `GENERAL`; finalizing a placement run while the term is in any status other than `SCHEDULING` fails with the same error.

Academic blocks express recurring weekly placement demand. A `Scheduler` creates a block — permitted while the term is `DRAFT` or `SCHEDULING`, with a term in `GENERAL` or `CLOSED` rejecting the attempt with `ERR_INVALID_STATE` — with a `term_id`, a `course_code`, an `instructor_name`, an `enrollment` headcount, a `days_of_week` list drawn from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, and `SUN`, and day-time bounds `start_time` and `end_time` in HH:MM UTC; `required_features` is optional and defaults to empty. The block is rejected with `ERR_BLOCK_WINDOW_OUT_OF_TERM` when the start time is not earlier than the end time, when `days_of_week` is empty, or when the recurrence would produce no instance inside the term's dates. New blocks are `UNPLACED`, with `assigned_room_id` and `scheduling_run_id` null until a run places them.

Each block's `priority_score` is computed from its request data only, never from any candidate room; it is computed and stored at block creation and recomputed in the first pass of every finalization. The score awards ten points per enrolled student, adds a per-feature weight for each entry in `required_features` — 50 for `PIANO`, 40 for `STAGE`, 30 for `LAB_BENCHES`, 25 for `KITCHEN_ACCESS`, 20 for `VIDEO_CONF`, 15 for `SOUND_SYSTEM`, 10 for `PROJECTOR`, and 5 for `ADA_LIFT` — and adds a flat 100-point large-class bonus when enrollment reaches at least 100.

A `Scheduler` creates a scheduling run for a term by supplying the `term_id` and the OCC field `expected_term_version` described in §2.8. Each term has exactly one live `DRAFT` run: creating a new run supersedes the prior `DRAFT`, moving it to `SUPERSEDED` and repointing the term's `current_draft_run_id` to the new run, and the term's `version` increments by one. Finalizing a run requires the run to be `DRAFT`, the term to be in `SCHEDULING` (otherwise `ERR_TERM_PRIORITY_LOCKED`), and no other `FINALIZED` run to exist for the term (otherwise `ERR_TERM_ALREADY_FINALIZED`).

Finalization executes the placement algorithm in three pinned passes. First, every `UNPLACED` block of the term is scored from request data as above — scoring completes for all blocks before any assignment is considered. Second, the blocks are sorted by descending `priority_score`, ties broken by descending `enrollment`, then by ascending `created_at`. Third, each block is assigned in that order. Candidate rooms are `ACTIVE` rooms whose `capacity` is at least the block's `enrollment` and whose `features` are a superset of `required_features`; the same capacity guard that rejects an over-attendance event with `ERR_CAPACITY_EXCEEDED` applies to enrollment figures here, with under-capacity rooms simply ineligible as candidates. For each block, the algorithm first tries free candidates — those with no overlap from any `PLACED` block instance and no overlap from any event occupancy, `REQUESTED` demand included — picking the best fit, meaning the candidate whose capacity exceeds the enrollment by the fewest seats, with ties broken by the earliest-created room. If no free candidate exists, it tries bumpable candidates — those with no `PLACED` block overlaps and whose only event conflicts are bumpable events — applying the same best-fit rule and bumping every conflicting bumpable event with the full cascade of §3.4. A block with neither free nor bumpable candidates remains `UNPLACED` and is recorded in the run's `unplaced_block_ids`. Placed blocks move to `PLACED` with `assigned_room_id` and `scheduling_run_id` set. The run records `placed_count`, the `bumped_event_ids` in placement processing order, the `unplaced_block_ids` in processing order, and `finalized_at`; the term's `current_draft_run_id` is cleared to null since the run is no longer a draft.

Placement is not irreversible for the block itself: a `Scheduler` may unplace a `PLACED` block, clearing `assigned_room_id` and `scheduling_run_id` and returning it to `UNPLACED`. Events bumped by the original placement are not retroactively restored — they remain `BUMPED` and must be rebooked.

### 3.4. The Event Reservation Lifecycle

An ad-hoc booking begins when an `OrgRequester` creates an event reservation with a `room_id`, a `title`, an `expected_attendance`, the event bounds `start_at` and `end_at`, and the OCC field `expected_room_version`; `required_features`, `setup_minutes`, and `teardown_minutes` are optional, with the latter two defaulting to zero, and a negative setup or teardown value is rejected with `ERR_INVALID_REQUEST`. The request is screened at creation: attendance must be at least one (`ERR_INVALID_REQUEST`) and no more than the room's `capacity` (`ERR_CAPACITY_EXCEEDED`), `end_at` must be later than `start_at` (`ERR_INVALID_TIME_RANGE`), the event must run at least 30 minutes and at most 8 hours (`ERR_DURATION_OUT_OF_RANGE`), `required_features` must be a subset of the room's `features` (`ERR_FEATURE_MISMATCH`), and the buffered occupancy must conflict with nothing already committed on the room (`ERR_ROOM_NOT_AVAILABLE`). An event created while the organization is `SUSPENDED` is rejected with `ERR_ORG_SUSPENDED`. The system stamps the reservation with the creator's organization as `requester_org_id`, taken from `X-User-ID` — an `X-User-ID` naming no registered organization is rejected with `ERR_NOT_FOUND` — sets `status` to `REQUESTED`, computes `decision_deadline` as 72 hours after creation, derives `precedence_tier` from the organization's type, and increments the room's `version` by one.

Approval is the `Scheduler`'s decision, and its gates follow the tier order of §2.9. The event must still be `REQUESTED` with its `decision_deadline` not yet passed (otherwise `ERR_INVALID_STATE`); the organization must not be `SUSPENDED`; no term whose instructional dates intersect the event's span may still be in `SCHEDULING` (otherwise `ERR_TERM_PRIORITY_LOCKED`); and the room must be `ACTIVE` (otherwise `ERR_ROOM_NOT_AVAILABLE`), have capacity for the `expected_attendance`, offer a superset of the `required_features`, and show no occupancy conflict against committed events, placed block instances, or outage windows. Approval pins the economics onto the event: `pinned_hourly_rate_cents` is the room's rate card entry for the requester's `org_type` and `pinned_peak_multiplier_bps` is the room's current multiplier, and later room edits never reprice this event. A `PROVISIONAL` invoice is created from the room charge, the forward-looking service charge, and the insurance surcharge as defined in §3.6; `confirm_deadline` is set to 48 hours after the approval; and `approved_by_user_id` records the acting scheduler's `X-User-ID`, later feeding the segregation-of-duties rule on waivers. The event is now `APPROVED`.

A `Scheduler` may instead decline a `REQUESTED` event, supplying a `reason` that is stored as the event's `decline_reason` as the event moves to `DECLINED`. Requests left undecided expire on their own: the daily-close moves a `REQUESTED` event past its `decision_deadline` to `EXPIRED`, and an `APPROVED` event past its `confirm_deadline` to `EXPIRED` with its provisional invoice voided.

Confirmation belongs to the requesting organization. The actor must own the event — a mismatch is masked as `ERR_NOT_FOUND` — and three gates apply in tier order. For an `EXTERNAL` organization, the `insurance_certificate_expiry` must fall on or after the event's `end_at` and `insurance_coverage_cents` must be at least 100000000 cents of liability coverage, failing which the confirmation is rejected with `ERR_INSURANCE_INVALID`. The confirmation must arrive on or before the `confirm_deadline`, otherwise `ERR_CONFIRM_WINDOW_EXPIRED`. And an organization on `PROBATION` may confirm only when its provisional invoice is fully covered — `paid_cents` plus `waived_cents` reaching the invoice's `total_cents` — otherwise `ERR_PREPAYMENT_REQUIRED`. A confirmed event's occupancy becomes hard-locked for conflict checks, and confirmation arms the bump shields: from `CONFIRMED`, the event can be bumped only while at least 72 hours remain before its start and it holds no `ISSUED` or `OVERDUE` grants.

Check-in moves a `CONFIRMED` event to `IN_PROGRESS`. Either the owning `OrgRequester` or a `FacilitiesManager` may check in, but only within the window from thirty minutes before the event's `start_at` through fifteen minutes after it, both bounds inclusive; outside that window the attempt is rejected with `ERR_CHECKIN_WINDOW_CLOSED`. A successful check-in records `checked_in_at`.

Cancellation is available from `REQUESTED`, `APPROVED`, `CONFIRMED`, and `BUMPED`. The owning `OrgRequester` cancels with `cancel_reason` recorded as `CLIENT`; a `Scheduler` cancels with reason `ADMIN`; cancelling from the `BUMPED` state records reason `BUMPED`; and the suspension cascade of §3.1 records `ORG_SUSPENDED`. A `CONFIRMED` event holding any access grant in `ISSUED` or `OVERDUE` refuses cancellation with `ERR_ACCESS_GRANTS_OUTSTANDING` until those grants are returned or marked lost. Client cancellations carry a tiered fee computed from the exact-minute notice between the cancellation moment and the event's `start_at`, applied to a pinned base equal to the provisional invoice's `room_charge_cents` plus its `service_charge_cents` — a snapshot, never recomputed at cancel time. Notice of at least 72 hours is free; notice of at least 24 hours but less than 72 hours incurs half the base, expressed as 5000 basis points; notice under 24 hours incurs the full base, expressed as 10000 basis points. The fee is the base multiplied by the tier's basis points and divided by ten thousand, rounded half-up once to whole cents. A cancellation made exactly 72 hours before the start is free, while one made exactly 24 hours before falls into the half-fee tier. Cancellations with reason `ADMIN`, `BUMPED`, or `ORG_SUSPENDED` are always free regardless of notice. The computed amount is stored on the event as `cancellation_fee_cents`.

Invoice handling at cancellation follows the money. Events cancelled from `REQUESTED` or `BUMPED` have no live invoice — a request never had one, and a bumped event's provisional invoice was voided at bump time — so the fee is zero and no invoice is created or transitioned. For an event with a live invoice, the invoice is voided when the fee is zero and no order has been fulfilled (voiding applies to a live `PROVISIONAL` invoice; one already `PAID` is left untouched); otherwise the invoice is finalized — a `PROVISIONAL` invoice moving to `FINALIZED`, an already-`PAID` invoice keeping its status — with a total consisting of the cancellation fee plus the fulfilled service charges plus any accrued deposit forfeits, with the room charge line excluded and no insurance surcharge applied. All of the event's remaining non-terminal service orders move to `CANCELLED` — fulfilled orders do not, having already moved to `INVOICED` as the invoice finalized — with `fee_waived` set true for every reason except `CLIENT`, and its access grants still in `REQUESTED` are revoked.

Bumping is the system's way of reclaiming space, triggered by placement finalization, by a room going out of service, or by a capacity reduction below an event's `expected_attendance`. `REQUESTED` and `APPROVED` events are always bumpable; `CONFIRMED` events are bumpable only under the 72-hour and no-outstanding-grants shield described above. The bump cascade clears the event's `room_id` to null, voids its `PROVISIONAL` invoice in a full waiver when one exists, cancels all non-terminal service orders — fulfilled ones included — with `fee_waived` set true, and revokes its `REQUESTED` access grants.

A bumped event is not dead. Rebooking — available to a `Scheduler` or the owning `OrgRequester` — supplies a new `room_id` and applies the same room gates as approval: the new room must be `ACTIVE`, sized for the attendance, equipped with a superset of the required features, free of occupancy and outage conflicts, and clear of the term priority lock. The event's `room_id` is set to the new room, rates are re-pinned from the new room at rebooking time, `approved_by_user_id` is set to the rebooking actor's `X-User-ID`, a fresh `PROVISIONAL` invoice is created at the new rates with the voided history retained, and `confirm_deadline` restarts at 48 hours after the rebooking — the organization must confirm again before the event stands.

Events that nobody shows up for are marked by the daily-close: a `CONFIRMED` event whose clock has passed fifteen minutes after `start_at` with no recorded check-in moves to `NO_SHOW`. Its invoice is finalized with the room charged at 100%, the fulfilled service charges, and a flat 5000-cent `no_show_fee_cents`, with no insurance surcharge applied. Fulfilled orders move to `INVOICED`; every other non-terminal order is cancelled with `fee_waived` false. The organization's `no_show_count` is incremented by one and its `standing` recomputed — exactly two strikes means `PROBATION`, three or more means `SUSPENDED` with the full suspension cascade.

An event that does proceed completes at the daily-close once the clock reaches its `end_at`, moving from `IN_PROGRESS` to `COMPLETED`. The invoice is finalized on the final variant of §3.6: fulfilled and invoiced orders only, the insurance surcharge recomputed on the final base for external clients, and any deposit charges included. Fulfilled orders move to `INVOICED`, while orders still in `SCHEDULED`, `APPROVED`, `QUOTED`, `REQUESTED`, or `NEEDS_REVISION` are cancelled with `fee_waived` true.

### 3.5. Service Orders and Crew Assignment

The owning `OrgRequester` attaches a service order to one of its events by supplying the `event_id`, a `category` of `AV`, `CATERING`, `CUSTODIAL`, or `SECURITY`, a `quantity` of at least one — a non-positive quantity is rejected with `ERR_INVALID_REQUEST` — and the service window bounds `service_start_at` and `service_end_at`. The parent event must be `APPROVED` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`). The window must end after it begins (`ERR_INVALID_TIME_RANGE`) and must lie within the margin from two hours before the event's `start_at` to two hours after its `end_at`, both margin bounds inclusive (`ERR_SERVICE_WINDOW_OUT_OF_RANGE`). New orders are `REQUESTED`, with `unit_cost_cents`, `quoted_total_cents`, and `crew_id` all null.

Quoting belongs to the `ServiceCoordinator`, who supplies a `unit_cost_cents` — a negative value is rejected with `ERR_INVALID_REQUEST`. A quote moves a `REQUESTED` order to `QUOTED`, setting `quoted_total_cents` to the `quantity` multiplied by the per-unit cost, and requires the parent event to be `APPROVED` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`). The owning requester then either approves the quote, moving the order from `QUOTED` to `APPROVED`, or sends it back for revision with a `note`, moving it from `QUOTED` to `NEEDS_REVISION` with the note stored as `revision_note`. While an order sits in `NEEDS_REVISION` it is excluded from the provisional invoice's service charge. A fresh quote on a `NEEDS_REVISION` order moves it back to `QUOTED`, recomputing the quoted total and clearing the `revision_note`. Every quote, re-quote, approval, revision request, and cancellation recomputes the parent provisional invoice's `service_charge_cents`, which is the sum of `quoted_total_cents` over the event's orders in `QUOTED`, `APPROVED`, `SCHEDULED`, or `FULFILLED` status — deliberately forward-looking, since it anticipates work that has been priced even if not yet performed.

Scheduling an `APPROVED` order assigns a crew. The `ServiceCoordinator` names a `crew_id`, and three checks follow in order. The crew's `category` must equal the order's `category` (`ERR_CREW_CATEGORY_MISMATCH`). The crew's shift — the span from its `shift_start` to its `shift_end` — must cover the entire service window, judged at minute granularity on UTC clock times: `shift_start` must be at or before the service window's start time-of-day and `shift_end` at or after its end time-of-day (`ERR_CREW_SHIFT_MISMATCH`). And the crew must have capacity: counting the crew's other `SCHEDULED` orders whose service windows overlap this one — half-open, so a window ending exactly when another begins is not an overlap — the count must be strictly below the crew's `concurrent_capacity`. One below capacity schedules fine; a count equal to capacity is rejected with `ERR_CREW_CAPACITY_EXCEEDED`. A successful scheduling sets `crew_id` and moves the order to `SCHEDULED`.

Once the clock reaches an order's `service_end_at`, the `ServiceCoordinator` marks it fulfilled, moving it from `SCHEDULED` to `FULFILLED`; an attempt before that instant is rejected with `ERR_INVALID_STATE`. Fulfillment is the point of no return: when the parent event finalizes — by completion, by a cancellation with charges, or by no-show — fulfilled orders move to `INVOICED` and their charges lock into the final invoice. A non-terminal order may instead be cancelled by the `ServiceCoordinator` or the owning requester from `REQUESTED`, `QUOTED`, `NEEDS_REVISION`, `APPROVED`, or `SCHEDULED`, ending in `CANCELLED` with the provisional service charge recomputed. The `fee_waived` flag records who is responsible: it is true only when the cancellation came from a system cascade — a bump, an admin or suspension cancellation, or event completion — and false for requester-initiated cancels and for orders swept aside by a no-show.

Crews themselves are registered by the `ServiceCoordinator` with a `name`, a `category` from the same four-value vocabulary, a `concurrent_capacity` of at least one, and the shift bounds `shift_start` and `shift_end` in HH:MM UTC, the end later than the start — a non-positive capacity or an end not later than the start is rejected with `ERR_INVALID_REQUEST`.

### 3.6. Invoicing, Payments, and Finance Controls

An invoice is born `PROVISIONAL` at event approval or rebooking, and each event has at most one live `PROVISIONAL` or `FINALIZED` invoice at a time; voided invoices are retained as history. The invoice's `event_id` ties it to its event, and `org_id` is denormalized from the event's owner for finance queries. Its charges decompose into `room_charge_cents`, `service_charge_cents`, `insurance_surcharge_cents`, `cancellation_fee_cents`, `no_show_fee_cents`, and `deposit_charge_cents`, and `total_cents` is always the sum of those components. The cumulative ledgers `paid_cents`, `waived_cents`, and `refunded_cents` start at zero.

The room charge bills occupancy — but not the turnaround buffer. The billable interval runs from `setup_minutes` before `start_at` to `teardown_minutes` after `end_at`, using the pinned rate and pinned multiplier. That interval is split into wall-clock-hour buckets aligned to UTC hour boundaries, and every bucket the interval touches counts as one full billed hour, however briefly it is touched. A peak bucket — one whose starting clock hour is 18:00 UTC or later, or whose date is a Saturday or Sunday in UTC — charges the pinned hourly rate multiplied by the pinned peak multiplier basis points and divided by ten thousand, rounded half-up to whole cents; any other bucket charges the pinned hourly rate. The rounding order is pinned: each bucket is rounded to cents first, and the rounded bucket charges are then summed. Summing first and rounding once is a different, forbidden order — with a pinned rate of 9999 cents and three peak buckets, the pinned order yields 37497 cents where sum-then-round would yield 37496.

The insurance surcharge applies to external clients only: two percent of the combined room and service charges, rounded half-up to whole cents, and zero for `INTERNAL_DEPARTMENT` and `STUDENT_GROUP` organizations. It is never applied on cancellation or no-show invoices.

The provisional and final variants diverge in what they anticipate. The provisional variant, computed at approval or rebooking, is forward-looking: its service charge sums the quoted totals of orders in `QUOTED`, `APPROVED`, `SCHEDULED`, or `FULFILLED`, and its total is the room charge plus that service charge plus the insurance surcharge. The final variant, computed at completion, no-show, or cancellation with charges, counts actuals. On completion, the service charge sums orders in `FULFILLED` or `INVOICED` only, the surcharge is recomputed on that final base for external clients, and the total adds any `deposit_charge_cents`. On no-show, the total is the room charge at full value plus the final service charge plus the flat 5000-cent no-show fee plus deposit charges, with no surcharge. On cancellation with charges, the total is the cancellation fee plus the final service charge plus deposit charges, with the room line excluded and no surcharge. The two variants diverge whenever an order sits in `QUOTED`, `APPROVED`, or `SCHEDULED` but never reaches `FULFILLED`.

Deposit forfeits from access grants accrue into `deposit_charge_cents`, and the invoice totals are recomputed when they arrive — even on an already-`FINALIZED` invoice.

Payments come from the owning `OrgRequester` or a `FinanceAdmin` as an `amount_cents`, which must be positive — a non-positive amount is rejected with `ERR_INVALID_REQUEST` here and on the waiver and refund actions alike. Prepayment of a `PROVISIONAL` invoice is allowed — this is how a probationary organization satisfies its confirmation gate — while `FINALIZED` and `PARTIALLY_PAID` invoices accept payments in the ordinary way. The amount may not exceed the remaining balance, the invoice's `total_cents` less its `paid_cents` and `waived_cents`, and attempts beyond that are rejected with `ERR_OVERPAYMENT`, as is any payment attempted on a `VOIDED` or `REFUNDED` invoice. Each payment adds to `paid_cents`. A partial payment moves a `FINALIZED` invoice to `PARTIALLY_PAID`; a payment or waiver that brings `paid_cents` plus `waived_cents` to exactly `total_cents` moves the invoice to `PAID`, whether it started `PROVISIONAL`, `FINALIZED`, or `PARTIALLY_PAID`.

Waivers are a `FinanceAdmin`-only act carrying an `amount_cents` and a `reason`, and they are segregation-of-duties gated: the waiving operator's `X-User-ID` must differ from the event's recorded `approved_by_user_id`, or the waiver is rejected with `ERR_SEGREGATION_OF_DUTIES`. A waiver against a `VOIDED` or `REFUNDED` invoice is rejected with `ERR_INVALID_STATE`. The waived amount is capped at the remaining balance — `total_cents` less `paid_cents` and `waived_cents` — with excess rejected as `ERR_OVERPAYMENT`, and each waiver adds to `waived_cents`.

Refunds run against money actually collected: only a `PAID` or `PARTIALLY_PAID` invoice can be refunded, and any other status is rejected with `ERR_INVALID_STATE`. A `FinanceAdmin` supplies an `amount_cents` that may not exceed `paid_cents` less `refunded_cents`, otherwise `ERR_REFUND_EXCEEDS_PAID`. Each refund adds to `refunded_cents`, and the invoice becomes `REFUNDED` only when the accumulated refunds equal the accumulated payments in full, from either `PAID` or `PARTIALLY_PAID`.

### 3.7. Access Grants, Key Inventory, and Deposit Forfeiture

Physical access is provisioned per event. An `OrgRequester` requests a grant for one of its events, or a `FacilitiesManager` files the request on the organization's behalf, supplying the `event_id` and a `grant_type` of `PHYSICAL_KEY` or `CARD_ACCESS`. The new grant is `REQUESTED`, its `room_id` is copied from the event's room, and its `return_deadline` is computed as 24 hours after the event's `end_at`.

Issuance is a `FacilitiesManager` action and requires the event to be `CONFIRMED`, failing which the request is rejected with `ERR_INVALID_STATE`. At issuance the deposit is set — 7500 cents for a physical key, 2500 cents for card access — the organization's `deposit_held_cents` grows by that amount, and for a physical key the grant draws the lowest-numbered free `key_slot` of the room's slot namespace — spanning 1 through `key_count` + `keys_lost_total`, with slots retired by lost keys never reused — while the room's `keys_issued` increments by one. A physical-key issuance is refused with `ERR_NO_KEYS_AVAILABLE` once `keys_issued` has reached `key_count`. Card access draws no slot and touches no counter.

Grants left outstanding past their deadline are marked `OVERDUE` by the daily-close once the clock passes the `return_deadline`.

Returning a grant — from either `ISSUED` or `OVERDUE` — records `returned_at` and settles the deposit. A return on or before the `return_deadline` forfeits nothing; a late return forfeits half of the deposit, rounded half-up to whole cents. The organization's `deposit_held_cents` is released by the full `deposit_cents`, the forfeited portion is recorded as the grant's `deposit_forfeit_cents` and lands in the event invoice's `deposit_charge_cents` with totals recomputed even on a finalized invoice, and a physical key frees its `key_slot` while `keys_issued` decrements by one.

Marking a grant lost — again from `ISSUED` or `OVERDUE` — forfeits the entire deposit, recorded as `deposit_forfeit_cents`, releases the held deposit, and adds the forfeit to the event invoice. A lost physical key permanently shrinks the room's inventory: `key_count` decrements by one, `keys_issued` decrements by one, `keys_lost_total` increments by one, and the retired `key_slot` is never reused, keeping the sum of `key_count` and `keys_lost_total` invariant.

Finally, the system revokes grants still in `REQUESTED` whenever the underlying event is bumped, cancelled, declined, or caught in a suspension cascade, moving them to `REVOKED`. `RETURNED`, `LOST`, and `REVOKED` are the terminal states of the grant lifecycle.

## 4. Endpoint Definitions

Operations that create new resources (an organization, a room, a term, an academic block, a scheduling run, an event reservation, a service order, a service crew, or an access grant) return a `201 Created` status code. Operations that modify an existing resource or drive a state transition — approvals, confirmations, cancellations, payments, the daily-close checkpoint, and the clock adjustment — return a `200 OK` status code. Readers must refer back to §3 for the full request and response semantics of each operation; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the test-driving logical clock | Scheduler |
| POST | `/campus/organizations` | Create an organization | Scheduler |
| GET | `/campus/organizations/{id}` | Get organization details incl. standing and balances | Scheduler, FinanceAdmin, OrgRequester |
| PATCH | `/campus/organizations/{id}` | Update organization contact/insurance fields | Scheduler |
| POST | `/campus/organizations/{id}/reinstate` | Reinstate a suspended organization | Scheduler |
| POST | `/campus/rooms` | Create a room | FacilitiesManager |
| GET | `/campus/rooms/{id}` | Get room details incl. key counters | Scheduler, FacilitiesManager, ServiceCoordinator, FinanceAdmin, OrgRequester |
| PATCH | `/campus/rooms/{id}` | Edit room configuration; capacity cuts bump or block | FacilitiesManager |
| POST | `/campus/rooms/{id}/out-of-service` | Take a room out of service over a window | FacilitiesManager |
| GET | `/campus/rooms/{id}/utilization` | Computed utilization analytics over a window | Scheduler, FacilitiesManager |
| POST | `/campus/terms` | Create a term window | Scheduler |
| GET | `/campus/terms/{id}` | Get term details | Scheduler, FacilitiesManager, ServiceCoordinator, FinanceAdmin, OrgRequester |
| POST | `/campus/academic-blocks` | Create an academic block | Scheduler |
| GET | `/campus/academic-blocks/{id}` | Get an academic block | Scheduler |
| GET | `/campus/academic-blocks` | List academic blocks with filters | Scheduler |
| POST | `/campus/academic-blocks/{id}/unplace` | Remove a block's placement | Scheduler |
| POST | `/campus/scheduling-runs` | Create a draft scheduling run (OCC on term version) | Scheduler |
| GET | `/campus/scheduling-runs/{id}` | Get a scheduling run | Scheduler |
| GET | `/campus/scheduling-runs` | List scheduling runs with filters | Scheduler |
| POST | `/campus/scheduling-runs/{id}/finalize` | Execute the placement pass | Scheduler |
| POST | `/campus/event-reservations` | Create an event request (OCC on room version) | OrgRequester |
| GET | `/campus/event-reservations/{id}` | Get an event; OrgRequester reads own org only | Scheduler, FacilitiesManager, ServiceCoordinator, FinanceAdmin, OrgRequester |
| GET | `/campus/event-reservations` | List events; OrgRequester scoped to own org | Scheduler, FacilitiesManager, ServiceCoordinator, FinanceAdmin, OrgRequester |
| POST | `/campus/event-reservations/{id}/approve` | Approve a request; pins rates and creates the provisional invoice | Scheduler |
| POST | `/campus/event-reservations/{id}/decline` | Decline a request | Scheduler |
| POST | `/campus/event-reservations/{id}/confirm` | Confirm an approved event | OrgRequester |
| POST | `/campus/event-reservations/{id}/cancel` | Cancel an event; tiered fees for client cancels | OrgRequester, Scheduler |
| POST | `/campus/event-reservations/{id}/rebook` | Rebook a bumped event into a new room | Scheduler, OrgRequester |
| POST | `/campus/event-reservations/{id}/check-in` | Check in a confirmed event within its check-in window | OrgRequester, FacilitiesManager |
| POST | `/campus/service-orders` | Attach a service order to an event | OrgRequester |
| GET | `/campus/service-orders/{id}` | Get a service order; OrgRequester reads own org only | ServiceCoordinator, Scheduler, OrgRequester |
| GET | `/campus/service-orders` | List service orders; OrgRequester scoped to own org | ServiceCoordinator, Scheduler, OrgRequester |
| POST | `/campus/service-orders/{id}/quote` | Quote or re-quote a service order | ServiceCoordinator |
| POST | `/campus/service-orders/{id}/approve` | Approve a quote | OrgRequester |
| POST | `/campus/service-orders/{id}/request-revision` | Send a quote back for revision | OrgRequester |
| POST | `/campus/service-orders/{id}/schedule` | Assign a crew to an approved order | ServiceCoordinator |
| POST | `/campus/service-orders/{id}/fulfill` | Mark a scheduled order fulfilled | ServiceCoordinator |
| POST | `/campus/service-orders/{id}/cancel` | Cancel a non-terminal service order | ServiceCoordinator, OrgRequester |
| POST | `/campus/service-crews` | Create a service crew | ServiceCoordinator |
| GET | `/campus/invoices/{id}` | Get an invoice; OrgRequester reads own org only | FinanceAdmin, Scheduler, OrgRequester |
| GET | `/campus/invoices` | List invoices; OrgRequester scoped to own org | FinanceAdmin, Scheduler, OrgRequester |
| POST | `/campus/invoices/{id}/pay` | Pay toward an invoice | OrgRequester, FinanceAdmin |
| POST | `/campus/invoices/{id}/waive` | Waive part of an invoice (segregation of duties) | FinanceAdmin |
| POST | `/campus/invoices/{id}/refund` | Refund against paid amounts | FinanceAdmin |
| POST | `/campus/access-grants` | Request key/card access for an event | OrgRequester, FacilitiesManager |
| GET | `/campus/access-grants/{id}` | Get an access grant; OrgRequester reads own org only | FacilitiesManager, Scheduler, OrgRequester |
| GET | `/campus/access-grants` | List access grants; OrgRequester scoped to own org | FacilitiesManager, Scheduler, OrgRequester |
| POST | `/campus/access-grants/{id}/issue` | Issue a key/card for a confirmed event | FacilitiesManager |
| POST | `/campus/access-grants/{id}/return` | Return an issued/overdue grant | FacilitiesManager |
| POST | `/campus/access-grants/{id}/mark-lost` | Mark an issued/overdue grant lost | FacilitiesManager |
| POST | `/campus/ops/daily-close` | Apply all clock-driven transitions in pinned order | Scheduler |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_DURATION_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_SERVICE_WINDOW_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_BLOCK_WINDOW_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INSURANCE_INVALID` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ORG_SUSPENDED` | 409 Conflict |
| `ERR_TERM_PRIORITY_LOCKED` | 409 Conflict |
| `ERR_CONFIRM_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ROOM_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FEATURE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_CATEGORY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_SHIFT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_NO_KEYS_AVAILABLE` | 409 Conflict |
| `ERR_ACCESS_GRANTS_OUTSTANDING` | 409 Conflict |
| `ERR_ROOM_EDIT_BLOCKED` | 409 Conflict |
| `ERR_ROOM_BLOCKED` | 409 Conflict |
| `ERR_TERM_ALREADY_FINALIZED` | 409 Conflict |
| `ERR_PREPAYMENT_REQUIRED` | 402 Payment Required |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |

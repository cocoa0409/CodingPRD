# On-Call Emergency Maintenance Rotation API — Product Requirements Document

## 1. Introduction

Apartment communities live or die by how they handle the 2 a.m. phone call. A gas leak, a burst riser, a failed furnace in January — each demands that the right on-call technician be reached, dispatched, and documented, that after-hours vendor spend be authorized within firm fiscal limits, and that displaced residents be relocated and the incident settled with the insurance carrier on deadline. Behind every one of those calls sits a compensation problem as well: standby hours and callback minutes must be priced correctly, fatigue must be managed so the same technician is not dispatched past safe limits, and the weekly pay run must reconcile it all.

This document specifies the On-Call Emergency Maintenance Rotation API, the system of record for that entire workflow. It governs the rotation schedule and its on-call pay differentials; call intake, triage against true-emergency criteria, and dispatch against response-time targets with escalation to supervision; after-hours vendor authorizations under layered spending caps; temporary mitigation and the follow-up work orders it spawns; relocation of residents when a unit is declared uninhabitable; incident documentation with insurance notification deadlines; and fatigue management with next-day scheduling consequences. All operations are evaluated against a controllable logical clock so that timers, windows, and pay periods behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). A request whose role is not in the endpoint's allowed set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled as follows:

- `PropertyAdmin` — the property operations administrator. This role manages technicians, units, vendors, rotation shifts, and pay periods, holds unlimited vendor-authorization capacity, and operates the logical clock and escalation checkpoint. When `X-User-Role` is `PropertyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it nowhere on technician-keyed fields — for example, when a `PropertyAdmin` approves a vendor authorization or a relocation case, the corresponding `authorized_by_technician_id` or `approved_by_technician_id` is left null — and it is never compared to any entity's `id`.
- `Dispatcher` — the call-intake and triage operator who dispatches on-call technicians and closes mitigated tickets. When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.
- `OnCallTechnician` — a technician currently covering on-call shifts. When `X-User-Role` is `OnCallTechnician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's foreign-key field to `X-User-ID`. Technician-self actions (arriving on scene, mitigating, beginning an assigned work order, starting or completing one's own shift, submitting or revising one's own incident record) reject a mismatched `X-User-ID` with `ERR_NOT_ASSIGNED_TECHNICIAN` (HTTP 403).
- `MaintenanceSupervisor` — a supervising technician who handles escalations, approves relocations and vendor spend, assigns and verifies work, and reviews incident records. When `X-User-Role` is `MaintenanceSupervisor`, `X-User-ID` is again the `id` of the acting `Technician`, with the same ownership-comparison semantics. In addition, the backing `Technician` row must carry `capability` equal to `SUPERVISOR`; a `MaintenanceSupervisor` request whose technician row lacks that capability is rejected with `ERR_NOT_SUPERVISOR_CAPABLE` (HTTP 403).
- `Vendor` — an external trade vendor that submits invoices against its own authorizations and completes vendor-engaged work orders. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`; a vendor action whose `X-User-ID` does not match the `vendor_id` on the authorization in question is rejected with `ERR_VENDOR_MISMATCH` (HTTP 403).

Two segregation-of-duties rules also live at this layer and are detailed in §3: a technician authorizing vendor spend they themselves requested above the self-authorization cap is rejected with `ERR_SELF_AUTHORIZATION_FORBIDDEN` (HTTP 403), and a relocation decision or vendor-authorization rejection executed by the same party who proposed it is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every timestamp the system assigns — intake stamps, dispatch stamps, deadline computations, pay-period boundary checks — reads from a server-held **logical clock**, never from wall time. Before any operator intervention, the logical clock starts at exactly `2026-08-01T00:00:00Z`. A `PropertyAdmin` may set the clock by supplying a `to_iso8601` instant; the operation returns the resulting time as `now_iso8601`, and the clock never falls back to wall time afterward. Throughout this document, the word "now" always refers to the logical clock's current instant.

### 2.5. Common Resource Properties

All primary resources carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource and underpins optimistic concurrency control.

`PayStatement` is the single exception. Because statements are emitted once at period close and never mutated thereafter, a `PayStatement` carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. Every mutation described in §3 — including automatic cascade mutations such as a work order being placed on hold by a relocation approval — refreshes the affected resource's `updated_at` and, where the resource carries one, increments its `version`.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are integer cents — rates, caps, authorized amounts, invoice totals, and pay figures alike — and all money arithmetic produces integer cents. Wherever a calculation must round, it rounds **half up** to whole cents, and the rounding points are pinned per calculation: per-shift standby pay is rounded individually at shift completion; final period standby pay is accumulated without intermediate rounding and rounded once at the end; vendor invoice lines are rounded per line before summing; the relocation overage nightly rate is rounded once before being multiplied by overage nights. Summing first and rounding later yields different cents and is not compliant. Differentials and markups expressed in basis points are divided by ten thousand to obtain the fractional multiplier — a differential of 1500 basis points means 15 percent.

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the API are guarded by optimistic concurrency control, each requiring a non-optional version field carrying the caller's last observed `version` of the target resource:

- Dispatching (or re-dispatching) a call ticket requires `expected_call_ticket_version` in the request body. If the value does not match the ticket's current `version` — for instance because another writer has advanced the ticket since the dispatcher last read it — the request is rejected with `ERR_STALE_CALL_TICKET_VERSION` (HTTP 412).
- Transferring a published rotation shift requires `expected_rotation_shift_version`. Because a transfer leaves the shift's `status` untouched, a second transfer issued after a completed one observes identical state; only the version check distinguishes a stale view. A mismatch with the shift's current `version` is rejected with `ERR_STALE_ROTATION_SHIFT_VERSION` (HTTP 412).

Endpoints not listed above do not accept a version field at all.

### 2.8. Nested Resource Retrieval and Reference Existence

Some operations are addressed through a parent resource in the path — for example, proposing vendor spend or creating the incident record under a specific call ticket. For every such request, path identifiers are validated for existence strictly left to right: the first identifier that does not correspond to an existing resource determines the 404 response. A vendor-spend proposal under a nonexistent ticket therefore fails with `ERR_CALL_TICKET_NOT_FOUND` before any body validation runs. Existence failures map to the resource-specific errors `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`, `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`, `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`, `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each with HTTP 404. Identifiers carried in the request body as foreign-key references are validated for existence under the same tier.

### 2.9. Validation Priority Order

When several validations could reject the same request, the system evaluates them in a single global order, and the earliest failing tier determines the error returned:

1. **Authentication context** — presence of the headers and a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role and scope authorization** — role membership for the endpoint, supervisor capability, technician-self and vendor-self identity, and segregation-of-duties scoping (the 403 family).
3. **Existence** — path identifiers left to right, then body foreign keys (the 404 family).
4. **Request body shape** — required fields present, enum values valid, datetimes and integers well-formed, window ends strictly after their starts, amounts strictly positive (`ERR_INVALID_REQUEST`, HTTP 400).
5. **State and stale version** — the target resource must be in a state that permits the requested transition (the per-entity invalid-state errors, HTTP 409), with the two optimistic-concurrency rejections riding at this tier as HTTP 412.
6. **Fatigue and rest** — the technician must not be rest-blocked at the reference time (`ERR_FATIGUE_REST_REQUIRED`) on dispatch, shift publication, shift transfer, and work-order assignment.
7. **Cross-entity and referential gates** — the ticket is a true emergency, the technician is on an active shift, the vendor is active, the unit was declared uninhabitable before relocation, related records exist and are in the required states, insurance decisions precede finalization, and pay-period prerequisites hold (the business-referential 409 family, plus `ERR_REFERENTIAL_MISMATCH` at HTTP 422).
8. **Temporal conflicts** — shift overlap, relocation stay overlap, and activation before the stay's start date (HTTP 409).
9. **Uniqueness** — the property-wide unit-number constraint (`ERR_UNIT_NUMBER_EXISTS`, HTTP 409).
10. **Fiscal caps** — the vendor money limits in their pinned order: per-incident vendor limit, then role authorization cap, then per-incident aggregate cap, and the invoice overage ceiling at invoice time (HTTP 402 family).

### 2.10. Interval and Window Semantics

Time windows appear throughout the domain, and each kind has a fixed inclusivity. **Rotation shifts** occupy a half-open interval: the shift covers its `start_at` inclusive and its `end_at` exclusive, so two shifts of the same technician where one ends exactly when the other begins are adjacent, not overlapping. **Pay periods** follow the same half-open convention from `period_start` inclusive to `period_end` exclusive. **Relocation stays**, by contrast, occupy a closed interval: both `start_date` and `end_date` are nights of displacement, and a second approved stay for the same unit that merely shares a boundary date with an existing one is already a conflict. The **fatigue accumulation window** is left-open: callback work counts toward a technician's rolling total when its mitigation instant falls after now minus 168 hours and at or before now. Finally, the **night-pay window** is half-open across midnight: a dispatch time-of-day at or after 22:00 UTC and strictly before 06:00 UTC qualifies as night work.

## 3. Business Logic & Workflows

### 3.1. Staffing the Roster: Technicians, Units, and Vendors

A `PropertyAdmin` onboards each technician by registering a `full_name`, a `capability` of either `TECHNICIAN` or `SUPERVISOR` (the latter gates every `MaintenanceSupervisor` action), a `base_hourly_rate_cents` strictly greater than zero, and an `on_call_differential_bp` in basis points that prices standby and callback work. A new technician starts with `status` `ACTIVE`, a `callback_minutes_168h` of zero, and a null `fatigue_block_until`. Offboarding is one-way: deactivating a technician moves them from `ACTIVE` to `INACTIVE`, increments their `version`, and an attempt to deactivate an already-inactive technician is rejected with `ERR_INVALID_REQUEST`. An inactive technician can no longer be dispatched (dispatch rejects them with `ERR_TECHNICIAN_NOT_ON_SHIFT`), and future shift publication, shift transfer, and work-order assignment to them are blocked; a transfer aimed at an inactive target fails with `ERR_ROTATION_SHIFT_INVALID_STATE`. Anyone but a `Vendor` may read a technician record, which is where the live fatigue fields `callback_minutes_168h` and `fatigue_block_until` are exposed.

Units are registered with a property-wide unique `unit_number` — a duplicate is rejected with `ERR_UNIT_NUMBER_EXISTS` — plus a `building_code`. Every unit carries a `habitability_status` that begins at `HABITABLE` and is flipped only as a side effect of relocation approval and relocation end; there is no direct unit-status edit.

Vendors are registered with a `name`, a `trade` of `PLUMBING`, `HVAC`, `ELECTRICAL`, `GENERAL`, or `RESTORATION`, and a `per_incident_limit_cents` strictly greater than zero that caps any single authorization written against that vendor. A vendor starts `ACTIVE`; suspending one moves it to `SUSPENDED`, increments its `version`, and blocks both new spend proposals and authorizations involving that vendor with `ERR_VENDOR_SUSPENDED`.

### 3.2. Publishing and Running the On-Call Rotation

The rotation schedule is a set of shifts, each naming its owning `technician_id` and a half-open window from `start_at` to `end_at`. Publishing a shift requires the window's end to be strictly after its start, requires the technician to exist, rejects a technician who is rest-blocked at the shift's start with `ERR_FATIGUE_REST_REQUIRED`, and rejects any half-open overlap with that technician's existing `PUBLISHED` or `ACTIVE` shifts with `ERR_SHIFT_OVERLAP` — adjacency, where one shift's `end_at` equals the other's `start_at`, is allowed. A published shift begins in `PUBLISHED` with `needs_coverage` false. The shift list can be filtered by `technician_id` and `status`, alongside the standard `limit` and `offset`.

When the window arrives, the owning technician (or a `PropertyAdmin`) starts the shift, moving `PUBLISHED → ACTIVE`; starting outside the window, or starting a shift that is not `PUBLISHED`, fails with `ERR_ROTATION_SHIFT_INVALID_STATE`, and an `OnCallTechnician` whose `X-User-ID` is not the shift's `technician_id` fails with `ERR_NOT_ASSIGNED_TECHNICIAN`. Once now reaches the shift's `end_at`, completion moves `ACTIVE → COMPLETED` under the same actor rules and computes the shift's pay figures.

Completion prices standby as follows. The shift's duration is its window length in whole minutes. From that, the system subtracts the **callback overlap**: the sum of `callback_minutes` over tickets assigned to the shift's technician whose `dispatched_at` falls inside the shift window (half-open) and whose status is `MITIGATED` or `CLOSED`. The result, floored at zero, is stored as `standby_minutes`. The `provisional_shift_pay_cents` is then the standby minutes divided by sixty, multiplied by the technician's `base_hourly_rate_cents`, and increased by the on-call differential — that is, multiplied by one plus `on_call_differential_bp` divided by ten thousand — with the per-shift result rounded half-up to whole cents. No weekly tier cap is applied at this stage; per-shift rounding at completion is pinned.

A `PUBLISHED` shift can be reassigned by a `PropertyAdmin` or `MaintenanceSupervisor` through a transfer carrying `to_technician_id` and the OCC field described in §2.7. The target must be `ACTIVE` (else `ERR_ROTATION_SHIFT_INVALID_STATE`), must not be rest-blocked at the shift's `start_at` (else `ERR_FATIGUE_REST_REQUIRED`), and must have no overlapping `PUBLISHED` or `ACTIVE` shift of their own (else `ERR_SHIFT_OVERLAP`). A successful transfer rewrites `technician_id`, clears `needs_coverage` to false, and increments the shift's `version`. Cancelling moves `PUBLISHED → CANCELLED` and increments `version`; shifts already started cannot be cancelled.

### 3.3. Call Intake, Triage, Dispatch, and Escalation

Intake begins when a `Dispatcher` (or `PropertyAdmin`) records an emergency call against a `unit_id` with the `caller_name`, `caller_phone`, a `category` of `GAS_LEAK`, `FLOOD`, `NO_HEAT`, `NO_POWER`, `LOCKOUT`, `LEAK_MINOR`, `APPLIANCE`, or `OTHER`, and a free-text `description`. The ticket is stamped with `received_at` from the logical clock and opens in `RECEIVED`. The ticket list can be filtered by `unit_id`, `assigned_technician_id`, `status`, and `category`.

Triage is the `Dispatcher`'s exclusive call and hinges on the `is_true_emergency` flag, and it is only valid from `RECEIVED` (else `ERR_CALL_TICKET_INVALID_STATE`). A call judged a true emergency moves `RECEIVED → TRIAGED`: the flag is stored, `triaged_at` is stamped, and the response target `sla_target_minutes` is assigned from the category — 30 minutes for `GAS_LEAK` or `FLOOD`, 60 minutes for `NO_HEAT` or `NO_POWER`, and 120 minutes for every other category. A call judged non-emergency moves `RECEIVED → DEFERRED` instead, and the system automatically creates a follow-up work order with `priority` `DEFERRED` in `OPEN`, its `unit_id` copied from the ticket. `DEFERRED` is terminal; deferred tickets can never be dispatched, because dispatch's state check admits only `TRIAGED` or `ESCALATED` tickets.

Dispatch assigns an on-call technician to a `TRIAGED` ticket — or re-assigns one in `ESCALATED` — and is performed by a `Dispatcher` or `MaintenanceSupervisor` supplying a `technician_id` and the `expected_call_ticket_version` from §2.7. Validation runs in the global order of §2.9: the ticket's state is confirmed first (`ERR_CALL_TICKET_INVALID_STATE`), then the version check (`ERR_STALE_CALL_TICKET_VERSION`), then the fatigue gate — the technician's `fatigue_block_until` must be null or already past (else `ERR_FATIGUE_REST_REQUIRED`) — and finally the on-shift verification, which requires the technician to be `ACTIVE` and to hold a RotationShift in `ACTIVE` whose window covers now (else `ERR_TECHNICIAN_NOT_ON_SHIFT`). A successful dispatch sets `assigned_technician_id`, stamps `dispatched_at`, resets `escalation_level` to 0, and increments the ticket's `version`. Because escalation timers measure from `dispatched_at`, a re-dispatch also re-bases those timers.

While a ticket sits in `DISPATCHED`, escalation surfaces it to supervision. A manual escalation — available to `Dispatcher`, `OnCallTechnician`, and `MaintenanceSupervisor` — moves `DISPATCHED → ESCALATED` and raises `escalation_level` by one with a floor of one, so a first escalation from level zero lands on level one. Separately, an ops-run checkpoint — a capability restricted to `PropertyAdmin` and `MaintenanceSupervisor` — sweeps all `DISPATCHED` and `ESCALATED` tickets against the logical clock: a `DISPATCHED` ticket whose elapsed time since `dispatched_at` is strictly more than 15 minutes moves to `ESCALATED` at level 1, and an `ESCALATED` ticket still below level 2 whose elapsed time is strictly more than 30 minutes advances to level 2. The checkpoint reports how many tickets were examined as `evaluated_count` and the tickets it moved as `escalated`. Escalation never undoes an assignment; the assigned technician remains responsible for arriving.

Arrival is the assigned technician's own action, valid from either `DISPATCHED` or `ESCALATED` (else `ERR_CALL_TICKET_INVALID_STATE`), and only when `X-User-ID` matches the ticket's `assigned_technician_id` (else `ERR_NOT_ASSIGNED_TECHNICIAN`). Arrival stamps `on_scene_at`, computes `response_minutes` as the whole minutes from `received_at` to `on_scene_at` (partial minutes truncated), and sets `response_breach` to true only when `response_minutes` is strictly greater than `sla_target_minutes` — a response landing exactly on the target is not a breach.

### 3.4. On-Scene Response, Ticket Closure, and Fatigue Management

Once on scene, the assigned technician records temporary mitigation, moving `ON_SCENE → MITIGATED`. The action accepts `mitigation_notes` and a `unit_uninhabitable` flag; it stamps `mitigated_at`, computes `callback_minutes` as the whole minutes from `dispatched_at` to `mitigated_at`, and copies the flag into `unit_declared_uninhabitable`, which later gates both relocation and ticket closure. Mitigation also automatically creates a follow-up work order with `priority` `EMERGENCY_FOLLOWUP` in `OPEN`, its `unit_id` copied from the ticket — this order represents the permanent repair and is deliberately exempt from the relocation hold cascade described in §3.7.

Closure moves `MITIGATED → CLOSED` and is restricted to `Dispatcher` and `MaintenanceSupervisor`. Two gates guard it, after the state check itself: the ticket's incident record must exist and be in `SUBMITTED`, `UNDER_REVIEW`, or `FINALIZED` (a missing record, or one still in `DRAFT` or `RETURNED`, fails with `ERR_INCIDENT_RECORD_NOT_SUBMITTED`), and when `unit_declared_uninhabitable` is true there must exist a relocation case for this ticket in `APPROVED`, `ACTIVE`, or `ENDED` (else `ERR_RELOCATION_UNRESOLVED`).

A successful close stamps `closed_at` and prices the callback. The **billed duration** is the ticket's `callback_minutes`, raised to a two-hour minimum when the actual callback ran shorter. The **effective rate** starts from the assigned technician's `base_hourly_rate_cents` and stacks three multiplicative uplifts, each read from the ticket's `dispatched_at` and `category` — never from arrival or close time: 1.5 when the dispatch time-of-day falls in the night window (at or after 22:00 UTC, strictly before 06:00 UTC); 1.25 when the dispatch fell on a Saturday or Sunday in UTC; and 1.5 when the category is `GAS_LEAK` or `FLOOD`. The `callback_pay_cents` stored on the ticket is the billed minutes divided by sixty, multiplied by the effective rate, rounded half-up to whole cents.

Closure also drives the fatigue cascade, and it is the only place the block is set. The technician's `callback_minutes_168h` is recomputed as the sum of `callback_minutes` over all of that technician's tickets in `MITIGATED` or `CLOSED` whose `mitigated_at` falls inside the left-open rolling window — after now minus 168 hours, up to and including now. If the previous total was below 720 minutes (twelve hours) and the recomputed total is at or above 720 — the boundary is inclusive, so landing exactly on 720 triggers — two things happen at once: the technician's `fatigue_block_until` is set to the triggering ticket's `mitigated_at` plus ten hours, and every `PUBLISHED` rotation shift belonging to that technician whose window overlaps the rest window (its `start_at` before the block's end and its `end_at` after the triggering `mitigated_at`) is flagged `needs_coverage` true. Separately from the crossing rule, every dispatch, shift publication, shift transfer, and work-order assignment performs a live block check against `fatigue_block_until` — at transfer the reference instant is the shift's `start_at`, elsewhere it is now — and rejects a blocked technician with `ERR_FATIGUE_REST_REQUIRED`.

### 3.5. Work Orders: Follow-Ups, Assignment, and Completion

Beyond the two auto-created kinds, a `Dispatcher`, `MaintenanceSupervisor`, or `PropertyAdmin` may raise a `STANDARD` work order against a ticket by supplying `call_ticket_id`, a `title`, and a `description`; the new order opens in `OPEN` with `priority` `STANDARD` and its `unit_id` copied from the originating ticket. An optional `parent_work_order_id` chains the order as a follow-up of an earlier one, but the parent must already be `COMPLETED` or `VERIFIED` — otherwise the create fails with `ERR_FOLLOWUP_PARENT_NOT_FINISHED`. The work-order list supports filtering by `call_ticket_id`, `unit_id`, `parent_work_order_id`, `status`, and `assigned_technician_id`.

Assignment is the `MaintenanceSupervisor`'s action and works from either `OPEN` or `REOPENED` (else `ERR_WORK_ORDER_INVALID_STATE`), writing `assigned_technician_id` and incrementing `version`. The named `technician_id` must reference an `ACTIVE` technician free of any rest block; either failure is rejected with `ERR_FATIGUE_REST_REQUIRED`. A work order can also become assigned without any technician: when a vendor authorization is authorized (§3.6), its linked work order moves `OPEN → ASSIGNED` with `assigned_technician_id` left null, marking the work as vendor-executed.

The assigned technician then begins work, moving `ASSIGNED → IN_PROGRESS`, with the usual self-check (`ERR_NOT_ASSIGNED_TECHNICIAN`). Completion moves `IN_PROGRESS → COMPLETED` and may be reported either by the assigned technician or by an engaged vendor — a `Vendor` actor qualifies when their `X-User-ID` matches the `vendor_id` of an authorization on this work order that is `AUTHORIZED` or `INVOICED` (else `ERR_VENDOR_MISMATCH`). From `COMPLETED`, a supervisor either verifies the work (`COMPLETED → VERIFIED`, terminal) or reopens it (`COMPLETED → REOPENED`, optionally carrying a `reason`), feeding the rework loop back into assignment. Cancellation is available to `MaintenanceSupervisor` and `PropertyAdmin` from `OPEN`, `ASSIGNED`, `ON_HOLD`, or `REOPENED` and lands in `CANCELLED`. The `ON_HOLD` state itself is never entered by direct action — it is produced only by the relocation cascade of §3.7 and unwound when the relocation ends, at which point held orders return to `OPEN` with their `assigned_technician_id` cleared.

### 3.6. After-Hours Vendor Authorizations and Invoicing

When a night's work needs an outside trade, an `OnCallTechnician` or `MaintenanceSupervisor` proposes spend under the incident's ticket by naming a `work_order_id`, a `vendor_id`, and an `amount_cents` ceiling strictly greater than zero. The work order must actually belong to the ticket in the path — a mismatch is rejected with `ERR_REFERENTIAL_MISMATCH` (HTTP 422) — and a `SUSPENDED` vendor blocks the proposal with `ERR_VENDOR_SUSPENDED`. A new authorization opens in `PROPOSED` with `requested_by_technician_id` copied from the caller's `X-User-ID`. The authorization list can be filtered by `call_ticket_id`, `work_order_id`, `vendor_id`, `requested_by_technician_id`, `authorized_by_technician_id`, and `status`.

Authorization is the fiscally sensitive step and may be performed by an `OnCallTechnician`, a `MaintenanceSupervisor`, or a `PropertyAdmin`. Its checks run in a pinned order. The authorization must be `PROPOSED` (else `ERR_VENDOR_AUTHORIZATION_INVALID_STATE`). The segregation-of-duties check comes before any fiscal cap: an actor who is the `requested_by_technician_id` may authorize their own request only when `amount_cents` is no more than 50000 cents ($500.00); self-authorization above that ceiling is rejected with `ERR_SELF_AUTHORIZATION_FORBIDDEN`. The vendor must be `ACTIVE` (else `ERR_VENDOR_SUSPENDED`). Then the three money caps fire in order, each allowing equality: first `amount_cents` must not exceed the vendor's `per_incident_limit_cents` (else `ERR_VENDOR_LIMIT_EXCEEDED`); then `amount_cents` must not exceed the acting role's cap — 50000 cents for an `OnCallTechnician`, 250000 cents ($2,500.00) for a `MaintenanceSupervisor`, and unlimited for a `PropertyAdmin` (else `ERR_ROLE_AUTH_LIMIT_EXCEEDED`); and finally the incident aggregate, the sum of `amount_cents` over the ticket's sibling authorizations already in `AUTHORIZED`, `INVOICED`, or `PAID` plus this `amount_cents`, must not exceed 500000 cents ($5,000.00) (else `ERR_INCIDENT_VENDOR_CAP_EXCEEDED`). A successful authorization records `authorized_by_technician_id` from the caller when the caller is technician-backed — it stays null when a `PropertyAdmin` approves — moves the linked work order `OPEN → ASSIGNED` with no assigned technician, and increments the authorization's `version`.

Rejection, available to `MaintenanceSupervisor` and `PropertyAdmin` with an optional `reason`, moves `PROPOSED → REJECTED` and is forbidden to the requesting technician themself (`ERR_SEGREGATION_OF_DUTIES`). A manual void moves `AUTHORIZED → VOIDED`; as compensation, the linked work order is released `ASSIGNED → OPEN` — but only when no sibling authorization on the same work order remains in `AUTHORIZED` or `INVOICED`. Separately, the relocation cascade of §3.7 voids authorizations that are still `PROPOSED` when their work order is placed on hold; the system path never touches committed ones.

The engaged vendor then invoices against the authorization — a self action, so `X-User-ID` must equal the authorization's `vendor_id` (else `ERR_VENDOR_MISMATCH`), and only from `AUTHORIZED` (else `ERR_VENDOR_AUTHORIZATION_INVALID_STATE`). The invoice carries `lines`, each line a `description`, a `quantity`, and a `unit_cost_cents`, plus an `overhead_markup_bp` in basis points. A line's `quantity` is a positive number and need not be an integer — fractional quantities such as 1.5 are legal, and a non-positive or non-numeric `quantity` is rejected with `ERR_INVALID_REQUEST`. Fractional quantities multiply exactly by their decimal value (1.5 means exactly three halves, not a binary-float approximation). Settlement rounds in pinned order: each line total is `quantity` times `unit_cost_cents` rounded half-up to whole cents; `invoice_subtotal_cents` is the sum of those per-line rounded totals; `invoice_markup_cents` is the rounded subtotal multiplied by `overhead_markup_bp` divided by ten thousand, rounded half-up; and `invoice_total_cents` is the subtotal plus the markup. The invoice is accepted only when `invoice_total_cents` does not exceed the authorization's overage ceiling — `amount_cents` multiplied by 1.10, rounded half-up — with equality allowed; an over-ceiling invoice is rejected with `ERR_INVOICE_EXCEEDS_AUTHORIZATION` and nothing is recorded. Acceptance moves the authorization `AUTHORIZED → INVOICED`. Finally, a `PropertyAdmin` marks an `INVOICED` authorization paid, moving it to `PAID`, terminal.

### 3.7. Resident Relocation for Uninhabitable Units

When mitigation leaves a unit unlivable, an `OnCallTechnician` or `MaintenanceSupervisor` proposes a relocation case naming the `unit_id`, the originating `call_ticket_id`, a `start_date` and `end_date` (midnight UTC timestamps bracketing the first and last nights of displacement, closed-interval), and a `nightly_rate_cents` strictly greater than zero. The proposal is only meaningful for a genuinely uninhabitable unit: the referenced ticket must have been mitigated with `unit_uninhabitable` true (else `ERR_UNIT_NOT_UNINHABITABLE`), and the case's `unit_id` must equal the ticket's own unit (else `ERR_REFERENTIAL_MISMATCH`). The stay must span at least one night — `end_date` strictly after `start_date`, with the whole-day difference stored as `planned_nights` — and the closed interval must not collide with any other `APPROVED` or `ACTIVE` case for the same unit: because both boundaries are inclusive, even a shared boundary date is a conflict, rejected with `ERR_RELOCATION_OVERLAP`. The estimated cost is computed at proposal as `planned_nights` times `nightly_rate_cents` plus a flat administrative fee of 15000 cents ($150.00), stored as `est_cost_cents`. The case opens in `PROPOSED` with `proposed_by_technician_id` copied from the caller. The case list filters by `unit_id`, `call_ticket_id`, `proposed_by_technician_id`, `approved_by_technician_id`, and `status`.

Approval belongs to a `MaintenanceSupervisor` or `PropertyAdmin` who is not the proposer (`ERR_SEGREGATION_OF_DUTIES`), acting on a `PROPOSED` case (else `ERR_RELOCATION_CASE_INVALID_STATE`). Approval records `approved_by_technician_id` — null when the approver is a `PropertyAdmin` — recomputes `est_cost_cents`, increments `version`, and fires a three-link cascade that is the system's largest side effect: the unit's `habitability_status` flips to `UNINHABITABLE`; every work order on that unit in `OPEN` or `ASSIGNED` whose `priority` is not `EMERGENCY_FOLLOWUP` is placed `ON_HOLD` (emergency follow-ups keep moving); and each such held order's still-`PROPOSED` vendor authorizations are moved to `VOIDED`. Rejection, under the same segregation rule, moves `PROPOSED → REJECTED` and stores the supplied `reason` as `reject_reason`. A rejected case is not dead: resubmission by an `OnCallTechnician` or `MaintenanceSupervisor` moves `REJECTED → PROPOSED`, replaces the stay's dates and `nightly_rate_cents`, re-records `proposed_by_technician_id` as the resubmitting actor, recomputes `est_cost_cents`, re-runs the closed-interval overlap check, and increments `version` — while the earlier `reject_reason` is preserved through the cycle.

Once approved, activation moves `APPROVED → ACTIVE` but not before the stay's `start_date` has been reached (else `ERR_BEFORE_START_DATE`); activation is a `MaintenanceSupervisor` duty. Ending the stay, also supervisor-only, moves `ACTIVE → ENDED` and takes an `actual_end_date`. End is blocked while any work order on the unit remains in `OPEN`, `ASSIGNED`, `IN_PROGRESS`, or `REOPENED` — orders sitting `ON_HOLD` are excluded from this check and do not block (else `ERR_WORK_ORDER_INVALID_STATE`). Ending computes `actual_cost_cents`: the actual nights run from `start_date` to `actual_end_date` (at least one); nights beyond `planned_nights` are overage nights, billed each at the nightly rate multiplied by 1.25 with that overage nightly rate rounded half-up once before multiplication; the total is the normal nights times `nightly_rate_cents`, plus the overage nights times the rounded overage rate, plus the same 15000-cent administrative fee. Ending also restores the unit's `habitability_status` to `HABITABLE` and releases every `ON_HOLD` work order on the unit back to `OPEN` with `assigned_technician_id` cleared, then increments the case's `version`.

### 3.8. Incident Documentation and Insurance Notification

Every ticket supports exactly one incident record — a second create against the same ticket is rejected with `ERR_INCIDENT_RECORD_EXISTS`. An `OnCallTechnician` or `MaintenanceSupervisor` creates it under the ticket while the ticket is `ON_SCENE` or `MITIGATED`, supplying a chronological `narrative` and an `estimated_damage_cents` of zero or more. The record opens in `DRAFT` with `created_by_technician_id` copied from the caller. The record list filters by `call_ticket_id`, `created_by_technician_id`, and `status`.

The drafting technician alone submits the record (`DRAFT → SUBMITTED`; a non-creator is rejected with `ERR_NOT_ASSIGNED_TECHNICIAN`). Every transition in the record's lifecycle — submit, begin-review, return, revise, and finalize alike — is valid only from its stated source state; attempting any of them from a different state is rejected with `ERR_INCIDENT_RECORD_INVALID_STATE`. A `MaintenanceSupervisor` then begins review (`SUBMITTED → UNDER_REVIEW`), and from review may either return the record — supplying a `reason` that is stored as `return_reason`, moving `UNDER_REVIEW → RETURNED` — or finalize it. A returned record goes back to its creator through revision: the technician supplies a fresh `narrative` and `estimated_damage_cents`, the record moves `RETURNED → DRAFT`, and its `version` increments, ready for another submit.

Carrier notification is recorded on the record by a `MaintenanceSupervisor` or `PropertyAdmin` supplying the carrier's `claim_number`, which is stored as `insurance_claim_number` alongside an `insurance_notified_at` stamp of now. At that moment the system also sets `insurance_notification_late`: notification is late only when `insurance_notified_at` is strictly later than the parent ticket's `closed_at` plus 24 hours — a notification landing exactly at the deadline is not late.

Finalization (`UNDER_REVIEW → FINALIZED`, terminal) is supervisor-only and carries two gates beyond the state check. The parent ticket must already be `CLOSED` (else `ERR_CALL_TICKET_INVALID_STATE`). And the insurance decision must be complete: when `estimated_damage_cents` is at least 100000 cents ($1,000.00) — equality requires it — a recorded notification is mandatory; below that threshold, finalize still requires either a recorded notification or an `insurance_waived_reason` supplied with the finalize call, which is then stored. Failing either branch is rejected with `ERR_INSURANCE_NOTIFICATION_REQUIRED`.

### 3.9. Payroll Periods and Pay Statements

Compensation settles through pay periods. A `PropertyAdmin` opens one by supplying `period_start` and `period_end`, midnight-UTC instants forming a half-open interval with the end strictly after the start; the period opens in `OPEN`. Statements are not visible until close: the period list and statement reads are available to `PropertyAdmin` and `MaintenanceSupervisor`, and the statement list filters by `pay_period_id` and `technician_id`.

Closing a period is `PropertyAdmin`-only and gated twice after the state check (`ERR_PAY_PERIOD_INVALID_STATE` unless `OPEN`): the period must actually have ended — `period_end` at or before now (else `ERR_PERIOD_NOT_ENDED`) — and no rotation shift whose `start_at` falls inside the period may remain in `PUBLISHED` or `ACTIVE` (else `ERR_OPEN_SHIFTS_IN_PERIOD`), so every in-period shift must first be completed or cancelled.

A successful close emits one `PayStatement` per technician who has at least one `COMPLETED` shift starting inside the period, and computes two pay sections. The **standby section** re-prices that technician's `COMPLETED` shifts with `start_at` in the period — `CANCELLED` shifts, and any still `PUBLISHED` or `ACTIVE`, are excluded entirely — using a chronological tier split. Shifts are processed in ascending `start_at` order, ties broken by ascending `created_at`. A running allowance of 2400 minutes (40 hours) of full-differential standby is tracked: each shift contributes its `standby_minutes` up to the remaining allowance at the full rate — minutes divided by sixty, times `base_hourly_rate_cents`, times one plus `on_call_differential_bp` divided by ten thousand — and any minutes beyond the allowance at half the differential, that is, times one plus `on_call_differential_bp` divided by twenty thousand. The accumulation is exact, with no intermediate rounding, and `standby_pay_final_cents` is the single half-up rounding of the period total — which is why the final figure can legitimately differ from the sum of the per-shift `provisional_shift_pay_cents` values. The statement also records `standby_minutes_total`, the sum of `standby_minutes` over the included shifts. The **callback section** sums, over the technician's `CLOSED` tickets whose `closed_at` falls inside the period, `callback_minutes` into `callback_minutes_total` and the per-ticket `callback_pay_cents` (each already rounded at ticket close) into `callback_pay_final_cents`. The statement's `total_pay_cents` is the standby final plus the callback final. Recall from §2.5 that statements carry `pay_period_id` and `technician_id` and are immutable once emitted — no `updated_at`, no `version`.

## 4. Endpoint Definitions

All endpoints live under the `/v1` mount except the two operations utilities. Creating a new resource returns HTTP 201; reads, state transitions, and all other modifications return HTTP 200. Request bodies, computed fields, side effects, and error conditions are defined by the narratives of §2 and §3 rather than by this table; read endpoints are open to all five roles unless the Authorized Role(s) column narrows them.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/v1/technicians` | Register a technician | PropertyAdmin |
| GET | `/v1/technicians/{technicianId}` | Read a technician (fatigue fields live here) | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| POST | `/v1/technicians/{technicianId}/deactivate` | Deactivate a technician (ACTIVE → INACTIVE); blocks future dispatch, shift publication, transfer, and assignment | PropertyAdmin |
| POST | `/v1/units` | Register an apartment unit; `unit_number` is property-wide unique | PropertyAdmin |
| GET | `/v1/units/{unitId}` | Read a unit | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| POST | `/v1/vendors` | Register a vendor with its per-incident authorization limit | PropertyAdmin |
| GET | `/v1/vendors/{vendorId}` | Read a vendor | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor, Vendor |
| POST | `/v1/vendors/{vendorId}/suspend` | Suspend a vendor (blocks new proposals and authorizations) | PropertyAdmin |
| POST | `/v1/rotation-shifts` | Publish an on-call shift (half-open window; per-technician overlap rejected) | PropertyAdmin, MaintenanceSupervisor |
| GET | `/v1/rotation-shifts` | List shifts; filterable | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| GET | `/v1/rotation-shifts/{rotationShiftId}` | Read a shift | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| POST | `/v1/rotation-shifts/{rotationShiftId}/start` | Technician starts the on-call shift inside its window | OnCallTechnician, PropertyAdmin |
| POST | `/v1/rotation-shifts/{rotationShiftId}/complete` | Complete an ACTIVE shift after its window ends; computes standby minutes and provisional pay | OnCallTechnician, PropertyAdmin |
| POST | `/v1/rotation-shifts/{rotationShiftId}/transfer` | Transfer a PUBLISHED shift to another technician (OCC-guarded) | PropertyAdmin, MaintenanceSupervisor |
| POST | `/v1/rotation-shifts/{rotationShiftId}/cancel` | Cancel a PUBLISHED shift | PropertyAdmin, MaintenanceSupervisor |
| POST | `/v1/call-tickets` | Intake: create an emergency call (`received_at` stamped from the logical clock) | Dispatcher, PropertyAdmin |
| GET | `/v1/call-tickets` | List call tickets; filterable | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor, Vendor |
| GET | `/v1/call-tickets/{callTicketId}` | Read a call ticket | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor, Vendor |
| POST | `/v1/call-tickets/{callTicketId}/triage` | Triage: true emergency → TRIAGED, else DEFERRED (plus an automatic DEFERRED work order) | Dispatcher |
| POST | `/v1/call-tickets/{callTicketId}/dispatch` | Dispatch or re-dispatch an on-call technician (OCC-guarded) | Dispatcher, MaintenanceSupervisor |
| POST | `/v1/call-tickets/{callTicketId}/arrive` | Assigned technician arrives on scene; response time and breach computed | OnCallTechnician |
| POST | `/v1/call-tickets/{callTicketId}/escalate` | Manual escalation to supervision (level raised by one, floor one) | Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| POST | `/v1/call-tickets/{callTicketId}/mitigate` | Assigned technician records temporary mitigation; creates an EMERGENCY_FOLLOWUP work order | OnCallTechnician |
| POST | `/v1/call-tickets/{callTicketId}/close` | Close a mitigated ticket; computes callback pay and runs the fatigue cascade | Dispatcher, MaintenanceSupervisor |
| POST | `/v1/call-tickets/{callTicketId}/vendor-authorizations` | Propose after-hours vendor spend against a ticket | OnCallTechnician, MaintenanceSupervisor |
| GET | `/v1/vendor-authorizations` | List vendor authorizations; filterable | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor, Vendor |
| GET | `/v1/vendor-authorizations/{vendorAuthorizationId}` | Read a vendor authorization | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor, Vendor |
| POST | `/v1/vendor-authorizations/{vendorAuthorizationId}/authorize` | Authorize proposed spend under segregation-of-duties and layered caps; engages the vendor onto the work order | OnCallTechnician, MaintenanceSupervisor, PropertyAdmin |
| POST | `/v1/vendor-authorizations/{vendorAuthorizationId}/reject` | Reject proposed spend (rejecter must differ from requester) | MaintenanceSupervisor, PropertyAdmin |
| POST | `/v1/vendor-authorizations/{vendorAuthorizationId}/void` | Void an AUTHORIZED engagement; releases the work order when no sibling authorization remains engaged | MaintenanceSupervisor, PropertyAdmin |
| POST | `/v1/vendor-authorizations/{vendorAuthorizationId}/invoice` | Vendor submits invoice lines; per-line rounding settlement; ten-percent overage ceiling | Vendor |
| POST | `/v1/vendor-authorizations/{vendorAuthorizationId}/mark-paid` | Mark an invoiced authorization paid | PropertyAdmin |
| POST | `/v1/work-orders` | Create a STANDARD work order, optionally as a follow-up of a finished parent | Dispatcher, MaintenanceSupervisor, PropertyAdmin |
| GET | `/v1/work-orders` | List work orders; filterable | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor, Vendor |
| GET | `/v1/work-orders/{workOrderId}` | Read a work order | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor, Vendor |
| POST | `/v1/work-orders/{workOrderId}/assign` | Assign a work order to a technician | MaintenanceSupervisor |
| POST | `/v1/work-orders/{workOrderId}/begin` | Assigned technician begins work | OnCallTechnician |
| POST | `/v1/work-orders/{workOrderId}/complete` | Mark work complete (assigned technician, or engaged vendor) | OnCallTechnician, Vendor |
| POST | `/v1/work-orders/{workOrderId}/verify` | Supervisor verifies completed work | MaintenanceSupervisor |
| POST | `/v1/work-orders/{workOrderId}/reopen` | Supervisor rejects completed work; rework cycle | MaintenanceSupervisor |
| POST | `/v1/work-orders/{workOrderId}/cancel` | Cancel a non-terminal work order | MaintenanceSupervisor, PropertyAdmin |
| POST | `/v1/relocation-cases` | Propose resident relocation for a unit declared uninhabitable (closed-interval stay) | OnCallTechnician, MaintenanceSupervisor |
| GET | `/v1/relocation-cases` | List relocation cases; filterable | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| GET | `/v1/relocation-cases/{relocationCaseId}` | Read a relocation case | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| POST | `/v1/relocation-cases/{relocationCaseId}/approve` | Approve relocation (approver differs from proposer); fires the unit → work order → vendor authorization cascade | MaintenanceSupervisor, PropertyAdmin |
| POST | `/v1/relocation-cases/{relocationCaseId}/reject` | Reject relocation (rejecter differs from proposer) | MaintenanceSupervisor, PropertyAdmin |
| POST | `/v1/relocation-cases/{relocationCaseId}/resubmit` | Amend and resubmit a REJECTED case | OnCallTechnician, MaintenanceSupervisor |
| POST | `/v1/relocation-cases/{relocationCaseId}/activate` | Activate an approved case on or after its start date | MaintenanceSupervisor |
| POST | `/v1/relocation-cases/{relocationCaseId}/end` | End an active case; computes actual cost; restores the unit; resumes held work orders | MaintenanceSupervisor |
| POST | `/v1/call-tickets/{callTicketId}/incident-record` | Create the ticket's single incident record | OnCallTechnician, MaintenanceSupervisor |
| GET | `/v1/incident-records` | List incident records; filterable (at most one per ticket) | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| GET | `/v1/incident-records/{incidentRecordId}` | Read an incident record | PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor |
| POST | `/v1/incident-records/{incidentRecordId}/submit` | Technician submits the draft record | OnCallTechnician |
| POST | `/v1/incident-records/{incidentRecordId}/begin-review` | Supervisor begins review | MaintenanceSupervisor |
| POST | `/v1/incident-records/{incidentRecordId}/return` | Supervisor returns the record for revision | MaintenanceSupervisor |
| POST | `/v1/incident-records/{incidentRecordId}/revise` | Technician revises a returned record back to DRAFT | OnCallTechnician |
| POST | `/v1/incident-records/{incidentRecordId}/notify-insurance` | Record carrier notification; lateness computed against ticket close plus 24 hours | MaintenanceSupervisor, PropertyAdmin |
| POST | `/v1/incident-records/{incidentRecordId}/finalize` | Finalize after review; requires ticket CLOSED and the insurance decision complete | MaintenanceSupervisor |
| POST | `/v1/pay-periods` | Open a pay period | PropertyAdmin |
| GET | `/v1/pay-periods/{payPeriodId}` | Read a pay period | PropertyAdmin, MaintenanceSupervisor |
| POST | `/v1/pay-periods/{payPeriodId}/close` | Close the period; emits one pay statement per technician (final tiered standby pay plus callback pay) | PropertyAdmin |
| GET | `/v1/pay-statements` | List pay statements; filterable | PropertyAdmin, MaintenanceSupervisor |
| GET | `/v1/pay-statements/{payStatementId}` | Read a pay statement | PropertyAdmin, MaintenanceSupervisor |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default is exactly 2026-08-01T00:00:00Z; the clock never falls back to wall time) | PropertyAdmin |
| POST | `/_ops/evaluate-escalations` | Ops-run checkpoint: escalate tickets whose elapsed time since dispatch exceeds the level thresholds; returns the evaluated count | PropertyAdmin, MaintenanceSupervisor |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions for each error are defined in the §2 and §3 narratives where the guarded workflow lives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_SUPERVISOR_CAPABLE | 403 |
| ERR_NOT_ASSIGNED_TECHNICIAN | 403 |
| ERR_VENDOR_MISMATCH | 403 |
| ERR_SELF_AUTHORIZATION_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_TECHNICIAN_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_VENDOR_NOT_FOUND | 404 |
| ERR_ROTATION_SHIFT_NOT_FOUND | 404 |
| ERR_CALL_TICKET_NOT_FOUND | 404 |
| ERR_WORK_ORDER_NOT_FOUND | 404 |
| ERR_VENDOR_AUTHORIZATION_NOT_FOUND | 404 |
| ERR_RELOCATION_CASE_NOT_FOUND | 404 |
| ERR_INCIDENT_RECORD_NOT_FOUND | 404 |
| ERR_PAY_PERIOD_NOT_FOUND | 404 |
| ERR_PAY_STATEMENT_NOT_FOUND | 404 |
| ERR_CALL_TICKET_INVALID_STATE | 409 |
| ERR_ROTATION_SHIFT_INVALID_STATE | 409 |
| ERR_WORK_ORDER_INVALID_STATE | 409 |
| ERR_VENDOR_AUTHORIZATION_INVALID_STATE | 409 |
| ERR_RELOCATION_CASE_INVALID_STATE | 409 |
| ERR_INCIDENT_RECORD_INVALID_STATE | 409 |
| ERR_PAY_PERIOD_INVALID_STATE | 409 |
| ERR_STALE_CALL_TICKET_VERSION | 412 |
| ERR_STALE_ROTATION_SHIFT_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FATIGUE_REST_REQUIRED | 409 |
| ERR_TECHNICIAN_NOT_ON_SHIFT | 409 |
| ERR_VENDOR_SUSPENDED | 409 |
| ERR_UNIT_NOT_UNINHABITABLE | 409 |
| ERR_REFERENTIAL_MISMATCH | 422 |
| ERR_FOLLOWUP_PARENT_NOT_FINISHED | 409 |
| ERR_INCIDENT_RECORD_EXISTS | 409 |
| ERR_INCIDENT_RECORD_NOT_SUBMITTED | 409 |
| ERR_RELOCATION_UNRESOLVED | 409 |
| ERR_INSURANCE_NOTIFICATION_REQUIRED | 409 |
| ERR_OPEN_SHIFTS_IN_PERIOD | 409 |
| ERR_PERIOD_NOT_ENDED | 409 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_RELOCATION_OVERLAP | 409 |
| ERR_BEFORE_START_DATE | 409 |
| ERR_UNIT_NUMBER_EXISTS | 409 |
| ERR_VENDOR_LIMIT_EXCEEDED | 402 |
| ERR_ROLE_AUTH_LIMIT_EXCEEDED | 402 |
| ERR_INCIDENT_VENDOR_CAP_EXCEEDED | 402 |
| ERR_INVOICE_EXCEEDS_AUTHORIZATION | 409 |

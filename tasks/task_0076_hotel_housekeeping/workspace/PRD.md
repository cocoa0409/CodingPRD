# Hotel Housekeeping API — Product Requirements Document

## 1. Introduction

A modern full-service hotel runs three operational rhythms that constantly cross-talk: the property management system (PMS) booking arriving and departing guests, the housekeeping floor turning rooms over and replenishing minibars, and the engineering and laundry teams keeping fixtures and linen serviceable. When these rhythms drift out of sync — when the PMS believes a room is occupied while housekeeping has cleaned and inspected it as vacant, or when a guest disputes a minibar charge that the folio already shows posted — guest experience degrades, revenue leaks, and shift supervisors burn time reconciling clipboards.

This document specifies the API contract for a hotel-housekeeping platform that consolidates that work into one event-driven backbone. It models the lifecycle of every room across vacant, occupied, dirty, clean, inspected, and out-of-order states; auto-dispatches cleaning tasks to the right housekeeper using a zone-aware workload-balancing selector; orchestrates supervisor inspection with random-sampling and rework loops; charges minibar consumption to guest folios with a strict dispute window and waiver path; routes maintenance tickets to engineering with room-isolation cascades when severity warrants; and tracks linen movements end-to-end from collection through laundry return and loss/damage resolution. Inbound integrations with PMS, payment, engineering, and laundry are first-class endpoints so that external systems become regular event producers, not bolt-on adapters.

The platform is designed for desk staff, supervisors, housekeepers, engineers, and a trusted integration channel — each with a distinct surface area, distinct authority, and a shared audit trail. Concurrency, optimistic-locking, and deterministic-selection guarantees are stated in the spec so that test-time behavior matches production behavior on the first deploy.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the actor, and `X-User-Role`, identifying the actor's role. A request that omits either header, or sends one of them empty, is rejected with `ERR_MISSING_USER_CONTEXT`. A request whose role is not permitted for the requested endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognises exactly five role names. When `X-User-Role` is `Housekeeper`, `X-User-ID` is the `id` of the acting `Housekeeper` entity; ownership checks on any resource that references a `Housekeeper` (in particular, `CleaningTask.assigned_housekeeper_id` for accept, start, and submit, and `Housekeeper.id` itself for a self-toggle of shift status) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Supervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `InspectionRecord.supervisor_id` when a supervisor inspects a submitted task, or as `RoomStatusEvent.actor_id` on manual correction) but does not compare it to any entity's `id`. The same applies to `FrontDesk`: its `X-User-ID` is opaque, used only for audit and event-actor recording. `Engineer` is also opaque — engineering personnel use this role to read room, maintenance, and cleaning-task state, but all engineering mutations actually arrive on the inbound-event channel. `SystemIntegration` is likewise opaque: it represents the trusted inbound channel from PMS, engineering, laundry, and the test clock, and its `X-User-ID` is recorded as the actor identifier on audit entries created from inbound events.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has a minimum of 0. A request with `limit` outside that inclusive range, or with `offset` below zero, is rejected with `ERR_INVALID_PAGINATION`. List endpoints sort results by `created_at` ascending unless an endpoint description states otherwise. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, Versioning, and Optimistic Concurrency

Every resource has a server-minted `id` that is a plain UUID without any type prefix or namespace. Resources that carry the common fields — `Room`, `Housekeeper`, `CleaningTask`, `MinibarItem`, `MinibarConsumption`, `MaintenanceTicket`, `LinenType`, and `LinenMovement` — also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` field that is an integer starting at 1 on creation and incrementing by 1 on every mutation. Subordinate records — `InspectionRecord`, `RoomStatusEvent`, `LinenMovement` as an append-only event, and `AuditLog` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from those entities because they are immutable once written.

`PATCH` endpoints accept an optional `version` field in the request body. When `version` is supplied, the server compares it for strict equality with the current server value and rejects a mismatch with `ERR_VERSION_CONFLICT`; when `version` is omitted, the optimistic-concurrency check is skipped. Whenever a mutation succeeds, `version` increments by one and `updated_at` refreshes to the moment of the write.

### 2.5. Status Codes and Hierarchical Path Validation

Endpoints that create a new resource return HTTP `201 Created`; endpoints that mutate or read an existing resource return HTTP `200 OK`. For any path that nests resource identifiers — for example, a fetch of the inspection record belonging to a particular cleaning task — the server validates path parameters left to right: `roomId` is checked first, followed in order by `taskId`, `ticketId`, `consumptionId`, `movementId`, `housekeeperId`, and `itemId` where applicable. The first identifier that fails to resolve emits its specific not-found error (`ERR_ROOM_NOT_FOUND`, `ERR_TASK_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONSUMPTION_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_HOUSEKEEPER_NOT_FOUND`, `ERR_MINIBAR_ITEM_NOT_FOUND`, `ERR_LINEN_TYPE_NOT_FOUND`, or `ERR_INSPECTION_NOT_FOUND`). Foreign-key references inside a request body (the `room_id` on a cleaning-task or maintenance-ticket creation, the `assigned_housekeeper_id` on reassignment, the `minibar_item_id` on a consumption line, the `linen_type_id` on a linen movement) are validated with the same not-found error codes.

### 2.6. Validation Priority Ordering

When several validation checks could in principle reject a request, the server evaluates them in this fixed order so that the error a client sees is predictable: first the two authentication checks — header presence (`ERR_MISSING_USER_CONTEXT`) and then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`); then path-parameter existence; then foreign-key existence in the request body; then state-machine eligibility for the requested transition (raising the family of state errors enumerated in §5, such as `ERR_TASK_NOT_ASSIGNED`, `ERR_TASK_NOT_ACCEPTED`, `ERR_TASK_NOT_IN_PROGRESS`, `ERR_TASK_NOT_SUBMITTED`, `ERR_TICKET_NOT_REPORTED`, `ERR_TICKET_NOT_DISPATCHED`, `ERR_TICKET_NOT_COMPLETED`, `ERR_CONSUMPTION_NOT_PENDING`, `ERR_CONSUMPTION_NOT_POSTED`, `ERR_CONSUMPTION_NOT_INVESTIGATED`, `ERR_MOVEMENT_NOT_COLLECTED`, `ERR_MOVEMENT_NOT_LOSS_REPORTED`, `ERR_ROOM_NOT_OUT_OF_ORDER`, `ERR_INVALID_ROOM_STATE`, or `ERR_TASK_TERMINAL`); then the business-safety checks (manual-correction target validity and isolating-ticket conflicts); then actor-identity referential checks (such as a non-assignee touching a task); then domain-specific structural and constraint checks on payload shape and content; then temporal-window checks; and finally, when present, the optimistic-concurrency `version` check and pagination bounds. A malformed request body that fails generic structural validation — a missing required field or a value of the wrong type — is rejected with `ERR_INVALID_REQUEST`.

### 2.7. Cascading Side Effects, Audit, and Status Event History

Whenever a mutation succeeds, the affected aggregate's `version` increments and `updated_at` refreshes; this applies equally to cascade-driven mutations, so a single business action can bump several aggregates' versions and timestamps in one transaction. Two append-only logs preserve provenance. `RoomStatusEvent` captures every change of `Room.status`: each entry carries `previous_status` (null only for the room's initial-creation event), `new_status`, a `change_reason` drawn from the closed set `PMS_SYNC`, `TASK_COMPLETED`, `INSPECTION_PASS`, `MAINTENANCE_ISOLATE`, `MAINTENANCE_VERIFY`, `MANUAL_CORRECTION`, and `INITIAL`, an `actor_id` (the requesting `X-User-ID` for human actions, the literal `system` for cascades, or `pms` for PMS-driven changes), and a `correction_note` that is required exactly when `change_reason` is `MANUAL_CORRECTION` and is null otherwise. `AuditLog` captures broader mutations: every entry carries `actor_id` (either the user's `X-User-ID` or the literal `system`, `pms`, `payment`, `engineering`, or `laundry` for inbound events), `actor_role` (the `X-User-Role` value, null for inbound-event actors), `action_type` from the closed set `ROOM_STATUS_CHANGE`, `MINIBAR_CONSUMPTION_POST`, `MINIBAR_CONSUMPTION_DISPUTE`, `MINIBAR_CONSUMPTION_WAIVE`, `MANUAL_CORRECTION`, and `EVENT_INGESTED`, a `subject_entity` naming the affected entity (for example, `Room` or `MinibarConsumption`), a `subject_id` for that entity, and a free-form `detail` JSON object capturing the previous and next values, the changed fields, and any inbound event payload.

### 2.8. Precision, Rounding, and Monetary Discipline

Monetary amounts on minibar charges and linen replacement costs are integer cents. Cleaning durations are integer minutes. Time-tax and synergy calculations apply round-half-up when fractional results occur. The minibar-charge total is rounded on the summed gross, never per line item; the same rule governs the synergy multiplier on the cleaning-task priority bonus stack. Once a minibar consumption advances past `PENDING`, its `gross_amount_cents`, `tax_cents`, and `posted_amount_cents` are immutable, so the folio always reconciles exactly to the moment of posting.

### 2.9. Concurrency Serialization

The system serialises competing writes on the entity each operation mutates. When two supervisors submit an inspection for the same `SUBMITTED` cleaning task at the same instant, exactly one wins; the loser observes that the task has already moved past `SUBMITTED` and receives `ERR_TASK_NOT_SUBMITTED`. When two supervisors attempt to dispatch isolating maintenance tickets against the same room, exactly one wins by being the first to set `Room.out_of_order_ticket_id`; the loser receives `ERR_ROOM_ALREADY_ISOLATED`. When a housekeeper attempts to accept an `ASSIGNED` cleaning task at the same instant a supervisor reassigns it, exactly one operation succeeds and the loser receives `ERR_TASK_NOT_ASSIGNED`. When two attempts to post the same `PENDING` minibar consumption arrive together, the first wins; the loser receives `ERR_CONSUMPTION_NOT_PENDING`. Finally, the optimistic-concurrency `version` mismatch on any `PATCH` endpoint yields `ERR_VERSION_CONFLICT`; the client is expected to re-fetch and retry. All five guarantees are first-writer-wins on the contested field.

### 2.10. Status-Discrepancy Detection

After every PMS-sync event, every manual room-status correction, and every cascade-driven `Room.status` mutation, the server recomputes `Room.discrepancy_flag`. The flag is true exactly when the PMS view and the housekeeping view disagree on occupancy: a room whose `pms_occupancy` is `OCCUPIED` or `DUE_OUT` while its `status` is none of `OCCUPIED_CLEAN`, `OCCUPIED_DIRTY`, or `INSPECTED` is flagged, and conversely a room whose `pms_occupancy` is `VACANT` or `NO_SHOW` while its `status` is one of the three occupied-side statuses is also flagged; in every other combination the flag is false. When the flag flips from false to true, an `AuditLog` entry is appended with `action_type` equal to `EVENT_INGESTED` and a `detail` object whose `alert` key is `STATUS_DISCREPANCY`.

### 2.11. Test Clock

A test-driving capability advances the logical clock by a supplied number of `minutes`. Each advance runs two sweeps: rooms in `INSPECTED` whose elapsed time since the inspection transition is at least the inspected-grace threshold (described in §3.3) progress to `VACANT_CLEAN`; and the early-check-in window on pending and assigned cleaning tasks is re-evaluated, so that tasks whose `early_check_in_at` has just slipped outside the window lose their early-check-in bonus on the next priority computation. The response contains a `now` field naming the new logical clock value.

## 3. Business Logic & Workflows

### 3.1. Room Catalogue and Initial State

A front-desk agent creates a `Room` by supplying its `room_number`, a `zone_code` indicating the housekeeping zone (for example, `FLOOR_12_NORTH`), and a `room_type` drawn from `STANDARD`, `SUITE`, or `PRESIDENTIAL`; `vip_flag` and `pms_occupancy` are optional on creation. The `room_number` is unique across all rooms and is immutable after creation. When `pms_occupancy` is supplied as `VACANT` (or omitted, in which case it defaults to `VACANT`), the new room enters `VACANT_CLEAN`; when it is supplied as `OCCUPIED`, the room enters `OCCUPIED_DIRTY` to reflect that an occupied bed has not yet been turned. Every new room receives an initial `RoomStatusEvent` whose `change_reason` is `INITIAL` and whose `previous_status` is null. `pms_synced_at` is initially null and is set when a PMS sync touches the room thereafter. `last_cleaned_at` is null until the first time the room is inspected with a passing outcome.

### 3.2. PMS Synchronization

The PMS pushes occupancy changes through the inbound-event channel, addressing each event by `room_number` and supplying an `event_type` and a target `pms_occupancy`. A `CHECK_IN` event whose `pms_occupancy` transitions to `OCCUPIED` advances a `VACANT_CLEAN` room to `OCCUPIED_CLEAN`. A `DAILY_TURN` event flips an `OCCUPIED_CLEAN` room to `OCCUPIED_DIRTY` to seed a stayover cleaning. A `CHECK_OUT` event flips an `OCCUPIED_DIRTY` room to `VACANT_DIRTY` and atomically auto-creates a cleaning task with `task_source` equal to `CHECK_OUT` and `expedite_flag` equal to false. An `OCCUPANCY_SYNC` event refreshes `pms_occupancy` and `pms_synced_at` without driving the housekeeping state machine, but still recomputes `discrepancy_flag`. Every PMS-driven status change appends a `RoomStatusEvent` whose `change_reason` is `PMS_SYNC` and whose `actor_id` is `pms`, and an `AuditLog` entry with `action_type` `ROOM_STATUS_CHANGE`.

### 3.3. Cleaning Task Lifecycle and Auto-Dispatch

A cleaning task originates from one of three sources: a check-out flush (auto-created when the PMS reports check-out), a stayover daily turn (auto-created by the daily scheduler or by a PMS daily-turn event), or a manual schedule created by front desk or a supervisor. A manual creation supplies `room_id`, the `task_source`, and optionally `expedite_flag` and `early_check_in_at`. The new task receives `status` `PENDING`, and its `estimated_minutes`, `priority_score`, and `priority_tier` are computed immediately (see §3.4 and §3.5).

If at least one `Housekeeper` is on shift in the room's zone at the moment of creation, the system auto-dispatches the task right away and advances it from `PENDING` to `ASSIGNED`; if no eligible housekeeper is on shift, the task remains `PENDING` until a supervisor triggers a manual dispatch. The selector applied at every dispatch picks the on-shift housekeeper whose `assigned_zone` equals the room's `zone_code` and whose `provisional_workload_minutes` is lowest, with ties broken by `employee_code` in ascending order; if the candidate pool is empty, the task stays `PENDING` and a manual dispatch attempt returns `ERR_NO_ELIGIBLE_HOUSEKEEPER`. Once selected, `assigned_housekeeper_id` is set and the selected housekeeper's `provisional_workload_minutes` is recomputed.

From `ASSIGNED`, the assignee accepts the task (writing `accepted_at`), advancing it to `ACCEPTED`. Acceptance, starting, and submission must all be invoked by the assignee — when `X-User-ID` does not match `assigned_housekeeper_id`, the request is rejected with `ERR_NOT_TASK_ASSIGNEE`. A supervisor may reassign an `ASSIGNED` or `ACCEPTED` task by supplying a `new_housekeeper_id` in the body: the reassignment target must be on shift and must differ from the current assignee, otherwise `ERR_INVALID_REASSIGN_TARGET` is returned; on success the old and new assignees' `provisional_workload_minutes` are both recomputed, `accepted_at` is cleared back to null, and the task moves back to `ASSIGNED`. From `ACCEPTED`, the assignee starting the room transitions the task to `IN_PROGRESS` and records `started_at`. From `IN_PROGRESS`, submitting for inspection transitions to `SUBMITTED`, sets `submitted_at`, and computes `actual_minutes` as the number of minutes between `started_at` and `submitted_at` rounded half-up to a whole minute; the assignee's `realized_workload_minutes` is recomputed at that point as well.

A supervisor's inspection then resolves the task. A passing inspection advances the task to `COMPLETED`; a failing inspection advances it to `CANCELLED` and auto-creates a rework task whose `parent_task_id` is the failed task's id, whose `task_source` is the failed task's original `task_source`, and whose `expedite_flag` is forced to true; that rework task is auto-dispatched immediately. The original assignee's `provisional_workload_minutes` is recomputed in both outcomes. If a room is isolated for maintenance (see §3.7) while one or more of its cleaning tasks are in `PENDING`, `ASSIGNED`, `ACCEPTED`, or `IN_PROGRESS`, those tasks cascade to `CANCELLED` and the affected housekeepers' `provisional_workload_minutes` are recomputed.

The cleaning task's status moves only through this sequence — `PENDING → ASSIGNED → ACCEPTED → IN_PROGRESS → SUBMITTED → COMPLETED` for the success path, `SUBMITTED → CANCELLED` for an inspection failure, and `PENDING / ASSIGNED / ACCEPTED / IN_PROGRESS → CANCELLED` for the room-isolation cascade. Touching a task in `COMPLETED` or `CANCELLED` with a state-changing request is rejected with `ERR_TASK_TERMINAL`.

Once a room reaches `INSPECTED` (driven by a passing inspection on a check-out cleaning), it sits there until the test clock observes that at least the inspected-grace threshold of minutes have elapsed since the inspection — that threshold is 30 minutes — and that `pms_occupancy` is `VACANT`; at that point the room transitions automatically to `VACANT_CLEAN`, ready for the next guest cycle. A passing inspection on a stayover task transitions the room from `OCCUPIED_DIRTY` back to `OCCUPIED_CLEAN` without taking the `INSPECTED` detour. In either outcome `Room.last_cleaned_at` is set to the inspection's `created_at`.

A supervisor may also edit a pending or in-flight task to change its `task_source`, `expedite_flag`, or `early_check_in_at`, optionally passing `version` to lock the update; the server recomputes `estimated_minutes` and `priority_score` (and therefore `priority_tier`) on every such change.

### 3.4. Estimated Duration

A cleaning task's `estimated_minutes` is the base duration for the room's `room_type` plus an overhead that depends on the `task_source`. Base durations are 25 minutes for `STANDARD`, 45 minutes for `SUITE`, and 75 minutes for `PRESIDENTIAL`. Overheads are 15 minutes for a `CHECK_OUT` cleaning, 0 minutes for a `STAYOVER`, and 10 minutes for a `SCHEDULED` task. Recomputation happens on creation and on any edit that changes `task_source`.

### 3.5. Cleaning-Task Priority and Banding

The priority of a cleaning task is computed from a base attributable to its `task_source`, three independent bonuses, and a synergy multiplier when all three bonuses are present. The base is 50 for `CHECK_OUT`, 30 for `STAYOVER`, and 20 for `SCHEDULED`. The VIP bonus is 30 when the parent room's `vip_flag` is true and 0 otherwise; the expedite bonus is 20 when the task's `expedite_flag` is true and 0 otherwise; the early-check-in bonus is 25 when `early_check_in_at` is non-null and the difference between `early_check_in_at` and the current time, expressed in seconds, is between zero and four hours inclusive — that is, when the early-check-in moment is in the future and no further off than the four-hour window — and 0 otherwise. The three bonuses are summed; if all three are strictly greater than zero, the sum is multiplied by a synergy multiplier of 1.20 and the product rounded half-up to a whole number before being added to the base. The final `priority_score` is the base plus the (possibly synergised) bonus sum; the synergy multiplier never touches the base. From `priority_score`, the `priority_tier` is banded with inclusive upper boundaries: a score of at least 100 yields `URGENT`, a score below 100 but at least 70 yields `HIGH`, and a score below 70 yields `NORMAL`. Original (non-rework) tasks pass `task_source` straight into the formula; rework tasks always carry `expedite_flag` true because that field is forced at auto-creation, which can lift a task from `HIGH` to `URGENT` purely on the rework path even if the underlying inputs would not otherwise have done so.

Priority is recomputed on task creation and on any edit that mutates `expedite_flag`, `early_check_in_at`, or `task_source`. The nightly clock advance also re-evaluates the early-check-in window so that a task whose `early_check_in_at` has aged past the four-hour boundary loses the bonus on the next computation.

### 3.6. Workload Balancing and Housekeeper Roster

A supervisor creates a `Housekeeper` by supplying `employee_code`, `display_name`, and `assigned_zone`; `employee_code` is unique across all housekeepers, and `shift_status` defaults to `OFF_SHIFT`. A self-toggle of `shift_status` (where the toggling actor's `X-User-ID` equals the housekeeper's id) is allowed, and a supervisor may also toggle any housekeeper's shift on or off. The roster maintains two workload numbers, both integer minutes. `provisional_workload_minutes` is the sum, over every cleaning task whose `assigned_housekeeper_id` equals the housekeeper's id and whose `status` is one of `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, or `SUBMITTED`, of `estimated_minutes`; this is the number the auto-dispatch selector uses. `realized_workload_minutes` is the sum, over every cleaning task whose `assigned_housekeeper_id` equals the housekeeper's id and whose `status` is `COMPLETED` with `submitted_at` on or after the start of the current UTC day, of `actual_minutes`. Both fields are recomputed at read time so that a fetch of a housekeeper always returns up-to-date numbers, and the difference between them is meaningful: at the same instant, for the same housekeeper, the realized number is strictly less than the provisional number whenever at least one non-completed task is on the roster, and the two numbers must differ whenever such an in-flight task exists.

### 3.7. Maintenance Tickets and Room Isolation

Any housekeeper or supervisor reports a maintenance issue by creating a `MaintenanceTicket` against a room, supplying `room_id`, `reporter_housekeeper_id`, a `category` drawn from `ELECTRICAL`, `PLUMBING`, `HVAC`, `FURNITURE`, `APPLIANCE`, or `OTHER`, a `severity` drawn from `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a free-text `description`. The ticket enters `REPORTED` and the server computes `isolates_room` as true exactly when `severity` is one of `HIGH` or `CRITICAL` — that single field is the gate to the isolation cascade.

A supervisor dispatches a reported ticket by supplying an `engineering_assignee` opaque identifier; the ticket advances to `DISPATCHED` and `engineering_assignee` is stored. If the ticket isolates the room, that dispatch atomically forces the parent room into `OUT_OF_ORDER` from whichever non-isolating status it was in (`VACANT_CLEAN`, `VACANT_DIRTY`, `OCCUPIED_CLEAN`, `OCCUPIED_DIRTY`, or `INSPECTED`), sets `Room.out_of_order_ticket_id` to the ticket's id, cascades every cleaning task on that room whose `status` is `PENDING`, `ASSIGNED`, `ACCEPTED`, or `IN_PROGRESS` to `CANCELLED`, appends a `RoomStatusEvent` whose `change_reason` is `MAINTENANCE_ISOLATE`, and appends an `AuditLog`. The cascade depth — dispatch isolates the room, the room flips, the open cleaning tasks cancel, and every affected housekeeper's `provisional_workload_minutes` is recomputed — is intentional, and the room must be free of any prior isolation: dispatching an isolating ticket against a room whose `out_of_order_ticket_id` is already set to a different ticket is rejected with `ERR_ROOM_ALREADY_ISOLATED`.

Engineering progress arrives on the inbound channel as an `engineering-update` event carrying `ticket_id` and `new_status`: an event with `new_status` of `IN_REPAIR` advances a `DISPATCHED` ticket, and an event with `new_status` of `REPAIR_COMPLETED` advances an `IN_REPAIR` ticket and records `completed_at`. A supervisor then verifies completion: verification advances the ticket to `VERIFIED`, sets `verified_at`, appends an `AuditLog`, and — when the ticket had isolated the room — cascades the room from `OUT_OF_ORDER` back to `VACANT_DIRTY`, clears `Room.out_of_order_ticket_id`, auto-creates a re-clean cleaning task whose `task_source` is `SCHEDULED` and whose `expedite_flag` is true, writes that new task's id into `re_clean_task_id`, and appends a `RoomStatusEvent` whose `change_reason` is `MAINTENANCE_VERIFY`. Alternatively, a supervisor rejects a reported ticket, advancing it to `REJECTED` and appending an `AuditLog`; rejection is terminal alongside `VERIFIED`. Manual room-status correction is forbidden from entering or exiting `OUT_OF_ORDER` (see §3.10).

### 3.8. Inspection, Sampling, and Rework

A supervisor inspects a submitted cleaning task by posting an inspection containing the `outcome` (`PASS` or `FAIL`), a non-empty `checklist_items` array, and optional `notes`. Each entry in `checklist_items` has an `item_code` drawn from a fixed enum set, a `passed` boolean, and an optional `note`. A `PASS` outcome is only valid when every checklist item has `passed` equal to true — submitting `PASS` while at least one item's `passed` is false, or submitting with an empty checklist, is rejected with `ERR_INVALID_INSPECTION_CHECKLIST`. The resulting `InspectionRecord` carries `cleaning_task_id`, a denormalised `room_id` for archival queries, `supervisor_id` taken from the inspecting supervisor's `X-User-ID`, the `checklist_items`, `outcome`, optional `notes`, and a server-set `sampled_flag`.

Sampling is deterministic and computed on the submission, not at random. For each housekeeper, the server counts the chronological sequence number `n` of the submitted task — meaning the count of cleaning tasks belonging to the same `assigned_housekeeper_id` whose `status` is one of `SUBMITTED`, `COMPLETED`, or `CANCELLED`, whose `submitted_at` falls on the current UTC day, and whose `submitted_at` is at or before the inspected task's `submitted_at`, ordered by `submitted_at` ascending with the task's `id` ascending as tie-breaker, making `n` one-indexed from the first daily submission. The `sampled_flag` is true exactly when `n` is an integer multiple of the sample interval — every third submission is sampled — so the first submission of the day is not sampled by the modulo rule. Independently, if the housekeeper's immediately preceding submission today (the one at sequence `n − 1`) was inspected with an outcome of `FAIL`, the `sampled_flag` on the current submission is forced to true regardless of the modulo result.

On a `PASS` inspection, the cleaning task advances to `COMPLETED`, the room state machine advances atomically as described in §3.3 and §3.9, `Room.last_cleaned_at` is set to the inspection's `created_at`, an `AuditLog` is appended, and `provisional_workload_minutes` for the assignee is recomputed. On a `FAIL` inspection, the cleaning task advances to `CANCELLED`, the `InspectionRecord` is persisted with `outcome` `FAIL`, a rework task is auto-created with `parent_task_id` set to the failing task's id, its `task_source` matching the failing task's `task_source`, and `expedite_flag` forced to true; the rework task is auto-dispatched immediately. The original assignee's `provisional_workload_minutes` is recomputed in either branch. Two supervisors who inspect the same `SUBMITTED` task at the same instant serialise on the task's `status`: the first wins, the second receives `ERR_TASK_NOT_SUBMITTED`.

### 3.9. Room Status Progression and Status-Event History

Putting the room state machine together: the cycle for a check-out is `VACANT_CLEAN → OCCUPIED_CLEAN → OCCUPIED_DIRTY → VACANT_DIRTY → INSPECTED → VACANT_CLEAN`, with check-in, daily-turn, check-out, passing inspection, and grace-period sweep driving each step respectively. The stayover cycle is shorter: `OCCUPIED_CLEAN → OCCUPIED_DIRTY → OCCUPIED_CLEAN`, where a passing inspection on a stayover cleaning task moves the room directly back to occupied-clean without visiting `INSPECTED`. The isolation excursion is `(any non-OUT_OF_ORDER state) → OUT_OF_ORDER → VACANT_DIRTY`, driven by an isolating ticket dispatch and a verification. Every transition appends a `RoomStatusEvent` whose `change_reason`, `actor_id`, `previous_status`, and `new_status` reflect the cause, and the chronological history of those events is available as the room's status-event list (ordered by `created_at` ascending). A read of the history list also accepts `limit` and `offset` pagination.

### 3.10. Manual Status Correction

A supervisor may correct a room's status by posting a `new_status` together with a required `correction_note` and an optional `version` for optimistic concurrency. Manual correction is constrained: the room's current `status` must not be `OUT_OF_ORDER`, the supplied `new_status` must not be `OUT_OF_ORDER`, and `new_status` must differ from the current `status`; any of these violations is rejected with `ERR_MANUAL_CORRECTION_INVALID_TARGET`. A successful correction appends a `RoomStatusEvent` whose `change_reason` is `MANUAL_CORRECTION`, whose `correction_note` is preserved verbatim, and whose `actor_id` is the supervisor's `X-User-ID`; an `AuditLog` entry with `action_type` `MANUAL_CORRECTION` is appended, and `Room.discrepancy_flag` is recomputed. Because `OUT_OF_ORDER` is reserved for the maintenance pathway, neither entry into nor exit from that state can ever be expressed as a manual correction; the only legitimate paths in and out of `OUT_OF_ORDER` are the isolating-dispatch and verification transitions described in §3.7.

### 3.11. Minibar Catalogue, Consumption, and Folio Reconciliation

A supervisor creates a `MinibarItem` by supplying `sku_code` (unique across active items), `display_name`, `unit_price_cents`, `par_level`, and `replenishment_threshold`; the item enters `ACTIVE`. Archiving an item flips `status` to `ARCHIVED` and removes it from consumption eligibility. A consumption record is created by a housekeeper at room turn-down or by front desk on guest self-report: the payload carries `room_id`, a `source_type` of either `HOUSEKEEPER` or `GUEST_SELF_REPORT`, a `line_items` array, and an optional `cleaning_task_id` linking to the originating cleaning task (which must be null exactly when `source_type` is `GUEST_SELF_REPORT`). Each line carries a `minibar_item_id` and a `quantity`; `line_items` must be non-empty, every `quantity` must be at least one, and the same `minibar_item_id` must not appear twice in a single record. Violations are rejected with `ERR_INVALID_LINE_QUANTITY` for empty arrays or sub-one quantities, and `ERR_DUPLICATE_MINIBAR_LINE_ITEM` for repeated SKUs. A line that references an archived item is rejected with `ERR_MINIBAR_ITEM_ARCHIVED`. The new consumption enters `PENDING`.

Posting the consumption to the folio is a front-desk action; the request body is empty (the consumption is identified by its path id). On posting, the server computes `gross_amount_cents` as the sum, across every line, of the referenced item's `unit_price_cents` multiplied by the line's `quantity`; computes `tax_cents` as the gross amount multiplied by the minibar tax rate of 0.10 and rounded half-up to a whole cent on that single product (per-line tax-then-sum is incorrect because each line's tax would be rounded independently); and computes `posted_amount_cents` as the gross amount plus the tax. The same archived-item check applies at posting time. The server then emits an outbound `payment-post` event; the returned `folio_reference` is stored on the consumption. A `MINIBAR_CONSUMPTION_POST` audit entry is appended. For every line, the system also checks the replenishment threshold: if the remaining par count for the SKU after this consumption would be at or below the SKU's `replenishment_threshold`, a replenishment trigger is fired (the par count for a SKU is its `par_level` minus the cumulative unreplenished consumption). Once posted, `gross_amount_cents`, `tax_cents`, and `posted_amount_cents` are immutable. Two simultaneous posts on the same `PENDING` consumption serialise on `MinibarConsumption.status`: the first wins, the second receives `ERR_CONSUMPTION_NOT_PENDING`.

A guest dispute is a front-desk action that may only be raised while the consumption is `POSTED` and within a strict 72-hour window measured from `posted_at`. The window is half-open — strictly less than 72 hours — so an attempt at exactly 72 hours is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`; an attempt outside `POSTED` is rejected with `ERR_CONSUMPTION_NOT_POSTED`. The body carries `dispute_note`. The consumption advances to `DISPUTED` and a `MINIBAR_CONSUMPTION_DISPUTE` audit entry is appended. A supervisor then opens an investigation by posting a `finding_note`, advancing the record from `DISPUTED` to `INVESTIGATED`; attempting to investigate a consumption that is not in `DISPUTED` is rejected with `ERR_CONSUMPTION_NOT_DISPUTED`. The supervisor resolves the investigation by supplying `keep_charge`: when `keep_charge` is true the record advances to `RESOLVED` (the folio charge stands) and an audit entry is appended; when `keep_charge` is false the record advances to `WAIVED`, the server emits an outbound `payment-reverse` event reversing `folio_reference` (only valid when the original `posted_amount_cents` is greater than zero), and a `MINIBAR_CONSUMPTION_WAIVE` audit entry is appended. The full lifecycle is `PENDING → POSTED → DISPUTED → INVESTIGATED → {RESOLVED | WAIVED}`. The waiver path preserves a strict invariant: the absolute reversal recorded at resolution exactly equals the `gross_amount_cents` plus `tax_cents` posted on the original folio-post action, so a posted-then-waived charge nets to zero on the folio.

### 3.12. Linen Inventory and Replacement

A supervisor creates a `LinenType` by supplying `code` (unique across active linen types), `display_name`, a `replacement_policy` drawn from `PER_STAY`, `SCHEDULED`, or `ON_REQUEST`, an optional `scheduled_interval_days` (required when `replacement_policy` is `SCHEDULED`, omitted otherwise), `par_per_room`, and `replacement_cost_cents`. When a housekeeper starts cleaning a room, the system determines which linen types need replacing on this visit. For a `PER_STAY` linen, replacement is required when the originating cleaning task's `task_source` is `CHECK_OUT`, or when the room is in `OCCUPIED_DIRTY` and no previous `LinenMovement` exists for the room and linen type. For a `SCHEDULED` linen, the elapsed time since the most recent movement (whose status is `SENT_TO_LAUNDRY`, `RETURNED`, `LOSS_REPORTED`, or `RESOLVED`) is converted to whole days by flooring the seconds-difference divided by 86400; replacement is required when that elapsed-days count is at least `scheduled_interval_days`. Zero elapsed days never triggers a scheduled replacement; the boundary is inclusive on the upper side, not strict-greater. For an `ON_REQUEST` linen, replacement is required when a movement for the same room and linen type exists in `COLLECTED` whose `created_at` is at or after the cleaning task's `created_at`.

A housekeeper records the actual collection by creating a `LinenMovement` with `room_id`, `linen_type_id`, optional `cleaning_task_id`, and `collected_quantity` (must be zero or greater); the new movement enters `COLLECTED`. Creating a movement under a `SCHEDULED` policy before the scheduled interval has elapsed is rejected with `ERR_LINEN_REPLACEMENT_NOT_DUE`. The housekeeper then hands off the collected linen to laundry, which advances the movement to `SENT_TO_LAUNDRY` and copies `collected_quantity` into `sent_to_laundry_quantity`; hand-off requires `collected_quantity` strictly greater than zero. The laundry-return inbound event carries `movement_id`, `returned_quantity`, `loss_quantity`, and `damage_quantity`; the server enforces the invariant that `returned_quantity` plus `loss_quantity` plus `damage_quantity` equals `sent_to_laundry_quantity`, otherwise the event is rejected with `ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH`. When the event is accepted, the movement advances to `RETURNED`; if `loss_quantity` plus `damage_quantity` is strictly greater than zero, the movement transitions further to `LOSS_REPORTED`, otherwise it transitions automatically to `RESOLVED`. A supervisor resolves a `LOSS_REPORTED` movement by invoking the resolution endpoint (no body required): the server computes `folio_charge_cents` as `loss_quantity` plus `damage_quantity` multiplied by the linen type's `replacement_cost_cents`, freezes that field, advances the movement to `RESOLVED`, and emits an outbound `payment-post` event for `folio_charge_cents` only when it is strictly greater than zero. A `LinenMovement` is append-only — it carries only `id` and `created_at` as immutable common metadata.

### 3.13. Audit Log Retrieval

A supervisor reads the audit history by listing audit entries, optionally filtering by `action_type` or `subject_id`. The list paginates by `limit` and `offset` and orders entries by `created_at` ascending. List endpoints elsewhere in the system follow the same pagination and ordering conventions; list endpoints that filter by foreign key accept the relevant id as a query parameter — for example, the cleaning-task list accepts `housekeeper_id`, `room_id`, `status`, and `priority_tier` filters, while the rooms list accepts `status`, `zone`, and `discrepancy_only` filters.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP `201 Created`; endpoints that mutate or read an existing resource return HTTP `200 OK`. Refer back to §3 for the request payload, response payload, and side effects of each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /rooms | Create a Room | FrontDesk |
| GET | /rooms | List rooms (optional `?status=&zone=&discrepancy_only=`) | FrontDesk, Supervisor, Housekeeper, Engineer |
| GET | /rooms/{roomId} | Get a Room | FrontDesk, Supervisor, Housekeeper, Engineer |
| POST | /rooms/{roomId}/correct-status | Manual status correction | Supervisor |
| GET | /rooms/{roomId}/status-events | Status change history (chronological ascending) | FrontDesk, Supervisor, Housekeeper, Engineer |
| POST | /housekeepers | Create a housekeeper | Supervisor |
| GET | /housekeepers | List housekeepers | Supervisor, FrontDesk, Housekeeper, Engineer |
| GET | /housekeepers/{housekeeperId} | Get a housekeeper (with provisional and realized workload) | Supervisor, FrontDesk, Housekeeper, Engineer |
| POST | /housekeepers/{housekeeperId}/shift | Toggle housekeeper on or off shift | Supervisor, Housekeeper |
| POST | /cleaning-tasks | Create a cleaning task (manual) | FrontDesk, Supervisor |
| GET | /cleaning-tasks | List cleaning tasks | FrontDesk, Supervisor, Housekeeper, Engineer |
| GET | /cleaning-tasks/{taskId} | Get a cleaning task | FrontDesk, Supervisor, Housekeeper, Engineer |
| PATCH | /cleaning-tasks/{taskId} | Mutate `task_source`, `expedite_flag`, or `early_check_in_at`; recomputes priority | Supervisor |
| POST | /cleaning-tasks/{taskId}/dispatch | Manual dispatch of a pending task | Supervisor |
| POST | /cleaning-tasks/{taskId}/accept | Housekeeper accepts assigned task | Housekeeper |
| POST | /cleaning-tasks/{taskId}/reassign | Reassign to a different housekeeper | Supervisor |
| POST | /cleaning-tasks/{taskId}/start | Begin cleaning (advances from `ACCEPTED` to `IN_PROGRESS`) | Housekeeper |
| POST | /cleaning-tasks/{taskId}/submit | Submit for inspection | Housekeeper |
| POST | /cleaning-tasks/{taskId}/inspect | Supervisor inspection (`PASS` or `FAIL`) | Supervisor |
| GET | /cleaning-tasks/{taskId}/inspection | Get the inspection record for a task | FrontDesk, Supervisor, Housekeeper, Engineer |
| POST | /maintenance-tickets | File a maintenance ticket | Housekeeper, Supervisor |
| GET | /maintenance-tickets | List maintenance tickets | FrontDesk, Supervisor, Engineer, Housekeeper |
| GET | /maintenance-tickets/{ticketId} | Get a maintenance ticket | FrontDesk, Supervisor, Engineer, Housekeeper |
| POST | /maintenance-tickets/{ticketId}/dispatch | Dispatch ticket to engineering | Supervisor |
| POST | /maintenance-tickets/{ticketId}/verify | Verify completed repair | Supervisor |
| POST | /maintenance-tickets/{ticketId}/reject | Reject the report | Supervisor |
| POST | /minibar-items | Create catalog item | Supervisor |
| GET | /minibar-items | List minibar items | FrontDesk, Supervisor, Housekeeper, Engineer |
| POST | /minibar-items/{itemId}/archive | Archive a minibar item | Supervisor |
| POST | /minibar-consumptions | Record consumption (housekeeper or guest) | Housekeeper, FrontDesk |
| GET | /minibar-consumptions | List consumption records | FrontDesk, Supervisor, Housekeeper |
| GET | /minibar-consumptions/{consumptionId} | Get a consumption record | FrontDesk, Supervisor, Housekeeper |
| POST | /minibar-consumptions/{consumptionId}/post | Post to folio | FrontDesk |
| POST | /minibar-consumptions/{consumptionId}/dispute | Guest dispute | FrontDesk |
| POST | /minibar-consumptions/{consumptionId}/investigate | Supervisor opens investigation | Supervisor |
| POST | /minibar-consumptions/{consumptionId}/resolve | Resolve disputed consumption | Supervisor |
| POST | /linen-types | Create linen type | Supervisor |
| GET | /linen-types | List linen types | FrontDesk, Supervisor, Housekeeper, Engineer |
| POST | /linen-movements | Record collected used linen | Housekeeper |
| GET | /linen-movements | List linen movements | Supervisor, Housekeeper, FrontDesk |
| POST | /linen-movements/{movementId}/handover-laundry | Hand off to laundry | Housekeeper |
| POST | /linen-movements/{movementId}/resolve-loss-damage | Resolve reported loss or damage | Supervisor |
| GET | /audit-logs | List audit log entries | Supervisor |
| POST | /_events/pms-sync | Inbound PMS event (`CHECK_IN`, `CHECK_OUT`, `DAILY_TURN`, `OCCUPANCY_SYNC`) | SystemIntegration |
| POST | /_events/engineering-update | Inbound engineering progress | SystemIntegration |
| POST | /_events/laundry-return | Inbound laundry return | SystemIntegration |
| POST | /_clock/advance | Test-only clock advance | SystemIntegration |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_USER_CONTEXT | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_ROOM_NOT_FOUND | 404 |
| ERR_TASK_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_CONSUMPTION_NOT_FOUND | 404 |
| ERR_MOVEMENT_NOT_FOUND | 404 |
| ERR_HOUSEKEEPER_NOT_FOUND | 404 |
| ERR_MINIBAR_ITEM_NOT_FOUND | 404 |
| ERR_LINEN_TYPE_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_TASK_NOT_ASSIGNED | 409 |
| ERR_TASK_NOT_ACCEPTED | 409 |
| ERR_TASK_NOT_IN_PROGRESS | 409 |
| ERR_TASK_NOT_SUBMITTED | 409 |
| ERR_TASK_TERMINAL | 409 |
| ERR_TICKET_NOT_REPORTED | 409 |
| ERR_TICKET_NOT_DISPATCHED | 409 |
| ERR_TICKET_NOT_COMPLETED | 409 |
| ERR_CONSUMPTION_NOT_PENDING | 409 |
| ERR_CONSUMPTION_NOT_POSTED | 409 |
| ERR_CONSUMPTION_NOT_DISPUTED | 409 |
| ERR_CONSUMPTION_NOT_INVESTIGATED | 409 |
| ERR_MOVEMENT_NOT_COLLECTED | 409 |
| ERR_MOVEMENT_NOT_LOSS_REPORTED | 409 |
| ERR_INVALID_ROOM_STATE | 409 |
| ERR_ROOM_NOT_OUT_OF_ORDER | 409 |
| ERR_MANUAL_CORRECTION_INVALID_TARGET | 409 |
| ERR_ROOM_ALREADY_ISOLATED | 409 |
| ERR_NOT_TASK_ASSIGNEE | 403 |
| ERR_INVALID_REASSIGN_TARGET | 409 |
| ERR_NO_ELIGIBLE_HOUSEKEEPER | 409 |
| ERR_DUPLICATE_MINIBAR_LINE_ITEM | 400 |
| ERR_INVALID_LINE_QUANTITY | 400 |
| ERR_MINIBAR_ITEM_ARCHIVED | 409 |
| ERR_INVALID_INSPECTION_CHECKLIST | 400 |
| ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH | 422 |
| ERR_LINEN_REPLACEMENT_NOT_DUE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_INVALID_PAGINATION | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DISPUTE_WINDOW_EXPIRED | 409 |

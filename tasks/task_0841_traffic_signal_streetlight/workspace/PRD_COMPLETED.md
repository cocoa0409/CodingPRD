# Traffic Signal & Streetlight Maintenance API — Product Requirements Document

## 1. Introduction

Municipal traffic-signal and streetlight networks are unforgiving systems: a dark intersection or a knocked-down signal pole is a live public-safety hazard, and the crews, engineers, and utility coordinators who keep them running each operate from a different corner of the same shared asset inventory. This API is the system of record that ties those corners together. It tracks every physical asset — intersections, poles, the signal heads, controllers, detectors, and streetlights mounted on them — alongside the geographic (GIS) coordinates that let dispatchers find them, and it drives the full maintenance workflow from the moment a fault is reported through triage, field repair, and closeout.

The service coordinates five distinct operator communities against one consistent picture of the field. Dispatchers open and triage outage, malfunction, and knockdown tickets and drive the work-order pipeline; field technicians close out the jobs assigned to their own crews; traffic engineers review and apply signal timing changes; utility coordinators run the locate-and-clear process that must precede any excavation, manage third-party pole attachments, and adjudicate warranty claims; and an administrator owns the physical inventory and the system's logical clock. Because a single field event — a car striking a signal pole, a crew completing a repair — can ripple across device status, intersection posture, crew capacity, and pending engineering reviews, the system's central obligation is to keep every one of those derived facts immediately consistent with the events that cause them.

This document specifies the complete external contract: the resources and their fields, the state machines that govern each workflow, the calculations that produce priority scores, costs, and payouts, and the validation rules — in strict precedence order — that protect the network from unsafe or inconsistent operations.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, a string identifying the acting user, and `X-User-Role`, naming that user's role. A request missing either header, or presenting an `X-User-Role` that is not one of the five recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles are `Admin`, `Dispatcher`, `FieldTech`, `TrafficEngineer`, and `UtilityCoordinator`.

- `Admin` is the inventory and system owner and holds a hierarchical override over the physical catalog: it creates intersections, poles, devices, and crews, decommissions devices, and sets the logical clock. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.
- `Dispatcher` owns the ticket and work-order pipelines and may submit and resubmit timing change requests. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `TrafficEngineer` reviews and decides signal timing changes and may also submit and resubmit them. When `X-User-Role` is `TrafficEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `UtilityCoordinator` owns locate coordination, pole attachments, and warranty claims. When `X-User-Role` is `UtilityCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `FieldTech` is a field crew member and is the one role bound to a persisted entity. When `X-User-Role` is `FieldTech`, `X-User-ID` is the `id` of the acting `Crew`; ownership checks on a work order compare that work order's `crew_id` to `X-User-ID`. A field technician may only complete a work order whose `crew_id` equals their `X-User-ID`; a mismatch is an `ERR_UNAUTHORIZED` (HTTP 403).

All five roles may call every read (GET) endpoint. The precise mapping of roles to write operations is given in the endpoint table of §4.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100. `offset` defaults to 0 and may not be negative. A supplied `limit` or `offset` that is not an integer, or that falls outside those bounds, is rejected with `ERR_VALIDATION` (HTTP 422). Results are always returned sorted by `created_at` in ascending order (oldest first), with ties broken by ascending creation sequence (server insertion order). For every list response, the `meta` object carries `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` in UUID form with no type prefix. Every resource also carries a `created_at` timestamp, expressed as an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created.

All entities in this system — `Intersection`, `Pole`, `Device`, `PoleAttachment`, `Crew`, `Ticket`, `WorkOrder`, `TimingPlanChangeRequest`, `LocateRequest`, and `WarrantyClaim` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. `updated_at` is refreshed on every mutation of the resource, and `version` begins at its initial value and increments by one on each mutation. The `created_at` and `updated_at` timestamps (and the `api_request_timestamp` carried in every response envelope) are stamped from real wall-clock UTC time and are independent of the logical clock. Timestamps that record when workflow events occurred against the logical clock — such as a ticket's `triaged_at` or a request's `decided_at` — are distinct from `updated_at`, are read from the logical clock, and follow the same ISO 8601 UTC format.

### 2.5. The Logical Clock

All time-dependent behavior in this system reads from a server-maintained logical clock rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. An administrator may advance the clock by supplying a target instant `to_iso8601`; the operation returns the new clock value as `current_utc`. SLA windows, locate validity, warranty age, and reopen eligibility are all measured against this logical clock, so tests may drive time forward deterministically.

### 2.6. Optimistic Concurrency on Pole Capacity

Creating a pole attachment is guarded by optimistic concurrency control against its parent `Pole`. A create-attachment request (`POST /pole-attachments`) must include `expected_pole_version` as a required field carrying the client's last observed `version` of the target pole. If that value does not equal the pole's current `version`, the create is rejected with `ERR_STALE_POLE_VERSION` (HTTP 412). Because a prior attachment create or approve on the same pole legitimately advances the pole's `version` (and, on approve, its `committed_load_units`), a create still carrying an earlier version is working from a stale view of remaining capacity and must be refused so it cannot overwrite a change it has not yet observed. No other endpoint takes a version field.

### 2.7. Monetary Precision and Rounding

All dollar amounts — provisional and final work-order costs and warranty payouts — are computed to 2 decimal places using round-half-up. Work-order costs additionally observe a **pinned rounding order** described in §3: each parts line item is rounded to cents individually before the line items are summed, and labor and overhead are each rounded to cents at their own step. Summing raw un-rounded line values and rounding only once at the end ("sum-then-round") is incorrect and must not be used. Crew labor hours and pole load units are integer- or fixed-precision quantities and are aggregated without additional rounding. Priority scores are whole-number integers; posture and coverage variants are categorical.

### 2.8. Referential Integrity and Nested Lookups

The asset model is flat: every collection is addressed at the top level and relationships are expressed by foreign-key fields carried in request bodies, not by URL nesting. When a request supplies path ids and body foreign keys, they are resolved left to right, and the first identifier that does not resolve to an existing resource yields the corresponding not-found error for that resource type (for example `ERR_INTERSECTION_NOT_FOUND`, `ERR_POLE_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ATTACHMENT_NOT_FOUND`, `ERR_TCR_NOT_FOUND`, `ERR_LOCATE_NOT_FOUND`, or `ERR_WARRANTY_NOT_FOUND`), each carrying HTTP 404. Relationships between assets are discovered through filtered list endpoints — for example, listing poles or devices by `intersection_id`, devices by `pole_id`, or work orders by `ticket_id`, `crew_id`, or `locate_request_id`.

### 2.9. Validation Precedence

When more than one rule could reject a request, checks are evaluated in a fixed precedence so the reported `error_id` is deterministic. The order is:

1. Authentication — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the acting role is permitted for the operation, including the `FieldTech` ownership rule on completion, else `ERR_UNAUTHORIZED` (403).
3. Existence — every path id and body foreign key resolves, else the appropriate not-found error (404).
4. Request-body validity — required fields present and correctly typed, enum members valid, and `reported_severity` between 1 and 5 inclusive, else `ERR_VALIDATION` (422).
5. State — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
6. Business safety — excavation scheduling requires a cleared, non-expired locate, and timing-change review or approval requires the intersection not be in `EMERGENCY` posture, else `ERR_LOCATE_NOT_CLEARED`, `ERR_LOCATE_EXPIRED`, `ERR_LOCATE_REQUIRED`, or `ERR_INTERSECTION_EMERGENCY` (409).
7. Business referential — the referenced cross-entity resource is in a usable state (dispatch requires its device not decommissioned; attachment approval requires the pole standing), else `ERR_DEVICE_DECOMMISSIONED` or `ERR_POLE_NOT_STANDING` (409).
8. Temporal occupancy — crew schedule overlap or pole-attachment window conflict, else `ERR_CREW_SCHEDULE_CONFLICT` or `ERR_ATTACHMENT_WINDOW_CONFLICT` (409).
9. Pole load capacity — else `ERR_POLE_LOAD_EXCEEDED` (409).
10. Crew labor budget — else `ERR_CREW_CAPACITY_EXCEEDED` (409).
11. Reopen window — else `ERR_REOPEN_WINDOW_EXPIRED` (409).
12. Ticket-close open-work check — else `ERR_TICKET_HAS_OPEN_WORK` (409).
13. Warranty age — else `ERR_WARRANTY_EXPIRED` (409).
14. Optimistic concurrency on pole version — else `ERR_STALE_POLE_VERSION` (412).

Where several of these could apply to one request, the lower-numbered check is decided first; for instance, an unauthenticated caller is rejected before any existence or state check runs, and a state violation surfaces before a temporal or capacity conflict.

### 2.10. Operational Posture and Cascade Consistency

Each `Intersection` exposes a computed `operational_posture` of `NORMAL`, `DEGRADED`, or `EMERGENCY`, derived solely from the statuses of that intersection's devices that have not been decommissioned. It is recomputed immediately on any device status change belonging to the intersection and on any pole knockdown or restoration. If any of those devices is `KNOCKED_DOWN`, the posture is `EMERGENCY`; otherwise, if any is `OUT_OF_SERVICE` or `UNDER_MAINTENANCE`, the posture is `DEGRADED`; otherwise it is `NORMAL`. Decommissioned devices are excluded from this evaluation entirely.

Because a single field event can touch several resources at once, every cascade described in §3 is applied atomically and immediately: when an operation changes a device's status, the owning intersection's posture is re-derived in the same operation, and any resource whose `version` or `updated_at` is affected is bumped in step. Ledger fields (`committed_load_units`, `available_load_units`, `committed_labor_hours`, `available_labor_hours`) are likewise recomputed the instant an underlying attachment or work order changes state.

## 3. Business Logic & Workflows

### 3.1. Building the Asset Inventory

The administrator seeds the network. An intersection is created with a human-readable `name`, a maintenance `district` code, and its GIS `latitude` and `longitude`. A newly created intersection begins with `operational_posture` of `NORMAL`, an `active_plan_revision` of 0, and `active_cycle_length_sec` and `active_offset_sec` both at 0; these active-plan fields are later overwritten only when a timing change is approved (see §3.6).

Poles are created with a field asset `label`, GIS `latitude` and `longitude`, and a `load_capacity_units` figure describing the total structural and attachment load the pole may carry in abstract load units. A pole may optionally reference the intersection it belongs to via `intersection_id`; a standalone streetlight pole leaves that association empty. A pole starts life `STANDING` with `committed_load_units` at 0, so its `available_load_units` equals its full `load_capacity_units`. A pole is knocked down (`STANDING` to `DOWN`) only as part of a knockdown cascade, and restored to `STANDING` only when the corresponding emergency work is completed.

A device is registered against its owning `intersection_id` and, when it is physically mounted on a pole, a `pole_id` — cabinet controllers and other non-pole-mounted units leave `pole_id` empty. Each device declares its `device_type` (one of `SIGNAL_CONTROLLER`, `SIGNAL_HEAD`, `PED_SIGNAL`, `DETECTOR`, or `STREETLIGHT`), its `criticality` (`CRITICAL`, `STANDARD`, or `LOW`, which later feeds ticket priority), a manufacturer `model`, an `installed_at` in-service date from which warranty age is measured, a `replacement_cost` in dollars, and a `warranty_provider`. A device enters service as `IN_SERVICE`, carries no `last_pm_at` until its first preventive-maintenance or lamp job completes, and, upon creation, triggers a recomputation of its intersection's posture. Over its life a device moves among `IN_SERVICE`, `OUT_OF_SERVICE`, `UNDER_MAINTENANCE`, `KNOCKED_DOWN`, and finally `DECOMMISSIONED`; all of the intermediate transitions are driven automatically by ticket triage and work-order flow, while retirement is an explicit administrative action.

Decommissioning is available to the administrator when a device is either `IN_SERVICE` or `OUT_OF_SERVICE`, and only when no work order for that device is currently in `DRAFT`, `SCHEDULED`, or `DISPATCHED`; retirement moves the device to `DECOMMISSIONED` and recomputes the intersection's posture, which — since decommissioned devices are excluded from the posture evaluation — may relax a `DEGRADED` reading. A crew is created with a `name`, a `specialty` (`SIGNAL`, `LIGHTING`, `LOCATE`, or `GENERAL`), and a `labor_capacity_hours` pool; it begins with `committed_labor_hours` at 0 so that `available_labor_hours` equals the full capacity. At all times a crew's committed and available hours sum to its capacity: `available_labor_hours` is always the `labor_capacity_hours` minus the sum of `estimated_labor_hours` over that crew's work orders currently in `SCHEDULED` or `DISPATCHED`.

### 3.2. Reporting Faults and Triage

A dispatcher opens a ticket against a device, supplying the `device_id`, the reporting `source`, a reporter-assessed `reported_severity`, and a free-text `description`. The `source` is one of `SRC_311` (a public 311 report), `DETECTOR` (an automated detector alarm), or `KNOCKDOWN` (a physical strike). Two optional flags refine the report: `hazard_flag` marks a reported public-safety hazard and defaults to false, and `struck_pole` — meaningful only for a knockdown — defaults to false and, when true, signals that the device's supporting pole was struck. `reported_severity` must be an integer from 1 through 5 inclusive; a value outside that range is an `ERR_VALIDATION` (422). A fresh ticket opens in `OPEN` status with `sla_response_status` of `PENDING`, and its `priority_score`, `priority_band`, `triaged_at`, `response_due`, and `resolution_due` all remain empty until triage runs.

Triage is where a ticket is scored and its downstream cascade fires; it moves the ticket from `OPEN` to `TRIAGED`. Triage is permitted only when the referenced device exists and is not `DECOMMISSIONED`. On triage the system computes the priority score as a capped sum of four contributions. The source contributes 10 points for `SRC_311`, 15 for `DETECTOR`, and 30 for `KNOCKDOWN`. The device's criticality contributes 40 points for `CRITICAL`, 20 for `STANDARD`, and 10 for `LOW`. The reported severity contributes 8 points per severity level (so its 1-to-5 range yields 8 to 40 points). A reported hazard adds a further 25 points, and nothing when the hazard flag is false. These four contributions are summed and then capped at 100, so `priority_score` is the smaller of 100 and the raw total.

The `priority_band` follows from the score with one override. If the score is at least 80 — or if the ticket carries a hazard and the device is `CRITICAL`, which forces the top band regardless of the numeric score — the band is `P1`. Otherwise a score of at least 60 is `P2`, a score of at least 35 is `P3`, and anything below 35 is `P4`. Triage also captures `triaged_at` at the current clock and sets the two SLA deadlines from the band. Response deadlines are 60 minutes for `P1`, 240 minutes for `P2`, 1440 minutes for `P3`, and 4320 minutes for `P4`; resolution deadlines are 240 minutes for `P1`, 1440 minutes for `P2`, 4320 minutes for `P3`, and 10080 minutes for `P4`. `response_due` is `triaged_at` plus the band's response minutes and `resolution_due` is `triaged_at` plus the band's resolution minutes.

The `sla_response_status` is evaluated whenever the ticket is read. Before triage it is `PENDING`. Once triaged, if the ticket is not yet resolved or closed it is `BREACHED` when the logical clock has reached or passed `response_due` — the boundary is inclusive, so at exactly `response_due` the ticket is already `BREACHED` — and `ON_TRACK` otherwise. For a ticket that has reached `RESOLVED` or `CLOSED`, the status is judged against the moment it was resolved: `ON_TRACK` if `resolved_at` is strictly before `response_due`, and `BREACHED` if it is at or after it.

Triage also drives a source-specific cascade on the physical assets. For a non-knockdown ticket (a 311 or detector report), the referenced device moves from `IN_SERVICE` to `OUT_OF_SERVICE` and the intersection's posture is recomputed. A knockdown triage is far more consequential: the device moves to `KNOCKED_DOWN`; if `struck_pole` is set and the device is pole-mounted, that pole's `status` moves to `DOWN`; the intersection's posture recomputes to `EMERGENCY`; every timing change request for that intersection currently in `SUBMITTED` or `UNDER_REVIEW` is automatically suspended (moved to `SUSPENDED`); and an emergency work order is auto-created in `DRAFT` for that ticket and device with a `work_type` of `EMERGENCY`. This emergency posture is the serialization point that blocks new timing reviews and approvals until the field is restored.

### 3.3. Resolving, Reopening, and Closing Tickets

Once repair work has landed, a dispatcher resolves the ticket, moving it from `IN_PROGRESS` to `RESOLVED`. A ticket becomes `IN_PROGRESS` automatically: when a work order linked to it by `ticket_id` is dispatched, a ticket sitting in `TRIAGED` bubbles up to `IN_PROGRESS`. Resolution is permitted only when at least one work order carrying this ticket's id has reached `COMPLETED`; on success the system stamps `resolved_at` at the current clock.

A resolved ticket can be reopened by a dispatcher, which returns it from `RESOLVED` back to `TRIAGED` and re-enters the active pipeline. Reopening is allowed only while the logical clock is within 72 hours of `resolved_at`; once more than 72 hours have elapsed the reopen is rejected with `ERR_REOPEN_WINDOW_EXPIRED`. A successful reopen increments `reopen_count` by one and clears `resolved_at`. Alternatively a resolved ticket is closed, moving it from `RESOLVED` to the terminal `CLOSED` state, but only when no work order linked to it by `ticket_id` is still in `DRAFT`, `SCHEDULED`, or `DISPATCHED`; an attempt to close while such open work remains is rejected with `ERR_TICKET_HAS_OPEN_WORK`.

### 3.4. Work Orders: Costing, Scheduling, Dispatch, and Completion

A dispatcher creates a work order against a device by supplying the `device_id`, the `work_type` (`REPAIR`, `PM_LAMP`, `LED_REPLACEMENT`, `EXCAVATION`, or `EMERGENCY`), an `estimated_labor_hours` figure, and an optional `estimated_parts` list. It may optionally reference the originating ticket via `ticket_id` — standalone preventive-maintenance and emergency jobs leave it empty — and, for excavation work, a `locate_request_id` as discussed in §3.5. The `estimated_parts` list (and, later, `actual_parts`) is an array of line items, each with a `qty` and a `unit_price`. A new work order opens in `DRAFT` with `crew_id`, `scheduled_start`, and `scheduled_end` empty, and its `provisional_cost` is computed immediately from the estimated inputs.

Cost is computed the same way for both the provisional figure at creation and the `final_cost` at completion, differing only in whether estimated or actual inputs feed it, and the rounding order is pinned. First, the labor cost is the hours multiplied by the labor rate of \$95.00 per hour, rounded to two decimal places. Next, each parts line item's cost is the line's `qty` multiplied by its `unit_price`, rounded to two decimal places for that line individually; these per-line rounded values are then summed to give the parts cost. The subtotal is the labor cost plus the parts cost. Overhead is 15 percent of that subtotal, rounded to two decimal places. The final cost is the subtotal plus the rounded overhead. Rounding each line first and then summing is required; summing raw line values and rounding once at the end would produce a different, incorrect figure. The provisional computation uses `estimated_labor_hours` and `estimated_parts` and writes `provisional_cost`; the final computation, run at completion, uses `actual_labor_hours` and `actual_parts` and writes `final_cost`, which diverges from the provisional whenever the actuals differ from the estimates.

Scheduling assigns a crew and time window, moving the work order from `DRAFT` to `SCHEDULED`; the dispatcher supplies `crew_id`, `scheduled_start`, and `scheduled_end`. Several checks guard scheduling in the precedence of §2.9. The referenced crew must exist. If the work is excavation, the locate safety rules of §3.5 apply. The crew must be free across the requested window: no other work order of the same crew in `SCHEDULED` or `DISPATCHED` may have a `[scheduled_start, scheduled_end)` interval — start inclusive, end exclusive — that overlaps the requested one, or the request is rejected with `ERR_CREW_SCHEDULE_CONFLICT`. Finally, the job must fit the crew's remaining budget: `estimated_labor_hours` must not exceed the crew's `available_labor_hours`, else `ERR_CREW_CAPACITY_EXCEEDED`. On a successful schedule the `crew_id`, `scheduled_start`, and `scheduled_end` are recorded and the crew's `committed_labor_hours` rises by `estimated_labor_hours`, which lowers its `available_labor_hours` by the same amount.

Dispatch moves the work order from `SCHEDULED` to `DISPATCHED` and requires that the device is not `DECOMMISSIONED`, else `ERR_DEVICE_DECOMMISSIONED`. On dispatch the device moves to `UNDER_MAINTENANCE` (unless it is currently `KNOCKED_DOWN`, in which case it stays knocked down) and the intersection posture recomputes; additionally, if the work order references a ticket and that ticket is `TRIAGED`, the ticket bubbles up to `IN_PROGRESS`.

Completion is performed by a field technician of the owning crew — the caller's `X-User-ID` must equal the work order's `crew_id`, else `ERR_UNAUTHORIZED` — and moves the order from `DISPATCHED` to the terminal `COMPLETED` state. The technician reports `actual_labor_hours` and an optional `actual_parts` list. Completion computes `final_cost` from those actuals, releases the crew commitment by subtracting `estimated_labor_hours` from `committed_labor_hours` (restoring `available_labor_hours`), returns the device to `IN_SERVICE`, and recomputes the intersection posture, which may drop it from `EMERGENCY` or `DEGRADED` back toward `NORMAL`. If the completed device was `KNOCKED_DOWN` and its supporting pole was `DOWN`, that pole is restored to `STANDING`. When the work is a `PM_LAMP` or `LED_REPLACEMENT` job, the device's `last_pm_at` is stamped at the current clock.

A dispatcher may cancel a work order while it is still `DRAFT` or `SCHEDULED`, moving it to the terminal `CANCELLED` state. Cancelling a `DRAFT` order has no ledger effect, but cancelling a `SCHEDULED` order performs a compensating release: the crew's `committed_labor_hours` is reduced by `estimated_labor_hours`, returning `available_labor_hours` to its pre-schedule value.

### 3.5. Locate Coordination and Excavation Safety

Before any digging, a utility coordinator opens a locate request against an intersection by supplying the `intersection_id`, the `requested_by` name of the requesting utility, and an optional `valid_days`. The clearance remains valid for `valid_days` days from creation, defaulting to 21 days when omitted; the system records `valid_until` as the creation clock plus that many days. A locate request opens `OPEN`, is advanced to `MARKED` when the utility lines have been physically located, and then to `CLEARED` when the coordinator clears it.

Only a `CLEARED` locate that the clock has not yet passed unblocks excavation scheduling. When a work order's `work_type` is `EXCAVATION`, scheduling requires that `locate_request_id` be supplied (else `ERR_LOCATE_REQUIRED`), that the referenced locate be in `CLEARED` status (else `ERR_LOCATE_NOT_CLEARED`), and that the current clock be at or before that locate's `valid_until` (else `ERR_LOCATE_EXPIRED`). These safety checks precede the crew-conflict and capacity checks in the precedence order.

### 3.6. Signal Timing Plan Changes

A dispatcher or a traffic engineer submits a timing change request against an intersection, providing the `intersection_id`, the `proposed_cycle_length_sec`, the `proposed_offset_sec`, and a `rationale`. The request opens in `SUBMITTED` with `revision_count` at 0. A traffic engineer begins review, moving it from `SUBMITTED` to `UNDER_REVIEW`, but only while the intersection is not in `EMERGENCY` posture; a review started against an intersection in emergency is rejected with `ERR_INTERSECTION_EMERGENCY`.

From `UNDER_REVIEW` the request forks three ways under the traffic engineer. Approval moves it to the terminal `APPROVED` state and is likewise blocked while the intersection is in `EMERGENCY` posture (`ERR_INTERSECTION_EMERGENCY`); on approval the proposed plan is applied to the intersection — `active_cycle_length_sec` is set to `proposed_cycle_length_sec`, `active_offset_sec` to `proposed_offset_sec`, `active_plan_revision` is incremented by one, and the intersection's `version` is incremented by one — and the request's `decided_at` is stamped at the current clock. Rejection moves it to the terminal `REJECTED` state and only stamps `decided_at`, applying no change to the intersection. Requesting changes moves it to `CHANGES_REQUESTED` with no side effects, returning it to the submitter.

A `CHANGES_REQUESTED` request is resubmitted by a dispatcher or traffic engineer back to `SUBMITTED`, which increments `revision_count` by one and optionally overwrites `proposed_cycle_length_sec`, `proposed_offset_sec`, and `rationale` from the resubmission body. Separately, when a knockdown cascade drives an intersection into `EMERGENCY`, every one of its requests then in `SUBMITTED` or `UNDER_REVIEW` is automatically moved to `SUSPENDED`. A suspended request can also be resubmitted back to `SUBMITTED`, but only once the intersection is no longer in `EMERGENCY` posture; that resubmission also increments `revision_count` by one.

### 3.7. Pole Attachments and the Load Ledger

A utility coordinator requests a third-party pole attachment by supplying the target `pole_id`, the `attacher_name`, the `mount_zone` (`LOW`, `MID`, or `HIGH` — the vertical band it occupies), the `load_units` it will consume, and the occupancy window `effective_from` and `effective_to` (both inclusive). The request must also carry `expected_pole_version` for the concurrency check described in §2.6. A new attachment opens in `REQUESTED`, and merely creating it advances the pole's `version` by one.

Approving an attachment moves it from `REQUESTED` to `APPROVED` and is guarded by three checks in precedence order. The pole must be `STANDING`, else `ERR_POLE_NOT_STANDING`. No other `APPROVED` attachment on the same pole and the same `mount_zone` may occupy a window within 7 days of this one: the two `[effective_from, effective_to]` windows must be disjoint and additionally separated by at least a 7-day buffer, otherwise the approval is rejected with `ERR_ATTACHMENT_WINDOW_CONFLICT`. Finally the pole must have room: the attachment's `load_units` must not exceed the pole's `available_load_units` — equivalently, the pole's `committed_load_units` plus this attachment's `load_units` must not exceed its `load_capacity_units` — else `ERR_POLE_LOAD_EXCEEDED`. On approval the pole's `committed_load_units` rises by the attachment's `load_units` (recomputing `available_load_units`) and the pole's `version` increments by one. A pole's `committed_load_units` is always the sum of `load_units` over its currently `APPROVED` attachments, and `available_load_units` is `load_capacity_units` minus that sum.

A requested attachment may instead be denied, moving it from `REQUESTED` to the terminal `DENIED` state with no ledger effect. An approved attachment may later be revoked, moving it from `APPROVED` to the terminal `REVOKED` state; revocation is a compensating release that reduces the pole's `committed_load_units` by the attachment's `load_units` (returning `available_load_units` to its pre-approval value) and increments the pole's `version` by one.

### 3.8. Warranty Claims

A utility coordinator files a warranty claim against a device, supplying the `device_id`, a `defect_description`, and optionally the `work_order_id` of the repair that exposed the defect. Coverage is decided at creation from the device's age. The age in whole calendar months is measured from the device's `installed_at` to the current clock. If that age exceeds 60 months the claim is refused with `ERR_WARRANTY_EXPIRED`, since the device is past its warranty term. If the age is at most 12 months, the claim's `coverage_variant` is `FULL` and the `payout_amount` is the device's full `replacement_cost`, rounded to two decimal places. Otherwise — for an age greater than 12 months but not exceeding 60 — the `coverage_variant` is `PRORATED` and the `payout_amount` is the straight-line depreciated value: the `replacement_cost` multiplied by the remaining term, that is by 60 minus the age in months, then divided by 60, rounded to two decimal places. A newly filed claim opens in `SUBMITTED`. A coordinator subsequently either approves it, moving it to the terminal `APPROVED` state, or denies it, moving it to the terminal `DENIED` state; neither decision alters the computed payout.

### 3.9. Reporting

Beyond individual resource reads, the system offers roll-up reporting. An intersection summary returns that intersection's `intersection_id`, its current `operational_posture`, its `device_count` (every device belonging to the intersection, including any that have been decommissioned), its `out_of_service_count` (devices whose status is exactly `OUT_OF_SERVICE`), and its `open_ticket_count` (tickets against those devices whose status is `OPEN`, `TRIAGED`, or `IN_PROGRESS`). A fleet device-availability report returns `total_devices`, `in_service`, `out_of_service`, `knocked_down`, and an `availability_pct`, and may be scoped to a single intersection by supplying an `intersection_id` filter; all four counts exclude `DECOMMISSIONED` devices (so `total_devices` counts every non-decommissioned device, including those `UNDER_MAINTENANCE`, while `in_service`, `out_of_service`, and `knocked_down` count only devices in exactly those statuses), and `availability_pct` is `in_service` divided by `total_devices` multiplied by 100, rounded to two decimal places using round-half-up, and is `0` when `total_devices` is 0. All roll-up reports read the current state and mutate nothing.

## 4. Endpoint Definitions

Resource creation endpoints return HTTP 201 with the created resource; state transitions, reads, reporting, and the clock control all return HTTP 200 with the affected or requested resource. Request bodies, response bodies, and side effects for each endpoint are described in the §3 workflows above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |
| POST | `/intersections` | Create an intersection | Admin |
| GET | `/intersections/{id}` | Get one intersection (with computed posture) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/intersections/{id}/summary` | Rolled-up status for one intersection | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/poles` | Create a pole | Admin |
| GET | `/poles/{id}` | Get one pole | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/poles` | List poles (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/devices` | Create a device | Admin |
| GET | `/devices/{id}` | Get one device | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/devices` | List devices (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/devices/{id}/decommission` | Retire a device from service | Admin |
| POST | `/crews` | Create a maintenance crew | Admin |
| GET | `/crews/{id}` | Get one crew (with committed/available hours) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/pole-attachments` | Request a pole attachment (OCC on the pole) | UtilityCoordinator |
| GET | `/pole-attachments/{id}` | Get one pole attachment | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/pole-attachments` | List pole attachments (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/pole-attachments/{id}/approve` | Approve a pole attachment | UtilityCoordinator |
| POST | `/pole-attachments/{id}/deny` | Deny a pole attachment | UtilityCoordinator |
| POST | `/pole-attachments/{id}/revoke` | Revoke an approved attachment | UtilityCoordinator |
| POST | `/tickets` | Open an outage/malfunction/knockdown ticket | Dispatcher |
| GET | `/tickets/{id}` | Get one ticket (with computed priority and SLA status) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/tickets` | List tickets (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/tickets/{id}/triage` | Triage a ticket (score, SLA, and cascade) | Dispatcher |
| POST | `/tickets/{id}/resolve` | Mark a ticket resolved | Dispatcher |
| POST | `/tickets/{id}/reopen` | Reopen a resolved ticket within the window | Dispatcher |
| POST | `/tickets/{id}/close` | Close a resolved ticket | Dispatcher |
| POST | `/work-orders` | Create a work order | Dispatcher |
| GET | `/work-orders/{id}` | Get one work order | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/work-orders` | List work orders (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/work-orders/{id}/schedule` | Assign a crew and time window | Dispatcher |
| POST | `/work-orders/{id}/dispatch` | Dispatch a scheduled work order | Dispatcher |
| POST | `/work-orders/{id}/complete` | Complete a dispatched work order | FieldTech |
| POST | `/work-orders/{id}/cancel` | Cancel a DRAFT or SCHEDULED work order | Dispatcher |
| POST | `/timing-change-requests` | Submit a signal timing/plan change request | Dispatcher, TrafficEngineer |
| GET | `/timing-change-requests/{id}` | Get one timing change request | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/timing-change-requests` | List timing change requests (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/timing-change-requests/{id}/start-review` | Begin engineering review | TrafficEngineer |
| POST | `/timing-change-requests/{id}/approve` | Approve and apply the proposed plan | TrafficEngineer |
| POST | `/timing-change-requests/{id}/reject` | Reject the request | TrafficEngineer |
| POST | `/timing-change-requests/{id}/request-changes` | Return the request for changes | TrafficEngineer |
| POST | `/timing-change-requests/{id}/resubmit` | Resubmit a CHANGES_REQUESTED or SUSPENDED request | Dispatcher, TrafficEngineer |
| POST | `/locate-requests` | Open a utility locate request | UtilityCoordinator |
| GET | `/locate-requests/{id}` | Get one locate request | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/locate-requests` | List locate requests (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/locate-requests/{id}/mark` | Mark utility lines located | UtilityCoordinator |
| POST | `/locate-requests/{id}/clear` | Clear the locate (unblocks excavation) | UtilityCoordinator |
| POST | `/warranty-claims` | File a warranty claim | UtilityCoordinator |
| GET | `/warranty-claims/{id}` | Get one warranty claim | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| GET | `/warranty-claims` | List warranty claims (filterable) | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |
| POST | `/warranty-claims/{id}/approve` | Approve a warranty claim | UtilityCoordinator |
| POST | `/warranty-claims/{id}/deny` | Deny a warranty claim | UtilityCoordinator |
| GET | `/reports/device-availability` | Fleet availability roll-up | Admin, Dispatcher, FieldTech, TrafficEngineer, UtilityCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INTERSECTION_NOT_FOUND` | 404 |
| `ERR_POLE_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_ATTACHMENT_NOT_FOUND` | 404 |
| `ERR_TCR_NOT_FOUND` | 404 |
| `ERR_LOCATE_NOT_FOUND` | 404 |
| `ERR_WARRANTY_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEVICE_DECOMMISSIONED` | 409 |
| `ERR_LOCATE_REQUIRED` | 409 |
| `ERR_LOCATE_NOT_CLEARED` | 409 |
| `ERR_LOCATE_EXPIRED` | 409 |
| `ERR_INTERSECTION_EMERGENCY` | 409 |
| `ERR_POLE_NOT_STANDING` | 409 |
| `ERR_CREW_SCHEDULE_CONFLICT` | 409 |
| `ERR_ATTACHMENT_WINDOW_CONFLICT` | 409 |
| `ERR_POLE_LOAD_EXCEEDED` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_REOPEN_WINDOW_EXPIRED` | 409 |
| `ERR_TICKET_HAS_OPEN_WORK` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_STALE_POLE_VERSION` | 412 |

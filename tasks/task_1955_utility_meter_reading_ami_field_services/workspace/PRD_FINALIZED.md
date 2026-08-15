# Utility Meter Reading & AMI Field Services API — Product Requirements Document

## 1. Introduction

Utility billing runs on register data, and every billing period is a race between the field force and the calendar. A metering contractor dispatches technicians across foot and vehicle routes to collect handheld reads inside narrow read windows, while an AMI head-end streams remote reads from communicating endpoints continuously. When neither channel produces a value before the window closes, the utility must fall back to statistically defensible estimates — but only so many times in a row before regulator and customer patience runs out. At the same time, meters are physical assets living in hostile environments: dogs and locked gates block access, tamper and theft indications demand evidence-preserving investigation, and aging AMI endpoints silently stop communicating and must be detected, escalated, and swapped under a managed replacement program.

This document specifies the Utility Meter Reading & AMI Field Services API, the system of record a metering contractor uses to run that entire operation. It governs billing-cycle period setup and read-window alignment, route construction and field read capture, read validation and estimation, field-safety hazard flagging, tamper and theft investigations with back-billing, field work orders including meter exchanges and endpoint swaps, replacement campaigns, and periodic operations checkpoints that measure backlog and read-rate performance against a contractual service-level standard. All collections are rooted directly at the API root (for example `/meters`, `/routes`, `/ops-snapshots`). The intended reader is the engineer implementing the service; every behavioral rule in this document is normative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must carry `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five roles, spelled exactly as follows: `MeterOpsAdmin`, `Dispatcher`, `FieldTechnician`, `BillingLiaison`, and `Investigator`. A request missing either header, or presenting a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A caller whose role is not listed for the requested operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); this role screen also covers one parameter-level restriction, the administrative read-correction mode described in §3.3, which is reserved to `MeterOpsAdmin`.

Role semantics deserve precision, because `X-User-ID` means different things under different roles:

- When `X-User-Role` is `FieldTechnician`, `X-User-ID` is the `id` of the acting FieldTechnician entity; ownership checks on any resource that references a FieldTechnician compare the resource's foreign-key field to `X-User-ID`. This is how route start and completion, stop-level field operations, and work-order start and completion verify the caller against the assigned `technician_id`, and it is how a hazard report stamps its `reported_by_technician_id`.
- When `X-User-Role` is `MeterOpsAdmin`, `Dispatcher`, `BillingLiaison`, or `Investigator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `opened_by_user_id` or `closed_by_user_id` on an Investigation — but never compares it to any entity's `id`.

Duties are deliberately segregated. `MeterOpsAdmin` alone registers technicians, accounts, and meters, installs and retires meters, ingests AMI reads, creates billing periods, runs replacement campaigns and operations checkpoints, verifies or reworks completed work orders, and drives the logical clock. `Dispatcher` alone builds routes, assigns and reassigns crews, and creates, dispatches, reschedules, and cancels work orders. `FieldTechnician` executes assigned routes and work orders, captures reads, marks no-reads, skips hazards, and reports or renews hazard flags. `BillingLiaison` alone validates or rejects reads, generates estimates, and finalizes and closes billing periods. `Investigator` alone drives tamper and theft investigations end to end, subject to the segregation-of-duties close gate in §3.6. Window open and close are shared between `BillingLiaison` and `MeterOpsAdmin`; hazard-flag clearing is shared among `FieldTechnician`, `Dispatcher`, and `MeterOpsAdmin`; ordinary read capture is shared between the assigned `FieldTechnician` and `MeterOpsAdmin` acting in correction mode. Every role may use all retrieval endpoints.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Server-Stamped Time

The server maintains a logical business clock rather than reading wall-clock time. Before any clock-setting call has been made, the logical clock starts at `2026-08-01T00:00:00Z`; it never falls back to wall-clock time thereafter. A `MeterOpsAdmin` may advance or set the clock through an admin-only, test-driving capability that accepts a `to_iso8601` instant (an ISO 8601 UTC timestamp) and returns 200. Every server-stamped timestamp reads this clock: resource `created_at` values, a hazard flag's `reported_at`, a work order's `completed_at`, and the timestamps attached to snapshot sweeps. Client-supplied instants such as `read_at` and `snapshot_at` remain the caller's own data, but any rule phrased in terms of "the current date" — opening or closing a read window, for example — is evaluated against the logical clock.

### 2.5. Common Resource Properties

Every primary resource in this API — FieldTechnician, ServiceAccount, Meter, BillingCyclePeriod, Route, RouteStop, MeterRead, HazardFlag, WorkOrder, Investigation, ReplacementCampaign, CampaignEnrollment, and OpsSnapshot — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T06:00:00.123Z`), recording when the resource was first created; it reads the logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including modifications applied automatically by the system cascades described throughout this document. Selected writes use this field for optimistic concurrency control per §2.7.

No resource type is exempt: all thirteen carry the full quartet, and any mutation — client-driven or cascaded — refreshes `updated_at` and increments `version` on each resource it touches.

### 2.6. Request Validation Discipline and Evaluation Order

Every request is checked against a fixed validation ladder. When several checks could reject the same call, the server surfaces the error from the earliest applicable rung — the ordering below is normative, not illustrative.

The ladder opens with context checks. First, the presence and well-formedness of the `X-User-ID` and `X-User-Role` headers (failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400). Second, role authorization: the caller's role must be listed for the endpoint, and the read-correction mode (`correction` set to true) counts as a role restriction of its own, reserved to `MeterOpsAdmin` (`ERR_FORBIDDEN_FOR_ROLE`, HTTP 403). Third, request-body shape: required fields present, enum membership, and type sanity, including the period date-ordering rule and the back-bill array-length rule (`ERR_INVALID_REQUEST` at HTTP 400, or `ERR_WINDOW_DATE_ORDER` / `ERR_BACKBILL_INPUT_MISMATCH` at HTTP 422). Fourth, ownership on field operations: on route start and completion, stop read capture, mark-no-read, skip-hazard, and work-order start and completion, the caller must be the assigned technician (`ERR_NOT_ASSIGNED_TECHNICIAN`, HTTP 403).

Existence checks follow. Fifth, path resource identifiers must exist, validated in left-to-right order along the path; the first missing identifier yields `ERR_NOT_FOUND` (HTTP 404). Sixth, body-referenced entities — `technician_id`, `meter_id`, `hazard_flag_id`, period identifiers, `new_meter_id`, and their kin — must exist (`ERR_REFERENCED_ENTITY_NOT_FOUND`, HTTP 404). Seventh, the optimistic-concurrency check on the three version-guarded writes (`ERR_STALE_VERSION`, HTTP 412; see §2.7).

Only then do domain state gates engage, in this relative order: stop actionability (`ERR_STOP_NOT_ACTIONABLE`, HTTP 409) is evaluated before the generic state-machine gate so that stop-state failures surface as domain-specific errors; the generic gate follows (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — including `ERR_ROUTE_NOT_REASSIGNABLE` when reassignment is attempted from a route that is not `ASSIGNED`); then the route-in-progress requirement for stop field operations (`ERR_ROUTE_NOT_IN_PROGRESS`, HTTP 409); then the period window gates (`ERR_READ_WINDOW_NOT_OPEN` and `ERR_READ_WINDOW_STILL_OPEN`, HTTP 409).

Safety screens come next: the active-hazard block on read capture (`ERR_ACTIVE_HAZARD_BLOCKS_READ`, HTTP 422), the active-flag requirement for hazard skips (`ERR_SKIP_REQUIRES_ACTIVE_HAZARD`, HTTP 409), and the evidence-preservation hold on meters under investigation (`ERR_EVIDENCE_PRESERVATION_HOLD`, HTTP 409). Temporal business rules follow: the `read_at` window check (`ERR_READ_OUTSIDE_WINDOW`, HTTP 422), the route-schedule window check (`ERR_ROUTE_OUTSIDE_READ_WINDOW`, HTTP 422), and technician shift-window conflicts (`ERR_TECHNICIAN_WINDOW_CONFLICT`, HTTP 409).

Business constraints close the middle of the ladder: register rollback (`ERR_READ_ROLLBACK`, HTTP 422); meter installation and swap rules (`ERR_ACCOUNT_HAS_INSTALLED_METER` and `ERR_METER_NOT_AVAILABLE_FOR_INSTALL` at HTTP 409, `ERR_METER_NOT_INSTALLED_AT_ACCOUNT` at HTTP 409, `ERR_METER_NOT_AMI` at HTTP 422); uniqueness (`ERR_DUPLICATE_ACCOUNT_NUMBER` and `ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409); estimate eligibility (`ERR_ESTIMATE_CAP_REACHED` and `ERR_INSUFFICIENT_READ_HISTORY`, HTTP 409); account lifecycle gates (`ERR_ACCOUNT_NOT_ACTIVE`, `ERR_ACCOUNT_HAS_OPEN_INVESTIGATION`, and `ERR_ACCOUNT_HAS_OPEN_WORK`, HTTP 409); technician lifecycle gates (`ERR_TECHNICIAN_NOT_ACTIVE` and `ERR_TECHNICIAN_HAS_OPEN_WORK`, HTTP 409); and the one-open-investigation-per-meter rule (`ERR_INVESTIGATION_ALREADY_OPEN`, HTTP 409).

Three terminal groups apply last, each with its own pinned intra-group order. Campaign enrollment checks run the batch quota first — the entire batch is rejected atomically when it would exceed remaining capacity (`ERR_CAMPAIGN_QUOTA_EXCEEDED`, HTTP 409) — then per-meter eligibility (`ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN`, HTTP 409), then duplicate enrollment (`ERR_METER_ALREADY_ENROLLED`, HTTP 409). Aggregate gates count unresolved stops before checking billable-read coverage (`ERR_CYCLE_HAS_UNRESOLVED_STOPS` ahead of `ERR_ACCOUNT_MISSING_BILLABLE_READ`, both HTTP 409; route completion fails as `ERR_ROUTE_HAS_PENDING_STOPS`, HTTP 409). Investigation closure gates come last of all (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403, and `ERR_EXCHANGE_NOT_VERIFIED`, HTTP 409).

### 2.7. Optimistic Concurrency Control

Three write operations carry mandatory optimistic concurrency control. Each requires a non-optional version field in the request body carrying the client's last observed `version` of the target resource; if another writer has advanced the resource's `version` since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a state it has not observed.

- Reassigning a route (`POST /routes/{id}/reassign`) requires `expected_route_version` matching the route's current `version`. Reassignment legitimately supersedes the current technician assignment while `ASSIGNED`, so a client holding a stale version would otherwise silently overwrite a newer assignment.
- Capturing a read on a route stop (`POST /route-stops/{id}/reads`) requires `expected_route_stop_version` matching the stop's current `version`. Re-capture from `READ_CAPTURED` and actual-supersedes-estimate from `ESTIMATED` are both legitimate supersede operations, so a stale-version capture would otherwise overwrite a newer read the client never saw.
- Rescheduling a work order (`POST /work-orders/{id}/reschedule`) requires `expected_work_order_version` matching the work order's current `version`. Reschedule supersedes the prior schedule from `OPEN` or `DISPATCHED` without a state change, so a stale-version reschedule would otherwise silently overwrite a newer schedule.

No other endpoint accepts a version field; the three version fields above are mandatory on exactly these three operations.

### 2.8. The Billing Calendar: Read Windows and Shift Windows

Billing is organized into periods. Each BillingCyclePeriod carries a `cycle_code` naming the billing cycle it belongs to (for example `C03`), a `period_start_date` and `period_end_date` bounding the billed usage span, a `read_window_open_date` and `read_window_close_date` bounding when reads count, and a `bill_run_date` on which billing executes; all dates use `YYYY-MM-DD` form. At creation the dates must form a non-decreasing chain — the period start on or before the window open, the window open on or before the window close, the window close on or before the period end, and the period end on or before the bill run date — or creation is rejected with `ERR_WINDOW_DATE_ORDER` (HTTP 422). A period's `period_status` walks from `SCHEDULED` through `WINDOW_OPEN` and `WINDOW_CLOSED` to `BILLED` and finally `CLOSED`; the transitions and their gates live in §3.2 and §3.4.

The read window is the interval from `read_window_open_date` through `read_window_close_date` with both endpoints inclusive. A read whose `read_at` date falls inside its period's window is on-cycle and is credited to the period whose window contains it; a `read_at` even one day outside in either direction is rejected at capture with `ERR_READ_OUTSIDE_WINDOW` (HTTP 422). The same interval governs route planning: a route whose `scheduled_date` falls outside its period's window is rejected with `ERR_ROUTE_OUTSIDE_READ_WINDOW` (HTTP 422). Window membership alone never permits capture — reads can additionally be captured only while the period is `WINDOW_OPEN`, a separate gate that fails with `ERR_READ_WINDOW_NOT_OPEN` (HTTP 409).

Field commitments are scheduled against named shift windows within a service date. The `AM` shift runs from 06:00 up to but not including 12:00; the `PM` shift runs from 12:00 up to but not including 18:00; the `FULL` shift runs from 06:00 up to but not including 18:00. One technician cannot hold two commitments on the same date whose shift intervals overlap — an `AM` commitment and a `PM` commitment on the same date are adjacent, not overlapping, and are allowed. Violations surface as `ERR_TECHNICIAN_WINDOW_CONFLICT` (HTTP 409) at route assignment and reassignment and at work-order dispatch and reschedule.

### 2.9. Register Integrity and Numeric Precision

Meter registers move in one direction. Every `read_value`, `old_final_read_value`, and `reread_value` is a non-negative integer number of kWh, and any value presented below the account's `last_validated_read_value` (when that field is set) is rejected with `ERR_READ_ROLLBACK` (HTTP 422). This rollback screen applies uniformly to field read capture, AMI head-end ingestion, re-read completion, and meter-exchange completion.

Precision rules are pinned per quantity. Register reads and estimates are whole-kWh integers; estimation performs no intermediate rounding and applies a single round-half-up at the final step only. Read rates (`read_rate_percent`, `net_read_rate_percent`) are percentages expressed to exactly two decimal places, rounded half-up. Back-bill amounts are integer cents with the pinned per-month rounding order described in §3.6. The service-level breach test uses exact integer cross-multiplication on raw counts and never consults the rounded display rate (§3.9).

### 2.10. Field Safety as a Cross-Cutting Concern

Field safety overrides convenience everywhere in the API. A service account carrying an `ACTIVE` hazard flag blocks field read capture on its stops unless the route was explicitly planned as a two-person crew (`two_person_crew`), in which case capture proceeds. Hazard flags are not eternal: every flag carries a thirty-day time-to-live, and repeated reports of the same hazard at the same account merge into the existing flag rather than piling up duplicates. Flags can be cleared deliberately by field or office staff, and they expire automatically under the operations checkpoint sweep; either resolution can release hazard-skipped stops back to workable status, as detailed in §3.5. Separately, a meter suspected of tamper sits under an evidence-preservation hold that blocks replacement work until the investigation resolves (§3.6).

### 2.11. Read-Rate Accounting and the Service-Level Standard

Performance is measured with two rates, and the distinction is contractual. A **gross** read rate divides covered stops by all stops except `CANCELLED` ones; hazard-skipped stops count against it. A **net** read rate divides covered stops by that same denominator less the `SKIPPED_HAZARD` stops, so identical stop data always yields a strictly higher net rate whenever any hazard skip exists. Route reconciliation pins the gross variant to the route's `read_rate_percent` — the contractual SLA denominator — and the net variant to `net_read_rate_percent`, the operations view; operations checkpoints apply the same pairing to their own `read_rate_percent` and `net_read_rate_percent` fields. Both rates are rounded half-up to two decimal places, and a zero denominator yields null rather than a computed value. The standing service-level standard is a gross covered ratio of 98.50 percent: at snapshot finalization the verdict is computed with exact integer arithmetic on the raw counts, strictly below standard constituting a breach (§3.9).

### 2.12. State Consistency and Cascading Effects

Consistency is immediate, never deferred. When a parent resource transitions in a way that strands its children, the system resolves the children in the same request: suspending a service account cancels its still-pending stops; cancelling a route cancels its pending stops; removing or suspecting a meter withdraws its campaign enrollments and cancels their work orders; closing a campaign withdraws its non-terminal enrollments and cancels their orders. Conversely, child events propagate upward: validating a read resolves its stop, and completing an endpoint-swap work order advances its enrollment and may complete its campaign. Cascades are frequently conditional — they touch only children in named states and leave everything else untouched — and §3 spells out each cascade's exact filter. Every resource a cascade mutates has its `updated_at` refreshed and its `version` incremented, so optimistic-concurrency clients always observe cascade movement. Where a transition is not permitted from a resource's current state and no more specific rule names the failure, the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409).
## 3. Business Logic & Workflows

### 3.1. Master Data: Technicians, Service Accounts, and the Meter Inventory

Before any reading can happen, the contractor's master data must exist. A `MeterOpsAdmin` registers each field technician with a `display_name`; the new technician starts `ACTIVE`, and the technician collection can be filtered by `technician_status` when listing. Deactivation moves `technician_status` from `ACTIVE` to `INACTIVE`, but only when the technician holds no open commitments: a route assigned or in progress under that technician, or a work order dispatched or in progress under them, blocks deactivation with `ERR_TECHNICIAN_HAS_OPEN_WORK` (HTTP 409). An `INACTIVE` technician cannot receive new routes or work orders — assignment, reassignment, and dispatch all fail with `ERR_TECHNICIAN_NOT_ACTIVE` (HTTP 409) — though commitments already in flight are unaffected.

Service accounts are the billing anchors. Creating one requires an `account_number` that is unique across all accounts (a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER`, HTTP 409), a `service_address` for the premise, a `billing_cycle_code` placing the account in a billing cycle such as `C03`, and optionally an `estimation_method` selecting the estimate variant — `TRAILING_AVERAGE` or `SAME_PERIOD_LAST_YEAR` — which defaults to `TRAILING_AVERAGE` when omitted. Every account begins with `account_status` `ACTIVE`. Four system-maintained fields keep the account's metering picture current: `current_meter_id` names the meter whose `installed_service_account_id` points at this account and whose `meter_status` is `IN_SERVICE` (null when none exists); `last_validated_read_value` and `last_validated_read_at` echo the value and timestamp of the account's most recent `VALIDATED` read by `read_at` (both null until one exists); and `estimated_read_streak` counts consecutive billing periods whose billable read is estimated — incremented when an estimate is generated, decremented when an actual read supersedes an estimate, and reset to zero whenever an actual read is validated, starting from zero. The account list may be filtered by `billing_cycle_code`, `account_status`, or `current_meter_id`.

Suspending an account moves `account_status` from `ACTIVE` to `SUSPENDED` and immediately strands its field work: every route stop for the account still sitting in `PENDING` on a route in `DRAFT`, `ASSIGNED`, or `IN_PROGRESS` transitions to `CANCELLED`. Reactivation from `SUSPENDED` back to `ACTIVE` is refused while any investigation for the account sits in `OPEN`, `EVIDENCE_GATHERING`, `PENDING_DISPOSITION`, or `CONFIRMED_THEFT` (`ERR_ACCOUNT_HAS_OPEN_INVESTIGATION`, HTTP 409); a `CLEARED` investigation does not block. Closing an account — permitted from either `ACTIVE` or `SUSPENDED` and restricted to `MeterOpsAdmin` — requires that no open work remain: open stops, unfinished work orders, or un-closed investigations cause rejection with `ERR_ACCOUNT_HAS_OPEN_WORK` (HTTP 409). `CLOSED` is terminal. One further cascade enters through the back door: confirming theft on an investigation suspends the account automatically, with the same pending-stop cancellation cascade (§3.6).

Meters are physical assets tracked on three independent state dimensions that evolve in parallel on one record. Registering a meter takes a `serial_number` unique across all meters (duplicates fail with `ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409) and a `meter_type` of `HANDHELD` or `AMI`. A new meter starts with `meter_status` `IN_STOCK`, `tamper_status` `NONE`, and an `endpoint_comms_status` that defaults by type — `COMMUNICATING` for an `AMI` meter, `NOT_APPLICABLE` for a `HANDHELD` one — with `consecutive_missed_days` at zero and `non_communicating_since` null. The comms dimension walks `COMMUNICATING`, `DEGRADED`, `NON_COMMUNICATING`, and `FAILED` under the checkpoint sweep (§3.9), while the tamper dimension walks `NONE`, `SUSPECTED`, and `CONFIRMED` under investigations (§3.6); the lifecycle dimension moves only through installs, exchanges, and retirement. The meter list filters by `meter_status`, `endpoint_comms_status`, `tamper_status`, or `installed_service_account_id`.

Installing a meter moves it from `IN_STOCK` to `IN_SERVICE` at an account named by `service_account_id` in the payload. The target account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`, HTTP 409) and must not already have another meter in service (`ERR_ACCOUNT_HAS_INSTALLED_METER`, HTTP 409). On success the meter's `installed_service_account_id` is set and the account's `current_meter_id` recomputes to this meter. Retirement moves a meter from `IN_STOCK` or `REMOVED` to the terminal `RETIRED` state. Notably, `REMOVED` is never reached by direct call — only the meter-exchange cascade of §3.7 takes a meter out of service.

### 3.2. Billing Periods and Route Planning

A `MeterOpsAdmin` opens each billing cycle by creating a BillingCyclePeriod with its `cycle_code`, `period_start_date`, `period_end_date`, `read_window_open_date`, `read_window_close_date`, and `bill_run_date`, subject to the date-ordering chain of §2.8. The period begins `SCHEDULED`. When the logical clock's current date reaches the `read_window_open_date`, a `BillingLiaison` or `MeterOpsAdmin` may open the read window, moving `period_status` to `WINDOW_OPEN`; attempting this before that date is rejected with `ERR_READ_WINDOW_NOT_OPEN` (HTTP 409). Once the clock's current date has passed the `read_window_close_date`, closing the window moves the period to `WINDOW_CLOSED` — an attempt while the clock date is still on or before the close date fails with `ERR_READ_WINDOW_STILL_OPEN` (HTTP 409). Closing the window carries a sweep: every route stop bound to the period still in `PENDING` transitions to `NO_READ_PENDING` with its `no_read_reason` stamped `WINDOW_EXPIRED`. A period exposes its `unresolved_stop_count`, the count of its stops sitting in `PENDING` or `NO_READ_PENDING`, which gates billing finalization in §3.4. Period lists filter by `cycle_code` or `period_status`.

Routes are the field plan for a period. A `Dispatcher` creates one with the target `billing_cycle_period_id`, a `scheduled_date` that must lie inside the period's read window (`ERR_ROUTE_OUTSIDE_READ_WINDOW`, HTTP 422), a `route_shift` of `AM`, `PM`, or `FULL`, and an optional `two_person_crew` flag that defaults to false and, when true, exempts the route's stops from the active-hazard capture block. The period must still be `SCHEDULED` or `WINDOW_OPEN` for route creation. Upon creation the system auto-generates the route's stops: every service account that is `ACTIVE`, has an `IN_SERVICE` meter, and whose meter is either of type `HANDHELD` or has an `endpoint_comms_status` other than `COMMUNICATING` — communicating AMI endpoints are read remotely and need no visit — receives one RouteStop in `PENDING`. Each stop records its `route_id`, its `service_account_id`, and a `billing_cycle_period_id` denormalized from the route, and receives a 1-based `sequence_number` ordering the stops by the accounts' creation timestamps, earliest first.

A route is born in `DRAFT` with `technician_id` null. Two counters track its coverage as work proceeds: `stops_total` counts the route's stops excluding any in `CANCELLED`, and `captured_stop_count` counts stops in `READ_CAPTURED`, `VALIDATED`, `ESTIMATED`, or `SUPERSEDED`. The two read-rate fields, `read_rate_percent` and `net_read_rate_percent`, stay unset until reconciliation computes them per §2.11. Route lists filter by `billing_cycle_period_id`, `technician_id`, or `route_status`, and a dedicated listing returns a route's stops in sequence order; the stop collection itself filters by `route_id`, `service_account_id`, `billing_cycle_period_id`, `stop_status`, `hazard_flag_id`, or `current_read_id`.

### 3.3. Route Execution and Field Read Capture

Crewing a route begins with assignment. A `Dispatcher` assigns a `DRAFT` route by naming a `technician_id`; the technician must be `ACTIVE` (`ERR_TECHNICIAN_NOT_ACTIVE`) and free of any overlapping commitment — another assigned route or dispatched work order on the same `scheduled_date` whose shift window overlaps (`ERR_TECHNICIAN_WINDOW_CONFLICT`) — whereupon the route moves to `ASSIGNED` and `technician_id` is set. Reassigning an `ASSIGNED` route supersedes the current technician with a new `technician_id` under the optimistic-concurrency rule of §2.7: the request must carry `expected_route_version` matching the route's current `version` (mismatches fail with `ERR_STALE_VERSION`, HTTP 412), the new technician must be `ACTIVE` and conflict-free, and the operation increments the route's `version` by one while remaining in `ASSIGNED`. Reassignment from any state other than `ASSIGNED` fails with `ERR_ROUTE_NOT_REASSIGNABLE` (HTTP 409). Unassigning returns an `ASSIGNED` route to `DRAFT` with `technician_id` cleared to null. Cancelling is possible from `DRAFT` or `ASSIGNED`; the route becomes `CANCELLED` and only its stops still in `PENDING` cascade to `CANCELLED` — stops in any other state are untouched.

Field work starts when the assigned technician starts the route: the caller's `X-User-ID` must equal the route's `technician_id` (`ERR_NOT_ASSIGNED_TECHNICIAN`, HTTP 403), and the route moves from `ASSIGNED` to `IN_PROGRESS`. Completion moves an `IN_PROGRESS` route to `COMPLETED`, again restricted to the assigned technician, and is gated on field work being settled — any stop still in `PENDING` blocks completion with `ERR_ROUTE_HAS_PENDING_STOPS` (HTTP 409), though stops in `NO_READ_PENDING` or `SKIPPED_HAZARD` do not. After completion, a `Dispatcher` reconciles the route, moving it to the terminal `RECONCILED` state and computing both read rates per §2.11: covered stops are those in `VALIDATED`, `ESTIMATED`, or `SUPERSEDED`; the gross rate pinned to `read_rate_percent` divides covered by all non-`CANCELLED` stops, and the net rate pinned to `net_read_rate_percent` divides covered by that denominator less the `SKIPPED_HAZARD` stops, each rounded half-up to two decimal places and set to null when its denominator is zero.

The atomic act of the whole system is capturing a read on a stop. A stop may receive a capture from `PENDING`, `NO_READ_PENDING`, `READ_CAPTURED`, or `ESTIMATED`; capture from any other stop state fails with `ERR_STOP_NOT_ACTIONABLE` (HTTP 409). Ordinarily the caller is the route's assigned `FieldTechnician`; the alternative path is an administrative correction — a payload with `correction` set true — which only a `MeterOpsAdmin` may send, and a `FieldTechnician` presenting `correction` as true is rejected with `ERR_FORBIDDEN_FOR_ROLE`. Every capture request carries `meter_id`, `read_value`, `read_at`, and the OCC field `expected_route_stop_version` per §2.7, with `tamper_indication` optional and defaulting to false. The request is then checked, in the §2.6 order, against the route being `IN_PROGRESS` (`ERR_ROUTE_NOT_IN_PROGRESS`), the period being `WINDOW_OPEN` (`ERR_READ_WINDOW_NOT_OPEN`), the hazard screen — an `ACTIVE` hazard flag on the account blocks capture unless the route's `two_person_crew` is true (`ERR_ACTIVE_HAZARD_BLOCKS_READ`, HTTP 422) — the `read_at` date falling inside the read window on both ends (`ERR_READ_OUTSIDE_WINDOW`), the presented `meter_id` being the account's currently installed meter (`ERR_METER_NOT_INSTALLED_AT_ACCOUNT`, HTTP 409), and the rollback rule against `last_validated_read_value` (`ERR_READ_ROLLBACK`).

A successful capture creates a MeterRead with `read_source` `HANDHELD` and `read_status` `PROVISIONAL`, moves the stop to `READ_CAPTURED`, points the stop's `current_read_id` at the new read, and increments the stop's `version` by one. Supersedure keeps history honest. Re-capturing a stop already in `READ_CAPTURED` transitions the prior provisional current read to `SUPERSEDED` with its `supersedes_read_id` pointing at the new read. Capturing against an `ESTIMATED` stop — no correction flag required; an actual read simply supersedes an estimate — transitions the `ESTIMATED` read to `SUPERSEDED`, sets its `supersedes_read_id`, and decrements the account's `estimated_read_streak` by one as compensation. And when `tamper_indication` arrives true, capture additionally fires the investigation cascade of §3.6. Reads are attributed permanently: the read's `meter_id` freezes the serial attribution at capture time, and the account linkage is recorded on `service_account_id`.

When a stop cannot be read, the technician has two outs. Marking no-read moves a `PENDING` stop to `NO_READ_PENDING` and records a free-text `no_read_reason`; the manual form requires the route `IN_PROGRESS` and the assigned technician. (The same target state is also reached by two system cascades — window close stamping `WINDOW_EXPIRED`, and read rejection stamping `READ_REJECTED`.) Skipping for hazard moves a `PENDING` stop to `SKIPPED_HAZARD` citing a `hazard_flag_id`; that flag must be an `ACTIVE` hazard flag on this stop's own account, or the skip is rejected with `ERR_SKIP_REQUIRES_ACTIVE_HAZARD` (HTTP 409) — citing another account's flag fails the same way. A hazard-skipped stop reverts automatically: when the cited flag is cleared or expires and no other `ACTIVE` hazard flag remains on the account, the stop returns from `SKIPPED_HAZARD` to `PENDING` with `hazard_flag_id` cleared to null, provided its route is `ASSIGNED` or `IN_PROGRESS` (§3.5). The RouteStop lifecycle terminates at `VALIDATED`, `ESTIMATED`, `SUPERSEDED`, or `CANCELLED`; a `PENDING` stop also cascades to `CANCELLED` when its route is cancelled or its account is suspended.

### 3.4. Read Validation, Estimation, and Billing Finalization

Every MeterRead carries a `read_source` drawn from six values — `HANDHELD`, `REREAD`, `AMI_REMOTE`, `ESTIMATE`, `EXCHANGE_FINAL`, and `EXCHANGE_INITIAL` — and its starting `read_status` depends on that source: field and re-reads begin `PROVISIONAL`; AMI-remote and both exchange reads are auto-validated and begin `VALIDATED`; estimates begin `ESTIMATED`. Reads born of stop capture point back through `route_stop_id`; `AMI_REMOTE`, `EXCHANGE_FINAL`, and `EXCHANGE_INITIAL` reads have no stop and carry null there. The `estimation_method` on a read is set only on `ESTIMATE` reads, where it also makes a method fallback observable (below). A read's `is_billable` flag is computed: it is true exactly when the read is `VALIDATED`, or when the read is `ESTIMATED` and its period has not yet reached `BILLED` or `CLOSED`; `SUPERSEDED` and `REJECTED` reads are never billable, and the flag starts false until one of those conditions holds. The read collection filters by `service_account_id`, `meter_id`, `route_stop_id`, `read_status`, or `supersedes_read_id`.

AMI reads arrive from the head-end through a `MeterOpsAdmin` ingestion call carrying `read_value` and `read_at` against a specific meter. The meter must be an `AMI` meter — ingestion against a `HANDHELD` meter fails with `ERR_METER_NOT_AMI` (HTTP 422) — and must be `IN_SERVICE`. The rollback rule applies (`ERR_READ_ROLLBACK`), and the created `AMI_REMOTE` read is auto-validated. Two further effects follow: when the ingested read's `read_at` is the latest among the account's validated reads, the account's `last_validated_read_value` and `last_validated_read_at` advance; and the meter's comms dimension recovers — a meter in `DEGRADED`, `NON_COMMUNICATING`, or `FAILED` returns to `COMMUNICATING` with `consecutive_missed_days` reset to zero and `non_communicating_since` cleared to null.

Provisional reads are adjudicated by the `BillingLiaison`. Validation moves a `PROVISIONAL` read to `VALIDATED`: the account's last-validated pair updates when this read's `read_at` is the latest, the account's `estimated_read_streak` resets to zero, and the owning stop — when its `current_read_id` is this read — transitions from `READ_CAPTURED` to `VALIDATED`. Validation also completes supersede chains: when the newly validated read supersedes an older read for the same stop, that older read — whether `VALIDATED` or `ESTIMATED` — transitions to `SUPERSEDED` (an administrative-correction target has in fact already been moved to `SUPERSEDED` at capture time), the stop follows the same cascade from `VALIDATED` or `ESTIMATED` to `SUPERSEDED`, and the superseded read's `is_billable` recomputes to false with account aggregates recomputed. Rejection moves a `PROVISIONAL` read to `REJECTED` with a mandatory `rejection_reason`; the owning stop, when its `current_read_id` is this read, falls back from `READ_CAPTURED` to `NO_READ_PENDING` with `no_read_reason` `READ_REJECTED`, and the stop's `current_read_id` is cleared to null — a rejected read is never superseded by a later capture. `REJECTED` and `SUPERSEDED` are terminal for a read, and any read in `PROVISIONAL`, `VALIDATED`, or `ESTIMATED` transitions to `SUPERSEDED` when a superseding read is captured or validated per the capture side effects.

When a stop reaches the window's end unread, the `BillingLiaison` may generate an estimate, moving the stop from `NO_READ_PENDING` to `ESTIMATED`. Three gates guard it, in ladder order: the period must be `WINDOW_OPEN` or `WINDOW_CLOSED` (`ERR_READ_WINDOW_NOT_OPEN`); the account's `estimated_read_streak` must be below the cap of three consecutive estimates (`ERR_ESTIMATE_CAP_REACHED`, HTTP 409); and the account must hold at least two `VALIDATED` reads with `read_at` inside the trailing 365 days (`ERR_INSUFFICIENT_READ_HISTORY`, HTTP 409). Only `VALIDATED` reads ever feed the estimation math — `ESTIMATED`, `PROVISIONAL`, `REJECTED`, and `SUPERSEDED` reads are excluded from the input set.

The estimate value depends on the account's `estimation_method`. Under `TRAILING_AVERAGE`, the calculation identifies the account's most recent validated read — the latest value at the latest timestamp — and the validated read with the greatest `read_at` strictly earlier than that timestamp, the prior value at the prior timestamp. Average daily usage is the difference between the latest and prior values divided by the number of days between the two timestamps, carried at full precision with no intermediate rounding. The projection horizon is the number of days from the latest read's timestamp to the period's `read_window_close_date` — the estimate targets the window close. The estimate is the latest value plus the product of the average daily usage and the horizon, rounded half-up to a whole kWh in one final rounding step.

Under `SAME_PERIOD_LAST_YEAR`, the candidate set is the account's validated reads whose `read_at` date falls inside the same calendar month one year before the month containing the period's `read_window_close_date` — a window closing on 2026-07-28 draws candidates from 2025-07-01 through 2025-07-31. When at least two candidates exist, the estimate is the account's last validated value plus the spread between the largest and smallest candidate `read_value`. When fewer than two exist, the method falls back — pinned — to the trailing-average computation, and the created read records `estimation_method` `TRAILING_AVERAGE` so the fallback is observable on the read itself. Either way, estimate creation produces a MeterRead with `read_source` `ESTIMATE` and `read_status` `ESTIMATED`, points the stop's `current_read_id` at it, and increments the account's `estimated_read_streak` by one.

Finalizing a billing period is the `BillingLiaison`'s last act on it. From `WINDOW_CLOSED`, finalization first requires the period's `unresolved_stop_count` to be zero (`ERR_CYCLE_HAS_UNRESOLVED_STOPS`, HTTP 409), then requires that every `ACTIVE` service account whose `billing_cycle_code` matches the period's `cycle_code` hold a billable read for the period — routed accounts satisfy this through their resolved stop, while non-routed AMI accounts satisfy it through a `VALIDATED` `AMI_REMOTE` read whose `read_at` date lies inside the read window (`ERR_ACCOUNT_MISSING_BILLABLE_READ`, HTTP 409). Both gates passing moves the period to `BILLED`. Closing the period moves it from `BILLED` to the terminal `CLOSED` state and locks corrections: from then on, read capture and estimate generation against the period fail with `ERR_READ_WINDOW_NOT_OPEN`.
### 3.5. Hazard Flags and Stop-Level Safety

Field technicians are the eyes of the safety program. A `FieldTechnician` reports a hazard by naming the `service_account_id`, a `hazard_type` of `DOG`, `ACCESS`, `LOCKED_GATE`, `CHEMICAL`, or `OTHER`, and a `severity` of `LOW` or `HIGH`. The new flag starts `ACTIVE`, stamps `reported_by_technician_id` from the caller's `X-User-ID`, stamps `reported_at` from the logical clock, computes `expires_at` as `reported_at` plus thirty days, and starts `renewed_count` at zero. The flag collection filters by `service_account_id`, `reported_by_technician_id`, or `flag_status`.

Repeat reporting merges rather than duplicates. When a report arrives for an account and hazard type that already has an `ACTIVE` flag, no second row is created: the existing flag's `expires_at` is pushed out to the later of its current `expires_at` and thirty days from now, its `renewed_count` is incremented by one, and the call returns 200 with the existing flag (a genuinely fresh report returns 201). Explicit renewal works the same way — renewing an `ACTIVE` flag refreshes `expires_at` to thirty days from now (keeping the existing `expires_at` if it is later) and increments `renewed_count` — but renewing a flag already `EXPIRED` or `CLEARED` is rejected with `ERR_HAZARD_FLAG_NOT_ACTIVE` (HTTP 409). Clearing is an explicit act available to `FieldTechnician`, `Dispatcher`, or `MeterOpsAdmin` and moves an `ACTIVE` flag to `CLEARED`. Expiry is the system's act: at each operations checkpoint, the sweep examines `ACTIVE` flags in ascending `expires_at` order and expires any flag whose `expires_at` is strictly earlier than the snapshot instant; a flag whose `expires_at` equals the snapshot instant survives it and remains `ACTIVE`. Both `EXPIRED` and `CLEARED` are terminal.

Resolution releases stranded stops. When a flag clears or expires and no other `ACTIVE` hazard flag remains on the account, every stop of that account sitting in `SKIPPED_HAZARD` and citing this flag reverts to `PENDING` with its `hazard_flag_id` cleared to null — provided the stop's route is `ASSIGNED` or `IN_PROGRESS`. While a flag is `ACTIVE`, of course, the capture block of §2.10 applies: stops on the flagged account refuse read capture with `ERR_ACTIVE_HAZARD_BLOCKS_READ` unless the route runs as a two-person crew, and technicians may instead skip the stop per §3.3.

### 3.6. Tamper and Theft Investigations

Revenue protection begins when an investigation opens. An `Investigator` opens one manually by naming the `service_account_id`, the `meter_id`, and an `indication_type` of `TAMPER_FLAG`, `THEFT_REPORT`, or `USAGE_ANOMALY`; the investigation starts `OPEN` with `opened_by_user_id` recording the caller's `X-User-ID`. Only one non-terminal investigation may exist per meter — a manual open while another investigation for the meter sits in any state short of `CLOSED` fails with `ERR_INVESTIGATION_ALREADY_OPEN` (HTTP 409). Investigations also open themselves: when a field capture arrives with `tamper_indication` true and no non-terminal investigation exists for that account and meter, the system creates an `OPEN` investigation whose `triggering_read_id` points at the tamper-flagged read and whose `opened_by_user_id` is recorded as `system`. The investigation list filters by `service_account_id`, `meter_id`, `investigation_status`, `triggering_read_id`, or `exchange_work_order_id`.

Either path flips the meter's `tamper_status` from `NONE` to `SUSPECTED`, and suspicion has teeth. While any investigation for the meter remains non-terminal, new `EXCHANGE` or `ENDPOINT_SWAP` work orders for that meter — and any attempt to enroll the meter in a replacement campaign — are rejected with `ERR_EVIDENCE_PRESERVATION_HOLD` (HTTP 409), preserving the physical evidence. Suspicion also withdraws the meter from any replacement program already in flight: a CampaignEnrollment for the meter in `ENROLLED` or `WORK_ORDER_CREATED` transitions to `WITHDRAWN`, its `OPEN` or `DISPATCHED` work order transitions to `CANCELLED`, and the owning campaign recomputes its counts, auto-completing when every enrollment has reached a terminal state (§3.8).

The investigation workflow is a supervised loop. From `OPEN`, the investigator begins evidence gathering (`EVIDENCE_GATHERING`); from there they submit a disposition (`PENDING_DISPOSITION`); a disposition can bounce back to `EVIDENCE_GATHERING` when more evidence is requested, and this revision loop may repeat indefinitely. Evidence accumulates through the field: each `TAMPER_CHECK` work-order completion appends its note to the investigation's `evidence_notes` array (§3.7).

Two exits resolve a disposition. Clearing the investigation moves it from `PENDING_DISPOSITION` to `CLEARED` and returns the meter's `tamper_status` from `SUSPECTED` to `NONE`, lifting the evidence-preservation hold. Confirming theft moves it from `PENDING_DISPOSITION` to `CONFIRMED_THEFT` and is the heaviest transaction in the API. The caller supplies `theft_window_months` — the number of months of unbilled usage claimed — and `monthly_estimated_kwh`, an array of per-month estimated kWh whose length must equal `theft_window_months` exactly, failing which the request is rejected with `ERR_BACKBILL_INPUT_MISMATCH` (HTTP 422) at body-validation time. The back-bill is then computed with a pinned rounding order: each month's charge is that month's estimated kWh multiplied by eleven and a quarter cents, rounded half-up to a whole cent — per-month rounding happens before any summation, and summing first and rounding once produces a different result and is rejected; the subtotal is the sum of those per-month charges; the penalty is one quarter of the subtotal, rounded half-up to a whole cent; and the total back-bill, stored on `backbill_cents`, is the subtotal plus the penalty. Confirmation then cascades: an `EXCHANGE` work order is auto-created in `OPEN` for the account and meter with `exchange_work_order_id` recording it; the meter's `tamper_status` moves from `SUSPECTED` to `CONFIRMED`; and the account moves from `ACTIVE` to `SUSPENDED` with the full pending-stop cancellation cascade of §3.1.

Closure is deliberately two-person. From either `CONFIRMED_THEFT` or `CLEARED`, an investigator may close the investigation, but the closer's `X-User-ID` must differ from the `opened_by_user_id` — the same operator cannot close what they opened, and an attempt fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Closing from `CONFIRMED_THEFT` carries a second gate: the auto-created exchange work order recorded on `exchange_work_order_id` must have reached `VERIFIED`, failing which the close is rejected with `ERR_EXCHANGE_NOT_VERIFIED` (HTTP 409). A successful close stamps `closed_by_user_id` and lands the investigation in the terminal `CLOSED` state.

### 3.7. Field Work Orders

Work orders dispatch every piece of non-route field work. A `Dispatcher` creates one by naming a `work_order_type` — `RE_READ`, `EXCHANGE`, `TAMPER_CHECK`, or `ENDPOINT_SWAP` — together with the `service_account_id`, a `scheduled_date`, and a `work_shift` of `AM`, `PM`, or `FULL`, with free-text `notes` optional. Reference requirements are type-specific at creation: `EXCHANGE` and `ENDPOINT_SWAP` orders require a `meter_id`; a `RE_READ` order requires a `route_stop_id` whose stop is currently `NO_READ_PENDING` (`ERR_STOP_NOT_ACTIONABLE` otherwise); a `TAMPER_CHECK` order requires an `investigation_id` naming a non-terminal investigation — note that the stricter evidence-gathering gate applies at completion time, not at creation. Two cross-cutting gates also apply: the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the evidence-preservation hold of §3.6 blocks `EXCHANGE` and `ENDPOINT_SWAP` creation for a suspected meter (`ERR_EVIDENCE_PRESERVATION_HOLD`). A new order starts `OPEN` with `technician_id` null; the work-order list filters by `service_account_id`, `meter_id`, `technician_id`, `route_stop_id`, `investigation_id`, `campaign_enrollment_id`, `new_meter_id`, `work_order_status`, or `work_order_type`. Campaign-born orders are recognizable by their `campaign_enrollment_id`, set when enrollment auto-creates them (§3.8) with `scheduled_date` seven days after the enrollment date and `work_shift` `FULL`.

Dispatch moves an order from `OPEN` or `REWORK` to `DISPATCHED`, naming a `technician_id`; the technician must be `ACTIVE` (`ERR_TECHNICIAN_NOT_ACTIVE`) and free of overlapping same-date shift commitments across both routes and other work orders (`ERR_TECHNICIAN_WINDOW_CONFLICT`), and `technician_id` is set. Rescheduling is a self-loop: from `OPEN` or `DISPATCHED` the order stays `OPEN` — the visible mutation is the `scheduled_date` and `work_shift` being replaced, superseding the prior schedule, and the `version` incrementing by one. Reschedule is OCC-guarded per §2.7: the request must carry `expected_work_order_version` matching the order's current `version`, mismatches failing with `ERR_STALE_VERSION`; when rescheduling a `DISPATCHED` order, the new schedule must not create a technician window conflict. Starting work moves a `DISPATCHED` order to `IN_PROGRESS` and, like route start, requires the caller to be the assigned technician (`ERR_NOT_ASSIGNED_TECHNICIAN`).

Completion is where the type-specific work lands, and each type carries its own payload and cascade. Completion of an `IN_PROGRESS` order by its assigned technician stamps `completed_at` from the logical clock and moves the order to `COMPLETED`; a missing type-specific payload fails with `ERR_INVALID_REQUEST` (HTTP 400).

- Completing a `RE_READ` order requires `reread_value` and `reread_at`. The linked stop must be `NO_READ_PENDING` (`ERR_STOP_NOT_ACTIONABLE`), and `reread_value` must clear the rollback rule against the account's `last_validated_read_value` (`ERR_READ_ROLLBACK`). Completion creates a `PROVISIONAL` MeterRead with `read_source` `REREAD` on the linked stop and advances that stop from `NO_READ_PENDING` to `READ_CAPTURED`.
- Completing an `EXCHANGE` order — the serial swap — requires `new_meter_id`, `old_final_read_value`, and `new_initial_read_value`. The new meter must be `IN_STOCK` and different from the meter being removed (`ERR_METER_NOT_AVAILABLE_FOR_INSTALL`, HTTP 409), and `old_final_read_value` must clear the rollback rule (`ERR_READ_ROLLBACK`). The cascade runs in order: an auto-validated `EXCHANGE_FINAL` read is created on the old meter and an auto-validated `EXCHANGE_INITIAL` read on the new meter; the old meter moves from `IN_SERVICE` to `REMOVED` with its `installed_service_account_id` cleared to null; the new meter moves from `IN_STOCK` to `IN_SERVICE` with `installed_service_account_id` set to the account; the account's `current_meter_id` recomputes; and then the removed meter's replacement-program cascade runs — any enrollment for that meter in `ENROLLED` or `WORK_ORDER_CREATED` transitions to `WITHDRAWN`, its `OPEN` or `DISPATCHED` work order transitions to `CANCELLED`, and the owning campaign recomputes its counts and auto-completes when every enrollment is terminal and at least one exists (§3.8).
- Completing a `TAMPER_CHECK` order requires `evidence_note`. The linked investigation must be in `EVIDENCE_GATHERING` (`ERR_INVALID_STATE_TRANSITION` otherwise), and completion appends the note to the investigation's `evidence_notes`.
- Completing an `ENDPOINT_SWAP` order needs no payload. The meter's `endpoint_comms_status` returns to `COMMUNICATING` with `consecutive_missed_days` reset to zero and `non_communicating_since` cleared to null; the CampaignEnrollment owning the order transitions from `WORK_ORDER_CREATED` to `REPLACED`; and the campaign recomputes its counts with the auto-complete check.

After completion, quality control takes over. A `MeterOpsAdmin` verifies a `COMPLETED` order, moving it to the terminal `VERIFIED` state; alternatively they may request rework with a `rework_reason`, moving it to `REWORK`, from which it can be dispatched again. One caveat governs rework of an exchange: the meter swap effects persist through rework — rework re-dispatches field verification only, and undoing a swap requires a second `EXCHANGE` order. Cancelling is available from `OPEN`, `DISPATCHED`, or `REWORK` and lands the order in the terminal `CANCELLED` state. Cancellation reaches back into campaigns: when a dispatcher manually cancels an order whose `campaign_enrollment_id` is set and that enrollment is `WORK_ORDER_CREATED`, the enrollment reverts to `ENROLLED` with its `work_order_id` cleared to null; cascade-driven cancels instead leave the enrollment `WITHDRAWN`.

### 3.8. Endpoint Replacement Campaigns

Aging AMI endpoints are retired through campaigns. A `MeterOpsAdmin` creates a ReplacementCampaign with a `campaign_name` and a `quota` — the maximum number of meters the campaign may enroll, which must be at least one — and the campaign starts `DRAFT`; opening it moves it to `OPEN`. The campaign list filters by `campaign_status`.

Enrollment is an atomic batch operation against an `OPEN` campaign, taking a `meter_ids` array. Three checks run in pinned order: first the batch quota — if the batch size exceeds the campaign's remaining capacity (`quota` less the current `enrolled_count`), the entire batch is rejected with `ERR_CAMPAIGN_QUOTA_EXCEEDED` (HTTP 409) and nothing is enrolled; then each meter's eligibility — only meters whose `endpoint_comms_status` has reached `FAILED` qualify, others failing with `ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN` (HTTP 409); then duplicate membership — a meter already enrolled in an `OPEN` campaign fails with `ERR_METER_ALREADY_ENROLLED` (HTTP 409). The evidence-preservation hold applies here too: enrolling a suspected meter under a non-terminal investigation is rejected with `ERR_EVIDENCE_PRESERVATION_HOLD`. A successful batch returns 201 with the created enrollments.

Every enrollment begins moving immediately. A CampaignEnrollment is born `ENROLLED` with its `campaign_id` and `meter_id` recorded, and the system instantly auto-creates an `ENDPOINT_SWAP` work order for it — `scheduled_date` set to the enrollment date plus seven days, `work_shift` `FULL` — advancing the enrollment to `WORK_ORDER_CREATED` with `work_order_id` set. From there the enrollment waits on the field: completion of that swap order moves it to `REPLACED` per §3.7. Withdrawal arrives by cascade — the meter being removed through an exchange, the meter's `tamper_status` flipping to `SUSPECTED`, or the campaign closing — moving an enrollment in `ENROLLED` or `WORK_ORDER_CREATED` to `WITHDRAWN` and cancelling its linked `OPEN` or `DISPATCHED` work order. `REPLACED` and `WITHDRAWN` are terminal. The enrollment list filters by `campaign_id`, `meter_id`, `enrollment_status`, or `work_order_id`.

The campaign tracks three computed counts: `enrolled_count` (enrollments in `ENROLLED` or `WORK_ORDER_CREATED`), `replaced_count` (enrollments in `REPLACED`), and `withdrawn_count` (enrollments in `WITHDRAWN`), each starting at zero. After any enrollment status change, the campaign checks for completion: when at least one enrollment exists and every enrollment is in `REPLACED` or `WITHDRAWN`, the campaign moves itself from `OPEN` to the terminal `COMPLETED`. An administrator may instead close an `OPEN` campaign outright: closing moves it to the terminal `CLOSED` state and cascades down — enrollments in `ENROLLED` or `WORK_ORDER_CREATED` transition to `WITHDRAWN`, and their work orders in `OPEN`, `DISPATCHED`, or `REWORK` transition to `CANCELLED`.

### 3.9. Operations Checkpoints and SLA Finalization

Operations health is measured by checkpoints. A `MeterOpsAdmin` runs one by supplying a `snapshot_at` instant — the effective business timestamp of the checkpoint — and the system creates an OpsSnapshot in `DRAFT` and immediately executes its pinned four-step sweep in order: hazard expiry first, AMI comms evaluation second, no-read escalation scoring third, and aggregate counting with aging buckets fourth. The snapshot list filters by `snapshot_status`.

Step one expires hazards per §3.5: `ACTIVE` flags are examined in ascending `expires_at` order, and each flag whose `expires_at` is strictly earlier than `snapshot_at` transitions to `EXPIRED`, firing the hazard-skip revert cascade wherever no other active flag remains on the account; equality with `snapshot_at` keeps the flag active.

Step two evaluates AMI communications. For each `AMI` meter in `IN_SERVICE`, examined in ascending order of the meter's `created_at`, the sweep inspects the window from just after the previous snapshot's instant up to and including this `snapshot_at` — for the first snapshot, from just after the meter's `created_at` up to and including `snapshot_at`. If any `AMI_REMOTE` read in any status other than `REJECTED` has its `read_at` inside that window, the meter returns to `COMMUNICATING` with `consecutive_missed_days` reset to zero and `non_communicating_since` cleared to null. Otherwise the meter's `consecutive_missed_days` is incremented by one: a first miss moves a `COMMUNICATING` meter to `DEGRADED`, a second consecutive miss leaves it `DEGRADED`, and on the third consecutive miss a meter in `COMMUNICATING` or `DEGRADED` becomes `NON_COMMUNICATING` with `non_communicating_since` set to `snapshot_at` — three consecutive misses always pass through `DEGRADED`; no direct jump exists. A meter already `NON_COMMUNICATING` whose `non_communicating_since` is at least fourteen days before `snapshot_at` — exactly fourteen days qualifies; the boundary is inclusive — becomes `FAILED` and is from that moment eligible for replacement-campaign enrollment. A missed day is cumulative across snapshots and resets on any AMI read.

Step three escalates unread stops. For every stop in `NO_READ_PENDING` whose period is `WINDOW_OPEN` or `WINDOW_CLOSED` — evaluated in pinned order: descending score, then ascending days until window close, then ascending stop `created_at` — the sweep computes an urgency score. The score starts from a base of 10, adds 25 for each unit of the account's `estimated_read_streak`, adds 5 for each day by which seven days exceeds the number of days from the snapshot date to the `read_window_close_date` — that day count is measured as close date minus snapshot date and turns negative once the close has passed, so this term is zero while seven or more days remain and keeps growing past the close — and adds 15 when the account carries an `ACTIVE` hazard flag; the total is capped at 100. When the score reaches at least 40 — the threshold boundary is inclusive — and no `RE_READ` work order in `OPEN`, `DISPATCHED`, `IN_PROGRESS`, or `REWORK` already exists for the stop, the sweep auto-creates a `RE_READ` work order in `OPEN` linked to the stop, scheduled on the snapshot date with a `FULL` shift.

Step four counts the world as of the snapshot. `eligible_stop_count` counts stops on non-`CANCELLED` routes whose `scheduled_date` is on or before the snapshot date, excluding `CANCELLED` stops; `covered_stop_count` counts the eligible stops in `VALIDATED`, `ESTIMATED`, or `SUPERSEDED`; `backlog_count` counts stops in `PENDING` or `NO_READ_PENDING` on non-`CANCELLED` routes; `backlog_aged_7plus_count` counts backlog stops whose `created_at` is at least seven days before `snapshot_at` — a stop created exactly seven days earlier counts as aged, the boundary inclusive. `estimated_read_count` and `validated_read_count` count reads sitting in `ESTIMATED` and `VALIDATED` status at snapshot time. From these, `read_rate_percent` is the gross rate — covered over eligible, times one hundred, rounded half-up to two decimal places, null when no stops are eligible — and `net_read_rate_percent` is the net rate, covered over the eligible count less the `SKIPPED_HAZARD` stops, null when that denominator is zero. Membership is pinned as of `snapshot_at`: an `ESTIMATED` stop counts toward coverage as of the snapshot, and later streak changes never revise a recorded checkpoint.

Finalization turns the checkpoint into a verdict. A `MeterOpsAdmin` finalizes a `DRAFT` snapshot, moving `snapshot_status` to the terminal `FINALIZED` state and locking in `sla_breach`. The breach test — a field that is null while the snapshot remains `DRAFT` — uses exact integer arithmetic on the raw counts, never the rounded display rate: the snapshot is in breach only when two hundred times the covered count is strictly less than one hundred ninety-seven times the eligible count, that is, when the true covered ratio falls strictly below 98.50 percent. Exact equality — two hundred times covered equal to one hundred ninety-seven times eligible, precisely 98.50 percent — is not a breach, and the verdict, once written at finalization, is locked thereafter.
## 4. Endpoint Definitions

Operations that create new, stand-alone resources return a `201 Created` status code — this covers registering technicians, accounts, meters, periods, routes, work orders, investigations, campaigns, and snapshots, as well as AMI read ingestion, field read capture, estimate generation, batch enrollment, and a genuinely fresh hazard report. Operations that modify an existing resource return `200 OK`; note in particular that a hazard report which merges into an existing active flag returns 200 with the existing flag rather than creating anything. The table below is a navigational summary only — request payloads, response shapes, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | MeterOpsAdmin |
| POST | `/field-technicians` | Register a field technician | MeterOpsAdmin |
| GET | `/field-technicians` | List technicians | All roles |
| GET | `/field-technicians/{id}` | Get a technician | All roles |
| POST | `/field-technicians/{id}/deactivate` | Deactivate a technician | MeterOpsAdmin |
| POST | `/service-accounts` | Create a service account | MeterOpsAdmin |
| GET | `/service-accounts` | List accounts | All roles |
| GET | `/service-accounts/{id}` | Get an account | All roles |
| POST | `/service-accounts/{id}/suspend` | Suspend an account | MeterOpsAdmin |
| POST | `/service-accounts/{id}/reactivate` | Reactivate an account | MeterOpsAdmin |
| POST | `/service-accounts/{id}/close` | Close an account | MeterOpsAdmin |
| POST | `/meters` | Register a meter into stock | MeterOpsAdmin |
| GET | `/meters` | List meters | All roles |
| GET | `/meters/{id}` | Get a meter | All roles |
| POST | `/meters/{id}/install` | Install a meter at an account | MeterOpsAdmin |
| POST | `/meters/{id}/retire` | Retire a meter | MeterOpsAdmin |
| POST | `/meters/{id}/ami-reads` | Ingest an AMI head-end read | MeterOpsAdmin |
| POST | `/billing-cycle-periods` | Create a billing cycle period | MeterOpsAdmin |
| GET | `/billing-cycle-periods` | List periods | All roles |
| GET | `/billing-cycle-periods/{id}` | Get a period | All roles |
| POST | `/billing-cycle-periods/{id}/open-read-window` | Open the period's read window | BillingLiaison, MeterOpsAdmin |
| POST | `/billing-cycle-periods/{id}/close-read-window` | Close the read window | BillingLiaison, MeterOpsAdmin |
| POST | `/billing-cycle-periods/{id}/finalize-billing` | Finalize billing for the period | BillingLiaison |
| POST | `/billing-cycle-periods/{id}/close` | Close the period | BillingLiaison |
| POST | `/routes` | Create a route and generate its stops | Dispatcher |
| GET | `/routes` | List routes | All roles |
| GET | `/routes/{id}` | Get a route | All roles |
| GET | `/routes/{id}/stops` | List a route's stops in sequence order | All roles |
| POST | `/routes/{id}/assign` | Assign a technician to the route | Dispatcher |
| POST | `/routes/{id}/reassign` | Reassign the route (OCC-guarded) | Dispatcher |
| POST | `/routes/{id}/unassign` | Clear the route's assignment | Dispatcher |
| POST | `/routes/{id}/start` | Start the route | FieldTechnician |
| POST | `/routes/{id}/complete` | Complete the route | FieldTechnician |
| POST | `/routes/{id}/reconcile` | Reconcile the route and compute read rates | Dispatcher |
| POST | `/routes/{id}/cancel` | Cancel the route | Dispatcher |
| GET | `/route-stops` | List and filter stops | All roles |
| GET | `/route-stops/{id}` | Get a stop | All roles |
| POST | `/route-stops/{id}/reads` | Capture a field read on a stop | FieldTechnician, MeterOpsAdmin |
| POST | `/route-stops/{id}/mark-no-read` | Mark a stop as no-read | FieldTechnician |
| POST | `/route-stops/{id}/skip-hazard` | Skip a stop citing an active hazard | FieldTechnician |
| POST | `/route-stops/{id}/generate-estimate` | Generate an estimated read for a stop | BillingLiaison |
| GET | `/reads` | List and filter reads | All roles |
| GET | `/reads/{id}` | Get a read | All roles |
| POST | `/reads/{id}/validate` | Validate a provisional read | BillingLiaison |
| POST | `/reads/{id}/reject` | Reject a provisional read | BillingLiaison |
| POST | `/hazard-flags` | Report a hazard (merges on repeat report) | FieldTechnician |
| GET | `/hazard-flags` | List and filter hazard flags | All roles |
| GET | `/hazard-flags/{id}` | Get a hazard flag | All roles |
| POST | `/hazard-flags/{id}/clear` | Clear a hazard flag | FieldTechnician, Dispatcher, MeterOpsAdmin |
| POST | `/hazard-flags/{id}/renew` | Renew a hazard flag | FieldTechnician |
| POST | `/work-orders` | Create a field work order | Dispatcher |
| GET | `/work-orders` | List and filter work orders | All roles |
| GET | `/work-orders/{id}` | Get a work order | All roles |
| POST | `/work-orders/{id}/dispatch` | Dispatch a work order to a technician | Dispatcher |
| POST | `/work-orders/{id}/reschedule` | Reschedule a work order (OCC-guarded) | Dispatcher |
| POST | `/work-orders/{id}/start` | Start a work order | FieldTechnician |
| POST | `/work-orders/{id}/complete` | Complete a work order with its type-specific payload | FieldTechnician |
| POST | `/work-orders/{id}/verify` | Verify a completed work order | MeterOpsAdmin |
| POST | `/work-orders/{id}/request-rework` | Send a completed work order to rework | MeterOpsAdmin |
| POST | `/work-orders/{id}/cancel` | Cancel a work order | Dispatcher |
| POST | `/investigations` | Open a tamper/theft investigation | Investigator |
| GET | `/investigations` | List and filter investigations | All roles |
| GET | `/investigations/{id}` | Get an investigation | All roles |
| POST | `/investigations/{id}/begin-evidence` | Begin evidence gathering | Investigator |
| POST | `/investigations/{id}/submit-disposition` | Submit the investigation for disposition | Investigator |
| POST | `/investigations/{id}/request-more-evidence` | Return the investigation for more evidence | Investigator |
| POST | `/investigations/{id}/confirm-theft` | Confirm theft and compute the back-bill | Investigator |
| POST | `/investigations/{id}/clear` | Clear the investigation | Investigator |
| POST | `/investigations/{id}/close` | Close the investigation | Investigator |
| POST | `/replacement-campaigns` | Create a replacement campaign | MeterOpsAdmin |
| GET | `/replacement-campaigns` | List campaigns | All roles |
| GET | `/replacement-campaigns/{id}` | Get a campaign | All roles |
| POST | `/replacement-campaigns/{id}/open` | Open the campaign for enrollment | MeterOpsAdmin |
| POST | `/replacement-campaigns/{id}/enroll` | Enroll a batch of failed meters | MeterOpsAdmin |
| POST | `/replacement-campaigns/{id}/close` | Close the campaign | MeterOpsAdmin |
| GET | `/campaign-enrollments` | List and filter enrollments | All roles |
| GET | `/campaign-enrollments/{id}` | Get an enrollment | All roles |
| POST | `/ops-snapshots` | Run an operations checkpoint | MeterOpsAdmin |
| GET | `/ops-snapshots` | List snapshots | All roles |
| GET | `/ops-snapshots/{id}` | Get a snapshot | All roles |
| POST | `/ops-snapshots/{id}/finalize` | Finalize a snapshot and lock the SLA verdict | MeterOpsAdmin |
## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are defined by the narratives of §2 and §3 rather than restated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_TECHNICIAN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_READ_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_READ_WINDOW_STILL_OPEN` | 409 Conflict |
| `ERR_READ_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_ROUTE_OUTSIDE_READ_WINDOW` | 422 Unprocessable Entity |
| `ERR_WINDOW_DATE_ORDER` | 422 Unprocessable Entity |
| `ERR_READ_ROLLBACK` | 422 Unprocessable Entity |
| `ERR_ACTIVE_HAZARD_BLOCKS_READ` | 422 Unprocessable Entity |
| `ERR_SKIP_REQUIRES_ACTIVE_HAZARD` | 409 Conflict |
| `ERR_HAZARD_FLAG_NOT_ACTIVE` | 409 Conflict |
| `ERR_STOP_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_ROUTE_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_ROUTE_NOT_REASSIGNABLE` | 409 Conflict |
| `ERR_ROUTE_HAS_PENDING_STOPS` | 409 Conflict |
| `ERR_TECHNICIAN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TECHNICIAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_TECHNICIAN_HAS_OPEN_WORK` | 409 Conflict |
| `ERR_ESTIMATE_CAP_REACHED` | 409 Conflict |
| `ERR_INSUFFICIENT_READ_HISTORY` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_INVESTIGATION` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_WORK` | 409 Conflict |
| `ERR_ACCOUNT_HAS_INSTALLED_METER` | 409 Conflict |
| `ERR_DUPLICATE_ACCOUNT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL_NUMBER` | 409 Conflict |
| `ERR_METER_NOT_AVAILABLE_FOR_INSTALL` | 409 Conflict |
| `ERR_METER_NOT_INSTALLED_AT_ACCOUNT` | 409 Conflict |
| `ERR_METER_NOT_AMI` | 422 Unprocessable Entity |
| `ERR_INVESTIGATION_ALREADY_OPEN` | 409 Conflict |
| `ERR_EVIDENCE_PRESERVATION_HOLD` | 409 Conflict |
| `ERR_EXCHANGE_NOT_VERIFIED` | 409 Conflict |
| `ERR_BACKBILL_INPUT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CAMPAIGN_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN` | 409 Conflict |
| `ERR_METER_ALREADY_ENROLLED` | 409 Conflict |
| `ERR_CYCLE_HAS_UNRESOLVED_STOPS` | 409 Conflict |
| `ERR_ACCOUNT_MISSING_BILLABLE_READ` | 409 Conflict |

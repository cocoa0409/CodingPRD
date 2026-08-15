# Boatyard Refit API — Product Requirements Document

## 1. Introduction

Running a full-service boatyard is a choreography of heavy machinery, finite real estate, environmental regulation, and money. A vessel arrives, is lifted out of the water by the yard's single travel lift, is blocked on stands in a numbered row, accumulates daily storage charges while technicians and subcontractors execute bottom paint, mechanical, rigging, and seasonal work, and is finally splashed back into the water for a sea trial before the account is settled. Every one of those steps can fail independently: the lift has a hard 60-ton capacity rating, the stands in a row are finite, spring moratoria prohibit hauling during sensitive ecological windows, sanding runoff is regulated, and owners expect deposits before the yard commits the lift to a splash.

This document specifies the Boatyard Haul-Out & Refit Management API, mounted under the `/yard` prefix. It is written for the engineers who will implement the service. The API covers vessel registration and insurance tracking, refit job lifecycle from draft through closure, travel-lift slot scheduling with turnaround buffers, blocking-stand capacity management, work-order estimating with a change-order cycle, labor logging with subcontractor markup, owner-supplied parts policy, environmental event logging with an automatic violation cascade, compliance holds segregated by role, a double-entry-style job ledger with deposits and statements, a daily-close operations checkpoint that accrues storage tiered by lay-day count and season, and a test-driving logical clock that all date-sensitive rules read. The specification distinguishes contract-level detail (envelope shapes, pagination, role and state enumerations, error identifiers) from business behavior, which is deliberately presented as narrative workflow in Section 3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role that is not one of the declared roles below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); this also covers the kind-conditional segregation on compliance holds described below. All five roles are opaque-identity roles:

- `ServiceWriter` — yard service writer: intake, estimates, work orders, labor logging, parts inspection.
- `YardManager` — yard operations manager: lift schedule, rows and stands, sea trials, daily close, the logical clock.
- `EnvironmentalOfficer` — compliance officer: environmental logging, violation remediation, environmental holds.
- `Accountant` — yard accountant: payments, credits, deposits, voids, payment holds.
- `Owner` — vessel owner: approves estimates, requests changes, registers owner-supplied parts; scoped to their own vessels.

For `ServiceWriter`, `YardManager`, `EnvironmentalOfficer`, and `Accountant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against an entity `id`. For `Owner`, `X-User-ID` is likewise an opaque operator identifier, but it is matched against a stored field: each `Vessel` records the `owner_user_id` supplied at registration, and an `Owner` may act only on resources whose vessel's `owner_user_id` equals the request's `X-User-ID`. An owner attempting to approve a work order, request a change, register a part, or read a vessel-scoped resource (job, statement, work order, part) belonging to a different `owner_user_id` is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

Compliance-hold creation and release are kind-segregated: a hold of kind `ENVIRONMENTAL` may be created or released only by an `EnvironmentalOfficer`, and a hold of kind `PAYMENT` only by an `Accountant`; a mismatch between the caller's role and the hold kind is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are sorted by `created_at` ascending. The `meta` envelope of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Individual list endpoints may accept additional filter parameters (for example `owner_user_id`, `status`, `kind`, `row_id`, or `job_id`), which are described with the corresponding workflows in Section 3.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at` (both ISO 8601 UTC timestamps with three fractional digits) and a `version` integer that increments by one on every mutation of the resource. Two entity families are leaner by design: `LaborEntry` and `LedgerEntry` are append-only records that carry only `id` and `created_at` — neither `updated_at` nor `version` exists on them, because they are never mutated after creation (a ledger correction voids and re-posts rather than editing in place).

A vessel's registered dimensions — `name`, `owner_name`, `owner_user_id`, `loa_ft`, `beam_ft`, `hull_type` (one of `POWER` or `SAIL`), and `displacement_tons` — are fixed at registration; both `loa_ft` and `beam_ft` and `displacement_tons` must be greater than zero. The vessel's `loa_ft` later drives storage billing and its `displacement_tons` is cross-checked against the lift rating.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

Updating a refit job's editable fields requires the request to carry `expected_refit_job_version` holding the job's `version` as the client last observed it. If the job's current `version` no longer matches — because another writer has mutated the job since the client's read — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.

Creating a stand assignment against a yard row requires the request to carry `expected_yard_row_version` holding the row's `version` as the client last observed it. The capacity decision on `stands_in_use` must be based on a current view of the row; if the row's current `version` no longer matches — another assignment or release has landed since the read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.6. The Logical Yard Clock

All date-sensitive rules — insurance effective and expiry windows, the spring environmental moratorium, the winterization seasonal window, lift-slot windows and no-show detection, storage accrual, certificate expiry — read a single server-side logical clock, never the wall clock. At server startup the logical clock is exactly `2026-08-01T00:00:00Z`. A `YardManager` may advance it through a test-driving capability that sets the current UTC instant from a supplied `to_iso8601` value; the capability returns the new `current_utc`. The clock never falls back to wall-clock time on its own. "Current calendar date" throughout this document means the calendar date of the logical clock.

### 2.7. Monetary Precision and Rounding Discipline

All money is integer cents. Every monetary multiplication is rounded half-up to zero decimal places, and the rounding point is pinned per rule: quoted totals round the labor product only, before adding the parts allowance; labor lines round each line individually before any summation — never sum-then-round; daily storage rounds each calendar day's charge individually before any accumulation. Percentage comparisons (runoff thresholds) are evaluated at one decimal place, with the boundary inclusive: a measured value exactly at the violation threshold is a violation.

### 2.8. The Job Ledger

Each refit job carries an append-only ledger of `LedgerEntry` rows. A ledger entry has a `kind`, a `category`, an `amount_cents` that is always positive (the sign derives from the `kind`, never from a negative amount), an optional `memo`, and a `status` of `POSTED` or `VOIDED`. Through the API an `Accountant` may post entries of kind `PAYMENT`, `CREDIT`, or `DEPOSIT`; the kind `CHARGE` is system-created only and is rejected from API input with `ERR_VALIDATION`. Every API-posted entry is recorded with category `OTHER`; the system-assigned categories `STORAGE`, `LABOR`, and `PARTS_HANDLING` appear only on system-created charges. System charges trace their origin: a labor charge records the originating work order in `source_work_order_id`, and a parts-handling charge records the originating part in `source_part_id`; both fields are absent on any other entry.

The job's `balance_cents` is the sum of `amount_cents` over all `POSTED` entries of kind `CHARGE`, minus the sum of `amount_cents` over all `POSTED` entries of kind `PAYMENT`, `CREDIT`, or `DEPOSIT`. Voiding is the sole compensation mechanism: an `Accountant` may void a posted entry, moving it from `POSTED` to `VOIDED`, after which it contributes nothing to the balance or to statement aggregates. Posting then voiding the same entry leaves the balance unchanged. Manual entries may be posted only while the job is not `CANCELLED` or `CLOSED`; against a terminal job the post is rejected with `ERR_INVALID_STATE`.

### 2.9. Request Evaluation Order

Every request is evaluated against the following gates in this fixed order. Authentication comes first — missing or malformed headers or an undeclared role yield `ERR_UNAUTHENTICATED`. Authorization comes second — a role not permitted for the endpoint, including the kind-conditional hold segregation, yields `ERR_UNAUTHORIZED`. Ownership scope comes third — an `Owner` acting on a resource outside their `owner_user_id` scope yields `ERR_OWNERSHIP_MISMATCH`. Existence comes fourth — path- and body-referenced identifiers (vessel, job, slot, row, assignment, work order, part, event, hold, entry) are resolved left to right, and the first missing reference yields `ERR_NOT_FOUND`. Request shape comes fifth — missing required fields, invalid types, invalid enum membership, `scheduled_end` not strictly after `scheduled_start`, `end_date` before `start_date`, non-positive amounts, a `CHARGE` kind submitted through the ledger API, or subcontractor labor without a `subcontractor_name` all yield `ERR_VALIDATION`. Optimistic concurrency comes sixth — a stale `expected_refit_job_version` or `expected_yard_row_version` yields `ERR_STALE_VERSION`. State legality comes seventh — a wrong from-state yields `ERR_INVALID_STATE`, an entity already in a terminal state yields `ERR_ALREADY_TERMINAL`, and a splash booking against a job that is not ready yields `ERR_JOB_NOT_READY_FOR_SPLASH`. Only after all seven generic gates pass do the business rules of Section 3 apply, in the order each workflow narrative states them.

## 3. Business Logic & Workflows

### 3.1. Registering Vessels and Insurance

A `ServiceWriter` registers each vessel with its display identity and dimensions. Registration captures the vessel's `name`, the owner's display `owner_name`, the `owner_user_id` that later scopes every `Owner`-role action on this vessel, the length overall `loa_ft`, the `beam_ft`, the `hull_type` (`POWER` or `SAIL`), and the `displacement_tons` used at lift time. Vessels can be listed with pagination, optionally filtered by `owner_user_id`, and fetched individually by any role.

Insurance is tracked per vessel as `InsuranceCertificate` records. A `ServiceWriter` adds a certificate with the `vessel_id`, the insurer `provider`, the `policy_no`, the `liability_coverage_cents` (which must be positive, and must reach at least 100000000 cents — one million dollars — for the certificate to qualify a scheduled operation), the `effective_date`, and the `expiry_date`. A new certificate starts `ACTIVE`. The two dates form a half-open coverage window: a certificate covers a scheduled operation on date D only when `effective_date` is on or before D and `expiry_date` is strictly after D — a certificate expiring exactly on the operation date does not cover it.

When the yard needs the vessel's qualifying certificate at a reference date — at job submit, where the reference is the current date, or at slot booking, where the reference is the slot's scheduled start date — the selector considers the vessel's certificates that are `ACTIVE`, effective on or before the reference date, and expiring strictly after it. Among the candidates the selector ranks by `expiry_date` descending, breaking ties by `created_at` descending (never by `id`). An empty candidate set means no qualifying certificate, and the guarded operation is rejected with `ERR_INSURANCE_MISSING`. Slot booking adds a second requirement beyond selection: the selected certificate's `liability_coverage_cents` must be at least 100000000. Certificates of a vessel can be listed by `ServiceWriter`, `YardManager`, or the vessel's `Owner`. Certificates do not live forever: the daily close transitions any `ACTIVE` certificate whose `expiry_date` is before the current calendar date to `EXPIRED`, and `EXPIRED` is terminal.

### 3.2. Opening a Refit Job

A `ServiceWriter` opens a refit job for a vessel by supplying the `vessel_id`, an optional `billing_mode`, and optional free-text `scope_notes`. The `billing_mode` is `DAILY` or `MONTHLY_CONTRACT` and defaults to `DAILY` when omitted; it selects which storage-accrual variant the daily close will apply, and it is locked once the vessel is hauled. The new job starts in `DRAFT`. One active job per vessel is a hard rule: creating a job while the vessel already has a job in any non-terminal state is rejected with `ERR_DUPLICATE_ACTIVE_JOB`.

While a job remains in `DRAFT` or `INTAKE`, a `ServiceWriter` may still update its `billing_mode` or `scope_notes`; this is the OCC-guarded patch described in §2.5, requiring `expected_refit_job_version`, and it increments the job's `version` by one. Once the job has left `INTAKE` the patch is rejected with `ERR_INVALID_STATE`.

Submitting the job moves it from `DRAFT` to `INTAKE`. The submit gate is insurance: the vessel must have a qualifying certificate at the current date per the selection rule of §3.1; otherwise the submit is rejected with `ERR_INSURANCE_MISSING`. Jobs and their detail are readable by `ServiceWriter`, `YardManager`, `Accountant`, `EnvironmentalOfficer`, and the owning `Owner`; jobs of a vessel can be listed with an optional `status` filter alongside `limit` and `offset`.

A `ServiceWriter` may cancel a job at any point up to `READY_FOR_SPLASH`. Cancellation moves the job to `CANCELLED` and runs the full compensation set regardless of the starting state: every `BOOKED` lift slot of the job — including a `BOOKED` haul-out slot when cancelling from `HAUL_SCHEDULED`, and a `BOOKED` splash slot when cancelling from `READY_FOR_SPLASH` — becomes `CANCELLED`; every `ACTIVE` stand assignment becomes `RELEASED`, decrementing its row's `stands_in_use` by the assignment's `stands_used` and incrementing the row's `version` by one; every non-terminal work order — any of `ESTIMATE`, `APPROVED`, `IN_PROGRESS`, `ON_HOLD`, or `CHANGE_REQUESTED` — becomes `CANCELLED`. Ledger entries are deliberately not voided by cancellation: posted charges remain due. Cancellation accepts an optional free-text `reason`.

### 3.3. Scheduling the Haul: Lift Slots, Moratorium, and Capacity

The yard operates a single travel lift, scheduled through `LiftSlot` bookings made by a `YardManager`. Booking a slot requires the `job_id`, the slot `kind` (`HAUL_OUT` or `SPLASH`), the `scheduled_start` and `scheduled_end` window in ISO 8601 UTC, and the declared `vessel_displacement_tons`. The end of the window must be strictly after the start. A new slot starts `BOOKED`.

Three safety gates guard every booking, checked in this order after the generic gates of §2.9. First, the environmental moratorium: no `HAUL_OUT` slot may have a `scheduled_start` whose month-and-day falls within April 1 through May 31, inclusive on both ends; a booking inside that window is rejected with `ERR_ENV_MORATORIUM`. Second, the lift rating: the declared `vessel_displacement_tons` must be at most 60 tons, else the booking is rejected with `ERR_LIFT_CAPACITY_EXCEEDED`. Third, insurance: the vessel must have a qualifying certificate selected per §3.1 whose `expiry_date` is strictly after the `scheduled_start` date and whose `liability_coverage_cents` is at least 100000000, else the booking is rejected with `ERR_INSURANCE_MISSING`.

Beyond the safety gates, the single lift imposes a temporal-conflict rule. Every slot that is `BOOKED` or `COMPLETED` — across all jobs — competes for the lift, with a 30-minute turnaround buffer on each side. A new slot's window conflicts with an existing one when the new start falls before the existing end plus 30 minutes, and the existing start falls before the new end plus 30 minutes. Adjacency is allowed: when the existing window's end plus exactly 30 minutes equals the new start, there is no conflict, because the comparison is a strict inequality. `CANCELLED` and `NO_SHOW` slots occupy nothing. A conflicting booking is rejected with `ERR_LIFT_SLOT_CONFLICT`.

Booking a `HAUL_OUT` slot for a job in `INTAKE` automatically advances the job to `HAUL_SCHEDULED`. Booking a `SPLASH` slot carries two additional fiscal and readiness gates: the job must be in `READY_FOR_SPLASH`, else the booking is rejected with `ERR_JOB_NOT_READY_FOR_SPLASH`; and the job's deposit requirement must be satisfied, else the booking is rejected with `ERR_DEPOSIT_SHORTFALL`. The deposit requirement and its boundary rule are defined in §3.10. A job's slots can be listed by `YardManager` or `ServiceWriter`, filtered by `kind`, `status`, `limit`, and `offset`.

A `BOOKED` slot is completed by a `YardManager` only while the current logical time falls within the slot's window, both endpoints inclusive; completion outside the window is rejected with `ERR_INVALID_STATE`. Completing a `HAUL_OUT` slot additionally requires the job to hold an `ACTIVE` stand assignment at that moment — a vessel cannot be lifted with nowhere to stand — and is otherwise rejected with `ERR_STAND_ASSIGNMENT_MISSING`. On haul completion the job moves from `HAUL_SCHEDULED` to `ON_HARD`: `hauled_at` is set to the current calendar date (this is lay day 1), `lay_days` resets to 0, and `last_accrual_date` is null until the first accrual. Completing a `SPLASH` slot moves the job from `READY_FOR_SPLASH` to `AWAITING_TRIAL`, sets `splashed_at` to the current calendar date, and releases the job's `ACTIVE` stand assignment — the row's `stands_in_use` decreases by the assignment's `stands_used` and the row's `version` increments by one.

A `YardManager` may cancel a `BOOKED` slot. Cancelling a haul-out slot returns the job from `HAUL_SCHEDULED` to `INTAKE` so a new slot can be booked — the rebooking loop. The daily close also sweeps stale bookings: any slot still `BOOKED` whose `scheduled_end` is in the past becomes `NO_SHOW`, with the same rebooking side effect for haul-outs. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are all terminal for a slot; acting on a terminal slot yields `ERR_ALREADY_TERMINAL`.

### 3.4. Blocking and Stands

The hard-standing area is organized into `YardRow` records created by a `YardManager` with a yard-unique `code` (for example "A") and a `total_stands` count greater than zero. A row's `stands_in_use` is the running sum of `stands_used` over the row's `ACTIVE` assignments and starts at zero.

Assigning stands is a `YardManager` operation guarded by the row-level OCC rule of §2.5. The request supplies the `row_id`, the `job_id`, the `stands_used` (greater than zero), the occupancy window `start_date` and `end_date`, and the `expected_yard_row_version`. Both dates are inclusive — a closed interval — and `end_date` must not precede `start_date`. The job must be in `INTAKE`, `HAUL_SCHEDULED`, `ON_HARD`, or `WORK_IN_PROGRESS`; against any other job state the assignment is rejected with `ERR_INVALID_STATE`. A new assignment is `ACTIVE`, increments the row's `stands_in_use` by `stands_used`, and increments the row's `version` by one.

Row capacity is enforced under closed-interval intersection. An `ACTIVE` assignment covers every calendar date from its `start_date` through its `end_date`, both ends inclusive. Two assignments' windows intersect whenever each starts on or before the other's end — touching dates do intersect, because the intervals are closed. The projected occupancy of the row over the new window is the sum of `stands_used` across the row's `ACTIVE` assignments whose windows intersect the new one. The assignment is rejected with `ERR_STANDS_EXHAUSTED` only when the projected occupancy plus the requested `stands_used` strictly exceeds `total_stands`; an exactly-full row — projected plus requested equal to `total_stands` — is allowed.

Releasing an assignment — by a `YardManager`, or automatically through the splash-completion and job-cancel cascades — moves it from `ACTIVE` to `RELEASED`, decrements the row's `stands_in_use` by the assignment's `stands_used`, and increments the row's `version` by one. This is the compensating invariant: after release, `stands_in_use` returns to its pre-assignment value. `RELEASED` is terminal. Assignments are readable individually or as a paginated list filtered by `row_id`, `job_id`, and `status`.

### 3.5. Work Orders and the Change-Order Cycle

Work on a hauled vessel is organized into `WorkOrder` records created by a `ServiceWriter` against a job. The request carries the `job_id`, the work `type` — one of `BOTTOM_PAINT`, `MECHANICAL`, `ELECTRICAL`, `RIGGING`, `FIBERGLASS`, `WINTERIZATION`, or `SHRINK_WRAP` — a free-text `description`, and the quotation triple `quoted_hours`, `quoted_rate_cents`, and `quoted_parts_cents`, each of which must be zero or greater. The job must be in `DRAFT`, `INTAKE`, `HAUL_SCHEDULED`, `ON_HARD`, or `WORK_IN_PROGRESS`; creating a work order against any other job state is rejected with `ERR_INVALID_STATE`. A seasonal gate applies to winter work: a `WINTERIZATION` or `SHRINK_WRAP` work order may be created only when the current month-and-day falls within September 15 through December 15, inclusive; outside that window creation is rejected with `ERR_WINTERIZATION_WINDOW`.

A new work order starts in `ESTIMATE` with `revision` 0 and `change_note` empty until a first change request. Its `quoted_total_cents` is computed at creation as the product of `quoted_hours` and `quoted_rate_cents` rounded half-up to whole cents, plus `quoted_parts_cents` — the rounding applies to the labor product only, before the parts allowance is added.

The owner-facing approval loop begins when the `Owner` approves the estimate, moving the work order from `ESTIMATE` to `APPROVED`. Approval is ownership-scoped: the acting owner's `X-User-ID` must equal the vessel's `owner_user_id`, else the approval is rejected with `ERR_OWNERSHIP_MISMATCH`. A `ServiceWriter` then starts the approved work order, moving it from `APPROVED` to `IN_PROGRESS`. Starting is gated twice: the job must be in `ON_HARD` or `WORK_IN_PROGRESS` — the vessel must actually be on the hard — else `ERR_INVALID_STATE`; and the job must have no open compliance holds, else `ERR_OPEN_COMPLIANCE_HOLD`. When the first work order starts while the job is `ON_HARD`, the job automatically advances to `WORK_IN_PROGRESS`.

While a work order is `IN_PROGRESS`, either the `Owner` or a `ServiceWriter` may request a scope change, supplying a `change_note`; the work order moves to `CHANGE_REQUESTED` and the note is recorded. A `ServiceWriter` then re-quotes the change-requested work order with a fresh `quoted_hours`, `quoted_rate_cents`, and `quoted_parts_cents`: the quoted fields are replaced, `quoted_total_cents` is recomputed by the same formula as at creation, the `revision` increments by one, and the work order returns to `ESTIMATE` to await a fresh owner approval. This is the change-order cycle: `ESTIMATE → APPROVED → IN_PROGRESS → CHANGE_REQUESTED → ESTIMATE`, repeatable as scope evolves. Work orders are readable individually or as a paginated per-job list with an optional `status` filter.

### 3.6. Logging Labor and Subcontractor Rules

Against an `IN_PROGRESS` work order a `ServiceWriter` logs labor lines. Each line carries the `work_order_id`, the `worker_type` (`YARD_CREW` or `SUBCONTRACTOR`), the `hours` worked (greater than zero), the `rate_cents` per hour (greater than zero), and — required exactly when the `worker_type` is `SUBCONTRACTOR` — the `subcontractor_name`. Logging labor against a work order in any other state is rejected with `ERR_INVALID_STATE`; a missing `subcontractor_name` on subcontractor labor is rejected with `ERR_VALIDATION`. Yard policy prohibits subcontractor labor on `BOTTOM_PAINT` work orders outright, for environmental-liability reasons; such a line is rejected with `ERR_SUBCONTRACTOR_NOT_ALLOWED`.

Each line's `line_cost_cents` is the product of `hours`, `rate_cents`, and a markup factor, rounded half-up to whole cents per line. The markup is 1.15 for `SUBCONTRACTOR` lines and 1.0 for `YARD_CREW` lines — the yard's fifteen percent subcontractor uplift. The work order's `actual_cost_cents` is the sum of `line_cost_cents` over all of its labor lines, with no state filter because lines are append-only; the rounding order is pinned — round each line first, then sum, never the reverse. The estimate and actual variants intentionally diverge: the subcontractor markup exists only in the actual variant, and quoted hours and parts need not match logged lines. Labor lines are listed per work order, paginated, for `ServiceWriter`, `YardManager`, and `Accountant`.

Completing an `IN_PROGRESS` work order — a `ServiceWriter` action — moves it to `COMPLETE`. When the work order's `actual_cost_cents` is greater than zero, completion posts a system ledger charge of kind `CHARGE`, category `LABOR`, amount equal to `actual_cost_cents`, status `POSTED`, with `source_work_order_id` pointing at the completed work order. Completion also triggers the job's readiness re-evaluation described in §3.10.

Holds interrupt work automatically: when a compliance hold opens on the job, every `IN_PROGRESS` work order of the job becomes `ON_HOLD`; when the job's `open_hold_count` returns to zero, every `ON_HOLD` work order resumes to `IN_PROGRESS`. The sea-trial failure cascade of §3.10 can move a `COMPLETE` work order back to `CHANGE_REQUESTED`. Job cancellation moves any work order in `ESTIMATE`, `APPROVED`, `IN_PROGRESS`, `ON_HOLD`, or `CHANGE_REQUESTED` to `CANCELLED`, which is terminal.

### 3.7. Parts and Owner-Supplied Policy

Parts for a job are registered either by the `Owner` or by a `ServiceWriter`. Registration captures the `job_id`, a free-text `description`, the `category` (`BOTTOM_PAINT`, `MECHANICAL`, `ELECTRICAL`, `RIGGING`, or `OTHER`), the boolean `owner_supplied`, and the `declared_value_cents` (zero or greater), which is the basis of the owner-supplied handling fee. The job must be in `INTAKE`, `HAUL_SCHEDULED`, `ON_HARD`, `WORK_IN_PROGRESS`, or `READY_FOR_SPLASH`; otherwise registration is rejected with `ERR_INVALID_STATE`. Owner registration is ownership-scoped per §2.1. Yard policy prohibits owner-supplied bottom paint: a part with `owner_supplied` true and `category` `BOTTOM_PAINT` is rejected with `ERR_OWNER_PARTS_PROHIBITED`. A new part starts `EXPECTED` with no `inspect_note`.

When the part arrives, a `ServiceWriter` inspects it with an `outcome` and an optional `inspect_note`, which is recorded either way. Inspecting with outcome `RECEIVED` moves the part to `RECEIVED`; when the part is owner-supplied, inspection posts a system ledger charge of kind `CHARGE`, category `PARTS_HANDLING`, status `POSTED`, whose amount is ten percent of `declared_value_cents` rounded half-up to whole cents, with `source_part_id` pointing at the part. Inspecting with outcome `REJECTED` moves the part to `REJECTED` and charges no fee. Both outcomes are terminal. Parts of a job are listed with pagination and an optional `status` filter.

### 3.8. Environmental Compliance and the Violation Cascade

An `EnvironmentalOfficer` logs washdown, sanding, and paint-spray activity against a job as `EnvironmentalEvent` records, supplying the `job_id`, the event `kind` (`WASHDOWN`, `SANDING`, or `PAINT_SPRAY`), whether `containment_used` is true, and the measured `runoff_tss_ppm` (zero or greater). The job must be in `ON_HARD`, `WORK_IN_PROGRESS`, or `READY_FOR_SPLASH`; logging against any other job state is rejected with `ERR_INVALID_STATE`. The event's `occurred_at` is the current calendar date from the logical clock.

The event's initial `status` is computed from the runoff reading at creation. A reading of 100.0 ppm or higher is a violation — the boundary is inclusive, so exactly 100.0 is a violation — and the event is `VIOLATION_FLAGGED`. A reading of 50.0 ppm or higher but below 100.0 is `ADVISORY`. Below 50.0 ppm the event is simply `LOGGED`. `LOGGED` and `ADVISORY` are terminal.

A violation fires a four-hop cascade. Hop one: the system creates a `ComplianceHold` of kind `ENVIRONMENTAL`, source `AUTO_VIOLATION`, status `OPEN`, whose `source_event_id` references the event, and the job's `open_hold_count` increases by one. Hop two: readiness is revoked — if the job was `READY_FOR_SPLASH` it returns to `WORK_IN_PROGRESS`. Hop three: because the job left `READY_FOR_SPLASH`, every `BOOKED` splash slot of the job becomes `CANCELLED`. Hop four: every `IN_PROGRESS` work order of the job becomes `ON_HOLD`.

Remediating a flagged violation — an `EnvironmentalOfficer` action carrying a `remediation_note`, which is recorded — moves the event from `VIOLATION_FLAGGED` to `REMEDIATED`, which is terminal. Remediation releases the auto-created hold: the `AUTO_VIOLATION` hold becomes `RELEASED` and the job's `open_hold_count` decreases by one. When the count returns to zero, the job's `ON_HOLD` work orders resume to `IN_PROGRESS` and readiness re-evaluation runs. Events of a job are listed, paginated, for `EnvironmentalOfficer`, `YardManager`, and `ServiceWriter`.

### 3.9. Compliance Holds

Beyond the automatic violation holds, authorized staff may place manual holds on a job. Hold creation supplies the `job_id`, the `kind` (`ENVIRONMENTAL` or `PAYMENT`), and a free-text `note`. The kind is role-segregated: `ENVIRONMENTAL` holds are placed by an `EnvironmentalOfficer`, `PAYMENT` holds by an `Accountant`, and a kind-role mismatch is rejected with `ERR_UNAUTHORIZED`. The job must not be terminal; against a `CLOSED` or `CANCELLED` job, creation is rejected with `ERR_INVALID_STATE`. A manual hold is created `OPEN` with `source` `MANUAL` and no `source_event_id`.

Hold creation — manual or automatic — has the same side effects either way: the job's `open_hold_count` increases by one; if the job was `READY_FOR_SPLASH` it becomes `WORK_IN_PROGRESS`; every `BOOKED` splash slot of the job becomes `CANCELLED`; and every `IN_PROGRESS` work order of the job becomes `ON_HOLD`.

Releasing a manual hold moves it from `OPEN` to `RELEASED`, decrements the job's `open_hold_count` by one, and — when the count returns to zero — resumes the job's `ON_HOLD` work orders to `IN_PROGRESS` and runs readiness re-evaluation. Release is again role-segregated by kind: an `ENVIRONMENTAL` hold is released by an `EnvironmentalOfficer`, a `PAYMENT` hold by an `Accountant`, else `ERR_UNAUTHORIZED`. An `AUTO_VIOLATION` hold cannot be released through the manual release operation at all — attempting it is rejected with `ERR_INVALID_STATE`; only remediating the source environmental event releases it. `RELEASED` is terminal. Holds of a job are listed with an optional `status` filter for all roles.

### 3.10. Splash, Sea Trial, Deposits, and Readiness

Readiness for splash is a computed job property, re-evaluated on every work-order completion and every hold release. A job becomes `READY_FOR_SPLASH` — from either `ON_HARD` or `WORK_IN_PROGRESS` — when three conditions hold simultaneously: at least one of the job's work orders is `COMPLETE`; every work order of the job is in `COMPLETE` or `CANCELLED`; and the job's `open_hold_count` is zero. Readiness breaks symmetrically: when a compliance hold opens, or when a work order leaves the `COMPLETE`/`CANCELLED` set (as the sea-trial failure cascade does), a `READY_FOR_SPLASH` job returns to `WORK_IN_PROGRESS`, and every `BOOKED` splash slot of the job is cancelled as part of that transition.

Before a splash slot may be booked, the job must be `READY_FOR_SPLASH` (else `ERR_JOB_NOT_READY_FOR_SPLASH`) and the deposit gate must pass. The required deposit is one quarter of the sum of `quoted_total_cents` across the job's work orders in `APPROVED`, `IN_PROGRESS`, `ON_HOLD`, or `COMPLETE` — estimates and cancelled orders do not count — rounded half-up to whole cents. The posted deposits are the sum of `amount_cents` over the job's `POSTED` ledger entries of kind `DEPOSIT`. The requirement is satisfied when posted deposits are at least the required amount; the boundary is inclusive, so deposits exactly equal to the requirement pass. Booking a splash while short is rejected with `ERR_DEPOSIT_SHORTFALL`.

Completing the splash slot moves the job to `AWAITING_TRIAL` with the stand-release side effects described in §3.3. A `YardManager` then records the sea trial with an `outcome` and optional `notes`. A `PASS` outcome moves the job from `AWAITING_TRIAL` to `COMPLETE` and sets `completed_at` to the current calendar date. A `FAIL` outcome requires `failed_work_order_id` referencing one of the job's work orders that is currently `COMPLETE`; a reference to a work order in any other state is rejected with `ERR_INVALID_STATE`. On failure the job returns to `WORK_IN_PROGRESS` and the referenced work order becomes `CHANGE_REQUESTED` — hop two of the sea-trial-fail cascade — re-entering the change-order cycle of §3.5.

### 3.11. Statements, Daily Close, Storage Accrual, and Closure

The job's billing statement is a computed read available to `ServiceWriter`, `Accountant`, and the owning `Owner`. It reports the `job_id`, the `billing_mode`, the job `status`, the accrued `lay_days`, the per-category aggregates `storage_charges_cents`, `labor_charges_cents`, and `parts_handling_charges_cents`, the `total_charges_cents`, the `payments_cents`, `credits_cents`, and `deposits_cents` aggregates, the `balance_cents` per the ledger rule of §2.8, the current `required_deposit_cents` per the deposit rule of §3.10, and the boolean `deposit_satisfied`.

Once per logical day a `YardManager` runs the daily close, an operations checkpoint that executes four steps in a pinned order. Step one expires insurance: every `ACTIVE` certificate whose `expiry_date` is before the current calendar date becomes `EXPIRED`. Step two sweeps stale slots: every slot still `BOOKED` whose `scheduled_end` is in the past becomes `NO_SHOW`, and a no-show haul-out returns its job from `HAUL_SCHEDULED` to `INTAKE`. Step three accrues storage for every job in `ON_HARD`, `WORK_IN_PROGRESS`, or `READY_FOR_SPLASH`. Step four closes accounts: every `COMPLETE` job whose `balance_cents` is zero or negative becomes `CLOSED`, with `closed_at` set to the current calendar date. The checkpoint reports the `closed_date`, the count `storage_entries_posted`, and the identifier lists `expired_certificate_ids`, `no_show_slot_ids`, and `closed_job_ids`.

Storage accrual in step three walks each eligible job over every calendar date from the day after `last_accrual_date` — or from `hauled_at` when no accrual has run yet — through the current date, inclusive. A job whose `last_accrual_date` already equals the current date is skipped, so a same-day re-run of the close accrues nothing; the close is idempotent. Each accrued date carries a one-based lay-day index: the job's current `lay_days` plus the date's offset within the sweep. After the sweep, `lay_days` increases by the number of accrued dates and `last_accrual_date` becomes the current date.

Under the `DAILY` billing variant, each accrued date posts one ledger entry of kind `CHARGE`, category `STORAGE`. The per-day charge is the vessel's `loa_ft` multiplied by a marginal tier rate in cents per foot and by a winter multiplier, rounded half-up to whole cents per day — per-day rounding is pinned, never sum-then-round. The tier rate is 50 cents per foot for lay-day indexes 1 through 7, 65 cents per foot for indexes 8 through 30, and 85 cents per foot for index 31 and beyond. The winter multiplier is 0.85 when the accrued date's month-and-day falls within November 1 through March 31, inclusive, and 1.0 otherwise.

Under the `MONTHLY_CONTRACT` variant, storage posts in flat 30-day blocks: when the accrued date's lay-day index, reduced by one, is an exact multiple of 30 — that is, lay days 1, 31, 61, and so on — one ledger entry of kind `CHARGE`, category `STORAGE` posts for the vessel's `loa_ft` multiplied by 1400 cents per foot, rounded half-up. All other accrued dates post nothing. The two variants intentionally diverge: identical lay days produce different totals, with short stays cheaper under daily accrual than under a monthly block.

Closure is the end of the lifecycle. `CLOSED` and `CANCELLED` are the job's terminal states; any state-transition attempt against a terminal job — or against a terminal slot, assignment, hold, part, ledger entry, or remediated event — is rejected with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; operations that modify an existing resource, trigger a state transition, or perform a read return HTTP 200. Request and response bodies, side effects, and gating rules for each endpoint are specified in the narratives of Sections 2 and 3; this table is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /yard/vessels | Register a vessel | ServiceWriter |
| GET | /yard/vessels/{vesselId} | Get a vessel | ServiceWriter, YardManager, Accountant, EnvironmentalOfficer, Owner |
| GET | /yard/vessels | List vessels (paginated; optional owner filter) | ServiceWriter, YardManager, Accountant, EnvironmentalOfficer, Owner |
| POST | /yard/insurance-certificates | Add an insurance certificate to a vessel | ServiceWriter |
| GET | /yard/vessels/{id}/insurance-certificates | List certificates of a vessel | ServiceWriter, YardManager, Owner |
| POST | /yard/refit-jobs | Open a refit job for a vessel | ServiceWriter |
| GET | /yard/refit-jobs/{jobId} | Get a refit job | ServiceWriter, YardManager, Owner, Accountant, EnvironmentalOfficer |
| GET | /yard/vessels/{id}/refit-jobs | List refit jobs of a vessel | ServiceWriter, YardManager, Owner |
| PATCH | /yard/refit-jobs/{jobId} | Update billing_mode / scope_notes before haul (OCC-guarded) | ServiceWriter |
| POST | /yard/refit-jobs/{jobId}/submit | Submit job to intake (requires qualifying insurance) | ServiceWriter |
| POST | /yard/refit-jobs/{jobId}/cancel | Cancel a non-terminal job with compensation | ServiceWriter |
| GET | /yard/refit-jobs/{jobId}/statement | Computed billing statement for the job | ServiceWriter, Accountant, Owner |
| POST | /yard/refit-jobs/{jobId}/record-sea-trial | Record sea trial outcome | YardManager |
| POST | /yard/lift-slots | Book a travel-lift slot | YardManager |
| GET | /yard/refit-jobs/{id}/lift-slots | List lift slots of a job | YardManager, ServiceWriter |
| POST | /yard/lift-slots/{slotId}/complete | Complete a booked slot within its window | YardManager |
| POST | /yard/lift-slots/{slotId}/cancel | Cancel a booked slot | YardManager |
| POST | /yard/yard-rows | Create a blocking row | YardManager |
| GET | /yard/yard-rows/{rowId} | Get a yard row | YardManager, ServiceWriter |
| POST | /yard/stand-assignments | Assign blocking stands to a job (OCC-guarded on the row) | YardManager |
| GET | /yard/stand-assignments/{assignmentId} | Get a stand assignment | YardManager, ServiceWriter |
| GET | /yard/stand-assignments | List stand assignments (filter by row and/or job) | YardManager, ServiceWriter |
| POST | /yard/stand-assignments/{assignmentId}/release | Release an active stand assignment | YardManager |
| POST | /yard/work-orders | Create a work order on a job | ServiceWriter |
| GET | /yard/work-orders/{workOrderId} | Get a work order | ServiceWriter, YardManager, Owner |
| GET | /yard/refit-jobs/{id}/work-orders | List work orders of a job | ServiceWriter, YardManager, Owner |
| POST | /yard/work-orders/{workOrderId}/approve | Owner approves the estimate | Owner |
| POST | /yard/work-orders/{workOrderId}/start | Start an approved work order | ServiceWriter |
| POST | /yard/work-orders/{workOrderId}/request-change | Request a scope change | Owner, ServiceWriter |
| POST | /yard/work-orders/{workOrderId}/requote | Re-quote a change-requested work order | ServiceWriter |
| POST | /yard/work-orders/{workOrderId}/complete | Complete an in-progress work order | ServiceWriter |
| POST | /yard/labor-entries | Log a labor line on an in-progress work order | ServiceWriter |
| GET | /yard/work-orders/{id}/labor-entries | List labor entries of a work order | ServiceWriter, YardManager, Accountant |
| POST | /yard/parts | Register a part for a job | Owner, ServiceWriter |
| GET | /yard/refit-jobs/{id}/parts | List parts of a job | ServiceWriter, YardManager, Owner |
| POST | /yard/parts/{partId}/inspect | Inspect an expected part | ServiceWriter |
| POST | /yard/environmental-events | Log a washdown/sanding/spray event | EnvironmentalOfficer |
| GET | /yard/refit-jobs/{id}/environmental-events | List environmental events of a job | EnvironmentalOfficer, YardManager, ServiceWriter |
| POST | /yard/environmental-events/{eventId}/remediate | Remediate a flagged violation | EnvironmentalOfficer |
| POST | /yard/compliance-holds | Place a manual hold | Accountant, EnvironmentalOfficer |
| GET | /yard/refit-jobs/{id}/compliance-holds | List holds of a job | ServiceWriter, YardManager, Accountant, EnvironmentalOfficer, Owner |
| POST | /yard/compliance-holds/{holdId}/release | Release a manual hold | Accountant, EnvironmentalOfficer |
| POST | /yard/ledger-entries | Post a manual financial entry | Accountant |
| GET | /yard/refit-jobs/{id}/ledger-entries | List ledger entries of a job | Accountant, ServiceWriter, Owner |
| POST | /yard/ledger-entries/{entryId}/void | Void a posted entry | Accountant |
| POST | /yard/ops/run-daily-close | Run the daily-close operations checkpoint | YardManager |
| POST | /yard/_clock/set_current_utc | Set the logical clock (test-driving endpoint) | YardManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of Sections 2 and 3; this table lists only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_ENV_MORATORIUM | 409 |
| ERR_LIFT_CAPACITY_EXCEEDED | 409 |
| ERR_INSURANCE_MISSING | 409 |
| ERR_OPEN_COMPLIANCE_HOLD | 409 |
| ERR_LIFT_SLOT_CONFLICT | 409 |
| ERR_STANDS_EXHAUSTED | 409 |
| ERR_STAND_ASSIGNMENT_MISSING | 409 |
| ERR_OWNER_PARTS_PROHIBITED | 422 |
| ERR_WINTERIZATION_WINDOW | 422 |
| ERR_SUBCONTRACTOR_NOT_ALLOWED | 422 |
| ERR_DUPLICATE_ACTIVE_JOB | 409 |
| ERR_JOB_NOT_READY_FOR_SPLASH | 409 |
| ERR_DEPOSIT_SHORTFALL | 409 |

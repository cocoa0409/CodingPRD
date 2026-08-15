# Line Construction API — Product Requirements Document

## 1. Introduction

Electric utilities routinely contract the construction and maintenance of overhead and underground distribution lines to specialty line contractors under unit-price agreements: the utility publishes a schedule of bid items (a 35-foot pole set, a linear foot of conductor trench, a cubic yard of spoil hauled away), the contractor reports installed quantities daily, and payment follows measured, inspected, accepted units rather than lump-sum milestones. Managing such an engagement through phone calls and spreadsheets breaks down precisely where the money and the risk live — field production must reconcile against the utility's own material stock, outage windows must clear one another on shared circuits, storm duty must be compensated under premium pay rules, and a single serious safety incident must be able to stop all work on the contract at once.

This document specifies the API for the system of record that governs that engagement end to end. The system tracks contracts and their unit-price schedules, work packages and the crew and equipment assignments that staff them, daily production entries and the utility inspections that accept or reject them, utility-owned material issuance and reconciliation, outage coordination with the utility dispatcher, storm standby and call-out duty with premium pay, safety observations and incidents, and progress billing against completed units. The operating model is an approval chain spanning two organizations: the contractor's project manager and foremen propose, staff, and report, while the utility's inspectors and dispatchers examine, decide, release, and pay. Two quantities are conserved at all times — utility stock units and billable production units — and the API is built so that every movement of either can be traced back to the operation that caused it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representation contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` to identify the acting operator and `X-User-Role` to declare the capacity in which they act. The system recognizes exactly five roles: `CONTRACTOR_PM` (the contractor's project manager, who owns contract setup, work packages, crews, equipment, outage requests, and progress billing), `FOREMAN` (the contractor's field foreman, who runs crew and equipment assignments, daily production reporting, and material issuance and returns), `UTILITY_INSPECTOR` (the utility's inspector, who schedules and submits standard inspections and approves or rejects invoices), `UTILITY_DISPATCHER` (the utility's dispatcher, who manages utility stock, outage decisions and releases, storm activations, invoice payment, and contract resumption), and `SAFETY_OFFICER` (the safety officer, who logs safety observations and incidents and drives their review lifecycle).

A request whose `X-User-Role` header is missing or does not name one of the five declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity in this system is opaque for every role. For each of `CONTRACTOR_PM`, `FOREMAN`, `UTILITY_INSPECTOR`, `UTILITY_DISPATCHER`, and `SAFETY_OFFICER`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity: the server may record it for audit purposes, but it never compares `X-User-ID` against any resource's `id` or foreign-key field, and no ownership check is derived from it. Authorization decisions rest entirely on the declared role.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned in one page; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter sets how many items to skip before the page begins and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order — the oldest record first.

The `meta` object of a paginated list response carries the fields `limit`, `offset`, `total_count`, and `has_more`, so a caller can always tell how many records exist in total and whether further pages remain.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system — contracts, bid items, work packages, crews, equipment, assignments, production entries, stock items, material issues, inspections, outage requests, storm activations, safety events, and invoices alike — carries the same set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every modification of the resource.

Every mutation counts for versioning — including mutations produced by cascading side effects and derived-field recomputation rather than by a direct write to the resource. Creation of an assignment or of an invoice also increments the parent work package's `version` by one; posting a production entry increments the parent assignment's `version` by one; recording a stock receipt increments the stock item's `version` by one; lifecycle transitions increment the transitioning resource's `version` by one. No resource in this system omits `updated_at` or `version`.

### 2.5. The Logical Clock and Time-Derived Evaluation

The system maintains a logical clock rather than relying on wall-clock time. Before any client sets it, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own. A test-driving capability, available to all five roles, advances the clock to a supplied `to_iso8601` instant.

"Today" throughout this document means the calendar-date part of the logical clock. The date governs three time-derived behaviors. First, an assignment may only be activated when today falls inside its working date interval. Second, the computed availability statuses of crews and equipment are evaluated against today: an assignment covers its resource only from its first working date through its last, inclusive. Third, approved outage windows take effect lazily: whenever the clock is set, and whenever an outage request is read or referenced by another operation, an approved outage whose window contains the current logical time moves itself into effect. Advancing the clock therefore re-evaluates crew and equipment statuses and outage windows together.

### 2.6. Optimistic Concurrency Control on Field Writes

Two write operations protect their parent resource with optimistic concurrency control, and both require the client to state which version of the parent it last observed.

A request to report daily production against an assignment must carry `expected_assignment_version`, set to the assignment's `version` as the client last read it. If the assignment's current `version` has advanced since that read — for instance because another writer has posted a production entry against the same assignment, which legitimately advances the assignment's daily tally — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from recording production against a tally it has not observed.

Likewise, a request to create a progress-billing invoice for a work package must carry `expected_work_package_version`, matching the work package's current `version`. If the work package's version has advanced since the client last read it — for instance because another writer has created an invoice, which legitimately supersedes the prior billing view of the work package — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from billing from a billable-unit pool it has not observed.

Endpoints not named here do not accept an expected-version field; optimistic locking applies to exactly these two writes.

### 2.7. Units, Money, and Rounding Discipline

All monetary amounts in the system — unit prices, line extensions, retainage, invoice totals, and storm premium pay — are computed with decimal arithmetic and rounded half-up to exactly two decimal places. Rounding is always applied per component before any summation: each invoice line's extension is rounded before lines are summed, and each premium-pay component is rounded before components are added. Monetary values appear in API responses as plain numbers, never strings.

Quantities of installed units, material movements, and hours are exact numeric values with no rounding applied. Configuration and rate inputs, such as a crew's hourly rate or a contract's percentage parameters, preserve whatever precision the client supplies. Quantity comparisons against thresholds use exact numeric comparison, and wherever a boundary is inclusive this document says so explicitly.

### 2.8. Conservation Principles: Stock Accounts and the Billable Unit Pool

Two ledgers run through the system, and both are strictly conserved.

The first is the utility stock account. A stock item's `on_hand` is derived, never stored as an independent fact: it equals the item's `initial_on_hand`, plus the quantity of every receipt recorded against the item, minus the `quantity_issued` of every material issue drawn from it, plus the `quantity_returned` of those issues. Issuing a quantity and later returning the same quantity restores `on_hand` to its pre-issue value exactly.

The second is the billable unit pool of each bid item. For any bid item, the remaining billable quantity equals its `accepted_quantity` minus the units frozen onto lines of the same work package's invoices that stand in `SUBMITTED`, `APPROVED`, or `PAID` status. Billed plus remaining always equals accepted, for any partition of frozen invoices: submitting an invoice that bills some quantity and later voiding that same invoice leaves the remaining billable quantity unchanged. A bid item's `billed_quantity` is the sum, over those frozen non-void invoice lines, of each line's in-schedule plus overrun units.

### 2.9. Request Validation Order and Nested Path Resolution

Every request is evaluated against a fixed precedence ladder, so that when several rules would fail at once the error surfaced to the caller is deterministic. The ladder runs as follows:

1. Authentication — the `X-User-Role` header must be present and name a declared role, otherwise `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role must be permitted on the endpoint, otherwise `ERR_FORBIDDEN`.
3. Request shape — required fields present, enum values drawn from their declared sets, numeric constraints satisfied (positive quantities and rates, percentages in range), otherwise `ERR_INVALID_REQUEST`.
4. Existence — path identifiers are resolved left to right, then foreign-key references in the body; the first reference that does not exist is rejected with `ERR_NOT_FOUND`.
5. Stale-version checks — the two optimistic-concurrency writes of §2.6 compare the expected version against the parent's current `version` and reject with `ERR_STALE_VERSION` before any state evaluation.
6. Contract activity — operational writes require an `ACTIVE` contract, otherwise `ERR_CONTRACT_SUSPENDED` or `ERR_CONTRACT_NOT_ACTIVE` as described in §2.10.
7. Lifecycle and source-state gates — the entity must stand in a valid source state for the requested transition or child operation, otherwise `ERR_INVALID_STATE`; bid item creation outside `DRAFT` yields `ERR_BID_ITEMS_LOCKED`.
8. Work-safety gates — outage coverage for outage-dependent production (`ERR_OUTAGE_REQUIRED`) and equipment availability (`ERR_EQUIPMENT_DOWN`).
9. Business constraints — crew and equipment scheduling conflicts, outage-window clearance, storm-duty exclusivity, open-inspection uniqueness, the quantity ceiling, date-range well-formedness, return bounds, variance authorization, and the completion, resume, and close gates, each carrying its own error identifier.
10. Cross-contract referential integrity — every cross-reference must stay within one contract, otherwise `ERR_CROSS_CONTRACT_REFERENCE`.
11. Fiscal rules — billing-period non-overlap, billable-units presence, and stock sufficiency, otherwise `ERR_BILLING_PERIOD_OVERLAP`, `ERR_NO_BILLABLE_UNITS`, or `ERR_INSUFFICIENT_STOCK`.

The existence step's left-to-right order matters for nested paths: a request that addresses a child resource under a parent that does not exist fails on the parent first, and the caller receives `ERR_NOT_FOUND` for the leftmost missing identifier rather than a verdict on the child.

### 2.10. Stop-Work Authority: Contract Suspension and Its Exemptions

Operational writes are only accepted while the owning contract is `ACTIVE`. When the contract is `SUSPENDED`, such writes are rejected with `ERR_CONTRACT_SUSPENDED` (HTTP 409); when it is `DRAFT` or `CLOSED`, they are rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409). The gate covers work package transitions, assignment creation and transitions, production reporting, material issuance, returns and reconciliation, inspection scheduling and submission, outage requests and their downstream operations, storm activations, safety-event creation, and invoice creation and transitions.

Two exemptions keep the stop-work state escapable. Safety-event review transitions — moving an event to `UNDER_REVIEW` or `CLOSED` — remain available while the contract is suspended, so incidents logged before the suspension can be reviewed and closed; without this exemption, resumption would be unreachable. All read endpoints are likewise exempt and continue to serve normally.

Suspension itself is never requested directly. It is the system's response to a serious field incident: when a safety event of kind `INCIDENT` with severity `OSHA_RECORDABLE` or `FATAL` is created, the contract moves from `ACTIVE` to `SUSPENDED` automatically, and the stop-work cascade resolves everything in flight — every assignment of every work package of the contract standing in `PLANNED` or `ACTIVE` is moved to `CANCELLED`, and every outage request of every work package standing in `REQUESTED`, `APPROVED`, or `CHANGE_REQUESTED` is moved to `CANCELLED`. Resumption is a deliberate utility act, described in §3.8.

## 3. Business Logic & Workflows

### 3.1. Contract Setup and the Unit-Price Schedule

Everything begins when a `CONTRACTOR_PM` registers the engagement as a new contract, supplying the `utility_name`, a `contract_number` that must be unique across all contracts, and the agreement's `effective_start` and `effective_end` instants, with the end required to fall on or after the start. Three percentage parameters shape the billing behavior and may be omitted: `retainage_pct` defaults to 0.10 — one tenth of every invoice subtotal is withheld as retainage — and must always be at least 0 and strictly less than 1; `overrun_threshold_pct` defaults to 1.10, meaning cumulative accepted units up to one hundred ten percent of a bid item's estimate bill at the base price; and `quantity_cap_pct` defaults to 1.25, meaning reported production may never exceed one hundred twenty-five percent of the estimate. A new contract stands in `DRAFT`.

While the contract is in `DRAFT`, the project manager builds the unit-price schedule one bid item at a time. Each bid item carries an `item_code` drawn from the utility's schedule — a value such as OH-POLE-35 — that must be unique within the contract, a free-text `description`, a `unit` of measure drawn from `EACH`, `LF`, `CY`, and `HR`, a strictly positive `unit_price`, and a strictly positive `estimated_quantity`. An optional `overrun_rate` sets the price applied to units beyond the overrun threshold; when it is left unset, overrun units bill at the base `unit_price`. Every bid item also exposes two running totals that both start at zero: `accepted_quantity`, the sum of `quantity_reported` over the item's production entries standing in `ACCEPTED`, and `billed_quantity`, the frozen units already placed on submitted-or-later invoices as defined in §2.8. A read of a single bid item always includes both totals.

Activation is the project manager's act: a contract transition request with `to` set to `ACTIVE` moves the contract from `DRAFT` to `ACTIVE`, but only when at least one bid item exists — otherwise the request fails with `ERR_INVALID_STATE`. The moment the contract leaves `DRAFT`, the schedule locks: any further attempt to add a bid item is rejected with `ERR_BID_ITEMS_LOCKED`. Closure is the mirror act at the end of the engagement — a transition with `to` set to `CLOSED` succeeds only when every work package of the contract has reached a terminal state, `COMPLETED` or `CANCELLED`; while any work package remains open the close is rejected with `ERR_OPEN_WORK_PACKAGES`. The bid-item and work-package collections can be listed with an optional `contract_id` filter, and work packages additionally by `status`.

### 3.2. Crews, Equipment, and the Assignment Window

Field resources are registered once and reused across contracts. A `CONTRACTOR_PM` registers a crew with a unique `crew_code`, a `crew_type` of `OVERHEAD`, `UNDERGROUND`, or `STORM`, a strictly positive `base_rate_per_hour` — the straight-time hourly rate that anchors storm premium pay — and an optional `home_depot` naming its home service center. Equipment registers similarly, with a unique `equipment_code`, a `kind` of `BUCKET_TRUCK`, `DIGGER_DERRICK`, `TRENCHER`, or `REEL_TRAILER`, a strictly positive `daily_rate`, and an optional `maintenance_flag` that defaults to false and, when true, marks the unit as down for maintenance. At registration both kinds of resource compute their status as `AVAILABLE`.

Availability is a computed status, re-derived on every read and after every assignment transition, storm activation change, and clock movement. A crew reads `CALLOUT` when an `ACTIVE` storm activation of kind `CALLOUT` references it; failing that, `STANDBY` when an `ACTIVE` storm activation of kind `STANDBY` references it; failing that, `ASSIGNED` when an `ACTIVE` assignment covers it from its first through its last working date inclusive, measured against the logical clock's date; otherwise `AVAILABLE`. Equipment reads `IN_USE` when an `ACTIVE` assignment covers it by the same date rule, and `AVAILABLE` otherwise. The crew list supports filtering by `crew_type` and `status`, and the equipment list by `kind` and `status`.

Work packages decompose the contract into buildable scopes. The project manager creates one under an `ACTIVE` contract with a `name`, a `location` describing the feeder, address, or mileage, and an optional `requires_outage` flag — false by default, and true only when production may be reported solely under a live outage window. A new work package stands in `PLANNED`. Its lifecycle proceeds by transition requests naming `to`: from `PLANNED` to `MOBILIZED`, which requires the contract to be `ACTIVE` and otherwise surfaces `ERR_CONTRACT_NOT_ACTIVE` or `ERR_CONTRACT_SUSPENDED`; from `MOBILIZED` to `IN_PROGRESS`, which requires at least one assignment of the package to stand in `PLANNED` or `ACTIVE` and otherwise fails with `ERR_INVALID_STATE`; from `IN_PROGRESS` to `PUNCH` without further preconditions; and from `PUNCH` to `COMPLETED`, which is gated twice — the package's `rework_open_count` must be zero or the transition fails with `ERR_OPEN_REWORK`, and its `open_material_issue_count` must be zero or it fails with `ERR_OPEN_MATERIAL_ISSUES`. A work package may instead be cancelled from `PLANNED`, `MOBILIZED`, or `IN_PROGRESS`; cancellation moves every assignment standing in `PLANNED` or `ACTIVE` to `CANCELLED` and voids every invoice in `DRAFT` or `REJECTED`, releasing their frozen unit pool. Every transition increments the work package's `version` by one. Two counters ride on the package and appear on every read of it: `rework_open_count`, the number of production entries reported under its assignments that currently stand in `REWORK_REQUIRED`, and `open_material_issue_count`, the number of its material issues still `OPEN`.

Staffing a work package is the foreman's job. The foreman creates an assignment by naming a `crew_id`, an `equipment_id`, and a closed working interval from `start_date` through `end_date`, both inclusive; an `end_date` earlier than the `start_date` is rejected with `ERR_INVALID_DATE_RANGE`. The work package must stand in `MOBILIZED` or `IN_PROGRESS`, or the create fails with `ERR_INVALID_STATE`. Three independent exclusions then apply: equipment whose `maintenance_flag` is true cannot be assigned and yields `ERR_EQUIPMENT_DOWN`; a crew holding an `ACTIVE` storm activation cannot take a regular assignment and yields `ERR_CREW_ON_STORM_DUTY`; and neither the crew nor the equipment may already hold an assignment in `PLANNED` or `ACTIVE` whose closed date interval overlaps the requested one — intervals overlap when each starts on or before the other ends, while pure adjacency, where the next assignment starts after the prior one ends, is allowed — yielding `ERR_CREW_SCHEDULE_CONFLICT` or `ERR_EQUIPMENT_SCHEDULE_CONFLICT` respectively. A new assignment stands in `PLANNED`, and creating one increments the work package's `version` by one.

Once mobilized, the foreman drives the assignment through its own lifecycle with `to`. Activation — from `PLANNED` to `ACTIVE` — requires the logical clock's date to fall on or after the `start_date` and on or before the `end_date`, and the work package to stand in `MOBILIZED` or `IN_PROGRESS`; violations surface as `ERR_INVALID_STATE`. Activation recomputes the crew's and equipment's statuses, which may turn to `ASSIGNED` and `IN_USE`. Completion — from `ACTIVE` to `COMPLETED` — requires that no production entry of the assignment stands in `SUBMITTED` or `REWORK_REQUIRED`, again enforced as `ERR_INVALID_STATE`. Cancellation is permitted from either `PLANNED` or `ACTIVE`, and also arrives unbidden through the contract suspension cascade of §2.10. Each assignment transition increments the assignment's `version` by one. The assignment collection lists with filters on `work_package_id`, `crew_id`, `equipment_id`, and `status`, and a single read includes the assignment's current `version`, which the foreman needs for production reporting.

### 3.3. Daily Production and the Quantity Ceiling

Each working day, the foreman reports what the crew installed. A production entry is created against an assignment with a payload naming the `bid_item_id` the work counts against, the `work_date` the units were installed, a strictly positive `quantity_reported`, and the OCC field `expected_assignment_version` described in §2.6. A new entry stands in `SUBMITTED` with its `rework_count` at zero, and posting it increments the assignment's `version` by one.

Three layers of gates protect the report. The lifecycle gate requires the work package to stand in `IN_PROGRESS`, the assignment to be `ACTIVE`, and the `work_date` to fall inside the assignment's working interval, both ends inclusive — any violation is `ERR_INVALID_STATE`. The referential gate requires the named bid item to belong to the same contract as the work package the assignment serves, otherwise `ERR_CROSS_CONTRACT_REFERENCE`. And the outage gate, for any work package whose `requires_outage` flag is true, demands that an outage request belonging to that same work package stand `IN_EFFECT` with a window covering the entry's `work_date`; without such coverage the report is rejected with `ERR_OUTAGE_REQUIRED`.

Above those gates sits the quantity ceiling. The cumulative `quantity_reported` across the bid item's entries standing in `SUBMITTED` or `ACCEPTED`, plus the quantity now being reported, must not exceed the bid item's `estimated_quantity` multiplied by the contract's `quantity_cap_pct` — one hundred twenty-five percent of the schedule by default. Equality is permitted: the check rejects only a strict excess, with `ERR_QUANTITY_CAP_EXCEEDED` (HTTP 422). Entries in `REWORK_REQUIRED` or `VOID` are excluded from the cumulative figure, so a rejected-then-voided report does not consume headroom.

Rework and withdrawal close the loop. When an entry has been kicked back to `REWORK_REQUIRED` by inspection, the foreman resubmits it after correction; resubmission re-applies the quantity ceiling exactly as at creation — `ERR_QUANTITY_CAP_EXCEEDED` again on excess — returns the entry to `SUBMITTED`, increments its `rework_count` by one, decrements the work package's `rework_open_count` by one, and, when that counter falls back to zero, clears the `hold_reason` of every `DRAFT` invoice of the work package to null. The foreman may instead void an entry standing in `SUBMITTED` or in `REWORK_REQUIRED`, moving it to `VOID`; voiding a rework entry likewise decrements `rework_open_count` by one and clears invoice holds when the counter reaches zero. The production-entry collection lists with filters on `assignment_id`, `bid_item_id`, and `status`, and a single read shows the entry's status and `rework_count`.

### 3.4. Utility Material: Issuance, Return, and Reconciliation

Material for utility work is utility-owned. A `UTILITY_DISPATCHER` registers each stock item under its contract with a `material_code` that is unique within the contract, a `description`, a free-text `uom` such as EACH or LF, and an optional `initial_on_hand` opening balance that defaults to zero and may not be negative; the item's `on_hand` starts equal to `initial_on_hand`. Additional stock arrives through receipts: each receipt carries a `quantity` that is added to `on_hand` and increments the stock item's `version` by one. The stock ledger then obeys the conservation rule of §2.8 at all times. The stock-item collection lists with an optional `contract_id` filter, and a single read exposes the current `on_hand`.

Drawing material is a foreman's act against a work package: the issue names a `stock_item_id` and a strictly positive `quantity_issued`. The work package must stand in `IN_PROGRESS`, otherwise `ERR_INVALID_STATE`; the stock item must belong to the same contract as the work package, otherwise `ERR_CROSS_CONTRACT_REFERENCE`; and the draw may not exceed the stock on hand — `quantity_issued` at most `on_hand`, with equality permitted so the shelf may be drawn to exactly zero, and any excess rejected as `ERR_INSUFFICIENT_STOCK` (HTTP 422). A successful issue stands `OPEN` with `quantity_returned` at zero and `quantity_installed` unset; it immediately subtracts the issued quantity from `on_hand` and adds one to the work package's `open_material_issue_count`.

Unused material comes back through returns. A return names a `quantity`, which is added both to the issue's `quantity_returned` and to the stock item's `on_hand`. A return that would push the cumulative `quantity_returned` above the original `quantity_issued` is rejected with `ERR_RETURN_EXCEEDS_ISSUED`.

Reconciliation closes an issue by declaring how much material actually went into the ground. The reconcile call carries `quantity_installed` and, when needed, a `variance_note`. Two paths exist. When installed plus returned exactly equals issued, a foreman reconciles directly: the issue moves to `RECONCILED`, its `variance` is recorded as zero, and the package's `open_material_issue_count` drops by one. When the quantities do not balance, only a `CONTRACTOR_PM` may reconcile, and only with a non-empty `variance_note` explaining the difference; the issue then moves to `VARIANCE_RECONCILED` with `variance` recorded as the issued quantity minus the installed quantity minus the returned quantity, and the counter likewise drops by one. A foreman attempting the variance path, or a variance reconciliation submitted without a note, is rejected with `ERR_MATERIAL_VARIANCE_UNRESOLVED`. The material-issue collection lists with filters on `work_package_id`, `stock_item_id`, and `status`, and a single read shows all four quantities, the `variance`, and the status.

### 3.5. Inspection and the Rework Loop

Utility acceptance of production is inspection-driven. A `UTILITY_INSPECTOR` schedules an inspection under a work package by naming the `production_entry_id` to be examined — the entry must belong to that work package, otherwise `ERR_CROSS_CONTRACT_REFERENCE` — and the `standard_code` of the governing utility construction standard, a reference such as UTIL-OH-12.4. The entry under inspection is one that has been reported and stands in `SUBMITTED`. At most one inspection per production entry may be open at a time: scheduling a second while one still stands `SCHEDULED` is rejected with `ERR_INSPECTION_ALREADY_OPEN`. A new inspection stands in `SCHEDULED` with its `result` unset.

Submitting the result is the pivotal act. The inspector records a `result` of `PASS` or `FAIL`; the entry under inspection must still stand in `SUBMITTED`, or the submission fails with `ERR_INVALID_STATE`. A passing result moves the inspection to `PASSED` and the production entry from `SUBMITTED` to `ACCEPTED`, which adds the entry's `quantity_reported` to the bid item's `accepted_quantity` and forces every `DRAFT` invoice of the work package to recompute its lines, `subtotal`, `retainage_amount`, and `amount_due`. A failing result moves the inspection to `FAILED` and the entry from `SUBMITTED` to `REWORK_REQUIRED`, which raises the work package's `rework_open_count` by one — and when that counter rises from zero to one, every `DRAFT` invoice of the work package takes on a `hold_reason` of `OPEN_REWORK`, flagging that billing is blocked until the rework clears. The inspection collection lists with filters on `work_package_id`, `production_entry_id`, and `result`.

### 3.6. Outage Coordination and Switching Windows

Work on energized facilities is sequenced through outage requests. The project manager requests a window under a work package by naming the `circuit_id` being switched out and the proposed `window_start` and `window_end` instants; the end must fall strictly after the start, or the request is rejected with `ERR_INVALID_DATE_RANGE`, and the work package must not yet be terminal, otherwise `ERR_INVALID_STATE`. A new request stands in `REQUESTED`.

The decision belongs to the `UTILITY_DISPATCHER`, who records a `decision` of `APPROVED` or `DENIED`. Approval runs a clearance check on the circuit: for every other outage request on the same `circuit_id` standing in `APPROVED` or `IN_EFFECT`, the new window must either begin at least sixty minutes after the other window ends or end at least sixty minutes before the other window begins. A gap of exactly one hour satisfies the buffer; anything tighter is rejected with `ERR_OUTAGE_WINDOW_CONFLICT`. Denial needs no check and moves the request to `DENIED`, which is terminal.

Plans change, and an approved window can be renegotiated. The project manager may propose a new window for an `APPROVED` request, again with a `window_start` strictly before the `window_end` under the same date-range rule; the request moves to `CHANGE_REQUESTED` and the proposal is stored in `requested_window_start` and `requested_window_end` without disturbing the operative window. Re-approval from `CHANGE_REQUESTED` applies the same sixty-minute clearance check to the proposed window, then adopts it: `window_start` and `window_end` are overwritten from the requested values and both requested fields are cleared to null. Denial from `CHANGE_REQUESTED` is terminal, exactly as from `REQUESTED`.

Taking effect is the system's act, not a client's. Whenever the logical clock enters an approved window — the current time falling on or after `window_start` and on or before `window_end` — the request moves from `APPROVED` to `IN_EFFECT`. The evaluation is lazy: it runs whenever the clock is set and whenever the request is read or referenced by another operation, including list reads. Once live, the dispatcher releases the outage, moving it from `IN_EFFECT` to `RELEASED`, and the project manager may cancel a request standing in `REQUESTED`, `APPROVED`, or `CHANGE_REQUESTED`, moving it to `CANCELLED` — the suspension cascade of §2.10 can force the same cancellation. Recall from §3.3 that an `IN_EFFECT` window belonging to the work package is what authorizes production on outage-dependent packages. The outage collection lists with filters on `work_package_id`, `circuit_id`, and `status`.

### 3.7. Storm Duty: Standby, Call-Out, and Premium Pay

When weather threatens, the utility places contractor crews on storm duty. A `UTILITY_DISPATCHER` creates a storm activation under a contract, naming the `crew_id`, the `kind` — `STANDBY` to hold the crew ready, `CALLOUT` to send it to work — and the `activation_date`. A crew may hold at most one `ACTIVE` activation at a time; a second activation for the same crew is rejected with `ERR_DUPLICATE_ACTIVE_STANDBY`. A new activation stands `ACTIVE` with `converted` false, and its creation recomputes the crew's status, which turns to `STANDBY` or `CALLOUT` accordingly.

A standby posting that turns into real work is converted rather than recreated: converting requires the activation's `kind` to be `STANDBY` — attempting to convert a call-out fails with `ERR_INVALID_STATE` — and sets `kind` to `CALLOUT` and `converted` to true, with the crew's status recomputed from `STANDBY` to `CALLOUT`.

Closing an activation is where premium pay is computed. The dispatcher closes with `hours_standby` and `hours_worked`, each at least zero, and the system computes `premium_pay` before resting the activation in `CLOSED` and recomputing the crew's status. The formula has two variants, and the `converted` flag decides between them. A pure call-out — created as `CALLOUT` and never converted — credits the greater of `hours_worked` and four hours at double the crew's `base_rate_per_hour`, rounded half-up to two decimal places; standby hours are not credited in this variant, so the four-hour minimum is a pure call-out guarantee. A standby-convert — created as `STANDBY` and later converted — credits `hours_standby` at one half of the crew's `base_rate_per_hour` plus `hours_worked` at double that rate, each component rounded half-up to two decimal places separately before being summed, with no minimum-hours guarantee; identical worked hours therefore price differently under the two variants. Cancellation moves an `ACTIVE` activation to `CANCELLED` without recording hours, and recomputes the crew's status. The storm-activation collection lists with filters on `contract_id`, `crew_id`, and `status`, and a single read exposes the `kind`, `converted` flag, recorded hours, and computed `premium_pay`.

### 3.8. Safety Observations, Incidents, and Resumption

Safety reporting runs alongside production. A `SAFETY_OFFICER` logs an event under a work package with a `kind` of `OBSERVATION` or `INCIDENT`, a `severity` of `POSITIVE`, `AT_RISK`, `OSHA_RECORDABLE`, or `FATAL`, a free-text `description`, and an optional `crew_id` identifying the crew involved. Creation is an operational write and requires an `ACTIVE` contract per §2.10. A new event stands `OPEN`.

The serious cases move the whole contract. Logging an `INCIDENT` with severity `OSHA_RECORDABLE` or `FATAL` suspends the contract immediately, executing the stop-work cascade described in §2.10 — in-flight assignments and outage requests across every work package of the contract are cancelled. Lesser events, observations, and positive findings leave the contract untouched.

Review proceeds on the safety officer's own track: an event moves from `OPEN` to `UNDER_REVIEW` and from `UNDER_REVIEW` to `CLOSED` through transition requests naming `to`. Per the §2.10 exemption, these review transitions remain available while the contract is `SUSPENDED`, so the incidents that caused a stop-work can be worked to closure.

Resumption is the dispatcher's deliberate act: a contract transition with `to` set to `ACTIVE` moves a `SUSPENDED` contract back to `ACTIVE`, but only when no safety event of kind `INCIDENT` stands in `OPEN` or `UNDER_REVIEW` on any work package of the contract — while one remains, the resume is rejected with `ERR_SAFETY_EVENT_OPEN`. The safety-event collection lists with filters on `work_package_id`, `crew_id`, `kind`, and `status`.

### 3.9. Progress Billing and Invoicing

Billing converts accepted production into money, period by period. The project manager creates an invoice under a work package by naming the `period_start` and `period_end` dates — the end on or after the start, both inclusive, otherwise `ERR_INVALID_DATE_RANGE` — together with the OCC field `expected_work_package_version` described in §2.6. The work package must stand in `IN_PROGRESS`, `PUNCH`, or `COMPLETED`, otherwise `ERR_INVALID_STATE`, and the new period may not overlap the period of any other non-`VOID` invoice of the same work package: two periods coexist only when one starts after the other ends, and any overlap is rejected with `ERR_BILLING_PERIOD_OVERLAP`. A new invoice stands in `DRAFT`, and creating one increments the work package's `version` by one.

An invoice's body is its `lines`, one per bid item of the contract, each recording the `bid_item_id` and `item_code`, the split of units into `in_schedule_units` and `overrun_units`, the `in_schedule_rate` and `overrun_rate_applied`, and the line's `extension_amount`. While the invoice is in `DRAFT`, the lines are recomputed live — at creation, on every read of the invoice, and whenever inspection acceptance moves production under the work package — always on the final basis, where only `ACCEPTED` production counts.

The per-line computation runs as follows. The eligible units are the sum of `quantity_reported` over the bid item's `ACCEPTED` entries whose `work_date` falls inside the invoice period, both ends inclusive. From these, subtract the units the bid item has already contributed to lines of the same work package's invoices standing in `SUBMITTED`, `APPROVED`, or `PAID`; the billable quantity is the remainder, or zero when that remainder would be negative. Tier positioning uses the bid item's cumulative acceptance history: the threshold, in whole units, is the largest whole number not exceeding `estimated_quantity` multiplied by the contract's `overrun_threshold_pct` — one hundred ten percent of the estimate by default. The prior cumulative accepted quantity — the bid item's `accepted_quantity` minus this period's eligible units — positions the boundary. `in_schedule_units` is then the larger of zero and the smaller of the billable quantity and the threshold minus the prior cumulative accepted quantity; `overrun_units` is whatever of the billable quantity remains. The `overrun_rate_applied` is the bid item's `overrun_rate` when one is set, otherwise its base `unit_price`; the `in_schedule_rate` is always the base `unit_price`. The `extension_amount` is the in-schedule units multiplied by the `unit_price`, rounded half-up to two decimal places, plus the overrun units multiplied by the applied overrun rate, also rounded half-up to two decimal places — the two components rounded separately, then added.

Totals follow a pinned rounding order: lines first, then the sum. The `subtotal` is the sum of the already-rounded per-line `extension_amount` values, with no further rounding applied. Rounding only after summation is forbidden: two lines of 100.005 round to 100.01 each and total 200.02, whereas summing the raw values to 200.01 and rounding once would yield 200.01 — the pinned order always produces 200.02. The `retainage_amount` is the `subtotal` multiplied by the contract's `retainage_pct`, rounded half-up to two decimal places, and the `amount_due` is the `subtotal` minus the `retainage_amount`.

Submission turns the draft into a claim. A transition with `to` set to `SUBMITTED` requires the work package's `rework_open_count` to be zero — open rework blocks billing with `ERR_OPEN_REWORK` — and at least one line whose in-schedule plus overrun units exceed zero, otherwise `ERR_NO_BILLABLE_UNITS` (HTTP 422). On submission the lines and the computed `subtotal`, `retainage_amount`, and `amount_due` freeze, and each bid item's `billed_quantity` rises by its line's total units, debiting the billable pool of §2.8. The `hold_reason` field, set to `OPEN_REWORK` on drafts while rework stands open per §3.5, must have cleared before submission can succeed.

Utility review and payment complete the chain. The `UTILITY_INSPECTOR` moves a `SUBMITTED` invoice to `APPROVED` or to `REJECTED`; the `UTILITY_DISPATCHER` moves an `APPROVED` invoice to `PAID`. Rejection is not the end: the project manager may revise a `REJECTED` invoice back to `DRAFT`, which unfreezes the lines, returns each line's units to the pool by lowering each bid item's `billed_quantity` accordingly, and resumes live recomputation. Voiding is available to the project manager from `DRAFT`, `REJECTED`, or `SUBMITTED` — from the first two the invoice simply becomes `VOID` (the work-package cancellation cascade of §3.2 forces the same), while voiding a `SUBMITTED` invoice additionally restores each line's units by lowering `billed_quantity`, returning the frozen units to the remaining billable pool exactly as §2.8 conserves.

Before committing to a period, anyone on the working team may run a computed billing preview: a transient, invoice-shaped view of the same computation for a supplied `period_start` and `period_end`, which persists nothing. Passing the `variant` parameter as `provisional` widens the eligible-units basis to count `SUBMITTED` entries alongside `ACCEPTED` ones, so identical production data yields a larger preview total whenever un-inspected entries exist; without that value the preview uses the final basis. The preview is available to the `CONTRACTOR_PM`, `FOREMAN`, `UTILITY_INSPECTOR`, and `UTILITY_DISPATCHER`. The invoice collection itself lists with filters on `work_package_id` and `status`, and a read of a single invoice exposes its lines, totals, `hold_reason`, and status.

## 4. Endpoint Definitions

Operations that create a new resource — a contract, bid item, work package, crew, equipment item, assignment, production entry, stock item, material issue, inspection, outage request, storm activation, safety event, or invoice — return `201 Created`. Operations that read, transition, or otherwise modify an existing resource return `200 OK`. Path variables are named after the resource they address: `contract_id`, `bid_item_id`, `work_package_id`, `crew_id`, `equipment_id`, `assignment_id`, `production_entry_id`, `stock_item_id`, `material_issue_id`, `inspection_id`, `outage_request_id`, `storm_activation_id`, `safety_event_id`, and `invoice_id`. The table below is a navigational summary only; request fields, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/contracts` | Create a contract in `DRAFT` | CONTRACTOR_PM |
| GET | `/contracts/{contract_id}` | Get a contract | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/contracts/{contract_id}/transition` | Contract lifecycle: activate from `DRAFT`, resume from `SUSPENDED`, close from `ACTIVE` | CONTRACTOR_PM, UTILITY_DISPATCHER |
| POST | `/contracts/{contract_id}/bid-items` | Add a unit-price bid item (contract must be `DRAFT`) | CONTRACTOR_PM |
| GET | `/bid-items` | List bid items, optionally filtered by contract | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/bid-items/{bid_item_id}` | Get a single bid item (includes `accepted_quantity` and `billed_quantity`) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/contracts/{contract_id}/work-packages` | Create a work package (contract must be `ACTIVE`) | CONTRACTOR_PM |
| GET | `/work-packages` | List work packages, optionally filtered by contract and status | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/work-packages/{work_package_id}` | Get a work package (includes `rework_open_count`, `open_material_issue_count`, `version`) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/work-packages/{work_package_id}/transition` | Work package lifecycle transitions | CONTRACTOR_PM |
| POST | `/crews` | Register a crew | CONTRACTOR_PM |
| GET | `/crews` | List crews (computed status visible) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/crews/{crew_id}` | Get a single crew (includes computed status) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/equipment` | Register equipment | CONTRACTOR_PM |
| GET | `/equipment` | List equipment (computed status visible) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/equipment/{equipment_id}` | Get a single equipment item (includes computed status) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/work-packages/{work_package_id}/assignments` | Assign a crew and equipment item to a work package over a closed date interval | FOREMAN |
| GET | `/assignments` | List assignments with filters | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/assignments/{assignment_id}` | Get an assignment (includes current `version` for OCC) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/assignments/{assignment_id}/transition` | Assignment lifecycle transitions | FOREMAN |
| POST | `/assignments/{assignment_id}/production-entries` | Report daily production against a bid item (OCC on the assignment) | FOREMAN |
| GET | `/production-entries` | List production entries with filters | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/production-entries/{production_entry_id}/resubmit` | Resubmit a `REWORK_REQUIRED` entry after rework (re-applies the quantity ceiling) | FOREMAN |
| POST | `/production-entries/{production_entry_id}/void` | Void a `SUBMITTED` or `REWORK_REQUIRED` entry | FOREMAN |
| GET | `/production-entries/{production_entry_id}` | Get a single production entry (status, `rework_count`) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/contracts/{contract_id}/stock-items` | Register a utility-owned stock item with an opening balance | UTILITY_DISPATCHER |
| POST | `/stock-items/{stock_item_id}/receipts` | Receive additional utility stock | UTILITY_DISPATCHER |
| GET | `/stock-items` | List stock items, optionally filtered by contract | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/stock-items/{stock_item_id}` | Get a stock item (includes `on_hand`) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/work-packages/{work_package_id}/material-issues` | Issue material from utility stock to a work package | FOREMAN |
| GET | `/material-issues` | List material issues with filters | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/material-issues/{material_issue_id}/return` | Return unused material to utility stock | FOREMAN |
| POST | `/material-issues/{material_issue_id}/reconcile` | Reconcile an issue: exact match by a foreman, or variance with note by the project manager | FOREMAN, CONTRACTOR_PM |
| GET | `/material-issues/{material_issue_id}` | Get a single material issue (quantities, variance, status) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/work-packages/{work_package_id}/inspections` | Schedule a utility-standard inspection of a `SUBMITTED` production entry | UTILITY_INSPECTOR |
| POST | `/inspections/{inspection_id}/submit` | Submit the inspection result (`PASS` or `FAIL`); drives the accept/rework cascade | UTILITY_INSPECTOR |
| GET | `/inspections` | List inspections with filters | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/inspections/{inspection_id}` | Get a single inspection | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/work-packages/{work_package_id}/outage-requests` | Request an outage/switching window for a circuit | CONTRACTOR_PM |
| POST | `/outage-requests/{outage_request_id}/decide` | Utility decision: approve (runs the sixty-minute buffer check; adopts the requested window when `CHANGE_REQUESTED`) or deny | UTILITY_DISPATCHER |
| POST | `/outage-requests/{outage_request_id}/request-change` | Propose a new window for an `APPROVED` outage (moves to `CHANGE_REQUESTED`; re-approval required) | CONTRACTOR_PM |
| POST | `/outage-requests/{outage_request_id}/release` | Release an `IN_EFFECT` outage back to the utility | UTILITY_DISPATCHER |
| POST | `/outage-requests/{outage_request_id}/cancel` | Cancel a `REQUESTED`, `APPROVED`, or `CHANGE_REQUESTED` outage | CONTRACTOR_PM |
| GET | `/outage-requests` | List outage requests with filters (lazy `IN_EFFECT` evaluation on read against the logical clock) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/outage-requests/{outage_request_id}` | Get a single outage request (window and status; lazy `IN_EFFECT` evaluation applies) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/contracts/{contract_id}/storm-activations` | Place a crew on storm `STANDBY` or `CALLOUT` | UTILITY_DISPATCHER |
| POST | `/storm-activations/{storm_activation_id}/convert` | Convert a `STANDBY` activation to `CALLOUT` | UTILITY_DISPATCHER |
| POST | `/storm-activations/{storm_activation_id}/close` | Close an activation, recording hours and computing `premium_pay` | UTILITY_DISPATCHER |
| POST | `/storm-activations/{storm_activation_id}/cancel` | Cancel an `ACTIVE` activation without closing hours | UTILITY_DISPATCHER |
| GET | `/storm-activations` | List storm activations with filters | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/storm-activations/{storm_activation_id}` | Get a single storm activation (kind, converted flag, hours, premium pay) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/work-packages/{work_package_id}/safety-events` | Log a safety observation or incident; an `INCIDENT` of severity `OSHA_RECORDABLE` or `FATAL` suspends the contract | SAFETY_OFFICER |
| POST | `/safety-events/{safety_event_id}/transition` | Safety event review flow: `UNDER_REVIEW`, then `CLOSED` | SAFETY_OFFICER |
| GET | `/safety-events` | List safety events with filters | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/safety-events/{safety_event_id}` | Get a single safety event | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/work-packages/{work_package_id}/invoices` | Create a `DRAFT` progress-billing invoice for a period (OCC on the work package) | CONTRACTOR_PM |
| GET | `/invoices` | List invoices with filters | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| GET | `/invoices/{invoice_id}` | Get an invoice (lines, totals, `hold_reason`, status; `DRAFT` invoices recompute lines on read) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |
| POST | `/invoices/{invoice_id}/transition` | Invoice lifecycle: submit, approve, reject, pay, revise to draft, void | CONTRACTOR_PM, UTILITY_INSPECTOR, UTILITY_DISPATCHER |
| GET | `/work-packages/{work_package_id}/billing-preview` | Computed read: transient invoice-shaped preview of billable units and amounts for a period; `variant` selects the final or provisional basis | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default is exactly 2026-08-01T00:00:00Z; never falls back to wall-clock time) | CONTRACTOR_PM, FOREMAN, UTILITY_INSPECTOR, UTILITY_DISPATCHER, SAFETY_OFFICER |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are defined in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONTRACT_SUSPENDED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_BID_ITEMS_LOCKED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_OUTAGE_REQUIRED` | 409 Conflict |
| `ERR_EQUIPMENT_DOWN` | 409 Conflict |
| `ERR_CREW_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_EQUIPMENT_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_OUTAGE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_STANDBY` | 409 Conflict |
| `ERR_CREW_ON_STORM_DUTY` | 409 Conflict |
| `ERR_INSPECTION_ALREADY_OPEN` | 409 Conflict |
| `ERR_QUANTITY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_RETURN_EXCEEDS_ISSUED` | 409 Conflict |
| `ERR_MATERIAL_VARIANCE_UNRESOLVED` | 409 Conflict |
| `ERR_OPEN_REWORK` | 409 Conflict |
| `ERR_OPEN_MATERIAL_ISSUES` | 409 Conflict |
| `ERR_SAFETY_EVENT_OPEN` | 409 Conflict |
| `ERR_OPEN_WORK_PACKAGES` | 409 Conflict |
| `ERR_CROSS_CONTRACT_REFERENCE` | 409 Conflict |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_NO_BILLABLE_UNITS` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |

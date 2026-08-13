# Industrial Equipment Installation API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Industrial Equipment Installation & Millwright Services API, the operating system of record for a union millwright contractor that installs heavy industrial equipment inside customer plants. An installation engagement is precision work with a long chain of physical dependencies: a site survey must verify the foundation's anchor-bolt pattern against its tolerance before steel moves; the foundation itself must cure before load is set; a rigging plan must prove the crane can carry the lift before a crane is booked; laser alignment of the machine train must pass its tolerance class before the customer will sign off; and commissioning cannot complete until the customer's representative has signed the checklist. The API models this entire chain, from project award through mobilization, installation, and commissioning to final completion.

The commercial and labor dimensions are equally demanding. Projects are billed either on a time-and-materials basis against a not-to-exceed cap or as a fixed lump-sum price billed by cumulative progress percentage, with retainage withheld on every invoice and all previously withheld retainage released at final billing. Field labor is costed under prevailing-wage rules with union classifications, a night-shift multiplier, fringe, and an overtime regime that the project selects — daily or weekly — and that meaningfully changes how the same hours are paid. Safety governance is first-class: a site-specific safety plan gates mobilization, lockout-tagout windows are scheduled on individual electrical feeders with mandatory clearance buffers, and suspending the safety plan immediately places the project on hold and rejects labor awaiting payroll approval. The sections that follow define the system-wide contracts, the business workflows, the endpoint inventory, and the error catalogue for this API.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled as follows: `ProjectManager`, `SiteSupervisor`, `SafetyOfficer`, `PayrollClerk`, and `CustomerRep`. A request whose `X-User-Role` header is missing or does not match one of these five declared roles is rejected with `ERR_UNAUTHENTICATED`, and a request missing the `X-User-ID` header is likewise rejected with `ERR_UNAUTHENTICATED`. When the role is recognized but not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN`.

All five roles use opaque operator identities; no role's `X-User-ID` is the `id` of any persisted entity. When `X-User-Role` is `ProjectManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same is true when `X-User-Role` is `SiteSupervisor`, when it is `SafetyOfficer`, when it is `PayrollClerk`, and when it is `CustomerRep`. The server may record these identifiers on resources — for example as `submitted_by_user_id` on a labor entry, `approved_by_user_id` on an approved entry, `checked_by_user_id` on a checklist item, or `signed_off_by_user_id` on a commissioning checklist — but it never compares `X-User-ID` to any entity's `id`.

The division of labor across roles follows a strict segregation-of-duties model: the `SiteSupervisor` records field data (surveys, rigging plans, lift bookings, alignment measurements, labor entries, checklist items), the `ProjectManager` owns the project lifecycle, reviews, invoicing, and the test clock, the `SafetyOfficer` alone manages the safety plan and lockout-tagout windows, the `PayrollClerk` approves or rejects submitted labor and is deliberately distinct from the submitting supervisor, and the `CustomerRep` holds sole authority for commissioning sign-off. All roles may read every resource through the list and detail endpoints.

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

Requests that match no defined route, or a defined route with an unsupported method, are rejected in this same envelope with `ERR_NOT_FOUND` (404); unexpected server faults are reported in the same envelope with `ERR_INTERNAL` (500).

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it may not be less than 1 or more than 100. The `offset` parameter specifies how many items to skip and defaults to 0, and it may not be negative. A non-integer or out-of-range `limit` or `offset` fails with `ERR_VALIDATION`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by insertion order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus `limit` is less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource — projects, site surveys, safety plans, lockout windows, rigging plans, lift permits, alignment records, commissioning checklists, and labor entries — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification to the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including updates to derived or rollup fields.

The invoice resource is the deliberate exception. Invoices are append-only financial records: they carry `id` and `created_at` only, are never updated after creation, and therefore expose neither `updated_at` nor `version`.

### 2.5. The Logical Clock

Time inside this system is governed by a logical clock, not by wall-clock time. A test-driving capability restricted to the `ProjectManager` role advances the logical clock to a supplied `to` instant provided as `to_iso8601` — applied unconditionally, even to an instant earlier than the current logical time — and the current logical time is reported back as `current_utc`. Before any such call, the clock's startup default is exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time. Foundation cure evaluation, lockout-window activation and expiry, lift-permit expiry, and lift-execution window checks all read this logical clock. Advancing the clock triggers the automatic state transitions described in §3.3 and §3.5.

### 2.6. Validation Pipeline Order

Every request is evaluated against a fixed sequence of checks, and the first failing check determines the error response. Authentication comes first — a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED` — followed by authorization, where a recognized role without permission for the operation yields `ERR_FORBIDDEN`. Existence checking follows: every resource identifier appearing in the path or the request body must resolve to an existing resource, or the request fails with `ERR_NOT_FOUND`. Only after all three of those gates does the optimistic-concurrency version check apply on the one endpoint that defines it, where a stale version is rejected with `ERR_STALE_VERSION`. State and phase validity comes next (`ERR_INVALID_STATE`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and only then request-schema validation — the body must be a JSON object, required fields present, enum members valid, ranges respected, and conditional requirements met (`ERR_VALIDATION`).

Once those generic layers pass, the business rules execute in a fixed relative order. The safety interlocks run first: the project safety-hold check (`ERR_SAFETY_HOLD`) precedes the active-safety-plan check (`ERR_SAFETY_PLAN_NOT_ACTIVE`). Next come the referential gates in sequence: an accepted site survey (`ERR_SITE_SURVEY_NOT_ACCEPTED`), a pinned approved rigging plan (`ERR_RIGGING_PLAN_NOT_APPROVED`), an executed lift (`ERR_NO_EXECUTED_LIFT`), no outstanding lockouts (`ERR_LOCKOUTS_OUTSTANDING`), the alignment gate (`ERR_ALIGNMENT_OUTSTANDING`), and the signed-off checklist gate (`ERR_CHECKLIST_NOT_SIGNED_OFF`). Singleton constraints follow (`ERR_SAFETY_PLAN_EXISTS`, `ERR_CHECKLIST_EXISTS`), then measurement and completeness constraints (`ERR_ANCHOR_OUT_OF_TOLERANCE`, `ERR_FOUNDATION_NOT_CURED`, `ERR_LIFT_WEIGHT_EXCEEDED`, `ERR_CHECKLIST_INCOMPLETE`). Temporal rules are evaluated after those (`ERR_INVALID_WINDOW`, `ERR_LOCKOUT_CONFLICT`, `ERR_CRANE_WINDOW_CONFLICT`, `ERR_OUTSIDE_LIFT_WINDOW`), then the fiscal rules (`ERR_NTE_EXCEEDED`, `ERR_FINAL_INVOICE_EXISTS`, `ERR_NO_BILLABLE_WORK`). Last of all comes the constraint that no other rigging plan is still open for the project (`ERR_RIGGING_PLAN_OPEN_EXISTS`).

### 2.7. Optimistic Concurrency Control

Exactly one write operation in the API participates in optimistic concurrency control: the creation of a rigging plan. That request must carry `expected_project_version`, a non-optional field holding the `version` of the parent project as the client last observed it. If the supplied value does not match the project's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects the approval pin: creating a plan supersedes the currently approved plan and clears the project's pinned approval, so a writer working from a stale project view must not be allowed to silently discard an approval or supersede chain it never observed. No other endpoint in the API accepts a version field.

### 2.8. Monetary Precision, Rounding, and Comparison Rules

All monetary values in the system are integer cents. Wherever a monetary value is computed rather than supplied, the standard round-half-up method applies. Labor costing pins its rounding order: the straight-time, overtime, and fringe components are each rounded half-up to whole cents individually, and only then summed into the entry's total — the components are never summed first and rounded once. Retainage on an invoice is likewise rounded half-up exactly once, computed on the summed gross and never line by line. Tolerance comparisons for anchors, alignment, and lift weight are made in the raw input units with no rounding at all, and in every such comparison a value exactly equal to the limit passes. All datetime comparisons — foundation cure, window well-formedness, lockout clearance, crane overlap, lift-window execution — are made at second precision.

### 2.9. Shared Fleet Resources, Cascades, and Nested Retrieval

Cranes are a fleet-wide shared resource. A crane booking made under one project competes with bookings of the same crane unit under every other project, so overlap validation always runs fleet-wide against the crane unit identifier rather than within a single project. Electrical feeders, by contrast, are pooled per project: lockout clearance rules compare windows on the same feeder within the same project only.

Certain operations trigger automatic cascades that mutate resources beyond the one named in the request. Suspending a safety plan places its project on safety hold and rejects labor awaiting approval; creating a new rigging plan supersedes the currently approved plan, clears the project's approval pin, and cancels outstanding crane bookings. These cascades are system-driven transitions, not client requests on the affected resources. Every mutation of a project — including re-evaluation of its derived rollup fields caused by child activity — refreshes the project's `updated_at` and increments its `version` by one.

Requests that target nested resources validate path identifiers strictly left to right. On a path such as a project's child-collection listing, the project identifier is resolved first; if it does not correspond to an existing project the request fails immediately with `ERR_NOT_FOUND`, before any child-side evaluation occurs.

## 3. Business Logic & Workflows

### 3.1. Projects, Commercial Terms, and the Work-Phase Chain

Everything begins when a `ProjectManager` creates a project with a `name`, the plant owner's `customer_name`, and the installation `site_address`. Two commercial choices are locked in at this moment and can never be changed afterward, because no project update capability exists. The first is `billing_mode`, which is either `TM` for time-and-materials billing or `LUMP_SUM` for fixed-price billing and which selects the invoice amount variant used for the project's entire life. The second is `contract_amount_cents`, which must be greater than zero and carries a different meaning per mode: for a `LUMP_SUM` project it is the fixed contract price, while for a `TM` project it is the not-to-exceed cap that cumulative billing may never cross. The project also records the `equipment_hourly_rate_cents` — a required integer of zero or more — at which crane time is billed under time-and-materials work, a `retainage_pct` specifying the fraction withheld from each non-final invoice (defaulting to 0.10 when omitted or null, and always within zero to 0.20 inclusive), and an `ot_basis` of `DAILY_OT` or `WEEKLY_OT` selecting the prevailing-wage overtime regime for the project's labor — `DAILY_OT` applies when the field is omitted or null.

A new project starts with `work_status` of `AWARDED`, `hold_status` of `CLEAR`, no approved rigging plan (`approved_rigging_plan_id` and `approved_rigging_plan_revision` are null), all three rollup figures (`approved_labor_cents`, `approved_equipment_cents`, `invoiced_cents`) at zero, and `version` 1. The project list view supports optional filtering by `work_status` and by `billing_mode`.

The project advances through a linear work chain — `AWARDED` → `MOBILIZED` → `INSTALLING` → `COMMISSIONING` → `COMPLETED` — driven hop by hop by the `ProjectManager`. Every hop requires the project to be clear of any safety hold, and each hop carries one additional gate described in the subsection that owns it: mobilization requires an active safety plan (§3.3), entering installation requires an accepted site survey (§3.2), entering commissioning requires at least one executed lift and no outstanding lockouts (§3.5 and §3.3), and completion requires a signed-off commissioning checklist (§3.7). Each successful advance increments the project's `version` by one. `COMPLETED` is terminal: any attempt to advance a completed project is rejected with `ERR_INVALID_STATE`.

### 3.2. Site Survey and Foundation Readiness

Before steel can move, a `SiteSupervisor` records a site survey against the project, naming the parent in the payload's `project_id` and capturing the `survey_date` (a `YYYY-MM-DD` calendar date), the verified `anchor_bolt_count` (which must be greater than zero), the allowed `anchor_tolerance_mm` from the engineering specification, the worst actually measured deviation `anchor_measured_max_deviation_mm` (zero or greater), the `overhead_clearance_mm` measured along the rigging path, and the `foundation_pour_date` timestamp at which the foundation was poured. Both tolerance figures must be greater than zero.

Two computed flags govern whether the pad is ready. The `anchor_check_passed` flag is computed at creation and is true when the worst measured deviation is no more than the allowed tolerance — a deviation exactly equal to the tolerance passes. The `foundation_cured` flag is evaluated continuously against the logical clock, at read time and again at review time: it becomes true once the current logical time has reached or passed seven full days after `foundation_pour_date`, so a pour that is exactly seven days old counts as cured.

A survey begins as `DRAFT`. Submission by the `SiteSupervisor` moves it to `SUBMITTED`, after which a `ProjectManager` reviews it with an `outcome` of `ACCEPTED` or `REJECTED` and an optional `reviewer_note` that is recorded on the survey. Acceptance is gated on both readiness flags: an anchor pattern out of tolerance is rejected with `ERR_ANCHOR_OUT_OF_TOLERANCE`, and a foundation poured fewer than seven days ago at review time is rejected with `ERR_FOUNDATION_NOT_CURED`. Rejection carries no such gates. Both `ACCEPTED` and `REJECTED` are terminal; when a survey fails, the remedy is to record an entirely new site survey row, not to repair the rejected one. The mobilization-to-installation advance gate lives here: the project cannot enter `INSTALLING` until some survey of the project stands `ACCEPTED`, failing with `ERR_SITE_SURVEY_NOT_ACCEPTED` otherwise.

### 3.3. Safety Plans, Safety Holds, and Lockout-Tagout Windows

Each project may have at most one safety plan; an attempt to create a second is rejected with `ERR_SAFETY_PLAN_EXISTS`. The `SafetyOfficer` creates it with a `plan_document_ref` pointing to the site-specific safety plan document and a `loto_procedure_ref` pointing to the lockout-tagout procedure document, and the plan begins as `DRAFT`. Activation moves it to `ACTIVE`. An active plan is a hard prerequisite for two things: scheduling any lockout window, and the very first project advance from `AWARDED` to `MOBILIZED` — both fail with `ERR_SAFETY_PLAN_NOT_ACTIVE` when no plan of the project stands `ACTIVE`.

Suspension is the system's most consequential cascade. When the `SafetyOfficer` suspends an `ACTIVE` plan, the plan moves to `SUSPENDED` and three things happen in sequence: first the project's `hold_status` flips from `CLEAR` to `SAFETY_HOLD`; then, as a consequence, every labor entry of the project sitting in `SUBMITTED` status — that is, awaiting payroll approval — is automatically rejected with `rejection_reason` recorded as `SAFETY_HOLD`; finally the project's derived fields are re-evaluated and its `version` increments by one. The project's `approved_labor_cents` does not change during this cascade, because entries that were merely submitted had never been added to it. While a project is under `SAFETY_HOLD`, four operations are blocked outright with `ERR_SAFETY_HOLD`: any work-phase advance, the creation of a labor entry, the submission of a labor entry, and the execution of a lift. Resuming a `SUSPENDED` plan returns it to `ACTIVE`, restores the project's `hold_status` to `CLEAR`, and increments the project `version` by one — a compensating transition that deliberately leaves the cascade-rejected labor entries in `REJECTED`, from which a supervisor may resubmit them once the hold is clear.

Closing a safety plan is allowed from either `ACTIVE` or `SUSPENDED`, but only when the project has no lockout window in `ACTIVE` status; outstanding active lockouts block closure with `ERR_LOCKOUTS_OUTSTANDING`. Closing a plan that was `SUSPENDED` additionally clears the project's safety hold and increments its `version`. `CLOSED` is terminal.

Lockout-tagout windows are scheduled by the `SafetyOfficer` on a specific energy source identified by `feeder_id`, with a `starts_at` and `ends_at` defining the window. The window must be well-formed — the end strictly after the start — or creation fails with `ERR_INVALID_WINDOW`. Beyond well-formedness, a clearance rule protects each feeder: within the same project on the same `feeder_id`, a new window must keep at least a thirty-minute clearance from every existing window in `SCHEDULED` or `ACTIVE` status, meaning the new window either starts at least thirty minutes after the existing window ends or ends at least thirty minutes before the existing window starts. Exactly thirty minutes of clearance satisfies the rule; anything less is rejected with `ERR_LOCKOUT_CONFLICT`. The lockout listing for a project can optionally be filtered by `feeder_id`.

A new window begins as `SCHEDULED`. From there the logical clock takes over: when the clock reaches a point at or after `starts_at` but before `ends_at`, the window transitions to `ACTIVE`; if the clock reaches or passes `ends_at` while the window is still `SCHEDULED`, it transitions to `EXPIRED` instead. A `SCHEDULED` window may be cancelled by the `SafetyOfficer`, moving it to `CANCELLED`. An `ACTIVE` window never releases itself when its end passes — physical locks require manual removal — so the `SafetyOfficer` releases it explicitly, moving it to `RELEASED`. `RELEASED`, `CANCELLED`, and `EXPIRED` are all terminal. Lockouts also gate the installation-to-commissioning advance: the project cannot enter `COMMISSIONING` while any of its windows remains `SCHEDULED` or `ACTIVE`, failing with `ERR_LOCKOUTS_OUTSTANDING`.

### 3.4. Rigging Plans and the Approval Pin

Rigging plans are created by the `SiteSupervisor` with the planned `lift_weight_tons` (the gross lifted weight including rigging, greater than zero), the `crane_model`, the `planned_crane_capacity_tons` of the planned crane configuration (greater than zero), and a `rigging_config` of `SINGLE_CRANE`, `TANDEM`, or `GANTRY`. Creation carries the optimistic-concurrency contract of §2.7: the request must include `expected_project_version` matching the project's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Only one rigging plan may be open at a time per project — if another plan already exists in `DRAFT` or `SUBMITTED`, creation is rejected with `ERR_RIGGING_PLAN_OPEN_EXISTS`. Each new plan receives a 1-based `revision` equal to the count of prior rigging plans for the project plus one, starts as `DRAFT`, and has its `weight_check_passed` computed immediately: true when `lift_weight_tons` is no more than `planned_crane_capacity_tons`, with equality passing.

Creating a plan is also the supersede mechanism. When a project currently has an `APPROVED` plan pinned, the creation of a new plan automatically moves that approved plan to `SUPERSEDED`, clears the project's pin (`approved_rigging_plan_id` and `approved_rigging_plan_revision` become null), cancels every lift permit of the project still in `ISSUED` status — each such permit's approval basis is gone — and increments the project's `version` by one. `SUPERSEDED` is the rigging plan's only terminal state.

The review cycle mirrors the survey's. Submission by the `SiteSupervisor` moves a plan from `DRAFT` to `SUBMITTED`; a `ProjectManager` then reviews with an `outcome`. Approval is gated twice: some site survey of the project must stand `ACCEPTED` (otherwise `ERR_SITE_SURVEY_NOT_ACCEPTED`), and the plan's `weight_check_passed` must be true (otherwise `ERR_LIFT_WEIGHT_EXCEEDED`). On approval, the project pins the plan — `approved_rigging_plan_id` is set to this plan's id and `approved_rigging_plan_revision` to this plan's `revision` — and the project `version` increments by one. The optional `reviewer_note` is recorded on the plan on either outcome; rejection moves the plan to `REJECTED`.

Rejection is not the end for a rigging plan. The `SiteSupervisor` may revise a `REJECTED` plan, which returns the same row to `DRAFT`; the revision request optionally supplies new `lift_weight_tons`, `planned_crane_capacity_tons`, `crane_model`, or `rigging_config` values, any supplied field replaces the prior value, any field not supplied — including a previously recorded `reviewer_note` — is retained, and `weight_check_passed` is recomputed when the inputs changed. The same row therefore cycles `DRAFT` → `SUBMITTED` → `REJECTED` → `DRAFT` as many times as review requires.

### 3.5. Crane Lift Permits and Equipment Charges

With a rigging plan approved and pinned, the `SiteSupervisor` books crane time by creating a lift permit naming the fleet crane unit `crane_ref` and a half-open booking window from `lift_starts_at` to `lift_ends_at`. Booking is gated on the project's phase and readiness: the project must be in `INSTALLING` (otherwise `ERR_INVALID_STATE`), clear of any safety hold, and must have an approved rigging plan currently pinned (otherwise `ERR_RIGGING_PLAN_NOT_APPROVED`). The window must be well-formed, the end strictly after the start, or creation fails with `ERR_INVALID_WINDOW`. Every booking request carries a required boolean `road_permit_required`; when the crane mobilization requires an oversize-load road permit the flag is set to true and the request must then supply `road_permit_number`. The number is required exactly when the flag is true, and a missing or wrongly present number fails schema validation with `ERR_VALIDATION`.

Because cranes are shared across the entire fleet, the booking overlap check runs against every `ISSUED` permit of the same `crane_ref` under any project. A new window conflicts with an existing `ISSUED` window only when the two half-open intervals genuinely overlap — the new start falls before the existing end and the existing start falls before the new end. Touching endpoints are not a conflict: a new window that starts exactly when an existing window ends, or ends exactly when one starts, books cleanly. Any genuine overlap is rejected with `ERR_CRANE_WINDOW_CONFLICT`. A permit is created in `ISSUED` status with its `duration_hours` computed as the length of the booked window in hours; its `equipment_charge_cents` remains null until execution. The lift permit listing for a project can be filtered by `crane_ref` or by `status`.

Execution happens inside the booked window. When the `SiteSupervisor` executes the lift, the project's `hold_status` must be `CLEAR` (otherwise `ERR_SAFETY_HOLD`) and the current logical time must fall within the half-open booking window — at or after `lift_starts_at` and strictly before `lift_ends_at` — otherwise the attempt is rejected with `ERR_OUTSIDE_LIFT_WINDOW`. On successful execution the permit moves to `EXECUTED`, its `equipment_charge_cents` is computed once as `duration_hours` multiplied by the project's `equipment_hourly_rate_cents`, rounded half-up to whole cents, that charge is added into the project's `approved_equipment_cents`, and the project's `version` increments by one. An `ISSUED` permit may instead be cancelled by the `SiteSupervisor`, moving it to `CANCELLED`, and a permit still `ISSUED` when the logical clock reaches or passes `lift_ends_at` automatically transitions to `EXPIRED`. Cancellation — whether by the supervisor or by the rigging supersede cascade of §3.4 — and expiry both release the booking: the window stops counting toward the crane's committed time, whereas an `EXECUTED` window is historic and likewise no longer counts. `EXECUTED`, `CANCELLED`, and `EXPIRED` are terminal.

Lifts gate the third work-phase hop. The advance from `INSTALLING` to `COMMISSIONING` requires at least one lift permit of the project in `EXECUTED` status, failing with `ERR_NO_EXECUTED_LIFT` otherwise, in addition to the lockout gate of §3.3 and the ever-present hold check.

### 3.6. Precision Alignment Records

During commissioning preparation, the `SiteSupervisor` records laser alignment measurements for points of the machine train, identified by a free-form `measurement_point` such as PUMP-TO-MOTOR. Each record declares a `tolerance_class` of `STANDARD` or `PRECISION` and carries two measured values: `measured_offset_mils`, the laser-measured parallel offset in mils, and `measured_angular_mils_per_in`, the angular misalignment in mils per inch; both measurements must be zero or greater. Recording is not phase-gated: a record may be created in any work phase of the project.

The verdict is computed at creation against the declared class, with equality passing on every comparison. A `STANDARD` point passes its offset check when `measured_offset_mils` is no more than 5.0 mils and passes its angular check when `measured_angular_mils_per_in` is no more than 1.0 mils per inch. A `PRECISION` point tightens those limits to no more than 2.0 mils of offset and no more than 0.5 mils per inch of angular misalignment. The record exposes both outcomes as `offset_passed` and `angular_passed`, and its `verdict` is `PASS` only when both checks passed, otherwise `FAIL`. These comparisons use the raw measured units with no rounding.

A record begins as `RECORDED` and awaits review by a `ProjectManager`, who accepts or rejects it with an `outcome` and an optional `reviewer_note` that is recorded on the record. `ACCEPTED` and `REJECTED` are both terminal. Records awaiting review block commissioning progress, as the next subsection describes. The alignment listing for a project can be filtered by `measurement_point`.

### 3.7. Commissioning Checklist and Customer Sign-Off

A `ProjectManager` creates the commissioning checklist once the project has reached `INSTALLING` or `COMMISSIONING` — creation in any other phase, including `COMPLETED`, fails with `ERR_INVALID_STATE`. At most one checklist per project may be non-terminal at a time; if one already exists in `IN_PROGRESS` or `SUBMITTED`, creation of another is rejected with `ERR_CHECKLIST_EXISTS`. The checklist is created with its `items`, an array of entries (the array may be empty) each carrying an `item_key`, a `description`, and a `required` flag; every item starts with its `checked` flag false and its `checked_by_user_id` and `checked_at` both null. Two counters are maintained over the items: `required_count`, the number of items marked required, and `checked_required_count`, the number of required items currently checked.

Field completion is item-by-item. The `SiteSupervisor` marks one item at a time by its `item_key`, which sets that item's checked flag and records the acting supervisor's `X-User-ID` and the time of checking — the current logical time — on the item, then recomputes `checked_required_count`. Marking an already-checked item is permitted and simply refreshes its `checked_by_user_id` and `checked_at`; if duplicate `item_key` values exist, the first matching item is marked. An `item_key` that does not match any item of the checklist is an unknown identifier and fails with `ERR_NOT_FOUND`.

Submitting the checklist — moving it from `IN_PROGRESS` to `SUBMITTED` — is a triple gate. The project must stand in `COMMISSIONING` (otherwise `ERR_INVALID_STATE`). Every required item must be checked, so that `checked_required_count` equals `required_count` (otherwise `ERR_CHECKLIST_INCOMPLETE`). And the alignment gate must be satisfied: at least one alignment record of the project must stand `ACCEPTED` with a `verdict` of `PASS`, and no alignment record of the project may remain in `RECORDED` awaiting review — a project with passing records but unreviewed measurements still fails, with `ERR_ALIGNMENT_OUTSTANDING` covering both halves of the gate.

Final authority rests with the customer. A `CustomerRep` signs off a `SUBMITTED` checklist, optionally attaching a `signoff_note` (validated as a string when supplied but not stored on the checklist); sign-off moves the checklist to `SIGNED_OFF`, records the representative's `X-User-ID` as `signed_off_by_user_id`, and increments the project's `version` by one. `SIGNED_OFF` is terminal and unlocks the last work-phase hop: advancing from `COMMISSIONING` to `COMPLETED` requires some checklist of the project to stand `SIGNED_OFF`, failing with `ERR_CHECKLIST_NOT_SIGNED_OFF` otherwise.

### 3.8. Labor Entries and Prevailing-Wage Costing

Labor is reported by the `SiteSupervisor` one entry per worker per date, with the worker identified by `worker_ref` (their union card reference), a prevailing-wage `classification` of `MW_JOURNEYMAN`, `MW_APPRENTICE`, `MW_FOREMAN`, or `OPERATOR`, the `work_date` (a `YYYY-MM-DD` calendar date), the `hours_worked` that date (greater than zero and at most twenty-four), and a `shift` of `DAY` or `NIGHT`. Creation is refused while the project is under a safety hold (`ERR_SAFETY_HOLD`). The full labor cost is computed and frozen on the row at creation and is never recomputed afterward, even if the worker's other entries change later.

The costing proceeds in fixed steps. The `base_rate_cents` is looked up from the classification: 8,500 cents per hour for `MW_JOURNEYMAN`, 5,600 for `MW_APPRENTICE`, 9,800 for `MW_FOREMAN`, and 7,200 for `OPERATOR`. The shift multiplier is 1.0 for a `DAY` shift and 1.10 for a `NIGHT` shift. The entry's hours are then split into `regular_hours` and `overtime_hours` according to the project's `ot_basis`, and this is where the two regimes diverge. Under `DAILY_OT`, the split is per-entry: up to eight hours of the entry's `hours_worked` are straight time, and any hours beyond eight are overtime. Under `WEEKLY_OT`, the threshold applies to cumulative same-worker hours across the ISO week, Monday through Sunday, containing the entry's `work_date`: the system first totals the `hours_worked` of the worker's other entries in that week — across all projects, not only the entry's own project — whose status is `SUBMITTED`, `APPROVED`, or `INVOICED` — entries still `DRAFT` or already `REJECTED` do not count. The new entry's straight-time portion is then the amount of the forty-hour weekly threshold not already absorbed by that prior total: take the smaller of (the prior total plus this entry's hours) and forty, subtract the smaller of (the prior total) and forty, and floor the result at zero; whatever remains of the entry's hours is overtime. Identical `hours_worked` can therefore split differently on a weekly-regime project depending on what the worker has already logged that week.

Three components make up the cost, and the rounding order is pinned — each component is rounded half-up to whole cents individually, then the three are summed. The straight-time component is `regular_hours` times `base_rate_cents` times the shift multiplier. The overtime component is `overtime_hours` times `base_rate_cents` times one and a half times the shift multiplier. The fringe component is `hours_worked` times 2,100 cents per hour, applied to every hour worked regardless of the overtime split. Their sum is the entry's `total_cost_cents`.

An entry begins as `DRAFT`. Submission by the `SiteSupervisor` — permitted only while the project is clear of a safety hold — moves it to `SUBMITTED` and records the submitter's `X-User-ID` as `submitted_by_user_id`. Payroll review belongs to the `PayrollClerk`, with one hard segregation rule: the approver's `X-User-ID` must differ from the entry's `submitted_by_user_id`, and a self-approval attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval moves the entry to `APPROVED`, records `approved_by_user_id`, adds the entry's `total_cost_cents` into the project's `approved_labor_cents`, and increments the project `version` by one. Rejection of a `SUBMITTED` entry moves it to `REJECTED` and records the supplied `reason` — required on every rejection — as `rejection_reason`. A rejected entry is not dead: the supervisor may resubmit it, which returns it to `SUBMITTED`, records the new `submitted_by_user_id`, and clears the `rejection_reason` — the payroll revision loop `SUBMITTED` → `REJECTED` → `SUBMITTED`. Rejection can also run in reverse: an entry already `APPROVED` but not yet invoiced may be rejected by the `PayrollClerk`, which compensates the rollup by subtracting its `total_cost_cents` from the project's `approved_labor_cents`, increments the project `version`, and records the reason. Once an entry has been invoiced this reversal path is closed. The labor listing for a project can be filtered by `status` or by `worker_ref`.

### 3.9. Invoicing, Retainage, and Project Cost Rollups

Billing is initiated by the `ProjectManager` with an invoice naming the `kind` — `PROGRESS` or `FINAL` — and a billing period from `period_start` through `period_end`, both `YYYY-MM-DD` dates inclusive, with the end no earlier than the start; an end earlier than the start fails schema validation with `ERR_VALIDATION`. Phase gates apply at creation: a `PROGRESS` invoice requires the project to be in `MOBILIZED`, `INSTALLING`, or `COMMISSIONING`, while a `FINAL` invoice requires `COMPLETED`; issuing against the wrong phase fails with `ERR_INVALID_STATE`. At creation the invoice snapshots the project's `billing_mode` onto `billing_mode_snapshot`, and that snapshot selects the amount variant. The invoice also echoes the request's `progress_pct` (null on time-and-materials invoices).

Under the `TM` variant, the invoice bills actuals for the period. The labor portion is the sum of `total_cost_cents` over the project's labor entries standing `APPROVED` whose `work_date` falls within the inclusive billing period; the equipment portion is the sum of `equipment_charge_cents` over the project's lift permits standing `EXECUTED` whose `lift_starts_at` calendar date falls within the same inclusive period. The invoice's `gross_cents` is the sum of the two portions with no additional rounding, since both are sums of already-rounded values. Issuing the invoice marks each included labor entry `INVOICED` — the entry's terminal state — and the invoice records which rows it swept up in `labor_entry_ids` and `lift_permit_ids`, each listed in `created_at` ascending order; both lists stay empty on lump-sum work. Time-and-materials billing is capped: if the sum of all prior invoices' `gross_cents` plus this invoice's `gross_cents` would exceed the project's `contract_amount_cents` not-to-exceed cap, creation is rejected with `ERR_NTE_EXCEEDED`.

Under the `LUMP_SUM` variant, the invoice bills by cumulative progress. The request carries `progress_pct`, the cumulative percent of the contract billed to date between zero and one hundred inclusive; it is required exactly when the project is lump-sum, and supplying it for a time-and-materials project — or omitting it for a lump-sum one — fails schema validation with `ERR_VALIDATION`. The cumulative billing target is the project's `contract_amount_cents` multiplied by `progress_pct` and divided by one hundred, rounded half-up to whole cents; the invoice's `gross_cents` is that target minus the sum of `gross_cents` over all prior invoices of the project.

Both variants share the same retainage tail. The `retainage_cents` is the `gross_cents` multiplied by the project's `retainage_pct`, rounded half-up — computed exactly once on the summed gross, never line by line. A `FINAL` invoice additionally releases everything previously withheld: its `retainage_released_cents` is the sum of `retainage_cents` across all prior invoices of the project, while a `PROGRESS` invoice releases zero. The payable `amount_cents` is `gross_cents` minus `retainage_cents` plus `retainage_released_cents`. Two further fiscal rules apply: a project may have at most one `FINAL` invoice, with a second attempt rejected as `ERR_FINAL_INVOICE_EXISTS`, and a `PROGRESS` invoice must have positive billable content — a gross of zero or less is rejected with `ERR_NO_BILLABLE_WORK`, while a `FINAL` invoice is exempt from this rule so that a pure retainage release remains possible.

Three rollup figures on the project keep the financial picture live. The `approved_labor_cents` is the sum of `total_cost_cents` over the project's labor entries in `APPROVED` or `INVOICED` status; the `approved_equipment_cents` is the sum of `equipment_charge_cents` over the project's lift permits in `EXECUTED` status; and the `invoiced_cents` is the sum of `amount_cents` over all invoices of the project. These rollups re-evaluate on labor approval, on rejection of an approved entry, on invoice marking, on lift execution, and on invoice creation, and each such re-evaluation mutates the project — refreshing `updated_at` and incrementing `version` as §2.4 requires.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, computed fields, preconditions, and side effects for every operation are specified in the narratives of §2 and §3; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/projects` | Create a project | ProjectManager |
| GET | `/v1/projects` | List projects with pagination and optional filters | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| GET | `/v1/projects/{id}` | Get a single project (includes version and pinned rigging plan fields) | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/projects/{id}/advance` | Advance the project one hop in the work-phase chain | ProjectManager |
| POST | `/v1/site-surveys` | Create a site survey with anchor and foundation measurements | SiteSupervisor |
| GET | `/v1/projects/{id}/site-surveys` | List site surveys for a project | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/site-surveys/{id}/submit` | Submit a draft survey for review | SiteSupervisor |
| POST | `/v1/site-surveys/{id}/review` | Accept or reject a submitted survey | ProjectManager |
| POST | `/v1/safety-plans` | Create the project's safety plan | SafetyOfficer |
| GET | `/v1/projects/{id}/safety-plans` | List safety plans for a project | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/safety-plans/{id}/activate` | Activate a draft safety plan | SafetyOfficer |
| POST | `/v1/safety-plans/{id}/suspend` | Suspend an active plan; cascades a safety hold onto the project | SafetyOfficer |
| POST | `/v1/safety-plans/{id}/resume` | Resume a suspended plan; clears the project safety hold | SafetyOfficer |
| POST | `/v1/safety-plans/{id}/close` | Close a plan once no active lockouts remain | SafetyOfficer |
| POST | `/v1/lockout-windows` | Schedule a lockout-tagout window on a feeder | SafetyOfficer |
| GET | `/v1/projects/{id}/lockout-windows` | List lockout windows for a project, optionally by feeder | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/lockout-windows/{id}/cancel` | Cancel a scheduled lockout window | SafetyOfficer |
| POST | `/v1/lockout-windows/{id}/release` | Release an active lockout | SafetyOfficer |
| POST | `/v1/rigging-plans` | Create a rigging plan; supersedes the currently approved plan | SiteSupervisor |
| GET | `/v1/projects/{id}/rigging-plans` | List rigging plans for a project | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/rigging-plans/{id}/submit` | Submit a draft rigging plan for review | SiteSupervisor |
| POST | `/v1/rigging-plans/{id}/review` | Approve or reject a submitted rigging plan | ProjectManager |
| POST | `/v1/rigging-plans/{id}/revise` | Return a rejected rigging plan to draft, optionally replacing values | SiteSupervisor |
| POST | `/v1/lift-permits` | Book a crane lift window | SiteSupervisor |
| GET | `/v1/projects/{id}/lift-permits` | List lift permits for a project, optionally by crane or status | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/lift-permits/{id}/execute` | Execute a lift inside its booked window | SiteSupervisor |
| POST | `/v1/lift-permits/{id}/cancel` | Cancel an issued lift permit | SiteSupervisor |
| POST | `/v1/alignment-records` | Record a precision laser alignment measurement | SiteSupervisor |
| GET | `/v1/projects/{id}/alignment-records` | List alignment records for a project | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/alignment-records/{id}/review` | Accept or reject a recorded alignment record | ProjectManager |
| POST | `/v1/commissioning-checklists` | Create the commissioning checklist | ProjectManager |
| GET | `/v1/projects/{id}/commissioning-checklists` | List commissioning checklists for a project | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/commissioning-checklists/{id}/check-item` | Mark one checklist item checked | SiteSupervisor |
| POST | `/v1/commissioning-checklists/{id}/submit` | Submit the completed checklist | ProjectManager |
| POST | `/v1/commissioning-checklists/{id}/sign-off` | Customer representative signs off a submitted checklist | CustomerRep |
| POST | `/v1/labor-entries` | Create a labor entry; cost computed and frozen at creation | SiteSupervisor |
| GET | `/v1/projects/{id}/labor-entries` | List labor entries for a project, optionally by status or worker | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/labor-entries/{id}/submit` | Submit a draft or rejected labor entry for payroll approval | SiteSupervisor |
| POST | `/v1/labor-entries/{id}/approve` | Approve a submitted labor entry | PayrollClerk |
| POST | `/v1/labor-entries/{id}/reject` | Reject a submitted entry or reverse an approved one not yet invoiced | PayrollClerk |
| POST | `/v1/invoices` | Create an invoice; variant selected by the project's billing mode | ProjectManager |
| GET | `/v1/projects/{id}/invoices` | List invoices for a project | ProjectManager, SiteSupervisor, SafetyOfficer, PayrollClerk, CustomerRep |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock; drives automatic time-based transitions | ProjectManager |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SAFETY_HOLD` | 409 |
| `ERR_SAFETY_PLAN_NOT_ACTIVE` | 409 |
| `ERR_SITE_SURVEY_NOT_ACCEPTED` | 409 |
| `ERR_RIGGING_PLAN_NOT_APPROVED` | 409 |
| `ERR_NO_EXECUTED_LIFT` | 409 |
| `ERR_LOCKOUTS_OUTSTANDING` | 409 |
| `ERR_ALIGNMENT_OUTSTANDING` | 409 |
| `ERR_CHECKLIST_NOT_SIGNED_OFF` | 409 |
| `ERR_SAFETY_PLAN_EXISTS` | 409 |
| `ERR_CHECKLIST_EXISTS` | 409 |
| `ERR_ANCHOR_OUT_OF_TOLERANCE` | 409 |
| `ERR_FOUNDATION_NOT_CURED` | 409 |
| `ERR_LIFT_WEIGHT_EXCEEDED` | 409 |
| `ERR_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_LOCKOUT_CONFLICT` | 409 |
| `ERR_CRANE_WINDOW_CONFLICT` | 409 |
| `ERR_OUTSIDE_LIFT_WINDOW` | 409 |
| `ERR_NTE_EXCEEDED` | 409 |
| `ERR_FINAL_INVOICE_EXISTS` | 409 |
| `ERR_NO_BILLABLE_WORK` | 409 |
| `ERR_RIGGING_PLAN_OPEN_EXISTS` | 409 |
| `ERR_INTERNAL` | 500 |

# Home Elevator & Residential Lift API — Product Requirements Document

## 1. Introduction

A residential elevator dealer coordinates a long, tightly regulated pipeline for every home it serves: a site survey establishes whether a shaft and pit can physically host a lift; a product is selected against those measurements; a permit is filed with the local authority having jurisdiction and may cycle through corrections; structural modification may be required before installation; the unit is installed, inspected, registered with the state elevator bureau, and then kept under an annual inspection regime; and homeowners may finance part of the work through accessibility grant programs while change orders and final settlement reconcile the money at close. After hand-over, the same dealer dispatches maintenance visits, repairs, and emergency entrapment responses under tiered service contracts with explicit response-time obligations.

This document specifies the REST API that backs that operation. It covers sixteen resources — properties, site surveys, catalog product models, technicians, general contractors, installation and modernization projects, permit applications, structural work orders, elevator units, inspections, state registration certificates, service contracts, service calls, grant programs, grant applications, and change orders — together with a test-driving logical clock that drives time-based sweeps such as permit expiry, certificate renewal windows, and grant-pool exhaustion. The system enforces segregation of duties between installers and inspectors, conservation invariants over grant pools and contract visit counts, optimistic concurrency on the two aggregates whose scope is legitimately re-editable, and a strict validation priority order so that conflicting requests always fail with a predictable error.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting user and `X-User-Role` names the role under which that user acts. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Nine roles are declared. `DealerAdmin` is the dealer's back-office administrator, owning the catalog, people, grant programs, and the logical clock. `ProjectCoordinator` runs the operational pipeline: properties, surveys, projects, permits, work orders, inspection scheduling, registration certificates, service contracts, dispatch, and change-order proposals. `Surveyor` is a field surveyor who completes assigned surveys. `Installer` is an installation technician who completes installations and works dispatched service calls. `Inspector` is a QEI-certified inspector who records inspection results. `Contractor` is an external general contractor who reports structural work complete. `Homeowner` is the property owner, who opens service calls, applies for grants, and decides change orders. `GrantOfficer` approves or denies grant applications. `Regulator` is the government side — the AHJ permit reviewer and state elevator bureau — performing permit review and certificate issuance.

Identity binding differs by role. When `X-User-Role` is `Surveyor`, `Installer`, or `Inspector`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's foreign-key field — such as `surveyor_technician_id`, `inspector_technician_id`, `technician_id`, or `lead_installer_technician_id` — to `X-User-ID`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor`, and ownership checks compare a work order's `contractor_id` to `X-User-ID`. When `X-User-Role` is `DealerAdmin`, `ProjectCoordinator`, `Homeowner`, `GrantOfficer`, or `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. For a `Homeowner`, that opaque identifier is still compared to a `Property`'s `owner_user_id` field wherever ownership of the property behind a resource must be established; the server records the identifier but never compares it to any entity's `id` for the other four opaque roles.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock rather than the logical clock of §2.4.
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

List endpoints accept two query parameters: `limit`, which defaults to 10 and must lie between 1 and 100 inclusive, and `offset`, which defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Results are sorted by `created_at` in ascending order, with ties broken by creation order (earliest-created first). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` so that clients can page deterministically through the full result set; `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`. List endpoints additionally accept exact-match filter query parameters on selected scalar fields of the resource (for example `status` and the resource's foreign-key id fields): a supplied parameter narrows the result to records whose field string-equals the given value, records whose field is null never match a supplied filter, and unrecognized query parameters are ignored.

### 2.4. The Logical Clock and Time-Driven Sweeps

All time-derived behavior in the system is evaluated against a logical clock, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any client sets it, every timestamp comparison observes that default. A `DealerAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc` value. The new instant is unrestricted — it may be earlier than, equal to, or later than the current value. Setting the clock triggers the system sweep in which time-derived statuses are recomputed.

Three sweeps run on every clock advancement. First, any approved permit whose `valid_through` instant has passed (the clock is strictly later than `valid_through`) while the project's installation is not yet complete — that is, while the project's status is none of `INSTALL_COMPLETE`, `AWAITING_REGISTRATION`, `REGISTERED`, `CLOSED`, or `CANCELLED` — transitions to `EXPIRED`; the project's own status is left unchanged, but installation scheduling is blocked until a fresh permit is approved. Second, any certificate in `ACTIVE` whose `expiration_date` is thirty days or fewer in the future transitions to `RENEWAL_DUE`, and any certificate in `ACTIVE` or `RENEWAL_DUE` whose `expiration_date` has passed transitions to `EXPIRED`, which in turn lapses the unit's registration and forces its equipment out of service. Third, grant-program exhaustion is recomputed as pool movements occur. A clock set is never a partial operation: all sweeps implied by the new instant are applied atomically with it.

### 2.5. Resource Identity, Timestamps, and Money

Every resource in the system carries a server-minted `id` formatted as a bare UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 UTC strings with three fractional digits and are drawn from the logical clock of §2.4, never from wall-clock time. The `version` starts at 1 on creation and increments by 1 on every mutation of the resource; `updated_at` is refreshed on the same occasions.

All monetary fields are numbers denominated in dollars and carried to 2 decimal places with round-half-up rounding. Where a calculation is composed of multiple monetary components, the rounding rule attached to that calculation governs each component; in particular, the permit fee is rounded per component before summation and is never re-rounded after the sum, because summing raw components and rounding once at the end is a different algorithm that can diverge by whole cents. Distance fields — catalog `min_pit_depth_inches` and `min_overhead_clearance_inches`, and survey `measured_pit_depth_inches`, `measured_overhead_clearance_inches`, `shaft_width_inches`, and `shaft_depth_inches` — are accepted as JSON numbers in inches and compared as exact decimals with no integer constraint; `floors_served` and `capacity_lbs` must be integers. Durations that feed billing are measured in minutes.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both guards are framed purely in stale-version terms. Within the §2.7 priority order, the stale-version check runs immediately after state admission and before certification.

A product-selection or scope update against a `Project` — the endpoint contract named in §4 as the project `PATCH` — requires the request to carry `expected_project_version`, a non-optional field holding the `version` of the project as the client last observed it. If the project's current `version` has advanced beyond that value since the client's last read, the update is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), so that a coordinator holding a stale view cannot silently overwrite a selection another writer has legitimately superseded. Re-selection while a project is in `DRAFT` or `QUOTED` is a legitimate supersession, which is exactly why the stale writer must be refused rather than allowed to win.

A tier change against a `ServiceContract` — the contract `PATCH` — likewise requires `expected_contract_version` matching the contract's current `version`. A mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). Tier changes on a `DRAFT` contract legitimately supersede one another, so the same stale-writer refusal applies.

No other endpoint takes an expected-version field.

### 2.7. Validation Priority Order

Every endpoint applies its guard checks in a fixed priority order, and when several checks could fail on the same request the earliest one wins. The order is:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and the role is a declared role; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization** — the role is permitted on the endpoint; otherwise `ERR_FORBIDDEN` (HTTP 403).
3. **Path existence** — path resource identifiers exist, validated left to right along the URL, each yielding its resource-specific not-found error (`ERR_PROPERTY_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_PRODUCT_MODEL_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_CALL_NOT_FOUND`, `ERR_GRANT_PROGRAM_NOT_FOUND`, `ERR_GRANT_APPLICATION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`; all HTTP 404).
4. **Body well-formedness and body references** — required fields are present, types and enum members are valid, and no unknown fields appear, yielding `ERR_INVALID_REQUEST` (HTTP 400); an explicit `null` for any field is treated as absent, so a `null` required field fails as missing. Only after that are the body's foreign-key references (`property_id`, `survey_id`, `product_model_id`, technician ids, `contractor_id`, `project_id`, `unit_id`, `program_id`, `modernize_unit_id`) resolved, each to the same not-found set.
5. **State admission** — the target resource is in a state that allows the operation, covering the per-resource state guards (`ERR_SURVEY_STATE_FORBIDS`, `ERR_PROJECT_STATE_FORBIDS`, `ERR_PERMIT_STATE_FORBIDS`, `ERR_WORK_ORDER_STATE_FORBIDS`, `ERR_UNIT_STATE_FORBIDS`, `ERR_INSPECTION_STATE_FORBIDS`, `ERR_CERTIFICATE_STATE_FORBIDS`, `ERR_CONTRACT_STATE_FORBIDS`, `ERR_SERVICE_CALL_STATE_FORBIDS`, `ERR_APPLICATION_STATE_FORBIDS`, `ERR_CHANGE_ORDER_STATE_FORBIDS`, `ERR_PROGRAM_STATE_FORBIDS`; all HTTP 409) and the creation-time cross-entity gates enumerated in §3.
6. **Certification** — the referenced technician holds the certification the operation demands: CET (or `CET_AND_QEI`) to install or to be dispatched on `REPAIR` and `ENTRAPMENT` calls, QEI (or `CET_AND_QEI`) to perform inspections; otherwise `ERR_TECHNICIAN_NOT_CERTIFIED` (HTTP 403).
7. **Identity binding and independence** — caller-identity bindings such as lead installer, assigned surveyor, assigned inspector, dispatched technician, assigned contractor, and property owner, and the segregation-of-duties rule that the inspector must differ from the project's lead installer (`ERR_INSPECTOR_NOT_INDEPENDENT`, `ERR_NOT_LEAD_INSTALLER`, `ERR_NOT_ASSIGNED_SURVEYOR`, `ERR_NOT_ASSIGNED_INSPECTOR`, `ERR_NOT_ASSIGNED_TECHNICIAN`, `ERR_NOT_ASSIGNED_CONTRACTOR`, `ERR_NOT_PROPERTY_OWNER`; all HTTP 403).
8. **Referenced-entity status** — referenced configuration entities are in an allowed status: model not discontinued (`ERR_MODEL_DISCONTINUED`, 409), contractor active (`ERR_CONTRACTOR_NOT_ACTIVE`, 409), technician active (`ERR_TECHNICIAN_NOT_ACTIVE`, 409), grant program open (`ERR_PROGRAM_NOT_OPEN`, 409), unit in service for contract activation (`ERR_UNIT_NOT_IN_SERVICE`, 409), survey completed (`ERR_SURVEY_NOT_COMPLETED`, 409).
9. **Uniqueness and overlap** — one non-terminal permit per project (`ERR_OPEN_PERMIT_EXISTS`), one non-terminal structural work order per project (`ERR_OPEN_WORK_ORDER_EXISTS`), one live contract per unit (`ERR_CONTRACT_ALREADY_EXISTS`), serial-number uniqueness (`ERR_SERIAL_NUMBER_TAKEN`), one pending application per project-program pair (`ERR_DUPLICATE_APPLICATION`), contractor window overlap (`ERR_CONTRACTOR_WINDOW_OVERLAP`), inspector buffered conflicts (`ERR_INSPECTOR_BUFFER_CONFLICT`), one in-flight modernization per unit (`ERR_UNIT_PROJECT_IN_PROGRESS`), project-type eligibility (`ERR_PROJECT_TYPE_INELIGIBLE`, 422); all others HTTP 409.
10. **Temporal gates** — window ordering and date gates (`ERR_INVALID_DATE_RANGE`, `ERR_APPLICATION_WINDOW_CLOSED`, `ERR_RENEWAL_GRACE_EXPIRED`, all 422; `ERR_PERMIT_EXPIRED_FOR_INSTALL`, `ERR_INSTALL_WINDOW_NOT_STARTED`, `ERR_INSPECTION_NOT_STARTED`, all 409).
11. **Fiscal gates, always last** — money gates are evaluated after every other class: household income at submission (`ERR_INCOME_ABOVE_CAP`, 402), verified income at approval (`ERR_VERIFIED_INCOME_INELIGIBLE`, 402), and pool availability at approval (`ERR_GRANT_POOL_EXHAUSTED`, 402).

Because fiscal gates come last, a grant submission that fails both the application window and the income cap reports `ERR_APPLICATION_WINDOW_CLOSED`, and an approval that would fail both independence-style checks and income verification surfaces the earlier check.

### 2.8. Certifications, Inspection Independence, and the Entity Registers

Technicians carry a `certification` enum of `CET`, `QEI`, or `CET_AND_QEI`. Installation completion and dispatch of `REPAIR` or `ENTRAPMENT` calls require CET-level certification; inspections require QEI-level certification; `CET_AND_QEI` satisfies both. Beyond certification, the system enforces segregation of duties: the inspector on any inspection tied to a project must differ from that project's lead installer, so a technician can never inspect work they installed.

Two person-and-firm registers gate operational work. A technician is onboarded with `full_name`, `certification`, and `home_region`, and starts `ACTIVE`; a technician in `INACTIVE` status may not be referenced by new work, and deactivation itself is refused with `ERR_TECHNICIAN_HAS_OPEN_CALLS` while the technician still has service calls in `OPEN`, `DISPATCHED`, or `ON_SITE`, and with `ERR_TECHNICIAN_HAS_OPEN_INSPECTIONS` while inspections remain `SCHEDULED`. Deactivating an already-`INACTIVE` technician is refused with `ERR_TECHNICIAN_NOT_ACTIVE`. A contractor is registered with `company_name`, a unique `license_number` (a duplicate is refused with `ERR_INVALID_REQUEST`), and the `license_state_code` that issued it, and likewise starts `ACTIVE`; a contractor in `SUSPENDED` status may not be referenced by new selections or work-order releases. Suspending an already-`SUSPENDED` contractor is refused with `ERR_CONTRACTOR_NOT_ACTIVE`. Product models are catalogued with a unique `model_code` (a duplicate is refused with `ERR_INVALID_REQUEST`), a `drive_type` of `HYDRAULIC`, `TRACTION`, `PNEUMATIC`, or `PLATFORM_LIFT`, their dimensional minimums, a rated `capacity_lbs`, and the two catalog prices; a model moves from `ACTIVE` to `DISCONTINUED` and then may not be selected or filed against. Discontinuing an already-`DISCONTINUED` model is refused with `ERR_MODEL_DISCONTINUED`. Every stateful resource exposes its lifecycle through a `status` field (or, for elevator units, the two parallel fields `equipment_status` and `registration_status`).

## 3. Business Logic & Workflows

### 3.1. Properties, Surveys, and Feasibility

Everything begins with the home. A `ProjectCoordinator` registers a property by supplying `owner_user_id` (the opaque identifier of the homeowner, stored so that later ownership checks compare `X-User-ID` against it), `address_line`, the `state_code` that will drive the registration requirement (stored as supplied, with no format validation beyond being a string), and optionally `has_existing_shaft`, which defaults to false when omitted.

With a property on file, the coordinator schedules a site survey by naming the `property_id`, the `surveyor_technician_id` of an `ACTIVE` technician, and a `scheduled_date`. A new survey starts in `SCHEDULED`. When the field visit happens, the assigned surveyor — and only that surveyor, with any other caller refused `ERR_NOT_ASSIGNED_SURVEYOR` — records completion by submitting `measured_pit_depth_inches`, `measured_overhead_clearance_inches`, `shaft_width_inches`, `shaft_depth_inches`, and `floors_served` (at least 2; a smaller value is refused with `ERR_INVALID_REQUEST`). A coordinator may instead cancel a still-scheduled survey, moving it to `CANCELLED`. Completing or cancelling a survey that has already left `SCHEDULED` is refused with `ERR_SURVEY_STATE_FORBIDS`.

Completion computes the `feasibility_verdict` by comparing the measurements against every product model whose status is `ACTIVE` at that moment. For each candidate model, the pit shortfall is the amount by which the model's `min_pit_depth_inches` exceeds `measured_pit_depth_inches`, floored at zero, and the overhead shortfall is the amount by which its `min_overhead_clearance_inches` exceeds `measured_overhead_clearance_inches`, also floored at zero. A model **fits directly** when both shortfalls are exactly zero; it **fits correctably** when each shortfall is at most 12 inches, the maximum correctable shortfall. The verdict is `FEASIBLE` when at least one active model fits directly; `CONDITIONAL` when none fits directly but at least one fits correctably; and `INFEASIBLE` otherwise — including the degenerate case where no active models exist at all. These are exact decimal comparisons with no rounding.

### 3.2. Product Selection and the Provisional Quote

A project is born when a coordinator creates one from a completed survey, supplying `property_id`, `survey_id`, a `project_type` of `NEW_INSTALLATION` or `MODERNIZATION`, and — only for a modernization — `modernize_unit_id` naming the existing unit to be replaced; omitting it on a modernization or supplying it on a new installation is refused with `ERR_INVALID_REQUEST`. The supplied `property_id` is stored as given; the server does not require it to equal the survey's `property_id`. The survey must be `COMPLETED`, or creation fails with `ERR_SURVEY_NOT_COMPLETED`, and its verdict must not be `INFEASIBLE`, or creation fails with `ERR_SURVEY_INFEASIBLE`. Creating a modernization project immediately moves the target unit's equipment status from `IN_SERVICE` or `OUT_OF_SERVICE` to `UNDER_MODERNIZATION`; a unit in any other equipment state triggers `ERR_UNIT_STATE_FORBIDS`, and a unit already referenced by another non-terminal modernization project triggers `ERR_UNIT_PROJECT_IN_PROGRESS`. A new project starts in `DRAFT`.

Product selection is a scope update performed by the coordinator and is the OCC-guarded write described in §2.6: the request must carry `expected_project_version` alongside any of `product_model_id`, `lead_installer_technician_id`, and `contractor_id`, and at least one of those three fields must be present, else `ERR_INVALID_REQUEST`. The first valid selection moves the project from `DRAFT` to `QUOTED`; a further selection while the project is still in `DRAFT` or `QUOTED` legitimately supersedes the prior one and recomputes every pricing field, incrementing `Project.version` by 1 each time. A scope update that does not supply `product_model_id` changes only the supplied fields and leaves every pricing field unchanged.

Selection enforces a battery of checks. The referenced model must still be `ACTIVE` (`ERR_MODEL_DISCONTINUED`). The model must fit the survey: recompute the pit and overhead shortfalls exactly as the feasibility verdict does, and if either shortfall exceeds the 12-inch maximum correctable shortfall the selection is rejected with `ERR_MODEL_DOES_NOT_FIT`. When either shortfall is positive, `requires_structural` is set to true and a `contractor_id` must be supplied (`ERR_CONTRACTOR_REQUIRED`) naming an `ACTIVE` contractor (`ERR_CONTRACTOR_NOT_ACTIVE`). The `lead_installer_technician_id` must be present for a selection — neither supplied in the request nor already recorded on the project yields `ERR_INVALID_REQUEST` — and must name an `ACTIVE` technician (`ERR_TECHNICIAN_NOT_ACTIVE`) holding CET-level certification (`ERR_TECHNICIAN_NOT_CERTIFIED`).

The **provisional quote** is computed at every successful selection. When `requires_structural` is true, the `structural_estimate` is a base structural fee of $1,500.00 plus $250.00 per inch of pit shortfall plus $150.00 per inch of overhead shortfall; when no shortfall exists, the estimate is zero. The floor fee is $750.00 for each landing beyond the two landings included in every installation — that is, the count of `floors_served` above 2, floored at zero, times $750.00. The `contract_price` is then the model's `base_price` plus its `install_labor_price` plus the `structural_estimate` plus the floor fee, all in dollars at 2 decimal places with round-half-up rounding. This quote is forward-looking: it uses the survey's measurements and catalog prices, with structural work priced at estimate. The `approved_change_order_total` starts at zero, `disbursed_grants` starts at zero, `funding_posture` starts at `UNFUNDED`, `structural_adjustment` starts null and is reconciled later, `final_invoice` remains null until close, and `homeowner_balance` remains null until the first successful selection computes a `contract_price`. Before close, the running `homeowner_balance` is `contract_price` plus `approved_change_order_total` minus `disbursed_grants`.

### 3.3. Permitting and the Corrections Cycle

Once quoted, the coordinator files a permit application with the authority having jurisdiction by supplying the `project_id` and the `ahj_name`. Filing is allowed while the project is in `QUOTED`, `PERMIT_APPROVED`, or `READY_FOR_INSTALL` — the latter two cover re-permitting after an expiry — and only a project in `QUOTED` actually moves, advancing to `PERMIT_IN_PROGRESS`; a project already in `PERMIT_APPROVED` or `READY_FOR_INSTALL` stays in place while the new permit is reviewed. A project in any other state is refused with `ERR_PROJECT_STATE_FORBIDS`. The model must still be `ACTIVE` at filing time (`ERR_MODEL_DISCONTINUED`), and the project must not already carry a non-terminal permit application (`ERR_OPEN_PERMIT_EXISTS`).

The permit `fee` is computed at filing with a pinned rounding order: each percentage component is rounded half-up to 2 decimal places **before** summation, and no rounding happens after the sum. The plan-review component is 1.5 percent of the project's `contract_price`, the energy component is 0.4 percent, and the accessibility component is 0.7 percent, each individually rounded; the floor component is exactly $50.00 per landing times the survey's `floors_served` with no rounding needed; and the total is a base fee of $250.00 plus the floor component plus the three rounded percentage components.

A fresh application enters `UNDER_REVIEW`. From there a `Regulator` may request corrections, moving it to `CORRECTIONS_REQUIRED` and incrementing `revision_count` (which starts at 0) by 1, with a `correction_notes` string required in the request (validated but not persisted on the application). The coordinator resubmits, returning the application to `UNDER_REVIEW`; the cycle can repeat. The regulator may approve — permitted only while the project is in `PERMIT_IN_PROGRESS`, else `ERR_PROJECT_STATE_FORBIDS` — which sets `approved_date` to the logical clock and `valid_through` to 180 days later, moves the application to `APPROVED`, advances the project from `PERMIT_IN_PROGRESS` to `PERMIT_APPROVED`, and, when the project requires no structural work, auto-advances it further to `READY_FOR_INSTALL`. Alternatively the regulator may deny with a `denial_reason` string required in the request (likewise validated but not persisted), moving the application to `DENIED` and dropping the project back from `PERMIT_IN_PROGRESS` to `QUOTED`, where a corrected strategy can be re-filed.

Time works against an approved permit: when the clock sweep finds the clock past `valid_through` while installation is incomplete, the application moves from `APPROVED` to `EXPIRED`. Expiry does not move the project, but scheduling an installation against an expired permit fails with `ERR_PERMIT_EXPIRED_FOR_INSTALL`, so the coordinator re-files — the re-permit path above. Permit applications also move from `UNDER_REVIEW`, `CORRECTIONS_REQUIRED`, or `APPROVED` to `CANCELLED` automatically when the parent project is cancelled. Operating on a permit that is not in the state an action requires yields `ERR_PERMIT_STATE_FORBIDS`.

### 3.4. Structural Modification Work Orders

A project whose survey shows a correctable shortfall requires structural modification before installation, coordinated through a structural work order. The coordinator creates one with `project_id`, `contractor_id`, a `scope_description`, a work window from `scheduled_start_date` to `scheduled_end_date` (end must be strictly after start, else `ERR_INVALID_DATE_RANGE`), and the contractor's `estimated_cost`. Creation is gated: the project must be in `PERMIT_APPROVED` with `requires_structural` true, and it must not already carry a non-terminal work order (`ERR_OPEN_WORK_ORDER_EXISTS`). The named contractor must match the contractor recorded on the project; a mismatch is refused with `ERR_INVALID_REQUEST`. A new work order starts in `DRAFT`.

Releasing the work order hands it to the contractor. Release requires the contractor to be `ACTIVE` (`ERR_CONTRACTOR_NOT_ACTIVE`) and checks window overlap against that contractor's other released or work-complete orders: the windows are treated as half-open intervals, so a conflict exists exactly when the new window's start is before an existing window's end **and** the existing window's start is before the new window's end; pure adjacency — one window's end equal to the other's start — is allowed. A true overlap is rejected with `ERR_CONTRACTOR_WINDOW_OVERLAP`. Release moves the work order from `DRAFT` to `RELEASED` and the project from `PERMIT_APPROVED` to `STRUCTURAL_IN_PROGRESS`.

The contractor — only the contractor whose `id` matches the work order's `contractor_id`, with anyone else refused `ERR_NOT_ASSIGNED_CONTRACTOR` — reports completion with an `actual_cost`, moving the order from `RELEASED` to `WORK_COMPLETE`. The coordinator then verifies: verification moves the order from `WORK_COMPLETE` to `VERIFIED`, advances the project from `STRUCTURAL_IN_PROGRESS` to `READY_FOR_INSTALL`, and computes the project's `structural_adjustment` as the reconciliation between actual and estimated structural cost. If the actual cost exceeds the `structural_estimate`, the homeowner absorbs half of the overage — the excess times 0.50, rounded half-up to 2 decimal places; if the actual cost comes in at or under the estimate, the adjustment is the full signed difference, crediting the homeowner the entire underrun. When a project requires no structural work, or no verified work order exists, the adjustment is zero. Verification may instead be rejected with a `rejection_reason`, which loops the order back from `WORK_COMPLETE` to `RELEASED` for rework and clears `actual_cost` back to null. Work orders in `DRAFT` or `RELEASED` are cancelled automatically when the parent project is cancelled, and operating on an order in the wrong state yields `ERR_WORK_ORDER_STATE_FORBIDS`.

### 3.5. Installation, Acceptance Inspection, and the Elevator Unit

With the project in `READY_FOR_INSTALL`, the coordinator schedules the installation window by supplying `install_start_date` and `install_end_date`. The end must be strictly after the start (`ERR_INVALID_DATE_RANGE`), and the project's current permit — the most recently filed `APPROVED` application — must have a `valid_through` at or after the logical clock; having no `APPROVED` permit at all yields the same `ERR_PERMIT_EXPIRED_FOR_INSTALL`. Scheduling moves the project to `INSTALL_SCHEDULED`.

Completion is performed by the installer of record: the caller's `X-User-ID` must equal the project's `lead_installer_technician_id` (`ERR_NOT_LEAD_INSTALLER`), the logical clock must have reached `install_start_date` (`ERR_INSTALL_WINDOW_NOT_STARTED`), and the supplied `serial_number` must be unique across every elevator unit in the system (`ERR_SERIAL_NUMBER_TAKEN`). Completion moves the project from `INSTALL_SCHEDULED` to `INSTALL_COMPLETE` and creates the `ElevatorUnit`: `property_id` and `product_model_id` are copied from the project, `project_id` points back to the installing project, `serial_number` comes from the input, `install_date` is the logical clock timestamp, `equipment_status` starts at `INSTALLED`, and `registration_status` starts at `UNREGISTERED`. For a modernization, the new unit's `modernized_from_unit_id` records the lineage back to the unit being replaced.

Before the state will register the unit, an acceptance inspection must pass. The coordinator schedules inspections by supplying `unit_id`, an `inspection_type`, the `inspector_technician_id`, and a window from `scheduled_start` to `scheduled_end` (end strictly after start, `ERR_INVALID_DATE_RANGE`). `ACCEPTANCE` and `MODERNIZATION_ACCEPTANCE` inspections also require a `project_id` — omitting it yields `ERR_INVALID_REQUEST`, and supplying one for an `ANNUAL` or `REINSPECTION` inspection likewise yields `ERR_INVALID_REQUEST` — and require that project to be in `INSTALL_COMPLETE`; the inspector must hold QEI-level certification (`ERR_TECHNICIAN_NOT_CERTIFIED`) and must differ from the project's lead installer (`ERR_INSPECTOR_NOT_INDEPENDENT`). Scheduling also enforces a buffered-conflict rule: a new inspection window may not begin within 45 minutes of another `SCHEDULED` inspection for the same inspector — exactly, a conflict exists when the new window's start is earlier than 45 minutes after an existing window's end or the existing window's start is earlier than 45 minutes after the new window's end, so adjacency without a full 45-minute gap in either direction is rejected with `ERR_INSPECTOR_BUFFER_CONFLICT`. A new inspection starts in `SCHEDULED` with an empty `deficiency_codes` array.

Only the assigned inspector records the result (`ERR_NOT_ASSIGNED_INSPECTOR`), and not before `scheduled_start` (`ERR_INSPECTION_NOT_STARTED`). The request carries a `result` string matched case-insensitively against pass/passed and fail/failed, any other value yielding `ERR_INVALID_REQUEST`; the system stamps `recorded_at` with the logical clock at that moment. A passing result moves the inspection to `PASSED` and stores an empty `deficiency_codes` array; a failing result moves it to `FAILED` and requires a non-empty `deficiency_codes` array (`ERR_DEFICIENCY_CODES_REQUIRED`, a check evaluated only after the state, identity, and not-yet-started gates above). When an `ACCEPTANCE` or `MODERNIZATION_ACCEPTANCE` inspection passes, the project advances from `INSTALL_COMPLETE` to `AWAITING_REGISTRATION`; a passing `MODERNIZATION_ACCEPTANCE` additionally decommissions the replaced unit, moving it from `UNDER_MODERNIZATION` to `DECOMMISSIONED` while the replacement unit remains `INSTALLED`, so the property's count of non-decommissioned units is unchanged across the pair. Inspections may also be cancelled by the coordinator while still `SCHEDULED`, and are cancelled automatically by the project-cancel cascade. Operating on an inspection that has left `SCHEDULED` yields `ERR_INSPECTION_STATE_FORBIDS`.

### 3.6. State Registration, Renewal, and the Inspection Calendar

With acceptance passed, the coordinator applies for state registration of the unit. Application requires the unit's latest `ACCEPTANCE` or `MODERNIZATION_ACCEPTANCE` inspection to be `PASSED` (`ERR_ACCEPTANCE_NOT_PASSED`) — "latest" throughout this section means the greatest `recorded_at`, ties broken by creation order — and creates a certificate in `PENDING_ISSUANCE`; the server does not prevent multiple certificates from existing for the same unit. The `Regulator` then issues it: a `certificate_number` is minted in the format `CERT-` followed by twelve uppercase hexadecimal characters, `issued_date` is set to the logical clock, `expiration_date` is set exactly one year later, and the certificate moves to `ACTIVE`. Issuance simultaneously flips the unit's `registration_status` from `UNREGISTERED` to `REGISTERED`, its `equipment_status` from `INSTALLED` to `IN_SERVICE`, and advances the installing project from `AWAITING_REGISTRATION` to `REGISTERED`.

Certificates age on the clock sweep described in §2.4: `ACTIVE` becomes `RENEWAL_DUE` once the clock reaches thirty days before `expiration_date`, and `ACTIVE` or `RENEWAL_DUE` becomes `EXPIRED` once the clock passes `expiration_date`. Expiry lapses the unit — `registration_status` from `REGISTERED` to `LAPSED` — and forces the equipment out of service — `equipment_status` from `IN_SERVICE` to `OUT_OF_SERVICE` — which in turn cascade-cancels the unit's `OPEN` or `DISPATCHED` service calls with their consumed visits restored (this call cancellation applies on every certificate expiry, even if the equipment was not `IN_SERVICE` at the time).

Renewal always moves the certificate back to `ACTIVE`, extends validity by one year, increments `renewal_count` (which starts at 0), and records the charged fee in `last_renewal_fee`, but the exact behavior depends on the certificate's standing. From `RENEWAL_DUE`, renewal requires the unit's latest `ANNUAL` inspection to have `PASSED` (`ERR_ANNUAL_INSPECTION_REQUIRED`) and charges the base renewal fee of $175.00 with `expiration_date` extended by one year from its current value. From `EXPIRED`, a late renewal first requires the unit's latest `ANNUAL` inspection to have `PASSED` (`ERR_ANNUAL_INSPECTION_REQUIRED`, evaluated before the grace check) and is then allowed only within a 90-day grace window — the clock must be no later than 90 days past `expiration_date`, otherwise `ERR_RENEWAL_GRACE_EXPIRED` and fresh initial registration is required instead; the late fee is tiered by whole days late, where days late is the floor of the elapsed time past expiration in days, floored at zero: zero days late charges the base fee, 1 to 30 days late charges 1.25 times base, and 31 to 90 days late charges 1.50 times base, each rounded half-up to 2 decimal places. Late renewal sets `expiration_date` to one year after the current clock and restores the unit — `registration_status` from `LAPSED` back to `REGISTERED`, `equipment_status` from `OUT_OF_SERVICE` back to `IN_SERVICE`. From `REVOKED`, reinstatement requires the unit's latest `REINSPECTION` to have `PASSED` (`ERR_REINSPECTION_REQUIRED`), always charges the base tier, sets `expiration_date` to one year after the clock, and restores the unit from `SUSPENDED` to `REGISTERED` and from `OUT_OF_SERVICE` to `IN_SERVICE`. Acting on a certificate in a state that forbids the operation yields `ERR_CERTIFICATE_STATE_FORBIDS`.

The annual inspection regime keeps registrations honest. An `ANNUAL` inspection may be scheduled only against a unit whose equipment is `IN_SERVICE` (`ERR_UNIT_NOT_IN_SERVICE`); a `REINSPECTION` may be scheduled only when the unit's latest terminal inspection was `FAILED`, else `ERR_REINSPECTION_NOT_APPLICABLE`; neither carries a `project_id`. A passing `ANNUAL` enables renewal; a failing one fires a four-hop cascade: first the unit's certificate in `ACTIVE` or `RENEWAL_DUE` is `REVOKED`; second the unit's `registration_status` moves from `REGISTERED` to `SUSPENDED`; third its `equipment_status` moves from `IN_SERVICE` to `OUT_OF_SERVICE`; fourth the unit's `OPEN` or `DISPATCHED` service calls are cancelled with consumed visits restored (again regardless of the equipment state at that moment). A passing `REINSPECTION` is the key that unlocks reinstatement from `REVOKED` as described above.

When a unit is decommissioned — whether by modernization acceptance of its replacement or by cancellation of the installing project before registration — every certificate of that unit not already `SUPERSEDED` becomes `SUPERSEDED`, the terminal state for certificates.

### 3.7. Service Contracts and Service Calls

Once a unit is in service, the coordinator may sell a service contract by naming the `unit_id`, a `tier` of `BASIC`, `STANDARD`, or `PREMIUM`, and a `contract_year_start` anchor date; creation requires only that the unit exist — the `IN_SERVICE` requirement is enforced at activation, not at creation. The tier derives the commercial terms: `BASIC` carries an `annual_fee` of $600.00 with 1 included maintenance visit per contract year and an `entrapment_sla_minutes` of 240; `STANDARD` carries $1,200.00 with 2 visits and 120 minutes; `PREMIUM` carries $2,400.00 with 4 visits and 60 minutes. `visits_consumed` starts at zero. A new contract is `DRAFT` and may be re-tiered by the coordinator through the OCC-guarded contract update described in §2.6 — the request carries `tier` and `expected_contract_version`, tier-derived fields are recomputed, and the contract's `version` increments by 1; a tier change on a contract that has left `DRAFT` is refused with `ERR_CONTRACT_STATE_FORBIDS`.

Activation requires the unit's `equipment_status` to be `IN_SERVICE` (`ERR_UNIT_NOT_IN_SERVICE`) and no other `ACTIVE` or `SUSPENDED` contract on the same unit (`ERR_CONTRACT_ALREADY_EXISTS`), moving the contract from `DRAFT` to `ACTIVE`. A contract may be suspended (`ACTIVE` to `SUSPENDED`) and later resumed (`SUSPENDED` back to `ACTIVE`), and may be terminated from either `ACTIVE` or `SUSPENDED` into the terminal `TERMINATED` state; termination detaches any attached `OPEN` or `DISPATCHED` service calls by nulling their `contract_id`, turning them into ad-hoc calls, without restoring any visit consumed at dispatch.

Service calls originate with the homeowner, who supplies the `unit_id`, a `call_type` of `MAINTENANCE_VISIT`, `REPAIR`, or `ENTRAPMENT`, and an optional `description`; no property-ownership or unit-state check is applied at creation. Creation stamps `reported_at` from the logical clock, sets the call to `OPEN`, and auto-attaches the unit's `ACTIVE` contract into `contract_id` when one exists, leaving it null for ad-hoc calls. Dispatch by the coordinator assigns a `technician_id`: the technician must be `ACTIVE` (`ERR_TECHNICIAN_NOT_ACTIVE`); `REPAIR` and `ENTRAPMENT` calls require CET-level certification (`ERR_TECHNICIAN_NOT_CERTIFIED`); and dispatching a `MAINTENANCE_VISIT` under an attached contract requires `visits_consumed` to be below `included_visits` (`ERR_NO_VISITS_REMAINING`) and then increments `visits_consumed` by 1. Dispatch also computes the commercial baseline: the `provisional_estimate` is a flat $0.00 for a `PREMIUM` contract, $150.00 for `STANDARD`, $300.00 for `BASIC`, and $450.00 for an ad-hoc call, and for an `ENTRAPMENT` call the `sla_deadline` is set to `reported_at` plus the attached contract's entrapment SLA minutes — or 240 minutes when no contract is attached. The provisional estimate is deliberately approximate by design: it ignores duration, parts, after-hours timing, and SLA outcome, and may diverge arbitrarily from the final bill.

Arrival is recorded by the dispatched technician (`ERR_NOT_ASSIGNED_TECHNICIAN`), stamping `arrived_at` and moving the call from `DISPATCHED` to `ON_SITE`; for an entrapment call, `sla_breached` is computed here as true exactly when the elapsed minutes from `reported_at` to `arrived_at` are strictly greater than the SLA minutes — arrival exactly at the deadline is compliant. Resolution, likewise restricted to the assigned technician, takes `resolution_notes` and an optional `parts_cost` (defaulting to $0.00 when omitted), stamps `resolved_at` (which must not precede `arrived_at`, else `ERR_INVALID_DATE_RANGE`), moves the call from `ON_SITE` to `RESOLVED`, and computes `final_billable`: the on-site duration from `arrived_at` to `resolved_at` in minutes is rounded **up** to whole half-hour units; each unit bills at $60.00; if the arrival's UTC hour is at or after 18 or before 7 the labor amount is multiplied by 1.5 and rounded half-up to 2 decimals; parts cost is then added; an attached `PREMIUM` contract on an `ENTRAPMENT` call zeroes the gross entirely; an attached `STANDARD` contract halves the gross with round-half-up to 2 decimals; an attached `BASIC` contract grants no discount; and an entrapment call whose SLA was breached subtracts a $100.00 credit with the result floored at zero. The resulting amount is `final_billable`.

A call may be cancelled from `OPEN` or `DISPATCHED`. A homeowner cancelling must own the property behind the unit — `X-User-ID` is compared to the property's `owner_user_id`, else `ERR_NOT_PROPERTY_OWNER`; a coordinator may also cancel; and cancellation additionally arrives automatically from the out-of-service cascade (certificate expiry or annual-inspection failure) — project cancellation does not cancel service calls. When a visit was consumed at dispatch, cancellation decrements `visits_consumed` by 1 as compensation. This bookkeeping obeys a conservation invariant: at every moment, `visits_consumed` plus the derived remaining visits equals the contract's `included_visits` for the current contract year. Calls in a terminal state refuse further transitions with `ERR_SERVICE_CALL_STATE_FORBIDS`.

### 3.8. Accessibility Grants, Change Orders, and Project Settlement

Accessibility funding is administered through grant programs created by a `DealerAdmin` with `program_name`, `funder_name`, `max_award` per application, an `income_cap` on household income, a `coverage_percent` fraction of contract value, a `total_pool`, an application window from `application_open_date` through `application_close_date` (both inclusive), and `eligible_project_types` drawn from `NEW_INSTALLATION` and `MODERNIZATION`. A program opens in `OPEN` with `remaining_pool` equal to `total_pool`. An administrator may pause and resume a program, and may close it permanently from `OPEN`, `PAUSED`, or `EXHAUSTED`; a program whose `remaining_pool` reaches exactly zero on an approval debit moves itself from `OPEN` to `EXHAUSTED`, and an `EXHAUSTED` program whose pool is credited back above zero reopens itself to `OPEN`. Program actions against a program in a forbidding state yield `ERR_PROGRAM_STATE_FORBIDS`. The pool obeys a conservation invariant: `remaining_pool` always equals `total_pool` minus the sum of `final_award` over the program's `APPROVED` and `DISBURSED` applications.

A homeowner applies by naming the `project_id`, the `program_id`, and declaring `household_income`; no property-ownership check is applied at submission. Submission requires the clock to fall within the program's inclusive application window (`ERR_APPLICATION_WINDOW_CLOSED`), the program to be `OPEN` (`ERR_PROGRAM_NOT_OPEN`), the project's `project_type` to appear in the program's `eligible_project_types` (`ERR_PROJECT_TYPE_INELIGIBLE`), the declared income to be no greater than `income_cap` (`ERR_INCOME_ABOVE_CAP`), the project to be in one of `QUOTED`, `PERMIT_IN_PROGRESS`, `PERMIT_APPROVED`, `STRUCTURAL_IN_PROGRESS`, `READY_FOR_INSTALL`, or `INSTALL_SCHEDULED` (`ERR_PROJECT_STATE_FORBIDS`), and no existing `SUBMITTED` or `APPROVED` application for the same project and program pair (`ERR_DUPLICATE_APPLICATION`). A successful submission lands in `SUBMITTED`, stamps `submitted_at`, and computes the `provisional_award`: the lesser of the program's `max_award` and the `coverage_percent` fraction of the project's current contract value — defined as `contract_price` plus `approved_change_order_total` — with the coverage product rounded half-up to 2 decimals. The `provisional_award` deliberately does not observe the funding pool and is never re-anchored to later price changes.

A `GrantOfficer` decides the application. Approval records `verified_income` from the request, stamps `approved_at` from the clock, and enforces, in order relative to the other validation classes of §2.7: the program must be `OPEN` or `EXHAUSTED` (`ERR_PROGRAM_NOT_OPEN`) — submission requires `OPEN`, but an already-submitted application may be approved even after the program exhausts; the verified income must not exceed the `income_cap` (`ERR_VERIFIED_INCOME_INELIGIBLE`); and the `remaining_pool` must be greater than zero (`ERR_GRANT_POOL_EXHAUSTED`). The **final award** recomputes coverage against the current contract value at approval time — again `contract_price` plus `approved_change_order_total`, the coverage fraction rounded half-up to 2 decimals — and then takes the smallest of three caps: that coverage amount, the program's `max_award`, and the program's `remaining_pool`. The award is debited from the pool immediately; a debit that drains the pool to exactly zero flips the program from `OPEN` to `EXHAUSTED`. Because the final award re-anchors to current value and observes the pool, it differs from the provisional award whenever the price moved or the pool binds. Denial requires a `denial_reason` string in the request (validated but not persisted) and moves the application to `DENIED` with no financial effect. Acting on an application in the wrong state yields `ERR_APPLICATION_STATE_FORBIDS`.

Withdrawal is the homeowner's compensating action and requires property ownership (`ERR_NOT_PROPERTY_OWNER`). From `SUBMITTED`, withdrawal simply moves the application to `WITHDRAWN`. From `APPROVED`, withdrawal additionally credits the `final_award` back to the program's `remaining_pool` — reopening an `EXHAUSTED` program if the credit lifts the pool above zero — and recomputes the project's `funding_posture`. After disbursement, the same withdrawal action claws the application back from `DISBURSED` to `CLAWED_BACK`: the program's `remaining_pool` is credited with the `disbursed` amount, the project's `disbursed_grants` is reduced by the same amount, and `homeowner_balance` is recomputed.

Change orders price scope changes after the quote. The coordinator proposes one with `project_id`, a `description`, and a signed non-zero `amount` (zero is refused with `ERR_INVALID_REQUEST`); creation requires the project not to be `CLOSED` or `CANCELLED` (`ERR_PROJECT_STATE_FORBIDS`), and the order lands in `PROPOSED`. The homeowner decides: approval requires property ownership (`ERR_NOT_PROPERTY_OWNER`) and a project not `CLOSED` or `CANCELLED` (`ERR_PROJECT_STATE_FORBIDS`), stamps `approved_at`, and freezes the order's `effective_amount` under a chronological markup rule — an approved change order takes its `amount` with no markup exactly when no other change order of the same project is already `APPROVED` at the moment of approval, and otherwise takes its `amount` increased by 10 percent, rounded half-up to 2 decimal places. Approval also recomputes the project's `approved_change_order_total` as the sum of `effective_amount` over its approved orders, and with it `homeowner_balance` and `funding_posture`. Rejection likewise requires property ownership (`ERR_NOT_PROPERTY_OWNER`) but no project-state check, and moves the order to `REJECTED`. Acting on an order that is not `PROPOSED` yields `ERR_CHANGE_ORDER_STATE_FORBIDS`.

The `funding_posture` derives from committed grant money: summing `final_award` over the project's applications in `APPROVED` or `DISBURSED` gives the committed total; when that total is at least the current contract value and the value is positive the posture is `FULLY_FUNDED`, when the total is positive but below the value it is `PARTIALLY_FUNDED`, and when nothing is committed it is `UNFUNDED`. The posture is recomputed on every grant approval, withdrawal, clawback, change-order approval, project scope update (§3.2), and project close.

Closing is the financial settlement of a `REGISTERED` project, performed by the coordinator. Close first computes `final_invoice`: the `contract_price`, plus the sum of `effective_amount` over all approved change orders (each frozen at approval by the markup rule), plus the `structural_adjustment`. It then runs the **grant disbursement waterfall** over the project's `APPROVED` applications — and only `APPROVED` ones; `SUBMITTED`, `DENIED`, and `WITHDRAWN` applications are excluded — in pinned chronological order by `approved_at` ascending with ties broken by `created_at` ascending. The running balance starts at the just-computed `final_invoice`; each application in turn disburses the lesser of its `final_award` and the remaining balance, records that amount in its `disbursed` field, and moves to `DISBURSED`. When the pass completes, the project's `disbursed_grants` is the sum of all disbursed amounts and `homeowner_balance` is the final remaining balance — `final_invoice` minus `disbursed_grants`. The waterfall resolves what would otherwise be a circular dependency between the balance and each disbursement cap by fixing the chronological pass. Close moves the project to `CLOSED`.

Cancellation is the other exit. A coordinator may cancel a project in any state except `CLOSED`, `CANCELLED`, or `REGISTERED` — a registered project can never be cancelled, and the attempt yields `ERR_PROJECT_STATE_FORBIDS`. Cancellation cascades outward in hops: first, the project's non-terminal permit applications (those in `UNDER_REVIEW`, `CORRECTIONS_REQUIRED`, or `APPROVED`) and structural work orders move to `CANCELLED`, its `SUBMITTED` grant applications move to `WITHDRAWN`, and its `SCHEDULED` inspections move to `CANCELLED`; second, its `APPROVED` grant applications move to `WITHDRAWN` with the `final_award` credited back to the program pool; third, a pool credit that lifts an `EXHAUSTED` program above zero reopens it to `OPEN`. If the project had created a unit, that unit moves from `INSTALLED` to `DECOMMISSIONED` and its certificates are superseded; a modernization cancelled before acceptance instead returns the targeted unit from `UNDER_MODERNIZATION` to `IN_SERVICE`. Disbursed applications cannot exist at cancel time, because disbursement only happens at close and a `REGISTERED` project cannot be cancelled.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Creating a new resource returns HTTP 201 with the created resource in `data`; operations that modify an existing resource return HTTP 200 with the updated resource; error responses use the standard error envelope with the codes catalogued in §5. GET endpoints are readable by all nine roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/properties | Create a property | ProjectCoordinator |
| GET | /api/properties | List properties | All roles |
| GET | /api/properties/`{propertyId}` | Get a property | All roles |
| POST | /api/surveys | Schedule a site survey | ProjectCoordinator |
| GET | /api/surveys | List surveys | All roles |
| GET | /api/surveys/`{surveyId}` | Get a survey | All roles |
| POST | /api/surveys/`{surveyId}`/complete | Record survey measurements; computes the feasibility verdict | Surveyor |
| POST | /api/surveys/`{surveyId}`/cancel | Cancel a scheduled survey | ProjectCoordinator |
| POST | /api/product-models | Create a catalog product model | DealerAdmin |
| GET | /api/product-models | List product models | All roles |
| GET | /api/product-models/`{productModelId}` | Get a product model | All roles |
| POST | /api/product-models/`{productModelId}`/discontinue | Discontinue a model | DealerAdmin |
| POST | /api/technicians | Onboard a technician | DealerAdmin |
| GET | /api/technicians | List technicians | All roles |
| GET | /api/technicians/`{technicianId}` | Get a technician | All roles |
| POST | /api/technicians/`{technicianId}`/deactivate | Deactivate a technician (no open calls/inspections) | DealerAdmin |
| POST | /api/contractors | Register a general contractor | DealerAdmin |
| GET | /api/contractors | List contractors | All roles |
| GET | /api/contractors/`{contractorId}` | Get a contractor | All roles |
| POST | /api/contractors/`{contractorId}`/suspend | Suspend a contractor | DealerAdmin |
| POST | /api/projects | Create a project from a completed survey | ProjectCoordinator |
| GET | /api/projects | List projects | All roles |
| GET | /api/projects/`{projectId}` | Get a project | All roles |
| PATCH | /api/projects/`{projectId}` | Select/supersede product model, lead installer, contractor (OCC-guarded) | ProjectCoordinator |
| POST | /api/projects/`{projectId}`/schedule-installation | Schedule the installation window | ProjectCoordinator |
| POST | /api/projects/`{projectId}`/complete-installation | Lead installer marks installation complete; creates the elevator unit | Installer |
| POST | /api/projects/`{projectId}`/cancel | Cancel a non-terminal project with full cascade | ProjectCoordinator |
| POST | /api/projects/`{projectId}`/close | Close a registered project: final invoice and grant disbursement waterfall | ProjectCoordinator |
| POST | /api/permits | File a permit application (fee computed) | ProjectCoordinator |
| GET | /api/permits | List permit applications | All roles |
| GET | /api/permits/`{permitId}` | Get a permit application | All roles |
| POST | /api/permits/`{permitId}`/request-corrections | AHJ requests corrections (revision cycle) | Regulator |
| POST | /api/permits/`{permitId}`/resubmit | Resubmit a corrected permit | ProjectCoordinator |
| POST | /api/permits/`{permitId}`/approve | Approve a permit (valid 180 days) | Regulator |
| POST | /api/permits/`{permitId}`/deny | Deny a permit | Regulator |
| POST | /api/work-orders | Create a structural work order | ProjectCoordinator |
| GET | /api/work-orders | List work orders | All roles |
| GET | /api/work-orders/`{workOrderId}` | Get a work order | All roles |
| POST | /api/work-orders/`{workOrderId}`/release | Release a work order to the contractor (window overlap checked) | ProjectCoordinator |
| POST | /api/work-orders/`{workOrderId}`/complete-work | Contractor reports work complete with actual cost | Contractor |
| POST | /api/work-orders/`{workOrderId}`/verify | Coordinator verifies structural work | ProjectCoordinator |
| POST | /api/work-orders/`{workOrderId}`/reject-verification | Reject verification; work order loops back for rework | ProjectCoordinator |
| GET | /api/units | List elevator units | All roles |
| GET | /api/units/`{unitId}` | Get an elevator unit | All roles |
| POST | /api/inspections | Schedule an inspection (type-gated, QEI, independence, buffered conflicts) | ProjectCoordinator |
| GET | /api/inspections | List inspections | All roles |
| GET | /api/inspections/`{inspectionId}` | Get an inspection | All roles |
| POST | /api/inspections/`{inspectionId}`/record-result | Inspector records pass/fail; annual failure fires the revocation cascade | Inspector |
| POST | /api/inspections/`{inspectionId}`/cancel | Cancel a scheduled inspection | ProjectCoordinator |
| POST | /api/registration-certificates | Apply for state registration of a unit | ProjectCoordinator |
| GET | /api/registration-certificates | List registration certificates | All roles |
| GET | /api/registration-certificates/`{certificateId}` | Get a certificate | All roles |
| POST | /api/registration-certificates/`{certificateId}`/issue | Regulator issues the certificate | Regulator |
| POST | /api/registration-certificates/`{certificateId}`/renew | Renew, late-renew within grace, or reinstate after reinspection | ProjectCoordinator |
| POST | /api/service-contracts | Create a service contract for a unit | ProjectCoordinator |
| GET | /api/service-contracts | List service contracts | All roles |
| GET | /api/service-contracts/`{contractId}` | Get a service contract | All roles |
| PATCH | /api/service-contracts/`{contractId}` | Change tier on a draft contract (OCC-guarded) | ProjectCoordinator |
| POST | /api/service-contracts/`{contractId}`/activate | Activate a contract (unit in service; one live contract per unit) | ProjectCoordinator |
| POST | /api/service-contracts/`{contractId}`/suspend | Suspend a contract | ProjectCoordinator |
| POST | /api/service-contracts/`{contractId}`/resume | Resume a suspended contract | ProjectCoordinator |
| POST | /api/service-contracts/`{contractId}`/terminate | Terminate a contract; open calls detach to ad-hoc | ProjectCoordinator |
| POST | /api/service-calls | Homeowner opens a service call; active contract auto-attaches | Homeowner |
| GET | /api/service-calls | List service calls | All roles |
| GET | /api/service-calls/`{serviceCallId}` | Get a service call | All roles |
| POST | /api/service-calls/`{serviceCallId}`/dispatch | Dispatch a technician | ProjectCoordinator |
| POST | /api/service-calls/`{serviceCallId}`/arrive | Technician arrives on site | Installer |
| POST | /api/service-calls/`{serviceCallId}`/resolve | Technician resolves the call; final billable computed | Installer |
| POST | /api/service-calls/`{serviceCallId}`/cancel | Cancel an open/dispatched call (visit restoration) | Homeowner, ProjectCoordinator |
| POST | /api/grant-programs | Create a grant program with a funding pool | DealerAdmin |
| GET | /api/grant-programs | List grant programs | All roles |
| GET | /api/grant-programs/`{programId}` | Get a grant program | All roles |
| POST | /api/grant-programs/`{programId}`/pause | Pause a program | DealerAdmin |
| POST | /api/grant-programs/`{programId}`/resume | Resume a paused program | DealerAdmin |
| POST | /api/grant-programs/`{programId}`/close | Close a program permanently | DealerAdmin |
| POST | /api/grant-applications | Homeowner applies for accessibility funding; provisional award computed | Homeowner |
| GET | /api/grant-applications | List grant applications | All roles |
| GET | /api/grant-applications/`{applicationId}` | Get a grant application | All roles |
| POST | /api/grant-applications/`{applicationId}`/approve | Approve with verified income; final award clamps to pool | GrantOfficer |
| POST | /api/grant-applications/`{applicationId}`/deny | Deny an application | GrantOfficer |
| POST | /api/grant-applications/`{applicationId}`/withdraw | Withdraw or claw back; pool credited | Homeowner |
| POST | /api/change-orders | Propose a change order on a project | ProjectCoordinator |
| GET | /api/change-orders | List change orders | All roles |
| GET | /api/change-orders/`{changeOrderId}` | Get a change order | All roles |
| POST | /api/change-orders/`{changeOrderId}`/approve | Homeowner approves; chronological markup applies | Homeowner |
| POST | /api/change-orders/`{changeOrderId}`/reject | Homeowner rejects | Homeowner |
| POST | /api/_clock/set_current_utc | Set the logical clock; triggers time-derived sweeps | DealerAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_PROPERTY_NOT_FOUND | 404 |
| ERR_SURVEY_NOT_FOUND | 404 |
| ERR_PRODUCT_MODEL_NOT_FOUND | 404 |
| ERR_TECHNICIAN_NOT_FOUND | 404 |
| ERR_CONTRACTOR_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_PERMIT_NOT_FOUND | 404 |
| ERR_WORK_ORDER_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_SERVICE_CALL_NOT_FOUND | 404 |
| ERR_GRANT_PROGRAM_NOT_FOUND | 404 |
| ERR_GRANT_APPLICATION_NOT_FOUND | 404 |
| ERR_CHANGE_ORDER_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_SURVEY_STATE_FORBIDS | 409 |
| ERR_PROJECT_STATE_FORBIDS | 409 |
| ERR_PERMIT_STATE_FORBIDS | 409 |
| ERR_WORK_ORDER_STATE_FORBIDS | 409 |
| ERR_UNIT_STATE_FORBIDS | 409 |
| ERR_INSPECTION_STATE_FORBIDS | 409 |
| ERR_CERTIFICATE_STATE_FORBIDS | 409 |
| ERR_CONTRACT_STATE_FORBIDS | 409 |
| ERR_SERVICE_CALL_STATE_FORBIDS | 409 |
| ERR_APPLICATION_STATE_FORBIDS | 409 |
| ERR_CHANGE_ORDER_STATE_FORBIDS | 409 |
| ERR_PROGRAM_STATE_FORBIDS | 409 |
| ERR_SURVEY_NOT_COMPLETED | 409 |
| ERR_SURVEY_INFEASIBLE | 422 |
| ERR_MODEL_DOES_NOT_FIT | 422 |
| ERR_MODEL_DISCONTINUED | 409 |
| ERR_CONTRACTOR_REQUIRED | 422 |
| ERR_TECHNICIAN_NOT_CERTIFIED | 403 |
| ERR_TECHNICIAN_NOT_ACTIVE | 409 |
| ERR_TECHNICIAN_HAS_OPEN_CALLS | 409 |
| ERR_TECHNICIAN_HAS_OPEN_INSPECTIONS | 409 |
| ERR_CONTRACTOR_NOT_ACTIVE | 409 |
| ERR_INSPECTOR_NOT_INDEPENDENT | 403 |
| ERR_NOT_LEAD_INSTALLER | 403 |
| ERR_NOT_ASSIGNED_SURVEYOR | 403 |
| ERR_NOT_ASSIGNED_INSPECTOR | 403 |
| ERR_NOT_ASSIGNED_TECHNICIAN | 403 |
| ERR_NOT_ASSIGNED_CONTRACTOR | 403 |
| ERR_NOT_PROPERTY_OWNER | 403 |
| ERR_OPEN_PERMIT_EXISTS | 409 |
| ERR_OPEN_WORK_ORDER_EXISTS | 409 |
| ERR_CONTRACT_ALREADY_EXISTS | 409 |
| ERR_SERIAL_NUMBER_TAKEN | 409 |
| ERR_DUPLICATE_APPLICATION | 409 |
| ERR_CONTRACTOR_WINDOW_OVERLAP | 409 |
| ERR_INSPECTOR_BUFFER_CONFLICT | 409 |
| ERR_UNIT_PROJECT_IN_PROGRESS | 409 |
| ERR_NO_VISITS_REMAINING | 409 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_APPLICATION_WINDOW_CLOSED | 422 |
| ERR_PERMIT_EXPIRED_FOR_INSTALL | 409 |
| ERR_INSTALL_WINDOW_NOT_STARTED | 409 |
| ERR_INSPECTION_NOT_STARTED | 409 |
| ERR_RENEWAL_GRACE_EXPIRED | 422 |
| ERR_DEFICIENCY_CODES_REQUIRED | 422 |
| ERR_ACCEPTANCE_NOT_PASSED | 409 |
| ERR_ANNUAL_INSPECTION_REQUIRED | 409 |
| ERR_REINSPECTION_REQUIRED | 409 |
| ERR_REINSPECTION_NOT_APPLICABLE | 409 |
| ERR_UNIT_NOT_IN_SERVICE | 409 |
| ERR_PROGRAM_NOT_OPEN | 409 |
| ERR_INCOME_ABOVE_CAP | 402 |
| ERR_VERIFIED_INCOME_INELIGIBLE | 402 |
| ERR_GRANT_POOL_EXHAUSTED | 402 |
| ERR_PROJECT_TYPE_INELIGIBLE | 422 |
| ERR_STALE_PROJECT_VERSION | 412 |
| ERR_STALE_CONTRACT_VERSION | 412 |

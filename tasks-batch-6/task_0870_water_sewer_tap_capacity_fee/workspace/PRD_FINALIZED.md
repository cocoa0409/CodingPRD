# Water-Sewer Tap & Capacity Fee API — Product Requirements Document

## 1. Introduction

Municipal water and sewer utilities face a deceptively intricate problem the moment a property owner asks to connect a parcel to the public system. Before a single pipe is tapped, the utility must determine whether public mains even front the property, calculate capacity (impact) fees that reflect the hydraulic burden the new connection places on the system, collect and account for tap-installation labor, coordinate field inspections and meter installations against limited crews, enforce backflow-prevention requirements for higher-risk uses, and — where a developer must build a main extension to reach the parcel — hold construction escrow and later recover a fair share of that cost from the neighbors who eventually benefit. This API is the system of record for that entire journey.

The platform is at heart a pricing engine wrapped in a workflow orchestrator. Capacity fees are assessed from a governing rate card and a meter-size capacity schedule, adjusted by use classification and, for redevelopment, credited for the capacity of any prior connection. Layered on top of the pricing logic is a network of interdependent state machines: connection applications move through submission, review, and approval; developer agreements guarantee escrow before a main extension may be built; inspections and meter sets cascade into one another; and latecomer reimbursements draw down a conserved recovery pool. Because several of these processes touch shared money balances, the system enforces optimistic concurrency on the two write paths where a stale read could silently corrupt a ledger, and it separates duties so that no single reviewer both determines availability and approves the same application.

This document specifies the complete contract: the resources, their fields, the transitions and the preconditions that guard them, the exact fee formulas, the validation ordering, and the error vocabulary. It is the sole reference for implementation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the acting role is not permitted to invoke the requested operation under the access matrix, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Applicant`, `Developer`, `UtilityReviewer`, `FieldInspector`, and `UtilityAdmin`.

Four of these roles carry an **opaque** identity: their `X-User-ID` is a free-form operator identifier that is not the primary key of any persisted resource. When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque identifier that the server records as `applicant_user_id` when a connection application is created; ownership of an application is later checked by comparing that stored `applicant_user_id` to the caller's `X-User-ID`. When `X-User-Role` is `Developer`, `X-User-ID` is an opaque identifier recorded as `developer_user_id` on the projects and agreements the developer owns; the execute, start-construction, and escrow-posting actions compare the caller's `X-User-ID` against that stored owner. When `X-User-Role` is `UtilityReviewer`, `X-User-ID` is an opaque identifier; the server records it as `availability_reviewer_id` on an application at the moment that reviewer files the availability determination, so that the separation-of-duties check at approval can compare it to the approver. When `X-User-Role` is `UtilityAdmin`, `X-User-ID` is an opaque administrative identifier that the server may log but does not compare against any resource's primary key.

The fifth role, `FieldInspector`, carries an **entity-backed** identity: when `X-User-Role` is `FieldInspector`, `X-User-ID` is the `id` of the acting `Inspector` resource. Ownership checks on inspection field work compare the inspection's `inspector_id` to `X-User-ID`; for example, starting a scheduled inspection is permitted only when the acting inspector is the assigned `inspector_id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are ordered by the resource's `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object.

### 2.4. Common Resource Properties and Versioning

Every primary resource is minted with a server-generated `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that starts at its initial value and increments by one on each mutation. These `version` counters are the substrate for optimistic concurrency (see §2.6) and for the cascade bookkeeping described in §2.7. Every lifecycle-bearing resource exposes its current lifecycle state in a `status` field, whose permitted values are enumerated per resource in §3.

One resource is deliberately lighter: an `EscrowTransaction` is an append-only ledger entry that is immutable once written. It carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because it is never modified after creation. Whenever a derived balance or computed field on a resource changes as a side effect of some action — for instance, the escrow balances on a developer agreement, or the recovery-pool figures on a main-extension project — that change is a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented accordingly.

### 2.5. Monetary Values, Precision, and Rounding

All money in the system is expressed in integer **cents**; there are no fractional-cent values stored or returned. Where a calculation multiplies a cents amount by a ratio or a fraction (a use multiplier, an administrative-fee percentage, a discount percentage, or a proration factor), the result is converted back to an integer number of cents using the **round-half-up** convention — a value exactly halfway between two integers rounds up to the larger magnitude. Each formula below states precisely where rounding is applied; in particular, the capacity fee and the latecomer share each round exactly once, at the single final step, whereas the total-fees calculation rounds at two distinct steps (the administrative fee, then the volume discount). Pure aggregations of already-integer cents — escrow balances and the reimbursement pool — are exact and involve no rounding.

### 2.6. Optimistic Concurrency Control

Two write paths touch a shared, conserved money balance on a parent resource, and both are guarded by optimistic concurrency to prevent a client from acting on a stale view of that balance.

The first guard protects escrow ledger postings. A request that appends an escrow transaction must include `expected_developer_agreement_version` carrying the client's last-observed `version` of the target `DeveloperAgreement`. If that value does not equal the agreement's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because every legitimate deposit or drawdown that changed the held balance advances the agreement's `version`, a mismatch means another writer has already moved the escrow balance and the caller's view of `escrow_held_cents` is stale; the caller must re-read the agreement before retrying.

The second guard protects latecomer assessments. A request that creates a latecomer reimbursement must include `expected_main_extension_project_version` carrying the client's last-observed `version` of the target `MainExtensionProject`. If that value does not equal the project's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because every prior assessment that drew from the recovery pool advances the project's `version`, a mismatch means the caller's view of `outstanding_recoverable_cents` is stale and the new share must be recomputed against a fresh read before retrying.

These are the only two endpoints that accept a version field. No other endpoint takes an expected-version input, and none applies an optimistic-concurrency check.

### 2.7. Cascading State Reconciliation

Several actions transition more than one resource. When a resource crosses a state boundary that logically determines the state of another resource, the server performs the dependent transition automatically, without a separate client request, and each automatically transitioned resource independently has its `updated_at` refreshed and its `version` incremented.

Three cascade chains are central to the system. First, when a developer agreement is executed, the main-extension project it references is automatically advanced from `PROPOSED` to `APPROVED_TO_CONSTRUCT`. Second, when a main-extension project is accepted, the accepting action sets the project's actual cost and recovery-pool figures and then auto-advances the project's still-`EXECUTED` developer agreement to `COMPLETION_PENDING`; that agreement transition in turn flips the referenced application's availability determination so that both `water_main_available` and `sewer_main_available` become true and `extension_required` becomes false — the extension has, in effect, made service available. Third, when a meter-set inspection passes, the application's meter set is advanced from `SET` to `INSTALLED`, and that meter set reaching `INSTALLED` bubbles the application up from `APPROVED` to `READY_FOR_ACTIVATION`. A backflow inspection passing certifies the assembly, and a backflow inspection failing marks the assembly failed; these are detailed in §3.

### 2.8. Path and Reference Validation

For any endpoint whose URL contains a resource identifier, the server validates that identifier before doing any business work: a path id that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), evaluated left to right so that the first unresolved identifier in the path is the one reported. The same not-found treatment applies to foreign-key references supplied in a request body — for example, an `application_id`, `inspector_id`, `crew_id`, `main_extension_project_id`, `benefiting_application_id`, `developer_agreement_id`, or `main_extension_project_id` that does not correspond to an existing resource is rejected with `ERR_NOT_FOUND`.

### 2.9. Segregation of Duties

Approval of a connection application is a four-eyes control. The reviewer who recorded the availability determination for an application — captured as `availability_reviewer_id` — may not be the same reviewer who approves that application. If the approving reviewer's `X-User-ID` equals the stored `availability_reviewer_id`, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Validation Ordering and Error Precedence

When several checks apply to one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first, then authorization against the access matrix (`ERR_UNAUTHORIZED`, 403), then existence of path resources and body foreign keys (`ERR_NOT_FOUND`, 404). For the two application endpoints that consume a meter size — submission and approval — the requested `meter_size` must correspond to an existing meter-size schedule row, and a missing row yields `ERR_METER_SIZE_UNKNOWN` (HTTP 422); this check precedes the state check. Next comes the state-legality check (`ERR_INVALID_STATE`, HTTP 409), confirming the target resource is in a state from which the requested transition is allowed. Business-specific guards — separation of duties, referential prerequisites, safety prerequisites, temporal window checks, resource-availability overlap checks, and fiscal checks — follow, each described alongside the workflow it guards. A generic body-shape check (`ERR_VALIDATION`, HTTP 400), which confirms that required fields are present and that enum and numeric values are well-formed, is the lowest-precedence guard and is applied last.

## 3. Business Logic & Workflows

### 3.1. Configuring Schedules, Rate Cards, Inspectors, and Crews

Before any application can be priced, a `UtilityAdmin` establishes the reference data. A **meter-size schedule** row maps a nominal meter size to two things: an `eru_factor`, the AWWA hydraulic-capacity ratio expressed in Equivalent Residential Units, and a `tap_install_fee_cents`, the flat labor-and-materials tap fee for that size. The `meter_size` key must be one of `FIVE_EIGHTH`, `THREE_QUARTER`, `ONE`, `ONE_AND_HALF`, or `TWO`, and it is unique across schedule rows; the `eru_factor` must be greater than zero and the `tap_install_fee_cents` at least zero.

A **fee schedule** is the governing rate card. Assessment always uses the most recently created rate card whose `is_active` flag is true (`is_active` defaults to true when omitted). A rate card carries the per-ERU capacity fees `water_capacity_fee_per_eru_cents` and `sewer_capacity_fee_per_eru_cents` (each at least zero); a `use_multipliers` object keyed by use classification; an `admin_fee_pct` administrative-fee fraction and its `admin_fee_cap_cents` ceiling; a `volume_discount_threshold_cents` and its `volume_discount_pct`; and a `pavement_cut_surcharge_cents` applied when a tap requires cutting pavement. A representative governing card sets the water capacity fee to 400000 cents (that is, $4,000.00) per ERU and the sewer capacity fee to 500000 cents ($5,000.00) per ERU; multipliers of 1.00 for `RESIDENTIAL`, 1.15 for `COMMERCIAL`, and 1.30 for `IRRIGATION`; an administrative fee of 0.03 (three percent) capped at 50000 cents ($500.00); a volume-discount threshold of 2000000 cents ($20,000.00) with a discount of 0.05 (five percent); and a pavement-cut surcharge of 80000 cents ($800.00).

The admin also registers field resources. An `Inspector` has a display `name` and an `active` flag (defaulting to true) governing whether the inspector may take new inspections; a `MeterCrew` likewise has a `name` and an `active` flag for new appointments. All of these configuration collections are readable by the operational roles, while creation of schedules, rate cards, inspectors, and crews is reserved to the `UtilityAdmin`.

### 3.2. The Connection Application: Intake and Review

An `Applicant` opens the process by creating a **connection application**, which begins in `DRAFT`. Creation captures the `parcel_id` (the assessor parcel number), the `service_type` — one of `WATER`, `SEWER`, or `BOTH` — the requested `meter_size`, and the `use_type`, one of `RESIDENTIAL`, `COMMERCIAL`, or `IRRIGATION`. Two optional flags shape the eventual fee: `requires_pavement_cut` (defaulting to false) records whether the tap will cut pavement, and the pair `prior_credit_eru` (defaulting to 0, and at least zero) and `assessment_basis` (defaulting to `NEW`, otherwise `REDEVELOPMENT`) control the redevelopment credit described in §3.4. The server stamps `applicant_user_id` from the caller's `X-User-ID`; the applicant does not supply it.

Submitting an application moves it from `DRAFT` to `SUBMITTED`. Submission requires that `parcel_id`, `service_type`, `meter_size`, and `use_type` all be present and that the `meter_size` match an existing meter-size schedule row (otherwise `ERR_METER_SIZE_UNKNOWN`). The same submit action also serves the revision loop: an application sitting in `REVISION_REQUESTED` returns to `SUBMITTED` through the same transition, so an applicant may cycle through corrections as many times as review demands.

A `UtilityReviewer` picks up a `SUBMITTED` application and begins review, moving it to `UNDER_REVIEW`. From there the reviewer has three exits. They may send it back, transitioning `UNDER_REVIEW → REVISION_REQUESTED` (optionally attaching a `reason`); they may deny it, transitioning `UNDER_REVIEW → DENIED` (again optionally with a `reason`), a terminal outcome; or they may approve it, transitioning `UNDER_REVIEW → APPROVED`. Approval is the most heavily guarded transition in the system and is detailed in §3.4. At any point up to and including approval, an `Applicant` may withdraw the application — the withdraw action is allowed from `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`, and drives the application to the terminal `WITHDRAWN` state.

### 3.3. Availability, Main Extensions, Developer Agreements, and Escrow

Whether an application can be approved at all hinges on **availability**. A `UtilityReviewer` records an **availability determination** for an application by supplying the `application_id` and the `distance_to_main_ft`, the distance in feet from the parcel connection point to the nearest usable public main (at least zero). Recording the determination also stamps that reviewer's `X-User-ID` onto the application as `availability_reviewer_id`, arming the separation-of-duties control. The determination computes three booleans. Treating the application as needing water when its `service_type` is `WATER` or `BOTH`, and as needing sewer when its `service_type` is `SEWER` or `BOTH`: `water_main_available` is true when water is needed and `distance_to_main_ft` is at most the maximum connection distance of 200 feet; `sewer_main_available` is true when sewer is needed and the distance is at most 200 feet. A distance of exactly 200 feet counts as available. `extension_required` is true when a needed water main is unavailable or a needed sewer main is unavailable.

When service is not available at the parcel, a developer builds a **main-extension project** to reach it — and that same project becomes the reimbursement pool for future latecomers. A `Developer` or `UtilityReviewer` proposes a project, which starts in `PROPOSED`, by supplying the `application_id`, the `developer_user_id` who will own it, the `length_ft` of main to be built (greater than zero), the `estimated_cost_cents` engineer's estimate (at least zero), the total benefiting `total_assessable_front_ft` and `total_assessable_area_sqft` (each greater than zero, and each the denominator for one of the two latecomer methods), and the `reimbursement_cap_cents` contractual ceiling on recoverable principal (at least zero).

Construction is guaranteed by a **developer agreement**, which a `UtilityAdmin` creates in `DRAFT` by supplying the `main_extension_project_id` and the `developer_user_id`. The admin then offers the agreement, transitioning `DRAFT → PENDING_ESCROW`, which requires the referenced project to be `PROPOSED` and sets `required_escrow_cents` equal to the project's `estimated_cost_cents`. The developer funds the agreement by appending escrow ledger entries and then executes it: the execute action transitions `PENDING_ESCROW → EXECUTED`, and is permitted only when the acting developer owns the agreement and `escrow_held_cents` is at least `required_escrow_cents` (otherwise `ERR_ESCROW_INSUFFICIENT`, HTTP 422). Execution cascades the referenced project from `PROPOSED` to `APPROVED_TO_CONSTRUCT`.

Each **escrow transaction** is an immutable ledger entry against an agreement, carrying the `developer_agreement_id`, a `txn_type` of `DEPOSIT`, `DRAWDOWN`, or `REFUND`, a positive `amount_cents`, and an optional free-text `memo` (defaulting to empty). Postings are made by the owning `Developer`. A `DEPOSIT` or `DRAWDOWN` may be posted only while the agreement is in `PENDING_ESCROW` or `EXECUTED`, and every posting must carry `expected_developer_agreement_version` matching the agreement's current `version` per §2.6 (a mismatch yields `ERR_STALE_VERSION`). A `DRAWDOWN` is further constrained: its `amount_cents` may not exceed the current `escrow_held_cents`, or the posting is rejected with `ERR_ESCROW_INSUFFICIENT`. From the full ledger the server derives four balances on the agreement: `escrow_deposited_cents` is the sum of `amount_cents` over `DEPOSIT` entries, `escrow_drawn_cents` the sum over `DRAWDOWN` entries, `escrow_refunded_cents` the sum over `REFUND` entries, and `escrow_held_cents` equals deposited minus drawn minus refunded. This holds the conservation invariant that deposited always equals held plus drawn plus refunded. Each posting recomputes those balances and increments the agreement's `version` by one.

The developer agreement's later life is driven by cascades and admin actions. When the project it guarantees is accepted (see §3.8), the agreement auto-advances from `EXECUTED` to `COMPLETION_PENDING`. The admin then closes it, transitioning `COMPLETION_PENDING → CLOSED`; closing appends a `REFUND` escrow transaction for exactly the remaining `escrow_held_cents`, so that the held balance becomes zero while conservation is preserved. Alternatively, an unexecuted agreement — one still in `DRAFT` or `PENDING_ESCROW` — may be terminated by the admin to the terminal `TERMINATED` state; if any `escrow_held_cents` remains at termination, a `REFUND` transaction for that held balance is appended.

A main-extension project itself progresses through construction under the developer's and inspectors' hands. Once `APPROVED_TO_CONSTRUCT`, the owning `Developer` starts construction, transitioning it to `UNDER_CONSTRUCTION`. A `FieldInspector` records the passing construction inspection, moving it `UNDER_CONSTRUCTION → INSPECTED`. Finally a `UtilityReviewer` accepts it (see §3.8). A project that has not yet begun construction — one in `PROPOSED` or `APPROVED_TO_CONSTRUCT` — may instead be cancelled by a `UtilityReviewer` to the terminal `CANCELLED` state.

### 3.4. Fee Assessment at Approval

Approving an application is where pricing happens, and its preconditions are checked in a fixed order after the standard authentication, authorization, and existence checks. Because approval consumes the `meter_size`, an unknown meter size surfaces first as `ERR_METER_SIZE_UNKNOWN`. The application must be `UNDER_REVIEW`, or the transition is rejected with `ERR_INVALID_STATE`. The separation-of-duties control is then applied: the approving reviewer's `X-User-ID` must differ from `availability_reviewer_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. Next, an availability determination must exist for the application, or approval fails with `ERR_DETERMINATION_MISSING` (HTTP 422). Finally, service must actually be available: for every requested utility the corresponding availability boolean must be true, unless a developer agreement in `EXECUTED`, `COMPLETION_PENDING`, or `CLOSED` state covers a main-extension project for this application. If neither condition holds, approval is rejected with `ERR_SERVICE_UNAVAILABLE` (HTTP 422).

When all guards pass, the server assesses three amounts, in order, and stamps them onto the application.

The **capacity fee** is computed first. The base capacity is the `eru_factor` of the meter-size schedule row matching the application's `meter_size`. Under the `NEW` basis, the net capacity equals that base factor in full. Under the `REDEVELOPMENT` basis, the net capacity is the base factor reduced by the application's `prior_credit_eru`, but never below zero — the credit for a prior or abandoned connection cannot produce a negative charge. The governing rate card's `water_capacity_fee_per_eru_cents` is multiplied by the net capacity to give the water component, counted only when the `service_type` is `WATER` or `BOTH` and otherwise zero; the `sewer_capacity_fee_per_eru_cents` is multiplied by the net capacity to give the sewer component, counted only when the `service_type` is `SEWER` or `BOTH` and otherwise zero. The two components are summed and multiplied by the use multiplier drawn from `use_multipliers` for the application's `use_type`. That single product is rounded half up to whole cents and stored as `capacity_fee_cents`.

The **tap installation fee** is computed next. It is the `tap_install_fee_cents` of the meter-size schedule row for the application's `meter_size`, plus the rate card's `pavement_cut_surcharge_cents` when `requires_pavement_cut` is true, and only the schedule fee otherwise. The result is stored as `tap_fee_cents`.

The **total fees due** is computed last, from the two amounts just derived and the governing rate card, in a fixed order because the discount depends on a gross that itself depends on the administrative fee. The subtotal is `capacity_fee_cents` plus `tap_fee_cents`. The administrative fee is the subtotal multiplied by `admin_fee_pct`, rounded half up to whole cents, then capped so it never exceeds `admin_fee_cap_cents` — the smaller of the rounded fee and the cap. The gross is the subtotal plus the administrative fee. A volume discount applies only when the gross is at least `volume_discount_threshold_cents`: in that case the discount is the gross multiplied by `volume_discount_pct`, rounded half up to whole cents; otherwise the discount is zero. The total is the gross minus the discount, stored as `total_fees_due_cents`.

Approval also determines the backflow requirement. The server computes `backflow_required` as true exactly when the `use_type` is `COMMERCIAL` or `IRRIGATION`. When `backflow_required` is true, approval creates a `BackflowAssembly` for the application in the `REQUIRED` state.

### 3.5. Inspections and the Meter Set

Field verification runs on two booking calendars — inspectors and crews — each with its own conflict rule.

An **inspection** is requested for an application by an `Applicant`, `FieldInspector`, or `UtilityReviewer`, supplying the `application_id`, the `inspector_id`, an `inspection_type` of `TAP`, `METER_SET`, or `BACKFLOW`, and the `scheduled_start` and `scheduled_end` window in ISO 8601 UTC. It begins in `REQUESTED`. A `FieldInspector` schedules it, transitioning `REQUESTED → SCHEDULED`; the same schedule action also serves the reinspection loop, taking a `FAILED` inspection back to `SCHEDULED`. A schedule request may restate `scheduled_start` and `scheduled_end`. Scheduling requires the window end to be strictly after the window start, or the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422). It further requires that the window not overlap any other `SCHEDULED` or `IN_PROGRESS` inspection on the same `inspector_id`; overlap is evaluated on half-open intervals, meaning two windows conflict only when the new start is strictly before an existing end and the new end is strictly after an existing start — so windows that merely touch end-to-start do not conflict. A conflict is rejected with `ERR_INSPECTOR_UNAVAILABLE` (HTTP 409).

Once scheduled, the assigned inspector starts the inspection, transitioning `SCHEDULED → IN_PROGRESS` (permitted only when the acting `FieldInspector` is the assigned `inspector_id`), and then either passes it (`IN_PROGRESS → PASSED`) or fails it (`IN_PROGRESS → FAILED`). A requested or scheduled inspection may instead be cancelled by a `FieldInspector` to the terminal `CANCELLED` state, releasing the inspector's window.

Passing an inspection cascades according to its type. A `METER_SET` inspection passing advances the application's meter set from `SET` to `INSTALLED`, which in turn bubbles the application from `APPROVED` to `READY_FOR_ACTIVATION`. A `BACKFLOW` inspection passing certifies the application's installed backflow assembly (§3.6). Failing a `BACKFLOW` inspection, when the assembly is `INSTALLED`, drives that assembly to `FAILED`.

The **meter set** is the physical meter installation, created for an application by an `Applicant` or `FieldInspector` with the `application_id`, the `crew_id`, and the `appointment_start` and `appointment_end` window; it begins in `PENDING`. A `FieldInspector` schedules it, transitioning `PENDING → SCHEDULED`, and may restate `appointment_start` and `appointment_end`. Scheduling requires the appointment end to be strictly after the appointment start (otherwise `ERR_INVALID_WINDOW`). Crew conflicts use a closed interval plus a buffer of 60 minutes (one hour): the new appointment conflicts with any `SCHEDULED` or `SET` appointment on the same `crew_id` unless the two are separated by at least that buffer — concretely, a conflict exists when the new start is before the existing end extended by the buffer and the new end extended by the buffer is after the existing start. A conflict is rejected with `ERR_CREW_UNAVAILABLE` (HTTP 409).

A scheduled meter set is installed by a `FieldInspector` via the complete-install action, transitioning `SCHEDULED → SET`. This action requires that the application's `TAP` inspection be `PASSED`, or it is rejected with `ERR_INSPECTION_NOT_PASSED` (HTTP 422); it additionally requires that, when the application's backflow is required, the backflow assembly not be in the `FAILED` state. Once `SET`, the meter set is carried to `INSTALLED` by the passing `METER_SET` inspection cascade described above. A `UtilityAdmin` may later remove an installed meter, transitioning `INSTALLED → REMOVED`.

### 3.6. Backflow Prevention

A backflow assembly exists only for applications whose use classification demands it — the `COMMERCIAL` and `IRRIGATION` uses that set `backflow_required` at approval. The assembly is created by the approval side effect in the `REQUIRED` state, carrying the `application_id` and a `serial_number` (defaulting to empty until installation).

An `Applicant` records installation, transitioning `REQUIRED → INSTALLED` and setting the supplied `serial_number` (installation requires a `serial_number` to be provided). The same install action also serves the repair-and-reinstall loop, taking a `FAILED` assembly back to `INSTALLED`. Certification is not a direct action: it arrives as the cascade from a passing `BACKFLOW` inspection, which advances the assembly from `INSTALLED` to the terminal `CERTIFIED` state; conversely a failing `BACKFLOW` inspection drives an `INSTALLED` assembly to `FAILED`. Certification matters at activation, described next.

### 3.7. Payment, Activation, and the Service Account

Fees are collected incrementally. An `Applicant` records a payment toward the amount owed via the pay-fees action, supplying `amount_cents`; each payment adds to the running `fees_paid_cents`, which starts at zero.

Activation is the final step of the application lifecycle and is performed by the `Applicant`. It transitions `READY_FOR_ACTIVATION → ACTIVATED`, and its guards are checked in order: the application must be `READY_FOR_ACTIVATION`; when `backflow_required` is true, the backflow assembly must be `CERTIFIED`, or activation is rejected with `ERR_BACKFLOW_NOT_CERTIFIED` (HTTP 422); and `fees_paid_cents` must be at least `total_fees_due_cents`, or activation is rejected with `ERR_FEES_UNPAID` (HTTP 402). On success, activation creates a **service account** for the application in the `ACTIVE` state, with a system-generated `account_number`, carrying the `application_id`.

A service account has its own small lifecycle managed by a `UtilityAdmin`. An `ACTIVE` account may be suspended (`ACTIVE → SUSPENDED`) and a `SUSPENDED` account reinstated (`SUSPENDED → ACTIVE`); an account that is either `ACTIVE` or `SUSPENDED` may be closed to the terminal `CLOSED` state.

### 3.8. Acceptance and Latecomer Reimbursement

Accepting a completed main-extension project both closes out the construction guarantee and opens the reimbursement pool. A `UtilityReviewer` accepts a project that is `INSTALLED`-complete — that is, in the `INSPECTED` state — by supplying the `actual_construction_cost_cents`, transitioning `INSPECTED → ACCEPTED`. Acceptance records the actual cost and establishes the pool: `reimbursable_principal_cents` is set to the smaller of `actual_construction_cost_cents` and `reimbursement_cap_cents`; `reimbursed_collected_cents` is set to zero; and `outstanding_recoverable_cents` is set equal to the reimbursable principal. Acceptance then cascades: the project's `EXECUTED` developer agreement advances to `COMPLETION_PENDING`, and that in turn flips the application's availability determination to show both mains available and no extension required, as described in §2.7. Throughout the pool's life, the conservation invariant holds that the reimbursable principal always equals the collected amount plus the outstanding recoverable amount.

A **latecomer reimbursement** recovers a fair share of that principal from a new connection that benefits from the extension. A `UtilityAdmin` assesses one, which begins in `ASSESSED`, by supplying the `main_extension_project_id`, the `benefiting_application_id`, the allocation `method` (`FRONT_FOOTAGE` or `AREA`), the benefiting parcel's `parcel_front_ft` and `parcel_area_sqft` (each at least zero), and the `expected_main_extension_project_version` that the optimistic-concurrency guard checks against the project's current `version` (mismatch yields `ERR_STALE_VERSION`). The referenced project must be `ACCEPTED` with its reimbursable principal set, or the assessment is rejected with `ERR_PROJECT_NOT_ACCEPTED` (HTTP 422).

The assessed `amount_cents` is a proration of the project's `reimbursable_principal_cents`. Under the `FRONT_FOOTAGE` method, the share is the principal multiplied by the benefiting `parcel_front_ft` divided by the project's `total_assessable_front_ft`. Under the `AREA` method, the share is the principal multiplied by the benefiting `parcel_area_sqft` divided by the project's `total_assessable_area_sqft`. In either case the share is rounded half up to whole cents in a single final step, and — because the two methods use different numerators and denominators — the same principal generally yields different shares under the two methods. The computed share may not exceed the project's current `outstanding_recoverable_cents`; if it would, the assessment is rejected with `ERR_REIMBURSEMENT_EXCEEDED` (HTTP 422). Creating the assessment increments the project's `version` by one.

A `UtilityAdmin` resolves an assessed reimbursement one of two ways. Collecting it transitions `ASSESSED → COLLECTED`, and updates the project pool: the collected `amount_cents` is added to `reimbursed_collected_cents` and subtracted from `outstanding_recoverable_cents`, preserving the pool conservation invariant. Waiving it (optionally with a `reason`) transitions `ASSESSED → WAIVED` and does not touch the pool.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource — including the state-transition actions — return `200 OK`. Every endpoint requires the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/meter-size-schedules` | Create a meter-size → ERU factor + tap fee row | UtilityAdmin |
| GET | `/meter-size-schedules` | List meter-size schedule rows | UtilityAdmin, UtilityReviewer, Applicant, Developer, FieldInspector |
| POST | `/fee-schedules` | Create a rate card | UtilityAdmin |
| GET | `/fee-schedules` | List rate cards | UtilityAdmin, UtilityReviewer |
| POST | `/inspectors` | Create a field inspector | UtilityAdmin |
| GET | `/inspectors` | List inspectors | UtilityAdmin, FieldInspector, UtilityReviewer |
| POST | `/meter-crews` | Create a meter-set crew | UtilityAdmin |
| GET | `/meter-crews` | List meter crews | UtilityAdmin, FieldInspector |
| POST | `/connection-applications` | Create a connection application in DRAFT | Applicant |
| GET | `/connection-applications` | List connection applications | Applicant, UtilityReviewer, UtilityAdmin |
| GET | `/connection-applications/{id}` | Fetch one application | Applicant, UtilityReviewer, UtilityAdmin |
| POST | `/connection-applications/{id}/submit` | Submit a DRAFT/REVISION_REQUESTED application | Applicant |
| POST | `/connection-applications/{id}/start-review` | Begin review | UtilityReviewer |
| POST | `/connection-applications/{id}/request-revision` | Send an application back for revision | UtilityReviewer |
| POST | `/connection-applications/{id}/approve` | Approve; assess fees; create backflow requirement | UtilityReviewer |
| POST | `/connection-applications/{id}/deny` | Deny an application under review | UtilityReviewer |
| POST | `/connection-applications/{id}/pay-fees` | Record a payment toward fees due | Applicant |
| POST | `/connection-applications/{id}/activate` | Activate a ready application; create the service account | Applicant |
| POST | `/connection-applications/{id}/withdraw` | Withdraw an application before activation | Applicant |
| POST | `/availability-determinations` | Record an availability finding; set availability reviewer | UtilityReviewer |
| GET | `/availability-determinations` | List availability determinations | UtilityReviewer, UtilityAdmin, Applicant |
| GET | `/availability-determinations/{id}` | Fetch one availability determination | UtilityReviewer, UtilityAdmin, Applicant |
| POST | `/main-extension-projects` | Propose a main-extension project | Developer, UtilityReviewer |
| GET | `/main-extension-projects` | List main-extension projects | Developer, UtilityReviewer, UtilityAdmin |
| GET | `/main-extension-projects/{id}` | Fetch one main-extension project | Developer, UtilityReviewer, UtilityAdmin |
| POST | `/main-extension-projects/{id}/start-construction` | Developer begins construction | Developer |
| POST | `/main-extension-projects/{id}/record-inspection` | Record a passing construction inspection | FieldInspector |
| POST | `/main-extension-projects/{id}/accept` | Accept the completed extension; set pool; cascade | UtilityReviewer |
| POST | `/main-extension-projects/{id}/cancel` | Cancel a project not yet under construction | UtilityReviewer |
| POST | `/developer-agreements` | Create a developer agreement in DRAFT | UtilityAdmin |
| GET | `/developer-agreements` | List developer agreements | UtilityAdmin, Developer |
| GET | `/developer-agreements/{id}` | Fetch one developer agreement | UtilityAdmin, Developer |
| POST | `/developer-agreements/{id}/offer` | Offer the agreement; set required escrow | UtilityAdmin |
| POST | `/developer-agreements/{id}/execute` | Execute once escrow funded; cascade project | Developer |
| POST | `/developer-agreements/{id}/escrow-transactions` | Append an escrow ledger entry (OCC-guarded) | Developer |
| GET | `/developer-agreements/{id}/escrow-transactions` | List escrow ledger entries | UtilityAdmin, Developer |
| POST | `/developer-agreements/{id}/close` | Close a completed agreement; refund remaining escrow | UtilityAdmin |
| POST | `/developer-agreements/{id}/terminate` | Terminate an unexecuted agreement; refund escrow | UtilityAdmin |
| POST | `/inspections` | Request an inspection for an application | Applicant, FieldInspector, UtilityReviewer |
| GET | `/inspections` | List inspections | Applicant, FieldInspector, UtilityReviewer, UtilityAdmin |
| GET | `/inspections/{id}` | Fetch one inspection | Applicant, FieldInspector, UtilityReviewer, UtilityAdmin |
| POST | `/inspections/{id}/schedule` | Schedule/reschedule an inspection (overlap-checked) | FieldInspector |
| POST | `/inspections/{id}/start` | Start a scheduled inspection | FieldInspector |
| POST | `/inspections/{id}/pass` | Mark an inspection passed; cascade per type | FieldInspector |
| POST | `/inspections/{id}/fail` | Mark an inspection failed | FieldInspector |
| POST | `/inspections/{id}/cancel` | Cancel a requested/scheduled inspection | FieldInspector |
| POST | `/meter-sets` | Create a meter-set record for an application | Applicant, FieldInspector |
| GET | `/meter-sets` | List meter-sets | Applicant, FieldInspector, UtilityAdmin |
| GET | `/meter-sets/{id}` | Fetch one meter-set | Applicant, FieldInspector, UtilityAdmin |
| POST | `/meter-sets/{id}/schedule` | Book a crew appointment window (buffer-checked) | FieldInspector |
| POST | `/meter-sets/{id}/complete-install` | Crew completes the physical install | FieldInspector |
| POST | `/meter-sets/{id}/remove` | Remove an installed meter | UtilityAdmin |
| GET | `/backflow-assemblies` | List backflow assemblies | Applicant, FieldInspector, UtilityReviewer, UtilityAdmin |
| GET | `/backflow-assemblies/{id}` | Fetch one backflow assembly | Applicant, FieldInspector, UtilityReviewer, UtilityAdmin |
| POST | `/backflow-assemblies/{id}/install` | Record install (or reinstall after failure) | Applicant |
| GET | `/service-accounts` | List service accounts | Applicant, UtilityAdmin |
| GET | `/service-accounts/{id}` | Fetch one service account | Applicant, UtilityAdmin |
| POST | `/service-accounts/{id}/suspend` | Suspend an active account | UtilityAdmin |
| POST | `/service-accounts/{id}/reinstate` | Reinstate a suspended account | UtilityAdmin |
| POST | `/service-accounts/{id}/close` | Close an account | UtilityAdmin |
| POST | `/latecomer-reimbursements` | Assess a latecomer share (OCC-guarded) | UtilityAdmin |
| GET | `/latecomer-reimbursements` | List latecomer reimbursements | UtilityAdmin, Developer |
| GET | `/latecomer-reimbursements/{id}` | Fetch one latecomer reimbursement | UtilityAdmin, Developer |
| POST | `/latecomer-reimbursements/{id}/collect` | Record collection; update the project pool | UtilityAdmin |
| POST | `/latecomer-reimbursements/{id}/waive` | Waive an assessed reimbursement | UtilityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_METER_SIZE_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DETERMINATION_MISSING` | 422 Unprocessable Entity |
| `ERR_SERVICE_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_INSPECTION_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_BACKFLOW_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_INSPECTOR_UNAVAILABLE` | 409 Conflict |
| `ERR_CREW_UNAVAILABLE` | 409 Conflict |
| `ERR_ESCROW_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FEES_UNPAID` | 402 Payment Required |
| `ERR_REIMBURSEMENT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROJECT_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |

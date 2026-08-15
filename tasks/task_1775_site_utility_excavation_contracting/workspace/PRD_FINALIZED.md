# Site Utility & Excavation Contracting API — Product Requirements Document

## 1. Introduction

Site utility and excavation contracting is a discipline of serialized dependencies: before a bucket ever touches soil, the crew needs a lawful one-call locate, verified pothole exposures at every crossing, and an approved trench safety plan matched to the soil classification and depth of the cut. Once pipe is in the ground, the work passes through installation inspection, lift-by-lift backfill compaction testing, a tie-in shutdown negotiated with the utility owner under strict notice and duration limits, dewatering discharge compliance, and finally an as-built survey that the utility owner must accept. At any moment, an unforeseen condition — rock, groundwater, contaminated soil, a conflicting utility, a void — can stop the job outright and spawn a change order drawn against the owner's contingency pool.

This document specifies an API that orchestrates that entire workflow for a site utility contractor. The system exists because the current patchwork of phone calls, whiteboard schedules, and spreadsheets cannot enforce the controls regulators and owners demand: segregation of duties between the field and the reviewer, a ledger of committed shutdown hours per utility owner, provable compaction coverage per backfill lift, and a fiscal trail that keeps change-order spending inside its caps. Every mutation the system accepts — whether driven by a user action or by the logical clock — is captured in a per-project audit trail, and time-driven lifecycle events (ticket expiry, permit activation, missed shutdown windows) are evaluated deterministically so that compliance behavior is reproducible. All resources are exposed under a single mount point rooted at `/site-utility`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request carries `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. The system recognizes exactly six roles: `OpsAdmin`, `ProjectManager`, `Foreman`, `SafetyOfficer`, `Inspector`, and `UtilityOwnerRep`. A request that is missing either header, or whose role header does not name one of these six roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the attempted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity semantics differ by role. When `X-User-Role` is `UtilityOwnerRep`, `X-User-ID` is the `id` of the acting `UtilityOwner`; ownership checks on any resource that references a `UtilityOwner` compare the resource's `utility_owner_id` field to `X-User-ID`. This is how the system decides which representative may confirm a shutdown window, accept an as-built package, or approve a large change order. When `X-User-Role` is `OpsAdmin`, `ProjectManager`, `Foreman`, `SafetyOfficer`, or `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` on a trench safety plan, as `recorded_by_user_id` on an installation inspection or compaction test, or as `actor_user_id` on an audit event — but it never compares such a value to any entity's `id`.

Segregation of duties is enforced wherever one user submits or records and another reviews: the reviewer's `X-User-ID` must differ from the identifier captured at submission or recording time, and a violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403). All six roles may call every read endpoint; the write surface of each role is enumerated in §4.

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

List endpoints paginate through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and it must lie between 1 and 100 inclusive. `offset` skips a number of items from the front of the result set and defaults to 0. Unless a specific list documents a different ordering, list endpoints return resources sorted by `created_at` in ascending order; resources that share the same `created_at` — common under the logical clock, which moves only when advanced — keep the order in which they were created. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`. Beyond pagination, each list accepts the resource-specific filter parameters named in §3; every read endpoint is open to all six roles.

### 2.4. Resource Identity, Timestamps, and the Audit Trail

Every resource in the system except the audit log carries a standard set of system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. `version` is an integer that starts at 1 when the resource is created and increments by one on every mutation. Mutations include user-driven actions, system-driven state transitions, and recomputations of derived fields — so when a project's `approved_co_total_cents` changes because a change order was approved, the project's `updated_at` refreshes and its `version` increments even though no client wrote to the project directly.

The audit log is the one exception. An audit event carries only `id` and `created_at` from the common set; it has no `updated_at` and no `version`, because it is immutable once written. Each audit event records the `project_id` scoping the mutation, the caller's `actor_role` and `actor_user_id`, the `action` performed (the HTTP method and path template of the mutation), the `entity_type` and `entity_id` of the mutated resource, and a human-readable `detail` summarizing what changed (for example, "status DRAFT→SUBMITTED"). Every successful mutation in the system — user action or system transition — appends one audit event per mutated resource, and a project's full audit history is retrievable in chronological order as described in §3.1.

### 2.5. The Logical Clock and Time-Driven Transitions

Time inside this system is logical, not wall-clock. Before any client interaction the server clock reads exactly 2026-08-01T00:00:00Z, and it never silently falls back to the host's wall clock. An `OpsAdmin` advances the clock through an admin-only capability that accepts a `to_iso8601` instant; the new value must be strictly greater than the current clock reading, and the response reports the new `current_utc`. Advancing the clock is how waiting periods expire, permits activate, and shutdown windows come due.

Each advance fires time-driven transitions in one pinned evaluation order, and the order matters when several events fall inside the same advance. First, locate tickets in `SUBMITTED` whose `legal_start_at` has been reached become `ACTIVE`. Second, locate tickets in `ACTIVE` — or still in `SUBMITTED` — whose `valid_until` has been reached become `EXPIRED`; because activation is evaluated before expiry within the same advance, a ticket whose entire validity window was skipped while it waited lands directly in `EXPIRED`. Third, discharge permits move: `ISSUED` becomes `ACTIVE` when the current instant falls inside the permit's effective window, and a permit in `ISSUED` or `ACTIVE` becomes `EXPIRED` once its `effective_to` has been reached. Fourth, shutdown windows move: a window still `PROPOSED` when its `window_start` passes becomes `MISSED`; a `CONFIRMED` window becomes `ACTIVE` when its start is reached while the project's work posture is `CLEAR`; and a window in `CONFIRMED` or `ACTIVE` becomes `MISSED` once its `window_end` passes. Every entity transitioned by the clock appends its own audit event.

### 2.6. Work Posture, Segment Holds, and Cascading State Propagation

A project carries a computed `work_posture` of `CLEAR` or `STOPPED`. The posture is `STOPPED` exactly when the project has at least one unforeseen condition in `OPEN` status whose `stop_work_required` flag is true; otherwise it is `CLEAR`. Posture changes cascade into the pipe segments of the project in a second hop: when a project stops, every segment in `INSTALLING` or `BACKFILLING` moves to `ON_HOLD`, with `hold_reason` set to `STOP_WORK` and `resume_status` remembering the status the segment left. When the last blocking condition leaves `OPEN`, the posture recomputes to `CLEAR`, and every segment sitting `ON_HOLD` with `hold_reason` `STOP_WORK` returns to its remembered `resume_status`; its `hold_reason` resets to `NONE` and `resume_status` clears to null.

A second, independent hold cause exists for dewatering. When a project's active discharge permit is suspended, segments that were `INSTALLING` and flagged `requires_dewatering` move to `ON_HOLD` with `hold_reason` `DEWATERING` and `resume_status` `INSTALLING`; segments already `BACKFILLING` are not held, because the pipe is already in the ground. Clearing one hold cause never resumes the other: posture returning to `CLEAR` does not touch `DEWATERING`-held segments, and permit reinstatement does not touch `STOP_WORK`-held segments. A held segment resumes to `INSTALLING` only when its `resume_status` is `INSTALLING`, and to `BACKFILLING` only when its `resume_status` is `BACKFILLING`; on every resume the `hold_reason` returns to `NONE` and `resume_status` returns to null.

### 2.7. Monetary Representation and Fiscal Caps

All monetary values are integer cents — never fractional currency units — and labor and equipment rates are expressed in cents per hour. Every rounding in a money calculation is round half up applied to a whole cent, and the pricing procedure rounds each cost line and each markup tier slice individually before summing, so that stored totals are always exact sums of rounded components (§3.8 gives the full procedure). Two fiscal caps govern change-order spending on every project: `single_co_cap_cents`, the ceiling on any one change order's provisional price, and `contingency_cents`, the owner-funded pool that the aggregate of approved change-order money must never exceed.

### 2.8. Field Measurement Units, Rounding, and Tolerance Boundaries

Field measurements mix units by convention: pothole depths and offsets are whole inches; trench depths, cover depths, and survey lengths are feet; slopes and compaction figures are percentages; discharge volumes are whole gallons; and durations are whole minutes. Computed percentages and tolerances are rounded half up before any comparison — compaction percentages to a resolution of one tenth of a percent, as-built length tolerances to one tenth of a foot, and as-built invert tolerances to one hundredth of a foot. Unless a rule says otherwise, a tolerance boundary is inclusive: a measurement landing exactly on the limit passes. The discharge compliance rules are the explicit exception family, and §3.6 states which of those boundaries are inclusive and which are strict.

### 2.9. Optimistic Concurrency Control on Project-Scoped Creates

Two creation operations — proposing a shutdown window and creating a change order — are guarded by optimistic concurrency control on the project they reference. Each such request must carry `expected_project_version`, the `version` of the project as the client last observed it; the field is not optional on these two creates. If the project's current `version` has advanced beyond the supplied value — for example because another writer has just booked a window, an operation that legitimately succeeds and bumps the project's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). For the change-order create the guard has a specific purpose: a create against a fresh project version legitimately supersedes an open change order for the same condition, and the stale-version rejection ensures that supersede never fires from an outdated view of the project. Both guarded creates increment the project's `version` by one when they succeed. No other endpoint accepts a version field; every other write proceeds without an optimistic-concurrency token.

### 2.10. Validation Order of Evaluation

When a request violates several rules, the rejection it receives is deterministic, because checks are evaluated in a fixed priority order and the earliest applicable failure wins. Authentication comes first: a missing header or an undeclared role is `ERR_UNAUTHENTICATED`. Authorization comes second: a role not permitted for the endpoint, a `UtilityOwnerRep` whose `X-User-ID` does not match the target resource's `utility_owner_id`, or a segregation-of-duties breach surfaces as `ERR_UNAUTHORIZED_ROLE` or `ERR_SOD_VIOLATION` respectively. Third, the request body itself must be well-formed — every required field present, types correct, enum values in range, numeric fields positive where required, and a proposed shutdown's duration within the owning utility's per-window cap — or the request fails with `ERR_VALIDATION`. Fourth, every identifier in the path and every foreign key referenced in the body must name an existing resource, else `ERR_NOT_FOUND`; whether an existing reference is scoped to the wrong project is deliberately deferred to a later step. Fifth, on the two project-scoped creates the `expected_project_version` must match the project's current `version`, else `ERR_STALE_VERSION`.

Sixth, the target resource must be in a valid from-state for the requested transition, and a resource in a terminal state rejects every action, else `ERR_INVALID_STATE`. Seventh come the safety and compliance gates, and they are sub-ordered: a stopped project surfaces `ERR_PROJECT_STOPPED` before any locate-ticket check; a missing or inactive locate surfaces `ERR_LOCATE_NOT_ACTIVE`; trench slope and depth noncompliance on plan submission surfaces `ERR_SLOPE_NONCOMPLIANT` or `ERR_ENGINEERED_DESIGN_REQUIRED`; and a reading taken against a non-active permit surfaces `ERR_PERMIT_NOT_ACTIVE`. Eighth come the temporal rules, also sub-ordered: a `window_start` that is not strictly in the future is `ERR_WINDOW_IN_PAST`; insufficient notice to the owner is `ERR_INSUFFICIENT_NOTICE`; overlap with the owner's existing committed windows is `ERR_OWNER_WINDOW_OVERLAP`; insufficient clearance from the project's other committed windows is `ERR_PROJECT_WINDOW_BUFFER`; and a reading timestamped outside its permit's effective window is `ERR_READING_OUTSIDE_PERMIT_WINDOW`.

Ninth come cross-entity integrity and cross-entity state gates: a body reference that resolves into a different project's scope is `ERR_CROSS_PROJECT_REFERENCE`; a missing approved trench plan is `ERR_PLAN_NOT_APPROVED`; unresolved potholes are `ERR_POTHOLES_OUTSTANDING`; a latest confirmed inspection that is not a pass is `ERR_INSPECTION_NOT_PASSED`; an as-built submitted before segment completion is `ERR_SEGMENT_NOT_COMPLETE`; a change order created, submitted, or approved against a condition that is not open for that step is `ERR_CONDITION_NOT_OPEN`; and resolving a condition while its change orders are unsettled is `ERR_CO_NOT_COMPLETED`. Tenth come aggregate and uniqueness constraints: a second open locate ticket is `ERR_DUPLICATE_OPEN_TICKET`; a duplicate live station is `ERR_DUPLICATE_STATION`; a second open as-built package is `ERR_ASBUILT_ALREADY_OPEN`; a skipped backfill lift is `ERR_LIFT_SEQUENCE`; completing a segment with lifts outstanding is `ERR_LIFTS_INCOMPLETE`; and a premature closeout is `ERR_CLOSEOUT_INCOMPLETE`. Eleventh and last come the fiscal caps: `ERR_PRICE_CAP_EXCEEDED` for a change order priced over the per-order cap and `ERR_CONTINGENCY_EXCEEDED` for an approval that would overrun the project's contingency pool.

### 2.11. Cross-Project Referential Integrity

All resources are flat peers — no resource is nested beneath another in the URL space — so every relationship is expressed as a foreign key carried in a request body, such as `project_id`, `pipe_segment_id`, `locate_ticket_id`, or `unforeseen_condition_id`. References must stay inside one project scope. A pothole verification's locate ticket must belong to the same project as the pothole; a trench safety plan's pipe segment must belong to the same project as the plan; a shutdown window's pipe segment must belong to the window's project, and the window's `utility_owner_id` must match the owner recorded on that segment; a change order's unforeseen condition must belong to the change order's project; and an unforeseen condition that names a pipe segment must name one inside its own project. Any breach is rejected with `ERR_CROSS_PROJECT_REFERENCE`. Note the interaction with §2.10: a reference that names no resource at all fails earlier with `ERR_NOT_FOUND`; `ERR_CROSS_PROJECT_REFERENCE` is reserved for references that exist but point across a project boundary.

## 3. Business Logic & Workflows

### 3.1. Establishing the Project and the Utility-Owner Registry

Work begins with the registry. An `OpsAdmin` registers each utility owner the contractor deals with, recording its `name`, its `owner_type` — one of `WATER`, `SEWER`, `GAS`, `ELECTRIC`, or `TELECOM` — and two scheduling parameters that later bind every shutdown negotiation: `min_notice_hours`, the minimum lead time before a shutdown may start, and `max_shutdown_hours`, the longest single shutdown the owner will grant. A freshly registered owner carries a `committed_shutdown_minutes` ledger balance of zero; §3.5 describes how that ledger rises and falls with window bookings.

A `ProjectManager` then creates the project itself, supplying a display `name`, the `contract_ref` job number, a `soil_class_default` of `SOIL_A`, `SOIL_B`, or `SOIL_C` as the site's default classification, and the two fiscal controls: `contingency_cents`, the owner-funded pool available for change orders, and `single_co_cap_cents`, the provisional-price ceiling on any individual change order. A new project starts in `ACTIVE` status with `work_posture` `CLEAR`, an `approved_co_total_cents` of zero, and no `closed_at` timestamp. The `approved_co_total_cents` field is a computed ledger: it carries the `provisional_price_cents` of every `APPROVED` change order plus the `final_price_cents` of every `COMPLETED` one, so the number drifts from provisional to actual as change orders settle (§3.8).

Projects can be listed with `status` and `work_posture` filters. Every mutation that touches a resource scoped to the project — including system-driven transitions — appends to the project's audit trail, and the trail is retrievable per project in `created_at` ascending order, with events that share the same `created_at` appearing in the order they were appended, optionally narrowed by `entity_type`. Closure itself is a two-step affair covered in §3.9: the project moves `ACTIVE → CLOSING → CLOSED`, and `closed_at` is stamped only at the final step.

### 3.2. Utility Locates and Pothole Verification

No ground is broken without a lawful locate. A `ProjectManager` creates a locate ticket for a project by supplying the `project_id`, the one-call center's `ticket_number`, and `legal_start_at`, the earliest instant digging becomes legal. The ticket is born `DRAFT`, with `renew_count` zero and a computed `valid_until` set exactly 672 hours — twenty-eight days — after `legal_start_at`. A project may have at most one open ticket: creation is rejected with `ERR_DUPLICATE_OPEN_TICKET` if the project already holds a ticket in `DRAFT`, `SUBMITTED`, or `ACTIVE`. Submitting moves the ticket `DRAFT → SUBMITTED` and re-checks that same exclusivity rule.

From there the clock takes over. When the clock reaches `legal_start_at`, a `SUBMITTED` ticket becomes `ACTIVE`; when it reaches `valid_until`, a ticket in `ACTIVE` — or one still waiting in `SUBMITTED` — becomes `EXPIRED`. A `ProjectManager` may renew a ticket, which extends `valid_until` by another 672 hours and increments `renew_count` by one. Renewal behaves differently depending on where the ticket stands. Renewing an `ACTIVE` ticket keeps it `ACTIVE`, unless the current time has already reached the newly extended `valid_until`, in which case it lands `EXPIRED` instead — a renewal too late to matter. Renewing an `EXPIRED` ticket returns it to `ACTIVE` only when the extended validity covers the current instant; if even the extended deadline lies in the past, the ticket stays `EXPIRED`, though `renew_count` still increments. The `ACTIVE` status is a hard gate on the work itself: performing a pothole, marking a segment ready, starting installation, and starting backfill are each rejected with `ERR_LOCATE_NOT_ACTIVE` when no active ticket covers the project.

Pothole verification proves out what the locate painted. A `ProjectManager` plans a verification at a survey station by providing the `project_id`, the `locate_ticket_id` of the ticket covering the dig area — which must belong to the same project or the create fails with `ERR_CROSS_PROJECT_REFERENCE` — plus the `station_label` (for example, STA 10+25), the `expected_utility_type` (`WATER`, `SEWER`, `GAS`, `ELECTRIC`, `TELECOM`, or `UNKNOWN`), the excavation `method` (`VACUUM` or `HAND_DIG`), and the design expectations `design_depth_in` and `design_offset_in`, both in inches. The plan starts `PLANNED`. Only one live verification may exist per station within a project: if a verification for the same `station_label` already exists in `PLANNED`, `PERFORMED`, or `VERIFIED`, the create is rejected with `ERR_DUPLICATE_STATION`. If the existing one is in `CONFLICT`, however, the new plan supersedes it, pushing the old record into `SUPERSEDED` — conflict is the only state from which a station may be re-planned.

A `Foreman` performs the exposure, recording `measured_depth_in` and `measured_offset_in`, both of which remain null until this moment. Performing requires the ticket referenced by the verification to be `ACTIVE` (`ERR_LOCATE_NOT_ACTIVE`) and the project's posture to be `CLEAR` (`ERR_PROJECT_STOPPED`), and it moves the verification `PLANNED → PERFORMED`. A `ProjectManager` then adjudicates: verification succeeds, moving `PERFORMED → VERIFIED`, when the measured depth differs from the design depth by at most 6 inches and the measured offset differs from the design offset by at most 12 inches — both boundaries inclusive — and is rejected with `ERR_POTHOLE_TOLERANCE_EXCEEDED` otherwise. Alternatively the manager may mark the finding `PERFORMED → CONFLICT` when the exposed utility is not what design expected. Pothole verifications can be listed filtered by `project_id`, `locate_ticket_id`, or `status`.

### 3.3. Trench Safety Planning and Competent-Person Review

Every pipe segment digs under a plan. A `Foreman` drafts a trench safety plan for a segment by supplying the `project_id`, the `pipe_segment_id` it covers — the segment must sit inside the same project, else `ERR_CROSS_PROJECT_REFERENCE` — the `max_depth_ft` the plan covers, the `soil_class` (`SOIL_A`, `SOIL_B`, or `SOIL_C`), and the `protective_system`: `SLOPING`, `BENCHING`, `SHORING`, or `TRENCH_BOX`. When the design relies on the ground standing on its own — `SLOPING` or `BENCHING` — a `slope_ratio` expressing the horizontal-to-vertical run must be supplied; `engineered_certification`, a registered-PE certification flag, defaults to false when omitted. A new plan is `DRAFT` at `revision` 1.

Submitting a plan, again by the `Foreman`, is where the safety arithmetic bites. For `SLOPING` or `BENCHING`, the `slope_ratio` must be present and must be at least the required ratio for the plan's soil class — 0.75 for `SOIL_A`, 1.0 for `SOIL_B`, and 1.5 for `SOIL_C` — with the boundary inclusive, so a ratio of exactly 1.5 on `SOIL_C` passes; shortfalls are rejected with `ERR_SLOPE_NONCOMPLIANT`. Independently, any plan covering a `max_depth_ft` of 20 feet or more must specify `SHORING` or `TRENCH_BOX` and carry `engineered_certification` set to true; otherwise submission fails with `ERR_ENGINEERED_DESIGN_REQUIRED`. A successful submission captures the caller in `submitted_by_user_id` and moves the plan `DRAFT → SUBMITTED`.

Review belongs to the `SafetyOfficer`, the competent person for excavation safety, who passes a `decision` of `APPROVE` or `REJECT`. Segregation of duties applies: the reviewer's `X-User-ID` must differ from `submitted_by_user_id`, else `ERR_SOD_VIOLATION`. The reviewer is captured in `reviewed_by_user_id`, and the plan moves from `SUBMITTED` to `APPROVED` or `REJECTED` according to the decision. A `REJECTED` plan is not dead — the `Foreman` may revise it back to `DRAFT`, which increments `revision` by one and optionally applies new values for `max_depth_ft`, `soil_class`, `protective_system`, `slope_ratio`, or `engineered_certification` before the next submission.

Groundwater can void a plan from underneath the crew. When an unforeseen condition of type `GROUNDWATER` is reported on the project (§3.7), the readiness recompute fires in a pinned order: first the project's open groundwater conditions are collected; then every `APPROVED` plan of the project built on `SLOPING` or `BENCHING` moves to `VOIDED`, since standing-water excavation cannot rely on sloped or benched walls; then every segment in `READY` whose plan was just voided reverts to `PLANNED`. Plans using `SHORING` or `TRENCH_BOX` ride the event out untouched. Plans may be listed filtered by `project_id`, `pipe_segment_id`, or `status`.

### 3.4. Pipe Installation: Readiness, Inspection, and Backfill

A pipe segment is the unit of physical work. A `Foreman` creates one with the `project_id`, the `utility_owner_id` of the owner whose facility it will tie into, a `segment_label` such as WL-A-01, the `pipe_material` (`PVC_C900`, `DUCTILE_IRON`, `HDPE`, or `RCP`), the nominal `diameter_in` in inches, the design `length_ft`, the `bedding_class` (`CLASS_B`, `CLASS_C`, or `CLASS_D`), the `design_invert_depth_ft`, the `design_slope_pct`, and the `requires_dewatering` flag. The segment is born `PLANNED` with `lifts_satisfied` zero, `hold_reason` `NONE`, no `resume_status`, and `tie_in_completed` false. Creation also computes `lifts_required`, the number of one-foot backfill lifts the trench will demand: the trench depth is the design invert depth plus the pipe diameter converted from inches to feet plus a bedding allowance of 0.5 feet for `CLASS_B`, 0.5 feet for `CLASS_C`, or 0.25 feet for `CLASS_D`; that depth, divided by the one-foot lift thickness and rounded up to a whole number, is the lift count.

Readiness is a four-gate checkpoint. Marking a segment ready moves it `PLANNED → READY` only when the segment has a trench safety plan in `APPROVED` status (else `ERR_PLAN_NOT_APPROVED`), the project holds an `ACTIVE` locate ticket (`ERR_LOCATE_NOT_ACTIVE`), no pothole verification of the project remains in `PLANNED`, `PERFORMED`, or `CONFLICT` (`ERR_POTHOLES_OUTSTANDING`), and the project's posture is `CLEAR` (`ERR_PROJECT_STOPPED`). Starting installation moves `READY → INSTALLING` and re-verifies the active-ticket and clear-posture gates. Completing installation moves `INSTALLING → INSTALLED` with no further preconditions.

Before backfill, the installation must survive inspection. An `Inspector` records an installation inspection against an `INSTALLED` segment — any other segment status draws `ERR_INVALID_STATE` — capturing the `bedding_ok` and `joint_ok` booleans, the `slope_measured_pct`, and the `cover_depth_ft` over the pipe crown; the recorder's identity lands in `recorded_by_user_id`. The computed `result` is `PASS` only when bedding and joints both conform, the measured slope deviates from the segment's `design_slope_pct` by at most 0.2 percentage points with the boundary inclusive, and the cover is at least 0.5 feet; anything else is `FAIL`. The record starts `RECORDED`. A different `Inspector` — segregation of duties against `recorded_by_user_id`, enforced as `ERR_SOD_VIOLATION` — confirms it, moving `RECORDED → CONFIRMED`. A `ProjectManager` may instead dispute a recorded inspection, moving `RECORDED → DISPUTED`; an inspection in `DISPUTED` status is ignored by the backfill gate, and a fresh inspection may be recorded to take its place.

Backfill is where the rework loop lives. Starting backfill moves `INSTALLED → BACKFILLING` and demands that the segment's most recently created `CONFIRMED` inspection has `result` `PASS` — when none exists, or the latest is a failure, the rejection is `ERR_INSPECTION_NOT_PASSED` — alongside the standing active-ticket and clear-posture gates. When several confirmed inspections of a segment share the same `created_at` — possible because timestamps come from the logical clock — the most recently created is the one recorded last. When the latest confirmed inspection is a `FAIL`, the `Foreman` may instead reopen installation, moving `INSTALLED → INSTALLING` (the attempt draws `ERR_INVALID_STATE` when the latest confirmed result is not `FAIL`), and the segment cycles `INSTALLING → INSTALLED` again once reworked.

During `BACKFILLING`, the `Foreman` records a compaction test per lift, supplying the `pipe_segment_id`, the `lift_number`, the lab's `proctor_max_density_pcf`, the `field_density_pcf`, and the `moisture_pct`. Tests may only be recorded while the segment is `BACKFILLING` (`ERR_INVALID_STATE` otherwise), and lift numbering is strictly sequential: each test's `lift_number` must equal the highest lift number already recorded or accepted on the segment plus one, with the first test numbered 1, else `ERR_LIFT_SEQUENCE`. The computed `compaction_pct` is one hundred times the field density divided by the proctor maximum, rounded half up to one decimal place. The `required_pct` depends on the segment's bedding class — 95.0 for `CLASS_B`, 90.0 for `CLASS_C`, 85.0 for `CLASS_D` — and the `result` is `PASS` when the compaction percentage is at least the required percentage, boundary inclusive, and `FAIL` otherwise.

An `Inspector` reviews each recorded test with a `decision` of `ACCEPT` or `REJECT`, moving the test from `RECORDED` to `ACCEPTED` or `REJECTED` accordingly, again under segregation of duties against `recorded_by_user_id`, and the reviewer's identity is captured in `reviewed_by_user_id`. When a review accepts a test whose result is `PASS`, the segment's compaction summary recomputes over its governing set — the segment's tests in `ACCEPTED` status only, with `RECORDED` and `REJECTED` excluded: `lifts_satisfied` becomes the count of distinct lift numbers between 1 and `lifts_required` that hold an accepted passing test; `avg_compaction_pct` becomes the arithmetic mean of `compaction_pct` across the governing set, rounded half up to one decimal; and `min_compaction_pct` becomes the lowest value in that set. Both statistics are null until at least one test is accepted. Completion then moves `BACKFILLING → COMPLETE` only when `lifts_satisfied` equals `lifts_required` (`ERR_LIFTS_INCOMPLETE` otherwise): the gate is per-lift worst-lift coverage, not the average, so a healthy `avg_compaction_pct` can never mask a missing lift. Segments may be listed filtered by `project_id`, `utility_owner_id`, or `status`; inspections by `pipe_segment_id`, `status`, or `result`; and compaction tests by `pipe_segment_id`, `lift_number`, `status`, or `result`.

### 3.5. Tie-In Shutdown Windows and the Committed-Hours Ledger

Connecting the new segment to the owner's live facility requires a negotiated shutdown. A `ProjectManager` proposes a shutdown window with the `project_id`, the `utility_owner_id`, the `pipe_segment_id` being tied in, the planned `window_start` and `window_end`, and the concurrency token `expected_project_version` described in §2.9. The segment must belong to the named project, and the named owner must match the owner recorded on the segment, else `ERR_CROSS_PROJECT_REFERENCE`. The window occupies the half-open interval from `window_start` inclusive to `window_end` exclusive, and its computed `duration_minutes` is the whole minutes between them; the duration must be greater than zero and no longer than the owner's `max_shutdown_hours` expressed in minutes, with the cap itself allowed, else `ERR_VALIDATION`.

Four temporal rules then guard the proposal, evaluated in this order. The start must lie strictly in the future (`ERR_WINDOW_IN_PAST`). The gap between the current time and `window_start` must be at least the owner's `min_notice_hours` (`ERR_INSUFFICIENT_NOTICE`). The new window must not overlap any existing `PROPOSED`, `CONFIRMED`, or `ACTIVE` window of the same owner under half-open semantics — two windows that merely touch endpoints do not overlap (`ERR_OWNER_WINDOW_OVERLAP`). And the new window must keep at least 120 minutes of clearance from every existing `PROPOSED`, `CONFIRMED`, or `ACTIVE` window of the same project, with exactly 120 minutes of clearance passing (`ERR_PROJECT_WINDOW_BUFFER`).

A created window starts `PROPOSED`, and booking it already commits the owner's time: the owner's `committed_shutdown_minutes` rises by `duration_minutes`, and the project's `version` increments by one as the schedule changes. The ledger rule is simple: an owner's committed minutes are the total `duration_minutes` of that owner's windows in `PROPOSED`, `CONFIRMED`, or `ACTIVE`, and windows in any terminal state — `COMPLETED`, `MISSED`, `REJECTED`, or `CANCELLED` — contribute zero.

The owner's answer comes from a `UtilityOwnerRep` whose `X-User-ID` equals the window's `utility_owner_id` (any other caller draws `ERR_UNAUTHORIZED_ROLE`), passing a `decision` of `CONFIRM` or `REJECT` and thereby moving the window from `PROPOSED` to `CONFIRMED` or `REJECTED`. Confirming additionally requires the project's posture to be `CLEAR` (`ERR_PROJECT_STOPPED`) and the tied-in segment to be in `READY`, `INSTALLING`, `INSTALLED`, or `BACKFILLING` (`ERR_INVALID_STATE`); a confirmation leaves the committed-minutes ledger unchanged, because `PROPOSED` already counted. A rejection releases the window's minutes back off the ledger. A `ProjectManager` may instead cancel: a `PROPOSED` window may be cancelled at any time, while a `CONFIRMED` window may be cancelled only while the current time is still before its `window_end` — once the end has passed, the window is in missed territory and the cancel is rejected with `ERR_INVALID_STATE`. Cancellation releases the committed minutes in both cases.

From there, the clock decides fate as laid out in §2.5: a window still `PROPOSED` when its start passes becomes `MISSED` and releases its minutes; a `CONFIRMED` window becomes `ACTIVE` when its start arrives while the project is `CLEAR`, but a confirmed window whose start passes while the project is `STOPPED` simply stays `CONFIRMED`; and a window in `CONFIRMED` or `ACTIVE` becomes `MISSED` once its end passes, again releasing minutes. When the tie-in is finished inside an `ACTIVE` window, the `Foreman` completes it, moving `ACTIVE → COMPLETED`: the segment's `tie_in_completed` flips to true and the owner's committed minutes fall by the window's duration. One more system path exists — when a segment is placed on a dewatering hold (§3.6), each of its `PROPOSED` windows is cancelled automatically with the same release of minutes. Windows may be listed filtered by `project_id`, `utility_owner_id`, `pipe_segment_id`, or `status`.

### 3.6. Dewatering Discharge Permits and Compliance Readings

Segments flagged `requires_dewatering` cannot run pumps without a discharge permit. A `ProjectManager` registers a permit with the `project_id`, the regulator's `permit_number`, and the compliance parameters: `max_flow_gpm`, the maximum instantaneous flow; `turbidity_limit_ntu`, the turbidity ceiling; `daily_volume_limit_gal`, the maximum cumulative discharge per UTC calendar day; and the effective window bounded by `effective_from` and `effective_to`, treated as half-open — valid on or after `effective_from` and strictly before `effective_to`. A permit whose `effective_from` is not strictly before its `effective_to` is rejected with `ERR_VALIDATION`. The permit's status is computed once at creation: `ACTIVE` when the current instant already falls inside the effective window, otherwise `ISSUED`, with the clock driving later activation and expiry per §2.5. Its `exceedance_count` starts at zero.

A `Foreman` records each discharge reading with the `discharge_permit_id`, the `recorded_at` instant, the measured `flow_gpm`, the measured `turbidity_ntu`, and the `duration_min` the reading represents. Readings are accepted only while the permit is `ACTIVE` (`ERR_PERMIT_NOT_ACTIVE`), and `recorded_at` must fall inside the permit's effective window (`ERR_READING_OUTSIDE_PERMIT_WINDOW`). The computed `volume_gal` is the flow multiplied by the duration.

Classification follows a strict precedence, first match wins. If the reading's turbidity is at or above the permit's turbidity limit, the `classification` is `EXCEEDS_TURBIDITY` — the boundary is inclusive. Otherwise, if the day's cumulative volume — the sum of `volume_gal` across every reading of this permit whose `recorded_at` falls on the same UTC calendar date as the new reading, processed chronologically by `recorded_at` and then `created_at`, the new reading included — is strictly greater than `daily_volume_limit_gal`, the classification is `EXCEEDS_VOLUME`. Otherwise, if `flow_gpm` is strictly greater than `max_flow_gpm`, the classification is `EXCEEDS_FLOW`. Failing all three, the reading is `NORMAL`. Any of the three exceedance classifications increments the permit's `exceedance_count` by one.

A turbidity exceedance does more than count. `EXCEEDS_TURBIDITY` suspends the permit, moving it `ACTIVE → SUSPENDED`, and the `SUSPENDED` status cascades: every segment of the project that is `INSTALLING` with `requires_dewatering` true moves to `ON_HOLD` with `hold_reason` `DEWATERING` and `resume_status` `INSTALLING`, and every `PROPOSED` shutdown window of each held segment is cancelled with its committed minutes released. Segments already `BACKFILLING` are not held — the pipe is already in the ground and covering it cannot wait for a permit.

Reinstatement belongs to the `ProjectManager`. When the current instant still falls inside the effective window and the project's posture is `CLEAR` (`ERR_PROJECT_STOPPED` otherwise), the permit returns `SUSPENDED → ACTIVE`, and every segment held for `DEWATERING` resumes to its remembered `resume_status`, with `hold_reason` clearing to `NONE` and `resume_status` to null. When the permit's `effective_to` has already passed, reinstatement instead moves the permit `SUSPENDED → EXPIRED`, and any segment still held for dewatering remains `ON_HOLD` — excavation cannot resume under an expired permit. A permit's readings are listed in chronological order — by `recorded_at`, then `created_at`, with readings equal on both keys keeping the order in which they were recorded — rather than the default ordering, and may be filtered by `classification`; permits themselves may be listed filtered by `project_id` or `status`.

### 3.7. Unforeseen Conditions and the Stop-Work Cascade

When the trench surprises the crew, a `ProjectManager` reports an unforeseen condition with the `project_id`, an optional `pipe_segment_id` — left null for project-wide conditions, and when supplied it must reference a segment of the same project or face `ERR_CROSS_PROJECT_REFERENCE` — the `condition_type` (`ROCK`, `GROUNDWATER`, `CONTAMINATED_SOIL`, `CONFLICTING_UTILITY`, or `VOID`), the `stop_work_required` flag, and a free-text `description`. Conditions may only be reported against a project that is still `ACTIVE`; against anything else the create draws `ERR_INVALID_STATE`. The condition starts `OPEN`.

Two cascades can fire at creation. If `stop_work_required` is true, the project's `work_posture` flips to `STOPPED` — that is the first hop — and then every segment of the project in `INSTALLING` or `BACKFILLING` moves to `ON_HOLD` with `hold_reason` `STOP_WORK` and its prior status remembered in `resume_status`, the second hop described in §2.6. Independently, a condition of type `GROUNDWATER` fires the readiness recompute from §3.3: the project's open groundwater conditions are collected, every `APPROVED` plan relying on `SLOPING` or `BENCHING` is `VOIDED`, and every `READY` segment whose plan was voided falls back to `PLANNED`, in that pinned order.

Resolution is gated on money. A `ProjectManager` resolves a condition by passing an `outcome` of `RESOLVED` or `CLOSED_NO_ACTION`. From `OPEN`, either outcome requires that no change order of the condition remain in `DRAFT`, `SUBMITTED`, or `APPROVED` (`ERR_CO_NOT_COMPLETED`). A condition that has moved to `MITIGATING` — which happens automatically the moment one of its change orders is approved (§3.8) — may move to `RESOLVED` only when every change order of the condition has reached `COMPLETED` or `SUPERSEDED`. Whenever a stop-work condition leaves `OPEN`, the project's posture recomputes: if no other `OPEN` condition with `stop_work_required` remains, the posture clears and every segment held with `hold_reason` `STOP_WORK` resumes per §2.6; segments held for `DEWATERING` are not resumed by this transition. Conditions may be listed filtered by `project_id`, `pipe_segment_id`, `status`, or `condition_type`.

### 3.8. Change Orders: Pricing, Approval, and Settlement

Unforeseen conditions are paid for through change orders. A `ProjectManager` creates one against a condition that is still `OPEN` — anything else is `ERR_CONDITION_NOT_OPEN` — supplying the `project_id`, the `unforeseen_condition_id` (which must sit in the same project, else `ERR_CROSS_PROJECT_REFERENCE`), the `utility_owner_id` responsible for payment, the estimated `labor_hours` and `labor_rate_cents`, the estimated `equipment_hours` and `equipment_rate_cents`, the estimated `material_cost_cents`, and the concurrency token `expected_project_version` from §2.9. The new order starts `DRAFT` at `revision` 1. Creation is also a supersede event: any existing change order of the same condition in `DRAFT` or `SUBMITTED` moves to `SUPERSEDED`, and because creation increments the project's `version` by one, the stale-version guard is what prevents a supersede from ever firing off an outdated view of the project.

Pricing follows a pinned rounding order so that stored totals are exact sums of rounded components. The labor cost line is the labor hours multiplied by the labor rate in cents per hour, rounded half up to a whole cent; the equipment cost line is computed the same way from the equipment hours and rate. The `direct_cost_cents` is the sum of those two rounded lines plus the material cost. The markup is marginal over the direct cost in three tiers: fifteen percent of the portion of the direct cost up to and including 2,500,000 cents — twenty-five thousand dollars; ten percent of the portion above 2,500,000 cents and up to and including 10,000,000 cents — one hundred thousand dollars; and five percent of any portion above 10,000,000 cents. Each tier slice is rounded half up to a whole cent, and the `markup_cents` is the sum of the three rounded slices. The estimate-based `provisional_price_cents` is the direct cost plus the markup, and it must not exceed the project's `single_co_cap_cents`, with a price exactly at the cap allowed — a breach at creation or at submission is `ERR_PRICE_CAP_EXCEEDED`.

Submitting moves the order `DRAFT → SUBMITTED`, re-verifying that the condition is `OPEN` or `MITIGATING` (`ERR_CONDITION_NOT_OPEN`) and that the provisional price still fits under the per-order cap, and capturing the caller in `submitted_by_user_id`. Review is amount-gated. When the `provisional_price_cents` is 2,500,000 cents or more, only a `UtilityOwnerRep` whose `X-User-ID` equals the change order's `utility_owner_id` may decide; below that threshold the decision belongs to a `ProjectManager`. Either way, the reviewer's identity must differ from `submitted_by_user_id` (`ERR_SOD_VIOLATION`), the condition must still be `OPEN` or `MITIGATING` (`ERR_CONDITION_NOT_OPEN`), and an approval must keep the project's books inside its pool: the existing `approved_co_total_cents` plus this order's `provisional_price_cents` may not exceed `contingency_cents`, with equality allowed, else `ERR_CONTINGENCY_EXCEEDED`. The reviewer passes a `decision` of `APPROVE` or `REJECT` — moving the order from `SUBMITTED` to `APPROVED` or `REJECTED` — and is captured in `reviewed_by_user_id`.

Approval moves money and condition alike: the project's `approved_co_total_cents` rises by the `provisional_price_cents`, and a condition still `OPEN` moves to `MITIGATING`. Rejection leaves the books untouched, and a `REJECTED` order may be revised back to `DRAFT` by the `ProjectManager` — `revision` increments by one, and any newly supplied `labor_hours`, `labor_rate_cents`, `equipment_hours`, `equipment_rate_cents`, or `material_cost_cents` trigger a recompute of `direct_cost_cents`, `markup_cents`, and `provisional_price_cents`.

Settlement happens at completion. Completing an `APPROVED` order takes the actuals — `actual_labor_hours`, `actual_labor_rate_cents`, `actual_equipment_hours`, `actual_equipment_rate_cents`, and `actual_material_cost_cents` — and prices them through the identical procedure used for the estimate, producing the time-and-materials `final_price_cents`. The `price_delta_cents` is the final price minus the provisional price, and the project's `approved_co_total_cents` shifts by exactly that delta: the order's contribution to the ledger swaps from its provisional value to its final value, so an underrun reduces the committed total. The order ends `COMPLETED`. Change orders may be listed filtered by `project_id`, `unforeseen_condition_id`, `utility_owner_id`, or `status`.

### 3.9. As-Built Records and Project Closeout

The record of what was actually built is the as-built package. A `ProjectManager` drafts one for a segment by supplying the `pipe_segment_id`, the licensed surveyor's `surveyor_stamp`, and the surveyed `measured_length_ft` and `measured_invert_ft`. A segment may have at most one open package: creating while one exists in `DRAFT` or `SUBMITTED` is rejected with `ERR_ASBUILT_ALREADY_OPEN`. The package starts `DRAFT` at `revision` 1, and its acceptance arithmetic is computed at creation and again on every revision.

Acceptance is a two-axis tolerance check. The `length_variance_ft` is the measured length minus the segment's design `length_ft`, and the `invert_variance_ft` is the measured invert minus the segment's `design_invert_depth_ft`. The length tolerance is the larger of 1.0 foot and one percent of the design length rounded half up to one decimal place; the invert tolerance is the larger of 0.1 foot and one half of one percent of the design invert depth rounded half up to two decimal places. The computed `within_tolerance` is true only when the absolute length variance is at most the length tolerance and the absolute invert variance is at most the invert tolerance — both boundaries inclusive.

Submitting the package moves it `DRAFT → SUBMITTED` and requires the segment to be `COMPLETE` (`ERR_SEGMENT_NOT_COMPLETE`). Review belongs to a `UtilityOwnerRep` whose `X-User-ID` equals the segment's `utility_owner_id`, failing which the call draws `ERR_UNAUTHORIZED_ROLE`. The rep passes a `decision` of `ACCEPT` or `REJECT`, moving the package from `SUBMITTED` to `ACCEPTED` or `REJECTED`; an accept against a package whose `within_tolerance` is false is rejected with `ERR_ASBUILT_OUT_OF_TOLERANCE`. An accepted package is terminal; a `REJECTED` package may be revised back to `DRAFT` by the `ProjectManager`, incrementing `revision` and optionally applying a new `surveyor_stamp`, `measured_length_ft`, or `measured_invert_ft`, with the variances and `within_tolerance` recomputed from whatever was supplied.

Closeout is the project's final gate. Beginning closeout moves the project `ACTIVE → CLOSING` — the intermediate `CLOSING` status marks that closeout has been initiated — only when the completeness bundle passes in full: every pipe segment of the project is `COMPLETE`, every pipe segment has an as-built package in `ACCEPTED`, no unforeseen condition remains in `OPEN` or `MITIGATING`, no change order remains in `DRAFT`, `SUBMITTED`, or `APPROVED`, and the project's `work_posture` is `CLEAR`. Any shortfall is rejected with `ERR_CLOSEOUT_INCOMPLETE`. Closing then moves `CLOSING → CLOSED` and stamps `closed_at` with the current logical clock time; `CLOSED` is terminal, and no further actions may be taken on the project. As-built packages may be listed filtered by `pipe_segment_id` or `status`.

## 4. Endpoint Definitions

Creating a new resource returns `201 Created`; every operation that modifies an existing resource — transitions, reviews, renewals, revisions, completions — returns `200 OK`. All list endpoints paginate per §2.3, and all six roles may call every GET endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/site-utility/projects` | Create a project (starts `ACTIVE`, posture `CLEAR`) | ProjectManager |
| GET | `/site-utility/projects` | List projects with optional filters | Any (all roles) |
| GET | `/site-utility/projects/{id}` | Get one project | Any (all roles) |
| POST | `/site-utility/projects/{id}/begin-closeout` | `ACTIVE → CLOSING` after the closeout completeness bundle passes | ProjectManager |
| POST | `/site-utility/projects/{id}/close` | `CLOSING → CLOSED`; stamps `closed_at` | ProjectManager |
| GET | `/site-utility/projects/{id}/audit-events` | List audit events for a project, chronological | Any (all roles) |
| POST | `/site-utility/utility-owners` | Register a utility owner | OpsAdmin |
| GET | `/site-utility/utility-owners` | List utility owners | Any (all roles) |
| GET | `/site-utility/utility-owners/{id}` | Get one utility owner | Any (all roles) |
| POST | `/site-utility/locate-tickets` | Create a locate ticket for a project (`DRAFT`); one open ticket per project | ProjectManager |
| GET | `/site-utility/locate-tickets` | List locate tickets | Any (all roles) |
| GET | `/site-utility/locate-tickets/{id}` | Get one locate ticket | Any (all roles) |
| POST | `/site-utility/locate-tickets/{id}/submit` | `DRAFT → SUBMITTED` | ProjectManager |
| POST | `/site-utility/locate-tickets/{id}/renew` | Extend `valid_until` by 672 hours; `EXPIRED → ACTIVE` when the new validity covers now | ProjectManager |
| POST | `/site-utility/pothole-verifications` | Plan a pothole verification at a station; supersedes a same-station `CONFLICT` pothole | ProjectManager |
| GET | `/site-utility/pothole-verifications` | List pothole verifications | Any (all roles) |
| GET | `/site-utility/pothole-verifications/{id}` | Get one pothole verification | Any (all roles) |
| POST | `/site-utility/pothole-verifications/{id}/perform` | `PLANNED → PERFORMED`; records measurements; requires active ticket and clear posture | Foreman |
| POST | `/site-utility/pothole-verifications/{id}/verify` | `PERFORMED → VERIFIED` when measurements are within tolerance | ProjectManager |
| POST | `/site-utility/pothole-verifications/{id}/mark-conflict` | `PERFORMED → CONFLICT` | ProjectManager |
| POST | `/site-utility/trench-safety-plans` | Draft a trench safety plan for a pipe segment | Foreman |
| GET | `/site-utility/trench-safety-plans` | List trench safety plans | Any (all roles) |
| GET | `/site-utility/trench-safety-plans/{id}` | Get one trench safety plan | Any (all roles) |
| POST | `/site-utility/trench-safety-plans/{id}/submit` | `DRAFT → SUBMITTED`; enforces slope and depth compliance | Foreman |
| POST | `/site-utility/trench-safety-plans/{id}/review` | `SUBMITTED → APPROVED` or `REJECTED`; reviewer must differ from submitter | SafetyOfficer |
| POST | `/site-utility/trench-safety-plans/{id}/revise` | `REJECTED → DRAFT`; bumps `revision`; optional field changes | Foreman |
| POST | `/site-utility/pipe-segments` | Create a pipe segment (`PLANNED`); computes `lifts_required` | Foreman |
| GET | `/site-utility/pipe-segments` | List pipe segments | Any (all roles) |
| GET | `/site-utility/pipe-segments/{id}` | Get one pipe segment | Any (all roles) |
| POST | `/site-utility/pipe-segments/{id}/mark-ready` | `PLANNED → READY`; enforces plan, locate, pothole, and posture gates | Foreman |
| POST | `/site-utility/pipe-segments/{id}/start-install` | `READY → INSTALLING`; re-checks locate ticket and posture | Foreman |
| POST | `/site-utility/pipe-segments/{id}/complete-install` | `INSTALLING → INSTALLED` | Foreman |
| POST | `/site-utility/pipe-segments/{id}/reopen-install` | `INSTALLED → INSTALLING` rework loop; requires latest confirmed inspection `FAIL` | Foreman |
| POST | `/site-utility/pipe-segments/{id}/start-backfill` | `INSTALLED → BACKFILLING`; requires latest confirmed inspection `PASS`, active ticket, clear posture | Foreman |
| POST | `/site-utility/pipe-segments/{id}/complete` | `BACKFILLING → COMPLETE`; requires all lifts satisfied | Foreman |
| POST | `/site-utility/installation-inspections` | Record an installation inspection on an `INSTALLED` segment; computes `result` | Inspector |
| GET | `/site-utility/installation-inspections` | List installation inspections | Any (all roles) |
| GET | `/site-utility/installation-inspections/{id}` | Get one installation inspection | Any (all roles) |
| POST | `/site-utility/installation-inspections/{id}/confirm` | `RECORDED → CONFIRMED`; confirmer must differ from recorder | Inspector |
| POST | `/site-utility/installation-inspections/{id}/dispute` | `RECORDED → DISPUTED`; disputed inspections are ignored by the backfill gate | ProjectManager |
| POST | `/site-utility/shutdown-windows` | Propose a tie-in shutdown window; OCC-guarded on the project; enforces notice, overlap, and buffer rules | ProjectManager |
| GET | `/site-utility/shutdown-windows` | List shutdown windows | Any (all roles) |
| GET | `/site-utility/shutdown-windows/{id}` | Get one shutdown window | Any (all roles) |
| POST | `/site-utility/shutdown-windows/{id}/review` | `PROPOSED → CONFIRMED` or `REJECTED`; owner rep of the window's owner only | UtilityOwnerRep |
| POST | `/site-utility/shutdown-windows/{id}/cancel` | `PROPOSED` or `CONFIRMED → CANCELLED`; releases committed minutes | ProjectManager |
| POST | `/site-utility/shutdown-windows/{id}/complete` | `ACTIVE → COMPLETED`; marks the segment `tie_in_completed` | Foreman |
| POST | `/site-utility/discharge-permits` | Register a dewatering discharge permit | ProjectManager |
| GET | `/site-utility/discharge-permits` | List discharge permits | Any (all roles) |
| GET | `/site-utility/discharge-permits/{id}` | Get one discharge permit | Any (all roles) |
| POST | `/site-utility/discharge-permits/{id}/reinstate` | `SUSPENDED → ACTIVE` inside the effective window, else `→ EXPIRED`; resumes dewatering-held segments | ProjectManager |
| GET | `/site-utility/discharge-permits/{id}/readings` | List readings of a permit, chronological by `recorded_at` then `created_at` | Any (all roles) |
| POST | `/site-utility/discharge-readings` | Record a discharge reading; computes volume and classification; `EXCEEDS_TURBIDITY` suspends the permit | Foreman |
| POST | `/site-utility/compaction-tests` | Record a compaction test on the next lift of a `BACKFILLING` segment; computes `compaction_pct`, `required_pct`, `result` | Foreman |
| GET | `/site-utility/compaction-tests` | List compaction tests | Any (all roles) |
| GET | `/site-utility/compaction-tests/{id}` | Get one compaction test | Any (all roles) |
| POST | `/site-utility/compaction-tests/{id}/review` | `RECORDED → ACCEPTED` or `REJECTED`; reviewer must differ from recorder; accepted passes advance `lifts_satisfied` | Inspector |
| POST | `/site-utility/as-built-packages` | Draft an as-built survey package for a segment; computes variances and `within_tolerance` | ProjectManager |
| GET | `/site-utility/as-built-packages` | List as-built packages | Any (all roles) |
| GET | `/site-utility/as-built-packages/{id}` | Get one as-built package | Any (all roles) |
| POST | `/site-utility/as-built-packages/{id}/submit` | `DRAFT → SUBMITTED`; requires segment `COMPLETE` | ProjectManager |
| POST | `/site-utility/as-built-packages/{id}/review` | `SUBMITTED → ACCEPTED` or `REJECTED`; owner rep of the segment's owner; accept requires `within_tolerance` | UtilityOwnerRep |
| POST | `/site-utility/as-built-packages/{id}/revise` | `REJECTED → DRAFT`; bumps `revision`; optional field changes recompute variances | ProjectManager |
| POST | `/site-utility/unforeseen-conditions` | Report an unforeseen condition; stop-work drives the hold cascade; `GROUNDWATER` voids sloped plans | ProjectManager |
| GET | `/site-utility/unforeseen-conditions` | List unforeseen conditions | Any (all roles) |
| GET | `/site-utility/unforeseen-conditions/{id}` | Get one unforeseen condition | Any (all roles) |
| POST | `/site-utility/unforeseen-conditions/{id}/resolve` | `OPEN` or `MITIGATING → RESOLVED`, or `OPEN → CLOSED_NO_ACTION`; open change orders block resolution | ProjectManager |
| POST | `/site-utility/change-orders` | Create a change order for an `OPEN` condition; OCC-guarded on the project; supersedes open orders of the same condition | ProjectManager |
| GET | `/site-utility/change-orders` | List change orders | Any (all roles) |
| GET | `/site-utility/change-orders/{id}` | Get one change order | Any (all roles) |
| POST | `/site-utility/change-orders/{id}/submit` | `DRAFT → SUBMITTED`; re-checks condition openness and the price cap | ProjectManager |
| POST | `/site-utility/change-orders/{id}/review` | `SUBMITTED → APPROVED` or `REJECTED`; amount-gated role (at or above 2,500,000 cents: the owner rep; below: the project manager); reviewer differs from submitter | ProjectManager, UtilityOwnerRep |
| POST | `/site-utility/change-orders/{id}/revise` | `REJECTED → DRAFT`; bumps `revision`; optional pricing changes recompute the provisional price | ProjectManager |
| POST | `/site-utility/change-orders/{id}/complete` | `APPROVED → COMPLETED`; computes the final price from actuals and the delta | ProjectManager |
| POST | `/site-utility/_clock/set_current_utc` | Advance the server logical clock; fires the pinned time-driven transitions | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_STOPPED` | 409 Conflict |
| `ERR_LOCATE_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_TICKET` | 409 Conflict |
| `ERR_DUPLICATE_STATION` | 409 Conflict |
| `ERR_POTHOLES_OUTSTANDING` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_INSPECTION_NOT_PASSED` | 409 Conflict |
| `ERR_LIFTS_INCOMPLETE` | 409 Conflict |
| `ERR_PERMIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_OWNER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROJECT_WINDOW_BUFFER` | 409 Conflict |
| `ERR_CO_NOT_COMPLETED` | 409 Conflict |
| `ERR_CONTINGENCY_EXCEEDED` | 409 Conflict |
| `ERR_ASBUILT_ALREADY_OPEN` | 409 Conflict |
| `ERR_ASBUILT_OUT_OF_TOLERANCE` | 409 Conflict |
| `ERR_CLOSEOUT_INCOMPLETE` | 409 Conflict |
| `ERR_SEGMENT_NOT_COMPLETE` | 409 Conflict |
| `ERR_POTHOLE_TOLERANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SLOPE_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_ENGINEERED_DESIGN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_LIFT_SEQUENCE` | 422 Unprocessable Entity |
| `ERR_READING_OUTSIDE_PERMIT_WINDOW` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_NOTICE` | 422 Unprocessable Entity |
| `ERR_CONDITION_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_CROSS_PROJECT_REFERENCE` | 422 Unprocessable Entity |
| `ERR_PRICE_CAP_EXCEEDED` | 422 Unprocessable Entity |

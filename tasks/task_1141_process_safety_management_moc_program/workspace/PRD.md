# Process Safety MOC API — Product Requirements Document

## 1. Introduction

A chemical plant's Process Safety Management (PSM) office carries a regulatory obligation that is unforgiving in both directions: every change to process equipment, chemistry, or procedures must pass through a disciplined Management of Change (MOC) pipeline, and every safeguard the plant relies on — hazard analyses, pre-startup reviews, action items, audits — must stay demonstrably current. Paper systems and ad-hoc spreadsheets fail audits because they cannot prove, at any instant, who approved what, which temporary changes are about to expire, or whether the plant's aggregate risk posture still permits new work. This API exists to make that proof mechanical.

The service governs the full MOC lifecycle for a fleet of plant units: change-request classification and technical review, the PHA/HAZOP revalidation cycle, a pre-startup safety review (PSSR) gate before startup authorization, action-item tracking with closure evidence, temporary-change expiry and extension control, procedure and training linkage, incident investigations that feed back into the hazard analysis, and compliance audits whose findings spawn corrective actions. A logical, admin-controlled clock drives all scheduling semantics so that expiry, overdue, and revalidation behavior is deterministic and testable. All resources are mounted under the `/psm` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly across the API: authentication, response envelopes, pagination, time semantics, resource identity, precision, concurrency control, validation ordering, and the unit-level safety posture that gates plant work.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes nine roles: `PsmAdmin` (PSM system administrator — unit configuration, personnel registry, logical clock), `PsmManager` (PSM office manager — classification, the PHA program, verifications, closures, extension decisions), `Requester` (process engineer who initiates and shepherds MOCs), `TechnicalReviewer` (discipline-qualified technical reviewer), `OpsApprover` (operations manager approving MOCs for implementation and activation), `PssrLead` (PSSR-certified field verification leader), `Investigator` (incident investigator), `Auditor` (compliance auditor), and `TrainingCoordinator` (procedure and training administrator). All nine roles may perform reads; write operations are restricted per role as detailed in §4.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Requester`, `TechnicalReviewer`, `OpsApprover`, `PssrLead`, `Investigator`, or `Auditor`, `X-User-ID` is the `id` of the acting `Personnel` record; ownership checks on any resource that references a `Personnel` compare the resource's foreign-key field (for example `requester_id` on a MOC, `assignee_id` on an action item, `lead_id` on a PSSR, `investigator_id` on an investigation, `lead_auditor_id` on an audit, or `personnel_id` on a training assignment) to `X-User-ID`. When `X-User-Role` is `PsmAdmin`, `PsmManager`, or `TrainingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `decided_by` on an extension decision or `verifier_id` on a verified action item) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. One exception is noted in §3.3: the list of technical review rounds for a MOC is ordered by ascending `round_number`. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Calendar-Day Semantics

The server maintains a logical clock that governs every date comparison in the system. At startup, before any administrative intervention, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. A `PsmAdmin` may advance it through a test-driving capability that accepts a `to_iso8601` instant; the supplied instant must be at or after the current logical time, and an attempt to move the clock backward is rejected with `ERR_CLOCK_REGRESSION`. Every clock set runs a sweep across the plant: PHA studies transition into `DUE_SOON` or `OVERDUE` as their dues arrive, in-service temporary MOCs whose end dates have passed are swept into expiry, overdue action-item counts are refreshed, and every affected unit's safety index and posture are recomputed.

Every business date and datetime field in the system is calendar-day granular in UTC, serialized as ISO 8601 with the time component fixed at T00:00:00Z. All comparisons — due dates, overdue tests, fieldwork windows, revalidation dues — are performed on those normalized UTC midnights against the logical clock.

### 2.5. Common Resource Properties and Identity

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the resource type.
- `created_at` — an ISO 8601 UTC timestamp recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on any modification.
- `version` — a system-managed integer that increments by one on every mutation of the resource.

Any operation that mutates a resource — including system-driven cascades and sweeps — refreshes its `updated_at` and increments its `version`. Evidence items are the single exception to this contract: an `EvidenceItem` is append-only, carries only `id` and `created_at`, has neither `updated_at` nor `version`, and exposes no update or delete operations.

### 2.6. Numeric Precision, Rounding, and Date Arithmetic

All risk scores and coverage percentages are decimal values rounded half-up to exactly two decimal places, and are returned as numbers rather than strings. The unit process safety index is computed in integer arithmetic with exact band comparisons. PHA revalidation dues are computed at day granularity; the risk-accelerated due date rounds its day count down to a whole number of days. All forward date arithmetic treats one month as exactly thirty days. Training coverage rounds twice by design — each procedure update's coverage is rounded half-up to two decimal places first, and only then averaged and rounded again — as detailed in §3.4.

### 2.7. Optimistic Concurrency Control

Two creation endpoints participate in optimistic concurrency control, both guarding a supersede decision on a parent MOC. Creating a pre-startup safety review on a MOC, and creating an extension request on a MOC, each require a non-optional `expected_moc_version` field in the request body carrying the client's last observed `version` of that MOC. If the supplied value does not match the MOC's current `version`, the request is rejected with `ERR_STALE_MOC_VERSION` (HTTP 412): the client's view of the MOC is stale — for example, another writer's superseding creation has already advanced the version — so a supersede decision must not be based on it. This stale-version check is evaluated before any business-rule validation on those two endpoints. Endpoints other than these two do not accept a version field at all.

### 2.8. Nested Resource Retrieval

Requests that target nested resources are validated strictly left-to-right along the path: the unit is resolved before the MOC, the MOC before its child collection, and so on. The first identifier that does not correspond to an existing resource produces that resource type's not-found error — `ERR_UNIT_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`, `ERR_MOC_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_PHA_STUDY_NOT_FOUND`, `ERR_REVALIDATION_NOT_FOUND`, `ERR_PSSR_NOT_FOUND`, `ERR_ACTION_ITEM_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_PROCEDURE_UPDATE_NOT_FOUND`, `ERR_TRAINING_ASSIGNMENT_NOT_FOUND`, or `ERR_EXTENSION_NOT_FOUND` — and no later segment is examined. The same not-found discipline applies to personnel referenced by identifier in a request body: an unknown referenced `Personnel` id yields `ERR_PERSONNEL_NOT_FOUND`.

### 2.9. Validation Pipeline and Priority Ordering

Every request is validated in a fixed pipeline order, and the first failing check determines the error returned; later checks are never consulted once an earlier one has fired.

1. **User context.** The `X-User-ID` and `X-User-Role` headers are present and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The role is permitted for the endpoint — otherwise `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Path existence.** Path identifiers exist, validated left-to-right as in §2.8 — otherwise the corresponding 404.
4. **Stale version (OCC).** On the two guarded creation endpoints, `expected_moc_version` matches the MOC's current `version` — otherwise `ERR_STALE_MOC_VERSION`. This runs before any business check.
5. **State validity.** The target entity is in a valid from-state for the requested transition — otherwise the entity's state error (for example `ERR_MOC_INVALID_STATE`, `ERR_PSSR_INVALID_STATE`, `ERR_EXTENSION_NOT_PENDING`).
6. **Business safety, in sub-order.** Ownership first (`ERR_NOT_RESOURCE_OWNER`), then qualification (`ERR_QUALIFICATION_MISSING`), then segregation of duties (`ERR_SOD_REVIEWER_IS_REQUESTER`, `ERR_SOD_APPROVER_IS_REQUESTER`, `ERR_SOD_PSSR_LEAD_IS_REQUESTER`, `ERR_SOD_VERIFIER_IS_COMPLETER`), then unit posture gates (`ERR_UNIT_POSTURE_FROZEN`, `ERR_UNIT_POSTURE_RESTRICTED`), then verdict checklist integrity (`ERR_REVIEW_CHECKLIST_INCOMPLETE`).
7. **Temporal windows and clock.** Fieldwork-window and PHA-currency checks (`ERR_FIELDWORK_WINDOW_NOT_ACTIVE`, `ERR_PHA_NOT_CURRENT`), and monotonicity of the logical clock on clock sets (`ERR_CLOCK_REGRESSION`).
8. **Business constraints, in sub-order.** Kind/class constraints (`ERR_MOC_NOT_TEMPORARY`, `ERR_INVALID_REQUEST`); then numeric caps in their pinned sub-order — extension count first (`ERR_MAX_EXTENSIONS_REACHED`), then per-extension days (`ERR_TEMP_EXTENSION_EXCEEDS_MAX_DAYS`), then the total temporary cap (`ERR_TEMP_TOTAL_CAP_EXCEEDED`), with the classify-time duration bound `ERR_TEMP_DURATION_EXCEEDS_MAX` in the same family; then uniqueness (`ERR_UNIT_CODE_EXISTS`, `ERR_EMPLOYEE_REF_EXISTS`, `ERR_PHA_STUDY_EXISTS`, `ERR_DUPLICATE_TRAINING_ASSIGNMENT`); then temporal overlap (`ERR_PSSR_WINDOW_OVERLAP`, `ERR_AUDIT_WINDOW_CONFLICT`).
9. **Cross-entity completion gates.** Final gate checks that depend on the state of other entities: `ERR_PSSR_NOT_APPROVED`, `ERR_OPEN_P1_ACTION_ITEMS`, `ERR_PROCEDURES_NOT_PUBLISHED`, `ERR_TRAINING_COVERAGE_INSUFFICIENT`, `ERR_NO_EVIDENCE_ATTACHED`, `ERR_AUDIT_OPEN_FINDINGS`, `ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE`, `ERR_PSSR_OPEN_PUNCH_ITEMS`, `ERR_NO_TRAINING_ASSIGNED`.

Independent of this pipeline, any request that is malformed — a missing required field, a value of the wrong type, an unknown enum value, or an invalid date — is rejected with `ERR_INVALID_REQUEST`.

### 2.10. Unit Process Safety Index and Posture Gating

Each plant unit carries a computed `process_safety_index`, a composite score capped between 0 and 100, and a derived `psm_posture` of `NORMAL`, `RESTRICTED`, or `FROZEN`. The index is evaluated in two pinned phases that must not interleave, because some of its inputs (action-item due dates, for instance) were themselves assigned using earlier index snapshots. Phase one takes a snapshot of counts at the current clock: the number of the unit's action items in an open status — `OPEN`, `IN_PROGRESS`, `SUBMITTED_FOR_VERIFICATION`, or `REJECTED` — whose `due_date` is strictly before the current clock; a one if the unit's PHA study is `OVERDUE`, else zero; a one if the study is `REVALIDATION_REQUIRED`, else zero; the number of the unit's incident investigations not yet `CLOSED` whose `severity_class` is `HIGH` or `CATASTROPHIC`; and the number of audit findings across the unit's audits with `severity` `MAJOR_NC` that are not yet `CLOSED`. Phase two composes the index: fifteen points per overdue open action item, plus twenty-five if the study is overdue, plus twenty if a revalidation is required, plus ten per open high-severity incident, plus five per open major nonconformance — the total capped at one hundred.

The posture band is inclusive on its lower edge: an index below 40 is `NORMAL`, an index of at least 40 but below 70 is `RESTRICTED`, and an index of 70 or higher is `FROZEN` — so exactly 40 is `RESTRICTED` and exactly 70 is `FROZEN`. The index is always recomputed from a fresh phase-one snapshot, never from a partially updated index, and no fixed-point iteration is performed. Recomputation is triggered by the clock sweep; by action-item creation, verification, reopening, and voiding; by incident creation and closure; by audit reporting; by revalidation opening, completion, and abandonment; and by any PHA study status change. Posture gates work: a `FROZEN` unit refuses new MOC creation and startup authorization, and a unit that is `RESTRICTED` or `FROZEN` refuses MOC submission — the specific rejections appear with each workflow in §3.

### 2.11. Hierarchical Consistency, Cascades, and Compensating Actions

The system maintains consistency across aggregate boundaries automatically. When a child resource resolves — an action item verified, a revalidation completed, a corrective action closed — the parent that was waiting on it is advanced, decremented, or restored without a separate client call: verification of a PSSR punch item decrements the review's open punch count, verification of a corrective action closes its audit finding, and verification of a revert item closes its expired MOC. Cascades run in the other direction as well: reporting an audit spawns findings and corrective actions, closing a severe incident forces a PHA revalidation, and the clock sweep expires temporary MOCs. Every such reconciliation mutates the affected resource, refreshing `updated_at` and incrementing `version` where the resource carries those fields.

Three compensating invariants are contractual. Abandoning a PHA revalidation restores the study to the status it held before revalidation began while leaving its validation schedule untouched. Denying an extension request leaves the MOC's dates and extension counts exactly as they were. And verifying then later reopening an action item conserves the unit's open-action count across the pair — what verify removes, reopen restores.

## 3. Business Logic & Workflows

### 3.1. Program Foundations: Plant Units and the Personnel Registry

Everything in the program hangs off a **PlantUnit**. A `PsmAdmin` registers a unit with a display `name`, a `unit_code` that must be unique across all units (`ERR_UNIT_CODE_EXISTS` on collision), and a `pha_cycle_months` revalidation cycle expressed as an integer from 12 to 60 months. Four temporary-change limits and one training gate may be supplied at creation or left to their defaults: `temp_moc_max_days` (the maximum initial duration of a temporary MOC, 180 days by default), `max_extensions` (the maximum number of approved extensions per temporary MOC, 2 by default), `extension_max_days` (the maximum size of a single extension request, 90 days by default), `total_temp_cap_days` (a hard lifetime cap — a temporary MOC's end date may never pass its start date by more than this, 360 days by default), and `training_coverage_threshold_pct` (the minimum training coverage required before implementation can be declared, 100.00 by default). A freshly created unit starts with `psm_posture` `NORMAL`, an `open_action_count` and `overdue_action_count` of zero, and a `process_safety_index` of zero. Updating a unit's configuration — including changing `pha_cycle_months` — recomputes its PHA study's due dates and its index and posture, and increments the unit's `version`. Reading a unit always returns freshly computed counts, index, and posture.

The personnel registry is likewise administered by `PsmAdmin`. Each `Personnel` record carries a `full_name`, an `employee_ref` unique across all personnel (`ERR_EMPLOYEE_REF_EXISTS`), a `qualifications` list (defaulting to empty) drawn from `MECHANICAL`, `CHEMICAL`, `ELECTRICAL`, `PROCESS`, `HAZOP_LEADER`, and `PSSR_CERTIFIED`, and an `active` flag defaulting to true. Inactive personnel cannot be assigned new work: assigning an action item, a training seat, or a revalidation leadership to a person who is not `active`, or to one lacking a required qualification, is rejected with `ERR_QUALIFICATION_MISSING`. Every person's workload is traceable — the API lists the MOCs a person requested or approved, the review rounds they submitted, the PSSRs and PHA revalidations and audits they lead, the investigations they own, the action items assigned to them, the evidence they uploaded, and their training assignments.

### 3.2. MOC Intake: Drafting, Classification, and Screening Risk

A `Requester` initiates a change by creating a **MocRequest** under a unit, supplying a `title`, a `description`, and a `discipline` of `MECHANICAL`, `CHEMICAL`, `ELECTRICAL`, or `PROCESS` — the discipline later drives reviewer qualification. The new MOC is stamped with the creating user as its `requester_id` and with the owning unit from the creation path as its `unit_id`; it starts in `DRAFT` status at `version` 1, with `change_class` still unset and `review_round` at zero. If the unit's posture is `FROZEN`, creation is refused with `ERR_UNIT_POSTURE_FROZEN`. A draft that goes nowhere may be withdrawn: the requester (and only the requester — anyone else draws `ERR_NOT_RESOURCE_OWNER`) may withdraw a MOC from `DRAFT`, and equally from `CLASSIFIED`, moving it to the terminal `WITHDRAWN` status; attempting withdrawal from any later state is rejected with `ERR_MOC_INVALID_STATE`.

Classification is a `PsmManager` act that turns a `DRAFT` MOC into a `CLASSIFIED` one (any other from-state yields `ERR_MOC_INVALID_STATE`). The manager supplies the `change_class` — `REPLACEMENT_IN_KIND`, `TEMPORARY`, or `PERMANENT` — along with `screening_severity` and `screening_likelihood`, each an integer from 1 to 5, and may optionally pass `requires_pssr_override`. On classification the system stores those inputs and computes the provisional `screening_risk_score`: severity multiplied by likelihood multiplied by a change-class multiplier — 1.0 for `PERMANENT`, 1.2 for `TEMPORARY`, and 0.5 for `REPLACEMENT_IN_KIND` — rounded half-up to two decimal places. The `risk_rank` is mapped from that score: below 5 is `LOW`; at least 5 but below 12 is `MEDIUM`; at least 12 but below 20 is `HIGH`; and 20 or higher is `CRITICAL`. Band boundaries are inclusive on the lower side, so a score of exactly 12.00 is `HIGH` and exactly 20.00 is `CRITICAL`. The screening variant is deliberately provisional — it has no detection factor, no posture branch, and no cap — and will diverge from the definitive score computed at review time even on identical severity and likelihood.

Classification also fixes the PSSR obligation: `requires_pssr` is set to false only when the class is `REPLACEMENT_IN_KIND` and `requires_pssr_override` is not true; in every other case it is true. When the class is `TEMPORARY`, the request must additionally carry `temporary_start_date` and `temporary_duration_days`; a missing date or a malformed value is a malformed request (`ERR_INVALID_REQUEST`), and a duration below 1 day or beyond the unit's `temp_moc_max_days` is rejected with `ERR_TEMP_DURATION_EXCEEDS_MAX`. For a temporary MOC the system derives `temporary_end_date` as the start date plus the duration — and, more generally throughout the MOC's life, the end date is always the start date plus `temporary_duration_days` plus `total_approved_extension_days`, with `extension_count` and `total_approved_extension_days` both starting at zero.

### 3.3. Technical Review and the Revision Cycle

Submitting a `CLASSIFIED` MOC is the requester's own action; any other user is turned away with `ERR_NOT_RESOURCE_OWNER`, and a MOC in any other state draws `ERR_MOC_INVALID_STATE`. Two environmental gates guard submission, in the pipeline order of §2.9: the unit's posture must be neither `RESTRICTED` (`ERR_UNIT_POSTURE_RESTRICTED`) nor `FROZEN` (`ERR_UNIT_POSTURE_FROZEN`), and the unit must hold a PHA study in `CURRENT` or `DUE_SOON` status — a unit with no study, or a study that is `OVERDUE`, `REVALIDATION_REQUIRED`, or `IN_REVALIDATION`, blocks submission with `ERR_PHA_NOT_CURRENT`.

From there the path forks on class. A `REPLACEMENT_IN_KIND` change bypasses technical review entirely, moving `CLASSIFIED` → `APPROVAL_PENDING` in one step. Any other class moves `CLASSIFIED` → `TECHNICAL_REVIEW`: `review_round` increments to 1 and a **TechnicalReview** is created in `OPEN` status with `round_number` equal to the MOC's `review_round`, its `moc_id` pointing back to the MOC, and its `reviewer_id` unset until a verdict is filed. The review rounds of a MOC are listed in ascending `round_number` order.

A `TechnicalReviewer` files a verdict on an `OPEN` review (`ERR_REVIEW_INVALID_STATE` otherwise) whose MOC sits in `TECHNICAL_REVIEW` (`ERR_MOC_INVALID_STATE` otherwise). Three guards apply before the verdict's content is even considered: the reviewer must hold a qualification matching the MOC's `discipline` (`ERR_QUALIFICATION_MISSING`), and the reviewer must not be the MOC's requester (`ERR_SOD_REVIEWER_IS_REQUESTER`). The verdict payload carries a four-part checklist — `design_basis_ok`, `codes_standards_ok`, `relief_systems_ok`, and `materials_compat_ok` — plus `severity_score`, `likelihood_score`, and `detection_score` (each 1 to 5, where a detection score of 1 means easily detected and 5 means undetectable), the `verdict` itself (`ACCEPT` or `RETURN`), and optional `notes`.

The two verdicts diverge deliberately. An `ACCEPT` verdict requires all four checklist booleans to be true; any false value is rejected with `ERR_REVIEW_CHECKLIST_INCOMPLETE`. A `RETURN` verdict carries no checklist requirement and loops the MOC from `TECHNICAL_REVIEW` to `RETURNED_FOR_REVISION`. Both outcomes move the review itself from `OPEN` to `SUBMITTED`, record the filing user as `reviewer_id`, persist the payload fields, and compute the definitive risk picture on the MOC: a base value is formed from `severity_score` times `likelihood_score`, capped at 25 — a product above 25 yields a base of 25; a detection factor is derived as one plus one quarter of (detection score minus one), so detection 1 yields 1.00 and each further point adds 0.25 up to 2.00 at detection 5; and a posture factor of 1.25 applies when the unit's `process_safety_index` is 70 or higher at verdict time, otherwise 1.0. The `definitive_risk_score` is the base multiplied by the same change-class multiplier used at screening, multiplied by the detection factor, multiplied by the posture factor, rounded half-up to two decimal places, and the `risk_rank` is recomputed from it under the same band mapping as screening.

A returned MOC is not dead — it enters a revision cycle that may repeat without bound. The requester resubmits from `RETURNED_FOR_REVISION` (any other state: `ERR_MOC_INVALID_STATE`; any other user: `ERR_NOT_RESOURCE_OWNER`), which moves the MOC back to `TECHNICAL_REVIEW`, increments `review_round` once more, and creates a fresh `OPEN` review for the new round.

### 3.4. Approval, Procedure Updates, and Training Readiness

An `OpsApprover` decides an `APPROVAL_PENDING` MOC. Approval requires the approver to be someone other than the requester (`ERR_SOD_APPROVER_IS_REQUESTER`); on success the approver is stamped as `approver_id` (null until this moment) and the MOC moves to `APPROVED_IMPLEMENTATION`. The approval payload may carry an optional `conditions` array: each element spawns a new action item in `OPEN` status with `source_type` `MOC_CONDITION` sourced to this MOC, due per the priority SLA of §3.9, and the unit's `open_action_count` increases by the number spawned with index and posture recomputed. Rejection is the sibling branch — same from-state `APPROVAL_PENDING`, same role — and moves the MOC to the terminal `REJECTED` status; either way the MOC's `version` increments.

An approved change almost always drags paperwork. A `TrainingCoordinator` registers a **ProcedureUpdate** under the MOC with a controlled `document_ref`; it begins in `DRAFT`. Publication is gated three ways: the update must be `DRAFT` (`ERR_PROCEDURE_UPDATE_INVALID_STATE`), its MOC must be in `APPROVED_IMPLEMENTATION` or `IMPLEMENTED_PSSR_PENDING` (`ERR_MOC_INVALID_STATE`), and at least one **TrainingAssignment** must exist for it (`ERR_NO_TRAINING_ASSIGNED`). A successful publish stamps `published_at` with the clock date and moves the update to `PUBLISHED`. Assignments are created by the coordinator with a `personnel_id`, are unique per (`procedure_update_id`, `personnel_id`) pair (`ERR_DUPLICATE_TRAINING_ASSIGNMENT`), require the trainee to be active personnel (`ERR_QUALIFICATION_MISSING`), and begin as `ASSIGNED`. The trainee — any entity-backed role whose `X-User-ID` matches the assignment's `personnel_id`, anyone else drawing `ERR_NOT_RESOURCE_OWNER` — completes it from `ASSIGNED` (`ERR_TRAINING_ASSIGNMENT_INVALID_STATE` otherwise), which stamps `completed_at` and moves it to `COMPLETED`.

These threads converge in the MOC's `training_coverage_pct`. Whenever an update is created or published, whenever an assignment is created or completed, and whenever the MOC is read, coverage is recomputed as follows: for each linked update in `PUBLISHED` status, a per-update coverage is one hundred times the update's completed assignments divided by its total assignments, rounded half-up to two decimal places; the MOC's `training_coverage_pct` is then the arithmetic mean of those per-update values across all published updates, itself rounded half-up to two decimal places. `DRAFT` updates are excluded from both the numerator and the denominator of the average, and a published update with zero assignments cannot exist because publication requires at least one. The pinned rounding order — round each update first, then average and round again — is the conforming behavior; aggregating all completions over all assignments before a single rounding produces a different, non-conforming number.

With procedures published and people trained, the requester marks implementation complete from `APPROVED_IMPLEMENTATION` (other states: `ERR_MOC_INVALID_STATE`; other users: `ERR_NOT_RESOURCE_OWNER`). Two completion gates apply: at least one linked procedure update must be `PUBLISHED` (`ERR_PROCEDURES_NOT_PUBLISHED`), and `training_coverage_pct` must be at least the unit's `training_coverage_threshold_pct` (`ERR_TRAINING_COVERAGE_INSUFFICIENT`). Success stamps `implemented_at` with the clock date and advances the MOC to `IMPLEMENTED_PSSR_PENDING`.

### 3.5. Pre-Startup Safety Review and Startup Authorization

When `requires_pssr` is true, a **Pssr** gates startup. A `PssrLead` — who must hold the `PSSR_CERTIFIED` qualification (`ERR_QUALIFICATION_MISSING`) — creates the review against a MOC in `APPROVED_IMPLEMENTATION` or `IMPLEMENTED_PSSR_PENDING` (`ERR_MOC_INVALID_STATE` otherwise), declaring `field_window_start` and `field_window_end` for the field verification window and, per §2.7, the mandatory `expected_moc_version`. The creator is recorded as `lead_id`. Creation legitimately supersedes any existing `PLANNED` PSSR on the same MOC, moving the older one to `VOID`, and the MOC's `version` increments by one; a request whose `expected_moc_version` no longer matches is rejected with `ERR_STALE_MOC_VERSION` before any of this happens, so a supersede decision is never based on a stale view. The new review's window is also checked for overlap against every PSSR in `PLANNED`, `IN_FIELD`, or `PUNCH_LIST` on the same unit — across any MOC — excluding the same-MOC sibling being superseded: windows are treated as half-open intervals from start inclusive to end exclusive, so two reviews whose windows merely touch (one starting exactly when the other ends) do not conflict, while a true intersection is rejected with `ERR_PSSR_WINDOW_OVERLAP`. The review begins in `PLANNED` with `punch_open_count` at zero.

Once the logical clock falls inside the declared window — from `field_window_start` through `field_window_end`, both bounds inclusive, otherwise `ERR_FIELDWORK_WINDOW_NOT_ACTIVE` — the lead (and only the lead, `ERR_NOT_RESOURCE_OWNER`) begins fieldwork, moving `PLANNED` → `IN_FIELD`. During fieldwork the lead — again, only the recorded `lead_id`, anyone else drawing `ERR_NOT_RESOURCE_OWNER` — raises punch items, each with a `title`, a `priority`, and an `assignee_id`; punch items may be raised only while the review is `IN_FIELD` (`ERR_PSSR_INVALID_STATE` otherwise), and every punch item spawns an action item in `OPEN` status with `source_type` `PSSR` sourced to this review and due per its priority SLA, increments the review's `punch_open_count` and the unit's `open_action_count`, and recomputes the unit index. The first punch item moves the review from `IN_FIELD` to `PUNCH_LIST`.

Approval and rejection are likewise the recorded lead's sibling decisions — a different user is rejected with `ERR_NOT_RESOURCE_OWNER` — both available from either `IN_FIELD` or `PUNCH_LIST` (`ERR_PSSR_INVALID_STATE` from anywhere else). Approval carries three further gates: the lead must not be the MOC's requester (`ERR_SOD_PSSR_LEAD_IS_REQUESTER`), `punch_open_count` must be zero (`ERR_PSSR_OPEN_PUNCH_ITEMS`), and the MOC must currently stand in `IMPLEMENTED_PSSR_PENDING` (`ERR_MOC_INVALID_STATE`). An approved review stamps `approved_at` and lands in `APPROVED`. Rejection needs no such gates beyond state and ownership, lands in `REJECTED`, and pushes the MOC backward from `IMPLEMENTED_PSSR_PENDING` to `APPROVED_IMPLEMENTATION` — the change must re-clear mark-implemented before startup can be sought again.

Startup authorization itself is a `PsmManager` act on a MOC in `IMPLEMENTED_PSSR_PENDING` (`ERR_MOC_INVALID_STATE`). The unit must not be `FROZEN` (`ERR_UNIT_POSTURE_FROZEN`); when `requires_pssr` holds, a linked PSSR in `APPROVED` status must exist (`ERR_PSSR_NOT_APPROVED`); and no open-class action item of priority `P1` may remain that is sourced either as `MOC_CONDITION` to this MOC or as `PSSR` to any of this MOC's reviews (`ERR_OPEN_P1_ACTION_ITEMS`). Passing all three moves the MOC to `STARTUP_AUTHORIZED`.

### 3.6. Life in Service: Activation, Temporary Expiry, and Extensions

An `OpsApprover` places a `STARTUP_AUTHORIZED` MOC in service, moving it to `IN_SERVICE`. From there, endings differ by class. A `PsmManager` may close a `PERMANENT` or `REPLACEMENT_IN_KIND` MOC from `IN_SERVICE`, provided no open-class action item with `source_type` `MOC_CONDITION` remains sourced to it (`ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE`); closure stamps `closed_at` and lands in `CLOSED`. A `TEMPORARY` MOC never closes this way — it closes only through the revert path below.

The clock sweep polices temporary life. When the logical clock advances strictly beyond a temporary in-service MOC's `temporary_end_date` — a MOC whose end date is exactly today is not yet expired — the sweep moves it from `IN_SERVICE` to `EXPIRED_REVERT_REQUIRED`, spawns a revert action item with `source_type` `REVERT` sourced to the MOC, priority `P1`, assigned to the MOC's `requester_id`, due thirty days after the clock date, and the unit's `open_action_count` and index are updated accordingly. When that revert item is later verified closed, the MOC bubbles up from `EXPIRED_REVERT_REQUIRED` to `CLOSED` with `closed_at` stamped — no separate MOC-level call is needed.

While a temporary MOC is `IN_SERVICE`, its requester may seek more time by creating an **ExtensionRequest** carrying `requested_days` and the mandatory `expected_moc_version` of §2.7. Extensions are a temporary-only construct — requesting one on a non-`TEMPORARY` MOC is rejected with `ERR_MOC_NOT_TEMPORARY`, and a temporary MOC not in service rejects with `ERR_MOC_INVALID_STATE`; only the requester may ask (`ERR_NOT_RESOURCE_OWNER`). Creation supersedes any existing `PENDING` extension on the same MOC, moving the older one to `VOID`, and increments the MOC's `version`; the new request lands in `PENDING` with `decided_by` unset. Three caps guard creation and are evaluated in a pinned order: first the count — if the MOC's `extension_count` has already reached the unit's `max_extensions`, the rejection is `ERR_MAX_EXTENSIONS_REACHED`; second the per-extension size — `requested_days` (at least 1) must not exceed the unit's `extension_max_days`, else `ERR_TEMP_EXTENSION_EXCEEDS_MAX_DAYS`; third the lifetime cap — the candidate end date (the current `temporary_end_date` plus `requested_days`) must not fall beyond `temporary_start_date` plus the unit's `total_temp_cap_days`, else `ERR_TEMP_TOTAL_CAP_EXCEEDED`.

A `PsmManager` decides a pending request (`ERR_EXTENSION_NOT_PENDING` from any other state), and is recorded as `decided_by`. Approval adds `requested_days` to `total_approved_extension_days`, pushes `temporary_end_date` out by the same number of days, increments `extension_count` by one, and increments the MOC's `version`, landing the request in `APPROVED`. Denial lands in `DENIED` and changes none of the MOC's dates or counts — the extension budget is left exactly as it was, a deliberate compensating invariant.

### 3.7. PHA Studies, Revalidation, and Incident Feedback

Each unit carries at most one **PhaStudy** — a second creation attempt is rejected with `ERR_PHA_STUDY_EXISTS`. A `PsmManager` creates it with a `method` of `HAZOP`, `WHAT_IF`, or `CHECKLIST` and an `initial_validated_at` date; the study's `last_validated_at` is set from that input, its status starts `CURRENT`, its `revalidation_count` is zero, and its three due dates are computed. The `nominal_next_due` is `last_validated_at` plus `pha_cycle_months` converted at thirty days per month — pure calendar arithmetic that ignores incidents. The `risk_accelerated_due` compresses the cycle when severe incidents have landed: letting N be the number of the unit's `CLOSED` incident investigations with `severity_class` `HIGH` or `CATASTROPHIC` whose `occurred_at` is on or after `last_validated_at`, the cycle length in days is multiplied by the larger of 0.25 and (one minus one tenth of N), rounded down to a whole number of days, and added to `last_validated_at` — so with no qualifying incidents the accelerated date equals the nominal, each qualifying incident strips a tenth of the cycle, and the multiplier never falls below one quarter. The `effective_next_due` is the earlier of the nominal and risk-accelerated dates. All three dues are recomputed at study creation, at revalidation completion, and on unit configuration changes to `pha_cycle_months`.

The clock sweep ages the study. When the clock reaches sixty days before `effective_next_due` — that is, the clock is on or after `effective_next_due` minus sixty days and on or before `effective_next_due` itself — a `CURRENT` study becomes `DUE_SOON`. Once the clock passes `effective_next_due`, a study in `CURRENT` or `DUE_SOON` becomes `OVERDUE`, and the unit index picks up the twenty-five-point overdue-study contribution.

Incidents feed the same machinery. A `PsmManager` opens an **IncidentInvestigation** with a `title`, a `severity_class` of `MINOR`, `SERIOUS`, `HIGH`, or `CATASTROPHIC`, the `occurred_at` date, and an `investigator_id` designating the only person who may run its analysis; it begins `OPEN`, and while a `HIGH` or `CATASTROPHIC` investigation remains unclosed it contributes ten points to the unit index. The designated investigator (anyone else: `ERR_NOT_RESOURCE_OWNER`) begins root-cause analysis from `OPEN` (`ERR_INCIDENT_INVALID_STATE`), moving to `ROOT_CAUSE_ANALYSIS`, and later submits findings from that state, each element of `findings` spawning an action item in `OPEN` status with `source_type` `INCIDENT` sourced to the investigation and due per its priority SLA, with unit counts and index updated; the investigation lands in `FINDINGS_SUBMITTED`. A `PsmManager` closes it from there, which sets `feeds_pha` to true exactly when `severity_class` is `HIGH` or `CATASTROPHIC`. When `feeds_pha` is true and the unit's study stands in `CURRENT`, `DUE_SOON`, or `OVERDUE`, closure forces the study into `REVALIDATION_REQUIRED` and spawns a `P1` action item with `source_type` `PHA_REVALIDATION` sourced to the study, assigned to the investigation's `investigator_id`, due thirty days after the clock date; the unit index shifts accordingly — a study that was `OVERDUE` stops contributing its twenty-five points and instead contributes twenty for the forced revalidation. Closing a `MINOR` or `SERIOUS` investigation sets no PHA flag and disturbs no study.

A `PsmManager` opens a revalidation from `DUE_SOON`, `OVERDUE`, or `REVALIDATION_REQUIRED` (`ERR_PHA_STUDY_INVALID_STATE` from anywhere else), naming a `leader_id` who must be active personnel holding `HAZOP_LEADER` (`ERR_QUALIFICATION_MISSING`). The study captures its current status into `status_before_revalidation`, moves to `IN_REVALIDATION`, and a **PhaRevalidation** is created in `OPEN` status bound to the study by `study_id`, with the unit index recomputed. Completion requires the revalidation to be `OPEN` (`ERR_REVALIDATION_INVALID_STATE`) and a `findings_summary` to be supplied; it resets `last_validated_at` to the clock date, increments `revalidation_count` by one, recomputes all three dues, returns the study to `CURRENT`, moves the revalidation to `COMPLETED`, and spawns one action item per element of the optional `findings` array — each carrying a `title`, a `priority` of `P1`, `P2`, or `P3`, and an `assignee_id` — with `source_type` `PHA_REVALIDATION` sourced to the revalidation itself, due per the SLA, with unit counts and index updated. Abandonment, the sibling exit from `OPEN`, moves the revalidation to `ABANDONED` and restores the study to whatever `status_before_revalidation` captured — back to `DUE_SOON`, to `OVERDUE`, or to `REVALIDATION_REQUIRED` as the case may be — while leaving `last_validated_at`, all three due dates, and `revalidation_count` unchanged: an abandoned attempt leaves the validation schedule exactly as it found it.

### 3.8. Audits, Findings, and Corrective Actions

A `PsmManager` schedules an **Audit** for a unit with a `title`, a `lead_auditor_id` designating the only person who may run its fieldwork and report, and a closed `field_window_start`-to-`field_window_end` window. Scheduling enforces a separation rule: the new window must stand at least fourteen days clear of every other audit in `SCHEDULED`, `FIELDWORK`, or `REPORTED` on the same unit — a window that comes within fourteen days of a neighbor on either side is rejected with `ERR_AUDIT_WINDOW_CONFLICT`. The audit begins `SCHEDULED` with `open_finding_count` at zero.

When the logical clock sits inside the window — both bounds inclusive, else `ERR_FIELDWORK_WINDOW_NOT_ACTIVE` — the lead auditor (only the lead, `ERR_NOT_RESOURCE_OWNER`; from `SCHEDULED` only, `ERR_AUDIT_INVALID_STATE`) begins fieldwork, moving to `FIELDWORK`. Reporting, again the lead alone and again state-guarded, carries a `findings` array whose elements each supply a `title`, a `severity`, and an `assignee_id`. For each element the system creates an **AuditFinding** (bound by `audit_id`) that is created in `OPEN` and immediately moved to `ACTION_ASSIGNED` within the same request, spawns a corrective action item in `OPEN` with `source_type` `AUDIT` sourced to the finding and priority mapped from severity — `MAJOR_NC` to `P1`, `MINOR_NC` to `P2`, `OBSERVATION` to `P3` — and sets the finding's `corrective_action_id` to the spawned item. The audit's `open_finding_count` is set to the number of findings reported, the unit's `open_action_count` grows by the same amount, the index is recomputed, and the audit lands in `REPORTED`.

Resolution flows back up the chain. When a corrective action item is verified closed, its finding moves from `ACTION_ASSIGNED` to `CLOSED` and the audit's `open_finding_count` decrements; if that item is later reopened, the finding returns from `CLOSED` to `ACTION_ASSIGNED` and the count increments again. A `PsmManager` closes the audit from `REPORTED` (`ERR_AUDIT_INVALID_STATE` otherwise) only when `open_finding_count` has reached zero (`ERR_AUDIT_OPEN_FINDINGS`), landing it in `CLOSED`.

### 3.9. Action Items, Evidence, and the Verification Loop

The **ActionItem** is the program's unit of tracked work. Beyond the spawned sources seen above, a `PsmManager` may raise one manually under a unit with a `title`, a `priority` of `P1`, `P2`, or `P3`, and an `assignee_id` naming active personnel (`ERR_QUALIFICATION_MISSING` for an inactive assignee, `ERR_PERSONNEL_NOT_FOUND` for an unknown one); a manual item carries `source_type` `MANUAL` and a null `source_id`. Every item's `due_date` is its creation clock date plus an SLA of thirty days for `P1`, ninety for `P2`, or one hundred eighty for `P3` — except that a creation path accepting a `due_in_days` override uses that many days instead. An item counts as overdue when its `due_date` is strictly before the current clock; an item due exactly today is not overdue. The unit's `open_action_count` tallies its items in `OPEN`, `IN_PROGRESS`, `SUBMITTED_FOR_VERIFICATION`, or `REJECTED`, and `overdue_action_count` is the overdue subset of those; each creation increments the count and recomputes the unit index. The polymorphic `source_id` resolves by `source_type`: the MOC's id for `MOC_CONDITION` and `REVERT`, the review's id for `PSSR`, the investigation's id for `INCIDENT`, the finding's id for `AUDIT`, the study's id for a forced-revalidation `PHA_REVALIDATION` item, and the revalidation's id for a completion-findings `PHA_REVALIDATION` item. A unit's action-item list may be filtered by `status` and `priority`.

Work proceeds through a guarded loop. The assignee — whose `X-User-ID` must match `assignee_id` (`ERR_NOT_RESOURCE_OWNER`) and who acts under one of the six entity-backed roles — starts work from `OPEN`, and equally restarts from `REJECTED` after a verification rejection, landing in `IN_PROGRESS` (`ERR_ACTION_ITEM_INVALID_STATE` from any other state). Submitting for verification requires `IN_PROGRESS` and at least one attached piece of evidence — `evidence_count` of zero draws `ERR_NO_EVIDENCE_ATTACHED` — and stamps the submitter as `completer_id`, moving to `SUBMITTED_FOR_VERIFICATION`. Evidence is gathered through an append-only **EvidenceItem** per upload: the assignee supplies a `file_ref` and a `description`, the uploader is recorded as `uploaded_by`, the item's `action_item_id` binds it to its parent, and each upload increments the item's `evidence_count` from its initial zero; uploads are accepted only while the item is `OPEN`, `IN_PROGRESS`, or `REJECTED`.

Verification belongs to a `PsmManager` acting on a `SUBMITTED_FOR_VERIFICATION` item, and the verifier must not be the completer (`ERR_SOD_VERIFIER_IS_COMPLETER`). A verified item lands in the terminal `VERIFIED_CLOSED` status with `verifier_id` recorded, the unit's `open_action_count` decrements, the index is recomputed, and the source bubble-ups fire: a `PSSR` item decrements its review's `punch_open_count`; an `AUDIT` item closes its finding and decrements the audit's `open_finding_count`; a `REVERT` item closes its expired MOC as described in §3.6; `PHA_REVALIDATION`, `INCIDENT`, `MOC_CONDITION`, and `MANUAL` items have no parent effect. The manager may instead reject the verification, returning the item to `REJECTED` with `completer_id` retained for audit and no count changes — the assignee then restarts the loop. Reopening is verification's compensating action: a manager moves a `VERIFIED_CLOSED` item back to `IN_PROGRESS` (supplying a `reason`), `reopen_count` — which starts at zero — increments by one, the open count and index move back up, and the bubble-ups run in reverse — an audit finding returns to `ACTION_ASSIGNED` with the audit's count restored, and a PSSR item's review regains its punch count — so the unit's open count is conserved across any verify-then-reopen pair. Finally, a manager may void an item from `OPEN`, `IN_PROGRESS`, or `REJECTED`, landing it in the terminal `VOID` status with the open count decremented and the index recomputed.

## 4. Endpoint Definitions

Operations that create a new resource — a unit, a person, a MOC, a study, a revalidation, a PSSR, an action item, an evidence item, an investigation, an audit, a procedure update, a training assignment, or an extension request — return `201 Created`. Operations that modify an existing resource, including all state-transition actions and the administrative clock set, return `200 OK`. All endpoints are mounted under the `/psm` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/psm/_clock/set_current_utc` | Set the server's logical clock; runs the expiry/overdue sweep | PsmAdmin |
| POST | `/psm/units` | Create a PlantUnit (config entity) | PsmAdmin |
| GET | `/psm/units` | List PlantUnits (paginated) | Any |
| GET | `/psm/units/{id}` | Get a PlantUnit with fresh computed counts/index/posture | Any |
| PATCH | `/psm/units/{id}` | Update unit config; recomputes PHA dues and posture | PsmAdmin |
| POST | `/psm/personnel` | Create a Personnel record | PsmAdmin |
| GET | `/psm/personnel` | List Personnel (paginated) | Any |
| GET | `/psm/personnel/{id}` | Get a Personnel record | Any |
| POST | `/psm/units/{unitId}/moc-requests` | Create a MOC in DRAFT; requester is the caller; blocked when unit FROZEN | Requester |
| GET | `/psm/moc-requests/{id}` | Get a MOC | Any |
| GET | `/psm/units/{id}/moc-requests` | List MOCs of a unit | Any |
| GET | `/psm/personnel/{id}/moc-requests` | List MOCs requested or approved by a person | Any |
| POST | `/psm/moc-requests/{id}/classify` | Classify a DRAFT MOC; computes screening risk and rank; sets PSSR obligation | PsmManager |
| POST | `/psm/moc-requests/{id}/submit` | Submit a classified MOC; RIK bypasses to approval, others enter technical review | Requester |
| POST | `/psm/moc-requests/{id}/resubmit` | Resubmit a returned MOC; opens a fresh review round | Requester |
| POST | `/psm/moc-requests/{id}/approve` | Approve for implementation; optional conditions spawn action items | OpsApprover |
| POST | `/psm/moc-requests/{id}/reject` | Reject an approval-pending MOC (terminal) | OpsApprover |
| POST | `/psm/moc-requests/{id}/withdraw` | Withdraw a DRAFT or CLASSIFIED MOC (terminal); owner only | Requester |
| POST | `/psm/moc-requests/{id}/mark-implemented` | Mark implementation complete; requires published procedures and sufficient coverage | Requester |
| POST | `/psm/moc-requests/{id}/authorize-startup` | Authorize startup; PSSR gate, open-P1 gate, posture gate | PsmManager |
| POST | `/psm/moc-requests/{id}/activate` | Place a startup-authorized MOC in service | OpsApprover |
| POST | `/psm/moc-requests/{id}/close` | Close a PERMANENT or RIK MOC in service | PsmManager |
| GET | `/psm/moc-requests/{id}/technical-reviews` | List review rounds of a MOC (ascending round_number) | Any |
| GET | `/psm/personnel/{id}/technical-reviews` | List reviews submitted by a person | Any |
| POST | `/psm/technical-reviews/{id}/submit-verdict` | Submit review verdict; computes definitive risk; ACCEPT requires full checklist | TechnicalReviewer |
| POST | `/psm/units/{unitId}/pha-studies` | Create the unit's PHA study (at most one per unit) | PsmManager |
| GET | `/psm/units/{id}/pha-studies` | List PHA studies of a unit (0 or 1 element) | Any |
| GET | `/psm/pha-studies/{id}` | Get a PHA study | Any |
| POST | `/psm/pha-studies/{id}/open-revalidation` | Open a revalidation; leader must hold HAZOP_LEADER | PsmManager |
| GET | `/psm/pha-studies/{id}/revalidations` | List revalidations of a study | Any |
| GET | `/psm/personnel/{id}/pha-revalidations` | List revalidations led by a person | Any |
| POST | `/psm/pha-revalidations/{id}/complete` | Complete a revalidation; resets the study schedule; findings spawn action items | PsmManager |
| POST | `/psm/pha-revalidations/{id}/abandon` | Abandon a revalidation; study status restored, schedule unchanged | PsmManager |
| POST | `/psm/moc-requests/{id}/pssrs` | Create a PSSR; supersedes a PLANNED sibling; OCC-guarded; window overlap check | PssrLead |
| GET | `/psm/moc-requests/{id}/pssrs` | List PSSRs of a MOC | Any |
| GET | `/psm/personnel/{id}/pssrs` | List PSSRs led by a person | Any |
| GET | `/psm/pssrs/{id}` | Get a PSSR | Any |
| POST | `/psm/pssrs/{id}/begin-fieldwork` | Begin field verification inside the declared window | PssrLead |
| POST | `/psm/pssrs/{id}/punch-items` | Raise a punch item; spawns a PSSR action item; first punch moves to PUNCH_LIST | PssrLead |
| POST | `/psm/pssrs/{id}/approve` | Approve a PSSR; requires zero open punch items and MOC awaiting PSSR | PssrLead |
| POST | `/psm/pssrs/{id}/reject` | Reject a PSSR; MOC falls back to approved-implementation | PssrLead |
| POST | `/psm/units/{unitId}/action-items` | Create a manual action item | PsmManager |
| GET | `/psm/units/{id}/action-items` | List action items of a unit; filterable by status and priority | Any |
| GET | `/psm/personnel/{id}/action-items` | List action items assigned to a person | Any |
| GET | `/psm/action-items/{id}` | Get an action item | Any |
| POST | `/psm/action-items/{id}/start` | Assignee starts (or restarts after rejection) work | Requester, TechnicalReviewer, OpsApprover, PssrLead, Investigator, Auditor |
| POST | `/psm/action-items/{id}/submit-verification` | Assignee submits for verification; requires evidence | Requester, TechnicalReviewer, OpsApprover, PssrLead, Investigator, Auditor |
| POST | `/psm/action-items/{id}/verify` | Verify closure; verifier differs from completer; bubble-ups fire | PsmManager |
| POST | `/psm/action-items/{id}/reject-verification` | Reject closure; item returns toward the assignee | PsmManager |
| POST | `/psm/action-items/{id}/reopen` | Reopen a verified-closed item (compensating action of verify) | PsmManager |
| POST | `/psm/action-items/{id}/void` | Void an open-class item (terminal) | PsmManager |
| POST | `/psm/action-items/{id}/evidence-items` | Attach closure evidence (assignee only, item open-class) | Requester, TechnicalReviewer, OpsApprover, PssrLead, Investigator, Auditor |
| GET | `/psm/action-items/{id}/evidence-items` | List evidence of an action item | Any |
| GET | `/psm/personnel/{id}/evidence-items` | List evidence uploaded by a person | Any |
| GET | `/psm/action-items/{id}/audit-findings` | List audit findings whose corrective action is this item (0 or 1) | Any |
| POST | `/psm/units/{unitId}/incident-investigations` | Open an incident investigation | PsmManager |
| GET | `/psm/units/{id}/incident-investigations` | List investigations of a unit | Any |
| GET | `/psm/incident-investigations/{id}` | Get an investigation | Any |
| GET | `/psm/personnel/{id}/incident-investigations` | List investigations owned by a person | Any |
| POST | `/psm/incident-investigations/{id}/begin-rca` | Begin root-cause analysis (assigned investigator only) | Investigator |
| POST | `/psm/incident-investigations/{id}/submit-findings` | Submit findings; each spawns an INCIDENT action item | Investigator |
| POST | `/psm/incident-investigations/{id}/close` | Close investigation; HIGH/CATASTROPHIC forces PHA revalidation cascade | PsmManager |
| POST | `/psm/units/{unitId}/audits` | Schedule an audit; 14-day buffered separation on the same unit | PsmManager |
| GET | `/psm/units/{id}/audits` | List audits of a unit | Any |
| GET | `/psm/audits/{id}` | Get an audit | Any |
| GET | `/psm/personnel/{id}/audits` | List audits led by a person | Any |
| GET | `/psm/audits/{id}/findings` | List findings of an audit | Any |
| POST | `/psm/audits/{id}/begin-fieldwork` | Begin fieldwork (lead auditor only; clock inside window) | Auditor |
| POST | `/psm/audits/{id}/report` | Report findings; each spawns a corrective action item by severity | Auditor |
| POST | `/psm/audits/{id}/close` | Close audit; requires zero open findings | PsmManager |
| POST | `/psm/moc-requests/{id}/procedure-updates` | Create a procedure update linked to a MOC | TrainingCoordinator |
| GET | `/psm/moc-requests/{id}/procedure-updates` | List procedure updates of a MOC | Any |
| GET | `/psm/procedure-updates/{id}` | Get a procedure update | Any |
| POST | `/psm/procedure-updates/{id}/publish` | Publish; requires the MOC in implementation states and at least one assignment | TrainingCoordinator |
| POST | `/psm/procedure-updates/{id}/training-assignments` | Assign training to a person; unique per update and person | TrainingCoordinator |
| GET | `/psm/procedure-updates/{id}/training-assignments` | List assignments of an update | Any |
| GET | `/psm/personnel/{id}/training-assignments` | List assignments of a person | Any |
| POST | `/psm/training-assignments/{id}/complete` | Trainee completes an assignment | Requester, TechnicalReviewer, OpsApprover, PssrLead, Investigator, Auditor |
| POST | `/psm/moc-requests/{id}/extension-requests` | Request a temporary extension (owner only; OCC-guarded; supersedes a pending sibling) | Requester |
| GET | `/psm/moc-requests/{id}/extension-requests` | List extension requests of a MOC | Any |
| POST | `/psm/extension-requests/{id}/approve` | Approve an extension; end date and counts advance | PsmManager |
| POST | `/psm/extension-requests/{id}/deny` | Deny an extension; MOC dates and counts unchanged | PsmManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the workflow narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_PERSONNEL_NOT_FOUND` | 404 Not Found |
| `ERR_MOC_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_PHA_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_REVALIDATION_NOT_FOUND` | 404 Not Found |
| `ERR_PSSR_NOT_FOUND` | 404 Not Found |
| `ERR_ACTION_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEDURE_UPDATE_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXTENSION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_MOC_VERSION` | 412 Precondition Failed |
| `ERR_MOC_INVALID_STATE` | 409 Conflict |
| `ERR_REVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_PHA_STUDY_INVALID_STATE` | 409 Conflict |
| `ERR_REVALIDATION_INVALID_STATE` | 409 Conflict |
| `ERR_PSSR_INVALID_STATE` | 409 Conflict |
| `ERR_ACTION_ITEM_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_AUDIT_INVALID_STATE` | 409 Conflict |
| `ERR_PROCEDURE_UPDATE_INVALID_STATE` | 409 Conflict |
| `ERR_TRAINING_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_EXTENSION_NOT_PENDING` | 409 Conflict |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_QUALIFICATION_MISSING` | 403 Forbidden |
| `ERR_SOD_REVIEWER_IS_REQUESTER` | 403 Forbidden |
| `ERR_SOD_APPROVER_IS_REQUESTER` | 403 Forbidden |
| `ERR_SOD_PSSR_LEAD_IS_REQUESTER` | 403 Forbidden |
| `ERR_SOD_VERIFIER_IS_COMPLETER` | 403 Forbidden |
| `ERR_UNIT_POSTURE_FROZEN` | 403 Forbidden |
| `ERR_UNIT_POSTURE_RESTRICTED` | 403 Forbidden |
| `ERR_REVIEW_CHECKLIST_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_FIELDWORK_WINDOW_NOT_ACTIVE` | 409 Conflict |
| `ERR_PHA_NOT_CURRENT` | 409 Conflict |
| `ERR_MOC_NOT_TEMPORARY` | 422 Unprocessable Entity |
| `ERR_TEMP_DURATION_EXCEEDS_MAX` | 422 Unprocessable Entity |
| `ERR_MAX_EXTENSIONS_REACHED` | 422 Unprocessable Entity |
| `ERR_TEMP_EXTENSION_EXCEEDS_MAX_DAYS` | 422 Unprocessable Entity |
| `ERR_TEMP_TOTAL_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNIT_CODE_EXISTS` | 409 Conflict |
| `ERR_EMPLOYEE_REF_EXISTS` | 409 Conflict |
| `ERR_PHA_STUDY_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_TRAINING_ASSIGNMENT` | 409 Conflict |
| `ERR_PSSR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_PSSR_NOT_APPROVED` | 409 Conflict |
| `ERR_OPEN_P1_ACTION_ITEMS` | 409 Conflict |
| `ERR_PROCEDURES_NOT_PUBLISHED` | 409 Conflict |
| `ERR_TRAINING_COVERAGE_INSUFFICIENT` | 409 Conflict |
| `ERR_NO_EVIDENCE_ATTACHED` | 409 Conflict |
| `ERR_AUDIT_OPEN_FINDINGS` | 409 Conflict |
| `ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE` | 409 Conflict |
| `ERR_PSSR_OPEN_PUNCH_ITEMS` | 409 Conflict |
| `ERR_NO_TRAINING_ASSIGNED` | 409 Conflict |
| `ERR_CLOCK_REGRESSION` | 409 Conflict |

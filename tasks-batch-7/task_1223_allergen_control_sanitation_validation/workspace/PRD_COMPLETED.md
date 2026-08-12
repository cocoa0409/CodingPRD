# Allergen Control Sanitation API — Product Requirements Document

## 1. Introduction

Undeclared allergens are among the most expensive and most dangerous failure modes in food manufacturing: a single cross-contact event on a shared production line can trigger a recall, a regulatory finding, and — far worse — a consumer safety incident. This document specifies the API for the Allergen Control & Sanitation Validation Program operated by a food plant's quality assurance department. The program exists to make every product changeover provable: which allergens a product carries, what a line must do before a different allergen profile may run on it, which swabs verified the clean-out, and what the packaging actually declared to the consumer.

The API manages the full lifecycle of that proof. Master data covers the allergen catalogue, the production lines with their sanitation classes, the per-line allergen handling matrix that drives sequencing decisions, and the products with their declared allergen profiles and approved label revisions. On top of that foundation, the system sequences production runs, gates each run behind a validated changeover whenever new allergens are introduced, records ATP and allergen swab results against configured action levels, reconciles printed labels against the label revision pinned at run creation, routes rework material under strict containment rules, and escalates undeclared-allergen findings and sanitation failures into tracked incidents. Technician certification, rolling training scores, and audit findings close the loop on the human side of the program.

All endpoints are mounted under the `/qa` prefix. Five roles share the work under a segregation-of-duties model: the QA manager owns configuration and final closure authority, the shift QA supervisor owns scheduling, label reconciliation, and investigation, certified bench technicians record swab and label evidence, line operators execute runs, changeovers, and rework commits, and auditors record findings. A derived line posture — `OPEN`, `RESTRICTED`, or `HOLD` — gates what may proceed on each line at any moment, so the safety state of the plant is always legible from the data rather than from hallway conversation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly five roles: `QaManager`, `QaSupervisor`, `QaTechnician`, `LineOperator`, and `Auditor`. A request with missing or malformed headers is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); a role string outside those five values counts as a malformed header, and `X-User-ID` must be a non-empty string. A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403), regardless of how otherwise valid the request may be.

Identity semantics differ by role, and the difference matters for ownership and segregation checks. When `X-User-Role` is `QaTechnician`, `X-User-ID` is the `id` of the acting QaTechnician entity; checks on any resource that references a technician — such as a swab record's `recorded_by_id` or an audit finding's `technician_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Auditor`, `X-User-ID` is likewise entity-backed: it is the `id` of the QaTechnician performing the audit of record, and it is compared against the `auditor_id` carried on audit findings. When `X-User-Role` is `QaManager`, `QaSupervisor`, or `LineOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for traceability but never compares it to any entity's `id`.

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

Requests that reach an unknown path, or a known path with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404) in the same envelope.

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order; resources created within the same millisecond (equal `created_at`) are ordered by server creation sequence.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-dependent rules in the program evaluate against a server-maintained logical clock, never against wall-clock time. At startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `QaManager` may advance the clock through an admin-only, test-driving capability by supplying a `to_iso8601` instant; the response reports the new `current_utc`. The clock may be set to any instant, forward or backward — no monotonicity is enforced — and the overdue sweep only ever moves `OPEN` findings to `OVERDUE`, never the reverse.

Three families of rules read this clock: run-start eligibility (a run may not start before its planned start), audit-finding overdue sweeps, and technician certification expiry. Advancing the clock sweeps every `OPEN` audit finding whose `corrective_action_due_utc` lies before the new clock instant into the `OVERDUE` state, with the score consequences described in §3.9. Certification expiry is deliberately not retroactive: swabs that were recorded while a certification was valid remain valid, but any swab recorded after the technician's `certification_expiry_utc` is rejected at recording time.

### 2.5. Line Posture: The Derived Safety Gate

Every production line carries a derived `posture` of `OPEN`, `RESTRICTED`, or `HOLD`. Posture is never assigned directly by a client; it is recomputed from the line's open incidents and unresolved changeovers whenever an incident is created, contained, closed, or voided, whenever a changeover on the line lands in `FAILED`, `REWORK_REQUIRED`, or `VALIDATED`, and whenever a reswab moves a changeover out of `REWORK_REQUIRED` back to `SWAB_PENDING`.

The recomputation follows a pinned evaluation order — the HOLD condition is checked first, then RESTRICTED, then OPEN. If any incident on the line has `severity` `CRITICAL` while standing in `OPEN`, `INVESTIGATING`, or `CONTAINED`, or if any changeover on the line stands at `FAILED`, the posture is `HOLD`. Failing that, if any incident on the line has `severity` `HIGH` in those same three non-final statuses, or any changeover on the line stands at `REWORK_REQUIRED`, the posture is `RESTRICTED`. Only when neither condition holds does the line read `OPEN`. Because the check order is pinned, a line with both a `CRITICAL` incident and a `REWORK_REQUIRED` changeover reports `HOLD`, never `RESTRICTED`.

Posture gates production throughout the program. Scheduling a run and starting a run both require the line to be `OPEN`, and fail with `ERR_LINE_NOT_OPEN` (HTTP 409) otherwise. Beginning a changeover is more tolerant — it accepts `OPEN` or `RESTRICTED` — but a line sitting at `HOLD` refuses the begin with `ERR_LINE_ON_HOLD` (HTTP 409).

### 2.6. Common Resource Properties

All resources in this API — allergens, production lines, products, matrix entries, production runs, changeovers, changeover procedures, swab results, technicians, label reconciliations, rework batches, incidents, and audit findings — carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (for example, `2025-05-24T10:30:00.123Z`) recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp, in the same format, recording the last modification.
- **`version` (integer):** a system-managed integer, starting at 1 when the resource is created, that increments by one on every mutation of the resource.

Recomputation of derived fields counts as mutation. When the server recomputes a line's `posture`, a technician's `training_score`, a changeover's `validation_score`, or a procedure family's `is_current` flags, the owning resource's `updated_at` refreshes and its `version` increments. Two workflows additionally increment a *related* resource's version: scheduling a run increments the version of the `ProductionLine` it targets, and beginning a changeover does the same, because both actions change what other writers may safely assume about that line.

### 2.7. Optimistic Concurrency Control

Two write operations in the program require an explicit optimistic-concurrency token, because both mutate shared family or line state that other writers depend on.

Scheduling a production run requires the request to carry `expected_line_version`, holding the line `version` the client last observed. If the line's current `version` has advanced since that observation — for example because another supervisor has just scheduled a different run on the same line, legitimately changing the overlap universe — the schedule request is rejected with `ERR_STALE_LINE_VERSION` (HTTP 412), preventing the client from committing against a view of line occupancy it has not observed.

Approving a changeover procedure requires the request to carry `expected_procedure_version`, holding the procedure `version` the client last observed. Approving from a stale observation risks double-superseding a sibling version that has already been superseded by a prior approval, so a mismatch with the procedure's current `version` is rejected with `ERR_STALE_PROCEDURE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field; all other mutations proceed without an OCC check.

### 2.8. Validation Cascade and Nested Resource Resolution

Requests are evaluated against an ordered validation cascade, and the first failing check determines the error returned. The order is:

1. **Identity headers** — `X-User-ID` and `X-User-Role` must be present and well formed, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization** — the declared role must be permitted on the target endpoint, failing with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Existence** — path identifiers and foreign-key parents must resolve, validated left to right along the URL. A request that names a non-existent identifier is rejected with `ERR_NOT_FOUND` (HTTP 404) at the *first* unresolved identifier in the path, before any later identifier is examined.
4. **Optimistic concurrency** — any required `expected_*_version` field must match the parent's current `version` (HTTP 412, per §2.7).
5. **Source-state legality** — the entity must stand in the exact source state the transition requires, failing with the corresponding member of the not-in-state family (`ERR_RUN_NOT_DRAFT`, `ERR_RUN_NOT_SCHEDULED`, `ERR_RUN_NOT_IN_PROGRESS`, `ERR_CHANGEOVER_NOT_PLANNED`, `ERR_CHANGEOVER_NOT_IN_EXECUTION`, `ERR_CHANGEOVER_NOT_REWORK`, `ERR_RECON_NOT_OPEN`, `ERR_INCIDENT_NOT_OPEN`, `ERR_INCIDENT_NOT_INVESTIGATING`, `ERR_INCIDENT_NOT_CONTAINED`, `ERR_FINDING_NOT_OPEN`, `ERR_TECH_NOT_SUSPENDED`, `ERR_PROCEDURE_NOT_DRAFT`, `ERR_PROCEDURE_NOT_APPROVED`, `ERR_REWORK_NOT_AVAILABLE`), each HTTP 409. Product activity is checked at this step as well: an inactive product fails with `ERR_PRODUCT_INACTIVE` (HTTP 422), immediately after the run-state check and before the posture gates.
6. **Posture gates** — line posture must permit the operation (`ERR_LINE_NOT_OPEN`, `ERR_LINE_ON_HOLD`, HTTP 409).
7. **Business-safety rules** — prohibited allergens on a line, the changeover validation gate, the label reconciliation gate, rework allergen containment, and technician certification.
8. **Business constraints** — run overlap, the rework class gate, and procedure-in-use.
9. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
10. **Temporal rules** — planned-start reachability and time-range sanity.
11. **Allergen referential integrity** — referenced allergens must be active.
12. **Quantity and budget rules** — rework quantity sufficiency and changeover minute budgets.

Where a workflow in §3 pins a more specific gate order for an endpoint — as §3.4 does for scheduling and §3.7 does for rework commits — that endpoint-specific order governs within and across these steps.

Malformed payloads, missing required fields, and values outside their permitted ranges fail schema validation with `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur.

### 2.9. Numbers, Thresholds, and Rounding

Minute budgets (`changeover_minutes`, `scheduled_changeover_minutes`, `scheduled_minutes`, `actual_minutes`) are whole minutes, expressed as integers. Scores — a changeover's `validation_score` and a technician's `training_score` — are integers clamped to the inclusive range 0 through 100.

Swab measurements are compared at full numeric precision against their action levels, and the comparison is strict in the safety direction: a measured value exactly equal to the action level counts as a `FAIL`, not a `PASS`. Allergen concentrations are recorded in parts per million and ATP readings in relative light units; the API performs no unit conversion and no rounding on `measured_value`.

## 3. Business Logic & Workflows

### 3.1. Allergen Master Data and the Line-Allergen Matrix

Before any run can be sequenced, a `QaManager` registers the master data the program reasons over. An **allergen** is registered with a short `code` (unique across the catalogue, restricted to uppercase letters and underscores — `PEANUT`, `MILK`, `SOY`, `WHEAT` are typical — with a duplicate or ill-formed code rejected with `ERR_INVALID_REQUEST`, HTTP 400), a human-readable `display_name`, and a `regulatory_class` drawn from `MAJOR_9`, `SESAME`, `SULFITE`, or `OTHER`. Membership in `MAJOR_9` is what drives the mandatory-changeover behaviour described later. Each allergen also carries an `is_active` flag, defaulting to true, which soft-disables the allergen: an inactive allergen cannot be newly mapped anywhere.

A **production line** is registered with a unique `line_code` (such as LINE-1; a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a free-text `description`, and a `sanitation_class` of `WET_WASH`, `DRY_CLEAN`, or `ALLERGEN_DEDICATED`. A newly created line starts with `posture` `OPEN` and with `last_validated_changeover_id` empty — null until some changeover on the line reaches `VALIDATED`.

The **line-allergen matrix** is the program's sequencing rulebook. Each matrix entry ties a `line_id` to an `allergen_id` and declares a `handling` of `ALLOWED`, `REQUIRES_CHANGEOVER`, or `PROHIBITED`, plus a `changeover_minutes` budget — the minimum scheduled minutes required when transitioning to a product that introduces that allergen on that line — a non-negative integer defaulting to 30 minutes when not supplied. Multiple entries may name the same `(line_id, allergen_id)` pair; every matching entry is then consulted when the sequencing decisions of §3.4 are computed. Referential integrity is enforced at write time: a matrix entry that references an allergen whose `is_active` is false is rejected with `ERR_ALLERGEN_INACTIVE` (HTTP 422), and the same rejection meets a product registration whose `allergen_set` contains a code that does not resolve to an active allergen row.

### 3.2. Product Registration, Rework Classes, and Label Revisions

A `QaManager` registers each **product** with a unique `sku` (a duplicate fails with `ERR_INVALID_REQUEST`, HTTP 400), a commercial `product_name`, and the `allergen_set` — the array of allergen codes intentionally present in the product, which constitutes its declared allergen profile. Two governance fields ride along: the `rework_class`, one of `SAME_INTO_SAME`, `SAME_ALLERGEN_PROFILE`, `RESTRICTED_REWORK`, or `NO_REWORK`, which governs where the product's rework material may later be routed; and the `label_revision`, an integer of at least 1 defaulting to 1 that identifies the currently approved label artwork. Products also carry an `is_active` flag defaulting to true.

Label revisions move for two reasons. A `QaManager` may patch a product directly, supplying a new `label_revision`, toggling `is_active`, or replacing the `allergen_set`. Supplying any of the three fields counts as a mutation (the `version` increments) even when the supplied value equals the current one, but the `allergen_set` is compared as a set, so a mere reordering creates no incident. Neither the patch nor the supplier-allergen-change flow re-validates the replacement `allergen_set` against active allergens — the `ERR_ALLERGEN_INACTIVE` check of §3.1 fires only at product registration. Separately, when a supplier reformulates an ingredient, the manager records the notification through the supplier-allergen-change flow, supplying the `new_allergen_set` and a `supplier_notice_ref` for traceability; the product's `allergen_set` is replaced and its `label_revision` is incremented by one automatically.

Either path, whenever the `allergen_set` changes, has the same side effect: an incident of `incident_type` `SUPPLIER_ALLERGEN_CHANGE` with `severity` `MEDIUM` is auto-created against the product, with `product_id` populated and `allergen_id` left null. Runs already sitting in `DRAFT` or `SCHEDULED` for that product keep the `label_revision_snapshot` they pinned at creation — a deliberate stale-pin — so any label reconciliation performed for those runs afterwards will flag a `REVISION_MISMATCH` and force a conscious disposition rather than silently absorbing the new artwork.

### 3.3. Changeover Procedures and Version Control

A **changeover procedure** is the versioned standard operating procedure for removing an allergen from a line. A `QaManager` drafts one by supplying a `procedure_code` (a unique SOP code such as COP-PEANUT-V3), the `target_allergen_id` the procedure removes, a `method` of `FULL_WET_WASH`, `DRY_SCRAPE`, `PURGE`, or `VACUUM_ONLY`, and three validation parameters: `min_swab_zones`, the minimum number of distinct swab zones that must pass for the changeover to validate; `atp_action_level_rlu`, the relative-light-unit reading at or above which an ATP swab fails; and `allergen_action_level_ppm`, the parts-per-million reading at or above which an allergen swab fails.

Procedures are versioned per `procedure_code` family. Reusing an existing `procedure_code` at creation starts a new version whose `version_seq` is one greater than the current family maximum, monotonically increasing within the family. A fresh draft is not the family's current row — `is_current` stays false until approval — and each procedure's `status` begins at `DRAFT`.

Approval is the pivot of the family lifecycle, and it is guarded by checks evaluated in the cascade order of §2.8: the OCC token `expected_procedure_version` must match the procedure's current `version`, failing with `ERR_STALE_PROCEDURE_VERSION` (HTTP 412) on mismatch; the procedure must stand in `DRAFT`, failing with `ERR_PROCEDURE_NOT_DRAFT` otherwise; and the validation parameters must be sane — `min_swab_zones` at least 1, `atp_action_level_rlu` greater than 0, and `allergen_action_level_ppm` greater than 0 — failing with `ERR_INVALID_REQUEST` otherwise. When approval succeeds, the newly approved row moves to `APPROVED` and becomes the family's current row (`is_current` true), any previously `APPROVED` sibling with the same `procedure_code` is pushed to `SUPERSEDED` and loses currency, and the procedure's own `version` increments by one. Supersession is automatic from then on: whenever a newer family version is approved, the older approved row flips to `SUPERSEDED` without any client action.

Retirement is the family exit. A `QaManager` may retire a procedure only while it stands at `APPROVED` (`ERR_PROCEDURE_NOT_APPROVED` otherwise), and only while no changeover in `PLANNED`, `IN_EXECUTION`, `SWAB_PENDING`, or `REWORK_REQUIRED` still references it — an active reference blocks retirement with `ERR_PROCEDURE_IN_USE` (HTTP 409). Retiring moves the procedure to the terminal `RETIRED` state and clears its `is_current`.

### 3.4. Production Run Scheduling and the Changeover Gate

A `QaSupervisor` drafts a **production run** by naming the `line_id` it will execute on, the `product_id` it will manufacture, and the `planned_start_utc` and `planned_end_utc` bracketing it. The planned end must be strictly later than the planned start, failing with `ERR_INVALID_TIME_RANGE` (HTTP 400) otherwise. The run is born in `DRAFT`, and creation does three pieces of bookkeeping immediately: the product's current `label_revision` is pinned into the run's `label_revision_snapshot`; the run's `introduced_allergens` are computed; and `changeover_required` plus `scheduled_changeover_minutes` are derived from them.

The introduced-allergen computation is a set difference against a baseline. The baseline is the declared allergen profile of the most recent `COMPLETED` or `IN_PROGRESS` run on the same line, where candidate runs are ordered by planned start time and then by creation time, both ascending, and the final run in that ordering supplies the baseline; if no such prior run exists, the baseline is the empty set. The run's `introduced_allergens` are then exactly the codes in its product's `allergen_set` that the baseline does not contain, listed in ascending allergen-code order. At creation time the preview is *optimistic*: runs still sitting in `SCHEDULED` are counted in the baseline set as though they will complete, so an immediately preceding scheduled run already contributes its allergens to the preview. Runs in `DRAFT`, `REJECTED`, or `CANCELLED` never contribute to any baseline.

Whether a changeover is required follows directly. When `introduced_allergens` is empty, `changeover_required` is false. When any introduced allergen is mapped `PROHIBITED` on that line, the run cannot proceed at all — the write is rejected with `ERR_ALLERGEN_PROHIBITED_ON_LINE` (HTTP 422), and this is enforced both at run creation and again at scheduling. Otherwise, if any introduced allergen is mapped `REQUIRES_CHANGEOVER`, the changeover is required. If no introduced allergen demands one but the line's `sanitation_class` is anything other than `ALLERGEN_DEDICATED` and the introduced set is non-empty, a changeover is still required; on an `ALLERGEN_DEDICATED` line with no `REQUIRES_CHANGEOVER` mapping, it is not. The `scheduled_changeover_minutes` are the largest `changeover_minutes` among the matrix entries covering the introduced allergens on that line, or zero when nothing was introduced.

Overlap is policed at creation and again at scheduling: the run's half-open interval — including `planned_start_utc` and excluding `planned_end_utc`, so back-to-back runs touching at an endpoint do not collide — must not intersect the corresponding interval of any other `SCHEDULED` or `IN_PROGRESS` run on the same line, failing with `ERR_RUN_OVERLAP` (HTTP 409).

Scheduling moves the run `DRAFT` → `SCHEDULED` under a `QaSupervisor`, and it is the most heavily gated transition in the program. Consistent with the cascade of §2.8, the OCC check fires first: the request's `expected_line_version` must match the line's current `version` (`ERR_STALE_LINE_VERSION`, HTTP 412 — another writer may have scheduled a competing run on this line since the client last read it, and the client's view of line occupancy is then stale). The remaining gates follow: the run must still be `DRAFT` (`ERR_RUN_NOT_DRAFT`); the product's `is_active` must be true (`ERR_PRODUCT_INACTIVE`, HTTP 422); the line's `posture` must be `OPEN` (`ERR_LINE_NOT_OPEN`); and if the run's stored `changeover_required` is true — the gate reads the value currently stored on the run (pinned optimistically at creation; cleared by unscheduling) exactly as-is, with no strict recomputation performed ahead of it — a covering changeover targeting this run must already exist in one of `PLANNED`, `IN_EXECUTION`, `SWAB_PENDING`, `REWORK_REQUIRED`, or `VALIDATED` (`ERR_CHANGEOVER_MISSING`; a `CANCELLED` or `FAILED` changeover does not cover). Only then is `introduced_allergens` recomputed under the *strict* variant — the baseline now counts only runs that are actually `COMPLETED` or `IN_PROGRESS`, so a predecessor still sitting in `SCHEDULED` does not contribute its allergens — and this strict recomputation is what re-enforces the prohibited-allergen rule at scheduling (`ERR_ALLERGEN_PROHIBITED_ON_LINE`). After the recomputation the overlap check above is re-run (`ERR_RUN_OVERLAP`), and only on success are the recomputed `introduced_allergens`, `changeover_required`, and `scheduled_changeover_minutes` stored back onto the run, the run moved to `SCHEDULED`, and the line's `version` incremented by one.

Two escape hatches return a run to or out of `DRAFT`. Unscheduling moves `SCHEDULED` → `DRAFT` (the run must be `SCHEDULED`, failing with `ERR_RUN_NOT_SCHEDULED`) and clears `introduced_allergens`, `changeover_required`, and `scheduled_changeover_minutes` — reset to empty, false, and zero — until the next scheduling attempt. Rejecting moves `DRAFT` → `REJECTED` outright (again requiring `DRAFT`, failing with `ERR_RUN_NOT_DRAFT`). Cancelling accepts a run in `DRAFT` or `SCHEDULED` and lands it in `CANCELLED` — a run in any other state is rejected with `ERR_RUN_NOT_CANCELLABLE`. Cancellation cascades into the changeover book: any changeover whose `to_run_id` names this run and which still stands at `PLANNED` is cancelled with it, and when a `SCHEDULED` run is cancelled the cascade also reaches changeovers in `IN_EXECUTION`, invalidating any swab results recorded against them mid-flight that are not already `INVALIDATED`.

The floor crew takes over once the schedule holds. A `LineOperator` starts the run, moving it `SCHEDULED` → `IN_PROGRESS`. The run must be `SCHEDULED` (`ERR_RUN_NOT_SCHEDULED`), the line must be `OPEN` (`ERR_LINE_NOT_OPEN`), a run flagged `changeover_required` may only start once its covering changeover stands at `VALIDATED` (`ERR_CHANGEOVER_NOT_VALIDATED`), and the logical clock must have reached `planned_start_utc` — starting early is rejected with `ERR_RUN_NOT_DUE` (HTTP 409). A successful start consumes the covering changeover — when several `VALIDATED` changeovers cover the run, the most recently created one — and refreshes the line's `last_validated_changeover_id` with the changeover that was just consumed; the consumed changeover itself is not modified and remains `VALIDATED`.

Completion moves `IN_PROGRESS` → `COMPLETED` under the same role. The run must be `IN_PROGRESS` (`ERR_RUN_NOT_IN_PROGRESS`), and every label reconciliation raised for the run must either carry the verdict `MATCH` or stand in `RESOLVED` status — any reconciliation that satisfies neither condition (an `OPEN` reconciliation whose verdict is `MATCH` does not block) is rejected with `ERR_LABEL_RECONCILIATION_OPEN` (HTTP 409), which is exactly how an unresolved undeclared-allergen finding holds product on the floor. A completed run becomes the baseline against which later runs on the line diff their allergen profiles. `COMPLETED`, `REJECTED`, and `CANCELLED` are the run's terminal states.

### 3.5. Changeover Execution and Swab Verification

A **changeover** is the planned, executed, and verified cleaning event between two runs. A `QaSupervisor` plans one by naming the `line_id`, the `from_run_id` of the run ending (null when this is the first run ever scheduled on the line), the `to_run_id` of the run that will start afterwards, the `procedure_id` of the procedure version being executed, and a `scheduled_minutes` budget. The budget must be at least the to-run's `scheduled_changeover_minutes`; a short budget is rejected with `ERR_CHANGEOVER_BUDGET_SHORT` (HTTP 422). Planning performs no other gate: the line's posture, the to-run's state, and the procedure's status are all unchecked at planning time. The changeover is born `PLANNED`, with `actual_minutes` and `validation_score` both null until execution and swab data exist.

A `LineOperator` begins execution, moving the changeover `PLANNED` → `IN_EXECUTION`. The changeover must be `PLANNED` (`ERR_CHANGEOVER_NOT_PLANNED`), its to-run must still be `SCHEDULED` (`ERR_RUN_NOT_SCHEDULED` — a cancelled or unscheduled to-run strands the changeover), and the line's `posture` must be `OPEN` or `RESTRICTED`, with a `HOLD` line refusing the begin via `ERR_LINE_ON_HOLD`. Beginning increments the line's `version` by one. When the physical clean-out finishes, the same role records the outcome by finishing execution, moving `IN_EXECUTION` → `SWAB_PENDING`; the changeover must be `IN_EXECUTION` (`ERR_CHANGEOVER_NOT_IN_EXECUTION`), and `actual_minutes` must be supplied and non-negative (`ERR_INVALID_REQUEST` otherwise), at which point the value is recorded on the changeover.

Swab evidence then accumulates against the `SWAB_PENDING` changeover — a swab recorded against a changeover in any other state is rejected with `ERR_SWAB_NOT_PENDING` (HTTP 409). Every swab result is bound to the changeover it verifies through its `changeover_id`, recorded as part of the write. A `QaTechnician` records each **swab result** with a `zone_code` identifying the physical zone swabbed (BELT-A, HOPPER-2, and the like), a `swab_type` of `ATP`, `ALLERGEN_PROTEIN`, or `ALLERGEN_ELISA`, a `measured_value` (relative light units for ATP, parts per million for the allergen types), an optional `invalidated_reason`, and the `recorded_by_id` of the technician who performed the test. Two personnel gates guard the write: the recording technician must be `ACTIVE` — a `SUSPENDED` or `SEPARATED` technician is turned away with `ERR_TECH_NOT_ACTIVE` (HTTP 403) — and must hold a current certification covering the procedure's target allergen, meaning the allergen appears in the technician's `certified_allergen_ids` and the logical clock has not passed `certification_expiry_utc`, failing with `ERR_TECH_NOT_CERTIFIED` (HTTP 403) otherwise.

The outcome of each swab is computed, never asserted. The applied threshold, stored as `action_level_used`, is the procedure's `atp_action_level_rlu` when the swab is `ATP`, and the procedure's `allergen_action_level_ppm` for `ALLERGEN_PROTEIN` and `ALLERGEN_ELISA`. Supplying an `invalidated_reason` at recording marks the swab `INVALIDATED` outright (the field is otherwise null). Otherwise the `outcome` is `PASS` when the `measured_value` is strictly below the `action_level_used`, and `FAIL` when it equals or exceeds it — an exact hit on the action level is a failure.

The changeover then converges automatically on one of three verdicts, driven by the swab book. Validation requires two conditions together: the count of distinct `zone_code` values holding a `PASS` swab reaches the procedure's `min_swab_zones`, and no swab on the changeover stands at `FAIL`. When both hold, the changeover moves `SWAB_PENDING` → `VALIDATED`: its `validation_score` is computed, the line's `last_validated_changeover_id` is set to this changeover, the line's `posture` is recomputed, and the covering gate on the to-run is satisfied. If instead the `FAIL` count reaches two, the changeover moves to `FAILED`: an incident with `incident_type` `SWAB_FAILURE_CLUSTER` and `severity` `HIGH` is auto-created with its `source_changeover_id` pointing at this changeover, the line's `posture` drops to `HOLD`, and the to-run remains `SCHEDULED` but cannot start. A single `FAIL` lands the changeover in `REWORK_REQUIRED` instead, with the failed zones queued for re-cleaning.

Recovery from `REWORK_REQUIRED` is the reswab: a `LineOperator` moves the changeover back to `SWAB_PENDING` after the re-clean (the changeover must be `REWORK_REQUIRED`, failing with `ERR_CHANGEOVER_NOT_REWORK`), and every prior `FAIL` swab on the changeover is marked `INVALIDATED` with `invalidated_reason` set to RESWAB, clearing them from the failure count, and the line's `posture` is recomputed. Cancellation is the other exit: a `QaSupervisor` may cancel a changeover standing at `PLANNED` or `IN_EXECUTION` — anything more advanced is terminal for this purpose and rejected with `ERR_CHANGEOVER_TERMINAL` — and cancelling one that is mid-execution marks its recorded swabs `INVALIDATED` with the reason CHANGEOVER_CANCELLED.

The `validation_score` rewards discipline. It starts from a base of 100 points. Finishing on time — `actual_minutes` at or under `scheduled_minutes` — adds a 5-point bonus. Running over subtracts 1 point for each full five-minute block of overrun, and that tardy deduction is capped at 20 points no matter how long the overrun runs. Each `PASS` swab whose `measured_value` is at most half of its `action_level_used` adds a 1-point margin bonus, with the total margin bonus capped at 10 points. Each `INVALIDATED` swab subtracts 2 points. The final figure is clamped to the inclusive range 0 through 100 and stored as an integer.

### 3.6. Label Reconciliation and Packaging Control

Packaging control closes the loop between what the run is and what the consumer is told. A `QaTechnician` or `QaSupervisor` raises a **label reconciliation** for a run by supplying the `run_id`, the `printed_label_revision` actually observed on the packaging line, and the `declared_allergens_on_label` — the allergen codes printed on the label. At creation the reconciliation copies its `expected_label_revision` from the run's pinned `label_revision_snapshot`, then computes both allergen deltas: `missing_allergens`, the codes in the product's `allergen_set` that the label failed to declare, and `extra_allergens`, the codes the label declares that the product does not contain, each listed in ascending allergen-code order.

The `verdict` is computed under a pinned precedence — undeclared allergens outrank everything. When `missing_allergens` is non-empty the verdict is `UNDECLARED_ALLERGEN`. Failing that, when `printed_label_revision` differs from `expected_label_revision` the verdict is `REVISION_MISMATCH`. Failing that, a non-empty `extra_allergens` yields `OVER_DECLARED`. Only when nothing is missing, the revision matches, and nothing extra is declared does the reconciliation read `MATCH`. Recomputing the declared allergens or the printed revision re-derives the same fields under the same precedence.

A reconciliation is born `OPEN` and exits in one of two directions. A `QaSupervisor` may resolve it — `OPEN` → `RESOLVED` — only while it is `OPEN` (`ERR_RECON_NOT_OPEN`) and only when the verdict is `MATCH`; attempting to resolve a non-`MATCH` reconciliation directly is rejected with `ERR_RECON_NOT_MATCH` (HTTP 409), because anything other than a clean match demands escalation, not quiet closure. Escalation moves `OPEN` → `ESCALATED` (again requiring `OPEN`, failing with `ERR_RECON_NOT_OPEN`; any `OPEN` reconciliation may be escalated, including a `MATCH` one) and raises an incident automatically: `incident_type` `UNDECLARED_ALLERGEN` at `severity` `CRITICAL` when `missing_allergens` is non-empty, otherwise `LABEL_MISMATCH` at `severity` `HIGH`, with the incident's `source_label_reconciliation_id` recording the reconciliation that spawned it and its `line_id` and `product_id` copied from the run. The `CRITICAL` branch bites immediately — the line's `posture` drops to `HOLD` — and because the escalated reconciliation is terminal with a non-`MATCH` verdict, the run it names can never afterwards satisfy the completion gate of §3.4. `RESOLVED` and `ESCALATED` are both terminal for the reconciliation.

### 3.7. Rework Handling and Allergen Containment

Rework — product recovered from one run and reintroduced into another — is where allergen profiles silently drift unless the rules are mechanical. A `LineOperator` or `QaSupervisor` creates a **rework batch** from the `source_run_id` that generated the material, the `source_product_id` it came from, and the `quantity_kg` available, which must be greater than zero (`ERR_INVALID_REQUEST`, HTTP 400 — the same rule and error apply to the quantity named at commit). At creation the batch's `remaining_kg` is initialized to the full `quantity_kg`, its `rework_allergen_set` is copied from the source product's declared `allergen_set`, and its `status` opens at `AVAILABLE`.

Committing the batch into a target run is a `LineOperator` action carrying the `target_run_id` and the `quantity_kg` to consume. Four gates stand in front of it. The batch must be `AVAILABLE` (`ERR_REWORK_NOT_AVAILABLE`); its `remaining_kg` must be greater than zero, and the requested quantity must not exceed `remaining_kg` — either failure is `ERR_REWORK_EXHAUSTED` (HTTP 422). Then the two rework rules fire in a pinned order, class gate first. The class gate reads the target run's product `rework_class`: under `SAME_INTO_SAME` the batch's source product must be the very product the target run is manufacturing; under `SAME_ALLERGEN_PROFILE` the batch's `rework_allergen_set` must be identical to the target product's `allergen_set`; under `RESTRICTED_REWORK` the batch's allergen set must be a subset of the target's; and under `NO_REWORK` every commit is refused. A class-gate failure is rejected with `ERR_REWORK_CLASS_VIOLATION` (HTTP 422). Only after the class gate passes does the allergen-subset rule apply: regardless of class, the batch's `rework_allergen_set` must be a subset of the target product's `allergen_set`, failing with `ERR_REWORK_ALLERGEN_BREACH` (HTTP 422). Because the class gate is evaluated first, a commit that violates both surfaces `ERR_REWORK_CLASS_VIOLATION`, never the allergen breach.

A successful commit decrements `remaining_kg` by the committed quantity, and a batch whose remainder reaches zero flips automatically from `COMMITTED` to `CONSUMED` with no further client action. A `QaSupervisor` may instead scrap a batch standing at `AVAILABLE` or `COMMITTED` — a batch already in a terminal state is rejected with `ERR_REWORK_TERMINAL` (HTTP 409) — which zeroes `remaining_kg` and lands the batch at `SCRAPPED`. `CONSUMED` and `SCRAPPED` are terminal.

### 3.8. Incident Escalation and Line Posture Recovery

**Incidents** are the program's escalation currency, raised either automatically — by swab failure clusters, label escalations, and supplier allergen changes — or manually by a `QaSupervisor` or `QaManager` supplying an `incident_type` of `UNDECLARED_ALLERGEN`, `LABEL_MISMATCH`, `SWAB_FAILURE_CLUSTER`, `SUPPLIER_ALLERGEN_CHANGE`, or `REWORK_RULE_BREACH`; a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`; the affected `line_id` (null for supplier incidents), `product_id`, and `allergen_id` as applicable; and a free-text `description`. Auto-raised incidents carry their provenance in `source_label_reconciliation_id` or `source_changeover_id`. Every incident is born `OPEN`, and creating one immediately recomputes the line's `posture` — a fresh `CRITICAL` incident puts its line on `HOLD` without any further action.

The investigation path is deliberately staged. A `QaSupervisor` begins investigation, moving `OPEN` → `INVESTIGATING` (the incident must be `OPEN`, failing with `ERR_INCIDENT_NOT_OPEN`). Containment moves `INVESTIGATING` → `CONTAINED` under the same role: the incident must be `INVESTIGATING` (`ERR_INCIDENT_NOT_INVESTIGATING`), and a non-empty `containment_action` describing the containment steps is mandatory (`ERR_INVALID_REQUEST` without it). When a contained incident was the `CRITICAL` one holding its line at `HOLD`, the posture is recomputed at containment and may relax to `RESTRICTED`.

Closure is reserved for a `QaManager`, moving `CONTAINED` → `CLOSED`. The incident must be `CONTAINED` (`ERR_INCIDENT_NOT_CONTAINED`), a non-empty `root_cause` narrative is mandatory (`ERR_INVALID_REQUEST` without it), and segregation of duties is enforced: the closing manager must differ from the technician who recorded the swab or label entry that triggered the incident, failing with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The triggering users recorded for this check are, for a swab-failure-cluster incident, the technicians who recorded the `FAIL` swabs and, for a label escalation, the user who created the reconciliation; a manually raised incident records no triggering user, so the check can never fire for one. Closing recomputes the line's posture. The alternate exit is voiding — `OPEN` → `VOID` by a `QaManager`, requiring the incident to be `OPEN` (`ERR_INCIDENT_NOT_OPEN`) — which likewise recomputes the line's posture. `CLOSED` and `VOID` are terminal.

### 3.9. Technician Certification, Training Scores, and Audit Findings

The human layer of the program runs on **QA technicians**. A `QaManager` registers each technician with a unique `tech_code` (such as TECH-014; a duplicate fails with `ERR_INVALID_REQUEST`, HTTP 400), a `full_name`, the `certified_allergen_ids` array naming every allergen the technician is certified to verify (each entry must resolve to an existing allergen, failing `ERR_NOT_FOUND` otherwise), and the `certification_expiry_utc` at which that coverage lapses. A new technician starts with a `training_score` of 100 and a `status` of `ACTIVE`.

The training score is a rolling aggregate, recomputed whenever the technician's audit findings change. It starts from 100; every finding standing at `OPEN`, `OVERDUE`, or `RESOLVED` subtracts its `points_deducted`; every finding that has incurred the overdue penalty and stands at `OVERDUE` or `RESOLVED` subtracts a further 3-point overdue penalty on top (the penalty, once incurred, is never refunded); and a `WAIVED` finding deducts nothing, its points having been refunded. The score floors at 0, ceilings at 100, and is stored as an integer. When a recomputation leaves the score below 60, the technician flips automatically from `ACTIVE` to `SUSPENDED`. A `SUSPENDED` or `SEPARATED` technician cannot record swabs or audits — attempts are rejected with `ERR_TECH_NOT_ACTIVE`. A `QaManager` may also suspend a technician manually; manual suspension requires the technician to be `ACTIVE` — a `SEPARATED` technician is rejected with `ERR_TECH_TERMINAL` (HTTP 409) and any other non-`ACTIVE` state with `ERR_TECH_NOT_ACTIVE` (HTTP 403). Reinstatement moves `SUSPENDED` → `ACTIVE` (the technician must be `SUSPENDED`, failing with `ERR_TECH_NOT_SUSPENDED`) and resets the `training_score` to exactly 75. Separation moves `ACTIVE` or `SUSPENDED` → `SEPARATED` (a technician already in a terminal state is rejected with `ERR_TECH_TERMINAL`), and `SEPARATED` is terminal.

**Audit findings** are how the score moves. An `Auditor` records a finding against a technician by supplying the `technician_id` audited, the `auditor_id` performing the audit, a `finding_type` of `PROCEDURE_DEVIATION`, `DOCUMENTATION_GAP`, `TRAINING_DEFICIENCY`, `SWAB_TECHNIQUE`, or `LABEL_CONTROL`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and the `corrective_action_due_utc` deadline. Segregation of duties applies at creation: the `auditor_id` must differ from the `technician_id`, failing with `ERR_SEGREGATION_OF_DUTIES`. The severity fixes the computed `points_deducted` — 2 points for `MINOR`, 5 for `MAJOR`, 15 for `CRITICAL` — and the technician's `training_score` is recomputed immediately, auto-suspending the technician if it lands below 60.

Findings age against the logical clock. When the clock passes a finding's `corrective_action_due_utc` while the finding still stands `OPEN`, the finding flips automatically to `OVERDUE` and a further 3-point penalty is deducted from the technician's score. A `QaSupervisor` resolves a finding standing at `OPEN` or `OVERDUE` — anything else is rejected with `ERR_FINDING_NOT_OPEN` — by supplying a non-empty `corrective_action_note` (`ERR_INVALID_REQUEST` without one); resolution recomputes the score, and the overdue penalty already incurred is *not* refunded. A `QaManager` may instead waive a finding, but only one standing at `OPEN` (`ERR_FINDING_NOT_OPEN`) and only when its severity is `MINOR` (`ERR_FINDING_NOT_MINOR`, HTTP 422); waiving refunds the `points_deducted` to the technician's score and lands the finding at `WAIVED`. `RESOLVED` and `WAIVED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify or transition an existing resource — including state transitions, patches, and the clock-setting capability — return a `200 OK` status code. Error responses carry the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/qa/_clock/set_current_utc` | Set the server's logical clock (test-driving) | QaManager |
| POST | `/qa/allergens` | Create an allergen | QaManager |
| GET | `/qa/allergens` | List allergens (filterable by `is_active`) | All roles |
| GET | `/qa/allergens/{allergenId}` | Get one allergen | All roles |
| POST | `/qa/production-lines` | Create a production line | QaManager |
| GET | `/qa/production-lines` | List production lines (filterable by `posture`) | All roles |
| GET | `/qa/production-lines/{lineId}` | Get one production line | All roles |
| POST | `/qa/line-allergen-matrix-entries` | Add an allergen handling row for a line | QaManager |
| GET | `/qa/line-allergen-matrix-entries` | List matrix entries (filterable by `line_id`, `allergen_id`) | All roles |
| GET | `/qa/line-allergen-matrix-entries/{entryId}` | Get one matrix entry | All roles |
| POST | `/qa/products` | Create a product | QaManager |
| GET | `/qa/products` | List products (filterable by `is_active`) | All roles |
| GET | `/qa/products/{productId}` | Get one product | All roles |
| PATCH | `/qa/products/{productId}` | Bump label revision or toggle active flag | QaManager |
| POST | `/qa/products/{productId}/supplier-allergen-change` | Record a supplier allergen change notification | QaManager |
| POST | `/qa/production-runs` | Create a production run (DRAFT) | QaSupervisor |
| GET | `/qa/production-runs` | List production runs (filterable by `line_id`, `product_id`, `status`) | All roles |
| GET | `/qa/production-runs/{runId}` | Get one production run | All roles |
| POST | `/qa/production-runs/{runId}/schedule` | Transition DRAFT to SCHEDULED (OCC on line version) | QaSupervisor |
| POST | `/qa/production-runs/{runId}/unschedule` | Transition SCHEDULED to DRAFT | QaSupervisor |
| POST | `/qa/production-runs/{runId}/start` | Transition SCHEDULED to IN_PROGRESS | LineOperator |
| POST | `/qa/production-runs/{runId}/complete` | Transition IN_PROGRESS to COMPLETED | LineOperator |
| POST | `/qa/production-runs/{runId}/reject` | Transition DRAFT to REJECTED | QaSupervisor |
| POST | `/qa/production-runs/{runId}/cancel` | Transition DRAFT or SCHEDULED to CANCELLED | QaSupervisor |
| POST | `/qa/changeover-procedures` | Create a new changeover procedure version (DRAFT) | QaManager |
| GET | `/qa/changeover-procedures` | List changeover procedures (filterable by `procedure_code`, `target_allergen_id`, `status`) | QaManager, QaSupervisor, QaTechnician, Auditor |
| GET | `/qa/changeover-procedures/{procedureId}` | Get one procedure | QaManager, QaSupervisor, QaTechnician, Auditor |
| POST | `/qa/changeover-procedures/{procedureId}/approve` | Approve a DRAFT procedure (OCC on procedure version) | QaManager |
| POST | `/qa/changeover-procedures/{procedureId}/retire` | Retire an APPROVED procedure not in active use | QaManager |
| POST | `/qa/changeovers` | Plan a changeover between two runs on a line | QaSupervisor |
| GET | `/qa/changeovers` | List changeovers (filterable by `line_id`, `from_run_id`, `to_run_id`, `procedure_id`, `status`) | All roles |
| GET | `/qa/changeovers/{changeoverId}` | Get one changeover | All roles |
| POST | `/qa/changeovers/{changeoverId}/begin` | Transition PLANNED to IN_EXECUTION | LineOperator |
| POST | `/qa/changeovers/{changeoverId}/finish-execution` | Transition IN_EXECUTION to SWAB_PENDING | LineOperator |
| POST | `/qa/changeovers/{changeoverId}/reswab` | Transition REWORK_REQUIRED to SWAB_PENDING | LineOperator |
| POST | `/qa/changeovers/{changeoverId}/cancel` | Cancel a PLANNED or IN_EXECUTION changeover | QaSupervisor |
| POST | `/qa/changeovers/{changeoverId}/swab-results` | Record a swab result against a SWAB_PENDING changeover | QaTechnician |
| GET | `/qa/swab-results` | List swab results (filterable by `changeover_id`, `outcome`, `recorded_by_id`) | QaManager, QaSupervisor, QaTechnician, Auditor |
| GET | `/qa/swab-results/{swabId}` | Get one swab result | QaManager, QaSupervisor, QaTechnician, Auditor |
| POST | `/qa/technicians` | Create a QA technician | QaManager |
| GET | `/qa/technicians` | List technicians (filterable by `status`) | QaManager, QaSupervisor, Auditor |
| GET | `/qa/technicians/{techId}` | Get one technician | QaManager, QaSupervisor, Auditor |
| POST | `/qa/technicians/{techId}/suspend` | Manually suspend a technician | QaManager |
| POST | `/qa/technicians/{techId}/reinstate` | Reinstate a suspended technician | QaManager |
| POST | `/qa/technicians/{techId}/separate` | Separate (terminate) a technician | QaManager |
| POST | `/qa/label-reconciliations` | Create a label reconciliation for a run | QaTechnician, QaSupervisor |
| GET | `/qa/label-reconciliations` | List label reconciliations (filterable by `run_id`, `verdict`, `status`) | QaManager, QaSupervisor, QaTechnician, Auditor |
| GET | `/qa/label-reconciliations/{reconId}` | Get one label reconciliation | QaManager, QaSupervisor, QaTechnician, Auditor |
| POST | `/qa/label-reconciliations/{reconId}/resolve` | Resolve a MATCH reconciliation | QaSupervisor |
| POST | `/qa/label-reconciliations/{reconId}/escalate` | Escalate an OPEN reconciliation to an incident | QaSupervisor |
| POST | `/qa/rework-batches` | Create a rework batch from a source run | LineOperator, QaSupervisor |
| GET | `/qa/rework-batches` | List rework batches (filterable by `source_run_id`, `source_product_id`, `status`) | All roles |
| GET | `/qa/rework-batches/{batchId}` | Get one rework batch | All roles |
| POST | `/qa/rework-batches/{batchId}/commit` | Commit a quantity of this batch into a target run | LineOperator |
| POST | `/qa/rework-batches/{batchId}/scrap` | Scrap a rework batch | QaSupervisor |
| POST | `/qa/incidents` | Manually raise an incident | QaSupervisor, QaManager |
| GET | `/qa/incidents` | List incidents (filterable by `line_id`, `product_id`, `allergen_id`, `source_label_reconciliation_id`, `source_changeover_id`, `status`, `severity`) | All roles |
| GET | `/qa/incidents/{incidentId}` | Get one incident | All roles |
| POST | `/qa/incidents/{incidentId}/begin-investigation` | Transition OPEN to INVESTIGATING | QaSupervisor |
| POST | `/qa/incidents/{incidentId}/contain` | Transition INVESTIGATING to CONTAINED | QaSupervisor |
| POST | `/qa/incidents/{incidentId}/close` | Transition CONTAINED to CLOSED (segregation of duties) | QaManager |
| POST | `/qa/incidents/{incidentId}/void` | Transition OPEN to VOID | QaManager |
| POST | `/qa/audit-findings` | Record an audit finding against a technician | Auditor |
| GET | `/qa/audit-findings` | List audit findings (filterable by `technician_id`, `auditor_id`, `status`) | QaManager, QaSupervisor, Auditor |
| GET | `/qa/audit-findings/{findingId}` | Get one audit finding | QaManager, QaSupervisor, Auditor |
| POST | `/qa/audit-findings/{findingId}/resolve` | Resolve a finding with a corrective action note | QaSupervisor |
| POST | `/qa/audit-findings/{findingId}/waive` | Waive a MINOR finding, refunding points | QaManager |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_STALE_LINE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROCEDURE_VERSION` | 412 Precondition Failed |
| `ERR_RUN_NOT_DRAFT` | 409 Conflict |
| `ERR_RUN_NOT_SCHEDULED` | 409 Conflict |
| `ERR_RUN_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_RUN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_RUN_OVERLAP` | 409 Conflict |
| `ERR_RUN_NOT_DUE` | 409 Conflict |
| `ERR_LINE_NOT_OPEN` | 409 Conflict |
| `ERR_LINE_ON_HOLD` | 409 Conflict |
| `ERR_ALLERGEN_PROHIBITED_ON_LINE` | 422 Unprocessable Entity |
| `ERR_ALLERGEN_INACTIVE` | 422 Unprocessable Entity |
| `ERR_PRODUCT_INACTIVE` | 422 Unprocessable Entity |
| `ERR_CHANGEOVER_MISSING` | 409 Conflict |
| `ERR_CHANGEOVER_NOT_VALIDATED` | 409 Conflict |
| `ERR_CHANGEOVER_NOT_PLANNED` | 409 Conflict |
| `ERR_CHANGEOVER_NOT_IN_EXECUTION` | 409 Conflict |
| `ERR_CHANGEOVER_NOT_REWORK` | 409 Conflict |
| `ERR_CHANGEOVER_TERMINAL` | 409 Conflict |
| `ERR_CHANGEOVER_BUDGET_SHORT` | 422 Unprocessable Entity |
| `ERR_LABEL_RECONCILIATION_OPEN` | 409 Conflict |
| `ERR_RECON_NOT_OPEN` | 409 Conflict |
| `ERR_RECON_NOT_MATCH` | 409 Conflict |
| `ERR_REWORK_NOT_AVAILABLE` | 409 Conflict |
| `ERR_REWORK_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_REWORK_CLASS_VIOLATION` | 422 Unprocessable Entity |
| `ERR_REWORK_ALLERGEN_BREACH` | 422 Unprocessable Entity |
| `ERR_REWORK_TERMINAL` | 409 Conflict |
| `ERR_TECH_NOT_ACTIVE` | 403 Forbidden |
| `ERR_TECH_NOT_CERTIFIED` | 403 Forbidden |
| `ERR_TECH_NOT_SUSPENDED` | 409 Conflict |
| `ERR_TECH_TERMINAL` | 409 Conflict |
| `ERR_INCIDENT_NOT_OPEN` | 409 Conflict |
| `ERR_INCIDENT_NOT_INVESTIGATING` | 409 Conflict |
| `ERR_INCIDENT_NOT_CONTAINED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_FINDING_NOT_OPEN` | 409 Conflict |
| `ERR_FINDING_NOT_MINOR` | 422 Unprocessable Entity |
| `ERR_PROCEDURE_NOT_DRAFT` | 409 Conflict |
| `ERR_PROCEDURE_NOT_APPROVED` | 409 Conflict |
| `ERR_PROCEDURE_IN_USE` | 409 Conflict |
| `ERR_SWAB_NOT_PENDING` | 409 Conflict |

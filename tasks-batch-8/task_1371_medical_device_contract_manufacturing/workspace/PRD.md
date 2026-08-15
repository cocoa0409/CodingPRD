# Medical Device Contract Manufacturing API — Product Requirements Document

## 1. Introduction

This document specifies the quality-system API of a medical device contract manufacturer operating under ISO 13485. The platform is the system of record for the full compliance lifecycle that begins at design transfer — where a Device Master Record revision is drafted, reviewed, and approved — and extends through process validation (installation, operational, and performance qualification), supplier qualification and monitoring, lot production with UDI labeling and component genealogy, and the post-market loop of nonconformance reports, corrective and preventive actions, complaints, and field actions.

Three persistent tensions in contract manufacturing shape the design. First, regulatory evidence must be segregated: the person who authors a record may never be the one who approves it, and the platform enforces that separation at the API level rather than by convention. Second, quality positions must be simultaneously current and auditable: supplier scores exist in a provisional and a finalized variant, shelf-life claims exist in a provisional and a confirmed variant, and the passage between the two is itself a controlled, side-effecting event. Third, time is a compliance input: quality agreements expire, revalidation falls due thirty-six months after validation, and audit intervals depend on risk tier — so the platform runs on a deterministic logical clock that administrators can advance, with every time-driven consequence (agreement expiry, revalidation sweeps, overdue flags) derived from it. All resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Six roles exist, spelled exactly as follows:

- `QualityEngineer` — QMS quality engineer: design-transfer drafting, validation execution, sterile-barrier studies, NCR and CAPA initiation and disposition, lot holds and scrap.
- `QualityManager` — approvals and dispositions of record: DMR approval and obsolescence, validation-phase approval and rejection, study completion, lot release, label approval and voiding, NCR closure, CAPA effectiveness verification.
- `ProductionOperator` — lot creation and completion, component genealogy recording, label creation and printing.
- `SupplierQualityEngineer` — supplier lifecycle, quality agreements, parts and receipts, change notifications, audits.
- `RegulatoryAffairs` — complaint intake, investigation, and closure, plus field actions.
- `QMSAdmin` — quality-system administrator: logical clock and manufacturing-line configuration only.

An attempt to invoke an operation outside the caller's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Every list and single-resource read endpoint is available to all six roles.

For each of the six roles — `QualityEngineer`, `QualityManager`, `ProductionOperator`, `SupplierQualityEngineer`, `RegulatoryAffairs`, and `QMSAdmin` alike — `X-User-ID` is an opaque operator identifier that is not tied to the `id` of any persisted entity. The server records it on the resources the operator touches (for example as `author_user_id` on a Device Master Record, `initiator_user_id` on a nonconformance report or a CAPA, `investigator_user_id` on a complaint, or the phase executor and approver fields on a validation protocol) and uses those recorded values for the segregation-of-duties comparisons of §2.6, but it never compares `X-User-ID` against any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

List responses include four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — Device Master Records, manufacturing lines, suppliers, quality agreements, supplier parts, change notifications, audits, validation protocols, sterile-barrier studies, lots, lot components, UDI labels, nonconformance reports, complaints, CAPAs, and field actions — carries the same four system-managed properties, with no exceptions:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T00:00:00.000Z`), fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one with every mutation of the resource.

Cascade-driven mutations count as mutations: when a system side effect changes a resource — a supplier suspended by a score recomputation, a study invalidated by a supersession, a lot held by a change-notification acceptance — that resource's `updated_at` refreshes and its `version` increments exactly as if a client had written it directly.

### 2.5. The Logical Clock and Time-Driven Sweeps

Every notion of "now" in the system — `notified_at` on a change notification, `received_at` on a complaint, `started_at` on a study, `completed_at` on an audit, `validated_at` on a protocol, `approved_at` on a DMR, `printed_at` on a label, `issued_at` on a field action, the effective windows of agreements, the notice windows of audits and change notifications, revalidation due dates, and audit-overdue evaluation — reads from a single logical clock, never from wall-clock time. At server startup the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock afterwards.

A `QMSAdmin`-only, test-driving capability advances the logical clock to a supplied `to_iso8601` instant. The clock is monotonic: an attempt to set it backwards — or to a value that is not a valid UTC ISO 8601 timestamp — is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400). A successful set responds with the new time as `current_utc` and fires exactly two sweeps within the same request:

1. **Agreement expiry sweep.** Every quality agreement in `ACTIVE` whose `effective_to` has been reached or passed (that is, now is at or after `effective_to`) transitions to `EXPIRED`. When that leaves a `QUALIFIED` supplier with no remaining `ACTIVE` agreement, the supplier is suspended with the full part-and-lot cascade described in §3.4.
2. **Revalidation sweep.** Every validation protocol in `VALIDATED` whose `revalidation_due_at` has been reached or passed transitions to `REVALIDATION_REQUIRED` with `revalidation_reason` `TIME_EXPIRY`, and the in-flight lots produced under it are placed on hold per §3.3.

No other entity is mutated by the clock. The audit-overdue flag of §2.9 is evaluated from the logical clock at read time rather than by a sweep.

### 2.6. Segregation of Duties

Regulatory evidence requires that the operator who creates or executes a record is never the one who approves or closes it. The platform enforces four such pairings, and a violation of any of them is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- The operator approving a Device Master Record revision must not be its `author_user_id`.
- The operator approving a validation phase must not be that phase's recorded executor (`iq_executor_user_id`, `oq_executor_user_id`, or `pq_executor_user_id`, according to the phase under review).
- The operator closing a nonconformance report must not be its `initiator_user_id`.
- The operator verifying CAPA effectiveness must not be the CAPA's `initiator_user_id`.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control; no other endpoint accepts a version field.

- **Quality-agreement creation** against a supplier requires the request to carry `expected_supplier_version` equal to that supplier's current `version`. If another writer has advanced the supplier's version since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed. The guard exists because creating an agreement legitimately supersedes the supplier's existing `DRAFT` agreements: a writer holding a stale supplier version would silently supersede an agreement it never saw. Successful creation itself increments the supplier's `version` by one as part of its side effects.
- **Successor-revision creation** against a Device Master Record requires `expected_dmr_version` equal to the parent revision's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Revision creation is only meaningful from the latest `APPROVED` revision, and a prior revision-creation or approval moves the version forward. Successful creation increments the parent revision's `version` by one.

Endpoints not named here take no version field at all.

### 2.8. Cascading State Propagation and the Lot Hold Model

A device lot carries two parallel, independent state dimensions. Its `disposition_status` walks the production line (`IN_PRODUCTION`, then `COMPLETED`, then `RELEASED`, with `SCRAPPED` and `RECALLED` as terminal outcomes), while its `hold_status` moves only between `CLEAR` and `ON_HOLD` regardless of how far production has progressed. Whenever a lot is held, its `hold_reason` records exactly one of `NONE`, `MANUAL`, `NCR_OPEN`, `SUPPLIER_QUALITY`, `REVALIDATION`, `STERILITY_FAILURE`, or `FIELD_ACTION`, and the release-hold resolution rules of §3.6 are keyed to that reason.

Many single operations mutate several entities at once: suspending a supplier flips its qualified parts to `ON_HOLD` and holds the in-flight lots that consume them; scrapping a lot voids its labels and auto-dispositions its open nonconformance reports; issuing a field action recalls whole bands of lots. The consistency model is **immediate**: every mutation and every cascade it triggers is visible in that same request's response and in all subsequent reads — there is no eventual-consistency window anywhere in the system.

One stability rule keeps cascades predictable: a cascade that would place a lot on hold is a no-op when the lot is already `ON_HOLD`. The existing `hold_reason` is retained, and the hold is not re-stacked or re-attributed.

### 2.9. Supplier Quality Scoring, Risk Tiering, and Audit Cadence

Each supplier carries two quality scores in parallel. The **current** score, `quality_score`, reflects everything the system knows right now; the **finalized** score, `quality_score_finalized`, counts only what has been closed out, and it alone drives the supplier's `risk_tier`.

Penalty arithmetic is shared by both variants. A nonconformance report whose `fault` is `SUPPLIER` contributes a severity penalty — 5 points for `MINOR`, 15 for `MAJOR`, 30 for `CRITICAL`. A completed audit contributes twice its `findings_count` plus eight times its `major_findings_count`. A report counts against a supplier when its `supplier_part_id` belongs to that supplier, or — when only a `lot_id` is set — when the lot's recorded component genealogy includes a part of that supplier. The accumulators differ only in which reports they count: `applied_penalty_points` sums supplier-fault reports in `DISPOSITIONED` or `CLOSED` plus all completed-audit penalties, while `applied_finalized_penalty_points` counts only supplier-fault reports in `CLOSED` plus the same completed-audit penalties. Each score is one hundred minus its accumulator, floored at zero: `quality_score` never falls below 0, and neither does `quality_score_finalized`. Scores are carried at one decimal place with round-half-up; because every penalty term is an integer, both scores are integral in practice. Closing a supplier-fault report moves its penalty from the provisional accumulator into the finalized one; reopening a report reverses its penalty from the provisional accumulator exactly.

The `risk_tier` derives from `quality_score_finalized` alone: `LOW` when the finalized score is at least 90, `MEDIUM` when it is at least 70 but below 90, and `HIGH` below 70.

Whenever a recomputation leaves `quality_score` below 50 on a supplier that is `QUALIFIED`, the supplier is automatically suspended — with the same part-and-lot cascade as a manual suspension (§3.4). This auto-suspension fires from both penalty entry points: nonconformance disposition and audit completion.

Audit cadence follows the tier. `next_audit_due_at` is `last_audit_completed_at` plus 24 months for `LOW`, 12 months for `MEDIUM`, or 6 months for `HIGH`, using calendar-month arithmetic (§2.12). A supplier that has never been audited is due at its `created_at` plus 12 months. `is_audit_overdue` is true when `next_audit_due_at` is at or before the logical now — the comparison is inclusive, so an audit due exactly now counts as overdue — except that a `DISQUALIFIED` supplier is never flagged overdue.

### 2.10. Validation Order

Every request passes a fixed twelve-step validation pipeline, and a failure at any step masks all later checks — the caller sees the earliest applicable error, never a later one:

1. **Header context.** `X-User-ID` and `X-User-Role` are present and the role is one of the six declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role permission.** The role is permitted for this endpoint (`ERR_FORBIDDEN_ROLE`).
3. **Body shape.** Required fields are present, types match, enum values are valid, integer ranges are respected (quantities strictly positive where required, finding counts non-negative), datetime strings parse, and window orderings hold — `scope_mfg_start` strictly before `scope_mfg_end`, `scheduled_start` strictly before `scheduled_end`, `planned_start` strictly before `planned_end`. At the same priority, label creation enforces the GS1 check digit on `udi_di`, and a nonconformance report must reference at least one of `lot_id` or `supplier_part_id` (`ERR_VALIDATION`, and for the check digit `ERR_UDI_CHECK_DIGIT_MISMATCH`).
4. **Existence.** Path identifiers are resolved left to right, then body-referenced foreign keys — `dmr_id`, `line_id`, `supplier_part_id`, `lot_id`, `validation_protocol_id`, `source_complaint_id`, `source_ncr_id`, `reason_complaint_id` — are resolved (`ERR_NOT_FOUND`).
5. **Optimistic concurrency.** On the two version-guarded endpoints of §2.7, the expected version matches (`ERR_STALE_VERSION`).
6. **Segregation of duties.** The four self-approval prohibitions of §2.6 (`ERR_SEGREGATION_OF_DUTIES`).
7. **State-machine shape.** The trigger is a declared transition from the entity's current state; terminal states accept nothing (`ERR_INVALID_STATE_TRANSITION`).
8. **Named state preconditions.** Hold `CLEAR` for release (`ERR_LOT_ON_HOLD`), sterility not already resulted (`ERR_STERILITY_ALREADY_RESULTED`), lot `COMPLETED` for label printing (`ERR_LOT_NOT_COMPLETED`), and the hold-resolution conditions (`ERR_HOLD_CONDITION_UNRESOLVED`).
9. **Release safety gates and their kin.** Sterility passed for sterile devices (`ERR_STERILITY_NOT_PASSED`), protocol validated (`ERR_PROTOCOL_NOT_VALIDATED`), no open nonconformance (`ERR_OPEN_NCRS_EXIST`), printed label with matching revision (`ERR_NO_PRINTED_LABEL`), DMR approved (`ERR_DMR_NOT_APPROVED`), and the complaint-intake gate requiring a released or recalled lot (`ERR_LOT_NOT_RELEASED`).
10. **Temporal windows.** Agreement in effect (`ERR_AGREEMENT_NOT_IN_EFFECT`), change-notice window (`ERR_CHANGE_NOTICE_WINDOW_BREACHED`), audit-window overlap (`ERR_AUDIT_WINDOW_OVERLAP`), audit-notice window (`ERR_AUDIT_NOTICE_WINDOW_BREACHED`), and line changeover conflicts (`ERR_LINE_WINDOW_CONFLICT`).
11. **Cross-reference coherence.** Part belongs to the path supplier (`ERR_PART_NOT_OF_SUPPLIER`), protocol validates the lot's DMR (`ERR_PROTOCOL_DMR_MISMATCH`), label revision matches the family's approved revision (`ERR_LABEL_REVISION_MISMATCH`), CAPA source linkage matches its `source_type` and DMR (`ERR_SOURCE_MISMATCH`), the field-action reason complaint is actionable (`ERR_COMPLAINT_NOT_ACTIONABLE`), and the DMR-approved gate on protocol creation (`ERR_DMR_NOT_APPROVED`).
12. **Uniqueness and capacity.** Revision uniqueness (`ERR_DUPLICATE_DMR_REVISION`), unique codes (`ERR_DUPLICATE_CODE`), component-lot uniqueness (`ERR_DUPLICATE_COMPONENT_LOT`), one active study per DMR (`ERR_STUDY_ALREADY_ACTIVE`), one active label per lot (`ERR_ACTIVE_LABEL_EXISTS`), sufficient part quantity (`ERR_INSUFFICIENT_PART_QUANTITY`), supplier not disqualified (`ERR_SUPPLIER_DISQUALIFIED`), and part/supplier qualification for component commit (`ERR_PART_NOT_QUALIFIED`).

### 2.11. Nested Resource Retrieval

Several creation endpoints live under a parent path — a supplier's agreements, parts, change notifications, and audits are addressed through a `supplierId` segment; a lot's components and labels through a `lotId` segment; a DMR's successor revisions through the revision's own `id` segment. Path identifiers are validated strictly left to right: the request is rejected with a 404 `ERR_NOT_FOUND` for the *first* path identifier that does not correspond to an existing resource, before later segments are even examined. Body-referenced foreign keys are checked only after every path identifier has resolved, per the pipeline order of §2.10.

### 2.12. Numeric Precision, Rounding, and Calendar Arithmetic

Numeric and temporal rules are uniform across the platform:

- The complaint rate `complaint_rate_per_100k` is rounded half-up to exactly 4 decimal places.
- Supplier scores are carried at 1 decimal place with round-half-up (all penalty terms are integers, so scores are integral in practice).
- Sterility sampling works in integer units; a single ceiling is applied after the critical-component multiplier, with no intermediate rounding.
- Shelf-life and expiry arithmetic is done in integer months; `expiry_date` is stored at second precision in UTC.
- Calendar-month arithmetic — used for lot expiry, `revalidation_due_at`, and `next_audit_due_at` — preserves the day-of-month, clamps to the last day of the target month when that month is shorter, and preserves the time-of-day.
- Datetime comparisons are made at second precision; whether a boundary is inclusive or exclusive is stated with each rule that performs one.

## 3. Business Logic & Workflows

### 3.1. Design Transfer: Device Master Records and the Revision Chain

A `QualityEngineer` opens design transfer by creating the first revision of a Device Master Record, supplying a `device_code` for the device family, a `revision_code` label such as "A", a `sterile` flag indicating whether the device is supplied sterile, and a strictly positive `shelf_life_claim_months`. The pairing of `device_code` and `revision_code` must be unique across all revisions; a collision is rejected with `ERR_DUPLICATE_DMR_REVISION`. The new revision starts in `DRAFT` with `revision_seq` 1, a null `parent_dmr_id`, the caller recorded as `author_user_id`, `approver_user_id` and `approved_at` null, `confirmed_shelf_life_months` null, and its complaint metrics — `complaint_rate_per_100k` at 0 and `field_action_review_required` false — in their initial state.

Approval is the preserve of a `QualityManager`, applies only from `DRAFT` (anything else is `ERR_INVALID_STATE_TRANSITION`), and is subject to segregation of duties: the approver must not be the revision's author. Approval stamps `approver_user_id` and `approved_at` from the logical clock, and it supersedes the rest of the family: any other revision of the same `device_code` that is currently `APPROVED` — including revisions reachable through the `parent_dmr_id` chain — transitions to `SUPERSEDED`, and every sterile-barrier study of each such superseded revision that is still `IN_PROGRESS` transitions to `INVALIDATED`. The `APPROVED` to `SUPERSEDED` transition is therefore always system-driven; no client ever requests it directly.

When the design evolves, a `QualityEngineer` creates a successor revision against an existing revision. The parent revision must be `APPROVED` — a revision-creation attempted against a revision in any other status is rejected with `ERR_DMR_NOT_APPROVED` — and the request must carry `expected_dmr_version` under the optimistic-concurrency rules of §2.7. The successor inherits the parent's `device_code`, takes the caller-supplied `revision_code`, `shelf_life_claim_months`, and `sterile`, receives `revision_seq` one greater than its parent's, records the parent revision in `parent_dmr_id`, and starts in `DRAFT`. The same uniqueness rule on the `device_code` and `revision_code` pair applies to successors. Approving the successor later supersedes the parent automatically, per the approval cascade above.

Obsolescence retires a revision from `APPROVED` or `SUPERSEDED` to the terminal `OBSOLETE` state. A `QualityManager` is refused with `ERR_LOTS_IN_FLIGHT` while any lot references the revision with disposition `IN_PRODUCTION` or `COMPLETED`, and with `ERR_PROTOCOLS_IN_FLIGHT` while any validation protocol references it in `DRAFT`, `IQ_EXECUTION`, `IQ_REVIEW`, `OQ_EXECUTION`, `OQ_REVIEW`, `PQ_EXECUTION`, or `PQ_REVIEW`. Obsolescence also invalidates the revision's sterile-barrier studies that are still `IN_PROGRESS`.

Reading a revision returns its computed fields alongside the inputs: the single-record view includes `complaint_rate_per_100k` and `field_action_review_required`, whose derivation lives with the complaint workflow in §3.7. The revision list can be filtered by `device_code`, by `status`, and by `parent_dmr_id` to walk a revision chain.

The `sterile` flag is not decorative: it gates sterile-barrier study creation in §3.2 and the sterility release gate in §3.6.

### 3.2. Sterile Barrier Studies and the Shelf-Life Ladder

Because sterility claims must be evidenced, a `QualityEngineer` starts a sterile-barrier study against a DMR by supplying its `dmr_id`, a `study_type` of `REAL_TIME` or `ACCELERATED`, and a strictly positive `claimed_months`. The target revision must be `APPROVED` (`ERR_DMR_NOT_APPROVED`) and must be a sterile device — a study against a non-sterile DMR is rejected with `ERR_DMR_NOT_STERILE`. At most one study may be `IN_PROGRESS` per DMR at a time; a second attempt is refused with `ERR_STUDY_ALREADY_ACTIVE`. The study stamps `started_at` from the logical clock and begins in `IN_PROGRESS`. Studies can be listed filtered by `dmr_id` and `status`.

Completion is a `QualityManager` decision expressed through a `passed` flag. Completing with `passed` true requires `result_months_confirmed` in the request and moves the study to `PASSED`: the DMR's `confirmed_shelf_life_months` is set to `result_months_confirmed`, and the expiry of every lot of that DMR still in `IN_PRODUCTION` or `COMPLETED` is recomputed under the final variant below, flipping each such lot's `expiry_basis` to `FINAL`. Lots already `RELEASED` or `RECALLED` keep their pinned expiry untouched — what shipped, shipped. Completing with `passed` false moves the study to `FAILED` and forces revalidation: every validation protocol of that DMR currently `VALIDATED` transitions to `REVALIDATION_REQUIRED` with `revalidation_reason` `STUDY_FAILURE`, and the lot-hold cascade of §3.3 fires for each. Independently of completion, a study still `IN_PROGRESS` is invalidated — moved to `INVALIDATED` — whenever its DMR revision is superseded or obsoleted. `PASSED`, `FAILED`, and `INVALIDATED` are all terminal.

Every lot's shelf life sits on a two-rung ladder, computed at lot creation and recomputed only when a study passes. While the lot's DMR has no `PASSED` study, the **provisional** variant applies: the expiry month count is half of `shelf_life_claim_months` rounded up to a whole month, capped at twelve months, and the lot's `expiry_basis` is `PROVISIONAL`. Once a study has passed, the **final** variant applies: the month count is `confirmed_shelf_life_months` capped at sixty months, and the basis is `FINAL`. In both variants the lot's `expiry_date` is its `manufactured_at` plus the computed number of months, using the calendar-month arithmetic of §2.12 (same day-of-month, clamped to month end, time-of-day preserved).

### 3.3. Process Validation: Lines, the IQ/OQ/PQ Pipeline, and Revalidation

Before any protocol can be scheduled, a `QMSAdmin` registers manufacturing lines. A line carries a unique `line_code` (collisions rejected with `ERR_DUPLICATE_CODE`), an optional free-text `description` defaulting to an empty string, and an optional `changeover_buffer_hours` defaulting to 24 — the mandatory gap between validation windows on that line.

A `QualityEngineer` then creates a validation protocol with a unique `protocol_code`, the `dmr_id` of the pinned revision under validation (which must be `APPROVED`, else `ERR_DMR_NOT_APPROVED`), the `line_id` of the reserved line, and a planned window from `planned_start` (inclusive) to `planned_end` (inclusive), with the start strictly before the end (`ERR_VALIDATION`). Line occupancy is enforced with the changeover buffer: protocols in `DRAFT`, `IQ_EXECUTION`, `IQ_REVIEW`, `OQ_EXECUTION`, `OQ_REVIEW`, `PQ_EXECUTION`, or `PQ_REVIEW` occupy their line, and a new protocol is rejected with `ERR_LINE_WINDOW_CONFLICT` when the gap between its window and any occupying protocol's window — measured from the earlier window's `planned_end` to the later window's `planned_start`, in either direction — is strictly less than the line's `changeover_buffer_hours`. A gap of exactly the buffer, or more, is acceptable. Protocols that have reached `VALIDATED` or `REVALIDATION_REQUIRED` no longer occupy their line. A new protocol starts in `DRAFT` with `generation` 1, all phase executor and approver identifiers null, and `revalidation_reason` `NONE`. Protocols can be listed filtered by `dmr_id`, `line_id`, and `status`.

Execution follows the classic three-phase pipeline, with strict segregation at every gate. Beginning execution moves a protocol from `DRAFT` — or, in a later cycle, from `REVALIDATION_REQUIRED` — to `IQ_EXECUTION`; the pinned DMR must be `APPROVED` at that moment (`ERR_DMR_NOT_APPROVED`). When execution begins from `REVALIDATION_REQUIRED`, a new validation cycle starts: `generation` increments by one, all six phase identifiers (`iq_executor_user_id`, `iq_approver_user_id`, `oq_executor_user_id`, `oq_approver_user_id`, `pq_executor_user_id`, `pq_approver_user_id`) are cleared, and `revalidation_reason` resets to `NONE`.

A `QualityEngineer` submits each finished execution phase for review — `IQ_EXECUTION` to `IQ_REVIEW`, `OQ_EXECUTION` to `OQ_REVIEW`, `PQ_EXECUTION` to `PQ_REVIEW` — and is recorded as that phase's executor. A `QualityManager` then decides each review. Approval is forbidden to the phase's executor (`ERR_SEGREGATION_OF_DUTIES`): approving `IQ_REVIEW` records `iq_approver_user_id` and advances to `OQ_EXECUTION`; approving `OQ_REVIEW` records `oq_approver_user_id` and advances to `PQ_EXECUTION`; approving `PQ_REVIEW` records `pq_approver_user_id` and completes the cycle — the protocol becomes `VALIDATED`, `validated_at` is stamped from the logical clock, `revalidation_due_at` is set to thirty-six months (three years) after `validated_at`, and `revalidation_reason` is `NONE`. Rejection instead returns the phase to its execution state and clears that phase's executor identifier, so rework may be performed by any quality engineer.

A validated process does not stay validated forever. The `VALIDATED` to `REVALIDATION_REQUIRED` transition is only ever system-driven, by exactly four triggers, each recording its `revalidation_reason`: the logical clock reaching `revalidation_due_at` (`TIME_EXPIRY`, via the sweep of §2.5); acceptance of a `MAJOR` supplier change affecting a critical part used by the validated revision's lots (`SUPPLIER_CHANGE`, §3.5); a process-changing CAPA entering implementation (`CAPA_PROCESS_CHANGE`, §3.7); or a sterile-barrier study of the DMR failing (`STUDY_FAILURE`, §3.2). Whichever trigger fires, every lot produced under the protocol that is still `IN_PRODUCTION` or `COMPLETED` is placed `ON_HOLD` with `hold_reason` `REVALIDATION`.

### 3.4. Supplier Lifecycle: Qualification, Agreements, and Audits

A `SupplierQualityEngineer` registers a supplier with a unique `supplier_code` and a legal `name`. The supplier begins in `PENDING_QUALIFICATION` with `quality_score` and `quality_score_finalized` both at 100, `risk_tier` `LOW`, `last_audit_completed_at` null, `next_audit_due_at` set to its `created_at` plus twelve months, and `is_audit_overdue` false. The supplier list can be filtered by `status`.

Qualification is gated on a contractual foundation. A `SupplierQualityEngineer` drafts a quality agreement under the supplier's path, supplying a unique `agreement_code`, the `audit_rights_granted` flag, the `effective_from` and `effective_to` window, optionally `audit_notice_days` (defaulting to 30) and `change_notice_days` (defaulting to 90), and — because creation is version-guarded — `expected_supplier_version` per §2.7. The new agreement starts in `DRAFT`, and its creation supersedes every existing `DRAFT` agreement of the same supplier; an `ACTIVE` agreement is not disturbed by a mere draft. Activation moves an agreement from `DRAFT` to `ACTIVE` and enforces its temporal window: now must be at or after `effective_from` and strictly before `effective_to` (`ERR_AGREEMENT_NOT_IN_EFFECT`), and the supplier must not be `DISQUALIFIED` (`ERR_SUPPLIER_DISQUALIFIED`). Activating one agreement supersedes any other `ACTIVE` agreement of the same supplier. Termination moves an `ACTIVE` agreement to `TERMINATED`, and when that leaves the supplier with no `ACTIVE` agreement while the supplier is `QUALIFIED`, the supplier is suspended on the spot with the full cascade below; the identical rule fires when the clock sweep of §2.5 expires a supplier's last `ACTIVE` agreement. `SUPERSEDED`, `EXPIRED`, and `TERMINATED` are all terminal for an agreement. Agreements can be listed filtered by `supplier_id` and `status`.

With an `ACTIVE` agreement in place, a `SupplierQualityEngineer` qualifies the supplier: `PENDING_QUALIFICATION` to `QUALIFIED` is refused without one (`ERR_NO_ACTIVE_QUALITY_AGREEMENT`).

Suspension — `QUALIFIED` to `SUSPENDED` — happens two ways: manually, at a `SupplierQualityEngineer`'s hand, or automatically the moment a recomputed `quality_score` falls below 50. Either way the consequences are identical: every `QUALIFIED` part of the supplier moves to `ON_HOLD`, and every lot in `IN_PRODUCTION` or `COMPLETED` whose recorded components include any of those parts is placed `ON_HOLD` with `hold_reason` `SUPPLIER_QUALITY`.

Reinstatement from `SUSPENDED` to `QUALIFIED` requires the supplier's `quality_score` to be at least 50 (`ERR_SCORE_BELOW_REINSTATE_THRESHOLD`) and at least one `ACTIVE` quality agreement (`ERR_NO_ACTIVE_QUALITY_AGREEMENT`). Reinstatement returns the supplier's `ON_HOLD` parts to `QUALIFIED`, but it deliberately does not release lot holds wholesale — each held lot must be cleared individually under the resolution rules of §3.6.

Disqualification is terminal. From `QUALIFIED` or `SUSPENDED`, a `SupplierQualityEngineer` may disqualify a supplier: every part of the supplier in `QUALIFIED` or `ON_HOLD` becomes `DISQUALIFIED`, in-flight lots containing those parts are held `SUPPLIER_QUALITY`, and any `ACTIVE` quality agreement of the supplier is `TERMINATED`. A `DISQUALIFIED` supplier blocks agreement activation and is exempt from audit-overdue flagging (§2.9).

Audits close the monitoring loop. Scheduling an audit under a supplier's path takes `scheduled_start` and `scheduled_end` — the start strictly before the end — defining a half-open window: the start instant is occupied, the end instant is free, so two audits whose endpoints merely touch do not overlap. An audit whose window overlaps another `SCHEDULED` audit of the same supplier is rejected with `ERR_AUDIT_WINDOW_OVERLAP`, and the window's start must respect the notice period of the supplier's `ACTIVE` agreement — `scheduled_start` must be at least `audit_notice_days` days after now (`ERR_AUDIT_NOTICE_WINDOW_BREACHED`). Completing a `SCHEDULED` audit records `findings_count` and `major_findings_count` (both non-negative): `penalty_points` is set to twice the minor findings plus eight times the major findings, that penalty is added to both `applied_penalty_points` and `applied_finalized_penalty_points`, both scores and the `risk_tier` are recomputed per §2.9, `last_audit_completed_at` and `completed_at` are stamped from the logical clock, `next_audit_due_at` is recomputed from the current tier, and if the recomputed `quality_score` has fallen below 50 on a `QUALIFIED` supplier the automatic suspension cascade fires. Cancelling a `SCHEDULED` audit moves it to `CANCELLED` with no scoring effect at all. Audits can be listed filtered by `supplier_id` and `status`.

### 3.5. Supplier Parts, Receipts, and Change Notifications

Parts are registered under a supplier's path by a `SupplierQualityEngineer` with a `part_number` unique within that supplier (`ERR_DUPLICATE_CODE`), a `description`, and an optional `critical` flag defaulting to false — critical parts drive the sampling multiplier of §3.6 and widen the revalidation scope of accepted changes below. A new part starts `QUALIFIED` with all five quantity buckets at zero.

Inventory moves through the buckets in a strict choreography. A receipt carrying a strictly positive `quantity` adds that amount to both `quantity_received` and `quantity_remaining`. From there, `quantity_remaining` holds uncommitted stock; recording a component into a lot moves units into `quantity_committed` (and removing the component moves them back); releasing a lot moves its consumed units from `quantity_committed` into `quantity_in_released_lots`; scrapping a lot moves them into `quantity_in_scrapped_lots` instead. Units counted in `quantity_in_released_lots` cover both `RELEASED` and `RECALLED` lots. The part list can be filtered by `supplier_id` and `status`.

A part leaves `QUALIFIED` for `ON_HOLD` only through system cascades — supplier suspension, a supplier-fault nonconformance disposition (§3.7), or acceptance of a `MAJOR` change notification on it — and each of those cascades also holds the in-flight lots containing the part (`SUPPLIER_QUALITY`). Releasing a part hold is a `SupplierQualityEngineer` action with two guards: the supplier must be neither `SUSPENDED` nor `DISQUALIFIED` (`ERR_SUPPLIER_NOT_CLEAR`), and no change notification on that part may be sitting in `SUBMITTED` or `UNDER_REVIEW` (`ERR_SCN_PENDING`). Parts driven to `DISQUALIFIED` by supplier disqualification are terminal.

Supplier change notifications keep process changes visible before they land. A `SupplierQualityEngineer` submits one under the supplier's path with a `change_description`, an `impact_class` of `MINOR` or `MAJOR`, a `proposed_effective_date`, and optionally a `supplier_part_id` scoping the change — when present, that part must belong to the path supplier (`ERR_PART_NOT_OF_SUPPLIER`). The notification stamps `notified_at` from the logical clock at submission, and the proposed date must respect the contractual notice period: the gap from `notified_at` to `proposed_effective_date` must be at least the `change_notice_days` of the supplier's `ACTIVE` agreement (`ERR_CHANGE_NOTICE_WINDOW_BREACHED`). Review moves the notification `SUBMITTED` → `UNDER_REVIEW` → `ACCEPTED` or `REJECTED`, with both outcomes terminal.

Acceptance is where impact class bites. A `MINOR` acceptance changes nothing downstream. A `MAJOR` acceptance with a part scope places that part `ON_HOLD` if it was `QUALIFIED` and cascades `SUPPLIER_QUALITY` holds to its in-flight lots; and when the affected part is `critical`, every validation protocol in `VALIDATED` whose pinned DMR revision has lots containing that part transitions to `REVALIDATION_REQUIRED` with `revalidation_reason` `SUPPLIER_CHANGE` — each such transition holding its own in-flight lots with `hold_reason` `REVALIDATION`. Notifications can be listed filtered by `supplier_id`, `supplier_part_id`, and `status`.

### 3.6. Lot Production, Component Genealogy, and Label Control

Production begins when a `ProductionOperator` creates a device lot. The `lot_number` must be unique within its DMR (`ERR_DUPLICATE_CODE`); the `dmr_id` must reference an `APPROVED` revision (`ERR_DMR_NOT_APPROVED`); and the `validation_protocol_id` must reference a protocol pinned to that same DMR revision (`ERR_PROTOCOL_DMR_MISMATCH`) — though the protocol need not be `VALIDATED` yet: production under validation-in-progress is permitted, while release is not. The operator also supplies a strictly positive `quantity` and the `manufactured_at` timestamp, which drives both the expiry computation and later field-action scoping. A new lot starts with `disposition_status` `IN_PRODUCTION`, `hold_status` `CLEAR` with `hold_reason` `NONE`, `sterility_result` `PENDING`, and an `expiry_date` computed under the ladder of §3.2 — provisional or final according to the study state of its DMR. The lot list can be filtered by `dmr_id`, `validation_protocol_id`, `disposition_status`, and `hold_status`.

Component genealogy is recorded while the lot is `IN_PRODUCTION`: each component entry names a `supplier_part_id`, a strictly positive `quantity_used`, and the supplier's own `supplier_lot_number` for batch genealogy. The referenced part must be `QUALIFIED` and its supplier must be `QUALIFIED` (`ERR_PART_NOT_QUALIFIED`); `quantity_used` may not exceed the part's `quantity_remaining` (`ERR_INSUFFICIENT_PART_QUANTITY`); and the triple of lot, part, and supplier lot number must be unique (`ERR_DUPLICATE_COMPONENT_LOT`). Recording a component moves `quantity_used` from the part's remaining bucket into its committed bucket; removing a component — permitted only while its lot is still `IN_PRODUCTION`, and answered with a 204 No Content on success — moves the same units back. Components can be listed filtered by `lot_id` and `supplier_part_id`.

Completion is a `ProductionOperator` action requiring at least one recorded component (`ERR_NO_COMPONENTS_RECORDED`). It moves the lot from `IN_PRODUCTION` to `COMPLETED` and computes the sterility sample size. Process maturity decides the regime: when fewer than three sibling lots under the same validation protocol have reached `RELEASED` or `RECALLED`, the process is immature and `sample_qty` equals the entire `quantity` — a 100% inspection. Once at least three such siblings exist, a tiered base applies instead: a quantity of 25 or fewer samples the full quantity; 26 to 150 samples 20 units; 151 to 1,200 samples 32; 1,201 to 10,000 samples 80; and above 10,000 samples 125. If any recorded component of the lot references a part flagged `critical`, that base is multiplied by one and a half and rounded up to the next whole unit — a single ceiling with no intermediate rounding. The final `sample_qty` is the smaller of the lot's `quantity` and the computed base, and `releasable_qty` is `quantity` minus `sample_qty`.

Sterility is recorded once, by a `QualityEngineer`, on a `COMPLETED` lot (any other disposition is `ERR_INVALID_STATE_TRANSITION`) whose `sterility_result` is still `PENDING` — a lot already resulted answers `ERR_STERILITY_ALREADY_RESULTED`. The request carries the `result`: `PASSED` or `FAILED`. A `FAILED` result immediately places the lot `ON_HOLD` with `hold_reason` `STERILITY_FAILURE`, a hold that can never be cleared.

Holds are the lot's safety brake. A `QualityEngineer` may place a manual hold on an `IN_PRODUCTION` or `COMPLETED` lot whose hold is `CLEAR`, setting `hold_reason` `MANUAL`; system cascades set the other reasons, and per §2.8 a cascade landing on an already-held lot changes nothing. Releasing a hold re-verifies the reason's resolution condition and fails with `ERR_HOLD_CONDITION_UNRESOLVED` when it is not met: an `NCR_OPEN` hold clears only when no nonconformance report of the lot remains `OPEN` or `CONTAINED`; a `SUPPLIER_QUALITY` hold clears only when every component part of the lot is back to `QUALIFIED`; a `REVALIDATION` hold clears only when the lot's validation protocol is `VALIDATED` again; a `MANUAL` hold always clears; and `STERILITY_FAILURE` and `FIELD_ACTION` holds never clear through this operation. A successful release returns the lot to `CLEAR` and resets `hold_reason` to `NONE`.

Labeling binds the lot to the UDI system. A `ProductionOperator` creates a label for a lot by supplying `udi_di`: exactly fourteen digits, of which the final digit must be the GS1 check digit over the first thirteen — each of the thirteen digits is weighted 3 or 1 in strict alternation counting from the right, the rightmost of the thirteen carrying weight 3; the weighted sum is taken modulo ten; and the expected check digit is ten minus that remainder, modulo ten. A mismatch is rejected with `ERR_UDI_CHECK_DIGIT_MISMATCH`. The server computes `udi_pi` as the literal prefix `LOT-` followed by the lot's `lot_number`, then `-EXP-`, then the lot's `expiry_date` formatted as YYYYMMDD; it pins `label_revision` to the `revision_code` of the lot's DMR revision; and it starts the label in `DRAFT`. Labels can be listed filtered by `lot_id` and `status`.

Approval, printing, and voiding complete the label lifecycle. A `QualityManager` approves a `DRAFT` label under three gates: no other label of the same lot may be `APPROVED` or `PRINTED` (`ERR_ACTIVE_LABEL_EXISTS`); the label's `label_revision` must equal the `revision_code` of the currently `APPROVED` revision of the lot's device-code family (`ERR_LABEL_REVISION_MISMATCH`) — and when no revision of that family is `APPROVED` at all, because the lot's revision was superseded or obsoleted, approval instead fails with `ERR_DMR_NOT_APPROVED`; and the lot must still be `IN_PRODUCTION` or `COMPLETED`. A `ProductionOperator` then prints an `APPROVED` label once the lot is `COMPLETED` (`ERR_LOT_NOT_COMPLETED`), stamping `printed_at`. Voiding moves a label from `DRAFT`, `APPROVED`, or `PRINTED` to the terminal `VOID`: a `QualityManager` voids manually with `void_reason` `MANUAL`; scrapping the lot voids its labels in any of those three states with `void_reason` `LOT_SCRAPPED`; recalling the lot voids its `APPROVED` and `PRINTED` labels with `void_reason` `LOT_RECALLED` (a `DRAFT` label survives a recall).

Release is the most heavily gated action in the system, performed by a `QualityManager` and evaluated under the pipeline order of §2.10. The lot must be `COMPLETED` (`ERR_INVALID_STATE_TRANSITION`); its hold must be `CLEAR` (`ERR_LOT_ON_HOLD`); when the lot's DMR is sterile, `sterility_result` must be `PASSED` (`ERR_STERILITY_NOT_PASSED`); the validation protocol the lot was produced under must be `VALIDATED` (`ERR_PROTOCOL_NOT_VALIDATED`); no nonconformance report of the lot may be `OPEN` or `CONTAINED` (`ERR_OPEN_NCRS_EXIST`); at least one label of the lot must be `PRINTED` with a `label_revision` equal to the lot's pinned DMR `revision_code` (`ERR_NO_PRINTED_LABEL`); and the lot's DMR must be `APPROVED` (`ERR_DMR_NOT_APPROVED`). On release the lot becomes `RELEASED`, each component's `quantity_used` moves from the part's committed bucket into `quantity_in_released_lots`, and the DMR's complaint rate is recomputed with this lot's `releasable_qty` entering the denominator (§3.7).

Scrapping is a `QualityEngineer` action from `IN_PRODUCTION` or `COMPLETED`. Each component's committed units move into `quantity_in_scrapped_lots`; the lot's labels in `DRAFT`, `APPROVED`, or `PRINTED` are voided with `void_reason` `LOT_SCRAPPED`; and the lot's nonconformance reports in `OPEN` or `CONTAINED` are auto-dispositioned to `DISPOSITIONED` with `disposition` `SCRAP` and their `fault` unchanged — no supplier penalty accrues from that auto-disposition while the fault remains `UNDETERMINED`. `SCRAPPED` is terminal.

Recall — `RELEASED` to `RECALLED` — is never a direct client action on the lot; it is only ever the system's doing when a field action is issued (§3.7). Recall voids the lot's `APPROVED` and `PRINTED` labels (`LOT_RECALLED`) and recomputes the DMR's complaint rate with this lot's `releasable_qty` leaving the denominator.

### 3.7. Nonconformance, Complaints, CAPA, and Field Actions

A `QualityEngineer` opens a nonconformance report with a unique `ncr_code`, a `description`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and at least one of `lot_id` or `supplier_part_id` — a report referencing neither is rejected with `ERR_VALIDATION`. The report starts `OPEN` with `fault` `UNDETERMINED`, `disposition` `NONE`, the caller recorded as `initiator_user_id`, and `penalty_points_applied` at 0. Creation is itself a containment signal: when the referenced lot is `IN_PRODUCTION` or `COMPLETED`, it is placed `ON_HOLD` with `hold_reason` `NCR_OPEN`. Reports can be listed filtered by `lot_id`, `supplier_part_id`, `status`, and `fault`.

The report then walks a disciplined loop. Containment moves it `OPEN` → `CONTAINED`. Disposition — again a `QualityEngineer` action, from `CONTAINED` — supplies the `disposition` (`USE_AS_IS`, `REWORK`, `SCRAP`, or `RETURN_TO_SUPPLIER`) and the `fault` (`INTERNAL` or `SUPPLIER`), and when `disposition` is `SCRAP` against a lot, that lot must still be `IN_PRODUCTION` or `COMPLETED`. Disposition is where supplier accountability lands: when `fault` is `SUPPLIER`, the severity penalty — 5 points for `MINOR`, 15 for `MAJOR`, 30 for `CRITICAL` — is recorded as `penalty_points_applied`, added to the supplier's `applied_penalty_points`, and `quality_score` is recomputed, with the automatic-suspension cascade of §3.4 firing if it has fallen below 50 on a `QUALIFIED` supplier; when `supplier_part_id` is also set, that part moves to `ON_HOLD` and its in-flight lots are held `SUPPLIER_QUALITY`. When `disposition` is `SCRAP` against a lot, the lot itself is scrapped with the full §3.6 cascade — components to the scrapped bucket, labels voided, and its other open reports auto-dispositioned.

Closure is reserved for a `QualityManager` who is not the report's initiator (`ERR_SEGREGATION_OF_DUTIES`). Closing a supplier-fault report finalizes its penalty: `penalty_points_applied` is added to `applied_finalized_penalty_points`, and `quality_score_finalized`, `risk_tier`, and `next_audit_due_at` are recomputed. Closure also releases containment: if the lot's `hold_reason` is `NCR_OPEN` and no other report of the lot remains `OPEN` or `CONTAINED`, the hold clears automatically to `CLEAR` with reason `NONE`.

Reopening — `DISPOSITIONED` back to `OPEN` — is the exact mirror of disposition. A supplier-fault penalty is reversed precisely: `penalty_points_applied` is subtracted from `applied_penalty_points`, `quality_score` is recomputed, `penalty_points_applied` returns to 0, `fault` resets to `UNDETERMINED`, and `disposition` resets to `NONE`. If the referenced lot is still `IN_PRODUCTION`, it is re-held `ON_HOLD` with reason `NCR_OPEN`; a `COMPLETED` lot is instead governed by the release gate `ERR_OPEN_NCRS_EXIST`.

Complaints arrive from the field through `RegulatoryAffairs`. Intake requires a unique `complaint_code`, the `lot_id` of the complained unit — and that lot must be `RELEASED` or `RECALLED` (`ERR_LOT_NOT_RELEASED`) — a `severity` of `COSMETIC`, `MINOR`, `SERIOUS_INJURY`, or `DEATH`, and a `description`. The complaint starts `RECEIVED` with `confirmed` false and `received_at` stamped from the logical clock. Starting investigation records the caller as `investigator_user_id` and moves the complaint to `UNDER_INVESTIGATION`. Completing the investigation supplies `confirmed` and moves it to `INVESTIGATED`: the flag is set from the input, and the DMR's complaint rate and review flag are recomputed. When the complaint is confirmed with severity `SERIOUS_INJURY` or `DEATH`, two cascades fire together: a CAPA is auto-created in `INITIATED` with `source_type` `COMPLAINT`, `source_complaint_id` pointing at this complaint, `dmr_id` taken from the complained lot's DMR, `initiator_user_id` set to the investigator, and `process_change` false; and every lot of the same DMR that is `COMPLETED` with hold `CLEAR` is placed `ON_HOLD` with `hold_reason` `FIELD_ACTION` — an investigation hold pending the field-action decision. Reopening an `INVESTIGATED` complaint returns it to `UNDER_INVESTIGATION`, resets `confirmed` to false, and recomputes the rate with this complaint dropped from the numerator. Closing a complaint requires every CAPA spawned from it to be `CLOSED` (`ERR_CAPA_NOT_CLOSED`). Complaints can be listed filtered by `lot_id`, `status`, and `confirmed`.

The complaint rate is the DMR's public health signal, and its evaluation order is pinned because the feedback loop matters — a recall shrinks the denominator, which can re-cross the threshold. On each of the four triggers — a complaint investigation completing with confirmation, a complaint reopening, a lot release, and a lot recall — the system first applies all entity mutations of the triggering action; then sums the denominator as the total `releasable_qty` across the DMR's lots in `RELEASED`; then counts the numerator as the confirmed complaints in `INVESTIGATED` or `CLOSED` whose lot belongs to the DMR; then computes the rate as zero when the denominator is zero, otherwise the numerator divided by the denominator, multiplied by one hundred thousand, and rounded half-up to four decimal places; and finally stores `complaint_rate_per_100k` and sets `field_action_review_required` true exactly when the rate is at least 5.0.

CAPAs are the corrective engine. A `QualityEngineer` creates one with a unique `capa_code`, the `dmr_id` it acts on, and a `source_type` of `COMPLAINT`, `NCR`, `AUDIT`, or `MANUAL`. Source linkage must match the type: `COMPLAINT` requires `source_complaint_id`, `NCR` requires `source_ncr_id`, and `AUDIT` and `MANUAL` take neither; for a complaint source, the complaint's lot must belong to the CAPA's DMR — any violation is `ERR_SOURCE_MISMATCH`. The `process_change` flag defaults to false; the CAPA starts `INITIATED` with the caller as `initiator_user_id` and `effectiveness_cycles` at 0. The workflow runs: beginning investigation moves to `INVESTIGATING`; planning actions records the `action_summary` and moves to `ACTION_PLANNED`; implementing moves to `IMPLEMENTING` — and when `process_change` is true, every validation protocol of the CAPA's DMR currently `VALIDATED` transitions to `REVALIDATION_REQUIRED` with `revalidation_reason` `CAPA_PROCESS_CHANGE`, each holding its in-flight lots `REVALIDATION`; completing implementation moves to `EFFECTIVENESS_CHECK`. Verification belongs to a `QualityManager` who is not the CAPA's initiator, and the outcome is given by the `effective` flag: `effective` true closes the CAPA (`closer_user_id` recorded), but only when a linked source NCR is itself `CLOSED` (`ERR_SOURCE_NOT_CLOSED`); `effective` false moves it to `INEFFECTIVE`, from which restarting investigation returns it to `INVESTIGATING` and increments `effectiveness_cycles` by one. CAPAs can be listed filtered by `dmr_id`, `status`, `source_complaint_id`, and `source_ncr_id`.

Field actions are the regulatory endpoint of the whole loop. A `RegulatoryAffairs` operator drafts one with a unique `action_code`, the `dmr_id` in scope, an `action_type` of `CORRECTION` or `REMOVAL`, a manufacturing scope from `scope_mfg_start` to `scope_mfg_end` (the start strictly before the end), and a `reason_complaint_id`. The reason complaint must be confirmed, of severity `SERIOUS_INJURY` or `DEATH`, and tied to a lot of the same DMR (`ERR_COMPLAINT_NOT_ACTIONABLE`). The draft sits in `DRAFT` until issued. Issuing stamps `issued_at`, recalls every `RELEASED` lot of the DMR whose `manufactured_at` falls within the closed scope interval — on or after `scope_mfg_start` and on or before `scope_mfg_end` — with each recalled lot's label-void and rate-recompute cascade per §3.6, and records how many lots transitioned as `recalled_lot_count`. Closing an `ISSUED` field action requires the reason complaint to be `CLOSED` (`ERR_SOURCE_NOT_CLOSED`). Field actions can be listed filtered by `dmr_id`, `status`, and `reason_complaint_id`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource return `200 OK`; the removal of a lot component returns `204 No Content` with an empty body. All payloads, request fields, and side effects are specified in §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/device-master-records` | Create the first revision of a Device Master Record | QualityEngineer |
| GET | `/api/device-master-records` | List DMRs with optional filters | All roles |
| GET | `/api/device-master-records/{id}` | Get one DMR | All roles |
| POST | `/api/device-master-records/{id}/approve` | Approve a DRAFT revision; supersedes the family's prior APPROVED revision | QualityManager |
| POST | `/api/device-master-records/{id}/obsolete` | Obsolete an APPROVED or SUPERSEDED revision | QualityManager |
| POST | `/api/device-master-records/{id}/revisions` | Create a successor revision (OCC-guarded) | QualityEngineer |
| POST | `/api/manufacturing-lines` | Register a manufacturing line | QMSAdmin |
| GET | `/api/manufacturing-lines` | List manufacturing lines | All roles |
| GET | `/api/manufacturing-lines/{id}` | Get one manufacturing line | All roles |
| POST | `/api/suppliers` | Register a supplier | SupplierQualityEngineer |
| GET | `/api/suppliers` | List suppliers with optional status filter | All roles |
| GET | `/api/suppliers/{id}` | Get one supplier | All roles |
| POST | `/api/suppliers/{id}/qualify` | Qualify a supplier | SupplierQualityEngineer |
| POST | `/api/suppliers/{id}/suspend` | Suspend a QUALIFIED supplier | SupplierQualityEngineer |
| POST | `/api/suppliers/{id}/reinstate` | Reinstate a SUSPENDED supplier | SupplierQualityEngineer |
| POST | `/api/suppliers/{id}/disqualify` | Disqualify a supplier (terminal) | SupplierQualityEngineer |
| POST | `/api/suppliers/{supplierId}/quality-agreements` | Create a quality agreement (OCC-guarded) | SupplierQualityEngineer |
| GET | `/api/quality-agreements` | List quality agreements | All roles |
| GET | `/api/quality-agreements/{id}` | Get one quality agreement | All roles |
| POST | `/api/quality-agreements/{id}/activate` | Activate a DRAFT agreement | SupplierQualityEngineer |
| POST | `/api/quality-agreements/{id}/terminate` | Terminate an ACTIVE agreement | SupplierQualityEngineer |
| POST | `/api/suppliers/{supplierId}/parts` | Register a supplier part | SupplierQualityEngineer |
| GET | `/api/supplier-parts` | List supplier parts | All roles |
| GET | `/api/supplier-parts/{id}` | Get one supplier part | All roles |
| POST | `/api/supplier-parts/{id}/receive` | Receive additional part quantity | SupplierQualityEngineer |
| POST | `/api/supplier-parts/{id}/reinstate` | Release a part hold | SupplierQualityEngineer |
| POST | `/api/suppliers/{supplierId}/change-notifications` | Submit a supplier change notification | SupplierQualityEngineer |
| GET | `/api/change-notifications` | List change notifications | All roles |
| GET | `/api/change-notifications/{id}` | Get one change notification | All roles |
| POST | `/api/change-notifications/{id}/start-review` | Move an SCN to UNDER_REVIEW | SupplierQualityEngineer |
| POST | `/api/change-notifications/{id}/accept` | Accept an SCN (MAJOR cascades) | SupplierQualityEngineer |
| POST | `/api/change-notifications/{id}/reject` | Reject an SCN | SupplierQualityEngineer |
| POST | `/api/suppliers/{supplierId}/audits` | Schedule a supplier audit | SupplierQualityEngineer |
| GET | `/api/supplier-audits` | List supplier audits | All roles |
| GET | `/api/supplier-audits/{id}` | Get one audit | All roles |
| POST | `/api/supplier-audits/{id}/complete` | Complete an audit with findings | SupplierQualityEngineer |
| POST | `/api/supplier-audits/{id}/cancel` | Cancel a scheduled audit | SupplierQualityEngineer |
| POST | `/api/validation-protocols` | Create a validation protocol | QualityEngineer |
| GET | `/api/validation-protocols` | List validation protocols | All roles |
| GET | `/api/validation-protocols/{id}` | Get one validation protocol | All roles |
| POST | `/api/validation-protocols/{id}/execute-phase` | Begin (or restart) phase execution | QualityEngineer |
| POST | `/api/validation-protocols/{id}/submit-phase-review` | Submit the current execution phase for review | QualityEngineer |
| POST | `/api/validation-protocols/{id}/approve-phase` | Approve the current review phase | QualityManager |
| POST | `/api/validation-protocols/{id}/reject-phase` | Reject the current review phase back to execution | QualityManager |
| POST | `/api/sterile-barrier-studies` | Start a sterile-barrier shelf-life study | QualityEngineer |
| GET | `/api/sterile-barrier-studies` | List studies | All roles |
| GET | `/api/sterile-barrier-studies/{id}` | Get one study | All roles |
| POST | `/api/sterile-barrier-studies/{id}/complete` | Complete a study (pass/fail) | QualityManager |
| POST | `/api/device-lots` | Create a device lot | ProductionOperator |
| GET | `/api/device-lots` | List device lots | All roles |
| GET | `/api/device-lots/{id}` | Get one device lot | All roles |
| POST | `/api/device-lots/{id}/complete` | Complete production; computes the sterility sample | ProductionOperator |
| POST | `/api/device-lots/{id}/place-hold` | Place a manual hold on an in-flight lot | QualityEngineer |
| POST | `/api/device-lots/{id}/release-hold` | Clear a hold after its resolution condition is met | QualityEngineer |
| POST | `/api/device-lots/{id}/release` | Release a lot for distribution | QualityManager |
| POST | `/api/device-lots/{id}/scrap` | Scrap an in-flight lot | QualityEngineer |
| POST | `/api/device-lots/{id}/record-sterility-result` | Record the sterility result of a COMPLETED lot | QualityEngineer |
| POST | `/api/device-lots/{lotId}/components` | Record a component into an IN_PRODUCTION lot | ProductionOperator |
| GET | `/api/lot-components` | List lot components (genealogy traceability) | All roles |
| GET | `/api/lot-components/{id}` | Get one lot component | All roles |
| DELETE | `/api/lot-components/{id}` | Remove a component while its lot is IN_PRODUCTION | ProductionOperator |
| POST | `/api/device-lots/{lotId}/udi-labels` | Create a label DRAFT for a lot | ProductionOperator |
| GET | `/api/udi-labels` | List UDI labels | All roles |
| GET | `/api/udi-labels/{id}` | Get one UDI label | All roles |
| POST | `/api/udi-labels/{id}/approve` | Approve a label DRAFT | QualityManager |
| POST | `/api/udi-labels/{id}/print` | Print an APPROVED label | ProductionOperator |
| POST | `/api/udi-labels/{id}/void` | Manually void a label | QualityManager |
| POST | `/api/nonconformance-reports` | Open an NCR against a lot and/or supplier part | QualityEngineer |
| GET | `/api/nonconformance-reports` | List NCRs | All roles |
| GET | `/api/nonconformance-reports/{id}` | Get one NCR | All roles |
| POST | `/api/nonconformance-reports/{id}/contain` | Contain an OPEN NCR | QualityEngineer |
| POST | `/api/nonconformance-reports/{id}/disposition` | Disposition a CONTAINED NCR | QualityEngineer |
| POST | `/api/nonconformance-reports/{id}/close` | Close a DISPOSITIONED NCR | QualityManager |
| POST | `/api/nonconformance-reports/{id}/reopen` | Reopen a DISPOSITIONED NCR | QualityEngineer |
| POST | `/api/complaints` | Intake a complaint against a RELEASED or RECALLED lot | RegulatoryAffairs |
| GET | `/api/complaints` | List complaints | All roles |
| GET | `/api/complaints/{id}` | Get one complaint | All roles |
| POST | `/api/complaints/{id}/start-investigation` | Start complaint investigation | RegulatoryAffairs |
| POST | `/api/complaints/{id}/complete-investigation` | Complete complaint investigation | RegulatoryAffairs |
| POST | `/api/complaints/{id}/reopen` | Reopen an INVESTIGATED complaint | RegulatoryAffairs |
| POST | `/api/complaints/{id}/close` | Close an INVESTIGATED complaint | RegulatoryAffairs |
| POST | `/api/capas` | Create a CAPA | QualityEngineer |
| GET | `/api/capas` | List CAPAs | All roles |
| GET | `/api/capas/{id}` | Get one CAPA | All roles |
| POST | `/api/capas/{id}/begin-investigation` | Move a CAPA to INVESTIGATING | QualityEngineer |
| POST | `/api/capas/{id}/plan-actions` | Record the action plan | QualityEngineer |
| POST | `/api/capas/{id}/implement` | Begin implementation (process-change cascade) | QualityEngineer |
| POST | `/api/capas/{id}/complete-implementation` | Move to effectiveness check | QualityEngineer |
| POST | `/api/capas/{id}/verify-effectiveness` | Verify effectiveness (close or mark ineffective) | QualityManager |
| POST | `/api/capas/{id}/restart-investigation` | Restart investigation after an ineffective outcome | QualityEngineer |
| POST | `/api/field-actions` | Draft a field action scoped by manufacturing window | RegulatoryAffairs |
| GET | `/api/field-actions` | List field actions | All roles |
| GET | `/api/field-actions/{id}` | Get one field action | All roles |
| POST | `/api/field-actions/{id}/issue` | Issue the field action (recalls in-scope RELEASED lots) | RegulatoryAffairs |
| POST | `/api/field-actions/{id}/close` | Close an ISSUED field action | RegulatoryAffairs |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock (fires expiry and revalidation sweeps) | QMSAdmin |

## 5. Error Code Catalogue

The catalogue below fixes the identifier-to-status mapping. The trigger condition of each error is specified in §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UDI_CHECK_DIGIT_MISMATCH` | 400 Bad Request |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_LOT_ON_HOLD` | 409 Conflict |
| `ERR_HOLD_CONDITION_UNRESOLVED` | 409 Conflict |
| `ERR_STERILITY_ALREADY_RESULTED` | 409 Conflict |
| `ERR_LOT_NOT_COMPLETED` | 409 Conflict |
| `ERR_STERILITY_NOT_PASSED` | 409 Conflict |
| `ERR_PROTOCOL_NOT_VALIDATED` | 409 Conflict |
| `ERR_OPEN_NCRS_EXIST` | 409 Conflict |
| `ERR_NO_PRINTED_LABEL` | 409 Conflict |
| `ERR_DMR_NOT_APPROVED` | 409 Conflict |
| `ERR_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_IN_EFFECT` | 409 Conflict |
| `ERR_CHANGE_NOTICE_WINDOW_BREACHED` | 409 Conflict |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_NOTICE_WINDOW_BREACHED` | 409 Conflict |
| `ERR_LINE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_DMR_REVISION` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_COMPONENT_LOT` | 409 Conflict |
| `ERR_STUDY_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_ACTIVE_LABEL_EXISTS` | 409 Conflict |
| `ERR_INSUFFICIENT_PART_QUANTITY` | 409 Conflict |
| `ERR_PART_NOT_QUALIFIED` | 409 Conflict |
| `ERR_SUPPLIER_DISQUALIFIED` | 409 Conflict |
| `ERR_SUPPLIER_NOT_CLEAR` | 409 Conflict |
| `ERR_SCN_PENDING` | 409 Conflict |
| `ERR_NO_ACTIVE_QUALITY_AGREEMENT` | 409 Conflict |
| `ERR_SCORE_BELOW_REINSTATE_THRESHOLD` | 409 Conflict |
| `ERR_NO_COMPONENTS_RECORDED` | 409 Conflict |
| `ERR_LOTS_IN_FLIGHT` | 409 Conflict |
| `ERR_PROTOCOLS_IN_FLIGHT` | 409 Conflict |
| `ERR_CAPA_NOT_CLOSED` | 409 Conflict |
| `ERR_SOURCE_NOT_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PART_NOT_OF_SUPPLIER` | 422 Unprocessable Entity |
| `ERR_PROTOCOL_DMR_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LABEL_REVISION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SOURCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMPLAINT_NOT_ACTIONABLE` | 422 Unprocessable Entity |
| `ERR_DMR_NOT_STERILE` | 422 Unprocessable Entity |

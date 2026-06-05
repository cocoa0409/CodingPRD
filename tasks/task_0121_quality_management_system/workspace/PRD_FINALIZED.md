# Quality Management System API — Product Requirements Document

## 1. Introduction

Manufacturing quality organizations operating to an ISO 9001 footing live and die by the rigor of their corrective-action loop. When a defect surfaces — whether a supplier ships out-of-spec parts, an internal line catches a problem, or an auditor cites a clause violation — the organization must record the nonconformance, decide what to do with the affected material, drive a disciplined root-cause investigation to a verified close, and hold suppliers accountable through formal corrective-action demands. This API is the system of record for that entire chain. It governs nonconformance reports (NCRs), the 8D-structured corrective and preventive action (CAPA) workflow, supplier corrective action requests (SCARs), AQL-based receiving inspection, ISO 9001 audits and their findings, engineering deviations and waivers, and the revision history of control plans.

The system's defining concern is **integrity under segregation of duties**. The quality engineer who authors a CAPA may never be the manager who verifies or closes it; the manager who dispositions an NCR may never be the engineer who raised it. Material decisions carry money — every open nonconformance reserves budget against a quality reserve, and the disposition chosen (rework, scrap, use-as-is under waiver, or return-to-supplier) changes both the cost recorded and the downstream obligations created. Supplier quality is a live, recomputed score that reacts to inspection outcomes, attributed nonconformances, and outstanding corrective-action demands, and that score in turn gates whether a supplier remains approved, on probation, or disqualified.

This document is the complete functional contract for the service. It specifies the entities and their fields, the state machines that govern every lifecycle, the calculations that produce derived figures, the validation rules and their precedence, the full endpoint surface, the role-based access model, and the catalogue of error identifiers the service emits.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two HTTP headers: `X-User-ID` and `X-User-Role`. The `X-User-ID` header carries the identifier of the acting principal, and `X-User-Role` declares the role under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role must be permitted to invoke the requested operation; a recognized role attempting an operation outside its authority is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are five roles. Four of them — `QualityEngineer`, `QualityManager`, `Inspector`, and `Auditor` — are backed by the `Personnel` entity: when `X-User-Role` is any of these, `X-User-ID` is the `id` of the acting `Personnel` record, and ownership and segregation-of-duties checks compare that `id` against the relevant person-stamp foreign keys on the target resource (for example, an NCR's `created_by_personnel_id`, a CAPA's `authored_by_personnel_id`, or an audit's `lead_auditor_id`). The fifth role, `SupplierUser`, is backed by the `Supplier` entity: when `X-User-Role` is `SupplierUser`, `X-User-ID` is the `id` of the acting `Supplier`, and ownership checks on any SCAR compare the SCAR's `supplier_id` to `X-User-ID`. A `SupplierUser` may read and act only on resources tied to its own supplier.

A small number of bootstrap and operator calls — registering `Personnel`, creating a `Supplier`, and setting the test-driving clock — require only that the headers be present and the role be recognized and permitted; for these, `X-User-ID` need not resolve to any persisted entity. For every other operation that names an owner or author, `X-User-ID` must resolve to the appropriate principal, and two further checks may apply: a resource-ownership check that rejects with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) when an entity-backed actor acts on a resource it does not own, and a segregation-of-duties check that rejects with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the acting person is the author or creator of a resource and is therefore barred from performing an independent-reviewer step on it.

It is important to distinguish the role names above from the `role` attribute stored on a `Personnel` record. A person's `role` field is one of `QUALITY_ENGINEER`, `QUALITY_MANAGER`, `INSPECTOR`, or `AUDITOR`, and that stored value is the underlying identity that the request-time role names map onto.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; a requested limit above the maximum is treated as the maximum. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are ordered by `created_at` in ascending order. The pagination fields `limit`, `offset`, `total_count`, and `has_more` are reported in the `meta` object of a list response, where `total_count` is the total number of records matching the query before pagination and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp formatted as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) that is refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by one on every mutation that changes the resource. There is one exception: the 8D step record carries only `id` and `created_at` — it has neither an `updated_at` nor a `version`, because a step is an append-only journal entry that is never mutated after it is recorded. All other entities — personnel, suppliers, nonconformance reports, CAPAs, SCARs, inspection plans, inspection lots, audits, audit findings, deviations, control plans, and control-plan revisions — carry the full set of common properties.

Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented. This applies equally to side-effect mutations: when one operation cascades a change onto a second resource, the second resource's `updated_at` and `version` advance as well. For instance, opening a supplier-sourced nonconformance recomputes the supplier's quality rating, and that recomputation is itself a mutation of the supplier, so the supplier's `version` advances.

### 2.5. Precision, Rounding, and Monetary Units

Monetary amounts are stored as integer counts of cents; no fractional cents ever appear. Wherever a calculation produces a non-integer intermediate that must become cents, it is rounded half-up (round-half-away-from-zero) to a whole cent. The supplier quality rating and the CAPA effectiveness scores are decimal figures rounded half-up to exactly two decimal places. Where the cost-of-quality calculation accumulates a per-unit figure across many units, the rounding is applied to each per-unit line first and the rounded lines are then summed — the system never sums raw figures and rounds once at the end. Counts such as sample sizes, acceptance numbers, and rejection numbers are pure integers with no rounding.

### 2.6. Nested Resource Retrieval and Reverse Lookups

Several read endpoints are nested under a parent resource — for example, the SCARs of a supplier, the inspection lots of an inspection plan, the CAPAs of a nonconformance report, the steps of a CAPA, the findings of an audit, the revisions of a control plan, or the deviations of a nonconformance report. For any such nested path, the server validates each path segment left to right: the parent resource named earlier in the path must exist before the nested collection is considered, and a missing resource at any position yields `ERR_NOT_FOUND` (HTTP 404). These nested listings exist so that a foreign key pointing from child to parent can be traversed in reverse; the child's link to its parent is never declared as a navigable field on the parent, only resolved through the listing.

### 2.7. Optimistic Concurrency on Control Plans

Creating a control-plan revision is guarded by optimistic concurrency control on the parent control plan. A request to create a revision must carry an `expected_control_plan_version` field holding the `version` of the target control plan that the client last observed. The server compares that value to the control plan's current `version`; if they do not match — because some other writer has advanced the control plan since the client read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This makes the rule deterministic and observable from two strictly sequential requests: because a freshly created draft revision could otherwise legitimately supersede a prior draft for the same plan, a second create still carrying the originally read version would slip through against a plan that has already moved on, and the version check closes that gap. No other endpoint in the system takes a version field, and no other create or transition is gated by this check.

### 2.8. Cascading Side Effects and Derived-Field Reconciliation

Many operations in this system mutate more than one entity. A supplier's computed counters — `lots_inspected`, `lots_rejected`, `ncrs_attributed`, and `open_scar_count` — are never written directly by a client; they are reconciled as side effects of inspection dispositions, nonconformance lifecycle events, and SCAR lifecycle events, and every change to any of them triggers a recomputation of the supplier's `quality_rating` and `approval_status`. Likewise an audit's `open_finding_count`, a control plan's `current_revision_no`, a CAPA's `rework_loops`, and an inspection plan's `consecutive_rejects` and `severity_mode` are all derived counters reconciled by the operations described in Section 3. Each subsection of Section 3 names the specific cascades its operations perform; the governing principle here is that derived fields are authoritative outputs of the workflow, never client inputs, and that any cascade that touches a second resource advances that resource's `updated_at` and `version`.

### 2.9. Segregation of Duties and Resource Ownership

Two cross-cutting safeguards protect the integrity of the corrective-action chain. Resource ownership requires that an entity-backed actor act only on resources it owns: a `SupplierUser` acting on a SCAR must have an `X-User-ID` equal to that SCAR's `supplier_id`, and an `Auditor` driving an audit's lifecycle must have an `X-User-ID` equal to that audit's `lead_auditor_id`; a violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Segregation of duties requires that the person performing an independent-reviewer step not be the person who authored or created the resource: the manager dispositioning a nonconformance must not be the engineer recorded in its `created_by_personnel_id`, and the manager verifying, rejecting verification of, or closing a CAPA (whether effective or ineffective) must not be the engineer recorded in its `authored_by_personnel_id`; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Validation Precedence

When more than one check could fail on a single request, the checks are applied in a fixed precedence so that the reported error is deterministic. Authentication comes first: missing or unrecognised headers yield `ERR_UNAUTHENTICATED`. Next the role's authority for the endpoint is checked, yielding `ERR_FORBIDDEN_ROLE` if the role is not permitted. Then every resource named in the URL path is checked for existence, left to right, yielding `ERR_NOT_FOUND` for the first that is missing. Then every foreign key carried in the request body is checked, yielding `ERR_FK_NOT_FOUND` if any does not resolve to an existing resource of the correct type. Then the body itself is checked for well-formedness — required fields present, enum values in range, and constrained integers non-negative — yielding `ERR_INVALID_REQUEST`. Only after these pass is the target's state checked against the requested transition, yielding `ERR_INVALID_STATE` if the transition is not defined from the current state. Resource-ownership checks (`ERR_NOT_RESOURCE_OWNER`) and then segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`) follow, and only after all of these do the remaining business rules specific to each operation apply. On a disposition, for example, this means the state check is evaluated before the segregation-of-duties check, which is evaluated before the deviation-required check for `USE_AS_IS`, which is evaluated before the source check for `RETURN_TO_SUPPLIER`.

## 3. Business Logic & Workflows

### 3.1. Actors, Suppliers, and the Foundational Catalogue

Before any quality work can be recorded, the participants and the parts they govern must exist. A `QualityManager` registers each `Personnel` actor by supplying a `full_name`, an `email` (which serves as the login identifier and must be unique across all personnel), and a `role` drawn from `QUALITY_ENGINEER`, `QUALITY_MANAGER`, `INSPECTOR`, or `AUDITOR`. A new person begins with `status` of `ACTIVE`; the only other value the `status` field can hold is `DEACTIVATED`.

A `QualityManager` also registers each `Supplier` by supplying a legal `name` and a short `code` that is unique across suppliers. A freshly created supplier starts in a pristine quality posture: its `quality_rating` is 100.00, its `approval_status` is `APPROVED`, and all of its computed counters — `open_scar_count`, `lots_inspected`, `lots_rejected`, and `ncrs_attributed` — are zero. The rating and the counters are never set by a client; they are maintained by the system as described in the inspection, nonconformance, and SCAR workflows below.

Two further catalogue entities anchor the inspection regime. A `QualityManager` creates a `ControlPlan` by supplying a `name` and the `part_number` it governs; a new control plan is `ACTIVE` (the only other status it may hold is `RETIRED`) and its `current_revision_no` is 0 until the first revision is approved. Against a control plan, a `QualityManager` creates one or more `InspectionPlan` records, each supplying a `name`, the `control_plan_id` it implements, the `part_number` it inspects, a nominal `lot_size`, an `aql_pct` chosen from the permitted set 0.65, 1.0, 1.5, 2.5, 4.0, or 6.5, and an optional `inspection_level` that defaults to `GII` and may also be `GI` or `GIII`. A new inspection plan begins in `NORMAL` `severity_mode` (the alternative is `TIGHTENED`), with `consecutive_rejects` at 0 and `needs_review` false.

### 3.2. Raising and Opening a Nonconformance

The corrective-action chain begins when a `QualityEngineer` raises a nonconformance. Raising one creates a `NonconformanceReport` in `DRAFT` status with its `created_by_personnel_id` stamped to the acting engineer's `X-User-ID` and its `budget_reserved_cents` at 0. The payload supplies a `title`, a `source` of `SUPPLIER`, `INTERNAL`, or `AUDIT`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, a `defect_qty` that must be at least 1, a `unit_cost_cents` that must be zero or greater, and a `part_number`. Depending on origin, the report also carries a `supplier_id`, an `audit_finding_id`, and an optional `inspection_lot_id` linking the lot that surfaced the defect; an optional `rework_hours` figure (the estimated labour hours to rework a single unit, defaulting to 0) feeds the later cost calculation. When `source` is `SUPPLIER`, a `supplier_id` is required and the others must be omitted; when `source` is `AUDIT`, an `audit_finding_id` is required; for `INTERNAL` reports neither attribution is required. Any foreign key supplied in the body must resolve to an existing resource of the right type, or the request fails with `ERR_FK_NOT_FOUND` (HTTP 404). The report's `status`, `disposition`, `deviation_id`, `cost_of_quality_cents`, and `budget_reserved_cents` are all system-maintained and never accepted as input.

Opening the report advances it from `DRAFT` to `OPEN`, and is permitted only while it is in `DRAFT`. At open time the system reserves budget against the quality reserve: the reserved figure, held in `budget_reserved_cents`, is the `defect_qty` multiplied by the `unit_cost_cents`, and that reservation stands as long as the report remains non-terminal. If the report's `source` is `SUPPLIER`, opening it increments the referenced supplier's `ncrs_attributed` and recomputes that supplier's quality rating. If the `source` is `AUDIT`, the precondition is that the referenced audit finding resolves and is currently `OPEN`; opening the report drives that finding from `OPEN` to `NCR_RAISED` and records the new report's `id` in the finding's `raised_ncr_id`. A supplier-sourced report can be opened only if its supplier resolves and is `ACTIVE`.

A report may be voided to either of its terminal states. From `DRAFT`, a `QualityEngineer` may void it, moving it `DRAFT → VOID` and releasing its reserved budget back to zero. From `OPEN`, a `QualityManager` may void it, moving it `OPEN → VOID`, but only if no CAPA has yet been opened against it; an attempt to void an open report that already has a CAPA is rejected with `ERR_NCR_HAS_CAPA` (HTTP 409). Voiding an open report releases its reserved budget to zero and, in addition, reverses the attribution side effects that opening created: a `SUPPLIER`-sourced report decrements the supplier's `ncrs_attributed` and recomputes the supplier's rating, and an `AUDIT`-sourced report reverts its finding from `NCR_RAISED` back to `OPEN` and clears that finding's `raised_ncr_id`. Any transition attempted from a status that does not define it is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Dispositioning Material and the Cost of Quality

Once a report is `OPEN`, a `QualityManager` decides what becomes of the affected material by dispositioning it, which advances the report from `OPEN` to `DISPOSITIONED`. The decision is recorded in the `disposition` field, which until this point is null and thereafter holds exactly one of `REWORK`, `SCRAP`, `USE_AS_IS`, or `RETURN_TO_SUPPLIER`. Disposition is the most heavily guarded operation in the report's life, and its checks are evaluated in a fixed order. First the report must actually be in `OPEN` status, or the attempt fails with `ERR_INVALID_STATE`. The acting manager must not be the same person recorded in the report's `created_by_personnel_id`; a self-disposition is rejected with `ERR_SEGREGATION_OF_DUTIES`. A choice of `USE_AS_IS` is permitted only when an `APPROVED` deviation exists for this report whose `max_qty` is at least the report's `defect_qty` and whose validity window contains the current server clock — that is, the clock is at or after the deviation's `valid_from` and strictly before its `valid_to`; absent such a deviation the request is rejected with `ERR_DEVIATION_REQUIRED` (HTTP 409). A choice of `RETURN_TO_SUPPLIER` is permitted only when the report's `source` is `SUPPLIER`; otherwise it is rejected with `ERR_DISPOSITION_NOT_ALLOWED` (HTTP 409). When `USE_AS_IS` succeeds, the report's `deviation_id` is set to the `id` of the approving deviation.

Dispositioning also fixes the cost of quality. The system computes `cost_of_quality_cents` and then re-reserves budget so that `budget_reserved_cents` equals the freshly computed cost of quality. The computation proceeds per unit and is summed across the `defect_qty` identical units. First, a per-unit labour figure is computed as the `rework_hours` multiplied by a labour rate of 6,000 cents per hour (that is, 60 dollars per hour), rounded half-up to whole cents. Then a per-unit base component is selected by disposition: for `REWORK`, the base component is that rounded labour figure alone, since the unit is salvaged and no material value is lost; for `SCRAP`, the base component is the full `unit_cost_cents`, since the entire unit value is lost and no rework labour is incurred; for `USE_AS_IS`, the base component is the `unit_cost_cents` multiplied by a concession factor of 0.30 and rounded half-up to whole cents, representing the negotiated write-down; for `RETURN_TO_SUPPLIER`, the base component is the `unit_cost_cents` multiplied by a handling factor of 0.10 and rounded half-up to whole cents, representing handling and freight only. Each per-unit base component is then multiplied by a severity multiplier — 1.5 when `severity` is `CRITICAL`, 1.0 when `MAJOR`, and 0.5 when `MINOR` — and that product is rounded half-up to whole cents to form the per-unit line. Finally the per-unit line is summed across all `defect_qty` units; because the units are identical, the total equals the `defect_qty` times the per-unit rounded line. Rounding is applied per line and only then summed, never the reverse.

### 3.4. The 8D Corrective-Action Workflow

A corrective and preventive action is the disciplined investigation that follows a disposition. A `QualityEngineer` opens a `Capa` against a dispositioned report by supplying the `ncr_id` of the report and a `title`; the report must be in `DISPOSITIONED` status. A new CAPA starts in `OPEN` status with its `current_step` at `D1` and its `authored_by_personnel_id` stamped to the opening engineer. The first CAPA opened against a report has a side effect on the report itself: the system advances that report from `DISPOSITIONED` to `CAPA_IN_PROGRESS`. The CAPA's `status` ranges over `OPEN`, `ROOT_CAUSE`, `VERIFICATION`, `EFFECTIVENESS_CHECK`, and the two terminal states `CLOSED_EFFECTIVE` and `CLOSED_INEFFECTIVE`, while `current_step` tracks the highest 8D discipline reached, from `D1` through `D8`.

The investigation is documented through 8D step records. A `QualityEngineer` or a `QualityManager` records an `EightDStep` against a CAPA, supplying a `discipline` from `D1` through `D8`, a `narrative`, an optional `containment_count` (the number of distinct containment or corrective actions captured in that step, defaulting to 0 and never negative), and an optional `recurred_defects` (used on the D8 effectiveness record to report the count of recurrences observed during the monitoring window, defaulting to 0 and never negative). Each step is stamped with a `recorded_by_personnel_id` and carries a `capa_id` linking it to its CAPA. Step records are journal entries and are never edited once written.

The CAPA's progress is driven by a single transition operation whose behaviour depends on the supplied `action`. A `QualityEngineer` advances the CAPA. Advancing from `OPEN` to `ROOT_CAUSE` requires that at least one step with a `discipline` of `D1`, `D2`, or `D3` already exists for the CAPA; this advance sets `current_step` to `D4`. Advancing from `ROOT_CAUSE` to `VERIFICATION` requires that at least one step with a `discipline` of `D4` or `D5` and a `containment_count` of at least 1 exists; this advance sets `current_step` to `D6` and computes the projected effectiveness. The **projected (provisional) effectiveness**, recorded in `provisional_effectiveness` and clamped to the range 0.00 through 1.00, is the total of the `containment_count` values across all `D4` and `D5` steps divided by the parent report's `defect_qty` (treating the divisor as 1 if `defect_qty` were ever zero), capped at 1.00 and rounded half-up to two decimal places.

The remaining transitions belong to the `QualityManager`, and each of them is barred to the engineer who authored the CAPA. From `VERIFICATION`, a manager may reject the verification, looping the CAPA back from `VERIFICATION` to `ROOT_CAUSE`: this increments `rework_loops` by one, resets `current_step` to `D4`, and clears `provisional_effectiveness` back to null. Alternatively, from `VERIFICATION` a manager may verify the CAPA, advancing it from `VERIFICATION` to `EFFECTIVENESS_CHECK`; verification requires that `provisional_effectiveness` be at least 0.50, failing which the request is rejected with `ERR_EFFECTIVENESS_TOO_LOW` (HTTP 409), and on success it sets `current_step` to `D7` and stamps `verified_by_personnel_id` with the acting manager. Both the reject-verification and verify actions require that the acting manager not be the CAPA's author, enforced with `ERR_SEGREGATION_OF_DUTIES`.

Closure happens from `EFFECTIVENESS_CHECK`, and again the acting manager must not be the CAPA's author. Both closure actions require that at least one step with `discipline` of `D8` exists, set `current_step` to `D8`, and compute the **measured (final) effectiveness**, recorded in `final_effectiveness` and clamped to 0.00 through 1.00. The final effectiveness is one minus the `recurred_defects` on the D8 step divided by the parent report's `defect_qty` (again treating the divisor as 1 if it were zero), rounded half-up to two decimal places. Closing the CAPA as effective requires that this final effectiveness be at least 0.80, failing which the close is rejected with `ERR_EFFECTIVENESS_TOO_LOW`; on success the CAPA moves from `EFFECTIVENESS_CHECK` to `CLOSED_EFFECTIVE` and cascades a closure onto its parent report, driving that report from `CAPA_IN_PROGRESS` to `CLOSED`. Closing the CAPA as ineffective carries no effectiveness threshold and no NCR cascade: the CAPA moves from `EFFECTIVENESS_CHECK` to `CLOSED_INEFFECTIVE`, the final effectiveness is still computed and recorded, but the parent report remains in `CAPA_IN_PROGRESS`. Any of these transition actions attempted from a status that does not define them is rejected with `ERR_INVALID_STATE`.

When the parent report is driven to `CLOSED`, its reserved budget is released to zero, and a further cascade may follow: if the report's `source` is `SUPPLIER` and a SCAR exists for the report in `ACCEPTED_RESPONSE` status, that SCAR is itself resolved as described next.

### 3.5. Supplier Corrective Action Requests

When a supplier is on the hook for a nonconformance, a `QualityManager` opens a `Scar` against the supplier-attributed report, supplying the `ncr_id`, the `supplier_id` of the supplier required to respond, and a `due_at` response-due timestamp. A new SCAR begins in `OPEN` status; opening it increments the supplier's `open_scar_count` and recomputes the supplier's quality rating. The SCAR's `status` ranges over `OPEN`, `ACK`, `RESPONDED`, `ACCEPTED_RESPONSE`, `REJECTED_RESPONSE`, the terminal `RESOLVED` and `CANCELLED`, and it tracks a `rejection_count` of how many times its response has been rejected, plus the supplier's `response_narrative` once supplied.

The SCAR lifecycle is driven by a transition operation parameterised by `action`. A `SupplierUser` — and only the supplier that owns the SCAR, meaning the acting `X-User-ID` equals the SCAR's `supplier_id`, otherwise `ERR_NOT_RESOURCE_OWNER` — acknowledges and responds. Acknowledging moves the SCAR from `OPEN` to `ACK`. Responding from `ACK` moves it to `RESPONDED` and requires a non-empty `response_narrative`. The reviewing `QualityManager` then either accepts the response, moving it from `RESPONDED` to `ACCEPTED_RESPONSE`, or rejects it, moving it from `RESPONDED` to `REJECTED_RESPONSE` and incrementing `rejection_count` by one. A rejected SCAR loops back: the owning `SupplierUser` may respond again, moving it from `REJECTED_RESPONSE` to `RESPONDED`, once more requiring a non-empty `response_narrative`. A `QualityManager` may cancel a SCAR while it is still `OPEN`, moving it from `OPEN` to `CANCELLED`, which decrements the supplier's `open_scar_count` and recomputes the supplier's rating.

A SCAR reaches `RESOLVED` not by a direct call but as the cascade described earlier: when the parent report referenced by the SCAR's `ncr_id` reaches `CLOSED` while the SCAR is in `ACCEPTED_RESPONSE`, the SCAR transitions from `ACCEPTED_RESPONSE` to `RESOLVED`, decrements the supplier's `open_scar_count`, and recomputes the supplier's rating. Note that for the purpose of the supplier's `open_scar_count`, a SCAR counts as open while its status is any of `OPEN`, `ACK`, `RESPONDED`, or `REJECTED_RESPONSE`. Any SCAR action attempted from a status that does not define it is rejected with `ERR_INVALID_STATE`.

### 3.6. Receiving Inspection and AQL Sampling

Receiving inspection determines whether an incoming lot is accepted or rejected on the strength of a sample. An `Inspector` creates an `InspectionLot` by supplying the `inspection_plan_id` of the governing plan, the `supplier_id` of the supplier that shipped the lot, and the `actual_lot_size` of units actually received (at least 1). A new lot is `PENDING`; its `sample_size`, `acceptance_number`, `rejection_number`, `severity_mode_used`, and `defects_found` are not client inputs at creation. Its `status` ranges over `PENDING`, `IN_INSPECTION`, and the terminal `ACCEPTED` and `REJECTED`, and it carries an `inspected_by_personnel_id` stamp.

Starting inspection moves the lot from `PENDING` to `IN_INSPECTION` and freezes the sampling numbers from the plan, requiring that the linked inspection plan exist. The sampling resolution proceeds in two stages. First a sample-size **code letter** is fixed from the plan's `inspection_level` and the plan's nominal `lot_size` — note that the code letter is driven by the plan's `lot_size`, not by the lot's `actual_lot_size`. For general level `GII`, the lot-size bands map as follows: 2 through 8 gives code letter A; 9 through 15 gives B; 16 through 25 gives C; 26 through 50 gives D; 51 through 90 gives E; 91 through 150 gives F; 151 through 280 gives G; and 281 through 500 gives H. Level `GI` is one code letter less strict than `GII` — shift the band's result one letter earlier in the alphabet, clamped so it never falls below A. Level `GIII` is one code letter more strict than `GII` — shift the result one letter later, clamped so it never rises above H.

The second stage reads the acceptance figures from a fixed single-sampling lookup table indexed by the code letter and an AQL column. The table holds, for each code letter D through H and each AQL column of 1.0, 2.5, or 4.0, a sample size and an acceptance number: at code letter D the sample size is 8 in every column with acceptance numbers of 0 at AQL 1.0, 0 at 2.5, and 1 at 4.0; at code letter E the sample size is 13 with acceptance numbers 0, 1, and 1; at code letter F the sample size is 20 with acceptance numbers 0, 1, and 2; at code letter G the sample size is 32 with acceptance numbers 1, 2, and 3; and at code letter H the sample size is 50 with acceptance numbers 1, 3, and 5. The chosen AQL column depends on the plan's `severity_mode` at the moment inspection starts. In `NORMAL` mode the column is the plan's own `aql_pct` used as-is. In `TIGHTENED` mode the column is stepped one position tighter than the plan's `aql_pct`, where the ordered columns from tightest to loosest are 1.0, then 2.5, then 4.0: stepping tighter takes 4.0 to 2.5 and 2.5 to 1.0, while 1.0 stays at 1.0 because there is no tighter column. The resolved `sample_size` is the table's sample size for that cell, the resolved `acceptance_number` is the table's acceptance number, and the `rejection_number` is the acceptance number plus one. Tightening keeps the same code letter — and therefore the same sample size — but the tighter column yields an acceptance number that is the same or smaller, so a lot that would have been accepted in normal mode can flip to rejected in tightened mode. Starting inspection also snapshots the plan's mode into the lot's `severity_mode_used`.

Dispositioning the lot moves it from `IN_INSPECTION` to a terminal state and requires the inspector to supply `defects_found` (the number of defective units found in the sample, never negative). If `defects_found` is at most the `acceptance_number` — equality at the acceptance number still accepts — the lot is `ACCEPTED`: this increments the supplier's `lots_inspected`, resets the inspection plan's `consecutive_rejects` to 0, and recomputes the supplier's quality rating. If `defects_found` is at least the `rejection_number` — equality at the acceptance number plus one rejects — the lot is `REJECTED`: this increments both the supplier's `lots_inspected` and `lots_rejected`, increments the plan's `consecutive_rejects`, and recomputes the supplier's rating; and if the running `consecutive_rejects` reaches 2, the plan's `severity_mode` switches from `NORMAL` to `TIGHTENED`. A disposition attempted on a lot that is not `IN_INSPECTION`, or a start attempted on a lot that is not `PENDING`, is rejected with `ERR_INVALID_STATE`.

### 3.7. The Supplier Quality Rating

A supplier's `quality_rating` is a live score between 0.00 and 100.00, recomputed whenever an inspection lot is dispositioned, a SCAR is resolved or cancelled, or a supplier-sourced nonconformance is opened or voided. The score blends three weighted factors. The **lot factor** rewards a clean acceptance history: if `lots_inspected` is zero it is 1.0, otherwise it is one minus the ratio of `lots_rejected` to `lots_inspected`, with the result floored at 0.0. The **nonconformance factor** penalises attributed defects: it is one minus the `ncrs_attributed` multiplied by a per-NCR penalty of 0.10, floored at 0.0. An **open-SCAR penalty** caps outstanding accountability: it is the `open_scar_count` multiplied by a per-SCAR step of 0.05, but never more than a ceiling of 0.20. The base score weights the lot factor at 0.6 and the nonconformance factor at 0.4 (the two weights sum to 1.0), then the open-SCAR penalty is subtracted, with the result floored at 0.0. That figure is multiplied by 100 and rounded half-up to two decimal places to produce the stored `quality_rating`.

The same recomputation sets the supplier's `approval_status` from the resulting rating: a rating of at least 70.00 yields `APPROVED`; a rating below 70.00 but at least 50.00 yields `PROBATION`; and a rating below 50.00 yields `DISQUALIFIED`. Both thresholds are inclusive at their lower bound.

### 3.8. ISO 9001 Audits and Findings

An `Auditor` creates an `Audit` by supplying a `title`, the `lead_auditor_id` of the auditor who will lead it (which must resolve to a person whose role is `AUDITOR`), a `scheduled_from` and `scheduled_to` defining the inclusive audit window, and an optional `clause_scope` listing the ISO 9001 clauses in scope. A new audit is `PLANNED`; its `status` ranges over `PLANNED`, `IN_PROGRESS`, and the terminal `CLOSED`, and it carries a computed `open_finding_count`. Throughout the audit's lifecycle, the lead-auditor actions may be performed only by the auditor whose `X-User-ID` equals the audit's `lead_auditor_id`, otherwise `ERR_NOT_RESOURCE_OWNER`.

Starting an audit moves it from `PLANNED` to `IN_PROGRESS`, but a lead auditor may not be double-booked. Starting is rejected with `ERR_AUDITOR_DOUBLE_BOOKED` (HTTP 409) if the audit's window, expanded by a 24-hour buffer on both sides, collides with the window of any other non-closed audit (one that is `PLANNED` or `IN_PROGRESS`) belonging to the same `lead_auditor_id`. Concretely, a collision exists when this audit's `scheduled_from` is at or before the other audit's `scheduled_to` plus 24 hours, and the other audit's `scheduled_from` is at or before this audit's `scheduled_to` plus 24 hours. Because the buffer is inclusive, windows that merely touch within the 24-hour margin do conflict.

During an audit, the lead `Auditor` records findings. Recording an `AuditFinding` against the audit supplies a `clause` (the ISO 9001 clause cited), a `grade` of `MAJOR`, `MINOR`, or `OBSERVATION`, and a `description`. A new finding is `OPEN`, carries an `audit_id` linking it to its parent, and increments the parent audit's `open_finding_count`. The finding's `status` ranges over `OPEN`, `NCR_RAISED`, and the terminal `CLOSED` and `VOID`, and it carries a `raised_ncr_id` back-pointer set when a nonconformance is escalated from it. A finding counts toward `open_finding_count` while its status is anything other than `CLOSED` or `VOID` — so a finding in `NCR_RAISED` still counts as open.

Findings reach their terminal states through their own transition operation. A finding in `NCR_RAISED` can be closed only once the nonconformance escalated from it (the one referenced by its `raised_ncr_id`) has reached `CLOSED`; closing it before then is rejected with `ERR_FINDING_NCR_OPEN` (HTTP 409). A finding still in `OPEN` may be closed directly only when its `grade` is `OBSERVATION` — observations alone may close without an escalated nonconformance — and an attempt to close a non-observation finding directly from `OPEN` is rejected with `ERR_FINDING_REQUIRES_NCR` (HTTP 409). A finding in `OPEN` may also be voided. Each of closing from `NCR_RAISED`, closing an observation from `OPEN`, and voiding from `OPEN` decrements the parent audit's `open_finding_count`. Closing the audit itself moves it from `IN_PROGRESS` to `CLOSED` and requires that its `open_finding_count` be exactly zero — every finding `CLOSED` or `VOID` — failing which the close is rejected with `ERR_AUDIT_HAS_OPEN_FINDINGS` (HTTP 409).

### 3.9. Deviations and Waivers

A deviation authorises shipping or using nonconforming material under a bounded waiver, and it is the precondition for a `USE_AS_IS` disposition. A `QualityEngineer` requests a `Deviation` against a nonconformance by supplying the `ncr_id` it covers, the `supplier_id` and `part_number` being waived (denormalised for overlap scoping), a `valid_from` and `valid_to` defining the waiver window, and a `max_qty` of nonconforming units the waiver authorises (at least 1). The waiver window is half-open: `valid_from` is inclusive and `valid_to` is exclusive. A new deviation is `REQUESTED`; its `status` ranges over `REQUESTED`, `APPROVED`, and the terminal `REJECTED`, `EXPIRED`, and `REVOKED`, and an `approved_by_personnel_id` stamp is set when it is approved.

A `QualityManager` decides a deviation through its transition operation. Approving it moves it from `REQUESTED` to `APPROVED` and stamps `approved_by_personnel_id` with the acting manager, but only if the new waiver does not overlap an existing `APPROVED` deviation for the same `supplier_id` and `part_number`. Two half-open windows overlap when the first's `valid_from` is strictly before the second's `valid_to` and the second's `valid_from` is strictly before the first's `valid_to`; an overlap is rejected with `ERR_DEVIATION_OVERLAP` (HTTP 409). Abutting windows, where one's `valid_to` exactly equals the other's `valid_from`, do not overlap and are allowed. Rejecting a deviation moves it from `REQUESTED` to `REJECTED`. Revoking an approved deviation moves it from `APPROVED` to `REVOKED`, but is blocked if the deviation is still in live use — that is, if any nonconformance has its `deviation_id` pointing at this deviation, was dispositioned `USE_AS_IS`, and is not yet `CLOSED` or `VOID` — in which case the revoke is rejected with `ERR_DEVIATION_IN_USE` (HTTP 409). A transition attempted from a status that does not define it is rejected with `ERR_INVALID_STATE`.

A deviation can also expire on its own. When the server clock is advanced (see below), the system sweeps every `APPROVED` deviation whose `valid_to` is at or before the new clock value and transitions each from `APPROVED` to `EXPIRED`.

### 3.10. Control-Plan Revisions and the Test-Driving Clock

Control plans evolve through revisions, often as the documented outcome of a corrective action. A `QualityEngineer` drafts a `ControlPlanRevision` by supplying the `control_plan_id` being revised, a `revision_no`, a `change_summary`, the required `expected_control_plan_version`, and an optional `source_capa_id` linking the CAPA whose corrective action prompted the revision (validated to exist when provided). A new revision is `DRAFT`; its `status` ranges over `DRAFT`, `APPROVED`, and the terminal `SUPERSEDED`, and it carries an `approved_by_personnel_id` stamp. At create time the `revision_no` must equal the parent control plan's `current_revision_no` plus one, or the create is rejected with `ERR_REVISION_SEQUENCE` (HTTP 409). The create is additionally guarded by the optimistic-concurrency check described in Section 2.7: the supplied `expected_control_plan_version` must match the control plan's current `version`, or the create is rejected with `ERR_STALE_VERSION`; a successful create advances the control plan's `version`.

A `QualityManager` approves a revision, moving it from `DRAFT` to `APPROVED`. Approval again requires that the `revision_no` equal the parent control plan's `current_revision_no` plus one (`ERR_REVISION_SEQUENCE`). On approval the system sets the parent control plan's `current_revision_no` to the approved `revision_no`, cascades a `needs_review` of true onto every inspection plan whose `control_plan_id` points at that control plan, and supersedes any prior `APPROVED` revision of the same plan by moving it from `APPROVED` to `SUPERSEDED`. A revision transition attempted from a status that does not define it is rejected with `ERR_INVALID_STATE`.

Finally, an administrative test-driving capability lets a `QualityManager` set the server's logical clock to a supplied instant via a `to_iso8601` value. Setting the clock both establishes the current time used by every window and validity check in the system and triggers the deviation-expiry sweep described above.

## 4. Endpoint Definitions

The table below summarises the API surface. Creating a new resource returns HTTP 201 with the created resource in `data`; reads and state-changing operations on existing resources return HTTP 200 with the affected resource (the clock endpoint returns 200 with an empty `data`). Request payloads, response details, and side effects are described in the Section 3 narratives and are not repeated here; refer back to those workflows to reconstruct each call's full contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/personnel` | Register a Personnel actor | QualityManager |
| GET | `/personnel/{id}` | Get a Personnel | QualityManager, QualityEngineer, Inspector, Auditor |
| POST | `/suppliers` | Create a Supplier | QualityManager |
| GET | `/suppliers/{id}` | Get a Supplier including rating and counters | QualityManager, QualityEngineer, Inspector, SupplierUser |
| GET | `/suppliers/{id}/scars` | List SCARs for a supplier | QualityManager, SupplierUser |
| GET | `/suppliers/{id}/inspection-lots` | List inspection lots for a supplier | QualityManager, Inspector |
| GET | `/suppliers/{id}/deviations` | List deviations for a supplier | QualityManager, QualityEngineer |
| POST | `/nonconformance-reports` | Create an NCR in DRAFT | QualityEngineer |
| GET | `/nonconformance-reports/{id}` | Get an NCR | QualityManager, QualityEngineer |
| GET | `/nonconformance-reports` | List NCRs (filterable) | QualityManager, QualityEngineer |
| POST | `/nonconformance-reports/{id}/open` | Open an NCR (DRAFT to OPEN) | QualityEngineer |
| POST | `/nonconformance-reports/{id}/disposition` | Disposition an OPEN NCR | QualityManager |
| POST | `/nonconformance-reports/{id}/void` | Void an NCR | QualityEngineer, QualityManager |
| POST | `/capas` | Open a CAPA against a dispositioned NCR | QualityEngineer |
| GET | `/capas/{id}` | Get a CAPA | QualityManager, QualityEngineer |
| GET | `/nonconformance-reports/{id}/capas` | List CAPAs for an NCR | QualityManager, QualityEngineer |
| GET | `/nonconformance-reports/{id}/scars` | List SCARs for an NCR | QualityManager, QualityEngineer |
| POST | `/capas/{id}/steps` | Record an 8D step | QualityEngineer, QualityManager |
| GET | `/capas/{id}/steps` | List 8D steps for a CAPA | QualityManager, QualityEngineer |
| POST | `/capas/{id}/transition` | Drive the CAPA state machine | QualityEngineer, QualityManager |
| POST | `/scars` | Open a SCAR | QualityManager |
| GET | `/scars/{id}` | Get a SCAR | QualityManager, SupplierUser |
| POST | `/scars/{id}/transition` | Drive the SCAR state machine | SupplierUser, QualityManager |
| POST | `/control-plans` | Create a ControlPlan | QualityManager |
| GET | `/control-plans/{id}` | Get a ControlPlan | QualityManager, QualityEngineer, Inspector |
| POST | `/control-plan-revisions` | Create a DRAFT revision (OCC) | QualityEngineer |
| GET | `/control-plans/{id}/revisions` | List revisions for a control plan | QualityManager, QualityEngineer |
| POST | `/control-plan-revisions/{id}/approve` | Approve a revision | QualityManager |
| POST | `/inspection-plans` | Create an InspectionPlan | QualityManager |
| GET | `/inspection-plans/{id}` | Get an InspectionPlan | QualityManager, Inspector |
| GET | `/control-plans/{id}/inspection-plans` | List inspection plans for a control plan | QualityManager, Inspector |
| POST | `/inspection-lots` | Create an InspectionLot | Inspector |
| GET | `/inspection-lots/{id}` | Get an InspectionLot | QualityManager, Inspector |
| GET | `/inspection-plans/{id}/inspection-lots` | List lots for an inspection plan | QualityManager, Inspector |
| POST | `/inspection-lots/{id}/transition` | Drive the InspectionLot state machine | Inspector |
| POST | `/audits` | Create an Audit | Auditor |
| GET | `/audits/{id}` | Get an Audit | QualityManager, Auditor |
| POST | `/audits/{id}/transition` | Drive the Audit state machine | Auditor |
| POST | `/audits/{id}/findings` | Record an AuditFinding | Auditor |
| GET | `/audit-findings/{id}` | Get an AuditFinding | QualityManager, Auditor, QualityEngineer |
| GET | `/audits/{id}/findings` | List findings for an audit | QualityManager, Auditor |
| POST | `/audit-findings/{id}/transition` | Drive the AuditFinding state machine | Auditor |
| POST | `/deviations` | Request a Deviation/waiver | QualityEngineer |
| GET | `/deviations/{id}` | Get a Deviation | QualityManager, QualityEngineer |
| GET | `/nonconformance-reports/{id}/deviations` | List deviations for an NCR | QualityManager, QualityEngineer |
| POST | `/deviations/{id}/transition` | Drive the Deviation state machine | QualityManager |
| POST | `/_clock/set_current_utc` | Set the server clock; sweep expired deviations | QualityManager |

## 5. Error Code Catalogue

The trigger condition for each error is described in the relevant Section 2 or Section 3 narrative; this catalogue lists only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DEVIATION_REQUIRED` | 409 |
| `ERR_DISPOSITION_NOT_ALLOWED` | 409 |
| `ERR_DEVIATION_OVERLAP` | 409 |
| `ERR_DEVIATION_IN_USE` | 409 |
| `ERR_AUDITOR_DOUBLE_BOOKED` | 409 |
| `ERR_AUDIT_HAS_OPEN_FINDINGS` | 409 |
| `ERR_FINDING_NCR_OPEN` | 409 |
| `ERR_FINDING_REQUIRES_NCR` | 409 |
| `ERR_REVISION_SEQUENCE` | 409 |
| `ERR_EFFECTIVENESS_TOO_LOW` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NCR_HAS_CAPA` | 409 |

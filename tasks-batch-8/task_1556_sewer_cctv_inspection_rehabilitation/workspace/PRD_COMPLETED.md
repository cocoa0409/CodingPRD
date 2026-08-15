# Sewer CCTV Inspection & Rehabilitation API — Product Requirements Document

## 1. Introduction

Municipal sewer districts and the NASSCO-certified contractors who serve them run a long, tightly regulated pipeline of work: pipe segments are inventoried manhole-to-manhole, CCTV crawlers video their interiors, PACP-certified coders grade every defect, district engineers select a rehabilitation method — cured-in-place lining, spot repair, or full replacement — crews pump bypass flow around the work zone while customers are notified, liners are cured in place, service laterals are reinstated, and the district then has to prove to regulators that inflow and infiltration actually fell afterwards. This document specifies the Sewer CCTV Inspection & Rehabilitation API, the system of record for that pipeline, covering segment inventory, inspection scheduling and certification, rehabilitation planning and unit-priced costing, bypass pumping and customer notification, post-construction acceptance, warranty adjudication, and pre/post flow monitoring.

The API is mounted under the `/sewer` prefix. It serves two audiences at once: the district engineering office, which owns budgets, plans, approvals, warranty claims, and flow analysis, and the certified field and office technicians — coders, QA reviewers, and crew leads — whose credentials and assignments gate every safety-relevant transition. Wherever money, public notice, or worker safety is involved, the specification favors explicit gates over convenience: a coded inspection cannot be certified by its own coder, a full-replacement crew cannot mobilize without an approved bypass plan, a lining job cannot complete until every active service lateral has been reinstated and a post-lining inspection certified, and no rehabilitation plan may commit funds beyond the district's annual budget.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly five roles, spelled as follows: `DistrictEngineer`, `Coder`, `QaReviewer`, `CrewLead`, and `CustomerServiceRep`. A request missing either header, or presenting a role outside this catalog, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A properly identified caller who attempts an operation their role is not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the per-endpoint role assignments are enumerated in §4.

Identity semantics differ by role, and the difference matters for every ownership check in the system. When `X-User-Role` is `Coder`, `QaReviewer`, or `CrewLead`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a technician — an inspection's `coder_id`, a work order's `crew_lead_id` — compare the resource's foreign-key field directly against `X-User-ID`. The referenced technician must additionally list the matching capability in their `capabilities` list (a subset of `CODER`, `QA_REVIEWER`, `CREW_LEAD`) and must be `active`; inactive technicians cannot be assigned to any new responsibility. An acting caller in an entity-backed role whose `X-User-ID` is not a registered technician, whose technician lacks the capability the requested operation requires, or whose technician is inactive is rejected with `ERR_UNAUTHORIZED` (HTTP 403). When `X-User-Role` is `DistrictEngineer` or `CustomerServiceRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it for audit purposes but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned in one page: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips the given number of items before the page begins and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless stated otherwise, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order; ties on `created_at` are broken by `id` in ascending order.

Paginated list responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All temporal rules in this document — certification expiry, cycle scheduling windows, bypass windows, notice lead times, warranty expiry, monitoring durations — are evaluated against a server-maintained logical clock, never against wall-clock time. At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time under any circumstance.

A test-driving capability, restricted to the `DistrictEngineer` role, advances the logical clock to a supplied instant: the request body carries `to_iso8601`, and the response returns the new `current_utc`. The supplied instant may be any valid ISO 8601 instant, earlier or later than the current reading; no monotonicity is enforced. Setting the clock also runs the customer-notice expiry sweep across every district: any notice still in `QUEUED` status whose `event_start` has been reached by the new clock transitions to `EXPIRED`. Independently of explicit clock-setting, the same expiry sweep is evaluated on every state-changing request within a district, so a queued notice can never survive past the start of the event it announces.

### 2.5. Common Resource Properties and Entity Identity

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID, with no type prefix of any kind.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): the same timestamp format, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation — including mutations caused by system cascades and automatic transitions rather than by a direct client write.

One deliberate exception exists. Defect observations are append-only records that are never updated in place, so a `DefectObservation` carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Pipeline Hierarchy, Cascades, and Nested Retrieval

A sewer district is the root of nearly everything the API tracks. Inspection cycles, pipe segments, and flow-monitoring periods each record their owning `district_id`. Segments in turn own service laterals, CCTV inspections, rehabilitation plans, and warranty cases, each carrying its `segment_id`. A rehabilitation plan owns its work orders through their `plan_id`, and each work order owns its line items, bypass plans, and customer notices through their `work_order_id`. Inspections own their defect observations through `inspection_id`. Warranty cases are deliberately cross-aggregate: a single case ties together the segment under claim, the completed work order whose warranty covers it, and the re-inspection created to investigate it.

Nested resource paths are validated strictly left to right. When an endpoint path contains several identifiers, the server confirms that each identifier exists and belongs to its declared parent scope before examining anything deeper, and the first identifier that fails this check produces `ERR_NOT_FOUND` (HTTP 404). A request naming a lateral beneath the wrong segment fails on that segment-to-lateral pairing before any lateral-specific rule is ever evaluated.

State changes propagate along this hierarchy in both directions, and the propagation is always immediate: every side effect of a request is visible in that request's response. Completion bubbles upward — a finishing work order can complete its parent plan and flip the segment's rehabilitation status in the same call — while stand-downs and cancellations cascade downward to dependent bypass plans. Every resource touched by such a cascade is independently mutated: its `updated_at` refreshes and its `version` increments by one, even though the client never addressed that resource directly.

### 2.7. Monetary Precision: Integer Cents and Per-Line Rounding

All monetary values in the API — district budgets, catalog unit prices, line totals, plan totals — are integers denominated in cents. No fractional cents ever appear anywhere in the system.

Derived totals obey a pinned rounding order: each line item's value is rounded first, half-up to a whole cent, and only then are the rounded line values summed. Summing the unrounded products and rounding once at the end is expressly forbidden, because the two orders produce different invoices on real jobs.

Two costing variants coexist throughout the plan and work-order lifecycle. The provisional variant, used at proposal and approval time for budget commitment, prices every line at its scheduled quantity. The final variant, used at work-order completion and billing, prices every line at its field-measured installed quantity and falls back, line by line, to the provisional value whenever a line's installed quantity was never reported. Both variants add the work order's mobilization fee on top of the summed line values, and both exclude the line items of cancelled work orders from the plan-level totals.

### 2.8. Scoring and Measurement Precision

Three families of derived measurements carry their own precision contracts. The weighted structural index computed from certified inspections is stored to exactly two decimal places, rounded half-up. Inflow/infiltration reduction percentages are reported to exactly one decimal place, rounded half-up. The PACP Quick Rating, by contrast, is a four-character ordinal code with no fractional content at all. The formulas behind these numbers live with the workflows that produce them — certification in §3.3, basin analysis in §3.9 — while the rounding contract itself lives here and admits no exceptions.

### 2.9. Optimistic Concurrency Control

Exactly two write operations in the API are guarded by optimistic concurrency control, and on both the guard is mandatory.

Approving a rehabilitation plan requires the request body to carry `expected_plan_version`, holding the `version` of the plan the client last observed. If the plan's current `version` has advanced past that value — because another engineer reopened or otherwise modified the plan in the meantime, legitimately changing its provisional total and the district's budget arithmetic — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated. Adding a line item to a work order likewise requires `expected_work_order_version`, the last observed `version` of the parent work order; a mismatch against the work order's current `version` is rejected with the same `ERR_STALE_VERSION` (HTTP 412), because provisional totals and the mobilization tier derive from line items and a stale writer would otherwise commit budget against out-of-date quantities. No other endpoint accepts an expected-version field.

### 2.10. The Validation Cascade

When several rules could reject the same request, checks execute in a fixed priority order so that the failure a client sees is deterministic rather than accidental:

1. **Authentication** — the headers are present and the role is known, otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted on this endpoint, otherwise `ERR_UNAUTHORIZED`.
3. **Existence** — every path identifier exists and nests inside its declared parent, validated left to right, otherwise `ERR_NOT_FOUND`.
4. **State eligibility** — the target resource sits in a from-state that lists the requested transition, otherwise `ERR_INVALID_STATE`.
5. **Personnel certification and segregation** — NASSCO certification validity and segregation-of-duties on coding and QA actions: `ERR_CERT_EXPIRED`, `ERR_SOD_VIOLATION`, `ERR_NOT_ASSIGNED_CODER`. The cycle-open gate on inspection start (`ERR_CYCLE_NOT_OPEN`) is evaluated immediately after the certification-validity check.
6. **Flow-control prerequisites** — an approved bypass before full-replacement mobilization, an active bypass before physical work begins, and adequate pump capacity at bypass approval: `ERR_BYPASS_REQUIRED`, `ERR_BYPASS_NOT_ACTIVE`, `ERR_PUMP_UNDERSIZED`.
7. **Business constraints** — method-to-grade compatibility, plan uniqueness per segment, cycle-window membership, defect distance bounds, and PACP code shape: `ERR_METHOD_INCOMPATIBLE`, `ERR_PLAN_CONFLICT`, `ERR_OUTSIDE_CYCLE_WINDOW`, `ERR_DEFECT_OUT_OF_RANGE`, `ERR_INVALID_REQUEST`.
8. **Temporal rules** — notice lead times, buffered bypass-window overlap, flow-monitoring window rules, warranty expiry, and bypass activation windows: `ERR_NOTICE_LEAD_VIOLATION`, `ERR_BYPASS_WINDOW_CONFLICT`, `ERR_FLOW_WINDOW_CONFLICT`, `ERR_MONITORING_TOO_SHORT`, `ERR_WARRANTY_EXPIRED`, `ERR_OUTSIDE_WINDOW`.
9. **Referential integrity** — certified basis inspections, a QA reviewer who differs from the coder, crew-lead capability, lining-notice addresses that match real laterals, and the presence of a pre-rehabilitation flow baseline: `ERR_BASIS_NOT_CERTIFIED`, `ERR_NOT_ASSIGNED_CREW`, `ERR_ADDRESS_NOT_ON_SEGMENT`, `ERR_NO_BASELINE`.
10. **Fiscal ceiling** — the district budget-commitment check on plan approval, always evaluated last: `ERR_BUDGET_EXCEEDED`.

The practical consequence: on a plan approval that would fail both an earlier business check and the budget ceiling, the client always sees the earlier error first; the fiscal check fires only when everything upstream of it has passed.

## 3. Business Logic & Workflows

This section walks the rehabilitation pipeline in the order a district experiences it: standing up the district and its people, inventorying segments, inspecting and coding them, planning and funding the rehabilitation, executing the work under flow control and public notice, accepting the finished liner, then living through warranty and proving the inflow/infiltration reduction. State names appear as their exact enumeration strings, and state pairs such as `SCHEDULED` → `IN_PROGRESS` name the transitions that §4 maps to concrete endpoints.

### 3.1. District Onboarding and the Technician Registry

A `DistrictEngineer` begins by registering the sewer district itself. Creation requires a `name`, which must be unique across the API; an `ii_reduction_target_pct`, the basin inflow/infiltration reduction target expressed as a percentage between 0 and 100 — a basin is only considered complete when its measured reduction reaches this figure; and `budget_cents`, the annual rehabilitation budget in integer cents. Two policy knobs are optional: `notice_lead_hours`, the required customer-notice lead time before a bypass activation or excavation, defaults to 48 hours when omitted, and `warranty_months`, the warranty window that runs from each work order's completion, defaults to 12 months. A duplicate `name`, an `ii_reduction_target_pct` outside 0–100, or a supplied `notice_lead_hours` or `warranty_months` that is not a non-negative integer are all rejected with `ERR_INVALID_REQUEST`. The district's `budget_committed_cents` is never written by clients: it starts at 0 and is maintained by the system as the running sum of provisional totals over the district's plans that sit in `APPROVED` or `EXECUTING` status.

People come next. Registering a technician captures a `full_name`, a `nassco_cert_number` that must be unique, a `nassco_cert_expires_at` instant, and a `capabilities` list drawn from `CODER`, `QA_REVIEWER`, and `CREW_LEAD` that gates which of the entity-backed roles the technician may act as. The `capabilities` list must be non-empty, and a duplicate `nassco_cert_number` is rejected with `ERR_INVALID_REQUEST`. The `active` flag defaults to true; an inactive technician cannot be assigned to anything new. Certification validity is a hard gate on every coding and QA action: any attempt to code or QA-review at or after the `nassco_cert_expires_at` instant is rejected with `ERR_CERT_EXPIRED`. A `DistrictEngineer` may later update a technician's certification expiry, capabilities, or active flag, and each such update increments the technician's `version`.

### 3.2. Inspection Cycles and the Pipe Segment Inventory

Work inside a district is organized into inspection cycles. A `DistrictEngineer` creates a cycle with a free-form `label` such as '2026-Basin-A' plus a `window_start` and `window_end`; the end must be later than the start (`ERR_INVALID_REQUEST` otherwise), and the new cycle sits in `DRAFT`. Opening a cycle — the `DRAFT` → `OPEN` transition — requires the `window_start` to be strictly earlier than the `window_end`, and requires that no other cycle of the same district is already `OPEN`; a second concurrent cycle is rejected with `ERR_CYCLE_OVERLAP`. Closing a cycle, `OPEN` → `CLOSED`, is only possible once every inspection scheduled against that cycle has reached a terminal-or-stable state, meaning `CERTIFIED` or `VOIDED`; stragglers block the close with `ERR_INSPECTIONS_OPEN`. Both transitions increment the cycle's `version`, and the cycle list can be filtered by `status`.

The pipe segment is the district's unit of inventory. Creating one records a `segment_ref` — the upstream-to-downstream manhole reference, formatted like 'MH-104->MH-105' (the format is illustrative; any non-empty string is accepted) and unique within the district, with duplicates rejected as `ERR_INVALID_REQUEST` — a `diameter_mm` that must be a positive integer and later drives both the mobilization price tier and the pump-sizing rule, a `material` drawn from `VCP`, `RCP`, `PVC`, `HDPE`, `CI`, and `BRICK`, a `length_m` that must be greater than zero, and an integer `install_year`. Everything about a segment's condition is computed rather than written: `structural_grade` and `om_grade` both begin at 0, `quick_rating` and `structural_index` remain null until the segment's first certified inspection, and `last_rehab_completed_at` stays null until a work order completes. The segment's `rehab_status` begins at `NONE` and, as later sections describe, walks through `PLANNED`, `IN_PROGRESS`, `REHABILITATED`, and `WARRANTY` as plans are approved, crews mobilize, work finishes, and claims arrive. The segment list supports filtering by `rehab_status` and by `min_structural_grade`, the latter returning only segments whose current stored `structural_grade` is at least the supplied value, which must be an integer (`ERR_INVALID_REQUEST` otherwise).

Each segment may carry any number of service laterals. Adding one records an `address` unique within the segment, a `connection_type` of `DIRECT`, `WYE`, or `SADDLE`, and an optional `active` flag that defaults to true; a lateral's `reinstated` flag always starts false. Only active laterals are owed reinstatement after a lining job, which is why the flag matters long before construction starts. The lateral list can be filtered by `active` and by `reinstated`; both filters accept `true`/`false` case-insensitively (with `1`/`0` as synonyms), and any other filter value is `ERR_INVALID_REQUEST`.

### 3.3. CCTV Inspection, Defect Coding, and QA Certification

A `DistrictEngineer` schedules an inspection on a segment by naming the `cycle_id` it belongs to, a `scheduled_at` instant, and the `coder_id` of the technician who will code the footage; the `purpose` is optional and defaults to `BASELINE`, with `PRE_REHAB`, `POST_CIPP`, and `WARRANTY_RE` as the alternatives. The scheduled instant must fall inside the referenced cycle's window — the window endpoints are inclusive, so an instant exactly equal to `window_start` or `window_end` qualifies — or the request fails with `ERR_OUTSIDE_CYCLE_WINDOW`. The named cycle must exist and belong to the segment's district (`ERR_NOT_FOUND` otherwise), and the named coder must be an active technician holding the `CODER` capability (`ERR_INVALID_REQUEST` otherwise). A fresh inspection sits in `SCHEDULED` with `reject_count` at 0 and both `qa_reviewer_id` and `certified_at` null.

Field capture starts when the assigned coder begins work, moving the inspection `SCHEDULED` → `IN_PROGRESS`. Three guards apply to that first step: the acting `Coder`'s technician identity must equal the inspection's `coder_id` (`ERR_NOT_ASSIGNED_CODER`), the coder's certification must still be valid at the current logical time (`ERR_CERT_EXPIRED`), and the inspection's cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`). Moving from the field to the desk — `IN_PROGRESS` → `CODING` — again requires the acting coder to be the assigned one. The same assigned-coder and certification-validity gates also guard the QA submission and every defect append or removal.

Coding is where defects are recorded. While the inspection is `CODING`, a `Coder` appends observations, each carrying a `pacp_code` (an uppercase NASSCO code of one to six characters such as 'CRK', 'B', or 'RTL'; anything else is `ERR_INVALID_REQUEST`), a `family` of `STRUCTURAL` or `OM`, a `grade` from 1 to 5 where 5 demands immediate attention, a `distance_m` measured from the upstream manhole that must lie between zero and the segment's `length_m` inclusive, a `clock_position` from 0 to 12 where 0 means not applicable, and an optional `extent_m` that defaults to 0 for point defects and must not be negative (`ERR_INVALID_REQUEST`). A grade outside 1–5, a distance outside the segment's length, or a clock position outside 0–12 is rejected with `ERR_DEFECT_OUT_OF_RANGE`. Observations may also be removed, but only while the inspection remains `CODING`; appends or removals attempted in any other status fail with `ERR_INVALID_STATE`. Adding or removing observations during `CODING` leaves the segment's stored condition scores untouched — no scoring preview is exposed anywhere — and the segment's grades change only at certification.

When the footage is fully coded, the assigned coder submits the inspection for quality assurance, `CODING` → `QA_REVIEW`; an inspection with zero observations cannot be submitted and draws `ERR_NO_DEFECTS_CODED`.

Certification is the system's central checkpoint. A `QaReviewer` certifies `QA_REVIEW` → `CERTIFIED`, and segregation of duties is absolute: the reviewing technician must differ from the inspection's `coder_id` (`ERR_SOD_VIOLATION`), must hold the `QA_REVIEWER` capability, and must hold a certification valid at the current logical time (`ERR_CERT_EXPIRED`). On certification the inspection records the acting technician as `qa_reviewer_id` and stamps `certified_at`, and the parent segment's condition scores are recomputed from this inspection's observations alone, across both families:

- `structural_grade` becomes the worst (highest) grade among the inspection's structural observations, or 0 when there are none.
- `om_grade` becomes the worst grade among the O&M observations, or 0 when there are none.
- `structural_index` becomes the extent-weighted mean of the structural observations: each observation contributes its grade multiplied by its weight, where the weight is the larger of the defect's `extent_m` and 1.0, and the sum of those products is divided by the sum of the weights; the result is stored to two decimal places, rounded half-up, and remains null when the inspection carries no structural observations.
- `quick_rating` becomes the four-character PACP Quick Rating: the first character is the highest structural grade observed; the second is the count of observations at that grade, capped at 9; the third is the second-highest grade, or 0 when no second grade exists; the fourth is the count at that second grade, capped at 9, or 0. Grades of {5, 5, 4, 3, 1} therefore encode as `5241`, and an inspection with no structural observations yields `0000`.

The two readings of the same observation set answer different questions. The quick rating is an ordinal triage and regulatory-reporting code that ignores extent entirely — a segment with one grade-5 point defect and a long grade-4 crack reports a severity of the `5141` style. The weighted index, by contrast, lets longitudinal defects count for more: that same observation set produces an index of 4.03. Neither is a rounding of the other.

Certification deliberately does not drive rehabilitation decisions by itself. When a certified inspection reveals a structural grade of 5 on a segment whose `rehab_status` is `NONE`, the status does not change automatically — the grade is a flag for the engineer, and the decision to rehabilitate remains manual. One acceptance rule does fire at certification: when the certified inspection's `purpose` is `POST_CIPP`, a completed work order exists for the segment, and every active lateral on the segment shows `reinstated` as true, the segment's `rehab_status` advances to `WARRANTY`. In every other case certification leaves `rehab_status` untouched.

Rejection is the other half of the QA loop. A `QaReviewer` other than the coder (again `ERR_SOD_VIOLATION`) may reject the inspection with an optional `reason`; rejection applies the same capability and certification-validity gates as certification. The first and second rejections route the inspection `QA_REVIEW` → `CODING` and increment `reject_count`. When an inspection already carrying a `reject_count` of 2 is rejected again, the reject call itself still succeeds — but instead of returning to `CODING`, the inspection is voided by an automatic system transition: its status becomes `VOIDED` and its `reject_count` is set to 3. That auto-void ripples outward: any warranty case currently in `RE_INSPECTION` whose `re_inspection_id` names this inspection falls back to `OPENED`. A `DistrictEngineer` may also void an inspection outright, but only from `SCHEDULED` or `CODING`.

Two list views serve the coding office. The per-segment list filters by `status` and `purpose`; a cross-segment list supports reverse lookup by `cycle_id`, `coder_id`, `qa_reviewer_id`, and `status`, which is how supervisors answer "which inspections has this technician coded or reviewed?" The per-inspection defect list can additionally be filtered by `family`.

### 3.4. Rehabilitation Planning: Method Selection and Budget Commitment

Once a segment's certified condition is known, a `DistrictEngineer` drafts a rehabilitation plan against it. Plan creation takes two inputs: the `method`, one of `CIPP_LINING`, `SPOT_REPAIR`, or `FULL_REPLACE`, and the `basis_inspection_id`, the certified inspection on which the method decision rests. The referenced inspection must exist and belong to the segment (`ERR_NOT_FOUND` otherwise); its `CERTIFIED` status is enforced only at proposal time, not at creation. A new plan is `DRAFT`, with `provisional_total_cents` at 0 and `final_total_cents` null until completion.

Proposing the plan — `DRAFT` → `PROPOSED` — is where method discipline is enforced. The basis inspection must be `CERTIFIED` (`ERR_BASIS_NOT_CERTIFIED`), and the chosen method must be compatible with the segment's certified grades (`ERR_METHOD_INCOMPATIBLE`):

- `SPOT_REPAIR` is allowed only when the segment's `structural_grade` is at most 3 and the basis inspection contains exactly one or two structural observations graded 3 or worse — spot repair is a surgical technique, not a systemic one.
- `CIPP_LINING` requires a `structural_grade` of at least 2 and a segment `material` other than `BRICK`; liners cannot be cured inside brick.
- `FULL_REPLACE` is always allowed; open-cut excavation has no grading precondition.

At proposal time the plan's `provisional_total_cents` is recomputed from whatever work-order line items exist — and is simply 0 when no work order has been staged yet.

Approval commits money, and it is the most heavily guarded transition in the API. Three independent gates apply, in cascade order. First, uniqueness: the segment must have no other plan sitting in `PROPOSED`, `APPROVED`, or `EXECUTING` (`ERR_PLAN_CONFLICT`). Second, concurrency: the request must carry `expected_plan_version` equal to the plan's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.9; a missing or non-integer `expected_plan_version` is `ERR_INVALID_REQUEST`. Third, always last, the fiscal ceiling: the plan's `provisional_total_cents` plus the district's `budget_committed_cents` must not exceed the district's `budget_cents`, or the approval fails with `ERR_BUDGET_EXCEEDED`. On success the district's `budget_committed_cents` increases by the plan's `provisional_total_cents` — the ledger sync — and the segment's `rehab_status` advances to `PLANNED`.

An approved plan is not yet irreversible. Reopening it — `APPROVED` → `DRAFT` — is permitted only while no child work order has progressed beyond `ISSUED` (cancelled work orders never block a reopen); once a crew has mobilized, the attempt fails with `ERR_WORK_STARTED`. A successful reopen writes the compensating ledger entry: the district's `budget_committed_cents` decreases by the plan's `provisional_total_cents`, floored at zero, and the segment's `rehab_status` returns to `NONE` provided no other `APPROVED` or `EXECUTING` plan remains for it. Plans still in `DRAFT` or `PROPOSED` may instead be cancelled outright, moving to `CANCELLED`. The per-segment plan list filters by `status`, and a cross-segment plan list supports reverse lookup by `basis_inspection_id` and `status`, answering "which plans were decided on the strength of this inspection?"

### 3.5. Work Order Execution and Unit-Priced Line Items

Issuing a work order is how an approved plan gets a crew. A `DistrictEngineer` creates the work order under an `APPROVED` plan and names the `crew_lead_id`; the plan must sit in `APPROVED` status at that moment — issuing under a plan in any other status, `EXECUTING` included, fails with `ERR_PLAN_NOT_APPROVED` — and the named technician must exist (`ERR_NOT_FOUND` otherwise), be active, and hold the `CREW_LEAD` capability, with an inactive or incapable technician failing as `ERR_NOT_ASSIGNED_CREW`. The work order is born with `execution_status` `ISSUED` and `billing_status` `UNBILLED` — two independent dimensions that proceed in parallel from then on. At the same instant the system derives the work order's `mobilization_tier` from the segment's geometry, evaluating the tiers large-first: `MOB_LARGE` when the segment's `diameter_mm` is at least 600 millimeters or its `length_m` exceeds 300 meters; otherwise `MOB_STANDARD` when the diameter is at least 300 millimeters; otherwise `MOB_SMALL`. The tier keys the mobilization fee that joins every cost rollup: 900,000 cents (that is, $9,000.00) for `MOB_LARGE`, 400,000 cents ($4,000.00) for `MOB_STANDARD`, and 150,000 cents ($1,500.00) for `MOB_SMALL`.

Quantities arrive as unit-priced line items. A `DistrictEngineer` adds a line by naming its `pay_item_code` — a catalog code such as 'CIPP-8IN-LF', 'SPOT-EA', or 'EXC-CY' — a `scheduled_qty` greater than zero, a `unit_price_cents` greater than zero, and the mandatory `expected_work_order_version` guard from §2.9 (a missing or non-integer guard value is `ERR_INVALID_REQUEST`). Line items may be added while the work order sits in any execution status. Each line immediately earns its `provisional_line_cents`: the scheduled quantity multiplied by the unit price, rounded half-up to a whole cent, per line. The parent plan's `provisional_total_cents` recomputes over all lines of all non-cancelled work orders plus each order's mobilization fee, and the work order's own `version` increments with every line added. Every such recompute that moves the provisional total of a plan sitting in `APPROVED` or `EXECUTING` shifts the district's `budget_committed_cents` by the same delta — whether the trigger is a line item added or corrected, a work order created, or a work order cancelled — so the running sum of §3.1 is preserved exactly. Corrections split by role and by phase: while the work order is still `ISSUED`, a `DistrictEngineer` — and only a `DistrictEngineer` (`ERR_UNAUTHORIZED` otherwise) — may correct a line's `scheduled_qty` or `unit_price_cents` to new positive values, and attempting either correction in any other execution status fails with `ERR_INVALID_STATE`; once work is underway, the assigned `CrewLead` (any other crew lead fails with `ERR_NOT_ASSIGNED_CREW`) or a `DistrictEngineer` reports the field-measured `installed_qty`, a number greater than or equal to zero, which is accepted only while execution is `IN_WORK` or `PUNCH_LIST` (`ERR_INVALID_STATE` otherwise). A line-item update carrying neither kind of field is `ERR_INVALID_REQUEST`. A line's `final_line_cents` stays null until an installed quantity is reported for it, at which point it is computed exactly like the provisional value but on the installed quantity.

Mobilization is the point of no return for the plan. The assigned crew lead — and only that technician, else `ERR_NOT_ASSIGNED_CREW` — moves the work order `ISSUED` → `MOBILIZED`. The parent plan must be `APPROVED` or `EXECUTING` (`ERR_PLAN_NOT_APPROVED`). For a `FULL_REPLACE` job, a bypass plan in `APPROVED` or `ACTIVE` status must already exist for the work order (`ERR_BYPASS_REQUIRED`), because open-cut excavation cannot proceed without flow control in place. And every customer notice for this work order whose `event_start` falls at or before the earliest bypass or excavation start must already be `SENT` or `ACKNOWLEDGED` (`ERR_NOTICE_LEAD_VIOLATION`); the earliest bypass or excavation start is taken as the earliest `event_start` among the work order's own notices, so the gate binds exactly the notices due at that earliest instant. A successful mobilization bubbles upward: the parent plan moves `APPROVED` → `EXECUTING` automatically, and the segment's `rehab_status` becomes `IN_PROGRESS`.

Physical work follows a tight loop. Beginning work — `MOBILIZED` → `IN_WORK` — requires that any bypass plan attached to the work order is `ACTIVE` (`ERR_BYPASS_NOT_ACTIVE`). Weather or a utility strike can force a stand-down, `IN_WORK` → `MOBILIZED`, which cascades downward: any `ACTIVE` bypass plan for the work order is demobilized with it. When the crew believes the work is done, submitting the punch list — `IN_WORK` → `PUNCH_LIST` — requires every line item to carry a reported `installed_qty` (`ERR_QTY_MISSING`). If the punch walk reveals more work, resuming returns the order `PUNCH_LIST` → `IN_WORK`. A `DistrictEngineer` may cancel a work order from `ISSUED` or `MOBILIZED`; cancelling a `MOBILIZED` order also sweeps any of its bypass plans still in `PROPOSED`, `APPROVED`, or `ACTIVE` down to `CLOSED`.

Work orders support two list views: the per-plan list, and a cross-plan reverse lookup filtered by `crew_lead_id` and `execution_status` — the view a dispatcher uses to see everything a crew lead currently holds.

### 3.6. Bypass Pumping and Customer Notification

Flow control is planned per work order. The assigned `CrewLead` — any other crew lead fails with `ERR_NOT_ASSIGNED_CREW` — proposes a bypass plan with a `window_start`, a `window_end` that must be later than the start (`ERR_INVALID_REQUEST` otherwise), and a positive integer `pump_capacity_gpm` (`ERR_INVALID_REQUEST` otherwise); the plan enters `PROPOSED`. Bypass windows use half-open interval semantics: the window covers every instant from its start up to but not including its end.

Approval, by a `DistrictEngineer`, applies two engineering checks. Pump adequacy comes from the segment's diameter: the rated `pump_capacity_gpm` must be at least 25 gallons per minute per inch of diameter, where the inch figure is the segment's `diameter_mm` divided by 25.4 and rounded up to the next whole inch; an undersized pump is rejected with `ERR_PUMP_UNDERSIZED`. Scheduling safety then widens each window by a thirty-minute setup buffer on both ends and checks the buffered half-open intervals of all other bypass plans — for work orders of the same segment — currently in `APPROVED` or `ACTIVE`; any intersection is rejected with `ERR_BYPASS_WINDOW_CONFLICT`. A `DistrictEngineer` may instead reject a proposed bypass outright, moving it `PROPOSED` → `REJECTED`.

Activation belongs to the crew. Any technician holding the `CREW_LEAD` capability — not necessarily the assigned crew lead — activates an approved plan — `APPROVED` → `ACTIVE` — only while the logical clock sits inside the window, meaning at or after `window_start` and strictly before `window_end` (`ERR_OUTSIDE_WINDOW`, evaluated before the parent work order's status check), and only while the parent work order is `MOBILIZED` or `IN_WORK` (`ERR_INVALID_STATE`). Demobilization — `ACTIVE` → `DEMOBILIZED` — happens at the hand of any `CREW_LEAD`-capable technician or automatically when the work order stands down, and a `DistrictEngineer` closes the plan out `DEMOBILIZED` → `CLOSED`. The bypass list for a work order can be filtered by `status`.

Public notice runs on its own track. A `CustomerServiceRep` queues a notice against a work order with the affected `address`, a `channel` of `DOOR_HANGER`, `MAIL`, `SMS`, or `EMAIL`, and the `event_start` — the start of the disruptive event being announced, whether that is a bypass activation or an excavation. For lining work the address must match an active lateral's address on the segment; notices addressed elsewhere are rejected with `ERR_ADDRESS_NOT_ON_SEGMENT`. Queued notices sit in `QUEUED` until sent. Sending enforces the district's lead time: the send must occur no later than `event_start` minus the district's `notice_lead_hours` — with the default 48-hour lead, a notice for a 09:00 Monday event must go out by 09:00 the previous Saturday — and a late send is rejected with `ERR_NOTICE_LEAD_VIOLATION`. A successful send stamps `sent_at` and moves the notice to `SENT`; recording the resident's acknowledgment moves it `SENT` → `ACKNOWLEDGED`. A notice still `QUEUED` when the logical clock reaches its `event_start` expires automatically, per the sweep described in §2.4. The notice list for a work order filters by `status`.

### 3.7. Completion, Post-Lining Acceptance, and Lateral Reinstatement

Completing a work order — `PUNCH_LIST` → `COMPLETED` — is the crew lead's final act and carries the heaviest gate set on the execution dimension. Any bypass plan attached to the work order must already be `DEMOBILIZED` or `CLOSED`; a still-running bypass blocks completion with `ERR_BYPASS_STILL_ACTIVE`, while `REJECTED` bypass plans never block completion. For a `CIPP_LINING` plan, two further gates apply: a `POST_CIPP` inspection of the segment must already exist in `CERTIFIED` status (`ERR_POST_INSPECTION_REQUIRED`), and every active lateral on the segment must show `reinstated` as true (`ERR_LATERALS_OPEN`). The lateral gate is vacuously satisfied when the segment has no active laterals at all.

Reinstatement is recorded one lateral at a time by the `CrewLead`. Each reinstatement flips the lateral's `reinstated` to true and increments the lateral's `version`; the operation is idempotent, may target any lateral of the segment whether active or not, and is permitted regardless of work-order state, with reinstatement progress always computed on demand from the lateral flags rather than stored as a separate field on the segment. Note the reset semantics that make this meaningful: when a completing lining work order finishes its plan — as the plan's last non-cancelled work order — every active lateral's `reinstated` is set back to false in that same call, and reinstatement recordings from that point flip them true again; the flags always describe the most recent lining job.

Completion stamps `completed_at` from the logical clock and derives `warranty_expires_at` as `completed_at` plus the district's `warranty_months`, adding calendar months with the day-of-month clamped to the length of the target month. Money settles at the same instant: every line's `final_line_cents` is recomputed from installed quantities, and the plan's `final_total_cents` becomes the sum of those final line values — falling back per line to the provisional value where no installed quantity was ever reported — plus the mobilization fee. When the finishing work order is the plan's last non-cancelled one, the plan completes automatically, `EXECUTING` → `COMPLETED`, and the cascade runs to the top: the district's `budget_committed_cents` releases the plan's provisional commitment (floored at zero), the segment's `rehab_status` becomes `REHABILITATED`, its `last_rehab_completed_at` is stamped, and — for lining plans — the lateral reset described above fires.

Billing travels on the second, independent dimension. Invoicing moves `UNBILLED` → `INVOICED` and is only possible once execution has reached `COMPLETED` (`ERR_NOT_COMPLETED`). An invoice issued in error can be voided back, `INVOICED` → `UNBILLED`, and once the district pays, marking paid moves `INVOICED` → `PAID`. Because the dimensions are independent, nothing about the billing track blocks or accelerates the execution track.

### 3.8. Warranty Claims and Re-Inspection

A warranty case opens against a segment, not against paper. A `DistrictEngineer` creates the case by naming the `work_order_id` of the completed work order whose warranty covers the claim, a `defect_summary` describing what the customer or inspector observed, and — because every claim triggers a fresh look — the scheduling trio for the linked re-inspection: `cycle_id`, `scheduled_at`, and `coder_id`. The case's `opened_at` is stamped from the logical clock and must be at or before the referenced work order's `warranty_expires_at`; a claim filed after the warranty window closes is rejected with `ERR_WARRANTY_EXPIRED`. Creation further requires the referenced work order to be `COMPLETED` (`ERR_INVALID_REQUEST` otherwise), the named cycle to exist and belong to the segment's district (`ERR_NOT_FOUND`), the named coder to be an active technician holding the `CODER` capability (`ERR_INVALID_REQUEST`), and `scheduled_at` to fall inside the cycle window, endpoints inclusive (`ERR_OUTSIDE_CYCLE_WINDOW`). Creation produces two things at once: the case itself in `OPENED`, and a linked `WARRANTY_RE` inspection in `SCHEDULED` on the segment, recorded on the case as `re_inspection_id`. If the segment's `rehab_status` was `REHABILITATED`, it moves to `WARRANTY` at this point.

From there the case is chained to the re-inspection's fate. When the linked inspection reaches `IN_PROGRESS`, the case follows automatically, `OPENED` → `RE_INSPECTION`. If the re-inspection is voided — by an engineer's explicit void or by the three-rejection auto-void described in §3.3 — the case falls back, `RE_INSPECTION` → `OPENED`, ready to be scheduled again.

Adjudication waits on evidence. Authorizing repair — `RE_INSPECTION` → `UNDER_REPAIR` — requires the linked re-inspection to be `CERTIFIED` with a `structural_grade` of at least 4 on the segment; anything less is `ERR_DEFECT_UNCONFIRMED`. Denying the claim — `RE_INSPECTION` → `DENIED` — requires the re-inspection to be `CERTIFIED` (`ERR_BASIS_NOT_CERTIFIED`) and a `resolution_note` explaining the decision (`ERR_INVALID_REQUEST`). Resolving a repaired claim — `UNDER_REPAIR` → `RESOLVED` — likewise requires a `resolution_note`. Closing a case never by itself changes the segment's `rehab_status`: it remains `WARRANTY` regardless of how many sibling cases are still open.

Two exits round out the lifecycle. A resolved claim can recur: reopening moves `RESOLVED` → `OPENED` and is permitted only while the logical clock is at or before the referenced work order's `warranty_expires_at` (`ERR_WARRANTY_EXPIRED`). And a claim still in `OPENED` or `RE_INSPECTION` may be withdrawn to `WITHDRAWN`; withdrawing from `RE_INSPECTION` also voids the linked re-inspection if it is still `SCHEDULED` or `CODING`. The warranty-case list filters by `work_order_id`, `re_inspection_id`, and `status`.

### 3.9. Flow Monitoring and Inflow/Infiltration Reduction

The district closes the loop by measuring what rehabilitation actually bought. A `DistrictEngineer` creates a flow-monitoring period with a `basin_label` naming the sub-basin, a `phase` of `PRE_REHAB` or `POST_REHAB`, and a `window_start` and `window_end`; unlike bypass windows, monitoring windows are closed intervals, inclusive of both endpoint instants. The new period sits in `DRAFT`.

Activation enforces three rules. Duration: the end must be at least 168 hours — one full week — after the start, or the period is rejected with `ERR_MONITORING_TOO_SHORT`. Exclusion: no other period for the same district and `basin_label` may be `ACTIVE` over an intersecting closed interval, and because the intervals are inclusive, two periods that merely share an endpoint still conflict (`ERR_FLOW_WINDOW_CONFLICT`). Sequencing: a `POST_REHAB` period may activate only after at least one district segment has reached `REHABILITATED` or `WARRANTY` (`ERR_NO_REHAB_YET`) — there must be something rehabilitated to measure.

Closing an `ACTIVE` period records the field data: both `dry_weather_avg_gpm` and `peak_storm_gpm` must be supplied in the close payload, or the close fails with `ERR_FLOW_DATA_MISSING`; supplied values that are not numbers fail with `ERR_INVALID_REQUEST`. Analysis then compares like with like. Analyzing a closed `POST_REHAB` period requires a baseline: a `PRE_REHAB` period for the same basin in `CLOSED` or `ANALYZED` status (`ERR_NO_BASELINE`). When several baselines qualify, the selector picks the one with the greatest `window_end`, breaking ties by the latest `created_at`. A baseline whose recorded flow figure is zero makes the ratio undefined and fails the analysis with `ERR_INVALID_REQUEST`.

The analysis computes two reduction percentages and returns both, each rounded half-up to one decimal place. The dry-weather reduction is one hundred times the quantity one minus the ratio of the post-rehabilitation dry-weather average to the baseline's dry-weather average. The storm-event reduction is the same construction over the two `peak_storm_gpm` figures. Only the dry-weather figure carries regulatory weight: `basin_target_met` is true exactly when the dry-weather reduction percentage is at least the district's `ii_reduction_target_pct` — the boundary is inclusive, so a measured reduction equal to the target passes, and the comparison uses the rounded figure exactly as reported. The storm-event figure is engineering context only and can never satisfy the basin target, even when it crosses the same threshold. The analysis response carries `dry_weather_reduction_pct`, `storm_event_reduction_pct`, and `basin_target_met`, and the period itself advances `CLOSED` → `ANALYZED`. Analyzing a `CLOSED` `PRE_REHAB` period is likewise permitted: it advances to `ANALYZED` and returns null for all three analysis fields. The period list for a district filters by `phase` and `status`.

## 4. Endpoint Definitions

Status codes follow a uniform rule. Endpoints that create a new stand-alone resource or add a new member to a collection return `201 Created`. Endpoints that modify an existing resource — including every state-transition action — return `200 OK`. The single deletion endpoint, removing a defect observation, returns `204 No Content` with no payload. Request and response bodies are deliberately not repeated here; each operation's inputs, outputs, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sewer/_clock/set_current_utc` | Set the server's logical clock | DistrictEngineer |
| POST | `/sewer/districts` | Create a SewerDistrict | DistrictEngineer |
| GET | `/sewer/districts` | List SewerDistricts (paginated) | Any (all five roles) |
| GET | `/sewer/districts/{id}` | Get a SewerDistrict | Any (all five roles) |
| POST | `/sewer/technicians` | Register a Technician | DistrictEngineer |
| GET | `/sewer/technicians/{id}` | Get a Technician | Any (all five roles) |
| PATCH | `/sewer/technicians/{id}` | Update technician (cert renewal, capabilities, active flag) | DistrictEngineer |
| POST | `/sewer/districts/{id}/inspection-cycles` | Create an InspectionCycle in DRAFT | DistrictEngineer |
| GET | `/sewer/districts/{id}/inspection-cycles` | List cycles of a district | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/inspection-cycles/{id}` | Get an InspectionCycle | DistrictEngineer, Coder, QaReviewer, CrewLead |
| POST | `/sewer/inspection-cycles/{id}/open` | Open a cycle for scheduling | DistrictEngineer |
| POST | `/sewer/inspection-cycles/{id}/close` | Close a cycle | DistrictEngineer |
| POST | `/sewer/districts/{id}/segments` | Create a PipeSegment | DistrictEngineer |
| GET | `/sewer/districts/{id}/segments` | List segments of a district | Any (all five roles) |
| GET | `/sewer/segments/{id}` | Get a PipeSegment (includes computed grades) | Any (all five roles) |
| POST | `/sewer/segments/{id}/laterals` | Add a Lateral to a segment | DistrictEngineer |
| GET | `/sewer/segments/{id}/laterals` | List laterals of a segment | Any (all five roles) |
| POST | `/sewer/segments/{id}/laterals/{lateralId}/reinstate` | Record lateral reinstatement after CIPP lining | CrewLead |
| POST | `/sewer/segments/{id}/cctv-inspections` | Schedule a CCTV inspection | DistrictEngineer |
| GET | `/sewer/segments/{id}/cctv-inspections` | List inspections of a segment | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/cctv-inspections` | Filtered list of inspections across segments (cycle/technician reverse lookup) | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/cctv-inspections/{id}` | Get a CctvInspection | DistrictEngineer, Coder, QaReviewer, CrewLead |
| POST | `/sewer/cctv-inspections/{id}/start` | Begin field capture | Coder |
| POST | `/sewer/cctv-inspections/{id}/begin-coding` | Enter coding phase | Coder |
| POST | `/sewer/cctv-inspections/{id}/submit-qa` | Submit coded inspection for QA | Coder |
| POST | `/sewer/cctv-inspections/{id}/certify` | QA certify (segregation of duties enforced) | QaReviewer |
| POST | `/sewer/cctv-inspections/{id}/reject` | QA reject back to CODING; third rejection auto-voids | QaReviewer |
| POST | `/sewer/cctv-inspections/{id}/void` | Void a SCHEDULED or CODING inspection | DistrictEngineer |
| POST | `/sewer/cctv-inspections/{id}/defects` | Append a defect observation (inspection must be CODING) | Coder |
| GET | `/sewer/cctv-inspections/{id}/defects` | List defects of an inspection | DistrictEngineer, Coder, QaReviewer, CrewLead |
| DELETE | `/sewer/cctv-inspections/{id}/defects/{defectId}` | Remove a defect (only while inspection is CODING) | Coder |
| POST | `/sewer/segments/{id}/rehab-plans` | Create a RehabPlan in DRAFT | DistrictEngineer |
| GET | `/sewer/segments/{id}/rehab-plans` | List plans of a segment | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/rehab-plans` | Filtered list of rehab plans (basis-inspection reverse lookup) | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/rehab-plans/{id}` | Get a RehabPlan | DistrictEngineer, Coder, QaReviewer, CrewLead |
| POST | `/sewer/rehab-plans/{id}/propose` | Propose a plan (method/grade compatibility checked) | DistrictEngineer |
| POST | `/sewer/rehab-plans/{id}/approve` | Approve a plan (OCC-guarded; commits budget) | DistrictEngineer |
| POST | `/sewer/rehab-plans/{id}/reopen` | Reopen an APPROVED plan back to DRAFT (releases budget) | DistrictEngineer |
| POST | `/sewer/rehab-plans/{id}/cancel` | Cancel a DRAFT or PROPOSED plan | DistrictEngineer |
| POST | `/sewer/rehab-plans/{id}/work-orders` | Issue a WorkOrder under an APPROVED plan | DistrictEngineer |
| GET | `/sewer/rehab-plans/{id}/work-orders` | List work orders of a plan | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/work-orders` | Filtered list of work orders (crew-lead reverse lookup) | DistrictEngineer, CrewLead |
| GET | `/sewer/work-orders/{id}` | Get a WorkOrder | DistrictEngineer, Coder, QaReviewer, CrewLead |
| POST | `/sewer/work-orders/{id}/mobilize` | Mobilize crew (bypass + notice gates) | CrewLead |
| POST | `/sewer/work-orders/{id}/begin-work` | Start physical work | CrewLead |
| POST | `/sewer/work-orders/{id}/stand-down` | Stand down from IN_WORK to MOBILIZED (demobilizes active bypass) | CrewLead |
| POST | `/sewer/work-orders/{id}/submit-punch` | Enter punch list (requires installed quantities) | CrewLead |
| POST | `/sewer/work-orders/{id}/resume-work` | Return from punch list to work | CrewLead |
| POST | `/sewer/work-orders/{id}/complete` | Complete execution (post-CIPP inspection + lateral gates) | CrewLead |
| POST | `/sewer/work-orders/{id}/cancel` | Cancel an ISSUED or MOBILIZED work order | DistrictEngineer |
| POST | `/sewer/work-orders/{id}/invoice` | Invoice a completed work order | DistrictEngineer |
| POST | `/sewer/work-orders/{id}/void-invoice` | Void an invoice back to UNBILLED | DistrictEngineer |
| POST | `/sewer/work-orders/{id}/mark-paid` | Mark an invoice paid | DistrictEngineer |
| POST | `/sewer/work-orders/{id}/line-items` | Add a line item (OCC-guarded on the work order) | DistrictEngineer |
| GET | `/sewer/work-orders/{id}/line-items` | List line items of a work order | DistrictEngineer, CrewLead |
| PATCH | `/sewer/work-orders/{id}/line-items/{lineId}` | Report installed quantity (IN_WORK or PUNCH_LIST) or correct scheduled quantity/price (ISSUED) | CrewLead, DistrictEngineer |
| POST | `/sewer/work-orders/{id}/bypass-plans` | Propose a bypass pumping plan | CrewLead |
| GET | `/sewer/work-orders/{id}/bypass-plans` | List bypass plans of a work order | DistrictEngineer, CrewLead |
| GET | `/sewer/bypass-plans/{id}` | Get a BypassPlan | DistrictEngineer, CrewLead |
| POST | `/sewer/bypass-plans/{id}/approve` | Approve bypass (window-conflict + pump-size checks) | DistrictEngineer |
| POST | `/sewer/bypass-plans/{id}/reject` | Reject a proposed bypass | DistrictEngineer |
| POST | `/sewer/bypass-plans/{id}/activate` | Activate bypass inside its window | CrewLead |
| POST | `/sewer/bypass-plans/{id}/demobilize` | Demobilize an active bypass | CrewLead |
| POST | `/sewer/bypass-plans/{id}/close` | Close a demobilized bypass | DistrictEngineer |
| POST | `/sewer/work-orders/{id}/customer-notices` | Queue a customer notice | CustomerServiceRep |
| GET | `/sewer/work-orders/{id}/customer-notices` | List notices of a work order | DistrictEngineer, CustomerServiceRep, CrewLead |
| GET | `/sewer/customer-notices/{id}` | Get a CustomerNotice | DistrictEngineer, CustomerServiceRep |
| POST | `/sewer/customer-notices/{id}/send` | Send a queued notice (lead-time enforced) | CustomerServiceRep |
| POST | `/sewer/customer-notices/{id}/acknowledge` | Acknowledge receipt | CustomerServiceRep |
| POST | `/sewer/segments/{id}/warranty-cases` | Open a warranty claim (creates linked WARRANTY_RE inspection in SCHEDULED) | DistrictEngineer |
| GET | `/sewer/segments/{id}/warranty-cases` | List warranty cases of a segment | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/warranty-cases` | Filtered list of warranty cases (work-order / re-inspection reverse lookup) | DistrictEngineer, Coder, QaReviewer, CrewLead |
| GET | `/sewer/warranty-cases/{id}` | Get a WarrantyCase | DistrictEngineer, Coder, QaReviewer, CrewLead |
| POST | `/sewer/warranty-cases/{id}/authorize-repair` | Authorize warranty repair after certified re-inspection confirms grade 4 or worse | DistrictEngineer |
| POST | `/sewer/warranty-cases/{id}/deny` | Deny a claim after certified re-inspection | DistrictEngineer |
| POST | `/sewer/warranty-cases/{id}/resolve` | Resolve a repaired claim | DistrictEngineer |
| POST | `/sewer/warranty-cases/{id}/reopen` | Re-open a resolved claim inside the warranty window | DistrictEngineer |
| POST | `/sewer/warranty-cases/{id}/withdraw` | Withdraw an open claim (voids pending re-inspection) | DistrictEngineer |
| POST | `/sewer/districts/{id}/flow-periods` | Create a flow monitoring period in DRAFT | DistrictEngineer |
| GET | `/sewer/districts/{id}/flow-periods` | List flow periods of a district | DistrictEngineer |
| GET | `/sewer/flow-periods/{id}` | Get a FlowMonitoringPeriod | DistrictEngineer |
| POST | `/sewer/flow-periods/{id}/activate` | Activate a monitoring window (duration + overlap + phase gates) | DistrictEngineer |
| POST | `/sewer/flow-periods/{id}/close` | Close with recorded flow data | DistrictEngineer |
| POST | `/sewer/flow-periods/{id}/analyze` | Analyze a closed POST_REHAB period against its PRE baseline | DistrictEngineer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified where each rule lives — in the cascade of §2.10 and in the workflow narratives of §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CYCLE_OVERLAP` | 409 |
| `ERR_INSPECTIONS_OPEN` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_OUTSIDE_CYCLE_WINDOW` | 409 |
| `ERR_NOT_ASSIGNED_CODER` | 409 |
| `ERR_CERT_EXPIRED` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_NO_DEFECTS_CODED` | 409 |
| `ERR_DEFECT_OUT_OF_RANGE` | 409 |
| `ERR_METHOD_INCOMPATIBLE` | 409 |
| `ERR_BASIS_NOT_CERTIFIED` | 409 |
| `ERR_PLAN_CONFLICT` | 409 |
| `ERR_BUDGET_EXCEEDED` | 409 |
| `ERR_WORK_STARTED` | 409 |
| `ERR_PLAN_NOT_APPROVED` | 409 |
| `ERR_NOT_ASSIGNED_CREW` | 409 |
| `ERR_BYPASS_REQUIRED` | 409 |
| `ERR_BYPASS_NOT_ACTIVE` | 409 |
| `ERR_BYPASS_STILL_ACTIVE` | 409 |
| `ERR_BYPASS_WINDOW_CONFLICT` | 409 |
| `ERR_PUMP_UNDERSIZED` | 409 |
| `ERR_OUTSIDE_WINDOW` | 409 |
| `ERR_NOTICE_LEAD_VIOLATION` | 409 |
| `ERR_ADDRESS_NOT_ON_SEGMENT` | 409 |
| `ERR_QTY_MISSING` | 409 |
| `ERR_NOT_COMPLETED` | 409 |
| `ERR_POST_INSPECTION_REQUIRED` | 409 |
| `ERR_LATERALS_OPEN` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_DEFECT_UNCONFIRMED` | 409 |
| `ERR_MONITORING_TOO_SHORT` | 409 |
| `ERR_FLOW_WINDOW_CONFLICT` | 409 |
| `ERR_NO_REHAB_YET` | 409 |
| `ERR_FLOW_DATA_MISSING` | 409 |
| `ERR_NO_BASELINE` | 409 |

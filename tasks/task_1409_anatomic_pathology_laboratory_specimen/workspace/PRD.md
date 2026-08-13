# Anatomic Pathology Lab API — Product Requirements Document

## 1. Introduction

Hospital anatomic pathology operates under an unforgiving discipline: every specimen that enters the laboratory must be traceable from the accessioning bench to the signed report, every gram of tissue must be accounted for as blocks are cut into slides, and every diagnostic opinion must survive retrospective quality review. Today these guarantees are carried by paper logs, LIS workarounds, and the vigilance of individual technologists — an arrangement that fails quietly exactly where it matters most: at handoffs between roles, at reflex testing decisions, and at the moment a signed report must be amended.

This document specifies a REST API for an anatomic pathology laboratory specimen workflow platform. The system governs the full lifecycle of a pathology case: patient registration and case intake, specimen accessioning under a two-identifier patient safety check, grossing, paraffin block and slide production with exacting tissue accounting, special-stain ordering with rule-driven reflex cascades, assignment of cases to credentialed pathologists under workload-aware selection, subspecialty sign-out with readiness gating, second-opinion consultation with automatic discrepancy capture, report amendment under segregation-of-duties controls, turnaround-time deadline tracking against a logical clock, and the controlled release of slides and blocks to outside institutions. All endpoints are mounted under the `/pathology` prefix.

The design treats the case as the anchor aggregate and every mutation as a reconciling event: creating a block recomputes case complexity, a failed slide pulls a case out of sign-out readiness, a resulted stain can spawn reflex orders that move the turnaround deadline, and signing a report completes specimens and cancels outstanding work in a single atomic act. Role separation is strict — laboratory administrators own configuration and assignment, histotechnologists run the wet bench, pathologists' assistants perform grossing, and only pathologists order studies, consult, and sign.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, wire contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles, spelled as follows: `LabAdmin`, `Histotech`, `PathologyAssistant`, and `Pathologist`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identities bind to data differently per role:

- When `X-User-Role` is `Pathologist`, `X-User-ID` is the `id` of the acting `Pathologist` entity; ownership checks on any resource that references a pathologist compare the resource's foreign-key field to `X-User-ID`. Concretely, submitting a case for sign-out, signing it out, or acknowledging a discrepancy requires `X-User-ID` to equal the case's `assigned_pathologist_id`; accepting, declining, or answering a consultation requires equality with the consultation's `consultant_pathologist_id`; incorporating or rerouting requires equality with `requesting_pathologist_id`; and signing or cancelling an amendment requires equality with the case's `amender_pathologist_id`.
- When `X-User-Role` is `LabAdmin`, `Histotech`, or `PathologyAssistant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but it is never compared to any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` envelope of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept resource-specific filter parameters, each matching on exact equality: the case list accepts `patient_id`, `assigned_pathologist_id`, `amender_pathologist_id`, `status`, and `tat_breached`; the specimen list accepts `case_id` and `status`; the block list accepts `specimen_id` and `status`; the slide list accepts `block_id` and `status`; the stain-order list accepts `case_id`, `block_id`, `reflex_rule_id`, `parent_stain_order_id`, `ordered_by_pathologist_id`, and `status`; the reflex-rule list accepts `active`; the report list accepts `case_id`, `supersedes_report_id`, `signed_by_pathologist_id`, and `status`; the consultation list accepts `case_id`, `consultant_pathologist_id`, `requesting_pathologist_id`, and `status`; the discrepancy list accepts `case_id`, `consultation_id`, `report_id`, `attributed_pathologist_id`, `status`, and `severity`; the release-request list accepts `block_id`, `slide_id`, and `status`; and the coverage-window list accepts `status`.

### 2.4. Common Resource Properties and Laboratory Identifiers

Every resource in the system — Patient, Pathologist, CoverageWindow, Case, Specimen, Block, Slide, StainOrder, ReflexRule, Report, Consultation, Discrepancy, and ReleaseRequest — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation.
- `version` (integer): starts at 1 and increments by exactly 1 on every mutation of the resource, including mutations driven by system cascades rather than direct client action.

Beyond the UUID, each accessioned specimen also receives a human-facing `accession_number`, minted by the server in the format `SP` followed by the two-digit year, a hyphen, and a six-digit sequence number that restarts each calendar year (for example, `SP26-000001`). Any `accession_number` value supplied by the client is ignored.

### 2.5. The Laboratory Logical Clock and Scheduled Sweeps

The laboratory does not trust wall-clock time for any temporal rule; it evaluates every deadline, window, and expiry against a **logical clock** held by the server. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never silently falls back to wall time. A `LabAdmin`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant and the server's current time becomes that value.

Setting the clock runs the system sweep. Every consultation still in `REQUESTED` whose `due_at` is strictly before the new clock value transitions to `EXPIRED` — a `due_at` exactly equal to the new clock value is not expired. Every release request in `SHIPPED` whose `due_back_at` is strictly before the new clock value transitions to `OVERDUE`, with equality likewise not overdue. Separately, reading a case that has not yet reached `FINAL` re-evaluates its turnaround breach flags against the current logical clock, so breach visibility never depends on a write having happened recently.

### 2.6. Case-Anchored Hierarchy and Cascading Reconciliation

Cases anchor a strict containment hierarchy: a case owns specimens, each specimen owns blocks, each block owns slides; stain orders, reports, consultations, and discrepancies also belong to a case. Any endpoint whose path nests one resource beneath another validates path identifiers strictly left to right, returning `ERR_NOT_FOUND` (HTTP 404) for the first path identifier that does not resolve, and only then checks identifiers referenced in the request body, each unresolved reference likewise producing `ERR_NOT_FOUND`.

Hierarchical consistency is maintained by automatic reconciliation rather than by client choreography. Events on children bubble up: the first grossed specimen moves its case from intake into workup; a specimen rejection can cancel the case outright. Events on the parent cascade down: signing out a case completes its in-flight specimens and cancels its open stain orders; cancelling a case cancels its non-terminal slides, stain orders, and consultations. Readiness can also be revoked: a failed slide or a newly ordered stain pulls a case that was awaiting sign-out back into workup. Each such automatic transition is a real mutation of the affected resource — its `updated_at` refreshes and its `version` increments by 1 — exactly as if a client had driven it. The specific cascades and their preconditions are described with each workflow in §3.

### 2.7. Measurement Precision and Rounding Discipline

All numeric measurement in the laboratory follows pinned precision rules so that independent implementations agree bit-for-bit:

- Tissue percentages (`tissue_remaining_pct`, `consumption_pct`) are carried at 1 decimal place using round-half-up. Crucially, rounding is applied **per consumption event before summation**: each section or recut event's consumption is rounded to 1 decimal first, and only then is the sum taken. Summing raw values and rounding once at the end is a different, forbidden algorithm — for example, three raw events of 3.33, 3.33, and 3.34 yield a remainder of 90.1 under the pinned per-event order but 90.0 under sum-then-round.
- Case `complexity_score` is carried at 1 decimal place; tier boundaries are inclusive at the lower bound and exclusive at the upper bound.
- Time durations derived from timestamp differences (`cold_ischemia_minutes`, `breach_minutes`) are whole minutes, truncated toward zero.
- Discrepancy rates (`discrepancy_rate_simple`, `discrepancy_rate_weighted`) are rounded half-up to 4 decimal places.
- `workload_score` is carried at 1 decimal place; because its component weights are integers, no rounding ever occurs in practice.
- Computed datetimes such as `turnaround_deadline` and `retention_until` are second-precision values with no rounding applied.

### 2.8. Optimistic Concurrency Control

Two write operations overwrite an existing definition or assignment and therefore require the caller to prove it has observed the current state:

- The case-reassignment endpoint (`POST /pathology/cases/{id}/reassign`) requires the request to carry `expected_case_version`, holding the `version` of the case as the client last read it. If the case's current `version` differs — because another writer has advanced it since — the reassignment is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the client from silently overwriting an assignment it never observed.
- The reflex-rule update endpoint (`PUT /pathology/reflex-rules/{id}`) requires the request to carry `expected_reflex_rule_version`, holding the rule's `version` as last read. A mismatch with the rule's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from clobbering a rule definition it never observed.

No other endpoint takes a version field; endpoints not named above process mutations without an OCC check.

### 2.9. Validation Order and Error Precedence

When a single request violates several rules, the returned error is determined by a fixed validation priority; a rule with a lower priority number wins over a higher-numbered one. The broad funnel runs as follows: authentication of the headers (priority 1) comes before role authorization and entity-backed ownership checks (priority 2), which come before request-shape validation (priority 3), which comes before resource-existence checks ordered left to right across path identifiers and then body-referenced identifiers (priority 4), which come before the case-terminal guard on child mutations (priority 5). The specific state, safety, constraint, referential, temporal, and tissue-budget rules then follow in their declared order. The priority-3 shape validation rejects with `ERR_INVALID_REQUEST` (HTTP 400) on any of: a missing required field, an invalid enum member, an out-of-range number such as a `container_count` below 1 or a `consumption_pct` of 0 or less, a window `end_at` not strictly after its `start_at`, a loan `due_back_at` not strictly after its `requested_out_at`, a reflex rule whose `followup_stain_type` equals its `trigger_stain_type`, or a release request whose identifier field does not match its declared `material_type`. Three orderings deserve emphasis because they are easy to get backwards: on release approval, the last-diagnostic-material safety check is evaluated before the loan-interval temporal check, so a doubly-forbidden approval surfaces `ERR_LAST_DIAGNOSTIC_MATERIAL` rather than `ERR_LOAN_INTERVAL_CONFLICT`; on consultation creation and reroute, the self-consultation check is evaluated before the consultant-is-the-assignee check, so a consultant who is both the requester and the assignee surfaces `ERR_SELF_CONSULTATION`; and on slide sectioning and recutting, the tissue-budget check is deliberately last, so a request that fails both a state rule and the budget surfaces the state error first.

## 3. Business Logic & Workflows

### 3.1. Patient Registration, Case Intake, and Turnaround Expectations

A `LabAdmin` registers each patient once, supplying the medical record number `mrn`, the patient's `full_name`, and `date_of_birth` in `YYYY-MM-DD` form. The `mrn` is unique across all patients and must be non-empty; a duplicate registration is rejected with `ERR_DUPLICATE_MRN` (HTTP 409). The pairing of `mrn` and `date_of_birth` is not ceremonial — it is the two-identifier safety check that every later specimen accession must satisfy.

Pathologists are registered by a `LabAdmin` with a `full_name`, a non-empty `subspecialties` array whose members are drawn from `DERMATOPATH`, `GI`, `BREAST`, `HEME`, `GU`, `GYN`, `NEURO`, and `GENERAL`, and an `active` flag that defaults to `true` when omitted. Fetching a pathologist also exposes three computed quality and load indicators: `workload_score`, `discrepancy_rate_simple`, and `discrepancy_rate_weighted`, each recomputed at read time, plus `last_assigned_at`, the timestamp of the most recent successful assignment naming this pathologist, which stays null until the first assignment.

A case is opened for a patient by a `LabAdmin` or `Histotech` through a payload containing the `patient_id`, the case `subspecialty` (one of the eight values above, driving assignment eligibility), and an optional `tat_mode`. The turnaround mode selects the deadline variant: `CALENDAR`, the default when omitted, counts plain clock hours with weekends and nights included, while `BUSINESS_HOURS` counts only Monday-through-Friday business time between 08:00 and 17:00 UTC — nine business hours per day. Under `BUSINESS_HOURS`, the base time is first advanced into the business window: a base before 08:00 moves to 08:00 the same day, and a base at or after 17:00, or falling on a Saturday or Sunday, moves to 08:00 on the next business day; only then are the allotted hours consumed. Identical inputs therefore yield a later deadline under `BUSINESS_HOURS` than under `CALENDAR` whenever any weekend or off-hours time intervenes.

The deadline itself rests on `tat_base_time`: the earliest `received_datetime` among the case's specimens that are not `REJECTED`, falling back to the case's `created_at` when no such specimen exists — which is exactly the situation at creation, so a fresh case's initial `turnaround_deadline` is computed from its creation timestamp. The allowance added to the base depends on the case's `complexity_class`: 48 hours for `SIMPLE`, 72 for `MODERATE`, 120 for `COMPLEX`, and 168 for `HIGH_COMPLEXITY`. Every case begins life in `OPEN` status with `complexity_class` `SIMPLE` and no assigned pathologist (`assigned_pathologist_id` null), no signed report (`current_signed_report_id` null), no amender (`amender_pathologist_id` null), no finalization timestamp (`finalized_at` null), and an `open_critical_discrepancy_count` of zero.

Breach evaluation compares a reference time against `turnaround_deadline`: for a case in `FINAL` or `AMENDING` the reference is `finalized_at`, and for any other status it is the current logical clock. `tat_breached` is true only when the reference time is strictly greater than the deadline — a reference exactly equal to the deadline is not a breach — and `breach_minutes` carries the whole-minute excess, truncated toward zero, or 0 when the case is not breached.

### 3.2. Specimen Accessioning, Grossing, Rejection, and Wet-Tissue Disposition

A `Histotech` accessions a specimen under an existing case by supplying `patient_mrn` and `patient_dob` alongside the specimen details. The two identifiers must exactly match the `mrn` and `date_of_birth` of the patient who owns the parent case; any mismatch is rejected with `ERR_PATIENT_IDENTIFIER_MISMATCH` (HTTP 422). The clinical payload comprises `specimen_type` — one of `BIOPSY`, `EXCISION`, `RESECTION`, or `CYTOLOGY` — free-text `anatomical_site`, the `collection_datetime` when the tissue left the patient, the `received_datetime` when the laboratory took custody, a `container_count` of at least 1, and an optional `fixative_type` of `FORMALIN`, `SALINE`, `FROZEN`, or `NONE` that defaults to `FORMALIN`. A `received_datetime` earlier than `collection_datetime` is rejected with `ERR_COLLECTION_AFTER_RECEIVED` (HTTP 422). On acceptance the server mints the `accession_number` (§2.4), computes `cold_ischemia_minutes` as the whole minutes from collection to receipt truncated toward zero — a value that later gates cold-sensitive stains — and sets the specimen's `status` to `ACCESSIONED` with `gross_description`, `retention_until`, `wet_tissue_disposed_at`, and `reject_reason` all null. Because the earliest receipt anchors the turnaround base, accessioning a specimen that lowers the case's earliest `received_datetime` recomputes `tat_base_time` and `turnaround_deadline`, and every accession recomputes the case's `complexity_score`.

Grossing is performed by a `PathologyAssistant`. The specimen must still be `ACCESSIONED` — grossing or rejecting a specimen in any other status is rejected with `ERR_SPECIMEN_NOT_ACCESSIONED` (HTTP 409) — and the parent case must be in `OPEN` or `WORKUP`. Grossing records the supplied `gross_description` and moves the specimen to `GROSSING`; when this is the case's first grossed specimen, the event bubbles up and the case itself moves `OPEN → WORKUP`. Rejection, by contrast, is a `Histotech` action that moves an `ACCESSIONED` specimen to `REJECTED`, recording the supplied `reason` in `reject_reason`. Rejection is refused once any block exists for the specimen, surfacing `ERR_BLOCKS_EXIST` (HTTP 409). A rejection shrinks the case: `tat_base_time` and `turnaround_deadline` are recomputed excluding the rejected specimen, and `complexity_score` is recomputed likewise. When every specimen of a case is `REJECTED` and the case is still `OPEN`, the case auto-transitions to `CANCELLED` with the standard cancellation cascade (§3.6).

A specimen reaches `COMPLETE` only as a cascade of case finalization (§3.6), never by direct client action; at that moment `retention_until` is set to the case's `finalized_at` plus the retention period configured for its `specimen_type`. Once retained wet tissue has outlived that period, a `Histotech` disposes of it: disposal requires the specimen to be `COMPLETE` with `wet_tissue_disposed_at` still null (otherwise `ERR_SPECIMEN_NOT_COMPLETE`, HTTP 409) and the current logical clock to be at or after `retention_until` — the boundary is inclusive, so disposal exactly at `retention_until` is eligible, while an earlier attempt is rejected with `ERR_RETENTION_NOT_ELAPSED` (HTTP 422). Disposal stamps `wet_tissue_disposed_at` and is not a status transition.

### 3.3. Block and Slide Production with Tissue Accounting

Once a specimen is grossed, a `PathologyAssistant` or `Histotech` creates paraffin blocks from it. Block creation requires the specimen to be in `GROSSING` or `PROCESSING` — attempting it on an `ACCESSIONED` specimen is rejected with `ERR_GROSS_NOT_RECORDED` (HTTP 409) — and the owning case must not be in `CANCELLED` or `FINAL` (otherwise `ERR_CASE_TERMINAL`, HTTP 409; this same guard covers every child mutation under a case, including specimen gross and reject, block creation and embedding, slide creation, sectioning, staining, QC review and recutting, and stain start and result entry). Each block carries a `block_label` unique within its specimen, with duplicates rejected by `ERR_DUPLICATE_BLOCK_LABEL` (HTTP 409). A new block starts in `CREATED` status with `tissue_remaining_pct` at exactly 100.0 and `on_loan` false, and the very first block created under a specimen moves that specimen `GROSSING → PROCESSING`. A `Histotech` then embeds a `CREATED` block, moving it to `EMBEDDED`; embedding from any other state is rejected with `ERR_BLOCK_NOT_CREATED` (HTTP 409).

Slides are ordered by a `Histotech` against an `EMBEDDED` block, each with a `slide_label` unique within the block (`ERR_DUPLICATE_SLIDE_LABEL`, HTTP 409, on collision) and a `stain_type` that currently admits only `H_E` and defaults to it. The block's state is reported precisely: targeting a block still in `CREATED` yields `ERR_BLOCK_NOT_EMBEDDED` (HTTP 409), while targeting a `DEPLETED` block yields the dedicated `ERR_BLOCK_DEPLETED` (HTTP 409) — the same pairing applies to sectioning and recutting. A new slide starts `ORDERED` with `consumption_pct` 0.0 and `qc_failure_reason` null.

Sectioning moves a slide `ORDERED → SECTIONED` and debits the block. The payload's `consumption_pct` must be greater than 0 (a shape violation otherwise, `ERR_INVALID_REQUEST`) and no greater than the block's current `tissue_remaining_pct`; a consumption that would drive the remaining tissue below 0.0 is rejected outright with `ERR_INSUFFICIENT_TISSUE` (HTTP 422) and no mutation is applied — this budget check is evaluated last, after every other rule (§2.9). The accepted consumption is rounded half-up to 1 decimal and recorded on the slide's `consumption_pct`, then the block's `tissue_remaining_pct` is recomputed as 100.0 minus the sum of the per-event rounded consumptions of every section or recut event ever applied to the block — including events on slides that were later `CANCELLED` — with the per-event-rounding-then-summation order pinned per §2.7. When the resulting remainder falls strictly below 5.0 percent, the block can no longer be recut and transitions `EMBEDDED → DEPLETED` automatically; depletion deliberately does not recompute the case's `complexity_score`, because `DEPLETED` blocks still count toward it. Staining completion moves `SECTIONED → STAINED`, and QC review of a `STAINED` slide takes a `result` payload: `PASS` moves the slide to the terminal `QC_PASSED`, while `FAIL` moves it to `QC_FAILED` and records the payload's `reason` in `qc_failure_reason`. A QC failure on a case that is `PENDING_SIGNOUT` pulls the case back to `WORKUP` — readiness must be re-earned. Any of these slide actions attempted from the wrong slide state is rejected with `ERR_SLIDE_WRONG_STATE` (HTTP 409). A failed slide is not dead: recutting moves it `QC_FAILED → SECTIONED` under exactly the same block-state and consumption rules as the original section, replacing the slide's `consumption_pct` with the new event's rounded value and debiting the block again.

All of these production events feed one case-level number. A case's `complexity_score` is the maximum specimen base weight among its non-`REJECTED` specimens — 1 for `BIOPSY`, 2 for `EXCISION`, 3 for `RESECTION`, 0 for `CYTOLOGY`, and 0 when no non-rejected specimen exists — plus 1.0 for every block of the case regardless of block status (`DEPLETED` included), plus 0.5 for every slide of the case that is not `CANCELLED`, plus 2.0 for every stain order of the case in `ORDERED`, `IN_PROGRESS`, or `RESULTED`. The score maps to `complexity_class` with inclusive lower and exclusive upper bounds: below 4.0 is `SIMPLE`, 4.0 up to but not including 10.0 is `MODERATE`, 10.0 up to but not including 20.0 is `COMPLEX`, and 20.0 or more is `HIGH_COMPLEXITY`. The classification recomputes whenever a block is created, a slide is created or cancelled, or a stain order is created or cancelled — reflex-created orders included — and on any change of `complexity_class` the `turnaround_deadline` is recomputed and `tat_breached` re-evaluated, since the deadline allowance depends on the class.

### 3.4. Special Stains and Reflex Ordering

A `Pathologist` orders a special study on a block of the case by supplying the target `block_id` and a `stain_type` drawn from `HER2_IHC`, `PD_L1`, `KI67`, `PAX5`, `CD20`, `MUCIN`, `GRAM`, or `GMS`. Ordering requires the case to be in `WORKUP`, `PENDING_SIGNOUT`, or `AMENDING` (otherwise `ERR_CASE_NOT_ORDERABLE`, HTTP 409), and the referenced block must belong to a specimen of the same case (otherwise `ERR_BLOCK_NOT_IN_CASE`, HTTP 422). The server stamps `ordered_by_pathologist_id` from the authenticated caller and leaves `reflex_rule_id` and `parent_stain_order_id` null on a manual order. Two cold-sensitive stains carry an ischemia gate: `HER2_IHC` requires the target block's specimen to have `cold_ischemia_minutes` of at most 60 minutes, and `PD_L1` requires at most 90 minutes, with violations rejected as `ERR_COLD_ISCHEMIA_EXCEEDED` (HTTP 422). Ordering a stain while the case is `PENDING_SIGNOUT` pulls the case back to `WORKUP`, mirroring the QC-failure pull-back, and each new order recomputes `complexity_score` — the stain term adds 2.0 per open or resulted order — cascading into deadline and breach re-evaluation on class change.

The bench workflow belongs to the `Histotech`: starting moves an order `ORDERED → IN_PROGRESS`, and result entry moves `IN_PROGRESS → RESULTED`, recording the supplied `result_value` (`POSITIVE`, `NEGATIVE`, or `EQUIVOCAL`) and stamping `resulted_at`. A `Pathologist` may cancel an order still in `ORDERED` or `IN_PROGRESS`, moving it to `CANCELLED`; the system applies the same transition to open orders when the case is cancelled or signed out. Any start, result, or cancel attempted from a disallowed state is rejected with `ERR_STAIN_WRONG_STATE` (HTTP 409). Cancellation also recomputes `complexity_score`, now excluding the cancelled order, and on class change the deadline and breach flags follow.

Resulting an order arms the reflex engine. The candidates are all `active` `ReflexRule` rows whose `trigger_stain_type` equals the resulted order's stain type and whose `trigger_result` equals the entered `result_value`. Matching rules fire in ascending `priority` order, ties broken by the rule's `created_at` ascending — never by identifier. Each rule fires at most once per case: if any stain order of the case already carries that rule in its `reflex_rule_id`, the rule is skipped. Firing is also depth-guarded along the `parent_stain_order_id` ancestry chain: a manual order sits at depth 0, its reflex children at depths 1 through 3, and an order already at depth 3 spawns nothing. A rule that fires creates a child order in `ORDERED` status with the rule's `followup_stain_type`, the same `block_id` as the resulted order, `reflex_rule_id` and `parent_stain_order_id` set to the rule and the triggering order respectively, and `ordered_by_pathologist_id` null to mark its system origin. Reflex children are validated like manual orders with one deliberate exception: the cold-ischemia gate is not re-applied to them. Each created child then drives the case complexity cascade exactly as a manual order would.

Reflex rules themselves are `LabAdmin` configuration. Creating one takes a human-readable `name`, the `trigger_stain_type`, the `trigger_result`, the `followup_stain_type` (which must differ from the trigger — an identical pair is a shape violation), an integer `priority` where lower fires first, and an `active` flag defaulting to `true`. Among rules with `active` true, the triple of trigger stain, trigger result, and follow-up stain must be unique; a colliding create or update is rejected with `ERR_DUPLICATE_REFLEX_RULE` (HTTP 409). Updating a rule is an OCC-guarded write carrying `expected_reflex_rule_version` (§2.8) and may change any of `name`, `trigger_stain_type`, `trigger_result`, `followup_stain_type`, `priority`, or `active`. Deactivation is a separate action that sets `active` to false; a deactivated rule never fires.

### 3.5. Assignment, Coverage Windows, and Pathologist Workload

Cases reach a signing pathologist through assignment, a `LabAdmin` action valid while the case is `OPEN` or `WORKUP` (otherwise `ERR_CASE_NOT_ASSIGNABLE`, HTTP 409). The request may name an explicit `pathologist_id` or omit it to invoke the deterministic server selector. Either way the target must be eligible: `active` must be true, the pathologist's `subspecialties` must contain the case's `subspecialty`, and no `ACTIVE` coverage window of type `UNAVAILABLE` may contain the current logical clock under closed containment — a window whose `start_at` is at or before now and whose `end_at` is at or after now blocks eligibility. An explicitly named pathologist who fails eligibility is rejected with `ERR_PATHOLOGIST_INELIGIBLE` (HTTP 422). The selector ranks the same eligibility pool by `workload_score` ascending, breaks ties by `last_assigned_at` ascending with never-assigned pathologists (null) first, and breaks remaining ties by the pathologist's `created_at` ascending; an empty pool is rejected with `ERR_NO_ELIGIBLE_PATHOLOGIST` (HTTP 422). A successful assignment sets `assigned_pathologist_id`, stamps the assignee's `last_assigned_at`, and recomputes the workload of both the former and the new assignee.

Reassignment — valid while the case is `WORKUP` or `PENDING_SIGNOUT`, otherwise `ERR_CASE_NOT_REASSIGNABLE` (HTTP 409) — applies the same eligibility and selection rules but additionally requires `expected_case_version` matching the case's current `version`; a stale value is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) per §2.8. Reassignment legitimately supersedes the current assignment: `assigned_pathologist_id` is swapped, the new assignee's `last_assigned_at` is stamped, and both pathologists' workloads are recomputed.

Coverage windows are how the laboratory knows who can take consults. A `LabAdmin` creates a window for a pathologist with a `window_type` of `CONSULT_SERVICE` (bookable consult duty) or `UNAVAILABLE` (no consults or assignments), a `start_at`, and an `end_at` that must be strictly after the start. Windows are born `ACTIVE` and can be cancelled, moving to `CANCELLED`; cancelling a window that is not `ACTIVE` is rejected with `ERR_COVERAGE_WINDOW_NOT_ACTIVE` (HTTP 409). Two temporal invariants guard creation among the same pathologist's `ACTIVE` windows: a new `CONSULT_SERVICE` window must not overlap any other `ACTIVE` `CONSULT_SERVICE` window under half-open containment — the interval runs from `start_at` inclusive to `end_at` exclusive, so touching endpoints where one window ends exactly when another begins are allowed — with overlaps rejected as `ERR_COVERAGE_WINDOW_OVERLAP` (HTTP 409); and a new `UNAVAILABLE` window must keep a buffer of at least 60 minutes from every `ACTIVE` `CONSULT_SERVICE` window, with smaller gaps rejected as `ERR_UNAVAILABILITY_BUFFER_VIOLATION` (HTTP 409).

The workload number behind selection is straightforward to reconstruct. A pathologist's `workload_score` sums a per-class weight over their assigned cases in `OPEN`, `WORKUP`, `PENDING_SIGNOUT`, or `AMENDING` — 1 for a `SIMPLE` case, 2 for `MODERATE`, 3 for `COMPLEX`, 5 for `HIGH_COMPLEXITY` — and adds 2 for every consultation where the pathologist is the consultant and the status is `ACCEPTED`. It is recomputed on read and refreshed at every event that changes the inputs: assignment and reassignment, a case leaving the open set through sign-out or cancellation, and a consultation entering or leaving `ACCEPTED` through accept, answer, reroute, or cancellation.

### 3.6. Sign-Out, Amendment, and Discrepancy Tracking

When the bench work is complete, the assigned pathologist submits the case for sign-out. Submission requires the case to be in `WORKUP` (otherwise `ERR_CASE_NOT_IN_WORKUP`, HTTP 409) and the caller to be the case's `assigned_pathologist_id` (otherwise `ERR_FORBIDDEN`). Readiness is gated on every child: every slide of the case that is not `CANCELLED` must be `QC_PASSED`, and every stain order must be `RESULTED` or `CANCELLED` — a violation surfaces `ERR_SLIDES_NOT_READY` (HTTP 409). Independently, at least one slide of the case must be `QC_PASSED`; a case whose slides are all cancelled fails with `ERR_EMPTY_SLIDE_SET` (HTTP 422). The aggregate emptiness check is evaluated after the per-slide readiness gate, and the two cannot fire together: a non-empty set of unready slides always surfaces `ERR_SLIDES_NOT_READY`, leaving `ERR_EMPTY_SLIDE_SET` for the all-cancelled situation. A passing submission moves the case `WORKUP → PENDING_SIGNOUT`, a state it can lose — a QC failure or a newly ordered stain pulls it back to `WORKUP` as described above.

Sign-out is the assigned pathologist's signature act. It requires `PENDING_SIGNOUT` (otherwise `ERR_CASE_NOT_PENDING_SIGNOUT`, HTTP 409), an `open_critical_discrepancy_count` of zero — meaning no discrepancy of severity `LEVEL_3` in `OPEN` or `ACKNOWLEDGED` status, a violation surfacing `ERR_UNRESOLVED_CRITICAL_DISCREPANCY` (HTTP 422) — and no consultation of the case still in `ACCEPTED` (otherwise `ERR_ACCEPTED_CONSULTATION_OPEN`, HTTP 409). A successful sign-out is a single atomic cascade: a `Report` is created with `report_class` `FINAL`, status `SIGNED`, `version_number` 1, `supersedes_report_id` and `amendment_reason` null, the supplied `diagnosis_text`, `signed_by_pathologist_id` set to the caller, and `signed_at` set to now; the case's `finalized_at` is stamped once and never rewritten by later amendments; `current_signed_report_id` points at the new report; `tat_breached` and `breach_minutes` are computed against `finalized_at`; every specimen still in `GROSSING` or `PROCESSING` becomes `COMPLETE` with `retention_until` set per §3.2; every stain order still in `ORDERED` or `IN_PROGRESS` becomes `CANCELLED`; and the assignee's workload is recomputed as the case leaves the open set.

A case can also be abandoned outright. A `LabAdmin` cancels a case, supplying a `reason`, while the case is `OPEN` or `WORKUP`; cancelling from any other status is rejected with `ERR_CASE_NOT_CANCELLABLE` (HTTP 409). Cancellation reconciles everything beneath the case: stain orders still in `ORDERED` or `IN_PROGRESS` become `CANCELLED`, consultations still in `REQUESTED`, `ACCEPTED`, or `ANSWERED` become `CANCELLED` (with the consultant's workload recomputed when an `ACCEPTED` one is dropped), and — for a case cancelled from `WORKUP`, where bench work may exist — slides still in `ORDERED`, `SECTIONED`, `STAINED`, or `QC_FAILED` become `CANCELLED` as well. The assigned pathologist's workload is recomputed as the case leaves the open set. The same cascade applies when a case cancels itself because all of its specimens were rejected (§3.2).

Diagnoses are not immutable, but correction is tightly governed. Opening an amendment requires the case to be `FINAL` (otherwise `ERR_CASE_NOT_FINAL`, HTTP 409) and enforces segregation of duties: when any discrepancy of severity `LEVEL_2` or `LEVEL_3` — in any status — references the case's `current_signed_report_id`, the caller must differ from that report's `signed_by_pathologist_id`, or the request is rejected with `ERR_SOD_AMENDMENT_FORBIDDEN` (HTTP 422). Amending moves the case `FINAL → AMENDING`, records the caller in `amender_pathologist_id`, and creates a new `Report` in `DRAFT` with `report_class` `AMENDED`, `version_number` one greater than the prior report's, `supersedes_report_id` set to the current signed report, and `diagnosis_text` plus `amendment_reason` taken from the payload. The amender — and only the amender, with `ERR_CASE_NOT_AMENDING` (HTTP 409) guarding the case state — then either signs or abandons the draft. Signing moves the case `AMENDING → FINAL`, stamps the draft's `signed_by_pathologist_id` and `signed_at` as it becomes `SIGNED`, and moves the previously signed report named by `supersedes_report_id` to `SUPERSEDED`, with `current_signed_report_id` updated and `amender_pathologist_id` cleared. Cancelling the amendment instead moves the case back to `FINAL`, discards the draft as `CANCELLED`, and leaves the previously signed report `SIGNED` and `current_signed_report_id` untouched — a full compensation with no drift. Across all of these flows one invariant holds: exactly one `SIGNED` report exists per case at any time, and the very first report of a case is created directly in `SIGNED` by sign-out; `DRAFT` is entered only through the amend flow.

Discrepancies feed the laboratory's quality program. A `Pathologist` or `LabAdmin` records one manually on a case with a `severity` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3`, a free-text `description`, and an optional `report_id`; such entries carry `source` `INTERNAL_QA`, a null `consultation_id`, and `status` `OPEN`. The attributed pathologist — `attributed_pathologist_id` — is the signer of the referenced report when `report_id` is given, and otherwise the case's assigned pathologist at creation time. Consultation-created discrepancies (§3.7) instead carry `source` `CONSULTATION` with `consultation_id` set. The case's `open_critical_discrepancy_count` tracks its `LEVEL_3` rows in `OPEN` or `ACKNOWLEDGED` and is what blocks sign-out. The assigned pathologist acknowledges an `OPEN` discrepancy, moving it to `ACKNOWLEDGED` — note that acknowledging a `LEVEL_3` does not unblock sign-out, since the count spans both states. Resolution is severity-tiered: a `LEVEL_1` discrepancy may be resolved directly from `OPEN` with `resolved_with_amendment` false permitted, while resolution from `ACKNOWLEDGED` accepts any severity; acting from any other state is rejected with `ERR_DISCREPANCY_WRONG_STATE` (HTTP 409). Resolving a `LEVEL_2` or `LEVEL_3` row additionally demands that the payload's `resolved_with_amendment` be true and that the case hold an `AMENDED` report in `SIGNED` status whose `signed_at` is strictly after the discrepancy's `created_at` — failing either condition yields `ERR_AMENDMENT_REQUIRED` (HTTP 422). Resolution stamps `resolved_at` and records `resolved_with_amendment`.

Each pathologist's two discrepancy rates are computed on read over a trailing 365-day window, both bounds inclusive, measured on the logical clock. The denominator counts `FINAL`-class reports signed by the pathologist with `signed_at` inside the window — a superseded final report still counts. The numerator set is the `RESOLVED` discrepancies attributed to the pathologist with `resolved_at` inside the window. `discrepancy_rate_simple` is the plain ratio of resolved discrepancies to signed finals, so a `LEVEL_1` and a `LEVEL_3` contribute identically; `discrepancy_rate_weighted` instead weights the numerator by severity — 1 for `LEVEL_1`, 3 for `LEVEL_2`, 5 for `LEVEL_3` — so identical data yields a strictly larger weighted rate whenever any `LEVEL_2` or `LEVEL_3` discrepancy is present. When the denominator is zero, both rates are exactly 0.0.

### 3.7. Second-Opinion Consultations

A pathologist who wants another set of eyes on a case requests a consultation, naming the `consultant_pathologist_id`, the requested `subspecialty`, the clinical `question_text`, and a response deadline `due_at`. The case must be in `WORKUP`, `PENDING_SIGNOUT`, `FINAL`, or `AMENDING` — an `OPEN` or `CANCELLED` case is not consultable and yields `ERR_CASE_NOT_CONSULTABLE` (HTTP 409). The server stamps `requesting_pathologist_id` from the authenticated caller. The consultant identity checks run in a fixed order (§2.9): the consultant must differ from the requester (`ERR_SELF_CONSULTATION`, HTTP 422), then from the case's assigned pathologist (`ERR_CONSULTANT_IS_ASSIGNED`, HTTP 422); the requested `subspecialty` must be a member of the consultant's `subspecialties` (`ERR_SUBSPECIALTY_MISMATCH`, HTTP 422); and `due_at` must be strictly in the future (`ERR_DUE_AT_NOT_FUTURE`, HTTP 422). A created consultation starts in `REQUESTED` with `reroute_count` 0 and `opinion_text`, `concordance`, `answered_at`, and `decline_reason` all null.

The consultant answers the request next. Accepting moves `REQUESTED → ACCEPTED` and requires the caller to be the named consultant, the logical clock to be strictly before `due_at` (a consultation past its deadline will already have been swept to `EXPIRED`), and the consultant not to be inside an `ACTIVE` `UNAVAILABLE` window under closed containment — `start_at` at or before now and `end_at` at or after now — with a violation rejected as `ERR_CONSULTANT_UNAVAILABLE` (HTTP 422). Acceptance raises the consultant's workload, since `ACCEPTED` consults carry weight. Declining moves `REQUESTED → DECLINED` and records the supplied `reason` in `decline_reason`. Once `ACCEPTED`, the consultant answers by supplying `opinion_text` and a `concordance` grade of `CONCORDANT`, `MINOR_DISCORDANT`, or `MAJOR_DISCORDANT`; the transition to `ANSWERED` stamps `answered_at`, drops the consult from the workload-bearing set, and — when the grade is not `CONCORDANT` — auto-creates a discrepancy on the case: a `MINOR_DISCORDANT` answer produces severity `LEVEL_1`, a `MAJOR_DISCORDANT` answer severity `LEVEL_2`, in both cases with `source` `CONSULTATION`, `consultation_id` set to the answered consultation, and `report_id` set to the case's `current_signed_report_id` (null when the case has no signed report yet). The requester then incorporates an `ANSWERED` opinion, moving it to the terminal `INCORPORATED`.

Consultations cycle: from `DECLINED` or `EXPIRED`, the requester may reroute to a new consultant with a new `due_at`, returning the consultation to `REQUESTED`. The reroute re-applies the creation-time checks to the new consultant — not the requester, not the case assignee, subspecialty match — and requires the new `due_at` to be strictly in the future; success replaces `consultant_pathologist_id` and `due_at` and increments `reroute_count` by 1. Consultation actions from disallowed states — accept or decline when not `REQUESTED`, answer when not `ACCEPTED`, incorporate when not `ANSWERED`, reroute when not `DECLINED` or `EXPIRED` — are rejected with `ERR_CONSULTATION_WRONG_STATE` (HTTP 409). Expiry itself is systemic: the clock sweep (§2.5) moves a `REQUESTED` consultation to `EXPIRED` when its `due_at` is strictly before the new clock value. Cancelling a case cascades its consultations in `REQUESTED`, `ACCEPTED`, or `ANSWERED` to `CANCELLED`, recomputing the consultant's workload when an `ACCEPTED` one is cancelled.

### 3.8. Material Release and External Loans

Blocks and slides may leave the laboratory on loan to outside institutions, but only after the diagnostic story is closed: creating a release request — open to `LabAdmin` and `Pathologist` — requires the material's case to be `FINAL`, otherwise `ERR_CASE_NOT_FINAL` (HTTP 409). The request declares a `material_type` of `BLOCK` or `SLIDE` and must carry exactly the matching identifier — `block_id` when the type is `BLOCK`, `slide_id` when `SLIDE`; presenting the wrong field or both is a shape violation. The material itself must be releasable: a block must be `EMBEDDED` and a slide must be `QC_PASSED`, otherwise `ERR_MATERIAL_NOT_RELEASABLE` (HTTP 409). The payload also carries the `requesting_institution`, the `reason` for the release, the planned loan start `requested_out_at`, and the return deadline `due_back_at`, which must be strictly after `requested_out_at`. A created request starts in `REQUESTED` with `shipped_at`, `returned_at`, and `deny_reason` null and `returned_late` false.

Approval is a `LabAdmin` decision with two gates, safety before temporal (§2.9). The safety gate refuses to strip a case of its last diagnostic material: approving a slide that is the only `QC_PASSED` slide of its case, or a block that is the only `EMBEDDED` non-`DEPLETED` block of its case, is rejected with `ERR_LAST_DIAGNOSTIC_MATERIAL` (HTTP 422). The temporal gate then checks for scheduling conflicts: if any other release request for the same material is in `REQUESTED`, `APPROVED`, `SHIPPED`, or `OVERDUE` with a closed interval from `requested_out_at` to `due_back_at` that intersects this request's interval — and touching endpoints count as a conflict — approval is rejected with `ERR_LOAN_INTERVAL_CONFLICT` (HTTP 409); a `DENIED` or `RETURNED` request frees its interval. Denial records the supplied `reason` in `deny_reason`. Approving or denying a request not in `REQUESTED`, shipping one not `APPROVED`, or returning one not `SHIPPED` or `OVERDUE` is rejected with `ERR_RELEASE_WRONG_STATE` (HTTP 409).

Physical movement belongs to the `Histotech`. Shipping an `APPROVED` request moves it to `SHIPPED`, stamps `shipped_at`, and flips the referenced material's `on_loan` to true. The clock sweep (§2.5) moves a `SHIPPED` request to `OVERDUE` once `due_back_at` is strictly before the new clock value. Return accepts a request in `SHIPPED` or `OVERDUE`, moves it to `RETURNED`, stamps `returned_at`, computes `returned_late` as true exactly when the return happens strictly after `due_back_at`, and flips `on_loan` back to false, restoring the material's availability.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — this includes patient, pathologist, coverage-window, case, specimen, block, slide, stain-order, reflex-rule, consultation, discrepancy, and release-request creation, as well as opening an amendment, which creates the amended draft report. Operations that modify an existing resource — state transitions, assignment, sign-out, amendment signing or cancellation, updates, and the clock set — return `200 OK`. All endpoints are mounted under the `/pathology` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pathology/patients` | Register a patient | LabAdmin |
| GET | `/pathology/patients/{id}` | Fetch one patient | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/pathologists` | Register a pathologist | LabAdmin |
| GET | `/pathology/pathologists/{id}` | Fetch one pathologist with computed workload and discrepancy rates | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/pathologists/{id}/coverage-windows` | Create a coverage window for a pathologist | LabAdmin |
| GET | `/pathology/pathologists/{id}/coverage-windows` | List coverage windows of a pathologist | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/coverage-windows/{id}/cancel` | Cancel an ACTIVE coverage window | LabAdmin |
| POST | `/pathology/cases` | Open a pathology case for a patient | LabAdmin, Histotech |
| GET | `/pathology/cases/{id}` | Fetch one case with all computed fields | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/cases` | List cases with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/cases/{id}/assign` | Assign a pathologist explicitly or via the server selector | LabAdmin |
| POST | `/pathology/cases/{id}/reassign` | Reassign the case under optimistic concurrency | LabAdmin |
| POST | `/pathology/cases/{id}/submit-for-signout` | Assigned pathologist submits a worked-up case | Pathologist |
| POST | `/pathology/cases/{id}/sign-out` | Sign the case out, creating the SIGNED FINAL report | Pathologist |
| POST | `/pathology/cases/{id}/amend` | Open an amendment on a FINAL case | Pathologist |
| POST | `/pathology/cases/{id}/amend/sign` | Sign the amended report, superseding the prior one | Pathologist |
| POST | `/pathology/cases/{id}/amend/cancel` | Abandon the amendment, leaving the prior report intact | Pathologist |
| POST | `/pathology/cases/{id}/cancel` | Cancel an OPEN or WORKUP case with child cascade | LabAdmin |
| POST | `/pathology/cases/{id}/specimens` | Accession a specimen under a case | Histotech |
| GET | `/pathology/specimens/{id}` | Fetch one specimen | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/specimens` | List specimens with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/specimens/{id}/reject` | Reject an accessioned specimen that has no blocks | Histotech |
| POST | `/pathology/specimens/{id}/gross` | Record the gross description | PathologyAssistant |
| POST | `/pathology/specimens/{id}/dispose-wet-tissue` | Dispose of wet tissue after the retention period | Histotech |
| POST | `/pathology/specimens/{id}/blocks` | Create a paraffin block for a grossed specimen | PathologyAssistant, Histotech |
| GET | `/pathology/blocks/{id}` | Fetch one block | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/blocks` | List blocks with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/blocks/{id}/embed` | Embed a CREATED block | Histotech |
| POST | `/pathology/blocks/{id}/slides` | Order a routine H&E slide from an EMBEDDED block | Histotech |
| GET | `/pathology/slides/{id}` | Fetch one slide | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/slides` | List slides with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/slides/{id}/section` | Section an ORDERED slide, debiting block tissue | Histotech |
| POST | `/pathology/slides/{id}/stain-complete` | Mark a SECTIONED slide as STAINED | Histotech |
| POST | `/pathology/slides/{id}/qc-review` | QC review of a STAINED slide (PASS or FAIL) | Histotech |
| POST | `/pathology/slides/{id}/recut` | Recut a QC_FAILED slide, debiting additional tissue | Histotech |
| POST | `/pathology/cases/{id}/stain-orders` | Order a special stain on a block of the case | Pathologist |
| GET | `/pathology/stain-orders/{id}` | Fetch one stain order | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/stain-orders` | List stain orders with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/stain-orders/{id}/start` | Begin processing an ORDERED stain | Histotech |
| POST | `/pathology/stain-orders/{id}/result` | Enter the stain result, firing reflex evaluation | Histotech |
| POST | `/pathology/stain-orders/{id}/cancel` | Cancel an open stain order | Pathologist |
| POST | `/pathology/reflex-rules` | Create a reflex rule | LabAdmin |
| GET | `/pathology/reflex-rules/{id}` | Fetch one reflex rule | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/reflex-rules` | List reflex rules | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| PUT | `/pathology/reflex-rules/{id}` | Update a reflex rule under optimistic concurrency | LabAdmin |
| POST | `/pathology/reflex-rules/{id}/deactivate` | Deactivate a reflex rule | LabAdmin |
| GET | `/pathology/reports/{id}` | Fetch one report | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/reports` | List reports with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/cases/{id}/consultations` | Request a second-opinion consultation | Pathologist |
| GET | `/pathology/consultations/{id}` | Fetch one consultation | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/consultations` | List consultations with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/consultations/{id}/accept` | Consultant accepts the consultation | Pathologist |
| POST | `/pathology/consultations/{id}/decline` | Consultant declines the consultation | Pathologist |
| POST | `/pathology/consultations/{id}/answer` | Consultant answers with opinion and concordance | Pathologist |
| POST | `/pathology/consultations/{id}/incorporate` | Requester incorporates the answered opinion | Pathologist |
| POST | `/pathology/consultations/{id}/reroute` | Reroute a DECLINED or EXPIRED consultation to a new consultant | Pathologist |
| POST | `/pathology/cases/{id}/discrepancies` | Manually record a QA discrepancy on a case | Pathologist, LabAdmin |
| GET | `/pathology/discrepancies/{id}` | Fetch one discrepancy | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/discrepancies` | List discrepancies with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/discrepancies/{id}/acknowledge` | Assigned pathologist acknowledges an OPEN discrepancy | Pathologist |
| POST | `/pathology/discrepancies/{id}/resolve` | Resolve a discrepancy with severity-tiered amendment rules | Pathologist, LabAdmin |
| POST | `/pathology/release-requests` | Request release of a block or slide | LabAdmin, Pathologist |
| GET | `/pathology/release-requests/{id}` | Fetch one release request | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| GET | `/pathology/release-requests` | List release requests with filters and pagination | LabAdmin, Histotech, PathologyAssistant, Pathologist |
| POST | `/pathology/release-requests/{id}/approve` | Approve a release (safety then temporal gates) | LabAdmin |
| POST | `/pathology/release-requests/{id}/deny` | Deny a release request | LabAdmin |
| POST | `/pathology/release-requests/{id}/ship` | Ship an approved release, placing material on loan | Histotech |
| POST | `/pathology/release-requests/{id}/return` | Receive loaned material back | Histotech |
| POST | `/pathology/_clock/set_current_utc` | Set the server's logical clock and run the expiry sweeps | LabAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CASE_TERMINAL` | 409 |
| `ERR_SPECIMEN_NOT_ACCESSIONED` | 409 |
| `ERR_GROSS_NOT_RECORDED` | 409 |
| `ERR_BLOCK_NOT_CREATED` | 409 |
| `ERR_BLOCK_NOT_EMBEDDED` | 409 |
| `ERR_BLOCK_DEPLETED` | 409 |
| `ERR_SLIDE_WRONG_STATE` | 409 |
| `ERR_CASE_NOT_ASSIGNABLE` | 409 |
| `ERR_CASE_NOT_REASSIGNABLE` | 409 |
| `ERR_CASE_NOT_CANCELLABLE` | 409 |
| `ERR_CASE_NOT_IN_WORKUP` | 409 |
| `ERR_CASE_NOT_PENDING_SIGNOUT` | 409 |
| `ERR_CASE_NOT_FINAL` | 409 |
| `ERR_CASE_NOT_AMENDING` | 409 |
| `ERR_CASE_NOT_ORDERABLE` | 409 |
| `ERR_CASE_NOT_CONSULTABLE` | 409 |
| `ERR_STAIN_WRONG_STATE` | 409 |
| `ERR_CONSULTATION_WRONG_STATE` | 409 |
| `ERR_DISCREPANCY_WRONG_STATE` | 409 |
| `ERR_RELEASE_WRONG_STATE` | 409 |
| `ERR_MATERIAL_NOT_RELEASABLE` | 409 |
| `ERR_SPECIMEN_NOT_COMPLETE` | 409 |
| `ERR_COVERAGE_WINDOW_NOT_ACTIVE` | 409 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PATIENT_IDENTIFIER_MISMATCH` | 422 |
| `ERR_COLD_ISCHEMIA_EXCEEDED` | 422 |
| `ERR_UNRESOLVED_CRITICAL_DISCREPANCY` | 422 |
| `ERR_ACCEPTED_CONSULTATION_OPEN` | 409 |
| `ERR_SELF_CONSULTATION` | 422 |
| `ERR_CONSULTANT_IS_ASSIGNED` | 422 |
| `ERR_SOD_AMENDMENT_FORBIDDEN` | 422 |
| `ERR_LAST_DIAGNOSTIC_MATERIAL` | 422 |
| `ERR_DUPLICATE_MRN` | 409 |
| `ERR_DUPLICATE_BLOCK_LABEL` | 409 |
| `ERR_DUPLICATE_SLIDE_LABEL` | 409 |
| `ERR_DUPLICATE_REFLEX_RULE` | 409 |
| `ERR_EMPTY_SLIDE_SET` | 422 |
| `ERR_SLIDES_NOT_READY` | 409 |
| `ERR_PATHOLOGIST_INELIGIBLE` | 422 |
| `ERR_NO_ELIGIBLE_PATHOLOGIST` | 422 |
| `ERR_SUBSPECIALTY_MISMATCH` | 422 |
| `ERR_BLOCK_NOT_IN_CASE` | 422 |
| `ERR_BLOCKS_EXIST` | 409 |
| `ERR_AMENDMENT_REQUIRED` | 422 |
| `ERR_COLLECTION_AFTER_RECEIVED` | 422 |
| `ERR_DUE_AT_NOT_FUTURE` | 422 |
| `ERR_CONSULTANT_UNAVAILABLE` | 422 |
| `ERR_COVERAGE_WINDOW_OVERLAP` | 409 |
| `ERR_UNAVAILABILITY_BUFFER_VIOLATION` | 409 |
| `ERR_LOAN_INTERVAL_CONFLICT` | 409 |
| `ERR_RETENTION_NOT_ELAPSED` | 422 |
| `ERR_INSUFFICIENT_TISSUE` | 422 |

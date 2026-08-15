# Structural Steel Fabrication API — Product Requirements Document

## 1. Introduction

Structural steel work runs on paper as much as it runs on iron. An AISC-certified fabricator and erector lives inside a chain of custody that begins with a detailer's shop drawing and ends with a piece of steel standing in a building — and every link in that chain (the engineer's approval stamp, the mill's scale ticket, the welder's qualification card, the inspector's report, the truck's load list, the general contractor's progress payment) must reconcile exactly when an auditor pulls the file. This document specifies the Structural Steel Fabrication API, the system of record for that chain: it tracks jobs from award through fabrication, erection, and completion; it manages the shop drawing revision cycle with engineer-of-record decisions; it books mill orders against the advance bill of material; it follows every piece mark from detailing through the shop, inspection, shipping, and erection; and it carries the money — progress billings with tiered retainage, field fixes, and backcharges — alongside the steel.

Two design commitments shape every workflow below. The first is segregation of duties: the detailer who submits a drawing may not approve it, and the welder who lays a weld may not inspect it. The second is derived-state discipline: piece staleness, sequence completion, load weight, job percent-complete, and even job completion itself are never asserted by a client — they are computed from the underlying records and kept consistent automatically as those records change. Wherever a computed view could go stale between a client's read and its write, the API pins an optimistic-concurrency token to the parent record so that decisions are always made against observed state.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly seven roles, spelled as follows: `FABRICATOR_ADMIN`, `DETAILER`, `EOR`, `FOREMAN`, `WELDER`, `QC_INSPECTOR`, and `GC_PM`. Each endpoint admits a fixed set of roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403).

The seven roles divide the work along the industry's natural lines. The `FABRICATOR_ADMIN` is the fabricator's operations manager: contracts, material, welder registration, billing creation, backcharge settlement, and the logical clock. The `DETAILER` runs the shop drawing cycle — creating drawings, submitting them, and cutting new revisions. The `EOR` is the engineer of record who approves or rejects submitted drawings and must never be the submitter. The `FOREMAN` runs shop and field: erection sequences, pieces, shipping loads, and field fixes. The `WELDER` logs welds and performs repairs, and may act only on their own welds. The `QC_INSPECTOR` schedules, submits, and voids inspections, and must never inspect a weld they performed. The `GC_PM` is the general contractor's project manager: approving field fixes, responding to backcharges, and approving, paying, or voiding progress billings. All seven roles may use every read endpoint in the API.

Identity semantics differ across the roles. When `X-User-Role` is `WELDER`, `X-User-ID` is the `id` of the acting Welder record; ownership checks on any resource that references a welder compare the resource's `welder_id` field against `X-User-ID`. Logging a weld or repairing one under another welder's identity is rejected with `ERR_FORBIDDEN` (HTTP 403). For each of the other six roles — `FABRICATOR_ADMIN`, `DETAILER`, `EOR`, `FOREMAN`, `QC_INSPECTOR`, and `GC_PM` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_user_id` on a drawing or billing, `decided_by_user_id` on a drawing decision, or `inspector_user_id` on an inspection) but does not compare it to any entity's `id`.

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

Endpoints that return lists of resources paginate through two query parameters. The `limit` parameter caps how many items come back; it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100 — a `limit` above 100 is clamped to 100 rather than rejected, while a `limit` below 1, a negative `offset`, or a non-integer value for either parameter fails as `ERR_INVALID_REQUEST` (HTTP 400). The `offset` parameter states how many items to skip and defaults to 0.

Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by creation order (the earlier-created record first).

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — jobs, shop drawings, mill orders, erection sequences, pieces, welders, welds, inspections, shipping loads, field fixes, backcharges, and progress billings — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed whenever the resource is modified.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one with every modification to the resource.

Side-effect cascades count as modifications. When one operation recomputes derived fields on a related resource — an approved billing booking amounts onto its job, a superseded drawing flipping piece staleness flags, an erected piece refreshing the job's erected weight — each resource so touched refreshes its own `updated_at` and increments its own `version`. Recomputation is immediate: a response to any mutating request reflects every derived value the mutation touched, with no eventual-consistency window.

### 2.5. The Logical Clock

All date-sensitive behavior in the system reads a single server-side logical clock rather than wall-clock time. The clock governs three rules: a weld's `weld_date` may not lie in the future; a welder's qualification is valid only through `qual_expires_on`; and the 183-day welding-continuity window of §3.5 is measured backward from the current logical date. Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own.

A `FABRICATOR_ADMIN`-only test-driving capability sets the clock: the caller supplies a `to_iso8601` instant, and every subsequent clock read returns the set instant until the clock is set again.

### 2.6. Cents, Pounds, and Percent: The Precision Rules

Three numeric disciplines run through the system, and each is pinned exactly.

Money is integer cents everywhere — contract values, mill invoices, billing lines, backcharge amounts, job aggregates. Where a computed monetary component could land on a fraction of a cent, it is rounded half up to whole cents; the specific points at which rounding fires are pinned per calculation in §3 and are part of the contract.

Percent complete is a number carried to exactly four decimal places, rounded half up. The four-decimal snapshot frozen onto a progress billing obeys the same rule.

Weight is integer pounds, exact, with no rounding anywhere. Mill pricing converts pounds to hundredweight — one hundredweight is exactly one hundred pounds — by dividing the weight by one hundred before applying the per-hundredweight price; shop weights are multiples of one hundred in practice, so this division is exact in the normal case. Day-count rules (welder continuity, laydown buffering) operate in whole days.

### 2.7. Optimistic Concurrency Control

Exactly two operations in the system carry an optimistic-concurrency token, and both guard against a client acting on a superseded view of a parent record.

Revising a shop drawing requires the request to carry `expected_drawing_version`, holding the source drawing's `version` as the client last observed it. If that value does not match the drawing's current `version` — because, for instance, another writer has already cut the next revision from the same source — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating a progress billing requires the request to carry `expected_job_version`, holding the job's `version` as the client last observed it. Billing creation snapshots the job's aggregates — percent complete, billed-to-date, settled backcharges — so a stale job view would produce a billing computed from superseded aggregates; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Every other write in the API is validated purely against current state per the ladder of §2.8.

### 2.8. The Validation Ladder and Reference Resolution

Every request walks a fixed ladder of checks, and the first failing rung produces the response — later rungs are never evaluated. The rungs, in order:

1. **Authentication.** Missing or unrecognized credentials fail as `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization.** A role not admitted by the endpoint, or a `WELDER` caller acting on another welder's weld, fails as `ERR_FORBIDDEN` (HTTP 403).
3. **Existence.** Path identifiers are validated left to right — for a path carrying both a load `id` and a `piece_id`, the load resolves first — and the first identifier that does not resolve fails as `ERR_NOT_FOUND` (HTTP 404). Foreign keys supplied in a request body receive the same treatment once the path identifiers have resolved.
4. **Request shape.** Missing required fields, a request body that is not a JSON object, wrong types, out-of-range enum values, non-positive integers where a positive value is required, a negative `settled_amount_cents`, a `weld_date` later than the current logical date, an empty `repair_lines` array, or a `window_end` that is not strictly after its `window_start` fail as `ERR_INVALID_REQUEST` (HTTP 400).
5. **Stale version.** The optimistic-concurrency tokens of §2.7 fail as `ERR_STALE_VERSION` (HTTP 412).
6. **State legality.** The target entity must be in a valid from-state for the requested transition — including a mill order placed only against a job that is not `ESTIMATING`, load line edits only while the load is `STAGING` or `LOADING`, and a field fix reported only on a `SHIPPED` or `ERECTED` piece — failing as `ERR_INVALID_STATE` (HTTP 409).
7. **Safety and segregation.** Welder qualification and continuity on weld logging (`ERR_WELDER_NOT_QUALIFIED`), drawing self-approval on drawing decisions (`ERR_SELF_APPROVAL_FORBIDDEN`), weld-inspector segregation on weld inspection submission (`ERR_SEGREGATION_OF_DUTIES`), and the AISC audit hold on load shipment (`ERR_AISC_HOLD_ACTIVE`).
8. **Referential gates.** Within this rung the checks evaluate in a fixed order: piece staleness (`ERR_PIECE_STALE_REVISION`), pinned drawing approval (`ERR_DRAWING_NOT_APPROVED`), sequence release (`ERR_SEQUENCE_NOT_RELEASED`), material receipt (`ERR_MATERIAL_NOT_RECEIVED`), job fabricating for sequence release (`ERR_JOB_NOT_FABRICATING`), job billable for billing creation (`ERR_JOB_NOT_BILLABLE`), same-job consistency of body references (`ERR_CROSS_JOB_REFERENCE`), inspection target shape (`ERR_INSPECTION_TARGET_INVALID`), inspection not locked by downstream progress (`ERR_INSPECTION_LOCKED`), and load readiness at shipment (`ERR_PIECES_NOT_READY`).
9. **Constraint satisfaction.** Uniqueness rules (`ERR_PIECE_MARK_NOT_UNIQUE`, `ERR_DRAWING_NOT_UNIQUE`, `ERR_SEQUENCE_NUMBER_NOT_UNIQUE`, `ERR_LOAD_NUMBER_NOT_UNIQUE`, `ERR_DUPLICATE_BILLING_PERIOD`), scheduling and capacity rules (`ERR_WELDER_DOUBLE_BOOKED`, `ERR_LAYDOWN_SLOT_CONFLICT`, `ERR_LOAD_OVERWEIGHT`), weld completeness before final inspection (`ERR_WELDS_INCOMPLETE`), the weld repair limit (`ERR_WELD_REPAIR_LIMIT`), mill weight tolerance (`ERR_WEIGHT_OUT_OF_TOLERANCE`), and the open-backcharge block on field-fix resolution (`ERR_BACKCHARGE_OPEN`).
10. **Fiscal limits.** Settled backcharges may not exceed earned billings (`ERR_BACKCHARGE_EXCEEDS_EARNED`).

### 2.9. Cascades, Automatic Transitions, and the Compound Completion Check

Clients drive some transitions directly; others the system drives itself whenever their criteria come true. Three cascade families run through the domain, and each is spelled out fully in §3.

The first is the drawing-approval cascade: approving a new revision supersedes its predecessor, marks not-yet-shipped pieces pinned to the predecessor as stale, and pulls those stale pieces off any load they were on. The second is the inspection cascade: submitting or voiding an inspection moves the dependent piece or weld forward or backward along its own state machine. The third is the erection cascade: erecting a piece refreshes the job's erected weight, completes the piece's sequence when it was the last one standing, and then runs the compound completion check on the job.

That compound check is the system's only route to job completion. It is re-evaluated automatically after every piece erection, every sequence auto-completion, every billing payment or void, and every backcharge settlement — never through a client-callable transition of its own. When the check passes, the job moves to `COMPLETE` on its own. Every hop of every cascade is a mutation of the touched resource: its `updated_at` refreshes and its `version` increments per §2.4.

## 3. Business Logic & Workflows

### 3.1. The Job: Award, Fabrication, Erection

Everything hangs off the job. A `FABRICATOR_ADMIN` creates one with a `name`, a `contract_value_cents` that must be a positive integer, and a `billing_basis` of either `WEIGHT` or `COUNT` — a permanent choice that selects which percent-complete variant every billing of the job will use. The optional `requires_aisc_hold` flag defaults to false; when set true, no load of the job may ship until a passed AISC audit inspection exists for the job (§3.7). A new job opens in `ESTIMATING` with every aggregate at zero, and the job register can be listed with an optional `status` filter or read individually with its computed aggregates.

Three manual transitions move the job through its life, each performed by a `FABRICATOR_ADMIN` and each incrementing the job's `version`. Awarding moves `ESTIMATING` to `AWARDED`. Starting fabrication moves `AWARDED` to `FABRICATING` and is gated on shop drawing approval: at least one drawing of the job must be `APPROVED`, or the request is rejected with `ERR_DRAWING_NOT_APPROVED`. Starting erection moves `FABRICATING` to `ERECTING` and is gated on field readiness: at least one erection sequence of the job must be `RELEASED`, or the request fails with `ERR_SEQUENCE_NOT_RELEASED`. Invoking any of these from the wrong from-state fails with `ERR_INVALID_STATE`. The final move, `ERECTING` to `COMPLETE`, belongs to the system alone and is covered in §3.9.

A job carries eight computed aggregates, all refreshed immediately as the underlying records change. `total_weight_lbs` is the sum of `weight_lbs` over every piece of the job, whatever its status. `erected_weight_lbs` is the same sum restricted to pieces in `ERECTED`. `pct_complete` derives per §3.9 using the job's `billing_basis`. `billed_to_date_cents` sums `net_due_cents` over the job's billings in `APPROVED` or `PAID`. `retainage_held_cents` sums `retainage_booked_cents` over that same set. `pending_backcharge_cents` sums `amount_cents` over the job's backcharges in `PENDING`, `ACCEPTED`, or `DISPUTED`. `settled_backcharge_cents` sums `settled_amount_cents` over backcharges in `SETTLED`. Finally, `retainage_releasable_cents` sits at zero through the job's whole life until the moment it auto-completes, when it is set equal to the then-current `retainage_held_cents` — the amount the fabricator may now bill for release.

### 3.2. Shop Drawings: Submission, Decision, and the Revision Chain

A drawing begins when a `DETAILER` creates it against a `job_id` with a `drawing_number`. The first revision is numbered 1 and opens in `DRAFT`. The triple of `job_id`, `drawing_number`, and `revision` must be unique; a collision is rejected with `ERR_DRAWING_NOT_UNIQUE`. Drawings can be listed with filters on `job_id`, `supersedes_id`, or `status`, which is how a reviewer walks a revision chain.

Submission moves a drawing from `DRAFT` to `SUBMITTED` and captures the caller as `submitted_by_user_id`. The decision belongs to the `EOR`, who supplies a `decision` of `APPROVE` or `REJECT`; either way the decider is recorded as `decided_by_user_id`, and either way the decider must not be the submitter — an `EOR` deciding a drawing whose `submitted_by_user_id` equals their own `X-User-ID` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. A `REJECT` decision lands the drawing in `REJECTED`, terminal.

An `APPROVE` decision lands the drawing in `APPROVED` and fires the supersede cascade. If the newly approved drawing's `supersedes_id` points at a revision still in `APPROVED`, that predecessor moves to `SUPERSEDED`. Every piece pinned to the superseded revision via `drawing_id` whose status is not `SHIPPED` or `ERECTED` has its `stale_revision` flag set to true — pieces already shipped or standing are grandfathered and stay clean. Any piece thus marked stale that was sitting on a shipping load is pulled off: its `load_id` is cleared to null, the load's `total_weight_lbs` is recomputed, and if that load was in `LOADING` and now holds no lines at all, it falls back to `STAGING`. A supersession is also the only route into `SUPERSEDED`: when a newer revision of the same `drawing_number` is approved, the older approved revision transitions automatically.

Revision itself is a `DETAILER` action taken against a source drawing in `APPROVED` or `REJECTED` — revising from any other state fails with `ERR_INVALID_STATE`. The request must carry the `expected_drawing_version` token of §2.7, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful revise creates a brand-new drawing row: its `revision` is the source's revision plus one, its `supersedes_id` is the source's `id`, and it opens in `DRAFT` ready for its own submit-decide cycle. The act of revising also increments the source drawing's `version` by one, which is exactly what makes a second client's stale `expected_drawing_version` detectable.

### 3.3. Mill Orders: Buying the Steel

Material enters the system as mill orders placed by a `FABRICATOR_ADMIN` against the advance bill of material. The create payload names the `job_id`, a `material_grade` of `A36`, `A572`, or `A992`, an `ordered_weight_lbs` that must be positive, a `unit_price_per_cwt_cents` mill price per hundredweight that must also be positive, and a `billing_mode` of `NOMINAL` or `ACTUAL` that selects the invoice variant. A mill order may not be placed against a job still in `ESTIMATING` — material buying starts only once the job is awarded — and such an attempt fails with `ERR_INVALID_STATE`. A placed order opens in `PLACED` with `received_weight_lbs` and `invoice_amount_cents` null until receive, and the order book can be listed with `job_id` or `status` filters.

Receiving is the scale-house event: the caller records the `received_weight_lbs` from the scale ticket, and the order moves from `PLACED` to `RECEIVED`, terminal. The scale weight must land within ten percent of the ordered weight in either direction — the absolute difference between `received_weight_lbs` and `ordered_weight_lbs` must not exceed one tenth of `ordered_weight_lbs`, with a delivery at exactly ten percent over or under accepted — or the receive is rejected with `ERR_WEIGHT_OUT_OF_TOLERANCE`.

A successful receive computes `invoice_amount_cents` by converting the billable weight to hundredweight and multiplying by `unit_price_per_cwt_cents`, rounding half up to whole cents. The two billing modes differ only in which weight is billed: a `NOMINAL` order bills the ordered weight regardless of what the scale read, while an `ACTUAL` order bills the received scale weight. The tolerance gate applies identically to both variants before either invoice figure is computed.

### 3.4. Erection Sequences and Piece-Mark Tracking

The field plan is a set of erection sequences created by a `FOREMAN` with a `job_id` and a `seq_number`; the sequence number must be unique within its job, with collisions rejected as `ERR_SEQUENCE_NUMBER_NOT_UNIQUE`. A sequence opens in `PLANNED`. Releasing one — the foreman's signal that the field is ready for that sequence's steel — moves it from `PLANNED` to `RELEASED` and requires the owning job to be in `FABRICATING` or `ERECTING`; releasing against a job in any other state fails with `ERR_JOB_NOT_FABRICATING`. Sequences can be listed with `job_id` or `status` filters. The third sequence state, `ERECTED`, is never set by a client: it arrives automatically per the erection cascade of §3.4's close.

Pieces are the atoms of the system, created by a `FOREMAN` with a `job_id`, a `piece_mark` that must be unique within the job (`ERR_PIECE_MARK_NOT_UNIQUE` on collision), a positive `weight_lbs`, and two pins: the `drawing_id` of the approved-or-pending revision the piece is detailed from, and the `sequence_id` of its erection sequence. Both pins must reference records belonging to the same job as the piece's `job_id`; a drawing or sequence from another job is rejected with `ERR_CROSS_JOB_REFERENCE`. A new piece opens in `DETAILED` with `stale_revision` false and `load_id` null, and its creation immediately recomputes the job's `total_weight_lbs`. The piece register can be listed with filters on `job_id`, `drawing_id`, `sequence_id`, `load_id`, or `status`.

Starting shop work moves a piece from `DETAILED` to `IN_SHOP`, and the same action serves the rework loop, moving a piece from `REWORK` back to `IN_SHOP` under the identical gate. Four conditions guard the start, evaluated in this order: the piece's `stale_revision` must be false (`ERR_PIECE_STALE_REVISION` — a piece detailed from a superseded revision must be re-pinned before it can be worked); the pinned drawing must be `APPROVED` (`ERR_DRAWING_NOT_APPROVED`); the piece's sequence must be `RELEASED` (`ERR_SEQUENCE_NOT_RELEASED`); and at least one mill order of the job must be `RECEIVED` (`ERR_MATERIAL_NOT_RECEIVED`). From `IN_SHOP` the piece's further progress is driven by inspections (§3.6) and shipping (§3.7) until it is standing.

The last step belongs to the field: erecting moves a piece from `SHIPPED` to `ERECTED` — from any other state the request fails with `ERR_INVALID_STATE` — and fires the three-hop erection cascade. First the job's `erected_weight_lbs` is recomputed. Second, if every piece of the piece's sequence now stands in `ERECTED`, the sequence itself moves from `RELEASED` to `ERECTED`. Third, the job's compound completion check of §3.9 runs.

### 3.5. Welders, Welds, and the Repair Loop

Before any arc is struck, a `FABRICATOR_ADMIN` registers each welder with a `full_name`, a `qual_process` of `SMAW`, `FCAW`, or `GMAW`, and a `qual_expires_on` ISO calendar date through which the qualification remains valid. A registered welder opens in `ACTIVE`. Suspension — also a `FABRICATOR_ADMIN` action — moves a welder from `ACTIVE` to `SUSPENDED`, and the API exposes no reinstatement path: `SUSPENDED` is effectively terminal as far as clients are concerned.

Welding itself is logged by a `WELDER`, and the identity rule is strict: the payload's `welder_id` must equal the caller's `X-User-ID`, or the request is rejected with `ERR_FORBIDDEN`. The weld names its `piece_id` — the piece must be in `IN_SHOP`, since shop welding happens before inspection and shipping, with any other state failing as `ERR_INVALID_STATE` — plus the `process` used, the `weld_date` (an ISO calendar date that must not be later than the current logical clock date, failing as `ERR_INVALID_REQUEST` (HTTP 400)), and a work window from `window_start` to `window_end`, both ISO 8601 datetimes, with the end strictly after the start or the request fails `ERR_INVALID_REQUEST`. A logged weld opens in `WELDED` with `repair_count` at zero, and the weld log can be listed with `piece_id`, `welder_id`, or `status` filters.

Qualification is checked at log time against the logical clock, and any failure is rejected with `ERR_WELDER_NOT_QUALIFIED`. A welder is qualified for a weld exactly when all of the following hold: the welder is `ACTIVE`; the weld's `process` equals the welder's `qual_process`; the current logical date is on or before `qual_expires_on`; and the welder's continuity in that process is intact — either the welder has no prior weld in that process at all, or the most recent such prior weld's `weld_date` is no earlier than 183 days before the current logical date. "Most recent" means the greatest `weld_date` among the welder's prior welds in that process, with ties broken by the greatest `created_at`. Note that continuity is measured per process and counts prior welds in any status — a rejected weld still demonstrates the welder was practicing the process.

Double-booking is checked at the same time. A new weld conflicts with an existing weld of the same welder whenever their windows genuinely overlap — unless the new window ends at or before the existing window's start, or begins at or after the existing window's end. The arithmetic is half-open: a weld starting at exactly the moment another ends is allowed, as is one ending exactly when another begins. Every prior weld of the welder participates in this check regardless of status; even a weld later rejected still occupied its time. A genuine overlap is rejected with `ERR_WELDER_DOUBLE_BOOKED`.

Inspections then drive the weld through its quality gates, as detailed in §3.6: a weld in `WELDED` moves to `VISUAL_PASSED` or `VISUAL_REJECTED` on its visual inspection, and a weld in `VISUAL_PASSED` moves to `NDT_PASSED` or `NDT_REJECTED` on its NDT inspection, with `NDT_PASSED` terminal.

A rejected weld is not scrap — it enters the repair loop. Repairing moves a weld from `VISUAL_REJECTED` or `NDT_REJECTED` back to `WELDED`, ready to be re-inspected from the visual stage onward. Two guards apply: the repair is rejected with `ERR_WELD_REPAIR_LIMIT` once the weld's `repair_count` has reached 2 (repairs at counts zero and one proceed), and only the welder who performed the weld may repair it — the caller's `X-User-ID` must equal the weld's `welder_id`, or the request fails `ERR_FORBIDDEN`. Each successful repair increments `repair_count` by one.

### 3.6. Inspections: Final Piece, Weld Quality, and the AISC Audit

A `QC_INSPECTOR` schedules an inspection with a `job_id` and a `kind` of `FINAL_PIECE`, `WELD_VISUAL`, `WELD_NDT`, or `AISC_AUDIT`. The kind dictates the target shape, enforced as `ERR_INSPECTION_TARGET_INVALID` when violated: a `FINAL_PIECE` inspection requires a `piece_id`; a `WELD_VISUAL` or `WELD_NDT` inspection requires a `weld_id`; an `AISC_AUDIT` inspection targets the job alone and carries neither. Every inspection opens in `SCHEDULED`, and the inspection register can be listed with filters on `job_id`, `piece_id`, `weld_id`, `kind`, or `status`.

Scheduling a `FINAL_PIECE` inspection is itself a shop milestone: it advances the piece from `IN_SHOP` to `AWAITING_INSPECTION`, so the piece must currently be `IN_SHOP` (any other state fails `ERR_INVALID_STATE`), and every weld logged against that piece must already stand in `NDT_PASSED` — if any weld of the piece is short of that mark the scheduling is rejected with `ERR_WELDS_INCOMPLETE`.

Submitting a result is the `QC_INSPECTOR`'s second act, carrying an `outcome` of `PASSED` or `FAILED` and recording the caller as `inspector_user_id`. The dependent transitions below apply when the dependent record stands in the stated from-state at submit time; when it does not — for instance, a second `WELD_NDT` inspection submitted after the weld has already advanced — the outcome is still recorded on the inspection and the dependent record is left unchanged rather than the submission being rejected. For weld inspections a segregation rule applies: the inspector's `X-User-ID` must not equal the weld's `welder_id` — no one inspects their own weld — with violations rejected as `ERR_SEGREGATION_OF_DUTIES`. The two outcomes then move the inspection's dependent record, per kind:

- A passed `FINAL_PIECE` inspection moves its piece from `AWAITING_INSPECTION` to `INSPECTED` and then, within the same request, immediately onward to `READY_TO_SHIP`.
- A failed `FINAL_PIECE` inspection moves its piece from `AWAITING_INSPECTION` to `REWORK`, from which the restart path of §3.4 returns it to `IN_SHOP`.
- A passed `WELD_VISUAL` inspection moves its weld from `WELDED` to `VISUAL_PASSED`; a failed one moves it from `WELDED` to `VISUAL_REJECTED`.
- A passed `WELD_NDT` inspection moves its weld from `VISUAL_PASSED` to `NDT_PASSED`; a failed one moves it from `VISUAL_PASSED` to `NDT_REJECTED`.

An `AISC_AUDIT` submission moves no piece or weld: the audit is a job-level attestation, and its only downstream effect is satisfying the shipping hold of §3.7 while it stands as `PASSED` and unvoided.

Voiding retracts a decided inspection, and what happens to the dependent record depends on the kind and the outcome being voided. Voiding a failed inspection — moving it from `FAILED` to `VOIDED` — is always allowed and reverts nothing: the piece stays in `REWORK`, the rejected weld stays rejected. Voiding a passed inspection reverts the dependent transition, but only while downstream progress has not consumed the result; once it has, the inspection is locked and the void is rejected with `ERR_INSPECTION_LOCKED`. The lock conditions, per kind: a passed `FINAL_PIECE` inspection is voidable only while its piece is `READY_TO_SHIP` with a null `load_id` — a piece already shipped or sitting on a load locks the inspection — and voiding reverts the piece from `READY_TO_SHIP` back to `AWAITING_INSPECTION`. A passed `WELD_VISUAL` inspection is voidable only while its weld is still `VISUAL_PASSED` — once an NDT result has been submitted on top of it, the visual result is locked — and voiding reverts the weld from `VISUAL_PASSED` back to `WELDED`. A passed `WELD_NDT` inspection is voidable only while its weld is `NDT_PASSED`, and voiding reverts the weld from `NDT_PASSED` back to `VISUAL_PASSED`. A passed `AISC_AUDIT` drives no dependent state and may be voided freely; once voided it no longer counts toward the shipping hold.

### 3.7. Shipping Loads and the Laydown Yard

Outbound steel moves on shipping loads created by a `FOREMAN` with a `job_id`, a `load_number` unique within the job (`ERR_LOAD_NUMBER_NOT_UNIQUE`), a `laydown_slot` yard code, a `delivery_date` ISO calendar date, and a positive `trailer_capacity_lbs`. A new load opens in `STAGING` with `total_weight_lbs` at zero. The yard is shared across every job the shop serves, so the laydown slot is checked globally: creating a load conflicts when another load of any job holds the same `laydown_slot` in `STAGING` or `LOADING` status with a `delivery_date` at most two days away in either direction. The buffer is closed at two days — delivery dates exactly two days apart conflict and the create is rejected with `ERR_LAYDOWN_SLOT_CONFLICT`, while dates three or more days apart coexist freely. A load that has shipped frees its slot: `SHIPPED` loads never participate in the check. Loads can be listed with `job_id` or `status` filters.

Lines are added and removed while the load is `STAGING` or `LOADING`; against a `SHIPPED` load either edit fails with `ERR_INVALID_STATE`. Adding a line names a `piece_id`; the piece must be in `READY_TO_SHIP` status and not already sitting on a load — adding a piece whose `load_id` is already set fails with `ERR_INVALID_STATE`. The capacity gate weighs the candidate against the trailer: the load's current `total_weight_lbs` plus the candidate's `weight_lbs` must not exceed `trailer_capacity_lbs`, with a total landing exactly on capacity accepted and a single pound over rejected with `ERR_LOAD_OVERWEIGHT`. A successful add sets the piece's `load_id` to the load, recomputes `total_weight_lbs` as the sum of `weight_lbs` over every piece whose `load_id` points at the load, and — when it is the load's first line — moves the load from `STAGING` to `LOADING`. Removing a line clears the piece's `load_id` to null, recomputes the total, and — when it was the last line — drops the load from `LOADING` back to `STAGING` with a recomputed total of zero. Both line edits return the updated load object in the response's `data` field. The load's current lines can be listed at any time. Recall from §3.2 that the drawing-supersede cascade performs these same removals automatically when a piece on a load goes stale.

Shipping is the `FOREMAN`'s departure call, moving a load from `LOADING` to `SHIPPED`. Three gates guard it. The load must hold at least one line, and every piece on it must be `READY_TO_SHIP` with `stale_revision` false — an empty load, an unready piece, or a stale piece each fail with `ERR_PIECES_NOT_READY`. And when the job's `requires_aisc_hold` flag is true, a `PASSED`, non-`VOIDED` `AISC_AUDIT` inspection must exist for the job at ship time; without one the ship is rejected with `ERR_AISC_HOLD_ACTIVE`. A successful ship moves every piece on the load from `READY_TO_SHIP` to `SHIPPED`, after which the field can erect them per §3.4.

### 3.8. Field Fixes and Backcharges

Erection sometimes reveals damage or misfabrication that must be corrected in the field. A `FOREMAN` reports a field fix with a `job_id`, the `piece_id` in question — the piece must be `SHIPPED` or `ERECTED`, since a fix is by definition discovered after the steel has left the shop, and any other status fails `ERR_INVALID_STATE` — a free-text `description`, and a non-empty `repair_lines` array. Each repair line carries `labor_hours` as a number, `labor_rate_cents` as an integer, and `material_cents` as an integer; an empty array fails `ERR_INVALID_REQUEST`. A reported fix opens in `PRICED` with `amount_cents` null until approval prices it, and fixes can be listed with `job_id`, `piece_id`, or `status` filters.

Approval belongs to the `GC_PM`, and approving is what prices the fix. The amount is computed in a pinned rounding order. For each repair line, the labor component is the line's `labor_hours` multiplied by its `labor_rate_cents`, rounded half up to whole cents; the line total is that rounded labor component plus the line's `material_cents`. The subtotal is the plain sum of all line totals. The markup is fifteen percent of the subtotal, rounded half up to whole cents. The fix's `amount_cents` is the subtotal plus the markup. Rounding labor only once after summing across lines — or computing the markup on unrounded labor — produces different cents and is not permitted.

The same approval creates the money claim: a backcharge springs into existence in `PENDING` status with its `amount_cents` copied from the fix's freshly computed `amount_cents`, its `field_fix_id` pointing at the fix, and its `job_id` copied from the fix's job; the job's `pending_backcharge_cents` is recomputed to include it. The fix itself moves from `PRICED` to `APPROVED`. Backcharges can be listed with `job_id`, `field_fix_id`, or `status` filters.

The general contractor then answers the claim: responding with a `response` of `ACCEPT` moves the backcharge from `PENDING` to `ACCEPTED`, while a `response` of `DISPUTE` moves it from `PENDING` to `DISPUTED`. Settlement is the fabricator's act — a `FABRICATOR_ADMIN` records the negotiated `settled_amount_cents`, which must be a non-negative integer or the request fails `ERR_INVALID_REQUEST` (HTTP 400), moving the backcharge from `ACCEPTED` or `DISPUTED` to `SETTLED`. The fiscal cap guards settlement: the job's current `settled_backcharge_cents` plus the new `settled_amount_cents` must not exceed the job's `billed_to_date_cents` — the shop cannot settle backcharges out of money it has not yet billed — with violations rejected as `ERR_BACKCHARGE_EXCEEDS_EARNED`. A successful settle moves the money between the job's aggregates: `pending_backcharge_cents` drops by the backcharge's `amount_cents` and `settled_backcharge_cents` rises by `settled_amount_cents`; then the job's compound completion check of §3.9 runs.

A fix is closed by resolving it, a `FOREMAN` action moving it from `APPROVED` to `RESOLVED` — but only once the linked backcharge stands in `SETTLED`; resolving while the claim is still open fails with `ERR_BACKCHARGE_OPEN`.

### 3.9. Progress Billing, Retainage, and Closing the Job

Billing starts with percent complete, and the job's `billing_basis` picks the variant. For a `WEIGHT` job, percent complete is the job's `erected_weight_lbs` divided by its `total_weight_lbs` — every piece counts toward the denominator whatever its status, while only `ERECTED` pieces count toward the numerator. For a `COUNT` job, percent complete is the number of the job's pieces in `ERECTED` divided by the total number of its pieces, weighting every piece equally regardless of size. A job with no pieces at all reports 0.0000. The figure is carried to exactly four decimal places with half-up rounding.

A `FABRICATOR_ADMIN` creates a progress billing with a `job_id`, a `period_label`, and the `expected_job_version` concurrency token of §2.7 — a mismatch with the job's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), and the act of creating a billing itself increments the job's `version` by one. Two gates apply: the job must be `FABRICATING`, `ERECTING`, or `COMPLETE` — billing against an `ESTIMATING` or `AWARDED` job fails with `ERR_JOB_NOT_BILLABLE` — and the `period_label` must be unique within the job among billings not in `VOIDED`, with duplicates rejected as `ERR_DUPLICATE_BILLING_PERIOD`. A new billing opens in `DRAFT`.

Creation freezes a snapshot computed in a pinned evaluation order. First the job's percent complete is taken and stored as `pct_complete_snapshot` at four decimal places. Second, `earned_cum_cents` is the job's `contract_value_cents` multiplied by that percentage, rounded half up to whole cents. Third, the retainage rate is selected on the whole amount: five percent when the percent complete is at least one half (0.5000), ten percent when it is below — the selected rate applies to the entire cumulative earned figure, not marginally to a bracket. Fourth, `retainage_cum_cents` is `earned_cum_cents` multiplied by that rate, rounded half up to whole cents. Fifth, prior billings are summed — only billings in `APPROVED` or `PAID` count; `DRAFT`, `SUBMITTED`, and `VOIDED` billings are excluded — yielding the previously billed net (the sum of their `net_due_cents`) and the previously booked retainage (the sum of their `retainage_cum_cents`). Finally, `net_due_cents` is `earned_cum_cents` minus `retainage_cum_cents` minus the job's `settled_backcharge_cents` minus the previously billed net, and `retainage_booked_cents` is `retainage_cum_cents` minus the previously booked retainage. Billings can be listed with `job_id` or `status` filters.

From `DRAFT`, the fabricator submits — recording `submitted_by_user_id` and moving the billing to `SUBMITTED`. The `GC_PM` then approves, moving it from `SUBMITTED` to `APPROVED` and booking the money onto the job: `billed_to_date_cents` rises by `net_due_cents`, `retainage_held_cents` rises by `retainage_booked_cents`, and the job's `version` increments. Payment moves an `APPROVED` billing to `PAID` and triggers the compound completion check. Voiding — also from `APPROVED` alone — moves the billing to `VOIDED` and exactly reverses the booking: `billed_to_date_cents` falls by the billing's `net_due_cents`, `retainage_held_cents` falls by its `retainage_booked_cents`, the job's `version` increments, and the compound completion check runs. Both `PAID` and `VOIDED` are terminal.

That compound check is how a job closes. It is re-evaluated automatically after every piece erection, every automatic sequence completion, every billing payment, every billing void, and every backcharge settlement, and it passes exactly when all of the following hold: the job is `ERECTING`; at least one erection sequence exists for the job and every sequence is `ERECTED`; at least one progress billing exists for the job and every billing is `PAID` or `VOIDED`; and every backcharge of the job is `SETTLED` — a condition vacuously satisfied when the job has no backcharges. When the check passes, the job moves to `COMPLETE`, terminal: its `retainage_releasable_cents` is set to the `retainage_held_cents` current at that moment, and its `version` increments.

## 4. Endpoint Definitions

Operations that create new resources — a job, drawing, revision, mill order, sequence, piece, welder, weld, inspection, shipping load, load line, field fix, or progress billing — return a `201 Created` status code. Operations that modify an existing resource, including every state transition, decision, receive, ship, respond, settle, pay, void, and the clock set, return a `200 OK` status code. The table below is a summary only; request payloads, response bodies, and side effects are defined by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint); before any call the clock reads exactly 2026-08-01T00:00:00Z | FABRICATOR_ADMIN |
| POST | `/jobs` | Create a job in `ESTIMATING` with zeroed aggregates | FABRICATOR_ADMIN |
| GET | `/jobs` | List jobs with optional `status` filter | All roles |
| GET | `/jobs/{id}` | Read a job with its computed aggregates | All roles |
| POST | `/jobs/{id}/award` | Award a job (`ESTIMATING` to `AWARDED`) | FABRICATOR_ADMIN |
| POST | `/jobs/{id}/start-fabrication` | Start fabrication (`AWARDED` to `FABRICATING`); requires at least one approved drawing | FABRICATOR_ADMIN |
| POST | `/jobs/{id}/start-erection` | Start erection (`FABRICATING` to `ERECTING`); requires at least one released sequence | FABRICATOR_ADMIN |
| POST | `/shop-drawings` | Create revision 1 of a drawing in `DRAFT` | DETAILER |
| GET | `/shop-drawings` | List drawings with `job_id`, `supersedes_id`, and `status` filters | All roles |
| GET | `/shop-drawings/{id}` | Read a shop drawing | All roles |
| POST | `/shop-drawings/{id}/submit` | Submit a draft for engineer review (`DRAFT` to `SUBMITTED`) | DETAILER |
| POST | `/shop-drawings/{id}/decide` | Approve or reject a submitted drawing; approval fires the supersede and staleness cascade | EOR |
| POST | `/shop-drawings/{id}/revise` | Cut the next revision from an approved or rejected drawing; OCC-guarded on the source drawing version | DETAILER |
| POST | `/mill-orders` | Place a mill order against the advance bill of material; job must not be `ESTIMATING` | FABRICATOR_ADMIN |
| GET | `/mill-orders` | List mill orders with `job_id` and `status` filters | All roles |
| GET | `/mill-orders/{id}` | Read a mill order | All roles |
| POST | `/mill-orders/{id}/receive` | Receive a mill order with the scale weight; computes the invoice per billing mode | FABRICATOR_ADMIN |
| POST | `/erection-sequences` | Create an erection sequence in `PLANNED`; sequence number unique per job | FOREMAN |
| GET | `/erection-sequences` | List erection sequences with `job_id` and `status` filters | All roles |
| GET | `/erection-sequences/{id}` | Read an erection sequence | All roles |
| POST | `/erection-sequences/{id}/release` | Release a sequence (`PLANNED` to `RELEASED`); job must be fabricating or erecting | FOREMAN |
| POST | `/pieces` | Create a piece in `DETAILED` pinned to a drawing revision and sequence of the same job | FOREMAN |
| GET | `/pieces` | List pieces with `job_id`, `drawing_id`, `sequence_id`, `load_id`, and `status` filters | All roles |
| GET | `/pieces/{id}` | Read a piece | All roles |
| POST | `/pieces/{id}/start` | Start shop work (`DETAILED` or `REWORK` to `IN_SHOP`); gated on revision freshness, drawing approval, sequence release, material receipt | FOREMAN |
| POST | `/pieces/{id}/erect` | Erect a shipped piece (`SHIPPED` to `ERECTED`); fires the sequence and job completion cascade | FOREMAN |
| POST | `/welders` | Register a welder with qualification process and expiry (`ACTIVE`) | FABRICATOR_ADMIN |
| POST | `/welders/{id}/suspend` | Suspend a welder (`ACTIVE` to `SUSPENDED`); no reinstatement endpoint | FABRICATOR_ADMIN |
| POST | `/welds` | Log a weld on an `IN_SHOP` piece; own-welds identity, qualification, continuity, and window-overlap enforced | WELDER |
| GET | `/welds` | List welds with `piece_id`, `welder_id`, and `status` filters | All roles |
| GET | `/welds/{id}` | Read a weld | All roles |
| POST | `/welds/{id}/repair` | Repair a rejected weld back to `WELDED`; repair limit two, own welds only | WELDER |
| POST | `/inspections` | Schedule an inspection; target shape depends on kind; final-piece scheduling advances the piece | QC_INSPECTOR |
| GET | `/inspections` | List inspections with `job_id`, `piece_id`, `weld_id`, `kind`, and `status` filters | All roles |
| GET | `/inspections/{id}` | Read an inspection | All roles |
| POST | `/inspections/{id}/submit` | Submit an inspection outcome; weld-inspector segregation enforced; dependent transitions fire per kind | QC_INSPECTOR |
| POST | `/inspections/{id}/void` | Void a passed or failed inspection with dependent reversion; locked once downstream progress consumed the result | QC_INSPECTOR |
| POST | `/shipping-loads` | Create a load in `STAGING`; buffered laydown-slot conflict enforced across all jobs | FOREMAN |
| GET | `/shipping-loads` | List shipping loads with `job_id` and `status` filters | All roles |
| GET | `/shipping-loads/{id}` | Read a shipping load | All roles |
| GET | `/shipping-loads/{id}/lines` | List the pieces currently on a load | All roles |
| POST | `/shipping-loads/{id}/lines` | Add a `READY_TO_SHIP` piece to the load; trailer capacity gate; first line flips to `LOADING` | FOREMAN |
| DELETE | `/shipping-loads/{id}/lines/{piece_id}` | Remove a piece from the load; last line flips back to `STAGING` | FOREMAN |
| POST | `/shipping-loads/{id}/ship` | Ship the load (`LOADING` to `SHIPPED`); readiness and AISC hold enforced; all line pieces ship | FOREMAN |
| POST | `/field-fixes` | Report a field fix on a shipped or erected piece with priced repair lines | FOREMAN |
| GET | `/field-fixes` | List field fixes with `job_id`, `piece_id`, and `status` filters | All roles |
| GET | `/field-fixes/{id}` | Read a field fix | All roles |
| POST | `/field-fixes/{id}/approve` | Approve a fix (`PRICED` to `APPROVED`); computes the amount and creates the pending backcharge | GC_PM |
| POST | `/field-fixes/{id}/resolve` | Resolve a fix (`APPROVED` to `RESOLVED`); requires the linked backcharge settled | FOREMAN |
| GET | `/backcharges` | List backcharges with `job_id`, `field_fix_id`, and `status` filters | All roles |
| GET | `/backcharges/{id}` | Read a backcharge | All roles |
| POST | `/backcharges/{id}/respond` | Accept or dispute a pending backcharge | GC_PM |
| POST | `/backcharges/{id}/settle` | Settle an accepted or disputed backcharge; fiscal cap against billed-to-date enforced | FABRICATOR_ADMIN |
| POST | `/progress-billings` | Create a draft billing snapshotting job aggregates; OCC-guarded on the job version; period unique per job among non-voided | FABRICATOR_ADMIN |
| GET | `/progress-billings` | List progress billings with `job_id` and `status` filters | All roles |
| GET | `/progress-billings/{id}` | Read a progress billing | All roles |
| POST | `/progress-billings/{id}/submit` | Submit a draft billing (`DRAFT` to `SUBMITTED`) | FABRICATOR_ADMIN |
| POST | `/progress-billings/{id}/approve` | Approve a billing (`SUBMITTED` to `APPROVED`); books net due and retainage onto the job | GC_PM |
| POST | `/progress-billings/{id}/pay` | Pay an approved billing (`APPROVED` to `PAID`); runs the job completion check | GC_PM |
| POST | `/progress-billings/{id}/void` | Void an approved billing (`APPROVED` to `VOIDED`); exactly reverses the booked amounts | GC_PM |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_WELDER_NOT_QUALIFIED` | 409 |
| `ERR_WELDER_DOUBLE_BOOKED` | 409 |
| `ERR_WELD_REPAIR_LIMIT` | 409 |
| `ERR_WELDS_INCOMPLETE` | 409 |
| `ERR_INSPECTION_TARGET_INVALID` | 409 |
| `ERR_INSPECTION_LOCKED` | 409 |
| `ERR_DRAWING_NOT_APPROVED` | 409 |
| `ERR_PIECE_STALE_REVISION` | 409 |
| `ERR_SEQUENCE_NOT_RELEASED` | 409 |
| `ERR_MATERIAL_NOT_RECEIVED` | 409 |
| `ERR_PIECE_MARK_NOT_UNIQUE` | 409 |
| `ERR_DRAWING_NOT_UNIQUE` | 409 |
| `ERR_SEQUENCE_NUMBER_NOT_UNIQUE` | 409 |
| `ERR_LOAD_NUMBER_NOT_UNIQUE` | 409 |
| `ERR_CROSS_JOB_REFERENCE` | 409 |
| `ERR_LOAD_OVERWEIGHT` | 409 |
| `ERR_PIECES_NOT_READY` | 409 |
| `ERR_LAYDOWN_SLOT_CONFLICT` | 409 |
| `ERR_JOB_NOT_FABRICATING` | 409 |
| `ERR_JOB_NOT_BILLABLE` | 409 |
| `ERR_DUPLICATE_BILLING_PERIOD` | 409 |
| `ERR_BACKCHARGE_EXCEEDS_EARNED` | 409 |
| `ERR_BACKCHARGE_OPEN` | 409 |
| `ERR_WEIGHT_OUT_OF_TOLERANCE` | 409 |
| `ERR_AISC_HOLD_ACTIVE` | 409 |

# Lymphedema & Specialty Rehab API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Lymphedema & Specialty Rehabilitation Clinic API. The system supports a specialty outpatient clinic that treats lymphedema and related conditions through Complete Decongestive Therapy (CDT). It coordinates the full arc of care: an initial clinical evaluation with limb staging and circumferential measurement; insurance authorization against a finite visit cap; a CDT treatment plan and the individual therapy sessions delivered under it; compression-garment ordering with HCPCS L-code classification and downstream durable-medical-equipment (DME) dispensing; a home-program adherence record; and periodic reassessment that measures outcomes and may graduate a patient into a maintenance phase.

Two accounting problems sit at the center of the domain. The first is a **quota** problem: every payer authorization grants a fixed number of CDT visits, and the clinic must reserve, consume, and release visits against that cap without ever overcommitting it — exhausting the pool must ripple outward to pause the plans that depend on it. The second is a **ledger reconciliation** problem: limb volume, excess volume, garment stock on hand, and adherence percentages are all derived quantities that must be recomputed deterministically from their underlying records rather than stored as free-standing values. The requirements below describe the entities, the state machines that govern them, the calculations that reconcile the derived fields, and the validation and access-control rules that keep the whole system consistent.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, conventions, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a role string outside the recognized set, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Clinician`, `Authorizer`, `DMECoordinator`, and `ClinicAdmin`.

- A `Clinician` is a certified lymphedema therapist who owns clinical documentation: evaluations, treatment plans, sessions and their lifecycle, garment-order creation, reassessments, and adherence logs. When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Therapist`; any ownership check on a resource that references a `Therapist` compares that resource's therapist foreign key to `X-User-ID`.
- An `Authorizer` is a payer / utilization-management actor who owns insurance authorizations and payer decisions on garment orders. When `X-User-Role` is `Authorizer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- A `DMECoordinator` owns DME inventory and dispensing. When `X-User-Role` is `DMECoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- A `ClinicAdmin` is a clinic administrator who registers patients and therapists, sets up DME items, drives the logical clock, and co-owns authorization creation and DME-item creation. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

Read operations (listing and fetching resources) are broadly shared, but each collection restricts reads to the roles that have a business interest in it; the authorized roles for every endpoint are enumerated in §4. Authentication is always evaluated before authorization.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and its accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 on creation and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in §2.6.

`AdherenceLog` is the sole exception: it is an append-only, immutable record and therefore carries only `id` and `created_at`. It has no `updated_at` and no `version`, and it is never modified after creation. All other entities — `Patient`, `Evaluation`, `Authorization`, `TreatmentPlan`, `Therapist`, `Session`, `GarmentOrder`, `DMEItem`, `Dispense`, and `Reassessment` — carry the full four-field set.

When a resource is mutated, whether directly by a client action or indirectly as a downstream cascade effect, its `updated_at` is refreshed and its `version` is incremented. This applies to derived-field recomputations as well: for example, when a session cascade changes an authorization's visit counters, that authorization's `updated_at` and `version` advance even though no field was supplied by a client on that resource.

### 2.5. Existence Resolution and Validation Ordering

Although resource URLs are flat (a resource is addressed directly by its own `id`, never nested under a parent path), most write operations still reference other resources by foreign-key identifiers carried in the request body. The system validates a request through a fixed priority ladder, and the **first** failing check determines the error returned:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and valid, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role must be permitted for the operation, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — the path `id` and every foreign-key `id` in the body must resolve to an existing resource, checked left-to-right in the order they appear (path identifier first, then body references in listed order). The first unresolved identifier yields its specific not-found error: `ERR_PATIENT_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_THERAPIST_NOT_FOUND`, `ERR_GARMENT_ORDER_NOT_FOUND`, `ERR_DME_ITEM_NOT_FOUND`, `ERR_DISPENSE_NOT_FOUND`, or `ERR_REASSESSMENT_NOT_FOUND` (all 404).
4. **Well-formedness** — the body must be structurally valid: required fields present, numbers within range, and `scheduled_end` strictly after `scheduled_start`. A missing/malformed/out-of-range field yields `ERR_VALIDATION` (422); an enum field carrying a value outside its declared set yields `ERR_INVALID_ENUM` (422).
5. **Optimistic concurrency** — where applicable (see §2.6), `expected_patient_version` must equal the patient's current `version`, else `ERR_STALE_PATIENT_VERSION` (412).
6. **State** — the target resource, and any cross-entity guard, must be in a state that permits the operation, else the appropriate 409 (`ERR_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_AUTH_NOT_APPROVED`, `ERR_EVALUATION_NOT_FINALIZED`, `ERR_GARMENT_ORDER_NOT_APPROVED`, or `ERR_OPEN_SESSIONS_EXIST`).
7. **Referential consistency** — cross-reference rules such as a session's authorization matching its plan's authorization, an evaluation belonging to the named patient, or a dispensed item's L-code matching the order's L-code, else `ERR_AUTH_PLAN_MISMATCH`, `ERR_EVALUATION_PATIENT_MISMATCH`, or `ERR_DME_LCODE_MISMATCH` (all 409).
8. **Temporal windows** — session-within-authorization-window, therapist double-booking, and authorization-window overlap, yielding `ERR_SESSION_OUTSIDE_AUTH_WINDOW`, `ERR_THERAPIST_DOUBLE_BOOKED`, or `ERR_AUTH_WINDOW_OVERLAP` (all 409).
9. **Measurement and stock sufficiency** — at least two circumference points and equal-length arrays on evaluation create (`ERR_INSUFFICIENT_MEASUREMENT`, `ERR_MEASUREMENT_LENGTH_MISMATCH`, both 422); dispense quantity within stock on hand (`ERR_DME_INSUFFICIENT_STOCK`, 409).
10. **Visit-cap fiscal check** — a new session may only reserve a visit if the cap is not already fully committed, else `ERR_VISIT_CAP_EXCEEDED` (409).

This ordering is normative: when more than one condition is violated, the lower-numbered category wins. Not every operation exercises every rung — each rung applies only to the endpoints where it is meaningful — but where multiple rungs apply to the same request, they are evaluated in this sequence.

### 2.6. Optimistic Concurrency on the Patient Record

Two write operations mutate a patient indirectly by superseding a prior record for the same patient and body region, and both are guarded by optimistic concurrency keyed on `Patient.version`. Creating an evaluation and creating a garment order each require a non-optional `expected_patient_version` field carrying the patient `version` the client last observed. If that value does not equal the patient's current `version`, the create is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412), and no evaluation or order is created and no supersession occurs.

The guard exists because both creates advance `Patient.version` by one as a side effect: each new evaluation supersedes the prior FINALIZED evaluation for the patient and body region, and each new garment order supersedes the prior DRAFT or APPROVED order for the patient and body region. If another writer has already created a superseding record, the current client's view of the patient is stale, and its `expected_patient_version` will no longer match — the mismatch prevents it from overwriting a record it never observed. No other endpoint takes a version field; operations outside evaluation-create and garment-order-create perform no optimistic-concurrency check.

### 2.7. Measurement Precision and Rounding

All rounding in the system uses the **round-half-up** convention (a value exactly halfway between two representable results rounds away from zero, i.e., upward for the non-negative quantities used here).

Limb-volume computation has a **pinned rounding order** that must not be reinterpreted: each truncated-cone segment volume is rounded to two decimal places *first*, the rounded segments are then summed, and only that sum is rounded — to one decimal place — to produce the reported volume. Summing the raw (unrounded) segments and rounding once at the end is not equivalent and is not permitted; the two approaches can differ by 0.1 ml.

Derived percentages — `volume_reduction_pct`, `perv_pct`, and `adherence_rate` — are each rounded half-up to one decimal place. Excess volume is rounded to one decimal place. Visit counters and stock quantities are exact integers. The mathematical constant π is taken as 3.141592653589793.

### 2.8. The Visit Ledger and Cascade Consistency

Each authorization maintains a visit ledger derived entirely from the sessions that reference it, never stored as an independent tally. `visits_reserved` is the count of sessions on the authorization whose `clinical_status` is `SCHEDULED` or `CHECKED_IN`. `visits_used` is the count of sessions whose `clinical_status` is `COMPLETED` or `NO_SHOW`. `visits_remaining` is the authorization's `visit_cap` minus `visits_reserved` minus `visits_used`. These three counters are recomputed whenever a session that references the authorization is created or changes clinical status, and each such recomputation refreshes the authorization's `updated_at` and increments its `version`.

Session completion and no-show can trigger a cascade up to three links deep. The session itself is the first mutation; the second is the debit against the authorization's ledger; the third, conditional link exhausts the authorization once the cap is fully consumed; and the fourth-order effect places dependent plans on hold. §3 describes each link at the point in the workflow where it fires. The governing rule for all of these is that derived state is reconciled immediately and consistently — a client never has to poll for or trigger the propagation itself.

## 3. Business Logic & Workflows

### 3.1. Foundational Records: Patients, Therapists, and DME Inventory

Before clinical work begins, several reference records must exist. A `ClinicAdmin` registers a patient by supplying a `full_name`, a clinic-unique `mrn` (medical record number), and an optional `date_of_birth` as an ISO date. A newly registered patient starts in `status` `ACTIVE` and remains `ACTIVE` throughout this system's scope; patients are never advanced out of that status here. Reads on patients are available to every role.

A `ClinicAdmin` also registers therapists, each defined by a `full_name` and a `credential` drawn from `CLT` (certified lymphedema therapist), `OT`, or `PT`. A therapist is created `ACTIVE` and stays so. Because a `Clinician`'s `X-User-ID` is the `id` of a therapist record, the therapist roster is what ties an authenticated clinician to the sessions and documentation they own.

DME inventory is set up by a `DMECoordinator` or a `ClinicAdmin`. Each `DMEItem` carries a clinic-unique `sku`, an optional `description`, the HCPCS `l_code` the SKU fulfills (for example, L8100), and an `initial_stock_qty` of physical units received into inventory (zero or greater). `initial_stock_qty` is the conserved base quantity that never changes after creation. Two derived counters accompany it: `outstanding_dispensed_qty`, which starts at 0, is the sum of `quantity` across all dispenses of this item currently in `DISPENSED` status; and `on_hand_qty`, which is `initial_stock_qty` minus `outstanding_dispensed_qty`. The invariant `on_hand_qty` plus `outstanding_dispensed_qty` equals `initial_stock_qty` holds at all times.

### 3.2. Clinical Evaluation: Staging and Circumferential Measurement

A `Clinician` opens the clinical record by creating an evaluation for a patient. The create payload names the `patient_id`, the affected `body_region` (one of `LEFT_ARM`, `RIGHT_ARM`, `LEFT_LEG`, `RIGHT_LEG`, `HEAD_NECK`, `TRUNK`, or `GENITAL`), the `etiology` (`PRIMARY` or `SECONDARY`), the ISL clinical stage `isl_stage` (`STAGE_0`, `STAGE_I`, `STAGE_II`, or `STAGE_III`), the `interval_cm` spacing between adjacent measurement points, and two ordered arrays: `circumferences_cm`, the circumferences of the affected limb from proximal to distal, and `contralateral_circumferences_cm`, the circumferences of the unaffected opposite limb. The payload also carries `expected_patient_version` for the concurrency guard described in §2.6.

Measurement sufficiency is enforced at create time: at least two circumference points are required, and fewer than two is rejected with `ERR_INSUFFICIENT_MEASUREMENT`. The affected and contralateral arrays must be exactly the same length; a length difference is rejected with `ERR_MEASUREMENT_LENGTH_MISMATCH`.

At creation the system computes the affected limb's `limb_volume_ml` as a truncated-cone (frustum) summation over the measurement segments. For each adjacent pair of circumferences taken in listed order — the point at index *i* and the next point at index *i*+1 — the segment volume in milliliters equals the `interval_cm` spacing multiplied by the sum of the first circumference squared, the product of the two circumferences, and the second circumference squared, all divided by twelve times π. Following the pinned rounding order of §2.7, each segment volume is rounded to two decimal places first; the rounded segments are then summed; and that sum is rounded to one decimal place to yield `limb_volume_ml`. The identical procedure over `contralateral_circumferences_cm` yields `contralateral_volume_ml`. The `excess_volume_ml` is the affected volume minus the contralateral volume, floored at zero (never negative), rounded to one decimal place.

A new evaluation is created in `DRAFT`. A `Clinician` finalizes it, which requires the evaluation to be in `DRAFT` and otherwise returns `ERR_INVALID_STATE`; finalization moves the evaluation to `FINALIZED` and freezes `limb_volume_ml`, `contralateral_volume_ml`, and `excess_volume_ml` as the definitive measurement. Because a fresh evaluation for the same `patient_id` and `body_region` represents a newer clinical picture, creating one causes any prior `FINALIZED` evaluation for that same patient and region to transition from `FINALIZED` to `SUPERSEDED`, advancing that prior record's `updated_at` and `version`. Every successful evaluation create also increments the patient's `version` by one. An evaluation's status therefore moves `DRAFT` → `FINALIZED` → `SUPERSEDED`, with `SUPERSEDED` terminal.

### 3.3. Insurance Authorization and the Visit Pool

Insurance coverage for CDT is represented by an authorization, created by an `Authorizer` or a `ClinicAdmin`. The create payload carries the `patient_id`, the `body_region` the authorization covers (same region enum as an evaluation), the `payer_name`, the payer's `auth_number`, the `visit_cap` (a non-negative integer maximum number of authorized visits), and an inclusive effective window bounded by `effective_start_date` and `effective_end_date`. On creation the authorization is `DRAFT`, `visits_reserved` and `visits_used` are 0, and `visits_remaining` equals `visit_cap`. A new authorization is rejected with `ERR_AUTH_WINDOW_OVERLAP` if its window overlaps that of any existing authorization for the same `patient_id` and `body_region` whose status is `DRAFT`, `SUBMITTED`, `APPROVED`, or `EXHAUSTED`; the windows are treated as closed intervals, so windows that merely touch at an endpoint are considered overlapping.

The authorization moves through a cyclic lifecycle driven by the `Authorizer`. Submitting a `DRAFT` authorization advances it `DRAFT` → `SUBMITTED`; the same submit action re-submits a denied authorization, advancing it `DENIED` → `SUBMITTED`. From `SUBMITTED`, an approve advances it to `APPROVED`, while a deny advances it to `DENIED`; a denied authorization can be resubmitted, forming the resubmission loop. Each of these transitions requires the authorization to be in the expected source state and otherwise returns `ERR_INVALID_STATE`.

An authorization becomes exhausted automatically, not by client request: when a session completion or no-show debit drives `visits_used` to be greater than or equal to `visit_cap`, the authorization transitions `APPROVED` → `EXHAUSTED`. An `Authorizer` reopens an exhausted pool by renewing it, supplying `additional_visits` in the payload; renewal requires the authorization to be `EXHAUSTED` (otherwise `ERR_INVALID_STATE`), moves it `EXHAUSTED` → `APPROVED`, adds `additional_visits` to `visit_cap`, and recomputes `visits_remaining`. Renewal also resumes work, as described in §3.4.

### 3.4. The CDT Treatment Plan Lifecycle

With a finalized evaluation and a governing authorization in place, a `Clinician` creates a CDT treatment plan. The create payload names the `patient_id`, the `evaluation_id`, the `authorization_id`, and the `prescribed_daily_minutes` of home-program work (bandaging and exercise) used later for adherence scoring. The referenced evaluation must be `FINALIZED` — a still-`DRAFT` evaluation is rejected with `ERR_EVALUATION_NOT_FINALIZED` — and must belong to the named patient, else `ERR_EVALUATION_PATIENT_MISMATCH`. A new plan starts in `DRAFT`, in `phase` `PHASE_1_INTENSIVE`, with `adherence_rate` at 0.

Activation is a `Clinician` action that requires the plan to be in `DRAFT` (otherwise `ERR_INVALID_STATE`) and the referenced authorization to be `APPROVED` (otherwise `ERR_AUTH_NOT_APPROVED`); it advances the plan `DRAFT` → `ACTIVE`. An active plan is subject to the automatic hold-and-resume cycle tied to its authorization: when the governing authorization becomes `EXHAUSTED`, every `ACTIVE` plan on that authorization transitions `ACTIVE` → `ON_HOLD`; when that authorization is later renewed back to `APPROVED`, every `ON_HOLD` plan on it transitions `ON_HOLD` → `ACTIVE`. These hold and resume transitions are system-driven side effects of the authorization's own exhaustion and renewal, never direct client requests on the plan.

Completing a plan is a `Clinician` action requiring the plan to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and requiring that no session on the plan is still in `clinical_status` `SCHEDULED` or `CHECKED_IN`; an attempt to complete with open sessions is rejected with `ERR_OPEN_SESSIONS_EXIST`. A successful completion advances the plan `ACTIVE` → `COMPLETED`, which is terminal. The plan's overall status path is `DRAFT` → `ACTIVE` → `ON_HOLD` → `ACTIVE` (the hold/resume loop) → `COMPLETED`.

### 3.5. Scheduling and Conducting Sessions

Individual CDT visits are represented by sessions, each created by a `Clinician`. The create payload names the `plan_id`, the `authorization_id`, the `therapist_id`, the `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants, with the end required to be strictly after the start, else `ERR_VALIDATION`), and the `cdt_component` delivered (`MLD`, `COMPRESSION_BANDAGING`, `EXERCISE`, `SKIN_CARE`, or `EDUCATION`). Several guards apply before a session may be booked. The plan must be `ACTIVE`, otherwise `ERR_PLAN_NOT_ACTIVE`. The governing authorization must be `APPROVED`, otherwise `ERR_AUTH_NOT_APPROVED`. The session's `authorization_id` must equal the plan's own `authorization_id`, otherwise `ERR_AUTH_PLAN_MISMATCH`.

Two temporal guards then apply. The session's `[scheduled_start, scheduled_end]` interval must fall entirely within the authorization's `[effective_start_date, effective_end_date]` window, otherwise `ERR_SESSION_OUTSIDE_AUTH_WINDOW`. The assigned therapist must not be double-booked: the create is rejected with `ERR_THERAPIST_DOUBLE_BOOKED` if any existing session for the same `therapist_id` whose `clinical_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED` sits within a fifteen-minute buffer of the new interval — that is, treating each interval as half-open on the end and expanding by the buffer, the two must not come within fifteen minutes of touching.

Finally, the fiscal quota check: a new session may reserve a visit only when the sum of `visits_reserved` and `visits_used` on the authorization is strictly less than `visit_cap`. If reserving would reach or exceed the cap, the create is rejected with `ERR_VISIT_CAP_EXCEEDED`. When the session is created it starts with `clinical_status` `SCHEDULED` and `billing_status` `RESERVED`, and it increments the authorization's `visits_reserved` by one (with `visits_remaining` recomputed accordingly).

A session carries two parallel status dimensions. The clinical dimension moves `SCHEDULED` → `CHECKED_IN` → `COMPLETED`, with `SCHEDULED` or `CHECKED_IN` also able to divert to `CANCELLED` or `NO_SHOW`; the billing dimension moves in lockstep as described below. Every session lifecycle action is a `Clinician` operation, and each requires the appropriate source clinical status, returning `ERR_INVALID_STATE` when the session is not in a state the action permits.

- **Check-in** requires `SCHEDULED` and advances the session to `CHECKED_IN`; the visit remains reserved (still counted in `visits_reserved`), and billing stays `RESERVED`.
- **Completion** requires `CHECKED_IN` and advances the session to `COMPLETED`. This triggers the cascade: the billing dimension moves `RESERVED` → `BILLED`; then (link one) the authorization's `visits_used` increases by one and `visits_reserved` decreases by one, with `visits_remaining` recomputed; then (link two, conditional) if `visits_used` is now greater than or equal to `visit_cap`, the authorization transitions `APPROVED` → `EXHAUSTED`; then (link three, conditional) every `ACTIVE` plan on that now-exhausted authorization transitions to `ON_HOLD`.
- **No-show** requires the session to be `SCHEDULED` or `CHECKED_IN` and advances it to `NO_SHOW`. Billing moves `RESERVED` → `BILLED`; a no-show consumes the visit exactly as completion does — `visits_used` increases by one and `visits_reserved` decreases by one — and the same conditional authorization-exhaustion and plan-hold cascade follows.
- **Cancellation** requires the session to be `SCHEDULED` or `CHECKED_IN` and advances it to `CANCELLED`. Billing moves `RESERVED` → `VOID`, and the reservation is released as compensation: `visits_reserved` decreases by one, `visits_remaining` is recomputed, and no `visits_used` debit is recorded. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are all terminal clinical states.

### 3.6. Compression Garment Orders and L-Code Classification

A `Clinician` orders a compression garment for a patient by supplying the `patient_id`, the `evaluation_id`, the `quantity` of units ordered (at least 1), and the `expected_patient_version` concurrency token. The referenced evaluation must be `FINALIZED`, otherwise `ERR_EVALUATION_NOT_FINALIZED`, and must belong to the named patient, otherwise `ERR_EVALUATION_PATIENT_MISMATCH`. The order copies its `body_region` from the referenced evaluation and derives its garment attributes automatically.

Classification uses the evaluation's `isl_stage`, its `excess_volume_ml`, and its `body_region`. The region is grouped: `LEFT_ARM` and `RIGHT_ARM` form the arm group, `LEFT_LEG` and `RIGHT_LEG` form the leg group, and every other region (`HEAD_NECK`, `TRUNK`, `GENITAL`) forms the other group. A base class is read from the stage: `STAGE_0` and `STAGE_I` both give base class 1, `STAGE_II` gives 2, and `STAGE_III` gives 3. The base class is bumped up by one when the excess volume reaches or exceeds the group's volume-bump threshold — 150 ml for the arm group, 500 ml for the leg group, and 150 ml for the other group. The bumped class is then capped at 4, and the resulting `compression_class` is rendered as `CLASS_1`, `CLASS_2`, `CLASS_3`, or `CLASS_4`.

Whether the garment must be custom-fabricated is a separate determination captured in `custom_fabrication`: it is true when the capped compression class equals 4, or when the excess volume reaches or exceeds the group's custom threshold — 400 ml for the arm group, 1200 ml for the leg group, and 400 ml for the other group. The `garment_type` is fixed by region: `LEFT_ARM` and `RIGHT_ARM` yield `SLEEVE`, `LEFT_LEG` and `RIGHT_LEG` yield `STOCKING`, `HEAD_NECK` yields `CHIN_STRAP`, `TRUNK` yields `VEST`, and `GENITAL` yields `COMPRESSION_SHORT`. The HCPCS `l_code` is then selected from garment type and custom flag: a `SLEEVE` is L8100 off-the-shelf and L8102 custom; a `STOCKING` is L8110 off-the-shelf and L8112 custom; a `CHIN_STRAP` is L8130, a `VEST` is L8140, and a `COMPRESSION_SHORT` is L8150 regardless of the custom flag.

A new order is created in `DRAFT`. Because a fresh order for the same `patient_id` and `body_region` supersedes the prior one, creating an order transitions any existing `DRAFT` or `APPROVED` order for that patient and region to `SUPERSEDED`, and increments the patient's `version` by one (subject to the §2.6 stale-version guard). An `Authorizer` renders the payer decision: approving a `DRAFT` order advances it `DRAFT` → `APPROVED`, and denying a `DRAFT` order advances it `DRAFT` → `DENIED`; each requires the order to be `DRAFT` and otherwise returns `ERR_INVALID_STATE`. `DENIED` and `SUPERSEDED` are terminal.

### 3.7. DME Dispensing and Returns

Once a garment order is approved, a `DMECoordinator` dispenses physical stock against it. The dispense payload names the `garment_order_id` and the `dme_item_id` and specifies a `quantity` of units (at least 1). The referenced garment order must be `APPROVED`, otherwise `ERR_GARMENT_ORDER_NOT_APPROVED`. The chosen DME item's `l_code` must equal the garment order's `l_code`, otherwise `ERR_DME_LCODE_MISMATCH`. The dispensed `quantity` must not exceed the item's `on_hand_qty`, otherwise `ERR_DME_INSUFFICIENT_STOCK`.

A successful dispense is created in status `DISPENSED`, snapshots the item's L-code into the dispense's own `l_code` field at dispense time, increases the item's `outstanding_dispensed_qty` by the dispensed quantity, and decreases its `on_hand_qty` by the same amount. A `DMECoordinator` may reverse a dispense by returning it, which requires the dispense to be `DISPENSED` (otherwise `ERR_INVALID_STATE`) and advances it `DISPENSED` → `RETURNED`. A return is compensating: the item's `outstanding_dispensed_qty` decreases by the returned quantity and its `on_hand_qty` increases by the same amount, restoring the stock. Because `outstanding_dispensed_qty` counts only dispenses still in `DISPENSED` status, returned dispenses are excluded from it. `RETURNED` is terminal.

### 3.8. Home-Program Adherence and Outcome Reassessment

Throughout the intensive phase the patient records home-program days, and a `Clinician` logs each one as an adherence entry naming the `plan_id`, the `log_date` (the ISO date recorded), the `minutes_completed` that day (zero or greater), and `wore_garment`, a boolean for whether the compression garment was worn. Adherence logs are append-only and immutable; each one recomputes the owning plan's `adherence_rate`. A day counts as compliant when `wore_garment` is true *and* `minutes_completed` is greater than or equal to the plan's `prescribed_daily_minutes`. The `adherence_rate` is the count of compliant days divided by the total number of logged days, multiplied by 100 and rounded to one decimal place; when a plan has no logged days the rate is exactly 0.0.

Outcome measurement is done through a reassessment, created by a `Clinician`, that compares two evaluations of the same limb over time. The create payload names the `plan_id`, the `baseline_evaluation_id` (the earlier finalized evaluation), and the `current_evaluation_id` (the later finalized evaluation). Both referenced evaluations must have progressed past `DRAFT` — that is, each must be `FINALIZED` or `SUPERSEDED`, otherwise the create is rejected with `ERR_EVALUATION_NOT_FINALIZED`. A `SUPERSEDED` baseline is acceptable, because the current evaluation is exactly what supersedes it. A new reassessment is created in `DRAFT`.

A `Clinician` finalizes the reassessment, which requires it to be `DRAFT` (otherwise `ERR_INVALID_STATE`) and computes and freezes two outcome figures. The `volume_reduction_pct` measures shrinkage of the affected limb against its own earlier size: it is the baseline evaluation's `limb_volume_ml` minus the current evaluation's `limb_volume_ml`, divided by the baseline's `limb_volume_ml`, multiplied by 100, rounded to one decimal place. The `perv_pct` (Percent Excess Volume Reduction) instead measures shrinkage of the excess over the contralateral limb, and its denominator is the baseline **excess** rather than the baseline volume: it is the baseline's `excess_volume_ml` minus the current's `excess_volume_ml`, divided by the baseline's `excess_volume_ml`, multiplied by 100, rounded to one decimal place — a materially different figure from the volume reduction even for identical inputs. The `outcome_category` is keyed off `perv_pct`: `EXCELLENT` when it is at least 50, `GOOD` when it is at least 25 but below 50, `PARTIAL` when it is at least 0 but below 25, and `REGRESSION` when it is below 0.

Finalization also carries a phase-advancement side effect: when `perv_pct` is at least 50, the referenced plan's `phase` advances `PHASE_1_INTENSIVE` → `PHASE_2_MAINTENANCE`. A reassessment's status moves `DRAFT` → `FINALIZED`, with `FINALIZED` terminal.

### 3.9. Test-Driving the Logical Clock

To make time-dependent behavior deterministic, the server keeps a logical clock that a `ClinicAdmin` can set. The clock's startup default is 2026-05-01T00:00:00Z; before any set call the clock reads exactly this default and never falls back to wall-clock time. An admin-only test-driving capability sets the clock to a supplied `to_iso8601` instant and reports back the new `current_utc`. All server-minted timestamps and any "as of now" comparison — such as evaluating certification or scheduling times relative to the present — read from this logical clock.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including lifecycle transitions and derived-field recomputations — return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patients` | Register a patient | ClinicAdmin |
| GET | `/patients` | List patients | Clinician, Authorizer, DMECoordinator, ClinicAdmin |
| GET | `/patients/{id}` | Get a patient | Clinician, Authorizer, DMECoordinator, ClinicAdmin |
| POST | `/evaluations` | Create an evaluation (staging + measurement) | Clinician |
| GET | `/evaluations` | List evaluations | Clinician, Authorizer, ClinicAdmin |
| GET | `/evaluations/{id}` | Get an evaluation | Clinician, Authorizer, ClinicAdmin |
| POST | `/evaluations/{id}/finalize` | Finalize an evaluation | Clinician |
| POST | `/authorizations` | Create an insurance authorization | Authorizer, ClinicAdmin |
| GET | `/authorizations` | List authorizations | Clinician, Authorizer, ClinicAdmin |
| GET | `/authorizations/{id}` | Get an authorization | Clinician, Authorizer, ClinicAdmin |
| POST | `/authorizations/{id}/submit` | Submit or resubmit an authorization | Authorizer |
| POST | `/authorizations/{id}/approve` | Approve an authorization | Authorizer |
| POST | `/authorizations/{id}/deny` | Deny an authorization | Authorizer |
| POST | `/authorizations/{id}/renew` | Renew an exhausted authorization | Authorizer |
| POST | `/treatment-plans` | Create a CDT treatment plan | Clinician |
| GET | `/treatment-plans` | List treatment plans | Clinician, Authorizer, ClinicAdmin |
| GET | `/treatment-plans/{id}` | Get a treatment plan | Clinician, Authorizer, ClinicAdmin |
| POST | `/treatment-plans/{id}/activate` | Activate a plan | Clinician |
| POST | `/treatment-plans/{id}/complete` | Complete a plan | Clinician |
| POST | `/therapists` | Register a therapist | ClinicAdmin |
| GET | `/therapists` | List therapists | Clinician, Authorizer, DMECoordinator, ClinicAdmin |
| GET | `/therapists/{id}` | Get a therapist | Clinician, Authorizer, DMECoordinator, ClinicAdmin |
| POST | `/sessions` | Schedule a CDT session | Clinician |
| GET | `/sessions` | List sessions | Clinician, Authorizer, ClinicAdmin |
| GET | `/sessions/{id}` | Get a session | Clinician, Authorizer, ClinicAdmin |
| POST | `/sessions/{id}/check-in` | Check in a scheduled session | Clinician |
| POST | `/sessions/{id}/complete` | Complete a session | Clinician |
| POST | `/sessions/{id}/cancel` | Cancel a session | Clinician |
| POST | `/sessions/{id}/no-show` | Mark a session no-show | Clinician |
| POST | `/garment-orders` | Order a compression garment | Clinician |
| GET | `/garment-orders` | List garment orders | Clinician, Authorizer, DMECoordinator, ClinicAdmin |
| GET | `/garment-orders/{id}` | Get a garment order | Clinician, Authorizer, DMECoordinator, ClinicAdmin |
| POST | `/garment-orders/{id}/approve` | Payer approves the garment order | Authorizer |
| POST | `/garment-orders/{id}/deny` | Payer denies the garment order | Authorizer |
| POST | `/dme-items` | Add a DME inventory item | DMECoordinator, ClinicAdmin |
| GET | `/dme-items` | List DME items | Clinician, DMECoordinator, ClinicAdmin |
| GET | `/dme-items/{id}` | Get a DME item | Clinician, DMECoordinator, ClinicAdmin |
| POST | `/dispenses` | Dispense DME against an approved order | DMECoordinator |
| GET | `/dispenses` | List dispenses | Clinician, DMECoordinator, ClinicAdmin |
| GET | `/dispenses/{id}` | Get a dispense | Clinician, DMECoordinator, ClinicAdmin |
| POST | `/dispenses/{id}/return` | Return a dispense (restores stock) | DMECoordinator |
| POST | `/reassessments` | Create a reassessment | Clinician |
| GET | `/reassessments` | List reassessments | Clinician, Authorizer, ClinicAdmin |
| GET | `/reassessments/{id}` | Get a reassessment | Clinician, Authorizer, ClinicAdmin |
| POST | `/reassessments/{id}/finalize` | Finalize a reassessment | Clinician |
| POST | `/adherence-logs` | Record a home-program adherence day | Clinician |
| GET | `/adherence-logs` | List adherence logs | Clinician, ClinicAdmin |
| GET | `/adherence-logs/{id}` | Get an adherence log | Clinician, ClinicAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ClinicAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_EVALUATION_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_THERAPIST_NOT_FOUND` | 404 |
| `ERR_GARMENT_ORDER_NOT_FOUND` | 404 |
| `ERR_DME_ITEM_NOT_FOUND` | 404 |
| `ERR_DISPENSE_NOT_FOUND` | 404 |
| `ERR_REASSESSMENT_NOT_FOUND` | 404 |
| `ERR_STALE_PATIENT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_AUTH_NOT_APPROVED` | 409 |
| `ERR_EVALUATION_NOT_FINALIZED` | 409 |
| `ERR_GARMENT_ORDER_NOT_APPROVED` | 409 |
| `ERR_OPEN_SESSIONS_EXIST` | 409 |
| `ERR_AUTH_PLAN_MISMATCH` | 409 |
| `ERR_EVALUATION_PATIENT_MISMATCH` | 409 |
| `ERR_DME_LCODE_MISMATCH` | 409 |
| `ERR_SESSION_OUTSIDE_AUTH_WINDOW` | 409 |
| `ERR_THERAPIST_DOUBLE_BOOKED` | 409 |
| `ERR_AUTH_WINDOW_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_MEASUREMENT` | 422 |
| `ERR_MEASUREMENT_LENGTH_MISMATCH` | 422 |
| `ERR_DME_INSUFFICIENT_STOCK` | 409 |
| `ERR_VISIT_CAP_EXCEEDED` | 409 |

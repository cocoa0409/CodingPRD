# USDA-Inspected Meat Processing & HACCP API — Product Requirements Document

## 1. Introduction

Operating a USDA-inspected packing establishment means living under continuous federal scrutiny: an FSIS inspector must be on premise before the chain moves, every critical control point in the plant's HACCP plan must be monitored on a documented frequency, and a single positive pathogen result can freeze inventory, halt production, and follow the plant's compliance record for months. This document specifies an API that models that operating reality end to end — HACCP plan drafting, review, and activation; inspector coverage scheduling with check-in enforcement; production-day gating; carcass receiving, fabrication, and yield accounting; pathogen sampling with positive-lot hold cascades; label approval and claim substantiation; cold-chain shelf-life dating; humane-handling audits; noncompliance records; and recall-readiness exercises.

Two design ideas organize the whole platform. The first is **segregation of duties**: the technician who records a monitoring reading may not verify the corrective action it spawned, and the operator who caused a noncompliance record may not be the inspector who closes it. The second is **posture-driven gating**: plants, production days, carcass lots, and finished lots each carry an explicit lifecycle state, and regulatory events propagate through those states as immediate, synchronous cascades — a failed humane-handling audit suspends the plant and every open production day beneath it, while a positive pathogen result holds the source lot, quarantines its finished product, and marks the production day restricted. Every derived figure the platform exposes — cooler occupancy, compliance scores, yield percentages, shelf-life dating, day posture — is recomputed at the moment the triggering event is recorded, never lazily.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. The platform recognizes exactly six roles: `PlantAdmin`, `QAManager`, `QATech`, `LabAnalyst`, `Inspector`, and `ProductionManager`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not on the target endpoint's authorized-role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

One further identity rule applies specifically to inspector shift check-in and check-out: the presented `X-User-ID` must equal the shift's recorded `inspector_user_id`, otherwise the request fails with `ERR_CHECKIN_IDENTITY_MISMATCH` (HTTP 403).

For each of the six roles — `PlantAdmin`, `QAManager`, `QATech`, `LabAnalyst`, `Inspector`, and `ProductionManager` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the resources the actor touches (for example, as `approved_by` on a HACCP plan or label approval, `monitor_user_id` on a CCP observation, `collected_by` on a pathogen sample, `auditor_user_id` on a humane-handling audit, `created_by` on a noncompliance record, and `action_logged_by`, `verified_by`, or `resolved_by` where corrective and resolution workflows apply), but it never compares `X-User-ID` to any entity's `id`. The inspector shift rule above compares `X-User-ID` against a stored payload field, not against a resource identifier, so it does not contradict this opacity principle.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 rather than wall-clock time.
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
- The same envelope covers framework-level rejections: requests to undefined routes, and to defined paths with an unsupported method, surface as `ERR_NOT_FOUND` (HTTP 404), and any unexpected server fault surfaces as `ERR_INVALID_REQUEST` (HTTP 400).

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter sets the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by `id` ascending.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. The Logical Clock

All timestamps this document describes as "now" — submission and approval stamps on plans, check-in and check-out stamps on shifts, lab result stamps, audit and recall stamps, finished-lot production stamps, the `created_at` and `updated_at` stamps of every resource, and the date matching used to attach monitoring observations to a production day — read from a single server-side **logical clock**, never from wall-clock time. At startup the logical clock is exactly `2026-08-01T00:00:00Z`, and it advances only when explicitly set.

A `PlantAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the new clock reading as `current_utc`. Advancing the clock performs a sweep: every inspector shift still in `SCHEDULED` status whose `scheduled_end` now lies in the past transitions to `NO_SHOW`. The sweep processes eligible shifts ordered by `scheduled_end` ascending, breaking ties by `created_at` ascending.

### 2.5. Common Resource Properties

Primary resources — plants, HACCP plans, critical control points, deviations, inspector shifts, production days, carcass lots, pathogen samples, label approvals, finished lots, noncompliance records, and recall exercises — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments on every mutation.

Three record types are append-only event records and carry **only** `id` and `created_at`: CCP observations, cut records, and humane-handling audits. For these three, both `updated_at` and `version` are absent.

When a cascade described in this document mutates a resource — a state flip, a recomputed score, a refreshed posture — that mutation refreshes the resource's `updated_at` and increments its `version` exactly as a client-driven write would.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. Each identifier in the path must correspond to an existing resource; the first identifier that does not resolve rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any later segment is examined. A child resource whose parent foreign key does not match the parent named in the path is treated as not found, producing the same `ERR_NOT_FOUND` rejection. Only after every path identifier has resolved do state and business rules come into play.

### 2.7. Validation Order

Every request is evaluated against a fixed sequence of rule families, and a failure in an earlier family masks all later families:

1. **Authentication** — presence of `X-User-ID` and `X-User-Role` with a declared role (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the acting role appears in the endpoint's authorized list (`ERR_FORBIDDEN_ROLE`).
3. **Shift identity** — for check-in and check-out only, `X-User-ID` equals the shift's `inspector_user_id` (`ERR_CHECKIN_IDENTITY_MISMATCH`); because the comparison needs the shift's stored field, an unresolvable shift id rejects with `ERR_NOT_FOUND` before this check runs.
4. **Request body schema** — required fields present, types and enum memberships valid, numeric ranges respected (`ERR_INVALID_REQUEST`). The body must be a JSON object — a non-object body fails with `ERR_INVALID_REQUEST`, while an absent or unparseable body is treated as an empty object — and required string fields must be non-empty. The cross-field rule that a CCP's lower critical limit must sit below its upper limit is deliberately *not* part of this family; it is evaluated later as a business constraint.
5. **Path existence** — left-to-right resolution per §2.6 (`ERR_NOT_FOUND`).
6. **Resource state** — the target resource sits in the from-state its transition requires, and day/lot/plan/label/sample/shift/deviation/noncompliance/recall state guards hold (the 409 family).
7. **Business rules** — safety, temporal, referential, and constraint checks (the 422 family), then segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`, HTTP 403) last.

Within a single endpoint, the specific business checks run in the relative order stated in the §3 narrative for that workflow.

### 2.8. Cascading Posture and Hierarchical Consistency

The platform maintains consistency across its hierarchy through three declared cascade chains, all applied synchronously at the moment the triggering event is recorded.

The **pathogen cascade** has three links. Link 1: a lab result of `POSITIVE` moves the sampled carcass lot to `HELD` — or directly to `CONDEMNED` whenever the lot was already `HELD` (the confirmation-retest path being the common case). Link 2: the lot's transition to `HELD` or `CONDEMNED` moves every finished lot sourced from it and still in `PRODUCED` status to `QUARANTINED`. Link 3: each such quarantine recomputes the owning production day's posture to `RESTRICTED`.

The **noncompliance cascade** also has three links. Link 1: creation of a noncompliance record with severity `CRITICAL` (a failed humane-handling audit or a failed recall exercise) flips the plant's `operating_status` to `SUSPENDED`. Link 2: the plant's suspension moves every `OPEN` production day of that plant to `SUSPENDED`. Link 3: resolving the last remaining `OPEN` `CRITICAL` record flips the plant back to `ACTIVE` — but production days suspended along the way are *not* automatically resumed; each requires an explicit open action to run again.

The **inspector-departure cascade** is conditional: when an inspector checks out and no other shift of the same plant remains `ON_PREMISE`, every `OPEN` production day of the plant transitions to `SUSPENDED`.

A production day's `posture` field is derived, never set directly: it reads `RESTRICTED` while any carcass lot of the day is `HELD`, any finished lot of the day is `QUARANTINED`, or any deviation of the day is `OPEN` or `ACTION_LOGGED`, and `CLEAR` otherwise.

### 2.9. Precision, Rounding, and Measurement Conventions

All weight, yield, percentage, and dating figures produced by the platform's calculations are rounded to exactly 2 decimal places using the round-half-up method, with one exception: the cut-weight and cold-weight totals — the lot's `total_cut_weight_lbs` and the production day's `total_cut_weight_lbs` and `total_cold_weight_lbs` — are kept and exposed as exact, unrounded sums at every accumulation and aggregation step, and two-decimal rounding applies only to the percentages and yields derived from them, never to the totals themselves. Plant compliance scores are integers. Accumulated cold-chain penalty hours are exposed rounded to 2 decimal places (the shelf-life computation itself subtracts the unrounded accumulation), and shelf-life timestamps are stored at millisecond precision and compared as stored. Humane-handling audit metrics are compared exactly as supplied in the request, with no rounding applied before threshold comparison.

### 2.10. Optimistic Concurrency Control

This API declares no optimistic-concurrency rules. No write endpoint accepts an expected-version field, and no request is rejected for carrying a stale `version` reading. Every write-write conflict in the domain is decidable from state the second request can observe — the state preconditions in §3 act as the serialization mechanism — so the `version` field described in §2.5 is informational rather than a concurrency token.

## 3. Business Logic & Workflows

### 3.1. Plant Registration, Cooler Capacity, and Compliance Posture

A `PlantAdmin` registers an establishment by supplying its `establishment_number` — unique across all plants, with duplicates rejected as `ERR_INVALID_REQUEST` (HTTP 400) — along with a display `name`, the FSIS `district_code`, and the finished-product `cooler_capacity_lbs`, which must be greater than zero. Registration initializes `operating_status` to `ACTIVE`, both compliance scores to 100, and `cooler_occupied_lbs` to zero.

Cooler occupancy is a running ledger over the plant's finished lots: `cooler_occupied_lbs` is the sum of `total_weight_lbs` across the plant's finished lots in `PRODUCED`, `QUARANTINED`, or `SPOILED` status; lots that have been `SHIPPED` no longer occupy the cooler. Packing a new finished lot adds exactly its `total_weight_lbs`, and shipping a lot removes exactly its `total_weight_lbs`, so occupancy always sits between zero and `cooler_capacity_lbs` inclusive. The creation gate rejects a packing run that would push occupancy strictly above capacity — landing exactly on capacity is allowed — with `ERR_COOLER_CAPACITY_EXCEEDED` (HTTP 422).

Two scores track the plant's compliance standing, and they answer different questions. The `provisional_compliance_score` is a flat operational reading: 100 minus 2 points for each of the plant's deviations still in `OPEN` or `ACTION_LOGGED` status, regardless of severity, and ignoring verified deviations entirely. The `official_compliance_score` is the severity-weighted standing: 100 minus the sum of severity weights over the plant's `VERIFIED` deviations only, where a `MINOR` deviation weighs 2 points and a `MAJOR` deviation weighs 5. Both scores are floored at zero. Because the variants count different populations of the same underlying data, identical plant history routinely yields two different numbers — the provisional score moves while work is unresolved, and the official score moves only when verification lands.

### 3.2. HACCP Plans and Critical Control Points

A `QAManager` drafts a HACCP plan for a plant by naming its `process_type`, one of `SLAUGHTER`, `RAW_GROUND`, `RAW_INTACT`, or `COOKED_RTE`. Only one plan per plant and process type may be in flight at a time: if another plan for the same pair already exists in `DRAFT`, `SUBMITTED`, or `APPROVED` status, creation is rejected with `ERR_DUPLICATE_ACTIVE_PLAN`. A new plan starts in `DRAFT` with `revision_number` zero.

While the plan is `DRAFT`, the `QAManager` adds critical control points to it; attempting to add a CCP to a plan in any other state is rejected with `ERR_PLAN_INVALID_STATE`. Each CCP carries a plant-local `ccp_code` unique within its plan (for example, `CCP-1B`), a `hazard_category` of `BIOLOGICAL`, `CHEMICAL`, or `PHYSICAL`, a free-text `description`, and an integer `monitoring_frequency_minutes` interval greater than zero that documents how often the point is checked — the server stores this interval but does not enforce it. Critical limits are optional per side but not both absent: at least one of `critical_limit_min_f` and `critical_limit_max_f` must be supplied, and when both are present the minimum must be strictly below the maximum; violations surface as `ERR_CCP_LIMIT_INVALID` at the business-constraint stage, after body-schema validation has already run. `ccp_code` uniqueness is enforced last: a code already carried by another CCP of the same plan is rejected with `ERR_INVALID_REQUEST` (HTTP 400), after the critical-limit check above. From the hazard category the server derives `deviation_severity`: `MAJOR` for a `BIOLOGICAL` hazard, `MINOR` otherwise.

Submitting the plan moves it from `DRAFT` to `SUBMITTED` and stamps `submitted_at` from the logical clock. The state check runs first, then the content check: a plan with zero critical control points cannot be submitted and is rejected with `ERR_PLAN_HAS_NO_CCP`. An `Inspector` then dispositions the submission — approving stamps `approved_by` with the inspector's `X-User-ID` and `approved_at` with the clock, while rejecting records the payload's `rejection_reason` and moves the plan to `REJECTED`. Both actions require the plan to be `SUBMITTED`, enforced as `ERR_PLAN_INVALID_STATE`. A rejected plan re-enters the loop: resubmission moves `REJECTED` back to `SUBMITTED`, increments `revision_number` by one, clears `rejection_reason` to null, and refreshes `submitted_at`.

Activation is the final step and belongs to the `QAManager`: an `APPROVED` plan becomes `EFFECTIVE`, and any previously `EFFECTIVE` plan of the same plant and `process_type` is simultaneously moved to `SUPERSEDED`, so at most one plan per plant and process type is ever effective. `SUPERSEDED` is terminal. Plans can be listed with filters on `plant_id`, `process_type`, and `status`; CCPs can be listed filtered by `haccp_plan_id` or `hazard_category`.

### 3.3. Inspector Coverage Shifts and the Production Day

Federal inspection requires coverage before production may run, and the shift workflow enforces it. A `PlantAdmin` schedules coverage by supplying the `inspector_user_id` to be covered plus `scheduled_start` and `scheduled_end` instants; the start must be strictly before the end or the request fails body-schema validation. One inspector may not hold overlapping commitments: a new shift for the same `inspector_user_id` that overlaps an existing shift in `SCHEDULED` or `ON_PREMISE` status is rejected with `ERR_SHIFT_WINDOW_CONFLICT`. Intervals are treated as half-open — a new shift whose start equals an existing shift's end (or vice versa) touches without overlapping and is allowed.

The scheduled inspector checks in personally. Among the check-in rules, identity is evaluated first (`ERR_CHECKIN_IDENTITY_MISMATCH` when `X-User-ID` does not match `inspector_user_id`), then the from-state (`ERR_SHIFT_INVALID_STATE` unless the shift is `SCHEDULED`), then the arrival window: check-in is accepted only when the logical clock reads within the inclusive window from fifteen minutes before `scheduled_start` through `scheduled_end`, and is otherwise rejected with `ERR_SHIFT_CHECKIN_OUTSIDE_WINDOW`. A successful check-in moves the shift to `ON_PREMISE` and stamps `checked_in_at`. Check-out mirrors the identity and state rules (`ON_PREMISE` required), stamps `checked_out_at`, moves the shift to `DEPARTED`, and then fires the conditional cascade of §2.8: if no other shift of the plant remains `ON_PREMISE`, every `OPEN` production day of that plant is suspended. A shift that nobody checks into is swept to `NO_SHOW` when the clock passes its `scheduled_end`, per §2.4. Shifts can be listed filtered by `plant_id`, `inspector_user_id`, or `status`.

Against that coverage backdrop, a `ProductionManager` plans a production day with a `production_date` calendar date and the `process_type` to be run. At most one non-`CLOSED` day may exist per plant and calendar date; a colliding plan is rejected with `ERR_DUPLICATE_PRODUCTION_DAY`. The new day starts `PLANNED` with `posture` `CLEAR`, its running totals `total_cut_weight_lbs` and `total_cold_weight_lbs` initialized to zero, and `day_yield_pct` null until the day closes.

Opening a day — from `PLANNED`, or resuming from `SUSPENDED` through the same action — is the most heavily gated transition in the platform, and its checks run in a fixed order. The from-state is validated first (`ERR_DAY_INVALID_STATE` for anything but `PLANNED` or `SUSPENDED`). Then come four business gates, in this order: the plant's `operating_status` must be `ACTIVE` (`ERR_PLANT_SUSPENDED`); at least one inspector shift of the plant must be `ON_PREMISE` (`ERR_INSPECTOR_NOT_PRESENT`); the logical-clock date must equal `production_date` (`ERR_DAY_DATE_MISMATCH`); and an `EFFECTIVE` HACCP plan must exist for the plant and the day's `process_type` (`ERR_PLAN_NOT_EFFECTIVE`). Success lands the day in `OPEN` and recomputes its posture.

Suspending an `OPEN` day moves it to `SUSPENDED`; resuming re-runs the full open gate sequence above. Closing a day — permitted from `OPEN` or `SUSPENDED` — is blocked with `ERR_DAY_INVALID_STATE` while any deviation of the day remains `OPEN` or `ACTION_LOGGED`, or while any carcass lot of the day sits outside the terminal-for-close pair `FABRICATED` and `CONDEMNED`. A successful close freezes the day's reconciliation: `total_cut_weight_lbs` and `total_cold_weight_lbs` are summed, unrounded, over the day's `FABRICATED` lots only (`CONDEMNED` lots are excluded from both sums), and `day_yield_pct` is set to one hundred times the frozen cut total divided by the frozen cold total, rounded half-up to two decimal places — or null when the frozen cold total is zero. `CLOSED` is terminal. Days can be listed filtered by `plant_id`, `production_date`, or `status`.

### 3.4. CCP Monitoring, Deviations, and Compliance Scoring

During an open production day, a `QATech` records a monitoring observation against a critical control point by supplying the `observed_value_f` reading. Two business gates guard the recording, evaluated in this order: an `OPEN` production day must exist for the CCP's plant whose `production_date` equals the current logical-clock date (`ERR_NO_OPEN_PRODUCTION_DAY`), and the plan owning the CCP must be `EFFECTIVE` (`ERR_PLAN_NOT_EFFECTIVE`). The observation records the technician's `X-User-ID` as `monitor_user_id` and the matched day's identifier as `production_day_id`. The server then computes `within_limit` with inclusive bounds: the reading passes when it is at least `critical_limit_min_f` (or the minimum is unset) and at most `critical_limit_max_f` (or the maximum is unset).

An out-of-limit observation spawns a `Deviation` in `OPEN` status whose `severity` is copied from the CCP's `deviation_severity`, links the observation back through `deviation_id`, and records the originating `observation_id` and `ccp_id`. The spawn immediately recomputes the plant's two compliance scores (§3.1) and the owning day's posture (§2.8).

Disposition follows a two-step path owned by the `QAManager`, with segregation of duties enforced at the second step. Logging a corrective action moves the deviation from `OPEN` to `ACTION_LOGGED` — any other from-state draws `ERR_DEVIATION_INVALID_STATE` — recording the payload's `corrective_action_note` and stamping `action_logged_by` with the actor's `X-User-ID`; the plant's `provisional_compliance_score` and the day's `posture` are recomputed. Verification then moves `ACTION_LOGGED` to `VERIFIED`: after the state check, the verifier's `X-User-ID` must differ both from the spawning observation's `monitor_user_id` and from `action_logged_by`, otherwise the request fails with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). A successful verify stamps `verified_by`, recomputes both plant scores — the official score now picks up the deviation's severity weight while the provisional score releases its flat two points — and recomputes the day's posture, which returns to `CLEAR` once no unresolved deviations, held lots, or quarantined finished lots remain. `VERIFIED` is terminal. Deviations can be listed filtered by `ccp_id`, `production_day_id`, `observation_id`, or `status`; observations by `ccp_id`, `production_day_id`, or `within_limit` — the `within_limit` filter treats the case-insensitive string `true` as true and any other value as false.

### 3.5. Carcass Receiving, Fabrication, and Yield Accounting

Livestock arrives against an `OPEN` production day. A `ProductionManager` receives a lot by declaring its `species` (`BOVINE`, `SWINE`, `OVINE`, or `POULTRY`), the `supplier_name`, an integer `head_count` greater than zero, and a `live_weight_lbs` greater than zero; the lot lands in `RECEIVED`. Every processing step that follows requires the owning day to be `OPEN`, enforced as `ERR_DAY_NOT_OPEN`, and the lot itself must sit in the step's required from-state, enforced as `ERR_LOT_INVALID_STATE`: ante-mortem requires `RECEIVED`, harvest requires `CLEARED`, chill-complete requires `HARVESTED`, fabrication requires `CHILLED` or `RELEASED`, and fabrication completion requires `FABRICATING`.

An `Inspector` performs the ante-mortem pass, moving `RECEIVED` to `CLEARED`. Harvest then records `hot_carcass_weight_lbs` — greater than zero — and moves the lot to `HARVESTED`. When chilling finishes, the recorded `cold_carcass_weight_lbs` must be greater than zero and no more than the hot weight; a cold weight exceeding the hot weight is rejected with `ERR_INVALID_REQUEST`. Chilling completes the lot into `CHILLED` and computes `drip_loss_pct` as one hundred times the difference between hot and cold carcass weight divided by the hot weight, rounded half-up to two decimal places.

Fabrication begins by moving `CHILLED` — or `RELEASED`, for a lot cleared from a hold — into `FABRICATING`. While the lot fabricates, the `ProductionManager` records cut lines — like every processing step this requires the owning day to be `OPEN` (`ERR_DAY_NOT_OPEN`) — each line carrying a `primal_type` (`CHUCK`, `RIB`, `LOIN`, `ROUND`, `BRISKET`, `BELLY`, `HAM`, or `OTHER`) and a `weight_lbs` greater than zero. Each line's `pct_of_cold_weight` — one hundred times the line weight divided by the lot's cold carcass weight — is rounded half-up to two decimal places at line creation, and the line's weight accumulates unrounded into the lot's `total_cut_weight_lbs`. Cut records are immutable once created, so lot-level totals never filter them.

Completion of fabrication is where the day's yield accounting crystallizes, and its checks run in order: the day must be `OPEN` (`ERR_DAY_NOT_OPEN`), the lot must be `FABRICATING` (`ERR_LOT_INVALID_STATE`), and then the mass-balance rule bites — at least one cut record must exist, and the absolute difference between the lot's `total_cut_weight_lbs` plus the payload's `trim_waste_lbs` (zero or more) and its `cold_carcass_weight_lbs` must not exceed half a pound, with violations rejected as `ERR_MASS_BALANCE_VIOLATION`. On success the lot becomes `FABRICATED` and two yield variants are computed from the *unrounded* sum of stored cut weights, each rounded half-up to two decimal places exactly once at the end: `fabrication_yield_pct` divides by the cold carcass weight and is the authoritative lot yield, while `packer_yield_pct` divides by the hot carcass weight so that cooler shrink counts against it — the packer figure is strictly lower than the fabrication figure whenever any drip loss occurred. Because the per-line percentages were rounded line by line, their sum may differ from `fabrication_yield_pct`; the lot-level figure governs. From the fabrication yield the server assigns `yield_grade`: `A` when it is at least 72.0, otherwise `B` when at least 68.0, otherwise `C`. Completion also syncs the owning day's `total_cut_weight_lbs` and `total_cold_weight_lbs` running totals. Lots can be listed filtered by `production_day_id`, `status`, or `species`; cut records by `lot_id` or `primal_type`.

### 3.6. Pathogen Sampling and the Positive-Result Hold Cascade

A `QATech` collects a pathogen sample from a lot by naming the target `organism` — `ECOLI_O157H7`, `SALMONELLA`, `LISTERIA_MONOCYTOGENES`, or `GENERIC_ECOLI` — and the `sample_type`, one of `CARCASS_SWAB`, `GROUND_PRODUCT`, or `ENVIRONMENTAL`. The owning day is checked first and must be `OPEN` (`ERR_DAY_NOT_OPEN`); then the lot's state is validated — sampling is permitted while the lot is `HARVESTED`, `CHILLED`, `FABRICATING`, or `FABRICATED`, and also while `HELD`, the held-lot path being precisely how confirmation retests are taken, with any other lot state drawing `ERR_LOT_INVALID_STATE`. The new sample records the collector as `collected_by`, starts with `result` `PENDING`, and computes `is_confirmation`: true when an earlier-created `POSITIVE` sample already exists for the same lot.

A `LabAnalyst` reports the outcome by supplying the `result` as `NEGATIVE` or `POSITIVE`; only a still-`PENDING` sample may be reported, otherwise `ERR_SAMPLE_ALREADY_REPORTED`. Either way `reported_at` is stamped from the logical clock. A `NEGATIVE` result ends the sample's story — but a `POSITIVE` result fires the three-link cascade of §2.8: the lot moves to `HELD` from any of the four processing states — or to `CONDEMNED` whenever a `POSITIVE` is reported while the lot is already `HELD`, the confirmation-retest path being the common case — every finished lot sourced from it and still `PRODUCED` moves to `QUARANTINED`, and the day's `posture` is recomputed to `RESTRICTED`. A `POSITIVE` reported while the lot sits in any other state (for example `RELEASED` or `CONDEMNED`) is recorded on the sample but fires no cascade.

Releasing a held lot is a `QAManager` action carrying a `disposition_note`. The lot must be `HELD` (`ERR_LOT_INVALID_STATE`), and the release requires proof the positive was resolved: a `NEGATIVE` sample of the lot ordered after the latest `POSITIVE` sample must exist — ordering is by `created_at`, ties broken by creation order, so a `NEGATIVE` recorded in the same clock tick but after the `POSITIVE` qualifies — otherwise the release is rejected with `ERR_POSITIVE_PATHOGEN_UNRESOLVED`. A successful release moves the lot to `RELEASED` — from which fabrication may begin or resume — and recomputes the day's posture. A held lot whose confirmation retest comes back `POSITIVE` instead moves to `CONDEMNED`, which is terminal; the same quarantine and posture cascades apply. Samples can be listed filtered by `lot_id`, `result`, or `organism`.

### 3.7. Label Approvals and Claim Substantiation

Label applications follow a review loop parallel to the HACCP plan loop but lighter. A `QAManager` drafts an application with the `product_name` as printed, a `claims` array whose members are drawn from `ORGANIC`, `GRASS_FED`, `NO_ANTIBIOTICS_EVER`, and `NATURAL`, a `substantiation_doc_refs` array of supporting document references, and a `formulation_version` integer of at least 1. The draft starts in `DRAFT`.

Submitting — from `DRAFT`, or from `REJECTED` as a resubmission — requires the substantiation file to cover every claim: at least one document reference per member of `claims`, otherwise `ERR_CLAIM_SUBSTANTIATION_MISSING`. The from-state check (`ERR_LABEL_INVALID_STATE`) runs before the substantiation check. Resubmission additionally clears any recorded `rejection_reason` to null. An `Inspector` then approves or rejects from `SUBMITTED`. Approval stamps `approved_by` and pins `approved_formulation_version` to whatever `formulation_version` the application carried at the moment of approval — this pinning is what lets packaging refer to an immutable, approved formulation even if later drafts change the declared version. Rejection records the payload's `rejection_reason`. `APPROVED` is terminal. Applications can be listed filtered by `plant_id`, `status`, or `product_name`.

### 3.8. Finished Goods, the Cold Chain, and Shelf-Life Dating

Packing converts a fabricated carcass lot into sellable units. A `ProductionManager` creates a finished lot on an `OPEN` production day by supplying the `source_lot_id` — which must reference a carcass lot in `FABRICATED` status, from any production day, even a `CLOSED` one — the `label_approval_id` to apply, an integer `units_produced` count greater than zero, a `unit_weight_lbs` greater than zero, and an integer `shelf_life_days` greater than zero. The gates run in a fixed order: the state family comes first — the owning day must be `OPEN` (`ERR_DAY_NOT_OPEN`) — then the payload's `source_lot_id` and `label_approval_id` must resolve to existing resources (`ERR_NOT_FOUND`) — followed by the business checks: the label must be `APPROVED` (`ERR_LABEL_INVALID_STATE`); the source lot must be `FABRICATED` (`ERR_LOT_INVALID_STATE`); no pathogen sample of the source lot may be `PENDING` or `POSITIVE` (`ERR_POSITIVE_PATHOGEN_UNRESOLVED`); the label must be the latest-approved application for the packing day's plant and the label's `product_name` — latest-approved is judged by the applications' `updated_at` stamps (refreshed at approval), ties broken by `id`, and the applied label is not itself required to belong to the packing plant — otherwise `ERR_LABEL_VERSION_STALE`; and the cooler gate of §3.1 must admit the new weight (`ERR_COOLER_CAPACITY_EXCEEDED`).

On success the server computes `total_weight_lbs` as `units_produced` times `unit_weight_lbs`, rounded half-up to two decimal places, and immediately debits `cooler_occupied_lbs` by that amount. Dating is established from the logical clock: `production_date` is stamped now, `base_use_by_at` is set to `production_date` plus `shelf_life_days` times twenty-four hours, `penalty_hours` starts at zero, and `use_by_at` starts equal to `base_use_by_at`. The lot's `temperature_logs` field is an append-only array of recorded-at/temperature entries kept in `recorded_at` order, initially empty, and the lot enters `PRODUCED`.

Cold-chain stewardship runs through temperature logging. A `ProductionManager` appends a reading by supplying `temp_f`; logging is permitted while the lot is `PRODUCED` or `QUARANTINED` and is otherwise rejected with `ERR_FINISHED_LOT_INVALID_STATE`. Each append records the entry at the current logical clock and triggers a full recomputation of the abuse penalty. The logs are processed in `recorded_at` ascending order with insertion order breaking ties. For every entry whose temperature is strictly above 40.0 °F, an interval is measured in hours — to the next entry's `recorded_at` when one exists, otherwise to the current logical clock — and that interval accrues into `penalty_hours` multiplied by a tier factor: 1.0 for readings above 40.0 °F and at most 45.0 °F, 1.5 for readings above 45.0 °F and at most 50.0 °F, and 2.0 for readings above 50.0 °F. Entries at exactly 40.0 °F or below accrue nothing. The recomputed `use_by_at` is the later of `production_date` and `base_use_by_at` minus the accumulated penalty, where the subtraction uses the unrounded accumulation while the exposed `penalty_hours` field carries that accumulation rounded half-up to two decimal places; an interval that would measure negative hours (possible only if the clock is moved backwards) accrues nothing, and timestamps are stored at millisecond precision and compared as stored. If the recomputed `use_by_at` has already passed relative to the logical clock, a lot in `PRODUCED` auto-transitions to `SPOILED` in the same request.

Shipping is the lot's exit. A `ProductionManager` ships a lot in `PRODUCED` status; the temporal gate is inclusive — the logical clock must read at or before `use_by_at`, and a strictly-later clock rejects the shipment with `ERR_SHELF_LIFE_EXPIRED`. A successful ship moves the lot to `SHIPPED`, stamps `shipped_at`, and credits `cooler_occupied_lbs` back by exactly the lot's `total_weight_lbs`. `SHIPPED`, `QUARANTINED`, and `SPOILED` are all terminal. Finished lots can be listed filtered by `production_day_id`, `source_lot_id`, `label_approval_id`, or `status`.

### 3.9. Humane Handling Audits, Noncompliance Records, and Recall Exercises

An `Inspector` records a humane-handling audit against a specific `production_day_id`, which must resolve to a day of the plant — an unresolvable id or a day of another plant rejects with `ERR_NOT_FOUND` — and that day must be `OPEN` (`ERR_DAY_NOT_OPEN`). The audit captures three metrics, each between 0 and 100: `stunning_efficacy_pct`, the percentage of animals rendered insensible on the first attempt; `slips_falls_pct`, the percentage slipping or falling; and `vocalization_pct`, the percentage vocalizing. The `outcome` is computed synchronously at creation, comparing the inputs exactly as provided: `PASSED` when stunning efficacy is at least 99.0 and slips and falls are at most 3.0 and vocalization is at most 10.0, and `FAILED` otherwise. The inspector's `X-User-ID` is recorded as `auditor_user_id`.

A `FAILED` outcome fires the noncompliance cascade of §2.8: a `NoncomplianceRecord` is created for the plant with `category` `HUMANE_HANDLING`, severity `CRITICAL`, `created_by` set to the auditor, a server-defaulted `regulation_cite` appropriate to the category (`9 CFR 313` for `HUMANE_HANDLING`, `9 CFR 418` for `TRACEABILITY`, `9 CFR 310.25` for `PATHOGEN_CONTROL`, `9 CFR 416` for `SANITATION`), a server-generated narrative `description`, and the audited day linked through `production_day_id`; the audit's `noncompliance_record_id` points at it (and stays null when the audit passed). The plant's `operating_status` flips to `SUSPENDED`, and every `OPEN` production day of the plant suspends with it. Audits can be listed filtered by `plant_id`, `production_day_id`, or `outcome`.

Noncompliance records carry a lifecycle of their own: `OPEN`, `APPEALED`, and terminal `CLOSED`, with severity `MAJOR` or `CRITICAL` across categories `HUMANE_HANDLING`, `TRACEABILITY`, `PATHOGEN_CONTROL`, and `SANITATION` (humane-handling and traceability origins are always `CRITICAL`; recall-origin records carry a null `production_day_id`). A `QAManager` appeals an `OPEN` record — any other state draws `ERR_NONCOMPLIANCE_INVALID_STATE` — recording the payload's `appeal_note` and moving it to `APPEALED`. An `Inspector` resolves a record from `OPEN` or `APPEALED` by supplying a `resolution_note`; after the state check, segregation of duties requires the resolver's `X-User-ID` to differ from the record's `created_by`, otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Resolution stamps `resolved_by`, moves the record to `CLOSED`, and recomputes the plant's `operating_status`: when the closed record was the plant's last `OPEN` `CRITICAL` record, the plant returns from `SUSPENDED` to `ACTIVE`, while days suspended along the way stay suspended until explicitly reopened. Records can be listed filtered by `plant_id`, `production_day_id`, `category`, or `status`.

Recall readiness is drilled, not assumed. A `PlantAdmin` initiates a traceability exercise against a `target_finished_lot_id` — which must resolve to an existing finished lot (`ERR_NOT_FOUND`) and must belong to the plant named in the path, otherwise `ERR_RECALL_TARGET_INVALID` — and a `scope` of `ONE_STEP_BACK`, `ONE_STEP_FORWARD`, or `FULL`. Initiation stamps `initiated_at` from the clock, sets `deadline_at` to twenty-four hours later, snapshots the target lot's `total_weight_lbs` as `basis_weight_lbs` (the one-hundred-percent recovery basis), and lands the exercise in `INITIATED`.

Completion belongs to the `QAManager`, who supplies the `reconciled_weight_lbs` actually accounted for (zero or more); an exercise no longer `INITIATED` rejects completion with `ERR_RECALL_ALREADY_COMPLETED`. The server computes `recovery_pct` as one hundred times the smaller of `reconciled_weight_lbs` and `basis_weight_lbs` divided by `basis_weight_lbs`, rounded half-up to two decimal places. The pass/fail decision, however, uses the unrounded ratio: the exercise lands in `PASSED` when the logical clock reads at or before `deadline_at` and the ratio of reconciled (capped at basis) to basis is at least 0.995 — a recovery percentage of at least 99.5 — and in `FAILED` when the deadline has passed or the ratio falls short. Either way `completed_at` is stamped. A `FAILED` exercise fires the full noncompliance cascade: a `TRACEABILITY` record with severity `CRITICAL` is created for the plant with `created_by` set to the completing operator and a null `production_day_id`, the plant suspends, and every `OPEN` production day of the plant suspends behind it. Exercises can be listed filtered by `plant_id`, `target_finished_lot_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — lifecycle transitions, appends to a resource's log, check-in/check-out — return `200 OK`. All responses use the envelope of §2.2, all list endpoints paginate per §2.3, and every endpoint enforces the header and role rules of §2.1 and the validation order of §2.7.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plants` | Register a USDA-inspected plant | PlantAdmin |
| GET | `/plants/{id}` | Plant detail including posture and compliance scores | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/plants/{id}/haccp-plans` | Create a HACCP plan in DRAFT for a process type | QAManager |
| GET | `/haccp-plans/{id}` | HACCP plan detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/haccp-plans` | List HACCP plans | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/haccp-plans/{id}/submit` | Submit plan for review; also resubmits a REJECTED plan | QAManager |
| POST | `/haccp-plans/{id}/approve` | Inspector approves a SUBMITTED plan | Inspector |
| POST | `/haccp-plans/{id}/reject` | Inspector rejects a SUBMITTED plan | Inspector |
| POST | `/haccp-plans/{id}/activate` | Activate an APPROVED plan, superseding the current EFFECTIVE sibling | QAManager |
| POST | `/haccp-plans/{id}/ccps` | Add a CCP to a DRAFT plan | QAManager |
| GET | `/ccps/{id}` | CCP detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/ccps` | List CCPs | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/ccps/{id}/observations` | Record a CCP monitoring observation; spawns a Deviation when out of limits | QATech |
| GET | `/observations/{id}` | Observation detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/observations` | List observations | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/deviations/{id}` | Deviation detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/deviations` | List deviations | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/deviations/{id}/log-corrective-action` | Record corrective action; OPEN to ACTION_LOGGED | QAManager |
| POST | `/deviations/{id}/verify` | Verify a corrective action; ACTION_LOGGED to VERIFIED | QAManager |
| POST | `/plants/{id}/inspector-shifts` | Schedule an inspector coverage shift | PlantAdmin |
| GET | `/inspector-shifts/{id}` | Shift detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/inspector-shifts` | List shifts | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/inspector-shifts/{id}/check-in` | Inspector checks in; SCHEDULED to ON_PREMISE | Inspector |
| POST | `/inspector-shifts/{id}/check-out` | Inspector checks out; may suspend the plant's OPEN days | Inspector |
| POST | `/plants/{id}/production-days` | Plan a production day | ProductionManager |
| GET | `/production-days/{id}` | Production day detail including posture and totals | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/production-days` | List production days | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/production-days/{id}/open` | Open a PLANNED day or resume a SUSPENDED day | ProductionManager |
| POST | `/production-days/{id}/suspend` | Suspend an OPEN day | ProductionManager |
| POST | `/production-days/{id}/close` | Close a day and freeze yield reconciliation | ProductionManager |
| POST | `/production-days/{id}/lots` | Receive a livestock lot on an OPEN day | ProductionManager |
| GET | `/lots/{id}` | Lot detail including yield accounting fields | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/lots` | List lots | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/lots/{id}/pass-ante-mortem` | Inspector passes ante-mortem inspection; RECEIVED to CLEARED | Inspector |
| POST | `/lots/{id}/harvest` | Record harvest and hot carcass weight; CLEARED to HARVESTED | ProductionManager |
| POST | `/lots/{id}/chill-complete` | Record cold carcass weight; HARVESTED to CHILLED; computes drip loss | ProductionManager |
| POST | `/lots/{id}/fabricate` | Begin fabrication; CHILLED or RELEASED to FABRICATING | ProductionManager |
| POST | `/lots/{id}/complete-fabrication` | Close out fabrication; enforces mass balance, computes yields and grade | ProductionManager |
| POST | `/lots/{id}/release-hold` | Release a HELD lot after a confirming NEGATIVE retest | QAManager |
| POST | `/lots/{id}/cut-records` | Record a cut against a FABRICATING lot | ProductionManager |
| GET | `/cut-records/{id}` | Cut record detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/cut-records` | List cut records | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/lots/{id}/pathogen-samples` | Collect a pathogen sample on a lot | QATech |
| GET | `/pathogen-samples/{id}` | Sample detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/pathogen-samples` | List samples | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/pathogen-samples/{id}/report-result` | Lab reports NEGATIVE or POSITIVE; POSITIVE fires the hold cascade | LabAnalyst |
| POST | `/plants/{id}/label-approvals` | Draft a label approval application with claims and substantiation | QAManager |
| GET | `/label-approvals/{id}` | Label approval detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/label-approvals` | List label approvals | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/label-approvals/{id}/submit` | Submit or resubmit a label; every claim requires a substantiation ref | QAManager |
| POST | `/label-approvals/{id}/approve` | Inspector approves label; pins the approved formulation version | Inspector |
| POST | `/label-approvals/{id}/reject` | Inspector rejects a SUBMITTED label | Inspector |
| POST | `/production-days/{id}/finished-lots` | Pack finished product from a FABRICATED lot under an approved label | ProductionManager |
| GET | `/finished-lots/{id}` | Finished lot detail including dating and temperature log | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/finished-lots` | List finished lots | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/finished-lots/{id}/ship` | Ship a PRODUCED lot; inclusive use-by gate; credits cooler capacity | ProductionManager |
| POST | `/finished-lots/{id}/log-temperature` | Append a cold-chain reading; recomputes penalty, use-by, possible spoilage | ProductionManager |
| POST | `/plants/{id}/humane-audits` | Record a humane-handling audit on an OPEN day; FAILED cascades | Inspector |
| GET | `/humane-audits/{id}` | Audit detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/humane-audits` | List humane handling audits | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/noncompliance-records/{id}` | Noncompliance record detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/noncompliance-records` | List noncompliance records | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/noncompliance-records/{id}/appeal` | QA appeals an OPEN record; OPEN to APPEALED | QAManager |
| POST | `/noncompliance-records/{id}/resolve` | Inspector closes a record; resolver must differ from its creator | Inspector |
| POST | `/plants/{id}/recall-exercises` | Initiate a traceability drill against a finished lot of this plant | PlantAdmin |
| GET | `/recall-exercises/{id}` | Recall exercise detail | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| GET | `/recall-exercises` | List recall exercises | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |
| POST | `/recall-exercises/{id}/complete` | Complete the drill with reconciled weight; FAILED cascades to a TRACEABILITY NR | QAManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock; sweeps expired SCHEDULED shifts to NO_SHOW | PlantAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CHECKIN_IDENTITY_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_DAY_INVALID_STATE` | 409 |
| `ERR_DAY_NOT_OPEN` | 409 |
| `ERR_LOT_INVALID_STATE` | 409 |
| `ERR_SAMPLE_ALREADY_REPORTED` | 409 |
| `ERR_LABEL_INVALID_STATE` | 409 |
| `ERR_FINISHED_LOT_INVALID_STATE` | 409 |
| `ERR_SHIFT_INVALID_STATE` | 409 |
| `ERR_DEVIATION_INVALID_STATE` | 409 |
| `ERR_NONCOMPLIANCE_INVALID_STATE` | 409 |
| `ERR_RECALL_ALREADY_COMPLETED` | 409 |
| `ERR_PLANT_SUSPENDED` | 422 |
| `ERR_INSPECTOR_NOT_PRESENT` | 422 |
| `ERR_POSITIVE_PATHOGEN_UNRESOLVED` | 422 |
| `ERR_SHIFT_WINDOW_CONFLICT` | 422 |
| `ERR_SHIFT_CHECKIN_OUTSIDE_WINDOW` | 422 |
| `ERR_SHELF_LIFE_EXPIRED` | 422 |
| `ERR_DAY_DATE_MISMATCH` | 422 |
| `ERR_NO_OPEN_PRODUCTION_DAY` | 422 |
| `ERR_PLAN_NOT_EFFECTIVE` | 422 |
| `ERR_LABEL_VERSION_STALE` | 422 |
| `ERR_RECALL_TARGET_INVALID` | 422 |
| `ERR_CCP_LIMIT_INVALID` | 422 |
| `ERR_PLAN_HAS_NO_CCP` | 422 |
| `ERR_DUPLICATE_ACTIVE_PLAN` | 422 |
| `ERR_DUPLICATE_PRODUCTION_DAY` | 422 |
| `ERR_MASS_BALANCE_VIOLATION` | 422 |
| `ERR_COOLER_CAPACITY_EXCEEDED` | 422 |
| `ERR_CLAIM_SUBSTANTIATION_MISSING` | 422 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 |

# Food Safety Inspection API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Health Department Food Safety Inspection API, the system of record by which a municipal health department licenses food establishments, schedules and conducts inspections, scores results into letter grades and placard colors, and pursues enforcement when an establishment falls out of compliance. The platform unifies what is, in most jurisdictions, a fragmented set of paper processes: a plan-review and permitting front office, a field-inspection operation that cites violations against the FDA Food Code, a placarding and closure regime driven by numeric scores and critical-violation counts, a complaint and foodborne-illness intake desk, and a formal enforcement track that can escalate to a hearing.

The central tension the API manages is that a single field inspection has cascading consequences. The violations an inspector records roll up into two distinct scores — one as observed and one crediting corrections made on the spot — which in turn drive a letter grade, a placard color, and, in the worst cases, an automatic closure order that suspends the establishment's permit. Reinspections can clear prior violations and reinstate a suspended establishment; enforcement hearings can vacate a closure entirely. Because so much downstream state hinges on the moment an inspection is finalized, the system treats finalization as a carefully guarded, version-checked operation and models time through an explicit logical clock so that reinspection due dates, permit expiry, and hearing dates are all deterministic and testable.

This API is intended for four classes of departmental user — front-office permit clerks, field inspectors, enforcement officers, and the health director — each with a tightly scoped set of operations. The sections that follow define the global request and response contract, the cross-cutting principles that govern scoring, concurrency, and time, and then the detailed business workflows for each stage of an establishment's regulatory life.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. If either header is missing or empty, the request is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly four roles: `PermitClerk`, `Inspector`, `EnforcementOfficer`, and `HealthDirector`. When a syntactically valid request is made by a role that is not permitted to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`.

The four roles are peers — none is a superset of another, and authorization is decided per operation rather than by rank. A `PermitClerk` is the front-office operator: it creates and updates establishments, submits and manages plan reviews, issues permits, and triages and closes complaints. An `Inspector` is the field operator: it runs routes, drives inspections through their lifecycle, records and removes violations, and dispatches complaints into inspections. An `EnforcementOfficer` administers closure orders and enforcement cases and their hearing lifecycle. A `HealthDirector` administers the code catalog and inspector roster, revokes establishments, issues hearing rulings, and controls the logical clock. Several operations are shared across roles, and these are spelled out in the workflow sections and the endpoint table.

Three of the four roles carry an opaque identity. When `X-User-Role` is `PermitClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `EnforcementOfficer` and when `X-User-Role` is `HealthDirector`: in each case `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`. The `Inspector` role is different: it is entity-backed. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` row, and ownership checks on any resource that references an `Inspector` compare the resource's inspector foreign-key field to `X-User-ID`. In particular, only the inspector whose `id` equals an inspection's `inspector_id` may start that inspection; a mismatch is rejected with `ERR_NOT_ASSIGNED_INSPECTOR`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Resource Identity

Every primary resource in the system — `FdaFoodCode`, `Inspector`, `Establishment`, `PlanReview`, `Permit`, `InspectionRoute`, `Inspection`, `Violation`, `ClosureOrder`, `Complaint`, and `EnforcementCase` — carries a standard set of system-managed fields. Each resource has an `id`, a unique server-minted UUID with no type prefix. Each has a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation. Each also carries an `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and a `version`, an integer that starts at the resource's creation and increments by one on every mutation of that resource. All entities in this system carry the full set of these four fields; there are no creation-only resources that omit `updated_at` or `version`.

Whenever the server changes a resource — whether in direct response to a client request or as an automatic side effect of another operation — that resource's `updated_at` is refreshed and its `version` is incremented. This applies to computed and derived fields just as it does to client-supplied fields: when finalizing an inspection promotes new score and grade values onto an establishment, the establishment is mutated, so its `updated_at` and `version` advance.

### 2.5. Filtered Retrieval and Reference Validation

This system has a flat topology: every entity is a top-level collection, and resources reference one another through foreign-key fields carried in request bodies rather than through nested URL paths. Relationships are therefore discovered through filtered list endpoints. A list of inspections can be narrowed by `establishment_id`, `inspector_id`, `route_id`, `reinspection_of_id`, `inspection_type`, or `status`; plan reviews by `establishment_id` or `status`; permits by `establishment_id`, `plan_review_id`, or `status`; violations by `inspection_id`, `fda_code_id`, `classification`, or `resolution_status`; closure orders by `establishment_id`, `triggering_inspection_id`, or `status`; complaints by `establishment_id`, `linked_inspection_id`, `status`, or `priority`; enforcement cases by `establishment_id`, `closure_order_id`, or `status`; routes by `inspector_id` or `status`; establishments by `status` or `risk_category`; and FDA Food Codes by `classification` or `is_active`.

For any request that names a resource by its identifier in the path, the system validates that identifier before applying business rules; an unknown identifier yields the corresponding not-found error (for example `ERR_ESTABLISHMENT_NOT_FOUND`, `ERR_PLAN_REVIEW_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_CODE_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CLOSURE_ORDER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`). When a path carries more than one identifier, they are validated left to right and the first unknown identifier determines the not-found response. Foreign keys supplied in a request body — `fda_code_id`, `plan_review_id`, `route_id`, `inspector_id`, `reinspection_of_id`, `establishment_id`, `triggering_inspection_id`, and `closure_order_id` — must reference existing rows; an unknown body foreign key yields the matching not-found error with HTTP status 404.

### 2.6. Request Validation and Evaluation Order

Validation is layered, and the layers are applied in a fixed priority so that test results are deterministic. The presence of the user-context headers is checked first; a missing or empty `X-User-ID` or `X-User-Role` produces `ERR_MISSING_USER_CONTEXT` (HTTP 401). Role authorization is checked next: a role not permitted for the operation produces `ERR_FORBIDDEN_ROLE` (HTTP 403). Existence of path-referenced resources is checked third, left to right, producing the appropriate not-found error (HTTP 404). Existence of body foreign keys is checked fourth, producing the appropriate not-found error (HTTP 404). The optimistic-concurrency check on a supplied inspection version is checked fifth, before any business logic (see §2.8). State legality — whether the target resource is in a state from which the requested transition is allowed — is checked sixth, producing the relevant conflict error (HTTP 409). Domain-specific business checks (such as a retired code, an invalid reinspection target, route capacity, double-booking, or a past route or hearing date) follow. Body well-formedness — required fields present, enum values valid, and integers within their declared ranges — is enforced with `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint.

### 2.7. The Logical Clock and Scheduled Time

The system does not use wall-clock time for any business rule. Instead it maintains a single logical clock expressed as an integer day index, exposed and read as `current_index`. On server startup the clock is fixed at index 0, which corresponds to 2026-01-01T00:00:00Z; before any explicit set call the clock reads exactly index 0 and never falls back to the host's wall-clock time. A `HealthDirector` may move the clock to any integer day index by supplying `to_index`. All time-driven values — an inspection's `scheduled_index`, a route's `route_date_index`, a permit's `issued_index` and `expires_index`, a closure order's `issued_index`, a hearing's `hearing_index`, and an establishment's `next_reinspection_due_index` — are expressed in these integer day indices and are compared against the current `current_index`.

### 2.8. Optimistic Concurrency on Inspection Finalization

Finalizing an inspection is the one operation in this system guarded by optimistic concurrency control, because it promotes a score that the client read at some earlier point onto the establishment and fires irreversible cascades. The finalize request must carry `expected_inspection_version`, a non-optional field holding the `version` of the target `Inspection` that the client last observed. Before any finalize business logic runs, the server compares `expected_inspection_version` against the inspection's current `version`; if they do not match, the request is rejected with `ERR_STALE_INSPECTION_VERSION` (HTTP 412). The reason this matters is that a `COMPLETED` inspection can be reopened to `AMENDING` and re-completed — each reopen increments the inspection's `version` — which legitimately supersedes the score the finalizing client last read. A finalize still carrying the pre-amendment version is therefore stale and must be rejected rather than allowed to overwrite work it never saw. No other endpoint in the system accepts or requires a version field; only finalization performs this check.

### 2.9. Scoring Precision and Rounding

All scores in this system are integers on a 0-to-100 scale, derived by subtracting accumulated demerit points from a base of 100. Demerit accumulation has a pinned order of operations that the implementation must follow exactly, because reordering the steps changes the result. The per-violation point contribution is computed first, and where a correction credit halves a violation's points, that halving is applied per violation and rounded up to the nearest whole point before any summation. Only after every violation's points are individually computed are they summed. The summed total is then subtracted from 100, and the result is clamped so that it never falls below 0 and never exceeds 100. This is a sum-then-clamp model, not a per-line clamp: points are aggregated across all violations first, and the clamp is applied once to the final figure. Monetary amounts elsewhere in the system (plan-review fees, permit fees, and penalties) are whole integer cents; the only rounding that occurs is the per-violation ceiling in scoring and a floor applied to a reduced penalty, both described in their workflow sections.

### 2.10. Cascades, Reconciliation, and Hierarchical Consistency

Many operations in this system mutate more than one resource. The system maintains consistency immediately: when a finalized inspection changes an establishment's grade, the establishment's promoted score, grade, and placard fields, its open-critical tally, its closure linkage, and its status are all reconciled within the same operation, and each mutated resource has its `updated_at` refreshed and its `version` incremented. The server may transition a parent resource automatically when a child operation satisfies or violates the parent's criteria — an establishment can move from `PERMITTED` to `SUSPENDED` because a finalized inspection produced a closing grade, and from `SUSPENDED` back to `PERMITTED` because a passing reinspection or a vacated closure cleared the condition — without an explicit client request against the establishment itself. The specific cascade rules live in the workflow sections that follow.

## 3. Business Logic & Workflows

### 3.1. Catalog and Roster Administration

Before any establishment can be inspected, the department maintains two reference catalogs. The `HealthDirector` curates the **FDA Food Code** catalog. Each `FdaFoodCode` is created with a `code` — the FDA Food Code section identifier such as "3-501.16", which must be unique across all codes and is immutable once created — together with a human-readable `title`, a `classification` that is either `CRITICAL` or `NON_CRITICAL`, and a `base_demerit_points` value (an integer from 1 to 40) representing the points deducted from the 100-point base when the code is cited once at full weight. A code may also declare `repeat_surcharge_points`, an integer from 0 to 20 that defaults to 0 and represents extra points added when the same code is cited against an establishment that already has an unresolved prior citation of it. Each code carries an `is_active` flag that begins true. The director may retire a code, which sets `is_active` to false; a retired code remains in the catalog and on historical violations but cannot be cited on a new violation.

The `HealthDirector` also registers **inspectors**. An `Inspector` is created with a `full_name` and a `badge_number` that must be unique across all inspectors. Each inspector declares `max_daily_route_stops`, an integer from 1 to 20 defaulting to 8, which caps how many stops may be assigned to that inspector on a single route day. An inspector carries an `is_active` flag that begins true; an inactive inspector cannot be assigned to new routes or inspections.

### 3.2. Establishment Onboarding, Risk Classification, and Plan Review

A `PermitClerk` registers a new food establishment by supplying its `name`, its `address`, an optional descriptive `cuisine_type`, a declared `seating_capacity` (a non-negative integer), and two optional boolean flags that both default to false: `serves_raw_animal_foods`, true when the menu includes raw or undercooked animal foods, and `does_onsite_processing`, true when the establishment cans, cures, or smokes food on site. A new establishment begins in the `PRELICENSE` status.

At creation the system computes the establishment's `risk_category`, one of `CATEGORY_1` (low), `CATEGORY_2` (medium), or `CATEGORY_3` (high), in a fixed order. The seating band is determined first: the base category is `CATEGORY_1`, but a seating capacity of at least 50 raises the base to `CATEGORY_2`, and a seating capacity of at least 150 raises it to `CATEGORY_3`. Two escalators are then applied in their declared order, each lifting the category by exactly one band and capped at `CATEGORY_3`: first, if the establishment serves raw animal foods, the category is bumped up one band; then, if it does on-site processing, the category is bumped up one band again. Bumping `CATEGORY_3` leaves it at `CATEGORY_3`. From the resulting `risk_category` the system derives `routine_interval_days`, the number of days between routine inspections: 365 days for `CATEGORY_1`, 180 days for `CATEGORY_2`, and 90 days for `CATEGORY_3`. Updating an establishment's profile recomputes both `risk_category` and `routine_interval_days` by the same procedure.

Before a permit can issue, the prospective layout undergoes a **plan review**. A `PermitClerk` submits a `PlanReview` carrying the `establishment_id` it is for, a `submitted_layout_sqft` (a positive integer of proposed kitchen square footage), and an `equipment_count` (a non-negative integer of NSF-listed equipment items). A new plan review begins `SUBMITTED` with a `revision_round` of 0. On submission the system computes `plan_fee_cents`, the plan review fee in whole cents, by marginal square-footage tiering on top of a base fee. The base fee is 20,000 cents. The first 500 square feet add nothing. Each square foot from the 501st through the 1,500th adds 50 cents. Each square foot beyond the 1,500th adds 80 cents. To this the system adds 1,500 cents per item of declared equipment. Because the tier rates are whole cents, no rounding is required.

A submitted plan review may be approved or rejected by a `PermitClerk`. Approval moves a plan review from `SUBMITTED` to `APPROVED`; it requires that the plan review currently be `SUBMITTED` (otherwise `ERR_PLAN_REVIEW_NOT_SUBMITTED`) and that the establishment still be `PRELICENSE` (otherwise `ERR_ESTABLISHMENT_NOT_PRELICENSE`). Rejection moves a plan review from `SUBMITTED` to `REJECTED`; it likewise requires the plan review to be `SUBMITTED` (otherwise `ERR_PLAN_REVIEW_NOT_SUBMITTED`) and requires a non-empty `rejection_reason` in the request, which is recorded on the plan review — a missing or empty reason yields `ERR_MISSING_REJECTION_REASON`. A rejected plan review can be resubmitted, which is the cyclic path back from `REJECTED` to `SUBMITTED`: resubmit requires the plan review to be `REJECTED` (otherwise `ERR_PLAN_REVIEW_NOT_REJECTED`), and when it succeeds it increments `revision_round` by one, accepts optionally revised `submitted_layout_sqft` and `equipment_count`, recomputes `plan_fee_cents` against the new layout and equipment, and clears the recorded `rejection_reason`. A plan can bounce between `SUBMITTED` and `REJECTED` any number of times until it is finally approved; `APPROVED` is terminal.

### 3.3. Permit Issuance and Establishment Lifecycle

With an approved plan review in hand, a `PermitClerk` issues a **permit**, supplying the `establishment_id` and the `plan_review_id` of the approving review. Issuance is the transition that moves an establishment from `PRELICENSE` to `PERMITTED`. It requires that the establishment currently be `PRELICENSE` (otherwise `ERR_ESTABLISHMENT_NOT_PRELICENSE`) and that the referenced plan review both belong to this establishment and be in the `APPROVED` status (otherwise `ERR_PLAN_REVIEW_NOT_APPROVED`). Issuance creates a `Permit` whose `status` is `ACTIVE`, records its `issued_index` at the current clock index, sets its `expires_index` to the issued index plus 365 days, and computes its `annual_fee_cents`. The annual permit fee is a flat figure scaled by the establishment's risk category at issuance: 30,000 cents for `CATEGORY_1`, 60,000 cents for `CATEGORY_2`, and 120,000 cents for `CATEGORY_3`. As part of the same issuance the establishment moves to `PERMITTED` and its `next_reinspection_due_index` is set to the current clock index plus its `routine_interval_days`.

A permit's `status` is derived on every read. It reads `ACTIVE` while the establishment holds it, becomes `EXPIRED` once the current clock index exceeds the permit's `expires_index` (provided it has not been voided), and is set to `VOID` when its establishment is revoked. Permit validity holds while the clock index is less than or equal to `expires_index`.

The establishment's `status` follows a cyclic lifecycle. From `PERMITTED` an establishment moves to `SUSPENDED` when a closure order becomes active against it — whether that closure was raised automatically by a closing grade at finalization or issued manually. Suspension requires the establishment to be `PERMITTED` (otherwise `ERR_ESTABLISHMENT_NOT_PERMITTED`) and sets the establishment's `active_closure_order_id` to the new closure order's id. From `SUSPENDED` an establishment returns to `PERMITTED` when its active closure is lifted — either automatically by a passing reinspection or by an explicit lift action. The explicit lift action targets a closure order by its path identifier and checks its preconditions in this order: it first requires the targeted closure order's establishment to be `SUSPENDED` (otherwise `ERR_ESTABLISHMENT_NOT_SUSPENDED`), and then requires that targeted closure order to itself be `ACTIVE` (otherwise `ERR_CLOSURE_ORDER_NOT_ACTIVE`). On success the closure order moves to `LIFTED`, the establishment's `active_closure_order_id` is cleared to null, and the establishment returns to `PERMITTED`. This `SUSPENDED`-to-`PERMITTED`-and-back loop may repeat across the establishment's life as closures are issued and lifted.

Revocation is terminal and reserved for the `HealthDirector`. An establishment may be revoked from either `PERMITTED` or `SUSPENDED`; an attempt from any other status is rejected with `ERR_ESTABLISHMENT_NOT_REVOCABLE`. (When the revoke action is invoked specifically against a suspended establishment that must be suspended, the suspension precondition `ERR_ESTABLISHMENT_NOT_SUSPENDED` governs.) Revocation sets the establishment's `status` to `REVOKED` and voids all of its active permits, moving each to `VOID`. Beyond its core profile fields, an establishment also exposes the rolled-up results of its inspection history: `current_score`, the integer score from its most recent finalized inspection (null until the first finalize); `current_grade`, one of `A`, `B`, `C`, or `CLOSED` from that inspection; `current_placard_color`, one of `GREEN`, `YELLOW`, or `RED`; `open_critical_count`, the count of unresolved critical violations across all of its finalized inspections; and `next_reinspection_due_index`, the clock index by which a mandated reinspection must occur (null when none is pending).

### 3.4. Routes, Scheduling, and the Inspection Lifecycle

Field work is organized into **inspection routes**. A `PermitClerk` or an `Inspector` creates an `InspectionRoute` for a given `inspector_id` on a `route_date_index` (a non-negative integer day index); a new route begins `PLANNED` with a `planned_stop_count` of 0. As inspections are scheduled under a route, the route's `planned_stop_count` is incremented. An `Inspector` dispatches a planned route, moving it from `PLANNED` to `DISPATCHED`. Dispatch requires the route to be `PLANNED` (otherwise `ERR_ROUTE_NOT_PLANNED`); it also requires that the route's `route_date_index` be no earlier than the current clock index (otherwise `ERR_ROUTE_DATE_IN_PAST`) and that the route's `planned_stop_count` not exceed the assigned inspector's `max_daily_route_stops` (otherwise `ERR_ROUTE_CAPACITY_EXCEEDED`). After the day's work an `Inspector` closes a dispatched route, moving it from `DISPATCHED` to `COMPLETED`; closing requires the route to be `DISPATCHED` (otherwise `ERR_ROUTE_NOT_DISPATCHED`).

A `PermitClerk` or an `Inspector` schedules an **inspection** by supplying the `establishment_id`, the assigned `inspector_id`, the `inspection_type` — one of `ROUTINE`, `REINSPECTION`, or `COMPLAINT` — and the `scheduled_index` (a non-negative integer day index). An inspection may optionally name a `route_id` under which it runs (ad-hoc inspections leave it null), and when a `route_id` is supplied the named route's `planned_stop_count` is incremented by one. A reinspection must additionally name a `reinspection_of_id`, and that referenced inspection must be a prior `FINALIZED` inspection of the same establishment; if it is not, scheduling is rejected with `ERR_INVALID_REINSPECTION_TARGET`. The same inspector cannot be booked twice on the same day: if scheduling would place this inspection's `inspector_id` on a `scheduled_index` already occupied by another non-terminal inspection for that inspector, the request is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`. A new inspection begins `SCHEDULED`.

The inspection then walks a lifecycle driven entirely by the `Inspector`. An assigned inspector starts a scheduled inspection, moving it from `SCHEDULED` to `IN_PROGRESS`; starting requires the inspection to be `SCHEDULED` (otherwise `ERR_INSPECTION_NOT_SCHEDULED`), requires the acting inspector's `X-User-ID` to equal the inspection's `inspector_id` (otherwise `ERR_NOT_ASSIGNED_INSPECTOR`), and requires the establishment not to be revoked (otherwise `ERR_ESTABLISHMENT_REVOKED`). From `IN_PROGRESS` the inspector completes the inspection, moving it to `COMPLETED`; completion requires the inspection to be `IN_PROGRESS` (otherwise `ERR_INSPECTION_NOT_IN_PROGRESS`) and recomputes this inspection's scores, critical count, grade, and placard color from its violations as preview values that are not yet promoted onto the establishment.

A completed inspection may be reopened for amendment before it is finalized. Reopening moves an inspection from `COMPLETED` to `AMENDING`; it requires the inspection to be `COMPLETED` (otherwise `ERR_INSPECTION_NOT_COMPLETED`) and increments the inspection's `version` by one. From `AMENDING` the inspector re-completes the inspection back to `COMPLETED`; re-completion requires the inspection to be `AMENDING` (otherwise `ERR_INSPECTION_NOT_AMENDING`) and again recomputes the scores, critical count, grade, and placard color. This `COMPLETED`-to-`AMENDING`-to-`COMPLETED` cycle exists so that violations can be added or removed before the result is locked in. Recording a `Violation` or removing one is only permitted while the inspection is `IN_PROGRESS` or `AMENDING`; attempting to add or remove a violation in any other state is rejected with `ERR_INSPECTION_NOT_EDITABLE`.

### 3.5. Recording Violations and Computing the Two Scores

While an inspection is editable, the `Inspector` records a `Violation` by supplying the `inspection_id` it belongs to, the `fda_code_id` of the cited code, and an optional `corrected_on_site` boolean (defaulting to false) that marks whether the deficiency was fixed during the visit. The cited code must be active: citing a retired code (one whose `is_active` is false) is rejected with `ERR_CODE_RETIRED`. On creation the violation copies its `classification` (`CRITICAL` or `NON_CRITICAL`) from the cited code at citation time, begins with a `resolution_status` of `OPEN`, and has the system compute its `repeat_offense` flag: the flag is true when the same FDA code was cited on a prior finalized inspection of this establishment and that prior citation was left unresolved. An `Inspector` may also delete a violation while its inspection is editable.

Each violation contributes points to two parallel running totals, recorded on the violation itself. Its `demerit_points_observed` is the cited code's `base_demerit_points`, plus the code's `repeat_surcharge_points` when this violation is a repeat offense and zero otherwise. Its `demerit_points_final` is the same observed figure unless the violation was corrected on site, in which case the observed figure is halved and rounded up to the nearest whole point. These per-violation figures are computed and rounded individually before any summation.

Two scores are then produced for the inspection. The `as_observed_score` is a provisional figure that ignores on-site corrections entirely: it is 100 minus the sum of every violation's observed points, clamped so it is never below 0. The `final_score` credits corrections: it is 100 minus the sum of every violation's final points, again clamped so it is never below 0. The final score is the one that drives the grade and the placard and that is promoted to the establishment at finalization. The ordering is pinned and consequential — each violation's points (including the halve-and-ceil for corrected violations) are computed first, then summed, then subtracted from 100, then clamped; summing first and halving afterward would produce a different result. The inspection also records `critical_count`, the number of its violations whose classification is `CRITICAL`.

### 3.6. Grades, Placards, and Closure Triggers

From the `final_score` and the `critical_count` the system assigns the inspection's `grade` and `placard_color`. First a score band is derived from the final score: a final score of at least 90 is band `A`, a final score of at least 80 but below 90 is band `B`, and any final score below 80 is band `C`. Independently, a critical-count cap is derived because each critical violation lowers the best achievable letter: zero critical violations cap at `A`, exactly one caps at `B`, and two or more cap at `C`. The grade is the worse of the score band and the critical cap, where severity orders `A` before `B` before `C` before `CLOSED` and "worse" means the more severe of the two. After that worst-of result is taken, a closure override is applied: the grade becomes `CLOSED` if the critical count is at least 3, or if the final score is below 60. The evaluation order is fixed — compute the score band, compute the critical cap, take the worse of the two, and only then apply the `CLOSED` override. The placard color is paired to the grade: `A` is `GREEN`, `B` is `YELLOW`, `C` is `YELLOW`, and `CLOSED` is `RED`.

When a finalized inspection produces a `CLOSED` grade, the system also determines the closure's `reason_code`, and the two closing conditions are evaluated with the critical-count cause taking precedence: if the critical count is at least 3, the reason is `CRITICAL_THRESHOLD`; otherwise, if the final score is below 60, the reason is `GRADE_C_AUTOCLOSE`; otherwise the reason is `IMMINENT_HEALTH_HAZARD`.

### 3.7. Finalization and Its Cascades

Finalizing an inspection is the pivotal act that promotes a result onto the establishment and fires the downstream cascades. The acting `Inspector` finalizes a completed inspection, moving it from `COMPLETED` to `FINALIZED`. Finalization requires the inspection to be `COMPLETED` (otherwise `ERR_INSPECTION_NOT_COMPLETED`); it requires the supplied `expected_inspection_version` to match the inspection's current `version`, and a mismatch is rejected with `ERR_STALE_INSPECTION_VERSION` before any business logic runs (see §2.8); and it requires that the establishment not be revoked, since an inspection cannot be finalized — nor started — on a revoked establishment, which is rejected with `ERR_ESTABLISHMENT_REVOKED`.

On a successful finalize the inspection's `final_score`, `grade`, and `placard_color` are promoted onto the establishment's `current_score`, `current_grade`, and `current_placard_color`, and the establishment's `open_critical_count` is recomputed across all of its finalized inspections. The inspection's `version` is then incremented by one. Beyond that promotion, three conditional cascades may fire, and the establishment's reinspection schedule is advanced accordingly:

- **Passing reinspection cascade.** If this inspection's `inspection_type` is `REINSPECTION`, its grade is `A` or `B`, and it carries zero critical violations, then the system marks the matching prior `OPEN` violations as `RESOLVED`; and if the establishment is currently `SUSPENDED`, it lifts the establishment's active closure order (moving that closure order to `LIFTED`, clearing `active_closure_order_id`) and returns the establishment to `PERMITTED`.
- **Closure cascade.** If the resulting grade is `CLOSED`, the system creates a `ClosureOrder` whose `reason_code` is set per the closure-trigger rule of §3.6, moves the establishment from `PERMITTED` to `SUSPENDED`, and sets the establishment's `next_reinspection_due_index` to the current clock index plus 14 days.
- **Routine pass cascade.** If this inspection's `inspection_type` is `ROUTINE` and its grade is `A` or `B`, the establishment's `next_reinspection_due_index` is set to the current clock index plus the establishment's `routine_interval_days`.

### 3.8. Closure Orders

A closure order suspends an establishment's permit. Beyond the automatic closure raised at finalization, an `EnforcementOfficer` or a `HealthDirector` may issue a closure order manually — for instance for an imminent health hazard discovered outside the scoring path — by supplying the `establishment_id`, the `triggering_inspection_id` of the finalized inspection behind the closure, and a `reason_code` of `GRADE_C_AUTOCLOSE`, `CRITICAL_THRESHOLD`, or `IMMINENT_HEALTH_HAZARD`. A manually issued closure order begins `ACTIVE`, records its `issued_index` at the current clock index, moves the establishment from `PERMITTED` to `SUSPENDED`, sets the establishment's `active_closure_order_id`, and sets `next_reinspection_due_index` to the current clock index plus 14 days.

An active closure order may be lifted manually by an `EnforcementOfficer` or a `HealthDirector` once corrective action is verified. Lifting moves the closure order from `ACTIVE` to `LIFTED`, returns the establishment from `SUSPENDED` to `PERMITTED`, and clears the establishment's `active_closure_order_id` to null. A closure order also reaches `LIFTED` automatically through the passing-reinspection cascade described above, and reaches the distinct terminal status `VACATED` when an enforcement hearing dismisses the case behind it.

### 3.9. Complaints and Foodborne-Illness Intake

Any of the four roles may file a **complaint**. A `Complaint` is created against an `establishment_id` with a `complaint_type` of `FOODBORNE_ILLNESS`, `SANITATION`, or `OTHER`, and an optional `reported_ill_count` (a non-negative integer of persons reporting illness, defaulting to 0). A new complaint begins `RECEIVED`.

A `PermitClerk` triages a received complaint, moving it from `RECEIVED` to `TRIAGED`; triage requires the complaint to be `RECEIVED` (otherwise `ERR_COMPLAINT_NOT_RECEIVED`) and computes the complaint's `severity_score` and its `priority` band. The severity score is the sum of three weights. A type weight is assigned by complaint type: 40 for `FOODBORNE_ILLNESS`, 15 for `SANITATION`, and 5 for `OTHER`. An illness weight is the reported ill count capped at 10, then multiplied by 4 points each. A risk weight is drawn from the parent establishment's risk category: 0 for `CATEGORY_1`, 5 for `CATEGORY_2`, and 10 for `CATEGORY_3`. From the resulting `severity_score` the `priority` is banded: a score of at least 60 is `URGENT`, a score of at least 30 but below 60 is `PRIORITY`, and any score below 30 is `ROUTINE`.

An `Inspector` dispatches a triaged complaint, supplying the `inspector_id` that will handle it; dispatch requires the complaint to be `TRIAGED` (otherwise `ERR_COMPLAINT_NOT_TRIAGED`) and requires the establishment not to be revoked (otherwise `ERR_ESTABLISHMENT_REVOKED`). Dispatch spawns a new `COMPLAINT`-type inspection in the `SCHEDULED` status, scheduled at the current clock index and assigned to the dispatching inspector, records that inspection's id on the complaint's `linked_inspection_id`, and moves the complaint to `DISPATCHED`. Finally a `PermitClerk` closes a dispatched complaint, moving it from `DISPATCHED` to `CLOSED`; closing requires the complaint to be `DISPATCHED` (otherwise `ERR_COMPLAINT_NOT_DISPATCHED`) and requires that the linked inspection have reached `FINALIZED` (otherwise `ERR_COMPLAINT_INSPECTION_OPEN`).

### 3.10. Enforcement Cases and Hearings

When an establishment contests a closure or owes a penalty, an `EnforcementOfficer` opens an **enforcement case** by supplying the `establishment_id`, the `alleged_penalty_cents` sought (a non-negative integer), and optionally the `closure_order_id` being contested (left null for fine-only cases). A new case begins `OPENED`. From `OPENED` the case forks into one of two divergent paths.

On the hearing path, the `EnforcementOfficer` schedules a hearing by supplying a `hearing_index`; scheduling requires the case to be `OPENED` (otherwise `ERR_CASE_NOT_OPENED`) and requires the `hearing_index` to be no earlier than the current clock index (otherwise `ERR_HEARING_IN_PAST`). Scheduling records the `hearing_index` and moves the case to `HEARING_SCHEDULED`. Once the scheduled day has arrived, the `HealthDirector` issues a `ruling`; ruling requires the case to be `HEARING_SCHEDULED` (otherwise `ERR_CASE_NOT_SCHEDULED`), requires the current clock index to have reached the `hearing_index` (otherwise `ERR_HEARING_NOT_REACHED`), and requires the `ruling` to be one of `UPHELD`, `REDUCED`, or `DISMISSED` (otherwise `ERR_INVALID_RULING`). The ruling is recorded, the case moves to `HEARD`, and the case's `assessed_penalty_cents` is computed from the ruling: a `DISMISSED` ruling assesses 0 cents; a `REDUCED` ruling assesses the alleged penalty multiplied by one half and rounded down to a whole cent; and an `UPHELD` ruling assesses the full alleged penalty. When the ruling is `DISMISSED` and the case names a `closure_order_id`, that closure order is moved to `VACATED`, and if the establishment is `SUSPENDED` with no other active closure it returns to `PERMITTED`. A heard case is then closed by the `EnforcementOfficer`, moving it from `HEARD` to `CLOSED`; closing requires the case to be `HEARD` (otherwise `ERR_CASE_NOT_HEARD`).

On the settle path, the `EnforcementOfficer` settles an open case directly without a hearing, moving it straight from `OPENED` to `CLOSED`; settling requires the case to be `OPENED` (otherwise `ERR_CASE_NOT_OPENED`) and assesses the alleged penalty in full, setting `assessed_penalty_cents` equal to `alleged_penalty_cents` with no reduction and no ruling recorded.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource or drive a state transition return a `200 OK` status code, except deletions, which return `204 No Content`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_index` | Set the logical clock to an integer day index | HealthDirector |
| GET | `/_clock` | Read the current logical clock index | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/fda-food-codes` | Create an FDA Food Code catalog entry | HealthDirector |
| GET | `/fda-food-codes` | List FDA Food Codes | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/fda-food-codes/{codeId}` | Get an FDA Food Code | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/fda-food-codes/{codeId}/retire` | Retire an FDA Food Code | HealthDirector |
| POST | `/inspectors` | Register an inspector | HealthDirector |
| GET | `/inspectors` | List inspectors | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/inspectors/{inspectorId}` | Get an inspector | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/establishments` | Create an establishment | PermitClerk |
| GET | `/establishments` | List establishments | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/establishments/{establishmentId}` | Get an establishment | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| PUT | `/establishments/{establishmentId}` | Update an establishment profile | PermitClerk |
| POST | `/establishments/{establishmentId}/revoke` | Revoke an establishment's permit | HealthDirector |
| POST | `/plan-reviews` | Submit a plan review | PermitClerk |
| GET | `/plan-reviews` | List plan reviews | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/plan-reviews/{planReviewId}` | Get a plan review | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/plan-reviews/{planReviewId}/approve` | Approve a submitted plan review | PermitClerk |
| POST | `/plan-reviews/{planReviewId}/reject` | Reject a submitted plan review | PermitClerk |
| POST | `/plan-reviews/{planReviewId}/resubmit` | Resubmit a rejected plan review | PermitClerk |
| POST | `/permits` | Issue a permit against an approved plan review | PermitClerk |
| GET | `/permits` | List permits | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/permits/{permitId}` | Get a permit | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/inspection-routes` | Create an inspection route | PermitClerk, Inspector |
| GET | `/inspection-routes` | List inspection routes | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/inspection-routes/{routeId}` | Get an inspection route | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/inspection-routes/{routeId}/dispatch` | Dispatch a planned route | Inspector |
| POST | `/inspection-routes/{routeId}/close` | Close a dispatched route | Inspector |
| POST | `/inspections` | Schedule an inspection | PermitClerk, Inspector |
| GET | `/inspections` | List inspections | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/inspections/{inspectionId}` | Get an inspection | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/inspections/{inspectionId}/start` | Start an assigned inspection | Inspector |
| POST | `/inspections/{inspectionId}/complete` | Complete an inspection | Inspector |
| POST | `/inspections/{inspectionId}/reopen` | Reopen a completed inspection for amendment | Inspector |
| POST | `/inspections/{inspectionId}/finalize` | Finalize an inspection | Inspector |
| POST | `/violations` | Record a violation | Inspector |
| GET | `/violations` | List violations | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/violations/{violationId}` | Get a violation | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| DELETE | `/violations/{violationId}` | Remove a violation | Inspector |
| POST | `/closure-orders` | Issue a manual closure order | EnforcementOfficer, HealthDirector |
| GET | `/closure-orders` | List closure orders | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/closure-orders/{closureOrderId}` | Get a closure order | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/closure-orders/{closureOrderId}/lift` | Lift an active closure order | EnforcementOfficer, HealthDirector |
| POST | `/complaints` | File a complaint / foodborne-illness report | PermitClerk, Inspector, EnforcementOfficer, HealthDirector |
| GET | `/complaints` | List complaints | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/complaints/{complaintId}` | Get a complaint | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/complaints/{complaintId}/triage` | Triage a complaint | PermitClerk |
| POST | `/complaints/{complaintId}/dispatch` | Dispatch a triaged complaint into an inspection | Inspector |
| POST | `/complaints/{complaintId}/close` | Close a complaint | PermitClerk |
| POST | `/enforcement-cases` | Open an enforcement case | EnforcementOfficer |
| GET | `/enforcement-cases` | List enforcement cases | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| GET | `/enforcement-cases/{caseId}` | Get an enforcement case | HealthDirector, PermitClerk, Inspector, EnforcementOfficer |
| POST | `/enforcement-cases/{caseId}/schedule-hearing` | Schedule a hearing for an open case | EnforcementOfficer |
| POST | `/enforcement-cases/{caseId}/rule` | Issue a hearing ruling | HealthDirector |
| POST | `/enforcement-cases/{caseId}/settle` | Settle an open case directly | EnforcementOfficer |
| POST | `/enforcement-cases/{caseId}/close` | Close a heard case | EnforcementOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_INSPECTOR` | 403 Forbidden |
| `ERR_ESTABLISHMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_CODE_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTOR_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSURE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MISSING_REJECTION_REASON` | 400 Bad Request |
| `ERR_INVALID_RULING` | 400 Bad Request |
| `ERR_STALE_INSPECTION_VERSION` | 412 Precondition Failed |
| `ERR_ESTABLISHMENT_NOT_PRELICENSE` | 409 Conflict |
| `ERR_ESTABLISHMENT_NOT_PERMITTED` | 409 Conflict |
| `ERR_ESTABLISHMENT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_ESTABLISHMENT_NOT_REVOCABLE` | 409 Conflict |
| `ERR_ESTABLISHMENT_REVOKED` | 409 Conflict |
| `ERR_PLAN_REVIEW_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PLAN_REVIEW_NOT_REJECTED` | 409 Conflict |
| `ERR_PLAN_REVIEW_NOT_APPROVED` | 409 Conflict |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_INSPECTION_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_INSPECTION_NOT_COMPLETED` | 409 Conflict |
| `ERR_INSPECTION_NOT_AMENDING` | 409 Conflict |
| `ERR_INSPECTION_NOT_EDITABLE` | 409 Conflict |
| `ERR_INVALID_REINSPECTION_TARGET` | 409 Conflict |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CODE_RETIRED` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNED` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ROUTE_DATE_IN_PAST` | 409 Conflict |
| `ERR_NO_ACTIVE_CLOSURE_ORDER` | 409 Conflict |
| `ERR_CLOSURE_ORDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_COMPLAINT_NOT_RECEIVED` | 409 Conflict |
| `ERR_COMPLAINT_NOT_TRIAGED` | 409 Conflict |
| `ERR_COMPLAINT_NOT_DISPATCHED` | 409 Conflict |
| `ERR_COMPLAINT_INSPECTION_OPEN` | 409 Conflict |
| `ERR_CASE_NOT_OPENED` | 409 Conflict |
| `ERR_CASE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_CASE_NOT_HEARD` | 409 Conflict |
| `ERR_HEARING_IN_PAST` | 409 Conflict |
| `ERR_HEARING_NOT_REACHED` | 409 Conflict |

# Appraisal Management Company API — Product Requirements Document

## 1. Introduction

An Appraisal Management Company (AMC) sits between mortgage lenders and the independent appraisers who value the properties securing their loans. The AMC must intake appraisal orders from loan-production clients, route each order to a qualified appraiser through a fair rotation policy, hold every party to a turnaround service-level commitment, and run each delivered report through a USPAP/UAD compliance gate before it is released back to the lender. This document specifies the API that orchestrates that entire pipeline.

The work is unusually constraint-heavy because two regulatory pressures cut across the ordinary order workflow. The first is appraiser independence: under Appraiser Independence Requirements (AIR), loan-production staff must be walled off from anything that could influence the valuation — they may place orders and ask for a reconsideration, but they may not pick the appraiser, finalize a compliance review, or open a value-dispute revision. The second is the compliance loop: a failed compliance review must be able to push a report, its assignment, and the parent order all the way back into rework, and the system must be able to climb back out of that loop when the appraiser resubmits. Money flows alongside the workflow — every order carries a fee that is split between the appraiser and the AMC, with the appraiser's share eroded by each revision round and bounded by a floor.

The design goal is a single, internally consistent system of record that an AMC's coordinators, its compliance reviewers, its panel of appraisers, and its lender clients can all act against, with every state change, fee recomputation, and firewall block fully determined by the rules below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API. The entire API is mounted under the `/amc` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `AMCCoordinator`, `ComplianceReviewer`, `Appraiser`, `LenderUser`, and `PlatformAdmin`.

- `AMCCoordinator` is AMC operations staff: order intake, appraiser assignment and rotation, panel management, fee configuration, reconsideration handling, and order completion or cancellation. When `X-User-Role` is `AMCCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow demands it but does not compare it to any entity's `id`.
- `ComplianceReviewer` is the USPAP/UAD compliance reviewer, kept independent of loan production and of order assignment as a segregation-of-duties measure. When `X-User-Role` is `ComplianceReviewer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the actor on a logged firewall event) but does not compare it to any entity's `id`.
- `Appraiser` is a panel appraiser who accepts or declines assignments, schedules the inspection, and submits or resubmits reports; an appraiser can never self-assign. When `X-User-Role` is `Appraiser`, `X-User-ID` is the `id` of the acting `Appraiser`; ownership checks on any resource that references an `Appraiser` compare the resource's appraiser foreign key to `X-User-ID`. In particular, accepting, declining, or submitting against an assignment requires that the assignment's `appraiser_id` equal `X-User-ID`.
- `LenderUser` is a loan-production client user who places orders and requests reconsiderations of value. When `X-User-Role` is `LenderUser`, `X-User-ID` is the `id` of the acting `Lender`; ownership checks on any resource that references a `Lender` compare the resource's lender foreign key to `X-User-ID`. The AIR firewall (described in §2.4) further restricts this role.
- `PlatformAdmin` is a superuser/operator with a hierarchical override across all business operations, plus exclusive access to the test-driving clock endpoint. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry these four pagination fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Appraiser Independence (AIR) Firewall

The AMC operates under Appraiser Independence Requirements, which demand that the loan-production side be structurally prevented from influencing valuation outcomes. The firewall is enforced for the `LenderUser` role on three firewalled operations: appraiser selection (creating an assignment on an order), finalizing a compliance review, and opening a revision request whose `reason_category` is `VALUE_DISPUTE`. When a `LenderUser` attempts any of these, the request is denied with `ERR_AIR_FIREWALL_VIOLATION` (HTTP 403) and a `FirewallEvent` is recorded against the order.

This firewall check is deliberately evaluated **before** the generic authorization check, because it is compliance-critical and the attempt must be logged. Concretely, when the acting role is `LenderUser` on one of the three firewalled endpoints, the firewall specialization supersedes the generic permission error: the actor receives `ERR_AIR_FIREWALL_VIOLATION` rather than `ERR_UNAUTHORIZED`. Any non-`LenderUser` actor who is simply not permitted on those endpoints falls through to the ordinary authorization handling and receives `ERR_UNAUTHORIZED` instead. Note that a revision request is firewalled for `LenderUser` only when the requested category is `VALUE_DISPUTE`; `LenderUser` is in any case not among the roles permitted to open revision requests, so the firewall is the governing path for that role on that endpoint.

A `FirewallEvent` is a lightweight audit record. It captures the `order_id` whose firewall was touched, the `actor_role` of the blocked actor (the value of their `X-User-Role`), a short `blocked_operation` label for the attempted operation (`SELECT_APPRAISER` for appraiser selection, `FINALIZE_COMPLIANCE` for finalizing a compliance review, and `OPEN_VALUE_DISPUTE` for opening a value-dispute revision), and the `error_id` returned to that actor (the string `ERR_AIR_FIREWALL_VIOLATION`). `FirewallEvent` is an audit-only entity: it carries only `id` and `created_at` and is never mutated, so it has neither an `updated_at` field nor a `version` field. All other entities in the system are mutable and carry the full common property set described in §2.6.

### 2.5. Order, Assignment, and Compliance State Propagation

Many transitions in this system are not standalone: completing an order, cancelling an order, accepting an assignment, submitting a report, and finalizing a compliance review all ripple outward and mutate neighboring resources. Whenever a transition's effects reach another resource, that resource's own state, its `updated_at`, and (where it carries one) its `version` are updated as part of the same operation. The order, in particular, advances its `version` by one on each of its own transitions — initial assignment, superseding reassignment, the bubble-up to `IN_PROGRESS` when its assignment is accepted, the bubble-up to `IN_QC` when a report is submitted, the compliance-driven move to either `IN_PROGRESS` or `DELIVERED`, and the coordinator-driven `COMPLETED` or `CANCELLED`.

The most consequential cascade is the compliance-fail loop, a depth-three propagation. When a compliance review finalizes as a failure, it drives the report it reviewed from `UNDER_REVIEW` to `REVISION_REQUESTED`, which in turn drives the order's accepted assignment from `ACCEPTED` to `REVISION`, which in turn reverts the order from `IN_QC` back to `IN_PROGRESS`. The reverse path closes the loop: when the appraiser resubmits, the report moves from `REVISION_REQUESTED` to `RESUBMITTED`, the assignment returns from `REVISION` to `ACCEPTED`, and the order climbs from `IN_PROGRESS` back to `IN_QC`. These cascades are described operation-by-operation in §3; what §2 establishes is that they are server-driven and atomic — a single client request can legitimately change several resources at once, and each affected resource records the change in its own `updated_at` and `version`.

### 2.6. Common Resource Properties

Every mutable resource — `Lender`, `Appraiser`, `Property`, `Order`, `Assignment`, `Report`, `ComplianceReview`, `RevisionRequest`, `ReconsiderationOfValue`, and `FeeSplit` — carries a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification to the resource.
- `version`: an integer that starts at creation and increments by one on every modification. It is the value used for optimistic concurrency control (see §2.8).

As noted in §2.4, `FirewallEvent` is the sole exception: it carries only `id` and `created_at` — it has no `updated_at` and no `version`, because it is written once and never changed.

### 2.7. Monetary Precision and the Fee-Conservation Invariant

All money in this system is expressed in integer cents — `order_fee_cents`, `monthly_fee_budget_cents`, `committed_fee_cents`, `appraiser_fee_cents`, `amc_fee_cents`, `revision_penalty_cents`, `prior_appraised_value_cents`, `appraised_value_cents`, `opinion_of_value_cents`, `requested_value_cents`, and `new_value_cents` are all whole-cent integers. Wherever a fee component is derived by multiplying a fee by a fraction, the result is rounded to whole cents using the round-half-up method. The fee-split computation pins the rounding order: each named component is rounded to whole cents on its own first, and only then are the components combined — never the reverse (see §3.6 for the full derivation).

A standing invariant governs every fee split: the appraiser's share and the AMC's share must always sum to the order's fee. The AMC share is therefore never computed independently; it is always the residual obtained by subtracting `appraiser_fee_cents` from the order's `order_fee_cents`. Any recomputation that changes the appraiser's share must re-derive the AMC's share from this complement so that conservation is preserved exactly.

### 2.8. Optimistic Concurrency Control on Orders

Three order-mutating operations require the caller to prove it is acting on a current view of the order: creating an assignment on the order, cancelling the order, and completing the order. Each of these requests must carry an `expected_order_version` field carrying the client's last observed `version` of the target `Order`. The server compares it to the order's current `version`; if they do not match, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). This `expected_order_version` field is non-optional on these three operations; endpoints not named here do not take a version field.

The reassignment scenario is the motivating case for the assignment-create rule. After an appraiser declines, a coordinator reassigns the order, and the new assignment legitimately supersedes the declined one — but if another writer has already advanced the order's `version` by creating that superseding assignment since the current coordinator last read the order, the current coordinator's create is rejected with `ERR_STALE_ORDER_VERSION`, preventing it from overwriting an assignment it never observed. The rule is purely a stale-version guard: it fires whenever the supplied `expected_order_version` differs from the order's stored `version`, independent of any timing between requests.

### 2.9. Nested Resource Retrieval and Left-to-Right Existence

Several paths address a resource nested under a parent — an order's assignments, an order's fee split, an order's reconsiderations, an order's firewall events, an assignment's reports, a report's compliance reviews, a report's revision requests. Each of these nested-collection GET endpoints returns an array-typed, paginated list response (`response_type` `array`, with the four pagination fields in `meta`), even the order's fee split, which is returned as a single-element array rather than as a bare object. For any such path, the server validates the referenced resources from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the first identifier in the path that does not correspond to an existing resource. A request naming a non-existent order, for example, fails with `ERR_NOT_FOUND` before the server attempts to resolve anything beneath it.

### 2.10. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic:

1. **Authentication** comes first: headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED`.
2. **The AIR firewall** is checked next, ahead of generic authorization, on its three firewalled endpoints, yielding `ERR_AIR_FIREWALL_VIOLATION` for a `LenderUser` and recording a `FirewallEvent` (see §2.4).
3. **Generic authorization** against the role matrix follows, yielding `ERR_UNAUTHORIZED`.
4. **Existence** of all path-referenced resources, left to right, yielding `ERR_NOT_FOUND`.
5. **Eligible-appraiser availability** on assignment creation — the rotation candidate set must be non-empty after filtering, else `ERR_NO_ELIGIBLE_APPRAISER` (see §3.2).
6. **Report-target revisability** on report submission — the assignment must be in an acceptable state and owned by the acting appraiser, else `ERR_ASSIGNMENT_NOT_REVISABLE` (see §3.4).
7. **State legality** — the target resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`.
8. **Optimistic concurrency** — `expected_order_version` must match the order's `version` on the three OCC operations, else `ERR_STALE_ORDER_VERSION`.
9. **Appraiser inspection-window conflict** on accept, else `ERR_APPRAISER_WINDOW_CONFLICT` (see §3.3).
10. **Property inspection-window conflict** on accept, else `ERR_PROPERTY_WINDOW_CONFLICT` (see §3.3).
11. **Inspection-window validity** on accept — end strictly after start, else `ERR_INVALID_WINDOW`.
12. **Second-review requirement** on reconsideration resolution to a changed value, else `ERR_SECOND_REVIEW_REQUIRED` (see §3.7).
13. **Lender monthly budget** on order placement, else `ERR_LENDER_BUDGET_EXCEEDED` (see §3.1).
14. **Field-shape validation** last — required fields present, enums in range, numeric constraints satisfied — else `ERR_INVALID_REQUEST`.

This ordering is normative: a request that violates several rules surfaces the lowest-numbered applicable error. In particular, a mid-flight firewall block (priority 2) surfaces before any permission, existence, or business check; and an `ERR_INVALID_STATE` (priority 7) surfaces before a stale-version rejection (priority 8) when both would apply.

## 3. Business Logic & Workflows

### 3.1. Order Intake, the Lender Panel, and the Monthly Budget

The pipeline begins with three reference entities. A `Lender` is a loan-production client, registered with a `name`, an `approved_panel_appraiser_ids` array (the set of appraiser identities the lender has approved onto its panel — assignment is restricted to this set, and it may be empty), and a `monthly_fee_budget_cents` ceiling that must be at least zero. The lender also exposes a computed `committed_fee_cents`: the sum of `order_fee_cents` across this lender's orders whose status is not `CANCELLED` and whose `placed_at` falls within the current calendar month in UTC. It starts at zero and is recomputed whenever an order is created, an order is cancelled, or a fee split is recomputed. A coordinator may later replace a lender's panel wholesale by supplying a new `approved_panel_appraiser_ids` list.

An `Appraiser` is rostered with a `full_name`, a `license_state` (a two-letter uppercase US state code that must equal a subject property's state for the appraiser to be eligible), and a `base_fee_share_pct` — the fraction of an order's fee the appraiser earns on a clean, on-time, revision-free order before any penalties, which must be greater than 0.0 and at most 1.0. An appraiser's `status` is one of `ACTIVE`, `SUSPENDED`, or `RETIRED`, defaulting to `ACTIVE` at creation. Several appraiser fields are computed and discussed where they are used: `active_assignment_count`, `completed_count`, `on_time_count`, `last_assigned_at`, and `panel_score` (see §3.2 and §3.8). At creation `panel_score` is initialized to `0.0` and is not recomputed at creation; it first takes its blended value only at one of the recompute triggers enumerated in §3.8 (an assignment completion or an appraiser status change). When a coordinator changes an appraiser's `status`, the panel score is recomputed; a move to `SUSPENDED` or `RETIRED` drives that score to zero.

A `Property` is the subject of an appraisal, recorded with a `street_address`, a `state_code` (two-letter uppercase US state code that must match an appraiser's license state for assignment eligibility), and an optional `prior_appraised_value_cents` (null when none is known).

Placing an order is the first lifecycle event. A `LenderUser`, an `AMCCoordinator`, or a `PlatformAdmin` submits a payload naming the `lender_id`, the `property_id`, the `order_fee_cents` (the borrower-paid total the lender pays the AMC for this order, which must be strictly greater than zero), the `product_type`, and an optional `rush` flag (defaulting to false). A `lender_id` or `property_id` that is absent or not a string is rejected with `ERR_INVALID_REQUEST`; a well-formed `lender_id` or `property_id` string that does not resolve to an existing `Lender` or `Property` (lender checked first, then property) is rejected with `ERR_NOT_FOUND`, ahead of the remaining field-shape and budget checks. The `product_type` is one of `URAR_1004`, `CONDO_1073`, or `EXTERIOR_2055`. Before the order is accepted, the lender's monthly budget is checked: the lender's current `committed_fee_cents` plus this order's `order_fee_cents` must not exceed the lender's `monthly_fee_budget_cents` for the current calendar month; if it would, placement is rejected with `ERR_LENDER_BUDGET_EXCEEDED`.

On successful placement the order enters `PLACED`, its `placed_at` is stamped from the server clock, and its turnaround `sla_hours` is computed from the product type and rush flag (see §3.9). The order's `status` ranges over `PLACED`, `ASSIGNED`, `IN_PROGRESS`, `IN_QC`, `DELIVERED`, `COMPLETED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. Placement also creates exactly one `FeeSplit` for the order in its provisional form (see §3.6) and increases the lender's `committed_fee_cents` by the order's `order_fee_cents`. The order's `appraised_value_cents` remains null until the report is first delivered.

### 3.2. Assignment and the Rotation Selector

A coordinator assigns an order by asking the server to pick an appraiser — appraisers are never named by the caller and can never self-assign. The request carries only `expected_order_version`; the server runs the rotation selector and sets the chosen appraiser. Initial assignment is permitted only when the order is in `PLACED`, the supplied `expected_order_version` matches the order's `version`, and at least one eligible appraiser exists. It creates an `Assignment` in `OFFERED` whose `appraiser_id` is the selector's pick, copies the order's `sla_hours` onto the assignment's own `sla_hours`, advances the order from `PLACED` to `ASSIGNED`, and increments the order's `version` by one.

Reassignment reuses the same capability after a decline or cancel. It is permitted only when the order is already in `ASSIGNED`, the order's current latest assignment is in `DECLINED` or `CANCELLED`, the supplied `expected_order_version` matches the order's `version`, and at least one eligible appraiser exists once appraisers already declined on this order are excluded. It creates a superseding `Assignment` in `OFFERED` whose `supersedes_assignment_id` points at the prior assignment, leaves the order in `ASSIGNED` (an `ASSIGNED → ASSIGNED` self-transition), and increments the order's `version` by one. The first assignment on an order has a null `supersedes_assignment_id`. The stale-order guard described in §2.8 applies to both the initial and superseding cases.

The **rotation selector** decides who gets the work. It first builds a candidate set of appraisers, admitting an appraiser only when all of the following hold: the appraiser's `status` is `ACTIVE`; the appraiser's `license_state` equals the subject property's `state_code`; the appraiser's `id` is a member of the lender's `approved_panel_appraiser_ids`; the appraiser's `id` is not among the appraisers who have already declined an assignment on this order; and the appraiser's `active_assignment_count` is strictly less than the maximum active load of five concurrent assignments. If the candidate set is empty after this filter, assignment fails with `ERR_NO_ELIGIBLE_APPRAISER`.

Among candidates, the selector ranks by `panel_score` from highest to lowest. Ties are broken in a fixed cascade: first by the fewest `active_assignment_count` (lowest first, to balance load); then, still tied, by the oldest `last_assigned_at` (earliest first, with an appraiser who has never been assigned — a null `last_assigned_at` — ordered ahead of any who have); and then, still tied, by the earliest `created_at`. The selector never uses the `id` as a tie-break. The first candidate under this ordering is selected.

### 3.3. Acceptance, Decline, and Inspection-Window Scheduling

An offered assignment awaits the appraiser's decision. The assignment's `status` ranges over `OFFERED`, `ACCEPTED`, `REVISION`, `COMPLETED`, `DECLINED`, and `CANCELLED`, with `COMPLETED`, `DECLINED`, and `CANCELLED` terminal; it begins at `OFFERED`. The acting appraiser must be the assignment's own `appraiser_id`; on accept and decline this ownership check is enforced ahead of the state-legality check and a mismatch is rejected with `ERR_UNAUTHORIZED` (on report submission the ownership check is instead folded into the priority-6 `ERR_ASSIGNMENT_NOT_REVISABLE` check).

Accepting moves the assignment from `OFFERED` to `ACCEPTED`. The appraiser supplies the scheduled on-site inspection window as `inspection_start` and `inspection_end`. Acceptance stamps `accepted_at` from the server clock, persists the two window endpoints, increments the appraiser's `active_assignment_count`, sets the appraiser's `last_assigned_at` to this assignment's `created_at`, and cascades the order: an order in `PLACED` or `ASSIGNED` advances to `IN_PROGRESS` (incrementing the order's `version`).

Three window checks guard acceptance, and they are evaluated in this order. First, the window must not collide with another inspection window of the **same appraiser**. Treat each window as the half-open interval from its start up to but not including its end, and apply a sixty-minute travel buffer: two windows of the same appraiser collide when the later window starts strictly less than sixty minutes after the earlier window ends — that is, when the earlier window's end plus sixty minutes is strictly later than the later window's start. Only the appraiser's assignments in `ACCEPTED` or `REVISION` are considered. A collision is rejected with `ERR_APPRAISER_WINDOW_CONFLICT`. Second, the window must not collide with another inspection window on the **same property**; here the window is treated as a closed interval that includes both endpoints, with no buffer, so even a boundary touch is a conflict, again considering only `ACCEPTED` or `REVISION` assignments. A collision is rejected with `ERR_PROPERTY_WINDOW_CONFLICT`. Third, the window itself must be valid: `inspection_end` must be strictly after `inspection_start`, else `ERR_INVALID_WINDOW`.

Declining moves the assignment from `OFFERED` to `DECLINED`. The order stays in `ASSIGNED`, awaiting reassignment; no appraiser counters change. A declined or cancelled assignment is what licenses the superseding reassignment described in §3.2.

### 3.4. Report Submission and Resubmission

Once an assignment is accepted, the appraiser submits the appraisal report against it. There is exactly one `Report` per assignment: the first submission creates it, and any later resubmission supersedes the same report in place — same `id`, with `version` incrementing — rather than creating a new row. The submission payload carries the `opinion_of_value_cents` (the appraiser's opinion of value for the subject, strictly greater than zero), the `uad_condition_rating` (one of `C1`, `C2`, `C3`, `C4`, `C5`, `C6`), the `uad_quality_rating` (one of `Q1`, `Q2`, `Q3`, `Q4`, `Q5`, `Q6`), and the `comparable_count` (the number of comparable sales included, at least zero). The report also carries `assignment_id` (the assignment whose work it submits) and a `submitted_at` stamp set from the server clock on each submission or resubmission. The report's `status` ranges over `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `RESUBMITTED`, `ACCEPTED`, and `REJECTED`, with `ACCEPTED` and `REJECTED` terminal.

A submission is only honored when its target assignment is in `ACCEPTED` or `REVISION` status and that assignment belongs to the acting appraiser; otherwise it is rejected with `ERR_ASSIGNMENT_NOT_REVISABLE`. The first submission creates the report in `SUBMITTED` and cascades the order from `IN_PROGRESS` to `IN_QC` (incrementing the order's `version`).

A resubmission applies when the report is currently in `REVISION_REQUESTED`: it supersedes the report in place, advancing it to `RESUBMITTED`, marks the open revision request as `RESOLVED`, and runs the revision-loop close — the assignment returns from `REVISION` to `ACCEPTED`, and the order climbs from `IN_PROGRESS` back to `IN_QC`. This is the cyclic revision loop in its closing direction (see §3.5 for the opening direction). The report-submission endpoint returns `201 Created` for both the first submission and every resubmission (the resubmission response carries the superseded report in its `data` field), even though a resubmission mutates the existing report in place rather than creating a new row.

### 3.5. Compliance Review, Findings, and the Revision Cascade

A submitted or resubmitted report is sent to compliance. A `ComplianceReviewer` (or a `PlatformAdmin`) opens a review on a report that is in `SUBMITTED` or `RESUBMITTED`; this creates a `ComplianceReview` in `PENDING` and moves the report to `UNDER_REVIEW`. Each open of a review on a resubmitted report creates a new `ComplianceReview`. At creation the review snapshots two booleans from the report: `uspap_comp_minimum_met` is true exactly when the report's `comparable_count` is at least the USPAP minimum of three comparable sales, and `uad_ratings_valid` is true exactly when both the `uad_condition_rating` and the `uad_quality_rating` fall within their allowed UAD enumerations. The review records its disposition in `outcome`, one of `PENDING`, `PASS`, `CONDITIONAL`, or `FAIL`, beginning at `PENDING`; `PASS`, `CONDITIONAL`, and `FAIL` are terminal. The review also references its `report_id`.

Finalization, performed by a `ComplianceReviewer` or `PlatformAdmin`, supplies optional `finding_codes` — reviewer-captured USPAP/UAD finding codes — and is the fork that decides delivery versus rework. It is defined only from `PENDING`. The outcome is determined from the snapshot and the supplied findings, with three mutually exclusive branches of equal weight:

- **PASS** results when both snapshot booleans are true and `finding_codes` is empty. The outcome becomes `PASS`, the report advances to `ACCEPTED`, and the order cascades from `IN_QC` to `DELIVERED`. On that delivery the order's `appraised_value_cents` is set to the report's `opinion_of_value_cents`, and the order's `version` increments.
- **CONDITIONAL** results when both snapshot booleans are true and `finding_codes` is non-empty but every code in it is a non-USPAP advisory code. The outcome becomes `CONDITIONAL`, and the report and order cascade identically to the PASS branch — report to `ACCEPTED`, order from `IN_QC` to `DELIVERED` with `appraised_value_cents` set to the report's `opinion_of_value_cents` and the order's `version` incremented. A finding code counts as a USPAP code exactly when it begins with the prefix `USPAP` (compared case-insensitively); any code with a different prefix is treated as a non-USPAP advisory code.
- **FAIL** results when either snapshot boolean is false, or when `finding_codes` contains at least one USPAP code. The outcome becomes `FAIL`. A failure creates a `RevisionRequest` with origin `COMPLIANCE` in status `OPEN` and `reason_category` `USPAP_DEFICIENCY`, then runs the depth-three compliance-fail cascade: the report moves from `UNDER_REVIEW` to `REVISION_REQUESTED`, the assignment moves from `ACCEPTED` to `REVISION` (incrementing its `revision_round` by one), and the order reverts from `IN_QC` to `IN_PROGRESS` (incrementing the order's `version`). Because the assignment entered a revision round, the fee split's revision penalty is recomputed and the appraiser and AMC shares are re-split with conservation preserved (see §3.6).

Compliance review and finalization are firewalled operations: a `LenderUser` attempting to finalize is blocked with `ERR_AIR_FIREWALL_VIOLATION` and a logged `FirewallEvent`, per §2.4.

A revision can also be opened manually. An `AMCCoordinator`, `ComplianceReviewer`, or `PlatformAdmin` may open a `RevisionRequest` on a report by supplying a `reason_category`, one of `USPAP_DEFICIENCY`, `UAD_DEFICIENCY`, `DATA_CORRECTION`, or `VALUE_DISPUTE`. Every revision request records an `origin` of either `COMPLIANCE` (cascaded from a failed review) or `MANUAL` (coordinator- or reviewer-initiated), and a `status` of `OPEN` or `RESOLVED` that begins at `OPEN`. A manual revision request may be opened only while the target report is in `SUBMITTED`, `RESUBMITTED`, or `UNDER_REVIEW` (otherwise the request is rejected with `ERR_INVALID_STATE`). A manual revision request is created with origin `MANUAL` in `OPEN`, and it drives the same head-of-cascade as a compliance failure: the report moves to `REVISION_REQUESTED`, which cascades the assignment from `ACCEPTED` to `REVISION` and the order from `IN_QC` to `IN_PROGRESS` (the assignment and order legs of the cascade fire only when the assignment is currently `ACCEPTED` and the order currently `IN_QC`, and the fee split's revision penalty is recomputed when they do). The `VALUE_DISPUTE` category is the firewall-protected one: a `LenderUser` may never open a value-dispute revision and is blocked with `ERR_AIR_FIREWALL_VIOLATION` and a logged `FirewallEvent`.

An assignment moves to `REVISION` only while an `OPEN` revision request exists for its report; that revision round is closed when the appraiser resubmits and the open request transitions to `RESOLVED`, as described in §3.4. The revision loop is genuinely cyclic — an assignment may pass through `ACCEPTED → REVISION → ACCEPTED` repeatedly, incrementing `revision_round` on each re-open.

### 3.6. The Fee Split

Every order owns exactly one `FeeSplit`, created in its provisional form when the order is placed. The split records a `variant` of either `PROVISIONAL` (computed at placement) or `FINAL` (computed at completion), the `appraiser_fee_cents`, the `amc_fee_cents`, and the cumulative `revision_penalty_cents` shifted from the appraiser to the AMC across revision rounds. It also references its `order_id`. Because the appraiser's base depends on the assigned appraiser's `base_fee_share_pct` and no appraiser is yet selected at placement (the rotation selector runs only when the assignment is created, §3.2), the split as first created at placement carries `appraiser_fee_cents` of 0, `amc_fee_cents` equal to the full `order_fee_cents`, and `revision_penalty_cents` of 0, with its `variant` reading `PROVISIONAL`; its appraiser and AMC shares are populated by the recompute that runs when the order's appraiser is assigned (see below).

The split is computed as a waterfall over the order's fee, in integer cents, with each named component independently rounded half-up to whole cents before the components are combined. First, the **base** is the order's `order_fee_cents` multiplied by the assigned appraiser's `base_fee_share_pct`, rounded half-up to whole cents. Second, a **rush premium** applies only when the order's `rush` flag is set: it is the `order_fee_cents` multiplied by the rush premium fraction of ten percent, rounded half-up to whole cents; when the order is not a rush, the rush premium is zero. The gross appraiser amount is the base plus the rush premium. Third, the **revision penalty** is accumulated per revision round: for each completed revision round on the assignment, a flat penalty equal to the `order_fee_cents` multiplied by the revision-penalty fraction of five percent — rounded half-up to whole cents for that one round — is added to the running penalty, and the per-round amounts are summed to give `revision_penalty_cents` (the penalty is computed per round and then summed, not by multiplying the count once). The appraiser's share is then the gross appraiser amount minus the accumulated penalty, but never below the appraiser floor of 5000 cents — the share is the larger of those two values. Finally, the AMC's share is the conserved residual: the order's `order_fee_cents` minus the appraiser's share.

The split has two variants. The **provisional** variant is the one created at placement, before any revision, when the assignment's `revision_round` is zero: the penalty is zero, only the gross appraiser amount applies, and the `variant` field reads `PROVISIONAL`. The **final** variant is computed when the order completes: the penalty reflects the assignment's final `revision_round`, and the `variant` field reads `FINAL`. The two variants differ in cents whenever the order went through one or more revision rounds. The split is recomputed at these moments: at placement (provisional, with the 0/full shares described above before any appraiser exists); when the order's appraiser is assigned, which re-derives the provisional appraiser and AMC shares from the chosen appraiser's `base_fee_share_pct` while leaving the `variant` as `PROVISIONAL`; on each assignment revision (penalty recompute); and at completion (final). A reconsideration that changes the delivered value also triggers a fee-split recompute (see §3.7).

### 3.7. Reconsideration of Value

After an order is delivered, a lender may contest the appraised value. A `LenderUser`, `AMCCoordinator`, or `PlatformAdmin` opens a `ReconsiderationOfValue` against an order, supplying the `requested_value_cents` the requester contends is supportable (strictly greater than zero). A reconsideration may be opened only when the order is in `DELIVERED` or `COMPLETED` and its `appraised_value_cents` is non-null; in any other state the request is rejected with `ERR_INVALID_STATE`. At creation the system computes the `value_delta_pct`: the absolute difference between the `requested_value_cents` and the order's delivered `appraised_value_cents`, divided by that delivered value, multiplied by one hundred, and rounded half-up to two decimal places. From it the system derives `requires_second_review`, which is true exactly when the `value_delta_pct` is strictly greater than the reconsideration delta threshold of ten percent; this flag gates whether a value change demands a second compliance review. The reconsideration's `resolution` is one of `REQUESTED`, `UNDER_REVIEW`, `VALUE_CHANGED`, or `VALUE_UPHELD`, beginning at `REQUESTED`, with `VALUE_CHANGED` and `VALUE_UPHELD` terminal. It also references its `order_id` and carries a `new_value_cents` that stays null unless the reconsideration resolves to a changed value.

A coordinator moves the reconsideration into review, advancing `resolution` from `REQUESTED` to `UNDER_REVIEW`; this is permitted only while the owning order is still in `DELIVERED`. Resolving an under-review reconsideration is a branching fork with divergent effects:

- **Value changed.** When the coordinator supplies a `new_value_cents` present and strictly greater than zero, the reconsideration resolves to `VALUE_CHANGED`. If `requires_second_review` is true, this branch additionally demands that a second, post-delivery `ComplianceReview` on the order's report be in `PASS` or `CONDITIONAL`; the requirement is satisfied exactly when at least two of the compliance reviews across the order's reports are in `PASS` or `CONDITIONAL` (the first such passing review is the one that originally delivered the order, so a genuinely additional passing review is needed). If no such passing second review exists, the resolution is rejected with `ERR_SECOND_REVIEW_REQUIRED`. On success the order's `appraised_value_cents` is set to the `new_value_cents`, and that change cascades a fee-split recompute (a depth-two effect) that bumps the fee split's `version` while leaving its existing `variant` unchanged.
- **Value upheld.** When the coordinator supplies no `new_value_cents`, the reconsideration resolves to `VALUE_UPHELD`. The value does not change and no fee-split recompute occurs.

An order cannot be completed while it has an open contest. Completion (see §3.8) is blocked while any reconsideration on the order is in `REQUESTED` or `UNDER_REVIEW`.

### 3.8. Order Completion, Cancellation, and Appraiser Scoring

A coordinator completes a delivered order. Completion is permitted only when the order is in `DELIVERED`, no reconsideration on the order sits in `REQUESTED` or `UNDER_REVIEW`, and the supplied `expected_order_version` matches the order's `version`. It advances the order from `DELIVERED` to `COMPLETED`, advances the order's accepted assignment from `ACCEPTED` to `COMPLETED`, and increments the order's `version`. On the assignment's completion, its `actual_turnaround_hours` is computed (the chronological elapsed time from acceptance to completion; see §3.9). The owning appraiser's counters are then refreshed: `active_assignment_count` is decremented (the conserved active load), and `completed_count`, `on_time_count`, `last_assigned_at`, and `panel_score` are recomputed. Finally the fee split is finalized in its `FINAL` variant.

A coordinator may cancel a non-terminal order — one in `PLACED`, `ASSIGNED`, `IN_PROGRESS`, or `IN_QC` — provided the supplied `expected_order_version` matches the order's `version`. Cancellation advances the order to `CANCELLED` and runs several cascades: each of the order's non-terminal assignments — those in `OFFERED`, `ACCEPTED`, or `REVISION` — cascades to `CANCELLED` and the owning appraiser's `active_assignment_count` is decremented (preserving the conserved count); any non-terminal report on a cancelled order — that is, any report whose status is neither `ACCEPTED` nor `REJECTED` — cascades to `REJECTED`; the fee split is zeroed, with `appraiser_fee_cents` and `amc_fee_cents` both set to zero (its `revision_penalty_cents` and `variant` are left as they stand); and the lender's `committed_fee_cents` is recomputed so this order drops out of the current-month commitment. The order's `version` increments. An offered, accepted, or in-revision assignment that is cancelled by this order cascade moves to `CANCELLED`; only an assignment that was active (in `ACCEPTED` or `REVISION`) decrements the appraiser's active count, since an offered assignment was never counted as active.

The **panel score** is the appraiser's weighted rotation-ranking score, a number in the range zero to one, recomputed on every assignment completion and on every appraiser status change, and read by the rotation selector at assignment time. When the appraiser's `status` is anything other than `ACTIVE`, the panel score is zero. Otherwise it is a weighted blend of three rates. The **completion rate** is the appraiser's `completed_count` divided by the greater of one and the sum of `completed_count` and `active_assignment_count`. The **on-time rate** is the appraiser's `on_time_count` divided by the greater of one and `completed_count`. The **load factor** is one minus the smaller of one and the appraiser's `active_assignment_count` divided by the maximum active load of five — so a fully loaded appraiser contributes a load factor of zero and an idle one contributes one. The panel score is then the completion rate weighted by 0.4, plus the on-time rate weighted by 0.3, plus the load factor weighted by 0.3, with the final sum rounded half-up to four decimal places. The supporting counters feed this score: `completed_count` is the number of this appraiser's assignments in `COMPLETED`, and `on_time_count` is the number of those completed assignments whose `actual_turnaround_hours` is at most the assignment's `sla_hours`. The `active_assignment_count` is the number of this appraiser's assignments whose status is not `DECLINED`, `CANCELLED`, or `COMPLETED` — a conserved quantity, incremented when an assignment is accepted and decremented on cascade-cancel and on completion. The `last_assigned_at` is the `created_at` of the most recent assignment this appraiser accepted, or null if none, and serves as a rotation tie-break ordering oldest first.

### 3.9. Turnaround SLA: Projected and Actual

The turnaround commitment has two faces. At placement the **projected** SLA is set on the order's `sla_hours` by a table lookup over the product type, shortened for rush: the base SLA is 120 hours for `URAR_1004`, 96 hours for `CONDO_1073`, and 72 hours for `EXTERIOR_2055`; when the order's `rush` flag is set, the projected SLA is the base less the rush shortening of 48 hours, and otherwise it is the base unchanged. The order's `sla_hours` is fixed once placed, and the assignment copies it onto its own `sla_hours` at assignment creation as the clock it will be measured against.

At completion the **actual** turnaround is computed on the assignment's `actual_turnaround_hours`: the whole-hours elapsed from the assignment's `accepted_at` to the completion clock time, floored to a whole number of hours. An assignment is on time exactly when its `actual_turnaround_hours` is at most its `sla_hours`; equivalently, an SLA breach occurs exactly when the `actual_turnaround_hours` is strictly greater than the `sla_hours`, so an actual turnaround equal to the SLA counts as on time. The on-time determination is what feeds the appraiser's `on_time_count` and, through it, the panel score.

For deterministic SLA and turnaround arithmetic, a `PlatformAdmin` may pin the server clock to a fixed UTC instant by supplying a `to_iso8601` value; once pinned, the server returns that instant for all subsequent `placed_at`, `accepted_at`, and completion timestamps. This is an admin-only test-driving capability with no business state transition of its own.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including state transitions such as accept, decline, finalize, complete, cancel, and resolve — return `200 OK`. The clock-pinning capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/amc/lenders` | Register a lender (loan-production client) | `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/lenders/{id}` | Fetch a lender with current-month committed fees | `AMCCoordinator`, `PlatformAdmin`, `LenderUser` |
| PATCH | `/amc/lenders/{id}/panel` | Set the lender's approved appraiser panel | `AMCCoordinator`, `PlatformAdmin` |
| POST | `/amc/appraisers` | Add an appraiser to the AMC roster | `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/appraisers/{id}` | Fetch an appraiser with counters and panel score | `AMCCoordinator`, `PlatformAdmin`, `ComplianceReviewer`, `Appraiser` |
| POST | `/amc/appraisers/{id}/status` | Change an appraiser's panel status | `AMCCoordinator`, `PlatformAdmin` |
| POST | `/amc/properties` | Create a subject property | `AMCCoordinator`, `PlatformAdmin`, `LenderUser` |
| GET | `/amc/properties/{id}` | Fetch a property | `AMCCoordinator`, `PlatformAdmin`, `LenderUser` |
| POST | `/amc/orders` | Place an appraisal order | `LenderUser`, `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/orders` | List orders, filterable by `lender_id`, `property_id`, and/or `status` query parameters | `AMCCoordinator`, `PlatformAdmin`, `LenderUser` |
| GET | `/amc/orders/{id}` | Fetch an order | `AMCCoordinator`, `PlatformAdmin`, `LenderUser` |
| POST | `/amc/orders/{id}/assignments` | Assign/reassign the order via the rotation selector | `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/orders/{id}/assignments` | List a given order's assignments | `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/orders/{id}/fee-split` | Fetch the order's fee split | `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/orders/{id}/reconsiderations` | List the order's reconsiderations | `AMCCoordinator`, `PlatformAdmin`, `LenderUser` |
| GET | `/amc/orders/{id}/firewall-events` | List AIR firewall events for the order | `AMCCoordinator`, `PlatformAdmin` |
| POST | `/amc/orders/{id}/complete` | Complete a delivered order; finalize fees and counters | `AMCCoordinator`, `PlatformAdmin` |
| POST | `/amc/orders/{id}/cancel` | Cancel a non-terminal order; cascade | `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/assignments` | List assignments, filterable by `appraiser_id`, `order_id`, `supersedes_assignment_id`, and/or `status` query parameters | `AMCCoordinator`, `PlatformAdmin`, `Appraiser` |
| GET | `/amc/assignments/{id}` | Fetch an assignment | `AMCCoordinator`, `PlatformAdmin`, `Appraiser` |
| POST | `/amc/assignments/{id}/accept` | Accept and schedule the inspection window | `Appraiser` |
| POST | `/amc/assignments/{id}/decline` | Decline the assignment | `Appraiser` |
| POST | `/amc/assignments/{id}/reports` | Submit or resubmit the appraisal report | `Appraiser` |
| GET | `/amc/assignments/{id}/reports` | List the assignment's reports | `AMCCoordinator`, `PlatformAdmin`, `ComplianceReviewer`, `Appraiser` |
| GET | `/amc/reports/{id}` | Fetch a report | `AMCCoordinator`, `PlatformAdmin`, `ComplianceReviewer`, `Appraiser` |
| POST | `/amc/reports/{id}/compliance-reviews` | Open a USPAP/UAD compliance review | `ComplianceReviewer`, `PlatformAdmin` |
| GET | `/amc/reports/{id}/compliance-reviews` | List the report's compliance reviews | `AMCCoordinator`, `PlatformAdmin`, `ComplianceReviewer` |
| POST | `/amc/reports/{id}/revision-requests` | Open a manual revision request on a report | `AMCCoordinator`, `ComplianceReviewer`, `PlatformAdmin` |
| GET | `/amc/reports/{id}/revision-requests` | List the report's revision requests | `AMCCoordinator`, `PlatformAdmin`, `ComplianceReviewer`, `Appraiser` |
| GET | `/amc/compliance-reviews/{id}` | Fetch a compliance review | `AMCCoordinator`, `PlatformAdmin`, `ComplianceReviewer` |
| POST | `/amc/compliance-reviews/{id}/finalize` | Finalize the review; drive delivery vs revision | `ComplianceReviewer`, `PlatformAdmin` |
| POST | `/amc/orders/{id}/reconsiderations` | Open a reconsideration of value on a delivered order | `LenderUser`, `AMCCoordinator`, `PlatformAdmin` |
| GET | `/amc/reconsiderations/{id}` | Fetch a reconsideration | `AMCCoordinator`, `PlatformAdmin`, `LenderUser` |
| POST | `/amc/reconsiderations/{id}/start-review` | Move a reconsideration into review | `AMCCoordinator`, `PlatformAdmin` |
| POST | `/amc/reconsiderations/{id}/resolve` | Resolve a reconsideration (value changed or upheld) | `AMCCoordinator`, `PlatformAdmin` |
| POST | `/amc/_clock/set_current_utc` | Pin the server clock for deterministic time math | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_AIR_FIREWALL_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NO_ELIGIBLE_APPRAISER` | 422 |
| `ERR_ASSIGNMENT_NOT_REVISABLE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_APPRAISER_WINDOW_CONFLICT` | 409 |
| `ERR_PROPERTY_WINDOW_CONFLICT` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_SECOND_REVIEW_REQUIRED` | 409 |
| `ERR_LENDER_BUDGET_EXCEEDED` | 422 |
| `ERR_INVALID_REQUEST` | 422 |

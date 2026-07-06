# Event Parade Permit API — Product Requirements Document

## 1. Introduction

Municipalities that host parades, street festivals, foot races, and rallies face a coordination problem that no single office can solve alone. A single large event can close several road corridors, place tens of thousands of people onto a park or plaza, and draw simultaneously on police, fire, emergency-medical, and public-works resources — all while a second sponsor is eyeing the very same venue for the very same weekend. This API is the system of record for that negotiation. It lets an event sponsor file a permit application, lay out a road-closure route plan, and shepherd it through a mandatory four-department review, while giving the municipal permit office the levers it needs to accept insurance, hold a cleanup deposit, impose conditions, issue the permit, and settle costs after the event.

The platform is built around a small number of hard truths. An event may not be booked onto a venue whose occupancy window (padded by a mandatory setup-and-teardown buffer) collides with another live application. A road corridor may not be closed twice with insufficient clear time between closures. Every one of the four reviewing departments holds a veto, and any single veto sinks the permit outright; conversely, a permit is only conditionally approved once all four departments have signed off. Money flows in two directions — a fixed application fee plus a staffing cost-recovery charge that is first estimated from planned staffing and later trued-up against actual logged hours, and a cleanup deposit that is partially forfeited or fully refunded depending on the after-action assessment. The sections that follow specify the global contract every endpoint honors, the business logic and lifecycle of each entity, the full endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or its value is not a recognized, well-formed identifier/role, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the headers are present and valid but the caller's role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles, spelled precisely as follows: `Applicant`, `DepartmentReviewer`, and `PermitOfficer`.

An `Applicant` is the event sponsor. It files applications, edits drafts, builds the route plan, submits insurance and deposit records, acknowledges conditions, submits for review, and cancels. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that references an `Applicant` compare the resource's foreign-key field to `X-User-ID`. Concretely, the owning applicant of a permit application is recorded in `applicant_user_id`, and every applicant-restricted action on that application verifies that `X-User-ID` equals `applicant_user_id`; a mismatch is rejected with `ERR_NOT_APPLICATION_OWNER` (HTTP 403).

A `DepartmentReviewer` is a police, fire, EMS, or public-works reviewer who acts on the one department review that matches their department. When `X-User-Role` is `DepartmentReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Instead, `X-User-ID` encodes the reviewer's department context, and the server compares that department against the `department` of the review being acted upon; a mismatch is rejected with `ERR_DEPARTMENT_MISMATCH` (HTTP 403).

A `PermitOfficer` is the municipal officer who owns venues and closure schedules, accepts or rejects insurance, issues permits, opens and finalizes debriefs, and advances the logical clock. When `X-User-Role` is `PermitOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The officer role is deliberately segregated from filing reviews and from being the applicant — an officer runs the approval workflow but does not cast department votes.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, drawn from the server's real wall-clock time independently of the logical `EventClock` (which governs only resource fields such as `created_at` and `updated_at`).
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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0 and has a minimum of 0. List results are ordered by `created_at` in ascending order (oldest first). Each list response reports the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the total number of matching records before pagination is applied and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id`, which is a UUID with no type prefix. All timestamps — including `created_at` and `updated_at` — are ISO 8601 UTC values with three fractional digits.

Most entities carry the full complement of common fields: `id`, `created_at`, `updated_at`, and an integer `version` that begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource. Whenever a resource is mutated, its `updated_at` is refreshed to the current logical time and its `version` advances. The `EventClock` is the sole exception: it is a system configuration singleton that carries only its `current_utc` field and does not expose `created_at`, `updated_at`, or `version`.

### 2.5. Nested Resource Retrieval and Path Validation

Many resources are addressed through nested paths — for example, a route segment, department review, condition, insurance certificate, deposit, or debrief beneath a specific application. Path parameters are validated left to right. The parent application is resolved first; if it does not exist, the request fails with `ERR_APPLICATION_NOT_FOUND` (HTTP 404) before any child is examined. Only then is the child resolved, and it must genuinely belong to that parent. A route segment that does not exist under the named application yields `ERR_SEGMENT_NOT_FOUND`; a review yields `ERR_REVIEW_NOT_FOUND`; an insurance certificate yields `ERR_COI_NOT_FOUND`; a condition yields `ERR_CONDITION_NOT_FOUND`; a deposit yields `ERR_DEPOSIT_NOT_FOUND`; a debrief yields `ERR_DEBRIEF_NOT_FOUND`. References to a missing venue, closure schedule, or applicant yield `ERR_VENUE_NOT_FOUND`, `ERR_CLOSURE_SCHEDULE_NOT_FOUND`, and `ERR_APPLICANT_NOT_FOUND` respectively. All not-found conditions return HTTP 404.

### 2.6. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Header presence and validity is checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Role authorization is checked next (`ERR_UNAUTHORIZED`). Path-resource existence and correct parentage is checked third (the various not-found errors above). Application ownership for applicant-restricted actions (`ERR_NOT_APPLICATION_OWNER`) is checked fourth. Resource-state correctness for the requested transition is checked fifth (for example `ERR_APPLICATION_NOT_DRAFT`, `ERR_APPLICATION_NOT_UNDER_REVIEW`, `ERR_APPLICATION_NOT_APPROVABLE`, `ERR_APPLICATION_NOT_ISSUED`, `ERR_APPLICATION_NOT_CANCELLABLE`, `ERR_REVIEW_NOT_PENDING`, `ERR_COI_NOT_SUBMITTED`, `ERR_CONDITION_NOT_PROPOSED`, `ERR_DEBRIEF_NOT_OPEN`). Department-match for review actions (`ERR_DEPARTMENT_MISMATCH`) is checked sixth. Only after those gates pass are the operation-specific business rules evaluated, in the order laid out through §3: the empty-route-plan check, the capacity check, the venue double-booking check, the closure-conflict check, the suspended-schedule check, the COI expiry and coverage checks, the deposit-underfunded check, the issuance-readiness checks, the veto-reason check, and finally the time-window well-formedness check. Where two checks guard the same endpoint, the earlier one in this ordering surfaces first and masks the later one.

### 2.7. Venue Occupancy, Buffers, and Double-Booking

A `Venue` models a park, plaza, stadium, or street corridor and carries a human-readable `name`, a `venue_type` that is one of `PARK`, `PLAZA`, `STADIUM`, or `STREET_CORRIDOR`, a `max_capacity` giving the maximum peak occupants the venue may lawfully hold at once, and a `setup_buffer_minutes` value. A venue also carries a `status` of `ACTIVE` or `DECOMMISSIONED`; it is `ACTIVE` at creation and moves to `DECOMMISSIONED` only via the decommission action.

The `setup_buffer_minutes` (which defaults to 60 when not supplied) represents the exclusive setup and teardown time reserved on *both* sides of any booked occupancy on that venue. When the system tests whether a new application may occupy the venue, it expands the candidate application's occupancy window by `setup_buffer_minutes` at both the start and the end, and rejects the booking if that expanded window overlaps the booked window of any other application on the same venue that is neither terminal nor still in `DRAFT` (only the candidate window is buffered; the other application's own window is compared un-buffered). This is a closed-interval buffer test: touching within the buffer counts as a conflict. The detailed timing of when this test runs is given in §3.

### 2.8. Corridor Closures and Minimum Gap

A `ClosureSchedule` represents a single road corridor that route segments close. It carries a `corridor_name`, a `min_gap_minutes` value, and a `status` of `OPEN` or `SUSPENDED`; an `OPEN` schedule accepts new closures while a `SUSPENDED` one rejects them. The `min_gap_minutes` (defaulting to 30) is the minimum clear gap required between any two closures on that corridor. Closure intervals are treated as half-open windows, so two closures may be scheduled back-to-back only if the clear gap between them is at least `min_gap_minutes`. The mechanics of when a new segment is checked against existing closures are described in §3.

### 2.9. Fee, Deposit, Coverage, and Cost-Recovery Precision

All monetary figures — application fees, deposits, coverage minimums expressed in dollars, staffing cost recovery, invoice balances, and deposit reconciliation amounts — are computed to two decimal places using round-half-up rounding, except where a figure is defined in whole integer dollars (as with the insurance coverage minimum). Where a calculation names an explicit order in which rounding is applied, that order is binding and is spelled out alongside the calculation in §3. Cost-recovery in particular pins its rounding order: each department's staffing line is rounded to cents first, the rounded lines are summed, the overhead multiplier is then applied, and only then is the grand total rounded — this is a round-per-line-then-sum discipline, never sum-then-round.

### 2.10. Optimistic Concurrency on Venue Booking

Submitting an application for review is guarded by optimistic concurrency against the venue it occupies. The submit-for-review request must carry `expected_venue_version`, which is the `version` of the referenced `Venue` that the applicant last observed (obtained by reading the venue). If another application has since been submitted or resubmitted for the same venue and provisionally reserved its occupancy window, the venue's `version` will have advanced beyond the applicant's observed value; the applicant's view is therefore stale. When `expected_venue_version` does not equal the venue's current `version`, the submit is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412), preventing the applicant from booking against a venue whose reservation posture has moved on since they last read it. This concurrency guard applies solely to the submit-for-review operation; no other endpoint accepts or requires a venue-version field.

## 3. Business Logic & Workflows

### 3.1. Registration and Municipal Setup

Before any application can be filed, the participating parties and resources must exist. An event sponsor is registered as an `Applicant` carrying an `org_name` and a `contact_email`; the returned `id` becomes the value a sponsor supplies as `X-User-ID` on subsequent applicant actions. Registration is open to both the sponsor themselves and to a permit officer acting on their behalf.

A permit officer stands up the physical resources. Creating a venue supplies its `name`, `venue_type`, and `max_capacity`, and optionally `setup_buffer_minutes`; the venue is born `ACTIVE` with `version` 1. Decommissioning a venue moves its `status` to `DECOMMISSIONED` and, like any mutation, advances its `version`. Creating a closure schedule supplies a `corridor_name` and optionally `min_gap_minutes`, and the schedule opens in `OPEN` status. Suspending a schedule moves its `status` to `SUSPENDED` so it will no longer accept new closures. Because expiry and window rules must be reproducible under test, an officer-only test-driving capability sets the logical clock: the `EventClock` holds a single `current_utc` instant that starts at 2026-05-01T00:00:00Z when the server boots and can be advanced by supplying a `to_iso8601` instant.

### 3.2. Filing and Shaping a Draft Application

An `Applicant` opens a new permit application by supplying the sponsoring `applicant_org`, the `venue_id` of the site to occupy, the `event_kind` (one of `PARADE`, `FESTIVAL`, `RACE`, or `RALLY`), the `expected_attendance` as a peak headcount, and the occupancy window bounded by `occupy_start` (inclusive) and `occupy_end` (exclusive). The application is created in `DRAFT`, its `applicant_user_id` is set to the caller's `X-User-ID`, and the window is validated on the way in: `occupy_end` must be strictly later than `occupy_start`, and a window that fails this is rejected with `ERR_INVALID_TIME_WINDOW`. On creation the time-window well-formedness check runs before the referenced `venue_id` is resolved, so an ill-formed window surfaces `ERR_INVALID_TIME_WINDOW` even when the venue does not exist; only once the window is well-formed is a missing `venue_id` rejected with `ERR_VENUE_NOT_FOUND`. Expected attendance must be at least 1.

The moment a draft is created — and again whenever its `expected_attendance` changes while it remains `DRAFT` — the system derives several computed figures. The `permit_class` is derived from attendance by threshold: an attendance of 1000 or fewer is `SMALL`, an attendance from 1001 through 5000 inclusive is `MEDIUM`, and an attendance of 5001 or more is `LARGE`. These same edits recompute the `application_fee`, the `deposit_required`, and the `required_coverage_min`. Editing a draft is done through the applicant's edit action, which may change `expected_attendance`, `occupy_start`, or `occupy_end`, and which re-runs all four derivations while the application is still `DRAFT`. A window edited to violate the strict-ordering rule is again rejected with `ERR_INVALID_TIME_WINDOW`.

The **application fee** is a tiered figure. It begins with a base fee determined by permit class — 150.00 for `SMALL`, 400.00 for `MEDIUM`, and 900.00 for `LARGE`. On top of the base sits a *marginal* attendance surcharge computed per head over successive breakpoints, not as an average. There is no surcharge on the first 1000 attendees. For attendance above 1000, each head from 1001 up through 5000 adds 0.20; that is, the surcharge accrues 0.20 for every head in the span between 1000 and the lesser of the attendance and 5000. For attendance above 5000, each head beyond 5000 adds a further 0.35. The surcharge so accumulated is rounded to two decimal places once, after both tiers are summed. Thus an event of exactly 1000 pays no surcharge while an event of 1001 pays the surcharge for a single head. Separately, a closure fee is levied at 75.00 for every route segment attached to this application, counting every segment regardless of its status; the closure fee is rounded to two decimals. The `application_fee` is then the base plus the rounded surcharge plus the closure fee, with the final total rounded half-up to two decimals. Because segments enter the closure fee, adding a route segment while the application is `DRAFT` recomputes the fee.

The **cleanup deposit**, held in `deposit_required`, is computed on a different basis. It takes the larger of a class-based floor and a per-head figure. The floor is 200.00 for `SMALL`, 500.00 for `MEDIUM`, and 1500.00 for `LARGE`. The per-head figure is the attendance multiplied by 0.10, rounded to two decimals. The `deposit_required` is the greater of those two values, rounded half-up to two decimals.

The **insurance coverage minimum**, held in `required_coverage_min`, is expressed in whole dollars. It starts from a base of 1,000,000 and adds 100 dollars for each attendee above 1000 — that is, 100 multiplied by whichever is greater of zero and the attendance minus 1000 — but the result is capped at 5,000,000. An event of 1000 or fewer therefore requires exactly the 1,000,000 base, and no event ever requires more than the 5,000,000 cap.

### 3.3. Building the Route Plan

A road-closure plan is assembled by attaching `RouteSegment` children to a `DRAFT` or `REVISION_REQUESTED` application. Each segment names the `closure_schedule_id` of the corridor it closes, a human `segment_label`, and the closure interval bounded by `closure_start` (inclusive) and `closure_end` (exclusive). A newly added segment is born `PLANNED`. The closure interval is validated for strict ordering just as occupancy windows are — `closure_end` must be strictly after `closure_start`, else `ERR_INVALID_TIME_WINDOW`.

Two guards run when a segment is added. First, the target schedule must be accepting closures: if its `status` is `SUSPENDED`, the add is rejected with `ERR_CLOSURE_SCHEDULE_SUSPENDED`. Second, the new closure must respect the corridor's minimum gap. Treating closures as half-open intervals, the new interval must stay at least `min_gap_minutes` clear of every other non-terminal closure already scheduled on the same corridor; a closure counts as non-terminal for this test when its own segment is not `RELEASED` and the application that owns it is not in a terminal state (`DENIED`, `CANCELLED`, or `CLOSED`). Back-to-back closures are permitted only when the clear gap between them is at least `min_gap_minutes`. A violation is rejected with `ERR_CLOSURE_CONFLICT`. When a segment is successfully added while the application is `DRAFT`, the `application_fee` is recomputed to reflect the new closure count.

Each segment tracks a lifecycle in its `status`: it is `PLANNED` while the plan is being assembled, moves to `ACTIVE` when the permit is issued, and moves to `RELEASED` when the closure reservation is freed — whether that freeing happens because the application was denied, cancelled, or finally debriefed. A released segment's corridor reservation is returned to the schedule.

### 3.4. Submitting for Multi-Department Review

When the plan is ready, the owning `Applicant` submits the application for review. Submission is permitted from `DRAFT` and, during the revision loop, from `REVISION_REQUESTED`; attempting it from any other state is rejected with `ERR_APPLICATION_NOT_DRAFT`. The caller must own the application or the submit is rejected with `ERR_NOT_APPLICATION_OWNER`. The application must already carry at least one route segment, or the submit is rejected with `ERR_ROUTE_PLAN_EMPTY`. The `expected_attendance` must not exceed the venue's `max_capacity`, or the submit is rejected with `ERR_CAPACITY_EXCEEDED`. The venue occupancy window, expanded on both sides by the venue's `setup_buffer_minutes` as described in §2.7, must not overlap the booked window of any other application on the same venue that is neither terminal nor in `DRAFT` (so other applications still in `DRAFT` are ignored by this check), or the submit is rejected with `ERR_VENUE_DOUBLE_BOOKED`. Finally, submission is guarded by optimistic concurrency: the request must carry `expected_venue_version`, and if it does not equal the venue's current `version`, the submit is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412) as detailed in §2.10.

On a first, successful submit from `DRAFT`, the application transitions `DRAFT → UNDER_REVIEW` and four `DepartmentReview` children are created, one per department — `POLICE`, `FIRE`, `EMS`, and `PUBLIC_WORKS` — each born `PENDING`. At this moment the `application_fee`, `deposit_required`, and `required_coverage_min` are frozen at their computed values, and `expected_attendance` is no longer editable. The submit also increments the venue's `version` by 1, provisionally reserving the occupancy window for the application's window (and thereby making any other applicant's earlier venue read stale).

When a submit instead comes from `REVISION_REQUESTED` — the resubmit in the revision loop — the application again transitions to `UNDER_REVIEW` and again increments the venue's `version` by 1, but the fee is not recomputed because it was frozen at the first submit. Every `DepartmentReview` that had been moved to `CHANGES_REQUESTED` is reset back to `PENDING` so those departments can re-examine the revised plan. The revision loop is cyclic: an application may pass through `REVISION_REQUESTED → UNDER_REVIEW → REVISION_REQUESTED` any number of times.

### 3.5. Department Review, Staffing, and Conditions

Once an application is `UNDER_REVIEW`, each of the four `DepartmentReview` rows becomes actionable by the `DepartmentReviewer` whose department matches. Every review action requires that the review itself is `PENDING` (else `ERR_REVIEW_NOT_PENDING`), that the acting reviewer's department matches the review's `department` (else `ERR_DEPARTMENT_MISMATCH`), and that the parent application is `UNDER_REVIEW` (else `ERR_APPLICATION_NOT_UNDER_REVIEW`). For the approve, request-changes, and veto actions these three gates are evaluated in exactly that order — review-`PENDING` first, then department-match, then application-`UNDER_REVIEW` — so when a non-`PENDING` review is acted on the `ERR_REVIEW_NOT_PENDING` masks a department mismatch, and a department mismatch masks a not-under-review application. A reviewer has three mutually exclusive verdicts.

**Approving** a review moves it `PENDING → APPROVED`. When a reviewer approves, they may also record the department's staffing plan by supplying `planned_personnel`, `planned_hours`, and `hourly_rate`; each of these defaults to 0 if not supplied and drives the later cost-recovery estimate. Approval recomputes the application-wide quorum figures. The `quorum_met` flag is true only when all four required departments — `POLICE`, `FIRE`, `EMS`, and `PUBLIC_WORKS` — have their `DepartmentReview` in `APPROVED`, and the `has_veto` flag is true if any review is `VETOED`. When approval causes all four to be `APPROVED` (so `quorum_met` becomes true and `has_veto` remains false), the application automatically transitions `UNDER_REVIEW → CONDITIONALLY_APPROVED`, described in §3.6.

**Requesting changes** moves the review `PENDING → CHANGES_REQUESTED`. The reviewer may attach an explanatory `note`. As a side effect, the reviewer may propose one or more conditions (described below), and the parent application automatically transitions `UNDER_REVIEW → REVISION_REQUESTED` so the applicant can revise and resubmit.

**Vetoing** moves the review `PENDING → VETOED` and is absolute. A veto requires a non-empty `note` giving the reason, and a veto submitted without one is rejected with `ERR_VETO_REASON_REQUIRED` (HTTP 422). A single veto immediately drives the parent application `UNDER_REVIEW → DENIED`; the accompanying cascade is described in §3.7. `VETOED` is a terminal state for that review.

A reviewer may attach a `PermitCondition` to their own review while acting on the application. Attaching a condition is gated only by the reviewer's department matching the target review's `department` (else `ERR_DEPARTMENT_MISMATCH`); it does not require the review to be `PENDING` nor the application to be `UNDER_REVIEW`, so a condition may be attached to a review in any status regardless of the parent application's state. A condition carries the `text` the applicant must satisfy and a `mandatory` flag that defaults to true; it records the `department_review_id` of the review that imposed it and is born `PROPOSED`. A mandatory condition must be acknowledged before the permit can be issued. The owning `Applicant` acknowledges a condition, which requires that it is `PROPOSED` (else `ERR_CONDITION_NOT_PROPOSED`) and that the caller owns the parent application (else `ERR_NOT_APPLICATION_OWNER`); acknowledgement moves the condition `PROPOSED → ACKNOWLEDGED`. A condition that is still `PROPOSED` when the application is denied or cancelled is moved to `WAIVED`.

When a resubmit resets a `CHANGES_REQUESTED` review back to `PENDING`, that reviewer's earlier proposed conditions remain in place; the reviewer simply gets a fresh chance to approve, request changes again, or veto against the revised plan.

### 3.6. Insurance and Deposit Prerequisites

Two prerequisites must be in place before a conditionally-approved permit can be issued: an accepted certificate of insurance and a held cleanup deposit.

The `Applicant` submits an `InsuranceCertificate` (a "COI") carrying a `carrier`, a `coverage_amount`, and an `expires_at` instant; it is born `SUBMITTED`. Submitting a COI is gated only by application ownership (else `ERR_NOT_APPLICATION_OWNER`) and carries no application-state precondition, so a COI may be submitted while the application is in any state. A `PermitOfficer` then reviews it. Accepting a COI requires that it is `SUBMITTED` (else `ERR_COI_NOT_SUBMITTED`), that its `expires_at` is strictly after the application's `occupy_end` (else `ERR_COI_EXPIRES_BEFORE_EVENT`), and that its `coverage_amount` is at least the application's `required_coverage_min` (else `ERR_COI_COVERAGE_INSUFFICIENT`, HTTP 402); these three checks run in that order, so the expiry check is evaluated before the coverage check and masks it when both fail. Acceptance moves the certificate `SUBMITTED → ACCEPTED` and recomputes the application's `coi_on_file` to true. Because only the latest accepted certificate counts, accepting a COI demotes any previously `ACCEPTED` certificate back to `SUBMITTED`; the flag `coi_on_file` is true precisely when there exists an `ACCEPTED` certificate meeting the coverage minimum. Rejecting a COI requires only that it is `SUBMITTED`, moves it `SUBMITTED → REJECTED` (a terminal state), and recomputes `coi_on_file`, which may remain false.

The `Applicant` pays a `Deposit` by supplying an `amount`, which must be at least the application's `deposit_required` or the payment is rejected with `ERR_DEPOSIT_UNDERFUNDED` (HTTP 402); an omitted `amount` is likewise treated as underfunded. Like COI submission, paying a deposit is gated only by application ownership and carries no application-state precondition, so it may be paid while the application is in any state. A paid deposit is `HELD`. Its `forfeited_amount` and `refunded_amount` both begin at 0 and are settled only at debrief.

When all four departments have approved and the application enters `CONDITIONALLY_APPROVED`, the system computes the staffing cost-recovery **estimate** and creates or refreshes the application's `Invoice`. The invoice snapshots `fee_component`, records `cost_recovery_estimate`, sets `balance_due` to the sum of `fee_component` and `cost_recovery_estimate`, leaves `cost_recovery_actual` at 0, and opens the invoice in `OPEN`. The cost-recovery estimate is built from the four department reviews: for each department, a staffing line is `planned_personnel` multiplied by `planned_hours` multiplied by `hourly_rate`, rounded to cents. The four rounded lines are summed to a subtotal, the subtotal is then multiplied by one plus the 0.15 overhead rate, and that product is rounded half-up to two decimals to give the total. The rounding order is binding: round each line first, then sum, then apply overhead, then round the total.

### 3.7. Issuance and the Denial/Cancellation Cascades

A `PermitOfficer` issues a permit that has reached `CONDITIONALLY_APPROVED`. Issuance requires that the application is `CONDITIONALLY_APPROVED` (else `ERR_APPLICATION_NOT_APPROVABLE`), that `coi_on_file` is true, meaning an accepted certificate meets `required_coverage_min` (else `ERR_COI_NOT_ON_FILE`), that a `Deposit` exists in `HELD` with an `amount` at least `deposit_required` (else `ERR_DEPOSIT_NOT_HELD`), and that every mandatory `PermitCondition` is `ACKNOWLEDGED` (else `ERR_UNACKNOWLEDGED_CONDITIONS`). When these hold, the application transitions `CONDITIONALLY_APPROVED → ISSUED`, every `PLANNED` route segment moves to `ACTIVE`, and the invoice's `fee_component` snapshot is pinned while the invoice remains `OPEN`.

A veto triggers the **denial cascade**. When any department vetoes, the application moves `UNDER_REVIEW → DENIED`: every `PLANNED` route segment is moved to `RELEASED` and its corridor closure reservation is freed, the reserved venue occupancy is released (which increments the venue's `version` by 1), and every `PermitCondition` not already `WAIVED` is moved to `WAIVED` — for this cascade the only condition status treated as terminal is `WAIVED` itself, so both `PROPOSED` and `ACKNOWLEDGED` conditions are moved to `WAIVED`. `DENIED` is terminal.

An `Applicant` may **cancel** their own application; cancellation always verifies ownership (else `ERR_NOT_APPLICATION_OWNER`). Cancellation is permitted from `DRAFT`, `UNDER_REVIEW`, `REVISION_REQUESTED`, and `CONDITIONALLY_APPROVED`; attempting it from a terminal state or from `ISSUED` is rejected with `ERR_APPLICATION_NOT_CANCELLABLE`. Cancelling a bare `DRAFT` simply moves it to `CANCELLED` — no reviews were created and no venue was reserved, so there is nothing to unwind. Cancelling from `UNDER_REVIEW` or `REVISION_REQUESTED` moves all `PLANNED` route segments to `RELEASED`, increments the venue's `version` by 1 to free the reservation, and moves all `PROPOSED` conditions to `WAIVED`. Cancelling from `CONDITIONALLY_APPROVED` likewise releases all `PLANNED` segments and increments the venue's `version` by 1, and additionally refunds any `HELD` deposit in full — the deposit moves to `REFUNDED` with `refunded_amount` set to its `amount` and `forfeited_amount` set to 0. `CANCELLED` is terminal.

### 3.8. Post-Event Debrief, True-Up, and Reconciliation

After an event, its actuals are logged and the permit is closed. While the application is `ISSUED` and before the debrief is finalized, each `DepartmentReviewer` logs their department's actual post-event staffing by supplying `actual_hours` for their review; this requires the parent application to be `ISSUED` and the acting reviewer's department to match the review, and is not gated by the review's own status (a review in any status, e.g. `APPROVED`, accepts logged actuals). The supplied `actual_hours` overwrites the field, defaulting to 0 when the body omits it. A department that never logs actuals keeps its `actual_hours` at the default of 0.

A `PermitOfficer` opens a `CleanupDebrief` on an `ISSUED` application, supplying the `actual_attendance` observed, optionally the `cleanup_charges` assessed against the deposit (defaulting to 0), and optionally the `incident_count` logged during the event (defaulting to 0). The debrief is born `OPEN`.

Finalizing the debrief closes the permit. Finalization requires the application to be `ISSUED` (else `ERR_APPLICATION_NOT_ISSUED`) and a debrief in `OPEN` to exist for the application (else `ERR_DEBRIEF_NOT_OPEN`). Finalization performs several coordinated effects. First, it computes the staffing cost-recovery **actual** using the same method as the estimate but drawing each department's hours from `actual_hours` rather than `planned_hours`: each department's line is `planned_personnel` multiplied by `actual_hours` multiplied by `hourly_rate` rounded to cents, the four rounded lines are summed, the subtotal is multiplied by one plus the 0.15 overhead rate, and the product is rounded half-up to two decimals. The invoice's `cost_recovery_actual` is set to this figure, its `balance_due` is trued up to the sum of `fee_component` and `cost_recovery_actual`, and the invoice moves to `SETTLED`. Second, the deposit is reconciled: the `forfeited_amount` is the lesser of the deposit's `amount` and the debrief's `cleanup_charges`, rounded to two decimals, and the `refunded_amount` is the deposit's `amount` minus the `forfeited_amount`, rounded to two decimals — so the two always sum back to the deposit `amount`, and cleanup charges beyond the deposit are never clawed back from the applicant. If `cleanup_charges` exceed 0 the deposit moves to `FORFEITED_PARTIAL`; otherwise it moves to `REFUNDED`. Third, every `ACTIVE` route segment is moved to `RELEASED`, freeing its corridor reservation and incrementing the venue's `version` by 1. Finally, the debrief moves `OPEN → FINALIZED` and the application transitions `ISSUED → CLOSED`, a terminal state.

## 4. Endpoint Definitions

Requests that create a new resource return HTTP 201 with the created resource in `data`. Requests that modify an existing resource, perform a state transition, or read a resource or list return HTTP 200. All error responses use the status codes listed in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/applicants` | Register an applicant organization | Applicant, PermitOfficer |
| GET | `/applicants/{applicantId}` | Get an applicant | Applicant, PermitOfficer |
| POST | `/venues` | Create a venue | PermitOfficer |
| GET | `/venues` | List venues | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/venues/{venueId}` | Get a venue (read current version for OCC) | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/venues/{venueId}/decommission` | Decommission a venue | PermitOfficer |
| POST | `/closure-schedules` | Create a road-corridor closure schedule | PermitOfficer |
| GET | `/closure-schedules` | List closure schedules | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/closure-schedules/{scheduleId}` | Get a closure schedule | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/closure-schedules/{scheduleId}/suspend` | Suspend a closure schedule | PermitOfficer |
| POST | `/permit-applications` | Create a DRAFT permit application | Applicant |
| GET | `/permit-applications` | List permit applications (filterable by `venue_id`, `applicant_user_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-applications/{id}` | Get a permit application with computed fields | Applicant, PermitOfficer, DepartmentReviewer |
| PATCH | `/permit-applications/{id}` | Edit a DRAFT application | Applicant |
| POST | `/permit-applications/{id}/submit-for-review` | Submit for multi-department review (OCC-guarded on venue) | Applicant |
| POST | `/permit-applications/{id}/cancel` | Cancel an application | Applicant |
| POST | `/permit-applications/{id}/issue` | Issue a conditionally-approved permit | PermitOfficer |
| POST | `/permit-applications/{appId}/route-segments` | Add a route segment | Applicant |
| GET | `/permit-applications/{appId}/route-segments` | List an application's route segments | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-applications/{appId}/route-segments/{segmentId}` | Get a route segment | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/route-segments` | List route segments (filterable by `closure_schedule_id`, `application_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/route-segments/{segmentId}` | Get a route segment by id | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-applications/{appId}/reviews` | List an application's department reviews | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-applications/{appId}/reviews/{reviewId}` | Get a department review | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/permit-applications/{appId}/reviews/{reviewId}/approve` | Approve a review; may set staffing plan | DepartmentReviewer |
| POST | `/permit-applications/{appId}/reviews/{reviewId}/request-changes` | Request changes on a review | DepartmentReviewer |
| POST | `/permit-applications/{appId}/reviews/{reviewId}/veto` | Veto a review (absolute deny) | DepartmentReviewer |
| POST | `/permit-applications/{appId}/reviews/{reviewId}/log-actuals` | Log post-event actual staffing hours | DepartmentReviewer |
| POST | `/permit-applications/{appId}/reviews/{reviewId}/conditions` | Attach a permit condition to a review | DepartmentReviewer |
| GET | `/permit-applications/{appId}/conditions` | List an application's conditions | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-applications/{appId}/reviews/{reviewId}/conditions` | List conditions imposed by a review | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/permit-applications/{appId}/conditions/{conditionId}/acknowledge` | Acknowledge a proposed condition | Applicant |
| POST | `/permit-applications/{appId}/coi` | Submit a COI record | Applicant |
| GET | `/permit-applications/{appId}/coi` | List an application's COIs | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/permit-applications/{appId}/coi/{coiId}/accept` | Accept a COI | PermitOfficer |
| POST | `/permit-applications/{appId}/coi/{coiId}/reject` | Reject a COI | PermitOfficer |
| POST | `/permit-applications/{appId}/deposit` | Pay the cleanup/damage deposit | Applicant |
| GET | `/permit-applications/{appId}/deposit` | List an application's deposit(s) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-applications/{appId}/invoice` | List an application's invoice(s) | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/permit-applications/{appId}/debrief` | Open a post-event debrief | PermitOfficer |
| GET | `/permit-applications/{appId}/debrief` | List an application's debriefs | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/permit-applications/{appId}/debrief/{debriefId}/finalize` | Finalize a debrief and close the permit | PermitOfficer |
| GET | `/department-reviews` | List department reviews (filterable by `application_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/department-reviews/{reviewId}` | Get a department review by id | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-conditions` | List permit conditions (filterable by `application_id`, `department_review_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/permit-conditions/{conditionId}` | Get a permit condition by id | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/insurance-certificates` | List insurance certificates (filterable by `application_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/insurance-certificates/{coiId}` | Get an insurance certificate by id | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/deposits` | List deposits (filterable by `application_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/deposits/{depositId}` | Get a deposit by id | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/invoices` | List invoices (filterable by `application_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/invoices/{invoiceId}` | Get an invoice by id | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/cleanup-debriefs` | List cleanup debriefs (filterable by `application_id`) | Applicant, PermitOfficer, DepartmentReviewer |
| GET | `/cleanup-debriefs/{debriefId}` | Get a cleanup debrief by id | Applicant, PermitOfficer, DepartmentReviewer |
| POST | `/_clock/set_current_utc` | Set the logical server clock | PermitOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_CLOSURE_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_SEGMENT_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_COI_NOT_FOUND` | 404 |
| `ERR_CONDITION_NOT_FOUND` | 404 |
| `ERR_DEPOSIT_NOT_FOUND` | 404 |
| `ERR_DEBRIEF_NOT_FOUND` | 404 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_NOT_APPLICATION_OWNER` | 403 |
| `ERR_DEPARTMENT_MISMATCH` | 403 |
| `ERR_APPLICATION_NOT_DRAFT` | 409 |
| `ERR_APPLICATION_NOT_UNDER_REVIEW` | 409 |
| `ERR_APPLICATION_NOT_APPROVABLE` | 409 |
| `ERR_APPLICATION_NOT_ISSUED` | 409 |
| `ERR_APPLICATION_NOT_CANCELLABLE` | 409 |
| `ERR_REVIEW_NOT_PENDING` | 409 |
| `ERR_COI_NOT_SUBMITTED` | 409 |
| `ERR_CONDITION_NOT_PROPOSED` | 409 |
| `ERR_DEBRIEF_NOT_OPEN` | 409 |
| `ERR_ROUTE_PLAN_EMPTY` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_VENUE_DOUBLE_BOOKED` | 409 |
| `ERR_CLOSURE_CONFLICT` | 409 |
| `ERR_CLOSURE_SCHEDULE_SUSPENDED` | 409 |
| `ERR_COI_NOT_ON_FILE` | 409 |
| `ERR_DEPOSIT_NOT_HELD` | 409 |
| `ERR_UNACKNOWLEDGED_CONDITIONS` | 409 |
| `ERR_VETO_REASON_REQUIRED` | 422 |
| `ERR_COI_COVERAGE_INSUFFICIENT` | 402 |
| `ERR_COI_EXPIRES_BEFORE_EVENT` | 409 |
| `ERR_DEPOSIT_UNDERFUNDED` | 402 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_STALE_VENUE_VERSION` | 412 |

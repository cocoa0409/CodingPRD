# Residential Appraisal Practice API — Product Requirements Document

## 1. Introduction

An independent residential appraisal firm lives or dies by three things: turn time, panel standing, and defensibility. Lender and AMC clients route orders to the firm expecting a quoted fee and a promised delivery date. State boards expect every appraisal to be backed by a complete, retained workfile and every complaint to be answered before its deadline. The firm's own quality-control discipline — segregation of duties between signer and reviewer, supervised trainees, comparable-adjustment limits — is what keeps its licenses intact. Running that practice on email and spreadsheets produces missed due dates, stale fee quotes, and workfiles that cannot survive a board inquiry.

This document specifies the Residential Appraisal Practice API, the system of record for such a firm. It governs the full order lifecycle from client intake through scope determination, assignment, inspection, comparable analysis, drafting, quality control, signature, and delivery — and then keeps going, through revision requests and reconsiderations of value, workfile retention and legal hold, board complaints and their sanction cascades, and the scorecards that decide whether an appraiser remains in good standing. Five roles interact with the system: firm operations staff, client portal users, staff appraisers, quality-control reviewers, and compliance officers. Every temporal rule in the system is evaluated against a controllable logical clock so that deadline, recency, and retention behavior is deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

All business resources are mounted under the `/appraisal` URL prefix; the logical-clock capability sits at the server root. This section defines the rules that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The API recognizes exactly five roles: `FirmAdmin`, `ClientUser`, `Appraiser`, `QCReviewer`, and `ComplianceOfficer`. A request missing either header, presenting a blank value, or naming an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Where the role is permitted but the caller does not own the resource — a `ClientUser` quoting another client's `client_id`, or an `Appraiser` acting on an order assigned to someone else — the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The identity carried by `X-User-ID` differs per role, and the distinction drives every ownership check in the system:

- When `X-User-Role` is `FirmAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.
- When `X-User-Role` is `ClientUser`, `X-User-ID` is the `id` of the acting Client; ownership checks on any resource that belongs to a client compare the resource's `client_id` — or, for child resources such as orders, reports, and revision requests, the owning order's `client_id` — to `X-User-ID`.
- When `X-User-Role` is `Appraiser`, `X-User-ID` is the `id` of the acting Appraiser; checks such as "the acting appraiser must be the order's assignee" compare `X-User-ID` against the referenced appraiser field.
- When `X-User-Role` is `QCReviewer`, `X-User-ID` is likewise the `id` of an Appraiser entity — the reviewer is a certified appraiser acting in a review capacity, and review-time rules resolve that appraiser record.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items are skipped and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

Every temporal rule in this document — deadline checks, sale-recency windows, retention expiry, fee-schedule window selection, license-expiry comparisons — is evaluated against a logical clock maintained by the server, never against wall-clock time. Before the clock has been set explicitly, it reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own. A `FirmAdmin` moves the clock through the clock-setting capability by supplying a `to_iso8601` timestamp; the response echoes the new reading as `current_utc`. Phrases such as "now", "the current date", or "at acceptance" throughout this document refer to this logical clock. Fields typed as calendar dates rather than datetimes — `license_expiry` on an appraiser and `sale_date` on a comparable, both YYYY-MM-DD — are compared against the calendar date of the logical clock.

### 2.5. Common Resource Properties

Every resource in the system — clients, appraisers, panel memberships, fee schedules, orders, appointments, comparables, reports, revision requests, workfile records, and complaints — carries the same four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by exactly one with every modification to the resource.

No entity in this system omits `updated_at` or `version`. Status fields throughout the system are exact uppercase strings; §3 introduces each entity's state machine values in narrative, and those strings are part of the API contract.

### 2.6. Money, Rates, and Rounding

All monetary amounts are integer cents: fees, fee adjustments, comparable prices, adjustment lines, and value conclusions are never fractional. Whenever a calculation would produce a fractional cent — a rush premium, a half-fee cancellation, a per-line comparable adjustment — the result is rounded half-up to the nearest whole cent, where "half-up" means an exact half rounds up (a 45500-cent fee halved yields 22750 cents, never 22749). Percentages are carried at two decimal places, rounded half-up, with one exception: the scorecard's `on_time_rate` is carried at four decimal places, rounded half-up. Turn-time averages on the scorecard are carried at two decimal places, rounded half-up.

### 2.7. The Validation Pipeline

Every incoming request passes through an ordered validation pipeline, and the first failing check determines the rejection — later checks are not evaluated, so a request that would violate two rules always surfaces the earlier one. The evaluation order is:

1. Authentication: both headers present and non-blank, and the role recognized (`ERR_UNAUTHENTICATED`, 401).
2. Authorization and ownership: the role is listed for the endpoint (`ERR_FORBIDDEN_ROLE`, 403) and, where an ownership rule applies, the caller owns the resource (`ERR_NOT_RESOURCE_OWNER`, 403).
3. Request shape: required fields present, enum values within their declared sets, and numeric ranges honored — monetary amounts strictly positive where required, `window_end` strictly after `window_start`, `distance_miles` non-negative, `rush_multiplier_bps` between 0 and 10000 inclusive, `default_turn_time_days` and `requested_turn_days` at least 1 (`ERR_VALIDATION`, 400).
4. Reference resolution: path identifiers resolve left-to-right, then body foreign keys; each unresolved id yields the referenced entity's 404 (§2.9).
5. State preconditions: the target entity is in the transition's required from-state (`ERR_INVALID_STATE`, 409); revision-request creation and complaint creation use `ERR_ORDER_NOT_DELIVERED` (409) for their order-state overlay instead.
6. Optimistic concurrency: the expected-version field matches the parent entity's current version (412, §2.8).
7. License, signature, and safety gates (422): expired licenses (`ERR_LICENSE_EXPIRED`), insufficient license level (`ERR_LICENSE_LEVEL_INSUFFICIENT`), missing supervisor co-signature (`ERR_SIGNATURE_COSIGN_REQUIRED`), co-signer mismatch (`ERR_SUPERVISOR_SIGNATURE_MISMATCH`), reviewer conflicts (`ERR_SOD_REVIEWER_CONFLICT`), open-complaint holds (`ERR_COMPLIANCE_HOLD_ACTIVE`), workfile completeness (`ERR_WORKFILE_INCOMPLETE`), desktop-appraisal restrictions (`ERR_DESKTOP_NOT_ALLOWED`), and ineligible comparables (`ERR_COMP_INELIGIBLE`).
8. Cross-entity integrity (422): active-client checks (`ERR_CLIENT_NOT_ACTIVE`), panel membership (`ERR_APPRAISER_NOT_ON_PANEL`), assignee eligibility (`ERR_APPRAISER_NOT_ASSIGNABLE`), assignee identity (`ERR_NOT_ASSIGNED_APPRAISER`), and supervisor certification (`ERR_SUPERVISOR_NOT_CERTIFIED`).
9. Temporal windows (422): appointment window timing (`ERR_WINDOW_IN_PAST`), appointment overlap (`ERR_APPOINTMENT_OVERLAP`), fee-schedule window overlap (`ERR_SCHEDULE_WINDOW_OVERLAP`), the reconsideration-of-value window (`ERR_ROV_WINDOW_EXPIRED`), the complaint response deadline (`ERR_RESPONSE_DEADLINE_PASSED`), and retention expiry (`ERR_RETENTION_NOT_EXPIRED`).
10. Uniqueness and aggregate constraints (422): duplicate panel memberships (`ERR_DUPLICATE_PANEL_MEMBERSHIP`), invalid tier overrides (`ERR_INVALID_TIER_OVERRIDE`), insufficient locked comparables (`ERR_INSUFFICIENT_LOCKED_COMPS`), an empty assignment selector pool (`ERR_NO_ELIGIBLE_APPRAISER`), and deactivation with open assignments (`ERR_APPRAISER_HAS_OPEN_ASSIGNMENTS`).
11. Fiscal bounds (422): fee-adjustment limits (`ERR_FEE_WAIVER_EXCEEDS_BALANCE`).

A request rejected at any step mutates no resource.

### 2.8. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and no other endpoint takes an expected-version field.

Creating a revision request — `POST /appraisal/orders/{id}/revision-requests` — requires the request body to carry `expected_order_version`, holding the order `version` the caller last observed. If that value does not equal the order's current `version` at the time of the write — for example because another writer has since created a revision request on the same order, legitimately superseding the previously open one and advancing the order's version — the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), protecting the caller from acting on a view of the order it has not observed.

Creating a fee schedule — `POST /appraisal/fee-schedules` — likewise requires `expected_client_version` matching the client record's current `version`. Because creating a schedule legitimately closes the prior open-ended window for that client and tier and advances the client's `version`, a caller working from a stale view of the client is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412).

### 2.9. Reference Resolution and Not-Found Errors

The resource graph is flat: every entity is a peer addressed by its own `id`, and relationships are expressed through reference fields rather than deep URL nesting. When a request references resources — path identifiers first, resolved left to right, and then body foreign keys such as `order_id`, `client_id`, `appraiser_id`, `respondent_appraiser_id`, and `supervisor_id` — each identifier must resolve to an existing record. The first unresolvable identifier rejects the request with the referenced entity's not-found error: `ERR_CLIENT_NOT_FOUND`, `ERR_APPRAISER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_COMPARABLE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_REVISION_REQUEST_NOT_FOUND`, `ERR_WORKFILE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, or `ERR_PANEL_MEMBERSHIP_NOT_FOUND`, each with HTTP 404.

### 2.10. Cascading State Propagation and Version Semantics

State changes propagate across entity boundaries. Submitting a report for review moves its order; completing an inspection appointment moves its order; accepting a revision request moves the order, the report, and every locked comparable; closing a complaint with a sanction moves the respondent's memberships, orders, and appointments. These system-driven transitions are part of the same write that triggered them — no separate client call is needed or possible for the propagated change. Every transition of an order, whether operator-invoked or system-invoked, increments the order's `version` by exactly one and refreshes its `updated_at`; the same version-and-timestamp rule applies to every mutation of every other entity, including counter updates such as an order's `open_complaint_count`. Because even creating a revision request advances the order's `version`, the optimistic-concurrency guard of §2.8 is what protects a caller from writing against a stale view of the order.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding, Panels, and Fee Schedules

A `FirmAdmin` onboards a lender or AMC by creating a client with its legal `name`, a `client_type` of `AMC`, `DIRECT_LENDER`, or `PRIVATE`, a `contact_email`, and a `default_turn_time_days` — the client's standard turn time in calendar days, at least 1. A new client starts in `ACTIVE` status. From there the firm may suspend an `ACTIVE` client, moving it to `SUSPENDED`; reactivate a `SUSPENDED` client back to `ACTIVE`; or terminate a client from either `ACTIVE` or `SUSPENDED` into the terminal `TERMINATED` state. Invoking any of these against a client in the wrong from-state is rejected with `ERR_INVALID_STATE`. Suspension blocks new order creation for the client — rejected with `ERR_CLIENT_NOT_ACTIVE` — while leaving in-flight orders untouched. Termination goes further: every `ACTIVE` panel membership the client holds is moved to `REMOVED`, and new orders as well as new fee schedules for the terminated client are rejected with `ERR_CLIENT_NOT_ACTIVE`. Clients can be listed with an optional `status` filter.

Panel membership records which appraisers may receive which clients' orders. A `FirmAdmin` adds an appraiser to a client's panel by creating a membership carrying the `client_id` and the `appraiser_id`; the membership starts `ACTIVE`. At most one `ACTIVE` membership may exist for a given (`client_id`, `appraiser_id`) pair: creating a second active row is rejected with `ERR_DUPLICATE_PANEL_MEMBERSHIP`, although a pair whose earlier membership is `REMOVED` may be created anew. A membership leaves the panel through removal, moving from `ACTIVE` to the terminal `REMOVED` state — a removal attempted against a membership that is not `ACTIVE` fails with `ERR_INVALID_STATE` — and the same transition is driven by the system itself, without any client call, when the client is terminated or when a sanction cascade strips the appraiser (§3.8). Memberships can be listed filtered by `client_id`, `appraiser_id`, or `status`.

Fees are governed by per-client, per-tier fee schedules. A schedule row carries the `client_id`, a `complexity_tier` of `STANDARD`, `COMPLEX`, or `HIGH_VALUE`, a strictly positive `base_fee_cents`, a `rush_multiplier_bps` between 0 and 10000 inclusive expressing the rush premium in basis points of the base fee, a non-negative `revision_fee_cents` charged when a revision request is accepted (§3.7), an inclusive `effective_from`, and an optional `effective_to` marking the exclusive end of the window — null means open-ended. Windows are half-open: a schedule governs from `effective_from` up to but not including `effective_to`. For any one client and tier, windows must never overlap; a new row whose window would intersect an existing window for the same pair is rejected with `ERR_SCHEDULE_WINDOW_OVERLAP`. Creating a new schedule for a client and tier whose prior row is open-ended closes that prior row by setting its `effective_to` to the new row's `effective_from`.

Because schedule creation mutates the client record — closing the prior window and advancing the client's `version` by one — creation must carry `expected_client_version` as described in §2.8, and a stale view is rejected with `ERR_STALE_CLIENT_VERSION`. Schedules can be listed filtered by `client_id` or `complexity_tier`. When no schedule window covers the timestamp a fee quote needs, the firm's retail rate card applies instead (§3.3).

### 3.2. The Appraiser Roster, Supervision, and Panel Standing

A `FirmAdmin` builds the roster by creating appraisers, each with a `full_name`, a `license_level` of `TRAINEE`, `LICENSED`, or `CERTIFIED_RESIDENTIAL`, a state `license_number`, and a `license_expiry` date. A trainee must name a supervising appraiser through `supervisor_id`: the field is required exactly when `license_level` is `TRAINEE` and is forbidden for any other level, and the referenced supervisor must itself hold `CERTIFIED_RESIDENTIAL` — otherwise creation is rejected with `ERR_SUPERVISOR_NOT_CERTIFIED`. A new appraiser starts `ACTIVE`, with `sanction_override` false and all performance counters at zero.

Availability is managed through the `ACTIVE` / `INACTIVE` status flag, which is independent of the appraiser's computed standing. Deactivation moves `ACTIVE` to `INACTIVE` and is refused with `ERR_APPRAISER_HAS_OPEN_ASSIGNMENTS` while the appraiser still holds orders in any working state — `ASSIGNED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `IN_ANALYSIS`, `DRAFTING`, or `QC_REVIEW`. Reactivation moves `INACTIVE` back to `ACTIVE` and requires the appraiser's `license_expiry` to fall strictly after the logical clock's date, failing with `ERR_LICENSE_EXPIRED` otherwise; the same unexpired-license rule recurs at assignment (§3.4) and at delivery (§3.6). Both transitions reject a wrong from-state with `ERR_INVALID_STATE`. The roster list accepts `license_level`, `status`, and `supervisor_id` filters. An `Appraiser`-role caller may read only their own appraiser record and their own scorecard — anyone else's is `ERR_NOT_RESOURCE_OWNER` — while `FirmAdmin` and `QCReviewer` may read any appraiser record.

An appraiser's panel standing is computed, never stored by hand. The scorecard recomputes on every read of the scorecard view and during every assignment-eligibility evaluation — in practice after every delivery, cancellation, no-show, and sanction set or clear. Its `completed_count` counts orders assigned to the appraiser that have reached a first delivery; cancelled orders never reached delivery and are excluded. Its `on_time_count` counts the subset delivered on or before the order's `due_at`. The `on_time_rate` is null while the appraiser has no completions, and otherwise is the count of on-time deliveries divided by `completed_count`, rounded half-up to four decimal places. Standing follows a strict ladder: `PANEL_SUSPENDED` whenever `sanction_override` is in force; otherwise, once at least four orders are complete, an `on_time_rate` below 0.75 forces `PANEL_SUSPENDED` and a rate below 0.90 yields `PROBATION`; everyone else is `GOOD_STANDING`. The boundaries are exact — a rate of exactly 0.7500 remains `PROBATION` rather than suspended, a rate of exactly 0.9000 is `GOOD_STANDING`, and the fourth completed order is the first one that makes the scorecard rated at all.

The scorecard view also carries `confirmed_minutes` — the summed length in minutes, from `window_start` to `window_end`, across the appraiser's `CONFIRMED` appointments — and two turn-time averages. `avg_calendar_turn_days` is the mean elapsed time from `accepted_at` to `first_delivered_at`, measured in days across completed orders and rounded half-up to two decimal places. `avg_business_turn_days` applies the same averaging but counts only the dates after the acceptance date, up to and including the delivery date, whose weekday is Monday through Friday: an order accepted on Saturday 2026-08-01 and delivered on Wednesday 2026-08-05 counts 4 calendar days but 3 business days. The full scorecard payload carries `appraiser_id`, `completed_count`, `on_time_count`, `on_time_rate`, `avg_calendar_turn_days`, `avg_business_turn_days`, `confirmed_minutes`, `standing`, and `sanction_override`.

When a board sanction has run its course, a `FirmAdmin` clears it: the appraiser's `sanction_override` flips to false and `standing` recomputes under the ordinary ladder above. Clearing a sanction restores nothing the cascade took — `REMOVED` memberships stay removed, and orders unassigned by the cascade stay unassigned until a fresh assignment is made.

### 3.3. Order Intake, Scope Determination, and Acceptance

An order enters the firm when a `ClientUser` or a `FirmAdmin` creates it with the `client_id` — a `ClientUser` must pass their own client's id, or the request fails with `ERR_NOT_RESOURCE_OWNER` — the subject `property_address`, a `property_type` of `SFR`, `CONDO`, `MULTI_2_4`, or `MANUFACTURED`, the client-stated `estimated_value_cents` (strictly positive, and the driver of tier determination), a `loan_type` of `CONVENTIONAL`, `FHA`, or `VA`, and the client's `requested_turn_days` (at least 1). The client must be `ACTIVE`, or creation is rejected with `ERR_CLIENT_NOT_ACTIVE`. A new order begins in `RECEIVED` with `requires_inspection` defaulting to true, no assignee, and its monetary counters — `surcharge_total_cents`, `waived_total_cents`, and `revision_fees_collected_cents` — at zero. Orders can be listed filtered by `client_id`, `assigned_appraiser_id`, or `status`.

Scope determination, performed by a `FirmAdmin`, moves a `RECEIVED` order to `SCOPE_DETERMINED`; any other order state is `ERR_INVALID_STATE`, and the client must still be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`). The computed `complexity_tier` is `HIGH_VALUE` when `estimated_value_cents` is at least 100000000 cents — the threshold is inclusive, so an estimate of exactly that amount yields `HIGH_VALUE`. Otherwise the tier is `COMPLEX` when `property_type` is `MULTI_2_4` or `MANUFACTURED`. Every remaining order is `STANDARD`. The administrator may supply `complexity_tier_override` to accept the computed tier or to raise it by exactly one level — `STANDARD` to `COMPLEX`, or `COMPLEX` to `HIGH_VALUE`. `HIGH_VALUE` admits no override, and any override that is neither the computed tier nor one level above it is rejected with `ERR_INVALID_TIER_OVERRIDE`. The same call may mark the order as a desktop appraisal by passing `requires_inspection` false, but only when the resulting tier is `STANDARD`; requesting a desktop assignment for any other tier fails with `ERR_DESKTOP_NOT_ALLOWED`. That flag matters downstream twice: it decides whether the appointment chain of §3.4 is required at all, and it decides whether inspection notes are required in the workfile at completion (§3.9).

Scope determination also quotes the fee, and the recipe is shared with acceptance. The system selects the fee schedule for the order's client and its just-determined tier whose window contains the as-of timestamp — `effective_from` at or before that instant, and `effective_to` either unset or strictly after it — taking the base from that row's `base_fee_cents` and the rush rate from its `rush_multiplier_bps`. When no window matches, the retail rate card supplies a base of 45000 cents for `STANDARD`, 60000 cents for `COMPLEX`, and 85000 cents for `HIGH_VALUE`, with a retail rush rate of 1500 basis points. The running total starts at the base. If the order's `requested_turn_days` is fewer than the client's `default_turn_time_days`, a rush premium is added: the base multiplied by the rush basis points and divided by ten thousand, rounded half-up to whole cents. A property surcharge follows — 15000 cents for `MULTI_2_4`, or 7500 cents for `MANUFACTURED` — and a government-loan surcharge of 5000 cents applies when `loan_type` is `FHA` or `VA`. The quote is finally bounded: raised to a floor of 35000 cents when below it, and capped at 150000 cents when above.

The provisional variant of this recipe runs at scope determination with the logical clock as its as-of timestamp, and its result is stored in `fee_quoted_cents`. Acceptance — again a `FirmAdmin` action, again requiring an `ACTIVE` client — moves `SCOPE_DETERMINED` to `ACCEPTED` and runs the final variant with the acceptance timestamp as its as-of, storing the result in `fee_current_cents`; whenever a superseding schedule window has taken effect between scope determination and acceptance, the final fee legitimately differs from the quote. Acceptance also stamps `accepted_at` with the logical clock, computes `due_at` as exactly `requested_turn_days` calendar days after `accepted_at`, and opens the order's workfile by filing an `ORDER_FORM` record. Both scope determination and acceptance advance the order's `version`.

### 3.4. Assignment and the Inspection Appointment Chain

Assignment moves an `ACCEPTED` order to `ASSIGNED`. A `FirmAdmin` may name the appraiser explicitly through `appraiser_id`, or omit it and let the firm's selector choose. Either way, the selectee must clear four gates. The appraiser's `status` must be `ACTIVE`, `standing` must not be `PANEL_SUSPENDED`, and `sanction_override` must be false — any failure is `ERR_APPRAISER_NOT_ASSIGNABLE`. An `ACTIVE` panel membership must exist for the order's client — otherwise `ERR_APPRAISER_NOT_ON_PANEL`. The license must cover the tier: `HIGH_VALUE` demands `CERTIFIED_RESIDENTIAL`, `COMPLEX` demands `LICENSED` or `CERTIFIED_RESIDENTIAL`, and `STANDARD` accepts any level — otherwise `ERR_LICENSE_LEVEL_INSUFFICIENT`. And `license_expiry` must fall strictly after the logical clock's date — otherwise `ERR_LICENSE_EXPIRED`.

When `appraiser_id` is omitted, the selector ranks every candidate clearing those four gates by `on_time_rate` descending — a null rate, meaning the appraiser has no completions yet, is treated as a perfect 1.0000 — then breaks ties by in-flight load ascending, counting the candidate's orders in `ASSIGNED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `IN_ANALYSIS`, `DRAFTING`, or `QC_REVIEW`, and finally by the appraiser record's `created_at` ascending. An empty candidate pool rejects the assignment with `ERR_NO_ELIGIBLE_APPRAISER`. A successful assignment records `assigned_appraiser_id` on the order and sets `requires_supervisor_cosign` to true exactly when the assignee is a `TRAINEE`.

For orders requiring inspection, the assignee or a `FirmAdmin` proposes an appointment with the `order_id`, the `appraiser_id`, and a window from `window_start` to `window_end`. The order must be `ASSIGNED` or `INSPECTION_SCHEDULED` — anything else is `ERR_INVALID_STATE`; `window_start` must fall strictly after the logical clock, failing with `ERR_WINDOW_IN_PAST`; and `window_end` must be strictly later than `window_start`, failing with `ERR_VALIDATION`. A new appointment starts `PROPOSED`. Whether `appraiser_id` matches the order's `assigned_appraiser_id` is deliberately not judged at proposal time — that check fires at confirmation.

Confirmation moves a `PROPOSED` appointment to `CONFIRMED` and can be performed by the appraiser or a `FirmAdmin`. The window must still lie strictly in the future (`ERR_WINDOW_IN_PAST`), the order must still be `ASSIGNED` or `INSPECTION_SCHEDULED` (`ERR_INVALID_STATE`), and the appointment's `appraiser_id` must equal the order's `assigned_appraiser_id` (`ERR_NOT_ASSIGNED_APPRAISER`). Confirmation also enforces a travel buffer: every appointment carries a buffered window from thirty minutes before its `window_start` to thirty minutes after its `window_end`, half-open, and the candidate's buffered window may not intersect the buffered window of any other `CONFIRMED` appointment belonging to the same appraiser. Because the interval is half-open, one buffer ending at the exact instant another begins is not an intersection. A violation is rejected with `ERR_APPOINTMENT_OVERLAP`. The first confirmation for an order automatically advances the order from `ASSIGNED` to `INSPECTION_SCHEDULED`.

A confirmed appointment can be rescheduled, returning it to `PROPOSED` with a replacement `window_start` and `window_end`; the new start must again be strictly after the logical clock (`ERR_WINDOW_IN_PAST`) and the end strictly after the start (`ERR_VALIDATION`), and the order remains `INSPECTION_SCHEDULED` throughout. Once the logical clock has reached `window_end`, the assigned appraiser completes the appointment — `CONFIRMED` to `COMPLETED`, with an earlier attempt failing as `ERR_WINDOW_IN_PAST` — which stamps the appointment's `completed_at`, moves the order from `INSPECTION_SCHEDULED` to `INSPECTED` with `inspection_completed_at` recorded, and files an `INSPECTION_NOTES` workfile record for the order. When the borrower fails to appear, marking the appointment `NO_SHOW` — open to the appraiser or a `FirmAdmin` — increments the appraiser's `no_show_count` and leaves the order in `INSPECTION_SCHEDULED`, where a fresh appointment is required. An appointment in `PROPOSED` or `CONFIRMED` may also be cancelled outright, landing in the terminal `CANCELLED` state, and the system applies that same landing when the order is cancelled (§3.9) or the assignee is stripped by the sanction cascade (§3.8). Appointments can be listed filtered by `order_id`, `appraiser_id`, or `status`.

Analysis begins when the assigned appraiser starts it: an inspected order moves from `INSPECTED` to `IN_ANALYSIS`, while a desktop order — one whose `requires_inspection` is false — skips the appointment chain entirely and moves from `ASSIGNED` to `IN_ANALYSIS` directly. Any other order state fails with `ERR_INVALID_STATE`, and any actor other than the order's assigned appraiser fails with `ERR_NOT_ASSIGNED_APPRAISER`.

### 3.5. Comparable Research and Adjustment Discipline

While the order is `IN_ANALYSIS`, the assigned appraiser builds the comparable set. Each comparable is created with the `order_id`, the comparable's `address`, its `sale_price_cents` (strictly positive), its `sale_date`, its `distance_miles` from the subject (zero or greater), and four signed adjustment lines — `site_adjustment_cents`, `gla_adjustment_cents`, `condition_adjustment_cents`, and `other_adjustment_cents` — with `other_adjustment_cents` defaulting to 0 when omitted. A comparable starts in `DRAFT`. The list view filters by `order_id` or `status`.

Derived figures are computed at creation, on every edit, and at verification, always in the same pinned order. Each of the four signed lines is rounded individually first: divided by 10000, rounded half-up to a whole number, and multiplied back by 10000, so every line lands on a whole hundred dollars before any summation takes place. Rounding the sum instead of the lines is non-conformant — the two orders of operation produce different cents. The comparable's `adjusted_price_cents` is then its `sale_price_cents` plus the sum of the four rounded lines. The `net_adjustment_pct` is the absolute value of that net sum divided by `sale_price_cents`, expressed as a percentage rounded half-up to two decimal places. The `gross_adjustment_pct` replaces the net sum with the sum of the four lines' absolute rounded values, divided by `sale_price_cents` and again expressed as a percentage rounded half-up to two decimal places. While a comparable remains `DRAFT` or `VERIFIED`, the appraiser may revise `sale_price_cents`, `distance_miles`, or any of the four adjustment lines, and every such edit recomputes the derived figures.

Verification moves a comparable from `DRAFT` to `VERIFIED` and is only available while the order is `IN_ANALYSIS` or `IN_REVISION`; any other order state is `ERR_INVALID_STATE`. Verification freezes the eligibility verdict against the logical clock at that moment. A comparable is eligible — `is_eligible` true — when its `net_adjustment_pct` is at most 15.00, its `gross_adjustment_pct` is at most 25.00, its `distance_miles` is at most 2.00, and its `sale_date` is no older than 365 days before the clock's date. All four boundaries are inclusive: a net of exactly 15.00, a gross of exactly 25.00, a distance of exactly 2.00 miles, and a sale exactly 365 days old all remain eligible. When the verdict is false, `ineligible_reasons` carries the applicable subset of `NET_ADJ_EXCEEDED` (net above 15.00), `GROSS_ADJ_EXCEEDED` (gross above 25.00), `DISTANCE_EXCEEDED` (distance above 2.00 miles), and `SALE_TOO_OLD` (sale date older than 365 days); the list is empty for an eligible comparable.

Locking — `VERIFIED` to `LOCKED` — is the appraiser's declaration that a comparable supports the value conclusion. It requires the order to be `IN_ANALYSIS`, `DRAFTING`, or `IN_REVISION` (`ERR_INVALID_STATE` otherwise), and it refuses an ineligible comparable with `ERR_COMP_INELIGIBLE`. A comparable still in `DRAFT` or `VERIFIED` may instead be excluded, moving it to the terminal `EXCLUDED` state. Locks are not permanent across a revision: when a revision request is accepted on the order, every `LOCKED` comparable returns to `VERIFIED` so the analysis can be reworked (§3.7).

### 3.6. Drafting, Quality Control, Signature, and Delivery

The report comes into existence once, and exactly once, per order. The appraiser creates it with the `order_id`, a `report_type` of `FORM_1004`, `FORM_1073`, or `FORM_1025`, and a `condition_rating` of `C1`, `C2`, `C3`, `C4`, `C5`, or `C6`. The order must be `IN_ANALYSIS`; because creation moves the order to `DRAFTING`, a second creation attempt finds the order no longer in that state and fails with `ERR_INVALID_STATE` — which is how the one-report-per-order rule is enforced. Creation requires at least three `LOCKED` eligible comparables on the order, failing with `ERR_INSUFFICIENT_LOCKED_COMPS` otherwise. The new report's `signing_appraiser_id` is set to the order's assigned appraiser, `revision_round` and `qc_fail_count` start at 0, the status begins at `DRAFT`, and a `COMP_DATA` workfile record is filed for the order.

The value conclusion is computed at creation over the order's `LOCKED`, eligible comparables. Each comparable carries a distance weight: 3 when its `distance_miles` is at most 0.50, 2 when at most 1.00, and 1 beyond that. The raw conclusion is the weighted mean — the sum of each weight times its comparable's `adjusted_price_cents`, divided by the sum of the weights — carried exactly, without intermediate rounding. The final `value_conclusion_cents` applies a single rounding: the mean, rounded half-up to the nearest 100000 cents — the nearest thousand dollars. No per-comparable rounding beyond the adjustment-line rounding of §3.5 is permitted.

When the draft is ready, the signing appraiser submits it for quality control. Submission is allowed from `DRAFT`, or from `UNDER_REVISION` during a revision cycle — any other report state is `ERR_INVALID_STATE` — and anyone other than the signing appraiser is `ERR_NOT_ASSIGNED_APPRAISER`. Submission re-derives `value_conclusion_cents` over the comparables `LOCKED` and eligible at that moment, still requiring at least three (`ERR_INSUFFICIENT_LOCKED_COMPS`), moves the report to `PENDING_QC`, and moves the order from `DRAFTING` to `QC_REVIEW` — or from `IN_REVISION` back to `QC_REVIEW` when the report was under revision.

Quality control is performed by a `QCReviewer`, and segregation of duties is enforced on both verdicts: the reviewer may not be the report's signing appraiser, nor its co-signer, with violations failing as `ERR_SOD_REVIEWER_CONFLICT`. A pass additionally requires the reviewer's identity to resolve to an appraiser record that exists, is `ACTIVE`, and holds `CERTIFIED_RESIDENTIAL` — anything less fails with `ERR_LICENSE_LEVEL_INSUFFICIENT`. A passing verdict records the acting reviewer's id in `reviewer_id` and moves the report from `PENDING_QC` to `QC_PASSED`. A failing verdict carries the reviewer's `notes`, increments `qc_fail_count`, returns the report to `DRAFT`, and moves the order from `QC_REVIEW` back to `IN_REVISION` when an `ACCEPTED` revision request exists on the order, or to `DRAFTING` otherwise.

Reports performed by trainees require a supervisor's countersignature before delivery. The co-sign action is performed by an `Appraiser` while the report is `PENDING_QC` or `QC_PASSED` — any other report state is `ERR_INVALID_STATE` — and records the acting appraiser as `co_signer_appraiser_id`. The co-signer must be the assignee's declared supervisor, meaning the appraiser named by the assignee's own `supervisor_id`, and must personally be `ACTIVE` and `CERTIFIED_RESIDENTIAL`; a mismatch on any of those conditions is rejected with `ERR_SUPERVISOR_SIGNATURE_MISMATCH`.

Delivery is performed by the signing appraiser from `QC_PASSED` and is gated four ways. The actor must be the signing appraiser (`ERR_NOT_ASSIGNED_APPRAISER`). When the order's `requires_supervisor_cosign` is set, `co_signer_appraiser_id` must be present (`ERR_SIGNATURE_COSIGN_REQUIRED`). The signing appraiser's `license_expiry` must fall strictly after the logical clock's date (`ERR_LICENSE_EXPIRED`). And the order's `open_complaint_count` must be zero (`ERR_COMPLIANCE_HOLD_ACTIVE`). Delivery moves the order to `DELIVERED` — from `QC_REVIEW` on the first pass, or from `IN_REVISION` on a revised report — stamps `first_delivered_at` when it was previously null and never again, files `REPORT_PDF` and `CERTIFICATION` workfile records, pins `retention_until` on every non-`PURGED` workfile record of the order per §3.8, and, when the delivery closes a revision cycle, resolves the order's `ACCEPTED` revision request to `RESOLVED`. Reports can be listed filtered by `order_id`, `status`, `signing_appraiser_id`, `co_signer_appraiser_id`, or `reviewer_id`.

### 3.7. Revision Requests and Reconsideration of Value

A delivered order can be challenged. A `ClientUser` — acting only on their own client's orders, else `ERR_NOT_RESOURCE_OWNER` — or a `FirmAdmin` opens a revision request against a `DELIVERED` order, with any other order state failing as `ERR_ORDER_NOT_DELIVERED`. The request supplies a `kind` of `CORRECTION` or `RECONSIDERATION_OF_VALUE`, a `detail` narrative, and the concurrency guard `expected_order_version` described in §2.8 — a stale view of the order fails with `ERR_STALE_ORDER_VERSION`, and the order's id travels in the request path, landing on the new request's `order_id`. A reconsideration of value additionally requires `submitted_value_cents`: strictly positive and different from the report's current `value_conclusion_cents`, with violations rejected as `ERR_VALIDATION`. A reconsideration must also be opened within ninety days of the order's `first_delivered_at`; a later attempt fails with `ERR_ROV_WINDOW_EXPIRED`, while a `CORRECTION` carries no such window. The new request starts `OPEN`, and if another request was already `OPEN` on the same order, the earlier one is moved to `SUPERSEDED` as part of the same write — which is exactly why the order's `version` advances at creation and why the concurrency guard exists.

A `FirmAdmin` accepts an `OPEN` request — the request must be `OPEN` and the order must be `DELIVERED`, with `ERR_INVALID_STATE` answering any deviation — and acceptance is a fan-out. The revision fee is read from the client's fee schedule for the order's tier effective as-of the order's `first_delivered_at`; when no window covers that instant, the retail fallback of 15000 cents applies. The charged amount is stored in `revision_fee_charged_cents` and added both to the order's `fee_current_cents` and to its running `revision_fees_collected_cents`. The order moves from `DELIVERED` to `IN_REVISION`, the report moves from `DELIVERED` to `UNDER_REVISION` with `revision_round` incremented by one, every `LOCKED` comparable on the order returns to `VERIFIED`, and a `REVISION_CORRESPONDENCE` workfile record is filed.

Alternatively, the firm rebuts an `OPEN` request, recording a required `rebuttal`; a rebuttal charges no fee and leaves both the order and the report in `DELIVERED`. An accepted request is resolved automatically when the revised report is delivered (§3.6), moving from `ACCEPTED` to `RESOLVED`. `REBUTTED`, `SUPERSEDED`, and `RESOLVED` are all terminal. Revision requests can be listed filtered by `order_id` or `status`.

### 3.8. Workfile Retention, Complaints, and the Sanction Cascade

The workfile is the order's evidentiary record. Each record carries the `order_id`, a `snapshot_type` of `ORDER_FORM`, `INSPECTION_NOTES`, `COMP_DATA`, `REPORT_PDF`, `CERTIFICATION`, or `REVISION_CORRESPONDENCE`, a system-stamped `recorded_at`, and a status that begins at `ACTIVE`. Most records are filed by the workflows themselves — acceptance files the `ORDER_FORM`, appointment completion files `INSPECTION_NOTES`, report creation files `COMP_DATA`, delivery files `REPORT_PDF` and `CERTIFICATION`, and revision acceptance files `REVISION_CORRESPONDENCE` — but a `FirmAdmin` may also add a record manually to any order that has not reached a terminal state; adding one to a completed or cancelled order is rejected as `ERR_INVALID_STATE`. Workfile records can be listed filtered by `order_id`, `snapshot_type`, or `status`.

Retention is pinned at first delivery, and not before: a record's `retention_until` stays null — and the record stays unpurgeable — until the order's first delivery. The standard pin is five calendar years after `first_delivered_at`, where year addition is calendar-based, preserving the month and day. When any complaint on the order has closed `CLOSED_SANCTIONED`, a judicial variant computes two calendar years after the latest such complaint's `closed_at`, and the pin becomes the later of the standard and the judicial dates; two otherwise-identical orders can therefore diverge in retention purely because one drew a sanctioned complaint. Records created after the pin — revision correspondence, most obviously — inherit the order's pinned `retention_until` at creation. Closing a complaint as sanctioned recomputes the pin on every non-`PURGED` record of the complaint's order.

Purging is the `ComplianceOfficer`'s prerogative and is triple-gated. The record must be `ACTIVE` — a record under `LEGAL_HOLD` cannot be purged, and any wrong state answers `ERR_INVALID_STATE`. Its `retention_until` must be set and must fall strictly before the logical clock, failing with `ERR_RETENTION_NOT_EXPIRED` otherwise — and a null pin, meaning the order was never delivered, can never pass this gate. The order's `open_complaint_count` must be zero (`ERR_COMPLIANCE_HOLD_ACTIVE`). A successful purge stamps `purged_at` and lands the record in the terminal `PURGED` state.

A board complaint arrives against a delivered or completed order — any other order state fails with `ERR_ORDER_NOT_DELIVERED` — and is filed by a `FirmAdmin` or a `ComplianceOfficer` with the `order_id`, the `respondent_appraiser_id` named in the inquiry, and a `description`. Intake stamps `received_at` with the logical clock, computes `response_due_at` as exactly 21 days later, increments the order's `open_complaint_count` by one, and sweeps every `ACTIVE` workfile record of the order into `LEGAL_HOLD`. While any complaint is open on an order, the order's reports cannot be delivered, the order cannot be completed, and its workfiles cannot be purged — each blocked with `ERR_COMPLIANCE_HOLD_ACTIVE`. Complaints can be listed filtered by `order_id`, `respondent_appraiser_id`, or `status`.

The response workflow belongs to the `ComplianceOfficer`. Drafting records `response_text` and moves the complaint from `RECEIVED` to `RESPONSE_DRAFTED`. Submission moves it from `RESPONSE_DRAFTED` to `RESPONSE_SUBMITTED` and is a hard deadline: the logical clock must be at or before `response_due_at`, and a submission after that instant fails with `ERR_RESPONSE_DEADLINE_PASSED`. Closing takes an `outcome` from `RESPONSE_SUBMITTED`: `NO_ACTION` closes the complaint to `CLOSED_NO_ACTION`, and `SANCTIONED` closes it to `CLOSED_SANCTIONED` — both terminal. Either close stamps `closed_at`, decrements the order's `open_complaint_count` by one, and, when that decrement brings the count to zero, returns every `LEGAL_HOLD` workfile record of the order to `ACTIVE`.

Closing with a sanction is the heaviest write in the system, and its links are worth enumerating in order. First, the respondent appraiser's `sanction_override` is set, forcing `standing` to `PANEL_SUSPENDED` until a `FirmAdmin` clears it (§3.2). Second, every `ACTIVE` panel membership of the respondent moves to `REMOVED`, and every order assigned to the respondent in a working state — `ASSIGNED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `IN_ANALYSIS`, `DRAFTING`, or `QC_REVIEW` — falls back to `ACCEPTED` with `assigned_appraiser_id` nulled and `requires_supervisor_cosign` reset to false. Third, each such unassigned order's `PROPOSED` or `CONFIRMED` appointments are moved to `CANCELLED`. Finally, the complaint's own order has the retention of its workfiles recomputed under the judicial variant above. The hold release works exactly as in the no-action close.

### 3.9. Cancellations, Fee Adjustments, and Order Completion

An order can be cancelled while it is `RECEIVED`, `SCOPE_DETERMINED`, `ACCEPTED`, or `ASSIGNED`; any later state is rejected with `ERR_INVALID_STATE`. The call records a `reason`. A `ClientUser` may cancel only their own client's orders — otherwise `ERR_NOT_RESOURCE_OWNER` — and only while the order is `RECEIVED` or `SCOPE_DETERMINED`, a later state again answering `ERR_INVALID_STATE`; a `FirmAdmin` faces no such narrowing. The cancellation fee, stored in `cancellation_fee_cents`, is zero when cancelling from `RECEIVED` or `SCOPE_DETERMINED`; from `ACCEPTED` or `ASSIGNED` it is half of `fee_current_cents`, rounded half-up to whole cents — a 45500-cent fee yields a 22750-cent cancellation fee. Cancelling also moves every `PROPOSED` or `CONFIRMED` appointment on the order to `CANCELLED`, a cascade reachable in practice once the order has been `ASSIGNED`. `CANCELLED` is terminal.

While an order is live, a `FirmAdmin` may post fee adjustments carrying a `kind` of `SURCHARGE` or `WAIVER`, an `amount_cents` that is strictly positive, and a `reason`. A `SURCHARGE` adds the amount to `fee_current_cents` and accumulates it into `surcharge_total_cents`. A `WAIVER` subtracts the amount from `fee_current_cents` and accumulates it into `waived_total_cents`, and a waiver whose amount exceeds the order's current `fee_current_cents` is rejected with `ERR_FEE_WAIVER_EXCEEDS_BALANCE`. Adjustments against a `CANCELLED` or `COMPLETED` order are rejected with `ERR_INVALID_STATE`. Every adjustment advances the order's `version`.

Completion is the order's final gate, performed by a `FirmAdmin` from `DELIVERED`. Three gates guard it. No revision request on the order may be `OPEN` or `ACCEPTED`; one being so fails with `ERR_INVALID_STATE`. The order's `open_complaint_count` must be zero, failing with `ERR_COMPLIANCE_HOLD_ACTIVE` otherwise. And the workfile must be complete: the order's non-`PURGED` records must cover `ORDER_FORM`, `COMP_DATA`, `REPORT_PDF`, and `CERTIFICATION`, plus `INSPECTION_NOTES` when the order's `requires_inspection` is true — any gap fails with `ERR_WORKFILE_INCOMPLETE`. Completion stamps `completed_at` and lands the order in the terminal `COMPLETED` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`, as do reads. Unless otherwise noted, create and modify operations return the created or updated resource in the envelope's `data` field. The table below is a summary only — request payloads, response details, preconditions, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | FirmAdmin |
| POST | `/appraisal/clients` | Create a lender/AMC client | FirmAdmin |
| GET | `/appraisal/clients/{id}` | Read a client; ClientUser limited to their own id | FirmAdmin, ClientUser |
| GET | `/appraisal/clients` | List clients | FirmAdmin |
| POST | `/appraisal/clients/{id}/suspend` | Suspend an ACTIVE client | FirmAdmin |
| POST | `/appraisal/clients/{id}/reactivate` | Reactivate a SUSPENDED client | FirmAdmin |
| POST | `/appraisal/clients/{id}/terminate` | Terminate a client and remove its active panel memberships | FirmAdmin |
| POST | `/appraisal/appraisers` | Create an appraiser | FirmAdmin |
| GET | `/appraisal/appraisers/{id}` | Read an appraiser | FirmAdmin, Appraiser, QCReviewer |
| GET | `/appraisal/appraisers` | List appraisers | FirmAdmin |
| POST | `/appraisal/appraisers/{id}/deactivate` | Deactivate an appraiser with no open assignments | FirmAdmin |
| POST | `/appraisal/appraisers/{id}/reactivate` | Reactivate an appraiser with an unexpired license | FirmAdmin |
| POST | `/appraisal/appraisers/{id}/clear-sanction` | Clear a board-sanction override | FirmAdmin |
| GET | `/appraisal/appraisers/{id}/scorecard` | Read the computed panel scorecard | FirmAdmin, Appraiser |
| POST | `/appraisal/panel-memberships` | Add an appraiser to a client's panel | FirmAdmin |
| GET | `/appraisal/panel-memberships/{id}` | Read a panel membership | FirmAdmin |
| POST | `/appraisal/panel-memberships/{id}/remove` | Remove a membership from the panel | FirmAdmin |
| GET | `/appraisal/panel-memberships` | List panel memberships | FirmAdmin |
| POST | `/appraisal/fee-schedules` | Create a fee window for a client and tier; closes the prior open-ended window | FirmAdmin |
| GET | `/appraisal/fee-schedules/{id}` | Read a fee schedule | FirmAdmin |
| GET | `/appraisal/fee-schedules` | List fee schedules | FirmAdmin |
| POST | `/appraisal/orders` | Place an appraisal order | ClientUser, FirmAdmin |
| GET | `/appraisal/orders/{id}` | Read an order | FirmAdmin, ClientUser, Appraiser, QCReviewer |
| GET | `/appraisal/orders` | List orders | FirmAdmin |
| POST | `/appraisal/orders/{id}/determine-scope` | Determine complexity tier, inspection need, and provisional fee | FirmAdmin |
| POST | `/appraisal/orders/{id}/accept` | Accept the order, locking the final fee and due date | FirmAdmin |
| POST | `/appraisal/orders/{id}/assign` | Assign an appraiser explicitly or via the panel selector | FirmAdmin |
| POST | `/appraisal/orders/{id}/cancel` | Cancel the order with a state-dependent cancellation fee | FirmAdmin, ClientUser |
| POST | `/appraisal/orders/{id}/start-analysis` | Begin analysis on an inspected or desktop order | Appraiser |
| POST | `/appraisal/orders/{id}/complete` | Complete a delivered order after all gates pass | FirmAdmin |
| POST | `/appraisal/orders/{id}/fee-adjustments` | Post a surcharge or waiver against the order's fee | FirmAdmin |
| POST | `/appraisal/appointments` | Propose an inspection window | Appraiser, FirmAdmin |
| GET | `/appraisal/appointments/{id}` | Read an appointment | FirmAdmin, Appraiser |
| GET | `/appraisal/appointments` | List appointments | FirmAdmin, Appraiser |
| POST | `/appraisal/appointments/{id}/confirm` | Confirm a proposed window, enforcing the travel buffer | Appraiser, FirmAdmin |
| POST | `/appraisal/appointments/{id}/reschedule` | Replace a confirmed window, returning it to proposed | Appraiser, FirmAdmin |
| POST | `/appraisal/appointments/{id}/complete` | Complete a confirmed appointment after its window ends | Appraiser |
| POST | `/appraisal/appointments/{id}/no-show` | Mark a confirmed appointment as a borrower no-show | Appraiser, FirmAdmin |
| POST | `/appraisal/appointments/{id}/cancel` | Cancel a proposed or confirmed appointment | Appraiser, FirmAdmin |
| POST | `/appraisal/comparables` | Add a comparable to an order in analysis | Appraiser |
| GET | `/appraisal/comparables/{id}` | Read a comparable | FirmAdmin, Appraiser |
| GET | `/appraisal/comparables` | List comparables | FirmAdmin, Appraiser |
| PATCH | `/appraisal/comparables/{id}` | Edit price, distance, or adjustments on a draft or verified comparable | Appraiser |
| POST | `/appraisal/comparables/{id}/verify` | Verify a draft comparable and compute eligibility | Appraiser |
| POST | `/appraisal/comparables/{id}/lock` | Lock a verified, eligible comparable | Appraiser |
| POST | `/appraisal/comparables/{id}/exclude` | Exclude a draft or verified comparable | Appraiser |
| POST | `/appraisal/reports` | Create the order's report and compute the value conclusion | Appraiser |
| GET | `/appraisal/reports/{id}` | Read a report | FirmAdmin, Appraiser, QCReviewer, ClientUser |
| GET | `/appraisal/reports` | List reports | FirmAdmin |
| POST | `/appraisal/reports/{id}/submit-for-qc` | Submit a draft or revised report for quality control | Appraiser |
| POST | `/appraisal/reports/{id}/qc-pass` | Pass a report under review | QCReviewer |
| POST | `/appraisal/reports/{id}/qc-fail` | Fail a report under review | QCReviewer |
| POST | `/appraisal/reports/{id}/co-sign` | Co-sign a report as the assignee's supervisor | Appraiser |
| POST | `/appraisal/reports/{id}/deliver` | Deliver a passed report to the client | Appraiser |
| POST | `/appraisal/orders/{id}/revision-requests` | Open a revision request or reconsideration of value | ClientUser, FirmAdmin |
| GET | `/appraisal/revision-requests/{id}` | Read a revision request | FirmAdmin, ClientUser, Appraiser |
| GET | `/appraisal/revision-requests` | List revision requests | FirmAdmin, ClientUser |
| POST | `/appraisal/revision-requests/{id}/accept` | Accept an open request, charging the revision fee and reopening the order | FirmAdmin |
| POST | `/appraisal/revision-requests/{id}/rebut` | Rebut an open request with a reasoned response | FirmAdmin |
| POST | `/appraisal/workfile-records` | Manually add a workfile record to a non-terminal order | FirmAdmin |
| GET | `/appraisal/workfile-records/{id}` | Read a workfile record | FirmAdmin, ComplianceOfficer |
| GET | `/appraisal/workfile-records` | List workfile records | FirmAdmin, ComplianceOfficer |
| POST | `/appraisal/workfile-records/{id}/purge` | Purge a workfile record past its retention date | ComplianceOfficer |
| POST | `/appraisal/complaints` | Intake a board complaint on a delivered or completed order | FirmAdmin, ComplianceOfficer |
| GET | `/appraisal/complaints/{id}` | Read a complaint | FirmAdmin, ComplianceOfficer |
| GET | `/appraisal/complaints` | List complaints | FirmAdmin, ComplianceOfficer |
| POST | `/appraisal/complaints/{id}/draft-response` | Draft the response to a received complaint | ComplianceOfficer |
| POST | `/appraisal/complaints/{id}/submit-response` | Submit the drafted response by its deadline | ComplianceOfficer |
| POST | `/appraisal/complaints/{id}/close` | Close a submitted complaint with an outcome | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPRAISER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COMPARABLE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_REVISION_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_WORKFILE_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_SCHEDULE_NOT_FOUND` | 404 Not Found |
| `ERR_PANEL_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERED` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CLIENT_VERSION` | 412 Precondition Failed |
| `ERR_CLIENT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_APPRAISER_NOT_ON_PANEL` | 422 Unprocessable Entity |
| `ERR_NOT_ASSIGNED_APPRAISER` | 422 Unprocessable Entity |
| `ERR_SUPERVISOR_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_LICENSE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_LICENSE_LEVEL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SOD_REVIEWER_CONFLICT` | 422 Unprocessable Entity |
| `ERR_SIGNATURE_COSIGN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SUPERVISOR_SIGNATURE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMPLIANCE_HOLD_ACTIVE` | 422 Unprocessable Entity |
| `ERR_WORKFILE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DESKTOP_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_OVERLAP` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_ROV_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RESPONSE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_RETENTION_NOT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PANEL_MEMBERSHIP` | 422 Unprocessable Entity |
| `ERR_INVALID_TIER_OVERRIDE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LOCKED_COMPS` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_APPRAISER` | 422 Unprocessable Entity |
| `ERR_FEE_WAIVER_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_APPRAISER_HAS_OPEN_ASSIGNMENTS` | 422 Unprocessable Entity |
| `ERR_COMP_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_APPRAISER_NOT_ASSIGNABLE` | 422 Unprocessable Entity |

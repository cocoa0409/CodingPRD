# Moving-Labor Marketplace API — Product Requirements Document

## 1. Introduction

The Moving-Labor & Loading Marketplace API powers a two-sided platform in the spirit of services such as HireAHelper and Dolly, where customers book crews of vetted helpers to load, unload, or move belongings — optionally with a truck and a range of add-on services. A booking begins as an instant, itemized quote and, once accepted inside a limited booking window, becomes a scheduled job that a crew executes on the ground.

The platform must reconcile several competing concerns at once. It is fundamentally a **pricing engine**: labor, crew surcharges, truck fees, taxed add-ons, weekend surge pricing, and a platform service fee all combine into a single customer charge, first as an estimate at quote time and again as a final figure once the actual hours worked are known. It is also a **scheduling system** operating over time windows, so it must guard against double-booking helpers and trucks, honor booking-window expiry, and price cancellations by how much notice the customer gives. Layered on top are helper vetting and reputation, damage claims settled against insurance policies, tips and ratings, and the payout ledger that ultimately pays each helper. This document specifies the API's resources, lifecycles, calculations, and the exact rules that govern each transition.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. The business workflows that build on these principles are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles: `Customer`, `Helper`, `Dispatcher`, and `Admin`. When an authenticated caller attempts an operation their role is not permitted to perform, or acts on a resource they do not own, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two of the roles are **entity-backed**, meaning the `X-User-ID` value is the identifier of a persisted profile and is used for ownership checks:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. A job records its booking customer in `customer_id`; ownership checks on any resource that references a `Customer` compare that foreign key to `X-User-ID`. A customer manages only the jobs they created and the claims and ratings they file against them.
- When `X-User-Role` is `Helper`, `X-User-ID` is the `id` of the acting `Helper`. Ownership checks on an `Assignment` compare the assignment's `helper_id` to `X-User-ID`; a helper may only check in or check out of an assignment they own.

The remaining two roles are **opaque** operator identities:

- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; a dispatcher performs operational crewing across all jobs.
- When `X-User-Role` is `Admin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. Administrators operate platform-wide and are not scoped to any single resource owner.

Role authority is summarized in the endpoint table of Section 4; the workflows in Section 3 name the role responsible for each action.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` reflects the total number of matching resources before pagination and `has_more` indicates whether further pages remain.

List endpoints also accept filter parameters that narrow the result set by a foreign key or state. Jobs may be filtered by `customer_id`, `rate_card_id`, `insurance_policy_id`, `truck_id`, and `status`. Add-ons may be filtered by `job_id`. Quotes may be filtered by `job_id` and `status`. Assignments may be filtered by `job_id`, `helper_id`, and `status`. Claims may be filtered by `job_id`, `responsible_helper_id`, and `status`. Ratings may be filtered by `job_id` and `helper_id`. Payouts may be filtered by `job_id`, `helper_id`, and `status`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value on creation and increments by one on every mutation. It is the basis for optimistic concurrency control described in Section 2.6.

`Customer`, `Helper`, `Truck`, `Job`, `AddOn`, `Quote`, `Assignment`, `Claim`, `Rating`, and `Payout` all carry the full set above. Two configuration resources are exceptions: a `RateCard` and an `InsurancePolicy` are immutable reference data and therefore carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field.

### 2.5. Monetary Values, Rates, and Rounding

Nearly all monetary amounts in the system are expressed as integer cents, and every field whose name ends in `_cents` is an integer count of cents. Wherever a calculation is specified as rounding "half up," the result is rounded to the nearest cent with ties resolved upward (a fractional value of exactly one-half rounds away from zero). Rounding is applied at each step the calculation rules in Section 3 pin explicitly; the order of rounding is significant and must be followed as written, because rounding a running total at a different point can change the result by a cent.

Rate and configuration fields that are fractions or multipliers — for example `crew_surcharge_pct`, `peak_surge_multiplier`, and `coverage_pct` — are stored as supplied and are not themselves rounded to cents. Two derived reputation figures are not monetary: `rating_avg` is rounded half up to two decimal places, and integer counters such as `rating_count`, `no_show_count`, and `active_assignment_count` are exact integers.

### 2.6. Optimistic Concurrency on Booking

Because a customer may re-quote a job repeatedly before committing to it, the booking step is guarded by optimistic concurrency control. A request to accept a quote and book a job must carry `expected_job_version`, a non-optional field whose value is the `version` of the target job the client last observed. The server compares `expected_job_version` against the job's current `version`. If they do not match — for instance because another writer re-quoted the job after the client read it, which supersedes the previously `ACTIVE` quote and advances `version` — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from committing against a quote it has not actually observed. Booking is the only operation that takes a version field; no other endpoint requires `expected_job_version`.

### 2.7. Cascading Consistency and Derived-Field Reconciliation

Many operations touch more than one resource. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` incremented; when the operation also mutates related resources, each of those is likewise updated and re-versioned. Several fields are **derived**: they are never written directly by a client but are recomputed from the current state of related resources whenever a triggering event occurs. A `Helper` maintains four such counters — `rating_avg`, `rating_count`, `no_show_count`, `active_assignment_count`, and the running `lifetime_payout_cents` — each recomputed from the helper's ratings, assignments, and payouts. A `Customer` maintains `wallet_credit_cents`, recomputed from approved claims. The precise recomputation rules live with the workflows that trigger them in Section 3.

### 2.8. Nested Resource Retrieval and Validation Ordering

When an endpoint references resources — whether by an identifier in the URL path or by a foreign key in the request body — the server validates existence left-to-right, path identifiers first and then body foreign keys, and rejects the first missing reference with `ERR_NOT_FOUND` (HTTP 404). Validation across all endpoints follows a fixed priority so that failures surface deterministically:

1. Authentication of the request headers is checked first; missing or unknown credentials yield `ERR_UNAUTHENTICATED` (401).
2. Authorization is checked next; a role not permitted for the operation, or an entity-backed owner acting on a resource they do not own, yields `ERR_FORBIDDEN` (403).
3. Existence of every referenced resource is checked next, yielding `ERR_NOT_FOUND` (404).
4. For a state-transition operation, the target resource's current state is checked; an operation attempted from an ineligible state yields `ERR_INVALID_STATE` (409).
5. Body-level request validity and the domain-specific business rules described in Section 3 are checked last, in the order those sections describe.

Malformed request bodies — a missing required field, a value of the wrong type, or an enum value outside the allowed set — are rejected with `ERR_INVALID_REQUEST` (HTTP 422).

### 2.9. The Logical Service Clock

All time-sensitive rules — booking-window expiry, cancellation notice, helper and truck availability windows — are evaluated against a server-managed logical clock rather than real wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and before it is ever set it holds that default; it never advances on its own. An administrator may advance the clock by supplying a target instant in the `to_iso8601` field of the clock-setting capability, after which all temporal comparisons use the new value. This makes booking windows, cancellation fees, and overlap checks fully deterministic under test.

## 3. Business Logic & Workflows

### 3.1. Customer, Helper, and Configuration Setup

An administrator provisions the platform's participants and reference data. Creating a `Customer` requires a `display_name` and an `email`; the customer's `wallet_credit_cents` is initialized to 0 and only ever grows through approved insurance claims (Section 3.8).

A `Helper` profile is created by an administrator with a `display_name`, an `email`, a `base_hourly_rate_cents` (the per-hour amount the platform pays this helper, which forms the basis of their payout), and an optional `skill_tier` that is one of `STANDARD` or `PRO` and defaults to `STANDARD`. Every new helper begins in `vetting_status` `PENDING_REVIEW`. A helper's reputation and workload fields — `rating_avg`, `rating_count`, `no_show_count`, `active_assignment_count`, and `lifetime_payout_cents` — all start at 0 and are maintained by the system thereafter.

Administrators also define the pricing and coverage reference data. A `RateCard` is created with a `name`, a `job_type` of `LOAD`, `UNLOAD`, or `MOVE`, a customer-facing `base_hourly_rate_cents` charged per helper per hour, a `min_billable_hours` floor, a `crew_surcharge_pct` fractional surcharge, a `peak_surge_multiplier` for weekend windows, and a flat `truck_fee_cents`. An `InsurancePolicy` is created with a `name`, a `tier` of `BASIC` or `FULL`, a `coverage_cap_cents` ceiling, a `deductible_cents`, and a `coverage_pct` fraction. A `Truck` is created with a `name`, a `capacity_cuft` cargo capacity in cubic feet, and an internal `daily_rate_cents`.

### 3.2. Helper Vetting Lifecycle

Before a helper may be crewed, an administrator must vet them. Vetting is driven by a `decision` field carrying one of four values. A helper in `PENDING_REVIEW` may be moved with an `APPROVE` decision to `APPROVED`, which makes them eligible to be assigned, or with a `REJECT` decision to `REJECTED`, which is terminal. An `APPROVED` helper may be moved to `SUSPENDED` with a `SUSPEND` decision, and a `SUSPENDED` helper may be returned to `APPROVED` with a `REINSTATE` decision. Any vet decision requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

Suspension is not merely a status change. When a helper transitions from `APPROVED` to `SUSPENDED` — whether by an administrator's `SUSPEND` decision or automatically as described in Section 3.9 — every one of that helper's assignments currently in status `ASSIGNED` is transitioned `ASSIGNED → RELEASED`, and each such release decrements that helper's `active_assignment_count`, which is recomputed as the number of the helper's assignments whose status is `ASSIGNED`, `CHECKED_IN`, or `CHECKED_OUT`.

### 3.3. Building and Pricing a Job

A `Customer` creates a job, which begins in status `DRAFT`. The creation payload supplies the `rate_card_id` of the pricing card to use, the `insurance_policy_id` selected for coverage, the `job_type` (`LOAD`, `UNLOAD`, or `MOVE`), the `crew_size` (the number of helpers required), the customer-estimated `estimated_hours`, the scheduled `window_start` and `window_end`, and an optional `truck_required` flag that defaults to false. The job's `customer_id` is taken from the acting customer's `X-User-ID`. At creation the system validates that `job_type` equals the referenced rate card's `job_type`, that `crew_size` is at least 1, that `estimated_hours` is greater than 0, and that `window_end` is strictly later than `window_start`; any violation is rejected with `ERR_INVALID_REQUEST`. The `truck_id`, `actual_hours`, `estimated_total_cents`, and `final_total_cents` all begin unset, and `cancellation_fee_cents` begins at 0.

While a job is still `DRAFT`, the customer may attach add-on lines. An `AddOn` records the `job_id` it belongs to (taken from the path), an `addon_type` of `PACKING_MATERIALS`, `HEAVY_ITEM`, `STAIRS`, `LONG_CARRY`, or `ASSEMBLY`, a `quantity` of at least 1, and a pre-tax `unit_fee_cents` per unit. Each line's `line_total_cents` is computed at creation by multiplying `unit_fee_cents` by `quantity`, multiplying the product by one plus the add-on tax rate of 8.5%, and rounding that result half up to whole cents. This per-line rounding is deliberate: the taxed lines are each rounded first and then summed, never summed and rounded once, because the two orders can differ by a cent.

**Requesting a quote.** When the customer requests a quote on a `DRAFT` job, it transitions `DRAFT → QUOTED` and a new `Quote` is created in status `ACTIVE`, carrying the job's full price breakdown and incrementing the job's `version` by one. Requesting a quote again while the job is `QUOTED` is a permitted self-loop: the job's current `ACTIVE` quote transitions `ACTIVE → SUPERSEDED`, a fresh `ACTIVE` quote is created, and `version` is incremented again. The quote records `job_id`, and its computed components `base_labor_cents`, `truck_fee_cents`, `addons_total_cents`, `surge_multiplier`, `subtotal_cents`, `service_fee_cents`, and `total_cents`, plus an `expires_at` and a `status`.

The price on a quote is computed as follows, using the customer's `estimated_hours` as the hours input. First, the billable hours are the greater of that hours input and the rate card's `min_billable_hours`. The raw base labor is the rate card's `base_hourly_rate_cents` multiplied by the job's `crew_size` and by the billable hours, rounded half up to cents. If `crew_size` is at least 3, the crew surcharge applies: the base labor becomes the raw base labor multiplied by one plus the rate card's `crew_surcharge_pct`, rounded half up to cents; if `crew_size` is below 3, the base labor equals the raw figure with no surcharge. This crew-adjusted amount is stored as `base_labor_cents`. The truck fee component `truck_fee_cents` equals the rate card's `truck_fee_cents` when the job's `truck_required` is true and is 0 otherwise. The add-ons total `addons_total_cents` is the sum of the per-line `line_total_cents` over all of the job's add-ons. The pre-surge `subtotal_cents` is the sum of `base_labor_cents`, `truck_fee_cents`, and `addons_total_cents`. The `surge_multiplier` is the rate card's `peak_surge_multiplier` when the job's `window_start` falls on a Saturday or Sunday in UTC, and is 1.0 on weekdays. The surged amount is the subtotal multiplied by the surge multiplier, rounded half up to cents. The `service_fee_cents` is that surged amount multiplied by the platform service-fee rate of 15%, rounded half up to cents. Finally, `total_cents` is the surged amount plus `service_fee_cents`. Every quote's `expires_at` is its `created_at` advanced by the booking-window length, and the quote's `status` starts as `ACTIVE`.

### 3.4. Booking, Rescheduling, and Cancellation

**Booking.** A customer commits to a `QUOTED` job by accepting its active quote, which transitions the job `QUOTED → BOOKED`. The request names the `quote_id` being accepted and carries `expected_job_version` for the concurrency check of Section 2.6. Booking succeeds only if the job is `QUOTED`, the referenced `quote_id` is the job's current `ACTIVE` quote, the booking window is still open, and `expected_job_version` matches the job's `version`. If the referenced quote is not the job's current `ACTIVE` quote, the request is rejected with `ERR_QUOTE_NOT_ACTIVE`. If the logical clock has reached or passed the quote's `expires_at`, the booking window has closed and the request is rejected with `ERR_QUOTE_EXPIRED`; the window is open only while the current time is strictly before `expires_at`. A version mismatch yields `ERR_STALE_VERSION` as described above. On success, the accepted quote transitions `ACTIVE → ACCEPTED`, the job's `estimated_total_cents` is set to that quote's `total_cents`, and the job's `version` is incremented by one.

**Rescheduling.** A `BOOKED` job may be rescheduled by its customer, which is a self-loop leaving the job `BOOKED`. The request supplies a new `window_start` and `window_end`; the new `window_end` must be strictly later than the new `window_start`, and the new `window_start` must be strictly later than the current logical time. On success the job's `window_start` and `window_end` are updated and its `version` is incremented by one.

**Cancellation.** A customer may cancel a job that is either `QUOTED` or `BOOKED`, transitioning it to `CANCELLED`. The cancellation fee depends on the originating state. Cancelling a `QUOTED` job is free: `cancellation_fee_cents` is set to 0, `final_total_cents` is set to 0, and the job's `ACTIVE` quote transitions `ACTIVE → SUPERSEDED`. Cancelling a `BOOKED` job is priced by notice: the hours of notice are the difference between the job's `window_start` and the current logical time expressed in hours (seconds difference divided by 3600). If that notice is at least 24 hours — the boundary of exactly 24 hours before `window_start` is treated as free — then `cancellation_fee_cents` is 0; otherwise it is the job's `estimated_total_cents` multiplied by 20%, rounded half up to cents. Either way `final_total_cents` is set equal to `cancellation_fee_cents`. Cancelling a booked job also releases the crew and truck: every assignment of the job in status `ASSIGNED` or `CHECKED_IN` transitions to `RELEASED`, each such release decrementing the corresponding helper's `active_assignment_count`, and the job's `truck_id` is cleared.

### 3.5. Crewing: Assignments and Attendance

A `Dispatcher` crews a job by creating assignments. An `Assignment` records the `job_id` and `helper_id` being crewed and an optional `role` of `LEAD` or `CREW` that defaults to `CREW`; it starts in status `ASSIGNED`. Creating an assignment recomputes the helper's `active_assignment_count`. Several checks guard assignment creation, evaluated in this order after the standard existence checks: the helper must be approved, then the job's crew slots must not be full, then the helper must be available in the requested window. If the helper's `vetting_status` is anything other than `APPROVED`, the request is rejected with `ERR_HELPER_NOT_APPROVED`. The number of the job's assignments in the count-eligible states (`ASSIGNED`, `CHECKED_IN`, or `CHECKED_OUT`) may not exceed the job's `crew_size`; an attempt to add one beyond that is rejected with `ERR_CREW_FULL`. Finally, the helper must have no other non-released assignment whose job window overlaps the target job's window, where overlap is judged on a half-open interval from window start up to but not including window end, extended by a 60-minute travel buffer; a conflict is rejected with `ERR_HELPER_UNAVAILABLE`.

Once crewed, the helper who owns an assignment drives its attendance. A helper checks in on an assignment that is `ASSIGNED`, transitioning it `ASSIGNED → CHECKED_IN`, and later checks out from a `CHECKED_IN` assignment, transitioning it `CHECKED_IN → CHECKED_OUT`; both actions require that the acting helper's `X-User-ID` equal the assignment's `helper_id`. A dispatcher may instead mark an `ASSIGNED` helper as a no-show, transitioning the assignment `ASSIGNED → NO_SHOW`; this recomputes the helper's `no_show_count` (an increment) and their `active_assignment_count` (a decrement, since `NO_SHOW` is not a count-eligible state). Assignments may also be moved to `RELEASED` by the system as a side effect of helper suspension or job cancellation, and each such release recomputes the affected helper's `active_assignment_count`.

### 3.6. Executing and Completing a Job

Before or during a booked job, a dispatcher may attach a truck, setting the job's `truck_id`. A truck may be assigned only if it has no other job in status `BOOKED` or `IN_PROGRESS` whose window collides with the target job's window; unlike the helper check, the truck overlap is judged on the closed interval between window start and window end with no travel buffer. A collision is rejected with `ERR_TRUCK_UNAVAILABLE`.

A dispatcher starts a `BOOKED` job, transitioning it `BOOKED → IN_PROGRESS`. Starting requires that at least one assignment for the job be in status `CHECKED_IN`; if no crew member has checked in, the request is rejected with `ERR_NO_CREW_CHECKED_IN`. When the work is done, the dispatcher completes the `IN_PROGRESS` job, transitioning it `IN_PROGRESS → COMPLETED`. Completion supplies `actual_hours`, which must be greater than 0; the job's `actual_hours` is stored and its `final_total_cents` is computed by the same pricing procedure used for the quote, but with `actual_hours` substituted for the estimated hours as the hours input — the billable-hours floor, crew surcharge, truck fee, taxed add-ons, weekend surge, and service fee all apply exactly as in Section 3.3.

### 3.7. Settlement and Payouts

An administrator settles a `COMPLETED` job, transitioning it `COMPLETED → SETTLED`. Settlement pays the crew: for each assignment of the job in status `CHECKED_OUT`, a `Payout` is created in status `RELEASED`, recording the `job_id`, the `helper_id`, and the computed amounts. A payout's `base_pay_cents` is the helper's `base_hourly_rate_cents` multiplied by the job's `actual_hours`, rounded half up to cents. Its `tip_cents` is the sum of the `tip_cents` across all ratings for this same job and helper. An on-time bonus applies when the job's `actual_hours` is less than or equal to its `estimated_hours`: in that case `bonus_cents` is `base_pay_cents` multiplied by 5%, rounded half up to cents; otherwise `bonus_cents` is 0. The `total_payout_cents` is the sum of `base_pay_cents`, `tip_cents`, and `bonus_cents`. As each payout is created, the paid helper's `lifetime_payout_cents` is recomputed as the sum of `total_payout_cents` over all of that helper's payouts still in status `RELEASED` (payouts in status `REVERSED` are excluded).

A payout that has been released may later be reversed. An administrator may reverse a `RELEASED` payout directly, and the system reverses one automatically as a consequence of an approved damage claim (Section 3.8); either way the payout transitions `RELEASED → REVERSED`, and the affected helper's `lifetime_payout_cents` is recomputed to exclude the reversed amount.

### 3.8. Damage Claims and Insurance Settlement

A customer files a `Claim` against a job when belongings are damaged. The claim records the `job_id`, a free-text `damage_description`, the `claimed_amount_cents`, and an optional `responsible_helper_id` naming a helper blamed for the damage; it begins in status `FILED`. Its `approved_amount_cents` and `insurance_covered_cents` begin unset and are computed only at approval.

A claim moves through review under administrator control: a `FILED` claim is moved to `UNDER_REVIEW`, and from `UNDER_REVIEW` it is either approved to `APPROVED` or denied to `DENIED`. Approval is gated on coverage: the claim's `claimed_amount_cents` must not exceed the job's insurance policy's `coverage_cap_cents`, and an attempt to approve a claim that exceeds the cap is rejected with `ERR_CLAIM_EXCEEDS_COVERAGE`.

On approval, the settlement is computed against the job's `InsurancePolicy`. The `approved_amount_cents` is the lesser of the `claimed_amount_cents` and the policy's `coverage_cap_cents`. The covered amount then depends on the policy `tier`. Under the `BASIC` tier, `insurance_covered_cents` is the approved amount minus the policy's `deductible_cents`, but never less than 0 — the deductible is subtracted with no percentage haircut. Under the `FULL` tier, `insurance_covered_cents` is the approved amount multiplied by the policy's `coverage_pct`, rounded half up to cents, with no deductible. The approving side effects then cascade: the customer's `wallet_credit_cents` is recomputed as the sum of `insurance_covered_cents` over all `APPROVED` claims filed on that customer's jobs. Additionally, if the claim carries a `responsible_helper_id` and that helper has a `RELEASED` payout for this same job, that payout is transitioned `RELEASED → REVERSED`, which in turn recomputes the helper's `lifetime_payout_cents`.

### 3.9. Ratings, Tips, and Reputation

After a job, a customer rates a helper. A `Rating` records the `job_id`, the `helper_id`, a `stars` value from 1 to 5, an optional `tip_cents` for the helper that defaults to 0, and an optional free-text `comment` that defaults to unset. A `stars` value outside the range 1 through 5 is rejected with `ERR_INVALID_REQUEST`. The tip recorded here is later folded into the helper's payout at settlement, as described in Section 3.7.

Filing a rating recomputes the helper's reputation. The helper's `rating_count` becomes the number of ratings referencing that helper, and `rating_avg` becomes the mean of the `stars` across those ratings, rounded half up to two decimal places (and defined as 0 when the helper has no ratings). A low average triggers automatic discipline: if, after the new rating, the helper's `rating_avg` is below 2.0 and the helper is currently `APPROVED`, the helper is automatically transitioned `APPROVED → SUSPENDED`, which carries the same release cascade over the helper's `ASSIGNED` assignments described in Section 3.2.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state transitions and the clock-setting capability — return `200 OK`. Request and response bodies are governed by the narratives in Section 3; the table below lists only the method, path, purpose, and the roles authorized to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | Admin |
| GET | `/customers/{id}` | Get a customer | Customer, Helper, Dispatcher, Admin |
| POST | `/helpers` | Create a helper profile | Admin |
| GET | `/helpers/{id}` | Get a helper | Customer, Helper, Dispatcher, Admin |
| POST | `/helpers/{id}/vet` | Vet a helper (approve/reject/suspend/reinstate) | Admin |
| POST | `/rate-cards` | Create a rate card | Admin |
| POST | `/insurance-policies` | Create an insurance policy | Admin |
| POST | `/trucks` | Create a truck | Admin |
| GET | `/trucks/{id}` | Get a truck | Customer, Helper, Dispatcher, Admin |
| POST | `/jobs` | Create a job | Customer |
| GET | `/jobs/{id}` | Get a job | Customer, Helper, Dispatcher, Admin |
| GET | `/jobs` | List/filter jobs | Customer, Helper, Dispatcher, Admin |
| POST | `/jobs/{id}/add-ons` | Add an add-on line to a draft job | Customer |
| POST | `/jobs/{id}/quote` | Generate an instant quote | Customer |
| POST | `/jobs/{id}/book` | Accept the active quote and book the job | Customer |
| POST | `/jobs/{id}/reschedule` | Reschedule a booked job's window | Customer |
| POST | `/jobs/{id}/cancel` | Cancel a quoted or booked job | Customer |
| POST | `/jobs/{id}/assign-truck` | Assign a truck to a job | Dispatcher |
| POST | `/jobs/{id}/start` | Start the job | Dispatcher |
| POST | `/jobs/{id}/complete` | Complete the job | Dispatcher |
| POST | `/jobs/{id}/settle` | Settle a completed job and release payouts | Admin |
| GET | `/add-ons/{id}` | Get an add-on | Customer, Helper, Dispatcher, Admin |
| GET | `/add-ons` | List/filter add-ons | Customer, Helper, Dispatcher, Admin |
| GET | `/quotes/{id}` | Get a quote | Customer, Helper, Dispatcher, Admin |
| GET | `/quotes` | List/filter quotes | Customer, Helper, Dispatcher, Admin |
| POST | `/assignments` | Assign an approved helper to a job | Dispatcher |
| GET | `/assignments/{id}` | Get an assignment | Customer, Helper, Dispatcher, Admin |
| GET | `/assignments` | List/filter assignments | Customer, Helper, Dispatcher, Admin |
| POST | `/assignments/{id}/check-in` | Helper checks in | Helper |
| POST | `/assignments/{id}/check-out` | Helper checks out | Helper |
| POST | `/assignments/{id}/no-show` | Mark a helper no-show | Dispatcher |
| POST | `/claims` | File a damage claim on a job | Customer |
| GET | `/claims/{id}` | Get a claim | Customer, Helper, Dispatcher, Admin |
| GET | `/claims` | List/filter claims | Customer, Helper, Dispatcher, Admin |
| POST | `/claims/{id}/review` | Move a claim to review | Admin |
| POST | `/claims/{id}/approve` | Approve a claim | Admin |
| POST | `/claims/{id}/deny` | Deny a claim | Admin |
| POST | `/ratings` | Rate and tip a helper on a completed job | Customer |
| GET | `/ratings/{id}` | Get a rating | Customer, Helper, Dispatcher, Admin |
| GET | `/ratings` | List/filter ratings | Customer, Helper, Dispatcher, Admin |
| GET | `/payouts/{id}` | Get a payout | Customer, Helper, Dispatcher, Admin |
| GET | `/payouts` | List/filter payouts | Customer, Helper, Dispatcher, Admin |
| POST | `/payouts/{id}/reverse` | Reverse a released payout | Admin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_HELPER_NOT_APPROVED` | 409 |
| `ERR_CREW_FULL` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_HELPER_UNAVAILABLE` | 409 |
| `ERR_TRUCK_UNAVAILABLE` | 409 |
| `ERR_CLAIM_EXCEEDS_COVERAGE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_QUOTE_NOT_ACTIVE` | 409 |
| `ERR_NO_CREW_CHECKED_IN` | 409 |

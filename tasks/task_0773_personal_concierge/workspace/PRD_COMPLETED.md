# Personal Concierge & Lifestyle Management API — Product Requirements Document

## 1. Introduction

The Personal Concierge & Lifestyle Management API is the operational backbone of a white-glove lifestyle service in which affluent clients delegate errands, bookings, travel arrangements, and gift sourcing to a dedicated concierge team. Clients subscribe under a monthly retainer that bundles a fixed bank of concierge hours; work beyond that allotment is billed as overage, and third-party vendor costs are passed through — sometimes at cost, sometimes with an agreed markup. The business therefore lives or dies on precise reconciliation: every logged minute must roll up into the correct billing cycle, every vendor charge must move from an estimate to a settled actual, and every client's outstanding balance must reflect the truth at all times.

This document specifies the complete contract for that system. It governs the intake and routing of service requests by category, the lifecycle of vendor engagements from proposal through settlement, the mechanics of the per-cycle hour-bank and its overage pricing, the priority weighting that gives higher-tier members faster attention, and the satisfaction signal the business uses to monitor service quality. Four operational roles collaborate over these workflows — the client, the concierge agent who performs the work, the account manager who administers relationships, and the finance operator who closes the books — and the API enforces a strict separation of what each may do. Because monetary correctness and consistent derived state are non-negotiable, all rollups are reconciled synchronously within the request that triggers them; there is no eventual consistency.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes four interactive roles — `Member`, `ConciergeAgent`, `AccountManager`, and `FinanceOps` — plus an internal `System` actor that has no HTTP surface and exists only to describe automation-driven transitions (for example, the automatic cancellation of a superseded membership). The `System` actor is never a valid value of `X-User-Role`.

The roles differ in how their identity binds to data. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's owning member to `X-User-ID`. Concretely, a `Member` may only act on a `ServiceRequest`, `Membership`, satisfaction rating, or standing-occurrence generation whose membership belongs to that same member — that is, the target membership's `member_id` must equal `X-User-ID` (reached through the request's `membership_id` when applicable). A `Member` acting on a resource owned by a different member is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `ConciergeAgent`, `AccountManager`, or `FinanceOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100. The `offset` parameter is the number of leading items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is not a valid integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, every list is returned sorted by each resource's creation timestamp (`created_at`) in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of matching resources across all pages and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent mutation. The `version` field is an integer that begins at 1 on creation and increments by 1 on every mutation of the resource; it also underpins optimistic concurrency control where applicable.

One entity is exempt from part of this convention. A `SatisfactionRating` is an immutable event: once written it is never modified. It therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Every other entity — `Member`, `RetainerPlan`, `Membership`, `BillingCycle`, `ServiceRequest`, `Vendor`, `VendorEngagement`, `TimeEntry`, and `Expense` — carries the full common set including `updated_at` and `version`.

### 2.5. Monetary Values, Minutes, and Precision

All money in the system is expressed in integer cents; there are no fractional-cent stored values. Two rounding disciplines apply, and they must not be confused. Where a rate must be reduced to whole cents — specifically the tier-adjusted effective overage rate — the value is rounded half up to the nearest whole cent. Where an overage charge is derived from minutes, the final cents figure is taken as the ceiling (rounded up to the next whole cent). Where a vendor charge is derived from cost lines under a markup, each line is rounded half up to whole cents individually and only then summed; the system never sums first and rounds once. Time is expressed in whole minutes throughout, and the hour-bank allotment is derived from whole plan hours.

### 2.6. Derived-State Reconciliation and Cascading Consistency

A defining property of this system is that derived fields are never stale. Whenever an operation changes an input that feeds a rollup, every dependent value is recomputed synchronously inside the same request before the response is returned. The dependency chain runs from a `TimeEntry` up through its `BillingCycle`, then to the owning `Membership`, and finally to the `Member`. Logging or reversing time recomputes the cycle's `consumed_minutes`, `overage_minutes`, and `overage_charge_cents`; that in turn refreshes the membership's `hour_bank_remaining_minutes` and `outstanding_balance_cents`; and that finally refreshes the member's `lifetime_billed_cents`. Confirming, reconciling, or voiding a vendor engagement likewise flows into `outstanding_balance_cents` and then `lifetime_billed_cents`.

Every entity a cascade actually mutates has its `updated_at` refreshed and its `version` incremented, exactly as a direct edit would. When a parent-state transition forces a change on children — for example, suspending a member cascading down to its memberships and their open cycles — each affected resource is mutated in place under these same rules. A member's `lifetime_billed_cents` is defined as the sum of `outstanding_balance_cents` across all of that member's memberships and is recomputed on any downstream ledger change.

### 2.7. Optimistic Concurrency Control on Membership Creation

Creating a `Membership` for a member is guarded by optimistic concurrency on the `Member`. The create request must carry `expected_member_version`, a non-optional field holding the `version` of the target `Member` that the client last observed. Because a membership create legitimately supersedes the member's prior `ACTIVE` membership and bumps the member's `version` as a side effect, a stale client view must be caught: if `expected_member_version` does not equal the target member's current `version`, the request is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), preventing the caller from acting on a member snapshot that has since advanced. This version field applies only to membership creation; no other endpoint accepts or requires it.

### 2.8. Validation Ordering and Resource Resolution

When several checks apply to one request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED` before anything else. Role authorization comes next, yielding `ERR_FORBIDDEN_ROLE`. For member-scoped operations, resource ownership is then checked, yielding `ERR_NOT_RESOURCE_OWNER`. Existence of every referenced resource is checked next: all path and body identifiers are resolved left to right, and the first that does not exist yields `ERR_NOT_FOUND` (HTTP 404). Only then is the request body validated for well-formedness — required fields present, enums drawn from their legal sets, and numeric constraints satisfied — with any violation yielding `ERR_INVALID_REQUEST` (HTTP 400). Business-specific state, referential, fiscal, and temporal rules are evaluated after these foundational checks; their individual precedence is described alongside the workflows they guard in Section 3. In particular, on membership creation the member's ACTIVE status (`ERR_MEMBER_NOT_ACTIVE`) is checked before the optimistic-concurrency version match (`ERR_STALE_MEMBER_VERSION`). More generally, any state-changing operation invoked on a resource whose current status does not define the requested transition is rejected with `ERR_INVALID_STATE` (HTTP 409); this applies uniformly to `Member`, `Membership`, `BillingCycle`, `Vendor`, `VendorEngagement`, `Expense`, and `TimeEntry` transitions as well as to `ServiceRequest` transitions.

## 3. Business Logic & Workflows

### 3.1. Members and Retainer Plans

The client relationship begins with a `Member`, created by an `AccountManager` with a `full_name` and an `email`. The `email` is the login identity and must be unique across all members; a create that reuses an existing address is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). A new member starts in `PENDING` status with `lifetime_billed_cents` initialized to zero. An `AccountManager` moves a member from `PENDING` to `ACTIVE` through activation. Activation is a prerequisite for commercial activity: no membership may be opened for a member who is not `ACTIVE`.

A member may later be suspended by an `AccountManager`, transitioning from `ACTIVE` to the terminal `SUSPENDED` status. Suspension is a heavy event: as a cascade, every one of that member's memberships currently in `ACTIVE` or `PAUSED` status is set to `CANCELLED`, and each such membership's `OPEN` billing cycle is set to `CLOSED`. The `SUSPENDED` status is terminal for a member.

Separately, an `AccountManager` defines the commercial templates. A `RetainerPlan` is created with a `name`, a `monthly_retainer_cents` recurring fee that must be greater than zero, an `included_hours` hour-bank allotment per cycle that must be greater than zero, an `overage_rate_cents_per_hour` base rate that must be greater than zero, a `max_pass_through_cents` ceiling on any single pass-through cost line that must be greater than zero, and a `default_markup_pct` default vendor markup fraction (for example, 0.15 denotes fifteen percent) that must be at least zero and defaults to 0.15 when omitted.

### 3.2. Memberships, Billing Cycles, and the Hour-Bank

An `AccountManager` opens a `Membership` for an `ACTIVE` member against a chosen plan, supplying the `plan_id`, an optional `vip_tier`, and the `expected_member_version` described in Section 2.7. The `vip_tier` is one of `STANDARD`, `SILVER`, `GOLD`, or `PLATINUM` and defaults to `STANDARD`; it drives overage discounting, request-category eligibility, and priority weight. On success the new membership is created in `ACTIVE` status with `current_cycle_index` set to 0, and the system opens its first `BillingCycle` with `cycle_index` 0 in `OPEN` status, snapshotting `included_minutes` as the plan's `included_hours` multiplied by 60. If the member already held an `ACTIVE` membership, that prior membership is superseded — the `System` actor transitions it from `ACTIVE` to `CANCELLED` and sets its `OPEN` cycle to `CLOSED` — and the member's `version` is incremented. This supersede-and-bump is precisely why the create requires a matching `expected_member_version`. The member's `version` is incremented on every successful membership create, including the case where the member held no prior `ACTIVE` membership to supersede.

An `AccountManager` may pause an `ACTIVE` membership, moving it to `PAUSED`, and later resume it back to `ACTIVE`; these two transitions form a revision loop. An `AccountManager` may also cancel a membership from either `ACTIVE` or `PAUSED`, moving it to the terminal `CANCELLED` status, provided the membership has no `ServiceRequest` in `SUBMITTED`, `IN_PROGRESS`, or `ON_HOLD`; if any such active request exists the cancellation is rejected with `ERR_CYCLE_HAS_ACTIVE_REQUESTS` (HTTP 409). A successful cancellation sets the membership's `OPEN` billing cycle to `CLOSED`. `CANCELLED` is terminal for a membership.

Each `BillingCycle` belongs to one membership via `membership_id` and tracks `consumed_minutes`, the sum of the `minutes` of the `FINALIZED` time entries booked to that cycle. The `overage_minutes` is the amount by which consumption exceeds the allotment, computed as consumed minutes minus included minutes, but never below zero. The `overage_charge_cents` is computed live for both `OPEN` and `CLOSED` cycles as described in Section 3.6. A `FinanceOps` operator closes an `OPEN` cycle, moving it to `CLOSED`; this is permitted only when the owning membership has no `ServiceRequest` in `SUBMITTED`, `IN_PROGRESS`, or `ON_HOLD`, otherwise it is rejected with `ERR_CYCLE_HAS_ACTIVE_REQUESTS`. Closing finalizes the cycle's `consumed_minutes`, `overage_minutes`, and `overage_charge_cents`, then opens a successor cycle at `cycle_index` one greater, in `OPEN` status, with `included_minutes` freshly snapshotted from the plan, and advances the membership's `current_cycle_index` to that successor. When a cycle is instead closed as a cascade of membership cancellation or member suspension, the `System` actor finalizes its `overage_charge_cents` but opens no successor cycle.

The membership's `hour_bank_remaining_minutes` reflects the current `OPEN` cycle: it is the cycle's `included_minutes` minus its `consumed_minutes`, never below zero. If the membership has no `OPEN` cycle — as after cancellation — the remaining hour-bank is zero.

### 3.3. Service Requests: Intake, Priority, and Category Eligibility

A `Member` intakes a `ServiceRequest` against one of their memberships, supplying the `membership_id`, a `category`, and a `title`, and optionally `is_standing`, `cadence`, `rush`, and `estimated_minutes`. The `category` is one of `ERRAND`, `BOOKING`, `TRAVEL`, or `GIFT`. The `is_standing` flag defaults to false and marks the request as a recurring template; `cadence` is one of `NONE`, `WEEKLY`, or `MONTHLY`, defaults to `NONE`, and is only meaningful when `is_standing` is true. The `rush` flag defaults to false and adds a priority bonus. The `estimated_minutes` concierge time estimate defaults to 0 and must be at least zero. A newly intaken request starts in `SUBMITTED` status. Intake requires the membership to be `ACTIVE`; against a non-active membership it is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409).

Intake is also gated on tier eligibility for the requested category. A `TRAVEL` request requires a `vip_tier` of `GOLD` or `PLATINUM`. A `GIFT` request requires `SILVER`, `GOLD`, or `PLATINUM`. `ERRAND` and `BOOKING` requests are open to any tier. A request whose membership tier is not eligible for its category is rejected with `ERR_CATEGORY_NOT_ELIGIBLE` (HTTP 422). Between these two state checks, the active-membership requirement is evaluated before category eligibility.

At intake the system computes the request's `priority_score` as the sum of three terms: a tier weight, a category weight, and a rush bonus. The tier weight is 1 for `STANDARD`, 2 for `SILVER`, 3 for `GOLD`, and 5 for `PLATINUM`. The category weight is 0 for `ERRAND`, 1 for `BOOKING`, 2 for `GIFT`, and 3 for `TRAVEL`. The rush bonus adds 2 when `rush` is true and 0 otherwise. The result is an integer and is recomputed on any read of the request. The request also carries `actual_minutes`, the sum of the `minutes` of its `FINALIZED` time entries, and a `recurrence_parent_id` that is null for originals (see Section 3.4).

### 3.4. The Request Lifecycle and Standing Recurrence

A `ConciergeAgent` drives a submitted request through its working life. Accepting a request advances it from `SUBMITTED` to `IN_PROGRESS` and sets its service window from the supplied `scheduled_start` and `scheduled_end`. The window must be valid — `scheduled_end` strictly after `scheduled_start` — or the accept is rejected with `ERR_INVALID_WINDOW` (HTTP 400). The window is treated as half-open, covering its start up to but excluding its end. Acceptance also checks for schedule collisions: no other request of the same membership that is currently `IN_PROGRESS` or `ON_HOLD` may have a half-open window overlapping the proposed one. Two windows that merely touch — one ending exactly when the other begins — do not overlap and are allowed; any true overlap is rejected with `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409). The accepted request must currently be in `SUBMITTED` status, or the accept is rejected with `ERR_INVALID_STATE` (HTTP 409); this status check is evaluated after datetime well-formedness but before the window-validity and schedule-conflict checks. Of these two accept-time checks, window validity is evaluated before the schedule-conflict check.

Once in progress, the agent may put the request `ON_HOLD` and later resume it back to `IN_PROGRESS`, forming a client-input revision loop, and may ultimately fulfill it, moving `IN_PROGRESS` to the terminal `FULFILLED` status. A request may be cancelled from `SUBMITTED`, `IN_PROGRESS`, or `ON_HOLD` to the terminal `CANCELLED` status; cancellation may be performed by either the owning `Member` or a `ConciergeAgent`. Any transition requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

A standing request — one created with `is_standing` true — serves as a template from which concrete occurrences are spawned. The owning `Member` generates an occurrence, which creates a new `ServiceRequest` in `SUBMITTED` status whose `recurrence_parent_id` points back to the template and which copies the template's `category`, `rush`, and `estimated_minutes`; the caller may override the `title`. The generated occurrence is itself non-standing — its `is_standing` is false and its `cadence` is `NONE`. Generation is valid only on a request whose `is_standing` is true; invoked on a non-standing request it is rejected with `ERR_NOT_STANDING` (HTTP 422). Like a direct intake, generation requires the membership to be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`) and the tier to be eligible for the copied category (`ERR_CATEGORY_NOT_ELIGIBLE`). These three business checks are evaluated in a fixed order: membership-active first, then category-eligibility, and finally the standing-template requirement (`ERR_NOT_STANDING`).

### 3.5. Time Logging and Overage Pricing

A `ConciergeAgent` logs effort against a request's hour-bank by recording `minutes` — which must be greater than zero — and an optional `note`. The system selects the `OPEN` billing cycle of the request's membership and records it on the new entry's `billing_cycle_id`; an `ACTIVE` membership always has exactly one open cycle, and time logging requires the membership to be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), which guarantees the open cycle exists. The entry is created in `FINALIZED` status. Logging then triggers the reconciliation cascade of Section 2.6: the cycle's `consumed_minutes` and overage figures are recomputed, the membership's `hour_bank_remaining_minutes` and `outstanding_balance_cents` are refreshed, and the member's `lifetime_billed_cents` follows.

A finalized entry may be reversed by a `ConciergeAgent`, moving it from `FINALIZED` to the terminal `REVERSED` status. Reversal removes the entry's minutes from consideration and reruns the same cascade: the cycle's `consumed_minutes`, `overage_minutes`, and `overage_charge_cents` are recomputed with the reversed entry excluded, the membership rollups are refreshed, and the member's `lifetime_billed_cents` is recomputed.

Overage pricing works as follows. For a given cycle, consumed minutes are the sum of `minutes` over that cycle's `FINALIZED` entries only — `REVERSED` entries are excluded entirely. The overage minutes are the consumed minutes minus the cycle's `included_minutes`, floored at zero, so that consuming exactly the included allotment yields zero overage while consuming one minute beyond it yields the first overage minute. The base `overage_rate_cents_per_hour` is adjusted for the membership tier by a multiplier — 1.00 for `STANDARD`, 0.95 for `SILVER`, 0.90 for `GOLD`, and 0.85 for `PLATINUM` — and the product is rounded half up to a whole-cent effective rate per hour. The `overage_charge_cents` is then the overage minutes multiplied by that effective per-hour rate, divided by 60, with the result taken as the ceiling to a whole cent.

### 3.6. Vendor Network, Engagements, and Client Charges

The concierge team sources work from a vendor network. An `AccountManager` registers a `Vendor` with a `name` and a `category` (one of `ERRAND`, `BOOKING`, `TRAVEL`, or `GIFT`), created in `ACTIVE` status, and may later suspend it to `SUSPENDED`. To fulfill a request through a vendor, a `ConciergeAgent` creates a `VendorEngagement` against the request, supplying the `vendor_id`, a `billing_mode`, the `estimated_cost_lines` (an array of integer cent amounts), and the vendor service window as `service_start` and `service_end` (a closed interval), plus an optional `markup_pct`. The engagement records its parent request via `service_request_id`. The vendor's `category` must equal the request's `category`, or creation is rejected with `ERR_VENDOR_CATEGORY_MISMATCH` (HTTP 422).

The `billing_mode` is either `MARKUP` or `PASS_THROUGH`. Under `PASS_THROUGH`, no markup is permitted: `markup_pct` must be zero or absent, or the request is rejected with `ERR_MARKUP_ON_PASS_THROUGH` (HTTP 422); additionally, every estimated cost line must be no greater than the plan's `max_pass_through_cents`, or the request is rejected with `ERR_PASS_THROUGH_LIMIT_EXCEEDED` (HTTP 422). Under `MARKUP`, the `markup_pct` is a fraction of at least zero, defaulting to 0. A new engagement is created in `PROPOSED` status with `client_charge_cents` of 0; it also carries `actual_cost_lines`, which are null until reconcile, and a `charge_basis` that becomes populated at confirm.

A `ConciergeAgent` confirms a proposed engagement, moving it from `PROPOSED` to `CONFIRMED`. Confirmation requires the vendor to be `ACTIVE`, or it is rejected with `ERR_VENDOR_INACTIVE` (HTTP 409). It also enforces a vendor buffer: no other engagement of the same vendor already in `CONFIRMED` or `RECONCILED` may have a closed service window within 30 minutes of this engagement's window; the two closed windows conflict unless the clear gap between them strictly exceeds 30 minutes, so a gap of exactly 30 minutes — or any overlap — is a collision, rejected with `ERR_VENDOR_WINDOW_CONFLICT` (HTTP 409). The vendor-active check is evaluated before the window-conflict check. On confirmation the engagement's `charge_basis` is set to `PROVISIONAL` and its `client_charge_cents` is computed from the `estimated_cost_lines`; the membership's `outstanding_balance_cents` is recomputed to add this charge, and the member's `lifetime_billed_cents` follows.

The client charge is computed as follows. Under `PASS_THROUGH`, the charge is simply the sum of the relevant cost lines, since those lines were already capped at creation. Under `MARKUP`, each individual line is multiplied by one plus the `markup_pct`, that per-line product is rounded half up to whole cents, and only then are the rounded lines summed to the total — the rounding is applied per line before summing, never to a single combined total. At confirm the lines used are the `estimated_cost_lines`, producing the provisional charge; at reconcile the lines used are the `actual_cost_lines`, producing the final charge.

A `FinanceOps` operator reconciles a confirmed engagement, moving it from `CONFIRMED` to the terminal `RECONCILED` status, supplying the `actual_cost_lines`, which must be present and non-empty or the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Reconciliation sets `charge_basis` to `FINAL`, recomputes `client_charge_cents` from the actual lines, and creates an `Expense` (see Section 3.7). The membership's `outstanding_balance_cents` is then recomputed to apply the delta between the final and prior provisional charge, and the member's `lifetime_billed_cents` follows.

A `ConciergeAgent` may void an engagement from either `PROPOSED` or `CONFIRMED`, moving it to the terminal `VOID` status. Voiding a merely proposed engagement has no ledger effect, since it never contributed a charge. Voiding a confirmed engagement reverses its provisional charge: the membership's `outstanding_balance_cents` is recomputed to remove it, and the member's `lifetime_billed_cents` follows.

The membership's `outstanding_balance_cents` is the sum of two components: the total of `overage_charge_cents` across all of the membership's billing cycles, both `OPEN` and `CLOSED`, plus the total of `client_charge_cents` across the membership's engagements that are in `CONFIRMED` or `RECONCILED` status. Engagements in `PROPOSED` or `VOID` status contribute nothing to this balance.

### 3.7. Expense Reconciliation and Disputes

Reconciling an engagement produces an `Expense`, a settled financial record linking the source engagement and the charged membership through `vendor_engagement_id` and `membership_id`. The expense snapshots the prior provisional charge as `estimated_cents` and the final charge as `actual_cents`, and records their difference as `variance_cents`, defined as the actual amount minus the estimated amount. A new expense is created in `RECONCILED` status.

A `FinanceOps` operator may dispute a reconciled expense, moving it from `RECONCILED` to `DISPUTED`, and later resolve it back from `DISPUTED` to `RECONCILED`; these two transitions form the expense reconciliation loop.

### 3.8. Satisfaction Ratings

After a request has been fulfilled, the owning `Member` may rate the service. A `SatisfactionRating` records the `service_request_id` of the fulfilled request being rated, carries the `membership_id` copied from that request, an integer `score` from 1 to 5 inclusive, and an optional free-text `comment`. A rating is only permitted on a request in `FULFILLED` status; rating any other request is rejected with `ERR_RATING_NOT_ALLOWED` (HTTP 409). On creation the rating is assigned a `sequence_no`, a strictly increasing per-membership counter that is the sole ordering key for recency — creation timestamps and identifiers are never used to break ties. Recording a rating recomputes the membership's `satisfaction_score`.

Satisfaction is reported in two variants. The `lifetime_average` is the mean of the `score` values across all of the membership's ratings, rounded half up to two decimal places. The `current_standing` is the mean of the scores of only the three most recent ratings, selected by `sequence_no` in descending order, likewise rounded half up to two decimal places; when a membership has three or fewer ratings, all of them are included. The membership's stored `satisfaction_score` holds the `current_standing` value. When a membership has no ratings at all — a `rating_count` of zero — both `lifetime_average` and `current_standing` are null, and the stored `satisfaction_score` is null. The computed satisfaction summary for a membership reports `lifetime_average`, `current_standing`, and `rating_count` together.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions — return a `200 OK` status code. Read operations return `200 OK`. Readers should reconstruct request bodies, side effects, and computed responses from the narratives in Section 3; the table below is intentionally limited to routing and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/concierge/members` | Create a Member (PENDING) | AccountManager |
| GET | `/concierge/members/{id}` | Get a Member | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/members/{id}/activate` | Activate a Member | AccountManager |
| POST | `/concierge/members/{id}/suspend` | Suspend a Member; cancel its memberships | AccountManager |
| POST | `/concierge/retainer-plans` | Create a RetainerPlan | AccountManager |
| GET | `/concierge/retainer-plans/{id}` | Get a RetainerPlan | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/vendors` | Create a Vendor (ACTIVE) | AccountManager |
| GET | `/concierge/vendors/{id}` | Get a Vendor | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/vendors/{id}/suspend` | Suspend a Vendor | AccountManager |
| POST | `/concierge/members/{id}/memberships` | Create a Membership (supersede prior; OCC) | AccountManager |
| GET | `/concierge/memberships/{id}` | Get a Membership | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/memberships` | List Memberships | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/memberships/{id}/satisfaction` | Satisfaction summary for a Membership | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/memberships/{id}/pause` | Pause a Membership | AccountManager |
| POST | `/concierge/memberships/{id}/resume` | Resume a Membership | AccountManager |
| POST | `/concierge/memberships/{id}/cancel` | Cancel a Membership | AccountManager |
| GET | `/concierge/billing-cycles/{id}` | Get a BillingCycle | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/billing-cycles` | List BillingCycles | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/billing-cycles/{id}/close` | Close a cycle; open its successor | FinanceOps |
| POST | `/concierge/service-requests` | Intake a ServiceRequest | Member |
| GET | `/concierge/service-requests/{id}` | Get a ServiceRequest | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/service-requests` | List ServiceRequests | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/service-requests/{id}/accept` | Accept and set service window | ConciergeAgent |
| POST | `/concierge/service-requests/{id}/hold` | Put a request on hold | ConciergeAgent |
| POST | `/concierge/service-requests/{id}/resume` | Resume a held request | ConciergeAgent |
| POST | `/concierge/service-requests/{id}/fulfill` | Fulfill a request | ConciergeAgent |
| POST | `/concierge/service-requests/{id}/cancel` | Cancel a request | ConciergeAgent, Member |
| POST | `/concierge/service-requests/{id}/generate` | Generate a standing occurrence | Member |
| POST | `/concierge/service-requests/{id}/time-entries` | Log time against the hour-bank | ConciergeAgent |
| POST | `/concierge/service-requests/{id}/ratings` | Rate a fulfilled request | Member |
| POST | `/concierge/service-requests/{id}/engagements` | Create a VendorEngagement | ConciergeAgent |
| GET | `/concierge/time-entries/{id}` | Get a TimeEntry | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/time-entries` | List TimeEntries | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/time-entries/{id}/reverse` | Reverse a finalized time entry | ConciergeAgent |
| GET | `/concierge/vendor-engagements/{id}` | Get a VendorEngagement | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/vendor-engagements` | List VendorEngagements | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/vendor-engagements/{id}/confirm` | Confirm an engagement; provisional charge | ConciergeAgent |
| POST | `/concierge/vendor-engagements/{id}/reconcile` | Reconcile with actuals; create Expense | FinanceOps |
| POST | `/concierge/vendor-engagements/{id}/void` | Void an engagement | ConciergeAgent |
| GET | `/concierge/expenses/{id}` | Get an Expense | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/expenses` | List Expenses | Member, ConciergeAgent, AccountManager, FinanceOps |
| POST | `/concierge/expenses/{id}/dispute` | Dispute a reconciled expense | FinanceOps |
| POST | `/concierge/expenses/{id}/resolve` | Resolve a disputed expense | FinanceOps |
| GET | `/concierge/satisfaction-ratings/{id}` | Get a SatisfactionRating | Member, ConciergeAgent, AccountManager, FinanceOps |
| GET | `/concierge/satisfaction-ratings` | List SatisfactionRatings | Member, ConciergeAgent, AccountManager, FinanceOps |

List endpoints accept the pagination parameters `limit` and `offset` alongside their filters. Memberships may be filtered by `member_id`, `plan_id`, and `status`. Billing cycles may be filtered by `membership_id` and `status`. Service requests may be filtered by `membership_id`, `recurrence_parent_id`, `status`, and `category`. Time entries may be filtered by `service_request_id`, `billing_cycle_id`, and `status`. Vendor engagements may be filtered by `service_request_id`, `vendor_id`, and `status`. Expenses may be filtered by `vendor_engagement_id`, `membership_id`, and `status`. Satisfaction ratings may be filtered by `service_request_id` and `membership_id`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_STALE_MEMBER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_CATEGORY_NOT_ELIGIBLE` | 422 |
| `ERR_RATING_NOT_ALLOWED` | 409 |
| `ERR_NOT_STANDING` | 422 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_MEMBER_SCHEDULE_CONFLICT` | 409 |
| `ERR_VENDOR_INACTIVE` | 409 |
| `ERR_VENDOR_CATEGORY_MISMATCH` | 422 |
| `ERR_MARKUP_ON_PASS_THROUGH` | 422 |
| `ERR_PASS_THROUGH_LIMIT_EXCEEDED` | 422 |
| `ERR_VENDOR_WINDOW_CONFLICT` | 409 |
| `ERR_CYCLE_HAS_ACTIVE_REQUESTS` | 409 |

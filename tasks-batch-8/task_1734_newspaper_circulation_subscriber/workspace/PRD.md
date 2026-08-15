# Newspaper Circulation & Subscriber Management API — Product Requirements Document

## 1. Introduction

Local newspaper circulation lives or dies on two ledgers that must never disagree: the subscriber's account (what they owe, what they've paid, what credits they've earned) and the carrier's weekly settlement (what each route delivered and what the publisher owes). This document specifies the Newspaper Circulation & Subscriber Management API — a system that runs both ledgers against the same underlying delivery reality, so a missed paper on a porch in District 4 ripples consistently into a subscriber credit, a carrier deduction, and an audit-bureau circulation count.

The API serves three operational constituencies under one roof. **Customer service** handles the subscriber-facing lifecycle: signing up accounts, managing plan step-ups, filing delivery complaints, issuing goodwill credits, recording payments, and running the save-offer choreography that rescues churning subscribers. **Distribution operations** manages the physical plant: delivery routes, carriers, route assignments over closed date intervals, retail rack locations, and the weekly rack sales reconciliation that feeds single-copy circulation. **Circulation management** closes the loop with the nightly batch cycle, financial overrides (payment reversals, charge write-offs, credit-memo voids), and the certified audit reports that the Alliance for Audited Media demands.

The system is built on a handful of cross-cutting invariants. Subscriptions carry two independent state axes — billing and delivery — that can force movement in one direction only. Every monetary figure is integer cents. Every vacation hold, route assignment, rack week, and audit period is a temporal window with its own overlap semantics. And the nightly batch cycle runs in a pinned step order so that "what happened today" is deterministic, replayable, and explainable to a subscriber on the phone. The rest of this document spells out those invariants and the workflows that honor them.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting party and `X-User-Role` naming their operational capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes four roles, spelled exactly as follows: `Subscriber`, `ServiceRep`, `DistrictManager`, `CirculationDirector`.

- When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber` record. Ownership checks compare the subscriber-chain of the target resource — the `subscriber_id` on a subscription, payment, credit memo, or billing charge, or the owning subscriber behind a subscription-scoped resource such as a vacation hold, delivery complaint, or save offer — against `X-User-ID`. A `Subscriber` caller touching any resource outside their own account chain is rejected with `ERR_NOT_OWN_RESOURCE` (HTTP 403). This applies to fetching their own subscriber record, listing their own subscriptions, holds, complaints, payments, charges, and offers, and to creating subscriptions, plan-changes, cancels, holds, complaints, and payments on their own behalf.
- When `X-User-Role` is `ServiceRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. Service representatives own subscriber care: they create subscribers, manage subscriptions, file and resolve complaints, issue goodwill credit memos, record and clear payments, and create retention save offers.
- When `X-User-Role` is `DistrictManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. District managers own distribution: routes, carriers, route assignments, rack locations, rack sales reports, and the carrier settlement read.
- When `X-User-Role` is `CirculationDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The circulation director is the hierarchical override role: every operation available to `ServiceRep` and `DistrictManager` is available to `CirculationDirector`, plus plan configuration, audit bureau reporting, payment reversal, charge write-off, credit-memo void, rack report reconciliation and dispute, the nightly batch cycle, and the test-driving clock.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Unless a list endpoint states otherwise, results are sorted by `created_at` in ascending order; the billing-charge list instead sorts by `period_start` ascending, then `created_at` ascending. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits recording when the resource was created. All entities in this system also carry an `updated_at` timestamp of the same format, refreshed on every mutation, and a `version` integer that starts at creation and increments by one on every modification — including system-driven mutations such as cascade side effects, status re-evaluations, and staged plan changes. No entity in this domain omits `updated_at` or `version`.

### 2.5. The Logical Clock and the Nightly Batch

All date rules in the system — "today", past-due aging, offer expiry, hold windows, complaint windows — are evaluated against a test-driving logical clock, never the wall clock. At startup, before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z, and "today" is the UTC date of that clock. A `CirculationDirector` may advance the clock to a supplied `to_iso8601` instant; doing so does **not** itself run any batch work.

The nightly batch is an explicit, director-invoked operation that runs seven steps in a pinned order against the current logical date: (1) activate `PENDING_START` subscriptions whose `start_date` has been reached, generating their first weekly charge immediately in a catch-up loop; (2) activate `SCHEDULED` vacation holds whose start has arrived; (3) complete `ACTIVE` holds whose end has arrived, issuing proration credits where the resolution calls for them; (4) run the weekly charge catch-up for subscriptions in `ACTIVE`, `GRACE`, or `CANCEL_PENDING`; (5) expire `OFFERED` save offers past their `expires_at`, churning `CANCEL_PENDING` subscriptions to `CANCELLED`; (6) re-evaluate the lapse cycle across all non-terminal subscriptions; (7) apply pending plan changes whose `effective_date` has arrived. The batch returns a summary object with counts: `activated_subscriptions`, `holds_activated`, `holds_completed`, `charges_generated`, `offers_expired`, `status_changes`, and `plan_changes_applied`.

### 2.6. The Subscriber Ledger

Every subscriber carries a ledger built from their billing charges. A charge's outstanding amount is its `amount_cents` minus `paid_amount_cents` minus `credit_applied_cents`. The subscriber's `balance_due_cents` is the sum of outstanding amounts over all charges in `OPEN`, `PARTIALLY_PAID`, or `PAID` status, minus the subscriber's `unapplied_cash_cents` (overpayment remainder not yet allocated to any charge). Charges in `WRITTEN_OFF` status are excluded from the balance entirely. Both `balance_due_cents` and `unapplied_cash_cents` are computed fields, recomputed immediately whenever a payment clears, a credit applies, a charge generates, or a reversal cascades through the ledger.

All monetary values throughout the system are integer cents. Where a calculation requires rounding, the system rounds half up to the nearest integer cent; the specific rounding points are stated with each calculation.

### 2.7. Dual State Axes on a Subscription

A subscription carries two independent state axes that evolve in parallel. The **billing axis** (`billing_status`) moves through `PENDING_START`, `ACTIVE`, `GRACE`, `SUSPENDED`, `CANCEL_PENDING`, and the terminal states `CANCELLED` and `LAPSED`. The **delivery axis** (`delivery_status`) moves through `NOT_DELIVERED`, `DELIVERING`, and `HELD`. The axes are independent except in one direction: billing transitions can force delivery transitions (suspension stops delivery; reinstatement resumes it for print-capable plans; cancellation and lapse end it), but a delivery-side change never moves the billing axis. `CANCELLED` and `LAPSED` are terminal — once reached, they are never re-entered.

### 2.8. Temporal Windows: Half-Open Holds, Closed Assignments, Monday Weeks

Different temporal windows in the system use different interval semantics, and the distinction is load-bearing:

- **Vacation holds** use a half-open interval: `start_date` is the first non-delivery day, `end_date` is the resume date and is **exclusive** — the hold's length in days is `end_date` minus `start_date`. Two holds on the same subscription overlap if their half-open intervals intersect; adjacency, where the new hold's start equals an existing hold's end, is allowed.
- **Route assignments** use a closed interval: both `start_date` and `end_date` are inclusive delivery days, and a null `end_date` means open-ended. Two active assignments for the same subscription collide if their closed intervals intersect — and unlike holds, touching ends (the new assignment's `start_date` equal to an existing assignment's `end_date`) **do** collide.
- **Rack sales weeks** are anchored to Mondays: a report's `week_start_date` must be a Monday, and only one report may exist per rack location per week.
- **Audit periods** are inclusive at both ends: `period_start` through `period_end`, and a new audit report's period may not overlap any existing audit report in `DRAFT`, `CERTIFIED`, or `SUBMITTED` status.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Staging a plan change on a subscription requires the request to carry `expected_subscription_version` equal to the subscription's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Manually creating a save offer on a subscription likewise requires `expected_subscription_version` matching the subscription's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) on mismatch. Both operations legitimately supersede prior state — a new plan change replaces any pending plan change, and a new manual offer auto-expires any existing `OFFERED` offer — so a client whose view of the subscription predates the latest superseding mutation is dropped rather than allowed to overwrite a change it never observed. Endpoints not named here do not take a version field.

### 2.10. Validation Ordering

When multiple checks could reject the same request, the system evaluates them in a fixed priority order so the surfaced error is deterministic. Authentication context first (missing or malformed headers, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_FORBIDDEN_FOR_ROLE`), then subscriber ownership scoping (`ERR_NOT_OWN_RESOURCE`). Only then does the system look at the resource graph: path identifiers must exist, validated left-to-right so the first missing id yields `ERR_NOT_FOUND`; then request-body shape — required fields present, types valid, enum membership, positive amounts, date ordering, Monday-anchored week starts, returned-copies not exceeding delivered-copies — with violations rejected as `ERR_INVALID_REQUEST`. State preconditions come next (the specific state-axis errors such as `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_COMPLAINT_NOT_OPEN`, `ERR_OFFER_NOT_OPEN`, and their siblings), then the OCC stale-version check (`ERR_STALE_VERSION`). Temporal interval rules follow (hold windows and overlaps, assignment overlaps, rack week conflicts, audit period overlaps, complaint filing windows), then cross-entity referential fit (service-address requirements and print-capability requirements), then capacity and uniqueness constraints (route capacity, duplicate complaints, route code uniqueness). Money and quota checks are always evaluated last: the monthly goodwill cap, the per-complaint credit cap, the annual hold budget, the settled-ledger requirement for subscriber close, and the unreconciled-rack-report block on audit certification.

### 2.11. Nested Resource Retrieval

Where an endpoint path nests one resource beneath another — a vacation hold or save offer created beneath a subscription — the system validates path identifiers left to right. A request naming a non-existent parent is rejected with `ERR_NOT_FOUND` before the child operation is even considered, and a non-existent child id under an existing parent yields the same error code for the child segment.

## 3. Business Logic & Workflows

### 3.1. Plans, Subscribers, and Getting a Subscription Started

A **subscription plan** is the commercial product. A `CirculationDirector` creates one with a display `name`, a `plan_type` of `PRINT`, `DIGITAL`, or `BUNDLE`, a count of `issues_per_week` (zero for `DIGITAL` plans, between one and seven otherwise), a `base_weekly_rate_cents` that must be positive, and a `min_weekly_rate_cents` floor used later by retention offers. Plans may also carry a `step_up_schedule` — a list of rate steps, each pairing an `after_weeks` tenure threshold with a `weekly_rate_cents` price, sorted by `after_weeks` ascending — and a `proration_method` of `PER_DAY` or `PER_ISSUE` selecting the vacation-hold credit variant (defaulting to `PER_DAY` when omitted). A plan begins `ACTIVE`. Retiring a plan flips it to `RETIRED`; existing subscriptions on the plan are unaffected, but new subscriptions and plan-changes targeting a retired plan are rejected with `ERR_PLAN_RETIRED`.

A **subscriber** is the account holder, created by a `ServiceRep` or `CirculationDirector` with a `display_name`, an `email`, and an optional `service_address`. The address matters: it must be present before any print-capable subscription can be created for the account, before a plan-change can target a print-capable plan, and before any vacation hold, delivery complaint, or route assignment can be attached — its absence surfaces as `ERR_SERVICE_ADDRESS_REQUIRED` at those moments. A new subscriber starts `ACTIVE` with a zero `balance_due_cents` and zero `unapplied_cash_cents`.

Creating a **subscription** takes a payload with the owning `subscriber_id`, the target `plan_id`, and a `start_date` — which may lie in the past, in which case catch-up weekly charges generate the moment the subscription activates. The new subscription begins with `billing_status` of `PENDING_START` and `delivery_status` of `NOT_DELIVERED`. When the daily cycle finds a `PENDING_START` subscription whose `start_date` has arrived, it flips billing to `ACTIVE`, sets `next_charge_date` to the start date, immediately generates the first weekly charge, and — if the plan is print-capable (`PRINT` or `BUNDLE`) — flips delivery from `NOT_DELIVERED` to `DELIVERING`. A subscriber whose account had drifted to `LAPSED` is bubbled back up to `ACTIVE` the moment any new subscription is created for them.

The weekly charge itself is priced by the **effective weekly rate**. Tenure in whole weeks is measured from the subscription's `start_date` to the charge's `period_start` — that is, the difference in days divided by seven, rounded down. The rate starts at the plan's `base_weekly_rate_cents`, then walks the `step_up_schedule` in ascending `after_weeks` order: any step whose `after_weeks` threshold has been reached by the current tenure — including exactly reached, since the boundary is inclusive — replaces the running rate with that step's `weekly_rate_cents`. If the subscription carries an accepted save discount and the charge's `period_start` falls strictly before `save_discount_until`, the stepped rate is multiplied by one minus `save_discount_pct`, rounded half up to the nearest cent, and the result is floored at the plan's `min_weekly_rate_cents`. Each generated charge records a weekly `period_start`, a `period_end` seven days later, a `due_date` fourteen days after the period start, and an `amount_cents` equal to the effective weekly rate at generation time. Charges begin `OPEN` with zero `paid_amount_cents` and zero `credit_applied_cents`.

### 3.2. The Lapse Cycle: Grace, Suspension, and Write-Off

Billing health is re-evaluated after every payment clear, credit application, and reversal, and again in step six of every nightly batch. The measure is the age of the oldest unpaid past-due charge: among the subscriber's charges in `OPEN` or `PARTIALLY_PAID` status, the system finds the greatest number of days by which `today` has passed the charge's `due_date`, treating the value as zero when nothing is past due. That single number drives the billing axis with strictly-greater thresholds — so a charge exactly seven days past due leaves the subscription in good standing:

- At most seven days past due: the subscription is or returns to `ACTIVE`.
- More than seven but at most twenty-one days: the subscription sits in `GRACE`.
- More than twenty-one but at most forty-five days: the subscription drops to `SUSPENDED`. Delivery stops — `DELIVERING` or `HELD` flips to `NOT_DELIVERED` — and charge generation pauses while the subscription remains suspended.
- More than forty-five days: the subscription lapses to the terminal `LAPSED`. Every `OPEN` or `PARTIALLY_PAID` charge on the subscription is written off, delivery is forced to `NOT_DELIVERED`, `ended_at` is stamped with the current date, and the owning subscriber's bubble-up is re-evaluated.

Reinstatement runs the same thresholds in reverse after a payment clears: a suspended subscription whose oldest unpaid charge is brought back to at most seven days past due lands in `ACTIVE`, with its `next_charge_date` reset to the reinstatement date and delivery resuming to `DELIVERING` when the plan is print-capable. A grace subscription that gets current returns to `ACTIVE` the same way. Note that `LAPSED` and `CANCELLED` never re-enter: a lapsed subscriber who wants service again starts a new subscription.

A subscriber may change plans mid-life by staging a plan change. The request names a `new_plan_id` and a future `effective_date` — an `effective_date` that has already arrived or passed is rejected with `ERR_INVALID_REQUEST` — and must carry `expected_subscription_version` per §2.9. Staging writes `pending_plan_id` and `pending_plan_effective_date` onto the subscription, superseding (silently replacing) any previously staged change, and increments the subscription's `version`. When the daily cycle's seventh step finds a pending change whose `effective_date` has arrived, it switches the subscription's `plan_id` to the pending target and clears both pending fields. A staged change targeting a print-capable plan requires the subscriber's `service_address` (`ERR_SERVICE_ADDRESS_REQUIRED`), and a target plan that has been retired is rejected with `ERR_PLAN_RETIRED`.

The subscriber-level **bubble-up** ties the axes to the account: when every subscription on a subscriber has reached a terminal billing state (`CANCELLED` or `LAPSED`) and at least one subscription exists, the subscriber's `status` flips from `ACTIVE` to `LAPSED`. Closing the account entirely is a deliberate act: a `ServiceRep` or `CirculationDirector` may close a `LAPSED` subscriber only when the ledger is fully settled — `balance_due_cents` of zero and `unapplied_cash_cents` of zero — otherwise the close is rejected with `ERR_SUBSCRIBER_NOT_SETTLED`. A successful close moves the subscriber to the terminal `CLOSED` status.

### 3.3. Vacation Holds and Proration Credits

A subscriber going away schedules a **vacation hold** against one of their subscriptions — self-service for `Subscriber` callers on their own subscriptions, or via a `ServiceRep` or `CirculationDirector`. The creation payload carries `start_date`, `end_date`, and a `resolution` of `CREDIT` or `REDELIVER`. The window must be valid: the start cannot be in the past relative to today (violations surface as `ERR_HOLD_WINDOW_INVALID`), and the length — `end_date` minus `start_date` under the half-open convention — must fall between one and twenty-one days inclusive. The new hold's half-open interval must not intersect any existing `SCHEDULED` or `ACTIVE` hold on the same subscription (`ERR_HOLD_OVERLAP`), remembering that a new hold starting exactly when an existing one resumes is adjacency, not overlap. Holds are only meaningful for print-capable plans; attempting one against a `DIGITAL` plan is rejected with `ERR_DIGITAL_ONLY_PLAN`. There is also an annual budget: the total hold days across a subscription's `SCHEDULED`, `ACTIVE`, and `COMPLETED` holds within the calendar year, plus the new hold's length, may not exceed thirty days — excess is rejected with `ERR_HOLD_LIMIT_EXCEEDED`. Finally, holds require the subscription's billing axis to be in an active set: `ACTIVE` or `GRACE`, otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`.

A scheduled hold sits in `SCHEDULED` until the batch cycle reaches its start date, when it flips to `ACTIVE`, captures `weekly_rate_snapshot_cents` from the effective weekly rate in force that day, and flips the subscription's delivery from `DELIVERING` to `HELD`. Completion arrives when the batch cycle reaches `end_date`, or earlier if an authorized caller resumes the hold — early resume sets the effective end to today. Either way the hold lands in `COMPLETED`, delivery flips back from `HELD` to `DELIVERING`, and the resolution determines the financial aftermath.

For a `CREDIT` resolution, the system issues a proration credit memo and records the amount on the hold's `credit_amount_cents`. The base is the snapshot rate, and the held-day count is the actual held span — from `start_date` up to but not including the actual end date. Under the `PER_DAY` variant, the credit is the snapshot rate multiplied by the held days, divided by seven, rounded half up to whole cents — a single rounding after the multiply. Under the `PER_ISSUE` variant, the rounding order is pinned differently: the per-issue rate is computed first as the snapshot rate divided by the plan's `issues_per_week`, rounded half up to whole cents, and only then multiplied by the held days. For a sense of the difference this ordering makes, a snapshot of 1000 cents over four held days yields 571 cents under `PER_DAY`, while a seven-issue-per-week plan under `PER_ISSUE` rounds the per-issue rate to 143 cents and yields 572. The resulting credit memo carries `source` of `PRORATION` with its `hold_id` pointing back to the hold, and it auto-applies through the payment waterfall at issuance. Under a `REDELIVER` resolution, no credit is issued; the missed copies are queued for the redelivery pack instead.

A `SCHEDULED` hold can still be cancelled outright — by the subscriber or a staff role — which flips it to `CANCELLED` with no credit, no delivery change, and zero drift on the subscriber ledger. Cancelling a hold that has already left `SCHEDULED` is rejected with `ERR_HOLD_NOT_CANCELLABLE`; resuming a hold that is not currently `ACTIVE` is rejected with `ERR_HOLD_NOT_ACTIVE`.

### 3.4. Complaints, Credits, and the Goodwill Cap

When a paper goes missing, arrives damaged, or shows up late, a **delivery complaint** is filed with the `subscription_id`, the `service_date` of the failed delivery, and a `complaint_type` of `MISSED`, `DAMAGED`, `LATE`, or `OTHER`. The filing window is tight: the service date must fall within today and the seven days prior — anything older is rejected with `ERR_COMPLAINT_WINDOW_CLOSED`. Complaints belong to print-capable plans only (`ERR_DIGITAL_ONLY_PLAN` otherwise), and the subscription must be in an active billing state. At filing, the system resolves `route_id` from the route assignment covering the service date — null if none exists — and the complaint begins `OPEN`. Only one non-`DENIED` complaint may exist per subscription per service date; a second filing collides with `ERR_DUPLICATE_COMPLAINT`.

A `ServiceRep` or `CirculationDirector` resolves an `OPEN` complaint in one of two directions. **Denying** records a `deny_reason` and flips the complaint to `DENIED` with no credit issued. **Crediting** flips the complaint to `CREDITED`, stamps its `credit_amount_cents`, and creates a credit memo with `source` of `COMPLAINT` and `complaint_id` set, which immediately auto-applies through the waterfall. The credit amount may be supplied explicitly in the request as `amount_cents`; when omitted, the default is the subscription's current effective weekly rate divided by the plan's `issues_per_week`, rounded half up. Two caps guard credit issuance. First, a per-complaint ceiling: the amount may not exceed 2000 cents, else `ERR_CREDIT_EXCEEDS_COMPLAINT_CAP`. Second, the monthly goodwill cap described below. Either resolution path requires the complaint to still be `OPEN` — acting on a resolved complaint surfaces `ERR_COMPLAINT_NOT_OPEN`.

The credit cascade is deliberately deep: the applied charge's `credit_applied_cents` rises (possibly flipping the charge to `PAID`), the subscriber's `balance_due_cents` is recomputed, and the subscription's billing axis is re-evaluated — a complaint credit can pull a subscription from `GRACE` back to `ACTIVE`.

Independent of complaints, staff can issue a manual **goodwill credit memo** for a subscriber with an `amount_cents` and a free-text `reason`; its `source` is `GOODWILL` and it too auto-applies at issuance. Both goodwill and complaint credits draw from the same monthly pool: the sum of `amount_cents` over the subscriber's credit memos with `source` of `GOODWILL` or `COMPLAINT`, excluding `VOIDED` memos, created within the current calendar month, plus the new amount, may not exceed 5000 cents — breach is rejected with `ERR_GOODWILL_CAP_EXCEEDED`.

Every credit memo tracks `applied_cents`, the portion the waterfall consumed at issuance. A memo whose full amount applied flips from `ISSUED` to `APPLIED`; a memo with leftover funds stays `ISSUED`. A `CirculationDirector` may void a memo, but only while nothing has been applied — voiding a memo with any `applied_cents` above zero is rejected with `ERR_CREDIT_MEMO_LOCKED`.

### 3.5. Cancellation and the Save-Offer Choreography

A cancellation request — from the subscriber themselves or a staff role, with a recorded `reason` — behaves differently depending on where the billing axis sits. From `ACTIVE` or `GRACE`, the subscription moves to `CANCEL_PENDING` rather than dying outright: the system auto-creates a save offer in `OFFERED` status with `origin` of `CANCEL_FLOW`, a `discount_pct` of 0.25, a `duration_weeks` of 8, and an `expires_at` seven days out, records the `cancel_reason` on the subscription, and increments the subscription's `version`. A cancellation attempted from any other billing state except `SUSPENDED` is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`. From `SUSPENDED`, no save offer is created at all — the subscription churns directly to `CANCELLED`, delivery is forced to `NOT_DELIVERED`, `ended_at` is stamped, and the subscriber bubble-up re-evaluates.

While an offer sits `OFFERED`, three outcomes compete. **Acceptance** — by the subscriber or staff — requires the offer still be `OFFERED` and today strictly before `expires_at` (`ERR_OFFER_NOT_OPEN` otherwise), and the subscription's billing state must be `CANCEL_PENDING`, `ACTIVE`, or `GRACE` (`ERR_SUBSCRIPTION_NOT_ACTIVE` otherwise). Accepting flips the offer to `ACCEPTED`, writes `save_discount_pct` onto the subscription, sets `save_discount_until` to today plus the offer's duration in weeks times seven days (the discount applies to charges whose period starts strictly before that date), clears the `cancel_reason`, rescues a `CANCEL_PENDING` subscription back to `ACTIVE`, and increments the subscription's `version`. **Declining** flips the offer to `DECLINED`; if the subscription was sitting in `CANCEL_PENDING`, it churns to `CANCELLED` with delivery stopped and `ended_at` stamped. **Expiry** arrives via the batch cycle when `expires_at` is reached: the offer flips to `EXPIRED`, and a `CANCEL_PENDING` subscription churns to `CANCELLED` — the churn is confirmed.

A `ServiceRep` or `CirculationDirector` may also create a save offer manually — origin `RETENTION_REP` — outside any cancel flow, supplying a `discount_pct` between 0.10 and 0.50 inclusive and a `duration_weeks` between 4 and 26 inclusive. Every offer, whatever its origin, carries an `offer_type` of `DISCOUNT_RATE` — the only offer type this version of the system supports. Manual creation **supersedes**: any existing `OFFERED` offer on the same subscription is auto-flipped to `EXPIRED` (the supersede flavor of expiry, which leaves the subscription's billing state untouched, unlike cycle expiry). The new offer begins `OFFERED` with `expires_at` seven days out, and the subscription's `version` increments. Because supersede is a destructive act against any concurrent writer's view, manual offer creation is OCC-guarded per §2.9: the request must carry `expected_subscription_version` matching the subscription's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 3.6. Routes, Carriers, and Assignments

Distribution's physical plant starts with the **delivery route**. A `DistrictManager` or `CirculationDirector` creates one with a `route_code` — unique among routes that are not `INACTIVE` — an optional `carrier_id`, and a `max_stops` capacity that must be positive. Routes begin `ACTIVE`; deactivating via a route update carrying `status` of `INACTIVE` blocks new assignments into the route (`ERR_ROUTE_INACTIVE`) while leaving existing assignments untouched. The same update operation can also re-point `carrier_id` or adjust `max_stops`. A route's `assigned_stop_count` is computed: the number of `ACTIVE` route assignments currently hanging off it.

**Carriers** are created with a `display_name`, a `compensation_model` of `PER_COPY_GROSS` or `PER_COPY_NET_OF_COMPLAINTS`, and a positive `per_copy_rate_cents`. Carriers have no lifecycle transitions in this version — they are always `ACTIVE` — because their weekly settlement is a computed read, not a state machine.

A **route assignment** ties a subscription to a route over a closed interval: the payload names the `subscription_id`, the `route_id`, a `start_date`, and an optional `end_date` (null meaning open-ended). Assignments require the subscription's billing axis in an active set and a print-capable plan (`ERR_DIGITAL_ONLY_PLAN` otherwise). Three guards protect the route: it must be `ACTIVE` (`ERR_ROUTE_INACTIVE`), it must have spare capacity — `assigned_stop_count` already at `max_stops` yields `ERR_ROUTE_AT_CAPACITY` — and the new closed interval must not collide with another `ACTIVE` assignment of the same subscription. Closed-interval collision is strict about touching ends: a new assignment whose `start_date` equals an existing assignment's `end_date` does collide, surfacing `ERR_ASSIGNMENT_OVERLAP`. A successful assignment begins `ACTIVE` and increments the route's `assigned_stop_count`. Ending an assignment requires it to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and takes an `end_date` no earlier than its `start_date` (otherwise `ERR_INVALID_REQUEST`); the assignment flips to `ENDED`, the end date is recorded, and the route's `assigned_stop_count` decrements.

### 3.7. Carrier Settlement

Once a week, distribution settles with each carrier through a computed read parameterized by `week_start_date`, covering the Monday-anchored half-open week from that date through the following seven days. The settlement walks the carrier's `ACTIVE` routes and, for every route assignment — regardless of assignment status — whose closed interval intersects the week, whose subscription's plan is print-capable, and whose subscription's billing state is `ACTIVE`, `GRACE`, or `CANCEL_PENDING`, it counts one delivered copy per delivery day: the overlap days between the assignment interval and the week, minus any held days falling inside that overlap. Complaints attribute to the carrier through their `route_id`: any complaint whose route belongs to the carrier and whose `service_date` falls in the week increments `complaint_count`, regardless of complaint status.

The money follows. `gross_cents` is the delivered copy count times the carrier's `per_copy_rate_cents`. A service bonus applies when complaints are few: at most two complaints earns a `bonus_cents` of five percent of gross, rounded half up; three or more complaints earns nothing. The deduction side depends on the compensation variant. Under `PER_COPY_GROSS`, the deduction is forced to zero — complaints cost the carrier their bonus but nothing more. Under `PER_COPY_NET_OF_COMPLAINTS`, the deduction is 150 cents per complaint, capped at 3000 cents total. The final `net_cents` is gross plus bonus minus deduction, floored at zero. To feel the variant difference: seven delivered copies at fifty cents each with one complaint yields 350 gross plus an 18-cent bonus, settling at 368 cents under `PER_COPY_GROSS` but 218 cents under `PER_COPY_NET_OF_COMPLAINTS` after the 150-cent deduction. The settlement response exposes `week_start_date`, `compensation_model`, `delivered_copies`, `complaint_count`, `gross_cents`, `bonus_cents`, `deduction_cents`, and `net_cents`.

### 3.8. Payments, the Waterfall, and Reversal

A **payment** is recorded against a subscriber with an `amount_cents` that must be positive and a `method` of `CARD`, `CHECK`, `CASH`, or `ACH`, beginning in `INITIATED`. Nothing moves on the ledger until the payment clears.

Clearing runs the **payment waterfall**, the same allocation discipline used when credit memos issue. The eligible set is the subscriber's charges in `OPEN` or `PARTIALLY_PAID` status with positive outstanding. Allocation walks them oldest-due-first — `due_date` ascending, ties broken by `created_at` ascending, never by id — taking from each charge the lesser of the remaining funds and that charge's outstanding, crediting `paid_amount_cents` (for a payment) or `credit_applied_cents` (for a credit memo), and flipping the charge to `PAID` when fully covered or `PARTIALLY_PAID` when partially. A payment's leftover remainder lands in the subscriber's `unapplied_cash_cents`; a credit memo's leftover stays on the memo, which remains `ISSUED`. The payment records the result in its `allocations` list — each entry pairing a `charge_id` with the `amount_cents` applied, in allocation order. Then the cascade: `balance_due_cents` recomputed, and the subscription billing axis re-evaluated, which can move `GRACE` to `ACTIVE` or lift `SUSPENDED` back to `ACTIVE` or `GRACE` per the reinstatement thresholds. Clearing or failing a payment that is not `INITIATED` is rejected with `ERR_PAYMENT_NOT_INITIATED`; failing simply stamps `FAILED` with no ledger effects.

Reversal is the deepest compensation in the system, reserved for `CirculationDirector`, and only available on a `CLEARED` payment (otherwise `ERR_PAYMENT_NOT_CLEARED`). It unwinds in three depths. First, each allocation is undone in reverse allocation order: the charge's `paid_amount_cents` is restored downward, and charge statuses revert — a `PAID` charge whose covered amount returns to zero flips all the way back to `OPEN`, while partial restoration lands at `PARTIALLY_PAID` or `OPEN` accordingly. Second, the charge restorations force the subscriber's `balance_due_cents` to recompute upward and claw back the reversed remainder from `unapplied_cash_cents`. Third, the worsened balance triggers subscription billing re-evaluation, which can flip `ACTIVE` to `GRACE` or `GRACE` to `SUSPENDED` under the same lapse thresholds. The payment ends in `REVERSED`.

Charges themselves can be forgiven directly: a `CirculationDirector` may write off a charge in `OPEN` or `PARTIALLY_PAID` status (anything else draws `ERR_CHARGE_NOT_OPEN`), flipping it to `WRITTEN_OFF` and excluding it from the `balance_due_cents` aggregation forever after.

### 3.9. Rack Sales and Single-Copy Reconciliation

Newsstand revenue runs through **rack locations**, created by distribution with a `location_name`, a street `address`, and a positive `price_per_copy_cents` — the single-copy price the location remits per sold copy. Racks begin `ACTIVE` and can be deactivated to `INACTIVE`, which blocks new sales reports for the rack with `ERR_INVALID_STATE` while leaving history intact.

Weekly, distribution files a **rack sales report** for a location with its `rack_location_id`, a Monday-anchored `week_start_date` (non-Mondays are `ERR_INVALID_REQUEST`), the `copies_delivered` drop count, the `copies_returned` pickup count (which may not exceed delivered), and optionally the location-reported `reported_sold_copies`. One report per rack per week: a second report for the same rack and week collides with `ERR_REPORT_WEEK_CONFLICT`. The report begins `DRAFT`, and while `DRAFT` both `copies_delivered` and `copies_returned` remain correctable.

Submission — from `DRAFT`, or resubmission from `DISPUTED` after correction — runs the reconciliation computation and freezes `copies_delivered`. `copies_sold` is delivered minus returned; `amount_due_cents` is copies sold times the rack's `price_per_copy_cents`; `variance_copies` is the reported count minus the computed sold count, or zero when no reported count was supplied; and `variance_flag` turns true only when the absolute variance strictly exceeds two copies — a variance of exactly two is within tolerance and does not flag. Resubmission from `DISPUTED` recomputes from the corrected `copies_returned` with `copies_delivered` untouched. Correction rights are asymmetric once submitted: a `DISPUTED` report accepts edits to `copies_returned` only, and attempting to edit `copies_delivered` there is `ERR_INVALID_REQUEST`; editing anything on a report outside `DRAFT` or `DISPUTED` is `ERR_REPORT_NOT_EDITABLE`. Submitting from any status other than `DRAFT` or `DISPUTED` is `ERR_REPORT_NOT_SUBMITTABLE`.

From `SUBMITTED`, only the `CirculationDirector` can move the report — an audit-trail control separating the reconciler from the submitter flow. Reconciling flips the report to its terminal `RECONCILED` state (requiring `SUBMITTED`, else `ERR_REPORT_NOT_RECONCILABLE`); disputing kicks it back to `DISPUTED` for correction with an optional `reason` (requiring `SUBMITTED`, else `ERR_INVALID_STATE`).

### 3.10. Audit Bureau Reporting

The audit bureau's circulation statement is the system's ultimate act of accountability, and only a `CirculationDirector` touches it. Creating an **audit report** takes an inclusive `period_start` and `period_end` (with `period_end` after `period_start`) and immediately snapshots three totals. `paid_print_subscribers` counts subscriptions on `PRINT` or `BUNDLE` plans whose billing state is `ACTIVE`, `GRACE`, or `CANCEL_PENDING` — `SUSPENDED`, `LAPSED`, and `CANCELLED` are not paid circulation — and whose service span overlaps the period: `start_date` no later than `period_end`, and either no `ended_at` or an `ended_at` no earlier than `period_start`. `paid_digital_subscribers` applies the same filter with `DIGITAL` or `BUNDLE` plans. `single_copy_copies` sums `copies_sold` over rack sales reports in `RECONCILED` status whose `week_start_date` falls inside the period — `DRAFT`, `SUBMITTED`, and `DISPUTED` reports are excluded. A new period may not overlap any existing audit report in `DRAFT`, `CERTIFIED`, or `SUBMITTED` status (`ERR_AUDIT_PERIOD_OVERLAP`). The report begins `DRAFT`.

Certification is the gate. Certifying requires the report still be `DRAFT` (`ERR_AUDIT_NOT_DRAFT`) and requires that every rack sales report with a `week_start_date` inside the period has reached `RECONCILED` — a single straggler blocks certification with `ERR_UNRECONCILED_RACK_VARIANCE`. On certification, all three totals are **recomputed** against current data — the stale `DRAFT` snapshot is discarded — and `certified_at` is stamped. Submitting then requires `CERTIFIED` (`ERR_AUDIT_NOT_CERTIFIED`) and lands the report in its terminal `SUBMITTED` state, off to the bureau.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, transition its state, or read data return `200 OK`. All endpoints are mounted under `/api` except the test-driving clock, which is mounted at the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/subscription-plans` | Create a subscription plan | CirculationDirector |
| GET | `/api/subscription-plans` | List plans | Subscriber, ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/subscription-plans/{id}` | Get a plan | Subscriber, ServiceRep, DistrictManager, CirculationDirector |
| POST | `/api/subscription-plans/{id}/retire` | Retire a plan | CirculationDirector |
| POST | `/api/subscribers` | Create a subscriber account | ServiceRep, CirculationDirector |
| GET | `/api/subscribers` | List subscribers | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/subscribers/{id}` | Get a subscriber (Subscriber role: own record only) | Subscriber, ServiceRep, DistrictManager, CirculationDirector |
| POST | `/api/subscribers/{id}/close` | Close a LAPSED subscriber with a settled ledger | ServiceRep, CirculationDirector |
| POST | `/api/subscriptions` | Create a subscription | Subscriber, ServiceRep, CirculationDirector |
| GET | `/api/subscriptions` | List subscriptions | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/subscriptions/{id}` | Get a subscription (Subscriber role: own only) | Subscriber, ServiceRep, DistrictManager, CirculationDirector |
| POST | `/api/subscriptions/{id}/plan-change` | Stage a plan change (OCC-guarded) | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/subscriptions/{id}/cancel` | Request cancellation (save offer or direct churn) | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/subscriptions/{id}/vacation-holds` | Schedule a vacation hold | Subscriber, ServiceRep, CirculationDirector |
| GET | `/api/vacation-holds` | List vacation holds | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/vacation-holds/{id}` | Get a vacation hold (Subscriber role: own subscription only) | Subscriber, ServiceRep, DistrictManager, CirculationDirector |
| POST | `/api/vacation-holds/{id}/cancel` | Cancel a SCHEDULED hold | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/vacation-holds/{id}/resume` | Early-resume an ACTIVE hold | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/complaints` | File a delivery complaint | Subscriber, ServiceRep, CirculationDirector |
| GET | `/api/complaints` | List complaints | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/complaints/{id}` | Get a complaint (Subscriber role: own subscription only) | Subscriber, ServiceRep, DistrictManager, CirculationDirector |
| POST | `/api/complaints/{id}/credit` | Credit an OPEN complaint | ServiceRep, CirculationDirector |
| POST | `/api/complaints/{id}/deny` | Deny an OPEN complaint | ServiceRep, CirculationDirector |
| POST | `/api/credit-memos` | Issue a manual GOODWILL credit | ServiceRep, CirculationDirector |
| GET | `/api/credit-memos` | List credit memos | ServiceRep, CirculationDirector |
| GET | `/api/credit-memos/{id}` | Get a credit memo | ServiceRep, CirculationDirector |
| POST | `/api/credit-memos/{id}/void` | Void an unapplied credit memo | CirculationDirector |
| POST | `/api/subscriptions/{id}/save-offers` | Manually create a retention save offer (OCC-guarded) | ServiceRep, CirculationDirector |
| GET | `/api/save-offers` | List save offers | ServiceRep, CirculationDirector |
| GET | `/api/save-offers/{id}` | Get a save offer (Subscriber role: own subscription only) | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/save-offers/{id}/accept` | Accept an OFFERED, unexpired offer | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/save-offers/{id}/decline` | Decline an OFFERED offer | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/routes` | Create a delivery route | DistrictManager, CirculationDirector |
| GET | `/api/routes` | List routes | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/routes/{id}` | Get a route | ServiceRep, DistrictManager, CirculationDirector |
| PATCH | `/api/routes/{id}` | Update carrier assignment, capacity, or deactivate | DistrictManager, CirculationDirector |
| POST | `/api/carriers` | Create a carrier | DistrictManager, CirculationDirector |
| GET | `/api/carriers` | List carriers | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/carriers/{id}` | Get a carrier | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/carriers/{id}/settlement` | Computed weekly settlement read | DistrictManager, CirculationDirector |
| POST | `/api/route-assignments` | Assign a subscription to a route over a closed interval | DistrictManager, CirculationDirector |
| GET | `/api/route-assignments` | List route assignments | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/route-assignments/{id}` | Get a route assignment | ServiceRep, DistrictManager, CirculationDirector |
| POST | `/api/route-assignments/{id}/end` | End an ACTIVE assignment | DistrictManager, CirculationDirector |
| POST | `/api/rack-locations` | Create a retail rack location | DistrictManager, CirculationDirector |
| GET | `/api/rack-locations` | List rack locations | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/rack-locations/{id}` | Get a rack location | ServiceRep, DistrictManager, CirculationDirector |
| PATCH | `/api/rack-locations/{id}` | Deactivate a rack | DistrictManager, CirculationDirector |
| POST | `/api/rack-sales-reports` | Create a DRAFT weekly rack sales report | DistrictManager, CirculationDirector |
| GET | `/api/rack-sales-reports` | List rack sales reports | ServiceRep, DistrictManager, CirculationDirector |
| GET | `/api/rack-sales-reports/{id}` | Get a rack sales report | ServiceRep, DistrictManager, CirculationDirector |
| PATCH | `/api/rack-sales-reports/{id}` | Correct counts (DRAFT: both; DISPUTED: returned only) | DistrictManager, CirculationDirector |
| POST | `/api/rack-sales-reports/{id}/submit` | Submit or resubmit: computes sold/due/variance | DistrictManager, CirculationDirector |
| POST | `/api/rack-sales-reports/{id}/reconcile` | Reconcile a SUBMITTED report | CirculationDirector |
| POST | `/api/rack-sales-reports/{id}/dispute` | Dispute a SUBMITTED report back for correction | CirculationDirector |
| POST | `/api/payments` | Record a payment | Subscriber, ServiceRep, CirculationDirector |
| GET | `/api/payments` | List payments | ServiceRep, CirculationDirector |
| GET | `/api/payments/{id}` | Get a payment (Subscriber role: own account only) | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/payments/{id}/mark-cleared` | Clear a payment (waterfall allocation) | ServiceRep, CirculationDirector |
| POST | `/api/payments/{id}/mark-failed` | Fail a payment | ServiceRep, CirculationDirector |
| POST | `/api/payments/{id}/reverse` | Reverse a CLEARED payment (depth-3 cascade) | CirculationDirector |
| GET | `/api/billing-charges` | List billing charges (period_start, then created_at) | ServiceRep, CirculationDirector |
| GET | `/api/billing-charges/{id}` | Get a billing charge (Subscriber role: own account only) | Subscriber, ServiceRep, CirculationDirector |
| POST | `/api/billing-charges/{id}/write-off` | Write off an OPEN/PARTIALLY_PAID charge | CirculationDirector |
| POST | `/api/audit-reports` | Create a DRAFT audit report with snapshot totals | CirculationDirector |
| GET | `/api/audit-reports` | List audit reports | CirculationDirector |
| GET | `/api/audit-reports/{id}` | Get an audit report | CirculationDirector |
| POST | `/api/audit-reports/{id}/certify` | Certify: all in-period rack reports RECONCILED; totals recomputed | CirculationDirector |
| POST | `/api/audit-reports/{id}/submit` | Submit a CERTIFIED report to the audit bureau | CirculationDirector |
| POST | `/api/ops/run-daily-cycle` | Run the nightly circulation batch (seven pinned steps) | CirculationDirector |
| POST | `/_clock/set_current_utc` | Set the test-driving logical clock | CirculationDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_OWN_RESOURCE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PLAN_RETIRED` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SERVICE_ADDRESS_REQUIRED` | 409 |
| `ERR_DIGITAL_ONLY_PLAN` | 409 |
| `ERR_OFFER_NOT_OPEN` | 409 |
| `ERR_HOLD_NOT_CANCELLABLE` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_COMPLAINT_NOT_OPEN` | 409 |
| `ERR_COMPLAINT_WINDOW_CLOSED` | 409 |
| `ERR_DUPLICATE_COMPLAINT` | 409 |
| `ERR_REPORT_NOT_EDITABLE` | 409 |
| `ERR_REPORT_NOT_SUBMITTABLE` | 409 |
| `ERR_REPORT_NOT_RECONCILABLE` | 409 |
| `ERR_REPORT_WEEK_CONFLICT` | 409 |
| `ERR_PAYMENT_NOT_INITIATED` | 409 |
| `ERR_PAYMENT_NOT_CLEARED` | 409 |
| `ERR_CHARGE_NOT_OPEN` | 409 |
| `ERR_AUDIT_NOT_DRAFT` | 409 |
| `ERR_AUDIT_NOT_CERTIFIED` | 409 |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 |
| `ERR_UNRECONCILED_RACK_VARIANCE` | 409 |
| `ERR_HOLD_WINDOW_INVALID` | 409 |
| `ERR_HOLD_OVERLAP` | 409 |
| `ERR_HOLD_LIMIT_EXCEEDED` | 409 |
| `ERR_ASSIGNMENT_OVERLAP` | 409 |
| `ERR_ROUTE_AT_CAPACITY` | 409 |
| `ERR_ROUTE_INACTIVE` | 409 |
| `ERR_CREDIT_MEMO_LOCKED` | 409 |
| `ERR_GOODWILL_CAP_EXCEEDED` | 409 |
| `ERR_CREDIT_EXCEEDS_COMPLAINT_CAP` | 409 |
| `ERR_SUBSCRIBER_NOT_SETTLED` | 409 |

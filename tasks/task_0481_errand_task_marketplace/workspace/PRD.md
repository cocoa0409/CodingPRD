# Errand & Task Marketplace API — Product Requirements Document

## 1. Introduction

The Errand & Task Marketplace API powers a two-sided platform — in the spirit of services like TaskRabbit — that connects clients who need everyday errands and tasks done with vetted, skilled taskers who perform them. The platform spans the full arc of a job: a client describes a task within a priced category, the booking is published as an open offer, a dispatcher claims it onto a qualified and available tasker, the tasker travels to the site and performs the work, and the engagement is settled with a final charge, tip, and payout. Around that spine sit the supporting concerns that make a real marketplace work: skill declaration and vetting, per-tasker availability windows, in-app chat between the two parties, mid-job rescheduling, cancellation fees that scale with how close to the start time the cancellation happens, recurring standing bookings, trust-and-safety incident handling that can restrict or suspend a tasker, and post-job ratings that feed re-booking decisions.

Two characteristics shape almost every rule in this document. First, the platform is **time-aware**: same-day dispatch, reschedule windows, cancellation-fee tiers, and the lazy expiry of stale offers are all measured against a server-controlled logical clock rather than wall-clock time, so the system behaves deterministically under test. Second, pricing is **dual-variant**: the quote a client sees when a booking is offered is deliberately distinct from the final settlement computed when the work is done, because the final charge bills the actual claimed tasker's personal rate against actual hours worked. The sections that follow define the global contract every endpoint shares (§2), then the business workflows where the detailed rules live (§3), before summarizing the endpoint surface (§4) and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Where a rule concerns a specific workflow, it is elaborated in §3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`. The system recognizes exactly four roles, spelled precisely as follows: `Client`, `Tasker`, `Dispatcher`, and `TrustSafetyOfficer`. When an authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two of these roles are **entity-backed**, meaning the identity in `X-User-ID` corresponds to a persisted record. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a client — a booking, a recurring series, or a review — compare that resource's client foreign key to `X-User-ID`. When `X-User-Role` is `Tasker`, `X-User-ID` is the `id` of the acting `Tasker`; ownership checks on any resource that references a tasker — the tasker side of a booking, the tasker's skills, availability windows, and the tasker as the subject of an incident — compare the resource's tasker foreign key to `X-User-ID`. When an entity-backed caller targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The remaining two roles are **opaque operators**. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. Likewise, when `X-User-Role` is `TrustSafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded but never matched against an entity `id`. The `Dispatcher` registers categories, taskers, and clients, and claims bookings onto taskers; the `TrustSafetyOfficer` vets skills, files and adjudicates trust incidents, and moderates reviews.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order; the in-app chat log inherits this same ascending-by-`created_at` ordering. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix — it conveys identity only and is never supplied by the client. Most resources also carry three further system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits stamped at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that begins at its initial value and increments by one on every modification, supporting the optimistic concurrency control described in §2.6. There is one exception: a `ChatMessage` is an append-only record that carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field, because a chat message is never modified after it is posted.

The platform runs on a **logical clock** rather than wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it stays at precisely that default and never falls back to the host's real time. An operator may advance the clock by supplying a target instant in the `to_iso8601` field; this is how all time-sensitive behavior — same-day gating, reschedule windows, cancellation-fee tiers, and offer expiry — is exercised deterministically. Whenever an `OFFERED` booking is read after the clock has advanced to or past its `scheduled_start`, the booking is lazily transitioned to `EXPIRED` at read time (see §3.3).

### 2.5. Hierarchical Consistency and Derived-Field Recomputation

Many operations mutate more than one resource. Whenever a child resource changes in a way that affects a parent's derived state, the server reconciles the parent immediately and independently: the parent's `updated_at` is refreshed and its `version` is incremented as part of that reconciliation. For example, claiming, cancelling, or accepting a reschedule on a booking recomputes the affected tasker's counts and bumps that tasker's `version`; adjudicating a trust incident recomputes the tasker's `trust_score` and may cascade into a status change; and moderating a review recomputes the tasker's `rating_count` and `avg_rating`. A tasker's derived fields — `trust_score`, `incident_penalty_total`, `active_booking_count`, `completed_booking_count`, `rating_count`, and `avg_rating` — and the booking's derived schedule and pricing fields are always kept current with respect to the events that drive them. When a tasker is read directly, its `trust_score`, derived `status`, and `avg_rating` are recomputed before the record is returned.

### 2.6. Optimistic Concurrency Control on Tasker Claims

Claiming a booking onto a tasker is guarded by optimistic concurrency control keyed on the tasker's `version`. A claim request must carry `expected_tasker_version`, a non-optional field holding the `version` of the target tasker that the dispatcher last observed. If that value does not equal the tasker's current `version` at the moment the claim is processed, the request is rejected with `ERR_STALE_TASKER_VERSION` (HTTP 412). This protects against acting on a stale view of the tasker: if another booking has been claimed onto the same tasker since the dispatcher last read it — which legitimately consumes that tasker's capacity and changes their schedule — the dispatcher's view is stale, and the claim is rejected on the version check before any availability or overlap re-evaluation that the stale view might otherwise have passed. The same `expected_tasker_version` field and the same stale-version rejection apply when accepting a reschedule proposal, since accepting a reschedule likewise advances the tasker's `version`. Endpoints that do not target a tasker's schedule do not take a version field and perform no concurrency check.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as **integer cents**. Wherever a money figure is derived from a multiplication — labor from a rate times hours, or a service fee from a percentage of labor — the result is computed and then **truncated downward to a whole number of cents** (the fractional part is dropped, never rounded up). This floor-truncation rule applies to every labor, service-fee, total, payout, and cancellation-fee figure in the system. The single place where a different rounding rule applies is a tasker's `avg_rating`, which is a rating average expressed to two decimal places using round-half-up (see §3.7).

### 2.8. Resource Existence and Left-to-Right Path Validation

When a request names resource identifiers — in the path or in the body — the server validates their existence left to right and rejects the request at the first identifier that does not resolve, returning the typed not-found error for that resource: `ERR_BOOKING_NOT_FOUND`, `ERR_TASKER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_SKILL_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_SERIES_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, or `ERR_INCIDENT_NOT_FOUND` as appropriate. A request for a booking's settlement when none has been produced yields `ERR_SETTLEMENT_NOT_FOUND`. Existence is checked before ownership, ownership before state legality, and state legality before the deeper business and field-domain rules, as detailed in §2.9.

### 2.9. Validation Ordering

When several checks could fail on the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) presence and validity of the `X-User-ID` and `X-User-Role` headers, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT`; (2) whether the caller's role is permitted for the operation, failing with `ERR_FORBIDDEN_ROLE`; (3) existence of every referenced resource id, failing with the relevant typed not-found error from §2.8; (4) for entity-backed callers, ownership of the targeted resource, failing with `ERR_NOT_RESOURCE_OWNER`; (5) whether the target resource is in a legal state for the requested transition, failing with the relevant invalid-state error (`ERR_BOOKING_INVALID_STATE`, `ERR_SKILL_INVALID_STATE`, `ERR_INCIDENT_INVALID_STATE`, `ERR_REVIEW_INVALID_STATE`, or `ERR_SERIES_INVALID_STATE`); (6) tasker trust and vetting gates, failing with `ERR_TASKER_SUSPENDED` or `ERR_VETTING_REQUIRED`; (7) temporal rules such as same-day date and not-in-the-past, failing with `ERR_SAME_DAY_DATE_MISMATCH` or `ERR_START_IN_PAST`; (8) availability-window containment, failing with `ERR_OUTSIDE_AVAILABILITY`; (9) booking-versus-booking overlap, failing with `ERR_SCHEDULE_CONFLICT`; (10) reschedule-flow constraints, failing with `ERR_RESCHEDULE_LIMIT` or `ERR_NO_RESCHEDULE_PENDING`; (11) the tasker-version concurrency check on claim, failing with `ERR_STALE_TASKER_VERSION`; and (12) field-domain validation — enum membership, numeric ranges, and the like — failing with `ERR_INVALID_REQUEST`. A consequence worth stating explicitly: because role and existence precede state and business checks, a forbidden caller acting on a non-existent or wrong-state resource still sees the authorization or not-found error first.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations: Categories, Taskers, Clients, and Skills

Everything the marketplace prices and dispatches rests on a **task category**. A `Dispatcher` creates a category by supplying its display `name`, a `pricing_model`, a `default_duration_minutes` that fixes the scheduled window length for fixed-price work and must be at least 15 minutes, and an optional `requires_vetting` flag that defaults to not requiring vetting. The `pricing_model` is one of two values. When it is `HOURLY`, the category must carry a `default_hourly_rate_cents` of at least 1000 cents, which seeds the quote before any tasker is attached. When it is `FIXED`, the category must instead carry a `fixed_price_cents` of at least 1000 cents, the flat charge for the work. A freshly created category opens in `ACTIVE` status. A dispatcher may later retire a category, moving its `status` to `RETIRED`; once retired it admits no new skills or bookings, and any operation that references a `RETIRED` category is rejected with `ERR_CATEGORY_RETIRED`.

A `Dispatcher` registers a **tasker** by supplying a `full_name` and a personal `hourly_rate_cents` of at least 1000 cents — this personal rate is what the tasker is actually billed at when an hourly job settles, as opposed to the category default used for the up-front quote. A new tasker opens in `ACTIVE` status with a `trust_score` of 100. The tasker's other surfaced numbers — `incident_penalty_total`, `active_booking_count`, `completed_booking_count`, `rating_count`, and `avg_rating` — are all derived and start at their natural zero. A dispatcher also registers a **client** by supplying a `full_name`; a new client starts with a `wallet_credit_cents` balance of 0, a refundable credit balance that the platform holds for the client and that never goes negative.

To be eligible for work in a category, a tasker declares a **skill** linking that tasker to that category. Either the tasker themselves or a dispatcher may declare a skill, supplying the `tasker_id` and the `category_id`; the skill's `vetting_status` opens in `PENDING`. A `TrustSafetyOfficer` then adjudicates it. Marking a skill `VETTED` is only permitted while the skill is still `PENDING` and requires the underlying category to be `ACTIVE`. The officer may instead reject a `PENDING` skill, moving it to `REJECTED`, and may also revoke a previously `VETTED` skill by rejecting it, again landing in `REJECTED`; a `REJECTED` skill is terminal and cannot be vetted again, so attempting to vet it fails with `ERR_SKILL_INVALID_STATE`. A category whose `requires_vetting` flag is set demands that, at claim time, the tasker hold a skill for that category in `VETTED` state; absent that, the claim is rejected with `ERR_VETTING_REQUIRED`.

A tasker's bookable time is described by **availability windows**. Either the tasker or a dispatcher creates a window for a tasker by supplying the owning `tasker_id`, an inclusive `window_start`, and a `window_end` that must be strictly later than `window_start`; a created window opens `OPEN`. A window may be closed, moving its `status` to `CLOSED`, after which it no longer admits bookings. Both window endpoints accept their times as ISO 8601 UTC instants.

### 3.2. Quoting and Offering a Booking

A booking is the unit of work. A `Client` (or a `Dispatcher` acting on their behalf) creates a one-off booking by supplying the `client_id`, the `category_id`, a `dispatch_mode`, a `scheduled_start`, an optional `estimated_hours` for hourly work, and an optional `tip_cents` that defaults to 0 and must be at least 0. For hourly categories the `estimated_hours` must be at least 0.25; for fixed categories it is ignored. A new booking is born in `DRAFT` status with no tasker attached — its `tasker_id` stays empty while the booking is `DRAFT` or `OFFERED`. The `dispatch_mode` is either `SAME_DAY` or `SCHEDULED`.

Publishing a draft advances the booking from `DRAFT` to `OFFERED` and is the moment the **quote is pinned**. Three preconditions guard this step: the referenced category must exist and be `ACTIVE`; if the booking's `dispatch_mode` is `SAME_DAY`, the calendar date of `scheduled_start` (in UTC) must equal the current clock's UTC date, and a mismatch is rejected with `ERR_SAME_DAY_DATE_MISMATCH`; and the `scheduled_start` must be strictly later than the current clock instant, a past start being rejected with `ERR_START_IN_PAST`. When the booking is offered, the system pins the estimate. For an hourly category, the estimated labor is the category's `default_hourly_rate_cents` multiplied by the client-supplied `estimated_hours`, then truncated down to whole cents — note that the **category default rate** is used here precisely because no tasker has yet been claimed. For a fixed category, the estimated labor is simply the category's `fixed_price_cents`. The estimated service fee is then fifteen percent of that estimated labor, truncated down to whole cents, and the estimated total is the estimated labor plus the estimated service fee. These three figures are stored as `estimated_labor_cents`, `estimated_service_fee_cents`, and `estimated_total_cents`; the estimate deliberately excludes any tip.

Offering also computes the booking's scheduled window end. The window's duration is the booking's `estimated_hours` converted to minutes (multiplied by 60) for an hourly category, or the category's `default_duration_minutes` for a fixed category; the `scheduled_end` is `scheduled_start` advanced by that many minutes. This `scheduled_end` is what every later availability and overlap check measures against.

### 3.3. Dispatch, Claiming, and the Job-in-Progress Lifecycle

An offered booking sits open until a `Dispatcher` **claims** it onto a specific tasker. The claim payload carries the chosen `tasker_id` and the `expected_tasker_version` described in §2.6. Claiming a booking that is not `OFFERED` is rejected with `ERR_BOOKING_INVALID_STATE`. Beyond the version check, several gates must all pass. The target tasker must not be `SUSPENDED` — a suspended tasker cannot be claimed onto any booking and the attempt fails with `ERR_TASKER_SUSPENDED` — although a `RESTRICTED` tasker may still be claimed through this dispatcher endpoint, since restriction only blocks automatic dispatch, not manual claiming. If the booking's category requires vetting, the tasker must hold a `VETTED` skill for that category, else `ERR_VETTING_REQUIRED`. The booking's window must be contained in one of the tasker's open availability windows, and the booking must not collide with the tasker's other active work; the rules for those two checks live in §3.4. When the claim succeeds, the booking moves to `CLAIMED`, its `tasker_id` is set to the target tasker, the tasker's `version` is incremented by one, and the tasker's `active_booking_count` is recomputed upward to reflect the newly held job.

From `CLAIMED`, the assigned tasker drives the job forward. Departing for the site advances the booking from `CLAIMED` to `EN_ROUTE`; this is permitted only when the caller is the booking's assigned tasker, the tasker is not `SUSPENDED` (a suspended tasker cannot depart, again `ERR_TASKER_SUSPENDED`), and no reschedule proposal is currently pending on the booking. Starting work advances it from `EN_ROUTE` to `IN_PROGRESS`, again only for the assigned tasker. Completing the work advances it from `IN_PROGRESS` to `COMPLETED`; completion is the tasker's to perform, and for an hourly booking the request must carry an `actual_hours` value of at least 0, while a `tip_cents` may optionally accompany it. Completion is the moment the **final settlement** is produced, detailed in §3.5. Any attempt to claim, depart, start, or complete from a state that does not permit it is rejected with `ERR_BOOKING_INVALID_STATE`; in particular, a booking in `IN_PROGRESS` cannot be cancelled and must run through to completion.

An offered booking that is never claimed eventually goes stale. The booking's three terminal states are `COMPLETED`, `CANCELLED`, and `EXPIRED`. When the logical clock reaches or passes an `OFFERED` booking's `scheduled_start` and no tasker has claimed it, the booking lazily transitions to `EXPIRED` the next time it is read — whether read individually or through a list. An expired booking produces no settlement and no cancellation.

### 3.4. Scheduling Constraints: Availability Containment and Buffered Overlap

Two geometric checks decide whether a tasker can take a booking's window, and both run at claim time and again when a reschedule is accepted. The first is **availability containment**. The booking's window, treated as the closed interval from `scheduled_start` to `scheduled_end`, must fit entirely within at least one of the tasker's `OPEN` availability windows, using closed containment with no buffer: there must exist an open window whose `window_start` is at or before the booking's `scheduled_start` and whose `window_end` is at or after the booking's `scheduled_end`. A booking whose end exactly meets a window's `window_end` is allowed; a booking that exceeds the window end by any positive amount is rejected with `ERR_OUTSIDE_AVAILABILITY`.

The second is **buffered overlap**. The platform reserves a travel buffer of 30 minutes after every booking, so a tasker is not double-booked back-to-back without time to travel. To evaluate a candidate window, the system looks at all of the tasker's other bookings currently in `CLAIMED`, `EN_ROUTE`, or `IN_PROGRESS` — excluding the booking being evaluated — scanning them in ascending `created_at` order. Each booking occupies the half-open interval from its start up to its end, with the 30-minute buffer appended after its end. The candidate and an existing booking conflict when the candidate's start is earlier than the other booking's end plus the buffer, and simultaneously the other booking's start is earlier than the candidate's end plus the buffer. Because the intervals are half-open at this buffered boundary, a candidate that starts exactly at another booking's end-plus-buffer does not conflict. Any genuine conflict is rejected with `ERR_SCHEDULE_CONFLICT`.

### 3.5. Settlement: The Final Charge and Payout

When a booking completes, the system creates a one-to-one **settlement** record against it and copies the final money figures onto that record. The settlement diverges from the up-front quote on two axes, which is the whole point of having a distinct final calculation. First, hourly billing uses the **claimed tasker's personal** `hourly_rate_cents`, not the category default rate that seeded the quote. Second, hourly billing measures **actual hours rounded up to the next quarter hour**: the reported `actual_hours` is divided by 0.25, rounded up to the next whole number, and multiplied back by 0.25 to give the billed hours. For an hourly booking, the `final_labor_cents` is the claimed tasker's personal hourly rate multiplied by those billed hours, truncated down to whole cents. For a fixed-price booking, the `final_labor_cents` is simply the category's `fixed_price_cents`, and the quarter-hour and personal-rate rules do not apply.

From that final labor figure the rest of the settlement follows. The `final_service_fee_cents` is fifteen percent of `final_labor_cents`, truncated down to whole cents. The settlement's `tip_cents` is copied from the booking's `tip_cents` as set at completion. The `total_charged_cents` billed to the client is the final labor plus the final service fee plus the tip. The `tasker_payout_cents` is the final labor plus the full tip — the tasker keeps all of the labor and all of the tip, while the platform retains the service fee. Because the final calculation bills the tasker's personal rate against quarter-hour-rounded actual hours, it produces a different labor and fee figure from the quote whenever the tasker's rate differs from the category default, or whenever the actual hours straddle a quarter-hour boundary. Completing the booking also recomputes the tasker's counts: `completed_booking_count` rises by one and `active_booking_count` falls by one. The settlement record for a booking can be retrieved on demand, returned as a collection of zero or one.

### 3.6. Cancellation, Reschedule, and Recurring Series

**Cancellation.** A booking that is `OFFERED`, `CLAIMED`, or `EN_ROUTE` may be cancelled; the request carries a `cancelled_by` of either `CLIENT` or `TASKER`. A `CLIENT` cancellation requires the caller to be the booking's client, and a `TASKER` cancellation requires the caller to be the booking's assigned tasker. The booking must not already be terminal, and — as noted — an `IN_PROGRESS` booking cannot be cancelled at all; an illegal cancellation is rejected with `ERR_BOOKING_INVALID_STATE`. A successful cancellation moves the booking to `CANCELLED`, records who cancelled it in the booking's `cancelled_by`, and creates a one-to-one **cancellation** record. That record captures `hours_before_start` — the difference between the booking's `scheduled_start` and the current clock instant, expressed in hours, which may be negative if the start has already passed — and from it derives the `fee_tier` and `cancellation_fee_cents`. The tier is chosen by threshold against the lead time: 24 or more hours before start is the `FREE` tier with a zero percentage; at least 2 hours but fewer than 24 is the `LATE` tier at twenty-five percent; anything under 2 hours is the `LAST_MINUTE` tier at fifty percent. The fee is that tier's percentage applied to the booking's pinned `estimated_labor_cents` (the labor estimate, not the total), truncated down to whole cents. If a tasker was assigned to the cancelled booking, that tasker's `active_booking_count` is recomputed downward and the tasker's `version` is incremented by one. One further cascade applies: when the cancellation is initiated by the tasker and lands in the `LAST_MINUTE` tier, the system files a trust incident of `MEDIUM` severity against that tasker, which in turn recomputes the tasker's `trust_score` and re-evaluates the trust gate (§3.7).

**Reschedule.** A booking that is `CLAIMED` or `EN_ROUTE` can have its time renegotiated through a propose-then-resolve cycle that leaves the booking's status unchanged; it is tracked entirely by the `reschedule_pending` flag and the `proposed_start` field rather than by a distinct status value. Either party — the client or the assigned tasker — proposes a new `proposed_start`. A proposal is only accepted when no proposal is already pending (a second concurrent proposal is rejected with `ERR_RESCHEDULE_ALREADY_PENDING`), when the booking's `reschedule_count` has not yet reached the cap of three accepted reschedules (a booking at the cap is rejected with `ERR_RESCHEDULE_LIMIT`), and when the `proposed_start` is strictly later than the current clock (a past proposal is rejected with `ERR_START_IN_PAST`). A valid proposal sets `proposed_start` and flips `reschedule_pending` to true. The counterparty then resolves it. Accepting requires a pending proposal and re-runs both scheduling checks of §3.4 against the new window; if either fails, the proposal is left pending and the request returns `ERR_OUTSIDE_AVAILABILITY` or `ERR_SCHEDULE_CONFLICT` accordingly. Acceptance also re-checks the tasker-version concurrency guard, so the accept request carries `expected_tasker_version` and a mismatch is rejected with `ERR_STALE_TASKER_VERSION`. On a clean accept, the booking's `scheduled_start` becomes the `proposed_start`, the `scheduled_end` is recomputed from the window duration, the `reschedule_count` increases by one, `reschedule_pending` clears, and the tasker's `version` is incremented by one. Declining likewise requires a pending proposal, clears `reschedule_pending`, and discards the `proposed_start`. Accepting or declining when nothing is pending is rejected with `ERR_NO_RESCHEDULE_PENDING`.

**Recurring series.** A `Client` (or a `Dispatcher` on their behalf) sets up a **recurring series** of standing bookings by supplying the `client_id`, the `category_id`, a preferred `tasker_id`, a `frequency`, a `first_start`, an `occurrence_count` between 2 and 12 inclusive, and an `estimated_hours` of at least 0.25 that is applied to every hourly occurrence and ignored for fixed categories. The `frequency` is either `WEEKLY` or `BIWEEKLY`, which spaces occurrences 7 or 14 days apart respectively. On creation the series opens `ACTIVE` and immediately generates exactly `occurrence_count` bookings: for each index from zero upward in ascending order, an occurrence is created whose `scheduled_start` is the `first_start` advanced by that index times the day-step, carrying the series's category, tasker, and `estimated_hours`, with its `series_id` set to the owning series, a `dispatch_mode` of `SCHEDULED`, and published directly into `OFFERED` status with its window and quote computed exactly as a one-off offer would be. (A one-off booking that belongs to no series carries an empty `series_id`.) The series records how many it produced in `generated_count`. A series may be ended by its owning client, moving its `status` to `ENDED`; ending it cascades a cancellation over every future not-yet-started occurrence — each child booking still in `DRAFT` or `OFFERED` is moved to `CANCELLED` with the booking's `cancelled_by` set to `SYSTEM` and no fee charged. A `SYSTEM` cancellation produces no cancellation record. Operating on a series that is not `ACTIVE` when the operation requires it is rejected with `ERR_SERIES_INVALID_STATE`.

### 3.7. Trust, Safety, and the Tasker Status Gate

A tasker's standing is governed by a **trust score** and the status gate derived from it. The score starts at 100 for a new tasker and is reduced only by trust incidents. A `TrustSafetyOfficer` files an incident against a tasker by supplying the `tasker_id`, a `severity`, and an optional `booking_id` tying the incident to a specific job. The `severity` is `LOW`, `MEDIUM`, or `HIGH`, carrying `penalty_points` of 5, 15, and 35 respectively while the incident counts against the tasker. A filed incident opens `OPEN`. The officer may uphold an `OPEN` incident, moving it to `UPHELD` while its penalty stays applied, or dismiss it from `OPEN` (or on a granted appeal from `UPHELD`), moving it to `DISMISSED` and setting its `penalty_points` to zero so the penalty is removed. The terminal state for an incident is `DISMISSED`; upholding or dismissing an incident that is not in a legal state is rejected with `ERR_INCIDENT_INVALID_STATE`.

The tasker's `incident_penalty_total` is the sum of `penalty_points` across that tasker's incidents whose status is `OPEN` or `UPHELD`; dismissed incidents are excluded. The `trust_score` is 100 minus that penalty total, floored at 0 so it never goes below zero. Every time the score is recomputed — on filing, upholding, or dismissing an incident — the **trust gate** re-derives the tasker's `status` from the new score: a score below 40 sets the tasker `SUSPENDED`; a score from 40 through 69 inclusive sets the tasker `RESTRICTED`; a score of 70 or more sets the tasker `ACTIVE`. Because dismissing an incident raises the score, it can bubble a tasker back upward — from `SUSPENDED` to `RESTRICTED` to `ACTIVE` — as the score crosses each boundary. A `RESTRICTED` tasker is skipped by automatic dispatch (recurring-series auto-claiming will not select them) but may still be claimed manually by a dispatcher. A `SUSPENDED` tasker keeps any bookings already offered, claimed, or en route, but no new claim may target them and they cannot depart or start work.

**Ratings and re-booking.** After a booking reaches `COMPLETED`, its `Client` may post one **review** of the tasker, supplying the `booking_id`, a `rating_value` from 1 to 5 inclusive, and an optional `comment` of at most 500 characters. The review may only reference a `COMPLETED` booking — otherwise `ERR_BOOKING_NOT_COMPLETED` — and only one review may exist per booking, a second attempt failing with `ERR_DUPLICATE_REVIEW`. A new review is `PUBLISHED` immediately, copies the `tasker_id` from the booking, and recomputes the tasker's rating aggregates. A `TrustSafetyOfficer` may moderate a review: hiding a `PUBLISHED` review moves it to `HIDDEN`, restoring a `HIDDEN` review moves it back to `PUBLISHED`, and removing a `PUBLISHED` or `HIDDEN` review moves it to the terminal `REMOVED` state; an illegal moderation transition is rejected with `ERR_REVIEW_INVALID_STATE`. The tasker's `rating_count` counts only `PUBLISHED` reviews, and the `avg_rating` is the mean of the `rating_value` over those published reviews, expressed to two decimal places using round-half-up, and reported as 0.0 when the tasker has no published reviews. Hiding or removing a review that was published decrements the count and recomputes the average; restoring a hidden review increments the count and recomputes the average. Finally, a satisfied client may **re-book** a completed job: this creates a fresh `DRAFT` booking copying the original booking's client and category, accepting a new `scheduled_start`, `dispatch_mode`, optional `estimated_hours`, and optional `tip_cents`, and leaving the new booking's `tasker_id` empty so it is claimed afresh. Re-booking requires the source booking to be `COMPLETED`, otherwise `ERR_BOOKING_NOT_COMPLETED`.

### 3.8. In-App Chat

Each booking carries a conversation. The booking's `Client` and assigned `Tasker` may each post a message by supplying its `body`, a text between 1 and 1000 characters. The server stamps each message with its `created_at` and derives its `sender_role` — either `CLIENT` or `TASKER` — from the authenticated caller rather than from the payload. Messages are append-only and are never edited or deleted, which is why a chat message carries only `id` and `created_at` among the system fields. The conversation is read back in ascending `created_at` order. Dispatchers and trust-and-safety officers may read a booking's chat for oversight but do not post into it.

## 4. Endpoint Definitions

Operations that create a new, standalone resource — a category, tasker, client, booking, skill, availability window, recurring series, review, trust incident, chat message, or a re-booked draft — return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. The request body, response body, and side effects of each endpoint are described in the §3 narratives above; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Dispatcher, TrustSafetyOfficer |
| POST | `/task-categories` | Create a task category | Dispatcher |
| GET | `/task-categories` | List categories | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| GET | `/task-categories/{id}` | Get a category | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| POST | `/task-categories/{id}/retire` | Retire a category | Dispatcher |
| POST | `/taskers` | Register a tasker | Dispatcher |
| GET | `/taskers` | List taskers | Dispatcher, TrustSafetyOfficer, Client |
| GET | `/taskers/{id}` | Get a tasker (derived trust/status/rating) | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| GET | `/taskers/{id}/skills` | List a tasker's skills | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| POST | `/tasker-skills` | Declare a tasker skill for a category | Dispatcher, Tasker |
| GET | `/tasker-skills` | List/filter tasker skills | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| GET | `/tasker-skills/{id}` | Get a single tasker skill | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| POST | `/tasker-skills/{id}/vet` | Mark a skill VETTED | TrustSafetyOfficer |
| POST | `/tasker-skills/{id}/reject` | Reject/revoke a skill | TrustSafetyOfficer |
| POST | `/availability-windows` | Create an availability window | Dispatcher, Tasker |
| GET | `/availability-windows` | List/filter availability windows | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| GET | `/availability-windows/{id}` | Get a single availability window | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| POST | `/availability-windows/{id}/close` | Close a window | Dispatcher, Tasker |
| POST | `/clients` | Register a client | Dispatcher |
| GET | `/clients` | List clients | Dispatcher, TrustSafetyOfficer |
| GET | `/clients/{id}` | Get a client | Dispatcher, TrustSafetyOfficer, Client |
| POST | `/bookings` | Create a one-off booking in DRAFT | Client, Dispatcher |
| GET | `/bookings` | List/filter bookings | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| GET | `/bookings/{id}` | Get a booking | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| POST | `/bookings/{id}/offer` | Publish a DRAFT booking as OFFERED | Client, Dispatcher |
| POST | `/bookings/{id}/claim` | Claim an OFFERED booking onto a tasker | Dispatcher |
| POST | `/bookings/{id}/depart` | Assigned tasker departs | Tasker |
| POST | `/bookings/{id}/start` | Assigned tasker starts work | Tasker |
| POST | `/bookings/{id}/complete` | Assigned tasker completes; creates settlement | Tasker |
| POST | `/bookings/{id}/cancel` | Cancel a non-terminal, non-IN_PROGRESS booking | Client, Tasker |
| POST | `/bookings/{id}/reschedule/propose` | Propose a new scheduled start | Client, Tasker |
| POST | `/bookings/{id}/reschedule/accept` | Accept the pending proposal | Client, Tasker |
| POST | `/bookings/{id}/reschedule/decline` | Decline the pending proposal | Client, Tasker |
| GET | `/bookings/{id}/settlement` | Get the settlement for a booking | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| GET | `/bookings/{id}/cancellation` | Get the cancellation for a booking | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| POST | `/bookings/{id}/messages` | Post a chat message to a booking | Client, Tasker |
| GET | `/bookings/{id}/messages` | List chat messages for a booking | Client, Tasker, Dispatcher, TrustSafetyOfficer |
| POST | `/bookings/{id}/rebook` | Re-book a completed booking | Client |
| POST | `/recurring-series` | Create a recurring series | Client, Dispatcher |
| GET | `/recurring-series` | List/filter recurring series | Dispatcher, TrustSafetyOfficer, Client |
| GET | `/recurring-series/{id}` | Get a recurring series | Dispatcher, TrustSafetyOfficer, Client |
| POST | `/recurring-series/{id}/end` | End a series; cascade-cancel future occurrences | Client, Dispatcher |
| POST | `/reviews` | Review a completed booking's tasker | Client |
| GET | `/reviews` | List/filter reviews | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| GET | `/reviews/{id}` | Get a single review | Dispatcher, TrustSafetyOfficer, Client, Tasker |
| POST | `/reviews/{id}/hide` | Hide a published review | TrustSafetyOfficer |
| POST | `/reviews/{id}/restore` | Restore a hidden review | TrustSafetyOfficer |
| POST | `/reviews/{id}/remove` | Permanently remove a review | TrustSafetyOfficer |
| POST | `/trust-incidents` | File a trust/safety incident against a tasker | TrustSafetyOfficer |
| GET | `/trust-incidents` | List/filter incidents | Dispatcher, TrustSafetyOfficer |
| GET | `/trust-incidents/{id}` | Get a single trust incident | Dispatcher, TrustSafetyOfficer |
| POST | `/trust-incidents/{id}/uphold` | Uphold an OPEN incident | TrustSafetyOfficer |
| POST | `/trust-incidents/{id}/dismiss` | Dismiss an incident; cascade trust recompute | TrustSafetyOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_TASKER_NOT_FOUND` | 404 Not Found |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_CATEGORY_NOT_FOUND` | 404 Not Found |
| `ERR_SKILL_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_SERIES_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_INVALID_STATE` | 409 Conflict |
| `ERR_SKILL_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_REVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_SERIES_INVALID_STATE` | 409 Conflict |
| `ERR_CATEGORY_RETIRED` | 409 Conflict |
| `ERR_TASKER_SUSPENDED` | 409 Conflict |
| `ERR_VETTING_REQUIRED` | 409 Conflict |
| `ERR_SAME_DAY_DATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_START_IN_PAST` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_AVAILABILITY` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_RESCHEDULE_LIMIT` | 409 Conflict |
| `ERR_NO_RESCHEDULE_PENDING` | 409 Conflict |
| `ERR_RESCHEDULE_ALREADY_PENDING` | 409 Conflict |
| `ERR_STALE_TASKER_VERSION` | 412 Precondition Failed |
| `ERR_BOOKING_NOT_COMPLETED` | 409 Conflict |
| `ERR_DUPLICATE_REVIEW` | 409 Conflict |

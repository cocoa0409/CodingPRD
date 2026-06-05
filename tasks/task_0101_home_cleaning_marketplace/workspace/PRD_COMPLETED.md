# Home Cleaning Marketplace API — Product Requirements Document

## 1. Introduction

The Home Cleaning Marketplace connects households that need recurring or one-off cleaning visits with vetted independent cleaning professionals. The platform owns three hard problems that a casual booking tool cannot: it must onboard cleaners through a background-check gate before they may ever take a job, it must price each visit deterministically from home size, optional add-ons, who supplies the cleaning materials, and the customer's loyalty standing, and it must keep a customer's wallet balance, a cleaner's payout, and the platform's ledger in perfect agreement after every charge, refund, fee, and tip.

This document specifies the API that drives the marketplace end to end. It covers cleaner onboarding and adjudication, the recurring-series engine that mints individual visits on a weekly or biweekly cadence, the one-time booking flow, preferred-pro assignment and automatic cleaner selection, the reschedule-and-cancellation window-fee policy, in-app tipping, and the satisfaction guarantee that lets a customer claim a free re-clean within a bounded window after a completed visit. Money is tracked in integer cents throughout, and every balance-moving operation settles atomically inside the request that triggers it — there are no deferred or background reconciliations.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. Requests that omit either header, or that supply a malformed value, are rejected with `ERR_UNAUTHENTICATED`. When the headers are well formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Customer`, `Cleaner`, and `PlatformAdmin`.

`Anonymous` is the unauthenticated self-registration surface; its identity is opaque and is never tied to any persisted entity. It exists only so that a brand-new person can register themselves as either a customer or a cleaner before they have an account to act on behalf of.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a customer compare that resource's `customer_id` foreign key to `X-User-ID`; a customer acting on a booking, address, series, preferred-pro association, tip, or ledger entry that they do not own is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

When `X-User-Role` is `Cleaner`, `X-User-ID` is the `id` of the acting `Cleaner` entity. A cleaner may only complete a booking whose assigned `cleaner_id` equals `X-User-ID`; acting on a booking assigned to a different cleaner is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`; the platform admin runs onboarding, background-check adjudication, plan activation, series generation, reclean scheduling, the test-driving clock, and the loyalty seed, and may read every collection.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. The `offset` parameter is the number of items to skip before collecting the page and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full size of the filtered collection and `has_more` indicates whether additional items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource is assigned a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry an `updated_at` timestamp, refreshed to an ISO 8601 UTC instant on every mutation, and a `version` integer that begins at its initial value and increments by one on every mutation of that resource.

Two resources are deliberately immutable append-only records and therefore carry only `id` and `created_at`, with no `updated_at` and no `version` field: the `Tip` and the `LedgerEntry`. Once written, a tip or a ledger entry is never updated in place; corrections are expressed as additional ledger entries rather than edits.

Whenever a transition refreshes a resource, it both advances that resource's `version` by one and updates its `updated_at`. Several operations touch more than one resource in a single request — for example, generating a series occurrence mutates the series and creates a booking and a ledger entry — and in those cases each mutated resource independently advances its own `version` and `updated_at`.

### 2.5. Resource Addressing and Existence Ordering

The marketplace uses a flat resource topology: every resource is addressable by its own collection and `id`, and foreign keys travel in request bodies and query strings rather than in nested URL segments. Before any business rule runs, the server resolves every identifier referenced by the request — the path `id` and every body or query foreign key such as `customer_id`, `address_id`, `cleaner_id`, `booking_id`, `series_id`, and `pricing_plan_id` — validating them left-to-right in the order they appear. The first identifier that does not resolve to an existing resource causes the request to fail immediately with `ERR_NOT_FOUND`, before later identifiers or business checks are considered.

### 2.6. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every referenced identifier (`ERR_NOT_FOUND`), then ownership for entity-backed actors (`ERR_FORBIDDEN_OWNERSHIP`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after these five gates pass does the server evaluate domain-specific business rules. Within the business tier the ordering, where multiple apply to the same call, runs: cleaner-cleared check, reclean eligibility, reclean window, add-on permissibility, address-archived check, cleaner-availability, cleaner double-booking, address double-booking, tip permissibility, optimistic-concurrency version match, and finally request-body field validation. Request-body type and enum validation (`ERR_INVALID_REQUEST`) is the lowest-priority business check; a malformed enum is only reported once the higher-priority structural and state gates have passed.

### 2.7. Optimistic Concurrency Control

Two operations mutate a shared invariant and are therefore guarded by optimistic concurrency control, where the client must echo back the `version` it last observed on the parent resource.

Generating the next occurrence of a recurring series requires the request to carry `expected_series_version`, which must equal the target series' current `version`. A prior generation legitimately creates a booking, advances the series' next occurrence date, and increments the series `version`; if a client's `expected_series_version` no longer matches because the series has since advanced, the generation is rejected with `ERR_STALE_VERSION` and HTTP status 412, so the same occurrence date can never be double-generated from a stale view.

Activating a pricing plan requires the request to carry `expected_plan_version`, which must equal that plan's current `version`. Because activation deactivates the previously active plan and bumps the activating plan's `version`, a second activation that still carries the previously observed version is acting on a stale view and is rejected with `ERR_STALE_VERSION` and HTTP status 412, resolving the single-active-plan invariant deterministically.

No other endpoint accepts a version field; only series generation and plan activation participate in concurrency control.

### 2.8. Monetary Precision and Rounding

All money is stored and returned as integer cents — there are no fractional cents and no floating-point currency. Wherever a percentage is applied to a cents amount (an add-on surcharge, a loyalty discount, a late-cancellation percentage, or a commission split), the multiplication is rounded half-up to a whole cent. Rounding is applied per component: in the price quote, each add-on surcharge and the loyalty discount are each rounded to whole cents before they are combined, rather than summing first and rounding once at the end. A customer's `wallet_credit_cents` is constrained never to drop below zero through any operation.

### 2.9. The Ledger Invariant

Every movement of money against a customer is recorded as a `LedgerEntry` whose `kind` is one of `CHARGE` (a debit against the customer), `REFUND` (a credit to the customer), `RECLEAN_CREDIT` (a zero-valued marker that records a guarantee re-clean carries no customer charge), or `CHANGE_FEE` (a debit for a reschedule or cancellation window fee). Each entry records the `customer_id` whose balance it moves, the originating `booking_id` (null for non-booking adjustments), and a signed `amount_cents` where a positive value credits the customer and a negative value debits them. When a booking is cancelled, the refund credits the full `quoted_price_cents` back, and any assessed window fee is recorded as a separate negative `CHANGE_FEE` entry, so the net refund equals the quoted price minus the window fee — the ledger conserves exactly the original charge less the fee, never more.

### 2.10. Cascading State Propagation

State changes can ripple from a parent to its children inside the same request. Cancelling a recurring series cancels every child booking still in a non-terminal state, and each of those child cancellations runs its own refund-and-fee settlement transitively; children that have already reached `COMPLETED` or `CANCELLED` are left untouched. Likewise, scheduling a re-clean spawns an entirely new booking as a side effect. In every such cascade, each affected resource independently advances its own `version` and `updated_at`, and every ledger movement triggered along the way is written as its own entry, all within the single triggering request.

## 3. Business Logic & Workflows

### 3.1. Cleaner Onboarding and the Background-Check Gate

A prospective cleaner registers themselves through the anonymous self-registration surface, supplying an `email` (stored lowercased; the platform does not enforce email uniqueness across cleaners, so a registration whose email duplicates an existing cleaner's is accepted rather than rejected), a `full_name`, and the list of `service_postal_codes` they intend to serve. A freshly registered cleaner begins in `APPLIED` status and may not take any work until they clear vetting. The cleaner record also carries running reputation counters maintained by the platform: `rating_sum` accumulates the star ratings (each from 1 to 5) received on completed visits, `rating_count` counts how many ratings have arrived, and `completed_job_count` counts the visits the cleaner has personally driven to `COMPLETED`. All three begin at zero.

A `PlatformAdmin` opens the vetting process by creating a background check against an `APPLIED` cleaner, supplying the external screening vendor's `provider_ref`. This advances the cleaner from `APPLIED` to `CHECK_PENDING` and creates a `BackgroundCheck` record — referencing the cleaner via `cleaner_id` — whose `result` starts at `PENDING` with a null `adjudicated_at`. The cleaner's `version` increments by one. Attempting to open a check on a cleaner who is not in `APPLIED` is rejected with `ERR_INVALID_STATE`.

Adjudication resolves a `CHECK_PENDING` cleaner's check, and is permitted only while the cleaner is in `CHECK_PENDING` and the check's `result` is still `PENDING` at call time. When a `PlatformAdmin` adjudicates with a clear outcome, the check's `result` is set to `CLEAR`, `adjudicated_at` is stamped with the current instant, and the cleaner advances from `CHECK_PENDING` to `CHECK_PASSED`. When the adjudication outcome is adverse, the check's `result` is set to `ADVERSE`, `adjudicated_at` is stamped, and the cleaner advances from `CHECK_PENDING` to `CHECK_FAILED`. Either way the cleaner's `version` increments by one. `CHECK_FAILED` is terminal: a cleaner who has failed vetting can never be activated and is permanently barred from work.

A `CHECK_PASSED` cleaner becomes assignable only once a `PlatformAdmin` activates them, moving `CHECK_PASSED` to `ACTIVE` and incrementing the cleaner's `version`. An active cleaner can be pulled from the assignable pool by suspension, moving `ACTIVE` to `SUSPENDED`; the same activation action reinstates a suspended cleaner, moving `SUSPENDED` back to `ACTIVE`. This `ACTIVE → SUSPENDED → ACTIVE` reinstatement loop is distinct from the terminal `CHECK_FAILED` branch. Each suspend and each reinstatement increments the cleaner's `version`. Any of these transitions attempted from the wrong state yields `ERR_INVALID_STATE`. The platform admin may also read a cleaner's background checks for audit, and the catalog of cleaners can be filtered by `status` and by serving `postal_code`.

### 3.2. Customers, Addresses, and Pricing Plans

A customer registers anonymously with an `email` (stored lowercased; the platform does not enforce email uniqueness across customers, so a registration whose email duplicates an existing customer's is accepted rather than rejected) and a `full_name`. On creation the platform initializes their `wallet_credit_cents` to 0 and their `lifetime_booking_count` to 0. The wallet holds non-negative store credit that is drawn down first whenever a booking is charged and topped up by re-clean compensation and cancellation refunds; the lifetime count tracks how many of the customer's bookings have reached `COMPLETED` and stayed there, and it drives the loyalty discount described in §3.6. A `PlatformAdmin` may grant or revoke store credit out of band through a credit adjustment that moves `wallet_credit_cents` by a supplied `amount_cents` (with an optional `reason`), never letting the resulting balance fall below zero, and increments the customer's `version`. For testing convenience an admin may also seed a customer's `lifetime_booking_count` directly to a supplied value, which likewise increments the customer's `version`.

A customer registers one or more service addresses, each created with the owning `customer_id`, a `line1` street line, a `postal_code` used for cleaner service-area matching, and a `home_size` band drawn from `STUDIO`, `ONE_BR`, `TWO_BR`, `THREE_BR`, or `FOUR_PLUS_BR`. The home-size band anchors the base price. An address carries an `archived` soft-delete flag that begins false. A customer may archive an address, setting `archived` to true and incrementing the address `version`; archived addresses are hidden from default address listings (unless a list request opts in with `include_archived`) and may not anchor any new booking or series, though they remain readable and keep historical bookings valid. The address list endpoint filters by `customer_id`.

Pricing is governed by rate cards. A `PlatformAdmin` creates a `PricingPlan` with a human `name`, a `base_price_cents` map from each home-size band to a base price in cents, a `deep_clean_surcharge_pct` fractional surcharge applied to base when the deep-clean add-on is present, a `move_out_surcharge_pct` fractional surcharge applied when the move-out add-on is present, and a flat `supplies_fee_cents` charged when the cleaner rather than the customer brings supplies. A new plan is created inactive, with its `active` flag false. Exactly one plan may be active at any moment; activating a plan sets its `active` flag true and clears the `active` flag on the previously active plan, as described under concurrency control in §2.7.

### 3.3. One-Time Bookings: Assignment, Scheduling, and Charging

A `Customer` creates a one-time booking by supplying the owning `customer_id`, the `address_id` to be cleaned, the `pricing_plan_id` whose rate card is pinned to this visit, and the `scheduled_start` instant of the visit; they may also supply `add_ons`, a `supplies_provided_by` choice, and an explicit `cleaner_id` to pin a specific pro. At creation the booking snapshots its `home_size` from the address so that later edits to the address never retro-change this visit's price, and it records the `supplies_provided_by` choice as either `CUSTOMER` (no supplies fee) or `CLEANER` (supplies fee added), defaulting to `CUSTOMER`. The `add_ons` field is a subset of the codes `DEEP_CLEAN` and `MOVE_OUT` and defaults to empty. A booking begins in `SCHEDULED` status, and a booking created directly by a customer leaves its `series_id` null while a series-generated booking carries the originating `series_id`.

The visit's end instant, `scheduled_end`, is computed from the snapshot home size: the visit duration is 90 minutes for a `STUDIO`, 120 minutes for a `ONE_BR`, 150 minutes for a `TWO_BR`, 180 minutes for a `THREE_BR`, and 240 minutes for a `FOUR_PLUS_BR`, and `scheduled_end` is `scheduled_start` plus that duration. Add-ons never change the length of the visit. The half-open interval running from `scheduled_start` up to but not including `scheduled_end` is the window the visit occupies, and it is the interval used for the double-booking checks in §3.5.

Cleaner selection runs as a side effect of creation and writes the booking's `cleaner_id`. When a customer pins a specific cleaner — by supplying `cleaner_id` on the booking, or via a series' `preferred_cleaner_id` — the selector is bypassed and the pinned cleaner is used, provided they are `ACTIVE` and serve the address postal code. A pin that exists and serves the area but is not `ACTIVE` (for example `SUSPENDED`, or `CHECK_PASSED` but not yet activated) is rejected with `ERR_CLEANER_NOT_CLEARED`; a pin that does not serve the postal code is rejected with `ERR_NO_CLEANER_AVAILABLE`. When no cleaner is pinned, the selector builds a candidate set of cleaners whose `status` is `ACTIVE` and whose `service_postal_codes` include the address postal code. If the customer has any preferred-pro associations whose cleaner is in that candidate set, the pool is narrowed to just those preferred pros; otherwise the full candidate set is the pool. An empty pool yields `ERR_NO_CLEANER_AVAILABLE`. The pool is ranked deterministically, using only entity fields and never the `id`: first by preferred-pro `priority` ascending when the pool is the preferred subset (lower number is stronger preference), then by average rating descending — computed as `rating_sum` divided by `rating_count`, treated as zero when `rating_count` is zero and compared as an exact ratio to avoid floating-point ties — then by `completed_job_count` descending, and finally by `created_at` ascending as the last tie-break. The top-ranked cleaner is assigned.

Once priced (see §3.6), creation charges the customer: a `LedgerEntry` of kind `CHARGE` is written for the booking, the customer's `wallet_credit_cents` is drawn down first against the quoted amount, and any remainder is accrued against the customer. The booking's final `quoted_price_cents` and any later `change_fee_cents` are pinned on the booking record; `change_fee_cents` is initialized to 0 at creation and is overwritten with the most recently assessed window fee on each reschedule or cancellation (it holds the latest fee, not a running total).

### 3.4. Recurring Series and Occurrence Generation

A `Customer` sets up recurring service as a `BookingSeries`, supplying the owning `customer_id`, the `address_id` serviced on every occurrence, the `pricing_plan_id` pinned at series creation, a `cadence` of either `WEEKLY` or `BIWEEKLY`, and a `first_occurrence_date` that seeds the series' `next_occurrence_date`. They may also supply `add_ons`, a `supplies_provided_by` choice, and an optional `preferred_cleaner_id` that pins the same pro to every occurrence; when `preferred_cleaner_id` is null, each occurrence is auto-assigned at generation time. A series begins in `ACTIVE` status. The move-out add-on may not appear on a recurring series — supplying `MOVE_OUT` in a series' `add_ons` is rejected with `ERR_ADDON_NOT_ALLOWED` — and a series anchored on an archived address is rejected with `ERR_ADDRESS_ARCHIVED`.

A `PlatformAdmin` mints the next visit by generating against an `ACTIVE` series whose `next_occurrence_date` is at or before the current clock; generating against a series whose `next_occurrence_date` is null or still in the future (not yet due) is rejected with `ERR_INVALID_STATE`. Generation, guarded by the `expected_series_version` concurrency check of §2.7, creates a child booking in `SCHEDULED` status whose `scheduled_start` is the series' `next_occurrence_date`, copying the series' `add_ons` and `supplies_provided_by`; it then assigns a cleaner (honoring the series' pinned pro, otherwise running the selector of §3.3), runs the price quote and pins the new booking's `quoted_price_cents`, writes a `CHARGE` ledger entry and draws down the customer wallet with the remainder accrued, and advances `next_occurrence_date` by the cadence step — 7 days for `WEEKLY`, 14 days for `BIWEEKLY`. The series `version` increments by one. Because the loyalty tier is read at each generation instant and the customer's `lifetime_booking_count` grows as earlier occurrences complete, two occurrences of the same series can legitimately quote different prices.

A customer may pause an `ACTIVE` series, moving it to `PAUSED` so no further occurrences generate, and resume a `PAUSED` series back to `ACTIVE` with generation re-enabled from the current `next_occurrence_date`. A customer may cancel a series that is in either `ACTIVE` or `PAUSED`, moving it to the terminal `CANCELLED` state. Cancellation cascades: every child booking still in `SCHEDULED` or `RESCHEDULED` is cancelled, and each such child cancellation runs its own refund-and-fee settlement transitively as in §3.5; children already `COMPLETED` or `CANCELLED` are untouched. Cancellation also sets the series' `next_occurrence_date` to null and increments the series `version`. Each pause, resume, and cancel increments the series `version`, and a transition attempted from a disallowed state is rejected with `ERR_INVALID_STATE`. Series can be listed and filtered by `customer_id`, `address_id`, `pricing_plan_id`, and `preferred_cleaner_id`.

### 3.5. Rescheduling, Cancellation, and the Window Fee

A booking in `SCHEDULED` or `RESCHEDULED` status may be moved by its owning customer, who supplies the new `scheduled_start` and may also revise `add_ons` and `supplies_provided_by`. A reschedule recomputes the window fee under the reschedule branch (described below) — measuring the hours-to-start against the booking's current (pre-move) `scheduled_start`, not the proposed new instant — assesses any resulting `change_fee_cents` as a negative `CHANGE_FEE` ledger entry that debits the customer when the fee is greater than zero, sets the booking's `scheduled_start` to the new instant, re-pins `quoted_price_cents` if the add-ons or supplies changed, and moves the booking to `RESCHEDULED`. A `RESCHEDULED` booking can be rescheduled again, returning to `RESCHEDULED`; this is the revision loop. If the booking carries a pinned cleaner, that cleaner must still serve the address postal code for the reschedule to proceed; if the assigned cleaner no longer serves the address postal code the reschedule is rejected with `ERR_NO_CLEANER_AVAILABLE` (this is the only cleaner re-check on reschedule — the cleaner's current `status` is not re-verified). Each reschedule increments the booking `version`.

Cancellation of a `SCHEDULED` or `RESCHEDULED` booking by its owning customer computes the window fee under the cancel branch, writes a `REFUND` ledger entry crediting the customer's wallet the full `quoted_price_cents` for the un-rendered visit, and — when the computed fee is greater than zero — writes a separate negative `CHANGE_FEE` ledger entry debiting the customer, so the net refund is the quoted price minus the window fee. The booking moves to the terminal `CANCELLED` state and its `version` increments.

The window fee is a function of how many whole hours remain until the visit starts, computed as the difference between the booking's `scheduled_start` and the current clock expressed in hours. The boundary is inclusive on the free side: if at least 48 hours remain, there is no fee. If fewer than 48 hours but at least 12 hours remain, the visit is in the late band; and if fewer than 12 hours remain — which includes any instant at or after the start time — the visit is in the no-show band. For a reschedule, the fee in either the late band or the no-show band is a flat 1500 cents and is never a percentage. For a cancellation, the fee escalates: in the late band it is 25 percent of the booking's `quoted_price_cents`, and in the no-show band it is 50 percent of `quoted_price_cents`, in each case rounded half-up to whole cents. Outside the window — 48 hours or more out — both reschedule and cancellation incur no fee.

Before a booking or reschedule is accepted, two temporal collision checks run. The cleaner double-booking check rejects, with `ERR_CLEANER_DOUBLE_BOOKED`, any visit whose assigned cleaner already holds another non-terminal booking (in `SCHEDULED` or `RESCHEDULED`) whose interval, extended by a 30-minute travel buffer on each side, overlaps this visit's half-open interval; adjacency closer than the 30-minute buffer counts as a collision because the cleaner needs travel time between jobs. The address double-booking check rejects, with `ERR_ADDRESS_DOUBLE_BOOKED`, any visit whose service address already holds another non-terminal booking whose raw half-open interval overlaps this visit's raw half-open interval; here there is no travel buffer, so two back-to-back visits that share exactly the boundary instant do not collide. Both checks apply to one-time booking creation, series generation, and reschedule.

### 3.6. Pricing: Home Size, Add-Ons, Supplies, and Loyalty

A booking's price is computed deterministically at creation, re-pinned on reschedule when add-ons or supplies change, and recomputed at each series generation. A re-clean visit is always priced at zero. For every other visit, pricing proceeds in a pinned order. The base is the pinned plan's `base_price_cents` entry for the booking's snapshot `home_size`. A surcharge accumulator starts at zero; if `DEEP_CLEAN` is among the add-ons, the base multiplied by `deep_clean_surcharge_pct` (rounded half-up to whole cents) is added to it, and if `MOVE_OUT` is among the add-ons, the base multiplied by `move_out_surcharge_pct` (rounded half-up to whole cents) is added to it. The supplies component is the plan's `supplies_fee_cents` when `supplies_provided_by` is `CLEANER`, and zero when it is `CUSTOMER`. The subtotal is the base plus the surcharge accumulator plus the supplies component.

The loyalty discount is keyed off the customer's `lifetime_booking_count` read at quote time, which never includes the in-flight booking itself. The discount rate is 0 percent when the count is below 5, 5 percent when the count is at least 5 but below 15, 10 percent when the count is at least 15 but below 40, and 15 percent when the count is 40 or more. The discount is the subtotal multiplied by that rate, rounded half-up to whole cents, and the priced amount is the subtotal minus the discount. Finally, a move-out floor applies: when `MOVE_OUT` is among the add-ons, the priced amount is raised if necessary so that it is never below 20000 cents. The resulting amount is pinned as `quoted_price_cents`. For a one-time booking the loyalty tier is read at the single creation instant; for a series occurrence it is read at the generation instant, which is why successive occurrences of one series can quote differently as the customer's lifetime count climbs.

### 3.7. Completion, Payouts, Tips, and the Satisfaction Guarantee

The assigned cleaner marks a visit done once the current clock has reached or passed the booking's `scheduled_start`, the booking is in `SCHEDULED` or `RESCHEDULED`, and the acting cleaner is the booking's assigned `cleaner_id`; an attempt to complete before the clock has reached `scheduled_start` is rejected with `ERR_INVALID_STATE`. Completion may carry an optional `rating` from the customer-facing star scale; when present it folds into the cleaner's `rating_sum` and `rating_count`. Completing the visit moves the booking to `COMPLETED`, computes the cleaner's payout, and creates a `CleanerPayout` record referencing the `cleaner_id` and `booking_id` with a `base_payout_cents` equal to 70 percent of the booking's `quoted_price_cents` rounded half-up to whole cents, a `tip_cents` of 0, and a `total_cents` equal to `base_payout_cents` plus `tip_cents`. Unless the visit is a re-clean, completion also increments the customer's `lifetime_booking_count` by one and the cleaner's `completed_job_count` by one; a re-clean's `quoted_price_cents` is zero, so its `base_payout_cents` is zero and the cleaner is not paid again, and it does not bump either of those two counters (an optional `rating` supplied on a re-clean completion, however, still folds into `rating_sum` and `rating_count`). The booking `version` increments. Payouts can be read and listed, filtered by `cleaner_id` or `booking_id`.

After a visit completes, its owning customer may tip the cleaner. A tip supplies the `booking_id`, the tipping `customer_id`, and the `amount_cents` (which must be greater than zero); the cleaner being tipped is copied onto the tip as `cleaner_id` from the booking. A tip is permitted only on a `COMPLETED` booking, only by the booking's owning customer, and at most once per booking — a tip on a non-completed booking, by a non-owner, or a second tip on the same booking is rejected with `ERR_TIP_NOT_ALLOWED`. Creating the tip recomputes the booking's existing `CleanerPayout`: the payout's `tip_cents` is set to the tip's `amount_cents` and its `total_cents` becomes `base_payout_cents` plus the new `tip_cents`. Tip amounts are already whole cents and are not rounded. Tips can be listed and filtered by `booking_id`, `customer_id`, and `cleaner_id`.

The satisfaction guarantee lets a customer claim a free re-clean. Requesting a re-clean is permitted only when the booking is `COMPLETED`, is not itself a re-clean (a re-clean cannot itself be recleaned), and the request arrives within 72 hours of the booking's completion instant. A request on an ineligible booking — one that is not completed, is itself a re-clean, or already has an open re-clean — is rejected with `ERR_RECLEAN_NOT_ELIGIBLE`, and a request that arrives after the 72-hour window has closed is rejected with `ERR_RECLEAN_WINDOW_CLOSED`. A valid request moves the booking from `COMPLETED` to `RECLEAN_REQUESTED` and increments its `version`. A `PlatformAdmin` then schedules the free re-clean against a `RECLEAN_REQUESTED` booking, which moves that booking to the terminal `RECLEAN_SCHEDULED` state and spawns a brand-new booking. The spawned booking carries `reclean_of_booking_id` pointing at the original, sets `is_reclean` to true, pins `quoted_price_cents` to 0, copies the original's `cleaner_id` (re-running assignment pinned to that original cleaner), copies the original's `add_ons` and `supplies_provided_by`, takes its `scheduled_start` from the `scheduled_start` supplied in the schedule-reclean request body (with `scheduled_end` recomputed from the address's home size), and starts in `SCHEDULED`; the two temporal collision checks of §3.5 are not run for the guarantee re-clean, so the spawned booking is created even if it overlaps another visit. Its creation writes a `RECLEAN_CREDIT` ledger entry valued at 0 as a marker, with no customer charge. The original booking's `version` increments. Although the schedule-reclean call also transitions the original booking, its `200 OK` response body returns the spawned brand-new re-clean booking — not the transitioned original — as the resource object in `data`. Bookings can be listed and filtered by `customer_id`, `address_id`, `pricing_plan_id`, `cleaner_id`, `series_id`, `reclean_of_booking_id`, and `status`.

Customers favorite cleaners by creating a preferred-pro association, supplying the `customer_id`, the favorited `cleaner_id`, and a `priority` of at least 1 where a lower number means stronger preference; this `priority` is the primary sort key when the assignment selector chooses among a customer's preferred pros, as described in §3.3. Preferred-pro associations can be listed and filtered by `customer_id` or `cleaner_id`. Ledger entries can be read and listed, filtered by `customer_id`, `booking_id`, and `kind`.

A `PlatformAdmin` controls a test-driving clock that sets the server's current UTC instant from a supplied `to_iso8601` value; this clock gates the window-fee bands and the re-clean window, so advancing it is how the passage of time is simulated. Until the clock has been explicitly set, the server's current instant falls back to real wall-clock UTC. Setting the clock returns a `200 OK` with an empty object in `data`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (such as registering a customer or cleaner, creating an address, a pricing plan, a preferred-pro association, a booking series, a booking, a tip, a background check, a credit adjustment, or generating a series occurrence) return a `201 Created` status. Operations that modify an existing resource — every state transition, activation, archival, adjudication, and the test-driving clock and loyalty-seed calls — return a `200 OK` status. The request and response payloads for each endpoint are described in the §3 narratives; the table below lists only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cleaning/customers` | Register a customer | Anonymous |
| GET | `/cleaning/customers/{id}` | Read a customer | Customer, PlatformAdmin |
| POST | `/cleaning/customers/{id}/credit-adjustments` | Grant or revoke store credit | PlatformAdmin |
| POST | `/cleaning/addresses` | Create a service address | Customer |
| GET | `/cleaning/addresses/{id}` | Read an address | Customer, PlatformAdmin |
| GET | `/cleaning/addresses` | List addresses | Customer, PlatformAdmin |
| POST | `/cleaning/addresses/{id}/archive` | Soft-delete an address | Customer |
| POST | `/cleaning/cleaners` | Register a cleaner applicant | Anonymous |
| GET | `/cleaning/cleaners/{id}` | Read a cleaner | Cleaner, PlatformAdmin, Customer |
| GET | `/cleaning/cleaners` | List cleaners | PlatformAdmin, Customer |
| POST | `/cleaning/cleaners/{id}/background-checks` | Open a background check | PlatformAdmin |
| GET | `/cleaning/cleaners/{id}/background-checks` | List a cleaner's background checks | PlatformAdmin |
| GET | `/cleaning/background-checks/{id}` | Read a background check | PlatformAdmin |
| POST | `/cleaning/background-checks/{id}/adjudicate` | Adjudicate a background check | PlatformAdmin |
| POST | `/cleaning/cleaners/{id}/activate` | Activate or reinstate a cleaner | PlatformAdmin |
| POST | `/cleaning/cleaners/{id}/suspend` | Suspend an active cleaner | PlatformAdmin |
| POST | `/cleaning/pricing-plans` | Create a rate card | PlatformAdmin |
| GET | `/cleaning/pricing-plans/{id}` | Read a pricing plan | PlatformAdmin, Customer |
| POST | `/cleaning/pricing-plans/{id}/activate` | Activate a pricing plan | PlatformAdmin |
| POST | `/cleaning/preferred-pros` | Favorite a cleaner | Customer |
| GET | `/cleaning/preferred-pros/{id}` | Read a preferred-pro association | Customer, PlatformAdmin |
| GET | `/cleaning/preferred-pros` | List preferred pros | Customer, PlatformAdmin |
| POST | `/cleaning/booking-series` | Create a recurring series | Customer |
| GET | `/cleaning/booking-series/{id}` | Read a series | Customer, PlatformAdmin |
| GET | `/cleaning/booking-series` | List series | Customer, PlatformAdmin |
| POST | `/cleaning/booking-series/{id}/generate` | Generate the next occurrence | PlatformAdmin |
| POST | `/cleaning/booking-series/{id}/pause` | Pause generation | Customer |
| POST | `/cleaning/booking-series/{id}/resume` | Resume generation | Customer |
| POST | `/cleaning/booking-series/{id}/cancel` | Cancel a series | Customer |
| POST | `/cleaning/bookings` | Create a one-time booking | Customer |
| GET | `/cleaning/bookings/{id}` | Read a booking | Customer, Cleaner, PlatformAdmin |
| GET | `/cleaning/bookings` | List bookings | Customer, Cleaner, PlatformAdmin |
| POST | `/cleaning/bookings/{id}/reschedule` | Reschedule a booking | Customer |
| POST | `/cleaning/bookings/{id}/cancel` | Cancel a booking | Customer |
| POST | `/cleaning/bookings/{id}/complete` | Mark a visit complete | Cleaner |
| POST | `/cleaning/bookings/{id}/request-reclean` | Request a guarantee re-clean | Customer |
| POST | `/cleaning/bookings/{id}/schedule-reclean` | Schedule the free re-clean | PlatformAdmin |
| POST | `/cleaning/tips` | Tip a cleaner | Customer |
| GET | `/cleaning/tips/{id}` | Read a tip | Customer, Cleaner, PlatformAdmin |
| GET | `/cleaning/tips` | List tips | Customer, Cleaner, PlatformAdmin |
| GET | `/cleaning/cleaner-payouts/{id}` | Read a payout | Cleaner, PlatformAdmin |
| GET | `/cleaning/cleaner-payouts` | List payouts | Cleaner, PlatformAdmin |
| GET | `/cleaning/ledger-entries/{id}` | Read a ledger entry | Customer, PlatformAdmin |
| GET | `/cleaning/ledger-entries` | List ledger entries | Customer, PlatformAdmin |
| POST | `/cleaning/_clock/set_current_utc` | Set the server clock | PlatformAdmin |
| POST | `/cleaning/_loyalty/set_count` | Seed a customer's lifetime count | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLEANER_NOT_CLEARED` | 409 |
| `ERR_RECLEAN_NOT_ELIGIBLE` | 409 |
| `ERR_RECLEAN_WINDOW_CLOSED` | 409 |
| `ERR_ADDON_NOT_ALLOWED` | 422 |
| `ERR_ADDRESS_ARCHIVED` | 409 |
| `ERR_NO_CLEANER_AVAILABLE` | 409 |
| `ERR_CLEANER_DOUBLE_BOOKED` | 409 |
| `ERR_ADDRESS_DOUBLE_BOOKED` | 409 |
| `ERR_TIP_NOT_ALLOWED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |

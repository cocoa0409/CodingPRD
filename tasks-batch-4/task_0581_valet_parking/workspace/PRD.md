# Valet Parking Operations API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Valet & Parking Operations API, a back-office platform operated by a valet vendor on behalf of the venues it serves. A single deployment coordinates the full ground game of event parking: laying out venues and their timed events, reserving drop-off and pickup lanes, provisioning lots (including overflow relationships), staffing attendants across shifts, issuing tickets as vehicles are received, running the retrieval floor, settling money at checkout, adjudicating damage incidents, and finally reconciling the cash drawer against the revenue the system expected to collect.

Three operational concerns dominate the design and recur throughout this specification. First, **finite lot capacity**: spaces are a scarce resource competed for at check-in, and the platform must never let two vehicles claim the same last space, which motivates an optimistic-concurrency guard on every lot. Second, **dual-variant money**: a ticket carries both a forward-looking quoted fee computed when the car arrives and a chronological final fee computed when it leaves, and a separate tip pool is split among shifts when an event closes. Third, **ledger reconciliation**: at the end of an event a cashier counts the drawer and the system computes the variance between what was declared and what the settled tickets, net of adjudicated liabilities, should have produced. Every endpoint in this API is mounted under the `/valet` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `Attendant`, `Cashier`, and `Supervisor`. When an authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The three roles map to identity as follows. When `X-User-Role` is `Attendant`, `X-User-ID` is the `id` of the acting `Attendant`; ownership checks on any resource that references an `Attendant` compare that resource's attendant foreign key to `X-User-ID`. Concretely, when an attendant records tips into a shift, the system requires that `X-User-ID` equal the `attendant_id` of that shift; a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`. When `X-User-Role` is `Cashier`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. When `X-User-Role` is `Supervisor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

Broadly, an `Attendant` runs the physical floor (check-in, the retrieval flow, recording tips on their own shift) and may file damage claims. A `Cashier` handles money (checkout, validation grants, reversals) and may also file damage claims. A `Supervisor` configures venues, events, lots, lanes, attendants, and shifts; drives every lifecycle transition on those configuration entities; adjudicates damage claims; and runs reconciliation. All three roles may perform any GET read.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every resource in this system — venues, events, lots, lane assignments, attendants, shifts, tickets, retrieval requests, validation grants, damage claims, and reconciliation reports — carries a standard system-managed set of fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation; it is the anchor for optimistic concurrency described in §2.6. Because a computed field changing (for example a lot's occupancy, or an attendant's running liability) is itself a mutation, such a change refreshes `updated_at` and increments `version` on the affected resource.

When a request targets a resource by an identifier in its path, or references another resource by a foreign key in its body, the referenced resources are validated for existence from left to right. The first identifier that does not resolve to an existing resource halts processing and yields the corresponding not-found error — `ERR_VENUE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ATTENDANT_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_RETRIEVAL_NOT_FOUND`, `ERR_VALIDATION_GRANT_NOT_FOUND`, `ERR_DAMAGE_CLAIM_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, or `ERR_LANE_ASSIGNMENT_NOT_FOUND` — before any business rule is evaluated. Independently, a request whose body is missing a required field, carries a value of the wrong type, or supplies an out-of-domain enum value is rejected with `ERR_VALIDATION`.

### 2.5. Monetary Precision and Rounding

All monetary amounts in this system are integer cents; there are no fractional-cent values anywhere in storage or in responses. Each venue records the ISO `currency` code that labels its monetary amounts, defaulting to `USD`. Where a calculation divides — the per-hour metering that rounds partial hours up, the percent-discount step of net-charge computation, and the per-share tip split — the specific rounding rule is stated with that calculation in §3, but the governing convention is that hour counts are rounded up to the next whole hour, percentage discounts are rounded half up to the nearest cent, and tip shares are floored with the leftover remainder distributed cent by cent. A variance figure at reconciliation may be negative (a drawer shortage) or positive (an overage).

### 2.6. Optimistic Concurrency on Lot Check-In

Checking a vehicle in claims a physical space against a lot, and the platform must prevent two attendants from both believing they took the last free space. To that end, the check-in request must carry `expected_lot_version`, a non-optional field holding the client's last observed `version` of the primary `Lot` it is checking into. If that value does not match the primary lot's current `version` at the moment the server processes the check-in — meaning another check-in has advanced the lot's version since the client last read it — the create is rejected with `ERR_STALE_LOT_VERSION` and HTTP 412, so the writer cannot claim capacity it has not actually observed. A successful check-in increments the primary lot's `version` by one; this holds even when the vehicle spills into an overflow lot, because the space claim is evaluated and version-guarded against the primary lot. Check-in is the only endpoint that takes a version field; no other endpoint accepts one.

### 2.7. Validation Ordering

When several checks apply to the same request, they are evaluated in a fixed priority order so that the most fundamental failure always surfaces first. The order is: (1) authentication of the `X-User-ID` / `X-User-Role` headers, failing with `ERR_UNAUTHENTICATED`; (2) role authorization per §2.1, failing with `ERR_UNAUTHORIZED`; (3) existence of every path and foreign-key reference, left to right, failing with the appropriate not-found error; (4) ownership, where an `Attendant` acting on a shift they do not own fails with `ERR_FORBIDDEN_OWNERSHIP`; (5) the target resource being in a state that permits the requested transition, failing with `ERR_INVALID_STATE` or one of its specialized forms; (6) well-formedness of supplied time windows and timestamps, failing with `ERR_INVALID_TIME_WINDOW`; (7) the check-in timestamp falling inside the event window, failing with `ERR_CHECKIN_OUTSIDE_EVENT_WINDOW`; (8) the no-open-damage-claim safety gate at checkout, failing with `ERR_OPEN_DAMAGE_CLAIM`; (9) cross-entity state preconditions, failing with `ERR_TICKET_NOT_PARKED` or `ERR_ATTENDANT_SHIFT_INACTIVE`; (10) uniqueness and overlap constraints, failing with `ERR_KEY_TAG_IN_USE`, `ERR_LANE_WINDOW_CONFLICT`, or `ERR_SHIFT_OVERLAP`; (11) lot capacity, failing with `ERR_LOT_AT_CAPACITY`; and finally (12) the optimistic-concurrency guard of §2.6, failing with `ERR_STALE_LOT_VERSION`. Where a single endpoint is subject to multiple of these — check-in most notably, which passes through existence, event-active state, window bounds, key-tag uniqueness, capacity, and concurrency — the earlier-numbered check is decided before the later one.

The specialized state errors named in step (5) are `ERR_EVENT_NOT_ACTIVE`, `ERR_TICKET_NOT_PARKED`, `ERR_CLAIM_NOT_OPEN`, `ERR_CLAIM_NOT_APPROVED`, `ERR_RETRIEVAL_BAD_STATE`, `ERR_SHIFT_NOT_ACTIVE`, `ERR_EVENT_NOT_CLOSABLE`, and `ERR_REPORT_ALREADY_FINALIZED`; the generic `ERR_INVALID_STATE` covers any transition attempted from an incompatible state that has no more specific code. The precise trigger for each is given alongside the workflow it guards in §3.

### 2.8. Derived Fields, Cascades, and Parallel Ticket State

Several fields are never written directly by a client but are reconciled by the system as a byproduct of other operations, and each such reconciliation is an atomic part of the triggering request — there is no eventual consistency, and all cascades complete before the response is returned. A lot's `occupied_count` is kept equal to the number of that lot's tickets whose `park_status` is `PARKED` or `RETRIEVED`; it rises by one at check-in and falls by one at checkout and is never negative. A lot's `overflow_active` flag is true while at least one ticket that spilled from that primary lot still occupies its overflow lot. An attendant's `total_liability_cents` is the running sum of the approved damage liabilities charged back to them. A shift's `allocated_tip_cents` is its share of the tip pool, assigned when the event closes, and its `liability_holdback_cents` is the amount withheld from that shift on account of disputed tickets its attendant handled; both begin at zero.

A `Ticket` is unusual in carrying two independent state axes. The `park_status` axis (`PARKED`, `RETRIEVED`, `CLOSED`) tracks physical custody of the vehicle, while the `settlement_status` axis (`UNSETTLED`, `SETTLED`, `DISPUTED`) tracks the money. The two move independently: a ticket that has been physically closed can still be moved to `DISPUTED` by a later damage-claim approval, and conversely a ticket can be disputed while still `PARKED`. Neither axis constrains the other except where a specific rule in §3 says so.

## 3. Business Logic & Workflows

### 3.1. Venues, Events, and the Event Lifecycle

The root configuration entity is the **Venue**, created by a `Supervisor` with a display `name`, a street `address`, and optionally a `currency` code (defaulting to `USD`). Within a venue a `Supervisor` schedules an **Event**, supplying the owning venue through the `venue_id` reference, a `name`, and the operating window as `window_start` (inclusive) and `window_end` (exclusive), where the end must be strictly after the start; a window whose end is at or before its start is rejected with `ERR_INVALID_TIME_WINDOW`. An event embeds its rate card at creation time, all fields optional with defaults: `free_grace_minutes` (default 15), `hourly_rate_cents` (default 800), `daily_max_cents` (default 2500), `event_surcharge_cents` (default 500), `overflow_surcharge_cents` (default 700), and `tip_split_mode` (default `EQUAL`, the alternative being `WEIGHTED`). An event's `status` begins at `SCHEDULED`. Events may be listed and filtered by `venue_id` and by `status`.

A `Supervisor` moves an event through its lifecycle. Activation advances the event from `SCHEDULED` to `ACTIVE`, which opens it for check-ins; activation attempted on an event not in `SCHEDULED` is rejected with `ERR_INVALID_STATE`. Closing advances the event from `ACTIVE` to `CLOSED`. Closing has two preconditions: the event must currently be `ACTIVE`, and no ticket of the event may still be physically on the floor — that is, no ticket may have `park_status` of `PARKED` or `RETRIEVED`. If either precondition fails, the close is rejected with `ERR_EVENT_NOT_CLOSABLE`. Closing is also the trigger for tip-pool distribution, described in §3.4, and once closed an event accepts no further check-ins. `CLOSED` is terminal.

### 3.2. Lots, Capacity, and Overflow

A **Lot** is created by a `Supervisor` under a venue via `venue_id`, with a `name` and a `capacity` that must be at least 1. A lot may name another lot as its overflow through `overflow_lot_id` (null means the lot has no overflow), and the `is_overflow` flag (default false) marks a lot that exists only to receive spillover. Two computed fields track live occupancy: `occupied_count`, reconciled as described in §2.8, and `overflow_active`. Lots may be listed and filtered by `venue_id` and by `overflow_lot_id` (to find the children spilling into a given parent).

Capacity is enforced at check-in. A lot has room when its `occupied_count` is strictly less than its `capacity`. When an attendant checks a vehicle into a primary lot that is full, the system consults that lot's `overflow_lot_id`: if an overflow lot is configured, the vehicle is placed there instead, the ticket's `lot_id` is set to the overflow lot, the ticket's `in_overflow` flag is set to true, and the primary lot's `overflow_active` is set to true. If the primary lot is full and no overflow lot is configured, the check-in is rejected with `ERR_LOT_AT_CAPACITY`. The overflow relationship reverses at checkout, as described in §3.7.

### 3.3. Lane Assignments

Drop-off and pickup lanes are a shared physical resource reserved per event. A `Supervisor` reserves a lane by creating a **LaneAssignment** with a `venue_id`, an `event_id`, a `lane_code` (the physical lane identifier such as "A1", unique per venue as a physical resource), and a reservation window of `window_start` (inclusive) and `window_end` (exclusive), the end strictly after the start or else `ERR_INVALID_TIME_WINDOW`. Two reservations of the same venue and `lane_code` may not overlap in time; overlap is judged on half-open intervals, so a reservation ending exactly when another begins does not conflict, while any true overlap is rejected with `ERR_LANE_WINDOW_CONFLICT`. Lane assignments may be listed and filtered by `venue_id` and `event_id`.

### 3.4. Attendants, Shifts, and the Tip Pool

An **Attendant** is created by a `Supervisor` under a venue via `venue_id` with a `name`. An attendant's `status` starts `ACTIVE` and its `total_liability_cents` starts at 0; both are system-maintained, the status flipping to `INACTIVE` only through the liability mechanism of §3.8. Attendants may be listed and filtered by `venue_id`.

A **Shift** places an attendant on the clock. A `Supervisor` schedules one with an `attendant_id`, an optional `event_id` (null for a non-event shift), and a window of `start_at` (inclusive) and `end_at` (exclusive), the end strictly after the start or else `ERR_INVALID_TIME_WINDOW`. A new shift may not overlap another shift of the same attendant, and even when they do not overlap, consecutive shifts of one attendant must be separated by at least a 30-minute rest gap; a shift that overlaps another of the same attendant, or that leaves less than 30 minutes of separation, is rejected with `ERR_SHIFT_OVERLAP`. A shift's `status` starts `SCHEDULED`; a `Supervisor` starts it (advancing `SCHEDULED` to `ACTIVE`, putting the attendant on the clock and eligible for retrieval assignment) and later closes it (advancing `ACTIVE` to `CLOSED`). A start or close attempted from an incompatible shift state is rejected with `ERR_SHIFT_NOT_ACTIVE`. Shifts also carry `declared_tips_cents` (default 0), `allocated_tip_cents` (default 0), and `liability_holdback_cents` (default 0), and may be listed and filtered by `attendant_id` and `event_id`.

Recording tips is the one attendant-owned write. An `Attendant` reports the cash they collected into their own shift by supplying `declared_tips_cents`, which the system stores on the shift; because this is owner-only, the acting `X-User-ID` must equal the shift's `attendant_id`, and any other attendant is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

The tip pool is distributed as a side effect when an event closes (§3.1). The system gathers every shift whose `event_id` is the closing event — regardless of that shift's own status — ordered by `created_at` ascending, and forms the pool as the sum of their `declared_tips_cents`. Under the `EQUAL` split mode, each of the n shifts receives the pool divided by n and rounded down to a whole cent. Under the `WEIGHTED` split mode, each shift's provisional share is the pool multiplied by that shift's hours and divided by the total hours across all the shifts, then rounded down to a whole cent, where a shift's hours is its duration from `start_at` to `end_at` expressed in hours (seconds elapsed divided by 3600 seconds per hour). After the provisional shares are computed, the remainder — the pool minus the sum of the floored shares, which is never negative — is distributed one cent at a time to the shifts in `created_at` ascending order, so the earliest-created shifts each receive one extra cent until the remainder is exhausted and the shares sum exactly to the pool. The resulting figure is written to each shift's `allocated_tip_cents`.

### 3.5. Vehicle Check-In and the Quoted Fee

An `Attendant` receives a vehicle by checking it in, which mints a **Ticket**. The check-in payload identifies the event via `event_id`, the intended primary lot via `lot_id`, and the receiving attendant via `attendant_id`, and records the vehicle's `license_plate`, a key-cabinet `key_tag`, the arrival timestamp `checkin_at`, and the customer's `estimated_departure_at`; it also carries `expected_lot_version` as the optimistic-concurrency guard described in §2.6. Check-in is permitted only while the event is `ACTIVE`; a check-in against an event in any other status is rejected with `ERR_EVENT_NOT_ACTIVE`. The `checkin_at` must fall inside the event's operating window — at or after `window_start` and strictly before `window_end` — or the check-in is rejected with `ERR_CHECKIN_OUTSIDE_EVENT_WINDOW`. The `key_tag` must be unique among the non-`CLOSED` tickets of the same event; reusing a tag still held by an open ticket is rejected with `ERR_KEY_TAG_IN_USE`. Capacity and overflow placement (§3.2) then decide the actual `lot_id` and set `in_overflow`, and the assigned lot's `occupied_count` rises by one.

On a successful check-in the ticket's `park_status` is initialized `PARKED` and its `settlement_status` is initialized `UNSETTLED`, its `checkout_at`, `final_fee_cents`, and `net_charge_cents` are left null, and the system computes the forward-looking **quoted fee** into `quoted_fee_cents`. The quoted fee is computed from the estimated stay, that is, the duration in minutes from `checkin_at` to `estimated_departure_at`. If that duration is at or below the event's `free_grace_minutes`, the fee is 0. Otherwise the number of billable hours is the duration in minutes divided by 60 and rounded up to the next whole hour; the metered component is the lesser of those hours multiplied by `hourly_rate_cents` and the event's `daily_max_cents` cap; the event's flat `event_surcharge_cents` is then added on top of the capped metered component; and finally, if the ticket is in overflow, the event's `overflow_surcharge_cents` is added as well. The result is an integer number of cents. Tickets may be fetched by id and listed with filters on `event_id`, `lot_id`, `attendant_id`, `park_status`, and `settlement_status`.

### 3.6. The Retrieval Floor

When a customer asks for their car, an `Attendant` opens a **RetrievalRequest** against the ticket via `ticket_id`, recording `requested_at`. A retrieval may only be opened for a ticket that is currently `PARKED`; a request against a ticket in any other `park_status` is rejected with `ERR_TICKET_NOT_PARKED`. The request's `status` begins `REQUESTED`, its `attendant_id` is null until a runner is assigned, and `ready_at` is null until the car is staged. Retrieval requests may be listed and filtered by `ticket_id`, `attendant_id`, and `status`.

The request then walks a small state machine, each hop driven by an `Attendant`, and any hop attempted from the wrong current status is rejected with `ERR_RETRIEVAL_BAD_STATE`. Assigning a runner advances `REQUESTED` to `ASSIGNED` and sets the request's `attendant_id` from the supplied `attendant_id`; the named runner must currently be on an `ACTIVE` shift, and if they are not the assignment is rejected with `ERR_ATTENDANT_SHIFT_INACTIVE`. Staging advances `ASSIGNED` to `STAGING` as the runner goes to fetch the vehicle. Marking ready advances `STAGING` to `READY`, records `ready_at`, and — as a cross-entity effect — flips the underlying ticket's `park_status` from `PARKED` to `RETRIEVED`; this transition additionally requires that the ticket still be `PARKED` at the moment it is marked ready, and a ticket no longer parked is rejected with `ERR_TICKET_NOT_PARKED`.

Reverting is a cyclic correction whose meaning depends on where the request currently sits. From `READY` it goes back to `STAGING` (for a delayed customer or a wrongly pulled car), which reverses the earlier cross-entity effect by setting the ticket's `park_status` back to `PARKED` and clearing `ready_at`. From `STAGING` it goes back to `ASSIGNED`, handing the runner off to await reassignment. From `REQUESTED` it goes to `CANCELLED`, abandoning a request before any assignment. Completing advances `READY` to `COMPLETED` as the vehicle is handed to the customer. `COMPLETED` and `CANCELLED` are terminal.

### 3.7. Checkout, Validation Grants, and the Net Charge

A `Cashier` closes a ticket at checkout by supplying `checkout_at`. Checkout is permitted from a `park_status` of either `PARKED` or `RETRIEVED`; from any other state it is rejected with `ERR_INVALID_STATE`. The `checkout_at` must be at or after the ticket's `checkin_at`, or the request is rejected with `ERR_INVALID_TIME_WINDOW`. As a safety gate, a ticket that has any damage claim still in `OPEN` status cannot be checked out; the attempt is rejected with `ERR_OPEN_DAMAGE_CLAIM`. On success the checkout advances `park_status` to `CLOSED` and advances the money axis by setting `settlement_status` to `SETTLED`, stamps `checkout_at`, decrements the `occupied_count` of the ticket's `lot_id` by one, and — when the ticket was in overflow and that overflow lot's `occupied_count` has fallen to zero — clears the primary lot's `overflow_active` back to false.

Checkout computes the **final fee** into `final_fee_cents`. The final fee uses exactly the same tiered formula as the quoted fee in §3.5 — free below the grace threshold, otherwise the metered hours (rounded up) times the hourly rate, capped by the daily maximum, plus the flat event surcharge, plus the overflow surcharge when the ticket is in overflow — but its duration is the chronological actual stay, the minutes from `checkin_at` to the supplied `checkout_at`, so it diverges from the quoted figure whenever the actual departure differs from the estimate. Checkout then computes the **net charge** into `net_charge_cents` by applying the ticket's validation grants to the final fee.

The net charge is computed by starting from `final_fee_cents` and folding in each of the ticket's grants whose `status` is `APPLIED`, taken in `created_at` ascending order; reversed grants are excluded. A `FULL_COMP` grant sets the running amount to 0. A `FLAT` grant subtracts its `value` in cents from the running amount, flooring the result at 0 so it never goes negative. A `PERCENT` grant multiplies the running amount by one hundred minus its whole-percent `value`, divides by one hundred, and rounds the result half up to the nearest cent. The order of application matters, so grants are always evaluated oldest first.

A `Cashier` applies a validation discount by creating a **ValidationGrant** against the ticket, choosing a `grant_type` of `PERCENT`, `FLAT`, or `FULL_COMP` and supplying `value` (a whole percent from 0 to 100 for `PERCENT`, a cent amount for `FLAT`, and ignored for `FULL_COMP`, defaulting to 0). The grant's `status` starts `APPLIED`, and creating it immediately recomputes the ticket's `net_charge_cents` by the rule above. A `Cashier` may reverse a grant, which moves its `status` from `APPLIED` to `REVERSED` and again recomputes the ticket's `net_charge_cents` (now excluding the reversed grant). Reversing a grant already in `REVERSED` is rejected with `ERR_GRANT_ALREADY_REVERSED`. Neither applying nor reversing a grant is allowed once the ticket's `settlement_status` is `DISPUTED`; such an attempt is rejected with `ERR_VALIDATION_NOT_APPLICABLE`. Validation grants may be fetched by id and listed with a `ticket_id` filter.

### 3.8. Damage Claims and the Liability Cascade

Either an `Attendant` or a `Cashier` may file a **DamageClaim** against a ticket via `ticket_id`, with a free-text `description` and a `claimed_amount_cents`. The claim may name the responsible attendant through `attendant_id`; when that is omitted it defaults to the ticket's own `attendant_id`. The claim's `status` starts `OPEN`, and `approved_liability_cents` is null until the claim is approved. Claims may be listed and filtered by `ticket_id`, `attendant_id`, and `status`. A `Supervisor` adjudicates. Approving and denying are both permitted only from `OPEN`; either attempted on a claim in any other status is rejected with `ERR_CLAIM_NOT_OPEN`.

Denial advances `OPEN` to `DENIED` and has no ledger or ticket effect whatsoever. Approval advances `OPEN` to `APPROVED` and runs a three-hop cascade that must complete atomically within the request. First, the claim's `approved_liability_cents` is fixed: to the optional `approved_liability_cents` override if the supervisor supplied one, otherwise to the claim's `claimed_amount_cents`. Hop one: the linked ticket's `settlement_status` is moved to `DISPUTED` and its `net_charge_cents` is set to 0 — and because the two ticket axes are independent (§2.8), this applies whether the ticket was `UNSETTLED` or already `SETTLED`, and regardless of its `park_status`. Hop two: the charged attendant's `total_liability_cents` is increased by the approved liability amount. Hop three: if that attendant's `total_liability_cents` has thereby reached or exceeded 10,000 cents, the attendant's `status` is flipped to `INACTIVE`, and as a further consequence every shift of that attendant currently in `ACTIVE` status is closed to `CLOSED`. A `Supervisor` may later settle an approved claim, advancing `APPROVED` to `SETTLED` to mark it paid out; a settle attempted on a claim not in `APPROVED` is rejected with `ERR_CLAIM_NOT_APPROVED`. `DENIED` and `SETTLED` are terminal.

### 3.9. Revenue Reconciliation

After an event has closed, a `Supervisor` opens a **ReconciliationReport** against it via `event_id`; the report may only be created for an event whose `status` is `CLOSED`. The report's `status` starts `DRAFT`. While in `DRAFT`, three figures are computed over the event's tickets and recomputed as the draft is refreshed. The `expected_revenue_cents` is the sum of `net_charge_cents` across the event's tickets whose `settlement_status` is `SETTLED`. The `overflow_surcharge_total_cents` is the event's `overflow_surcharge_cents` summed once for each of the event's `SETTLED` tickets that were `in_overflow`. The `liability_adjustment_cents` is the sum of `approved_liability_cents` across all damage claims on the event's tickets whose `status` is either `APPROVED` or `SETTLED`. The `declared_cash_cents` and `variance_cents` remain null until finalization. Reports may be fetched and listed with an `event_id` filter, and are readable by a `Supervisor` or a `Cashier`.

Finalization is the closing act. A `Supervisor` finalizes a `DRAFT` report by supplying the counted drawer total as `declared_cash_cents`, which advances the report's `status` from `DRAFT` to `FINALIZED` and fixes the `variance_cents` as the declared cash minus the difference of expected revenue and the liability adjustment — that is, `declared_cash_cents` minus the quantity (`expected_revenue_cents` minus `liability_adjustment_cents`). The variance may come out negative for a shortage or positive for an overage. A finalize attempted on a report already in `FINALIZED` is rejected with `ERR_REPORT_ALREADY_FINALIZED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch, list, or modify an existing resource (including lifecycle transitions) return `200 OK`. All endpoints are mounted under `/valet`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/valet/venues` | Create a venue | Supervisor |
| GET | `/valet/venues/{id}` | Fetch a venue | Supervisor, Cashier, Attendant |
| POST | `/valet/events` | Create an event with embedded rate card | Supervisor |
| GET | `/valet/events/{id}` | Fetch an event | Supervisor, Cashier, Attendant |
| GET | `/valet/events` | List events | Supervisor, Cashier, Attendant |
| POST | `/valet/events/{id}/activate` | Activate an event (SCHEDULED → ACTIVE) | Supervisor |
| POST | `/valet/events/{id}/close` | Close an event and distribute the tip pool | Supervisor |
| POST | `/valet/lots` | Create a parking lot | Supervisor |
| GET | `/valet/lots/{id}` | Fetch a lot | Supervisor, Cashier, Attendant |
| GET | `/valet/lots` | List lots | Supervisor, Cashier, Attendant |
| POST | `/valet/lane-assignments` | Reserve a lane for an event window | Supervisor |
| GET | `/valet/lane-assignments/{id}` | Fetch a lane assignment | Supervisor, Cashier, Attendant |
| GET | `/valet/lane-assignments` | List lane assignments | Supervisor, Cashier, Attendant |
| POST | `/valet/attendants` | Create an attendant | Supervisor |
| GET | `/valet/attendants/{id}` | Fetch an attendant | Supervisor, Cashier, Attendant |
| GET | `/valet/attendants` | List attendants | Supervisor, Cashier, Attendant |
| POST | `/valet/shifts` | Schedule a shift | Supervisor |
| GET | `/valet/shifts/{id}` | Fetch a shift | Supervisor, Cashier, Attendant |
| GET | `/valet/shifts` | List shifts | Supervisor, Cashier, Attendant |
| POST | `/valet/shifts/{id}/start` | Start a shift (SCHEDULED → ACTIVE) | Supervisor |
| POST | `/valet/shifts/{id}/close` | Close a shift (ACTIVE → CLOSED) | Supervisor |
| POST | `/valet/shifts/{id}/tips` | Record tips into own shift | Attendant |
| POST | `/valet/tickets` | Check a vehicle in | Attendant |
| GET | `/valet/tickets/{id}` | Fetch a ticket | Supervisor, Cashier, Attendant |
| GET | `/valet/tickets` | List tickets | Supervisor, Cashier, Attendant |
| POST | `/valet/tickets/{id}/checkout` | Check a vehicle out and settle | Cashier |
| POST | `/valet/tickets/{id}/validations` | Apply a validation grant | Cashier |
| GET | `/valet/validation-grants/{id}` | Fetch a validation grant | Supervisor, Cashier, Attendant |
| GET | `/valet/validation-grants` | List validation grants | Supervisor, Cashier, Attendant |
| POST | `/valet/validation-grants/{id}/reverse` | Reverse an applied grant | Cashier |
| POST | `/valet/retrieval-requests` | Open a retrieval request | Attendant |
| GET | `/valet/retrieval-requests/{id}` | Fetch a retrieval request | Supervisor, Cashier, Attendant |
| GET | `/valet/retrieval-requests` | List retrieval requests | Supervisor, Cashier, Attendant |
| POST | `/valet/retrieval-requests/{id}/assign` | Assign a runner (REQUESTED → ASSIGNED) | Attendant |
| POST | `/valet/retrieval-requests/{id}/stage` | Stage the vehicle (ASSIGNED → STAGING) | Attendant |
| POST | `/valet/retrieval-requests/{id}/ready` | Mark ready (STAGING → READY) | Attendant |
| POST | `/valet/retrieval-requests/{id}/revert` | Cyclic revert | Attendant |
| POST | `/valet/retrieval-requests/{id}/complete` | Complete (READY → COMPLETED) | Attendant |
| POST | `/valet/damage-claims` | File a damage claim | Attendant, Cashier |
| GET | `/valet/damage-claims/{id}` | Fetch a damage claim | Supervisor, Cashier, Attendant |
| GET | `/valet/damage-claims` | List damage claims | Supervisor, Cashier, Attendant |
| POST | `/valet/damage-claims/{id}/approve` | Approve a claim and run the liability cascade | Supervisor |
| POST | `/valet/damage-claims/{id}/deny` | Deny a claim | Supervisor |
| POST | `/valet/damage-claims/{id}/settle` | Settle an approved claim | Supervisor |
| POST | `/valet/reconciliation-reports` | Create a DRAFT reconciliation report | Supervisor |
| GET | `/valet/reconciliation-reports/{id}` | Fetch a reconciliation report | Supervisor, Cashier |
| GET | `/valet/reconciliation-reports` | List reconciliation reports | Supervisor, Cashier |
| POST | `/valet/reconciliation-reports/{id}/finalize` | Finalize and fix the variance | Supervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_ATTENDANT_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_RETRIEVAL_NOT_FOUND` | 404 |
| `ERR_VALIDATION_GRANT_NOT_FOUND` | 404 |
| `ERR_DAMAGE_CLAIM_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_LANE_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EVENT_NOT_ACTIVE` | 409 |
| `ERR_EVENT_NOT_CLOSABLE` | 409 |
| `ERR_TICKET_NOT_PARKED` | 409 |
| `ERR_CLAIM_NOT_OPEN` | 409 |
| `ERR_CLAIM_NOT_APPROVED` | 409 |
| `ERR_RETRIEVAL_BAD_STATE` | 409 |
| `ERR_SHIFT_NOT_ACTIVE` | 409 |
| `ERR_REPORT_ALREADY_FINALIZED` | 409 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_CHECKIN_OUTSIDE_EVENT_WINDOW` | 422 |
| `ERR_OPEN_DAMAGE_CLAIM` | 409 |
| `ERR_ATTENDANT_SHIFT_INACTIVE` | 409 |
| `ERR_LANE_WINDOW_CONFLICT` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_KEY_TAG_IN_USE` | 409 |
| `ERR_LOT_AT_CAPACITY` | 409 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_VALIDATION_NOT_APPLICABLE` | 409 |
| `ERR_GRANT_ALREADY_REVERSED` | 409 |

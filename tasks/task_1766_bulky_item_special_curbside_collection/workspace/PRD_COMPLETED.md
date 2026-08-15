# Bulky Curbside Collection API — Product Requirements Document

## 1. Introduction

Municipal solid-waste departments field a constant stream of resident requests that fall outside the weekly cart service: a broken sofa, a refrigerator awaiting refrigerant recovery, a pile of tires. Each of these set-outs consumes scarce route capacity, draws on a per-household annual allowance of free items, may carry regulatory handling fees, and — when abandoned at the curb without a booking — may constitute illegal dumping that triggers fines and account suspension. This document specifies the Bulky Curbside Collection API, the system of record through which a municipal department manages that entire lifecycle.

The API serves four distinct operational constituencies. Residents open requests, declare items, book appointments against zone-specific route days, and settle fees. Drivers execute dispatched routes, recording completions, refusals, and missed stops from the curb. Inspectors investigate reported set-outs to distinguish authorized appointments from illegal dumping, and hold the exclusive power to reinstate suspended households. Dispatchers administer the service territory: households, route days, seasonal amnesty windows, fee waivers, and the logical clock the whole system reads. Segregation of duties is deliberate — the officer who determines a fine is never the administrator who waives it, and no resident can lift their own suspension.

Underneath the workflow sits a quota-allocation engine (each household receives a small annual free-item allowance, consumed in deterministic item order and partially releasable on cancellation), a tiered pricing engine (over-allowance, refrigerant, oversize, and mattress fees composed per item under a municipal surcharge), and a capacity model that tracks every route day's committed load against hard maximums. Amnesty weeks seasonally waive over-allowance fees for requests scheduled into them, without ever waiving the regulatory refrigerant recovery charge.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API call must present two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. The recognized roles are exactly `Resident`, `Driver`, `Inspector`, and `Dispatcher`. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles interpret `X-User-ID` differently, and the distinction is load-bearing for ownership checks:

- When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Household`; ownership checks on any household-scoped resource — a pickup request, its items, its fee assessments, its notifications, its allowance ledger rows — compare the resource's owning `household_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. The single exception is the assessment-settlement action of §3.5: there, a settle attempt by a `Resident` whose `X-User-ID` does not match the assessment's `household_id` is reported under the settlability rule as `ERR_ASSESSMENT_NOT_SETTLABLE`, not `ERR_FORBIDDEN`.
- When `X-User-Role` is `Driver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `Inspector`, `X-User-ID` is likewise an opaque operator identifier; the role's authority flows from the role itself, not from resource ownership.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is again an opaque operator identifier for a municipal operations administrator.

Certain powers are exclusive by design. Only a `Resident` may create, itemize, submit, schedule, or cancel their own pickup requests, and only a `Resident` may settle a fee assessment charged to their own household. Only a `Driver` may complete, refuse, or mark missed a scheduled stop. Only an `Inspector` may determine a dumping report or reinstate a suspended household. Only a `Dispatcher` may register households, create and dispatch or close route days, declare or cancel amnesty windows, waive fees, and advance the logical clock. Filing a dumping report is shared between `Inspector` and `Driver`. Read access is broad: most resources are readable by some combination of roles, with the precise per-endpoint authorization fixed in §4.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, accepts a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1, a `limit` above 100 is treated as 100, and a negative `offset` is treated as 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless a listing states otherwise, results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full filtered result set and `has_more` is true exactly when `offset` plus the number of items actually returned is less than `total_count`.

Several list endpoints also accept domain filters as optional query parameters — the households listing accepts `service_zone` and `status`; the amnesty-window listing accepts `status`; the route-day listing accepts `service_zone`, `route_date`, and `status`; the pickup-request listing accepts `household_id`, `route_day_id`, `status`, and `scheduled_date`; the fee-assessment listing accepts `kind` and `status`; the dumping-report listing accepts `household_id` and `status`. All accept `limit` and `offset`.

### 2.4. The Logical Clock

The entire system reads dates and times from a single server-maintained **logical clock**, never from wall-clock time. At server startup, before any clock call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `Dispatcher` advances it by supplying a `to_iso8601` instant through the clock-setting capability; the response echoes the resulting `current_utc`. The logical clock must never silently fall back to wall-clock time.

Every temporal rule in this document — no scheduling into the past, the cancellation cutoff at midnight at the start of the pickup day, day-of-only dispatch, day-of-service completion/refusal/miss, amnesty-window membership, and the plus-or-minus-one-day authorized set-out window — is evaluated against this logical clock. Calendar dates such as `route_date` and `scheduled_date` are ISO `yyyy-mm-dd` strings interpreted against the logical clock; a date's "midnight instant" means `00:00:00Z` at the start of that date.

Two timestamp families exist side by side. Business instants — `reported_at` on dumping reports, `settled_at` on fee assessments, and the `current_utc` echoed by the clock endpoint — are read from the logical clock and serialize as the clock's exact ISO 8601 instant (no fractional digits when the clock value sits on a whole second). Audit timestamps — `created_at` and `updated_at` on every resource — are stamped from a separate monotonic wall clock that never moves backwards and never reuses a value, so creation order is always recoverable from `created_at`; the logical clock does not govern them.

### 2.5. Common Resource Properties

All primary resources — Households, HouseholdAllowance ledger rows, AmnestyWindows, RouteDays, PickupRequests, PickupItems, FeeAssessments, and DumpingReports — carry a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation, including mutations caused by system cascades rather than direct client writes.

Notifications are the sole exception: a Notification is an immutable emission record carrying only `id` and `created_at`; both `updated_at` and `version` are absent on Notification resources.

### 2.6. Money, Units, and Rounding

All monetary amounts are integer cents — fields named `item_fee_cents`, `provisional_total_cents`, `final_total_cents`, and `amount_cents` never carry fractional values. Where a calculation produces a fraction of a cent (only the per-item municipal surcharge does), the result is rounded **half-up to a whole cent at the per-item level before any summation**: each item's surcharge-inclusive fee is rounded first, and only then are item fees summed into a request total. This per-item-then-sum rounding order is pinned and must not be inverted. Route fullness percentages are likewise rounded half-up, to zero decimal places. Load units, item counts, and capacity figures are exact integers with no rounding at all.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both name their guard field explicitly.

A scheduling request must carry `expected_route_day_version`, equal to the `version` of the target RouteDay as the client last observed it. If the RouteDay's current `version` has advanced since that read — for example because another request was just scheduled onto the route or cancelled off it, legitimately moving `committed_load_units` or `committed_stops` — the schedule attempt is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412), because the client's capacity view is stale.

A cancellation request must carry `expected_request_version`, equal to the `version` of the PickupRequest as the client last observed it. If the request's current `version` has advanced — for example because it was just rescheduled after a refusal, which re-priced the quote and re-froze amnesty status — the cancel attempt is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412), because the fiscal state the client intends to void is no longer the one on record.

Both are non-optional inputs on their respective operations. A guard field that is missing or not an integer fails with `ERR_INVALID_REQUEST` (HTTP 400), raised at the optimistic-concurrency step of the §2.9 ordering; only an integer guard that differs from the current version produces the 412 stale-version error. Endpoints other than these two take no version field.

Independently of optimistic concurrency, the server fully serializes request handling: each request runs to completion before the next begins, so no concurrent caller can observe a half-applied transition or a partially mutated store.

### 2.8. Nested and Reverse-Reachable Retrieval

Requests that address nested resources validate every identifier strictly left-to-right: the pickup-request id in the path first, then any `route_day_id` supplied in the body, then any item ids, with the first non-existent identifier rejected as `ERR_NOT_FOUND` (HTTP 404) before later checks proceed. Existence validation extends to foreign keys in request bodies, not just path segments.

The object graph is also readable in reverse. From a household one can list its allowance ledger rows, its pickup requests, the dumping reports filed against it, and the fee assessments it fiscally owns (including unlinked dumping fines). From a route day one can list the requests scheduled onto it. From a pickup request one can list its items, its fee assessments, its notifications, and any dumping reports linked to it.

### 2.9. Validation Ordering

Every guarded endpoint evaluates checks in a fixed priority order, so that when several problems coexist the same error always surfaces first. The order is: (1) authentication — headers present and role recognized, else `ERR_UNAUTHENTICATED`; (2) authorization — role permitted and, for `Resident` calls on household-scoped resources, `X-User-ID` equals the owning household's id, else `ERR_FORBIDDEN` (on the assessment-settlement endpoint this household-ownership mismatch is instead reported by the settlability rule of priority (13), per §3.5); (3) existence — every path id and body foreign key resolves, else `ERR_NOT_FOUND`; (4) state-machine legality — the resource's current state lists the attempted trigger, else `ERR_INVALID_STATE`; (5) optimistic-concurrency checks on the two guarded writes, else the stale-version error; (6) prohibited-item and preparation scans at submission (the prohibition scan runs first, the preparation-acknowledgement scan second), else `ERR_PROHIBITED_ITEM` or `ERR_PREPARATION_NOT_ACKED`; (7) household standing, else `ERR_HOUSEHOLD_SUSPENDED`; (8) zone consistency, else `ERR_ZONE_MISMATCH`; (9) temporal rules, else `ERR_TEMPORAL_CONFLICT`; (10) the one-scheduled-pickup-per-household-per-date rule, else `ERR_DUPLICATE_PICKUP_DATE`; (11) aggregate route capacity, else `ERR_ROUTE_CAPACITY_EXCEEDED`; (12) dumping-determination and reinstatement consistency, else `ERR_DETERMINATION_INCONSISTENT`; (13) assessment settlability, else `ERR_ASSESSMENT_NOT_SETTLABLE`; and (14) request schema soundness — required fields present, categories drawn from the declared enumeration, `sequence_no` unique per request and at least 1, at least one item present at submission — else `ERR_INVALID_REQUEST`.

Two scoped refinements pin the ordering where the generic list underdetermines it. On the scheduling endpoint, the pickup request's own state gate (priority 4 — the request must be `SUBMITTED` or `REFUSED`, including the `EXCEEDS_DECLARED_ITEMS` bar) is evaluated immediately after the path id resolves, before the body's `route_day_id` foreign key is looked up; the route day's own state gate (`OPEN`, else `ERR_ROUTE_LOCKED`) then runs before the optimistic-concurrency check, per priorities (4) before (5). On the cancellation endpoint, the route-lock gate for a `SCHEDULED` request (`ERR_ROUTE_LOCKED`) likewise runs before the `expected_request_version` check. On completion, the `improper_preparation_item_ids` existence check (priority 3) runs before the stop's state gate (priority 4). Household-ownership checks on reads whose ownership is computable only from a fetched resource resolve that resource first, so a non-existent id yields `ERR_NOT_FOUND` even for a non-owning caller.

## 3. Business Logic & Workflows

### 3.1. Household Accounts, Allowances, and Standing

A `Dispatcher` onboards a service address by registering a **Household** with its `street_address` — which must be a single-family residential address inside the service territory, and which the API validates only as a non-blank string — and its `service_zone`, one of `ZONE_NORTH`, `ZONE_SOUTH`, `ZONE_EAST`, or `ZONE_WEST`. The registration may optionally carry `annual_allowance_items`, the number of items the household may set out free of charge each calendar year; when omitted, the household receives an annual allowance of 4 items, and the value must be a non-negative integer. A missing or blank `street_address`, an unrecognized `service_zone`, or a negative or non-integer `annual_allowance_items` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new household begins life with `status` equal to `ACTIVE` and `version` 1.

Allowance consumption is tracked per household per calendar year in a **HouseholdAllowance** ledger row keyed by `household_id` and `calendar_year`. No ledger row exists until the first scheduling event of that year touches it; the row is then created lazily with `items_consumed`, `items_released`, and `over_allowance_items` all zero. `items_consumed` counts items absorbed into the free allowance by requests whose `scheduled_date` falls in that calendar year and whose status is `SCHEDULED`, `COMPLETED`, or `REFUSED`. `items_released` is a cumulative audit counter of items returned to the pool by cancellations in that year — it never decrements `items_consumed` on its own; the two counters move together only through the release rule described in §3.3. `over_allowance_items` accumulates the fee-bearing items accepted beyond the free allowance. Requests in `DRAFT`, `SUBMITTED`, or `CANCELLED` never count against the ledger.

A household's standing is binary. While `status` is `ACTIVE` the household may use every resident-facing capability. When the household is suspended — the only path to which is a confirmed illegal-dumping determination, described in §3.6 — the system records the cause in `suspension_reason` (set to `ILLEGAL_DUMPING` by the cascade, null while active) and the household loses the ability to consume municipal service: creating a new pickup request, submitting one, or scheduling one are all rejected with `ERR_HOUSEHOLD_SUSPENDED`. The suspension gate is evaluated at the moment of the attempted transition, not eagerly at the moment of suspension. Reinstatement is Inspector-only and is gated on fiscal settlement: every `ILLEGAL_DUMPING_FINE` assessment owned by that household — whether linked to a pickup request or unlinked — must have reached `SETTLED` or `WAIVED` before the reinstatement clears `suspension_reason` and returns the household to `ACTIVE`, bumping its `version`. An attempt to reinstate while any such fine is still `PENDING` fails with `ERR_DETERMINATION_INCONSISTENT`.

### 3.2. Building a Request: Items, Preparation, and Provisional Pricing

A resident begins by creating a **PickupRequest** for their household — the creation payload names the `household_id` — which is born in `DRAFT` with `load_units` 0, `provisional_total_cents` 0, and `version` 1. Against a draft the resident adds **PickupItems** one at a time, declaring for each a `sequence_no` (a 1-based resident-declared ordering within the request, unique across the request's items; it serves as the tie-breaker in allowance consumption after `created_at`), a `category`, an optional `is_oversize` flag defaulting to false, and a `preparation_ack` confirming the resident has read the preparation instructions for that category. Item creation validates each field as it is declared: `sequence_no` must be an integer at least 1 and not already used on the request, `category` must be a member of the declared enumeration, `is_oversize` when present must be a boolean, and `preparation_ack` is required and must be a boolean — any violation fails the add with `ERR_INVALID_REQUEST` (HTTP 400). Adding or removing an item recomputes the request's `load_units` and bumps the request's `version` by 1; items may be added or removed only while the request is in `DRAFT` (any other status fails with `ERR_INVALID_STATE`) — there is no item-removal path on a `REFUSED` request, so a resident who needs to correct a refused set-out must cancel and redraft.

The item `category` is one of `STANDARD_FURNITURE`, `MATTRESS`, `APPLIANCE_NO_REFRIGERANT`, `APPLIANCE_WITH_REFRIGERANT`, `ELECTRONICS`, `TIRES`, or `PROHIBITED`. An item counts as oversize — and its `is_oversize` must be set true — when any dimension exceeds 1.5 metres or its weight exceeds 32 kilograms.

The request's `load_units` are the sum over its items of the category's base load, doubled for oversize items: standard furniture contributes 2 units, a mattress 3, a non-refrigerant appliance 4, a refrigerant appliance 5, electronics 2, and tires 1, each multiplied by 2 when the item is oversize and by 1 otherwise. A `PROHIBITED` item contributes 0 load units. This figure is recomputed on every item change while drafting and re-validated at scheduling.

Submission moves the request from `DRAFT` to `SUBMITTED` (any other source state fails with `ERR_INVALID_STATE`) and is the first gatekeeping moment. The request must contain at least one item, and submission is rejected with `ERR_INVALID_REQUEST` when the item list is empty or any item fails schema rules (unknown category, duplicated or sub-1 `sequence_no`). Per the priority ordering of §2.9, however, that schema check runs last: the safety scans run first, prohibition before preparation — any item whose `category` is `PROHIBITED` causes rejection with `ERR_PROHIBITED_ITEM`, and only after the prohibition scan passes does the preparation scan run: every item must carry `preparation_ack` equal to true, and refrigerant-bearing appliances in particular cannot be submitted without that acknowledgement because refrigerant recovery preparation is a regulatory requirement; any unacknowledged item fails with `ERR_PREPARATION_NOT_ACKED`. The household must also be `ACTIVE` at this point, and the standing check too precedes the empty-item and schema check — a suspended household's submission fails with `ERR_HOUSEHOLD_SUSPENDED` even when the item list is empty.

A successful submission produces the resident's first price signal. The system runs the **provisional variant** of the item-fee quote — a deliberately worst-case, pre-scheduling estimate in which every item is priced as though it were over-allowance and no amnesty applies (at this point `amnesty_applied` is still false and the allowance has not been touched). The quote walks the items in deterministic order — `created_at` ascending, ties broken by `sequence_no` ascending — and for each item composes its fee from up to four components: an over-allowance fee of 2500 cents when the item is not within the free allowance; a refrigerant recovery fee of 4500 cents when the category is `APPLIANCE_WITH_REFRIGERANT`; an oversize fee of 1500 cents when `is_oversize` is true; and a mattress fee of 1200 cents when the category is `MATTRESS`. The item's subtotal is the sum of whichever components apply, and the municipal processing surcharge of 8.5 percent is then applied to that subtotal and rounded half-up to a whole cent for that item; the item's `item_fee_cents` is its subtotal plus its surcharge. The request's `provisional_total_cents` is the sum of the per-item fees. Because the rounding happens per item before summing, two requests with identical components in different groupings can legitimately quote different totals, and implementations must reproduce the pinned order exactly. Submission records this quote on each item and the request, creates a **FeeAssessment** of `kind` `PROVISIONAL_QUOTE` for `amount_cents` equal to the quoted total in `PENDING` status, and bumps the request's `version`. Refrigerant recovery is never discounted or waived at any point in the lifecycle — not even by an amnesty week.

### 3.3. Route Days, Scheduling, and the Allowance Ledger

Dispatchers create supply in the form of **RouteDays**: a `service_zone`, a `route_date` (an ISO calendar date read against the logical clock), an aggregate capacity `max_load_units`, and a stop cap `max_stops`. Creation requires `service_zone` to be a declared zone, `route_date` to be a strict ISO `yyyy-mm-dd` date, and both capacities to be integers — no positivity constraint is imposed — with any violation rejected as `ERR_INVALID_REQUEST` (HTTP 400). A new route day is `OPEN` with `committed_load_units` and `committed_stops` both 0.

Scheduling is the central commitment act, available from either `SUBMITTED` or `REFUSED`, and it folds several rule families into one atomic transition. The resident names the target `route_day_id` and must present `expected_route_day_version` matching the route's current `version`, per the optimistic-concurrency rule in §2.7. The target route must be `OPEN` — scheduling against a route that is `DISPATCHED` or `CLOSED` fails with `ERR_ROUTE_LOCKED` — and must serve the same zone as the requesting household, failing with `ERR_ZONE_MISMATCH` otherwise. The route's date must not be in the past: a `route_date` earlier than the logical clock's date is rejected with `ERR_TEMPORAL_CONFLICT`. One household may hold at most one `SCHEDULED` request per calendar date — a point-equality test on the date, not an interval-overlap test — and a second booking on the same date fails with `ERR_DUPLICATE_PICKUP_DATE`. Capacity is enforced at the boundary inclusively: the schedule succeeds when the route's `committed_load_units` plus the request's `load_units` is less than or equal to `max_load_units` and `committed_stops` plus one is less than or equal to `max_stops`; exceeding either bound is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`.

When all gates pass, the transition into `SCHEDULED` does the following, atomically. It stamps `route_day_id` and copies `scheduled_date` from the route's `route_date`; that date fixes the allowance ledger's `calendar_year`. It freezes `amnesty_applied`: true if and only if an `ACTIVE` amnesty window exists whose half-open interval contains the scheduled date's midnight instant — that is, the window's `starts_at` is at or before midnight at the start of `scheduled_date`, and that midnight is strictly before `ends_at`. It then consumes allowance through the ledger rule of §3.1, walking items in `created_at`-then-`sequence_no` order: while the household's remaining free slots for the year — `annual_allowance_items` minus `items_consumed` — are at least 1, the next item in order takes a slot, its `within_allowance` becomes true, and `items_consumed` rises by 1; the item that lifts `items_consumed` from one below the allowance to exactly the allowance is still free, and the very next item is fee-bearing, its `within_allowance` false and `over_allowance_items` rising by 1 instead. With the allowance outcome known, the **scheduled variant** of the item-fee quote reruns: the same per-item composition and per-item-then-sum rounding as §3.2, but now honoring each item's actual `within_allowance` flag and the frozen `amnesty_applied` — when amnesty applies, the 2500-cent over-allowance component is waived to zero for every item, while the refrigerant, oversize, and mattress components and the 8.5 percent surcharge stand unchanged. The rewritten `item_fee_cents` and `provisional_total_cents` replace the worst-case estimate. The route absorbs the commitment: `committed_load_units` rises by the request's `load_units` and `committed_stops` by 1, bumping the RouteDay's `version` by 1. A Notification of `kind` `SCHEDULE_CONFIRMATION` is emitted, and the request's `version` increments.

Refusal does not end the booking relationship: from `REFUSED` the resident may schedule again onto another (or the same) open route, under the full set of scheduling gates above. The ledger is idempotent across this recovery loop — because a refusal never released allowance (§3.4), re-scheduling consumes slots only for items whose `within_allowance` is false and which have never consumed a slot on this request; items already counted keep their flags and are skipped. One exception closes the loop: when the refusal carried the reason `EXCEEDS_DECLARED_ITEMS`, the resident cannot simply rebook — the schedule attempt is rejected with `ERR_INVALID_STATE`, and since item edits exist only in `DRAFT`, the resident must cancel and redraft before scheduling again.

Cancellation is the resident's release valve, available from `SUBMITTED`, `SCHEDULED`, `MISSED`, and `REFUSED` (any other source state fails with `ERR_INVALID_STATE`), always carrying `expected_request_version` per §2.7. Cancelling a `SUBMITTED` request — one that never touched a route or the ledger — simply voids the pending provisional quote (its status becomes `WAIVED`, `settled_at` stamped from the clock), emits a `CANCELLATION_NOTICE`, and bumps the version. Cancelling a `SCHEDULED` request additionally unwinds the commitment, but only while the route is still unlocked and before the cutoff: a scheduled-cancel against a route that has left `OPEN` fails with `ERR_ROUTE_LOCKED` per §3.4, and otherwise the logical clock must be strictly earlier than midnight at the start of `scheduled_date`; at or after that midnight the pickup day has begun and cancellation fails with `ERR_TEMPORAL_CONFLICT`. A timely scheduled-cancel releases the route (`committed_load_units` falls by the request's `load_units`, `committed_stops` by 1, RouteDay `version` bumps) and releases the allowance: `items_consumed` falls by the number of items flagged `within_allowance`, `items_released` rises by the same count, `over_allowance_items` falls by the number of unflagged items, every item's `within_allowance` resets to false, the provisional quote is waived, and a `CANCELLATION_NOTICE` goes out. Cancelling from `MISSED` is light — notice plus version — because the miss already released both route and allowance (§3.4). Cancelling from `REFUSED` runs the same ledger release as a scheduled-cancel (the refusal had kept the allowance consumed), likewise waives any still-pending provisional quote and emits the `CANCELLATION_NOTICE`, but touches no route, since the refusal already returned the capacity — and is therefore permitted even after the route has been dispatched or closed. The lifecycle is deliberately cyclic: after any cancellation the household may draft afresh, and released allowance is immediately available to the next request.

### 3.4. Day of Service: Dispatch, Completion, Refusal, and Missed Stops

On the morning of collection, a `Dispatcher` dispatches the route — allowed only from `OPEN` (dispatching a route in any other status fails with `ERR_INVALID_STATE`), only when the logical clock's date equals `route_date` (dispatch is strictly day-of; any other date is `ERR_TEMPORAL_CONFLICT`), and only when at least one stop is committed (an empty route is not dispatched; `committed_stops` must be at least 1, and an empty route fails with `ERR_INVALID_STATE`). Dispatch moves the RouteDay from `OPEN` to `DISPATCHED`, bumps its `version`, and locks it: from that moment, scheduling attempts onto the route, and cancellations of requests still `SCHEDULED` on it, fail with `ERR_ROUTE_LOCKED` — those are the transitions that would mutate the route's committed capacity. Cancellations from `REFUSED` or `MISSED` remain permitted on a dispatched or closed route, because they touch no route counters.

A `Driver` working a dispatched route resolves each stop in one of three ways, all of which require the request to be `SCHEDULED` (anything else being `ERR_INVALID_STATE`), all of which require the request's route to be `DISPATCHED` (any other route status likewise being `ERR_INVALID_STATE`), and all of which require the logical clock's date to equal the request's `scheduled_date` — off-date driver actions are `ERR_TEMPORAL_CONFLICT`.

**Completion** moves the stop `SCHEDULED → COMPLETED` and is the fiscal climax. The driver may flag specific collected items as having been set out with improper preparation by passing their ids in `improper_preparation_item_ids`; the field is optional and defaults to an empty list, a non-list value fails with `ERR_INVALID_REQUEST`, each supplied id must resolve to an item of this request or the call fails with `ERR_NOT_FOUND` (an existence check that runs before the stop's state gate, per §2.9), and a duplicated id is counted only once. The final invoice builds on the frozen scheduled quote: `final_total_cents` is the request's `provisional_total_cents` plus a flat contamination penalty of 3000 cents for each item the driver flagged — the penalty carries no surcharge and no rounding, so the final total is always at least the provisional total. Completion creates a `FINAL_INVOICE` FeeAssessment for that amount in `PENDING` status — the penalty folds into that invoice and no separate `CONTAMINATION_PENALTY` assessment is emitted — waives the now-superseded `PROVISIONAL_QUOTE` assessment, assigns every collected item its `disposition_route` (§3.5), and bumps the request's `version`. Committed route counters deliberately stay put — a completed stop still occupies the day's capacity, so `COMPLETED` remains in the committed set alongside `SCHEDULED`.

**Refusal** moves the stop `SCHEDULED → REFUSED` when the set-out cannot be collected. The driver supplies a `refusal_reason_code`, one of `IMPROPER_PREPARATION`, `PROHIBITED_ITEM`, `BLOCKED_ACCESS`, `UNSAFE_SETOUT`, or `EXCEEDS_DECLARED_ITEMS`; a missing or unrecognized code fails with `ERR_INVALID_REQUEST` (HTTP 400), evaluated after the state, route, and date gates above. The route's committed load and stops are released (and the RouteDay's `version` bumps), but the household's allowance is **not** released — the set-out was made and consumed service capacity reaching the curb, so `items_consumed` stands. The pending provisional quote is waived, a `REFUSAL_NOTICE` notification is emitted carrying the reason code and, in its `message`, the category-specific preparation instructions for every item on the request, and the request's `version` increments. `REFUSED` is not terminal: the resident may reschedule per §3.3 or cancel per the cancellation rules.

**Miss** moves the stop `SCHEDULED → MISSED` when no set-out is present at the curb. The driver supplies a `missed_reason_code`, one of `NO_SETOUT`, `NOT_VISIBLE`, or `GATE_LOCKED`; a missing or unrecognized code fails with `ERR_INVALID_REQUEST` (HTTP 400), evaluated after the state, route, and date gates above. Because nothing was set out, both sides release: the route's committed counters decrement (RouteDay `version` bumps) and the allowance ledger runs its release rule — `items_consumed` and `over_allowance_items` fall by the flagged and unflagged item counts, `items_released` rises, item flags reset. The provisional quote is waived, a `MISSED_NOTICE` carrying the reason code is emitted, and the request's `version` increments.

When every stop on a dispatched route has left `SCHEDULED` — each request sitting in `COMPLETED`, `REFUSED`, `MISSED`, or `CANCELLED` — the `Dispatcher` may close the route, moving it `DISPATCHED → CLOSED` with a version bump; closing a route in any other status fails with `ERR_INVALID_STATE`. The bubble-up gate is strict: closing while any request on the route is still `SCHEDULED` fails with `ERR_ROUTE_NOT_EMPTY`.

### 3.5. Fees, Settlement, and Disposal Routing

Every monetary obligation in the system is a **FeeAssessment**, carrying a `kind` of `PROVISIONAL_QUOTE`, `FINAL_INVOICE`, `CONTAMINATION_PENALTY`, or `ILLEGAL_DUMPING_FINE`; an `amount_cents`; a `status` that begins at `PENDING`; and a `settled_at` that stays null while pending and stamps the logical clock at resolution. (The `CONTAMINATION_PENALTY` kind exists in the enumeration for completeness, but no assessment of that kind is ever emitted: the penalty folds into the `FINAL_INVOICE` per §3.4.) Assessments belong fiscally to a household via `household_id` — copied from the originating request, or set directly for an unlinked dumping fine — and normally reference their request through `pickup_request_id`, which is null only for an `ILLEGAL_DUMPING_FINE` raised without any linked pickup.

Settlement is a resident action on assessments their household owns. Settling requires the assessment to be `PENDING` and the acting resident's identity to match the assessment's `household_id`; settling a non-pending assessment or one belonging to another household fails with `ERR_ASSESSMENT_NOT_SETTLABLE` — for this action specifically, the settlability rule supersedes the generic §2.1 ownership rejection, so a non-owning `Resident` receives `ERR_ASSESSMENT_NOT_SETTLABLE` (409), not `ERR_FORBIDDEN`. A successful settle moves the assessment to `SETTLED`, stamps `settled_at`, and bumps `version`. A `Dispatcher` may instead waive any `PENDING` assessment, moving it to `WAIVED` with the same timestamp and version semantics; waiving an assessment that is not `PENDING` fails with `ERR_INVALID_STATE` — note the segregation of duties: waiver is Dispatcher-only, while dumping determinations and reinstatements are Inspector-only. System cascades also waive assessments without any client call: cancelling, refusing, missing, or completing a request each waives its pending provisional quote as described in §3.3 and §3.4. A zero-amount assessment is created `PENDING` like any other and may be settled or waived normally.

At completion, every collected item receives its downstream destination in `disposition_route`, assigned purely by category: `STANDARD_FURNITURE` goes to `LANDFILL`, `MATTRESS` to `MATTRESS_RECYCLING`, `APPLIANCE_NO_REFRIGERANT` to `METAL_RECYCLING`, `APPLIANCE_WITH_REFRIGERANT` to `REFRIGERANT_RECOVERY` (refrigerant items always route to recovery first, regardless of oversize), `ELECTRONICS` to `E_WASTE`, and `TIRES` to `TIRE_RECYCLING`.

### 3.6. Amnesty Weeks and Illegal-Dumping Enforcement

Twice a year or so, the department declares an **AmnestyWindow**: a `label` such as "Fall Amnesty Week 2026" plus `starts_at` and `ends_at` bounding a half-open interval — the window includes its start instant and excludes its end instant, so `starts_at` must be strictly earlier than `ends_at`, and the new window must not intersect any existing `ACTIVE` window (touching endpoints are allowed, since an instant that ends one window is excluded from it). Violating either temporal rule at declaration is `ERR_TEMPORAL_CONFLICT`. Inside an active window, requests scheduled with `amnesty_applied` true pay no over-allowance fees, per the scheduled quote in §3.3; the allowance ledger itself is untouched — amnesty forgives the fee, not the slot. A `Dispatcher` may cancel a window, moving it `ACTIVE → CANCELLED` with a version bump; requests already scheduled under it keep their frozen quotes, with no retroactive repricing.

Against this backdrop, dumping enforcement runs on **DumpingReports**. An `Inspector` or a `Driver` files a report naming the `household_id` at whose address material was found, and optionally the `pickup_request_id` the set-out is claimed to belong to; the report is born `OPEN` with `reported_at` stamped from the logical clock. Determination is Inspector-only and offers three outcomes.

The inspector's ruling takes one of three values for the report's terminal state: `DETERMINED_AUTHORIZED`, `DETERMINED_ILLEGAL`, or `DISMISSED`. The determination value `AUTHORIZED_SETOUT` — the material was placed within one day of a genuinely scheduled pickup for that household — requires that the report links a request, that the linked request is currently `SCHEDULED`, and that its `scheduled_date` falls within the inclusive window from one day before to one day after the `reported_at` date; it moves the report to `DETERMINED_AUTHORIZED` and, on the linked pickup request, the inspector's determination is visible in the request's `setout_classification` as `AUTHORIZED_SETOUT`. Determining `ILLEGAL_DUMPING` requires the absence of exactly that conjunction; it moves the report to `DETERMINED_ILLEGAL` and marks the linked request's `setout_classification` as `ILLEGAL_DUMPING` when one is linked. Issuing a determination inconsistent with the linked evidence — authorized without the qualifying link, or illegal while the qualifying link exists — fails with `ERR_DETERMINATION_INCONSISTENT`. In all three outcomes the inspector's determination is recorded as the report's terminal `status` (the report carries no separate determination field), `determination_notes` are set, and the report's `version` bumps; a `DISMISSED` determination does nothing further.

An illegal determination fires the deepest cascade in the system. It creates a `PENDING` FeeAssessment of `kind` `ILLEGAL_DUMPING_FINE` owned by the report's household: when the report links a request, the fine's `pickup_request_id` carries it; otherwise the fine stands unlinked against the household alone. The fine amount escalates with the household's history. The system counts the household's prior confirmed violations — dumping reports already `DETERMINED_ILLEGAL` with a `reported_at` strictly earlier than this report's `reported_at`, ties broken by `created_at` ascending — and the fine is the 25000-cent base fine doubled once per prior violation, capped at three doublings: no priors yields 25000 cents, one prior 50000, two priors 100000, and three or more priors 200000 cents. Transitively, the household's `status` flips to `SUSPENDED` with `suspension_reason` set, bumping the Household's `version` — and from then on the standing gate of §3.1 rejects that household's request creation, submission, and scheduling attempts. When the report links a request, an `ILLEGAL_DUMPING_WARNING` notification is emitted on that request. The path back to good standing runs only through settlement or waiver of every one of the household's illegal-dumping fines followed by Inspector reinstatement, as §3.1 describes.

Every lifecycle event that warrants resident communication emits a **Notification** on the affected request: `SCHEDULE_CONFIRMATION` at scheduling, `REFUSAL_NOTICE` (with `reason_code` and preparation instructions in the body), `MISSED_NOTICE` (with its reason code), `CANCELLATION_NOTICE`, and `ILLEGAL_DUMPING_WARNING`. Notifications are immutable emission records — `id` and `created_at` only, per §2.5 — and `reason_code` is null whenever the notice kind carries no driver reason.

### 3.7. Reading Route Load: Projected vs. Committed Fullness

A route day's fullness can be read two legitimate ways, and the API exposes both because they diverge exactly when a stop completes. The stored committed counters — `committed_load_units` and `committed_stops` — count requests in `SCHEDULED` or `COMPLETED`; this is the capacity-and-billing truth, the figure capacity enforcement uses, and it means a completed stop still occupies capacity for the rest of the day. The projected view, recomputed on every read of the route day, counts only requests currently in `SCHEDULED`: `projected_load_units` sums those requests' `load_units`, and `projected_fullness_pct` is 100 times that sum divided by `max_load_units`, rounded half-up to a whole percentage point (and defined as 0 when `max_load_units` is 0). A dispatcher planning remaining bookings reads the projection; the system enforcing limits reads the commitment.

## 4. Endpoint Definitions

Operations that create a new resource — a household, an amnesty window, a route day, a pickup request, an item on a request, a dumping report — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`; item removal returns `204 No Content`. All endpoints are mounted under the `/curbside` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/curbside/_clock/set_current_utc` | Set the server's logical clock (startup default exactly 2026-08-01T00:00:00Z) | Dispatcher |
| POST | `/curbside/households` | Register a household account | Dispatcher |
| GET | `/curbside/households/{id}` | Fetch one household | Dispatcher, Inspector, Resident |
| GET | `/curbside/households` | List households (filterable, paginated) | Dispatcher, Inspector |
| POST | `/curbside/households/{id}/reinstate` | Lift a suspension after fines settle | Inspector |
| GET | `/curbside/households/{id}/allowances` | List allowance ledger rows of a household | Dispatcher, Inspector, Resident |
| GET | `/curbside/households/{id}/pickup-requests` | List pickup requests of a household | Dispatcher, Inspector, Resident |
| GET | `/curbside/households/{id}/dumping-reports` | List dumping reports against a household | Dispatcher, Inspector |
| GET | `/curbside/households/{id}/fee-assessments` | List assessments owned by a household, including unlinked dumping fines | Dispatcher, Inspector, Resident |
| POST | `/curbside/amnesty-windows` | Declare an amnesty week window (half-open, non-intersecting) | Dispatcher |
| GET | `/curbside/amnesty-windows/{id}` | Fetch one amnesty window | Dispatcher, Inspector, Resident, Driver |
| GET | `/curbside/amnesty-windows` | List amnesty windows | Dispatcher, Inspector, Resident, Driver |
| POST | `/curbside/amnesty-windows/{id}/cancel` | Cancel an amnesty window; scheduled requests keep frozen quotes | Dispatcher |
| POST | `/curbside/route-days` | Create a route day for a zone/date with capacities | Dispatcher |
| GET | `/curbside/route-days/{id}` | Fetch route day including computed projected fullness fields | Dispatcher, Inspector, Resident, Driver |
| GET | `/curbside/route-days` | List route days | Dispatcher, Inspector, Resident, Driver |
| POST | `/curbside/route-days/{id}/dispatch` | Dispatch route (day-of only); locks schedule/cancel mutations | Dispatcher |
| POST | `/curbside/route-days/{id}/close` | Close route once every stop is terminal or post-service | Dispatcher |
| GET | `/curbside/route-days/{id}/pickup-requests` | List requests scheduled on this route | Dispatcher, Inspector, Driver |
| POST | `/curbside/pickup-requests` | Create a DRAFT pickup request for a household | Resident |
| GET | `/curbside/pickup-requests/{id}` | Fetch one pickup request | Dispatcher, Inspector, Resident, Driver |
| GET | `/curbside/pickup-requests` | List pickup requests (filterable) | Dispatcher, Inspector, Driver |
| POST | `/curbside/pickup-requests/{id}/items` | Add an item to a DRAFT request | Resident |
| DELETE | `/curbside/pickup-requests/{id}/items/{item_id}` | Remove an item from a DRAFT request | Resident |
| GET | `/curbside/pickup-requests/{id}/items` | List items of a request | Dispatcher, Inspector, Resident, Driver |
| POST | `/curbside/pickup-requests/{id}/submit` | Submit DRAFT request; produces provisional quote and assessment | Resident |
| POST | `/curbside/pickup-requests/{id}/schedule` | Schedule onto a route day (from SUBMITTED or REFUSED); OCC-guarded on the route day | Resident |
| POST | `/curbside/pickup-requests/{id}/cancel` | Cancel from SUBMITTED, SCHEDULED (before cutoff), MISSED, or REFUSED; OCC-guarded on the request | Resident |
| POST | `/curbside/pickup-requests/{id}/complete` | Driver marks pickup collected; builds final invoice and disposition routing | Driver |
| POST | `/curbside/pickup-requests/{id}/refuse` | Driver refuses non-compliant set-out; allowance not released | Driver |
| POST | `/curbside/pickup-requests/{id}/miss` | Driver marks stop missed (no set-out); allowance released | Driver |
| GET | `/curbside/pickup-requests/{id}/fee-assessments` | List assessments of a request | Dispatcher, Inspector, Resident |
| GET | `/curbside/pickup-requests/{id}/notifications` | List notifications of a request | Dispatcher, Inspector, Resident, Driver |
| GET | `/curbside/pickup-requests/{id}/dumping-reports` | List dumping reports linked to a request | Dispatcher, Inspector |
| GET | `/curbside/fee-assessments/{id}` | Fetch one assessment | Dispatcher, Inspector, Resident |
| GET | `/curbside/fee-assessments` | List assessments (filterable) | Dispatcher, Inspector |
| POST | `/curbside/fee-assessments/{id}/settle` | Resident settles a PENDING assessment they own | Resident |
| POST | `/curbside/fee-assessments/{id}/waive` | Dispatcher waives a PENDING assessment | Dispatcher |
| POST | `/curbside/dumping-reports` | File a report of material set out at a household address | Inspector, Driver |
| GET | `/curbside/dumping-reports/{id}` | Fetch one dumping report | Dispatcher, Inspector |
| GET | `/curbside/dumping-reports` | List dumping reports | Dispatcher, Inspector |
| POST | `/curbside/dumping-reports/{id}/determine` | Inspector determines AUTHORIZED_SETOUT / ILLEGAL_DUMPING / DISMISSED | Inspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ROUTE_VERSION` | 412 |
| `ERR_STALE_REQUEST_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROHIBITED_ITEM` | 422 |
| `ERR_PREPARATION_NOT_ACKED` | 422 |
| `ERR_HOUSEHOLD_SUSPENDED` | 409 |
| `ERR_ZONE_MISMATCH` | 422 |
| `ERR_TEMPORAL_CONFLICT` | 422 |
| `ERR_DUPLICATE_PICKUP_DATE` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_ROUTE_LOCKED` | 409 |
| `ERR_ROUTE_NOT_EMPTY` | 409 |
| `ERR_DETERMINATION_INCONSISTENT` | 422 |
| `ERR_ASSESSMENT_NOT_SETTLABLE` | 409 |

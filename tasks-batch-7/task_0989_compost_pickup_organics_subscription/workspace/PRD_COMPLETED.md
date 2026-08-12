# Compost Pickup API — Product Requirements Document

## 1. Introduction

Curbside organics collection succeeds or fails on two disciplines that rarely coexist in one system: the physical choreography of bins, routes, and weekly swaps, and the financial choreography of subscriptions, credits, and invoices. The Compost Pickup API is the operational backbone for a subscription-based organics service that must run both at once. Residential households and commercial kitchens receive bins sized to their plan; drivers run weekly routes and swap full bins for clean ones; contamination spotted at the curb or discovered later at the facility is tagged, disputed, and adjudicated; and every diverted kilogram earns credit that subscribers can redeem for bags of finished compost.

Two billing cultures run side by side here. Residential plans pay a flat weekly price regardless of weight, while commercial plans are metered — a base charge whenever a pickup is attempted or completed, plus a per-kilogram overage beyond an included weekly allowance, and the meter only settles once the facility's scale has spoken. Every kilogram therefore passes through two valuations: a driver estimate recorded at the curb and a weighed allocation computed when the route's load crosses the scale, with an append-only credit ledger reconciling the difference entry by entry. Around that core sit the temporal rules that make a weekly service operable — skip cutoffs, pause windows, quarterly skip allowances, invoice due dates — all read from a single logical clock, plus a contamination strike policy that protects stream quality by suspending repeat offenders automatically.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Four roles are recognized: `Anonymous`, `Subscriber`, `Driver`, and `OperationsManager`. A request with missing headers, or whose declared role is not one of these four, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed on the target endpoint — or, for a `Subscriber` caller, one that targets a resource the caller does not own — is rejected with `ERR_FORBIDDEN_ROLE`.

When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on any resource reachable through a subscriber chain — subscriptions, pickups, contamination tags, credit entries, redemptions, invoices — compare the resource's subscriber reference against `X-User-ID`. When `X-User-Role` is `Driver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `tagged_by_driver_id` on any contamination tag the driver files, where it anchors the segregation-of-duties rule, but never compares it to any entity's `id`. When `X-User-Role` is `OperationsManager`, `X-User-ID` is likewise opaque; the server records it as `resolved_by` when a contamination tag is confirmed or waived. A single person may hold both `Driver` and `OperationsManager` grants; even so, that person remains barred from confirming or waiving a tag they filed as a driver. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier with no entity backing, used only for the self-signup operation.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter tells the server how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise noted, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock

All time-dependent rules in this system — skip cutoffs, invoice due dates, quarter labels, season labels, pause-window placement — read a single server-side logical clock, never the wall clock. At startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time on its own. An `OperationsManager` may move the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and responds with the new `current_utc`; every cutoff, due-date, quarter, and season computation described in this document is evaluated against that value.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time as an ISO 8601 UTC value with three fractional digits, and `updated_at` is an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties. The `version` field is a system-managed integer that starts at 1 at creation and increments with every modification to the resource, and `updated_at` initially equals `created_at`; together these anchor the optimistic concurrency rule of §2.8. The `created_at` and `updated_at` values are stamped from the server's wall clock — kept monotonically increasing so that `created_at` ordering always matches insertion order — never from the logical clock of §2.4; the logical clock governs rule evaluations and logical timestamps such as a tag's `resolved_at`, not these record-keeping timestamps. Two resources are deliberately lighter: a `ServicePlan` is configuration and a `CompostCreditEntry` is an append-only ledger event, so each carries only `id` and `created_at` — both `updated_at` and `version` are absent from these two resources.

### 2.6. The Subscriber Credit Ledger

Every subscriber's account is backed by an append-only credit ledger. Each row is a `CompostCreditEntry` carrying a signed `amount_cents` — credits are positive, debits are negative — and the subscriber's `credit_balance_cents` is, at all times, exactly the sum of the signed `amount_cents` values across all of that subscriber's entries. The balance starts at zero. Six entry types exist: `EARNED_ESTIMATED` for the provisional curb-side credit posted at pickup completion, `EARNED_FINAL_ADJUSTMENT` for the reconciliation delta posted when a route is weighed, `REDEMPTION_DEBIT` for a fulfilled finished-compost redemption, `INVOICE_APPLICATION_DEBIT` for credits consumed at invoice issuance, `MANUAL_ADJUSTMENT` for an operator-posted correction, and `REVERSAL` for compensating entries that undo an earlier credit or debit. Every entry names its cause through the link fields — `pickup_id` for earned entries, for reversal entries tied to a pickup, and for the waiver's credit-restore adjustment of §3.6, `redemption_id` for redemption debits, and `invoice_id` for invoice applications and their reversals — while an operator-posted `MANUAL_ADJUSTMENT` carries no link field, only its `reason`; each entry also records a `season` label, which is the season of the causal pickup's `service_date` for `EARNED_ESTIMATED` and `EARNED_FINAL_ADJUSTMENT` entries and the season of the logical now at posting time for every other entry type. Only `MANUAL_ADJUSTMENT` takes its `amount_cents` from client input, accompanied by an operator `reason`; every other entry's amount is computed by the system. The balance is never allowed to go negative: a manual adjustment that would push `credit_balance_cents` below zero is rejected with `ERR_INSUFFICIENT_CREDIT`. The ledger is browsable through a list endpoint with optional filters on `subscriber_id`, `pickup_id`, `redemption_id`, `invoice_id`, and `entry_type`, and single entries can be read individually.

### 2.7. Weights, Money, and Rounding

Kilogram quantities are carried to exactly 2 decimal places using round-half-up and are serialized in responses as JSON numbers. Monetary amounts are integer cents, never floats; whenever a money computation produces a fractional cent, the result is rounded half-up to a whole cent. Seasonal multipliers are applied to a credit computation before its final cent rounding, not afterwards. Invoice math pins the rounding order explicitly: every charge line is computed and rounded to a whole cent in isolation, and the invoice subtotal is the sum of those integer line amounts — the system never sums unrounded values and rounds once at the end. The single exception to round-half-up is the invoice credit cap, which rounds down (floor) to a whole cent.

### 2.8. Optimistic Concurrency Control

Exactly one operation in the system is guarded by optimistic concurrency control: the plan-change. A request to the plan-change operation (`POST /subscriptions/{id}/plan-change`) must carry `expected_subscription_version`, a non-optional input field holding the `version` of the `Subscription` the caller last observed. If that value does not match the subscription's current `version` — because another accepted plan-change replaced the plan, or a pause, resume, or cancellation advanced the row since the caller read it — the caller's view is stale and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A legitimate newer plan therefore supersedes the prior one rather than being silently discarded by a second writer. No other endpoint accepts a version field.

### 2.9. Seasons and Credit Multipliers

Diversion credits carry a seasonal multiplier, so the calendar is partitioned into four seasons. `SPRING` runs from March 1 through May 31, `SUMMER` from June 1 through August 31, `FALL` from September 1 through November 30, and `WINTER` from December 1 through the end of February. A season label joins the calendar year to the season name, as in `2026-SUMMER`; December 2026 falls in `2026-WINTER`, while January and February 2027 fall in `2027-WINTER`. The multipliers are 1.0 for `SPRING`, 1.2 for `SUMMER`, 1.0 for `FALL`, and 0.8 for `WINTER`. Wherever a credit is computed from kilograms — the estimated credit at completion and the weighed credit at ticket posting alike — the multiplier of the service date's season is applied before the final cent rounding, and the entry records the resulting `season` label.

### 2.10. Validation Order and Identifier Resolution

When several checks apply to one request, the server evaluates them in a fixed order, so an earlier failure masks every later one. First, authentication: both headers present and the role recognized, otherwise `ERR_UNAUTHENTICATED`. Second, authorization: the role listed on the endpoint, otherwise `ERR_FORBIDDEN_ROLE`. Ownership for `Subscriber` callers is enforced together with identifier resolution in the fourth tier: where the identifier is a bare subscriber reference — the path id of `/subscribers/{id}` and its sub-resources, or a body `subscriber_id` — ownership is a direct string comparison against `X-User-ID` and a mismatch is `ERR_FORBIDDEN_ROLE` before that subscriber's existence is checked; where the target is a path-addressed resource, the resource is resolved first, its absence producing `ERR_NOT_FOUND`, and ownership of the resolved resource is then enforced as `ERR_FORBIDDEN_ROLE`. Third, request-body shape: required fields present, enums valid, ranges valid — `fullness_pct` between zero and one inclusive, `bags` at least one, `pause_end` later than `pause_start`, `week_start_date` a Monday, an adjustment's `amount_cents` nonzero — otherwise `ERR_INVALID_REQUEST`. Fourth, existence: every identifier referenced in the path and body — `plan_id`, `route_id`, `subscriber_id`, `new_plan_id`, and any path `id` — must resolve to an existing entity, otherwise `ERR_NOT_FOUND`; path identifiers are resolved left to right as they appear in the URL, and the first unresolvable identifier produces the 404. Fifth, concurrency: `expected_subscription_version` matching the current `Subscription.version` on the plan-change, otherwise `ERR_STALE_VERSION`. Sixth, state gates: the target resource must be in a valid from-state for the operation, otherwise the operation-specific conflict — `ERR_SUBSCRIPTION_STATE_CONFLICT`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_PICKUP_NOT_ACTIONABLE`, `ERR_TAG_NOT_RESOLVABLE`, `ERR_REDEMPTION_NOT_FULFILLABLE`, `ERR_INVOICE_NOT_PAYABLE`, or `ERR_INVALID_STATE`. Seventh, segregation of duties on tag confirmation and waiver, otherwise `ERR_SEGREGATION_OF_DUTIES`. Eighth, fiscal gates — account delinquency, credit sufficiency, and the quarterly skip allowance — otherwise `ERR_ACCOUNT_DELINQUENT`, `ERR_INSUFFICIENT_CREDIT`, or `ERR_SKIP_LIMIT_EXCEEDED`; this tier guards pause, resume, redemption creation and fulfillment, credit adjustments, and pickup skips. Ninth, structural constraints — route weekly slot capacity, clean-bin availability, plan-change bin-count compatibility, the one-open-tag rule, weigh-ticket uniqueness and allocatability, the weigh-ticket void lock, and finished-compost stock availability — otherwise `ERR_ROUTE_CAPACITY`, `ERR_NO_BIN_AVAILABLE`, `ERR_PLAN_DOWNGRADE_BLOCKED`, `ERR_TAG_ALREADY_OPEN`, `ERR_DUPLICATE_WEIGH_TICKET`, `ERR_INVALID_WEIGHT`, `ERR_PICKUP_LOCKED_BY_WEIGH_TICKET`, or `ERR_INSUFFICIENT_STOCK`; this tier guards subscription creation and plan-change, pickup completion and void, tag creation, weigh-ticket posting, and redemption creation. Tenth, temporal rules — the skip cutoff, pause-window overlap, the generate-stops weekday match, and the commercial weigh-ticket billing gate — otherwise `ERR_SKIP_CUTOFF_PASSED`, `ERR_PAUSE_WINDOW_OVERLAP`, `ERR_SERVICE_DATE_WEEKDAY_MISMATCH`, or `ERR_WEIGH_TICKET_PENDING`; this tier guards skips, pauses, stop generation, and the billing run.

### 2.11. Subscriber Visibility and Ownership Scoping

`Subscriber` callers never see other subscribers' data. On every list endpoint a `Subscriber` caller is force-scoped to their own records regardless of the filters supplied: their own subscriptions, the pickups of their own subscriptions, their own contamination tags, their own credit entries, their own redemptions, and their own invoices. Reading a single resource that belongs to another subscriber is rejected with `ERR_FORBIDDEN_ROLE`. `Driver` and `OperationsManager` callers operate across the fleet and the customer base according to the endpoint table in §4.

## 3. Business Logic & Workflows

### 3.1. Service Plans and Subscriber Signup

The service catalog is authored by an `OperationsManager` as a set of **Service Plans**. Each plan is created with a `code` (such as `RES_BIN` or `COM_BIN`), a human-readable `name`, a `subscriber_type` of either `RESIDENTIAL` or `COMMERCIAL`, and a `bin_type` drawn from `BIN_35L`, `BIN_70L`, `BIN_240L`, or `BIN_960L`. The plan's `included_bins` states how many bins a subscription of that plan receives. The pricing fields split along the two billing cultures: `weekly_price_cents` is the flat weekly charge that forms the residential billing basis and is zero on commercial plans, while `metered_base_cents` is the weekly base charged when a commercial pickup is attempted or completed, `per_kg_rate_cents` is the commercial per-kilogram overage rate beyond the included allowance, and `included_kg_per_week` is the commercial weekly included kilograms before overage — all three zero on residential plans. Every plan also declares `credit_rate_cents_per_kg`, the diversion credit earned per collected kilogram before the seasonal multiplier, and `skip_allowance_per_quarter`, the number of skips a subscription on the plan may consume per calendar quarter. Plans are readable by `Subscriber` and `OperationsManager` callers.

New customers self-signup through the anonymous signup operation, supplying an `email`, a `full_name`, a `subscriber_type` of `RESIDENTIAL` or `COMMERCIAL`, and a service `address`. A fresh subscriber begins in `GOOD_STANDING` with a `credit_balance_cents` of zero. The `account_standing` field is never stored; it is derived on every read from the subscriber's invoices, per §3.9, and surfaces as either `GOOD_STANDING` or `DELINQUENT`. A subscriber profile can be read by its owner or by an `OperationsManager`.

### 3.2. Subscriptions: Activation, Plan Changes, and Route Capacity

Before subscriptions can open, an `OperationsManager` defines the weekly **routes**. A route is created with a `code`, a `weekday` — one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN` marking its weekly service day — and `max_stops`, the maximum number of coexisting `ACTIVE` subscriptions the route can carry. Each route exposes `active_subscriptions_count`, the count of subscriptions whose `service_status` is `ACTIVE` on that route, and route reads are available to `Driver` and `OperationsManager` callers.

A subscription is opened by a `Subscriber` (for themselves) or an `OperationsManager` with a payload containing the `subscriber_id`, the `plan_id`, the `route_id`, and a `start_date` marking the first eligible service date. The plan's `subscriber_type` must equal the subscriber's own `subscriber_type`, otherwise the request is rejected with `ERR_INVALID_REQUEST`; this comparison needs both records, so it is evaluated only once the `subscriber_id`, `plan_id`, and `route_id` have all resolved, and an unresolvable identifier produces its 404 first. Creation triggers two structural checks. First, the depot must yield the bins: the system selects `included_bins` bins whose `bin_type` matches the plan's, whose `status` is `IN_DEPOT`, and whose `condition` is `CLEAN`, taking the earliest-created eligible bins first; if the depot runs short, creation fails with `ERR_NO_BIN_AVAILABLE`. Second, the route must have a free weekly slot — its `active_subscriptions_count` must be below `max_stops` — otherwise creation fails with `ERR_ROUTE_CAPACITY`; once the subscription is active the count is recomputed. Each selected bin moves to `AT_CUSTOMER` with its `current_subscription_id` set to the new subscription. The subscription itself begins with `service_status` `ACTIVE`, a `strike_count` of zero, `skips_used_this_quarter` at zero, an empty `pause_windows` list, and `current_quarter` left to be stamped lazily at the first skip accounting. The subscription list endpoint accepts optional filters on `subscriber_id`, `plan_id`, `route_id`, and `status`.

While a subscription is `ACTIVE`, its plan may be replaced through the plan-change operation — a self-transition that keeps the subscription `ACTIVE`. The payload carries the `new_plan_id` and, per §2.8, the `expected_subscription_version`; a stale version is rejected with `ERR_STALE_VERSION`. Attempting a plan-change on a subscription that is not `ACTIVE` — including a terminal `CANCELLED` one — is rejected with `ERR_SUBSCRIPTION_STATE_CONFLICT`. The new plan must exist, otherwise `ERR_NOT_FOUND`, and it must share the subscriber's `subscriber_type` while including at least as many bins as are currently assigned to the subscription; crossing the residential/commercial line or downsizing below the assigned bin count is rejected with `ERR_PLAN_DOWNGRADE_BLOCKED`. On success the `plan_id` is replaced and the subscription's `version` increments by one; no bins are added to or removed from the subscription by a plan-change — the bin assignment is left exactly as it was.

### 3.3. The Weekly Cycle: Stop Generation and the Bin Fleet

Each service week begins when an `OperationsManager` generates a route's stops for a supplied `service_date`. The weekday of that date must match the route's `weekday`, otherwise the request is rejected with `ERR_SERVICE_DATE_WEEKDAY_MISMATCH`. For every subscription with `service_status` `ACTIVE`, assigned to this route, whose `start_date` falls on or before the service date, and that has no pickup already existing for that date, the system creates a **Pickup Event** in `SCHEDULED` status with its `subscription_id`, `route_id`, and `service_date` set. Subscriptions are processed in ascending order of their own creation time, and generation is idempotent: subscriptions already covered for the date are skipped. The response reports the `created_count` and the list of `pickup_ids`. Pickup events can be browsed through a list endpoint with optional filters on `subscription_id`, `route_id`, `collected_bin_id`, `replacement_bin_id`, and `status`, sorted by creation time ascending, and individual pickups can be read.

The depot fleet is managed alongside. An `OperationsManager` registers each **bin** with a `bin_type` and a `nominal_capacity_kg` — the kilograms of organics the bin holds at one hundred percent fullness — and a new bin enters the fleet at `IN_DEPOT` with condition `CLEAN`. A bin evolves along two parallel dimensions: its `status` (`IN_DEPOT` or `AT_CUSTOMER`) and its `condition` (`CLEAN` or `NEEDS_WASH`) move independently, with two binding rules — only `CLEAN` bins may leave the depot, and any bin returning from a customer arrives with `NEEDS_WASH`. While a bin sits at a customer site its `current_subscription_id` names the subscription it serves; while in the depot that field is null. Washing is an `OperationsManager` action that requires the bin to be `IN_DEPOT` with condition `NEEDS_WASH` — any other combination is rejected with `ERR_INVALID_STATE` — and it sets the condition to `CLEAN`, leaves the status untouched, and increments the bin's `version`. The bin list endpoint accepts optional filters on `current_subscription_id`, `status`, and `condition`.

### 3.4. Completing a Stop: The Swap and the Estimated Credit

When a `Driver` reaches a scheduled stop, completing it records a `fullness_pct` — the fill fraction of the customer's bin as a value between zero and one inclusive; anything outside that range is rejected with `ERR_INVALID_REQUEST`. Only a pickup still in `SCHEDULED` may be completed, otherwise the request fails with `ERR_PICKUP_NOT_ACTIONABLE`. Before any field mutates, the system must be able to select a replacement bin: a depot bin whose `bin_type` equals the plan's, with `status` `IN_DEPOT` and condition `CLEAN`, choosing the earliest-created match. If no such bin exists the completion is rejected with `ERR_NO_BIN_AVAILABLE` and nothing changes — the operation is atomic. The same `ERR_NO_BIN_AVAILABLE` rejection applies when the subscription has no bin assigned to collect; when several bins sit at the customer, the collected bin is the earliest-created bin currently assigned to the subscription.

A successful completion performs the swap and posts the first valuation. The pickup's `estimated_kg` is computed as the collected bin's `nominal_capacity_kg` multiplied by `fullness_pct`, rounded half-up to two decimal places. The `collected_bin_id` records the subscription's outgoing bin, which returns to `IN_DEPOT` with condition `NEEDS_WASH` and its `current_subscription_id` cleared; the `replacement_bin_id` records the selected clean bin, which moves to `AT_CUSTOMER` with its `current_subscription_id` set to the served subscription. The pickup lands in `COMPLETED` and its `version` increments. In the same motion, an `EARNED_ESTIMATED` credit entry is created: the `estimated_kg` multiplied by the plan's `credit_rate_cents_per_kg` and by the seasonal multiplier of the service date, rounded half-up to integer cents, and the subscriber's `credit_balance_cents` rises by that amount. This is the estimated variant of the diversion credit — provisional, resting on the driver's fill estimate — and it stands until the route is weighed, when §3.7's weighed variant reconciles it; identical pickup data can therefore yield different cents under the two variants.

Two other driver outcomes close a scheduled stop without billing it. Marking a pickup missed moves it from `SCHEDULED` to `MISSED`, recording driver fault: the week is not billed for that stop, and the pickup's `version` increments. And because a waived contamination tag returns a rejected pickup for a make-up attempt (§3.6), completing a pickup after its service date is allowed.

### 3.5. Skips, Pauses, and Cancellations: Subscriber Schedule Control

A subscriber may skip an upcoming stop on their own subscription. The pickup must still be `SCHEDULED`, otherwise `ERR_PICKUP_NOT_ACTIONABLE`, and the subscription must be `ACTIVE`, otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`. Two further gates apply, both temporal. The cutoff: a skip is accepted only while the logical clock reads strictly earlier than forty-eight hours before 00:00 UTC on the service date — a skip attempted exactly at that cutoff instant, or later, is rejected with `ERR_SKIP_CUTOFF_PASSED`. The quarterly allowance: calendar quarters run Q1 from January through March, Q2 from April through June, Q3 from July through September, and Q4 from October through December, labeled as year-and-quarter strings such as `2026-Q2`. The allowance accounting is lazy — whenever the subscription's `current_quarter` differs from the quarter of the logical today, `skips_used_this_quarter` is reset to zero and `current_quarter` is stamped with today's quarter label. A skip is allowed only while `skips_used_this_quarter` is strictly below the plan's `skip_allowance_per_quarter`; a subscription that has consumed exactly its allowance is rejected with `ERR_SKIP_LIMIT_EXCEEDED`. A successful skip moves the pickup to `SKIPPED`, increments `skips_used_this_quarter` by one, and increments the pickup's `version`.

Pausing covers longer absences. From `ACTIVE` — any other service status is rejected with `ERR_SUBSCRIPTION_STATE_CONFLICT` — a subscriber (for their own subscription) or an `OperationsManager` may pause service over a window supplied as `pause_start` and `pause_end`. The subscriber must be in `GOOD_STANDING`, otherwise `ERR_ACCOUNT_DELINQUENT`. The window's `pause_end` must be later than its `pause_start`, otherwise `ERR_INVALID_REQUEST`, and the new half-open window — inclusive of its start, exclusive of its end — must not overlap any window already recorded in `pause_windows`; adjacency is allowed, so a new window whose start equals an existing window's end is accepted, while any true overlap is rejected with `ERR_PAUSE_WINDOW_OVERLAP`. On success the subscription's `service_status` becomes `PAUSED` immediately — wherever the window lies relative to the logical now — the window is appended to `pause_windows` (the list is append-only), every `SCHEDULED` pickup of the subscription whose `service_date` falls inside the window transitions to `CANCELLED_SYSTEM`, and the subscription's `version` increments by one. Resuming reverses the status half: from `PAUSED` — otherwise `ERR_SUBSCRIPTION_STATE_CONFLICT` — and only while the subscriber is in `GOOD_STANDING`, otherwise `ERR_ACCOUNT_DELINQUENT`; resuming returns the subscription to `ACTIVE` and increments its `version`. The `ACTIVE`–`PAUSED` pair loops indefinitely.

Cancellation is the terminal exit and can be invoked by the subscriber (own) or an `OperationsManager` from any of `ACTIVE`, `PAUSED`, or `SUSPENDED`, with no further preconditions; invoking it on an already-`CANCELLED` subscription is rejected with `ERR_SUBSCRIPTION_STATE_CONFLICT`. From `ACTIVE` or `PAUSED`, cancelling transitions all of the subscription's `SCHEDULED` pickups to `CANCELLED_SYSTEM` and returns every assigned bin to the depot — `status` to `IN_DEPOT`, `condition` to `NEEDS_WASH`, `current_subscription_id` cleared — then increments the subscription's `version`. From `SUSPENDED`, the same bin return runs but there are no scheduled pickups left to cancel: the suspension cascade of §3.6 has already cleared them. `CANCELLED` is terminal.

### 3.6. Contamination: Tagging, Disputes, and the Strike Cascade

When a `Driver` finds contamination, they file a **Contamination Tag** against the pickup, supplying a `severity` of `LOW`, `MEDIUM`, or `HIGH`, a `category` of `PLASTIC`, `GLASS`, `METAL`, `LIQUIDS`, or `OTHER`, and an optional free-text `note`. The tag records the `pickup_id` of the tagged pickup and a denormalized `subscription_id` for filtering, captures the caller's `X-User-ID` as `tagged_by_driver_id`, and opens in `TAGGED` status with `surcharge_cents`, `resolved_by`, and `resolved_at` all unset. A pickup may carry only one open tag — open meaning `TAGGED` or `DISPUTED` — so a second tag on a pickup that already has one is rejected with `ERR_TAG_ALREADY_OPEN`. The tag list endpoint accepts optional filters on `pickup_id`, `subscription_id`, and `status`.

Tagging lands differently depending on the pickup's state. On a `SCHEDULED` pickup — any other non-completed state is rejected with `ERR_PICKUP_NOT_ACTIONABLE` — the pickup transitions to `REJECTED_CONTAMINATION` and the bin is left with the customer: no swap occurs and no credit is earned. On a `COMPLETED` pickup, the facility-discovery case, the pickup keeps its `COMPLETED` status but the credit it earned is forfeited: a `REVERSAL` entry negating that pickup's `EARNED_ESTIMATED` amount is posted against the subscriber's balance whenever the earned amount is nonzero. Once a weigh ticket has been posted for the pickup's route and date, a credit-forfeiting tag on that completed pickup is rejected with `ERR_PICKUP_LOCKED_BY_WEIGH_TICKET`.

The subscriber may dispute an open tag on their own account, moving it from `TAGGED` to `DISPUTED`; a tag in any other state is rejected with `ERR_TAG_NOT_RESOLVABLE`. Resolution belongs exclusively to an `OperationsManager`, and both resolution paths are guarded by segregation of duties: the resolving caller's `X-User-ID` must differ from the tag's `tagged_by_driver_id`, otherwise the request is rejected with `ERR_SEGREGATION_OF_DUTIES` — even when one person holds both the driver and the operations grants, they may not resolve a tag they filed. Both confirmation and waiver accept a tag in either `TAGGED` or `DISPUTED`, otherwise `ERR_TAG_NOT_RESOLVABLE`, and a disputed tag resolves with exactly the same effects as one confirmed or waived directly from `TAGGED`.

Confirming a tag prices the contamination and advances the strike machinery. The `surcharge_cents` is stamped as the severity base — 500 cents for `LOW`, 1000 for `MEDIUM`, 1500 for `HIGH` — multiplied by the subscriber-type multiplier, 1.0 for `RESIDENTIAL` and 2.0 for `COMMERCIAL`, multiplied in turn by an escalator of one plus one half times the smaller of the subscription's strike count immediately before this confirmation and three; the product is rounded half-up to integer cents. The tag's `resolved_at` is set to the logical now and `resolved_by` to the resolving operator's `X-User-ID`. Then the cascade runs: the subscription's `strike_count` increments by one; if that count then stands at three or more, an `ACTIVE` subscription transitions to `SUSPENDED`; and suspension cancels every `SCHEDULED` pickup of the subscription into `CANCELLED_SYSTEM`. `SUSPENDED` is absorbing — the only way out is cancellation — and the tag's `version` increments.

Waiving a tag is the lenient branch. No strike is recorded, `surcharge_cents` remains unset, and `resolved_at` and `resolved_by` are stamped as on confirmation. If the tagged pickup sits in `REJECTED_CONTAMINATION`, it returns to `SCHEDULED` for a make-up attempt — completing it after the original service date is allowed. And if the pickup's credit was forfeited by an earlier `REVERSAL`, the waiver posts a `MANUAL_ADJUSTMENT` entry restoring the forfeited amount with the reason `TAG_WAIVED_CREDIT_RESTORE`. The tag's `version` increments here as well.

### 3.7. Weigh Tickets and the Reconciliation of Credits

When a route's load crosses the facility scale, a `Driver` or `OperationsManager` posts a **Weigh Ticket** for the route and a supplied `service_date`, recording the `gross_kg` scale reading and the `tare_kg` vehicle tare. The ticket's `net_kg` is the gross minus the tare and must be greater than zero, otherwise the posting is rejected with `ERR_INVALID_WEIGHT`. Only one ticket may exist for a given route and service date — a second posting is rejected with `ERR_DUPLICATE_WEIGH_TICKET` — and once created the ticket sits in `POSTED`, its only state: ticket posting is final. The ticket list endpoint accepts an optional `route_id` filter.

Posting the ticket allocates the weighed truth across the day's completed stops. The allocation set is every `COMPLETED` pickup of that route and date whose `estimated_kg` is greater than zero, and there must be at least one, otherwise `ERR_INVALID_WEIGHT`. Each included pickup receives a `final_kg` equal to the ticket's `net_kg` multiplied by the pickup's own `estimated_kg` divided by the sum of `estimated_kg` across the whole set, rounded half-up to two decimal places. Because per-pickup rounding drifts, the remainder — the `net_kg` minus the sum of the allocated `final_kg` values, itself rounded half-up to two decimal places — is added to the pickup with the largest `estimated_kg`; a tie is broken in favor of the pickup created earliest.

With final kilograms fixed, the ledger reconciles. Each allocated pickup's final credit is its `final_kg` multiplied by its plan's `credit_rate_cents_per_kg` and by the seasonal multiplier of the service date, rounded half-up to integer cents; the delta between that final credit and the pickup's earlier `EARNED_ESTIMATED` amount is posted, whenever nonzero, as an `EARNED_FINAL_ADJUSTMENT` entry carrying the signed delta. Every affected subscriber's `credit_balance_cents` is then recomputed as the sum of all their signed entries. This weighed variant of the diversion credit replaces the driver's curb estimate with scale truth, which is why the same pickup data yields different cents before and after the ticket.

A completed pickup can still be voided by an `OperationsManager`, but only while no weigh ticket exists for its route and date — once the ticket is posted the void is rejected with `ERR_PICKUP_LOCKED_BY_WEIGH_TICKET`, and any other from-state is rejected with `ERR_PICKUP_NOT_ACTIONABLE`. Voiding moves the pickup to `VOIDED` and, whenever the earned amount is nonzero, posts a `REVERSAL` entry negating the pickup's `EARNED_ESTIMATED` amount — unless that credit was already forfeited by a facility tag under §3.6, in which case the void posts no second `REVERSAL` — so a completion followed by a void nets the subscriber's balance to zero drift. The physical swap is deliberately not undone: the bins stay exactly as the completion left them. The pickup's `version` increments.

### 3.8. Finished Compost: Redemptions, Stock, and Diversion Impact

Collected organics come back to subscribers as finished compost, and the system tracks that stock continuously. The `produced_kg` is thirty percent of everything ever weighed — the sum of `final_kg` across all pickups that have one — rounded half-up to two decimal places. The `redeemed_kg` is the sum of `total_kg` over all redemptions in `FULFILLED`, and the `reserved_kg` is the same sum over redemptions still `REQUESTED`. The `available_kg` is what remains: produced minus redeemed minus reserved. This stock view is readable by `Subscriber`, `Driver`, and `OperationsManager` callers and reports exactly those four quantities.

A redemption request is opened with a `subscriber_id` and a count of `bags`, an integer of at least one, otherwise `ERR_INVALID_REQUEST`. Each bag is ten kilograms of finished compost priced at five hundred cents, so the request's `total_kg` is the bag count multiplied by ten and its `total_cents` the bag count multiplied by five hundred. Four gates guard creation, in the order of §2.10: the subscriber must hold an `ACTIVE` subscription, otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`; the subscriber must be in `GOOD_STANDING`, otherwise `ERR_ACCOUNT_DELINQUENT`; the subscriber's `credit_balance_cents` must cover the `total_cents`, otherwise `ERR_INSUFFICIENT_CREDIT`; and the requested `total_kg` must not exceed the `available_kg` — a request exactly equal to the available stock is allowed — otherwise `ERR_INSUFFICIENT_STOCK`. A successful request opens in `REQUESTED`; the stock is reserved at creation, but no credit is debited yet. The redemption list endpoint accepts optional filters on `subscriber_id` and `status`.

Fulfillment is an `OperationsManager` action on a `REQUESTED` redemption — any other status is rejected with `ERR_REDEMPTION_NOT_FULFILLABLE`. Because time may have passed since the request, the balance is re-checked at fulfill time: the subscriber's `credit_balance_cents` must still cover the `total_cents`, otherwise `ERR_INSUFFICIENT_CREDIT`. On success the system posts a `REDEMPTION_DEBIT` entry of negative `total_cents` with the `redemption_id` set, the subscriber's balance falls by that amount, the reserved stock converts to redeemed, the redemption moves to `FULFILLED`, and its `version` increments. Cancelling a pending request — by the owning subscriber or an `OperationsManager` — likewise requires `REQUESTED`, otherwise `ERR_REDEMPTION_NOT_FULFILLABLE`; it releases the stock reservation, takes no debit because none was ever taken, moves the redemption to `CANCELLED`, and increments its `version`.

Operators can also correct a balance directly. Posting a credit adjustment takes a signed, nonzero `amount_cents` — a zero adjustment is rejected with `ERR_INVALID_REQUEST` — and an operator `reason` — a missing `reason` is likewise rejected with `ERR_INVALID_REQUEST` — and creates a `MANUAL_ADJUSTMENT` entry that shifts `credit_balance_cents` by the supplied amount. If the result would take the balance below zero, the adjustment is rejected with `ERR_INSUFFICIENT_CREDIT`.

Finally, the diversion story is reported per subscriber through an impact report readable by the subscriber themselves or an `OperationsManager`. Across all `COMPLETED` pickups of the subscriber's subscriptions, each pickup contributes its `final_kg` once weighed and its `estimated_kg` otherwise. The report's `total_kg_diverted` is the sum of those kilograms rounded half-up to two decimal places, and `total_co2e_kg` is that total multiplied by one half kilogram of CO2-equivalent per diverted kilogram, again rounded half-up to two decimal places. The report also counts `pickups_completed` — the number of those completed pickups — and `contamination_tags_confirmed`, the number of the subscriber's tags standing in `CONFIRMED`.

### 3.9. Weekly Billing, Invoices, and Account Standing

Billing runs weekly at the hand of an `OperationsManager`, who supplies a `week_start_date`; the date must be a Monday, otherwise the run is rejected with `ERR_INVALID_REQUEST`. The billed window is the seven-day half-open span beginning on that Monday, and the run produces at most one invoice per subscriber with billable activity inside it. One gate stands in front of the whole run: every `COMPLETED` pickup of a `COMMERCIAL` subscription in the week must already have a posted weigh ticket for its route and service date — metered billing cannot proceed on estimates — and if any such pickup is missing its ticket, the entire run aborts with `ERR_WEIGH_TICKET_PENDING`.

Each invoice assembles its `lines` — one charge line per subscription, per pickup whose `service_date` falls in the week — and every line carries a `line_type`, a `reference_id`, and an integer `amount_cents`. For a residential plan, a pickup in `COMPLETED` or `REJECTED_CONTAMINATION` produces a `WEEKLY_FLAT` line at the plan's `weekly_price_cents`, while a pickup in `SKIPPED`, `MISSED`, `CANCELLED_SYSTEM`, or `VOIDED` produces no line at all. For a commercial plan, a `COMPLETED` pickup produces a `METERED_BASE` line at the plan's `metered_base_cents` plus — only when the pickup's `final_kg` exceeds the plan's `included_kg_per_week` — an `OVERAGE_KG` line amounting to the plan's `per_kg_rate_cents` multiplied by the excess of `final_kg` over `included_kg_per_week`, rounded half-up to integer cents. A commercial pickup in `REJECTED_CONTAMINATION` produces the `METERED_BASE` line only, because the service was attempted and the subscriber was at fault; `SKIPPED`, `MISSED`, `CANCELLED_SYSTEM`, and `VOIDED` produce no line, exactly as for residential. Surcharges join the same invoice: every contamination tag of the subscriber standing in `CONFIRMED` whose `resolved_at` falls within the week contributes a `CONTAMINATION_SURCHARGE` line at the tag's `surcharge_cents`.

Rounding order is pinned. Every line amount is an integer computed in isolation — round half-up per line — and the invoice's `subtotal_cents` is the sum of those integer line amounts; the system never sums unrounded amounts and rounds once at the end. Credits then apply in a fixed order that breaks the circular dependency between cap and total: first the `subtotal_cents` is fixed as above; then `credit_applied_cents` is the smaller of the subscriber's current `credit_balance_cents` and one half of the subtotal rounded down to a whole cent; then `total_cents` is the subtotal minus the applied credit. When the applied credit is greater than zero, an `INVOICE_APPLICATION_DEBIT` entry of negative `credit_applied_cents` with the `invoice_id` set is posted and the subscriber's balance decreases immediately. The invoice's `due_date` is fourteen days after the `week_start_date`, and the invoice is born `ISSUED`. No invoice is created for a subscriber whose subtotal is zero. The run is idempotent per subscriber and week: a rerun skips pairs already invoiced and reports them in `skipped_subscriber_ids`, and the run's response carries the `issued_count`, the list of `invoice_ids`, and that `skipped_subscriber_ids` list. Invoices are browsable through a list endpoint with optional filters on `subscriber_id` and `status`, and individual invoices can be read.

Settling an invoice is open to the owning subscriber or an `OperationsManager`: paying requires the invoice to be `ISSUED`, otherwise `ERR_INVOICE_NOT_PAYABLE`, and moves it to `PAID`, incrementing its `version`; the subscriber's standing then recomputes on the next read because this invoice no longer counts as overdue. An `OperationsManager` may instead void an `ISSUED` invoice — same gate, same `ERR_INVOICE_NOT_PAYABLE` — moving it to `VOID`; if the invoice had consumed credits, meaning its `credit_applied_cents` is greater than zero, a `REVERSAL` entry of positive `credit_applied_cents` with the `invoice_id` set restores the subscriber's balance, and the invoice's `version` increments. Both `PAID` and `VOID` are terminal.

Account standing closes the loop. A subscriber is `DELINQUENT` whenever any of their invoices stands `ISSUED` with a `due_date` earlier than the current logical date, and `GOOD_STANDING` otherwise; the value is derived on read, never stored. Delinquency is the fiscal brake of §2.10: it blocks pausing and resuming a subscription and opening a redemption request, each rejected with `ERR_ACCOUNT_DELINQUENT`, until the overdue invoice is paid or voided.

## 4. Endpoint Definitions

Operations that create a new resource — a plan, subscriber, subscription, route, bin, contamination tag, weigh ticket, redemption, or credit adjustment — return `201 Created`. Operations that modify an existing resource, perform a state transition, run a batch action such as stop generation or the weekly billing run, or simply read data return `200 OK`. The table below is a contract summary only; request fields, side effects, and validation order are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-plans` | Create a service plan (config) | OperationsManager |
| GET | `/service-plans/{id}` | Read a service plan | Subscriber, OperationsManager |
| POST | `/subscribers` | Self-signup a subscriber | Anonymous |
| GET | `/subscribers/{id}` | Read a subscriber (own or ops) | Subscriber, OperationsManager |
| GET | `/subscribers/{id}/impact` | Diversion and impact report | Subscriber, OperationsManager |
| POST | `/subscribers/{id}/credit-adjustments` | Post a manual signed credit adjustment | OperationsManager |
| POST | `/subscriptions` | Create a subscription (assigns bins, checks route capacity) | Subscriber, OperationsManager |
| GET | `/subscriptions` | List subscriptions with optional filters | Subscriber, OperationsManager |
| GET | `/subscriptions/{id}` | Read a subscription | Subscriber, OperationsManager |
| POST | `/subscriptions/{id}/pause` | Pause service over a half-open window | Subscriber, OperationsManager |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | Subscriber, OperationsManager |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription and return its bins | Subscriber, OperationsManager |
| POST | `/subscriptions/{id}/plan-change` | Replace the plan (OCC-guarded) | Subscriber, OperationsManager |
| POST | `/routes` | Create a weekly route | OperationsManager |
| GET | `/routes/{id}` | Read a route | Driver, OperationsManager |
| POST | `/routes/{id}/generate-stops` | Generate the week's pickup events for the route | OperationsManager |
| POST | `/routes/{id}/weigh-tickets` | Post the facility weigh-in for a route and date | Driver, OperationsManager |
| POST | `/bins` | Register a bin into the depot fleet | OperationsManager |
| GET | `/bins` | List bins with optional filters | Driver, OperationsManager |
| GET | `/bins/{id}` | Read a bin | Driver, OperationsManager |
| POST | `/bins/{id}/wash` | Wash a returned bin back to clean | OperationsManager |
| GET | `/pickups` | List pickups with optional filters | Subscriber, Driver, OperationsManager |
| GET | `/pickups/{id}` | Read a pickup | Subscriber, Driver, OperationsManager |
| POST | `/pickups/{id}/complete` | Driver completes a stop (fullness, swap, estimated credit) | Driver |
| POST | `/pickups/{id}/miss` | Driver marks a stop missed | Driver |
| POST | `/pickups/{id}/skip` | Subscriber skips a stop before the cutoff | Subscriber |
| POST | `/pickups/{id}/void` | Void a completed pickup before its weigh ticket | OperationsManager |
| POST | `/pickups/{id}/contamination-tags` | Driver files a contamination tag on a pickup | Driver |
| GET | `/contamination-tags` | List contamination tags with optional filters | Subscriber, Driver, OperationsManager |
| GET | `/contamination-tags/{id}` | Read a contamination tag | Subscriber, Driver, OperationsManager |
| POST | `/contamination-tags/{id}/dispute` | Subscriber disputes an open tag | Subscriber |
| POST | `/contamination-tags/{id}/confirm` | Operations confirms a tag (never the tagging driver) | OperationsManager |
| POST | `/contamination-tags/{id}/waive` | Operations waives a tag (never the tagging driver) | OperationsManager |
| GET | `/weigh-tickets` | List weigh tickets with optional route filter | Driver, OperationsManager |
| GET | `/weigh-tickets/{id}` | Read a weigh ticket | Driver, OperationsManager |
| GET | `/credit-entries` | List credit ledger entries with optional filters | Subscriber, OperationsManager |
| GET | `/credit-entries/{id}` | Read a single ledger entry | Subscriber, OperationsManager |
| POST | `/credit-redemptions` | Request finished-compost bags (reserves stock) | Subscriber, OperationsManager |
| GET | `/credit-redemptions` | List redemptions with optional filters | Subscriber, OperationsManager |
| GET | `/credit-redemptions/{id}` | Read a redemption | Subscriber, OperationsManager |
| POST | `/credit-redemptions/{id}/fulfill` | Fulfill a redemption request (debits credit) | OperationsManager |
| POST | `/credit-redemptions/{id}/cancel` | Cancel a pending redemption (releases stock) | Subscriber, OperationsManager |
| GET | `/compost-stock` | Read the finished-compost stock position | Subscriber, Driver, OperationsManager |
| POST | `/billing/run` | Run weekly billing for a Monday week start | OperationsManager |
| GET | `/invoices` | List invoices with optional filters | Subscriber, OperationsManager |
| GET | `/invoices/{id}` | Read an invoice | Subscriber, OperationsManager |
| POST | `/invoices/{id}/pay` | Pay an issued invoice | Subscriber, OperationsManager |
| POST | `/invoices/{id}/void` | Void an issued invoice (restores applied credit) | OperationsManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | OperationsManager |

## 5. Error Code Catalogue

The catalogue below lists every error identifier with its HTTP status. Trigger conditions are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SUBSCRIPTION_STATE_CONFLICT` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PICKUP_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_TAG_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_REDEMPTION_NOT_FULFILLABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_DELINQUENT` | 402 Payment Required |
| `ERR_INSUFFICIENT_CREDIT` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_SKIP_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ROUTE_CAPACITY` | 422 Unprocessable Entity |
| `ERR_NO_BIN_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_PLAN_DOWNGRADE_BLOCKED` | 422 Unprocessable Entity |
| `ERR_TAG_ALREADY_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_WEIGH_TICKET` | 409 Conflict |
| `ERR_INVALID_WEIGHT` | 422 Unprocessable Entity |
| `ERR_PICKUP_LOCKED_BY_WEIGH_TICKET` | 409 Conflict |
| `ERR_SKIP_CUTOFF_PASSED` | 422 Unprocessable Entity |
| `ERR_PAUSE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_SERVICE_DATE_WEEKDAY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WEIGH_TICKET_PENDING` | 422 Unprocessable Entity |

# Boat Manufacturing & Dealer Allocation API — Product Requirements Document

## 1. Introduction

A Brunswick-style recreational boat builder operates a seasonal production model: the catalog of hull models and factory options is fixed per model year, plant capacity is organized into one-week production runs broken into hour-budgeted build slots, and a franchised dealer network books orders against a manufacturer-administered annual allocation quota. Dealers finance delivered inventory through floor-plan credit lines whose interest rate floats with each dealer's credit utilization, while the manufacturer carries the cost of finished-but-undelivered boats at the plant, weighted by the production season. Around this commercial core sit the regulatory obligations of the marine industry: every completed hull receives a hull identification number, build certification is segregated from production reporting, retail sales open thirty-six-month warranty coverage, and safety recalls freeze affected certified hulls until each one is remedied.

This document specifies the API that orchestrates those workflows end to end — catalog seeding, dealer onboarding, production planning, order booking with a quota-gated waitlist, boat-show demand surges, hull completion and delivery with cascading financing effects, curtailment settlement, warranty adjudication, and recall fan-out. It is written for the engineers who will build the service: §2 fixes the system-wide contracts, §3 narrates the business workflows in which every rule lives, §4 tabulates the HTTP surface, and §5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request with either header missing, empty, or bearing an unrecognized role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The declared roles are `SystemAdmin`, `AllocationManager`, `ProductionPlanner`, `ComplianceOfficer`, `WarrantyAdministrator`, `DealerPrincipal`, and `Any` (the shared read capacity: every authenticated role may call every read endpoint). Performing an operation outside one's role, or — for a `DealerPrincipal` — acting on a dealer other than one's own, is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a dealer compare the resource's dealer foreign key to `X-User-ID` — an order's `dealer_id` on booking, amendment, confirmation, and cancellation; the path dealer id on curtailments; the registration's `dealer_id` at retail registration; and the registration's owning dealer when filing a claim. When `X-User-Role` is `SystemAdmin`, `AllocationManager`, `ComplianceOfficer`, or `WarrantyAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`. When `X-User-Role` is `ProductionPlanner`, `X-User-ID` is likewise opaque, with one recorded use: it is stamped onto each hull as `created_by_user_id` at production completion, where it later anchors the segregation-of-duties check at certification.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource, including mutations caused by a cascade originating elsewhere. `version` is an integer that starts at 1 when the resource is created and increments by one on every mutation, again including cascaded ones. One entity deviates: an `OrderOptionLine` is immutable once written and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock

All temporal rules in this system — option-change cutoffs, boat-show windows, the retail registration window, warranty coverage expiry, interest day counts, and carrying-cost day counts — evaluate against a server-side logical clock, never against wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it must never fall back to the host's wall clock. A `SystemAdmin`-only test-driving capability advances the clock by supplying a `to_iso8601` instant; monotonicity is not enforced, so any instant may be set.

### 2.6. Money, Rates, and Rounding

All monetary values are integer cents. Every rounding in the system rounds half up. Where a calculation involves per-component rounding — option line totals before the options sum, the logistics surcharge after the subtotal, the labor and parts components of a claim before their sum, each curtailment's interest settlement — the rounding order is pinned exactly as the relevant workflow in §3 states; reordering roundings (for example, summing unrounded line amounts and rounding once) is a rejected alternative.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to a parent entity's `version`:

- Amending an order (`PATCH /dealer-orders/{id}`) requires a non-optional `expected_order_version` carrying the client's last observed `version` of that order. If the order's current `version` has advanced past the supplied value — because another amendment, a promotion, or a lifecycle transition landed in between — the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412).
- Updating a dealer's quota, floor-plan limit, or standing (`PATCH /dealers/{id}`) requires a non-optional `expected_dealer_version`. A mismatch with the dealer's current `version` is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412), so quota and limit changes are never based on superseded utilization state.
- Posting a curtailment (`POST /dealers/{id}/curtailments`) likewise requires `expected_dealer_version`; a stale value is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412), forcing a re-read before the payment waterfall is applied against balances the client never observed.

Endpoints not listed here do not accept a version field.

### 2.8. Cascading Consistency and Recomputed Counters

A single business operation may mutate several resources in one atomic cascade — delivering a hull touches the hull, its order, a new floor-plan advance, and the dealer; cancelling a booked order touches the order, its slot, the dealer, and at most one promoted waitlisted order. Every resource touched by such a cascade is itself mutated: its `updated_at` refreshes and its `version` increments by one.

Derived counters are always recomputed from their source rows, never incrementally guessed. A dealer's `allocation_used` is recounted from that dealer's orders on every order status change; a dealer's `floor_plan_utilized_cents` is the sum of `outstanding_principal_cents` over that dealer's `OPEN` advances, re-established on every advance opening and curtailment; a dealer's `current_rate_tier` is re-derived from the resulting utilization ratio on the same events (and when the floor-plan limit itself changes); a slot's `reserved_hours` is the sum of `production_hours` of the orders occupying it in the pipeline states. The exact membership of each derivation is defined in §3 alongside the workflow that maintains it.

### 2.9. Request Validation Pipeline and Error Ordering

Inbound requests are validated against eleven families of rules, evaluated in the fixed priority order below; a failure in an earlier family surfaces its error and masks every later check.

1. Authentication context: both headers present, non-empty, and the role declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Authorization: the role is permitted for the endpoint, and for `DealerPrincipal` writes the acting user owns the dealer in question — otherwise `ERR_INSUFFICIENT_PERMISSIONS`.
3. Body schema and field domains: required fields present; enum values valid; dates well-formed with start not after end; a production run's `build_week_end` exactly seven days after its `build_week_start`; amounts non-negative; `hin_serial_start` not greater than `hin_serial_end`; a `BOAT_SHOW`-sourced order carries a `show_event_id` while other sources must not; `option_package_ids`, when provided on an amendment, is non-empty; and no duplicate option identifiers appear within one order — any violation is `ERR_INVALID_REQUEST`.
4. Path identifiers exist, validated left to right along the URL — the first missing resource yields its `ERR_{RESOURCE}_NOT_FOUND`: `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, or `ERR_MODEL_NOT_FOUND`.
5. Body-referenced foreign keys exist — `model_id`, `dealer_id`, `slot_id`, `show_event_id`, `run_id`, `order_id`, `hull_id`, `registration_id`, `recall_notice_id`, each element of `option_package_ids`, and `incompatible_with_option_id` — otherwise the corresponding `ERR_MODEL_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_SHOW_EVENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or `ERR_OPTION_NOT_FOUND`.
6. Optimistic concurrency: `expected_order_version` / `expected_dealer_version` match the parent's current `version` — otherwise `ERR_STALE_ORDER_VERSION` or `ERR_STALE_DEALER_VERSION`.
7. Entity state preconditions, including cross-entity ones: the ordered model is `ORDERABLE` (`ERR_MODEL_NOT_ORDERABLE`); the run is `OPEN` for bookings, slot creation, and close (`ERR_RUN_NOT_OPEN`); the order's state permits confirm, cancel, amendment, or hull creation (`ERR_INVALID_ORDER_STATE`); no hull already exists for the order (`ERR_HULL_ALREADY_EXISTS`); the hull's dimensions permit certify or deliver (`ERR_INVALID_HULL_STATE`); the claim is `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`); the campaign is `DRAFT` (`ERR_CAMPAIGN_NOT_DRAFT`); the notice is `NOTIFIED` (`ERR_INVALID_NOTICE_STATE`).
8. Safety duties: certification is segregated from hull creation (`ERR_SEGREGATION_OF_DUTY`); delivery is blocked under a recall hold (`ERR_HULL_RECALL_HOLD`) and without certification (`ERR_HULL_NOT_CERTIFIED`).
9. Temporal business rules: amendment before the option cutoff (`ERR_OPTION_CUTOFF_PASSED`); a show order created inside its event window (`ERR_SHOW_EVENT_NOT_ACTIVE`); retail registration inside the 45-day window and not in the future (`ERR_REGISTRATION_WINDOW_EXPIRED`); a claim inside coverage unless recall-linked (`ERR_COVERAGE_EXPIRED`).
10. Structural business constraints: no overlapping half-open run windows on the same plant line (`ERR_LINE_WINDOW_OVERLAP`); no overlapping closed show windows in the same region (`ERR_SHOW_WINDOW_OVERLAP`); option compatibility and model match (`ERR_OPTION_INCOMPATIBLE`); one registration per hull (`ERR_DUPLICATE_REGISTRATION`); registration dealer matches the delivered order's dealer (`ERR_SELLING_DEALER_MISMATCH`); a claim's recall notice belongs to the registration's hull (`ERR_RECALL_NOTICE_MISMATCH`).
11. Fiscal guards: dealer quota headroom (`ERR_QUOTA_EXCEEDED`); slot hours capacity (`ERR_SLOT_CAPACITY_EXCEEDED`); deposit covers the required amount (`ERR_DEPOSIT_INSUFFICIENT`); floor-plan headroom at delivery (`ERR_FLOOR_PLAN_LIMIT_EXCEEDED`); a curtailment not exceeding the total due (`ERR_CURTAILMENT_EXCEEDS_BALANCE`).

## 3. Business Logic & Workflows

### 3.1. Catalog Management: Models and Option Packages

A `SystemAdmin` seeds the catalog before any selling season begins. Registering a boat model takes a `model_code` (unique across all models, e.g. SP190), a `model_name`, a `model_year`, a `base_price_cents` strictly greater than zero — the MSRP base, which dealer standing never discounts — a `length_feet`, and the `production_hours` strictly greater than zero that one boat of this model consumes on the line. The model's `status` is set at creation and is immutable thereafter: it defaults to `ORDERABLE` when omitted, or may be seeded directly as `DISCONTINUED` for catalog cleanup. Orders referencing a `DISCONTINUED` model are refused with `ERR_MODEL_NOT_ORDERABLE`. The model collection can be listed with an optional `status` filter.

Option packages hang off models through the `model_id` supplied at registration. Each carries a unique `option_code` (e.g. WAKE-TOWER), a display `name`, a `price_cents` strictly greater than zero, and the additional `production_hours` the option adds to a build (zero or more). An option may declare a self-referential `incompatible_with_option_id`; incompatibility is symmetric, so if option A declares B, then B is treated as incompatible with A even though B's own row says nothing. The options collection supports reverse lookups by `model_id` or by `incompatible_with_option_id`.

### 3.2. Dealer Onboarding, Standing, and the Show Calendar

An `AllocationManager` onboards each dealership with a unique `dealer_code`, a `name`, a sales `region` code such as SE or NW, an `annual_allocation_quota` of zero or more, and a `floor_plan_limit_cents` strictly greater than zero. The dealer's `standing` may be supplied as `PREFERRED`, `STANDARD`, or `PROBATION` and defaults to `STANDARD`. Onboarding zeroes the computed fields: `allocation_used` starts at 0, `floor_plan_utilized_cents` at 0, and `current_rate_tier` at `TIER_STANDARD`.

Standing is the dealer's commercial grade and moves two levers at once: the discount captured on each option line (ten percent for `PREFERRED`, five percent for `STANDARD`, nothing for `PROBATION`) and the deposit-rate delta described in §3.4. The allocation desk may later revise a dealer's `annual_allocation_quota`, `floor_plan_limit_cents`, or `standing`; such an update must carry `expected_dealer_version`, increments the dealer's `version` by one, and re-derives `current_rate_tier` whenever the limit changes. Because bookings, deliveries, and curtailments all advance the dealer's `version` as side effects, a client holding an old read is refused with `ERR_STALE_DEALER_VERSION` rather than allowed to write quota policy over utilization it never saw.

The same desk maintains the boat-show calendar. Registering a show takes an `event_name`, the `region` it occupies, a `start_date` and an `end_date` with the end no earlier than the start — the window is closed, inclusive of both days — a `surge_deposit_rate` such as 0.05 that becomes the base deposit rate for show-sourced orders placed inside the window, and an `allocation_boost` that marks orders tied to the event for priority waitlist treatment while the clock is inside it. Two shows in the same region may not overlap on their closed windows — sharing even a single day is a conflict — and such a registration is rejected with `ERR_SHOW_WINDOW_OVERLAP`. Shows can be listed with an optional `region` filter.

### 3.3. Production Planning: Runs, Slots, and the Season Close

A `ProductionPlanner` opens production capacity one week at a time. Creating a run names the `plant_line_code`, declares the `season` as `PEAK`, `SHOULDER`, or `OFF_PEAK` (this choice drives the seasonal carrying-cost weighting at close), and fixes the build week: `build_week_end` must fall exactly seven days after `build_week_start`, and the run occupies the half-open window from `build_week_start` up to but not including `build_week_end`. The run also carries `option_change_cutoff_at`, the UTC instant after which option amendments on allocated orders are rejected; the cutoff must not be later than the end of the final build day. Two runs on the same plant line may not have overlapping half-open windows — adjacent runs where one's end equals the other's start are permitted — and a colliding registration fails with `ERR_LINE_WINDOW_OVERLAP`. A new run is `OPEN` with both carrying totals zeroed; the run collection can be filtered by `plant_line_code` or `status`.

Within an `OPEN` run — and only an `OPEN` one, else `ERR_RUN_NOT_OPEN` — the planner adds build slots, each with a `run_id` pointing at its run, a `slot_code` unique within that run, and `capacity_hours` strictly greater than zero. A slot is born `OPEN` with `reserved_hours` at 0; the slots collection can be filtered by `run_id`. While orders occupy it, `reserved_hours` always equals the summed `production_hours` of that slot's orders in `ALLOCATED`, `COMMITTED`, or `IN_PRODUCTION` — a conservation invariant every booking, amendment, cancellation, and promotion re-establishes rather than approximates.

Closing a run is the season checkpoint, performed by a `ProductionPlanner` and permitted only while the run is `OPEN` (a second close, or any close of a `CLOSED` run, draws `ERR_RUN_NOT_OPEN`). Close performs four acts. First, carrying accrual: for every hull sitting on one of this run's slots whose `delivery_status` is still `AT_PLANT`, the system counts the whole days from the hull's `completed_at` to the clock (zero when completion and close share a day), computes the actual carrying cost as those days times 750 cents per day, and computes the season-weighted cost as the actual cost times the season factor — 1.25 for `PEAK`, 1.00 for `SHOULDER`, 0.60 for `OFF_PEAK` — rounded half up. The run's `total_carrying_actual_cents` records the sum of the unweighted actual costs (the planning and statement view), its `total_carrying_seasonal_cents` the sum of the weighted costs, and each hull's `carrying_cost_cents` accumulates the weighted amount — the season-weighted variant is the one persisted to the inventory-carrying ledger. Delivered hulls are excluded; if no hull is still at the plant, both totals land at 0 and no error is raised. Second, every slot of the run transitions to `RELEASED` — a terminal state whose slots reject all new bookings — with each slot's `version` incremented. Third, every order still `ALLOCATED` on this run's slots is cancelled by the season rollover with `cancel_fee_cents` of 0 and a full refund of its deposit; unlike an ordinary cancellation, no waitlist promotion fires at close. Fourth, `COMMITTED` orders on the run persist untouched and may still report production completion afterwards — hull creation deliberately does not require the run to be `OPEN`. The run records `closed_at` from the clock and its `version` increments.

### 3.4. Booking Dealer Orders and Managing the Waitlist

A `DealerPrincipal` books an order with a payload naming the `dealer_id` — which must equal the caller's `X-User-ID` — the `model_id`, the order `source` (`RETAIL`, `FLEET`, or `BOAT_SHOW`), the `deposit_paid_cents` tendered (zero or more), and the chosen `option_package_ids`. A `slot_id` may be supplied to target a specific slot; a `show_event_id` is required when and only when the source is `BOAT_SHOW` — supplying one for a `RETAIL` or `FLEET` order, or omitting it for a show order, is an `ERR_INVALID_REQUEST` — and repeating the same option identifier twice within one order is likewise an `ERR_INVALID_REQUEST`. A show-sourced order must be created while the clock date falls inside its event's closed window, first day through last day inclusive; outside it the booking fails with `ERR_SHOW_EVENT_NOT_ACTIVE`.

Pricing is computed at booking and the rounding order is pinned. The order's `base_price_cents` is a snapshot of the model's base price taken at creation — a price lock that later amendments reuse rather than re-read. Each chosen option becomes an `OrderOptionLine` whose `unit_price_cents` snapshots the option's price at line creation and whose `discount_pct_applied` captures the dealer's standing at that moment (0.10 for `PREFERRED`, 0.05 for `STANDARD`, 0.00 for `PROBATION`). Every `line_total_cents` is its unit price times one minus the captured discount, rounded half up per line. The order's `options_total_cents` is the sum of those already-rounded line totals — summing raw amounts and rounding once is a rejected alternative. The `surcharge_cents` is three percent of base plus options, rounded half up; note the base price itself is never discounted. The `invoice_total_cents` is base plus options plus surcharge, and the order's `production_hours` is the model's base hours plus the hours of every chosen option.

The required deposit is computed alongside. The base rate depends on `source`: 0.10 for `RETAIL`, 0.15 for `FLEET`, and the event's `surge_deposit_rate` for a `BOAT_SHOW` order. Standing shifts that rate by −0.02 for `PREFERRED`, 0.00 for `STANDARD`, and +0.05 for `PROBATION`; the effective rate is the sum, but never less than a 0.03 floor. The `required_deposit_cents` is the invoice total times the effective rate, rounded half up, and then raised to a 50000-cent minimum if below it. The tendered `deposit_paid_cents` must be at least the required amount at booking, amendment, and confirmation alike; shortfalls are refused with `ERR_DEPOSIT_INSUFFICIENT`.

Slot securing decides the order's initial state. With an explicit `slot_id`, the chosen slot's run must be `OPEN` and the slot itself `OPEN`, otherwise `ERR_RUN_NOT_OPEN`; the fit check then requires the slot's `reserved_hours` plus the order's `production_hours` to be no greater than `capacity_hours` — landing exactly at capacity is allowed, exceeding it draws `ERR_SLOT_CAPACITY_EXCEEDED`. When `slot_id` is omitted, the system attempts automatic placement: among all slots of `OPEN` runs that are themselves `OPEN` and have enough free hours, ranked by their run's `build_week_start` ascending and then `slot_code` ascending. Either way, the dealer must have quota headroom: `allocation_used` must be strictly below `annual_allocation_quota`, with equality rejecting as `ERR_QUOTA_EXCEEDED` — a dealer one below quota books successfully and lands exactly at quota. A secured slot puts the order straight into `ALLOCATED`: the slot's `reserved_hours` grows by the order's hours with its `version` and `updated_at` refreshed, the dealer's `allocation_used` is recounted and `version` incremented, and the order is born at `version` 1. When no slot fits, the order lands in `WAITLISTED` with `slot_id` null — the quota gate does not apply to waitlisted entries, which by definition hold no committed production. The orders collection supports reverse-channel filters by `dealer_id`, `model_id`, `slot_id`, `show_event_id`, or `status`.

### 3.5. Amending, Confirming, and Cancelling Orders

Amendment is a self-loop available only from `WAITLISTED` and `ALLOCATED`; attempting it from `COMMITTED`, `IN_PRODUCTION`, `DELIVERED`, `RETAILED`, or `CANCELLED` is rejected with `ERR_INVALID_ORDER_STATE`. Every amendment must carry `expected_order_version`, and a value the server has already advanced past is refused with `ERR_STALE_ORDER_VERSION` — this is how a legitimate superseding amendment by another writer is detected instead of silently overwritten. The payload may replace the option set via `option_package_ids` (non-empty when provided) and may update `deposit_paid_cents`; the replacement set is re-checked for compatibility, and a declared incompatible pair — in either direction — or an option belonging to a different model fails with `ERR_OPTION_INCOMPATIBLE`.

The two amendment paths diverge on time and capacity. For an `ALLOCATED` order, the clock must be strictly before the run's `option_change_cutoff_at` — arriving exactly at the cutoff already rejects with `ERR_OPTION_CUTOFF_PASSED` — and the revised build must fit the same slot: the slot's `reserved_hours` minus the order's old hours plus its new hours must not exceed `capacity_hours` (equal is allowed), else `ERR_SLOT_CAPACITY_EXCEEDED`. For a `WAITLISTED` order no cutoff applies at all, since no run is bound. On either path the resulting deposit — newly supplied or carried over — must cover the newly computed `required_deposit_cents`, else `ERR_DEPOSIT_INSUFFICIENT`. A successful amendment atomically replaces the `OrderOptionLine` rows (old lines deleted, new lines written with fresh price and discount snapshots), recomputes `options_total_cents`, `surcharge_cents`, `invoice_total_cents`, `required_deposit_cents`, and `production_hours`, adjusts an allocated slot's `reserved_hours` by the hours delta with the slot's `version` incremented, and increments the order's `version`.

Confirmation moves an order `ALLOCATED` → `COMMITTED`. It requires the order to be `ALLOCATED` — any other state yields `ERR_INVALID_ORDER_STATE` — and re-verifies that `deposit_paid_cents` covers `required_deposit_cents`, failing with `ERR_DEPOSIT_INSUFFICIENT` if a price shift has opened a gap. The order's `version` increments.

Cancellation is tiered by how deep into the pipeline the order sits. From `WAITLISTED` there is no production commitment: `cancel_fee_cents` is 0 and `refund_cents` is the full `deposit_paid_cents`. From `ALLOCATED` the restocking fee is five percent of the invoice total, rounded half up; the slot is released (`reserved_hours` drops by the order's hours and the slot's `version` increments), the dealer's `allocation_used` is recounted down by one with the dealer's `version` incremented, and the freed capacity fires the waitlist promotion described below. From `COMMITTED` the fee is twelve percent of the invoice total, rounded half up, with the same slot release, the same waitlist cascade, and the same dealer recount as the allocated path. For an order whose `source` is `BOAT_SHOW`, either tier's fee is replaced by the larger of the computed percentage fee and the full `deposit_paid_cents` — a show order cancelled after the surge forfeits at least its percentage fee and at most its whole deposit. In all non-waitlisted cases `refund_cents` is the deposit minus the fee, floored at zero, and the order's `version` increments. Cancellation from `IN_PRODUCTION`, `DELIVERED`, `RETAILED`, or an already `CANCELLED` state is rejected with `ERR_INVALID_ORDER_STATE`.

The waitlist promotion runs after a slot release caused by cancelling an `ALLOCATED` or `COMMITTED` order — and only then; the run-close rollover never promotes. The candidate set is every `WAITLISTED` order whose `production_hours` fit the freed slot's available hours after the release and whose dealer's `allocation_used` is still below quota. Candidates rank first by show priority: an order sourced `BOAT_SHOW` whose event's closed window contains the current clock date carries a boost of 1 and outranks all unboosted orders, which carry 0. Within the same boost level, the earliest `created_at` wins; timestamps are unique at millisecond precision, so no further tie-break exists and the `id` is never consulted. Exactly one order is promoted per release event, even if hours remain for more; if the candidate set is empty the slot simply stays `OPEN` with its freed hours and no error is raised. The promoted order transitions `WAITLISTED` → `ALLOCATED` onto the freed slot: the slot's `reserved_hours` grows by its hours with a version increment, its dealer's `allocation_used` is recounted up by one with a dealer version increment, and the promoted order's `version` increments.

### 3.6. Hull Completion, Certification, and Delivery

When the line finishes a boat, a `ProductionPlanner` reports production completion against the order's `order_id`. The order must be `COMMITTED` — any other state, including one whose run has since closed, is refused with `ERR_INVALID_ORDER_STATE` (the pinned exception: completion does not require the run to remain `OPEN`) — and exactly one hull may exist per order, a second attempt drawing `ERR_HULL_ALREADY_EXISTS`. The hull is born `UNCERTIFIED` on its certification dimension and `AT_PLANT` on its delivery dimension; the two dimensions evolve independently, though delivery gates on certification. The hull copies `slot_id` and `model_id` from its order, stamps `completed_at` from the clock, and records the planner's `X-User-ID` as `created_by_user_id`. Completion advances the order `COMMITTED` → `IN_PRODUCTION` with a version increment.

Each hull receives its serial and identification number at creation. `serial_no` is a per-model-and-model-year sequence: the first hull of a given model and `model_year` takes 1, and each subsequent hull takes one more than the highest existing serial for that pair. The `hin` is a twelve-character composition: the manufacturer code `BRW`, then the serial zero-padded to five digits, then a single letter for the completion month — A for January through L for December, with I skipped by construction of the twelve-letter map — then the last digit of the completion year, then the model year modulo 100 zero-padded to two digits. The first hull of model year 2027 completed in August 2026 is therefore `BRW00001H627`, and uniqueness holds per model, model year, and serial.

Certification is a `ComplianceOfficer` act gated by segregation of duties: the hull must be `UNCERTIFIED` (else `ERR_INVALID_HULL_STATE`), and the certifier's `X-User-ID` must differ from the hull's `created_by_user_id` — the planner who reported completion may not certify it, and a matching identity fails with `ERR_SEGREGATION_OF_DUTY`. Success moves `certification_status` `UNCERTIFIED` → `CERTIFIED` and increments the hull's `version`.

Delivery to the dealer is the cascade-rich moment of the lifecycle, performed by a `ProductionPlanner`. Four preconditions hold: the hull's `delivery_status` is still `AT_PLANT` (else `ERR_INVALID_HULL_STATE`); the hull is not under recall hold (`ERR_HULL_RECALL_HOLD`); the hull is `CERTIFIED` (an `UNCERTIFIED` hull draws `ERR_HULL_NOT_CERTIFIED`); and the dealer's floor plan has headroom — `floor_plan_utilized_cents` plus the order's `invoice_total_cents` must not exceed `floor_plan_limit_cents`, with landing exactly at the limit permitted and any excess refused as `ERR_FLOOR_PLAN_LIMIT_EXCEEDED`. Delivery then executes in order. First, a `FloorPlanAdvance` opens: one advance per hull, its `dealer_id` copied from the delivered order, `principal_cents` equal to the order's invoice total, `status` `OPEN`, `opened_at` from the clock, `accrued_interest_cents` at 0, and `last_accrual_date` initialized to the opening date. Its `rate_tier` and `annual_rate` are locked at opening from the utilization ratio that includes this advance (the pinned evaluation in §3.7). Second, the dealer's `floor_plan_utilized_cents` rises by the new principal and the dealer's `version` increments. Third, the dealer's `current_rate_tier` is re-derived from the new ratio. Fourth, the order transitions `IN_PRODUCTION` → `DELIVERED` with a version increment. Finally the hull's `delivery_status` becomes `DELIVERED` (a terminal state), `delivered_at` stamps from the clock, and the hull's `version` increments. Hulls can be listed with `order_id`, `slot_id`, or `model_id` filters; advances with `dealer_id`, `hull_id`, or `status` filters. The option-line ledger of §3.4 is likewise readable per order through its `order_id` or per package through its `option_package_id`.

### 3.7. Floor-Plan Financing: Tier Lock and Curtailment Settlement

The interest rate on an advance is fixed for its life at the moment it opens, and the evaluation order is pinned to break an otherwise circular dependency — the tier depends on utilization, utilization includes the new advance, and the advance's rate depends on the tier. The utilization ratio is computed as the dealer's `floor_plan_utilized_cents` before the delivery plus the new `principal_cents`, all divided by `floor_plan_limit_cents`. A ratio strictly below 0.50 locks `TIER_STANDARD` at an `annual_rate` of 0.06; a ratio of exactly 0.50 up to strictly below 0.80 locks `TIER_ELEVATED` at 0.075; a ratio of exactly 0.80 or above locks `TIER_HIGH` at 0.095. The dealer's own `current_rate_tier` tracks the same bands recomputed from the live ratio after every advance opening and every curtailment.

A `DealerPrincipal` pays down the credit line by posting a curtailment of `amount_cents` against the dealer identified in the path — which must be the caller's own dealer id — carrying `expected_dealer_version` as the OCC guard described in §2.7. The amount may not exceed the total due across the dealer's `OPEN` advances, where the total due is interest accrued to the clock date plus outstanding principal; an over-payment is rejected with `ERR_CURTAILMENT_EXCEEDS_BALANCE`, while an exact full payoff is expressly allowed. Payment applies as a waterfall: advances are visited oldest first by `opened_at`, ties broken by `created_at` ascending, and within each advance interest settles before principal. The interest owed on an advance is its `outstanding_principal_cents` times its locked `annual_rate` times the number of whole days from `last_accrual_date` to the clock date (zero when they coincide), divided by a 365-day year and rounded half up; settled interest accumulates into `accrued_interest_cents` and `last_accrual_date` advances to the clock date. Whatever remains of the payment then reduces `outstanding_principal_cents`. A partial payoff leaves the advance `OPEN`; a payment that zeroes the outstanding principal transitions the advance `OPEN` → `PAID`, its terminal state. The dealer's `floor_plan_utilized_cents` falls by the total principal repaid, `current_rate_tier` is recomputed from the lower ratio, and the dealer's `version` increments.

### 3.8. Warranty Registration and Claim Adjudication

A retail sale is registered by the selling `DealerPrincipal` with the `hull_id`, the `dealer_id`, and the `retail_sale_date`. The `dealer_id` must equal the caller's `X-User-ID` and must match the dealer on the delivered order — a different dealer is refused with `ERR_SELLING_DEALER_MISMATCH`. A hull accepts exactly one registration, a second attempt failing with `ERR_DUPLICATE_REGISTRATION`. The sale date must not be in the future and must not be more than 45 days before the clock date — a sale exactly 45 days old still qualifies; anything older or later-dated is rejected with `ERR_REGISTRATION_WINDOW_EXPIRED`. Registration stamps `registered_at` from the clock, computes `coverage_end_date` as the sale date plus 36 months, and sets a permanent `ACTIVE` status — lapse is enforced purely temporally through the coverage end, never through a status change. Registration also closes the commercial pipeline: the order transitions `DELIVERED` → `RETAILED` with a version increment, and because `RETAILED` exits the pipeline while `DELIVERED` still counted, the dealer's `allocation_used` is recounted down by one with a dealer version increment. Registrations list with `hull_id` or `dealer_id` filters.

A warranty claim is filed by the owning `DealerPrincipal` against a `registration_id` — the registration's dealer must equal the caller — with a free-text `defect_description`, `labor_hours` strictly greater than zero, `parts_cents` of zero or more, and an optional `recall_notice_id` linking the defect to an open recall. The presence of that linkage decides the claim's `variant_applied`: `RECALL_GOODWILL` when a notice is linked, `STANDARD` otherwise. The linked notice must belong to the same hull as the registration — a notice for a different hull draws `ERR_RECALL_NOTICE_MISMATCH` — and must still be `NOTIFIED`, else `ERR_INVALID_NOTICE_STATE`. Coverage is enforced temporally: a claim submitted after the registration's `coverage_end_date` is rejected with `ERR_COVERAGE_EXPIRED`, while a recall-linked claim bypasses the coverage window entirely (submission on the coverage end date itself is still inside coverage). A new claim is `SUBMITTED`, with `labor_charge_cents`, `parts_credit_cents`, and `reimbursement_cents` all null until adjudication. Claims list with `registration_id`, `recall_notice_id`, or `status` filters.

Adjudication belongs to the `WarrantyAdministrator`. Both approval and rejection require the claim to be `SUBMITTED`, anything else drawing `ERR_CLAIM_NOT_SUBMITTED`. Approval computes the reimbursement with per-component rounding pinned — labor first, then parts, then the sum. Under the `STANDARD` variant, labor pays the first 2.0 claimed hours (or all of them when fewer) at 9000 cents per hour rounded half up, plus any hours beyond 2.0 at 9000 cents times 0.85 rounded half up, and parts are credited at 0.85 of `parts_cents` rounded half up. Under the `RECALL_GOODWILL` variant, labor pays flat — every claimed hour at 9000 cents, rounded half up, with no tier discount — and parts are credited at the full `parts_cents`; the same inputs therefore produce a strictly higher total than `STANDARD` whenever hours exceed the first tier or parts are nonzero. The claim's `labor_charge_cents`, `parts_credit_cents`, and their sum `reimbursement_cents` are written at approval, and the claim's `status` becomes `APPROVED`. A recall-linked approval also remedies the recall: the linked notice transitions `NOTIFIED` → `REMEDIED` with `remedy_path` `WARRANTY_CLAIM` and `remedied_at` from the clock; the hull's `RECALL_HOLD` lifts back to `CERTIFIED` if and only if no other `NOTIFIED` notice remains for that hull; the campaign's `open_notice_count` decrements by one; and a campaign whose count reaches zero automatically closes. Rejection simply moves the claim `SUBMITTED` → `REJECTED` with no financial side effects, the three amount fields remaining null.

### 3.9. Recall Campaigns, Notices, and Remedy Paths

A `ComplianceOfficer` drafts a recall campaign with a unique `campaign_code` such as RC-2026-014, a `severity` of `SAFETY_STOP`, `SAFETY_STANDARD`, or `EMISSIONS`, the target `model_code` and `model_year`, and an inclusive serial band from `hin_serial_start` (at least 1) through `hin_serial_end` (no less than the start). The `model_code` here is a criteria string matched through each hull's model rather than a hard reference, so a campaign may be drafted before any affected model or hull exists. A new campaign is `DRAFT` with `notice_count` and `open_notice_count` at zero and `issued_at` null.

Issuing the campaign — permitted only from `DRAFT`, otherwise `ERR_CAMPAIGN_NOT_DRAFT` — fans out notices. Every hull whose model's `model_code` equals the campaign's, whose model's `model_year` matches, whose `serial_no` falls within the closed band from `hin_serial_start` to `hin_serial_end`, and whose `certification_status` is `CERTIFIED` receives a `RecallNotice` born `NOTIFIED` with `notified_at` stamped from the clock, and the hull itself flips `CERTIFIED` → `RECALL_HOLD` with a version increment — which blocks any pending delivery of that hull until remedy. The campaign records `notice_count` and `open_notice_count` equal to the number of notices generated and stamps `issued_at`. A campaign whose criteria match nothing — zero notices — auto-transitions straight from `ISSUED` to `CLOSED` at issue. Thereafter, the campaign auto-transitions `ISSUED` → `CLOSED` whenever `open_notice_count` reaches zero through remedies, incrementing the campaign's `version`; the list of campaigns filters by `model_code` or `status`, and notices by `campaign_id`, `hull_id`, or `status`.

Two symmetric remedy paths close a notice, and both require it to be `NOTIFIED` — anything else fails with `ERR_INVALID_NOTICE_STATE`. The plant path is a direct remedy by a `ComplianceOfficer`, intended for hulls not yet retailed: the notice transitions to `REMEDIED` with `remedy_path` `PLANT_REMEDY` and `remedied_at` from the clock. The retail path is the recall-linked claim approval of §3.8, which remedies the notice with `remedy_path` `WARRANTY_CLAIM`. Either path then applies the same cascade: the hull's hold lifts `RECALL_HOLD` → `CERTIFIED` if and only if no other `NOTIFIED` notice remains for that hull — while any open notice persists, so does the hold — the campaign's `open_notice_count` decrements by one, and the campaign closes automatically at zero.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, drive a state transition, or perform an action return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/boat-models` | Register a boat model (status defaults to `ORDERABLE`; may be seeded `DISCONTINUED`) | SystemAdmin |
| GET    | `/boat-models` | List boat models | Any |
| GET    | `/boat-models/{id}` | Get one boat model | Any |
| POST   | `/option-packages` | Register an option package for a model; optional self-referential incompatibility | SystemAdmin |
| GET    | `/option-packages` | List option packages | Any |
| GET    | `/option-packages/{id}` | Get one option package | Any |
| POST   | `/dealers` | Onboard a dealer with quota and floor-plan limit | AllocationManager |
| GET    | `/dealers` | List dealers | Any |
| GET    | `/dealers/{id}` | Get one dealer (version, quota usage, utilization, tier) | Any |
| PATCH  | `/dealers/{id}` | Update dealer quota / floor-plan limit / standing under OCC | AllocationManager |
| POST   | `/dealers/{id}/curtailments` | Pay down floor-plan advances; waterfall oldest-first, interest then principal; OCC-guarded | DealerPrincipal |
| POST   | `/boat-show-events` | Register a boat show window; same-region closed-interval overlap rejected | AllocationManager |
| GET    | `/boat-show-events` | List boat show events | Any |
| POST   | `/production-runs` | Open a one-week production run on a plant line; half-open window overlap rejected | ProductionPlanner |
| GET    | `/production-runs` | List production runs | Any |
| GET    | `/production-runs/{id}` | Get one production run (carrying totals, status) | Any |
| POST   | `/production-runs/{id}/close` | Season checkpoint: accrue carrying costs, release slots, auto-cancel `ALLOCATED` orders with waived fee | ProductionPlanner |
| POST   | `/build-slots` | Add a capacity slot to an `OPEN` run | ProductionPlanner |
| GET    | `/build-slots` | List build slots | Any |
| GET    | `/build-slots/{id}` | Get one build slot | Any |
| POST   | `/dealer-orders` | Book a dealer order with option lines; secures a slot (explicit or auto-select) or lands `WAITLISTED` | DealerPrincipal |
| GET    | `/dealer-orders` | List dealer orders | Any |
| GET    | `/dealer-orders/{id}` | Get one dealer order | Any |
| PATCH  | `/dealer-orders/{id}` | Amend options/deposit while `WAITLISTED` or `ALLOCATED` (cutoff applies when `ALLOCATED`); OCC-guarded | DealerPrincipal |
| POST   | `/dealer-orders/{id}/confirm` | Commit an `ALLOCATED` order | DealerPrincipal |
| POST   | `/dealer-orders/{id}/cancel` | Cancel from `WAITLISTED`/`ALLOCATED`/`COMMITTED` with tiered restocking fee; releases slot and fires waitlist promotion | DealerPrincipal |
| GET    | `/order-option-lines` | List option lines | Any |
| GET    | `/order-option-lines/{id}` | Get one option line | Any |
| POST   | `/hulls` | Report production completion for a `COMMITTED` order; assigns the HIN; hull born `UNCERTIFIED`/`AT_PLANT` | ProductionPlanner |
| GET    | `/hulls` | List hulls | Any |
| GET    | `/hulls/{id}` | Get one hull | Any |
| POST   | `/hulls/{id}/certify` | Certify a hull's HIN/build compliance; certifier must differ from the creating planner | ComplianceOfficer |
| POST   | `/hulls/{id}/deliver` | Deliver a certified, hold-free hull; opens the floor-plan advance and cascades dealer utilization/tier | ProductionPlanner |
| GET    | `/floor-plan-advances` | List floor-plan advances | Any |
| GET    | `/floor-plan-advances/{id}` | Get one floor-plan advance | Any |
| POST   | `/warranty-registrations` | Register the retail sale of a delivered hull; opens 36-month coverage; order becomes `RETAILED` | DealerPrincipal |
| GET    | `/warranty-registrations` | List warranty registrations | Any |
| GET    | `/warranty-registrations/{id}` | Get one warranty registration | Any |
| POST   | `/warranty-claims` | Submit a claim; recall linkage selects the `RECALL_GOODWILL` variant and bypasses the coverage window | DealerPrincipal |
| GET    | `/warranty-claims` | List warranty claims | Any |
| GET    | `/warranty-claims/{id}` | Get one warranty claim | Any |
| POST   | `/warranty-claims/{id}/approve` | Adjudicate a claim: computes reimbursement per variant; recall-linked approval remedies the notice and cascades campaign posture | WarrantyAdministrator |
| POST   | `/warranty-claims/{id}/reject` | Reject a `SUBMITTED` claim (no financial side effects) | WarrantyAdministrator |
| POST   | `/recall-campaigns` | Draft a recall campaign by model code, model year, and inclusive HIN serial range | ComplianceOfficer |
| GET    | `/recall-campaigns` | List recall campaigns | Any |
| POST   | `/recall-campaigns/{id}/issue` | Issue the campaign: fan out notices to matching `CERTIFIED` hulls and flip them to `RECALL_HOLD`; a zero-match issue auto-closes | ComplianceOfficer |
| GET    | `/recall-notices` | List recall notices | Any |
| GET    | `/recall-notices/{id}` | Get one recall notice | Any |
| POST   | `/recall-notices/{id}/remedy` | Plant remedy path: closes the notice, lifts the hull hold when it was the last open notice, cascades campaign posture | ComplianceOfficer |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC); startup default is exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_OPTION_NOT_FOUND` | 404 Not Found |
| `ERR_DEALER_NOT_FOUND` | 404 Not Found |
| `ERR_SHOW_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_HULL_NOT_FOUND` | 404 Not Found |
| `ERR_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_DEALER_VERSION` | 412 Precondition Failed |
| `ERR_MODEL_NOT_ORDERABLE` | 409 Conflict |
| `ERR_RUN_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_HULL_ALREADY_EXISTS` | 409 Conflict |
| `ERR_INVALID_HULL_STATE` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_DRAFT` | 409 Conflict |
| `ERR_INVALID_NOTICE_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTY` | 403 Forbidden |
| `ERR_HULL_RECALL_HOLD` | 409 Conflict |
| `ERR_HULL_NOT_CERTIFIED` | 409 Conflict |
| `ERR_OPTION_CUTOFF_PASSED` | 422 Unprocessable Entity |
| `ERR_SHOW_EVENT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_COVERAGE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_LINE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SHOW_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OPTION_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_SELLING_DEALER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RECALL_NOTICE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_QUOTA_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FLOOR_PLAN_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_CURTAILMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |

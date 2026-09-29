# Touring Motorsports Series Promotion API — Product Requirements Document

## 1. Introduction

A touring motorsports promoter lives or dies by the arithmetic of a season: a building rented on the right night in the right market, a floor show that fits the clock, a seat pool that is sold exactly once, a safety envelope that survives inspection, and a settlement that both the promoter and the building agree on. Today that arithmetic lives in spreadsheets that disagree with each other. Marketing money is promised twice because two markets planned against the same pool. Hospitality seats are given away out of an allotment the box office has already sold. A vehicle fails technical inspection an hour before doors and nobody stops the sale. The purpose of this API is to make each of those events a rejected request instead of a post-mortem.

This document specifies the server that carries the whole promotion cycle: season and venue registration, rental-term negotiation with the building, market rotation across the calendar, competitor and vehicle logistics from transport through staging and technical inspection, run-order design with competition heats and intermission entertainment, tiered ticketing with group sales and a pre-show pit party add-on, sponsorship activation covering vehicle branding, signage and hospitality obligations, safety planning with barriers, catch fencing, medical staffing and emergency access, local marketing spend across radio, digital and grassroots channels, and finally event settlement with a venue payout waterfall and profitability analysis by market.

Two design commitments run through everything below. First, **conserved quantities**: a tier's seats and a season's marketing budget are pools that can be moved between buckets but never created or destroyed, and every operation that touches them must leave the pool arithmetic intact. Second, **life safety outranks money**: a stop whose safety posture has degraded stops selling tickets automatically, and no fiscal check is ever allowed to mask a safety shortfall. The specification is written so that an implementer can reconstruct every threshold, every ordering and every cascade from the prose alone.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint in the system. Domain behaviour is specified in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request with a missing or empty `X-User-ID` is rejected with `ERR_UNAUTHENTICATED` (401). A request whose `X-User-Role` is not among the roles authorized for the addressed endpoint is rejected with `ERR_UNAUTHORIZED` (403).

The system recognizes exactly seven roles, spelled as follows: `SeriesPromoter`, `VenueManager`, `CompetitorTeam`, `SafetyOfficial`, `TicketingManager`, `SponsorRep`, and `FinanceController`.

Three of these roles are **entity-backed**, meaning `X-User-ID` is the identifier of a persisted row and ownership checks compare a resource's foreign key against it:

- When `X-User-Role` is `VenueManager`, `X-User-ID` is the `id` of the acting `Venue`; ownership checks on any resource that references a `Venue` compare the resource's venue reference to `X-User-ID`. A `VenueManager` may therefore counter only bookings whose `venue_id` equals their own `X-User-ID`, and may dispute only the settlement of a stop whose booking names their venue.
- When `X-User-Role` is `CompetitorTeam`, `X-User-ID` is the `id` of the acting `Competitor`; entries may be created only with a `competitor_id` equal to `X-User-ID`, and only that team's own entries may be checked in.
- When `X-User-Role` is `SponsorRep`, `X-User-ID` is the `id` of the acting `Sponsor`; an activation may be proposed only with a `sponsor_id` equal to `X-User-ID`, and only that sponsor's own activations may be signed off as fulfilled.

Any entity-backed caller acting outside their own resource is rejected with `ERR_OWNERSHIP_MISMATCH` (403).

The remaining four roles are **opaque operator identities**: `X-User-ID` is an operator identifier that is not tied to any persisted entity and is never compared to any row's `id`.

- When `X-User-Role` is `SeriesPromoter`, `X-User-ID` is an opaque operator identifier. The promoter owns the season, the promoter side of the booking negotiation, the run order, sponsorship activation and the local marketing budget.
- When `X-User-Role` is `SafetyOfficial`, `X-User-ID` is an opaque operator identifier. The server records it as `authored_by_user_id` and `certified_by_user_id` on a `SafetyPlan` and as `inspected_by_user_id` on a `TechInspection`, and compares those recorded values against each other for segregation of duties, but never against any entity's `id`.
- When `X-User-Role` is `TicketingManager`, `X-User-ID` is an opaque operator identifier used for box-office operations only; nothing is compared against it.
- When `X-User-Role` is `FinanceController`, `X-User-ID` is an opaque operator identifier. The server records it as `prepared_by_user_id` and `approved_by_user_id` on an `EventSettlement` and compares those two recorded values for segregation of duties, but never against any entity's `id`.

A `VenueManager`'s identifier is additionally recorded as `last_counter_by_user_id` on the booking it counters.

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

### 2.3. Pagination, Sorting and Collection Filters

List endpoints accept two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1 and may not be larger than 100. `offset` skips rows before the page begins; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (422). Every list response carries `limit`, `offset`, `total_count` and `has_more` in the envelope's `meta` object.

Unless a specific collection declares otherwise, list results are sorted by `created_at` ascending. Two collections override that default: the inspection history of a vehicle entry is ordered by `attempt_no` ascending, and the run order of a stop is ordered by `run_order_position` ascending.

Collections also accept domain filters, which combine with pagination:

- Booking lists accept `season_id`, `venue_id` and `state`.
- Tour-stop lists accept `season_id`, `venue_booking_id`, `preceding_stop_id`, `market_code` and `sales_state`.
- Vehicle-entry lists accept `tour_stop_id`, `competitor_id` and `logistics_state`.
- Ticket-order lists accept `tour_stop_id`, `ticket_tier_id` and `status`.
- Sponsorship-activation lists accept `sponsor_id`, `tour_stop_id`, `hospitality_tier_id`, `branded_vehicle_entry_id` and `state`.
- Marketing-allocation lists of a stop accept `channel` and `state`.

Two single-child collections are returned as arrays of length zero or one rather than as bare objects: a stop's safety plan and a stop's settlement.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource in the system carries an `id`: a server-minted UUID with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the row was first written.

Almost every resource additionally carries `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation — and `version`, an integer that starts at 1 and increments by one on every mutation of that row, including mutations the server performs on its own initiative when a derived counter or a cascaded state change lands on the row. There is exactly one exception: a `TechInspection` is an immutable audit record. It carries only `id` and `created_at`; both `updated_at` and `version` are absent from it entirely.

All time-dependent behaviour in the system reads a **logical clock** rather than wall-clock time. Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`; it never falls back to the host's real time. A test-driving capability, available to all seven roles, accepts a `to_iso8601` instant, sets the clock to it, and returns the new value as `current_utc`. Every lead-time evaluation, on-sale window check, staging window check and server-stamped timestamp — `confirmed_at`, `paid_at`, `refunded_at`, `released_at`, `actual_arrival_utc`, `obligations_fulfilled_at` — reads the logical clock at the moment the request is processed.

### 2.5. Money, Precision and Conserved Pools

Every monetary amount in this system is an integer number of cents; no monetary field is ever a decimal. Where a percentage is applied to a monetary amount, the product is rounded to whole cents using the round-half-up rule, and the rounding is applied to each named component separately, on its own line, in the order the calculation declares. Summing several unrounded components and rounding once at the end is not equivalent and is incorrect. The only non-integer stored figures are rate fields — `revenue_share_pct`, `group_discount_pct`, `coop_credit_pct` — and `profitability_margin_pct`, which is rounded half up to exactly two decimal places.

Two pools in the system are **conserved quantities**, and every operation that touches them must preserve the identity of the pool.

The first is a tier's seat pool. For any `TicketTier`, its `allotment` always equals `available_seat_count` plus `reserved_seat_count` plus `sold_seat_count` plus `held_seat_count`. Reserving, paying, refunding, voiding and holding seats move quantity between those buckets; nothing adds to or subtracts from `allotment` itself.

The second is the season's marketing budget. For any `Season`, `total_marketing_budget_cents` always equals `marketing_allocated_cents` plus `marketing_unallocated_cents`. Committing local marketing spend moves money from unallocated to allocated; releasing an allocation moves exactly the same amount back. Every commit and every release applies exactly inverse deltas, so the invariant holds before and after each pair.

### 2.6. Path Resolution for Nested Addresses

Many creations and reads are addressed under a parent: a stop's ticket tiers, a stop's safety plan, an entry's inspections. When a path contains an identifier, the server resolves it before doing anything else, and when a path contains more than one identifier they are resolved strictly left to right. The first identifier that does not resolve determines the error, and the response is the 404 belonging to that entity — `ERR_SEASON_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_VENUE_BOOKING_NOT_FOUND`, `ERR_TOUR_STOP_NOT_FOUND`, `ERR_COMPETITOR_NOT_FOUND`, `ERR_VEHICLE_ENTRY_NOT_FOUND`, `ERR_TECH_INSPECTION_NOT_FOUND`, `ERR_SHOW_SEGMENT_NOT_FOUND`, `ERR_TICKET_TIER_NOT_FOUND`, `ERR_TICKET_ORDER_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_SPONSORSHIP_ACTIVATION_NOT_FOUND`, `ERR_SAFETY_PLAN_NOT_FOUND`, `ERR_MARKETING_ALLOCATION_NOT_FOUND` or `ERR_SETTLEMENT_NOT_FOUND`.

Foreign keys supplied in a request body are resolved with the same entity-specific 404s, immediately after path resolution and before any state or business rule is evaluated. The body keys that are resolved this way are `season_id`, `venue_id`, `competitor_id`, `tour_stop_id`, `ticket_tier_id`, `sponsor_id`, `hospitality_tier_id`, `branded_vehicle_entry_id`, `featured_vehicle_entry_id` and `preceding_stop_id`.

### 2.7. Optimistic Concurrency on the Tier and the Season Budget

Exactly two write operations in this system are protected by optimistic concurrency control, and each requires the client to declare the parent version it last observed. No other endpoint takes a version field, and supplying one elsewhere has no effect.

A `POST /ticket-orders` request must carry `expected_ticket_tier_version` as a non-optional field, holding the client's last observed `version` of the `TicketTier` named by `ticket_tier_id`. If that value does not equal the tier's current `version`, the create is rejected with `ERR_STALE_TIER_VERSION` (HTTP 412). The tier's `version` advances whenever its seat buckets move — another order was written against it, an order was paid, refunded or voided, or a sponsorship activation held hospitality seats out of it — so a stale value means the client's view of `available_seat_count` no longer describes the tier.

A `POST /tour-stops/{id}/marketing-allocations` request must carry `expected_season_version` as a non-optional field, holding the client's last observed `version` of the `Season` that owns the addressed stop. If that value does not equal the season's current `version`, the commit is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412). The season's `marketing_unallocated_cents` is the single pool every market draws from, and its `version` advances on every commit and every release, so a stale value means the client may be planning against money another market has already committed or handed back.

### 2.8. The Readiness Posture: One Derived Gate Over Two State Dimensions

Every `TourStop` carries two independent state dimensions — `sales_state` for ticketing and `safety_state` for the safety envelope — and a third field, `readiness_posture`, which is **derived** from both dimensions plus the stop's children. It is never set directly by a client. It is recomputed at the end of every mutation that touches a stop or any of its children: booking acceptance and withdrawal, logistics updates, safety-plan transitions, tier creation, entry creation, check-in and inspection, order transitions, activation transitions, and marketing commit or release.

The derivation is evaluated in this order, and the first matching branch wins:

1. If the stop's `safety_state` is `SAFETY_SUSPENDED`, or its `sales_state` is `CANCELLED`, the posture is `FROZEN`.
2. Otherwise, the posture is `RESTRICTED` if any of the following holds: the `safety_state` is anything other than `SAFETY_CERTIFIED`; the stop's `competition_segment_count` is zero; at least one vehicle entry of the stop whose `logistics_state` is `ENTERED` or `STAGED` has `tech_status` equal to `TECH_HELD`; the stop's `marketing_spend_committed_cents` is zero; or the stop's `show_start_utc` has not been set yet.
3. Otherwise the posture is `OPEN`.

The three postures gate differently. `FROZEN` rejects every mutation of the stop or of any of its children — the sole exception being a safety reinstatement, which exists precisely to lift the freeze — with `ERR_STOP_FROZEN` (409). `RESTRICTED` still permits children to be built, but the stop can neither go on sale nor return to sale. `OPEN` is the only posture from which sales may be opened or resumed.

Because the posture is derived, it can change without any client asking for it. Whenever a recomputation leaves the posture at something other than `OPEN` while `sales_state` is `ON_SALE`, the server immediately drives the stop from `ON_SALE` to `SALES_HALTED`, and every `TicketOrder` of the stop still in `PENDING` is moved to `VOID` with `void_reason` set to `SALES_HALTED`, releasing its `qty` from the tier's `reserved_seat_count` and recomputing `available_seat_count`. The stop's `version` increments on that automatic halt.

### 2.9. Three Named Cascades

Three multi-entity cascades are the spine of consistency in this system. Each is triggered by a single client request and each mutates several rows; every link is mandatory, not best-effort.

**Cascade A — booking withdrawal tears down the market.** Withdrawing a booking that is `CONFIRMED` sets the booking to `WITHDRAWN` with the supplied `withdraw_reason` and decrements the season's `booking_count`. Because the booking left `CONFIRMED`, the stop it produced moves `sales_state` to `CANCELLED` — from whichever state it held, whether `SALES_PENDING`, `ON_SALE`, `SALES_HALTED` or `SALES_CLOSED` — moves `safety_state` to `SAFETY_SUSPENDED` from either `SAFETY_CERTIFIED` or `SAFETY_DRAFT`, and records `cancel_reason` from the same reason text. Because the stop became `CANCELLED`, every `TicketOrder` of the stop in `PENDING` moves to `VOID` with `void_reason` set to `STOP_CANCELLED`, and every `TicketOrder` in `PAID` moves to `REFUNDED`. Because those orders left `PENDING` and `PAID`, each order's tier decrements `reserved_seat_count` or `sold_seat_count` accordingly and recomputes `available_seat_count`, and the stop's `tickets_sold_count`, `gross_ticket_revenue_cents`, `addon_revenue_cents`, `facility_fee_collected_cents` and `pit_party_sold_count` all decrease by the reversed amounts. Because the stop became `CANCELLED`, every `MarketingAllocation` of the stop in `COMMITTED` moves to `RELEASED` with `released_at` stamped from the logical clock, which decrements the season's `marketing_allocated_cents`, recomputes `marketing_unallocated_cents` and increments the season's `version` by one. Every `VehicleEntry` of the stop whose `logistics_state` is `ENTERED` or `STAGED` moves to `WITHDRAWN` and has its `staging_bay_index` cleared, returning that bay to the selector pool. Finally the stop's posture is recomputed and yields `FROZEN`.

**Cascade B — a bigger house invalidates a certified safety plan.** Adding a ticket tier can raise the stop's `expected_attendance`, which recomputes the safety plan's required provisioning. When the recomputed requirements outrun what a `CERTIFIED` plan actually provisioned, the plan moves from `CERTIFIED` to `RETURNED`, its `certified_by_user_id` is cleared, its `return_count` increments by one, and its `return_reason` is set to the exact string `AUTO_REQUIREMENT_INCREASE`. Because the plan left `CERTIFIED`, the stop's `safety_state` moves from `SAFETY_CERTIFIED` to `SAFETY_DRAFT` and its posture is recomputed to `RESTRICTED`. Because the posture left `OPEN`, a stop that was `ON_SALE` moves to `SALES_HALTED`, and because sales were halted, every `PENDING` order of the stop moves to `VOID`, releasing `reserved_seat_count` on its tier.

**Cascade C — settlement approval bubbles up to the season.** Approving a settlement recomputes every money field under the final variant, sets `variant` to `FINAL`, `state` to `APPROVED` and `approved_by_user_id` from the caller. Because the settlement became `APPROVED`, the stop moves `sales_state` from `SALES_CLOSED` to `SETTLED`. Because the stop became `SETTLED`, the season's `settled_stop_count` increments by one, the settlement's `net_to_promoter_cents` is added to the season's `season_net_cents`, and the season's `version` increments by one. If, after that, the season has at least one tour stop, every tour stop of the season has `sales_state` in `SETTLED` or `CANCELLED`, and at least one of them is `SETTLED`, the season's `status` moves from `PLANNING` to `CLOSED` and the season's `version` increments again.

### 2.10. Validation Precedence

Where several rules could reject the same request, they are evaluated in a fixed order and the first failure determines the response. Cheap envelope checks come first, then identity and concurrency, then lifecycle state, then life-safety gates, then referential companions, then calendar feasibility, then structural constraints, and money and inventory ledgers last. The full ladder, in evaluation order:

1. `ERR_UNAUTHENTICATED` (401) — `X-User-ID` absent or empty. Every endpoint.
2. `ERR_UNAUTHORIZED` (403) — the caller's role is not authorized for the endpoint. Every endpoint.
3. `ERR_INVALID_REQUEST` (422) — a required body field is missing, a scalar has the wrong type, a date or datetime is malformed, an enum value falls outside its declared set, a quantity, amount or count falls below its declared minimum, `limit` is outside 1 through 100, or `offset` is negative. Every endpoint with a body or query parameters.
4. The entity-specific 404 — the `{id}` in the path does not resolve to a row of the addressed entity. Every endpoint with a path parameter.
5. The entity-specific 404 — a foreign key supplied in the body does not resolve. Applies to booking creation, vehicle-entry creation, ticket-order creation, activation creation, run-order segment creation and the stop logistics update.
6. `ERR_OWNERSHIP_MISMATCH` (403) — an entity-backed caller acting on somebody else's resource. Applies to exactly five operations: booking counter, vehicle-entry creation, vehicle-entry check-in, activation creation and activation fulfilment.
7. `ERR_SAFETY_SELF_CERTIFICATION` (403) — safety-plan certification only.
8. `ERR_SETTLEMENT_SELF_APPROVAL` (403) — settlement approval only.
9. `ERR_STALE_TIER_VERSION` (412) — ticket-order creation only.
10. `ERR_STALE_SEASON_VERSION` (412) — marketing-allocation creation only.
11. `ERR_INVALID_STATE_TRANSITION` (409) — the addressed row is not in a state from which the requested transition is declared. This covers: a booking that is not `TERMS_PROPOSED` or `COUNTERED` when countered, revised or accepted, and any booking already `WITHDRAWN`; a plan that is not `DRAFT` or `RETURNED` when patched or submitted, and not `SUBMITTED` when certified or returned; an entry that is not `ENTERED` when checked in, and not `STAGED` when inspected; an order that is not `PENDING` when paid, and not `PAID` when refunded; an activation that is not `PROPOSED` when activated, and not `ACTIVATED` when fulfilled; a settlement that is not `PREPARED` when approved or disputed; any child write while the owning season's `status` is `CLOSED`; and any child write while the owning stop's `sales_state` is `CANCELLED` or `SETTLED`.
12. `ERR_SALES_NOT_OPEN` (409) — the stop's `sales_state` is not `ON_SALE` when an order is created. Ticket-order creation only.
13. `ERR_STOP_FROZEN` (409) — the stop's posture is `FROZEN` and the request mutates the stop or one of its children. Applies to exactly ten operations: the stop logistics update, run-order segment creation, ticket-tier creation, going on sale, resuming sales, marketing-allocation creation, vehicle-entry creation, ticket-order creation, activation creation and settlement preparation. Safety reinstatement is deliberately excluded.
14. `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (409) — booking counter only.
15. `ERR_SAFETY_NOT_CERTIFIED` (409) — the stop's `safety_state` is not `SAFETY_CERTIFIED` when sales are opened or resumed. Applies to both going on sale and resuming sales.
16. `ERR_MEDICAL_STAFFING_SHORTFALL` (422) — provisioned ALS or BLS medics fall short. Applies to both plan submission and plan certification.
17. `ERR_AMBULANCE_SHORTFALL` (422) — provisioned ambulances fall short. Both submission and certification.
18. `ERR_CATCH_FENCE_INSUFFICIENT` (422) — fence height below requirement or above the venue's rigging limit. Both submission and certification.
19. `ERR_EMERGENCY_ACCESS_INSUFFICIENT` (422) — emergency lanes fall short. Both submission and certification.
20. `ERR_BARRIER_INSUFFICIENT` (422) — barrier footage falls short. Both submission and certification.
21. `ERR_ENTRY_TECH_HELD` (409) — a vehicle entry whose `tech_status` is `TECH_HELD` is being featured in a run-order segment or branded by an activation. Applies to exactly two operations: run-order segment creation and activation creation.
22. `ERR_TECH_ATTEMPTS_EXHAUSTED` (409) — inspection filing only.
23. `ERR_RUN_ORDER_INCOMPLETE` (409) — the stop's `competition_segment_count` is zero when sales are opened. Going on sale only.
24. `ERR_NO_TICKET_TIERS` (409) — the stop has no tier rows when sales are opened. Going on sale only.
25. `ERR_PENDING_ORDERS_OUTSTANDING` (409) — the stop still has orders in `PENDING` when a settlement is prepared. Settlement preparation only.
26. `ERR_CHILD_STOP_MISMATCH` (422) — a referenced child belongs to a different stop than the one addressed. Applies to ticket-order creation, activation creation and run-order segment creation.
27. `ERR_SAFETY_PLAN_MISSING` (409) — the stop has no safety-plan row when a settlement is prepared. Settlement preparation only.
28. `ERR_DATE_OUTSIDE_SEASON` (422) — booking creation only.
29. `ERR_BOOKING_LEAD_TIME` (422) — booking creation only.
30. `ERR_VENUE_DATE_CONFLICT` (409) — applies to both booking creation and booking acceptance.
31. `ERR_HAUL_BUFFER_VIOLATION` (409) — the stop logistics update only.
32. `ERR_SEGMENT_TIMELINE_CONFLICT` (409) — run-order segment creation only.
33. `ERR_TIER_WINDOW_INVALID` (422) — ticket-tier creation only.
34. `ERR_TIER_WINDOW_CLOSED` (409) — ticket-order creation only.
35. `ERR_SHOW_TIMING_INVALID` (422) — the stop logistics update only.
36. `ERR_STAGING_WINDOW_CLOSED` (409) — vehicle-entry check-in only.
37. `ERR_MARKET_ROTATION_COOLDOWN` (409) — applies to both booking creation and booking acceptance.
38. `ERR_ROTATION_CHAIN_INVALID` (422) — the stop logistics update only.
39. `ERR_SHOW_WINDOW_EXCEEDED` (409) — run-order segment creation only.
40. `ERR_GROUP_MINIMUM_NOT_MET` (422) — ticket-order creation only.
41. `ERR_PIT_PARTY_CAPACITY_EXCEEDED` (409) — ticket-order creation only.
42. `ERR_BRANDING_SLOTS_EXCEEDED` (409) — activation creation only.
43. `ERR_SPONSOR_CATEGORY_EXCLUSIVITY` (409) — activation only.
44. `ERR_DUPLICATE_TIER_CODE` (409) — ticket-tier creation only.
45. `ERR_DUPLICATE_CHILD` (409) — applies to both safety-plan creation and settlement preparation.
46. `ERR_DUPLICATE_VEHICLE_ENTRY` (409) — vehicle-entry creation only.
47. `ERR_NO_STAGING_BAY_AVAILABLE` (409) — vehicle-entry creation only.
48. `ERR_TIER_SOLD_OUT` (409) — ticket-order creation only.
49. `ERR_HOSPITALITY_SEATS_EXCEEDED` (409) — applies to both activation creation and activation.
50. `ERR_CHANNEL_CAP_EXCEEDED` (409) — marketing-allocation creation only.
51. `ERR_STOP_MARKETING_CAP_EXCEEDED` (409) — marketing-allocation creation only.
52. `ERR_MARKETING_BUDGET_EXCEEDED` (409) — marketing-allocation creation only.
53. `ERR_STOP_NOT_READY` (409) — the stop's posture is not `OPEN` when sales are opened or resumed. This is the final composite gate on both operations, and it is reached only after every specific safety and referential check above it has already passed; a stop that is uncertified reports `ERR_SAFETY_NOT_CERTIFIED`, a stop with no competition segment reports `ERR_RUN_ORDER_INCOMPLETE`, and only a stop that survives all of those but still fails the derived posture reports `ERR_STOP_NOT_READY`.

Note the ordering consequence in the marketing tier: the channel cap is checked before the per-stop cap, which is checked before the season pool, so an allocation that breaches two of them reports the earliest breach.

### 2.11. Segregation of Duties

Two decisions in this system may never be taken by the same operator who set them up.

A safety plan's author is recorded in `authored_by_user_id` — written when the plan is created and re-stamped on every revision of a draft. The `X-User-ID` certifying that plan must differ from `authored_by_user_id`; if it does not, the request is rejected with `ERR_SAFETY_SELF_CERTIFICATION` (403). This check runs before any provisioning check, so a self-certification attempt on an under-provisioned plan reports the self-certification error, not a shortfall.

A settlement's preparer is recorded in `prepared_by_user_id` — written on the initial preparation and re-stamped on every re-preparation out of dispute. The `X-User-ID` approving that settlement must differ from `prepared_by_user_id`; if it does not, the request is rejected with `ERR_SETTLEMENT_SELF_APPROVAL` (403). This check likewise precedes the settlement's own state and sales-state gates.

## 3. Business Logic & Workflows

### 3.1. Seasons, Buildings and the Booking Negotiation

A season is the top-level container for a tour. A `SeriesPromoter` opens one by supplying a `name` such as "2026-27 Thunder Tour", the opening calendar `year`, the calendar window as `season_start_date` and `season_end_date` (both plain `YYYY-MM-DD` dates), and the season-wide local promotion budget as `total_marketing_budget_cents`, which may not be negative. An optional `market_rotation_cooldown_days` sets the minimum whole-day separation the season demands between two confirmed dates in the same market; it may not be negative and defaults to 21 days when omitted. A new season opens with `status` set to `PLANNING`, and only `PLANNING` and `CLOSED` are ever valid values for it. Its ledger fields open at a known state: `marketing_allocated_cents` is 0 and `marketing_unallocated_cents` equals `total_marketing_budget_cents`. Its roll-up counters — `booking_count`, `settled_stop_count` and `season_net_cents` — all open at 0. `booking_count` is the number of bookings of the season whose `state` is `TERMS_PROPOSED`, `COUNTERED` or `CONFIRMED`; `settled_stop_count` is the number of the season's stops whose `sales_state` is `SETTLED`; `season_net_cents` is the sum of `net_to_promoter_cents` over the season's settlements that reached `APPROVED`; and `marketing_allocated_cents` is the sum of `amount_cents` over the season's `COMMITTED` marketing allocations across all of its stops.

Buildings are registered independently of any season. A venue carries a `name`, the designated `market_code` that the rotation rule keys on (for example `ATL`), its `city` and two-letter `state_code`, a hard `seat_capacity` of at least 1, and a `floor_type` of `DIRT`, `CONCRETE` or `ASPHALT`. It also declares its physical envelope: `catch_fence_max_height_ft` is the tallest catch fence the building's rigging supports, `medical_bay_count` the number of on-site medical bays, `load_in_hours_required` the hours of load-in the building demands before doors, and `staging_bay_count` the number of staging bays the bay selector draws from, numbered from 1 upward. All four must be zero or greater. Finally, `turnaround_hours` is the mandatory buffer the building requires after one tear-down before another load-in may begin; it may not be negative and defaults to 12 hours.

Booking a date begins as a proposal from the promoter. The proposal names the `season_id` and `venue_id`, the show date as `tour_date`, and the three money terms: a flat guarantee `rental_base_cents`, the building's share of adjusted ticket gross as `revenue_share_pct` (a rate between 0 and 1 inclusive), and `per_ticket_facility_fee_cents`, the fee collected on each ticket and remitted to the building. The occupancy interval is declared as `load_in_start_utc` and `tear_down_end_utc`. Three calendar checks run at proposal time. The `tour_date` must fall on or between the season's `season_start_date` and `season_end_date`, or the proposal is rejected with `ERR_DATE_OUTSIDE_SEASON`. The `tour_date` must be at least 45 whole days after the current logical clock's date, or the proposal is rejected with `ERR_BOOKING_LEAD_TIME`. And `load_in_start_utc` must be strictly earlier than `tear_down_end_utc`; an inverted or zero-length interval is rejected with `ERR_VENUE_DATE_CONFLICT`.

That same error also guards the building's calendar. Venue occupancy intervals are treated as closed at both ends and are additionally padded by the venue's own `turnaround_hours` on each side, so intervals that merely touch collide. For each other booking at the same venue whose `state` is `CONFIRMED`, the server builds a blocked interval running from that booking's `load_in_start_utc` minus `turnaround_hours` to its `tear_down_end_utc` plus `turnaround_hours`. If the candidate's start is at or before the blocked interval's end and the blocked interval's start is at or before the candidate's end, the two collide and the request is rejected with `ERR_VENUE_DATE_CONFLICT`. Bookings in `TERMS_PROPOSED`, `COUNTERED` or `WITHDRAWN` never block anything.

Market rotation is the second calendar rule. For each other booking of the same season whose `state` is `CONFIRMED` and whose venue shares the candidate venue's `market_code`, the server takes the absolute difference in whole days between the two `tour_date` values. If that gap is strictly smaller than the season's `market_rotation_cooldown_days`, the request is rejected with `ERR_MARKET_ROTATION_COOLDOWN`. A gap exactly equal to the cooldown is allowed. Both the occupancy check and the rotation check run twice in a booking's life: once when the terms are first proposed, and again when they are accepted, because the set of confirmed bookings can change in between.

A fresh booking opens in `state` `TERMS_PROPOSED` with `negotiation_round` at 1, `terms_source` at `PROMOTER`, and `last_counter_by_user_id`, `confirmed_at` and `withdraw_reason` all null; the season's `booking_count` rises by one. The negotiation then cycles. A `VenueManager` for the booked building counters the terms, which moves the booking from `TERMS_PROPOSED` to `COUNTERED`: the counter supplies its own `rental_base_cents`, `revenue_share_pct` and `per_ticket_facility_fee_cents` plus an optional `note`, and those values overwrite the terms on the row; if the counter also supplies `load_in_start_utc` or `tear_down_end_utc`, those overwrite the occupancy bounds as well. Countering sets `terms_source` to `VENUE`, records the caller in `last_counter_by_user_id`, increments `negotiation_round` by one and increments the booking's `version` by one. A counter is admissible only while `negotiation_round` is still below 3; the fourth attempt to counter is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`.

The promoter answers a counter with a revision, moving the booking from `COUNTERED` back to `TERMS_PROPOSED`. A revision supplies `rental_base_cents`, `revenue_share_pct` and `per_ticket_facility_fee_cents`, may optionally restate `load_in_start_utc` and `tear_down_end_utc`, and may carry a `note`. It overwrites the terms fields, sets `terms_source` back to `PROMOTER` and increments the booking's `version`. Like the counter, it is admissible only while `negotiation_round` is below 3. `TERMS_PROPOSED` and `COUNTERED` therefore alternate until the round budget runs out or one side settles.

Acceptance is the promoter's act, and it is admissible from either `TERMS_PROPOSED` or `COUNTERED`; in the latter case the terms in force are the venue's counter terms, with `terms_source` reading `VENUE`. Acceptance requires that the caller be the `VenueManager` of the booked venue for ownership purposes and that the season's `status` still be `PLANNING`, and it re-runs both the occupancy-overlap check and the market-rotation check against currently `CONFIRMED` bookings. On success the booking moves to `CONFIRMED`, `confirmed_at` is stamped from the logical clock, and the booking's `version` increments. `booking_count` does not change on acceptance, since a confirmed booking was already being counted.

Acceptance is also the moment a **tour stop** comes into existence. The server synthesizes exactly one `TourStop` for the booking, copying `season_id` from the booking, recording the booking as `venue_booking_id`, denormalizing `market_code` from the booked venue and `event_date` from the booking's `tour_date`. The new stop opens with `sales_state` `SALES_PENDING` and `safety_state` `SAFETY_DRAFT`, and its posture is immediately computed, which yields `RESTRICTED`.

Withdrawal ends a booking. The promoter supplies a `reason`, which is stored as `withdraw_reason`, and the booking moves to `WITHDRAWN`. From `TERMS_PROPOSED` or `COUNTERED` there are no preconditions at all: the booking simply becomes `WITHDRAWN`, the season's `booking_count` decrements by one and the season's `version` increments by one, and nothing further happens because no stop exists yet. From `CONFIRMED` the withdrawal is admissible only while the booking's stop has a `sales_state` other than `SETTLED`, and it fires Cascade A in full as described in §2.9 — the same `booking_count` decrement and season `version` increment, plus the stop cancellation, the order reversals, the tier and stop counter reversals, the marketing release and the entry withdrawals. `CONFIRMED` and `WITHDRAWN` are both terminal for a booking; there is no route back.

### 3.2. Standing Up the Stop: Show Timing, the Pit Party and the Transport Chain

A newly synthesized stop knows its date and its market but not yet its clock. The promoter fills that in with a logistics update, which accepts any subset of `doors_open_utc`, `show_start_utc`, `show_window_minutes`, `pit_party_price_cents`, `pit_party_capacity`, `preceding_stop_id` and `haul_distance_miles`. `show_window_minutes` is the total on-floor minutes available to the run order and defaults to 150; `pit_party_price_cents` is the per-head price of the pre-show pit party add-on and defaults to 2450; `pit_party_capacity` is the maximum number of pit party heads the stop will sell and defaults to 0. None of the three may be negative. The stop also tracks `pit_party_sold_count`, the sum of `pit_party_addon_qty` over its orders that reached `PAID`.

Show timing is checked as a triple. `doors_open_utc` must be strictly earlier than `show_start_utc`, the gap between them must be at least one hour, and `show_start_utc` must fall inside the booking's occupancy interval running from `load_in_start_utc` to `tear_down_end_utc`. Any of those three failing is rejected with `ERR_SHOW_TIMING_INVALID`. When `show_start_utc` changes, the run-order timeline is recomputed for every segment of the stop, because all segment offsets are measured from show start.

The transport chain is expressed by `preceding_stop_id`, which points at the stop the transporters are coming from and is null for the first stop of a chain. Four conditions make a chain link invalid, and all four are rejected with `ERR_ROTATION_CHAIN_INVALID`: the named predecessor is the stop itself; the predecessor belongs to a different season; the predecessor's `event_date` is on or after this stop's `event_date`; or some other stop already points at that predecessor, since a stop may be the predecessor of at most one successor.

The stop's own `haul_distance_miles` records the road miles from the preceding stop's building to this one and may not be negative; it defaults to 0. Whenever either `preceding_stop_id` or `haul_distance_miles` is supplied, the server enforces a one-sided transport buffer. The required haul time in hours is the stop's `haul_distance_miles` divided by 50 miles per hour and rounded up to a whole number of hours, plus a further 10 hours of mandatory crew rest. The earliest permissible load-in is the preceding stop's booking `tear_down_end_utc` advanced by that many hours. If this stop's booking `load_in_start_utc` falls strictly before that instant, the update is rejected with `ERR_HAUL_BUFFER_VIOLATION`. Note that this buffer is anchored one-sidedly on the predecessor's tear-down, unlike the venue's symmetric turnaround pad.

A logistics update recomputes the stop's posture at the end, which matters because an unset `show_start_utc` is itself one of the conditions that holds a stop at `RESTRICTED`.

### 3.3. Competitors, Staging Bays and Technical Inspection

A competing team is registered with a `team_name`, a `driver_name`, its `home_market_code` and the `vehicle_class` it runs, which is either `LIGHT` or `HEAVY`. The team's `entry_count` is derived: it counts that competitor's vehicle entries whose `logistics_state` is `ENTERED` or `STAGED`, and it rises as entries are created.

Entering a vehicle in a stop names the `competitor_id` and the `tour_stop_id`, the `vehicle_number` as painted on the body, the race weight as `vehicle_weight_lbs` (at least 1), the `haul_distance_miles` the transporter will cover to reach this stop (zero or more), and the promised transporter ETA as `scheduled_arrival_utc`. A `CompetitorTeam` may only enter its own vehicles; the promoter may enter on any team's behalf. A team may not field two live entries with the same `vehicle_number` at the same stop — if the competitor already has a non-`WITHDRAWN` entry with that number on that stop, the request is rejected with `ERR_DUPLICATE_VEHICLE_ENTRY`.

Entry creation also assigns a staging bay. The candidate set is every bay index from 1 through the booked venue's `staging_bay_count`, minus the bays currently held by entries of the same stop whose `logistics_state` is `ENTERED` or `STAGED`; a `WITHDRAWN` entry releases its bay back into the pool. The choice within the candidate set depends on weight: an entry whose `vehicle_weight_lbs` is at least 9000 pounds is a heavy rig and takes the **highest** free bay index, staging nearest the ramp, while a lighter rig takes the **lowest** free index, staging from the far wall. Bay indices are unique integers, so no tie-break is ever needed. If the candidate set is empty — every bay of the building is already held by a live entry of the stop — the request is rejected with `ERR_NO_STAGING_BAY_AVAILABLE` and no entry is created at all. The chosen index is stored as `staging_bay_index`, and it is cleared to null whenever the entry becomes `WITHDRAWN`.

A new entry opens with `logistics_state` `ENTERED`, `tech_status` `TECH_PENDING`, `actual_arrival_utc` null, `tech_attempt_count` and `failed_attempt_count` at 0, and `branding_slots_committed` at 0. It also gets its first readiness score. The `readiness_score` is an integer between 0 and 100 that expresses how safely and punctually the entry is expected to reach the floor, and `readiness_variant` records which of the two scoring variants produced the value currently on the row. Both variants start from a base of 100 and subtract three penalties, then clamp the result into the range 0 through 100 inclusive.

The haul penalty is common to both variants: 5 points are deducted for every complete block of 500 road miles in the entry's own `haul_distance_miles`, where the number of blocks is the mileage divided by 500 and rounded down to a whole number. A 499-mile haul therefore costs nothing, a 500-mile haul costs 5 points, and a 1,200-mile haul costs 10.

Under the **`PRE_STAGING`** variant, which runs at entry creation while the transporter has not yet arrived and the entry is still `ENTERED`, the schedule penalty is 15 points when the promised `scheduled_arrival_utc` falls later than the staging close instant — that is, later than two hours before `show_start_utc` — and 0 otherwise. The inspection penalty under this variant is always 0, because inspections not yet filed are treated as a provisional pass. Creating an entry sets `readiness_variant` to `PRE_STAGING`.

Under the **`POST_STAGING`** variant, which runs from check-in onwards while the entry is `STAGED` and is recomputed after every inspection attempt, the projection is discarded entirely: the schedule penalty is 15 points when the actual `actual_arrival_utc` is later than the promised `scheduled_arrival_utc`, and 0 otherwise. The inspection penalty is 25 points for each failed attempt the entry has accumulated in `failed_attempt_count`, plus a further 10 points when the most recently filed inspection carries a `result` of `CONDITIONAL`. Check-in and every inspection set `readiness_variant` to `POST_STAGING`.

Check-in is how the transporter's arrival is recorded, moving the entry from `ENTERED` to `STAGED`. It may be called by the owning `CompetitorTeam` or by the promoter, carries an optional `arrival_note`, and requires three things of the stop: its `safety_state` must be `SAFETY_CERTIFIED`, its posture must not be `FROZEN`, and the current logical clock must sit inside the staging window, which opens 8 hours before `show_start_utc` and closes 2 hours before `show_start_utc`, with both bounds inclusive. A clock outside that window is rejected with `ERR_STAGING_WINDOW_CLOSED`; note that `scheduled_arrival_utc` is only a promise and never gates check-in, it only feeds the readiness penalties. On success the entry becomes `STAGED`, `actual_arrival_utc` is stamped from the logical clock, the score is recomputed under `POST_STAGING`, and the entry's `version` increments by one.

Technical inspection is filed by a `SafetyOfficial` against a `STAGED` entry, and each filing creates one immutable `TechInspection` record naming its `vehicle_entry_id`, the `result` (`PASSED`, `CONDITIONAL` or `FAILED`), the worst `defect_severity` found on that attempt (`NONE`, `MINOR`, `MAJOR` or `CRITICAL`), optional `notes`, the `attempt_no` and the filing official as `inspected_by_user_id`. `attempt_no` is a 1-based index computed at insert time as the entry's `tech_attempt_count` plus one. The entry's `tech_attempt_count` is simply the number of inspection rows it has, and `failed_attempt_count` the number of those whose `result` is `FAILED`. An attempt is admissible only while `tech_attempt_count` is still below 3; once three attempts exist, any further filing is rejected with `ERR_TECH_ATTEMPTS_EXHAUSTED`.

The `result` branches the entry's `tech_status`, and the three branches are deliberately unequal. A `PASSED` result moves the entry to `TECH_CLEARED`, increments `tech_attempt_count` and re-scores readiness under `POST_STAGING`. A `CONDITIONAL` result moves the entry to `TECH_CONDITIONAL`, increments `tech_attempt_count` and re-scores readiness, where the 10-point conditional penalty now applies; the entry remains eligible for the run order despite the penalty. A `FAILED` result moves the entry to `TECH_HELD`, increments both `tech_attempt_count` and `failed_attempt_count`, re-scores readiness with the 25-point-per-failure penalty, and — uniquely among the three branches — reaches across to the stop: the stop's posture is recomputed and becomes `RESTRICTED` while any live entry of the stop sits at `TECH_HELD`, which in turn drives a stop that was `ON_SALE` to `SALES_HALTED`.

An entry does not stay held forever. From `TECH_HELD`, a further attempt with `PASSED` moves it to `TECH_CLEARED` and a further attempt with `CONDITIONAL` moves it to `TECH_CONDITIONAL`; in both cases the re-inspection is appended as another attempt, readiness is re-scored under `POST_STAGING` with the earlier failure still counted in `failed_attempt_count`, and the stop's posture is recomputed, which may return it to `OPEN` once no live entry of the stop is held. A further attempt with `FAILED` while already `TECH_HELD` leaves the entry at `TECH_HELD`, appends the attempt, increments `failed_attempt_count` and re-scores readiness — and since the third failure exhausts the attempt budget, no fourth attempt of any kind is admissible.

While an entry is `TECH_HELD` it may neither headline a run-order segment nor carry sponsor branding; both attempts are rejected with `ERR_ENTRY_TECH_HELD`.

### 3.4. Building the Run Order

The floor show is a sequence of segments. Each segment belongs to a stop through `tour_stop_id`, declares a `segment_type` of either `COMPETITION` or `INTERMISSION`, a printed `title`, a 1-based `run_order_position` of at least 1, and `duration_minutes` of at least 1. A `COMPETITION` segment may headline one entry through `featured_vehicle_entry_id`; the field is null for a segment that features nobody. A featured entry must belong to the same stop as the segment — pointing at an entry of another stop is rejected with `ERR_CHILD_STOP_MISMATCH` — and it must not be in `TECH_HELD`.

Positions are unique per stop. Inserting a segment at a `run_order_position` another segment of the stop already occupies is rejected with `ERR_SEGMENT_TIMELINE_CONFLICT`.

Every insert recomputes the whole timeline of the stop. Segments are walked in ascending `run_order_position` — since positions are unique, this ordering has no ties and needs no fallback key — and laid out on half-open minute intervals measured from `show_start_utc`. A running offset starts at 0. For each segment in turn, `reset_gap_minutes` is set to 8 minutes when the immediately preceding position's segment is also of type `COMPETITION` and this segment is of type `COMPETITION`, and to 0 in every other case, including the very first segment; that reset gap accounts for clearing and re-preparing the floor between heats. The offset advances by the reset gap, `start_offset_minutes` is written as the offset, `end_offset_minutes` is written as the offset plus the segment's `duration_minutes`, and the offset then advances to that end value — so segments sit flush against each other with a gap of zero, which is legal. When the walk finishes, the stop's `run_order_end_offset_minutes` is set to the final offset, which is exactly the `end_offset_minutes` of the highest-positioned segment.

Aggregate capacity is then checked: if the recomputed `run_order_end_offset_minutes` is strictly greater than the stop's `show_window_minutes`, the insert is rejected with `ERR_SHOW_WINDOW_EXCEEDED`. Equality is allowed — a run order that fills the window exactly is admissible. Note the asymmetry with venue occupancy: in the run order, an exact touch between two segments is legal, whereas in the building's calendar an exact touch between two padded occupancy intervals is a conflict.

Each insert also refreshes the stop's `competition_segment_count`, which is the number of the stop's segments whose `segment_type` is `COMPETITION`, and recomputes the posture — which matters because a stop with zero competition segments is held at `RESTRICTED` and cannot open sales.

### 3.5. Safety Provisioning, Certification and Suspension

Each stop has at most one safety plan, and a `SafetyOfficial` authors it. Creating a second plan for the same stop is rejected with `ERR_DUPLICATE_CHILD`. The plan declares what has actually been provisioned: `barrier_linear_feet` of concrete barrier, a `catch_fence_height_ft`, `medical_als_staff_count` advanced-life-support medics, `medical_bls_staff_count` basic-life-support medics, `ambulance_count` ambulances on site, and `emergency_access_lanes` unobstructed lanes. None of the six may be negative. Creation records the caller in `authored_by_user_id`, opens the plan in `state` `DRAFT`, and immediately computes the requirement floors.

Those floors are derived from three inputs: the stop's `expected_attendance`, the number of live vehicle entries of the stop (entries whose `logistics_state` is `ENTERED` or `STAGED`), and whether any such live entry is a heavy rig with `vehicle_weight_lbs` of at least 9000 pounds. `expected_attendance` is itself derived as the smaller of the booked venue's `seat_capacity` and the sum of `allotment` over the stop's ticket tiers. The six floors are computed as follows, and every threshold is inclusive:

- `required_als_staff_count` is 1, plus one more when `expected_attendance` is 6000 or greater, plus one more when the live entry count is 12 or greater. An attendance of exactly 6000 already requires the second ALS medic.
- `required_bls_staff_count` is the larger of 2 and the attendance divided by 2500 rounded **up** to a whole number, plus one further medic when the booked venue's `floor_type` is `CONCRETE`.
- `required_ambulance_count` is the larger of 1 and the live entry count divided by 10 rounded **up** to a whole number.
- `required_catch_fence_height_ft` is 8 feet when a heavy rig is present among the live entries and 6 feet otherwise.
- `required_emergency_access_lanes` is 1, plus one more when `expected_attendance` is 6000 or greater.
- `required_barrier_linear_feet` is the larger of 1200 feet and 900 feet plus 75 feet for each live entry.

The plan's `safety_cost_cents` is the provisioning bill that later flows into settlement: each ALS medic costs 45,000 cents, each BLS medic 28,000 cents, each ambulance 120,000 cents, and each linear foot of barrier 350 cents, and the cost is the sum of `medical_als_staff_count`, `medical_bls_staff_count`, `ambulance_count` and `barrier_linear_feet` each multiplied by its own rate. Note that catch fencing and emergency lanes are requirements but carry no cost line.

The floors and the cost are recomputed at five distinct moments: when the plan is created, when a draft is revised, when the plan is submitted, when it is certified, and whenever a ticket tier is added to the stop — because a new tier can raise `expected_attendance`. Entry creation likewise refreshes the stop's requirement figures, since live entries drive ambulances, ALS staffing and barrier footage.

Revising a plan overwrites whichever of the six provisioning fields the request supplies, re-stamps `authored_by_user_id` with the caller, and recomputes the floors and the cost. A revision is admissible from `DRAFT`, where the plan simply stays in `DRAFT`, and from `RETURNED`, where it moves back to `DRAFT`; those two paths are otherwise identical.

Submitting the plan moves it from `DRAFT` to `SUBMITTED`, and is equally admissible from `RETURNED` to `SUBMITTED` with exactly the same preconditions and side effects — which is how the plan cycle `DRAFT → SUBMITTED → RETURNED → DRAFT` repeats. Submission first recomputes all six floors and `safety_cost_cents`, then requires four things to hold against the fresh figures: `medical_als_staff_count` must be at least `required_als_staff_count` and `medical_bls_staff_count` at least `required_bls_staff_count`, or the request is rejected with `ERR_MEDICAL_STAFFING_SHORTFALL`; `ambulance_count` must be at least `required_ambulance_count`, or `ERR_AMBULANCE_SHORTFALL`; `catch_fence_height_ft` must be at least `required_catch_fence_height_ft` and at the same time no greater than the booked venue's `catch_fence_max_height_ft`, or `ERR_CATCH_FENCE_INSUFFICIENT`; `emergency_access_lanes` must be at least `required_emergency_access_lanes`, or `ERR_EMERGENCY_ACCESS_INSUFFICIENT`; and `barrier_linear_feet` must be at least `required_barrier_linear_feet`, or `ERR_BARRIER_INSUFFICIENT`. On success the plan becomes `SUBMITTED` and the stop's `safety_state` moves from `SAFETY_DRAFT` to `SAFETY_REVIEW`, with the posture recomputed.

Certification moves a `SUBMITTED` plan to `CERTIFIED`. It carries an optional `note`, requires that the caller not be the plan's author, and re-checks the identical four provisioning conditions against freshly recomputed floors — a plan that was adequate at submission but was overtaken by a new tier or a new entry in the meantime fails certification with the same shortfall errors listed above. On success `certified_by_user_id` is set to the caller, and the stop's `safety_state` moves from `SAFETY_REVIEW` to `SAFETY_CERTIFIED`, with the posture recomputed — which is the moment a stop can first become `OPEN`.

Returning a `SUBMITTED` plan sends it to `RETURNED` with no preconditions at all. The supplied `reason` is stored as `return_reason`, `return_count` increments by one, and the stop's `safety_state` moves from `SAFETY_REVIEW` back to `SAFETY_DRAFT` with the posture recomputed. `return_count` therefore records how many times the plan has left `SUBMITTED` or `CERTIFIED` for `RETURNED`, counting both operator returns and the automatic return described in Cascade B.

The safety dimension of a stop also has a suspension cycle that is independent of the plan's own state. A `SafetyOfficial` may suspend a stop whose `safety_state` is `SAFETY_CERTIFIED` as long as its `sales_state` is not `SETTLED`, supplying a `reason`. Suspension moves `safety_state` to `SAFETY_SUSPENDED`, recomputes the posture to `FROZEN`, and — because the posture left `OPEN` — drives a stop that was `ON_SALE` to `SALES_HALTED`, which voids every `PENDING` order of the stop and releases their reserved seats. Reinstatement, also by a `SafetyOfficial` and carrying an optional `note`, moves `safety_state` from `SAFETY_SUSPENDED` back to `SAFETY_CERTIFIED`; it is admissible only while the stop's safety plan is still in `CERTIFIED` and the stop's `sales_state` is not `SETTLED`, and it recomputes the posture, which becomes `OPEN` when every other readiness condition still holds and `RESTRICTED` otherwise. Reinstatement deliberately does **not** restore sales: a stop halted by a suspension stays at `SALES_HALTED` until a `TicketingManager` resumes it. Cascade A also drives the safety dimension to `SAFETY_SUSPENDED`, whether the stop was `SAFETY_CERTIFIED` or `SAFETY_DRAFT` at the time.

### 3.6. Pricing Tiers and Seat Inventory

A `TicketingManager` builds the price card for a stop one tier at a time. A tier declares a `tier_code` that must be unique among the stop's tiers — a repeat is rejected with `ERR_DUPLICATE_TIER_CODE` — a face `price_cents` of zero or more, and an `allotment` of at least 1 seat, which is the conserved seat pool for that tier. Group-sales terms are `group_min_qty`, the minimum seats on one order to qualify for the group rate, which must be at least 1 and defaults to 20, and `group_discount_pct`, the discount applied to the ticket line when the threshold is met, which must lie between 0 and 1 inclusive and defaults to 0.125. The selling window is declared as `on_sale_start_utc` and `on_sale_end_utc`; `on_sale_start_utc` must be strictly earlier than `on_sale_end_utc` and `on_sale_end_utc` may not fall after the stop's `show_start_utc`, or the tier is rejected with `ERR_TIER_WINDOW_INVALID`.

The tier's four seat buckets are all derived. `reserved_seat_count` is the sum of `qty` over the tier's orders in `PENDING`; `sold_seat_count` the same sum over orders in `PAID`; `held_seat_count` the sum of `hospitality_seat_count` over sponsorship activations that name this tier for hospitality and sit in `ACTIVATED` or `FULFILLED`; and `available_seat_count` is the `allotment` minus all three of those, as the conservation rule in §2.5 requires.

Adding a tier has consequences beyond the price card. It recomputes the stop's `expected_attendance` as the smaller of the venue's `seat_capacity` and the new sum of tier allotments, and then recomputes the stop's safety requirement floors. If the fresh floors outrun what a `CERTIFIED` plan provisioned — that is, if at least one of `medical_als_staff_count`, `medical_bls_staff_count`, `ambulance_count`, `emergency_access_lanes`, `barrier_linear_feet` or `catch_fence_height_ft` now sits below its corresponding requirement — Cascade B fires exactly as described in §2.9: the plan is auto-returned with `return_reason` set to `AUTO_REQUIREMENT_INCREASE`, the stop's safety dimension drops from `SAFETY_CERTIFIED` to `SAFETY_DRAFT`, the posture becomes `RESTRICTED`, a stop that was `ON_SALE` is halted, and its `PENDING` orders are voided with their reserved seats released. Selling more seats can therefore stop the sale, which is the intended serialization point between the box office and the safety desk.

### 3.7. The Sales Window: Orders, Payment and Refunds

The ticketing dimension of a stop opens at `SALES_PENDING`. A `TicketingManager` takes it on sale, moving `sales_state` from `SALES_PENDING` to `ON_SALE`, and four conditions must hold: the stop's `safety_state` must be `SAFETY_CERTIFIED`, its `competition_segment_count` must be at least 1, it must have at least one ticket tier, and its `readiness_posture` must be `OPEN`. Each failure has its own error, and they are reported in the precedence order of §2.10: `ERR_SAFETY_NOT_CERTIFIED`, then `ERR_RUN_ORDER_INCOMPLETE`, then `ERR_NO_TICKET_TIERS`, and finally `ERR_STOP_NOT_READY` for a stop that passes all three specific checks but still fails the derived posture — which happens, for instance, when a live entry is `TECH_HELD` or when no marketing money has been committed to the market yet. Going on sale increments the stop's `version`.

Sales halt and resume in a cycle. The halt is always automatic, driven by the posture leaving `OPEN` as described in §2.8. Resumption is an operator act: a `TicketingManager` moves the stop from `SALES_HALTED` back to `ON_SALE`, which requires the posture to be `OPEN` again and re-runs the same certification and readiness gates as going on sale, reporting `ERR_SAFETY_NOT_CERTIFIED` and `ERR_STOP_NOT_READY` on the same terms. Resuming increments the stop's `version`. Closing sales ahead of settlement is admissible from either `ON_SALE` or `SALES_HALTED`, with identical effects in both cases and no preconditions: `sales_state` becomes `SALES_CLOSED`, every `PENDING` order of the stop moves to `VOID` with `void_reason` set to `SALES_CLOSED` and its reserved seats released, and the stop's `version` increments.

An order is placed against one tier of one stop. It names `tour_stop_id` and `ticket_tier_id`, the buyer as `purchaser_name` and `purchaser_email`, the seat count as `qty` (at least 1), the concurrency token `expected_ticket_tier_version` described in §2.7, an optional `is_group` flag defaulting to false, and an optional `pit_party_addon_qty` defaulting to 0 and never negative. The named tier must belong to the named stop, or the order is rejected with `ERR_CHILD_STOP_MISMATCH`. The stop's `sales_state` must be exactly `ON_SALE` — `SALES_PENDING`, `SALES_HALTED` and `SALES_CLOSED` all yield `ERR_SALES_NOT_OPEN`. The current logical clock must sit inside the tier's selling window running from `on_sale_start_utc` to `on_sale_end_utc`, with both bounds inclusive; outside it, the order is rejected with `ERR_TIER_WINDOW_CLOSED`. If `is_group` is true, `qty` must reach the tier's `group_min_qty`, or the order is rejected with `ERR_GROUP_MINIMUM_NOT_MET`. Pit party heads are capped twice: `pit_party_addon_qty` may not exceed `qty`, and the stop's `pit_party_sold_count` plus this order's `pit_party_addon_qty` may not exceed the stop's `pit_party_capacity`; either breach is rejected with `ERR_PIT_PARTY_CAPACITY_EXCEEDED`. Last of all, the tier's `available_seat_count` must be at least `qty`, or the order is rejected with `ERR_TIER_SOLD_OUT`.

The order's money is computed once, at creation, and frozen on the row; it is never recomputed afterwards, even if the tier's price or the stop's pit party price later changes. Six figures are written, and the rounding order is pinned — each percentage component is rounded to whole cents on its own line, in the order below, and only then are the lines summed. Rounding the two discounts together after adding them produces a different total and is wrong.

1. `line_subtotal_cents` is the tier's `price_cents` multiplied by `qty`.
2. The group rate applies when `is_group` is true **and** `qty` is at least the tier's `group_min_qty`. When it applies, `group_discount_cents` is `line_subtotal_cents` multiplied by the tier's `group_discount_pct`, rounded half up to whole cents; when it does not apply, `group_discount_cents` is 0.
3. `addon_subtotal_cents` is the stop's `pit_party_price_cents` multiplied by `pit_party_addon_qty`.
4. The pit party bundle rate applies when `pit_party_addon_qty` is greater than 0 **and** exactly equal to `qty` — every seat on the order brings a head to the pit party. When it applies, `addon_discount_cents` is `addon_subtotal_cents` multiplied by 15 percent, rounded half up to whole cents; when it does not apply, `addon_discount_cents` is 0.
5. `facility_fee_cents` is the `per_ticket_facility_fee_cents` from the stop's booking — the terms in force when the booking was confirmed — multiplied by `qty`. The facility fee is never discounted.
6. `total_cents` is `line_subtotal_cents` minus `group_discount_cents`, plus `addon_subtotal_cents` minus `addon_discount_cents`, plus `facility_fee_cents`.

A created order opens with `status` `PENDING`, `paid_at`, `refunded_at` and `void_reason` all null; its `qty` is added to the tier's `reserved_seat_count`, `available_seat_count` falls by the same amount, and the tier's `version` increments by one — which is exactly why the next client to write against that tier needs a fresh `expected_ticket_tier_version`.

Paying an order moves it from `PENDING` to `PAID`. It is admissible while the stop's `sales_state` is `ON_SALE` **or** `SALES_HALTED` — a halt does not strand money that has already been committed — and while the stop's posture is not `FROZEN`. Payment stamps `paid_at` from the logical clock, moves `qty` from the tier's `reserved_seat_count` to its `sold_seat_count` while leaving `available_seat_count` unchanged, and adds four amounts and two counts to the stop's roll-ups: `line_subtotal_cents` minus `group_discount_cents` goes to `gross_ticket_revenue_cents`, `addon_subtotal_cents` minus `addon_discount_cents` goes to `addon_revenue_cents`, `facility_fee_cents` goes to `facility_fee_collected_cents`, `qty` goes to `tickets_sold_count`, and `pit_party_addon_qty` goes to `pit_party_sold_count`. Both the tier's and the stop's `version` increment by one.

Refunding an order moves it from `PAID` to `REFUNDED` with a supplied `reason`, and is admissible as long as the stop's `sales_state` is not `SETTLED`. It stamps `refunded_at` from the logical clock, decrements the tier's `sold_seat_count` by `qty` and restores `available_seat_count` — the seat conservation invariant again — and subtracts exactly the same four money and count amounts from the stop's roll-ups that payment added. Both the tier's and the stop's `version` increment. A refund does **not** change the state of an existing settlement sitting at `PREPARED`; the recomputation performed at approval picks the refund up instead.

Voiding is never an operator act. An order in `PENDING` moves to `VOID` only because the server drove it there — a halt, a close, or a stop cancellation — and `void_reason` records which cause applied, taking the value `SALES_HALTED`, `SALES_CLOSED` or `STOP_CANCELLED` respectively. Voiding decrements the tier's `reserved_seat_count` by `qty` and recomputes `available_seat_count`. `REFUNDED` and `VOID` are both terminal for an order.

### 3.8. Sponsorship Activation: Branding, Signage and Hospitality

A sponsor is registered with a `company_name`, a `contact_email`, and a `category` drawn from `FUEL`, `TIRE`, `BEVERAGE`, `RETAIL` and `AUTOMOTIVE`. The boolean `exclusive_category`, which defaults to false, is the sponsor's claim to be the only brand of its category live at a stop.

An activation is the package a sponsor buys at one stop. It names `sponsor_id` and `tour_stop_id`, an activation `fee_cents` of zero or more, the `vehicle_branding_slots` bought on a vehicle, the `signage_units` owed at the building, and an optional `hospitality_seat_count` defaulting to 0 — all three counts must be zero or greater. Where branding is bought, `branded_vehicle_entry_id` names the entry that will carry it, and is null when no branding is bought; where hospitality is bought, `hospitality_tier_id` names the tier the seats are held against, and is null when `hospitality_seat_count` is 0. A `SponsorRep` may propose only its own sponsor's packages; the promoter may propose on any sponsor's behalf. Both the named tier and the named entry must belong to the addressed stop, or the proposal is rejected with `ERR_CHILD_STOP_MISMATCH`, and a branded entry sitting at `TECH_HELD` is rejected with `ERR_ENTRY_TECH_HELD`. At proposal time the branding capacity and hospitality capacity are already checked: committed slots on the branded entry plus the requested `vehicle_branding_slots` may not exceed 4 slots per vehicle, or the proposal is rejected with `ERR_BRANDING_SLOTS_EXCEEDED`; and the hospitality seats already held on the named tier plus the requested `hospitality_seat_count` may not push past that tier's `allotment`, or the proposal is rejected with `ERR_HOSPITALITY_SEATS_EXCEEDED`. A proposed activation opens in `state` `PROPOSED` with `recognized_fee_cents` at 0 and `obligations_fulfilled_at` null.

Activation is the promoter's act, moving the package from `PROPOSED` to `ACTIVATED`. Four conditions guard it. The stop's posture must not be `FROZEN`. When `hospitality_seat_count` is greater than 0, `hospitality_tier_id` must be set, must belong to the same stop, and that tier's `available_seat_count` must be at least `hospitality_seat_count` — the same hospitality ceiling against the tier's `allotment` is re-checked here and reported as `ERR_HOSPITALITY_SEATS_EXCEEDED`. When `vehicle_branding_slots` is greater than 0, `branded_vehicle_entry_id` must be set, must belong to the same stop, and the entry's `branding_slots_committed` plus the requested slots must not exceed 4. And category exclusivity must hold: if another activation on the same stop sits in `ACTIVATED` or `FULFILLED` whose sponsor has the same `category` as this one, and either of the two sponsors has `exclusive_category` set to true, the request is rejected with `ERR_SPONSOR_CATEGORY_EXCLUSIVITY`.

Activation moves money and inventory in four places. The `hospitality_seat_count` is added to the named tier's `held_seat_count`, that tier's `available_seat_count` is recomputed and its `version` increments by one — which is another reason a box-office client's `expected_ticket_tier_version` can go stale without any order being written. The `vehicle_branding_slots` are added to the branded entry's `branding_slots_committed`, which is the sum of slots over activations naming that entry in `ACTIVATED` or `FULFILLED`. The `fee_cents` is added to the stop's `sponsorship_committed_cents`, which sums fees over the stop's activations in `ACTIVATED` or `FULFILLED`, and the `hospitality_seat_count` is added to the stop's `held_hospitality_seat_count`, which sums hospitality seats over the same set.

Fulfilment is the sign-off that signage, branding and hospitality obligations were actually delivered, moving the activation from `ACTIVATED` to `FULFILLED`. It may be performed by the owning `SponsorRep` or by the promoter, carries an optional `note`, and requires the stop's `sales_state` to be `ON_SALE`, `SALES_HALTED` or `SALES_CLOSED`. It stamps `obligations_fulfilled_at` from the logical clock and sets `recognized_fee_cents` to the full `fee_cents`, because no holdback ever applies to a fulfilled activation under either settlement variant. `FULFILLED` is terminal.

### 3.9. Market Economics: Marketing Spend, Settlement and Season Close

Local promotion is bought per market and per channel. An allocation names the stop through `tour_stop_id`, a `channel` of `RADIO`, `DIGITAL` or `GRASSROOTS`, an `amount_cents` of at least 1, and the season concurrency token `expected_season_version` from §2.7. Three ceilings apply, checked in this order. The per-stop ceiling is 20 percent of the season's `total_marketing_budget_cents`, rounded half up to whole cents; each channel's ceiling is a share of that stop ceiling, again rounded half up — 40 percent for `RADIO`, 60 percent for `DIGITAL` and 30 percent for `GRASSROOTS`. First, the channel running total after this commit — the sum of `amount_cents` over the stop's `COMMITTED` allocations on the same channel, plus this `amount_cents` — must not exceed that channel's ceiling, or the request is rejected with `ERR_CHANNEL_CAP_EXCEEDED`. Second, the stop running total after this commit — the stop's `marketing_spend_committed_cents` plus this `amount_cents` — must not exceed the stop ceiling, or the request is rejected with `ERR_STOP_MARKETING_CAP_EXCEEDED`. Third, `amount_cents` must not exceed the season's `marketing_unallocated_cents`, or the request is rejected with `ERR_MARKETING_BUDGET_EXCEEDED`. All caps are inclusive: a running total landing exactly on a ceiling is admitted. Allocations in `RELEASED` are excluded from both running totals.

A committed allocation opens in `state` `COMMITTED` with `released_at` null. The commit adds `amount_cents` to the season's `marketing_allocated_cents`, recomputes `marketing_unallocated_cents` as the total budget minus the allocated figure, increments the season's `version` by one, adds `amount_cents` to the stop's `marketing_spend_committed_cents`, and recomputes the stop's posture — which is how the first marketing dollar in a market lifts one of the conditions holding the stop at `RESTRICTED`.

Releasing an allocation moves it from `COMMITTED` to `RELEASED`, stamps `released_at` from the logical clock, and applies exactly the inverse deltas: the amount comes off `marketing_allocated_cents`, `marketing_unallocated_cents` is restored, the season's `version` increments by one, the stop's `marketing_spend_committed_cents` falls, and the posture is recomputed — which can pull a stop back to `RESTRICTED` if the release leaves the market with no committed spend at all, halting an `ON_SALE` stop. The released row is returned so the conserved ledger is observable. Cascade A releases allocations the same way when a confirmed booking is withdrawn.

Settlement is prepared by a `FinanceController`. Preparation deliberately does **not** require sales to be closed — a promoter may cut a provisional settlement mid-window — but it does require that the stop already have a safety plan, or the request is rejected with `ERR_SAFETY_PLAN_MISSING`, and that no order of the stop is still in `PENDING`, or the request is rejected with `ERR_PENDING_ORDERS_OUTSTANDING`. A stop that already has a settlement row that is not `DISPUTED` cannot have a second one: that is rejected with `ERR_DUPLICATE_CHILD`. Preparation writes every money field under the `PROVISIONAL` variant, sets `variant` to `PROVISIONAL`, `state` to `PREPARED`, and `prepared_by_user_id` to the caller. Re-preparation out of `DISPUTED` runs the same computation and re-stamps `prepared_by_user_id`, but carries two additional preconditions: the stop's `sales_state` must be `SALES_CLOSED` and no order of the stop may be `PENDING`. Re-preparation leaves `dispute_count` and `dispute_reason` in place.

The settlement's revenue side is assembled from an **inclusion set** that depends on the active variant. Under `PROVISIONAL`, the included orders are those whose `status` is `PAID` as of preparation, and each activation in `ACTIVATED` or `FULFILLED` recognizes its full `fee_cents` with no holdback. Under `FINAL`, the included orders are those whose `status` is `PAID` as of approval — so anything refunded after preparation drops out — and recognition splits: an activation in `FULFILLED` recognizes its full `fee_cents`, while an activation still in `ACTIVATED` recognizes only its `fee_cents` multiplied by 50 percent, rounded half up to whole cents. Orders in `REFUNDED`, `VOID` or `PENDING` never contribute to either variant.

Over the included set, the settlement writes: `ticket_revenue_cents` as the sum of each included order's `line_subtotal_cents` minus its `group_discount_cents`; `addon_revenue_cents` as the sum of each included order's `addon_subtotal_cents` minus its `addon_discount_cents`; `facility_fee_cents` as the sum of the included orders' `facility_fee_cents`; and `sponsorship_revenue_cents` as the sum of the recognized fee over the stop's included activations. Three cost figures come from elsewhere on the stop: `marketing_spend_cents` is the sum of `amount_cents` over the stop's allocations in `COMMITTED`; `safety_cost_cents` is copied from the stop's safety plan, and is 0 when the stop has no plan; and `purse_cents` is the competitor purse, 150,000 cents for every vehicle entry of the stop whose `logistics_state` is `STAGED`.

The venue's money is computed next, and its evaluation order is pinned because the co-op credit rate is keyed on the very total the credit then reduces. The adjusted gross is the sum, over included orders, of `line_subtotal_cents` minus `group_discount_cents`, and the facility fee total is the sum of their `facility_fee_cents`. The share component is the adjusted gross multiplied by the booking's `revenue_share_pct`, rounded half up to whole cents. `rental_due_pre_credit_cents` is then the greater of the booking's `rental_base_cents` and that share component, plus the facility fee total. The co-op credit rate `coop_credit_pct` is selected from that pre-credit figure with inclusive boundaries: 0.06 when `rental_due_pre_credit_cents` is 5,000,000 cents or more, otherwise 0.04 when it is 2,500,000 cents or more, otherwise 0.02. The rate is **not** re-selected after the credit is applied. `coop_credit_cents` is then the smaller of two figures: the pre-credit total multiplied by `coop_credit_pct` and rounded half up to whole cents, and the stop's `marketing_spend_committed_cents` — the building only co-ops against marketing money that was actually committed in its market. `venue_due_cents` is `rental_due_pre_credit_cents` minus `coop_credit_cents`.

Two summary figures close the accounting. `collected_cash_cents` is `ticket_revenue_cents` plus `addon_revenue_cents` plus `facility_fee_cents` plus `sponsorship_revenue_cents`. `net_to_promoter_cents` is `collected_cash_cents` minus `venue_due_cents`, minus `safety_cost_cents`, minus `marketing_spend_cents`, minus `purse_cents`, and it may legitimately be negative. `profitability_margin_pct` is `net_to_promoter_cents` divided by `collected_cash_cents`, multiplied by 100 and rounded half up to two decimal places when `collected_cash_cents` is greater than 0; when collected cash is 0 the margin is 0.00.

Immediately after those figures, and in both variants, the payout waterfall funds four buckets in this exact order out of `collected_cash_cents`. A running remainder starts at the collected cash. `payout_venue_cents` is the smaller of the remainder and `venue_due_cents`, and the remainder falls by that amount. `payout_safety_cents` is then the smaller of the remainder and `safety_cost_cents`, and the remainder falls again. `payout_marketing_cents` is the smaller of the remainder and `marketing_spend_cents`. `payout_purse_cents` is the smaller of the remainder and `purse_cents`. Whatever survives all four buckets is `promoter_remainder_cents`, which is never negative by construction. `shortfall_cents` is the total unfunded obligation: the amount by which `venue_due_cents` exceeded its payout, plus the same difference for safety, plus marketing, plus purse. These are integer subtractions with no rounding, and every settlement must satisfy the identity that `net_to_promoter_cents` equals `promoter_remainder_cents` minus `shortfall_cents` under both variants.

A prepared settlement may be disputed, which is the loop that lets the building push back. Dispute is available to a `FinanceController` and to the `VenueManager` of the booked venue; when the caller is a `VenueManager`, their `X-User-ID` must equal the venue named by the stop's booking, or the request is rejected with `ERR_OWNERSHIP_MISMATCH`. The supplied `dispute_reason` is recorded, `dispute_count` increments by one, and the settlement moves from `PREPARED` to `DISPUTED`. `PREPARED → DISPUTED → PREPARED` repeats until the building accepts and finance approves.

Approval is the terminal act, performed by a `FinanceController` who is not the preparer and carrying an optional `note`. It requires the settlement to be `PREPARED` and the stop's `sales_state` to be `SALES_CLOSED`. Approval re-runs every money field under the `FINAL` variant — including the venue computation over the smaller inclusion set, which can flip which of `rental_base_cents` and the share component is the larger and can re-select the co-op tier — sets `variant` to `FINAL`, `state` to `APPROVED` and `approved_by_user_id` to the caller, and then fires Cascade C as described in §2.9: the stop moves from `SALES_CLOSED` to `SETTLED`, the season's `settled_stop_count` and `season_net_cents` and `version` all advance, and the season closes when no stop of the season remains outside `SETTLED` and `CANCELLED`.

The season's by-market report closes the loop for the promoter and the settlement desk. It groups the season's stops whose `sales_state` is `SETTLED` and whose settlement reached `APPROVED` by `market_code`, and emits one row per market containing that `market_code`, the `stop_count` of those stops in the market, the summed `collected_cash_cents`, the summed `net_to_promoter_cents`, and a `margin_pct` computed as the summed net divided by the summed collected cash, multiplied by 100 and rounded half up to two decimal places when the summed collected cash is greater than 0, and 0.00 otherwise. The rows are returned in `market_rows`, ordered by `net_to_promoter_cents` descending with `market_code` ascending as the tie-break. Alongside them the report carries the `season_id`, a `total_net_cents` that sums the rows' net figures, a `settled_stop_count` counting the season's stops whose `sales_state` is `SETTLED`, and an `unsettled_stop_count` counting the season's stops whose `sales_state` is neither `SETTLED` nor `CANCELLED`. Cancelled stops, and stops whose settlement is still `PREPARED` or `DISPUTED`, contribute to `unsettled_stop_count` only and never to a market row.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created` — season, venue, booking, competitor, vehicle entry, inspection, run-order segment, ticket tier, ticket order, sponsor, activation, safety plan, marketing allocation and settlement preparation, the last of these including a re-preparation out of dispute. Every other successful operation, including state transitions, partial updates, releases and reads, returns `200 OK`. Request bodies, response payloads and side effects are not repeated here — they are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/seasons` | Create a season with its calendar window, rotation cooldown and marketing budget | SeriesPromoter |
| GET | `/seasons/{id}` | Read one season including its marketing ledger and settled-stop counters | SeriesPromoter, FinanceController, TicketingManager |
| GET | `/seasons/{id}/market-report` | Profitability by market across the season's approved settlements | SeriesPromoter, FinanceController |
| POST | `/venues` | Register a building with its capacity, floor type, rigging limit, staging bays and turnaround buffer | SeriesPromoter |
| GET | `/venues/{id}` | Read one venue | SeriesPromoter, VenueManager, SafetyOfficial, FinanceController |
| POST | `/venue-bookings` | Propose rental terms for a date at a venue | SeriesPromoter |
| GET | `/venue-bookings` | List bookings, filterable by season, venue and state | SeriesPromoter, VenueManager, FinanceController |
| GET | `/venue-bookings/{id}` | Read one booking with the terms currently on the row | SeriesPromoter, VenueManager, FinanceController |
| POST | `/venue-bookings/{id}/counter` | Venue counters the terms | VenueManager |
| POST | `/venue-bookings/{id}/revise` | Promoter re-proposes terms after a counter | SeriesPromoter |
| POST | `/venue-bookings/{id}/accept` | Accept the terms on the row and synthesize the tour stop | SeriesPromoter |
| POST | `/venue-bookings/{id}/withdraw` | Withdraw the booking | SeriesPromoter |
| GET | `/tour-stops` | List tour stops, filterable by season, booking, transport predecessor, market and sales state | SeriesPromoter, VenueManager, TicketingManager, SafetyOfficial, FinanceController, CompetitorTeam |
| GET | `/tour-stops/{id}` | Read one stop with both state dimensions, the readiness posture and every roll-up | SeriesPromoter, VenueManager, TicketingManager, SafetyOfficial, FinanceController, CompetitorTeam, SponsorRep |
| PATCH | `/tour-stops/{id}/logistics` | Set show timing, pit party terms and the transport chain link | SeriesPromoter |
| POST | `/tour-stops/{id}/on-sale` | Open ticket sales | TicketingManager |
| POST | `/tour-stops/{id}/close-sales` | Close ticket sales ahead of settlement | TicketingManager |
| POST | `/tour-stops/{id}/resume-sales` | Return a halted stop to sale | TicketingManager |
| POST | `/tour-stops/{id}/safety-suspend` | Suspend the stop on safety grounds | SafetyOfficial |
| POST | `/tour-stops/{id}/safety-reinstate` | Lift a safety suspension | SafetyOfficial |
| POST | `/competitors` | Register a competing team | SeriesPromoter |
| GET | `/competitors/{id}` | Read one competitor | SeriesPromoter, CompetitorTeam, SafetyOfficial |
| POST | `/vehicle-entries` | Enter a vehicle in a stop and assign its staging bay | SeriesPromoter, CompetitorTeam |
| GET | `/vehicle-entries` | List entries, filterable by stop, competitor and logistics state | SeriesPromoter, CompetitorTeam, SafetyOfficial, SponsorRep |
| GET | `/vehicle-entries/{id}` | Read one entry with its staging bay, tech status and readiness score | SeriesPromoter, CompetitorTeam, SafetyOfficial, SponsorRep |
| POST | `/vehicle-entries/{id}/check-in` | Record the transporter's arrival at the staging bay | SeriesPromoter, CompetitorTeam |
| POST | `/vehicle-entries/{id}/tech-inspections` | File one technical inspection attempt | SafetyOfficial |
| GET | `/vehicle-entries/{id}/tech-inspections` | Full inspection history of an entry | SeriesPromoter, SafetyOfficial, CompetitorTeam |
| GET | `/tech-inspections/{id}` | Read one filed inspection attempt | SeriesPromoter, SafetyOfficial, CompetitorTeam |
| GET | `/vehicle-entries/{id}/featured-segments` | Run-order segments that headline this entry | SeriesPromoter, CompetitorTeam, SponsorRep |
| POST | `/tour-stops/{id}/show-segments` | Insert a competition or intermission segment into the run order | SeriesPromoter |
| GET | `/tour-stops/{id}/show-segments` | Run order of the stop | SeriesPromoter, TicketingManager, SafetyOfficial, SponsorRep |
| GET | `/show-segments/{id}` | Read one segment with its computed timeline offsets | SeriesPromoter, TicketingManager, SafetyOfficial, SponsorRep |
| POST | `/tour-stops/{id}/ticket-tiers` | Add a pricing tier to the stop | TicketingManager |
| GET | `/tour-stops/{id}/ticket-tiers` | Tiers of the stop | SeriesPromoter, TicketingManager, FinanceController, SponsorRep |
| GET | `/ticket-tiers/{id}` | Read one tier with its conserved seat pool | SeriesPromoter, TicketingManager, FinanceController, SponsorRep |
| POST | `/ticket-orders` | Place an order against a tier | TicketingManager |
| GET | `/ticket-orders` | List orders, filterable by stop, tier and status | SeriesPromoter, TicketingManager, FinanceController |
| GET | `/ticket-orders/{id}` | Read one order with its frozen money breakdown | SeriesPromoter, TicketingManager, FinanceController |
| POST | `/ticket-orders/{id}/pay` | Settle a pending order | TicketingManager |
| POST | `/ticket-orders/{id}/refund` | Refund a paid order | TicketingManager |
| POST | `/sponsors` | Register a sponsor and its category exclusivity claim | SeriesPromoter |
| GET | `/sponsors/{id}` | Read one sponsor | SeriesPromoter, SponsorRep, FinanceController |
| POST | `/sponsorship-activations` | Propose an activation package | SeriesPromoter, SponsorRep |
| GET | `/sponsorship-activations` | List activations, filterable by sponsor, stop, hospitality tier, branded entry and state | SeriesPromoter, SponsorRep, FinanceController, TicketingManager |
| GET | `/sponsorship-activations/{id}` | Read one activation | SeriesPromoter, SponsorRep, FinanceController |
| POST | `/sponsorship-activations/{id}/activate` | Activate the package | SeriesPromoter |
| POST | `/sponsorship-activations/{id}/fulfill` | Sign off that the activation's obligations were delivered | SeriesPromoter, SponsorRep |
| POST | `/tour-stops/{id}/safety-plan` | Create the stop's single safety plan | SafetyOfficial |
| GET | `/tour-stops/{id}/safety-plan` | The stop's safety plan as an array of length 0 or 1 | SeriesPromoter, SafetyOfficial, FinanceController, VenueManager |
| GET | `/safety-plans/{id}` | Read one plan with provisioned and required figures side by side | SeriesPromoter, SafetyOfficial, FinanceController, VenueManager |
| PATCH | `/safety-plans/{id}` | Revise a plan's provisioning | SafetyOfficial |
| POST | `/safety-plans/{id}/submit` | Submit the plan for certification | SafetyOfficial |
| POST | `/safety-plans/{id}/certify` | Certify a submitted plan | SafetyOfficial |
| POST | `/safety-plans/{id}/return` | Return a submitted plan for rework | SafetyOfficial |
| POST | `/tour-stops/{id}/marketing-allocations` | Commit local marketing spend on one channel | SeriesPromoter |
| GET | `/tour-stops/{id}/marketing-allocations` | Allocations of the stop | SeriesPromoter, FinanceController |
| GET | `/marketing-allocations/{id}` | Read one allocation | SeriesPromoter, FinanceController |
| DELETE | `/marketing-allocations/{id}` | Release a committed allocation back to the season pool | SeriesPromoter |
| POST | `/tour-stops/{id}/settlement` | Prepare the stop's settlement under the provisional variant | FinanceController |
| GET | `/tour-stops/{id}/settlement` | The stop's settlement as an array of length 0 or 1 | SeriesPromoter, FinanceController, VenueManager |
| GET | `/settlements/{id}` | Read one settlement with its variant, waterfall buckets and margin | SeriesPromoter, FinanceController, VenueManager |
| POST | `/settlements/{id}/approve` | Approve the settlement under the final variant | FinanceController |
| POST | `/settlements/{id}/dispute` | Dispute a prepared settlement | FinanceController, VenueManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SeriesPromoter, VenueManager, CompetitorTeam, SafetyOfficial, TicketingManager, SponsorRep, FinanceController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SAFETY_SELF_CERTIFICATION` | 403 |
| `ERR_SETTLEMENT_SELF_APPROVAL` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_SEASON_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_VENUE_BOOKING_NOT_FOUND` | 404 |
| `ERR_TOUR_STOP_NOT_FOUND` | 404 |
| `ERR_COMPETITOR_NOT_FOUND` | 404 |
| `ERR_VEHICLE_ENTRY_NOT_FOUND` | 404 |
| `ERR_TECH_INSPECTION_NOT_FOUND` | 404 |
| `ERR_SHOW_SEGMENT_NOT_FOUND` | 404 |
| `ERR_TICKET_TIER_NOT_FOUND` | 404 |
| `ERR_TICKET_ORDER_NOT_FOUND` | 404 |
| `ERR_SPONSOR_NOT_FOUND` | 404 |
| `ERR_SPONSORSHIP_ACTIVATION_NOT_FOUND` | 404 |
| `ERR_SAFETY_PLAN_NOT_FOUND` | 404 |
| `ERR_MARKETING_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_STALE_TIER_VERSION` | 412 |
| `ERR_STALE_SEASON_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_SALES_NOT_OPEN` | 409 |
| `ERR_STOP_FROZEN` | 409 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_SAFETY_NOT_CERTIFIED` | 409 |
| `ERR_MEDICAL_STAFFING_SHORTFALL` | 422 |
| `ERR_AMBULANCE_SHORTFALL` | 422 |
| `ERR_CATCH_FENCE_INSUFFICIENT` | 422 |
| `ERR_EMERGENCY_ACCESS_INSUFFICIENT` | 422 |
| `ERR_BARRIER_INSUFFICIENT` | 422 |
| `ERR_ENTRY_TECH_HELD` | 409 |
| `ERR_TECH_ATTEMPTS_EXHAUSTED` | 409 |
| `ERR_RUN_ORDER_INCOMPLETE` | 409 |
| `ERR_NO_TICKET_TIERS` | 409 |
| `ERR_PENDING_ORDERS_OUTSTANDING` | 409 |
| `ERR_CHILD_STOP_MISMATCH` | 422 |
| `ERR_SAFETY_PLAN_MISSING` | 409 |
| `ERR_DATE_OUTSIDE_SEASON` | 422 |
| `ERR_BOOKING_LEAD_TIME` | 422 |
| `ERR_VENUE_DATE_CONFLICT` | 409 |
| `ERR_HAUL_BUFFER_VIOLATION` | 409 |
| `ERR_SEGMENT_TIMELINE_CONFLICT` | 409 |
| `ERR_TIER_WINDOW_INVALID` | 422 |
| `ERR_TIER_WINDOW_CLOSED` | 409 |
| `ERR_SHOW_TIMING_INVALID` | 422 |
| `ERR_STAGING_WINDOW_CLOSED` | 409 |
| `ERR_MARKET_ROTATION_COOLDOWN` | 409 |
| `ERR_ROTATION_CHAIN_INVALID` | 422 |
| `ERR_SHOW_WINDOW_EXCEEDED` | 409 |
| `ERR_GROUP_MINIMUM_NOT_MET` | 422 |
| `ERR_PIT_PARTY_CAPACITY_EXCEEDED` | 409 |
| `ERR_BRANDING_SLOTS_EXCEEDED` | 409 |
| `ERR_SPONSOR_CATEGORY_EXCLUSIVITY` | 409 |
| `ERR_DUPLICATE_TIER_CODE` | 409 |
| `ERR_DUPLICATE_CHILD` | 409 |
| `ERR_DUPLICATE_VEHICLE_ENTRY` | 409 |
| `ERR_NO_STAGING_BAY_AVAILABLE` | 409 |
| `ERR_TIER_SOLD_OUT` | 409 |
| `ERR_HOSPITALITY_SEATS_EXCEEDED` | 409 |
| `ERR_CHANNEL_CAP_EXCEEDED` | 409 |
| `ERR_STOP_MARKETING_CAP_EXCEEDED` | 409 |
| `ERR_MARKETING_BUDGET_EXCEEDED` | 409 |
| `ERR_STOP_NOT_READY` | 409 |

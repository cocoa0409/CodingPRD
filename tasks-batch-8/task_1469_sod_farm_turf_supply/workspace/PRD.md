# Sod Farm Turf Supply API — Product Requirements Document

## 1. Introduction

Turfgrass is a perishable crop sold against a booking calendar. A regional sod farm must reconcile finite standing inventory — fields at different maturity stages, each with a fixed remaining area — against an order book that competes for the same harvestable square footage and the same small fleet of trucks. Deliveries are promised in fixed windows, cut sod degrades within a day of harvest, and every pallet cut from a field permanently reduces what that field can still sell. Money moves on two settlement rails, installation quality decides whether a warranty is honored, and the whole operation runs on daylight hours.

This document specifies the API through which the farm runs that operation end to end: rate cards and variety definitions; field inventory with a computed maturity cycle and a re-seeding rotation; harvest batch scheduling under agronomic quality gates; quoting with tiered pricing and freight zones; order confirmation under cutoff, truck-capacity, and freshness-aware allocation rules; delivery verification and payment reconciliation; installation crew referral and scheduling; and an establishment warranty settled through watering-compliance credits. Five roles share the surface — `FarmManager`, `SalesRep`, `HarvestSupervisor`, `FleetManager`, and `Customer` — and a server-side logical clock governs every date- and time-dependent rule so the full lifecycle is reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: identity, envelope shape, pagination, resource conventions, the clock, numeric precision, rate-card governance, concurrency control, and the order in which validations run.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. The declared roles are `FarmManager`, `SalesRep`, `HarvestSupervisor`, `FleetManager`, and `Customer`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not authorized for the targeted operation is rejected with `ERR_UNAUTHORIZED_ROLE` (403).

When `X-User-Role` is `FarmManager`, `SalesRep`, `HarvestSupervisor`, or `FleetManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`. A `Customer` may read only their own record, their own orders, and the payments, delivery checks, crew referrals, warranty claims, and watering logs attached to those orders — acting on another customer's resource is rejected with `ERR_UNAUTHORIZED_ROLE`.

Capability follows the role split. A `FarmManager` owns rate cards, variety definitions, fields and their quality data, maturity scans, archiving, re-seeding plans, crew registration and deactivation, warranty evaluation, and the logical clock. A `SalesRep` owns the order book: customer registration, quotes and their acceptance, order confirmation, cancellation, and closure, delivery checks, payments, and crew referral and scheduling. A `HarvestSupervisor` schedules, completes, and cancels harvest batches. A `FleetManager` dispatches orders, records deliveries, and manages truck blocks. A `Customer` records installation progress on their own orders, files warranty claims, and logs watering. Read access is broader than write access: the fetch and list endpoints admit the roles named in §4 even where those roles hold no write capability.

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

List endpoints accept two query parameters. `limit` caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The server stamps `created_at` at millisecond precision and guarantees uniqueness per row, so ties cannot occur and the ordering is total.

List responses include four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — rate cards, variety configs, fields, re-seed plans, harvest batches, customers, crews, quotes, orders, crew referrals, warranty claims, and truck blocks — carries four system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments with every modification — state transitions, derived-field writes, and cascading updates that touch the entity all count as modifications.

Three append-only sub-resources break this pattern: a `Payment`, a `DeliveryCheck`, and a `WateringLog` each carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on them.

One deliberate exception narrows the versioning convention: recomputing a field's maturity — whether lazily on read or through an explicit maturity scan — does not increment the field's `version`, even when the persisted `maturity_state` changes (§3.2).

### 2.5. The Logical Clock

All date- and time-dependent rules — crop age, confirm cutoffs, harvest and delivery windows, freshness limits, claim windows — read a server-maintained logical clock, never the host's wall clock. Before it has ever been set, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time.

A `FarmManager` may advance the clock through an administrative capability (mounted at `/_clock/set_current_utc`) by supplying a `to_iso8601` timestamp. The call returns an empty data object on success.

### 2.6. Numeric Precision and Rounding

Monetary amounts — prices, freight, discounts, fees, credits, payments — are rounded half-up to exactly two decimal places. Several computations pin where rounding happens: the turf component of a quote rounds each line before summing (never the reverse), freight is rounded before it enters the subtotal, and the pricing ladder rounds at each pinned step (§3.4). One rate is held more finely than money: the per-unit rate used in delivery-shortfall credit is rounded half-up to four decimal places.

Agronomic and logistics quantities — square-foot yields, pallet and truck counts, watering credits, crop age — are integers; crop age discards partial days. All numeric values are represented in API responses as JSON numbers, not strings.

### 2.7. Rate Cards and Price Snapshots

A `PriceConfig` is the farm's rate card: one bundle carrying the turf rate and full-pallet coverage for each grade, slab and roll sizes, the per-zone freight rates and the freight square-foot unit, truck capacity per zone, the delivery window shape, the confirm cutoffs, the freshness limit, the card and cash settlement fractions, the volume-tier thresholds, and the permissible harvest hours. Exactly one rate card is current at any moment: the most recently created card has `is_current` set to true, and creating a new card flips `is_current` to false on every other card.

Quotes never price against the live card. A quote snapshots the current card at creation through its `price_config_id`, and the order born of an accepted quote inherits that same snapshot. Every pricing, capacity, and window computation for the quote and its order reads the snapshot, so later rate-card changes never reprice an existing booking.

### 2.8. Optimistic Concurrency Control on Harvest Scheduling

Exactly one write is version-guarded. Scheduling a harvest batch requires the request to carry `expected_field_version`, holding the `version` of the target field as the client last observed it. If the field's current `version` has advanced past that value — because an earlier batch creation bumped it, a quality update rewrote the agronomic inputs, or the field was archived — the create is rejected with `ERR_STALE_FIELD_VERSION` (HTTP 412). The rule is purely sequential: a second create carrying an older observed version deterministically fails, regardless of when the two requests were issued. The client's basis for the create — the field's remaining area and harvestable maturity — may have been invalidated by the intervening write, and the guard prevents planning against a field state the client never saw. No other endpoint accepts a version field.

### 2.9. Validation Order of Precedence

When a request fails several rules at once, the response is decided by evaluation order, not by which rule matters most in the abstract. The server evaluates twelve tiers in the following sequence and surfaces the first failure:

1. **Authentication** — both headers are present and the role is declared; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted on the endpoint and, for `Customer`, the resource belongs to them; otherwise `ERR_UNAUTHORIZED_ROLE`.
3. **Existence** — path identifiers resolve left-to-right, and body references (`customer_id`, `variety_id`, `field_id`, `crew_id`, and each quote line's `variety_id`) resolve; otherwise `ERR_NOT_FOUND`.
4. **Request shape** — required fields present, types and ranges valid, windows aligned, uniqueness respected; otherwise `ERR_INVALID_REQUEST`.
5. **Enum membership** — `grade`, `settlement_method`, `weather_case`, and payment `method` each carry a declared member; otherwise `ERR_INVALID_ENUM`.
6. **Terminal guard** — the target entity is not in a terminal state for this action; otherwise `ERR_ALREADY_TERMINAL`.
7. **From-state guard** — the entity sits in the state the requested transition requires; otherwise `ERR_INVALID_STATE`.
8. **Field-version guard** — on harvest batch creation only, `expected_field_version` matches the field's current `version`; otherwise `ERR_STALE_FIELD_VERSION`.
9. **Temporal rules** — delivery date not in the past, quote not expired, confirm before the cutoff, harvest times inside the daylight window, claim inside its thirty-day window; the corresponding error among `ERR_DELIVERY_DATE_TOO_SOON`, `ERR_QUOTE_EXPIRED`, `ERR_CUTOFF_PASSED`, `ERR_HARVEST_WINDOW`, and `ERR_CLAIM_WINDOW_EXPIRED`.
10. **Domain constraints** — the zone split matches the line total, one claim per order, re-seed eligibility, seed sufficiency, crew active and zone- and date-compatible; the corresponding error among `ERR_ZONE_SPLIT_MISMATCH`, `ERR_DUPLICATE_CLAIM`, `ERR_RESEED_NOT_ALLOWED`, `ERR_SEED_SHORTFALL`, `ERR_INVALID_REQUEST`, `ERR_CREW_ZONE_MISMATCH`, and `ERR_CREW_DATE_CONFLICT`.
11. **Safety gates** — harvestable maturity, the agronomic quality gate, allocation freshness, delivery freshness; the corresponding error among `ERR_FIELD_NOT_HARVESTABLE`, `ERR_FIELD_QUALITY_GATE`, `ERR_BATCH_NOT_FRESH`, and `ERR_DELIVERY_STALE`.
12. **Fiscal checks last** — truck capacity, field availability, allocation sufficiency, exact payment amount, settled order; the corresponding error among `ERR_CAPACITY_EXCEEDED`, `ERR_BATCH_YIELD_EXCEEDS_AVAILABLE`, `ERR_ORDER_UNDER_ALLOCATED`, `ERR_PAYMENT_AMOUNT_MISMATCH`, and `ERR_ORDER_NOT_SETTLED`.

The ordering is observable. A confirmation attempt that would fail both the window shape and the truck pool reports the shape error, and a wrong-amount payment against an already-closed order reports the terminal error rather than the payment mismatch.

### 2.10. Nested Resource Resolution

Paths that address a sub-resource are validated left-to-right: the server resolves the first identifier, then the next, and rejects with `ERR_NOT_FOUND` (404) at the first identifier that does not exist, never reaching deeper validations. The same 404 treatment applies to body-supplied references — a quote naming an unknown `customer_id`, a batch naming an unknown `field_id`, a referral naming an unknown `crew_id`, or a line naming an unknown `variety_id`.

### 2.11. Cascading Updates and Inventory Conservation

Several writes propagate beyond their primary target, and every cascade commits atomically within the request — there is no eventual-consistency window. Four cascades are structural: a maturity scan that moves a field into `OVERAGED` cancels its pending harvest batches and reverts under-allocated confirmed orders (§3.2); completing a re-seed plan resets the field's crop cycle and cancels its uncommitted batches (§3.2); deactivating a crew replaces its live referrals and clears the referral marker on the affected orders (§3.8); and cancelling an order releases its batch links, its delivery window, and its crew referral (§3.6). Two reconciliations are fiscal: delivery checks rewrite the order's chargeable amount, and both checks and payments recompute the order's balance fields (§3.7). Every entity a cascade touches has its own `updated_at` refreshed and `version` incremented, with the single maturity-recompute exception of §2.4.

Inventory is conserved per crop cycle. At any moment, a field's `remaining_sqft` plus the `sellable_sqft` of its non-cancelled completed batches in the current cycle equals its `field_sqft`. Pending batches reserve against availability without touching `remaining_sqft`, and batch cancellations never leak square footage (§3.3).

## 3. Business Logic & Workflows

### 3.1. Farm Setup: Rate Cards, Varieties, Customers, and Crews

A `FarmManager` opens a growing season by publishing a rate card. Only the card's `name` is required at creation; every other setting — pallet coverage, turf rates, freight parameters, window and cutoff hours, freshness limit, settlement fractions, tier thresholds, harvest hours — falls back to the defaults documented where each is used (§3.3 through §3.5) when omitted from the creation payload. Publication is exclusive: the new card immediately becomes the current card under the rule of §2.7.

Varieties come next. A `FarmManager` registers each turf variety with a unique `name` — a duplicate is rejected with `ERR_INVALID_REQUEST` — four maturity window bounds (`germination_max_days`, `growing_max_days`, `ready_max_days`, and `mature_max_days`, defaulting to 14, 60, 150, and 240 days), and a `seed_lbs_per_1000_sqft` re-seeding rate, six pounds per thousand square feet by default. These bounds drive the maturity cycle of §3.2.

A `SalesRep` registers each buyer as a `Customer` with `full_name`, a unique `email` (duplicates rejected with `ERR_INVALID_REQUEST`), `phone`, a `freight_zone` of 1, 2, or 3 (any other value is rejected with `ERR_INVALID_REQUEST`), and a delivery `address`. The freight zone later decides which freight rate column the quote uses and which crews may be referred for installation.

A `FarmManager` registers installation crews with a `name`, a `service_zones` array whose members are each 1, 2, or 3, and an `active` flag that defaults to true. The crew roster can be listed with an `active` filter; deactivation and its referral cascade are covered in §3.8.

### 3.2. Fields, the Maturity Cycle, and Re-Seeding Rotation

Fields are the farm's standing inventory. A `FarmManager` creates one with a `name`, the planted `variety_id`, the total plantable area `field_sqft` (which must be positive), the planting timestamp `last_planted_at`, and the current agronomic log: `mow_count` (zero or more), `last_mowed_at`, `soil_moisture_pct` (0 to 100), and `health_score` (0 to 100). A new field starts `ACTIVE` with `remaining_sqft` initialized to `field_sqft`. A `FarmManager` may later refresh the four agronomic inputs through the field's quality-update operation; that write increments the field's `version`, one of the movements the batch-scheduling guard of §2.8 watches for.

Maturity is computed, never stored by hand. The crop's `age_days` is the number of whole days elapsed since `last_planted_at` measured against the logical clock, any partial day discarded. Comparing `age_days` with the variety's windows yields `maturity_state`: `SEEDED` while age is at most `germination_max_days`, `GROWING` while at most `growing_max_days`, `READY` while at most `ready_max_days`, `MATURE` while at most `mature_max_days`, and `OVERAGED` beyond that. Band boundaries lean young — a field whose age equals `germination_max_days` is still `SEEDED`, and likewise for the later bands. The state is recomputed lazily whenever the field is read or its maturity feeds a precondition, and a `FarmManager` can force the recomputed value to be persisted with a maturity scan; per §2.4, recomputation never increments the field's `version`.

The scan has teeth. When the persisted `maturity_state` actually changes into `OVERAGED` — and only then — the field is no longer harvestable, so every `PENDING` harvest batch of that field becomes `CANCELLED`. Any order in `CONFIRMED` whose `allocated_sqft` after those cancellations falls below its promised `turf_sqft` reverts to `PLACED`: its delivery window is cleared (releasing the booked truck capacity), all of its remaining batch links are removed, and its `allocated_sqft` recomputes to zero. A scan that leaves the persisted value unchanged fires nothing.

Retirement is guarded. A `FarmManager` may archive a field only while it holds no `PENDING` or `COMPLETE` harvest batches and no re-seed plan in `PLANNING` or `IN_PROGRESS`. Archiving moves the field's status from `ACTIVE` to `ARCHIVED` — its terminal state — and archived fields disappear from the field inventory list unless the caller explicitly passes the `status` filter for `ARCHIVED`. The inventory list also accepts `variety_id` and `maturity_state` filters, which compose.

When a crop runs its course, rotation begins. A `FarmManager` opens a re-seed plan for a field with a `planned_date`; the plan starts in `PLANNING` and immediately computes `target_seed_lbs` as the field's `field_sqft` multiplied by the variety's `seed_lbs_per_1000_sqft`, divided by one thousand, rounded half-up to two decimal places. Opening a plan is refused with `ERR_RESEED_NOT_ALLOWED` unless three conditions all hold: the field's maturity is `MATURE` or `OVERAGED`; no batch of the field is linked to an order in `PLACED`, `CONFIRMED`, `OUT_FOR_DELIVERY`, `DELIVERED`, `INSTALLING`, or `INSTALLED`; and the field has no other plan in `PLANNING` or `IN_PROGRESS`. Starting the plan moves it from `PLANNING` to `IN_PROGRESS`. Completion requires the payload's `actual_seed_lbs` to be at least `target_seed_lbs` — anything less fails with `ERR_SEED_SHORTFALL` — and stamps `completed_at`. Completion also resets the crop cycle: the field's maturity hops to `SEEDED`, `last_planted_at` becomes the current clock instant, `remaining_sqft` returns to `field_sqft`, and `mow_count` zeroes; the stubble goes with the old crop, so every `PENDING` batch of the field and every `COMPLETE` batch still unlinked to an order becomes `CANCELLED`.

### 3.3. Harvest Batches: Yield Accounting and the Quality Gate

A `HarvestSupervisor` schedules a harvest batch against a field by supplying the `field_id`, the `grade` (`PREMIUM`, `STANDARD`, or `ECONOMY`), the `pallet_count` (at least one), the QC reject counts `shortfall_slabs` and `shortfall_rolls` (zero or more), a `scheduled_date` no earlier than the clock's current date, and the concurrency token `expected_field_version` of §2.8. The batch copies the field's `variety_id` at creation, starts `PENDING`, and sits unlinked — its `order_id` stays null until an order confirmation allocates it (§3.5). Two field-side gates run before the batch is accepted. The field's `maturity_state` must be `READY` or `MATURE`; anything else is rejected with `ERR_FIELD_NOT_HARVESTABLE`. And the agronomic quality gate must pass as a whole — `mow_count` of at least three, the last mow less than three days before batch creation, `soil_moisture_pct` between 35 and 55 inclusive, and `health_score` of at least 70 — with any failure rejected as `ERR_FIELD_QUALITY_GATE`.

Yield is pallet arithmetic against the current rate card. The batch's `full_sqft` is its `pallet_count` multiplied by the grade's full-pallet coverage — `pallet_sqft_premium`, `pallet_sqft_standard`, or `pallet_sqft_economy`, defaulting to 100, 50, and 20 square feet. From that, `yield_sqft` subtracts each rejected slab at the card's `slab_sqft` (5 by default) and each rejected roll at `roll_sqft` (10 by default). A batch whose `yield_sqft` comes out at zero or below is rejected with `ERR_INVALID_REQUEST`. Every slab and roll that passes QC is sellable, so `sellable_sqft` always equals `yield_sqft`.

Scheduling reserves against the field without decrementing it. Availability nets out pending reservations: from the field's `remaining_sqft`, subtract the `sellable_sqft` of every `PENDING` batch on that same field, and a new batch whose `sellable_sqft` exceeds what remains is rejected with `ERR_BATCH_YIELD_EXCEEDS_AVAILABLE`. Creating the batch also increments the field's `version`, which is what makes a strictly later create carrying an older `expected_field_version` fail (§2.8). The conservation rule of §2.11 holds throughout: pending batches hold reservations, completed batches hold real deductions, cancelled batches hold nothing.

Completion moves real inventory. When the `HarvestSupervisor` records the actual harvest, the payload's `actual_harvest_start` must fall at or after the card's `harvest_earliest_start_hour` (06:00 by default), `actual_harvest_end` must fall at or before `harvest_latest_end_hour` (18:00 by default), and the end must be strictly later than the start; any violation is rejected with `ERR_HARVEST_WINDOW`. On success the batch moves from `PENDING` to `COMPLETE` and the field's `remaining_sqft` drops by the batch's `sellable_sqft` — only completion decrements; a `PENDING` batch never has. Cancelling a batch is permitted only while it is `PENDING` and still unlinked to any order; a cancelled batch leaves `remaining_sqft` untouched, keeping the availability accounting conserved. Batches can be listed with `field_id`, `order_id`, `variety_id`, and `status` filters.

### 3.4. Quoting: Route Mix and the Pricing Ladder

A `SalesRep` prices a prospective order by creating a quote with the `customer_id`, the requested `delivery_date` (which must not be earlier than the clock's current date, else `ERR_DELIVERY_DATE_TOO_SOON`), the `settlement_method` (`CARD` or `CASH_CHECK`), the planned route mix `z1_pallets`, `z2_pallets`, and `z3_pallets` (each zero or more), and the merchandise `lines`. The `lines` array must contain at least one entry, and each entry carries a `variety_id`, a `grade`, a `pallet_count` of at least one, and `shortfall_slabs` and `shortfall_rolls` of zero or more. The quote's `total_pallets` is the sum of the per-line pallet counts, and the route mix must reconcile with it — if the three zone counts do not sum to `total_pallets`, creation is rejected with `ERR_ZONE_SPLIT_MISMATCH`. The quote's `capacity_zone`, the zone whose trucks the booking will draw on, is whichever of the three zone counts is largest, ties breaking to the lowest zone number. At creation the quote pins `price_config_id` to the current rate card (§2.7), starts in `DRAFT`, and computes the full pricing ladder below.

Each line first yields square footage exactly as a harvest batch would (§3.3): the line's pallet count multiplied by its grade's full-pallet coverage, minus rejected slabs and rolls at the card's `slab_sqft` and `roll_sqft`. The turf component `turf_sqft` then prices each line at its grade's per-square-foot rate — `rate_premium`, `rate_standard`, or `rate_economy` (0.855, 0.70, and 0.50 by default) — with each line's contribution rounded half-up to two decimal places **before** the contributions are summed. The round-per-line-then-sum order is authoritative; summing first and rounding once produces a different number and is not compliant.

Freight follows. The zone-weighted freight factor is `z1_pallets` times `zone1_rate` plus `z2_pallets` times `zone2_rate` plus `z3_pallets` times `zone3_rate` (1.20, 1.80, and 2.60 by default). The `freight_amount` is `turf_sqft` multiplied by that factor, divided by the card's `freight_sqft_unit` (500 by default), rounded half-up to two decimal places — freight is rounded before it joins anything else. The `pre_discount_subtotal` is then simply `turf_sqft` plus `freight_amount`.

The volume tier is evaluated on **pre-discount** values, resolving the apparent circularity between tier and fee: the quote earns `T2` when `turf_sqft` is at least `volume_t2_turf_min` (8000 by default) and `pre_discount_subtotal` is at least `volume_t2_pre_min` (15000 by default); otherwise `T1` when `turf_sqft` is at least `volume_t1_turf_min` (2000 by default) and `pre_discount_subtotal` is at least `volume_t1_pre_min` (4000 by default); otherwise `T0`. For `CARD` settlement, the ladder then computes `volume_discount` as the `pre_discount_subtotal` multiplied by the tier's fraction — `volume_t1_pct` at six percent or `volume_t2_pct` at fifteen percent by default, zero for `T0` — rounded half-up to two decimals; then `card_fee` as the discounted gross multiplied by `card_fee_pct` (two percent by default), again rounded half-up to two decimals; and finally `total_price` as the discounted gross plus the card fee, rounded half-up to two decimals. For `CASH_CHECK` settlement the tier discount and card fee do not apply: `volume_discount` and `card_fee` are both 0.00, and `total_price` equals `cash_price` — the `pre_discount_subtotal` reduced by the `cash_discount_pct` fraction (three percent by default), rounded half-up to two decimals. Every quote, whatever its settlement, also exposes two informational dual variants that are never authoritative: `cash_price`, the flat cash-settlement figure just described, and `additive_total` — for `CARD`, the `pre_discount_subtotal` marked up multiplicatively by one plus the tier fraction and then by one plus the card fee fraction, rounded half-up to two decimals; for `CASH_CHECK`, identical to `cash_price`. `additive_total` diverges from the ladder's `total_price` whenever the tier fraction is positive.

One draft per customer is the rule. Creating a new quote for a customer who already has a `DRAFT` quote supersedes the older one: its status becomes `SUPERSEDED`, its `superseded_by_id` points at the new quote, and its `version` increments. Acceptance turns a quote into a booking. A `SalesRep` may accept only a `DRAFT` quote: an accept attempted against a `SUPERSEDED` or `EXPIRED` quote is rejected with `ERR_INVALID_STATE`, while an accept against an already-`ACCEPTED` quote — like any action on a terminal quote — is rejected with `ERR_ALREADY_TERMINAL`. If the quote's `delivery_date` has fallen behind the clock's current date, the accept attempt flips the quote to `EXPIRED` and is rejected with `ERR_QUOTE_EXPIRED`. A successful acceptance creates the order: status `PLACED`, `payment_status` `PENDING`, `crew_referral_status` `NONE`, `chargeable_amount` equal to `total_price`. The order records the `quote_id` (at most one order ever exists per quote), copies `customer_id`, `price_config_id`, `delivery_date`, `settlement_method`, `capacity_zone`, `turf_sqft`, `freight_amount`, `pre_discount_subtotal`, `volume_tier`, `volume_discount`, `card_fee`, `total_price`, and `total_pallets` from the quote, and takes `freight_zone` from the customer record. Quotes and orders can both be listed with `customer_id`, `status`, and `price_config_id` filters; listing the orders of a quote returns zero or one element.

### 3.5. Order Confirmation: Cutoffs, Truck Capacity, and Batch Allocation

Confirmation books the trucks and the crop at once. A `SalesRep` confirms a `PLACED` order by supplying `delivery_window_start`, which must fall on the order's `delivery_date`, be aligned to the top of an hour, and start no earlier than the card's `delivery_earliest_start_hour` (06:00 by default) and no later than `delivery_latest_start_hour` (16:00 by default); the `delivery_window_end` is derived as the start plus `delivery_window_hours` (two hours by default), so a default booking ends by 18:00.

Cutoffs protect the harvest schedule. For a same-day order — `delivery_date` equal to the clock's current date — the confirm cutoff is the order's `created_at` plus `same_day_cutoff_hours` (two hours by default). For a future-day order, the cutoff falls on the day before `delivery_date` at `future_day_cutoff_hour` (14:00 by default). Confirmation is permitted only strictly before the cutoff; an attempt at exactly the cutoff instant fails with `ERR_CUTOFF_PASSED`.

Truck capacity is a per-zone pool shared with fleet holds. Delivery windows are treated as half-open intervals — a window includes its start instant and excludes its end instant, so two windows that merely touch at a boundary do not overlap. The consumers of a zone for a requested window are the orders in `CONFIRMED` or `OUT_FOR_DELIVERY` whose `capacity_zone` matches and whose booked windows overlap it, plus the `TruckBlock` records in that zone whose windows overlap it. When the existing consumer count already equals `zone_truck_capacity` (four by default), the request is rejected with `ERR_CAPACITY_EXCEEDED` — four overlapping consumers may hold capacity at once, and the one that would become the fifth fails. A `FleetManager` draws on the same pool by registering a `TruckBlock` with a `freight_zone` of 1, 2, or 3, an hour-aligned `window_start`, a `window_end` strictly later than the start (otherwise `ERR_INVALID_REQUEST`), and an optional `reason` that defaults to an empty string; a block that would push the zone past capacity meets the same `ERR_CAPACITY_EXCEEDED`. Blocks can be listed with a `freight_zone` filter.

Allocation picks the crop, freshness-aware, line by line in quote-line order. A candidate batch must be `PENDING` or `COMPLETE`, unlinked (its `order_id` null), matching the line's variety and grade, and projected fresh: for a `COMPLETE` batch the projected harvest end is its recorded `actual_harvest_end`, while for a `PENDING` batch it is the batch's `scheduled_date` at 08:00 UTC; the projected freshness is the hours from that projected end to the order's `delivery_window_end`, and the candidate is eligible only when the projection is at least zero and at most the card's `freshness_limit_hours` (24 hours by default) — a projection of exactly the limit remains eligible, while a negative projection (the batch would finish after the window ends) is ineligible. Eligible candidates are ranked freshest first — the latest projected harvest end leads — with ties broken toward the smaller `sellable_sqft` to minimize waste, and remaining ties toward the earlier `created_at`. Batches accumulate whole until the cumulative `sellable_sqft` reaches the line's yield; the final batch may overshoot, and partial consumption of a batch is not allowed. When the eligible pool runs out before a line is met, the failure is `ERR_BATCH_NOT_FRESH` if at least one variety- and grade-matched unlinked batch was excluded solely by the freshness projection, and `ERR_ORDER_UNDER_ALLOCATED` otherwise. On success the order becomes `CONFIRMED`, the selected batches take the order's `order_id` (their own status unchanged), and the order's `allocated_sqft` — the summed `sellable_sqft` of its linked, non-cancelled batches — is recomputed.

### 3.6. Dispatch, Delivery, Installation, and Settlement

Dispatch belongs to the `FleetManager` and is deliberately strict: the order must be `CONFIRMED`, every linked batch must be `COMPLETE`, and the clock's current date must equal the `delivery_date`; violations are rejected with `ERR_INVALID_STATE`. A successful dispatch moves the order from `CONFIRMED` to `OUT_FOR_DELIVERY`.

Delivery recording tolerates partial drops. Each delivery carries an `accepted_sqft` of zero or more, and the running `delivered_sqft` plus the new `accepted_sqft` must not exceed the order's `allocated_sqft` (otherwise `ERR_INVALID_REQUEST`). Freshness is enforced against the actual harvest: the hours from the earliest `actual_harvest_end` among the order's linked batches to the delivery instant must not exceed the card's `freshness_limit_hours` — 24 hours by default — or the delivery is rejected with `ERR_DELIVERY_STALE` and the order stays `OUT_FOR_DELIVERY`. The first accepted delivery stamps `actual_delivered_at`, moves the order to `DELIVERED`, and sets `freshness_hours` (the same elapsed-hours figure, rounded half-up to two decimals); later deliveries follow a `DELIVERED` to `DELIVERED` self-loop under the same rules, accumulating `delivered_sqft` and recomputing `freshness_hours` from the latest delivery.

From there the order closes by one of two doors. On the installation path, the owning `Customer` — and only that customer, with `X-User-ID` equal to the order's `customer_id`, otherwise `ERR_UNAUTHORIZED_ROLE` — marks installation started, moving `DELIVERED` to `INSTALLING` and stamping `install_started_at`, then marks installation complete, moving `INSTALLING` to `INSTALLED` and stamping `installed_at`. If the order is already `PAID` at that moment, the two parallel dimensions join and the order drops straight to `CLOSED`. On the no-installation path, a `SalesRep` closes a `DELIVERED` order directly, but only when `payment_status` is `PAID` (otherwise `ERR_INVALID_STATE`). The symmetric join also holds: when a payment flips an `INSTALLED` order to `PAID`, the order auto-transitions to `CLOSED`.

Cancellation releases everything. A `SalesRep` may cancel an order in `PLACED`, `CONFIRMED`, or `OUT_FOR_DELIVERY` provided nothing has been paid — a `total_paid` above zero rejects the cancel with `ERR_INVALID_STATE`, since paid orders require a credit workflow that is out of scope. Cancelling moves the order to `CANCELLED`, detaches every linked batch (each batch's `order_id` returns to null), releases the booked delivery window back to the zone's truck pool, and moves any crew referral in `REFERRED` or `SCHEDULED` to `REPLACED` with the order's `crew_referral_status` reset to `NONE`.

### 3.7. Delivery Verification and Financial Reconciliation

A `SalesRep` records a delivery check against an order to verify that deliveries are keeping pace with the promise — at most two checks per order, `check_index` 1 and then 2, with a third rejected as `ERR_INVALID_STATE`. Each check belongs to its order (`order_id`) and snapshots three quantities at check time: `promised_sqft`, the order's `turf_sqft`; `delivered_cumulative`, the order's `delivered_sqft`; and `prior_payments`, the order's `total_paid`. From these, `baseline_sqft` is ninety-five percent of `promised_sqft` rounded half-up to two decimals, and the authoritative `window_size` is sixty percent of the sum of `baseline_sqft` and `prior_payments`, rounded half-up to two decimals. The check's `in_window` verdict compares delivered against that window: the order passes when `delivered_cumulative` is at least `window_size`. An informational dual variant, `strict_in_window`, instead requires each delivery chunk to stand on its own — the chunk delivered since the previous check (the full `delivered_cumulative` for the first check) must reach sixty percent of `baseline_sqft`, rounded half-up to two decimals. Consider an order promising 1500 square feet with nothing yet paid: the baseline is 1425.00 and both windows start at 855.00; deliveries of 500 and then 400 leave `delivered_cumulative` at 900, so the cumulative `in_window` passes, while `strict_in_window` fails because the latest chunk of 400 never reached 855.00 on its own.

Shortfalls are priced, not just flagged. The check's `shortfall_sqft` is the promised amount minus the delivered amount, floored at zero; the `blended_rate` is the order's `total_price` divided by its `turf_sqft`, rounded half-up to four decimal places; the `shortfall_credit` is the shortfall multiplied by that rate, rounded half-up to two decimals; and `chargeable_after` is `total_price` minus the credit. Recording the check writes `chargeable_after` into the order's `chargeable_amount`, sets the order's `delivery_flagged` to true when the check is out of window, and clears `delivery_flagged` when a later check lands in window.

The order's money fields then reconcile, as they do after every payment as well. `chargeable_amount` starts at `total_price` when the order is created and is overwritten by each delivery check; `total_paid` is the sum of the order's payment amounts; `amount_due` is `chargeable_amount` minus `total_paid`, floored at zero; `credit_balance` is the overpayment, `total_paid` minus `chargeable_amount`, floored at zero; and `payment_status` is `PAID` exactly when `amount_due` is zero, `PENDING` otherwise — so a delivery check that raises the chargeable amount above what has been paid flips a `PAID` order back to `PENDING`. The books always balance: `total_paid` plus `amount_due` minus `credit_balance` equals `chargeable_amount` at every moment.

Payments themselves are exact-amount instruments. A `SalesRep` records a payment with an `amount` equal to the order's current `amount_due` — no partials, no overpayments — and a `method` of `CHECK` or `CARD`; any other amount, or any payment while `amount_due` is zero, is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. Each payment belongs to its order (`order_id`) and stamps `received_at` from the server clock. When the payment brings `amount_due` to zero, `payment_status` becomes `PAID` — and if the order is `INSTALLED` at that moment, it auto-transitions to `CLOSED` per §3.6. An order's checks and payments can each be listed under the order.

### 3.8. Crew Referral and Scheduling

Once an order is `CONFIRMED` or further along, a `SalesRep` may refer an installation crew by `crew_id`. The referred crew must be `active` — an inactive crew is rejected with `ERR_INVALID_REQUEST` — and its `service_zones` must include the customer's `freight_zone`, otherwise `ERR_CREW_ZONE_MISMATCH`. A referral belongs to its order (`order_id`), starts in `REFERRED`, and sets the order's `crew_referral_status` to `CREW_REFERRED`. At most one non-terminal referral exists per order at any time, by construction: creating a referral supersedes the order's existing `REFERRED` or `SCHEDULED` referral, moving it to `REPLACED` while the new one takes over.

Scheduling pins the crew to a date. A `SalesRep` schedules the order's live `REFERRED` referral with a `scheduled_date` that must not be earlier than the order's `delivery_date` (otherwise `ERR_INVALID_REQUEST`), and one crew serves at most one date across the entire book: if the same crew already holds a `SCHEDULED` referral for that calendar date on another order, the request is rejected with `ERR_CREW_DATE_CONFLICT`. A successful scheduling moves the referral from `REFERRED` to `SCHEDULED`, records the `scheduled_date`, and moves the order's `crew_referral_status` to `CREW_SCHEDULED`. A crew's incoming referrals can be listed from the crew side as well.

Deactivation ripples outward two hops. When a `FarmManager` deactivates a crew, its `active` flag drops to false, every referral of that crew in `REFERRED` or `SCHEDULED` moves to `REPLACED`, and each affected order's `crew_referral_status` resets to `NONE` — the orders are left uncrewed but otherwise untouched, free to receive a fresh referral.

### 3.9. Establishment Warranty and Watering Compliance

After installation, the farm stands behind establishment. The owning `Customer` files a warranty claim on their order with a `weather_case` of `W1`, `W2`, or `W3`. The order must have completed installation (its `installed_at` recorded), must be fully settled — a claim while `payment_status` is not `PAID` is rejected with `ERR_ORDER_NOT_SETTLED` — and must be claimed within thirty days of `installed_at`, otherwise `ERR_CLAIM_WINDOW_EXPIRED`. An order still carrying a set `delivery_flagged` cannot open a claim until a later in-window delivery check clears it (§3.7), and each order supports exactly one claim — a second is rejected with `ERR_DUPLICATE_CLAIM`. The claim is anchored to its order (`order_id`), copies `customer_id` from it, snapshots `eligible_turf_sqft` from the order's `delivered_sqft`, and starts `SUBMITTED`. The weather case sets the compliance bar: `target_credits` is 500 for `W1`, 400 for `W2`, and 300 for `W3`.

Compliance is evidenced day by day. The customer logs watering under the claim — each log tied to its claim by `claim_id` — with a `log_date` and a `moisture_reading` between 0 and 100. The `log_date` must lie within the claim window, from the `installed_at` date through thirty days after it inclusive, and only one log is accepted per calendar date per claim; a date outside the window or a duplicated date is rejected with `ERR_INVALID_REQUEST`. Each log earns `credits_awarded` by soil moisture: a reading of at least 40 earns 140 credits, a reading of at least 30 but below 40 earns 120, and below 30 earns 60. The claim's `total_credits` is the running sum across its logs.

Evaluation is the verdict. A `FarmManager` evaluates a `SUBMITTED` claim — at least one watering log must exist, otherwise `ERR_INVALID_STATE`. When `total_credits` reaches `target_credits`, the claim becomes `COMPLIANT`: `resolution` is set to `CREDIT_ISSUED` and `credit_amount` to the `eligible_turf_sqft` at fifty cents per square foot, rounded half-up to two decimals. Below target, the claim becomes `INSUFFICIENT` with `resolution` `REJECTED` and `credit_amount` 0.00. Either way `evaluated_at` is stamped and the claim is terminal; claims and their watering logs can be listed per order, and claims can be listed farm-wide with `customer_id` and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — a rate card, variety, customer, crew, field, re-seed plan, harvest batch, quote, the order born of an accepted quote, a delivery check, a payment, a crew referral, a warranty claim, a watering log, or a truck block — return `201 Created`. Operations that transition or modify an existing resource return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/price-configs` | Create a rate card; it becomes the current card | FarmManager |
| GET | `/price-configs` | List price configs | FarmManager, SalesRep |
| POST | `/variety-configs` | Register a turf variety with maturity windows and seed rate | FarmManager |
| GET | `/variety-configs` | List varieties | FarmManager, SalesRep, HarvestSupervisor |
| POST | `/customers` | Register a customer | SalesRep |
| GET | `/customers/{id}` | Fetch a customer | SalesRep, FarmManager, Customer |
| POST | `/crews` | Register an installation crew | FarmManager |
| GET | `/crews` | List crews | SalesRep, FarmManager |
| GET | `/crews/{id}` | Fetch a crew | SalesRep, FarmManager |
| POST | `/crews/{id}/deactivate` | Deactivate a crew; live referrals are replaced | FarmManager |
| GET | `/crews/{id}/crew-referrals` | List referrals pointing at a crew | SalesRep, FarmManager |
| POST | `/fields` | Create a field | FarmManager |
| GET | `/fields` | Field inventory; filters compose; archived hidden unless filtered | FarmManager, SalesRep, HarvestSupervisor |
| GET | `/fields/{id}` | Fetch a field; maturity recomputed lazily | FarmManager, SalesRep, HarvestSupervisor |
| PATCH | `/fields/{id}/quality` | Update agronomic quality inputs | FarmManager |
| POST | `/fields/{id}/maturity-scan` | Persist recomputed maturity; fires the conditional OVERAGED cascade | FarmManager |
| POST | `/fields/{id}/archive` | Archive a field with no live batches or active plans | FarmManager |
| POST | `/fields/{id}/reseed-plans` | Open a re-seed rotation plan | FarmManager |
| GET | `/fields/{id}/reseed-plans` | List a field's re-seed plans | FarmManager |
| POST | `/reseed-plans/{id}/start` | Begin re-seed field work | FarmManager |
| POST | `/reseed-plans/{id}/complete` | Complete re-seeding; resets the crop cycle | FarmManager |
| POST | `/harvest-batches` | Schedule a harvest batch (OCC-guarded) | HarvestSupervisor |
| GET | `/harvest-batches` | List and filter harvest batches | HarvestSupervisor, FarmManager, SalesRep |
| GET | `/harvest-batches/{id}` | Fetch a harvest batch | HarvestSupervisor, FarmManager |
| POST | `/harvest-batches/{id}/complete` | Record actual harvest times | HarvestSupervisor |
| POST | `/harvest-batches/{id}/cancel` | Cancel a pending, unlinked batch | HarvestSupervisor |
| POST | `/quotes` | Price a turf order; supersedes the customer's existing draft | SalesRep |
| GET | `/quotes` | List quotes | SalesRep, FarmManager |
| GET | `/quotes/{id}` | Fetch a quote with computed pricing | SalesRep, FarmManager |
| POST | `/quotes/{id}/accept` | Accept a draft quote; creates the order | SalesRep |
| GET | `/quotes/{id}/orders` | List the order created from this quote (0 or 1) | SalesRep, FarmManager |
| GET | `/orders` | List orders | SalesRep, FarmManager |
| GET | `/orders/{id}` | Fetch an order | SalesRep, FarmManager, Customer |
| POST | `/orders/{id}/confirm` | Book the delivery window and allocate batches | SalesRep |
| POST | `/orders/{id}/cancel` | Cancel an unpaid order; releases batches and window | SalesRep |
| POST | `/orders/{id}/dispatch` | Mark out for delivery | FleetManager |
| POST | `/orders/{id}/mark-delivered` | Record a (possibly partial) accepted delivery | FleetManager |
| POST | `/orders/{id}/install-start` | Customer marks installation started | Customer |
| POST | `/orders/{id}/install-complete` | Customer marks installation complete | Customer |
| POST | `/orders/{id}/close` | Close a delivered, fully-paid order without installation | SalesRep |
| POST | `/orders/{id}/delivery-checks` | Record a weighted delivery-window check (max 2) | SalesRep |
| GET | `/orders/{id}/delivery-checks` | List an order's delivery checks | SalesRep, FarmManager, Customer |
| POST | `/orders/{id}/payments` | Record a payment equal to the current amount due | SalesRep |
| GET | `/orders/{id}/payments` | List an order's payments | SalesRep, FarmManager, Customer |
| POST | `/orders/{id}/crew-referrals` | Refer an installation crew to the order | SalesRep |
| GET | `/orders/{id}/crew-referrals` | List an order's crew referrals | SalesRep, FarmManager, Customer |
| POST | `/orders/{id}/crew-schedule` | Schedule the referred crew on a date | SalesRep |
| POST | `/orders/{id}/warranty-claims` | File an establishment warranty claim | Customer |
| GET | `/orders/{id}/warranty-claims` | List an order's warranty claims | SalesRep, FarmManager, Customer |
| GET | `/warranty-claims` | List warranty claims | SalesRep, FarmManager |
| GET | `/warranty-claims/{id}` | Fetch a claim | SalesRep, FarmManager, Customer |
| POST | `/warranty-claims/{id}/watering-logs` | Log a watering day | Customer |
| GET | `/warranty-claims/{id}/watering-logs` | List a claim's watering logs | SalesRep, FarmManager, Customer |
| POST | `/warranty-claims/{id}/evaluate` | Evaluate watering compliance; issue or reject the credit | FarmManager |
| POST | `/truck-blocks` | Block a zone's truck capacity over a window | FleetManager |
| GET | `/truck-blocks` | List truck blocks | FleetManager, FarmManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | FarmManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives alongside the rules they guard; this table is the identifier and status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_FIELD_VERSION` | 412 Precondition Failed |
| `ERR_DELIVERY_DATE_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_CUTOFF_PASSED` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_HARVEST_WINDOW` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_ZONE_SPLIT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CLAIM` | 409 Conflict |
| `ERR_RESEED_NOT_ALLOWED` | 409 Conflict |
| `ERR_SEED_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_FIELD_NOT_HARVESTABLE` | 409 Conflict |
| `ERR_FIELD_QUALITY_GATE` | 409 Conflict |
| `ERR_BATCH_NOT_FRESH` | 422 Unprocessable Entity |
| `ERR_DELIVERY_STALE` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BATCH_YIELD_EXCEEDS_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_ORDER_UNDER_ALLOCATED` | 409 Conflict |
| `ERR_ORDER_NOT_SETTLED` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_DATE_CONFLICT` | 409 Conflict |
| `ERR_CREW_ZONE_MISMATCH` | 422 Unprocessable Entity |

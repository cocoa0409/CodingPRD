# Aquaculture Fish Farm API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Aquaculture Fish Farm Management API, a backend platform that tracks the full production arc of a working fish farm: from hatchery broodstock and the stocking of cohorts into tanks and ponds, through daily feeding and water-quality monitoring, growth and biomass estimation, grading and splitting, veterinary treatment with mandatory withdrawal periods, harvest, processing yield, and finally finished-goods inventory and sales.

The operational reality the system models is one of competing concerns. A tank's water quality can deteriorate faster than fish can be moved; a treatment's withdrawal period can collide with a harvest schedule; a grading split must conserve fish to the last animal; and a single product lot can be promised to several customers at once. The API exists to make these tensions explicit and enforce them automatically, so that an unsafe harvest, an over-stocked pond, or an oversold lot is rejected at the moment of the request rather than discovered after the fact. Five operator roles — farm management, husbandry technicians, veterinarians, harvest operators, and sales agents — each act on their own slice of this lifecycle while the system maintains a single consistent view of biomass, health, and inventory.

Because production events are time-gated (growth accrues by the day, withdrawal periods elapse over days, occupancy intervals must not overlap), the system runs on a controllable logical clock rather than wall-clock time. This makes every time-dependent rule deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's role. A request missing either header, or carrying an `X-User-Role` value that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This applies to every endpoint, including the logical-clock endpoint, which still requires valid headers.

The system recognizes exactly five roles: `FarmManager`, `FarmTechnician`, `Veterinarian`, `HarvestOperator`, and `SalesAgent`. Once a request is authenticated, the system checks whether the acting role is permitted to perform the requested operation. If the role is recognized but not authorized for that operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The authorization matrix is summarized in the §4 endpoint table.

Roles in this system are operator categories, not entity-backed identities. For each of `FarmManager`, `FarmTechnician`, `Veterinarian`, `HarvestOperator`, and `SalesAgent`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`, and ownership of resources is not scoped to a particular operator's identifier. Authorization is therefore decided purely by role, not by which specific operator created a resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter sets how many items to skip from the front of the result set; it defaults to 0 and must be 0 or greater. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT_RANGE` (HTTP 400).

Unless otherwise stated, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Most resources in the system carry a standard set of system-managed fields. Every such resource receives an `id`, a unique server-minted UUID with no type prefix; a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first created; an `updated_at` timestamp of the same format recording the most recent modification; and a `version`, an integer that starts at 1 and increments by one on every mutation of the resource. The `version` field underpins optimistic concurrency control (§2.8).

Two entity types are append-only event records and are therefore exceptions to this rule: a `StockingEvent` and a `FeedLog` carry only `id` and `created_at`. For these two, both `updated_at` and `version` are absent, because once written they are never modified. A `WaterQualityReading` is likewise an immutable observation and carries only `id` and `created_at`, with no `updated_at` and no `version`.

Whenever an operation mutates a resource — whether by direct request or as an automatic side effect of another operation — the system refreshes that resource's `updated_at` and increments its `version` by one. This holds for computed fields too: when a cohort's `estimated_biomass_kg` or `cumulative_feed_kg` is recomputed as part of a mutating operation (a feeding, a grading commit, or a harvest mutation), when a tank's `posture` flips, or when a product lot's reserved weight changes as a cascade of a sales action, the affected resource's `version` advances and its `updated_at` is refreshed. Recomputation that happens solely to serve a read — the `estimated_biomass_kg` refreshed when a single cohort summary is requested or when a tank's `current_biomass_kg` is recomputed for a tank read or tank list — is a read-only computation and does not advance `version` or `updated_at`.

### 2.5. Nested Resource Retrieval and Existence Checks

Several endpoints address a resource nested under a parent path segment — for example, the feed logs or water-quality readings belonging to a particular cohort or tank. For any request whose path contains one or more resource identifiers, the system validates them left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not correspond to an existing resource. Only after every path identifier resolves does the system validate foreign-key references carried in the request body, again rejecting an unknown reference with `ERR_NOT_FOUND`. Existence checking precedes all business-rule evaluation.

### 2.6. Precision and Rounding

All weights, biomass figures, ratios, yields, and monetary totals that the system computes are rounded to exactly 2 decimal places using the round-half-up convention (a value exactly at the halfway point rounds away from zero). This applies to every calculated field described in §3, including estimated biomass, feed conversion ratios, processing yields and variances, per-line subtotals, and order totals. Where a calculation nests rounding steps — most notably the order-total computation — the rounding order described in the relevant workflow is mandatory and must not be collapsed into a single final rounding.

Treatment windows are measured in whole days, and the comparisons that gate harvest and re-treatment are inclusive of the computed withdrawal boundary, as detailed in §3.

### 2.7. Tank Posture and the Operational Gate

Every tank carries a computed operational gate called its `posture`, one of three values: `OPEN`, `RESTRICTED`, or `FROZEN`. A tank initializes to `OPEN`. The posture governs what husbandry actions the tank will accept: `OPEN` permits new stocking and feeding; `RESTRICTED` blocks new stocking but still permits feeding; `FROZEN` blocks all cohort operations on that tank.

A tank's effective posture is the more severe of two inputs: the severity derived from its most recent water-quality reading, and an optional manual floor called `posture_override`. The `posture_override` is set only by a `FarmManager` and may be `RESTRICTED`, `FROZEN`, or null; null means the posture is driven purely by water quality. On the set-or-clear endpoint, a request body that supplies `posture_override` as explicit null, or that omits the `posture_override` key entirely, both clear the floor to null. Any `posture_override` value other than `RESTRICTED`, `FROZEN`, or null is rejected with `ERR_POSTURE_OVERRIDE_INVALID` (HTTP 400). The effective posture is the most severe of the reading-derived posture and the override floor, treating `OPEN` as least severe, then `RESTRICTED`, then `FROZEN` as most severe.

Cohorts inherit a tank's freeze through a computed `operational_status` of either `ACTIVE` or `SUSPENDED`. A cohort residing in a `FROZEN` tank is `SUSPENDED`; otherwise it is `ACTIVE`. While a cohort is `SUSPENDED`, all feeding, grading, and harvest operations on it are blocked. The cascade and recovery mechanics of freezing are detailed in §3.

### 2.8. Optimistic Concurrency Control

Two operations require the client to prove it is acting on a current view of a parent resource, using optimistic concurrency control keyed on the parent's `version`.

Committing a grading event requires the request to carry `expected_source_cohort_version`, the `version` the client last observed on the source cohort. If that value does not equal the source cohort's current `version` at commit time, the commit is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against a second writer — another grading commit, or a harvest completion — having already changed the source cohort's `fish_count` or `lifecycle_status` since the client read it, which would otherwise let a stale split plan violate fish-count conservation.

Confirming a sales order requires the request to carry `expected_lot_version`, the single `version` that every `ProductLot` referenced by the order's lines must currently equal. If any referenced lot's current `version` differs from `expected_lot_version`, the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against another sales confirm having already reserved weight against the same lot and advanced its `version` since the client's last read. Adding a line to an order does not bump any lot's `version`; only confirm, fulfill, and cancel advance a lot's `version`. Consequently, two freshly created lots referenced by one order are both at `version` 1 at confirm time, and the client supplies that value.

No other endpoint takes a version field; operations not listed here proceed without an OCC check.

### 2.9. Water-Temperature Banding

Every species declares a viable water-temperature band through `min_water_temp_c` and `max_water_temp_c`, where `max_water_temp_c` must be strictly greater than `min_water_temp_c`. When a water-quality reading is recorded on a tank that currently holds one or more cohorts, the reading's `water_temp_c` must fall within the species band of those residing cohorts. A reading whose `water_temp_c` lies outside that band is rejected with `ERR_WATER_TEMP_OUT_OF_BAND` (HTTP 422). When no cohort resides in the tank, no banding check applies.

### 2.10. Conservation Invariants

The system maintains two hard conservation invariants. The first governs fish counts during grading: when a cohort is split, the sum of the child cohorts' fish counts always equals the source cohort's fish count immediately before the split — no fish are created or destroyed. The second governs product weight: for every product lot, the lot's total weight always equals the sum of its available, reserved, and shipped weight. Every operation that touches these quantities is designed to preserve the corresponding invariant, and the system rejects any request that would break it.

### 2.11. The Logical Clock

All time-gated rules — growth accrual, withdrawal expiry, occupancy and treatment-window overlap, and harvest gating — are evaluated against a logical clock rather than the host's wall clock. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until the clock is explicitly set it remains at that default and never falls back to real time. A `FarmManager` may advance or rewind the clock to a supplied UTC instant, provided in the `to_iso8601` field, after which every subsequent time comparison uses the new value. The clock-set endpoint returns `200 OK` with a `data` object carrying a single field, `current_utc`, holding the new clock value rendered in the standard ISO 8601 UTC format with three fractional digits. An event timestamp is subject to an `ERR_CLOCK_BACKWARDS` (HTTP 422) consistency check only when the rule that governs that event requires a past-only event; an event whose rule does not declare it past-only carries no clock-consistency check on its supplied timestamp. The one event the system treats as past-only is the `FeedLog`: its `fed_at` is rejected with `ERR_CLOCK_BACKWARDS` if it lies in the future relative to the clock or if it precedes the feeding cohort's `stocked_at`. Other event timestamps — a `WaterQualityReading`'s `measured_at` (§3.4), a `HealthTreatment`'s `started_at` (§3.7), a `Cohort`'s `stocked_at` (§3.2), a `StockingEvent`'s `stocked_at`/`expected_harvest_at` (§3.6), and a `HarvestOrder`'s `scheduled_at` (§3.8) — are not declared past-only and are therefore accepted at any instant relative to the clock and relative to their resource's creation (subject only to the field-specific ordering constraints stated in their own sections).

### 2.12. Validation Ordering

When an endpoint is subject to several checks, they are evaluated in a fixed priority order so that the rejection an operator sees is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then the existence of every referenced resource (`ERR_NOT_FOUND`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then the optimistic-concurrency version match (`ERR_STALE_VERSION`). Only after those five gates pass does the system evaluate domain-specific business rules: the tank posture and operational gate, the withdrawal gate, occupancy and treatment-window overlap, grading conservation, lot integrity and availability, biomass capacity, and broodstock allocation, in the order described across §3. Generic input validation — required fields present and well-typed, enum values within their declared sets, and numeric constraints honored — is applied on every create and update endpoint where the request body is first read; a missing required field, a bad type, an out-of-range numeric value, or an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The precise interaction of each rule with its endpoint is given in the workflow narratives below.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Species, Tanks, and Broodstock

The farm's reference layer is owned by the `FarmManager`. A **Species** record anchors the biological model for every cohort of that kind. It is created with a `common_name`, a `code`, a `target_market_weight_g`, a `base_daily_growth_g`, a `default_processing_yield_pct`, a `min_water_temp_c`, and a `max_water_temp_c`. The `code` is a short identifier, uppercase letters A–Z and digits 0–9, between 2 and 8 characters, and it must be unique across all species; an attempt to register a `code` that already exists is rejected with `ERR_DUPLICATE_CODE` (HTTP 409). The `target_market_weight_g`, `base_daily_growth_g` must each be greater than zero, the `default_processing_yield_pct` must be greater than zero and at most 1 (so 0.62 means 62% of live weight survives processing), and the temperature band must satisfy `max_water_temp_c` strictly above `min_water_temp_c`. The species list endpoint accepts a `code` filter for exact-match lookup by code.

A **Tank** is the physical water body. It is created with a `name`, a `kind` — one of `TANK`, `POND`, `RACEWAY`, or `CAGE` — a `volume_liters`, and a `max_biomass_kg`, with both `volume_liters` and `max_biomass_kg` greater than zero. A tank's `posture` initializes to `OPEN`, its `posture_override` initializes to null, and its `current_biomass_kg` initializes to 0. The `current_biomass_kg` is computed as the sum of `estimated_biomass_kg` over every cohort whose `current_tank_id` is this tank and whose `lifecycle_status` is one of `STOCKED`, `GROWING`, or `HARVESTING`; retrieving a single tank recomputes this figure from the residing cohorts, and listing tanks likewise recomputes each tank's `current_biomass_kg` before returning. The tank list endpoint accepts a `posture` filter for exact-match lookup by effective posture.

A **BroodstockBatch** represents a hatchery output and is created with a `species_id`, a `spawned_at` date, and a `fingerling_count` (which must be 0 or greater). Its `allocated_count` initializes to 0 and tracks how many fingerlings have been drawn into cohorts from this batch. Its `status` begins `AVAILABLE` and becomes `DEPLETED` once `allocated_count` equals `fingerling_count`; because this condition is evaluated at creation as well, a batch created with a `fingerling_count` of 0 begins already `DEPLETED`. The list endpoint for broodstock batches accepts a `species_id` filter for reverse lookup by species.

### 3.2. Stocking a Cohort and the Growth Model

A **Cohort** is the production unit — a lot of fish moving together through the lifecycle — and is created by a `FarmTechnician`. Creation supplies a `label`, a `species_id`, a `current_tank_id`, an optional `origin_broodstock_id`, an optional `parent_cohort_id`, a `fish_count`, a `stocked_avg_weight_g`, and a `stocked_at` timestamp. The `fish_count` must be 0 or greater and the `stocked_avg_weight_g` must be greater than zero. The `origin_broodstock_id` names the hatchery batch the fingerlings are drawn from and is null for cohorts produced by grading; the `parent_cohort_id` self-references the source cohort when this cohort was born from a grading split and is null for originally stocked cohorts. A newly created cohort begins with `lifecycle_status` `STOCKED`, `health_status` `HEALTHY`, `operational_status` `ACTIVE`, `cumulative_feed_kg` 0, `estimated_biomass_kg` 0, and `withdrawal_until` null. The cohort list endpoint exposes reverse-lookup filters for `species_id`, `current_tank_id`, `origin_broodstock_id`, `parent_cohort_id`, `lifecycle_status`, and `health_status`.

When a cohort draws from a broodstock batch, the draw must not exceed the batch's remaining fingerlings — that is, the requested `fish_count` may not exceed `fingerling_count` minus `allocated_count`. A draw that would exceed the remainder is rejected with `ERR_BROODSTOCK_INSUFFICIENT` (HTTP 422). A successful draw adds the cohort's `fish_count` to the batch's `allocated_count`, and if that brings `allocated_count` up to `fingerling_count`, the batch's `status` flips to `DEPLETED`.

The cohort's biomass is a derived figure produced by the growth model, recomputed on every feeding, whenever the cohort summary is requested, and on grading and harvest mutations. The model first determines the number of whole days elapsed since stocking: the difference between the current clock and `stocked_at`, taken as a whole number of days by discarding any fractional day (floored toward negative infinity), and then clamped to a minimum of 0 so that a clock earlier than `stocked_at` yields zero elapsed days rather than a negative count. Growth then slows in two age tiers: if the elapsed days are at most 90, each fish gains weight at the full baseline rate; if the elapsed days are more than 90 but at most 180, the rate is reduced to three-quarters of baseline; beyond 180 days the rate is reduced to one-half of baseline. The estimated average individual weight in grams is the `stocked_avg_weight_g` plus the product of the elapsed days, the species' `base_daily_growth_g`, and the applicable tier factor; this estimate is then capped so that it never exceeds the species' `target_market_weight_g`. A survival fraction is applied multiplicatively: survival is the larger of a floor of 0.80 and the quantity one minus 0.0005 times the elapsed days. Finally, the `estimated_biomass_kg` is the cohort's current `fish_count` multiplied by the estimated average weight in grams, multiplied by the survival fraction, divided by 1000 to convert grams to kilograms, and rounded to 2 decimal places.

### 3.3. Feeding, Lifecycle Advance, and Feed Conversion

Feeding is recorded by a `FarmTechnician` as a **FeedLog** against a cohort, supplying a `fed_at` timestamp, an `amount_kg` greater than zero, and a `feed_type` label. Feeding is a lifecycle transition defined only out of a cohort in `STOCKED` (which it advances to `GROWING`, below) or `GROWING` (which it leaves unchanged); a feeding attempt on a cohort whose `lifecycle_status` is any other value — `HARVESTING` or `HARVESTED` — is a transition that is not defined from the cohort's current state and is rejected with `ERR_INVALID_STATE` (HTTP 409). Consistent with the §2.12 ordering, this lifecycle-state check is evaluated before the operational and posture gate. Beyond a valid lifecycle state, feeding is permitted only when the cohort's `operational_status` is `ACTIVE` and its residing tank's `posture` is `OPEN` or `RESTRICTED`; a feeding attempt on a cohort whose tank posture is `FROZEN` or whose `operational_status` is `SUSPENDED` is rejected with `ERR_TANK_NOT_OPERATIONAL` (HTTP 409). Recording a feed recomputes the cohort's `cumulative_feed_kg` as the sum of `amount_kg` over all of that cohort's feed logs, and recomputes its `estimated_biomass_kg` via the growth model.

The first feeding also advances the cohort's lifecycle. A cohort in `STOCKED` moves to `GROWING` (`STOCKED → GROWING`) on its first feed, provided the operational and posture preconditions above hold. Lifecycle and health are parallel, independent dimensions: feeding advances `lifecycle_status` without touching `health_status`, so a `GROWING` cohort can simultaneously be `UNDER_TREATMENT`. The feed list endpoint returns the feed logs for a cohort by reverse lookup on the cohort.

The cohort summary endpoint is a read-only computation that returns, for the cohort, its `cohort_id`, the recomputed `estimated_biomass_kg`, the provisional feed conversion ratio `provisional_fcr`, the `cumulative_feed_kg`, and the `days_elapsed` since stocking. The **feed conversion ratio** measures feed delivered against biomass gained. The provisional ratio uses the growth-model estimate for the gain: the provisional biomass gain is the cohort's `estimated_biomass_kg` minus the stocked biomass, where stocked biomass is the cohort's current `fish_count` multiplied by `stocked_avg_weight_g` divided by 1000. The `provisional_fcr` is then the `cumulative_feed_kg` divided by that gain — but to avoid division by a vanishing or negative gain, the divisor used is the larger of the computed gain and a floor of 0.01 kilograms. The result is rounded to 2 decimal places. The final feed conversion ratio is computed instead at harvest completion and is described in §3.7; it uses actual landed weight rather than the estimate, and diverges from the provisional figure whenever the estimate misses the actuals.

### 3.4. Water-Quality Readings, Posture Transitions, and the Freeze Cascade

A `FarmTechnician` records a **WaterQualityReading** on a tank with a `measured_at` timestamp, a `dissolved_oxygen_mg_l` (0 or greater), an `ammonia_mg_l` (0 or greater), and a `water_temp_c`. The system classifies the reading into a `severity` of `NORMAL`, `WARNING`, or `CRITICAL`. Dissolved oxygen is a lower-bound threshold and ammonia is an upper-bound threshold. The reading is `CRITICAL` if the dissolved oxygen is strictly below 4.0 mg/L or the ammonia is strictly above 1.0 mg/L. Otherwise, if the dissolved oxygen is strictly below 6.0 mg/L or the ammonia is strictly above 0.5 mg/L, the reading is `WARNING`. Otherwise the reading is `NORMAL`. The boundary is exact: a dissolved oxygen reading of exactly 4.0 is not critical, while 3.99 is. The water-temperature band check of §2.9 applies to the recorded `water_temp_c`.

The classified severity drives the tank's posture machine, which is cyclic in both directions. A `WARNING` reading (with no override floor in force) drives an `OPEN` tank to `RESTRICTED` (`OPEN → RESTRICTED`), setting `posture` to `RESTRICTED`. A `CRITICAL` reading drives `OPEN → FROZEN` or `RESTRICTED → FROZEN`, setting `posture` to `FROZEN`. Recovery runs the other way when `posture_override` is null: a `NORMAL` reading restores `RESTRICTED → OPEN` or `FROZEN → OPEN`, and a `WARNING` reading eases `FROZEN → RESTRICTED`. A `FarmManager` may also drive these transitions directly by setting `posture_override` to `RESTRICTED` or `FROZEN`, or clear it to null to let water quality govern; the resulting effective posture is the more severe of the reading-derived posture and the override floor. Each posture change increments the tank's `version`.

Freezing a tank fires a cascade in three hops. The first hop sets `posture` to `FROZEN`. The second hop, caused by the first, suspends every cohort residing in the tank that is in production — that is, every cohort whose `current_tank_id` is this tank and whose `lifecycle_status` is `STOCKED`, `GROWING`, or `HARVESTING` — by setting its `operational_status` to `SUSPENDED` and bumping that cohort's `version`. The third hop, caused by the second, blocks harvest: any harvest order on a now-suspended cohort that was in `SCHEDULED` is moved to `BLOCKED` (`SCHEDULED → BLOCKED`), bumping that order's `version`. Recovery is deliberately asymmetric: when a tank returns to `OPEN`, every residing cohort whose `operational_status` is `SUSPENDED` is restored to `ACTIVE` (with a `version` bump), but harvest orders that were auto-`BLOCKED` are not auto-restored — they require an explicit re-schedule by a `HarvestOperator`.

### 3.5. Grading and Splitting

Grading divides a cohort into size-sorted child cohorts. A `FarmTechnician` opens a **GradingEvent** against a `source_cohort_id` with a `planned_splits` array; each entry of `planned_splits` specifies a `label`, a `fish_count`, a `target_tank_id`, and an `avg_weight_g`. A new grading event begins in `DRAFT` with an empty `child_cohort_ids`. The `planned_splits` must be non-empty and no split may carry a non-positive `fish_count`; an empty array or a split with `fish_count` of zero or less is rejected with `ERR_GRADING_SPLIT_EMPTY` (HTTP 422).

Moving a grading event from `DRAFT` to `PLANNED` (`DRAFT → PLANNED`) imposes two checks. The sum of the `fish_count` across all `planned_splits` must exactly equal the source cohort's `fish_count` — no fish created or destroyed; a mismatch is rejected with `ERR_FISH_COUNT_MISMATCH` (HTTP 422). Each split's `target_tank_id` must reference a tank whose `posture` is `OPEN`; a `target_tank_id` that does not resolve to an existing tank is rejected with `ERR_NOT_FOUND` (HTTP 404), and a resolved target whose posture is anything other than `OPEN` is rejected with `ERR_INVALID_SPLIT_TARGET` (HTTP 409). The conservation check is evaluated before the target-tank checks: at `plan`, a fish-count mismatch is rejected before any split's target tank is examined. A planned event may be revised back to `DRAFT` (`PLANNED → DRAFT`), optionally replacing `planned_splits`, which makes the planning loop cyclic; and a `DRAFT` event may be cancelled (`DRAFT → CANCELLED`), which creates no cohorts and leaves the source untouched.

Committing a planned event (`PLANNED → COMMITTED`) is the consequential step and carries `expected_source_cohort_version` for the optimistic-concurrency check of §2.8. The commit requires that the source cohort's `operational_status` is `ACTIVE`, that its `lifecycle_status` is `STOCKED` or `GROWING`, and that the `planned_splits` fish counts still sum exactly to the source cohort's current `fish_count`. If the source cohort's `operational_status` is `SUSPENDED` (its tank posture forbids the operation), the commit is rejected with `ERR_TANK_NOT_OPERATIONAL` (HTTP 409); a source cohort whose `operational_status` is `ACTIVE` but whose `lifecycle_status` is neither `STOCKED` nor `GROWING` is likewise rejected with `ERR_TANK_NOT_OPERATIONAL`; a count mismatch at commit is rejected with `ERR_FISH_COUNT_MISMATCH`. On a successful commit, the system creates one child cohort per `planned_splits` entry — each child taking its `fish_count` from the split, its `current_tank_id` from the split's `target_tank_id`, its `stocked_avg_weight_g` from the split's `avg_weight_g`, its `parent_cohort_id` set to the source, its `origin_broodstock_id` set to null, and its `stocked_at` copied from the source cohort's `stocked_at` (each child otherwise initializes like a freshly stocked cohort: `lifecycle_status` `STOCKED`, `health_status` `HEALTHY`, `operational_status` `ACTIVE`, `cumulative_feed_kg` 0, `withdrawal_until` null) — and records the new ids in the source event's `child_cohort_ids`. The source cohort is consumed: its `fish_count` is set to 0 and its `lifecycle_status` is set to `HARVESTED`. The fish-count conservation invariant holds: the sum of the children's fish counts equals the source's fish count immediately before the split. Both the source cohort's `version` and the grading event's `version` are incremented, and the event's `status` becomes `COMMITTED`.

A grading commit re-validates each split's `target_tank_id` exactly as `plan` does — an unresolved target is rejected with `ERR_NOT_FOUND` and a resolved target whose posture is not `OPEN` with `ERR_INVALID_SPLIT_TARGET` — and must also respect tank biomass capacity for each target tank: a commit that would push a target tank's `current_biomass_kg` above its `max_biomass_kg` is rejected with `ERR_TANK_BIOMASS_EXCEEDED` (HTTP 422). The biomass a split contributes to its target tank is estimated at stocking-day zero as the split's `fish_count` multiplied by its `avg_weight_g` divided by 1000 (rounded to 2 decimal places); these contributions are aggregated per target tank and added to that tank's current biomass for the comparison. The grading list endpoint filters by `source_cohort_id` for reverse lookup.

### 3.6. Stocking Events and Tank Occupancy

Beyond the cohort's own `current_tank_id`, the farm logs **StockingEvent** records that reserve a tank for a bounded occupancy interval. A `FarmTechnician` records a stocking event with a `cohort_id`, a `tank_id`, a `fish_count` greater than zero, a `stocked_at`, and an `expected_harvest_at` that must be strictly after `stocked_at`. The occupancy interval is half-open, running from `stocked_at` up to but not including `expected_harvest_at`. A new stocking event's interval must not overlap the interval of any existing stocking event on the same tank; since a `StockingEvent` is an immutable append-only record with no status of its own, every previously recorded stocking event on the tank counts as an occupancy interval for this check. Two half-open intervals `[a, b)` and `[c, d)` overlap exactly when `a < d` and `c < b`; because the interval is half-open, a new event whose `stocked_at` equals a prior interval's `expected_harvest_at` is back-to-back and allowed, while any genuine overlap is rejected with `ERR_TANK_OCCUPANCY_OVERLAP` (HTTP 409).

Recording a stocking event requires the destination tank's `posture` to be `OPEN`; a stocking attempt against a tank whose posture is `RESTRICTED` or `FROZEN` is rejected with `ERR_TANK_NOT_OPERATIONAL` (HTTP 409). The event must also respect biomass capacity: a stocking event that would push the tank's `current_biomass_kg` above its `max_biomass_kg` is rejected with `ERR_TANK_BIOMASS_EXCEEDED` (HTTP 422). The would-be figure is the tank's current biomass plus the named cohort's current `estimated_biomass_kg` when that cohort does not already reside in this tank, or the tank's current biomass unchanged when the cohort already resides in it (its biomass is then already counted). The stocking-event list endpoint filters by `cohort_id` and `tank_id`.

### 3.7. Health Treatment and the Withdrawal Gate

Veterinary care is managed by a `Veterinarian` through **HealthTreatment** records, and it advances the cohort's health dimension independently of its lifecycle. Starting a treatment supplies a `cohort_id`, a `tank_id`, a `medication`, a `started_at`, a `duration_days` greater than zero, and a `withdrawal_days` of 0 or greater. The withdrawal period is a mandatory fallow time after dosing ends, during which harvest is forbidden and the tank may not be re-treated. From these inputs the system computes the window: the `treatment_end_at` is the `started_at` advanced by `duration_days` days, and the `withdrawal_end_at` is the `treatment_end_at` advanced by a further `withdrawal_days` days. A new treatment begins with `status` `ACTIVE`.

A treatment can be started only when the cohort's `health_status` is `HEALTHY`, moving it to `UNDER_TREATMENT` (`HEALTHY → UNDER_TREATMENT`) and setting the cohort's `withdrawal_until` to the treatment's `withdrawal_end_at`. Two treatments must not collide on a tank. A new treatment on a tank is rejected if its `started_at` falls before the `withdrawal_end_at` of any prior treatment on that same tank whose `status` is `ACTIVE` or `COMPLETED`; because the withdrawal period acts as a mandatory buffer, adjacency is allowed — a new treatment whose `started_at` equals a prior treatment's `withdrawal_end_at` is permitted, while an earlier start is rejected with `ERR_TREATMENT_WINDOW_CONFLICT` (HTTP 409).

The treatment lifecycle then proceeds in two further steps, both performed by a `Veterinarian`. Completing dosing moves the treatment `ACTIVE → COMPLETED` and the cohort `UNDER_TREATMENT → WITHDRAWAL`; this is permitted only once the current clock has reached or passed the treatment's `treatment_end_at`. Clearing withdrawal moves the treatment `COMPLETED → CLEARED` and the cohort `WITHDRAWAL → HEALTHY`, resetting the cohort's `withdrawal_until` to null; this is permitted only once the current clock has reached or passed the treatment's `withdrawal_end_at`. Either action attempted before its boundary — completing before `treatment_end_at`, or clearing before `withdrawal_end_at` — is rejected with `ERR_TREATMENT_NOT_DUE` (HTTP 409). The health-treatment list endpoint filters by `cohort_id` and `tank_id`.

The withdrawal period gates harvest. Scheduling or starting a harvest is forbidden while the cohort's `health_status` is anything other than `HEALTHY`, or while the current clock is earlier than the cohort's `withdrawal_until`; such an attempt is rejected with `ERR_WITHDRAWAL_ACTIVE` (HTTP 409). Harvest is permitted once the cohort is `HEALTHY` and the clock has reached or passed `withdrawal_until`, or when `withdrawal_until` is null.

### 3.8. Harvest

Harvest is operated by a `HarvestOperator` through a **HarvestOrder**, created against a `cohort_id` with a `planned_fish_count` greater than zero and a `scheduled_at`. A new order begins in `DRAFT`. Its `harvested_fish_count` and `harvested_live_weight_kg` are null until completion. The harvest-order list endpoint filters by `cohort_id` and by `status`.

Scheduling an order (`DRAFT → SCHEDULED`, or `BLOCKED → SCHEDULED` when re-scheduling after a freeze recovery) requires that the cohort's `operational_status` is `ACTIVE`, that its `health_status` is `HEALTHY`, that the clock has reached or passed the cohort's `withdrawal_until` (or it is null), and that the `planned_fish_count` does not exceed the cohort's current `fish_count`. These gates are evaluated in that order: a cohort whose `operational_status` is `SUSPENDED` is rejected first with `ERR_TANK_NOT_OPERATIONAL` (HTTP 409); then a health or withdrawal failure is rejected with `ERR_WITHDRAWAL_ACTIVE`; and finally a `planned_fish_count` exceeding the cohort's `fish_count` is rejected with `ERR_HARVEST_COUNT_EXCEEDS` (HTTP 422). The cyclic `BLOCKED → SCHEDULED` path is how a harvest order that was auto-blocked by a freeze cascade is brought back after the tank recovers.

Starting an order (`SCHEDULED → IN_PROGRESS`) again requires the cohort to be `ACTIVE`, `HEALTHY`, and past withdrawal — applying the same ordered gate as scheduling (a `SUSPENDED` cohort rejected with `ERR_TANK_NOT_OPERATIONAL`, a non-`HEALTHY` or within-withdrawal cohort rejected with `ERR_WITHDRAWAL_ACTIVE`) — and it bubbles the cohort into active harvest by setting the cohort's `lifecycle_status` to `HARVESTING` (`GROWING → HARVESTING`); both the order's and the cohort's `version` increment. Completing an order (`IN_PROGRESS → COMPLETED`) supplies the actual `harvested_fish_count` and `harvested_live_weight_kg`; the `harvested_fish_count` must be greater than zero and at most the cohort's current `fish_count`, and the `harvested_live_weight_kg` must be greater than zero. A `harvested_fish_count` exceeding the cohort's `fish_count` is rejected with `ERR_HARVEST_COUNT_EXCEEDS`. On completion the order stores the two actuals, the cohort's `fish_count` is reduced by `harvested_fish_count`, and if that brings the cohort's `fish_count` to 0 its `lifecycle_status` becomes `HARVESTED` (`HARVESTING → HARVESTED`); both versions increment.

Completion also fixes the final feed conversion ratio. Unlike the provisional ratio of §3.3, the final ratio uses the actual landed weight: the final biomass gain is the `harvested_live_weight_kg` minus the stocked-equivalent weight, where stocked-equivalent weight is the `harvested_fish_count` multiplied by the cohort's `stocked_avg_weight_g` divided by 1000. The final ratio is the cohort's `cumulative_feed_kg` divided by that gain, using the same floor of 0.01 kilograms as the divisor's lower bound, rounded to 2 decimal places. This final ratio is a computed figure that the system derives at completion to honor the calculation contract; unlike the provisional ratio, which the cohort-summary endpoint surfaces as `provisional_fcr` (§3.3), the final ratio is not a declared field on the harvest order or the cohort and is not returned in any response — the harvest order's completion response carries only the schema fields named in this section (notably the now-populated `harvested_fish_count` and `harvested_live_weight_kg`), with no `final_fcr` attribute.

A harvest order may be cancelled (`DRAFT → CANCELLED` or `SCHEDULED → CANCELLED`) while it is in `DRAFT`, `SCHEDULED`, or `BLOCKED`; cancellation sets `status` to `CANCELLED` and increments the order's `version`.

### 3.9. Processing and Yield

Once a harvest is complete, a `HarvestOperator` opens a **ProcessingBatch** against a `harvest_order_id`. At creation the batch copies the harvest order's `harvested_live_weight_kg` into its `input_live_weight_kg`, sets `estimated_yield_kg` to 0, leaves `actual_processed_weight_kg` null, and begins in `DRAFT`. A batch may be created only from a harvest order whose own lifecycle is complete. The processing-batch list endpoint filters by `harvest_order_id` and by `status`.

Starting processing (`DRAFT → PROCESSING`) requires the linked harvest order to be `COMPLETED` and computes the forward-looking yield estimate: the `estimated_yield_kg` is the batch's `input_live_weight_kg` multiplied by the species' `default_processing_yield_pct`, rounded to 2 decimal places. Completing processing (`PROCESSING → COMPLETED`) supplies the actual dressed weight `actual_processed_weight_kg` and the `price_per_kg` for the resulting lot; the `actual_processed_weight_kg` must be greater than zero and must not exceed the batch's `input_live_weight_kg`. An actual weight exceeding the input is rejected with `ERR_PROCESSING_WEIGHT_EXCEEDS` (HTTP 422). The yield variance is the actual processed weight minus the estimated yield, rounded to 2 decimal places, and diverges from the estimate by exactly that amount; like the final feed conversion ratio (§3.8), this variance is a derived figure that the calculation contract defines but that is not a declared field on the processing batch and is not returned in any response — the completion response carries only the schema fields named in this section (notably the now-populated `actual_processed_weight_kg`), with no `yield_variance` attribute. On completion the batch stores its `actual_processed_weight_kg` and creates exactly one **ProductLot**; the completion response returns the updated processing batch (not the newly minted lot, which is retrieved separately via the product-lot endpoints). Alternatively, a batch in `PROCESSING` may be rejected (`PROCESSING → REJECTED`), in which case no product lot is created.

### 3.10. Finished Goods and the Sales Lifecycle

A **ProductLot** is finished-goods inventory created when a processing batch completes. The lot copies the batch's identifier into its `processing_batch_id`, carries the species' `species_id`, and records a `total_weight_kg` equal to the batch's `actual_processed_weight_kg` — a figure immutable after creation. The lot's `available_weight_kg` initializes to the same total, its `reserved_weight_kg` and `shipped_weight_kg` initialize to 0, and its `price_per_kg` (greater than zero) is the list price. The lot's `status` is `AVAILABLE` while its `available_weight_kg` is greater than zero and `DEPLETED` when its `available_weight_kg` reaches exactly 0, cycling back to `AVAILABLE` when weight is later released. Throughout, the lot's `available_weight_kg` equals its `total_weight_kg` minus its `reserved_weight_kg` minus its `shipped_weight_kg`, and the conservation invariant holds that the total equals available plus reserved plus shipped. The lot's `reserved_weight_kg` is the sum of line weights across all confirmed orders referencing it, and its `shipped_weight_kg` is the sum of line weights across all fulfilled orders. The product-lot list endpoint filters by `processing_batch_id`, `species_id`, and `status`.

Sales are operated by a `SalesAgent`. A **SalesOrder** is created with a `customer_name` and an optional `discount_tier` — one of `NONE`, `BRONZE`, `SILVER`, or `GOLD`, defaulting to `NONE` — and begins in `DRAFT` with an `order_total` of 0. Lines are added to a `DRAFT` order as **SalesOrderLine** records, each naming a `product_lot_id` and a `weight_kg` greater than zero; adding a line computes that line's `line_subtotal` but reserves no weight yet. Each `line_subtotal` is its `weight_kg` multiplied by the referenced lot's `price_per_kg`, rounded to 2 decimal places. Two lines on the same order may not reference the same `product_lot_id`; a duplicate lot across lines is rejected with `ERR_DUPLICATE_LINE_LOT` (HTTP 409), because availability is aggregated per lot and requires one line per lot. The sales-order list filters by status, and the sales-order-line list filters by `sales_order_id` and `product_lot_id` for reverse lookup.

Confirming an order (`DRAFT → CONFIRMED`) is the reservation step and carries `expected_lot_version` for the optimistic-concurrency check of §2.8. The order must have at least one line; a confirm on an order with zero lines is rejected with `ERR_EMPTY_ORDER` (HTTP 422). Every referenced lot must be `AVAILABLE` at confirm time; a referenced lot that is `DEPLETED` is rejected with `ERR_LOT_DEPLETED` (HTTP 409). Each line's `weight_kg` must not exceed its lot's `available_weight_kg`, and the aggregate reserved per lot across the order's lines must not exceed that lot's `available_weight_kg`; an over-reservation is rejected with `ERR_INSUFFICIENT_LOT_WEIGHT` (HTTP 422). On a successful confirm the order's `order_total` is computed (below), and for each line the referenced lot's `reserved_weight_kg` is increased by the line's `weight_kg`, the lot's `available_weight_kg` is recomputed, and if a lot's `available_weight_kg` reaches exactly 0 the lot transitions `AVAILABLE → DEPLETED`. The referenced lots' versions and the order's `version` increment.

The **order total** is computed with a pinned rounding order: first each line's subtotal is computed as its `weight_kg` times its lot's `price_per_kg` rounded to 2 decimal places; then those already-rounded line subtotals are summed; then the volume discount for the order's `discount_tier` is applied — `NONE` removes nothing, `BRONZE` removes 5%, `SILVER` removes 10%, and `GOLD` removes 15% — by multiplying the sum by one minus the tier fraction; and finally the discounted figure is rounded to 2 decimal places. Per-line rounding strictly precedes summation, and the discount is applied after summation and before the final rounding.

Fulfilling a confirmed order (`CONFIRMED → FULFILLED`) converts reservation to shipment: for each line the referenced lot's `reserved_weight_kg` is decreased by the line's `weight_kg` and its `shipped_weight_kg` is increased by the same amount, leaving `available_weight_kg` unchanged; the lots' versions and the order's `version` increment. Cancelling a confirmed order (`CONFIRMED → CANCELLED`) is a compensation cascade: the first hop sets the order's `status` to `CANCELLED`; the second hop, caused by the first, releases each line's reserved weight by decreasing the referenced lot's `reserved_weight_kg` by the line's `weight_kg` and recomputing the lot's `available_weight_kg` upward; and a further effect of that release is that any lot whose `status` was `DEPLETED` and now has `available_weight_kg` greater than zero reverts `DEPLETED → AVAILABLE`. The weight-conservation invariant is restored, and the lots' versions and the order's `version` increment.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. State transitions and other modifications to existing resources return `200 OK`. The logical-clock endpoint returns `200 OK`. List and single-resource reads return `200 OK`. Every endpoint requires the `X-User-ID` and `X-User-Role` headers described in §2.1; the authorized roles are listed below. "All roles" denotes `FarmManager`, `FarmTechnician`, `Veterinarian`, `HarvestOperator`, and `SalesAgent`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a fixed UTC instant | FarmManager |
| POST | `/species` | Create a species reference record | FarmManager |
| GET | `/species` | List species | All roles |
| GET | `/species/{id}` | Get one species | All roles |
| POST | `/tanks` | Create a tank/pond | FarmManager |
| GET | `/tanks` | List tanks | All roles |
| GET | `/tanks/{id}` | Get one tank with computed posture and biomass | All roles |
| POST | `/tanks/{id}/posture-override` | Set or clear the manual posture floor | FarmManager |
| POST | `/tanks/{id}/water-quality-readings` | Record a water-quality reading; drive posture | FarmTechnician |
| GET | `/tanks/{id}/water-quality-readings` | List a tank's water-quality readings | All roles |
| POST | `/broodstock-batches` | Create a broodstock/hatchery batch | FarmManager |
| GET | `/broodstock-batches` | List broodstock batches | All roles |
| GET | `/broodstock-batches/{id}` | Get one broodstock batch | All roles |
| POST | `/cohorts` | Create (stock) a cohort | FarmTechnician |
| GET | `/cohorts` | List cohorts | All roles |
| GET | `/cohorts/{id}` | Get one cohort | All roles |
| GET | `/cohorts/{id}/summary` | Computed biomass and provisional FCR summary | All roles |
| POST | `/cohorts/{id}/feed-logs` | Record a feeding | FarmTechnician |
| GET | `/cohorts/{id}/feed-logs` | List a cohort's feed logs | All roles |
| POST | `/stocking-events` | Record a stocking event | FarmTechnician |
| GET | `/stocking-events` | List stocking events | All roles |
| GET | `/stocking-events/{id}` | Get one stocking event | All roles |
| POST | `/grading-events` | Create a grading/split plan | FarmTechnician |
| GET | `/grading-events` | List grading events | All roles |
| GET | `/grading-events/{id}` | Get one grading event | All roles |
| POST | `/grading-events/{id}/plan` | Move a grading event to PLANNED | FarmTechnician |
| POST | `/grading-events/{id}/revise` | Move a grading event back to DRAFT | FarmTechnician |
| POST | `/grading-events/{id}/commit` | Commit a grading event; create child cohorts | FarmTechnician |
| POST | `/grading-events/{id}/cancel` | Cancel a DRAFT grading event | FarmTechnician |
| POST | `/health-treatments` | Start a health treatment | Veterinarian |
| GET | `/health-treatments` | List health treatments | All roles |
| GET | `/health-treatments/{id}` | Get one health treatment | All roles |
| POST | `/health-treatments/{id}/complete` | Complete dosing | Veterinarian |
| POST | `/health-treatments/{id}/clear` | Clear the withdrawal period | Veterinarian |
| POST | `/harvest-orders` | Create a harvest order | HarvestOperator |
| GET | `/harvest-orders` | List harvest orders | All roles |
| GET | `/harvest-orders/{id}` | Get one harvest order | All roles |
| POST | `/harvest-orders/{id}/schedule` | Schedule a harvest | HarvestOperator |
| POST | `/harvest-orders/{id}/start` | Start a harvest | HarvestOperator |
| POST | `/harvest-orders/{id}/complete` | Complete a harvest | HarvestOperator |
| POST | `/harvest-orders/{id}/cancel` | Cancel a non-started harvest | HarvestOperator |
| POST | `/processing-batches` | Create a processing batch | HarvestOperator |
| GET | `/processing-batches` | List processing batches | All roles |
| GET | `/processing-batches/{id}` | Get one processing batch | All roles |
| POST | `/processing-batches/{id}/start` | Start processing | HarvestOperator |
| POST | `/processing-batches/{id}/complete` | Complete processing; create a product lot | HarvestOperator |
| POST | `/processing-batches/{id}/reject` | Reject processing | HarvestOperator |
| GET | `/product-lots` | List product lots | All roles |
| GET | `/product-lots/{id}` | Get one product lot | All roles |
| POST | `/sales-orders` | Create a sales order | SalesAgent |
| GET | `/sales-orders` | List sales orders | FarmManager, SalesAgent |
| GET | `/sales-orders/{id}` | Get one sales order | FarmManager, SalesAgent |
| POST | `/sales-orders/{id}/lines` | Add a line to a DRAFT sales order | SalesAgent |
| GET | `/sales-order-lines` | List sales order lines | FarmManager, SalesAgent |
| GET | `/sales-order-lines/{id}` | Get one sales order line | FarmManager, SalesAgent |
| POST | `/sales-orders/{id}/confirm` | Confirm a sales order; reserve lot weight | SalesAgent |
| POST | `/sales-orders/{id}/fulfill` | Fulfill a confirmed order | SalesAgent |
| POST | `/sales-orders/{id}/cancel` | Cancel a confirmed order; release weight | SalesAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TANK_NOT_OPERATIONAL` | 409 |
| `ERR_WITHDRAWAL_ACTIVE` | 409 |
| `ERR_TANK_OCCUPANCY_OVERLAP` | 409 |
| `ERR_TREATMENT_WINDOW_CONFLICT` | 409 |
| `ERR_FISH_COUNT_MISMATCH` | 422 |
| `ERR_LOT_DEPLETED` | 409 |
| `ERR_INSUFFICIENT_LOT_WEIGHT` | 422 |
| `ERR_TANK_BIOMASS_EXCEEDED` | 422 |
| `ERR_BROODSTOCK_INSUFFICIENT` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_VALIDATION_LIMIT_RANGE` | 400 |
| `ERR_INVALID_SPLIT_TARGET` | 409 |
| `ERR_HARVEST_COUNT_EXCEEDS` | 422 |
| `ERR_PROCESSING_WEIGHT_EXCEEDS` | 422 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_TREATMENT_NOT_DUE` | 409 |
| `ERR_WATER_TEMP_OUT_OF_BAND` | 422 |
| `ERR_DUPLICATE_LINE_LOT` | 409 |
| `ERR_POSTURE_OVERRIDE_INVALID` | 400 |
| `ERR_GRADING_SPLIT_EMPTY` | 422 |
| `ERR_CLOCK_BACKWARDS` | 422 |

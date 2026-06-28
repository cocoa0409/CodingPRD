# Dairy Herd Management API — Product Requirements Document

## 1. Introduction

Commercial dairy operations run on a continuous reconciliation between two very different clocks. One clock measures the biology of the herd — heifers maturing into the milking string, cows bred and confirmed pregnant, calvings that open and close lactations, treatments that temporarily make an animal's milk unsaleable. The other clock measures money — pounds of milk and its butterfat, protein, and other-solids components flowing into a cooperative's Federal Milk Marketing Order (FMMO) pool, against which the producer first receives a provisional advance and later a final settlement check. The Dairy Herd Management (DHIA) API exists to keep these two clocks in agreement: every test-day sample, every breeding service, every health treatment, and every milk check must reconcile against the animal records and the announced co-op prices.

This document specifies the API that a herd's manager, parlor technicians, veterinarian, settlement agent, and auditors use to record and settle this activity. The system is deliberately built around a logical clock rather than wall-clock time, because milk-withhold windows, pregnancy-check deadlines, and lactation projections must be evaluated deterministically and replayed for audit. The core challenges it addresses are: maintaining lactation production figures that recompute on every new test day; cascading the consequences of a calving across the prior lactation, the new lactation, the animal's status, and the herd's active count; gating a cow's milk out of the settlement pool while a drug withhold is in force; and reconciling the provisional advance already paid against the final FMMO component value at settlement time, under optimistic concurrency so that two settlement writers cannot silently overwrite each other.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). The system recognizes exactly five roles, spelled precisely as follows: `HerdManager`, `ParlorTech`, `Veterinarian`, `CoopSettlementAgent`, and `Auditor`. When a well-authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The `HerdManager` owns herd setup, animal registration, lactation lifecycle, calving, dry-off, culling, rations, and parlors, and shares some recording duties with other roles. The `ParlorTech` logs milking shifts and may record test-day samples. The `Veterinarian` owns breeding confirmation, health treatments, and withhold clearance, and shares AI logging and treatment recording with the `HerdManager`. The `CoopSettlementAgent` owns FMMO price sheets and the entire milk-check settlement lifecycle. The `Auditor` has read-only oversight across all herd data and may call any list or detail endpoint but may not mutate anything.

For all five roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a workflow calls for it — for example, when a milking shift is logged, the acting user's `X-User-ID` is stored as the shift's `operator_user_id` — but it never compares `X-User-ID` to any entity's `id` for ownership purposes. Authorization is by role alone; there is no per-record ownership check keyed to the caller's identity.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every time-sensitive rule in this system evaluates against a single server-maintained logical clock, never against wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default — it never falls back to the real-world time of day. An administrative test-driving capability allows the clock to be advanced (or set) to a supplied absolute UTC instant, provided in the request as `to_iso8601`; the response echoes the new `current_utc`. All five roles may invoke this capability. Whenever the clock moves, every withhold check, pregnancy-check deadline, milk-eligibility derivation, and lactation projection is re-evaluated against the new instant. References below to "the current clock" always mean this logical clock.

### 2.5. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, refreshed on every mutation. The `version` field is an integer that begins at 1 and increments by one on every mutation of the resource; it is the basis for the optimistic concurrency mechanism described in §2.7.

One resource type is an exception: a `TestDayRecord` is an immutable append-only measurement. It carries only an `id` and a `created_at`; it has no `updated_at` and no `version`, because it is never modified after it is written.

### 2.6. Decimal Precision and Rounding

Several quantities in this system are computed and must be stored and returned with fixed precision, using the "round half up" method throughout.

- **Feed and money in dollars** are rounded to 2 decimal places. This applies to `daily_feed_cost_per_cow`, to every per-component dollar line in a milk check, to `advance_paid`, `gross_settlement`, and the `milk_revenue` component of income-over-feed-cost.
- **Milk pounds totals** are rounded to 1 decimal place. This applies to a lactation's `cumulative_milk_lbs` and `projected_305d_milk_lbs`.
- **Pooled component pounds and weighted SCC** in a milk check (`pooled_fat_lbs`, `pooled_protein_lbs`, `pooled_other_solids_lbs`, `weighted_scc_thousands`) are rounded to 2 decimal places, each per the per-record and final rules described in §3.
- Price-sheet rate fields (butterfat, protein, other-solids, PPD, advance, and hauling rates) preserve the input precision they were supplied with (announced FMMO prices are quoted to as many as three decimals).

A recurring discipline applies to every aggregate that sums rounded sub-values: **round each line first, then sum the rounded lines.** Never sum raw products and round once at the end. Where this pinned ordering matters — feed cost and milk-check component values — it is restated in the relevant workflow.

### 2.7. Optimistic Concurrency on Settlement

The milk-check settlement lifecycle is the only place in this system guarded by optimistic concurrency control, and it is guarded deliberately. Both finalizing and cancelling a milk check require the caller to supply `expected_milk_check_version` in the request body, carrying the `version` of the `MilkCheck` the client last observed. Before any business precondition is evaluated, the server compares this value to the milk check's current `version`. If they do not match — because another settlement writer has already cancelled or re-issued that provisional check since the client last read it, advancing its version — the request is rejected with `ERR_STALE_MILK_CHECK_VERSION` (HTTP 412). This prevents a settlement agent from acting on a view of the check that has since been superseded. No other endpoint in the system takes a version field; only milk-check finalize and milk-check cancel are OCC-guarded, and on those two the version check is non-optional.

### 2.8. Hierarchical Consistency and Cascades

Many operations in this system mutate more than one resource. A calving, a dry-off, a cull, and a milk-check finalization each ripple through several entities at once, and the system applies the full ripple atomically: when an operation changes an animal's status it also resolves that animal's lactations, and when lactations or animals change the owning herd's `active_animal_count` is recomputed. The herd's `active_animal_count` is always the count of that herd's animals whose status is `ACTIVE` or `DRY` — heifers, sold, culled, and dead animals do not count. Each entity that a cascade touches has its own `updated_at` refreshed and its own `version` incremented as part of the mutation. The specific cascades are described in §3 alongside the workflows that trigger them.

### 2.9. Nested Resource Retrieval and Reference Validation

When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`). Only after every path identifier resolves does the server validate the foreign-key identifiers carried in the request body, checking them left-to-right in the order they appear. A reference that names a real resource but one belonging to a different herd or a different animal than the operation's context is not a not-found error; it is a cross-reference conflict, rejected with `ERR_CROSS_HERD_REFERENCE` (HTTP 409), described in §3.

### 2.10. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority so that the same input always produces the same error. The order is: first the authentication headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`), then existence of all referenced resources path-first then body left-to-right (the not-found errors), then — on the two OCC-guarded milk-check mutations — the stale-version check (`ERR_STALE_MILK_CHECK_VERSION`) ahead of any business precondition, then the target resource's state precondition (the various `ERR_*_NOT_*` state errors at HTTP 409), then field shape and numeric-range validation (`ERR_INVALID_REQUEST` at HTTP 422), then within-herd uniqueness (`ERR_DUPLICATE_KEY` at HTTP 409), then same-herd referential integrity (`ERR_CROSS_HERD_REFERENCE`), then the temporal and safety rules described in §3. This ordering means, for instance, that a stale milk-check version surfaces as `ERR_STALE_MILK_CHECK_VERSION` rather than being masked by the check's PROVISIONAL-state precondition, and that a missing referenced resource is reported before any state or shape complaint about the body.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Herd: Parlors, Rations, and Announced Prices

Everything begins with a **Herd**, created by a `HerdManager` with a `name` for the dairy operation and the `federal_order_number` identifying the FMMO marketing order it ships under. A new herd opens with its `milk_quality_status` at `GOOD` and its `active_animal_count` at 0; both are computed fields the herd never sets directly. The quality status is one of `GOOD`, `WARNING`, or `PENALIZED`, and it is refreshed only when a milk check is finalized, by the rule in §3.8.

A herd is configured with the physical and financial fixtures that animal activity will reference. A **Parlor** is created under a herd, carrying the `herd_id` it belongs to, a `name`, a `stall_capacity` that must be at least 1, and an optional `turnaround_minutes` wash-and-cleanup buffer that defaults to 0 and must not be negative. This buffer governs how closely milking shifts may be scheduled, as described in §3.3.

A **Ration** is likewise created under a herd with its `herd_id`, a `name`, and an `ingredients` array. Each ingredient entry is an object naming an `ingredient_name`, a quantity `lbs_as_fed`, and a `price_per_lb`; both numeric fields must be at least 0. A ration starts with its `status` at `ACTIVE` (the only other value being `RETIRED`). On creation the system computes `daily_feed_cost_per_cow`: for each ingredient line, multiply its `lbs_as_fed` by its `price_per_lb` and round that line to the cent; then sum the rounded line costs. The rounding is per line and then summed — the system must not multiply-and-sum first and round once. No per-ingredient status filter applies; every ingredient line on the ration contributes.

A `CoopSettlementAgent` registers announced FMMO prices for a settlement month as a **CoopPriceSheet** under a herd. It carries the `herd_id`, the `settlement_month` it applies to (a `YYYY-MM` string that must be unique within the herd — a duplicate is rejected with `ERR_DUPLICATE_KEY`), and the announced rates: `fat_price_per_lb`, `protein_price_per_lb`, and `other_solids_price_per_lb` (butterfat, true-protein, and other-solids dollars per pound), `ppd_per_cwt` (the Producer Price Differential in dollars per hundredweight), `advance_rate_per_cwt` (the provisional rate paid before final settlement), and an optional `hauling_rate_per_cwt` deduction that defaults to 0. These rates feed the milk-check calculations in §3.7 and §3.8.

### 3.2. The Animal and Its Lactation Cycle

An **Animal** is registered by a `HerdManager` against a herd. The payload supplies the `herd_id`, an `ear_tag` that must be unique within the herd (a collision is rejected with `ERR_DUPLICATE_KEY`), a `birth_date`, and optionally a `dam_id` naming the animal's genetic dam. The dam, when supplied, must be another animal in the same herd; a dam belonging to a different herd is rejected with `ERR_CROSS_HERD_REFERENCE`. A newly registered animal starts with `status` of `HEIFER`, `parity` of 0 (a heifer has not yet calved), and `milk_eligible` of `true`. An animal's lifecycle runs `HEIFER → ACTIVE`, then cycles `ACTIVE ↔ DRY` once per parity, and ends in one of the terminal states `SOLD`, `CULLED`, or `DIED`. The `status` enumeration is therefore `HEIFER`, `ACTIVE`, `DRY`, `SOLD`, `CULLED`, or `DIED`.

A heifer joins the milking string at her first calving. Recording a calving (see §3.6) advances a `HEIFER` to `ACTIVE` and increments `parity` to 1; thereafter each subsequent calving moves the cow from `DRY` back to `ACTIVE` and increments `parity` again. Between calvings, when a cow is to stop being milked, the `HerdManager` dries her off: this transition is permitted only when the animal is `ACTIVE` — otherwise `ERR_ANIMAL_NOT_MILKING` — and only when she has an `OPEN` lactation — otherwise `ERR_NO_OPEN_LACTATION`. Drying off moves the animal `ACTIVE → DRY` and, as a cross-entity side effect, transitions her `OPEN` lactation to `DRY` and stamps that lactation's `dry_off_date`. That cascaded lactation transition itself requires the lactation to be `OPEN`; if the targeted lactation is not in `OPEN` status the dry-off is rejected with `ERR_LACTATION_NOT_OPEN`.

A **Lactation** is never created directly by a client; it is opened by a calving. It records its `animal_id` and `herd_id`, the `parity` of the animal at the calving that opened it, the `calving_event_id` of that calving, a `start_date` equal to the calving date (day-in-milk 0), and a `dry_off_date` that is null while the lactation is `OPEN`. Its `status` runs `OPEN → DRY → CLOSED`, with a direct `OPEN → CLOSED` path when a cow is culled or dies straight from `ACTIVE`. It also carries the two computed production figures, `cumulative_milk_lbs` and `projected_305d_milk_lbs`, both 0 until the first test day, recomputed by §3.4 on every test-day add.

### 3.3. Recording Milking Shifts in the Parlor

A `ParlorTech` (or a `HerdManager`) logs a **MilkingShift** against a parlor by supplying the `parlor_id`, a `start_at` instant (inclusive), an `end_at` instant (exclusive, and which must be strictly after `start_at` — otherwise the request is an invalid one rejected with `ERR_INVALID_REQUEST`), and the `cows_milked` head count for the shift, which must be at least 0. On creation the system copies the `herd_id` from the parlor, records the acting user's identifier as `operator_user_id`, and sets `status` to `LOGGED`. The only other status a shift can reach is `VOIDED`.

Shifts on the same parlor may not collide. Treating each shift as the half-open interval from its `start_at` up to but not including its `end_at`, a new shift is rejected with `ERR_PARLOR_SHIFT_OVERLAP` if it would overlap any existing `LOGGED` shift on the same parlor once the parlor's turnaround buffer is applied. Concretely, a new shift's `start_at` must be at or after the prior shift's `end_at` plus the parlor's `turnaround_minutes`; a new shift that starts exactly at that buffer boundary is allowed. The check considers only `LOGGED` shifts: voiding a shift (`LOGGED → VOIDED`, permitted only when the shift is `LOGGED`, otherwise `ERR_SHIFT_NOT_LOGGED`) frees its interval so that a later shift that previously would have collided becomes permissible.

### 3.4. Test Days and the Recomputation of Lactation Production

A `HerdManager` or `ParlorTech` records a DHIA test sample as a **TestDayRecord** against an `OPEN` (or otherwise non-closed) lactation. The payload names the `lactation_id`, the `test_date` the sample was drawn, the `milk_weight_lbs` produced that day (at least 0), the butterfat `fat_pct` (between 0 and 15 inclusive), the true-protein `protein_pct` (between 0 and 10 inclusive), and the somatic-cell count `scc_thousands` in thousands per millilitre (at least 0). Values outside these ranges are rejected with `ERR_INVALID_REQUEST`. The system copies `animal_id` and `herd_id` from the lactation onto the record, and may later stamp `included_in_milk_check_id` when the record is pooled into a finalized milk check (until then it is null).

The record's `day_in_milk` is computed, not supplied: it is the whole number of days from the lactation's `start_date` to the `test_date`, taking the floor. Test days must advance: the new `day_in_milk` must be strictly greater than the highest `day_in_milk` already recorded on that lactation, and the `test_date` must be on or after the lactation's `start_date`; a violation of either is rejected with `ERR_TEST_DATE_NOT_AFTER_PRIOR`. A test day cannot be added to a lactation that has already reached `CLOSED`; such an attempt is rejected with `ERR_LACTATION_CLOSED`.

Each accepted test day recomputes the owning lactation's two production figures from all of that lactation's test-day records, ordered by `day_in_milk` ascending (ties are impossible because day-in-milk strictly increases). The **cumulative milk** figure uses the Test-Interval Method. Take the records as a sequence of (day-in-milk, milk-weight) pairs. Seed the accumulator with the first test's milk weight multiplied by its day-in-milk — this credits production from calving (day 0) up to the first test. Then for each subsequent test, add the average of the current and previous tests' milk weights, multiplied by the gap in days between the current and previous tests' day-in-milk values. After processing every test, round the accumulated total to 1 decimal place. This figure, reported as `cumulative_milk_lbs`, is the actual milk to the latest recorded test — it stops at the last test and does not extrapolate beyond it. All of the lactation's test-day records contribute regardless of whether any have been pooled into a milk check.

The **projected 305-day milk** figure builds on the cumulative figure. If the lactation has no test day yet, `projected_305d_milk_lbs` is 0. Otherwise, take the latest test (the one with the highest day-in-milk). If that latest day-in-milk is at or beyond 305 days — the standard lactation length — the projection simply equals the cumulative figure with no extrapolation. If the latest day-in-milk is short of 305 days, the projection adds, on top of the cumulative figure, the latest test's milk weight multiplied by the number of days remaining to reach 305 (that is, 305 minus the latest day-in-milk); the result is rounded to 1 decimal place. The same set of test-day records that feeds the cumulative figure feeds the projection, with the last test driving the forward extrapolation.

### 3.5. Breeding, Pregnancy Confirmation, and the Voluntary Waiting Period

A `Veterinarian` or `HerdManager` logs an artificial-insemination service as a **BreedingEvent** against an animal, supplying the `animal_id`, the `service_date` of insemination, and the `sire_code` of the semen used. The system copies the `herd_id` from the animal, sets `status` to `BRED`, and computes `confirm_due_at` as the `service_date` plus a 45-day pregnancy-check window — pregnancy must be confirmed at or before that instant. A breeding event's status runs `BRED → CONFIRMED_PREGNANT → SERVED_OUT`, with a `BRED → OPEN` branch for a failed service that is retried; the full enumeration is `BRED`, `CONFIRMED_PREGNANT`, `OPEN`, and `SERVED_OUT`.

Two interval rules guard a new service. First, a new breeding event may not be logged while the animal already has a breeding event in `BRED` or `CONFIRMED_PREGNANT` status — a cow with an open or confirmed service cannot be re-bred — and such an attempt is rejected with `ERR_OPEN_SERVICE_EXISTS`. Only after the prior service has been marked open or has been served out by a calving may a new one be logged. Second, a voluntary-waiting-period rule enforces a minimum gap on the animal's breeding timeline: the new `service_date` must be separated from every prior non-voided service on the same animal — those whose status is `OPEN` or `SERVED_OUT` — by at least 30 days. Concretely, the new `service_date` must be at or after each such prior service's `service_date` plus 30 days; a `service_date` falling within the half-open 30-day interval starting at any prior service date (on or after that date but before that date plus 30 days) is rejected with `ERR_SERVICE_WITHIN_VWP`. This is a minimum-gap rule along the animal's own timeline, distinct from the parlor's interval-overlap-with-buffer geometry.

The `Veterinarian` confirms a pregnancy, moving the event `BRED → CONFIRMED_PREGNANT`. Confirmation is permitted only on an event still in `BRED` — otherwise `ERR_BREEDING_NOT_PENDING` — and only at or before `confirm_due_at`; if the current clock has passed `confirm_due_at` the confirmation is rejected with `ERR_PREG_CHECK_WINDOW_ELAPSED`. When a service fails, the `Veterinarian` marks it open, moving the event `BRED → OPEN` (again permitted only from `BRED`, otherwise `ERR_BREEDING_NOT_PENDING`); this returns the animal to a breedable state so a fresh service can be logged, completing the retry cycle. The `BRED → OPEN` branch carries no calculation; it exists purely to release the animal for re-service.

### 3.6. Calving: The Central Cascade

Recording a **CalvingEvent** is the most consequential operation in the system, because a single calving cascades across a breeding event, the animal, two lactations, and the herd count. A `HerdManager` records it with the `animal_id`, the `breeding_event_id` of the confirmed service that produced the calving, and the `calving_date`. The named breeding event must be `CONFIRMED_PREGNANT`; if it is in any other state the calving is rejected with `ERR_BREEDING_NOT_CONFIRMED`. The breeding event must also belong to the same animal — a breeding event from another animal or herd is an `ERR_CROSS_HERD_REFERENCE`. The animal itself must be in a breedable state for calving: a `HEIFER` for her first calving or a `DRY` cow for a subsequent one; an animal that is already terminal (or otherwise not in `HEIFER`/`DRY`) is rejected with `ERR_ANIMAL_NOT_BREEDABLE_STATE`.

When these checks pass, the cascade runs in order. The referenced breeding event transitions `CONFIRMED_PREGNANT → SERVED_OUT` and is linked to this calving. The system copies `herd_id` from the animal onto the calving record. The animal's `parity` is incremented by one and her `status` is set to `ACTIVE` (a first calving moves `HEIFER → ACTIVE`; a later one moves `DRY → ACTIVE`). If the animal has a prior `OPEN` or `DRY` lactation, that lactation is transitioned to `CLOSED` and its `id` is recorded on the calving as `closed_lactation_id`; if there is no prior lactation (the heifer's first calving), `closed_lactation_id` is null. A new lactation is then opened in `OPEN` status with its `start_date` equal to the `calving_date`, and its `id` is recorded on the calving as `opened_lactation_id`. Finally the herd's `active_animal_count` is recomputed to reflect that the animal is now `ACTIVE`. Each entity touched by this cascade — breeding event, animal, the closed lactation if any, and the herd — has its `updated_at` refreshed and its `version` incremented.

### 3.7. Opening a Milk Check and Paying the Advance

The settlement cycle begins when a `CoopSettlementAgent` opens a **MilkCheck** against a herd, naming the `herd_id` and the `price_sheet_id` of the announced FMMO prices to apply. That price sheet must belong to the same herd; a price sheet from another herd is rejected with `ERR_CROSS_HERD_REFERENCE`. On creation the system copies the `settlement_month` from the price sheet, sets `status` to `PROVISIONAL`, and starts `version` at 1. A milk check's status runs `PROVISIONAL → FINALIZED` or `PROVISIONAL → CANCELLED`.

At creation the check pools its provisional milk weight and pays a provisional advance. The `pooled_milk_lbs` is the sum of the `milk_weight_lbs` of every eligible, not-yet-pooled test-day record in the settlement month for this herd (eligibility is defined in §3.8). The `advance_paid` is computed using only that pooled milk weight: take the announced `advance_rate_per_cwt`, multiply it by the pooled milk in hundredweight (the pooled pounds divided by 100), and round to 2 decimal places. The advance deliberately ignores components, somatic-cell adjustments, and the PPD — those enter only at final settlement. At the provisional stage `gross_settlement`, `net_payable`, and the pooled component figures remain 0; they are computed only when the check is finalized.

### 3.8. Finalizing the Milk Check: Pooling, Components, and Reconciliation

A `CoopSettlementAgent` finalizes a provisional check, moving it `PROVISIONAL → FINALIZED`. As established in §2.7, the request must carry `expected_milk_check_version`, and a mismatch with the check's current `version` is rejected with `ERR_STALE_MILK_CHECK_VERSION` before any other check. The milk check must still be `PROVISIONAL` — a check already in `FINALIZED` or `CANCELLED` is rejected with `ERR_MILK_CHECK_NOT_PROVISIONAL` — and there must be at least one eligible, not-yet-pooled test-day record in the settlement month, otherwise the finalize is rejected with `ERR_EMPTY_MILK_POOL`.

The **pool** comprises every test-day record whose `herd_id` is this herd, whose `test_date` falls in the check's `settlement_month`, whose owning animal is `milk_eligible` at the moment of finalization, and whose `included_in_milk_check_id` is still null (not already pooled by an earlier check). Records on lactations that have since been `CLOSED` are still included as long as they meet these conditions and are not already pooled. As the records are pooled, each one's `included_in_milk_check_id` is stamped with this check's `id`.

For each pooled record the system derives three component pounds, each rounded to 2 decimal places: the fat pounds are `milk_weight_lbs` times `fat_pct` divided by 100; the protein pounds are `milk_weight_lbs` times `protein_pct` divided by 100; and the other-solids pounds are `milk_weight_lbs` times a fixed other-solids percentage of 5.7 divided by 100. The pooled totals are then the sums of these per-record figures: `pooled_milk_lbs` is the sum of the milk weights, `pooled_fat_lbs` the sum of the fat-pound lines, `pooled_protein_lbs` the sum of the protein-pound lines, and `pooled_other_solids_lbs` the sum of the other-solids lines. The pool's hundredweight, used below, is the pooled milk pounds divided by 100. The milk-weighted somatic-cell count `weighted_scc_thousands` is the sum over pooled records of each record's `scc_thousands` times its `milk_weight_lbs`, divided by the total pooled milk pounds, rounded to 2 decimal places.

The **gross settlement** is the sum of five dollar lines, each rounded to the cent before they are added together. The fat value is `pooled_fat_lbs` times the price sheet's `fat_price_per_lb`. The protein value is `pooled_protein_lbs` times the `protein_price_per_lb`. The other-solids value is `pooled_other_solids_lbs` times the `other_solids_price_per_lb`. The somatic-cell adjustment is the somatic-cell baseline of 350 (in thousands) minus the pool's `weighted_scc_thousands`, multiplied by a per-thousand-per-hundredweight rate of 0.0005, multiplied by the pool's hundredweight — a credit when the pool's weighted SCC is below the baseline and a debit when it is above. The PPD value is the price sheet's `ppd_per_cwt` times the pool's hundredweight. Each of these five lines is rounded to 2 decimal places individually, and `gross_settlement` is their sum.

The settlement then **reconciles against the advance already paid**. The hauling deduction is the price sheet's `hauling_rate_per_cwt` times the pool's hundredweight, rounded to 2 decimal places. The `net_payable` is the `gross_settlement` minus the `advance_paid` recorded at creation minus this hauling deduction — an exact subtraction of the already-rounded values, no further rounding. Cancelling a check instead (`PROVISIONAL → CANCELLED`, likewise OCC-guarded and likewise requiring a `PROVISIONAL` check) stamps no test-day records and pools nothing; the `advance_paid` is retained on the record purely as informational history.

Finalizing also refreshes the herd's **milk-quality status** from the just-finalized check's `weighted_scc_thousands`. If that weighted SCC is at or below 200 (thousands), the herd's `milk_quality_status` becomes `GOOD`; if it is above 200 but at or below 400, it becomes `WARNING`; if it is above 400, it becomes `PENALIZED`. The upper bound of each band is inclusive. Finalizing increments the milk check's `version` by one, as does cancelling.

### 3.9. Health Treatments, Withhold Windows, and Milk Eligibility

When an animal is treated, a `Veterinarian` or `HerdManager` records a **HealthTreatment** naming the `animal_id`, the `drug_name` administered, the `administered_at` instant, the `milk_withhold_hours` during which milk must be discarded, and the `meat_withdrawal_hours` before the animal may be sold for slaughter; both hour values must be at least 0. The system copies the `herd_id` from the animal and computes two deadline fields: `milk_withhold_until` is `administered_at` plus the milk-withhold hours, and `meat_withdrawal_until` is `administered_at` plus the meat-withdrawal hours. The treatment starts `ACTIVE`; it can later become `CLEARED` or `VOIDED`.

A treatment's milk withhold gates the animal's `milk_eligible` flag, which is what determines whether the animal's test-day milk may enter a settlement pool. While the animal has any `ACTIVE` health treatment whose `milk_withhold_until` is still after the current clock, the animal is not `milk_eligible`. On recording a treatment, the system sets the animal's `milk_eligible` to false if the new treatment's `milk_withhold_until` is after the current clock. Because eligibility is evaluated against the logical clock, advancing the clock past a withhold deadline is what lets the milk become saleable again — and §3.8 evaluates eligibility at the moment of finalization.

The `Veterinarian` clears a treatment once its windows have elapsed, moving it `ACTIVE → CLEARED`. Clearing is permitted only on an `ACTIVE` treatment — otherwise `ERR_TREATMENT_NOT_ACTIVE` — and only when the current clock is at or beyond both `milk_withhold_until` and `meat_withdrawal_until`; if either window is still running the clear is rejected with `ERR_WITHHOLD_NOT_ELAPSED`. Clearing recomputes the animal's `milk_eligible`, setting it true if no other `ACTIVE` treatment still holds a live milk-withhold. A treatment entered in error is instead voided by the `Veterinarian`, moving it `ACTIVE → VOIDED` (again only from `ACTIVE`, otherwise `ERR_TREATMENT_NOT_ACTIVE`); voiding recomputes the animal's `milk_eligible` immediately, since a voided treatment no longer counts toward any withhold.

### 3.10. Culling, Replacement, and the Slaughter Withdrawal Gate

The end of a cow's productive life is recorded as a **CullDecision** by a `HerdManager`, naming the `animal_id`, a `reason` from `LOW_PRODUCTION`, `REPRO_FAILURE`, `HIGH_SCC`, `INJURY`, or `AGE`, a `disposition` from `SLAUGHTER`, `DAIRY_SALE`, or `DIED`, the `decided_at` instant the cull was executed, and optionally a `replacement_animal_id` designating a heifer in the same herd to take the culled cow's place. The replacement, when supplied, must be a `HEIFER` in the same herd; a replacement from another herd is rejected with `ERR_CROSS_HERD_REFERENCE`. A cull decision is an `EXECUTED` terminal record.

A cull may only be executed on an animal currently in `ACTIVE` or `DRY` status; an animal that is already terminal or still a `HEIFER` is rejected with `ERR_ANIMAL_NOT_CULLABLE`. A safety gate guards the slaughter path specifically: when the `disposition` is `SLAUGHTER`, the cull is blocked if the animal has any `ACTIVE` health treatment whose `meat_withdrawal_until` is still after the current clock, and is rejected with `ERR_MEAT_WITHDRAWAL_ACTIVE`. A `DAIRY_SALE` or `DIED` disposition is not subject to this meat-withdrawal gate.

When the cull executes, the system copies the `herd_id` from the animal and sets the animal's status to its terminal value — `CULLED` for a `SLAUGHTER` or `DAIRY_SALE` disposition, `DIED` for a `DIED` disposition. Any `OPEN` or `DRY` lactation the animal holds is transitioned to `CLOSED`. The animal's `milk_eligible` is set to false. Finally the herd's `active_animal_count` is recomputed to reflect that the animal has left the active and dry string. Each entity the cull touches has its `updated_at` refreshed and its `version` incremented.

### 3.11. Income Over Feed Cost

For day-to-day management decisions, the system exposes a computed **income-over-feed-cost** read for an animal. The caller supplies a `ration_id` naming a ration to price feed against and a `blend_price_per_cwt` blend milk price. The calculation takes the latest test-day record on the animal's `OPEN` lactation (the one with the highest day-in-milk). The milk revenue is that test's `milk_weight_lbs` in hundredweight (its pounds divided by 100) times the supplied `blend_price_per_cwt`, rounded to 2 decimal places. The income over feed cost per cow per day is then that milk revenue minus the named ration's `daily_feed_cost_per_cow` — an exact subtraction. The named ration must be `ACTIVE`. The response returns the `milk_revenue`, the ration's `daily_feed_cost_per_cow`, and the resulting `iofc_per_cow_per_day`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions such as dry-off, confirm, clear, void, finalize, and cancel, and the logical-clock and computed-read capabilities — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/herds/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds` | Create a herd | HerdManager |
| GET | `/herds` | List herds | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/{herdId}` | Get a herd | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/parlors` | Create a parlor | HerdManager |
| GET | `/herds/parlors` | List parlors (filter by `herd_id`) | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/parlors/{parlorId}` | Get a parlor | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/rations` | Create a ration | HerdManager |
| GET | `/herds/rations` | List rations (filter by `herd_id`) | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/rations/{rationId}` | Get a ration | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/coop-price-sheets` | Register announced FMMO prices for a settlement month | CoopSettlementAgent |
| GET | `/herds/coop-price-sheets` | List price sheets (filter by `herd_id`) | HerdManager, CoopSettlementAgent, Auditor |
| GET | `/herds/coop-price-sheets/{priceSheetId}` | Get a price sheet | HerdManager, CoopSettlementAgent, Auditor |
| POST | `/herds/animals` | Register an animal | HerdManager |
| GET | `/herds/animals` | List animals (filter by `herd_id`, `dam_id`, `status`) | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/animals/{animalId}` | Get an animal | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/animals/{animalId}/dry-off` | Dry off an ACTIVE cow | HerdManager |
| GET | `/herds/animals/{animalId}/iofc` | Computed income-over-feed-cost read | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/lactations` | List lactations (filter by `animal_id`, `herd_id`, `calving_event_id`) | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/lactations/{lactationId}` | Get a lactation | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/test-day-records` | Record a DHIA test day on a lactation | HerdManager, ParlorTech |
| GET | `/herds/test-day-records` | List test-day records (filter by `lactation_id`, `animal_id`, `herd_id`, `included_in_milk_check_id`) | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/test-day-records/{testDayRecordId}` | Get a test-day record | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/milking-shifts` | Log a milking shift on a parlor | ParlorTech, HerdManager |
| GET | `/herds/milking-shifts` | List shifts (filter by `parlor_id`, `herd_id`) | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/milking-shifts/{shiftId}` | Get a milking shift | HerdManager, ParlorTech, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/milking-shifts/{shiftId}/void` | Void a logged shift | ParlorTech, HerdManager |
| POST | `/herds/breeding-events` | Log an AI service | Veterinarian, HerdManager |
| GET | `/herds/breeding-events` | List breeding events (filter by `animal_id`, `herd_id`) | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/breeding-events/{breedingId}` | Get a breeding event | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/breeding-events/{breedingId}/confirm` | Confirm pregnancy within the check window | Veterinarian |
| POST | `/herds/breeding-events/{breedingId}/mark-open` | Mark a failed service open for retry | Veterinarian |
| POST | `/herds/calving-events` | Record a calving | HerdManager |
| GET | `/herds/calving-events` | List calving events (filter by `animal_id`, `herd_id`, `breeding_event_id`, `opened_lactation_id`, `closed_lactation_id`) | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/calving-events/{calvingEventId}` | Get a calving event | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/health-treatments` | Record a treatment with milk/meat withhold | Veterinarian, HerdManager |
| GET | `/herds/health-treatments` | List treatments (filter by `animal_id`, `herd_id`) | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| GET | `/herds/health-treatments/{treatmentId}` | Get a health treatment | HerdManager, Veterinarian, CoopSettlementAgent, Auditor |
| POST | `/herds/health-treatments/{treatmentId}/clear` | Clear a treatment once both windows elapsed | Veterinarian |
| POST | `/herds/health-treatments/{treatmentId}/void` | Void a treatment entered in error | Veterinarian |
| POST | `/herds/milk-checks` | Open a provisional milk check and pay an advance | CoopSettlementAgent |
| GET | `/herds/milk-checks` | List milk checks (filter by `herd_id`, `price_sheet_id`) | HerdManager, CoopSettlementAgent, Auditor |
| GET | `/herds/milk-checks/{milkCheckId}` | Get a milk check | HerdManager, CoopSettlementAgent, Auditor |
| POST | `/herds/milk-checks/{milkCheckId}/finalize` | Finalize a provisional check (OCC-guarded) | CoopSettlementAgent |
| POST | `/herds/milk-checks/{milkCheckId}/cancel` | Cancel a provisional check (OCC-guarded) | CoopSettlementAgent |
| POST | `/herds/cull-decisions` | Execute a cull/replacement decision | HerdManager |
| GET | `/herds/cull-decisions` | List cull decisions (filter by `animal_id`, `herd_id`, `replacement_animal_id`) | HerdManager, CoopSettlementAgent, Auditor |
| GET | `/herds/cull-decisions/{cullDecisionId}` | Get a cull decision | HerdManager, CoopSettlementAgent, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_HERD_NOT_FOUND` | 404 |
| `ERR_PARLOR_NOT_FOUND` | 404 |
| `ERR_RATION_NOT_FOUND` | 404 |
| `ERR_PRICE_SHEET_NOT_FOUND` | 404 |
| `ERR_ANIMAL_NOT_FOUND` | 404 |
| `ERR_LACTATION_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_BREEDING_NOT_FOUND` | 404 |
| `ERR_TREATMENT_NOT_FOUND` | 404 |
| `ERR_MILK_CHECK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_CROSS_HERD_REFERENCE` | 409 |
| `ERR_ANIMAL_NOT_BREEDABLE_STATE` | 409 |
| `ERR_ANIMAL_NOT_MILKING` | 409 |
| `ERR_NO_OPEN_LACTATION` | 409 |
| `ERR_ANIMAL_NOT_CULLABLE` | 409 |
| `ERR_LACTATION_NOT_OPEN` | 409 |
| `ERR_LACTATION_CLOSED` | 409 |
| `ERR_BREEDING_NOT_PENDING` | 409 |
| `ERR_BREEDING_NOT_CONFIRMED` | 409 |
| `ERR_PREG_CHECK_WINDOW_ELAPSED` | 409 |
| `ERR_OPEN_SERVICE_EXISTS` | 409 |
| `ERR_SERVICE_WITHIN_VWP` | 409 |
| `ERR_TREATMENT_NOT_ACTIVE` | 409 |
| `ERR_WITHHOLD_NOT_ELAPSED` | 409 |
| `ERR_SHIFT_NOT_LOGGED` | 409 |
| `ERR_MILK_CHECK_NOT_PROVISIONAL` | 409 |
| `ERR_TEST_DATE_NOT_AFTER_PRIOR` | 409 |
| `ERR_PARLOR_SHIFT_OVERLAP` | 409 |
| `ERR_MEAT_WITHDRAWAL_ACTIVE` | 403 |
| `ERR_EMPTY_MILK_POOL` | 409 |
| `ERR_STALE_MILK_CHECK_VERSION` | 412 |

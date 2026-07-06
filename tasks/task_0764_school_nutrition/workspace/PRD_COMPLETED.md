# School Nutrition & Cafeteria Operations API — Product Requirements Document

## 1. Introduction

School districts operate their nutrition programs at the intersection of two demanding regimes: the federal meal-pattern and reimbursement rules that govern what may be served and what may be claimed, and the day-to-day cafeteria mechanics of forecasting production, drawing down commodity and purchased inventory, ringing up meals and a-la-carte sales at the point of service, and keeping each student's prepay account solvent. This API unifies those concerns behind a single namespace so that a menu planned by one office, prepared by a cafeteria team, served at a register, and ultimately reimbursed by the state agency all reference one consistent set of records.

The platform is built around two accounting spines. The first is a **prepay ledger**: every deposit, meal charge, and void refund settles immediately against a student's balance, and the account's posture (healthy, low, or negative) is a live reflection of that arithmetic. The second is a **reimbursement claim** that reconciles a month of reimbursable meals against federal per-meal rates. Both spines distinguish a *forward-looking estimate* from a *chronological actual*: production is forecast before service and reconciled against real meal counts afterward, and a claim's reimbursement is estimated at submission and finalized at payment. Because late meals and voids can move the numbers between those two moments, the system leans heavily on compliance gates, segregation-of-duties controls, and optimistic concurrency to keep every downstream figure defensible.

This document specifies the complete contract: the entities and their fields, the state machines that move menus, production, meals, and claims through their lifecycles, the calculations that produce every derived amount, the validation rules and their precedence, and the full endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `MenuPlanner`, `NutritionDirector`, `CafeteriaManager`, and `POSClerk`. `PlatformAdmin` is the district/system operator who configures sites, food items, reimbursement rates, and students, marks claims paid, and controls the service clock. `MenuPlanner` authors menu cycles and submits them for review. `NutritionDirector` is the authorizing official who approves or rejects menus and who opens, submits, and recalls reimbursement claims. `CafeteriaManager` receives inventory and runs production. `POSClerk` is the register cashier who records and voids meals and takes prepay deposits.

For all five roles, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity: the server never compares it to any resource's `id`. It is, however, recorded where the workflow requires accountability — the server writes it into `submitted_by_user_id` when a `MenuPlanner` submits a menu cycle, into `created_by_user_id` when a `NutritionDirector` opens a claim, and into `submitted_by_user_id` when a claim is submitted — so that later segregation-of-duties checks can compare the acting `X-User-ID` against the recorded value. These recorded identifiers are used only for that comparison, never as foreign keys.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A `limit` outside the inclusive range from 1 to 100 is a body-shape violation and is rejected with `ERR_VALIDATION` (HTTP 400). The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is a body-shape violation rejected with `ERR_VALIDATION` (400).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties on `created_at` broken by ascending creation order (insertion sequence). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits: `created_at` is fixed at creation, and `updated_at` is refreshed on every mutation. The `version` is an integer that starts at 1 (or the initial value assigned at creation) and increments by one on every mutation of the resource; it is the value used for optimistic concurrency control where that applies.

`SchoolSite`, `FoodItem`, `ReimbursementRate`, `MenuCycle`, `InventoryLot`, `ProductionRecord`, `Student`, `MealTransaction`, and `ReimbursementClaim` all carry the full set — `id`, `created_at`, `updated_at`, and `version`. There are no reduced-field entities in this system; every resource exposes `updated_at` and `version`.

### 2.5. Reference Resolution and Validation Ordering

Validation across the API is strictly prioritized, and the **first** failing check in priority order is the one reported. The global precedence is: (1) authentication — a present and recognized `X-User-Role`, else `ERR_UNAUTHENTICATED` (401); (2) authorization — the role is permitted for the operation, else `ERR_FORBIDDEN` (403); (3) existence — every path `id` and every foreign-key reference carried in the request body resolves to a real resource, validated left-to-right in the order they appear, else `ERR_NOT_FOUND` (404); (4) body shape — required fields present, enum values legal, numeric types and ranges valid, and any pagination `limit` within 1 to 100, else `ERR_VALIDATION` (400). Only after these four pass does the system evaluate resource-specific rules.

Among the resource-specific rules the ordering continues by ascending priority: optimistic-concurrency staleness on a claim submission (`ERR_STALE_CLAIM_VERSION`, 412) is checked before segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 409), which is checked before the generic state-validity check (`ERR_INVALID_STATE`, 409). The remaining business checks follow, and where several apply to one endpoint the lower-priority-numbered rule is evaluated first. The per-endpoint precedence is spelled out in the workflow narratives of §3, but as a governing example, a point-of-service meal evaluates its guards in this order: production readiness (`ERR_PRODUCTION_NOT_READY`), then Smart-Snacks compliance (`ERR_NOT_SMART_SNACK_COMPLIANT`), then student-site match (`ERR_STUDENT_SITE_MISMATCH`), then component validity (`ERR_INVALID_COMPONENT`), then the duplicate-reimbursable-meal check (`ERR_DUPLICATE_REIMBURSABLE_MEAL`), and finally the balance check (`ERR_INSUFFICIENT_BALANCE`).

### 2.6. Monetary Values, Quantities, and Rounding Precision

All money in the system is expressed in whole integer **cents** — prices, copays, rates, add-ons, tax, balances, charges, and reimbursement amounts. Where a monetary computation produces a fractional cent (notably a-la-carte sales tax), the result is rounded half-up to a whole cent, and the pinned evaluation order for that rounding is specified with the a-la-carte calculation in §3.

Meal-pattern component sums are computed to two decimal places using round-half-up before their threshold comparisons. Inventory unit quantities are carried to three decimal places, round-half-up. Forecast and production portion counts are whole integers, produced by round-half-up. Every threshold comparison in the system that the calculations describe as "at least" or "at or below" is inclusive at the boundary, exactly as stated in the relevant §3 narrative.

### 2.7. Segregation of Duties and Optimistic Concurrency Control

Two independence controls protect the integrity of approvals and claims.

**Segregation of duties.** The user who advanced a record cannot also be the one who authorizes it. When a menu cycle is approved or rejected, the acting `X-User-ID` must differ from the `submitted_by_user_id` recorded when the cycle was submitted; if they are equal, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Likewise, when a reimbursement claim is submitted, the acting `X-User-ID` must differ from the `created_by_user_id` recorded when the claim was opened, else the same `ERR_SEGREGATION_OF_DUTIES` (409) applies.

**Optimistic concurrency on claim submission.** Submitting a reimbursement claim requires a non-optional `expected_claim_version` input field carrying the client's last observed `version` of the target `ReimbursementClaim`. If `expected_claim_version` does not equal the claim's current `version`, the submission is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). This guards against a stale view of the counts: a late meal transaction or a void for the same site and month legitimately recomputes the claim's free, reduced, and paid counts and increments the claim's `version` as a side effect, so a submit still carrying the pre-recompute `expected_claim_version` is working from counts that have since moved and must be refused. No other endpoint takes a version field; only claim submission carries this concurrency guard.

### 2.8. Cascading Consistency and Reconciliation

Many operations mutate more than one resource, and every such cascade is applied atomically and immediately. When a point-of-service meal is charged, the student's `balance_cents` moves, the student's `account_status` is recomputed, and if that recomputation flips the student into or out of the `NEGATIVE` posture the owning site's `negative_balance_count` is adjusted in the same operation; the linked production record's `served_qty` and `leftover_qty` are recomputed; and any `DRAFT` claim for that site and month has its counts recomputed and its `version` incremented. Preparing a production record depletes inventory lots and can flip lots to `DEPLETED`; cancelling a prepared record restores exactly what was drawn and can flip lots back to `AVAILABLE`. Every entity touched by a cascade has its own `updated_at` refreshed and its own `version` incremented as part of that mutation — a derived-field change such as a recomputed `served_qty`, `balance_cents`, or claim count is a real mutation of the affected resource, not a silent side write.

### 2.9. Nested Reference Retrieval

Where an endpoint path carries an identifier, and wherever a request body carries foreign-key references, the system resolves them left-to-right and rejects the request at the first identifier that does not resolve, returning `ERR_NOT_FOUND` (404) for that first missing reference before evaluating any later reference or any business rule. A meal transaction, for example, that names a `site_id`, a `student_id`, and a `production_record_id` is checked in that order.

### 2.10. The Logical Service Clock

The server keeps a logical clock in UTC rather than reading wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. A `PlatformAdmin` may advance it by supplying a `to_iso8601` instant. The clock governs every date-sensitive rule: whether a menu's `effective_date` is in the past at submission, which reimbursement rate is applicable for a claim month, and the derivation of a claim's month. Tests and operators must set the clock deliberately before exercising temporal behavior.

## 3. Business Logic & Workflows

### 3.1. Configuring the District: Sites, Food Items, and Reimbursement Rates

Before any cafeteria activity, a `PlatformAdmin` establishes the district's static configuration.

A **school site** is created with a `name` and a `site_code`, the latter unique across all sites; a `site_code` that duplicates an existing site is rejected with `ERR_VALIDATION` (400). A site declares whether it participates in the National School Lunch Program via `nslp_participating` and the School Breakfast Program via `sbp_participating` (both defaulting to true), whether it qualifies for the severe-need breakfast rate via `severe_need_breakfast` (default false), and whether it holds the performance-based reimbursement certification via `performance_based_certified` (default false). The `negative_balance_allowed` flag (default false) decides whether a paid or reduced charge may push a student's prepay balance below zero: when false, an over-charge is refused. A site sets `sales_tax_bps` (basis points applied to a-la-carte lines, default 0, e.g. 725 means 7.25%) and four price/copay fields in cents: `paid_lunch_price_cents` (default 300), `paid_breakfast_price_cents` (default 200), `reduced_lunch_copay_cents` (default 40), and `reduced_breakfast_copay_cents` (default 30). The site also exposes a computed `negative_balance_count`, initialized to 0 at creation, holding the number of that site's students currently in the `NEGATIVE` posture; it is recomputed on every prepay balance change.

A **food item** captures both a nutrition profile and an inventory unit. It has a `name` and a `category`, which is exactly one of `ENTREE`, `GRAIN`, `FRUIT`, `VEGETABLE`, `MILK`, `SNACK`, or `BEVERAGE`. The `is_commodity` flag (default false) marks USDA Foods items, which are always depleted before purchased stock. The nutrition fields — `calories` (default 0), `sat_fat_g` (default 0), `total_fat_g` (default 0), `sodium_mg` (default 0), `total_sugar_g` (default 0), and `weight_g` (default 1, the serving weight in grams used as the denominator for the Smart-Snacks sugar-by-weight test) — feed the a-la-carte Smart-Snacks screen. The meal-pattern contribution fields — `meat_alt_oz_eq`, `grain_oz_eq`, `fruit_cup`, and `veg_cup` (each default 0) — give the ounce-equivalents and cups the item contributes per serving, and `is_whole_grain_rich` (default false) marks a grain item as whole-grain-rich. The `unit` field is one of `EACH`, `OZ`, or `CASE` (default `EACH`) and describes the inventory unit.

A **reimbursement rate** row is time-versioned. It names a `program` — `NSLP` or `SBP` — a `category` — `FREE`, `REDUCED`, or `PAID` — a `severe_need` flag (default false, which selects the severe-need SBP variant and is ignored for NSLP), the base `rate_cents` per reimbursable meal, an optional `performance_addon_cents` (default 0) applied only when the serving site is performance-based certified, and an `effective_date` (a `YYYY-MM-DD` date) from which the rate applies. When a reimbursement amount must be computed, the applicable rate for a given program, category, and severe-need flag is the row with the greatest `effective_date` that is on or before the first day of the claim month; ties on `effective_date` are broken by the greatest `created_at`, and never by `id`.

### 3.2. Menu Planning and USDA Meal-Pattern Compliance

A `MenuPlanner` authors a **menu cycle** for a site. The cycle names its `site_id`, a `meal_type` of `BREAKFAST` or `LUNCH`, a `grade_group` of `GRADES_K_5`, `GRADES_6_8`, or `GRADES_9_12`, and a half-open service period defined by an inclusive `effective_date` and an exclusive `end_date`, so the period covers dates from `effective_date` up to but not including `end_date`. Its `components` array lists the planned meal components, each entry naming a `food_item_id` (resolved to a food item at write time), a `component` drawn from `MEAT_MEAT_ALT`, `GRAINS`, `FRUIT`, `VEGETABLE`, or `MILK`, a `planned_servings` count, and a `serving_amount` giving the ounce-equivalents or cups per portion. A newly created cycle starts in `DRAFT` status, and its `compliance_status` is computed immediately.

**Meal-pattern compliance** is evaluated over the cycle's own components, resolving each linked food item's nutrient contributions and weighting them by that component's `planned_servings`. The total meat/meat-alternate is the sum across components of `planned_servings` multiplied by the food item's `meat_alt_oz_eq`. The total grain is the sum of `planned_servings` multiplied by `grain_oz_eq`. The total fruit-and-vegetable is the sum of `planned_servings` multiplied by the food item's `fruit_cup` plus `veg_cup`. Milk is present when at least one component has `component` equal to `MILK` and its food item's `category` is `MILK`. The grains are all whole-grain-rich when every component whose `component` is `GRAINS` has `is_whole_grain_rich` equal to true. Each of these sums is computed to two decimal places, round-half-up, and every threshold comparison below is inclusive ("at least").

For a `LUNCH` cycle, the cycle is `COMPLIANT` when the total meat/meat-alternate is at least 1.0 ounce-equivalent, the total grain is at least 1.0 ounce-equivalent, the total fruit-and-vegetable is at least 0.75 cup, milk is present, and all grains are whole-grain-rich. For a `BREAKFAST` cycle, the cycle is `COMPLIANT` when the total grain is at least 1.0 ounce-equivalent, the total fruit-and-vegetable is at least 0.5 cup, milk is present, and all grains are whole-grain-rich (breakfast imposes no meat/meat-alternate minimum). If any applicable condition fails, `compliance_status` is `NONCOMPLIANT`. This screen is re-run on any change to a cycle's components and is re-checked as a precondition at submission.

Submitting a cycle for review advances it from `DRAFT` to `UNDER_REVIEW`. Submission requires that the cycle's `compliance_status` be `COMPLIANT`; a non-compliant cycle is refused with `ERR_MEAL_PATTERN_VIOLATION` (422). Submission also requires that the cycle's `effective_date` be on or after the current clock date; an `effective_date` earlier than today's logical date is refused with `ERR_MENU_EFFECTIVE_DATE_PAST` (422). On a successful submit, the server sets `submitted_by_user_id` to the acting `X-User-ID` and clears any prior `rejection_note`.

A `NutritionDirector` then either approves or rejects a cycle that is `UNDER_REVIEW`; in both cases the acting `X-User-ID` must differ from the recorded `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (409). Approval advances the cycle from `UNDER_REVIEW` to `APPROVED` and additionally requires that no other `APPROVED` menu cycle for the same `site_id`, `meal_type`, and `grade_group` cover an overlapping half-open date range; because ranges are half-open, exact adjacency where one period's `end_date` equals another's `effective_date` is allowed, but any true overlap is refused with `ERR_MENU_PERIOD_OVERLAP` (409). Once approved, a cycle becomes eligible to back production records. Rejection reverts the cycle from `UNDER_REVIEW` back to `DRAFT` and records the reviewer's `rejection_note` from the request; this revert edge lets the planner correct and resubmit. An attempt to submit, approve, or reject a cycle that is not in the required starting state is refused with the generic `ERR_INVALID_STATE` (409). The terminal state of a menu cycle is `APPROVED`.

### 3.3. Receiving Inventory: Commodity and Purchased Lots

A `CafeteriaManager` receives stock as an **inventory lot** tied to a `site_id` and a `food_item_id`. The `lot_type` is either `COMMODITY_USDA_FOODS` or `PURCHASED`. The lot records `quantity_received`, an optional per-unit `unit_cost_cents` (default 0), and a `received_date` (`YYYY-MM-DD`) that serves as the primary ordering key when the lot is drawn down. On receipt, the lot's computed `quantity_on_hand` equals `quantity_received` and its `status` is `AVAILABLE`. Thereafter `quantity_on_hand` equals `quantity_received` minus the sum of depletions plus the sum of restorations, and the lot's `status` becomes `DEPLETED` exactly when `quantity_on_hand` reaches 0.

### 3.4. Production: Forecast, Preparation, and Inventory Depletion

A `CafeteriaManager` opens a **production record** for a specific service day against an approved menu. The record names its `site_id`, the `menu_cycle_id` it draws from, a `service_date` that must fall within that cycle's half-open `[effective_date, end_date)` period, a `meal_type` that must equal the cycle's `meal_type`, and a `planned_qty` of portions. Creation requires the referenced menu cycle to be both `APPROVED` and `COMPLIANT`, else `ERR_MENU_NOT_APPROVED` (409); a `meal_type` unequal to the cycle's `meal_type`, or a `service_date` outside the cycle's half-open period, is rejected with `ERR_VALIDATION` (400); and at most one production record may exist per site, service date, and meal type, a second being refused with `ERR_PRODUCTION_ALREADY_EXISTS` (409) — records already in `CANCELLED` do not count toward this uniqueness, so a fresh record may be opened for the same site, service date, and meal type after the prior one is cancelled. A new record starts in `PLANNED` status.

At creation the system computes the **forecast par**: `forecast_par_qty` is the forward-looking projection equal to `planned_qty` multiplied by the participation factor of 0.9, rounded half-up to a whole number of portions. This projection is derived solely from `planned_qty` and is independent of any actual meals. Distinct from it, `served_qty` is the chronological actual — a running count of the non-voided meal transactions linked to this record — and `leftover_qty` is `prepared_qty` minus `served_qty`, never allowed below zero and reported as 0 while the record is still `PLANNED`. The two figures deliberately diverge as real service departs from the projection.

Preparing a record advances it from `PLANNED` to `PREPARED`, sets `prepared_qty` from the request, and depletes inventory. The depletion is a **commodity-first FIFO waterfall**. For each menu component, the required units equal `prepared_qty` multiplied by that component's `serving_amount`. Those units are drawn from the site's inventory lots matching the component's `food_item_id`, in this exact order: all `COMMODITY_USDA_FOODS` lots before any `PURCHASED` lot; then by ascending `received_date`; then by ascending `created_at` (never by `id`). Each lot's `quantity_on_hand` is decremented until the required units are satisfied, and any lot reaching 0 flips to `DEPLETED`. Unit quantities are carried to three decimal places, round-half-up. If the total on-hand across all eligible lots for a component is less than the required units, the preparation is refused with `ERR_INSUFFICIENT_INVENTORY` (409) and no lot is partially depleted.

Cancelling a record moves it to the terminal `CANCELLED` status. A record still in `PLANNED` cancels with no inventory effect, since nothing was drawn. A record in `PREPARED` may cancel only if no non-voided meal transaction is linked to it — that is, its `served_qty` is 0 — else the cancel is refused with `ERR_INVALID_STATE` (409); when it does cancel, the system runs the compensating restoration, returning the exact per-lot amounts that were drawn back to the exact lots they came from, so each affected lot's `quantity_on_hand` increases and any lot that was `DEPLETED` flips back to `AVAILABLE`. This preserves the inventory-conservation invariant that a prepare followed by a cancel leaves on-hand quantities exactly as they began.

### 3.5. Students and the Prepay Account

A `PlatformAdmin` enrolls a **student** at a `site_id` with a `first_name`, `last_name`, and `grade` (`GRADES_K_5`, `GRADES_6_8`, or `GRADES_9_12`). The student's `eligibility_category` — `FREE`, `REDUCED`, or `PAID`, defaulting to `PAID` — is the meal-benefit tier snapshotted onto each meal at service time. The student sets a `low_balance_threshold_cents` (default 500). The prepay `balance_cents` is computed and starts at 0: it equals the sum of deposits, minus the sum of charges from non-voided meal transactions, plus the sum of refunds from voided transactions.

The student's `account_status` is derived from that balance: it is `NEGATIVE` when `balance_cents` is below 0; it is `LOW_BALANCE` when `balance_cents` is at or above 0 and at or below `low_balance_threshold_cents` (the threshold comparison is inclusive at both ends); and it is `ACTIVE` when `balance_cents` is strictly greater than `low_balance_threshold_cents`. A brand-new student, at a balance of 0, is therefore `LOW_BALANCE` whenever the threshold is at least 0. A `POSClerk` adds funds through a deposit carrying an `amount_cents`; the deposit increases `balance_cents`, recomputes `account_status`, and — if the student thereby leaves the `NEGATIVE` posture — decrements the owning site's `negative_balance_count`.

### 3.6. Point-of-Service Meals: Offer-vs-Serve, A-la-Carte, and Charging

A `POSClerk` records a **meal transaction** at the register. The payload names the `site_id`, `student_id`, `production_record_id`, `service_date`, `meal_type`, the `selected_components` the student took (a subset of `MEAT_MEAT_ALT`, `GRAINS`, `FRUIT`, `VEGETABLE`, and `MILK`), and an optional `a_la_carte_lines` array. A meal enters the `RECORDED` state on creation. The transaction's `service_date` must equal the linked production record's `service_date`; a mismatch is a body-shape violation rejected with `ERR_VALIDATION` (400), evaluated before the guards below.

Several guards apply, evaluated in the order given in §2.5. The linked production record must be `PREPARED`, else `ERR_PRODUCTION_NOT_READY` (409). Any a-la-carte line whose food item is a `SNACK` or `BEVERAGE` must pass the **Smart-Snacks** nutrient screen, else `ERR_NOT_SMART_SNACK_COMPLIANT` (422); a snack or beverage item passes only when its `calories` are at most 200, its `sodium_mg` is at most 200, its `total_fat_g` contributes at most 35% of its calories, its `sat_fat_g` contributes less than 10% of its calories, and its `total_sugar_g` is at most 35% of its `weight_g` by weight (fat grams convert to calories at nine calories per gram for the percentage-of-calories tests). The `student_id` must belong to the same site as the transaction's `site_id`, else `ERR_STUDENT_SITE_MISMATCH` (409). Every value in `selected_components` must be a component offered by the production record's menu cycle, else `ERR_INVALID_COMPONENT` (422).

At service the meal's `claim_category` is snapshotted from the student's current `eligibility_category`. **Offer-vs-serve** then determines the meal's `meal_claim_status`. The number taken is the count of distinct `selected_components`, and the meal has a fruit-or-vegetable when `selected_components` includes at least one of `FRUIT` or `VEGETABLE`. A lunch meal is `REIMBURSABLE` when the number taken is at least 3 and it has a fruit-or-vegetable; a breakfast meal is `REIMBURSABLE` when the number taken is at least 3 and it has a fruit-or-vegetable. A meal that fails offer-vs-serve is `NON_REIMBURSABLE`. Additionally, at most one `REIMBURSABLE` meal is allowed per student, service date, and meal type: a second reimbursable meal for that same combination is refused with `ERR_DUPLICATE_REIMBURSABLE_MEAL` (409).

The **a-la-carte total** is computed line by line with tax rounded per line before summation. For each line — carrying a `food_item_id`, a `qty`, and a `unit_price_cents` — the base is `qty` multiplied by `unit_price_cents`, the line tax is that base multiplied by the site's `sales_tax_bps` divided by 10000 and then rounded half-up to whole cents, and the line total is the base plus the rounded tax. The transaction's `alacarte_total_cents` is the sum of the per-line totals. The tax must be rounded to whole cents on each line first and the rounded line totals summed afterward; summing the raw bases and rounding the aggregate once is explicitly not used and generally yields a different result.

The `meal_charge_cents` is the amount charged to the student's prepay account: it is the reimbursable-meal price or copay for the meal — determined by the snapshotted `claim_category` and the `meal_type` — plus `alacarte_total_cents`. A `FREE` student is charged nothing for the meal itself; a `REDUCED` student is charged the site's `reduced_lunch_copay_cents` for lunch or `reduced_breakfast_copay_cents` for breakfast; a `PAID` student is charged the site's `paid_lunch_price_cents` for lunch or `paid_breakfast_price_cents` for breakfast. Charging the student decreases `balance_cents` by `meal_charge_cents`, recomputes `account_status`, and — if the student thereby flips into the `NEGATIVE` posture — increments the owning site's `negative_balance_count`. If the resulting `balance_cents` would fall below 0 and the site's `negative_balance_allowed` is false, the whole transaction is refused with `ERR_INSUFFICIENT_BALANCE` (402). The `payment_status` is `PAID` when `meal_charge_cents` is 0 or the charge is fully covered by available funds, and `CHARGED` when the charge drove the balance negative at a site that permits it.

Recording a meal also updates downstream aggregates: the linked production record's `served_qty` increments and its `leftover_qty` is recomputed, and if a `DRAFT` reimbursement claim exists for the transaction's site and its service month, that claim's free, reduced, and paid counts are recomputed and its `version` is incremented.

Voiding a meal moves it from `RECORDED` to the terminal `VOIDED` state and is permitted only while the meal is `RECORDED`, else `ERR_INVALID_STATE` (409). A void sets `meal_claim_status` to `VOIDED` and `payment_status` to `REFUNDED`, and runs the compensating refund: `balance_cents` increases by exactly the original `meal_charge_cents`, `account_status` is recomputed, and if the student thereby leaves the `NEGATIVE` posture the site's `negative_balance_count` is decremented. The linked production record's `served_qty` decrements and `leftover_qty` is recomputed, and any `DRAFT` claim for the site and month has its counts recomputed and its `version` incremented. This preserves the prepay money-conservation invariant that a charge followed by its void nets to zero.

### 3.7. Monthly Reimbursement Claims: Estimate, Recall, and Final Settlement

A `NutritionDirector` opens a **reimbursement claim** for a `site_id` and a `claim_month` (`YYYY-MM`). At most one claim may exist per site and month; a duplicate is refused with `ERR_CLAIM_ALREADY_EXISTS` (409). The claim starts in `DRAFT`, records the opener's `X-User-ID` in `created_by_user_id`, and derives its counts. The counts are `free_count`, `reduced_count`, and `paid_count` — respectively the number of reimbursable, non-voided meal transactions in the claim month whose `claim_category` is `FREE`, `REDUCED`, or `PAID`. Because meals and voids for the month keep arriving, these counts and the claim's `version` are kept live: while a claim is `DRAFT`, every qualifying meal or void for the site and month recomputes the counts and bumps the `version`.

Submitting a claim advances it from `DRAFT` to `SUBMITTED`. Submission is guarded by optimistic concurrency: the request's `expected_claim_version` must equal the claim's current `version`, else `ERR_STALE_CLAIM_VERSION` (412), as described in §2.7. The acting `X-User-ID` must also differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (409). On success the server records the submitter in `submitted_by_user_id`, computes the **estimated** reimbursement into `estimated_reimbursement_cents` from the counts as of submission time, and increments the claim's `version` by one.

The **reimbursement amount** is computed the same way for both the estimate and the final figure, differing only in when the counts are read. It is computed per reimbursable meal rather than from the claim-level counts: each reimbursable, non-voided meal transaction in the claim month contributes the rate for the program derived from that meal's own `meal_type` — `NSLP` for a `LUNCH` meal and `SBP` for a `BREAKFAST` meal — paired with that meal's snapshotted `claim_category`. For each such program-and-category pairing, the applicable rate is the `rate_cents` of the reimbursement-rate row matching that program, category, and the site's severe-need flag, selected as the row with the greatest `effective_date` on or before the first day of the claim month (ties broken by greatest `created_at`, never by `id`); the add-on is the row's `performance_addon_cents` when the site is performance-based certified and 0 otherwise. The total amount is the sum, over every reimbursable non-voided meal in the month, of that meal's applicable `rate_cents` plus its add-on, all in whole cents; this equals `free_count`, `reduced_count`, and `paid_count` each multiplied by their category rate plus add-on only when every reimbursable meal in the month shares one program, and it diverges from that counts-times-rate shortcut in a month that mixes breakfast and lunch reimbursable meals. If no applicable rate row exists for a needed program-and-category pairing, the computation is refused with `ERR_RATE_NOT_FOUND` (409).

A submitted claim may be recalled by a `NutritionDirector`, reverting it from `SUBMITTED` back to `DRAFT`; recall clears `submitted_by_user_id` and increments `version` by one, reopening the claim so that late meals can be captured before it is resubmitted. Finally, a `PlatformAdmin` marks a submitted claim paid, advancing it from `SUBMITTED` to the terminal `PAID` state; this computes the **final** reimbursement into `final_reimbursement_cents` from the counts as of payment time and increments `version` by one. Because meals voided after submission lower the counts, the final figure is at most the earlier estimate — the `final_reimbursement_cents` remains null until the claim is `PAID`. Attempting any of these transitions from the wrong starting state is refused with `ERR_INVALID_STATE` (409), and the rate-availability check applies at both submit and mark-paid.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions, deposits, and the clock control — return `200 OK`. All list and single-get reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nutrition/sites` | Create a school site | PlatformAdmin |
| GET | `/nutrition/sites/{id}` | Get a school site | PlatformAdmin, MenuPlanner, NutritionDirector, CafeteriaManager, POSClerk |
| POST | `/nutrition/food-items` | Create a food item | PlatformAdmin |
| GET | `/nutrition/food-items/{id}` | Get a food item | PlatformAdmin, MenuPlanner, NutritionDirector, CafeteriaManager, POSClerk |
| POST | `/nutrition/reimbursement-rates` | Create a reimbursement rate row | PlatformAdmin |
| POST | `/nutrition/menu-cycles` | Create a DRAFT menu cycle | MenuPlanner |
| GET | `/nutrition/menu-cycles/{id}` | Get a menu cycle | PlatformAdmin, MenuPlanner, NutritionDirector, CafeteriaManager, POSClerk |
| GET | `/nutrition/menu-cycles` | List/filter menu cycles | PlatformAdmin, MenuPlanner, NutritionDirector, CafeteriaManager, POSClerk |
| POST | `/nutrition/menu-cycles/{id}/submit` | Submit a menu cycle for review | MenuPlanner |
| POST | `/nutrition/menu-cycles/{id}/approve` | Approve a menu cycle under review | NutritionDirector |
| POST | `/nutrition/menu-cycles/{id}/reject` | Reject a menu cycle under review | NutritionDirector |
| POST | `/nutrition/inventory-lots` | Receive an inventory lot | CafeteriaManager |
| GET | `/nutrition/inventory-lots/{id}` | Get an inventory lot | PlatformAdmin, CafeteriaManager, NutritionDirector |
| GET | `/nutrition/inventory-lots` | List/filter inventory lots | PlatformAdmin, CafeteriaManager, NutritionDirector |
| POST | `/nutrition/production-records` | Create a PLANNED production record | CafeteriaManager |
| GET | `/nutrition/production-records/{id}` | Get a production record | PlatformAdmin, CafeteriaManager, NutritionDirector, POSClerk |
| GET | `/nutrition/production-records` | List/filter production records | PlatformAdmin, CafeteriaManager, NutritionDirector, POSClerk |
| POST | `/nutrition/production-records/{id}/prepare` | Prepare a record and deplete inventory | CafeteriaManager |
| POST | `/nutrition/production-records/{id}/cancel` | Cancel a record (restore inventory if prepared) | CafeteriaManager |
| POST | `/nutrition/students` | Create a student | PlatformAdmin |
| GET | `/nutrition/students/{id}` | Get a student | PlatformAdmin, POSClerk, NutritionDirector |
| GET | `/nutrition/students` | List/filter students | PlatformAdmin, POSClerk, NutritionDirector |
| POST | `/nutrition/students/{id}/deposit` | Add funds to a student's prepay account | POSClerk |
| POST | `/nutrition/meal-transactions` | Record a point-of-service meal | POSClerk |
| GET | `/nutrition/meal-transactions/{id}` | Get a meal transaction | PlatformAdmin, POSClerk, NutritionDirector |
| GET | `/nutrition/meal-transactions` | List/filter meal transactions | PlatformAdmin, POSClerk, NutritionDirector |
| POST | `/nutrition/meal-transactions/{id}/void` | Void a meal transaction | POSClerk |
| POST | `/nutrition/reimbursement-claims` | Open a DRAFT monthly claim | NutritionDirector |
| GET | `/nutrition/reimbursement-claims/{id}` | Get a reimbursement claim | PlatformAdmin, NutritionDirector |
| GET | `/nutrition/reimbursement-claims` | List/filter reimbursement claims | PlatformAdmin, NutritionDirector |
| POST | `/nutrition/reimbursement-claims/{id}/submit` | Submit a DRAFT claim (OCC-guarded) | NutritionDirector |
| POST | `/nutrition/reimbursement-claims/{id}/recall` | Recall a SUBMITTED claim to DRAFT | NutritionDirector |
| POST | `/nutrition/reimbursement-claims/{id}/mark-paid` | Mark a SUBMITTED claim PAID | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (UTC) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRODUCTION_NOT_READY` | 409 |
| `ERR_MENU_NOT_APPROVED` | 409 |
| `ERR_MEAL_PATTERN_VIOLATION` | 422 |
| `ERR_NOT_SMART_SNACK_COMPLIANT` | 422 |
| `ERR_STUDENT_SITE_MISMATCH` | 409 |
| `ERR_RATE_NOT_FOUND` | 409 |
| `ERR_INVALID_COMPONENT` | 422 |
| `ERR_MENU_PERIOD_OVERLAP` | 409 |
| `ERR_PRODUCTION_ALREADY_EXISTS` | 409 |
| `ERR_DUPLICATE_REIMBURSABLE_MEAL` | 409 |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 |
| `ERR_MENU_EFFECTIVE_DATE_PAST` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |

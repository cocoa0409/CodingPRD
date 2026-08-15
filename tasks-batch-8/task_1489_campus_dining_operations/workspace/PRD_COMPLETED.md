# Campus Dining Operations API — Product Requirements Document

## 1. Introduction

Universities that outsource dining to a contract vendor such as Aramark or Sodexo run two businesses under one roof: a **board operation**, where students on meal plans enter the hall on a swipe and the university pays the vendor a fixed rate per cover, and a **retail operation**, where guests pay cash-equivalent prices at the register and the vendor owes the university a commission on every sale. Around those two revenue engines sit the operational disciplines that decide whether the program is safe and solvent: menu cycles and production forecasting from historical swipe data, allergen and dietary labeling with a dietitian review loop for special-diet students, labor scheduling against the class-rush calendar, food-waste tracking toward sustainability commitments, health-inspection compliance with corrective actions, catering for campus departments, and a monthly commission settlement with the vendor under a minimum-guarantee contract.

This document specifies the Campus Dining Operations API, the system of record for that entire program. It governs the lifecycle of dining halls and their vendor contracts, menu cycles and recipes, individual meal periods from scheduling through reconciliation, swipe ingestion, production forecasts, labor shifts, waste logs, inspection reports and corrective actions, departmental catering orders, and monthly commission statements. The API is built around two organizing ideas: **posture-driven gating**, where the operational posture of a dining hall (active or suspended) and the review posture of its recipes and corrective actions determine which workflows may proceed, and **ledger reconciliation**, where departmental catering budgets and vendor commission statements are recomputed deterministically from the events that actually settled. All date and time comparisons inside the system are evaluated against a logical clock described in §2.4, never against the server's wall clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. If either header is missing or blank, or if the role name is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not authorized for the target endpoint — or, for a `DepartmentUser`, the user attempts to act on another department's resources — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes seven roles:

- **`DiningAdmin`** — vendor-side operations administrator; owns dining halls, vendor-contract lifecycle data, menu cycles, commission statements, campus departments, and the logical clock.
- **`HallManager`** — runs a dining hall day to day: meal periods, swipe ingestion, labor scheduling, waste verification and posting, catering approval, and inspection acknowledgment.
- **`KitchenLead`** — production lead: recipes, production forecasts, waste recording, catering fulfillment, and accommodation activation.
- **`Dietitian`** — nutrition specialist; drives the special-diet accommodation review loop.
- **`HealthInspector`** — university environmental-health-and-safety inspector; files and submits inspection reports and manages corrective-action verification.
- **`ContractManager`** — university procurement; activates and terminates vendor contracts and finalizes commission statements.
- **`DepartmentUser`** — campus department staffer who orders catering.

**Identity semantics.** When `X-User-Role` is `DepartmentUser`, `X-User-ID` is the `id` of the acting `Department`; ownership checks on any resource that references a `Department` compare the resource's foreign-key field to `X-User-ID`. In particular, a `DepartmentUser` may create a catering order only when the request body's `department_id` equals `X-User-ID`, may read a department resource only for their own `id`, and may cancel only their own department's orders; any attempt to act for another department is rejected with `ERR_FORBIDDEN`. For the remaining six roles — `DiningAdmin`, `HallManager`, `KitchenLead`, `Dietitian`, `HealthInspector`, and `ContractManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `recorded_by_user_id` on a `WasteLog`, `inspector_user_id` on an `InspectionReport`, or `resolved_by_user_id` and `verified_by_user_id` on a `CorrectiveAction`) but does not compare it to any entity's `id` for ownership purposes. Ownership checks that can be decided without loading a resource — a `DepartmentUser` reading a department whose path `id` differs from their `X-User-ID`, or supplying another department's `department_id` in a create body — run at tier 2, before any existence check. Where ownership instead depends on a loaded resource — a `DepartmentUser` submitting or cancelling a specific catering order — the path identifier is resolved first, so a non-existent order id yields `ERR_NOT_FOUND` before ownership is evaluated against the loaded order.

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

Requests to an undefined path, or to a defined path with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope. An unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500) in this same envelope.

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_VALIDATION`.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order, with resources created in the same instant ordered by creation sequence.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `total_count` counts all matching resources before windowing, and `has_more` is true exactly when `offset + limit` is less than `total_count`.

List endpoints also accept exact-match filter query parameters, each restricting the result to records whose named field equals the supplied value: `status` for dining halls; `dining_hall_id` and `status` for vendor contracts and for menu cycles; `dining_hall_id`, `station`, and `status` for recipes; `dining_hall_id`, `menu_cycle_id`, `service_date`, `meal_period`, and `status` for meal periods; `meal_period_id` and `entry_type` for swipe events; `meal_period_id`, `recipe_id`, `status`, and `variant` for production forecasts; `dining_hall_id`, `status`, and `student_ref` for accommodation requests; `dining_hall_id`, `staff_ref`, `shift_date`, and `status` for labor shifts; `meal_period_id`, `status`, `category`, and `disposition` for waste logs; `dining_hall_id`, `status`, and `outcome` for inspection reports; `inspection_report_id`, `status`, and `severity` for corrective actions; `dining_hall_id`, `department_id`, `approval_status`, `fulfillment_status`, and `revised_from_id` for catering orders; and `vendor_contract_id`, `period_month`, and `status` for commission statements.

### 2.4. The Logical Clock and Scheduled Sweeps

All date and datetime comparisons in state machines, calculations, and validations — lead times, rest buffers, overdue determinations, contract expiry — are evaluated against a **logical clock**, never the server's wall clock. Before any client call, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `DiningAdmin` moves time forward through an admin-only test-driving capability that sets the logical clock to a supplied `to_iso8601` instant. The `to_iso8601` field is required and must be an ISO 8601 timestamp string, else `ERR_VALIDATION`; any parseable instant is accepted as given — the server does not require it to be later than the current value.

Setting the clock is not a passive act: it runs an **operations sweep** inside the same request. Two families of resources are transitioned by the sweep. First, every vendor contract in `ACTIVE` status whose `effective_end_date` is less than or equal to the new clock value transitions to `EXPIRED` — because the contract's effective interval is half-open, a contract whose end date equals the new clock value expires at that instant. Second, every corrective action in `OPEN` status whose `due_date` falls strictly before the new clock's date transitions to `OVERDUE` — an action whose due date equals the new clock date is *not* overdue. Each resource transitioned by the sweep has its own `version` incremented by 1. The sweep response returns the new `current_utc` — echoing the supplied `to_iso8601` string verbatim — alongside two arrays, `expired_contract_ids` and `overdue_corrective_action_ids`, listing the identifiers of every resource the sweep transitioned, each in creation order.

### 2.5. Common Resource Properties and Versioning

Every resource exposed by the API carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2025-05-24T10:30:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly 1 on every modification of the resource, including every state transition and every recomputation of a derived field described in §3.

One entity deviates from this convention: the `SwipeEvent` is an append-only ingestion record and carries only `id` and `created_at` from the common set. Both `updated_at` and `version` are absent from `SwipeEvent` representations.

The blanket rule above means that whenever §3 describes a transition — a hall being suspended, a forecast being locked, a statement being disputed — the acting resource's `version` rises by 1 and its `updated_at` refreshes. Cross-entity version bumps, where an operation on one resource also mutates another (for example, a catering approval that moves money between a department's budget buckets), increment the other resource's `version` by 1 as well; each such cascade is stated explicitly where it occurs.

### 2.6. Precision, Rounding, and Measurement Units

All monetary amounts are integer cents — never fractional, never floating point — and all commission-style rates are expressed in basis points. Wherever a calculation produces a non-integer cent or portion figure, the result is **rounded half-up** to the nearest whole unit: a fraction of exactly one half rounds away from zero. Portion counts and cover counts are likewise integers produced by rounding half-up.

Waste masses (`posted_waste_kg`, `landfill_waste_kg`, and individual log weights) are numbers with 2 decimal places, rounded half-up. The `diversion_rate` is carried to 4 decimal places. The `forecast_variance_pct` is a percentage number carried to 2 decimal places, rounded half-up. Scores on inspection reports are integers.

### 2.7. Validation Pipeline and Error Precedence

When several rules fail on the same request, the server does not report them all: it reports the failure from the **earliest tier** of a fixed ten-tier validation pipeline. The tiers are evaluated in the following order, and a request that fails an earlier tier never reaches a later one:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present, non-blank, and carry a recognized role name; failures yield `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role appears in the endpoint's authorized set, and a `DepartmentUser` is acting on their own department; failures yield `ERR_FORBIDDEN`.
3. **Existence** — path identifiers resolve left-to-right, then request-body foreign keys resolve in their declared input order; failures yield `ERR_NOT_FOUND`.
4. **State** — the target entity sits in one of the transition's from-states (`ERR_INVALID_STATE`), and the cross-entity state gates live at this same tier: `ERR_HALL_SUSPENDED` when an operation requires an `ACTIVE` hall, `ERR_CONTRACT_NOT_ACTIVE` when a statement operation requires an `ACTIVE` contract, `ERR_FORECAST_LOCKED_PERIOD` when a forecast operation requires a `SCHEDULED` period, `ERR_PENDING_WASTE_LOGS` when a period close finds unposted waste, and `ERR_INSPECTION_INCOMPLETE` when a report close finds unverified actions. Optimistic-concurrency staleness (`ERR_STALE_VERSION`) is also evaluated at this tier, immediately **after** from-state validation.
5. **Segregation of duties** — on waste-log verification, the verifier must not be the recorder; failures yield `ERR_SEGREGATION_OF_DUTIES` even when the verifier's role is otherwise allowed.
6. **Food-safety gates** — allergen-review completeness (`ERR_ALLERGEN_UNDECLARED`), suitable-menu existence (`ERR_NO_SUITABLE_MENU`), and open critical violations (`ERR_CRITICAL_VIOLATION_OPEN`).
7. **Structural conflicts** — menu-cycle interval overlap (`ERR_CYCLE_OVERLAP`), staff shift overlap (`ERR_SHIFT_OVERLAP`), catering slot capacity (`ERR_CATERING_CAPACITY_EXCEEDED`), a second `ACTIVE` contract at one hall (`ERR_DUPLICATE_ACTIVE_CONTRACT`), a second `DRAFT` forecast for the same period-recipe pair (`ERR_DUPLICATE_FORECAST`), and a second statement for the same contract month (`ERR_DUPLICATE_STATEMENT`).
8. **Temporal rules against the logical clock** — catering lead time (`ERR_LEAD_TIME_VIOLATION`), staff rest buffer (`ERR_REST_PERIOD_VIOLATION`), waste recording outside the open window (`ERR_WASTE_WINDOW_CLOSED`), and trend forecasting with insufficient history (`ERR_INSUFFICIENT_HISTORY`).
9. **Fiscal checks** — money is checked last among the business rules: catering submission requires sufficient departmental budget (`ERR_INSUFFICIENT_BUDGET`).
10. **Field shape** — required fields present, enum values in range, date intervals with start before end, swipe amounts consistent with entry type, worked-minutes bounds, invoice-total bounds; failures yield `ERR_VALIDATION`. Malformed-field rejections surface only after every higher-tier business check has passed for the affected resource — except authentication and existence, which always precede everything.

So, for example, a waste-log verification attempted by the wrong role on a period in the wrong state reports `ERR_INVALID_STATE`, not `ERR_SEGREGATION_OF_DUTIES`, because the state tier (tier 4) precedes the segregation tier (tier 5); and a catering submission that is simultaneously too close to the event and over budget reports `ERR_LEAD_TIME_VIOLATION`, because the temporal tier (tier 8) precedes the fiscal tier (tier 9).

### 2.8. Optimistic Concurrency Control

Two write operations in the API guard a parent aggregate with optimistic concurrency control, and these are the only two endpoints that accept a version field:

- Creating a production forecast against a meal period requires the request to carry `expected_meal_period_version`, holding the `version` of the parent `MealPeriodService` the client last observed. If the period's current `version` does not match — for instance because another planner has just created a forecast, which legitimately supersedes the prior locked forecast for the same recipe and advances the period's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a period state it has not observed.
- Approving a catering order requires the request to carry `expected_department_version`, holding the `version` of the order's `Department` the approver last observed. If the department's current `version` does not match — because another approval or rejection has just moved funds between the department's reserved and committed buckets — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412) and must be re-issued against fresh figures.

In both cases the version field is required and must be an integer — a missing or non-integer value is rejected with `ERR_VALIDATION` — and the staleness check runs immediately after from-state validation within tier 4 of the pipeline (§2.7). Endpoints not listed here do not take a version field of any kind.

### 2.9. Nested Resource Retrieval and Reference Resolution

The API enforces strict, hierarchical validation of resource references. When an endpoint path contains multiple resource identifiers, the system validates the existence of each identifier sequentially, left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve — a request aimed at forecasts under a non-existent meal period never attempts to interpret the request body. For request bodies that carry several foreign keys, existence is then checked in the fields' declared input order: `dining_hall_id` before `menu_cycle_id` before `recipe_id`; `department_id` before `revised_from_id`; and so on. This ordering is part of the contract, because it determines which `ERR_NOT_FOUND` surfaces when several references are simultaneously wrong.

### 2.10. Suspension Cascades and Posture-Driven Gating

A dining hall's `status` is the master posture flag for its operations. When a hall leaves `ACTIVE` — whether suspended directly by a `DiningAdmin` or cascaded out of a failed inspection or a reopened critical corrective action — the system immediately resolves its dependent work: every `MealPeriodService` at the hall still in `SCHEDULED` status transitions to `CANCELLED`, with each cancelled period's `version` incremented by 1. Meal periods that have already advanced to `FORECAST_LOCKED` or beyond are deliberately *not* auto-cancelled, because they carry locked forecasts or live service data that must settle through their own lifecycle.

The converse direction is gated: while any `CRITICAL`-severity corrective action at the hall sits in `OPEN` or `OVERDUE` status, both reactivating the hall and approving a catering order at the hall are refused with `ERR_CRITICAL_VIOLATION_OPEN`. Likewise, opening a meal period for service and confirming a labor shift each require the parent hall to be `ACTIVE` (otherwise `ERR_HALL_SUSPENDED`), as does submitting a catering order. These gates are what the product calls **posture-driven gating**: the hall, its recipes, and its corrective actions form a posture surface that downstream workflows test before they proceed.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Dining Hall and Its Vendor Contract

Everything begins with the **dining hall**. A `DiningAdmin` creates a hall with a display `name`, a `service_model` of `BOARD`, `RETAIL`, or `HYBRID` describing whether the hall runs board swipes, cash-register retail, or both, a `dining_capacity` giving the dining-room seat count (must be greater than zero; it feeds the forecast fallback in §3.3), and a `catering_kitchen_capacity` giving the maximum aggregate guaranteed covers the catering kitchen can produce for a single date-and-slot pool (also greater than zero). A new hall starts `ACTIVE`.

Suspension and recovery bracket the hall's working life. A `DiningAdmin` may suspend an `ACTIVE` hall, moving it to `SUSPENDED`; the cascade of §2.10 fires, cancelling every `SCHEDULED` meal period at the hall while leaving `FORECAST_LOCKED` and later periods untouched. Reactivation moves the hall from `SUSPENDED` back to `ACTIVE`, but only when no `CRITICAL` corrective action in `OPEN` or `OVERDUE` status exists on any inspection report filed for that hall — otherwise the request is refused with `ERR_CRITICAL_VIOLATION_OPEN`.

Each hall's commercial terms live on a **vendor contract**, created by a `DiningAdmin` in `NEGOTIATION` status. The contract names its hall via `dining_hall_id`, records the vendor's legal `vendor_name`, and carries four money terms: `board_rate_per_cover_cents`, the amount the university pays the vendor per board-swipe cover (zero or more); `retail_commission_bps`, the basis points of each retail sale the vendor owes back to the university; `catering_commission_bps`, the basis points of catering totals owed to the university; and `minimum_monthly_guarantee_cents`, the floor of commission the vendor guarantees per settlement month (zero or more). Both basis-point fields range from 0 to 10,000 inclusive. The contract's `effective_start_date` and `effective_end_date` describe a half-open interval — the end date itself is the first day the contract no longer covers — and the end date must be strictly later than the start date, or creation fails with `ERR_VALIDATION`.

A `ContractManager` activates a contract in `NEGOTIATION`, moving it to `ACTIVE`; activation is refused with `ERR_DUPLICATE_ACTIVE_CONTRACT` when another contract at the same hall is already `ACTIVE`, since a hall has at most one active vendor agreement. An `ACTIVE` contract may be terminated by a `ContractManager`, moving it to `TERMINATED`, or may expire on its own: the clock sweep of §2.4 moves every `ACTIVE` contract whose `effective_end_date` has been reached to `EXPIRED`. Both `EXPIRED` and `TERMINATED` are terminal.

### 3.2. Menu Cycles, Recipes, and Allergen Governance

Menus rotate on **menu cycles**. A `DiningAdmin` creates a cycle for a hall (`dining_hall_id`) with a `name` such as "Fall-2026 Cycle A", a `cycle_length_weeks` between 1 and 8 inclusive, and a half-open `start_date`/`end_date` interval whose end must be strictly after its start. Cycles are born `DRAFT`. Publishing a cycle is the moment allergen governance bites: every recipe at the same hall whose `status` is `ACTIVE` must have `allergen_reviewed` set to true, or publication is refused with `ERR_ALLERGEN_UNDECLARED` (the check is vacuously satisfied when the hall has no active recipes at all). Publication also enforces exclusivity of coverage — no other `PUBLISHED` cycle at the same hall may have a half-open interval that intersects this cycle's interval. Because both intervals are half-open, adjacency is allowed: one cycle's `end_date` equaling another's `start_date` is not an overlap. A violation is rejected with `ERR_CYCLE_OVERLAP`. A cycle in either `DRAFT` or `PUBLISHED` may be archived by a `DiningAdmin`, moving it to `ARCHIVED`, which is terminal.

**Recipes** are the unit of menu planning. A `KitchenLead` creates a recipe for a hall with a `name`, a `station` drawn from `GRILL`, `DELI`, `PIZZA`, `SALAD`, `GLOBAL`, or `BAKERY`, and two labeling arrays: `allergen_tags`, drawn from `MILK`, `EGG`, `PEANUT`, `TREE_NUT`, `SOY`, `WHEAT`, `FISH`, `SHELLFISH`, and `SESAME`, and `dietary_flags`, drawn from `VEGAN`, `VEGETARIAN`, `HALAL`, `KOSHER`, and `GLUTEN_FREE`. An empty `allergen_tags` array is a public claim that the dish is allergen-free, so it is only valid when `allergen_reviewed` is true; a recipe carrying no allergen tags without dietitian review is rejected with `ERR_VALIDATION`. Recipes also carry `popularity_share` — the fraction of a meal period's covers expected to choose this dish, strictly greater than 0 and at most 1 — and `unit_cost_cents`, the food cost per portion, strictly greater than 0. The `allergen_reviewed` flag defaults to false and flips to true only once a dietitian-reviewed allergen label exists; it may be supplied at creation or changed later. New recipes start `ACTIVE`.

A `KitchenLead` may re-label or re-cost a recipe in place, optionally changing any of `name`, `station`, `allergen_tags`, `dietary_flags`, `popularity_share`, `unit_cost_cents`, or `allergen_reviewed`, in any status — a suspended recipe may be patched as freely as an active one. Fields supplied with a null value are ignored as if omitted, the empty-`allergen_tags` rule above is re-validated against the merged result, and the recipe's `version` increments on every such call, even one that changes nothing. When an allergen audit casts doubt on a recipe, a `DiningAdmin` suspends it (`ACTIVE` → `SUSPENDED`); reinstatement moves it back to `ACTIVE` but only when `allergen_reviewed` is true at that moment, otherwise `ERR_ALLERGEN_UNDECLARED`.

### 3.3. The Meal Period: Scheduling, Forecasting, Service, and Reconciliation

The operational heartbeat of a hall is the **meal period**. A `HallManager` schedules one by naming the hall (`dining_hall_id`), the governing `menu_cycle_id`, a `service_date`, and a `meal_period` of `BREAKFAST`, `LUNCH`, `DINNER`, or `LATE_NIGHT`. The named cycle must belong to the named hall, must be `PUBLISHED`, and must cover the service date — the date must fall inside the cycle's half-open interval — otherwise creation is rejected with `ERR_VALIDATION`. A new period starts `SCHEDULED`, with `forecasted_covers`, `actual_board_swipes`, `actual_retail_sales_cents`, `actual_covers`, `posted_waste_kg`, and `landfill_waste_kg` all at 0, `forecast_variance_pct` and `diversion_rate` null, and `sustainability_alert` false.

**Production forecasts** are how the kitchen translates swipe history into a cook plan. A `KitchenLead` creates a forecast for one recipe on one period, naming the `recipe_id` and a `variant` of `BASE` or `TREND`. The named recipe must be `ACTIVE` and belong to the period's hall, otherwise `ERR_VALIDATION`. The parent period must still be `SCHEDULED`; once it has advanced past scheduling, forecast creation is refused with `ERR_FORECAST_LOCKED_PERIOD`. The request is also optimistic-concurrency guarded per §2.8: it must carry `expected_meal_period_version` matching the period's current `version`, with a mismatch rejected as `ERR_STALE_VERSION`. Two forecasts for the same period-and-recipe pair may not both sit in `DRAFT` — a second attempt is refused with `ERR_DUPLICATE_FORECAST`. Within one create request the guards fire in this order: the period's state gate, the staleness check, the duplicate-pair guard, the recipe's activity and hall membership, the variant's validity, and only then the history computation — so a request failing several of these reports the first of them in that order. When the create succeeds, any previously `LOCKED` forecast for the same pair is superseded by cascade, moving to `SUPERSEDED` with its own `version` incremented; the invariant maintained before and after is that at most one `LOCKED` forecast exists per period-and-recipe pair at any time. Successful creation also advances the parent period's `version` by 1. Each forecast is stored against its period through its `meal_period_id`, starts `DRAFT`, and may be locked by a `KitchenLead` (`DRAFT` → `LOCKED`); locking likewise requires the parent period to still be `SCHEDULED`, else `ERR_FORECAST_LOCKED_PERIOD`.

Both the create and the period-level lock compute portions through the same forward-looking algorithm. The historical occurrence set for a target period is built from periods at the same hall, in the same `meal_period`, whose service date falls exactly a whole number of weeks before the target's `service_date` — the same weekday in prior weeks — and whose status is `IN_SERVICE`, `RECONCILED`, or `CLOSED`. The four most recent such occurrences by service date are selected; the system does not enforce one period per date-and-slot, so if several selected candidates share the same service date, the tie is broken by earlier creation first. A historical period's cover count is the number of swipe events ingested against it, with `BOARD_SWIPE` and `RETAIL_SALE` events each counting as one cover.

When at least two historical occurrences exist, their mean cover count is computed and rounded half-up to a whole number. Under the `BASE` variant — the default planning variant — that rounded mean is the period's base covers. Under the `TREND` variant, a linear slope is added: the difference between the newest occurrence's covers and the oldest occurrence's covers, divided by one less than the number of selected occurrences (which ranges from two to four), is added to the rounded mean, and the sum is rounded half-up a second time to give base covers. When fewer than two historical occurrences exist, a `TREND` request is refused with `ERR_INSUFFICIENT_HISTORY`, while `BASE` falls back to the hall's seats: base covers is the hall's `dining_capacity` multiplied by 60 percent, rounded half-up. In all cases the forecast's `forecasted_portions` is the base covers multiplied by the recipe's `popularity_share` and then multiplied by 1.05 — a five percent preparation buffer — rounded half-up to a whole portion, and the computed `base_covers` is stored on the forecast alongside it. Both figures are frozen at creation.

Locking the period's forecast (`SCHEDULED` → `FORECAST_LOCKED`) is performed by a `HallManager` and is refused with `ERR_INVALID_STATE` unless at least one production forecast exists for the period and none of its forecasts remains in `DRAFT`. At that moment the `BASE` rule above runs at the period level — capacity fallback included — and the result is stored as the period's `forecasted_covers`.

Opening service (`FORECAST_LOCKED` → `IN_SERVICE`) requires the hall to be `ACTIVE`; a suspended hall refuses with `ERR_HALL_SUSPENDED`. Once `IN_SERVICE`, the register opens: a `HallManager` bulk-ingests entry events by posting an `events` array whose elements each carry an `entry_type` of `BOARD_SWIPE` or `RETAIL_SALE`, an `amount_cents`, and an optional `count` that expands the element into that many individual swipe-event rows (a single row when omitted or null), created in array order; a supplied `count` must be an integer of at least 1. The batch is all-or-nothing — any invalid element rejects the entire batch with `ERR_VALIDATION` and nothing is persisted. The amount rule is conditional on entry type: a `RETAIL_SALE` must carry an `amount_cents` strictly greater than 0, while a `BOARD_SWIPE` must carry exactly 0. Each persisted row is bound to the period through its `meal_period_id` and records the logical-clock ingestion instant as its `recorded_at`; being an append-only record, it carries no `updated_at` or `version` (§2.5). Ingestion is accepted only while the period is `IN_SERVICE`. A successful ingestion returns `201 Created` with `response_type` "array", its `data` holding the created swipe-event rows in ingestion order; being a bulk create rather than a list endpoint, its `meta` carries no pagination fields.

Reconciliation (`IN_SERVICE` → `RECONCILED`) is where the register rolls up. The system counts the period's `BOARD_SWIPE` events into `actual_board_swipes`, sums the `amount_cents` of its `RETAIL_SALE` events into `actual_retail_sales_cents`, and sets `actual_covers` to the board-swipe count plus the number of retail-sale events. The `forecast_variance_pct` is then the actual covers minus the forecasted covers, divided by the forecasted covers, times one hundred, carried to 2 decimal places rounded half-up; when `forecasted_covers` is 0 the variance is null rather than a division by zero.

Closing (`RECONCILED` → `CLOSED`) is performed by a `DiningAdmin` and is refused with `ERR_PENDING_WASTE_LOGS` while any waste log for the period still sits in `RECORDED` or `VERIFIED` status — the waste pipeline of §3.4 must fully settle first. `CLOSED` and `CANCELLED` are the terminal states; recall from §2.10 that the hall-suspension cascade moves only `SCHEDULED` periods to `CANCELLED`.

### 3.4. Food Waste and Sustainability Accounting

Waste is tracked per meal period by **waste logs**. A `KitchenLead` records a log against a period, supplying a `category` of `PRE_CONSUMER`, `POST_CONSUMER`, or `SPOILAGE`, a `disposition` of `LANDFILL`, `COMPOST`, or `DONATION`, and a `weight_kg` strictly greater than 0. The log is bound to its period through its `meal_period_id`. Recording is accepted only while the parent period is `IN_SERVICE` or `RECONCILED`; once the period is `CLOSED` (or was `CANCELLED`), the window has shut and recording is refused with `ERR_WASTE_WINDOW_CLOSED`, while a period still in `SCHEDULED` or `FORECAST_LOCKED` refuses recording with `ERR_INVALID_STATE`. The recorder's `X-User-ID` is stamped onto the log as `recorded_by_user_id`, and the log starts `RECORDED` with `verified_by_user_id` null.

Verification (`RECORDED` → `VERIFIED`) is a `HallManager` duty with a hard segregation-of-duties rule: the verifier's `X-User-ID` must differ from the log's `recorded_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — even though `HallManager` is otherwise the correct role. Verification also requires the parent period to be `IN_SERVICE` or `RECONCILED`, else `ERR_INVALID_STATE`. A successful verify stamps `verified_by_user_id`. A failed verification cycles the log back (`VERIFIED` → `RECORDED`) via rejection, clearing `verified_by_user_id` to null and accepting an optional `reason`; because only `POSTED` rows feed the period aggregates and rejection never changes the posted set, rejection deliberately performs no recomputation.

Posting (`VERIFIED` → `POSTED`) is the monetizable step: it requires the parent period to be `RECONCILED`, else `ERR_INVALID_STATE`, and it recomputes the period's sustainability aggregates. The period's `posted_waste_kg` becomes the sum of `weight_kg` over all its `POSTED` logs, and `landfill_waste_kg` the same sum restricted to logs whose disposition is `LANDFILL`; both are carried at 2 decimal places. The `diversion_rate` is the composted-plus-donated kilograms divided by the total posted kilograms, carried to 4 decimal places, and is null when no waste is posted at all. The `sustainability_alert` flag is then re-evaluated against the 0.15 kilograms-per-cover threshold: it is set true when `actual_covers` is greater than 0 and the landfill kilograms per actual cover is strictly greater than 0.15 — a ratio of exactly 0.15 does not raise the alert — and it is false whenever `actual_covers` is 0. Posting increments the parent period's `version` by 1 in addition to the log's own increment, and `POSTED` is terminal for the log.

### 3.5. Labor Scheduling and Weekly Overtime

A **labor shift** plans one worker's block. A `HallManager` creates a shift with the hall (`dining_hall_id`), a `role` of `COOK`, `SERVER`, `CASHIER`, or `DISHWASHER`, a `shift_date`, a `start_minute` between 0 and 1,439 inclusive measured from midnight, an `end_minute` that must be strictly greater than `start_minute` and at most 1,440 (the shift occupies the half-open interval from start to end), and an `hourly_rate_cents` strictly greater than 0. The `staff_ref` — an opaque staff identifier — is optional at creation: a shift created without it starts `PLANNED`, while one created with it starts `ASSIGNED` immediately, and in the latter case the assignment checks below run at creation time.

Assigning a staff member to a `PLANNED` shift (or creating an `ASSIGNED` shift outright) runs two guards against the staff member's existing commitments. The **overlap guard**: no other shift of the same `staff_ref` in `ASSIGNED`, `CONFIRMED`, or `COMPLETED` status may have a half-open interval on the same `shift_date` that intersects the new interval — because the intervals are half-open, one shift ending exactly when another begins is not an overlap — and a violation is refused with `ERR_SHIFT_OVERLAP`. The **rest guard**: for every prior shift of the same `staff_ref` in `ASSIGNED`, `CONFIRMED`, or `COMPLETED` status that ends before the new shift starts, the gap between the prior shift's end and the new shift's start — computed on an absolute minute timeline where a minute's absolute position is the day offset times 1,440 plus the minute-of-day — must be at least 480 minutes, with a gap of exactly 480 minutes allowed; a tighter turn-around is refused with `ERR_REST_PERIOD_VIOLATION`.

Confirmation (`ASSIGNED` → `CONFIRMED`) requires the hall to be `ACTIVE`, else `ERR_HALL_SUSPENDED`. A confirmed shift resolves in one of two terminal ways: completion or no-show. Marking no-show (`CONFIRMED` → `NO_SHOW`) simply closes the record. Completion (`CONFIRMED` → `COMPLETED`) takes a `worked_minutes` input — at least 1 and at most the scheduled length (end minute minus start minute) plus a 60-minute grace, otherwise `ERR_VALIDATION` — and triggers the weekly overtime allocation.

The overtime allocation re-scores the just-completed shift against its whole work week. The week is the ISO week (Monday 00:00 through Sunday 24:00) containing the shift's `shift_date`, and the candidate set is every shift of the same `staff_ref` in the same ISO week with status `COMPLETED`, including the shift just completed. The set is walked in a pinned order — by `shift_date` ascending, then `start_minute` ascending, then `created_at` ascending — with a running total of minutes worked. For each shift in that walk, its regular portion is the smaller of its `worked_minutes` and the room remaining under the 2,400-minute weekly threshold (forty hours) after the running total, floored at zero; its overtime portion is whatever `worked_minutes` remain beyond the regular portion; then its minutes accumulate into the running total. A shift that brings the running total to exactly 2,400 minutes contributes zero overtime — only minutes strictly beyond the threshold are overtime. The shift's pay fields then materialize: `regular_pay_cents` is `regular_minutes` times `hourly_rate_cents` divided by 60, rounded half-up to whole cents, and `overtime_pay_cents` is `overtime_minutes` times `hourly_rate_cents` times 1.5 divided by 60, rounded half-up to whole cents. Until completion, all four computed fields — `regular_minutes`, `overtime_minutes`, `regular_pay_cents`, `overtime_pay_cents` — rest at 0, and `worked_minutes` is null. Because completion order need not match chronological order, only the just-completed shift is re-scored; earlier `COMPLETED` shifts keep the split frozen at their own completion time and are never retroactively adjusted.

### 3.6. The Special-Diet Accommodation Review Loop

Students with medical or religious dietary needs are handled through **accommodation requests**. A `HallManager` files a request naming the hall (`dining_hall_id`), an opaque `student_ref` such as a campus ID, an `allergen_exclusions` array of allergen values that must not appear in suitable menu items, and a `dietary_requirement` of `VEGAN`, `VEGETARIAN`, `HALAL`, `KOSHER`, `GLUTEN_FREE`, or `OTHER`. The request starts `SUBMITTED` with an empty `review_notes`.

A `Dietitian` drives the review loop. Starting review moves `SUBMITTED` → `NUTRITION_REVIEW`. When more information is needed, a request-info call — which must carry a `review_notes` string, failing which `ERR_VALIDATION` — cycles the request back from `NUTRITION_REVIEW` to `SUBMITTED`, storing that note as the request's latest `review_notes`. Approving (`NUTRITION_REVIEW` → `APPROVED`) is gated on a suitable-menu check: at least one recipe at the request's hall must be `ACTIVE`, have `allergen_tags` disjoint from the request's `allergen_exclusions`, and satisfy the dietary requirement — where a requirement of `OTHER` imposes no flag constraint, and any other requirement must appear in the recipe's `dietary_flags`. If no such recipe exists, approval is refused with `ERR_NO_SUITABLE_MENU`. Finally, a `KitchenLead` confirms the production plan, moving `APPROVED` → `ACTIVE`. A request may be cancelled from any non-terminal state — `SUBMITTED`, `NUTRITION_REVIEW`, `APPROVED`, or `ACTIVE` — by a `HallManager` or a `Dietitian`, landing in the terminal `CANCELLED` state.

### 3.7. Health Inspections, Scoring, and Corrective Actions

A `HealthInspector` files an **inspection report** against a hall, supplying the `dining_hall_id`, the `inspection_date`, and a `violations` array whose elements each carry a violation `code` string and a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`. The filer's `X-User-ID` is stamped as `inspector_user_id`. The report is born `DRAFT`, with `score` and `outcome` null.

Submission (`DRAFT` → `SUBMITTED`) is where scoring happens. Each violation contributes demerits — `CRITICAL` costs 25, `MAJOR` costs 10, `MINOR` costs 3 — and the report's `score` is 100 minus the total demerits, floored at 0. The `outcome` follows: any report containing at least one `CRITICAL` violation is a `FAIL` regardless of score; otherwise a `score` of 70 or better is a `PASS` (exactly 70 passes); otherwise a `score` of 40 through 69 is `CONDITIONAL`; anything below 40 is a `FAIL`. Submission also cascade-creates one **corrective action** per violation, each bound to the report through its `inspection_report_id`, copying the violation's severity and code, setting each action's `due_date` relative to the inspection date — 7 days out for `CRITICAL`, 14 days for `MAJOR`, 30 days for `MINOR` — and starting each action `OPEN` with `resolved_by_user_id` and `verified_by_user_id` null. And submission carries the system's sharpest cascade: when the computed `outcome` is `FAIL`, the parent hall transitions from `ACTIVE` to `SUSPENDED`, whose own side effect (§2.10) cancels every `SCHEDULED` meal period at the hall — a transitive cascade three levels deep, from report to hall to periods.

From `SUBMITTED`, a `HallManager` acknowledges the report (`SUBMITTED` → `ACKNOWLEDGED`), and a `HealthInspector` eventually closes it (`ACKNOWLEDGED` → `CLOSED`), but only when every corrective action belonging to the report has reached `VERIFIED` — otherwise `ERR_INSPECTION_INCOMPLETE`. While a report is `SUBMITTED` or `ACKNOWLEDGED`, the inspector may also add an extra corrective action directly, supplying `violation_code`, `severity`, and `due_date`; such an action starts `OPEN`.

Corrective actions have their own loop. A `HallManager` resolves an action from either `OPEN` or `OVERDUE` (both land in `RESOLVED`), provided the parent report is `SUBMITTED` or `ACKNOWLEDGED` — otherwise `ERR_INVALID_STATE` — with the resolver's `X-User-ID` stamped as `resolved_by_user_id`. A `HealthInspector` then verifies (`RESOLVED` → `VERIFIED`), which requires the parent report to be `ACKNOWLEDGED`, else `ERR_INVALID_STATE`, and stamps `verified_by_user_id`. When verification fails, the inspector reopens the action (`RESOLVED` → `OPEN`), clearing `resolved_by_user_id` to null; and if the reopened action's severity is `CRITICAL` while the report's hall is currently `ACTIVE`, the hall is suspended on the spot — again cascading to cancel the hall's `SCHEDULED` meal periods. Independently of the human workflow, the clock sweep of §2.4 moves `OPEN` actions whose `due_date` has passed to `OVERDUE`. `VERIFIED` is terminal.

### 3.8. Department Catering: Quoting, Budgets, and Order Settlement

Campus departments order catering against a semester budget. A `DiningAdmin` creates a **department** with a `name`, a `department_code` that must be unique across all departments (a duplicate is rejected with `ERR_VALIDATION`), and a `semester_budget_cents` of zero or more. Four computed buckets track the money: `reserved_cents`, `committed_cents`, `spent_cents`, and `available_cents` all start at 0 except `available_cents`, which starts equal to the semester budget.

A `DepartmentUser` creates a **catering order** — and only for their own department, with the body's `department_id` required to equal their `X-User-ID` (§2.1). The order names the hall (`dining_hall_id`), an `event_date`, and a `time_slot` of `BREAKFAST`, `LUNCH`, or `DINNER`; slots start at fixed hours — breakfast at 07:00, lunch at 11:00, dinner at 17:00 — and the slot start drives both lead-time enforcement and the kitchen-capacity pool. The `guaranteed_covers` headcount must be greater than 0. The `menu_lines` array carries one element per dish with its `recipe_id` and `portions` (strictly greater than 0), and every named recipe must be `ACTIVE` at the order's hall, otherwise `ERR_VALIDATION`. The `dietary_plates` count — the number of special-diet plates in the order — is optional, defaults to 0, and cannot be negative. An optional `revised_from_id` lets the order point back at a `REJECTED` order it revises; a `revised_from_id` naming an order in any other status is rejected with `ERR_VALIDATION`. The order is born with `approval_status` `DRAFT` and `fulfillment_status` `NONE` — two parallel status dimensions — with `final_total_cents` null and `cancellation_fee_cents` 0.

Creation freezes the quote. The food cost is the exact sum over the menu lines of each line's portions times its recipe's `unit_cost_cents`. A markup rate is selected by the guaranteed headcount: 1.40 when fewer than 50 covers, 1.25 when at least 50 but fewer than 200, and 1.15 at 200 or more — so a party of exactly 50 takes the 1.25 rate and a party of exactly 200 the 1.15 rate. The marked-up food cost is the food cost times the markup rate, rounded half-up to whole cents, and that is the calculation's only rounding step. The dietary premium is `dietary_plates` times 300 cents per plate. The service fee is a 7,500-cent base plus 25 cents per guaranteed cover. The `quoted_total_cents` is the marked-up food cost plus the dietary premium plus the service fee — except that if that sum falls below the 50,000-cent minimum order, the quote is raised to 50,000 cents; the floor applies last. The frozen quote is reused verbatim if the order is later resubmitted.

Submitting an order (from either `DRAFT` or `REJECTED` to `SUBMITTED`) runs the submission gauntlet in pipeline order: the hall must be `ACTIVE` (else `ERR_HALL_SUSPENDED`); the event's slot start must be at least 48 hours after the current logical time, with exactly 48 hours allowed (else `ERR_LEAD_TIME_VIOLATION`); and the department's `available_cents` must cover the `quoted_total_cents`, with exact equality allowed (else `ERR_INSUFFICIENT_BUDGET`, HTTP 402). On success the quoted total moves into the department's `reserved_cents`, both the department's and the order's `version` increment.

Approval (`SUBMITTED` → `APPROVED`) is a `HallManager` decision under three guards beyond the OCC check of §2.8 — `expected_department_version` must match the department's current `version`, else `ERR_STALE_VERSION`, and this staleness check runs after the from-state check. No `CRITICAL` corrective action may be `OPEN` or `OVERDUE` on any inspection report at the order's hall (else `ERR_CRITICAL_VIOLATION_OPEN`). And the kitchen-capacity pool must hold: the sum of `guaranteed_covers` over all `APPROVED` orders at the same hall, on the same `event_date`, in the same `time_slot`, plus this order's own `guaranteed_covers`, must not exceed the hall's `catering_kitchen_capacity`, with equality allowed (else `ERR_CATERING_CAPACITY_EXCEEDED`). Approval moves the quoted total out of `reserved_cents` and into `committed_cents`, incrementing both versions. Rejection (`SUBMITTED` → `REJECTED`) accepts an optional `reason` and is the compensating action for submission: the quoted total comes back out of `reserved_cents`, and both versions increment.

Fulfillment runs on the second status dimension and only for `APPROVED` orders: a `HallManager` schedules (`NONE` → `SCHEDULED`), a `KitchenLead` marks fulfilled (`SCHEDULED` → `FULFILLED`), and a `HallManager` invoices (`FULFILLED` → `INVOICED`) by supplying the actual `final_total_cents`. The final total must land within a tolerance band around the frozen quote — at least the quoted total times 0.80 and at most the quoted total times 1.20, each bound computed by rounding half-up, with both bounds inclusive — otherwise `ERR_VALIDATION`. Payment (`INVOICED` → `PAID`) is a `DiningAdmin` act that settles the ledger: the quoted total leaves `committed_cents` and the final total lands in `spent_cents`, with both versions incrementing. `PAID` is terminal.

Cancellation behaves differently by stage, and always lands in the terminal `approval_status` `CANCELLED` (with `fulfillment_status` `CANCELLED` whenever fulfillment had progressed past `NONE`). Cancelling from `DRAFT` is free — `cancellation_fee_cents` stays 0 and no budget bucket moves. Cancelling from `SUBMITTED` is likewise free but releases the reservation: `reserved_cents` drops by the quoted total and the department's version increments. Cancelling an `APPROVED` order whose fulfillment is `NONE` or `SCHEDULED` charges a cancellation fee: the fee is the quoted total times a fee rate, rounded half-up to whole cents, where the rate is 1,000 basis points (ten percent) when the event's slot start is at least 72 hours after the current logical time — exactly 72 hours qualifies — and 2,500 basis points (twenty-five percent) otherwise. The committed bucket releases the quoted total, the fee lands in `spent_cents`, and both versions increment. Cancellation is available to the owning `DepartmentUser` and to a `HallManager`.

Across all of these transitions the department's four buckets obey a single conservation law: `reserved_cents` is the sum of `quoted_total_cents` over the department's orders in `SUBMITTED` approval; `committed_cents` is the same sum over orders `APPROVED` with fulfillment in `NONE`, `SCHEDULED`, `FULFILLED`, or `INVOICED`; `spent_cents` is the sum of `final_total_cents` over `PAID` orders plus the cancellation fees charged on cancelled orders; and `available_cents` is what remains of the `semester_budget_cents` after the other three buckets. At every instant, the four buckets sum exactly back to the semester budget — the submit/reject pair and the approve/cancel-with-fee pair each conserve the total exactly.

### 3.9. Vendor Commission Settlement

At month's end the vendor settles with the university through a **commission statement**. A `DiningAdmin` generates a statement for a contract by naming the `period_month` in `YYYY-MM` form; the statement is bound to the contract through its `vendor_contract_id`, the contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`), and at most one statement may exist per contract and month (else `ERR_DUPLICATE_STATEMENT`). The statement is born `PROVISIONAL`, all of its monetary fields are computed under the provisional variant described below, and the resulting total is pinned as `provisional_total_due_cents` — a figure that is immutable thereafter, surviving finalization, dispute, and recompute unchanged. The `finalized_at` timestamp starts null.

The settlement math aggregates three revenue lines over the contract's hall for the named month. **Board revenue**: the included meal periods are those at the contract's hall whose `service_date` falls inside the period month — under the provisional variant, periods in `RECONCILED` or `CLOSED` status; under the final variant, `CLOSED` periods only. Each included period contributes its `actual_board_swipes` times the contract's `board_rate_per_cover_cents`, and `board_revenue_cents` is the sum. **Retail commission**: every `RETAIL_SALE` swipe event of every included period contributes its `amount_cents` times `retail_commission_bps` divided by 10,000, rounded half-up to whole cents *per event*, and `retail_commission_cents` is the sum of those per-event rounded values — the rounding order is pinned: round each event first, then sum; summing first and rounding once is a different, forbidden result. **Catering commission**: the included orders are those at the hall whose `event_date` falls inside the period month — under the provisional variant, orders with `fulfillment_status` `SCHEDULED`, `FULFILLED`, `INVOICED`, or `PAID`, each contributing on its `quoted_total_cents` base; under the final variant, `PAID` orders only, each on its `final_total_cents` base. Each included order contributes its base times `catering_commission_bps` divided by 10,000, rounded half-up per order, and `catering_commission_cents` is the sum of the per-order rounded values. The **guarantee top-up** is the provisional/final split's sharpest edge: `guarantee_top_up_cents` is always 0 in the provisional variant, and in the final variant it is the contract's `minimum_monthly_guarantee_cents` minus the sum of the retail and catering commissions, floored at zero. The `total_due_to_university_cents` is the retail commission plus the catering commission plus the guarantee top-up.

Finalization (`PROVISIONAL` → `FINALIZED`) is a `ContractManager` act that again requires the contract to be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`, with the statement's from-state check evaluated before this contract re-check); it recomputes every monetary field under the final variant — stricter period inclusion, paid-only catering on final totals, and the guarantee top-up — and stamps `finalized_at` with the logical clock. A `DiningAdmin` may dispute a `FINALIZED` statement (`FINALIZED` → `DISPUTED`), optionally supplying a `reason`. Dispute resolution is regeneration: a `DiningAdmin` recomputes a `DISPUTED` statement, returning it to `PROVISIONAL`, recomputing all monetary fields under the provisional variant, clearing `finalized_at` to null, and — as always — leaving `provisional_total_due_cents` untouched. The statement has no terminal state; the dispute-recompute cycle may repeat.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. Request bodies, computed outputs, and side effects are defined by the workflows of §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dining-halls` | Create a dining hall | DiningAdmin |
| GET | `/dining-halls` | List dining halls | Any |
| GET | `/dining-halls/{id}` | Get one dining hall | Any |
| POST | `/dining-halls/{id}/suspend` | Suspend a hall; cancels its SCHEDULED meal periods | DiningAdmin |
| POST | `/dining-halls/{id}/reactivate` | Reactivate a suspended hall; blocked by open CRITICAL corrective actions | DiningAdmin |
| POST | `/vendor-contracts` | Create a vendor contract in NEGOTIATION | DiningAdmin |
| GET | `/vendor-contracts` | List vendor contracts | Any |
| GET | `/vendor-contracts/{id}` | Get one vendor contract | Any |
| POST | `/vendor-contracts/{id}/activate` | Activate a contract; at most one ACTIVE per hall | ContractManager |
| POST | `/vendor-contracts/{id}/terminate` | Terminate an ACTIVE contract | ContractManager |
| POST | `/menu-cycles` | Create a menu cycle in DRAFT | DiningAdmin |
| GET | `/menu-cycles` | List menu cycles | Any |
| GET | `/menu-cycles/{id}` | Get one menu cycle | Any |
| POST | `/menu-cycles/{id}/publish` | Publish a cycle; allergen-review gate plus half-open overlap check | DiningAdmin |
| POST | `/menu-cycles/{id}/archive` | Archive a DRAFT or PUBLISHED cycle | DiningAdmin |
| POST | `/recipes` | Create a recipe (ACTIVE; allergen_reviewed defaults false) | KitchenLead |
| GET | `/recipes` | List recipes | Any |
| GET | `/recipes/{id}` | Get one recipe | Any |
| PATCH | `/recipes/{id}` | Re-label or re-cost a recipe | KitchenLead |
| POST | `/recipes/{id}/suspend` | Suspend a recipe (allergen audit) | DiningAdmin |
| POST | `/recipes/{id}/reinstate` | Reinstate a suspended recipe; requires allergen review | DiningAdmin |
| POST | `/meal-periods` | Schedule a meal period; cycle must be PUBLISHED and cover the service date | HallManager |
| GET | `/meal-periods` | List meal periods | Any |
| GET | `/meal-periods/{id}` | Get one meal period (including `version` for OCC) | Any |
| POST | `/meal-periods/{id}/lock-forecast` | Lock the period's forecast; stores forecasted covers via the BASE rule | HallManager |
| POST | `/meal-periods/{id}/open-service` | Open service; requires hall ACTIVE | HallManager |
| POST | `/meal-periods/{id}/reconcile` | Reconcile actuals and forecast variance | HallManager |
| POST | `/meal-periods/{id}/close` | Close the period; requires no unposted waste | DiningAdmin |
| POST | `/meal-periods/{id}/swipes` | Bulk-ingest swipe/sale events; all-or-nothing; period must be IN_SERVICE | HallManager |
| GET | `/swipe-events` | List swipe events | Any |
| GET | `/swipe-events/{id}` | Get one swipe event | Any |
| POST | `/meal-periods/{id}/forecasts` | Create a forecast for one recipe on a SCHEDULED period; OCC-guarded; supersedes the pair's LOCKED forecast | KitchenLead |
| GET | `/production-forecasts` | List production forecasts | Any |
| GET | `/production-forecasts/{id}` | Get one production forecast | Any |
| POST | `/production-forecasts/{id}/lock` | Lock a DRAFT forecast; period must still be SCHEDULED | KitchenLead |
| POST | `/accommodation-requests` | File a special-diet accommodation request | HallManager |
| GET | `/accommodation-requests` | List accommodation requests | Any |
| GET | `/accommodation-requests/{id}` | Get one accommodation request | Any |
| POST | `/accommodation-requests/{id}/start-review` | Move a submitted request into nutrition review | Dietitian |
| POST | `/accommodation-requests/{id}/request-info` | Cycle a request back to submitted with dietitian notes | Dietitian |
| POST | `/accommodation-requests/{id}/approve` | Approve a request; suitable-menu safety gate | Dietitian |
| POST | `/accommodation-requests/{id}/activate` | Activate an approved request (kitchen confirms production plan) | KitchenLead |
| POST | `/accommodation-requests/{id}/cancel` | Cancel from any non-terminal state | HallManager, Dietitian |
| POST | `/labor-shifts` | Create a shift; staff_ref optional; overlap and rest checks run when present | HallManager |
| GET | `/labor-shifts` | List labor shifts | Any |
| GET | `/labor-shifts/{id}` | Get one labor shift | Any |
| POST | `/labor-shifts/{id}/assign` | Assign staff to a PLANNED shift with overlap and rest checks | HallManager |
| POST | `/labor-shifts/{id}/confirm` | Confirm an assigned shift; requires hall ACTIVE | HallManager |
| POST | `/labor-shifts/{id}/complete` | Complete a confirmed shift; runs weekly overtime allocation | HallManager |
| POST | `/labor-shifts/{id}/mark-no-show` | Mark a confirmed shift as no-show | HallManager |
| POST | `/meal-periods/{id}/waste-logs` | Record a waste log; period must be IN_SERVICE or RECONCILED | KitchenLead |
| GET | `/waste-logs` | List waste logs | Any |
| GET | `/waste-logs/{id}` | Get one waste log | Any |
| POST | `/waste-logs/{id}/verify` | Verify a recorded log; segregation of duties versus the recorder | HallManager |
| POST | `/waste-logs/{id}/post` | Post a verified log; recomputes period waste aggregates and the sustainability alert | HallManager |
| POST | `/waste-logs/{id}/reject` | Reject a verified log back to recorded; aggregates unchanged | HallManager |
| POST | `/inspection-reports` | File an inspection report in DRAFT | HealthInspector |
| GET | `/inspection-reports` | List inspection reports | Any |
| GET | `/inspection-reports/{id}` | Get one inspection report | Any |
| POST | `/inspection-reports/{id}/submit` | Submit a report; computes score and outcome, creates corrective actions, FAIL suspends the hall | HealthInspector |
| POST | `/inspection-reports/{id}/acknowledge` | Acknowledge a submitted report | HallManager |
| POST | `/inspection-reports/{id}/close` | Close an acknowledged report; all corrective actions must be VERIFIED | HealthInspector |
| POST | `/inspection-reports/{id}/corrective-actions` | Add an extra corrective action to a SUBMITTED or ACKNOWLEDGED report | HealthInspector |
| GET | `/corrective-actions` | List corrective actions | Any |
| GET | `/corrective-actions/{id}` | Get one corrective action | Any |
| POST | `/corrective-actions/{id}/resolve` | Resolve an OPEN or OVERDUE action | HallManager |
| POST | `/corrective-actions/{id}/verify` | Verify a resolved action; parent report must be ACKNOWLEDGED | HealthInspector |
| POST | `/corrective-actions/{id}/reopen` | Reopen a resolved action; CRITICAL reopen re-suspends the hall | HealthInspector |
| POST | `/departments` | Create a campus department with its semester budget | DiningAdmin |
| GET | `/departments/{id}` | Get one department including its computed budget ledger (DepartmentUser: own id only) | DiningAdmin, HallManager, ContractManager, DepartmentUser |
| POST | `/catering-orders` | Create a catering order in DRAFT/NONE; computes the frozen quote; DepartmentUser may only use their own department | DepartmentUser |
| GET | `/catering-orders` | List catering orders | Any |
| GET | `/catering-orders/{id}` | Get one catering order | Any |
| POST | `/catering-orders/{id}/submit` | Submit a DRAFT or REJECTED order; hall gate, 48-hour lead time, budget reservation | DepartmentUser |
| POST | `/catering-orders/{id}/approve` | Approve a submitted order; OCC on the department, critical-violation gate, slot capacity check | HallManager |
| POST | `/catering-orders/{id}/reject` | Reject a submitted order; releases the reservation | HallManager |
| POST | `/catering-orders/{id}/schedule` | Schedule an approved order | HallManager |
| POST | `/catering-orders/{id}/fulfill` | Mark a scheduled order fulfilled | KitchenLead |
| POST | `/catering-orders/{id}/invoice` | Invoice a fulfilled order; final total within 80–120 percent of quoted | HallManager |
| POST | `/catering-orders/{id}/pay` | Pay an invoiced order; settles committed into spent | DiningAdmin |
| POST | `/catering-orders/{id}/cancel` | Cancel; free from DRAFT/SUBMITTED, fee-based once APPROVED | DepartmentUser, HallManager |
| POST | `/vendor-contracts/{id}/commission-statements` | Generate the PROVISIONAL statement for a period month; contract must be ACTIVE; unique per contract and month | DiningAdmin |
| GET | `/commission-statements` | List commission statements | Any |
| GET | `/commission-statements/{id}` | Get one commission statement | Any |
| POST | `/commission-statements/{id}/finalize` | Finalize a provisional statement; recomputes under the final variant; contract must be ACTIVE | ContractManager |
| POST | `/commission-statements/{id}/dispute` | Dispute a finalized statement | DiningAdmin |
| POST | `/commission-statements/{id}/recompute` | Recompute a disputed statement back to provisional | DiningAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs the contract-expiry and corrective-action-overdue sweeps | DiningAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_HALL_SUSPENDED` | 409 |
| `ERR_CYCLE_OVERLAP` | 409 |
| `ERR_ALLERGEN_UNDECLARED` | 422 |
| `ERR_NO_SUITABLE_MENU` | 422 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_REST_PERIOD_VIOLATION` | 422 |
| `ERR_CATERING_CAPACITY_EXCEEDED` | 409 |
| `ERR_LEAD_TIME_VIOLATION` | 422 |
| `ERR_INSUFFICIENT_BUDGET` | 402 |
| `ERR_INSUFFICIENT_HISTORY` | 422 |
| `ERR_FORECAST_LOCKED_PERIOD` | 409 |
| `ERR_DUPLICATE_FORECAST` | 409 |
| `ERR_WASTE_WINDOW_CLOSED` | 422 |
| `ERR_PENDING_WASTE_LOGS` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CRITICAL_VIOLATION_OPEN` | 422 |
| `ERR_INSPECTION_INCOMPLETE` | 409 |
| `ERR_DUPLICATE_ACTIVE_CONTRACT` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_DUPLICATE_STATEMENT` | 409 |
| `ERR_INTERNAL` | 500 |

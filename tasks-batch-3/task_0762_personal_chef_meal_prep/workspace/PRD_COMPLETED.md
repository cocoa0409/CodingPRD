# Personal-Chef Meal-Prep API — Product Requirements Document

## 1. Introduction

The Personal-Chef Weekly Meal-Prep Service coordinates the entire arc of a household's in-home cooking arrangement: a client's dietary profile and plan, the weekly menu a chef designs against that plan, the grocery cost and markup that turn ingredients into a bill, the recurring in-home cook sessions, the labeled leftover containers those sessions produce, and the invoices that settle each week. The platform exists because this arrangement is full of moving parts that must reconcile precisely — a substituted ingredient must ripple into the week's grocery total, a skipped vacation week must credit the client's wallet and later reverse cleanly if the week resumes, and a completed cook must fan out into cooked meals, dated containers, and an issued invoice in one motion.

This document specifies the REST API that backs the service. It is written for the engineers who will implement the server, and it favors the business meaning of each rule over its mechanical shape. The domain is fundamentally a **ledger-reconciliation** problem layered over **temporal windowing**: money and credit must always tie out to their source events, while cook sessions, kitchen availability, and vacation windows are all gated by a server-controlled logical clock. Several calculations deliberately admit two legitimate-looking evaluation orders that produce different totals; the correct order is pinned throughout, and implementers should treat those pinnings as contractual rather than incidental.

Because the platform bills real money and handles allergen safety, the specification is strict about precision, about the order in which validations fire, and about which party is allowed to take which action. The sections that follow define the global contracts first, then walk the business workflows where the detailed rules live.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are present but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly three roles: `PlatformAdmin`, `Client`, and `Chef`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`. A `PlatformAdmin` is operational staff: they onboard clients and chefs, cancel clients, may report no-shows, and drive the logical clock.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`. Ownership checks on any resource that references a client compare the resource's owning-client foreign key to `X-User-ID`. A `Client` owns its own dietary plans, its weekly menus (and, through them, those menus' meals), and its invoices.
- When `X-User-Role` is `Chef`, `X-User-ID` is the `id` of the acting `Chef`. Ownership checks on any resource that references a chef compare the resource's owning-chef foreign key to `X-User-ID`. A `Chef` owns the menus they authored, the meals on those menus, and the cook sessions they staff.

For operations that mutate an ownership-scoped resource, if the entity-backed caller is not the owner of the target resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. Read (`GET`) endpoints are available to all three roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` supplied outside its permitted range is clamped to the nearest bound rather than rejected — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0 — while a non-integer or absent value simply falls back to its default (10 for `limit`, 0 for `offset`).

Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order.

Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of matching resources before pagination and `has_more` indicates whether items remain beyond the current page. Each list endpoint's documented filters are supplied as query parameters named for the referenced entity's foreign-key field — `client_id`, `chef_id`, `dietary_plan_id`, `weekly_menu_id`, or `menu_meal_id` as applicable to the endpoint — and an omitted filter parameter is simply not applied.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — `Client`, `Chef`, `DietaryPlan`, `WeeklyMenu`, `MenuMeal`, `CookSession`, `Container`, and `BillingInvoice` — carries a common set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at 1 on creation and increments by 1 on every mutation of the resource.

These four fields are present on all eight entity types. The `created_at` and `updated_at` stamps — and the envelope's `api_request_timestamp` of §2.2 — are read from the host system wall clock at the instant of the write, independently of the logical clock of §2.7, which governs only the temporal-rule stamps enumerated there (session start/end stamps, container prep and use-by dates, and the vacation-window checks). Whenever a derived or computed field on a resource is recomputed as a side effect of an operation — for example when a menu's frozen grocery total changes, when a client's wallet balance moves, or when a chef's strike count rises — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Monetary Precision and Rounding

All money in the system is expressed in whole integer cents; there are no fractional cents in any stored field or response body. Where a calculation multiplies a raw cost by a percentage or a fractional number of hours and the intermediate result is not a whole number, the value is rounded to the nearest whole cent using the **round half up** convention (a result whose fractional part is exactly one half rounds away from zero, upward). Each calculation below names its own rounding points explicitly; rounding is applied at those pinned points and nowhere else, because rounding early versus late can change a total.

### 2.6. Optimistic Concurrency on Dietary-Plan Creation

Creating a dietary plan for a client is guarded by optimistic concurrency control. The create request must carry `expected_client_version`, which is the `version` of the owning `Client` that the author last observed. Because a successful create supersedes the client's prior active plan and advances the client's `version`, the server compares `expected_client_version` against the client's current `version` before proceeding. If they do not match — meaning another writer has already advanced the client since the author last read it — the request is rejected with `ERR_STALE_CLIENT_VERSION` at HTTP status 412, and no plan is created. This prevents an author whose view of the client (and of which plan is currently active) is out of date from silently replacing a plan they never saw. No other endpoint takes a version field; dietary-plan creation is the only operation under OCC.

### 2.7. The Logical Clock and Temporal Windows

The server keeps a single logical clock that supplies "now" for every time-dependent rule — session start and completion stamps, container prep dates, and the vacation-window checks on menus. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it stays at that default; the server never falls back to wall-clock time. A `PlatformAdmin` may advance or rewind the clock by supplying a `to_iso8601` instant to the clock-setting capability. All temporal comparisons in this document — whether a service week has started, whether a session falls inside kitchen hours, what date a container was prepared — read this logical clock, never the host machine's time.

### 2.8. Cascading State Consistency

Several operations mutate more than one entity in a single motion, and those cascades are part of the contract, not an implementation detail. Completing a cook session drives a three-level cascade through the menu, its meals, the produced containers, and a new invoice (detailed in §3.7). Cancelling a client cascades into that client's live menus and, through them, into their non-terminal cook sessions, and reverses any still-live skip credit (§3.8). Each entity touched by a cascade undergoes a real state transition, and every such transition refreshes that entity's `updated_at` and increments its `version` per §2.4. When the specification says a parent transition "produces" or "issues" child resources, those children are created by the cascade itself and are never created through a direct client call.

### 2.9. Existence Checks and Validation Ordering

For any request, the server validates the existence of every resource id referenced in the path or body, checking them left to right in the order they appear and rejecting on the first missing one with the matching not-found error: `ERR_CLIENT_NOT_FOUND`, `ERR_CHEF_NOT_FOUND`, `ERR_DIETARY_PLAN_NOT_FOUND`, `ERR_WEEKLY_MENU_NOT_FOUND`, `ERR_MENU_MEAL_NOT_FOUND`, `ERR_COOK_SESSION_NOT_FOUND`, `ERR_CONTAINER_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` as appropriate to the entity type.

Across the system, validations fire in a fixed priority order so that failures surface deterministically. The order is: (1) the presence and well-formedness of the user-context headers (`ERR_MISSING_USER_CONTEXT`); (2) whether the declared role may invoke the operation at all (`ERR_FORBIDDEN_ROLE`); (3) whether an entity-backed caller owns the target resource (`ERR_NOT_RESOURCE_OWNER`); (4) existence of all referenced ids, left to right (the not-found family above); (5) the optimistic-concurrency check on dietary-plan creation (`ERR_STALE_CLIENT_VERSION`); (6) request-body well-formedness — required fields present, enum values in range, cents and quantities not negative, `scheduled_end` strictly after `scheduled_start`, `kitchen_close_hour` strictly above `kitchen_open_hour`, and a feedback `rating` within range — rejected with `ERR_VALIDATION`, except that an out-of-range feedback rating is rejected with `ERR_INVALID_RATING`; then (7) whether the target resource is in a legal state for the requested transition (the invalid-state family, described per workflow below). Cross-entity state dependencies, safety, temporal, and fiscal checks are evaluated after these, within the workflow that owns them. Wherever this ordering matters for a specific endpoint, it is restated in the relevant §3 workflow so that an earlier, higher-priority failure is never masked by a later check.

### 2.10. The Wallet-Credit Ledger

Each client carries a running wallet balance, `wallet_credit_cents`, that behaves as a reconciled ledger rather than a free-form field. Its value is always the sum of every credit the client has been granted — one grant of the client's `weekly_base_fee_cents` for each of the client's menus currently in a skipped state, plus one grant of the same `weekly_base_fee_cents` for each cook session recorded as a no-show — minus the total credit already consumed by paid invoices (the sum of `credit_applied_cents` across the client's paid invoices). The balance is floored at zero and is never negative. Every event that grants, reverses, or consumes credit — skipping a week, resuming a skipped week, reporting a no-show, cancelling a client with a live skip credit, or paying an invoice — moves this balance and is described with its direction in the workflows below.

## 3. Business Logic & Workflows

### 3.1. Onboarding Clients and Chefs

A `PlatformAdmin` brings both households and cooks onto the platform. Creating a client captures the household's identity and its commercial and kitchen parameters: a `full_name`, a contact `email`, the `household_size` (the number of people fed, which must be at least 1 and which drives the per-head surcharge on weekly billing), and a `billing_mode` of either `PER_WEEK` or `PER_MEAL`. The client also records the money parameters that later pricing reads: `weekly_base_fee_cents`, the flat weekly service fee (also the amount granted as credit when a week is skipped or a cook is a no-show), which cannot be negative; `per_meal_fee_cents`, the flat fee added per cooked meal under per-meal billing, which cannot be negative; and `weekly_grocery_budget_cents`, the ceiling that any of this client's menus' grocery cost may reach at approval, which cannot be negative. The kitchen itself is described by `available_equipment` — an optional array (defaulting to an empty array) drawn from `OVEN`, `STOVETOP`, `BLENDER`, `GRILL`, and `SOUS_VIDE` — and by an operating window of `kitchen_open_hour`, the earliest UTC hour (0 through 23) a session may start, and `kitchen_close_hour`, the latest UTC hour (0 through 24, and strictly greater than `kitchen_open_hour`) a session may end. A newly created client begins with `status` of `ACTIVE`, a `wallet_credit_cents` of 0, and a `version` of 1.

A chef is created with a `full_name`, a contact `email`, and an `hourly_rate_cents` labor rate (not negative) that feeds session payouts. A new chef starts with `status` `ACTIVE` and a `no_show_strikes` count of 0. As no-shows accumulate against a chef, that count rises; when it reaches the strike limit of three, the chef auto-transitions from `ACTIVE` to `SUSPENDED` and can no longer be scheduled or start sessions. There is no state other than `ACTIVE` and `SUSPENDED` for a chef.

Cancelling a client is a `PlatformAdmin` action that moves the client's `status` from `ACTIVE` to `CANCELLED` and cascades: every one of that client's menus whose status is `DRAFT`, `PROPOSED`, `APPROVED`, or `SKIPPED` is driven to `CANCELLED`, and for any such menu that was in the `SKIPPED` state, the skip credit previously granted is reversed out of the client's wallet balance (the client's `weekly_base_fee_cents` is subtracted). Each menu carried into `CANCELLED` by this cascade in turn drives its own non-terminal sessions to `CANCELLED`, as described in §3.8.

### 3.2. Dietary Plans and Supersession

A `Client` establishes the dietary rules the kitchen must respect by creating a dietary plan against their own client record, supplying the `client_id` of the owning client, the `restriction_tags` (any of `VEGAN`, `VEGETARIAN`, `GLUTEN_FREE`, `KETO`, `PALEO`, `OMNIVORE`), the `allergen_tags` the household must never be exposed to (any of `NUTS`, `DAIRY`, `SHELLFISH`, `EGGS`, `SOY`, `GLUTEN`), and a `daily_calorie_target` in kilocalories per day that must be greater than zero. A new plan begins with `status` `ACTIVE`.

A client may only have one active plan at a time. When a client creates a newer plan, the system supersedes the prior one: the previously `ACTIVE` plan for that client transitions to `SUPERSEDED`, and the new plan becomes the `ACTIVE` one. This supersession is the reason the create is under optimistic concurrency: as covered in §2.6, the request carries `expected_client_version`, and because a successful create advances the owning client's `version`, a create that still carries an earlier client version is rejected with `ERR_STALE_CLIENT_VERSION` at status 412. Menus that were approved against a plan keep the plan version they pinned even after that plan is later superseded — the pin is a snapshot, not a live reference.

### 3.3. Building the Weekly Menu: Meals, Ingredients, and Grocery Cost

A `Chef` drafts a weekly menu for a household by supplying the `client_id` the menu feeds, the `dietary_plan_id` the menu is built against, the `chef_id` of the authoring chef (who owns the menu), and the `week_start_date`, an ISO 8601 UTC instant marking the start of the service week. A new menu is created in `DRAFT` status with a `grocery_cost_cents` of 0.

Onto a `DRAFT` menu the chef adds meals (the server does not, however, gate meal creation on the menu's state — a meal may be added to a menu in any status, and the ownership check is the only authorization guard). Each meal names the owning `weekly_menu_id`, a `meal_name`, a `meal_slot` of `BREAKFAST`, `LUNCH`, or `DINNER`, and a `servings` count (at least 1) that determines how many portions a produced container will hold. A meal declares whether it is perishable through `is_perishable` (an optional boolean defaulting to true), which later sets the container's shelf life. It may declare `required_equipment` (an optional array defaulting to empty, drawn from the same equipment enum as the kitchen) that the menu will need to have satisfied by the client's kitchen at approval time. Finally, the meal carries its `ingredients`: an array of objects, each with a `name`, a `quantity`, a `unit`, a `unit_cost_cents`, an `allergen_tags` list, and a `status`. The `ingredients` array must contain at least one object — an empty or absent array is rejected with `ERR_VALIDATION` — and each object's per-ingredient `allergen_tags` is optional, defaulting to an empty list when omitted. Ingredient statuses are `INCLUDED`, `ADDED`, or `SUBSTITUTED_OUT`, and ingredients supplied at meal creation start as `INCLUDED`. A newly added meal begins in `PLANNED` status with a null `client_rating` (it cannot be rated until it is cooked).

The cost of a meal, `meal_grocery_cost_cents`, is the sum, over just those of its ingredients whose status is `INCLUDED` or `ADDED`, of each ingredient's `quantity` multiplied by its `unit_cost_cents`; ingredients marked `SUBSTITUTED_OUT` are excluded from the sum. Each `quantity` times `unit_cost_cents` product is an exact integer amount of cents. This meal cost is computed when the meal is created and recomputed whenever an ingredient is substituted. The menu's own `grocery_cost_cents` is the sum of `meal_grocery_cost_cents` across the menu's meals whose status is `PLANNED` or `COOKED` — a `CANCELLED` meal contributes nothing. The menu total is recomputed each time a meal is added and each time an ingredient on one of its meals is substituted, and (as covered below) it is recomputed once more and frozen at approval.

### 3.4. Proposing, Rejecting, and Approving a Menu — and the Revision Loop

Once a menu has meals on it, the authoring chef proposes it to the household, advancing the menu from `DRAFT` to `PROPOSED`. A propose attempted on a menu with zero meals is rejected with `ERR_MENU_HAS_NO_MEALS`.

The client reviewing a `PROPOSED` menu has two moves. Rejecting it returns the menu from `PROPOSED` back to `DRAFT`, handing it to the chef for revision; this back-edge is intentional, so a menu can loop `DRAFT` → `PROPOSED` → `DRAFT` → `PROPOSED` as many times as needed before the household is satisfied. Approving it advances the menu from `PROPOSED` to `APPROVED`, but only after four gates all pass, evaluated after the base state check that the menu is actually `PROPOSED`:

- The `DietaryPlan` referenced by the menu's `dietary_plan_id` must currently be in `ACTIVE` status; if it has been superseded, approval is rejected with `ERR_DIETARY_PLAN_NOT_ACTIVE`.
- No active ingredient on any of the menu's meals may carry an allergen that appears in the client's dietary-plan `allergen_tags`; a conflict is rejected with `ERR_ALLERGEN_CONFLICT`.
- Every meal's `required_equipment` must be a subset of the client's `available_equipment`; if any required piece is missing from the kitchen, approval is rejected with `ERR_EQUIPMENT_UNAVAILABLE`.
- The menu's `grocery_cost_cents` must be no greater than the client's `weekly_grocery_budget_cents`; if it exceeds the budget, approval is rejected with `ERR_GROCERY_BUDGET_EXCEEDED`.

When all four gates pass, approval freezes the commercial snapshot on the menu. The `grocery_cost_cents` is recomputed one final time and frozen. The menu records `pinned_plan_version` equal to the referenced dietary plan's current `version` (it is null on any menu that has not yet been approved). It records `billing_mode_snapshot` equal to the client's `billing_mode` at this moment, either `PER_WEEK` or `PER_MEAL`. And, for a `PER_WEEK` client only, it records `markup_pct_snapshot` — the grocery markup tier percent selected from the frozen grocery cost, one of 15, 12, or 10 (see §3.9 for how the tier is chosen); for a `PER_MEAL` client this snapshot is null. A menu's `billed_amount_cents` remains null through approval and is only populated later, when the menu reaches `COOKED`.

### 3.5. Substitutions and Feedback

During revision, the authoring chef may substitute one ingredient for another on a meal. The request names the `target_ingredient_name` to swap out and describes the replacement with `replacement_name`, `replacement_quantity`, `replacement_unit`, `replacement_unit_cost_cents`, and an optional `replacement_allergen_tags` list. The matching ingredient currently in `INCLUDED` or `ADDED` status whose name equals `target_ingredient_name` is marked `SUBSTITUTED_OUT`, and the replacement is appended to the ingredient list with status `ADDED`. Substitution is not gated by the menu's state — the server performs it regardless of whether the menu is `DRAFT`, `PROPOSED`, `APPROVED`, or beyond — and if no active ingredient matches `target_ingredient_name`, nothing is marked out yet the replacement is still appended as `ADDED` and no error is raised. The optional `replacement_allergen_tags` defaults to an empty list when omitted. Both the meal's `meal_grocery_cost_cents` and the parent menu's `grocery_cost_cents` are then recomputed. Because a substitution can introduce a new allergen, the same allergen-safety rule that guards approval also guards substitution: if the replacement (or any remaining active ingredient) would carry an allergen listed in the client's dietary-plan `allergen_tags`, the substitution is rejected with `ERR_ALLERGEN_CONFLICT`. The grocery-cost figure is a conserved quantity: substituting an ingredient and then reverse-substituting back leaves the menu total equal to the sum of the active line items, because the swapped-out ingredient no longer contributes and the added one does.

After a meal has been cooked, the client may leave feedback, supplying a `rating` and an optional `comment`. The rating populates the meal's `client_rating` and must be an integer from 1 through 5; a rating outside that range is rejected with `ERR_INVALID_RATING`. Feedback attempted on a meal that has not yet reached `COOKED` is rejected with `ERR_MEAL_NOT_COOKED`.

### 3.6. Scheduling In-Home Cook Sessions

A `Chef` schedules an in-home cook by supplying the `weekly_menu_id` to be cooked, the `chef_id` who will staff it, a `scheduled_start`, and a `scheduled_end` — both ISO 8601 UTC instants, with the end strictly after the start (a non-positive interval is a body-validation failure, `ERR_VALIDATION`). A new session is created in `SCHEDULED` status, and its `provisional_payout_cents` is fixed at this moment: it is the scheduled duration in hours — the difference between `scheduled_end` and `scheduled_start`, taken in total seconds and divided by 3600, which may be fractional — multiplied by the chef's `hourly_rate_cents`, rounded half up to whole cents.

Scheduling is subject to several checks. The assigned chef must be `ACTIVE`; a suspended chef cannot be scheduled and the attempt is rejected with `ERR_CHEF_SUSPENDED`. Beyond that, three temporal constraints apply to the proposed half-open interval running from `scheduled_start` up to but not including `scheduled_end`:

- **Chef separation.** The new interval must not overlap any other non-terminal session of the same chef, and it must additionally be separated from every such session by at least the chef buffer of 60 minutes. Exact adjacency — a gap of precisely 60 minutes — is permitted; anything closer, including any overlap, is rejected with `ERR_CHEF_SCHEDULE_CONFLICT`. Non-terminal here means a session in `SCHEDULED` or `IN_PROGRESS`; sessions that are `COMPLETED`, `NO_SHOW`, or `CANCELLED` are ignored.
- **Kitchen occupancy.** The new interval must not overlap any other non-terminal session at the same client's kitchen. Unlike the chef rule, no buffer is required here: two sessions that merely touch back-to-back, with a gap of zero, are allowed; only a genuine overlap is rejected, with `ERR_CLIENT_KITCHEN_DOUBLE_BOOKED`.
- **Kitchen hours.** The UTC hour of `scheduled_start` must be at or after the client's `kitchen_open_hour`, and the UTC hour of `scheduled_end` must be at or before the client's `kitchen_close_hour`. A session that begins before the kitchen opens or ends after it closes is rejected with `ERR_OUTSIDE_KITCHEN_HOURS`.

### 3.7. Running the Cook: Start, Complete, and the Production Cascade

The staffing chef starts a scheduled session, moving it from `SCHEDULED` to `IN_PROGRESS`. Two conditions gate the start: the parent menu must be in `APPROVED` status — starting against a menu that is not approved is rejected with `ERR_MENU_NOT_APPROVED` — and the chef must be `ACTIVE`, else `ERR_CHEF_SUSPENDED`. On start, the session's `actual_start` is stamped with the current logical clock; it is null until then.

Completing an in-progress session moves it from `IN_PROGRESS` to `COMPLETED` and stamps `actual_end` with the logical clock. The session's `final_payout_cents` is then set using the same payout formula as the provisional figure but over the actual worked interval: the actual duration in hours — the difference between `actual_end` and `actual_start` in total seconds divided by 3600 — multiplied by the chef's `hourly_rate_cents`, rounded half up to whole cents. This final figure is null until completion and will differ from the provisional one whenever the cook ran shorter or longer than scheduled.

Completion drives a three-level production cascade off the parent menu. The menu advances from `APPROVED` to `COOKED`. Every one of the menu's meals still in `PLANNED` advances to `COOKED`. For each meal that becomes `COOKED`, a container is synthesized to hold its leftovers: the container records the `menu_meal_id` it portions, a `label_prep_date` equal to the logical clock at the moment the session completed, a `portion_count` copied from that meal's `servings`, and a `label_use_by_date` derived from the prep date — the prep date plus 3 days when the meal is perishable, or plus 5 days when it is not. Both `label_prep_date` and `label_use_by_date` are stored as full ISO 8601 UTC timestamps with three fractional digits (the logical-clock instant, and that instant plus the shelf-life days), not calendar-date-only strings. The container also carries a human-readable `label_text` combining the meal name, the prep date, and the use-by date, formatted exactly as `{meal_name} — prep {label_prep_date} — use by {label_use_by_date}`, and its `status` is always `FILLED` (a container is a produced artifact with no other state). Containers are only ever produced by this cascade, never created directly.

The same completion issues the week's bill. A billing invoice is synthesized in `ISSUED` status, recording the `client_id` being billed, the `weekly_menu_id` billed, a `billing_mode` copied from the menu's `billing_mode_snapshot`, and a `gross_amount_cents` computed as described in §3.9. At issuance the invoice's `credit_applied_cents` is 0 and its `net_amount_cents` is null; both are populated only when the invoice is later paid (§3.9). The menu's own `billed_amount_cents` is then set equal to that invoice's `gross_amount_cents`. Like containers, invoices are only produced by this cascade and are never created directly.

### 3.8. Vacations, No-Shows, and Cancellation — the Credit Ledger in Motion

A household on vacation can skip an approved week. Skipping moves the menu from `APPROVED` to `SKIPPED` and grants a credit: the client's `weekly_base_fee_cents` is added to their `wallet_credit_cents`. Resuming a skipped week moves the menu from `SKIPPED` back to `APPROVED` and compensates exactly: the same `weekly_base_fee_cents` that the skip added is subtracted back out of the wallet. Both skip and resume are only permitted while the logical clock is strictly before the menu's `week_start_date`; once the service week has begun, either attempt is rejected with `ERR_WEEK_ALREADY_STARTED`.

A no-show is reported against a scheduled session when the chef fails to appear; either the household or a `PlatformAdmin` may report it. Reporting moves the session from `SCHEDULED` to `NO_SHOW` and produces two divergent side effects with no menu progression: the client is compensated by adding the client's `weekly_base_fee_cents` to their `wallet_credit_cents`, and the chef's `no_show_strikes` is incremented by one. If that increment brings the chef's strike count to the limit of three, the chef transitions from `ACTIVE` to `SUSPENDED`.

The scheduled state of a cook session therefore forks three ways: forward into `IN_PROGRESS` and eventually `COMPLETED` on the productive path (§3.7); sideways into `NO_SHOW` with client credit and a chef strike; or into `CANCELLED` when the parent menu is cancelled. On that third branch, when a menu is cancelled its non-terminal sessions are driven to `CANCELLED`, the provisional payout is no longer owed, and the chef's schedule slot and the kitchen slot are freed. This is the cascade referenced in §3.1: cancelling a client cancels the client's live menus, each cancelled menu cancels its non-terminal sessions, and any still-live skip credit is reversed from the wallet so the ledger ties back out. A menu carried to `CANCELLED` also carries its `PLANNED` meals to `CANCELLED`.

### 3.9. Issuing the Invoice and Settling Payment

The gross amount on the issued invoice depends on which billing mode the menu snapshotted at approval, and the two modes compute genuinely different totals over the same cooked menu.

Under **`PER_WEEK`** billing, the gross is the sum of three parts. First, a grocery markup: a tier percent is selected from the menu's frozen `grocery_cost_cents` — 15 percent when the frozen grocery cost is below 15000 cents, 12 percent when it is at least 15000 but below 30000 cents, and 10 percent when it is 30000 cents or more (the boundaries are inclusive at the lower tier's exit, so a grocery cost of exactly 15000 selects 12 percent while 14999 selects 15 percent, and exactly 30000 selects 10 percent). This chosen percent is the value stored in `markup_pct_snapshot`. The grocery markup itself is the frozen grocery cost multiplied by that tier percent, divided by 100, rounded half up to whole cents. Second, a household surcharge: for each household member above the first two, 500 cents is charged — that is, the greater of zero and the household size minus two, multiplied by 500 cents. Third, the flat `weekly_base_fee_cents`. The gross amount is the sum of the base fee, the grocery markup, and the household surcharge.

Under **`PER_MEAL`** billing, the gross is built meal by meal and the rounding order is pinned: for each cooked meal, take that meal's `meal_grocery_cost_cents`, multiply it by 120 and divide by 100 (a 20 percent markup), round that marked-up grocery figure half up to whole cents, and then add the client's `per_meal_fee_cents`; the gross amount is the sum of these per-meal charges over all cooked meals. Each meal's marked-up grocery is rounded first and the rounded charges are then summed — summing the raw figures and rounding once at the end is explicitly not the method and would yield a different total. When a menu has no cooked meals, the per-meal gross is zero.

Settling an invoice is a client action that moves it from `ISSUED` to `PAID`; an attempt to pay an invoice not currently `ISSUED` is rejected with `ERR_INVALID_INVOICE_STATE`. Payment draws down the wallet: `credit_applied_cents` is set to the lesser of the client's current `wallet_credit_cents` and the invoice's `gross_amount_cents`, that amount is subtracted from the client's wallet balance, and the invoice's `net_amount_cents` is set to the gross amount minus the applied credit. This consumption is the term that the wallet ledger of §2.10 subtracts, keeping the running balance reconciled against its credit-granting and credit-consuming events.

State transitions across all of these workflows are guarded by their state checks: an illegal menu transition is rejected with `ERR_INVALID_MENU_STATE`, an illegal session transition with `ERR_INVALID_SESSION_STATE`, and an illegal invoice transition with `ERR_INVALID_INVOICE_STATE`, each surfacing only after the higher-priority header, role, ownership, existence, and body-validation checks of §2.9 have passed.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that read a resource, or that modify or transition an existing resource (including the action endpoints that drive state machines), return `200 OK`. All endpoints emit the standard envelope of §2.2 and are subject to the header, role, and validation rules above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a client profile | PlatformAdmin |
| GET | `/clients/{id}` | Fetch a client | PlatformAdmin, Client, Chef |
| POST | `/clients/{id}/cancel` | Cancel a client and cascade-cancel their live menus and sessions | PlatformAdmin |
| POST | `/chefs` | Create a chef | PlatformAdmin |
| POST | `/dietary-plans` | Create a dietary plan; supersedes the prior active plan | Client |
| GET | `/dietary-plans/{id}` | Fetch a dietary plan | PlatformAdmin, Client, Chef |
| GET | `/dietary-plans` | List dietary plans, filterable by client | PlatformAdmin, Client, Chef |
| POST | `/weekly-menus` | Draft a weekly menu for a client and plan | Chef |
| GET | `/weekly-menus/{id}` | Fetch a weekly menu | PlatformAdmin, Client, Chef |
| GET | `/weekly-menus` | List weekly menus, filterable by client, plan, or chef | PlatformAdmin, Client, Chef |
| POST | `/weekly-menus/{id}/propose` | Propose the drafted menu to the client | Chef |
| POST | `/weekly-menus/{id}/reject` | Reject a proposed menu, returning it for revision | Client |
| POST | `/weekly-menus/{id}/approve` | Approve a proposed menu; freeze cost and snapshots | Client |
| POST | `/weekly-menus/{id}/skip` | Skip an approved week; grant a wallet credit | Client |
| POST | `/weekly-menus/{id}/resume` | Resume a skipped week; reverse the skip credit | Client |
| POST | `/menu-meals` | Add a meal with ingredients to a draft menu | Chef |
| GET | `/menu-meals/{id}` | Fetch a menu meal | PlatformAdmin, Client, Chef |
| GET | `/menu-meals` | List meals, filterable by menu | PlatformAdmin, Client, Chef |
| POST | `/menu-meals/{id}/substitute` | Substitute an ingredient; safety-checked and cost-recomputed | Chef |
| POST | `/menu-meals/{id}/feedback` | Rate a cooked meal | Client |
| POST | `/cook-sessions` | Schedule an in-home cook session | Chef |
| GET | `/cook-sessions/{id}` | Fetch a cook session | PlatformAdmin, Client, Chef |
| GET | `/cook-sessions` | List cook sessions, filterable by menu or chef | PlatformAdmin, Client, Chef |
| POST | `/cook-sessions/{id}/start` | Start a scheduled session | Chef |
| POST | `/cook-sessions/{id}/complete` | Complete a session; drive the production cascade | Chef |
| POST | `/cook-sessions/{id}/no-show` | Report a chef no-show for a scheduled session | Client, PlatformAdmin |
| GET | `/containers/{id}` | Fetch a produced container | PlatformAdmin, Client, Chef |
| GET | `/containers` | List containers, filterable by meal | PlatformAdmin, Client, Chef |
| GET | `/billing-invoices/{id}` | Fetch an invoice | PlatformAdmin, Client, Chef |
| GET | `/billing-invoices` | List invoices, filterable by client or menu | PlatformAdmin, Client, Chef |
| POST | `/billing-invoices/{id}/pay` | Pay an issued invoice; apply available wallet credit | Client |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_CHEF_NOT_FOUND` | 404 Not Found |
| `ERR_DIETARY_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_WEEKLY_MENU_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_MEAL_NOT_FOUND` | 404 Not Found |
| `ERR_COOK_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_CONTAINER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CLIENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_MENU_STATE` | 409 Conflict |
| `ERR_INVALID_SESSION_STATE` | 409 Conflict |
| `ERR_INVALID_INVOICE_STATE` | 409 Conflict |
| `ERR_MENU_HAS_NO_MEALS` | 409 Conflict |
| `ERR_WEEK_ALREADY_STARTED` | 409 Conflict |
| `ERR_MEAL_NOT_COOKED` | 409 Conflict |
| `ERR_DIETARY_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_MENU_NOT_APPROVED` | 409 Conflict |
| `ERR_CHEF_SUSPENDED` | 409 Conflict |
| `ERR_INVALID_RATING` | 422 Unprocessable Entity |
| `ERR_ALLERGEN_CONFLICT` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_CHEF_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CLIENT_KITCHEN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_OUTSIDE_KITCHEN_HOURS` | 422 Unprocessable Entity |
| `ERR_GROCERY_BUDGET_EXCEEDED` | 402 Payment Required |

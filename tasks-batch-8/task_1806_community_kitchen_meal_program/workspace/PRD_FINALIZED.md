# Community Kitchen Meal Program API — Product Requirements Document

## 1. Introduction

A community kitchen lives and dies by the count. Cook too little and guests are turned away at the door; cook too much and a donation-funded program watches its margin wilt in the compost bin. This document specifies the Community Kitchen Meal Program API, a system that coordinates the full daily cycle of a multi-site meal program: forecasting production from reconciled history, receiving food under a strict safety-inspection regime, staffing the line with certified volunteers, serving guests across dine-in, to-go, and delivery channels, and reconciling waste and cost when the last tray comes back.

Meals are served under a standing no-charge policy; guests are never billed, and any donation prompt is handled outside the system. What the system does enforce, as machine-checkable rules rather than advisory flags, are the program's safety and readiness gates: an uninspected batch cannot reach a menu item, a kitchen with halted equipment cannot open a service window, an allergen conflict stops an order twice — once at reservation and again at the pass — and every serving received is accounted for as allocated, served, wasted, or redirected. All endpoints are mounted under `/kitchen`.

Five kinds of actors cooperate through the API. Program administrators own the sites and the equipment registry. Kitchen managers run the day: planning menus, allocating batches, opening services, scheduling shifts, and closing the books. Food safety officers form an independent inspection function, deliberately segregated from the staff who receive and allocate food. Volunteers work the shifts, and guests reserve the meals.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `ProgramAdmin`, `KitchenManager`, `FoodSafetyOfficer`, `Volunteer`, and `Guest`. A request missing either header, or carrying a role value outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `ProgramAdmin`, `KitchenManager`, or `FoodSafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any entity's `id`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer record, and ownership checks on any resource that references a volunteer compare the resource's `volunteer_id` field to `X-User-ID` — this is how the system ensures a volunteer checks in to, or self-cancels, only their own shift. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting GuestProfile, and ownership checks compare an order's `guest_id` to `X-User-ID`, so a guest reserves and releases only their own meals.

Role responsibilities follow the program's separation of duties. A `ProgramAdmin` is the platform-level operator: creating kitchen sites, registering equipment, volunteers, and guests, and driving the test clock. A `KitchenManager` runs a site day to day — menu planning and forecast locking, batch allocation, item confirmation, the full service lifecycle, shift scheduling and completion, guest flagging, volunteer suspension, equipment maintenance and repair, and waste logging — and may also place or release an order on a guest's behalf. A `FoodSafetyOfficer` is the independent inspector: the only role permitted to begin a batch inspection, record an inspection outcome, or reject a batch, a deliberate segregation from the kitchen staff who receive and allocate food; the officer may also receive batches and record waste. A `Volunteer` works the line — checking in, driving the preparation pipeline, serving and delivering — and may report an equipment fault. A `Guest` browses menu days, items, and services and manages their own reservations.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter skips a number of items from the head of the result set and defaults to 0. Every list response is sorted by the resources' `created_at` timestamp in ascending order, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

In addition to pagination, list endpoints accept resource-scoped filter parameters that mirror fields of the returned resource — for example `status`, `site_id`, `volunteer_id`, `service_date`, `service_model`, `source_type`, `equipment_class`, `certification_level`, `reason`, `disposition`, `fulfillment_status`, and `prep_status` — each narrowing the result set to records whose named field equals the supplied value.

### 2.4. Common Resource Properties

All primary resources in the program — sites, menu days, menu items, food batches, volunteers, shifts, guest profiles, services, orders, and equipment assets — share four system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): incremented by one on every mutation of the resource, including mutations that only touch derived or ledger fields.

Two record types are append-only exceptions to this convention. A batch allocation and a waste log each carry only `id` and `created_at`; both `updated_at` and `version` are absent from these records, since neither is ever modified after being written.

### 2.5. The Logical Clock

All time-gated behavior in the system — batch expiry, certification validity, check-in windows, no-show detection, order expiry — is evaluated against a single server-held logical clock, never against wall-clock time. At server startup, before any request is processed, the logical clock reads exactly 2026-08-01T00:00:00Z. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; time-gated automatic transitions, such as a shift lapsing to `NO_SHOW` or a still-open order expiring at service close, are re-evaluated lazily on the next read or write that touches them.

Two boundary conventions recur throughout this document. A deadline expressed as an expiry instant is exclusive in both directions of phrasing used here: a batch is unusable at or after its `use_by` (an instant exactly equal to `use_by` is already expired), and a food-handler certification is invalid at or after its `certification_expires_at`. Intervals such as shifts and service windows are half-open: they include their start instant and exclude their end instant.

### 2.6. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order so the surfaced error is deterministic. A structurally malformed body — a missing required field or a value of the wrong JSON type — fails first with `ERR_VALIDATION` (HTTP 400). The business pipeline then proceeds in this order:

1. Authentication: the headers are present and the role is recognized, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. Authorization: the acting role is permitted on the endpoint, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. Existence: every path-referenced resource exists, validated left to right, else `ERR_NOT_FOUND` (HTTP 404).
4. State legality: the target entity is in a state from which the requested transition is defined, including all state-machine preconditions, else `ERR_INVALID_STATE` (HTTP 409).
5. Food-safety gates: batch expiry, inspection standing, allergen separation at the pass, and safety-discard targeting, else `ERR_SAFETY_VIOLATION` (HTTP 422) or the more specific safety codes named in later sections.
6. Temporal conflicts: colliding shift, service, or maintenance intervals and lapsed certifications, else `ERR_TEMPORAL_CONFLICT` (HTTP 422).
7. Uniqueness and shape: duplicate natural keys, out-of-range quantities, invalid enum members, and capacity-shape rules, else `ERR_CONSTRAINT_VIOLATION` (HTTP 422).
8. Referential integrity with state: cross-referenced resources exist and are in an admissible state, else `ERR_REFERENCE_INVALID` (HTTP 422).
9. Capacity and quota ceilings — service capacity, batch remainder, the rescue cap — are enforced last of all, else `ERR_CAPACITY_FULL` (HTTP 422).

The ordering matters operationally: a request that is both unauthenticated and aimed at a missing resource surfaces `ERR_UNAUTHENTICATED`, and a capacity rejection is reported only after every safety, temporal, shape, and reference check has already passed.

### 2.7. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. Each identifier in the path is resolved in turn, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource — before any later segment, and before any body validation, is considered. A request for a menu item beneath a non-existent menu day therefore reports the missing menu day, not the missing item.

### 2.8. Optimistic Concurrency Control

Two write operations in the program are guarded by optimistic concurrency control, and both guard on the parent menu day's `version`. Locking a menu day's forecast requires the request to carry `expected_menu_day_version` equal to the menu day's current `version`; if the version the client last observed no longer matches — because, for example, an intervening item confirmation advanced the menu day's version through ledger synchronization, invalidating the client's view of `committed_servings` — the lock is rejected with `ERR_STALE_VERSION` (HTTP 412). Opening a meal service carries the same `expected_menu_day_version` field with the same rejection: if the parent menu day's version has advanced since the client read it — say a committed item went unavailable and recomputed the committed tally — the open is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than letting the service open against a production plan the client has not observed. No other endpoint accepts a version field.

### 2.9. Derived Tallies and Kitchen-Wide Consistency

A handful of fields are never accepted as input; the server derives them and keeps them synchronized as events occur. On a site, `equipment_posture` is recomputed on every equipment status transition. On a menu day, `forecast_servings` is written once when the forecast is locked and then pinned; `committed_servings` rises and falls as items are confirmed or pulled; `served_count` climbs as orders are served or delivered; and `overproduction_ratio` — the excess of committed over served servings, expressed relative to the served count — is recomputed alongside, remaining null until at least one guest has been served. On a service, `reserved_count` tracks the live reservation pipeline. On a volunteer, `hours_balance` and `strike_count` accumulate from shift outcomes. On a guest, `visits_count` tallies fulfilled visits. On a batch, `remaining_servings` is the conserved remainder described in §3.3.

Whenever such a derived value changes on a resource, that resource's `updated_at` refreshes and its `version` increments — including parent resources mutated only through ledger synchronization from below. A menu day whose committed tally moved because one of its items was confirmed is a mutated menu day for every purpose in this document, including the optimistic-concurrency checks of §2.8. Consistency is immediate: there is no deferred or eventual recalculation of any derived tally.

### 2.10. Units, Precision, and Rounding

Servings are whole numbers; where a computation yields a fractional serving count, such as the production forecast, the result is rounded up to the next whole serving. Money is accounted in cents carried to two decimal places (hundredths of a cent): per-line costs and the final per-meal division are rounded half up to two decimal places, while the acquisition-cost field `unit_cost_cents_per_serving` preserves whatever fractional precision it is given — 33.335 is a legitimate value. Volunteer hours are kept to two decimal places, rounded half up per ledger event. Waste ratios are carried to four decimal places, rounded half up.

## 3. Business Logic & Workflows

### 3.1. Sites, Equipment, and the Kitchen's Operating Posture

Everything in the program hangs off a **Site**. A `ProgramAdmin` registers a kitchen site with a display `name` (unique across the program; a duplicate is rejected with `ERR_CONSTRAINT_VIOLATION`), a `dine_in_capacity` bounding seated guests per service run (at least 1), a `togo_capacity_per_window` bounding to-go meals issuable per thirty-minute pickup window, and a `delivery_radius_km` bounding how far delivery orders may travel. A new site begins life `OPEN`, and its `status` may later move to `CLOSED`; a `CLOSED` site refuses the creation of any new service run and blocks production from starting on its menu days.

Each site also carries a computed `equipment_posture`, initialized to `OPERATIONAL` when the site is created and recomputed on every equipment status transition at that site. The posture aggregates only the site's `CRITICAL` equipment assets: it is `OPERATIONAL` when every critical asset is `OPERATIONAL`, `RESTRICTED` when exactly one critical asset is `DOWN_FOR_REPAIR` or `IN_MAINTENANCE`, and `HALTED` when two or more critical assets are down or in maintenance. Assets classed `SUPPORT` never influence the posture. A `HALTED` posture is a hard operational gate: starting production, opening a service, and resuming a paused service are all rejected with `ERR_EQUIPMENT_HALTED` while the site is halted.

Equipment itself is registered by a `ProgramAdmin` or `KitchenManager` with the owning `site_id`, a `name` such as "Combi Oven 1", an `equipment_class` of `OVEN`, `STOVETOP`, `COLD_HOLDING`, or `GENERAL`, and a `criticality` of `CRITICAL` or `SUPPORT` (defaulting to `SUPPORT`). A newly registered asset begins `OPERATIONAL`, and registration immediately recomputes the site's posture. Every asset is on an inspection cadence: completing a maintenance or repair visit stamps `last_inspected_at` with the current logical time, and the system derives `next_inspection_due` by adding the program-wide `INSPECTION_INTERVAL_DAYS` interval to it. An asset whose `next_inspection_due` has passed cannot return to service until it has been re-inspected.

Planned upkeep moves an asset from `OPERATIONAL` to `IN_MAINTENANCE`, requested with a `maint_start` and `maint_end`. The maintenance window must not collide with any other in-maintenance record for the same `equipment_class` at the same site; the collision test treats each window as a closed interval and widens it by a fifteen-minute buffer on both sides, and a collision is rejected with `ERR_TEMPORAL_CONFLICT`. Completing maintenance returns the asset to `OPERATIONAL`, stamps the inspection time, recomputes the next due date, and recomputes the site posture.

Unplanned failure is reported by a `KitchenManager` or a `Volunteer` and moves the asset from `OPERATIONAL` to `DOWN_FOR_REPAIR`. The posture is recomputed immediately, and if the site thereby becomes `HALTED`, the failure cascades: every currently `OPEN` service at the site whose menu day includes an item requiring that equipment class is driven to `ABORTED`, and every order still in those services' pipelines is released. Completing a repair returns the asset from `DOWN_FOR_REPAIR` to `OPERATIONAL`, but only when the repair closes while the asset is still within its inspection interval — the logical clock has not passed `next_inspection_due` — or when an inspection is completed at repair close, signalled by the request's `inspected` flag; when inspection does occur at close, `last_inspected_at` is stamped and `next_inspection_due` recomputed, and in all cases the site posture is recomputed. An asset that will not be repaired is moved from `DOWN_FOR_REPAIR` to `DECOMMISSIONED`, at which point it leaves the posture set entirely and the posture is recomputed once more.

### 3.2. Planning the Menu Day and Locking the Forecast

A **MenuDay** is the production plan for one site on one date. A `KitchenManager` creates it with a `site_id`, a `service_date`, and an optional `forecast_variant` of `TRAILING_AVERAGE` (the default) or `DOW_WEIGHTED`, recorded for audit. Only one menu day may exist per site and service date; a duplicate pair is rejected with `ERR_CONSTRAINT_VIOLATION`. A new menu day is `DRAFT` with `committed_servings` and `served_count` both at zero, and its lifecycle runs `DRAFT` → `FORECAST_LOCKED` → `IN_PRODUCTION` → `SERVING` → `RECONCILED`, with `CANCELLED` as the early-exit terminal state available from `DRAFT`.

While the day is a `DRAFT`, the manager adds **MenuItem** records to it, each carrying a `menu_day_id` back to its plan, a dish `name`, a `planned_servings` count (which must be at least 1 for the item to stand as confirmed), an optional `allergen_tags` list drawn from the canonical allergen registry of `GLUTEN`, `DAIRY`, `EGG`, `SOY`, `PEANUT`, `TREE_NUT`, `FISH`, `SHELLFISH`, and `SESAME`, an optional `dietary_labels` list drawn from `VEGETARIAN`, `VEGAN`, `HALAL`, `KOSHER_STYLE`, `LOW_SODIUM`, and `DIABETIC_FRIENDLY`, and an optional `requires_equipment_class` of `OVEN`, `STOVETOP`, `COLD_HOLDING`, or `NONE` (defaulting to `NONE`) naming the critical equipment class the dish depends on. Items begin `PLANNED`.

An item becomes real when it is confirmed, moving `PLANNED` → `CONFIRMED`. Confirmation is allowed only while the owning menu day is still `DRAFT` — confirming against a day that has moved on is rejected with `ERR_INVALID_STATE` — and it carries two substantive gates. First, coverage: the sum of `servings` across the item's batch allocations must be at least the item's `planned_servings`; partial coverage is not confirmable and is rejected with `ERR_INVALID_STATE`. Second, provenance: every batch feeding the item must have `inspection_result` `PASSED` and status `ACCEPTED`, and no allocated batch may be past its use-by deadline — an uninspected or failed batch trips the food-safety gate with `ERR_SAFETY_VIOLATION`, and an expired one with `ERR_BATCH_EXPIRED`. Confirming is a ledger event: the menu day's `committed_servings` increases by the item's `planned_servings`, the day's `overproduction_ratio` is recomputed, and the menu day's own `version` increments as the parent ledger mutation.

Locking the forecast moves the day `DRAFT` → `FORECAST_LOCKED` and is where production forecasting runs. Two preconditions guard the lock: at least one item under the day must be `CONFIRMED`, and every food batch referenced by the day's allocations must be `ACCEPTED`; failures surface as `ERR_INVALID_STATE`. The request must also carry `expected_menu_day_version` matching the menu day's current `version`, per §2.8; a stale read is rejected with `ERR_STALE_VERSION`. When the lock lands, the system computes `forecast_servings` and pins it on the menu day. The forecast looks backward over reconciled history: the input set is the site's `RECONCILED` menu days within a twenty-eight-day lookback window ending on (and including) the day before the `service_date` — cancelled days never contribute. Under the `TRAILING_AVERAGE` variant, the forecast is the mean of the `served_count` values over all such reconciled days, regardless of weekday, multiplied by a growth factor of 1.05, with the product rounded up to the next whole serving. Under the `DOW_WEIGHTED` variant, the system blends two means — the mean `served_count` of the most recent four reconciled menu days at the site falling on the same weekday as the `service_date`, weighted six-tenths, and the mean `served_count` over all reconciled days in the same twenty-eight-day window regardless of weekday, weighted four-tenths — rounds the blend up to a whole serving first, and then multiplies by the 1.05 growth factor. If no reconciled history exists at all, the forecast is seeded at sixty servings. For identical history the two variants diverge whenever the same-weekday mean differs from the overall mean, which is precisely when the day-of-week seasonality the second variant captures matters.

Starting production moves the day `FORECAST_LOCKED` → `IN_PRODUCTION` and requires the site's `status` to be `OPEN` and its `equipment_posture` to be anything other than `HALTED` — a halted kitchen rejects the start with `ERR_EQUIPMENT_HALTED`. The first service opening beneath the day then carries it automatically from `IN_PRODUCTION` to `SERVING` (see §3.6). Each of these transitions increments the menu day's `version`.

Cancelling the plan moves `DRAFT` → `CANCELLED` and is allowed only while no service under the day stands `OPEN` or `PAUSED`. Cancellation is a full cascade: every item under the day still `PLANNED` or `CONFIRMED` is moved to `UNAVAILABLE`; every batch allocation beneath those items is released, restoring each batch's `remaining_servings` per the conservation rule of §3.3; and every volunteer shift referencing the day still `SCHEDULED` is moved to `CANCELLED`. The menu day's `version` increments with the cancellation.

### 3.3. Receiving Food and the Inspection Cycle

Food enters the program as a **FoodBatch**, receivable by a `KitchenManager` or a `FoodSafetyOfficer` at a given `site_id`. The intake record captures a `source_type` of `DONATION`, `PURCHASE`, or `RESCUE` — the provenance drives both inspection strictness and leftover policy downstream — plus a free-text `item_description`, a `quantity_servings` count of at least 1, a `received_at` timestamp for physical arrival, a `use_by` safety deadline, an optional supplier-declared `allergen_tags` list from the same canonical registry used for menu items (these tags propagate into items at allocation time), and, for `PURCHASE` batches, a required `unit_cost_cents_per_serving` acquisition cost that may be fractional. The same cost field is ignored — treated as zero — for `DONATION` batches, while `RESCUE` batches are costed through a per-serving handling fee instead (§3.8). A new batch stands in status `RECEIVED` with `inspection_result` `PENDING` and `remaining_servings` equal to its full `quantity_servings`.

Inspection is the exclusive province of the `FoodSafetyOfficer`. Beginning an inspection moves a batch from `RECEIVED` to `INSPECTING`, and the same begin-inspection action also re-opens inspection from `QUARANTINED` (the re-inspection cycle) and from `ACCEPTED` (routine re-inspection of stock already on hand). Every begin-inspection path requires the logical clock to be strictly earlier than the batch's `use_by`; at or after that instant the batch is expired and the action fails with `ERR_BATCH_EXPIRED`. Re-entering inspection from `QUARANTINED` additionally requires that a `SAFETY_DISCARD` waste log covering the contaminated portion has already been recorded for the batch, and each re-inspection round is counted for audit. Re-entering from `ACCEPTED` resets `inspection_result` back to `PENDING` for the new round.

Recording an outcome takes a `result` of `PASSED` or `FAILED`. A pass moves `INSPECTING` → `ACCEPTED` — again requiring the batch to be unexpired, else `ERR_BATCH_EXPIRED` — sets `inspection_result` to `PASSED`, and establishes `remaining_servings` as the batch's `quantity_servings` minus whatever has already been wasted. A fail moves `INSPECTING` → `QUARANTINED`, sets `inspection_result` to `FAILED`, and fires a depth-3 cascade: every batch allocation drawn from this batch leads to its owning menu item, and each such item still `CONFIRMED` is moved to `UNAVAILABLE`; that item transition in turn cascades to its reserved orders (substitute-or-release, per §3.7) and decrements the parent menu day's `committed_servings` ledger. A quarantined batch that will not be reworked is rejected outright, `QUARANTINED` → `REJECTED`, which forces `remaining_servings` to zero and releases all outstanding allocations. Finally, an `ACCEPTED` batch auto-transitions to `DEPLETED` the moment its `remaining_servings` reaches zero — everything allocated, served, wasted, or redirected.

Allocation links a batch to an item: a `KitchenManager` creates a **BatchAllocation** naming the `menu_item_id` it feeds, the `food_batch_id` it draws from, and the `servings` drawn (at least 1); the server stamps `allocated_at`. The referenced batch must be `ACCEPTED` — referencing a batch in any other status is rejected with `ERR_REFERENCE_INVALID`, a failed-inspection batch additionally trips `ERR_SAFETY_VIOLATION`, and an expired batch `ERR_BATCH_EXPIRED`. The draw itself is bounded by four ceilings, and the recorded amount is the smallest of them: the requested amount, the batch's `remaining_servings`, the item's uncovered need (its `planned_servings` less servings already allocated), and — for `RESCUE` batches only — a rescue cap equal to one half of the batch's total `quantity_servings` for any single menu item. A request asking for more servings than the batch still holds is rejected outright with `ERR_CAPACITY_FULL` rather than silently clamped, and a draw that would breach the rescue cap is rejected with the same code. Allocation decrements the batch's `remaining_servings` by the recorded amount and re-checks depletion.

Conservation is the invariant underneath all of this. For every batch, at every moment, its `quantity_servings` equals exactly the sum of its allocated servings (across all allocations from the batch, whatever item they feed), its wasted servings, and its `remaining_servings`. The waste side of that identity is defined in §3.8, including the one deliberate exception: servings sent onward to another program via rescue redirect reduce `remaining_servings` — the food has left the building, and it counts toward the batch's depletion — but they are not counted as kitchen waste.

### 3.4. Volunteers, Certification, and the Hours Ledger

Volunteers are registered by a `ProgramAdmin` or `KitchenManager` with a `full_name`, a contact `email` (unique across the program; duplicates are rejected with `ERR_CONSTRAINT_VIOLATION`), an optional `certification_level` of `NONE` (the default), `BASIC`, or `SUPERVISOR`, and a `certification_expires_at` for carded volunteers — null whenever the level is `NONE`, and the certification is invalid at or after that instant. New volunteers start `ACTIVE` with an `hours_balance` of zero and a `strike_count` of zero. A volunteer's `status` moves between `ACTIVE`, `SUSPENDED`, and `INACTIVE`.

A **VolunteerShift** is scheduled by a `KitchenManager` with a `site_id`, the assignee `volunteer_id`, the `menu_day_id` the shift supports, a `role_on_shift` of `PREP`, `COOK`, `SERVER`, `DRIVER`, or `SUPERVISOR_ON_DUTY`, and a `starts_at` / `ends_at` pair. Shift intervals are half-open — they include `starts_at` and exclude `ends_at` — and one volunteer may never hold two overlapping shifts; a collision is rejected with `ERR_TEMPORAL_CONFLICT`. The references must also be sound in their current state: a shift pointing at a missing or inadmissible volunteer, site, or menu day is rejected with `ERR_REFERENCE_INVALID`. Certification gates the role: working as `COOK` requires at least `BASIC`, and working as `SUPERVISOR_ON_DUTY` requires `SUPERVISOR`, with the card unexpired at the moment it is exercised; a shortfall is rejected with `ERR_CERTIFICATION_INSUFFICIENT`.

The shift lifecycle begins at `SCHEDULED`. The assigned volunteer checks in — only their own shift, per §2.1 — moving `SCHEDULED` → `CHECKED_IN` under three preconditions: the volunteer's account is `ACTIVE`; the certification required for the shift's role is valid at the current logical instant; and that instant falls inside the check-in window, which opens fifteen minutes before `starts_at` and runs to (but excludes) `ends_at`. A check-in attempted outside that window is rejected with `ERR_TEMPORAL_CONFLICT`.

Completing a shift is a `KitchenManager` action moving `CHECKED_IN` → `COMPLETED`, permitted once the logical clock has reached `ends_at`, or earlier when the manager sets the request's `early_close` flag. Completion credits the hours ledger: the shift's duration — `ends_at` minus `starts_at`, expressed in fractional hours and rounded half up to two decimal places — is added to the volunteer's `hours_balance`.

A shift can also be reassigned in place: a `KitchenManager` may move `CHECKED_IN` back to `SCHEDULED` under a different `volunteer_id`, provided the new assignee satisfies the same certification and overlap rules; the prior volunteer's credited hours are untouched by the swap.

Absence is handled by the no-show path. When the logical clock reaches `ends_at` and the shift was never checked in, the system moves `SCHEDULED` → `NO_SHOW` automatically; a `KitchenManager` can also force the same transition by marking the shift no-show. Either way the volunteer's `strike_count` increases by one, and a volunteer whose strike count reaches three — the program's `MAX_STRIKES` — is automatically moved from `ACTIVE` to `SUSPENDED`, with the cascade that all of their future `SCHEDULED` shifts are cancelled without penalty. Suspension can also be imposed directly by a `KitchenManager`, with the same cascade. Reinstating a suspended volunteer returns them `SUSPENDED` → `ACTIVE` and resets `strike_count` to zero.

Cancellation has its own etiquette. A volunteer may self-cancel a `SCHEDULED` shift only while the logical clock is earlier than `starts_at` by at least the program's `CANCEL_LOCKOUT_HOURS` lockout margin; inside the lockout the attempt is rejected with `ERR_CANCEL_IN_LOCKOUT`. A `KitchenManager` may cancel at any time, and when cancelling inside the lockout may set the request's `apply_penalty` flag, which subtracts two hours from the volunteer's `hours_balance`, floored at zero. The ledger is applied as a chronological replay of the volunteer's completion credits and penalty debits ordered by shift end time, with ties broken by record creation order, and the floor at zero is applied per event rather than at read time — which is exactly why the replay order matters.

### 3.5. Guests, Dietary Profiles, and Reserving a Meal

A **GuestProfile** is registered by a `ProgramAdmin` or `KitchenManager` with a `full_name` (the guest or household head), a `household_size` of at least 1 that caps how many servings one order may request, an `allergens` list from the canonical allergen registry, a `dietary_preferences` list from the dietary-label registry, and — for guests who will use delivery — a `delivery_address` and a `delivery_distance_km` measured from the home site. New guests are `ACTIVE` with a `visits_count` of zero.

Guest standing is managed by the `KitchenManager`. Flagging moves `ACTIVE` → `FLAGGED`: a flagged guest may still order, but every order for that guest must come through the manager's approval path — an order attempted under the `Guest` role for a `FLAGGED` profile is rejected with `ERR_GUEST_FLAGGED_NEEDS_REVIEW`, while the same order placed by a `KitchenManager` proceeds. Unflagging returns the profile to `ACTIVE`. Deactivation moves `ACTIVE` → `INACTIVE` and is permitted only when no order with fulfillment `RESERVED` still exists for the guest; an order that references a guest who has gone `INACTIVE` fails referential integrity with `ERR_REFERENCE_INVALID`.

Reserving a meal creates a **MealOrder**. The actor is either the guest themselves or a `KitchenManager` acting on their behalf, and the payload names the `meal_service_id` fulfilling the order, the `guest_id`, the `menu_item_id`, a `quantity` of servings, and an optional `substitution_allowed` flag (default true) recording whether the kitchen may swap in an allergen-safe alternative if the ordered dish later becomes unavailable. The gates fire in the §2.6 order. The service must be `OPEN` — reserving against a planned, paused, closed, or aborted service is rejected with `ERR_INVALID_STATE`, which is exactly how a paused service stops new orders. The referenced item must belong to the service's menu day and be `CONFIRMED`; an item that is missing from that menu day, merely `PLANNED`, `UNAVAILABLE`, or `SOLD_OUT` is rejected with `ERR_REFERENCE_INVALID`. The item's `allergen_tags` must have an empty intersection with the guest's `allergens` at creation time, else `ERR_ALLERGEN_CONFLICT`. The `quantity` must be at least 1 and no more than the guest's `household_size`, else `ERR_CONSTRAINT_VIOLATION`. For a delivery service, the guest's `delivery_distance_km` must not exceed the site's `delivery_radius_km`, else `ERR_DELIVERY_OUT_OF_RANGE`. And last, per §2.6, capacity: an order is accepted while the service's `reserved_count` remains strictly below its `capacity` — the order that brings the count exactly up to capacity is the last one accepted, and the next reservation attempt is rejected with `ERR_CAPACITY_FULL`.

A new reservation starts with `prep_status` `QUEUED` and `fulfillment_status` `RESERVED`, and its creation increments the service's `reserved_count` by one and re-evaluates whether the ordered item has now sold out (§3.7). Under the program's no-charge policy the order's `charge_cents` is always computed as zero; the field is kept as a computed value so that any future policy change has a single audit point, and the donation prompt is handled entirely out of band.

### 3.6. Opening and Running the Service Window

A **MealService** is one channel of one menu day: a `KitchenManager` creates it with a `menu_day_id`, a `service_model` of `DINE_IN`, `TO_GO`, or `DELIVERY`, a `window_start` and `window_end` describing a half-open service window, a `capacity` bounding accepted orders, and an optional `requires_supervisor` flag (default false). The referenced menu day must already be `IN_PRODUCTION` or `SERVING`; attaching a service to a day in any other state is rejected with `ERR_INVALID_STATE`, and a `CLOSED` site refuses new services outright.

Window hygiene is enforced per site. Two services of the same `service_model` at the same site may never have overlapping windows under the half-open convention, and a dine-in window additionally keeps a thirty-minute buffer against to-go: no to-go window at the same site may start within thirty minutes before or after the dine-in window. A violation of either rule is rejected with `ERR_TEMPORAL_CONFLICT`. The `capacity` is also shape-checked against the site: a dine-in service's capacity must not exceed the site's `dine_in_capacity`; a to-go service's capacity must not exceed the site's `togo_capacity_per_window` multiplied by the number of whole thirty-minute slots that fit inside the window; and a delivery service's capacity is unbounded by site shape, since every delivery order is instead range-checked individually. A broken shape rule is rejected with `ERR_CONSTRAINT_VIOLATION`. Services begin `PLANNED` with a `reserved_count` of zero.

Opening the service moves `PLANNED` → `OPEN` and is the most heavily gated transition in the program. The parent menu day must be `IN_PRODUCTION`; the site's `equipment_posture` must not be `HALTED`, else `ERR_EQUIPMENT_HALTED`; the window-conflict rules above are re-checked at open time; and when `requires_supervisor` is true there must exist a shift at the same site with `role_on_shift` `SUPERVISOR_ON_DUTY` currently `CHECKED_IN` whose half-open shift interval overlaps the service window, else `ERR_SUPERVISOR_REQUIRED`. The request must also carry `expected_menu_day_version` matching the menu day's current `version`, per §2.8, with mismatches rejected as `ERR_STALE_VERSION`. When the first service under a menu day opens, the menu day automatically advances `IN_PRODUCTION` → `SERVING`, incrementing its `version`.

From `OPEN`, a manager may pause the service, `OPEN` → `PAUSED`, which rejects new reservations while leaving the existing pipeline intact, and resume it, `PAUSED` → `OPEN`, provided the site's posture is still not `HALTED` (a halted site rejects the resume with `ERR_EQUIPMENT_HALTED`). Closing is terminal and available from either `OPEN` or `PAUSED`: every order still non-terminal — fulfillment `RESERVED`, whatever its preparation state — is automatically moved to `EXPIRED`, and the service's `reserved_count` is decremented once per expired order. Aborting is the emergency sibling, `OPEN` → `ABORTED`, justified when the site's posture is `HALTED` or by explicit manager override: every order still `RESERVED` or `IN_PREP` in the pipeline is moved to `RELEASED` with the reserved count reduced accordingly, and a posture re-check is scheduled as derived recomputation. A menu day can only be reconciled once every service beneath it stands `CLOSED` or `ABORTED`.

### 3.7. The Order Pipeline: Preparation, Allergen Re-Check, and Fulfillment

Every order lives on two parallel tracks. The kitchen-side `prep_status` runs `QUEUED` → `IN_PREP` → `READY` with a rework loop back, and the guest-side `fulfillment_status` runs from `RESERVED` to one of `SERVED`, `DELIVERED`, `RELEASED`, or `EXPIRED`, all four terminal.

Starting preparation moves `QUEUED` → `IN_PREP` and is performed by a `Volunteer` — specifically one currently `CHECKED_IN` on a shift at this site that covers the current logical instant and whose role is `PREP` or `COOK`; the service must also still be `OPEN`, else `ERR_INVALID_STATE`. Marking an order ready moves `IN_PREP` → `READY` and carries the program's second allergen gate: the item's `allergen_tags` — including anything propagated from its allocated batches — are intersected with the guest's `allergens` again at ready time, not merely trusted from reservation time, and any overlap is rejected with `ERR_ALLERGEN_CONFLICT`. When that re-check fails in practice, the rework loop moves `READY` back to `IN_PREP`, recording a `reason` and appending an audit note, so the dish can be re-fires safely.

Fulfillment forks by channel. Serving moves `RESERVED` → `SERVED`, is performed by a `Volunteer`, and requires the order's `prep_status` to be `READY`, the service's `service_model` to be `DINE_IN`, and the service still `OPEN`. Delivery moves `RESERVED` → `DELIVERED`, requires the order `READY`, the service's `service_model` `DELIVERY`, and the acting volunteer to be `CHECKED_IN` on a `DRIVER` shift covering the current instant. Both fulfillments fire the same ledger cascade: the menu day's `served_count` increases by the order's `quantity` (and the day's `overproduction_ratio` is recomputed with it), the guest's `visits_count` increases by one, and the service's `reserved_count` decreases by one.

Release is the no-charge cancellation path, `RESERVED` → `RELEASED`, returning capacity to the pool. A guest may release their own order only before the service's `window_start`; a `KitchenManager` may release at any time; and the system itself releases orders through the cascades described elsewhere (an item going unavailable, a service aborting). Every release decrements the service's `reserved_count` by one and re-evaluates whether the referenced item has sold out. Expiry, `RESERVED` → `EXPIRED`, is the system's housekeeping move at service close for any order still non-terminal, again decrementing `reserved_count`.

Two item-level transitions ride on this pipeline. The moment the number of orders referencing a `CONFIRMED` item with fulfillment `RESERVED`, `SERVED`, or `DELIVERED` reaches the item's `planned_servings`, the item auto-transitions to `SOLD_OUT` and is excluded from further ordering. And when an item is pulled — moving `CONFIRMED` → `UNAVAILABLE` at a manager's hand, or by cascade from a batch quarantine (§3.3) — provided the menu day is in `DRAFT`, `FORECAST_LOCKED`, `IN_PRODUCTION`, or `SERVING`, the day's `committed_servings` decreases by the item's `planned_servings` and every order for that item still `RESERVED` whose preparation has not reached `READY` is resolved one of two ways: if the order's `substitution_allowed` is set, the order is re-pointed to a `CONFIRMED`, allergen-compatible item on the same menu day chosen by the kitchen's selector policy; otherwise the order is released, moving fulfillment to `RELEASED` and decrementing `reserved_count`. Orders already `READY` are left alone to be served. Pulling a still-`PLANNED` item to `UNAVAILABLE` needs no such cascade and changes no ledger, since nothing was ever committed for it.

### 3.8. Waste, Reconciliation, and the Cost of a Served Meal

Leftovers and losses are recorded as **WasteLog** entries by a `KitchenManager` or `FoodSafetyOfficer`. Each log names the `menu_day_id` being reconciled and the `food_batch_id` the waste is attributed to, a `servings_wasted` count of at least 1, a `reason` of `OVERPRODUCTION`, `SPOILAGE`, `SAFETY_DISCARD`, or `PACKAGING_DAMAGE`, and a `disposition` of `DISCARD`, `COMPOST`, or `RESCUE_REDIRECT`; the server stamps `logged_at`. The `SAFETY_DISCARD` reason is restricted to batches that are `QUARANTINED` or expired — using it against healthy stock is rejected with `ERR_SAFETY_VIOLATION`. Writing a waste log re-runs the conservation identity of §3.3: servings disposed as `DISCARD` or `COMPOST` count as waste and reduce `remaining_servings`; servings sent onward as `RESCUE_REDIRECT` also reduce `remaining_servings` — the food left the building, and they count when the system checks whether the batch should auto-transition to `DEPLETED` — but they are deliberately excluded from the kitchen's waste totals, because a successful diversion to another program is not waste. After every log the invariant must hold exactly: `quantity_servings` equals allocated plus wasted plus remaining.

Reconciliation closes the day. A `KitchenManager` reconciles a menu day, moving `SERVING` → `RECONCILED`, only when every service beneath the day is `CLOSED` or `ABORTED` and every order beneath those services has reached a terminal fulfillment state — `SERVED`, `DELIVERED`, `RELEASED`, or `EXPIRED`; otherwise the transition is rejected with `ERR_INVALID_STATE`. Reconciliation computes the day's waste ratio: the numerator is the sum of `servings_wasted` over the day's waste logs with disposition `DISCARD` or `COMPOST`, and the denominator is the day's `committed_servings` at reconcile time. The ratio is carried to four decimal places with round-half-up. If nothing was ever committed — the denominator is zero — the ratio is null and no alert can fire. Otherwise, a ratio strictly greater than 0.15 raises the day's overproduction alert flag, surfaced on subsequent reads of the menu day; a ratio exactly equal to 0.15 does not alert. The transition increments the menu day's `version`.

The reconciled day also supports a computed summary read exposing the forecast versus committed versus served tallies, the waste ratio, and the cost of a served meal. That cost is built one line per `CONFIRMED` menu item — including items that later went `UNAVAILABLE` — fed by the batches allocated to it: a `PURCHASE`-fed line costs the batch's `unit_cost_cents_per_serving` multiplied by the item's `planned_servings`, rounded half up to two decimal places; a `DONATION`-fed line costs zero; and a `RESCUE`-fed line costs a flat handling fee of 35 cents per planned serving, likewise rounded half up to two decimal places. The day's total cost is the sum of those already-rounded lines — the rounding order is pinned, per line first and only then summed, because summing raw unrounded values and rounding once produces different cents and is not compliant: two lines of raw 100.005 sum to 200.01 under sum-then-round, but to 100.01 + 100.01 = 200.02 under the pinned order. The cost per served meal is that total divided by the day's `served_count` — or by 1 when no guest was served, so the divisor is never zero — rounded half up to two decimal places. Alongside it, the day's `overproduction_ratio` reports the excess of `committed_servings` over `served_count` relative to `served_count`, or null when nothing was served.

Throughout the day the ledger tallies of §2.9 keep every parent consistent with its children: confirmations and pulls move `committed_servings` and bump the menu day's `version`; fulfillments move `served_count`, `visits_count`, and `reserved_count`; allocation, waste, and acceptance events keep `remaining_servings` exact; and equipment transitions keep `equipment_posture` honest. A reader at any instant sees the same numbers the gates enforced.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a site, a menu day, a menu item, a food batch, an allocation, a volunteer, a shift, a guest, a service, an order, an equipment asset, or a waste log — return `201 Created`. Operations that act on an existing resource, including every state-transition action, return `200 OK`. Request payloads, response contents, and side effects for each operation are defined by the narratives in §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/kitchen/sites` | Create a kitchen site | ProgramAdmin |
| GET | `/kitchen/sites` | List sites (paginated) | ProgramAdmin, KitchenManager, FoodSafetyOfficer, Volunteer, Guest |
| GET | `/kitchen/sites/{id}` | Get one site including computed equipment_posture | ProgramAdmin, KitchenManager, FoodSafetyOfficer, Volunteer, Guest |
| GET | `/kitchen/sites/{id}/equipment-assets` | List equipment at a site | ProgramAdmin, KitchenManager, Volunteer |
| GET | `/kitchen/sites/{id}/food-batches` | List food batches received at a site | ProgramAdmin, KitchenManager, FoodSafetyOfficer |
| GET | `/kitchen/sites/{id}/volunteer-shifts` | List shifts at a site | ProgramAdmin, KitchenManager, Volunteer |
| POST | `/kitchen/menu-days` | Create a production plan for (site_id, service_date) | KitchenManager |
| GET | `/kitchen/menu-days` | List menu days, filterable | ProgramAdmin, KitchenManager, FoodSafetyOfficer, Volunteer, Guest |
| GET | `/kitchen/menu-days/{id}` | Get one menu day with computed fields | ProgramAdmin, KitchenManager, FoodSafetyOfficer, Volunteer, Guest |
| GET | `/kitchen/menu-days/{id}/summary` | Computed read: forecast vs committed vs served, waste_ratio, cost_per_served_meal | ProgramAdmin, KitchenManager |
| GET | `/kitchen/menu-days/{id}/menu-items` | List items of a menu day | ProgramAdmin, KitchenManager, FoodSafetyOfficer, Volunteer, Guest |
| GET | `/kitchen/menu-days/{id}/meal-services` | List services of a menu day | ProgramAdmin, KitchenManager, Volunteer, Guest |
| GET | `/kitchen/menu-days/{id}/waste-logs` | List waste logs of a menu day | ProgramAdmin, KitchenManager, FoodSafetyOfficer |
| GET | `/kitchen/menu-days/{id}/volunteer-shifts` | List shifts supporting a menu day | ProgramAdmin, KitchenManager, Volunteer |
| POST | `/kitchen/menu-days/{id}/lock-forecast` | Lock the forecast (DRAFT → FORECAST_LOCKED); runs production_forecast; OCC-guarded | KitchenManager |
| POST | `/kitchen/menu-days/{id}/start-production` | Start production (FORECAST_LOCKED → IN_PRODUCTION) | KitchenManager |
| POST | `/kitchen/menu-days/{id}/reconcile` | Reconcile the day (SERVING → RECONCILED); computes the waste-ratio alert | KitchenManager |
| POST | `/kitchen/menu-days/{id}/cancel` | Cancel the day (DRAFT → CANCELLED) with full cascade to items, allocations, and shifts | KitchenManager |
| POST | `/kitchen/menu-days/{id}/menu-items` | Add a planned item to a DRAFT menu day | KitchenManager |
| GET | `/kitchen/menu-items/{id}` | Get one menu item | ProgramAdmin, KitchenManager, FoodSafetyOfficer, Volunteer, Guest |
| GET | `/kitchen/menu-items/{id}/batch-allocations` | List allocations feeding this item | ProgramAdmin, KitchenManager, FoodSafetyOfficer |
| GET | `/kitchen/menu-items/{id}/meal-orders` | List orders referencing this item | ProgramAdmin, KitchenManager, Volunteer |
| POST | `/kitchen/menu-items/{id}/allocations` | Allocate servings from an ACCEPTED batch to this item | KitchenManager |
| POST | `/kitchen/menu-items/{id}/confirm` | Confirm the item (PLANNED → CONFIRMED) with coverage check | KitchenManager |
| POST | `/kitchen/menu-items/{id}/mark-unavailable` | Mark the item unavailable (PLANNED or CONFIRMED → UNAVAILABLE) with order cascade | KitchenManager |
| POST | `/kitchen/food-batches` | Receive a food batch at a site | KitchenManager, FoodSafetyOfficer |
| GET | `/kitchen/food-batches/{id}` | Get one batch | ProgramAdmin, KitchenManager, FoodSafetyOfficer |
| GET | `/kitchen/food-batches/{id}/batch-allocations` | List allocations drawn from this batch | ProgramAdmin, KitchenManager, FoodSafetyOfficer |
| GET | `/kitchen/food-batches/{id}/waste-logs` | List waste logs attributed to this batch | ProgramAdmin, KitchenManager, FoodSafetyOfficer |
| POST | `/kitchen/food-batches/{id}/begin-inspection` | Begin or re-open inspection (RECEIVED, QUARANTINED, or ACCEPTED → INSPECTING) | FoodSafetyOfficer |
| POST | `/kitchen/food-batches/{id}/record-inspection` | Record inspection outcome (INSPECTING → ACCEPTED on PASSED, → QUARANTINED on FAILED) | FoodSafetyOfficer |
| POST | `/kitchen/food-batches/{id}/reject` | Reject a quarantined batch (QUARANTINED → REJECTED); releases allocations | FoodSafetyOfficer |
| POST | `/kitchen/volunteers` | Register a volunteer | ProgramAdmin, KitchenManager |
| GET | `/kitchen/volunteers` | List volunteers | ProgramAdmin, KitchenManager |
| GET | `/kitchen/volunteers/{id}` | Get one volunteer with hours_balance and strike_count | ProgramAdmin, KitchenManager, Volunteer |
| GET | `/kitchen/volunteers/{id}/volunteer-shifts` | List shifts of a volunteer | ProgramAdmin, KitchenManager, Volunteer |
| POST | `/kitchen/volunteers/{id}/suspend` | Suspend a volunteer (ACTIVE → SUSPENDED); cancels future scheduled shifts | KitchenManager |
| POST | `/kitchen/volunteers/{id}/reinstate` | Reinstate a volunteer (SUSPENDED → ACTIVE); resets strikes | KitchenManager |
| POST | `/kitchen/volunteer-shifts` | Schedule a shift; validates certification, overlap, and menu-day linkage | KitchenManager |
| GET | `/kitchen/volunteer-shifts/{id}` | Get one shift | ProgramAdmin, KitchenManager, Volunteer |
| POST | `/kitchen/volunteer-shifts/{id}/check-in` | Check in to a shift (SCHEDULED → CHECKED_IN) | Volunteer |
| POST | `/kitchen/volunteer-shifts/{id}/complete` | Complete a shift (CHECKED_IN → COMPLETED); credits the hours ledger | KitchenManager |
| POST | `/kitchen/volunteer-shifts/{id}/reassign` | Reassign a checked-in shift to a different volunteer (CHECKED_IN → SCHEDULED) | KitchenManager |
| POST | `/kitchen/volunteer-shifts/{id}/cancel` | Cancel a shift (SCHEDULED → CANCELLED); lockout and penalty rules apply | Volunteer, KitchenManager |
| POST | `/kitchen/volunteer-shifts/{id}/mark-no-show` | Mark a shift no-show (SCHEDULED → NO_SHOW); strike cascade may suspend the volunteer | KitchenManager |
| POST | `/kitchen/guests` | Register a guest profile | ProgramAdmin, KitchenManager |
| GET | `/kitchen/guests/{id}` | Get one guest | ProgramAdmin, KitchenManager, Guest |
| GET | `/kitchen/guests/{id}/meal-orders` | List a guest's orders | ProgramAdmin, KitchenManager, Guest |
| POST | `/kitchen/guests/{id}/flag` | Flag a guest (ACTIVE → FLAGGED) | KitchenManager |
| POST | `/kitchen/guests/{id}/unflag` | Unflag a guest (FLAGGED → ACTIVE) | KitchenManager |
| POST | `/kitchen/guests/{id}/deactivate` | Deactivate a guest (ACTIVE → INACTIVE); requires no reserved orders | KitchenManager |
| POST | `/kitchen/meal-services` | Create a service run under a menu day; validates window overlap and capacity shape | KitchenManager |
| GET | `/kitchen/meal-services/{id}` | Get one service | ProgramAdmin, KitchenManager, Volunteer, Guest |
| GET | `/kitchen/meal-services/{id}/meal-orders` | List orders of a service | ProgramAdmin, KitchenManager, Volunteer |
| POST | `/kitchen/meal-services/{id}/open` | Open the service (PLANNED → OPEN); OCC on the parent menu day; supervisor and posture gates | KitchenManager |
| POST | `/kitchen/meal-services/{id}/pause` | Pause the service (OPEN → PAUSED) | KitchenManager |
| POST | `/kitchen/meal-services/{id}/resume` | Resume the service (PAUSED → OPEN) | KitchenManager |
| POST | `/kitchen/meal-services/{id}/close` | Close the service (OPEN or PAUSED → CLOSED); non-terminal orders auto-expire | KitchenManager |
| POST | `/kitchen/meal-services/{id}/abort` | Abort the service (OPEN → ABORTED); releases all pipeline orders | KitchenManager |
| POST | `/kitchen/meal-orders` | Reserve an order (no-charge); allergen, capacity, household, and delivery-radius checks | Guest, KitchenManager |
| GET | `/kitchen/meal-orders/{id}` | Get one order (both state dimensions) | ProgramAdmin, KitchenManager, Volunteer, Guest |
| POST | `/kitchen/meal-orders/{id}/start-prep` | Start preparation (prep QUEUED → IN_PREP) | Volunteer |
| POST | `/kitchen/meal-orders/{id}/mark-ready` | Mark ready (prep IN_PREP → READY) with allergen re-check | Volunteer |
| POST | `/kitchen/meal-orders/{id}/rework` | Rework (prep READY → IN_PREP) | Volunteer |
| POST | `/kitchen/meal-orders/{id}/serve` | Serve the order (fulfillment RESERVED → SERVED; dine-in only) | Volunteer |
| POST | `/kitchen/meal-orders/{id}/deliver` | Deliver the order (fulfillment RESERVED → DELIVERED; delivery only, driver shift) | Volunteer |
| POST | `/kitchen/meal-orders/{id}/release` | Release the order (fulfillment RESERVED → RELEASED); returns capacity | Guest, KitchenManager |
| POST | `/kitchen/equipment-assets` | Register equipment at a site | ProgramAdmin, KitchenManager |
| GET | `/kitchen/equipment-assets/{id}` | Get one asset | ProgramAdmin, KitchenManager, Volunteer |
| POST | `/kitchen/equipment-assets/{id}/schedule-maintenance` | Schedule maintenance (OPERATIONAL → IN_MAINTENANCE) | KitchenManager |
| POST | `/kitchen/equipment-assets/{id}/complete-maintenance` | Complete maintenance (IN_MAINTENANCE → OPERATIONAL); stamps inspection | KitchenManager |
| POST | `/kitchen/equipment-assets/{id}/report-fault` | Report a fault (OPERATIONAL → DOWN_FOR_REPAIR); may cascade halted-posture aborts | KitchenManager, Volunteer |
| POST | `/kitchen/equipment-assets/{id}/complete-repair` | Complete a repair (DOWN_FOR_REPAIR → OPERATIONAL) with inspection gating | KitchenManager |
| POST | `/kitchen/equipment-assets/{id}/decommission` | Decommission an asset (DOWN_FOR_REPAIR → DECOMMISSIONED) | KitchenManager |
| POST | `/kitchen/waste-logs` | Record waste or leftover disposition against a menu day and batch | KitchenManager, FoodSafetyOfficer |
| GET | `/kitchen/waste-logs/{id}` | Get one waste log | ProgramAdmin, KitchenManager, FoodSafetyOfficer |
| POST | `/kitchen/_clock/set_current_utc` | Test-driving capability: set the logical clock | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an identifier-and-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SAFETY_VIOLATION` | 422 Unprocessable Entity |
| `ERR_TEMPORAL_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CONSTRAINT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_REFERENCE_INVALID` | 422 Unprocessable Entity |
| `ERR_CAPACITY_FULL` | 422 Unprocessable Entity |
| `ERR_DELIVERY_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ALLERGEN_CONFLICT` | 422 Unprocessable Entity |
| `ERR_SUPERVISOR_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_HALTED` | 422 Unprocessable Entity |
| `ERR_CANCEL_IN_LOCKOUT` | 422 Unprocessable Entity |
| `ERR_GUEST_FLAGGED_NEEDS_REVIEW` | 422 Unprocessable Entity |
| `ERR_BATCH_EXPIRED` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |

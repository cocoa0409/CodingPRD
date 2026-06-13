# Commissary Shared Production Kitchen API — Product Requirements Document

## 1. Introduction

A commissary is a shared, licensed production kitchen where many independent food businesses rent time, equipment, and storage rather than carrying the overhead of their own facility. This API is the operational backbone of such a facility. It coordinates the things that make a shared kitchen work: members reserve stations during the hours they need, claim shelf space in dry, cold, and frozen storage, develop recipes with full bills of materials, run production batches, replenish their ingredient stocks, pack finished goods for catering events, and settle a monthly bill — all against a backdrop of health-code temperature monitoring and allergen control that the facility is legally obligated to enforce.

The system serves four constituencies with distinct concerns. Member operators care about getting their production done and knowing what it costs. The facility manager cares about keeping the shared assets healthy, the schedule honest, and the books balanced. The compliance officer cares about food safety — that cold storage stays cold and that a unit which has drifted out of range is quarantined before contaminated product reaches an event. And prospective members simply need a way to register. The requirements below describe a single REST API that mediates all of these workflows while holding two hard invariants throughout: a member's prepaid wallet is a conserved ledger that must always reconcile, and storage slots are a conserved capacity that can never be over-allocated.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across the entire API. Where a later business-workflow section (§3) describes a specific operation, the global rules here still govern it.

### 2.1. User and Role-Based Access Control

Every request other than member self-registration must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. A request that is missing either header (on any endpoint except member registration) is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role must be permitted to perform the requested operation per the authorization matrix; a permitted-but-wrong-role attempt is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `MemberOperator`, `FacilityManager`, and `ComplianceOfficer`.

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; an anonymous caller may only self-register a new member and may do nothing else.
- When `X-User-Role` is `MemberOperator`, `X-User-ID` is the `id` of the acting `Member`. This is the only entity-backed role. Ownership checks on any resource that references a `Member` compare the resource's `member_id` foreign-key field to `X-User-ID`. A member operator acting on a member-scoped resource that they do not own — that is, where the resource's `member_id` does not equal `X-User-ID` — is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403). This ownership rejection is enforced on the member-scoped *mutating* operations a `MemberOperator` may invoke (the creates and state transitions whose path or body carries a `member_id`); the read-only `GET` endpoints are not ownership-gated — any permitted role, including a `MemberOperator` supplying a `member_id` other than their own in the path, may read a member-scoped resource so long as the path identifiers resolve.
- When `X-User-Role` is `FacilityManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The facility manager administers shared resources — stations, storage units, ingredients — manages the member lifecycle (suspend, reinstate, close), and runs billing (invoice generation, issue, pay). The server may record this identifier but does not compare it to any entity's `id`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The compliance officer owns temperature logging, reading certification, unit quarantine clearance, and quarantine release of assignments. The server may record this identifier but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip; it defaults to 0 and its minimum is 0. A list request whose `limit` falls outside the range of 1 through 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION` (HTTP 422). Because list endpoints carry no business preconditions, this is a pure request-shape check and its relative position among other checks is immaterial.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the number of items matching the request before pagination is applied, and `has_more` is true exactly when `offset` plus the number of items returned on this page is less than `total_count` (i.e. when further items remain beyond this page).

### 2.4. Common Resource Properties and Identity

Most primary resources in this system — `Member`, `Station`, `Booking`, `StorageUnit`, `StorageAssignment`, `Ingredient`, `Recipe`, `ProductionBatch`, `IngredientOrder`, `EventPackout`, and `Invoice` — carry a standard set of system-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 on creation and increments by one on every mutation. It is used for the optimistic concurrency control described in §2.6. `Recipe` is the one exception to the "increments on every mutation" rule: a recipe's `version` is its revision counter (per §3.4), so it advances by one only when the recipe is revised and is left unchanged by its other mutations (publish, retire) even though those still refresh `updated_at`.

Two entities are deliberately lighter-weight. A `RecipeComponent` (a single bill-of-materials line) and a `TempLog` (a single temperature reading) carry only `id` and `created_at`; they have neither `updated_at` nor `version`, because they are append-only records that are never independently mutated after creation.

### 2.5. Hierarchical Consistency, Derived Fields, and Nested Path Resolution

Many writes in this system touch more than one resource. When an operation mutates a resource — directly, or as a downstream cascade — that resource's `updated_at` is refreshed and its `version` is incremented. This applies equally to derived (read-only, computed) fields: when a member's wallet is debited, when a storage unit's used-slot count changes, or when a unit's compliance posture flips, the affected resource is a genuine mutation and advances its own `version`. The server may also transition a resource on its own initiative — for example, quarantining a storage unit and the assignments it holds — without an explicit client request against that specific resource; these autonomous transitions are mutations and follow the same `updated_at`/`version` discipline.

For any request whose URL contains more than one resource identifier (for example, a booking nested under a member, or a temperature reading nested under a storage unit), the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The parent is always checked before the child: a booking id is never evaluated until the member id in the same path has been confirmed to exist. The same `ERR_NOT_FOUND` governs foreign-key references supplied in a request body — `station_id`, `recipe_id`, `ingredient_id`, `storage_unit_id`, and the entries of `batch_ids` must each resolve to an existing entity, or the create is rejected.

### 2.6. Optimistic Concurrency on Member Writes

Two member-scoped creates commit financial or capacity claims against a member's standing state, and both are guarded by optimistic concurrency control keyed on the member's `version`. The two guarded writes are booking creation and storage-assignment creation. Each of these requests must carry an `expected_member_version` field whose value is the `version` of the target `Member` that the client last observed.

When a booking is created, the request must carry `expected_member_version` matching the target member's current `version`. A booking debits the member's wallet and advances the member's `version`; if another writer (a prior booking, a wallet top-up, a suspension, or any other member mutation) has advanced that `version` since the client last read the member, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) so the wallet debit is never computed against an out-of-date balance. The storage-assignment create behaves the same way: its `expected_member_version` must match the member's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a stale member view may mean an intervening suspension or close has changed the member's eligibility to take on a new obligation. Booking creation and storage-assignment creation are the only two endpoints that *require* `expected_member_version` (it is a mandatory body field, and its absence is an `ERR_INVALID_REQUEST` body-well-formedness failure). The member-lifecycle transitions (suspend, reinstate, close) additionally *accept* an `expected_member_version`, but for them it is optional: when supplied it is checked against the member's current `version` and a mismatch yields `ERR_STALE_VERSION`, and when omitted no concurrency check is performed and the transition proceeds. No endpoint other than these five reads the field.

### 2.7. The Wallet Ledger and Its Conservation Invariant

Each member carries a prepaid wallet, expressed in whole cents, that is the source of funds for every charge the facility levies. Three read-only figures track it: `wallet_balance_cents` is the current spendable balance and starts at 0 on registration; `lifetime_loaded_cents` is the running total of every top-up ever applied; and `lifetime_charged_cents` is the running total of all charges net of refunds. These three are bound by a permanent invariant: `wallet_balance_cents` always equals `lifetime_loaded_cents` minus `lifetime_charged_cents`. Every operation that moves money must preserve this identity.

A top-up of `amount_cents` credits the wallet balance and adds the same amount to `lifetime_loaded_cents`, and it advances the member's `version`. A charge (a booking fee, a production fee, or an invoice payment) subtracts from the wallet balance and adds the same amount to `lifetime_charged_cents`. A refund (a booking cancellation) credits the wallet balance back and subtracts the refunded amount from `lifetime_charged_cents`, restoring the invariant rather than touching the loaded total. Whenever a charge is attempted and the member's `wallet_balance_cents` is below the computed amount, the operation is refused with `ERR_INSUFFICIENT_WALLET` (HTTP 402). This guard applies in exactly three places: booking creation (against the booking fee), batch completion (against the production fee), and invoice payment (against the invoice total).

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and returned as whole integer cents. Wherever a calculation produces a fractional cent, the system applies the round-half-up convention — a value exactly halfway between two cents rounds up to the larger cent. Each calculation rule in §3 states precisely where rounding is applied and in what order, because for the multi-line cost calculations the order matters: per-line rounding followed by summation does not in general equal summing then rounding, and this system pins the per-line-then-sum order for food-cost estimates and actuals.

### 2.9. Storage Capacity and Slot Conservation

Shelf space is a conserved resource. Each storage unit advertises a fixed `total_slots`, and its read-only `used_slots` is the sum of `requested_slots` over the `ACTIVE` storage assignments allocated into that unit. Free capacity in a unit is therefore its total slots minus its used slots. Allocations may never drive a unit's used slots above its total slots, and the system never performs a partial allocation: a storage request either secures every requested slot or is rejected outright. When an assignment is created, every unit it touches has its `used_slots` increased by the slots allocated there; when an assignment is released, those same slots are returned. This release is a compensating action that restores the slot-conservation invariant exactly.

### 2.10. Food Safety, Temperature Excursions, and Allergen Control

Cold and frozen storage are subject to continuous temperature monitoring, and the facility's health-code obligations are encoded directly in the state of each storage unit. A unit holds a derived `compliance_status` that begins `COMPLIANT` and can move to `EXCURSION` and then `QUARANTINED` as out-of-range readings accumulate, as detailed in §3.7. A quarantined unit blocks new storage activity and drags the assignments it holds into quarantine with it. Separately, allergen control governs catering packouts: every recipe carries the union of the allergen codes of its ingredients, and a packout cannot be sealed if the allergens of what it contains intersect what the event declared it must be free of. These safety gates are not advisory — they reject the offending operation rather than merely flagging it.

### 2.11. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the same failing request always yields the same error. The order is: first, authentication of the request headers (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_UNAUTHORIZED`); then ownership for an entity-backed member operator acting on a member-owned resource (`ERR_FORBIDDEN_NOT_OWNER`); then existence of path-referenced resources, validated left to right (`ERR_NOT_FOUND`); then existence of foreign-key references carried in the body (`ERR_NOT_FOUND`); then request-body well-formedness — required fields present, enum values valid, numeric fields parseable (`ERR_INVALID_REQUEST`); then the optimistic-concurrency check on `expected_member_version` for the two guarded creates (`ERR_STALE_VERSION`); then the target resource being in the correct state for the requested transition (`ERR_INVALID_STATE`); then the acting member being `ACTIVE` for member-scoped creates (`ERR_MEMBER_NOT_ACTIVE`). The priority-6 well-formedness check covers only parse-level shape (presence, enum membership, numeric parseability); a value's *range* or *minimum* constraint — `requested_slots` ≥ 1, `planned_yield_units` ≥ 1, `actual_yield_units` ≥ 1, `order_qty` > 0, `planned_qty` > 0, and the non-negativity of monetary inputs — is a separate `ERR_INVALID_REQUEST` evaluated *after* the member-active gate (and, where a state precondition such as recipe-publication also applies to that create, after that precondition too), not as part of priority 6. Thus, for a member-scoped create where the member is non-`ACTIVE` and a value is also out of range, `ERR_MEMBER_NOT_ACTIVE` surfaces first. After these, the domain-specific business rules described throughout §3 apply — quarantine blocks, allergen conflicts, interval validity, peak-tier gating, booking overlap, station availability, recipe-publication state, stock sufficiency, batch-completion-for-packout, recipe-in-use, open-obligation blocks, storage-capacity sufficiency, and finally wallet sufficiency. The intent is that a structural problem (who you are, what exists, whether the body parses) always surfaces before a business problem (whether the action is permitted by domain rules).

## 3. Business Logic & Workflows

### 3.1. Member Registration, Wallet, and Lifecycle

The entry point to the entire system is member registration, the one action an `Anonymous` caller may take. A registrant supplies a `business_name` (the registered food-business name, a required non-empty string) and an `email` (the login address, a required non-empty string nominally unique across all members — though registration does not actively enforce uniqueness and a duplicate `email` is accepted rather than rejected), and optionally a `plan_tier`. A missing or empty `business_name` or `email` is rejected with `ERR_INVALID_REQUEST`. The plan tier is one of `STANDARD` or `PREMIUM` and defaults to `STANDARD` when omitted (any other value is `ERR_INVALID_REQUEST`); a `PREMIUM` member gains access to peak-hour station bookings and a five-percent discount on storage. Registration is also accepted when valid `X-User-ID`/`X-User-Role` headers are present (it is not restricted to header-less callers); it is simply the one operation reachable without them. On registration the new member is created with `status` set to `ACTIVE` and the three wallet figures — `wallet_balance_cents`, `lifetime_loaded_cents`, and `lifetime_charged_cents` — all initialized to 0.

A member's `status` is one of `ACTIVE`, `SUSPENDED`, or `CLOSED`, and the `FacilityManager` drives its lifecycle. Suspending a member moves it from `ACTIVE` to `SUSPENDED`; this requires the member to currently be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and is version-aware — the request may carry an `expected_member_version`, and when it is present a mismatch with the member's current `version` is rejected with `ERR_STALE_VERSION` (this concurrency check, when applicable, is evaluated before the state check). The `expected_member_version` is optional here: when it is omitted the suspend proceeds with no concurrency check. Reinstate and close are version-aware in the same optional way. Reinstating a member moves it from `SUSPENDED` back to `ACTIVE` and requires the member to currently be `SUSPENDED` (otherwise `ERR_INVALID_STATE`). A `SUSPENDED` member is frozen out of new activity: while suspended or closed, the member may not create bookings, batches, storage assignments, ingredient orders, or packouts, and any such attempt is rejected with `ERR_MEMBER_NOT_ACTIVE`. Each of suspend, reinstate, and close advances the member's `version` by one, as does a wallet top-up.

Closing a member account is terminal and moves the member from `ACTIVE` to `CLOSED`. A close is only permitted when the member has wound down its obligations: it must have no `ACTIVE` storage assignments and no `CONFIRMED` future bookings. If either obligation is still open, the close is rejected with `ERR_MEMBER_HAS_OPEN_OBLIGATIONS`. Loading funds onto the wallet — a top-up carrying an `amount_cents`, which must be a non-negative whole-cent integer (a missing, non-integer, or negative `amount_cents` is rejected with `ERR_INVALID_REQUEST`) — is available to the member operator or the facility manager and follows the wallet conservation rules of §2.7. A top-up is permitted regardless of the member's `status` (it is not gated on the member being `ACTIVE`).

### 3.2. Stations and the Booking Lifecycle

The facility manager provisions the bookable equipment as **stations**. A station has a `name` label, a `station_class` of `PREP_TABLE`, `CONVECTION_OVEN`, or `BLAST_CHILLER` (which selects its hourly rate), a `turnover_buffer_minutes` that defaults to 30 and represents the cleaning gap required between two members' bookings on that station, and a `status` of `OPEN` or `OUT_OF_SERVICE` that defaults to `OPEN`. Creating a station requires a non-empty `name` and a valid `station_class`; `turnover_buffer_minutes`, when supplied, must be a non-negative integer, and `status`, when supplied, must be one of the two valid values — any missing required field or out-of-domain value is rejected with `ERR_INVALID_REQUEST`. A station that is `OUT_OF_SERVICE` accepts no new bookings. The manager may later adjust a station's `status` or `turnover_buffer_minutes` via PATCH (any other fields in the patch body are ignored; supplying neither leaves the station unchanged, and an invalid `status` or negative `turnover_buffer_minutes` is rejected with `ERR_INVALID_REQUEST`).

A `MemberOperator` reserves time by creating a **booking**, which records the `station_id` of the reserved station and a half-open time interval defined by `start_utc` (inclusive start) and `end_utc` (exclusive end), both ISO 8601 UTC. A booking is born in `CONFIRMED` status and can end in either `CANCELLED` or `COMPLETED`. Creating a booking is the most heavily guarded operation in the system. The acting member must be `ACTIVE` (otherwise `ERR_MEMBER_NOT_ACTIVE`); the referenced station must be `OPEN` (otherwise `ERR_STATION_OUT_OF_SERVICE`); the interval must be non-empty, meaning `end_utc` is strictly later than `start_utc` (otherwise `ERR_INVALID_INTERVAL`); and the create carries `expected_member_version` for the OCC check of §2.6.

Whether a booking is a peak booking is derived at creation and stored in the read-only `is_peak` flag: a booking is a peak booking exactly when its `start_utc`, read in local hours, falls within the peak window that runs from 06:00 inclusive up to 10:00 exclusive. "Local hours" here is the hour-of-day component of `start_utc` taken directly in UTC (the facility applies no separate timezone offset): a `start_utc` whose UTC hour is 6, 7, 8, or 9 is a peak booking, and one whose UTC hour is 10 or later (or earlier than 6) is not. Peak bookings are a premium privilege — if a booking would be a peak booking but the member's `plan_tier` is not `PREMIUM`, the booking is rejected with `ERR_PEAK_REQUIRES_PREMIUM`. The reserved interval must also be free of conflicts: a booking is rejected with `ERR_BOOKING_OVERLAP` if there is any existing `CONFIRMED` or `COMPLETED` booking on the same station whose interval, expanded by the station's `turnover_buffer_minutes` of cleaning time, overlaps the new interval. In other words, a new booking must clear both the occupied time and the turnover buffer on either side of every existing reservation on that station. Concretely, for each existing booking the clear gap between the two half-open intervals is measured: the gap is negative when their occupied times overlap, zero when they abut exactly (the new interval's `start_utc` equals an existing `end_utc`, or its `end_utc` equals an existing `start_utc`), and positive otherwise. A new booking is rejected with `ERR_BOOKING_OVERLAP` whenever, against any existing booking, that gap is negative (occupied-time overlap) or strictly between 0 and the station's `turnover_buffer_minutes` (the cleaning buffer is encroached). A gap of exactly 0 (an exact abutment) is permitted, and a gap greater than or equal to `turnover_buffer_minutes` is permitted. The read-only `turnover_applied` flag on the new booking is set true exactly when the new booking abuts at least one existing `CONFIRMED` or `COMPLETED` booking on that station with a gap of exactly 0 (so the cleaning buffer must be reserved next to it); it is false otherwise — including when the nearest neighbor is separated by a gap of `turnover_buffer_minutes` or more. When `turnover_applied` is true it adds a cleaning surcharge to the fee.

The booking fee is computed at confirmation and stored read-only in `fee_cents`; its full derivation lives in §3.3. The fee is held against the member's wallet at confirmation, which requires the member's `wallet_balance_cents` to be at least the computed `fee_cents` (otherwise `ERR_INSUFFICIENT_WALLET`); confirmation then debits `wallet_balance_cents` by `fee_cents` and increases `lifetime_charged_cents` by the same amount.

Cancelling a booking is permitted only while it is `CONFIRMED` (otherwise `ERR_INVALID_STATE`) and moves it to `CANCELLED`; the cancellation refunds the member by crediting `wallet_balance_cents` by `fee_cents` and reducing `lifetime_charged_cents` by the same amount, the compensating move that restores the wallet invariant. Completing a booking is also permitted only from `CONFIRMED` (otherwise `ERR_INVALID_STATE`) and moves it to `COMPLETED`; the fee stays charged and the booking becomes eligible to roll into an invoice. The terminal states `CANCELLED` and `COMPLETED` are final.

### 3.3. Pricing a Booking

The booking fee blends a class-based hourly rate, a peak multiplier, and a possible flat cleaning surcharge. The hourly rate is selected by the station's `station_class`: a `PREP_TABLE` is billed at 1200 cents per hour, a `CONVECTION_OVEN` at 3000 cents per hour, and a `BLAST_CHILLER` at 2500 cents per hour. The peak multiplier is 1.5 when the booking is a peak booking (`is_peak` true) and 1.0 otherwise.

To compute the fee, first take the scaled base: the hourly rate multiplied by the booking's duration expressed in hours (that is, the duration in minutes divided by 60), then multiplied by the applicable peak or off-peak multiplier. Round this scaled base to whole cents using round-half-up — this single rounding is applied once, to the scaled base, before anything else is added. Then, if `turnover_applied` is true, add a flat cleaning surcharge of 800 cents; if it is false, add nothing. The result is `fee_cents`. The cleaning surcharge is a flat addition that is never multiplied by the peak factor and is never itself rounded, because it is already a whole-cent constant added after the base has been rounded.

### 3.4. Recipes and Bills of Materials

A `MemberOperator` develops products as **recipes**. A recipe records its owning `member_id`, a `name`, a `batch_yield_units` (the number of finished units a single standard batch is expected to produce, which must be at least 1), and a `version` that starts at 1. A recipe's `status` moves through `DRAFT`, `PUBLISHED`, and `RETIRED`. A new recipe is created in `DRAFT`.

While a recipe is in `DRAFT`, the operator builds out its bill of materials by adding **recipe components**. Each component is a line item recording the `recipe_id` it belongs to, the `ingredient_id` it consumes, and a `planned_qty` — the planned quantity of that ingredient, in base units, consumed per standard batch, which must be strictly greater than 0 (otherwise `ERR_INVALID_REQUEST`). Adding a component is permitted only while the recipe is in `DRAFT`; an attempt to add a component to a `PUBLISHED` or `RETIRED` recipe is rejected with `ERR_INVALID_STATE`. The `ingredient_id` must resolve to an existing ingredient (`ERR_NOT_FOUND`), and that foreign-key existence is checked before the `planned_qty` value and before the recipe-state check. An ingredient itself is a facility-managed catalog entry with a `name`, a current `unit_cost_cents` (cost per base unit, updated when an order is received), a read-only `on_hand_qty` reflecting the quantity in stock, and a list of `allergen_tags` (allergen codes such as `PEANUT`, `MILK`, `GLUTEN`, `SOY`, `EGG`) that defaults to an empty list. Creating an ingredient requires a non-empty `name` and a non-negative integer `unit_cost_cents` (a missing or invalid value is `ERR_INVALID_REQUEST`); `allergen_tags`, when supplied, must be a list. The new ingredient's `on_hand_qty` is initialized to 0.

Publishing a recipe transitions it from `DRAFT` to `PUBLISHED`. It is permitted only when the recipe is currently `DRAFT` (otherwise `ERR_INVALID_STATE`) and only when the recipe has at least one component (otherwise `ERR_RECIPE_EMPTY`). Publication computes two derived fields. The recipe's read-only `allergen_tags` is set to the union of the `allergen_tags` of every ingredient referenced by its components — the recipe inherits every allergen any of its ingredients carries. The recipe's read-only `estimated_food_cost_cents` is computed from the planned quantities, as detailed in §3.5.

The recipe lifecycle is cyclic. Revising a `PUBLISHED` recipe sends it back to `DRAFT` and increments its `version` by one, so the same recipe may loop `DRAFT → PUBLISHED → DRAFT` repeatedly, each revision producing a new version number. Revision is permitted only when the recipe is currently `PUBLISHED` (otherwise `ERR_INVALID_STATE`) and only when no `IN_PRODUCTION` batch has pinned this recipe's version (otherwise `ERR_RECIPE_IN_USE`). Retiring a recipe is terminal and moves it from `PUBLISHED` to `RETIRED`; it is permitted only when the recipe is currently `PUBLISHED` (otherwise `ERR_INVALID_STATE`) and only when no `PLANNED` or `IN_PRODUCTION` batch references the recipe (otherwise `ERR_RECIPE_IN_USE`). Retirement has no further side effects.

### 3.5. Food-Cost Estimation

The estimated food cost of a recipe is a bill-of-materials roll-up, and the order of operations is pinned: each line is rounded to whole cents first, and only then are the lines summed. For each component, take its `planned_qty`, scale it by a scale factor, multiply the scaled quantity by that ingredient's `unit_cost_cents`, and round the product to whole cents with round-half-up to produce a per-line cost. Sum all the per-line costs to obtain the estimate. Because rounding happens per line and not on the final sum, the result can differ from a sum-then-round computation, and the per-line-then-sum order is the canonical one.

This same roll-up is evaluated at two points with two different scale factors. At recipe publication the scale factor is exactly 1.0, so the estimate reflects a single standard batch, and the result is stored in the recipe's `estimated_food_cost_cents`. At batch planning the scale factor is the batch's `planned_yield_units` divided by the recipe's `batch_yield_units`, applied against the bill of materials of the pinned recipe version, and the result is stored in the batch's own `estimated_food_cost_cents`.

### 3.6. Production Batches: Planning, Starting, Completing, Scrapping

A **production batch** is a member's run of a published recipe. Planning a batch records its `member_id`, the `recipe_id` being produced, and a `planned_yield_units` (the planned number of finished units, which must be at least 1). A batch is created in `PLANNED`, and its `status` advances through `IN_PRODUCTION` and then forks to either `COMPLETED` or `SCRAPPED`. Planning requires the acting member to be `ACTIVE` (otherwise `ERR_MEMBER_NOT_ACTIVE`), the target recipe to be `PUBLISHED` (otherwise `ERR_RECIPE_NOT_PUBLISHED`), and `planned_yield_units` to be at least 1 (otherwise `ERR_INVALID_REQUEST`). At planning the batch captures `recipe_version_pinned` — the recipe's `version` at this moment — which locks the bill of materials against any later recipe revision, and it computes its `estimated_food_cost_cents` from that pinned bill of materials as described in §3.5.

Starting a batch moves it from `PLANNED` to `IN_PRODUCTION`. It is permitted only when the batch is currently `PLANNED` (otherwise `ERR_INVALID_STATE`) and only when there is enough stock on hand: for every component of the recipe, the ingredient's `on_hand_qty` must be at least the planned quantity scaled to this run — that is, the component's `planned_qty` multiplied by `planned_yield_units` divided by the recipe's `batch_yield_units`. If any ingredient falls short of its scaled demand, the start is rejected with `ERR_INSUFFICIENT_STOCK`. Once a batch is in production, its pinned recipe version is considered in use, which is what blocks a revision of that version.

Completing a batch moves it from `IN_PRODUCTION` to `COMPLETED`. It is permitted only when the batch is currently `IN_PRODUCTION` (otherwise `ERR_INVALID_STATE`). At completion the operator supplies an `actual_yield_units` (the actual count of finished units, which must be at least 1, otherwise `ERR_INVALID_REQUEST`) and optionally an `actual_components` list of `{ingredient_id, actual_qty}` entries recording what was actually consumed (when supplied it must be a list and each entry must carry both `ingredient_id` and `actual_qty`, otherwise `ERR_INVALID_REQUEST`); the `actual_yield_units` value is recorded in the batch's read-only field of the same name, which is null until completion. The actual food cost, the inventory drawdown, and the batch's stored `actual_components` all range over exactly the pinned recipe's bill-of-materials ingredients: for each BOM ingredient a supplied `actual_qty` overrides the scaled-planned default, and any `actual_components` entry naming an ingredient outside the BOM is ignored (it neither adds cost nor draws down stock). Completion computes the actual food cost (see §3.7) and the production fee (see §3.8). Because completion charges the production fee to the wallet, the member's `wallet_balance_cents` must be at least the computed `production_fee_cents` (otherwise `ERR_INSUFFICIENT_WALLET`); completion then debits `wallet_balance_cents` by `production_fee_cents` and increases `lifetime_charged_cents` by the same amount. Completion also draws down inventory: each ingredient's `on_hand_qty` is decremented by the actual quantity consumed for that ingredient, a cascade that reaches every ingredient in the bill of materials.

A batch may instead be scrapped, ending in `SCRAPPED`. Scrapping is permitted from either `PLANNED` or `IN_PRODUCTION` (in either case the batch must be in that state, otherwise `ERR_INVALID_STATE`). Scrapping levies no wallet charge and consumes no ingredients; the batch simply becomes terminal.

### 3.7. Actual Food Cost and Inventory Replenishment

When a batch completes, its actual food cost is computed from what was actually consumed, with the same per-line-then-sum rounding discipline as the estimate, plus a spoilage adder. For each line in `actual_components` — and for any bill-of-materials ingredient omitted from that list, the system defaults that line's quantity to the planned quantity scaled to this run — multiply the line's `actual_qty` by that ingredient's `unit_cost_cents`, round to whole cents with round-half-up, and sum these per-line costs into a base. Then compute spoilage as the base multiplied by the spoilage rate of five percent, rounded to whole cents with round-half-up, and add it to the base; the sum is the batch's `actual_food_cost_cents` (null until the batch is `COMPLETED`). No separate per-unit cost figure is computed or surfaced on the batch; `actual_food_cost_cents` is the only cost figure the completion produces (the implied per-unit cost is simply `actual_food_cost_cents` divided by `actual_yield_units`, but the system does not store or return it as its own field). The actual cost can diverge from the estimate captured at planning for two reasons: it uses actual quantities rather than planned ones, and it includes the five-percent spoilage adder that the estimate omits — and the ingredient `unit_cost_cents` may itself have changed if an order was received between planning and completion.

That cost movement comes from **ingredient orders**. A `MemberOperator` places a replenishment order recording its `member_id`, the `ingredient_id` being replenished, an `order_qty` (quantity in base units, which must be strictly greater than 0, otherwise `ERR_INVALID_REQUEST`), and the quoted `unit_cost_cents` for the order. Placing requires the acting member to be `ACTIVE` (otherwise `ERR_MEMBER_NOT_ACTIVE`). An order's `status` is one of `PLACED`, `RECEIVED`, or `CANCELLED`; it is born `PLACED`. Receiving an order is permitted only while it is `PLACED` (otherwise `ERR_INVALID_STATE`) and moves it to `RECEIVED`; receipt increments the ingredient's `on_hand_qty` by the `order_qty` and sets the ingredient's `unit_cost_cents` to the order's `unit_cost_cents`, which is exactly how a later batch can complete against a different cost than its estimate assumed. Cancelling an order is likewise permitted only from `PLACED` (otherwise `ERR_INVALID_STATE`) and moves it to `CANCELLED` with no inventory effect.

### 3.8. The Production Fee

Separate from food cost, the facility levies a production fee on each completed batch, charged to the member's wallet at completion. The base fee is the batch's `actual_yield_units` multiplied by a per-unit facility fee of 35 cents. Large runs earn a flat volume rebate: when `actual_yield_units` is at least 100, a flat rebate of 500 cents is subtracted from the base fee; below 100 units there is no rebate. The `production_fee_cents` is the base fee minus the applicable rebate, floored at 0 — that is, if the rebate were ever to exceed the base fee, the fee is 0 rather than a negative number.

### 3.9. Storage Assignments and Waterfall Allocation

A `MemberOperator` claims shelf space by creating a **storage assignment**, supplying its `member_id`, a `temp_class` of `DRY`, `COLD`, or `FROZEN`, the number of `requested_slots` (which must be at least 1), and the `expected_member_version` for the OCC check. The request body does not carry a `storage_unit_id`: the primary `storage_unit_id` is a derived field, set by the server to the first unit the waterfall allocation fills (any `storage_unit_id` a client includes in the body is ignored). The only required body fields are `temp_class`, `requested_slots`, and `expected_member_version`. Each storage unit is a facility-managed resource created with a required `name` (non-empty string), its own required `temp_class` (one of `DRY`/`COLD`/`FROZEN`), a required non-negative integer `total_slots` capacity, and required numeric `temp_min_c` and `temp_max_c` (the inclusive Celsius safe-temperature band); a create missing any of these or carrying an invalid value is rejected with `ERR_INVALID_REQUEST`. Its derived `used_slots` starts at 0, and its derived `compliance_status` (`COMPLIANT`) and `excursion_minutes` (0) are server-managed. An assignment's `temp_class` must match the temperature class of the units it draws from.

Creating an assignment requires the acting member to be `ACTIVE` (otherwise `ERR_MEMBER_NOT_ACTIVE`), `requested_slots` to be at least 1 (otherwise `ERR_INVALID_REQUEST`), and the version-guarded OCC check of §2.6 to pass; it also requires capacity and a clear compliance picture. The system fills the request by a **waterfall allocation** across the candidate units. The candidates are all storage units of the matching `temp_class` whose `compliance_status` is not `QUARANTINED`, considered strictly in ascending `created_at` order (the earliest-created unit fills first; ties and ordering are by creation time, never by id). Walking the candidates in that order, the system takes from each unit the smaller of its free slots (its `total_slots` minus its `used_slots`) and the slots still needed, recording a `{storage_unit_id, slots}` entry for each unit that contributes a positive amount, until the request is fully satisfied. The resulting ordered list is stored in the read-only `allocation_plan`, and the primary `storage_unit_id` is the first unit in that plan.

If the aggregate free capacity across all same-class non-quarantined units is less than `requested_slots`, the request cannot be filled and is rejected with `ERR_STORAGE_CAPACITY_EXCEEDED`; there is no partial allocation. Independently, if any same-class unit that the waterfall plan would touch is itself `QUARANTINED`, the create is refused with `ERR_UNIT_QUARANTINED`. When allocation succeeds, every touched unit's `used_slots` is incremented by the slots allocated there (a cascade across all units in the plan), and the assignment's `monthly_fee_cents` is computed per §3.10.

A storage assignment's `status` is one of `ACTIVE`, `RELEASED`, or `QUARANTINED`; it is born `ACTIVE`. Releasing an assignment is permitted only while it is `ACTIVE` (otherwise `ERR_INVALID_STATE`) and moves it to `RELEASED`, decrementing each touched unit's `used_slots` by the slots that assignment had allocated — the compensating move that restores slot conservation. An assignment may instead be dragged to `QUARANTINED` by the system when a unit in its `allocation_plan` is quarantined (see §3.7's temperature workflow below); in that case the slots are held, not freed, pending compliance release. A `ComplianceOfficer` returns a quarantined assignment to `ACTIVE` once the situation is resolved; this is permitted only when the assignment is currently `QUARANTINED` (otherwise `ERR_INVALID_STATE`) and only when the underlying storage unit's `compliance_status` is back to `COMPLIANT` (otherwise `ERR_UNIT_QUARANTINED`); the unit whose compliance is checked here is the assignment's primary `storage_unit_id` (the first entry of its `allocation_plan`).

### 3.10. Storage Pricing

A storage assignment's monthly fee is rate times slots, less a possible loyalty discount. The per-slot monthly rate is selected by the assignment's `temp_class`: `DRY` storage is 400 cents per slot per month, `COLD` storage is 700 cents per slot per month, and `FROZEN` storage is 900 cents per slot per month. The gross fee is the `requested_slots` multiplied by that per-slot rate. If the member's `plan_tier` is `PREMIUM`, a five-percent discount applies: compute the discount as the gross multiplied by five percent, rounded to whole cents with round-half-up, and subtract it from the gross. A `STANDARD` member receives no discount. The resulting `monthly_fee_cents` is the gross minus the discount, and it is what rolls into the member's monthly invoice.

### 3.11. Temperature Logging, Excursions, and Quarantine Cascade

Food safety is enforced through the stream of temperature readings recorded against each storage unit. A `ComplianceOfficer` (or the facility manager) records a **temp log** carrying the `storage_unit_id`, a `reading_c` (the Celsius reading, which must be a number), and a `reading_utc` timestamp (which must be a parseable ISO 8601 timestamp); a missing or non-numeric `reading_c`, or a missing or unparseable `reading_utc`, is rejected with `ERR_INVALID_REQUEST`. A temp log may be recorded against a unit in any `compliance_status`, including a `QUARANTINED` one. The system derives `in_range` for the reading: it is true exactly when the reading sits within the unit's safe band, that is, when `reading_c` is greater than or equal to `temp_min_c` and less than or equal to `temp_max_c`, with both bounds inclusive — a reading exactly at `temp_max_c` is in range. Each reading also carries a `certified` flag that defaults to false and becomes true only once a compliance officer certifies that specific reading; certification is a standalone audit mark with no effect on compliance state.

Readings are processed strictly in chronological order by `reading_utc`, with ties broken by `created_at` ascending, and they drive the unit's compliance posture. A storage unit's `compliance_status` is `COMPLIANT`, `EXCURSION`, or `QUARANTINED` and begins `COMPLIANT`, with a companion `excursion_minutes` that accumulates the duration of the current consecutive out-of-range run. When an in-range reading arrives, `excursion_minutes` is reset to 0, and if the unit was in `EXCURSION` it returns to `COMPLIANT`. When an out-of-range reading arrives and the unit is `COMPLIANT`, the unit moves to `EXCURSION` and the run begins with `excursion_minutes` at 0 (the first breach reading starts the run at zero). When an out-of-range reading arrives and the unit is already in `EXCURSION`, the gap in minutes between the previous out-of-range reading and this one — the elapsed seconds divided by 60 and rounded to the nearest whole minute — is added to `excursion_minutes`, which is therefore always a whole-minute integer. The whole compliance posture (`compliance_status` and `excursion_minutes`) is recomputed by replaying the unit's full set of readings in this chronological order each time a new reading is recorded, so a reading that arrives with an out-of-sequence `reading_utc` is folded into its correct chronological position.

If, after adding that gap, `excursion_minutes` strictly exceeds 120 — 120 minutes exactly is not yet a breach, only a value greater than 120 is — the unit transitions to `QUARANTINED`. Quarantining a unit cascades: every `ACTIVE` storage assignment whose `allocation_plan` touches this unit is itself moved to `QUARANTINED`, with its slots held rather than freed. A quarantined unit is cleared back to `COMPLIANT` only by a `ComplianceOfficer` certifying it compliant, which is permitted only when the unit is currently `QUARANTINED` (otherwise `ERR_INVALID_STATE`) and only when the latest temperature reading for the unit is in range (otherwise `ERR_UNIT_NOT_RECOVERED`); the "latest" reading here is the one with the greatest `reading_utc`, ties broken by the later `created_at`. Clearing resets `excursion_minutes` to 0 and returns the unit to `COMPLIANT`. Only after the unit is back to `COMPLIANT` can a compliance officer lift the quarantine on the assignments it dragged down.

### 3.12. Event Packouts and Allergen Gating

When a member assembles finished product for a catering event, it creates an **event packout** recording its `member_id`, an `event_name`, a `batch_ids` list of the production batches to pack, and an optional `allergen_free_required` list of allergen codes the event must be free of (defaulting to an empty list). A packout's `status` is one of `DRAFT`, `SEALED`, or `SHIPPED`; it is born `DRAFT`. Creating a packout requires the acting member to be `ACTIVE` (otherwise `ERR_MEMBER_NOT_ACTIVE`) and requires that every id in `batch_ids` reference a `COMPLETED` production batch owned by this member (otherwise `ERR_BATCH_NOT_COMPLETED`). At creation the system computes two read-only roll-ups over the packed batches: `combined_allergen_tags`, the union of the `allergen_tags` of the recipes behind the packed batches, and `packed_unit_count`, the sum of `actual_yield_units` across those `COMPLETED` batches.

Sealing a packout is the safety gate. It is permitted only while the packout is `DRAFT` (otherwise `ERR_INVALID_STATE`) and only when the packout's `combined_allergen_tags` shares no allergen code with the `allergen_free_required` list — the two sets must be disjoint. If they intersect in even one code, the seal is rejected with `ERR_ALLERGEN_CONFLICT`; otherwise the packout moves to `SEALED` and its figures are locked. Shipping moves a `SEALED` packout to the terminal `SHIPPED` state and is permitted only from `SEALED` (otherwise `ERR_INVALID_STATE`).

### 3.13. Monthly Invoicing

The `FacilityManager` settles a member's account by generating an **invoice** for a billing period bounded by `period_start_utc` (inclusive) and `period_end_utc` (exclusive); the period must be non-empty, with `period_end_utc` strictly later than `period_start_utc` (otherwise `ERR_INVALID_INTERVAL`). An invoice's `status` runs `DRAFT`, `ISSUED`, `PAID`; it is born `DRAFT` with all figures computed at generation.

Generation rolls up three subtotals over the member's activity. The `booking_subtotal_cents` is the sum of `fee_cents` over the member's `COMPLETED` bookings whose `end_utc` falls in the half-open period (at or after `period_start_utc` and before `period_end_utc`). The `storage_subtotal_cents` is the sum of `monthly_fee_cents` over the member's `ACTIVE` storage assignments at the moment of generation. The `production_subtotal_cents` is the sum of `production_fee_cents` over the member's `COMPLETED` batches whose completion time falls in the same half-open period. The `subtotal_cents` is the sum of those three subtotals.

From the subtotal the system derives a loyalty discount and a platform fee in a pinned order. The `loyalty_discount_cents` is keyed on which tier the subtotal reaches: if the subtotal is at least 50000 cents the discount rate is ten percent; otherwise if the subtotal is at least 20000 cents the rate is five percent; otherwise there is no discount. The discount is the subtotal multiplied by that rate, rounded to whole cents with round-half-up. The `platform_fee_cents` is a three-percent facility fee computed on the subtotal before any discount, namely the subtotal multiplied by three percent, rounded to whole cents with round-half-up. The evaluation order is fixed: first the subtotal, then the discount keyed on the subtotal tier, then the platform fee on the same subtotal, then the total. The `total_cents` is the subtotal minus the loyalty discount plus the platform fee. This invoice figure is a period rollup of historical completed items and is distinct from the live wallet ledger, which is a chronological running balance; the two describe the same money through different algorithms.

Issuing an invoice moves it from `DRAFT` to `ISSUED` and locks its figures against any recomputation; it is permitted only from `DRAFT` (otherwise `ERR_INVALID_STATE`). Paying an issued invoice moves it from `ISSUED` to `PAID`; it is permitted only from `ISSUED` (otherwise `ERR_INVALID_STATE`) and only when the member's `wallet_balance_cents` is at least the invoice `total_cents` (otherwise `ERR_INSUFFICIENT_WALLET`). Payment debits `wallet_balance_cents` by `total_cents` and increases `lifetime_charged_cents` by the same amount.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (registering a member, creating a station, placing an order, planning a batch, and the like) return `201 Created`. Operations that modify an existing resource — every state transition, every release, every certify, every issue or pay — return `200 OK`. All endpoints are mounted at the root path.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members/register` | Register a new member | Anonymous |
| GET | `/members` | List members | FacilityManager |
| GET | `/members/{id}` | Get a member | MemberOperator, FacilityManager |
| POST | `/members/{id}/wallet/top-ups` | Load prepaid funds onto a member wallet | MemberOperator, FacilityManager |
| POST | `/members/{id}/suspend` | Suspend a member | FacilityManager |
| POST | `/members/{id}/reinstate` | Reinstate a suspended member | FacilityManager |
| POST | `/members/{id}/close` | Close a member account | FacilityManager |
| POST | `/stations` | Create a station | FacilityManager |
| GET | `/stations` | List stations | MemberOperator, FacilityManager |
| GET | `/stations/{id}` | Get a station | MemberOperator, FacilityManager |
| PATCH | `/stations/{id}` | Update station status or turnover buffer | FacilityManager |
| GET | `/stations/{id}/bookings` | List bookings on a station | MemberOperator, FacilityManager |
| POST | `/members/{id}/bookings` | Create a station booking | MemberOperator |
| GET | `/members/{id}/bookings` | List a member's bookings | MemberOperator, FacilityManager |
| GET | `/members/{id}/bookings/{bid}` | Get a booking | MemberOperator, FacilityManager |
| POST | `/members/{id}/bookings/{bid}/cancel` | Cancel a booking and refund the wallet | MemberOperator |
| POST | `/members/{id}/bookings/{bid}/complete` | Mark a booking completed | MemberOperator, FacilityManager |
| POST | `/storage-units` | Create a storage unit | FacilityManager |
| GET | `/storage-units` | List storage units | MemberOperator, FacilityManager, ComplianceOfficer |
| GET | `/storage-units/{id}` | Get a storage unit | MemberOperator, FacilityManager, ComplianceOfficer |
| POST | `/storage-units/{id}/temp-logs` | Record a temperature reading | ComplianceOfficer, FacilityManager |
| GET | `/storage-units/{id}/temp-logs` | List temp readings for a unit | ComplianceOfficer, FacilityManager |
| POST | `/storage-units/{id}/temp-logs/{logid}/certify` | Certify a temp reading | ComplianceOfficer |
| POST | `/storage-units/{id}/certify-compliant` | Clear a quarantined unit back to COMPLIANT | ComplianceOfficer |
| POST | `/members/{id}/storage-assignments` | Claim storage slots | MemberOperator |
| GET | `/members/{id}/storage-assignments` | List a member's storage assignments | MemberOperator, FacilityManager |
| GET | `/storage-units/{id}/storage-assignments` | List assignments touching a unit | MemberOperator, FacilityManager, ComplianceOfficer |
| GET | `/members/{id}/storage-assignments/{sid}` | Get a storage assignment | MemberOperator, FacilityManager |
| POST | `/members/{id}/storage-assignments/{sid}/release` | Release storage and free slots | MemberOperator |
| POST | `/members/{id}/storage-assignments/{sid}/release-quarantine` | Return a quarantined assignment to ACTIVE | ComplianceOfficer |
| POST | `/ingredients` | Create an ingredient | FacilityManager |
| GET | `/ingredients` | List ingredients | MemberOperator, FacilityManager |
| GET | `/ingredients/{id}` | Get an ingredient | MemberOperator, FacilityManager |
| POST | `/members/{id}/recipes` | Create a recipe | MemberOperator |
| GET | `/members/{id}/recipes` | List a member's recipes | MemberOperator, FacilityManager |
| GET | `/members/{id}/recipes/{rid}` | Get a recipe | MemberOperator, FacilityManager |
| POST | `/members/{id}/recipes/{rid}/components` | Add a BOM component to a DRAFT recipe | MemberOperator |
| GET | `/members/{id}/recipes/{rid}/components` | List BOM components | MemberOperator, FacilityManager |
| GET | `/ingredients/{id}/recipe-components` | List BOM lines using an ingredient | MemberOperator, FacilityManager |
| POST | `/members/{id}/recipes/{rid}/publish` | Publish a DRAFT recipe | MemberOperator |
| POST | `/members/{id}/recipes/{rid}/revise` | Send a PUBLISHED recipe back to DRAFT | MemberOperator |
| POST | `/members/{id}/recipes/{rid}/retire` | Retire a recipe | MemberOperator |
| POST | `/members/{id}/batches` | Plan a production batch | MemberOperator |
| GET | `/members/{id}/batches` | List a member's batches | MemberOperator, FacilityManager |
| GET | `/members/{id}/recipes/{rid}/batches` | List batches against a recipe | MemberOperator, FacilityManager |
| GET | `/members/{id}/batches/{bid}` | Get a batch | MemberOperator, FacilityManager |
| POST | `/members/{id}/batches/{bid}/start` | Start production | MemberOperator |
| POST | `/members/{id}/batches/{bid}/complete` | Complete production and record actuals | MemberOperator |
| POST | `/members/{id}/batches/{bid}/scrap` | Scrap a batch | MemberOperator |
| POST | `/members/{id}/ingredient-orders` | Place a replenishment order | MemberOperator |
| GET | `/members/{id}/ingredient-orders` | List a member's orders | MemberOperator, FacilityManager |
| GET | `/ingredients/{id}/ingredient-orders` | List orders for an ingredient | MemberOperator, FacilityManager |
| POST | `/members/{id}/ingredient-orders/{oid}/receive` | Receive an order; update stock and cost | MemberOperator |
| POST | `/members/{id}/ingredient-orders/{oid}/cancel` | Cancel a placed order | MemberOperator |
| POST | `/members/{id}/packouts` | Create an event packout | MemberOperator |
| GET | `/members/{id}/packouts` | List a member's packouts | MemberOperator, FacilityManager |
| GET | `/members/{id}/packouts/{pid}` | Get a packout | MemberOperator, FacilityManager |
| POST | `/members/{id}/packouts/{pid}/seal` | Seal a packout | MemberOperator |
| POST | `/members/{id}/packouts/{pid}/ship` | Ship a sealed packout | MemberOperator |
| POST | `/members/{id}/invoices` | Generate a draft invoice for a period | FacilityManager |
| GET | `/members/{id}/invoices` | List a member's invoices | MemberOperator, FacilityManager |
| GET | `/members/{id}/invoices/{iid}` | Get an invoice | MemberOperator, FacilityManager |
| POST | `/members/{id}/invoices/{iid}/issue` | Issue (lock) an invoice | FacilityManager |
| POST | `/members/{id}/invoices/{iid}/pay` | Pay an issued invoice from wallet | FacilityManager |
| GET | `/bookings/{id}` | Get a booking by id | MemberOperator, FacilityManager |
| GET | `/bookings` | List/filter bookings | MemberOperator, FacilityManager |
| GET | `/storage-assignments/{id}` | Get a storage assignment by id | MemberOperator, FacilityManager, ComplianceOfficer |
| GET | `/storage-assignments` | List/filter storage assignments | MemberOperator, FacilityManager, ComplianceOfficer |
| GET | `/recipes/{id}` | Get a recipe by id | MemberOperator, FacilityManager |
| GET | `/recipes` | List/filter recipes | MemberOperator, FacilityManager |
| GET | `/recipe-components/{id}` | Get a recipe component by id | MemberOperator, FacilityManager |
| GET | `/recipe-components` | List/filter recipe components | MemberOperator, FacilityManager |
| GET | `/batches/{id}` | Get a production batch by id | MemberOperator, FacilityManager |
| GET | `/batches` | List/filter batches | MemberOperator, FacilityManager |
| GET | `/temp-logs/{id}` | Get a temp log by id | ComplianceOfficer, FacilityManager |
| GET | `/temp-logs` | List/filter temp logs | ComplianceOfficer, FacilityManager |
| GET | `/ingredient-orders/{id}` | Get an ingredient order by id | MemberOperator, FacilityManager |
| GET | `/ingredient-orders` | List/filter ingredient orders | MemberOperator, FacilityManager |
| GET | `/packouts/{id}` | Get a packout by id | MemberOperator, FacilityManager |
| GET | `/packouts` | List/filter packouts | MemberOperator, FacilityManager |
| GET | `/invoices/{id}` | Get an invoice by id | MemberOperator, FacilityManager |
| GET | `/invoices` | List/filter invoices | MemberOperator, FacilityManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_MEMBER_HAS_OPEN_OBLIGATIONS` | 409 |
| `ERR_STATION_OUT_OF_SERVICE` | 409 |
| `ERR_PEAK_REQUIRES_PREMIUM` | 409 |
| `ERR_BOOKING_OVERLAP` | 409 |
| `ERR_RECIPE_EMPTY` | 409 |
| `ERR_RECIPE_NOT_PUBLISHED` | 409 |
| `ERR_RECIPE_IN_USE` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_BATCH_NOT_COMPLETED` | 409 |
| `ERR_ALLERGEN_CONFLICT` | 409 |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 409 |
| `ERR_UNIT_QUARANTINED` | 409 |
| `ERR_UNIT_NOT_RECOVERED` | 409 |
| `ERR_INSUFFICIENT_WALLET` | 402 |
| `ERR_VALIDATION` | 422 |

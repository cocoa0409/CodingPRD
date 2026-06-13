# Butcher Shop & Custom Meat Counter API — Product Requirements Document

## 1. Introduction

A neighborhood butcher shop runs on a deceptively complex set of overlapping workflows. The case must be tracked by cut and by weight; a customer's request for "two ribeyes, about a pound and a half each" turns into a custom-cut order whose final price cannot be known until the meat is actually weighed on the scale. Holiday seasons bring a wave of dated pre-orders that must be reserved against a finite production capacity. Whole-animal shares are sold by the half and the quarter, sausage is produced in recipe batches that consume trim from several lots at once, premium cuts spend weeks dry-aging in temperature-controlled lockers, and a single out-of-band thermometer reading can put a whole locker — and every cut aging inside it — into quarantine.

This API is the system of record that unifies those workflows. It governs inventory lots tracked to the gram, a dual-variant pricing engine that distinguishes the *estimated* price quoted from ordered weight at order time from the *final* price billed from the actual catch weight after shrink, holiday-window capacity quotas, fractional animal-share claims with refundable deposits, sausage batch production with yield shrink, and an append-only food-safety temperature log whose excursions cascade through lockers into aging lots. The design goal is a single source of truth where weight, money, and food-safety posture all stay reconciled as events occur, so that staff can take an order, cut it, age a roast, or pull a holiday pre-order without ever guessing at a balance, a remaining weight, or a safety state.

The intended operators are the front counter, the back of house, the shift manager who owns configuration and exception handling, the food-safety inspector, and the customers themselves, each acting through a constrained set of operations described below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across the entire API. Unless a later business-logic subsection narrows or overrides a behavior for a specific workflow, the rules here are in force everywhere.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they act. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `Customer`, `CounterClerk`, `Butcher`, `ShiftManager`, and `SafetyOfficer`.

The `Customer` role is entity-backed. When `X-User-Role` is `Customer`, the supplied `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare that resource's `customer_id` to `X-User-ID`. Concretely, a `Customer` may cancel an order or a share claim only when the order's or claim's `customer_id` equals `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The other four roles are operator roles whose identity is opaque. When `X-User-Role` is `CounterClerk`, `Butcher`, `ShiftManager`, or `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

The roles partition the work of the shop. A `CounterClerk` is front-counter staff: they register customers, take and confirm orders, place claims and orders on behalf of a customer, and cancel undrawn orders. A `Butcher` is back-of-house: they receive lots, run aging, draw and short order lines, fill orders, break down shares, and run sausage batches. A `ShiftManager` owns configuration and exceptions: pricing policy, cut types, lockers, holiday windows, quarantine release, lot discard, and share cancellation, and may also advance the test clock. A `SafetyOfficer` is the food-safety inspector, whose sole write operation is appending temperature readings (which may quarantine a locker). The precise operation-to-role mapping appears in the §4 endpoint table; the authorization checks above are evaluated before any business rule.

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0. Unless a specific endpoint says otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every primary resource — `Customer`, `CutType`, `PricingPolicy`, `InventoryLot`, `DryAgeLocker`, `AnimalShare`, `ShareClaim`, `CustomOrder`, `OrderLine`, `LotDraw`, `SausageBatch`, `BatchInput`, and `HolidayWindow` — carries a system-managed set of fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording first creation; `updated_at` is an ISO 8601 UTC timestamp recording the most recent modification; and `version` is an integer that starts at 1 and increments by one on every mutation of the resource. These four fields are present on all of the entities just listed.

Two append-only log entities are the exception. `TempReading` rows and — by their immutable nature — log entries that are never edited after creation carry only `id` and `created_at`; they do **not** carry `updated_at` and do **not** carry `version`. Specifically, a `TempReading` has only `id` and `created_at` among the system fields. All other entities, including the junction-style `LotDraw` and `BatchInput`, carry the full set of `id`, `created_at`, `updated_at`, and `version`.

Whenever a derived or computed field changes on a resource — for example `remaining_weight_g` on an `InventoryLot`, `occupied_g` on a `DryAgeLocker`, `committed_g` on a `HolidayWindow`, `claimed_fraction_x4` and `remaining_carcass_g` on an `AnimalShare`, or `store_credit_cents` on a `Customer` — that change is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Nested Resource Retrieval and Existence Checks

Several paths address a child resource under a parent (for example, temperature readings under a locker, or order lines under an order). When a path names more than one resource, the system validates existence left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource. The same existence rule applies to foreign keys referenced in a request body: if a payload names a `cut_type_id`, `locker_id`, `animal_share_id`, `customer_id`, `inventory_lot_id`, `holiday_window_id`, `source_share_id`, `output_cut_type_id`, or any other reference that does not resolve, the request is rejected with `ERR_NOT_FOUND`. Existence is checked after authentication and authorization but before deeper business rules.

### 2.6. Weight, Money, and Rounding Conventions

All weights in the system are integer grams; all money is integer cents. There are no fractional grams or fractional cents stored anywhere. Where a calculation produces a non-integer intermediate value, the rule that governs it states exactly how the value is reduced to an integer.

Two reduction methods are used and must not be confused. **Round half up** is used for monetary results: the value is rounded to the nearest whole cent, and a value exactly halfway between two cents rounds up to the larger cent. **Floor** is used for weight results that must not over-report available product: the value is truncated down to the next-lower whole gram. The pricing rules in §3 apply round-half-up at the per-line level and only then sum lines into an order total; the weight rules (billable grams after shrink, remaining carcass grams, sausage yield) apply floor. A configuration field that holds a rate or fraction — such as a shrink percentage or a discount percentage — preserves the precision supplied at input and is not rounded.

### 2.7. Cascading Food-Safety Posture

Food-safety state propagates downward through a strict chain, and this is the system's most consequential cross-cutting behavior. A temperature reading that falls outside a locker's safe band drives the locker into quarantine; quarantine in turn holds every cut currently aging inside that locker; and a held cut cannot be drawn, completed, or otherwise advanced until the locker is released. The full mechanics of the excursion chain, the quarantine cascade, and the release cascade are described in §3, but the principle is system-wide: whenever a parent's posture changes, the server automatically transitions the affected children in the same operation, refreshing each touched resource's `updated_at` and incrementing its `version`, without requiring a separate client request against each child.

### 2.8. Derived-Field Reconciliation

Several fields are never written directly by a client; they are reconciled by the server from the underlying records every time those records change. An `InventoryLot`'s `remaining_weight_g` is its `received_weight_g` minus the sum of `weight_g` over its committed (non-reverted) draws, recomputed on every draw and every reversal. A `DryAgeLocker`'s `occupied_g` is the sum of `received_weight_g` over the lots currently aging inside it, recomputed whenever a lot starts or stops aging. A `HolidayWindow`'s `committed_g` is the sum of ordered grams over its live holiday orders, recomputed on placement and cancel. An `AnimalShare`'s `claimed_fraction_x4` and `remaining_carcass_g` are reconciled on every claim and cancel. Because these are derived, a client must never be required to supply them on input, and the server is the sole authority for their values.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent resource's `version`, and only these two.

Drawing an order line's catch weight from a lot requires the request to carry `expected_inventory_lot_version`, which must equal the target `InventoryLot`'s current `version`. A draw legitimately reduces a lot's `remaining_weight_g` and bumps its `version`; if another writer (a different order line, or a sausage batch reservation) has advanced the lot's `version` since the acting client last read the lot, the client's view is stale and the grams it expected to commit may no longer be available. In that case the draw is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). This field is mandatory on the draw operation.

Releasing a quarantined locker requires the request to carry `expected_dry_age_locker_version`, which must equal the target `DryAgeLocker`'s current `version`. A subsequent out-of-band reading, or another release attempt, bumps the locker's `version`; releasing against a stale view would resume aging on lots that a newer excursion may have re-held. A mismatch is rejected with `ERR_STALE_LOCKER_VERSION` (HTTP 412), and this field is mandatory on the release operation.

No other endpoint takes a version field, and no other endpoint performs an OCC check.

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed order so that the returned error is deterministic. First, authentication of the headers (`ERR_UNAUTHENTICATED`). Second, role authorization for the operation (`ERR_FORBIDDEN_ROLE`). Third, for the two customer-owned cancel operations, resource ownership (`ERR_NOT_RESOURCE_OWNER`). Fourth, existence of every path and foreign-key resource (`ERR_NOT_FOUND`). Fifth, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). After these gatekeeping checks come the business-specific rules described in §3 — lot availability, locker quarantine, aging completion, holiday cutoffs, cut-type matching, grind requirements, share over-commitment, locker capacity, lot weight, holiday capacity, and the two stale-version checks — and finally, lowest in priority, the generic request-shape check (`ERR_INVALID_REQUEST`, HTTP 400) for a missing required field, a wrong type, an enum value outside its allowed set, or a number outside its allowed range. Where §3 describes a workflow with multiple business checks, the relative ordering stated there governs which error surfaces first.

## 3. Business Logic & Workflows

### 3.1. Configuration: Customers, Cut Types, and the Active Pricing Policy

Before any meat moves, the shop is configured. A customer is registered with a `full_name` and a `phone` (used for pre-order pickup notification), and an optional `loyalty_tier` which is one of `STANDARD`, `PREFERRED`, or `WHOLESALE` and defaults to `STANDARD` when omitted. Every new customer starts with a `store_credit_cents` balance of 0; store credit is a refundable balance, credited when deposits are refunded and when an overcharge is corrected, and it is the destination for every refund described later in this document. Registration is performed by front-counter staff or the manager. Fetching a customer returns the current `store_credit_cents` along with the rest of the record.

A cut type is the catalog entry for a kind of meat. It is created by the manager with a `code` (a short cut code such as RIBEYE or GROUND_CHUCK, unique across all cut types, written in uppercase alphanumerics and underscores), a `species` which is one of `BEEF`, `PORK`, `LAMB`, or `POULTRY`, and a `base_price_cents_per_kg` which is the list price per kilogram in cents before any tier discount or shrink and must be at least 1. Two booleans tune downstream behavior: `is_grind` (defaulting to false) marks a cut produced by grinding, which selects the grind shrink rate at billing time, and `requires_dry_age` (defaulting to false) marks a cut whose lots must complete dry-aging before they can be sold. Cut types can be fetched individually or listed, optionally filtered by `species`.

Pricing is governed by a single active `PricingPolicy`. The manager creates a policy by supplying `shrink_pct_whole_cut` and `shrink_pct_grind` (the fractional shrink applied to whole-cut and to grind catch weights respectively — for example 0.04 means four percent — each at least 0 and strictly below 1), `preferred_discount_pct` and `wholesale_discount_pct` (the discount fractions for the `PREFERRED` and `WHOLESALE` tiers, each at least 0 and below 1), `bulk_threshold_g` (the catch-weight grams at or above which a bulk rate begins to apply, at least 1), and `bulk_extra_discount_pct` (the additional discount fraction applied to the portion at or above the bulk threshold, at least 0 and below 1). A policy carries an `is_active` flag. Creating a new policy activates it: the server sets `is_active` to true on the new policy and sets `is_active` to false on whichever policy was previously active, so that exactly one policy is ever active. All pricing in §3.4 reads from the active policy.

### 3.2. Receiving Inventory and the Dry-Age Lifecycle

A `Butcher` or the manager receives meat into the case as an `InventoryLot`. Receiving takes a `cut_type_id` naming the cut the lot holds, a `received_weight_g` in grams (at least 1), an optional `aging_target_days` (the number of days the lot must age before it may return to sale, at least 0, defaulting to 0), and an optional `source_share_id`. The `source_share_id` is set only when the lot was broken out of a whole-animal share, otherwise it is null. On receipt the server initializes `remaining_weight_g` to `received_weight_g` and sets `lot_status` to `AVAILABLE`. A lot's `lot_status` is one of `AVAILABLE`, `AGING`, `ON_HOLD`, `DEPLETED`, or `DISCARDED`, with `DEPLETED` and `DISCARDED` terminal. Lots can be fetched individually (returning `remaining_weight_g` and `lot_status`) or listed with filters by `cut_type_id`, `locker_id`, `source_share_id`, or `lot_status`.

Dry-aging moves a lot through a locker. A locker is created by the manager with a `name` (a label such as LOCKER-A, unique across lockers), a `capacity_g` (maximum grams of aging product, at least 1), and a safe temperature band defined by `min_temp_c` and `max_temp_c` in Celsius, where the maximum must be at least the minimum. A new locker has `locker_status` of `OPERATIONAL` (the alternative is `QUARANTINED`) and `occupied_g` of 0; it also carries a `last_excursion_at` timestamp, null until the first quarantining reading. A locker is fetched returning its `occupied_g` and `locker_status`.

A `Butcher` starts aging by moving an `AVAILABLE` lot into a locker, supplying the `locker_id`; this advances the lot `AVAILABLE → AGING`. Four conditions must hold. The lot's cut type must have `requires_dry_age` set to true. The target locker must be `OPERATIONAL`. The lot must be untouched — its `remaining_weight_g` must equal its `received_weight_g`, meaning no draws have been taken. And the locker must have room: the locker's current `occupied_g` plus the lot's `received_weight_g` must be less than or equal to the locker's `capacity_g`, a check that is inclusive at equality, so a lot that exactly fills the remaining space is accepted. If that capacity check fails, the request is rejected with `ERR_LOCKER_OVER_CAPACITY` (HTTP 409). On success the server sets the lot's `locker_id` to the target locker, sets `aging_started_at` to the current UTC time, and recomputes the locker's `occupied_g` by adding the lot's `received_weight_g`.

Aging completes when a `Butcher` returns the lot to the case, advancing `AGING → AVAILABLE`. Two conditions apply. The lot's locker must be `OPERATIONAL` — completing aging on a lot whose locker is quarantined is rejected with `ERR_LOCKER_QUARANTINED` (HTTP 409). Because the quarantine cascade transitions a held lot `AGING → ON_HOLD` without clearing its `locker_id`, "a lot whose locker is quarantined" is necessarily `ON_HOLD` rather than `AGING`; this quarantined-locker check is therefore evaluated ahead of the generic state gate, so that completing aging on an `ON_HOLD` lot whose `locker_id` still points to a `QUARANTINED` locker surfaces `ERR_LOCKER_QUARANTINED` rather than `ERR_INVALID_STATE`. (An `ON_HOLD` lot whose locker is no longer quarantined, and any other lot that is not `AGING`, still falls to the generic `ERR_INVALID_STATE` state gate.) And enough time must have elapsed: the number of whole days between `aging_started_at` and the current clock must be at least the lot's `aging_target_days`; if too little time has passed the request is rejected with `ERR_AGING_NOT_COMPLETE` (HTTP 409). On success the server clears the lot's `locker_id` and recomputes the locker's `occupied_g` by subtracting the lot's `received_weight_g`.

### 3.3. Temperature Excursions and the Quarantine Cascade

Food safety is enforced through an append-only temperature log. A `SafetyOfficer` appends a reading to a locker by supplying a `temp_c` (the measured Celsius temperature) and a `reading_at` (the client-supplied UTC timestamp at which it was taken). The reading also carries the `locker_id` of the locker it belongs to. The server computes `in_band`, which is true exactly when the measured temperature is greater than or equal to the locker's `min_temp_c` and less than or equal to its `max_temp_c` at the time of logging, and `triggered_quarantine`, which is true exactly when this reading is the one that drove the locker from `OPERATIONAL` to `QUARANTINED`. Readings are immutable once written and can be listed for a locker (optionally filtered by `in_band`) or fetched individually.

An out-of-band reading — one whose `temp_c` is strictly below `min_temp_c` or strictly above `max_temp_c` — is the first hop of the excursion cascade. It drives the locker `OPERATIONAL → QUARANTINED`, sets the locker's `last_excursion_at` to that reading's `reading_at`, and sets the reading's `triggered_quarantine` to true. As the second hop, the same operation cascades to the locker's contents: every `InventoryLot` whose `locker_id` is this locker and whose `lot_status` is `AGING` is transitioned `AGING → ON_HOLD` in the same operation, with each held lot's `version` and `updated_at` refreshed. A lot that is `ON_HOLD` is unavailable for draws.

Releasing a locker reverses the posture. The manager releases a `QUARANTINED` locker, which must carry `expected_dry_age_locker_version` matching the locker's current `version` as described in §2.9; a mismatch is rejected with `ERR_STALE_LOCKER_VERSION` (HTTP 412). On success the locker transitions `QUARANTINED → OPERATIONAL`, its `version` is incremented by one, and the release cascades to its contents: every `InventoryLot` whose `locker_id` is this locker and whose `lot_status` is `ON_HOLD` is transitioned `ON_HOLD → AGING`. A resumed lot keeps its original `aging_started_at`, so the time already spent aging is preserved.

A held lot that will not be sold can instead be discarded by the manager, advancing the lot `ON_HOLD → DISCARDED`. Discarding clears the lot's `locker_id`, recomputes the locker's `occupied_g` by subtracting the lot's `received_weight_g`, and sets the lot's `remaining_weight_g` to 0. A lot that runs to zero remaining weight through draws instead bubbles `AVAILABLE → DEPLETED` automatically the moment a committed draw brings its `remaining_weight_g` to 0; a depleted lot can no longer be drawn from.

### 3.4. Pricing: The Estimated and Final Variants

Pricing runs in two variants that share a structure but differ in their inputs, and keeping them distinct is essential because the shop quotes one number and bills another.

The **estimated** variant prices an order line at the moment the order is placed, using the line's `ordered_weight_g` and applying **no shrink**. The computation reads the line's cut type and the active pricing policy and the ordering customer's `loyalty_tier`. First a per-gram base rate is derived by dividing the cut's `base_price_cents_per_kg` by 1000, since there are 1000 grams in a kilogram. A tier discount fraction is selected: 0 for a `STANDARD` customer, the policy's `preferred_discount_pct` for a `PREFERRED` customer, and the policy's `wholesale_discount_pct` for a `WHOLESALE` customer. The grams are then split around the bulk threshold. If the line's `ordered_weight_g` is greater than or equal to the policy's `bulk_threshold_g`, the grams from the threshold value upward (that is, the ordered grams minus the bulk threshold) are the bulk portion and receive the bulk treatment, while the remaining grams are the normal portion; the threshold boundary is inclusive, so the gram at exactly the threshold counts as bulk. The normal portion is priced as its grams times the per-gram rate times one-minus-the-tier-fraction. The bulk portion is priced as its grams times the per-gram rate times one-minus-the-tier-fraction and then additionally times one-minus-the-`bulk_extra_discount_pct`, so the bulk discount stacks multiplicatively on top of the tier discount and applies only to the bulk grams. The two parts are summed and rounded half up to whole cents to produce the line's `est_line_cents`. If `ordered_weight_g` is below the bulk threshold, the whole line is simply its grams times the per-gram rate times one-minus-the-tier-fraction, rounded half up. An order's `estimated_total_cents` is the sum of `est_line_cents` over its lines, summed after each line is individually rounded.

The **final** variant prices an order line at the moment it is drawn, using the actual `catch_weight_g` weighed on the scale and applying shrink *before* pricing. The shrink fraction is the policy's `shrink_pct_grind` if the line's cut has `is_grind` true, otherwise the policy's `shrink_pct_whole_cut`. Billable grams are the catch weight times one-minus-the-shrink-fraction, floored to a whole number of grams. From there the computation is identical in shape to the estimate: the same per-gram base rate, the same tier-fraction selection by `loyalty_tier`, and the same split around `bulk_threshold_g` — but applied to the billable (post-shrink) grams. If the billable grams are at least the bulk threshold, the grams from the threshold upward are the bulk portion priced with the stacked bulk discount and the remainder is the normal portion, otherwise the whole billable amount is priced at the normal tier rate; the result is rounded half up to whole cents to produce the line's `final_line_cents`. An order's `final_total_cents` is the sum of `final_line_cents` over its drawn lines, each rounded before summing. A line that is shorted contributes 0 cents to the final total.

### 3.5. The Custom Order Lifecycle: Placement, Confirmation, Fill, and Cancellation

A custom order is placed by a customer or by a clerk on the customer's behalf. Placement supplies the `customer_id`, an `order_kind` of either `STANDARD` or `HOLIDAY`, and the order's `lines`; a `STANDARD` order fills immediately from the case, while a `HOLIDAY` order is a dated pre-order against a window's capacity and additionally supplies a `holiday_window_id` and a `pickup_date` (the holiday pickup day). For a `STANDARD` order both `holiday_window_id` and `pickup_date` are null. Each entry in `lines` becomes an `OrderLine` carrying its parent's `custom_order_id`, a `cut_type_id` for the requested cut, and an `ordered_weight_g` (the requested grams, at least 1). On placement the server creates the order line rows, computes each line's `est_line_cents` by the estimated variant, and sets the order's `estimated_total_cents` to their sum. A line starts with `line_status` of `PENDING` (later `DRAWN` or `SHORTED`); the order starts with `order_status` of `PLACED`, and its `final_total_cents` is null until the order is filled. An order is one of `PLACED`, `CONFIRMED`, `FILLED`, `SHORT_FILLED`, or `CANCELLED`, with the last three terminal.

Holiday placement carries extra obligations described in §3.6 (the deposit and the capacity reservation). For a `STANDARD` order the order's `deposit_cents` is 0; for a `HOLIDAY` order it is computed as described there and charged on placement.

A `CounterClerk` confirms a placed order, advancing `PLACED → CONFIRMED`; this locks the order so that no new lines may be added. Confirmation requires the order to have at least one order line, and for a holiday order it requires the current clock to be at or before the window's `cutoff_at`, failing which the confirmation is rejected with `ERR_WINDOW_CUTOFF_PASSED` (HTTP 422).

Once an order is `CONFIRMED`, a `Butcher` fills each line. Drawing a line (advancing the line `PENDING → DRAWN`) supplies the `drawn_lot_id` of the lot to cut from, the `catch_weight_g` actually weighed, and the `expected_inventory_lot_version` for the OCC check. Several conditions are checked in order: the parent order must be `CONFIRMED`; the target lot must exist; the lot must be `AVAILABLE` — drawing from a lot that is `AGING`, `ON_HOLD`, `DEPLETED`, or `DISCARDED` is rejected with `ERR_LOT_NOT_AVAILABLE` (HTTP 409), and the specific case of an `ON_HOLD` lot whose locker is quarantined surfaces as `ERR_LOCKER_QUARANTINED` (HTTP 409); the lot's `cut_type_id` must equal the line's `cut_type_id`, or the draw is rejected with `ERR_CUT_TYPE_MISMATCH` (HTTP 422); the lot's `remaining_weight_g` must be at least the supplied `catch_weight_g`, or the draw is rejected with `ERR_INSUFFICIENT_LOT_WEIGHT` (HTTP 409); and `expected_inventory_lot_version` must match the lot's current `version`, or the draw is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). On a successful draw the server creates a `COMMITTED` `LotDraw` for `catch_weight_g`, reduces the lot's `remaining_weight_g` by that amount, increments the lot's `version`, records the line's `catch_weight_g` and `drawn_lot_id`, computes the line's `final_line_cents` by the final variant, and — if the lot's `remaining_weight_g` has reached 0 — bubbles the lot `AVAILABLE → DEPLETED`.

When no lot can satisfy a line, a `Butcher` shorts it, advancing the line `PENDING → SHORTED`; this requires the parent order to be `CONFIRMED` and sets the line's `final_line_cents` to 0, excluding it from the final total.

Filling the order is the fork. A `Butcher` finalizes a `CONFIRMED` order, and the outcome depends on the lines. If **every** order line is `DRAWN`, the order advances `CONFIRMED → FILLED`: the server recomputes `final_total_cents` as the sum of `final_line_cents` over all lines, and for a holiday order, if that final total is less than the `deposit_cents` already paid, the difference is refunded to the customer's `store_credit_cents`. If instead at least one line is `SHORTED` and at least one line is `DRAWN`, the order advances `CONFIRMED → SHORT_FILLED`: the server recomputes `final_total_cents` as the sum of `final_line_cents` over the drawn lines only (shorted lines contribute 0), and for a holiday order refunds the difference between the `deposit_cents` and that final total to `store_credit_cents` whenever that difference is positive.

An order can be cancelled before fulfillment locks in. A customer may cancel their own order while it is `PLACED`, and a clerk may cancel an order while it is `CONFIRMED` provided no line has yet been drawn (no line is `DRAWN`); either way the order advances to `CANCELLED`. On cancellation, for a holiday order the server refunds the order's `deposit_cents` to the customer's `store_credit_cents` and recomputes the order's `HolidayWindow.committed_g` by subtracting this order's ordered grams. A customer cancelling an order they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 3.6. Holiday Windows: Deposits and Capacity Quotas

A holiday window is the shop's pre-order capacity for a single occasion. The manager creates one with a `name` (a label such as THANKSGIVING_2026, unique across windows), a `pickup_date` (the single pickup day), a `capacity_g` (the total grams of pre-orders the shop can fulfill that window, at least 1), and a `cutoff_at` (the UTC instant after which no new holiday orders may be placed against the window). A new window has `committed_g` of 0, and a fetch returns the live `committed_g`.

When a holiday order is placed, two gates apply in addition to the ordinary placement work. First, the timing gate: the current clock must be at or before the window's `cutoff_at`, or placement is rejected with `ERR_WINDOW_CUTOFF_PASSED` (HTTP 422). Second, the capacity gate: the window's `committed_g` represents the sum of ordered grams across all of that window's orders whose `order_status` is one of `PLACED`, `CONFIRMED`, `FILLED`, or `SHORT_FILLED` (cancelled orders are excluded). The order's own ordered grams — the sum of `ordered_weight_g` over its lines — are added; if the resulting committed total would exceed the window's `capacity_g`, placement is rejected with `ERR_HOLIDAY_CAPACITY_EXCEEDED` (HTTP 409). The boundary is inclusive at equality: a placement that brings `committed_g` to exactly `capacity_g` is accepted, and only a placement that would push it strictly above `capacity_g` is rejected. When the order is accepted, the window's `committed_g` is recomputed to include it; when a holiday order is later cancelled, `committed_g` is recomputed to exclude it.

The holiday deposit is a fixed fraction of the estimated total. On holiday placement the server sets the order's `deposit_cents` to one quarter of the order's `estimated_total_cents`, rounded half up once on the order-level total (not per line). This quarter is the holiday deposit rate; it is charged when the order is placed. Standard orders carry no deposit. As described in §3.5, the deposit is reconciled against the actual `final_total_cents` at fill time, and any overage flows back to the customer's store credit; the full deposit returns to store credit on cancellation.

### 3.7. Whole-Animal Shares and Fractional Claims

A whole-animal share lets several customers split one carcass. The manager or a butcher opens an `AnimalShare` with a `species` (one of `BEEF`, `PORK`, `LAMB`, `POULTRY`), a `carcass_weight_g` (the hanging carcass weight in grams available to divide, at least 1), and a `deposit_cents` (the deposit per whole-equivalent unit, at least 0). A new share has `share_status` of `OPEN`, a `claimed_fraction_x4` of 0, and a `remaining_carcass_g` equal to the full `carcass_weight_g`. A share's status is one of `OPEN`, `FULLY_CLAIMED`, `BROKEN_DOWN`, or `CANCELLED`, with `CANCELLED` terminal. A fetch returns the live `claimed_fraction_x4` and `remaining_carcass_g`.

Shares are claimed in quarter units. A customer (or a clerk on their behalf) claims a `fraction` of a share, supplying the `animal_share_id` and the claiming `customer_id`; the fraction is either `QUARTER` or `HALF`. Internally the system tracks claimed fractions in quarter units: a `QUARTER` claim is worth 1 unit and a `HALF` claim is worth 2 units, and `claimed_fraction_x4` is the sum of these unit values over the share's `ACTIVE` claims. A claim is admitted only if it does not over-commit the carcass: the current `claimed_fraction_x4` plus the requested units must be less than or equal to 4 (a whole animal is 4 quarter-units). A claim that would push the total above 4 quarter-units is rejected with `ERR_SHARE_OVERCOMMITTED` (HTTP 409). On a successful claim the server charges a deposit: the claim's `deposit_paid_cents` is the share's `deposit_cents` multiplied by 1 for a `QUARTER` or by 2 for a `HALF`. A claim starts with `claim_status` of `ACTIVE` (later `CANCELLED`). After the claim, the share's `claimed_fraction_x4` is incremented and its `remaining_carcass_g` is recomputed as the `carcass_weight_g` times the quantity four-minus-`claimed_fraction_x4`, divided by 4, floored to whole grams. When a claim brings `claimed_fraction_x4` to exactly 4, the share bubbles `OPEN → FULLY_CLAIMED` and its `remaining_carcass_g` becomes 0. Claims can be fetched individually or listed, filtered by `animal_share_id` or `customer_id`.

Cancellation conserves carcass grams by exactly reversing a claim. A customer cancels their own `ACTIVE` claim, advancing the claim `ACTIVE → CANCELLED`; this is permitted only while the parent share is `OPEN` or `FULLY_CLAIMED` (not `BROKEN_DOWN` and not `CANCELLED`). On cancel the server refunds the claim's `deposit_paid_cents` to the customer's `store_credit_cents`, decrements the share's `claimed_fraction_x4` by the claim's quarter units, and recomputes `remaining_carcass_g`. If the share had been `FULLY_CLAIMED` and the cancel drops `claimed_fraction_x4` below 4, the share bubbles `FULLY_CLAIMED → OPEN`; this revert is cyclic, so a share moves back and forth between `OPEN` and `FULLY_CLAIMED` as claims are added and cancelled. A customer cancelling a claim they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

Once a share is `FULLY_CLAIMED`, a `Butcher` breaks it down, advancing `FULLY_CLAIMED → BROKEN_DOWN`; the break-down supplies a `lots` payload, and the server spawns the described `InventoryLot` rows with each new lot's `source_share_id` set to this share. Separately, the manager may cancel an `OPEN` share, advancing `OPEN → CANCELLED`, but only when the share has no active claims (`claimed_fraction_x4` is 0).

### 3.8. Sausage Batches: Reserving Inputs and Producing Yield

Sausage is made in batches that consume meat from several lots. A `Butcher` creates a draft batch with a `recipe_name`, an `output_cut_type_id` naming the cut produced, and a `planned_output_g` (the target grams of finished sausage, at least 1). The output cut type must be a grind cut — its `is_grind` must be true — or creation is rejected with `ERR_OUTPUT_NOT_GRIND` (HTTP 422). A batch's `batch_status` is one of `DRAFT`, `RESERVED`, `PRODUCED`, or `CANCELLED`, with the last two terminal; it begins `DRAFT`, and its `actual_yield_g` is null until production. Batches can be fetched or listed, filtered by `output_cut_type_id`.

While a batch is in draft, the butcher adds inputs. Each `BatchInput` carries its parent `sausage_batch_id`, an `inventory_lot_id` naming the lot contributing meat, and a `weight_g` (grams allocated from that lot, at least 1). Inputs can be listed for a batch.

Reserving a batch commits its draws and advances `DRAFT → RESERVED`. A batch must have at least one input, and for each input the named lot must be `AVAILABLE` and its `remaining_weight_g` must be at least that input's `weight_g`; a lot that is not available is rejected with `ERR_LOT_NOT_AVAILABLE` (HTTP 409) (a held lot under a quarantined locker surfaces as `ERR_LOCKER_QUARANTINED`), and an input asking for more than the lot has remaining is rejected with `ERR_INSUFFICIENT_LOT_WEIGHT` (HTTP 409). On reserve, for each input the server creates a `COMMITTED` `LotDraw` for that input's `weight_g`, reduces that lot's `remaining_weight_g`, and increments that lot's `version`; any lot driven to 0 remaining bubbles `AVAILABLE → DEPLETED`.

Producing a reserved batch advances `RESERVED → PRODUCED`. The server computes the batch's `actual_yield_g` as the sum of its inputs' `weight_g` times one-minus-the-policy's-`shrink_pct_grind`, floored to whole grams, and then creates a brand-new `AVAILABLE` `InventoryLot` whose `cut_type_id` is the batch's `output_cut_type_id` and whose `received_weight_g` is that yield.

A batch can be cancelled, advancing to `CANCELLED`. Cancelling a `DRAFT` batch has no side effects. Cancelling a `RESERVED` batch compensates the reservation: for each `COMMITTED` `LotDraw` of the batch the server sets the draw's `draw_status` to `REVERTED`, restores that lot's `remaining_weight_g`, increments that lot's `version`, and — if the lot had been `DEPLETED` and now has remaining weight above 0 — reverts it `DEPLETED → AVAILABLE`. A `LotDraw` is one of `COMMITTED` or `REVERTED`; a committed draw reduces `remaining_weight_g` and a reverted draw restores it. Each draw records its `inventory_lot_id`, its `weight_g`, and exactly one of an `order_line_id` (for an order-line draw) or a `batch_input_id` (for a batch-input draw), with the other left null. Lot draws can be listed for a lot or fetched individually, and the full draw log is filterable by `inventory_lot_id`, `order_line_id`, `batch_input_id`, or `draw_status`.

### 3.9. Reverse Reachability and the Test Clock

To support tracing meat through the shop, several lists support reverse-reachability filters. Order lines can be listed filtered by `custom_order_id`, `cut_type_id`, or `drawn_lot_id`, so a manager can find every line filled from a given lot. Lot draws and batch inputs expose the filters noted above. Sausage batches list by `output_cut_type_id`, and inventory lots by `source_share_id`, so a share can be traced to the lots broken out of it. Temperature readings list per locker and individual readings are addressable on their own.

Finally, because aging completion and holiday cutoffs depend on the passage of time, the manager has a test-driving capability that sets the server's notion of the current UTC instant to a supplied `to_iso8601` value. This logical clock is what the aging-elapsed check in §3.2 and the holiday-cutoff checks in §3.5 and §3.6 read when they evaluate "the current clock."

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or append a new resource to a collection return `201 Created`. Operations that modify, transition, or read an existing resource return `200 OK`. All endpoints are subject to the authentication, authorization, existence, and validation rules of §2, and to the workflow preconditions described in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | CounterClerk, ShiftManager |
| GET | `/customers/{id}` | Fetch a customer (includes store credit) | CounterClerk, ShiftManager, Customer |
| POST | `/cut-types` | Create a cut type | ShiftManager |
| GET | `/cut-types/{id}` | Fetch a cut type | CounterClerk, ShiftManager, Butcher, Customer |
| GET | `/cut-types` | List cut types | CounterClerk, ShiftManager, Butcher, Customer |
| POST | `/pricing-policies` | Create and activate a pricing policy | ShiftManager |
| GET | `/pricing-policies/{id}` | Fetch a pricing policy | ShiftManager, CounterClerk, Butcher |
| POST | `/inventory-lots` | Receive a lot into the case | Butcher, ShiftManager |
| GET | `/inventory-lots/{id}` | Fetch a lot | Butcher, ShiftManager, CounterClerk |
| GET | `/inventory-lots` | List lots | Butcher, ShiftManager, CounterClerk |
| POST | `/inventory-lots/{id}/start-aging` | Move an available lot into a locker to begin aging | Butcher |
| POST | `/inventory-lots/{id}/complete-aging` | Return an aged lot to the case | Butcher |
| POST | `/inventory-lots/{id}/discard` | Discard an on-hold lot | ShiftManager |
| GET | `/inventory-lots/{id}/draws` | List draws against this lot | Butcher, ShiftManager |
| POST | `/dry-age-lockers` | Create a dry-age locker | ShiftManager |
| GET | `/dry-age-lockers/{id}` | Fetch a locker | Butcher, ShiftManager, SafetyOfficer |
| POST | `/dry-age-lockers/{id}/temp-readings` | Append a temperature reading | SafetyOfficer |
| GET | `/dry-age-lockers/{id}/temp-readings` | List temperature readings for a locker | SafetyOfficer, ShiftManager, Butcher |
| POST | `/dry-age-lockers/{id}/release` | Release a quarantined locker (OCC-guarded) | ShiftManager |
| POST | `/animal-shares` | Open a whole-animal share | ShiftManager, Butcher |
| GET | `/animal-shares/{id}` | Fetch a share | ShiftManager, Butcher, Customer, CounterClerk |
| POST | `/animal-shares/{id}/break-down` | Break a fully-claimed share into lots | Butcher |
| POST | `/animal-shares/{id}/cancel` | Cancel an open, unclaimed share | ShiftManager |
| POST | `/share-claims` | Claim a fraction of an open share | Customer, CounterClerk |
| GET | `/share-claims/{id}` | Fetch a share claim | Customer, CounterClerk, ShiftManager |
| GET | `/share-claims` | List share claims | Customer, CounterClerk, ShiftManager |
| POST | `/share-claims/{id}/cancel` | Cancel an active claim | Customer |
| POST | `/holiday-windows` | Create a holiday pre-order window | ShiftManager |
| GET | `/holiday-windows/{id}` | Fetch a holiday window | ShiftManager, CounterClerk, Customer |
| GET | `/custom-orders` | List custom orders | CounterClerk, ShiftManager, Customer, Butcher |
| POST | `/custom-orders` | Place a standard or holiday order | Customer, CounterClerk |
| GET | `/custom-orders/{id}` | Fetch an order | Customer, CounterClerk, ShiftManager, Butcher |
| GET | `/custom-orders/{id}/order-lines` | List the order's lines | Customer, CounterClerk, ShiftManager, Butcher |
| POST | `/custom-orders/{id}/confirm` | Confirm an order for fulfillment | CounterClerk |
| POST | `/custom-orders/{id}/fill` | Finalize a confirmed order (FILLED or SHORT_FILLED) | Butcher |
| POST | `/custom-orders/{id}/cancel` | Cancel a placed or undrawn-confirmed order | Customer, CounterClerk |
| GET | `/order-lines/{id}` | Fetch an order line | Customer, CounterClerk, ShiftManager, Butcher |
| GET | `/order-lines` | List order lines | Customer, CounterClerk, ShiftManager, Butcher |
| POST | `/order-lines/{id}/draw` | Fill a line from a lot at a catch weight (OCC-guarded) | Butcher |
| POST | `/order-lines/{id}/short` | Mark a line as shorted | Butcher |
| POST | `/sausage-batches` | Create a draft sausage batch | Butcher |
| GET | `/sausage-batches/{id}` | Fetch a batch | Butcher, ShiftManager |
| GET | `/sausage-batches` | List sausage batches | Butcher, ShiftManager |
| POST | `/sausage-batches/{id}/inputs` | Add a lot input to a draft batch | Butcher |
| GET | `/sausage-batches/{id}/inputs` | List the batch's lot inputs | Butcher, ShiftManager |
| POST | `/sausage-batches/{id}/reserve` | Reserve the batch (commit input draws) | Butcher |
| POST | `/sausage-batches/{id}/produce` | Produce the batch (compute yield, create output lot) | Butcher |
| POST | `/sausage-batches/{id}/cancel` | Cancel a draft/reserved batch (revert draws) | Butcher |
| GET | `/lot-draws/{id}` | Fetch a single lot draw | Butcher, ShiftManager |
| GET | `/lot-draws` | List lot draws | Butcher, ShiftManager |
| GET | `/batch-inputs/{id}` | Fetch a single batch input | Butcher, ShiftManager |
| GET | `/batch-inputs` | List batch inputs | Butcher, ShiftManager |
| GET | `/temp-readings/{id}` | Fetch a single temperature reading | SafetyOfficer, ShiftManager, Butcher |
| POST | `/_clock/set_current_utc` | Set the server's current UTC time (test-driving) | ShiftManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LOT_NOT_AVAILABLE` | 409 |
| `ERR_LOCKER_QUARANTINED` | 409 |
| `ERR_AGING_NOT_COMPLETE` | 409 |
| `ERR_WINDOW_CUTOFF_PASSED` | 422 |
| `ERR_CUT_TYPE_MISMATCH` | 422 |
| `ERR_OUTPUT_NOT_GRIND` | 422 |
| `ERR_SHARE_OVERCOMMITTED` | 409 |
| `ERR_LOCKER_OVER_CAPACITY` | 409 |
| `ERR_INSUFFICIENT_LOT_WEIGHT` | 409 |
| `ERR_HOLIDAY_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_STALE_LOCKER_VERSION` | 412 |

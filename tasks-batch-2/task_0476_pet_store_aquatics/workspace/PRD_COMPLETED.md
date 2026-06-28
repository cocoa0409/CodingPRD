# Pet Store & Aquatics Supply API — Product Requirements Document

## 1. Introduction

The Pet Store & Aquatics Supply platform is the operational backbone of a national big-box pet retailer that sells both packaged catalog goods (food, habitats, accessories, medications) and live animals (fish, reptiles, and small mammals) across many physical stores. Unlike a conventional retailer, this business carries inventory that can be alive, can be sick, can be under regulatory quarantine, or can be the subject of a manufacturer recall — and the same customer who buys a bag of food on auto-ship may also adopt a bearded dragon at a weekend partner event, book a vaccine clinic, and redeem loyalty points earned across all of it. The API exists to keep these intertwined concerns consistent: animal husbandry and health, food-and-medication inventory with first-expiry-first-out allocation, prescription-diet authorization tied to veterinary exams, subscription auto-ship, special orders, loyalty accrual and tiering, adoption-event capacity, and the cross-store fan-out of product recalls.

The central design challenge this system addresses is **compliance and traceability under cascading state change**. A single recall can quarantine inventory in dozens of stores, flip a catalog product's sale eligibility, and halt every active subscription that ships it — and resolving that recall must surgically reverse only the effects it caused, leaving untouched anything a second, still-open recall continues to cover. Likewise, livestock cannot reach the sales floor until its quarantine window has elapsed and it is demonstrably healthy, and a batch that crosses a mortality threshold must be condemned and pulled from sale automatically. This document specifies every entity, state machine, calculation, validation, and access-control rule the implementation must honor so that these guarantees hold uniformly and deterministically.

Throughout, all timestamps are interpreted against a **logical server clock** rather than wall-clock time, so that time-gated rules (quarantine elapse, appointment check-in, shipment due dates, prescription expiry) are reproducible. The clock starts at a fixed default and is advanced only by an explicit administrative capability described in §3.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All collections are mounted at the top level (for example, `/products`, `/inventory-lots`, `/livestock-batches`), and every entity is addressable both as a collection and by its individual identifier.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles, spelled precisely as follows: `InventoryManager`, `LivestockKeeper`, `ClinicVet`, `StoreClerk`, and `Customer`. The first four are operational staff roles. When `X-User-Role` is `InventoryManager`, `LivestockKeeper`, `ClinicVet`, or `StoreClerk`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may use it to identify the actor but does not compare it to any entity's `id`. These roles are partitioned by responsibility: `InventoryManager` owns catalog, stores, inventory lots, recalls, and special-order allocation; `LivestockKeeper` owns livestock intake, health and quarantine transitions, and adoption placements; `ClinicVet` owns clinic appointments and prescription issuance and revocation; `StoreClerk` owns point-of-sale, livestock sales, subscription shipment runs, special-order fulfillment, and adoption events.

The `Customer` role is different. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare that resource's `customer_id` (or, for the customer record itself, its own `id`) to `X-User-ID`. A `Customer` may only act on subscriptions, special orders, prescriptions, shipments, and the customer record that belong to them. When a `Customer` attempts to pause, resume, or cancel a subscription, or cancel a special order, that does not belong to them, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check is distinct from the role-permission check: a customer is permitted by role to cancel subscriptions in general, but forbidden by ownership to cancel one that is not theirs.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100 rather than rejected; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_FIELD_VALUE`. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted resource carries a system-managed `id`, formatted as a UUID with no type prefix, generated by the server at creation time and never supplied by the client. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first created.

All entities in this system are mutable and therefore additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is an ISO 8601 UTC timestamp (three fractional digits) refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value when the resource is created and increments by one on every mutation. Wherever a workflow below states that an operation "bumps the version" or increments `version`, it also refreshes `updated_at` on that same resource; the two always move together. When the server mutates a resource as an automatic side effect of another operation — for example, when an adoption event closing returns a still-placed batch to the floor, or a recall halts a subscription — that secondary mutation independently increments the affected resource's `version` and refreshes its `updated_at`, exactly as a direct mutation would.

### 2.5. Nested Resource Retrieval and Identifier Validation

Several endpoints address a resource by an identifier embedded in the URL path, and a few address an entity through a chain (for example, returning a placement under an event). When a path contains a resource identifier, the system validates its existence before applying any business rule, and when a path or body involves more than one referenced entity, identifiers are validated left-to-right in path order first, then body foreign keys. The request is rejected with the not-found error specific to the first missing resource — `ERR_STORE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_SPECIAL_ORDER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, or `ERR_RECALL_NOT_FOUND` — according to which resource type was not found. Creation endpoints that carry foreign-key body fields (such as `product_id`, `store_id`, `batch_id`, `customer_id`, `subscription_id`, `event_id`, or `issued_by_appointment_id`) resolve each referenced entity and reject with the corresponding not-found error when any does not exist.

### 2.6. Validation Ordering and the Precedence of Checks

Because many operations layer several independent checks, the order in which checks run is itself part of the contract; an implementation that runs them in a different order will surface the wrong error to a client whose request fails more than one rule. The system evaluates checks in this fixed precedence. First, authentication: the user-context headers must be present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role authorization: the declared role must be permitted for the operation (`ERR_INSUFFICIENT_PERMISSIONS`). Third, resource ownership for customer-owned resources (`ERR_NOT_RESOURCE_OWNER`). Fourth, existence of every path-resource identifier, validated left-to-right (the appropriate not-found error). Fifth, existence of every referenced foreign-key body field (the appropriate not-found error). Sixth, body field types and ranges (`ERR_INVALID_FIELD_VALUE`). Seventh, uniqueness constraints (`ERR_DUPLICATE_RESOURCE`). Eighth, the target resource's state must permit the requested transition (`ERR_..._STATE_INVALID` or the relevant state error). Ninth, where applicable, the optimistic-concurrency version check (`ERR_STALE_VERSION`), evaluated immediately after the state precondition and before any inventory or charge work. Only after all of these do the deeper, operation-specific business rules (temporal gates, safety gates, capacity, fiscal sufficiency) run. Within those deeper rules, each workflow in §3 states the relative order of any checks that can co-occur.

Field-level validation under the sixth step rejects with `ERR_INVALID_FIELD_VALUE` (HTTP 422) any body whose values are out of range or of the wrong type. This includes a `quantity` or `head` that is not greater than zero, a `head_count` not greater than zero, a `unit_price_cents` not greater than zero, an `end_at` that is not strictly after `start_at`, a `discount_pct` outside the inclusive range from 0.0 to 0.5, a `deposit_pct` outside the inclusive range from 0.0 to 1.0, and any value of `severity`, `category`, `animal_class`, or `service_type` that is not one of its permitted enumeration members.

### 2.7. Uniqueness Constraints

Three uniqueness rules are enforced, each rejecting a violating create with `ERR_DUPLICATE_RESOURCE` (HTTP 409). A `Product` `sku` must be globally unique across the catalog. An `InventoryLot` `lot_code` must be unique among lots of the same `product_id` (the same physical lot code may legitimately recur for a different product). A `Customer` `email` must be globally unique. These checks apply respectively to product creation, inventory-lot receiving, and customer registration.

### 2.8. Monetary Values, Loyalty Tiering, and Precision

All monetary amounts in this system are stored and exchanged as integer cents; there are no fractional-cent fields. Where a calculation produces a non-integer intermediate (for example, after applying a discount fraction), the final stored amount is obtained by **rounding half up** to a whole number of cents. Each calculation in §3 specifies exactly where that single rounding occurs, because the placement of rounding materially changes results.

A customer's standing is summarized by `loyalty_tier`, a derived value taking one of `BRONZE`, `SILVER`, or `GOLD`. The tier is a pure function of the customer's cumulative `lifetime_spend_cents` and is recomputed every time that figure increases. A customer whose lifetime spend is at least 20,000,000 cents (that is, two hundred thousand dollars) is `GOLD`; otherwise, a customer whose lifetime spend is at least 5,000,000 cents (fifty thousand dollars) is `SILVER`; otherwise the customer is `BRONZE`. Both thresholds are inclusive lower bounds: a lifetime spend exactly equal to 5,000,000 cents is `SILVER`, and exactly 20,000,000 cents is `GOLD`. New customers begin at `BRONZE` with zero `loyalty_points` and zero `lifetime_spend_cents`.

### 2.9. Inventory Allocation: First-Expiry-First-Out

Whenever the system must draw catalog units from stock — to run a subscription shipment, to allocate or fulfill a special order, or to complete a point-of-sale — it allocates from inventory lots using a fully deterministic first-expiry-first-out (FEFO) discipline. The candidate set is every `InventoryLot` whose `store_id` equals the fulfilling store, whose `product_id` equals the target product, whose `status` is `AVAILABLE`, and whose free-unit count (its `quantity_on_hand` minus its `quantity_reserved`) is greater than zero; lots that are `QUARANTINED` or `DEPLETED` are never candidates. Candidate lots are ordered by `expiry_date` ascending (earliest expiry first); ties are broken by `received_at` ascending (earliest received first); any remaining ties are broken by `created_at` ascending. The resolver never falls back to `id`. Units are taken greedily from the head of this ordered list until the requested count is satisfied, and the last lot drawn may be drawn partially. If the sum of free units across all candidate lots is less than the requested count, the operation is rejected with `ERR_INSUFFICIENT_INVENTORY` and no units are taken — allocation is all-or-nothing, never partial.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a resource. In each case the request body must carry a version field naming the client's last observed `version` of the parent resource, and the operation proceeds only if that value equals the resource's current `version`.

A request to run a subscription's due auto-ship cycle must carry `expected_subscription_version` matching the target subscription's current `version`. If another writer has already advanced the subscription's version since the client last read it — for example, by running the due shipment, which advances `next_ship_at` and `shipments_count` and bumps the version — the run is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a stale writer from re-running a cycle that has already been fulfilled, which would double-charge the customer and double-decrement inventory.

A request to adjust an inventory lot's on-hand quantity must carry `expected_lot_version` matching the target lot's current `version`. If the lot's version has advanced since the client last read it — because, say, a recall just quarantined it or a shipment just decremented it — the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing a quantity computed from a no-longer-current on-hand figure. The version check on both endpoints runs immediately after the state precondition and before any quantity, charge, or allocation work. Endpoints other than these two do not take a version field and are not subject to this check.

### 2.11. The Logical Server Clock

All time-gated rules in this system are evaluated against a logical clock rather than the host's wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any administrative set the clock holds precisely that default and never falls back to real time. An administrative test-driving capability accepts a target instant in the `to_iso8601` body field and sets the logical clock to it for all subsequent time-gated checks. Quarantine elapse, appointment check-in and no-show timing, shipment due dates, and prescription expiry are all judged against whatever the logical clock currently reads.

## 3. Business Logic & Workflows

### 3.1. Stores, Catalog, and the Recall State of a Product

An `InventoryManager` establishes the physical and catalog backbone of the system. A store is created with a display `name` and a US `state_code` (such as CA or NY), which governs the jurisdictional scoping of recalls; an optional `loyalty_point_value_cents` may be supplied to set the cents of redeemable value carried by one loyalty point at that store, defaulting to 1 when omitted. A store is born `OPEN`; its `status` field takes one of `OPEN` or `CLOSED`, but the system exposes no operation that transitions a store to `CLOSED`, so in practice a store remains `OPEN`, and no sale, shipment, allocation, or other operation gates on a store's `status`.

Catalog products are likewise created by an `InventoryManager`. Each product carries a globally unique `sku`, a display `name`, a `category` that is one of `FOOD`, `HABITAT`, `ACCESSORY`, or `MEDICATION`, and a `unit_price_cents` list price that must be greater than zero. Two optional flags shape downstream behavior: `is_prescription_diet`, which defaults to false and, when true, marks the product as sellable only against a valid prescription authorization, and `loyalty_points_per_unit`, a non-negative count of loyalty points earned per unit sold, defaulting to 0. Every product also exposes a derived `recall_state`, one of `CLEAR` or `RECALLED`, which is recomputed from the open recalls covering it; a freshly created product is `CLEAR`.

The `recall_state` is not stored input — it is a reflection of recall coverage. A product is `RECALLED` whenever at least one `OPEN` `Recall` names its `product_id`, and `CLEAR` when no open recall does; the recall's optional `lot_code` and `scope_state_code` scoping (described in §3.9) does not narrow this product-level derivation — any open recall on the product's `product_id` renders the product `RECALLED` regardless of that scoping, which only narrows which lots are quarantined and which subscriptions are halted in the cascade. Every place in the system that consults whether a product may be sold, shipped, allocated, or resumed reads this derived state.

### 3.2. Receiving and Adjusting Inventory Lots

Inventory arrives as lots. An `InventoryManager` receives a lot into a store by supplying its `store_id`, its `product_id`, a manufacturer `lot_code` (unique within that product), the `quantity_on_hand` of sellable units physically present, a `received_at` receiving timestamp, and an `expiry_date`. A newly received lot is `AVAILABLE`, with `quantity_reserved` initialized to zero. The lot's `status` takes one of `AVAILABLE`, `QUARANTINED`, or `DEPLETED`. The `quantity_on_hand` is decremented as units are sold or shipped and is never allowed to fall below zero, while `quantity_reserved` tracks units set aside for pending auto-ship or special orders and never exceeds `quantity_on_hand`. The `expiry_date` is the primary FEFO ordering key and `received_at` the secondary key, as described in §2.9.

An `InventoryManager` may correct a lot's on-hand count — to record additional receiving or to write down shrinkage — by submitting a signed `delta` together with `expected_lot_version`. As established in §2.10, the adjustment is rejected with `ERR_STALE_VERSION` when `expected_lot_version` does not match the lot's current `version`. When the version matches, the `delta` is added to `quantity_on_hand`; the result must remain at least as large as `quantity_reserved` and must not go below zero. If the resulting `quantity_on_hand` is zero, the lot becomes `DEPLETED`; if the lot had been `DEPLETED` and the adjustment raises it above zero, it returns to `AVAILABLE`. The adjustment increments the lot's `version`.

### 3.3. Livestock Intake, Quarantine, and Health

Live animals enter the system as batches, governed by two **independent, parallel state dimensions**: a health dimension (`health_state`) and a sale dimension (`sale_state`). A `LivestockKeeper` intakes a batch into a store with its `store_id`, a `species` label (such as betta or bearded_dragon), an `animal_class` of `FISH`, `REPTILE`, or `SMALL_ANIMAL`, a `head_count` of live animals greater than zero, a per-head `unit_price_cents` greater than zero, an `intake_at` timestamp that starts the quarantine window, and a required `quarantine_days` duration greater than zero. On intake, `health_state` is `QUARANTINE`, `sale_state` is `HELD`, and `mortality_count` is zero. The health dimension takes one of `QUARANTINE`, `HEALTHY`, `UNDER_TREATMENT`, or `CONDEMNED`; the sale dimension takes one of `HELD`, `ON_FLOOR`, `RESERVED`, or `SOLD_OUT`. `CONDEMNED` (health) and `SOLD_OUT` (sale) are terminal.

Clearing quarantine moves a batch's health from `QUARANTINE` to `HEALTHY`. The `LivestockKeeper` performing this transition succeeds only when the batch is currently in `QUARANTINE` health (otherwise `ERR_BATCH_HEALTH_STATE_INVALID`), when the logical clock has reached at least `intake_at` plus `quarantine_days` — a closed lower bound, so the instant exactly equal to `intake_at` plus `quarantine_days` qualifies (otherwise `ERR_QUARANTINE_NOT_ELAPSED`), and when `mortality_count` is exactly zero (otherwise `ERR_QUARANTINE_MORTALITY_BLOCK`). A successful clearance sets `health_state` to `HEALTHY` and bumps the batch `version`.

The same clear-quarantine capability also serves as the recovery path for a treated batch: a batch whose health is `UNDER_TREATMENT` may return to `HEALTHY` through it. In that recovery case the precondition is that the batch is in `UNDER_TREATMENT` health (otherwise `ERR_BATCH_HEALTH_STATE_INVALID`) and that its mortality ratio — `mortality_count` divided by `head_count` — remains strictly below the condemnation rate of 0.5 (otherwise `ERR_QUARANTINE_MORTALITY_BLOCK`); on success the batch returns to `HEALTHY` and the `version` is bumped.

Recording mortality is how deaths are logged. A `LivestockKeeper` submits a `deaths` count, permitted while the batch's health is `QUARANTINE`, `HEALTHY`, or `UNDER_TREATMENT` (otherwise `ERR_BATCH_HEALTH_STATE_INVALID`). The submitted `deaths` are added to the cumulative `mortality_count`. The system then evaluates the mortality ratio: `mortality_count` divided by `head_count`, where `head_count` is the original intake count and is never reduced by recorded deaths. This is a real-number division. If that ratio is at least 0.5 — the boundary is inclusive, so a ratio of exactly 0.5 condemns — the batch is condemned: `health_state` becomes `CONDEMNED` and, because a condemned batch can no longer be sold, `sale_state` becomes `SOLD_OUT`. Otherwise the batch's health becomes `UNDER_TREATMENT`. Either way the `version` is bumped. A `LivestockKeeper` may also condemn an under-treatment batch outright: a batch whose health is `UNDER_TREATMENT` (otherwise `ERR_BATCH_HEALTH_STATE_INVALID`) is moved to `CONDEMNED` health with its `sale_state` forced to `SOLD_OUT`, bumping the `version`.

### 3.4. Listing Livestock for Sale, Adoption Placement, and Livestock Sales

A batch reaches buyers through the sale dimension. Listing a batch on the floor advances its sale from `HELD` to `ON_FLOOR`; the `LivestockKeeper` doing so succeeds only when the batch's sale is currently `HELD` (otherwise `ERR_BATCH_SALE_STATE_INVALID`) and the batch's `health_state` is `HEALTHY` (otherwise `ERR_BATCH_NOT_HEALTHY`), and the transition bumps the `version`. The health-must-be-`HEALTHY` guard is shared with two other operations and is described together in §3.5.

Adoption placements connect livestock to partner adoption events (the events themselves are covered in §3.6). A `LivestockKeeper` places head from a batch into an event by supplying the `event_id`, the `batch_id`, and the `head` to place (greater than zero). Placement requires the batch's sale to be `ON_FLOOR` (otherwise `ERR_BATCH_SALE_STATE_INVALID`), the batch's `health_state` to be `HEALTHY` (otherwise `ERR_BATCH_NOT_HEALTHY`), the requested `head` to be no greater than the batch's live head — its `head_count` minus its `mortality_count` (otherwise `ERR_INSUFFICIENT_HEAD`), and the event's `placed_head` plus the requested `head` to be no greater than the event's `capacity` (otherwise `ERR_EVENT_CAPACITY_EXCEEDED`). When both quantity checks could fail, the live-head check is evaluated before the capacity check. A successful placement is created in `PLACED` status; the event's `placed_head` is increased by the placed `head` and the event's `version` is bumped; and the batch's `version` is bumped. When — and only when — the placed `head` equals the batch's entire live head (its `head_count` minus its `mortality_count`), the batch's sale advances from `ON_FLOOR` to `RESERVED`, reflecting that the whole live batch is now committed to the event.

A placement may be returned as a compensating action, freeing the batch back to the floor. Returning a placement requires that the placement is still in `PLACED` status (otherwise `ERR_PLACEMENT_NOT_RETURNABLE`). On return, the placement's `status` becomes `RETURNED`, the event's `placed_head` is decreased by that placement's `head` and the event `version` is bumped, and if the batch's sale was `RESERVED` it returns to `ON_FLOOR`; the batch `version` is bumped.

A `StoreClerk` sells a full on-floor batch to a customer by referencing the `batch_id` and the buyer's `customer_id`. The sale requires the batch's sale to be `ON_FLOOR` (otherwise `ERR_BATCH_SALE_STATE_INVALID`) and its `health_state` to be `HEALTHY` (otherwise `ERR_BATCH_NOT_HEALTHY`). On success the batch's sale becomes `SOLD_OUT`, the customer is credited per the livestock-sale accrual described below, and the batch `version` is bumped; the operation returns the updated batch resource with a `201 Created` status. The amount charged is computed from the live head sold — the batch's `head_count` minus its `mortality_count` — multiplied by the batch's per-head `unit_price_cents`, then reduced by the customer's loyalty-tier discount fraction read at sale time (`BRONZE` earns no discount, `SILVER` earns 0.05, and `GOLD` earns 0.10), with the resulting amount rounded half up to whole cents exactly once. That net amount is added to the customer's `lifetime_spend_cents`. Earned loyalty points equal the net amount in cents divided by 100 and rounded down to a whole number (that is, whole dollars of net spend), multiplied by one point per dollar; those points are added to the customer's `loyalty_points`. Finally the customer's `loyalty_tier` is recomputed from the new `lifetime_spend_cents` per the thresholds in §2.8.

### 3.5. The Health-Gate and Recall-Gate Safety Rules

Two cross-cutting safety gates recur across the workflows and are stated here once so their full reach is unambiguous. The **health gate** requires a batch's `health_state` to be `HEALTHY`, and it guards exactly three operations: listing a batch on the floor, placing the batch into an adoption event, and selling the batch. In all three the rejection when the batch is not healthy is `ERR_BATCH_NOT_HEALTHY`.

The **recall gate** blocks any attempt to move a product whose derived `recall_state` is `RECALLED`. It guards exactly five operations: running a subscription shipment, allocating a special order, fulfilling a special order, resuming a subscription, and a point-of-sale product sale. In all five the rejection when the product is recalled is `ERR_PRODUCT_RECALLED`.

### 3.6. Adoption Events

A `StoreClerk` schedules an adoption-partner event at a store by giving the `store_id`, a `partner_name` (the rescue or shelter), an `event_date`, and a `capacity` (the maximum head the event may place, greater than zero). A new event is `SCHEDULED` with `placed_head` at zero; its `status` takes one of `SCHEDULED`, `OPEN`, or `CLOSED`, with `CLOSED` terminal. Opening an event advances it from `SCHEDULED` to `OPEN`, permitted only while it is `SCHEDULED` (otherwise `ERR_EVENT_STATE_INVALID`), and bumps the `version`. Placements (see §3.4) raise `placed_head` toward `capacity` while the event is open.

Closing an event advances it from `OPEN` to `CLOSED`, permitted only while it is `OPEN` (otherwise `ERR_EVENT_STATE_INVALID`). Closing is a cascade: for every placement still in `PLACED` status under the event, the placement's `status` is set to `RETURNED`, the event's `placed_head` is reduced by that placement's `head`, and if the placement's batch had its sale in `RESERVED` the batch returns to `ON_FLOOR` with its `version` bumped. After the cascade resolves all outstanding placements, the event's `status` becomes `CLOSED` and its `version` is bumped.

### 3.7. Clinic Appointments and the Vet-Exam Gateway

The clinic side of the business runs on appointments. An appointment is booked by a `ClinicVet` or a `StoreClerk` against a store and customer, supplying the `store_id`, the `customer_id`, a `service_type` of `GROOMING`, `VACCINE`, or `VET_EXAM`, a `room` identifier, a `start_at` (inclusive) and an `end_at` (exclusive, and required to be strictly after `start_at`), and a `fee_cents` charge that must be at least zero. A new appointment is `BOOKED`; its `status` takes one of `BOOKED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`, or `NO_SHOW`. At booking time the system enforces a room double-booking rule: within the same store and `room`, no existing appointment whose own `status` is `BOOKED` or `CHECKED_IN` may have a half-open time interval `[start_at, end_at)` that overlaps the new one; a violation is rejected with `ERR_ROOM_DOUBLE_BOOKED`. Because the interval is half-open, two appointments that merely touch — one ending exactly when the next begins — do not overlap and are both allowed.

A `ClinicVet` checks in a booked appointment, advancing it from `BOOKED` to `CHECKED_IN`, permitted only when the appointment is `BOOKED` (otherwise `ERR_APPOINTMENT_STATE_INVALID`) and only once the logical clock has reached at least `start_at` (otherwise `ERR_APPOINTMENT_NOT_STARTED`); the `version` is bumped. From `CHECKED_IN`, a `ClinicVet` completes the appointment, moving it to `COMPLETED` (permitted only from `CHECKED_IN`, otherwise `ERR_APPOINTMENT_STATE_INVALID`). Completion accrues clinic loyalty to the customer and bumps the `version`. The clinic accrual adds the appointment's `fee_cents` to the customer's `lifetime_spend_cents`; it grants loyalty points equal to the fee in cents divided by 100 and rounded down to whole dollars, multiplied by one point per dollar, and further multiplied by a service multiplier of 1 for `GROOMING`, 2 for `VACCINE`, and 3 for `VET_EXAM`; those points are added to `loyalty_points`; and the customer's `loyalty_tier` is recomputed from the new `lifetime_spend_cents`.

A booked appointment may instead be cancelled by a `ClinicVet`, moving it from `BOOKED` to `CANCELLED` (permitted only from `BOOKED`, otherwise `ERR_APPOINTMENT_STATE_INVALID`), bumping the `version`. Or it may be marked a no-show, moving it from `BOOKED` to `NO_SHOW`, permitted only from `BOOKED` (otherwise `ERR_APPOINTMENT_STATE_INVALID`) and only once the logical clock has reached at least `end_at` (otherwise `ERR_APPOINTMENT_NOT_ENDED`), bumping the `version`. Completing a `VET_EXAM` appointment is significant beyond loyalty: it is the cross-entity precondition that unlocks issuing a prescription that references this appointment, as §3.8 describes.

### 3.8. Prescriptions and Prescription-Diet Sales

A `ClinicVet` issues a prescription authorizing prescription-diet purchases. The issuance carries the `customer_id`, the authorized `product_id`, the `issued_by_appointment_id` of the exam that justifies it, a `max_units_per_order` cap (greater than zero) on how many prescription-diet units may be sold in a single sale, and an `expires_at` instant. The referenced `issued_by_appointment_id` must be a `COMPLETED` appointment whose `service_type` is `VET_EXAM` and whose customer is the same as the prescription's `customer_id`; otherwise issuance is rejected with `ERR_APPOINTMENT_NOT_ELIGIBLE`. A new prescription is `ACTIVE`; its `status` takes one of `ACTIVE` or `REVOKED`. A `ClinicVet` may revoke a prescription, moving it from `ACTIVE` to `REVOKED` and bumping the `version`; revoking a prescription whose `status` is not `ACTIVE` is rejected with `ERR_INVALID_FIELD_VALUE`. Expiry is enforced at sale time against `expires_at`, not by a status change: a prescription whose `expires_at` is at or before the current logical clock is treated as not honored at sale time even while its `status` is still `ACTIVE`.

When a point-of-sale product sale targets a product whose `is_prescription_diet` is true, the sale requires that the buying customer hold a prescription for that exact customer-and-product pair whose `status` is `ACTIVE`, whose `expires_at` is strictly after the current logical clock, and whose `max_units_per_order` is at least the quantity being sold. If no such prescription exists, or the requested quantity exceeds `max_units_per_order`, the sale is rejected with `ERR_PRESCRIPTION_REQUIRED`.

### 3.9. Recalls and Their Cross-Store Cascade

A recall is the system's most far-reaching operation, issued by an `InventoryManager`. The recall is created against a `product_id` (which must exist, otherwise `ERR_PRODUCT_NOT_FOUND`) and a `severity` of `ADVISORY` or `MANDATORY`. Two optional scoping fields narrow its reach: a `lot_code`, which when present limits the recall to lots bearing that manufacturer code (and when absent covers all lots of the product), and a `scope_state_code`, which when present limits the recall to lots held in stores whose `state_code` matches it (and when absent covers all states). A new recall is `OPEN`; its `status` takes one of `OPEN` or `RESOLVED`. Issuing a recall fans out a three-hop transitive cascade. In the first hop, every in-scope `AVAILABLE` `InventoryLot` for the product — those matching the optional `lot_code` and the optional `scope_state_code` — is set to `QUARANTINED`, its `version` bumped, and the count of such lots is recorded in the recall's `affected_lot_count`. The second hop is caused by the first: the product's `recall_state` is recomputed from its now-quarantined coverage and becomes `RECALLED`. The third hop is caused by the second: every `Subscription` whose `status` is `ACTIVE` or `PAUSED`, whose product is now `RECALLED`, and whose store lies within the recall's scope is moved to `HALTED`, each such subscription's `version` bumped, and the count recorded in the recall's `halted_subscription_count`.

Resolving a recall is the compensating operation, reversing only the effects that this particular recall caused, and only where no other open recall still demands them. A `ClinicVet` cannot do this; resolution is an `InventoryManager` action, permitted only while the recall is `OPEN` (otherwise `ERR_RECALL_STATE_INVALID`). For every lot this recall quarantined that is not still covered by another `OPEN` recall, the lot's `status` returns to `AVAILABLE` and its `version` is bumped. Each affected product's `recall_state` is then recomputed and becomes `CLEAR` when no `OPEN` recall covers it any longer. For every subscription that this recall halted whose product is now `CLEAR`, the subscription returns to `ACTIVE`, its `next_ship_at` is reset to the current logical clock plus its `cycle_days`, and its `version` is bumped. Finally the recall's `status` becomes `RESOLVED`. The recall additionally tracks `affected_lot_count` and `halted_subscription_count` as the record of what it touched at issuance.

### 3.10. Subscriptions and the Auto-Ship Cycle

A subscription is an auto-ship arrangement created by the owning `Customer` or by a `StoreClerk` on their behalf. It carries the `customer_id`, the `product_id` to be shipped, the fulfilling `store_id`, a `quantity_per_cycle` greater than zero, a `cycle_days` interval greater than zero, an optional base `discount_pct` (a fraction from 0.0 to 0.5 applied before any loyalty-tier discount, defaulting to 0.0), and a `next_ship_at` timestamp for the first shipment. A new subscription is `ACTIVE` with `shipments_count` at zero; its `status` takes one of `ACTIVE`, `PAUSED`, `HALTED`, or `CANCELLED`, with `CANCELLED` terminal.

The owning `Customer` may pause an active subscription, moving it from `ACTIVE` to `PAUSED` (permitted only from `ACTIVE`, otherwise `ERR_SUBSCRIPTION_STATE_INVALID`), bumping the `version`. They may resume a paused subscription, moving it from `PAUSED` back to `ACTIVE` (permitted only from `PAUSED`, otherwise `ERR_SUBSCRIPTION_STATE_INVALID`), but only if the product's `recall_state` is `CLEAR` (otherwise `ERR_PRODUCT_RECALLED`); on resume the `next_ship_at` is reset to the current logical clock plus `cycle_days` and the `version` is bumped. The owning `Customer` may cancel from any of `ACTIVE`, `PAUSED`, or `HALTED` (otherwise `ERR_SUBSCRIPTION_STATE_INVALID`), moving the subscription to `CANCELLED` and bumping the `version`. The pause, resume, and cancel actions are also subject to the ownership rule of §2.1: a customer acting on a subscription that is not theirs is rejected with `ERR_NOT_RESOURCE_OWNER`. Subscriptions also move to and from `HALTED` automatically as a consequence of recall issuance and resolution, as described in §3.9; those are system transitions, not customer actions.

Running a due cycle is performed by a `StoreClerk` and is the OCC-guarded self-loop that leaves the subscription `ACTIVE` while producing a shipment. It carries only `expected_subscription_version` in its body. The run requires, in order, that the subscription's `status` is `ACTIVE` (otherwise `ERR_SUBSCRIPTION_STATE_INVALID`); that `expected_subscription_version` equals the subscription's current `version` (otherwise `ERR_STALE_VERSION`, per §2.10); that the logical clock has reached at least `next_ship_at` (otherwise `ERR_SHIPMENT_NOT_DUE`); that the product's `recall_state` is `CLEAR` (otherwise `ERR_PRODUCT_RECALLED`); and that the ordered free units across `AVAILABLE` lots for the subscription's store and product total at least `quantity_per_cycle` (otherwise `ERR_INSUFFICIENT_INVENTORY`). On success the system creates a shipment record, allocates `quantity_per_cycle` units FEFO per §2.9, decrementing each drawn lot's `quantity_on_hand` and marking any lot driven to zero as `DEPLETED` (each drawn lot's `version` bumped); increments `shipments_count` by one and advances `next_ship_at` by `cycle_days`; charges the customer per the auto-ship calculation below; and increments the subscription's `version` by one.

A shipment is an append-only record of a fulfilled cycle. It captures its parent `subscription_id`, the `lot_id` of the last lot drawn for it, the `units` shipped (equal to the subscription's `quantity_per_cycle` at run time), the pre-discount `gross_cents`, and the post-discount `net_cents`. A shipment's `status` is always `FULFILLED`. The auto-ship charge is computed as follows. The gross is the `units` shipped multiplied by the product's `unit_price_cents`, an exact integer recorded as `gross_cents`. The two discounts then compose **multiplicatively on the gross sum as a whole, base discount first then loyalty-tier discount, with a single rounding only at the very end**: take the gross, multiply it by one minus the subscription's `discount_pct`, then multiply that result by one minus the loyalty-tier discount fraction read at run time (`BRONZE` 0.00, `SILVER` 0.05, `GOLD` 0.10), and round that final real number half up to whole cents exactly once to obtain `net_cents`. The loyalty tier is read at the moment the shipment runs, not at subscription creation. That `net_cents` is then added to the customer's `lifetime_spend_cents`, the customer earns loyalty points equal to whole dollars of `net_cents` (its cents divided by 100, rounded down) at one point per dollar added to `loyalty_points`, and the customer's `loyalty_tier` is recomputed.

### 3.11. Special Orders: Deposit at Request, Balance at Fulfillment

A special order lets a customer order a product for later pickup, paying a deposit up front and the balance on fulfillment. It is requested by the owning `Customer` or a `StoreClerk` with the `customer_id`, the `product_id`, the pickup `store_id`, a `quantity` greater than zero, and an optional `deposit_pct` (a fraction from 0.0 to 1.0, defaulting to 0.25). A new order is `REQUESTED`; its `status` takes one of `REQUESTED`, `ALLOCATED`, `FULFILLED`, or `CANCELLED`, with `FULFILLED` and `CANCELLED` terminal. At request time the system computes and stores the order's `deposit_cents` and `balance_cents`.

The special-order pricing deliberately differs from auto-ship in its rounding discipline: here the loyalty-tier discount is applied **per unit and rounded per unit, then summed**, rather than once at the end. The tier discount fraction (`BRONZE` 0.00, `SILVER` 0.05, `GOLD` 0.10) is read at request time and frozen on the order even if the customer's tier later changes. For each unit, take the product's `unit_price_cents`, multiply by one minus the frozen tier discount, and round that half up to whole cents to obtain a per-unit net; multiply that per-unit net by the `quantity` to obtain the order's gross net in cents. The `deposit_cents` is that gross net multiplied by `deposit_pct`, rounded half up to whole cents, and is charged up front at request time. The `balance_cents` is the gross net minus the `deposit_cents`, charged at fulfillment. Because identical price, quantity, and tier inputs are rounded per-line-item here but once-at-end in auto-ship, the two can produce different totals on the same inputs.

An `InventoryManager` allocates a requested order, reserving inventory. Allocation requires the order to be `REQUESTED` (otherwise `ERR_SPECIAL_ORDER_STATE_INVALID`), the product's `recall_state` to be `CLEAR` (otherwise `ERR_PRODUCT_RECALLED`), and the ordered free units across `AVAILABLE` lots for the store and product to total at least the order's `quantity` (otherwise `ERR_INSUFFICIENT_INVENTORY`). On success the system reserves `quantity` units FEFO, increasing each chosen lot's `quantity_reserved` and bumping that lot's `version`; the order moves to `ALLOCATED` and its `version` is bumped.

A `StoreClerk` fulfills an allocated order. Fulfillment requires the order to be `ALLOCATED` (otherwise `ERR_SPECIAL_ORDER_STATE_INVALID`) and the product's `recall_state` to be `CLEAR` (otherwise `ERR_PRODUCT_RECALLED`). On success, for each lot reserved for this order, its `quantity_reserved` and its `quantity_on_hand` are both reduced by the reserved amount and, if its `quantity_on_hand` reaches zero, the lot becomes `DEPLETED` (lot `version` bumped); the order moves to `FULFILLED`. The customer is charged the full order: the sum of its `deposit_cents` and `balance_cents` is added to `lifetime_spend_cents`, loyalty points are earned on that net at one point per whole dollar and added to `loyalty_points`, the `loyalty_tier` is recomputed, and the order `version` is bumped.

The owning `Customer` may cancel a special order from either `REQUESTED` or `ALLOCATED` (otherwise `ERR_SPECIAL_ORDER_STATE_INVALID`); cancellation is also subject to the ownership rule and rejects with `ERR_NOT_RESOURCE_OWNER` when the order is not the acting customer's. Cancelling an `ALLOCATED` order is compensating: for each lot reserved for the order, its `quantity_reserved` is reduced by the reserved amount (releasing the reservation) and that lot's `version` is bumped. In either case the order moves to `CANCELLED` and its `version` is bumped.

### 3.12. Point-of-Sale Product Sales and Loyalty Redemption

A `StoreClerk` rings up a catalog product sale at the point of sale by supplying the `store_id`, the `product_id`, the buyer's `customer_id`, the `quantity` of units, and an optional `redeem_points` count of loyalty points to apply against the purchase. The sale runs the recall gate (rejecting a `RECALLED` product with `ERR_PRODUCT_RECALLED`), then the prescription gate of §3.8 for prescription-diet products (`ERR_PRESCRIPTION_REQUIRED`), then the loyalty-redemption check, and finally the inventory-sufficiency check. The redemption check requires the requested `redeem_points` not to exceed the customer's current `loyalty_points` balance (otherwise `ERR_INSUFFICIENT_LOYALTY_POINTS`). The inventory check requires the ordered free units across `AVAILABLE` lots for the store and product to total at least the requested `quantity` (otherwise `ERR_INSUFFICIENT_INVENTORY`), and it is evaluated after the recall and prescription gates.

On success the system allocates the `quantity` units FEFO per §2.9, decrementing each drawn lot's `quantity_on_hand` and marking any lot driven to zero as `DEPLETED`. The charge is the `quantity` multiplied by the product's `unit_price_cents`, reduced by the redeemed value (the redeemed points converted to cents at the store's `loyalty_point_value_cents`); this net charge is computed as a plain integer-cents subtraction and is not floored at zero, so a redemption whose value exceeds the gross yields a negative net charge that is added to `lifetime_spend_cents` as-is. The customer's `loyalty_points` is decreased by the `redeem_points` applied and then increased by the points earned on this sale, where the earned points equal the `quantity` multiplied by the product's `loyalty_points_per_unit` (no rounding or per-dollar conversion). The net charge is added to the customer's `lifetime_spend_cents`, and the `loyalty_tier` is recomputed from the new total. The operation returns the last `InventoryLot` drawn for the sale (serialized as a lot resource) with a `201 Created` status.

### 3.13. Registering Customers and Reading the Catalog

A customer record is registered by a `StoreClerk` or an `InventoryManager` with an `email` (globally unique), a `full_name`, and a `home_store_id` naming the default fulfilling store. Registration starts the customer at `BRONZE` `loyalty_tier` with zero `loyalty_points` and zero `lifetime_spend_cents`, as established in §2.8. Customers, stores, products, lots, batches, prescriptions, appointments, subscriptions, shipments, special orders, recalls, events, and placements are all listable and individually retrievable; list endpoints accept the pagination parameters of §2.3 and, where noted in §4, optional filter parameters that narrow results by a foreign key — for example listing inventory lots by `store_id` or `product_id`, listing customers by `home_store_id`, listing prescriptions by `customer_id`, `product_id`, or `issued_by_appointment_id`, listing clinic appointments by `store_id` or `customer_id`, listing subscriptions by `customer_id`, `product_id`, or `store_id`, listing shipments by `subscription_id` or `lot_id`, listing special orders by `customer_id`, `product_id`, or `store_id`, listing recalls by `product_id`, listing adoption events by `store_id`, and listing adoption placements by `event_id` or `batch_id`. A `Customer` reading these collections sees their own records and the public catalog.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — or that produce a new distinct record such as a shipment or a sale — return a `201 Created` status code. Operations that modify an existing resource, including state-transition actions, the lot adjustment, and the clock-set capability, return a `200 OK` status code. List and single-resource read operations return `200 OK`. The request bodies, response bodies, and side effects of each operation are specified in §3 and §2, not in the table below; the table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stores` | Create a store | InventoryManager |
| GET | `/stores` | List stores | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| GET | `/stores/{storeId}` | Get a store | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| POST | `/products` | Create a catalog product | InventoryManager |
| GET | `/products` | List products | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| GET | `/products/{productId}` | Get a product (includes derived recall_state) | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| POST | `/inventory-lots` | Receive an inventory lot at a store | InventoryManager |
| GET | `/inventory-lots` | List inventory lots (filterable by store_id and/or product_id) | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| GET | `/inventory-lots/{lotId}` | Get an inventory lot | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| POST | `/inventory-lots/{lotId}/adjust` | Adjust a lot's quantity_on_hand (OCC-guarded) | InventoryManager |
| POST | `/livestock-batches` | Intake a livestock batch (enters quarantine) | LivestockKeeper |
| GET | `/livestock-batches` | List livestock batches (filterable by store_id) | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| GET | `/livestock-batches/{batchId}` | Get a livestock batch | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| POST | `/livestock-batches/{batchId}/clear-quarantine` | Clear quarantine to HEALTHY (also UNDER_TREATMENT recovery) | LivestockKeeper |
| POST | `/livestock-batches/{batchId}/record-mortality` | Record deaths; may trigger UNDER_TREATMENT or CONDEMNED | LivestockKeeper |
| POST | `/livestock-batches/{batchId}/list-on-floor` | List a healthy batch on the sales floor | LivestockKeeper |
| POST | `/livestock-batches/{batchId}/condemn` | Condemn an under-treatment batch | LivestockKeeper |
| POST | `/livestock-sales` | Sell a full healthy on-floor batch to a customer | StoreClerk |
| POST | `/customers` | Register a customer | StoreClerk, InventoryManager |
| GET | `/customers` | List customers (filterable by home_store_id) | InventoryManager, StoreClerk, ClinicVet |
| GET | `/customers/{customerId}` | Get a customer (includes derived loyalty_tier) | InventoryManager, StoreClerk, ClinicVet, Customer |
| POST | `/prescriptions` | Issue a prescription tied to a COMPLETED VET_EXAM | ClinicVet |
| GET | `/prescriptions` | List prescriptions (filterable by customer_id, product_id, issued_by_appointment_id) | InventoryManager, StoreClerk, ClinicVet, Customer |
| GET | `/prescriptions/{prescriptionId}` | Get a prescription | InventoryManager, StoreClerk, ClinicVet, Customer |
| POST | `/prescriptions/{prescriptionId}/revoke` | Revoke a prescription | ClinicVet |
| POST | `/clinic-appointments` | Book a grooming/vaccine/vet-exam appointment | ClinicVet, StoreClerk |
| GET | `/clinic-appointments` | List clinic appointments (filterable by store_id and/or customer_id) | InventoryManager, ClinicVet, StoreClerk, Customer |
| GET | `/clinic-appointments/{apptId}` | Get a clinic appointment | InventoryManager, ClinicVet, StoreClerk, Customer |
| POST | `/clinic-appointments/{apptId}/check-in` | Check in a booked appointment | ClinicVet |
| POST | `/clinic-appointments/{apptId}/complete` | Complete an appointment (accrues loyalty; unlocks prescription) | ClinicVet |
| POST | `/clinic-appointments/{apptId}/cancel` | Cancel a booked appointment | ClinicVet |
| POST | `/clinic-appointments/{apptId}/no-show` | Mark a booked appointment as no-show after its end time | ClinicVet |
| POST | `/subscriptions` | Create an auto-ship subscription | Customer, StoreClerk |
| GET | `/subscriptions` | List subscriptions (filterable by customer_id, product_id, store_id) | InventoryManager, StoreClerk, Customer |
| GET | `/subscriptions/{subId}` | Get a subscription | InventoryManager, StoreClerk, Customer |
| POST | `/subscriptions/{subId}/pause` | Pause an active subscription | Customer |
| POST | `/subscriptions/{subId}/resume` | Resume a paused subscription | Customer |
| POST | `/subscriptions/{subId}/cancel` | Cancel a subscription | Customer |
| POST | `/subscriptions/{subId}/run-shipment` | Fulfill a due auto-ship cycle (OCC-guarded; allocates FEFO; charges) | StoreClerk |
| GET | `/shipments` | List shipments (filterable by subscription_id and/or lot_id) | InventoryManager, StoreClerk, Customer |
| GET | `/shipments/{shipmentId}` | Get a shipment | InventoryManager, StoreClerk, Customer |
| POST | `/special-orders` | Request a special order (charges deposit) | Customer, StoreClerk |
| GET | `/special-orders` | List special orders (filterable by customer_id, product_id, store_id) | InventoryManager, StoreClerk, Customer |
| GET | `/special-orders/{orderId}` | Get a special order | InventoryManager, StoreClerk, Customer |
| POST | `/special-orders/{orderId}/allocate` | Reserve inventory for a special order | InventoryManager |
| POST | `/special-orders/{orderId}/fulfill` | Fulfill an allocated special order (charges balance) | StoreClerk |
| POST | `/special-orders/{orderId}/cancel` | Cancel a special order (releases reservations if allocated) | Customer |
| POST | `/product-sales` | Point-of-sale of catalog product units | StoreClerk |
| POST | `/recalls` | Issue a product recall (3-hop cross-store cascade) | InventoryManager |
| GET | `/recalls` | List recalls (filterable by product_id) | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| GET | `/recalls/{recallId}` | Get a recall | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk, Customer |
| POST | `/recalls/{recallId}/resolve` | Resolve a recall (reverse quarantine + reactivate subscriptions) | InventoryManager |
| POST | `/adoption-events` | Schedule an adoption-partner event | StoreClerk |
| GET | `/adoption-events` | List adoption events (filterable by store_id) | InventoryManager, LivestockKeeper, StoreClerk, Customer |
| GET | `/adoption-events/{eventId}` | Get an adoption event | InventoryManager, LivestockKeeper, StoreClerk, Customer |
| POST | `/adoption-events/{eventId}/open` | Open a scheduled event for placements | StoreClerk |
| POST | `/adoption-events/{eventId}/close` | Close an event (returns still-placed batches to floor) | StoreClerk |
| POST | `/adoption-placements` | Place livestock head into an open event | LivestockKeeper |
| GET | `/adoption-placements` | List placements (filterable by event_id and/or batch_id) | InventoryManager, LivestockKeeper, StoreClerk, Customer |
| GET | `/adoption-placements/{placementId}` | Get a placement | InventoryManager, LivestockKeeper, StoreClerk, Customer |
| POST | `/adoption-placements/{placementId}/return` | Return a placed batch to the floor | LivestockKeeper |
| POST | `/_clock/set_current_utc` | Set the logical server clock | InventoryManager, LivestockKeeper, ClinicVet, StoreClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_STORE_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_PLACEMENT_NOT_FOUND` | 404 |
| `ERR_RECALL_NOT_FOUND` | 404 |
| `ERR_INVALID_FIELD_VALUE` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_BATCH_HEALTH_STATE_INVALID` | 409 |
| `ERR_BATCH_SALE_STATE_INVALID` | 409 |
| `ERR_SUBSCRIPTION_STATE_INVALID` | 409 |
| `ERR_SPECIAL_ORDER_STATE_INVALID` | 409 |
| `ERR_APPOINTMENT_STATE_INVALID` | 409 |
| `ERR_EVENT_STATE_INVALID` | 409 |
| `ERR_RECALL_STATE_INVALID` | 409 |
| `ERR_PLACEMENT_NOT_RETURNABLE` | 409 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_QUARANTINE_NOT_ELAPSED` | 409 |
| `ERR_APPOINTMENT_NOT_STARTED` | 409 |
| `ERR_APPOINTMENT_NOT_ENDED` | 409 |
| `ERR_SHIPMENT_NOT_DUE` | 409 |
| `ERR_BATCH_NOT_HEALTHY` | 409 |
| `ERR_QUARANTINE_MORTALITY_BLOCK` | 409 |
| `ERR_PRODUCT_RECALLED` | 409 |
| `ERR_PRESCRIPTION_REQUIRED` | 409 |
| `ERR_APPOINTMENT_NOT_ELIGIBLE` | 409 |
| `ERR_INSUFFICIENT_HEAD` | 409 |
| `ERR_EVENT_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_INSUFFICIENT_LOYALTY_POINTS` | 409 |
| `ERR_STALE_VERSION` | 412 |

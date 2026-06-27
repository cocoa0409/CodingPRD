# Greenhouse Nursery Grower API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Greenhouse Nursery Grower API, the back-office system of record for a wholesale ornamental-plant operation. A wholesale grower lives at the intersection of two hard problems: finite physical bench space that many crops compete for, and finite saleable inventory that many brokers compete for. Between those two scarcity points sits a long, branching production pipeline — sourcing plugs and liners, transplanting them into a climate-appropriate zone, growing them through a multi-week cycle, grading them against ship-ready specifications, and finally publishing the survivors to an availability list that re-wholesalers draw against.

The API is built to make every step of that journey auditable and to keep the two scarcity ledgers — bench-space footprint and saleable plant count — honest at all times. Space promised to a planned batch must be reserved before the plants arrive and released the moment a batch is voided, culled, or shipped out. Saleable units offered on the availability list must be committed when a broker order is confirmed and released when that order is cancelled. Production reality is messy: plants die, shrink accumulates, grades fail, and crops are held back for a second grow. The system therefore models compensation explicitly — culls, voids, and shipment reversals each unwind their effects on the surrounding ledgers — so that occupancy figures, broker balances, and availability counts never drift from physical truth.

This specification is written for the engineers implementing that system. It is organized into global, system-wide rules (Section 2), the business workflows that constitute the bulk of the domain logic (Section 3), a consolidated endpoint reference (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API. All resources are mounted under the `/nursery` path prefix unless explicitly noted otherwise.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes four roles: `GrowerManager`, `ProductionTech`, `SalesCoordinator`, and `Broker`.

Three of these roles carry an opaque operator identity. When `X-User-Role` is `GrowerManager`, `ProductionTech`, or `SalesCoordinator`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but never compares it against any entity's `id`. The `GrowerManager` owns the crop catalogue, the greenhouse zones, and overall production governance — it creates and manages the lifecycle of varieties and zones, voids planned batches, and runs the operational checkpoint. The `ProductionTech` runs the grow operations: creating and transplanting batches, recording climate, irrigation, fertilizer, scouting, and grade events, and grading or culling batches. The `SalesCoordinator` owns the commercial side: brokers, the availability list, broker orders and their lines, phytosanitary certificates, and shipments.

The `Broker` role is entity-backed. When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting `Broker` entity; ownership checks on any resource that references a `Broker` compare the resource's broker foreign key to `X-User-ID`. A broker may create and edit its own draft orders and lines and read its own commercial data, but it cannot confirm or ship. Concretely, when a `Broker` acts on an order, that order's `broker_id` must equal `X-User-ID`, and any certificate or order foreign-key target named in the request must belong to the same broker; a violation of this ownership rule is rejected with `ERR_FORBIDDEN`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response includes the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system share a common set of system-managed fields. Each carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created. Resources that can be modified after creation additionally carry an `updated_at` timestamp, in the same format, refreshed on every mutation, and a `version`, a non-negative integer that begins at the creation baseline and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control described in Section 2.9.

One entity is append-only and therefore deliberately spare: an input-log event carries only an `id` and a `created_at`. It has no `updated_at` and no `version`, because such an event is never modified after it is written. Every other primary resource — varieties, zones, batches, brokers, availability entries, orders, order lines, shipments, and phytosanitary certificates — carries the full `updated_at` and `version` pair.

All time-sensitive behavior in the system reads from a **logical clock** rather than wall-clock time. The clock's startup default is `2026-01-01T00:00:00Z`; before any call is made the clock reads exactly this default and never falls back to the host's wall-clock time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant, and every subsequent timestamp the server records — an event's `recorded_at`, a batch's `stick_date`, a shipment's `shipped_at`, a certificate's `inspected_at` — together with every expiry and grow-cycle comparison, is taken from this logical clock.

### 2.5. Hierarchical Consistency, Cascades, and Derived-Field Reconciliation

The system maintains immediate consistency across the foreign-key relationships that bind its entities together. Many operations mutate more than one entity at once: transplanting a batch changes both the batch and its zone; confirming an order changes the order, every committed availability entry, and the broker's balance; dispatching a shipment changes the shipment, its lines, the drawn-on batches, the zone, the order, the broker, and possibly a certificate. Whenever an operation cascades into a secondary entity, that secondary entity is itself a mutation: its `updated_at` is refreshed and its `version` is incremented. Wherever this document states that an operation increments a zone's `version` or a broker's balance, the corresponding `updated_at` is refreshed in the same step.

Several fields are **derived** and are never set directly by a client. A zone's `occupied_units`, `reserved_units`, `free_units`, and `fill_state` are recomputed from the live state of the batches assigned to it; a batch's `live_count`, `saleable_count`, and several count fields are recomputed from its event history and lifecycle; an availability entry's `committed_quantity` and `available_quantity` are recomputed from the order lines that draw on it; and an order's monetary totals are recomputed from its lines. To prevent rounding and accounting drift, the zone occupancy figures are fully recomputed — not incrementally adjusted — on every event that touches the zone. Section 3 specifies exactly when each derived field is recomputed and from what inputs.

### 2.6. Nested Resource Retrieval and Referential Validation

The entity model is flat: every collection lives directly under `/nursery`, and resources reference one another by foreign key rather than by deep URL nesting. A handful of convenience endpoints expose a parent's children — the batches assigned to a zone, the input-log events recorded against a batch, the lines on an order, the lines drawing on an availability entry, the certificates issued to a broker, and the shipments dispatched against an order. For any such request, the system validates path identifiers left to right: the parent named in the path must exist before its children are considered. When any referenced resource — whether named in the path or as a foreign key in the body — does not exist, the request is rejected with `ERR_NOT_FOUND`. Existence is checked left-to-right in the path first, then on the body foreign keys.

### 2.7. Monetary Values, Counts, and Precision

All monetary values are integer cents; there are no fractional currency amounts anywhere in the system. Plant counts and footprint units are integers. Where a calculation produces an intermediate fractional value that must be reduced to an integer, this document states the exact reduction — `floor` (round toward zero for non-negative inputs), `ceil` (round up to the next whole number), or **round half up** (round to nearest, with exact halves rounded away from zero) — for that specific step. Unless a step says otherwise, no rounding is applied to exact integer arithmetic.

### 2.8. Validation Ordering

When several conditions guard a single operation, they are evaluated in a fixed priority order so that the rejection a client receives is deterministic. The global ordering is: first, authentication — the headers must be present and name a known role (`ERR_UNAUTHENTICATED`); second, authorization — the acting role must be permitted to perform the operation (`ERR_FORBIDDEN`); third, existence — every path and body resource must exist, validated left-to-right in the path and then on the body foreign keys (`ERR_NOT_FOUND`); fourth, request well-formedness — required body fields must be present and correctly typed, enum values must fall within their allowed set, and numeric ranges must be honored (`ERR_INVALID_REQUEST`). For broker-role order operations, an ownership check follows immediately after existence and well-formedness: the broker must own the order it acts on and any certificate or order foreign-key target must belong to the same broker, failing which the request is rejected with `ERR_FORBIDDEN`.

After those universal checks, state legality is evaluated: the target resource must be in a state from which the requested transition is defined, failing which the request is rejected with `ERR_INVALID_STATE`. Only then are the operation-specific business rules applied. Within a single operation those business rules are themselves ordered, and Section 3 states the order wherever more than one applies — for example, on a transplant the climate, started-count, capacity, and stale-version checks each have their place; on an order confirm the empty-order, broker-hold, availability, credit, and stale-version checks each have their place. The optimistic-concurrency version check is the last gate on the operations that carry it, evaluated only after every other business precondition for that operation has passed.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent resource whose shared state they depend on, because a stale read of that parent can lead to a silently invalid write.

The first is the transplant of a planned batch into its zone. A transplant request must carry `expected_zone_version`, the zone `version` the client last observed. Because another transplant, cull, void, or shipment may have changed the zone's occupied and free footprint since the client read it, the client's view of available space may be stale and the new placement could legitimately over-fill the zone under the fresh occupancy. If `expected_zone_version` does not match the zone's current `version`, the transplant is rejected with `ERR_STALE_VERSION` (HTTP 412).

The second is the confirmation of a draft order. A confirm request must carry `expected_order_version`, the order `version` the client last observed. Because a line add or remove, or a prior confirm, may have changed the order's lines and totals since the client read it, the credit-and-availability snapshot the client is confirming against may be stale. If `expected_order_version` does not match the order's current `version`, the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412).

These two version fields are non-optional inputs to their respective operations. No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.10. Bench-Space Quota: Reservation, Occupation, and Fill Posture

Bench space is the scarce physical resource of the greenhouse, and every zone accounts for it with four derived footprint figures measured in footprint units. A zone's `capacity_units` is its fixed total. Its `reserved_units` is the footprint promised to planned batches that have not yet been transplanted, computed as the sum, over every batch assigned to the zone whose status is `PLANNED`, of that batch's `sourced_count` multiplied by its variety's `container_footprint_units`. Its `occupied_units` is the footprint physically planted, computed as the sum, over every batch assigned to the zone whose status is `GROWING`, `GRADING`, `SALEABLE`, or `HELD`, of that batch's `live_count` multiplied by its variety's `container_footprint_units`. Its `free_units` is `capacity_units` minus `occupied_units` minus `reserved_units`. These three figures are fully recomputed from scratch on every batch transplant, cull, ship, void, or shipment void that touches the zone, never incrementally patched.

A zone's `fill_state` is derived from its free footprint and gates new placements. When `free_units` is zero or below, `fill_state` is `FULL`. Otherwise, when `free_units` is at most the floor of `capacity_units` multiplied by fifteen hundredths, `fill_state` is `TIGHT`. Otherwise `fill_state` is `OPEN`. The boundaries are inclusive on the low side: a `free_units` of exactly zero is `FULL`, and a `free_units` exactly equal to the floor of fifteen percent of capacity is `TIGHT`. The fill posture governs how much new planned reservation a zone will accept, as detailed in Section 3.

### 2.11. Production Loss Accounting

Whenever plants are culled, the system records the financial loss using a flat standard plug cost of 35 cents per plant. This standard plug cost is the basis for the loss-accounting figures described in Section 3, where two costing variants — a flat standard cost and an amortized actual cost — are computed for a cull action.

## 3. Business Logic & Workflows

### 3.1. The Crop Variety Catalogue

Everything the nursery grows begins as a **crop variety** in the catalogue. A `GrowerManager` registers a variety by supplying its marketing `common_name`, its `cultivar_code` (an uppercase alphanumeric code that must be unique among varieties that are not retired), a `propagation_form` describing how new batches are sourced (one of `PLUG`, `LINER`, or `BARE_ROOT`), the nominal `grow_cycle_days` from transplant to ship-ready (at least 1), the `container_footprint_units` of bench space one finished plant occupies (at least 1), the minimum mean height in centimeters a plant must reach to grade out as saleable (`ship_ready_grade_min_height_cm`, greater than zero), and the minimum live fraction of the started stand required to pass grading (`ship_ready_min_live_pct`, greater than zero and at most one — for example, 0.80). A variety may optionally declare `requires_phyto`, a boolean that flags whether interstate shipment of this variety requires a phytosanitary certificate; when omitted it defaults to false. A newly created variety begins in `DRAFT` and is not yet eligible to back any batch.

The catalogue lifecycle runs `DRAFT` → `ACTIVE` → `SUSPENDED` → `RETIRED`, with `RETIRED` terminal. A `GrowerManager` activates a variety to move it from `DRAFT` to `ACTIVE`. Activation requires that all agronomy fields needed downstream — `grow_cycle_days`, `ship_ready_grade_min_height_cm`, `ship_ready_min_live_pct`, and `container_footprint_units` — are present, and that the `cultivar_code` is unique among all varieties whose status is not `RETIRED`; a collision is rejected with `ERR_DUPLICATE_CULTIVAR`. Once `ACTIVE`, the variety becomes eligible to back new batch creation.

A `GrowerManager` may suspend an `ACTIVE` variety, moving it to `SUSPENDED`; while suspended, new batch creation against this variety is blocked, but batches already growing continue undisturbed. Reactivating a `SUSPENDED` variety moves it back to `ACTIVE` and again requires that its `cultivar_code` remains unique among non-retired varieties, with a collision rejected by `ERR_DUPLICATE_CULTIVAR`. Retiring a variety — permitted from either `ACTIVE` or `SUSPENDED` — moves it to the terminal `RETIRED` state, but only when no batch referencing the variety is in any of the states `PLANNED`, `GROWING`, `GRADING`, `SALEABLE`, or `HELD`; if such a batch exists, retirement is rejected with `ERR_VARIETY_IN_USE`. Once retired, the variety's `cultivar_code` is freed for reuse by future varieties, since the uniqueness rule ignores retired entries. Throughout the catalogue, the `status` field tracks the variety's lifecycle and begins at `DRAFT`.

### 3.2. Zones and the Bench-Space Ledger

A **zone** is a greenhouse bench-range that holds growing batches and meters out the bench-space quota described in Section 2.10. A `GrowerManager` creates a zone with a `name`, a `climate_class` (one of `WARM`, `COOL`, or `MIXED`), and a `capacity_units` total footprint (at least 1). At creation the derived figures start clean: `occupied_units` is 0, `reserved_units` is 0, `free_units` equals `capacity_units`, `fill_state` is `OPEN`, and `status` is `OPEN_FOR_USE`.

A zone's operational `status` runs `OPEN_FOR_USE` → `QUARANTINED` (and back) or `OPEN_FOR_USE` → `DECOMMISSIONED`, the latter terminal. Quarantining a zone blocks new batch placement — both creating a planned batch in it and transplanting into it — while it is quarantined, though batches already growing there keep growing; an attempt to place into a non-open zone is rejected with `ERR_ZONE_NOT_OPEN`. Releasing the quarantine returns the zone to `OPEN_FOR_USE`. Decommissioning permanently removes a zone from the placement candidate set, but is allowed only when the zone holds nothing: both `occupied_units` and `reserved_units` must be exactly zero, failing which the request is rejected with `ERR_ZONE_NOT_EMPTY`.

A read of a zone exposes the live occupancy figures, and zones can be listed and filtered by `status` and by `fill_state`. A reverse-lookup capability lists every batch assigned to a given zone.

### 3.3. Starting a Batch: Sourcing and Reserving Space

A **propagation batch** is the unit of production: a single sourced lot of one variety, grown in one zone. A `GrowerManager` or a `ProductionTech` starts a batch by naming the `variety_id` to grow, the `zone_id` to grow it in, the `source_supplier` from whom the plugs or liners are bought, and the `sourced_count` of plugs or liners ordered to start the batch (at least 1). On creation the server mints a unique traceability `lot_code`, sets the batch to `PLANNED`, and initializes `live_count` to 0 and `saleable_count` to 0. The variety must be `ACTIVE`, or creation is rejected with `ERR_VARIETY_NOT_ACTIVE`; the zone must be `OPEN_FOR_USE`, or creation is rejected with `ERR_ZONE_NOT_OPEN`.

Creating a planned batch reserves bench space up front. The reservation footprint is the batch's `sourced_count` multiplied by the variety's `container_footprint_units`, and it is added to the zone's reservation pool, after which the zone's `free_units` and `fill_state` are recomputed and the cascade onto the zone refreshes its `updated_at` and increments its `version`. The reservation is subject to the zone's fill posture. When the zone's `fill_state` is `FULL`, no new planned placement is accepted at all, and the request is rejected with `ERR_ZONE_CAPACITY_EXCEEDED`. When the zone's `fill_state` is `TIGHT`, the new reservation footprint must not exceed the floor of `free_units` divided by two; a reservation larger than that congestion cap is rejected with `ERR_ZONE_TIGHT_FILL_CAP`. In all cases the reservation footprint must fit within the available free space.

A batch may carry the system-managed counts that track its life: `started_count` (set at transplant), `cull_count` (cumulative units culled or removed dead), `live_count` (the current living stand, equal to `started_count` minus `cull_count` minus `shipped_count`), `shipped_count` (cumulative units committed to shipments), and `saleable_count` (units available to sell after grading). It also records `mean_height_cm` (the latest mean height from a grade event), `stick_date` (the transplant timestamp), and `target_ship_date` (the projected ship-ready instant). Its `status` tracks the grow cycle from the initial `PLANNED`. Batches can be listed and filtered by `status`, `variety_id`, and `zone_id`.

If a planned batch is abandoned before transplant, a `GrowerManager` voids it, moving it to the terminal `VOIDED` state. Voiding releases the batch's reservation: the zone's `reserved_units` is reduced by this batch's reservation, its `free_units` and `fill_state` are recomputed, and the cascade onto the zone increments the zone's `version`.

### 3.4. Transplanting: Committing Plants to the Bench

Transplanting is the moment plugs become a living, space-occupying stand. A `ProductionTech` transplants a `PLANNED` batch into its zone, advancing it from `PLANNED` to `GROWING`. The request supplies the `started_count` actually stuck into the zone and the `expected_zone_version` for the concurrency check.

Several preconditions guard the transplant, evaluated after the universal authentication, authorization, existence, well-formedness, and state-legality checks. The variety must be `ACTIVE`, or the transplant is rejected with `ERR_VARIETY_NOT_ACTIVE`. The zone must be `OPEN_FOR_USE`, or it is rejected with `ERR_ZONE_NOT_OPEN`. Climate must be compatible: a zone whose `climate_class` is `MIXED` accepts any variety, and otherwise the zone's climate class must match the variety's propagation requirement; an incompatible pairing is rejected with `ERR_CLIMATE_MISMATCH`. The `started_count` must be at least 1 and no greater than the batch's `sourced_count`; a value outside that inclusive range is rejected with `ERR_INVALID_STARTED_COUNT`. The footprint actually being planted — `started_count` multiplied by the variety's `container_footprint_units` — must fit within the zone's current `free_units` plus the reservation this batch had previously been holding (since transplanting converts this batch's reservation into occupation); an overflow is rejected with `ERR_ZONE_CAPACITY_EXCEEDED`. Finally, as the last gate, `expected_zone_version` must equal the zone's current `version`, or the transplant is rejected with `ERR_STALE_VERSION`.

On a successful transplant the batch's `started_count` is set to the supplied value, `live_count` is set equal to `started_count`, `cull_count` is set to 0, and `saleable_count` is set to 0. The `stick_date` is set to the current logical-clock instant, and the `target_ship_date` is set to the `stick_date` advanced by the variety's `grow_cycle_days` days. The space ledger then cascades onto the zone: this batch's prior reservation is removed from the zone's `reserved_units`, the planted footprint (`started_count` multiplied by `container_footprint_units`) is added to the zone's `occupied_units`, the zone's `free_units` and `fill_state` are recomputed from scratch, and the zone's `version` is incremented by one.

### 3.5. Recording Climate, Irrigation, and Shrink

Throughout the grow cycle, a `ProductionTech` records **input-log events** against a batch — an append-only stream that documents how the crop was grown and how it fared. Each event names the `batch_id` it applies to and an `event_type`, one of `CLIMATE`, `IRRIGATION`, `FERTILIZER`, `SCOUTING`, or `GRADE`. The server stamps each event with a `recorded_at` taken from the logical clock. Depending on type, an event may carry a `temperature_c` (air temperature for a climate reading), `irrigation_liters` (water volume applied), `fertilizer_ppm_n` (feed nitrogen concentration), `mean_height_cm` (measured mean plant height, which is required for a grade event), `dead_observed` (units observed dead or unsaleable, which drives culling and defaults to 0), and a free-text `note`. Input-log events for a batch can be listed and filtered by `event_type`.

A `GRADE` event additionally updates the batch's own `mean_height_cm` to the measured value, which is what later grade gates read. Both `SCOUTING` and `GRADE` events can report shrink. When such an event reports a `dead_observed` greater than zero against a batch that is `GROWING`, `GRADING`, or `HELD`, the reported dead count is added to the batch's `cull_count`, and the batch's `live_count` is recomputed as `started_count` minus `cull_count` minus `shipped_count`. The system then evaluates cumulative shrink as `cull_count` divided by `started_count`. When that cumulative fraction reaches or exceeds one half, and the batch is in `GROWING`, `GRADING`, or `HELD`, the whole remaining stand is auto-culled by the system: the remaining `live_count` is moved into `cull_count` so the living stand reaches zero, the batch is driven to the terminal `CULLED` state, and the released footprint cascades onto the zone exactly as a manual cull does. The auto-cull boundary is inclusive — a cumulative shrink fraction of exactly one half triggers it.

### 3.6. Grading: The Branching Path to Saleable

Once a batch has grown, it must be **graded** before it can be sold, and grading is where the production pipeline forks. The grading sub-cycle uses two recomputations of `saleable_count` — a forward-looking provisional figure when grading begins, and a final realized figure when the grade passes.

A `ProductionTech` begins grading, advancing a batch from `GROWING` to `GRADING`. This is permitted only after the grow cycle is complete — the current logical-clock instant must be at or after the batch's `target_ship_date`, otherwise the request is rejected with `ERR_GROW_CYCLE_INCOMPLETE` — and only when at least one `GRADE` input-log event carrying a `mean_height_cm` has been recorded, otherwise it is rejected with `ERR_NO_GRADE_MEASUREMENT`. On entry to `GRADING`, the `saleable_count` is recomputed via the **provisional** calculation: it is the floor of the batch's current `live_count` multiplied by the variety's `ship_ready_min_live_pct`. This is a forward-looking projection of how many plants will pass grade, discounting the shrink that scouting is expected to remove but has not yet culled; whenever `ship_ready_min_live_pct` is below one, the provisional figure is strictly less than the eventual final figure. The `live_count` used here, and in every saleable computation, is `started_count` minus `cull_count` minus `shipped_count` measured at the moment the recomputation is triggered.

From `GRADING`, the `ProductionTech` finalizes the grade, and the batch forks one of two ways. The batch passes to `SALEABLE` only when both gates clear: the batch's `mean_height_cm` is at least the variety's `ship_ready_grade_min_height_cm`, and the live fraction — `live_count` divided by `started_count` — is at least the variety's `ship_ready_min_live_pct`. If the height gate fails, the rejection is `ERR_GRADE_BELOW_SPEC`; if the live-fraction gate fails, the rejection is `ERR_LIVE_PCT_BELOW_SPEC`. On passing, `saleable_count` is recomputed via the **final** calculation as exactly the batch's `live_count` — the realized graded stand after scouting culls, with no minimum-live discount applied — and this figure is immutable until the batch is regraded; the batch becomes publishable to the availability list. If, on the other hand, the batch's `mean_height_cm` is below the height spec, or its live fraction is below the minimum-live spec, finalization instead moves the batch to `HELD`: its `saleable_count` is set to 0 and it is held back for a re-grow with no availability published.

The grading fork supports a re-grade loop. A `HELD` batch can re-enter `GRADING` once a newer `GRADE` input-log event has been recorded since it entered `HELD` — absent such a fresh measurement the request is rejected with `ERR_NO_GRADE_MEASUREMENT` — and re-entry recomputes `saleable_count` provisionally, after which the held batch can again finalize to either `SALEABLE` or `HELD`. A `SALEABLE` batch can likewise be sent back to `GRADING` to re-grade after a fresh measurement, but only when no order line drawing on this batch's availability entry is in the `COMMITTED` state — an outstanding commitment blocks the regrade with `ERR_BATCH_HAS_COMMITMENTS` — and only when a newer `GRADE` event has been recorded since the batch entered `SALEABLE`, failing which the regrade is rejected with `ERR_NO_GRADE_MEASUREMENT`. On the next finalize, any availability entry's `published_quantity` is refreshed to reflect the new grade.

### 3.7. Culling a Batch and Loss Accounting

A `ProductionTech` may **cull** a batch — removing its whole living stand — from `GROWING`, `HELD`, or `SALEABLE`, driving it to the terminal `CULLED` state. The cull is requested with an optional `loss_basis`. From `GROWING`, the cull is blocked when a `COMMITTED` order line draws on the batch, rejected with `ERR_BATCH_HAS_COMMITMENTS`; from `SALEABLE`, the cull is likewise blocked when a `COMMITTED` order line draws on the batch's availability entry, with the same `ERR_BATCH_HAS_COMMITMENTS`; from `HELD`, no commitment can exist and the cull proceeds unconditionally.

In every cull, the count effects are the same: the batch's current `live_count` is added to its `cull_count`, its `live_count` is set to 0, and its `saleable_count` is set to 0. The released footprint then cascades onto the zone — the zone's `occupied_units` is reduced by the released footprint, its `free_units` and `fill_state` are recomputed, and its `version` is incremented by one. When the batch is culled from `SALEABLE`, there is an additional cascade: any `OPEN` availability entry for this batch is moved to `CLOSED` and its `published_quantity` is set to 0.

Culling values the lost plants. The number culled by this action — the living stand just before a full cull, or the `dead_observed` delta for a partial scouting cull — is costed two ways. The **standard** loss values each culled plant at the flat standard plug cost of 35 cents: the standard loss in cents is the number culled multiplied by 35, ignoring how many plugs were actually bought versus started. The **actual** loss amortizes the batch's real sourcing spend across the plants that were actually started: first compute a per-unit actual cost as the batch's `sourced_count` multiplied by 35 cents, divided by its `started_count`, rounded half up to a whole number of cents; then multiply that rounded per-unit cost by the number culled. The half-up rounding is applied to the per-unit amortization before multiplying by the number culled. The two variants coincide when `sourced_count` equals `started_count` and diverge whenever the batch was over-sourced, since the real per-plant cost is then higher than the flat plug cost.

### 3.8. Publishing Availability

Once a batch is `SALEABLE`, a `SalesCoordinator` publishes it to the **availability list** so that brokers can order against it. Publishing names the `batch_id` and a wholesale `unit_price_cents` per finished plant (at least 1). The batch must be `SALEABLE`, or the publish is rejected with `ERR_BATCH_NOT_SALEABLE`. On publish, the entry copies the batch's `variety_id`, snapshots its `published_quantity` from the batch's current `saleable_count`, sets `committed_quantity` to 0 and `available_quantity` equal to `published_quantity`, and opens in `OPEN` status. The entry's `available_quantity` is always its `published_quantity` minus its `committed_quantity`, the sellable remainder.

An availability entry runs `OPEN` → `CLOSED`. A `SalesCoordinator` may manually close an entry so it accepts no further commitments. As described in Section 3.6, a finalize after a regrade refreshes the entry's `published_quantity`; as described in Section 3.7, culling the underlying batch from `SALEABLE` closes the entry and zeroes its published quantity. Entries can be read with their committed and available quantities and listed and filtered by `status`, `variety_id`, and `batch_id`.

### 3.9. Brokers and the Credit Ledger

A **broker** is an external re-wholesaler that places orders. A `SalesCoordinator` creates a broker with a `company_name`, a `contact_email`, a two-letter `ship_to_state` destination code (two uppercase letters), and a `credit_limit_cents` open-order credit ceiling (at least 0). A new broker opens `ACTIVE` with `open_balance_cents` of 0. The `open_balance_cents` is the running ledger of the sum of `order_total_cents` over this broker's orders that are `CONFIRMED` or `FULFILLING` and not yet fully shipped; it rises when an order is confirmed and falls when an order ships out or is cancelled.

A broker's `status` runs `ACTIVE` → `ON_HOLD` and back. A `SalesCoordinator` may place a broker `ON_HOLD`, which blocks new order confirmations, and may reinstate an `ON_HOLD` broker to `ACTIVE`. A broker reads its own ledger; brokers can be listed and filtered by `status`.

### 3.10. Building and Pricing an Order

A broker order assembles lines, prices them, and — once confirmed — commits saleable inventory and charges broker credit. A `SalesCoordinator` or a `Broker` creates an order by naming the `broker_id` and a `requested_ship_date`; a `Broker` may only create an order whose `broker_id` equals its own identity. The order opens in `DRAFT` with all totals at 0.

While the order is `DRAFT`, lines are added and removed. Adding a line names the `availability_entry_id` to draw from and the `quantity` of finished plants requested (at least 1). On creation the line snapshots its `unit_price_cents` from the named availability entry, computes its `extended_cents` as `quantity` multiplied by `unit_price_cents`, and opens in `PENDING` status; its `shipped_quantity` starts at 0 and the line also carries the `order_id` of its parent. Each line add recomputes the order totals and increments the order's `version` by one. Removing a `PENDING` line from a `DRAFT` order moves it to `RELEASED`, recomputes the order totals, and again increments the order's `version` by one. Lines can be read individually or listed under their order, and can be listed and filtered by `order_id`, `availability_entry_id`, and `status`.

Order totals are recomputed on every line add or remove while `DRAFT`, and finalized at confirm time, by the order-pricing calculation, whose steps are evaluated in this exact order. First, for each line, the extended price is the line's `quantity` multiplied by its `unit_price_cents` — exact integer cents, no rounding. Second, the `order_subtotal_cents` is the sum of those exact line extended prices over all lines. Third, the `freight_cents` is computed from the total finished-plant count and the broker's destination, as detailed below. Fourth, a volume rebate is computed against the summed subtotal: let the total units be the sum of every line's `quantity`; if the total units are at least 5000, the rebate is the `order_subtotal_cents` multiplied by five hundredths, rounded half up; otherwise if the total units are at least 2000, the rebate is the `order_subtotal_cents` multiplied by two hundredths, rounded half up; otherwise the rebate is 0. The rebate's rounding is applied once to the summed subtotal — sum first, then round — not per line. Fifth and finally, the `order_total_cents` is the `order_subtotal_cents` minus the volume rebate plus the `freight_cents`.

Freight itself is a function of three interacting inputs: the order's total finished-plant count, the destination zone band derived from the broker's `ship_to_state`, and a per-rack stepping. The destination resolves to one of three bands. When the broker's `ship_to_state` equals the origin reference state `OR`, the band is `IN_STATE`. When it is one of `WA`, `CA`, `ID`, or `NV`, the band is `NEIGHBOR`. Any other destination is the `FAR` band. Each band carries a base charge, a per-rack charge, a floor, and a cap, all in cents. The `IN_STATE` band has a base of 2500, a per-rack of 600, a floor of 2500, and a cap of 9000. The `NEIGHBOR` band has a base of 4000, a per-rack of 1100, a floor of 4000, and a cap of 16000. The `FAR` band has a base of 7000, a per-rack of 1900, a floor of 7000, and a cap of 28000. Racks are counted at 50 finished plants per rack, rounded up: the rack count is the ceiling of the total units divided by 50. The raw freight is the band's base plus the rack count multiplied by the band's per-rack charge. The final `freight_cents` clamps that raw figure into the band's range: it is the smaller of the band cap and the larger of the band floor and the raw freight. The clamp is applied after the raw freight is computed, never below the floor and never above the cap.

### 3.11. Confirming an Order: Commitment and Credit

Confirming an order is the pivot from a tentative draft to a binding commitment against scarce saleable inventory and broker credit. Only a `SalesCoordinator` confirms; the request carries `expected_order_version`. Advancing a `DRAFT` order to `CONFIRMED` is guarded, in order, by these business preconditions after the universal checks. The order must have at least one line, or it is rejected with `ERR_EMPTY_ORDER`. The broker must be `ACTIVE`, or it is rejected with `ERR_BROKER_ON_HOLD`. For each line, the requested `quantity` must not exceed the drawn-on entry's `available_quantity`, or the confirm is rejected with `ERR_INSUFFICIENT_AVAILABILITY`. The broker's `open_balance_cents` plus this order's `order_total_cents` must be at most the broker's `credit_limit_cents`, or the confirm is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. Finally, as the last gate, `expected_order_version` must equal the order's current `version`, or the confirm is rejected with `ERR_STALE_VERSION`.

On a successful confirm, each line moves from `PENDING` to `COMMITTED`, and for each line the drawn-on availability entry has its `committed_quantity` increased by the line's `quantity` and its `available_quantity` recomputed — a cascade onto the entry. The `order_subtotal_cents`, `freight_cents`, and `order_total_cents` are finalized by the order-pricing calculation. The broker's `open_balance_cents` is increased by the order's `order_total_cents` — a cascade onto the broker — and the order's `version` is incremented by one.

### 3.12. Cancelling an Order

A `SalesCoordinator` cancels an order to unwind it. Cancelling a `DRAFT` order simply moves it to the terminal `CANCELLED` state and releases its lines: each `PENDING` line moves to `RELEASED`, and because no commitments existed there is no ledger change. Cancelling a `CONFIRMED` order is a full compensation of the confirm: it is permitted only when no shipment for this order is `DISPATCHED`, otherwise it is rejected with `ERR_ORDER_HAS_SHIPMENT`. On cancellation of a confirmed order, each `COMMITTED` line moves to `RELEASED`, every drawn-on availability entry has its `committed_quantity` reduced by that line's `quantity` and its `available_quantity` recomputed (a cascade onto the entry), the broker's `open_balance_cents` is reduced by the order's `order_total_cents` (a cascade onto the broker, reversing the confirm), and the order moves to `CANCELLED`. The order's `version` is incremented.

### 3.13. Phytosanitary Certificates

Some varieties may not cross state lines without a **phytosanitary certificate** attesting they were inspected and cleared. A `SalesCoordinator` issues a certificate for a broker destination by naming the `broker_id`, the state-issued `certificate_number` (unique among certificates that are not expired), the two-letter `origin_state` issuing code (two uppercase letters), and the `valid_until` expiry instant on or before which a shipment must dispatch. On issue, the certificate copies its `destination_state` from the broker's `ship_to_state`, stamps its `inspected_at` from the logical clock, and opens in `VALID` status.

A certificate's `status` runs `VALID` → `CONSUMED` → back to `VALID`, or `VALID` → `EXPIRED` (terminal). The system consumes a `VALID` certificate when a shipment that attaches it dispatches, and restores a `CONSUMED` certificate to `VALID` when that shipment is voided. During the operational checkpoint, any `VALID` certificate whose `valid_until` is strictly before the current logical-clock instant is moved to `EXPIRED`. Certificates can be read and listed and filtered by `broker_id` and `status`.

### 3.14. Shipments: Dispatch, Stock Deduction, and Compensation

A **shipment** dispatches finished plants against a confirmed order. A `SalesCoordinator` creates a shipment in `DRAFT` by naming the `order_id`, an optional `phyto_certificate_id`, and the set of `lines` with their quantities to dispatch; its `ship_units` is the sum of the requested line quantities, validated to not exceed the remaining committed quantity, and its `shipped_at` is stamped only at dispatch. Shipments can be read and listed and filtered by `order_id`, `status`, and `phyto_certificate_id`.

Dispatching a shipment moves it from `DRAFT` to `DISPATCHED` and is the operation that actually deducts living stock and advances the order. It is guarded, after the universal checks, by these preconditions. The order must be `CONFIRMED` or `FULFILLING`, or the dispatch is rejected with `ERR_ORDER_NOT_FULFILLABLE`. Every line in the dispatch must draw on a batch that is `SALEABLE`, or it is rejected with `ERR_BATCH_NOT_SALEABLE`, and that batch's `live_count` must be at least the remaining quantity on the line, or it is rejected with `ERR_INSUFFICIENT_LIVE_STOCK`. When any line's variety has `requires_phyto` set, the shipment must carry a `phyto_certificate_id` whose certificate is present and `VALID`, whose `destination_state` equals the broker's `ship_to_state`, and whose `valid_until` is at or after the current logical-clock instant: a missing certificate is rejected with `ERR_PHYTO_REQUIRED`, a non-`VALID` (already-consumed) certificate with `ERR_PHYTO_INVALID`, an expired or past-`valid_until` certificate with `ERR_PHYTO_EXPIRED`, and a destination mismatch with `ERR_PHYTO_DESTINATION_MISMATCH`.

On dispatch, the count and ledger cascades fire together. For each dispatched line, the line's `shipped_quantity` is increased by the dispatched quantity, the drawn-on batch's `shipped_count` is increased by that quantity, and the batch's `live_count` is reduced by that quantity. The freed footprint cascades onto the zone — the zone's `occupied_units` is reduced by the shipped footprint, its `free_units` and `fill_state` are recomputed, and its `version` is incremented by one. The order advances: a `CONFIRMED` order moves to `FULFILLING` on its first dispatch, and once every `COMMITTED` line has its `shipped_quantity` equal to its `quantity` the order is automatically driven to the terminal `SHIPPED` state, with each fully shipped line moving to `SHIPPED`. When the order reaches `SHIPPED`, the broker's `open_balance_cents` is reduced by the order's `order_total_cents`, releasing that credit — a cascade onto the broker. If a certificate was attached, it is consumed: a `VALID` certificate moves to `CONSUMED`. The shipment's `shipped_at` is stamped from the logical clock and its `ship_units` recorded.

Dispatch can be undone. A `SalesCoordinator` voids a `DISPATCHED` shipment, moving it to the terminal `VOIDED` state, permitted only when the order is not already `SHIPPED`-closed beyond the reversal point — an attempt to void after the order has closed is rejected with `ERR_ORDER_ALREADY_CLOSED`. Voiding is a full compensation of the dispatch: for each line the `shipped_quantity` is reduced by the dispatched quantity, the batch's `shipped_count` is reduced by that quantity, and the batch's `live_count` is restored by that quantity. The restored footprint cascades onto the zone — the zone's `occupied_units` is increased by the restored footprint, its `free_units` and `fill_state` are recomputed, and its `version` is incremented by one. The order reverts from its shipped or fulfilling posture, and if the broker's credit ledger had been released on closing it is restored. If a certificate had been `CONSUMED` by this shipment, it is reverted from `CONSUMED` back to `VALID`.

### 3.15. The Operational Checkpoint

The system exposes a `GrowerManager`-only operational checkpoint that sweeps time-driven state forward against the current logical clock. Running the checkpoint moves every `VALID` phytosanitary certificate whose `valid_until` is strictly before the current logical-clock instant to `EXPIRED`, and auto-culls every `GROWING`, `GRADING`, or `HELD` batch whose cumulative shrink — `cull_count` divided by `started_count` — has reached or exceeded one half, driving each such batch to `CULLED` with the same zone-release cascade a manual cull performs. A separate `GrowerManager`-only test-driving capability sets the server's logical clock to a supplied `to_iso8601` instant, governing every recorded timestamp and every expiry and grow-cycle comparison thereafter, as described in Section 2.4.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions, line removals, and the operational sweep — return a `200 OK` status code. All paths are mounted under the `/nursery` prefix except the clock control endpoint as shown.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nursery/varieties` | Create a crop variety in DRAFT | GrowerManager |
| GET | `/nursery/varieties/{id}` | Get one variety | GrowerManager, ProductionTech, SalesCoordinator, Broker |
| GET | `/nursery/varieties` | List varieties (paginated; filter by status) | GrowerManager, ProductionTech, SalesCoordinator, Broker |
| POST | `/nursery/varieties/{id}/activate` | Activate a variety (DRAFT/SUSPENDED to ACTIVE) | GrowerManager |
| POST | `/nursery/varieties/{id}/suspend` | Suspend an ACTIVE variety | GrowerManager |
| POST | `/nursery/varieties/{id}/retire` | Retire a variety (terminal) | GrowerManager |
| POST | `/nursery/zones` | Create a greenhouse zone | GrowerManager |
| GET | `/nursery/zones/{id}` | Get one zone with live occupancy fields | GrowerManager, ProductionTech, SalesCoordinator |
| GET | `/nursery/zones` | List zones (paginated; filter by status, fill_state) | GrowerManager, ProductionTech, SalesCoordinator |
| GET | `/nursery/zones/{id}/batches` | List batches assigned to a zone | GrowerManager, ProductionTech, SalesCoordinator |
| POST | `/nursery/zones/{id}/quarantine` | Quarantine a zone (blocks new placement) | GrowerManager |
| POST | `/nursery/zones/{id}/release-quarantine` | Release a quarantined zone | GrowerManager |
| POST | `/nursery/zones/{id}/decommission` | Decommission an empty zone (terminal) | GrowerManager |
| POST | `/nursery/batches` | Create a PLANNED batch (reserves zone footprint) | GrowerManager, ProductionTech |
| GET | `/nursery/batches/{id}` | Get one batch with computed counts | GrowerManager, ProductionTech, SalesCoordinator |
| GET | `/nursery/batches` | List batches (filter by status, variety_id, zone_id) | GrowerManager, ProductionTech, SalesCoordinator |
| POST | `/nursery/batches/{id}/transplant` | Transplant a PLANNED batch (PLANNED to GROWING); OCC-guarded on zone | ProductionTech |
| POST | `/nursery/batches/{id}/start-grading` | Begin grading; recompute provisional saleable_count | ProductionTech |
| POST | `/nursery/batches/{id}/finalize-grade` | Finalize grade: pass to SALEABLE or fail to HELD | ProductionTech |
| POST | `/nursery/batches/{id}/cull-batch` | Cull the whole living stand of a batch (to CULLED) | ProductionTech |
| POST | `/nursery/batches/{id}/void` | Void a PLANNED batch (to VOIDED); release reservation | GrowerManager |
| GET | `/nursery/batches/{id}/input-logs` | List input-log events for a batch | GrowerManager, ProductionTech, SalesCoordinator |
| POST | `/nursery/batches/{id}/input-logs` | Record a climate/irrigation/fertilizer/scouting/grade event | ProductionTech |
| POST | `/nursery/brokers` | Create a broker account | SalesCoordinator |
| GET | `/nursery/brokers/{id}` | Get one broker with open-balance ledger | SalesCoordinator, Broker |
| GET | `/nursery/brokers` | List brokers (paginated; filter by status) | SalesCoordinator |
| POST | `/nursery/brokers/{id}/hold` | Put a broker ON_HOLD | SalesCoordinator |
| POST | `/nursery/brokers/{id}/reinstate` | Reinstate an ON_HOLD broker | SalesCoordinator |
| POST | `/nursery/availability` | Publish a saleable batch to the availability list | SalesCoordinator |
| GET | `/nursery/availability/{id}` | Get one availability entry | SalesCoordinator, Broker |
| GET | `/nursery/availability` | List availability entries (filter by status, variety_id, batch_id) | SalesCoordinator, Broker |
| POST | `/nursery/availability/{id}/close` | Manually close an availability entry | SalesCoordinator |
| POST | `/nursery/orders` | Create a DRAFT broker order | SalesCoordinator, Broker |
| GET | `/nursery/orders/{id}` | Get one order with computed totals | SalesCoordinator, Broker |
| GET | `/nursery/orders` | List orders (paginated; filter by status, broker_id) | SalesCoordinator, Broker |
| POST | `/nursery/orders/{id}/lines` | Add a line to a DRAFT order; recompute totals | SalesCoordinator, Broker |
| GET | `/nursery/orders/{id}/lines` | List lines on an order | SalesCoordinator, Broker |
| GET | `/nursery/order-lines/{id}` | Get one order line | SalesCoordinator, Broker |
| GET | `/nursery/order-lines` | List order lines (filter by order_id, availability_entry_id, status) | SalesCoordinator, Broker |
| DELETE | `/nursery/order-lines/{id}` | Remove a PENDING line from a DRAFT order; recompute totals | SalesCoordinator, Broker |
| POST | `/nursery/orders/{id}/confirm` | Confirm a DRAFT order (commit lines, charge credit); OCC-guarded on order | SalesCoordinator |
| POST | `/nursery/orders/{id}/cancel` | Cancel a DRAFT or CONFIRMED order; release commitments and credit | SalesCoordinator |
| POST | `/nursery/phyto-certificates` | Issue a phytosanitary certificate for a broker destination | SalesCoordinator |
| GET | `/nursery/phyto-certificates/{id}` | Get one phyto certificate | SalesCoordinator, Broker |
| GET | `/nursery/phyto-certificates` | List phyto certificates (filter by broker_id, status) | SalesCoordinator, Broker |
| POST | `/nursery/shipments` | Create a DRAFT shipment naming lines and quantities to dispatch | SalesCoordinator |
| GET | `/nursery/shipments/{id}` | Get one shipment | SalesCoordinator, Broker |
| GET | `/nursery/shipments` | List shipments (filter by order_id, status, phyto_certificate_id) | SalesCoordinator, Broker |
| POST | `/nursery/shipments/{id}/dispatch` | Dispatch a DRAFT shipment (DRAFT to DISPATCHED) | SalesCoordinator |
| POST | `/nursery/shipments/{id}/void` | Void a DISPATCHED shipment (compensation) | SalesCoordinator |
| POST | `/nursery/run-ops` | Run the ops checkpoint: expire certs, sweep auto-cull | GrowerManager |
| POST | `/_clock/set_current_utc` | Test-driving: set the server logical clock | GrowerManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_CULTIVAR` | 409 Conflict |
| `ERR_VARIETY_NOT_ACTIVE` | 409 Conflict |
| `ERR_VARIETY_IN_USE` | 409 Conflict |
| `ERR_ZONE_NOT_OPEN` | 409 Conflict |
| `ERR_ZONE_NOT_EMPTY` | 409 Conflict |
| `ERR_CLIMATE_MISMATCH` | 409 Conflict |
| `ERR_INVALID_STARTED_COUNT` | 422 Unprocessable Entity |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ZONE_TIGHT_FILL_CAP` | 409 Conflict |
| `ERR_GROW_CYCLE_INCOMPLETE` | 409 Conflict |
| `ERR_NO_GRADE_MEASUREMENT` | 409 Conflict |
| `ERR_GRADE_BELOW_SPEC` | 409 Conflict |
| `ERR_LIVE_PCT_BELOW_SPEC` | 409 Conflict |
| `ERR_BATCH_HAS_COMMITMENTS` | 409 Conflict |
| `ERR_BATCH_NOT_SALEABLE` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 409 Conflict |
| `ERR_BROKER_ON_HOLD` | 409 Conflict |
| `ERR_INSUFFICIENT_AVAILABILITY` | 409 Conflict |
| `ERR_INSUFFICIENT_LIVE_STOCK` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_ORDER_NOT_FULFILLABLE` | 409 Conflict |
| `ERR_ORDER_HAS_SHIPMENT` | 409 Conflict |
| `ERR_ORDER_ALREADY_CLOSED` | 409 Conflict |
| `ERR_PHYTO_REQUIRED` | 409 Conflict |
| `ERR_PHYTO_INVALID` | 409 Conflict |
| `ERR_PHYTO_EXPIRED` | 409 Conflict |
| `ERR_PHYTO_DESTINATION_MISMATCH` | 409 Conflict |

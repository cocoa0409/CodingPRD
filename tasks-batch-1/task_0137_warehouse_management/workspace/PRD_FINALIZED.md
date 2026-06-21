# Warehouse Management API — Product Requirements Document

## 1. Introduction

This document specifies the behaviour of a Warehouse Management System (WMS) exposed as a REST API. The platform models the full physical flow of goods through a distribution centre: inbound goods arrive against an Advance Shipping Notice (ASN), are received onto license plates (the barcode-tracked unit-load containers the floor staff scan), and are then either put away into deep reserve storage or cross-docked straight to an outbound staging lane. On the outbound side, customer orders are gathered into picking waves, inventory is reserved against specific license plates, and pickers confirm each pick under a pick-to-light protocol before the order ships. Running alongside both flows are two continuous inventory-hygiene processes: ABC-cadenced cycle counting, which periodically reconciles the system's recorded quantity against a physical count, and min/max replenishment, which refills forward pick faces from deep reserve before they run dry.

The system is built around the tension between *quota allocation* — never reserving inventory the warehouse does not physically hold — and *workflow orchestration*, where a single floor action ripples through several entities at once (a pick confirm advances a task, commits a reservation, stages a license plate, and may close out both the order and the wave). Correctness therefore depends on disciplined separation of duties between floor roles, optimistic concurrency control on the two contended write paths, and a set of derived quantity fields that must be recomputed deterministically after every inventory movement. The remainder of this document defines the global contracts (Section 2), the business workflows where the bulk of the domain logic lives (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the individual actor, and `X-User-Role`, naming the actor's role. The six recognized roles are spelled exactly as `PlatformAdmin`, `ReceivingClerk`, `PutawayOperator`, `Picker`, `WavePlanner`, and `InventoryController`.

On any mutating request, if either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Read operations (GET) may be performed by any authenticated role permitted to see that resource family; the per-endpoint authorization is enumerated in Section 4.

All six roles use an **opaque** identity model. In every case `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and the server never compares it to an entity's `id` for ownership purposes. The server does, however, *record* the identifier where a scaffolded transition writes it: when a `ReceivingClerk` posts the first receipt against an ASN, the server pins that clerk's `X-User-ID` onto the ASN as `received_by_user_id`; when an `InventoryController` submits a physical count, the server pins that controller's `X-User-ID` onto the count as `counted_by_user_id`. These two recorded identifiers are not ownership keys — they exist solely to feed the segregation-of-duties checks described in Section 3.

The role responsibilities are segregated by duty. A `PlatformAdmin` is the operational super-user: it alone may configure SKUs and drive the test clock, it may also configure locations, and it may read everything. A `ReceivingClerk` operates the inbound dock — announcing ASNs, adding expected lines, posting receipts, and closing or cancelling ASNs. A `PutawayOperator` executes putaway floor moves and completes replenishment moves. A `Picker` executes pick-to-light picks, short-picks, and ships picked orders. A `WavePlanner` builds and releases waves, manages outbound orders, and creates and cancels manual reservations. An `InventoryController` runs cycle counts, approves or rejects count variances, creates and manages replenishment tasks, and configures locations (including blocking and unblocking them).

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

All list endpoints are paginated through two query parameters. The `limit` parameter controls the page size; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter controls how many records are skipped before the page begins; it defaults to 0 and has a minimum of 0. List results are returned in ascending `created_at` order — that is, oldest record first. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the full number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id`, formatted as a UUID with no type prefix, generated by the server at creation time and never supplied by the client. Most resources also carry three further common properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at its initial value on creation and is incremented by exactly one on every mutation that changes the resource. The `created_at` value is fixed at creation and never changes; `updated_at` is refreshed on every mutation.

One entity is exempt from the full common-property set. A `ReceiptEvent` is an append-only inbound record and carries only `id` and `created_at`; it has neither an `updated_at` nor a `version`, because a receipt event is never modified after it is written. All other entities — `Sku`, `Location`, `LicensePlate`, `InboundAsn`, `AsnLine`, `PutawayTask`, `OutboundOrder`, `OrderLine`, `InventoryAllocation`, `Wave`, `PickTask`, `CycleCount`, and `ReplenishmentTask` — carry the full set including `updated_at` and `version`.

### 2.5. Nested Resource Retrieval and Path Validation

Many resources are reachable both directly and through a parent-scoped collection path. When a request addresses a nested path, the server validates each path segment from left to right: a parent that does not resolve to an existing entity produces `ERR_NOT_FOUND` (HTTP 404) before any child segment is examined, and likewise a child id that does not resolve produces `ERR_NOT_FOUND`. This left-to-right rule applies to all reference ids appearing in a path or body — every referenced id must resolve to an existing entity of the expected type.

### 2.6. Derived Quantity Fields and Recomputation

Several quantity fields are not supplied by clients but are computed by the server and kept reconciled with the underlying physical state. On `Sku`, the fields `on_hand_qty`, `available_qty`, and `cycle_count_due` are all derived; on `Location`, `used_volume_cm3` is derived; on `AsnLine`, `received_qty` and `line_status` are derived; on `OrderLine`, `allocated_qty` and `picked_qty` are derived. Each of these is recomputed deterministically whenever an event changes its inputs (the exact formulas live in Section 3), and the recomputed values are reflected immediately — the system uses an immediate-consistency model, so a read always observes the fully reconciled state. When a single-resource fetch of a `Sku`, `Location`, `AsnLine`, `OrderLine`, `ReceiptEvent` line, or related resource is performed, the server recomputes the derived fields on that read so the returned values are current.

### 2.7. Volume Precision and Rounding

All cubic-volume figures are tracked in cubic centimetres. A `Location`'s consumed capacity, `used_volume_cm3`, is the sum across the license plates resting at that location of each plate's eaches multiplied by the per-each volume of the plate's SKU. This sum is computed in full first and then rounded once, half-up, to two decimal places — the rounding is applied a single time to the completed sum, never per line. All other quantities in the system (eaches on hand, ordered, allocated, picked, received, variance) are exact integers and are never rounded.

### 2.8. Optimistic Concurrency Control

Two write paths are guarded by optimistic concurrency control (OCC), and only these two. Each requires the client to submit the version of the parent resource it last observed, and rejects the write if that version no longer matches the resource's current `version`.

The first guarded path is **wave release**. A release request must carry `expected_wave_version`, which must equal the target wave's current `version`. Releasing a wave synthesizes a fresh set of reservations against the available license-plate pool, so a release that legitimately ran earlier — because an order was added or a prior release already advanced the wave — leaves a later client's view of the wave out of date. If `expected_wave_version` does not match the wave's current `version`, the release is rejected with `ERR_STALE_WAVE_VERSION` (HTTP 412), preventing the client from acting on a wave it has not re-read.

The second guarded path is **manual allocation creation**. A request to create an `InventoryAllocation` must carry `expected_lpn_version`, which must equal the target license plate's current `version`. A reservation supersedes the plate's prior free-quantity view; if the plate's `version` has advanced since the client read it — because another reservation, a pick confirm, or a replenishment drain already changed its quantity or disposition — the client's available-quantity view is out of date and the create is rejected with `ERR_STALE_LPN_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field. Endpoints outside these two paths perform no version check.

### 2.9. Segregation of Duties

To prevent a single individual from both recording and approving an inventory adjustment, cycle-count approval and rejection are subject to a segregation-of-duties constraint. The actor who approves or rejects a count must not be the actor who submitted that count (the `X-User-ID` recorded as `counted_by_user_id`), and — on approval specifically — must additionally not be a `ReceivingClerk` who received any ASN that fed inventory at the counted location (the `X-User-ID` recorded as `received_by_user_id` on such an ASN). A violation of either separation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Volume Capacity as Shared Aggregate

Each `Location` has a fixed cubic capacity, `max_volume_cm3`. Storage capacity is a shared aggregate: any inbound physical move into a location — completing a putaway, cross-docking on ASN close, or completing a replenishment — must not push the location's `used_volume_cm3` above `max_volume_cm3`. The check compares the location's existing consumed volume plus the incoming plate's volume against the ceiling; if the combined figure would exceed `max_volume_cm3`, the move is rejected with `ERR_LOCATION_CAPACITY` (HTTP 409). A location whose `status` is `BLOCKED` rejects all inbound moves regardless of capacity.

### 2.11. Validation Ordering

When several checks could fire on a single request, they are evaluated in a fixed priority order so the rejection reason is deterministic. The order is: first, authentication of the `X-User-ID`/`X-User-Role` headers (`ERR_UNAUTHENTICATED`); second, role authorization (`ERR_FORBIDDEN_ROLE`); third, existence of every referenced id, validated left-to-right in the path (`ERR_NOT_FOUND`); fourth, request-body well-formedness — required fields present and correctly typed, and any enum value within its declared set (`ERR_INVALID_REQUEST`); fifth, the state-machine precondition that the target entity is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); sixth, the OCC version check on the two guarded paths (`ERR_STALE_WAVE_VERSION` or `ERR_STALE_LPN_VERSION`); seventh, segregation of duties on count approval and rejection (`ERR_SEGREGATION_OF_DUTIES`); eighth, cross-entity state guards (`ERR_CROSS_ENTITY_STATE`); and thereafter the remaining domain-specific business constraints described in Section 3 (uniqueness, capacity, pick-face dedication, replenishment eligibility, availability, open-line, selector-emptiness, and pick-to-light checks). The general rule is that an earlier check, when it fires, masks all later ones.

## 3. Business Logic & Workflows

### 3.1. SKU and Location Configuration

Before any goods move, the catalogue and the floor map must exist. A `PlatformAdmin` registers each stock-keeping unit, supplying its merchandising `sku_code`, a free-text `description`, its velocity classification `abc_class` (one of `A`, `B`, or `C`), the cubic volume of a single each as `each_volume_cm3`, and the replenishment band given by `min_qty` and `max_qty`. The `sku_code` must be unique across all SKUs and non-empty; a collision is rejected with `ERR_DUPLICATE_CODE`. The `each_volume_cm3` must be greater than zero, `min_qty` must be at least zero, and `max_qty` must be strictly greater than `min_qty`. A newly created SKU starts with `on_hand_qty` at zero, `available_qty` at zero, and `cycle_count_due` set to true.

A SKU's three derived figures are kept continuously reconciled. The `on_hand_qty` is the total eaches across every license plate of that SKU whose disposition is `STORED`, `ALLOCATED`, or `PICKED_STAGED`; plates that are `PUTAWAY_PENDING`, `SHIPPED`, or `DEPLETED` are excluded from the on-hand total. It is recomputed on every change to a plate's quantity or disposition. The `available_qty` is the SKU's `on_hand_qty` minus the sum of `allocated_qty` across that SKU's allocations that are `RESERVED` or `COMMITTED`; available quantity may reach zero but is never negative, a floor protected by the allocation availability check. The `cycle_count_due` flag is described under cycle counting below.

Locations are created by a `PlatformAdmin` or an `InventoryController`. Each location carries a unique, non-empty `location_code`, a functional `zone` (one of `RECEIVING`, `RESERVE`, `PICK_FACE`, `CROSS_DOCK`, or `STAGING`), and a cubic capacity `max_volume_cm3` greater than zero. A location's operational `status` is either `AVAILABLE` or `BLOCKED` and defaults to `AVAILABLE`. Its consumed-capacity figure `used_volume_cm3` initializes to zero and is recomputed on every plate move in or out, as the sum over the plates resting there (disposition `STORED`, `ALLOCATED`, or `PICKED_STAGED`) of each plate's quantity times the SKU's per-each volume, the completed sum rounded half-up once to two decimal places. A duplicate `location_code` is rejected with `ERR_DUPLICATE_CODE`.

A `PICK_FACE` location may be dedicated as the single forward pick face of exactly one SKU; in that case the creating request supplies `pick_face_for_sku_id` naming that SKU, and the field is null for all other locations. A pick face may be claimed by at most one SKU: an attempt to create a location dedicating the same pick face to a second, different SKU is rejected with `ERR_PICKFACE_TAKEN`. An `InventoryController` may take a damaged bin out of service, transitioning its `status` from `AVAILABLE` to `BLOCKED`, and may later return it to service with the reverse `BLOCKED` to `AVAILABLE` transition.

### 3.2. Inbound: ASN Announcement, Lines, and Receiving

The inbound flow begins when a `ReceivingClerk` announces an expected shipment. Announcing creates an `InboundAsn` in status `ANNOUNCED` with a unique, non-empty `asn_number`, the originating `supplier_name`, and a `handling_mode` of either `PUTAWAY` (the default, routing received goods into storage) or `CROSS_DOCK` (routing them straight to an outbound staging lane). A duplicate `asn_number` is rejected with `ERR_DUPLICATE_CODE`. While the ASN is still `ANNOUNCED`, the clerk adds expected lines; each line names the expected `sku_id` and an `expected_qty` greater than zero, and is created with `line_status` of `OPEN` and `received_qty` of zero. Each line belongs to its parent ASN via `asn_id`.

Receiving against the ASN is where physical goods enter the system. The clerk posts a receipt naming the `asn_line_id` being received against and the `received_qty` for that event, which must be greater than zero. The first receipt against an `ANNOUNCED` ASN advances it from `ANNOUNCED` to `RECEIVING` and pins the clerk's `X-User-ID` onto the ASN as `received_by_user_id`; subsequent receipts post against the same `RECEIVING` ASN without changing its status. The referenced line must belong to this ASN. Every receipt has the same effects: it appends a `ReceiptEvent` (carrying its `asn_id`, `asn_line_id`, the system-set `lpn_id` of the plate it minted, and its `received_qty`); it mints a new `LicensePlate` for the line's SKU with `qty` equal to the received eaches, `source_asn_id` set to this ASN, `disposition` of `PUTAWAY_PENDING`, and `location_id` null; it recomputes the line's `received_qty` as the sum of all that line's receipt events; it re-derives the line's `line_status`; and it recomputes the SKU's `on_hand_qty`. Every receipt increments the ASN's `version`.

A line's `line_status` is derived from the comparison of its `received_qty` against its `expected_qty`: while `received_qty` is strictly less than `expected_qty` the line is `OPEN`; when `received_qty` exactly equals `expected_qty` the line is `SATISFIED`; and when `received_qty` is strictly greater than `expected_qty` the line is `OVER`. The `SATISFIED` band is exact equality only — neither under nor over receipt counts as satisfied.

### 3.3. Closing the Inbound Fork: Putaway versus Cross-Dock

Closing receiving is the fork in the inbound road, and the two branches diverge sharply. A clerk may close an ASN only from `RECEIVING`, and only when every line is fully accounted for — every `AsnLine` must have `line_status` of `SATISFIED` or `OVER`, with no line still `OPEN`. If any line remains `OPEN` (its `received_qty` below its `expected_qty`), the close is rejected with `ERR_ASN_LINES_OPEN`.

When the ASN's `handling_mode` is `PUTAWAY`, closing advances the ASN from `RECEIVING` to `PUT_AWAY` and creates one `PutawayTask` (in status `CREATED`) for every `PUTAWAY_PENDING` license plate minted from this ASN. No plate moves yet — the plates wait in `PUTAWAY_PENDING` for the putaway floor work described in Section 3.4. When the ASN's `handling_mode` is `CROSS_DOCK`, closing instead advances the ASN from `RECEIVING` to `CROSS_DOCKED` and, for every `PUTAWAY_PENDING` plate of this ASN, moves it directly into a `CROSS_DOCK`-zone location chosen by the cross-dock selector: each plate's `disposition` becomes `STORED`, its `location_id` is set to the chosen lane, and that location's `used_volume_cm3` is recomputed. Crucially, the cross-dock branch creates **no** putaway tasks; the plate lands `STORED` in a cross-dock lane immediately. Both branches increment the ASN's `version`.

The cross-dock selector chooses among the `AVAILABLE` locations whose `zone` is `CROSS_DOCK` and whose residual capacity — `max_volume_cm3` minus current `used_volume_cm3` — is at least the plate's required volume (its `qty` times the SKU's `each_volume_cm3`). Among those eligible lanes it prefers the **most open** one: it ranks candidates by largest residual capacity first, with the residual measured to two decimal places, and breaks ties by oldest `created_at` first. (Note the deliberate contrast with the putaway selector in Section 3.4, which prefers the *tightest* fit — the two slotting strategies rank residual capacity in opposite directions.)

A cross-docked ASN is finalized by a separate clerk action that advances it from `CROSS_DOCKED` to `CLOSED`. A putaway ASN, by contrast, auto-closes: once every putaway task spawned from the ASN has reached `COMPLETED` or `CANCELLED`, with at least one `COMPLETED`, the system bubbles the ASN from `PUT_AWAY` to `CLOSED`. Each of these transitions increments the ASN's `version`. Finally, an ASN that is still `ANNOUNCED` with no receipts posted may be cancelled, moving it from `ANNOUNCED` to `CANCELLED`; this transition also increments the ASN's `version`.

### 3.4. Putaway: Slotting Goods into Storage

A putaway task ferries one license plate from the receiving dock into a storage bin. Each task references the `lpn_id` of the plate to be put away, and its `target_location_id` is null until the destination is chosen at assignment. A `PutawayOperator` first assigns the task, advancing it from `CREATED` to `ASSIGNED`. Assignment invokes the putaway selector to choose the destination; if the selector returns an empty candidate set, the assign is rejected with `ERR_NO_PUTAWAY_LOCATION` and the task stays `CREATED`. On a successful assign the chosen location is written to `target_location_id`.

The putaway selector first computes the plate's required volume as its `qty` times the SKU's `each_volume_cm3`. It then filters to eligible destinations: a location qualifies when its `status` is `AVAILABLE`, its `zone` is `RESERVE` or `PICK_FACE`, its residual capacity (`max_volume_cm3` minus `used_volume_cm3`) is at least the required volume, and — if the location is a `PICK_FACE` — it is dedicated to this very SKU via `pick_face_for_sku_id`. Among eligible locations it applies ABC-class slotting: an `A`-class (high-velocity) SKU prefers a `PICK_FACE` location for forward velocity, while a `B`- or `C`-class SKU prefers a `RESERVE` location for deep storage. Concretely, a location is preferred when its zone matches the class preference — `PICK_FACE` for `A`-class, `RESERVE` otherwise — and a non-matching zone is deprioritized. Within the same preference tier the selector chooses the **tightest fit**: the smallest residual capacity first, residual measured to two decimal places. Remaining ties are broken by oldest `created_at` first. The resource `id` is never used as a ranking key.

Completing the task advances it from `ASSIGNED` to `COMPLETED`. Completion requires that the task is `ASSIGNED`, that the target location's `status` is `AVAILABLE`, and that the target's residual capacity is still at least the plate's volume. A target that has become `BLOCKED` since assignment, or whose residual capacity is no longer sufficient, blocks completion: a blocked target raises `ERR_CROSS_ENTITY_STATE`, and an over-capacity move raises `ERR_LOCATION_CAPACITY`. On completion the plate is driven from `PUTAWAY_PENDING` to `STORED` — its `location_id` is set to the target, the target's `used_volume_cm3` is recomputed, and the SKU's `on_hand_qty` is recomputed — and the plate's `version` is incremented. If this completion makes every putaway task of the source ASN terminal (all `COMPLETED` or `CANCELLED`, at least one `COMPLETED`), the ASN bubbles from `PUT_AWAY` to `CLOSED`. The task's `version` is incremented.

A putaway task may instead be cancelled. Cancellation is allowed from either `CREATED` or `ASSIGNED`, moving the task to `CANCELLED`; when cancelling from `ASSIGNED`, the task's `target_location_id` is cleared. Either cancel increments the task's `version`.

### 3.5. License-Plate Lifecycle

A license plate is the unit of inventory tracking, identified by a unique, non-empty `lpn_code`, carrying a single homogeneous SKU named by `sku_id`, holding `qty` eaches (never negative), resting at `location_id`, and originating from `source_asn_id` (null for plates minted by a replenishment split rather than a receipt). Its `disposition` is system-managed and is one of `PUTAWAY_PENDING`, `STORED`, `ALLOCATED`, `PICKED_STAGED`, `SHIPPED`, or `DEPLETED`, beginning at `PUTAWAY_PENDING` at mint time with `location_id` null.

The lifecycle threads through every other workflow. A receipt mints the plate `PUTAWAY_PENDING`; a putaway completion or a cross-dock move drives it to `STORED` (requiring it to be `PUTAWAY_PENDING` and the target location `AVAILABLE`). Once stored, a plate flips between `STORED` and `ALLOCATED` as reservations come and go: a plate transitions `STORED` to `ALLOCATED` only when an allocation is created against it *and* the sum of its `RESERVED` and `COMMITTED` allocation quantities equals the plate's full `qty` — a plate that is only partially reserved stays `STORED`. Conversely, when a `RESERVED` allocation against an `ALLOCATED` plate is released and the remaining `RESERVED` plus `COMMITTED` quantity falls below the plate's `qty`, the plate reverts from `ALLOCATED` to `STORED`. This `STORED`/`ALLOCATED` cycle churns back and forth with reservation activity, and every flip increments the plate's `version`.

A confirmed pick drives an `ALLOCATED` plate to `PICKED_STAGED` (the plate must be `ALLOCATED` and the pick's allocation eligible to commit on this plate). Shipping the order then drives a `PICKED_STAGED` plate to `SHIPPED`, setting the plate's `qty` to zero and recomputing the SKU's `on_hand_qty`. Separately, a replenishment completion that drains a `STORED` reserve plate to zero eaches drives it from `STORED` to `DEPLETED`, clearing its `location_id` to null and recomputing the prior location's `used_volume_cm3`. Each of these transitions increments the plate's `version`. The plate's terminal states are `SHIPPED` and `DEPLETED`.

### 3.6. Outbound Orders and Manual Allocation

A `WavePlanner` opens a customer order, supplying a unique, non-empty `order_number` and an optional `priority` integer that defaults to 5 and must be at least 1, where a lower integer means higher priority. A new order begins in status `OPEN`, with `wave_id` null until it joins a wave. A duplicate `order_number` is rejected with `ERR_DUPLICATE_CODE`. The planner adds order lines while the order is `OPEN`; each line names the ordered `sku_id` and an `ordered_qty` greater than zero, belongs to its order via `order_id`, and begins with `allocated_qty` and `picked_qty` both zero. A line's `allocated_qty` is the sum of `allocated_qty` across that line's allocations that are `RESERVED` or `COMMITTED`; its `picked_qty` is the sum across that line's `COMMITTED` allocations only. An order that is still `OPEN`, not yet waved, may be cancelled, moving it from `OPEN` to `CANCELLED`.

Reservations may be created manually as well as through wave release. A manual reservation creates an `InventoryAllocation` naming the `order_line_id` on the demand side and the `lpn_id` on the supply side, with an `allocated_qty` greater than zero, and the OCC field `expected_lpn_version` carrying the plate's last-observed `version`. The allocation begins in status `RESERVED`. A reservation may not draw more than the plate's free quantity — the plate's `qty` minus the eaches already `RESERVED` or `COMMITTED` against that plate — and may not exceed the SKU's `available_qty`; a request that would breach either ceiling is rejected with `ERR_INSUFFICIENT_AVAILABLE`. The OCC guard described in Section 2.8 rejects the create with `ERR_STALE_LPN_VERSION` if `expected_lpn_version` no longer matches the plate's current `version`. On a successful create the line's `allocated_qty` and the SKU's `available_qty` are recomputed, and if the reservation now fully reserves the plate it is driven from `STORED` to `ALLOCATED`; the plate's `version` is incremented exactly once on every successful manual allocation create — whether or not the reservation fully reserved the plate (a partial reservation that leaves the plate `STORED` still bumps the version once, just as the `STORED` to `ALLOCATED` flip does).

Releasing a reservation moves it from `RESERVED` to `RELEASED`. The release recomputes the line's `allocated_qty` and the SKU's `available_qty`, and if the plate is no longer fully reserved it reverts from `ALLOCATED` to `STORED`; the allocation's `version` is incremented. An allocation's terminal states are `RELEASED` and `COMMITTED`.

### 3.7. Waves: The Two Parallel Status Axes

A wave carries two independent status axes that advance separately. The `release_status` axis tracks the planning lifecycle through `PLANNING`, `RELEASED`, and `CLOSED`; the `fulfillment_status` axis tracks physical progress through `UNALLOCATED`, `ALLOCATED`, `PICKING`, and `PICKED`. A `WavePlanner` creates a wave with a unique, non-empty `wave_label`; it starts with `release_status` of `PLANNING` and `fulfillment_status` of `UNALLOCATED`.

While a wave is in `PLANNING`, the planner adds open orders to it. Adding an order requires the order to be `OPEN` and the wave to be in `PLANNING`; the order is driven from `OPEN` to `WAVED` and its `wave_id` is set to the wave. Releasing the wave is the central allocation event and is OCC-guarded: the request carries `expected_wave_version`, the wave must be in `PLANNING`, and the wave must already hold at least one order — a release of an order-less wave is rejected with `ERR_CROSS_ENTITY_STATE`. If `expected_wave_version` does not match the wave's current `version`, the release is rejected with `ERR_STALE_WAVE_VERSION`. A successful release advances `release_status` from `PLANNING` to `RELEASED`, runs the allocation waterfall (Section 3.8) to create `RESERVED` allocations, sets `fulfillment_status` from `UNALLOCATED` to `ALLOCATED`, drives every newly fully-reserved plate from `STORED` to `ALLOCATED`, recomputes `available_qty` for the affected SKUs, and increments the wave's `version`.

Picking is started on the fulfillment axis, independently of the release axis. Starting picking requires `fulfillment_status` to be `ALLOCATED` and `release_status` to be `RELEASED`; it advances `fulfillment_status` from `ALLOCATED` to `PICKING`, spawns one `PickTask` (in status `PENDING`) per allocation of the wave, drives each `WAVED` order of the wave to `PICKING`, and increments the wave's `version`; `release_status` stays `RELEASED`. When every pick task of the wave is terminal — none `PENDING` or `IN_PROGRESS`, and at least one `PICKED` — the system bubbles `fulfillment_status` from `PICKING` to `PICKED` and, in the same step, bubbles `release_status` from `RELEASED` to `CLOSED`. The wave's terminal state is `CLOSED`. Both the fulfillment-axis completion and the release-axis close increment the wave's `version`.

### 3.8. Wave Allocation Waterfall

Wave release allocates inventory in a fully deterministic order so the outcome never depends on insertion accidents. Demand is processed order by order, the orders of the wave sorted by `priority` ascending and then by `created_at` ascending; within each order the lines are processed in `created_at` ascending order. For each line, the system computes the remaining demand as the line's `ordered_qty` minus its current `allocated_qty`. Supply is drawn from the `STORED` license plates of the line's SKU that still have free quantity, sorted oldest-received first by `created_at` ascending (a FEFO-by-receipt proxy); the resource `id` is never used as an ordering key. Walking that supply list, for each plate the system computes the free quantity (the plate's `qty` minus what is already reserved on it) and takes the smaller of that free quantity and the remaining demand; when the take is positive it creates a `RESERVED` `InventoryAllocation` for that line against that plate with `allocated_qty` equal to the take, and reduces the remaining demand by the take. It stops walking a line's supply once the remaining demand reaches zero. If a line's demand cannot be fully covered, the leftover is simply left under-allocated — this is not an error; the unfilled portion surfaces later as a short pick.

### 3.9. Picking: Pick-to-Light, Short Picks, and Shipment

Pick tasks are spawned by starting picking on a wave; each names its parent `wave_id`, the `allocation_id` of the reservation it fulfills, and a pick-to-light flag `light_confirmed` that begins false. A `Picker` starts a task, advancing it from `PENDING` to `IN_PROGRESS`; starting requires the task to be `PENDING` and the parent wave's `fulfillment_status` to be `PICKING` — a start while the wave is not yet `PICKING` is rejected with `ERR_CROSS_ENTITY_STATE`.

Confirming a pick is the pick-to-light protocol's heart and advances the task from `IN_PROGRESS` to `PICKED`. The confirm request carries `light_confirmed`, which must be true — a confirm submitted with `light_confirmed` not true (the operator did not press the bin light) is rejected with `ERR_VALIDATION_LIGHT_REQUIRED`. Confirmation requires the task to be `IN_PROGRESS` and its referenced allocation to be `RESERVED`. On a successful confirm the system sets the task's `light_confirmed` to true; drives the allocation from `RESERVED` to `COMMITTED` and recomputes the order line's `picked_qty`; drives the picked plate from `ALLOCATED` to `PICKED_STAGED`; and increments the task's `version`. If every line of the order is now fully picked — each line's `picked_qty` equal to its `ordered_qty` — the order bubbles from `PICKING` to `PICKED`. If no pick task of the wave remains `PENDING` or `IN_PROGRESS`, the wave's `fulfillment_status` bubbles from `PICKING` to `PICKED` (and, as noted, the `release_status` closes).

A pick that cannot be filled is recorded as a short pick, advancing the task from `IN_PROGRESS` to `SHORT`. A short pick is the compensation path: rather than committing, it drives the task's allocation from `RESERVED` to `RELEASED`, recomputes the order line's `allocated_qty` and the SKU's `available_qty`, and — if the plate is no longer fully reserved — reverts the plate from `ALLOCATED` to `STORED`; the task's `version` is incremented. A `WavePlanner` may also cancel a still-`PENDING` pick task, moving it from `PENDING` to `CANCELLED` and releasing its reservation from `RESERVED` to `RELEASED`. A pick task's terminal states are `PICKED`, `SHORT`, and `CANCELLED`.

An order becomes shippable once it is `PICKED`. A `Picker` ships a `PICKED` order, advancing it from `PICKED` to `SHIPPED`. Shipment drives each `PICKED_STAGED` plate behind the order's `COMMITTED` allocations to `SHIPPED`, setting each plate's `qty` to zero and recomputing the SKU's `on_hand_qty`; the order's `COMMITTED` allocations remain `COMMITTED` (their terminal state); and the order's `version` is incremented. The order's terminal states are `SHIPPED` and `CANCELLED`.

### 3.10. ABC Cycle Counting

Continuous inventory accuracy is maintained by cycle counts cadenced by ABC velocity class. An `InventoryController` opens a count for a SKU at a location, naming the `location_id` and `sku_id`. Opening snapshots `system_qty` once, at open time, as the sum of `qty` across the license plates at that location for that SKU whose disposition is `STORED` or `ALLOCATED`; this snapshot is captured a single time and is not re-snapshotted on submit. The count begins in status `OPEN` with `counted_qty` unset and `variance_qty` zero.

The controller submits the physical count, advancing it from `OPEN` to `COUNTED`. Submission requires `counted_qty` (at least zero) in the request; it records `counted_qty`, pins the submitting controller's `X-User-ID` as `counted_by_user_id`, computes `variance_qty` as `counted_qty` minus the snapshot `system_qty` (a signed value that may be negative), and increments the count's `version`.

A counted count is then either approved or rejected, both subject to the segregation-of-duties rule. Approval advances the count from `COUNTED` to `RECONCILED` and requires that the approver's `X-User-ID` is not the `counted_by_user_id`, and additionally is not the `received_by_user_id` of any ASN that fed an LPN at the counted location; a violation of either is rejected with `ERR_SEGREGATION_OF_DUTIES`. On approval, if `variance_qty` is non-zero, the `STORED` license-plate quantity at this location for this SKU is adjusted by the variance, filling plates in `created_at` ascending order, and the SKU's `on_hand_qty` and the location's `used_volume_cm3` are recomputed; the SKU's `cycle_count_due` is set to false (re-derived as below); and the count's `version` is incremented. Rejection advances the count from `COUNTED` to `REJECTED`, requires only that the rejecter's `X-User-ID` is not the `counted_by_user_id`, makes no inventory adjustment (on-hand is unchanged), and increments the count's `version`. A count's terminal states are `RECONCILED` and `REJECTED`.

The `cycle_count_due` flag is derived from the elapsed time since a SKU was last reconciled, against an ABC-keyed cadence. The system measures the whole days (floored) between the current clock and the `updated_at` of the most recent `RECONCILED` count for that SKU. The cadence is 30 days for an `A`-class SKU, 60 days for a `B`-class SKU, and 90 days for a `C`-class SKU. The SKU is due when the elapsed whole days are at least the cadence — exactly the cadence number of days makes the SKU due (the boundary is inclusive). If no reconciled count has ever existed for the SKU, it is due. The current clock used for this comparison is driven by the test-driving clock capability described in Section 3.12.

### 3.11. Min/Max Replenishment

Forward pick faces are refilled from deep reserve by replenishment tasks. An `InventoryController` creates a task naming the `sku_id` to refill. Creation pins `pick_face_location_id` to the SKU's dedicated `PICK_FACE` location (the location whose `pick_face_for_sku_id` equals this SKU) and computes `replen_qty`. The task may be created only when the pick face is at or below the SKU's replenishment floor: the pick-face on-hand — the sum of `qty` across the plates at the pick-face location for this SKU whose disposition is `STORED` or `ALLOCATED` — must be at most the SKU's `min_qty` (the boundary is inclusive of exactly `min_qty`). If the pick-face on-hand is above `min_qty`, the create is rejected with `ERR_REPLEN_NOT_NEEDED`. When eligible, `replen_qty` is computed as the SKU's `max_qty` minus the current pick-face on-hand — that is, the quantity needed to refill the face up to `max_qty` exactly. The task begins in status `CREATED` with `source_lpn_id` null.

Assigning the task selects a reserve source plate via the source selector and advances it from `CREATED` to `ASSIGNED`. The source selector considers the `STORED` plates of the task's SKU that rest in a `RESERVE`-zone location and still hold a positive `qty`, sorted oldest-received first by `created_at` ascending (a FEFO proxy; the resource `id` is never used). It accumulates plates from oldest to newest until the running sum of selected plate quantities is at least `replen_qty`. If the whole pool's combined quantity is below `replen_qty` (or the pool is empty), the assign is rejected with `ERR_NO_REPLEN_SOURCE`; otherwise the chosen source plate is written to `source_lpn_id`. (For symmetry: a putaway assign with no eligible location is rejected with `ERR_NO_PUTAWAY_LOCATION`, whereas a replenishment assign with no covering source uses `ERR_NO_REPLEN_SOURCE`.)

Completing the task is performed by a `PutawayOperator` and advances it from `ASSIGNED` to `COMPLETED`. Completion requires that the source plate's `qty` is at least `replen_qty`, and the destination move is capacity-checked against the pick face: a move that would push the pick face's `used_volume_cm3` above its `max_volume_cm3` is rejected with `ERR_LOCATION_CAPACITY`. On completion the source plate's `qty` is decremented by `replen_qty` — and if it reaches zero the source plate is driven from `STORED` to `DEPLETED` — while `replen_qty` eaches are added to the pick face by minting or merging into a `PICK_FACE` plate at `pick_face_location_id` (disposition `STORED`); the SKU's `on_hand_qty` is recomputed (the move is net-zero across the warehouse) and both locations' `used_volume_cm3` are recomputed; the task's `version` is incremented. A replenishment task may be cancelled from either `CREATED` or `ASSIGNED`, moving it to `CANCELLED`; when cancelling from `ASSIGNED`, the task's `source_lpn_id` is cleared. The task's terminal states are `COMPLETED` and `CANCELLED`.

### 3.12. Test-Driving the Clock

Because the cycle-count cadence depends on elapsed calendar time, the system exposes an admin-only test-driving capability that sets the server's current UTC clock to a supplied `to_iso8601` instant. Only a `PlatformAdmin` may invoke it. Setting the clock changes the reference instant the cycle-count due-flag derivation uses to measure elapsed days since a SKU's last reconciliation, allowing the cadence boundaries to be exercised deterministically.

## 4. Endpoint Definitions

All endpoints are mounted under the `/warehouse` prefix. A request that creates a new resource returns HTTP 201; a request that modifies, transitions, or reads an existing resource returns HTTP 200. The request and response payloads for each endpoint are described narratively in Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/warehouse/skus` | Create a SKU | PlatformAdmin |
| GET | `/warehouse/skus/{id}` | Fetch a SKU with computed quantities | PlatformAdmin, ReceivingClerk, PutawayOperator, Picker, WavePlanner, InventoryController |
| GET | `/warehouse/skus` | List SKUs | PlatformAdmin, ReceivingClerk, PutawayOperator, Picker, WavePlanner, InventoryController |
| POST | `/warehouse/locations` | Create a storage location | PlatformAdmin, InventoryController |
| GET | `/warehouse/locations/{id}` | Fetch a location with computed used volume | PlatformAdmin, ReceivingClerk, PutawayOperator, Picker, WavePlanner, InventoryController |
| GET | `/warehouse/locations` | List locations | PlatformAdmin, ReceivingClerk, PutawayOperator, Picker, WavePlanner, InventoryController |
| POST | `/warehouse/locations/{id}/block` | Block a location | InventoryController |
| POST | `/warehouse/locations/{id}/unblock` | Unblock a location | InventoryController |
| POST | `/warehouse/inbound-asns` | Announce an inbound ASN | ReceivingClerk |
| GET | `/warehouse/inbound-asns/{id}` | Fetch an ASN | PlatformAdmin, ReceivingClerk, PutawayOperator, WavePlanner, InventoryController |
| GET | `/warehouse/inbound-asns` | List ASNs | PlatformAdmin, ReceivingClerk, PutawayOperator, WavePlanner, InventoryController |
| POST | `/warehouse/inbound-asns/{id}/lines` | Add an expected line to an ASN | ReceivingClerk |
| GET | `/warehouse/inbound-asns/{id}/lines` | List the lines of an ASN | PlatformAdmin, ReceivingClerk, PutawayOperator, InventoryController |
| GET | `/warehouse/asn-lines/{id}` | Fetch a single ASN line | PlatformAdmin, ReceivingClerk, PutawayOperator, InventoryController |
| GET | `/warehouse/asn-lines` | List ASN lines | PlatformAdmin, ReceivingClerk, PutawayOperator, InventoryController |
| POST | `/warehouse/inbound-asns/{id}/receipts` | Post a receipt; mints an LPN | ReceivingClerk |
| GET | `/warehouse/inbound-asns/{id}/receipts` | List receipt events of an ASN | PlatformAdmin, ReceivingClerk, PutawayOperator, InventoryController |
| GET | `/warehouse/receipt-events/{id}` | Fetch a single receipt event | PlatformAdmin, ReceivingClerk, PutawayOperator, InventoryController |
| GET | `/warehouse/receipt-events` | List receipt events | PlatformAdmin, ReceivingClerk, PutawayOperator, InventoryController |
| POST | `/warehouse/inbound-asns/{id}/close` | Close receiving (putaway or cross-dock fork) | ReceivingClerk |
| POST | `/warehouse/inbound-asns/{id}/close-crossdock` | Finalize a cross-docked ASN | ReceivingClerk |
| POST | `/warehouse/inbound-asns/{id}/cancel` | Cancel an announced ASN | ReceivingClerk |
| GET | `/warehouse/license-plates/{id}` | Fetch a license plate | PlatformAdmin, ReceivingClerk, PutawayOperator, Picker, WavePlanner, InventoryController |
| GET | `/warehouse/license-plates` | List license plates | PlatformAdmin, ReceivingClerk, PutawayOperator, Picker, WavePlanner, InventoryController |
| GET | `/warehouse/putaway-tasks/{id}` | Fetch a putaway task | PlatformAdmin, PutawayOperator, InventoryController |
| GET | `/warehouse/putaway-tasks` | List putaway tasks | PlatformAdmin, PutawayOperator, InventoryController |
| POST | `/warehouse/putaway-tasks/{id}/assign` | Assign a destination via the putaway selector | PutawayOperator |
| POST | `/warehouse/putaway-tasks/{id}/complete` | Complete putaway; store the LPN | PutawayOperator |
| POST | `/warehouse/putaway-tasks/{id}/cancel` | Cancel a putaway task | PutawayOperator |
| POST | `/warehouse/outbound-orders` | Create an outbound order | WavePlanner |
| GET | `/warehouse/outbound-orders/{id}` | Fetch an outbound order | PlatformAdmin, WavePlanner, Picker, InventoryController |
| GET | `/warehouse/outbound-orders` | List outbound orders | PlatformAdmin, WavePlanner, Picker, InventoryController |
| POST | `/warehouse/outbound-orders/{id}/lines` | Add a line to an open order | WavePlanner |
| GET | `/warehouse/outbound-orders/{id}/lines` | List the lines of an order | PlatformAdmin, WavePlanner, Picker, InventoryController |
| GET | `/warehouse/order-lines/{id}` | Fetch a single order line | PlatformAdmin, WavePlanner, Picker, InventoryController |
| GET | `/warehouse/order-lines` | List order lines | PlatformAdmin, WavePlanner, Picker, InventoryController |
| POST | `/warehouse/outbound-orders/{id}/ship` | Ship a picked order | Picker |
| POST | `/warehouse/outbound-orders/{id}/cancel` | Cancel an open order | WavePlanner |
| POST | `/warehouse/allocations` | Create a manual reservation (OCC on LPN version) | WavePlanner |
| GET | `/warehouse/allocations/{id}` | Fetch an allocation | PlatformAdmin, WavePlanner, Picker, InventoryController |
| GET | `/warehouse/allocations` | List allocations | PlatformAdmin, WavePlanner, Picker, InventoryController |
| POST | `/warehouse/allocations/{id}/cancel` | Release a reserved allocation | WavePlanner |
| POST | `/warehouse/waves` | Create a wave | WavePlanner |
| GET | `/warehouse/waves/{id}` | Fetch a wave (both status axes) | PlatformAdmin, WavePlanner, Picker, InventoryController |
| GET | `/warehouse/waves` | List waves | PlatformAdmin, WavePlanner, Picker, InventoryController |
| POST | `/warehouse/waves/{id}/add-order` | Add an open order to a planning wave | WavePlanner |
| POST | `/warehouse/waves/{id}/release` | Release the wave; run allocation (OCC on wave version) | WavePlanner |
| POST | `/warehouse/waves/{id}/start-picking` | Start picking; spawn pick tasks | WavePlanner |
| GET | `/warehouse/waves/{id}/pick-tasks` | List the pick tasks of a wave | PlatformAdmin, WavePlanner, Picker, InventoryController |
| GET | `/warehouse/pick-tasks/{id}` | Fetch a pick task | PlatformAdmin, WavePlanner, Picker, InventoryController |
| GET | `/warehouse/pick-tasks` | List pick tasks | PlatformAdmin, WavePlanner, Picker, InventoryController |
| POST | `/warehouse/pick-tasks/{id}/start` | Begin a pick | Picker |
| POST | `/warehouse/pick-tasks/{id}/confirm` | Pick-to-light confirm | Picker |
| POST | `/warehouse/pick-tasks/{id}/short` | Short-pick | Picker |
| POST | `/warehouse/pick-tasks/{id}/cancel` | Cancel a pending pick task | WavePlanner |
| POST | `/warehouse/cycle-counts` | Open a cycle count; snapshot system quantity | InventoryController |
| GET | `/warehouse/cycle-counts/{id}` | Fetch a cycle count | PlatformAdmin, InventoryController, ReceivingClerk |
| GET | `/warehouse/cycle-counts` | List cycle counts | PlatformAdmin, InventoryController, ReceivingClerk |
| POST | `/warehouse/cycle-counts/{id}/submit` | Submit the physical count | InventoryController |
| POST | `/warehouse/cycle-counts/{id}/approve` | Approve & reconcile a count | InventoryController |
| POST | `/warehouse/cycle-counts/{id}/reject` | Reject a count | InventoryController |
| POST | `/warehouse/replenishment-tasks` | Create a min/max replenishment task | InventoryController |
| GET | `/warehouse/replenishment-tasks/{id}` | Fetch a replenishment task | PlatformAdmin, InventoryController, PutawayOperator |
| GET | `/warehouse/replenishment-tasks` | List replenishment tasks | PlatformAdmin, InventoryController, PutawayOperator |
| POST | `/warehouse/replenishment-tasks/{id}/assign` | Assign a reserve source via the source selector | InventoryController |
| POST | `/warehouse/replenishment-tasks/{id}/complete` | Complete replenishment; move to pick face | PutawayOperator |
| POST | `/warehouse/replenishment-tasks/{id}/cancel` | Cancel a replenishment task | InventoryController |
| POST | `/warehouse/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_WAVE_VERSION | 412 |
| ERR_STALE_LPN_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CROSS_ENTITY_STATE | 409 |
| ERR_DUPLICATE_CODE | 409 |
| ERR_LOCATION_CAPACITY | 409 |
| ERR_PICKFACE_TAKEN | 409 |
| ERR_REPLEN_NOT_NEEDED | 409 |
| ERR_INSUFFICIENT_AVAILABLE | 409 |
| ERR_ASN_LINES_OPEN | 409 |
| ERR_NO_PUTAWAY_LOCATION | 409 |
| ERR_NO_REPLEN_SOURCE | 409 |
| ERR_VALIDATION_LIGHT_REQUIRED | 409 |

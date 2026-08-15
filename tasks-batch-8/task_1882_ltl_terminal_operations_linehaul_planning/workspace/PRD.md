# LTL Terminal Operations API — Product Requirements Document

## 1. Introduction

This document specifies the API for a less-than-truckload (LTL) terminal operations and linehaul planning platform, modeled on the operational reality of a large regional carrier's cross-dock network. Freight does not move in straight lines in this world. A shipment is tendered at an origin terminal, collected by a pickup-and-delivery route, stripped across a dock, sorted by destination, built into an outbound trailer under hard cube and weight ceilings, and then moved through a chain of linehaul legs — sometimes relayed through meet points — until it arrives at its destination terminal. At every step the business wants a single source of truth for where the freight is, what it weighs for billing purposes, and whether the service promise is being kept.

Three pressures shape this system. First, trailer capacity is a finite, contested resource: cube and weight are separate constraints, either one can bind, and the dock needs a ledger that never silently overcommits. Second, money follows measurement — a shipper's declared dimensions are accepted at tender, but a certified dimensioner scan and a re-class inspection can rewrite the billing basis, and every such correction must produce an auditable, signed adjustment rather than a quiet overwrite. Third, the operation is posture-driven: an outbound trailer that is still `LOADING` accepts manifests, but once it is `SEALED` the dock's hands are off it, and the dispatcher's linehaul plan takes over. Overage, shortage, and damage claims interpose their own discipline — freight under an open claim must not be loaded, and a shipment cannot be billed while a claim is unresolved.

The API serves five peer roles with deliberately disjoint write surfaces: a terminal administrator, a P&D and linehaul dispatcher, a dock supervisor, a rating clerk, and an OS&D claims clerk. What follows is the complete behavioral contract: global conventions, business workflows with every state transition and calculation rule, the endpoint table, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role the API does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is therefore evaluated before any other concern — the server never reaches path resolution, state checks, or business rules for an unauthenticated or unauthorized caller.

The platform defines exactly five roles, spelled exactly as follows:

- `TerminalAdmin` — terminal staff administrator. Registers and closes terminals, runs service-standard reports, and operates the logical clock used by the test harness.
- `Dispatcher` — pickup-and-delivery and linehaul dispatcher. Tenders and cancels shipments, plans pickup routes and stops, dispatches and recalls routes, drives stop arrival/completion/skipping, and plans, departs, arrives, and cancels linehaul legs.
- `DockSupervisor` — dock operations lead. Registers dock doors and drives the full door lifecycle, opens/closes/dispositions sortation batches, spots outbound trailers, builds and trims manifests, marks trailers ready, seals, reopens, and voids them.
- `RatingClerk` — freight rating and inspection clerk. Runs initial rating and billing on shipments, records dimensioner scans, opens re-class inspections, and confirms or rejects them.
- `OsdClerk` — overage/shortage/damage claims clerk. Opens OS&D cases and moves them through review, resolution, and denial.

All five roles hold an **opaque** identity. When `X-User-Role` is `TerminalAdmin`, `Dispatcher`, `DockSupervisor`, `RatingClerk`, or `OsdClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server does not compare it to any resource's `id`. The server may, however, record it where a workflow requires provenance: specifically, when a `RatingClerk` records a dimensioner scan, the acting operator's `X-User-ID` is persisted as `scanned_by` on the resulting scan record. No other resource compares `X-User-ID` to a foreign key.

Read-only list and retrieval endpoints accept any of the five roles unless §4 says otherwise; write endpoints are restricted to the roles named in the endpoint table, and the per-endpoint role restriction is enforced as the second validation after authentication (see §2.8 for the full priority ordering).

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

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100; a value outside that range is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter defaults to 0 and must be a non-negative integer. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object. All list endpoints sort by `created_at` ascending; no other sort keys are supported.

### 2.4. Common Resource Properties

Every resource in this API exposes an `id` field, a server-minted UUID with no type prefix. All resources also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set once at creation and never changed. Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of that resource, and `version`, an integer starting at 1 on creation and incremented by exactly 1 on every mutation. These four fields together are the "common fields".

Two resource types deliberately omit `updated_at` and `version` and carry only `id` and `created_at`: **DimensionerScan** (a measurement, once recorded, is an immutable evidentiary fact) and **ServiceStandardReport** (a report is a point-in-time snapshot). Both are append-only in spirit; neither is mutated by any endpoint.

### 2.5. Monetary Precision and Rounding Discipline

All money in this platform is carried as integer cents — no decimals, no floats. Where a calculation produces a fractional cent, the result is rounded half-up to whole cents before the next step of the calculation proceeds. This rounding order is pinned and non-negotiable for freight rating (§3.4): the line-haul charge is rounded half-up to whole cents first, the fuel surcharge is then computed on that rounded line-haul and itself rounded half-up, and accessorial charges — already whole cents — are added last without further rounding. Percentages (trailer utilization, on-time percentage) are expressed as a number rounded half-up to one decimal place. Time accrual for linehaul delay is expressed in whole minutes, truncated toward zero.

### 2.6. Optimistic Concurrency Control on the Trailer Ledger

A trailer's loaded-weight and loaded-cube ledger is mutated by multiple dock actors, and a client acting on a stale read of that ledger would allocate cube it never saw as committed. Two write operations therefore participate in optimistic concurrency control, and only these two:

- **Manifesting a shipment onto a trailer** requires the request body to carry `expected_trailer_version`, the value of the trailer's `version` the client last observed. If that value does not equal the trailer's current `version`, the request is rejected with `ERR_STALE_TRAILER_VERSION` (HTTP 412).
- **Sealing a trailer** likewise requires `expected_trailer_version` in the request body, matching the trailer's current `version`. A mismatch is rejected with `ERR_STALE_TRAILER_VERSION` (HTTP 412).

Every successful manifest add, manifest remove, seal, or reopen increments the trailer's `version` by exactly 1 and refreshes its `updated_at`. A client that last read a trailer at `version` 4, for example, must re-read the trailer after any intervening mutation before sealing; presenting 4 again after another writer advanced the trailer to 5 yields `ERR_STALE_TRAILER_VERSION`. No endpoint other than the two named above accepts a version field — requests that do not name `expected_trailer_version` in their contract simply do not carry one.

### 2.7. Trailer Capacity, Utilization, and the Binding Constraint

An outbound trailer is created with two hard ceilings supplied by the dock supervisor: `max_weight_lbs`, the legal payload cap in whole pounds, and `max_cube_cuft`, the interior cube capacity in cubic feet. Both must be integers of at least 1. The trailer's live load is tracked as `loaded_weight_lbs` and `loaded_cube_cuft`, each starting at 0 while the trailer is empty, and its `utilization_pct` reports the more constraining of the two fill ratios as a percentage: the larger of loaded weight divided by maximum weight and loaded cube divided by maximum cube, multiplied by 100, rounded half-up to one decimal place. A trailer 95% full by cube but only 40% full by weight therefore reports 95.0 — the binding constraint drives the number, and the number drives the readiness gate described in §3.5. The minimum utilization a trailer must reach before it may be marked ready for dispatch is 60.0 percent.

### 2.8. Validation Priority Ordering

When a request violates more than one rule, the server evaluates checks in a fixed priority order and returns the error from the earliest matching check — a caller never sees a low-priority business error masking an authentication failure or a not-found path. The order is:

1. Authentication — missing or invalid `X-User-Role` / `X-User-ID` → `ERR_UNAUTHENTICATED`.
2. Authorization — role not permitted on this endpoint → `ERR_FORBIDDEN`.
3. Path resolution — every id in the URL path is resolved left to right; the first unresolvable id yields `ERR_NOT_FOUND`.
4. Body reference resolution — every foreign-key field in the request body (for example `origin_terminal_id`, `destination_terminal_id`, `route_id`, `shipment_id`, `trailer_id`, `scan_id`) must resolve to an existing entity, else `ERR_REFERENCE_NOT_FOUND`.
5. Entity state preconditions for the requested transition (e.g. trailer must be `LOADING` to accept a manifest entry, a stop must be `ARRIVED` to complete, a leg must be `EN_ROUTE` to arrive) → `ERR_INVALID_STATE`.
6. Optimistic concurrency — `expected_trailer_version` must equal the trailer's current `version` on the two OCC-guarded writes → `ERR_STALE_TRAILER_VERSION`.
7. OS&D safety hold — the freight must not be under an active claim hold before loading → `ERR_SHIPMENT_ON_OSD_HOLD`.
8. Destination alignment between trailer and shipment → `ERR_DESTINATION_MISMATCH`.
9. (Reserved by the catalogue; no rule at this priority.)
10. Door-kind agreement between the door and its intended use → `ERR_DOOR_KIND_MISMATCH`.
11. Stop timing within the route's shift window → `ERR_STOP_OUTSIDE_SHIFT`.
12. Relay connect feasibility between consecutive legs → `ERR_RELAY_CONNECT_INFEASIBLE`.
13. Leg time window validity (arrival strictly after departure) → `ERR_LEG_WINDOW_INVALID`.
14. Trailer capacity ceilings on projected load → `ERR_TRAILER_OVER_CAPACITY`.
15. Billability of the shipment → `ERR_SHIPMENT_NOT_BILLABLE`.
16. Terminal-open guard → `ERR_TERMINAL_CLOSED`.
17. Route dispatched before stop arrival → `ERR_ROUTE_NOT_DISPATCHED`.
18. Relay sequencing on departure → `ERR_RELAY_SEQUENCE_VIOLATION`.
19. Trailer loadability gate for mark-ready → `ERR_TRAILER_NOT_LOADABLE`.
20. Field-level request validity — enum membership, integer ranges, required fields → `ERR_INVALID_REQUEST`.
21. Inspection evidence alignment → `ERR_SCAN_SHIPMENT_MISMATCH`.

Two consequences of this ordering are worth internalizing. First, a stale trailer version (priority 6) surfaces before the destination-mismatch check (priority 8) and the capacity check (priority 14): a client holding an obsolete `version` always hears about the staleness first, and re-reading the trailer is the correct response before re-attempting. Second, `ERR_INVALID_STATE` at priority 5 precedes the OCC check — if a trailer is not even in `LOADING`, the server says so rather than quibbling over the version. Field-level request validity (priority 20) sits late in the ordering deliberately: an enum violation on `nmfc_class` in an otherwise routable request is reported, but only after the request has cleared identity, existence, and state gates. The §5 catalogue lists error identifiers and HTTP statuses; trigger conditions live here and in §3, next to the workflows they guard.

### 2.9. Logical Clock and Terminal Timezones

The platform keeps a logical clock rather than reading wall time. At startup the clock reads 2026-08-01T00:00:00Z, and a `TerminalAdmin` may advance it to a supplied instant via a test-driving capability that accepts `to_iso8601` and reports back the new `current_utc`. Every timestamp the server stamps — tender instants, departures, arrivals, deliveries — is read from this logical clock. Terminals each carry a `timezone` (an IANA timezone name, defaulting to `America/Chicago` when not supplied at registration) that governs service-standard cutoff math: a shipment's committed delivery instant is computed from terminal-local calendar days at the destination terminal, and service-standard reports aggregate over terminal-local days translated into half-open UTC windows (§3.7).

### 2.10. Closed-Terminal Guard

Terminals are the network's anchor entities. A `TerminalAdmin` registers a terminal with a unique `code` (exactly three uppercase letters, A through Z — for example CHI), a human-readable `name`, the count of physical `dock_doors` at the facility (an integer of at least 1), and an optional `timezone`. Closing a terminal is a one-way `ACTIVE` → `CLOSED` transition available to a `TerminalAdmin`. Once a terminal is `CLOSED`, four kinds of new work against it are rejected with `ERR_TERMINAL_CLOSED` (HTTP 409): tendering a shipment whose origin is that terminal, spotting an outbound trailer at that terminal, opening a sortation batch at that terminal, and reserving a dock door belonging to that terminal. In-flight work already accepted is not torn down — closure gates new commitments, not the completion of old ones. Shipment rating additionally requires that both the origin and destination terminals currently be `ACTIVE` (§3.2).

## 3. Business Logic & Workflows

### 3.1. Tendering Freight: The Shipment Enters the Network

A `Dispatcher` tenders a shipment by supplying `origin_terminal_id` and `destination_terminal_id` (both must resolve to existing terminals, and the origin must not be `CLOSED`), the declared `nmfc_class`, the shipper-declared `actual_weight_lbs` in whole pounds, the declared carton dimensions `length_in`, `width_in`, and `height_in` in whole inches, the committed `service_standard`, and optionally a list of `accessorial_codes` requested at tender. The declared NMFC class must be one of `CLASS_50`, `CLASS_55`, `CLASS_60`, `CLASS_65`, `CLASS_70`, `CLASS_85`, `CLASS_100`, or `CLASS_125`; each accessorial code must be one of `LIFTGATE`, `NOTIFY`, `RESIDENTIAL`, or `INSIDE`; weight and every dimension must be at least 1. Violations of enum membership or these ranges are rejected with `ERR_INVALID_REQUEST`. The service standard is one of `STANDARD`, `EXPEDITED`, or `GUARANTEED`.

On acceptance the server mints a `pro_number` — the string `PRO-` followed by a zero-padded serial — and stamps `tendered_at_utc` from the logical clock. The new shipment is born with `rating_status` `UNRATED` and `handling_status` `TENDERED`; these are two parallel status axes that move independently (a shipment can be `RATED` while still `TENDERED`, or `IN_LINEHAUL` while still `RATED`). Its computed billing fields start conservative: `chargeable_weight_lbs` equals the declared `actual_weight_lbs`, `dim_weight_lbs` is 0 until a dimensioner measurement exists, `rated_amount_cents` is 0 until the first rating run, and `billed_amount_cents` stays 0 until the shipment is actually billed. `osd_hold` is `false`. The committed delivery instant, `committed_delivery_utc`, is computed at tender as `tendered_at_utc` plus a number of terminal-local calendar days at the destination terminal: three days for `STANDARD`, two for `EXPEDITED`, one for `GUARANTEED`. `delivered_at_utc` remains null until the shipment is delivered.

A dispatcher may cancel a shipment while it is `TENDERED` or `ON_DOCK`, provided no `ACTIVE` manifest entry references it; cancellation moves `handling_status` to `CANCELLED` and flips every still-`PLANNED` pickup stop referencing the shipment to `SKIPPED`. A shipment already manifested is past the point of cancellation.

### 3.2. Rating the Shipment: The GROSS Baseline

A `RatingClerk` runs the initial rating on a shipment whose `rating_status` is `UNRATED` and whose `handling_status` is either `TENDERED` or `ON_DOCK`; rating is impossible once the freight is manifested or further along, and impossible if either endpoint terminal has since gone `CLOSED` (both `origin_terminal_id` and `destination_terminal_id` must reference `ACTIVE` terminals at rating time). A state mismatch here is `ERR_INVALID_STATE`.

The initial run is the GROSS variant of the freight-rating calculation: the chargeable weight is simply the declared `actual_weight_lbs`, and the declared dimensions play no role in billing (they matter later, for cube accounting on trailers). The rate is a flat per-class tariff per hundredweight. The calculation proceeds in pinned order:

1. The **line-haul charge** is the chargeable weight divided by 100 and multiplied by the per-class rate in cents per hundredweight, rounded half-up to whole cents. The per-class rates are: `CLASS_50` 1800, `CLASS_55` 2000, `CLASS_60` 2150, `CLASS_65` 2350, `CLASS_70` 2500, `CLASS_85` 2900, `CLASS_100` 3400, `CLASS_125` 4100.
2. The **fuel surcharge** is 22 percent of the rounded line-haul charge, itself rounded half-up to whole cents.
3. **Accessorial charges** are the sum of flat per-code amounts for every code in `accessorial_codes`: `LIFTGATE` 7500, `NOTIFY` 3500, `RESIDENTIAL` 9000, `INSIDE` 12000 cents. These are whole-cent amounts and are added without rounding.

The rated amount is the sum of those three components, stored on the shipment as `rated_amount_cents`, and `rating_status` advances to `RATED`. On this initial run the server also records `chargeable_weight_lbs` equal to `actual_weight_lbs` and confirms `dim_weight_lbs` at 0. Note the rounding order is pinned: line-haul rounded first, fuel computed on the rounded line-haul, accessorials added last — never sum-then-round.

### 3.3. Pickup & Delivery: Routes, Stops, and Getting Freight On Dock

A `Dispatcher` plans a pickup-and-delivery route by naming its home `terminal_id`, the `route_date` (a terminal-local calendar date in `YYYY-MM-DD` form), an opaque `driver_id` from the driver roster, and the shift window as `shift_start_minute` and `shift_end_minute` — both minute-of-day integers, the start in the range 0 through 1439, the end in the range 1 through 1440, with the end strictly greater than the start. The route is created `PLANNED`.

Stops are added to a route by a dispatcher, each carrying `route_id`, the `shipment_id` to collect, a 1-based `stop_sequence` giving the visit order, and a `planned_arrival_minute`. That planned arrival must fall within the route's shift window, with both endpoints of the window included — a planned arrival exactly at `shift_start_minute` or exactly at `shift_end_minute` is acceptable; anything outside is rejected with `ERR_STOP_OUTSIDE_SHIFT` (HTTP 422). Each stop is created `PLANNED`.

Dispatching a route (PLANNED → DISPATCHED) requires at least one stop still `PLANNED` on it. Once dispatched, the driver's day unfolds as stop transitions: marking a stop arrived (`PLANNED` → `ARRIVED`) is only legal while the route is `DISPATCHED` — attempting it otherwise is rejected with `ERR_ROUTE_NOT_DISPATCHED` — and completing a stop (`ARRIVED` → `PICKED_UP`) is the moment the freight physically changes custody: the shipment's `handling_status` moves from `TENDERED` to `ON_DOCK`. A dispatcher may also skip a stop outright, moving it from `PLANNED` (or `ARRIVED`, when the skip comes from a route recall or shipment cancel cascade) to `SKIPPED`.

Routes complete themselves by exhaustion: the moment every stop on a dispatched route sits in `PICKED_UP` or `SKIPPED`, the route's `status` becomes `COMPLETED` without any explicit call. Alternatively, a dispatcher may recall a dispatched route — but only while no stop on it is `ARRIVED`. Recall moves the route to `RECALLED` and flips every remaining `PLANNED` stop to `SKIPPED`; those skips then feed the same completion check, though a recalled route stays `RECALLED` rather than completing.

### 3.4. Measurement and Re-Class: Dimensioner Scans and Inspections

Declared weight is a courtesy; measured weight is evidence. A `RatingClerk` records a dimensioner scan against a shipment, supplying `shipment_id`, the measured dimensions `measured_length_in`, `measured_width_in`, `measured_height_in` in whole inches, and the certified-scale `measured_weight_lbs` — each at least 1. The scan is append-only: it carries `id` and `created_at` but no `updated_at` or `version`, and the server stamps `scanned_by` with the clerk's `X-User-ID`. Scans accumulate on a shipment; ordering between them is by `created_at`.

A scan becomes consequential when a `RatingClerk` opens a re-class inspection, supplying `shipment_id`, the `scan_id` of the measurement evidence, and the inspector-asserted `claimed_nmfc_class` (drawn from the same eight-class enum as the shipment's declared class). Two gates apply. First, the shipment's `rating_status` must be `RATED` — or `RERATED` for a re-inspection cycle — else `ERR_INVALID_STATE`. Second, the scan named by `scan_id` must belong to this shipment; a scan recorded against a different shipment is rejected with `ERR_SCAN_SHIPMENT_MISMATCH` (HTTP 422). For a re-inspection on a `RERATED` shipment there is an additional freshness rule: the scan must be newer than the scan behind the previous inspection, ordered by `created_at`.

Opening the inspection moves the shipment's `rating_status` to `INSPECTION_PENDING` and immediately rebases its weight fields from the scan evidence: `dim_weight_lbs` becomes the measured length times width times height in inches, divided by the dimensional divisor 194 and rounded up to a whole pound; and `chargeable_weight_lbs` becomes the larger of the scan's `measured_weight_lbs` and that computed `dim_weight_lbs`. The inspection itself is born with `outcome` `PENDING` and `adjustment_cents` 0.

The inspection resolves in one of two directions. **Confirming** the re-class — legal only while `outcome` is `PENDING` — stamps `outcome` `CONFIRMED_RECLASS`, rewrites the shipment's `nmfc_class` to the `claimed_nmfc_class`, and re-runs freight rating under the DIM variant: the chargeable weight is the larger of `measured_weight_lbs` and the ceiling of the measured-dimension product over 194, the class rate is the (new) class's tariff, and the line-haul → fuel → accessorial pipeline from §3.2 reruns with the same pinned rounding order. The shipment's `rated_amount_cents` is replaced by the DIM-variant result, `rating_status` advances to `RERATED`, and the inspection's `adjustment_cents` records the signed delta — the new rated amount minus the rated amount the shipment carried before the inspection opened (positive means an upcharge to the shipper). **Rejecting** the inspection — likewise only from `PENDING` — stamps `outcome` `REJECTED`, sets `adjustment_cents` to 0, restores the shipment's `chargeable_weight_lbs` to the declared `actual_weight_lbs`, resets `dim_weight_lbs` to 0, and returns `rating_status` to `RATED`. Both outcomes are terminal for the inspection. A `RERATED` shipment may cycle back to `INSPECTION_PENDING` through a fresh inspection with a newer scan, repeating the same rebasing side effects; there is no limit on the number of cycles.

### 3.5. The Outbound Dock: Doors, Sortation, Trailers, and the Manifest Ledger

Dock work begins with doors. A `DockSupervisor` registers each physical door with its `terminal_id`, a `door_number` (an integer of at least 1, unique within its terminal — the pair of terminal and door number may not repeat), and a `door_kind` of either `INBOUND` (strip doors, where P&D freight is unloaded) or `OUTBOUND` (load doors, where linehaul trailers are built). Doors are created `AVAILABLE` and cycle through a simple lifecycle: reserving an `AVAILABLE` door moves it to `RESERVED` (legal only while the owning terminal is `ACTIVE` — otherwise `ERR_TERMINAL_CLOSED`); occupying a `RESERVED` door moves it to `OCCUPIED`; releasing an `OCCUPIED` door returns it to `AVAILABLE` — but only when no sortation batch with that door as its `inbound_door_id` is `OPEN` or `CLOSED`, and no outbound trailer spotted at that door is in posture `LOADING`, `READY`, or `SEALED`. A door in any of `AVAILABLE`, `RESERVED`, or `OCCUPIED` may be taken out of service (to `OUT_OF_SERVICE`) under the same no-active-user precondition as release, and an `OUT_OF_SERVICE` door may be returned to `AVAILABLE` unconditionally.

Sortation is the destination-wise grouping of stripped freight. A dock supervisor opens a sortation batch naming the `terminal_id` running the sort, the `inbound_door_id` where the batch is stripped, and the single `destination_terminal_id` the batch sorts for. The door must be of `door_kind` `INBOUND` — pointing the batch at an outbound door is rejected with `ERR_DOOR_KIND_MISMATCH` (HTTP 422) — and the terminal must be `ACTIVE`. The batch moves `OPEN` → `CLOSED` → `DISPOSITIONED`; disposition is what frees the inbound door, since a door cannot be released while an `OPEN` or `CLOSED` batch still names it.

Outbound trailers are where capacity becomes a contested pool. Spotting a trailer requires `terminal_id`, `destination_terminal_id`, the `outbound_door_id` it is spotted at — which must be an `OUTBOUND` door, else `ERR_DOOR_KIND_MISMATCH` — and the two ceilings `max_weight_lbs` and `max_cube_cuft`. The trailer is created in posture `LOADING` with `loaded_weight_lbs` 0, `loaded_cube_cuft` 0, and `utilization_pct` 0.0.

**Manifesting** a shipment onto a trailer is the central write of the dock, and it is OCC-guarded: the request carries `shipment_id`, the `load_position` (a 1-based nose-to-tail slot index, where 1 is the nose and delivery sequence runs tail-first), and `expected_trailer_version` as described in §2.6. The full gate list, evaluated in the priority order of §2.8:

- The trailer's `posture` must be `LOADING` — manifesting into a `READY`, `SEALED`, or later trailer is `ERR_INVALID_STATE`.
- The shipment's `handling_status` must be `ON_DOCK` and its `rating_status` must be `RATED` or `RERATED` — freight that is unrated, mid-inspection, billed, or already moving cannot be loaded (state failures again surface as `ERR_INVALID_STATE`).
- The OCC check: `expected_trailer_version` must equal the trailer's current `version`, else `ERR_STALE_TRAILER_VERSION` (HTTP 412).
- The shipment must not be under an OS&D hold — `osd_hold` must be `false`, meaning no linked case is `OPEN` (see §3.8) — else `ERR_SHIPMENT_ON_OSD_HOLD` (HTTP 409).
- The trailer's `destination_terminal_id` must equal the shipment's `destination_terminal_id` — loading freight onto a trailer bound elsewhere is `ERR_DESTINATION_MISMATCH` (HTTP 422).
- The projected load must fit: the trailer's current `loaded_weight_lbs` plus the shipment's `chargeable_weight_lbs` must not exceed `max_weight_lbs`, and the current `loaded_cube_cuft` plus the shipment's cube must not exceed `max_cube_cuft`. A projection that is strictly greater on either axis is rejected with `ERR_TRAILER_OVER_CAPACITY` (HTTP 422); a projection landing exactly at either cap is allowed. The shipment's cube is its length times width times height in inches divided by 1728, rounded up to a whole cubic foot.
- A shipment may hold at most one `ACTIVE` manifest entry across the network; attempting to manifest a shipment that already has an `ACTIVE` entry is a state violation.

On success the entry is created with `status` `ACTIVE`, the shipment's `handling_status` advances from `ON_DOCK` to `MANIFESTED`, and the trailer's ledger absorbs the freight: `loaded_weight_lbs` increases by the shipment's `chargeable_weight_lbs`, `loaded_cube_cuft` increases by the shipment's ceiling-cube, `utilization_pct` is recomputed per §2.7, and the trailer's `version` increments by 1 with `updated_at` refreshed.

**Removing** a manifest entry is the mirror write, legal while the entry is `ACTIVE` and the trailer's posture is `LOADING` or `READY` (a `SEALED` trailer must first be reopened). Removal sets the entry's `status` to `REMOVED`, returns the shipment from `MANIFESTED` to `ON_DOCK`, subtracts the shipment's weight and cube from the trailer's loaded totals, recomputes utilization, and increments the trailer's `version`. Removal does not take an OCC field; the posture gate is the protection.

**Readiness** is a deliberate gate. Marking a trailer ready requires at least one `ACTIVE` manifest entry aboard and `utilization_pct` of at least 60.0 — a trailer running 59.9 percent utilized, however close, is rejected with `ERR_TRAILER_NOT_LOADABLE` (HTTP 422), as is an empty trailer. Success moves posture from `LOADING` to `READY`. **Sealing** moves `READY` → `SEALED` and is the second OCC-guarded write: the request carries `expected_trailer_version` and a mismatch is `ERR_STALE_TRAILER_VERSION`; sealing also increments the trailer's `version`. A `READY` or `SEALED` trailer may be reopened back to `LOADING` — for a `SEALED` trailer only if no linehaul leg referencing it is currently `EN_ROUTE` — which re-enables manifest add/remove and likewise bumps `version`. An empty trailer in `LOADING` or `READY` may be voided outright (`VOIDED` is terminal), which frees its outbound door for release.

### 3.6. Linehaul: Legs, Relays, and Provisional ETAs

Linehaul moves a sealed trailer between terminals, possibly through relay meet points. A `Dispatcher` plans a leg with `origin_terminal_id`, `destination_terminal_id`, the `trailer_id` being moved, `planned_departure_utc` and `planned_arrival_utc` (both ISO 8601 UTC instants), and `relay_sequence` — a 1-based index ordering the legs of a relay chain that share the same trailer. Two temporal validations apply at planning time. The planned arrival must be strictly after the planned departure; equality is not enough, and a violation is `ERR_LEG_WINDOW_INVALID` (HTTP 422). And for any leg with `relay_sequence` greater than 1, the planned departure must be no earlier than the previous leg's planned arrival plus a 45-minute connect buffer — the minimum connect time at a relay point. A tighter connection is rejected with `ERR_RELAY_CONNECT_INFEASIBLE` (HTTP 422); a departure exactly 45 minutes after the prior arrival is feasible. Legs are created `PLANNED`, and legs later `CANCELLED` are excluded from relay chain reasoning.

Departing a leg stamps `actual_departure_utc` from the logical clock and moves the leg `PLANNED` → `EN_ROUTE`. Two sequencing preconditions govern departure, both state-class errors: for the first leg of a chain, the trailer's `posture` must be `SEALED`; for a later leg, the previous leg for the same trailer (the one whose `relay_sequence` is one less) must already be `ARRIVED` — departing leg N while leg N−1 is anything other than `ARRIVED` is rejected with `ERR_RELAY_SEQUENCE_VIOLATION` (HTTP 409). Departing the first leg also drives the trailer `SEALED` → `DISPATCHED` and sweeps every shipment with an `ACTIVE` manifest entry aboard from `MANIFESTED` to `IN_LINEHAUL` in one cascade.

While a leg is en route, the platform maintains a forward-looking ETA. The accrued departure delay is the difference between the actual and planned departure instants, expressed in whole minutes and floored at zero — an early departure accrues no negative delay. The leg's `provisional_eta_utc` is its `planned_arrival_utc` plus those accrued delay minutes. For the next leg of the same relay chain (still `PLANNED`), the projection works as follows: if the current leg's provisional ETA leaves at least the 45-minute connect buffer before the next leg's planned departure, the next leg's projected arrival stays its own `planned_arrival_utc`; otherwise the next leg's projected arrival is pushed out by exactly the connect shortfall — that is, by the amount by which the current leg's provisional ETA plus 45 minutes exceeds the next leg's planned departure. Before any leg of the chain has departed, projections use planned times only, with no accrued delay.

Arriving a leg requires it to be `EN_ROUTE` and stamps `actual_arrival_utc` from the logical clock, moving the leg to `ARRIVED`. When the arriving leg's `destination_terminal_id` equals the trailer's `destination_terminal_id` — that is, it is the final leg of the relay chain — the arrival cascades: the trailer's posture moves `DISPATCHED` → `ARRIVED` (terminal), and every shipment with an `ACTIVE` manifest entry aboard moves `IN_LINEHAUL` → `DELIVERED`, each stamped with `delivered_at_utc` at the same instant. An intermediate relay leg's arrival merely completes that leg, leaving the trailer `DISPATCHED` and the shipments `IN_LINEHAUL` for the next leg. A still-`PLANNED` leg may be cancelled (`CANCELLED`, terminal) with no further effects; an en-route leg may not.

### 3.7. Billing, Service Standards, and the On-Time Report

Billing finalizes the money. A `RatingClerk` may bill a shipment whose `rating_status` is `RATED` or `RERATED` only when two conditions hold: its `handling_status` is `DELIVERED`, and no OS&D case linked to the shipment is `OPEN` or `UNDER_REVIEW`. Billing against either violation is rejected with `ERR_SHIPMENT_NOT_BILLABLE` (HTTP 409). On success, `billed_amount_cents` is frozen to the current `rated_amount_cents` and `rating_status` becomes `BILLED` — terminal for the rating axis.

Service performance is reported per terminal per terminal-local day. A `TerminalAdmin` generates a service-standard report by supplying `report_date` in `YYYY-MM-DD` form against a terminal; the server computes the reporting window as `window_start_utc` (the inclusive UTC instant of that terminal-local day's start) and `window_end_utc` (the exclusive UTC instant of the next terminal-local day's start, per the terminal's `timezone`) — a half-open window. The report counts `shipments_due`: shipments whose `destination_terminal_id` is this terminal, whose `committed_delivery_utc` falls inside the window, and whose `handling_status` is `IN_LINEHAUL` or `DELIVERED` — freight still `TENDERED`, `ON_DOCK`, or `MANIFESTED`, and cancelled freight, is excluded from both numerator and denominator. Of those, `shipments_on_time` counts the shipments that are `DELIVERED` with `delivered_at_utc` at or before `committed_delivery_utc` — arrival exactly at the commitment instant counts as on time. The `on_time_pct` is the on-time count divided by the due count, multiplied by 100, rounded half-up to one decimal place; when no shipments are due, the percentage is 0.0 by definition. `service_level_met` is true when the on-time percentage is at least 95.0 — the service target — and 95.0 exactly meets the standard. Reports are snapshots: they carry `id` and `created_at` only, with no `updated_at` or `version`.

### 3.8. Overage, Shortage & Damage: Claims, Holds, and Capped Liability

When freight is lost, short, or hurt, an `OsdClerk` opens a case against the shipment, supplying `shipment_id`, a `case_kind` of `OVERAGE`, `SHORTAGE`, or `DAMAGE`, a `claimed_amount_cents` (an integer of at least 0), and `item_amounts_cents` — a non-empty list of per-line claimed amounts, each an integer of at least 0. The case is created `OPEN`, and opening it sets the shipment's `osd_hold` to `true` immediately: freight under an open claim may not be manifested (§3.5), and the hold is the physical interlock for that rule. Reviewing the case moves it `OPEN` → `UNDER_REVIEW`; the hold remains in force.

Resolution computes the carrier's capped liability through a waterfall. Four ceilings are evaluated, and the award is the smallest of them:

1. The claimed total: `claimed_amount_cents`.
2. The gross line-item total: the sum of the per-line amounts in `item_amounts_cents`, each already whole cents.
3. The per-pound class cap: the shipment's current `actual_weight_lbs` multiplied by the per-pound liability for its current `nmfc_class`, rounded half-up to whole cents. The per-pound rates are: `CLASS_50` 150, `CLASS_55` 200, `CLASS_60` 250, `CLASS_65` 300, `CLASS_70` 350, `CLASS_85` 450, `CLASS_100` 600, `CLASS_125` 800 cents per pound.
4. The freight-multiple cap: the shipment's current `rated_amount_cents` multiplied by 10, rounded half-up to whole cents.

The `awarded_amount_cents` is the minimum of those four values; when ceilings tie, the same value results, so tie order is immaterial. Because the class cap uses the shipment's *current* class and the freight cap its *current* rated amount, a confirmed re-class (§3.4) changes the liability landscape for any case resolved afterward — the sequencing of inspection and claims work matters. Resolving moves the case to the terminal state `RESOLVED`. Denial, the alternative terminal outcome, moves the case from `UNDER_REVIEW` to `DENIED` and sets `awarded_amount_cents` to 0.

Both resolution and denial clear the hold when the shipment has no other case still `OPEN` or `UNDER_REVIEW` — the `osd_hold` flips back to `false` and the freight (if still on dock) becomes loadable again. One further fiscal coupling: if the shipment's `rating_status` is already `BILLED` when a case resolves, the award is offset against billed revenue — `billed_amount_cents` is reduced by the awarded amount. A denied case never touches the billed amount. A shipment with any case `OPEN` or `UNDER_REVIEW` cannot be billed in the first place (§3.7), so the billed-then-resolved path is the only way the offset arises.

## 4. Endpoint Definitions

All endpoints are mounted under the `/ltl` prefix. Status code conventions: endpoints that create a new resource return 201; endpoints that retrieve, list, or mutate an existing resource (including all state-transition actions) return 200. Request payloads, response payloads, and side effects are as specified in §3; the table below is a locator, not a full contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /ltl/_clock/set_current_utc | Set the server's logical clock (test-driving; default 2026-08-01T00:00:00Z) | TerminalAdmin |
| POST | /ltl/terminals | Register a terminal | TerminalAdmin |
| GET | /ltl/terminals | List terminals | TerminalAdmin, Dispatcher, DockSupervisor, RatingClerk, OsdClerk |
| GET | /ltl/terminals/{`terminalId`} | Get one terminal | TerminalAdmin, Dispatcher, DockSupervisor, RatingClerk, OsdClerk |
| POST | /ltl/terminals/{`terminalId`}/close | Close a terminal (blocks new tenders, trailer spottings, batches, reservations) | TerminalAdmin |
| POST | /ltl/shipments | Tender a shipment (created UNRATED / TENDERED) | Dispatcher |
| GET | /ltl/shipments | List shipments (filterable) | TerminalAdmin, Dispatcher, DockSupervisor, RatingClerk, OsdClerk |
| GET | /ltl/shipments/{`shipmentId`} | Get one shipment | TerminalAdmin, Dispatcher, DockSupervisor, RatingClerk, OsdClerk |
| POST | /ltl/shipments/{`shipmentId`}/rate | Run initial GROSS-variant rating | RatingClerk |
| POST | /ltl/shipments/{`shipmentId`}/bill | Finalize billing on a delivered shipment | RatingClerk |
| POST | /ltl/shipments/{`shipmentId`}/cancel | Cancel a tendered/on-dock shipment | Dispatcher |
| POST | /ltl/pickup-routes | Plan a P&D route | Dispatcher |
| GET | /ltl/pickup-routes | List pickup routes | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/pickup-routes/{`routeId`} | Get one pickup route | TerminalAdmin, Dispatcher, DockSupervisor |
| POST | /ltl/pickup-routes/{`routeId`}/dispatch | Dispatch a planned route | Dispatcher |
| POST | /ltl/pickup-routes/{`routeId`}/recall | Recall a dispatched route with no ARRIVED stops | Dispatcher |
| POST | /ltl/pickup-stops | Add a pickup stop to a route | Dispatcher |
| GET | /ltl/pickup-routes/{`routeId`}/stops | List stops of a route | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/pickup-stops | List pickup stops (filterable) | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/pickup-stops/{`stopId`} | Get one pickup stop | TerminalAdmin, Dispatcher, DockSupervisor |
| POST | /ltl/pickup-stops/{`stopId`}/arrive | Mark stop arrived | Dispatcher |
| POST | /ltl/pickup-stops/{`stopId`}/complete | Complete pickup (freight moves on dock) | Dispatcher |
| POST | /ltl/pickup-stops/{`stopId`}/skip | Skip a planned stop | Dispatcher |
| POST | /ltl/dock-doors | Register a dock door | DockSupervisor |
| GET | /ltl/dock-doors | List dock doors | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/dock-doors/{`doorId`} | Get one dock door | TerminalAdmin, Dispatcher, DockSupervisor |
| POST | /ltl/dock-doors/{`doorId`}/reserve | Reserve a door | DockSupervisor |
| POST | /ltl/dock-doors/{`doorId`}/occupy | Mark door occupied | DockSupervisor |
| POST | /ltl/dock-doors/{`doorId`}/release | Release door when no active batch/trailer uses it | DockSupervisor |
| POST | /ltl/dock-doors/{`doorId`}/take-out-of-service | Take door out of service | DockSupervisor |
| POST | /ltl/dock-doors/{`doorId`}/return-to-service | Return door to service | DockSupervisor |
| POST | /ltl/sortation-batches | Open a sortation batch at an inbound door for one destination | DockSupervisor |
| GET | /ltl/sortation-batches | List sortation batches | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/sortation-batches/{`batchId`} | Get one sortation batch | TerminalAdmin, Dispatcher, DockSupervisor |
| POST | /ltl/sortation-batches/{`batchId`}/close | Close a batch | DockSupervisor |
| POST | /ltl/sortation-batches/{`batchId`}/disposition | Disposition a closed batch (frees the inbound door) | DockSupervisor |
| POST | /ltl/trailers | Spot an outbound trailer at a door for a destination | DockSupervisor |
| GET | /ltl/trailers | List outbound trailers | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/trailers/{`trailerId`} | Get one trailer (with loaded ledger) | TerminalAdmin, Dispatcher, DockSupervisor |
| POST | /ltl/trailers/{`trailerId`}/manifest-entries | Manifest a shipment onto the trailer (OCC-guarded) | DockSupervisor |
| GET | /ltl/trailers/{`trailerId`}/manifest-entries | List manifest entries on a trailer | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/manifest-entries | List manifest entries (filterable) | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/manifest-entries/{`entryId`} | Get one manifest entry | TerminalAdmin, Dispatcher, DockSupervisor |
| POST | /ltl/manifest-entries/{`entryId`}/remove | Remove a manifest entry (trailer still LOADING/READY) | DockSupervisor |
| POST | /ltl/trailers/{`trailerId`}/mark-ready | Mark trailer ready (≥1 entry, utilization ≥ 60.0) | DockSupervisor |
| POST | /ltl/trailers/{`trailerId`}/seal | Seal trailer for dispatch (OCC-guarded) | DockSupervisor |
| POST | /ltl/trailers/{`trailerId`}/reopen | Reopen a READY/SEALED trailer back to LOADING | DockSupervisor |
| POST | /ltl/trailers/{`trailerId`}/void | Void an empty LOADING/READY trailer | DockSupervisor |
| POST | /ltl/linehaul-legs | Plan a linehaul leg (relay chains share a trailer; sequence orders legs) | Dispatcher |
| GET | /ltl/linehaul-legs | List linehaul legs | TerminalAdmin, Dispatcher, DockSupervisor |
| GET | /ltl/linehaul-legs/{`legId`} | Get one leg (with provisional ETA) | TerminalAdmin, Dispatcher, DockSupervisor |
| POST | /ltl/linehaul-legs/{`legId`}/depart | Depart a planned leg (stamps actual departure; computes provisional ETA) | Dispatcher |
| POST | /ltl/linehaul-legs/{`legId`}/arrive | Arrive an en-route leg | Dispatcher |
| POST | /ltl/linehaul-legs/{`legId`}/cancel | Cancel a planned leg | Dispatcher |
| POST | /ltl/dimensioner-scans | Record a dimensioner + certified-scale measurement (append-only) | RatingClerk |
| GET | /ltl/shipments/{`shipmentId`}/dimensioner-scans | List scans of a shipment | TerminalAdmin, RatingClerk, OsdClerk |
| GET | /ltl/dimensioner-scans | List dimensioner scans (filterable) | TerminalAdmin, RatingClerk, OsdClerk |
| GET | /ltl/dimensioner-scans/{`scanId`} | Get one dimensioner scan | TerminalAdmin, RatingClerk, OsdClerk |
| POST | /ltl/inspections | Open a re-class inspection on a RATED/RERATED shipment | RatingClerk |
| GET | /ltl/shipments/{`shipmentId`}/inspections | List inspections of a shipment | TerminalAdmin, RatingClerk, OsdClerk |
| GET | /ltl/inspections | List inspections (filterable) | TerminalAdmin, RatingClerk, OsdClerk |
| GET | /ltl/inspections/{`inspectionId`} | Get one inspection | TerminalAdmin, RatingClerk, OsdClerk |
| POST | /ltl/inspections/{`inspectionId`}/confirm | Confirm re-class: apply DIM-variant rating and adjustment | RatingClerk |
| POST | /ltl/inspections/{`inspectionId`}/reject | Reject re-class: restore pre-inspection rating basis | RatingClerk |
| POST | /ltl/osd-cases | Open an overage/shortage/damage case | OsdClerk |
| GET | /ltl/osd-cases | List OS&D cases | TerminalAdmin, RatingClerk, OsdClerk |
| GET | /ltl/osd-cases/{`caseId`} | Get one case | TerminalAdmin, RatingClerk, OsdClerk |
| POST | /ltl/osd-cases/{`caseId`}/review | Move case to UNDER_REVIEW | OsdClerk |
| POST | /ltl/osd-cases/{`caseId`}/resolve | Resolve case: compute capped liability award | OsdClerk |
| POST | /ltl/osd-cases/{`caseId`}/deny | Deny case | OsdClerk |
| POST | /ltl/terminals/{`terminalId`}/service-standard-reports | Generate the on-time report for a terminal-local date | TerminalAdmin |
| GET | /ltl/terminals/{`terminalId`}/service-standard-reports | List reports for a terminal | TerminalAdmin, Dispatcher |
| GET | /ltl/service-standard-reports | List service standard reports (filterable) | TerminalAdmin, Dispatcher |
| GET | /ltl/service-standard-reports/{`reportId`} | Get one service standard report | TerminalAdmin, Dispatcher |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2.8 and in the §3 workflow narratives alongside the operations they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_TRAILER_VERSION | 412 |
| ERR_SHIPMENT_ON_OSD_HOLD | 409 |
| ERR_DESTINATION_MISMATCH | 422 |
| ERR_DOOR_KIND_MISMATCH | 422 |
| ERR_STOP_OUTSIDE_SHIFT | 422 |
| ERR_RELAY_CONNECT_INFEASIBLE | 422 |
| ERR_LEG_WINDOW_INVALID | 422 |
| ERR_TRAILER_OVER_CAPACITY | 422 |
| ERR_SHIPMENT_NOT_BILLABLE | 409 |
| ERR_TRAILER_NOT_LOADABLE | 422 |
| ERR_SCAN_SHIPMENT_MISMATCH | 422 |
| ERR_TERMINAL_CLOSED | 409 |
| ERR_ROUTE_NOT_DISPATCHED | 409 |
| ERR_RELAY_SEQUENCE_VIOLATION | 409 |

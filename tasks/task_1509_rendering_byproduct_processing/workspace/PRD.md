# Rendering & Byproduct Processing API — Product Requirements Document

## 1. Introduction

A rendering plant earns its keep in the space between what slaughterhouses, farms, butcher shops, and grocery stores cannot sell and what oleochemical, feed, and pet-food manufacturers will pay for. Raw material arrives by the truckload — fallen stock from farms, offal from slaughter lines, trimmings from butcher counters — and leaves days later as graded tallow, yellow grease, or protein meal sold against customer contracts. Between those two moments the plant must prove, continuously and audibly, that species streams were never illegally mixed, that cookers were never over-committed, that every pound received was either consumed or accounted for, that odor complaints were investigated by someone other than the person who logged them, and that every dollar of pickup fees and product revenue landed in exactly one settlement period.

This document specifies the Rendering & Byproduct Processing API, the system of record for that operation. All resource collections are mounted flat under the `/rendering` prefix; cross-references between resources travel in request payloads rather than nested URL paths. A separate test-driving capability for the server's logical clock lives outside that prefix and is described in §2.5. The API is built around four operational doctrines: a plant-level **posture gate** that can halt operations when environmental compliance fails, strict **segregation of duties** so that no operator both initiates and approves a sensitive decision, exact **conservation of mass and money** across every workflow, and **optimistic concurrency control** on the three write paths where a stale read would otherwise silently succeed. Every mutation, including cascaded side effects, commits atomically within its request and is visible immediately in the response and in all subsequent reads.

## 2. Global Specifications & System-Wide Principles

This section fixes the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. If either header is missing, or if `X-User-Role` does not name one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is declared but not authorized for the target endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system declares eleven roles. `PlantManager` is the plant general manager and owns plant creation, decommissioning, agreement and contract approval, and settlement reopening and finalization. `ComplianceOfficer` handles environmental compliance: permits and their submission, odor-event intake and adjudication, batch compliance holds and adjudication, and vehicle quarantine. `Regulator` is the external authority that issues, suspends, reinstates, and revokes permits. `ProcurementManager` onboards suppliers and drafts, submits, and amends supply agreements, but may not approve them. `RouteDispatcher` owns the fleet and the road: vehicles, wash tickets, collection routes, route stops, and the shipment of finished product. `ScalehouseOperator` runs the weighbridge, receiving walk-in batches and performing initial screening, but may not adjudicate their own screenings. `ProductionSupervisor` owns cook runs from staging through completion and releases graded product lots, but may not release lots they graded. `QualityLabTech` records laboratory results and grades, downgrades, regrades, and rejects product lots. `SalesManager` owns customer contracts and sales orders up through confirmation, but may not approve their own contracts and may not ship. `FinanceAnalyst` publishes price index entries, invoices shipped orders, closes period settlements, and advances the settlement calendar. `Any` is a read-only pseudo-role: every declared role may perform every GET operation.

For each of these roles — `PlantManager`, `ComplianceOfficer`, `Regulator`, `ProcurementManager`, `RouteDispatcher`, `ScalehouseOperator`, `ProductionSupervisor`, `QualityLabTech`, `SalesManager`, `FinanceAnalyst`, and the pseudo-role `Any` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on resources where a workflow captures an actor — `created_by` on supplier agreements and customer contracts, `reported_by` and `confirmed_by` on odor events, `screened_by` on inbound batches, `graded_by` on product lots, `closed_by` on period settlements, `recorded_by` on wash tickets, and `published_by` on price index entries — and the segregation-of-duties checks of §2.10 compare those recorded identifiers against the caller's `X-User-ID`. It is never compared to any entity's `id`.

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

### 2.3. Pagination and List Filtering

List endpoints paginate through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Unless otherwise stated, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, each collection supports exact-match filtering on selected fields. Plants filter by `posture`; permits by `plant_id` and `status`; odor events by `plant_id`, `permit_id`, and `status`; suppliers by `plant_id`, `status`, and `supplier_type`; supplier agreements by `plant_id`, `supplier_id`, and `status`; vehicles by `plant_id`, `sanitation_status`, and `duty_class`; wash tickets by `plant_id`, `vehicle_id`, and `result`; collection routes by `plant_id`, `vehicle_id`, `status`, and `service_date`; route stops by `route_id`, `supplier_id`, `agreement_id`, `plant_id`, and `status`; inbound batches by `plant_id`, `supplier_id`, `agreement_id`, `route_stop_id`, `status`, and `species`; cook runs by `plant_id`, `status`, and `recipe`; product lots by `plant_id`, `cook_run_id`, `status`, `product_type`, and `grade`; customer contracts by `plant_id`, `status`, and `product_type`; sales orders by `contract_id`, `plant_id`, and `status`; price index entries by `plant_id` and `index_product`; period settlements by `plant_id`, `period_index`, and `status`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource; it anchors the optimistic concurrency checks of §2.8.

Two resource types are deliberately lighter. A wash ticket and a price index entry are both append-only records: each carries only `id` and `created_at`, and neither `updated_at` nor `version` exists on them, because they are never modified after creation.

Any mutation of a resource — including automatic transitions and cascaded side effects, and including changes confined to computed fields — refreshes that resource's `updated_at` and increments its `version`.

### 2.5. The Logical Clock and Scheduling Conventions

The server maintains a deterministic logical clock. At startup, before any operator intervention, the clock reads exactly `2026-08-01T00:00:00Z`; it never silently falls back to wall-clock time. A `PlantManager` may advance the clock through a test-driving capability that accepts a `to_iso8601` timestamp and responds with the resulting `current_utc`. Permit expiry, route dispatch window checks, and period-boundary decisions all observe this logical clock, never the host's wall clock.

Two time shapes coexist. Calendar dates — a permit's `expires_on`, agreement and contract windows, a route's `service_date`, an index entry's `effective_date`, an order's `requested_ship_date` — are plain `YYYY-MM-DD` dates. Instants — `scheduled_departure` and `scheduled_return` on routes, the stop window bounds, `cook_start` and `cook_end` on cook runs, `washed_at`, `received_at`, and `reported_at` — are full ISO 8601 timestamps. Route departure and return times and cook-run window bounds must fall on whole hours, and a cook run's window duration must itself be a whole number of hours.

### 2.6. Units, Precision, and Rounding

All monetary amounts are integer numbers of cents; there are no fractional cents anywhere in the system. Weights and distances are integers — pounds and miles respectively. Laboratory inputs (`lab_moisture_pct`, `lab_ffa_pct`, `lab_protein_pct`) are percentages recorded to one decimal place.

Computed percentages — `yield_variance_pct` on a cook run and `margin_pct` on a sales order or a period settlement — are rounded half-up to two decimal places. Where a calculation requires rounding to whole units (per-line theoretical yields, the volume-discount portion of a pickup fee, the unit price of an order, the discount portion of an order), the rounding method is always round half-up to the nearest integer. The exact points where rounding occurs are pinned in the workflow narratives of §3, because rounding at the wrong step produces a different cent.

### 2.7. Plant Posture as an Operational Gate

Every plant carries a `posture`, one of `OPERATING`, `RESTRICTED`, `SUSPENDED`, or `DECOMMISSIONED`, starting at `OPERATING` when the plant is created. Posture is not set directly; it moves in response to odor-score dynamics and permit health, as detailed in §3.1 and §3.2.

Posture gates every mutating operational endpoint. While a plant is `SUSPENDED`, every operational mutation on its routes, stops, batches, cook runs, sales orders, and price index entries — creations and action endpoints alike — is rejected with `ERR_PLANT_SUSPENDED` (HTTP 409); administrative entities (permits, odor events, suppliers, agreements, vehicles, wash tickets, contracts, and settlements) remain writable while the plant is suspended, because remediation must not be blocked by the sanction itself. While a plant is `RESTRICTED`, operations otherwise remain open, but two specific actions are forbidden: dispatching a collection route and starting a cook run. Attempting either returns `ERR_PLANT_RESTRICTED` (HTTP 409). A `DECOMMISSIONED` plant rejects every mutation with `ERR_PLANT_DECOMMISSIONED` (HTTP 409); decommissioning is terminal.

Posture transitions cascade. When a plant falls to `SUSPENDED` — whether by permit suspension, revocation, or expiry — every collection route still in `PLANNED`, `DISPATCHED`, or `IN_PROGRESS` is cancelled; every stop on those routes in `SCHEDULED` or `ARRIVED` is cancelled; every stop in `COLLECTED` is instead moved to `VOIDED`, its final fee and transport cost reversed out of the current period settlement, and the inbound batch it created is moved to `REJECTED`. When a plant is decommissioned, all non-terminal routes are cancelled with this same stop cascade, and all non-terminal sales orders are cancelled.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, because each leaves its parent resource in a state that would otherwise permit a second, stale write to succeed undetected:

- Creating a sales order (capability: order creation against a contract) requires the request to carry `expected_contract_version`, the contract `version` the client last observed. If the contract's current `version` has advanced past that value, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than allowing the client to book against contract terms it has not observed. A successful creation itself increments the contract's `version` by one.
- Adding a route stop to a collection route requires `expected_route_version`, the route `version` the client last observed. A mismatch with the route's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful stop creation increments the route's `version` by one.
- Amending a supplier agreement's commercial terms requires `expected_agreement_version`, the agreement `version` the client last observed. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful amend increments the agreement's `version` by one.

No other endpoint accepts a version field. The rejection is framed purely as a stale-version check: the client read a version, the resource has since moved, and the write is refused so the client can re-read and retry.

### 2.9. Validation Order and Error Precedence

When several validation rules could reject the same request, the server evaluates them in a fixed priority order and reports the first failure encountered. The order, from first to last:

1. **Caller context.** `X-User-ID` and `X-User-Role` must be present, and the role must be one of the declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Request schema.** Required fields must be present, types must be correct, enum values must belong to their declared domains, integer quantities must be at least 1 where so declared, `scheduled_return` must be strictly later than `scheduled_departure`, `cook_end` must be strictly later than `cook_start` with a whole-hour duration, `effective_to` must be on or after `effective_from`, and `species_scope` must be non-empty. Violations return `ERR_INVALID_REQUEST` (400).
3. **Role authorization.** The caller's role must be listed for the endpoint; otherwise `ERR_INSUFFICIENT_PERMISSIONS` (403).
4. **Existence.** Every identifier in the path must exist, then every foreign-key identifier in the body must exist, validated left-to-right — path first, then body fields in their declared order. The first missing resource yields its specific 404: `ERR_PLANT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_WASH_TICKET_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_COOK_RUN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INDEX_ENTRY_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_ODOR_EVENT_NOT_FOUND`.
5. **Plant posture gate.** As specified in §2.7: `ERR_PLANT_SUSPENDED`, `ERR_PLANT_RESTRICTED`, or `ERR_PLANT_DECOMMISSIONED` (all 409).
6. **Source state.** The target resource must be in a valid from-state for the requested transition, otherwise the transition's specific 409: `ERR_PERMIT_INVALID_STATE`, `ERR_SUPPLIER_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_VEHICLE_INVALID_STATE`, `ERR_ROUTE_INVALID_STATE`, `ERR_STOP_INVALID_STATE`, `ERR_BATCH_INVALID_STATE`, `ERR_COOK_RUN_INVALID_STATE`, `ERR_LOT_INVALID_STATE`, `ERR_CONTRACT_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_SETTLEMENT_INVALID_STATE`, or `ERR_ODOR_EVENT_ALREADY_RESOLVED`.
7. **Segregation of duties.** The approving or adjudicating actor must differ from the initiating actor, as detailed in §2.10; otherwise `ERR_SOD_VIOLATION` (403).
8. **Vehicle sanitation and duty.** Dispatch requires a `SANITIZED` vehicle of `RAW_MATERIAL` or `DUAL` duty; shipping requires a `SANITIZED` vehicle of `FINISHED_PRODUCT` or `DUAL` duty; washing a quarantined vehicle requires a deep wash. Violations return `ERR_VEHICLE_NOT_SANITIZED` (409), `ERR_VEHICLE_DUTY_MISMATCH` (409), or `ERR_DEEP_WASH_REQUIRED` (422).
9. **Species and sourcing compliance.** Cook-run inputs must fit the recipe's allowed species set (`ERR_SPECIES_MIXING_VIOLATION`, 422); a stop's `species_tag` must lie inside its agreement's `species_scope` (`ERR_SPECIES_OUT_OF_SCOPE`, 422); a dead-stock stop requires an agreement that accepts dead stock (`ERR_DEAD_STOCK_NOT_ACCEPTED`, 422).
10. **Product specification.** Every allocated lot must satisfy the contract's specification; otherwise `ERR_SPEC_BELOW_CONTRACT_MIN` (422).
11. **Cross-entity state.** Stop creation requires the supplier `ACTIVE` (`ERR_SUPPLIER_NOT_ACTIVE`, 409) and the agreement `ACTIVE` and belonging to that supplier (`ERR_AGREEMENT_NOT_ACTIVE`, 409); order creation, pricing, and confirmation require the contract `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`, 409); cook-run inputs must be batches in `ACCEPTED` (`ERR_BATCH_NOT_ACCEPTED`, 409); agreement reinstatement requires the supplier `ACTIVE` (`ERR_SUPPLIER_NOT_ACTIVE`).
12. **Uniqueness and overlap.** At most one `ACTIVE` or `SUSPENDED` permit per plant (`ERR_DUPLICATE_ACTIVE_PERMIT`, 409); no overlapping `ACTIVE`/`SUSPENDED` agreement windows for one supplier (`ERR_AGREEMENT_WINDOW_OVERLAP`, 409); a price index entry is unique per plant, product, and effective date (`ERR_DUPLICATE_INDEX_ENTRY`, 409); no vehicle schedule overlap (`ERR_VEHICLE_SCHEDULE_OVERLAP`, 409); cooker aggregate capacity respected (`ERR_COOKER_CAPACITY_EXCEEDED`, 409).
13. **Capacity and allocation sums**, evaluated in this listed order within a request: route planned load against vehicle capacity (`ERR_ROUTE_OVER_CAPACITY`, 422); cook-run `planned_inputs` non-empty (`ERR_EMPTY_INPUT`, 422); each cook input weight within its batch's `remaining_lbs` (`ERR_WEIGHT_EXCEEDS_REMAINING`, 422); dispatch requires at least one non-cancelled stop (`ERR_ROUTE_EMPTY`, 422); an order's allocation sum must equal its ordered quantity (`ERR_ALLOCATION_MISMATCH`, 422) **before** per-lot availability is examined (`ERR_INSUFFICIENT_LOT_QUANTITY`, 422); a manual route cancel is blocked while any stop is `COLLECTED` (`ERR_ROUTE_HAS_COLLECTED_STOPS`, 409); a stop's `sequence_no` must be unique per route among non-`CANCELLED` stops (`ERR_DUPLICATE_STOP_SEQUENCE`, 422).
14. **Yield tolerance.** A cook run whose absolute yield variance exceeds 25 percent may only complete with an operator override; otherwise `ERR_YIELD_OUT_OF_TOLERANCE` (422).
15. **Temporal windows.** A stop's planned window must sit inside its route's window (`ERR_WINDOW_OUTSIDE_ROUTE`, 422); dispatch must not occur after the route's `scheduled_return` per the logical clock (`ERR_ROUTE_WINDOW_PASSED`, 422); a route's `service_date` must lie within each stop's agreement window (`ERR_AGREEMENT_NOT_IN_EFFECT`, 422); an order's `requested_ship_date` must lie within its contract window (`ERR_CONTRACT_NOT_IN_EFFECT`, 422).
16. **Index availability.** Index-linked pricing requires a suitable published index entry; otherwise `ERR_NO_INDEX_FOR_DATE` (422).
17. **Margin floor.** A confirming order's margin must meet the contract floor; otherwise `ERR_MARGIN_FLOOR_BREACH` (402).
18. **Period openness.** Fee accrual at collection, fee reversal at void, revenue accrual at invoice, and calendar advancement all consult the settlement calendar; violations return `ERR_PERIOD_CLOSED` (409) or `ERR_SETTLEMENT_NOT_CLOSED` (409).

### 2.10. Segregation of Duties

Six decisions in the plant require a second pair of eyes, and the system enforces each mechanically by comparing `X-User-ID` to a recorded actor field. A supplier agreement may only be approved by someone other than its `created_by` drafter. A customer contract may only be approved by someone other than its `created_by` drafter. An odor event may only be confirmed or dismissed by someone other than its `reported_by` logger. A quarantined batch may only be adjudicated by someone other than the `screened_by` screener, when a screener is recorded. A product lot may only be released by someone other than the `graded_by` lab technician. A period settlement may only be finalized by someone other than its `closed_by` closer. Each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

### 2.11. Conservation of Mass and Money

Two invariants hold at every instant, not merely at period close, and every workflow in §3 is written against them.

**Batch mass conservation.** For every inbound batch, its `weight_lbs` always equals the sum of its `remaining_lbs`, `reserved_lbs`, and `consumed_lbs`. Staging a cook run moves pounds from `remaining_lbs` into `reserved_lbs`; completing a cook run moves them from `reserved_lbs` into `consumed_lbs`; cancelling a staged or failed run moves them from `reserved_lbs` back into `remaining_lbs`. A stage followed by a cancel of the same run must restore `remaining_lbs` to exactly its prior value.

**Settlement accrual conservation.** The current period settlement's `pickup_fees_accrued_cents` tracks the running sum of `final_fee_cents` over the period's collected and delivered stops, minus reversals. Collecting a stop and later voiding that same stop must leave `pickup_fees_accrued_cents`, `transport_costs_cents`, and the supplier's `outstanding_service_fees_cents` exactly at their pre-collection values. Reversals always land in the settlement whose `period_index` matches the plant's `current_period_index`; voiding a stop collected in an earlier, already-advanced period is rejected with `ERR_PERIOD_CLOSED`.

## 3. Business Logic & Workflows

### 3.1. Plant Onboarding and the Settlement Calendar

A `PlantManager` brings a rendering plant into the system by supplying its `plant_name`, its `location`, its `cooker_capacity` — the maximum number of cook runs that may occupy an active cooking stage at once, which must be at least 1 — and its `standard_cost_cents_per_lb`, the standard production cost basis per finished pound that later anchors order margin checks. A new plant starts with `posture` `OPERATING`, an `odor_score` of 1000 on its 0-to-1000 scale, and `current_period_index` 1. Creation also opens the plant's first `PeriodSettlement`: `period_index` 1, status `OPEN`, with `pickup_fees_accrued_cents`, `product_revenue_cents`, `energy_costs_cents`, `transport_costs_cents`, and `confirmed_odor_events` all zero.

Each settlement is the plant's financial ledger page for one period. Its `gross_margin_cents` is always derivable as `product_revenue_cents` plus `pickup_fees_accrued_cents` minus `energy_costs_cents` minus `transport_costs_cents`. Its `margin_pct` expresses that gross margin as a percentage of the sum of product revenue and pickup fees, rounded half-up to two decimal places, and is null whenever that revenue sum is zero.

When a plant has reached the end of its life, a `PlantManager` may decommission it from `OPERATING`, `RESTRICTED`, or `SUSPENDED` posture; attempting to decommission a plant already `DECOMMISSIONED` is rejected with `ERR_PLANT_DECOMMISSIONED`. Decommissioning moves the plant to `DECOMMISSIONED` and cascades: every non-terminal collection route is cancelled (with the stop cascade of §2.7 applied), and every non-terminal sales order is cancelled. The plant's history remains readable.

### 3.2. Environmental Permits and Odor Compliance

A rendering plant cannot legally operate without its environmental permit, and the API treats permit health as a first-class driver of plant posture. A `ComplianceOfficer` registers a permit with its `plant_id`, the regulator's `permit_number`, an `odor_event_threshold` of at least 1 (the number of confirmed odor events in a single period that automatically suspends the permit), the permitted `emission_limit_ppm` ceiling, and an `expires_on` date; the permit expires automatically once the logical clock passes that date. A new permit is `DRAFT` with `confirmed_violation_count` zero and `issued_on` null.

From `DRAFT`, the compliance officer submits the permit, moving it to `PENDING_ISSUANCE`; submitting from any other state is rejected with `ERR_PERMIT_INVALID_STATE`. A `Regulator` then issues it: the permit must be `PENDING_ISSUANCE`, no other permit of the same plant may be `ACTIVE` or `SUSPENDED` (violations return `ERR_DUPLICATE_ACTIVE_PERMIT`), and `expires_on` must be on or after the current logical date — a lapsed permit cannot be issued and the attempt returns `ERR_PERMIT_INVALID_STATE`. Issuance stamps `issued_on` with the current logical date, moves the permit to `ACTIVE`, and, if the plant's posture is `SUSPENDED`, recomputes that posture: `OPERATING` when the plant's `odor_score` is at least 700, otherwise `RESTRICTED`.

A permit leaves `ACTIVE` along three paths. A `Regulator` may suspend it directly, and the system suspends it automatically the moment its `confirmed_violation_count` reaches its `odor_event_threshold`; either way the plant's posture falls to `SUSPENDED` with the full route, stop, batch, and fee cascade of §2.7. A `Regulator` may revoke a permit from either `ACTIVE` or `SUSPENDED`, moving it to the terminal `REVOKED` state — from `ACTIVE` this again drops the plant to `SUSPENDED` with the cascade, while from `SUSPENDED` the plant is already suspended and no further cascade fires; revoking from any other state returns `ERR_PERMIT_INVALID_STATE`. Finally, when the settlement calendar advances (§3.9), any `ACTIVE` permit whose `expires_on` is earlier than the current logical date becomes `EXPIRED`, with the same plant suspension cascade.

A suspended permit is not dead. A `Regulator` may reinstate it provided it is `SUSPENDED` (otherwise `ERR_PERMIT_INVALID_STATE`) and its `expires_on` is still on or after the current logical date (otherwise `ERR_PERMIT_INVALID_STATE`). Reinstatement returns the permit to `ACTIVE`, resets its `confirmed_violation_count` to zero, and recomputes plant posture: `OPERATING` when `odor_score` is at least 700, `RESTRICTED` below that.

Odor complaints are the permit's adversary. A `ComplianceOfficer` logs an odor event with its `plant_id`, the `reported_at` complaint timestamp, a free-text `location_description`, and a `severity` of `LOW`, `MEDIUM`, or `HIGH`; the event starts `REPORTED` with the caller recorded as `reported_by` and `permit_id` null. A different compliance officer then resolves it. Confirmation requires the event still `REPORTED` — an already-resolved event, whether `CONFIRMED` or `DISMISSED`, rejects with `ERR_ODOR_EVENT_ALREADY_RESOLVED` — and the confirmer must differ from `reported_by` (`ERR_SOD_VIOLATION`). On confirmation the server records `confirmed_by`, links `permit_id` to the plant's `ACTIVE` permit when one exists, and applies the severity penalty to the plant's `odor_score`: 50 points for `LOW`, 100 for `MEDIUM`, 150 for `HIGH`, never driving the score below 0. If the penalized score falls below 600 while the plant is `OPERATING`, posture drops to `RESTRICTED`. The current period settlement's `confirmed_odor_events` increments by one, and when a permit was linked, its `confirmed_violation_count` increments by one — reaching the permit's `odor_event_threshold` suspends the permit, which suspends the plant, which cancels non-terminal routes and stops and voids collected-stop fees per §2.7. Dismissal, with the same `REPORTED` precondition and the same segregation-of-duties check, moves the event to `DISMISSED` and changes no scores.

The odor score has hysteresis. A confirm-time penalty only pushes posture to `RESTRICTED` when it crosses below 600; recovery only restores `OPERATING` when the score reaches at least 700 (§3.9). Scores from 600 up to 699 cause no posture transition in either direction.

### 3.3. Supplier Onboarding and Supply Agreements

A `ProcurementManager` onboards each supplier with its `plant_id`, a `supplier_name`, and a `supplier_type` of `FARM`, `SLAUGHTERHOUSE`, `BUTCHER_SHOP`, or `GROCERY`. New suppliers start `ACTIVE` with `contamination_strikes` zero and `outstanding_service_fees_cents` zero — the latter being the running balance of unpaid dead-stock and pickup service fees the supplier owes the plant.

Contamination is a three-strikes discipline. Each site rejection for prohibited material (§3.4) adds one strike; the instant `contamination_strikes` reaches 3 the supplier is automatically `SUSPENDED`, every one of its `ACTIVE` agreements is suspended, and every one of its stops still in `SCHEDULED` or `ARRIVED` is cancelled. A `ProcurementManager` may reinstate a `SUSPENDED` supplier (any other state returns `ERR_SUPPLIER_INVALID_STATE`), which returns it to `ACTIVE` and resets `contamination_strikes` to zero — but deliberately does not reinstate its agreements; each suspended agreement must be reinstated separately. Termination is available from `ACTIVE` or `SUSPENDED` (anything else returns `ERR_SUPPLIER_INVALID_STATE`) and moves the supplier to the terminal `TERMINATED` state, terminates every non-`TERMINATED` agreement it holds, and cancels its `SCHEDULED` and `ARRIVED` stops.

Supply agreements are drafted per supplier. The create payload names the `supplier_id` and a `plant_id` that must equal the supplier's owning plant, plus an external `agreement_ref`; the commercial heart of the agreement is its `species_scope` (a non-empty subset of `BOVINE`, `PORCINE`, `POULTRY`, `OVINE`, and `MIXED`), its `prohibited_material_policy` of `ZERO_TOLERANCE` or `SORT_AND_RETURN`, whether it `accepts_dead_stock`, and its fee schedule: `pickup_base_fee_cents`, `per_lb_fee_cents`, and `mileage_rate_cents`, each at least 0, an optional `dead_stock_surcharge_cents` defaulting to 0, an optional `minimum_volume_lbs` defaulting to 0 (zero disables the volume discount), and an optional `volume_discount_pct` defaulting to 0. The agreement's window runs from `effective_from` through `effective_to`, both inclusive, with `effective_to` no earlier than `effective_from`. A new agreement is `DRAFT`, and the server records the caller as `created_by`.

The drafting workflow is: `DRAFT` → `SUBMITTED` → `ACTIVE`. The drafter submits; submission from any other state returns `ERR_AGREEMENT_INVALID_STATE`. A `PlantManager` approves, and approval is where the agreement earns its constraints: the agreement must be `SUBMITTED` (`ERR_AGREEMENT_INVALID_STATE`), the approver must differ from `created_by` (`ERR_SOD_VIOLATION`), and no other `ACTIVE` or `SUSPENDED` agreement of the same supplier may have a window overlapping this one's `effective_from`-to-`effective_to` span (`ERR_AGREEMENT_WINDOW_OVERLAP`). A `PlantManager` may instead return a `SUBMITTED` agreement to `DRAFT` for revision.

An `ACTIVE` agreement can be suspended — manually by a `PlantManager`, or automatically by the supplier strike cascade — which cancels every stop referencing it that is still `SCHEDULED` or `ARRIVED`; manual suspension of a non-`ACTIVE` agreement returns `ERR_AGREEMENT_INVALID_STATE`. Reinstatement requires the agreement `SUSPENDED` (`ERR_AGREEMENT_INVALID_STATE`) and its supplier currently `ACTIVE` (`ERR_SUPPLIER_NOT_ACTIVE`), and returns it to `ACTIVE`. Termination is permitted from `DRAFT`, `SUBMITTED`, `ACTIVE`, or `SUSPENDED` (other states return `ERR_AGREEMENT_INVALID_STATE`) and is terminal; terminating from `ACTIVE` or `SUSPENDED` additionally cancels the agreement's `SCHEDULED` and `ARRIVED` stops, while terminating from `DRAFT` or `SUBMITTED` has no stops to cancel.

Commercial terms on an `ACTIVE` agreement evolve through amendment rather than replacement. A `ProcurementManager` amends in place — the agreement stays `ACTIVE` — passing `expected_agreement_version` per §2.8 together with any subset of the amendable fields: `pickup_base_fee_cents`, `per_lb_fee_cents`, `mileage_rate_cents`, `dead_stock_surcharge_cents`, `minimum_volume_lbs`, `volume_discount_pct`, and `effective_to`. A stale `expected_agreement_version` is rejected with `ERR_STALE_VERSION` (HTTP 412); a successful amendment increments the agreement's `version` by one.

### 3.4. Fleet Sanitation and Collection Logistics

Vehicles are the plant's circulatory system, and sanitation law treats them accordingly. A `RouteDispatcher` registers each vehicle with its `plant_id`, a fleet `vehicle_tag`, a `capacity_lbs` of at least 1, and a `duty_class` of `RAW_MATERIAL`, `FINISHED_PRODUCT`, or `DUAL`. A new vehicle's `sanitation_status` is `SANITIZED` and its `completed_trip_count` is zero.

The sanitation lifecycle is a loop with a quarantine branch. Completing a collection route, or shipping a sales order on the vehicle, moves it from `SANITIZED` to `DIRTY` and adds 1 to `completed_trip_count`. Recording a wash ticket with `result` `PASS` returns a `DIRTY` vehicle to `SANITIZED`; a wash ticket carries the `vehicle_id`, a `plant_id` equal to the vehicle's plant, a `wash_type` of `STANDARD` or `DEEP`, the `washed_at` timestamp, the `detergent_ppm` concentration used, the `result` of `PASS` or `FAIL`, and the recording caller's `recorded_by`. A `FAIL` result leaves sanitation unchanged, and washing an already-`SANITIZED` vehicle is a harmless no-op that still records the ticket and returns success. A `ComplianceOfficer` may quarantine a vehicle from `SANITIZED` or `DIRTY` — quarantining an already-`QUARANTINED` vehicle returns `ERR_VEHICLE_INVALID_STATE` — and a quarantined vehicle can only be cleared by a `DEEP` wash that passes: requesting a `STANDARD` wash on a `QUARANTINED` vehicle is rejected with `ERR_DEEP_WASH_REQUIRED`, and a failing deep wash leaves the vehicle `QUARANTINED`.

Collection routes bind a vehicle to a day's rounds. The dispatcher creates a route with its `plant_id`, the assigned `vehicle_id`, a human `route_code`, a `service_date`, and a whole-hour window from `scheduled_departure` to the strictly later `scheduled_return`. The vehicle is validated at creation: it must be `SANITIZED` (`ERR_VEHICLE_NOT_SANITIZED`), its `duty_class` must be `RAW_MATERIAL` or `DUAL` (`ERR_VEHICLE_DUTY_MISMATCH`), and its schedule must be free of conflicts. Routes occupy half-open windows: a new route conflicts with an existing route of the same vehicle exactly when the existing route is `PLANNED`, `DISPATCHED`, or `IN_PROGRESS`, the new route's `scheduled_departure` is earlier than the existing route's `scheduled_return`, and the existing route's `scheduled_departure` is earlier than the new route's `scheduled_return`. Adjacency is explicitly not a conflict — a new route departing exactly when an existing one returns, or returning exactly when an existing one departs, is allowed. A genuine conflict is rejected with `ERR_VEHICLE_SCHEDULE_OVERLAP`. A new route starts `PLANNED` with `total_collected_lbs` zero.

Dispatch is the route's point of no return. A dispatcher may dispatch a route that is `PLANNED` (any other state: `ERR_ROUTE_INVALID_STATE`); the plant must be `OPERATING` — `RESTRICTED` posture returns `ERR_PLANT_RESTRICTED` and `SUSPENDED` returns `ERR_PLANT_SUSPENDED`; at least one non-`CANCELLED` stop must exist (`ERR_ROUTE_EMPTY`); the vehicle must still be `SANITIZED` (`ERR_VEHICLE_NOT_SANITIZED`) and of `RAW_MATERIAL` or `DUAL` duty (`ERR_VEHICLE_DUTY_MISMATCH`); and the current logical time must not be later than `scheduled_return` (`ERR_ROUTE_WINDOW_PASSED`); and the route's `service_date` must still lie within each stop's agreement window (`ERR_AGREEMENT_NOT_IN_EFFECT`). Dispatch moves the route to `DISPATCHED`; the first stop arrival then moves it automatically to `IN_PROGRESS`.

Stops are added while the route is `PLANNED` — adding to a route in any other state returns `ERR_ROUTE_INVALID_STATE` — and each stop is a small contract of expectations. The create payload carries the `route_id`, the `supplier_id`, the `agreement_id` of an agreement belonging to that supplier, a `plant_id` equal to the route's plant, a `sequence_no` of at least 1 that must be unique within the route among non-`CANCELLED` stops (`ERR_DUPLICATE_STOP_SEQUENCE`), the planned arrival window from `scheduled_window_start` to a strictly later `scheduled_window_end` (both must fall within the route's departure-to-return window, else `ERR_WINDOW_OUTSIDE_ROUTE`), an `estimated_weight_lbs` of at least 1, an `estimated_distance_miles` of at least 0, a `species_tag` drawn from the five species values, whether the stop `is_dead_stock`, and the `expected_route_version` guard of §2.8. Cross-entity checks then apply: the supplier must be `ACTIVE` (`ERR_SUPPLIER_NOT_ACTIVE`), the agreement must be `ACTIVE` and belong to the named supplier (`ERR_AGREEMENT_NOT_ACTIVE`), the route's `service_date` must lie within the agreement's `effective_from`-to-`effective_to` window (`ERR_AGREEMENT_NOT_IN_EFFECT`), the `species_tag` must appear in the agreement's `species_scope` (`ERR_SPECIES_OUT_OF_SCOPE`), and a stop marked `is_dead_stock` requires the agreement to accept dead stock (`ERR_DEAD_STOCK_NOT_ACCEPTED`). Capacity is checked in aggregate: the planned load — the sum of `estimated_weight_lbs` over the route's stops currently `SCHEDULED` or `ARRIVED`, plus the new stop's own estimate — must not exceed the vehicle's `capacity_lbs`. Equality is allowed; one pound over returns `ERR_ROUTE_OVER_CAPACITY`. A created stop starts `SCHEDULED` with `actual_weight_lbs`, `actual_distance_miles`, and `final_fee_cents` null until collection and `rejection_reason` null unless the stop is rejected; its creation increments the route's `version` by one, and the server records a `provisional_fee_cents` estimate: the agreement's `pickup_base_fee_cents`, plus `estimated_weight_lbs` times `per_lb_fee_cents`, plus `estimated_distance_miles` times `mileage_rate_cents`, plus `dead_stock_surcharge_cents` when the stop is a dead-stock pickup. The provisional estimate never includes the volume discount.

On the road, a dispatcher marks a `SCHEDULED` stop `ARRIVED` (wrong stop state: `ERR_STOP_INVALID_STATE`; the route must be `DISPATCHED` or `IN_PROGRESS`, else `ERR_ROUTE_INVALID_STATE`), and the route's first arrival moves the route from `DISPATCHED` to `IN_PROGRESS`. A stop that never materializes is marked `MISSED` from `SCHEDULED` under the same route-state precondition.

Collection is the financially decisive act. From `ARRIVED`, the dispatcher records the scale weight `actual_weight_lbs`, the `actual_distance_miles`, and the material's `temperature_f`. The current period settlement must be `OPEN` or `REOPENED` (`ERR_PERIOD_CLOSED`). The stop becomes `COLLECTED` and the server settles its `final_fee_cents`: the agreement's `pickup_base_fee_cents`, plus `actual_weight_lbs` times `per_lb_fee_cents`, plus `actual_distance_miles` times `mileage_rate_cents`, plus `dead_stock_surcharge_cents` when the stop is a dead-stock pickup — and then, when the agreement's `minimum_volume_lbs` is greater than zero and the supplier's current-period collected volume reaches or exceeds that minimum, a discount equal to the subtotal times `volume_discount_pct`, rounded half-up to whole cents, is subtracted. The supplier's current-period collected volume is the sum of `actual_weight_lbs` over this supplier's stops collected into the current period — the period whose `period_index` equals the plant's `current_period_index` — including this stop. Because the provisional estimate never applies the discount and uses estimates rather than actuals, a stop generally settles at a different amount than its estimate. Collection also creates the corresponding `InboundBatch` in `RECEIVED` with `screening_result` `PENDING`, its `weight_lbs` equal to the stop's `actual_weight_lbs`, its species carried from the stop's `species_tag`, its `temperature_f` as recorded at the truck, and its `route_stop_id` pointing back to this stop. Financially, the current period settlement's `pickup_fees_accrued_cents` increases by the final fee, its `transport_costs_cents` increases by the actual miles times the fleet transport rate of 150 cents per mile, and the supplier's `outstanding_service_fees_cents` increases by the final fee. Because collection creates the batch resource, the collection call returns 201 rather than 200.

A stop rejected at the supplier's site — from `ARRIVED` (`ERR_STOP_INVALID_STATE` otherwise) — becomes `REJECTED_AT_SITE` with a `rejection_reason` of `PROHIBITED_MATERIAL`, `TEMPERATURE_EXCURSION`, or `OTHER`; no fee accrues and `final_fee_cents` stays null. When the reason is `PROHIBITED_MATERIAL`, the supplier's `contamination_strikes` increments by one, and the third strike triggers the supplier suspension cascade of §3.3.

From `COLLECTED`, the dispatcher marks the stop `DELIVERED` when the truck unloads at the plant. A collected or delivered stop can still be unwound by voiding — but only while its effects remain reversible: the linked batch must have `reserved_lbs` and `consumed_lbs` both zero (otherwise `ERR_BATCH_INVALID_STATE`), and the current period settlement must be `OPEN` or `REOPENED` (`ERR_PERIOD_CLOSED`). Voiding moves the stop to `VOIDED`, subtracts the final fee from `pickup_fees_accrued_cents`, subtracts the actual miles times 150 cents from `transport_costs_cents`, subtracts the final fee from the supplier's `outstanding_service_fees_cents`, and moves the linked batch to `REJECTED` — exactly restoring the pre-collection ledger per §2.11. Attempting to void from any stop state other than `COLLECTED` or `DELIVERED` returns `ERR_STOP_INVALID_STATE`.

A route completes when its book of stops is closed: the route must be `DISPATCHED` or `IN_PROGRESS` (`ERR_ROUTE_INVALID_STATE`) and every stop must be terminal — `DELIVERED`, `REJECTED_AT_SITE`, `MISSED`, `CANCELLED`, or `VOIDED` (`ERR_STOP_INVALID_STATE`). Completion moves the route to `COMPLETED`, sets its `total_collected_lbs` to the sum of `actual_weight_lbs` over its stops in `DELIVERED` or `VOIDED`, turns the vehicle `DIRTY`, and adds 1 to its `completed_trip_count`. Manual cancellation is available from `PLANNED`, `DISPATCHED`, or `IN_PROGRESS` but is refused while any stop is `COLLECTED` (`ERR_ROUTE_HAS_COLLECTED_STOPS`) — such stops must first be delivered or voided — and cancels every `SCHEDULED` or `ARRIVED` stop. System-driven cancellation (plant suspension or decommission, supplier suspension, agreement suspension) applies the same stop cancellations and additionally voids `COLLECTED` stops with the fee and batch reversal described above.

### 3.5. Receiving, Screening, and Batch Adjudication

Raw material enters inventory as an inbound batch, either created automatically by a stop collection (§3.4) or recorded directly by a `ScalehouseOperator` as walk-in receiving. The walk-in payload names the `plant_id`, the origin `supplier_id`, the governing `agreement_id`, the material `species` (`BOVINE`, `PORCINE`, `POULTRY`, `OVINE`, or `MIXED`), the received gross `weight_lbs` of at least 1, the `temperature_f` at receipt, and the `received_at` timestamp; its `route_stop_id` stays null, distinguishing walk-ins from route-delivered material. Every new batch starts `RECEIVED` with `screening_result` `PENDING`, `reserved_lbs` zero, `consumed_lbs` zero, `remaining_lbs` equal to its `weight_lbs`, and `screened_by` null until screening.

Screening is the scalehouse's first-quality gate. Screening a `RECEIVED` batch (from any other state: `ERR_BATCH_INVALID_STATE`) records the `screening_result` and the screener's `screened_by`, and routes the batch by outcome and by the governing agreement's `prohibited_material_policy`: a `PASS` moves the batch to `ACCEPTED`; a `FAIL_TEMPERATURE` moves it to `QUARANTINED`; a `FAIL_PROHIBITED` moves it to `REJECTED` under a `ZERO_TOLERANCE` policy but only to `QUARANTINED` under `SORT_AND_RETURN`, giving the material a chance at adjudicated return. Independently of screening, a `ComplianceOfficer` may place a compliance hold on a `RECEIVED` batch, moving it straight to `QUARANTINED`.

A quarantined batch awaits adjudication by a `ComplianceOfficer`, who supplies a `decision` of `ACCEPT` or `REJECT`. The batch must be `QUARANTINED` (`ERR_BATCH_INVALID_STATE`), and when a `screened_by` screener is recorded the adjudicator must be someone else (`ERR_SOD_VIOLATION`). `ACCEPT` moves the batch to `ACCEPTED`; `REJECT` moves it to `REJECTED`, which is terminal.

Cook runs draw down a batch's mass per §3.6, and the batch's books always balance per the conservation invariant of §2.11: `weight_lbs` equals `remaining_lbs` plus `reserved_lbs` plus `consumed_lbs` at all times. Pounds are reserved while referencing cook runs are `STAGED`, `COOKING`, `SETTLING`, `PRESSING`, or `FAILED`, and consumed when a referencing run completes. When a completion leaves a batch's `remaining_lbs` at exactly 0 with `consumed_lbs` greater than 0, the batch automatically becomes `DEPLETED`, which is terminal.

### 3.6. Cook Runs: Staging, Segregation, and Yield Settlement

Rendering happens in cook runs, staged by a `ProductionSupervisor` with the `plant_id`, a `cooker_line` identifier of at least 1, a `recipe` of `RUMINANT_RENDER`, `PORCINE_RENDER`, `POULTRY_RENDER`, or `MIXED_RENDER`, the cook window from `cook_start` to a strictly later `cook_end` (whole-hour bounds, whole-hour duration), and a non-empty `planned_inputs` list whose entries each pair a `batch_id` with a `weight_lbs` of at least 1. An empty input list is rejected with `ERR_EMPTY_INPUT`.

Species segregation is absolute. `RUMINANT_RENDER` accepts only `BOVINE` and `OVINE` inputs — and uniquely, those two may be mixed in one run; `PORCINE_RENDER` accepts only `PORCINE`; `POULTRY_RENDER` accepts only `POULTRY`; `MIXED_RENDER` accepts `BOVINE`, `OVINE`, and `PORCINE` — poultry is never permitted in a mixed render. Any input batch outside the recipe's allowed set is rejected with `ERR_SPECIES_MIXING_VIOLATION`. Every input batch must also be in `ACCEPTED` status — never `QUARANTINED`, never `REJECTED` — or the staging fails with `ERR_BATCH_NOT_ACCEPTED`. Each input's planned weight must not exceed its batch's current `remaining_lbs` (`ERR_WEIGHT_EXCEEDS_REMAINING`).

Cooker capacity is enforced in aggregate, not per line: `cooker_line` is informational and does not partition capacity. The server counts the plant's cook runs in `STAGED`, `COOKING`, `SETTLING`, or `PRESSING` whose half-open cook windows overlap the new run's window — two windows overlap exactly when each one's start is earlier than the other's end; windows merely touching at an endpoint do not overlap — and that count must be strictly less than the plant's `cooker_capacity`, else staging is rejected with `ERR_COOKER_CAPACITY_EXCEEDED`. Staging is an operational mutation, so the §2.7 posture gate applies: a `SUSPENDED` plant refuses it, while a `RESTRICTED` plant still permits staging.

A staged run starts `STAGED` with `recook_count` zero and `failure_reason` null. The server immediately computes its theoretical yield. For each planned input line, the line's weight is multiplied by the fat coefficient of that batch's species — 0.16 for `BOVINE`, 0.14 for `PORCINE`, 0.10 for `POULTRY`, 0.15 for `OVINE`, 0.12 for `MIXED` — and the product rounded half-up to a whole pound; `theoretical_fat_lbs` is the sum of those per-line rounded values. `theoretical_meal_lbs` is computed identically with the meal coefficients — 0.24 for `BOVINE`, 0.22 for `PORCINE`, 0.30 for `POULTRY`, 0.23 for `OVINE`, 0.25 for `MIXED`. `total_input_lbs` is the plain sum of the planned input weights. At the same moment, each input batch's `reserved_lbs` increases by its planned weight and its `remaining_lbs` decreases by the same amount.

Starting the run — `STAGED` to `COOKING` — is one of the two operations a `RESTRICTED` posture forbids (`ERR_PLANT_RESTRICTED`); a `SUSPENDED` plant refuses it with `ERR_PLANT_SUSPENDED`, and any other run state returns `ERR_COOK_RUN_INVALID_STATE`. At start the server re-verifies that every planned input batch still has sufficient `remaining_lbs` for its planned weight (`ERR_WEIGHT_EXCEEDS_REMAINING`). From `COOKING` the run advances to `SETTLING`, and from `SETTLING` to `PRESSING`; each advance from the wrong state returns `ERR_COOK_RUN_INVALID_STATE`.

Completion, from `PRESSING` only (`ERR_COOK_RUN_INVALID_STATE`), is where theory meets the scale. The supervisor records the measured `actual_fat_output_lbs` and `actual_meal_output_lbs`. The server finalizes `yield_variance_pct`: the sum of the two actual outputs minus the sum of the two theoretical yields, divided by that theoretical total, multiplied by one hundred, and rounded half-up to two decimal places. When the absolute variance exceeds 25 percent, completion is refused with `ERR_YIELD_OUT_OF_TOLERANCE` unless the supervisor supplies an `override_note`, which is the deliberate human-override channel for unusual but legitimate cooks.

Completion prices the run's energy with a marginal two-tier tariff. The run's duration is its whole-hour window length. The plant's banked hours are the sum of durations of this plant's cook runs that completed earlier in the current period, with completions at the same instant ordered by `updated_at` ascending. Of this run's hours, the portion billed at the first-tier rate is the larger of zero and the smaller of the run's duration and the gap remaining between the banked hours and the 500-hour tier boundary; the remainder bills at the second-tier rate. The first tier costs 4200 cents per hour and the second 3800 cents per hour, so `energy_cost_cents` is the first-tier hours times 4200 plus the second-tier hours times 3800. This cost accrues into the current period settlement's `energy_costs_cents`.

Completion also settles mass and creates product. For each input batch, `reserved_lbs` decreases by the planned weight and `consumed_lbs` increases by the same amount; a batch whose `remaining_lbs` reaches 0 with positive consumption becomes `DEPLETED`. Two product lots are created per run, both `LAB_PENDING` with `grade` `UNGRADED`, their `plant_id` denormalized from the run and their `cook_run_id` pointing back to it: a `RUMINANT_RENDER`, `PORCINE_RENDER`, or `MIXED_RENDER` run produces a `TALLOW` lot with `quantity_lbs` equal to `actual_fat_output_lbs` and a `PROTEIN_MEAL` lot with `quantity_lbs` equal to `actual_meal_output_lbs`; a `POULTRY_RENDER` run instead produces a `YELLOW_GREASE` lot from the fat output and a `FEATHER_MEAL` lot from the meal output.

Failure and recook are first-class. A run in `COOKING` or `SETTLING` may be failed (from any other state: `ERR_COOK_RUN_INVALID_STATE`), recording the supplied `failure_reason`; batch reservations are retained so the material can be cooked again. A `FAILED` run may be restaged to `STAGED`, which increments `recook_count` by one, clears `failure_reason`, and again retains the reservations. Cancellation is permitted from `STAGED` or `FAILED` (else `ERR_COOK_RUN_INVALID_STATE`) and releases each input batch's reservation exactly — `reserved_lbs` down, `remaining_lbs` up by the planned weight — so that a stage followed by a cancel returns every batch's `remaining_lbs` to its pre-stage value.

### 3.7. Product Lots and Laboratory Grading

A product lot is the saleable unit of rendered output. Beyond the fields stamped at creation (§3.6), a lot tracks `available_lbs` — always `quantity_lbs` minus `allocated_lbs` — with `allocated_lbs` starting at zero, and its laboratory fields `lab_moisture_pct`, `lab_ffa_pct`, and `lab_protein_pct` remain null until grading.

A `QualityLabTech` grades a `LAB_PENDING` lot (any other state: `ERR_LOT_INVALID_STATE`) by submitting the lab values, each to one decimal place; the server computes the `grade` and records `graded_by`. Fats — `TALLOW` and `YELLOW_GREASE` — are judged on `lab_moisture_pct` and `lab_ffa_pct`: `PREMIUM` when moisture is at most 0.3 and FFA at most 2.0; otherwise `STANDARD` when moisture is at most 0.5 and FFA at most 4.0; otherwise `FEED_GRADE` when moisture is at most 1.0 and FFA at most 8.0; otherwise `OFF_SPEC`. Meals — `PROTEIN_MEAL` and `FEATHER_MEAL` — are judged on `lab_protein_pct` and `lab_moisture_pct`: `PREMIUM` when protein is at least 65 and moisture at most 8; otherwise `STANDARD` when protein is at least 60 and moisture at most 10; otherwise `FEED_GRADE` when protein is at least 55 and moisture at most 12; otherwise `OFF_SPEC`. All boundary comparisons are inclusive, exactly as written. A lot that computes to `OFF_SPEC` does not stop at `GRADED`: it moves directly to `REJECTED`, which is terminal.

A `GRADED` lot is released for sale by a `ProductionSupervisor` — never by the technician who graded it (`ERR_SOD_VIOLATION`); the lot must be `GRADED` and its grade must not be `OFF_SPEC` (both violations surface as `ERR_LOT_INVALID_STATE`). Release moves it to `RELEASED`, the only state from which sales orders may draw.

Quality work continues after release. A lab tech may downgrade a lot from `GRADED` or from `RELEASED` — the latter only while its `allocated_lbs` is zero, because product already committed to an order cannot be pulled back (both violations: `ERR_LOT_INVALID_STATE`) — moving it to `DOWNGRADED`. A `DOWNGRADED` lot may be regraded with fresh lab values; the grade is recomputed by the same tables, an `OFF_SPEC` outcome moves it directly to `REJECTED`, and otherwise it returns to `GRADED` (and would need a fresh release to be sold). A lot may also be rejected outright from `GRADED` or `DOWNGRADED`; `REJECTED` is terminal. Finally, when a shipment draws a `RELEASED` lot down so that both `available_lbs` and `allocated_lbs` reach zero, the lot automatically becomes `DEPLETED`, which is terminal.

### 3.8. Customer Contracts, Index Pricing, and Order Fulfilment

Sales begin with a customer contract drafted by a `SalesManager`. The payload names the `plant_id` and `customer_name`, the contracted `product_type` (`TALLOW`, `YELLOW_GREASE`, `PROTEIN_MEAL`, or `FEATHER_MEAL`), and the specification the customer will accept: `spec_max_moisture_pct`, `spec_max_ffa_pct` for fats, and `spec_min_protein_pct` for meals (0 for fats). Pricing comes in two modes selected by `pricing_mode`. A `FIXED` contract must declare its `base_price_cents_per_lb`; an `INDEX_LINKED` contract instead declares an `index_product` of `TALLOW` or `MEAL` and a signed `index_basis_adjustment_cents` that may be negative. Supplying a `FIXED` contract without a base price, or an `INDEX_LINKED` contract without its index fields, is a schema violation rejected with `ERR_INVALID_REQUEST`; the base price is ignored on index-linked contracts. The contract may also carry a `volume_commitment_lbs` (informational), a `tier_discounts` list whose entries each pair a `threshold_lbs` with a `discount_pct` sorted ascending by threshold (an empty list is allowed), and a `margin_floor_pct` such as 15.0. Its window spans `effective_from` through `effective_to`, inclusive, with `effective_to` no earlier than `effective_from`. A new contract is `DRAFT` with `delivered_volume_lbs` zero and the caller recorded as `created_by`.

The contract lifecycle mirrors the agreement lifecycle: `DRAFT` → `SUBMITTED` → `ACTIVE`, with submission by the `SalesManager` and approval by a `PlantManager` who must differ from `created_by` (`ERR_SOD_VIOLATION`); a `SUBMITTED` contract may be returned to `DRAFT`. A `SalesManager` may suspend an `ACTIVE` contract and later reinstate a `SUSPENDED` one; out-of-state transitions return `ERR_CONTRACT_INVALID_STATE`. Termination is available from `DRAFT`, `SUBMITTED`, `ACTIVE`, or `SUSPENDED` and is terminal; terminating from `ACTIVE` or `SUSPENDED` additionally cancels every order of the contract still in `DRAFT` or `PRICED`, while terminating a never-activated contract has no orders to cancel.

Index-linked pricing depends on the plant's price index feed, which a `FinanceAnalyst` publishes as append-only entries. Each entry carries its `plant_id`, an `index_product` of `TALLOW` or `MEAL`, the `effective_date` from which the quote applies, a `price_cents_per_lb` of at least 1, and a `source` of `USDA_AMS`, `JACOBSEN`, or `INTERNAL`; the publisher is recorded as `published_by`. Entries are unique per plant, product, and effective date — a duplicate returns `ERR_DUPLICATE_INDEX_ENTRY` — and, being append-only records, they carry no `updated_at` or `version` (§2.4).

A `SalesManager` creates an order against a contract by supplying the `contract_id`, a `plant_id` equal to the contract's plant, a `quantity_lbs` of at least 1, a `requested_ship_date` that must lie within the contract's effective window (`ERR_CONTRACT_NOT_IN_EFFECT`), and the `expected_contract_version` guard of §2.8; the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`). A new order is `DRAFT`, and its creation increments the contract's `version` by one. Until priced, the order's `unit_price_cents`, `applied_index_price_cents`, `applied_discount_pct`, `gross_amount_cents`, `discount_amount_cents`, `freight_surcharge_cents`, `net_amount_cents`, and `margin_pct` are all null.

Pricing is a single act with a pinned evaluation order, triggered by the sales manager supplying an `expected_grade` of `PREMIUM`, `STANDARD`, or `FEED_GRADE`. First the base price: on a `FIXED` contract the base is `base_price_cents_per_lb` and `applied_index_price_cents` stays null; on an `INDEX_LINKED` contract the server selects the plant's index entry whose `index_product` matches the contract's and whose `effective_date` is on or before the order's `requested_ship_date`, choosing the latest such date — ties cannot exist because entries are unique per plant, product, and date — and when no such entry exists pricing fails with `ERR_NO_INDEX_FOR_DATE`. The index-linked base is the entry's `price_cents_per_lb` plus the contract's `index_basis_adjustment_cents`, and `applied_index_price_cents` records the entry's price. The unit price applies a grade multiplier to the base — 1.05 for `PREMIUM`, 1.00 for `STANDARD`, 0.85 for `FEED_GRADE` — rounded half-up to whole cents in exactly one rounding step, producing `unit_price_cents`.

The order's amounts then compose in a fixed sequence, with rounding per component and never on the total. `gross_amount_cents` is the order's `quantity_lbs` times the already-rounded `unit_price_cents` — an exact integer, never the rounding of a quantity-times-unrounded-price product. The tier discount is selected on projected volume: the contract's `delivered_volume_lbs` plus this order's own `quantity_lbs`, so an order contributes to its own tier evaluation while orders not yet shipped do not; scanning `tier_discounts` in ascending order, the selected tier is the last one whose `threshold_lbs` the projected volume reaches or exceeds, and when no tier qualifies the discount fraction is zero. That fraction becomes `applied_discount_pct`, and `discount_amount_cents` is the gross times that fraction, rounded half-up to whole cents. A flat freight surcharge of 12500 cents per order is then added as `freight_surcharge_cents`, and `net_amount_cents` is the gross minus the discount plus the freight. Finally `margin_pct` is one hundred times the amount by which `unit_price_cents` exceeds the plant's `standard_cost_cents_per_lb`, divided by `unit_price_cents`, rounded half-up to two decimal places. Because `delivered_volume_lbs` only advances at shipment, re-pricing an order after another order has shipped can legitimately select a different tier for the same quantity. Successful pricing moves the order from `DRAFT` to `PRICED`; a non-`DRAFT` order returns `ERR_ORDER_INVALID_STATE`, the contract must still be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), and the `requested_ship_date` must still lie within the contract's effective window (`ERR_CONTRACT_NOT_IN_EFFECT`).

Confirmation commits inventory. The sales manager confirms a `PRICED` order (`ERR_ORDER_INVALID_STATE` otherwise, `ERR_CONTRACT_NOT_ACTIVE` if the contract has left `ACTIVE`) with an `allocations` list whose entries each pair a `lot_id` with a `quantity_lbs`. Specification safety is checked before any fiscal concern: every allocated lot must be `RELEASED`, its `product_type` must equal the contract's, its `lab_moisture_pct` must not exceed `spec_max_moisture_pct`, a fat lot's `lab_ffa_pct` must not exceed `spec_max_ffa_pct`, a meal lot's `lab_protein_pct` must be at least `spec_min_protein_pct`, and its grade must not be `OFF_SPEC` — any failure returns `ERR_SPEC_BELOW_CONTRACT_MIN`. Then, in this order: the allocations must sum exactly to the order's `quantity_lbs` (`ERR_ALLOCATION_MISMATCH`), and only afterward is each lot's `available_lbs` checked for sufficiency (`ERR_INSUFFICIENT_LOT_QUANTITY`). Finally the fiscal gate: the order's `margin_pct` must be at least the contract's `margin_floor_pct`, else `ERR_MARGIN_FLOOR_BREACH` (HTTP 402). A confirmed order records its `allocations` and increases each allocated lot's `allocated_lbs` by its allocated quantity, decreasing `available_lbs` accordingly; the order is now `CONFIRMED`.

Deallocation unwinds confirmation exactly: a `CONFIRMED` order returns to `PRICED`, each lot's `allocated_lbs` decreases by its allocated quantity, and the order's `allocations` are cleared. Cancellation is available from `DRAFT`, `PRICED`, or `CONFIRMED` (else `ERR_ORDER_INVALID_STATE`); cancelling a `CONFIRMED` order releases its allocations the same way.

Shipment is the dispatcher's act. Shipping a `CONFIRMED` order (`ERR_ORDER_INVALID_STATE` otherwise) requires a plant posture of `OPERATING` or `RESTRICTED` — a `SUSPENDED` plant returns `ERR_PLANT_SUSPENDED` — and a nominated `vehicle_id` whose `sanitation_status` is `SANITIZED` (`ERR_VEHICLE_NOT_SANITIZED`) and whose `duty_class` is `FINISHED_PRODUCT` or `DUAL` (`ERR_VEHICLE_DUTY_MISMATCH`). Shipping records `shipped_vehicle_id` (null until this moment), turns the vehicle `DIRTY` with one more completed trip, decrements each allocated lot's `allocated_lbs` by its shipped quantity (a lot left with `available_lbs` and `allocated_lbs` both zero becomes `DEPLETED`), adds the order's `quantity_lbs` to the contract's `delivered_volume_lbs`, and moves the order to `SHIPPED`.

Invoicing closes the revenue loop. A `FinanceAnalyst` invoices a `SHIPPED` order (`ERR_ORDER_INVALID_STATE` otherwise) while the current period settlement is `OPEN` or `REOPENED` (`ERR_PERIOD_CLOSED`); the settlement's `product_revenue_cents` increases by the order's `net_amount_cents`, and the order becomes `INVOICED`, its terminal state.

### 3.9. Period Close, Margin Accounting, and Calendar Advancement

The period settlement is where the plant's period economics are frozen and reviewed. A settlement is born `OPEN` — at plant creation for period 1, and at each calendar advancement for the next period — and accumulates pickup fees at stop collection, transport costs at 150 cents per actual mile, energy costs at cook-run completion, product revenue at invoicing, and the count of confirmed odor events, as narrated in §3.4, §3.6, §3.8, and §3.2 respectively.

A `FinanceAnalyst` closes a settlement from `OPEN` or `REOPENED` (any other state: `ERR_SETTLEMENT_INVALID_STATE`), recording `closed_by` and moving it to `CLOSED`. Closing is not irreversible: a `PlantManager` may reopen a `CLOSED` settlement, but only the settlement of the plant's current period — its `period_index` must equal the plant's `current_period_index`, otherwise `ERR_SETTLEMENT_INVALID_STATE`; reopening clears `closed_by` and returns the settlement to `REOPENED`, from which it can be closed again under the same rule. Finalization is the terminal act: a `PlantManager` finalizes a `CLOSED` settlement, and the finalizer must differ from the recorded `closed_by` (`ERR_SOD_VIOLATION`). `FINALIZED` is terminal.

Advancing the settlement calendar is the plant's operational checkpoint, performed by a `FinanceAnalyst`, and it is gated: the settlement of the current period must be `CLOSED`, or advancement is rejected with `ERR_SETTLEMENT_NOT_CLOSED`. Advancement increments the plant's `current_period_index` by one, creates a fresh `OPEN` settlement for the new period with all accumulators at zero, and resets the plant's `ACTIVE` permit's `confirmed_violation_count` to zero. Odor recovery then applies: if the just-closed settlement recorded zero `confirmed_odor_events`, the plant's `odor_score` increases by 50, never exceeding the 1000 cap; after recovery, a `RESTRICTED` plant whose score has reached at least 700 returns to `OPERATING`, provided its `ACTIVE` permit, if any, is not `SUSPENDED`, `REVOKED`, or `EXPIRED`. Advancement is also when permit expiry is processed: any `ACTIVE` permit whose `expires_on` is now earlier than the current logical date becomes `EXPIRED`, dropping the plant to `SUSPENDED` with the route, stop, batch, and fee cascade of §2.7.

Two cross-period disciplines deserve emphasis. Accruals and reversals always target the settlement whose `period_index` equals the plant's `current_period_index`, so collecting, voiding, or invoicing against a settlement that is not `OPEN` or `REOPENED` fails with `ERR_PERIOD_CLOSED` — and voiding a stop that was collected in an earlier, already-advanced period fails the same way, because its settlement can no longer accept reversals. And because a stop collected and then voided within the same period must restore `pickup_fees_accrued_cents`, `transport_costs_cents`, and the supplier's `outstanding_service_fees_cents` to exactly their pre-collection values, the fee arithmetic of §3.4 is specified to the cent.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. One operational action — recording a stop collection — returns `201 Created` because it creates the corresponding inbound batch as part of the same atomic request. All request and response bodies conform to §2.2, and every endpoint enforces the validation precedence of §2.9.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlantManager |
| POST | `/rendering/plants` | Create a rendering plant; opens settlement period 1 | PlantManager |
| GET | `/rendering/plants` | List plants | Any |
| GET | `/rendering/plants/{id}` | Get one plant | Any |
| POST | `/rendering/plants/{id}/decommission` | Decommission a plant (terminal) | PlantManager |
| POST | `/rendering/plants/{id}/advance-period` | Advance to the next settlement period | FinanceAnalyst |
| POST | `/rendering/permits` | Create a compliance permit | ComplianceOfficer |
| GET | `/rendering/permits` | List permits | Any |
| GET | `/rendering/permits/{id}` | Get one permit | Any |
| POST | `/rendering/permits/{id}/submit` | Submit a permit for issuance | ComplianceOfficer |
| POST | `/rendering/permits/{id}/issue` | Issue a permit | Regulator |
| POST | `/rendering/permits/{id}/suspend` | Suspend a permit | Regulator |
| POST | `/rendering/permits/{id}/reinstate` | Reinstate a suspended permit | Regulator |
| POST | `/rendering/permits/{id}/revoke` | Revoke a permit | Regulator |
| POST | `/rendering/odor-events` | Log an odor complaint | ComplianceOfficer |
| GET | `/rendering/odor-events` | List odor events | Any |
| GET | `/rendering/odor-events/{id}` | Get one odor event | Any |
| POST | `/rendering/odor-events/{id}/confirm` | Confirm a reported odor event | ComplianceOfficer |
| POST | `/rendering/odor-events/{id}/dismiss` | Dismiss a reported odor event | ComplianceOfficer |
| POST | `/rendering/suppliers` | Onboard a supplier | ProcurementManager |
| GET | `/rendering/suppliers` | List suppliers | Any |
| GET | `/rendering/suppliers/{id}` | Get one supplier | Any |
| POST | `/rendering/suppliers/{id}/reinstate` | Reinstate a suspended supplier | ProcurementManager |
| POST | `/rendering/suppliers/{id}/terminate` | Terminate a supplier | ProcurementManager |
| POST | `/rendering/supplier-agreements` | Create a supplier agreement | ProcurementManager |
| GET | `/rendering/supplier-agreements` | List supplier agreements | Any |
| GET | `/rendering/supplier-agreements/{id}` | Get one supplier agreement | Any |
| POST | `/rendering/supplier-agreements/{id}/submit` | Submit an agreement for approval | ProcurementManager |
| POST | `/rendering/supplier-agreements/{id}/approve` | Approve a submitted agreement | PlantManager |
| POST | `/rendering/supplier-agreements/{id}/return-to-draft` | Return an agreement to draft | PlantManager |
| POST | `/rendering/supplier-agreements/{id}/suspend` | Suspend an active agreement | PlantManager |
| POST | `/rendering/supplier-agreements/{id}/reinstate` | Reinstate a suspended agreement | PlantManager |
| POST | `/rendering/supplier-agreements/{id}/terminate` | Terminate an agreement | PlantManager |
| POST | `/rendering/supplier-agreements/{id}/amend` | Amend an active agreement's commercial terms | ProcurementManager |
| POST | `/rendering/vehicles` | Register a vehicle | RouteDispatcher |
| GET | `/rendering/vehicles` | List vehicles | Any |
| GET | `/rendering/vehicles/{id}` | Get one vehicle | Any |
| POST | `/rendering/vehicles/{id}/wash-tickets` | Record a wash ticket | RouteDispatcher |
| GET | `/rendering/wash-tickets` | List wash tickets | Any |
| GET | `/rendering/wash-tickets/{id}` | Get one wash ticket | Any |
| POST | `/rendering/vehicles/{id}/quarantine` | Quarantine a vehicle | ComplianceOfficer |
| POST | `/rendering/collection-routes` | Create a collection route | RouteDispatcher |
| GET | `/rendering/collection-routes` | List collection routes | Any |
| GET | `/rendering/collection-routes/{id}` | Get one collection route | Any |
| POST | `/rendering/collection-routes/{id}/dispatch` | Dispatch a planned route | RouteDispatcher |
| POST | `/rendering/collection-routes/{id}/complete` | Complete a dispatched route | RouteDispatcher |
| POST | `/rendering/collection-routes/{id}/cancel` | Cancel a non-terminal route | RouteDispatcher |
| POST | `/rendering/route-stops` | Add a stop to a planned route | RouteDispatcher |
| GET | `/rendering/route-stops` | List route stops | Any |
| GET | `/rendering/route-stops/{id}` | Get one route stop | Any |
| POST | `/rendering/route-stops/{id}/arrive` | Mark a stop arrived | RouteDispatcher |
| POST | `/rendering/route-stops/{id}/collect` | Record a stop collection (creates the inbound batch) | RouteDispatcher |
| POST | `/rendering/route-stops/{id}/reject-at-site` | Reject a stop at the supplier site | RouteDispatcher |
| POST | `/rendering/route-stops/{id}/miss` | Mark a stop missed | RouteDispatcher |
| POST | `/rendering/route-stops/{id}/deliver` | Mark a collected stop delivered | RouteDispatcher |
| POST | `/rendering/route-stops/{id}/void` | Void a collected or delivered stop | RouteDispatcher |
| POST | `/rendering/inbound-batches` | Receive a walk-in inbound batch | ScalehouseOperator |
| GET | `/rendering/inbound-batches` | List inbound batches | Any |
| GET | `/rendering/inbound-batches/{id}` | Get one inbound batch | Any |
| POST | `/rendering/inbound-batches/{id}/screen` | Screen a received batch | ScalehouseOperator |
| POST | `/rendering/inbound-batches/{id}/quarantine` | Place a batch under compliance hold | ComplianceOfficer |
| POST | `/rendering/inbound-batches/{id}/adjudicate` | Adjudicate a quarantined batch | ComplianceOfficer |
| POST | `/rendering/cook-runs` | Stage a cook run | ProductionSupervisor |
| GET | `/rendering/cook-runs` | List cook runs | Any |
| GET | `/rendering/cook-runs/{id}` | Get one cook run | Any |
| POST | `/rendering/cook-runs/{id}/start` | Start cooking a staged run | ProductionSupervisor |
| POST | `/rendering/cook-runs/{id}/advance` | Advance the run one cook stage | ProductionSupervisor |
| POST | `/rendering/cook-runs/{id}/fail` | Fail a run in progress | ProductionSupervisor |
| POST | `/rendering/cook-runs/{id}/restage` | Restage a failed run for recook | ProductionSupervisor |
| POST | `/rendering/cook-runs/{id}/complete` | Complete a pressing run with measured outputs | ProductionSupervisor |
| POST | `/rendering/cook-runs/{id}/cancel` | Cancel a staged or failed run | ProductionSupervisor |
| GET | `/rendering/product-lots` | List product lots | Any |
| GET | `/rendering/product-lots/{id}` | Get one product lot | Any |
| POST | `/rendering/product-lots/{id}/grade` | Grade a lot from laboratory results | QualityLabTech |
| POST | `/rendering/product-lots/{id}/release` | Release a graded lot for sale | ProductionSupervisor |
| POST | `/rendering/product-lots/{id}/downgrade` | Downgrade a lot after a spot check | QualityLabTech |
| POST | `/rendering/product-lots/{id}/regrade` | Re-grade a downgraded lot | QualityLabTech |
| POST | `/rendering/product-lots/{id}/reject` | Reject a lot (terminal) | QualityLabTech |
| POST | `/rendering/customer-contracts` | Create a customer contract | SalesManager |
| GET | `/rendering/customer-contracts` | List customer contracts | Any |
| GET | `/rendering/customer-contracts/{id}` | Get one customer contract | Any |
| POST | `/rendering/customer-contracts/{id}/submit` | Submit a contract for approval | SalesManager |
| POST | `/rendering/customer-contracts/{id}/approve` | Approve a submitted contract | PlantManager |
| POST | `/rendering/customer-contracts/{id}/return-to-draft` | Return a contract to draft | PlantManager |
| POST | `/rendering/customer-contracts/{id}/suspend` | Suspend an active contract | SalesManager |
| POST | `/rendering/customer-contracts/{id}/reinstate` | Reinstate a suspended contract | SalesManager |
| POST | `/rendering/customer-contracts/{id}/terminate` | Terminate a contract | SalesManager |
| POST | `/rendering/sales-orders` | Create a sales order | SalesManager |
| GET | `/rendering/sales-orders` | List sales orders | Any |
| GET | `/rendering/sales-orders/{id}` | Get one sales order | Any |
| POST | `/rendering/sales-orders/{id}/price` | Price a draft order | SalesManager |
| POST | `/rendering/sales-orders/{id}/confirm` | Confirm a priced order with lot allocations | SalesManager |
| POST | `/rendering/sales-orders/{id}/deallocate` | Release a confirmed order's allocations | SalesManager |
| POST | `/rendering/sales-orders/{id}/ship` | Ship a confirmed order | RouteDispatcher |
| POST | `/rendering/sales-orders/{id}/invoice` | Invoice a shipped order | FinanceAnalyst |
| POST | `/rendering/sales-orders/{id}/cancel` | Cancel an order | SalesManager |
| POST | `/rendering/price-index-entries` | Publish a price index entry | FinanceAnalyst |
| GET | `/rendering/price-index-entries` | List price index entries | Any |
| GET | `/rendering/price-index-entries/{id}` | Get one price index entry | Any |
| GET | `/rendering/period-settlements` | List period settlements | Any |
| GET | `/rendering/period-settlements/{id}` | Get one period settlement | Any |
| POST | `/rendering/period-settlements/{id}/close` | Close a settlement | FinanceAnalyst |
| POST | `/rendering/period-settlements/{id}/reopen` | Reopen the current period's settlement | PlantManager |
| POST | `/rendering/period-settlements/{id}/finalize` | Finalize a closed settlement (terminal) | PlantManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_PLANT_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_WASH_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_STOP_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_COOK_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INDEX_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ODOR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLANT_SUSPENDED` | 409 Conflict |
| `ERR_PLANT_RESTRICTED` | 409 Conflict |
| `ERR_PLANT_DECOMMISSIONED` | 409 Conflict |
| `ERR_PERMIT_INVALID_STATE` | 409 Conflict |
| `ERR_SUPPLIER_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_VEHICLE_INVALID_STATE` | 409 Conflict |
| `ERR_ROUTE_INVALID_STATE` | 409 Conflict |
| `ERR_STOP_INVALID_STATE` | 409 Conflict |
| `ERR_BATCH_INVALID_STATE` | 409 Conflict |
| `ERR_COOK_RUN_INVALID_STATE` | 409 Conflict |
| `ERR_LOT_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRACT_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_SETTLEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ODOR_EVENT_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_SUPPLIER_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_BATCH_NOT_ACCEPTED` | 409 Conflict |
| `ERR_VEHICLE_NOT_SANITIZED` | 409 Conflict |
| `ERR_VEHICLE_DUTY_MISMATCH` | 409 Conflict |
| `ERR_DEEP_WASH_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SPECIES_MIXING_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SPECIES_OUT_OF_SCOPE` | 422 Unprocessable Entity |
| `ERR_DEAD_STOCK_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_SPEC_BELOW_CONTRACT_MIN` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_PERMIT` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_INDEX_ENTRY` | 409 Conflict |
| `ERR_VEHICLE_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_COOKER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ROUTE_OVER_CAPACITY` | 422 Unprocessable Entity |
| `ERR_WEIGHT_EXCEEDS_REMAINING` | 422 Unprocessable Entity |
| `ERR_EMPTY_INPUT` | 422 Unprocessable Entity |
| `ERR_ROUTE_EMPTY` | 422 Unprocessable Entity |
| `ERR_ROUTE_HAS_COLLECTED_STOPS` | 409 Conflict |
| `ERR_ALLOCATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STOP_SEQUENCE` | 422 Unprocessable Entity |
| `ERR_YIELD_OUT_OF_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_WINDOW_OUTSIDE_ROUTE` | 422 Unprocessable Entity |
| `ERR_ROUTE_WINDOW_PASSED` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_NOT_IN_EFFECT` | 422 Unprocessable Entity |
| `ERR_CONTRACT_NOT_IN_EFFECT` | 422 Unprocessable Entity |
| `ERR_NO_INDEX_FOR_DATE` | 422 Unprocessable Entity |
| `ERR_MARGIN_FLOOR_BREACH` | 402 Payment Required |
| `ERR_PERIOD_CLOSED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

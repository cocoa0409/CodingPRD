# Emergency Food Assistance Allocation API — Product Requirements Document

## 1. Introduction

State distributing agencies that operate the Emergency Food Assistance Program sit between two very different worlds. Upstream, the federal government ships commodity entitlements into state warehouses in whole truckloads, charges the state a fixed entitlement value per case, and expects every pound to be accounted for. Downstream, several hundred food banks and pantries — each with its own agreement paperwork, its own civil rights training calendar, and its own walk-in freezer — draw against a case pool that is never large enough. Between the two sits an allocation formula that must be defensible in an audit, a dock calendar that must not double-book a receiving bay, and a recall process that must reach every household-serving agency that touched a suspect lot.

This API is the system of record for that middle layer. It governs the full arc of a program period: recording a federal entitlement receipt into a warehouse, deciding how many cases each eligible agency is entitled to, opening and closing the order window, reviewing and approving what agencies ask for, reserving physical lots on a first-expired-first-out basis, booking dock appointments that respect both warehouse staging capacity and the receiving agency's cold storage ceiling, monitoring what is sitting too long and transferring it before it spoils, executing recalls across downstream agencies, capturing household self-declarations, and finally reconciling the administrative funds pool against how much each agency actually distributed.

Two design commitments run through every section that follows. First, cases are physical: the system treats the total number of cases in the program as a conserved quantity, and every commitment has an exact compensating release, so a cancelled order leaves no residue in any counter. Second, eligibility is never a single flag: an agency's agreement paperwork and its civil rights training expire on independent schedules, and the program posture that gates ordering is derived from both. All business paths in this document are mounted under `/efap`.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across the entire API: authentication, response shape, pagination, the logical clock, identity and versioning, precision, concurrency, the case ledger, and the order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is the logical-clock read described in §2.4, which may be called without headers. If `X-User-Role` carries a value that is not one of the four recognised roles, or names a role that the addressed operation does not authorise, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `StateAdmin`, `ComplianceReviewer`, `AgencyCoordinator`, and `StateWarehouseOperator`, spelled exactly as shown.

A `StateAdmin` is state distributing agency staff. They register program configuration — service areas, agencies, commodities, warehouses — record federal entitlement receipts, drive the allocation cycle and its two operational checkpoint runs, propose inventory transfers, and execute recalls. A `StateAdmin` cannot approve an order, cannot approve or renew an agency agreement, cannot record a civil rights training, and cannot close a recall they themselves raised.

A `ComplianceReviewer` is state compliance staff. They own the agency eligibility paperwork — agreement approval and renewal, civil rights training records — and the order review gate, meaning both returning an order for revision and approving it. A `ComplianceReviewer` cannot create program configuration, cannot run any operational checkpoint, and cannot schedule or confirm deliveries. A reviewer who returned an order for revision may not approve that order after it is resubmitted.

An `AgencyCoordinator` is staff at an emergency feeding organization. They start and submit orders, add lines, accept or decline inventory transfers offered to their agency, acknowledge and disposition recall actions addressed to their agency, and record and void household distributions. An `AgencyCoordinator` cannot approve their own order, cannot post an inventory lot, cannot book or confirm a dock appointment, and cannot touch another agency's rows.

A `StateWarehouseOperator` is warehouse dock staff. They confirm delivery at their own dock, and they share the appointment-booking capability with `StateAdmin`. A `StateWarehouseOperator` cannot cancel an appointment (that is reserved to `StateAdmin`), cannot approve orders, cannot run the inventory monitor, and cannot confirm a delivery at another warehouse.

Two of the four roles are backed by a persisted entity, and two are not:

- When `X-User-Role` is `AgencyCoordinator`, `X-User-ID` is the `id` of the acting `Agency`; ownership checks on any resource that references an `Agency` compare the resource's foreign-key field to `X-User-ID`. Concretely, a coordinator's writes are refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) unless `X-User-ID` equals the `agency_id` of the order being created, lined, submitted or cancelled, the `to_agency_id` of the transfer being accepted or declined, the `agency_id` of the recall action being acknowledged or dispositioned, and the `agency_id` of the household distribution being recorded or voided.
- When `X-User-Role` is `StateWarehouseOperator`, `X-User-ID` is the `id` of the acting `Warehouse`; ownership checks on any resource that references a `Warehouse` compare the resource's foreign-key field to `X-User-ID`. Concretely, confirming a delivery is refused with `ERR_NOT_RESOURCE_OWNER` unless `X-User-ID` equals the addressed appointment's `warehouse_id`.
- When `X-User-Role` is `StateAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `initiated_by_user_id` on a `Recall` — but never compares it to any entity's `id`.
- When `X-User-Role` is `ComplianceReviewer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server records it as `last_returned_by_user_id` and `approved_by_user_id` on a `CommodityOrder`, but never compares it to any entity's `id`.

Both opaque identifiers are nonetheless compared against each other across time, which is what makes segregation of duties work: the recorded `last_returned_by_user_id` is compared with the `X-User-ID` presented at approval, and the recorded `initiated_by_user_id` is compared with the `X-User-ID` presented at recall closure. A match in either comparison yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of rows returned; it defaults to 10 when omitted, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of rows to skip and defaults to 0; negative values are not accepted. A `limit` outside the range of 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination and `has_more` indicates whether rows remain beyond the current page.

### 2.4. The Logical Program Clock

Every deadline in this system — agreement expiry, training expiry, order-window boundaries, dock windows, lot age — is evaluated against a server-side logical clock rather than wall-clock time. The clock starts at the fixed instant `2026-08-01T00:00:00Z` and must never fall back to wall-clock time, even before any client has moved it. A `StateAdmin` may advance or rewind it by supplying a `current_utc` instant to the clock-setting capability, which performs no entity writes and simply changes what every later read of the current instant returns. Any caller may read the clock back, and that read is the one operation in the API that does not require authentication headers; it answers with the same `current_utc` field.

Whenever this document says "the current instant", it means the value of that logical clock at the moment the request is processed.

### 2.5. Resource Identity, Timestamps and Versioning

Every stored resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits (for example `2026-08-01T00:00:00.000Z`).

Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation, and `version`, an integer that increments by one on every mutation. Writing a derived field counts as a mutation: when a household distribution changes an agency allocation's `distributed_pounds`, or a monitor run changes a lot's `slow_moving_index`, that row's `updated_at` is refreshed and its `version` is incremented exactly as if a client had edited it directly. `ServiceArea`, `Agency`, `Warehouse`, `InventoryLot`, `AllocationCycle`, `AgencyAllocation`, `CommodityOrder`, `OrderLine`, `DeliveryAppointment`, `InventoryTransfer`, `Recall`, `RecallAction`, and `HouseholdDistribution` all behave this way.

`Commodity` is the single exception. A commodity is immutable configuration once created, so it carries only `id` and `created_at`: both `updated_at` and `version` are absent from a commodity representation entirely.

### 2.6. Identifier Resolution Order

Requests that address a resource through a path identifier are resolved strictly left to right, and the first identifier that fails to resolve decides the response. For a path such as `/efap/agencies/{agency_id}/agreement-renewals`, the agency is resolved before the request body is inspected at all; an unknown `agency_id` yields `ERR_AGENCY_NOT_FOUND` (HTTP 404) regardless of whatever else is wrong with the payload. The same discipline governs every other identifier, and each maps to its own dedicated not-found code, all of them HTTP 404: `service_area_id` to `ERR_SERVICE_AREA_NOT_FOUND`, `commodity_id` to `ERR_COMMODITY_NOT_FOUND`, `warehouse_id` to `ERR_WAREHOUSE_NOT_FOUND`, `inventory_lot_id` to `ERR_INVENTORY_LOT_NOT_FOUND`, `cycle_id` to `ERR_CYCLE_NOT_FOUND`, `agency_allocation_id` to `ERR_ALLOCATION_NOT_FOUND`, `order_id` to `ERR_ORDER_NOT_FOUND`, `order_line_id` to `ERR_ORDER_LINE_NOT_FOUND`, `appointment_id` to `ERR_APPOINTMENT_NOT_FOUND`, `transfer_id` to `ERR_TRANSFER_NOT_FOUND`, `recall_id` to `ERR_RECALL_NOT_FOUND`, `recall_action_id` to `ERR_RECALL_ACTION_NOT_FOUND`, and `distribution_id` to `ERR_DISTRIBUTION_NOT_FOUND`.

Only after every path identifier resolves does the server inspect the body. Foreign keys supplied in a body — `service_area_id`, `agency_id`, `cycle_id`, `commodity_id`, `warehouse_id`, `from_lot_id`, `source_lot_id`, `to_agency_id`, `order_id` — are then resolved, again yielding the not-found code matching the entity that could not be found. Body-level foreign-key resolution happens *after* payload well-formedness is checked, which is why a request that both omits a required field and names a nonexistent agency answers `ERR_INVALID_REQUEST` rather than `ERR_AGENCY_NOT_FOUND`. The full ordering is spelled out in §2.10.

### 2.7. Numeric Precision and Remainder Reconciliation

All rounding in this system is round-half-up, and the number of decimal places is fixed per quantity rather than chosen by the implementation:

- Pound quantities — `line_pounds`, `total_pounds`, `delivered_pounds`, `pounds_distributed`, `distributed_pounds`, and the `prior_period_pounds_distributed` baseline — carry two decimal places.
- `poverty_factor`, `slow_moving_index`, and `record_compliance_pct` carry four decimal places.
- `poverty_share`, `prior_share`, and `raw_score` carry six decimal places.
- `net_weight_lbs_per_case` is supplied with three decimal places and stored at that precision; because per-case weights are that fine, the order in which the system rounds and sums is observable, and §3.6 pins it.
- Cases, pallets, cents, and counts are integers throughout. No monetary or case quantity is ever stored as a fraction.

Wherever an integer total has to be split proportionally — the case pool across agencies, the administrative funds pool across allocations, a hold-harmless clawback across donors — the system floors each proportional share first and then reconciles the leftover units by the largest-fractional-part method: rank the candidates by the discarded fractional part in descending order, apply the documented tie-breaks, and hand out one extra unit to each of the leading candidates until the leftover is exhausted. Every tie-break in this document ends in `created_at` ascending. **No ranking anywhere in this system ever reads a row's `id`.**

### 2.8. Stale-Version Guards on Order and Transfer Creation

Two creation operations in this API write against a parent row whose state the client must have observed first, and both are protected by an optimistic-concurrency check on that parent's `version`.

Starting a commodity order requires the non-optional field `expected_agency_allocation_version`, carrying the client's last observed `version` of the `AgencyAllocation` the order will draw against. If that value does not equal the allocation's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This is what protects the entitlement headroom: a prior `DRAFT` order for the same agency and cycle may already have been superseded and cancelled by another writer, and because supersession is legitimate product behaviour, a second sequential create would otherwise succeed against a view of `cases_remaining` the client no longer holds. The current allocation `version` is read from the entitlement list or detail reads.

Proposing an inventory transfer requires the non-optional field `expected_inventory_lot_version`, carrying the client's last observed `version` of the source `InventoryLot`. If that value does not equal the lot's current `version`, the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412). Several transfers may legitimately be proposed from one lot, so a second sequential proposal against unchanged state would succeed on its own merits; the guard exists to stop a proposal written against an outdated view of the lot's uncommitted cases.

No other endpoint in this API accepts a version field, and no other endpoint performs a version check. Note that both guarded creates themselves increment the parent's `version` by one on success — order creation advances the `AgencyAllocation`, and transfer proposal advances the `InventoryLot` — so a client issuing two creates in sequence must re-read the parent between them.

### 2.9. The Conserved Case Ledger

Cases are physical objects, and the system's central invariant is that they are never created or destroyed by bookkeeping. Three definitions make this precise.

The **available cases** of a lot are its `cases_on_hand` minus its `cases_committed`. Only available cases may be reserved by an approval or offered in a transfer.

The **program case total** is the sum of `cases_on_hand` across every `InventoryLot` whose `status` is `AVAILABLE`, `WATCH`, or `HOLD`, plus the sum of `agency_cases_on_hand` across every `Agency`. Every operation described in §3 either leaves this total unchanged or moves cases between its two terms.

For every entitlement row, `cases_remaining` equals `allocated_cases` minus `cases_committed` minus `cases_delivered`, and this identity holds after every single mutation — it is recomputed, never drifted into.

Each forward movement has an exact compensating reverse, and the pairing is what guarantees no drift:

- **Approve / cancel.** Approval adds each line's reserved cases to that lot's `cases_committed` and adds the order's `total_cases_approved` to the allocation's `cases_committed`. Cancelling the order subtracts exactly those same amounts, restoring every touched `cases_committed` and the allocation's `cases_remaining` to their exact pre-approval values. The program case total is untouched by either, because `cases_on_hand` never moves.
- **Propose / decline.** Proposing a transfer adds `cases` to the source lot's `cases_committed` and leaves `cases_on_hand` alone. Declining subtracts exactly that amount. Again the program case total is untouched.
- **Deliver.** Confirming a delivery subtracts the reserved cases from the lot's `cases_on_hand` and from its `cases_committed`, adds them to the lot's `cases_shipped_to_date`, and adds the order's `total_cases_approved` to the receiving agency's `agency_cases_on_hand`. The program case total is unchanged; the cases have simply moved from the warehouse term into the agency term.
- **Accept a transfer.** Same shape: cases leave the lot's `cases_on_hand` and `cases_committed`, accumulate into `cases_shipped_to_date`, and arrive in the receiving agency's `agency_cases_on_hand`.

No rounding of any kind occurs anywhere in this ledger; every quantity is an integer count of cases.

### 2.10. Validation Precedence

When a single request violates more than one rule, the answer is decided by the *first* violated rule in the ordering below, and no later rule is consulted. The ordering is normative — it is not a description of a convenient implementation, and reversing any two adjacent entries produces observably wrong error codes.

1. Authentication headers present and non-empty on every endpoint except the logical-clock read — `ERR_UNAUTHENTICATED`.
2. `X-User-Role` is one of the four roles and is authorised for the addressed operation — `ERR_UNAUTHORIZED`.
3. Every identifier in the request path resolves, left to right — the matching not-found code.
4. Payload well-formedness: every required field present, types as specified, enum values inside their permitted list, and every numeric range honoured — `ERR_INVALID_REQUEST`. This covers `cases_requested` greater than zero, `cases` greater than zero, `cases_distributed` greater than zero, `household_size` at least 1 and at most 20, `declared_monthly_income_cents` at least zero, `allocatable_cases` greater than zero, `admin_funds_pool_cents` not negative, `dock_number` at least 1 and at most the warehouse's `dock_count`, `window_end` strictly after `window_start`, `order_window_close_at` strictly after `order_window_open_at`, `agreement_end_date` strictly after `agreement_start_date`, `completed_at` at or before the current instant, `attendee_count` at least 1, `cases_accounted` at or below the action's `exposed_cases`, `reason` between 1 and 400 characters, pagination bounds, and each `line_adjustments` entry naming an `OrderLine` of the addressed order with a `cases_approved` value between 1 and that line's `cases_requested` inclusive.
5. Every foreign key supplied in the request body resolves — the matching not-found code.
6. Resource ownership for `AgencyCoordinator` and `StateWarehouseOperator` writes — `ERR_NOT_RESOURCE_OWNER`.
7. The optimistic-concurrency check of §2.8 — `ERR_STALE_VERSION`.
8. The addressed row is in a state that admits the requested transition — `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_CYCLE_STATE`, `ERR_INVALID_LOT_STATE`, `ERR_INVALID_APPOINTMENT_STATE`, `ERR_INVALID_TRANSFER_STATE`, `ERR_INVALID_RECALL_STATE`, `ERR_INVALID_RECALL_ACTION_STATE`, `ERR_INVALID_DISTRIBUTION_STATE`, or `ERR_AGREEMENT_NOT_RENEWABLE`, whichever machine owns the row.
9. Cross-entity state dependency on the parent cycle — `ERR_INVALID_CYCLE_STATE`. Lines may be added only while the cycle is `ALLOCATED` or `OPEN`; an order may be created only while the cycle is `ALLOCATED` or `OPEN`; approval requires the cycle to be `OPEN` or `CLOSED`; a distribution may be neither recorded nor voided against a `RECONCILED` cycle.
10. Recall hold: no lot the operation touches is in `HOLD` and no recall in `INITIATED`, `NOTIFYING`, or `MONITORING` covers it — `ERR_RECALL_HOLD_ACTIVE`. This blocks posting a lot, booking an appointment for a held order, confirming a delivery whose reservations include a held lot, proposing a transfer from a held lot, and accepting such a transfer.
11. Full case accounting on a `CLASS_I` recall before closure — `ERR_RECALL_CASES_UNACCOUNTED`.
12. Cold-chain feasibility when adding an order line — `ERR_STORAGE_CLASS_UNSUPPORTED`.
13. Civil rights training currency when approving or renewing an agreement — `ERR_TRAINING_NOT_CURRENT`.
14. Agency eligibility posture — `ERR_AGENCY_INELIGIBLE`. This guards five operations: order submit, order approve, transfer accept, household distribution recording, and delivery confirmation.
15. The household self-declaration income test — `ERR_HOUSEHOLD_INELIGIBLE`.
16. Segregation of duties on order approval and recall closure — `ERR_SEGREGATION_OF_DUTIES`.
17. The ordered commodity or distributed commodity is offered by the cycle — `ERR_COMMODITY_NOT_OFFERED`. This guards three operations: adding an order line, submitting an order, and recording a distribution.
18. Referential coherence across parents. The ordering agency must hold an entitlement in the order's cycle and a distributing agency must hold an entitlement in the named cycle, each otherwise answering `ERR_ALLOCATION_NOT_FOUND` (HTTP 404); a transfer's source lot and the proposing warehouse must agree; and an appointment's `dock_number` must belong to the order's warehouse.
19. At most one live appointment per order — `ERR_APPOINTMENT_ALREADY_EXISTS`.
20. The order window has opened — `ERR_ORDER_WINDOW_NOT_OPEN`.
21. The order window has not closed — `ERR_ORDER_WINDOW_CLOSED`. This guards order submit and window opening.
22. Appointment window sanity — `ERR_APPOINTMENT_WINDOW_INVALID`. This guards appointment creation and delivery confirmation.
23. Dock exclusivity including the turnaround buffer — `ERR_DOCK_WINDOW_CONFLICT`.
24. Uniqueness: `code` on `Commodity`, `name` on `Warehouse`, `county_code` on `ServiceArea`, and `cycle_code` on `AllocationCycle` are each unique program-wide, and `federal_lot_code` is unique within a warehouse — all answering `ERR_DUPLICATE_CODE`; at most one open recall exists per source lot — `ERR_RECALL_ALREADY_OPEN`; at most one recall action exists per recall-and-agency pair — `ERR_DUPLICATE_RECALL_ACTION`.
25. An order carries at least one line at submit — `ERR_EMPTY_ORDER`.
26. The allocation run has a non-empty included set — `ERR_NO_ELIGIBLE_AGENCIES`.
27. The allocation is arithmetically feasible — `ERR_ALLOCATION_INFEASIBLE`.
28. Warehouse staging capacity for the requested appointment — `ERR_WAREHOUSE_COLD_CAPACITY_EXCEEDED`.
29. The receiving agency's cold-storage ceiling — `ERR_AGENCY_COLD_STORAGE_EXCEEDED`.
30. A recall may be raised only against a lot in `RECEIVED`, `AVAILABLE`, or `WATCH` — `ERR_INVALID_LOT_STATE`.
31. First-expired-first-out coverage at approval — `ERR_INSUFFICIENT_INVENTORY`.
32. Entitlement headroom at submit and at approval — `ERR_ALLOCATION_EXCEEDED`.
33. Transfer volume against the source lot's available cases — `ERR_LOT_CASES_UNAVAILABLE`.
34. Agency on-hand sufficiency — `ERR_AGENCY_INVENTORY_INSUFFICIENT`. This guards distribution recording and a return-to-state disposition.
35. A cycle may be finalized only when no order of that cycle is still in flight — `ERR_INVALID_ORDER_STATE`.

Three worked conflicts illustrate the discipline. Submitting an order that is already `SUBMITTED` *and* asks for more cases than remain answers `ERR_INVALID_ORDER_STATE`, because the state check at position 8 precedes the headroom check at position 32. Submitting an order for an agency whose training has lapsed — posture `PROBATION` — where a line also names a commodity absent from the cycle's offering answers `ERR_AGENCY_INELIGIBLE`, because the posture gate at position 14 precedes the offering check at position 17. Creating an appointment that both collides with an existing dock window inside its turnaround buffer *and* would exceed the warehouse's frozen staging capacity answers `ERR_DOCK_WINDOW_CONFLICT`, because dock exclusivity at position 23 precedes staging capacity at position 28.

### 2.11. Cascade Discipline and Derived-Field Reconciliation

Many operations in this system touch more than one row. The rule is that every cascade named in §3 is part of the same transaction as its trigger: either the whole chain lands or nothing does. When a first-expired-first-out reservation cannot be satisfied, for example, no lot's `cases_committed` moves at all and the order stays where it was — there is no such thing as a partially reserved order.

Cascades in this domain are frequently *conditional*: they touch only rows in a named set of states and leave every other row alone. When an agreement is terminated, that agency's orders in `DRAFT` or `SUBMITTED` are cancelled, while orders already `APPROVED`, `SCHEDULED`, `DELIVERED`, or `CANCELLED` are untouched. When an order window closes, only `DRAFT` orders of that cycle are cancelled; `SUBMITTED` and later orders survive precisely so that review can continue after the window shuts. Implementations must not generalise a conditional cascade into a blanket one.

Derived fields are always recomputed from their inputs rather than incrementally patched where the two could diverge. A service area's `eligible_agency_count` is recomputed as the count of agencies in that area whose posture is `ELIGIBLE` after every posture write anywhere in that area. An entitlement's `cases_remaining` is recomputed from `allocated_cases`, `cases_committed`, and `cases_delivered`. A cycle's `draw_posture` is recomputed from the aggregate state of its entitlement rows whenever any of those rows' `cases_committed` or `cases_delivered` changes: it reads `NOT_STARTED` while every entitlement of the cycle is still `ENTITLED`, `FULLY_DRAWN` only when every entitlement of the cycle is `FULLY_DRAWN`, and `PARTIAL` in every other case. Each such recomputation is a mutation of the row it writes, refreshing `updated_at` and incrementing `version` per §2.5.

## 3. Business Logic & Workflows

### 3.1. Program Configuration: Service Areas, Commodities and State Warehouses

Before any allocation can run, a `StateAdmin` populates three registries.

A **service area** is a county. It is registered with a display `name` of 1 to 120 characters, a `county_code` of 2 to 8 uppercase characters that must be unique across every service area (a repeat answers `ERR_DUPLICATE_CODE`), a `poverty_population` — the count of persons below 130% of the federal poverty guideline living in that county, which may be zero but never negative — and an optional `urban_rural` classification of `URBAN`, `RURAL`, or `MIXED`, defaulting to `MIXED` when omitted. The rurality classification is carried for reporting only and enters no formula. Alongside these inputs the area maintains `eligible_agency_count`, which starts at 0 and thereafter tracks how many agencies in that area currently hold an `ELIGIBLE` posture. That count is the divisor that splits the county's poverty population across co-located agencies, and it is the reason a single training lapse in one agency changes every other agency's entitlement in the same county. A `StateAdmin` may later revise `poverty_population` and `urban_rural`; such a revision only affects cycles whose allocations are computed after the change, since a computed allocation freezes its inputs.

A **commodity** is federal configuration and is immutable once written. It is registered with a `code` in uppercase snake case, unique program-wide, a display `name`, a `storage_class` of `DRY`, `COLD`, or `FROZEN` that decides which warehouse pool and which agency ceiling the commodity consumes, a `net_weight_lbs_per_case` greater than zero carried to three decimal places, a `cases_per_pallet` count greater than zero used as the per-line pallet divisor, an `entitlement_value_cents_per_case` greater than zero charged to the state per case, a nominal `shelf_life_days` greater than zero kept for reporting (the actual shelf arithmetic uses each lot's own pack and best-by dates instead), and an `excess_case_ceiling` greater than zero — the cases-on-hand level above which a lot is flagged as excess before any staleness scoring is even considered.

A **warehouse** is registered with a `name` that must be unique program-wide, a `dock_count` of at least 1, and three independent staging pools: `dry_pallet_capacity`, `cold_pallet_capacity`, and `frozen_pallet_capacity`, each of which may be zero. A `frozen_pallet_capacity` of zero means the warehouse simply cannot serve frozen commodities at all. The warehouse also carries a `monitor_policy` feature flag of `TURNOVER_BASED` or `SHELF_LIFE_BASED`, defaulting to `TURNOVER_BASED` when omitted, which selects which staleness-scoring variant the monitor run applies to that warehouse's lots. A `StateAdmin` may later revise `dock_count`, any of the three pools, or `monitor_policy`; flipping the policy means the *next* monitor run scores that warehouse's lots under the new variant, and existing scores are not retroactively restated.

### 3.2. Agency Eligibility: Two Independent Axes and One Derived Posture

A `StateAdmin` registers an **agency** — an eligible recipient organization such as a food bank or pantry — with a `name` of 1 to 120 characters, the `service_area_id` of the county whose poverty population feeds its entitlement, a `cold_storage_pallet_capacity` of zero or more frozen-pallet positions the agency can hold at one time, and optionally the two prior-period baselines the allocation formula reads: `prior_period_pounds_distributed`, a non-negative figure carried to two decimals and defaulting to 0.0, and `prior_period_allocated_cases`, a non-negative integer defaulting to 0. A freshly registered agency starts with `agreement_status` `PENDING`, `training_status` `REQUIRED`, and `eligibility_posture` `INELIGIBLE`, and it does not move its service area's `eligible_agency_count`, because a pending agency is not eligible. The returned `id` is the value an `AgencyCoordinator` presents as `X-User-ID` from then on. A `StateAdmin` may later revise `cold_storage_pallet_capacity`, `prior_period_pounds_distributed`, and `prior_period_allocated_cases`.

The agency's eligibility is tracked on **two axes that advance independently**, and either may move before the other.

The **agreement axis** lives in `agreement_status`, which begins at `PENDING` and takes the values `PENDING`, `ACTIVE`, `EXPIRED`, and `TERMINATED`, the last of which is terminal. A `ComplianceReviewer` moves it by recording an agreement renewal, supplying `agreement_start_date` — the inclusive first day of the term — and `agreement_end_date` — the inclusive last day — both as ISO 8601 calendar dates. Both dates are null while the agency is `PENDING`. Recording a renewal is permitted only while `training_status` is `CURRENT`; attempting it while training is `REQUIRED` or `LAPSED` is refused with `ERR_TRAINING_NOT_CURRENT`. Three renewal transitions exist and they differ in their extra precondition:

- `PENDING → ACTIVE` is the initial approval. Beyond training currency, it requires `agreement_end_date` to be strictly after `agreement_start_date`, otherwise `ERR_INVALID_REQUEST`. It writes both dates from the payload, increases `renewal_count` by one, recomputes the agency's posture, and recomputes `eligible_agency_count` on the agency's service area.
- `ACTIVE → ACTIVE` is early renewal of a term that has not yet lapsed. Beyond training currency, it requires the payload's `agreement_start_date` to be strictly after the agency's *current* `agreement_end_date`, otherwise `ERR_AGREEMENT_NOT_RENEWABLE`. It replaces the term with the payload dates and increases `renewal_count` by one.
- `EXPIRED → ACTIVE` is reinstatement after a lapse. Training currency is its only extra precondition. It writes the new term, increases `renewal_count` by one, recomputes the posture, and recomputes the service area's `eligible_agency_count`.

An agreement in `TERMINATED` is not renewable at all; any attempt answers `ERR_AGREEMENT_NOT_RENEWABLE`.

The **training axis** lives in `training_status`, which begins at `REQUIRED` and takes the values `REQUIRED`, `CURRENT`, and `LAPSED`; none of them is terminal, so the training cycle `CURRENT → LAPSED → CURRENT` may repeat indefinitely. A `ComplianceReviewer` records a civil rights training session by supplying `completed_at`, the UTC instant the session finished, and `attendee_count`, which must be at least 1. Recording a training writes `last_training_completed_at` from `completed_at` and sets `training_expires_at` to one year — 365 days — after that instant, then recomputes the posture. `training_expires_at` stays null until the first training is recorded, as does `last_training_completed_at`. Three transitions exist:

- `REQUIRED → CURRENT` is the first recorded session. It requires `completed_at` at or before the current instant and `attendee_count` of at least 1, either violation answering `ERR_INVALID_REQUEST`.
- `CURRENT → CURRENT` is re-training before expiry, which extends the window. It requires `completed_at` to be strictly after the agency's existing `last_training_completed_at`, otherwise `ERR_INVALID_REQUEST`; it refreshes both `last_training_completed_at` and `training_expires_at`.
- `LAPSED → CURRENT` is re-training after expiry. It requires `completed_at` at or before the current instant, refreshes both timestamps, and recomputes the posture — an agency whose agreement is still `ACTIVE` moves from `PROBATION` back to `ELIGIBLE` in the same write.

The **derived posture** in `eligibility_posture` is the join of the two axes and is recomputed after every write to either one. If `agreement_status` is `ACTIVE` and `training_status` is `CURRENT`, the posture is `ELIGIBLE`. If `agreement_status` is `ACTIVE` and `training_status` is `LAPSED`, the posture is `PROBATION`. In every other combination — including an `ACTIVE` agreement whose training is still `REQUIRED`, and any agency whose agreement is `PENDING`, `EXPIRED`, or `TERMINATED` — the posture is `INELIGIBLE`. Immediately after any posture write, the `eligible_agency_count` of that agency's service area is recomputed as the number of agencies in that area whose posture is `ELIGIBLE`.

The posture is what the rest of the program reads, and it is read at two different strictnesses. Only an `ELIGIBLE` agency may be included in an allocation run, may submit an order, may have an order approved, and may accept an inventory transfer. Either `ELIGIBLE` or `PROBATION` suffices to record a household distribution or to have a delivery confirmed against an already-approved order — an agency whose training has lapsed may still hand out the food it already holds. An `INELIGIBLE` agency may do none of these. Every refusal on this gate carries `ERR_AGENCY_INELIGIBLE`.

Both axes also move on their own, through an operational checkpoint run that a `StateAdmin` triggers over every agency at once and which returns the agencies it changed. That sweep performs three passes and reports the union of what it touched:

- An agreement moves `ACTIVE → EXPIRED` once its `agreement_end_date` is strictly before the current date. The posture is recomputed — it necessarily becomes `INELIGIBLE` — and the service area's `eligible_agency_count` is recomputed.
- A training in `CURRENT` moves to `LAPSED` once the current instant reaches `training_expires_at`. The boundary is inclusive: exactly at the expiry instant, the training has lapsed. The posture is recomputed to `PROBATION` when the agreement is still `ACTIVE` and to `INELIGIBLE` otherwise, and the service area's `eligible_agency_count` is recomputed.
- An agreement in `EXPIRED` moves to `TERMINATED` once the current date reaches `agreement_end_date` plus the 90-day grace period. This is the one sweep outcome with a cross-entity cascade: every commodity order of that agency sitting in `DRAFT` or `SUBMITTED` is cancelled with `cancel_reason` set to `AGREEMENT_TERMINATED`, while that agency's terminal and post-approval orders are deliberately left alone. The service area's `eligible_agency_count` is recomputed.

The `version` of every agency the sweep touches is incremented by one.

### 3.3. Federal Entitlement Receipts, Inventory Monitoring and Transfers

When a federal truck arrives, a `StateAdmin` records an **inventory lot**: the `commodity_id` received, the `warehouse_id` that received it, the `federal_lot_code` from the bill of lading (1 to 40 characters, unique within that warehouse, a repeat answering `ERR_DUPLICATE_CODE`), a `cases_received` count greater than zero, and the two shelf dates `pack_date` and `best_by_date`, the latter of which must be strictly after the former. At creation the lot's `entitlement_value_cents` is written as `cases_received` multiplied by the commodity's `entitlement_value_cents_per_case` — the total federal value charged to the state for this receipt. The lot lands in `status` `RECEIVED` with `cases_on_hand` at 0, `cases_committed` at 0, `cases_shipped_to_date` at 0, `monitor_flag` at `NONE`, and `slow_moving_index` at 0.0; `posted_at`, `last_monitored_at`, and `hold_recall_id` are all null. A lot's `status` ranges over `RECEIVED`, `AVAILABLE`, `WATCH`, `HOLD`, `DISPOSED`, and `DEPLETED`, the last two being terminal.

Posting the receipt is what makes the cases real. A `StateAdmin` posts a lot, moving it `RECEIVED → AVAILABLE`: `cases_on_hand` is set to `cases_received`, `cases_committed` is set to 0, and `posted_at` is stamped from the logical clock. Posting requires the lot to be in `RECEIVED` — any other status answers `ERR_INVALID_LOT_STATE` — and requires that no recall in `INITIATED`, `NOTIFYING`, or `MONITORING` covers the lot, otherwise `ERR_RECALL_HOLD_ACTIVE`. The lot's `version` is incremented.

**Inventory monitoring** is the second operational checkpoint. A `StateAdmin` triggers a monitor run, optionally narrowing it to a single `warehouse_id`; the run returns the lots it scored. Only lots in `AVAILABLE` or `WATCH` are scored. Lots in `RECEIVED`, `HOLD`, `DISPOSED`, or `DEPLETED` are skipped entirely and keep whatever `monitor_flag` they already had.

For each scored lot the run derives four intermediates. Its **days on hand** is the whole number of complete days between `posted_at` and the current instant, computed by dividing the elapsed time by 86,400 seconds and discarding any fraction. Its **turnover ratio** is 0.0000 when `cases_received` is zero, and otherwise `cases_shipped_to_date` divided by `cases_received`, rounded half up to four decimals. Its **shelf span** is the number of days from `pack_date` to `best_by_date`. Its **shelf remaining fraction** is the number of days from the current date to `best_by_date`, floored at zero if the best-by date has already passed, divided by the shelf span, rounded half up to four decimals.

The `slow_moving_index` then follows the owning warehouse's `monitor_policy`, and the two variants genuinely disagree:

- Under `TURNOVER_BASED`, the index is 70 percent of the unsold share — one minus the turnover ratio — plus 30 percent of the age saturation, where age saturation is the days on hand divided by a 90-day horizon, capped at 1.0 so that a lot older than 90 days saturates rather than growing without bound. The sum is rounded half up to four decimals. This variant ignores the shelf-life window entirely.
- Under `SHELF_LIFE_BASED`, the index is half of the consumed shelf life — one minus the shelf remaining fraction — plus half of the unsold share — one minus the turnover ratio. The sum is rounded half up to four decimals. The same lot with the same shipment history can score above 0.60 under one policy and below 0.60 under the other, so the two policies flag different lots from identical data.

The `monitor_flag` is then decided with **excess taking strict precedence over staleness**: if the lot's `cases_on_hand` exceeds its commodity's `excess_case_ceiling`, the flag is `EXCESS` and the index plays no part in that decision; otherwise, if the rounded `slow_moving_index` is at least 0.60, the flag is `SLOW_MOVING`; otherwise the flag is `NONE`. The threshold comparison is inclusive and is made against the *rounded* index, so an index of exactly 0.6000 is `SLOW_MOVING`.

Status follows the flag. A lot in `AVAILABLE` that scores `EXCESS` or `SLOW_MOVING` moves `AVAILABLE → WATCH`. A lot in `WATCH` that scores `NONE` moves `WATCH → AVAILABLE`. A lot already in the status its flag implies simply has its `slow_moving_index` and `last_monitored_at` refreshed. Every scored lot has `monitor_flag`, `slow_moving_index`, and `last_monitored_at` written and its `version` incremented by one.

**Inventory transfers** are how the state moves stock that is watching itself age. A `StateAdmin` proposes a transfer by naming the `from_lot_id` the cases are drawn from, the `to_agency_id` that will receive them, a `cases` count greater than zero, and the stale-version guard `expected_inventory_lot_version` of §2.8. The source lot must be in `AVAILABLE` or `WATCH`: a lot in `HOLD` answers `ERR_RECALL_HOLD_ACTIVE`, and any other status answers `ERR_INVALID_LOT_STATE`. The proposed `cases` may not exceed the lot's available cases as defined in §2.9 — that is, `cases_on_hand` minus `cases_committed` at proposal time — otherwise `ERR_LOT_CASES_UNAVAILABLE`. On success the transfer is written in `status` `PROPOSED` with `transferred_value_cents` computed as `cases` multiplied by the `entitlement_value_cents_per_case` of the source lot's commodity, the lot's `cases_committed` grows by `cases` with `cases_on_hand` deliberately untouched, and the lot's `version` is incremented. `accepted_at` and `decline_reason` are both null at this point.

The receiving agency's `AgencyCoordinator` decides the outcome, and either decision is refused with `ERR_INVALID_TRANSFER_STATE` if the transfer is already `ACCEPTED` or `DECLINED` — both are terminal.

Accepting a transfer moves it `PROPOSED → ACCEPTED`. It requires the acting coordinator to own the receiving agency, requires that agency's posture to be `ELIGIBLE` (otherwise `ERR_AGENCY_INELIGIBLE`), and requires the source lot to still be in `AVAILABLE` or `WATCH` — a lot that has since gone to `HOLD` answers `ERR_RECALL_HOLD_ACTIVE`, and any other status answers `ERR_INVALID_LOT_STATE`. The cases then physically move: the lot's `cases_on_hand` and `cases_committed` each fall by `cases`, its `cases_shipped_to_date` rises by `cases`, the receiving agency's `agency_cases_on_hand` rises by `cases`, and `accepted_at` is stamped from the logical clock. If the debit brings the lot's `cases_on_hand` to zero, the lot moves `AVAILABLE → DEPLETED` or `WATCH → DEPLETED` according to where it stood, and its `monitor_flag` is reset to `NONE`.

Declining a transfer moves it `PROPOSED → DECLINED`. It requires the same ownership check, takes a `decline_reason`, and compensates the proposal exactly: the lot's `cases_committed` falls by `cases` while `cases_on_hand` is never touched, restoring the lot to its pre-proposal figures.

### 3.4. Building an Allocation Cycle: Splitting the Case Pool

A `StateAdmin` opens a program period as an **allocation cycle**, supplying a `cycle_code` of 3 to 20 uppercase characters that must be unique across all cycles (a repeat answering `ERR_DUPLICATE_CODE`), a `formula_variant` of `STANDARD` or `HOLD_HARMLESS` that selects which allocation variant the run applies, an `allocatable_cases` pool greater than zero, an `admin_funds_pool_cents` figure that may not be negative, an `offered_commodity_codes` array of 1 to 20 entries each of which must match an existing commodity `code`, and the two order-window instants `order_window_open_at` — the inclusive start — and `order_window_close_at` — the exclusive end, which must be strictly after the open instant. The cycle lands in `status` `DRAFT` with `draw_posture` `NOT_STARTED`, `total_allocated_cases` at 0, `eligible_agency_count` at 0, `admin_funds_allocated_cents` at 0, and `allocation_locked_at` null. A cycle's `status` runs `DRAFT`, `ALLOCATED`, `OPEN`, `CLOSED`, `RECONCILED`, the last being terminal, and each of the four transitions between them increments the cycle's `version` by one.

Running the allocation moves the cycle `DRAFT → ALLOCATED` and is the heart of the program. Three preconditions guard it: at least one agency must currently hold posture `ELIGIBLE`, otherwise `ERR_NO_ELIGIBLE_AGENCIES`; every entry of `offered_commodity_codes` must resolve to an existing commodity `code`, otherwise `ERR_COMMODITY_NOT_FOUND`; and under the `HOLD_HARMLESS` variant the floor lift must be fundable, otherwise `ERR_ALLOCATION_INFEASIBLE`.

The **included set** is every agency whose `eligibility_posture` is `ELIGIBLE` at the instant the run executes. Agencies in `PROBATION` or `INELIGIBLE` receive no entitlement row at all — not a zero row, no row. Service-area poverty figures and agency prior-period figures are read at run time and frozen into the entitlement rows the run creates, which is why later revisions to a service area or an agency do not disturb an allocation that has already been computed. The run stamps `allocation_locked_at` from the logical clock and records into the cycle's `eligible_agency_count` how many agencies the included set held.

The split proceeds in eight steps, in this order.

**Step one — the poverty factor.** Each included agency's `poverty_factor` is its service area's `poverty_population` divided by that same area's `eligible_agency_count`, rounded half up to four decimals. Co-located eligible agencies therefore split their county's poverty count evenly between them.

**Step two — the poverty share.** The poverty factors of all included agencies are summed, and each agency's `poverty_share` is its own `poverty_factor` divided by that sum, rounded half up to six decimals.

**Step three — the prior share and the blended score.** The `prior_period_pounds_distributed` of all included agencies are summed. If that sum is zero, every agency's `prior_share` is 0.000000 and its `raw_score` is set equal to its `poverty_share` — the weights collapse entirely onto poverty. Otherwise each agency's `prior_share` is its own `prior_period_pounds_distributed` divided by that sum, rounded half up to six decimals, and its `raw_score` is 60 percent of its `poverty_share` plus 40 percent of its `prior_share`, rounded half up to six decimals.

**Step four — the exact and floored case counts.** Each agency's exact entitlement is the cycle's `allocatable_cases` multiplied by its `raw_score`; its base entitlement is that exact figure with the fractional part discarded.

**Step five — largest-remainder rounding.** The remainder is the cycle's `allocatable_cases` minus the sum of all base entitlements. The included agencies are ranked by the fractional part they lost in step four, descending, with ties broken by `poverty_factor` descending and then by the entitlement row's `created_at` ascending. One extra case is given to each of the first agencies in that ranking until the remainder is exhausted. The result is each agency's *provisional* entitlement.

**Step six — the variant switch on `formula_variant`.**

Under `STANDARD`, `floor_cases` stays 0 for every agency and `allocated_cases` is simply the provisional figure. No agency is protected against a decline relative to what it received last period.

Under `HOLD_HARMLESS`, each agency's `floor_cases` is 90 percent of its `prior_period_allocated_cases` with the fractional part discarded, and no agency may finish below that floor. The total shortfall is the sum, across all agencies, of how far each agency's floor exceeds its provisional figure, counting zero where the provisional figure already meets or beats the floor. The donors are those agencies whose provisional figure strictly exceeds their own floor, ranked by their excess — provisional minus floor — descending, with ties broken by `prior_period_allocated_cases` descending and then by the entitlement row's `created_at` ascending. The total excess is the sum of the donors' individual excesses. If the total shortfall exceeds the total excess the allocation cannot be funded and the run is refused with `ERR_ALLOCATION_INFEASIBLE`. Otherwise every donor except the last in rank order is reduced by the total shortfall multiplied by that donor's own excess divided by the total excess, with the fractional part discarded; the last donor in rank order absorbs whatever remains of the total shortfall after those earlier reductions, which is what makes the clawback sum exactly. Each agency's `allocated_cases` is then the greater of its provisional figure and its `floor_cases`, less whatever reduction it absorbed as a donor; agencies that were not donors absorb no reduction.

**Step seven — the minimum lift.** Under both variants, a single pass then lifts every agency whose `allocated_cases` is below the five-case programme minimum up to exactly five cases. Each lifted case is funded one at a time from whichever agency currently holds the largest `allocated_cases`, with ties broken by the entitlement row's `created_at` ascending, and no agency may be taken below the greater of the five-case minimum and its own `floor_cases`. If the lift cannot be fully funded under that constraint, the run is refused with `ERR_ALLOCATION_INFEASIBLE`. The lift runs exactly once and is never re-evaluated against its own output — an agency pushed down to the five-case minimum by funding someone else's lift does not itself trigger a further lift.

**Step eight — the invariant.** The sum of `allocated_cases` across the cycle's entitlement rows equals the cycle's `allocatable_cases` exactly, and the cycle's `total_allocated_cases` is written from that sum.

Every entitlement row created by the run records its `cycle_id` and `agency_id` along with every formula intermediate — `poverty_factor`, `poverty_share`, `prior_share`, `raw_score`, `floor_cases`, `allocated_cases` — and starts its draw counters at `cases_committed` 0, `cases_delivered` 0, `cases_remaining` equal to `allocated_cases`, and `status` `ENTITLED`. An entitlement's `status` ranges over `ENTITLED`, `PARTIALLY_DRAWN`, `FULLY_DRAWN`, and `RECONCILED`. Its recordkeeping and funds fields — `distributed_pounds`, `distribution_record_count`, `record_compliance_pct`, `admin_funds_base_cents`, `admin_funds_withheld_cents`, `admin_funds_cents` — all start at zero and are filled in later, the first three by distribution recording and the last three at reconciliation. Entitlement rows are created by cascade rather than by direct client request, so they are discoverable only through the entitlement reads — which is also where a client obtains the `version` it must present under §2.8.

Once allocations exist, a `StateAdmin` opens the order window, moving the cycle `ALLOCATED → OPEN`. Opening requires the current instant to be strictly before `order_window_close_at`; at or after that instant the window is already closed and the request is refused with `ERR_ORDER_WINDOW_CLOSED`. Closing the window later moves the cycle `OPEN → CLOSED` and cascades conditionally: every commodity order of that cycle still sitting in `DRAFT` is cancelled with `cancel_reason` set to `WINDOW_CLOSED`, while `SUBMITTED` and later orders survive so that review can finish after the window shuts.

### 3.5. Agency Ordering: Draft Orders, Lines and Submission

An `AgencyCoordinator` starts a **commodity order** by naming the `cycle_id` whose window and offering will constrain it, the `agency_id` placing it — which must equal `X-User-ID` — the `warehouse_id` whose lots will fill it, and the `expected_agency_allocation_version` guard of §2.8. The cycle must be in `ALLOCATED` or `OPEN`, otherwise `ERR_INVALID_CYCLE_STATE`; and the named agency must hold an entitlement in that cycle, otherwise `ERR_ALLOCATION_NOT_FOUND`. Creation is *superseding*: any existing order of the same agency in the same cycle that is still in `DRAFT` is cancelled with `cancel_reason` set to `SUPERSEDED`, so an agency never accumulates competing drafts. The new order lands in `status` `DRAFT` with `line_count` 0, `total_cases_requested` 0, `total_cases_approved` 0, `total_pounds` 0.0, `total_pallets` 0, `revision_count` 0, and `last_returned_by_user_id`, `approved_by_user_id`, `submitted_at`, `approved_at`, and `cancel_reason` all null. Creation increments the parent entitlement's `version` by one — which is exactly why a client issuing a second create must re-read the entitlement first. An order's `status` runs over `DRAFT`, `SUBMITTED`, `APPROVED`, `HELD`, `SCHEDULED`, `DELIVERED`, and `CANCELLED`, the last two being terminal.

Lines are added to a `DRAFT` order one at a time by its owning coordinator, each naming a `commodity_id` and a `cases_requested` count greater than zero. The `order_id` of a line comes from the addressed order rather than from the body. Adding a line requires the order to be in `DRAFT` (otherwise `ERR_INVALID_ORDER_STATE`) and its cycle to be in `ALLOCATED` or `OPEN` (otherwise `ERR_INVALID_CYCLE_STATE`), and it requires the commodity's `code` to appear in the cycle's `offered_commodity_codes`, otherwise `ERR_COMMODITY_NOT_OFFERED`.

Cold-chain feasibility is checked at this point too, because there is no sense in accepting a line the chain cannot carry. The receiving warehouse must have a non-zero capacity pool for the line's storage class — a `DRY` line needs `dry_pallet_capacity` above zero, a `COLD` line needs `cold_pallet_capacity` above zero, a `FROZEN` line needs `frozen_pallet_capacity` above zero — and a `FROZEN` line additionally requires the ordering agency's own `cold_storage_pallet_capacity` to be above zero. Any of these failing answers `ERR_STORAGE_CLASS_UNSUPPORTED`. The line records a `storage_class` copied from the commodity at creation time, which is the value every later capacity computation reads. Its `cases_approved` starts at 0, its `line_pounds` at 0.0, its `line_pallets` at 0, and its `lot_assignments` as an empty array; all four are written at approval. Each line added increases the order's `line_count` by one, recomputes its `total_cases_requested` as the sum of `cases_requested` over its lines, and increments the order's `version`.

Submitting the order hands it to compliance review and moves it `DRAFT → SUBMITTED`. Seven preconditions apply, and the ordering of §2.10 decides which one answers when several fail at once. The order's cycle must be in `status` `OPEN` and the current instant must be at or after `order_window_open_at`, either failing answering `ERR_ORDER_WINDOW_NOT_OPEN`. The current instant must be strictly before `order_window_close_at`; exactly at the close instant the window is shut, and the request is refused with `ERR_ORDER_WINDOW_CLOSED`. The agency's posture must be `ELIGIBLE`, otherwise `ERR_AGENCY_INELIGIBLE`. The order must carry at least one line, otherwise `ERR_EMPTY_ORDER`. Every line's commodity `code` must still appear in the cycle's `offered_commodity_codes`, otherwise `ERR_COMMODITY_NOT_OFFERED`. And the order's `total_cases_requested` must not exceed the entitlement's `cases_remaining`, otherwise `ERR_ALLOCATION_EXCEEDED`. On success `submitted_at` is stamped from the logical clock and the order's `version` is incremented; note that `submitted_at` records the *most recent* submit, so a resubmission after a revision round trip overwrites it.

An order may be cancelled by its owning `AgencyCoordinator` or by a `StateAdmin`, with a `cancel_reason` supplied in the payload, along any of four transitions: `DRAFT → CANCELLED`, `SUBMITTED → CANCELLED`, `APPROVED → CANCELLED`, and `SCHEDULED → CANCELLED`. Cancelling an order that is already `DELIVERED` or `CANCELLED` answers `ERR_INVALID_ORDER_STATE`. From `DRAFT` or `SUBMITTED` there are no commitments to release, so the cancellation merely writes `cancel_reason`. From `APPROVED` the full compensation of §2.9 runs: each lot named in the order's `lot_assignments` has its `cases_committed` reduced by exactly the cases it had reserved with `cases_on_hand` untouched, the entitlement's `cases_committed` falls by `total_cases_approved` and its `cases_remaining` is recomputed, the entitlement returns to `status` `ENTITLED` when both its `cases_committed` and its `cases_delivered` are zero, and the cycle's `draw_posture` is recomputed. From `SCHEDULED` the same compensation runs, and in addition the order's delivery appointment — whether it is `SCHEDULED` or `BLOCKED` — is cancelled. Every cancellation increments the order's `version`.

### 3.6. Compliance Review: Revision Round Trips, Approval, Conversion and Reservation

A `ComplianceReviewer` who is unhappy with a submitted order returns it for revision, moving it `SUBMITTED → DRAFT`. The order must actually be in `SUBMITTED`, otherwise `ERR_INVALID_ORDER_STATE`. The return increases `revision_count` by one, writes the acting reviewer's `X-User-ID` into `last_returned_by_user_id`, and increments the order's `version`. The agency then edits and resubmits, so the revision cycle `DRAFT → SUBMITTED → DRAFT → SUBMITTED` may repeat as often as review demands.

That recorded identity is what enforces four-eyes review. When a reviewer approves an order, either the order has never been returned — `revision_count` is 0 — or the acting `X-User-ID` must differ from `last_returned_by_user_id`. A reviewer attempting to approve the very resubmission they themselves sent back is refused with `ERR_SEGREGATION_OF_DUTIES`.

Approval moves the order `SUBMITTED → APPROVED` and is the single most consequential operation in the API. Its cycle must be in `OPEN` or `CLOSED`, otherwise `ERR_INVALID_CYCLE_STATE`. Beyond the four-eyes check, the agency's posture must be `ELIGIBLE`, otherwise `ERR_AGENCY_INELIGIBLE`. The reviewer may trim the order by supplying an optional `line_adjustments` array, whose entries each take the form of an `order_line_id` naming a line of *this* order together with a `cases_approved` value between 1 and that line's `cases_requested` inclusive; an entry naming a foreign line or an out-of-range figure answers `ERR_INVALID_REQUEST`. Any line without a matching adjustment entry is approved at its full `cases_requested`. Lines are never partially skipped: every line of the order receives a `cases_approved` value.

**Pound and pallet conversion.** With every line's `cases_approved` settled, each line's `line_pounds` is its `cases_approved` multiplied by its commodity's `net_weight_lbs_per_case`, rounded half up to two decimals; and each line's `line_pallets` is its `cases_approved` divided by its commodity's `cases_per_pallet`, rounded *up* to the next whole number. **The order of rounding and summation is pinned: each line is rounded and each line is ceilinged first, and only then are the results summed.** The order's `total_pounds` is the sum of the per-line rounded `line_pounds` values, and its `total_pallets` is the sum of the per-line ceilinged `line_pallets` values. The two tempting alternatives — summing the raw case-weight products across lines and rounding once at the end, or summing all cases across lines and ceilinging once against a pallet factor — produce different numbers and are explicitly **not** the contract. To make the difference concrete: with per-case weights of 24.375, 20.000, and 30.125 pounds and pallet factors of 60, 50, and 45 cases per pallet, lines of 10 and 15 cases of canned peaches plus 23 cases of frozen chicken give a `total_pounds` of 1302.26 and a `total_pallets` of 3 under the pinned per-line order, against 1302.25 and 2 under the rejected alternatives. The same per-line pallet figures are read again later when a delivery appointment computes its per-class pallet load.

**First-expired-first-out reservation.** Approval then pins physical cases against the order's lines, processing the lines in their own `created_at` ascending order. For each line, the candidate lots are those at the order's `warehouse_id` whose `commodity_id` matches the line's, whose `status` is `AVAILABLE` or `WATCH`, and whose available cases — `cases_on_hand` minus `cases_committed` — are greater than zero. Lots in `RECEIVED`, `HOLD`, `DISPOSED`, or `DEPLETED` are invisible to the selector. The candidates are ranked by `best_by_date` ascending, with ties broken by `created_at` ascending and by nothing else; the selector walks that ranking in order, taking from each candidate the lesser of the cases still needed and that candidate's available cases, until the line's need is met. Each amount taken is appended to the line's `lot_assignments` in fill order as a pairing of the `lot_id` drawn from and the `cases` taken, and is added to that lot's `cases_committed`.

If the ranked candidate list is exhausted while a line still needs cases, the **entire approval fails** with `ERR_INSUFFICIENT_INVENTORY`: no line is partially reserved, no lot's `cases_committed` changes, and the order remains in `SUBMITTED`. Approval is all-or-nothing.

Once conversion and reservation succeed, the order's `total_cases_approved` is written as the sum of the lines' `cases_approved`, and that figure must not exceed the entitlement's `cases_remaining`, otherwise `ERR_ALLOCATION_EXCEEDED`. On success `approved_at` is stamped from the logical clock, `approved_by_user_id` records the reviewer's `X-User-ID`, each reserved lot's `cases_committed` carries its new reservation, the entitlement's `cases_committed` grows by `total_cases_approved` with `cases_remaining` recomputed and its `status` moved to `PARTIALLY_DRAWN`, the cycle's `draw_posture` is recomputed, and the order's `version` is incremented.

### 3.7. Dock Scheduling and Delivery Confirmation

An approved order needs a dock. A `StateWarehouseOperator` or a `StateAdmin` books a **delivery appointment** by naming the `order_id`, a `dock_number`, and the half-open window bounded by `window_start` (inclusive) and `window_end` (exclusive, and strictly after the start). The `warehouse_id` and `agency_id` of the appointment are copied from the order rather than supplied, and the appointment's three per-class pallet loads are summed from the order's lines: `dry_pallets` is the sum of `line_pallets` over the order's `DRY` lines, `cold_pallets` the sum over its `COLD` lines, and `frozen_pallets` the sum over its `FROZEN` lines. The appointment lands in `status` `SCHEDULED` with `delivered_pounds` 0.0 and both `confirmed_by_user_id` and `cancel_reason` null, and it moves its order `APPROVED → SCHEDULED`, incrementing the order's `version`. An appointment's `status` runs over `SCHEDULED`, `BLOCKED`, `DELIVERED`, and `CANCELLED`, the last two being terminal.

Booking is gated by a stack of checks. The order must be in `APPROVED`, otherwise `ERR_INVALID_ORDER_STATE` — an order sitting in `HELD` because a recall touched one of its lots cannot be scheduled, and an attempt to book against held inventory answers `ERR_RECALL_HOLD_ACTIVE`. The order must not already have a live appointment: if one exists in `SCHEDULED`, `BLOCKED`, or `DELIVERED`, the request answers `ERR_APPOINTMENT_ALREADY_EXISTS` even when the requested window is entirely free. The `dock_number` must be at least 1 and at most the warehouse's `dock_count`, and it must belong to the order's own warehouse. The `window_start` must be at or after the current instant; a window that starts in the past answers `ERR_APPOINTMENT_WINDOW_INVALID`.

Then come three capacity tests, and **their interval geometries deliberately differ**. A pair of windows that merely touch at one instant is a conflict under the first test, harmless under the second, and a capacity interaction under the third. Window instants are compared at minute resolution throughout, and every pallet sum is an integer.

**Test A — dock exclusivity, with a turnaround buffer.** The resource is a single dock at a single warehouse. The peers are appointments at the same `warehouse_id` on the same `dock_number` whose `status` is `SCHEDULED`, `BLOCKED`, or `DELIVERED` — a delivered appointment still occupies its dock for exclusivity purposes. A conflict exists when the new window starts before an existing window's end extended by the half-hour turnaround (30 minutes) *and* that existing window starts before the new window's end extended by the same half-hour. In other words the buffer is applied on both sides of every existing window. A new window starting exactly 30 minutes after an existing window's end is accepted; starting one minute earlier than that is rejected with `ERR_DOCK_WINDOW_CONFLICT`.

**Test B — warehouse staging capacity, on plain half-open overlap.** The resource is the warehouse's three staging pools. The peers are appointments at the same `warehouse_id` whose `status` is `SCHEDULED` or `BLOCKED` — a delivered appointment no longer consumes staging — and which overlap the new window in the half-open sense: the peer starts strictly before the new window ends *and* the new window starts strictly before the peer ends, so windows that merely touch at an endpoint do not interact. For each of the three storage classes independently, the new appointment's pallets of that class plus the sum of that class's pallets over the overlapping peers must not exceed the warehouse's matching capacity — `dry_pallets` against `dry_pallet_capacity`, `cold_pallets` against `cold_pallet_capacity`, `frozen_pallets` against `frozen_pallet_capacity`. Any of the three breaching answers `ERR_WAREHOUSE_COLD_CAPACITY_EXCEEDED`.

**Test C — the agency's cold storage ceiling, on closed-interval overlap across all warehouses.** The resource here is the receiving agency, not a warehouse, and the peers span *every* warehouse: appointments with the same `agency_id` whose `status` is `SCHEDULED` or `BLOCKED` and which overlap the new window in the closed sense — the peer starts at or before the new window's end *and* the new window starts at or before the peer's end — so windows that touch at an endpoint *do* interact. The new appointment's `frozen_pallets` plus the sum of `frozen_pallets` over those peers must not exceed the agency's `cold_storage_pallet_capacity`, otherwise `ERR_AGENCY_COLD_STORAGE_EXCEEDED`. This is the aggregate ceiling that stops an agency from accepting more frozen product across concurrent appointments than its own freezer can hold.

**Confirming delivery** is reserved to the `StateWarehouseOperator` who owns the dock: `X-User-ID` must equal the appointment's `warehouse_id`, otherwise `ERR_NOT_RESOURCE_OWNER`. The appointment must be in `SCHEDULED` — `BLOCKED`, `DELIVERED`, and `CANCELLED` all answer `ERR_INVALID_APPOINTMENT_STATE`. The current instant must be at or after `window_start`, otherwise `ERR_APPOINTMENT_WINDOW_INVALID`. Every lot named in the order's `lot_assignments` must still be in `AVAILABLE` or `WATCH`, otherwise `ERR_RECALL_HOLD_ACTIVE`. The receiving agency's posture must be `ELIGIBLE` or `PROBATION`, otherwise `ERR_AGENCY_INELIGIBLE`.

Confirmation then drives the longest cascade in the system, and every link of it must land. The appointment moves `SCHEDULED → DELIVERED`, capturing `delivered_pounds` from the order's `total_pounds` and recording the confirming operator in `confirmed_by_user_id`. Each reserved lot has the reserved cases subtracted from `cases_on_hand`, subtracted from `cases_committed`, and added to `cases_shipped_to_date`; a lot whose `cases_on_hand` reaches zero moves to `DEPLETED` with its `monitor_flag` reset to `NONE`. The order moves `SCHEDULED → DELIVERED`. The entitlement then has `total_cases_approved` subtracted from its `cases_committed` and added to its `cases_delivered`, its `cases_remaining` is recomputed, and its `status` becomes `FULLY_DRAWN` when `cases_remaining` reaches zero and `PARTIALLY_DRAWN` otherwise. The cycle's `draw_posture` is recomputed from all of its entitlement rows. Finally the receiving agency's `agency_cases_on_hand` and `delivered_cases_ytd` each grow by the order's `total_cases_approved` — the first is the live stock the agency may hand out or return, the second a cumulative year-to-date figure that never falls. The appointment's `version` is incremented.

An appointment may also be cancelled, and this is a `StateAdmin` capability — the warehouse operator cannot do it. Cancellation takes a `cancel_reason` and runs either `SCHEDULED → CANCELLED` or `BLOCKED → CANCELLED`; an appointment already `DELIVERED` or `CANCELLED` answers `ERR_INVALID_APPOINTMENT_STATE`. Cancelling a `SCHEDULED` appointment returns its order `SCHEDULED → APPROVED`, retaining every lot and entitlement commitment while releasing the dock slot, so the order can simply be rebooked. Cancelling a `BLOCKED` appointment leaves its order in `HELD` — the recall, not the appointment, is what holds it — while still releasing the dock window and both the warehouse and agency pallet ceilings. Either way the appointment's `version` is incremented.

### 3.8. Recall Execution Across Downstream Agencies

A `StateAdmin` raises a **recall** against a suspect lot by naming the `source_lot_id`, a `recall_class` of `CLASS_I`, `CLASS_II`, or `CLASS_III`, a `hold_scope` of `LOT_ONLY` or `COMMODITY_WIDE`, and a `reason` narrative of 1 to 400 characters. The source lot must be in `RECEIVED`, `AVAILABLE`, or `WATCH`; a `DISPOSED` or `DEPLETED` lot cannot be recalled and answers `ERR_INVALID_LOT_STATE`. At most one recall in `INITIATED`, `NOTIFYING`, or `MONITORING` may name a given source lot at a time, a second attempt answering `ERR_RECALL_ALREADY_OPEN`. The recall records `commodity_code`, denormalised from the source lot's commodity at creation for downstream reporting, and `initiated_by_user_id` from the raising admin's `X-User-ID`. It lands in `status` `INITIATED` with `held_lot_count`, `action_count`, `acknowledged_count`, `dispositioned_count`, and `accounted_cases` all at 0 and `notices_dispatched_at` null. A recall's `status` runs over `INITIATED`, `NOTIFYING`, `MONITORING`, and `CLOSED`, the last being terminal.

**The hold scope decides coverage.** Under `LOT_ONLY`, only the source lot is covered. Under `COMMODITY_WIDE`, every lot in `AVAILABLE` or `WATCH` sharing the source lot's `commodity_id` is covered, in every warehouse, not just the source lot's own. Each covered lot moves `AVAILABLE → HOLD` or `WATCH → HOLD` — a lot moved from `WATCH` keeps its existing `monitor_flag`, since the hold says nothing about staleness — has its `hold_recall_id` set to the recall's `id`, contributes one to the recall's `held_lot_count`, and has its `version` incremented. A source lot still in `RECEIVED` is not moved to `HOLD`, because no such transition exists; posting it is nonetheless refused with `ERR_RECALL_HOLD_ACTIVE` for as long as the recall stays open.

**The cascade chain then runs three links deep: recall to lot hold, lot hold to appointment block, appointment block to order hold.** Every delivery appointment in `SCHEDULED` whose order reserves cases from a newly held lot — that is, whose order has a line whose `lot_assignments` reference that lot — moves `SCHEDULED → BLOCKED`. Every order behind such an appointment moves `SCHEDULED → HELD`, and every order in `APPROVED` with no appointment yet but with `lot_assignments` referencing a held lot moves `APPROVED → HELD`. In both cases the commitments stay exactly in place: a held order neither releases its reserved cases nor its entitlement headroom, and while it is `HELD` it can be neither scheduled nor delivered.

**Downstream exposure becomes recall actions.** For every agency that already received cases from a held lot, whether by confirmed delivery or by accepted transfer, the recall creates one `RecallAction` in `status` `PENDING_NOTICE` recording the `recall_id`, the `agency_id`, and an `exposed_cases` count captured at creation, with `disposition`, `cases_accounted`, `notified_at`, `acknowledged_at`, and `dispositioned_at` all empty. Each action created raises the recall's `action_count`. A recall action's `status` runs over `PENDING_NOTICE`, `NOTIFIED`, `ACKNOWLEDGED`, and `DISPOSITIONED`, the last being terminal. Like entitlement rows, action rows are created by cascade and are therefore discoverable only through the recall-action reads. At most one action may exist per recall-and-agency pair.

**Dispatching notices** moves the recall `INITIATED → NOTIFYING` and requires an `action_count` of at least 1, otherwise `ERR_INVALID_RECALL_STATE`. Every action of the recall that is in `PENDING_NOTICE` moves `PENDING_NOTICE → NOTIFIED` with `notified_at` stamped from the logical clock, the recall's `notices_dispatched_at` is stamped from the same clock, and the recall's `version` is incremented. Dispatch is valid while the recall is `INITIATED` or `NOTIFYING`, which is what lets a re-expanded recall be re-dispatched.

**Acknowledgement is the downstream agency's job.** The `AgencyCoordinator` who owns the addressed action acknowledges it, moving it `NOTIFIED → ACKNOWLEDGED`; an action in any other status answers `ERR_INVALID_RECALL_ACTION_STATE`. The acknowledgement stamps `acknowledged_at` from the logical clock, raises the recall's `acknowledged_count` — which counts every action in `ACKNOWLEDGED` or `DISPOSITIONED` — and increments the action's `version`. When `acknowledged_count` reaches `action_count`, the acknowledgement bubbles up and moves the recall `NOTIFYING → MONITORING`, a transition that writes no field beyond the recall's own counters.

**Reporting a disposition** is the same coordinator's next step, moving the action `ACKNOWLEDGED → DISPOSITIONED`; an action not in `ACKNOWLEDGED` answers `ERR_INVALID_RECALL_ACTION_STATE`. The report supplies a `disposition` of `DESTROYED`, `RETURNED_TO_STATE`, or `NOT_RECEIVED`, and a `cases_accounted` figure that may not exceed the action's `exposed_cases`, otherwise `ERR_INVALID_REQUEST`. A `RETURNED_TO_STATE` disposition additionally requires `cases_accounted` not to exceed the agency's `agency_cases_on_hand`, otherwise `ERR_AGENCY_INVENTORY_INSUFFICIENT` — an agency cannot return stock it no longer holds. The report writes `disposition`, `cases_accounted`, and `dispositioned_at`, raises the recall's `dispositioned_count` by one and its `accounted_cases` by `cases_accounted`, and increments the action's `version`. Under `RETURNED_TO_STATE` the cases physically travel back: the agency's `agency_cases_on_hand` falls by `cases_accounted` and the source lot's `cases_on_hand` rises by the same amount, keeping the program case total of §2.9 conserved.

**Expanding a recall** handles exposure discovered late. A `StateAdmin` names an additional `agency_id`; the recall must be in `MONITORING`, otherwise `ERR_INVALID_RECALL_STATE`, and no existing action of that recall may already name that agency, otherwise `ERR_DUPLICATE_RECALL_ACTION`. The expansion creates one new action in `PENDING_NOTICE` with `exposed_cases` computed from that agency's receipts, raises `action_count` by one, returns the recall `MONITORING → NOTIFYING` so the new notice can be dispatched, and increments the recall's `version`. The recall cycle `NOTIFYING → MONITORING → NOTIFYING` may therefore repeat as often as new exposure surfaces.

**Closing a recall** is the final act, and it may not be performed by the `StateAdmin` recorded in `initiated_by_user_id` — that same admin attempting closure is refused with `ERR_SEGREGATION_OF_DUTIES`. Two closure paths exist. The normal path is `MONITORING → CLOSED`, available once the recall's `dispositioned_count` equals its `action_count`. The zero-exposure escape hatch is `INITIATED → CLOSED`, available when the recall's `action_count` is 0: a recall raised on a lot with no delivered or transferred cases downstream has no action to dispatch, so it never needs to pass through `NOTIFYING` and `MONITORING` at all. Any other combination — dispatching aside, a recall with at least one action that has not reached `MONITORING` with every action dispositioned, or an `INITIATED` recall that does have actions — answers `ERR_INVALID_RECALL_STATE`.

Closure of a `CLASS_I` recall carries one extra bar: every dispositioned action must have reported a `cases_accounted` figure equal to its `exposed_cases`, and any shortfall refuses the closure with `ERR_RECALL_CASES_UNACCOUNTED`. A `CLASS_II` or `CLASS_III` recall may close with partial accounting.

What closure does to the held lots depends entirely on **whether any dispositioned action reported `DESTROYED`**, and the two outcomes are mirror images of each other.

If no disposition was `DESTROYED`, the recall releases: each held lot moves `HOLD → AVAILABLE` with `hold_recall_id` cleared back to null, every delivery appointment that this lot's hold had put into `BLOCKED` moves `BLOCKED → SCHEDULED`, and every order in `HELD` whose `lot_assignments` reference the lot moves `HELD → APPROVED` — and where its appointment came back to `SCHEDULED`, the order continues on to `SCHEDULED` in the same cascade. The hold cycle `APPROVED → HELD → APPROVED` closes cleanly with every commitment intact, and a recall closed from `INITIATED` with no actions at all always takes this release path, since with no downstream exposure there can be no destruction to account for.

If at least one disposition was `DESTROYED`, the recall disposes: each held lot moves `HOLD → DISPOSED` with both `cases_on_hand` and `cases_committed` written to 0, every delivery appointment in `BLOCKED` *or* `SCHEDULED` drawing on that lot is cancelled with `cancel_reason` set to `LOT_DISPOSED`, and every order in `HELD` *or* `APPROVED` whose `lot_assignments` reference the lot is cancelled — with the commitment release path of §2.9 running for each, so the entitlement's `cases_committed` and `cases_remaining` return to their pre-approval figures and the cycle's `draw_posture` is recomputed. Either way the recall moves to `CLOSED` and its `version` is incremented.

### 3.9. Household Distribution, Recordkeeping and Cycle Reconciliation

The program's purpose is reached when an agency hands food to a household, and that is recorded by the agency's own `AgencyCoordinator` as a **household distribution**. The record names the `agency_id` (which must equal `X-User-ID`), the `cycle_id` it is recorded against, the `commodity_id` handed over, and the self-declared facts: a `household_size` of at least 1 and at most 20 persons, a `declared_monthly_income_cents` figure of gross monthly household income in cents that may not be negative, an optional `participates_in_snap` boolean defaulting to `false`, a `self_declaration_signed` boolean recording whether the signed self-declaration form was actually captured, a `cases_distributed` count greater than zero, and a `distribution_date` as an ISO 8601 calendar date. The record's `status` is `RECORDED` on creation and may later become `VOIDED`, which is terminal; `void_reason` is null until then.

The cycle must not be `RECONCILED`, otherwise `ERR_INVALID_CYCLE_STATE`. The agency must hold an entitlement in that cycle, otherwise `ERR_ALLOCATION_NOT_FOUND`. The commodity's `code` must appear in the cycle's `offered_commodity_codes`, otherwise `ERR_COMMODITY_NOT_OFFERED`. The agency's posture must be `ELIGIBLE` or `PROBATION`, otherwise `ERR_AGENCY_INELIGIBLE`.

**The self-declaration income test** decides household eligibility from the request alone; no history is consulted. The record's `income_limit_cents` is a base limit of 195,000 cents per month plus 68,000 cents for each person in the household beyond the first — that is, the base plus `household_size` less one, multiplied by the per-person figure. If `declared_monthly_income_cents` is at or below that limit, `eligibility_determination` is written as `ELIGIBLE`; the boundary is inclusive. If the declared income exceeds the limit but `participates_in_snap` is `true`, the household qualifies categorically regardless of income and `eligibility_determination` is written as `CATEGORICALLY_ELIGIBLE`. If the declared income exceeds the limit and `participates_in_snap` is `false`, the request is refused with `ERR_HOUSEHOLD_INELIGIBLE`, no row is persisted, and no rollup figure or on-hand counter moves at all. Worked at a `household_size` of 3, the limit comes to 331,000 cents: a declared 331,000 is `ELIGIBLE`, a declared 331,001 is refused, and a declared 331,001 with SNAP participation is `CATEGORICALLY_ELIGIBLE`.

The distribution's `pounds_distributed` is its `cases_distributed` multiplied by the commodity's `net_weight_lbs_per_case`, rounded half up to two decimals. The `cases_distributed` figure must not exceed the agency's `agency_cases_on_hand`, otherwise `ERR_AGENCY_INVENTORY_INSUFFICIENT`; on success that counter falls by `cases_distributed`.

**The recordkeeping rollup** is then recomputed on the entitlement row for that agency and cycle, over its `RECORDED` rows only — `VOIDED` rows are excluded from every aggregate. The entitlement's `distribution_record_count` is the number of such rows; its `distributed_pounds` is the sum of their `pounds_distributed` values, rounded half up to two decimals; and its `record_compliance_pct` is 0.0000 when the count is zero, and otherwise the number of those rows carrying `self_declaration_signed` equal to `true` divided by the count, rounded half up to four decimals. That compliance share is what later decides whether administrative funds are withheld.

Voiding a distribution moves it `RECORDED → VOIDED` and is available to the owning coordinator with a `void_reason`. The record must be in `RECORDED`, otherwise `ERR_INVALID_DISTRIBUTION_STATE`, and its cycle must not be `RECONCILED`, otherwise `ERR_INVALID_CYCLE_STATE`. The void compensates exactly: the entitlement's `distributed_pounds` falls by the record's `pounds_distributed`, its `distribution_record_count` falls by one, and its `record_compliance_pct` is recomputed over the remaining `RECORDED` rows, while the agency's `agency_cases_on_hand` rises by `cases_distributed`. Recording a row and then voiding it therefore restores `distributed_pounds`, `distribution_record_count`, `record_compliance_pct`, and `agency_cases_on_hand` to their exact pre-record values. The record's `version` is incremented.

**Finalizing the cycle** moves it `CLOSED → RECONCILED` and is a `StateAdmin` act. It is permitted only when no commodity order of that cycle is still in `SUBMITTED`, `APPROVED`, `HELD`, or `SCHEDULED`, otherwise `ERR_INVALID_ORDER_STATE` — the administrative funds must be computed over settled distributions only, not over orders still in flight.

Finalization distributes the cycle's `admin_funds_pool_cents` across its entitlement rows. **The evaluation order below is pinned and each step runs exactly once.** The dependency reads as though it were circular — each agency's final award depends on a redistribution pool that itself depends on the base awards — and it is resolved by forbidding any second pass.

**Step one — the weighting basis.** The `distributed_pounds` figures of every entitlement row of the cycle are summed. If that total is zero, the weighting basis is substituted: each row's weight becomes its `allocated_cases` and the total weight becomes the cycle's `total_allocated_cases`, so the pool is still fully distributed and the closing invariant still holds. Otherwise each row's weight is its own `distributed_pounds` and the total weight is the pounds total.

**Step two — the base award.** Each row's exact base is the cycle's `admin_funds_pool_cents` multiplied by that row's weight and divided by the total weight; its floored base is that figure with the fractional part discarded. The residual is the pool minus the sum of the floored bases. The rows are ranked by the fractional part discarded, descending, with ties broken by weight descending and then by the row's `created_at` ascending, and one extra cent is given to each of the leading rows until the residual is exhausted. The result is written to `admin_funds_base_cents`.

**Step three — the recordkeeping withholding.** A row whose `record_compliance_pct` is below the 0.9500 compliance minimum has 10 percent of its `admin_funds_base_cents` withheld, with the fractional part discarded, written to `admin_funds_withheld_cents`; a compliant row has `admin_funds_withheld_cents` of 0. **This test reads only the step-two figures and is never re-evaluated against the post-redistribution award of step five.**

**Step four — redistributing the withheld pool.** The withheld pool is the sum of every row's `admin_funds_withheld_cents`. The recipients are the rows whose withholding came to zero; if no row is compliant, the recipient set falls back to *all* rows of the cycle. The recipient base total is the sum of `admin_funds_base_cents` over the recipient set. Each recipient's exact redistribution share is the withheld pool multiplied by that recipient's `admin_funds_base_cents` and divided by the recipient base total, taken as zero when that total is zero; its floored share discards the fractional part, and non-recipients receive nothing. The redistribution residual is the withheld pool minus the sum of the floored shares. The recipients are ranked by the fractional part discarded, descending, with ties broken by `admin_funds_base_cents` descending and then by `created_at` ascending, and one extra cent is given to each of the leading recipients until that residual is exhausted.

**Step five — the final award.** Each row's `admin_funds_cents` is its `admin_funds_base_cents` less its `admin_funds_withheld_cents` plus its redistribution share.

**Step six — the fiscal invariant.** The sum of `admin_funds_cents` across the cycle's rows equals the cycle's `admin_funds_pool_cents` exactly, in cents, and the cycle's `admin_funds_allocated_cents` is written from that sum. Every entitlement row of the cycle then moves to `status` `RECONCILED`.

A computed read is available afterwards that reconciles the whole pool for audit. It answers with the cycle's `cycle_code`, its `admin_funds_pool_cents` and `admin_funds_allocated_cents`, a `withheld_cents_total` summing every row's withholding, a `redistributed_cents_total` summing every redistribution share paid out, an `allocation_line_count` counting the cycle's entitlement rows, and a `non_compliant_line_count` counting the rows that suffered a withholding.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — a service area, an agency, a commodity, a warehouse, an inventory lot, an allocation cycle, an order, an order line, a delivery appointment, an inventory transfer, a recall, a recall action created by expansion, a household distribution, and the agreement-renewal and civil-rights-training records that write onto an agency — return `201 Created`. Operations that modify existing state, including every state-machine action, every operational checkpoint run, every `PATCH`, and the logical-clock setter, return `200 OK`. All reads return `200 OK`. An "Any" entry in the authorised-roles column means all four roles — `StateAdmin`, `ComplianceReviewer`, `AgencyCoordinator`, and `StateWarehouseOperator` — are permitted.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/efap/_clock/set_current_utc` | Set the logical clock used by every deadline, expiry, order-window, dock-window and age rule | StateAdmin |
| GET | `/efap/_clock/current` | Read the logical clock | Any |
| POST | `/efap/service-areas` | Register a service area with its poverty population | StateAdmin |
| GET | `/efap/service-areas` | List service areas | Any |
| GET | `/efap/service-areas/{service_area_id}` | Read one service area including its live eligible agency count | Any |
| PATCH | `/efap/service-areas/{service_area_id}` | Revise a service area's poverty population or urban/rural designation | StateAdmin |
| POST | `/efap/agencies` | Register an emergency feeding organization | StateAdmin |
| GET | `/efap/agencies` | List agencies, filterable by service area, either state axis, or the derived posture | Any |
| GET | `/efap/agencies/{agency_id}` | Read one agency including both state axes and the derived posture | Any |
| PATCH | `/efap/agencies/{agency_id}` | Revise an agency's cold storage capacity and prior-period baselines | StateAdmin |
| POST | `/efap/agencies/{agency_id}/agreement-renewals` | Approve or renew the agency agreement | ComplianceReviewer |
| POST | `/efap/agencies/{agency_id}/civil-rights-trainings` | Record a civil rights training session | ComplianceReviewer |
| GET | `/efap/agencies/{agency_id}/allocations` | List every entitlement held by this agency across cycles | Any |
| POST | `/efap/compliance-sweeps` | Operational checkpoint expiring agreements, lapsing training and terminating agreements past grace | StateAdmin |
| POST | `/efap/commodities` | Register a federal commodity; immutable once created | StateAdmin |
| GET | `/efap/commodities` | List commodities | Any |
| GET | `/efap/commodities/{commodity_id}` | Read one commodity | Any |
| POST | `/efap/warehouses` | Register a state warehouse with dock count, three capacity pools and its monitor policy | StateAdmin |
| GET | `/efap/warehouses` | List warehouses | Any |
| GET | `/efap/warehouses/{warehouse_id}` | Read one warehouse | Any |
| PATCH | `/efap/warehouses/{warehouse_id}` | Revise dock count, any capacity pool, or the monitor policy flag | StateAdmin |
| POST | `/efap/inventory-lots` | Record receipt of a federal commodity entitlement into a warehouse | StateAdmin |
| GET | `/efap/inventory-lots` | List lots, filterable by warehouse, commodity, holding recall, status and monitor flag | Any |
| GET | `/efap/inventory-lots/{inventory_lot_id}` | Read one lot including its committed cases, monitor flag and staleness index | Any |
| POST | `/efap/inventory-lots/{inventory_lot_id}/post` | Post a received lot to available, making its cases visible to reservation | StateAdmin |
| POST | `/efap/inventory-monitor-runs` | Operational checkpoint scoring available and watched lots for excess and slow movement | StateAdmin |
| POST | `/efap/allocation-cycles` | Open a distribution cycle in draft with its pools, offering, window and formula variant | StateAdmin |
| GET | `/efap/allocation-cycles` | List allocation cycles | Any |
| GET | `/efap/allocation-cycles/{cycle_id}` | Read one cycle including its allocated total, draw posture and administrative funds figure | Any |
| POST | `/efap/allocation-cycles/{cycle_id}/compute-allocations` | Run the allocation formula over every eligible agency, creating one entitlement per agency | StateAdmin |
| POST | `/efap/allocation-cycles/{cycle_id}/open-window` | Open the order window | StateAdmin |
| POST | `/efap/allocation-cycles/{cycle_id}/close-window` | Close the order window, cancelling the cycle's draft orders | StateAdmin |
| POST | `/efap/allocation-cycles/{cycle_id}/finalize` | Reconcile the cycle and allocate the administrative funds pool | StateAdmin |
| GET | `/efap/allocation-cycles/{cycle_id}/allocations` | List the entitlement rows created by this cycle | Any |
| GET | `/efap/allocation-cycles/{cycle_id}/admin-funds-report` | Computed read reconciling the administrative funds pool | Any |
| GET | `/efap/agency-allocations` | List entitlements, filterable by cycle, agency and draw status | Any |
| GET | `/efap/agency-allocations/{agency_allocation_id}` | Read one entitlement including every formula intermediate and funds figure | Any |
| POST | `/efap/commodity-orders` | Start a draft order against the agency's entitlement in a cycle | AgencyCoordinator |
| GET | `/efap/commodity-orders` | List orders, filterable by cycle, agency, warehouse and status | Any |
| GET | `/efap/commodity-orders/{order_id}` | Read one order including its totals and its revision and approval provenance | Any |
| POST | `/efap/commodity-orders/{order_id}/lines` | Add a line to a draft order | AgencyCoordinator |
| GET | `/efap/commodity-orders/{order_id}/lines` | List the lines of an order including their lot reservations | Any |
| POST | `/efap/commodity-orders/{order_id}/submit` | Submit a draft order for compliance review inside the cycle's order window | AgencyCoordinator |
| POST | `/efap/commodity-orders/{order_id}/return-for-revision` | Return a submitted order to draft, recording which reviewer returned it | ComplianceReviewer |
| POST | `/efap/commodity-orders/{order_id}/approve` | Approve a submitted order, converting cases to pounds and pallets and reserving lots | ComplianceReviewer |
| POST | `/efap/commodity-orders/{order_id}/cancel` | Cancel an order, releasing every lot and entitlement commitment it holds | AgencyCoordinator, StateAdmin |
| GET | `/efap/order-lines` | List order lines across orders, filterable by owning order and by commodity | Any |
| GET | `/efap/order-lines/{order_line_id}` | Read one order line including its conversion figures and lot reservations | Any |
| POST | `/efap/delivery-appointments` | Book a dock window for an approved order, running the three capacity tests | StateWarehouseOperator, StateAdmin |
| GET | `/efap/delivery-appointments` | List appointments, filterable by order, warehouse, agency and status | Any |
| GET | `/efap/delivery-appointments/{appointment_id}` | Read one appointment including its per-class pallet load and delivered pounds | Any |
| POST | `/efap/delivery-appointments/{appointment_id}/confirm-delivery` | Confirm delivery, debiting the reserved lots and driving the order, entitlement and cycle cascade | StateWarehouseOperator |
| POST | `/efap/delivery-appointments/{appointment_id}/cancel` | Cancel a scheduled or blocked appointment, releasing the dock window and pallet ceilings | StateAdmin |
| POST | `/efap/inventory-transfers` | Propose a transfer of uncommitted cases from a lot to an agency | StateAdmin |
| GET | `/efap/inventory-transfers` | List transfers, filterable by source lot, receiving agency and status | Any |
| GET | `/efap/inventory-transfers/{transfer_id}` | Read one transfer | Any |
| POST | `/efap/inventory-transfers/{transfer_id}/accept` | Accept a proposed transfer; the cases move from the lot to the agency | AgencyCoordinator |
| POST | `/efap/inventory-transfers/{transfer_id}/decline` | Decline a proposed transfer; the proposal's commitment is compensated away | AgencyCoordinator |
| POST | `/efap/recalls` | Raise a recall on a lot, holding covered lots and creating one action per exposed agency | StateAdmin |
| GET | `/efap/recalls` | List recalls, filterable by source lot, class and status | Any |
| GET | `/efap/recalls/{recall_id}` | Read one recall including its held-lot, acknowledgement and disposition counters | Any |
| POST | `/efap/recalls/{recall_id}/dispatch-notices` | Dispatch recall notices to every pending action | StateAdmin |
| POST | `/efap/recalls/{recall_id}/expand` | Add a newly discovered downstream agency to a monitoring recall | StateAdmin |
| POST | `/efap/recalls/{recall_id}/close` | Close a recall, releasing held lots or disposing them when any disposition was destruction | StateAdmin |
| GET | `/efap/recalls/{recall_id}/actions` | List the per-agency actions of a recall | Any |
| GET | `/efap/recall-actions` | List recall actions across recalls, filterable by recall, agency and status | Any |
| GET | `/efap/recall-actions/{recall_action_id}` | Read one recall action including its exposed cases and reported disposition | Any |
| POST | `/efap/recall-actions/{recall_action_id}/acknowledge` | Acknowledge a notified action | AgencyCoordinator |
| POST | `/efap/recall-actions/{recall_action_id}/report-disposition` | Report what happened to the agency's exposed cases | AgencyCoordinator |
| POST | `/efap/household-distributions` | Record a household distribution against the self-declaration income test | AgencyCoordinator |
| GET | `/efap/household-distributions` | List distribution records, filterable by agency, cycle, commodity and status | Any |
| GET | `/efap/household-distributions/{distribution_id}` | Read one distribution record including its income limit and determination | Any |
| POST | `/efap/household-distributions/{distribution_id}/void` | Void a recorded distribution, reversing every aggregate it contributed to | AgencyCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SERVICE_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_AGENCY_NOT_FOUND` | 404 Not Found |
| `ERR_COMMODITY_NOT_FOUND` | 404 Not Found |
| `ERR_WAREHOUSE_NOT_FOUND` | 404 Not Found |
| `ERR_INVENTORY_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_ACTION_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_INVALID_CYCLE_STATE` | 409 Conflict |
| `ERR_INVALID_LOT_STATE` | 409 Conflict |
| `ERR_INVALID_APPOINTMENT_STATE` | 409 Conflict |
| `ERR_INVALID_TRANSFER_STATE` | 409 Conflict |
| `ERR_INVALID_RECALL_STATE` | 409 Conflict |
| `ERR_INVALID_RECALL_ACTION_STATE` | 409 Conflict |
| `ERR_INVALID_DISTRIBUTION_STATE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_RENEWABLE` | 409 Conflict |
| `ERR_RECALL_HOLD_ACTIVE` | 409 Conflict |
| `ERR_RECALL_CASES_UNACCOUNTED` | 409 Conflict |
| `ERR_STORAGE_CLASS_UNSUPPORTED` | 422 Unprocessable Entity |
| `ERR_TRAINING_NOT_CURRENT` | 422 Unprocessable Entity |
| `ERR_AGENCY_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_HOUSEHOLD_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_COMMODITY_NOT_OFFERED` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ORDER_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_ORDER_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_RECALL_ALREADY_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_RECALL_ACTION` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_AGENCIES` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_WAREHOUSE_COLD_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_AGENCY_COLD_STORAGE_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_ALLOCATION_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LOT_CASES_UNAVAILABLE` | 409 Conflict |
| `ERR_AGENCY_INVENTORY_INSUFFICIENT` | 422 Unprocessable Entity |

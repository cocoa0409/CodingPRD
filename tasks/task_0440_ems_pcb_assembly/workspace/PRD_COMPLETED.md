# Ems Pcb Assembly API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a contract electronics manufacturing (EMS) shop floor that builds printed-circuit-board assemblies on behalf of customers. The platform threads together every stage of the build: the engineering definition of a product (its bill of materials and the approved vendors permitted to supply each component), the receipt and stocking of physical inventory lots, the planning and kitting of a production run, the setup of a surface-mount-technology (SMT) line, serialization of finished boards, automated optical and in-circuit test (AOI/ICT), rework of defective boards, and the eventual field return (RMA) of shipped product. Because a single defective component or an unapproved source can compromise an entire run — and because regulatory regimes such as RoHS and conflict-minerals reporting impose hard gates on what material may be consumed — the system treats compliance and traceability as first-class concerns rather than afterthoughts.

The reference web among these records is genuinely a graph, not a simple tree. A bill of materials line points at a part; a part is linked to many vendors through approval records and stocks many inventory lots; a kit requirement consumes lots that belong to a part across aggregate boundaries; finished units serialize against a work order; rework orders and field returns reference units and engineering change orders. The platform must keep all of these derived rollups — on-hand quantities, reserved and consumed material, build costs, yields, and rework counts — continuously reconciled as the underlying records mutate.

A second governing concern is the separation of responsibilities among the people who run the floor. The process engineer who authors and implements an engineering change cannot also be the quality engineer who approves it, and the operator who closes the rework an engineering change triggers cannot be the engineer who authored that change. These segregation-of-duties rules, together with optimistic-concurrency guards on the most contention-prone operations, ensure that the audit trail of who-did-what remains trustworthy even under concurrent edits.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque operator identifier, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` does not name one of the three known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles are spelled exactly `ProcessEngineer`, `ProductionPlanner`, and `QualityEngineer`. A `ProcessEngineer` owns the engineering definition of the shop: part master records, vendors, the approved-vendor list, bills of materials, SMT line programs, and the authoring, submission, and implementation of engineering change orders. A `ProductionPlanner` owns execution of a run: receiving inventory lots, creating and kitting work orders, line setup, starting the run, serializing units, closing, cancelling, and shipping work orders, executing rework, and routing field returns through repair and closure. A `QualityEngineer` owns quality gating: recording test results, finalizing test, quarantining lots, approving and rejecting engineering change orders, and receiving, triaging, and scrapping field returns. All three roles may call every read (GET) endpoint.

For all three roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any record's `id`. The server does, however, record it where a workflow demands an auditable actor: when a `ProcessEngineer` creates an engineering change order, the server stores the caller's `X-User-ID` as `authored_by_user_id` on that record, and when a `QualityEngineer` later approves it the caller's identifier is stored as `approved_by_user_id`. These stored identifiers are what the segregation-of-duties checks compare against — never an entity `id`. Two operations additionally accept an explicit `acting_user_id` field in the request body so that the acting identity is unambiguous at the point of an authorship or approval check, as described in the workflow sections below.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of records to skip. List results are always ordered by `created_at` ascending. For every list response, the `meta` object carries the effective `limit`, the effective `offset`, the `total_count` of records matching the query before pagination, and a `has_more` boolean that is true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, set once at creation. All entities in this system additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 and increments by exactly one on each mutation of that record. Whenever a transition or side effect described below changes a record, the reader should assume its `updated_at` is refreshed and its `version` advances by one, even where the prose does not restate it.

### 2.5. Monetary and Yield Precision

All monetary amounts in this system are integer cents — `standard_cost_cents`, `unit_cost_cents`, `material_cost_cents`, `added_material_cost_cents`, and `warranty_credit_cents` are all whole-cent integers and never carry a fractional component. Where a calculation multiplies an amount by a rate or factor and the result must be rounded back to whole cents, rounding is half-up to the nearest cent. Quantities — required, reserved, consumed, on-hand, and available — are integers with no rounding. The single percentage value in the system, `first_pass_yield_pct`, is carried to two decimal places, rounded half-up.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of a parent record. Both require the client to submit the `version` it last observed for that parent, and both reject the request if that submitted value does not equal the parent's current `version`.

Shipping the finished units of a work order requires the request to carry `expected_work_order_version`, which must equal the target work order's current `version`. If another writer has advanced the work order's version since the client last read it — for example by closing a rework on the same run, which legitimately advances the work order and can move a unit from `FAIL` to `REWORKED` and thereby change which units are shippable — the ship request is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), so the client cannot ship against a set of units it has not observed.

Receiving an inventory lot against an approved-vendor record requires the request to carry `expected_avl_entry_version`, which must equal that approval record's current `version`. If another writer has advanced the approval record's version since the client last read it — for example by revoking or otherwise mutating the approval — the receive request is rejected with `ERR_STALE_AVL_VERSION` (HTTP 412). No other operation accepts a version field; only these two carry an expected-version input.

### 2.7. Resource Resolution and Validation Ordering

When an operation can fail several checks, those checks are evaluated in a fixed priority order so that the reported error is deterministic. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a known but unpermitted role yields `ERR_FORBIDDEN`. The system then resolves path-referenced resources left to right; if any resource named in the URL path does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404). Next, every foreign-key reference supplied in the request body must resolve to an existing record; an unresolved body reference fails with `ERR_FK_NOT_FOUND` (HTTP 404). Then, for any state-transition operation, the target must currently be in a state from which the requested transition is defined; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409). Optimistic-concurrency version checks (the two described above) are evaluated after state validity. Business and safety rules — segregation of duties, RoHS, conflict minerals, approved-source gating, and the rest — follow. Finally, basic request-shape validation (required fields present, types and enums valid) yields `ERR_INVALID_REQUEST` (HTTP 400) when violated, and a generic business-rule violation not covered by a more specific code (such as a non-positive received quantity) yields `ERR_VALIDATION` (HTTP 422).

For nested list and fetch endpoints whose paths name a parent followed by a child collection or a child id, the parent segment is resolved before the child; a missing parent yields `ERR_NOT_FOUND` regardless of whether the child would have existed.

### 2.8. Compliance Gating: RoHS and Conflict Minerals

Two material-compliance gates protect every consumption of inventory. The first concerns the restriction of hazardous substances. A part whose `is_rohs_required` flag is set may only draw from lots whose `is_rohs_compliant` flag is set; if any lot that would be reserved or consumed for such a part is not RoHS compliant, the operation is rejected with `ERR_ROHS_VIOLATION` (HTTP 422). This gate applies in three places: when a work order is kitted, when a run is started, and when a rework order is closed. The second gate concerns conflict minerals. A part whose `contains_conflict_minerals` flag is set may only consume lots that carry a conflict-minerals reporting template, signalled by the lot's `has_cmrt` flag; consuming a lot that lacks the template fails with `ERR_CMRT_MISSING` (HTTP 422). The conflict-minerals gate applies at two consumption points: when a run is started and when a rework order is closed.

### 2.9. Inventory Rollups and Lot Lifecycle

Each part exposes two computed inventory rollups that the system keeps reconciled. `total_on_hand_qty` is the sum of `remaining_qty` across the part's lots whose `status` is either `AVAILABLE` or `QUARANTINED` — that is, all physical stock on the floor, excluding `DEPLETED` lots; it is recomputed on every lot mutation. `available_qty` is the sum of `remaining_qty` across the part's `AVAILABLE` lots only, minus the quantity currently reserved by open kit requirements; it is recomputed on every reserve, consume, and release. A lot begins life `AVAILABLE`. A quality engineer may quarantine an `AVAILABLE` lot, moving it to `QUARANTINED`; its `remaining_qty` then leaves the available pool but remains counted in on-hand stock, so quarantine recomputes the owning part's `available_qty` accordingly. A lot becomes `DEPLETED` automatically — not by an explicit call — the moment a consumption draw brings its `remaining_qty` to zero, at which point the owning part's `total_on_hand_qty` and `available_qty` are recomputed.

## 3. Business Logic & Workflows

### 3.1. Engineering Definition: Parts, Vendors, and the Approved-Vendor List

The engineering record begins with the part master. A `ProcessEngineer` creates a part by supplying its `internal_pn` — a manufacturer-agnostic internal part number that must be non-empty and unique across all parts — a human-readable `description`, a `package_type` drawn from the footprint families `0402`, `0603`, `0805`, `SOT23`, `QFN`, `BGA`, and `THT`, and a `standard_cost_cents` catalog cost that must be at least zero. Two compliance flags may be supplied: `is_rohs_required`, which defaults to true and indicates that only RoHS-compliant lots may ever be consumed for the part, and `contains_conflict_minerals`, which defaults to false and indicates that every consumed lot must carry a conflict-minerals declaration. A newly created part starts with `total_on_hand_qty` and `available_qty` both at zero.

Vendors are likewise created by a `ProcessEngineer`. A vendor carries a `name` that must be non-empty and unique, a `cage_code` commercial-and-government entity code, and an `is_rohs_certified` flag (default false) recording whether the vendor is certified to supply RoHS-compliant material. A vendor's `status` begins `ACTIVE`. A `ProcessEngineer` may suspend a vendor, moving its `status` to `SUSPENDED`; a suspended vendor can no longer back a lot receipt.

The bridge between parts and vendors is the approved-vendor list. A `ProcessEngineer` approves a part/vendor pairing by supplying the `part_id` being approved, the `vendor_id` of the approved source, that vendor's own `vendor_pn` for the part, and an `approval_rank` of at least 1, where rank 1 denotes the primary source and lower ranks are preferred when auto-selecting a source. An approval record's `status` begins `APPROVED`. A `ProcessEngineer` may revoke an approval, transitioning it from `APPROVED` to `REVOKED`; revocation is the only transition out of the approved state.

### 3.2. Receiving and Stocking Inventory

A `ProductionPlanner` receives physical material against an existing approval record, which is the operation guarded by optimistic concurrency described earlier. The request supplies a `lot_code` (the vendor lot or date code, which must be unique within the part), a `received_qty` that must be greater than zero, the actual `unit_cost_cents` paid for the lot (at least zero), and a `received_at` logical receipt timestamp that determines the lot's place in the first-in-first-out consumption order — the oldest `received_at` is consumed first. Two compliance attributes accompany the lot: `is_rohs_compliant` (default false), recording whether the physical material is RoHS compliant, and `has_cmrt` (default false), recording whether a conflict-minerals reporting template accompanies the shipment. The request also carries `expected_avl_entry_version` for the concurrency check. The receiving party need not name the part or the approval link in the body beyond the path: the new lot's `part_id` and `avl_entry_id` are both derived from the approval record named in the path.

Receiving is gated on the approval being usable. A lot may be received only when the approval record's `status` is `APPROVED` and the backing vendor's `status` is `ACTIVE`; a receipt against a revoked approval or a suspended vendor is rejected with `ERR_AVL_NOT_APPROVED` (HTTP 422). A successfully received lot is created with `remaining_qty` equal to its `received_qty` and `status` `AVAILABLE`, and the owning part's `total_on_hand_qty` and `available_qty` are recomputed; the receipt advances the approval record's `version` by one. The `remaining_qty` of a lot is, in general, its `received_qty` less the sum of every consumption charged against it, floored at zero.

### 3.3. Authoring and Releasing a Bill of Materials

A bill of materials defines what a product is built from. A `ProcessEngineer` creates one in `DRAFT` by supplying the `product_code` of the assembly being built, a `revision` label such as `A`, `B`, or `C` that must be unique within the product code, and optionally a `supersedes_bom_id` naming the prior revision this one replaces — the first revision leaves it null, later revisions chain backward through it to form a revision history. A new bill of materials starts with `line_count` zero.

The engineer then adds lines to the draft. Each line names the `part_id` placed at a set of `ref_designators` — a non-empty list of reference designator strings such as `R1`, `R2`, `R3`, each of which must be unique within the bill of materials — and a `qty_per_assembly` count of placements of that part per finished assembly, which must be greater than zero and must equal the number of reference designators supplied. If the placement count does not equal the length of the designator list, or a designator is duplicated within the bill of materials, the line is rejected with `ERR_DESIGNATOR_MISMATCH` (HTTP 422). A line may be flagged `is_dnp` (do-not-place, default false): a do-not-place line is documented but never placed and consumes no inventory. Each added line increments the bill of materials' `line_count` and advances its `version`. The line itself records the `bom_id` of the bill it belongs to.

Releasing a draft is the gate into production. A `ProcessEngineer` may release a bill of materials only while it is in `DRAFT`, only when it has at least one line, and only when every line's part has at least one approval record in `APPROVED` status. If some non-do-not-place line's part has no approved source, release is rejected with `ERR_NO_APPROVED_SOURCE` (HTTP 422). On a successful release the bill of materials transitions from `DRAFT` to `RELEASED`. Release also drives a two-hop cascade onto the revision it supersedes: if `supersedes_bom_id` is not null and that prior bill of materials is currently `RELEASED`, the prior bill transitions from `RELEASED` to `OBSOLETE`; and for that now-obsolete prior bill, every work order anchored to it that is still in `PLANNED` is set to `CANCELLED`, releasing any reservations those work orders held. `OBSOLETE` is the terminal state of a bill of materials and is reached only through this superseding cascade, never by a direct call.

### 3.4. SMT Line Programs

Before a run can be set up, the placement program for the SMT line must exist and be verified. A `ProcessEngineer` creates a line program targeting a particular `bom_id`, identified by a `line_code` such as `LINE-A`, occupying a stated `feeder_slot_count` of feeder slots that must be greater than zero, and carrying a `program_checksum` of the placement-program file used for setup verification. A line program's `status` begins `UNVERIFIED`. A `ProcessEngineer` verifies it, moving its `status` to `VERIFIED`; only a verified program may be assigned at setup.

### 3.5. Planning a Run: Work Orders and Kitting

A `ProductionPlanner` opens a run by creating a work order against a released bill of materials, supplying the `bom_id` and a `planned_qty` of finished assemblies that must be greater than zero; if the named bill of materials is not currently `RELEASED`, the request is rejected with `ERR_VALIDATION` (HTTP 422). A new work order starts `PLANNED` with its computed counters — `kit_shortage_count`, `built_qty`, `passed_qty`, `first_pass_yield_pct`, and `material_cost_cents` — all at zero, and its `line_program_id` null until setup. The work order anchors the released bill of materials whose `bom_id` it names.

Kitting is the first execution step. A `ProductionPlanner` may kit a work order only while it is `PLANNED` and only when its anchoring bill of materials is `RELEASED`. Kitting creates one kit requirement per distinct part that appears on a non-do-not-place line of the bill, each requirement recording its `work_order_id` and `part_id`. For each such part, the `required_qty` is computed by summing `qty_per_assembly` across every non-do-not-place line carrying that part (a part may appear on more than one line) to obtain the per-assembly placement count, then multiplying that per-assembly count by the work order's `planned_qty`. Do-not-place lines contribute nothing and create no kit requirement. The system then reserves material toward each requirement from the part's `AVAILABLE` lots in first-in-first-out order, oldest `received_at` first, populating each requirement's `reserved_qty` and setting its `status` to `RESERVED` when the requirement is fully covered or `SHORT` when the available stock is less than the `required_qty`. The work order's `kit_shortage_count` is recomputed as the number of requirements left `SHORT`.

Kitting must fully reserve every requirement. If any requirement cannot be fully reserved — that is, if `kit_shortage_count` is greater than zero — the work order remains `PLANNED` and the request is rejected with `ERR_KIT_SHORTAGE` (HTTP 409); only when no requirement is short does the work order transition from `PLANNED` to `KITTED`. The RoHS gate also applies here: if any lot that would be reserved for a part whose `is_rohs_required` flag is set is not RoHS compliant, kitting fails with `ERR_ROHS_VIOLATION` before the work order advances.

A work order that has not yet started may be cancelled by a `ProductionPlanner`. Cancelling a `PLANNED` work order simply transitions it to `CANCELLED`. Cancelling a `KITTED` work order additionally compensates the reservations it holds: every kit requirement in `RESERVED` status is set to `RELEASED` with its `reserved_qty` returned to zero, and the affected parts' `available_qty` is recomputed before the work order moves to `CANCELLED`. (As noted in the release cascade, a `PLANNED` work order on a superseded bill of materials is also cancelled automatically when that bill becomes obsolete.)

### 3.6. Setup, Start, and Material Consumption

Setting up a kitted run assigns the placement program. A `ProductionPlanner` may set up a work order only while it is `KITTED`, naming a `line_program_id` whose program is `VERIFIED` and whose own `bom_id` matches the work order's `bom_id`. If the named program is unverified or targets a different bill of materials, setup is rejected with `ERR_PROGRAM_NOT_READY` (HTTP 422). On success the work order records the assigned `line_program_id` and transitions from `KITTED` to `SETUP`.

Starting the run consumes the reserved material. A `ProductionPlanner` may start a work order only while it is `SETUP`. Starting charges each kit requirement's `consumed_qty` against the part's lots in first-in-first-out order — lots ordered by `received_at` ascending, with `created_at` ascending as the tie-break — decrementing each drawn lot's `remaining_qty` and setting each requirement's `status` to `CONSUMED`. Any lot whose `remaining_qty` reaches zero during this draw is set to `DEPLETED`, and the affected parts' `available_qty` and `total_on_hand_qty` are recomputed. The work order's `material_cost_cents` is then recomputed from the actual consumption (see below), and the work order transitions from `SETUP` to `RUNNING`. Both compliance gates apply at start: a RoHS-required part drawing a non-compliant lot fails with `ERR_ROHS_VIOLATION`, and a conflict-minerals part drawing a lot without a conflict-minerals template fails with `ERR_CMRT_MISSING`.

The consumed-material cost is the actual FIFO cost of what was drawn. Lot draws are taken in the pinned order — by `received_at` ascending, tie-broken by `created_at` ascending — and a single requirement may straddle several lots, with each straddle segment treated as a separate draw. The work order's `material_cost_cents` is the sum, over every lot draw, of the quantity drawn in that segment multiplied by that lot's `unit_cost_cents`; because every term is an integer-cent product, the sum is exact and no rounding is applied. This consumed-actual cost is distinct from the planning estimate that could be formed at kitting time, which would instead value each requirement's `required_qty` at the part's `standard_cost_cents`; the actual cost diverges from that catalog estimate whenever a consumed lot's `unit_cost_cents` differs from its part's `standard_cost_cents`.

### 3.7. Serialization and Test

Once a run is `RUNNING`, finished boards are serialized one at a time. Each serialization under a running work order mints a `serial_number` — a server-assigned, immutable traceability serial that is unique across all units — and creates a unit recording its `work_order_id`, with `quality_status` `BUILT` and `disposition` `IN_PROCESS`. Each serialization increments the work order's `built_qty`. When `built_qty` reaches `planned_qty` — every planned board serialized — the work order advances from `RUNNING` to `AT_TEST`.

A unit carries two independent dimensions that evolve in parallel on the same record: `quality_status`, which tracks test and rework outcomes across `BUILT`, `PASS`, `FAIL`, and `REWORKED`, and `disposition`, which tracks where the physical board is across `IN_PROCESS`, `SHIPPED`, `SCRAPPED`, and `RETURNED`. A `QualityEngineer` records an AOI/ICT result against a unit only while the unit is `BUILT` and its parent work order is `AT_TEST`. Recording a `PASS` result advances the unit from `BUILT` to `PASS` and recomputes the parent work order's `passed_qty` and `first_pass_yield_pct`. The `passed_qty` is the count of the work order's units whose `quality_status` is exactly `PASS`; units in `REWORKED` are not counted toward `passed_qty`. Recording a `FAIL` result requires a `defect_code` to be supplied; it advances the unit from `BUILT` to `FAIL`, stores the `defect_code`, and recomputes the parent's `first_pass_yield_pct`. The result is conveyed in the `result` field of the request; a `FAIL` without a `defect_code` is an invalid request.

First-pass yield measures how many boards passed cleanly on their first test. Let the tested population be the count of units under the work order whose `quality_status` is not `BUILT` — that is, units that have reached `PASS`, `FAIL`, or `REWORKED`. Let the first-pass population be the count of units whose `quality_status` is `PASS` and whose `rework_count` is zero — boards that passed on the very first test and were never reworked. The `first_pass_yield_pct` is the first-pass population divided by the tested population, multiplied by 100, carried to two decimal places and rounded half-up; when no units have been tested yet the value is zero. After each individual test result the tested population counts only the units tested so far, so the running value may sit above or below where it finally lands; at finalize-test the tested population equals `planned_qty`, and because reworked boards count in the tested population but never in the first-pass population, a run that reworked any failures finishes with a first-pass yield strictly below its eventual pass rate.

### 3.8. Finalizing Test and Closing the Run

A `QualityEngineer` finalizes testing once a run is `AT_TEST`. Finalization first recomputes the work order's `first_pass_yield_pct`, then branches on the outcome, testing the two branches in this order. If every unit under the work order has reached `quality_status` `PASS` or `REWORKED` — none remaining `BUILT` or `FAIL` — the work order transitions from `AT_TEST` to `PASSED` (this branch is evaluated first and applies regardless of the first-pass yield). Otherwise, if the recomputed `first_pass_yield_pct` is below the minimum acceptable first-pass yield of 70 percent, the work order transitions from `AT_TEST` to `FAILED`. These are the two finalize outcomes, each carrying equal weight in the contract: a clean run with no outstanding boards passes, and a run whose first-pass yield falls under the 70-percent floor fails. If neither branch applies — some unit remains `BUILT` or `FAIL` yet the recomputed first-pass yield is at or above the 70-percent floor — the finalize transition is not defined and the request is rejected with `ERR_INVALID_STATE` (HTTP 409), leaving the work order `AT_TEST`.

A `ProductionPlanner` may close a work order only while it is `PASSED`, and only when no rework order under that work order remains `OPEN`. If an open rework order still exists, closing is rejected with `ERR_OPEN_REWORK_BLOCKS_CLOSE` (HTTP 409). Closing transitions the work order from `PASSED` to `CLOSED`.

Shipping is the operation guarded by optimistic concurrency. A `ProductionPlanner` ships the finished, shippable units of a work order that is `PASSED` or `CLOSED`, supplying `expected_work_order_version`; shipping sets the `disposition` of every shippable unit (those whose `quality_status` is `PASS` or `REWORKED`) to `SHIPPED`. As described earlier, a mismatch between `expected_work_order_version` and the work order's current `version` rejects the request with `ERR_STALE_WORK_ORDER_VERSION`.

### 3.9. Rework: Engineering Change Orders and Defect Repair

An engineering change order governs design-level rework. A `ProcessEngineer` creates one in `DRAFT` by supplying a `title`, the `bom_id` the change targets, and a `change_summary`; the server records the caller as `authored_by_user_id`. The author submits it, moving it from `DRAFT` to `SUBMITTED`; submission is permitted only when the acting identity supplied as `acting_user_id` equals the recorded `authored_by_user_id`. A `QualityEngineer` then either approves or rejects the submitted change. Approval moves it from `SUBMITTED` to `APPROVED`, recording the approver's `acting_user_id` as `approved_by_user_id`, and is permitted only when that acting identity differs from `authored_by_user_id`; an approver who is the author is rejected with `ERR_SOD_VIOLATION` (HTTP 409). Rejection moves it from `SUBMITTED` to `REJECTED`. A rejected change is not dead: its author may resubmit it, moving it back from `REJECTED` to `SUBMITTED` under the same authorship check, forming the revise-and-resubmit cycle. Finally, a `ProcessEngineer` marks an `APPROVED` change `IMPLEMENTED`, its terminal state.

A rework order repairs a single defective board. A `ProductionPlanner` opens one by supplying the `unit_id` of the failed board, the `defect_code` being addressed, and optionally the `eco_id` of an engineering change authorizing the rework (null for ordinary non-engineering defect rework). A rework order may be opened only against a unit whose `quality_status` is `FAIL` or `REWORKED`; opening against a `PASS` or `BUILT` unit is rejected with `ERR_INVALID_STATE`. A new rework order starts `OPEN`.

Closing a rework order is the most cascade-heavy operation in the system. A `ProductionPlanner` may close a rework order only while it is `OPEN`, only against a target unit whose `quality_status` is `FAIL` or `REWORKED`, and — when the rework names an `eco_id` — only when that engineering change is `APPROVED` (otherwise `ERR_REWORK_ECO_NOT_APPROVED`, HTTP 422) and only when the acting `acting_user_id` differs from the linked change's `authored_by_user_id` (otherwise `ERR_SOD_VIOLATION`, HTTP 409). The close request supplies `replacement_part_id`, a `replacement_qty` that must be greater than zero (a non-positive `replacement_qty` is rejected with `ERR_VALIDATION`, HTTP 422), and the `acting_user_id`. On close, the system: computes the rework's `added_material_cost_cents` (see below); consumes the replacement material from the replacement part's lots in first-in-first-out order, decrementing each drawn lot's `remaining_qty`; sets any lot whose `remaining_qty` reaches zero to `DEPLETED` and recomputes the affected parts' `available_qty`; rolls the `added_material_cost_cents` into the parent work order's `material_cost_cents`; sets the target unit's `quality_status` to `REWORKED` and increments its `rework_count` by one; and finally sets the rework order's `status` to `CLOSED`. Both compliance gates apply to the replacement draw: a RoHS-required replacement part drawing a non-compliant lot fails with `ERR_ROHS_VIOLATION`, and a conflict-minerals replacement part drawing a lot without a template fails with `ERR_CMRT_MISSING`. When the target unit was already `REWORKED`, closing keeps it `REWORKED` and still increments `rework_count`; because the unit was already excluded from the first-pass population on its original failure, re-rework leaves `first_pass_yield_pct` unaffected.

Alternatively, a `ProductionPlanner` may abandon an `OPEN` rework order rather than close it. Abandoning sets the target unit's `disposition` to `SCRAPPED` and moves the rework order to `ABANDONED`, its other terminal state.

The rework cost is a base material cost plus a tiered handling surcharge. The base part cost is the sum, over every replacement lot draw (taken FIFO by `received_at` ascending, tie-broken by `created_at` ascending), of the quantity drawn multiplied by that lot's `unit_cost_cents`. The handling surcharge is then selected from the base part cost by tier: when the base part cost is 5,000 cents or less, the surcharge is a flat 1,500 cents; when the base part cost is from 5,001 cents through 20,000 cents inclusive, the surcharge is 20 percent of the base part cost, rounded half-up to whole cents; when the base part cost exceeds 20,000 cents, the surcharge is 30 percent of the base part cost, rounded half-up to whole cents. The tier boundaries are inclusive on their upper edge: a base part cost of exactly 5,000 cents takes the flat surcharge, and exactly 20,000 cents takes the 20-percent rate. The `added_material_cost_cents` is the base part cost plus the selected surcharge.

### 3.10. Field Returns (RMA)

A field return is opened by a `QualityEngineer` for a board that has actually shipped. The request supplies the `unit_id` and the customer's `reported_defect_code`; a return may be opened only for a unit whose `disposition` is `SHIPPED`, otherwise it is rejected with `ERR_UNIT_NOT_SHIPPED` (HTTP 422). A new return starts `RECEIVED` with `warranty_credit_cents` zero.

A `QualityEngineer` triages a `RECEIVED` return by assigning a `failure_class` — one of `WORKMANSHIP`, `COMPONENT`, `DESIGN`, or `NO_FAULT_FOUND` — which both moves the return from `RECEIVED` to `TRIAGED` and computes its `warranty_credit_cents`. The warranty credit is derived from the returned board's build cost. That per-unit build cost is the parent work order's `material_cost_cents` divided by its `built_qty`, using integer floor division. A credit factor is then applied by failure class: a `WORKMANSHIP` failure credits the full build cost (factor 1.00); a `COMPONENT` failure credits 0.60 of it; a `DESIGN` failure credits 0.80 of it; and a `NO_FAULT_FOUND` return credits nothing (factor 0.00, treated as customer error). The base credit is the build cost multiplied by the class factor, rounded half-up to whole cents. If the returned unit's `rework_count` is greater than zero, a rework penalty equal to 0.10 of the build cost — computed separately, rounded half-up to whole cents — is subtracted from that base credit; a unit that was never reworked incurs no penalty. The final `warranty_credit_cents` is the rounded base credit minus the rounded penalty (the penalty applying only when `rework_count` is positive), floored at zero so the credit is never negative.

From `TRIAGED`, the return forks. A `ProductionPlanner` routes it to repair, but only when the `failure_class` is not `NO_FAULT_FOUND`; a repair attempt on a `NO_FAULT_FOUND` return — a valid `TRIAGED` state for the transition, so this is a business-rule rejection rather than a state error — is rejected with `ERR_VALIDATION` (HTTP 422). Repair moves the return from `TRIAGED` to `REPAIRED` and, as a cross-entity cascade, sets the returned unit's `disposition` back to `IN_PROCESS` and its `quality_status` to `REWORKED`. Alternatively a `QualityEngineer` scraps a `TRIAGED` return, moving it from `TRIAGED` to `SCRAPPED` and setting the returned unit's `disposition` to `SCRAPPED`. A `ProductionPlanner` closes the return at the end: closing a `REPAIRED` return moves it to `CLOSED` and sets the returned unit's `disposition` back to `SHIPPED` (the board is re-shipped after repair), while closing a `SCRAPPED` return simply moves it to `CLOSED`. `CLOSED` is the return's terminal state.

### 3.11. Deterministic Build-and-Test Driver

For test and demonstration purposes, a `ProductionPlanner` may drive a `RUNNING` work order all the way to `AT_TEST` in a single call rather than hand-issuing every serialization and test. The driver names the `work_order_id`, a `pass_first_count` of units to mark `PASS` on the first test (leaving their `rework_count` at zero), a `rework_from_fail_count` of units to fail and then immediately rework to `REWORKED` (each consuming one unit of `replacement_part_id` FIFO and ending with `rework_count` 1 via a non-engineering rework), and the `replacement_part_id` used for those reworks. Each count must be at least zero, and the sum of `pass_first_count` and `rework_from_fail_count` must equal the work order's `planned_qty`; a negative count or a sum that does not equal `planned_qty` is rejected with `ERR_VALIDATION` (HTTP 422). The driver serializes exactly `planned_qty` units, applies the described pass/fail-then-rework mix, recomputes `passed_qty`, `first_pass_yield_pct`, and `material_cost_cents`, and advances the work order from `RUNNING` to `AT_TEST` so that finalize-test can then branch on the resulting first-pass yield.

## 4. Endpoint Definitions

The general rule for status codes is that creating a brand-new resource returns 201, while fetches, list reads, and state-changing actions on an existing resource return 200. All endpoints emit the standard envelope of §2.2; request and response bodies are reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /parts | Create a part master record. | ProcessEngineer |
| GET | /parts/{id} | Fetch a part, including computed inventory rollups. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /parts | List parts (paginated). | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /vendors | Create a vendor. | ProcessEngineer |
| GET | /vendors/{id} | Fetch a vendor. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /vendors/{id}/suspend | Suspend a vendor; suspended vendors cannot back lot receipts. | ProcessEngineer |
| POST | /avl-entries | Approve a part/vendor pairing (add to AVL). | ProcessEngineer |
| GET | /avl-entries/{id} | Fetch an AVL entry. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /avl-entries | List AVL entries; filter by part_id or vendor_id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /avl-entries/{id}/revoke | Revoke an AVL approval. | ProcessEngineer |
| POST | /avl-entries/{id}/receive-lot | Receive an inventory lot against this approved pairing (OCC-guarded on the AVL entry version). | ProductionPlanner |
| GET | /inventory-lots/{id} | Fetch an inventory lot. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /inventory-lots | List inventory lots; filter by part_id or avl_entry_id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /inventory-lots/{id}/quarantine | Quarantine a lot so it cannot be reserved/consumed. | QualityEngineer |
| POST | /boms | Create a BOM (draft). | ProcessEngineer |
| GET | /boms/{id} | Fetch a BOM. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /boms | List BOMs; filter by supersedes_bom_id or product_code. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /boms/{id}/lines | Add a line to a draft BOM. | ProcessEngineer |
| GET | /boms/{id}/lines | List the lines of a BOM. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /bom-lines | List BOM lines; filter by part_id or bom_id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /bom-lines/{id} | Fetch a single BOM line by id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /boms/{id}/release | Release a draft BOM; cascades obsolescence onto the superseded revision. | ProcessEngineer |
| POST | /line-programs | Create an SMT line program (unverified). | ProcessEngineer |
| GET | /line-programs/{id} | Fetch a line program. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /line-programs | List line programs; filter by bom_id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /line-programs/{id}/verify | Verify a line program so it may be assigned at setup. | ProcessEngineer |
| POST | /work-orders | Create a work order against a RELEASED BOM. | ProductionPlanner |
| GET | /work-orders/{id} | Fetch a work order including computed rollups. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /work-orders | List work orders; filter by bom_id, line_program_id, or status. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /work-orders/{id}/kit | Kit the work order: build requirements, reserve material FIFO. | ProductionPlanner |
| POST | /work-orders/{id}/setup | Assign a VERIFIED line program; KITTED to SETUP. | ProductionPlanner |
| POST | /work-orders/{id}/start | Start the run: consume reserved material FIFO; SETUP to RUNNING. | ProductionPlanner |
| POST | /work-orders/{id}/units | Serialize one finished unit; advance to AT_TEST when fully built. | ProductionPlanner |
| GET | /work-orders/{id}/units | List the units of a work order. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /work-orders/{id}/kit-requirements | List the kit requirements of a work order. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /work-orders/{id}/finalize-test | Finalize testing: compute FPY, branch PASSED or FAILED. | QualityEngineer |
| POST | /work-orders/{id}/close | Close a PASSED work order. | ProductionPlanner |
| POST | /work-orders/{id}/cancel | Cancel a PLANNED or KITTED work order; releases reservations. | ProductionPlanner |
| POST | /work-orders/{id}/ship | Ship the PASS/REWORKED units (OCC-guarded on the work-order version). | ProductionPlanner |
| GET | /kit-requirements/{id} | Fetch a kit requirement. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /kit-requirements | List kit requirements; filter by part_id or work_order_id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /units/{id} | Fetch a unit by id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /units/{id}/test-result | Record an AOI/ICT test result; BUILT to PASS or FAIL. | QualityEngineer |
| POST | /rework-orders | Open a rework order against a FAIL or REWORKED unit. | ProductionPlanner |
| GET | /rework-orders/{id} | Fetch a rework order. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /rework-orders | List rework orders; filter by unit_id or eco_id. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /rework-orders/{id}/close | Close a rework: consume material, roll cost, mark unit REWORKED. | ProductionPlanner |
| POST | /rework-orders/{id}/abandon | Abandon a rework: scrap the unit. | ProductionPlanner |
| POST | /ecos | Create an ECO (draft); records the author. | ProcessEngineer |
| GET | /ecos/{id} | Fetch an ECO. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /ecos | List ECOs; filter by bom_id or status. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /ecos/{id}/submit | Submit a DRAFT or resubmit a REJECTED ECO (author only). | ProcessEngineer |
| POST | /ecos/{id}/approve | Approve a SUBMITTED ECO (not the author — SoD). | QualityEngineer |
| POST | /ecos/{id}/reject | Reject a SUBMITTED ECO. | QualityEngineer |
| POST | /ecos/{id}/implement | Mark an APPROVED ECO IMPLEMENTED. | ProcessEngineer |
| POST | /rmas | Open an RMA for a SHIPPED unit (field return). | QualityEngineer |
| GET | /rmas/{id} | Fetch an RMA. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| GET | /rmas | List RMAs; filter by unit_id or status. | ProcessEngineer, ProductionPlanner, QualityEngineer |
| POST | /rmas/{id}/triage | Triage an RMA: assign failure class, compute warranty credit. | QualityEngineer |
| POST | /rmas/{id}/repair | Route a TRIAGED RMA to repair; unit returns to process. | ProductionPlanner |
| POST | /rmas/{id}/scrap | Scrap a TRIAGED RMA unit. | QualityEngineer |
| POST | /rmas/{id}/close | Close a REPAIRED or SCRAPPED RMA. | ProductionPlanner |
| POST | /_test/build-and-test-units | Deterministically drive a RUNNING work order to AT_TEST with a precise yield mix. | ProductionPlanner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_WORK_ORDER_VERSION | 412 |
| ERR_STALE_AVL_VERSION | 412 |
| ERR_SOD_VIOLATION | 409 |
| ERR_ROHS_VIOLATION | 422 |
| ERR_CMRT_MISSING | 422 |
| ERR_AVL_NOT_APPROVED | 422 |
| ERR_DESIGNATOR_MISMATCH | 422 |
| ERR_NO_APPROVED_SOURCE | 422 |
| ERR_PROGRAM_NOT_READY | 422 |
| ERR_UNIT_NOT_SHIPPED | 422 |
| ERR_KIT_SHORTAGE | 409 |
| ERR_REWORK_ECO_NOT_APPROVED | 422 |
| ERR_OPEN_REWORK_BLOCKS_CLOSE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VALIDATION | 422 |

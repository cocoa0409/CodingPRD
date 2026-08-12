# Hospitality FF&E Procurement & Installation API — Product Requirements Document

## 1. Introduction

Renovating or launching a hotel under a brand flag is a capital exercise measured in thousands of line items: casegoods, lighting packages, textiles, decor, and appliances must be specified against brand standards, bid out to vendors, consolidated into freight, received at a warehouse, and installed room by room on a floor-by-floor schedule — all while the owner's funding envelope is watched line by line. Today this pipeline lives in spreadsheets and email threads, where a short shipment discovered at the dock, a disputed damage claim, or an owner change order silently invalidates budget math that nobody recomputes.

This document specifies the Hospitality FF&E Procurement & Installation API, the system of record for that pipeline. It governs purchase specification and brand-standard approval, vendor bidding with sample rounds and evaluated-cost award, freight consolidation and warehouse receiving with damage and shortage reconciliation, installation scheduling by floor with crew-capacity and room-turn rules, attic stock and spare inventory, dual budget-versus-actual reporting, and owner change orders drawn against contingency under segregation of duties. All resources are mounted under the `/api` prefix. The API's defining commitment is immediate, visible consistency: every receiving post, claim resolution, or applied change order recomputes the affected line, budget, and project aggregates within the same request's response, so no reader ever observes a stale budget position.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, resource metadata, money handling, concurrency control, the validation pipeline, and the cross-cutting financial and freight models that every workflow in §3 builds upon.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their capacity. The system recognizes exactly six roles, spelled as follows: `PurchasingAgent` (the hotel FF&E purchasing agent who owns the procure-to-install pipeline), `BrandApprover` (the brand-standard reviewer), `Vendor` (an external supplier who bids, acknowledges purchase orders, and disputes claims), `WarehouseReceiver` (consolidation warehouse staff who post receiving events and manage attic stock), `InstallationManager` (the field installation lead who manages rooms, windows, and room-turn tasks), and `OwnerRep` (the hotel owner representative who decides change orders). A request missing either header, or carrying a role outside these six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the endpoint — or for the specific transition target on a shared transition endpoint — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); for example, a `Vendor` attempting an award, a `PurchasingAgent` attempting a brand review or a change-order decision, or a `Vendor` attempting to resolve a claim. Per-target role rules apply on shared transition endpoints: only `Vendor` may move a purchase order's fulfillment axis to `ACKNOWLEDGED` or `READY_TO_SHIP`; on claim transitions, `PurchasingAgent` drives submission and all three resolutions while `Vendor` may only dispute; only `OwnerRep` may apply or reject a change order.

All six roles carry an **opaque operator identity**: `X-User-ID` is not the `id` of any persisted entity, for any role. The server never compares `X-User-ID` to a resource's `id` or foreign key. The single place an operator identity is persisted is the change-order workflow: when a change order is proposed, the server records the request's `X-User-ID` as the order's `proposer_user_id`, and segregation of duties later forbids that same user id from applying or rejecting the order — a self-decision attempt is rejected with `ERR_CHANGE_ORDER_SELF_APPROVAL` (HTTP 403). All read (GET) endpoints accept any of the six roles.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — projects, budget lines, spec items, bids, purchase orders, PO lines, shipments, receiving events, damage claims, rooms, installation windows, installation tasks, and change orders — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID used purely for identity; it carries no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource — including mutations caused by cascades originating on another resource.
- `version` (integer): starts at 1 at creation and increments by one on every mutation, again including cascaded mutations.

The one exception is the attic stock movement record, which is an append-only event: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it, it is immutable after creation, and no update endpoint exists for it.

### 2.5. Money, Units, and Rounding Discipline

All monetary values in the system — budgets, commitments, landed costs, freight, credits, fees — are represented as **integer cents**; there are no fractional-cent amounts anywhere in the API. Multiplications of integer-cent unit prices by integer quantities are exact and require no rounding. Where a computation can produce a fractional cent — the per-line freight shares at seal and at receipt, and the change-order draw fee — the result is rounded to whole cents using the **round half up** method. Attic target quantities are whole units; the raw target term is rounded up to the next whole unit (ceiling) before clamping. Cube volumes (`declared_cube_m3`, `total_cube_m3`) are integer cubic meters.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, each against a parent entity's `version`.

First, applying a change order requires the request body to carry `expected_project_version`, a non-optional field holding the project `version` the approver last observed. Since that read, a receiving-event post, a damage-claim resolution, or another applied change order may have advanced the project version by recomputing committed and actual totals and posture, so the funding check must run against a current view. If `expected_project_version` does not equal the project's current `version`, the apply is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

Second, recording an attic stock movement against a PO line requires the request body to carry `expected_po_line_version`, a non-optional field holding the line `version` the requester last observed. Receiving posts and installation-task completions silently change the line's pools and bump its version, so a transfer computed from a stale pool view must not apply blindly. If `expected_po_line_version` does not equal the line's current `version`, the transfer is rejected with `ERR_STALE_PO_LINE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.7. Existence Validation and Nested Resource Retrieval

For any endpoint whose path contains resource identifiers — path parameters such as `projectId`, `budgetLineId`, `specItemId`, `bidId`, `purchaseOrderId`, `poLineId`, `shipmentId`, `receivingEventId`, `damageClaimId`, `roomId`, `installationWindowId`, `installationTaskId`, `changeOrderId`, or a bare `id` — the server validates existence left to right and rejects immediately with the 404 error corresponding to the first identifier that does not resolve: `ERR_PROJECT_NOT_FOUND`, `ERR_BUDGET_LINE_NOT_FOUND`, `ERR_SPEC_ITEM_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_PO_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_RECEIVING_EVENT_NOT_FOUND`, `ERR_DAMAGE_CLAIM_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_INSTALLATION_WINDOW_NOT_FOUND`, `ERR_INSTALLATION_TASK_NOT_FOUND`, or `ERR_CHANGE_ORDER_NOT_FOUND`. The same 404 family applies to foreign keys supplied in request bodies — `project_id`, `spec_item_id`, `purchase_order_id`, `shipment_id`, `window_id`, `room_id`, `po_line_id`, and each `budget_line_id` inside a change order's `adjustments` — on creation and attach endpoints.

### 2.8. The Validation Pipeline

Every write request passes through a fixed, prioritized validation cascade; a failure at an earlier stage masks all later stages. The stages, in evaluation order, are:

1. **Authentication context** — both headers present and the role recognized, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization** — the role is permitted for this endpoint and, on shared transition endpoints, for the requested target state, else `ERR_UNAUTHORIZED_ROLE` (403). The segregation-of-duties bar on change-order decisions (`ERR_CHANGE_ORDER_SELF_APPROVAL`, 403) is enforced at this stage.
3. **Path existence** — path identifiers exist, validated left to right (404 family).
4. **Body reference existence** — foreign keys in the payload resolve (same 404 family).
5. **State preconditions** — the target entity's state machine permits the operation, including the procurement posture gates (`ERR_PROJECT_BUDGET_FROZEN` for `FROZEN`, `ERR_PROJECT_PROCUREMENT_SEALED` for `SEALED`), the project lifecycle gates (`ERR_NO_BUDGET_LINES`, `ERR_WINDOWS_OUTSTANDING`, `ERR_OPEN_CLAIMS_REMAIN`, `ERR_ACTIVE_POS_EXIST`), each machine's invalid-transition guard, the bid-intake gate (`ERR_SPEC_NOT_OPEN_FOR_BIDS`), the shipment attach gates (`ERR_SHIPMENT_NOT_CONSOLIDATING`, `ERR_PO_NOT_READY_TO_SHIP`), and the receiving-event gate (`ERR_SHIPMENT_NOT_IN_TRANSIT`). All stage-5 failures carry 409. Where one request depends on two states, the order is pinned: attaching a purchase order to a shipment checks the shipment's state before the purchase order's, and when both posture errors could apply, `FROZEN` is reported before `SEALED`.
6. **Optimistic concurrency** — the two OCC checks of §2.6 (412).
7. **Brand-standard gate** — the spec behind a new PO line must be `BRAND_APPROVED`, else `ERR_SPEC_NOT_BRAND_APPROVED` (409).
8. **Cross-entity referential consistency** — an awarded or ordered bid exists for the spec and the PO's vendor (`ERR_NO_AWARDED_BID`); an attached PO belongs to the shipment's project and a task's window, room, and line share one project and a change order's adjustments reference budget lines of its own project (`ERR_CROSS_PROJECT_REFERENCE`); every receiving-event entry names a line whose PO is attached to that shipment (`ERR_LINE_NOT_ON_SHIPMENT`). All 409.
9. **Uniqueness, caps, and quantity residuals** — one budget line per project and category (`ERR_DUPLICATE_BUDGET_CATEGORY`); one room per project and room number (`ERR_DUPLICATE_ROOM`); at most one non-cancelled PO line per spec item (`ERR_SPEC_ALREADY_ORDERED`); the sample-round cap (`ERR_SAMPLE_ROUNDS_EXHAUSTED`); claim residuals (`ERR_CLAIM_QTY_EXCEEDS_RESIDUAL`); pool sufficiency (`ERR_INSUFFICIENT_INSTALLABLE`, `ERR_INSUFFICIENT_ATTIC`); the attic target cap (`ERR_ATTIC_TARGET_EXCEEDED`); receipt bounds (`ERR_OVER_RECEIPT`, `ERR_DAMAGE_EXCEEDS_RECEIPT`); reversal guards (`ERR_CLAIMS_BLOCK_REVERSAL`, `ERR_REVERSAL_POOL_SHORTFALL`); the cross-axis guard (`ERR_INVOICE_BEFORE_DELIVERY`); the close guards (`ERR_INVOICE_NOT_PAID`, `ERR_LINES_NOT_RECONCILED`); the reconcile guards (`ERR_LINE_NOT_RECEIVED`, `ERR_LINE_SHORTFALL_OPEN`, `ERR_CLAIMS_OPEN`); lines before ready-to-ship (`ERR_PO_HAS_NO_LINES`); a non-empty shipment at seal (`ERR_SHIPMENT_EMPTY`); and the window task guards (`ERR_WINDOW_NO_TASKS`, `ERR_TASKS_OUTSTANDING`, `ERR_WINDOW_NOT_IN_PROGRESS`). Within attic transfers the order is pinned: pool sufficiency is checked **before** the target cap.
10. **Temporal rules** — window date sanity (`ERR_INVALID_WINDOW_DATES`, 422), room half-open overlap (`ERR_ROOM_WINDOW_OVERLAP`, 409), and floor crew capacity (`ERR_FLOOR_CREW_CAPACITY_EXCEEDED`, 409).
11. **Fiscal checks, always last** — the budget-line exposure gate at PO-line creation (`ERR_BUDGET_LINE_EXCEEDED`), the change-order funding check including the draw fee (`ERR_CHANGE_ORDER_UNFUNDED`), and the adjusted-lines obligations floor (`ERR_BUDGET_BELOW_OBLIGATIONS`). All three carry 402.

Malformed bodies — a missing required field, a wrong type, an enum value outside its declared set, a non-positive quantity, an `unallocated_contingency_cents` exceeding `total_budget_cents`, or a missing `approved_credit_cents` on a credit resolution — are rejected with `ERR_INVALID_REQUEST` (400).

### 2.9. Procurement Posture: OPEN, SEALED, and FROZEN

Each project carries a derived `procurement_posture`, recomputed after every mutation of its `committed_cents` or `actual_spend_cents` and whenever any of its installation windows enters or leaves `IN_PROGRESS`. The derivation is: when the sum of `committed_cents` and `actual_spend_cents` is **strictly greater than** `total_budget_cents`, the posture is `FROZEN` — equality with the total budget is *not* frozen. Otherwise, when any installation window of the project is `IN_PROGRESS`, the posture is `SEALED`. Otherwise the posture is `OPEN`.

Posture gates new spend: creating a purchase order, adding a line to a purchase order, and awarding a bid each require the project's posture to be `OPEN`. A `FROZEN` project rejects these with `ERR_PROJECT_BUDGET_FROZEN`; a `SEALED` project rejects them with `ERR_PROJECT_PROCUREMENT_SEALED`; when both conditions hold, the frozen error is reported first. A budget-raising applied change order can restore headroom and lift `FROZEN`.

### 2.10. The Budget Ledger and Its Two Variance Views

Every budget line maintains two accumulators and two variance views, and the project rolls the accumulators up.

A line's `committed_cents` is the sum, over every PO line whose spec's category equals the budget line's category, whose own status is not `CANCELLED`, and whose purchase order's `fulfillment_status` is one of `ISSUED`, `ACKNOWLEDGED`, `READY_TO_SHIP`, or `CONSOLIDATED`, of that PO line's `extended_cents` plus its `freight_alloc_provisional_cents`. Purchase orders that have reached `DELIVERED` or `CLOSED` drop out of the committed view; cancelled lines never count.

A line's `actual_cents` is the sum, over PO lines of the category that are not `CANCELLED` and have `qty_received` greater than zero, of each line's `actual_landed_cents`. A line's `actual_landed_cents` is its `qty_received` multiplied by its `unit_price_cents`, plus its freight allocation — the final allocation `freight_alloc_final_cents` once it has been assigned, otherwise the provisional `freight_alloc_provisional_cents` — minus its `damage_credit_cents`.

The two variances serve different reports. `variance_commitment_cents` is `budgeted_cents` minus `committed_cents` minus `actual_cents`: the forward-looking exposure view used by the budget gate at PO-line creation. `variance_final_cents` is `budgeted_cents` minus `actual_cents`: the reconciled view, which ignores open commitments entirely. Two identical datasets therefore show different variances whenever any purchase order is still open. At the project level, `committed_cents` is the sum of the budget lines' `committed_cents`, and `actual_spend_cents` is the sum of their `actual_cents`.

These figures are recomputed on every mutation that touches their input set: adding a PO line, cancelling a PO, sealing a shipment (provisional freight), posting or reversing a receiving event, resolving a claim for credit, or applying a change order (which moves `budgeted_cents`, after which both variances of each mutated line are recomputed).

### 2.11. Freight Mode and Allocation Economics

Freight economics are decided twice for each shipment: provisionally when the shipment is sealed, and finally when it is received.

At seal, the shipment's `freight_mode` is `FCL` when its `total_cube_m3` — the sum of the `total_cube_m3` of its attached purchase orders — is at least 67 cubic meters; below that threshold the mode is `LTL`. The `freight_total_cents` is a flat 480000 cents for `FCL`; for `LTL` it is 9000 cents per cubic meter multiplied by `total_cube_m3`. Both `freight_mode` and `freight_total_cents` remain null until the shipment is sealed.

The **provisional allocation** distributes `freight_total_cents` across every non-cancelled PO line of every attached purchase order in proportion to declared cube: each line's raw share is the total freight multiplied by the line's `declared_cube_m3` divided by the sum of `declared_cube_m3` over all lines in the allocation set. Each line's share is rounded half-up to whole cents **first**; the signed residual — the total freight minus the sum of the rounded shares — is then added to the line with the largest raw (unrounded) share, with ties broken by the earliest line `created_at`. Rounding each line before reconciling the residual is the pinned order; summing first and rounding once is not the contract and yields different cents. The result is stored on each line as `freight_alloc_provisional_cents`.

The **final allocation** runs at receipt with the identical procedure, except the basis is received units: each line's raw share uses its `qty_received` divided by the sum of `qty_received` over the allocation set, and the result is stored as `freight_alloc_final_cents`. If no units were received at all — the sum of `qty_received` is zero — every line's final allocation is zero and the freight total is dropped from actuals, since no line received anything to absorb it. The allocation set in both variants is all non-cancelled PO lines of all purchase orders attached to the shipment (those purchase orders are `CONSOLIDATED`, or `DELIVERED` after receipt). The same shipment yields different per-line freight under the two variants whenever declared cube proportions differ from received-unit proportions; at receipt, `actual_landed_cents` and each budget line's `actual_cents` switch to the final basis.

### 2.12. Cascading Recompute and Immediate Consistency

The system's consistency model is immediate: every cascade and recompute triggered by an operation is fully applied before the response is returned, and is visible in that response. Mutations propagate along fixed chains — a receiving post mutates its lines, which mutates the affected budget lines, which mutates the project's aggregates and posture; a shipment receipt mutates its purchase orders, their lines, the budget lines, and the project in five ordered links; a change-order apply mutates budget lines, contingency, and posture. Every resource mutated along such a chain — not just the resource named in the request — has its `updated_at` refreshed and its `version` incremented by one. Derived fields (`committed_cents`, `actual_cents`, both variances, project rollups, `actual_landed_cents`, `attic_target_qty`, `procurement_posture`, shipment and PO totals) are never set by clients; they are recomputed by the server per the rules in this section and §3.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Project and Its Budget Envelope

A `PurchasingAgent` opens an engagement by creating a project with a `name`, the `hotel_name` of the property, the `brand_program` it is flagged under — one of `MARQUEE_SELECT`, `MARQUEE_LUXE`, or `INDIE_SOFT` — and the owner-approved funding envelope `total_budget_cents`, which must be strictly positive. Two optional knobs complete the envelope: `unallocated_contingency_cents`, the contingency not yet drawn into any budget line, defaults to 0 and must be at least 0 and no more than `total_budget_cents`; and `default_crew_capacity_per_floor_day`, the maximum summed crew count allowed across overlapping installation windows on one floor per calendar day, defaults to 8 and must be at least 1. A new project starts in `PLANNING` status with `procurement_posture` `OPEN` and all aggregates — `committed_cents`, `actual_spend_cents`, `sunk_fees_cents` — at zero. The project list endpoint supports a `status` query filter alongside the standard `limit` and `offset` parameters.

With the envelope declared, the `PurchasingAgent` carves it into budget lines, each naming its `project_id`, a `category` — one of `FURNITURE`, `LIGHTING`, `TEXTILES`, `DECOR`, `APPLIANCES`, `FREIGHT`, or `INSTALLATION` — and its `budgeted_cents`, which must be at least 0. The category is unique per project: a second line in the same category is rejected with `ERR_DUPLICATE_BUDGET_CATEGORY`. A fresh line's `committed_cents` and `actual_cents` initialize to zero and its variances derive per §2.10. A line's `budgeted_cents` is thereafter mutated only by applied change orders.

The project lifecycle is driven by the `PurchasingAgent` naming a `to_status`. From `PLANNING`, the project may advance to `PROCUREMENT`, which requires at least one budget line to exist — otherwise `ERR_NO_BUDGET_LINES` — and recomputes the posture. From `PROCUREMENT` it may advance to `INSTALLATION` with no further preconditions, again recomputing posture. From `INSTALLATION` it may reach `COMPLETED` only when no installation window remains in `PLANNED`, `RELEASED`, or `IN_PROGRESS` (otherwise `ERR_WINDOWS_OUTSTANDING`) and no damage claim remains in `OPEN`, `SUBMITTED`, or `DISPUTED` (otherwise `ERR_OPEN_CLAIMS_REMAIN`); on completion, every spec item still `BRAND_APPROVED` is locked to `LOCKED`. Cancellation is available from `PLANNING` or `PROCUREMENT`, and only while no purchase order of the project sits in `READY_TO_SHIP`, `CONSOLIDATED`, `DELIVERED`, or `CLOSED` (otherwise `ERR_ACTIVE_POS_EXIST`); the cancellation cascade moves every purchase order in `ISSUED` or `ACKNOWLEDGED` to `CANCELLED`, moves all of their non-cancelled lines to `CANCELLED`, and recomputes each budget line's `committed_cents` — cancelled lines drop out of the sum — along with the project rollup and posture. Any `to_status` that is not a legal next state from the project's current state — including every transition out of the terminal `COMPLETED` or `CANCELLED` states, and skips such as `PLANNING` directly to `INSTALLATION` — is rejected with `ERR_INVALID_LIFECYCLE_TRANSITION` (409).

### 3.2. Purchase Specifications and the Brand-Standard Review Loop

Work on the buy side begins with spec items. A `PurchasingAgent` authors each spec against its `project_id` and `category`, supplying the purchase specification `description`, the `brand_standard_ref` code under review, the `quantity_per_room` (at least 1), the `room_count` it covers (at least 1; later adjusted by applied change orders), and the `unit_budget_cents` (at least 1). The derived `total_qty` is the product of `quantity_per_room` and `room_count`. Procurement parameters round out the spec: `required_lead_days`, the latest acceptable vendor lead time before a penalty applies in bid evaluation, defaults to 21 and must be at least 0; `is_critical` defaults to false and marks a critical-path item whose attic raw target is doubled; `attic_target_pct`, the fraction of installed quantity targeted as attic spares, defaults to 0.05 and must be greater than 0 and at most 1; `attic_min_qty` defaults to 0; and `attic_max_qty` defaults to 9999 and must be at least `attic_min_qty`. A new spec starts `DRAFT` with `attic_target_qty` at zero. Before any purchase order line can be added for a spec, the spec's category must correspond to a budget line of the same project, since the fiscal gate is measured against that line's `budgeted_cents`.

Submission moves a spec from `DRAFT` to `SUBMITTED`; the same action resubmits a spec from `BRAND_REJECTED` back to `SUBMITTED`, closing the revision loop, and the loop is unbounded. From any other state the attempt fails with `ERR_SPEC_NOT_SUBMITTABLE`. The `BrandApprover` then records a brand-standard `decision` of `APPROVE` or `REJECT`, with optional `notes`, on a spec currently `SUBMITTED` — otherwise `ERR_SPEC_NOT_IN_REVIEW` — moving it to `BRAND_APPROVED` or `BRAND_REJECTED` respectively. Approval is what opens the spec to bids and, later, to ordering. When the owning project finally reaches `COMPLETED`, the system automatically moves every spec still `BRAND_APPROVED` to the terminal `LOCKED` state.

### 3.3. Vendor Bids, Sample Rounds, and the Award

A `Vendor` submits a bid against a spec by naming the `spec_item_id`, its own `vendor_name` identity label, a `unit_price_cents` (at least 1), a `freight_estimate_cents` covering the full spec quantity (at least 0), and a `lead_time_days` (at least 0). Bids are accepted only against `BRAND_APPROVED` specs; anything earlier is rejected with `ERR_SPEC_NOT_OPEN_FOR_BIDS`. The bid opens in `SUBMITTED` with `sample_round` at 1.

Every bid carries an `evaluated_cost_cents`, computed whenever the bid is read and again at award time. It is the bid's `unit_price_cents` multiplied by the spec's `total_qty`, plus the `freight_estimate_cents`, plus a lead-time penalty of 25000 cents for each day by which `lead_time_days` exceeds the spec's `required_lead_days` — a bid at or under the required lead time pays no penalty.

The `PurchasingAgent` rules on the current sample round with an `outcome` of `APPROVED` or `REJECTED`, legal only while the bid is `SUBMITTED` (otherwise `ERR_BID_NOT_SUBMITTED`), moving it to `SAMPLE_APPROVED` or `SAMPLE_REJECTED`. A rejected vendor may resubmit: from `SAMPLE_REJECTED` only (otherwise `ERR_BID_NOT_RESUBMITTABLE`), and only while `sample_round` is still below the hard cap of 2 — a resubmit attempted at round 2 fails with `ERR_SAMPLE_ROUNDS_EXHAUSTED`, so the sample negotiation cycle `SUBMITTED` to `SAMPLE_REJECTED` to `SUBMITTED` permits at most one resubmit. Resubmission increments `sample_round` by one, replaces any of `unit_price_cents`, `freight_estimate_cents`, or `lead_time_days` that are provided, and recomputes `evaluated_cost_cents`.

Award is the contested transition, and its checks run in a pinned order. First, the bid being awarded must itself be `SAMPLE_APPROVED`, else `ERR_BID_NOT_SAMPLE_APPROVED`. Second, the project's posture must be `OPEN`, per the §2.9 gate. Third, the bid must be the top-ranked eligible bid: among all `SAMPLE_APPROVED` bids for the same `spec_item_id`, the lowest `evaluated_cost_cents` wins, with ties broken by the earliest bid `created_at`; any other bid is rejected with `ERR_BID_NOT_BEST_EVALUATED`. The eligible pool is never empty at award time, because the bid under award has already passed the state check and is therefore in the pool. A successful award moves the bid to `AWARDED` and the system immediately moves every sibling bid of the same spec sitting in `SUBMITTED` or `SAMPLE_APPROVED` to `REJECTED`. Finally, when a purchase order line is created against the awarded bid's spec and vendor, the bid advances automatically from `AWARDED` to `ORDERED`, its terminal state alongside `REJECTED`.

### 3.4. Purchase Orders on Two Independent Axes

A `PurchasingAgent` places a purchase order with a vendor by supplying the `project_id` and the `vendor_name`; creation requires the posture gate of §2.9. A new PO opens with `fulfillment_status` `ISSUED` and `invoice_status` `UNBILLED` — two independent axes evolving on the same row — and with `total_extended_cents` and `total_cube_m3` at zero, derived as the sums of `extended_cents` and `declared_cube_m3` over its non-cancelled lines.

Lines are added with a `spec_item_id`, a `quantity_ordered` (at least 1), and a `declared_cube_m3` (at least 1) used for the consolidation threshold and provisional freight allocation. A chain of gates guards the add. The posture must be `OPEN`. The spec must be `BRAND_APPROVED`, else `ERR_SPEC_NOT_BRAND_APPROVED`. A bid in `AWARDED` or `ORDERED` status must exist pairing that spec with the PO's `vendor_name`, else `ERR_NO_AWARDED_BID`. At most one non-cancelled line may exist for a spec across all purchase orders, else `ERR_SPEC_ALREADY_ORDERED`. The line's `unit_price_cents` is then copied from that awarded bid — never from the request — and its `extended_cents` is the exact product of `quantity_ordered` and `unit_price_cents`. Last in the pipeline comes the fiscal gate: the category's `committed_cents` plus the new line's `extended_cents` must remain at or below the budget line's `budgeted_cents`; a strictly greater result is rejected with `ERR_BUDGET_LINE_EXCEEDED` (402), while landing exactly on the budget is allowed. A successful add moves the sourcing bid from `AWARDED` to `ORDERED`, recomputes the category's and the project's `committed_cents`, recomputes the posture, and bumps the purchase order's `version`.

The fulfillment axis is walked by transition requests carrying an `axis` of `FULFILLMENT` and a `to_status`. A `Vendor` acknowledges an order, moving fulfillment from `ISSUED` to `ACKNOWLEDGED`, and later marks it from `ACKNOWLEDGED` to `READY_TO_SHIP`, which requires at least one non-cancelled line on the PO (else `ERR_PO_HAS_NO_LINES`). Attachment to a consolidating shipment then moves the PO automatically from `READY_TO_SHIP` to `CONSOLIDATED`, stamping its `shipment_id`. When that shipment reaches receipt, the system moves each attached PO from `CONSOLIDATED` to `DELIVERED` and finalizes every line's `qty_short` as its `quantity_ordered` minus its `qty_received`. A `PurchasingAgent` closes a delivered order — `DELIVERED` to `CLOSED` — only when the invoice axis already shows `PAID` (else `ERR_INVOICE_NOT_PAID`) and every line is `RECONCILED` or `CANCELLED` (else `ERR_LINES_NOT_RECONCILED`). Cancellation by a `PurchasingAgent` is legal from `ISSUED` or `ACKNOWLEDGED` and cascades: all non-cancelled lines move to `CANCELLED`, `committed_cents` is recomputed for the affected categories and the project, and the posture is recomputed. Any fulfillment request that is not legal from the current state is rejected with `ERR_INVALID_PO_TRANSITION`.

The invoice axis, walked with an `axis` of `INVOICE` and belonging to the `PurchasingAgent`, runs `UNBILLED` to `PARTIALLY_INVOICED` to `INVOICED` to `PAID`, with a direct hop from `UNBILLED` to `INVOICED` also legal. The single cross-axis guard sits at payment: `INVOICED` to `PAID` requires fulfillment to be `DELIVERED` or `CLOSED`, else `ERR_INVOICE_BEFORE_DELIVERY`. Otherwise the axes are genuinely independent — an order may be `INVOICED` while fulfillment is still `ISSUED`, or `ACKNOWLEDGED` while the invoice is `UNBILLED`; only `PAID` and `CLOSED` look across. Every transition on either axis bumps the PO's `version` and refreshes `updated_at`.

Each PO line tracks a family of quantity pools. `qty_received` accumulates posted receipts; `qty_damaged_unresolved` counts received-damaged units with no credit or replacement resolution yet; `qty_damaged_credited` counts damaged units covered by a resolved claim; `qty_short` is finalized at shipment receipt; `qty_installed` counts units consumed by completed installation tasks; `qty_attic` counts units held as attic stock; and `qty_installable` — the units available for installation or attic transfer — is what remains: `qty_received` less `qty_damaged_unresolved`, less `qty_damaged_credited`, less `qty_installed`, less `qty_attic`. A line's lifecycle is driven automatically by receipts: from `OPEN` to `PARTIALLY_RECEIVED` when a posted event leaves the cumulative `qty_received` below `quantity_ordered`, and to `FULLY_RECEIVED` when it reaches it exactly; a later post moves `PARTIALLY_RECEIVED` to `FULLY_RECEIVED`. Reversal reopens a line — `FULLY_RECEIVED` falls back to `PARTIALLY_RECEIVED`, and when all receipts are reversed the line returns to `OPEN`. Lines are also cancelled automatically — from `OPEN` when the owning PO or project is cancelled, and from `PARTIALLY_RECEIVED` when the owning project is cancelled, since a PO-level cancel requires no receipts in flight.

### 3.5. Freight Consolidation and Warehouse Receiving

A `PurchasingAgent` opens a consolidation shipment with its `project_id` and the `carrier_name`; it starts `PLANNED`. From `PLANNED` the agent moves it to `CONSOLIDATING`, which unlocks attach: a purchase order named by `purchase_order_id` may be attached while the shipment is `CONSOLIDATING` — checked first, else `ERR_SHIPMENT_NOT_CONSOLIDATING` — and while the PO itself is `READY_TO_SHIP` — checked second, else `ERR_PO_NOT_READY_TO_SHIP`; the two must belong to the same project, else `ERR_CROSS_PROJECT_REFERENCE`. Attachment moves the PO from `READY_TO_SHIP` to `CONSOLIDATED`, sets its `shipment_id`, bumps its `version`, and refreshes the shipment's `total_cube_m3`.

Sealing the shipment — `CONSOLIDATING` to `SEALED` — requires at least one attached PO (else `ERR_SHIPMENT_EMPTY`) and triggers the freight computation of §2.11: `freight_mode` and `freight_total_cents` are fixed, and every attached line receives its `freight_alloc_provisional_cents` by declared-cube share with the residual reconciled to the largest raw share. Because provisional freight enters the committed sum, sealing recomputes `committed_cents` for every affected budget category and the project, and recomputes the posture; the shipment's `version` bumps. Departure moves `SEALED` to `IN_TRANSIT`.

Arrival — `IN_TRANSIT` to `RECEIVED` — is the heaviest transition in the system. It requires at least one posted receiving event on the shipment (else `ERR_NO_RECEIPTS_POSTED`) and no receiving event still in `DRAFT` (else `ERR_DRAFT_EVENTS_OUTSTANDING`). It then runs a five-link cascade, each link visible in the same response. Link 1: every attached PO in `CONSOLIDATED` moves to `DELIVERED`, bumping each PO's `version`. Link 2: each delivered PO finalizes its lines — `qty_short` becomes `quantity_ordered` minus `qty_received`, and a line whose shortfall is zero moves to `FULLY_RECEIVED` while one with a shortfall stays `PARTIALLY_RECEIVED`. Link 3: the final freight allocation is recomputed on the received-units basis and each line's `freight_alloc_final_cents` is set. Link 4: each mutated line's `actual_landed_cents` is recomputed, and `actual_cents` plus both variances are recomputed for the affected budget categories. Link 5: the project's `actual_spend_cents` and `procurement_posture` are recomputed. The shipment's `version` bumps. Any shipment move that is not legal from its current state — sealing from `PLANNED`, departing from `CONSOLIDATING`, receiving from `SEALED`, or cancelling from `SEALED` — is rejected with `ERR_INVALID_SHIPMENT_TRANSITION`. Cancellation is available from `PLANNED` or `CONSOLIDATING`; it detaches everything: attached POs fall back from `CONSOLIDATED` to `READY_TO_SHIP` with their `shipment_id` cleared, `committed_cents` is recomputed, and the shipment's `version` bumps.

Warehouse intake is recorded by a `WarehouseReceiver` as receiving events. Creation names the `shipment_id` and a `lines` array whose entries each carry a `po_line_id`, a `qty_received` of at least 1, and a `qty_damaged` of at least 0. The cross-field bound that `qty_damaged` not exceed its entry's `qty_received` is not evaluated at creation — an entry in violation is accepted into the event and the bound is enforced later, at posting, per the next paragraph. The shipment must be `IN_TRANSIT` at creation, else `ERR_SHIPMENT_NOT_IN_TRANSIT`, and every entry's line must belong to a PO attached to that shipment, else `ERR_LINE_NOT_ON_SHIPMENT`. The event opens in `DRAFT` and mutates nothing yet.

Posting the event — `DRAFT` to `POSTED` — re-checks that the shipment is `IN_TRANSIT` and applies two per-entry guards: the cumulative `qty_received` over already-posted events for the line plus the new `qty_received` must not exceed the line's `quantity_ordered` (else `ERR_OVER_RECEIPT`, 422), and `qty_damaged` must not exceed `qty_received` within the entry (else `ERR_DAMAGE_EXCEEDS_RECEIPT`, 422). Receipts accumulate in event-posting order; the order determines only which event trips the over-receipt guard, never the totals. Each entry then mutates its line: `qty_received` grows by the entry's received quantity, `qty_damaged_unresolved` grows by the damaged quantity, `qty_installable` grows by the difference between them, the line's status advances per the cumulative total, and the line's `version` bumps. Downstream, each mutated line's `actual_landed_cents`, the category's `actual_cents`, and the project's `actual_spend_cents` and posture are recomputed, and the event's own `version` bumps. An event transition that is not legal from its current state — re-posting, or reversing from `DRAFT` — fails with `ERR_INVALID_EVENT_TRANSITION`.

Reversal — `POSTED` to `REVERSED` — is the compensating path and is guarded accordingly. The shipment must still be `IN_TRANSIT` (else `ERR_SHIPMENT_NOT_IN_TRANSIT`). No claim on any covered line may be in `SUBMITTED`, `DISPUTED`, `RESOLVED_CREDIT`, `RESOLVED_REPLACEMENT`, or `DENIED` — such a claim blocks the reversal outright with `ERR_CLAIMS_BLOCK_REVERSAL` — while claims still `OPEN` are voided to `VOID` instead. And the pools must survive the subtraction: for each entry, `qty_installable` minus the entry's net receipt (its received minus its damaged) must remain at least zero given units already installed or moved to attic, else `ERR_REVERSAL_POOL_SHORTFALL`. The reversal then decrements `qty_received` and `qty_damaged_unresolved` by the event's quantities, decrements `qty_installable` by the net, recomputes the line status (a fully-received line falls back to `PARTIALLY_RECEIVED`, or to `OPEN` when nothing remains), bumps the line's `version`, and recomputes the budget and project actuals and posture; the event's `version` bumps.

### 3.6. Damage and Shortage Claims

When the dock reveals damage or a finalized shortfall, a `PurchasingAgent` files a claim naming the `po_line_id`, a `claim_type` of `DAMAGE` or `SHORTAGE`, a `quantity` of at least 1, and a `claimed_credit_cents` of at least 0. Each claim is bounded by a type-specific residual. For `DAMAGE`, the residual is the line's `qty_damaged_unresolved` minus the summed quantities of its non-terminal damage claims — those in `OPEN`, `SUBMITTED`, or `DISPUTED`. For `SHORTAGE`, the residual is the line's `qty_short` minus the summed quantities of its non-terminal shortage claims. A claim whose quantity is at most the residual is accepted — equality with the residual is allowed — while exceeding it is rejected with `ERR_CLAIM_QTY_EXCEEDS_RESIDUAL` (422). A new claim is `OPEN`, and its `approved_credit_cents` stays null unless a credit resolution sets it.

The claim lifecycle is a negotiation. The `PurchasingAgent` submits an `OPEN` claim, moving it to `SUBMITTED`; the `Vendor` disputes a `SUBMITTED` claim, moving it to `DISPUTED`; and the `PurchasingAgent` may submit again from `DISPUTED` — the `SUBMITTED`–`DISPUTED` cycle is unbounded. Three resolutions exist, all from `SUBMITTED` and all by the `PurchasingAgent`: resolution for credit, which requires `approved_credit_cents` to be provided and at least 0 (a missing value fails with `ERR_INVALID_REQUEST`); resolution by replacement; and denial. Any move not legal from the claim's current state — resolving from `OPEN`, disputing from `DISPUTED`, or anything out of a terminal state — fails with `ERR_INVALID_CLAIM_TRANSITION`.

Resolution for credit runs a three-link cascade. The approved amount is recorded on the claim; the line's `damage_credit_cents` grows by it; and when the claim is a damage claim, `qty_damaged_unresolved` falls by the claim's `quantity` while `qty_damaged_credited` rises by the same amount. The line's `actual_landed_cents` is then recomputed, the category's `actual_cents` and both variances follow, and the project's `actual_spend_cents` and posture follow them; the claim's `version` bumps. Resolution by replacement applies the same pool shift for damage claims — unresolved falls, credited rises — but changes no credit amounts, and bumps the claim's `version`. Denial changes no pools and no credits: the units remain damaged and uncredited, and only the claim's `version` bumps. Separately, whenever a posted receiving event covering a line is reversed, any claim still `OPEN` on that line is automatically voided to `VOID`.

Reconciliation closes the loop on a line. A `PurchasingAgent` may reconcile a line in `FULLY_RECEIVED` or `PARTIALLY_RECEIVED` — from any other state the attempt fails with `ERR_LINE_NOT_RECEIVED`. A `PARTIALLY_RECEIVED` line may reconcile only once its shipment has reached `RECEIVED`, so its shortfall is final; otherwise `ERR_LINE_SHORTFALL_OPEN`. And no claim on the line may remain in `OPEN`, `SUBMITTED`, or `DISPUTED`, else `ERR_CLAIMS_OPEN`. Success moves the line to `RECONCILED` and bumps its `version`. Recall from §3.4 that closing a purchase order additionally requires every line to be `RECONCILED` or `CANCELLED` with the invoice `PAID`.

### 3.7. Installation Scheduling, Windows, and Room Turns

The field side begins with rooms. An `InstallationManager` registers each room with its `project_id`, the `floor_number` it sits on (at least 1), a `room_number` unique within the project — a duplicate is rejected with `ERR_DUPLICATE_ROOM` — and a `room_type` of `GUEST_KING`, `GUEST_DOUBLE`, `SUITE`, `CORRIDOR`, or `LOBBY`.

Installation windows are planned per floor: `project_id`, `floor_number` (at least 1), a `start_date` and an `end_date` as ISO 8601 dates forming a **half-open interval** — the `end_date` is the day after the last work day — and a `crew_count` (at least 1), the crews booked per calendar day of the window. The `end_date` must be strictly after the `start_date`; otherwise creation fails with `ERR_INVALID_WINDOW_DATES` (422). A new window is `PLANNED`.

Releasing a window — `PLANNED` to `RELEASED` — runs two temporal guards. The room-overlap guard: for every task of this window, no other window in `RELEASED` or `IN_PROGRESS` may hold a task on the same room over an intersecting half-open date range — intersection meaning the other window starts before this one ends and this one starts before the other ends — while pure adjacency, one window's `end_date` equal to the other's `start_date`, is allowed; a violation is `ERR_ROOM_WINDOW_OVERLAP` (409). The crew-capacity guard: for every calendar day of this window, the summed `crew_count` over windows of the same project and floor in `RELEASED` or `IN_PROGRESS` covering that day, plus this window's own `crew_count`, must be at most the project's `default_crew_capacity_per_floor_day`; a strictly greater sum is `ERR_FLOOR_CREW_CAPACITY_EXCEEDED` (409), and a sum landing exactly on capacity is allowed.

Starting work — `RELEASED` to `IN_PROGRESS` — requires at least one `SCHEDULED` task on the window (else `ERR_WINDOW_NO_TASKS`) and passes an aggregate stock check: for every PO line referenced by the window's scheduled tasks, the summed task quantities must not exceed that line's `qty_installable`, else `ERR_INSUFFICIENT_INSTALLABLE_STOCK` (409). Starting a window recomputes the project posture — the first `IN_PROGRESS` window flips the project from `OPEN` to `SEALED` — and bumps both the project's and the window's `version`. Completing a window — `IN_PROGRESS` to `COMPLETE` — requires every task of the window to be `COMPLETE` or `CANCELLED` (else `ERR_TASKS_OUTSTANDING`); it recomputes the posture — `SEALED` lifts when no window remains `IN_PROGRESS` — and bumps both versions. Cancelling a window is legal from `PLANNED` or `RELEASED` and cascades conditionally: every task still `SCHEDULED` moves to `CANCELLED`, while tasks already terminal are untouched; the window's `version` bumps. Moves that are not legal from the current state — starting from `PLANNED`, completing from `RELEASED`, cancelling from `IN_PROGRESS` — are rejected with `ERR_INVALID_WINDOW_TRANSITION`.

Individual room turns are scheduled as tasks. An `InstallationManager` creates one by naming the `window_id`, the `room_id`, the `po_line_id` supplying the units, and the `quantity` to install in that turn (at least 1); the task opens `SCHEDULED`. The window, the room, and the line must all belong to the same project, else `ERR_CROSS_PROJECT_REFERENCE`, and the line's `qty_installable` must cover the task's quantity, else `ERR_INSUFFICIENT_INSTALLABLE_STOCK`.

Completing a task requires the task to be `SCHEDULED` (else `ERR_INVALID_TASK_TRANSITION`), its owning window to be `IN_PROGRESS` (else `ERR_WINDOW_NOT_IN_PROGRESS`), and the line's `qty_installable` to be at least the task `quantity` (else `ERR_INSUFFICIENT_INSTALLABLE_STOCK`). Completion debits the line: `qty_installable` falls by the task quantity and `qty_installed` rises by it, the line's `version` bumps, and the spec's `attic_target_qty` is recomputed from the new installed count.

The attic target itself is computed from the spec's single non-cancelled PO line — uniqueness enforced by `ERR_SPEC_ALREADY_ORDERED` — whenever that line is created and whenever its `qty_installed` changes. With no such line, `attic_target_qty` is zero. Otherwise, the raw target is the spec's `attic_target_pct` multiplied by the line's `qty_installed`, doubled when the spec's `is_critical` flag is true, and rounded up to a whole unit; the target is then clamped — raised to `attic_min_qty` when the raw value falls below it, and capped at `attic_max_qty` when it exceeds it.

### 3.8. Attic Stock and Spare Inventory

Spares are managed as movements against a line's two pools, recorded by a `WarehouseReceiver`. Each movement carries a `direction` — `IN` moves units from installable to attic, `OUT` returns them from attic to installable, `WRITE_OFF` destroys attic units — a `quantity` of at least 1, and the OCC field `expected_po_line_version` per §2.6; a stale version is rejected with `ERR_STALE_PO_LINE_VERSION` (412) before any pool or cap check runs.

For `IN`, the quantity must not exceed the line's `qty_installable`, else `ERR_INSUFFICIENT_INSTALLABLE` (422); then — only after pool sufficiency passes — the resulting `qty_attic` must not exceed the spec's `attic_target_qty`, else `ERR_ATTIC_TARGET_EXCEEDED` (422), with equality against the target allowed. For `OUT` and `WRITE_OFF`, the quantity must not exceed the line's `qty_attic`, else `ERR_INSUFFICIENT_ATTIC` (422). Each accepted movement appends an immutable attic stock movement row that records `resulting_installable` and `resulting_attic` — the line's two pools immediately after the move — and bumps the line's `version`. The movement history of a line is readable through its attic-movements listing.

### 3.9. Owner Change Orders and the Contingency Draw

Budget movement after the envelope is declared flows through change orders. A `PurchasingAgent` or an `OwnerRep` proposes one with the `project_id`, a `title`, and an `adjustments` array whose entries each name a `budget_line_id` and a non-zero `delta_cents`; a positive delta draws from unallocated contingency, a negative delta returns budget to contingency. Every referenced budget line must exist (else `ERR_BUDGET_LINE_NOT_FOUND`) and belong to the change order's own project (else `ERR_CROSS_PROJECT_REFERENCE`). The server records the proposer's `X-User-ID` as `proposer_user_id`; the order opens `PROPOSED` with its `fee_cents` null until applied.

Decision power rests with the `OwnerRep`, under segregation of duties: the deciding request's `X-User-ID` must differ from the `proposer_user_id`, on both apply and reject, else `ERR_CHANGE_ORDER_SELF_APPROVAL` (403). The order must still be `PROPOSED` — this guard covers both re-applying an already `APPLIED` order and deciding an already `REJECTED` one — else `ERR_CO_NOT_PROPOSED`. Applying additionally carries `expected_project_version`; per §2.6 a mismatch with the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` (412), because a receiving post, a claim resolution, or another applied order may have advanced the project since the approver last read it.

Applying an order draws a contingency fee, computed in a pinned order so the fee never feeds its own tier. First, `POS` is the sum of the positive deltas and `NEG` the sum of the absolute values of the negative deltas across the adjustments. Second, utilization is measured **pre-fee**: the project's `committed_cents` plus `actual_spend_cents` plus `POS`, divided by `total_budget_cents`. Third, the rate is 5 percent when utilization is at most 0.80, 8 percent when utilization is above 0.80 and at most 0.95, and 12 percent above 0.95. Fourth, `fee_cents` is the rate multiplied by `POS`, rounded half-up to whole cents. Fifth, the funding check — evaluated last in the validation pipeline, as all fiscal checks are — requires `unallocated_contingency_cents` plus `NEG` to be at least `POS` plus `fee_cents`, else `ERR_CHANGE_ORDER_UNFUNDED` (402). Independently, every adjusted budget line must keep its `budgeted_cents` at or above its current `committed_cents` plus `actual_cents` after the delta is applied, else `ERR_BUDGET_BELOW_OBLIGATIONS` (402).

An applied order mutates the envelope: each adjusted line's `budgeted_cents` shifts by its `delta_cents`; the project's `unallocated_contingency_cents` moves by `NEG` minus `POS` minus `fee_cents`; `sunk_fees_cents` grows by `fee_cents` and is never returned to contingency; the computed fee is stored on the order's `fee_cents`. Both variances are then recomputed for each mutated line, and the project posture is recomputed — a budget-raising applied order can lift a `FROZEN` project. The project's `version` and the order's `version` each bump. Rejection, by contrast, moves the order from `PROPOSED` to `REJECTED` with the same segregation-of-duties bar, bumps the order's `version`, and touches no budget figures.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions, attaches, and decisions — return `200 OK`. Error responses use the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/projects` | Create an FF&E project | PurchasingAgent |
| GET | `/api/projects` | List projects (paginated; `status` filter) | Any |
| GET | `/api/projects/{projectId}` | Get a project with computed aggregates and posture | Any |
| POST | `/api/projects/{id}/lifecycle-transitions` | Advance project lifecycle | PurchasingAgent |
| GET | `/api/projects/{id}/budget-lines` | List budget lines of a project | Any |
| GET | `/api/projects/{id}/spec-items` | List spec items of a project | Any |
| GET | `/api/projects/{id}/purchase-orders` | List purchase orders of a project | Any |
| GET | `/api/projects/{id}/shipments` | List shipments of a project | Any |
| GET | `/api/projects/{id}/rooms` | List rooms of a project | Any |
| GET | `/api/projects/{id}/installation-windows` | List installation windows of a project | Any |
| GET | `/api/projects/{id}/change-orders` | List change orders of a project | Any |
| POST | `/api/budget-lines` | Create a budget line (unique category per project) | PurchasingAgent |
| GET | `/api/budget-lines/{budgetLineId}` | Get a budget line with committed/actual/variance views | Any |
| POST | `/api/spec-items` | Create a purchase specification | PurchasingAgent |
| GET | `/api/spec-items/{specItemId}` | Get a spec item | Any |
| GET | `/api/spec-items/{id}/bids` | List bids for a spec | Any |
| GET | `/api/spec-items/{id}/po-lines` | List PO lines for a spec | Any |
| POST | `/api/spec-items/{id}/submit` | Submit (or resubmit) for brand review | PurchasingAgent |
| POST | `/api/spec-items/{id}/brand-review` | Brand-standard decision | BrandApprover |
| POST | `/api/bids` | Submit a vendor bid against a brand-approved spec | Vendor |
| GET | `/api/bids/{bidId}` | Get a bid | Any |
| POST | `/api/bids/{bidId}/sample-decision` | Approve or reject the current sample round | PurchasingAgent |
| POST | `/api/bids/{bidId}/resubmit` | Vendor resubmits after sample rejection | Vendor |
| POST | `/api/bids/{bidId}/award` | Award the spec to the top-ranked sample-approved bid | PurchasingAgent |
| POST | `/api/purchase-orders` | Create a purchase order for a vendor | PurchasingAgent |
| GET | `/api/purchase-orders/{purchaseOrderId}` | Get a purchase order | Any |
| GET | `/api/purchase-orders/{id}/lines` | List lines of a purchase order | Any |
| POST | `/api/purchase-orders/{id}/lines` | Add a line priced from the awarded bid | PurchasingAgent |
| POST | `/api/purchase-orders/{id}/transitions` | Move one axis (fulfillment or invoice) | PurchasingAgent, Vendor |
| GET | `/api/po-lines/{poLineId}` | Get a PO line with quantity pools and landed cost | Any |
| POST | `/api/po-lines/{id}/reconcile` | Close a fully or short-received line after claims resolve | PurchasingAgent |
| POST | `/api/po-lines/{id}/attic-transfers` | Move units between installable and attic pools (OCC-guarded) | WarehouseReceiver |
| GET | `/api/po-lines/{id}/attic-movements` | List attic movements of a line | Any |
| GET | `/api/po-lines/{id}/damage-claims` | List damage/shortage claims of a line | Any |
| GET | `/api/po-lines/{id}/installation-tasks` | List installation tasks drawing on a line | Any |
| POST | `/api/shipments` | Create a freight consolidation shipment | PurchasingAgent |
| GET | `/api/shipments/{shipmentId}` | Get a shipment | Any |
| GET | `/api/shipments/{id}/purchase-orders` | List purchase orders attached to a shipment | Any |
| GET | `/api/shipments/{id}/receiving-events` | List receiving events of a shipment | Any |
| POST | `/api/shipments/{id}/purchase-orders` | Attach a ready-to-ship PO to a consolidating shipment | PurchasingAgent |
| POST | `/api/shipments/{id}/transitions` | Move the shipment through its lifecycle | PurchasingAgent |
| POST | `/api/receiving-events` | Record a warehouse receiving event | WarehouseReceiver |
| GET | `/api/receiving-events/{receivingEventId}` | Get a receiving event | Any |
| POST | `/api/receiving-events/{receivingEventId}/transitions` | Post or reverse a receiving event | WarehouseReceiver |
| POST | `/api/damage-claims` | File a damage or shortage claim bounded by the line's residual | PurchasingAgent |
| GET | `/api/damage-claims/{damageClaimId}` | Get a claim | Any |
| POST | `/api/damage-claims/{damageClaimId}/transitions` | Submit, dispute, resolve, or deny a claim | PurchasingAgent, Vendor |
| POST | `/api/rooms` | Register a room (unique room number per project) | InstallationManager |
| GET | `/api/rooms/{roomId}` | Get a room | Any |
| GET | `/api/rooms/{id}/installation-tasks` | List tasks scheduled on a room | Any |
| POST | `/api/installation-windows` | Plan an installation window for a floor | InstallationManager |
| GET | `/api/installation-windows/{installationWindowId}` | Get an installation window | Any |
| GET | `/api/installation-windows/{id}/tasks` | List tasks of a window | Any |
| POST | `/api/installation-windows/{id}/transitions` | Release, start, complete, or cancel a window | InstallationManager |
| POST | `/api/installation-tasks` | Schedule a room turn drawing units from a PO line | InstallationManager |
| GET | `/api/installation-tasks/{installationTaskId}` | Get an installation task | Any |
| POST | `/api/installation-tasks/{installationTaskId}/complete` | Mark a room turn installed | InstallationManager |
| POST | `/api/change-orders` | Propose an owner change order | PurchasingAgent, OwnerRep |
| GET | `/api/change-orders/{changeOrderId}` | Get a change order | Any |
| POST | `/api/change-orders/{changeOrderId}/apply` | Apply a proposed change order (OCC on project version) | OwnerRep |
| POST | `/api/change-orders/{changeOrderId}/reject` | Reject a proposed change order | OwnerRep |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_BUDGET_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SPEC_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_BID_NOT_FOUND` | 404 Not Found |
| `ERR_PURCHASE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PO_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RECEIVING_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_DAMAGE_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_INSTALLATION_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_INSTALLATION_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_LIFECYCLE_TRANSITION` | 409 Conflict |
| `ERR_NO_BUDGET_LINES` | 409 Conflict |
| `ERR_WINDOWS_OUTSTANDING` | 409 Conflict |
| `ERR_OPEN_CLAIMS_REMAIN` | 409 Conflict |
| `ERR_ACTIVE_POS_EXIST` | 409 Conflict |
| `ERR_SPEC_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_SPEC_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_SPEC_NOT_OPEN_FOR_BIDS` | 409 Conflict |
| `ERR_SPEC_NOT_BRAND_APPROVED` | 409 Conflict |
| `ERR_BID_NOT_SUBMITTED` | 409 Conflict |
| `ERR_BID_NOT_RESUBMITTABLE` | 409 Conflict |
| `ERR_SAMPLE_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_BID_NOT_SAMPLE_APPROVED` | 409 Conflict |
| `ERR_BID_NOT_BEST_EVALUATED` | 409 Conflict |
| `ERR_INVALID_PO_TRANSITION` | 409 Conflict |
| `ERR_PO_HAS_NO_LINES` | 409 Conflict |
| `ERR_INVOICE_BEFORE_DELIVERY` | 409 Conflict |
| `ERR_INVOICE_NOT_PAID` | 409 Conflict |
| `ERR_LINES_NOT_RECONCILED` | 409 Conflict |
| `ERR_INVALID_SHIPMENT_TRANSITION` | 409 Conflict |
| `ERR_SHIPMENT_NOT_CONSOLIDATING` | 409 Conflict |
| `ERR_PO_NOT_READY_TO_SHIP` | 409 Conflict |
| `ERR_SHIPMENT_EMPTY` | 409 Conflict |
| `ERR_SHIPMENT_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_NO_RECEIPTS_POSTED` | 409 Conflict |
| `ERR_DRAFT_EVENTS_OUTSTANDING` | 409 Conflict |
| `ERR_INVALID_EVENT_TRANSITION` | 409 Conflict |
| `ERR_INVALID_CLAIM_TRANSITION` | 409 Conflict |
| `ERR_LINE_NOT_RECEIVED` | 409 Conflict |
| `ERR_LINE_SHORTFALL_OPEN` | 409 Conflict |
| `ERR_CLAIMS_OPEN` | 409 Conflict |
| `ERR_INVALID_WINDOW_TRANSITION` | 409 Conflict |
| `ERR_WINDOW_NO_TASKS` | 409 Conflict |
| `ERR_TASKS_OUTSTANDING` | 409 Conflict |
| `ERR_INVALID_TASK_TRANSITION` | 409 Conflict |
| `ERR_WINDOW_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_CO_NOT_PROPOSED` | 409 Conflict |
| `ERR_CHANGE_ORDER_SELF_APPROVAL` | 403 Forbidden |
| `ERR_PROJECT_PROCUREMENT_SEALED` | 409 Conflict |
| `ERR_PROJECT_BUDGET_FROZEN` | 409 Conflict |
| `ERR_NO_AWARDED_BID` | 409 Conflict |
| `ERR_CROSS_PROJECT_REFERENCE` | 409 Conflict |
| `ERR_LINE_NOT_ON_SHIPMENT` | 409 Conflict |
| `ERR_DUPLICATE_BUDGET_CATEGORY` | 409 Conflict |
| `ERR_DUPLICATE_ROOM` | 409 Conflict |
| `ERR_SPEC_ALREADY_ORDERED` | 409 Conflict |
| `ERR_INVALID_WINDOW_DATES` | 422 Unprocessable Entity |
| `ERR_ROOM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_FLOOR_CREW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_OVER_RECEIPT` | 422 Unprocessable Entity |
| `ERR_DAMAGE_EXCEEDS_RECEIPT` | 422 Unprocessable Entity |
| `ERR_CLAIM_QTY_EXCEEDS_RESIDUAL` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INSTALLABLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ATTIC` | 422 Unprocessable Entity |
| `ERR_ATTIC_TARGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INSTALLABLE_STOCK` | 409 Conflict |
| `ERR_CLAIMS_BLOCK_REVERSAL` | 409 Conflict |
| `ERR_REVERSAL_POOL_SHORTFALL` | 409 Conflict |
| `ERR_BUDGET_LINE_EXCEEDED` | 402 Payment Required |
| `ERR_CHANGE_ORDER_UNFUNDED` | 402 Payment Required |
| `ERR_BUDGET_BELOW_OBLIGATIONS` | 402 Payment Required |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PO_LINE_VERSION` | 412 Precondition Failed |

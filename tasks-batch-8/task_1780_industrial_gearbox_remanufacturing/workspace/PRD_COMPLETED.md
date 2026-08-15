# Industrial Gearbox Remanufacturing API — Product Requirements Document

## 1. Introduction

Heavy industrial gearboxes are too valuable to discard and too critical to trust to informal repair. This document specifies the API for a gear-drive service center that remanufactures serialized industrial gear units end to end: a registry of customers and their units with lifetime service-hour odometers, teardown findings, per-component engineering decisions (regrind, cut new, replace with OEM, or reuse as-is), customer approval of scope changes against credit exposure, assembly clearance and backlash certification, a witnessed run-in test with oil analysis, heavy freight and rigging bay logistics, a loaner fleet that keeps customer lines running, and a warranty program metered in both service hours and calendar age.

Three tensions shape the design. Engineering discipline demands hard gates — a gearbox may not progress to run-in until measured clearances fall inside tolerance, and a failed run-in forces the build back rather than letting a marginal unit ship. Commercial prudence demands that approved scope accumulate against each customer's credit limit, with work blocked when exposure would breach it. Operational reality demands revision loops — teardown surprises change the priced scope, sometimes repeatedly, while the customer deliberates. The API coordinates five roles (front-desk intake, shop engineering, quality, service management, and the customer themselves) through a strictly ordered order lifecycle, with optimistic concurrency on the two writes most prone to stale views and a deterministic logical clock so that every date-dependent rule — loaner windows, warranty calendar legs, completion timestamps — is reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, envelope shape, pagination, resource conventions, state legality, concurrency control, the logical clock, monetary precision, credit accounting, and the order in which validation failures surface.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request with a missing or unrecognized `X-User-Role` header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Only the role header gates authentication: a missing `X-User-ID` is not by itself rejected — for staff roles it is simply recorded as null wherever an operator id is captured, and for the `Customer` role it merely fails the ownership check. A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles: `IntakeCoordinator`, `RemanEngineer`, `QualityInspector`, `ServiceManager`, and `Customer`.

- When `X-User-Role` is `IntakeCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the front desk registers customers and units, opens orders, books freight and loaners, records service hours, and drives shipment dispatch and delivery.
- When `X-User-Role` is `RemanEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the shop engineer runs teardown, logs findings, posts component decisions, submits and revises scope, and drives the build forward.
- When `X-User-Role` is `QualityInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `recorded_by` on each `AssemblyRecord` the inspector creates, but it is never compared to any entity's `id`.
- When `X-User-Role` is `ServiceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the service manager ships and completes orders, manages the loaner fleet, adjudicates warranty claims, scraps units, and controls the test clock.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource reachable from that customer — an order, the gear unit it belongs to, or a claim filed under the order — compare the resource's owning chain (the order's gear unit, and that unit's `customer_id`) to `X-User-ID`. Customer reads are restricted to the customer's own record and its units and orders; a customer attempting to act on another customer's order is rejected with `ERR_FORBIDDEN`.

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

List endpoints are paginated by two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to the nearest bound rather than rejected, and a non-numeric `limit` falls back to the default. The `offset` parameter skips a number of items from the start of the result set and defaults to 0; a negative or non-numeric `offset` likewise falls back to the nearest bound or default rather than erroring. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order; because `created_at` derives from the logical clock (§2.8) ties are common, and they break by creation sequence — the resource created earlier sorts first. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Append-Only Findings Log

Every primary resource — Customer, GearUnit, RemanOrder, ComponentDecision, AssemblyRecord, RunInTest, LoanerUnit, LoanerAssignment, FreightShipment, and WarrantyClaim — carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by one with every mutation, including system-driven side effects such as status flips and computed-field recomputation.

The `TeardownFinding` log is the deliberate exception: findings are append-only, so a finding carries only `id` and `created_at`; both `updated_at` and `version` are absent on it. Across all resources, a request body missing a required field or carrying a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a body carrying a field the endpoint does not declare is rejected the same way. Action endpoints that declare no request fields accept an absent or empty body and reject a body carrying any field — except unit check-in and unit scrap, which ignore the request body entirely.

### 2.5. Nested Resource Retrieval

Paths in this API are hierarchical — an order lives under a unit, a unit under a customer, and findings, decisions, assembly records, run-in tests, shipments, and warranty claims under an order. When a request path contains multiple identifiers, the server validates their existence strictly left to right (customer, then unit, then order, then the child resource) and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource; later segments are not examined once an earlier one fails.

### 2.6. State Legality and Terminal Lockdown

Every action in this API exists only from specific states of its target resource; invoking an action from any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Terminal states admit no further transitions at all: a `COMPLETED` or `CANCELLED` order, a `SCRAPPED` unit (on its physical dimension), a `RETURNED` or `CANCELLED` loaner assignment, a `DELIVERED` or `CANCELLED` shipment, and an `APPROVED` or `DENIED` warranty claim are each locked against any further action. The single carve-out is warranty intake: a `COMPLETED` order still accepts new warranty claims (§3.7), while a `CANCELLED` order accepts nothing.

### 2.7. Optimistic Concurrency Control

Exactly two writes in this API are guarded by optimistic concurrency control, each keyed to the `version` of the resource being mutated:

- The scope-revision write, `POST /reman/orders/{orderId}/revise-scope`, requires a non-optional `expected_order_version` field carrying the `version` of the RemanOrder as the client last observed it. Any mismatch with the order's current `version` — for example because another revision was submitted in between and advanced it — is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the order before revising again.
- The loaner-return write, `POST /reman/loaner-assignments/{assignmentId}/return`, requires a non-optional `expected_assignment_version` field carrying the `version` of the LoanerAssignment as the client last observed it. A mismatch with the assignment's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

In both writes the expected version may be supplied as a JSON integer or as a decimal digit string; anything else is `ERR_INVALID_REQUEST`. No other endpoint accepts a version field; all other writes proceed without an OCC check.

### 2.8. The Shop Logical Clock

All date- and time-dependent behavior in the system reads a single logical clock, never wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, every date comparison sees that instant. A `ServiceManager`-only capability sets the clock by supplying a `to_iso8601` timestamp — any valid timestamp is accepted, including one earlier than the current reading — and returns the resulting `current_utc`. The logical clock governs the "current date" used by loaner checkout window checks, the `completed_at_utc` stamped when an order completes, and the calendar leg of warranty eligibility; it also sources every other server-emitted timestamp, including `created_at`, `updated_at`, and `meta.api_request_timestamp`. Both `current_utc` and `completed_at_utc` render the clock as ISO 8601 UTC with three fractional digits, dropping the fractional part entirely when it is zero (so a whole-second clock reads e.g. `2026-08-02T00:00:00Z`).

### 2.9. Money, Cents, and Per-Line Rounding

All monetary values in the system — `credit_limit_cents`, `outstanding_approved_cents`, `quoted_estimate_cents`, `approved_scope_cents`, `final_invoice_cents`, `material_cents`, `line_total_cents`, and `freight_charge_cents` — are integer cents; no fractional cents ever appear. Where a price is computed from hourly rates and multipliers, the rounding rule is fixed: each component line is rounded half-up to integer cents first, and order-level totals are then the plain sum of those already-rounded line values. Summing unrounded lines and rounding once at the end produces different cents and is non-conformant.

### 2.10. Customer Credit Exposure

Each customer carries a running exposure figure, `outstanding_approved_cents`: the sum of `approved_scope_cents` over that customer's orders whose `status` is one of `APPROVED`, `IN_BUILD`, `ASSEMBLY`, `RUN_IN`, `READY_TO_SHIP`, or `SHIPPED`. Orders in `INTAKE`, `TEARDOWN`, `SCOPE_APPROVAL`, `COMPLETED`, or `CANCELLED` contribute nothing. The customer's `credit_hold` flag is set to true whenever `outstanding_approved_cents` is strictly greater than `credit_limit_cents` — landing exactly on the limit is not a hold — and is cleared again once the outstanding figure returns to at-or-below the limit. Exposure enters the sum at scope approval (whether by the customer or by automatic approval) and leaves it at exactly one point: order completion. A scope cancelled while still awaiting customer approval never entered the sum, so cancelling it requires no compensating debit. A freshly registered customer starts with `outstanding_approved_cents` of 0 and `credit_hold` false.

### 2.11. Validation Priority Order

Every request is validated against a fixed priority order, and a request that would fail several checks surfaces the earliest one, so higher-priority rejections mask lower-priority ones:

1. **Authentication** — all endpoints: the `X-User-Role` header must be present and recognized, else `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — all endpoints: the role must be permitted for the endpoint, and entity-backed ownership must hold where declared (a `Customer` may act only on its own units' orders), else `ERR_FORBIDDEN`.
3. **Existence** — all endpoints: path resources are validated left to right (customer, unit, order, child), else `ERR_NOT_FOUND`.
4. **State legality** — all action endpoints: the target resource must be in a state from which the requested transition exists, including terminal-state lockdown, else `ERR_INVALID_STATE`.
5. **Assembly tolerance safety gate** — the submit-assembly action: the `within_tolerance` verdict of the latest active assembly record is enforced before the referential checks below, else `ERR_TOLERANCE_EXCEEDED`.
6. **Referential completeness** — scope submission, scope revision, assembly submission, and warranty review: findings must exist (`ERR_NO_FINDINGS`), every finding must carry a pending decision (`ERR_DECISIONS_INCOMPLETE`), an active assembly record must exist (`ERR_NO_ASSEMBLY_RECORD`), and a warranty claim may only be reviewed once its order's passing run-in has established the oil baseline.
7. **Uniqueness and exclusivity** — unit registration, order creation, loaner reservation, and freight booking: serial numbers must be unique (`ERR_SERIAL_EXISTS`), a unit may carry at most one non-terminal order (`ERR_UNIT_BUSY`), loaner windows must not overlap (`ERR_LOANER_OVERLAP`), and rigging bay occupancies must not intersect (`ERR_RIGGING_BAY_CONFLICT`).
8. **Temporal windows** — loaner reservation and checkout, and warranty approval: an assignment's end must fall strictly after its start (`ERR_INVALID_WINDOW`), checkout may not precede the window start (`ERR_LOANER_WINDOW_FUTURE`), and an expired claim may not be approved (`ERR_WARRANTY_EXPIRED`).
9. **Fiscal gates** — scope approval: the customer's credit headroom must cover the approved scope, else `ERR_CREDIT_LIMIT_EXCEEDED`.

Two checks sit outside the numbered list: request-body shape validation (§2.4) surfaces after existence and before state legality, and the optimistic-concurrency version check (§2.7) surfaces immediately after state legality and before referential completeness.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and the Serialized Unit Registry

Everything begins at the front desk. An `IntakeCoordinator` registers a customer with its `legal_name` and a `credit_limit_cents` ceiling on outstanding approved scope; the account opens with no exposure and no hold, per §2.10. Under a customer, the coordinator registers each serialized gear unit with its manufacturer `serial_number` (unique across the entire unit registry — a duplicate is rejected with `ERR_SERIAL_EXISTS`), its gearbox `model` designation, and its nameplate `rated_torque_nm`. The new unit's `customer_id` ties it to the owning account, its `cumulative_service_hours` odometer starts at 0, and it is born with `physical_status` of `IN_SERVICE` and `commercial_status` of `STANDARD`.

A gear unit carries two independent status dimensions on the same row. The physical dimension moves `IN_SERVICE → AT_SHOP → (back to IN_SERVICE, or terminally to SCRAPPED)`; the commercial dimension moves among `STANDARD`, `UNDER_WARRANTY_REVIEW`, and `WARRANTY_FLAGGED`, driven by warranty events described in §3.7. Neither dimension implies the other.

While a unit is in service, the coordinator advances its service-hour odometer by posting an `hours` reading; the reading is in fact accepted in any physical state except `SCRAPPED` (terminal lockdown, §2.6) — only a scrapped unit rejects it. The odometer is forward-only, so `cumulative_service_hours` becomes the greater of its current value and the reported `hours` — a reading below the current odometer simply leaves it unchanged rather than erroring. When a unit arrives at the shop, the coordinator checks it in, moving `physical_status` from `IN_SERVICE` to `AT_SHOP`; a unit whose `commercial_status` is `WARRANTY_FLAGGED` may not be checked in (`ERR_UNIT_FLAGGED`). A `ServiceManager` may scrap a unit that is physically `AT_SHOP`, moving it to the terminal `SCRAPPED` state, but only while no order for that unit sits in a non-terminal state (`ERR_UNIT_BUSY`); scrapping also resets the unit's `commercial_status` to `STANDARD`.

### 3.2. Order Intake, Teardown Findings, and Component Decisions

Once a unit is physically at the shop, the coordinator opens a remanufacturing order against it. Intake requires three things: the unit's `physical_status` must be `AT_SHOP` (`ERR_UNIT_NOT_AT_SHOP`); the unit must have no other order in a non-terminal state — at most one open order per unit, enforced here and again at teardown start (`ERR_UNIT_BUSY`); and the reported `intake_hours` must equal the unit's current `cumulative_service_hours` exactly, so the order's baseline odometer can never drift from the registry (`ERR_INTAKE_HOURS_MISMATCH`). The coordinator also records a `quoted_estimate_cents` — a provisional figure quoted from the flat inspection book rate before anything is known about teardown actuals, and deliberately divergent from the eventual invoice — and may mark the job with an optional `rush` flag (defaulting to false when omitted) whose pricing effect lands in §3.3. The order is born in `INTAKE` with `approved_scope_cents` at 0 and both completion snapshots (`completed_at_hours`, `completed_at_utc`) unset; its `gear_unit_id` anchors it to the unit.

A `RemanEngineer` starts teardown, moving the order `INTAKE → TEARDOWN`, subject to the same two shop-floor guards: the unit must still be `AT_SHOP` (`ERR_UNIT_NOT_AT_SHOP`) and no other non-terminal order may exist for the same unit (`ERR_UNIT_BUSY`).

During teardown the engineer appends findings to the order's log. Each finding names a `component_code` (shop identifiers such as PINION_1, GEAR_2, BEARING_3), a `condition` of `REUSABLE`, `REGRINDABLE`, `CUT_ONLY`, or `BEYOND_REPAIR`, a `severity` integer from 1 (cosmetic) to 5 (safety-critical), and free-text `notes`; every row is stamped with its `reman_order_id`. The log is append-only — findings are never edited or deleted, and per §2.4 they carry no `updated_at` or `version`.

For each finding, the engineer posts a component decision: the `component_code` it answers, an `action` of `REGRIND`, `CUT_NEW`, `REPLACE_OEM`, or `REUSE_AS_IS`, the planned `labor_hours` (a JSON number — fractional hours such as 2.665 are accepted), and the `material_cents` part cost (integer cents). A decision is born with `approval_status` of `PENDING` and its `line_total_cents` priced per the rules of §3.3. Decisions are per-component replaceable: posting a new decision for a `component_code` that already has a `PENDING` decision on the same order flips the older one to `SUPERSEDED`, so at any moment each component has at most one pending decision. Decisions may be posted only while the order is in `TEARDOWN` or `SCOPE_APPROVAL`; at any other stage the attempt is rejected with `ERR_INVALID_STATE`. Posting a decision does not by itself move the order's approved scope total — that recompute happens only when the scope is submitted or revised.

### 3.3. Scope Pricing, Submission, and the Approval Loop

Labor is billed per decision at an action-tiered hourly rate in cents per hour: `REGRIND` at 8,500, `CUT_NEW` at 14,200, `REPLACE_OEM` at 6,000 (labor only — for a replacement the part cost rides entirely on `material_cents`), and `REUSE_AS_IS` at 2,500. When the order is flagged `rush`, the labor component of every line is multiplied by 1.25. Each line's `line_total_cents` is then: the planned `labor_hours` times the tier rate times the rush factor (1.25 when the order is rushed, 1.0 otherwise), rounded half-up to integer cents, plus the line's `material_cents`, rounded half-up once more — per §2.9, lines are rounded individually and only then summed. The order's `approved_scope_cents` is the sum of `line_total_cents` over its currently `PENDING` decisions, and remains 0 until teardown work is priced and submitted.

When the engineer submits the scope, two completeness guards fire first: at least one teardown finding must exist for the order (`ERR_NO_FINDINGS`), and every logged finding's `component_code` must be covered by a `PENDING` decision (`ERR_DECISIONS_INCOMPLETE`). The submission recomputes each decision's line total and then `approved_scope_cents` from the pending set. What happens next branches on money: if `approved_scope_cents` exceeds the intake `quoted_estimate_cents`, the order lands in `SCOPE_APPROVAL` and waits for the customer; otherwise — the scope is at or under the estimate — the system auto-approves it, driving the order straight `TEARDOWN → APPROVED`, flipping every `PENDING` decision to `APPROVED`, adding `approved_scope_cents` to the customer's `outstanding_approved_cents`, and recomputing `credit_hold`, a fiscal footprint identical to an explicit customer approval. Either way the unit's `physical_status` stays `AT_SHOP`.

While the order sits in `SCOPE_APPROVAL`, the owning customer may approve it. The caller must be the customer who owns the gear unit (`ERR_FORBIDDEN` otherwise), and the credit gate of §2.10 is enforced at this moment: `credit_hold` must currently be false and the projected exposure — current `outstanding_approved_cents` plus this order's `approved_scope_cents` — must be at or below `credit_limit_cents`, landing exactly on the limit being acceptable (`ERR_CREDIT_LIMIT_EXCEEDED`). Approval moves the order `SCOPE_APPROVAL → APPROVED`, flips all pending decisions to `APPROVED`, and adds the scope to the customer's outstanding exposure with `credit_hold` recomputed.

More often than not the customer pushes back, and the engineer revises. The revision cycle is a self-loop within `SCOPE_APPROVAL`: the engineer posts replacement decisions (each superseding its component's prior pending decision, per §3.2) and then re-presents the amended scope. That re-presentation is OCC-guarded per §2.7 — the request must carry `expected_order_version` matching the order's current `version`, and a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412). The revision re-validates that every finding still has a `PENDING` decision (`ERR_DECISIONS_INCOMPLETE`), recomputes `approved_scope_cents` from the current pending set, and increments the order's `version` by one; the loop may repeat without bound, each pass advancing the version again.

Cancellation has two shapes. The customer may cancel an order waiting in `SCOPE_APPROVAL`: its `PENDING` decisions flip to `SUPERSEDED`, any `RESERVED` loaner assignments held for the order flip to `CANCELLED` (freeing those loaner windows), and — because a scope awaiting approval never entered the outstanding-exposure sum of §2.10 — no credit debit occurs. The `IntakeCoordinator` may instead cancel an order still in `INTAKE`, which carries no side effects at all. Each role's cancellation exists only from its own state: the coordinator cancelling in `SCOPE_APPROVAL`, or the customer cancelling in `INTAKE`, is rejected like any other undefined transition. From any other state, cancellation is not a defined transition and is rejected with `ERR_INVALID_STATE`.

### 3.4. Build, Assembly Tolerances, and Run-In Certification

With the scope approved, the engineer starts the build (`APPROVED → IN_BUILD`), which requires that every component decision on the order stands `APPROVED` (`ERR_DECISIONS_INCOMPLETE`). Starting assembly (`IN_BUILD → ASSEMBLY`) has no further preconditions.

During assembly, a `QualityInspector` records the critical geometry: `backlash_mm` (measured gear backlash), `radial_clearance_mm` (bearing radial clearance), and `axial_clearance_mm` (shaft axial clearance). The record captures the inspector's `X-User-ID` as `recorded_by`, is born with `status` of `ACTIVE`, and computes its own `within_tolerance` verdict: backlash must lie within the band from 0.08 mm to 0.18 mm inclusive at both ends — a measured 0.18 mm is within tolerance — and each of the two clearances must be no greater than 0.05 mm. Several records may accumulate on an order; the gate reads the latest active one.

Submitting the assembly for run-in (`ASSEMBLY → RUN_IN`) enforces the quality gate: an `ACTIVE` assembly record must exist for the order (`ERR_NO_ASSEMBLY_RECORD`), and that latest active record's `within_tolerance` must be true (`ERR_TOLERANCE_EXCEEDED`).

The run-in test is the certification event, and it may be recorded only while the order stands `RUN_IN` (`ERR_INVALID_STATE` from any other state). The inspector records `duration_minutes`, the peak oil temperature `max_temp_c`, the peak vibration velocity `vibration_mm_s`, and the oil analysis `oil_particle_count` (particles per ml, ISO 4406 basis). The recording endpoint always creates the test row; its `result` is computed as `PASS` only when all four conditions hold together — the duration is exactly 120 minutes, `max_temp_c` is no greater than 95.0, `vibration_mm_s` is no greater than 4.5, and `oil_particle_count` is no greater than 3,200 — and `FAIL` otherwise. The branches diverge sharply:

- On a `PASS`, the test's `status` is `RECORDED`, its `oil_baseline_established` flag is set true — this row becomes the warranty oil baseline referenced in §3.7 — the order advances `RUN_IN → READY_TO_SHIP`, and the `final_invoice_cents` is computed: the sum of `line_total_cents` over the order's `APPROVED` decisions, plus the `freight_charge_cents` of every shipment on the order whose own status is not `CANCELLED`.
- On a `FAIL`, the test's `status` is `SUPERSEDED` and its `oil_baseline_established` stays false; the order automatically falls back `RUN_IN → IN_BUILD` for rework, and every currently `ACTIVE` assembly record is flipped to `INVALIDATED`, forcing fresh clearance and backlash measurements on the rebuild. That invalidation is a leaf mutation — it triggers no further cascade.

### 3.5. Freight, Rigging Bay Scheduling, and Order Completion

Heavy units move by booked freight. The coordinator books a shipment on an order with a `direction` of `INBOUND` (customer to shop) or `OUTBOUND` (shop to customer), the gross `weight_kg`, the `rigging_bay_date` the bay is booked for, and the booked `rigging_bay_hours`. Booking is allowed while the order is in any non-terminal state; booking against a `COMPLETED` or `CANCELLED` order is rejected with `ERR_INVALID_STATE`. The shipment is born `BOOKED` and its `freight_charge_cents` is computed immediately: the base is 45,000 cents for a gross weight up to and including 500 kg; 120,000 cents for anything heavier up to and including 2,000 kg; and above 2,000 kg, 120,000 cents plus 18,000 cents for each started 500-kg block beyond 2,000 kg, partial blocks rounding up. On top of the weight-tiered base, each booked rigging hour is charged at 9,500 cents.

The rigging bay is a contended resource. A booking occupies the bay for a half-open interval beginning at its `rigging_bay_date` and spanning its booked hours plus a two-hour turnaround buffer; if that occupancy intersects the occupancy of any other non-cancelled shipment, the booking is rejected with `ERR_RIGGING_BAY_CONFLICT`. Because the intervals are half-open, one booking ending exactly when another begins is permitted.

From `BOOKED`, the coordinator dispatches the shipment (moving it to `IN_TRANSIT`), later marks it delivered (`IN_TRANSIT → DELIVERED`), or cancels it while still `BOOKED` (`→ CANCELLED`). Marking the outbound shipment of a `SHIPPED` order delivered causes no further cascade by itself — completing the order is a separate, explicit step.

Shipping the order (`READY_TO_SHIP → SHIPPED`) is a `ServiceManager` action with two readiness guards: an `OUTBOUND` shipment must exist for the order and still be `BOOKED` (`ERR_FREIGHT_NOT_READY`), and no loaner assignment for the order may still be `CHECKED_OUT` (`ERR_LOANER_OUTSTANDING`, §3.6). Shipping moves every `OUTBOUND` shipment still `BOOKED` to `IN_TRANSIT` alongside the order.

Once an `OUTBOUND` shipment stands `DELIVERED`, the service manager completes the order (`SHIPPED → COMPLETED`; attempting it earlier fails with `ERR_FREIGHT_NOT_READY`). Completion is the fiscal and registry pivot: the unit's `physical_status` returns to `IN_SERVICE` and its `commercial_status` resets to `STANDARD`; the customer's `outstanding_approved_cents` is reduced by the order's `approved_scope_cents` — the only debit point in the whole credit lifecycle — with `credit_hold` recomputed; and the order stamps its two warranty anchors, `completed_at_hours` as a snapshot of the unit's `cumulative_service_hours` at that moment and `completed_at_utc` from the logical clock.

### 3.6. The Loaner Fleet Program

To keep customer lines running while their unit is on the bench, the shop maintains a loaner fleet. A `ServiceManager` registers each loaner with a `serial_number` unique across the fleet (duplicates fail with `ERR_SERIAL_EXISTS`) and the gearbox `model` it can substitute for; a loaner is born `AVAILABLE`.

The coordinator then reserves a loaner for a specific order by posting the `reman_order_id` it covers together with a window: `start_date` inclusive and `end_date` exclusive, a half-open interval. The referenced order must exist — an unknown `reman_order_id` is rejected with `ERR_NOT_FOUND` — but its status is not constrained: a window may be reserved against an order in any state, and the loaner's own availability is likewise not consulted at reservation time (it is enforced only at checkout). The window must be non-empty — an `end_date` at or before `start_date` is rejected with `ERR_INVALID_WINDOW`. Overlap is judged on those half-open windows: the reservation conflicts with an existing non-cancelled assignment on the same loaner exactly when the existing window starts before the requested `end_date` and the requested `start_date` starts before the existing window's end — touching back-to-back windows are allowed — and a true conflict is rejected with `ERR_LOANER_OVERLAP`. A reservation is born `RESERVED`, carrying its `loaner_unit_id`; the full assignment book can be listed with an optional `reman_order_id` query filter.

At the window start the coordinator checks the loaner out (`RESERVED → CHECKED_OUT`), which requires the loaner to currently be `AVAILABLE` (`ERR_LOANER_UNAVAILABLE`) and the current date — per the logical clock of §2.8 — to be on or after `start_date` (`ERR_LOANER_WINDOW_FUTURE`); checkout flips the loaner itself to `CHECKED_OUT`. Returning the loaner (`CHECKED_OUT → RETURNED`) is the second OCC-guarded write of §2.7: the request must carry `expected_assignment_version` matching the assignment's current `version`, a stale view failing with `ERR_STALE_VERSION` (HTTP 412); a successful return flips the loaner back to `AVAILABLE` and increments the assignment's `version` by one. A reservation may also be extended while `RESERVED` or `CHECKED_OUT` by supplying a `new_end_date`; the new date must still fall strictly after `start_date` (`ERR_INVALID_WINDOW`) but need not be later than the current `end_date`, the overlap rule is re-validated against the extended window with the assignment itself excluded, and the assignment's `version` increments. Finally, a `RESERVED` assignment may be cancelled outright by the coordinator — or by the cascade when its order is cancelled from `SCOPE_APPROVAL` (§3.3) — landing in `CANCELLED` and freeing the window. One cross-program guard bears repeating: an order cannot be marked shipped while any of its assignments is still `CHECKED_OUT`; the outstanding loaner surfaces as `ERR_LOANER_OUTSTANDING` at ship time.

### 3.7. Warranty Claims and Dual-Basis Eligibility

A customer files a warranty claim against the order that remanufactured their unit, supplying the unit's `reported_hours` — its cumulative service hours at claim time, which may not be below the unit's current `cumulative_service_hours` odometer (`ERR_HOURS_REGRESSION`) — and a free-text `claim_reason`. The order need not be finished: a claim may be opened while the order is still in flight, in which case it sits `OPEN` with its `eligibility` unset (null) until resolution is possible. Once the linked order is `COMPLETED` — already so at filing time, or later upon completion — the claim's `warranty_clock_start_hours` is copied from the order's `completed_at_hours` snapshot and the dual-basis verdict is computed.

Eligibility is metered two ways, and the two verdicts can legitimately differ for identical claim data. The hours leg computes `hours_since_reman` as `reported_hours` minus `warranty_clock_start_hours`: covered when that figure is no greater than 2,000 hours — a claim at exactly 2,000 hours is covered, one at 2,001 is not — and failed as `EXPIRED_HOURS` otherwise. The calendar leg measures whole days between the claim's `created_at` and the order's `completed_at_utc`: covered at no more than 365 days, failed as `EXPIRED_CALENDAR` beyond that. The combined `eligibility` is `COVERED` only when both legs are covered; when the hours leg fails it is reported as `EXPIRED_HOURS` — the hours basis is evaluated before the calendar basis — and otherwise `EXPIRED_CALENDAR`.

A `QualityInspector` moves an `OPEN` claim to `UNDER_REVIEW` only once its linked order stands `COMPLETED` (`ERR_ORDER_NOT_COMPLETED`) — completion guaranteeing that a passing run-in established the oil baseline the review leans on; the move also flips the unit's `commercial_status` to `UNDER_WARRANTY_REVIEW`. (Opening a claim against an already-`COMPLETED` order moves the unit to `UNDER_WARRANTY_REVIEW` at filing time.) Adjudication belongs to the `ServiceManager`: approval (`UNDER_REVIEW → APPROVED`) is permitted only when `eligibility` is `COVERED`, any other verdict failing with `ERR_WARRANTY_EXPIRED`, and it flags the unit `WARRANTY_FLAGGED` — which in turn blocks future check-in per §3.1; denial (`UNDER_REVIEW → DENIED`) returns the unit's `commercial_status` to `STANDARD`. Both verdicts are terminal.

## 4. Endpoint Definitions

Operations that create a new resource — registering a customer, unit, order, finding, decision, assembly record, run-in test, loaner, assignment, shipment, or warranty claim — return `201 Created` with the created resource in `data`. Operations that modify an existing resource or drive a state transition return `200 OK` with the updated resource, and all reads return `200 OK`. In the table below, "All roles" means every role named in §2.1; `Customer` access remains restricted to its own records as described there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reman/customers` | Register a customer | IntakeCoordinator |
| GET | `/reman/customers/{customerId}` | Get a customer | All roles |
| GET | `/reman/customers/{id}/units` | List gear units of a customer | All roles |
| POST | `/reman/customers/{id}/units` | Register a serialized gear unit | IntakeCoordinator |
| GET | `/reman/units/{unitId}` | Get a gear unit | All roles |
| POST | `/reman/units/{unitId}/record-service-hours` | Advance the unit's service-hour odometer (forward only) | IntakeCoordinator |
| POST | `/reman/units/{unitId}/check-in` | Check unit into the shop | IntakeCoordinator |
| POST | `/reman/units/{unitId}/scrap` | Scrap a unit (terminal) | ServiceManager |
| POST | `/reman/units/{id}/orders` | Open a remanufacturing order at intake | IntakeCoordinator |
| GET | `/reman/orders/{orderId}` | Get an order | All roles |
| GET | `/reman/units/{id}/orders` | List orders for a unit | All roles |
| POST | `/reman/orders/{orderId}/start-teardown` | Begin teardown | RemanEngineer |
| POST | `/reman/orders/{id}/findings` | Append a teardown finding | RemanEngineer |
| GET | `/reman/orders/{id}/findings` | List findings for an order | All roles |
| POST | `/reman/orders/{id}/decisions` | Add a component decision (per-component replacement supersedes the prior pending decision) | RemanEngineer |
| GET | `/reman/orders/{id}/decisions` | List component decisions for an order | All roles |
| POST | `/reman/orders/{orderId}/submit-scope` | Submit teardown scope; auto-approves when within the quoted estimate | RemanEngineer |
| POST | `/reman/orders/{orderId}/revise-scope` | Revise the pending scope within SCOPE_APPROVAL (OCC-guarded) | RemanEngineer |
| POST | `/reman/orders/{orderId}/approve-scope` | Customer approves the scope | Customer |
| POST | `/reman/orders/{orderId}/start-build` | Begin build | RemanEngineer |
| POST | `/reman/orders/{orderId}/start-assembly` | Begin assembly | RemanEngineer |
| POST | `/reman/orders/{id}/assembly-records` | Record clearance & backlash measurements | QualityInspector |
| GET | `/reman/orders/{id}/assembly-records` | List assembly records for an order | All roles |
| POST | `/reman/orders/{orderId}/submit-assembly` | Submit assembly for run-in | QualityInspector |
| POST | `/reman/orders/{id}/run-in-tests` | Record a run-in test with oil analysis | QualityInspector |
| GET | `/reman/orders/{id}/run-in-tests` | List run-in tests for an order | All roles |
| POST | `/reman/orders/{orderId}/ship` | Mark order shipped (outbound freight must be booked and unit ready) | ServiceManager |
| POST | `/reman/orders/{orderId}/complete` | Complete the order after outbound delivery | ServiceManager |
| POST | `/reman/orders/{orderId}/cancel` | Cancel an order in INTAKE or SCOPE_APPROVAL | IntakeCoordinator, Customer |
| POST | `/reman/loaner-units` | Register a loaner unit | ServiceManager |
| GET | `/reman/loaner-units/{loanerId}` | Get a loaner unit | IntakeCoordinator, RemanEngineer, ServiceManager |
| GET | `/reman/loaner-units/{id}/assignments` | List assignments for a loaner | IntakeCoordinator, RemanEngineer, ServiceManager |
| POST | `/reman/loaner-units/{id}/assignments` | Reserve a loaner window for an order (half-open interval; adjacency allowed) | IntakeCoordinator |
| GET | `/reman/loaner-assignments` | List loaner assignments, optionally filtered by order | IntakeCoordinator, RemanEngineer, ServiceManager |
| GET | `/reman/loaner-assignments/{assignmentId}` | Get a loaner assignment | IntakeCoordinator, RemanEngineer, ServiceManager |
| POST | `/reman/loaner-assignments/{assignmentId}/checkout` | Check out the loaner at window start | IntakeCoordinator |
| POST | `/reman/loaner-assignments/{assignmentId}/return` | Return the loaner (OCC-guarded) | IntakeCoordinator |
| POST | `/reman/loaner-assignments/{assignmentId}/extend` | Extend the end date of a RESERVED or CHECKED_OUT assignment | IntakeCoordinator |
| POST | `/reman/loaner-assignments/{assignmentId}/cancel` | Cancel a RESERVED assignment outright | IntakeCoordinator |
| POST | `/reman/orders/{id}/shipments` | Book freight + rigging bay for a heavy unit move | IntakeCoordinator |
| GET | `/reman/orders/{id}/shipments` | List shipments for an order | All roles |
| GET | `/reman/shipments/{shipmentId}` | Get a shipment | IntakeCoordinator, RemanEngineer, QualityInspector, ServiceManager |
| POST | `/reman/shipments/{shipmentId}/dispatch` | Dispatch a booked shipment | IntakeCoordinator |
| POST | `/reman/shipments/{shipmentId}/deliver` | Mark shipment delivered | IntakeCoordinator |
| POST | `/reman/shipments/{shipmentId}/cancel` | Cancel a booked shipment | IntakeCoordinator |
| POST | `/reman/orders/{id}/warranty-claims` | Open a warranty claim against an order | Customer |
| GET | `/reman/orders/{id}/warranty-claims` | List warranty claims for an order | All roles |
| GET | `/reman/warranty-claims/{claimId}` | Get a warranty claim | All roles |
| POST | `/reman/warranty-claims/{claimId}/review` | Move claim to review | QualityInspector |
| POST | `/reman/warranty-claims/{claimId}/approve` | Approve a covered claim | ServiceManager |
| POST | `/reman/warranty-claims/{claimId}/deny` | Deny a claim | ServiceManager |
| POST | `/reman/_clock/set_current_utc` | Set the logical clock (ISO 8601); unset clock reads the startup default | ServiceManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_UNIT_NOT_AT_SHOP` | 409 Conflict |
| `ERR_UNIT_BUSY` | 409 Conflict |
| `ERR_UNIT_FLAGGED` | 409 Conflict |
| `ERR_SERIAL_EXISTS` | 409 Conflict |
| `ERR_INTAKE_HOURS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_FINDINGS` | 422 Unprocessable Entity |
| `ERR_DECISIONS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NO_ASSEMBLY_RECORD` | 422 Unprocessable Entity |
| `ERR_TOLERANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_COMPLETED` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_HOURS_REGRESSION` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LOANER_OVERLAP` | 409 Conflict |
| `ERR_LOANER_UNAVAILABLE` | 409 Conflict |
| `ERR_LOANER_WINDOW_FUTURE` | 422 Unprocessable Entity |
| `ERR_LOANER_OUTSTANDING` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_RIGGING_BAY_CONFLICT` | 409 Conflict |
| `ERR_FREIGHT_NOT_READY` | 409 Conflict |

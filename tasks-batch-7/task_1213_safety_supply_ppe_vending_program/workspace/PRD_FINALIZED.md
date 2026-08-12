# Safety Supply & PPE Vending Program API — Product Requirements Document

## 1. Introduction

Industrial safety programs live or die on two promises: the right protective equipment reaches the right worker at the right moment, and every dollar of that equipment is traceable back to the cost center that consumed it. This document specifies the Safety Supply & PPE Vending Program API, a Fastenal-style industrial vending platform that dispenses personal protective equipment at the point of work while enforcing per-role issuance policy, respirator fit-test linkage, serialized fall-protection inspection cycles, and contract-priced chargeback to home cost centers.

Seven operator roles share the surface. Front-line employees vend for themselves by badge identity; line managers grant bounded, time-windowed overrides and reverse mistaken vends under segregation of duties; EHS administrators curate the catalog, the policy book, and the workforce; vending technicians commission machines, maintain planograms, restock, and service; safety officers record fit tests and regulated-unit inspections; finance analysts run cost-center chargeback batches; and compliance auditors file findings over override usage and inspection compliance. All time-dependent behavior — rolling usage windows, override expiry, inspection due dates, fit-test expiry — is driven by a deterministic logical clock rather than wall-clock time, so sweeps and boundary conditions are exactly reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The declared roles are `EHSAdministrator`, `Manager`, `Employee`, `VendingTechnician`, `SafetyOfficer`, `FinanceAnalyst`, `ComplianceAuditor`, and the shared read surface `Any`. A request missing either header, naming an undeclared role, or — for the entity-backed roles — presenting an `X-User-ID` that does not resolve to an existing Employee row is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). Role authorization then gates each endpoint per §4; a role not permitted for the endpoint, or a `Manager` assertion by an Employee whose `is_manager` flag is false, is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403).

Identity semantics are per role. When `X-User-Role` is `Manager` or `Employee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee compare the resource's foreign-key field to `X-User-ID`. This is how a vend records the caller as the issuance's `employee_id`, and how the segregation-of-duties rules compare a manager's header identity against the `employee_id` of the override being granted or the issuance being reversed. When `X-User-Role` is `EHSAdministrator`, `VendingTechnician`, `SafetyOfficer`, `FinanceAnalyst`, `ComplianceAuditor`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `inspector_user_id` on a serialized unit's inspection-log entries, where the inspection write stores it) but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by creation timestamp in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

The platform never reads wall-clock time. A deterministic logical clock governs every temporal evaluation: vend timestamps, rolling usage windows, service-window reachability, override and fit-test expiry, and inspection due-date sweeps. At server startup, before any clock-setting call, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter.

An `EHSAdministrator` may set the clock to a supplied `to_iso8601` instant through the admin-only clock capability; the call answers with the resulting `current_utc`. Every such set triggers the system sweeps described in §3.8 — override expiry, inspection due and overdue quarantine, and fit-test expiry. Date-granularity comparisons throughout this document — a vend date against a price window, the current date against an expiry date — are always made against this logical clock.

### 2.5. Common Resource Properties

Every resource in the API carries four system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` (string): the same timestamp shape, refreshed on every mutation of the resource.
- `version` (integer): starts low and increments by one on every mutation of the resource.

When a single operation mutates several resources — a vend that decrements a slot, draws an override, and issues a serialized unit — each affected resource independently refreshes `updated_at` and increments `version`.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents. Contract price resolution and line totals are exact integer arithmetic with no rounding anywhere in the pricing path. The single rounding operation in the platform is the chargeback administration fee, computed per swept line with round-half-up to whole cents before summation (§3.7). Calendar dates are ISO dates in `YYYY-MM-DD` form unless a field is explicitly a timestamp; timestamps are ISO 8601 UTC.

### 2.7. Nested Resource Retrieval and Identifier Validation

Endpoints whose paths chain identifiers — a slot under a machine — validate path identifiers left to right and reject with the 404 corresponding to the first identifier that does not resolve; a slot request under a nonexistent machine fails on the machine before the slot is ever consulted. After path identifiers, the foreign keys in the request body (`machine_id`, `slot_id`, `item_id`, `job_role_id`, `home_cost_center_id`, `employee_id`, `serialized_unit_id`, `manager_override_id`) are resolved, and any miss produces the resource-specific 404: `ERR_COST_CENTER_NOT_FOUND`, `ERR_JOB_ROLE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CONTRACT_PRICE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_SERIALIZED_UNIT_NOT_FOUND`, `ERR_MANAGER_OVERRIDE_NOT_FOUND`, `ERR_ISSUANCE_NOT_FOUND`, `ERR_RESTOCK_ORDER_NOT_FOUND`, `ERR_SERVICE_TICKET_NOT_FOUND`, `ERR_CHARGEBACK_BATCH_NOT_FOUND`, or `ERR_COMPLIANCE_AUDIT_NOT_FOUND`.

### 2.8. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and no other endpoint accepts a version field. `POST /machines/{machineId}/slots` — creating a planogram slot — requires the request to carry `expected_machine_version` as a non-optional field, equal to the parent machine's current `version`; if another write — commissioning, an offline toggle, a service start, or an earlier slot create — has advanced the machine since the client last read it, the caller's planogram view is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). `PUT /slots/{slotId}` — updating a planogram slot (an item swap, a capacity change, or a par-level change) — likewise requires `expected_slot_version` as a non-optional field matching the slot's current `version`; a prior planogram edit that has already superseded the caller's view produces the same `ERR_STALE_VERSION` (412) rejection.

### 2.9. Idempotent Vend Submission

Vend submission is idempotent on the client-supplied `idempotency_key`, which is unique across all issuance transactions. When a vend arrives carrying a key already stored, the server compares the remainder of the payload: an identical payload returns the original transaction with a 201 status (a replay, not a second vend), while a difference in any other field is rejected with `ERR_IDEMPOTENCY_CONFLICT` (409). This check runs after existence resolution and before every business gate.

### 2.10. Validation Order — First Failure Wins

Every request is validated in a fixed order, and the first failing check determines the response. The pinned sequence:

1. Authentication context: both headers present, the role declared, and entity-backed identities resolving to an existing Employee (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint, including the `is_manager` gate on the `Manager` role (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Request-body shape: required fields present, types valid, enum members valid, integer ranges enforced — `qty` above zero, `capacity` above zero, `par_level` within zero up to but not including `capacity`, window ends after starts (`ERR_VALIDATION_FAILED`). Shape runs after the two auth checks and before existence.
4. Existence of path identifiers left to right, then of body foreign keys (the fourteen resource-specific 404 errors of §2.7).
5. Vend idempotency replay (`ERR_IDEMPOTENCY_CONFLICT`).
6. Optimistic-concurrency tokens on the two guarded writes (`ERR_STALE_VERSION`).
7. Employee `ACTIVE` for a vend (`ERR_EMPLOYEE_NOT_ACTIVE`).
8. Machine state gates (`ERR_MACHINE_NOT_ACTIVE`).
9. Item `ACTIVE` (`ERR_ITEM_DISCONTINUED`).
10. Target-resource state preconditions per the state machines (`ERR_OVERRIDE_NOT_ACTIVE`, `ERR_SERIALIZED_UNIT_NOT_ISSUABLE`, `ERR_RESTOCK_ORDER_INVALID_STATE`, `ERR_SERVICE_TICKET_INVALID_STATE`, `ERR_BATCH_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_ISSUANCE_ALREADY_REVERSED`, `ERR_INVALID_STATE`).
11. Respirator fit-test linkage (`ERR_FIT_TEST_REQUIRED`).
12. Fall-protection linkage (`ERR_SERIALIZED_UNIT_NOT_ISSUABLE` for unit state, `ERR_REGULATED_ITEM_INSPECTION_DUE` for an employee holding a lapsed unit).
13. Service-window overlap (`ERR_SERVICE_WINDOW_OVERLAP`).
14. Override window separation (`ERR_OVERRIDE_WINDOW_OVERLAP`).
15. Contract-price and batch-period window conflicts (`ERR_CONTRACT_PRICE_WINDOW_CONFLICT`, `ERR_BATCH_PERIOD_OVERLAP`).
16. Service-window reachability at start (`ERR_SERVICE_WINDOW_NOT_REACHED`).
17. Structural integrity in its own pinned sub-order — slot-to-machine membership, serialized-unit presence, serialized quantity, unit-to-slot-and-item match, serialized-category misuse, capacity (`ERR_SLOT_ITEM_MISMATCH`, `ERR_SERIALIZED_UNIT_REQUIRED`, `ERR_SERIALIZED_QTY_INVALID`, `ERR_ITEM_NOT_SERIALIZED_CATEGORY`, `ERR_CAPACITY_EXCEEDED`).
18. Uniqueness (`ERR_DUPLICATE_EMPLOYEE_CODE`, `ERR_DUPLICATE_MACHINE_LOCATION`, `ERR_DUPLICATE_SKU`, `ERR_DUPLICATE_SERIAL_NUMBER`, `ERR_DUPLICATE_SLOT_CODE`, `ERR_DUPLICATE_POLICY`).
19. Segregation of duties (`ERR_SELF_OVERRIDE_FORBIDDEN`, `ERR_SELF_REVERSAL_FORBIDDEN`).
20. Entitlement (`ERR_ITEM_NOT_ENTITLED`).
21. Issuance limits and override draw (`ERR_ISSUANCE_LIMIT_EXCEEDED`, `ERR_OVERRIDE_QTY_EXCEEDED`).
22. Non-empty chargeback close (`ERR_EMPTY_CHARGEBACK_BATCH`).
23. Referential blockers (`ERR_OPEN_RESTOCK_ORDERS_EXIST`, `ERR_OPEN_SERVICE_TICKETS_EXIST`, `ERR_OPEN_BATCHES_EXIST`, `ERR_NO_OPEN_CHARGEBACK_BATCH`).

### 2.11. Cross-Aggregate Consistency

Cascades keep the flat entity graph coherent whenever one operation's effects cross resource boundaries. Terminating an employee revokes their `ACTIVE` overrides; starting service on a machine cancels its open restock orders; reversing a vend restores stock, cancels a now-unneeded suggested restock, returns a serialized unit to stock, and posts a chargeback adjustment when the original line was already billed; closing a chargeback batch advances the cost center's year-to-date total. Each cascade is spelled out with its trigger in §3, and every resource mutated by any cascade refreshes `updated_at` and increments `version` per §2.5.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations: Job Roles, Items, and Contract Pricing

An `EHSAdministrator` builds the catalog before any machine can vend. Job roles come first: each carries a unique `role_name` (WELDER, ELECTRICIAN, and the like) plus a free-text `description` that defaults to empty when omitted. Items follow, identified by a unique `sku` — a duplicate submission is rejected with `ERR_DUPLICATE_SKU` — with a display `name`, a `category` of `GENERAL`, `RESPIRATOR`, or `FALL_PROTECTION`, and a `base_list_price_cents` fallback unit price that cannot be negative.

Two behavioral flags derive from `category` at creation, and any client-supplied value for them is ignored: `requires_fit_test` is true exactly when the item is a `RESPIRATOR`, and `serialized_tracking` is true exactly when the item is `FALL_PROTECTION`. Fall-protection items additionally require `inspection_interval_days`, a positive integer that drives the regulated inspection cycle of §3.3; for any other category the field stays null. Every item begins life `ACTIVE`.

Discontinuation is a one-way door. An `EHSAdministrator` discontinues an `ACTIVE` item, moving it to `DISCONTINUED`; repeating the action against an item no longer `ACTIVE` is rejected with `ERR_ITEM_DISCONTINUED`. Once discontinued, the item refuses four operations with `ERR_ITEM_DISCONTINUED`: new vends, new planogram slots, new restock orders for slots holding it, and new serialized-unit registrations. Issuance policies that reference the item remain in force for historical reads.

Contract pricing is tiered per item. A price row binds an `item_id` to a breakpoint `min_period_qty` (zero or greater), a `unit_price_cents` (zero or greater), and an inclusive effectiveness window from `effective_from` to `effective_to`, whose end must not precede its start. A tier applies when the issuing cost center's cumulative posted quantity for that item within the vend's calendar month, measured before the current line, reaches at least `min_period_qty`; how a vend resolves among multiple rows is pinned in §3.4, and how batches re-resolve tiers at close is covered in §3.7. Windows for the same item and the same `min_period_qty` breakpoint must not intersect under closed-interval comparison — a new row whose window touches any existing row's window for the same item at the same breakpoint is rejected with `ERR_CONTRACT_PRICE_WINDOW_CONFLICT` — while rows for the same item at different breakpoints may share or overlap windows freely (that coexistence is exactly how tiered pricing is expressed), and gaps between windows are perfectly legal. The price book can be listed with an optional `item_id` filter.

### 3.2. People, Issuance Policies, and Respirator Fit Tests

Employee records anchor both identity and policy. An `EHSAdministrator` creates each employee with a unique `employee_code` (duplicates fail with `ERR_DUPLICATE_EMPLOYEE_CODE`), a `full_name`, the `job_role_id` that will drive entitlement resolution at vend time, the `home_cost_center_id` that chargeback will bill, and an optional `is_manager` flag defaulting to false — the gate that lets an Employee-backed identity act in the `Manager` role. New employees start `ACTIVE` with an empty `fit_tests` list. The employee directory can be filtered by `job_role_id`, `cost_center_id`, `home_cost_center_id`, or `status`.

The employee lifecycle is deliberately small. Suspension moves `ACTIVE` to `SUSPENDED`, reinstatement moves `SUSPENDED` back to `ACTIVE`, and termination is allowed from either `ACTIVE` or `SUSPENDED`, landing in the terminal `TERMINATED` state. A status change from any other configuration is rejected with `ERR_INVALID_STATE`. Termination is the consequential transition: every `ACTIVE` manager override belonging to the employee is cascaded to `REVOKED`, with its consumed quantity preserved for audit. The same administrative update may also reassign `job_role_id` or `home_cost_center_id`, or flip `is_manager`; each successful update increments the employee's `version`.

Issuance policies express entitlement. Each policy pairs a `job_role_id` with an `item_id` — the pair is unique, and a second policy for the same pair is rejected with `ERR_DUPLICATE_POLICY` — and declares a `period_limit_qty`, the base quantity a worker in that role may draw of that item within a rolling window of `period_window_days` days. Policies can be listed filtered by `job_role_id`, `item_id`, or both. An employee with no policy row for an item is simply not entitled to it, a rule the vend enforces late in its gate order (§3.4).

Respirator fitness is tracked per employee and item. A `SafetyOfficer` records a fit test with the `item_id`, the `tested_on` date, and a `result` of `PASS` or `FAIL`; the system appends an entry to the employee's `fit_tests` carrying its own `fit_test_id`, `item_id`, `tested_on`, `result`, `expires_on`, and `status`. A `PASS` earns an `expires_on` of the test date plus 365 days and a `VALID` status; a `FAIL` records an `expires_on` equal to the test date and is also stored with status `VALID`, but a failed result never authorizes a respirator vend. Validity always reads the latest entry for the employee and item — greatest `tested_on`, ties broken by greatest `created_at` — and the logical-clock sweep of §3.8 flips a `VALID` entry to `EXPIRED` once the current date passes its `expires_on`, with the expiry date itself still counting as valid.

### 3.3. Machines, Planograms, and Serialized Fall-Protection Stock

A `VendingTechnician` registers each machine with a unique `location_code` (duplicates rejected with `ERR_DUPLICATE_MACHINE_LOCATION`), a `site_name`, and a `model`; the machine starts in `COMMISSIONING`. Commissioning completes — `COMMISSIONING` to `ACTIVE` — only once the machine has at least one planogram slot, failing with `ERR_MACHINE_NO_PLANOGRAM` otherwise. From `ACTIVE` a technician may take the machine `OFFLINE` and later restore it to `ACTIVE`. Decommissioning is allowed from `ACTIVE` or `OFFLINE`, but only when the machine has no restock orders in `SUGGESTED` or `PICKED` (else `ERR_OPEN_RESTOCK_ORDERS_EXIST`) and no service tickets in `OPEN` or `IN_PROGRESS` (else `ERR_OPEN_SERVICE_TICKETS_EXIST`); the machine then reaches the terminal `DECOMMISSIONED` state. The remaining state, `IN_SERVICE`, is entered and left exclusively through the service-ticket workflow of §3.6 — a direct machine write naming `IN_SERVICE` or any other unsupported target is rejected with `ERR_INVALID_STATE`. Every successful lifecycle write increments the machine's `version`. Machines can be listed filtered by `status`.

Planogram slots fill a machine. Creating a slot names the parent machine in the path and submits `slot_code`, `item_id`, `capacity`, `par_level`, and the OCC token `expected_machine_version` (§2.8). The `slot_code` must be unique within its machine (`ERR_DUPLICATE_SLOT_CODE`), `capacity` must be positive, and `par_level` must be at least zero and strictly less than `capacity`. The parent machine must be `COMMISSIONING`, `ACTIVE`, or `IN_SERVICE` — any other state fails with `ERR_MACHINE_NOT_ACTIVE` — and the stocked item must be `ACTIVE` (`ERR_ITEM_DISCONTINUED`). A fresh slot starts with `on_hand_qty` at zero, and its creation advances the parent machine's `version` by one, which is exactly why the OCC token exists. Slot edits — swapping the item, resizing `capacity`, retargeting `par_level` — go through the slot update carrying `expected_slot_version`, are accepted only while the machine is `COMMISSIONING` or `IN_SERVICE`, leave `on_hand_qty` untouched, and must never shrink `capacity` below the current `on_hand_qty` (`ERR_CAPACITY_EXCEEDED`); each edit increments the slot's `version`. Slots are readable per machine, or across the estate through a cross-machine listing filtered by `item_id` or `machine_id`.

Serialized units give fall-protection gear its chain of custody. An `EHSAdministrator` registers each unit with its `item_id` — which must belong to a `FALL_PROTECTION` item, otherwise `ERR_ITEM_NOT_SERIALIZED_CATEGORY` — a globally unique `serial_number` (`ERR_DUPLICATE_SERIAL_NUMBER` on collision), and the `slot_id` it physically sits in. Registration requires the machine to be `COMMISSIONING` or `ACTIVE` (`ERR_MACHINE_NOT_ACTIVE`) and the item to be `ACTIVE`, starts the unit `IN_STOCK`, and raises the slot's `on_hand_qty` by one, which may not push it past `capacity` (`ERR_CAPACITY_EXCEEDED`). While `IN_STOCK`, the unit's `issued_to_employee_id`, `last_inspected_on`, and `next_inspection_due_on` are all null, and its `inspection_log` — an append-only list of entries holding `inspected_on`, `result`, and `inspector_user_id` — stays empty until the first inspection. Units can be listed filtered by `item_id`, `slot_id`, `issued_to_employee_id`, or `status`.

Inspections move units through their regulated cycle. A `SafetyOfficer` records an inspection with a `result` and an `inspected_on` date. A `PASS` on a unit in `ISSUED` or `INSPECTION_DUE` returns it to — or keeps it in — `ISSUED`: `last_inspected_on` becomes the inspection date, `next_inspection_due_on` is recomputed as the inspection date plus the item's `inspection_interval_days`, and the log is appended; a voluntary early pass on an `ISSUED` unit is the same write. A `PASS` attempted on a unit in any other state is rejected with `ERR_SERIALIZED_UNIT_NOT_ISSUABLE`. A `FAIL` on an `ISSUED` or `INSPECTION_DUE` unit sends it to the terminal `QUARANTINED` state with the log appended and `issued_to_employee_id` retained for audit traceability. A `FAIL` on an `IN_STOCK` unit — incoming inspection rejecting stock — also quarantines with the log appended, and additionally decrements the slot's `on_hand_qty`, since the unit leaves sellable stock.

### 3.4. The Vend: Badge-Swipe Issuance at the Machine

The vend is the system's transactional heart: an `Employee` swipes at a machine and the API decides, in the fixed gate order of §2.10, whether product drops. The request names the `machine_id` and `slot_id`, the `qty`, a client `idempotency_key` (§2.9), and — when required — a `serialized_unit_id` and a `manager_override_id`; the employee's own identity is taken from the `X-User-ID` header, never from the payload. After shape, existence, and idempotency come the state gates: the employee must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`), the machine must be `ACTIVE` (`ERR_MACHINE_NOT_ACTIVE`), and the item must be `ACTIVE` (`ERR_ITEM_DISCONTINUED`).

Safety gates follow. For a `RESPIRATOR` item — one whose `requires_fit_test` is true — the employee's latest fit-test entry for that item must be a `PASS` that is not `EXPIRED`; no entry at all, a latest entry whose result is `FAIL`, or an expired entry each fail with `ERR_FIT_TEST_REQUIRED` (403). For a `FALL_PROTECTION` item, two further gates apply: the named unit must be issuable — currently `IN_STOCK`, otherwise `ERR_SERIALIZED_UNIT_NOT_ISSUABLE` — and the employee must not currently hold another unit of the same item in `INSPECTION_DUE` or `QUARANTINED`; holding such a lapsed unit fails with `ERR_REGULATED_ITEM_INSPECTION_DUE`.

Structural checks then pin the request to physical reality, evaluated in their pinned sub-order. First, the `slot_id` must belong to the named `machine_id` (`ERR_SLOT_ITEM_MISMATCH`). Second, a vend of a serialized item must name a `serialized_unit_id`, and a vend of a non-serialized item must not — either violation is `ERR_SERIALIZED_UNIT_REQUIRED`. Third, a serialized vend must request exactly one unit (`ERR_SERIALIZED_QTY_INVALID`). Fourth, the named unit must sit in the requested slot and be of the slot's item — a mismatch on either is `ERR_SLOT_ITEM_MISMATCH`. Capacity misuse and category misuse share this priority band in the order given in §2.10.

Entitlement and limits close the gate sequence. An issuance policy must exist pairing the employee's `job_role_id` with the item, otherwise `ERR_ITEM_NOT_ENTITLED`. The employee's rolling usage is then computed: the sum of `qty` over the employee's `POSTED` issuance lines for the item whose age — the logical clock minus the line's `vended_at` — is at least zero and at most the policy's `period_window_days` multiplied by twenty-four hours. A line whose age equals exactly that many hours still counts; a line one second older does not; `REVERSED` lines never count.

The effective limit builds on that usage in a pinned order. The base limit is the policy's `period_limit_qty`. The system then locates the unique `ACTIVE` override for this employee and item whose closed window from `valid_from` to `valid_until` covers the current date — uniqueness is guaranteed by the window-gap rule of §3.5 — and, when the request names a `manager_override_id`, that id must equal the covering override's id; an id that names no override, an inactive one, or one whose window does not cover today fails with `ERR_OVERRIDE_NOT_ACTIVE`. The effective limit is the base limit plus the override's `remaining_qty` when a covering override exists, and the base limit alone otherwise. The draw split decides who pays: if the current usage plus the requested `qty` stays within the base limit, `override_drawn_qty` is zero; beyond the base limit with a covering override, the needed draw equals usage plus `qty` minus the larger of the base limit and the current usage, it may not exceed the override's `remaining_qty` (`ERR_OVERRIDE_QTY_EXCEEDED`), and it becomes the line's `override_drawn_qty`; beyond the base limit with no covering override, the vend dies with `ERR_ISSUANCE_LIMIT_EXCEEDED`.

Pricing runs per line at vend time. The cumulative-before figure is the sum of `qty` over `POSTED` lines for the employee's home cost center and this item, vended within the same calendar month as the vend date — calendar months by the logical clock — measured strictly before this line. Candidate tiers are the item's contract price rows whose inclusive `effective_from`-to-`effective_to` window covers the vend date and whose `min_period_qty` is at most that cumulative; when candidates exist, the line's `unit_price_cents` comes from the candidate with the largest `min_period_qty`, ties broken by the latest `effective_from` and then the earliest `created_at`. When no tier breakpoint has been reached, the fallback ladder looks at rows covering the vend date regardless of breakpoint: if none cover, the price is the item's `base_list_price_cents`; otherwise the `unit_price_cents` of the covering row with the smallest `min_period_qty` under the same tie-breaks. The resolved `unit_price_cents` multiplied by `qty` gives `line_total_cents` — exact integer cents, no rounding.

A successful vend writes an issuance in `POSTED` status whose `item_id` is copied from the slot, whose `cost_center_id` is copied from the employee's `home_cost_center_id`, whose `vended_at` is the logical clock, and whose `chargeback_batch_id` stays null until a batch sweeps it. Physical effects land in the same breath: the slot's `on_hand_qty` drops by `qty`; a drawn override's `consumed_qty` rises by `override_drawn_qty` and flips the override to `CONSUMED` the moment consumption reaches `approved_qty`, leaving `remaining_qty` at zero; a serialized unit moves from `IN_STOCK` to `ISSUED`, stamping `issued_to_employee_id` with the vending employee and `next_inspection_due_on` with the vend date plus the item's `inspection_interval_days`. The slot, the drawn override if any, and the issued unit if any each increment their `version`, and the par-level restock trigger of §3.6 evaluates after the decrement. The issuance ledger can be read back filtered by any combination of `employee_id`, `machine_id`, `slot_id`, `item_id`, `cost_center_id`, `manager_override_id`, `serialized_unit_id`, `chargeback_batch_id`, or `status`.

### 3.5. Manager Overrides and Vend Reversals

Overrides are bounded, auditable capacity. A `Manager` grants one with the grantee's `employee_id`, the covered `item_id`, an `approved_qty` of extra units beyond policy (at least one), a closed validity window from `valid_from` to `valid_until` whose end may not precede its start, and a `reason_code` of `MEDICAL`, `NEW_HIRE`, `INCIDENT`, `PROJECT`, or `OTHER`. The granting identity is captured as `granted_by_user_id` from the header, and segregation of duties forbids granting to oneself — a grantor equal to the grantee's `employee_id` fails with `ERR_SELF_OVERRIDE_FORBIDDEN` (403). New grants start `ACTIVE` with `consumed_qty` at zero and `remaining_qty` reading `approved_qty` minus `consumed_qty`. Overrides are listable by `employee_id`, `item_id`, or `status`.

Windows for the same employee and item must keep their distance. Against every other `ACTIVE` override for the pair, the new closed interval must leave at least one full calendar day of separation: the new `valid_from` must fall at least two calendar days after the existing window's `valid_until`, or the new `valid_until` must fall at least two calendar days before the existing window's `valid_from`. A closer window is rejected with `ERR_OVERRIDE_WINDOW_OVERLAP`. This gap rule is what makes the covering override at vend time unique.

An override ends in one of three terminal ways. Consumption is automatic: the vend whose draw makes `consumed_qty` reach `approved_qty` moves the override to `CONSUMED` with `remaining_qty` at zero. Expiry arrives via the logical-clock sweep (§3.8): once the current date passes `valid_until`, an `ACTIVE` override becomes `EXPIRED`, while the `valid_until` day itself remains usable. Revocation is a `Manager`'s explicit act — revoking works only from `ACTIVE` (otherwise `ERR_OVERRIDE_NOT_ACTIVE`), preserves `consumed_qty` for audit, drops `remaining_qty` to zero, and the same transition also fires as the termination cascade of §3.2.

Reversal unwinds a vend without rewriting history. A `Manager` reverses an issuance currently in `POSTED` — any other state fails with `ERR_ISSUANCE_ALREADY_REVERSED` — and may never reverse their own vend: a reversing identity equal to the issuance's `employee_id` fails with `ERR_SELF_REVERSAL_FORBIDDEN` (403). When the line was already billed — its `chargeback_batch_id` names a batch in `CLOSED`, `DISPUTED`, or `SETTLED` — an `OPEN` batch for the same cost center must exist to absorb the adjustment, otherwise `ERR_NO_OPEN_CHARGEBACK_BATCH`.

The reversal's effects then land together. The slot's `on_hand_qty` rises by the vended `qty` — one unit for a serialized line — and if that restoration pushes the slot strictly above `par_level` while a restock order for the slot sits in `SUGGESTED`, the now-unneeded order is cancelled. A serialized unit returns from `ISSUED` to `IN_STOCK` with `issued_to_employee_id` and `next_inspection_due_on` cleared. The employee's rolling usage for the item falls by the reversed quantity, because usage is recomputed over `POSTED` rows only — but the override's `consumed_qty` is never restored: consumption is final, and the audit of §3.8 reconciles any divergence. An unbilled reversed line simply drops out of every future close sweep; a line billed in a non-open batch posts an `adjustment_cents` decrement equal to its `line_total_cents` onto the cost center's `OPEN` batch.

### 3.6. Restocking and Machine Service

Par levels drive replenishment. After any decrease of a non-serialized slot's `on_hand_qty` — in practice, a vend — the trigger fires when `on_hand_qty` is at or below `par_level` and no restock order for the slot is in `SUGGESTED` or `PICKED`: the system creates an order with `source` `AUTO_PAR` whose `qty` fills the slot to capacity, that is, `capacity` minus the current `on_hand_qty`. A slot sitting exactly at par triggers; one unit above par does not. Serialized fall-protection slots never auto-trigger — their stock moves one serialized registration at a time.

A `VendingTechnician` may also raise a restock order by hand, naming `machine_id`, `slot_id`, and a positive `qty`. The slot must belong to the machine (`ERR_SLOT_ITEM_MISMATCH`) and must hold a non-serialized item — a restock order against a serialized slot is rejected with `ERR_ITEM_NOT_SERIALIZED_CATEGORY` — and the item must still be `ACTIVE` (`ERR_ITEM_DISCONTINUED`). Manual orders start in `SUGGESTED` with `source` `MANUAL`, and their `qty` is exactly the requested amount: the naive fill-to-request variant. Every order, however created, also records a `suggested_qty` computed at creation as the committed-aware recommendation — `par_level` minus `on_hand_qty` minus the sum of `qty` over the slot's orders still in `SUGGESTED` or `PICKED`, floored at zero. The two variants diverge whenever on-hand stock or open orders are non-zero: the naive figures aim at capacity or the client request, while `suggested_qty` aims at par and discounts the pipeline already committed. Orders are listable by `machine_id`, `slot_id`, `item_id`, or `status`.

The order lifecycle is a short conveyor. Picking moves `SUGGESTED` to `PICKED`. Loading moves `PICKED` to `LOADED`, requires the machine to be `ACTIVE` or `OFFLINE` (`ERR_MACHINE_NOT_ACTIVE`), requires that `on_hand_qty` plus the order's `qty` not exceed `capacity` (`ERR_CAPACITY_EXCEEDED`), and on success adds the `qty` into `on_hand_qty`. Cancelling works from `SUGGESTED` or `PICKED` and lands in the terminal `CANCELLED` state; any pick, load, or cancel attempted from a disallowed state fails with `ERR_RESTOCK_ORDER_INVALID_STATE`. Two system cascades also cancel: a machine entering `IN_SERVICE` cancels every one of its orders in `SUGGESTED` or `PICKED`, and the reversal cascade of §3.5 cancels a `SUGGESTED` order made redundant by restored stock.

Service tickets schedule hands-on work. A `VendingTechnician` opens a ticket with the `machine_id`, an `issue_code` of `JAM`, `DOOR_FAULT`, `NETWORK`, `DISPLAY`, `PLANOGRAM_CHANGE`, or `PREVENTIVE`, and a half-open service window from `window_start` to `window_end`, the end strictly after the start. For the same machine, no other ticket in `OPEN` or `IN_PROGRESS` may intersect that half-open window — intersection fails with `ERR_SERVICE_WINDOW_OVERLAP` — while pure adjacency, one ticket's `window_end` equal to another's `window_start`, is allowed. New tickets start `OPEN` and are listable by `machine_id` or `status`.

Starting service is the consequential transition: the ticket must be `OPEN` (else `ERR_SERVICE_TICKET_INVALID_STATE`), the logical clock must fall within the half-open window — on or after `window_start` and before `window_end`, otherwise `ERR_SERVICE_WINDOW_NOT_REACHED` — and the machine must be `ACTIVE` or `OFFLINE` (`ERR_MACHINE_NOT_ACTIVE`). On start the ticket moves to `IN_PROGRESS`, the machine moves from `ACTIVE` or `OFFLINE` into `IN_SERVICE`, and every restock order of that machine in `SUGGESTED` or `PICKED` is cancelled. Resolution moves the ticket from `IN_PROGRESS` to `RESOLVED`, returns the machine from `IN_SERVICE` to `ACTIVE`, and runs the post-service restock sweep: for every slot of the machine whose item is non-serialized, whose `on_hand_qty` is at or below `par_level`, and which has no order in `SUGGESTED` or `PICKED`, an `AUTO_PAR` order is auto-created with `qty` equal to `capacity` minus `on_hand_qty`.

### 3.7. Chargeback Batches and Consumption Reporting

Cost centers are the billing target. A `FinanceAnalyst` registers each with a unique `cost_center_code` (such as CC-4100) and a display `name`; the running `ytd_charged_cents` starts at zero and thereafter holds the sum of `total_cents` over the center's batches in `CLOSED`, `DISPUTED`, or `SETTLED`, maintained as batches close and settle.

A chargeback batch opens for one `cost_center_id` over a half-open period from `period_start` to `period_end`, the end strictly after the start. Periods for the same cost center must not overlap under half-open comparison — `ERR_BATCH_PERIOD_OVERLAP` — while adjacency, one batch's `period_end` equal to the next's `period_start`, is allowed. A fresh batch is `OPEN` with `line_count`, `snapshot_total_cents`, `rerated_total_cents`, `admin_fee_cents`, and `total_cents` all reading zero, while `adjustment_cents` — always zero or negative — may already be accumulating the reversal adjustments of §3.5 for lines billed in this center's earlier non-open batches. Batches are listable by `cost_center_id` or `status`.

Closing is where the money is computed. The batch must be `OPEN` (`ERR_BATCH_INVALID_STATE`), and the close is refused with `ERR_EMPTY_CHARGEBACK_BATCH` unless the sweep set is non-empty or `adjustment_cents` is non-zero. The sweep stamps every issuance with this batch's `cost_center_id`, status `POSTED`, a null `chargeback_batch_id`, and a vend date on or after `period_start` and before `period_end` with this batch's id. `line_count` counts the swept lines, and `snapshot_total_cents` sums their stored `line_total_cents` — vend-time pricing, frozen.

The rerated total replays history. Swept `POSTED` lines are re-walked in chronological order — `vended_at` ascending, ties by `created_at` ascending — maintaining a running cumulative per item; each line re-resolves its tier against the contract price rows effective on its original vend date, taking the row with the largest `min_period_qty` not exceeding the running cumulative before that line (with the same fallback ladder and tie-breaks as vend-time pricing in §3.4), and the repriced line is the resolved unit price times its `qty`. `rerated_total_cents` is the sum of those repriced lines. Snapshot and rerate diverge precisely when a reversal removed lower-tier lines whose cumulative contribution had pushed later lines into a cheaper tier.

The administration fee rounds per line, never in aggregate. For each swept `POSTED` line, the fee is the line's rerated total multiplied by 250 ten-thousandths — two and a half percent — rounded half up to a whole cent; `admin_fee_cents` is the sum of those per-line fees. The rounding order is pinned: round each line first, then sum. Three 1350-cent lines make the difference concrete — each line's fee of 33.75 cents rounds to 34 and the three sum to 102, whereas summing first would round 101.25 to 101 and understate the fee by a cent. The batch's `total_cents` is then the rerated total plus `adjustment_cents` plus `admin_fee_cents`, and the cost center's `ytd_charged_cents` rises by exactly that `total_cents`.

After close, two fates remain. A `Manager` disputes a `CLOSED` batch, moving it to `DISPUTED`; a `FinanceAnalyst` settles a batch in `CLOSED` or `DISPUTED`, moving it to the terminal `SETTLED`. Any close, dispute, or settle attempted from the wrong state fails with `ERR_BATCH_INVALID_STATE`.

For live consumption visibility, a computed read returns, for a `cost_center_id` and a half-open period from `period_start` to `period_end`, an aggregate over the `POSTED` (non-reversed) issuance lines of that cost center in the window: the `line_count`, the `total_qty` of units vended, and the `total_amount_cents` they sum to.

### 3.8. Compliance Audits and Clock-Driven Sweeps

Audits examine the two compliance surfaces. A `ComplianceAuditor` opens a case with a `scope` of `OVERRIDE_USAGE` or `INSPECTION_COMPLIANCE` and a closed period from `period_start` to `period_end`, the end not preceding the start; the case begins in `DRAFT` with `exceptions_count` at zero and `findings_detail` empty. Beginning fieldwork moves `DRAFT` to `FIELDWORK` and is refused while any chargeback batch whose period overlaps the audit's closed interval — closed-interval overlap on both sides — remains `OPEN` (`ERR_OPEN_BATCHES_EXIST`). Filing findings moves `FIELDWORK` to `FINDINGS_FILED` and computes the findings; closing moves `FINDINGS_FILED` to the terminal `CLOSED`. Each of these three transitions attempted from the wrong state fails with `ERR_AUDIT_INVALID_STATE`.

Findings are scope-specific. Under `OVERRIDE_USAGE`, every manager override — of any status — whose closed window from `valid_from` to `valid_until` intersects the audit's closed period, and whose `consumed_qty` differs from the sum of `override_drawn_qty` over the `POSTED` issuance lines referencing it, becomes a finding whose `finding_type` is `OVERRIDE_CONSUMPTION_MISMATCH` and whose `entity_id` is the override's id; this is the rule that reconciles the finality of `consumed_qty` against reversed vends. Under `INSPECTION_COMPLIANCE`, every serialized unit sitting in `INSPECTION_DUE` or `QUARANTINED` at the moment findings are filed becomes a finding whose `finding_type` is `UNIT_INSPECTION_LAPSED`. In both scopes `exceptions_count` is the number of findings, and each `findings_detail` entry carries its `finding_type`, `entity_id`, and free-text `detail`.

Three sweeps ride on every logical-clock set, all at date granularity. The override-expiry sweep moves an `ACTIVE` override whose `valid_until` is now in the past to `EXPIRED`; a current date equal to `valid_until` keeps the override `ACTIVE`, the closed interval still in force. The inspection sweep moves an `ISSUED` unit whose `next_inspection_due_on` is now in the past to `INSPECTION_DUE` — the due date itself keeps the unit `ISSUED`, with the unit becoming due the following day — and moves an `INSPECTION_DUE` unit more than thirty full days past due, a current date later than `next_inspection_due_on` plus thirty days, to `QUARANTINED` without appending any `inspection_log` entry; exactly thirty days past keeps the unit in `INSPECTION_DUE`, with quarantine landing on day thirty-one. The fit-test sweep moves a `VALID` fit-test entry whose `expires_on` is now in the past to `EXPIRED`; the expiry date itself remains valid.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — lifecycle transitions, slot edits, fit-test recording, inspections, picks, loads, cancels, closes, disputes, settles — return `200 OK`, as do all reads. The table below is a routing summary only; request fields, preconditions, and side effects for each operation are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cost-centers` | Create a cost center | FinanceAnalyst |
| GET | `/cost-centers/{costCenterId}` | Get a cost center | Any |
| POST | `/job-roles` | Create a job role | EHSAdministrator |
| GET | `/job-roles/{jobRoleId}` | Get a job role | Any |
| POST | `/items` | Create a catalog item | EHSAdministrator |
| GET | `/items/{itemId}` | Get an item | Any |
| POST | `/items/{itemId}/discontinue` | Discontinue an item | EHSAdministrator |
| POST | `/contract-prices` | Create a contract price tier row for an item | EHSAdministrator |
| GET | `/contract-prices` | List contract prices (filter by `item_id`) | Any |
| GET | `/contract-prices/{priceId}` | Get a contract price row | Any |
| POST | `/issuance-policies` | Create an issuance policy line (job role entitlement) | EHSAdministrator |
| GET | `/issuance-policies` | List issuance policies (filter by `job_role_id` and/or `item_id`) | Any |
| GET | `/issuance-policies/{policyId}` | Get an issuance policy | Any |
| POST | `/employees` | Create an employee | EHSAdministrator |
| GET | `/employees` | List employees (filter by job role, cost center, or status) | Any |
| GET | `/employees/{employeeId}` | Get an employee | Any |
| PUT | `/employees/{employeeId}` | Update employee status, job role, cost center, or manager flag | EHSAdministrator |
| POST | `/employees/{employeeId}/fit-tests` | Record a respirator fit test for an employee | SafetyOfficer |
| POST | `/machines` | Register a vending machine | VendingTechnician |
| GET | `/machines` | List machines (filter by status) | Any |
| GET | `/machines/{machineId}` | Get a machine | Any |
| PUT | `/machines/{machineId}` | Machine lifecycle transitions: commission, take offline, restore, decommission | VendingTechnician |
| POST | `/machines/{machineId}/slots` | Create a planogram slot (OCC-guarded) | VendingTechnician |
| GET | `/machines/{machineId}/slots` | List planogram slots of a machine | Any |
| GET | `/slots` | List slots across machines (filter by item or machine) | Any |
| GET | `/slots/{slotId}` | Get a slot | Any |
| PUT | `/slots/{slotId}` | Update a planogram slot (OCC-guarded) | VendingTechnician |
| POST | `/serialized-units` | Register a serialized fall-protection unit into a slot | EHSAdministrator |
| GET | `/serialized-units` | List serialized units | Any |
| GET | `/serialized-units/{unitId}` | Get a serialized unit | Any |
| POST | `/serialized-units/{unitId}/inspect` | Record an inspection of a serialized unit | SafetyOfficer |
| POST | `/manager-overrides` | Grant a manager override for beyond-limit issuance | Manager |
| GET | `/manager-overrides` | List overrides | Any |
| GET | `/manager-overrides/{overrideId}` | Get an override | Any |
| POST | `/manager-overrides/{overrideId}/revoke` | Revoke an ACTIVE override | Manager |
| POST | `/issuances` | Vend PPE to the calling employee (badge swipe); idempotent | Employee |
| GET | `/issuances` | List issuances | Any |
| GET | `/issuances/{issuanceId}` | Get an issuance | Any |
| POST | `/issuances/{issuanceId}/reverse` | Reverse a POSTED issuance (segregation of duties enforced) | Manager |
| POST | `/restock-orders` | Manually create a restock order for a non-serialized slot | VendingTechnician |
| GET | `/restock-orders` | List restock orders | Any |
| GET | `/restock-orders/{orderId}` | Get a restock order | Any |
| POST | `/restock-orders/{orderId}/pick` | Pick a SUGGESTED restock order | VendingTechnician |
| POST | `/restock-orders/{orderId}/load` | Load a PICKED restock order into the machine slot | VendingTechnician |
| POST | `/restock-orders/{orderId}/cancel` | Cancel a SUGGESTED or PICKED restock order | VendingTechnician |
| POST | `/service-tickets` | Open a service ticket with a half-open service window | VendingTechnician |
| GET | `/service-tickets` | List service tickets | Any |
| GET | `/service-tickets/{ticketId}` | Get a service ticket | Any |
| POST | `/service-tickets/{ticketId}/start` | Start service within its window | VendingTechnician |
| POST | `/service-tickets/{ticketId}/resolve` | Resolve an IN_PROGRESS ticket | VendingTechnician |
| POST | `/chargeback-batches` | Open a chargeback batch for a cost center and period | FinanceAnalyst |
| GET | `/chargeback-batches` | List chargeback batches | Any |
| GET | `/chargeback-batches/{batchId}` | Get a chargeback batch | Any |
| POST | `/chargeback-batches/{batchId}/close` | Close an OPEN batch: sweep lines, compute totals, bump year-to-date | FinanceAnalyst |
| POST | `/chargeback-batches/{batchId}/dispute` | Dispute a CLOSED batch | Manager |
| POST | `/chargeback-batches/{batchId}/settle` | Settle a CLOSED or DISPUTED batch | FinanceAnalyst |
| POST | `/compliance-audits` | Create a compliance audit case | ComplianceAuditor |
| GET | `/compliance-audits/{auditId}` | Get a compliance audit | Any |
| POST | `/compliance-audits/{auditId}/begin-fieldwork` | Begin fieldwork (requires no overlapping OPEN batches) | ComplianceAuditor |
| POST | `/compliance-audits/{auditId}/file-findings` | Compute and file findings | ComplianceAuditor |
| POST | `/compliance-audits/{auditId}/close` | Close a FINDINGS_FILED audit | ComplianceAuditor |
| GET | `/reports/consumption` | Consumption report for a cost center over a half-open period | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the system sweeps | EHSAdministrator |

## 5. Error Code Catalogue

The catalogue below maps every error identifier to its HTTP status code. Trigger conditions for each error are specified in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_VALIDATION_FAILED` | 400 Bad Request |
| `ERR_COST_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_ROLE_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_PRICE_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 Not Found |
| `ERR_MACHINE_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_SERIALIZED_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_MANAGER_OVERRIDE_NOT_FOUND` | 404 Not Found |
| `ERR_ISSUANCE_NOT_FOUND` | 404 Not Found |
| `ERR_RESTOCK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGEBACK_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLIANCE_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_MACHINE_NOT_ACTIVE` | 409 Conflict |
| `ERR_MACHINE_NO_PLANOGRAM` | 409 Conflict |
| `ERR_ITEM_DISCONTINUED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_OVERRIDE_NOT_ACTIVE` | 409 Conflict |
| `ERR_SERIALIZED_UNIT_NOT_ISSUABLE` | 409 Conflict |
| `ERR_RESTOCK_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_SERVICE_TICKET_INVALID_STATE` | 409 Conflict |
| `ERR_BATCH_INVALID_STATE` | 409 Conflict |
| `ERR_AUDIT_INVALID_STATE` | 409 Conflict |
| `ERR_ISSUANCE_ALREADY_REVERSED` | 409 Conflict |
| `ERR_FIT_TEST_REQUIRED` | 403 Forbidden |
| `ERR_REGULATED_ITEM_INSPECTION_DUE` | 409 Conflict |
| `ERR_SERVICE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OVERRIDE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CONTRACT_PRICE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_BATCH_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SERVICE_WINDOW_NOT_REACHED` | 409 Conflict |
| `ERR_SLOT_ITEM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SERIALIZED_UNIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SERIALIZED_QTY_INVALID` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_SERIALIZED_CATEGORY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMPLOYEE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_MACHINE_LOCATION` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_SLOT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_POLICY` | 409 Conflict |
| `ERR_SELF_OVERRIDE_FORBIDDEN` | 403 Forbidden |
| `ERR_SELF_REVERSAL_FORBIDDEN` | 403 Forbidden |
| `ERR_ITEM_NOT_ENTITLED` | 422 Unprocessable Entity |
| `ERR_ISSUANCE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_OVERRIDE_QTY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EMPTY_CHARGEBACK_BATCH` | 422 Unprocessable Entity |
| `ERR_OPEN_RESTOCK_ORDERS_EXIST` | 409 Conflict |
| `ERR_OPEN_SERVICE_TICKETS_EXIST` | 409 Conflict |
| `ERR_OPEN_BATCHES_EXIST` | 409 Conflict |
| `ERR_NO_OPEN_CHARGEBACK_BATCH` | 409 Conflict |

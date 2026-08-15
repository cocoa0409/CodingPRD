# Pump & Valve Repair / Rebuild Center API — Product Requirements Document

## 1. Introduction

Industrial operators running critical rotating and pressure-containing equipment — refineries mid-turnaround, chemical plants inside a shutdown window, power stations nursing a degrading pump — depend on service centers that can take a failed unit in over the dock, tear it down, quote the work honestly, repair it against a measurable acceptance standard, and certify it before the outage window closes. This document specifies the API for such a Pump & Valve Repair / Rebuild Center: a Flowserve-style service operation that manages serialized pumps, general valves, and safety-relief valves from equipment intake and nameplate capture through teardown inspection, quotation, shop repair, performance test verification, certification tagging, and final closeout.

The system coordinates several concerns that pull against each other in a real shop. Quoting must respect each customer's credit limit while prices flex with turnaround-season shop loading; a surge multiplier rewards pool-program membership and charges surge-priority work, but never beyond a fixed floor and cap. Parts obsolescence can invalidate a quote the customer is actively reviewing, forcing a revision with aftermarket substitution. Safety-relief valves demand segregation of duties between the technician who assembles the valve and the certifier who stamps its tag. Customers enrolled in the rotable spare pool can exchange a failed unit rather than wait for its repair, and every close or cancellation must settle window reservations, pool positions, and warranty bookkeeping consistently. A server-managed logical clock — never wall time — drives quote validity periods and warranty day-counts so that all time-dependent behavior is deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the declared roles. A request whose `X-User-Role` header is missing or does not name a declared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

Seven roles are recognized. `ServiceManager` is the service-center manager, owning customer onboarding, the parts catalog, quoting, certification voids, and the logical clock. `IntakeCoordinator` is the front desk, handling equipment intake and nameplate capture, pool administration, and shipping and closeout. `Inspector` is the teardown inspector who authors and finalizes inspection reports. `Technician` performs repair, assembly, and test runs. `Certifier` is the certified SRV inspector who issues certification tags. `Planner` is the turnaround and shutdown planner who manages capacity windows. `Customer` is the external customer organization, which approves or declines quotes, withdraws its own pool units, and may intake its own repair orders. Any attempt to perform an operation outside the caller's role, or by a customer against another customer's resource, is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`. When `X-User-Role` is `ServiceManager`, `IntakeCoordinator`, `Inspector`, `Technician`, `Certifier`, or `Planner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server records it where a workflow writes it — for example as `inspector_id` on an inspection report, `assembled_by_id` on a repair order, `tested_by_id` on a test run, or `certified_by_id` on a certification — but does not compare it to any entity's `id`.

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

### 2.3. Pagination, Sorting, and List Filtering

List endpoints paginate through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Several list endpoints also accept filters as query parameters. The asset list filters by `customer_id`. The repair order list filters by `customer_id`, `asset_id`, `status`, `capacity_window_id`, or `warranty_parent_ro_id`. The quote list filters by `repair_order_id`, `capacity_window_id`, `status`, or `supersedes_quote_id`. The parts list filters by `status` or `superseded_by_id`. The pool unit list filters by `customer_id`, `asset_id`, `pool_status`, or `reserved_for_ro_id`.

### 2.4. The Logical Clock

All timestamps and all date arithmetic in the system run on a server-managed logical clock, never on wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, every read of the current instant returns this default. A `ServiceManager` may advance the clock through the `POST /_clock/set_current_utc` capability by supplying a `to_iso8601` instant; the response carries the new `current_utc`. Every system-stamped timestamp — `created_at`, `issued_at`, `expires_at`, `closed_at` — and every time-dependent rule, including lazy quote expiry and warranty day-counts, observes the logical clock from the moment it is advanced.

### 2.5. Common Resource Properties and Mutation Semantics

Every resource in the system — customers, assets, repair orders, inspection reports, quotes, parts, pool units, test runs, certifications, and capacity windows — carries four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed upon any change to the resource's properties. `version` is an integer that increments by one with every mutation of the resource.

Version increments apply to system-driven mutations exactly as they do to client-requested ones. Every repair order state transition — including the automatic transitions triggered by a finalized inspection report, an approved quote, a recorded test run, or an issued or voided certification — increments the repair order's `version` by one and refreshes its `updated_at`. Creating a new quote revision is likewise a mutation of the repair order and increments its `version` by one. Cascades that change a capacity window's reserved hours or a pool unit's status are mutations of those resources in their own right.

### 2.6. Request Validation Order and Nested Path Resolution

Incoming requests are validated in a fixed priority order; a failure at an earlier tier is never masked by a later one.

1. **Authentication** — the `X-User-Role` header must be present and name a declared role (`ERR_UNAUTHENTICATED`, HTTP 401).
2. **Request-body shape** — required fields present, enum values valid, date and datetime formats valid, and the conditional nameplate fields present per equipment class (`ERR_VALIDATION`, HTTP 400).
3. **Authorization** — the role must be permitted for the endpoint, and a `Customer` caller may act only on resources whose `customer_id` equals its `X-User-ID` (`ERR_FORBIDDEN`, HTTP 403).
4. **Existence** — path-referenced and body-referenced resources must exist, validated left to right (`ERR_NOT_FOUND`, HTTP 404).
5. **State validity** — the target entity must be in a valid from-state for the requested transition, terminal states are locked, and the quote-creation version check must match (`ERR_INVALID_STATE`, HTTP 409; the version mismatch carries `ERR_STALE_VERSION`, HTTP 412, on quote creation). On the certification-issuing endpoint, the permanent applicability gate is evaluated first within this tier: a repair order that does not require certification is rejected with `ERR_CERTIFICATION_NOT_APPLICABLE` before any from-state evaluation would produce `ERR_INVALID_STATE`.
6. **Certification safety** — segregation of duties and set-pressure tolerance (`ERR_SOD_VIOLATION` and `ERR_SET_PRESSURE_OUT_OF_TOLERANCE`, HTTP 422), evaluated only on certification issuance.
7. **Temporal intervals** — capacity-window half-open overlap, asset service-window overlap, and lazy quote expiry (`ERR_WINDOW_OVERLAP`, `ERR_ASSET_WINDOW_OVERLAP`, `ERR_QUOTE_EXPIRED`, HTTP 409).
8. **Referenced-entity usability** — supersession target active, pool unit and repair order under the same customer, substitution target obsolete, warranty parent eligible (`ERR_SUPERSEDES_NOT_ACTIVE`, `ERR_POOL_CUSTOMER_MISMATCH`, `ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE`, `ERR_WARRANTY_NOT_ELIGIBLE`, HTTP 409).
9. **Domain constraints** — an obsolete part quoted without substitution (`ERR_PART_OBSOLETE`), substitution where aftermarket use is not allowed (`ERR_SUBSTITUTION_NOT_ALLOWED`), a full capacity window (`ERR_WINDOW_FULL`), an approval that would exceed window capacity (`ERR_WINDOW_CAPACITY_EXCEEDED`), a duplicate inspection report (`ERR_REPORT_ALREADY_EXISTS`), a missing assembly record (`ERR_ASSEMBLY_NOT_RECORDED`), and the pool and exchange rules (`ERR_POOL_UNIT_UNAVAILABLE`, `ERR_EXCHANGE_NOT_REQUESTED`, `ERR_POOL_PROGRAM_REQUIRED`), all HTTP 409.
10. **Fiscal limit** — a quote total above the customer's credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422), evaluated only on quote approval.

For nested paths — inspection reports, test runs, and certifications addressed beneath a repair order identifier — existence validation runs strictly left to right: the repair order is located first, and a request beneath a non-existent repair order is rejected with `ERR_NOT_FOUND` before any child resource is examined.

### 2.7. Optimistic Concurrency Control on Quote Creation

Quote creation is the one write endpoint guarded by optimistic concurrency control. A request creating a quote revision must carry `expected_repair_order_version`, a non-optional input holding the `version` of the target repair order as the client last observed it. If that value does not match the repair order's current `version` — most commonly because a prior successful quote creation legitimately superseded the client's base revision and advanced the order's version — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no quote is created. Endpoints other than quote creation neither accept nor require a version field.

### 2.8. Monetary Precision and Rounding

All money is handled as integer cents: part prices, labor rates, quote totals, credit limits, and invoiced amounts alike. Wherever a calculation produces a fractional cent, the value is rounded half-up to a whole cent. Quote part lines are rounded per line, half-up, before any summation; rounding the sum instead of each line produces a different, non-conforming result. Percentages used in test evaluation are rounded half-up to two decimal places, and every tolerance comparison uses those rounded values. The surge multiplier is expressed to two decimal places and, once stored on a quote, never changes.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding, Credit Terms, and the Rotable Pool Program

A `ServiceManager` onboards each customer organization with its `name`, a billing `account_number` that must be unique across customers, a `credit_limit_cents` bounding approved quote totals, and `warranty_terms_days`, the length of warranty coverage in days running from a prior closed repair. The `pool_program` flag marks participation in the rotable spare pool program and defaults to false when omitted. At onboarding the customer's `pool_available_count` starts at zero; thereafter it counts the customer's pool units whose `pool_status` is `IN_POOL` or `RESERVED` — `ISSUED` and `WITHDRAWN` units are not available — and is recomputed whenever a unit is enrolled, issued, or withdrawn.

Under the pool program, an `IntakeCoordinator` enrolls a serialized unit by submitting the owning `customer_id` and the unit's `asset_id`; enrollment for a customer whose `pool_program` is false is rejected with `ERR_POOL_PROGRAM_REQUIRED`. A newly enrolled unit starts `IN_POOL`. Pool units move through four statuses — `IN_POOL`, `RESERVED`, `ISSUED`, and `WITHDRAWN` — of which the last two are terminal. Reserving a unit binds it to an exchange: the coordinator names the target `repair_order_id`, and the reservation is permitted only when that repair order exists and is non-terminal, belongs to the same customer as the unit (a mismatch is rejected with `ERR_POOL_CUSTOMER_MISMATCH`), and has `exchange_requested` set (otherwise the reservation is rejected with `ERR_EXCHANGE_NOT_REQUESTED`). A successful reservation moves the unit `IN_POOL` → `RESERVED` and records the order on `reserved_for_ro_id`. Releasing a reservation returns the unit `RESERVED` → `IN_POOL` and clears `reserved_for_ro_id` to null. A customer may pull its own unit out of the pool, and a coordinator may withdraw on the customer's behalf; withdrawal moves the unit `IN_POOL` → `WITHDRAWN`.

### 3.2. Equipment Registration and Nameplate Capture

Every serialized unit entering the shop is registered as an asset by an `IntakeCoordinator`, capturing the owning `customer_id` and the nameplate data: `serial_number` (unique within the customer), `equipment_class`, `manufacturer`, and `model`. The `equipment_class` is one of `PUMP`, `GENERAL_VALVE`, or `SAFETY_RELIEF_VALVE`, and it drives two conditional nameplate fields. A pump must carry `rated_flow_gpm`, its nameplate rated flow in gallons per minute, and that field must be omitted or null on the other two classes. A safety-relief valve must carry `set_pressure_psig`, its nameplate set pressure, which likewise must be omitted or null for pumps and general valves. A missing or misplaced conditional nameplate field is rejected with `ERR_VALIDATION`.

Each asset also selects the acceptance standard used to judge its test runs. The `test_standard` is either `API_610_PER_POINT` or `SHOP_WEIGHTED_AVG`, defaulting to `SHOP_WEIGHTED_AVG` when intake leaves it unspecified. The choice is sticky: it selects the verdict variant evaluated on every test run recorded against repair orders for that asset (§3.7).

### 3.3. Repair Order Intake, Warranty Eligibility, and Service Windows

A repair order is opened by an `IntakeCoordinator`, or by the `Customer` role for its own equipment — in which case the payload's `customer_id` must equal the caller's `X-User-ID`. Intake captures the `asset_id` of the serialized unit in for repair, a `failure_mode` of `SEAL_LEAK`, `BEARING_FAILURE`, `CAVITATION`, `SEAT_LEAKAGE`, `SPRING_DRIFT`, or `OTHER`, a free-text `failure_description`, and an `intake_priority` of `STANDARD` or `SURGE` for turnaround and shutdown surge work. The planned service window runs from `planned_start_date` through `planned_end_date`, both calendar dates, and the window is a closed interval — inclusive at both ends. Two non-terminal repair orders for the same asset may not hold overlapping planned windows; because the interval is closed, even touching endpoints conflict, and an overlapping intake is rejected with `ERR_ASSET_WINDOW_OVERLAP`. The `estimated_bay_hours` field — the shop time later reserved against a capacity window at approval — must be a positive whole number of hours.

An order opens in `RECEIVED` with `repair_round` at zero and `repair_outcome` at `NONE`. Its full status vocabulary is `RECEIVED`, `IN_INSPECTION`, `QUOTE_IN_PROGRESS`, `AUTHORIZED`, `IN_REPAIR`, `IN_TEST`, `READY_FOR_CERT`, `COMPLETE`, `CLOSED`, and `CANCELLED`, the last two terminal. The `requires_certification` flag is derived from the asset: true exactly when the unit is a `SAFETY_RELIEF_VALVE`. A customer unwilling to wait out a repair sets `exchange_requested` (default false), which permits a pool reservation against the order (§3.1) and obliges one at approval time (§3.6). The `capacity_window_id` and `assembled_by_id` fields remain null until quote approval and assembly logging respectively, while `invoiced_total_cents` and `closed_at` remain null until closeout, and `quote_attention_required` stays false unless parts obsolescence forces a quote revision (§3.5).

Warranty work enters through `warranty_parent_ro_id`, naming the prior closed repair this order claims warranty against. Eligibility requires every one of the following: the parent order exists and is `CLOSED`; it covers the same `asset_id`; it belongs to the same `customer_id`; and the whole days between the parent's `closed_at` and the current logical clock — elapsed seconds divided by 86,400 and rounded down — do not exceed the customer's `warranty_terms_days`. The day boundary is inclusive: an intake exactly `warranty_terms_days` days after the parent's closure still qualifies. Failing any condition rejects the creation with `ERR_WARRANTY_NOT_ELIGIBLE`. When eligibility holds, the new order's `warranty_case` is set true — which later forces the `WARRANTY` pricing variant on its quotes — and `repeat_failure_flag` is set true exactly when the parent's `failure_mode` matches the new order's, feeding re-repair analysis. An order created without `warranty_parent_ro_id` is ordinary commercial work with `warranty_case` false.

### 3.4. Teardown Inspection and Findings Finalization

From `RECEIVED`, an `IntakeCoordinator` starts teardown, moving the order `RECEIVED` → `IN_INSPECTION`. An `Inspector` then authors the teardown inspection report with a `findings_summary` narrative, a `recommended_action` of `REPAIR`, `REPLACE`, or `RETURN_UNREPAIRED`, the inspector's `estimated_labor_hours` estimate, and the `part_lines` the job requires — each line a `part_id` referencing a catalog part together with a `quantity`. The creating inspector's `X-User-ID` is recorded as `inspector_id`, and the report begins with `report_status` `DRAFT`. One repair order carries at most one inspection report; a second authoring attempt against the same order is rejected with `ERR_REPORT_ALREADY_EXISTS`, so listing an order's reports returns zero or one element. Authoring against an order that has left `IN_INSPECTION` is rejected with `ERR_INVALID_STATE`.

Finalizing the report moves it `DRAFT` → `FINALIZED`, from which it is immutable — no further writes are accepted. Finalization is permitted only while the order is still `IN_INSPECTION`, and it automatically drives the order `IN_INSPECTION` → `QUOTE_IN_PROGRESS`, incrementing the repair order's `version` by one. An order without a finalized report never reaches quoting.

### 3.5. Quote Composition, Pricing, and Catalog Substitutions

While an order sits in `QUOTE_IN_PROGRESS`, a `ServiceManager` composes a quote revision naming the `repair_order_id`, the `capacity_window_id` of the capacity window the work is planned into, the quoted `labor_hours`, the hourly `labor_rate_cents`, and the quoted `part_lines` — each line carrying a `part_id`, a `quantity`, a `unit_price_cents` sell price, and optionally `substitution_for_part_id` naming the obsolete OEM part this line substitutes. Because the order may have advanced since the client last read it, the request must also carry `expected_repair_order_version` matching the order's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7, and composing against an order that has left `QUOTE_IN_PROGRESS` is rejected with `ERR_INVALID_STATE`.

Revisions are counted per repair order: the first quote is `revision` 1 with `supersedes_quote_id` null, and each subsequent creation increments the counter, marks every prior non-terminal quote for that order — any quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — as `SUPERSEDED`, and points `supersedes_quote_id` at the immediately prior non-terminal revision. A quote's full status vocabulary is `DRAFT`, `ISSUED`, `REVISION_REQUESTED`, `APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED`, and `CANCELLED`, the last five terminal. Creating a quote increments the repair order's `version` by one, which is precisely what invalidates a stale `expected_repair_order_version` on the next attempt.

Pricing attaches three computed fields to the quote. The `pricing_variant` is `WARRANTY` when the repair order's `warranty_case` is true, otherwise `COMMERCIAL`. The `surge_multiplier_applied` snapshots the surge multiplier at creation time (§3.6) and never changes afterward. The totals follow a pinned rounding order. Each part line's total is its `quantity` multiplied by its `unit_price_cents`, reduced by a fifty-percent parts discount only when the variant is `WARRANTY`, with each line's result rounded half-up to a whole cent before any summation. The `parts_subtotal_cents` is the sum of those already-rounded per-line totals. The `labor_cents` is `labor_hours` multiplied by `labor_rate_cents`, rounded half-up to a whole cent — except on a `WARRANTY` quote, where labor is free and `labor_cents` is zero. The `total_cents` is the sum of `parts_subtotal_cents` and `labor_cents`, multiplied by `surge_multiplier_applied`, with the final amount rounded half-up to a whole cent.

The parts catalog is owned by the `ServiceManager`. Each part is created `ACTIVE` with a unique `part_number`, a `description`, a current sell price in `unit_price_cents`, and an `aftermarket_allowed` flag — default false — that governs whether an aftermarket substitute may replace the part once it is obsolete. Marking a part obsolete moves it `ACTIVE` → `OBSOLETE`; an optional `superseded_by_id` may record the replacement part, but that target must exist, be `ACTIVE`, and not be the part itself, and any violation is rejected with `ERR_SUPERSEDES_NOT_ACTIVE`. Obsolescence then cascades into open quoting work in two links. First, every quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` whose `part_lines` contain the part has those lines flagged `substitution_required`. Second, every such quote still `ISSUED` is forced `ISSUED` → `REVISION_REQUESTED`, and its repair order's `quote_attention_required` flag is set true — the customer sees a revision request they never asked for.

Substitution carries its own rules, enforced when a quote is issued (§3.6): a line's `substitution_for_part_id` must reference a part that is `OBSOLETE`, and that obsolete part must have `aftermarket_allowed` true.

### 3.6. Quote Negotiation, Capacity Windows, and the Approval Gate

Turnaround-season shop loading is modeled with capacity windows. A `Planner` creates each window with a `label`, a `window_start`, a `window_end` that must be strictly later than the start (otherwise `ERR_VALIDATION`), and a positive whole number of `bay_hours_capacity`. Windows are half-open intervals — the start inclusive, the end exclusive — and a new window may not overlap an existing one; adjacency is allowed, and an overlapping creation is rejected with `ERR_WINDOW_OVERLAP`. A new window starts with `bay_hours_reserved` zero and `window_posture` `NORMAL`.

A window's `bay_hours_reserved` is the sum of `estimated_bay_hours` over the repair orders planned into it whose status is `AUTHORIZED`, `IN_REPAIR`, `IN_TEST`, `READY_FOR_CERT`, or `COMPLETE`; orders that close or cancel release their hours and reserve nothing. From the reserved figure the `window_posture` derives: the window is `FULL` when reserved hours meet or exceed capacity; short of that, it is `SURGE` when reserved hours meet or exceed the smallest whole number that is at least eighty percent of capacity — a 101-hour window turns `SURGE` at 81 reserved hours; otherwise it is `NORMAL`. Both thresholds are inclusive, so reserved hours exactly equal to capacity is `FULL`.

The surge multiplier snapshot at quote creation reads this posture. The multiplier starts at 1.00, or at 1.25 when the referenced window's posture at creation time is `SURGE`. When the referenced window's posture is `FULL`, quote creation is rejected outright with `ERR_WINDOW_FULL` — no multiplier is produced and no quote is stored. A repair order whose `intake_priority` is `SURGE` adds 0.15 to the multiplier, and membership in the customer's pool program subtracts 0.10. The result is then clamped: it never falls below 1.00 and never exceeds 1.50, expressed to two decimal places. On a `WARRANTY` quote the multiplier is forced to exactly 1.0 regardless of posture, priority, or pool membership.

Issuing a quote moves it `DRAFT` → `ISSUED` and stamps `issued_at` with the logical clock and `expires_at` fourteen days later; before issuance both fields are null. Issuance validates every part line: a line referencing an `OBSOLETE` part without a valid substitution is rejected with `ERR_PART_OBSOLETE`; a line whose `substitution_for_part_id` references a part that is not `OBSOLETE` is rejected with `ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE`; and a line substituting an obsolete part whose `aftermarket_allowed` is false is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`.

Once `ISSUED`, the quote belongs to the customer to answer, and time works against it: any read or action on an `ISSUED` quote when the logical clock has reached or passed `expires_at` first transitions the quote to `EXPIRED`, and the requested action is rejected with `ERR_QUOTE_EXPIRED`. The owning customer may approve, request a revision, or decline. Approval evaluates its gates in validation-priority order — the lazy-expiry check first, then the window-capacity and pool-unit constraints, and the credit check last, so an over-credit quote on an over-capacity window surfaces the capacity error. The capacity gate requires that the window absorb the order: the window's current `bay_hours_reserved` plus the order's `estimated_bay_hours` must not exceed `bay_hours_capacity`, with equality permitted; an overflow is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED`. When the order's `exchange_requested` is set, a pool unit must already stand `RESERVED` with `reserved_for_ro_id` pointing at this order, else approval is rejected with `ERR_POOL_UNIT_UNAVAILABLE`. Finally, `total_cents` must not exceed the customer's `credit_limit_cents` — equality is allowed — else approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

An approved quote cascades in three links: the repair order moves `QUOTE_IN_PROGRESS` → `AUTHORIZED`; the quote's `capacity_window_id` is copied onto the order; and the order's `estimated_bay_hours` are added to the window's `bay_hours_reserved`, recomputing `window_posture`, which may flip `NORMAL` → `SURGE` or `SURGE` → `FULL`. The repair order's `version` increments by one. Requesting a revision moves the quote `ISSUED` → `REVISION_REQUESTED` with no further effects. Declining moves it `ISSUED` → `DECLINED` and cascades the repair order `QUOTE_IN_PROGRESS` → `CANCELLED`, carrying the cancellation's own side effects — notably the release of any pool reservation (§3.9). Both customer answers are subject to the same lazy expiry as approval.

### 3.7. Shop Execution and the Repair–Test Rework Loop

With an approved quote behind it, a `Technician` starts repair, moving the order `AUTHORIZED` → `IN_REPAIR`; the precondition is that an `APPROVED` quote exists for the order, and without one the transition is rejected with `ERR_INVALID_STATE`. During repair the technician logs assembly, recording the caller's `X-User-ID` as the order's `assembled_by_id`; the log is repeatable while the order remains `IN_REPAIR`, and the latest call wins. Submitting the order for test moves it `IN_REPAIR` → `IN_TEST` — but an order whose `requires_certification` is true needs an assembly record first: submitting with no `assembled_by_id` logged is rejected with `ERR_ASSEMBLY_NOT_RECORDED`.

In test, a `Technician` records test runs. Each run takes a `test_type` of `PERFORMANCE_CURVE`, `HYDROSTATIC`, or `POP_TEST` and a set of `measured_points`, each point a `duty_pct` greater than zero and at most 150 together with a `measured_value` and a `reference_value`. Runs are numbered with a 1-based chronological `run_number` per repair order, and the recorder's `X-User-ID` is stored as `tested_by_id`. Recording a run against an order that is not `IN_TEST` is rejected with `ERR_INVALID_STATE`.

The verdict is computed per point and per asset standard. Each point's deviation percentage is the signed difference between `measured_value` and `reference_value`, divided by `reference_value`, expressed as a percentage and rounded half-up to two decimal places. The run's `max_deviation_pct` is the largest absolute value among the rounded per-point deviations. Its `weighted_deviation_pct` is the duty-weighted average of the rounded per-point deviations — each deviation multiplied by its point's `duty_pct`, the products summed and divided by the sum of all `duty_pct` values — itself rounded half-up to two decimal places. Under the per-point variant selected by an `API_610_PER_POINT` asset, the `verdict` is `PASS` only when `max_deviation_pct` is at most 5.00; every point stands alone, and cancelling deviations cannot rescue a bad point. Under the weighted-average variant of a `SHOP_WEIGHTED_AVG` asset, the run passes when the absolute `weighted_deviation_pct` is at most 5.00, so opposing deviations cancel and identical data can pass here while failing per-point. Both boundaries are inclusive — a deviation of exactly 5.00 passes, 5.01 fails — and every comparison uses the rounded values.

The verdict drives the order. A `FAIL` loops the order `IN_TEST` → `IN_REPAIR` and increments `repair_round` by one — the rework loop that later separates a first-time fix from a re-repair. A `PASS` on an order that requires certification advances it `IN_TEST` → `READY_FOR_CERT`; a `PASS` on any other order completes the technical work, `IN_TEST` → `COMPLETE`. Each of these system-driven transitions increments the repair order's `version` by one.

### 3.8. Safety-Relief Valve Certification and Segregation of Duties

Safety-relief valves carry a final gate: certification by a `Certifier`, deliberately distinct from whoever assembled the valve. The applicability gate is permanent and runs before any state check — attempting certification on an order whose asset is not a `SAFETY_RELIEF_VALVE` is rejected with `ERR_CERTIFICATION_NOT_APPLICABLE` regardless of the order's status. For an applicable order, certification requires `READY_FOR_CERT`; any other state is rejected with `ERR_INVALID_STATE`.

The certification records the as-tested pop `set_pressure_psig` and a `seat_leakage_class` of `CLASS_IV`, `CLASS_V`, or `CLASS_VI`. Two business-safety rules guard issuance. Segregation of duties: the certifier's `X-User-ID`, stored as `certified_by_id`, must differ from the order's `assembled_by_id`; a certifier who assembled the valve is rejected with `ERR_SOD_VIOLATION` (HTTP 422). Set-pressure fidelity: the as-tested pressure must sit within three percent of the asset's nameplate `set_pressure_psig` in either direction — the absolute difference divided by the nameplate value must not exceed 0.03, so a deviation of exactly three percent passes and anything greater is rejected with `ERR_SET_PRESSURE_OUT_OF_TOLERANCE` (HTTP 422).

Each issued certification is tagged with a sequential `tag_number` minted in creation order — `SVT-000001`, `SVT-000002`, and so on — and begins with `cert_status` `ISSUED`. Issuance completes the order: `READY_FOR_CERT` → `COMPLETE`, incrementing its `version` by one. A `ServiceManager` may later void a certification, recording a `void_reason` — null while the certification is `ISSUED` — and moving it `ISSUED` → `VOIDED`. Voiding is a compensation revert: the order falls back `COMPLETE` → `READY_FOR_CERT`, and a fresh certification is required to complete it again.

### 3.9. Closeout, Cancellation, and Pool Settlement

Closeout belongs to the `IntakeCoordinator`. Closing an order moves it `COMPLETE` → `CLOSED` and settles every open ledger at once: `closed_at` stamps the current logical clock; `invoiced_total_cents` snapshots the approved quote's `total_cents`; `repair_outcome` resolves to `FIRST_TIME_FIX` when `repair_round` is zero and `RE_REPAIR` otherwise; the order's `estimated_bay_hours` are subtracted from its window's `bay_hours_reserved`, recomputing the window's posture; and, where a pool unit stands `RESERVED` for this order, the exchange settles — the reserved unit moves `RESERVED` → `ISSUED`, and a fresh pool unit carrying this order's `customer_id` and `asset_id` is created `IN_POOL` as replenishment. The repair order's `version` increments by one.

Cancellation is broader. An `IntakeCoordinator` may cancel from any non-terminal state; a `Customer` may cancel only its own orders and only while the order is `RECEIVED`, `IN_INSPECTION`, or `QUOTE_IN_PROGRESS`. Cancellation releases everything the order holds: if the order had reached `AUTHORIZED` or any later non-terminal state, its `estimated_bay_hours` come off the window's `bay_hours_reserved` and posture is recomputed; any pool unit `RESERVED` for the order returns `RESERVED` → `IN_POOL` with `reserved_for_ro_id` cleared to null; and every non-terminal quote on the order — `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` — moves to `CANCELLED`. Terminal states lock: nothing leaves `CLOSED` or `CANCELLED`, and attempts to act on them are rejected with `ERR_INVALID_STATE`.

Pool settlement also has a manual path. A coordinator may issue a reserved unit — `RESERVED` → `ISSUED` — once its linked repair order has reached `AUTHORIZED`, `IN_REPAIR`, `IN_TEST`, `READY_FOR_CERT`, or `COMPLETE`. Issuing and withdrawing each recompute the customer's `pool_available_count`.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a customer, registering an asset, intaking a repair order, authoring an inspection report, creating a quote revision, creating a catalog part, enrolling a pool unit, recording a test run, issuing a certification, or creating a capacity window — return `201 Created`. Operations that modify an existing resource or drive a state transition, including the clock set, return `200 OK`. The table below is a summary only; request payloads, computed fields, preconditions, and cascades are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server-managed logical clock | ServiceManager |
| POST | `/customers` | Onboard a customer | ServiceManager |
| GET | `/customers` | List customers (paginated) | All roles |
| GET | `/customers/{id}` | Get one customer | All roles |
| POST | `/assets` | Register a serialized equipment unit with nameplate capture | IntakeCoordinator |
| GET | `/assets` | List assets (paginated, filterable) | All roles |
| GET | `/assets/{id}` | Get one asset | All roles |
| POST | `/repair-orders` | Intake a repair order for a customer asset | IntakeCoordinator, Customer |
| GET | `/repair-orders` | List repair orders (paginated, filterable) | All roles |
| GET | `/repair-orders/{id}` | Get one repair order | All roles |
| POST | `/repair-orders/{id}/start-teardown` | Move an order from `RECEIVED` to `IN_INSPECTION` | IntakeCoordinator |
| POST | `/repair-orders/{id}/start-repair` | Move an order from `AUTHORIZED` to `IN_REPAIR` | Technician |
| POST | `/repair-orders/{id}/log-assembly` | Record the acting technician as `assembled_by_id` | Technician |
| POST | `/repair-orders/{id}/submit-for-test` | Move an order from `IN_REPAIR` to `IN_TEST` | Technician |
| POST | `/repair-orders/{id}/close` | Move an order from `COMPLETE` to `CLOSED`, settling window, pool, and invoice | IntakeCoordinator |
| POST | `/repair-orders/{id}/cancel` | Cancel an order from any non-terminal state | IntakeCoordinator, Customer |
| POST | `/repair-orders/{id}/inspection-reports` | Author the teardown inspection report (one per order) | Inspector |
| GET | `/repair-orders/{id}/inspection-reports` | List inspection reports for an order (zero or one) | All roles |
| POST | `/inspection-reports/{id}/finalize` | Finalize a report, driving the order to quoting | Inspector |
| POST | `/quotes` | Create a quote revision (OCC-guarded create-with-supersede) | ServiceManager |
| GET | `/quotes` | List quotes (paginated, filterable) | All roles |
| GET | `/quotes/{id}` | Get one quote (lazy expiry applied on read) | All roles |
| POST | `/quotes/{id}/issue` | Issue a draft quote, stamping validity | ServiceManager |
| POST | `/quotes/{id}/approve` | Approve an issued quote, committing window hours | Customer |
| POST | `/quotes/{id}/request-revision` | Request a revision of an issued quote | Customer |
| POST | `/quotes/{id}/decline` | Decline an issued quote, cancelling the order | Customer |
| POST | `/parts` | Create a catalog part | ServiceManager |
| GET | `/parts` | List parts (paginated, filterable) | All roles |
| GET | `/parts/{id}` | Get one part | All roles |
| POST | `/parts/{id}/mark-obsolete` | Mark a part obsolete with optional supersession | ServiceManager |
| POST | `/pool-units` | Enroll a serialized unit into a customer's rotable pool | IntakeCoordinator |
| GET | `/pool-units` | List pool units (paginated, filterable) | All roles |
| GET | `/pool-units/{id}` | Get one pool unit | All roles |
| POST | `/pool-units/{id}/reserve` | Reserve a unit against an exchange-requested repair order | IntakeCoordinator |
| POST | `/pool-units/{id}/release` | Release a reservation back to the pool | IntakeCoordinator |
| POST | `/pool-units/{id}/issue` | Issue a reserved unit once its order is authorized or later | IntakeCoordinator |
| POST | `/pool-units/{id}/withdraw` | Withdraw a unit from the pool | Customer, IntakeCoordinator |
| POST | `/repair-orders/{id}/test-runs` | Record a performance test run with computed verdict | Technician |
| GET | `/repair-orders/{id}/test-runs` | List an order's test runs chronologically | All roles |
| POST | `/repair-orders/{id}/certifications` | Issue SRV certification and tag (segregation of duties enforced) | Certifier |
| GET | `/repair-orders/{id}/certifications` | List an order's certifications | All roles |
| POST | `/certifications/{id}/void` | Void an issued certification, reverting the order | ServiceManager |
| POST | `/capacity-windows` | Create a turnaround/shutdown capacity window | Planner |
| GET | `/capacity-windows` | List capacity windows (paginated) | All roles |
| GET | `/capacity-windows/{id}` | Get one capacity window | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflows that raise them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_ASSET_WINDOW_OVERLAP` | 409 |
| `ERR_WARRANTY_NOT_ELIGIBLE` | 409 |
| `ERR_SUPERSEDES_NOT_ACTIVE` | 409 |
| `ERR_PART_OBSOLETE` | 409 |
| `ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE` | 409 |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 409 |
| `ERR_WINDOW_FULL` | 409 |
| `ERR_WINDOW_CAPACITY_EXCEEDED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_POOL_UNIT_UNAVAILABLE` | 409 |
| `ERR_POOL_CUSTOMER_MISMATCH` | 409 |
| `ERR_EXCHANGE_NOT_REQUESTED` | 409 |
| `ERR_POOL_PROGRAM_REQUIRED` | 409 |
| `ERR_REPORT_ALREADY_EXISTS` | 409 |
| `ERR_ASSEMBLY_NOT_RECORDED` | 409 |
| `ERR_CERTIFICATION_NOT_APPLICABLE` | 409 |
| `ERR_SOD_VIOLATION` | 422 |
| `ERR_SET_PRESSURE_OUT_OF_TOLERANCE` | 422 |

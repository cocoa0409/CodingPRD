# Flatbed Heavy Haul API — Product Requirements Document

## 1. Introduction

Moving oversize and overweight freight across state lines is a coordination problem long before it is a driving problem. A shipper declares dimensions and weight; a dispatcher must pick a trailer that physically fits the load, prove the route survives its lowest bridge, win a permit from every state crossed, book pilot cars against a shared provider calendar, and clear a securement inspection — all before a wheel turns. Along the way the system must enforce curfews and travel windows, catch overweight conditions at the scale house, and convert the whole affair into an auditable invoice. Each of those steps has historically lived in spreadsheets, phone calls, and paper permit jackets, with predictable results: loads dispatched against a stale dimension, fines discovered after the fact, and customers billed from memory.

This document specifies the Flatbed Heavy Haul API, the platform on which a specialized carrier runs that pipeline end to end. The API governs the full lifecycle of a **Load** — from shipper intake and trailer configuration, through route survey and permit acquisition, to escort and crane booking, departure gating, transit events, and final billing — and it does so under three invariants. First, safety and regulatory adequacy are checked mechanically at every gate, never by convention. Second, the money is pinned down twice: once as a forward-looking provisional estimate that guards departure, and once as a final invoice snapshot taken after delivery, and the two may legitimately diverge as permits are refiled, escorts cancel, and fines accrue. Third, every mutation is immediately visible and fully cascaded, so no participant ever acts on a half-committed state.

The audience is the engineering team building the service. All operations are mounted under the `/heavy-haul` API prefix, with one platform-level clock capability outside that surface for test-driving time-dependent behavior.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Beyond header presence, every endpoint restricts which roles may call it; an authenticated caller whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Eight roles are recognized, spelled exactly as follows: `PlatformAdmin`, `Shipper`, `Dispatcher`, `PermitClerk`, `StateAuthority`, `SafetyManager`, `Driver`, and `BillingClerk`.

Identity is bound to a persisted entity for exactly one role. When `X-User-Role` is `Shipper`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A `Shipper` who attempts to act on a load, fine, cost estimate, or invoice belonging to a different customer is rejected with `ERR_NOT_OWN_RESOURCE` (HTTP 403). For every other role — `PlatformAdmin`, `Dispatcher`, `PermitClerk`, `StateAuthority`, `SafetyManager`, `Driver`, and `BillingClerk` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Audit Trail

Every primary resource — Customer, Load, SecurementPlan, Permit, EscortBooking, CraneAppointment, DelayEvent, Fine, and Invoice — carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation of the resource.
- `version` (integer): a system-managed counter starting from its initial value at creation and incremented by exactly 1 on every mutation of the resource.

Scale tickets are the deliberate exception. A `ScaleTicket` is an immutable, append-only weighing event: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it entirely. No endpoint modifies or deletes a scale ticket.

Any mutation of a Load — whether driven by a client call on the load itself or by a cascade originating in one of its child resources — refreshes the load's `updated_at` and increments its `version` by 1.

### 2.5. The Trailer Catalog and Legal Dimension Baselines

Trailer configuration is not free-form. A plan must select one of four cataloged trailer types — `FLATBED`, `STEP_DECK`, `RGN_LOWBOY`, or `EXTENDABLE_DOUBLE_DROP` — and every downstream rule keys off the catalog row for the chosen type. The catalog, fixed for all deployments, is:

| Trailer type | Max payload (lbs) | Deck height (in) | Cost per mile (cents) |
| ------------ | ----------------- | ---------------- | --------------------- |
| `FLATBED` | 48,000 | 60 | 350 |
| `STEP_DECK` | 46,000 | 42 | 400 |
| `RGN_LOWBOY` | 90,000 | 24 | 550 |
| `EXTENDABLE_DOUBLE_DROP` | 150,000 | 22 | 700 |

Legal baselines are likewise fixed. A load is **oversize** when its cargo is wider than 102 inches, taller than 162 inches of cargo height, or longer than 636 inches. A load is **overweight** when its gross weight exceeds 80,000 lbs. A load is a **superload** when gross weight exceeds 150,000 lbs or width exceeds 192 inches. Axle planning assumes 20,000 lbs per axle, and the minimum axle count is 2. Route surveys apply a 6-inch safety margin below the lowest bridge clearance on the route. These constants are stated here once and referenced throughout §3; the catalog itself is the `TRAILER_CATALOG` constant table that every payload limit, deck-height, and per-mile-rate lookup resolves against.

### 2.6. Optimistic Concurrency Control on the Load

Two write operations that derive their content from the load's current computed state are guarded by optimistic concurrency control against the load's `version`:

- Creating a permit application for a load requires the request to carry `expected_load_version`, holding the load `version` the client last observed.
- Booking an escort for a load likewise requires `expected_load_version`.

In both cases, if the supplied value does not equal the load's current `version`, the request is rejected with `ERR_STALE_LOAD_VERSION` (HTTP 412). The rationale is concrete: permit class and fee derive from the load's declared dimensions, weight, and route, and required escort positions derive from the load's computed dimensions, so a client whose view of the load predates the latest mutation would file the wrong permit class or book the wrong positions. Endpoints not listed above take no version field; all other mutations proceed without an OCC check.

### 2.7. Hierarchical Consistency and Cascading State Changes

The system maintains immediate consistency across the load and its dependents. When a parent load undergoes a state transition, every dependent child resource whose continued state would contradict the new reality is transitioned in the same request — permits are withdrawn on cancellation, escorts and crane appointments are completed on delivery, and the overweight cascade (§3.8) walks permits, the load, and escort bookings in one atomic step. Conversely, changes on child resources — a permit grant, an escort booking created or cancelled, a crane appointment scheduled, a securement plan approved — re-trigger evaluation of the parent load's readiness, and the load advances automatically when all criteria are satisfied. Automatic transitions are strictly upward: cancelling an escort booking never demotes a `CLEARED` load, and no child event ever moves a load backward except the two documented demotion paths (a failed survey, §3.3, and an overweight scale event, §3.8). Every automatic mutation observes the audit rules of §2.4: `updated_at` refreshes and `version` increments on each entity the cascade touches.

### 2.8. The Logical Clock, Travel Windows, and Curfew

All time-dependent decisions — permit travel windows, the departure curfew, and escort/crane overlap checks — are evaluated against a server-maintained **logical clock**, not wall-clock time. Before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z; a `PlatformAdmin` may advance it by supplying a `to_iso8601` instant through the clock-setting capability, and the clock thereafter reports the supplied instant until the next such call. The clock never falls back to wall-clock time.

Two temporal rules gate departure. Every granted permit carries a legal travel window between `travel_window_start` and `travel_window_end`; departure is only lawful while the logical clock sits inside every granted permit's window, and a granted permit whose window has already passed is first flipped to `EXPIRED` during that evaluation. Independently, departure is only lawful when the logical clock's UTC hour is at least 5 and strictly before 21 — a night curfew that keeps oversize moves off the road between 21:00 and 05:00 UTC.

### 2.9. Monetary Values and Precision

All monetary amounts are integers of cents; the API never returns fractional cents. Every division that occurs inside a calculation — escort line totals, standby charges, the fuel surcharge — is rounded **half-up to whole cents** at the point the division occurs, and the rounding points are pinned per calculation in §3. Where a calculation aggregates several lines, each line is individually rounded before the sum; summing raw unrounded lines and rounding once at the end is forbidden. Surcharges and tiered prices are always computed from exact integer arithmetic, and tier boundaries are evaluated with inclusive lower bounds precisely as stated in the relevant subsection.

### 2.10. Nested Resource Retrieval

Every child resource is addressed through its owning load — permits, securement plans, escort bookings, crane appointments, delay events, scale tickets, fines, and invoices all live under a load path, and each such record carries a `load_id` that binds it to that owning load. When an endpoint path contains multiple resource identifiers, the system validates them strictly left to right: the load first, then the child within that load's scope. A request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not exist, and a child identifier that exists but belongs to a different parent is likewise `ERR_NOT_FOUND`. Existence checking happens before any business rule is evaluated, so a request against a nonexistent parent never surfaces a business-rule error.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Credit Standing

A `PlatformAdmin` registers each shipper by providing a `company_name`, which must be unique across customers, and a `credit_limit_cents`, which must be greater than zero. The customer record comes into existence with `status` `ACTIVE` and an `outstanding_balance_cents` of zero. The outstanding balance is a computed figure: it is the sum of `total_cents` over that customer's invoices currently in `ISSUED` status, so issuing an invoice debits the balance while paying or voiding it credits the balance back. Any role may read a customer record, and a `Shipper` may read their own.

Credit standing is enforced at two points. When an invoice is issued and the resulting `outstanding_balance_cents` is strictly greater than the customer's `credit_limit_cents`, the customer flips automatically to `SUSPENDED`; equality leaves the customer `ACTIVE`. A `SUSPENDED` customer cannot create loads — the attempt is rejected with `ERR_CUSTOMER_SUSPENDED` (HTTP 409). Reinstatement is performed by a `BillingClerk` and moves `SUSPENDED` back to `ACTIVE`, but only when the customer is in fact `SUSPENDED` (otherwise `ERR_INVALID_STATE`, HTTP 409) and only when the outstanding balance is at or below the credit limit — if it still exceeds the limit, the reinstatement is rejected with `ERR_REINSTATE_NOT_ALLOWED` (HTTP 409).

The second enforcement point is departure (§3.7), where the provisional estimate must fit within the customer's remaining credit headroom.

### 3.2. Load Intake and Trailer Planning

A `Shipper` opens a shipment by creating a load with a free-text `cargo_description`, the declared `gross_weight_lbs`, cargo `width_in`, `height_in`, and `length_in` in whole inches, free-text `origin` and `destination`, an optional `cargo_requires_tarp` flag that defaults to false, and an optional `declared_value_cents` that defaults to zero and may not be negative. Each of the weight and dimension fields must be greater than zero; violations of required-field presence, enum membership, integer floors, or datetime ordering on any endpoint are rejected with `ERR_INVALID_REQUEST` (HTTP 400). The new load's `customer_id` is taken from the calling shipper's `X-User-ID`, its `status` starts at `DRAFT`, and `survey_result` starts null. Because customer suspension is checked before any other load-creation rule, a suspended shipper hears `ERR_CUSTOMER_SUSPENDED` regardless of what else is wrong with the payload.

Planning converts a `DRAFT` load into a configured movement. A `Dispatcher` supplies `trailer_type` (one of the four catalog values), `trailer_axle_count` (at least 2), `driver_name`, and the `driver_oversize_endorsed` flag. Planning is allowed while the load is `DRAFT`, `PLANNED`, or `SURVEYED` — the latter two being re-plans — and any other state is rejected with `ERR_LOAD_INVALID_STATE` (HTTP 409). Three adequacy checks run at plan time, in a fixed order so the first failure is the one reported:

1. **Capacity first.** The chosen trailer's catalog payload limit must be greater than or equal to `gross_weight_lbs` — a payload exactly equal to the limit passes — or the plan is rejected with `ERR_TRAILER_CAPACITY_EXCEEDED` (HTTP 422).
2. **Axles second.** `trailer_axle_count` must be at least the required axle count, which is the greater of 2 and the declared gross weight divided by 20,000 lbs per axle rounded up to a whole axle; a shortfall is rejected with `ERR_AXLE_COUNT_INSUFFICIENT` (HTTP 422).
3. **Endorsement last.** When the load is oversize or overweight, `driver_oversize_endorsed` must be true; planning such a load under an unendorsed driver is rejected with `ERR_DRIVER_NOT_ENDORSED` (HTTP 422).

On acceptance, the system stores the four plan inputs on the load and refreshes the computed dimensions. The overall height `overall_height_in` becomes `height_in` plus the chosen trailer's catalog deck height (it is null until the first successful plan). The flags `is_oversize`, `is_overweight`, and `is_superload` are computed from the §2.5 baselines. The required axle count `required_axles` is stored. Required escort positions are derived as `required_escort_positions`: width of at least 168 inches demands both a `FRONT` and a `REAR` escort; width of at least 144 inches but under 168 demands a `REAR` escort only; narrower loads need none — and independently, an `overall_height_in` of at least 192 inches appends a `POLE_FRONT` pole car. The boundary comparisons are inclusive: a width of exactly 144 inches requires the rear escort, 143 inches requires none, and exactly 192 inches of overall height adds the pole car. Re-planning a `SURVEYED` load is permitted because deck height and capacity may change, but it invalidates the survey: `survey_result` is reset to null. Every successful plan or re-plan increments the load's `version` by 1.

### 3.3. Route Survey and Bridge Analysis

With a trailer configured, a `Dispatcher` records the route survey: surveyed `route_miles` (greater than zero), the ordered `states_crossed` list of two-letter codes drawn from {CA, NV, AZ, TX, OR} (which must be non-empty), the route's lowest overhead clearance `min_bridge_clearance_in`, and its lowest bridge weight rating `max_bridge_weight_lbs` (both greater than zero). Surveying requires the load to be `PLANNED` or `SURVEYED`; otherwise the request is rejected with `ERR_LOAD_INVALID_STATE`.

The survey verdict is computed, not asserted. The survey passes when `overall_height_in` plus the 6-inch safety margin is less than or equal to `min_bridge_clearance_in`, **and** `gross_weight_lbs` is less than or equal to `max_bridge_weight_lbs`; otherwise it fails. A passing survey moves the load from `PLANNED` to `SURVEYED`, stores the four survey inputs, sets `survey_result` to `PASSED`, and increments the load's `version`. Re-surveying an already-`SURVEYED` load with a passing result keeps it `SURVEYED` and overwrites the survey fields; permits already filed keep their computed fees even if the route changed. A failing survey leaves `survey_result` as `FAILED` and demotes the load for re-planning: a `SURVEYED` load drops back to `PLANNED`, while a `PLANNED` load that fails its survey simply stays `PLANNED` with the failed verdict stored. Each survey attempt increments the load's `version` by 1.

### 3.4. Securement and Tarping

A `Dispatcher` files the securement plan for a load that is `PLANNED` or `SURVEYED` (any other state is `ERR_LOAD_INVALID_STATE`). The filing carries a `method` of `CHAINS`, `STRAPS`, or `CHAINS_AND_TARPS`, a `tiedown_count` of at least 2, and a `wll_per_tiedown_lbs` working load limit per tiedown greater than zero. The plan's `aggregate_wll_lbs` is computed as `tiedown_count` multiplied by `wll_per_tiedown_lbs`, and the plan is created directly in `SUBMITTED` status.

Review belongs to the `SafetyManager`. Approval evaluates two conditions: the aggregate working load limit must be at least half the load's gross weight, where an odd pound rounds up — a shortfall is rejected with `ERR_SECUREMENT_WLL_INSUFFICIENT` (HTTP 422) — and when the load's `cargo_requires_tarp` flag is set, the method must be `CHAINS_AND_TARPS`, or approval is rejected with `ERR_TARPING_REQUIRED` (HTTP 422). Approving a plan that is no longer `SUBMITTED` is `ERR_INVALID_STATE`. A successful approval moves the plan to `APPROVED` and re-evaluates the load's readiness gate (§3.7), which may advance a `SURVEYED` load to `CLEARED`. Rejection moves the plan to `REJECTED`; both outcomes are terminal for that plan, and a rejected plan is replaced by filing a new one, not by reopening the old.

### 3.5. Permit Acquisition, Filing, and the Refile Loop

Every state the route crosses requires its own permit, and the permit class must match the load's computed flags: a superload requires a `SUPERLOAD` permit; otherwise an oversize load requires an `OVERSIZE` permit if and only if `is_oversize` holds, and an overweight load requires an `OVERWEIGHT` permit if and only if `is_overweight` holds. A `STANDARD` load — neither oversize nor overweight — needs no permits at all. A `PermitClerk` creates a permit application against a load that is `SURVEYED`, `CLEARED`, or `ON_HOLD`, supplying `state_code` (one of CA, NV, AZ, TX, OR), `permit_type` (`OVERSIZE`, `OVERWEIGHT`, or `SUPERLOAD`), and the OCC field `expected_load_version` per §2.6. Creating a permit whose type does not match the load's flags is rejected with `ERR_PERMIT_TYPE_NOT_REQUIRED` (HTTP 409), and creating a second permit for the same `(state_code, permit_type)` pair while one already exists in `DRAFT`, `FILED`, or `GRANTED` status is rejected with `ERR_DUPLICATE_PERMIT` (HTTP 409). A new permit starts in `DRAFT`, and its creation increments the owning load's `version` by 1.

Filing is the paid act. A `PermitClerk` files a permit that is `DRAFT`, `DENIED`, or `REVOKED` — any other status is `ERR_INVALID_STATE` — and at every such transition the fee is computed fresh. The fee's **weight basis** is declared-versus-measured: when no scale ticket exists for the load, `weight_basis_lbs` is the shipper-declared `gross_weight_lbs`; once at least one scale ticket exists (typical for a refile after revocation), `weight_basis_lbs` is the `measured_gross_lbs` of the most recently created ticket, so identical dimensions produce a different fee whenever measured and declared weights differ. The fee itself, `fee_cents`, is the sum of three components:

1. A **state base fee** keyed on the permit's state and class. For `OVERSIZE` the bases are 9,000 cents in CA, 7,000 in NV, 8,000 in AZ, 10,000 in TX, and 8,500 in OR. For `OVERWEIGHT` they are 15,000 / 12,000 / 13,000 / 16,000 / 14,000 cents across CA, NV, AZ, TX, OR respectively. For `SUPERLOAD` they are 50,000 / 40,000 / 45,000 / 55,000 / 48,000 cents in the same order.
2. A **marginal weight surcharge**, which applies to `OVERWEIGHT` and `SUPERLOAD` permits only and is zero for `OVERSIZE`. The surcharge prices the pounds by which the weight basis exceeds 80,000 lbs (zero if it does not): the first 20,000 excess pounds at 1 cent per pound, the next 30,000 pounds at 2 cents per pound, and every pound beyond 50,000 excess at 4 cents per pound, each tier priced only on the pounds inside it.
3. A **flat width surcharge**, which applies to `OVERSIZE` and `SUPERLOAD` permits only and is zero for `OVERWEIGHT`. Only the highest applicable bracket counts: width over 192 inches adds 10,000 cents; else over 168 inches adds 5,000; else over 144 inches adds 2,500; otherwise nothing.

All fee terms are integer cents and no rounding is needed. Filing records `weight_basis_lbs` alongside the computed `fee_cents`.

Disposition belongs to the `StateAuthority`. Granting a `FILED` permit stores the legal travel window — `travel_window_start` and a `travel_window_end` that must be strictly after the start — moves the permit to `GRANTED`, and re-evaluates the load's readiness gate. Denying a `FILED` permit stores the free-text `denial_reason` and moves it to `DENIED`. `DENIED` is not terminal: the clerk re-files after amendment, which recomputes the fee on the current weight basis, and that negotiation cycle may repeat. Permits also move without any client action in three situations: a granted permit whose travel window has passed flips lazily to `EXPIRED` the next time the readiness gate or the departure check evaluates it; the scale-violation cascade (§3.8) revokes granted weight permits; and cancelling the load withdraws every permit not yet in a terminal state — any of `DRAFT`, `FILED`, `GRANTED`, `DENIED`, or `REVOKED` becomes `WITHDRAWN`. `EXPIRED` and `WITHDRAWN` are terminal.

### 3.6. Escort and Crane Booking

Pilot cars are booked by the `Dispatcher` against a load that is `PLANNED`, `SURVEYED`, `CLEARED`, or `ON_HOLD`; other states are rejected with `ERR_LOAD_INVALID_STATE`. The booking names a `provider_name`, a `position` of `FRONT`, `REAR`, or `POLE_FRONT`, a `scheduled_start` and a later `scheduled_end`, an hourly `rate_per_hour_cents` greater than zero, and the OCC field `expected_load_version` per §2.6. The system computes `scheduled_minutes` as the whole-minute length of the window and creates the booking directly in `CONFIRMED` status. Each booking increments the owning load's `version` by 1 and re-evaluates the readiness gate.

A provider cannot be in two places at once. A new booking is rejected with `ERR_ESCORT_WINDOW_OVERLAP` (HTTP 409) when its half-open window — inclusive of `scheduled_start`, exclusive of `scheduled_end` — intersects any other `CONFIRMED` booking for the same `provider_name`. Adjacency is allowed: a booking that begins exactly when another ends does not overlap it. The check is per provider, so overlapping windows for different providers are fine. The `Dispatcher` may also cancel a `CONFIRMED` booking; cancellation frees the provider's window and re-evaluates the readiness gate, but per §2.7 it never demotes an already-`CLEARED` load. Cancellation of a booking not in `CONFIRMED` status is `ERR_INVALID_STATE`. Bookings reach `COMPLETED` automatically when their load is delivered, and `CANCELLED` automatically through the load-cancel or scale-violation cascades.

Crane lifts follow the same pattern with a buffer. The `Dispatcher` schedules an appointment with a `site` of `ORIGIN` or `DESTINATION`, a `crane_id`, and a `window_start` / `window_end` pair with the end strictly after the start; the load must be `PLANNED`, `SURVEYED`, `CLEARED`, or `ON_HOLD`. The appointment is created in `SCHEDULED` status and re-evaluates the readiness gate. Cranes demand turnaround time: each appointment's window is conceptually expanded by 45 minutes on both sides, and a new appointment is rejected with `ERR_CRANE_WINDOW_OVERLAP` (HTTP 409) when its buffered window intersects another `SCHEDULED` appointment's buffered window for the same `crane_id`. Intersection is strict, exactly as for escort windows: buffered windows that merely touch — one buffered window ending at the precise instant the other begins — do not intersect. The net effect is that two appointments for the same `crane_id` must be separated by at least 90 minutes between one appointment's `window_end` and the other's `window_start`; exactly 90 minutes is accepted, and any smaller separation — including overlapping raw windows — is rejected. Crane appointments are never cancelled by direct client action — they complete automatically on delivery and cancel automatically through the load-cancel cascade.

### 3.7. The Clearance Gate, Departure, and Transit Events

The readiness gate converts a `SURVEYED` load into a `CLEARED` one and is re-evaluated automatically after every permit grant, escort booking creation, crane appointment creation, and securement approval. All five conditions must hold simultaneously:

1. `survey_result` is `PASSED`.
2. Permits are complete: for every state in `states_crossed`, a superload holds a `GRANTED` `SUPERLOAD` permit for that state; otherwise the load holds a `GRANTED` `OVERSIZE` permit for that state when oversize and a `GRANTED` `OVERWEIGHT` permit when overweight, and standard loads need nothing.
3. Every position in `required_escort_positions` is covered by at least one `CONFIRMED` escort booking in that position.
4. At least one `SCHEDULED` crane appointment exists with `site` `ORIGIN` and at least one with `site` `DESTINATION`.
5. An `APPROVED` securement plan exists for the load.

When all five pass, the load advances to `CLEARED` and its `version` increments.

Departure is the `Driver`'s act and the most heavily gated transition in the system. The checks evaluate in a pinned order — load state, escort coverage, travel windows, curfew, then credit — so the earliest failing check is the error returned. The load must be `CLEARED` (`ERR_LOAD_INVALID_STATE`). Every required escort position must still be covered by a `CONFIRMED` booking, or departure is rejected with `ERR_ESCORT_REQUIREMENT_UNMET` (HTTP 409). The logical clock must lie within every `GRANTED` permit's travel window — permits whose window has passed flip to `EXPIRED` during this evaluation, and any window violation is `ERR_OUTSIDE_TRAVEL_WINDOW` (HTTP 409). The clock's UTC hour must be at least 5 and strictly before 21, or departure is rejected with `ERR_CURFEW_VIOLATION` (HTTP 409). Finally, the provisional cost estimate's `total_cents` must not exceed the customer's remaining credit — `credit_limit_cents` minus `outstanding_balance_cents` — with equality passing and any excess rejected as `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). A clean departure moves the load to `IN_TRANSIT` and increments its `version`.

The provisional estimate that backs the credit check is also directly readable as the load's cost estimate by `Dispatcher`, `BillingClerk`, `Shipper`, and `PlatformAdmin` callers once the load is at least `SURVEYED` (before that, `route_miles` and trailer do not yet exist together, and the request is `ERR_LOAD_INVALID_STATE`). It mirrors the final invoice structure line for line but prices the future: linehaul is `route_miles` multiplied by the trailer's catalog cost per mile; permits are summed over `FILED` and `GRANTED` permits at their current `fee_cents`; escorts are summed over `CONFIRMED` bookings with each booking's charge rounded half-up individually before summing; `standby_cents` and `fines_cents` are both zero; and the subtotal, fuel surcharge, and total follow the same pinned rules as the invoice (§3.9).

Once rolling, the `Driver` records operational events. A delay event carries a `kind` of `CUSTOMER_DELAY`, `CARRIER_DELAY`, or `WEATHER`, plus `started_at` and a later `ended_at`; the load must be `CLEARED`, `ON_HOLD`, or `IN_TRANSIT`. Only customer-caused delay is billable. The event's `duration_minutes` is the whole-minute length of the delay. Its `billable_minutes` is the duration minus a 120-minute free allowance, floored at zero, for `CUSTOMER_DELAY` events, and zero for carrier delays and weather. The `standby_amount_cents` tiers the billable minutes per event: the first 360 billable minutes at 17,500 cents per hour, any remainder at a 1.5-times premium of 26,250 cents per hour, with the sum of the two tier charges divided by 60 and rounded half-up to whole cents. Two anchors pin the tiers: exactly 120 minutes of customer delay bills nothing, and exactly 480 minutes bills 360 minutes entirely at the standard rate.

Arrival is the counterpart of departure: the `Driver` marks an `IN_TRANSIT` load delivered, moving it to the terminal `DELIVERED` state, completing every `CONFIRMED` escort booking and every `SCHEDULED` crane appointment on the load, and incrementing the load's `version`.

Cancellation is the `Shipper`'s escape hatch, shared with the `Dispatcher`. A load in `DRAFT`, `PLANNED`, `SURVEYED`, `CLEARED`, or `ON_HOLD` may be cancelled; one in `IN_TRANSIT`, `DELIVERED`, or `CANCELLED` may not, and the attempt is rejected with `ERR_LOAD_NOT_CANCELLABLE` (HTTP 409). A `Shipper` may cancel only their own loads — ownership is checked per §2.1 with `ERR_NOT_OWN_RESOURCE`. Cancellation cascades: every non-terminal permit becomes `WITHDRAWN`, every `CONFIRMED` escort booking and every `SCHEDULED` crane appointment becomes `CANCELLED`, the load becomes `CANCELLED`, and the load's `version` increments.

### 3.8. Scale Tickets and the Overweight Cascade

Certified scale weighings are recorded by the `Driver` while the load is `CLEARED`, `IN_TRANSIT`, or `ON_HOLD`; a weighing against any other load state is `ERR_LOAD_INVALID_STATE`. The record carries `measured_gross_lbs` (greater than zero) and the `weighed_at` instant, and it is immutable once written — scale tickets are the system's append-only audit of what the truck actually weighed. Two computed fields land at recording time: `excess_lbs` is the amount by which the measured weight exceeds the load's declared `gross_weight_lbs`, floored at zero, and `is_violation` is true exactly when the measured weight, multiplied by 100, is strictly greater than the declared weight multiplied by 103 — a 3% tolerance evaluated in exact integer arithmetic with no floating-point rounding.

A violating ticket fires the full cascade in one request. First, the system creates a `Fine` of kind `OVERWEIGHT` with `liable_party` `CUSTOMER`, priced marginally on `excess_lbs`: the first 2,000 excess pounds at 25 cents per pound, the next 3,000 at 50 cents, and every pound beyond 5,000 at 100 cents, each tier priced only on the pounds inside it. Second, every `GRANTED` `OVERWEIGHT` or `SUPERLOAD` permit of the load flips to `REVOKED`; `OVERSIZE` permits are unaffected. Third, if the load is `CLEARED` or `IN_TRANSIT` it moves to `ON_HOLD` with `hold_reason` set to `SCALE_OVERWEIGHT`, and that hold cancels every `CONFIRMED` escort booking, freeing the providers' windows. A load already `ON_HOLD` simply absorbs the new fine and revocations. A non-violating ticket does none of this — it is just a record.

Recovery from the hold is deliberate. The revoked permits must be re-filed — now on the measured weight basis per §3.5 — and re-granted with fresh travel windows. Only then may a `SafetyManager` release the hold, and only when every required `(state_code, permit_type)` pair again has a `GRANTED` permit; a shortfall is rejected with `ERR_PERMIT_REQUIREMENT_UNMET` (HTTP 409), and a release attempted on a load not `ON_HOLD` is `ERR_LOAD_INVALID_STATE`. Release clears `hold_reason` to null, returns the load to `SURVEYED`, immediately re-evaluates the readiness gate — which may advance it straight back to `CLEARED` if escorts, cranes, and securement again satisfy the gate — and increments the load's `version`.

### 3.9. Fines, Disputes, and Final Billing

Beyond the system-created overweight fines, the `Driver` and `SafetyManager` may manually report fines of kind `DAMAGE` or `PERMIT_VIOLATION` against a load that is `CLEARED`, `ON_HOLD`, `IN_TRANSIT`, or `DELIVERED`, supplying `kind`, an `amount_cents` greater than zero, and a free-text `description`. Manually reporting an `OVERWEIGHT` fine is rejected with `ERR_FINE_KIND_NOT_MANUAL` (HTTP 409) — that class exists only through the scale cascade. Manual fines are born `PENDING` with `liable_party` defaulted to `CARRIER`, on the principle that breakage and permit violations are the carrier's problem until adjudicated; the system-created `OVERWEIGHT` fine is the mirror image, born customer-liable.

Liability can be contested. A `Shipper` may dispute a fine that is still `PENDING` and customer-liable — disputing a non-pending fine or a carrier-liable one (those are absorbed, not disputed) is rejected with `ERR_FINE_NOT_DISPUTABLE` (HTTP 409) — and only for loads they own, with `ERR_NOT_OWN_RESOURCE` guarding cross-customer disputes. Dispute moves the fine to `DISPUTED`. Resolution belongs to the `SafetyManager`, who supplies a `resolution` of `CUSTOMER_LIABLE` or `CARRIER_LIABLE` and an optional `adjusted_amount_cents`. Resolving a fine that is neither `PENDING` nor `DISPUTED` is `ERR_INVALID_STATE`. A customer-liable resolution sets `liable_party` to `CUSTOMER`, replaces `amount_cents` with the adjusted amount when one is supplied, and moves the fine to `RESOLVED_CUSTOMER_LIABLE`; a carrier-liable resolution sets `liable_party` to `CARRIER`, moves the fine to `RESOLVED_CARRIER_LIABLE` (terminal), and excludes it from all invoice computations.

Final billing begins only after delivery. A `BillingClerk` creates the invoice for a `DELIVERED` load, and a load may carry at most one `ISSUED` invoice at a time — a second attempt is rejected with `ERR_INVOICE_EXISTS` (HTTP 409). The invoice is a snapshot: every line is computed once at creation and stored, with the evaluation order pinned because rounding order matters:

1. `linehaul_cents` — `route_miles` multiplied by the trailer's catalog cost per mile in cents.
2. `permits_cents` — the sum of `fee_cents` over the load's `GRANTED` permits only; `DRAFT`, `FILED`, `DENIED`, `REVOKED`, `EXPIRED`, and `WITHDRAWN` permits contribute nothing.
3. `escorts_cents` — for each `COMPLETED` escort booking, `scheduled_minutes` multiplied by `rate_per_hour_cents` and divided by 60, rounded half-up to whole cents **per booking**, with the rounded line values then summed; summing first and rounding once is forbidden.
4. `standby_cents` — the sum of `standby_amount_cents` over all of the load's delay events.
5. `fines_cents` — the sum of `amount_cents` over fines with `liable_party` `CUSTOMER` whose status is `PENDING` or `RESOLVED_CUSTOMER_LIABLE`; `DISPUTED` and `RESOLVED_CARRIER_LIABLE` fines are excluded.
6. `subtotal_cents` — the sum of the five lines above.
7. `fuel_surcharge_cents` — keyed on the **pre-surcharge** subtotal: a subtotal of at least 5,000,000 cents attracts a 12% surcharge, anything below attracts 8%, and the chosen percentage is multiplied by the subtotal and rounded half-up to whole cents. The tier never keys on the total, so a subtotal just under the threshold still bills the low rate even though the surcharge itself would push the total over it.
8. `total_cents` — the subtotal plus the fuel surcharge.

Creation moves the invoice directly to `ISSUED` and sweeps every customer-liable fine still `PENDING` or `RESOLVED_CUSTOMER_LIABLE` into `APPLIED`. The customer is debited immediately: `outstanding_balance_cents` increases by `total_cents`, and if the result strictly exceeds `credit_limit_cents` the customer flips to `SUSPENDED` per §3.1. The final invoice can therefore diverge from the provisional estimate the departure gate checked — permits are counted only when granted (denied and refiled fees settle, and measured-basis refiles change the numbers), escorts are counted only when completed (cancellations drop out), and standby plus customer-liable fines are included only in the final.

Settlement closes the loop. Paying an invoice requires the caller's `amount_cents` to equal the invoice's `total_cents` exactly — a mismatch is `ERR_INVALID_REQUEST` — and requires the invoice to be `ISSUED`, otherwise `ERR_INVOICE_NOT_ISSUED` (HTTP 409). Payment moves the invoice to the terminal `PAID` state and credits `outstanding_balance_cents` down by `total_cents`. Voiding, also restricted to `ISSUED` invoices, moves it to the terminal `VOID` state, credits the same amount off the outstanding balance, and un-sweeps the invoice's fines from `APPLIED` back to `PENDING` so that a replacement invoice can legitimately include them.

## 4. Endpoint Definitions

Operations that create a new resource — a customer, a load, a child record under a load, or an invoice — return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. All validation failures return the 4xx code of the specific rule violated, per the catalogue in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/heavy-haul/customers` | Register a shipper customer | PlatformAdmin |
| GET | `/heavy-haul/customers/{id}` | Get a customer | PlatformAdmin, BillingClerk, Dispatcher, SafetyManager, Shipper |
| POST | `/heavy-haul/customers/{id}/reinstate` | Reinstate a SUSPENDED customer within credit limit | BillingClerk |
| POST | `/heavy-haul/loads` | Create a load in DRAFT for the calling Shipper's customer | Shipper |
| GET | `/heavy-haul/loads` | List loads; Shipper callers auto-scoped to their own customer | Shipper, Dispatcher, PermitClerk, StateAuthority, SafetyManager, Driver, BillingClerk, PlatformAdmin |
| GET | `/heavy-haul/loads/{id}` | Get a load | Shipper, Dispatcher, PermitClerk, StateAuthority, SafetyManager, Driver, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/loads/{id}/plan` | Select trailer configuration and driver; compute flags, axles, escort positions | Dispatcher |
| POST | `/heavy-haul/loads/{id}/survey` | Record route survey and bridge analysis; auto-evaluate PASSED/FAILED | Dispatcher |
| POST | `/heavy-haul/loads/{id}/cancel` | Cancel a pre-transit load; cascade to permits, escorts, cranes | Shipper, Dispatcher |
| POST | `/heavy-haul/loads/{id}/depart` | Depart a CLEARED load; enforce escorts, travel windows, curfew, credit | Driver |
| POST | `/heavy-haul/loads/{id}/arrive` | Mark an IN_TRANSIT load delivered; complete escorts and cranes | Driver |
| POST | `/heavy-haul/loads/{id}/release-hold` | Release an ON_HOLD load after revoked permits are refiled and granted | SafetyManager |
| GET | `/heavy-haul/loads/{id}/cost-estimate` | Provisional forward-looking cost estimate | Dispatcher, BillingClerk, Shipper, PlatformAdmin |
| POST | `/heavy-haul/loads/{id}/securement-plans` | File a securement and tarping plan (created SUBMITTED) | Dispatcher |
| GET | `/heavy-haul/loads/{id}/securement-plans` | List securement plans of a load | Shipper, Dispatcher, SafetyManager, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/securement-plans/{id}/approve` | Approve a plan after WLL and tarping validation | SafetyManager |
| POST | `/heavy-haul/securement-plans/{id}/reject` | Reject a plan (terminal; replacement must be refiled) | SafetyManager |
| POST | `/heavy-haul/loads/{id}/permits` | Create a permit application in DRAFT (OCC-guarded on the load) | PermitClerk |
| GET | `/heavy-haul/loads/{id}/permits` | List permits of a load | Shipper, Dispatcher, PermitClerk, StateAuthority, SafetyManager, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/permits/{id}/file` | File or re-file a permit; compute fee on the current weight basis | PermitClerk |
| POST | `/heavy-haul/permits/{id}/grant` | Grant a filed permit with its legal travel window | StateAuthority |
| POST | `/heavy-haul/permits/{id}/deny` | Deny a filed permit | StateAuthority |
| POST | `/heavy-haul/loads/{id}/escort-bookings` | Book a pilot car (created CONFIRMED; OCC-guarded; overlap rejected) | Dispatcher |
| GET | `/heavy-haul/loads/{id}/escort-bookings` | List escort bookings of a load | Shipper, Dispatcher, SafetyManager, Driver, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/escort-bookings/{id}/cancel` | Cancel a CONFIRMED booking, freeing the provider window | Dispatcher |
| POST | `/heavy-haul/loads/{id}/crane-appointments` | Schedule a crane lift window; buffered overlap rejected | Dispatcher |
| GET | `/heavy-haul/loads/{id}/crane-appointments` | List crane appointments of a load | Shipper, Dispatcher, SafetyManager, Driver, PlatformAdmin |
| POST | `/heavy-haul/loads/{id}/delay-events` | Record a delay event; compute billable minutes and tiered standby charge | Driver |
| GET | `/heavy-haul/loads/{id}/delay-events` | List delay events of a load | Shipper, Dispatcher, Driver, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/loads/{id}/scale-tickets` | Record a certified weighing; violations cascade to fines, revocations, hold | Driver |
| GET | `/heavy-haul/loads/{id}/scale-tickets` | List scale tickets of a load (immutable, append-only) | Shipper, Dispatcher, SafetyManager, Driver, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/loads/{id}/fines` | Report a damage or permit-violation fine (OVERWEIGHT is system-only) | Driver, SafetyManager |
| GET | `/heavy-haul/loads/{id}/fines` | List fines of a load | Shipper, Dispatcher, SafetyManager, Driver, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/fines/{id}/dispute` | Shipper disputes a customer-liable PENDING fine | Shipper |
| POST | `/heavy-haul/fines/{id}/resolve` | Resolve a PENDING or DISPUTED fine; fix liability, optionally adjust amount | SafetyManager |
| POST | `/heavy-haul/loads/{id}/invoices` | Create the final invoice for a DELIVERED load (issued snapshot) | BillingClerk |
| GET | `/heavy-haul/loads/{id}/invoices` | List invoices of a load | Shipper, Dispatcher, BillingClerk, PlatformAdmin |
| POST | `/heavy-haul/invoices/{id}/pay` | Pay an ISSUED invoice in full | BillingClerk |
| POST | `/heavy-haul/invoices/{id}/void` | Void an ISSUED invoice; compensate balance and un-sweep fines | BillingClerk |

Query parameters supported on the list endpoints are: `customer_id` and `status` on the load list; `status` on the permit, escort-booking, and fine lists; `site` on the crane-appointment list; `kind` on the delay-event and fine lists; and `limit` / `offset` on every list endpoint.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_OWN_RESOURCE` | 403 Forbidden |
| `ERR_STALE_LOAD_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_LOAD_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LOAD_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PERMIT_REQUIREMENT_UNMET` | 409 Conflict |
| `ERR_FINE_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUED` | 409 Conflict |
| `ERR_REINSTATE_NOT_ALLOWED` | 409 Conflict |
| `ERR_TRAILER_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_AXLE_COUNT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_DRIVER_NOT_ENDORSED` | 422 Unprocessable Entity |
| `ERR_SECUREMENT_WLL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_TARPING_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ESCORT_REQUIREMENT_UNMET` | 409 Conflict |
| `ERR_OUTSIDE_TRAVEL_WINDOW` | 409 Conflict |
| `ERR_CURFEW_VIOLATION` | 409 Conflict |
| `ERR_ESCORT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CRANE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PERMIT_TYPE_NOT_REQUIRED` | 409 Conflict |
| `ERR_DUPLICATE_PERMIT` | 409 Conflict |
| `ERR_FINE_KIND_NOT_MANUAL` | 409 Conflict |
| `ERR_INVOICE_EXISTS` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |

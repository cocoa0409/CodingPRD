# Integrated Facilities Management API — Product Requirements Document

## 1. Introduction

A corporate real-estate services organisation manages hundreds of buildings on behalf of its clients, and today the work is spread across disconnected tools: a spreadsheet for asset registers, an e-mail thread for vendor call-outs, a separate ledger for tenant recharges, and a quarterly slide deck for sustainability figures. The consequence is not merely inefficiency — it is incoherence. A chiller can be dead for a week while the janitorial crew is still being scheduled into the plant room; a work order can be billed to a tenant twice; a capital project can be over-committed because two managers drew on the same budget without seeing each other's orders.

This document specifies a single Integrated Facilities Management service that treats a building as one coherent operational object. Every building carries a derived **operating posture** that reflects the real condition of its critical plant and its open emergency workload, and that posture gates what may be done inside the building. Beneath the posture sit the working parts of the business: an asset register with preventive-maintenance plans, a corrective work-order pipeline dispatched to trade vendors under contractual SLAs, soft-service (janitorial and security) shift coordination, utility metering, lease and occupancy allocation, monthly tenant chargeback, and capital-project funding. All of them share one arithmetic, one clock, and one set of conserved quantities.

The API is mounted under `/fm`. It is deliberately deterministic: a logical clock replaces wall-clock time, every monetary line is rounded exactly once at a stated point, and every derived counter is recomputed from its underlying rows rather than incrementally patched. Implementers should read the business narrative in §3 as the specification of record — §4 and §5 are indexes into it, not substitutes for it.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present and well-formed but the caller's role is not among the roles authorised for the endpoint being addressed (see the table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles are `PlatformAdmin`, `FacilityManager`, `VendorTech`, `FinanceController`, `TenantRep`, and `SustainabilityAnalyst`.

A `PlatformAdmin` is the operator superset: it may perform every business operation, and it alone may drive the logical clock. A `FacilityManager` runs the physical building — assets, spaces, preventive-maintenance plans, work orders, vendor dispatch, quality assurance, soft-service scheduling, and the operational epoch run. A `FinanceController` owns leases, chargeback statements, and capital-project decisions. A `SustainabilityAnalyst` feeds utility meter readings and reads the energy and KPI surface. A `VendorTech` acts on behalf of a single contracted vendor. A `TenantRep` acts on behalf of a single lease.

Four of the roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `FacilityManager`, `FinanceController`, or `SustainabilityAnalyst`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it — for example, a capital project stores the proposer's identifier in `proposed_by_user_id` and the decider's in `approved_by_user_id` — but it never compares it against any entity's `id`.

Two of the roles are **entity-backed**. When `X-User-Role` is `VendorTech`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare that resource's vendor foreign key to `X-User-ID`. Concretely, a `VendorTech` may accept, decline, or complete only a dispatch whose `vendor_id` equals its `X-User-ID`, and may complete only a soft-service shift whose `vendor_id` equals its `X-User-ID`. When `X-User-Role` is `TenantRep`, `X-User-ID` is the `id` of the acting `Lease`; a `TenantRep` may dispute only a chargeback statement whose `lease_id` equals its `X-User-ID`. In every one of these five cases, an ownership mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) — the role is right, the resource is not theirs.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1 and a maximum of 100; a value outside that inclusive range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). `offset` defaults to 0 and its minimum is 0; a negative value is likewise rejected with `ERR_INVALID_REQUEST`.

List responses set `response_type` to `"array"` and place four pagination fields in `meta`: `limit` and `offset` echo the effective values used, `total_count` reports the number of rows matching the filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current page. Unless a subsection below states otherwise, list endpoints return their rows sorted by `created_at` ascending.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every persisted resource carries a server-minted `id`, a UUID string with no type prefix, allocated by the server and never supplied by a client. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC string with three fractional digits. Almost every resource additionally carries an `updated_at` timestamp in the same format and an integer `version` that starts at 1 on creation and increments by 1 on every mutation of that resource; `updated_at` is refreshed on every mutation as well. The one exception is `UtilityReading`, which is an append-only measurement record: a reading exposes only `id` and `created_at`, and carries neither `updated_at` nor `version`, because it is never modified after it is written.

Time in this system is a **logical clock**, never the host's wall clock. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and it stays there until a `PlatformAdmin` moves it by supplying a `to_iso8601` instant; the response confirms the new value as `current_utc`. Every timestamp the server stamps, every SLA deadline evaluation, every preventive-maintenance compliance computation, and every allocation-coverage test reads this clock and nothing else.

### 2.5. Path Resolution and Referential Integrity

Nested paths are resolved strictly left to right. When a client addresses a space through its building, the building is looked up first; if it does not exist the request fails with `ERR_BUILDING_NOT_FOUND` (HTTP 404) and the space is never consulted. The same discipline applies to every path parameter in the API, and each entity has its own not-found code: `ERR_BUILDING_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_PM_PLAN_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, and `ERR_PROJECT_NOT_FOUND` — all HTTP 404.

Foreign keys supplied in a request body are resolved with the same codes. Whenever a payload names a `building_id`, `asset_id`, `pm_plan_id`, `funding_project_id`, `vendor_id`, `space_id`, or `zone_space_id` that does not resolve to an existing row, the corresponding not-found code is returned. A `funding_project_id` that does not resolve yields `ERR_PROJECT_NOT_FOUND`; a `zone_space_id` that does not resolve yields `ERR_SPACE_NOT_FOUND`.

### 2.6. The Order in Which a Request Is Judged

Because a single request can violate several rules at once, the order of evaluation is fixed and the first failure wins. The sequence is:

1. **Authentication** — headers present and the role recognised, else `ERR_UNAUTHENTICATED`.
2. **Role authorisation** — the caller's role is listed for the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. **Request shape** — every required field present, every enum value legal, every numeric constraint honoured, else `ERR_INVALID_REQUEST`. The numeric constraints checked here are: `gross_area_sqm` greater than zero; `area_sqm` greater than zero; `share_pct` greater than zero and at most 100; `hourly_rate` greater than zero; `base_cost` greater than zero; `end_at` strictly later than `start_at`; `effective_to` no earlier than `effective_from`; `period_end` strictly later than `period_start`; `planned_headcount` at least 1; `estimated_labor_hours` and `estimated_parts_cost` each at least zero; `interval_days` at least 1; `grace_days` at least zero; `sla_response_minutes` and `sla_resolve_minutes` each at least 1; `consumption_kwh` and `cost` each at least zero; `base_rate_per_sqm_month` at least zero; `end_date` strictly later than `start_date`; `limit` within 1 to 100 inclusive; `offset` at least zero.
4. **Path existence** — every resource named in the path exists, left to right, else the matching 404 code.
5. **Body foreign-key existence** — every foreign key in the payload resolves, else the matching 404 code.
6. **Resource ownership** — the entity-backed ownership rules of §2.1, else `ERR_NOT_RESOURCE_OWNER`.
7. **Segregation of duties** — the capital-project rule below, else `ERR_SEGREGATION_OF_DUTIES`.
8. **Optimistic concurrency** — the version check of §2.7, else `ERR_STALE_VERSION`.
9. **Transition legality** — the target resource is in a state from which the requested transition is declared, else one of `ERR_WORK_ORDER_NOT_OPEN`, `ERR_DISPATCH_NOT_ACTIONABLE`, `ERR_SHIFT_NOT_SCHEDULED`, `ERR_STATEMENT_NOT_ACTIONABLE`, `ERR_LEASE_NOT_DRAFT`, `ERR_PROJECT_NOT_PROPOSED`, or `ERR_ASSET_NOT_IN_SERVICE` (all HTTP 409).
10. **Referenced-parent state** — the asset a work order names is not `RETIRED` (else `ERR_ASSET_RETIRED`), the capital project a work order draws on is `APPROVED` or `IN_FLIGHT` (else `ERR_PROJECT_NOT_FUNDABLE`), and the lease a statement is created for or issued against is `ACTIVE` (else `ERR_LEASE_NOT_ACTIVE`) — all HTTP 409.
11. **Building posture gate** — §2.8, else `ERR_BUILDING_FROZEN` or `ERR_BUILDING_RESTRICTED`.
12. **Vendor eligibility** — a suspended vendor may not be dispatched, else `ERR_VENDOR_SUSPENDED`.
13. **Trade competence** — else `ERR_VENDOR_TRADE_MISMATCH`.
14. **Cross-aggregate coherence** — else `ERR_PM_PLAN_ASSET_MISMATCH`, `ERR_ASSET_BUILDING_MISMATCH`, or `ERR_SPACE_BUILDING_MISMATCH`.
15. **Shift overlap** — else `ERR_SHIFT_OVERLAP`.
16. **Statement period** — else `ERR_STATEMENT_PERIOD_INVALID` or `ERR_STATEMENT_PERIOD_DUPLICATE`.
17. **Allocation capacity** — else `ERR_SPACE_SHARE_EXCEEDED`.
18. **Uniqueness** — else `ERR_DUPLICATE_BUILDING_CODE`, `ERR_DUPLICATE_ASSET_TAG`, or `ERR_DUPLICATE_SPACE_CODE`.
19. **Capital funding** — else `ERR_PROJECT_BUDGET_EXCEEDED`.

Steps 1 and 2 apply to every endpoint. Step 3 applies to every write endpoint and every list endpoint. Step 4 applies to every endpoint that has a path parameter. The rest apply to the specific operations named in §3.

The segregation-of-duties rule at step 7 governs capital-project decisions only: the `FinanceController` deciding a project must not be the user who proposed it, that is, the decider's `X-User-ID` must differ from the project's `proposed_by_user_id`. If they are the same, the decision is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and — because it is judged at step 7 — it is refused before the project's own status is even examined.

### 2.7. Optimistic Concurrency on Work Orders and Leases

Two write operations in the system destroy work that a client may not have seen, and both are therefore guarded by an optimistic-concurrency check against the parent's `version`.

The first is dispatch creation. A request to dispatch a work order must carry a non-optional field `expected_work_order_version` holding the `version` of that work order as the client last read it. If the value does not equal the work order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because dispatch creation legitimately supersedes any dispatch on the order that is still sitting in `OFFERED`, cancelling it; a client working from a stale view of the order would silently cancel an offer it never observed, and the version check converts that into a deterministic refusal instead.

The second is statement creation. A request to draft a chargeback statement for a lease must carry a non-optional field `expected_lease_version` holding the `version` of that lease as the client last read it. If it does not equal the lease's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Here the guard exists because a new statement for a period that already holds a `DRAFT` statement legitimately voids that draft and re-collects its work orders; a client working from a stale view of the lease — whose allocations may have moved since it read them — would void and re-price a draft it never observed.

No other endpoint in the API takes a version field, and no other endpoint performs a version check. Note also that both of these operations advance their parent's `version` on success, so a client that drafts two statements for the same lease must re-read the lease between them.

### 2.8. Operating Posture: the Building-Level Gate

Every building carries an `operating_posture`, one of `OPEN`, `RESTRICTED`, or `FROZEN`. It is never set by a caller. It is derived, and it is recomputed from scratch after every asset failure report, every work-order creation, every quality-assurance decision, every work-order cancellation, and every operational epoch run.

The derivation reads two counters that the building also exposes. `oos_critical_asset_count` is the number of assets in the building whose `criticality` is `CRITICAL` and whose `status` is `OUT_OF_SERVICE`; a `RETIRED` asset does not count towards it. `open_p1_work_order_count` is the number of work orders in the building whose `priority` is `P1` and whose `status` is one of `NEW`, `DISPATCHED`, `IN_PROGRESS`, or `PENDING_QA`. From those two counters: if `oos_critical_asset_count` is at least 1, the posture is `FROZEN`; otherwise, if `open_p1_work_order_count` is at least 2, the posture is `RESTRICTED`; otherwise the posture is `OPEN`. A brand-new building with no assets and no work orders is therefore `OPEN`, and a building with exactly one open `P1` order is `OPEN` while a building with exactly two is `RESTRICTED`.

The posture gates writes into the building. While a building is `FROZEN`, a new work order is refused with `ERR_BUILDING_FROZEN` (HTTP 409) unless it is both `CORRECTIVE` and priority `P1` — the crisis is only allowed to be fixed, not worked around — and scheduling any soft-service shift in that building is refused with `ERR_BUILDING_FROZEN` regardless of its service line. While a building is `RESTRICTED`, a new work order of priority `P3` or `P4` is refused with `ERR_BUILDING_RESTRICTED` (HTTP 409), while `P1` and `P2` orders pass; soft-service scheduling is unaffected by `RESTRICTED`.

### 2.9. Money, Measurement and Rounding

All monetary amounts are held to 2 decimal places and rounded half up. Where a formula in §3 specifies a rounding point, that is the *only* rounding point: intermediate products and sums are carried at full precision until the stated round is applied. This matters most in the chargeback computation, where rounding happens per line and the lines are then summed — summing first and rounding once produces a different total whenever two lines carry a repeating fraction, and it is wrong.

Two figures depart from the two-decimal default. The building energy-intensity KPI is rounded half up to 3 decimal places. SLA durations are measured in whole minutes, computed by taking the elapsed seconds between the two instants and discarding the remainder — that is, rounding down to the whole minute below. Asset condition scores are held to 2 decimal places and clamped into the closed range 0 to 100.

### 2.10. Conserved Quantities

Two invariants in this system are conserved quantities: the system maintains a total and a remainder that always sum back to the whole, and every forward action has a compensating reverse action that restores the remainder exactly.

The first is space occupancy. For any space, `allocated_share_pct` and `free_share_pct` always sum to exactly 100, after every allocation and after every release. The second is capital funding: for any capital project, `budget_amount` minus `committed_amount` minus `spent_amount` always equals `remaining_amount`, and every work order that draws on a project either eventually charges the project (on closure) or hands the money back (on cancellation, or on the estimate being revised). Neither invariant is allowed to drift; both are recomputed from the underlying rows on every touching operation rather than patched incrementally.

---

## 3. Business Logic & Workflows

### 3.1. Portfolio Foundations: Buildings, Spaces, Assets and Preventive Plans

A `PlatformAdmin` or `FacilityManager` registers a building by supplying its `name`, a `code`, and its `gross_area_sqm` — the gross leasable and serviceable floor area in square metres, which serves as the denominator for utility pro-rata, for the occupancy KPI, and for the O&M share of every chargeback statement. A `region` label may also be supplied; it is purely informational. The `code` must be unique across the entire portfolio; a repeat is refused with `ERR_DUPLICATE_BUILDING_CODE`. A newly registered building comes up with `operating_posture` at `OPEN`, `oos_critical_asset_count` at 0, and `open_p1_work_order_count` at 0.

Spaces are the sub-divisions of a building. Each is created inside its parent building with a `space_code` that must be unique within that building — a repeat is refused with `ERR_DUPLICATE_SPACE_CODE`, and note that two buildings may freely use the same space code. A space also declares its `floor` number, its rentable `area_sqm` in square metres, and its `space_type`, one of `OFFICE`, `LAB`, `RETAIL`, `COMMON`, or `PLANT`. An optional `cost_center` code may be attached for chargeback reporting. Every space is born empty: `allocated_share_pct` at 0, `free_share_pct` at 100, and `occupancy_status` at `VACANT`. The space carries its parent's identifier in `building_id`, and a listing of a building's spaces may be narrowed by `occupancy_status`.

Assets are the plant items a building depends on: chillers, lifts, sprinkler risers, switchgear, pumps. Registering one requires the `building_id` it serves, an `asset_tag` that is unique across the whole estate (a repeat is refused with `ERR_DUPLICATE_ASSET_TAG`), a `category` drawn from `HVAC`, `ELEVATOR`, `FIRE`, `ELECTRICAL`, or `PLUMBING`, and a `criticality` of `CRITICAL`, `STANDARD`, or `LOW`. Cumulative `runtime_hours` since the last preventive visit may be supplied at registration and otherwise starts at 0. A fresh asset enters `IN_SERVICE` with `failure_count` at 0 and `last_pm_at` unset, and its `condition_score` is computed immediately from the runtime it was registered with. A building's assets can be listed and narrowed by `status`.

The condition score is a decay curve. Start from 100. Subtract 5 points for each *complete* block of 1000 runtime hours the asset has accumulated — 999 hours cost nothing, 1000 hours cost 5, 1999 hours still cost 5, 2000 hours cost 10 — and subtract a further 12 points for every failure in `failure_count`. Clamp the result into the range 0 to 100 (never below 0, never above 100) and hold it to 2 decimal places, rounded half up. The score is recomputed on asset registration, on every failure report, and whenever a preventive order on the asset passes quality assurance.

When a `FacilityManager` or `PlatformAdmin` reports a failure, the asset moves `IN_SERVICE → OUT_OF_SERVICE`; reporting a failure on an asset that is not `IN_SERVICE` is refused with `ERR_ASSET_NOT_IN_SERVICE`. The report increments `failure_count` by 1, recomputes `condition_score`, and recomputes the parent building's `oos_critical_asset_count`. If the failed asset was `CRITICAL`, that count reaches at least 1 and the building's posture becomes `FROZEN` — from either `OPEN` or `RESTRICTED`. Freezing is not a passive label: it suspends work across the whole building. Every preventive-maintenance plan on any asset of that building that is currently `ACTIVE` moves `ACTIVE → SUSPENDED`, and every soft-service shift of that building that is currently `SCHEDULED` moves `SCHEDULED → CANCELLED`. Those shift cancellations are *not* the vendor's fault and carry no penalty of any kind against the vendor.

Against that asset register sit the **preventive-maintenance plans**. A preventive-maintenance plan is created against an asset by naming its `asset_id`, the `interval_days` between visits, the `grace_days` of tolerance allowed after a visit falls due, and the `next_due_at` instant at which the next visit becomes due. `interval_days` must be at least 1 and `grace_days` at least zero. A plan is born `ACTIVE`, and its lifecycle states are `ACTIVE`, `SUSPENDED`, and `RETIRED`, of which `RETIRED` is terminal. Plans of an asset can be listed and narrowed by `status`.

Independently of that lifecycle, every plan exposes a `compliance_state` that is derived freshly from the logical clock — it is recomputed on every read of the plan and during every operational epoch run. Compare the clock to the plan's own `next_due_at`. If the clock is strictly earlier than `next_due_at`, the plan is `ON_TIME`. If the clock has reached or passed `next_due_at` but has not passed `next_due_at` advanced by `grace_days` days, the plan is `DUE` — both ends of that grace window are inclusive, so the instant exactly equal to `next_due_at` is already `DUE`, and the instant exactly equal to the end of the grace window is still `DUE`. Beyond that, the plan is `OVERDUE`. A `RETIRED` plan keeps whatever value it last computed; a `SUSPENDED` plan still computes a compliance state, but it takes no part in the promotion described in §3.8.

The plan lifecycle is driven entirely by forces outside the plan itself. A plan is `SUSPENDED` when its building's posture becomes `FROZEN`, and it returns `SUSPENDED → ACTIVE` when the posture leaves `FROZEN` — that is, when the building becomes `OPEN` or `RESTRICTED` again. And a plan is retired when its asset is: whether the plan was `ACTIVE` or `SUSPENDED` at the time, it moves to `RETIRED` when the asset it covers is retired, and it never promotes again.

### 3.2. Vendors, Trades and Standing

A vendor is registered with its company `name`, the single `trade` it is certified for — one of `HVAC`, `ELEVATOR`, `FIRE`, `ELECTRICAL`, `PLUMBING`, `JANITORIAL`, or `SECURITY` — its contracted `hourly_rate`, and the two SLA windows in its contract: `sla_response_minutes`, the minutes from dispatch within which it must accept a job, and `sla_resolve_minutes`, the minutes from dispatch within which it must complete it. Both windows must be at least 1 minute and the rate must be greater than zero. A newly registered vendor has `status` `ACTIVE`, `strike_count` 0, `completed_dispatch_count` 0, and both `performance_score` and `lifetime_performance_score` at 100.00.

Vendor standing is a strike ladder. A vendor earns one strike whenever a dispatch of theirs completes having missed either SLA leg, and one strike whenever one of their soft-service shifts is marked as missed during an operational epoch run. Each such event adds 1 to `strike_count`. When the incremented count reaches exactly 2, the vendor's `status` becomes `PROBATION`; when it reaches 3 or more, the vendor's `status` becomes `SUSPENDED`. A vendor in `ACTIVE` or `PROBATION` standing may be given new work; a `SUSPENDED` vendor may not, and any attempt to dispatch to one is refused with `ERR_VENDOR_SUSPENDED`. Declining an offer is not misconduct and never adds a strike.

Suspension is retroactive as well as prospective. At the moment a vendor crosses into `SUSPENDED` — whether through a completion breach or a missed shift — every dispatch of that vendor still sitting in `OFFERED` moves `OFFERED → CANCELLED`, and each of those cancelled dispatches' work orders reverts `DISPATCHED → NEW`, with `dispatched_at`, `sla_response_due_at`, and `sla_resolve_due_at` all cleared back to unset. The work has to be re-offered to somebody else.

Both performance scores are weighted averages over the vendor's *completed* dispatches, and both are recomputed at the same two moments: whenever a dispatch of the vendor completes, and whenever a work order of the vendor undergoes quality assurance, on either outcome. Take the vendor's dispatches whose `status` is `COMPLETED`, ordered by `completed_at` ascending with `created_at` ascending as the tie-break. The **rolling** score, exposed as `performance_score`, considers only the 3 most recent entries of that ordered set, so that old failures age out of the figure a facility manager reads before choosing a vendor. The **lifetime** score, exposed as `lifetime_performance_score`, considers every completed dispatch the vendor has ever had; with four or more dispatches and one old breach the two figures legitimately disagree on identical data.

Whichever set is selected, if it is empty the score is 100.00. Otherwise compute three rates over the selected dispatches: the response rate is the fraction of them whose `sla_response_met` is true; the resolve rate is the fraction whose `sla_resolve_met` is true; and the QA rate is the fraction whose work order has a `failed_qa_count` of zero. The score is 100 multiplied by the sum of the response rate weighted at 0.4, the resolve rate weighted at 0.3, and the QA rate weighted at 0.3, rounded half up to 2 decimal places. Only dispatches actually sitting in `COMPLETED` count: a dispatch pushed back out of completion by a failed quality check leaves the set entirely until it completes again — and because its work order's `failed_qa_count` stays incremented, when it does come back it contributes nothing to the QA rate.

### 3.3. Capital Projects and the Funding Ledger

A capital project is proposed against a building by supplying its `building_id`, a `title`, and a `base_cost` greater than zero. On creation the server derives the whole funding ledger in a pinned order. First it selects a `contingency_pct` from the base cost alone: 0.10 if `base_cost` is at most 100,000; otherwise 0.07 if it is at most 500,000; otherwise 0.05. The lookup key is always the *base* cost and never the derived budget — the tiers may look circular, but they are not. Second, `contingency_amount` is the base cost multiplied by that percentage, rounded half up to 2 decimal places. Third, `budget_amount` is the base cost plus the contingency amount, rounded half up to 2 decimal places. Fourth, `remaining_amount` is the budget amount less `committed_amount` less `spent_amount`, rounded half up to 2 decimal places; both of those start at zero on a new project, so a fresh project's remaining amount equals its budget. The project's `proposed_by_user_id` is recorded from the caller's `X-User-ID`.

The project starts in `PROPOSED`. A `FinanceController` decides it by supplying a `decision` of either `APPROVE` or `REJECT` — but not if that controller is the same user who proposed it (see §2.6). On `APPROVE`, the project moves `PROPOSED → APPROVED`, `approved_by_user_id` records the deciding `X-User-ID`, and the budget becomes drawable by work orders. On `REJECT`, the project moves `PROPOSED → REJECTED`, `approved_by_user_id` likewise records the deciding `X-User-ID`, and `budget_amount`, `committed_amount`, and `spent_amount` are frozen where they stand; a rejected project can never fund a work order. Deciding a project that is not in `PROPOSED` is refused with `ERR_PROJECT_NOT_PROPOSED`.

The ledger moves in three ways once the project is live. `committed_amount` is at all times the sum of `estimated_amount` across the work orders funded by the project whose `status` is `NEW`, `DISPATCHED`, `IN_PROGRESS`, or `PENDING_QA` — money promised but not yet spent. `spent_amount` is the sum of `billable_amount` across the work orders funded by the project whose `status` is `CLOSED` — money actually gone. And `remaining_amount` is always the budget less the committed less the spent. The first work order that names an `APPROVED` project as its funder pulls the project `APPROVED → IN_FLIGHT`, and the project's committed amount rises by that order's estimate.

Nothing may over-draw the project. Whenever a work order names a `funding_project_id`, the project's remaining amount must cover the order's newly computed `estimated_amount`. At creation time that means the project's remaining amount must be at least the new estimate. At dispatch time — when the estimate is re-derived against the vendor's actual rate — the check is against the project's remaining amount *plus the estimate this order was already holding*, because that older hold is about to be given back; that combined figure must be at least the newly computed estimate. Either way, a shortfall is refused with `ERR_PROJECT_BUDGET_EXCEEDED` (HTTP 402), and a work order naming a project whose status is neither `APPROVED` nor `IN_FLIGHT` is refused earlier, with `ERR_PROJECT_NOT_FUNDABLE`. A building's capital projects can be listed and narrowed by `status`.

### 3.4. Raising Work Orders

A work order is the unit of work in the system, and it carries two independent status dimensions on the same row: an execution dimension in `status` and a billing dimension in `billing_status`. The two advance separately and neither waits for the other.

A `FacilityManager` or `PlatformAdmin` raises an order by naming the `building_id` it belongs to, its `wo_type` (`CORRECTIVE`, `PREVENTIVE`, or `SOFT_SERVICE`), its `priority` (`P1`, `P2`, `P3`, or `P4`), and the two estimates the provisional cost is derived from: `estimated_labor_hours` and `estimated_parts_cost`, each at least zero. Three optional links may be supplied: an `asset_id`, when the order concerns a specific asset — `SOFT_SERVICE` orders leave it unset; a `pm_plan_id`, when the order fulfils a preventive-maintenance plan; and a `funding_project_id`, when a capital project bankrolls the work. A `chargeable` flag, defaulting to true, decides whether the settled cost is ultimately passed through to tenants. The order is born with `status` `NEW`, `billing_status` `PENDING`, `failed_qa_count` 0, `sla_state` `WITHIN`, `statement_id` unset, `billable_amount` unset, and `actual_labor_hours`, `actual_parts_cost`, `dispatched_at`, `sla_response_due_at`, `sla_resolve_due_at`, and `closed_at` all unset.

Three coherence rules bind the links together. The plan named by `pm_plan_id` must cover the very asset named by `asset_id`, or the request is refused with `ERR_PM_PLAN_ASSET_MISMATCH` (HTTP 422). The asset named by `asset_id` must sit in the building named by `building_id`, or the request is refused with `ERR_ASSET_BUILDING_MISMATCH` (HTTP 422). And an asset that has been retired can no longer take work: naming a `RETIRED` asset is refused with `ERR_ASSET_RETIRED`. Beyond those, the building's posture gate of §2.8 applies here in full.

On creation the order's `estimated_amount` is computed by the **provisional** variant of the costing rule, and because no vendor is attached yet, it uses the house standard labour rate of 80.00 per hour. If a `funding_project_id` was named, the project's `committed_amount` rises by that estimate, its `remaining_amount` is recomputed, and an `APPROVED` project is pulled into `IN_FLIGHT`. Finally the building's `open_p1_work_order_count` is recomputed and the posture with it — which is how raising a second open `P1` order in a building tips it into `RESTRICTED`.

**The costing rule.** Both the provisional estimate and the final settlement run the same core computation; they differ in their inputs and in whether a penalty is deducted at the end. The computation begins by fixing a **reference instant**, which determines whether the job is priced as after-hours work. At work-order creation the reference instant is the logical clock at the moment of creation. At dispatch creation it is that dispatch's `dispatched_at`. At dispatch completion it is the work order's `dispatched_at` — deliberately *not* the completion instant, so that a job priced as a daytime call-out stays a daytime call-out even if the vendor finishes it at midnight. The job counts as after-hours when the UTC hour of the reference instant is earlier than 8, or is 18 or later; a job whose reference instant falls anywhere from 08:00:00 to 17:59:59 UTC is not after-hours.

Next fix the **labour rate**. Where no vendor is attached to the order — at creation, and again after an offer has been declined — the rate is the standard 80.00 per hour. Where a vendor is attached — at dispatch creation, and at dispatch completion — the rate is that vendor's `hourly_rate`.

Now compute. Take the labour hours in play and cap them at 12: any hours beyond the twelfth are simply not billed. Multiply the capped hours by the labour rate, and multiply that product by 1.5 if the job is after-hours, or leave it as it is if it is not; that is the labour component. Add a priority surcharge on top of the labour component: 25 percent of it for a `P1` order, 10 percent for a `P2`, and nothing at all for a `P3` or a `P4`. Then handle parts. The parts markup is tiered on the parts figure itself: 15 percent when the parts figure is at most 500, 10 percent when it is above 500 but at most 2000, and 5 percent when it is above 2000. The billed parts figure is the parts figure increased by its markup. Sum the labour component, the surcharge, and the billed parts to get a gross figure — but never let the gross fall below the minimum call-out charge of 150.00; if the sum is below that, the gross is 150.00. Round the gross half up to 2 decimal places. That single round is the only rounding in the whole computation.

The **provisional** variant stops there: it uses `estimated_labor_hours` and `estimated_parts_cost` as its hours and parts, never deducts an SLA penalty (no SLA outcome exists yet), and writes the rounded gross into the order's `estimated_amount` — the figure that is held against the funding project's committed amount. It runs at work-order creation, at dispatch creation, and again whenever a vendor declines an offer.

The **final settlement** variant runs only when a dispatch completes. It uses the vendor-reported `actual_labor_hours` and `actual_parts_cost` as its hours and parts, always uses the vendor's `hourly_rate`, and then continues past the gross: the penalty is the gross multiplied by the dispatch's `penalty_pct`, rounded half up to 2 decimal places, and the order's `billable_amount` is the gross less that penalty, again rounded half up to 2 decimal places. For identical work the two variants therefore disagree whenever the actuals differ from the estimates or whenever any SLA leg was breached.

### 3.5. Dispatch, SLA and the Completion Cascade

Dispatching an order sends it to a vendor and moves it `NEW → DISPATCHED`. The `FacilityManager` supplies the `vendor_id` being offered the job and the `expected_work_order_version` that §2.7 requires. Several gates apply before the offer stands. The order must be in `NEW` (otherwise `ERR_WORK_ORDER_NOT_OPEN`). The vendor's standing must be `ACTIVE` or `PROBATION` (otherwise `ERR_VENDOR_SUSPENDED`). And when the order names an asset, the vendor's `trade` must equal the asset's `category` — a plumber cannot be sent to a lift, and the mismatch is refused with `ERR_VENDOR_TRADE_MISMATCH` (HTTP 422). If the order draws on a capital project, the budget check of §3.3 applies against the re-derived estimate.

The offer itself is a `Dispatch`, born in `OFFERED` with its `work_order_id`, its `vendor_id`, and its `dispatched_at` stamped from the logical clock; `accepted_at`, `completed_at`, `response_minutes`, `resolve_minutes`, `sla_response_met`, and `sla_resolve_met` all start unset, and `penalty_pct` starts at 0. Creating a dispatch supersedes any earlier dispatch of the same order still sitting in `OFFERED`, which moves `OFFERED → CANCELLED`. The order records the same `dispatched_at`, and from it derives its two deadlines: `sla_response_due_at` is `dispatched_at` advanced by the vendor's `sla_response_minutes` minutes, and `sla_resolve_due_at` is `dispatched_at` advanced by the vendor's `sla_resolve_minutes` minutes. The order's `estimated_amount` is recomputed by the provisional variant, now using the vendor's real `hourly_rate` in place of the standard rate, and any funding project's `committed_amount` moves by the difference between the new estimate and the old one, with `remaining_amount` following. Dispatch creation increments the work order's `version` by 1 — which is precisely why the next dispatch attempt needs a freshly-read `expected_work_order_version`.

A `VendorTech` may **accept** an offer, which moves the dispatch `OFFERED → ACCEPTED` and the work order `DISPATCHED → IN_PROGRESS`. Acceptance stamps `accepted_at` from the clock and computes `response_minutes` as the whole minutes elapsed from `dispatched_at` to `accepted_at`, taking the elapsed seconds and discarding the remainder below a whole minute. It then evaluates `sla_response_met`, which is true when `accepted_at` is at or before `sla_response_due_at` — the boundary is inclusive, so accepting at exactly the deadline is a hit, not a miss. When the response is missed, the work order's `sla_state` moves to `RESPONSE_BREACHED`.

A `VendorTech` may instead **decline** an offer, optionally supplying a `reason`. The dispatch moves `OFFERED → DECLINED` and the work order reverts `DISPATCHED → NEW`. Its `dispatched_at`, `sla_response_due_at`, and `sla_resolve_due_at` are all cleared back to unset — a superseded or declined offer's timing is discarded entirely — and its `estimated_amount` is recomputed by the provisional variant back onto the standard labour rate basis, since no vendor is attached any more; any funding project's `committed_amount` moves by that estimate delta. The declining vendor's `strike_count` is untouched: a decline is a refusal, not a breach. Accepting or declining a dispatch that is not in `OFFERED` is refused with `ERR_DISPATCH_NOT_ACTIONABLE` (HTTP 409), as is completing a dispatch that is not in `ACCEPTED`.

**Completion** is where the system's deepest cascade fires. The `VendorTech` reports its `actual_labor_hours` and `actual_parts_cost`; the dispatch moves `ACCEPTED → COMPLETED` and the work order `IN_PROGRESS → PENDING_QA`. At the first level, the dispatch stamps `completed_at` from the clock, computes `resolve_minutes` as the whole minutes from `dispatched_at` to `completed_at` (again discarding the sub-minute remainder), and evaluates `sla_resolve_met` as true when `completed_at` is at or before `sla_resolve_due_at` — inclusive again. The dispatch's `penalty_pct` is then the sum of 0.10 if the response leg was missed and 0.15 if the resolve leg was missed, capped at 0.25; if both legs were met it is 0. The work order copies the two reported actuals onto its own `actual_labor_hours` and `actual_parts_cost`, sets `sla_state` to `RESOLVE_BREACHED` if the resolve leg was missed — a resolve breach dominates a response breach, so an order that missed both reads `RESOLVE_BREACHED`, and an order that missed only the response leg reads `RESPONSE_BREACHED`, and an order that met both reads `WITHIN` — and computes its `billable_amount` by the final-settlement variant.

At the second level, the vendor's counters move: if either SLA leg was missed, the vendor's `strike_count` rises by 1; `completed_dispatch_count` rises by 1 regardless; and both `performance_score` and `lifetime_performance_score` are recomputed. At the third level, the strike ladder is consulted: a `strike_count` that has just reached exactly 2 puts the vendor into `PROBATION`, and one that has reached 3 or more puts it into `SUSPENDED`. At the fourth level, if the vendor has just been suspended, every one of its dispatches still in `OFFERED` — anywhere in the portfolio, on any building — moves `OFFERED → CANCELLED`, and each of those dispatches' work orders reverts `DISPATCHED → NEW` with `dispatched_at` and both SLA deadlines cleared. A single completion by an over-struck vendor can therefore reshuffle the dispatch board across the entire estate.

Dispatches can be listed and narrowed by `work_order_id`, by `vendor_id`, and by `status`, and read individually with their SLA outcome flags and `penalty_pct` exposed.

### 3.6. Quality Assurance, Closure and Recovery

A completed job is not a finished job. A `FacilityManager` reviews the work and submits an `outcome` of either `PASS` or `FAIL`; a review submitted against an order that is not in `PENDING_QA` is refused with `ERR_WORK_ORDER_NOT_OPEN`.

A `FAIL` is a rework loop. The work order moves `PENDING_QA → IN_PROGRESS`, its `failed_qa_count` rises by 1, and the `COMPLETED` dispatch behind it moves `COMPLETED → ACCEPTED` so the vendor can go back and fix the work. That dispatch's `completed_at`, `resolve_minutes`, `sla_resolve_met`, and `penalty_pct` are all cleared, and the work order's `billable_amount` is reset to unset. Because the dispatch has left the completed set, and because the order's `failed_qa_count` is now permanently non-zero, both of the vendor's performance scores are recomputed — and when the dispatch completes a second time it will contribute nothing to the QA component of either score. The rework is punished in the vendor's reputation, not in a strike.

A `PASS` closes the order. Its `status` moves `PENDING_QA → CLOSED` and `closed_at` is stamped from the logical clock. On the billing dimension, an order whose `chargeable` flag is false moves `billing_status` `PENDING → WAIVED` and is permanently excluded from every statement's O&M share ever after; an order whose `chargeable` flag is true stays at `PENDING`, waiting to be collected by a chargeback statement.

A `PASS` also heals the physical world. If the order was `CORRECTIVE` and named an asset that is currently `OUT_OF_SERVICE`, that asset moves `OUT_OF_SERVICE → IN_SERVICE`. If the order was `PREVENTIVE` and named an asset, the asset's `runtime_hours` is reset to 0, its `failure_count` is decremented by 1 but never below 0, its `last_pm_at` is stamped from the clock, and its `condition_score` is recomputed on the restarted decay curve; and if the order also named a `pm_plan_id`, that plan's `next_due_at` is pushed forward by its own `interval_days` days.

The building then re-derives itself. Both `open_p1_work_order_count` and `oos_critical_asset_count` are recomputed and the posture with them. This is the route out of `FROZEN`: when the corrective order that restored the last out-of-service critical asset passes review, the count of out-of-service critical assets drops to zero and the building leaves `FROZEN` — landing in `OPEN` if at most one `P1` order remains open, or in `RESTRICTED` if two or more remain open. Either way, every preventive-maintenance plan of that building's assets sitting in `SUSPENDED` moves back to `ACTIVE`. Note the asymmetry with the freeze: leaving `FROZEN` reactivates the suspended plans, but it does *not* restore the soft-service shifts that the freeze cancelled — those are gone and must be rescheduled.

Finally, if the closed order was funded by a capital project, the ledger settles: the project's `committed_amount` falls by the order's `estimated_amount` (the hold is released) and its `spent_amount` rises by the order's `billable_amount` (the real money is charged), with `remaining_amount` recomputed from both.

**Cancellation** is the other way an order can leave the pipeline. A `FacilityManager` may cancel an order that is in `NEW` or in `DISPATCHED`, moving it to `CANCELLED`; an order in any other status — an `IN_PROGRESS` order in particular — cannot be cancelled and the attempt is refused with `ERR_WORK_ORDER_NOT_OPEN`. Cancelling a `DISPATCHED` order also cancels the dispatch sitting on it: an `OFFERED` dispatch moves `OFFERED → CANCELLED`, and in the rare case where a decline or supersede has left an `ACCEPTED` dispatch on an order that is still `DISPATCHED`, that dispatch moves `ACCEPTED → CANCELLED` too. Cancellation is the compensating action for the funding invariant: if the order named a funding project, the project's `committed_amount` falls by the order's `estimated_amount` and its `remaining_amount` is restored to exactly its pre-creation value, while `spent_amount` is left untouched — the money was never spent. The building's `open_p1_work_order_count` and posture are recomputed, so cancelling one of two open `P1` orders takes a `RESTRICTED` building back to `OPEN`.

### 3.7. Soft-Service Coordination

Janitorial and security work is scheduled as shifts rather than work orders. A `FacilityManager` schedules one by naming the `building_id`, the `vendor_id` staffing it, the `zone_space_id` — the space within that building the crew will cover — the `service_type` (`JANITORIAL` or `SECURITY`), a `start_at`, an `end_at` strictly later than the start, and a `planned_headcount` of at least 1. The shift is born `SCHEDULED` with `actual_headcount` unset.

Three checks guard the schedule. The vendor's `trade` must equal the requested `service_type`, or the request is refused with `ERR_VENDOR_TRADE_MISMATCH`. The zone space must sit in the same building as the shift, or the request is refused with `ERR_SPACE_BUILDING_MISMATCH`. And a crew cannot be in two places at once: a new shift whose interval intersects an existing shift of the *same* vendor that is `SCHEDULED` or `IN_PROGRESS` is refused with `ERR_SHIFT_OVERLAP` (HTTP 409), and the check ignores building, zone, and service line entirely — the resource being protected is the vendor, not the space. The interval is **half-open**: it includes its start instant and excludes its end instant. A new shift that begins at exactly the instant an existing shift of the same vendor ends therefore does *not* collide, and both may stand.

A `VendorTech` reports a shift as delivered by supplying the `actual_headcount` that turned up; the shift moves to `COMPLETED` from either `SCHEDULED` or `IN_PROGRESS`. Completing a shift that is in any other status is refused with `ERR_SHIFT_NOT_SCHEDULED` (HTTP 409). Shifts can be listed and narrowed by `building_id`, `vendor_id`, `zone_space_id`, and `status`.

Shifts that nobody reports are swept up by the epoch run described next, and a swept-up shift becomes `MISSED` — which is a strike against the vendor. A shift cancelled by a building freeze, by contrast, is nobody's fault and costs the vendor nothing.

### 3.8. The Operational Epoch

Buildings do not tick by themselves; a `FacilityManager` or `PlatformAdmin` advances a building's operational epoch against the current logical clock, and the epoch run performs six sweeps in a fixed order, reporting what it did.

**First, preventive-maintenance promotion.** The run gathers the plans of that building's assets that are `ACTIVE`, whose freshly computed `compliance_state` is `OVERDUE`, and that do not already have a work order pointing at them in a status other than `CLOSED` or `CANCELLED`. Plans that are `SUSPENDED` — because their building is frozen — and plans that are `RETIRED` are skipped entirely. The gathered plans are processed in ascending `next_due_at`, with `created_at` ascending as the tie-break, and each one produces a new work order in the building on the plan's asset, carrying the plan's identifier, with `wo_type` `PREVENTIVE`, `priority` `P2`, `chargeable` true, `estimated_labor_hours` of 3, `estimated_parts_cost` of 200.00, no funding project, and `status` `NEW`; the provisional costing variant then prices it. Because a plan that already has an open preventive order is skipped, running the epoch twice in the same epoch produces the promotions only once. The identifiers of the new orders come back as `created_work_order_ids`.

**Second, the shift sweep.** A `SCHEDULED` shift whose `start_at` has been reached or passed by the clock while the clock is still strictly before its `end_at` moves `SCHEDULED → IN_PROGRESS`, and its identifier comes back in `in_progress_shift_ids`. A shift whose `end_at` has been reached or passed by the clock and which is still `SCHEDULED`, or still `IN_PROGRESS`, moves to `MISSED`, and its identifier comes back in `missed_shift_ids`. Each miss adds 1 to the vendor's `strike_count` and runs the same standing ladder as a completion breach — exactly 2 strikes puts the vendor in `PROBATION`, 3 or more puts it in `SUSPENDED`, and a fresh suspension cancels that vendor's `OFFERED` dispatches everywhere and reverts their work orders `DISPATCHED → NEW`.

**Third, asset retirement.** An asset that is `OUT_OF_SERVICE` and whose `condition_score` has fallen below 20 moves `OUT_OF_SERVICE → RETIRED`; its identifier comes back in `retired_asset_ids`. Retiring the asset retires every plan of that asset that is `ACTIVE` or `SUSPENDED`. And because a `RETIRED` asset is no longer counted as out of service, the building's `oos_critical_asset_count` falls — which is the second route out of a `FROZEN` posture: the crisis is resolved by writing the asset off rather than by fixing it.

**Fourth, lease expiry.** A lease that is `ACTIVE` and whose `end_date` the clock has strictly passed moves `ACTIVE → EXPIRED`; its identifier comes back in `expired_lease_ids`. Every allocation of that lease that is `ACTIVE` moves to `RELEASED`, and each affected space's `free_share_pct` rises back by exactly that allocation's `share_pct`.

**Fifth, capital-project closure.** A project that is `IN_FLIGHT`, whose `committed_amount` has fallen to exactly zero, and at least one of whose funded work orders has reached `CLOSED`, moves `IN_FLIGHT → CLOSED`; its identifier comes back in `closed_project_ids`. A closed project can no longer be named as the funder of any new work order.

**Sixth and last, the posture is recomputed** from the two counters, exactly as §2.8 prescribes, and the resulting `posture` is returned alongside the five identifier lists.

### 3.9. Occupancy, Utilities, Tenant Chargeback and the Building KPI Surface

A lease is drafted against a building with its `building_id`, the `tenant_name`, the `base_rate_per_sqm_month` charged per allocated square metre per month, and the inclusive `start_date` and `end_date` of the term. It is born `DRAFT` with `allocated_area_sqm` at 0. Leases of a building can be listed and narrowed by `status`.

Space is given to a lease through allocations. Each allocation names the `space_id` being taken, the `share_pct` of that space's area the lease is taking — greater than zero and at most 100 — and the closed interval it applies over, from `effective_from` to `effective_to`. Unlike a soft-service shift, this interval is **fully closed**: both endpoints belong to the interval, so an allocation that starts on exactly the day an existing allocation ends *does* cover a shared date, and both allocations are considered to be covering it. The space must belong to the lease's own building, or the allocation is refused with `ERR_SPACE_BUILDING_MISMATCH`. An allocation is born `ACTIVE`.

The capacity rule is aggregate, not exclusive. Two leases may hold shares of the same space over the same dates, provided the shares fit: for every date inside the new allocation's closed interval, the sum of `share_pct` across the space's `ACTIVE` allocations whose own closed intervals cover that date, plus the new `share_pct`, must not exceed 100. If it would exceed 100 on any single date, the request is refused with `ERR_SPACE_SHARE_EXCEEDED` (HTTP 422).

After every allocation and every release, the space's derived figures are recomputed as of the current logical clock date. `allocated_share_pct` is the sum of `share_pct` across the space's `ACTIVE` allocations whose closed interval covers today's clock date, rounded half up to 2 decimal places; `free_share_pct` is 100 less that figure, likewise rounded; and `occupancy_status` is `OCCUPIED` when the allocated share is greater than zero and `VACANT` otherwise. The lease's `allocated_area_sqm` is recomputed at the same time as the sum, over the lease's `ACTIVE` allocations, of each allocated space's `area_sqm` multiplied by that allocation's `share_pct` divided by 100, with the sum rounded half up to 2 decimal places at the end.

Releasing an allocation is a soft delete: the row is retained but its `status` moves `ACTIVE → RELEASED`. A released allocation is excluded from every derived figure immediately, so a release restores the space's `free_share_pct` to exactly the value it had before the allocation was made. Released rows are also hidden from allocation listings unless a caller explicitly filters on the `RELEASED` status; listings may otherwise be narrowed by `lease_id`, by `space_id`, and by `status`.

A `DRAFT` lease is activated by a `FinanceController` or `PlatformAdmin`, moving it `DRAFT → ACTIVE` and incrementing the lease's `version` by 1. A lease may only be activated if it is in `DRAFT` and it already holds at least one `ACTIVE` allocation; both an activation attempt on a non-`DRAFT` lease and an activation attempt on a `DRAFT` lease with no active allocation are refused with `ERR_LEASE_NOT_DRAFT` (HTTP 409).

**Utility readings** are appended by a `SustainabilityAnalyst`, a `FacilityManager`, or a `PlatformAdmin` against a `building_id`. Each names the `meter_type` (`ELECTRIC`, `GAS`, or `WATER`), the inclusive `period_start` and `period_end` the reading covers, the `consumption_kwh` in kWh-equivalent units, and the `cost` of that metered period. Readings are immutable once written, and a building's readings can be listed and narrowed by `meter_type`.

**A chargeback statement** bills one lease for one calendar month. The `FinanceController` or `PlatformAdmin` supplies the `period_start` and `period_end`, which must be exactly the first and last instant of one and the same calendar month — anything else is refused with `ERR_STATEMENT_PERIOD_INVALID` (HTTP 422) — plus the `expected_lease_version` that §2.7 requires. The lease must be `ACTIVE`, or the request is refused with `ERR_LEASE_NOT_ACTIVE`. If a statement for the same lease and the same `period_start` already exists with a status of `ISSUED`, `DISPUTED`, or `SETTLED`, the new statement is refused with `ERR_STATEMENT_PERIOD_DUPLICATE` (HTTP 409). If the existing statement for that period is still in `DRAFT`, however, it is not an obstacle: it moves `DRAFT → VOID`, and every work order carrying that voided statement's identifier reverts its `billing_status` `INVOICED → PENDING` with its `statement_id` cleared, so that the superseding statement may collect those orders afresh. Creating a statement increments the lease's `version` by 1.

The statement's four money fields are then computed, and the order of rounding matters more than anything else in this document. Let the relevant allocations be those of the lease whose `status` is `ACTIVE` and whose closed interval overlaps the statement period, taken in ascending `created_at`.

- `base_rent` is computed **per allocation line and rounded per line, then summed**. For each such allocation, take the allocated space's `area_sqm`, multiply by that allocation's `share_pct` divided by 100, multiply by the lease's `base_rate_per_sqm_month`, and round the result half up to 2 decimal places. Sum those rounded line figures.
- `utility_share` is likewise computed **per allocation line and rounded per line, then summed**. First total the `cost` of the building's utility readings whose own inclusive `period_start`-to-`period_end` window is *fully contained* within the statement period, both ends inclusive — a reading that straddles the boundary is not counted at all, and all three meter types count towards this total. Then for each relevant allocation, take that total utility cost, multiply it by the allocation's allocated area (the space's `area_sqm` multiplied by the allocation's `share_pct` divided by 100) divided by the building's `gross_area_sqm`, and round the result half up to 2 decimal places. Sum those rounded line figures.
- `om_share` is computed **per work order and rounded per work order, then summed**. Let the lease's share of the building be its `allocated_area_sqm` divided by the building's `gross_area_sqm`. The collectable orders are those of the same building whose `status` is `CLOSED`, whose `billing_status` is `PENDING`, whose `chargeable` flag is true, and whose `closed_at` falls within the statement period, both ends inclusive. For each such order, multiply its `billable_amount` by the lease's share, round the result half up to 2 decimal places, and sum those rounded figures. Orders that are `WAIVED`, already `INVOICED`, or already `SETTLED_CHARGEBACK` are never re-collected.
- `total_amount` is the sum of the three already-rounded figures — `base_rent` plus `utility_share` plus `om_share` — rounded half up to 2 decimal places. There is no further rounding pass over the underlying lines; summing the raw lines and rounding once at the end is a different number and it is wrong.

Every work order the statement collects moves its `billing_status` `PENDING → INVOICED` and records the statement's identifier in its `statement_id`. Work orders can themselves be listed and narrowed by `building_id`, `asset_id`, `pm_plan_id`, `funding_project_id`, `statement_id`, `status`, and `billing_status` — the last of which is how a finance controller finds what is still uncollected.

The statement then walks its own lifecycle, from `DRAFT` through `ISSUED`, possibly `DISPUTED`, to `SETTLED` — with `VOID` as the other terminal outcome. Issuing a `DRAFT` statement moves it `DRAFT → ISSUED` and stamps `issued_at` from the logical clock; the lease must still be `ACTIVE` or the issue is refused with `ERR_LEASE_NOT_ACTIVE`. A `TenantRep` — and only the one whose lease this is — may dispute an `ISSUED` statement by supplying a `dispute_reason`, moving it `ISSUED → DISPUTED` and recording the reason. Issuing again from `DISPUTED` moves it `DISPUTED → ISSUED`, re-stamps `issued_at`, retains the `dispute_reason`, and — crucially — recomputes `base_rent`, `utility_share`, `om_share`, and `total_amount` from scratch against current data, so a genuine correction upstream is reflected in the re-issued figures. Settling an `ISSUED` statement moves it `ISSUED → SETTLED`, stamps `settled_at` from the clock, and moves every work order carrying that statement's identifier from `billing_status` `INVOICED → SETTLED_CHARGEBACK`. Issuing a statement that is in neither `DRAFT` nor `DISPUTED`, disputing one that is not `ISSUED`, or settling one that is not `ISSUED`, is refused with `ERR_STATEMENT_NOT_ACTIONABLE` (HTTP 409). A lease's statements can be listed and narrowed by `status`.

**The KPI dashboard** summarises one building over an inclusive window bounded by `window_start` and `window_end`. Both are optional: `window_start` defaults to `1970-01-01T00:00:00Z` and `window_end` defaults to the current logical clock, so a caller who supplies neither gets the building's whole history to date. The dashboard computes nothing persistent — it is a pure read.

Only the building's utility readings whose own inclusive metered period is *fully contained* in the window contribute to the energy figures. `energy_intensity_kwh_per_sqm` is the sum of `consumption_kwh` over those contained readings whose `meter_type` is `ELECTRIC` or `GAS` — water is deliberately excluded from intensity — divided by the building's `gross_area_sqm`, rounded half up to 3 decimal places. `total_utility_cost` is the sum of `cost` over those same contained readings across all three meter types, rounded half up to 2 decimal places.

`open_work_order_count` is the number of the building's work orders whose `status` is `NEW`, `DISPATCHED`, `IN_PROGRESS`, or `PENDING_QA`. `sla_compliance_pct` is 100 multiplied by the fraction of the building's `COMPLETED` dispatches that met *both* SLA legs — that is, whose `sla_response_met` and `sla_resolve_met` are both true — rounded half up to 2 decimal places. `pm_compliance_pct` is 100 multiplied by the fraction of the building's `ACTIVE` preventive-maintenance plans whose freshly computed compliance state is anything other than `OVERDUE` (so both `ON_TIME` and `DUE` plans count as compliant), rounded half up to 2 decimal places. `occupancy_pct` is 100 multiplied by the sum of `area_sqm` over the building's spaces whose `occupancy_status` is `OCCUPIED`, divided by the building's `gross_area_sqm`, rounded half up to 2 decimal places. And `posture` simply echoes the building's current `operating_posture`.

The empty-set behaviour of each figure is pinned, because a building with nothing in it must not report a division by zero. With no completed dispatches, `sla_compliance_pct` is 100.00. With no active plans, `pm_compliance_pct` is 100.00. With no readings inside the window, `energy_intensity_kwh_per_sqm` is 0.0 and `total_utility_cost` is 0.00. With no occupied spaces, `occupancy_pct` is 0.00.

---

## 4. Endpoint Definitions

All endpoints are mounted under the `/fm` prefix. Creating a new resource returns HTTP 201; every other successful operation — reads, state transitions, releases, and the epoch run — returns HTTP 200. Every request body, every query parameter, and every side effect is specified in the narratives of §2 and §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/fm/buildings` | Create a building; posture starts `OPEN`. | PlatformAdmin, FacilityManager |
| GET | `/fm/buildings/{id}` | Read a building including its derived posture and counters. | PlatformAdmin, FacilityManager, FinanceController, SustainabilityAnalyst, VendorTech, TenantRep |
| GET | `/fm/buildings/{id}/kpi` | KPI dashboard for a building over an inclusive window. | PlatformAdmin, FacilityManager, FinanceController, SustainabilityAnalyst |
| POST | `/fm/buildings/{id}/ops-run` | Advance the building's operational epoch against the logical clock. | PlatformAdmin, FacilityManager |
| POST | `/fm/buildings/{id}/spaces` | Create a space in a building. | PlatformAdmin, FacilityManager |
| GET | `/fm/buildings/{id}/spaces` | List the spaces of a building. | PlatformAdmin, FacilityManager, FinanceController, TenantRep |
| GET | `/fm/spaces/{id}` | Read a space, including its live share figures as of the logical clock. | PlatformAdmin, FacilityManager, FinanceController, TenantRep |
| POST | `/fm/assets` | Register an asset in a building. | PlatformAdmin, FacilityManager |
| GET | `/fm/assets/{id}` | Read an asset. | PlatformAdmin, FacilityManager, FinanceController, VendorTech |
| GET | `/fm/buildings/{id}/assets` | List the assets of a building. | PlatformAdmin, FacilityManager, FinanceController |
| POST | `/fm/assets/{id}/report-failure` | Report an asset failure; origin of the posture cascade. | PlatformAdmin, FacilityManager |
| POST | `/fm/pm-plans` | Create a preventive-maintenance plan for an asset. | PlatformAdmin, FacilityManager |
| GET | `/fm/assets/{id}/pm-plans` | List an asset's PM plans with freshly computed compliance state. | PlatformAdmin, FacilityManager |
| POST | `/fm/vendors` | Register a vendor with its contracted rate and SLA windows. | PlatformAdmin, FacilityManager |
| GET | `/fm/vendors/{id}` | Read a vendor, including both variants of the performance score. | PlatformAdmin, FacilityManager, FinanceController, VendorTech |
| POST | `/fm/work-orders` | Raise a work order; gated by the building's posture. | PlatformAdmin, FacilityManager |
| GET | `/fm/work-orders/{id}` | Read a work order. | PlatformAdmin, FacilityManager, FinanceController, VendorTech |
| GET | `/fm/work-orders` | Filtered list of work orders. | PlatformAdmin, FacilityManager, FinanceController |
| POST | `/fm/work-orders/{id}/dispatches` | Dispatch a work order to a vendor; OCC-guarded on the work order. | PlatformAdmin, FacilityManager |
| POST | `/fm/work-orders/{id}/qa` | Quality-assure a completed order; `PASS` closes it, `FAIL` reworks it. | PlatformAdmin, FacilityManager |
| POST | `/fm/work-orders/{id}/cancel` | Cancel a `NEW` or `DISPATCHED` work order. | PlatformAdmin, FacilityManager |
| GET | `/fm/dispatches/{id}` | Read a dispatch, including SLA outcome flags and penalty. | PlatformAdmin, FacilityManager, FinanceController, VendorTech |
| GET | `/fm/dispatches` | Filtered list of dispatches. | PlatformAdmin, FacilityManager, FinanceController, VendorTech |
| POST | `/fm/dispatches/{id}/accept` | Vendor accepts an `OFFERED` dispatch. | VendorTech |
| POST | `/fm/dispatches/{id}/decline` | Vendor declines an `OFFERED` dispatch; the order returns to `NEW`. | VendorTech |
| POST | `/fm/dispatches/{id}/complete` | Vendor completes an `ACCEPTED` dispatch with its actuals. | VendorTech |
| POST | `/fm/soft-service-shifts` | Schedule a janitorial or security shift on a zone. | PlatformAdmin, FacilityManager |
| GET | `/fm/soft-service-shifts/{id}` | Read a shift. | PlatformAdmin, FacilityManager, VendorTech |
| GET | `/fm/soft-service-shifts` | Filtered list of shifts. | PlatformAdmin, FacilityManager, VendorTech |
| POST | `/fm/soft-service-shifts/{id}/complete` | Vendor reports the shift as delivered. | VendorTech |
| POST | `/fm/utility-readings` | Append an immutable utility meter reading for a building. | PlatformAdmin, FacilityManager, SustainabilityAnalyst |
| GET | `/fm/buildings/{id}/utility-readings` | List a building's meter readings. | PlatformAdmin, FacilityManager, FinanceController, SustainabilityAnalyst |
| POST | `/fm/leases` | Create a lease in `DRAFT`. | PlatformAdmin, FacilityManager, FinanceController |
| GET | `/fm/leases/{id}` | Read a lease. | PlatformAdmin, FacilityManager, FinanceController, TenantRep |
| GET | `/fm/buildings/{id}/leases` | List a building's leases. | PlatformAdmin, FacilityManager, FinanceController |
| POST | `/fm/leases/{id}/activate` | Activate a `DRAFT` lease that already holds an `ACTIVE` allocation. | PlatformAdmin, FinanceController |
| POST | `/fm/leases/{id}/allocations` | Allocate a share of a space to a lease over a closed date interval. | PlatformAdmin, FacilityManager, FinanceController |
| GET | `/fm/lease-allocations/{id}` | Read one allocation. | PlatformAdmin, FacilityManager, FinanceController, TenantRep |
| GET | `/fm/lease-allocations` | Filtered list of allocations; `RELEASED` rows excluded unless requested. | PlatformAdmin, FacilityManager, FinanceController, TenantRep |
| DELETE | `/fm/lease-allocations/{id}` | Release an allocation (soft: the row is retained as `RELEASED`). | PlatformAdmin, FacilityManager, FinanceController |
| POST | `/fm/leases/{id}/statements` | Draft a monthly chargeback statement; OCC-guarded on the lease. | PlatformAdmin, FinanceController |
| GET | `/fm/statements/{id}` | Read a statement. | PlatformAdmin, FacilityManager, FinanceController, TenantRep |
| GET | `/fm/leases/{id}/statements` | List a lease's statements. | PlatformAdmin, FacilityManager, FinanceController, TenantRep |
| POST | `/fm/statements/{id}/issue` | Issue a `DRAFT` statement, or re-issue a `DISPUTED` one. | PlatformAdmin, FinanceController |
| POST | `/fm/statements/{id}/dispute` | Tenant disputes an `ISSUED` statement. | TenantRep |
| POST | `/fm/statements/{id}/settle` | Settle an `ISSUED` statement. | PlatformAdmin, FinanceController |
| POST | `/fm/capital-projects` | Propose a capital project. | PlatformAdmin, FacilityManager, FinanceController |
| GET | `/fm/capital-projects/{id}` | Read a capital project and its funding ledger. | PlatformAdmin, FacilityManager, FinanceController |
| GET | `/fm/buildings/{id}/capital-projects` | List a building's capital projects. | PlatformAdmin, FacilityManager, FinanceController |
| POST | `/fm/capital-projects/{id}/approve` | Decide a `PROPOSED` project; the decider must not be the proposer. | FinanceController |
| POST | `/fm/_clock/set_current_utc` | Set the server's logical clock. | PlatformAdmin |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_PROJECT_BUDGET_EXCEEDED` | 402 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_BUILDING_NOT_FOUND` | 404 |
| `ERR_SPACE_NOT_FOUND` | 404 |
| `ERR_ASSET_NOT_FOUND` | 404 |
| `ERR_PM_PLAN_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_OPEN` | 409 |
| `ERR_DISPATCH_NOT_ACTIONABLE` | 409 |
| `ERR_SHIFT_NOT_SCHEDULED` | 409 |
| `ERR_STATEMENT_NOT_ACTIONABLE` | 409 |
| `ERR_LEASE_NOT_DRAFT` | 409 |
| `ERR_LEASE_NOT_ACTIVE` | 409 |
| `ERR_PROJECT_NOT_PROPOSED` | 409 |
| `ERR_PROJECT_NOT_FUNDABLE` | 409 |
| `ERR_ASSET_NOT_IN_SERVICE` | 409 |
| `ERR_ASSET_RETIRED` | 409 |
| `ERR_BUILDING_FROZEN` | 409 |
| `ERR_BUILDING_RESTRICTED` | 409 |
| `ERR_VENDOR_SUSPENDED` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_STATEMENT_PERIOD_DUPLICATE` | 409 |
| `ERR_DUPLICATE_BUILDING_CODE` | 409 |
| `ERR_DUPLICATE_ASSET_TAG` | 409 |
| `ERR_DUPLICATE_SPACE_CODE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VENDOR_TRADE_MISMATCH` | 422 |
| `ERR_PM_PLAN_ASSET_MISMATCH` | 422 |
| `ERR_ASSET_BUILDING_MISMATCH` | 422 |
| `ERR_SPACE_BUILDING_MISMATCH` | 422 |
| `ERR_STATEMENT_PERIOD_INVALID` | 422 |
| `ERR_SPACE_SHARE_EXCEEDED` | 422 |

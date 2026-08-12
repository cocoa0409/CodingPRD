# Feed Mill Operations & Ration Formulation API — Product Requirements Document

## 1. Introduction

A commercial feed mill earns its margin in the gap between volatile ingredient markets and the fixed promises it makes to livestock customers. Rations must be reformulated as spot prices move, forward contracts must be consumed before their windows lapse, medicated and non-medicated products must never cross-contaminate a shared production line, and every custom-mix order must be priced, produced, sampled, and delivered under audit-grade control. The Feed Mill Operations & Ration Formulation API is the system of record for that operation: least-cost ration formulation under nutrient constraints, ingredient inventory with physical bin assignment, batching accuracy with sequencing rules that prevent carryover, medicated-feed flushing under segregation of duties, quality sampling with retained-sample custody, delivery scheduling across compartmented bulk trucks, and customer credit exposure tracked from quote to delivery.

This document specifies that API for the engineers who will implement it. Section 2 fixes the system-wide contracts — roles, response envelopes, pagination, the logical clock, optimistic concurrency, rounding discipline, pricing and credit principles, and the order in which validation layers are evaluated. Section 3 walks the business workflows entity by entity, Section 4 summarizes the endpoint catalogue, and Section 5 enumerates the error codes. Five personas interact with the mill through the API: the `MillManager` who administers the plant, the `Nutritionist` who authors rations, the `Operator` crew running the floor, the `QualityTech` who gates release, and the `Customer` who quotes and confirms orders.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API. Where Section 3 narrates workflows, this section is the precise contract those workflows obey.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. Five roles are recognized, spelled exactly: `MillManager`, `Nutritionist`, `Operator`, `QualityTech`, and `Customer`. Each endpoint declares the roles admitted to it; a caller whose role is not admitted is rejected with `ERR_FORBIDDEN`.

The five roles fall into two identity models. When `X-User-Role` is `MillManager` or `Nutritionist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. When `X-User-Role` is `Operator` or `QualityTech`, `X-User-ID` is the `id` of the acting `Employee`; checks on resources that record an employee — such as a flush record's `recorded_by_employee_id` — compare that field against `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's customer reference against `X-User-ID`, and a `Customer` caller can only ever see their own orders and the trips belonging to those orders — an identifier belonging to another customer resolves exactly as if the resource did not exist, surfacing `ERR_NOT_FOUND`.

The two entity-backed floor roles are additionally gated by capability. An `Employee` is registered by a `MillManager` with a `full_name` and a `capability` of `OPERATOR`, `QUALITY_TECH`, or `DUAL`. Acting as `Operator` requires an employee whose `capability` is `OPERATOR` or `DUAL`; acting as `QualityTech` requires `QUALITY_TECH` or `DUAL`. A capability mismatch — a quality-only technician attempting an operator action, for instance — is rejected with `ERR_FORBIDDEN`. An `X-User-ID` that does not resolve to any registered `Employee` fails this check identically, with `ERR_FORBIDDEN`.

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
- The `api_request_timestamp` of both envelopes is generated from the server's wall clock, not from the logical mill clock of §2.5.
- A request to an unrecognized path, or to a recognized path with an unsupported method, is answered with `ERR_NOT_FOUND` (404) in this same error envelope; an unexpected internal fault is answered with `error_id` `ERR_INTERNAL` and HTTP 500.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is clamped at a maximum of 100. `offset` skips a number of items and defaults to 0. A `limit` below 1 is clamped up to 1 and a negative `offset` is clamped up to 0; a non-integer value for either parameter is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with resources sharing one `created_at` instant ordered by creation sequence, earliest-created first. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

All primary resources share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-05-01T00:00:00.000Z`), recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one with every mutation of the resource, including mutations driven by cascading side effects from elsewhere in the system. A resource is born with `version` 1, and its `updated_at` initially equals its `created_at`.

Derived fields are always recomputed immediately, inside the request that mutates their inputs; the API never answers a successful write with stale derived values. One resource breaks the versioning pattern deliberately: a `PriceTick` is an immutable, append-only market event and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.5. The Logical Mill Clock

Every rule in this document that says "now" — price effectiveness, contract windows, sample expiry, batch timestamps — reads a logical mill clock, never the wall clock. Before any adjustment, the logical clock reads exactly 2026-05-01T00:00:00Z. A `MillManager`-only capability sets the clock to a supplied `to_iso8601` instant — any instant is accepted as given, including one behind the current reading; no monotonicity check is applied — and the response echoes the new reading as `current_utc`. Advancing the clock triggers the contract expiry sweep: every `OPEN` contract whose window end has passed with tonnage still remaining transitions to `EXPIRED`, and provisional formula costs are recomputed wherever contract selector pools changed. The same expiry evaluation also runs lazily whenever an individual contract is read.

### 2.6. Optimistic Concurrency Control

Three write operations guard against stale client views through an explicit expected-version field, and all other endpoints take no version field at all.

Creating a customer order requires the request to carry `expected_customer_version`, holding the `version` of the customer as the client last observed it. If the customer's current `version` has advanced past that value — because another writer has created an order or otherwise mutated the customer's credit posture — the create is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412): the client must not write from a view of the customer it has not re-observed. The same field and the same rejection govern a `MillManager`'s adjustment of a customer's credit limit or medicated permit. Re-reading the customer and retrying with the fresh version succeeds, because creating several orders for one customer is a legitimate flow.

Re-running ration optimization requires `expected_formula_version`, matched against the formula's current `version`; a mismatch is rejected with `ERR_STALE_FORMULA_VERSION` (HTTP 412), since the client's view of the ration's lines and cost basis is stale. Sequential re-read of the formula and retry with the fresh version succeeds, because re-optimization is a legitimate, repeatable operation.

### 2.7. Monetary Precision and Rounding Discipline

All money is carried as integer cents. Tonnages are carried to three decimal places. A tonnage supplied at finer precision than three decimals is rounded half-up to three decimals at intake rather than rejected; the exceptions are a bin's `capacity_tons`, a compartment's `capacity_tons`, and a flush's `quantity_tons`, which are recorded exactly as supplied. Nutrient totals, deviation percentages, and dry-matter assay corrections are rounded to two decimal places. Every rounding in the system is round half up.

Rounding is pinned to specific stages, and the pinning is part of the contract. Each weighment's `line_cost_cents` is rounded to integer cents at the moment the weighment is recorded — before any summation — and batch and order totals aggregate those already-rounded amounts; summing unrounded products and rounding once at the end is a forbidden alternative. The provisional cost projection rounds half up exactly once, at the end of the projection. Once persisted, no derived money figure ever changes retroactively: a late-arriving price tick or a contract event takes effect on the next evaluation only, and already-recorded weighment costs and quoted or final order totals stand as written.

### 2.8. Spot Pricing and Contract Coverage Principles

The effective spot price of an ingredient at an instant T is the `price_cents_per_ton` of that ingredient's price tick with the greatest `effective_from` at or before T; when several ticks share that `effective_from`, the one with the latest `created_at` wins. If no tick of the ingredient has an `effective_from` at or before T, the ingredient has no effective price at all: it is excluded from the optimizer's candidate set, and a weighment attempting to draw it is rejected with `ERR_INVALID_REQUEST`.

Forward contracts overlay the spot market through a single, shared selector policy. For a given ingredient at instant T, the contract pool is every `OPEN` contract of that ingredient whose `window_start_date` is on or before the date of T and whose `window_end_date` is on or after it. The pool is always consumed in the same order: earliest `window_end_date` first (use-it-or-lose-it), ties broken toward the lower `fixed_price_cents_per_ton`, further ties toward the earlier `created_at`. The least-cost ration projection, the quoted price of an order, and the pricing of an individual weighment all draw from this same pool under this same ranking.

### 2.9. Medicated Feed Governance and Segregation of Duties

Medicated product is the mill's regulatory perimeter. An ingredient's `hazard_class` of `MEDICATED` propagates into everything downstream: a formula containing one produces medicated orders, medicated batches, and medicated cargo. A customer may confirm a medicated order only when a regulatory permit reference is on file. A production line remembers its most recent medicated mix as a contamination state, and a non-medicated batch may not start on a contaminated line until an approved flush has been recorded and independently verified. Flushing is subject to segregation of duties: the employee who recorded a flush may never be the employee who verifies it. Medicated cargo travels only on trucks built for it, and every compartment allocation on a delivery trip must agree with the order's medicated flag.

### 2.10. Credit Exposure and Fiscal Discipline

Each customer trades against a `credit_limit_cents` ceiling. The live exposure, `credit_used_cents`, is the sum of `quoted_total_cents` over the customer's orders in `CONFIRMED` or `IN_PRODUCTION`, plus the sum of `final_total_cents` over the customer's orders in `COMPLETED`. Orders in `QUOTED`, `REVISING`, `DELIVERED`, or `CANCELLED` contribute nothing. Exposure moves as orders move: it is charged at confirmation, released when a revision begins, re-charged when the revision commits, reclassed from quoted to final at completion, and released entirely on delivery or cancellation. The credit gate itself admits equality: an order whose quoted total would bring the exposure exactly to the limit passes.

### 2.11. Validation Order of Evaluation

When a request fails several rules at once, the layer that reports first is fixed. The layers, earliest first:

1. Authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`).
2. Request schema — required fields present, types valid, enum members in range, tonnages positive, datetimes parseable, and any planned end strictly after its planned start (`ERR_INVALID_REQUEST`).
3. Authorization — the role is admitted to the endpoint and, for the floor roles, the employee's capability covers the role (`ERR_FORBIDDEN`).
4. Existence — path identifiers resolve left to right, and body identifiers (formula, order, line, bin, ingredient, truck, contract) exist; customer-scoped callers see only their own resources (`ERR_NOT_FOUND`). Body identifiers are resolved in the order the fields are named in the endpoint's payload description. For a nested address such as the price-tick collection beneath an ingredient, the parent identifier is validated before the child collection is consulted.
5. Optimistic concurrency — expected-version fields match the current `version` (`ERR_STALE_CUSTOMER_VERSION`, `ERR_STALE_FORMULA_VERSION`).
6. State preconditions — transition from-states and cross-entity state requirements, including blocked bins and blocked orders (`ERR_INVALID_STATE`, `ERR_BIN_BLOCKED`, `ERR_ORDER_BLOCKED`).
7. Medicated and safety gates (`ERR_FLUSH_REQUIRED`, `ERR_MEDICATED_PERMIT_REQUIRED`, `ERR_SOD_VIOLATION`, `ERR_QUALITY_NOT_PASSED`, `ERR_CARGO_CLASS_MIX`, `ERR_TRUCK_NOT_MEDICATED_CAPABLE`).
8. Temporal and window rules (`ERR_LINE_WINDOW_CONFLICT`, `ERR_TRUCK_WINDOW_CONFLICT`, `ERR_CONTRACT_WINDOW_OVERLAP`, `ERR_RETAIN_EXPIRY_INVALID`).
9. Uniqueness, capacity, and constraint checks, evaluated within this layer in exactly this order: duplicate codes (`ERR_DUPLICATE_CODE`); bin assignment on a non-empty bin (`ERR_BIN_NOT_EMPTY`); replenish beyond capacity (`ERR_BIN_CAPACITY_EXCEEDED`); a weighment bin holding a different ingredient (`ERR_BIN_INGREDIENT_MISMATCH`); insufficient bin stock (`ERR_INSUFFICIENT_INVENTORY`); a weighed ingredient outside the pinned formula (`ERR_INGREDIENT_NOT_IN_FORMULA`); per-line mix deviation beyond tolerance (`ERR_WEIGHMENT_OUT_OF_TOLERANCE`); compartment capacity (`ERR_COMPARTMENT_CAPACITY_EXCEEDED`) — always evaluated before the order-level tonnage check; trip tonnage over-allocation (`ERR_ORDER_TONNAGE_OVERALLOCATED`); completion quantity mismatch (`ERR_ORDER_TONS_MISMATCH`); optimizer infeasibility (`ERR_FORMULA_NOT_FEASIBLE`); nutrient constraints unmet at activation (`ERR_NUTRIENT_CONSTRAINT_VIOLATION`); a discontinued ingredient referenced (`ERR_INGREDIENT_NOT_ACTIVE`); retirement of a formula pinned by live orders (`ERR_FORMULA_IN_USE`); unapproved flush material (`ERR_FLUSH_MATERIAL_INVALID`); flush quantity below the minimum (`ERR_FLUSH_QUANTITY_BELOW_MIN`).
10. Fiscal gates, evaluated last: quote freshness at confirmation (`ERR_QUOTE_STALE`), then credit headroom (`ERR_CREDIT_LIMIT_EXCEEDED`).

## 3. Business Logic & Workflows

### 3.1. Ingredient Catalogue and Spot Price Ticks

Everything the mill produces is built from the ingredient catalogue. A `MillManager` registers an ingredient with a unique `code` (a duplicate is refused with `ERR_DUPLICATE_CODE`), a display `name`, a `hazard_class` of `STANDARD` or `MEDICATED`, and an `is_flush_material` flag that defaults to false and marks whether the ingredient is approved as flush material. The nutrient profile is captured at registration as `crude_protein_pct`, `crude_fiber_pct`, and `metabolizable_energy_kcal_kg`, each of which must be zero or greater. A new ingredient starts in `ACTIVE` status.

Spot prices arrive as an append-only stream of ticks. Each tick names the `ingredient_id` it applies to, a positive `price_cents_per_ton`, and an `effective_from` instant — which may legitimately be earlier than the moment the tick is recorded, since market data arrives late. Ticks are never updated or deleted, and they are listable per ingredient so the history of a price can be audited. A tick may be recorded for an ingredient in any status; only the ingredient's existence is required. Recording a tick is never a quiet event: the provisional cost of every `DRAFT` or `ACTIVE` formula containing that ingredient is recomputed at once. As stated in §2.7, a late-arriving tick takes effect on the next evaluation only — already-recorded weighment costs and already-quoted order totals never change retroactively.

When an ingredient leaves the catalogue, a `MillManager` discontinues it, moving it from `ACTIVE` to the terminal `DISCONTINUED`. Only an `ACTIVE` ingredient can be discontinued; any other status draws `ERR_INVALID_STATE`. Discontinuation ripples outward in the same request: every bin still holding stock of the ingredient moves from `READY` to `BLOCKED`, and every formula in `DRAFT` or `ACTIVE` whose lines contain the ingredient is force-retired to `RETIRED` — the `ERR_FORMULA_IN_USE` protection that guards manual retirement does not apply to this cascade. The ingredient's own `version` increments, each blocked bin's `version` increments, and each retired formula's `version` increments.

### 3.2. Procurement Contracts and Coverage Windows

Against a volatile spot market, the mill buys forward. A `MillManager` registers a contract with the covered `ingredient_id`, a `supplier_ref`, a positive `fixed_price_cents_per_ton`, a positive `total_tons` carried to three decimal places, and a coverage window given as `window_start_date` and `window_end_date` in `YYYY-MM-DD` form. Both dates are inclusive — the window is a closed interval. A `window_end_date` earlier than `window_start_date` fails schema validation with `ERR_INVALID_REQUEST`. Two rules guard creation: the ingredient must be `ACTIVE` (a contract for a discontinued ingredient is refused with `ERR_INGREDIENT_NOT_ACTIVE`), and the window must not collide with any other contract of the same ingredient that is `OPEN` or `EXHAUSTED`. The overlap test follows closed-interval semantics: a new window whose start date exactly equals an existing window's end date conflicts, and the violation is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`. `EXPIRED` and `CANCELLED` contracts do not block new coverage. Registering a contract recomputes the provisional cost of every `DRAFT` or `ACTIVE` formula containing the ingredient.

Consumption is tracked live. A contract's `consumed_tons` is the sum of `actual_tons` over its `RECORDED` weighments, and its `remaining_tons` is `total_tons` minus `consumed_tons`, both carried to three decimals. The conservation invariant holds: weighing W tons against a contract and then voiding that same weighment restores `remaining_tons` to its prior value.

A contract is born `OPEN` and then lives four distinct lives. When a recorded weighment drives `remaining_tons` to exactly zero, the contract moves `OPEN` → `EXHAUSTED` on its own: it leaves the pricing selector pool, the provisional cost of every affected formula is recomputed, and customer orders still `QUOTED` against those formulas flip their derived `quote_stale` flag to true. When a voided weighment lifts `remaining_tons` back above zero, the contract moves `EXHAUSTED` → `OPEN`, re-enters the selector pool, and triggers the same provisional-cost recompute. When the logical clock's date passes `window_end_date` while `remaining_tons` is still above zero — evaluated when the clock is advanced, when an individual contract is read, when the contract collection is listed, and before a cancellation is processed, so a window-past contract refuses cancellation with `ERR_INVALID_STATE` — the contract moves `OPEN` → `EXPIRED`, leaves the pool, and recomputes affected formulas. Finally, a `MillManager` may cancel an `OPEN` contract outright, moving it `OPEN` → `CANCELLED` with the same pool exit and recompute. `EXPIRED` and `CANCELLED` are terminal; `EXHAUSTED` is not. Every one of these transitions increments the contract's `version` by one.

Contracts are listable with optional `ingredient_id` and `status` filters, so a buyer can survey all coverage for one ingredient or all contracts in a given lifecycle state.

### 3.3. Bin Assignment and Inventory Conservation

Physical stock lives in bins. A `MillManager` creates a bin with a unique `code` and a positive `capacity_tons`; the bin starts `EMPTY` with no `ingredient_id` assigned. Assignment is permitted only while `on_hand_tons` is exactly zero — the boundary passes, and any residual stock at all draws `ERR_BIN_NOT_EMPTY`. Assignment requires the ingredient to exist (`ERR_NOT_FOUND`); the ingredient's own status is not consulted. Once assigned, the assignment is retained even after the bin later empties; a new ingredient may be assigned only while the bin stands empty.

Replenishment adds stock by `tons`. A replenish requires the bin to be assigned and not `BLOCKED` — an unassigned bin refuses with `ERR_INVALID_STATE`, a blocked bin with `ERR_BIN_BLOCKED` — and the resulting level must not exceed `capacity_tons`; a replenishment landing exactly on capacity passes, while anything above is rejected with `ERR_BIN_CAPACITY_EXCEEDED`. The first accepted replenishment after assignment moves the bin `EMPTY` → `READY`. Each accepted replenishment adds `tons` to both `on_hand_tons` and `cumulative_replenished_tons` and increments the bin's `version`.

The running level obeys a conservation law: `on_hand_tons` is always `cumulative_replenished_tons` minus the sum of `actual_tons` over the bin's `RECORDED` weighments. Replenish X, weigh Y, then void that same weighment, and the bin reads X again. When a drawdown brings `on_hand_tons` to exactly zero, the bin moves `READY` → `EMPTY` automatically, retaining its ingredient assignment. Recording or voiding a weighment changes only derived bin state, so the bin's `version` is left untouched by those events unless the derived status actually flips: the `READY` → `EMPTY` flip on a drawdown to exactly zero and the `EMPTY` → `READY` flip when a void restores stock to an empty bin each increment the bin's `version` by one, while a drawdown or restoration that leaves the status unchanged does not. A bin reaches `BLOCKED` only through the ingredient-discontinuation cascade; a `MillManager` may then unblock it, moving `BLOCKED` → `READY`, provided stock remains — an unblocking attempt on an empty blocked bin, or on a bin that is not `BLOCKED` at all, is refused with `ERR_INVALID_STATE`. Status derivation is otherwise mechanical: `EMPTY` exactly when `on_hand_tons` is zero, `READY` otherwise, `BLOCKED` only by cascade. Bins are listable with optional `ingredient_id` and `status` filters.

### 3.4. Ration Formulation and Least-Cost Optimization

A `Nutritionist` authors a formula with a unique `code` and its nutrient contract: a floor `min_protein_pct`, a ceiling `max_fiber_pct`, and a floor `min_energy_kcal_kg`. A new formula starts in `DRAFT` with empty `lines` — nothing has been solved yet. Its nutrient totals and `provisional_cost_cents_per_ton` are null, and `meets_constraints` is false, until the first optimization run.

Optimization is the heart of the mill. Running it against a formula is not a state transition: it recomputes the formula's `lines`, totals, `meets_constraints`, and `provisional_cost_cents_per_ton` in place, increments the formula's `version` by one, and is allowed in both `DRAFT` and `ACTIVE`. The request must carry `expected_formula_version` per §2.6. The solve proceeds as a greedy waterfall. The candidate set is every ingredient that is `ACTIVE` and has an effective spot price at the current clock (per §2.8). If the candidate set is empty, or if seventy percent per candidate multiplied by the number of candidates falls short of one hundred percent, the run is rejected with `ERR_FORMULA_NOT_FEASIBLE`. Candidates are ranked cheapest first; ties on price break toward the higher `crude_protein_pct`, and further ties break toward the earlier `created_at`. Starting from a remaining share of one hundred percent, each candidate in rank order contributes the smaller of seventy percent and the remaining share; a line is appended only when that contribution is positive, and the walk stops the moment the remaining share reaches zero. Each appended line records the `ingredient_id` and its `inclusion_pct`.

From the solved lines, the nutrient totals follow: `total_protein_pct` is the sum over lines of each `inclusion_pct` times its ingredient's `crude_protein_pct`, divided by one hundred and rounded half-up to two decimals; `total_fiber_pct` and `total_energy_kcal_kg` are computed identically from `crude_fiber_pct` and `metabolizable_energy_kcal_kg`. The formula `meets_constraints` exactly when `total_protein_pct` is at least `min_protein_pct`, `total_fiber_pct` is at most `max_fiber_pct`, and `total_energy_kcal_kg` is at least `min_energy_kcal_kg`.

The provisional cost answers "what would one ton of this ration cost right now?" The projection prices one reference ton: each line's share of that ton is its `inclusion_pct` divided by one hundred. For each line independently, the contract pool of §2.8 — `OPEN` contracts of that ingredient covering the current date, ranked by earliest window end, then lowest fixed price, then earliest creation — is consumed in order; each contract covers the smaller of its own `remaining_tons` and the line's still-uncovered remainder at its `fixed_price_cents_per_ton`, and whatever remains uncovered prices at the effective spot price. Each line's projection is independent — there is no cross-line netting of contract tonnage. `provisional_cost_cents_per_ton` is the sum of the per-line projections, rounded half-up once at the very end to integer cents. This projection recomputes on optimization, on any price tick creation for a line ingredient, on any contract creation, cancellation, exhaustion, expiry, or reopening touching a line ingredient, and on a weighment void that reopens a contract. Recomputation never increments the formula's `version` — only optimize, activate, and retire do.

Activation moves `DRAFT` → `ACTIVE` and is refused unless three conditions hold: `lines` is non-empty, `meets_constraints` is true (else `ERR_NUTRIENT_CONSTRAINT_VIOLATION`), and every line ingredient is `ACTIVE` (else `ERR_INGREDIENT_NOT_ACTIVE`). Retirement moves `DRAFT` or `ACTIVE` → `RETIRED`, a terminal state, and is shared between the `Nutritionist` and the `MillManager`. Manually retiring an `ACTIVE` formula is refused with `ERR_FORMULA_IN_USE` while any live order — one in `CONFIRMED`, `REVISING`, `IN_PRODUCTION`, or `COMPLETED` — pins it; the ingredient-discontinuation cascade ignores this guard, as §3.1 notes. Retirement does not strand production: orders that already pinned the formula keep their `pinned_lines` snapshot and remain batchable. Both transitions increment the formula's `version`.

### 3.5. Customers, Credit, and the Order Lifecycle

A `MillManager` registers a customer with a display `name`, a positive `credit_limit_cents`, and an optional `medicated_permit_ref` — null by default, and null means the customer is not permitted to purchase medicated feed. A new customer starts `ACTIVE`. The manager may later suspend and reinstate the customer (`ACTIVE` ↔ `SUSPENDED`), each change incrementing the customer's `version`, and may adjust the credit limit or the permit reference; that adjustment must carry `expected_customer_version` per §2.6 and increments the customer's `version` even when the payload alters neither field. Setting the status the customer already holds is refused with `ERR_INVALID_STATE`. A `Customer` caller may read only their own record.

Ordering begins with a quote. A `Customer` creates an order with a payload naming the `formula_id`, the ordered `tons` (positive, three decimal places), and `expected_customer_version`; the `customer_id` is taken from the caller's `X-User-ID`, never from the payload. A caller whose `X-User-ID` is not the id of a registered customer is rejected with `ERR_NOT_FOUND`. The formula must be `ACTIVE` — ordering against anything else is rejected with `ERR_INVALID_STATE`. The system stamps the formula's current `version` into `quoted_formula_version` and its current cost basis into `quoted_cost_basis_cents`, computes `quoted_total_cents` at the current clock, derives `is_medicated` (true exactly when any formula line's ingredient is `MEDICATED`), and starts the order in `QUOTED`. Until confirmation, the four pinned fields — `pinned_formula_version`, `pinned_lines`, `pinned_min_protein_pct`, and `pinned_max_fiber_pct` — remain null, and `final_total_cents` stays null until completion. Creating an order is itself a mutation of the customer's credit posture and increments the customer's `version` by one.

The quoted price follows a pinned evaluation order, and the order matters because later steps consume earlier results. First, each pinned formula line's tonnage is its `inclusion_pct` share of the order's `tons`, rounded half-up to three decimals, and each line's cost is the contract-blend projection of §3.4 applied to that line tonnage — `OPEN` contracts covering the quote date, ranked earliest window end, lowest fixed price, earliest creation, with any uncovered remainder at the effective spot price — rounded half-up to integer cents per line. Second, the subtotal is the sum of those already-rounded line costs. Third, the margin tier is selected on the pre-margin subtotal: twelve percent when the subtotal is at or below $5,000.00, ten percent when it is above $5,000.00 and at or below $20,000.00, and eight percent when it is above $20,000.00. Fourth, the margin itself is rounded half-up to integer cents. Fifth, a medicated surcharge — the order's `tons` times $15.00 per ton, rounded half-up to integer cents — applies only when `is_medicated` is true; otherwise it is zero. Sixth, the delivery fee is a $75.00 base plus the order's `tons` times $9.00 per ton, that product rounded half-up to integer cents before the base is added. `quoted_total_cents` is the subtotal plus the margin plus the surcharge plus the delivery fee.

Between quote and confirmation the market may move, and the order tracks that: `quote_stale` is true exactly when the formula's current `version` differs from `quoted_formula_version` or its current `provisional_cost_cents_per_ton` differs from `quoted_cost_basis_cents`. Confirmation by the customer moves `QUOTED` → `CONFIRMED` through four gates evaluated in order: the order must be `QUOTED` and the customer `ACTIVE` (violations surface `ERR_INVALID_STATE`); a medicated order requires a non-null `medicated_permit_ref` (`ERR_MEDICATED_PERMIT_REQUIRED`); the quote must be fresh (`ERR_QUOTE_STALE`); and `credit_used_cents` plus `quoted_total_cents` must not exceed `credit_limit_cents`, with equality passing (`ERR_CREDIT_LIMIT_EXCEEDED`). On success the order pins the formula snapshot — `pinned_formula_version`, a deep copy of the lines in `pinned_lines`, and the nutrient floors `pinned_min_protein_pct` and `pinned_max_fiber_pct` — the quoted total joins the customer's exposure, and both the customer's and the order's `version` increment.

A confirmed order may be revised. Beginning a revision moves `CONFIRMED` → `REVISING` and is permitted only while no batch of the order is `BATCHING`, `MIXED`, or `HOLD` — violations surface `ERR_INVALID_STATE`; it releases the quoted total from the customer's exposure and increments both versions. Committing the revision moves `REVISING` → `CONFIRMED` with a new, positive `tons`: the order is re-quoted at current prices against the current formula, re-pinning the version, lines, and floors and refreshing `quoted_formula_version`, `quoted_cost_basis_cents`, and `quoted_total_cents`. The commit also re-derives `is_medicated` from the formula's current lines, and it does not re-check the formula's own status — a formula retired since confirmation does not block the commit. Because the snapshot is re-pinned at commit, the staleness gate cannot fire; the permit gate and the credit gate are re-applied exactly as at confirmation. The new exposure is charged and both versions increment.

Cancellation is the customer's (and, shared, the `MillManager`'s). From `QUOTED` or `REVISING` an order cancels freely, incrementing the order's `version`. From `CONFIRMED`, cancellation is refused with `ERR_INVALID_STATE` while any batch of the order is `PLANNED`, `BATCHING`, `MIXED`, or `HOLD`, or any delivery trip is `PLANNED`, `LOADING`, or `IN_TRANSIT`; when it proceeds, the quoted exposure is released and the customer's `version` increments alongside the order's.

Production flips the order on its own: the first batch of the order to start moves it `CONFIRMED` → `IN_PRODUCTION`. Completion is a `MillManager` act permitted only on an `IN_PRODUCTION` order — any other status surfaces `ERR_INVALID_STATE` before the three gates are consulted — with three gates: the order must not be `blocked` — no batch in `HOLD` — (`ERR_ORDER_BLOCKED`); no batch may remain in `PLANNED`, `BATCHING`, `MIXED`, or `HOLD` (`ERR_INVALID_STATE`); and the released tonnage must land within tolerance. The tolerance check divides the absolute gap between the sum of `actual_tons` over the order's `RELEASED` batches and the order's `tons` by the order's `tons`; a deviation strictly above two percent is rejected with `ERR_ORDER_TONS_MISMATCH`, while exactly 0.02 passes. Completion computes the final price, `final_total_cents`, under the same pinned evaluation order as the quote, but with the final variant of line costs: for each ingredient, the sum of `line_cost_cents` over the `RECORDED` weighments of the order's `RELEASED` batches — each already rounded per weighment, and never re-rounded. The customer's exposure reclasses from the quoted total to the final total, and both versions increment.

Delivery closes the loop without any explicit order action: when a trip's delivery leaves every trip of the order in a terminal state, with at least one `DELIVERED`, and the sum of `total_tons` over `DELIVERED` trips exactly equals the order's `tons`, the order moves `COMPLETED` → `DELIVERED`, the exposure for the order drops to zero, and both versions increment. The order's `blocked` flag, used by several gates above, is derived: true exactly when any batch of the order sits in `HOLD`. Order listings accept optional `customer_id`, `formula_id`, and `status` filters — and for a `Customer` caller the customer filter is forced to the caller.

### 3.6. Production Scheduling, Batching, and Weighment Recording

Production runs on lines. A `MillManager` creates a line with a unique `code`; it starts `ACTIVE` and may be moved `ACTIVE` ↔ `DOWN` at will, each change incrementing the line's `version`. Setting the status the line already holds is refused with `ERR_INVALID_STATE`. A line also carries the derived `contamination` flag described in §3.7.

Against those lines, a `MillManager` schedules a batch with a payload naming the `order_id` and `line_id`, a positive `target_tons` (three decimal places), and a planned window given by `planned_start_at` and `planned_end_at` — the end must be strictly after the start, or the request fails schema validation with `ERR_INVALID_REQUEST`. The new batch copies `is_medicated` from its order and starts `PLANNED`. Scheduling imposes no order-state precondition — a batch may be planned against a `QUOTED` order; the order's state is first gated at batch start. Scheduling is subject to a line-window rule with a cleanup tail: every existing batch of the same line in `PLANNED`, `BATCHING`, `MIXED`, `HOLD`, `RELEASED`, or `REJECTED` occupies its planned window extended by a forty-five-minute cleanup buffer (a `CANCELLED` batch frees its window entirely). A new batch conflicts when its planned start falls before an existing batch's buffer-extended end while that existing batch's planned start falls before the new batch's buffer-extended end; the boundary is kind — a new start landing exactly at an existing window's buffer-extended end is allowed. A colliding schedule is rejected with `ERR_LINE_WINDOW_CONFLICT`. Batch listings accept optional `order_id`, `line_id`, and `status` filters.

Starting a batch is an `Operator` act that moves `PLANNED` → `BATCHING` behind four gates: the batch must be `PLANNED`, the line must be `ACTIVE`, and the order must be `CONFIRMED` or `IN_PRODUCTION` (state violations surface `ERR_INVALID_STATE`); the order must not be `blocked` (`ERR_ORDER_BLOCKED`); and the sequencing gate — a batch whose `is_medicated` is false may not start on a line whose `contamination` is `MEDICATED` unless a `VERIFIED` flush exists whose `verified_at` falls after the last medicated batch's `mixed_at` (`ERR_FLUSH_REQUIRED`). When the order's first batch starts, the order itself moves `CONFIRMED` → `IN_PRODUCTION` with its own version bump; the batch's `version` increments as well.

While a batch is `BATCHING`, the `Operator` records weighments against it — each a payload naming the `ingredient_id`, the `bin_id` drawn from, and a positive `actual_tons` read off the scale (three decimals). Five checks guard the record: the ingredient must appear in the order's `pinned_lines` (`ERR_INGREDIENT_NOT_IN_FORMULA`); the bin must be `READY` — a `BLOCKED` bin refuses with `ERR_BIN_BLOCKED`; the bin must be assigned to the weighed ingredient (`ERR_BIN_INGREDIENT_MISMATCH`); the bin's `on_hand_tons` must cover the draw, with equality passing (`ERR_INSUFFICIENT_INVENTORY`); and the ingredient must have an effective spot price at the current clock (`ERR_INVALID_REQUEST`).

Pricing then follows the contract-selector policy, and it is all-or-nothing per weighment. The pool is every `OPEN` contract of the weighed ingredient whose window covers the current date and whose `remaining_tons` covers the entire `actual_tons`; a contract whose remaining tonnage exactly equals the draw is selected and is driven to exhaustion by it. The pool ranks by earliest `window_end_date`, then lowest `fixed_price_cents_per_ton`, then earliest `created_at`. When the pool is non-empty the weighment takes `source` `CONTRACT` with `contract_id` set and `unit_price_cents` at the contract's fixed price; otherwise it takes `source` `SPOT` with `contract_id` null and `unit_price_cents` at the effective spot price. The weighment's `line_cost_cents` is `actual_tons` times `unit_price_cents`, rounded half-up to integer cents at the moment of recording — per-weighment rounding, pinned before any summation. A weighment starts `RECORDED`.

Recording is never free of side effects: the bin's `on_hand_tons` drops by `actual_tons` (a draw to exactly zero flips the bin `READY` → `EMPTY`), and a contract-sourced weighment raises the contract's `consumed_tons` — a remainder of exactly zero flips the contract `OPEN` → `EXHAUSTED` and fires the §3.2 cascade. The batch's own derived figures track the same events: its `actual_tons` is the sum over its `RECORDED` weighments, and its `ingredient_cost_cents` is the sum of their `line_cost_cents`.

A weighment may be voided by an `Operator`, moving `RECORDED` → `VOID`, but only while its parent batch is `BATCHING` — which includes the rework window after a batch returns from `HOLD`. Voiding is the compensating action: it adds `actual_tons` back onto the bin's `on_hand_tons` (a bin sitting at zero returns `EMPTY` → `READY`), it subtracts `actual_tons` from the contract's `consumed_tons` when `contract_id` is set (a contract whose remainder climbs back above zero moves `EXHAUSTED` → `OPEN`, firing the recompute cascade), and it recomputes the provisional cost of every `DRAFT` or `ACTIVE` formula containing the ingredient. The weighment's `version` increments. Weighment listings accept optional `batch_id`, `bin_id`, `ingredient_id`, `contract_id`, and `status` filters, covering every foreign key the weighment carries.

Mixing closes the batching phase. The `Operator`'s mix moves `BATCHING` → `MIXED` behind a per-line accuracy gate: every pinned line must have at least one `RECORDED` weighment, and for every pinned line the line target — that line's `inclusion_pct` share of the batch's `target_tons`, rounded half-up to three decimals — is compared against the sum of `actual_tons` over the line's `RECORDED` weighments. The deviation is the absolute gap divided by the target, expressed as a percentage and rounded half-up to two decimals; any line strictly above 2.00 percent rejects the mix with `ERR_WEIGHMENT_OUT_OF_TOLERANCE`, while a deviation of exactly 2.00 percent passes. A pinned line whose rounded target is zero passes only when its weighed actual is also zero. A successful mix stamps `mixed_at` — null until this moment — from the logical clock, and when the batch is medicated the line's `contamination` becomes `MEDICATED`, derived from that timestamp. The batch's `version` increments. Separately, a `MillManager` may cancel a `PLANNED` batch outright — `PLANNED` → `CANCELLED`, freeing the line window and incrementing the batch's `version`.

### 3.7. Medicated Carryover Control and Flush Verification

A line's `contamination` is a pure derivation from its history. Consider the line's batches with `is_medicated` true and `mixed_at` set; take the one with the latest `mixed_at`, breaking any tie toward the latest `created_at`. The line is `MEDICATED` exactly when such a batch exists and no `VERIFIED` flush record of the line has a `verified_at` strictly after that batch's `mixed_at`; otherwise the line reads `NONE`. The timestamp comparison is strict — a flush verified at the very instant of the last medicated mix does not clear the line.

When a line must be cleared, an `Operator` records a flush with a payload naming the `line_id`, the `flush_material_ingredient_id`, and the `quantity_tons` run through the line. The material must be flush-approved — an ingredient whose `is_flush_material` is false is refused with `ERR_FLUSH_MATERIAL_INVALID` — and the quantity must be at least half a ton: exactly 0.5 tons passes, anything less is rejected with `ERR_FLUSH_QUANTITY_BELOW_MIN`. The record stamps `recorded_by_employee_id` from the caller's `X-User-ID` and starts in `RECORDED`, with `verified_by_employee_id` and `verified_at` still null.

Verification is the second key of the two-key rule. An `Operator` verifies a `RECORDED` flush, moving it to the terminal `VERIFIED` — but the caller's `X-User-ID` must differ from `recorded_by_employee_id`, and a self-verification is rejected with `ERR_SOD_VIOLATION`. A successful verification stamps `verified_by_employee_id` from the caller and `verified_at` from the logical clock, and when that `verified_at` falls after the last medicated mix the line's `contamination` recomputes to `NONE`; the flush's `version` increments. A `QualityTech` may instead reject a `RECORDED` flush, moving it to the terminal `REJECTED` and incrementing its `version`. Flush listings accept optional `line_id`, `flush_material_ingredient_id`, and `status` filters.

The discipline pays out at the sequencing gate of §3.6: a non-medicated batch may follow medicated work on the same line only after this record-then-verify cycle has produced a `VERIFIED` flush newer than the last medicated `mixed_at`. Recording alone is never enough — an unverified flush leaves the line `MEDICATED`, and the batch start still draws `ERR_FLUSH_REQUIRED`.

### 3.8. Quality Sampling and Release Gating

Quality control begins at the mixer. A `QualityTech` collects a sample against a batch that is `MIXED` or `HOLD` at sampling time, naming the `batch_id` and a `sample_type` of `COMPOSITE` or `RETAIN`. A `RETAIN` sample additionally requires a `retain_expiry_date` strictly after the current clock — a missing or non-future date is rejected with `ERR_RETAIN_EXPIRY_INVALID` — while a `COMPOSITE` sample carries none. Every sample starts with `result` `PENDING`, its assay fields null. Sample listings accept optional `batch_id`, `sample_type`, and `result` filters.

When the lab returns, the `QualityTech` enters the assay: `protein_pct_actual`, `crude_fiber_pct_actual`, and `moisture_pct` — the moisture figure must be at least zero and below one hundred. These are as-fed numbers; the system corrects them to a dry-matter basis before judging. `protein_dry_matter` is the as-fed protein divided by one minus the moisture fraction (the `moisture_pct` value divided by one hundred), rounded half-up to two decimals; `fiber_dry_matter` is computed identically from `crude_fiber_pct_actual`. The outcome is computed, not chosen: the sample passes exactly when `protein_dry_matter` is at least the order's `pinned_min_protein_pct` and `fiber_dry_matter` is at most the order's `pinned_max_fiber_pct`, and equality passes on both sides. The dry-matter basis alone gates release; the as-fed figures stand as reporting context only, so the same assay can read one way as-fed and the opposite way on dry matter whenever moisture is above zero. Entering a result stamps `result_by_employee_id` from the caller's `X-User-ID` and increments the sample's `version`.

A passing sample moves `PENDING` → `PASS` and unlocks the batch: a `QualityTech` may then release the batch `MIXED` → `RELEASED`, an act refused with `ERR_QUALITY_NOT_PASSED` unless a `PASS` sample exists for it. A failing sample moves `PENDING` → `FAIL` and detonates a cascade in the same request: the batch moves `MIXED` → `HOLD` provided it is still `MIXED` when the result is entered — a batch that has since left `MIXED` (for example, one already `RELEASED`) stays where it is — the order's `blocked` recomputes to true, and every delivery trip of the order in `PLANNED` or `LOADING` is cancelled with its compartment allocations released, regardless of the batch's current state — cancelled trips are not auto-revived if the batch later recovers. The batch's `version` increments only when it actually moves to `HOLD`.

From `HOLD`, two roads diverge. An `Operator` may rework the batch, moving `HOLD` → `BATCHING`; the order's `blocked` recomputes — false again once no batch of the order remains in `HOLD` — and during the rework window the operator may void `RECORDED` weighments and record replacements before mixing again. A failed batch may be re-sampled with a fresh `PENDING` sample after rework. Alternatively, a `QualityTech` may reject the batch, moving `HOLD` → `REJECTED`, a terminal state, with the order's `blocked` recomputed likewise. Rejection does not rewind the physical world: a `REJECTED` batch keeps its weighments `RECORDED`, and neither bin inventory nor contract consumption is auto-restored — the product exists, as scrap.

### 3.9. Fleet Dispatch and Order Fulfilment

The mill's fleet is registered by the `MillManager`. A truck is created with a unique `plate_no` (duplicates draw `ERR_DUPLICATE_CODE`), a `cargo_class_capability` of `STANDARD_ONLY` or `MEDICATED_CAPABLE`, and its `compartments`, fixed at creation: between one and eight entries, each pairing a `compartment_seq` unique within the truck with a positive `capacity_tons`. A new truck is `AVAILABLE`. Retirement is one-way — `AVAILABLE` → `RETIRED` — and is refused with `ERR_INVALID_STATE` while any trip of the truck is `PLANNED`, `LOADING`, or `IN_TRANSIT`.

A `MillManager` dispatches a delivery trip with a payload naming the `truck_id` and `order_id`, a half-open window from `planned_departure_at` to `planned_return_at` (the return strictly after the departure), and `compartment_allocations`: entries of `compartment_seq`, `tons`, and a `cargo_class` of `STANDARD` or `MEDICATED`. The truck must be `AVAILABLE` — a `RETIRED` truck refuses dispatch with `ERR_INVALID_STATE`, checked before the order's state. The order must be `IN_PRODUCTION` or `COMPLETED` — anything earlier surfaces `ERR_INVALID_STATE` — and must not be `blocked` (`ERR_ORDER_BLOCKED`). Every allocation's `cargo_class` must equal the order's medicated flag (`ERR_CARGO_CLASS_MIX`), and medicated cargo requires a `MEDICATED_CAPABLE` truck (`ERR_TRUCK_NOT_MEDICATED_CAPABLE`). Each allocation's `tons` must fit its compartment's `capacity_tons`, with equality passing (`ERR_COMPARTMENT_CAPACITY_EXCEEDED`) — a check always evaluated before the order-level rule that the sum of `total_tons` across the order's non-`CANCELLED` trips must not exceed the order's `tons`, again with equality passing (`ERR_ORDER_TONNAGE_OVERALLOCATED`). The trip's `total_tons` is the sum of its allocations. An allocation naming a `compartment_seq` the truck does not carry is rejected with `ERR_INVALID_REQUEST`. The allocation list may legitimately be empty — producing a zero-tonnage trip — and the same `compartment_seq` may appear more than once, each entry checked against the compartment's capacity individually. Trucks are shared resources under a pure half-open window rule with no buffer: trips of the same truck in `PLANNED`, `LOADING`, or `IN_TRANSIT` occupy their windows — `DELIVERED` and `CANCELLED` trips free the truck — and a new trip conflicts when its departure falls before an existing trip's return while that trip's departure falls before the new trip's return. Back-to-back dispatch is expressly allowed: a new departure exactly at an existing return does not conflict. Violations are rejected with `ERR_TRUCK_WINDOW_CONFLICT`. A new trip starts `PLANNED`. Trip listings accept optional `truck_id`, `order_id`, and `status` filters, and a `Customer` caller sees only the trips of their own orders.

The trip then walks a simple chain. Loading moves `PLANNED` → `LOADING` and requires the order to be `COMPLETED` (`ERR_INVALID_STATE`) and not `blocked` (`ERR_ORDER_BLOCKED`). Departure moves `LOADING` → `IN_TRANSIT`. Delivery moves `IN_TRANSIT` → `DELIVERED`, and it is delivery that can finish the order: when every trip of the order is then terminal, at least one is `DELIVERED`, and the sum of `total_tons` over `DELIVERED` trips exactly equals the order's `tons`, the order bubbles `COMPLETED` → `DELIVERED` and its credit exposure is released, per §3.5. Cancellation moves `PLANNED` → `CANCELLED` at the manager's hand; a `LOADING` trip, by contrast, can be cancelled only by the order-blocked cascade of §3.8 — a manual cancel attempt on a `LOADING` trip is refused with `ERR_INVALID_STATE`. Every trip transition increments the trip's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an ingredient, a contract, a bin, a customer, an employee, a formula, an order, a batch, a weighment, a sample, a flush record, a line, a truck, or a trip — return `201 Created`. Operations that modify an existing resource in place, including all state-transition and action endpoints, return `200 OK`. The full request and response semantics of each endpoint live in the narratives of Section 3; this table is the summary catalogue.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; triggers the contract expiry sweep | MillManager |
| POST | `/api/ingredients` | Create an ingredient | MillManager |
| GET | `/api/ingredients/{id}` | Get an ingredient by id | MillManager, Nutritionist, Operator, QualityTech, Customer |
| POST | `/api/ingredients/{id}/discontinue` | Discontinue an ingredient; cascades to bins and formulas | MillManager |
| POST | `/api/price-ticks` | Record an ingredient spot price tick (append-only; late `effective_from` allowed) | MillManager |
| GET | `/api/ingredients/{id}/price-ticks` | List price ticks of an ingredient | MillManager, Nutritionist, Operator, QualityTech, Customer |
| POST | `/api/contracts` | Create a forward purchase contract | MillManager |
| GET | `/api/contracts` | List contracts with optional filters | MillManager, Nutritionist, Operator, QualityTech, Customer |
| GET | `/api/contracts/{id}` | Get a contract by id | MillManager, Nutritionist, Operator, QualityTech, Customer |
| POST | `/api/contracts/{id}/cancel` | Cancel an `OPEN` contract | MillManager |
| POST | `/api/bins` | Create a bin (starts `EMPTY`, unassigned) | MillManager |
| GET | `/api/bins` | List bins with optional filters | MillManager, Nutritionist, Operator, QualityTech |
| GET | `/api/bins/{id}` | Get a bin by id | MillManager, Nutritionist, Operator, QualityTech |
| POST | `/api/bins/{id}/assign` | Assign an ingredient to an empty bin | MillManager |
| POST | `/api/bins/{id}/replenish` | Add stock to a bin | MillManager |
| POST | `/api/bins/{id}/unblock` | Manager override: `BLOCKED` to `READY` | MillManager |
| POST | `/api/customers` | Create a customer | MillManager |
| GET | `/api/customers/{id}` | Get a customer by id (`Customer` role: own record only) | MillManager, Customer |
| PATCH | `/api/customers/{id}` | Adjust credit limit and/or medicated permit; OCC on the customer version | MillManager |
| POST | `/api/customers/{id}/set-status` | Suspend or reinstate a customer | MillManager |
| POST | `/api/employees` | Create an employee (operator / quality tech identity) | MillManager |
| GET | `/api/employees/{id}` | Get an employee by id | MillManager |
| POST | `/api/formulas` | Create a formula with nutrient constraints (`DRAFT`, empty lines) | Nutritionist |
| GET | `/api/formulas/{id}` | Get a formula by id | MillManager, Nutritionist, Operator, QualityTech, Customer |
| POST | `/api/formulas/{id}/optimize` | Run least-cost greedy allocation; OCC on the formula version | Nutritionist |
| POST | `/api/formulas/{id}/activate` | Activate a `DRAFT` formula | Nutritionist |
| POST | `/api/formulas/{id}/retire` | Retire a `DRAFT` or `ACTIVE` formula | Nutritionist, MillManager |
| POST | `/api/orders` | Create a customer order in `QUOTED` with provisional price; OCC on the customer version | Customer |
| GET | `/api/orders` | List orders (`Customer` role: own orders only) | MillManager, Customer |
| GET | `/api/orders/{id}` | Get an order by id (`Customer` role: own orders only) | MillManager, Customer |
| POST | `/api/orders/{id}/confirm` | Confirm a quote; pins the formula snapshot | Customer |
| POST | `/api/orders/{id}/begin-revision` | Begin an order revision; releases credit exposure | Customer |
| POST | `/api/orders/{id}/commit-revision` | Commit a revision with new tonnage; reprices and re-pins | Customer |
| POST | `/api/orders/{id}/cancel` | Cancel an order | Customer, MillManager |
| POST | `/api/orders/{id}/complete` | Complete an in-production order; computes the final price | MillManager |
| POST | `/api/batches` | Schedule a batch on a line for an order | MillManager |
| GET | `/api/batches` | List batches with optional filters | MillManager, Nutritionist, Operator, QualityTech |
| GET | `/api/batches/{id}` | Get a batch by id | MillManager, Nutritionist, Operator, QualityTech |
| POST | `/api/batches/{id}/start` | Start a planned batch; sequencing and flush gate | Operator |
| POST | `/api/batches/{id}/weighments` | Record a scale weighment against a batch | Operator |
| GET | `/api/weighments` | List weighments with optional filters | MillManager, Nutritionist, Operator, QualityTech |
| GET | `/api/weighments/{id}` | Get a weighment by id | MillManager, Nutritionist, Operator, QualityTech |
| POST | `/api/weighments/{id}/void` | Void a weighment; restores bin stock and contract tonnage | Operator |
| POST | `/api/batches/{id}/mix` | Mix a batch; per-line tolerance gate | Operator |
| POST | `/api/batches/{id}/release` | Release a mixed batch with a passing sample | QualityTech |
| POST | `/api/batches/{id}/rework` | Rework a held batch back to batching | Operator |
| POST | `/api/batches/{id}/reject` | Reject a held batch (terminal; consumption not restored) | QualityTech |
| POST | `/api/batches/{id}/cancel` | Cancel a planned batch; frees the line window | MillManager |
| POST | `/api/samples` | Collect a quality sample on a mixed or held batch | QualityTech |
| GET | `/api/samples` | List samples with optional filters | MillManager, QualityTech |
| GET | `/api/samples/{id}` | Get a sample by id | MillManager, QualityTech |
| POST | `/api/samples/{id}/result` | Enter the lab assay; computes the dry-matter outcome | QualityTech |
| POST | `/api/flush-records` | Record a line flush | Operator |
| GET | `/api/flush-records` | List flush records with optional filters | MillManager, Operator, QualityTech |
| GET | `/api/flush-records/{id}` | Get a flush record by id | MillManager, Operator, QualityTech |
| POST | `/api/flush-records/{id}/verify` | Verify a recorded flush (verifier must differ from recorder) | Operator |
| POST | `/api/flush-records/{id}/reject` | Reject a recorded flush | QualityTech |
| POST | `/api/lines` | Create a production line | MillManager |
| GET | `/api/lines/{id}` | Get a line by id (includes derived contamination) | MillManager, Nutritionist, Operator, QualityTech |
| POST | `/api/lines/{id}/set-status` | Move a line between `ACTIVE` and `DOWN` | MillManager |
| POST | `/api/trucks` | Create a truck with fixed compartments | MillManager |
| GET | `/api/trucks/{id}` | Get a truck by id | MillManager, Nutritionist, Operator, QualityTech, Customer |
| POST | `/api/trucks/{id}/set-status` | Retire an available truck | MillManager |
| POST | `/api/trips` | Schedule a delivery trip with compartment allocations | MillManager |
| GET | `/api/trips` | List trips (`Customer` role: own orders' trips only) | MillManager, Customer |
| GET | `/api/trips/{id}` | Get a trip by id (`Customer` role: own orders' trips only) | MillManager, Customer |
| POST | `/api/trips/{id}/load` | Begin loading a planned trip | MillManager |
| POST | `/api/trips/{id}/depart` | Depart a loading trip | MillManager |
| POST | `/api/trips/{id}/deliver` | Deliver an in-transit trip; may complete the order's delivery | MillManager |
| POST | `/api/trips/{id}/cancel` | Cancel a planned trip | MillManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of Sections 2 and 3; this table is the summary catalogue.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CUSTOMER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FORMULA_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_BLOCKED` | 409 Conflict |
| `ERR_BIN_BLOCKED` | 409 Conflict |
| `ERR_FLUSH_REQUIRED` | 409 Conflict |
| `ERR_MEDICATED_PERMIT_REQUIRED` | 422 Unprocessable Content |
| `ERR_SOD_VIOLATION` | 422 Unprocessable Content |
| `ERR_QUALITY_NOT_PASSED` | 409 Conflict |
| `ERR_CARGO_CLASS_MIX` | 422 Unprocessable Content |
| `ERR_TRUCK_NOT_MEDICATED_CAPABLE` | 422 Unprocessable Content |
| `ERR_LINE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRUCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RETAIN_EXPIRY_INVALID` | 422 Unprocessable Content |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_BIN_NOT_EMPTY` | 409 Conflict |
| `ERR_BIN_CAPACITY_EXCEEDED` | 422 Unprocessable Content |
| `ERR_BIN_INGREDIENT_MISMATCH` | 422 Unprocessable Content |
| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Content |
| `ERR_INGREDIENT_NOT_IN_FORMULA` | 422 Unprocessable Content |
| `ERR_WEIGHMENT_OUT_OF_TOLERANCE` | 422 Unprocessable Content |
| `ERR_COMPARTMENT_CAPACITY_EXCEEDED` | 422 Unprocessable Content |
| `ERR_ORDER_TONNAGE_OVERALLOCATED` | 422 Unprocessable Content |
| `ERR_ORDER_TONS_MISMATCH` | 422 Unprocessable Content |
| `ERR_FORMULA_NOT_FEASIBLE` | 422 Unprocessable Content |
| `ERR_NUTRIENT_CONSTRAINT_VIOLATION` | 422 Unprocessable Content |
| `ERR_INGREDIENT_NOT_ACTIVE` | 422 Unprocessable Content |
| `ERR_FORMULA_IN_USE` | 409 Conflict |
| `ERR_FLUSH_MATERIAL_INVALID` | 422 Unprocessable Content |
| `ERR_FLUSH_QUANTITY_BELOW_MIN` | 422 Unprocessable Content |
| `ERR_QUOTE_STALE` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_INTERNAL` | 500 Internal Server Error |

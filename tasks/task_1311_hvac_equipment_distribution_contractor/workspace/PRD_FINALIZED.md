# HVAC Equipment Distribution & Contractor Program API — Product Requirements Document

## 1. Introduction

A wholesale HVAC equipment distributor operates a dealer network whose economics extend well beyond a simple order book. Contractors earn tier status from delivered purchase volume, accrue co-op advertising funds against merchandise they buy, commit to seasonal pre-buy programs in exchange for discounts and deposit terms, and compete for constrained equipment inventory during peak cooling and heating seasons. Alongside these commercial mechanics sit hard regulatory and program obligations: installed systems must be registered for warranty within a fixed window, parts claims must be adjudicated under a coverage schedule that depends on registration timeliness, refrigerant cylinders moving through the channel must be tracked by weight with heel-shortfall enforcement, and federal tax-credit or utility-rebate dossiers must be qualified against certified AHRI system ratings.

This document specifies the API through which distributor staff and dealer users run that entire operating loop. It covers the equipment catalog and AHRI-rated system matchups; contractor accounts, tiering, and co-op accrual; pre-buy programs and allocation pools; order capture with a dual fulfillment-and-billing state model; warranty registration and parts-claim adjudication; refrigerant cylinder tracking and compliance standing; rebate dossier qualification; and technical training credits. All requirements below are normative for implementers: where a rule is stated, it is stated precisely, and where the document is silent, no behavior is implied.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/api/v1` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled as follows: `DistributorAdmin`, `ContractorUser`, `WarrantyProcessor`, `ComplianceOfficer`, and `TrainingCoordinator`. A request whose headers are missing, or whose declared role is not one of these five values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the targeted endpoint or action is rejected with `ERR_UNAUTHORIZED` (HTTP 403) — for example, a `ContractorUser` attempting to qualify a rebate dossier.

The identity carried in `X-User-ID` differs by role:

- When `X-User-Role` is `ContractorUser`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks on any resource that references a `Contractor` compare the resource's contractor foreign-key field to `X-User-ID`.
- When `X-User-Role` is `DistributorAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `WarrantyProcessor`, `X-User-ID` is likewise an opaque operator identifier with no entity comparison.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier with no entity comparison.
- When `X-User-Role` is `TrainingCoordinator`, `X-User-ID` is an opaque operator identifier with no entity comparison.

Two segregation-of-duties boundaries are load-bearing. A `WarrantyProcessor` adjudicates parts claims — beginning review, approving, denying, and requesting more information — but may never pay one; payment of an approved claim is reserved to `DistributorAdmin`. Symmetrically, a `ComplianceOfficer` qualifies or rejects rebate dossiers but may never pay one; payout is reserved to `DistributorAdmin`. On order billing, invoicing events are reserved to `DistributorAdmin` while payment events are reserved to `ContractorUser`. Any crossing of these boundaries surfaces `ERR_UNAUTHORIZED`.

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

List endpoints accept two query parameters. The `limit` parameter bounds the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

List responses carry four pagination fields in the response envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Lazy State Sweeps

All deadline, window, expiry, and season logic in the system reads a single server-maintained **logical clock** — never the host wall clock. At server startup the logical clock reads 2026-08-01T00:00:00Z, and the server must not silently fall back to wall-clock time under any circumstance. A `DistributorAdmin` may advance or set the clock through an admin-only test-driving capability that accepts a target instant `to_iso8601` and answers with the resulting `current_utc`.

Advancing the clock does not, by itself, mutate any resource. Instead, time-driven transitions are applied **lazily**: the sweeps triggered by the new clock position — warranty-registration lapse, rebate-dossier expiry, cylinder overdue detection, training-credit expiry, and the recomputation of pre-buy program windows and allocation-pool seasons — are deferred to the next read of, or transition upon, the affected resource. A registration fetched after its deadline lapses at that fetch; a cylinder fetched after its thirtieth day out flips to overdue at that fetch. Implementers must therefore evaluate these sweeps on every read and every transition, not on the clock-setting call itself.

### 2.5. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at its initial value and incrementing by exactly 1 on every mutation of the resource.

"Mutation" is read broadly: client-driven edits, state transitions, and server-side recomputation of derived fields all refresh `updated_at` and increment `version`. When a single request cascades into several entities — a delivery recomputing a contractor's purchase totals, a registration lapse denying open claims — each affected entity is independently mutated, with its own `updated_at` refresh and `version` increment.

One entity is deliberately exempt. A `RefrigerantEvent` is an append-only ledger entry and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. Clients must not expect those fields on ledger entries.

### 2.6. Optimistic Concurrency Control

Exactly two write endpoints are guarded by optimistic concurrency control, and each names its guard field explicitly:

- Updating a draft order — the endpoint `PATCH /orders/{id}` — requires the request body to carry `expected_order_version`, the value of the order's `version` the client last observed. If that value no longer matches the order's current `version` — because the draft has legitimately changed since the client read it, for example a line was added or the pre-buy program was swapped — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a draft state it has not observed.
- Patching a rebate dossier's document checklist — the endpoint `PATCH /rebate-submissions/{id}` — requires `expected_rebate_version`. Because the checklist is cumulative, a writer working from an outdated checklist snapshot would silently drop documents another writer already attached; a mismatch with the dossier's current `version` is therefore rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. Requests to unguarded endpoints must not include one, and the stale-version check described above does not apply to them.

### 2.7. Units and Precision: Money, Weights, and Efficiency Ratings

Monetary amounts are represented as **integer cents** throughout the API — every field whose name ends in `_cents` is an integer count of cents, and all monetary arithmetic is performed in integer cents. Where a computation produces a fractional cent, the value is rounded **half-up to the nearest whole cent**, and the point at which rounding occurs is pinned per calculation: pre-buy line discounts are rounded per line before any summation (computing the discount on a summed total is forbidden); tier-discounted unit prices are rounded per unit price; an order's pre-buy deposit is rounded once, on the summed order total; co-op accrual is rounded once at the aggregate level, never per line; warranty coverage amounts are rounded per coverage component; and a rebate's thirty-percent cost ceiling is rounded before the lesser-of comparison that uses it.

Refrigerant weights — `tare_weight_lbs`, `full_weight_lbs`, `current_weight_lbs`, `weight_delta_lbs`, and the `returned_weight_lbs` supplied on a return — are decimal pounds carried to exactly two decimal places, and weight comparisons are exact at that precision. Efficiency ratings (`seer2`, `eer2`, `hspf2`) are decimal values carried to one decimal place; the classification thresholds that compare against them are inclusive and involve no rounding. Program fractions such as `deposit_pct` and `discount_pct`, and the co-op accrual rate, are decimal fractions (a value of 0.20 means twenty percent). All timestamps are ISO 8601 UTC.

### 2.8. Validation Pipeline and Error Priority

Every request is evaluated against a fixed validation pipeline, and **the first failing check determines the error returned**. The evaluation order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared; failures yield `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the endpoint and the specific action attempted; failures yield `ERR_UNAUTHORIZED` (403).
3. **Path existence** — path identifiers are resolved strictly left to right; the first non-existent identifier yields `ERR_NOT_FOUND` (404).
4. **Body reference existence** — foreign-key identifiers referenced in the payload (`contractor_id`, `order_id`, `ahri_rating_id`, and so on) must exist; failures yield `ERR_REFERENCE_NOT_FOUND` (404).
5. **From-state legality** — the target resource must be in a legal from-state for the requested transition; failures yield `ERR_INVALID_STATE` (409).
6. **Terminal lockdown** — no transition may leave a terminal state (`DELIVERED`, `CANCELLED`, `PAID`, `REJECTED`, `EXPIRED`, `RECLAIMED`, `VOID`); failures yield `ERR_ALREADY_TERMINAL` (409). The from-state check runs before this one, so a request failing both reports `ERR_INVALID_STATE`.
7. **Refrigerant compliance gate** — `ERR_COMPLIANCE_HOLD` (422); see §2.10.
8. **Cylinder return weight sanity** — `ERR_INVALID_CYLINDER_WEIGHT` (422); see §3.7.
9. **Window validity** — `ERR_WINDOW_EXPIRED` (422) for pre-buy order windows, ship-by enforcement, registration deadlines, and rebate payout deadlines.
10. **Pre-buy window overlap** — `ERR_WINDOW_OVERLAP` (422); see §3.3.
11. **Instructor session conflict** — `ERR_INSTRUCTOR_CONFLICT` (422); see §3.9.
12. **Allocation-pool aggregate capacity** — `ERR_POOL_CAPACITY_EXCEEDED` (422); see §3.3.
13. **AHRI pairing sanity** — `ERR_INVALID_SYSTEM_PAIRING` (422); see §3.2.
14. **Uniqueness** — `ERR_DUPLICATE` (409); see the per-resource unique fields in §3.
15. **Order-line shape** — `ERR_INVALID_LINE` (422); see §3.4.
16. **Referenced-model orderability** — `ERR_MODEL_NOT_ORDERABLE` (422); see §3.2 and §3.4.
17. **Rebate dossier consistency** — `ERR_REBATE_MISMATCH` (422); see §3.8.
18. **Parts-claim anchoring** — `ERR_WARRANTY_NOT_ACTIVE` (422); see §3.6.
19. **Credit hold** — `ERR_CREDIT_HOLD` (422); see §3.1 and §3.4.
20. **Co-op accrual sufficiency** — `ERR_ACCRUAL_EXCEEDED` (422); see §3.9.
21. **Stale-version OCC** — `ERR_STALE_VERSION` (412); see §2.6.
22. **Structural payload validity** — required fields present and well-typed, unknown fields rejected; failures yield `ERR_INVALID_REQUEST` (400). This check is deliberately last: a request that is structurally malformed but also trips a business rule surfaces the business error first.

The left-to-right rule of stage 3 deserves emphasis for nested paths. When an endpoint path contains more than one identifier — an order and one of its lines, a cylinder and its event ledger — the system validates the identifiers sequentially from the left and rejects with `ERR_NOT_FOUND` at the first identifier that does not resolve, without examining identifiers further right.

### 2.9. Derived Fields and Cascading Consistency

Many fields in this system are **server-derived**; where a request supplies a value for a derived field, the supplied value is ignored. A contractor's `tier` is derived from delivered purchase volume, an order line's `unit_price_cents` is resolved from pricing terms, a rating's `efficiency_class` and `tax_credit_eligible` fall out of its certified figures, and every entity's status fields advance only through the transitions described in §3. Derived values are recomputed at the moments §3 specifies — on the transition that triggers them, or lazily on read where §2.4 says so — and each recomputation that changes a resource is a mutation in the sense of §2.5.

Cascades cross entity boundaries and are part of the contract. Delivering an order recomputes the contractor's year-to-date purchases, final co-op accrual, and tier; lapsing or voiding a warranty registration denies its open parts claims; a cylinder passing thirty days out in the field forces its holder's compliance standing down; completing a course grants one credit per attendee and refreshes each attendee's balance. Where §3 describes a cascade, every step of it is mandatory, and every entity the cascade touches shows the mutation in its own `version` and `updated_at`.

### 2.10. Compliance Standing as a Cross-Cutting Gate

Each contractor carries a `compliance_standing` of `GOOD`, `WATCH`, or `HOLD`, driven entirely by refrigerant handling discipline (the mechanics live in §3.7). The standing starts at `GOOD`. A first heel-shortfall violation within a rolling twelve-month window moves the contractor to `WATCH`; a second heel-shortfall violation inside that window, or any cylinder held overdue beyond thirty days, moves the contractor to `HOLD`. The count behind these rules is `heel_violation_count_12m`, the number of heel-shortfall events recorded against the contractor in the trailing twelve months of the logical clock.

`HOLD` is an operational gate, not a label. A contractor in `HOLD` cannot submit orders and cannot be issued refrigerant cylinders; both attempts are rejected with `ERR_COMPLIANCE_HOLD` (422). Because stage 7 of the validation pipeline runs before the credit-hold and window checks, a contractor under `HOLD` learns of the compliance failure first, even when their account has other problems. Standing recovers only through the refrigerant workflows of §3.7 — there is no administrative reset.

## 3. Business Logic & Workflows

### 3.1. Dealer Accounts and the Tier Program

A `DistributorAdmin` onboards a dealer by creating a `Contractor` with a `company_name` and a `license_number` — the state HVAC license, unique across all contractors, so a duplicate submission is rejected with `ERR_DUPLICATE` (409). The creation payload may also carry `credit_hold` (defaulting to false) and a `status` of `ACTIVE` or `SUSPENDED` (defaulting to `ACTIVE`). The dealer's `tier` is not negotiable input: any value supplied at creation is ignored, and the account begins at `STANDARD` with `ytd_purchase_cents` at zero, both co-op accrual balances at zero, `training_credit_balance_hours` at zero, `compliance_standing` at `GOOD`, and `heel_violation_count_12m` at zero.

The **tier program** rewards delivered volume. A contractor's `ytd_purchase_cents` accumulates the merchandise totals of their orders that have reached `DELIVERED` — each order contributing its `total_cents`, that is, its merchandise valued net of all discounts (the sum of its lines' `line_total_cents`), never undiscounted list prices — counting only orders whose `submitted_at` falls inside the current calendar year of the logical clock; cancelled and in-flight orders contribute nothing. Whenever an order is delivered the year-to-date figure is recomputed and the tier re-evaluated against inclusive thresholds: at least $50,000 (5,000,000 cents) earns `SILVER`, at least $200,000 (20,000,000 cents) earns `GOLD`, and at least $500,000 (50,000,000 cents) earns `PLATINUM`; below $50,000 the contractor remains `STANDARD`. Tier determines the discount applied to list prices when order lines are priced for non-pre-buy orders: `STANDARD` receives no discount, `SILVER` three percent, `GOLD` five percent, and `PLATINUM` seven percent, with the discounted unit price rounded half-up to the nearest cent. Contractor creation runs this evaluation too, which is how a fresh account lands on `STANDARD`.

A `DistributorAdmin` may later update the mutable fields `credit_hold` and `status`; each such update increments the contractor's `version`. Setting `credit_hold` to true blocks that dealer from submitting orders — the submission is rejected with `ERR_CREDIT_HOLD` (422) — and a `SUSPENDED` dealer is likewise barred from submission and from receiving cylinders. The contractor list endpoint supports the filters `status` and `tier` alongside pagination, and fetching a single contractor triggers the lazy training-credit sweep of §2.4, refreshing `training_credit_balance_hours` as expired credits fall out.

### 3.2. The Equipment Catalog and AHRI-Rated System Matchups

The catalog is a flat list of `EquipmentModel` records maintained by `DistributorAdmin`. Each model carries a unique `model_number` (duplicates rejected with `ERR_DUPLICATE`), an `equipment_type` of `CONDENSER`, `HEAT_PUMP`, `COIL`, `FURNACE`, or `AIR_HANDLER`, a `refrigerant_type` of `R410A`, `R454B`, `R32`, or `NONE` (the latter for furnaces and coils that ship dry), a nominal `capacity_btuh`, a `family_code` such as RES_AC_3T that ties the model into allocation pools and pre-buy programs, a current `list_price_cents`, and a `status`. Model status is `ACTIVE` by default; `DISCONTINUED` models may not be referenced by new order lines, and `ALLOCATED_ONLY` models may be ordered only while an open allocation pool covers their family. An order line referencing a discontinued model, or an allocated-only model with no covering pool, is rejected with `ERR_MODEL_NOT_ORDERABLE` (422). The catalog list endpoint filters by `equipment_type`, `family_code`, and `status`.

On top of raw models sit **AHRI system ratings**: certified combinations that the industry rates as a matched system. Registering one requires an `ahri_reference_number` (unique, duplicates rejected with `ERR_DUPLICATE`), an `outdoor_unit_id` referencing a model whose type is `CONDENSER` or `HEAT_PUMP`, an `indoor_unit_id` referencing a `COIL` or `AIR_HANDLER`, and optionally a `furnace_id` which, when present, must reference a `FURNACE`. The outdoor and indoor units must also be refrigerant-compatible: their `refrigerant_type` values must match, unless the indoor unit ships dry with a type of `NONE`. A registration violating any of these component-type or compatibility rules is rejected with `ERR_INVALID_SYSTEM_PAIRING` (422). The rating records certified `seer2` and `eer2` figures to one decimal, plus an `hspf2` to one decimal that may be omitted for straight-cool systems. A rating's `status` begins `ACTIVE`; a `WITHDRAWN` rating may no longer be quoted on new order lines, and attempting to do so is likewise `ERR_MODEL_NOT_ORDERABLE`. The same rejection protects the registry itself: a rating registration whose referenced component models are `DISCONTINUED` is refused with `ERR_MODEL_NOT_ORDERABLE` (422).

From the certified figures the server derives two things at creation — and re-derives whenever a referenced equipment model becomes `DISCONTINUED`. First, `efficiency_class`: a rating with `seer2` at least 17.0 and `eer2` at least 12.0 is `PREMIUM`; otherwise one with `seer2` at least 15.2 and `eer2` at least 11.7 is `HIGH`; anything else is `STANDARD`. The boundaries are inclusive — a rating of exactly 17.0 SEER2 with `eer2` at least 12.0 classifies `PREMIUM`. Second, `tax_credit_eligible` is true precisely when the class is `PREMIUM`, or when the class is `HIGH` and a non-null `hspf2` of at least 8.1 is on record. Both derived fields drive the rebate qualification math of §3.8. The ratings list supports reverse-lookup filters on `outdoor_unit_id`, `indoor_unit_id`, `furnace_id`, and `efficiency_class`, so a user can find every certified system built from a given component.

### 3.3. Seasonal Pre-Buy Programs and Allocation Pools

Distributors shape demand with **pre-buy programs**. A `DistributorAdmin` creates a `PreBuyProgram` with a `name` (such as SPRING-2026-RES-AC), the `family_code` it prices, an order window from `window_start` (inclusive) to `window_end` (exclusive), a `ship_by_date` by which every order taken under the program must ship, a `deposit_pct` greater than zero and at most 0.5, and a `discount_pct` greater than zero and at most 0.20. Two programs for the same `family_code` may not have overlapping windows under half-open semantics: windows overlap precisely when each starts before the other ends, while windows that merely touch at an endpoint are permitted; a conflicting creation is rejected with `ERR_WINDOW_OVERLAP` (422). A program's `status` is derived from the clock: `SCHEDULED` before its window opens, `OPEN` inside the window, `CLOSED` once the window has passed or a `DistributorAdmin` closes it early, and `SETTLED` once the `ship_by_date` has passed with all of its orders in terminal fulfillment states. Closing a program early leaves any backordered pre-buy orders referencing it in place until the pool-close rules of this section and §3.4 apply.

**Allocation pools** ration scarce families through peak season. A pool is created with a `family_code`, a half-open season from `season_start` (inclusive) to `season_end` (exclusive), and a `total_qty` of units available for reservation; `reserved_qty` and `committed_qty` start at zero. A pool's `status` is `OPEN` while the logical clock sits inside its season and it has not been manually closed, and `CLOSED` otherwise. Overlapping pools for the same family are allowed, but an anti-over-subscription rule caps the aggregate: at every instant, the sum of `total_qty` across pools covering that instant for one family may not exceed twice the largest single pool's `total_qty` for that family, and a creation breaching the cap is rejected with `ERR_POOL_CAPACITY_EXCEEDED` (422). Creating a pool also triggers the re-reservation sweep of §3.4, giving backordered orders on the newly covered family another chance. Closing a pool releases nothing that was committed, but any backordered order whose shortage traces to that pool reverts from `BACKORDERED` to `SUBMITTED` with its partial reservations released, as §3.4 details. Both resources expose list endpoints filtered by `family_code` and `status`.

### 3.4. Order Capture, Pricing, and Allocation

A `ContractorUser` builds an order in two steps: create the order shell with a `contractor_id` and an optional `prebuy_program_id`, then add lines to it. While the order remains `DRAFT` the contractor may patch it — switching the `prebuy_program_id`, for instance — subject to the optimistic-concurrency rule of §2.6 via `expected_order_version`, and each successful patch increments the order's `version`.

Each **order line** names either an `ahri_rating_id` (a matched system) or an `equipment_model_id` (a part-only line) — exactly one of the two, never both, never neither — plus a `quantity` of at least one; violations are rejected with `ERR_INVALID_LINE` (422). Lines may only be added while the order is `DRAFT`. Pricing is entirely server-side: the line's `unit_price_cents` is resolved from the contractor's tier discount — or, when the order carries a `prebuy_program_id`, from pre-buy terms, under which the unit price is simply the model's `list_price_cents` with no tier discount applied — and any client-supplied price is ignored. The line's `line_discount_cents` and `line_total_cents` follow the pre-buy rounding discipline whenever a program applies: the line's gross (unit price times quantity) is multiplied by the program's `discount_pct` and rounded half-up to the cent **per line**, and the line total is the gross minus that discount. Every line addition recomputes the order's `subtotal_cents` (the sum of line grosses), `discount_cents` (the sum of line discounts), and `total_cents` (subtotal minus discount), and increments the order's `version`; computing discounts against a summed order total instead of per line is forbidden.

**Submission** turns a draft into a commercial commitment and is gated by a series of checks, evaluated in the pipeline order of §2.8: the order must be `DRAFT` with at least one line; the contractor must be `ACTIVE`; a contractor in `HOLD` standing is rejected first with `ERR_COMPLIANCE_HOLD`; a pre-buy order submitted outside its program's window — before `window_start` or at or after `window_end`, or while the program is not `OPEN` — is rejected with `ERR_WINDOW_EXPIRED`; and a `credit_hold` on the account yields `ERR_CREDIT_HOLD`. On acceptance the server stamps `submitted_at` from the logical clock, re-resolves every line's pricing under the order's terms, recomputes the order totals, and — for pre-buy orders — derives `deposit_due_cents` as the order total multiplied by the program's `deposit_pct`, rounded half-up to the cent once on the summed total; non-pre-buy orders keep a deposit of zero.

Submission also **reserves allocation**. For each line, the server looks for a pool whose `family_code` matches the component's family, whose `status` is `OPEN`, and whose season covers the logical clock; among candidates it picks the pool whose `season_start` is most recent, breaking ties by earliest `created_at`. A line with no eligible pool is unrestricted and reserves nothing. Where a pool is selected, the check is all-or-nothing per line: if the pool's available quantity — its `total_qty` minus `reserved_qty` minus `committed_qty` — is at least the line's quantity (equality suffices), the line's quantity is added to `reserved_qty`; otherwise nothing is reserved for that line and the order is marked for backorder. When every line is either unrestricted or fully reserved, the order advances `SUBMITTED` → `ALLOCATED` and each reservation converts, the quantity leaving `reserved_qty` and entering `committed_qty`. When any line cannot be fully reserved, the order falls to `BACKORDERED` with only its fully-reservable lines holding reservations.

Backorder is not a dead end. When availability reopens for the short family — a pool is created or its `total_qty` grows — a re-reservation sweep re-evaluates `BACKORDERED` orders in priority order: `PLATINUM` contractors first, then `GOLD`, then `SILVER`, then `STANDARD`; within a tier, earlier `submitted_at` wins; remaining ties break by earlier order `created_at`. An order whose lines are now all fully reservable moves `BACKORDERED` → `ALLOCATED`, each short line's quantity moving from reserved into committed. Conversely, if the pool whose shortage caused the backorder closes, the order reverts `BACKORDERED` → `SUBMITTED` and the partial reservations it held are released; the cycle `BACKORDERED` → `SUBMITTED` → `BACKORDERED` is reachable across successive pool open-and-close epochs. Every reservation change is reflected in the contractor's provisional co-op accrual (§3.9), which counts lines on `SUBMITTED`, `BACKORDERED`, `ALLOCATED`, `SHIPPED`, and `DELIVERED` orders alike — a $100,000 submitted order raises the provisional figure by $2,000 while moving the final figure by nothing.

Once `ALLOCATED`, a `DistributorAdmin` ships the order. For pre-buy orders the logical clock must be at or before the program's `ship_by_date`, failing which the ship is rejected with `ERR_WINDOW_EXPIRED`; non-pre-buy orders ship without a window check. Shipping moves the order to `SHIPPED` and changes no pool quantities — the units were already committed. Delivery moves `SHIPPED` → `DELIVERED` and fires a three-step cascade on the contractor: first `ytd_purchase_cents` and the final co-op accrual are recomputed from delivered lines; then the tier is re-evaluated from the new year-to-date figure, and on a tier change the period caps of the contractor's pending co-op claims re-derive; finally the provisional accrual is recomputed with this order's lines now part of the delivered population.

Cancellation is available to the `ContractorUser` while the order is `DRAFT`, `SUBMITTED`, or `BACKORDERED` — and, beyond `DRAFT`, only while the billing dimension is still `UNBILLED` or `DEPOSIT_INVOICED`. Cancelling releases every pool reservation the order holds, decrementing `reserved_qty` by the reserved quantities and `committed_qty` by any quantities committed to it, so that the pool's reserved-plus-committed conservation is preserved across a submit-then-cancel pair; the provisional accrual is recomputed as well. Cancelling an order whose deposit has been invoiced forfeits that deposit, moving the billing dimension to `FORFEITED` (§3.5). An order in `ALLOCATED`, `SHIPPED`, or any later state cannot be cancelled — such attempts are rejected with `ERR_INVALID_STATE` (409) — and `DELIVERED` and `CANCELLED` are terminal, with further transitions rejected under the terminal lockdown. Orders and lines are browsable through list endpoints filtered by `contractor_id`, `prebuy_program_id`, `status`, `ahri_rating_id`, `equipment_model_id`, or `order_id` as appropriate to each listing.

### 3.5. Order Billing, Deposits, and Forfeiture

The billing dimension evolves **in parallel** with fulfillment, on the same order resource, through billing events carrying an `event_type`. Invoicing events — `INVOICE_DEPOSIT` and `INVOICE_FINAL` — are reserved to `DistributorAdmin`; payment events — `PAY_DEPOSIT` and `PAY_FINAL` — are reserved to `ContractorUser`, and any crossing of that split is `ERR_UNAUTHORIZED`. Every accepted billing event advances `billing_status` and increments the order's `version`.

Two billing tracks exist. A **pre-buy order** begins `UNBILLED`; a deposit invoice moves it to `DEPOSIT_INVOICED`, which is permitted only while fulfillment is `SUBMITTED`, `BACKORDERED`, or `ALLOCATED` and only for orders carrying a `prebuy_program_id`, and the invoice amount is the order's `deposit_due_cents`. The contractor's deposit payment moves `DEPOSIT_INVOICED` → `DEPOSIT_PAID`. Once the order is `SHIPPED`, a final invoice moves `DEPOSIT_PAID` → `FINAL_INVOICED` for the order's `total_cents` minus the deposit already due. A **non-pre-buy order** bills once: from `UNBILLED` straight to `FINAL_INVOICED` once the order is `SHIPPED`, for the full `total_cents`. Either track concludes when the contractor's final payment moves `FINAL_INVOICED` → `PAID`.

`FORFEITED` is the billing dimension's other terminal state and is independent of fulfillment. It arrives two ways: the logical clock passes a pre-buy program's `ship_by_date` while the order — deposit invoiced — has not yet reached `SHIPPED` or `DELIVERED`; or the order is cancelled while `DEPOSIT_INVOICED`. In both cases the distributor retains the deposit. Forfeiture does not itself cancel the order: the fulfillment dimension is untouched, and the order may still be cancelled afterwards with its reservations released as §3.4 describes. An event that does not correspond to a legal transition from the current `billing_status` is rejected with `ERR_INVALID_STATE`, and `PAID` and `FORFEITED` accept no further events under the terminal lockdown.

### 3.6. Warranty Registration and Parts Claims

When a unit is installed, the installing `ContractorUser` creates a `WarrantyRegistration` with the unit's `serial_number` (unique across all registrations, duplicates rejected with `ERR_DUPLICATE`), the installed `equipment_model_id`, the `contractor_id`, the `order_id` of the order the unit shipped on — which must already be `DELIVERED` at creation — and the `install_date`, which may not lie in the future relative to the logical clock. The server derives `registration_deadline` as exactly sixty days after `install_date`, and the record begins in `PENDING_REGISTRATION` with `registered_at` empty and `extended_coverage_years` at its base value of 5.

**Registration** by the contractor moves the record to `REGISTERED` provided the logical clock is at or before `registration_deadline` — the boundary is inclusive, so registering exactly at the deadline succeeds — while a registration attempted after the deadline is rejected with `ERR_WINDOW_EXPIRED` (422). A successful registration stamps `registered_at` from the clock and extends `extended_coverage_years` to 10. Should the clock pass the deadline with the record still pending, it lapses automatically to `LAPSED` at the next read or transition (the lazy sweep of §2.4), and the lapse cascades: every parts claim anchored to the registration that sits in `SUBMITTED` or `MORE_INFO_REQUESTED` is auto-denied, each such claim's `total_award_cents` remaining 0 and its revision loop terminating. A `DistributorAdmin` may also void a registration in `PENDING_REGISTRATION` or `REGISTERED`, moving it to `VOID` with the same claim-denial cascade. `REGISTERED`, `LAPSED`, and `VOID` are terminal.

Against a registration, the contractor files a **parts claim** naming the `warranty_registration_id`, a `contractor_id` that must equal the registration's own contractor (a mismatch is rejected with `ERR_WARRANTY_NOT_ACTIVE`, 422), the `failure_date` (no later than the logical clock), and the claimed `part_cost_cents` and `labor_cost_cents`. The server mints a human-readable `claim_number` of the form `PC-` followed by eight hexadecimal characters, and the claim begins `SUBMITTED` with `covered_part_cents`, `covered_labor_cents`, `total_award_cents`, and `revision_count` all at zero.

Adjudication belongs to the `WarrantyProcessor`, acting through a decision endpoint carrying an `action`. Beginning review (`BEGIN_REVIEW`) moves `SUBMITTED` → `UNDER_REVIEW` and carries a cross-entity gate: the anchored registration must be `REGISTERED` at that moment, failing which the decision is rejected with `ERR_WARRANTY_NOT_ACTIVE`. From `UNDER_REVIEW` the processor has three exits. Denial (`DENY`) moves the claim to `DENIED` with its award staying 0. Requesting information (`REQUEST_INFO`) moves it to `MORE_INFO_REQUESTED`, from which the contractor resubmits — optionally supplying corrected `part_cost_cents` and `labor_cost_cents` — returning the claim to `SUBMITTED` and incrementing `revision_count`; at most three such revision cycles are permitted, and a resubmission attempted beyond the third is rejected with `ERR_REVISION_LIMIT` (422). Approval (`APPROVE`) finalizes coverage under a fixed schedule.

The coverage schedule works as follows. The unit's age in whole years is the number of 365.25-day years fully elapsed between `install_date` and `failure_date`, rounded down. The coverage horizon is the registration's `extended_coverage_years` — ten when the unit was registered on time, five otherwise. A failure occurring at an age strictly beyond the horizon is awarded nothing: both covered amounts are 0. Within the horizon, parts are covered at one hundred percent of `part_cost_cents` when the age is at most one year, seventy-five percent when the age is at most five years, and fifty percent thereafter, rounded half-up to the cent. Labor is covered at fifty percent of `labor_cost_cents` only when the age is at most one year **and** the registration was completed on time (its `registered_at` is set); otherwise labor is not covered. The two covered amounts are rounded half-up per component and summed into `total_award_cents`, which is fixed at the moment of approval. Payment (`PAY`) is a `DistributorAdmin` action, moving `APPROVED` → `PAID` — the segregation-of-duties boundary of §2.1 — and `PAID` and `DENIED` are terminal. Claims are listed with filters on `warranty_registration_id`, `contractor_id`, and `status`; registrations on `contractor_id`, `order_id`, `equipment_model_id`, and `status`.

### 3.7. Refrigerant Cylinders and the Heel-Compliance Regime

Refrigerant moves through the channel in tracked cylinders, each registered by a `DistributorAdmin` with a unique `cylinder_tag` (duplicates rejected with `ERR_DUPLICATE`), a `refrigerant_type` of `R410A`, `R454B`, or `R32`, and the `tare_weight_lbs` and `full_weight_lbs` to two decimal places. A freshly registered cylinder is `IN_STOCK` with `current_weight_lbs` initialized to its full weight, no holder, and `issued_at` empty.

**Issuing** a cylinder to a contractor takes a `contractor_id` and is gated twice: the target contractor must be `ACTIVE`, and must not be in `HOLD` standing — the safety gate rejects the issue with `ERR_COMPLIANCE_HOLD` (422). Issuing moves `IN_STOCK` → `ISSUED`, sets `holder_contractor_id` to the contractor, stamps `issued_at` from the clock, and appends a ledger entry of kind `ISSUE` with a zero weight delta. Thirty days is the outer limit of a lawful hold: once the logical clock passes `issued_at` by more than thirty days, the cylinder flips to `RETURN_PENDING` at the next read or transition, and the overdue condition alone forces the holder's `compliance_standing` to `HOLD` — which in turn makes that contractor's subsequent order submissions fail the compliance gate of §2.10.

**Returning** a cylinder supplies the gross `returned_weight_lbs`, which must be at least the `tare_weight_lbs` and at most the `full_weight_lbs`; a weight outside that band is rejected with `ERR_INVALID_CYLINDER_WEIGHT` (422). A valid return from either `ISSUED` or `RETURN_PENDING` moves the cylinder to `RETURNED`, appends a `RETURN` ledger entry whose delta is the difference between the returned weight and the previously recorded `current_weight_lbs`, and sets `current_weight_lbs` to the returned weight. The return also runs the **heel check**: a cylinder returned below ninety percent of its full weight — a heel shortfall exceeding ten percent of the charge — appends a further `ADJUSTMENT` entry whose `note` carries the marker text `HEEL_SHORTFALL`, and increments the holder's `heel_violation_count_12m`, counted over a rolling twelve-month window of the logical clock. The standing then recomputes: two or more heel violations inside the window force `HOLD`; exactly one forces `WATCH`. When an overdue cylinder is finally returned and no other violations remain, the contractor's standing eases from its overdue-forced `HOLD` down to `WATCH` — never directly back to `GOOD`. Either way the cylinder's `holder_contractor_id` and `issued_at` are cleared on return.

From `RETURNED`, two paths exist. **Refilling** appends an `ADJUSTMENT` entry restoring the cylinder to exactly its `full_weight_lbs` and moves it back to `IN_STOCK`, completing the issue-return-refill cycle. **Reclaiming** appends a `RECLAIM` entry whose delta brings the cylinder down to its `tare_weight_lbs`, sets `current_weight_lbs` to the tare weight, and moves the cylinder to `RECLAIMED`, which is terminal.

Every cylinder exposes its **append-only event ledger**. Entries carry a `cylinder_id`, an `event_type` of `ISSUE`, `RECOVERY_IN`, `RETURN`, `RECLAIM`, or `ADJUSTMENT`, a signed two-decimal `weight_delta_lbs` (negative when gas leaves the cylinder), a system-stamped `recorded_at`, and an optional free-text `note`. The cylinder's `current_weight_lbs` is always derivable as its full weight plus the sum of all deltas replayed in `recorded_at` order, with ties broken by `created_at`; as ledger entries, events carry no `updated_at` or `version` (§2.5). Cylinders are listed with filters on `holder_contractor_id` and `status`.

### 3.8. Rebate and Tax-Credit Dossiers

High-efficiency installs earn incentives, and the contractor assembles a **dossier** to claim them. Creation — by the `ContractorUser` — names the `contractor_id`, the `order_id` of the equipment order, the `ahri_rating_id` of the installed system, a `program_type` of `FEDERAL_TAX_CREDIT` or `UTILITY_REBATE`, the `homeowner_name`, the `install_address`, the `install_date`, and optionally an initial `docs` checklist. Consistency is enforced at both creation and submission: the referenced rating must appear on a line of the referenced order, and the `install_date` must be no earlier than the order's `submitted_at` and no later than the logical clock; mismatches are rejected with `ERR_REBATE_MISMATCH` (422). The checklist admits exactly four document kinds — `AHRI_CERTIFICATE`, `INVOICE`, `LOAD_CALC`, and `PERMIT` — and the dossier opens in `DRAFT` with `qualified_amount_cents` at zero and `submitted_at` and `decision_deadline` empty.

While `DRAFT` or `SUBMITTED`, the contractor attaches documents by patching the dossier with a `docs` list. The patch is guarded by the optimistic-concurrency rule of §2.6 via `expected_rebate_version`, and the checklist is **cumulative**: the payload list is merged into the stored checklist as a union, so documents accumulate and none are ever removed by a patch. Completeness is re-evaluated on every patch: the moment all four kinds are present on a `SUBMITTED` dossier, it advances `SUBMITTED` → `DOCS_COMPLETE` within that same request.

**Submission** is gated on the outside world. The referenced order must be `DELIVERED`; the referenced rating must be `ACTIVE`; for the `FEDERAL_TAX_CREDIT` lane the rating must be `tax_credit_eligible`; and the checklist must already contain at least `AHRI_CERTIFICATE` and `INVOICE`. A dossier failing the order- or rating-state gates is rejected with `ERR_INVALID_STATE` (409); one failing the consistency or document requirements with `ERR_REBATE_MISMATCH`. Acceptance stamps `submitted_at` and sets `decision_deadline` forty-five days later. A dossier submitted with all four documents already attached flows `DRAFT` → `SUBMITTED` → `DOCS_COMPLETE` inside the same request.

Adjudication belongs to the `ComplianceOfficer` through a decision `action`. Qualifying (`QUALIFY`) moves `DOCS_COMPLETE` → `QUALIFIED` and fixes the incentive under a pinned four-step evaluation. First, the installed cost is the sum of `line_total_cents` across the order's lines referencing this rating — already net of any line discounts. Second, the efficiency tier amount is read from the rating's class: $2,000 (200,000 cents) for `PREMIUM`, $1,000 (100,000 cents) for `HIGH`, and nothing for `STANDARD`. Third, the program lane applies its cap: a `FEDERAL_TAX_CREDIT` pays the lesser of the tier amount and thirty percent of the installed cost — the thirty-percent term rounded half-up to whole cents before the comparison — while a `UTILITY_REBATE` pays the flat tier amount but nothing when the class is `STANDARD`. Fourth, a federal submission whose rating is not `tax_credit_eligible` qualifies for zero regardless. The result is stored in `qualified_amount_cents`. Rejection (`REJECT`) moves the dossier to `REJECTED` instead.

Payment (`PAY`) is reserved to `DistributorAdmin` and must occur at or before the `decision_deadline`; a payout attempted past the deadline is rejected with `ERR_WINDOW_EXPIRED` (422). A `QUALIFIED` dossier whose deadline passes unpaid transitions to `EXPIRED` at the next read or transition — its `qualified_amount_cents` remains on record but is no longer payable. `PAID`, `REJECTED`, and `EXPIRED` are terminal. Dossiers are listed with filters on `contractor_id`, `order_id`, `ahri_rating_id`, and `status`.

### 3.9. Training Credits and Co-op Advertising Claims

The distributor invests in dealer capability through **training courses**, scheduled by a `TrainingCoordinator` with a unique `course_code` (duplicates rejected with `ERR_DUPLICATE`), a `title`, the `credit_hours` granted on completion, a `session_start` and `session_end`, the `instructor_name`, and a `max_seats` cap. Instructor scheduling is strict: sessions for the same instructor occupy closed intervals — they conflict when they share so much as a day — and even disjoint sessions require a full day of buffer, so the earlier session's `session_end` plus one day must fall strictly before the other session's `session_start` (and vice versa); violations are rejected with `ERR_INSTRUCTOR_CONFLICT` (422). A course may be cancelled while `SCHEDULED` by a `DistributorAdmin` or the coordinator, granting no credits.

**Completing** a course — allowed once the logical clock has reached `session_end` — takes the `attendee_contractor_ids` list, whose length may not exceed `max_seats`; an oversized roster is rejected with `ERR_SEAT_CAPACITY` (422). Completion moves `SCHEDULED` → `COMPLETED` and grants each attendee a `TrainingCredit` carrying the course's `credit_hours`, an `earned_at` stamped from the clock, and an `expires_at` exactly twenty-four months later. Each credit begins `ACTIVE` with `consumed_hours` at zero; consumption draws credits down first-in-first-out — the candidate set is credits still `ACTIVE` or `PARTIALLY_CONSUMED` whose `expires_at` lies ahead of the clock, ranked by earliest `earned_at` with ties broken by earliest `created_at` — moving them through `PARTIALLY_CONSUMED` to `CONSUMED`. Expiry is lazy: a credit whose `expires_at` the clock has reached or passed is treated as `EXPIRED` at the next read or balance computation, regardless of its stored status. A contractor's `training_credit_balance_hours` is the sum, over their non-expired and not-fully-consumed credits, of each credit's `credit_hours` minus its `consumed_hours`. Credits are listed with filters on `contractor_id`, `course_id`, and `status`; courses on `status` and `instructor_name`.

**Co-op advertising** closes the commercial loop. Recall from §3.4 that two accrual figures ride on each contractor, both at a two-percent rate applied to merchandise totals — here as in §3.1, the merchandise total of the covered lines is their `line_total_cents` summed, net of all line discounts rather than undiscounted list prices — and rounded half-up to the cent once, at the aggregate level rather than per line. The **provisional** figure, `coop_accrual_provisional_cents`, covers lines on orders in `SUBMITTED`, `BACKORDERED`, `ALLOCATED`, `SHIPPED`, and `DELIVERED` — cancelled orders excluded — and is recomputed at submit, backorder, cancellation, and delivery. The **final** figure, `coop_accrual_final_cents`, is the spendable balance: two percent of delivered lines only, minus the `approved_amount_cents` of the contractor's `PAID` claims.

Against that balance a `ContractorUser` files a `CoopClaim` naming the `contractor_id`, an `invoice_reference` unique per contractor (a repeat under the same contractor is rejected with `ERR_DUPLICATE`), a `period` label of the form YYYY-H1 or YYYY-H2, and the claimed `spend_cents`. The claim opens `SUBMITTED` with `eligible_amount_cents` at zero and `approved_amount_cents` empty. A `DistributorAdmin` then works the claim through a decision `action`. Verification (`VERIFY`) computes `eligible_amount_cents` as the smallest of three quantities: the claimed `spend_cents`, the contractor's current `coop_accrual_final_cents` at verification time, and the remaining cap for the claim's period — a period's cap being fifty percent of the final accrual for that period's window, reduced by amounts already claimed against the period. Approval (`APPROVE`) records an `approved_amount_cents` — empty until this point — that may not exceed the `eligible_amount_cents`, lest the decision be rejected with `ERR_ACCRUAL_EXCEEDED` (422). Disputing (`DISPUTE`) hands the claim back: the contractor resubmits (`RESUBMIT`) with a corrected `spend_cents`, the claim returns to `SUBMITTED`, and `eligible_amount_cents` resets to zero until re-verified — the loop `SUBMITTED` → `VERIFIED` → `DISPUTED` → `SUBMITTED` may repeat. Rejection (`REJECT`) is terminal, as is `PAID`: payment debits the contractor's `coop_accrual_final_cents` by the approved amount, which is what makes the final accrual a spendable balance. Because tier changes re-derive the period caps of pending claims (§3.4), a delivery that moves a contractor's tier can change what a still-open claim is worth before verification. Claims are listed with filters on `contractor_id`, `status`, and `period`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — state transitions, billing events, patches, line additions — return `200 OK`, as do all reads. The table below is a navigational summary; request payloads, response bodies, and side effects are specified by the narratives of §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/_clock/set_current_utc` | Set the logical clock (test-driving) | DistributorAdmin |
| POST | `/api/v1/contractors` | Create a dealer/contractor account | DistributorAdmin |
| GET | `/api/v1/contractors/{id}` | Fetch one contractor | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer, TrainingCoordinator |
| GET | `/api/v1/contractors` | List contractors with filters and pagination | DistributorAdmin, WarrantyProcessor, ComplianceOfficer, TrainingCoordinator |
| PATCH | `/api/v1/contractors/{id}` | Update mutable contractor fields (`credit_hold`, `status`) | DistributorAdmin |
| POST | `/api/v1/equipment-models` | Create an equipment model | DistributorAdmin |
| GET | `/api/v1/equipment-models/{id}` | Fetch one equipment model | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer, TrainingCoordinator |
| GET | `/api/v1/equipment-models` | List equipment models | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer, TrainingCoordinator |
| POST | `/api/v1/ahri-ratings` | Register an AHRI-rated system pairing | DistributorAdmin |
| GET | `/api/v1/ahri-ratings/{id}` | Fetch one AHRI rating | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer, TrainingCoordinator |
| GET | `/api/v1/ahri-ratings` | List AHRI ratings with component and class filters | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer, TrainingCoordinator |
| POST | `/api/v1/prebuy-programs` | Create a seasonal pre-buy program | DistributorAdmin |
| GET | `/api/v1/prebuy-programs/{id}` | Fetch one pre-buy program | DistributorAdmin, ContractorUser |
| GET | `/api/v1/prebuy-programs` | List pre-buy programs | DistributorAdmin, ContractorUser |
| POST | `/api/v1/prebuy-programs/{id}/close` | Manually close a program window early | DistributorAdmin |
| POST | `/api/v1/allocation-pools` | Create a peak-season allocation pool | DistributorAdmin |
| GET | `/api/v1/allocation-pools/{id}` | Fetch one allocation pool | DistributorAdmin, ContractorUser |
| GET | `/api/v1/allocation-pools` | List allocation pools | DistributorAdmin, ContractorUser |
| POST | `/api/v1/allocation-pools/{id}/close` | Close a pool (committed quantities remain) | DistributorAdmin |
| POST | `/api/v1/orders` | Create a draft order | ContractorUser |
| GET | `/api/v1/orders/{id}` | Fetch one order | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer |
| GET | `/api/v1/orders` | List orders with filters | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer |
| PATCH | `/api/v1/orders/{id}` | Edit a draft order (OCC-guarded) | ContractorUser |
| POST | `/api/v1/orders/{id}/lines` | Add a line to a draft order | ContractorUser |
| GET | `/api/v1/orders/{id}/lines` | List the lines of an order | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer |
| GET | `/api/v1/order-lines/{id}` | Fetch one order line | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer |
| GET | `/api/v1/order-lines` | List order lines across orders | DistributorAdmin, ContractorUser, WarrantyProcessor, ComplianceOfficer |
| POST | `/api/v1/orders/{id}/submit` | Submit a draft order | ContractorUser |
| POST | `/api/v1/orders/{id}/cancel` | Cancel an order in DRAFT/SUBMITTED/BACKORDERED | ContractorUser |
| POST | `/api/v1/orders/{id}/ship` | Ship an allocated order | DistributorAdmin |
| POST | `/api/v1/orders/{id}/deliver` | Deliver a shipped order | DistributorAdmin |
| POST | `/api/v1/orders/{id}/billing-events` | Advance the billing dimension | DistributorAdmin, ContractorUser |
| POST | `/api/v1/warranty-registrations` | Create a warranty registration for an installed unit | ContractorUser |
| GET | `/api/v1/warranty-registrations/{id}` | Fetch one registration | DistributorAdmin, ContractorUser, WarrantyProcessor |
| GET | `/api/v1/warranty-registrations` | List registrations with filters | DistributorAdmin, ContractorUser, WarrantyProcessor |
| POST | `/api/v1/warranty-registrations/{id}/register` | Register the unit (deadline-gated, inclusive) | ContractorUser |
| POST | `/api/v1/warranty-registrations/{id}/void` | Void a registration; denies open claims | DistributorAdmin |
| POST | `/api/v1/parts-claims` | File a parts/labor warranty claim | ContractorUser |
| GET | `/api/v1/parts-claims/{id}` | Fetch one parts claim | DistributorAdmin, ContractorUser, WarrantyProcessor |
| GET | `/api/v1/parts-claims` | List parts claims with filters | DistributorAdmin, ContractorUser, WarrantyProcessor |
| POST | `/api/v1/parts-claims/{id}/decision` | Adjudicate: BEGIN_REVIEW, APPROVE, DENY, REQUEST_INFO, PAY | WarrantyProcessor, DistributorAdmin |
| POST | `/api/v1/parts-claims/{id}/resubmit` | Resubmit a MORE_INFO_REQUESTED claim (max 3 cycles) | ContractorUser |
| POST | `/api/v1/refrigerant-cylinders` | Register a tracked refrigerant cylinder | DistributorAdmin |
| GET | `/api/v1/refrigerant-cylinders/{id}` | Fetch one cylinder | DistributorAdmin, ContractorUser, ComplianceOfficer |
| GET | `/api/v1/refrigerant-cylinders` | List cylinders with filters | DistributorAdmin, ContractorUser, ComplianceOfficer |
| POST | `/api/v1/refrigerant-cylinders/{id}/issue` | Issue a cylinder to a contractor | DistributorAdmin |
| POST | `/api/v1/refrigerant-cylinders/{id}/return` | Return a cylinder with gross weight | DistributorAdmin |
| POST | `/api/v1/refrigerant-cylinders/{id}/reclaim` | Reclaim residual gas (terminal) | DistributorAdmin |
| POST | `/api/v1/refrigerant-cylinders/{id}/refill` | Refill a returned cylinder to full | DistributorAdmin |
| GET | `/api/v1/refrigerant-cylinders/{id}/events` | Fetch the cylinder's append-only event ledger | DistributorAdmin, ContractorUser, ComplianceOfficer |
| POST | `/api/v1/rebate-submissions` | Create a rebate/tax-credit dossier in DRAFT | ContractorUser |
| GET | `/api/v1/rebate-submissions/{id}` | Fetch one dossier | DistributorAdmin, ContractorUser, ComplianceOfficer |
| GET | `/api/v1/rebate-submissions` | List dossiers with filters | DistributorAdmin, ContractorUser, ComplianceOfficer |
| PATCH | `/api/v1/rebate-submissions/{id}` | Attach documents (OCC-guarded) | ContractorUser |
| POST | `/api/v1/rebate-submissions/{id}/submit` | Submit the dossier | ContractorUser |
| POST | `/api/v1/rebate-submissions/{id}/decision` | QUALIFY/REJECT or PAY a dossier | ComplianceOfficer, DistributorAdmin |
| POST | `/api/v1/training-courses` | Schedule a training course | TrainingCoordinator |
| GET | `/api/v1/training-courses/{id}` | Fetch one course | DistributorAdmin, ContractorUser, TrainingCoordinator |
| GET | `/api/v1/training-courses` | List courses | DistributorAdmin, ContractorUser, TrainingCoordinator |
| PATCH | `/api/v1/training-courses/{id}` | Cancel a scheduled course via action | DistributorAdmin, TrainingCoordinator |
| POST | `/api/v1/training-courses/{id}/complete` | Complete a course and grant credits | TrainingCoordinator |
| GET | `/api/v1/training-credits/{id}` | Fetch one training credit | DistributorAdmin, ContractorUser, TrainingCoordinator |
| GET | `/api/v1/training-credits` | List training credits with filters | DistributorAdmin, ContractorUser, TrainingCoordinator |
| POST | `/api/v1/coop-claims` | Submit a co-op advertising claim | ContractorUser |
| GET | `/api/v1/coop-claims/{id}` | Fetch one co-op claim | DistributorAdmin, ContractorUser |
| GET | `/api/v1/coop-claims` | List co-op claims with filters | DistributorAdmin, ContractorUser |
| POST | `/api/v1/coop-claims/{id}/decision` | VERIFY/APPROVE/REJECT/DISPUTE/PAY or RESUBMIT | DistributorAdmin, ContractorUser |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_COMPLIANCE_HOLD` | 422 Unprocessable Entity |
| `ERR_INVALID_CYLINDER_WEIGHT` | 422 Unprocessable Entity |
| `ERR_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_INSTRUCTOR_CONFLICT` | 422 Unprocessable Entity |
| `ERR_POOL_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_SYSTEM_PAIRING` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_LINE` | 422 Unprocessable Entity |
| `ERR_MODEL_NOT_ORDERABLE` | 422 Unprocessable Entity |
| `ERR_REBATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WARRANTY_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 422 Unprocessable Entity |
| `ERR_ACCRUAL_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REVISION_LIMIT` | 422 Unprocessable Entity |
| `ERR_SEAT_CAPACITY` | 422 Unprocessable Entity |

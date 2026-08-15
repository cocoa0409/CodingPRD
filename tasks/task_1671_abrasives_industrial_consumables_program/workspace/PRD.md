# Abrasives & Industrial Consumables Program API — Product Requirements Document

## 1. Introduction

Industrial distributors running vendor-managed inventory programs for abrasives live and die by details that never appear on an invoice line: whether a bonded cut-off wheel is still inside its shelf life, whether the wheel's rated speed exceeds the grinder's spindle speed, whether a plant's consumption of flap discs has quietly drifted above the engineered standard, and whether a price negotiated eighteen months ago still holds on a release shipping next quarter. When any one of these is handled informally, the distributor absorbs the cost — in scrapped product, in safety liability, or in margin leaked through stale pricing.

This document specifies the Abrasives & Industrial Consumables Program API, the system of record for a distributor's managed-consumables program. The API governs the full operating loop: cataloguing abrasive products with their safety ratings and shelf-life policies, registering the customer machines those products run on, receiving inventory lots and rotating them by expiry, recording per-operation media consumption against engineered standards, administering pricing contracts with price-hold and escalation clauses, executing blanket purchase orders through scheduled releases, documenting product trials and converting the successful ones into new standards, and filing compliant disposal manifests for used media.

Two design commitments shape everything that follows. First, the program is run against a **logical clock** rather than wall-clock time, so that shelf-life expiry, contract expiry, and date-sensitive pricing are deterministic and testable. Second, the pricing model is deliberately dual: every commitment carries a **provisional** price evaluated at a scheduled future date, and every shipment is **final-billed** at the date it actually ships — the two diverge whenever a price-hold or escalation boundary falls between the scheduled and actual ship dates. All resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and cross-cutting mechanisms that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly three roles, spelled as follows:

- `ProgramAdmin` — the distributor's program administrator. This role owns the product catalog (registration and discontinuation), contract activation, amendment and termination, blanket-order confirmation, standard retirement, trial conversion and rejection decisions, and the logical clock.
- `AccountManager` — the distributor's account and field-operations role. This role registers machines, receives inventory lots, drafts contracts and blanket orders, schedules, picks, ships and cancels releases, accepts substitutions, records usage audits, creates usage standards, and documents trials.
- `EHSOfficer` — the customer-side environmental, health and safety officer. This role quarantines and reinstates machines, submits trial results and safety documentation, and files waste-disposal manifests.

All three roles may call any read (GET) endpoint. Any attempt to invoke an operation outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For all three roles — `ProgramAdmin`, `AccountManager`, and `EHSOfficer` — the value of `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity. The server may record it (for example, as `results_submitted_by_user_id` on a trial when results are submitted) but never compares it to any entity's `id`. Its one load-bearing use is the segregation-of-duties check on trial conversion described in §3.8.

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

### 2.3. Pagination and List Filtering

Endpoints returning collections are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Every list response sorts by `created_at` ascending, and every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

List endpoints additionally accept resource-specific filter query parameters, each of which narrows the collection to exact matches on the named field. Products may be filtered by `status`, `product_form`, or `replacement_product_id`. Lots may be filtered by `product_id` or `status`. Usage standards may be filtered by `machine_id`, `product_id`, or `status`. Usage records may be filtered by `machine_id`, `product_id`, or `lot_id`. Contract lines may be filtered by `contract_id` or `product_id`. Blanket orders may be filtered by `contract_id`, `product_id`, or `status`. Releases may be filtered by `blanket_order_id` or `status`. Trials may be filtered by `machine_id`, `product_id`, `incumbent_product_id`, `converted_standard_id`, or `status`. Disposal records may be filtered by `product_id` or `lot_id`.

### 2.4. The Logical Clock and Time-Driven Sweeps

The program keeps its own logical UTC clock. At server startup the clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time; the only way time advances is through an administrative capability, restricted to `ProgramAdmin`, that sets the clock to a supplied `to_iso8601` instant. The response of that capability reports the resulting `current_utc` together with two sweep counters, `lots_expired` and `contracts_expired`.

Advancing the clock runs two monotonic sweeps, atomically with the clock set. First, every inventory lot still `AVAILABLE` whose `expiry_date` is strictly earlier than the new clock date transitions to `EXPIRED`; a lot whose expiry date equals the new date stays `AVAILABLE`. Second, every contract still `ACTIVE` whose `term_end` is strictly earlier than the new clock date transitions to `EXPIRED`; a contract whose `term_end` equals the new date stays `ACTIVE`. Sweeps never reverse: once a lot is `EXPIRED` or a contract is `EXPIRED`, moving the clock does not restore it.

All date-sensitive behavior in the program — shelf-life expiry, contract expiry, price evaluation, usage-date futurity — is evaluated against this logical clock, and all calendar-date comparisons happen at ISO date (day) granularity unless a field is explicitly a timestamp.

### 2.5. Common Resource Properties

Primary resources — products, machines, lots, standards, contracts, contract lines, blanket orders, releases, and trials — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by one on every mutation; it is the anchor for optimistic concurrency control (§2.7).

Two resources are deliberately **append-only events**: a usage record and a disposal record each carry only `id` and `created_at`. Both `updated_at` and `version` are absent on these two resources, because they are never modified after acceptance.

### 2.6. Numeric Precision, Money, and Rounding Discipline

Three precision regimes coexist, and each is stated where its values are produced:

- **Money** is integer cents everywhere — prices, provisional values, and billed totals are whole-cent integers. Wherever a monetary computation produces a fraction (escalated prices, tier discounts), it is rounded **half-up** to whole cents at exactly the steps named in §3.5 and §3.7; rounding anywhere else produces different cents and is a defect.
- **Consumption rates and variances** (`standard_qty_per_part`, `actual_qty_per_part`, `variance_pct`) are decimal numbers carried to **4 decimal places, rounded half-up**.
- **Weights** (`gross_weight_kg` and the monthly hazard-mass aggregation) are decimal numbers carried to **2 decimal places, rounded half-up**.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and only these two accept a version field:

1. **Release creation under a blanket order.** The request must carry `expected_blanket_order_version`, holding the order's `version` as the client last observed it. If the value does not match the blanket order's current `version` — because the order has been mutated since the client read it, legitimately changing its committed pool — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is persisted.
2. **Contract amendment.** The request must carry `expected_contract_version`, holding the contract's `version` as the client last observed it. A mismatch with the contract's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from re-pricing a contract it has not re-read.

No other endpoint takes a version field. Both version checks are evaluated early in the validation pipeline, before any state preconditions (§2.8).

### 2.8. Validation Order of Evaluation

When several checks could fail on the same request, the API evaluates them in a single fixed priority order and reports the **first** failure. The order is:

1. **User context** — presence and well-formedness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization** — the caller's role must be listed for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`, 403).
3. **Request shape** — required fields present, enum values valid, numeric positivity (quantities at least 1, parts produced at least 1, weight greater than 0, speeds at least 1, `escalation_pct` at least 0), window shape (a trial's `scheduled_end` on or after its `scheduled_start`; a standard's `effective_to` strictly after its `effective_from` when present), a `BONDED` product carrying `shelf_life_months`, a rejection carrying `rejection_reason`, a discontinuation carrying `replacement_product_id` (`ERR_INVALID_REQUEST`, 400).
4. **Existence** — path identifiers are resolved first; then body foreign keys in the order they appear in the payload (machine, product, lot, contract, blanket order). A lot supplied with a usage or disposal payload must belong to the referenced product; a lot–product mismatch is `ERR_INVALID_REQUEST` (400), not a missing resource. Missing ids yield `ERR_NOT_FOUND` (404).
5. **Optimistic concurrency** — the two version checks of §2.7 (`ERR_STALE_VERSION`, 412). These are deliberately evaluated *before* state preconditions, so a stale write surfaces as a version conflict rather than being masked by a state error.
6. **State preconditions** — first the path resource's own state (release picks only from `SCHEDULED`, ships only from `PICKED`, cancels only from a non-terminal state; contract amendment only on `ACTIVE`; blanket confirmation only on `DRAFT`; trial conversion or rejection only from `EVALUATION`; discontinuation only on an `ACTIVE` product; quarantine only on an `ACTIVE` machine; reinstatement only on a `QUARANTINED` machine — violations yield `ERR_INVALID_STATE_TRANSITION`, 409), then cross-entity states (`ERR_MACHINE_NOT_ACTIVE`, `ERR_LOT_NOT_AVAILABLE`, `ERR_CONTRACT_NOT_ACTIVE`, all 409).
7. **Safety and compliance gates** — speed rating before guard requirement on usage and trials; on disposals, disposal method first, then manifest fields, then the regulator-report threshold (§3.9).
8. **Business constraints** — substitution and discontinuation gates, contract-line existence, standard-window overlap, trial-window conflict, replacement validity, segregation of duties, and covering-standard existence, in the per-endpoint sub-order given in §3.
9. **Temporal rules** — release ship dates inside the contract term; usage dates not in the future.
10. **Capacity and quota rules** — release quantity against the order's remaining pool; usage quantity against the lot's on-hand quantity; pick-pool eligibility before pick-pool sufficiency.

### 2.9. Referential Alignment and Cascade Consistency

Entities in the program are peers joined by references — a lot references its product, a standard references its machine and product, a release belongs to a blanket order that in turn references a contract and a product. The server maintains alignment across these references automatically: any operation whose rules cascade to other resources applies the primary mutation **and** every cascade atomically within the request; there is no observable intermediate state.

The deepest cascade is the contract amendment, which runs three hops — contract to its lines, lines to matching open blanket orders, orders to their scheduled releases — and the widest fan-out is product discontinuation, which touches blanket orders, releases, and inventory lots in one request. Both are specified step-by-step in §3.1 and §3.5. Every resource mutated along the way, primary or cascaded, observes the common-property rules of §2.5: its `updated_at` refreshes and its `version` increments.

The API contains exactly one nested creation route — a release is created as a child of a blanket order, and the path is validated left to right: the order identifier is resolved first (a nonexistent order yields `ERR_NOT_FOUND` before any payload evaluation), and only then are the body and business checks of §2.8 applied.

## 3. Business Logic & Workflows

### 3.1. Product Catalog: Registration, Shelf-Life Policy, and Discontinuation

A `ProgramAdmin` registers an abrasive product by supplying its `sku` (unique across the catalog), a display `name`, the `product_form` — one of `COATED`, `BONDED`, or `NONWOVEN` — and the product's `max_operating_speed_rpm`, the maximum safe operating speed, which must be at least 1. Two optional descriptors complete the safety and shelf-life profile. `shelf_life_months` gives the product's shelf life in calendar months; it is **required when the product form is `BONDED`** (bonded products degrade; omitting it is rejected with `ERR_INVALID_REQUEST`) and ignored for other forms. `shelf_life_policy` selects the expiry variant and is one of `EXACT_DAY` or `END_OF_MONTH`, defaulting to `EXACT_DAY` when omitted. `used_media_hazard_class` classifies the spent media as `NONE`, `METAL_SWARF`, or `OIL_CONTAMINATED`, defaulting to `NONE`. A new product starts `ACTIVE`.

Discontinuation is the catalog's terminal act and its widest fan-out. A `ProgramAdmin` discontinues a product by naming a replacement in the request body's `replacement_product_id`. The product must currently be `ACTIVE` — discontinuing anything else is `ERR_INVALID_STATE_TRANSITION`. A missing replacement id is `ERR_INVALID_REQUEST`; a replacement that does not exist is `ERR_NOT_FOUND`; a replacement that is the product itself, or that is not `ACTIVE`, is rejected with `ERR_REPLACEMENT_INVALID`. When the discontinuation succeeds, the product moves to `DISCONTINUED`, and both `replacement_product_id` and `discontinued_at` (stamped from the logical clock) are recorded on it. The cascade then runs, atomically:

- **Hop 1 — blanket orders.** Every blanket order in `DRAFT` or `OPEN` whose committed product is the discontinued product has its `substitution_status` set to `PENDING`.
- **Hop 2 — releases.** Every release in `SCHEDULED` belonging to a blanket order that just became `PENDING` moves to `ON_HOLD`.
- **Fan-out — lots.** Every inventory lot in `AVAILABLE` stocking the discontinued product moves to `BLOCKED`.

While an order's `substitution_status` is `PENDING`, no new releases may be scheduled against it (§3.6). The order's account manager resolves the pendency by accepting the substitution: the order's `product_id` is swapped to the replacement product, `substitution_status` becomes `ACCEPTED`, the order's `provisional_unit_price_cents` is re-stamped from the replacement product's contract line, `provisional_remaining_value_cents` is recomputed accordingly, and each of the order's `ON_HOLD` releases returns to `SCHEDULED` with its own `provisional_unit_price_cents` re-stamped by evaluating the price at its `scheduled_ship_date` against the replacement product's line. Acceptance requires that a contract line actually prices the replacement product on the order's contract; if none exists the acceptance fails with `ERR_CONTRACT_LINE_MISSING`. Acceptance on an order whose `substitution_status` is not `PENDING` is `ERR_INVALID_STATE_TRANSITION`.

### 3.2. Machine Assets and the Safety Gates

An `AccountManager` registers each customer machine with a free-form `customer_ref` identifying the customer or plant (there is no separate customer entity), a plant-floor `asset_tag`, the `machine_type` (for example `ANGLE_GRINDER`, `BELT_SANDER`, or `BENCH_GRINDER`), the machine's `spindle_max_rpm` (at least 1), and its `guard_type` — `FIXED`, `ADJUSTABLE`, or `NONE`. A new machine starts `ACTIVE` with `consumption_flag` set to `NORMAL`.

Machine safety state is cyclic: an `EHSOfficer` may quarantine an `ACTIVE` machine, moving it to `QUARANTINED`, and may later reinstate a `QUARANTINED` machine back to `ACTIVE`. There is no terminal state. Quarantining a machine that is not `ACTIVE`, or reinstating one that is not `QUARANTINED`, is `ERR_INVALID_STATE_TRANSITION`. While a machine is `QUARANTINED`, neither usage records nor trials may be created against it; both attempts fail with `ERR_MACHINE_NOT_ACTIVE`.

Two product-versus-machine safety gates guard both usage recording (§3.4) and trial creation (§3.8), and the speed gate is always evaluated before the guard gate. The **speed gate** requires the product's `max_operating_speed_rpm` to be at least the machine's `spindle_max_rpm`; a product rated slower than the spindle is rejected with `ERR_SPEED_RATING_EXCEEDED`. The **guard gate** requires any `BONDED` product to run only on a machine whose `guard_type` is `FIXED` or `ADJUSTABLE`; a bonded product on an unguarded (`NONE`) machine is rejected with `ERR_GUARD_REQUIRED`.

### 3.3. Inventory Lots: Receipt, Shelf Life, and Stock Movement

An `AccountManager` receives stock by lot, supplying the `product_id`, the manufacturer `lot_code`, the `manufacture_date` (an ISO date), and the `qty_received` (at least 1). The lot starts `AVAILABLE` with `qty_on_hand` initialized to `qty_received`, and the server computes its `expiry_date` from the product's shelf-life profile:

- When the product has no `shelf_life_months`, `expiry_date` is null — the lot never expires by shelf life.
- Under the `EXACT_DAY` policy, `expiry_date` is the `manufacture_date` advanced by `shelf_life_months` calendar months; if the target month has no such day-of-month, the date clamps to the target month's last day.
- Under the `END_OF_MONTH` policy, `expiry_date` is the last calendar day of the month reached by advancing `manufacture_date` by `shelf_life_months` months — later than the `EXACT_DAY` result whenever the manufacture day-of-month precedes the last day.

For example, a lot manufactured on 2026-01-15 with a 12-month shelf life expires on 2027-01-15 under `EXACT_DAY` but on 2027-01-31 under `END_OF_MONTH`.

A lot's stock moves through three mechanisms. Usage recording (§3.4) decrements `qty_on_hand` by the consumed quantity. Release picking (§3.7) decrements it by the allocated quantities. Release cancellation restores it. Whenever a decrement leaves `qty_on_hand` at exactly zero, the lot transitions from `AVAILABLE` to `DEPLETED`; when a cancel-restore lifts a `DEPLETED` lot back above zero, the lot returns to `AVAILABLE`. Restores into lots that are `BLOCKED` or `EXPIRED` increase `qty_on_hand` but leave the status untouched — such lots stay excluded from picking. Independently, the clock sweep (§2.4) expires lots, and product discontinuation (§3.1) blocks them.

### 3.4. Usage Standards and Consumption Variance Surveillance

The engineered consumption baseline for an operation is the **usage standard**. An `AccountManager` creates one by naming the `machine_id` and `product_id` it governs, an `operation_name` (for example `WELD_BLEND` or `EDGE_CHAMFER`), the `standard_qty_per_part` — media units per part, carried to 4 decimal places and strictly greater than 0 — and an effectiveness window: `effective_from` (inclusive) and an optional `effective_to`. The window is **half-open**: `effective_from` is inside it, `effective_to` is outside it, and a null `effective_to` means the standard is open-ended. When present, `effective_to` must be strictly after `effective_from`. Among `ACTIVE` standards for the same machine-and-product pair, windows must not overlap; adjacency — one standard's `effective_to` equal to another's `effective_from` — is allowed. An overlapping create is rejected with `ERR_STANDARD_WINDOW_OVERLAP`. A new standard starts `ACTIVE` with `needs_review` false. A `ProgramAdmin` may retire a standard, moving it from `ACTIVE` to `RETIRED` and freeing its window; retirement also recomputes the machine's `consumption_flag`, since the retired standard may have been the last one flagged for review.

Field consumption is captured by an `AccountManager` as a **usage record** — the VMI audit event — carrying `machine_id`, `product_id`, the `lot_id` the media was drawn from, the `usage_date`, the `qty_used` (at least 1), and the `parts_produced` (at least 1). Acceptance is gated, in the order of §2.8: the machine must be `ACTIVE` (`ERR_MACHINE_NOT_ACTIVE`); the lot must exist, must belong to the referenced product (a mismatch is `ERR_INVALID_REQUEST`), and must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE` — `BLOCKED`, `EXPIRED`, and `DEPLETED` lots cannot be consumed); the speed and guard gates of §3.2 apply; an `ACTIVE` standard whose half-open window contains the `usage_date` must exist for the machine-and-product pair (`ERR_NO_COVERING_STANDARD`); the `usage_date` must not be after the current logical-clock date (`ERR_USAGE_DATE_IN_FUTURE`); and the `qty_used` must not exceed the lot's `qty_on_hand` (`ERR_LOT_QTY_EXCEEDED` — consuming exactly the on-hand quantity is allowed and depletes the lot).

On acceptance the lot's `qty_on_hand` is decremented (reaching zero moves the lot to `DEPLETED`), and the record's three computed fields are stamped. `actual_qty_per_part` is `qty_used` divided by `parts_produced`, rounded half-up to 4 decimal places. `variance_pct` is the difference between `actual_qty_per_part` and the covering standard's `standard_qty_per_part`, divided by that standard, rounded half-up to 4 decimal places. `variance_band` classifies the variance: strictly greater than 0.10 is `OVER` — a variance of exactly 0.10 stays in band — strictly less than negative 0.10 is `UNDER`, and anything in between is `IN_BAND`.

Surveillance runs on a rolling window: the 5 most recent usage records for the same machine-and-product pair, ordered by `usage_date` descending and then `created_at` descending, inclusive of the record just accepted. When at least 3 of those 5 records are `OVER`, the covering standard's `needs_review` becomes true; otherwise it becomes false. The machine's `consumption_flag` is then recomputed: it is `ELEVATED` when any `ACTIVE` standard on that machine has `needs_review` true, and `NORMAL` otherwise. Usage records are append-only — they carry only `id` and `created_at`, and are never mutated.

### 3.5. Pricing Contracts: Drafting, Activation, Amendment, and Expiry

A pricing agreement is drafted by an `AccountManager` with the `customer_ref` it covers, a unique `contract_number`, the `term_start` and `term_end` bounding its term, the `price_hold_end` through which base prices hold, the `escalation_pct` (at least 0; for example 0.04), the `escalation_effective_date` from which escalated pricing applies, and a `lines` collection in which each entry pairs a `product_id` with its `base_unit_price_cents` (at least 1). The contract starts `DRAFT`, and one contract line is created per `lines` entry with `current_unit_price_cents` initialized to the entry's base price.

The central pricing function evaluates a line's price at a given date under its contract's terms, and every price the program stamps — provisional or final, on lines, orders, or releases — flows through it. All comparisons are at ISO-date granularity, and both boundary dates are **inclusive**: an evaluation date on or before `price_hold_end` yields the line's `base_unit_price_cents`; otherwise, an evaluation date on or after `escalation_effective_date` yields the base price multiplied by one plus `escalation_pct`, rounded half-up to whole cents; otherwise — the gap after the hold ends but before escalation takes effect — the base price applies unchanged.

Activation, performed by a `ProgramAdmin`, moves the contract from `DRAFT` to `ACTIVE`, stamps every line's `current_unit_price_cents` by evaluating the price at the current clock date, and increments the contract's `version`. Termination, also a `ProgramAdmin` act, moves the contract from `DRAFT` or `ACTIVE` to `TERMINATED`; the same transition from any other state is `ERR_INVALID_STATE_TRANSITION`. The clock sweep expires an `ACTIVE` contract once the clock date passes `term_end` (§2.4).

While `ACTIVE`, a contract may be amended by a `ProgramAdmin` changing its `escalation_pct` and/or `price_hold_end`. The amendment request must carry `expected_contract_version` matching the contract's current `version`, per §2.7; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and amending a contract that is not `ACTIVE` is `ERR_INVALID_STATE_TRANSITION`. A successful amendment increments the contract's `version` by one and fires the program's deepest cascade, atomically:

- **Hop 1 — lines.** Every contract line of the amended contract re-stamps `current_unit_price_cents` by evaluating the price at the current clock date under the amended terms.
- **Hop 2 — blanket orders.** Every blanket order in `OPEN` whose `product_id` matches a re-stamped line re-stamps its `provisional_unit_price_cents` from that line's `current_unit_price_cents`, and recomputes `provisional_remaining_value_cents` as its `remaining_qty` multiplied by the new provisional unit price.
- **Hop 3 — releases.** Every release in `SCHEDULED` belonging to a re-stamped order re-stamps its `provisional_unit_price_cents` by evaluating the price at that release's `scheduled_ship_date`.

This is why provisional prices are called provisional: they are forward-looking stamps that move when the contract moves. The final price at shipment (§3.7) is evaluated separately and may diverge.

### 3.6. Blanket Orders and Release Scheduling

A blanket order commits a customer — through its governing contract — to a pool of units of one product. An `AccountManager` drafts the order with a `contract_id`, a `product_id`, and the `committed_qty` (at least 1). The draft starts in `DRAFT` with `substitution_status` `NONE` and `remaining_qty` null; provisional pricing fields stay null until confirmation.

Confirmation, a `ProgramAdmin` act, moves the order from `DRAFT` to `OPEN` and is gated on three conditions: the governing contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); a contract line must exist for the order's contract-and-product pair (`ERR_CONTRACT_LINE_MISSING`); and the product must be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`). On confirmation the order's `remaining_qty` is initialized to `committed_qty`, `provisional_unit_price_cents` is stamped from the contract line's `current_unit_price_cents`, `provisional_remaining_value_cents` is computed as `remaining_qty` multiplied by the provisional unit price, and the order's `version` increments by one.

The committed pool is tracked continuously: `remaining_qty` is `committed_qty` minus the summed `qty` of the order's releases in `SCHEDULED`, `ON_HOLD`, `PICKED`, or `SHIPPED` status. Releases in `CANCELLED` are excluded from the sum — their quantity is given back to the pool.

Releases are scheduled by an `AccountManager` against an `OPEN` order — attempting to schedule against a `DRAFT`, `CLOSED`, or `CANCELLED` order is `ERR_INVALID_STATE_TRANSITION`. The create request carries the `qty`, the `scheduled_ship_date`, and — because this endpoint participates in optimistic concurrency — the `expected_blanket_order_version`; a version mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) before any state or business check, per §2.7 and §2.8. The remaining gates apply in order: the order's `substitution_status` must be `NONE` (`ERR_SUBSTITUTION_PENDING` — a substitution awaiting acceptance freezes new scheduling); then the order's product must still be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`); then the `scheduled_ship_date` must fall within the contract's term, on or after `term_start` and on or before `term_end` (`ERR_RELEASE_WINDOW_OUTSIDE_TERM`); and finally the `qty` must be at least 1 and no greater than the order's `remaining_qty` (`ERR_RELEASE_EXCEEDS_REMAINING` — a release exactly equal to the remaining pool is allowed). On acceptance the release starts `SCHEDULED`, the order's `remaining_qty` decreases by the release's `qty`, the release's `provisional_unit_price_cents` is stamped by evaluating the price at its `scheduled_ship_date`, and the parent order's `version` increments by one. At scheduling time, `final_unit_price_cents` and `billed_total_cents` are null and `allocations` is empty.

A blanket order can be cancelled by an `AccountManager` from either `DRAFT` or `OPEN`; cancelling from any other state is `ERR_INVALID_STATE_TRANSITION`. From `DRAFT` the transition to `CANCELLED` is a plain status change. From `OPEN` the cancellation cascades: every release in `SCHEDULED`, `ON_HOLD`, or `PICKED` moves to `CANCELLED` with the full per-state give-back behavior of §3.7 — including lot restoration for picked releases — and each cancelled release's quantity is returned to the pool (though for the now-terminal order the `remaining_qty` is informational only). Finally, the order auto-closes: after any individual release ships or is cancelled, if the order's `remaining_qty` has reached zero and no release remains in `SCHEDULED`, `ON_HOLD`, or `PICKED`, the order transitions from `OPEN` to `CLOSED` on its own.

### 3.7. Release Execution: FEFO Picking, Shipment, Billing, and Cancellation

Picking allocates physical stock to a `SCHEDULED` release on a first-expiry-first-out basis, performed by an `AccountManager`. The candidate pool is every lot of the order's product that is `AVAILABLE`, has `qty_on_hand` greater than zero, and has either no `expiry_date` or an `expiry_date` on or after the release's `scheduled_ship_date` — shipping on the lot's expiry day itself is allowed. An empty pool is rejected with `ERR_NO_ELIGIBLE_LOT`. Candidates are ranked by `expiry_date` ascending with never-expiring lots placed last, ties broken by `manufacture_date` ascending and then `created_at` ascending. The allocation walks the ranking as a waterfall, taking from each lot the lesser of its on-hand quantity and the remaining need, until the release quantity is covered. If the pool's total on-hand quantity is less than the release's `qty`, picking is rejected with `ERR_INSUFFICIENT_STOCK` and **no partial allocation is persisted**. A successful pick moves the release to `PICKED`, decrements each allocated lot's `qty_on_hand` (a lot reaching zero becomes `DEPLETED`), and records the waterfall lines — each a `lot_id` with its allocated `qty`, in allocation order — on the release's `allocations`. Notably, picking mutates only the release and the lots: the parent order's `version` is not bumped.

Shipment, also by an `AccountManager`, moves a `PICKED` release to `SHIPPED` and requires the order's contract to be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`). Shipment stamps the two final financial fields. `final_unit_price_cents` is the price evaluated at the **current logical-clock date** for the order's product — the final variant of the pricing function, which diverges from the provisional stamp whenever a hold or escalation boundary falls between the scheduled and actual ship dates. `billed_total_cents` follows a pinned five-step rounding order: first, the unit price is rounded at the unit level (this is the `final_unit_price_cents` just computed); second, each allocation line's gross is extended exactly as the unit price multiplied by that line's quantity; third, the line grosses are summed into the release gross; fourth, the tier discount percentage for the order is applied to the release gross and the result is rounded half-up to whole cents exactly once; fifth, the rounded discount is subtracted from the release gross. The tier percentage depends on the order's `committed_qty` with inclusive boundaries: at least 2000 committed units earns a discount of 6 percent (0.06); otherwise at least 500 committed units earns 3 percent (0.03); smaller orders earn no discount. For example, with a base price of 10013 cents, an escalation of 0.04 in effect at ship time, a shipped quantity of 2, and no tier, the pinned computation yields a unit price of 10414 cents and a total of 20828 cents — whereas rounding the unrounded unit-price-times-quantity product would yield 20827 cents, which is wrong. After shipment, the auto-close check of §3.6 runs on the parent order.

Cancellation returns a release's reservation to the pool and is reachable from three states, with behavior depending on the departure state. From `SCHEDULED`, the release moves to `CANCELLED`, its `qty` is added back to the order's `remaining_qty`, and the auto-close check runs. From `ON_HOLD`, the same give-back and auto-close apply. From `PICKED`, cancellation additionally restores stock: each allocation line's `qty` is returned to the **same** lot it was taken from, a `DEPLETED` lot lifted back above zero returns to `AVAILABLE`, `BLOCKED` and `EXPIRED` lots keep their status (their `qty_on_hand` increases but they remain unpickable), the release's `allocations` are cleared to empty, the quantity is given back, and the auto-close check runs. Cancelling a release that is already `SHIPPED` or `CANCELLED` is `ERR_INVALID_STATE_TRANSITION`. The same three branches execute when a release is cancelled by the blanket-order cancellation cascade of §3.6.

### 3.8. Product Trials: Documentation, Evaluation, and Conversion Governance

Before a new abrasive replaces an incumbent in a customer's operation, the program documents a structured trial. An `AccountManager` opens a trial with the trial `machine_id`, the candidate `product_id`, an optional `incumbent_product_id` being compared against, and a closed scheduling window from `scheduled_start` through `scheduled_end` (both dates inclusive; the end must be on or after the start). Creation is gated: the machine must be `ACTIVE` (`ERR_MACHINE_NOT_ACTIVE`); the speed and guard gates of §3.2 apply to the candidate product on the trial machine; the candidate product must be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`); and the trial's window must not conflict with any other trial in `ACTIVE` or `EVALUATION` status on the same machine. Windows are closed intervals, and the program requires a buffer of at least one full calendar day between trials on the same machine — overlapping windows, abutting windows, and windows separated by less than one full day are all rejected with `ERR_TRIAL_WINDOW_CONFLICT`. A new trial starts `ACTIVE`, with its measurement fields null.

When the trial run completes, an `EHSOfficer` submits the results: `measured_removal_rate_g_per_min`, `parts_per_unit_media` (strictly greater than 0), and `cost_per_part_cents`. Submission requires the trial to be `ACTIVE` (otherwise `ERR_INVALID_STATE_TRANSITION`), records the submitting officer's `X-User-ID` on the trial's `results_submitted_by_user_id`, stores the metrics, and moves the trial to `EVALUATION`.

Conversion is a `ProgramAdmin` decision on a trial in `EVALUATION`, and it enforces **segregation of duties**: the converting operator's `X-User-ID` must differ from the trial's `results_submitted_by_user_id`; the same person who measured the results may not approve the conversion, and an attempt to do so is rejected with `ERR_SEPARATION_OF_DUTIES`. A successful conversion moves the trial to `CONVERTED` and, atomically: retires the `ACTIVE` usage standard for the trial's machine-and-product pair if one exists, freeing its window; creates a new usage standard in `ACTIVE` status for the trial's `machine_id` and `product_id` with `operation_name` set to `TRIAL-CONVERSION`, `standard_qty_per_part` set to 1 divided by the trial's `parts_per_unit_media` rounded half-up to 4 decimal places, `effective_from` set to the current clock date, and `effective_to` null; points the trial's `converted_standard_id` at the new standard; and recomputes the machine's `consumption_flag`. Alternatively, a `ProgramAdmin` may reject a trial in `EVALUATION`, which requires a `rejection_reason` in the request body (omitting it is `ERR_INVALID_REQUEST`) and moves the trial to `REJECTED`.

### 3.9. Used-Media Disposal and Hazardous-Mass Reporting

Spent abrasives leave the program through a disposal manifest filed by an `EHSOfficer`. The record carries the `customer_ref` (the aggregation key for monthly hazard totals), the `product_id` of the disposed media, an optional `lot_id` traceability link — which may reference lots in any state, including `BLOCKED` or `EXPIRED` — the `qty_disposed` (at least 1), the `gross_weight_kg` (greater than 0, carried to 2 decimal places), the `disposal_method` (`RECYCLING`, `INCINERATION`, `LANDFILL`, or `HAZARDOUS_WASTE_FACILITY`), and the `disposed_at` date that fixes the record's calendar month. Disposal records are append-only: `id` and `created_at` only, never mutated.

Hazardous media — any product whose `used_media_hazard_class` is `METAL_SWARF` or `OIL_CONTAMINATED` — carries three escalating obligations, evaluated in this order. First, the `disposal_method` must be `HAZARDOUS_WASTE_FACILITY`; any other method is rejected with `ERR_HAZARD_DISPOSAL_METHOD_REQUIRED`. Second, both `manifest_number` and `certified_facility_ref` must be present; a missing field is rejected with `ERR_MANIFEST_FIELDS_REQUIRED` (HTTP 400). Third, the program aggregates the month's hazardous mass: the total `gross_weight_kg` over all disposal records sharing the new record's `customer_ref`, whose products are hazard-classed, and whose `disposed_at` falls in the same calendar month as the new record's `disposed_at` — the month running from its first day inclusive to the next month's first day exclusive — **including the new record itself**. When that monthly total reaches at least 1000.00 kg (the boundary is inclusive: exactly 1000.00 kg triggers the obligation), the record must carry a `regulator_report_ref`; its absence is rejected with `ERR_REGULATOR_REPORT_REQUIRED`. Records for products whose hazard class is `NONE` carry none of these three obligations.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, modify, or transition an existing resource return `200 OK`. All error responses use the envelope of §2.2 with the codes catalogued in §5. Request payloads, computed fields, and side effects are defined by the workflow narratives of §3; the table below is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/api/products` | Register an abrasives product (SKU) | ProgramAdmin |
| GET    | `/api/products` | List products | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/products/{id}` | Get a product | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/products/{id}/discontinue` | Discontinue a product with a named substitution replacement; cascades to blanket orders, releases, and lots | ProgramAdmin |
| POST   | `/api/machines` | Register a customer machine asset | AccountManager |
| GET    | `/api/machines/{id}` | Get a machine | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/machines/{id}/quarantine` | Safety-quarantine a machine (blocks usage and trials) | EHSOfficer |
| POST   | `/api/machines/{id}/reinstate` | Return a quarantined machine to service | EHSOfficer |
| POST   | `/api/lots` | Receive an inventory lot; computes `expiry_date` for shelf-life products | AccountManager |
| GET    | `/api/lots/{id}` | Get a lot | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/lots` | List lots | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/standards` | Create a standard consumption rate for a machine-and-product pair over a half-open window | AccountManager |
| GET    | `/api/standards/{id}` | Get a standard | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/standards` | List standards | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/standards/{id}/retire` | Retire a standard (frees its window) | ProgramAdmin |
| POST   | `/api/usage-records` | Record media consumption on a machine from a lot (VMI field audit) | AccountManager |
| GET    | `/api/usage-records/{id}` | Get a usage record | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/usage-records` | List usage records | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/contracts` | Create a pricing contract with per-product price lines | AccountManager |
| GET    | `/api/contracts/{id}` | Get a contract | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/contracts/{id}/activate` | Activate a contract; stamps line current prices at the logical clock | ProgramAdmin |
| PATCH  | `/api/contracts/{id}` | Amend `escalation_pct` and/or `price_hold_end` on an `ACTIVE` contract (OCC); depth-3 price cascade | ProgramAdmin |
| POST   | `/api/contracts/{id}/terminate` | Terminate a contract | ProgramAdmin |
| GET    | `/api/contract-lines/{id}` | Get a contract line | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/contract-lines` | List contract lines | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/blanket-orders` | Create a blanket order against a contract for one product | AccountManager |
| GET    | `/api/blanket-orders/{id}` | Get a blanket order | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/blanket-orders` | List blanket orders | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/blanket-orders/{id}/confirm` | Confirm a draft blanket order (requires `ACTIVE` contract, price line, `ACTIVE` product) | ProgramAdmin |
| POST   | `/api/blanket-orders/{id}/cancel` | Cancel a blanket order; cascades cancellation to open releases with give-back and lot restore | AccountManager |
| POST   | `/api/blanket-orders/{id}/accept-substitution` | Accept the discontinued product's replacement on a `PENDING` order | AccountManager |
| POST   | `/api/blanket-orders/{orderId}/releases` | Schedule a release against an `OPEN` blanket order (OCC on order version); reserves quantity and stamps the provisional price | AccountManager |
| GET    | `/api/releases/{id}` | Get a release | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/releases` | List releases | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/releases/{id}/pick` | FEFO-allocate stock lots for a `SCHEDULED` release | AccountManager |
| POST   | `/api/releases/{id}/ship` | Ship a `PICKED` release; stamps final price and billed total; requires `ACTIVE` contract | AccountManager |
| POST   | `/api/releases/{id}/cancel` | Cancel a `SCHEDULED`/`ON_HOLD`/`PICKED` release; gives back quantity; `PICKED` also restores lots | AccountManager |
| POST   | `/api/trials` | Document a product trial on a machine (safety-gated; closed-window scheduling with 1-day buffer) | AccountManager |
| GET    | `/api/trials/{id}` | Get a trial | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/trials` | List trials | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/trials/{id}/submit-results` | EHS officer submits trial measurements and safety documentation | EHSOfficer |
| POST   | `/api/trials/{id}/convert` | Approve conversion: retires the old operation standard and creates the converted standard | ProgramAdmin |
| POST   | `/api/trials/{id}/reject` | Reject a trial under evaluation | ProgramAdmin |
| POST   | `/api/disposal-records` | File a used-media waste disposal manifest | EHSOfficer |
| GET    | `/api/disposal-records/{id}` | Get a disposal record | ProgramAdmin, AccountManager, EHSOfficer |
| GET    | `/api/disposal-records` | List disposal records | ProgramAdmin, AccountManager, EHSOfficer |
| POST   | `/api/_clock/set_current_utc` | Set the logical clock (test-driving endpoint); runs the lot- and contract-expiry sweeps | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_MACHINE_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SPEED_RATING_EXCEEDED` | 409 Conflict |
| `ERR_GUARD_REQUIRED` | 409 Conflict |
| `ERR_PRODUCT_DISCONTINUED` | 409 Conflict |
| `ERR_SUBSTITUTION_PENDING` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_LINE_MISSING` | 409 Conflict |
| `ERR_STANDARD_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TRIAL_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SEPARATION_OF_DUTIES` | 409 Conflict |
| `ERR_NO_COVERING_STANDARD` | 409 Conflict |
| `ERR_RELEASE_WINDOW_OUTSIDE_TERM` | 409 Conflict |
| `ERR_USAGE_DATE_IN_FUTURE` | 409 Conflict |
| `ERR_RELEASE_EXCEEDS_REMAINING` | 409 Conflict |
| `ERR_LOT_QTY_EXCEEDED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_LOT` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_HAZARD_DISPOSAL_METHOD_REQUIRED` | 409 Conflict |
| `ERR_MANIFEST_FIELDS_REQUIRED` | 400 Bad Request |
| `ERR_REGULATOR_REPORT_REQUIRED` | 409 Conflict |
| `ERR_REPLACEMENT_INVALID` | 409 Conflict |

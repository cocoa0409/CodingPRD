# Vehicle Service Contract API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Vehicle Service Contract (VSC) and F&I Product Administration platform. The platform administers the full life of an aftermarket vehicle service contract in the style of programs such as Endurance or CARCHEX: an underwriter defines coverage plans with eligibility tiers and benefit limits, a contract administrator sells those plans against specific vehicles and optionally bundles ancillary products such as GAP, a claims organization adjudicates repair claims against published labor times and parts, and a reinsurance pool tracks ceded premium, paid losses, and held reserves as a loss-reserve ledger.

The system is fundamentally a ledger-reconciliation engine wrapped in a compliance workflow. Every claim payout, reserve movement, premium cession, and refund clawback posts a signed entry against a reinsurance pool, and the pool's surplus is continuously reconstructed from those postings. Layered on top are eligibility thresholds (vehicle age and odometer tiers), a dual-variant pro-rata refund calculation that can be driven either by elapsed time or by miles consumed, optimistic concurrency control on the contract aggregate during direct-pay disbursement, and a set of state machines — some cyclic, some carrying two independent dimensions at once — that govern contracts, claims, and authorizations.

Because money moves between customers, repair facilities, and a reinsurance pool, correctness and auditability are paramount. The platform records an audit event for material actions and maintains a logical clock so that earned-premium and free-look windows can be exercised deterministically. All monetary amounts are carried in integer cents to avoid floating-point drift.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. The platform recognizes exactly five roles: `AdminUnderwriter`, `ContractAdmin`, `ClaimsAdjuster`, `RepairFacility`, and `Auditor`. If the `X-User-Role` header is missing or names a role outside this set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four of the five roles carry an opaque identity. When `X-User-Role` is `AdminUnderwriter`, `ContractAdmin`, `ClaimsAdjuster`, or `Auditor`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it (for example, as the `actor_role` context on an `AuditEvent`) but never compares it to any entity's `id`. The `RepairFacility` role is different: its identity is entity-backed. When `X-User-Role` is `RepairFacility`, the `X-User-ID` is the `id` of the acting `RepairFacility` row, and any ownership check on a resource that references a repair facility compares that resource's facility foreign key to `X-User-ID`.

The broad division of authority is as follows. An `AdminUnderwriter` owns the product catalog — coverage plans and reinsurance pools — and registers repair facilities. A `ContractAdmin` sells and manages contracts, bundles ancillary products, and drives cancellations. A `ClaimsAdjuster` adjudicates claims and authorizes and disburses repair authorizations. A `RepairFacility` files claims and claim lines, receives direct pay, and reads its own authorizations. An `Auditor` has read-only oversight of every entity and the reinsurance ledger. The precise authorized-role set for each endpoint appears in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` that falls outside these bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 422).

Unless a specific endpoint states otherwise, all list responses are sorted by the `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources share a common set of system-managed fields. Every such resource has an `id` (a server-minted UUID with no type prefix), a `created_at` (ISO 8601 UTC timestamp with three fractional digits) marking when it was first created, an `updated_at` (same format) refreshed on every mutation, and a `version` (an integer that starts at 1 and increments by one on every mutation). The coverage plan, reinsurance pool, contract, ancillary product, repair facility, claim, claim line, repair authorization, and cancellation resources all carry this full set.

Three resources are deliberately leaner. The `LedgerEntry`, the `ClockState`, and the `AuditEvent` carry only `id` and `created_at`; they have neither an `updated_at` nor a `version`, because they are append-only or singleton records that are never individually mutated after creation.

The platform runs on a logical clock rather than wall-clock time. The `ClockState` exposes a single `current_utc` field that drives all earned-premium, free-look, and pro-rata window math. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied instant; if the supplied `to_iso8601` value is not a valid ISO 8601 UTC timestamp the request is rejected with `ERR_CLOCK_INVALID` (HTTP 422).

### 2.5. Monetary Precision and Rounding

All monetary fields are integer cents. Where a calculation produces a fractional cent — only the labor-line and the pro-rata refund computations can — the result is rounded to whole cents using the round-half-up method. The claim-payout and pool-surplus computations operate entirely on integer cents and need no rounding. The precise placement of each rounding step is specified with the calculation it belongs to in §3; the general rule is that rounding happens at the points called out there and nowhere else.

### 2.6. Request Validation and Range Constraints

Required body fields must be present and well-typed for the endpoint being called; a missing or ill-typed required field is rejected with `ERR_INVALID_REQUEST` (HTTP 422). Numeric inputs must respect their declared ranges. The `term_months` and `term_miles` of a plan must each be at least 1; `max_vehicle_age_years`, `max_odometer_at_sale`, `base_premium_cents`, `deductible_cents`, `labor_rate_cap_cents_per_hour`, `odometer_at_sale`, `sale_price_cents`, `finance_term_months`, `premium_cents`, `gap_cap_cents`, `posted_labor_rate_cents_per_hour`, `odometer_at_claim`, `requested_amount_cents`, `labor_hours`, and `rental_days_claimed` must all be non-negative. A numeric input that violates such a range constraint — a negative cents value or a `term_months` below 1, for example — is rejected with `ERR_VALIDATION_RANGE` (HTTP 422). A plan's `reinsurance_cession_pct` is a fraction that must lie between 0.0 and 1.0 inclusive; a value outside that closed interval is rejected with `ERR_INVALID_CESSION_PCT` (HTTP 422). This range check is applied at plan creation, when the value is supplied — a plan-creation request carrying a `reinsurance_cession_pct` outside `[0.0, 1.0]` is rejected with `ERR_INVALID_CESSION_PCT` — and the same check is re-applied as an activation precondition (§3.1).

### 2.7. Reference Resolution and Nested Path Validation

Many requests reference other resources by id, either in the URL path or in the request body. Path-referenced resources are validated left-to-right: when a path names more than one resource, the system checks each segment's resource in order and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first path id that does not resolve. Body foreign-key references — `coverage_plan_id`, `reinsurance_pool_id`, `contract_id`, `repair_facility_id`, and `claim_id` as supplied to contract creation, claim creation, ancillary-product creation, cancellation creation, and claim-line creation — must resolve to existing rows; an unresolved body reference is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). The list endpoints rooted at a parent resource (a pool's ledger entries and claims, a contract's ancillaries, claims, cancellation, and ledger entries, a facility's claims and authorizations, and a claim's lines and authorizations) are the reverse-reachability views over these foreign keys.

### 2.8. State Transition Guard

Every action endpoint that advances a resource through its state machine first checks that the target resource is currently in a state from which the requested transition is defined. If it is not, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). This guard is distinct from the business preconditions described in §3: it catches, for example, an attempt to approve a claim that is not under review or to reverse an authorization that was never disbursed.

### 2.9. The Reinsurance Ledger and Pool Surplus

Every reinsurance pool is a loss-reserve ledger. It tracks four computed money fields — `ceded_premium_cents`, `paid_loss_cents`, `reserve_held_cents`, and `surplus_cents` — and a `status` that is `OPEN` or `CLOSED`. All four money fields start at 0. Each financial event in the system posts a signed `LedgerEntry` against a pool, recording the `reinsurance_pool_id` it posts against, the `contract_id` that produced it when applicable, an `entry_type`, a signed `amount_cents`, and a human-readable `memo`. The `entry_type` is one of `PREMIUM_CEDED`, `RESERVE_SET`, `RESERVE_RELEASE`, `LOSS_PAID`, `LOSS_REVERSED`, or `REFUND_CLAWBACK`.

The pool's aggregates are reconstructed from its ledger after every posting, in a fixed evaluation order: first each column is aggregated, then the surplus is derived. The `ceded_premium_cents` is the sum of the signed amounts of the pool's `PREMIUM_CEDED` and `REFUND_CLAWBACK` entries; the `paid_loss_cents` is the sum of the pool's `LOSS_PAID` and `LOSS_REVERSED` entries; the `reserve_held_cents` is the sum of the pool's `RESERVE_SET` and `RESERVE_RELEASE` entries. The `surplus_cents` is then the ceded premium minus the paid loss minus the reserve held. All amounts are whole cents. Because clawbacks and reversals are posted as negative-signed amounts, summing the signed entries naturally nets them out. This recomputation runs whenever any ledger entry is posted, and it is also re-run when a pool is read so that its returned surplus reflects every posting to date.

### 2.10. Cascading Side Effects and Hierarchical Consistency

A single workflow action frequently mutates more than one resource. When a claim's reserve is set, released, or a payout is disbursed, the change ripples into the pool's ledger and aggregates; when an authorization is disbursed or reversed, the change ripples into the claim's payment dimension, the pool's reserve and loss columns, and the contract's running claim total. In every such case, each mutated resource independently has its `updated_at` refreshed and its `version` incremented (for resources that carry a version), and the pool surplus is recomputed per §2.9. The specific cascades — which resources move, in what order, and with which ledger postings — are described with the workflow that triggers them in §3. The governing principle here is that no cascade is optional: every secondary effect named in §3 always fires together with its primary action.

### 2.11. Optimistic Concurrency Control on Disbursement

Disbursing a repair authorization is the one operation guarded by optimistic concurrency control on the contract aggregate. The disburse request must carry `expected_contract_version`, a non-optional field carrying the client's last observed `version` of the contract behind the authorization's claim. If that value does not equal the contract's current `version`, the disbursement is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). The reason this matters: a prior disburse or reverse on any sibling authorization for the same contract bumps the contract's `version` (because it adjusts the contract's running claim total), so a disburse still carrying a previously observed version is acting on a stale view of that contract's claim ledger and must be refused. No other endpoint accepts or requires a version field; disbursement is the only one that does.

## 3. Business Logic & Workflows

### 3.1. Building the Product Catalog: Coverage Plans and Pools

The catalog begins with an `AdminUnderwriter`. A coverage plan is created in `DRAFT` status with a marketing `name`; a `tier` that is one of `POWERTRAIN`, `ENHANCED`, or `EXCLUSIONARY`; a coverage term expressed both as `term_months` and `term_miles`; two eligibility ceilings, `max_vehicle_age_years` (the vehicle's model-year age at sale, in years) and `max_odometer_at_sale` (the odometer reading at sale, in miles); a `base_premium_cents`; a per-visit `deductible_cents` applied to each repair authorization; a `labor_rate_cap_cents_per_hour`; and a `reinsurance_cession_pct` giving the fraction of earned premium ceded to the reinsurance pool. Three rental-and-towing benefit fields are optional and each default to 0 when omitted: `rental_benefit_cents_per_day`, `rental_max_days`, and `towing_benefit_cents`.

Activating a plan moves it from `DRAFT` to `ACTIVE`. Activation requires that the plan's `reinsurance_cession_pct` lie within the closed interval from 0.0 to 1.0 (otherwise `ERR_INVALID_CESSION_PCT`) and that `term_months` be at least 1 and `term_miles` be at least 1. The activation increments the plan's `version`. A contract may only be sold against an `ACTIVE` plan. Retiring a plan moves it from `ACTIVE` to the terminal `RETIRED` status and likewise increments its `version`; retirement is refused with `ERR_PLAN_IN_USE` (HTTP 409) if any contract in `PENDING` or `ACTIVE` status still references the plan.

Reinsurance pools are also created by an `AdminUnderwriter`, with just a `name`. A pool opens in `OPEN` status; its four money aggregates begin at 0 and evolve only through ledger postings as described in §2.9. The reverse-reachability views over a pool expose the ledger entries posted against it (filterable by `contract_id` and `entry_type`) and the claims charging against it.

Repair facilities round out the catalog and are registered by an `AdminUnderwriter` with a `name` and a `posted_labor_rate_cents_per_hour`. A facility's `network_status` is `IN_NETWORK` by default or may be set to `OUT_OF_NETWORK`, and `direct_pay_enrolled` defaults to false; both feed the disbursement routing described in §3.5. A facility's `status` is `ACTIVE` by default and may become `SUSPENDED`.

### 3.2. Selling and Maintaining a Contract

A `ContractAdmin` sells a contract by creating it against a chosen plan and pool. The sale captures the `coverage_plan_id` and `reinsurance_pool_id` it instantiates, the vehicle's `vin` and `vehicle_model_year`, the `odometer_at_sale`, the `sale_date` (the in-service date), and the `sale_price_cents` the customer paid including any ancillary bundle. Two finance fields complete the payload: `financed` defaults to false, and `finance_term_months` defaults to 0 and is required to be at least 1 only when the sale is financed. A freshly sold contract is in `PENDING` status.

A contract carries several computed fields. The `earned_premium_cents` is the premium recognized as earned to date; `paid_claim_total_cents` (default 0) is the running sum of approved-and-paid authorization payouts on the contract; and `cancellation_id` (default null) is the back-reference to a cancellation opened against the contract, set when a cancellation is opened and cleared if that cancellation is rejected. The contract's `status` is one of `PENDING`, `ACTIVE`, `LAPSED`, `CANCELLED`, or `EXPIRED`.

Activating a contract advances it from `PENDING` to `ACTIVE`. Activation enforces three preconditions in turn. First, the referenced plan must itself be in `ACTIVE` status, or the activation is rejected with `ERR_PLAN_NOT_ACTIVE`. Second, the vehicle must be eligible under the plan's tier: the vehicle's age — computed as the clock's current year minus the contract's `vehicle_model_year` — must be at most the plan's `max_vehicle_age_years`, and the contract's `odometer_at_sale` must be at most the plan's `max_odometer_at_sale`; a vehicle failing either bound is rejected with `ERR_VEHICLE_INELIGIBLE` (HTTP 422). Third, if the contract is financed, its `finance_term_months` must be at least 1, or the activation is rejected with `ERR_FINANCE_TERM_REQUIRED` (HTTP 422). On activation the contract's `earned_premium_cents` is set to 0, a placeholder `PREMIUM_CEDED` ledger entry of amount 0 is posted, and the contract's `version` is incremented; pool ceded-premium is recomputed lazily on earned-premium reads.

The contract runs a cyclic active/lapsed loop. Lapsing moves an `ACTIVE` contract to `LAPSED` and increments its `version`, but is refused with `ERR_OPEN_CLAIM_BLOCKS` (HTTP 409) if any claim under the contract is in adjudication status `UNDER_REVIEW`, or is `APPROVED` with a payment status other than `PAID`. Reinstating moves a `LAPSED` contract back to `ACTIVE` and increments its `version`, but only if the referenced plan is still in `ACTIVE` status (otherwise `ERR_PLAN_NOT_ACTIVE`).

Reading a contract recomputes its `earned_premium_cents` against the current clock and may automatically expire it: when the months elapsed since `sale_date` is at least the plan's `term_months`, an `ACTIVE` contract automatically transitions to the terminal `EXPIRED` status. That automatic expiry releases any remaining case reserves on the contract's open claims as `RESERVE_RELEASE` postings — decreasing the pool's `reserve_held_cents` — and increments the contract's `version`.

### 3.3. Bundling Ancillary Products

While a contract is still being sold, a `ContractAdmin` may bundle ancillary products onto it. Each ancillary names its parent `contract_id` and a `product_type` of `GAP`, `TIRE_WHEEL`, or `KEY_REPLACEMENT`, carries a `premium_cents` portion of the bundle, and exposes a `gap_cap_cents` (the maximum loan-deficiency payout for GAP, defaulting to 0 and held at 0 for non-GAP types) and a `refundable` flag that defaults to true and governs whether the ancillary is pro-rata refundable on cancellation. An ancillary's `status` is `BUNDLED` at creation and may later become `REFUNDED` or `CLAIMED`. Bundling is only permitted while the parent contract is in `PENDING` status; attempting to bundle an ancillary onto a non-`PENDING` contract — in particular adding GAP after activation — is rejected with `ERR_BUNDLE_TOO_LATE` (HTTP 422). The reverse-reachability view over a contract lists the ancillaries bundled with it.

### 3.4. Filing and Adjudicating a Claim

Claims are filed by either a `ClaimsAdjuster` or a `RepairFacility` against a contract and a repair shop. A new claim captures its `contract_id`, the `repair_facility_id` of the shop performing the repair, the `odometer_at_claim`, the `claim_date` of the repair event, and a free-text `complaint`. Two benefit-request fields are optional: `rental_days_claimed` defaults to 0 and `towing_claimed` defaults to false. At creation the claim copies the `reinsurance_pool_id` from its contract so that all of its reserve and loss postings land in the right pool. The claim also exposes computed money fields: `requested_amount_cents` (the running sum of its lines' requested amounts), `adjudicated_amount_cents` (the covered amount after adjudication, before deductible), and `reserve_cents` (the case reserve held in the pool while the claim is open, default 0).

A claim carries two independent state dimensions that evolve separately. The adjudication dimension, `adjudication_status`, runs `SUBMITTED` → `UNDER_REVIEW` → `APPROVED` or `DENIED`. The payment dimension, `payment_status`, runs `UNPAID` → `AUTHORIZED` → `PAID`, with a `PAID` → `VOID` reversal path. A claim has no single terminal state; it is fully resolved once its `adjudication_status` is `APPROVED` or `DENIED` and its `payment_status` is one of `PAID`, `VOID`, or `UNPAID`.

Claim lines are added to a claim by a `ClaimsAdjuster` or `RepairFacility`. Each line names its parent `claim_id` and a `line_type` of `PART` or `LABOR`. A part line carries a `part_number` and a `requested_amount_cents` (the claimed part price). A labor line carries `labor_hours` (published labor-time hours). Every line has a `covered` flag (default true) stating whether its component is covered under the plan tier, and a computed `allowed_amount_cents` holding the per-line covered amount after adjudication. A `PART` line must include a `part_number` and a `LABOR` line must include `labor_hours` greater than 0; a line violating either requirement is rejected with `ERR_INVALID_CLAIM_LINE` (HTTP 422). Adding a line recomputes the claim's `requested_amount_cents` as the sum of its lines' requested amounts. The reverse-reachability view over a claim lists its lines.

Starting review advances a claim's adjudication dimension from `SUBMITTED` to `UNDER_REVIEW`. Two preconditions guard the step. The referenced contract must be in `ACTIVE` status, or the request is rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409). And the claim's odometer must be within coverage: `odometer_at_claim` must be at most the contract's `odometer_at_sale` plus the plan's `term_miles`, or the request is rejected with `ERR_MILEAGE_EXCEEDED` (HTTP 422). When review starts, the system runs the adjudication computation to set each line's `allowed_amount_cents` and the claim's `adjudicated_amount_cents`, then sets the claim's `reserve_cents` equal to the adjudicated amount and posts a `RESERVE_SET` entry that increases the pool's `reserve_held_cents`, recomputing pool surplus.

The adjudication computation works line by line and then aggregates, with a pinned evaluation order: each line is computed and rounded to whole cents, and only then are the rounded lines summed — summing raw amounts and rounding once at the end is explicitly not used. For any line whose `covered` flag is false, the line's `allowed_amount_cents` is 0. For a covered `PART` line, the allowed amount equals its `requested_amount_cents` (already whole cents). For a covered `LABOR` line, the effective labor rate is the lesser of the facility's `posted_labor_rate_cents_per_hour` and the plan's `labor_rate_cap_cents_per_hour`; that effective rate is multiplied by the line's `labor_hours`, and the product is rounded half up to whole cents to give the line's allowed amount. The claim's `adjudicated_amount_cents` is the sum of all lines' rounded allowed amounts.

Approving a claim advances its adjudication dimension from `UNDER_REVIEW` to `APPROVED`, but only if the `adjudicated_amount_cents` is greater than 0; an attempt to approve when nothing is covered (the adjudicated amount is exactly 0) is rejected with `ERR_NOTHING_COVERED` (HTTP 422). Denying a claim instead advances its adjudication dimension from `UNDER_REVIEW` to `DENIED`; denial releases the case reserve by posting a `RESERVE_RELEASE` entry equal to the negative of the claim's `reserve_cents` — decreasing the pool's `reserve_held_cents` and recomputing surplus — and then setting the claim's `reserve_cents` to 0.

### 3.5. Authorizing and Disbursing a Repair

Once a claim is approved, a `ClaimsAdjuster` authorizes it, which creates a repair authorization and is the moment the claim's payment dimension advances from `UNPAID` to `AUTHORIZED`. Authorization copies the `repair_facility_id` from the claim and runs the payout computation as a preview to populate the authorization's money fields and routing. A repair authorization carries the originating `claim_id`, the copied `repair_facility_id`, a computed `covered_repair_cents` (the adjudicated covered amount before deductible), a `deductible_applied_cents` (the deductible withheld on this authorization), a `rental_payout_cents` and `towing_payout_cents` (each default 0), a `total_payout_cents` (the net amount disbursed), and a `pay_target` that is either `DIRECT_PAY` or `CUSTOMER_REIMBURSE`. Its `status` runs `PENDING` → `DISBURSED`, with a `DISBURSED` → `REVERSED` compensation path.

The payout computation applies the deductible exactly once per authorization, before rental and towing benefits are added. The covered repair amount is the claim's `adjudicated_amount_cents`. The deductible applied is the lesser of that covered repair amount and the plan's `deductible_cents`, so it never exceeds the covered repair and never drives the net below zero (the deductible floor is zero). The net repair is the covered repair minus the deductible applied. Rental is computed by first taking the lesser of the claim's `rental_days_claimed` and the plan's `rental_max_days`, then multiplying that day count by the plan's `rental_benefit_cents_per_day`. Towing pays the plan's flat `towing_benefit_cents` when the claim's `towing_claimed` is true and 0 otherwise. The authorization's `total_payout_cents` is the net repair plus the rental payout plus the towing payout; all amounts are whole cents and no rounding is required.

The `pay_target` is decided by the facility's enrollment: it is `DIRECT_PAY` when the facility's `direct_pay_enrolled` is true, and `CUSTOMER_REIMBURSE` otherwise. Enrollment alone only selects the direct-pay route; whether that route may actually disburse is enforced separately at disburse time, as described next.

Disbursing an authorization advances it from `PENDING` to `DISBURSED` and is the system's most consequential cascade. Several preconditions guard it. The authorization's claim must have `adjudication_status` of `APPROVED`, or the request is rejected with `ERR_CLAIM_NOT_APPROVED` (HTTP 409); the claim's `payment_status` must be `AUTHORIZED`, or it is rejected with `ERR_CLAIM_NOT_AUTHORIZED` (HTTP 409); and the supplied `expected_contract_version` must match the contract's current `version`, or it is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) as detailed in §2.11. Furthermore, when the authorization's `pay_target` is `DIRECT_PAY`, the facility must additionally be `ACTIVE` and `IN_NETWORK` (its `direct_pay_enrolled` is already true by virtue of the route having been selected); a `DIRECT_PAY` authorization whose facility is suspended or out-of-network is rejected with `ERR_FACILITY_NOT_DIRECT_PAY` (HTTP 422). An enrolled-but-out-of-network facility therefore yields a `pay_target` of `DIRECT_PAY` at authorization yet is refused at disburse time.

On a successful disbursement the payout is paid out — to the facility when `pay_target` is `DIRECT_PAY`, to the customer when it is `CUSTOMER_REIMBURSE` — and the cascade fires in three hops. First, the claim's `payment_status` is set to `PAID`, the claim's reserve is released by posting a `RESERVE_RELEASE` entry equal to the negative of the claim's `reserve_cents` (decreasing the pool's `reserve_held_cents`) and the claim's `reserve_cents` is set to 0. Second, a `LOSS_PAID` entry equal to the positive `total_payout_cents` is posted, increasing the pool's `paid_loss_cents` and recomputing surplus. Third, the contract's `paid_claim_total_cents` is increased by the `total_payout_cents`. The contract's `version` is incremented as part of this disbursement.

Reversing a disbursed authorization advances it from `DISBURSED` to the terminal `REVERSED` status and is the compensating action, permitted only while the authorization is in `DISBURSED` (otherwise `ERR_INVALID_STATE`). Reversal sets the claim's `payment_status` to `VOID`, posts a `LOSS_REVERSED` entry equal to the negative of the `total_payout_cents` (decreasing the pool's `paid_loss_cents` and recomputing surplus), decrements the contract's `paid_claim_total_cents` by the `total_payout_cents`, and increments the contract's `version`.

### 3.6. Cancellation and Pro-Rata Refund

A `ContractAdmin` opens a cancellation against a contract by supplying the `contract_id`, a `reason` of `CUSTOMER_REQUEST`, `REPOSSESSION`, `TOTAL_LOSS`, or `DEALER_UNWIND`, and the `request_date` the request was received. Opening a cancellation sets the contract's `cancellation_id` back-reference. A cancellation begins in `REQUESTED` status and exposes a set of computed fields filled in at approval: a `refund_basis` of `FULL`, `PRO_RATA_TIME`, or `PRO_RATA_MILEAGE`; a `gross_refund_cents` (the pro-rata unearned premium before fees and prior claims); a `cancellation_fee_cents` (default 0); a `claims_offset_cents` (default 0); and a `net_refund_cents` (the final refund disbursed). Its `status` runs `REQUESTED` → `APPROVED` → `REFUNDED`, with a `REQUESTED` → `REJECTED` path. The reverse-reachability view over a contract returns the zero or one cancellation opened against it.

Approving a cancellation advances it from `REQUESTED` to `APPROVED`. Two preconditions guard approval, evaluated in order: the referenced contract must be in `ACTIVE` or `LAPSED` status, or the approval is rejected with `ERR_CONTRACT_NOT_CANCELLABLE` (HTTP 409); and no claim under the contract may be in `payment_status` `AUTHORIZED` — an in-flight payout — or the approval is rejected with `ERR_CLAIM_IN_FLIGHT` (HTTP 409). On approval the refund computation runs and fills in `refund_basis`, `gross_refund_cents`, `cancellation_fee_cents`, `claims_offset_cents`, and `net_refund_cents`.

The refund computation begins with a free-look test. The days in force is the whole number of days between the contract's `sale_date` and the clock's current time, floored to whole days. If the days in force is at most the 30-day free-look window and the contract's `paid_claim_total_cents` is exactly 0, the refund basis is `FULL` and the gross refund equals the contract's full `sale_price_cents`. Otherwise the system computes a dual-variant unearned-premium refund. The time fraction is the days in force divided by the plan's term expressed in days — the `term_months` multiplied by 30 days per month — capped at 1.0. The miles used is the contract's current odometer minus its `odometer_at_sale`, floored at 0, where the current odometer is taken from the contract's latest claim by `claim_date` (breaking ties by `created_at` ascending) and falls back to the `odometer_at_sale` when there are no claims. The mileage fraction is the miles used divided by the plan's `term_miles`, capped at 1.0. The earned fraction is the greater of the time fraction and the mileage fraction — deliberately the greater fraction, hence the smaller refund. When the mileage fraction is at least the time fraction the refund basis is `PRO_RATA_MILEAGE`; otherwise it is `PRO_RATA_TIME`. The gross refund is the contract's `sale_price_cents` multiplied by one minus the earned fraction, with that product rounded half up to whole cents (the rounding happens after the multiplication).

A cancellation fee is withheld on every basis except free-look: the `cancellation_fee_cents` is 0 when the refund basis is `FULL` and is 5000 cents otherwise. A claims offset applies only when the reason is `DEALER_UNWIND`, in which case the `claims_offset_cents` equals the contract's `paid_claim_total_cents`; for every other reason the claims offset is 0. The `net_refund_cents` is the gross refund minus the cancellation fee minus the claims offset, floored at 0 so it never goes negative.

Rejecting a cancellation advances it from `REQUESTED` to the terminal `REJECTED` status and clears the contract's `cancellation_id` back-reference. Refunding an approved cancellation advances it from `APPROVED` to the terminal `REFUNDED` status; the refund transition is defined only from `APPROVED`, so a cancellation already in a terminal status (`REFUNDED` or `REJECTED`) fails the §2.8 structural state-transition guard and is rejected with `ERR_INVALID_STATE` (HTTP 409) ahead of any business check, while a cancellation still in the non-terminal `REQUESTED` status is rejected with the business error `ERR_CANCELLATION_NOT_APPROVED` (HTTP 409); refund further requires the contract to still be in `ACTIVE` or `LAPSED` status. The refund step disburses the `net_refund_cents` to the customer or lienholder and triggers a cross-entity cascade: the contract transitions to the terminal `CANCELLED` status, a `REFUND_CLAWBACK` entry equal to the negative of the `net_refund_cents` is posted (decreasing the pool's `ceded_premium_cents` and recomputing surplus), and every `BUNDLED` refundable ancillary product on the contract is set to `REFUNDED`. The contract's `version` is incremented as part of this transition.

### 3.7. Adjudication Priority and the Auditor's View

Several checks can apply to the same request, and they are evaluated in a fixed priority order so that the most fundamental failure surfaces first. Authentication of the role comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of path-referenced resources left-to-right (`ERR_NOT_FOUND`), then resolution of body foreign keys (`ERR_FK_NOT_FOUND`), then the state-transition guard that the resource is in a legal state for the requested move (`ERR_INVALID_STATE`). Only after those structural checks do the domain-specific state and business rules apply, in their own order: the contract-active check on start-review (`ERR_CONTRACT_NOT_ACTIVE`), the plan-active check on contract activate and reinstate (`ERR_PLAN_NOT_ACTIVE`), the approved-cancellation check on refund (`ERR_CANCELLATION_NOT_APPROVED`), the vehicle-eligibility check on contract activation (`ERR_VEHICLE_INELIGIBLE`), the mileage-coverage check on start-review (`ERR_MILEAGE_EXCEEDED`), the direct-pay facility check on disburse (`ERR_FACILITY_NOT_DIRECT_PAY`), the GAP-bundling-window check (`ERR_BUNDLE_TOO_LATE`), the nothing-covered check on approve (`ERR_NOTHING_COVERED`), the claim-line shape check (`ERR_INVALID_CLAIM_LINE`), the in-flight-payout check on cancellation approval (`ERR_CLAIM_IN_FLIGHT`), and the optimistic-concurrency check on disburse (`ERR_STALE_CONTRACT_VERSION`). The catch-all required-field-and-type check (`ERR_INVALID_REQUEST`) sits last among these. This ordering means, for instance, that a request lacking a valid role never reveals whether a downstream resource exists, and a disburse against a non-approved claim surfaces the claim-state error rather than a stale-version error.

The `Auditor` role sits across all of this with read-only access. An auditor can read every entity and walk the reinsurance ledger and every reverse-reachability list, but performs no mutations. The platform records an `AuditEvent` for material actions, capturing the `actor_role` that triggered the event, the `entity_type` and `entity_id` affected, and the `action` verb such as a claim approval or a contract cancellation.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource, including the state-transition actions that drive the workflows above, return a `200 OK` status code. Request and response bodies are not repeated here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coverage-plans` | Create a draft coverage plan | AdminUnderwriter |
| GET | `/coverage-plans` | List coverage plans | AdminUnderwriter, ContractAdmin, ClaimsAdjuster, Auditor |
| GET | `/coverage-plans/{id}` | Get a coverage plan | AdminUnderwriter, ContractAdmin, ClaimsAdjuster, Auditor |
| POST | `/coverage-plans/{id}/activate` | Activate a draft plan | AdminUnderwriter |
| POST | `/coverage-plans/{id}/retire` | Retire an active plan | AdminUnderwriter |
| POST | `/reinsurance-pools` | Create a reinsurance pool | AdminUnderwriter |
| GET | `/reinsurance-pools` | List pools | AdminUnderwriter, Auditor |
| GET | `/reinsurance-pools/{id}` | Get a pool with computed surplus | AdminUnderwriter, Auditor |
| GET | `/reinsurance-pools/{id}/ledger-entries` | List ledger entries posted against a pool | AdminUnderwriter, Auditor |
| GET | `/reinsurance-pools/{id}/claims` | List claims charging against a pool | AdminUnderwriter, Auditor |
| POST | `/contracts` | Sell (create) a pending contract | ContractAdmin |
| GET | `/contracts` | List contracts | ContractAdmin, ClaimsAdjuster, AdminUnderwriter, Auditor |
| GET | `/contracts/{id}` | Get a contract (earned premium recomputed; may auto-expire) | ContractAdmin, ClaimsAdjuster, AdminUnderwriter, Auditor |
| POST | `/contracts/{id}/activate` | Activate a pending contract after eligibility check | ContractAdmin |
| POST | `/contracts/{id}/lapse` | Lapse an active contract | ContractAdmin |
| POST | `/contracts/{id}/reinstate` | Reinstate a lapsed contract | ContractAdmin |
| GET | `/contracts/{id}/ancillary-products` | List ancillary products bundled with a contract | ContractAdmin, AdminUnderwriter, Auditor |
| GET | `/contracts/{id}/claims` | List claims filed under a contract | ContractAdmin, ClaimsAdjuster, Auditor |
| GET | `/contracts/{id}/cancellation` | List cancellation(s) opened against a contract | ContractAdmin, Auditor |
| GET | `/contracts/{id}/ledger-entries` | List ledger entries attributed to a contract | ContractAdmin, AdminUnderwriter, Auditor |
| POST | `/ancillary-products` | Bundle an ancillary product onto a pending contract | ContractAdmin |
| GET | `/ancillary-products/{id}` | Get an ancillary product | ContractAdmin, AdminUnderwriter, Auditor |
| POST | `/repair-facilities` | Register a repair facility | AdminUnderwriter |
| GET | `/repair-facilities/{id}` | Get a repair facility | AdminUnderwriter, ClaimsAdjuster, RepairFacility, Auditor |
| GET | `/repair-facilities/{id}/claims` | List claims filed at a facility | AdminUnderwriter, ClaimsAdjuster, RepairFacility, Auditor |
| GET | `/repair-facilities/{id}/repair-authorizations` | List repair authorizations directed to a facility | AdminUnderwriter, ClaimsAdjuster, RepairFacility, Auditor |
| POST | `/claims` | File a claim under a contract | ClaimsAdjuster, RepairFacility |
| GET | `/claims/{id}` | Get a claim | ClaimsAdjuster, RepairFacility, ContractAdmin, Auditor |
| POST | `/claims/{id}/lines` | Add a claim line (part or labor) | ClaimsAdjuster, RepairFacility |
| GET | `/claims/{id}/lines` | List claim lines | ClaimsAdjuster, RepairFacility, Auditor |
| POST | `/claims/{id}/start-review` | Begin adjudication; runs adjudication and sets reserve | ClaimsAdjuster |
| POST | `/claims/{id}/approve` | Approve an adjudicated claim | ClaimsAdjuster |
| POST | `/claims/{id}/deny` | Deny a claim; releases reserve | ClaimsAdjuster |
| POST | `/claims/{id}/authorize` | Create a repair authorization for an approved claim | ClaimsAdjuster |
| GET | `/repair-authorizations/{id}` | Get a repair authorization | ClaimsAdjuster, RepairFacility, Auditor |
| GET | `/claims/{id}/repair-authorizations` | List repair authorizations for a claim | ClaimsAdjuster, RepairFacility, Auditor |
| POST | `/repair-authorizations/{id}/disburse` | Disburse payout; OCC on contract version; cascades reserve release to loss paid | ClaimsAdjuster |
| POST | `/repair-authorizations/{id}/reverse` | Reverse a disbursed authorization (compensation) | ClaimsAdjuster |
| POST | `/cancellations` | Open a cancellation against a contract | ContractAdmin |
| GET | `/cancellations/{id}` | Get a cancellation | ContractAdmin, AdminUnderwriter, Auditor |
| POST | `/cancellations/{id}/approve` | Approve cancellation; runs pro-rata refund | ContractAdmin |
| POST | `/cancellations/{id}/reject` | Reject a cancellation | ContractAdmin |
| POST | `/cancellations/{id}/refund` | Disburse refund and cancel the contract | ContractAdmin |
| POST | `/_clock/set_current_utc` | Set the logical server clock | AdminUnderwriter, ContractAdmin, ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_IN_USE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_INVALID_CESSION_PCT` | 422 |
| `ERR_VEHICLE_INELIGIBLE` | 422 |
| `ERR_FINANCE_TERM_REQUIRED` | 422 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_MILEAGE_EXCEEDED` | 422 |
| `ERR_OPEN_CLAIM_BLOCKS` | 409 |
| `ERR_NOTHING_COVERED` | 422 |
| `ERR_INVALID_CLAIM_LINE` | 422 |
| `ERR_CLAIM_NOT_APPROVED` | 409 |
| `ERR_CLAIM_NOT_AUTHORIZED` | 409 |
| `ERR_FACILITY_NOT_DIRECT_PAY` | 422 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_BUNDLE_TOO_LATE` | 422 |
| `ERR_CLAIM_IN_FLIGHT` | 409 |
| `ERR_CANCELLATION_NOT_APPROVED` | 409 |
| `ERR_CONTRACT_NOT_CANCELLABLE` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_CLOCK_INVALID` | 422 |

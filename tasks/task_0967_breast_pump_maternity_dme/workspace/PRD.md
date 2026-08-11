# Breast Pump Maternity DME API — Product Requirements Document

## 1. Introduction

A durable medical equipment (DME) supplier specializing in breast pumps and maternity products operates at the intersection of retail fulfillment and health-insurance adjudication. A new mother typically has exactly one covered pump per benefit period, a narrow window in which a prescription remains valid, and a payer that may demand prior authorization before a device ships. On top of that, insurance-covered replacement parts must be dispensed on a strict cadence, compression garments draw against a separate per-period allowance, and every dollar the patient owes flows through deductible, coinsurance, and out-of-pocket-maximum arithmetic that must reconcile penny-for-penny with the payer's remittance.

This document specifies the REST API that powers that operation, mounted under `/dme`. It covers member registration, insurance policy management, prescription verification, pump order qualification and checkout with compression-garment add-ons, prior authorization, warehouse shipment and tracking, claims submission and remittance posting under segregation of duties, parts resupply scheduling with two distinct cadence modes, and the warranty lifecycle including capped replacements. A server-side logical clock governs every temporal rule — benefit periods, prescription expiry, resupply windows, warranty windows, and authorization validity — and temporal expiries are enforced lazily, at the moment an operation would rely on the expired artifact.

The API is designed for six distinct operator populations, from the patient herself through care coordinators, insurance specialists, billing specialists, warehouse staff, and platform administrators. Wherever two writers could disagree about the state of an order or a resupply schedule, optimistic concurrency control serializes them. Wherever money changes hands, provisional estimates computed at qualification time are explicitly distinguished from final adjudicated amounts computed at remittance time, and the two are never conflated.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the caller, and `X-User-Role` naming the caller's role. A request missing either header, or carrying a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, if the caller's role is not in the target endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The six roles are spelled exactly as follows: `Member`, `CareCoordinator`, `InsuranceSpecialist`, `BillingSpecialist`, `WarehouseOperator`, and `PlatformAdmin`.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's `member_id` field (or the member id carried in the path) to `X-User-ID`. A `Member` attempting to act on a resource owned by a different member is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403); this applies to member-facing endpoints covering pump orders, resupply orders, warranty claims, and member-scoped reads of policies, prescriptions, claims, and schedules. When `X-User-Role` is `CareCoordinator`, `InsuranceSpecialist`, `BillingSpecialist`, `WarehouseOperator`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `verified_by_user_id` on a `Prescription`, `submitted_by_user_id` on a `Claim` or `PriorAuthorization`, `decided_by_user_id` on a `PriorAuthorization`, or `remitted_by_user_id` on a `Claim` — but it is never compared to any entity's `id` for ownership.

One role-based rule deserves emphasis because it guards the financial ledger: the billing desk enforces **segregation of duties** between claim submission and remittance posting, described in §3.6.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must be at most 100. The `offset` parameter defaults to 0. Results are always sorted by `created_at` in ascending order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more` so the client can page deterministically through the full result set.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted entity carries a server-minted `id` (a UUID with no type prefix) and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Every entity in this system additionally carries `updated_at` (same format, refreshed on every mutation) and a `version` integer that starts at 1 on creation and increments by exactly 1 on every state transition, compensating action, cascade touch, or field mutation of that entity. A cascade that touches a policy, order, prescription, schedule, shipment, or claim therefore bumps that entity's `version` even though the client addressed a different resource — readers must treat `version` as an opaque change counter, not a record of their own writes.

Two write endpoints are guarded by optimistic concurrency control, and these are the only endpoints that accept a version field:

- Updating a pump order requires `expected_pump_order_version`, carrying the `version` of the `PumpOrder` the client last observed. If the order's current `version` differs — because a qualification, a cascade, or another writer advanced it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than silently overwriting state the client never saw.
- Adjusting a resupply schedule requires `expected_schedule_version`, carrying the `version` of the `ResupplySchedule` the client last observed. A resupply order created or cancelled in the meantime mutates the schedule and bumps its `version`, so a writer holding an old `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed above take no version field at all.

### 2.5. The Logical Clock and Lazy Temporal Evaluation

All date and datetime comparisons in the system are evaluated against a **logical clock**, never wall-clock time. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z. A `PlatformAdmin` may advance it via an admin-only test-driving capability that accepts a `to_iso8601` instant (ISO 8601 UTC) and returns the resulting `current_utc`; the logical clock never falls back to wall-clock time afterward.

Advancing the clock has **no eager side effects**. Nothing sweeps the database when time moves. Instead, temporal expiry is evaluated lazily at the guarded operations: a prescription that has passed its `expiration_date` flips to `EXPIRED` only when a verification, resubmission, or pump-order qualification attempt touches it; an approved prior authorization that has passed its `approved_until` flips to `EXPIRED` only when a shipment is attempted against its order; a resupply schedule whose policy's benefit period has ended flips to `ENDED` only when a resupply order is attempted against it. In each case the guarded call itself is rejected with the corresponding temporal error (`ERR_PRESCRIPTION_EXPIRED`, `ERR_PRIOR_AUTH_EXPIRED`, or `ERR_BENEFIT_PERIOD_ENDED`) at the same moment the lazy transition fires.

### 2.6. Monetary Precision and Rounding Discipline

All money amounts are integer cents. Every rounding in the system is **round half up**, applied per line before any summation. Two pinned evaluation orders prevent circular arithmetic:

1. **Line pricing precedes aggregation.** Each order line's total is computed as its quantity multiplied by its snapshotted unit price, rounded half up to integer cents, and only then are line totals summed into the order subtotal. Summing raw products and rounding once at the end is explicitly forbidden — the per-line-rounded sum is the only correct result.
2. **The bundle-discount tier test precedes discount allocation.** The merchandise subtotal is computed first, in full, with no discounts. The tier test then compares that pre-discount subtotal (which itself includes the garment lines) against the bundle threshold of 20000 cents — that is, $200.00. Only if the subtotal is at least the threshold does each garment line receive a discount of 10 percent of its line total, rounded half up per discounted line. Because the threshold is keyed on a subtotal that contains the very lines being discounted, evaluating the discount before the tier test would be circular.

### 2.7. Coverage Gates, Allowance Budgets, and Benefit Windows

An `InsurancePolicy` defines a benefit period as a **half-open interval**: the period begins at `benefit_period_start` (inclusive) and ends at `benefit_period_end` (exclusive). Any operation guarded by the benefit period — pump order creation, qualification, and resupply order creation — requires the current logical date to fall within that interval, and rejects with `ERR_BENEFIT_PERIOD_ENDED` (HTTP 422) otherwise. Among a single member's `ACTIVE` policies, benefit periods may never overlap; adjacency is permitted, meaning a new policy whose `benefit_period_start` equals an existing policy's `benefit_period_end` is allowed. An overlapping creation is rejected with `ERR_POLICY_PERIOD_OVERLAP` (HTTP 409).

Each policy carries two per-period consumption budgets. `pump_allowance_per_period` (default 1) caps how many pumps the member may consume in the period, tracked by `pumps_consumed_count`. `garment_allowance_per_period` (default 0) caps compression-garment units, tracked by `garments_consumed_count`. The invariant maintained at all times is that `garments_consumed_count` equals the sum of garment-line quantities over the policy's orders whose fulfillment is `QUALIFIED`, `SHIPPED`, or `DELIVERED`; consumption happens at qualification and is released at cancellation. Both budgets reject inclusively at their boundary: qualifying when the consumed count already equals the allowance is rejected, while a garment add-on that projects to exactly the allowance is permitted.

Prior authorization is gated by a dollar threshold. A policy's `prior_auth_threshold_cents` defaults to 50000 cents ($500.00), and the comparison at qualification is **inclusive**: an order whose estimated allowed amount equals the threshold exactly requires prior authorization just as surely as one above it.

### 2.8. Validation Pipeline and Priority Ordering

Every request passes through a fixed validation pipeline, evaluated in strict priority order. When several violations exist, the earliest category wins and determines the error returned:

1. **Authentication** — `X-User-Role` and `X-User-ID` headers are present and the role is declared (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization** — the role appears in the endpoint's role list (`ERR_FORBIDDEN`, 403).
3. **Ownership** — a `Member` caller acts only on their own resources (`ERR_OWNERSHIP_VIOLATION`, 403).
4. **Existence** — path identifiers resolve left-to-right and every foreign-key reference in the body exists; failures surface the entity-specific not-found errors such as `ERR_MEMBER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PRIOR_AUTH_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_RESUPPLY_ORDER_NOT_FOUND`, or `ERR_WARRANTY_CLAIM_NOT_FOUND` (all 404). Left-to-right resolution means a missing parent in a nested path is reported before the child is examined.
5. **Request shape** — required fields present, types valid, enum values valid, exactly one of the polymorphic foreign keys set where applicable, quantity at least 1, and `benefit_period_end` strictly after `benefit_period_start` (`ERR_VALIDATION`, 400).
6. **State** — state-machine preconditions hold, including terminal-state lockdown (`ERR_INVALID_STATE`, 409, and the state-specific 409 errors `ERR_PRESCRIPTION_NOT_VERIFIED`, `ERR_POLICY_NOT_ACTIVE`, `ERR_SCHEDULE_NOT_ACTIVE`, `ERR_PRIOR_AUTH_REQUIRED`, `ERR_PRIOR_AUTH_NOT_REQUIRED`, `ERR_DUPLICATE_CLAIM`).
7. **Segregation of duties** — remittance poster differs from claim submitter (`ERR_SEGREGATION_OF_DUTIES`, 422).
8. **Temporal rules** — prescription, benefit-period, resupply-window, warranty-window, and prior-auth-validity checks (`ERR_PRESCRIPTION_EXPIRED`, `ERR_BENEFIT_PERIOD_ENDED`, `ERR_RESUPPLY_WINDOW_NOT_OPEN`, `ERR_WARRANTY_EXPIRED`, `ERR_PRIOR_AUTH_EXPIRED`; all 422).
9. **Business constraints** — policy period overlap, pump-type match, add-on item type, reopen budget, and replacement budget (`ERR_POLICY_PERIOD_OVERLAP` at 409; `ERR_PUMP_TYPE_MISMATCH`, `ERR_INVALID_ITEM_TYPE`, `ERR_MAX_REOPENS_EXCEEDED`, `ERR_WARRANTY_REPLACEMENT_EXHAUSTED` at 422).
10. **Fiscal limits** — pump allowance, garment allowance, upgrade-tier coverage, resupply quantity cap, and remittance balance (`ERR_PUMP_ALLOWANCE_EXHAUSTED`, `ERR_GARMENT_ALLOWANCE_EXCEEDED`, `ERR_UPGRADE_TIER_NOT_COVERED`, `ERR_RESUPPLY_QUANTITY_CAP_EXCEEDED`, `ERR_REMITTANCE_IMBALANCE`; all 422).

### 2.9. Polymorphic References and Cross-Aggregate Linkage

Shipments and claims each serve two kinds of orders. A `Shipment` references either a pump order via `pump_order_id` or a resupply order via `resupply_order_id` — exactly one of the two must be set, never both, never neither; a violation is a request-shape error (`ERR_VALIDATION`). A `Claim` follows the identical rule over the same two fields. Both resources derive their `member_id` and `policy_id` from the source order rather than accepting them as input. The relationship between a member and everything downstream of her is always expressed through these references: a prescription names its patient by `member_id`, an order names its `member_id`, `policy_id`, `prescription_id`, and chosen `pump_item_id`, a prior authorization names its `pump_order_id`, and a resupply order names the `schedule_id` it draws against.

### 2.10. Cascades, Compensating Actions, and Aggregate Consistency

The system favors immediate consistency: when one operation mutates several entities, every touch happens in the same request. Delivery of a first, non-replacement pump shipment is the deepest cascade — it stamps the order's `delivery_date`, auto-creates resupply schedules for covered parts, and recomputes the member's resupply aggregates. Cancellations are compensating mirror images: cancelling a qualified order decrements the policy counters it incremented, restores the consumed prescription to `VERIFIED`, and withdraws any in-flight prior authorizations. Voiding an adjudicated claim reverses its deductible and out-of-pocket effects cent for cent. Two member-level aggregates are maintained continuously: `active_schedule_count` (the number of the member's resupply schedules currently `ACTIVE`) and `next_resupply_date` (the earliest `next_eligible_date` among those schedules, or null when none are `ACTIVE`). Both are recomputed whenever a schedule is created, suspended, resumed, or ended.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Members, Policies, and Prescriptions

A `CareCoordinator` (or `PlatformAdmin`) registers a patient by supplying `full_name`, `email`, `date_of_birth` in ISO `YYYY-MM-DD` form, and a default `shipping_address`. The `email` is unique across members. The new `Member` begins with `out_of_pocket_balance_cents` and `oop_accumulated_cents` at zero and `next_resupply_date` null, since no schedules exist yet.

With the member on file, a `PlatformAdmin` or `InsuranceSpecialist` creates an `InsurancePolicy` naming the policyholder by `member_id`, the `payer_name`, and a `plan_type` of exactly `COMMERCIAL_PPO`, `MEDICAID`, or `MEDICARE_ADVANTAGE`. The creator supplies `benefit_period_start` and `benefit_period_end`; the end must be strictly after the start, and the new period may not overlap any of the member's other `ACTIVE` policies, though back-to-back adjacency is fine. Optional coverage knobs include `requires_prior_auth` (default false — when true, every pump order needs an `APPROVED` prior authorization before it may ship), `prior_auth_threshold_cents`, `pump_allowance_per_period`, `garment_allowance_per_period`, `resupply_frequency_days` (default 90 days between parts fulfillments), `schedule_mode` of `ROLLING` or `CALENDAR_ANCHORED` (default `ROLLING`), `deductible_cents`, `coinsurance_pct` (a fraction between 0 and 1 inclusive), `oop_max_cents` (zero means no cap), and `upgrade_coverage` (whether `UPGRADE`-tier pumps are covered; the patient still pays the upgrade surcharge herself). A fresh policy starts `ACTIVE` with `pumps_consumed_count`, `garments_consumed_count`, and `deductible_met_cents` all at zero. Listing policies supports filters by `member_id` and `plan_type`, and terminating a policy is described in §3.8.

Prescriptions enter the system through a `CareCoordinator` or `PlatformAdmin`, who supplies the patient's `member_id`, an ICD-10-style `diagnosis_code`, a `pump_type` of `SINGLE_ELECTRIC`, `DOUBLE_ELECTRIC`, or `HOSPITAL_GRADE`, an `issued_date`, and an `expiration_date`. A new prescription lands in `PENDING_VERIFICATION`. An `InsuranceSpecialist` then verifies it — moving `PENDING_VERIFICATION → VERIFIED` and stamping `verified_by_user_id` with the caller's `X-User-ID` — or rejects it with a `rejection_reason`, moving `PENDING_VERIFICATION → REJECTED`. Verification refuses an expired document: if the current logical date is already past `expiration_date`, the prescription transitions `PENDING_VERIFICATION → EXPIRED` on the spot and the call is rejected with `ERR_PRESCRIPTION_EXPIRED`. A rejected prescription is not dead: a `CareCoordinator` or `InsuranceSpecialist` may resubmit it, moving `REJECTED → PENDING_VERIFICATION` and clearing `rejection_reason` to null — a loop that may repeat indefinitely, subject to the same expiry check (resubmitting past `expiration_date` flips the prescription to `EXPIRED` and is rejected with `ERR_PRESCRIPTION_EXPIRED`). The verification loop's terminal state is `EXPIRED`. Prescriptions may be listed filtered by `member_id`, `status`, or `consumed_by_order_id`.

### 3.2. Composing the Pump Order: Primary Line and Garment Add-Ons

The catalog is administered exclusively by `PlatformAdmin`. Each `CatalogItem` carries an `item_type` of `PUMP`, `PART`, or `COMPRESSION_GARMENT`, a display `name`, a unique `sku`, and a `unit_price_cents` list price. Pumps additionally declare an `insurance_tier` of `STANDARD` (the default) or `UPGRADE`, a flat patient-paid `upgrade_fee_cents` surcharge that is excluded from the deductible and coinsurance base, a `warranty_months` length measured from delivery, and a `pump_type` that must match the prescribing document. Parts declare `covered_under_resupply` (whether delivery of a pump order auto-creates a resupply schedule for the part) and `max_qty_per_frequency` (the most units a single resupply fulfillment may contain). Catalog listings filter by `item_type` or `covered_under_resupply`, and one can also list the order lines referencing a given catalog item.

A `Member` (for herself) or a `CareCoordinator` (on her behalf) opens a pump order by supplying `member_id`, `policy_id`, `prescription_id`, `pump_item_id`, and a `shipping_address` snapshot. Creation already enforces three guards: the policy must be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`), the current date must fall inside the benefit period (`ERR_BENEFIT_PERIOD_ENDED`), and the prescription's `pump_type` must equal the pump item's `pump_type` (`ERR_PUMP_TYPE_MISMATCH`). The server auto-creates the primary `OrderLine` — `line_type` `PUMP_PRIMARY`, `quantity` pinned to 1, `unit_price_cents` snapshotted from the catalog item — and runs pricing immediately. The order is born with `fulfillment_status` `PENDING_QUALIFICATION` and `billing_status` `UNBILLED`, two parallel dimensions that evolve independently, and with `replacement_count` at zero and `warranty_blocked` false.

Pricing works as follows. Every `OrderLine` stores its own `order_id`, `catalog_item_id`, and `line_type`. Each line's `line_total_cents` is the quantity multiplied by the snapshotted unit price, rounded half up per line. The order's `merchandise_subtotal_cents` is the sum of those per-line totals across all lines. Then the bundle rule fires: if the pre-discount subtotal reaches at least 20000 cents, each `ADDON_GARMENT` line receives a `discount_cents` equal to 10 percent of its line total, rounded half up; `PUMP_PRIMARY` lines always carry zero discount. The order's `discount_total_cents` sums the per-line discounts, and `order_total_cents` is the subtotal minus the discount total.

While the order remains `PENDING_QUALIFICATION`, the patient or coordinator may add compression-garment add-on lines by supplying a `catalog_item_id` and `quantity`. Add-on lines must reference `COMPRESSION_GARMENT` items only — anything else is rejected with `ERR_INVALID_ITEM_TYPE` — and each addition re-runs line pricing and the bundle discount. The garment budget is checked **projectively and inclusively**: the policy's current `garments_consumed_count` plus the quantities of all garment lines on this order including the new one must not exceed `garment_allowance_per_period`; projecting to exactly the allowance is allowed, and exceeding it is rejected with `ERR_GARMENT_ALLOWANCE_EXCEEDED`.

The same actors may also revise the order's pump model or `shipping_address` while it is `PENDING_QUALIFICATION`. That write carries `expected_pump_order_version` and is rejected with `ERR_STALE_VERSION` if the order's `version` has advanced beyond what the client observed. Swapping `pump_item_id` re-prices the primary line and re-runs the bundle discount, and the swap is held to the same compatibility gates as creation: the new pump's `pump_type` must match the prescription (`ERR_PUMP_TYPE_MISMATCH`), and an `UPGRADE`-tier pump is refused when the policy lacks `upgrade_coverage` (`ERR_UPGRADE_TIER_NOT_COVERED`). An order's lines can be listed at any time.

### 3.3. Qualification, Provisional Estimates, and Prior Authorization

Qualification is the pivotal act, performed by an `InsuranceSpecialist`. It is guarded by a battery of checks, and a reader reconstructing them should note where each sits in the pipeline of §2.8: the order must be `PENDING_QUALIFICATION`; the policy must be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`); the current date must sit inside the benefit period (`ERR_BENEFIT_PERIOD_ENDED`); the prescription must be `VERIFIED` (`ERR_PRESCRIPTION_NOT_VERIFIED`) and unexpired (`ERR_PRESCRIPTION_EXPIRED` — and if the date has passed, the prescription lazily transitions `VERIFIED → EXPIRED` as the call fails); the prescription and pump item must agree on `pump_type` (`ERR_PUMP_TYPE_MISMATCH`); the policy must have pump allowance remaining, i.e. `pumps_consumed_count` still below `pump_allowance_per_period` (`ERR_PUMP_ALLOWANCE_EXHAUSTED`); and an `UPGRADE`-tier pump requires `upgrade_coverage` on the policy (`ERR_UPGRADE_TIER_NOT_COVERED`).

A successful qualify — `PENDING_QUALIFICATION → QUALIFIED` — runs the **provisional estimate**, a forward-looking computation that deliberately uses the deductible state as it stands at qualify time and treats the payer-allowed amount as the pump's full list price. The insurance base is the pump's `unit_price_cents` minus its `upgrade_fee_cents`, because the upgrade surcharge is never covered. The deductible remaining is the policy's `deductible_cents` minus `deductible_met_cents`, floored at zero; the deductible applied is the smaller of the insurance base and that remainder. Coinsurance is the base net of deductible applied, multiplied by `coinsurance_pct`, rounded half up. The order then stores `provisional_allowed_cents` equal to the pump's full list `unit_price_cents`, `provisional_patient_cents` equal to the deductible applied plus coinsurance plus the upgrade fee, and its own `upgrade_fee_cents` snapshot copied from the catalog item (zero for `STANDARD`). These provisional figures are estimates; the final adjudicated numbers computed at remittance may differ, as §3.6 explains.

The same qualify evaluates the prior-auth requirement and stamps `prior_auth_required` on the order: true when the policy's `requires_prior_auth` flag is set, or when `provisional_allowed_cents` is at least `prior_auth_threshold_cents` — the threshold comparison is inclusive, so an estimate exactly equal to the threshold requires authorization. Qualification also consumes budgets: the policy's `pumps_consumed_count` rises by 1, its `garments_consumed_count` rises by the order's total garment quantity, and the supporting prescription cascades `VERIFIED → CONSUMED` with `consumed_by_order_id` pointing at this order.

When `prior_auth_required` is true, an `InsuranceSpecialist` submits a `PriorAuthorization` naming the order by `pump_order_id`; attempting this for an order that is not `QUALIFIED` or does not require authorization is rejected with `ERR_PRIOR_AUTH_NOT_REQUIRED`. The new PA derives its `member_id` and `policy_id` from the order, snapshots the pump's tier into `requested_item_tier`, records `submitted_by_user_id`, opens in `SUBMITTED` with `submission_count` 1, and cascades the order's `billing_status` from `UNBILLED` to `AUTH_PENDING`.

Payer responses arrive through a `PlatformAdmin` decision call carrying a `decision` and, as applicable, `auth_number`, `approved_until`, and `payer_notes`. From `SUBMITTED`, a decision of `APPROVED` (which must carry `approved_until`) moves the PA to `APPROVED`, stamps `auth_number`, `approved_until`, and `decided_by_user_id`, and cascades the order's billing to `AUTH_APPROVED`. A `DENIED` decision moves the PA to `DENIED`, records `decided_by_user_id`, and cascades billing to `DENIED`. A `PENDED` decision moves the PA to `PENDED` and stores `payer_notes`. Pended cases loop: an `InsuranceSpecialist` resubmits, moving `PENDED → SUBMITTED` and incrementing `submission_count` — an unbounded cycle. A denied PA is likewise appealable: appealing moves `DENIED → APPEALED` and returns the order's billing to `AUTH_PENDING`. From `APPEALED`, a payer decision of `APPROVED` lands in `APPROVED` (again requiring `approved_until` and setting `auth_number`; billing becomes `AUTH_APPROVED`), while `DENIED` lands in the terminal `DENIED_FINAL` (billing becomes `DENIED`). Approval is not a blank check: it lapses. If a shipment is attempted for the order after `approved_until` has passed and the order has not yet shipped or been delivered, the PA lazily transitions `APPROVED → EXPIRED`, the order's billing falls back to `AUTH_PENDING`, and the shipment is rejected with `ERR_PRIOR_AUTH_EXPIRED`. Prior authorizations can be listed filtered by `pump_order_id`, `member_id`, `policy_id`, or `status`.

### 3.4. Shipment, Delivery, and the Resupply Cascade

Fulfillment belongs to the `WarehouseOperator`. Creating a shipment requires exactly one of `pump_order_id` or `resupply_order_id`, plus a `carrier` and `tracking_number`; the server stamps `shipped_at` at creation and opens the shipment in `LABEL_CREATED` with `is_warranty_replacement` false (warranty replacements are created by the system, §3.7).

For a pump order, shipment is gated by authorization. If the order's `prior_auth_required` is false, the gate passes trivially. If it is true, an `APPROVED` prior authorization must exist whose `approved_until` has not passed; absent an approved PA the shipment is rejected with `ERR_PRIOR_AUTH_REQUIRED`, and an approved-but-lapsed PA flips to `EXPIRED` as described above (`ERR_PRIOR_AUTH_EXPIRED`). A passing shipment cascades the pump order `QUALIFIED → SHIPPED`. For a resupply order in `APPROVED`, the shipment cascades it `APPROVED → SHIPPED`. Shipment listings filter by `pump_order_id`, `resupply_order_id`, or `status`.

The warehouse then advances carrier status stepwise: `LABEL_CREATED → IN_TRANSIT`, `IN_TRANSIT → OUT_FOR_DELIVERY`, and `OUT_FOR_DELIVERY → DELIVERED`, each by declaring the target `to_status`. Off the happy path, a shipment in `LABEL_CREATED` or `IN_TRANSIT` may be marked `LOST`, and one `OUT_FOR_DELIVERY` may be marked `RETURNED`; `DELIVERED`, `RETURNED`, and `LOST` are terminal.

Delivery is the system's richest cascade. The shipment's `delivered_at` is stamped. What happens next depends on what was shipped:

- A **first, non-replacement pump shipment** whose order is `SHIPPED` moves that order `SHIPPED → DELIVERED` and stamps the order's `delivery_date` with the current logical date. Then, for every catalog part with `covered_under_resupply` true, the server creates a `ResupplySchedule`: `member_id` and `pump_order_id` taken from the delivered order, `catalog_item_id` naming the part, `frequency_days` and `schedule_mode` snapshotted from the policy at that moment, `anchor_date` set to the order's `delivery_date`, `last_fulfilled_date` null, `next_eligible_date` computed per the cadence rule of §3.5, and `status` `ACTIVE`. Finally the member's `active_schedule_count` and `next_resupply_date` are recomputed over her now-`ACTIVE` schedules. This full cascade fires only once per order — the first non-replacement delivery.
- A **warranty-replacement shipment** (flagged `is_warranty_replacement`) triggers no order transition and no schedule creation when it is delivered.
- A **resupply shipment** whose resupply order is `SHIPPED` moves that order `SHIPPED → DELIVERED`.

`DELIVERED` and `CANCELLED` are the terminal fulfillment states of a pump order; `DELIVERED` is also when the order becomes claimable (§3.6) and warranty-eligible (§3.7).

### 3.5. Parts Resupply: Cadence Variants and Eligibility Windows

Resupply schedules are read-only for members and coordinators except for one adjustment surface. A `CareCoordinator` may patch a schedule's `frequency_days` or flip its `status` between `ACTIVE` and `SUSPENDED`; the write carries `expected_schedule_version` and is rejected with `ERR_STALE_VERSION` when the schedule has moved on since the client last read it. Every adjustment recomputes `next_eligible_date`, and every `ACTIVE ↔ SUSPENDED` flip recomputes the member's `active_schedule_count` and `next_resupply_date`. Schedules list with filters by `member_id`, `pump_order_id`, `catalog_item_id`, or `status`.

The cadence rule has two variants, pinned by the schedule's snapshotted `schedule_mode`. Both share a base: with no fulfillment yet, the first eligibility falls exactly `frequency_days` after `anchor_date`.

- Under `ROLLING`, each fulfillment re-anchors the cadence: `next_eligible_date` is `last_fulfilled_date` plus `frequency_days`. A late fulfillment pushes the whole cadence out.
- Under `CALENDAR_ANCHORED`, eligibility instants are fixed to the delivery anchor at whole multiples of `frequency_days`; the `next_eligible_date` is the smallest such instant strictly later than `last_fulfilled_date`. An off-cadence fulfillment snaps forward to the next anchor instant, so the same fulfillment date can yield a different next eligibility than `ROLLING` would.

Either the patient or her coordinator draws against an `ACTIVE` schedule by creating a resupply order with `schedule_id`, `member_id`, and `quantity`; the `member_id` must equal the schedule's own member, the schedule must be `ACTIVE` (`ERR_SCHEDULE_NOT_ACTIVE` otherwise), the current date must have reached `next_eligible_date` — inclusive, so ordering exactly on the eligible date is allowed, and earlier attempts fail with `ERR_RESUPPLY_WINDOW_NOT_OPEN` — and the policy's benefit period must still be open. That last check is lazy: if the current date has reached the policy's `benefit_period_end`, the schedule transitions `ACTIVE → ENDED`, the member's aggregates are recomputed, and the call is rejected with `ERR_BENEFIT_PERIOD_ENDED`. The requested `quantity` must not exceed the part's `max_qty_per_frequency` (`ERR_RESUPPLY_QUANTITY_CAP_EXCEEDED`).

A resupply order is born in `APPROVED` — there is no separate approval step — with `unit_price_cents` snapshotted from the part and `total_cents` equal to quantity times unit price, rounded half up. Its `fulfilled_date` is its creation date, which counts as the fulfillment for pacing purposes: the schedule's `last_fulfilled_date` is set to the current date, `next_eligible_date` is recomputed, and the schedule's `version` advances. Resupply orders list with filters by `schedule_id`, `member_id`, or `status`.

Cancelling an `APPROVED` resupply order moves it to `CANCELLED` and repairs the pacing state: if the schedule's `last_fulfilled_date` equals this order's `fulfilled_date`, it rolls back to the `fulfilled_date` of the latest other non-`CANCELLED` resupply order on that schedule — or null if none remains — and `next_eligible_date` is recomputed. Both the order's and the schedule's `version` advance. Once a resupply order has shipped it can no longer be cancelled; `DELIVERED` and `CANCELLED` are terminal.

### 3.6. Claims, Remittance, and the Adjudication Waterfall

Once an order is `DELIVERED`, an `InsuranceSpecialist` files a `Claim` against it — pump order or resupply order, exactly one of `pump_order_id` or `resupply_order_id` set. At most one claim may exist per source order; a second attempt is rejected with `ERR_DUPLICATE_CLAIM`. The claim derives `member_id` and `policy_id` from the source order, receives a server-minted `claim_number`, records `submitted_by_user_id`, and opens in `SUBMITTED`. Its `provisional_allowed_cents` is frozen at creation: for a pump order it copies the order's provisional allowed estimate; for a resupply order it takes the order's total. Filing cascades the source order's `billing_status` to `CLAIM_FILED` — reachable from `UNBILLED` on the no-prior-auth path, or from `AUTH_APPROVED` once authorization is in hand. Claims list with filters by `member_id`, `policy_id`, `pump_order_id`, `resupply_order_id`, or `status`.

Remittance is the billing desk's act, performed by a `BillingSpecialist` (or `PlatformAdmin`) supplying an `outcome`, the payer's `adjudicated_allowed_cents`, the payer's `insurance_paid_cents`, and optionally a `remittance_reference`. Two guards precede the math. First, segregation of duties: the remitting `X-User-ID` must differ from the claim's `submitted_by_user_id` — the person who filed a claim may never post its remittance — else `ERR_SEGREGATION_OF_DUTIES`. Second, the remittance must balance, per the waterfall below, else `ERR_REMITTANCE_IMBALANCE`.

An `APPROVED` outcome on a `SUBMITTED` or `APPEALED` claim runs the **adjudication waterfall**, the dual of the provisional estimate: it uses the payer's adjudicated allowed amount and the deductible state at remit time, so identical order data can yield a different patient responsibility than the qualify-time estimate. The deductible remaining is the policy's `deductible_cents` minus `deductible_met_cents`, floored at zero; `deductible_applied_cents` is the smaller of the adjudicated allowed amount and that remainder. The remainder after deductible is multiplied by `coinsurance_pct` and rounded half up to get coinsurance. The patient responsibility before any cap is the deductible applied plus coinsurance. When the policy's `oop_max_cents` is greater than zero, the final `patient_responsibility_cents` is the smaller of that pre-cap amount and the headroom remaining under the out-of-pocket maximum — the cap minus the member's `oop_accumulated_cents`, floored at zero; with a zero cap the pre-cap amount stands. The invariant then binds: `insurance_paid_cents` must exactly equal the adjudicated allowed amount minus the computed patient responsibility, or the remit is rejected with `ERR_REMITTANCE_IMBALANCE`.

Posting an approved remittance moves the claim `SUBMITTED → ADJUDICATED` (or `APPEALED → ADJUDICATED`), stamps `remitted_by_user_id`, `remitted_at`, and `remittance_reference`, and ripples the ledger: the policy's `deductible_met_cents` rises by `deductible_applied_cents`, and the member's `oop_accumulated_cents` and `out_of_pocket_balance_cents` both rise by `patient_responsibility_cents`. The source order's billing moves to `ADJUDICATED`. A `DENIED` outcome instead moves the claim to `DENIED` and the order's billing to `DENIED`, still recording `remitted_by_user_id` and `remitted_at`.

Denial is not final. An `InsuranceSpecialist` may appeal a `DENIED` claim, moving it to `APPEALED` and returning the order's billing to `CLAIM_FILED`; the appealed claim is then remittable again under the same rules, and the `DENIED → APPEALED → DENIED` loop may cycle. Finally, a `BillingSpecialist` may void an `ADJUDICATED` claim: the claim moves to the terminal `VOID`, the compensation reverses the ledger — the policy's `deductible_met_cents` falls by `deductible_applied_cents`, and the member's `oop_accumulated_cents` and `out_of_pocket_balance_cents` both fall by `patient_responsibility_cents` — and the source order's billing returns to `CLAIM_FILED`, leaving the order claimable once more.

### 3.7. Warranty Claims, Replacements, and the Replacement Budget

A delivered pump carries a warranty measured from the order's `delivery_date` for the catalog item's `warranty_months`. The patient or her coordinator opens a `WarrantyClaim` by naming the `pump_order_id`, the device's `serial_number`, an `issue_type` of `MOTOR_FAILURE`, `BATTERY_FAILURE`, `SUCTION_LOSS`, `PHYSICAL_DAMAGE`, or `OTHER`, and an optional free-text `description`. Two temporal-and-budget gates apply at creation: the current date must not be past the delivery date plus the warranty length (`ERR_WARRANTY_EXPIRED`), and the order's `warranty_blocked` must be false — once an order's `replacement_count` has reached the replacement budget of 2, no further warranty claims open against it (`ERR_WARRANTY_REPLACEMENT_EXHAUSTED`). A new claim opens in `OPENED` with `reopen_count` zero and derives its `member_id` from the order. Warranty claims list with filters by `pump_order_id`, `member_id`, `status`, or `replacement_shipment_id`.

Adjudication belongs to `PlatformAdmin`, who submits a `decision` with optional `resolution_notes`. From `OPENED` the claim moves to `APPROVED_REPAIR`, `APPROVED_REPLACE`, or `DENIED` accordingly, storing the notes. A denied claim can be reopened by the patient or coordinator, moving `DENIED → OPENED` and incrementing `reopen_count` — but the reopen budget is 2, and a claim already reopened twice is rejected with `ERR_MAX_REOPENS_EXCEEDED`.

Resolution closes the loop. An `APPROVED_REPAIR` claim resolves straight to `RESOLVED`. An `APPROVED_REPLACE` claim resolves with a cascade: the server creates a replacement `Shipment` for the claim's `pump_order_id` with `is_warranty_replacement` true, carrier `WARRANTY_REPLACEMENT`, a server-minted `tracking_number`, and status `LABEL_CREATED`; the claim's `replacement_shipment_id` points at it; and the order's `replacement_count` increments, flipping `warranty_blocked` to true once the count reaches 2 — the budget that gates future claims. Replacement shipments advance through the normal carrier statuses, but per §3.4 their delivery deliberately does not move the order or mint new resupply schedules. `RESOLVED` is terminal.

### 3.8. Cancellations, Appeals, Voids, and Policy Termination

Several escape hatches keep the books honest when plans change, and each is a compensating mirror of the forward path.

A patient or coordinator may cancel a pump order while it is `PENDING_QUALIFICATION` or `QUALIFIED`; anything further along is locked (`ERR_INVALID_STATE`). Cancelling a `PENDING_QUALIFICATION` order simply moves it to `CANCELLED`. Cancelling a `QUALIFIED` order runs full compensation: the policy's `pumps_consumed_count` decreases by 1 and its `garments_consumed_count` decreases by the order's garment quantity; the consumed prescription is restored `CONSUMED → VERIFIED` with `consumed_by_order_id` cleared to null; and every prior authorization on the order sitting in `SUBMITTED` or `PENDED` cascades to `WITHDRAWN`. All touched entities' versions advance. Cancellation of resupply orders and its schedule rollback are covered in §3.5, claim appeal and void in §3.6, and warranty reopen in §3.7.

The heaviest hammer is policy termination, available to `PlatformAdmin` and `InsuranceSpecialist`. Terminating moves the policy `ACTIVE → TERMINATED` (its terminal state) and sweeps downstream: every `ResupplySchedule` whose originating pump order bills this policy and whose status is `ACTIVE` or `SUSPENDED` transitions to `ENDED`, and each affected member's `active_schedule_count` and `next_resupply_date` are recomputed. After termination the policy fails the `ACTIVE` gate everywhere — new orders and qualifications against it are rejected with `ERR_POLICY_NOT_ACTIVE` — while its historical claims, orders, and deliveries remain readable.

## 4. Endpoint Definitions

All endpoints are mounted under `/dme`. Creating a new resource returns HTTP 201 with the created resource; modifications, state transitions, and reads return HTTP 200 with the affected resource. Every write that mutates an entity increments that entity's `version` and refreshes `updated_at`. The two optimistic-concurrency endpoints named in §2.4 require their version field on every call; all other endpoints take no version field.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /dme/members | Register a member | CareCoordinator, PlatformAdmin |
| GET | /dme/members/{id} | Get one member; Member role only for self | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, WarehouseOperator, PlatformAdmin |
| GET | /dme/members | List members with pagination | CareCoordinator, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| POST | /dme/policies | Create an insurance policy for a member; rejects overlapping ACTIVE benefit periods (half-open, adjacency allowed) | PlatformAdmin, InsuranceSpecialist |
| GET | /dme/policies/{id} | Get one policy | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| GET | /dme/policies | List policies | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| POST | /dme/policies/{id}/terminate | Terminate a policy; cascades ACTIVE/SUSPENDED resupply schedules (via this policy's orders) to ENDED | PlatformAdmin, InsuranceSpecialist |
| POST | /dme/prescriptions | Create a prescription (PENDING_VERIFICATION) | CareCoordinator, PlatformAdmin |
| GET | /dme/prescriptions/{id} | Get one prescription | Member, CareCoordinator, InsuranceSpecialist, PlatformAdmin |
| GET | /dme/prescriptions | List prescriptions | Member, CareCoordinator, InsuranceSpecialist, PlatformAdmin |
| POST | /dme/prescriptions/{id}/verify | Verify a prescription | InsuranceSpecialist |
| POST | /dme/prescriptions/{id}/reject | Reject a prescription | InsuranceSpecialist |
| POST | /dme/prescriptions/{id}/resubmit | Resubmit a rejected prescription (cyclic loop) | CareCoordinator, InsuranceSpecialist |
| POST | /dme/catalog-items | Create a catalog item (pump model, part, or garment) | PlatformAdmin |
| GET | /dme/catalog-items/{id} | Get one catalog item | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, WarehouseOperator, PlatformAdmin |
| GET | /dme/catalog-items | List catalog items | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, WarehouseOperator, PlatformAdmin |
| GET | /dme/catalog-items/{id}/order-lines | List order lines referencing this catalog item | CareCoordinator, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| POST | /dme/pump-orders | Create a pump order; auto-creates the PUMP_PRIMARY OrderLine and runs pricing | Member, CareCoordinator |
| GET | /dme/pump-orders/{id} | Get one pump order | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, WarehouseOperator, PlatformAdmin |
| GET | /dme/pump-orders | List pump orders | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, WarehouseOperator, PlatformAdmin |
| PATCH | /dme/pump-orders/{id} | Change pump model and/or shipping address while PENDING_QUALIFICATION; OCC on order version | Member, CareCoordinator |
| POST | /dme/pump-orders/{id}/qualify | Run insurance qualification: provisional estimate, prior-auth requirement, allowance consumption, prescription consumption | InsuranceSpecialist |
| POST | /dme/pump-orders/{id}/cancel | Cancel a PENDING_QUALIFICATION or QUALIFIED order with full compensation | Member, CareCoordinator |
| POST | /dme/pump-orders/{id}/lines | Add a compression-garment add-on line (quantity caps enforced) | Member, CareCoordinator |
| GET | /dme/pump-orders/{id}/lines | List an order's lines | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| POST | /dme/prior-authorizations | Submit a prior authorization for a QUALIFIED order that requires one | InsuranceSpecialist |
| GET | /dme/prior-authorizations/{id} | Get one PA | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| GET | /dme/prior-authorizations | List PAs | Member, CareCoordinator, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| POST | /dme/prior-authorizations/{id}/payer-decision | Payer integration endpoint: record APPROVED / DENIED / PENDED decision (from SUBMITTED or APPEALED) | PlatformAdmin |
| POST | /dme/prior-authorizations/{id}/resubmit | Resubmit a PENDED PA (submission_count increments) | InsuranceSpecialist |
| POST | /dme/prior-authorizations/{id}/appeal | Appeal a DENIED PA | InsuranceSpecialist |
| POST | /dme/shipments | Create a shipment for a QUALIFIED pump order (PA gate enforced) or an APPROVED resupply order | WarehouseOperator |
| GET | /dme/shipments/{id} | Get one shipment (tracking) | Member, CareCoordinator, WarehouseOperator, InsuranceSpecialist, PlatformAdmin |
| GET | /dme/shipments | List shipments | Member, CareCoordinator, WarehouseOperator, InsuranceSpecialist, PlatformAdmin |
| POST | /dme/shipments/{id}/advance | Advance carrier status; DELIVERED fires the order delivery cascade (first, non-replacement deliveries only) | WarehouseOperator |
| POST | /dme/claims | Submit a claim for a DELIVERED pump or resupply order (at most one per order) | InsuranceSpecialist |
| GET | /dme/claims/{id} | Get one claim | Member, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| GET | /dme/claims | List claims | Member, InsuranceSpecialist, BillingSpecialist, PlatformAdmin |
| POST | /dme/claims/{id}/remit | Post payer remittance; runs the adjudication waterfall; segregation of duties enforced | BillingSpecialist, PlatformAdmin |
| POST | /dme/claims/{id}/appeal | Appeal a DENIED claim | InsuranceSpecialist |
| POST | /dme/claims/{id}/void | Void an ADJUDICATED claim; reverses deductible and member balance effects | BillingSpecialist |
| GET | /dme/resupply-schedules/{id} | Get one resupply schedule | Member, CareCoordinator, PlatformAdmin |
| GET | /dme/resupply-schedules | List resupply schedules | Member, CareCoordinator, PlatformAdmin |
| PATCH | /dme/resupply-schedules/{id} | Adjust frequency_days or suspend/resume; OCC on schedule version | CareCoordinator |
| POST | /dme/resupply-orders | Request a parts resupply against a schedule; eligibility window, quantity cap, and benefit period enforced; created in APPROVED | Member, CareCoordinator |
| GET | /dme/resupply-orders/{id} | Get one resupply order | Member, CareCoordinator, WarehouseOperator, PlatformAdmin |
| GET | /dme/resupply-orders | List resupply orders | Member, CareCoordinator, WarehouseOperator, PlatformAdmin |
| POST | /dme/resupply-orders/{id}/cancel | Cancel an APPROVED resupply order; rolls back schedule last_fulfilled_date if this was the latest fulfillment | Member, CareCoordinator |
| POST | /dme/warranty-claims | Open a warranty claim on a delivered pump order inside the warranty window | Member, CareCoordinator |
| GET | /dme/warranty-claims/{id} | Get one warranty claim | Member, CareCoordinator, PlatformAdmin |
| GET | /dme/warranty-claims | List warranty claims | Member, CareCoordinator, PlatformAdmin |
| POST | /dme/warranty-claims/{id}/decide | Adjudicate an OPENED warranty claim | PlatformAdmin |
| POST | /dme/warranty-claims/{id}/reopen | Reopen a DENIED warranty claim (max 2 reopens) | Member, CareCoordinator |
| POST | /dme/warranty-claims/{id}/resolve | Resolve an approved claim; APPROVED_REPLACE creates a replacement shipment and may exhaust the replacement budget | PlatformAdmin |
| POST | /dme/_clock/set_current_utc | Set the logical clock (ISO 8601 UTC); startup default 2026-05-01T00:00:00Z; no eager side effects | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_VIOLATION | 403 |
| ERR_VALIDATION | 400 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_POLICY_NOT_FOUND | 404 |
| ERR_PRESCRIPTION_NOT_FOUND | 404 |
| ERR_CATALOG_ITEM_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_PRIOR_AUTH_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_SCHEDULE_NOT_FOUND | 404 |
| ERR_RESUPPLY_ORDER_NOT_FOUND | 404 |
| ERR_WARRANTY_CLAIM_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_PRESCRIPTION_NOT_VERIFIED | 409 |
| ERR_POLICY_NOT_ACTIVE | 409 |
| ERR_SCHEDULE_NOT_ACTIVE | 409 |
| ERR_PRIOR_AUTH_REQUIRED | 409 |
| ERR_PRIOR_AUTH_NOT_REQUIRED | 409 |
| ERR_DUPLICATE_CLAIM | 409 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_PRESCRIPTION_EXPIRED | 422 |
| ERR_BENEFIT_PERIOD_ENDED | 422 |
| ERR_RESUPPLY_WINDOW_NOT_OPEN | 422 |
| ERR_WARRANTY_EXPIRED | 422 |
| ERR_PRIOR_AUTH_EXPIRED | 422 |
| ERR_POLICY_PERIOD_OVERLAP | 409 |
| ERR_PUMP_TYPE_MISMATCH | 422 |
| ERR_INVALID_ITEM_TYPE | 422 |
| ERR_MAX_REOPENS_EXCEEDED | 422 |
| ERR_WARRANTY_REPLACEMENT_EXHAUSTED | 422 |
| ERR_PUMP_ALLOWANCE_EXHAUSTED | 422 |
| ERR_GARMENT_ALLOWANCE_EXCEEDED | 422 |
| ERR_UPGRADE_TIER_NOT_COVERED | 422 |
| ERR_RESUPPLY_QUANTITY_CAP_EXCEEDED | 422 |
| ERR_REMITTANCE_IMBALANCE | 422 |
| ERR_STALE_VERSION | 412 |

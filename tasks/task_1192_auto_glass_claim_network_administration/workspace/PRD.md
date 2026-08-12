# Auto Glass Claim Network API — Product Requirements Document

## 1. Introduction

Auto glass claims sit at the intersection of insurance coverage law, parts logistics, and consumer-protection regulation. A third-party administrator operating a glass-claim network on behalf of carriers must determine coverage and deductibles state by state — including the zero-deductible windshield mandates in force in states such as Florida, Kentucky, and South Carolina — route each claim to a qualified network shop without improperly steering the customer, source OEM or aftermarket glass under negotiated pricing agreements, ensure vehicles equipped with advanced driver-assistance systems are recalibrated after glass replacement, and audit every invoice before money moves. Fraud signals accumulate across a policyholder's claim history, and shoddy workmanship flows back into the network as warranty strikes that can suspend a shop entirely.

This document specifies the API through which the network's participants execute that lifecycle. It governs claim intake with provisional customer-responsibility estimation, coverage verification and deductible determination, customer-choice disclosure, shop selection and scheduling under real bay and mobile-unit capacity constraints, ADAS calibration bookkeeping, invoicing with agreement pricing and audit, fraud-score accumulation and investigation, and warranty rework. Six roles share the platform, and the system enforces segregation of duties between the adjuster who verifies a claim's coverage and the auditor who decides that claim's invoices.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes six distinct roles: `Policyholder`, `ShopOperator`, `ClaimAdjuster`, `NetworkAuditor`, `FraudInvestigator`, and `NetworkAdmin`. Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented in `X-User-Role`. When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting Policyholder; ownership checks on any resource that references a Policyholder compare the resource's foreign-key field — for example a claim's `policyholder_id` — to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `ShopOperator`, `X-User-ID` is the `id` of the acting GlassShop; ownership checks on any resource that references a GlassShop compare the resource's foreign-key field — for example a work order's `shop_id` — to `X-User-ID`. When `X-User-Role` is `ClaimAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The same opaque form applies when `X-User-Role` is `NetworkAuditor`, when it is `FraudInvestigator`, and when it is `NetworkAdmin`: the server may record such an identifier (for example, as `coverage_verified_by_user_id` on a Claim when coverage is verified, or as `audited_by_user_id` on an Invoice when an audit is decided) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every timestamp the server assigns — `created_at` on any resource, `completed_at` on a work order, `filed_at` on a warranty claim, `paid_at` on an invoice — and every duration- or window-based calculation in the system reads a **logical clock**, never the wall clock. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An admin-only test-driving capability, restricted to `NetworkAdmin`, advances the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`. Scheduling windows, the fraud repeat-claim window, the rapid-completion measurement, and warranty filing deadlines are all evaluated against this clock.

### 2.5. Common Resource Properties

All primary resources in the system (Policyholder, StateRegulation, Policy, GlassShop, PartCatalogEntry, Claim, WorkOrder, CalibrationEvent, Invoice, InvoiceLineItem, FraudAlert, and WarrantyClaim) include a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (for example, 2026-05-01T09:15:30.123Z) indicating when the resource was created, stamped from the logical clock.
- **`updated_at` (string):** An ISO 8601 UTC timestamp indicating when the resource was last modified. It is refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments by one with every modification to the resource, including server-initiated cascade mutations.

The ChoiceDisclosureRecord is the sole exception. It is append-only and immutable once created, so it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are represented as integer cents. Wherever a division or a fractional multiplication would otherwise produce a fraction of a cent, the result is rounded half-up to the nearest whole cent. Two rounding disciplines deserve emphasis:

- **Invoice aggregation follows a pinned per-line-first order.** Each line's total is derived from its unit price and quantity before any summation takes place, and the alternative order of summing first and rounding afterward is forbidden. The single rounding point inside invoice aggregation is the tax computation, which is applied once to the summed parts subtotal.
- **Agreement unit prices are rounded per line.** The network-agreement unit price of each invoice line is rounded half-up to whole cents as it is computed, line by line, before any totals are assembled.

Shop audit scores are not money; they are rounded half-up to two decimal places at each update and on each read-time computation.

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the API carry an optimistic-concurrency field; no other endpoint accepts a version field.

A routing decision against a claim must carry `expected_claim_version`, holding the claim `version` the client last observed. If the claim's current `version` has advanced past that value — because a supplement, a cancellation cascade, or an earlier routing decision mutated the claim in between — the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). A routing decision legitimately supersedes any outstanding offered or no-show work order, so a stale write would otherwise succeed and silently supersede on the basis of claim data the client never saw; the 412 rejection is the intended serialization point.

Scheduling or rescheduling a work order must carry `expected_work_order_version`, holding the work order `version` the client last observed. Rescheduling from `SCHEDULED` or `NO_SHOW` is a legitimate forward action, so a second schedule carrying an already-consumed version would otherwise succeed and silently clobber the slot chosen by the earlier write; instead the stale request is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412).

### 2.8. Nested Resource Retrieval and Validation Priority

When an endpoint path contains multiple resource identifiers — for example, an invoice created beneath a work order, or a calibration event beneath a work order — the system validates the existence of each identifier in sequential, left-to-right order. The request is rejected immediately with the 404 error corresponding to the first identifier in the path that does not resolve to an existing resource, before any later identifier or any business rule is evaluated.

Every request is then evaluated against the following ordered cascade, and a failure in an earlier category masks the evaluation of later categories:

1. **Context headers** — presence of `X-User-ID` and `X-User-Role`, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role permission** — the role must be authorized for the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Ownership** — an entity-backed caller may act only on resources it owns: a policyholder on their own claims and the resources derived from them (cancellations, supplements, choice disclosures, warranty filings), and a shop operator on work orders whose `shop_id` matches their identity and the resources derived from those work orders (acceptance, decline, scheduling, no-show, completion, calibration events, invoices, and invoice submission). Violations surface as `ERR_RESOURCE_OWNERSHIP_MISMATCH`.
4. **Existence** — every path and body resource reference must resolve, validated left to right, yielding the appropriate `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_STATE_REGULATION_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CALIBRATION_EVENT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, or `ERR_FRAUD_ALERT_NOT_FOUND`.
5. **State and request shape** — the target resource must be in the state the transition requires (the 409 state-family errors), the optimistic-concurrency version must match where one is defined (`ERR_STALE_CLAIM_VERSION` and `ERR_STALE_WORK_ORDER_VERSION` at HTTP 412), and the payload must be sane: a missing required field, a wrong type, or an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).
6. **Business safety** — ADAS certification, calibration verification, choice-disclosure presence, and segregation of duties.
7. **Capability and uniqueness constraints** — mobile capability, one regulation per state, one active work order per claim, one open warranty claim per work order, suspended policyholders and shops, inactive or ineligible policies, discontinued parts, and mobile-fee gating.
8. **Temporal conflicts** — bay-minute budgets, mobile buffered-interval overlap, calibration-rig overlap, completion before the scheduled start, and the warranty filing window.
9. **Fiscal rules** — billed prices exceeding agreement prices, and audit decisions that fail to account for every line.

### 2.9. Hierarchical Consistency and Cascading Reconciliation

Claims, work orders, invoices, calibration events, and warranty claims form a living hierarchy, and the server keeps it aligned without waiting for explicit client requests on every level. When the last non-terminal work order of a claim falls away, the claim reverts to its verified state and forgets its shop assignment. When a work order completes, the claim rises to reflect completed work; when an invoice is submitted, the claim rises again to reflect that billing is in flight; when the invoice is paid, the claim settles. A rejected invoice denies its claim, and a policyholder's cancellation of a claim cancels every non-terminal work order beneath it, releasing any reserved shop capacity. Each such cascade independently mutates every affected resource, refreshing its `updated_at` and incrementing its `version`.

Two conservation invariants accompany this reconciliation. Shop bay minutes are conserved per shop per calendar date: the minutes available always equal the minutes configured minus the minutes booked, and schedule-then-cancel returns availability to its prior value with zero drift. Money is conserved on every invoice: from the moment of creation, the submitted total always equals the approved total plus the adjustment total, regardless of how many dispute-and-resubmit cycles the invoice passes through.

## 3. Business Logic & Workflows

### 3.1. Network Configuration and Reference Data

A `NetworkAdmin` registers each policyholder with a `full_name`, `email`, `phone`, and residential `state_code` given as a two-letter USPS code. A freshly registered policyholder begins with `status` set to `ACTIVE`, a `fraud_score` of zero, and a `no_show_count` of zero.

State-level glass regulation is reference data. For each state the administrator creates one StateRegulation carrying its `state_code`, the `zero_deductible_windshield` flag (true where state law mandates zero deductible for windshield replacement under comprehensive coverage), an optional `max_deductible_cents` cap (null meaning the state imposes no cap), and `glass_sales_tax_rate_bp`, the sales tax on glass parts expressed in basis points — a value of 560 denotes a 5.60 percent rate. Only one regulation row may exist per state; a second creation for the same `state_code` is rejected with `ERR_DUPLICATE_STATE_REGULATION` (HTTP 409). The regulation list can be filtered by `state_code`, and the usual `limit` and `offset` parameters apply.

Policies bind a policyholder to coverage. The administrator creates a Policy with the owning `policyholder_id` (which must resolve to an existing policyholder, else `ERR_POLICYHOLDER_NOT_FOUND`), the carrier's `policy_number`, the `state_code` the policy is written in, a `coverage_type` of either `COMPREHENSIVE` or `LIABILITY`, the comprehensive `deductible_cents`, and the coverage window given by `effective_start_date` and `effective_end_date`. The `oem_endorsement` flag records whether the policyholder paid for the OEM-parts endorsement that waives the OEM upcharge; it defaults to false when omitted. A policy's `status` is `ACTIVE` on creation and may later become `CANCELLED`. The policy list supports filtering by `policyholder_id` and by `status`.

Glass shops are onboarded with a `shop_name`, home `state_code`, the `service_zip_prefixes` array of ZIP-prefix strings the shop serves, capability flags `mobile_capable` (mobile service vans), `adas_certified` (ADAS recalibration), and `oem_certified` (OEM glass installation), an `agreement_tier` of `PLATINUM`, `PREFERRED`, or `STANDARD`, and capacity parameters `bay_count`, `mobile_unit_count`, and `operating_minutes_per_day` (defaulting to 480 operating minutes per bay per calendar date when omitted). A new shop's `network_status` is `ACTIVE`, its `warranty_strike_count` starts at zero, and both of its audit scores start at 100. The administrator may later adjust a shop's `network_status`, `agreement_tier`, `adas_certified`, or `mobile_capable` through an admin update, which increments the shop's `version`. A shop's work orders can be listed with an optional `status` filter.

The parts catalog is maintained entry by entry. Each PartCatalogEntry carries a `part_number`, a human-readable `part_description`, a `part_category` of `WINDSHIELD`, `SIDE_GLASS`, `REAR_GLASS`, `MOLDING_KIT`, or `CALIBRATION`, a `part_origin` of `OEM` or `AFTERMARKET`, and the `nags_list_price_cents` list price in cents. An entry is created with `status` `AVAILABLE`; the administrator may later update its `nags_list_price_cents` or move its `status` to `DISCONTINUED`, incrementing the entry's `version`. The catalog list supports filtering by `part_number`, `part_category`, and `status`, and every invoice line referencing a given entry remains reachable from the entry itself.

### 3.2. Claim Intake and Coverage Determination

A claim is born when a `Policyholder` files one, supplying the `policy_id` being claimed against, the `incident_state_code` where the loss occurred, the five-digit `service_zip_code` where service is needed, the damaged glass `part_category` (`WINDSHIELD`, `SIDE_GLASS`, or `REAR_GLASS`), the `loss_date`, a free-text `description`, the `requires_adas_calibration` flag, and the intake `estimated_repair_cost_cents`. The filing policyholder's identity is captured from the caller: the claim's `policyholder_id` is set from `X-User-ID`. A policyholder whose `status` is `SUSPENDED` may not file; the attempt is rejected with `ERR_POLICYHOLDER_SUSPENDED` (HTTP 422).

Intake performs two provisional computations, which require the referenced policy to exist (`ERR_POLICY_NOT_FOUND`) and a StateRegulation to exist for the incident state (`ERR_STATE_REGULATION_NOT_FOUND`). First, the deductible determination. The regulation is looked up by the claim's `incident_state_code`. The effective deductible starts as the policy's `deductible_cents` and is reduced to the state cap whenever the state sets one — that is, the effective deductible is the smaller of `deductible_cents` and `max_deductible_cents` whenever the latter is not null. The zero-deductible rule applies when all three conditions hold: the regulation's `zero_deductible_windshield` is true, the claim's `part_category` is `WINDSHIELD`, and the policy's `coverage_type` is `COMPREHENSIVE`. The provisional customer responsibility, stored as `provisional_customer_responsibility_cents`, is zero when the zero-deductible rule applies and otherwise the smaller of the effective deductible and the intake `estimated_repair_cost_cents`; it never exceeds the effective deductible. Second, the repeat-claim fraud signal is evaluated, as described in §3.6. If the policyholder's `fraud_score` is already at least 100 before the new claim's own signals are applied — the boundary is inclusive, so a score of exactly 100 triggers the hold — the new claim is created directly in `FRAUD_HOLD` status instead of `SUBMITTED`, and a `SCORE_THRESHOLD` fraud alert with a zero point contribution is opened against it. Otherwise the claim begins life in `SUBMITTED`.

A `ClaimAdjuster` then verifies coverage, optionally attaching `verification_notes`. Verification requires the claim to be `SUBMITTED` (else `ERR_CLAIM_NOT_SUBMITTED`, HTTP 409), the policy to be `ACTIVE` (else `ERR_POLICY_INACTIVE`, HTTP 422), the policy's `coverage_type` to be `COMPREHENSIVE` (else `ERR_COVERAGE_TYPE_INELIGIBLE`, HTTP 422), and a StateRegulation to exist for the incident state. On success the claim moves `SUBMITTED` → `COVERAGE_VERIFIED`; the final deductible basis is stored in `deductible_applied_cents` as zero under the zero-deductible rule and as the effective deductible otherwise; the adjuster's `X-User-ID` is recorded in `coverage_verified_by_user_id` for later segregation-of-duties enforcement; and the claim's `version` increments. Alternatively, the adjuster may deny a `SUBMITTED` claim outright, supplying a `denial_reason`, moving it `SUBMITTED` → `DENIED`.

The filing policyholder remains free to cancel their own claim while it is `SUBMITTED`, `COVERAGE_VERIFIED`, or `WORK_AUTHORIZED` — any other state is rejected with `ERR_CLAIM_NOT_CANCELLABLE` — and the caller's identity must match the claim's `policyholder_id`, else `ERR_RESOURCE_OWNERSHIP_MISMATCH`. Cancelling from `WORK_AUTHORIZED` cascades: every linked work order in `OFFERED`, `ACCEPTED`, or `SCHEDULED` moves to `CANCELLED`, and any that were scheduled release their reserved capacity.

Verified claims are not frozen. The policyholder may file a supplement with an `additional_damage_description` and a `revised_estimated_repair_cost_cents`, which requires the claim to be `COVERAGE_VERIFIED` (else `ERR_CLAIM_NOT_COVERAGE_VERIFIED`) and the same ownership match. The supplement moves the claim `COVERAGE_VERIFIED` → `SUBMITTED`: the intake estimate is replaced by the revised figure, the provisional customer responsibility is recomputed from it, and the stored `deductible_applied_cents` is reset to null until the adjuster verifies coverage again. This revision loop re-opens a verified claim for re-verification as many times as needed.

### 3.3. Customer Choice Documentation and Shop Routing

Before any routing takes place, the network must document that the customer understood their right to choose a shop. The policyholder creates a ChoiceDisclosureRecord on the claim — ownership of the claim is enforced — supplying the `disclosure_channel` (`PHONE`, `PORTAL`, or `IN_PERSON`), the `shop_solicited` flag indicating whether a shop solicited the customer before or without an insurer referral, an optional `customer_selected_shop_name` naming a shop the customer independently requested, and the `informed_of_network_options` flag confirming the customer was told they may choose any shop. The record is append-only and immutable. When `shop_solicited` is true, a solicitation fraud signal fires immediately, as detailed in §3.6. The disclosures recorded against a claim can be listed by any role.

Routing is performed by a `ClaimAdjuster` creating a routing decision against a `COVERAGE_VERIFIED` claim (else `ERR_CLAIM_NOT_COVERAGE_VERIFIED`). The request must carry `expected_claim_version` per §2.7, and a stale version is rejected with `ERR_STALE_CLAIM_VERSION`. Two gates protect customer choice and workflow integrity: at least one ChoiceDisclosureRecord must already exist for the claim (else `ERR_CHOICE_DISCLOSURE_REQUIRED`, HTTP 422), and no linked work order may currently be in `ACCEPTED` or `SCHEDULED` (else `ERR_ACTIVE_WORK_ORDER_EXISTS`, HTTP 409).

Shop selection then runs the network's selector policy. The eligibility filter admits a shop only when its `network_status` is `ACTIVE`, when at least one of its `service_zip_prefixes` is a prefix of the claim's `service_zip_code`, and when the claim either does not require ADAS calibration or the shop is `adas_certified`. The adjuster may pin the outcome by supplying `requested_shop_id`: a requested shop that does not exist yields `ERR_SHOP_NOT_FOUND`, and one that fails the eligibility filter is rejected with `ERR_SHOP_NOT_ELIGIBLE` (HTTP 422). Absent a requested shop, the eligible pool is ranked by the shop's agreement-tier multiplier in ascending order — `PLATINUM` (0.75) before `PREFERRED` (0.85) before `STANDARD` (0.95) — with ties broken by the shop's `created_at` in ascending order, so the cheapest agreement tier wins. An empty pool is rejected with `ERR_NO_ELIGIBLE_SHOP` (HTTP 422).

A successful routing decision has three visible effects. Every existing linked work order in `OFFERED` or `NO_SHOW` is moved to `SUPERSEDED`, each with its own `version` increment. A new work order is created for the selected shop with `status` `OFFERED` and a null `warranty_claim_id`. The claim itself moves `COVERAGE_VERIFIED` → `WORK_AUTHORIZED`, its `assigned_shop_id` is set to the selected shop, and its `version` increments. The claim list supports reverse lookup by `policyholder_id`, `policy_id`, `assigned_shop_id`, and `status`.

### 3.4. Scheduling, Capacity, and Service Fulfillment

A work order offered to a shop awaits the shop's answer. A `ShopOperator` accepts an `OFFERED` work order — acting only on work orders whose `shop_id` matches their identity — provided the shop's `network_status` is `ACTIVE` (a suspended shop's acceptance is rejected with `ERR_SHOP_SUSPENDED`, HTTP 409) and the work order is in fact `OFFERED` (else `ERR_WORK_ORDER_NOT_OFFERED`). Acceptance moves the work order `OFFERED` → `ACCEPTED`. Declining, with an optional `decline_reason`, moves it `OFFERED` → `DECLINED`; when no other non-terminal work order remains for the claim, the claim bubbles back down from `WORK_AUTHORIZED` to `COVERAGE_VERIFIED` and its `assigned_shop_id` is cleared to null, freeing the adjuster to route again.

Scheduling — whether the first booking from `ACCEPTED`, a reschedule from `SCHEDULED`, or a rebooking after a `NO_SHOW` — is performed by the owning shop operator supplying `service_mode` (`MOBILE` or `IN_SHOP`), `scheduled_start`, and `scheduled_end`, together with `expected_work_order_version` per §2.7; a stale version is rejected with `ERR_STALE_WORK_ORDER_VERSION`. A work order in any state other than `ACCEPTED`, `SCHEDULED`, or `NO_SHOW` cannot be scheduled (`ERR_WORK_ORDER_NOT_SCHEDULABLE`), and `scheduled_end` must be strictly later than `scheduled_start` (`ERR_INVALID_REQUEST`). Two capability gates apply: when the claim's `requires_adas_calibration` is true the shop must be `adas_certified` (else `ERR_ADAS_CERTIFICATION_REQUIRED`, HTTP 422), and a `service_mode` of `MOBILE` requires the shop to be `mobile_capable` (else `ERR_SERVICE_MODE_CAPABILITY_MISMATCH`, HTTP 422).

Two temporal capacity rules then guard the booking. For in-shop service, the total duration in minutes of the shop's non-terminal `SCHEDULED` in-shop work orders whose scheduled start falls on the calendar date of the new `scheduled_start`, plus the duration of the new booking, must not exceed the shop's `bay_count` multiplied by its `operating_minutes_per_day`; overflow is rejected with `ERR_BAY_CAPACITY_EXCEEDED` (HTTP 409). For mobile service, each booking occupies a buffered interval running from its `scheduled_start` to forty-five minutes after its `scheduled_end`; the new buffered interval must overlap fewer of the shop's other non-terminal `SCHEDULED` mobile work orders' buffered intervals than the shop has `mobile_unit_count` — that is, a shop with two vans may run at most two overlapping buffered mobile windows — and a violation is rejected with `ERR_MOBILE_BUFFER_VIOLATION` (HTTP 409). Rescheduling releases the previously reserved capacity and consumes the new slot under the same checks. Anyone can read a shop's computed capacity for a supplied calendar `date`, which answers `bay_minutes_total` (bay count times operating minutes per day), `bay_minutes_booked` (the summed durations of the shop's `SCHEDULED` in-shop work orders starting on that date), `bay_minutes_available` (the total minus the booked minutes), and `mobile_units_total`.

After a scheduled appointment, the shop reports the outcome. Marking a customer no-show requires the work order to be `SCHEDULED` (else `ERR_WORK_ORDER_NOT_SCHEDULED`) and moves it to `NO_SHOW`: the policyholder's `no_show_count` increments by one and the reserved capacity is released. The no-show recovery cycle then allows the shop to schedule again from `NO_SHOW`. Completing the work requires `SCHEDULED` as well, plus two further gates: when the claim requires ADAS calibration, at least one linked CalibrationEvent must be in `VERIFIED` or `WAIVED` (else `ERR_CALIBRATION_NOT_VERIFIED`, HTTP 422), and the logical clock must have reached `scheduled_start` (completing earlier is rejected with `ERR_COMPLETION_BEFORE_SCHEDULED_START`, HTTP 422). Completion stamps `completed_at` from the logical clock, releases the reserved capacity, cascades the claim `WORK_AUTHORIZED` → `WORK_COMPLETED`, evaluates the rapid-completion fraud signal described in §3.6, and — when the work order's `warranty_claim_id` is non-null — cascades that warranty claim from `APPROVED_REWORK` to `REWORK_COMPLETED`. A `ClaimAdjuster` may also cancel any work order in `OFFERED`, `ACCEPTED`, or `SCHEDULED` (else `ERR_WORK_ORDER_NOT_CANCELLABLE`), with an optional `cancel_reason`; a scheduled cancellation releases its capacity, and when no non-terminal work order remains the claim reverts to `COVERAGE_VERIFIED`.

Calibration events are booked beneath a work order by the owning shop, permitted only while the work order is `ACCEPTED` or `SCHEDULED` (else `ERR_WORK_ORDER_NOT_SCHEDULABLE`). Each event supplies a `calibration_type` of `STATIC` or `DYNAMIC` and a rig window given by `scheduled_start` and `scheduled_end`, beginning life in `SCHEDULED`. The shop operates a single calibration rig, so a new event whose half-open window overlaps the half-open window of any other `SCHEDULED` calibration event of the same shop — intervals touching at an endpoint do not overlap — is rejected with `ERR_CALIBRATION_SLOT_CONFLICT` (HTTP 409). Recording the outcome of a `SCHEDULED` event (else `ERR_CALIBRATION_NOT_SCHEDULED`) takes an `outcome` and an optional `report_reference`: an outcome of `VERIFIED` marks a successful calibration, an outcome of `FAILED` leaves the failed event behind (the shop creates a fresh event to retry), and an outcome of `WAIVED` excuses the calibration requirement. `VERIFIED` and `FAILED` may be recorded by the owning shop operator, whose `X-User-ID` must match the parent work order's `shop_id`; `WAIVED` may only be recorded by a `NetworkAuditor`, and any other role attempting it is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. An outcome recorded against a calibration event that does not exist surfaces `ERR_CALIBRATION_EVENT_NOT_FOUND`.

### 3.5. Invoicing, Agreement Pricing, and Audit Settlement

Once a work order is `COMPLETED` — billing earlier is rejected with `ERR_WORK_ORDER_NOT_COMPLETED` — the owning shop creates an invoice, supplying its `line_items`. Each line names its `line_type` (`PART`, `CALIBRATION`, `MOBILE_FEE`, or `MATERIALS`), a `quantity` of at least one, and the shop-billed `unit_price_cents`. `PART` and `CALIBRATION` lines must reference a catalog entry via `part_catalog_entry_id` (null for the other line types), and `PART` lines additionally carry the shop's `origin_claimed` as `OEM` or `AFTERMARKET`. The invoice is created in `DRAFT` status and records its `work_order_id`; every line in turn records the `invoice_id` of the invoice that owns it.

The server prices every line against the network agreement before anything is stored. The shop's `agreement_tier` determines the tier multiplier: 0.75 for `PLATINUM`, 0.85 for `PREFERRED`, and 0.95 for `STANDARD`. For `PART` and `CALIBRATION` lines, the referenced catalog entry must exist (`ERR_PART_NOT_FOUND`) and must still be `AVAILABLE` — billing a `DISCONTINUED` part is rejected with `ERR_PART_DISCONTINUED` (HTTP 422); the line's `agreement_unit_price_cents` is the entry's `nags_list_price_cents` multiplied by the tier multiplier, except that an `OEM` entry takes a multiplier of exactly 1.00 (OEM glass receives no tier discount), rounded half-up to whole cents per line. A `MOBILE_FEE` line is permitted only when the work order's `service_mode` is `MOBILE` (else `ERR_MOBILE_FEE_NOT_ALLOWED`, HTTP 422) and carries a flat `agreement_unit_price_cents` of 5000 cents — no tier multiplier and no tax. A `MATERIALS` line carries an `agreement_unit_price_cents` of 1500 cents multiplied by the tier multiplier, rounded half-up. Whatever the line type, when the billed `unit_price_cents` exceeds the computed `agreement_unit_price_cents` the invoice is rejected with `ERR_LINE_PRICE_EXCEEDS_AGREEMENT` (HTTP 402).

Invoice aggregation then proceeds in the pinned order of §2.6. Each line's `line_total_cents` is its `unit_price_cents` multiplied by its `quantity`, with no further rounding. The parts subtotal is the sum of the `line_total_cents` over lines whose `line_type` is `PART`. The `tax_amount_cents` is that parts subtotal multiplied by the incident state's `glass_sales_tax_rate_bp` and divided by ten thousand, rounded half-up to whole cents — tax is computed once on the summed parts subtotal, and labor, calibration, and fee lines are untaxed. The `submitted_total_cents` is the sum of all line totals plus the tax. At creation the `approved_total_cents` is zero and the `adjustment_total_cents` equals the submitted total, so the conservation invariant of §2.9 holds from the first moment.

Submitting moves the invoice from `DRAFT` to `SUBMITTED`, and resubmission from `DISPUTED` — supplying `revised_line_items` — replaces the line items wholesale, recomputes the agreement prices, the tax, and the submitted total, and resets the approved and adjustment totals to zero and the full submitted amount respectively. Submission requires the invoice to be in `DRAFT` or `DISPUTED` (else `ERR_INVOICE_NOT_SUBMITTABLE`), the acting shop to own the underlying work order, and at least one line item (an empty submission is rejected with `ERR_INVOICE_EMPTY`). On the first submission the claim cascades `WORK_COMPLETED` → `INVOICED`.

Audit is the exclusive province of a `NetworkAuditor`, who decides a `SUBMITTED` invoice (else `ERR_INVOICE_NOT_SUBMITTED`) by supplying an `action` of `APPROVE`, `DISPUTE`, or `REJECT`, optional `adjustment_lines`, and optional `audit_notes`. Segregation of duties is enforced here: the auditor's `X-User-ID` must differ from the claim's `coverage_verified_by_user_id`, so the adjuster who verified the claim's coverage may not audit that claim's invoices; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). For `APPROVE` and `DISPUTE`, the `adjustment_lines` must cover every line item exactly once, and each line's `approved_amount_cents` must not exceed its `line_total_cents`; incomplete coverage or an over-line approval is rejected with `ERR_AUDIT_INCOMPLETE` (HTTP 422). The auditor may also record a corrected `approved_origin` on a line, which overrides the shop's `origin_claimed` whenever it is set.

The three actions diverge in their effects. On `APPROVE`, the invoice becomes `APPROVED`: the `approved_total_cents` is set to the sum of the lines' approved amounts plus the `tax_amount_cents`; the `adjustment_total_cents` becomes the submitted total minus the approved total; the auditor's identifier is stored in `audited_by_user_id`; the shop's rolling audit score is updated per §3.7; and the claim's final settlement fields are computed. The claim's `oem_upcharge_cents` is the sum, over approved `PART` lines whose final origin — the `approved_origin` when set, otherwise the `origin_claimed` — is `OEM` and whose policy does not carry the `oem_endorsement`, of one quarter of each such line's approved amount, each quarter rounded half-up to whole cents per line and then summed; the endorsement waives the upcharge entirely. The `customer_responsibility_cents` is the smaller of the invoice's `approved_total_cents` and the sum of the claim's `deductible_applied_cents` plus its `oem_upcharge_cents` — it is capped at the approved total. The `insurer_payment_cents` is the approved total minus the customer responsibility, floored at zero. On `DISPUTE`, the invoice becomes `DISPUTED`: the proposed approved amounts are recorded on the lines and the adjustment total is computed, but the approved total stays at zero, so the whole submitted amount remains disputed; the auditor's identifier is likewise recorded. The shop may then resubmit with revised lines, repeating the cycle as often as needed. On `REJECT`, the invoice becomes `REJECTED` and the claim cascades `INVOICED` → `DENIED`. Reading an invoice that does not exist surfaces `ERR_INVOICE_NOT_FOUND`, and an invoice's lines remain listable from the invoice.

Payment closes the loop. Paying an invoice requires it to be `APPROVED` (else `ERR_INVOICE_NOT_APPROVED`), stamps `paid_at` from the logical clock, moves the invoice to `PAID`, and cascades the claim `INVOICED` → `SETTLED`.

### 3.6. Fraud Scoring and Investigation

Every policyholder carries a `fraud_score`, an integer tally of fraud signal points that never falls below zero. Three signals feed it, each creating a FraudAlert that records its `policyholder_id`, the triggering `claim_id`, its `alert_type`, and its `score_contribution`, and begins life `OPEN`. The `REPEAT_WINDOW` signal, worth 40 points, fires at claim intake when another claim of the same policyholder exists with a creation timestamp inside the trailing ninety-day window — strictly after the instant ninety days before now and at or before now. The `SOLICITATION` signal, worth 35 points, fires when a choice disclosure is recorded with `shop_solicited` set to true. The `RAPID_COMPLETION` signal, worth 25 points, fires at work-order completion when fewer than forty-five minutes elapsed between `scheduled_start` and `completed_at` and the claim's `part_category` is `WINDSHIELD`.

A threshold gate sits on top of the signals. Whenever a signal pushes a policyholder's score from below 100 to at least 100, an additional `SCORE_THRESHOLD` alert carrying zero points is created alongside it. And as described in §3.2, a policyholder already at or above 100 at intake has the new claim created directly in `FRAUD_HOLD` with its own `SCORE_THRESHOLD` alert.

Investigation is performed by a `FraudInvestigator` resolving an `OPEN` alert (else `ERR_ALERT_NOT_OPEN`, and a missing alert surfaces `ERR_FRAUD_ALERT_NOT_FOUND`), supplying a `resolution` of `CONFIRMED` or `DISMISSED` plus optional `resolution_notes`. A `DISMISSED` resolution reverses the alert's `score_contribution` from the policyholder's `fraud_score`, floored at zero; when the dismissed alert is a `SCORE_THRESHOLD` alert whose linked claim sits in `FRAUD_HOLD`, the claim is released back to `SUBMITTED`. A `CONFIRMED` resolution on a `SCORE_THRESHOLD` alert whose linked claim sits in `FRAUD_HOLD` denies the claim — moving it `FRAUD_HOLD` → `DENIED` — and suspends the policyholder, moving their `status` to `SUSPENDED`, which bars further claim filings. The alert list supports filtering by `policyholder_id`, `claim_id`, and `status`, and is visible to `ClaimAdjuster`, `NetworkAuditor`, `FraudInvestigator`, and `NetworkAdmin` readers.

### 3.7. Warranty Rework and Network Quality

A policyholder who discovers a defect — a leak, wind noise, a calibration fault — files a warranty claim against the original completed work order, supplying an `issue_description`; the filed record keeps that target in its `original_work_order_id`, and claim ownership by the filing policyholder is enforced. Filing requires the work order to be `COMPLETED` (else `ERR_WORK_ORDER_NOT_COMPLETED`; a missing work order surfaces `ERR_WORK_ORDER_NOT_FOUND`) and stamps `filed_at` from the logical clock. The warranty window depends on how the service was delivered: three hundred sixty-five days after completion for `MOBILE` service, seven hundred thirty days for `IN_SHOP` service. Filing at or before the completion timestamp plus the window is allowed — the boundary is inclusive — while filing later is rejected with `ERR_WARRANTY_WINDOW_EXPIRED` (HTTP 422). A second warranty claim while another for the same work order is still `FILED` or `APPROVED_REWORK` is rejected with `ERR_WARRANTY_ALREADY_OPEN` (HTTP 409).

A `NetworkAuditor` decides a `FILED` warranty claim (else `ERR_WARRANTY_NOT_FILED`; a missing one surfaces `ERR_WARRANTY_CLAIM_NOT_FOUND`), supplying a `decision` of `APPROVE_REWORK` or `DENY` and optional `decision_notes`. Denial moves the claim to `DENIED`, a terminal state. Approving rework moves it to `APPROVED_REWORK` and has three effects: a rework work order is created against the same claim and the same shop as the original work order, with its `warranty_claim_id` pointing back to this warranty claim and its `status` `OFFERED`; the responsible shop's `warranty_strike_count` increments by one; and when that count reaches three, the shop's `network_status` is moved to `SUSPENDED`, removing it from selector eligibility and blocking new acceptances. The rework work order then lives the ordinary lifecycle of §3.4, and its completion cascades the warranty claim from `APPROVED_REWORK` to `REWORK_COMPLETED`. The rework work orders spawned by a warranty claim remain listable from it.

Network quality is quantified by two audit scores on each shop, both fed by invoice approvals. Each approval of one of the shop's invoices produces a per-audit event score: the variance ratio is the invoice's `adjustment_total_cents` divided by its `submitted_total_cents` — taken as zero when the submitted total is zero — and the event score is one hundred times one minus that ratio. The `rolling_audit_score` is an exponentially weighted moving average maintained incrementally on every approval in chronological order of the audit decisions (with ties broken by the invoice's own `created_at` in ascending order): it is seven tenths of the previous rolling score plus three tenths of the event score, rounded half-up to two decimal places, starting from an initial previous value of 100. The `period_close_audit_score` is the flat arithmetic mean of all of the shop's per-audit event scores, rounded half-up to two decimal places, computed on read whenever the shop is retrieved, and equal to 100 when the shop has no approved audits yet. The two variants diverge by design: for two audits at event scores 100 then 90, the rolling score lands at 97.0 while the period-close score lands at 95.0, because the rolling variant weights recent audits more heavily and is order-sensitive where the flat mean is not.

## 4. Endpoint Definitions

Operations that create a new resource — registering a policyholder, filing a claim, creating a routing decision's resulting work order, booking a calibration event, creating an invoice, filing a warranty claim — return a `201 Created` status code. Operations that modify an existing resource (state transitions, admin updates, submissions, decisions) and all read operations return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/policyholders` | Register a policyholder | NetworkAdmin |
| GET | `/policyholders/{id}` | Read a policyholder | Any authenticated role |
| POST | `/state-regulations` | Create a state's glass-claim regulation (one per state) | NetworkAdmin |
| GET | `/state-regulations` | List state regulations | Any authenticated role |
| POST | `/policies` | Create a policy for a policyholder | NetworkAdmin |
| GET | `/policies/{id}` | Read a policy | Any authenticated role |
| GET | `/policies` | List policies | Any authenticated role |
| POST | `/glass-shops` | Onboard a network glass shop | NetworkAdmin |
| GET | `/glass-shops/{id}` | Read a shop (including both audit scores) | Any authenticated role |
| PATCH | `/glass-shops/{id}` | Admin update of network status, tier, or certifications | NetworkAdmin |
| GET | `/glass-shops/{id}/work-orders` | List a shop's work orders | Any authenticated role |
| GET | `/glass-shops/{id}/capacity` | Computed capacity read for a calendar date | Any authenticated role |
| POST | `/part-catalog-entries` | Add a part to the catalog | NetworkAdmin |
| GET | `/part-catalog-entries/{id}` | Read a catalog entry | Any authenticated role |
| GET | `/part-catalog-entries` | List catalog entries | Any authenticated role |
| PATCH | `/part-catalog-entries/{id}` | Discontinue a part or update its NAGS price | NetworkAdmin |
| GET | `/part-catalog-entries/{id}/line-items` | Invoice lines referencing this part | Any authenticated role |
| POST | `/claims` | Claim intake; fraud hold applies at high scores | Policyholder |
| GET | `/claims/{id}` | Read a claim (including deductible and settlement fields) | Any authenticated role |
| GET | `/claims` | List claims | Any authenticated role |
| POST | `/claims/{id}/verify-coverage` | Verify coverage and store the final deductible basis | ClaimAdjuster |
| POST | `/claims/{id}/deny` | Deny a submitted claim | ClaimAdjuster |
| POST | `/claims/{id}/cancel` | Policyholder cancels own claim; cascades to work orders | Policyholder |
| POST | `/claims/{id}/supplement` | Supplement a verified claim (revision loop) | Policyholder |
| POST | `/claims/{id}/choice-disclosures` | Document customer choice / anti-steering disclosure | Policyholder |
| GET | `/claims/{id}/choice-disclosures` | List disclosures for a claim | Any authenticated role |
| POST | `/claims/{id}/routing-decisions` | Route the claim to a shop; supersedes stale offers | ClaimAdjuster |
| GET | `/work-orders/{id}` | Read a work order | Any authenticated role |
| GET | `/claims/{id}/work-orders` | List a claim's work orders | Any authenticated role |
| POST | `/work-orders/{id}/accept` | Shop accepts an offered work order | ShopOperator |
| POST | `/work-orders/{id}/decline` | Shop declines an offered work order | ShopOperator |
| POST | `/work-orders/{id}/schedule` | Schedule or reschedule with OCC and capacity checks | ShopOperator |
| POST | `/work-orders/{id}/mark-no-show` | Mark a scheduled appointment as customer no-show | ShopOperator |
| POST | `/work-orders/{id}/complete` | Mark a scheduled work order completed (ADAS gate applies) | ShopOperator |
| POST | `/work-orders/{id}/cancel` | Adjuster cancels a non-terminal work order | ClaimAdjuster |
| POST | `/work-orders/{id}/calibration-events` | Book a calibration on the shop's rig | ShopOperator |
| GET | `/work-orders/{id}/calibration-events` | List calibration events of a work order | Any authenticated role |
| POST | `/calibration-events/{id}/verify` | Record calibration outcome; waiver requires auditor | ShopOperator, NetworkAuditor |
| POST | `/work-orders/{id}/invoices` | Create a DRAFT invoice with line items | ShopOperator |
| GET | `/invoices/{id}` | Read an invoice | Any authenticated role |
| GET | `/work-orders/{id}/invoices` | List invoices of a work order | Any authenticated role |
| GET | `/invoices/{id}/line-items` | List an invoice's line items | Any authenticated role |
| POST | `/invoices/{id}/submit` | Submit a DRAFT invoice or resubmit a DISPUTED one | ShopOperator |
| POST | `/invoices/{id}/audit-decisions` | Approve, dispute, or reject a submitted invoice | NetworkAuditor |
| POST | `/invoices/{id}/pay` | Pay an approved invoice; settles the claim | NetworkAuditor |
| GET | `/fraud-alerts/{id}` | Read a fraud alert | ClaimAdjuster, NetworkAuditor, FraudInvestigator, NetworkAdmin |
| GET | `/fraud-alerts` | List fraud alerts | ClaimAdjuster, NetworkAuditor, FraudInvestigator, NetworkAdmin |
| POST | `/fraud-alerts/{id}/resolve` | Confirm or dismiss an open alert | FraudInvestigator |
| POST | `/work-orders/{id}/warranty-claims` | File a warranty claim against a completed work order | Policyholder |
| GET | `/work-orders/{id}/warranty-claims` | List warranty claims against a work order | Any authenticated role |
| GET | `/warranty-claims/{id}` | Read a warranty claim | Any authenticated role |
| GET | `/warranty-claims/{id}/work-orders` | List rework work orders spawned by a warranty claim | Any authenticated role |
| POST | `/warranty-claims/{id}/decide` | Approve rework or deny a warranty claim | NetworkAuditor |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | NetworkAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_RESOURCE_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_POLICYHOLDER_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_STATE_REGULATION_NOT_FOUND` | 404 Not Found |
| `ERR_SHOP_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CALIBRATION_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_FRAUD_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_COVERAGE_VERIFIED` | 409 Conflict |
| `ERR_CLAIM_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_OFFERED` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_SCHEDULABLE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_SCHEDULED` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_COMPLETED` | 409 Conflict |
| `ERR_INVOICE_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_INVOICE_NOT_APPROVED` | 409 Conflict |
| `ERR_INVOICE_EMPTY` | 409 Conflict |
| `ERR_CALIBRATION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_WARRANTY_NOT_FILED` | 409 Conflict |
| `ERR_ALERT_NOT_OPEN` | 409 Conflict |
| `ERR_STALE_CLAIM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_ADAS_CERTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CALIBRATION_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_CHOICE_DISCLOSURE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SERVICE_MODE_CAPABILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STATE_REGULATION` | 409 Conflict |
| `ERR_ACTIVE_WORK_ORDER_EXISTS` | 409 Conflict |
| `ERR_SHOP_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_SHOP` | 422 Unprocessable Entity |
| `ERR_WARRANTY_ALREADY_OPEN` | 409 Conflict |
| `ERR_POLICYHOLDER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_SHOP_SUSPENDED` | 409 Conflict |
| `ERR_POLICY_INACTIVE` | 422 Unprocessable Entity |
| `ERR_COVERAGE_TYPE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PART_DISCONTINUED` | 422 Unprocessable Entity |
| `ERR_MOBILE_FEE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_BAY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_MOBILE_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_CALIBRATION_SLOT_CONFLICT` | 409 Conflict |
| `ERR_COMPLETION_BEFORE_SCHEDULED_START` | 422 Unprocessable Entity |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_LINE_PRICE_EXCEEDS_AGREEMENT` | 402 Payment Required |
| `ERR_AUDIT_INCOMPLETE` | 422 Unprocessable Entity |

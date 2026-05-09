# Pharma E-Commerce Compliance API — Product Requirements Document

## 1. Introduction

Online pharmaceutical commerce sits at the intersection of consumer convenience and regulated practice: the same checkout flow that lets a customer order a vitamin must, for a prescription drug, also reproduce the controls of a brick-and-mortar pharmacy — prescription verification, pharmacist re-review, controlled-substance quantity caps, real-name verification, cold-chain custody, and adverse-reaction reporting. This document specifies the Pharma E-Commerce Compliance API, the platform on which a regulated pharmaceutical retailer operates that workflow end-to-end.

The system is responsible for the full compliance ledger associated with every drug shipment. It governs catalog admission of new drugs (including national drug code validation, OTC/prescription classification, and special-control tagging for narcotic, psychotropic, and toxic substances); the two-line review process where a prescription is first validated and then a different qualified pharmacist re-reviews the order against drug-interaction and dosage rationality checks; rolling per-customer purchase caps by control category; cold-chain dispatch with temperature monitoring and out-of-range disposal; adverse drug reaction (ADR) intake, deadline-bound regulatory submission, and follow-up tracking; and the periodic qualification review of vendors and pharmacists against business licenses, drug operation permits, and pharmacist certificates. Every state-changing operation produces an immutable audit trail and, where applicable, an idempotent outbound event to the regulatory authority, payment provider, logistics carrier, or electronic-prescription platform.

Because regulated time matters more than wall-clock time, the platform exposes a deterministic logical clock that operators advance explicitly; certificate expiries, qualification reviews, and reporting deadlines are all evaluated against this clock so that the same input sequence produces the same compliance outcome on every run.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply across the entire API surface. The API is mounted under `/pharma-platforms`.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` to identify the acting principal, and `X-User-Role` to declare the operational capacity that principal is acting in. Missing, malformed, or empty headers cause the request to be rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Once headers are present, the server checks the role against the per-endpoint authorization table (see §4); a role that is not on the endpoint's whitelist receives `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognises seven roles, spelled exactly as follows: `PlatformAdmin`, `VendorAdmin`, `PrescriptionReviewer`, `PharmacistReReviewer`, `Pharmacist`, `Customer`, and `RegulatoryGateway`.

The semantics of `X-User-ID` depend on the role:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on audit entries but does not compare it to any entity's `id`.
- When `X-User-Role` is `RegulatoryGateway`, `X-User-ID` is likewise an opaque operator identifier; it is recorded on audit entries but is not compared to any entity row.
- When `X-User-Role` is `VendorAdmin`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` (most importantly, `resubmit-qualification` on a vendor) compare the resource's vendor foreign key to `X-User-ID`.
- When `X-User-Role` is `PrescriptionReviewer`, `PharmacistReReviewer`, or `Pharmacist`, `X-User-ID` is the `id` of the acting `Pharmacist`. The same physical pharmacist may switch between these three role headers across requests, but on a single Prescription/Order pair the pharmacist who approved the prescription and the pharmacist who re-reviews the order must be different `Pharmacist` rows; this segregation-of-duties rule is enforced explicitly via `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (see §3).
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; placing, paying for, or cancelling an order requires `X-User-ID` to equal the `customer_id` on the order.

Generic input validation failures (missing required field, type mismatch, enum value out of set) surface as `ERR_INVALID_REQUEST`. Resource lookups that miss return `ERR_NOT_FOUND` or its subject-specific siblings (e.g., `ERR_PLATFORM_NOT_FOUND`, `ERR_DRUG_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PHARMACIST_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_RULE_NOT_FOUND`).

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Deterministic Platform Clock

All primary, top-level resources — `PharmaPlatform`, `Drug`, `Vendor`, `Pharmacist`, `Customer`, `Prescription`, `PurchaseLimitRule`, `Order`, `PharmacistReview`, `ColdChainShipment`, and `AdverseReactionReport` — carry a standard set of system-managed fields:

- **`id` (string).** A unique, system-minted identifier formatted as a UUID. The id has no type prefix and is generated server-side at creation time.
- **`created_at` (string).** The ISO 8601 UTC timestamp at which the resource was first created, with three fractional digits (millisecond precision). For all primary resources this is taken from the platform clock at the moment of creation.
- **`updated_at` (string).** The ISO 8601 UTC timestamp at which the resource was last modified, with three fractional digits. Any state transition or field mutation refreshes `updated_at`.
- **`version` (integer).** A monotonically increasing integer that starts at the resource's initial mutation count and increases by exactly one with every server-side mutation of the resource. Cascade-driven mutations also bump `version` on the affected row.

Two entities are append-only logs and do not participate in the common-fields convention: `AuditLog` and `ExternalEvent` carry only `id` and `created_at`; they have no `updated_at` and no `version`. `PrescriberDenylistEntry` is similarly append-only with no `updated_at` and no `version`.

The platform exposes a deterministic logical clock, stored on `PharmaPlatform` as `current_clock_iso`. Each platform is created with a `name`, a `jurisdiction` (regulatory jurisdiction code such as `CN` or `US-CA`), and a mock `regulatory_endpoint` identifier; on creation `current_clock_iso` is initialised to `1970-01-01T00:00:00.000Z`. The clock advances only via the dedicated clock-advance capability whose body carries `to_iso`, an ISO 8601 UTC timestamp that must be strictly greater than the current `current_clock_iso`. Advancing the clock is the moment at which all time-driven evaluations occur — vendor qualification expiries, pharmacist certificate expiries, and the auto sweeps described in §3 — so timestamps captured on resources (`paid_at`, `dispatched_at`, `submitted_to_authority_at`, `archived_at`, `reported_at`, etc.) are always taken from `current_clock_iso` rather than from real wall-clock time.

### 2.5. Optimistic Concurrency Control

Mutation endpoints accept an optional `version` field in the request body. When a client supplies `version`, the server compares the supplied integer to the row's current `version`; if they differ, the request is rejected with `ERR_VERSION_MISMATCH` and no state changes. When `version` is omitted, the server processes the mutation without an OCC check. This applies uniformly to every endpoint that targets a specific row by its identifier in the path. Concurrent operations that race for the same state-machine slot have their own dedicated error codes (e.g., `ERR_REVIEW_ALREADY_OPEN` for two simultaneous attempts to open the same order's pharmacist re-review, `ERR_PRESCRIPTION_NOT_IN_REVIEW` for two simultaneous prescription approvals, `ERR_ORDER_NOT_PAYABLE` for a pay/cancel race on the same order, `ERR_DRUG_NOT_PENDING_REVIEW` for shelve/off-shelve races) — see §3 for where each one fires.

### 2.6. Nested Resource Retrieval and Path Validation

The API is hierarchical: every resource lives under a platform, most action endpoints live under an order, and pharmacist reviews live under both. When a path contains multiple identifiers (for example, the path that gets a specific pharmacist review carries `pid`, `orderId`, and `reviewId`), the system validates each identifier in the order they appear in the URL, left-to-right. The first identifier that does not resolve causes the request to be rejected immediately with the corresponding subject-specific not-found code (e.g., `ERR_PLATFORM_NOT_FOUND` first, then `ERR_ORDER_NOT_FOUND`, then `ERR_REVIEW_NOT_FOUND`); the server does not attempt to look up later identifiers once an earlier one has missed.

### 2.7. Hierarchical Consistency and Cascading Side Effects

Every state-changing operation produces a coherent set of mutations across all dependent rows in a single logical step. Off-shelving a drug, suspending a vendor, revoking an approved prescription, rejecting a pharmacist re-review, or disposing a cold-chain shipment all cascade into the orders, shipments, prescriptions, and payment dimensions that depend on them — see §3 for the specific cascade rules. Every cascaded mutation refreshes the affected row's `updated_at` and increments its `version`. Whenever an order's `payment_status` transitions to `REFUNDED` as a downstream effect, the server treats that refund as a fully observable side effect: an `AuditLog` row with `action` equal to `ORDER_REFUNDED` is appended, and an `ExternalEvent` row on `channel` `PAYMENT` with `event_type` `order.refunded` is emitted with a stable `idempotency_key`. The same shape applies to shipment disposal, prescription archival, vendor review-required, and ADR submission — see the per-workflow descriptions in §3.

The system also auto-archives a referenced approved prescription as soon as none of its referencing orders are in a non-terminal state. This evaluation runs at every transition that lands an order in `DELIVERED`, `CANCELLED`, `REJECTED`, or `REFUNDED`; if no order under the prescription remains in `PENDING_REVIEW`, `PHARMACIST_REVIEWING`, `APPROVED`, `DISPENSED`, or `SHIPPED`, the prescription's `status` advances from `APPROVED` to `ARCHIVED`, `archived_at` is set to the platform clock, and an `ExternalEvent` on `channel` `E_PRESCRIPTION_PLATFORM` with `event_type` `prescription.archived` is emitted.

### 2.8. Audit Log and Outbound Event Synchronisation

Every business-significant transition appends a row to `AuditLog`. Each row carries `platform_id`, the polymorphic `subject_type` (one of `PRESCRIPTION`, `ORDER`, `PHARMACIST_REVIEW`, `COLD_CHAIN_SHIPMENT`, `ADVERSE_REACTION_REPORT`, `VENDOR`), the `subject_id`, the discrete `action` name (one of `PRESCRIPTION_APPROVED`, `PRESCRIPTION_REJECTED`, `PRESCRIPTION_REVOKED`, `PHARMACIST_REVIEW_APPROVED`, `PHARMACIST_REVIEW_REJECTED`, `PHARMACIST_REVIEW_REQUEST_CHANGE`, `ORDER_DISPENSED`, `ORDER_SHIPPED`, `ORDER_DELIVERED`, `ORDER_REFUNDED`, `COLD_CHAIN_DISPOSED`, `ADR_SUBMITTED`, `ADR_ARCHIVED`, `VENDOR_SUSPENDED`), the `actor_role` and `actor_id` taken from the request headers (or the literal string `system` for auto transitions), the `occurred_at` timestamp taken from the platform clock, and a `payload` snapshot of the relevant fields at the moment of action.

In parallel, the platform emits outbound `ExternalEvent` rows on four channels: `REGULATORY_AUTHORITY`, `PAYMENT`, `LOGISTICS`, and `E_PRESCRIPTION_PLATFORM`. Each event carries `platform_id`, the `channel`, an `event_type` string (such as `adr.submitted`, `order.paid`, `order.refunded`, `order.shipped`, `order.delivered`, `prescription.approved`, `prescription.revoked`, `prescription.archived`, `vendor.review_required`, `shipment.dispatched`), the `subject_type`, `subject_id`, the `occurred_at` taken from the platform clock, the channel-specific `payload`, and an `idempotency_key`. The idempotency key is a stable string of the form `{event_type}:{subject_id}:{version}`. Two emissions sharing the same `idempotency_key` are deduplicated: the first writer's row stands, the duplicate is silently dropped, and only system-internal inspection of the conflict surfaces `ERR_IDEMPOTENCY_CONFLICT`.

### 2.9. Drug Catalog Classification and Quantities

Drugs are described by structured catalog fields: a `platform_id` (set by the system), a `name` for display, an `ndc` (National Drug Code), a `classification` enum that takes values `OTC` or `PRESCRIPTION`, a `control_category` enum that takes values `NONE`, `NARCOTIC`, `PSYCHOTROPIC_I`, `PSYCHOTROPIC_II`, or `TOXIC`, a boolean `cold_chain_required` (default `false`), an `indications` array of keyword strings, a `contraindications` array of keyword strings drawn from the set `PREGNANCY`, `MINOR`, `RENAL_FAILURE`, `GERIATRIC`, a `vendor_id` foreign key to the supplying vendor, an integer `per_order_qty_cap` (must be at least 1), an integer `per_period_qty_cap`, and a system-managed `status` that takes values `PENDING_REVIEW`, `ON_SHELF`, or `OFF_SHELF`. The `ndc` must match the regular expression `^\d{4,5}-\d{3,4}-\d{1,2}$` — a digit group of 4 or 5 digits, then a digit group of 3 or 4 digits, then a digit group of 1 or 2 digits, separated by hyphens; if the format is wrong the create call is rejected with `ERR_NDC_INVALID_FORMAT`. Within a single platform, two drugs that are not in `OFF_SHELF` may not share the same `ndc`; a duplicate is rejected with `ERR_NDC_DUPLICATE` (the same code surfaces both at create time and at re-shelve time). Any drug whose `control_category` is not `NONE` must have `classification` equal to `PRESCRIPTION`; the mismatch is rejected with `ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION`.

### 2.10. Real-Name Verification and Special-Population Restrictions

Customers carry `platform_id`, the legal `real_name`, a government-issued `id_document_no`, an array of `special_population_flags` drawn from the set `PREGNANCY`, `MINOR`, `RENAL_FAILURE`, `GERIATRIC`, and a boolean `real_name_verified` (default `false`) that becomes `true` only after offline ID verification. For any order that contains at least one prescription drug, the placing customer must have `real_name_verified` equal to `true` and a non-empty `id_document_no`; otherwise the order is rejected with `ERR_REAL_NAME_REQUIRED`. The customer's `special_population_flags` are also the input to two further compliance checks: the contraindication intersection at prescription approval time (`ERR_CONTRAINDICATION_VIOLATION`) and the special-population block at order time (`ERR_SPECIAL_POPULATION_RESTRICTED`). These are described in their respective workflows in §3.

### 2.11. Time-Driven Auto Sweeps

A subset of state transitions is driven not by an explicit operator action but by the platform clock. These transitions are evaluated when, and only when, the clock-advance capability runs. The auto sweep performs the following work in this order: pharmacist certificate expiry (`Pharmacist.qualification_status` `ACTIVE` → `EXPIRED` for every pharmacist whose `certificate_expires_at` is at or before the new clock value), vendor qualification review (`Vendor.qualification_status` `ACTIVE` → `REVIEW_REQUIRED` when the new clock is at or after the earlier of the vendor's `business_license_expires_at` and `drug_operation_permit_expires_at` minus the alert window), and vendor suspension (`REVIEW_REQUIRED` → `SUSPENDED` when the new clock is at or after the later of those two expiry timestamps). Vendor suspension cascades to the vendor's drugs and to in-flight orders, as described in §3.

### 2.12. Monetary Values, Quantities, and Rounding

Prices on order lines are integer cents in the field `unit_price_cents`; quantities on order lines are integers in the field `qty`. The order total is the simple sum of `qty` multiplied by `unit_price_cents` across every line in `items`, accumulated as integer cents. No rounding occurs anywhere in this calculation — the inputs are integers and the output is an integer. Decimal prices are not allowed.

Cold-chain temperatures are recorded as integer tenths of a degree Celsius in the field `celsius_tenths`: a value of `27` means 2.7 °C, and a value of `150` means 15.0 °C. Excursion windows are measured in integer minutes, rounded up. The vendor qualification weighted score is rounded half-up to one decimal place; raw component scores are integers; component days are floored to whole days. The forward-looking ADR reporting deadline is recorded as an ISO 8601 UTC timestamp with three fractional digits.

## 3. Business Logic & Workflows

### 3.1. Vendor Onboarding and Qualification Lifecycle

Each `Vendor` is created with the legal `name`, the `business_license_no` and its `business_license_expires_at` timestamp, and the `drug_operation_permit_no` with its `drug_operation_permit_expires_at` timestamp. A vendor begins life with `qualification_status` equal to `ACTIVE` and `latest_review_submitted_at` unset.

Vendor qualification is governed by a weighted scoring rule that runs both at every clock-advance and at every re-submission. The rule first computes raw days remaining for each of three components: the licence days `L_days`, defined as the number of whole days from `current_clock_iso` to `business_license_expires_at`, floored; the permit days `P_days`, defined the same way against `drug_operation_permit_expires_at`; and the certificate days `C_days`, defined as the smallest such whole-day count across every `Pharmacist` on the same platform (using the pharmacist's `certificate_expires_at`). If the platform has no pharmacists at all, `C_days` is treated as effectively unbounded — interpret this as not contributing to the score.

Each component then contributes a severity score: 0 if its days remaining is at least 90, 1 if days remaining is at least 30 but less than 90, 3 if days remaining is at least 0 but less than 30, and 5 if days remaining is below 0 (already expired). The raw total is the sum of these three component scores, treating an unbounded `C_days` as a contribution of 0. The raw total then determines a tier: the tier is `GREEN` when the raw total is at most 1, `YELLOW` when the raw total is between 2 and 4 inclusive, and `RED` when the raw total is at least 5. Finally, the weighted score is the raw total multiplied by the tier multiplier — 1.0 for `GREEN`, 1.5 for `YELLOW`, 2.0 for `RED` — rounded half-up to one decimal place. The order of evaluation is fixed: the raw total is computed first, the tier is derived from the raw total, and only then is the multiplier applied to that same total. Reversing the order (multiplying first and then bucketing) would yield a different number and is not permitted.

At every clock advance the auto sweep evaluates this rule for each vendor. When a vendor in `qualification_status` `ACTIVE` enters `YELLOW` or `RED`, or equivalently when `current_clock_iso` is at or after the earlier of the vendor's two expiry timestamps minus the alert window of 30 days, the vendor transitions `ACTIVE` → `REVIEW_REQUIRED`. No `AuditLog` row is appended for this transition — the audit `action` `VENDOR_SUSPENDED` is reserved for the harder transition — but an `ExternalEvent` on `channel` `REGULATORY_AUTHORITY` with `event_type` `vendor.review_required` is emitted, with `idempotency_key` of the form `vendor.review_required:{vendor_id}:{version}`. When the clock subsequently reaches the later of the two expiry timestamps, the vendor transitions `REVIEW_REQUIRED` → `SUSPENDED`; this transition appends an `AuditLog` row with `action` `VENDOR_SUSPENDED` and `subject_type` `VENDOR`, and it cascades: every drug of this vendor whose `status` is `ON_SHELF` is moved to `OFF_SHELF`, and that drug-level off-shelving in turn cascades into outstanding orders containing those drugs (see §3.2).

A `VendorAdmin` whose `X-User-ID` equals the vendor's `id` may exit `REVIEW_REQUIRED` or `SUSPENDED` by re-submitting qualification with a new `business_license_expires_at` and a new `drug_operation_permit_expires_at`. Both renewal timestamps must be strictly greater than `current_clock_iso`; otherwise the request is rejected with `ERR_RENEWAL_DATE_NOT_FUTURE`. The vendor's `qualification_status` returns to `ACTIVE` and `latest_review_submitted_at` is set to `current_clock_iso`. Re-submitting qualification on a vendor that is currently `ACTIVE` is rejected with `ERR_VENDOR_NOT_IN_REVIEW`. Note that re-activating a previously `SUSPENDED` vendor does not auto re-shelve that vendor's drugs — they remain `OFF_SHELF` and a `PlatformAdmin` must explicitly re-shelve each one.

### 3.2. Drug Catalog Lifecycle: Shelving, Re-shelving, and Cascading Off-Shelve

A new `Drug` is created in `status` `PENDING_REVIEW`. The validations described in §2.9 — NDC format, NDC uniqueness within the platform among non-`OFF_SHELF` drugs, and the control-category-implies-prescription constraint — apply at create time. A `PlatformAdmin` shelves a drug, transitioning it from `PENDING_REVIEW` to `ON_SHELF`, only if the drug is currently `PENDING_REVIEW` (otherwise `ERR_DRUG_NOT_PENDING_REVIEW`), the drug's vendor has `qualification_status` equal to `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`), the `ndc` is unique among the platform's `ON_SHELF` drugs (otherwise `ERR_NDC_DUPLICATE`), and — when `control_category` is anything other than `NONE` — the `classification` is `PRESCRIPTION` (otherwise `ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION`).

The same shelve capability also re-shelves a drug from `OFF_SHELF` back to `ON_SHELF` provided the drug is currently `OFF_SHELF` (otherwise `ERR_DRUG_NOT_OFF_SHELF` when the caller's intent is a re-shelve) and the vendor is again `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`).

Off-shelving moves an `ON_SHELF` drug to `OFF_SHELF`; the precondition is that the drug be currently `ON_SHELF` (otherwise `ERR_DRUG_NOT_ON_SHELF`). Off-shelving cascades: every outstanding `Order` that contains a line referencing the off-shelved drug and whose `dispensing_status` is `PENDING_REVIEW` or `PHARMACIST_REVIEWING` has its `dispensing_status` driven to `REJECTED`. Any of those orders that were already `PAID` cascade further: their `payment_status` flips from `PAID` to `REFUNDED`, an `AuditLog` row with `action` `ORDER_REFUNDED` is appended, and an `ExternalEvent` on `channel` `PAYMENT` with `event_type` `order.refunded` is emitted (`idempotency_key` of form `order.refunded:{order_id}:{version}`). Each cascaded order has its `updated_at` refreshed and its `version` incremented.

Two simultaneous shelve/off-shelve calls on the same drug serialize on `Drug.status`: the first writer wins, and the loser observes the post-write state and is rejected with `ERR_DRUG_NOT_PENDING_REVIEW`.

### 3.3. Pharmacist Lifecycle

A `Pharmacist` is created with `full_name`, `certificate_no`, `certificate_expires_at`, and an optional `courier_qualified` boolean (default `false`) used by the cold-chain courier check (see §3.7). The pharmacist begins with `qualification_status` equal to `ACTIVE`. When the platform clock advances to or past `certificate_expires_at`, the auto sweep transitions the pharmacist to `EXPIRED`. A `PlatformAdmin` may renew the certificate by supplying a new `certificate_expires_at` strictly greater than the current platform clock (otherwise `ERR_RENEWAL_DATE_NOT_FUTURE`); the pharmacist returns to `ACTIVE`. A `PlatformAdmin` may also suspend a pharmacist directly, transitioning `ACTIVE` to `SUSPENDED`. Any acting pharmacist whose `qualification_status` is not `ACTIVE` is rejected from prescription approval, opening a re-review, and from any pharmacist-review action endpoint with `ERR_PHARMACIST_NOT_ACTIVE`.

### 3.4. Prescription Upload, Review, and Revocation

A prescription is uploaded with a payload containing the `customer_id` of the patient, the `prescriber_name` and `prescriber_license_no` of the prescribing physician, the `image_url` of the uploaded image, the `issued_at` timestamp on which the prescription was written, an integer `validity_days` for which it is valid, and a `drug_items` array whose elements each contain a `drug_id` and a `qty`. On creation, a fresh `Prescription` enters `status` `UPLOADED` and is immediately auto-advanced to `REVIEW_PENDING` by the system after input validation.

A `PrescriptionReviewer` then approves or rejects the document. Approval transitions `REVIEW_PENDING` to `APPROVED` and sets `reviewer_pharmacist_id` to the reviewer's `X-User-ID`. The transition has five preconditions, each tied to its own error code: the acting pharmacist's `qualification_status` must be `ACTIVE` (otherwise `ERR_PHARMACIST_NOT_ACTIVE`); `current_clock_iso` must be strictly less than `issued_at` plus the smaller of `validity_days` and the per-control-category validity-days cap enforced by the server (otherwise `ERR_PRESCRIPTION_EXPIRED`); the prescription's `prescriber_license_no` must not appear on the prescriber denylist (otherwise `ERR_PRESCRIBER_NOT_QUALIFIED`); every `drug_id` in `drug_items` must resolve to a `Drug` whose `status` is `ON_SHELF` and whose `classification` is `PRESCRIPTION` (otherwise `ERR_DRUG_NOT_PRESCRIBABLE`); and for every drug, the intersection of its `contraindications` array with the customer's `special_population_flags` must be empty (otherwise `ERR_CONTRAINDICATION_VIOLATION`). When approval succeeds, the system appends an `AuditLog` row with `action` `PRESCRIPTION_APPROVED` and `subject_type` `PRESCRIPTION`, and emits an `ExternalEvent` on `channel` `E_PRESCRIPTION_PLATFORM` with `event_type` `prescription.approved` and `idempotency_key` of form `prescription.approved:{rx_id}:{version}`.

Rejection transitions `REVIEW_PENDING` to `REJECTED` with no business preconditions beyond the state check, and appends an `AuditLog` row with `action` `PRESCRIPTION_REJECTED`. Both approval and rejection require the prescription to currently be in `REVIEW_PENDING`; calling either on a different state returns `ERR_PRESCRIPTION_NOT_IN_REVIEW`. Two simultaneous approvals on the same prescription serialize on `Prescription.status` (first writer wins); the loser receives `ERR_PRESCRIPTION_NOT_IN_REVIEW`.

A `PrescriptionReviewer` (or a `PlatformAdmin`) may revoke an approved prescription, transitioning `APPROVED` to `REVOKED`, but only if no order in `PHARMACIST_REVIEWING`, `APPROVED`, `DISPENSED`, `SHIPPED`, or `DELIVERED` references the prescription; otherwise the request is rejected with `ERR_PRESCRIPTION_IN_USE`. Revocation appends an `AuditLog` row with `action` `PRESCRIPTION_REVOKED`, emits an `ExternalEvent` on `channel` `E_PRESCRIPTION_PLATFORM` with `event_type` `prescription.revoked`, and cascades: every order in `dispensing_status` `PENDING_REVIEW` that references this prescription is moved to `dispensing_status` `CANCELLED`. Cancelled orders that were `PAID` further cascade to `REFUNDED` per the rules in §2.7.

Once approved, a prescription is auto-archived as soon as no order under it remains in a non-terminal state. The auto-archive evaluation runs whenever any order under the prescription transitions to `DELIVERED`, `CANCELLED`, `REJECTED`, or `REFUNDED`; the prescription must currently be `APPROVED`, and no referencing order may sit in `PENDING_REVIEW`, `PHARMACIST_REVIEWING`, `APPROVED`, `DISPENSED`, or `SHIPPED`. When the condition holds, `archived_at` is set to the platform clock, and an `ExternalEvent` on `channel` `E_PRESCRIPTION_PLATFORM` with `event_type` `prescription.archived` is emitted. Archival is bookkeeping only and does not append an `AuditLog` row.

The prescriber denylist is itself a managed resource: a `PlatformAdmin` (or a `RegulatoryGateway` operator) may add an entry containing a `prescriber_license_no` and a `reason`, and the denylist is consulted both at upload time and at approval time.

### 3.5. Order Placement, Real-Name Verification, and Purchase-Limit Aggregation

Placing an order is a customer action whose payload carries the `customer_id` (which must equal `X-User-ID` for a `Customer`), an optional `prescription_id` (required when at least one item is a prescription drug, null otherwise), and an `items` array with at least one element where each element contains a `drug_id`, a `qty`, and a `unit_price_cents`. The server records `platform_id`, computes `total_amount_cents` as the sum of `qty` multiplied by `unit_price_cents` over every line (integer arithmetic, no rounding), and computes `cold_chain_required` as true if and only if at least one item's drug has `cold_chain_required` equal to true. New orders begin with `dispensing_status` equal to `PENDING_REVIEW` and `payment_status` equal to `UNPAID`; `paid_at`, `pharmacist_review_id`, and `cold_chain_shipment_id` are all unset.

When any item is a prescription drug, the customer must have `real_name_verified` equal to true and a non-empty `id_document_no` (otherwise `ERR_REAL_NAME_REQUIRED`).

The order then runs the purchase-limit aggregation. The platform stores a set of `PurchaseLimitRule` rows; each rule is keyed on a `control_category` and carries a `window_days` integer, a `max_units_per_window` integer, and a `blocks_special_populations` array of population flags. For each line in the proposed order the server identifies the rule whose `control_category` matches the line's `drug.control_category`; if no such rule exists for that category, the line is exempt from the aggregation portion of the check.

The aggregation runs three checks in this fixed order: per-order cap first, special-population block second, rolling-window aggregation third.

1. **Per-order cap.** For each line, `qty` must not exceed the line's drug's `per_order_qty_cap`; otherwise the order is rejected with `ERR_PURCHASE_LIMIT_EXCEEDED`.
2. **Special-population block.** For each line whose category is governed by a rule, the intersection of the customer's `special_population_flags` with that rule's `blocks_special_populations` must be empty; otherwise the order is rejected with `ERR_SPECIAL_POPULATION_RESTRICTED`.
3. **Rolling-window aggregation.** For each governed line, the server computes the window start as `current_clock_iso` minus the rule's `window_days` days. It then sums, in chronological order of `paid_at`, the `qty` of every line on every prior order that belongs to the same customer, has `payment_status` equal to `PAID`, has `paid_at` greater than or equal to the window start and strictly less than `current_clock_iso` (the window is closed at the left and open at the right), and whose drug shares the same `control_category` as the line under evaluation. To this existing total the server adds the proposed total — the sum of `qty` over every line in the new order that shares the same `control_category`. If the existing-plus-proposed total is strictly greater than the rule's `max_units_per_window`, the order is rejected with `ERR_PURCHASE_LIMIT_EXCEEDED`. The chronological summation is observable only in the determinism of which control category surfaces in the rejection message when more than one category would violate; the comparison itself is a single threshold check. Past orders that are `REFUNDED`, `CANCELLED`, or `REJECTED` are not counted; orders that are `UNPAID` are also not counted regardless of dispensing state.

A `Customer` may pay an `UNPAID` order, transitioning `payment_status` to `PAID`, only when `dispensing_status` is `PENDING_REVIEW`, `PHARMACIST_REVIEWING`, or `APPROVED` — that is, not in `REJECTED` or `CANCELLED`, and not already `PAID` or `REFUNDED` (otherwise `ERR_ORDER_NOT_PAYABLE`). When at least one line is a prescription drug, the order's `prescription_id` must be set and the referenced `Prescription.status` must be `APPROVED`; otherwise `ERR_PRESCRIPTION_NOT_APPROVED`. Successful payment sets `paid_at` to `current_clock_iso` and emits an `ExternalEvent` on `channel` `PAYMENT` with `event_type` `order.paid` and `idempotency_key` `order.paid:{order_id}:{version}`. Payment becoming `REFUNDED` is always a system-driven cascade — there is no direct refund endpoint; it occurs whenever a `PAID` order's `dispensing_status` flips to `REJECTED` or `CANCELLED`. The refund cascade appends an `AuditLog` row with `action` `ORDER_REFUNDED` and `subject_type` `ORDER`, and emits an `ExternalEvent` on `channel` `PAYMENT` with `event_type` `order.refunded` and `idempotency_key` `order.refunded:{order_id}:{version}`.

A `Customer` may cancel an order only while `dispensing_status` is `PENDING_REVIEW` (otherwise `ERR_ORDER_NOT_CANCELLABLE`). Cancellation drives `dispensing_status` to `CANCELLED`; if the order was `PAID`, the refund cascade described above runs, and the prescription auto-archive evaluation also runs.

A pay/cancel race on the same `PENDING_REVIEW` order serializes on the combination of `Order.dispensing_status` and `Order.payment_status`: exactly one operation wins, and the loser receives `ERR_ORDER_NOT_PAYABLE`.

A `PlatformAdmin` may also create or update purchase-limit rules: rule creation supplies the `control_category`, the `window_days`, the `max_units_per_window`, and the `blocks_special_populations` array, and rule deletion removes a rule by its identifier.

### 3.6. Pharmacist Re-Review: Segregation of Duties and Revision Cycles

Once an order with a prescription line is in `dispensing_status` `PENDING_REVIEW`, a `PharmacistReReviewer` opens a second-line review with a payload containing the `assigned_pharmacist_id` of the pharmacist who will conduct the review. This action transitions the order's `dispensing_status` from `PENDING_REVIEW` to `PHARMACIST_REVIEWING`, creates a fresh `PharmacistReview` row directly in `status` `IN_REVIEW` (the nominal `PENDING` state is not externally observable), and stores the new review's `id` on the order's `pharmacist_review_id`. The `PharmacistReview` row carries `platform_id`, `order_id`, `assigned_pharmacist_id`, the boolean re-review checks `interaction_check_passed` and `dosage_rationality_passed` (initially unset), `decision_notes` (a free-form string used at reject and request-change time), and a `revision_count` integer that starts at 0.

Opening a re-review has six preconditions. The order's `dispensing_status` must be `PENDING_REVIEW` (otherwise `ERR_ORDER_NOT_REVIEWABLE`). When any line is a prescription drug, the referenced `Prescription.status` must be `APPROVED` (otherwise `ERR_PRESCRIPTION_NOT_APPROVED`). The acting pharmacist's `X-User-ID` must be different from the prescription's `reviewer_pharmacist_id` (otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION`); this is the same first-line-versus-second-line separation enforced again at re-review approval time. The acting pharmacist's `qualification_status` must be `ACTIVE` (otherwise `ERR_PHARMACIST_NOT_ACTIVE`). The purchase-limit aggregation described in §3.5 must pass at this point too (otherwise `ERR_PURCHASE_LIMIT_EXCEEDED`). The special-population block must pass (otherwise `ERR_SPECIAL_POPULATION_RESTRICTED`). Two `PharmacistReReviewer` operators racing to open a re-review on the same order serialize first-writer-wins on the order's `pharmacist_review_id` field; the loser receives `ERR_REVIEW_ALREADY_OPEN`.

From `IN_REVIEW`, the assigned pharmacist may approve, reject, or request changes:

- **Approve.** The approve action requires the review to be currently `IN_REVIEW` (otherwise `ERR_REVIEW_NOT_IN_REVIEW`); the request body must set both `interaction_check_passed` and `dosage_rationality_passed` to true (otherwise `ERR_REVIEW_CHECKS_FAILED`); `X-User-ID` must equal the review's `assigned_pharmacist_id` (otherwise `ERR_REVIEWER_MISMATCH`); `X-User-ID` must still be different from the prescription's `reviewer_pharmacist_id` (otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION`); and the acting pharmacist must still be `ACTIVE` (otherwise `ERR_PHARMACIST_NOT_ACTIVE`). The `decision_notes` field is optional on approve. Approval transitions the review to `APPROVED`, cascades the order's `dispensing_status` from `PHARMACIST_REVIEWING` to `APPROVED`, and appends an `AuditLog` row with `action` `PHARMACIST_REVIEW_APPROVED`.
- **Reject.** The reject action requires the review to be `IN_REVIEW` (otherwise `ERR_REVIEW_NOT_IN_REVIEW`), `decision_notes` whose string length is at least 10 (otherwise `ERR_REVIEW_NOTES_TOO_SHORT`), and `X-User-ID` equal to `assigned_pharmacist_id` (otherwise `ERR_REVIEWER_MISMATCH`). Rejection transitions the review to `REJECTED`, cascades the order's `dispensing_status` to `REJECTED`, and — if the order's `payment_status` was `PAID` — runs the refund cascade (`payment_status` to `REFUNDED`, `AuditLog` `ORDER_REFUNDED`, `ExternalEvent` `order.refunded`). It also appends an `AuditLog` row with `action` `PHARMACIST_REVIEW_REJECTED`.
- **Request change.** The request-change action requires the review to be `IN_REVIEW` (otherwise `ERR_REVIEW_NOT_IN_REVIEW`), `decision_notes` whose string length is at least 10 (otherwise `ERR_REVIEW_NOTES_TOO_SHORT`), and the review's `revision_count` to be strictly less than the maximum of 2 revisions (otherwise `ERR_REVIEW_MAX_REVISIONS`). The transition moves the review to `REQUEST_CHANGE` and appends an `AuditLog` row with `action` `PHARMACIST_REVIEW_REQUEST_CHANGE`.
- **Resume.** From `REQUEST_CHANGE`, the assigned pharmacist may resume the review, returning it to `IN_REVIEW`. The action requires the review to currently be `REQUEST_CHANGE` (otherwise `ERR_REVIEW_NOT_IN_REQUEST_CHANGE`) and `X-User-ID` equal to `assigned_pharmacist_id` (otherwise `ERR_REVIEWER_MISMATCH`). Resuming bumps `revision_count` upward by exactly one. The cycle `REQUEST_CHANGE → IN_REVIEW → ... → REQUEST_CHANGE` may run at most twice before subsequent request-change attempts are rejected by the revision cap.

When the review's `status` flips to `APPROVED`, the order's `dispensing_status` advances from `PHARMACIST_REVIEWING` to `APPROVED` automatically. When the review's `status` flips to `REJECTED`, the order's `dispensing_status` advances to `REJECTED` automatically and — if `payment_status` was `PAID` — the refund cascade runs; if the prescription's only outstanding referencing order was this one, the prescription auto-archive evaluation also runs. Two pharmacist-review action endpoints racing on the same review serialize on `PharmacistReview.status` via the version field; exactly one transition wins, and the loser receives `ERR_REVIEW_NOT_IN_REVIEW`.

After a review is `APPROVED`, a `Pharmacist` (or the same `PharmacistReReviewer` operating in pharmacist capacity) dispenses the order, transitioning `dispensing_status` from `APPROVED` to `DISPENSED`. The dispense action requires `dispensing_status` equal to `APPROVED` (otherwise `ERR_ORDER_NOT_APPROVED`) and `payment_status` equal to `PAID` (otherwise `ERR_ORDER_NOT_PAID`); successful dispense appends an `AuditLog` row with `action` `ORDER_DISPENSED`.

### 3.7. Cold-Chain Dispatch, Temperature Excursions, and Disposal

When an order's `cold_chain_required` flag is true, fulfillment requires a `ColdChainShipment`. A `PlatformAdmin` dispatches a shipment with a payload containing the `order_id`, the `courier_pharmacist_id` of the carrier, and a `device_id` identifying the temperature-monitoring device. The shipment may only be created against an order whose `cold_chain_required` is true and whose `dispensing_status` is `APPROVED` or `DISPENSED` (otherwise `ERR_COLD_CHAIN_NOT_APPLICABLE`). The pharmacist named in `courier_pharmacist_id` must have both `courier_qualified` equal to true and `qualification_status` equal to `ACTIVE`; otherwise the dispatch is rejected with `ERR_COURIER_NOT_QUALIFIED`. On successful dispatch, the shipment enters `status` `DISPATCHED`, `dispatched_at` is set to `current_clock_iso`, and the order's `cold_chain_shipment_id` is set to the new shipment.

A shipment carries an append-only `temperature_readings` array whose elements each contain a `recorded_at` ISO 8601 timestamp and an integer `celsius_tenths` (degrees Celsius times ten). Each appended reading triggers a recompute of the integer `excursion_score`. The score is computed by sorting the readings ascending by `recorded_at`, then for each reading deriving a per-reading severity and a per-reading window length, multiplying them, and summing. The severity for a single reading is 0 when `celsius_tenths` is between 20 and 80 inclusive (the safe band of 2.0 °C through 8.0 °C); for any reading whose `celsius_tenths` is below 20 or above 80, the severity is 5 if `celsius_tenths` is below 0 or above 150 (the critical band of below 0 °C or above 15 °C), and 1 otherwise. The window length for the i-th reading (zero-indexed) is, for every reading except the last, the difference in seconds between the next reading's `recorded_at` and this reading's `recorded_at`, divided by 60, rounded up to the next whole number, and clamped to be at least 1; for the last reading the window length is exactly 1. The per-reading score is the integer product of severity and window length. The shipment's `excursion_score` is the sum of these per-reading scores across all readings. The order is fixed: the per-reading product is always computed first per reading, and only then are the per-reading scores summed. Multiplying total severity by total window length (in either direction) is forbidden — it produces a different number for the same input.

A shipment moves from `DISPATCHED` to `IN_TRANSIT` either as a system cascade when the order ships, or directly via a dedicated `PlatformAdmin` capability provided for test access. From `IN_TRANSIT`, the shipment moves to `DELIVERED` automatically when the order's deliver action succeeds — but only if `excursion_score` is at most the disposal threshold of 30. If `excursion_score` is strictly greater than that threshold, a `PlatformAdmin` must dispose the shipment instead: the dispose action requires the shipment to currently be in `IN_TRANSIT` or `DISPATCHED` (otherwise `ERR_SHIPMENT_NOT_DISPOSABLE`) and `excursion_score` to be strictly greater than 30 (otherwise `ERR_DISPOSAL_NOT_JUSTIFIED`). Disposal moves the shipment to `DISPOSED`, appends an `AuditLog` row with `action` `COLD_CHAIN_DISPOSED`, drives the order's `dispensing_status` to `REJECTED`, and runs the refund cascade if `payment_status` was `PAID`.

A `PlatformAdmin` ships an order, transitioning `dispensing_status` from `DISPENSED` to `SHIPPED`, only if the order is currently `DISPENSED` (otherwise `ERR_ORDER_NOT_DISPENSED`) and, when `cold_chain_required` is true, a `ColdChainShipment` for the order exists with `status` `DISPATCHED` (otherwise `ERR_COLD_CHAIN_SHIPMENT_REQUIRED`). The transition appends an `AuditLog` row with `action` `ORDER_SHIPPED` and emits an `ExternalEvent` on `channel` `LOGISTICS` with `event_type` `order.shipped`; if a cold-chain shipment exists, that shipment's `status` cascades from `DISPATCHED` to `IN_TRANSIT`.

Delivery moves `dispensing_status` from `SHIPPED` to `DELIVERED`. The order must be currently `SHIPPED` (otherwise `ERR_ORDER_NOT_SHIPPED`); if `cold_chain_required` is true, the linked shipment's `status` must be in `IN_TRANSIT` or `DELIVERED` and its `excursion_score` must be at most 30 (otherwise `ERR_COLD_CHAIN_OUT_OF_RANGE`). Successful delivery appends an `AuditLog` row with `action` `ORDER_DELIVERED`, emits an `ExternalEvent` on `channel` `LOGISTICS` with `event_type` `order.delivered`, cascades a still-`IN_TRANSIT` shipment to `DELIVERED`, and triggers the prescription auto-archive evaluation: if every sibling order under the same prescription is in a terminal state, the prescription transitions from `APPROVED` to `ARCHIVED`.

### 3.8. Adverse Drug Reaction Reporting and Deadlines

An `AdverseReactionReport` is created either by a `Customer` reporting their own experience or by a `PharmacistReReviewer` recording a clinical observation. The create payload carries the `drug_id` implicated in the reaction, the `customer_id` of the patient, an optional `order_id` for the originating order, the `reporter_kind` enum (`PATIENT` or `PHARMACIST`), and the initial `severity` (`NON_SERIOUS` or `SERIOUS`). On creation the report enters `status` `REPORTED`, `reported_at` is set to `current_clock_iso`, and `reporting_deadline_at` is computed forward-looking from `reported_at`: a `SERIOUS` report's deadline is `reported_at` plus 24 hours, and a `NON_SERIOUS` report's deadline is `reported_at` plus 15 days.

A `PharmacistReReviewer` may escalate a report's `severity` from `NON_SERIOUS` to `SERIOUS` after creation. The deadline is recomputed under the forward-looking convention: it remains anchored at the original `reported_at` and is recomputed to `reported_at` plus 24 hours; the moment of escalation does not extend the clock. As a consequence, if 24 hours have already elapsed since the original `reported_at`, the report is already past its deadline and a subsequent submit will fail.

Submission transitions a report from `REPORTED` to `SUBMITTED`. The action requires `status` equal to `REPORTED` (otherwise `ERR_REPORT_NOT_REPORTED`) and `current_clock_iso` strictly less than `reporting_deadline_at` (the grace allowance is 0 hours, so the deadline is hard); a submission past the deadline is rejected with `ERR_REPORTING_DEADLINE_PASSED`. Successful submission sets `submitted_to_authority_at` to `current_clock_iso`, sets `follow_up_due_at` to `submitted_to_authority_at` plus 7 days when `severity` is `SERIOUS` (and leaves it unset for non-serious reports), appends an `AuditLog` row with `action` `ADR_SUBMITTED`, and emits an `ExternalEvent` on `channel` `REGULATORY_AUTHORITY` with `event_type` `adr.submitted` and `idempotency_key` `adr.submitted:{report_id}:{version}`. Immediately after `SUBMITTED`, a `SERIOUS` report is auto-advanced to `FOLLOW_UP_PENDING` by the system.

Acknowledgement is the regulatory return path. A `RegulatoryGateway` operator may transition a `SUBMITTED` report to `ACKNOWLEDGED` only when its `severity` is `NON_SERIOUS`; serious reports must transit through `FOLLOW_UP_PENDING` and may not be acknowledged directly (otherwise `ERR_REPORT_REQUIRES_FOLLOW_UP`).

Archival is the terminal step. A `PharmacistReReviewer` archives a report: from `FOLLOW_UP_PENDING` (the path for serious reports) the action requires the report's `status` to be in `FOLLOW_UP_PENDING` or `ACKNOWLEDGED` (otherwise `ERR_REPORT_NOT_ARCHIVABLE`) and, when `severity` is `SERIOUS`, `current_clock_iso` to be at or after `follow_up_due_at` (otherwise `ERR_FOLLOW_UP_INCOMPLETE`); from `ACKNOWLEDGED` (the path for non-serious reports) the action requires `severity` equal to `NON_SERIOUS` (otherwise `ERR_REPORT_NOT_ARCHIVABLE`). On success, `archived_at` is set to `current_clock_iso` and an `AuditLog` row with `action` `ADR_ARCHIVED` is appended.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (such as a platform, drug, vendor, pharmacist, customer, prescription, order, or pharmacist review) return a `201 Created` status code. Operations that modify an existing resource — including state-machine transitions, cascade-driving actions, and clock advances — return a `200 OK` status code, except for resource deletion which returns `204 No Content`. Refer back to §3 for each endpoint's exact request body, response cascades, and trigger conditions.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/pharma-platforms` | Create a platform | PlatformAdmin |
| GET    | `/pharma-platforms/{pid}` | Get a platform | PlatformAdmin, VendorAdmin, PrescriptionReviewer, PharmacistReReviewer, Customer, RegulatoryGateway |
| POST   | `/pharma-platforms/{pid}/_clock/advance` | Advance the deterministic platform clock; runs auto sweeps | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/drugs` | Create a drug (status starts `PENDING_REVIEW`) | PlatformAdmin, VendorAdmin |
| GET    | `/pharma-platforms/{pid}/drugs` | List drugs (filter by status, classification, control category) | PlatformAdmin, VendorAdmin, PrescriptionReviewer, PharmacistReReviewer, Customer, RegulatoryGateway |
| GET    | `/pharma-platforms/{pid}/drugs/{drugId}` | Get a drug | PlatformAdmin, VendorAdmin, PrescriptionReviewer, PharmacistReReviewer, Customer, RegulatoryGateway |
| POST   | `/pharma-platforms/{pid}/drugs/{drugId}/shelve` | Shelve or re-shelve a drug | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/drugs/{drugId}/off-shelve` | Off-shelve a drug; cascades to outstanding orders | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/vendors` | Create a vendor | PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/vendors` | List vendors | PlatformAdmin, VendorAdmin, RegulatoryGateway |
| GET    | `/pharma-platforms/{pid}/vendors/{vendorId}` | Get a vendor | PlatformAdmin, VendorAdmin, RegulatoryGateway |
| POST   | `/pharma-platforms/{pid}/vendors/{vendorId}/resubmit-qualification` | Re-submit licence and permit renewal dates; returns vendor to `ACTIVE` | VendorAdmin |
| POST   | `/pharma-platforms/{pid}/pharmacists` | Create a pharmacist | PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/pharmacists` | List pharmacists | PlatformAdmin, VendorAdmin, PharmacistReReviewer, PrescriptionReviewer |
| GET    | `/pharma-platforms/{pid}/pharmacists/{pharmacistId}` | Get a pharmacist | PlatformAdmin, VendorAdmin, PharmacistReReviewer, PrescriptionReviewer |
| POST   | `/pharma-platforms/{pid}/pharmacists/{pharmacistId}/renew-certificate` | Renew a pharmacist certificate (`EXPIRED` → `ACTIVE`) | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/pharmacists/{pharmacistId}/suspend` | Suspend a pharmacist (`ACTIVE` → `SUSPENDED`) | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/customers` | Create a customer | PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/customers/{customerId}` | Get a customer | PlatformAdmin, Customer |
| PATCH  | `/pharma-platforms/{pid}/customers/{customerId}` | Update customer special-population flags or real-name verification | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/prescriber-denylist` | Add a prescriber to the denylist | PlatformAdmin, RegulatoryGateway |
| GET    | `/pharma-platforms/{pid}/prescriber-denylist` | List denylist entries | PlatformAdmin, PrescriptionReviewer, RegulatoryGateway |
| POST   | `/pharma-platforms/{pid}/purchase-limit-rules` | Create a per-category purchase rule | PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/purchase-limit-rules` | List purchase rules | PlatformAdmin, PrescriptionReviewer, PharmacistReReviewer |
| DELETE | `/pharma-platforms/{pid}/purchase-limit-rules/{ruleId}` | Delete a purchase rule | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/prescriptions` | Upload a prescription (auto-advances `UPLOADED` → `REVIEW_PENDING`) | Customer, PrescriptionReviewer |
| GET    | `/pharma-platforms/{pid}/prescriptions/{rxId}` | Get a prescription | Customer, PrescriptionReviewer, PharmacistReReviewer, RegulatoryGateway, PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/prescriptions/{rxId}/approve` | Approve a prescription (`REVIEW_PENDING` → `APPROVED`) | PrescriptionReviewer |
| POST   | `/pharma-platforms/{pid}/prescriptions/{rxId}/reject` | Reject a prescription (`REVIEW_PENDING` → `REJECTED`) | PrescriptionReviewer |
| POST   | `/pharma-platforms/{pid}/prescriptions/{rxId}/revoke` | Revoke an approved prescription | PrescriptionReviewer, PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/orders` | Place an order; runs purchase-limit checks | Customer |
| GET    | `/pharma-platforms/{pid}/orders/{orderId}` | Get an order | Customer, PlatformAdmin, PharmacistReReviewer, RegulatoryGateway |
| GET    | `/pharma-platforms/{pid}/orders` | List orders | PlatformAdmin, RegulatoryGateway |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/pay` | Pay an order (`UNPAID` → `PAID`) | Customer |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/cancel` | Cancel a `PENDING_REVIEW` order | Customer |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/open-pharmacist-review` | Open second-line pharmacist review (`PENDING_REVIEW` → `PHARMACIST_REVIEWING`) | PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/dispense` | Dispense an order (`APPROVED` → `DISPENSED`) | Pharmacist, PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/ship` | Ship an order (`DISPENSED` → `SHIPPED`); auto-advances cold-chain shipment | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/deliver` | Deliver an order (`SHIPPED` → `DELIVERED`) | PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/orders/{orderId}/pharmacist-reviews/{reviewId}` | Get a pharmacist review | PharmacistReReviewer, PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/pharmacist-reviews/{reviewId}/approve` | Approve a review (`IN_REVIEW` → `APPROVED`) | PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/pharmacist-reviews/{reviewId}/reject` | Reject a review (`IN_REVIEW` → `REJECTED`) | PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/pharmacist-reviews/{reviewId}/request-change` | Request changes (`IN_REVIEW` → `REQUEST_CHANGE`) | PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/orders/{orderId}/pharmacist-reviews/{reviewId}/resume` | Resume after changes (`REQUEST_CHANGE` → `IN_REVIEW`) | PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/cold-chain-shipments` | Dispatch a cold-chain shipment for an `APPROVED` or `DISPENSED` order | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/cold-chain-shipments/{shipmentId}/readings` | Append a temperature reading; recomputes excursion score | PlatformAdmin, Pharmacist |
| POST   | `/pharma-platforms/{pid}/cold-chain-shipments/{shipmentId}/mark-in-transit` | Move a dispatched shipment to `IN_TRANSIT` directly | PlatformAdmin |
| POST   | `/pharma-platforms/{pid}/cold-chain-shipments/{shipmentId}/dispose` | Dispose a shipment when excursion score exceeds threshold | PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/cold-chain-shipments/{shipmentId}` | Get a shipment | PlatformAdmin, Pharmacist, RegulatoryGateway |
| POST   | `/pharma-platforms/{pid}/adverse-reactions` | Create an ADR (`REPORTED`); deadline computed | Customer, PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/adverse-reactions/{reportId}/escalate` | Escalate severity from `NON_SERIOUS` to `SERIOUS` | PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/adverse-reactions/{reportId}/submit` | Submit an ADR (`REPORTED` → `SUBMITTED`) | PharmacistReReviewer |
| POST   | `/pharma-platforms/{pid}/adverse-reactions/{reportId}/acknowledge` | Acknowledge a non-serious ADR (`SUBMITTED` → `ACKNOWLEDGED`) | RegulatoryGateway |
| POST   | `/pharma-platforms/{pid}/adverse-reactions/{reportId}/archive` | Archive an ADR | PharmacistReReviewer |
| GET    | `/pharma-platforms/{pid}/adverse-reactions/{reportId}` | Get an ADR | PharmacistReReviewer, RegulatoryGateway, PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/adverse-reactions` | List ADRs | PharmacistReReviewer, RegulatoryGateway, PlatformAdmin |
| GET    | `/pharma-platforms/{pid}/audit-logs` | List audit log entries | PlatformAdmin, RegulatoryGateway |
| GET    | `/pharma-platforms/{pid}/external-events` | List external sync events | PlatformAdmin, RegulatoryGateway |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PLATFORM_NOT_FOUND` | 404 |
| `ERR_DRUG_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_PHARMACIST_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_RULE_NOT_FOUND` | 404 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
| `ERR_NDC_INVALID_FORMAT` | 400 |
| `ERR_NDC_DUPLICATE` | 409 |
| `ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION` | 400 |
| `ERR_DRUG_NOT_PENDING_REVIEW` | 409 |
| `ERR_DRUG_NOT_ON_SHELF` | 409 |
| `ERR_DRUG_NOT_OFF_SHELF` | 409 |
| `ERR_DRUG_NOT_PRESCRIBABLE` | 422 |
| `ERR_VENDOR_NOT_ACTIVE` | 409 |
| `ERR_VENDOR_NOT_IN_REVIEW` | 409 |
| `ERR_RENEWAL_DATE_NOT_FUTURE` | 422 |
| `ERR_PHARMACIST_NOT_ACTIVE` | 403 |
| `ERR_REAL_NAME_REQUIRED` | 403 |
| `ERR_PRESCRIPTION_NOT_IN_REVIEW` | 409 |
| `ERR_PRESCRIPTION_EXPIRED` | 422 |
| `ERR_PRESCRIBER_NOT_QUALIFIED` | 422 |
| `ERR_CONTRAINDICATION_VIOLATION` | 422 |
| `ERR_PRESCRIPTION_IN_USE` | 409 |
| `ERR_PRESCRIPTION_NOT_APPROVED` | 409 |
| `ERR_PURCHASE_LIMIT_EXCEEDED` | 422 |
| `ERR_SPECIAL_POPULATION_RESTRICTED` | 403 |
| `ERR_ORDER_NOT_REVIEWABLE` | 409 |
| `ERR_ORDER_NOT_PAYABLE` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_ORDER_NOT_APPROVED` | 409 |
| `ERR_ORDER_NOT_PAID` | 409 |
| `ERR_ORDER_NOT_DISPENSED` | 409 |
| `ERR_ORDER_NOT_SHIPPED` | 409 |
| `ERR_REVIEW_ALREADY_OPEN` | 409 |
| `ERR_REVIEW_NOT_IN_REVIEW` | 409 |
| `ERR_REVIEW_NOT_IN_REQUEST_CHANGE` | 409 |
| `ERR_REVIEWER_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 |
| `ERR_REVIEW_CHECKS_FAILED` | 422 |
| `ERR_REVIEW_NOTES_TOO_SHORT` | 422 |
| `ERR_REVIEW_MAX_REVISIONS` | 409 |
| `ERR_COLD_CHAIN_NOT_APPLICABLE` | 422 |
| `ERR_COURIER_NOT_QUALIFIED` | 422 |
| `ERR_COLD_CHAIN_SHIPMENT_REQUIRED` | 409 |
| `ERR_DISPOSAL_NOT_JUSTIFIED` | 422 |
| `ERR_COLD_CHAIN_OUT_OF_RANGE` | 422 |
| `ERR_SHIPMENT_NOT_DISPOSABLE` | 409 |
| `ERR_REPORT_NOT_REPORTED` | 409 |
| `ERR_REPORT_REQUIRES_FOLLOW_UP` | 409 |
| `ERR_REPORT_NOT_ARCHIVABLE` | 409 |
| `ERR_REPORTING_DEADLINE_PASSED` | 422 |
| `ERR_FOLLOW_UP_INCOMPLETE` | 409 |

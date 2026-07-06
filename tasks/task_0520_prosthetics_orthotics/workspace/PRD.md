# Prosthetics & Orthotics Practice API — Product Requirements Document

## 1. Introduction

Prosthetic and orthotic (O&P) practices operate at the intersection of clinical care and a uniquely unforgiving billing regime. A single delivered limb prosthesis touches a prescribing physician, a fabricating supplier, a fitting practitioner, a Medicare prior-authorization queue, a fee schedule expressed in HCPCS L-codes, and a web of compliance obligations under the DMEPOS (Durable Medical Equipment, Prosthetics, Orthotics, and Supplies) supplier standards. When any one of these threads is mishandled — an expired prescription, a lapsed accreditation, a physician who both prescribes and fits the same device — the claim is not merely delayed; it is denied, recouped, or flagged as a referral-integrity violation.

This document specifies the API for an O&P practice-management system that governs that entire lifecycle: the physician's prescription and face-to-face evaluation, the device order's progression through prior authorization and fabrication milestones, the fitting and delivery attestation, L-code claim adjudication and appeal, follow-up adjustments, and out-of-warranty repair and replacement. The system treats every state change as auditable and every monetary figure as a ledger entry that must reconcile. Because so many rules depend on the passage of time — the six-month validity of a prescription, a fourteen-day authorization deadline, a warranty term, a five-year reasonable-useful-lifetime window — the system runs on a *logical clock* that test operators and compliance staff advance deliberately rather than reading from wall-clock time.

The design goal is segregation of duties and defensible compliance: each actor sees only the operations their role warrants, every derived amount is recomputed from first principles rather than trusted from the client, and the act of delivering a device is gated behind a deterministic compliance evaluation that either passes cleanly or returns an ordered list of exactly what failed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. All resources described here are mounted under the `/op` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `Physician`, `Practitioner`, `BillingSpecialist`, and `ComplianceOfficer`. When an authenticated role attempts an operation it is not authorized to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles map to distinct kinds of identity. When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician` entity — the prescribing physician of record; ownership checks on any resource that references a `Physician` (for example, a prescription's `physician_id`) compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Practitioner`, `X-User-ID` is likewise the `id` of a `Physician` entity, namely the fitting practitioner who runs fabrication, performs the delivery attestation, and handles adjustments and repairs; ownership and segregation checks that reference the fitting practitioner compare a resource's `fitting_practitioner_id` to `X-User-ID`. When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record the value but does not compare it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is similarly an opaque operator identifier not tied to any persisted entity, used for supplier and physician onboarding, authorization adjudication, appeals, replacement authorization, and clock control; the server may record it but does not compare it to any entity's `id`.

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

### 2.4. Common Resource Properties and the Audit Record

Most resources in the system — `Patient`, `Physician`, `Supplier`, `Prescription`, `DeviceOrder`, `PriorAuth`, `ClaimLine`, `FabricationMilestone`, `Adjustment`, and `RepairRequest` — carry a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID. It carries no type prefix and is used for identity only.
- `created_at`: an ISO 8601 timestamp in UTC with three fractional digits, set when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource — including mutations applied as a cascaded side effect of an operation on a related resource.
- `version`: an integer that starts at 1 and increments by exactly 1 on every mutation. It is the basis for optimistic concurrency control (§2.10).

Two entities are deliberate exceptions and carry only `id` and `created_at`; they have neither `updated_at` nor `version` because they are append-only and never mutated after creation. The first is `ComplianceCheck`, the audit record written at delivery: in addition to `id` and `created_at` it records the `device_order_id` it audited, a boolean `passed` indicating the aggregate gate result, and an ordered `failure_reasons` array listing the reason codes that failed (empty when `passed` is true). The second is `ClockState`, which records each setting of the logical clock: in addition to `id` and `created_at` it carries `current_utc`, the logical clock value, which defaults to `2026-05-01T00:00:00Z` at server startup.

Whenever any derived or computed field changes on a resource that carries `version` — for instance when `milestone_progress_pct` or `allowed_total_cents` is recomputed on a `DeviceOrder` — that recomputation is itself a mutation: `updated_at` is refreshed and `version` is incremented.

### 2.5. Hierarchical Consistency and Cascading Transitions

The system maintains immediate consistency across the graph of related resources. Many state changes are not initiated directly by a client but instead *bubble up* from a child resource as a side effect — the server transitions a parent automatically when the child's change satisfies the parent's transition criteria. When the final fabrication milestone of an order is completed, the order itself advances from `FABRICATION` to `READY_FOR_FITTING` without a separate request on the order. When a prior authorization is approved, the order it covers advances from `AUTH_PENDING` to `FABRICATION`. When a claim line is adjudicated, denied, or has a denial overturned on appeal, the owning order's `allowed_total_cents` ledger is recomputed. Each such cascade independently mutates the affected parent — refreshing its `updated_at` and incrementing its `version` — exactly as a direct mutation would.

For requests that target nested resources through a multi-segment path, the system validates each path identifier in strict left-to-right order and rejects the request with `ERR_RESOURCE_NOT_FOUND` at the *first* identifier that does not resolve to an existing resource. Body-referenced foreign keys are validated after all path identifiers. Only once existence is confirmed does the system evaluate business rules.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control because cascaded side effects can legitimately advance a resource's `version` between the moment a client reads it and the moment the client acts on it.

The delivery operation on a `DeviceOrder` requires the field `expected_device_order_version`, carrying the client's last observed `version` of that order. A cascaded milestone completion or a claim-line change can move the order forward and bump its `version`; if the supplied `expected_device_order_version` does not equal the order's current `version`, delivery is rejected with `ERR_STALE_ORDER_VERSION` and HTTP status 412, preventing the client from acting on an order it has not observed in its current form.

The resubmission operation on a `PriorAuth` requires the field `expected_prior_auth_version`, carrying the client's last observed `version` of that authorization. If a clock sweep advanced the authorization's bookkeeping, or another resubmission already fired, the `version` will have moved; if the supplied `expected_prior_auth_version` does not equal the authorization's current `version`, the resubmission is rejected with `ERR_STALE_AUTH_VERSION` and HTTP status 412.

These are the only two operations that take a version field. Every other write operation in the system processes without an OCC check and accepts no version input.

### 2.7. Monetary Values, Percentages, and Rounding

All monetary amounts in this system are integers denominated in cents — `fee_schedule_cents`, `allowed_cents`, `allowed_total_cents`, `cost_cents`, and the `parts_cents` supplied when assessing a repair. Where a calculation multiplies by a coinsurance rate, the result is rounded to a whole number of cents using the round-half-up method. Where a calculation sums cents that are already whole, the sum is exact and no rounding occurs. The fabrication progress percentage `milestone_progress_pct` is likewise an integer, rounded half up to a whole percent.

### 2.8. Supplier Accreditation Status as a Derived Field

A `Supplier` carries an `accreditation_status` that is never written directly by a client; it is derived at read time from the supplier's `accreditation_expiry` relative to the logical clock. If `accreditation_expiry` is null — the supplier was never accredited — the status is `UNACCREDITED`. Otherwise, if the logical clock is at or before `accreditation_expiry`, the status is `ACCREDITED`; a clock value exactly equal to `accreditation_expiry` is still `ACCREDITED`. Once the logical clock passes `accreditation_expiry`, the status is `LAPSED`. This derivation is recomputed whenever a supplier is fetched and whenever the logical clock is advanced. A supplier also carries a `surety_bond_active` boolean recording whether a DMEPOS surety bond is on file and active.

### 2.9. The DMEPOS Compliance Gate

Delivery of a device is the single most consequential compliance event in the system, and it is gated by a deterministic evaluation that produces the `ComplianceCheck` audit record. The gate runs five checks in a fixed order, accumulating a reason code for each one that fails, and the device passes only when no reason code accumulated. The checks, in order, are: first, that the fabricating supplier's `accreditation_status` is `ACCREDITED` — failure appends `SUPPLIER_NOT_ACCREDITED`; second, that the supplier's `surety_bond_active` is true — failure appends `NO_SURETY_BOND`; third, that when the patient's `payer_type` is `MEDICARE` the prescribing physician's `pecos_enrolled` is true — failure appends `PHYSICIAN_NOT_PECOS` (the patient is resolved through the order's `prescription_id` to the prescription's `patient_id`); fourth, that the owning prescription's `status` is `CONSUMED` — failure appends `RX_NOT_CONSUMED`; and fifth, that the order's `fitting_practitioner_id` differs from the prescription's `physician_id` — failure appends `SEGREGATION_VIOLATION`. The resulting `failure_reasons` array preserves exactly this check order, and `passed` is true only when the array is empty. How the gate's outcome maps onto delivery-time rejections is described in §3.5.

## 3. Business Logic & Workflows

### 3.1. Patients, Physicians, and Suppliers: the Onboarding Foundation

Before any clinical work can begin, the practice records the people and organizations involved. A `BillingSpecialist` or `ComplianceOfficer` registers a `Patient` by supplying a `full_name`, a `date_of_birth` in `YYYY-MM-DD` form, and a `payer_type` drawn from `MEDICARE`, `MEDICAID`, `COMMERCIAL`, or `SELF_PAY`. When the payer is `MEDICARE`, the patient's Medicare Beneficiary Identifier `medicare_beneficiary_id` is supplied; for other payers it is null. For lower-limb prosthetic candidates the patient may also carry a Medicare functional level `functional_k_level`, an integer from 0 through 4 inclusive, or null for orthotic patients.

A `ComplianceOfficer` registers a `Physician` by supplying a `full_name` and a ten-digit National Provider Identifier `npi`, which must be exactly ten digits. A physician also carries `pecos_enrolled`, a boolean recording enrollment in Medicare PECOS that defaults to false when not supplied; PECOS enrollment is required before that physician can prescribe a Medicare-payable order. The same `Physician` records back both prescribing physicians and fitting practitioners — the distinction is a matter of role on a given order, not of entity type.

A `ComplianceOfficer` also registers a `Supplier`, supplying its DMEPOS `legal_name`, an optional `accreditation_expiry`, and an optional `surety_bond_active` flag that defaults to false. The supplier's `accreditation_status` is computed from `accreditation_expiry` against the logical clock as described in §2.8, both at registration and on every subsequent read.

### 3.2. Prescription Authorship and the Validity Window

A `Physician` authors a prescription, which begins life in `DRAFT`. Creation requires the `patient_id` of the patient being treated, the `physician_id` of the prescribing physician, a `device_category` drawn from `LOWER_LIMB_PROSTHETIC`, `UPPER_LIMB_PROSTHETIC`, `SPINAL_ORTHOSIS`, or `LOWER_EXTREMITY_ORTHOSIS`, a `primary_diagnosis_code` (the ICD-10 code supporting medical necessity), and a `face_to_face_date` in `YYYY-MM-DD` form recording the date of the physician's face-to-face evaluation. That face-to-face date anchors a six-month window during which the prescription may be ordered against.

Signing a prescription, performed by a `Physician`, advances it from `DRAFT` to `SIGNED`. Signing is permitted only when the acting physician's `id` equals the prescription's `physician_id`, and only when both the `primary_diagnosis_code` and the `face_to_face_date` are present. The prescription's `version` increments on signing. A `Physician` may instead void a prescription that is still in `DRAFT`, advancing it from `DRAFT` to `VOIDED`; voiding is permitted only when the acting physician's `id` equals the prescription's `physician_id`, and it increments the `version`. `VOIDED` is terminal.

A signed prescription is later consumed by the system when a device order is created against it: the prescription advances from `SIGNED` to `CONSUMED`, and its `version` increments. This consumption happens only while the logical clock is at or before the face-to-face date plus six months. If instead a clock advance or an audit sweep finds a `SIGNED` prescription whose face-to-face date plus six months has already passed, the prescription advances from `SIGNED` to `EXPIRED` and its `version` increments. Both `CONSUMED` and `EXPIRED` are terminal states.

### 3.3. Opening a Device Order

A `BillingSpecialist` opens a `DeviceOrder` against a prescription, supplying the `prescription_id` of the prescription being fulfilled, the `supplier_id` of the fabricating and dispensing supplier, and the `fitting_practitioner_id` of the practitioner of record who will later attest the fitting and delivery. The order begins in `INTAKE`. Several gates apply at creation, all of which surface against the order-creation operation. The referenced prescription must exist and must belong to a consistent patient chain; a body foreign key that is inconsistent with context is rejected with `ERR_REFERENTIAL_MISMATCH`. The prescription's `status` must be `SIGNED` — ordering against a prescription that is `DRAFT`, `VOIDED`, `CONSUMED`, or `EXPIRED` is rejected with `ERR_RX_NOT_SIGNED`. The logical clock must fall at or before the prescription's face-to-face date plus six months; ordering against a prescription past that validity window is rejected with `ERR_RX_EXPIRED`. When the patient's payer is Medicare, the prescribing physician's `pecos_enrolled` must be true at creation, or the order is rejected with `ERR_PHYSICIAN_NOT_PECOS`.

One further temporal gate protects against same-or-similar duplication under the Medicare reasonable-useful-lifetime rule, keyed on the patient. Order creation is rejected with `ERR_SAME_SIMILAR_OVERLAP` when the same patient already has a `DELIVERED` device order of the same `device_category` whose reasonable-useful-lifetime window is still open — that is, when the logical clock falls within the closed interval that begins at the prior order's `delivery_date` and ends at that delivery date plus five years, inclusive of both endpoints.

On successful creation, the system determines whether the order needs prior authorization and records the result in `requires_prior_auth`: this is true only when the patient's `payer_type` is `MEDICARE` and the prescription's `device_category` is either `LOWER_LIMB_PROSTHETIC` or `SPINAL_ORTHOSIS`, and false in all other cases. Order creation also consumes the prescription as described in §3.2, advancing it from `SIGNED` to `CONSUMED` and incrementing the prescription's `version`. A newly created order carries `milestone_progress_pct` of 0, `allowed_total_cents` of 0, and null `delivery_date` and `warranty_expiry`.

Cancellation is available to a `BillingSpecialist` while the order is in either `INTAKE` or `AUTH_PENDING`, moving it to the terminal `CANCELLED` state and incrementing the order's `version`. If a prior authorization for the order is currently in `SUBMITTED` or `PENDED`, cancellation cascades to set that authorization to `DENIED`.

### 3.4. Prior Authorization, Fabrication, and the Path to Fitting

For an order that requires prior authorization, a `BillingSpecialist` submits the authorization, which advances the order from `INTAKE` to `AUTH_PENDING`. Submission is permitted only when `requires_prior_auth` is true, the order is in `INTAKE`, and the order does not already own a non-terminal authorization. The single-active-authorization rule means an order may hold at most one open authorization at a time: if the order already owns a `PriorAuth` whose status is `SUBMITTED`, `PENDED`, or `APPROVED`, the submission is rejected with `ERR_AUTH_ALREADY_OPEN`; only once an existing authorization has reached a terminal status of `DENIED` or `EXPIRED` is the slot freed for a fresh submission. Submission cascades the creation of a `PriorAuth` in `SUBMITTED` status whose `device_order_id` is the order, with `submission_round` of 1 and a `decision_deadline` set to the logical clock plus fourteen days, and it increments the order's `version`.

For an order that does not require prior authorization, a `Practitioner` starts fabrication directly, advancing the order from `INTAKE` to `FABRICATION`. This is permitted only when `requires_prior_auth` is false and at least one fabrication milestone already exists for the order; an attempt with no milestone defined is rejected with `ERR_MILESTONE_REQUIRED`. The order's `version` increments.

A prior authorization moves through a revision cycle under the `ComplianceOfficer`'s control. From `SUBMITTED`, a compliance officer may pend it for more information, advancing it to `PENDED` and incrementing its `version`. A `BillingSpecialist` resubmits a pended authorization, advancing it from `PENDED` back to `SUBMITTED`; resubmission requires that the authorization currently be `PENDED` and is guarded by optimistic concurrency control as described in §2.6. Resubmission increments `submission_round` by 1, resets `decision_deadline` to the logical clock plus fourteen days, and increments the authorization's `version`. From `SUBMITTED`, a compliance officer may approve the authorization, advancing it to the terminal `APPROVED` state; approval is permitted only when the covering order's supplier `accreditation_status` is `ACCREDITED`, otherwise it is rejected with `ERR_SUPPLIER_NOT_ACCREDITED`. Approval stamps an `auth_number`, increments the authorization's `version`, and — provided at least one fabrication milestone exists for the order — cascades the order from `AUTH_PENDING` to `FABRICATION`. A compliance officer may instead deny a `SUBMITTED` authorization, advancing it to the terminal `DENIED` state and incrementing its `version`.

Authorizations are also swept by time. When the logical clock advances past an authorization's `decision_deadline` while the authorization is still in `SUBMITTED` or `PENDED`, the authorization advances to the terminal `EXPIRED` state and its `version` increments.

During fabrication, a `Practitioner` adds fabrication milestones to the order, each supplying a `step` drawn from `CASTING`, `MODIFICATION`, `ASSEMBLY`, or `QUALITY_CHECK`, and a relative-effort `weight` that must be at least 1. Each step may appear at most once per order; a duplicate step is rejected with `ERR_DUPLICATE_MILESTONE`. A milestone begins with `completed` false. Adding a milestone recomputes the order's `milestone_progress_pct`. A `Practitioner` marks a milestone complete, setting its `completed` to true and recomputing the order's progress: the progress percentage is the sum of the `weight` of completed milestones, multiplied by 100, divided by the sum of the `weight` of all milestones for the order, rounded half up to a whole percent; when the order has no milestones at all the percentage is 0. When the recomputation finds that every milestone for the order is complete, the progress reaches 100 and the order cascades from `FABRICATION` to `READY_FOR_FITTING`, with the order's `version` incrementing on the cascade.

### 3.5. Fitting, Delivery, and the Segregation of Duties

The delivery attestation is performed by a `Practitioner` on an order in `READY_FOR_FITTING`, advancing it to the terminal `DELIVERED` state. The request carries `expected_device_order_version` for the optimistic-concurrency check of §2.6. Three preconditions must hold. First, the supplied version must match the order's current `version`, else `ERR_STALE_ORDER_VERSION`. Second, the DMEPOS compliance gate of §2.9 must pass; when the gate fails for any reason other than segregation of duties, delivery is rejected with `ERR_COMPLIANCE_GATE_FAILED`. Third — surfaced as its own distinct rejection — the order's `fitting_practitioner_id` must differ from the owning prescription's `physician_id`; when they are equal, delivery is rejected with `ERR_SEGREGATION_OF_DUTIES`, reflecting the anti-self-referral control that the same physician may not both prescribe and attest the fitting of one device.

On successful delivery the system writes an append-only `ComplianceCheck` record for the order, stamps `delivery_date` to the current logical clock, computes the `warranty_expiry` (§3.7), advances every `ClaimLine` of the order that is still in `DRAFT` to `SUBMITTED`, and increments the order's `version`. (The prescription was already moved to `CONSUMED` at order creation, so no further prescription transition occurs here.)

A read-only billing summary is available to a `BillingSpecialist` or `ComplianceOfficer`, presenting both a provisional and a final view of the order's allowed total as described in §3.6, and the order's compliance-check audit history can be listed by a `ComplianceOfficer` or `BillingSpecialist`.

### 3.6. L-Code Billing, Adjudication, and Appeals

A `BillingSpecialist` creates a `ClaimLine` against an order, supplying the `device_order_id` of the order being billed, the HCPCS `l_code` (such as L5301), an optional pricing/coverage `modifier` drawn from `NONE`, `KX`, `GA`, `GZ`, `RT`, or `LT` and defaulting to `NONE`, the `billed_units` (which must be at least 1), and the per-unit Medicare `fee_schedule_cents` (which must be at least 0). A claim line begins with `adjudication_status` of `DRAFT`, `appeal_status` of `NONE`, and `allowed_cents` of 0. A claim line whose `billed_units` is below 1 or whose `fee_schedule_cents` is below 0 is rejected at creation with `ERR_INVALID_BILLING_AMOUNT`. Adjudication and appeal evolve as two independent dimensions on the same line: `adjudication_status` carries the billing lifecycle, while `appeal_status` carries the appeal lifecycle.

When an order is delivered, the system moves every `DRAFT` claim line of that order to `SUBMITTED`, incrementing each line's `version`. A `BillingSpecialist` then adjudicates a `SUBMITTED` line, advancing its `adjudication_status` to `ADJUDICATED`. Adjudication of a line bearing the `KX` modifier is permitted only when the covering order either does not require prior authorization or has an `APPROVED` prior authorization; a `KX` line on an auth-required order that lacks an approved authorization is rejected with `ERR_KX_WITHOUT_AUTH`. Adjudication computes the line's final `allowed_cents` and then recomputes the owning order's `allowed_total_cents` ledger, incrementing the line's `version`.

The final allowed amount for a line is computed from a base equal to the line's `fee_schedule_cents` multiplied by its `billed_units`, then branched on the `modifier`. A `KX` modifier asserts the coverage criteria are met and allows the full base. A `GA` modifier signals that an Advance Beneficiary Notice is on file with an expected denial, and the payer pays the statutory eighty percent: the allowed amount is the base multiplied by the coinsurance rate of 0.80, rounded half up to a whole number of cents. A `GZ` modifier signals no Advance Beneficiary Notice with an expected denial, and nothing is payable, so the allowed amount is 0. The `NONE`, `RT`, and `LT` modifiers are neutral or laterality-only and carry no price effect, so the allowed amount equals the base.

A `BillingSpecialist` may instead deny a `SUBMITTED` line, advancing its `adjudication_status` to `DENIED`, setting `allowed_cents` to 0, recomputing the order's `allowed_total_cents`, and incrementing the line's `version`. A `ComplianceOfficer` files an appeal on a denied line, advancing its `appeal_status` from `NONE` to `APPEALED` and incrementing the line's `version`. A `ComplianceOfficer` then records the appeal outcome by supplying an `outcome`; the outcome must be either `UPHELD` or `OVERTURNED`, and any other value is rejected with `ERR_INVALID_APPEAL_OUTCOME`. An upheld appeal sets `appeal_status` to `APPEAL_UPHELD`. An overturned appeal sets `appeal_status` to `APPEAL_OVERTURNED` and, for a line whose `adjudication_status` is `DENIED` and `appeal_status` is `APPEALED`, moves `adjudication_status` from `DENIED` back to `ADJUDICATED`, recomputes the line's `allowed_cents`, recomputes the order's `allowed_total_cents`, and increments the line's `version`.

The order's `allowed_total_cents` is the exact sum of `allowed_cents` over only those claim lines whose `adjudication_status` is `ADJUDICATED`; lines in `DRAFT`, `SUBMITTED`, or `DENIED` are excluded, and the sum involves no rounding. The billing summary of §3.5 presents two variants of this total. The provisional estimate is computed before adjudication: it sums, over the order's `SUBMITTED` lines, the provisional allowed amount, which is simply each line's billed amount — `fee_schedule_cents` multiplied by `billed_units` — with no modifier reduction applied. The provisional per-line figure therefore ignores the `GA` eighty-percent reduction and the `GZ` zero entirely; those reductions apply only in the final adjudicated computation. The final ledger view sums the persisted final `allowed_cents` over the order's `ADJUDICATED` lines and diverges from the provisional estimate once any `GA` or `GZ` lines are adjudicated.

### 3.7. Warranty, Follow-up Adjustments, and the No-Charge Window

Upon delivery the system computes `warranty_expiry` from the `delivery_date` plus a warranty term in calendar months that depends on the device category. Lower-limb and upper-limb prosthetics — `LOWER_LIMB_PROSTHETIC` and `UPPER_LIMB_PROSTHETIC` — carry an eighteen-month term; all orthoses carry a twelve-month term. The term is added as calendar months, preserving the day of month and clamping to the end of the target month where necessary.

After delivery, a `Practitioner` records a follow-up `Adjustment` on the order. Creating the adjustment stamps its `adjustment_date` to the current logical clock and computes both `within_warranty` and `billable`. The adjustment is `within_warranty` when its `adjustment_date` is at or before the order's `warranty_expiry`. Two free windows govern billability: a free-fitting window running from `delivery_date` through `delivery_date` plus ninety days inclusive, and the warranty window running through `warranty_expiry` inclusive. The adjustment is `billable` only when neither window covers it — that is, only when its `adjustment_date` is strictly after the ninety-day free-fitting cutoff and strictly after the warranty expiry. An adjustment dated exactly on the ninety-day cutoff, or exactly on the warranty expiry, is not billable. An adjustment or repair may only be created against an order that is in `DELIVERED` status; an attempt against an order in any other status is rejected with `ERR_NOT_DELIVERED`.

### 3.8. Repairs, Warranty Coverage, and Replacement

A `Practitioner` or `BillingSpecialist` reports a `RepairRequest` against a delivered order by supplying the `device_order_id`. The request begins in `REPORTED` with `cost_cents` of 0, `warranty_applies` false, and a null `replaces_order_id`. A `Practitioner` then assesses the request, advancing it from `REPORTED` to `ASSESSED` and supplying the `parts_cents` for the repair. Assessment computes `warranty_applies` and `cost_cents`: the repair is in warranty when the report date — the request's `created_at` — is at or before the order's `warranty_expiry`, a boundary that is inclusive so that a report dated exactly on the warranty expiry is still in warranty. When warranty applies, `cost_cents` is 0; otherwise the cost is the flat labor fee of 12,500 cents plus the supplied `parts_cents`. The request's `version` increments on assessment.

From `ASSESSED`, a `Practitioner` completes the repair, advancing it from `ASSESSED` to `REPAIRED` and incrementing the `version`. Alternatively, a `ComplianceOfficer` authorizes a replacement, permitted only when `warranty_applies` is false — in-warranty failures are repaired, not replaced, under the five-year reasonable-useful-lifetime rule, and an attempt while warranty still applies is rejected with `ERR_REPLACEMENT_IN_WARRANTY`. Authorizing a replacement advances the request from `ASSESSED` to `REPLACEMENT_AUTHORIZED`, cascades the creation of a new `DeviceOrder` in `INTAKE` that clones the original order's `prescription_id` and `supplier_id`, sets the request's `replaces_order_id` to that new order's `id` — a self-referential link back into the device-order population — and increments the request's `version`. Finally, a `Practitioner` closes a request that is in either `REPAIRED` or `REPLACEMENT_AUTHORIZED`, advancing it to the terminal `CLOSED` state and incrementing the `version`.

### 3.9. The Logical Clock and Time-Driven Sweeps

Time in this system is a logical clock that a `ComplianceOfficer` sets explicitly by supplying a `to_iso8601` instant; the server records each setting as a `ClockState` whose `current_utc` becomes the new clock value. Before the clock is ever set, every deadline, expiry, and window rule reads the startup default of `2026-05-01T00:00:00Z`. Advancing the clock has two cascading effects. First, every `PriorAuth` still in `SUBMITTED` or `PENDED` whose `decision_deadline` now lies in the past — that is, whose deadline the clock has passed — is swept to `EXPIRED`. Second, supplier accreditation status is re-derived against the new clock value on the next read of each supplier, as described in §2.8.

### 3.10. Validation Ordering

When an operation is subject to several checks, they are evaluated in a fixed precedence so that the most fundamental failures surface first. Authentication is evaluated first: a request missing valid headers or naming an unknown role fails with `ERR_UNAUTHENTICATED`. Authorization is evaluated next: a recognized role attempting an operation outside its permissions fails with `ERR_FORBIDDEN_ROLE`. Resource existence is checked third, validating path identifiers left-to-right and then body foreign keys, with a miss yielding `ERR_RESOURCE_NOT_FOUND`. Business-referential consistency of body foreign keys is checked fourth, yielding `ERR_REFERENTIAL_MISMATCH`. State legality is checked fifth: a transition not defined from the resource's current state yields `ERR_INVALID_STATE`. Only after these structural checks do the domain-specific business rules apply — the compliance gate, segregation of duties, prescription validity and signing, PECOS enrollment, KX-without-auth, duplicate milestones, in-warranty replacement, billing-amount validity, the same-or-similar overlap, the single-active-authorization rule, the optimistic-concurrency version match, and the well-formedness of the request body. A request body that is missing a required field, carries a value outside an enumeration, or carries an out-of-range integer is rejected with `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, including state transitions, return a `200 OK` status code. All paths are mounted under the `/op` prefix shown below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/op/patients` | Create a patient | BillingSpecialist, ComplianceOfficer |
| GET | `/op/patients/{id}` | Fetch a patient | BillingSpecialist, ComplianceOfficer, Practitioner |
| POST | `/op/physicians` | Register a prescribing/fitting physician | ComplianceOfficer |
| GET | `/op/physicians/{id}` | Fetch a physician | ComplianceOfficer, BillingSpecialist, Practitioner, Physician |
| POST | `/op/suppliers` | Register a DMEPOS supplier | ComplianceOfficer |
| GET | `/op/suppliers/{id}` | Fetch a supplier with derived accreditation status | ComplianceOfficer, BillingSpecialist, Practitioner |
| POST | `/op/prescriptions` | Create a DRAFT prescription | Physician |
| GET | `/op/prescriptions/{id}` | Fetch a prescription | Physician, BillingSpecialist, ComplianceOfficer, Practitioner |
| GET | `/op/prescriptions` | List prescriptions; filterable by patient or physician | Physician, BillingSpecialist, ComplianceOfficer |
| POST | `/op/prescriptions/{id}/sign` | Sign a draft prescription | Physician |
| POST | `/op/prescriptions/{id}/void` | Void a draft prescription | Physician |
| POST | `/op/device-orders` | Create a device order at intake | BillingSpecialist |
| GET | `/op/device-orders/{id}` | Fetch a device order with derived fields | BillingSpecialist, ComplianceOfficer, Practitioner |
| GET | `/op/device-orders` | List device orders; filterable by prescription, supplier, or fitting practitioner | BillingSpecialist, ComplianceOfficer, Practitioner |
| POST | `/op/device-orders/{id}/submit-auth` | Submit prior authorization for an order | BillingSpecialist |
| POST | `/op/device-orders/{id}/start-fabrication` | Begin fabrication for a no-auth order | Practitioner |
| POST | `/op/device-orders/{id}/deliver` | Deliver/fit the device | Practitioner |
| POST | `/op/device-orders/{id}/cancel` | Cancel an order | BillingSpecialist |
| GET | `/op/device-orders/{id}/billing-summary` | Provisional vs final allowed totals | BillingSpecialist, ComplianceOfficer |
| GET | `/op/device-orders/{id}/compliance-checks` | List compliance-check audit records | ComplianceOfficer, BillingSpecialist |
| POST | `/op/device-orders/{id}/fabrication-milestones` | Add a fabrication milestone | Practitioner |
| GET | `/op/device-orders/{id}/fabrication-milestones` | List milestones for an order | Practitioner, BillingSpecialist, ComplianceOfficer |
| POST | `/op/fabrication-milestones/{id}/complete` | Mark a milestone complete | Practitioner |
| GET | `/op/prior-auths/{id}` | Fetch a prior authorization | ComplianceOfficer, BillingSpecialist |
| GET | `/op/prior-auths` | List prior auths; filterable by device order | ComplianceOfficer, BillingSpecialist |
| POST | `/op/prior-auths/{id}/pend` | Pend a submitted auth for more info | ComplianceOfficer |
| POST | `/op/prior-auths/{id}/resubmit` | Resubmit a pended auth | BillingSpecialist |
| POST | `/op/prior-auths/{id}/approve` | Approve an auth | ComplianceOfficer |
| POST | `/op/prior-auths/{id}/deny` | Deny an auth | ComplianceOfficer |
| POST | `/op/claim-lines` | Create a draft claim line | BillingSpecialist |
| GET | `/op/claim-lines/{id}` | Fetch a claim line | BillingSpecialist, ComplianceOfficer |
| GET | `/op/claim-lines` | List claim lines; filterable by device order | BillingSpecialist, ComplianceOfficer |
| POST | `/op/claim-lines/{id}/adjudicate` | Adjudicate a submitted line | BillingSpecialist |
| POST | `/op/claim-lines/{id}/deny` | Deny a submitted line | BillingSpecialist |
| POST | `/op/claim-lines/{id}/appeal` | File an appeal on a denied line | ComplianceOfficer |
| POST | `/op/claim-lines/{id}/appeal-decision` | Record appeal outcome | ComplianceOfficer |
| POST | `/op/repair-requests` | Report a repair on a delivered order | Practitioner, BillingSpecialist |
| GET | `/op/repair-requests/{id}` | Fetch a repair request | Practitioner, BillingSpecialist, ComplianceOfficer |
| GET | `/op/repair-requests` | List repair requests; filterable by device order or replaced order | Practitioner, BillingSpecialist, ComplianceOfficer |
| POST | `/op/repair-requests/{id}/assess` | Assess a reported repair | Practitioner |
| POST | `/op/repair-requests/{id}/complete-repair` | Complete an assessed repair | Practitioner |
| POST | `/op/repair-requests/{id}/authorize-replacement` | Authorize replacement of an out-of-warranty device | ComplianceOfficer |
| POST | `/op/repair-requests/{id}/close` | Close a repair | Practitioner |
| POST | `/op/device-orders/{id}/adjustments` | Record a follow-up adjustment | Practitioner |
| GET | `/op/device-orders/{id}/adjustments` | List adjustments for an order | Practitioner, BillingSpecialist, ComplianceOfficer |
| POST | `/op/_clock/set_current_utc` | Set the logical clock | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENTIAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_COMPLIANCE_GATE_FAILED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_RX_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RX_NOT_SIGNED` | 422 Unprocessable Entity |
| `ERR_PHYSICIAN_NOT_PECOS` | 422 Unprocessable Entity |
| `ERR_KX_WITHOUT_AUTH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_MILESTONE` | 409 Conflict |
| `ERR_REPLACEMENT_IN_WARRANTY` | 422 Unprocessable Entity |
| `ERR_INVALID_BILLING_AMOUNT` | 422 Unprocessable Entity |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AUTH_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MILESTONE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SUPPLIER_NOT_ACCREDITED` | 422 Unprocessable Entity |
| `ERR_NOT_DELIVERED` | 422 Unprocessable Entity |
| `ERR_INVALID_APPEAL_OUTCOME` | 400 Bad Request |
| `ERR_SAME_SIMILAR_OVERLAP` | 422 Unprocessable Entity |
| `ERR_AUTH_ALREADY_OPEN` | 409 Conflict |

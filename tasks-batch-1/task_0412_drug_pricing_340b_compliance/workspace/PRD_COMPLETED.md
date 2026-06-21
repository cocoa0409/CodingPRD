# Drug Pricing 340B Compliance API — Product Requirements Document

## 1. Introduction

The federal 340B Drug Pricing Program lets registered safety-net providers — disproportionate-share hospitals, children's hospitals, freestanding cancer centers, critical-access hospitals, rural referral centers, federally qualified health centers, Ryan White grantees, and STD clinics — acquire covered outpatient drugs at or below a statutory ceiling price. Operating the program correctly is unforgiving: a provider must register its main site and every associated child site, prove that each dispensed drug went to an eligible patient, keep an honest split-billing accumulator so that 340B inventory and full-price (WAC) inventory never co-mingle, avoid both the duplicate-discount trap with Medicaid and the GPO-purchasing prohibition for hospital types, and survive HRSA audits and manufacturer ceiling-price reconciliations with a clean repayment ledger.

This API is the system of record for that compliance surface. It tracks the registration lifecycle of a covered entity and its child sites; classifies each prescription dispense as 340B or WAC through a fixed eligibility cascade; maintains a per-drug split-billing accumulator that crystallises whole replenishment packages and emits 340B purchase orders; reconciles purchase prices paid against published manufacturer ceiling prices; and runs the audit-and-self-disclosure workflow through which findings become repayment obligations. Throughout, the system enforces a strict separation of duties: the entity's compliance officer can self-disclose but cannot adjudicate, the HRSA auditor adjudicates but cannot dispense or self-disclose, and the pharmacy operator dispenses but cannot adjudicate or remit.

The product goal is a single, deterministic source of truth that makes the hard cases — penny pricing, provisional-vs-published ceilings, partial repayments, stale-version writes, and cross-quarter overcharge reconciliation — reproducible to the cent, so that any two readers of an entity's record reach the same compliance conclusion.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting compliance principles that apply across every endpoint. The whole API is mounted under the `/340b` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's operational capacity. The system recognises exactly three roles, spelled precisely as `ComplianceOfficer`, `HrsaAuditor`, and `PharmacyOperator`. A request missing either header, or carrying an `X-User-Role` that is not one of those three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but is not permitted to invoke the targeted endpoint per the authorization table in §4 is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All three roles are **opaque operator identifiers** — none is backed by a persisted entity. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier acting on behalf of a covered entity; the server does not compare it to any entity's `id`, though it does record it for the one segregation-of-duties rule described in §3 (a self-disclosed finding may not later be disputed by the same `X-User-ID` that created it). When `X-User-Role` is `HrsaAuditor`, `X-User-ID` is likewise an opaque identifier of the HRSA-side adjudicator and is not tied to any persisted entity. When `X-User-Role` is `PharmacyOperator`, `X-User-ID` is an opaque identifier of the pharmacy operator and is similarly never compared to any entity's `id`. In short, ownership in this system is established through foreign-key fields carried in request payloads, not through the caller's identity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1, a `limit` above 100, or a negative `offset` is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on each mutation. The `version` field is the basis for optimistic concurrency control (see §2.7).

One entity is the exception: the **prescriber** record carries only `id` and `created_at`. A prescriber has no `updated_at` and no `version`; it is effectively immutable after creation. Every other entity in this specification — covered entities, child sites, patients, drug products, ceiling-price records, contract-pharmacy arrangements, accumulators, prescription dispenses, Medicaid claims, audit findings, repayment obligations, and purchase orders — carries the full `id`/`created_at`/`updated_at`/`version` set.

When a computed or derived field on a resource changes as a downstream effect of some operation — for example a covered entity's `compliance_posture` or `open_repayment_cents`, or an accumulator's `accrued_units` — that change is itself a mutation: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval and Referential Integrity

Many paths address a resource nested under a parent, such as a child site under a covered entity, a ceiling-price record under a drug product, or a Medicaid claim under a dispense. For any such path, the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same `ERR_NOT_FOUND` governs foreign-key body fields: if a write payload references a parent — for instance a `covered_entity_id`, `drug_product_id`, `patient_id`, `prescriber_id`, `child_site_id`, `contract_pharmacy_id`, `accumulator_id`, `prescription_dispense_id`, `source_ref_id`, or `drug_product_id` on a ceiling-price record — and that parent does not exist, the request is rejected with `ERR_NOT_FOUND`.

Referential ownership is checked separately from mere existence. Several list endpoints exist precisely so that a foreign key is reverse-reachable: child sites and contract pharmacies and accumulators and audit findings and repayment obligations are all listable under their owning covered entity, ceiling-price records under their drug product, and Medicaid claims under their dispense; prescribers, patients, accumulators, dispenses, audit findings, repayment obligations, and purchase orders are all listable globally with a `covered_entity_id` (and other foreign-key) filter.

### 2.6. Validation Order and Precedence

When several checks could fail on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path-referenced resource and foreign-key parent (`ERR_NOT_FOUND`), then request-shape validity — required fields present, correct types, enum members drawn from their declared sets, and integer fields meeting their lower bounds (`ERR_INVALID_REQUEST`, HTTP 422). Only after those structural gates pass does the system evaluate the business rules described throughout §3. Where a single endpoint layers further business checks on top of these, the per-endpoint ordering is called out in the relevant §3 narrative; in every case, the earlier (lower-numbered) check takes precedence and its error is the one returned.

### 2.7. Optimistic Concurrency on Reconciliation Writes

Two operations in this system require a client to prove it is acting on a current view of a parent resource by submitting that parent's last-observed `version`. These are the only two endpoints that take a version field; every other endpoint omits it entirely.

The first is the **manual accumulator replenishment** operation. A request to finalise a replenishment sweep against an accumulator must carry `expected_accumulator_version`, which must equal the target accumulator's current `version`. If a 340B dispense — or an automatic replenishment that dispense triggered — has already advanced the accumulator's `accrued_units` and bumped its `version` since the client last read it, the client's view of the package count is stale, and the replenishment is rejected with `ERR_STALE_VERSION` (HTTP 412).

The second is the **ceiling-price reconciliation** operation. A request to reconcile a drug product for a quarter must carry `expected_drug_product_version`, which must equal that drug product's current `version`. If a newly published ceiling-price record has landed since the client last read the drug product — legitimately superseding the prior quarter price and bumping the drug product's `version` — then the overcharge basis the client computed is stale, and the reconcile is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Monetary and Quantity Precision

All prices, costs, and remittances are carried as **integer cents**; there are no fractional cents anywhere in the system, and because every monetary computation is a sum or product of integer cents, no rounding is ever required — results are exact. Unit quantities (dispensed units, package sizes, accrued units, package counts) are likewise integers. Package crystallisation uses integer floor division, described in §3. Where an overcharge or clawback could compute negative, it is floored at zero rather than allowed to go below it; the precise flooring order for multi-purchase-order reconciliation is pinned in §3 and matters for the assessed total.

### 2.9. Compliance Posture as a Derived Gate

Each covered entity exposes a derived `compliance_posture` of either `GOOD` or `FLAGGED`. It reads `FLAGGED` whenever the entity has at least one audit finding in `OPEN`, `UNDER_REVIEW`, or `DISPUTED` status, or at least one repayment obligation in `OWED` or `PARTIALLY_PAID` status; otherwise it reads `GOOD`. The entity also exposes `open_repayment_cents`, the sum of `remaining_balance_cents` across every repayment obligation referencing it whose `status` is `OWED` or `PARTIALLY_PAID`. Both fields are recomputed on every audit-finding and repayment side effect, and recertification of the entity is gated on `compliance_posture` being `GOOD`. A recomputation mutates the entity — refreshing its `updated_at` and incrementing its `version` as described in §2.4 — only when it actually changes `compliance_posture` or `open_repayment_cents`; a recompute that leaves both values unchanged is a no-op that neither refreshes `updated_at` nor bumps `version`.

## 3. Business Logic & Workflows

### 3.1. Registering and Adjudicating a Covered Entity

A `ComplianceOfficer` registers a covered entity by supplying its `hrsa_id` (the HRSA-assigned grant or registration identifier, which must be non-empty and unique across all covered entities — a collision is rejected with `ERR_DUPLICATE_HRSA_ID`), its `legal_name`, and its `entity_type`. The `entity_type` must be one of `DSH`, `CHILDRENS_HOSPITAL`, `FREESTANDING_CANCER`, `CRITICAL_ACCESS`, `RURAL_REFERRAL`, `FQHC`, `RYAN_WHITE`, or `STD_CLINIC`. At creation the system computes `gpo_prohibited` from the type alone: it is set `true` exactly when the `entity_type` is one of `DSH`, `CHILDRENS_HOSPITAL`, or `FREESTANDING_CANCER`, and `false` otherwise. This computed flag is never overwritten by any input the client supplies.

The registration payload also accepts `medicaid_billing_mode`, one of `CARVE_IN` or `CARVE_OUT`, defaulting to `CARVE_OUT` when omitted. A `CARVE_IN` entity bills Medicaid fee-for-service using 340B drugs and therefore must appear on the Medicaid Exclusion File; accordingly, a `CARVE_IN` registration is required to supply a non-null `medicaid_provider_number` (its Medicaid billing NPI). A `CARVE_IN` registration submitted without a `medicaid_provider_number` is rejected with `ERR_MEF_NUMBER_REQUIRED` (HTTP 422); the same requirement is re-checked at approval time. A `CARVE_OUT` entity may leave `medicaid_provider_number` null (its default). Every newly registered entity begins with `registration_status` of `PENDING`, `recert_period_index` of 0, `compliance_posture` of `GOOD`, and `open_repayment_cents` of 0.

A registration sits in `PENDING` until an `HrsaAuditor` adjudicates it. Approval, available only from `PENDING`, advances `registration_status` to `ACTIVE` and recomputes the entity's posture (which is `GOOD` on a fresh entity); denial, also only from `PENDING`, moves it to `DENIED`, a terminal state. Once `ACTIVE`, an auditor may flag the entity for recertification, moving it `ACTIVE → RECERT_DUE`. From `RECERT_DUE`, the `ComplianceOfficer` completes recertification, returning it `RECERT_DUE → ACTIVE` and incrementing `recert_period_index` by one — but only when `compliance_posture` is `GOOD`; if any audit finding is still open or any repayment is still outstanding the posture is `FLAGGED` and the attempt is blocked. An auditor may terminate an entity from either `ACTIVE` or `RECERT_DUE`, moving it to the terminal `TERMINATED` state; termination cascades to every contract-pharmacy arrangement of that entity whose `arrangement_status` is `ACTIVE`, driving each of those to `TERMINATED`. Any transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409); the recertify, approve, deny, flag, and terminate operations all share that guard.

### 3.2. Child Sites, Prescribers, and Patients

Under a covered entity, a `ComplianceOfficer` registers a **child site** with a `site_name` and `service_address`. A child site carries a `registered` boolean — `true` only once the site is listed in the 340B OPAIS database — which defaults to `false` and may be supplied at creation. Only a registered child site confers 340B eligibility on a dispense performed there. The site's parent linkage is the `covered_entity_id` it was created under, and child sites are listable beneath their entity, optionally filtered by `registered`.

Prescribers are registered under a covered entity by a `ComplianceOfficer` with an `npi` (which must be unique across all prescribers — a collision is rejected with `ERR_INVALID_REQUEST` (HTTP 422), as there is no dedicated duplicate-NPI error code), a `full_name`, and a `relationship_type` of `EMPLOYED`, `CONTRACTED`, `REFERRAL_ONLY`, or `EXTERNAL`. The `relationship_type` drives the eligibility cascade described in §3.5: only `EMPLOYED` and `CONTRACTED` prescribers support 340B eligibility. Each prescriber records the `covered_entity_id` that employs or contracts it. Prescribers are listable globally, filterable by `covered_entity_id`.

Patients are registered under a covered entity by either a `ComplianceOfficer` or a `PharmacyOperator`, with an `mrn` (medical record number within the entity). Three boolean flags encode the patient's eligibility footprint: `has_ce_care_record` (the entity maintains the patient's care records — HRSA patient-definition prong one — defaulting to `true`), `ce_retains_responsibility` (the entity retains responsibility for the patient's care — prong two — defaulting to `true`), and `medicaid_ffs_enrolled` (the patient is enrolled in Medicaid fee-for-service, defaulting to `false`), each consumed by the eligibility determination. Each patient records its `covered_entity_id`. Patients are listable globally, filterable by `covered_entity_id`.

### 3.3. Drug Products and the Ceiling-Price Model

A drug product is configured by either a `ComplianceOfficer` or an `HrsaAuditor` with an `ndc` (the 11-digit National Drug Code, which must be non-empty and unique across all drug products — a collision is rejected with `ERR_DUPLICATE_NDC`), a `drug_name`, a `package_size_units` (the number of dispensable units in one purchasable package, which must be an integer of at least 1 and serves as the accumulator's replenishment granularity), a `wac_price_per_unit_cents` (the wholesale acquisition cost per unit, an integer of at least 0, used as the non-340B acquisition price), and an `is_covered_outpatient_drug` flag (defaulting to `true`) that marks whether the NDC is subject to the GPO prohibition.

Under a drug product, a quarterly **ceiling-price record** is added with a `quarter` (format `YYYYQn`, e.g. `2026Q2`, matching a four-digit year followed by `Q` and a digit 1 through 4), an `amp_per_unit_cents` (Average Manufacturer Price per unit, integer of at least 0), a `ura_per_unit_cents` (Unit Rebate Amount per unit, integer of at least 0), and an `is_published` flag defaulting to `true` (where `true` marks the manufacturer's final published price for the quarter and `false` marks a provisional estimate). Each record records the `drug_product_id` it applies to.

On creation the system computes `ceiling_price_per_unit_cents` and `pricing_variant` from the record's own AMP and URA. The rule has two branches with an inclusive boundary. When the Unit Rebate Amount is strictly less than the Average Manufacturer Price, the ceiling price per unit is the Average Manufacturer Price minus the Unit Rebate Amount, and `pricing_variant` is `STANDARD`. When the Unit Rebate Amount is greater than or equal to the Average Manufacturer Price — the boundary is inclusive, so equality yields penny pricing rather than a zero ceiling — the ceiling price per unit is forced to the penny floor of exactly 1 cent, and `pricing_variant` is `PENNY`.

A drug product may hold at most one published ceiling-price record per quarter: a second record with `is_published` of `true` for a `(drug_product_id, quarter)` pair that already has a published record is rejected with `ERR_CEILING_QUARTER_OVERLAP` (HTTP 409). Provisional records (with `is_published` of `false`) never collide on quarter, and may coexist with a published record for the same quarter. Adding any ceiling-price record increments the parent drug product's `version` by one.

**Selecting the effective ceiling.** When a price must be chosen for a `(drug_product_id, quarter)` pair — whether to price a 340B dispense or to answer the effective-ceiling read — the system gathers every ceiling-price record for that drug product and quarter. If at least one is published, the effective record is the most recently created published record (the one with the latest `created_at`), and the variant is reported as `FINAL`; a later provisional estimate never overrides a published price. If none is published but provisional records exist, the effective record is the most recently created provisional record by `created_at`, and the variant is reported as `PROVISIONAL`. If no record exists at all for that pair, there is no effective ceiling, and a dispense that would otherwise classify 340B cannot be priced; the effective-ceiling read endpoint then responds `ERR_NOT_FOUND` (HTTP 404). When an effective record does exist, the effective-ceiling read returns that record's full serialized object with one additional field, `effective_variant`, carrying the reported variant (`FINAL` or `PROVISIONAL`); the read requires a `quarter` query parameter, rejecting an absent or non-`YYYYQn` value with `ERR_INVALID_REQUEST` (HTTP 422).

### 3.4. Contract-Pharmacy Arrangements

A `ComplianceOfficer` establishes a contract-pharmacy arrangement under a covered entity by supplying a `pharmacy_name`, a `ship_to_bill_to_npi` (the NPI under which 340B drugs are replenished to the external pharmacy), an `effective_start`, and an `effective_end` (both `YYYY-MM-DD`, with `effective_end` strictly later than `effective_start`). The arrangement's window is the half-open interval running from `effective_start` inclusive to `effective_end` exclusive. Each arrangement records its `covered_entity_id` and begins life with `arrangement_status` of `ACTIVE`.

A new arrangement may not overlap an existing one. Specifically, creating an arrangement is rejected with `ERR_CP_WINDOW_OVERLAP` (HTTP 409) when the same covered entity already has an arrangement whose `arrangement_status` is `ACTIVE` or `SUSPENDED`, that shares the same `ship_to_bill_to_npi`, and whose half-open window intersects the new half-open window. Because the intervals are half-open, adjacency does not collide: if an existing arrangement's `effective_end` equals the new arrangement's `effective_start`, the two abut without overlapping and the new arrangement is accepted.

Through its lifecycle, a `ComplianceOfficer` may suspend an `ACTIVE` arrangement (`ACTIVE → SUSPENDED`), reactivate a `SUSPENDED` one (`SUSPENDED → ACTIVE`, permitted only while the owning entity's `registration_status` is `ACTIVE`), or terminate an `ACTIVE` one (`ACTIVE → TERMINATED`, terminal). The same `TERMINATED` end-state is also reached when a covered-entity termination cascades through, as described in §3.1. A transition requested from a state that does not allow it returns `ERR_INVALID_STATE`.

### 3.5. Recording a Dispense and Determining Eligibility

A `PharmacyOperator` records a dispense by supplying a `covered_entity_id`, a `patient_id`, a `prescriber_id`, a `drug_product_id`, a `quantity_units` (integer of at least 1), a `quarter` (format `YYYYQn`), and optionally a `child_site_id` (when the dispense occurs at a child site rather than the parent site) and a `contract_pharmacy_id` (when an external contract pharmacy physically dispensed). A dispense begins with `dispense_status` of `DISPENSED`.

Before any classification runs, the dispense create enforces several preconditions in a fixed order. First, each supplied foreign key must belong to the same covered entity: the `child_site_id` (if present), the `contract_pharmacy_id` (if present), the `patient_id`, and the `prescriber_id` must all reference resources owned by `covered_entity_id`; a mismatch is rejected with `ERR_CROSS_ENTITY_MISMATCH` (HTTP 409). Next, the covered entity must be `ACTIVE`; a dispense against a non-active entity is rejected with `ERR_CE_NOT_ACTIVE` (HTTP 409), and the same guard applies when reinstating a reversed dispense. This cross-entity check is therefore evaluated before the `ERR_CE_NOT_ACTIVE` guard. Finally, if a `contract_pharmacy_id` is supplied, that arrangement's `arrangement_status` must be `ACTIVE`; a non-`ACTIVE` arrangement is rejected with `ERR_INVALID_STATE` (HTTP 409), evaluated after the `ERR_CE_NOT_ACTIVE` guard.

**The eligibility cascade.** The dispense's `classification_status` — either `CLASSIFIED_340B` or `CLASSIFIED_WAC` — together with its `eligibility_reason`, is determined by evaluating five prongs in this fixed order, where the first prong that fails determines the outcome:

1. **Relationship prong.** If the patient's `has_ce_care_record` is `false`, the dispense is `CLASSIFIED_WAC` with reason `INELIGIBLE_NO_RELATIONSHIP`.
2. **Responsibility prong.** Otherwise, if the patient's `ce_retains_responsibility` is `false`, the dispense is `CLASSIFIED_WAC` with reason `INELIGIBLE_NO_RESPONSIBILITY`.
3. **Prescriber prong.** Otherwise, if the prescriber's `relationship_type` is neither `EMPLOYED` nor `CONTRACTED` (that is, it is `REFERRAL_ONLY` or `EXTERNAL`), the dispense is `CLASSIFIED_WAC` with reason `INELIGIBLE_PRESCRIBER`.
4. **Site prong.** Otherwise, when the dispense names a `child_site_id` and that child site's `registered` flag is `false`, the dispense is `CLASSIFIED_WAC` with reason `INELIGIBLE_UNREGISTERED_SITE`. (When no child site is named, this prong is skipped.)
5. **Medicaid carve-out prong.** Otherwise, if the patient's `medicaid_ffs_enrolled` is `true` and the covered entity's `medicaid_billing_mode` is `CARVE_OUT`, the dispense is `CLASSIFIED_WAC` with reason `CARVED_OUT_MEDICAID`.

If all five prongs pass, the dispense is `CLASSIFIED_340B` with reason `ELIGIBLE_340B`.

When the cascade lands on `CLASSIFIED_340B`, the dispense must be priceable: there must be an effective ceiling-price record (published or provisional) for the `(drug_product_id, quarter)` pair. If none exists, the dispense is rejected with `ERR_NO_CEILING_PRICE` (HTTP 409).

**Pricing the line.** After classification, the system records `applied_price_per_unit_cents` and `line_cost_cents`. For a `CLASSIFIED_340B` dispense, `applied_price_per_unit_cents` is the effective ceiling price per unit selected by the rule in §3.3; for a `CLASSIFIED_WAC` dispense, it is the drug product's `wac_price_per_unit_cents`. The `line_cost_cents` is `applied_price_per_unit_cents` multiplied by `quantity_units` — an exact integer-cent product.

**The 340B accumulator cascade.** Only the 340B branch touches inventory. A `CLASSIFIED_WAC` dispense records its classification, reason, applied price, and line cost, and stops there. A `CLASSIFIED_340B` dispense, by contrast, cascades into the split-billing accumulator for its `(covered_entity_id, drug_product_id)` pair, as detailed in §3.6.

### 3.6. The Split-Billing Accumulator and Replenishment

An accumulator tracks the running balance of 340B-classified units for one `(covered_entity_id, drug_product_id)` pair that have been dispensed but not yet replenished into a whole purchasable package. It is created by a `ComplianceOfficer` or `PharmacyOperator` under a covered entity, naming the `drug_product_id` it tracks; each entity may hold at most one accumulator per drug product, so a second accumulator for an existing `(covered_entity_id, drug_product_id)` pair is rejected with `ERR_DUPLICATE_ACCUMULATOR` (HTTP 409). A fresh accumulator starts with `accrued_units` of 0, `replenished_packages_total` of 0, and `last_replenish_dispense_id` of null. It records the `covered_entity_id` that owns it and the `drug_product_id` it follows.

**Accruing and crystallising.** When a 340B dispense is created, its `quantity_units` is added to the matching accumulator's `accrued_units`, and the replenishment sweep then runs. Dispenses are applied to the accumulator in chronological order, by `created_at` ascending; record identifiers never decide ordering. The sweep compares `accrued_units` against the drug product's `package_size_units`. When `accrued_units` is greater than or equal to `package_size_units` — the boundary is inclusive, so reaching exactly the package size triggers a sweep — the system crystallises whole packages: the number of packages is the integer floor of `accrued_units` divided by `package_size_units`, computed by integer floor division; `accrued_units` is then reduced by the number of packages multiplied by `package_size_units`, leaving a remainder that always sits between 0 and one less than `package_size_units` inclusive; `replenished_packages_total` is increased by the number of packages crystallised; and `last_replenish_dispense_id` is set to the identifier of the dispense that triggered the sweep. As a side effect, the sweep creates a purchase order on the `B340B` channel for the crystallised packages, with its `accumulator_id` pointing back at this accumulator and its `unit_price_paid_cents` set to the effective ceiling price per unit.

**The virtual read versus the actual replenishment.** Reading an accumulator reports `accrued_units` as a running unit balance — a read-only projection that does not crystallise any package and creates no purchase order. The package-based actual replenishment is the operation that crystallises whole packages and emits the `B340B` purchase order. The two views diverge between package boundaries and re-converge each time a boundary is crossed.

**Manual replenishment.** A `PharmacyOperator` may also drive a replenishment sweep manually. This write is optimistic-concurrency-guarded: it must carry `expected_accumulator_version` equal to the accumulator's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.7. A successful manual sweep runs the same crystallisation logic, creates a `B340B` purchase order when a package boundary is reached, and increments the accumulator's `version`. Because no triggering dispense is named on a manual sweep, the emitted `B340B` order is priced from the drug product's most-recently-created ceiling-price record (preferring a published record over a provisional one, latest by creation), and the order's `unit_price_paid_cents` and `quarter` are taken from that record — falling back to a `unit_price_paid_cents` of 0 and a null `quarter` when the drug product has no ceiling record at all. A manual sweep leaves `last_replenish_dispense_id` at its prior value (it is not changed to name any dispense).

### 3.7. Reversing and Reinstating a Dispense; Disclosure

A `PharmacyOperator` may reverse a dispense that is currently `DISPENSED`, moving it `DISPENSED → REVERSED`. Reversal is blocked when any audit finding referencing this dispense is in `UNDER_REVIEW`, `DISPUTED`, or `RESOLVED` status (a dispense whose compliance review is in flight or already concluded may not be unwound), in which case the transition is rejected with `ERR_INVALID_STATE`. As compensation, if the dispense was `CLASSIFIED_340B`, the accumulator for its pair is debited: `accrued_units` is reduced by the dispense's `quantity_units`, preserving the accumulator invariant that the total 340B units accrued minus the replenished packages times the package size equals `accrued_units`.

A reversed dispense may be reinstated by a `PharmacyOperator`, moving it `REVERSED → DISPENSED`, but only while the owning covered entity's `registration_status` is `ACTIVE` (otherwise `ERR_CE_NOT_ACTIVE`). Reinstatement re-credits a `CLASSIFIED_340B` dispense's `quantity_units` back into the accumulator's `accrued_units` and re-runs the replenishment sweep — so the conserved quantity nets to zero across a reverse-then-reinstate pair. A dispense may cycle `DISPENSED ↔ REVERSED` through reverse and reinstate.

A dispense reaches the terminal `DISCLOSED` status when it is self-disclosed or when a finding against it is resolved (see §3.8). `DISCLOSED` is terminal: a disclosed dispense can be neither reversed nor reinstated.

### 3.8. Audit Findings, Self-Disclosure, and the Review Lifecycle

A compliance finding ties a specific dispense to a category of non-compliance. An `HrsaAuditor` raises a finding by supplying a `covered_entity_id`, a `prescription_dispense_id`, a `finding_type` (one of `DIVERSION`, `DUPLICATE_DISCOUNT`, `GPO_VIOLATION`, or `INELIGIBLE_PATIENT`), and `assessed_units` (the units of the dispense assessed as non-compliant, an integer of at least 1). An auditor-raised finding records `origin` of `HRSA_AUDIT`, begins with `finding_status` of `OPEN`, and flips the entity's `compliance_posture` to `FLAGGED`. Symmetrically, a `ComplianceOfficer` self-discloses under a covered entity by supplying a `prescription_dispense_id`, a `finding_type`, and `assessed_units`; a self-disclosure records `origin` of `SELF_DISCLOSURE`, begins `OPEN`, drives the referenced dispense `DISPENSED → DISCLOSED`, and likewise flips the entity to `FLAGGED`. In both cases `assessed_units` may not exceed the referenced dispense's `quantity_units`; an excess is rejected with `ERR_ASSESSED_UNITS_EXCEED` (HTTP 422).

The review lifecycle runs as follows. An `HrsaAuditor` starts review of an `OPEN` finding, moving it `OPEN → UNDER_REVIEW` and recomputing the entity posture (which stays `FLAGGED` while under review). From `UNDER_REVIEW`, a `ComplianceOfficer` may dispute the finding, moving it `UNDER_REVIEW → DISPUTED`; on a self-disclosed finding this is subject to segregation of duties — the disputing officer's `X-User-ID` must differ from the `X-User-ID` that created the disclosure, and a self-disputer is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A disputed finding can be sent back to review by an auditor, moving it `DISPUTED → UNDER_REVIEW`; this revision loop `UNDER_REVIEW → DISPUTED → UNDER_REVIEW` has no fixed bound, and each dispute requires a prior review. An auditor resolves an `UNDER_REVIEW` finding, moving it `UNDER_REVIEW → RESOLVED`, but only when a repayment obligation with `source_kind` of `AUDIT_FINDING` referencing this finding already exists; resolving without one set up is rejected with `ERR_REPAYMENT_REQUIRED` (HTTP 409). Resolution also drives the referenced dispense to `DISCLOSED` if it is not already terminal, and recomputes the entity posture. Finally, an auditor may dismiss a finding from either `OPEN` or `DISPUTED`, moving it to the terminal `DISMISSED` state and recomputing the entity posture. Any of these transitions attempted from a disallowed state returns `ERR_INVALID_STATE`.

### 3.9. Repayment Obligations and Remittance

A repayment obligation captures money owed and is polymorphic in its source. Its `source_kind` is either `AUDIT_FINDING` or `CEILING_RECONCILIATION`, and its `source_ref_id` resolves against an audit finding when the kind is `AUDIT_FINDING` and against a ceiling-price record when the kind is `CEILING_RECONCILIATION`. Each obligation records the `covered_entity_id` that owes it, starts with `paid_cents` of 0 and `status` of `OWED`, and exposes `remaining_balance_cents`, which is `assessed_cents` minus `paid_cents` and is never negative.

**Assessing the amount.** The `assessed_cents` has two variants. For an `AUDIT_FINDING` obligation — created against a finding via that finding's repayment operation by either an `HrsaAuditor` or a `ComplianceOfficer` — the amount is the discount the entity wrongly captured: the per-unit benefit is the drug product's `wac_price_per_unit_cents` minus the effective published ceiling price per unit for the dispense's `(drug_product_id, quarter)`, floored at zero (if the 340B price was not below WAC, no discount was captured and the per-unit benefit is zero); `assessed_cents` is that per-unit benefit multiplied by the finding's `assessed_units`. For a `CEILING_RECONCILIATION` obligation, `assessed_cents` is the total overcharge produced by the reconciliation described in §3.10. In both variants `remaining_balance_cents` initialises to `assessed_cents` because `paid_cents` starts at 0.

**Remitting.** A `ComplianceOfficer` remits toward an obligation by supplying `amount_cents`. The obligation must be in a remittable state — `OWED` or `PARTIALLY_PAID`; a remit against a `SETTLED` or `WAIVED` obligation is rejected with `ERR_INVALID_STATE` (HTTP 409), checked before the amount bounds. The amount must be greater than 0 and at most `remaining_balance_cents`; an amount of 0 or below, or an amount exceeding the remaining balance, is rejected with `ERR_REMIT_EXCEEDS_BALANCE` (HTTP 422). Each remittance adds `amount_cents` to `paid_cents` and recomputes `remaining_balance_cents`. When the remitted amount is strictly less than the remaining balance, the obligation moves to (or stays in) `PARTIALLY_PAID`; when the remitted amount exactly equals the remaining balance, the obligation moves to `SETTLED` with `remaining_balance_cents` driven to 0. An obligation may thus traverse `OWED → PARTIALLY_PAID`, repeat `PARTIALLY_PAID → PARTIALLY_PAID` across several payments, and reach `SETTLED` from either `OWED` (a single full payment) or `PARTIALLY_PAID`. Separately, an `HrsaAuditor` may waive an `OWED` obligation, moving it to the terminal `WAIVED` state with `remaining_balance_cents` set to 0; a waive attempted against any non-`OWED` obligation is rejected with `ERR_INVALID_STATE` (HTTP 409). Every remit and waive recomputes the owing entity's `open_repayment_cents` and `compliance_posture`; a settlement or waiver of the last outstanding obligation, with no findings still open, may flip the posture from `FLAGGED` back to `GOOD`.

### 3.10. Purchase Orders, GPO Prohibition, and Ceiling Reconciliation

Purchase orders are placed by a `PharmacyOperator` or `ComplianceOfficer`, and are also emitted automatically by the accumulator (§3.6). A purchase order names a `covered_entity_id`, a `drug_product_id`, a `channel` (one of `GPO`, `WAC`, or `B340B`), a `packages_ordered` (whole packages, integer of at least 1), a `quarter` (`YYYYQn`), a `unit_price_paid_cents` (the per-unit price actually paid, integer of at least 0), and optionally an `accumulator_id` (set when the order arose from a replenishment, null for a direct purchase).

**GPO prohibition.** A `GPO`-channel purchase order is rejected with `ERR_GPO_PROHIBITED` (HTTP 409) when the covered entity's `gpo_prohibited` is `true` and the drug product's `is_covered_outpatient_drug` is `true` — the GPO-prohibited hospital types may not buy covered outpatient drugs through a group purchasing organization. Orders on the `WAC` or `B340B` channel, or `GPO` orders for non-covered drugs or at non-prohibited entities, are unaffected.

**Ceiling-price reconciliation.** An `HrsaAuditor` reconciles a drug product for a quarter by supplying that `quarter` and `expected_drug_product_version`. The reconcile is optimistic-concurrency-guarded as described in §2.7, and it requires that a published ceiling-price record exist for the `(drug_product_id, quarter)` pair — a provisional-only quarter cannot be reconciled and is rejected with `ERR_NO_PUBLISHED_CEILING` (HTTP 409). The optimistic-concurrency check (`ERR_STALE_VERSION`) is evaluated before this published-ceiling check, so a stale `expected_drug_product_version` is reported even when no published ceiling exists. The system takes the effective published ceiling price per unit for the quarter, gathers every `B340B`-channel purchase order for that drug product and quarter in chronological order by `created_at` ascending (identifiers never order them), and computes the overcharge one purchase order at a time. For each such order, the unit count is its `packages_ordered` multiplied by the drug product's `package_size_units`; the per-unit overcharge is the order's `unit_price_paid_cents` minus the ceiling, floored at zero so an order bought below the ceiling contributes nothing; and that per-unit overcharge is multiplied by the unit count to give the order's overcharge. The total overcharge is the sum of these per-order overcharges. The flooring order is pinned: each order is floored at zero before summation, so an order bought below the ceiling never offsets an order bought above it — the total is a sum-of-floored values, not a floor-of-sum.

When the total overcharge is greater than zero, the reconcile creates a repayment obligation with `source_kind` of `CEILING_RECONCILIATION` whose `assessed_cents` equals that total and whose `source_ref_id` is the effective published ceiling-price record's `id`; the obligation's `covered_entity_id` is taken from the first chronological (by `created_at` ascending) `B340B` purchase order in the reconciled set, and the reconcile then recomputes that entity's `open_repayment_cents` and `compliance_posture`. The endpoint returns `201 Created` with the created obligation as its data. When the total overcharge is not greater than zero, no obligation is created and the endpoint still returns `201 Created` but with an empty object (`{}`) as its data. In both cases the reconcile increments the drug product's `version`.

### 3.11. Medicaid Claims and the Duplicate-Discount Guard

A `ComplianceOfficer` bills a dispense to Medicaid by creating a Medicaid claim against it, supplying a `medicaid_state_code` (two uppercase letters). The claim references its `prescription_dispense_id`. The system sets `claim_status` to `DUPLICATE_RISK` when the underlying dispense is `CLASSIFIED_340B` for a carve-in entity that has not listed on the Medicaid Exclusion File (because a rebate would then duplicate the 340B discount), and to `CLEAN` otherwise; `VOIDED` is the third possible value of `claim_status`.

The duplicate-discount guard blocks the genuinely impermissible case outright: a Medicaid claim may not be created against a `CLASSIFIED_340B` dispense when the covered entity's `medicaid_billing_mode` is `CARVE_OUT`, since a carve-out entity must bill Medicaid at WAC rather than at 340B. Such an attempt is rejected with `ERR_DUPLICATE_DISCOUNT` (HTTP 409). Medicaid claims on a dispense are listable, filterable by `claim_status`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions and remittances — return `200 OK`. All paths are mounted under the `/340b` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/340b/covered-entities` | Register a covered entity (starts PENDING) | ComplianceOfficer |
| GET | `/340b/covered-entities/{id}` | Fetch a covered entity | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/covered-entities` | List covered entities | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/covered-entities/{id}/approve` | Approve a pending registration | HrsaAuditor |
| POST | `/340b/covered-entities/{id}/deny` | Deny a pending registration | HrsaAuditor |
| POST | `/340b/covered-entities/{id}/flag-recert` | Flag an active CE recertification-due | HrsaAuditor |
| POST | `/340b/covered-entities/{id}/recertify` | Complete recertification | ComplianceOfficer |
| POST | `/340b/covered-entities/{id}/terminate` | Terminate a CE; cascades to contract pharmacies | HrsaAuditor |
| POST | `/340b/covered-entities/{id}/child-sites` | Register a child site under a CE | ComplianceOfficer |
| GET | `/340b/covered-entities/{id}/child-sites` | List child sites of a CE | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/child-sites/{id}` | Fetch a child site | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/covered-entities/{id}/prescribers` | Register a prescriber under a CE | ComplianceOfficer |
| GET | `/340b/prescribers` | List prescribers | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/prescribers/{id}` | Fetch a prescriber | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/covered-entities/{id}/patients` | Register a patient under a CE | ComplianceOfficer, PharmacyOperator |
| GET | `/340b/patients` | List patients | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/patients/{id}` | Fetch a patient | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/drug-products` | Create a drug product | ComplianceOfficer, HrsaAuditor |
| GET | `/340b/drug-products/{id}` | Fetch a drug product | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/drug-products/{id}/ceiling-prices` | Add a quarterly ceiling-price record | ComplianceOfficer, HrsaAuditor |
| GET | `/340b/drug-products/{id}/ceiling-prices` | List ceiling-price records | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/drug-products/{id}/ceiling-prices/effective` | Effective ceiling for (product, quarter) | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/drug-products/{id}/reconcile` | OCC-guarded overcharge reconciliation | HrsaAuditor |
| POST | `/340b/covered-entities/{id}/contract-pharmacies` | Create a contract-pharmacy arrangement | ComplianceOfficer |
| GET | `/340b/covered-entities/{id}/contract-pharmacies` | List contract pharmacies of a CE | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/contract-pharmacies/{id}` | Fetch a contract-pharmacy arrangement | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/contract-pharmacies/{id}/suspend` | Suspend an arrangement | ComplianceOfficer |
| POST | `/340b/contract-pharmacies/{id}/reactivate` | Reactivate a suspended arrangement | ComplianceOfficer |
| POST | `/340b/contract-pharmacies/{id}/terminate` | Terminate an arrangement | ComplianceOfficer |
| POST | `/340b/covered-entities/{id}/accumulators` | Create a split-billing accumulator | ComplianceOfficer, PharmacyOperator |
| GET | `/340b/covered-entities/{id}/accumulators` | List accumulators of a CE | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/accumulators` | List accumulators | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/accumulators/{id}` | Fetch an accumulator (virtual read) | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/accumulators/{id}/replenish` | OCC-guarded manual replenishment sweep | PharmacyOperator |
| POST | `/340b/dispenses` | Record a dispense | PharmacyOperator |
| GET | `/340b/dispenses/{id}` | Fetch a dispense | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| GET | `/340b/dispenses` | List dispenses | ComplianceOfficer, HrsaAuditor, PharmacyOperator |
| POST | `/340b/dispenses/{id}/reverse` | Reverse a dispense | PharmacyOperator |
| POST | `/340b/dispenses/{id}/reinstate` | Reinstate a reversed dispense | PharmacyOperator |
| POST | `/340b/dispenses/{id}/medicaid-claims` | Bill a dispense to Medicaid | ComplianceOfficer |
| GET | `/340b/dispenses/{id}/medicaid-claims` | List Medicaid claims on a dispense | ComplianceOfficer, HrsaAuditor |
| POST | `/340b/audit-findings` | Raise an HRSA finding against a dispense | HrsaAuditor |
| POST | `/340b/covered-entities/{id}/self-disclosures` | Self-disclose a finding; marks dispense DISCLOSED | ComplianceOfficer |
| GET | `/340b/audit-findings/{id}` | Fetch an audit finding | ComplianceOfficer, HrsaAuditor |
| GET | `/340b/covered-entities/{id}/audit-findings` | List audit findings of a CE | ComplianceOfficer, HrsaAuditor |
| GET | `/340b/audit-findings` | List audit findings | ComplianceOfficer, HrsaAuditor |
| POST | `/340b/audit-findings/{id}/start-review` | Move a finding into review | HrsaAuditor |
| POST | `/340b/audit-findings/{id}/dispute` | Dispute an under-review finding | ComplianceOfficer |
| POST | `/340b/audit-findings/{id}/resolve` | Resolve an under-review finding | HrsaAuditor |
| POST | `/340b/audit-findings/{id}/dismiss` | Dismiss a finding | HrsaAuditor |
| POST | `/340b/audit-findings/{id}/repayments` | Create the repayment obligation for a finding | HrsaAuditor, ComplianceOfficer |
| GET | `/340b/repayment-obligations/{id}` | Fetch a repayment obligation | ComplianceOfficer, HrsaAuditor |
| GET | `/340b/covered-entities/{id}/repayment-obligations` | List repayment obligations of a CE | ComplianceOfficer, HrsaAuditor |
| GET | `/340b/repayment-obligations` | List repayment obligations | ComplianceOfficer, HrsaAuditor |
| POST | `/340b/repayment-obligations/{id}/remit` | Remit a payment toward an obligation | ComplianceOfficer |
| POST | `/340b/repayment-obligations/{id}/waive` | Waive an obligation | HrsaAuditor |
| POST | `/340b/purchase-orders` | Place a purchase order; GPO-prohibition guarded | PharmacyOperator, ComplianceOfficer |
| GET | `/340b/purchase-orders/{id}` | Fetch a purchase order | PharmacyOperator, ComplianceOfficer, HrsaAuditor |
| GET | `/340b/purchase-orders` | List purchase orders | PharmacyOperator, ComplianceOfficer, HrsaAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_CROSS_ENTITY_MISMATCH` | 409 |
| `ERR_MEF_NUMBER_REQUIRED` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CE_NOT_ACTIVE` | 409 |
| `ERR_GPO_PROHIBITED` | 409 |
| `ERR_DUPLICATE_DISCOUNT` | 409 |
| `ERR_NO_CEILING_PRICE` | 409 |
| `ERR_ASSESSED_UNITS_EXCEED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_REMIT_EXCEEDS_BALANCE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NO_PUBLISHED_CEILING` | 409 |
| `ERR_REPAYMENT_REQUIRED` | 409 |
| `ERR_DUPLICATE_HRSA_ID` | 409 |
| `ERR_DUPLICATE_NDC` | 409 |
| `ERR_DUPLICATE_ACCUMULATOR` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
| `ERR_CP_WINDOW_OVERLAP` | 409 |
| `ERR_CEILING_QUARTER_OVERLAP` | 409 |

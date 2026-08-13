# Mattress Law Label API — Product Requirements Document

## 1. Introduction

A licensee mattress plant building Serta-branded product sells wholesale to retail partners across the United States, and every unit that crosses a state line carries a law label whose mandated statutory phrases, filling-material declarations, and warning blocks differ by destination state. No model may be built or shipped without a valid federal open-flame flammability certificate, and California-bound product must additionally respect Prop 65 warning rules. Around this regulatory spine the plant runs a full production floor — foam pours with temperature-adjusted cure windows and chamber capacity limits, quilt-panel scheduling across machines — plus the commercial afterlife of the product: a 100-night comfort-exchange program, a warranty keyed on measured sag depth, and a recycling take-back program that pays retailers for recovered material through a credit ledger.

This document specifies the Mattress Law Label API, mounted under the `/plant` path prefix. It covers retailer account and credit-ledger management; mattress model authoring with a bill of materials; compliance certificates with a segregation-of-duties approval loop and a three-hop revocation cascade; per-state law-label specifications and the labels generated from them; foam batch curing with quarantine and re-cure cycles; quilt run scheduling; production orders tracked on two parallel status dimensions; shipments and fulfillment; returns, warranty claims, and recycling intakes. All time-dependent behavior — cure eligibility, certificate expiry, the comfort window, warranty age — reads a controllable logical clock rather than wall-clock time, so that regulatory timelines can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if the role value is not one of the declared role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the caller's role is well-formed but not in the endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles are declared, spelled exactly as follows: `PlantManager`, `ComplianceOfficer`, `LineSupervisor`, `QcInspector`, `Retailer`, and `LogisticsCoordinator`.

- A `PlantManager` is the plant general manager: owns models, the bill of materials, retailer registration, order cancellation, claim adjudication, intake finalization, the credit ledger, and the logical clock.
- A `ComplianceOfficer` is the regulatory affairs officer: owns law-label specs, certificates, law labels, and model certification.
- A `LineSupervisor` runs the production floor: pours foam, manages cure chambers, schedules quilt runs, and drives the production pipeline.
- A `QcInspector` certifies cures (never their own pours), quarantines batches, gates orders through QC, and receives and inspects returns.
- A `Retailer` is a retail partner account: places its own orders and opens comfort-exchange returns and warranty claims for its own units.
- A `LogisticsCoordinator` runs shipping and reverse logistics: creates, dispatches, and delivers shipments and records recycling take-back intakes.

When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of the acting `Retailer`; ownership checks on any resource that references a `Retailer` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlantManager`, `ComplianceOfficer`, `LineSupervisor`, `QcInspector`, or `LogisticsCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by_user_id` on a certificate, `created_by_user_id` on a law label, or `poured_by_user_id` on a foam batch) but does not compare it to any entity's `id`.

All read endpoints (every GET) are shared: all six roles may list and retrieve resources. Write operations are role-restricted per the endpoint table in §4.

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

Every list endpoint accepts two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0. List results are always sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, alongside `api_request_id` and `api_request_timestamp`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and an integer `version` that increments by one on every mutation of that resource. One entity deviates: `CreditAdjustment` is an append-only ledger entry and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, because ledger entries are never modified after posting.

Several entities document their version as a coherence boundary for related writes. A `MattressModel`'s `version` increments on every lifecycle transition (submit, return-to-draft, certify, activate, discontinue), on every BOM line creation or edit, and on every law label generated against it, because label content derives from the BOM. A `Retailer`'s `version` increments on every credit adjustment posted to its ledger, whether manual or cascaded.

### 2.5. The Plant Logical Clock

The server maintains a logical clock that governs every time-dependent rule in this document: cure eligibility, certificate expiry, comfort windows, and warranty age all read this clock. Before it has ever been set, the logical clock reads exactly 2026-08-01T00:00:00Z; the server never falls back to wall-clock time. A `PlantManager`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. Advancing the clock across a certificate's `expires_on` may transition that certificate to `EXPIRED` — expiry is applied lazily, on any read or validation touch of the certificate, and never cascades (see §3.3).

### 2.6. Money, Mass, and Rounding Discipline

All monetary amounts are integer cents. Wherever a calculation involves rounding, the method is round half up, and it is applied exactly where the rule pins it — per BOM line before summing into the model cost, and per recycling material line before summing into a final credit. The order compliance fee is tiered on the order subtotal before the fee itself is added, never on the post-fee total. Deviating from these pinned evaluation orders produces different cent values and is not the contract.

Foam mass obeys a conservation invariant on every batch: at all times, `poured_mass_kg` equals the sum of `available_mass_kg`, `reserved_mass_kg`, `consumed_mass_kg`, and `scrapped_mass_kg`. Every material move in §3.5 and §3.7 (allocation, production start, cancellation release, scrap write-off) preserves this invariant.

### 2.7. Optimistic Concurrency Control

Three write operations take a mandatory expected-version field, carrying the client's last observed `version` of the parent entity. If that value does not equal the parent entity's current `version` at write time, the request is rejected with `ERR_STALE_VERSION` (HTTP 412):

- Generating a law label against a model requires `expected_model_version` matching the model's current `version`. Label generation itself bumps the model's version — the label's content derives from the BOM, so the model is the coherence boundary — and a generator holding a stale version has an out-of-date view of the BOM the label would be rendered from.
- Editing a BOM line requires `expected_model_version` matching the parent model's current `version`, because BOM edits change `bom_cost_cents` and any future label content, and each edit bumps the model's version.
- Posting a manual credit adjustment to a retailer requires `expected_retailer_version` matching the retailer's current `version`, because every adjustment recomputes `credit_balance_cents` and bumps the retailer's version; a client computing a top-up from a stale balance is rejected rather than allowed to compound on an outdated base.

No endpoint other than these three takes a version field.

### 2.8. Validation Order and Nested Path Resolution

Every request is evaluated against a fixed pipeline of twelve validation tiers, and an earlier tier masks later ones — a failure surfaces the error of the earliest tier it violates, and only a request clean through a tier reaches the next:

1. Header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`, 403).
3. Path resource existence, resolved left-to-right — on nested paths the parent `modelId` is resolved before any `lineId`, `certId`, or `labelId` beneath it, and `retailerId` before any ledger scope beneath it. Unknown ids produce the resource's dedicated 404: `ERR_MODEL_NOT_FOUND`, `ERR_BOM_LINE_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_LABEL_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_FOAM_BATCH_NOT_FOUND`, `ERR_QUILT_RUN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_INTAKE_NOT_FOUND`. A body-supplied unit reference that does not exist also resolves as `ERR_UNIT_NOT_FOUND`.
4. Request-body well-formedness (`ERR_VALIDATION_FAILED`, 400): required input fields present, enum values valid, `quantity` at least 1, masses strictly greater than zero, `unit_price_cents` strictly greater than zero, `expires_on` strictly after `issued_on`. A quilt window whose `end_at` is not strictly after `start_at` fails this tier as `ERR_INVALID_TIME_RANGE` (400).
5. State preconditions for the requested transition (the per-machine `ERR_*_NOT_*` errors, 409 — for example `ERR_MODEL_NOT_DRAFT`, `ERR_BATCH_NOT_CURING`, `ERR_CLAIM_NOT_FILED`).
6. Regulatory gates (409): `ERR_CERT_REQUIRED`, `ERR_LABEL_NOT_ACTIVE`, `ERR_CERT_EXPIRED`, `ERR_SPEC_SUPERSEDED`, `ERR_SPEC_NOT_PUBLISHED`, `ERR_CURE_INCOMPLETE`.
7. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403).
8. Resource and program constraints (409): `ERR_MACHINE_TIME_CONFLICT`, `ERR_CHAMBER_CAPACITY_EXCEEDED`, `ERR_DROPSHIP_NOT_ENABLED`, `ERR_RECYCLING_NOT_ENROLLED`, `ERR_MODEL_HAS_NO_BOM`, `ERR_OPEN_ORDERS_EXIST`, `ERR_RESOLUTION_REASON_MISMATCH`.
9. Temporal gates (409): `ERR_OUTSIDE_COMFORT_WINDOW`, `ERR_RUN_WINDOW_NOT_REACHED`.
10. Cross-entity referential integrity (422): `ERR_UNIT_ORDER_MISMATCH`, `ERR_RETAILER_UNIT_MISMATCH`, `ERR_RETAILER_IDENTITY_MISMATCH`, `ERR_UNIT_NOT_SCRAPPED`, `ERR_SAG_BELOW_THRESHOLD`.
11. Fiscal caps (402): `ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_INSUFFICIENT_FOAM_MASS`.
12. Optimistic concurrency (`ERR_STALE_VERSION`, 412).

Two consequences worth internalizing: a submit-for-certification on a model that is both non-`DRAFT` and BOM-less surfaces `ERR_MODEL_NOT_DRAFT` (tier 5), not `ERR_MODEL_HAS_NO_BOM` (tier 8); and a certificate approval by the submitter of a certificate that is not `SUBMITTED` surfaces `ERR_CERT_NOT_SUBMITTED` (tier 5), not the segregation error (tier 7).

### 2.9. Segregation of Regulatory Duties

Three approval-style operations are barred for the operator who created the artifact, and the rule binds at tier 7 of the pipeline above. A certificate may not be approved by the `X-User-ID` recorded as its `submitted_by_user_id`. A law label may not be approved or rejected by the `X-User-ID` recorded as its `created_by_user_id`. A foam batch's cure may not be certified by the `X-User-ID` recorded as its `poured_by_user_id`. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); on success, the approver or certifier identity is stamped onto the resource (`approved_by_user_id` on certificates and labels, `certified_by_user_id` on batches).

## 3. Business Logic & Workflows

### 3.1. Retailer Onboarding and the Credit Ledger

A `PlantManager` registers each retail partner with its legal `retailer_name`, two program flags — `drop_ship_enabled` (whether the retailer may place `DROP_SHIP` orders) and `recycling_enrolled` (whether it participates in the take-back program) — and a `credit_limit_cents` cap. The account opens with `credit_balance_cents` at zero. The retailer roster can be listed with filters on `drop_ship_enabled` and `recycling_enrolled`, and any individual retailer can be fetched by id.

Every movement of retailer credit is a `CreditAdjustment` — an append-only ledger entry recording `retailer_id`, the signed `amount_cents` (positive grants credit, negative claws it back), a free-text `reason` for manual entries (system text for cascaded ones), a `source` drawn from `MANUAL`, `WARRANTY_PAYOUT`, `RECYCLING_PROVISIONAL`, `RECYCLING_FINAL_DELTA`, or `EXCHANGE_RECOVERY`, and a `source_id` pointing at the originating warranty claim or recycling intake for cascaded entries (null for `MANUAL`). The retailer's `credit_balance_cents` is maintained as the sum of all its adjustments' `amount_cents`, recomputed on every posting, and each posting — manual or cascaded — increments the retailer's `version` by one. The ledger for a retailer can be listed at any time.

A `PlantManager` posts a manual adjustment by supplying `amount_cents`, a `reason`, and `expected_retailer_version` per the optimistic-concurrency rule of §2.7; a stale version is rejected with `ERR_STALE_VERSION` (412). Manual entries post with source `MANUAL` and a null `source_id`.

The credit cap is absolute: `credit_balance_cents` may never exceed `credit_limit_cents`. The cap is actively enforced at two posting points — when a recycling intake posts its provisional credit at creation, and when an approved warranty claim is paid. In both cases, a posting that would push the balance above the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) and nothing is recorded.

### 3.2. Model Authoring and the Bill of Materials

A `PlantManager` authors a mattress model by supplying a `model_code` — the plant's model code, such as SRT-PLUSH-QN, unique across all models — and the `quilt_pattern` identifier used by panel scheduling. The model is born in `DRAFT` status with `bom_cost_cents` initialized to zero. The model catalog can be listed with a `status` filter or fetched by id.

While a model remains `DRAFT`, the manager builds out its bill of materials one line at a time. Each line carries a `component_type` — one of `FOAM_CORE`, `MEMORY_LAYER`, `FIRE_BARRIER`, `TICKING`, `QUILT_PANEL`, `FOUNDATION`, or `THREAD` — a supplier `material_code`, a `quantity_per_unit` that may be fractional but must be greater than zero, and a `unit_cost_cents` that must be zero or greater. Lines whose component is a filling type — `FOAM_CORE`, `MEMORY_LAYER`, `FIRE_BARRIER`, or `TICKING` — must also carry a `filling_content_code` such as PU_FOAM_62 or POLY_FIBER_18; for all other component types the field is null. Adding or editing a line on a model that has left `DRAFT` is rejected with `ERR_MODEL_NOT_DRAFT` (409).

Each line's `line_cost_cents` is the product of `quantity_per_unit` and `unit_cost_cents`, rounded half up to integer cents. The model's `bom_cost_cents` is then the sum of those per-line rounded values across every line of the model, regardless of component type. The rounding order is pinned — round each line first, then sum; summing the unrounded products and rounding once at the end yields different cents and is not the contract. The cost recomputes on every line creation and every line edit, and each such write increments the model's `version` by one. Editing an existing line — changing `quantity_per_unit`, `unit_cost_cents`, or both — additionally requires `expected_model_version` matching the model's current `version`, with stale values rejected as `ERR_STALE_VERSION` (412) per §2.7.

### 3.3. Certificates, Model Certification, and the Revocation Cascade

A model's regulatory lifecycle runs `DRAFT` → `CERT_REVIEW` → `CERTIFIED` → `ACTIVE` → `DISCONTINUED`, with one revert loop and one involuntary cascade path. Every transition increments the model's `version` by one.

Submitting a model for certification moves it from `DRAFT` to `CERT_REVIEW`; the model must have at least one BOM line, otherwise the submission is rejected with `ERR_MODEL_HAS_NO_BOM` (409) — and, per the pipeline order of §2.8, a model not in `DRAFT` is rejected earlier with `ERR_MODEL_NOT_DRAFT`. If review surfaces a spec problem, a `PlantManager` can return the model from `CERT_REVIEW` to `DRAFT`; a model not in `CERT_REVIEW` answers `ERR_MODEL_NOT_CERT_REVIEW` (409).

Certificates are filed against a model while it sits in `CERT_REVIEW` (filing against a model in any other status fails with `ERR_MODEL_NOT_CERT_REVIEW`). A `ComplianceOfficer` submits each certificate with a `cert_type` — `FLAMMABILITY_16CFR1633`, `PROP65_CA`, or `TB117` — a `jurisdiction_state_code` (the two-letter state code the certificate covers; `FLAMMABILITY_16CFR1633` is federal and uses the state code `US`), and the `issued_on` / `expires_on` timestamps, with `expires_on` required to be strictly after `issued_on`. The certificate is born `SUBMITTED`, with `submitted_by_user_id` stamped from the caller and `approved_by_user_id` null until approval. A model's certificate set can be listed with a `status` filter.

A second `ComplianceOfficer` — never the submitter, per §2.9 — approves a `SUBMITTED` certificate, moving it to `APPROVED` and stamping `approved_by_user_id`; a certificate not in `SUBMITTED` answers `ERR_CERT_NOT_SUBMITTED`. Approval by the submitter is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). An `APPROVED` certificate can later be revoked by a `ComplianceOfficer`, moving it to `REVOKED` (a certificate not in `APPROVED` answers `ERR_CERT_NOT_APPROVED`), and revocation is the trigger for the plant's most dangerous cascade, described below. Independently of revocation, when the logical clock passes a certificate's `expires_on`, the certificate transitions `APPROVED` → `EXPIRED`, applied lazily on any read or validation touch. Expiry never cascades: existing law labels keep their status and units already manufactured remain valid. Expiry only blocks new shipments (with `ERR_CERT_EXPIRED`) and new model certifications (with `ERR_CERT_REQUIRED`). Only an explicit revoke cascades.

Certification proper is a `ComplianceOfficer` action moving the model `CERT_REVIEW` → `CERTIFIED`. It requires at least one `APPROVED` `FLAMMABILITY_16CFR1633` certificate on the model whose `expires_on` is strictly after the logical clock; without one the certification is rejected with `ERR_CERT_REQUIRED` (409). A `PlantManager` then activates the model (`CERTIFIED` → `ACTIVE`; a model not `CERTIFIED` answers `ERR_MODEL_NOT_CERTIFIED`), making it orderable. Discontinuing moves `ACTIVE` → `DISCONTINUED` and is refused with `ERR_OPEN_ORDERS_EXIST` (409) while any production order for the model sits in `PLANNED`, `MATERIAL_ALLOCATED`, `IN_PRODUCTION`, `QC_PENDING`, or `QC_HOLD`.

The revocation cascade runs three hops. When a revoked certificate was the model's last `APPROVED` unexpired `FLAMMABILITY_16CFR1633` certificate, hop one moves the model from `CERTIFIED` or `ACTIVE` back to `CERT_REVIEW`, incrementing its `version`. Hop two supersedes the model's paperwork: every law label of the model in `GENERATED`, `APPROVED`, or `ACTIVE` moves to `SUPERSEDED`. Hop three reaches the floor: each superseded label pushes every production order with `production_status` in `MATERIAL_ALLOCATED`, `IN_PRODUCTION`, or `QC_PENDING` whose `destination_state_code` equals that label's `state_code` into `QC_HOLD`. An order already in `QC_HOLD` or beyond stays where it is.

### 3.4. State Law-Label Specifications and the Label Lifecycle

A `ComplianceOfficer` authors each state's label law as a `StateLawLabelSpec`, born `DRAFT`, carrying the two-letter `state_code` it governs, an ordered list of `filling_content_codes` the label must declare, an ordered list of `required_phrases` that must appear verbatim, and a `prop65_warning_required` flag for the California warning block. Specs can be listed with `state_code` and `status` filters or fetched by id; the labels pinned to a given spec can also be listed beneath it.

Publishing a spec moves `DRAFT` → `PUBLISHED` (a spec not in `DRAFT` answers `ERR_SPEC_NOT_DRAFT`) and simultaneously moves any other `PUBLISHED` spec for the same `state_code` to `SUPERSEDED`, so at most one spec per state is ever published.

Label generation is a `ComplianceOfficer` action against a specific model, accepted only while the model is `CERTIFIED` or `ACTIVE` — a model in any other status rejects it with `ERR_MODEL_NOT_CERTIFIED`. The request names the destination `state_code` and carries `expected_model_version` per §2.7. There must be a `PUBLISHED` spec for that state, otherwise the generation fails with `ERR_SPEC_NOT_PUBLISHED` (409). On success the label pins `spec_id` to that published spec and `spec_version` to the spec's version at generation time — a pin that never changes afterward — and renders `content_text` as the spec's `required_phrases` joined in order, followed by the intersection of the spec's `filling_content_codes` with the model BOM's `filling_content_code` values in BOM line creation order (`created_at` ascending), followed by the Prop 65 warning block if and only if the spec's `prop65_warning_required` is true. The generator's identity lands in `created_by_user_id`, `approved_by_user_id` stays null until approval, generation increments the model's `version` by one, and the label is born `GENERATED`. Labels can be listed per model with `state_code` and `status` filters, or browsed across models with additional `model_id` and `spec_id` filters.

Approval and rejection form the second segregation-of-duties gate: a different `ComplianceOfficer` than the creator moves a `GENERATED` label to `APPROVED` (stamping `approved_by_user_id`) or to `REJECTED`; either action on a non-`GENERATED` label answers `ERR_LABEL_NOT_GENERATED`, and either action by the creator answers `ERR_SEGREGATION_OF_DUTIES` (403).

Activation moves `APPROVED` → `ACTIVE` under two regulatory preconditions, evaluated after the state check (`ERR_LABEL_NOT_APPROVED` for a label not in `APPROVED`): the pinned spec must still be `PUBLISHED` — a label pinned to a since-superseded spec is rejected with `ERR_SPEC_SUPERSEDED` — and the model must be `CERTIFIED` or `ACTIVE` (`ERR_MODEL_NOT_CERTIFIED`). Activating a label supersedes any other `ACTIVE` label for the same model and `state_code`; this voluntary replacement holds no production orders, unlike the revoke cascade of §3.3, which moves labels in `GENERATED`, `APPROVED`, or `ACTIVE` to `SUPERSEDED` and pushes matching open orders into `QC_HOLD`.

### 3.5. Foam Lots, Cure Chambers, and Quarantine

A `LineSupervisor` pours a foam lot by naming its `foam_density_class` — `STANDARD`, `HIGH_DENSITY`, or `MEMORY` — the `poured_mass_kg` (strictly greater than zero), and the `chamber_id` of the cure chamber it will occupy. The batch is born `POURED`: `available_mass_kg` initializes to the full `poured_mass_kg`; `reserved_mass_kg`, `consumed_mass_kg`, and `scrapped_mass_kg` initialize to zero; `cure_cycles` starts at zero; `cure_started_at` stays null until the first cure begins; and `poured_by_user_id` records the caller. Batch lists support `status` and `chamber_id` filters.

Starting the cure moves `POURED` → `CURING` (a batch not in `POURED` answers `ERR_BATCH_NOT_POURED`). The operator supplies an `ambient_temp_c` reading; the server stamps `cure_started_at` from the logical clock, increments `cure_cycles` by one, and computes `cure_eligible_at` as `cure_started_at` plus a base cure length by density class — 24 hours for `STANDARD`, 48 hours for `HIGH_DENSITY`, 72 hours for `MEMORY` — plus an ambient adjustment: when `ambient_temp_c` is below 18 °C, twelve hours are added; when it lies between 18 °C and 27 °C inclusive on both ends, nothing is added; when it exceeds 27 °C, six hours are subtracted.

The chamber is a capacity-limited resource: at most three batches may cure concurrently with overlapping windows on the same `chamber_id`. The incoming batch's estimated window runs from the current logical clock to the clock plus its total cure length (base plus ambient adjustment), end-exclusive. If two or more other batches are already `CURING` on the same chamber whose [`cure_started_at`, `cure_eligible_at`) windows overlap that estimated window, the start is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED` (409) — so a batch may become the third concurrent occupant of its chamber, never the fourth. Two windows overlap only when each starts strictly before the other ends; windows that merely touch at an endpoint do not overlap. Batches in `POURED`, `QUARANTINED`, or `CURED` never count as occupants.

Certifying the cure is a `QcInspector` action moving `CURING` → `CURED` (any other status answers `ERR_BATCH_NOT_CURING`). The logical clock must be at or after `cure_eligible_at` — the boundary is inclusive, so exact equality passes; a strictly earlier clock is rejected with `ERR_CURE_INCOMPLETE` (409). The certifier must differ from the batch's `poured_by_user_id`, per §2.9, with violations rejected as `ERR_SEGREGATION_OF_DUTIES`; success stamps `certified_by_user_id`.

Quality doubt routes a `CURING` batch to quarantine (`CURING` → `QUARANTINED`, again `ERR_BATCH_NOT_CURING`-guarded), a `QcInspector` decision with no further preconditions. From quarantine there are two exits. A `LineSupervisor` may release the batch back to cure (`QUARANTINED` → `CURING`; `ERR_BATCH_NOT_QUARANTINED` guards both quarantine exits): the re-cure increments `cure_cycles` by one and extends `cure_eligible_at` by twelve hours while leaving `cure_started_at` untouched, and the returning batch does not re-run the chamber capacity check against its own previous window, because it left `CURING` at quarantine. Alternatively, a `QcInspector` scraps the batch (`QUARANTINED` → `SCRAPPED`): `scrapped_mass_kg` becomes the full `available_mass_kg` and `available_mass_kg` drops to zero, preserving the mass-conservation invariant of §2.6.

A batch's terminal consumption is automatic: when a production start leaves the batch with `available_mass_kg` equal to zero and `reserved_mass_kg` equal to zero, the batch moves `CURED` → `CONSUMED` on its own.

### 3.6. Quilt Panel Scheduling

Panel production is scheduled per machine. A `LineSupervisor` books a quilt run naming the production `order_id` the panels are quilted for, the `machine_id`, the mattress `size` — `TWIN`, `FULL`, `QUEEN`, `KING`, or `CAL_KING` — and a window from `start_at` to `end_at`. The window is half-open, with `end_at` exclusive, and `start_at` must be strictly before `end_at`; a degenerate or reversed window is rejected with `ERR_INVALID_TIME_RANGE` (400).

Machine time is pairwise exclusive among live runs. A new run conflicts with an existing one on the same `machine_id` — and is rejected with `ERR_MACHINE_TIME_CONFLICT` (409) — when the existing run is `SCHEDULED` or `RUNNING` and its `start_at` is strictly before the new run's `end_at` while the new run's `start_at` is strictly before the existing run's `end_at`. Adjacency is explicitly allowed: a new run whose `start_at` equals an existing run's `end_at` may be booked back-to-back with zero gap. `COMPLETE` and `CANCELLED` runs never block new bookings. Run lists filter by `machine_id`, `order_id`, and `status`.

The run lifecycle itself is simple. A run is born `SCHEDULED`. Starting it moves `SCHEDULED` → `RUNNING`, but only once the logical clock has reached `start_at` — an early start is rejected with `ERR_RUN_WINDOW_NOT_REACHED` (409), and a run not in `SCHEDULED` answers `ERR_RUN_NOT_SCHEDULED`. Completing moves `RUNNING` → `COMPLETE` (guarded by `ERR_RUN_NOT_RUNNING`), and a still-`SCHEDULED` run may instead be cancelled into `CANCELLED` (`ERR_RUN_NOT_SCHEDULED` again guards the source state).

### 3.7. Production Orders: Allocation, Build, and Quality Gate

A production order is placed by a `PlantManager`, or by a `Retailer` ordering for itself, with `model_id`, `retailer_id`, `destination_state_code`, `quantity` (at least one), `unit_price_cents` (strictly positive), `foam_mass_required_kg` (strictly positive), and `ship_method` — `WAREHOUSE` or `DROP_SHIP`. The model must be `ACTIVE`, otherwise creation fails with `ERR_MODEL_NOT_ACTIVE` (409). A `DROP_SHIP` order requires the retailer's `drop_ship_enabled` flag (`ERR_DROPSHIP_NOT_ENABLED`, 409). A `Retailer` caller must pass its own id as `retailer_id`; referencing any other retailer is rejected with `ERR_RETAILER_IDENTITY_MISMATCH` (422). The order is born with `production_status` `PLANNED` and `fulfillment_status` `UNFULFILLED` — two independent, parallel status dimensions — and `foam_batch_id` unset until allocation.

Pricing is computed at creation in a pinned evaluation order. First, `subtotal_cents` is `quantity` multiplied by `unit_price_cents`. Second, `compliance_fee_cents` is tiered on that subtotal: a subtotal under 100,000 cents carries a 500-cent fee; a subtotal of at least 100,000 cents but under 500,000 cents carries 1,500 cents; a subtotal of 500,000 cents or more carries 3,000 cents. Both tier boundaries are inclusive of the tier they open. Third, `total_cents` is the subtotal plus the fee. The tier is always keyed on the subtotal before the fee is added — never on the total. Order lists filter by `model_id`, `retailer_id`, `foam_batch_id`, `production_status`, and `fulfillment_status`.

Allocating materials moves `PLANNED` → `MATERIAL_ALLOCATED` (an order not in `PLANNED` answers `ERR_ORDER_NOT_PLANNED`). A `LineSupervisor` names the `foam_batch_id` to draw from; that batch must be `CURED` (`ERR_BATCH_NOT_CURED`) and its `available_mass_kg` must be at least the order's `foam_mass_required_kg` — otherwise the allocation is rejected with `ERR_INSUFFICIENT_FOAM_MASS` (402). The required mass moves out of `available_mass_kg` and into `reserved_mass_kg` on the batch, preserving the conservation invariant.

Starting production moves `MATERIAL_ALLOCATED` → `IN_PRODUCTION` (`ERR_ORDER_NOT_MATERIAL_ALLOCATED` guards the source state). The gate is regulatory: an `ACTIVE` law label must exist for the order's model and `destination_state_code`, otherwise the start is rejected with `ERR_LABEL_NOT_ACTIVE` (409). On success the reserved mass converts — `reserved_mass_kg` decreases by the required amount and `consumed_mass_kg` increases by the same — and if the batch is thereby fully drained (zero available and zero reserved), it auto-transitions `CURED` → `CONSUMED` as described in §3.5.

Completing production moves `IN_PRODUCTION` → `QC_PENDING` (`ERR_ORDER_NOT_IN_PRODUCTION`) and manufactures the order's `quantity` of mattress units. Each unit is born `MANUFACTURED` with a server-assigned `serial_no` that is sequential within the order — an order-sequence prefix followed by a zero-padded counter, as in `<order_seq>-0001`. Every unit copies `model_id` and `retailer_id` from its order, records the `foam_batch_id` that supplied its foam, pins the currently `ACTIVE` law label for the model and destination state as its `law_label_id`, and stamps `purchase_price_cents` from the order's `unit_price_cents` — the later basis for warranty credit. The unit's `delivered_at` stays null until delivery.

The quality gate belongs to the `QcInspector`. Passing moves `QC_PENDING` → `COMPLETE`; holding moves `QC_PENDING` → `QC_HOLD`; both are guarded by `ERR_ORDER_NOT_QC_PENDING`. Releasing a hold returns `QC_HOLD` → `QC_PENDING` (`ERR_ORDER_NOT_QC_HOLD`). Independently of the inspector, the certificate-revocation cascade of §3.3 can push an order from `MATERIAL_ALLOCATED`, `IN_PRODUCTION`, or `QC_PENDING` into `QC_HOLD` when its destination state's `ACTIVE` label is superseded by the cascade.

A `PlantManager` may cancel an order while it is `PLANNED` or `MATERIAL_ALLOCATED`; any other status answers `ERR_ORDER_NOT_CANCELLABLE` (409). Cancelling an allocated order releases its foam reservation: `reserved_mass_kg` decreases by the required amount and `available_mass_kg` increases by the same, keeping the batch's mass ledger whole.

### 3.8. Shipments and Order Fulfillment

Once an order is `COMPLETE`, a `LogisticsCoordinator` builds a shipment from an explicit, non-empty `unit_ids` list against the order's `order_id`. Creation enforces a stack of gates in the pipeline order of §2.8: the order must be in `production_status` `COMPLETE` (`ERR_ORDER_NOT_COMPLETE`); an `ACTIVE` law label must exist for the order's model and destination state (`ERR_LABEL_NOT_ACTIVE`); the model's flammability certificate must be `APPROVED` and unexpired at shipment time — expired or absent, it is `ERR_CERT_EXPIRED`; and every listed unit must belong to the shipment's order (`ERR_UNIT_ORDER_MISMATCH`, 422) and be in `MANUFACTURED` status (`ERR_UNITS_NOT_MANUFACTURED`, 409). The shipment copies `retailer_id` and `destination_state_code` from its order and is born `CREATED`. Shipment lists filter by `order_id`, `retailer_id`, and `status`.

Dispatching a shipment (moving it `CREATED` → `DISPATCHED`; guarded by `ERR_SHIPMENT_NOT_CREATED`) moves every unit it carries from `MANUFACTURED` to `SHIPPED` and recomputes the parent order's `fulfillment_status`. Delivering a shipment (`DISPATCHED` → `DELIVERED`; guarded by `ERR_SHIPMENT_NOT_DISPATCHED`) moves every unit from `SHIPPED` to `DELIVERED`, stamps each unit's `delivered_at` from the logical clock, and recomputes fulfillment again.

The fulfillment recompute compares two exact counts against the order's `quantity`: the shipped count (units in `SHIPPED` or `DELIVERED`) and the delivered count (units in `DELIVERED`). If the delivered count equals `quantity`, fulfillment is `DELIVERED`. Otherwise, if the shipped count equals `quantity`, fulfillment is `FULLY_SHIPPED`. Otherwise, if at least one unit has shipped, it is `PARTIALLY_SHIPPED`; if none have, `UNFULFILLED`. The shipped-equals-quantity boundary is an exact equality, so a single shipment carrying every unit walks the order from `UNFULFILLED` straight to `FULLY_SHIPPED` at dispatch and to `DELIVERED` at delivery, while a partial first shipment leaves the order in `PARTIALLY_SHIPPED` until the remainder ships. Ties cannot occur because both counts are exact.

Individual units can be browsed across the plant with filters on `order_id`, `model_id`, `retailer_id`, `foam_batch_id`, `law_label_id`, and `status`, or fetched one at a time.

### 3.9. Returns, Warranty Claims, and Recycling Take-Back

**Returns.** A `Retailer` opens a return request for one of its own delivered units, supplying `unit_id`, `retailer_id`, and a `reason` of `COMFORT_EXCHANGE` or `DEFECT`. The unit must be `DELIVERED` (`ERR_UNIT_NOT_DELIVERED`, 409); the passed `retailer_id` must equal the unit's retailer (`ERR_RETAILER_UNIT_MISMATCH`, 422); and a `Retailer` caller may only reference its own id (`ERR_RETAILER_IDENTITY_MISMATCH`, 422). A comfort-exchange return is also bound to the 100-night comfort window: a `COMFORT_EXCHANGE` request made when the logical clock has passed the unit's `delivered_at` plus 100 days is rejected with `ERR_OUTSIDE_COMFORT_WINDOW` (409). The request is born `REQUESTED`. Return lists filter by `unit_id`, `retailer_id`, `replacement_unit_id`, and `status`.

Receiving the physical unit is a `QcInspector` action moving `REQUESTED` → `RECEIVED` (`ERR_RETURN_NOT_REQUESTED` guards the source state), and it moves the unit itself from `DELIVERED` to `RETURNED`. Inspection (`RECEIVED` → `INSPECTED`, guarded by `ERR_RETURN_NOT_RECEIVED`) records the inspector's `measured_sag_inches` from the inspection payload onto the return.

Resolution is a `PlantManager` decision on an `INSPECTED` return (`ERR_RETURN_NOT_INSPECTED`), expressed through the `resolution` field, and each branch has its own contract. `EXCHANGE` is valid only when the return's `reason` is `COMFORT_EXCHANGE` — an exchange resolution on a `DEFECT` return is rejected with `ERR_RESOLUTION_REASON_MISMATCH` (409). It manufactures a replacement unit against the same order, model, and batch, born `MANUFACTURED` and recorded as the return's `replacement_unit_id`, while the original unit moves `RETURNED` → `RECOVERED` — core recovery keeps it in the plant — and the return closes as `RESOLVED_EXCHANGE`. `RECYCLE` requires the unit's retailer to have `recycling_enrolled` true (`ERR_RECYCLING_NOT_ENROLLED`); the original unit moves `RETURNED` → `SCRAPPED`, which in turn creates a `RecyclingIntake` for the unit's retailer with `unit_id` set to the unit and `declared_weight_kg` equal to the sum of the model BOM's `quantity_per_unit` over the `FOAM_CORE`, `MEMORY_LAYER`, `TICKING`, and `FOUNDATION` lines, and the provisional credit that intake posts lands on the ledger with source `EXCHANGE_RECOVERY`. The return closes as `RESOLVED_RECYCLED`. `REJECT` ships the unit back to the retailer — the unit moves `RETURNED` → `DELIVERED` — and the return closes as `REJECTED`. For any non-exchange resolution, `replacement_unit_id` stays null.

**Warranty claims.** A `Retailer` files a claim against a delivered unit with `unit_id`, `retailer_id`, a `claim_type` of `SAG_DEFECT` or `WORKMANSHIP`, and a `measured_sag_inches` reading. The same ownership gates apply as for returns — the unit must be `DELIVERED` (`ERR_UNIT_NOT_DELIVERED`) and the retailer must match (`ERR_RETAILER_UNIT_MISMATCH`, `ERR_RETAILER_IDENTITY_MISMATCH`). A `SAG_DEFECT` claim additionally requires `measured_sag_inches` of at least 1.5 inches, boundary inclusive; a shallower sag is rejected with `ERR_SAG_BELOW_THRESHOLD` (422). The claim is born `FILED`, and claim lists filter by `unit_id`, `retailer_id`, and `status`.

Adjudication belongs to the `PlantManager`. Approving a claim (`FILED` → `APPROVED`; guarded by `ERR_CLAIM_NOT_FILED`) computes the credit at approval time, not filing time. First, `age_months` is the number of whole 30-day months between the unit's `delivered_at` and the logical clock at approval. That age selects the `credit_variant`: `FULL_REPLACEMENT` when `age_months` is at most 12, `PRORATED` when it exceeds 12. A full replacement pays the unit's entire `purchase_price_cents` regardless of sag depth. The prorated variant computes two guard rails around a linear amount: the linear amount is the purchase price multiplied by (120 − `age_months`) and divided by 120, rounded half up to integer cents, and it may go negative once the unit is past the 120-month term; the floor amount is the purchase price multiplied by one tenth, rounded half up to integer cents. The prorated credit is the larger of the floor amount and the smaller of the purchase price and the linear amount — the price cap binds first, the floor binds last, so a claim past the term still pays the ten-percent floor while a mid-life claim strictly underpays a full replacement. The result is stored as `credit_cents`. Denial moves `FILED` → `DENIED` under the same `ERR_CLAIM_NOT_FILED` guard.

Paying an approved claim (`APPROVED` → `PAID`; guarded by `ERR_CLAIM_NOT_APPROVED`) runs the fiscal cap: if the retailer's `credit_balance_cents` plus the claim's `credit_cents` would exceed `credit_limit_cents`, the payout is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (402). Otherwise the payout posts a `CreditAdjustment` for `+credit_cents` with source `WARRANTY_PAYOUT` and `source_id` set to the claim, recomputes the retailer's balance, and increments the retailer's `version`.

**Recycling take-back.** A `LogisticsCoordinator` records an intake with `retailer_id`, a `declared_weight_kg` manifest weight strictly greater than zero, and optionally a `unit_id` linking a scrapped unit being recovered for its core. The retailer must be enrolled in the program (`ERR_RECYCLING_NOT_ENROLLED`, 409), and when `unit_id` is given it must reference a `SCRAPPED` unit owned by that same retailer — anything else is `ERR_UNIT_NOT_SCRAPPED` (422). The provisional credit is computed immediately: `declared_weight_kg` multiplied by a flat 20 cents per kilogram, rounded half up to integer cents, stored as `provisional_credit_cents`, and posted to the retailer's ledger as a `CreditAdjustment` with source `RECYCLING_PROVISIONAL` and `source_id` set to the intake. That posting must respect the credit limit — a provisional credit that would push the balance above the cap is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (402) — and any successful posting recomputes the balance and increments the retailer's `version`. The intake is born `RECEIVED`; intake lists filter by `retailer_id`, `unit_id`, and `status`.

Finalization is a `PlantManager` action (`RECEIVED` → `FINALIZED`, guarded by `ERR_INTAKE_NOT_RECEIVED`) taken after the material is sorted and weighed. It accepts the four actual masses — `actual_steel_kg`, `actual_foam_kg`, `actual_fiber_kg`, and `actual_wood_kg` — and computes `final_credit_cents` as the sum of four per-material lines, each rounded half up to integer cents before summing: steel at 25 cents per kilogram, foam at 40, fiber at 15, and wood at 5. Because the final weighed credit almost always diverges from the flat provisional, the difference posts to the ledger as a signed `CreditAdjustment` equal to the final credit minus the provisional credit, with source `RECYCLING_FINAL_DELTA` — the delta may be negative. The retailer's balance is recomputed and its `version` incremented, and `final_credit_cents` (null until this point) is stored.

## 4. Endpoint Definitions

Endpoints that create a new resource answer 201 Created; all other successful operations — single-resource reads, list queries, state transitions, and actions — answer 200 OK. All response bodies follow the envelope defined in §2.2. The table below is a navigation summary only; request payloads, computed fields, preconditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/plant/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z; never wall-clock) | PlantManager |
| POST | `/plant/retailers` | Register a retailer account | PlantManager |
| GET | `/plant/retailers` | List retailers | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/retailers/{retailerId}` | Get a retailer | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/retailers/{id}/credit-adjustments` | Post a manual credit adjustment (OCC on retailer version) | PlantManager |
| GET | `/plant/retailers/{id}/credit-adjustments` | List a retailer's credit ledger entries | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/models` | Create a mattress model (status DRAFT) | PlantManager |
| GET | `/plant/models` | List models | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/models/{modelId}` | Get a model | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/models/{id}/submit-for-certification` | DRAFT → CERT_REVIEW (requires at least one BomLine) | PlantManager |
| POST | `/plant/models/{id}/return-to-draft` | CERT_REVIEW → DRAFT (revert loop for spec fixes) | PlantManager |
| POST | `/plant/models/{id}/certify` | CERT_REVIEW → CERTIFIED (requires APPROVED unexpired FLAMMABILITY_16CFR1633 cert) | ComplianceOfficer |
| POST | `/plant/models/{id}/activate` | CERTIFIED → ACTIVE | PlantManager |
| POST | `/plant/models/{id}/discontinue` | ACTIVE → DISCONTINUED (blocked by open orders) | PlantManager |
| POST | `/plant/models/{id}/bom-lines` | Add a BOM component line (model must be DRAFT) | PlantManager |
| GET | `/plant/models/{id}/bom-lines` | List BOM lines of a model | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| PATCH | `/plant/models/{id}/bom-lines/{lineId}` | Edit a BOM line (model must be DRAFT; OCC on model version) | PlantManager |
| POST | `/plant/models/{id}/certificates` | Submit a compliance certificate (model must be CERT_REVIEW) | ComplianceOfficer |
| GET | `/plant/models/{id}/certificates` | List certificates of a model | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/models/{id}/certificates/{certId}/approve` | Approve a submitted certificate (approver != submitter) | ComplianceOfficer |
| POST | `/plant/models/{id}/certificates/{certId}/revoke` | Revoke an approved certificate; triggers model → labels → orders cascade | ComplianceOfficer |
| POST | `/plant/law-label-specs` | Create a state law-label spec (DRAFT) | ComplianceOfficer |
| GET | `/plant/law-label-specs` | List specs | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/law-label-specs/{specId}` | Get a spec | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/law-label-specs/{id}/law-labels` | List law labels pinned to this spec | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/law-label-specs/{id}/publish` | Publish a spec; supersedes any other PUBLISHED spec for the same state | ComplianceOfficer |
| POST | `/plant/models/{id}/law-labels` | Generate a law label for a state, pinned to the currently PUBLISHED spec (model must be CERTIFIED or ACTIVE; OCC on model version) | ComplianceOfficer |
| GET | `/plant/models/{id}/law-labels` | List law labels of a model | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/law-labels` | Filtered list of law labels across models | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/law-labels/{labelId}` | Get a law label | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/models/{id}/law-labels/{labelId}/approve` | Approve a generated label (approver != creator) | ComplianceOfficer |
| POST | `/plant/models/{id}/law-labels/{labelId}/reject` | Reject a generated label (rejector != creator) | ComplianceOfficer |
| POST | `/plant/models/{id}/law-labels/{labelId}/activate` | Activate an approved label; supersedes the current ACTIVE label for the same model+state | ComplianceOfficer |
| POST | `/plant/foam-batches` | Pour a foam lot (POURED) | LineSupervisor |
| GET | `/plant/foam-batches` | List foam batches | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/foam-batches/{batchId}` | Get a foam batch | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/foam-batches/{batchId}/start-cure` | POURED → CURING; computes cure_eligible_at; enforces chamber capacity | LineSupervisor |
| POST | `/plant/foam-batches/{batchId}/certify-cured` | CURING → CURED at/after cure_eligible_at (certifier != pourer) | QcInspector |
| POST | `/plant/foam-batches/{batchId}/quarantine` | CURING → QUARANTINED | QcInspector |
| POST | `/plant/foam-batches/{batchId}/release-to-cure` | QUARANTINED → CURING re-cure loop; extends cure_eligible_at by +12h | LineSupervisor |
| POST | `/plant/foam-batches/{batchId}/scrap` | QUARANTINED → SCRAPPED; writes off available mass | QcInspector |
| POST | `/plant/quilt-runs` | Schedule a quilting/panel run on a machine (half-open overlap check) | LineSupervisor |
| GET | `/plant/quilt-runs` | List quilt runs | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/quilt-runs/{runId}` | Get a quilt run | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/quilt-runs/{runId}/start` | SCHEDULED → RUNNING (clock must be >= start_at) | LineSupervisor |
| POST | `/plant/quilt-runs/{runId}/complete` | RUNNING → COMPLETE | LineSupervisor |
| POST | `/plant/quilt-runs/{runId}/cancel` | SCHEDULED → CANCELLED | LineSupervisor |
| POST | `/plant/production-orders` | Create a production order; computes subtotal/fee/total | PlantManager, Retailer |
| GET | `/plant/production-orders` | List production orders | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/production-orders/{orderId}` | Get a production order | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/production-orders/{orderId}/allocate-materials` | PLANNED → MATERIAL_ALLOCATED; reserves foam mass from a CURED batch | LineSupervisor |
| POST | `/plant/production-orders/{orderId}/start-production` | MATERIAL_ALLOCATED → IN_PRODUCTION; consumes reserved foam; requires ACTIVE law label | LineSupervisor |
| POST | `/plant/production-orders/{orderId}/complete-production` | IN_PRODUCTION → QC_PENDING; manufactures quantity MattressUnits | LineSupervisor |
| POST | `/plant/production-orders/{orderId}/qc-pass` | QC_PENDING → COMPLETE | QcInspector |
| POST | `/plant/production-orders/{orderId}/qc-hold` | QC_PENDING → QC_HOLD | QcInspector |
| POST | `/plant/production-orders/{orderId}/qc-release` | QC_HOLD → QC_PENDING | QcInspector |
| POST | `/plant/production-orders/{orderId}/cancel` | PLANNED or MATERIAL_ALLOCATED → CANCELLED; releases reserved foam | PlantManager |
| GET | `/plant/units` | List mattress units | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/units/{unitId}` | Get a mattress unit | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/shipments` | Create a shipment for an order (drop-ship or warehouse); validates label + cert compliance | LogisticsCoordinator |
| GET | `/plant/shipments` | List shipments | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/shipments/{shipmentId}` | Get a shipment | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/shipments/{shipmentId}/dispatch` | CREATED → DISPATCHED; units → SHIPPED; fulfillment recomputed | LogisticsCoordinator |
| POST | `/plant/shipments/{shipmentId}/deliver` | DISPATCHED → DELIVERED; units → DELIVERED with delivered_at = clock | LogisticsCoordinator |
| POST | `/plant/returns` | Open a comfort-exchange or defect return for a delivered unit | Retailer |
| GET | `/plant/returns` | List return requests | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/returns/{returnId}` | Get a return request | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/returns/{returnId}/receive` | REQUESTED → RECEIVED; unit → RETURNED | QcInspector |
| POST | `/plant/returns/{returnId}/inspect` | RECEIVED → INSPECTED; records measured sag | QcInspector |
| POST | `/plant/returns/{returnId}/resolve` | INSPECTED → RESOLVED_EXCHANGE / RESOLVED_RECYCLED / REJECTED | PlantManager |
| POST | `/plant/warranty-claims` | File a warranty claim (SAG_DEFECT requires sag of at least 1.5 inches, inclusive) | Retailer |
| GET | `/plant/warranty-claims` | List warranty claims | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/warranty-claims/{claimId}` | Get a warranty claim | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/warranty-claims/{claimId}/approve` | FILED → APPROVED; computes age/variant/credit at approval time | PlantManager |
| POST | `/plant/warranty-claims/{claimId}/deny` | FILED → DENIED | PlantManager |
| POST | `/plant/warranty-claims/{claimId}/pay` | APPROVED → PAID; posts retailer credit (capped by credit limit) | PlantManager |
| POST | `/plant/recycling-intakes` | Record a take-back intake; posts provisional credit immediately | LogisticsCoordinator |
| GET | `/plant/recycling-intakes` | List recycling intakes | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| GET | `/plant/recycling-intakes/{intakeId}` | Get a recycling intake | PlantManager, ComplianceOfficer, LineSupervisor, QcInspector, Retailer, LogisticsCoordinator |
| POST | `/plant/recycling-intakes/{intakeId}/finalize` | RECEIVED → FINALIZED; computes per-material final credit and posts the signed delta | PlantManager |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RETAILER_NOT_FOUND` | 404 |
| `ERR_MODEL_NOT_FOUND` | 404 |
| `ERR_BOM_LINE_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_LABEL_NOT_FOUND` | 404 |
| `ERR_SPEC_NOT_FOUND` | 404 |
| `ERR_FOAM_BATCH_NOT_FOUND` | 404 |
| `ERR_QUILT_RUN_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_INTAKE_NOT_FOUND` | 404 |
| `ERR_VALIDATION_FAILED` | 400 |
| `ERR_INVALID_TIME_RANGE` | 400 |
| `ERR_MODEL_NOT_DRAFT` | 409 |
| `ERR_MODEL_NOT_CERT_REVIEW` | 409 |
| `ERR_MODEL_NOT_CERTIFIED` | 409 |
| `ERR_MODEL_NOT_ACTIVE` | 409 |
| `ERR_CERT_NOT_SUBMITTED` | 409 |
| `ERR_CERT_NOT_APPROVED` | 409 |
| `ERR_SPEC_NOT_DRAFT` | 409 |
| `ERR_LABEL_NOT_GENERATED` | 409 |
| `ERR_LABEL_NOT_APPROVED` | 409 |
| `ERR_BATCH_NOT_POURED` | 409 |
| `ERR_BATCH_NOT_CURING` | 409 |
| `ERR_BATCH_NOT_QUARANTINED` | 409 |
| `ERR_BATCH_NOT_CURED` | 409 |
| `ERR_RUN_NOT_SCHEDULED` | 409 |
| `ERR_RUN_NOT_RUNNING` | 409 |
| `ERR_ORDER_NOT_PLANNED` | 409 |
| `ERR_ORDER_NOT_MATERIAL_ALLOCATED` | 409 |
| `ERR_ORDER_NOT_IN_PRODUCTION` | 409 |
| `ERR_ORDER_NOT_QC_PENDING` | 409 |
| `ERR_ORDER_NOT_QC_HOLD` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_ORDER_NOT_COMPLETE` | 409 |
| `ERR_UNIT_NOT_DELIVERED` | 409 |
| `ERR_UNITS_NOT_MANUFACTURED` | 409 |
| `ERR_SHIPMENT_NOT_CREATED` | 409 |
| `ERR_SHIPMENT_NOT_DISPATCHED` | 409 |
| `ERR_RETURN_NOT_REQUESTED` | 409 |
| `ERR_RETURN_NOT_RECEIVED` | 409 |
| `ERR_RETURN_NOT_INSPECTED` | 409 |
| `ERR_CLAIM_NOT_FILED` | 409 |
| `ERR_CLAIM_NOT_APPROVED` | 409 |
| `ERR_INTAKE_NOT_RECEIVED` | 409 |
| `ERR_CERT_REQUIRED` | 409 |
| `ERR_CERT_EXPIRED` | 409 |
| `ERR_LABEL_NOT_ACTIVE` | 409 |
| `ERR_SPEC_NOT_PUBLISHED` | 409 |
| `ERR_SPEC_SUPERSEDED` | 409 |
| `ERR_CURE_INCOMPLETE` | 409 |
| `ERR_MACHINE_TIME_CONFLICT` | 409 |
| `ERR_CHAMBER_CAPACITY_EXCEEDED` | 409 |
| `ERR_DROPSHIP_NOT_ENABLED` | 409 |
| `ERR_RECYCLING_NOT_ENROLLED` | 409 |
| `ERR_MODEL_HAS_NO_BOM` | 409 |
| `ERR_OPEN_ORDERS_EXIST` | 409 |
| `ERR_RESOLUTION_REASON_MISMATCH` | 409 |
| `ERR_OUTSIDE_COMFORT_WINDOW` | 409 |
| `ERR_RUN_WINDOW_NOT_REACHED` | 409 |
| `ERR_UNIT_ORDER_MISMATCH` | 422 |
| `ERR_RETAILER_UNIT_MISMATCH` | 422 |
| `ERR_RETAILER_IDENTITY_MISMATCH` | 422 |
| `ERR_UNIT_NOT_SCRAPPED` | 422 |
| `ERR_SAG_BELOW_THRESHOLD` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_INSUFFICIENT_FOAM_MASS` | 402 |
| `ERR_STALE_VERSION` | 412 |

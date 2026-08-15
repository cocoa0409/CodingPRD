# Non-GMO Claim Verification API — Product Requirements Document

## 1. Introduction

Retailers and consumers increasingly rely on third-party claim seals — Non-GMO Project style verification being the most recognized — to trust what a product label asserts. Running such a program is an evidence-management problem: a verifier must configure claim standards with numeric thresholds, collect supply-chain segregation affidavits from brand participants, design PCR testing plans sized to product risk, audit facilities with a lot-level traceability exercise, and only then grant a time-boxed label license. The obligation does not end at issuance: licenses renew annually, formulation changes force re-evaluation, and market-place claim misuse must be investigated and sanctioned.

This document specifies the API for operating that verification program end to end. It covers claim-standard configuration, brand registration, product enrollment and its evaluation pipeline, the minor-ingredient exemption rules that decide which ingredients need laboratory testing versus paperwork, sampling plans and segregated laboratory result confirmation, facility audits, label-license issuance and lifecycle cascades, annual renewal, and claim-misuse enforcement with a penalty-point model that feeds back into a brand's standing. Because eligibility, freshness, and expiry rules are all time-driven, the server runs on a controllable logical clock rather than wall-clock time; all temporal rules below are evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` identifying the acting user and `X-User-Role` naming their capacity. The program recognizes exactly five roles: `VerifierAdmin`, `BrandRep`, `LabAnalyst`, `Auditor`, and `EnforcementOfficer`. A request with a missing header, or whose role is not one of these five, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`. A request whose role is recognized but not permitted for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `BrandRep`, `X-User-ID` is the `id` of the acting `Brand`; ownership checks on any resource that references a brand compare the resource's brand foreign key to `X-User-ID`. This ownership rule guards every brand-representative write operation — enrolling a product, submitting it, resubmitting it, renewing it, adding an ingredient, and submitting an affidavit — and a mismatch is rejected with `ERR_NOT_BRAND_RESOURCE`. For ingredient and affidavit writes, the checked brand is the brand of the product that owns the ingredient.

When `X-User-Role` is `VerifierAdmin`, `LabAnalyst`, `Auditor`, or `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` on a `SupplierAffidavit`, as `recorded_by_user_id` or `confirmed_by_user_id` on a `TestSample`, as `auditor_id` on a `FacilityAudit`, or as `opened_by_user_id` and `resolved_by_user_id` on an `EnforcementCase` — and individual workflows may compare it against such recorded values, but it is never compared to any entity's `id`.

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

Two transport-level rejections follow the same envelope: a request to a path the API does not define, or with a method the path does not support, is rejected with `ERR_NOT_FOUND` (404); a request body that is not a valid JSON object where one is expected is rejected with `ERR_VALIDATION` (400).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1 and above 100 as 100, and a negative `offset` as 0; a non-numeric `limit` or `offset` falls back to its default.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources sharing a creation timestamp are ordered by creation (insertion) order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this API — claim standards, brands, products, ingredients, affidavits, sampling plans, test samples, facility audits, label licenses, and enforcement cases — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was last modified; it refreshes on every change to the resource's properties, including recomputation of derived fields.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

Recomputing a derived field — for instance a brand's penalty counters or a product's exposure percentages — is a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version`, exactly as a direct edit would.

### 2.5. Numeric Precision and Rounding

Percentages and scores in this program are compared against hard thresholds, so rounding discipline is part of the contract. All computed percentages stored on resources — the product exposure estimates and the audit traceability score — are rounded to exactly 2 decimal places using round-half-up. Where a calculation chains several steps, the rounding points are pinned per rule: the traceability score rounds each lot individually before averaging, while the exposure estimate rounds exactly once after the full weighted sum has been computed exactly. Input-provided numbers (thresholds, weight percentages, PCR results) are stored at the precision supplied.

### 2.6. The Logical Clock and Time-Driven Sweeps

All temporal evaluation in the system — affidavit expiry, license expiry, renewal-window entry, and the rolling penalty window — is keyed to a server-side logical clock, never to wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it advances only when an operator sets it. A `VerifierAdmin` may advance the clock by supplying a `to_iso8601` instant; the capability responds with the resulting `current_utc`. The set accepts any parseable instant — including one earlier than the current logical time; no monotonicity check is applied. Every such set runs the following sweeps, in this order of business effect:

- Each `ACCEPTED` affidavit whose `valid_until` is at or before the new current time transitions to `EXPIRED`, and the owning ingredient's compliance standing is recomputed — an ingredient that loses its last current affidavit may drop from `COMPLIANT` to `PENDING`.
- Each `ACTIVE` label license whose `valid_until` is at or before the new current time transitions to `EXPIRED`, and its product — if `VERIFIED` or `RENEWAL_DUE` — transitions to `LAPSED`. Licenses in `SUSPENDED` status never expire.
- Each `VERIFIED` product whose `ACTIVE` license has entered its renewal window transitions to `RENEWAL_DUE`.
- Every brand's `rolling_penalty_points` is re-evaluated against the new current time, since the trailing window may have shed aging substantiations.

### 2.7. Optimistic Concurrency on Sampling-Plan Creation

Exactly one write operation in this API participates in optimistic concurrency control: the creation of a sampling plan. The request must carry `expected_product_version`, a non-optional field holding the `version` of the target product as the client last observed it. If another writer has advanced the product's `version` since that read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The check exists because creating a plan legitimately cancels the product's current non-`CANCELLED` plans; a writer holding a stale product version would otherwise silently cancel a plan it never saw. Endpoints other than sampling-plan creation do not take a version field.

### 2.8. Segregation of Duties Across the Verification Chain

Three workflows deliberately split authority between two distinct operators. First, laboratory results are confirmed by a different analyst than the one who recorded them: the confirming `X-User-ID` must differ from the sample's `recorded_by_user_id`. Second, an enforcement case is resolved by a different officer than the one who opened it: the resolving `X-User-ID` must differ from the case's `opened_by_user_id`. Violating either rule is rejected with `ERR_SEGREGATION_OF_DUTIES`. Third, a facility audit's traceability report may be submitted only by the auditor named in the audit's `auditor_id`; any other caller is rejected with `ERR_NOT_ASSIGNED_AUDITOR`. All three are HTTP 403 rejections.

### 2.9. Validation Order and Error Precedence

When several checks could reject the same request, the server applies them in a fixed priority order so that the surfaced error is deterministic. First, the authentication-context check runs: the headers must be present and the role recognized, else `ERR_MISSING_OR_INVALID_USER_CONTEXT`. Immediately after the authentication context — ahead of role authorization — request-shape errors are evaluated: missing required fields, unknown or computed fields in the body, invalid enum members, numeric range violations, and missing or improperly present conditional fields all fail here with `ERR_VALIDATION`. Next comes role authorization (`ERR_FORBIDDEN_ROLE`), then existence: path identifiers are validated left to right and body-supplied foreign keys — `brand_id`, `standard_id`, `product_id`, `ingredient_id`, `sampling_plan_id` — must resolve to existing resources, else `ERR_NOT_FOUND`. Brand-representative ownership follows (`ERR_NOT_BRAND_RESOURCE`), then the optimistic-concurrency check on plan creation (`ERR_STALE_VERSION`), then state-machine from-state preconditions (`ERR_PRODUCT_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_SAMPLE_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_CASE_NOT_OPEN`, `ERR_AFFIDAVIT_NOT_REVIEWABLE`). Business referential integrity comes next (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_NO_INGREDIENTS`), then the business safety gates in their declared sub-order — claim-integrity gates first, then segregation-of-duties and assigned-auditor checks, then the traceability-score floor — then temporal gates (`ERR_RENEWAL_WINDOW_CLOSED`, `ERR_AUDIT_STALE`), and finally constraint checks: affidavit window overlap, audit capacity, `gtin` uniqueness, ingredient weight-sum overflow, and ingredient testability.

### 2.10. Derived State Reconciliation and Cascade Integrity

The program maintains a web of derived state: an ingredient's `compliance_status`, a product's two exposure estimates, a plan's `confirmed_sample_count`, an audit's `traceability_score_pct`, a brand's penalty counters, `standing_status`, and `verified_product_count`. All of it is reconciled immediately — every side effect described in §3 applies atomically within the request that triggered it; the API never defers a recomputation to a later read or background job. When one operation mutates several aggregates — for example a substantiated enforcement case touching case, license, product, and brand — all of those changes land together, and each mutated resource independently refreshes `updated_at` and increments `version`. A brand's `verified_product_count` is always the count of its products whose `enrollment_status` is `VERIFIED` or `RENEWAL_DUE`; any transition into or out of those states recomputes it.

## 3. Business Logic & Workflows

### 3.1. Program Configuration: Claim Standards and Brand Registration

Before any product can be evaluated, a `VerifierAdmin` configures the claim standards the program verifies against. Creating a standard takes a `claim_code` — a program-level code such as `NGMO` that must be unique across all claim standards, with a duplicate rejected as `ERR_VALIDATION` by a check applied after role authorization — plus a human-readable `name` and two numeric thresholds. The `ingredient_threshold_pct` is the maximum GMO content permitted per ingredient, expressed as a percent; it must be greater than zero, and a confirmed PCR result at or below this threshold counts as compliant. The `exemption_max_weight_pct` is the minor-ingredient exemption ceiling, supplied as a percent of zero or greater: an ingredient whose share of product weight is at or below this value is exempt from PCR testing, and the boundary is inclusive. Three optional knobs carry defaults when omitted: `audit_validity_months` defaults to 12 and controls how many calendar months a passed facility audit stays fresh after its decision; `renewal_window_days` defaults to 60 and controls how far before license expiry the renewal window opens; `license_term_days` defaults to 365 and is the number of days of validity granted at issuance and at each renewal. When supplied, each knob must be a non-negative integer, else `ERR_VALIDATION`. The standards list can be filtered by `claim_code`.

Brands join the program through a `VerifierAdmin` as well, registered with a `name` and a `contact_email`. A freshly registered brand starts with `lifetime_penalty_points` and `rolling_penalty_points` at zero, `standing_status` of `GOOD_STANDING`, and `verified_product_count` of zero; all four are computed fields maintained by the enforcement and product lifecycles rather than by direct writes.

### 3.2. Product Enrollment and the Evaluation Pipeline

A `BrandRep` enrolls a product with a payload containing the `brand_id` of their own brand, the `standard_id` of the claim standard being pursued, the product `name`, its `gtin`, and the `annual_volume_units` production volume. The `brand_id` must equal the caller's identity, and the brand must be in `GOOD_STANDING` — a brand on probation cannot enroll new products and is turned away with `ERR_BRAND_ON_PROBATION`. The `gtin` must be unique among all products enrolled under the same `standard_id`; a collision is rejected with `ERR_PRODUCT_GTIN_EXISTS`. An `annual_volume_units` that is not an integer, or is negative, is rejected with `ERR_VALIDATION`. A new product begins with `enrollment_status` of `DRAFT` and both exposure estimates at zero. The product list supports filters on `brand_id`, `standard_id`, and `enrollment_status`.

Submitting a product moves it from `DRAFT` to `SUBMITTED` and is the first integrity gate. The product must have at least one ingredient, else `ERR_NO_INGREDIENTS`, and every ingredient that requires an affidavit must be covered by at least one `ACCEPTED` affidavit whose window currently covers the submission time, else `ERR_AFFIDAVIT_MISSING`. Submission also recomputes the product's `provisional_exposure_pct` and `confirmed_exposure_pct`. Once `SUBMITTED`, the product is frozen for administrative triage — ingredient additions are refused — until a `VerifierAdmin` picks it up, moving it from `SUBMITTED` to `UNDER_EVALUATION`.

Evaluation ends in a decision by a `VerifierAdmin`, who supplies a `decision` of `VERIFIED` or `REJECTED`. The `VERIFIED` path is gated by the full claim-integrity chain described in §3.7. A `REJECTED` decision requires a non-empty `rejection_reason`, which is stored on the product; omitting it is a shape error. A `rejection_reason` supplied alongside a `VERIFIED` decision is tolerated — it must still be a string if present and non-null — and is ignored. If the product's license happens to be suspended for a scope change at the time, rejection leaves that license suspended. Rejection is not terminal: the brand's representative may resubmit, moving the product from `REJECTED` back to `SUBMITTED`. Resubmission clears `rejection_reason` to null and re-checks affidavit currency under exactly the same rule as the original submission, so a lapsed affidavit surfaces as `ERR_AFFIDAVIT_MISSING` once again. Any product transition attempted from a state that does not support it is rejected with `ERR_PRODUCT_INVALID_STATE`.

### 3.3. Ingredient Composition and the Minor-Ingredient Exemption

Ingredients are the evidentiary unit of the program. A `BrandRep` adds an ingredient to one of their brand's products with a payload containing the `product_id`, the ingredient `name`, its `crop_type` — one of `HIGH_RISK`, `LOW_RISK`, or `NON_CROP` — and its `declared_weight_pct`, the ingredient's share of product weight in percent. The share must be greater than 0 and at most 100, and the running total across the product's ingredients — summed in exact decimal arithmetic — must never exceed 100; an addition that would push the sum over the top is rejected with `ERR_WEIGHT_SUM_EXCEEDED`, while an out-of-range share is `ERR_VALIDATION`. Ingredients may be added while the product is `DRAFT`, `REJECTED`, `UNDER_EVALUATION`, `VERIFIED`, or `RENEWAL_DUE`; a `SUBMITTED` product is frozen, and `REVOKED` or `LAPSED` products are terminal, all rejected with `ERR_PRODUCT_INVALID_STATE`. Adding an ingredient to a `VERIFIED` or `RENEWAL_DUE` product is a scope change with license consequences covered in §3.7.

From these inputs the server derives the ingredient's obligations. An ingredient is exempt — `is_exempt` is true — exactly when its `declared_weight_pct` is at or below the standard's `exemption_max_weight_pct`; the boundary is inclusive, so an ingredient declared at precisely the ceiling is exempt. Testing obligation follows: `requires_pcr` is true only for a `HIGH_RISK` crop that is not exempt. Paperwork obligation is broader: `requires_affidavit` is true for every `HIGH_RISK` ingredient, exempt or not, and for a `LOW_RISK` ingredient that is not exempt; a `NON_CROP` ingredient never requires an affidavit.

The ingredient's `compliance_status` summarizes where it stands, evaluated in this order. If any `CONFIRMED` sample of the ingredient has an outcome of `NON_COMPLIANT`, the ingredient is `NON_COMPLIANT`. Otherwise, if the ingredient requires neither PCR nor an affidavit, it is `EXEMPTED`. Otherwise, if every requirement is satisfied — at least one `CONFIRMED` sample with a `COMPLIANT` outcome when PCR is required, and at least one `ACCEPTED` affidavit whose window covers the current time when an affidavit is required — the ingredient is `COMPLIANT`. Anything else is `PENDING`. Note the asymmetry this creates: a `HIGH_RISK` ingredient declared under the exemption ceiling skips the laboratory but still owes supply-chain paperwork. The ingredient list can be filtered by `product_id`.

### 3.4. Supply-Chain Affidavits

An affidavit is a supplier's sworn statement that segregation controls keep the ingredient's supply chain clean. A `BrandRep` submits one with a payload containing the `ingredient_id`, the supplier's legal `supplier_name`, and a coverage window from `valid_from` to `valid_until`. Windows are half-open: coverage includes the `valid_from` instant and runs up to but excludes `valid_until`, and `valid_until` must be strictly later than `valid_from`. For a given ingredient and supplier pair, the new window must not overlap any sibling affidavit that is still `SUBMITTED` or `ACCEPTED`; overlap is rejected with `ERR_AFFIDAVIT_WINDOW_OVERLAP`. Because the windows are half-open, strict adjacency is allowed — a new affidavit whose `valid_from` equals the sibling's `valid_until` tiles cleanly. A submitted affidavit starts in `SUBMITTED` status and records the submitting representative in `submitted_by_user_id`. The affidavit list can be filtered by `ingredient_id` and `status`.

Review belongs to the `VerifierAdmin`, who supplies a `decision` of `ACCEPTED` or `REJECTED`. Only a `SUBMITTED` affidavit is reviewable; accepted, rejected, and expired affidavits are settled, and re-reviewing one is rejected with `ERR_AFFIDAVIT_NOT_REVIEWABLE`. Accepting an affidavit recomputes the owning ingredient's `compliance_status`, since a pending paperwork requirement may now be satisfied. Thereafter the affidavit ages on the logical clock: when its `valid_until` arrives, the sweep moves it from `ACCEPTED` to `EXPIRED` and recomputes the ingredient's standing again — this is the path by which a `COMPLIANT` ingredient can silently fall back to `PENDING` until a fresh affidavit lands.

### 3.5. PCR Sampling Plans and Laboratory Results

Testing is organized through sampling plans created by a `VerifierAdmin`. Plan creation names the `product_id` and a `risk_point` of `INGREDIENT_INTAKE`, `IN_PROCESS`, or `FINISHED_PRODUCT`, and requires the product to be `UNDER_EVALUATION`; products in any other state are rejected with `ERR_PRODUCT_INVALID_STATE`. The request is also the program's one OCC-guarded write and must carry `expected_product_version` as described in §2.7. The plan's `required_sample_count` is computed at creation from the product's risk profile: start with a base of 0 for `INGREDIENT_INTAKE`, 1 for `IN_PROCESS`, or 2 for `FINISHED_PRODUCT`; add one for each of the product's ingredients with `requires_pcr` true; add a volume tier of 2 when `annual_volume_units` reaches 100,000, 1 when it reaches 10,000, and 0 below that; and add 2 when the brand's history shows at least one `SUBSTANTIATED` enforcement case or at least one `FAILED` facility audit, 0 otherwise. The total is capped at 10. A plan is created `ACTIVE`, or `COMPLETED` immediately when the required count computes to zero.

Creation also supersedes: every existing `ACTIVE` or `COMPLETED` plan of the same product transitions to `CANCELLED`, with `superseded_by_plan_id` set to the new plan's id, and the product's `version` advances by one. A plan's `confirmed_sample_count` tracks how many of its samples currently sit in `CONFIRMED`; when that count reaches the required number — at or above, the boundary is inclusive — the plan moves from `ACTIVE` to `COMPLETED`, and if invalidation later drops the count below the requirement, a completed plan reopens to `ACTIVE`. Plan listings filter by `product_id` and `status`.

A `LabAnalyst` collects a sample under a plan by naming the `sampling_plan_id` and the `ingredient_id`. The plan must be `ACTIVE` — collecting against a completed or cancelled plan fails with `ERR_PLAN_NOT_ACTIVE` — the ingredient must belong to the plan's product, else `ERR_CROSS_REFERENCE_MISMATCH`, and the ingredient must actually require PCR, else `ERR_INGREDIENT_NOT_TESTABLE`. A new sample is `COLLECTED` with `result_gmo_pct` still null.

Recording a result moves a `COLLECTED` sample to `RESULT_RECORDED`: the analyst supplies the `result_gmo_pct`, which must be zero or greater, and the server stamps `recorded_by_user_id`. Confirmation moves it from `RESULT_RECORDED` to `CONFIRMED` and is the highest-leverage action in the laboratory. The confirmer must be a different analyst than the recorder, enforced per §2.8, and the parent plan must not be `CANCELLED` — confirming a sample under a cancelled plan is rejected with `ERR_PLAN_NOT_ACTIVE` — note the asymmetry with collection: a plan that has already reached `COMPLETED` may still confirm its in-flight recorded samples, since only cancellation blocks confirmation. Confirmation computes the `outcome`: `COMPLIANT` when the result is at or below the standard's `ingredient_threshold_pct` — the boundary is inclusive — and `NON_COMPLIANT` otherwise, stamps `confirmed_by_user_id`, and then fans out. The owning ingredient's `compliance_status` is recomputed, and a `NON_COMPLIANT` outcome forces the ingredient to `NON_COMPLIANT` regardless of everything else. The product's two exposure estimates are recomputed in turn. The plan's `confirmed_sample_count` rises by one and, upon reaching the requirement, the plan completes.

Invalidation is the compensating action, available to both `LabAnalyst` and `VerifierAdmin`, from either `RESULT_RECORDED` or `CONFIRMED`; any other state is rejected with `ERR_SAMPLE_INVALID_STATE`. Invalidating a recorded-but-unconfirmed sample simply moves it to `INVALIDATED` with no count change. Invalidating a `CONFIRMED` sample resets its `outcome` to null, decrements the plan's `confirmed_sample_count` by one, reopens the plan from `COMPLETED` to `ACTIVE` if the count has fallen below the requirement, and recomputes both the ingredient's standing and the product's exposure — a forced `NON_COMPLIANT` may lift to `PENDING` or `COMPLIANT`. A confirm followed by an invalidate of the same sample therefore leaves the count exactly where it was before the confirm, and `INVALIDATED` samples never count toward anything.

The two exposure estimates on the product share one weighted-sum skeleton and differ in one assumption. For each ingredient, take the maximum `result_gmo_pct` among its `CONFIRMED` samples — invalidated results are excluded — and weight it by `declared_weight_pct`. Under the evidence-only `confirmed_exposure_pct`, an ingredient with no confirmed result contributes zero. Under the conservative `provisional_exposure_pct`, an untested ingredient that requires PCR is assumed to sit exactly at the standard's threshold, while one that requires no testing still contributes zero. The weighted contributions are summed exactly across all ingredients, then rounded half-up to 2 decimal places once, after the sum. Whenever a PCR-required ingredient lacks a confirmed sample, the same data yields a provisional figure strictly above the confirmed one. Both fields are recomputed on product submission, on sample confirmation, and on sample invalidation. Sample listings filter by `sampling_plan_id`, `ingredient_id`, and `status`.

### 3.6. Facility Audits and the Traceability Exercise

Verification also requires an on-site facility audit per brand. A `VerifierAdmin` schedules one by naming the `brand_id`, the `facility_name`, the `auditor_id` of the assigned field auditor, and the `scheduled_date`. Capacity is gated per facility: at most one audit may sit in `SCHEDULED` or `REPORT_SUBMITTED` status for a given `brand_id` and `facility_name` pair, and a second scheduling attempt is rejected with `ERR_AUDIT_CAPACITY_CONFLICT`.

The assigned auditor — and only that auditor, per §2.8 — submits the traceability exercise report, which requires the audit still be `SCHEDULED`; the wrong state draws `ERR_AUDIT_INVALID_STATE`. The report payload is `lots`, a non-empty array of exercise lots each described by a `lot_code`, an `input_qty` greater than zero, and a `recovered_qty` of zero or more. Submission computes the `traceability_score_pct`: for each lot, the recovered quantity is divided by the input quantity and multiplied by 100, and that per-lot percentage is rounded half-up to 2 decimal places first; the per-lot values are then averaged, and the average is itself rounded half-up to 2 decimal places. The order is pinned — summing quantities first and dividing once produces different cents and is not used. Submission moves the audit from `SCHEDULED` to `REPORT_SUBMITTED`.

A `VerifierAdmin` then decides the audit. The `PASSED` decision is score-gated: the `traceability_score_pct` must be at least 95.00, with the boundary inclusive, else `ERR_TRACE_SCORE_BELOW_MIN`. The `FAILED` decision is always allowed regardless of score. Either decision stamps `decided_at` with the current logical time and is terminal. Freshness then matters downstream: a passed audit stays fresh for the standard's `audit_validity_months` calendar months after its `decided_at`; adding calendar months clamps the day-of-month to the target month's last day when it would otherwise overflow. Where a rule needs the brand's audit status, it consults the most recent passed audit — latest `decided_at`, with ties broken by the earliest `created_at` and any remaining ties by creation order — and treats it as fresh only while that `decided_at` plus the validity months is still later than now; an audit at or past that instant is stale and triggers `ERR_AUDIT_STALE` at verification and renewal time. Audit listings filter by `brand_id` and `status`.

### 3.7. Verification Decisions, Label Licenses, and Renewal

Deciding a product `VERIFIED` is the program's most heavily guarded transition, and its gates are evaluated in a declared order so the first failure surfaces deterministically. After the state check — the product must be `UNDER_EVALUATION` — the chain runs: no ingredient may be `NON_COMPLIANT`, else `ERR_NON_COMPLIANT_RESULTS_EXIST`; then no ingredient may be `PENDING`, else `ERR_INGREDIENTS_PENDING`; then every sampling plan of the product that is not `CANCELLED` must be `COMPLETED`, else `ERR_INCOMPLETE_SAMPLING`; then at least one passed facility audit must exist for the brand, else `ERR_AUDIT_NOT_PASSED`; then no enforcement case may be open against the product, else `ERR_OPEN_ENFORCEMENT_CASE`; then the brand's `rolling_penalty_points` must be below 10, else `ERR_BRAND_RECENT_PENALTIES`; and finally the most recent passed audit must still be fresh per §3.6, else `ERR_AUDIT_STALE`.

A successful verification issues the product's label license — licenses are never created directly, only cascaded out of this decision. If the product has no license yet, one is created `ACTIVE` with `valid_from` set to the current time and `valid_until` set `license_term_days` days later; its `license_code` is `LIC-` followed by a six-digit zero-padded issuance sequence beginning at `LIC-000001`, a deterministic counter not derived from the license `id`. If instead the product's license is currently `SUSPENDED` with `suspend_reason` of `SCOPE_CHANGE`, verification reactivates it to `ACTIVE` with no validity extension, clearing `suspended_at` and `suspend_reason` to null. Either way the brand's `verified_product_count` is recomputed. The license resource itself is read-only through the API; its `status` moves among `ACTIVE`, `SUSPENDED`, `REVOKED`, and `EXPIRED` purely through cascades and clock sweeps, and `suspended_at` together with `suspend_reason` are null whenever the license is not suspended. License listings filter by `product_id` and `status`.

Renewal keeps a verified product in good standing year over year. The renewal window opens `renewal_window_days` before the license's `valid_until`; when the logical clock enters that window — at or after `valid_until` minus the window, and still before `valid_until` — while the license is `ACTIVE`, the sweep moves a `VERIFIED` product to `RENEWAL_DUE`. The brand's representative may renew from either `VERIFIED` or `RENEWAL_DUE`, and the request re-runs the standing gates: no open enforcement case on the product, the brand's `standing_status` must be `GOOD_STANDING` — probation blocks renewal with `ERR_BRAND_ON_PROBATION` — `rolling_penalty_points` below 10, affidavit currency across every paperwork-required ingredient as at submission, at least one passed audit for the brand, the renewal window currently open — too early or at-or-after expiry draws `ERR_RENEWAL_WINDOW_CLOSED` — and a fresh most-recent passed audit. A successful renewal extends `valid_until` by `license_term_days` days counted from the current `valid_until`, not from the renewal date, and returns a `RENEWAL_DUE` product to `VERIFIED`.

Scope changes reopen evaluation. Adding an ingredient to a `VERIFIED` or `RENEWAL_DUE` product moves it back to `UNDER_EVALUATION` and simultaneously suspends its `ACTIVE` license with `suspend_reason` of `SCOPE_CHANGE` and `suspended_at` stamped to now; additions to `DRAFT`, `REJECTED`, or `UNDER_EVALUATION` products leave enrollment state untouched. After the verifier re-evaluates the enlarged formulation, a fresh `VERIFIED` decision restores the license as described above.

Enforcement suspensions unwind differently. Reinstating a product — a `VerifierAdmin` action requiring the product be `SUSPENDED` with no open enforcement case — moves it from `SUSPENDED` back to `VERIFIED` and reactivates its license. When the `suspend_reason` is `ENFORCEMENT`, the license's `valid_until` is extended by the exact suspension duration — the elapsed time from `suspended_at` to the reinstatement instant — so the remaining validity is conserved across the suspend-and-reinstate pair; a `SCOPE_CHANGE` suspension earns no such extension. Reinstatement clears `suspended_at` and `suspend_reason` to null and raises the brand's `verified_product_count` by one.

Finally, products can fall out of the program passively. When the logical clock passes an `ACTIVE` license's `valid_until`, the sweep expires the license and moves a `VERIFIED` or `RENEWAL_DUE` product to `LAPSED`, recomputing the brand's verified-product count. `REVOKED` and `LAPSED` are terminal states for a product.

### 3.8. Claim-Misuse Enforcement and Brand Standing

The enforcement arm polices claim misuse in the market. An `EnforcementOfficer` opens a case with a payload containing the `product_id`, the `source` — one of `CONSUMER_COMPLAINT`, `MARKETPLACE_MONITOR`, or `RETEST_FAILURE` — and a free-text `description`. Cases may be opened against products in any `enrollment_status`, which is how unlicensed claim use by never-verified products is monitored. A new case is `OPENED` and records `opened_by_user_id`. Case listings filter by `product_id` and `status`.

Resolution requires a second officer: the resolver's identity must differ from `opened_by_user_id`, per §2.8, and the case must still be `OPENED`, else `ERR_CASE_NOT_OPEN`. The resolving officer supplies an `outcome`. A `DISMISSED` outcome must carry no `sanction` — supplying one is a shape error — and simply stamps `resolved_by_user_id`, with no further effects; a dismissed case contributes nothing to any counter. A `SUBSTANTIATED` outcome requires a `sanction` of `WARNING`, `LICENSE_SUSPENSION`, or `LICENSE_REVOCATION`, stamps both `resolved_by_user_id` and the `substantiated_at` timestamp, and fixes the case's `penalty_points` at 5 for a warning, 15 for a suspension, and 25 for a revocation; while open or once dismissed, a case's `penalty_points` remain zero.

Substantiation then fans out along two independent tracks. The brand track applies regardless of sanction: the case's points add into the brand's `lifetime_penalty_points`, an all-time sum over `SUBSTANTIATED` cases on the brand's products; `rolling_penalty_points` is recomputed as the same sum restricted to cases whose `substantiated_at` is strictly more recent than 365 days before now — a substantiation exactly 365 days old is excluded; and `standing_status` flips to `PROBATION` exactly when the lifetime total reaches 20 or more, otherwise `GOOD_STANDING`. These counters gate the program: probation blocks new enrollment and renewal, and a rolling total of 10 or more blocks verification decisions and renewal.

The license track depends on the sanction. A `LICENSE_SUSPENSION` pushes the product's `ACTIVE` license to `SUSPENDED` with `suspend_reason` of `ENFORCEMENT` and `suspended_at` stamped to now — and if the license was already `SUSPENDED` for a scope change, `suspended_at` resets to now and the reason becomes `ENFORCEMENT` — then moves a `VERIFIED` or `RENEWAL_DUE` product to `SUSPENDED`, and finally recomputes the brand's `verified_product_count`. A `LICENSE_REVOCATION` moves the license — whether `ACTIVE` or `SUSPENDED` — to `REVOKED` and a `VERIFIED`, `RENEWAL_DUE`, or `SUSPENDED` product to `REVOKED`, again recomputing the count. A `WARNING` stops at the brand track. Products without a license — those still `DRAFT`, `SUBMITTED`, `UNDER_EVALUATION`, or `REJECTED` — keep their enrollment state through all of this; only the penalty points land.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — state transitions, decisions, reviews, confirmations, and clock sets — return a `200 OK` status code. Readers reconstruct each operation's request payload and side effects from the narratives in §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/claim-standards` | Create a claim standard (thresholds configuration) | VerifierAdmin |
| GET | `/claim-standards` | List claim standards | Any |
| POST | `/brands` | Register a participant brand | VerifierAdmin |
| GET | `/brands/{id}` | Get one brand (penalty points, standing, verified product count) | Any |
| POST | `/products` | Enroll a product (own brand only; brand must be in good standing) | BrandRep |
| GET | `/products` | List products with filters and pagination | Any |
| GET | `/products/{id}` | Get one product (status, exposure fields, version) | Any |
| POST | `/products/{id}/submit` | Submit enrollment for review (ingredient and affidavit gates) | BrandRep |
| POST | `/products/{id}/begin-evaluation` | Verifier picks up a submitted product | VerifierAdmin |
| POST | `/products/{id}/decide` | Verification decision; VERIFIED issues or reinstates the license, REJECTED requires a reason | VerifierAdmin |
| POST | `/products/{id}/resubmit` | Resubmit a rejected product (clears the rejection reason) | BrandRep |
| POST | `/products/{id}/renew` | Annual renewal inside the window; extends license validity | BrandRep |
| POST | `/products/{id}/reinstate` | Lift an enforcement suspension; enforcement suspensions extend validity by the suspension duration | VerifierAdmin |
| POST | `/ingredients` | Add an ingredient; on a verified product this is a scope change that suspends the license | BrandRep |
| GET | `/ingredients` | List ingredients | Any |
| GET | `/ingredients/{id}` | Get one ingredient (exemption flags, compliance status) | Any |
| POST | `/affidavits` | Submit a supply-chain segregation affidavit; windows per ingredient and supplier must not overlap | BrandRep |
| GET | `/affidavits` | List affidavits | Any |
| GET | `/affidavits/{id}` | Get one affidavit | Any |
| POST | `/affidavits/{id}/review` | Accept or reject a submitted affidavit | VerifierAdmin |
| POST | `/sampling-plans` | Create a PCR sampling plan (optimistic-concurrency guarded; supersedes the product's prior plans) | VerifierAdmin |
| GET | `/sampling-plans` | List sampling plans | Any |
| GET | `/sampling-plans/{id}` | Get one sampling plan | Any |
| POST | `/samples` | Collect a sample under a plan; ingredient must belong to the plan's product and require PCR | LabAnalyst |
| GET | `/samples` | List samples | Any |
| GET | `/samples/{id}` | Get one sample | Any |
| POST | `/samples/{id}/record-result` | Record a PCR result | LabAnalyst |
| POST | `/samples/{id}/confirm` | Confirm a recorded result; confirmer must differ from recorder | LabAnalyst |
| POST | `/samples/{id}/invalidate` | Invalidate a recorded or confirmed sample (compensates confirmation) | LabAnalyst, VerifierAdmin |
| POST | `/facility-audits` | Schedule a facility audit; at most one open audit per facility | VerifierAdmin |
| GET | `/facility-audits` | List facility audits | Any |
| GET | `/facility-audits/{id}` | Get one facility audit | Any |
| POST | `/facility-audits/{id}/submit-report` | Assigned auditor submits traceability exercise lots; computes the traceability score | Auditor |
| POST | `/facility-audits/{id}/decide` | Decide audit outcome; PASSED requires a traceability score of at least 95.00 | VerifierAdmin |
| GET | `/licenses` | List label licenses | Any |
| GET | `/licenses/{id}` | Get one label license | Any |
| POST | `/enforcement-cases` | Open a claim-misuse case against any product | EnforcementOfficer |
| GET | `/enforcement-cases` | List enforcement cases | Any |
| GET | `/enforcement-cases/{id}` | Get one enforcement case | Any |
| POST | `/enforcement-cases/{id}/resolve` | Resolve a case (resolver differs from opener); SUBSTANTIATED cascades sanctions | EnforcementOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock and run the time-driven sweeps | VerifierAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_BRAND_RESOURCE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_AUDITOR` | 403 Forbidden |
| `ERR_BRAND_ON_PROBATION` | 403 Forbidden |
| `ERR_BRAND_RECENT_PENALTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_INVALID_STATE` | 409 Conflict |
| `ERR_NO_INGREDIENTS` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_SAMPLE_INVALID_STATE` | 409 Conflict |
| `ERR_AUDIT_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_AFFIDAVIT_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_AFFIDAVIT_MISSING` | 409 Conflict |
| `ERR_AFFIDAVIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_AUDIT_NOT_PASSED` | 409 Conflict |
| `ERR_AUDIT_STALE` | 409 Conflict |
| `ERR_OPEN_ENFORCEMENT_CASE` | 409 Conflict |
| `ERR_NON_COMPLIANT_RESULTS_EXIST` | 409 Conflict |
| `ERR_INGREDIENTS_PENDING` | 409 Conflict |
| `ERR_INCOMPLETE_SAMPLING` | 409 Conflict |
| `ERR_AUDIT_CAPACITY_CONFLICT` | 409 Conflict |
| `ERR_TRACE_SCORE_BELOW_MIN` | 409 Conflict |
| `ERR_PRODUCT_GTIN_EXISTS` | 409 Conflict |
| `ERR_INGREDIENT_NOT_TESTABLE` | 409 Conflict |
| `ERR_CROSS_REFERENCE_MISMATCH` | 409 Conflict |
| `ERR_WEIGHT_SUM_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

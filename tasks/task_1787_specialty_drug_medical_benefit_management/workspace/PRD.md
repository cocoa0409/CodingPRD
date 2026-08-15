# Specialty Drug Medical-Benefit Management API — Product Requirements Document

## 1. Introduction

Specialty pharmaceuticals administered in clinical settings — infused oncology agents, biologics, enzyme replacement therapies — are reimbursed under the medical benefit rather than the pharmacy benefit. That single fact forces a health plan's pharmacy department to make a sourcing decision on every claim (buy-and-bill through the administering provider versus specialty-pharmacy "white bag" dispensing), to validate HCPCS J-code billing down to the billed unit and the discarded-waste level, and to keep provider reimbursement aligned with Average Sales Price benchmarks that move over time. Layered on top are a site-of-care redirection program that steers infusions out of hospital outpatient departments, a biosimilar substitution policy with provider and member incentives, weight-based dose optimization, and the need to forecast the budget impact of drugs still in the approval pipeline.

This document specifies the Specialty Drug Medical-Benefit Management API, the system of record for that operation. It governs the drug catalog and its dosing architecture, ASP rate schedule publication with retroactive repricing into a provider payment ledger, versioned clinical policies guarded by optimistic concurrency, the prior-authorization lifecycle from submission through approval, suspension, expiry, and exhaustion, synchronous infusion-claim adjudication with a dose-tolerance review fork, the redirection offer workflow, biosimilar policy windows, and pipeline spend forecasting. A logical, test-drivable clock — never the wall clock — governs every time-dependent rule so that effective-dated behavior is deterministic.

## 2. Global Specifications & System-Wide Principles

All endpoints described in this document are mounted under the `/api` URL prefix. Every mutation, together with all cascades it triggers, commits atomically within the request that caused it. The resources of this API are organized as flat, top-level collections; relationships between them are expressed through identifier fields carried on the resources and through filtered list queries, not through nested URL hierarchies.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly five roles: `PlanAdmin`, `MedicalPolicyOfficer`, `ProviderRep`, `CaseManager`, and `PharmacyAnalyst`. A request missing either header, or naming a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the caller's context is established, each operation is restricted to designated roles per §4; an authenticated caller attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Identity semantics differ by role, and the difference matters for ownership checks. When `X-User-Role` is `ProviderRep`, `X-User-ID` is the `id` of the acting `ProviderAccount`; ownership checks on any resource that references a `ProviderAccount` compare the resource's foreign-key field to `X-User-ID`. Prior authorizations and infusion claims created by a provider representative are stamped with that account as their `provider_account_id`. For the remaining four roles — `PlanAdmin`, `MedicalPolicyOfficer`, `CaseManager`, and `PharmacyAnalyst` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `override_by` on a claim where a medical override writes it) but does not compare it to any entity's `id`.

Provider representatives read through a scope lens. A `ProviderRep` addressing a resource that belongs to a different provider account is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` (HTTP 403). This scope guard applies to five read surfaces: the claims collection and single-claim reads (`GET /api/claims`, `GET /api/claims/{claimId}`), the prior-authorization collection and single-authorization reads (`GET /api/prior-authorizations`, `GET /api/prior-authorizations/{authId}`), single provider-account reads (`GET /api/provider-accounts/{accountId}`), the redirections collection (`GET /api/redirections`), and the claim-adjustments collection (`GET /api/claim-adjustments`). List queries issued by a provider representative without an explicit foreign `provider_account_id` filter are not rejected; they are silently scoped to the caller's own account. Redirection and adjustment records carry no provider field of their own; their scope is resolved through the owning authorization and claim respectively.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Time-Driven Transitions

A server-side logical clock — not the wall clock — decides every time-sensitive rule in this system: rate schedule activation, authorization and offer expiry, biosimilar policy expiry, and every date comparison in the validation pipeline. At startup, before any call, the clock reads exactly 2026-08-01T00:00:00Z. A `PlanAdmin`-only test-driving capability advances it: the caller supplies `to_iso8601`, an ISO 8601 UTC instant, and the server sets its logical clock to that value. Setting the clock eagerly applies every transition that has come due — rate schedules whose `effective_start` has been reached activate (running the repricing cascade of §3.3), authorizations whose validity window has closed expire, redirection offers more than thirty days old lapse, and biosimilar policies whose window has closed expire. The same due transitions are also applied lazily, immediately before any precondition check that reads a time-sensitive entity, so observable behavior never depends on whether the clock was set explicitly first.

### 2.5. Common Resource Properties

Most resources carry four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, in the same format, refreshed on every mutation; and `version`, a system-managed integer that increments with every mutation and anchors optimistic concurrency where §2.7 applies. Two resources are immutable records and deliberately carry only `id` and `created_at`: the claim adjustment, an append-only repricing event, and the spend-forecast run, a computed snapshot. Neither has `updated_at` nor `version`, because neither is ever modified after creation.

### 2.6. Monetary Values, Units, and Rounding Discipline

All monetary amounts are integer cents; fractional cents never appear in stored values or responses. Rates carried as fractions — add-on percentages, coinsurance, waivers, erosion — are exact decimal fractions. Rounding, where required, is round-half-up to whole cents, and the rounding point matters. Claim pricing rounds each payable component — the administered-drug amount and the payable-waste amount — individually before summing them; a sum-first-then-round computation is a different, non-conformant result. Forecast projections round each drug's per-year cost before summing across years; the policy-adjusted forecast variant rounds its erosion multiplier once per drug; the in-line annualization rounds once at the end. Doses are whole milligrams, and a weight-derived raw dose is kept exact until the rounding step of dose optimization.

### 2.7. Optimistic Concurrency Control on the Drug Policy Lineage

Two writes are guarded by optimistic concurrency: creating a clinical policy for a drug — in either `DRAFT` or `ACTIVE` status — and activating an existing `DRAFT` clinical policy. Both require the client to present `expected_drug_version`, the `version` of the governing `DrugCatalogEntry` as the client last observed it. If the presented value does not equal the drug's current `version`, the request is rejected with `ERR_STALE_DRUG_VERSION` (HTTP 412), and this check is evaluated before any business rule on the request. The rule exists because every policy creation or activation advances the drug's `version` — activation also supersedes the prior `ACTIVE` version under the create-with-supersede rule — so a client holding an older `version` is by definition working from a stale view of the drug's policy lineage and must re-read the drug before writing. The single-drug read is the canonical source of the current `version`. No other endpoint takes a version field: authorization, claim, payment, redirection, schedule, biosimilar, and forecast writes are not OCC-guarded.

### 2.8. The Validation Pipeline and Error Precedence

Every request is evaluated against an ordered pipeline, and an earlier failure masks later ones — the first failing stage determines the error returned. The stages, in order:

1. **Header context** (§2.1): both headers present and the role declared.
2. **Role permission**: the role is authorized for this endpoint per §4.
3. **ProviderRep scope guard** (§2.1): a provider representative never touches another account's resources.
4. **Request shape**: required fields present, types correct, enum members valid, and conditional-field rules honored — `mg_per_kg` present exactly when the drug is weight-based, `rounding_increment_mg` present exactly when the rounding mode is `INCREMENT`, `accepted_site` among the offered candidates, `horizon_years` within its allowed range, rates and percentages positive where required. Shape failures surface as `ERR_INVALID_REQUEST` and always precede existence checks.
5. **Existence** (§2.9): path identifiers resolve left to right, then body references resolve, surfacing as `ERR_NOT_FOUND`.
6. **Optimistic concurrency** (§2.7): the `expected_drug_version` check, deliberately placed before any business rule.
7. **Target-state gates**: the named action is legal in the resource's current state — approval or denial requires a `SUBMITTED` authorization, suspension an `APPROVED` one, reinstatement a `SUSPENDED` one, cancellation a non-terminal one, policy activation a `DRAFT` policy, biosimilar activation a `DRAFT` biosimilar policy, override and denial a `PENDED` claim, payment an `APPROVED_FOR_PAYMENT` claim, offer response an `OFFERED` redirection, and recoupment settlement a `RECOUPMENT_HOLD` account.
8. **Cross-entity state gates**: a claim requires an `APPROVED` authorization, a payment requires an `ACTIVE` provider account, and authorization approval requires an `ACTIVE` clinical policy for the drug.
9. **Clinical safety**: dosing-input completeness, diagnosis coverage, step therapy, mandatory biosimilar substitution, the single-dose cap, and the JW/waste rules.
10. **Referential coherence**: the billed drug and J-code match the authorization and catalog, vial geometry is legal, the biosimilar mapping is non-degenerate, and J-codes stay unique.
11. **Temporal rules**: dates against the clock, against authorization validity windows, and against policy windows.
12. **Sourcing and site-of-care program rules**: the claim's sourcing path and site against the drug's sourcing rule and any accepted redirection.
13. **Fiscal gates**, evaluated in this sub-order: first that an ASP rate exists for the drug on the service date, then the administered-dose tolerance check.

### 2.9. Identifier Resolution and Referential Existence

When an endpoint path contains resource identifiers, the system validates their existence in a strict left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that names no existing resource, before later identifiers or the body are examined. After the path resolves, foreign references in the request body — `auth_id`, `drug_id`, `reference_drug_id`, `biosimilar_drug_id` — must each name an existing resource, or the request fails with the same error. Because every collection here is top-level, hierarchy never rescues a missing reference: an identifier either names an existing resource or the request stops.

### 2.10. Provider Ledger Integrity

Each provider account maintains two computed ledger fields, both zero at registration. `cumulative_paid_cents` is the running total the plan has paid the provider: a claim payment adds the claim's `allowed_amount_cents`, and each retroactive repricing adjustment adds that adjustment's `delta_cents`, which may be negative. `recoupment_balance_cents` accumulates outstanding negative repricing deltas as positive cents — money the plan must recover from the provider. The moment a repricing leaves `recoupment_balance_cents` greater than zero, the account flips automatically from `ACTIVE` to `RECOUPMENT_HOLD`, and while on hold every payment to that provider is refused. Settling recoupment zeroes the balance and returns the account to `ACTIVE`. Ledger movements, and the account state flips they trigger, commit atomically with the request that caused them.

## 3. Business Logic & Workflows

### 3.1. Registering Drugs: Catalog Geometry and Dosing Architecture

A `PlanAdmin` registers each specialty drug in the catalog. The registration names the HCPCS `j_code` — unique across all drugs, so a duplicate registration is rejected with `ERR_JCODE_NOT_UNIQUE` — a display `drug_name`, and the billing geometry: `billing_unit_mg`, the milligrams represented by one billed J-code unit, which must be at least 1, and `vial_size_mg`, the single-vial size, which must be a positive whole multiple of the billing unit or registration fails with `ERR_INVALID_VIAL_UNIT_RATIO`. The `single_dose_vial` flag records the vial presentation and governs whether discarded waste is ever payable on claims (§3.6). The `site_of_care_eligible` flag marks whether the drug participates in the redirection program (§3.5).

Every drug also anchors the plan's sourcing decision through its `sourcing_rule`: `BUY_AND_BILL_ONLY`, `SPECIALTY_PHARMACY_ONLY`, or `EITHER`. Claims are checked against this rule at adjudication, as §3.6 describes.

The dosing architecture completes the registration. `weight_based_dosing` defaults to false; when it is true, `mg_per_kg` must be present, and when false it must be absent — likewise `rounding_increment_mg` must be present exactly when `dose_rounding_mode` is `INCREMENT` — and violations of these conditional-presence rules are shape errors rejected with `ERR_INVALID_REQUEST`. The `dose_rounding_mode`, either `VIAL` or `INCREMENT`, selects which dose-optimization variant runs at authorization approval (§3.4). Finally, `max_single_dose_mg` is an inclusive cap enforced twice — at authorization submission against `requested_dose_mg`, and at approval against the computed dose: a dose exactly equal to the cap is allowed, while one milligram above it is rejected with `ERR_DOSE_EXCEEDS_MAX`.

All five roles may browse the catalog, with the collection filterable by `sourcing_rule` and `site_of_care_eligible`. The single-drug read is the canonical source of the drug's `version` used by the policy OCC rules of §2.7.

### 3.2. Clinical Policy Versioning and Create-with-Supersede

Coverage policy is authored per drug by a `MedicalPolicyOfficer`. Policy creation carries `drug_id`, a non-empty `covered_diagnoses` list of ICD-10 codes, the `step_therapy_required` and `requires_site_of_care_redirection` flags, a `biosimilar_substitution` stance of `DISABLED`, `PREFERRED`, or `MANDATORY`, the desired initial `status` — `DRAFT` or `ACTIVE` — and the OCC field `expected_drug_version` (§2.7). Each new version receives the next per-drug sequential `version_no`, starting at 1, so successive versions of one drug's policy read 1, 2, 3, and so on.

Versioning follows a create-with-supersede discipline. Creating a policy version — whether it is born `DRAFT` or `ACTIVE` — increments the governing drug's `version` by one, and activating a `DRAFT` version later increments it again. Whenever a version becomes `ACTIVE`, whether atomically at creation or through later activation, the prior `ACTIVE` version for the same drug flips to `SUPERSEDED` in the same commit. Activation is refused unless the policy is `DRAFT`, failing with `ERR_POLICY_NOT_DRAFT`; per the pipeline of §2.8, the `expected_drug_version` check runs before that business rule and before every other business rule on the request.

`SUPERSEDED` is terminal, and superseded versions never govern new approvals. Authorizations approved under a version keep their pinned reference to it forever (§3.4), which is what makes historical adjudication auditable even after policy evolves. Policies are listable filtered by `drug_id` and `status`.

### 3.3. ASP Rate Schedules, Retroactive Repricing, and Recoupment

Provider reimbursement follows the Average Sales Price. A `PlanAdmin` publishes a rate schedule with `drug_id`, an ISO calendar `effective_start`, and `asp_rate_cents` — the per-billing-unit price in cents, which must be greater than zero or the publication fails with `ERR_INVALID_REQUEST`. A schedule whose `effective_start` lies in the future is born `SCHEDULED`; one whose `effective_start` is on or before the current clock date lands directly in `EFFECTIVE` at creation. The rate that prices any given service date is the `asp_rate_cents` of that drug's schedule with the greatest `effective_start` on or before the service date; several schedules may share an `effective_start`, and in that case the one with the latest `created_at` wins.

Activation — immediate at creation or later through the clock sweep — cascades through the book of business. Every other `EFFECTIVE` schedule for the same drug becomes `SUPERSEDED`; when a sweep finds several schedules of one drug due at once, they activate in ascending `effective_start` order so that the latest-dated schedule ends `EFFECTIVE`. Retroactive repricing then runs over the drug's claims. Candidates are claims whose `service_date` falls on or after the new `effective_start` and whose `asp_schedule_id_used` is not already this schedule; they are processed in chronological order — `service_date` ascending, ties broken by `created_at` ascending, never by identifier. Each candidate is re-evaluated at the new rate under the pricing rules of §3.6, with the add-on recomputed under the rules in force.

Two branches diverge at payment status, and both matter equally. A claim already `PAID` or `ADJUSTED` moves to — or remains in — `ADJUSTED`; its `allowed_amount_cents` and `asp_schedule_id_used` are updated; and an immutable adjustment record is written carrying `claim_id`, the triggering `asp_schedule_id`, `old_allowed_cents`, `new_allowed_cents`, their signed difference `delta_cents` (negative when the new rate pays less), and `reason` `ASP_RETRO`. The delta is then applied to the provider's ledger per §2.10: `cumulative_paid_cents` absorbs the signed `delta_cents`, a negative delta grows `recoupment_balance_cents` by its magnitude, and once every candidate claim has been processed, any provider left with a positive recoupment balance flips to `RECOUPMENT_HOLD`. A claim still unpaid — `APPROVED_FOR_PAYMENT` or `PENDED` — is instead repriced in place: `allowed_amount_cents` and `asp_schedule_id_used` update, `member_cost_share_cents` is recomputed, and no adjustment record or ledger movement occurs. Member cost share on already-paid claims is deliberately never retro-adjusted.

Provider accounts themselves are registered by a `PlanAdmin` with a display `name`; both ledger fields start at zero and the account starts `ACTIVE`. While an account is in `RECOUPMENT_HOLD`, payments to it are refused with `ERR_PROVIDER_RECOUPMENT_HOLD`. A `PlanAdmin` settles recoupment on a held account — attempting settlement on an account not on hold fails with `ERR_PROVIDER_NOT_ON_HOLD` — which zeroes `recoupment_balance_cents` and returns the account to `ACTIVE`. Accounts are listable filtered by `status`, and the account collection is not exposed to provider representatives.

### 3.4. Prior Authorization: Submission, Approval Gates, and the Lifecycle

A `ProviderRep` opens a prior authorization for a member by submitting `drug_id`, the plan's opaque `member_id`, a `diagnosis_code`, and a `requested_start_date`, which must not be earlier than the current clock date or submission fails with `ERR_START_DATE_IN_PAST`. Dosing input depends on the drug's architecture: a weight-based drug requires `weight_kg`, while any other drug requires `requested_dose_mg`, and the missing input fails with `ERR_MISSING_WEIGHT_OR_DOSE`. A submitted `requested_dose_mg` above the drug's `max_single_dose_mg` fails immediately with `ERR_DOSE_EXCEEDS_MAX`; a value equal to the cap passes. `step_therapy_completed` defaults to false when omitted. The new authorization lands in `SUBMITTED`, stamped with the creating representative's account as `provider_account_id`.

Approval by a `MedicalPolicyOfficer` walks its gates in a fixed order, and the first failing gate is the one reported. The authorization must be `SUBMITTED`, otherwise `ERR_AUTH_NOT_PENDING`. An `ACTIVE` clinical policy must exist for the drug, otherwise `ERR_NO_ACTIVE_POLICY`. The `diagnosis_code` must appear in that policy's `covered_diagnoses`, otherwise `ERR_DIAGNOSIS_NOT_COVERED`. When the policy's `step_therapy_required` is set, the authorization's `step_therapy_completed` must be true, otherwise `ERR_STEP_THERAPY_REQUIRED`. When the policy's `biosimilar_substitution` is `MANDATORY`, no `ACTIVE` biosimilar policy for the same reference drug may cover `requested_start_date` within its half-open window, otherwise `ERR_BIOSIMILAR_SUBSTITUTION_REQUIRED` (§3.7). The computed dose must not exceed `max_single_dose_mg`, otherwise `ERR_DOSE_EXCEEDS_MAX`. Finally, no other authorization for the same `member_id` and drug may sit in `APPROVED` or `SUSPENDED` with an overlapping validity window, otherwise `ERR_AUTH_WINDOW_OVERLAP`. Because validity windows are closed intervals, overlap is symmetric and inclusive: two windows overlap exactly when each window's start falls on or before the other window's end — windows that merely touch on a single calendar date do overlap.

Approving computes `approved_dose_mg` — null until this point — by dose optimization. The raw dose is `requested_dose_mg` for a conventional drug, or `weight_kg` multiplied by `mg_per_kg` for a weight-based one, kept exact until rounding. Under the `VIAL` variant, the raw dose is divided by `vial_size_mg`, rounded up to the next whole vial count, and multiplied back — guaranteeing enough drug on hand, so a 172 mg raw dose against 100 mg vials approves at 200 mg. Under the `INCREMENT` variant, the raw dose is divided by `rounding_increment_mg`, rounded half-up to the nearest whole increment, and multiplied back — so the same 172 mg raw dose against a 10 mg increment approves at 170 mg. The approval request itself supplies `max_administrations`, which must be at least 1. On approval the validity window is pinned: `validity_start` equals `requested_start_date`, and `validity_end` is exactly 180 days later, the window closed on both ends. The governing policy's identity is pinned onto the authorization as `policy_id` and `policy_version_no` — both null until approval — `administrations_used` starts at zero, and, when the policy's `requires_site_of_care_redirection` is set and the drug is `site_of_care_eligible`, an `OFFERED` redirection springs into existence automatically (§3.5).

From `SUBMITTED`, a `MedicalPolicyOfficer` may instead deny: the payload's `reason` is recorded as `denial_reason` — null at every other time — and the authorization becomes `DENIED`, terminal. Cancellation is legal from `SUBMITTED`, `APPROVED`, or `SUSPENDED`; attempted from a terminal authorization it fails with `ERR_AUTH_NOT_CANCELLABLE`. Cancelling withdraws any `OFFERED` redirection attached to the authorization, moving it to `EXPIRED`.

Suspension and reinstatement form a cycle for mid-flight investigations. Suspending requires the authorization to be `APPROVED` — otherwise `ERR_AUTH_NOT_APPROVED` — and moves it to `SUSPENDED`; every claim of that authorization currently `APPROVED_FOR_PAYMENT` is pended with `pend_reason` `AUTH_SUSPENDED`, while `PAID`, `ADJUSTED`, and dose-review-pended claims are untouched. Reinstating requires `SUSPENDED` — otherwise `ERR_AUTH_NOT_SUSPENDED` — and returns the authorization to `APPROVED`; exactly those claims pended with `AUTH_SUSPENDED` return to `APPROVED_FOR_PAYMENT`, claims pended for dose review stay pended, and `administrations_used` is left unchanged.

Two system transitions close the lifecycle. When the clock's current date passes `validity_end`, the authorization expires to `EXPIRED` — applied lazily before any precondition check on the authorization and eagerly whenever the clock is set. Expiry from `APPROVED` is quiet; expiry from `SUSPENDED` additionally denies every claim still pended with `AUTH_SUSPENDED`, stamping `denial_reason` `AUTH_EXPIRED` on each. Separately, whenever a claim-approval debit brings `administrations_used` to `max_administrations`, the authorization becomes `EXHAUSTED` — terminal, and further claims against it fail with `ERR_AUTH_NOT_APPROVED`, just as they would against any authorization that is not approved. The lifecycle's full state vocabulary is `SUBMITTED`, `APPROVED`, `DENIED`, `SUSPENDED`, `EXPIRED`, `CANCELLED`, and `EXHAUSTED`.

Authorizations are listable by all roles, filtered by `drug_id`, `member_id`, `status`, `provider_account_id`, or the pinned `policy_id`, with provider representatives auto-scoped per §2.1.

### 3.5. Site-of-Care Redirection Offers

The redirection program steers infusions away from the hospital outpatient department. Each auto-created offer begins `OFFERED`, with `from_site` fixed at `HOPD` — the high-cost site being redirected away from — and `candidate_sites` listing `OFFICE`, `HOME`, and `AMBULATORY`. A `CaseManager` records the member's decision.

Acceptance requires three things: the offer still `OFFERED`, otherwise `ERR_REDIRECTION_NOT_OFFERED`; an `accepted_site` that is one of the offered candidates, otherwise `ERR_INVALID_REQUEST`; and the authorization still `APPROVED`, otherwise `ERR_AUTH_NOT_APPROVED`. On acceptance the member's estimated waived cost share is computed and stored as `member_incentive_cents` — zero until then. The estimate takes the authorization's `approved_dose_mg` divided by the drug's `billing_unit_mg`, rounded up to a whole estimated unit count; multiplies that count by the ASP rate effective on the current clock date — the drug's schedule with the greatest `effective_start` on or before today, ties broken by latest `created_at`, and if no schedule is effective yet the acceptance fails with `ERR_NO_ASP_RATE` — and by one plus the six percent base add-on, rounded half-up to whole cents; the incentive is then twenty percent of that estimated allowed amount, again rounded half-up to whole cents. The chosen `accepted_site` — null until acceptance — is recorded.

Declining simply moves the offer to `DECLINED`, terminal. An offer left open lapses to `EXPIRED` once the current clock date is more than thirty days after its creation, and cancellation of the authorization expires it immediately (§3.4).

An `ACCEPTED` redirection binds later claims twice over. The claim's `site_of_care` must equal the `accepted_site`, or adjudication fails with `ERR_SITE_OF_CARE_VIOLATION`; and when the site matches, pricing earns the redirection add-on and the member's cost share on that claim is waived to zero (§3.6). Redirections are listable filtered by `auth_id` and `status`, with provider representatives auto-scoped per §2.1.

### 3.6. Infusion Claims: Synchronous Adjudication, the Tolerance Fork, and Payment

A `ProviderRep` bills an administration by submitting a claim whose payload carries `auth_id`, `drug_id`, `service_date`, `site_of_care` — one of `HOPD`, `OFFICE`, `HOME`, or `AMBULATORY` — `sourcing_path` as `BUY_AND_BILL` or `WHITE_BAG`, `j_code_billed`, `billed_units` of at least 1, and optionally `waste_units` (default zero) and `jw_modifier` (default false). The claim's `provider_account_id` is stamped from the caller. Creation returns 201, but `SUBMITTED` is transient: adjudication runs synchronously inside the request, and the returned claim is already `APPROVED_FOR_PAYMENT` or `PENDED`, with `pend_reason` set only in the pended case and null otherwise.

Adjudication runs the full validation pipeline of §2.8. The authorization must be `APPROVED` — anything else, including `SUSPENDED`, `EXPIRED`, or `EXHAUSTED`, fails with `ERR_AUTH_NOT_APPROVED`. The billed `drug_id` must equal the authorization's drug (`ERR_DRUG_AUTH_MISMATCH`), and `j_code_billed` must equal the drug's catalog `j_code` (`ERR_JCODE_MISMATCH`). The `service_date` must not be later than the current clock date (`ERR_FUTURE_SERVICE_DATE`) and must fall inside the authorization's closed validity window from `validity_start` through `validity_end` (`ERR_SERVICE_DATE_OUT_OF_WINDOW`). Sourcing is checked against the drug's `sourcing_rule`: `BUY_AND_BILL_ONLY` requires `sourcing_path` `BUY_AND_BILL`, `SPECIALTY_PHARMACY_ONLY` forbids that path, and `EITHER` accepts both — violations fail with `ERR_SOURCING_VIOLATION` — and an `ACCEPTED` redirection constrains the site per §3.5.

The JW-modifier waste rules guard discarded drug. Reporting `waste_units` above zero without setting `jw_modifier` fails with `ERR_JW_MODIFIER_REQUIRED`. Setting `jw_modifier` while reporting zero `waste_units` fails with `ERR_JW_WITHOUT_WASTE`. Reporting waste on a drug whose `single_dose_vial` is false fails with `ERR_WASTE_NOT_PAYABLE_MULTIDOSE`. And because a whole vial or more can never be discarded as waste, `waste_units` must be strictly less than the number of billing units in one vial — `vial_size_mg` divided by `billing_unit_mg` — or the claim fails with `ERR_WASTE_EXCEEDS_VIAL`.

Pricing follows the claim-allowed-amount calculation. The administered quantity `administered_mg` is `billed_units` multiplied by the drug's `billing_unit_mg` and deliberately excludes waste. The ASP rate resolves for the `service_date` per §3.3; if no schedule of the drug is effective yet, adjudication fails with `ERR_NO_ASP_RATE`. The total add-on fraction combines three components with equal standing: a six percent base add-on always applies; a further two percent applies exactly when the authorization holds an `ACCEPTED` redirection and the claim's `site_of_care` equals its `accepted_site`; and the biosimilar policy's `provider_incentive_addon_pct` applies when an `ACTIVE` biosimilar policy names the claim's drug as its biosimilar and the claim's `service_date` falls inside that policy's half-open window. `payable_waste_units` equals `waste_units` when the drug is single-dose and `jw_modifier` is set, and zero otherwise. Rounding is pinned per component: the drug component — `billed_units` times the rate times one plus the total add-on — is rounded half-up to whole cents; the waste component — `payable_waste_units` times the rate times one plus the same add-on — is rounded half-up independently; and `allowed_amount_cents` is the sum of the two rounded components. Summing first and rounding once is non-conformant: at a 325-cent rate with the six percent base add-on, 3 billed units plus 1 payable waste unit yields 1034 plus 345 — an allowed amount of 1379 cents — where sum-first arithmetic would yield 1378. The rate used, the total add-on fraction, and the schedule's identity are stored on the claim as `asp_rate_cents`, `addon_pct_applied`, and `asp_schedule_id_used`.

Member cost share is decided at the same moment. When the claim lands exactly on an accepted redirection's site, `member_cost_share_cents` is zero. Otherwise it is twenty percent of `allowed_amount_cents`, reduced by the `member_copay_waiver_pct` of any `ACTIVE` biosimilar policy covering the claim's drug and service date — zero waiver when none — rounded half-up once at the end. The figure is recomputed whenever an unpaid claim is repriced in place (§3.3, §3.7), but it is never retro-adjusted once the claim is `PAID` or `ADJUSTED`.

Adjudication then forks on dose. When `administered_mg` does not exceed `approved_dose_mg`, the claim lands `APPROVED_FOR_PAYMENT`: the authorization's `administrations_used` is incremented by one, and if that brings it to `max_administrations` the authorization immediately becomes `EXHAUSTED` (§3.4). An overage within the inclusive ten-percent tolerance instead pends the claim with `pend_reason` `DOSE_REVIEW` — provisional pricing is computed and stored, but no administration is debited. An overage beyond tolerance is rejected outright with `ERR_DOSE_EXCEEDS_APPROVED`: the boundary is exact, so a claim is rejected precisely when ten times the administered milligrams is greater than eleven times the approved milligrams, while equality still pends. These fiscal gates — rate existence and the tolerance boundary — guard both the initial adjudication and the medical override decision below.

A `MedicalPolicyOfficer` resolves pended claims. Override approval requires the claim to be `PENDED` (otherwise `ERR_CLAIM_NOT_PENDED`) and the authorization to be `APPROVED` (otherwise `ERR_AUTH_NOT_APPROVED`); an approved authorization always has administration headroom, because reaching the cap auto-exhausts it. The override records the acting officer in `override_by` — null on claims that approved directly at adjudication, which keeps the two branches auditable — returns the claim to `APPROVED_FOR_PAYMENT` at its adjudication-fixed price, since override deliberately does not re-price, and performs the same administration debit and possible exhaustion as the direct branch. Denial likewise requires the claim to be `PENDED`, records the payload's `reason` as `denial_reason`, and terminates the claim as `DENIED`.

Payment is a `PlanAdmin` act on an `APPROVED_FOR_PAYMENT` claim (otherwise `ERR_CLAIM_NOT_PAYABLE`) whose provider account is `ACTIVE` (otherwise `ERR_PROVIDER_RECOUPMENT_HOLD`). Payment stamps `paid_at` — null until this moment — with the current clock timestamp, moves the claim to `PAID`, and credits `allowed_amount_cents` to the provider ledger per §2.10. From `PAID`, later ASP repricing moves the claim to `ADJUSTED` with a full audit record, and further repricings keep it `ADJUSTED` (§3.3). Claims are listable by all roles with filters `auth_id`, `drug_id`, `provider_account_id`, `status`, and `asp_schedule_id_used`; the adjustment log is listable by `claim_id` and `asp_schedule_id`; both surfaces auto-scope provider representatives per §2.1.

### 3.7. Biosimilar Substitution Policy and Incentive Windows

A `PlanAdmin` maintains substitution policy between a reference biologic and its preferred biosimilar. Creating a policy names `reference_drug_id` and `biosimilar_drug_id` — which must differ, or creation fails with `ERR_REFERENCE_SELF_BIOSIMILAR` — plus `provider_incentive_addon_pct`, an extra reimbursement add-on fraction greater than zero and at most ten percent, `member_copay_waiver_pct`, the waived fraction of member cost share anywhere from zero to one inclusive, and the half-open effective window from `effective_start` (inclusive) to `effective_end` (exclusive), where the end must be later than the start (`ERR_INVALID_WINDOW`). New policies start `DRAFT`.

Activation, also by a `PlanAdmin`, requires a `DRAFT` policy — otherwise `ERR_BIOSIMILAR_POLICY_NOT_DRAFT` — and enforces window hygiene under half-open semantics. No other `ACTIVE` policy for the same reference drug may overlap the new window: two windows overlap exactly when each window's start is strictly before the other window's end, so a touching boundary where one window's end equals the other's start does not overlap; violations fail with `ERR_POLICY_WINDOW_OVERLAP`. Independently, the biosimilar drug must not already be mapped by another `ACTIVE` policy, or activation fails with `ERR_BIOSIMILAR_ALREADY_MAPPED`. Activation also reprices in flight: claims on the biosimilar drug that are still unpaid — `APPROVED_FOR_PAYMENT` or `PENDED` — with a `service_date` inside the new window are repriced in place with the incentive add-on, producing no adjustment record and no ledger movement, exactly as in the unpaid branch of §3.3, and their member cost share is recomputed under the new waiver. When the current clock date reaches `effective_end`, the policy expires to `EXPIRED`.

The policy's teeth show up upstream at authorization approval: when the drug's `ACTIVE` clinical policy sets `biosimilar_substitution` to `MANDATORY`, an `ACTIVE` biosimilar policy whose window covers the requested start date blocks approval of the reference drug outright with `ERR_BIOSIMILAR_SUBSTITUTION_REQUIRED` (§3.4). The `PREFERRED` and `DISABLED` stances impose no such approval block. Biosimilar policies are listable filtered by `reference_drug_id`, `biosimilar_drug_id`, and `status`.

### 3.8. Pipeline Registry and Spend Forecasting

Planning for future spend starts with the pipeline registry. A `PlanAdmin` registers each investigational drug with its `drug_name`, `expected_approval_date`, `prevalence_per_100k` — eligible patients per hundred thousand members, greater than zero — `projected_annual_cost_cents` per treated patient, also greater than zero, `year1_uptake_pct` as the treated fraction of eligible patients in the launch year, `steady_state_uptake_pct` as the treated fraction in each full post-launch year — both greater than zero and at most one — and `biosimilar_erosion_pct`, at least zero and strictly less than one, which only the policy-adjusted forecast variant applies.

A `PharmacyAnalyst` runs a forecast by supplying `variant` — `BASELINE` or `POLICY_ADJUSTED` — `horizon_years` of one through five inclusive (outside that range the run is rejected with `ERR_INVALID_REQUEST`), and `enrollment_projection` of at least one member. The run stamps `as_of_date` with the current clock date and stores an immutable snapshot per §2.5. Forecast year one begins on the as-of date and each subsequent year begins one calendar year later: year y spans the half-open interval from the as-of date plus (y−1) whole years up to — but not including — the as-of date plus y whole years.

Each pipeline drug is projected independently. A drug whose `expected_approval_date` falls on or after the end of the final horizon year is excluded from `per_drug_projections` and contributes nothing. Otherwise the eligible-patient pool is `enrollment_projection` multiplied by `prevalence_per_100k` and divided by one hundred thousand. For each forecast year, the treated fraction is zero when the approval date lands on or after that year's end; when approval falls inside the year, the fraction is `year1_uptake_pct` prorated by the number of days from the approval date to that year's end, divided by 365; and when approval precedes the year, the fraction is `steady_state_uptake_pct`. Each year's cost — the patient pool times `projected_annual_cost_cents` times that year's fraction — is rounded half-up to whole cents per year, and the drug's projection is the sum of those per-year rounded costs, recorded in `per_drug_projections` as a pairing of `pipeline_drug_id` with `projected_cents`. Under the `POLICY_ADJUSTED` variant, each included drug's summed projection is then multiplied by one minus its `biosimilar_erosion_pct`, rounded half-up once per drug, modeling biosimilar substitution savings — totals strictly lower than `BASELINE` whenever any included drug has positive erosion. Under `BASELINE`, no erosion is applied. The `pipeline_total_cents` sums the per-drug projections.

In-line spend is annualized alongside. The observation window is the trailing ninety days ending at — and excluding — the as-of date. The base sums `allowed_amount_cents` over claims in `PAID` or `ADJUSTED` with a `service_date` inside that window; pended, approved-but-unpaid, and denied claims never count. The `inline_annualized_cents` is that base scaled by 365 over 90, rounded half-up once at the end. Finally, `total_projected_cents` is `pipeline_total_cents` plus `inline_annualized_cents` multiplied by `horizon_years`. Completed runs are readable by all roles.

## 4. Endpoint Definitions

Operations that create a new resource — registering a drug, publishing a rate schedule, creating a policy version, registering a provider account, submitting an authorization or a claim, creating a biosimilar policy, registering a pipeline drug, or running a forecast — return `201 Created`. Operations that read or modify an existing resource, including all state-transition actions, return `200 OK`. Request payloads, responses, and side effects for each operation are as narrated in §2 and §3; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/drugs` | Register a specialty drug in the catalog | PlanAdmin |
| GET | `/api/drugs` | List drugs; filterable by `sourcing_rule` and `site_of_care_eligible` | All roles |
| GET | `/api/drugs/{drugId}` | Get one drug; canonical source of the OCC `version` | All roles |
| POST | `/api/asp-schedules` | Publish an ASP rate schedule; immediate activation runs retroactive repricing | PlanAdmin |
| GET | `/api/asp-schedules` | List ASP schedules; filterable by `drug_id` and `status` | All roles |
| GET | `/api/asp-schedules/{scheduleId}` | Get one ASP schedule | All roles |
| POST | `/api/clinical-policies` | Create a policy version; `status` `ACTIVE` supersedes the prior version; OCC on the drug | MedicalPolicyOfficer |
| GET | `/api/clinical-policies` | List clinical policies; filterable by `drug_id` and `status` | All roles |
| GET | `/api/clinical-policies/{policyId}` | Get one clinical policy | All roles |
| POST | `/api/clinical-policies/{policyId}/activate` | Activate a `DRAFT` policy, superseding the prior version; OCC on the drug | MedicalPolicyOfficer |
| POST | `/api/provider-accounts` | Register a provider organization | PlanAdmin |
| GET | `/api/provider-accounts` | List provider accounts; filterable by `status` | PlanAdmin, MedicalPolicyOfficer, CaseManager, PharmacyAnalyst |
| GET | `/api/provider-accounts/{accountId}` | Get one provider account; a ProviderRep may read only its own | All roles |
| POST | `/api/provider-accounts/{accountId}/settle-recoupment` | Zero the recoupment balance and return the account to `ACTIVE` | PlanAdmin |
| POST | `/api/prior-authorizations` | Submit a prior authorization request for a member | ProviderRep |
| GET | `/api/prior-authorizations` | List authorizations; filterable; ProviderRep auto-scoped | All roles |
| GET | `/api/prior-authorizations/{authId}` | Get one authorization; ProviderRep own-account only | All roles |
| POST | `/api/prior-authorizations/{authId}/approve` | Approve: dose optimization, validity window, policy pinning, optional redirection creation | MedicalPolicyOfficer |
| POST | `/api/prior-authorizations/{authId}/deny` | Deny a `SUBMITTED` authorization | MedicalPolicyOfficer |
| POST | `/api/prior-authorizations/{authId}/suspend` | Suspend an `APPROVED` authorization; pend its unpaid approved claims | MedicalPolicyOfficer |
| POST | `/api/prior-authorizations/{authId}/reinstate` | Reinstate a `SUSPENDED` authorization; restore its suspension-pended claims | MedicalPolicyOfficer |
| POST | `/api/prior-authorizations/{authId}/cancel` | Cancel a non-terminal authorization; withdraw any `OFFERED` redirection | MedicalPolicyOfficer |
| POST | `/api/claims` | Submit an infusion claim; synchronous adjudication per the full validation chain | ProviderRep |
| GET | `/api/claims` | List claims; filterable; ProviderRep auto-scoped | All roles |
| GET | `/api/claims/{claimId}` | Get one claim; ProviderRep own-account only | All roles |
| POST | `/api/claims/{claimId}/override-approve` | Medical override of a `PENDED` claim; records `override_by` and debits the authorization | MedicalPolicyOfficer |
| POST | `/api/claims/{claimId}/deny` | Deny a `PENDED` claim after medical review | MedicalPolicyOfficer |
| POST | `/api/claims/{claimId}/pay` | Pay an `APPROVED_FOR_PAYMENT` claim; credit the provider ledger | PlanAdmin |
| GET | `/api/claim-adjustments` | List repricing adjustments; filterable by `claim_id` and `asp_schedule_id` | All roles |
| GET | `/api/claim-adjustments/{adjustmentId}` | Get one adjustment | All roles |
| GET | `/api/redirections` | List redirections; filterable by `auth_id` and `status`; ProviderRep auto-scoped | All roles |
| GET | `/api/redirections/{redirectionId}` | Get one redirection | All roles |
| POST | `/api/redirections/{redirectionId}/accept` | Record member acceptance of a candidate site; compute the incentive estimate | CaseManager |
| POST | `/api/redirections/{redirectionId}/decline` | Record member decline of the offer | CaseManager |
| POST | `/api/biosimilar-policies` | Create a biosimilar substitution policy for a reference drug; starts `DRAFT` | PlanAdmin |
| GET | `/api/biosimilar-policies` | List biosimilar policies; filterable by `reference_drug_id`, `biosimilar_drug_id`, and `status` | All roles |
| GET | `/api/biosimilar-policies/{policyId}` | Get one biosimilar policy | All roles |
| POST | `/api/biosimilar-policies/{policyId}/activate` | Activate under the half-open overlap check; reprice in-flight biosimilar claims | PlanAdmin |
| POST | `/api/pipeline-drugs` | Register a pipeline drug for spend forecasting | PlanAdmin |
| GET | `/api/pipeline-drugs` | List pipeline drugs | All roles |
| GET | `/api/pipeline-drugs/{pipelineDrugId}` | Get one pipeline drug | All roles |
| POST | `/api/spend-forecasts` | Run a spend forecast (`BASELINE` or `POLICY_ADJUSTED`); stores an immutable snapshot | PharmacyAnalyst |
| GET | `/api/spend-forecasts/{forecastId}` | Get a stored forecast run | All roles |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock; applies all due time-driven transitions | PlanAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROVIDER_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_DRUG_VERSION` | 412 Precondition Failed |
| `ERR_JCODE_NOT_UNIQUE` | 409 Conflict |
| `ERR_INVALID_VIAL_UNIT_RATIO` | 422 Unprocessable Entity |
| `ERR_AUTH_NOT_PENDING` | 409 Conflict |
| `ERR_AUTH_NOT_APPROVED` | 409 Conflict |
| `ERR_AUTH_NOT_SUSPENDED` | 409 Conflict |
| `ERR_AUTH_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_NO_ACTIVE_POLICY` | 409 Conflict |
| `ERR_MISSING_WEIGHT_OR_DOSE` | 422 Unprocessable Entity |
| `ERR_START_DATE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_DIAGNOSIS_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_STEP_THERAPY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BIOSIMILAR_SUBSTITUTION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DOSE_EXCEEDS_MAX` | 422 Unprocessable Entity |
| `ERR_DRUG_AUTH_MISMATCH` | 422 Unprocessable Entity |
| `ERR_JCODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SERVICE_DATE_OUT_OF_WINDOW` | 422 Unprocessable Entity |
| `ERR_FUTURE_SERVICE_DATE` | 422 Unprocessable Entity |
| `ERR_AUTH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SOURCING_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SITE_OF_CARE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_JW_MODIFIER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_JW_WITHOUT_WASTE` | 422 Unprocessable Entity |
| `ERR_WASTE_NOT_PAYABLE_MULTIDOSE` | 422 Unprocessable Entity |
| `ERR_WASTE_EXCEEDS_VIAL` | 422 Unprocessable Entity |
| `ERR_NO_ASP_RATE` | 422 Unprocessable Entity |
| `ERR_DOSE_EXCEEDS_APPROVED` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_PENDED` | 409 Conflict |
| `ERR_CLAIM_NOT_PAYABLE` | 409 Conflict |
| `ERR_PROVIDER_RECOUPMENT_HOLD` | 409 Conflict |
| `ERR_PROVIDER_NOT_ON_HOLD` | 409 Conflict |
| `ERR_POLICY_NOT_DRAFT` | 409 Conflict |
| `ERR_BIOSIMILAR_POLICY_NOT_DRAFT` | 409 Conflict |
| `ERR_REFERENCE_SELF_BIOSIMILAR` | 422 Unprocessable Entity |
| `ERR_BIOSIMILAR_ALREADY_MAPPED` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REDIRECTION_NOT_OFFERED` | 409 Conflict |

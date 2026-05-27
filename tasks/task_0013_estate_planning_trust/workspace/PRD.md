# Estate Planning & Trust Administration API — Product Requirements Document

## 1. Introduction

Estate planning sits at the intersection of family law, fiduciary duty, and tax administration: a decedent's lifetime preparation must survive their death, withstand judicial scrutiny in probate, and survive contest from any party with standing — all while honoring beneficiary designations that may have been signed decades apart. This document specifies the back-office API that an estate-planning platform uses to drive that lifecycle end to end, from the first asset inventory the planner records on the kitchen table through the court-supervised distribution that finally discharges the executor.

The system covers eight tightly coupled domains in a single surface area: decedent registration, estate creation and finalization, asset inventory and appraisal, beneficiary designation (with primary/contingent chaining and basis-point accounting that must total to a whole estate), executor and trustee nomination, powers of attorney (both immediate and durable, financial and healthcare), end-of-life directives (living wills, DNRs, HIPAA authorizations), minor guardianship, creditor-claim adjudication under statutory priority, and probate-court order entry. The same record advances through clearly-named lifecycle states and the API must preserve the immediate consistency between them — when a death is registered, the cascading effects on powers of attorney, beneficiary-designated non-probate assets, and minor wards must all settle before the caller sees a response.

Two cross-cutting concerns shape every part of this specification. First, segregation of duties: a single human cannot simultaneously act as executor and as the attesting physician for that same estate's DNR, nor freely combine the executor and beneficiary roles without a court waiver. Second, version-pinned writes: in the contested phases of probate, multiple parties may legitimately attempt to mutate the same estate record from concurrent reads, and the API must reject any write whose underlying observation has been overtaken by another writer.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers identifying the caller: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying an `X-User-Role` value that is not one of the recognized roles below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is authenticated but whose role is not permitted for the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes seven roles, each with a distinct identity model:

- **`EstatePlanner`** is the attorney or paralegal who drafts the plan: registering decedents, creating estates, recording assets, nominating beneficiaries, executors, agents, guardians, and witnessing or notarizing directives. When `X-User-Role` is `EstatePlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may log it but does not compare it to any entity's `id`.
- **`Executor`** is the court-confirmed estate executor or trustee who runs probate administration. When `X-User-Role` is `Executor`, `X-User-ID` is the `id` of the acting `Executor` row; ownership checks on any resource that references an `Executor` (most notably an `Estate` whose `executor_user_id` field has been populated) compare the resource's pointer to `X-User-ID`.
- **`Judge`** is the court officer who enters and supersedes probate orders, resolves estate contests, and reviews guardianships. When `X-User-Role` is `Judge`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity (the server records it on `ProbateOrder.judge_user_id` when an order is created, but does not compare it to an entity `id`).
- **`Beneficiary`** is a named beneficiary on the estate who may read most resources and may initiate a probate contest. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `BeneficiaryDesignation`; ownership checks on resources that reference a `BeneficiaryDesignation` compare the foreign-key field to `X-User-ID`.
- **`Registrar`** is the vital-records registrar — the sole role permitted to register a death. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`Creditor`** is an external claimant filing a debt against the estate. When `X-User-Role` is `Creditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`PlatformAdmin`** operates test-driving and platform-level endpoints (most notably the system-clock pin used to make creditor windows and order-supersede windows deterministic). When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Two endpoints are exceptions to the authentication rule above: creating a `Decedent` profile and creating an `Estate` may proceed with `X-User-Role` set to `EstatePlanner` without the planner's identity being pre-registered — these are intentionally anonymous-create endpoints for the very first record a new file produces.

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

Every list endpoint accepts two query-string parameters: `limit` and `offset`. The `limit` parameter defaults to `10`, accepts a minimum value of `1`, and accepts a maximum value of `100`. The `offset` parameter defaults to `0` and represents the number of records to skip before the page begins. Each list response surfaces the four pagination fields — `limit`, `offset`, `total_count`, and `has_more` — inside `meta`, where `total_count` is the unfiltered count after any non-pagination query filters have been applied and `has_more` is true when `offset + limit < total_count`. Records are always returned in ascending order of `created_at` (the oldest record first); the API exposes no other sort key.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` field which is a UUID string (lowercase, hyphenated, with no resource-type prefix). The two timestamp fields `created_at` and `updated_at` are ISO 8601 UTC strings with three fractional digits; `created_at` is set once at resource creation and never changes thereafter, while `updated_at` is refreshed on every mutation. The `version` field is a non-negative integer that starts at `1` on creation and increments by exactly one on every successful mutation of the row. All eleven entity types in this system — `Decedent`, `Estate`, `Asset`, `BeneficiaryDesignation`, `Executor`, `PowerOfAttorney`, `EndOfLifeDirective`, `Guardianship`, `CreditorClaim`, and `ProbateOrder` — carry the full set of common fields (`id`, `created_at`, `updated_at`, and `version`).

### 2.5. Nested Resource Retrieval and Path Validation

Endpoints that embed an identifier in their path (for example `/estates/{id}` or `/beneficiary-designations/{id}/activate`) validate path parameters left to right. If any referenced resource — estate, asset, designation, executor, decedent, directive, guardianship, claim, or order — cannot be found, the response is `ERR_NOT_FOUND` (HTTP 404), returned before any role, state, or body validation runs.

### 2.6. Optimistic Concurrency Control on the Estate

Two endpoints in this API mutate or supersede prior decisions on a shared `Estate` record where two writers can each legitimately have something to do. Both endpoints are guarded by an optimistic-concurrency-control mechanism keyed on `Estate.version`.

The first is the action that revokes a beneficiary designation. A request that revokes a designation must include `expected_estate_version` as a non-optional input field, carrying the `version` value the client last observed on the parent `Estate`. If this value does not match the estate's current `version` at the moment the server processes the revocation, the request is rejected with `ERR_STALE_ESTATE_VERSION` (HTTP 412). This rule guards against the client missing a prior activation, revocation, or contest on the same estate that has re-shaped the residuary share map since the client read.

The second is the action that contests an estate from `PROBATE_OPEN` to `CONTESTED`. The contest request likewise must include `expected_estate_version`, and a mismatch with the parent estate's current `version` is rejected with `ERR_STALE_ESTATE_VERSION` (HTTP 412). This guarantees that even if two prospective contestants each read the same `PROBATE_OPEN` view, only the writer whose observation remains current will succeed — preventing the seventy-two-hour probate-order-supersede cascade from double-firing.

No other endpoint in this API accepts a version field. Endpoints whose mutations are not subject to a write-write contention pattern (for example, accepting an executor nomination, witnessing a directive, or filing a creditor claim) do not require `expected_estate_version` and silently ignore it if sent.

### 2.7. Monetary and Share Precision

All monetary amounts in this domain are integer cents — there is no floating-point currency, no internal rounding, and no fractional dollars. Sums of `appraised_value_cents`, `amount_cents`, and `paid_amount_cents` are computed in integer arithmetic. Beneficiary shares are expressed in `share_basis_points` where one basis point equals 0.01% and the full estate is exactly `10000` basis points; the intestacy allocator distributes any remainder of pool-divided-by-headcount one basis point at a time, in `created_at` ascending order, so that any per-class pool always sums exactly to its allotted basis points and the total always sums to `10000`. The net taxable estate calculation is floored at zero by taking the maximum of zero and the would-be negative result, so an estate whose allowed claims exceed its gross can never present a negative `net_taxable_estate_cents`.

### 2.8. Cascading Mutations and Audit Integrity

Several state transitions in this system propagate to multiple sibling and child entities in a single logical operation. When a transition's narrative names a cascade — for example, recording a death also terminating non-durable powers of attorney and excluding beneficiary-designated retirement and insurance assets — every affected row must be updated atomically: the row's status moves to the cascade target, its `updated_at` refreshes to the same instant, and its `version` increments by one. The triggering estate's `version` likewise increments by one for the overall logical operation; a cascade does not multiply the parent estate's version by the number of children touched.

The frozen `inventory_snapshot_gross_cents` field on `Estate` is a deliberate exception to the general rule that derived values track live inputs. Once the inventory-approval order from the court enters and the estate advances into administration, the snapshot is set to the then-current `gross_estate_value_cents` and never recomputed thereafter, even if assets are subsequently re-appraised. This freeze is what gives the final variant of the net-taxable-estate calculation its stability across the remainder of probate.

### 2.9. Validation Ordering on Every Request

Validations on every request are evaluated in a fixed priority order so that the first failure is always reported the same way:

1. Authentication — presence of `X-User-ID` and `X-User-Role` and known role value (`ERR_UNAUTHENTICATED`, HTTP 401).
2. Existence — all referenced resources in the URL path are present, validated left to right (`ERR_NOT_FOUND`, HTTP 404).
3. Authorization — the authenticated role is permitted for this operation (`ERR_UNAUTHORIZED`, HTTP 403).
4. State — the target resource's current `status` permits the requested transition (`ERR_INVALID_STATE`, HTTP 409).
5. Segregation of duties on directive activation — the attesting physician is not also the estate's executor (`ERR_SEGREGATION_OF_DUTIES_VIOLATED`, HTTP 422).
6. Executor–beneficiary conflict on probate opening — if the executor is also a beneficiary, the court has explicitly waived (`ERR_EXECUTOR_BENEFICIARY_CONFLICT`, HTTP 422).
7. Contingent parent referential integrity (`ERR_CONTINGENT_PARENT_INVALID`, HTTP 422).
8. Creditor-window timeliness (`ERR_CREDITOR_WINDOW_CLOSED`, HTTP 422).
9. Share over-allocation on individual activation (`ERR_SHARE_OVERALLOCATION`, HTTP 422).
10. Share full-allocation on estate finalization (`ERR_SHARE_NOT_FULLY_ALLOCATED`, HTTP 422).
11. Ward age eligibility (`ERR_WARD_OVER_AGE`, HTTP 422).
12. Estate-fund sufficiency for creditor payment (`ERR_INSUFFICIENT_ESTATE_FUNDS`, HTTP 422).
13. Duplicate executor active (`ERR_DUPLICATE_EXECUTOR_ACTIVE`, HTTP 422).
14. Optimistic-concurrency match (`ERR_STALE_ESTATE_VERSION`, HTTP 412).
15. HIPAA recipients present (`ERR_HIPAA_RECIPIENTS_REQUIRED`, HTTP 422).
16. Power-of-attorney interval non-overlap (`ERR_POA_INTERVAL_OVERLAP`, HTTP 422).
17. Ward point-uniqueness on guardianship creation (`ERR_DUPLICATE_WARD`, HTTP 422).

Syntactic problems — a missing required body field, a type mismatch, an enum value outside the declared set, a `share_basis_points` value at or below zero, an `amount_cents` not strictly positive, or any other constraint failure at the body-parse layer — surface as `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Drafting the Plan: Decedent, Estate, and Inventory

A new file begins with the planner registering a `Decedent` record. The minimum profile carries the decedent's `full_legal_name`, their `date_of_birth` as an ISO 8601 UTC instant interpreted as a calendar date at midnight, their `domicile_state_code` (a two-letter uppercase code drawn from `CA`, `NY`, `TX`, `FL`, or `IL` — the five jurisdictions whose intestacy tables this API encodes), and their `ssn_last4` (exactly four digits, used for matching against external asset records). The `date_of_death` field exists on `Decedent` but begins null and is set only when death is registered.

Once a decedent exists, the planner opens an `Estate` for that decedent by submitting `decedent_id`. The new estate begins in `DRAFT` with its `status` so set, its `gross_estate_value_cents` at `0`, its `net_taxable_estate_cents` at `0`, its `inventory_snapshot_gross_cents` null, its `executor_user_id` null, and the three lifecycle timestamps (`probate_filed_at`, `probate_opened_at`, `closed_at`) all null. The estate's `version` starts at `1`.

In `DRAFT`, the planner builds inventory by attaching `Asset` rows. Each asset records the parent `estate_id`, a `category` drawn from `REAL_ESTATE`, `BROKERAGE`, `BANK_ACCOUNT`, `RETIREMENT_IRA`, `LIFE_INSURANCE`, `PERSONAL_PROPERTY`, or `BUSINESS_INTEREST`, a free-text `description`, and an `appraised_value_cents` that must be a non-negative integer. The asset's `status` begins at `DRAFT`. The planner may also attach a `beneficiary_designation_id` at create time, which has no effect during the plan-drafting phase but becomes determinative on death — see the inheritance cascade in §3.3.

Beneficiary designations are likewise added in `DRAFT`. Each `BeneficiaryDesignation` carries the parent `estate_id`, the `beneficiary_full_name`, a `relationship` chosen from `SPOUSE`, `CHILD`, `GRANDCHILD`, `PARENT`, `SIBLING`, `CHARITY`, or `OTHER`, and a `share_basis_points` value strictly between zero and ten thousand inclusive of ten thousand. A designation may optionally point at another designation through `contingent_of_designation_id`: a non-null value marks the row as contingent on the named primary and is only promoted to active when the primary is revoked. On creation or manual activation, if `contingent_of_designation_id` is set, the referenced parent must belong to the same estate and must currently be in `ACTIVE` status — failure is `ERR_CONTINGENT_PARENT_INVALID`.

Finalizing the plan promotes the estate from `DRAFT` to `ALIVE`. The planner triggers this transition once the inventory and designations are complete; for it to succeed, the estate must own at least one asset whose `status` is in `DRAFT` or `INCLUDED`, the sum of `share_basis_points` across all designations being promoted to `ACTIVE` must equal exactly `10000` (not merely at most `10000` — partial allocation is rejected with `ERR_SHARE_NOT_FULLY_ALLOCATED`), and the decedent's `date_of_death` must still be null. On success, every asset on the estate whose `status` is `DRAFT` advances to `INCLUDED`; every designation in `DRAFT` advances to `ACTIVE` (subject still to the cumulative share check below); the gross-estate value is recomputed as the sum of `appraised_value_cents` across every asset whose `status` is `INCLUDED`, iterated by `created_at` ascending for stability; the estate's `updated_at` refreshes; and `Estate.version` increments by one.

A designation may also be activated individually outside the finalize cascade. On any activation — whether manual or as part of the finalize cascade — the new sum of `share_basis_points` across all designations on the estate that are or would be `ACTIVE` must not exceed `10000`; an overrun is `ERR_SHARE_OVERALLOCATION`. Manual activation is permitted whenever the estate's `status` is anything other than `CLOSED`. The activation transition is `DRAFT → ACTIVE`.

An `ACTIVE` designation can be revoked by the planner, moving it `ACTIVE → REVOKED`. Revocation is permitted only while the parent estate's `status` is `ALIVE` or `DECEASED`; it is the OCC-guarded action described in §2.6, so the request must carry `expected_estate_version` and a stale value is rejected with `ERR_STALE_ESTATE_VERSION`. On a successful revocation, every designation on the same estate whose `contingent_of_designation_id` points at the just-revoked row and whose current `status` is `DRAFT` is automatically promoted to `ACTIVE`, so the contingent backup takes effect immediately; each promoted child's `updated_at` refreshes and its `version` increments, and the parent estate's `version` likewise increments by one for the overall operation. Once `REVOKED`, the row is retained for audit and is not counted toward the share total.

### 3.2. The Executor Nomination Dance

While the plan is still in `DRAFT` or `ALIVE` (or after the decedent's death but before probate is filed), the planner nominates one or more `Executor` rows. Each carries the parent `estate_id`, the executor's `full_legal_name`, a `role_type` of either `EXECUTOR` (for probate-driven estates) or `TRUSTEE` (for revocable-trust pour-over flows), and a boolean `is_also_beneficiary` flag noting whether this executor is also named as a beneficiary on the same estate. The nomination begins in `NOMINATED`.

The named candidate accepts or declines. Acceptance moves `NOMINATED → ACCEPTED` and writes the accepting executor's `id` into the parent `Estate.executor_user_id`; the estate's `version` increments by one. Acceptance fails with `ERR_DUPLICATE_EXECUTOR_ACTIVE` if any other executor on the same estate with `role_type = EXECUTOR` is already in `ACCEPTED` or `COURT_CONFIRMED` status — only one executor at a time can be live. Declining moves `NOMINATED → DECLINED` and, if that declining executor's `id` happened to be sitting in `Estate.executor_user_id`, that pointer is cleared back to null; declining is permitted unless the estate is already `CLOSED`.

Court confirmation is not a direct API call: it is a cascade fired by the open-probate court order described in §3.5. When that order enters and the estate advances from `PROBATE_PENDING` to `PROBATE_OPEN`, the single executor whose `role_type` is `EXECUTOR` and whose `status` is `ACCEPTED` is advanced to `COURT_CONFIRMED`. The cascade also enforces the segregation rule: if `is_also_beneficiary` is true on that executor, the court must have separately entered a confirm-executor order; otherwise the open-probate entry itself is rejected with `ERR_EXECUTOR_BENEFICIARY_CONFLICT` and no cascade fires.

A `COURT_CONFIRMED` executor can be displaced in only two ways. If the court later supersedes the confirm-executor order, the executor moves `COURT_CONFIRMED → REMOVED` and `Estate.executor_user_id` is cleared. Otherwise, on the eventual closing of the estate, the executor is discharged: `COURT_CONFIRMED → DISCHARGED`.

### 3.3. Death and the Inheritance Cascade

When the decedent dies, the `Registrar` records `date_of_death` on the `Decedent` row. The registrar's call sets the date and immediately drives a multi-entity cascade. The estate, which must currently be in `ALIVE` for the cascade to be permitted, transitions to `DECEASED`. Every `PowerOfAttorney` on this decedent whose `scope` is `FINANCIAL` or `HEALTHCARE` (the two non-durable variants) and whose current `status` is `ACTIVE` is terminated — moved to the `TERMINATED` state — because non-durable powers do not survive incapacity or death. The two durable variants — `DURABLE_FINANCIAL` and `DURABLE_HEALTHCARE` — explicitly survive and are not touched by this cascade.

The same registration cascade reconfigures the inventory. Every `Asset` on the estate whose `beneficiary_designation_id` is non-null and whose `category` is `RETIREMENT_IRA` or `LIFE_INSURANCE` — the two non-probate-eligible categories that bypass probate by riding their own beneficiary nomination — auto-transitions from `INCLUDED` to `EXCLUDED`. Once the exclusion cascade completes, `gross_estate_value_cents` is recomputed; the dropped assets no longer contribute, and the recomputed total flows forward into the provisional net-taxable variant. The estate's `updated_at` refreshes and its `version` increments by one for the entire logical operation.

Guardianships themselves are created by the planner while the plan is still being drafted. Each `Guardianship` row carries the parent `estate_id`, the ward's `ward_full_name` and `ward_date_of_birth`, and the proposed `guardian_full_name`. The row begins in `PROPOSED`. Within a single estate, two guardianship rows may not share the same `ward_full_name` regardless of their respective statuses — even a `DISSOLVED` row still consumes that name slot as a point-uniqueness audit-trail block; a duplicate is rejected with `ERR_DUPLICATE_WARD`.

The third arm of the registration cascade reaches guardianships. Any `Guardianship` row on the estate whose ward is implied to be under eighteen as of the date of death is promoted from `PROPOSED` to `COURT_REVIEW`. Age is computed by the strict-inequality rule encoded in the guardian eligibility calculation: a ward is eligible if and only if their `ward_date_of_birth` plus eighteen years (interpreted in UTC calendar arithmetic) falls strictly later than the decedent's `date_of_death`. A ward whose eighteenth birthday lands on the exact date of death is ineligible; in that case the review yields `ERR_WARD_OVER_AGE`. On any subsequent guardianship review the same boundary applies — the judge's decision parameter is `decision`, and the row settles into `COURT_CONFIRMED` if the decision was `CONFIRM` and the ward is eligible, otherwise into `COURT_DENIED`. A ward who turns eighteen after court confirmation auto-transitions the guardianship to `DISSOLVED`.

### 3.4. Powers of Attorney and End-of-Life Directives

Powers of attorney live on the decedent rather than the estate. Each `PowerOfAttorney` row carries `decedent_id`, an `agent_full_name`, and a `scope` drawn from `FINANCIAL`, `HEALTHCARE`, `DURABLE_FINANCIAL`, or `DURABLE_HEALTHCARE`. A new POA begins in `DRAFT`. Activation transitions the row to `ACTIVE` and requires the planner to supply `effective_at` (the start of the effective interval) and optionally `effective_until` (the exclusive upper bound; null means open-ended). The interval semantics are half-open: an interval that ends at instant `T` does not collide with another interval that starts at `T`. On activation, the new interval `[effective_at, effective_until)` must not overlap any existing `ACTIVE` POA on the same `decedent_id` whose `scope` is identical; an overlap is rejected with `ERR_POA_INTERVAL_OVERLAP`. The grantor may explicitly revoke an `ACTIVE` POA at any time, moving it to `REVOKED`. As noted in §3.3, non-durable scopes (`FINANCIAL` and `HEALTHCARE`) automatically transition to `TERMINATED` when their grantor's death is registered.

End-of-life directives — the medical-side analogue to POAs — live on the decedent as well. Each `EndOfLifeDirective` row carries `decedent_id` and a `directive_type` of either `LIVING_WILL`, `DNR`, `HEALTHCARE_POA`, or `HIPAA_AUTHORIZATION`. A directive begins in `DRAFT` and is taken through a formal witnessing chain. The first step is witnessing the directive, advancing `DRAFT → WITNESSED`; this step is allowed only while the decedent's `date_of_death` is still null, since a postmortem witnessing is meaningless. Three of the four directive types must additionally be notarized: notarization advances `WITNESSED → NOTARIZED` and is required for `DNR`, `LIVING_WILL`, and `HEALTHCARE_POA`. The fourth type, `HIPAA_AUTHORIZATION`, may activate directly from `WITNESSED` without notarization.

Activation is the moment at which the directive begins to bind providers. The activate action moves the directive to `ACTIVE` from either `WITNESSED` (for a `HIPAA_AUTHORIZATION`) or `NOTARIZED` (for any of the other three types). For a `DNR` specifically, activation additionally requires that `physician_attester_user_id` be non-null — a DNR is not enforceable without a physician's signature. For a `LIVING_WILL`, the row must have been notarized; activation from `WITNESSED` alone is not permitted. Whenever `physician_attester_user_id` is set on any directive being activated, it must not equal the parent estate's `executor_user_id`; this segregation prevents the same person from acting as both the estate's executor and the attesting physician for that estate's medical directives, and is reported as `ERR_SEGREGATION_OF_DUTIES_VIOLATED`. Finally, for a `HIPAA_AUTHORIZATION`, the `hipaa_authorized_recipients` array must be non-empty at the time of activation — an authorization that names no one to release PHI to is rejected with `ERR_HIPAA_RECIPIENTS_REQUIRED`. Revocation moves an `ACTIVE` directive to `REVOKED` and is permitted only while the decedent's `date_of_death` remains null.

### 3.5. Filing for Probate, Opening the Court Process, and Probate Orders

Once the estate is in `DECEASED` and an executor is in `ACCEPTED` (with `Estate.executor_user_id` pointing at that executor's `id`), the executor files for probate. This filing advances the estate from `DECEASED` to `PROBATE_PENDING`, stamps `probate_filed_at` with the current server time, and increments `Estate.version` by one.

Court orders enter the picture immediately. A `ProbateOrder` row carries the parent `estate_id`, an `order_type` drawn from `OPEN_PROBATE`, `CONFIRM_EXECUTOR`, `APPROVE_INVENTORY`, `SETTLE_CREDITORS`, `FINAL_DISTRIBUTION`, or `CLOSE_ESTATE`, a `judge_user_id` recording the signing judge, and a `status` that begins at `DRAFT` (clerk-prepared). The order's `entered_at` is null until the judge enters it. Entering an order — moving it from `DRAFT` to `ENTERED` — stamps `entered_at` with the current server time and, depending on `order_type`, drives a state change on the parent estate.

Entering an `OPEN_PROBATE` order advances the estate from `PROBATE_PENDING` to `PROBATE_OPEN`, stamps `Estate.probate_opened_at` with the order's `entered_at`, and cascades the unique `ACCEPTED` executor up to `COURT_CONFIRMED`. The entry itself enforces the executor-beneficiary safety rule: if the confirmed executor's `is_also_beneficiary` flag is true, then a separate `CONFIRM_EXECUTOR` order must already be `ENTERED` on the same estate (the court waiver); absent that companion order, the open-probate entry is rejected with `ERR_EXECUTOR_BENEFICIARY_CONFLICT`. Entering an `APPROVE_INVENTORY` order advances the estate from `PROBATE_OPEN` to `ADMINISTRATION`, but only if every asset on the estate has a non-`DRAFT` status (no draft asset may slip through into administration) and the gross estate value is strictly positive; on this transition, `inventory_snapshot_gross_cents` is frozen to the current `gross_estate_value_cents` and the one-hundred-twenty-day creditor window begins ticking against `probate_opened_at`. Entering a `FINAL_DISTRIBUTION` order requires that every `CreditorClaim` whose `status` is `ALLOWED` has already advanced to `PAID`; this is the court's signal that the residuary may be distributed. Entering a `CLOSE_ESTATE` order requires a preceding `FINAL_DISTRIBUTION` order in `ENTERED` status on the same estate, and it advances the estate from `ADMINISTRATION` to `CLOSED`, stamps `Estate.closed_at` with the current server time, and discharges the `COURT_CONFIRMED` executor. Every order entry increments `Estate.version` by one.

The judge may also supersede an order that has already entered, either implicitly via the contest cascade described in §3.7 or explicitly through an admin action that records a `reason`. An explicit supersession of a `CONFIRM_EXECUTOR` order cascades to demote that estate's `COURT_CONFIRMED` executor to `REMOVED` and clears `Estate.executor_user_id`.

### 3.6. Creditor Claims and the Payment Waterfall

Once the estate is in `PROBATE_OPEN` and especially once it has reached `ADMINISTRATION`, creditors and the executor file claims. A `CreditorClaim` carries the parent `estate_id`, a `creditor_name`, an `amount_cents` (strictly positive), a `claim_class` drawn from `SECURED`, `ADMIN`, `FUNERAL`, `TAX`, or `UNSECURED`, and a `filed_at` timestamp. On creation, if the parent estate's `probate_opened_at` is already set, the claim's `filed_at` must fall no later than one hundred twenty days after `probate_opened_at`; a claim filed exactly at the one-hundred-twenty-day mark is still accepted, but a claim filed even one second beyond that point is rejected with `ERR_CREDITOR_WINDOW_CLOSED`. The claim begins in `FILED`.

The executor adjudicates each claim. Adjudication can move `FILED → ALLOWED` or `FILED → DISALLOWED`. Allowance is permitted only while the estate is in `ADMINISTRATION` and the same one-hundred-twenty-day window is still open at the moment of allowance; the side effect of allowance is to recompute `net_taxable_estate_cents` (allowed claims reduce the net taxable base). Disallowance is also restricted to `ADMINISTRATION` and has no value side effect.

Paying a claim moves it from `ALLOWED` to `PAID`. The payment endpoint applies the waterfall algorithm to determine the dollar amount actually paid against the target claim. The waterfall begins by computing the total already paid against this estate's claims — the sum of `paid_amount_cents` over every claim on this estate whose `status` is `PAID`. It then computes the remaining estate funds as `Estate.gross_estate_value_cents` minus that already-paid total. With that pool of remaining cents in hand, it walks the classes in the fixed statutory priority order — `SECURED` first, then `ADMIN`, then `FUNERAL`, then `TAX`, and `UNSECURED` last — and within each class iterates the allowed claims in ascending `created_at` order with `amount_cents` ascending as the tiebreaker. For every allowed claim earlier in the walk than the target, the walk simulates consumption: it subtracts the smaller of the remaining pool and that claim's `amount_cents` from the pool, but the simulated claim's `paid_amount_cents` is not actually updated and its status is not actually changed. When the walk reaches the target claim, the remaining pool is either zero or positive. If the pool is zero or negative at that point — meaning every earlier-priority allowed claim has notionally consumed the full estate — the payment is rejected with `ERR_INSUFFICIENT_ESTATE_FUNDS`; the target's `paid_amount_cents` stays at zero and its `status` stays `ALLOWED`. Otherwise the target's `paid_amount_cents` is set to the smaller of its own `amount_cents` and the remaining pool, and its `status` advances to `PAID`. Only the target claim is materially updated by a single pay invocation; earlier-priority claims that have not yet been paid remain in `ALLOWED` and will be settled through their own pay invocations. The `net_taxable_estate_cents` is recomputed once the pay completes. The estate's `gross_estate_value_cents` is not changed by the payment itself — it tracks asset value, not cash flow.

Two variants of this waterfall exist and they produce different per-claim amounts on the same inputs whenever a class is short-funded. The default behavior described above is the interim variant: while the estate is in `ADMINISTRATION` and no `CLOSE_ESTATE` order has yet been drafted, claims are paid in the order described — the marginal claim within an under-funded class gets whatever residual remains and later siblings within the same class get zero. The other variant is the final-distribution variant: while the estate is in `ADMINISTRATION` and at least one `CLOSE_ESTATE` order is in `DRAFT`, an under-funded class is paid pro-rata across all of its allowed members. In that case each member of the short-funded class receives the integer floor of its own `amount_cents` multiplied by the remaining pool divided by the sum of `amount_cents` across all allowed members of that class, and any residual cents left over after these floor divisions (i.e., the difference between the remaining pool and the sum of the floored shares) are allocated one cent at a time in `created_at` ascending order, so that the class's allocated total still equals the remaining pool exactly. The triggering condition between the two variants is solely the presence of a `DRAFT` `CLOSE_ESTATE` order on the estate at the moment of payment.

### 3.7. Contesting and Resolving the Estate

A `Beneficiary` may at any time while the estate is in `PROBATE_OPEN` initiate a contest. The contest action moves the estate from `PROBATE_OPEN` to `CONTESTED`. Because two prospective contestants could each legitimately have observed `PROBATE_OPEN` and prepared to act on it, the contest request must carry `expected_estate_version` matching the current `Estate.version`; a mismatch is rejected with `ERR_STALE_ESTATE_VERSION`. The contest request also carries a free-text `reason` explaining the grounds for the contest.

On a successful contest, every `ProbateOrder` whose `status` is currently `ENTERED` and whose `entered_at` is within the last seventy-two hours is auto-superseded — its `status` moves to `SUPERSEDED` — so that any inventory approval or distribution order entered in the immediate run-up to the contest is unwound. Older orders, outside the seventy-two-hour window, remain in force. The estate's `version` increments by one for the contest as a whole, regardless of how many orders were superseded.

A judge resolves the contest by submitting a `resolution_note` and moves the estate from `CONTESTED` back to `PROBATE_OPEN`. The resolution itself does not re-enter previously superseded orders; the clerk would have to re-draft and the judge re-enter them. `Estate.version` increments by one on resolution.

Independent of contest, the system supports an intestacy calculation that allocates basis-point shares to whatever surviving relatives have been recorded as designations. This calculation is invoked on demand by either a planner or a judge through the intestacy-shares capability, and it is also implicitly part of the precondition machinery behind a final-distribution order when the active beneficiary share map does not sum to ten thousand basis points. The calculation begins with the decedent's `domicile_state_code` and looks up the per-state share table. For `CA`, `NY`, `FL`, and `IL`, a surviving spouse receives `5000` basis points and the children's pool receives `5000` basis points. For `TX`, a separate-property children-favored regime, the surviving spouse receives `3333` basis points and the children's pool receives `6667` basis points. The relationship classes are walked in priority order — `SPOUSE` first, then `CHILD`, then `PARENT`, then `SIBLING`, then `CHARITY` — and a class is skipped if it contains no designations on the estate (whether `DRAFT` or `ACTIVE`). The spouse class's pool is the state's spouse share; the child class's pool is the state's child share; the remaining classes share whatever basis points are still unassigned, in order. Within a class, the pool is divided evenly across the class's members: each member receives `floor(pool / count)` basis points and any remainder of `pool % count` is allocated one basis point at a time to members in `created_at` ascending order. The result is a map from designation `id` to assigned basis points, plus the total assigned (always exactly `10000`).

### 3.8. Final Distribution and Closure

When all `ALLOWED` claims have advanced to `PAID`, the court may enter the `FINAL_DISTRIBUTION` order. This is the gate that authorizes the executor to distribute the residuary to beneficiaries according to the active share map (or, where the active map is incomplete, according to the intestacy allocation from §3.7). Following the entered final-distribution order, the court enters a `CLOSE_ESTATE` order whose entry requires three preconditions: every `ALLOWED` claim has also advanced to `PAID`, a `FINAL_DISTRIBUTION` order in `ENTERED` status already exists for the estate, and the net-taxable-estate calculation has run at least once on this estate. On entry, the estate advances from `ADMINISTRATION` to `CLOSED`, `Estate.closed_at` is stamped with the current server time, and the `COURT_CONFIRMED` executor is automatically discharged to `DISCHARGED`. `Estate.version` increments by one. A `CLOSED` estate is terminal — no further mutations are accepted on it.

### 3.9. The Two-Variant Net Taxable Estate

The system maintains a single field — `net_taxable_estate_cents` — but its value is produced by two distinct variants of the same underlying calculation, and the variant in use depends entirely on the estate's current `status`. While the estate is in `DECEASED`, `PROBATE_PENDING`, or `PROBATE_OPEN`, the provisional variant is in effect: the calculation uses the live `gross_estate_value_cents`, so any subsequent update to an `INCLUDED` asset's `appraised_value_cents` flows immediately into the provisional net taxable estate. Once the inventory-approval order from the court enters and the estate advances into `ADMINISTRATION` (and from then on into `CLOSED`), the final variant takes over: the calculation now uses the frozen `inventory_snapshot_gross_cents` instead of the live gross, so any subsequent asset re-appraisal does not re-enter the net-taxable computation. Both variants subtract the same two terms from their chosen gross figure: an exempt total formed by summing `appraised_value_cents` across every asset on the estate whose `status` is `INCLUDED` and whose `category` is `RETIREMENT_IRA` (note that retirement assets with a named beneficiary have already been excluded by the death cascade, so only retirement-IRA assets without a beneficiary designation remain in the exempt sum), and a claims total formed by summing `amount_cents` across every claim on the estate whose `status` is `ALLOWED` (whether or not yet paid — paid claims were allowed first and continue to count; disallowed claims do not count). The result is floored at zero by taking the maximum of zero and the subtraction. The same estate with the same assets and claims can therefore present two strictly different `net_taxable_estate_cents` values depending solely on whether its `status` is `PROBATE_OPEN` (provisional) or `ADMINISTRATION` (final).

The net-taxable summary is exposed as a read-only computation that returns `gross_estate_value_cents`, `exempt_cents`, `allowed_claims_total_cents`, `net_taxable_estate_cents`, and the active `variant` name. It runs the calculation in whichever variant matches the estate's current `status`.

The intestacy-shares capability likewise returns its own envelope shape: a `shares` object mapping designation identifiers to assigned basis points, plus a `total_bp_assigned` integer that always equals `10000`.

### 3.10. Deterministic Time

Two windows in this domain — the seventy-two-hour probate-order-supersede window on a contest, and the one-hundred-twenty-day creditor window measured from `probate_opened_at` — are sensitive to wall-clock time. To make the API testable under deterministic conditions, the system exposes a platform-admin-only test-driving capability that pins the logical clock to a supplied `to_iso8601` instant. Subsequent reads of "now" — for stamping `entered_at`, `closed_at`, `probate_filed_at`, and for evaluating the two time-bounded windows above — return the pinned instant rather than the host's wall clock. This capability is available only in benchmark mode and returns `{ now: <iso8601> }` in its envelope.

## 4. Endpoint Definitions

The endpoints below produce HTTP 201 when they create a new resource and HTTP 200 for every other successful mutation or read. Where path parameters are present, they are validated left to right before any body or role check. Body parameters, side effects, and the shape of the returned resource are described in §3; the table is intentionally compact and is not a substitute for the workflow narrative.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/decedents` | Register a decedent profile (alive at creation). | `EstatePlanner` |
| GET | `/decedents/{id}` | Fetch a decedent. | `EstatePlanner`, `Executor`, `Judge`, `Beneficiary`, `Registrar` |
| POST | `/decedents/{id}/register-death` | Record date of death; drives Estate, POA, asset, and guardianship cascade. | `Registrar` |
| POST | `/estates` | Create an estate for a decedent (starts in DRAFT). | `EstatePlanner` |
| GET | `/estates/{id}` | Fetch an estate. | `EstatePlanner`, `Executor`, `Judge`, `Beneficiary` |
| GET | `/estates` | List estates with optional filter. | `EstatePlanner`, `Judge` |
| POST | `/estates/{id}/finalize-plan` | Promote DRAFT estate to ALIVE; cascade DRAFT assets and designations. | `EstatePlanner` |
| POST | `/estates/{id}/file-for-probate` | Transition DECEASED to PROBATE_PENDING. | `Executor` |
| POST | `/estates/{id}/contest` | Transition PROBATE_OPEN to CONTESTED; supersede recent ProbateOrders. | `Beneficiary` |
| POST | `/estates/{id}/resolve-contest` | Transition CONTESTED back to PROBATE_OPEN. | `Judge` |
| POST | `/estates/{id}/compute-intestacy-shares` | Run the intestacy share allocation. | `Judge`, `EstatePlanner` |
| GET | `/estates/{id}/net-taxable-summary` | Returns net taxable estate using the current variant. | `EstatePlanner`, `Executor`, `Judge` |
| POST | `/assets` | Add an asset to an estate (starts DRAFT). | `EstatePlanner` |
| PATCH | `/assets/{id}` | Update an asset's appraised value (re-runs gross if INCLUDED). | `EstatePlanner`, `Executor` |
| GET | `/assets/{id}` | Fetch an asset. | `EstatePlanner`, `Executor`, `Judge` |
| GET | `/assets` | List assets; filter by estate or by designation. | `EstatePlanner`, `Executor`, `Judge` |
| POST | `/assets/{id}/liquidate` | Sell an asset (INCLUDED to LIQUIDATED); recomputes gross. | `Executor` |
| POST | `/beneficiary-designations` | Create a beneficiary designation (starts DRAFT). | `EstatePlanner` |
| GET | `/beneficiary-designations/{id}` | Fetch a designation. | `EstatePlanner`, `Executor`, `Judge`, `Beneficiary` |
| GET | `/beneficiary-designations` | List designations; filter by estate. | `EstatePlanner`, `Executor`, `Judge` |
| POST | `/beneficiary-designations/{id}/activate` | DRAFT to ACTIVE (subject to share-sum constraints). | `EstatePlanner` |
| POST | `/beneficiary-designations/{id}/revoke` | ACTIVE to REVOKED; cascade contingent children. OCC-guarded. | `EstatePlanner` |
| POST | `/executors` | Nominate an executor or trustee. | `EstatePlanner` |
| GET | `/executors/{id}` | Fetch an executor. | `EstatePlanner`, `Executor`, `Judge` |
| GET | `/executors` | List executors; filter by estate. | `EstatePlanner`, `Executor`, `Judge` |
| POST | `/executors/{id}/accept` | NOMINATED to ACCEPTED. | `Executor` |
| POST | `/executors/{id}/decline` | NOMINATED to DECLINED. | `Executor` |
| POST | `/powers-of-attorney` | Create a POA in DRAFT. | `EstatePlanner` |
| GET | `/powers-of-attorney/{id}` | Fetch a POA. | `EstatePlanner`, `Executor` |
| GET | `/powers-of-attorney` | List POAs; filter by decedent. | `EstatePlanner`, `Executor` |
| POST | `/powers-of-attorney/{id}/activate` | DRAFT to ACTIVE; enforce interval non-overlap. | `EstatePlanner` |
| POST | `/powers-of-attorney/{id}/revoke` | ACTIVE to REVOKED. | `EstatePlanner` |
| POST | `/directives` | Create a directive in DRAFT. | `EstatePlanner` |
| GET | `/directives/{id}` | Fetch a directive. | `EstatePlanner`, `Executor` |
| GET | `/directives` | List directives; filter by decedent. | `EstatePlanner`, `Executor` |
| POST | `/directives/{id}/witness` | DRAFT to WITNESSED. | `EstatePlanner` |
| POST | `/directives/{id}/notarize` | WITNESSED to NOTARIZED. | `EstatePlanner` |
| POST | `/directives/{id}/activate` | WITNESSED or NOTARIZED to ACTIVE. | `EstatePlanner` |
| POST | `/directives/{id}/revoke` | ACTIVE to REVOKED. | `EstatePlanner` |
| POST | `/guardianships` | Propose a guardian for a minor named in the plan. | `EstatePlanner` |
| GET | `/guardianships/{id}` | Fetch a guardianship. | `EstatePlanner`, `Executor`, `Judge` |
| GET | `/guardianships` | List guardianships; filter by estate. | `EstatePlanner`, `Executor`, `Judge` |
| POST | `/guardianships/{id}/review` | Judge advances COURT_REVIEW to confirmed or denied. | `Judge` |
| POST | `/creditor-claims` | File a creditor claim. | `Creditor`, `Executor` |
| GET | `/creditor-claims/{id}` | Fetch a creditor claim. | `EstatePlanner`, `Executor`, `Judge`, `Creditor` |
| GET | `/creditor-claims` | List creditor claims; filter by estate. | `EstatePlanner`, `Executor`, `Judge` |
| POST | `/creditor-claims/{id}/allow` | FILED to ALLOWED. | `Executor` |
| POST | `/creditor-claims/{id}/disallow` | FILED to DISALLOWED. | `Executor` |
| POST | `/creditor-claims/{id}/pay` | ALLOWED to PAID; runs the waterfall to confirm coverage. | `Executor` |
| POST | `/probate-orders` | Clerk drafts a probate order. | `Judge` |
| GET | `/probate-orders/{id}` | Fetch a probate order. | `EstatePlanner`, `Executor`, `Judge`, `Beneficiary` |
| GET | `/probate-orders` | List probate orders; filter by estate. | `EstatePlanner`, `Executor`, `Judge`, `Beneficiary` |
| POST | `/probate-orders/{id}/enter` | Judge signs order: DRAFT to ENTERED; cascade per order_type. | `Judge` |
| POST | `/probate-orders/{id}/supersede` | Manually supersede an ENTERED order. | `Judge` |
| POST | `/_clock/set_current_utc` | Pin the system clock for deterministic time tests. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATED` | 422 |
| `ERR_EXECUTOR_BENEFICIARY_CONFLICT` | 422 |
| `ERR_CONTINGENT_PARENT_INVALID` | 422 |
| `ERR_CREDITOR_WINDOW_CLOSED` | 422 |
| `ERR_SHARE_OVERALLOCATION` | 422 |
| `ERR_SHARE_NOT_FULLY_ALLOCATED` | 422 |
| `ERR_WARD_OVER_AGE` | 422 |
| `ERR_INSUFFICIENT_ESTATE_FUNDS` | 422 |
| `ERR_DUPLICATE_EXECUTOR_ACTIVE` | 422 |
| `ERR_STALE_ESTATE_VERSION` | 412 |
| `ERR_HIPAA_RECIPIENTS_REQUIRED` | 422 |
| `ERR_POA_INTERVAL_OVERLAP` | 422 |
| `ERR_DUPLICATE_WARD` | 422 |

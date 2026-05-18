# Estate Planning Trust API — Product Requirements Document

## 1. Introduction

Estate administration is one of the most procedurally dense domains in personal finance: a single decedent's affairs may span dozens of real-property holdings, brokerage accounts, household chattels and digital credentials, all of which must be inventoried, appraised, and ultimately conveyed to a heterogeneous set of heirs under the eye of a probate court. The Estate Planning Trust API exists to give a small operations team — an executor petitioning probate, a beneficiary watching the disposition of their share, a court clerk ruling on filings, and the assorted trustees and guardians appointed along the way — a single shared system of record across that lifecycle.

The platform models four collaborating actor roles whose duties are deliberately segregated: the person petitioning the court cannot also rule on their own filings, and the person receiving an inheritance cannot quietly mutate the asset table. On top of that role separation the system layers the documents that govern incapacity and end-of-life — Powers of Attorney, HIPAA authorizations, and end-of-life directives — and the fiduciary appointments — executors, trustees, and guardians of minor beneficiaries — so that one estate's full legal posture is reconstructible from the API alone. Court-recognized procedural milestones (petition, inventory, distribution petition, final accounting) advance the estate through its administrative phases, with strict invariants on bonding, designation completeness, and distribution drift at each step.

A logical clock drives time-gated transitions (POA activation, guardianship effectivity, HIPAA expiry) deterministically, so that tests and rehearsals can fast-forward without waiting on real wall-clock time. All monetary values are carried in integer cents to remove any ambiguity about rounding, and bond calculations apply marginal tiers with banker's rounding so that the bond posted in real life matches the bond demanded by the system to the cent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which the user is acting. Either header missing or empty causes the request to be rejected with `ERR_AUTH_REQUIRED` and HTTP 401. A request that supplies headers but whose role is not authorized for the endpoint receives `ERR_FORBIDDEN` and HTTP 403.

The four valid values of `X-User-Role` are `Executor`, `Beneficiary`, `CourtClerk`, and `Fiduciary`.

When `X-User-Role` is `Executor`, `X-User-ID` is the `id` of the acting `Fiduciary` row (one whose `scope_type` is `EXECUTOR`); ownership checks compare any resource's executor reference back to this `id`. When `X-User-Role` is `Fiduciary` (covering the non-executor scopes — trustees and guardians), `X-User-ID` is again the `id` of the acting `Fiduciary` row, and self-only operations — for example, resigning — compare it against the `Fiduciary.contact_user_id` of the target row. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`, and any self-only operation (such as disclaiming one's own interest) requires that `X-User-ID` match `Beneficiary.id`. When `X-User-Role` is `CourtClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; a request asking for a `limit` outside that band is rejected with `ERR_BAD_REQUEST`. The default `offset` is 0 and `offset` may not be negative. List results are returned sorted by `created_at` ascending, so a stable forward walk through pages produces every row exactly once. The response's `meta` block exposes `limit`, `offset`, `total_count`, and `has_more` for every list endpoint.

### 2.4. Common Resource Properties

All persisted resources carry an `id` which is a server-minted UUID and does not include any type prefix; clients never supply an `id`. Resources whose lifecycle is mutable also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that begins at 1 and increments by exactly 1 on every mutation (state transition, PATCH, or scaffold-defined cascade that writes to the row). `BeneficiaryDesignation` is the single append-only allocation record in the model: its rows carry only `id` and `created_at` — `updated_at` and `version` are absent — and a row's status is only ever changed through scaffold-defined cascades (PROPOSED→LOCKED on estate advance, PROPOSED→VOIDED on disclaim/remove/explicit void, LOCKED→VOIDED on a subsequent disclaim).

### 2.5. Nested Resource Retrieval

Resource paths follow the parent-child hierarchy under the `/estates` mount. The server validates path parameters strictly left-to-right: it first resolves the top-level `estateId`, and only if that estate exists does it look for the nested `assetId`, `beneficiaryId`, `designationId`, `fiduciaryId`, `guardianshipId`, `hipaaId`, `poaId`, `directiveId`, `filingId`, or `distributionId` under that estate. Any miss along the way yields `ERR_NOT_FOUND` with HTTP 404, including the case where the nested id refers to a resource that exists but is parented to a different estate.

### 2.6. Optimistic Concurrency

Mutation endpoints (PATCH and any state transition endpoint) accept an optional `version` field in the request body. When `version` is supplied, the server compares it to the current `version` of the target row before applying any change; a mismatch causes the request to be rejected with `ERR_VERSION_MISMATCH` and HTTP 409. When `version` is omitted, the OCC check is skipped — the caller is asserting it does not care which prior revision it is overwriting. Every mutation that succeeds increments `version` by 1 and refreshes `updated_at`.

State-transition endpoints additionally accept a `to_status` field in the request body naming the target state to move the resource into; the server validates that the `to_status` value is a permitted transition from the row's current status under the relevant entity's state machine, and rejects with `ERR_INVALID_STATE` (HTTP 409) when it is not.

### 2.7. Monetary Precision and the Cent Discipline

Every money-bearing field is carried in integer cents — `declared_value_cents`, `appraised_value_cents`, `bond_amount_cents`, `planned_amount_cents`, `actual_amount_cents`, `gross_estate_value_cents`, `net_estate_value_cents`. Cents must be non-negative integers; fractional cents are not representable on the wire. Aggregations of cents (sums, differences) are integer arithmetic and require no rounding. The bond calculation is the one place a non-integer rate meets the integer ledger: each per-tier product is rounded to the nearest cent using banker's rounding (round half to even), then the rounded per-tier amounts are summed and a flat fee added — the order "round each tier, then sum" is part of the contract, not "sum then round". The fiduciary risk score is the second non-integer site, rounded half-up to four decimal places. Distribution allocation uses floor at the per-designation level with deterministic remainder distribution; details are in §3.

### 2.8. Probate Posture and the Estate Compound State

Beyond its primary `admin_phase`, every estate also has a derived `probate_posture` that captures the court's current relationship to the estate. The posture is recomputed whenever any `ProbateFiling`, any `Fiduciary`, or the estate's own `admin_phase` changes, and is not directly writable. If `admin_phase` is `CONTESTED` the posture is `FROZEN`. Otherwise, if any `ProbateFiling` for this estate is in status `REVISION_REQUESTED`, the posture is `UNDER_COURT_REVIEW`. In every other case — including a settled estate — the posture is `OPEN`. The posture acts as a gating signal: an `OPEN` posture is required to advance an estate from `INVENTORIED` to `DISTRIBUTING`; any other posture causes that advance to be rejected with `ERR_POSTURE_BLOCKED`.

### 2.9. Cascades, Versions, and Updated Timestamps

Many state transitions in this domain trigger side effects on sibling rows — terminating Powers of Attorney when an estate enters probate, voiding designations when a beneficiary disclaims, revoking active HIPAA authorizations when the estate settles. Every cascaded row that is mutated as part of these side effects has its `updated_at` refreshed and its `version` incremented by one — exactly as if it had been the direct target of a request. Cascades fire synchronously within the originating request and are transactional: either the whole tree of mutations commits or the originating request is rejected. The single exception is `BeneficiaryDesignation`, which carries no `version` and no `updated_at` and is only ever marked status-changed in place.

### 2.10. Validation Priority Order

When a request would fail more than one validation, the rejection returns the first failing rule's `error_id`, evaluated in this fixed order: (1) authentication-header presence (`ERR_AUTH_REQUIRED`), (2) role authorization for the endpoint (`ERR_FORBIDDEN`), (3) URL path existence and parent-child scope (`ERR_NOT_FOUND`), (4) referential integrity of foreign-key fields in the body (`ERR_REFERENCE_NOT_FOUND`), (5) optimistic-concurrency `version` match (`ERR_VERSION_MISMATCH`), (6) state-machine reachability (`ERR_INVALID_STATE`), (7) HIPAA scope coverage for directive execution (`ERR_HIPAA_SCOPE_INSUFFICIENT`), (8) POA scope coverage for asset mutation while the estate is in `DRAFT` (`ERR_POA_SCOPE_INSUFFICIENT`), (9) court-supervised filing permission (`ERR_FILING_NOT_PERMITTED`), (10) the per-asset designation over-allocation cap (`ERR_DESIGNATION_OVER_ALLOCATED`), (11) guardianship-of-minors completeness at the distribution advance (`ERR_GUARDIANSHIP_MISSING`), (12) executor bonding adequacy (`ERR_BOND_INSUFFICIENT`), (13) distribution-amount drift on execution (`ERR_DISTRIBUTION_DRIFT`), (14) guardianship effective-date forward dating (`ERR_DIRECTIVE_EFFECTIVE_PAST`), (15) settlement-deadline preservation (`ERR_SETTLEMENT_DEADLINE_PASSED`). Authentication is therefore evaluated strictly before authorization, and structural checks before business rules.

### 2.11. The Logical Clock

The system maintains an internal logical clock, distinct from real wall-clock time, used to evaluate every time-gated transition. A `CourtClerk` may advance the logical clock to a supplied future instant; doing so causes the server to evaluate, in a single pass, every time-gated auto-transition that has just become eligible: any `PowerOfAttorney` in `PENDING` whose `effective_at` is now reached (and whose estate remains in `DRAFT`) becomes `ACTIVE`; any `GuardianshipDirective` in `DRAFT` whose `effective_at` is now reached (and whose estate is in `IN_PROBATE`, and whose appointed guardian fiduciary is `CONFIRMED`) becomes `EFFECTIVE`; any `HIPAAAuthorization` in `ACTIVE` whose `expires_at` is non-null and now reached becomes `EXPIRED`. The clock value may also be read; it never moves backward.

## 3. Business Logic & Workflows

### 3.1. Opening an Estate: Pre-Probate Drafting

A new estate is created by an `Executor` posting `testator_name`, `domicile_state` (the two-letter US state code where probate will be filed), and `filing_court_id` (the opaque identifier of the supervising court). On creation the estate's `admin_phase` is `DRAFT` and its derived `probate_posture` is `OPEN`. While the estate is in `DRAFT`, those three identity fields may be updated; once probate begins they freeze. During `DRAFT` the executor builds the inventory and document set without court supervision: declaring assets, naming beneficiaries, proposing share designations, filing HIPAA authorizations, executing Powers of Attorney, drafting end-of-life directives, and drafting guardianships for any minor heirs.

Asset declarations specify an `asset_class` chosen from `REAL_ESTATE`, `FINANCIAL`, `PERSONAL_PROPERTY`, or `DIGITAL`; a free-text `description` up to 500 characters; a non-negative `declared_value_cents` representing the executor's initial estimate; and an optional `requires_poa_for_mutation` flag. A newly declared asset enters `status` `DECLARED`. The `appraised_value_cents` is not supplied at creation — it is only written when the asset transitions from `INVENTORIED` to `APPRAISED`, and that field too must be a non-negative integer of cents. The `estate_id` of an asset is system-assigned from the path. Updates to `description` or `declared_value_cents` are only permitted while the asset is in `DECLARED` or `INVENTORIED`.

Beneficiaries carry a `full_name`, a `relationship` chosen from `SPOUSE`, `CHILD`, `PARENT`, `SIBLING`, `CHARITY`, or `OTHER`, and a boolean `is_minor` (true if the beneficiary is under 18 at the moment of estate filing). When `is_minor` is true, a `guardianship_id` will eventually be required before the estate can advance into distribution; until that linkage is made the field is null. A beneficiary's `estate_id` is system-assigned and the `status` begins at `ACTIVE`.

While the estate is in `DRAFT`, the executor may also nominate other fiduciaries — including their eventual `EXECUTOR`, plus any `TRUSTEE` or `GUARDIAN` slots. Each `Fiduciary` row carries an `estate_id`, a `scope_type` from `EXECUTOR | TRUSTEE | GUARDIAN`, a `full_name`, and a `contact_user_id` (the `X-User-ID` that this fiduciary will use to sign requests, used as the ownership anchor for self-only operations). The optional `bond_amount_cents` declares the court bond the nominee proposes to post. A nominated fiduciary's `status` is `NOMINATED` and its `court_confirmation_at` is null; the `CourtClerk` will later transition it to `CONFIRMED`, which writes `court_confirmation_at` to the moment of the transition. Confirming a nominated fiduciary as `EXECUTOR` requires that their `bond_amount_cents` be at least the calculated bond requirement (otherwise the confirm fails with `ERR_BOND_INSUFFICIENT`) and that no other `Fiduciary` with `scope_type` `EXECUTOR` is currently `CONFIRMED` on this estate (otherwise `ERR_DUPLICATE_EXECUTOR`). Confirming a nominee as `GUARDIAN` requires that at least one `Beneficiary` with `is_minor` true exists on this estate, otherwise the confirm fails with `ERR_NO_MINOR_BENEFICIARY`. A `NOMINATED` fiduciary may also be removed outright by the clerk; a `CONFIRMED` fiduciary may be removed unilaterally as well.

A confirmed `EXECUTOR` cannot resign mid-probate without leaving a successor in the chair: while the estate's `admin_phase` is in `IN_PROBATE`, `INVENTORIED`, or `DISTRIBUTING`, an attempt by the `EXECUTOR` to transition from `CONFIRMED` to `RESIGNED` is rejected with `ERR_NO_SUCCESSOR` unless another `Fiduciary` with `scope_type` `EXECUTOR` is already `NOMINATED` on the same estate. Outside that band — for example while the estate is still in `DRAFT` — an executor may resign without a successor.

Powers of Attorney drafted in this phase declare a `poa_type` from `FINANCIAL_DURABLE`, `MEDICAL`, or `LIMITED`; an `agent_fiduciary_id` naming the agent; an `asset_class_scope` array containing the subset of `{REAL_ESTATE, FINANCIAL, PERSONAL_PROPERTY, DIGITAL}` the POA covers (an empty array means it covers no asset class; the value `ALL` is also accepted to denote the full envelope); and an `effective_at` timestamp. A newly created POA is `PENDING`, its `revoked_at` is null. Advancing the logical clock past `effective_at` while the estate is still in `DRAFT` auto-transitions the POA to `ACTIVE`. The executor may revoke a POA from either `PENDING` or `ACTIVE` at any time, which sets `revoked_at` to the moment of revocation and moves the row to `REVOKED`.

HIPAA authorizations name an `authorized_recipient`, a `scope` chosen from `MEDICAL_RECORDS`, `MENTAL_HEALTH`, `SUBSTANCE_ABUSE`, or `ALL`, a `signed_at` timestamp, and an optional `expires_at`. A row begins in `ACTIVE`. If `expires_at` is null the authorization is durable and never auto-expires; otherwise the logical clock crossing `expires_at` auto-transitions it to `EXPIRED`. The executor may also explicitly revoke an active authorization, moving it to `REVOKED`.

End-of-life directives declare a `directive_type` from `LIVING_WILL`, `DNR`, `DNI`, or `POLST`; free-text `instructions` up to 4000 characters; and a `requires_hipaa_scope` value naming the minimum HIPAA scope (`MEDICAL_RECORDS`, `MENTAL_HEALTH`, `SUBSTANCE_ABUSE`, or `ALL`) required to execute the directive. Optionally `supersedes_directive_id` points at an earlier directive; if supplied at creation, the prior directive (in either `DRAFT` or `EXECUTED`) auto-transitions to `SUPERSEDED`. The new row begins in `DRAFT` with `executed_at` null. The revision loop is cyclic: an executor may move a `SUPERSEDED` directive back to `DRAFT` provided the estate has not yet `SETTLED`, allowing renewed drafting on the same row.

Guardianship directives are drafted to pair a minor beneficiary with a guardian fiduciary. The creation payload includes `minor_beneficiary_id` (a `Beneficiary` whose `is_minor` is true), `guardian_fiduciary_id` (a `Fiduciary` with `scope_type` `GUARDIAN`), and an `effective_at` ISO 8601 UTC wall-clock instant. The `effective_at` must be at or after the current logical clock — a request whose `effective_at` is strictly earlier than now is rejected with `ERR_DIRECTIVE_EFFECTIVE_PAST`. A newly created guardianship's `status` is `DRAFT`. It auto-transitions to `EFFECTIVE` when, at clock advance, all three of the following hold simultaneously: the estate's `admin_phase` is `IN_PROBATE`, the guardian fiduciary is `CONFIRMED`, and the logical clock has reached or passed `effective_at`. When the auto-transition fires, the matched `Beneficiary.guardianship_id` is set to this directive's `id`, satisfying the eventual distribution-phase guardianship precondition for that minor. Creating a new directive for the same minor while a prior one is `EFFECTIVE` causes the prior row to auto-move to `SUPERSEDED` and rewires `Beneficiary.guardianship_id` to the new directive. A `CourtClerk` may revoke a guardianship from `DRAFT` unconditionally and from `EFFECTIVE` provided the estate is not in `DISTRIBUTING` (otherwise `ERR_INVALID_STATE`); revocation while `EFFECTIVE` also clears the `Beneficiary.guardianship_id` link on the affected minor.

### 3.2. The POA Gate on Asset Mutation

A subtlety of the pre-probate phase: when an asset is created with `requires_poa_for_mutation` set to true (the default is false), the executor cannot mutate it during `DRAFT` unless an `ACTIVE` `PowerOfAttorney` exists on the estate whose `asset_class_scope` covers that asset's `asset_class`. This gate applies to two operations specifically — the PATCH that updates `description` or `declared_value_cents`, and the state-transition POST that advances the asset's `status`. If the gate fires (no covering active POA), the request is rejected with `ERR_POA_SCOPE_INSUFFICIENT` and HTTP 403. The gate only operates while the estate is in `DRAFT`; once the estate enters `IN_PROBATE`, all PowerOfAttorney rows have been terminated by the death-event cascade and the executor's court-confirmed authority replaces them.

### 3.3. Entering Probate: The DRAFT → IN_PROBATE Transition

When the testator has died (or, more precisely, when the executor is ready to put the estate before the court), the executor advances the estate's `admin_phase` from `DRAFT` to `IN_PROBATE`. The transition payload supplies the target status; the actor must be an `Executor`. Three preconditions must hold simultaneously. First, at least one `Fiduciary` with `scope_type` `EXECUTOR` and `status` `CONFIRMED` must exist for the estate; absent that the advance is rejected with `ERR_NO_CONFIRMED_EXECUTOR`. Second, a `ProbateFiling` with `filing_type` `PETITION_TO_PROBATE` and `status` `ACCEPTED` must exist; absent that the advance is rejected with `ERR_NO_ACCEPTED_PETITION`. Third, the confirmed executor's `bond_amount_cents` must be at least the bond requirement computed against the estate's current `gross_estate_value_cents` under the forward-looking variant; otherwise `ERR_BOND_INSUFFICIENT`.

On successful transition, three side effects fire: `petition_filed_at` is set to the current clock; `settlement_due_at` is set to eighteen months after `petition_filed_at` (the procedural deadline against which the eventual distribution must stay in advance); and every `PowerOfAttorney` row in `PENDING` or `ACTIVE` is moved to `TERMINATED` — the death-event cascade. This POA termination is the legal fact that POA authority ceases at the principal's death. The cascade is depth one. The depth-two consequence: any `DECLARED` asset whose only path to mutation was the now-terminated POA becomes locked from further PATCH by the rule in §3.2 — though in practice this depth-two consequence is moot since pre-probate mutation is what the POA gate was guarding in the first place. Every cascaded row's `version` is incremented and `updated_at` refreshed.

### 3.4. Asset Inventory, Appraisal, and the Gross-Value Aggregation

Once the estate is in `IN_PROBATE`, the executor walks the asset table. Each `DECLARED` asset is moved to `INVENTORIED` (which requires the estate to be in `IN_PROBATE` or `INVENTORIED`, otherwise `ERR_INVALID_STATE`), or moved to `EXCLUDED` from one of the pre-distribution states. An asset may be excluded directly from `DECLARED` while the estate is in `DRAFT` or `IN_PROBATE`; it may also be excluded from `INVENTORIED`, but only if no `BeneficiaryDesignation` references it (otherwise `ERR_HAS_DEPENDENCIES`). Once moved to `INVENTORIED`, an asset is appraised by the executor: a second state transition supplies `appraised_value_cents` (required, must be a non-negative integer) and moves the asset to `APPRAISED`. The transition writes `appraised_value_cents` onto the row and recomputes the estate's `gross_estate_value_cents`.

The `gross_estate_value_cents` calculation is an aggregation across all of an estate's assets, but the aggregation has two variants that differ in which intermediate status is treated. The forward-looking variant — used at the bond check for `DRAFT → IN_PROBATE` and for the `INVENTORIED → DISTRIBUTING` precondition — includes `INVENTORIED` assets at their `declared_value_cents` (treating them as projecting forward to eventual appraisal) and `APPRAISED` and `DISTRIBUTED` assets at their `appraised_value_cents`. `EXCLUDED` assets are omitted. The chronological variant — used at `DISTRIBUTING → SETTLED` for the final accounting check — includes only `APPRAISED` and `DISTRIBUTED` assets, each at their `appraised_value_cents`; any `INVENTORIED` asset that was never appraised is excluded entirely. The two variants produce the same number whenever every asset that began inventory was also appraised; they diverge when an asset stayed in `INVENTORIED` indefinitely. All values are integer cents and no rounding is applied — the operation is pure integer summation. When two assets tie on `appraised_value_cents` and order matters for downstream calculations, the tie-break is ascending `Asset.id` as a string.

Once every asset is in `INVENTORIED`, `APPRAISED`, or `EXCLUDED` — that is, no asset remains in `DECLARED` — and a `ProbateFiling` of `filing_type` `INVENTORY_REPORT` with `status` `ACCEPTED` exists, the executor advances the estate from `IN_PROBATE` to `INVENTORIED`. Either precondition unmet produces `ERR_ASSETS_NOT_INVENTORIED` or `ERR_NO_ACCEPTED_INVENTORY` respectively. Recomputation of `gross_estate_value_cents` is a side effect of this transition.

### 3.5. Bond Tiers: The Marginal Calculation

The bond requirement protects the estate against fiduciary malfeasance and is computed as a marginal-tier tariff on the forward-looking `gross_estate_value_cents`. The first 10,000,000 cents of gross — i.e., the first $100,000 — is bonded at the rate of one hundred basis points; the next 90,000,000 cents — i.e., the band from $100,000 up to and including $1,000,000 — is bonded at fifty basis points; every cent of gross strictly above 100,000,000 cents — i.e., above $1,000,000 — is bonded at twenty-five basis points. The tier boundaries are evaluated as portions: the slice up to and including 10,000,000 cents falls into tier one, the slice strictly above 10,000,000 cents and up to and including 100,000,000 cents falls into tier two, and the slice strictly above 100,000,000 cents falls into tier three. For each tier the corresponding cents portion is multiplied by its rate and the result is rounded to the nearest cent using banker's rounding (round half to even); the three rounded per-tier cent amounts are then summed; finally a flat fee of 25,000 cents is added unrounded to produce the final `required_bond_cents`. Per-tier rounding before summation is part of the contract — summing first and then rounding can produce a different cent and is incorrect. This bond figure is what an executor's `bond_amount_cents` is compared against at both the `NOMINATED → CONFIRMED` transition and the `DRAFT → IN_PROBATE` transition, with `ERR_BOND_INSUFFICIENT` returned on shortfall.

### 3.6. Designations, Allocation, and the Waterfall

While the estate is inventoried or before, the executor proposes `BeneficiaryDesignation` rows binding each `Asset` to one or more `Beneficiary` rows. Each designation supplies an `asset_id`, a `beneficiary_id` (which must reference a `Beneficiary` whose `status` is `ACTIVE` at creation, otherwise `ERR_REFERENCE_NOT_FOUND`), a `share_basis_points` integer in the range 0 to 10000, and a `priority_rank` integer that breaks ties when the waterfall fires. Lower `priority_rank` is paid first. A new designation enters `status` `PROPOSED`.

The over-allocation guard is enforced at create time: the sum of `share_basis_points` across all `PROPOSED` and `LOCKED` designations targeting the same `asset_id`, including the proposed new row, must not exceed 10000; otherwise the create is rejected with `ERR_DESIGNATION_OVER_ALLOCATED`. The executor may delete (void) any `PROPOSED` designation outright, moving the row's `status` to `VOIDED`; deletion of a `LOCKED` or already-`VOIDED` row is not permitted.

When the estate advances from `INVENTORIED` to `DISTRIBUTING`, every `PROPOSED` designation on the estate is system-moved to `LOCKED`. The lock is version-pinned: the `LOCKED` row is now bound to the current `Beneficiary` set and to the current `appraised_value_cents` of its asset. The intent: between lock time and settlement, no further share rearrangement is permitted by the executor.

The planned distribution calculation runs as a side effect of that same `INVENTORIED → DISTRIBUTING` transition. For each `Asset` whose `status` is `APPRAISED` and which has at least one `LOCKED` designation: first, the total locked share in basis points is summed across the asset; if that total is less than 10000 (a hole left, for example, by a `PROPOSED` row that was voided before lock), the shortfall (10000 minus the locked total) is redistributed by waterfall — designations are processed in ascending `priority_rank`, and within tied ranks in ascending `designation.id` as a string, each absorbing as much of the shortfall as is available until the shortfall is exhausted. Each designation's final `allocated_share_bp` is its original `share_basis_points` plus whatever the waterfall added to it. The per-designation cent amount is the floor of `appraised_value_cents` times `allocated_share_bp` divided by 10000 — pure integer floor on the multiplication, not floating-point. After every designation on the asset has been allocated its floor amount, the rounding remainder (the asset's `appraised_value_cents` minus the sum of allocated floors) is distributed one cent at a time, again in ascending `priority_rank` then ascending `designation.id`, until the remainder is exhausted. Finally, the per-beneficiary `Distribution.planned_amount_cents` is the sum of per-designation cent amounts across every asset for that beneficiary; one `Distribution` row is created per beneficiary with `status` `PLANNED` and `actual_amount_cents` null.

### 3.7. Court Filings and the Revision Cycle

Procedural milestones with the probate court are recorded as `ProbateFiling` rows. The `filing_type` enumeration is `PETITION_TO_PROBATE`, `INVENTORY_REPORT`, `INTERIM_ACCOUNTING`, `FINAL_ACCOUNTING`, and `DISTRIBUTION_PETITION`. Each filing carries a `filed_by_fiduciary_id` identifying the fiduciary who submitted it. For every non-petition filing type, the submitting fiduciary must be a `Fiduciary` with `scope_type` `EXECUTOR` and `status` `CONFIRMED`; if not, the filing is rejected with `ERR_FILING_NOT_PERMITTED`. Petitions to probate are exempt from that confirm-first rule because they precede confirmation.

A newly submitted filing has `status` `SUBMITTED`, `court_response_at` null, and `rejection_reason` null. The court ruling is performed by a `CourtClerk` (or in the re-submit direction by an `Executor`). The clerk may accept the filing (moving it to `ACCEPTED`), reject it outright (moving it to `REJECTED` with a required `rejection_reason`), or request a revision (moving it to `REVISION_REQUESTED` with a required `rejection_reason`); a missing reason on either of the last two yields `ERR_BAD_REQUEST`. All three court actions set `court_response_at` to the moment of the ruling. A `REVISION_REQUESTED` filing may be re-submitted by the executor by transitioning it back to `SUBMITTED`; the re-submit clears `rejection_reason` and `court_response_at` to null. From `SUBMITTED` the filing can again be accepted, rejected, or sent back for further revision — the cycle is open-ended.

The clerk's acceptance check is content-aware. Accepting an `INVENTORY_REPORT` requires that every asset of the estate is in `INVENTORIED`, `APPRAISED`, or `EXCLUDED` — otherwise the acceptance fails with `ERR_ASSETS_NOT_INVENTORIED`. Accepting a `DISTRIBUTION_PETITION` requires that for every asset, the sum of `share_basis_points` across `PROPOSED` designations equals exactly 10000 — otherwise `ERR_DESIGNATIONS_INCOMPLETE`. Accepting a `FINAL_ACCOUNTING` requires that every `Distribution` row on the estate has `status` `EXECUTED` — otherwise `ERR_DISTRIBUTIONS_PENDING`.

Two distinct filings of the same type cannot both sit in `SUBMITTED` at the same time on the same estate. If an executor attempts to create a second `INVENTORY_REPORT` (for instance) while the first is still `SUBMITTED`, the second create races against the first; the loser receives `ERR_FILING_ALREADY_PENDING` with HTTP 409. First-writer-wins on the tuple of `(estate_id, filing_type, status=SUBMITTED)`. Once the first filing has moved to `ACCEPTED`, `REJECTED`, or `REVISION_REQUESTED`, the slot frees and another filing of the same type may be submitted.

### 3.8. Contesting and the FROZEN Posture

At any time during `IN_PROBATE` or `INVENTORIED`, a `CourtClerk` may declare the estate `CONTESTED`. The transition has no business preconditions — court contest is an external event. On entering `CONTESTED`, the estate's `contested_at` is set to the current clock, and every `ProbateFiling` for the estate currently in `SUBMITTED` is moved to `REVISION_REQUESTED` with `rejection_reason` set to `estate_contested`. The cascade is depth one for the filings themselves; the depth-two consequence is that those `REVISION_REQUESTED` filings now block the estate from later advancing from `INVENTORIED` to `DISTRIBUTING`, since the distribution-phase advance requires the `probate_posture` to be `OPEN` — and any `REVISION_REQUESTED` filing puts the posture at `UNDER_COURT_REVIEW`. The contest itself sets the posture to `FROZEN`. The clerk may later resolve the contest by transitioning the estate back from `CONTESTED` to `IN_PROBATE`; the resolution is conditional — no `ProbateFiling` may remain in `REVISION_REQUESTED`, otherwise `ERR_FILINGS_PENDING`. On successful resolution, `Estate.contested_at` is cleared back to null.

### 3.9. Beneficiary Disclaim and Remove

A beneficiary's interest can end one of two ways before settlement. The beneficiary themselves may disclaim — the transition is `ACTIVE → DISCLAIMED` and is permitted only while the estate's `admin_phase` is `IN_PROBATE` or `INVENTORIED` (else `ERR_INVALID_STATE`), and only if no `Distribution` with this `beneficiary_id` has been executed (else `ERR_HAS_DEPENDENCIES`). Disclaim is irrevocable. Disclaim cascades through `BeneficiaryDesignation`: every designation referencing this beneficiary in `PROPOSED` or `LOCKED` is moved to `VOIDED`. The depth-two consequence: any asset whose per-asset sum of designation `share_basis_points` (in `PROPOSED` or `LOCKED`) falls below 10000 because of the disclaim now blocks any forward `INVENTORIED → DISTRIBUTING` advance until the executor reissues enough designations to total 10000 again. If a beneficiary disclaims after `LOCKED` designations exist for them — that is, after the estate has already advanced to `DISTRIBUTING` — the cascade still voids the `LOCKED` rows, and if any asset is left without a `LOCKED` designation summing to 10000 the estate is forced back from `DISTRIBUTING` to `INVENTORIED`.

Alternatively, a `CourtClerk` may remove a beneficiary — the transition is `ACTIVE → REMOVED`, permitted while the estate is in any phase except `SETTLED` (else `ERR_INVALID_STATE`). Removal voids any `PROPOSED` designation for the beneficiary, but `LOCKED` designations are court-protected and remain `LOCKED` — this is the deliberate asymmetry between disclaim (beneficiary-initiated, full void of both `PROPOSED` and `LOCKED`) and remove (court-initiated, `PROPOSED` only).

### 3.10. The Race Between Disclaim and Distribution Advance

The boundary between `INVENTORIED` and `DISTRIBUTING` is where serialization matters most. Suppose a beneficiary disclaims at the same moment the executor attempts to advance the estate from `INVENTORIED` to `DISTRIBUTING`. The two requests race on the same `Estate.admin_phase` row, and first-writer-wins. If the disclaim commits first, the subsequent state advance fails: the cascade of the disclaim has voided one or more would-be-locked designations and the precondition (sum of `share_basis_points` per asset across `PROPOSED` designations equals 10000) no longer holds; the executor receives `ERR_INVALID_STATE`. If the advance commits first, the disclaim still succeeds — disclaim has no precondition against `admin_phase` `DISTRIBUTING` — and the `LOCKED → VOIDED` cascade fires on the now-locked rows, which then forces `admin_phase` back from `DISTRIBUTING` to `INVENTORIED` if any asset is left short.

### 3.11. Distribution Petition, Distribution Execution, and Drift

To leave `INVENTORIED` for `DISTRIBUTING`, the executor's advance must satisfy four preconditions in addition to OCC. The `probate_posture` must be `OPEN` — neither `UNDER_COURT_REVIEW` nor `FROZEN` — else `ERR_POSTURE_BLOCKED`. Every beneficiary with `is_minor` true must have a `GuardianshipDirective` in `status` `EFFECTIVE` linked through `Beneficiary.guardianship_id`; missing the link yields `ERR_GUARDIANSHIP_MISSING`. The sum of `share_basis_points` per asset across `PROPOSED` designations must equal exactly 10000 for every asset, else `ERR_DESIGNATIONS_INCOMPLETE`. A `ProbateFiling` of `filing_type` `DISTRIBUTION_PETITION` and `status` `ACCEPTED` must exist, else `ERR_NO_ACCEPTED_DISTRIBUTION_PETITION`. Additionally, the current logical clock must be strictly before `Estate.settlement_due_at` — once that deadline has passed, the advance is rejected with `ERR_SETTLEMENT_DEADLINE_PASSED`.

The successful advance fires the two side effects already noted: `PROPOSED → LOCKED` on every designation, and the planned-distribution calculation that materializes one `Distribution` row per beneficiary in `status` `PLANNED`.

Each `Distribution` row is then executed by the executor in turn. Execution transitions `PLANNED → EXECUTED` and requires the estate's `admin_phase` to be `DISTRIBUTING` (else `ERR_INVALID_STATE`), and an `actual_amount_cents` non-negative integer to be supplied (else `ERR_BAD_REQUEST`). Critically, `actual_amount_cents` must equal `planned_amount_cents` exactly — there is no drift permitted — else `ERR_DISTRIBUTION_DRIFT`. On success, `executed_at` is set to the moment of the transition.

In parallel with `Distribution` execution, each `Asset` whose `LOCKED` designation has been disbursed is itself moved from `APPRAISED` to `DISTRIBUTED`. The transition requires the estate to be in `DISTRIBUTING`, requires the supplied `distribution_id` to refer to a `Distribution` whose `status` is already `EXECUTED`, and requires the supplied distribution to belong to a beneficiary that is in fact `LOCKED` against this asset; otherwise it fails with `ERR_INVALID_STATE` or `ERR_DESIGNATION_MISMATCH`. The side effect writes `distribution_id` onto the asset. Two simultaneous `APPRAISED → DISTRIBUTED` transitions on the same asset (the race that arises when two `LOCKED` designations mistakenly co-point to the same asset) serialize on `Asset.status=DISTRIBUTED` first-writer-wins; the loser receives `ERR_ASSET_ALREADY_DISTRIBUTED`.

A `CourtClerk` may reverse an `EXECUTED` distribution back to `REVERSED` as a compensating action — for example, when a beneficiary later disclaims while the estate is still `DISTRIBUTING`. Reversal requires the estate not to be in `SETTLED` and requires that the underlying `Beneficiary.status` is not `REMOVED`; either condition yields `ERR_INVALID_STATE`. On reversal, any `Asset` whose `distribution_id` references this distribution reverts to `APPRAISED` and has its `distribution_id` cleared back to null. The invariant the system preserves: an `EXECUTED + REVERSED` pair leaves `gross_estate_value_cents` unchanged from its value before the execute.

### 3.12. Final Accounting and Settlement

Once every asset that carries a `LOCKED` designation has reached `DISTRIBUTED`, and a `ProbateFiling` of `filing_type` `FINAL_ACCOUNTING` and `status` `ACCEPTED` exists, the executor advances the estate from `DISTRIBUTING` to `SETTLED`. The settlement check also requires that the sum of `actual_amount_cents` across `EXECUTED` distributions matches the sum of `planned_amount_cents` across `PLANNED` and `EXECUTED` distributions — and since drift on individual distributions is already forbidden by `ERR_DISTRIBUTION_DRIFT` at execution time, this aggregate matches by construction; the explicit aggregate check exists to catch any out-of-band manipulation, returning `ERR_DISTRIBUTION_DRIFT` if violated. Missing assets distribution yields `ERR_ASSETS_NOT_DISTRIBUTED`; missing final accounting yields `ERR_NO_ACCEPTED_FINAL_ACCOUNTING`.

`net_estate_value_cents` is computed at the settlement check as the chronological variant of `gross_estate_value_cents` minus any court-recognized fees and debts (zero in this benchmark by stipulation), and the identity holds: `net_estate_value_cents` equals the sum of `actual_amount_cents` across `EXECUTED` distributions.

On successful settlement, two cascades fire. Every `Fiduciary` with `scope_type` `EXECUTOR` and `status` `CONFIRMED` is moved to `REMOVED` — the executor's commission ends with the settled estate. Every `HIPAAAuthorization` in `ACTIVE` is moved to `REVOKED` — medical privacy authorizations dissolve with the estate. Both cascades increment `version` and refresh `updated_at` on each affected row.

### 3.13. Executing End-of-Life Directives and the HIPAA Race

An end-of-life directive in `DRAFT` may be executed by the `Executor` while the estate is in `IN_PROBATE` or `INVENTORIED` (else `ERR_INVALID_STATE`). The execution precondition is HIPAA scope coverage: there must exist a `HIPAAAuthorization` whose `status` is `ACTIVE` and whose `scope` covers the directive's `requires_hipaa_scope`. Scope coverage follows the natural enumeration — `ALL` covers any required scope, and any non-`ALL` `scope` covers only the matching scope (e.g., `MEDICAL_RECORDS` covers `MEDICAL_RECORDS` only). Absent a covering active authorization, the execution is rejected with `ERR_HIPAA_SCOPE_INSUFFICIENT` and HTTP 403. On success, `executed_at` is set to the moment of execution and the directive moves to `EXECUTED`.

When an executor revokes a HIPAA authorization in the same window that another request is executing a directive dependent on it, the two requests race on `HIPAAAuthorization.status` and first-writer-wins. If the revoke commits first, the directive execution sees no covering authorization and is rejected with `ERR_HIPAA_SCOPE_INSUFFICIENT`. If the execute commits first, the directive remains `EXECUTED` and the revocation proceeds normally; the now-revoked authorization no longer covers future executions, and any other `DRAFT` directive whose `requires_hipaa_scope` is no longer covered by any other `ACTIVE` authorization is blocked from future execution. The same cascade fires under the `ACTIVE → EXPIRED` auto-transition reached via clock advance: any future-execution path that depended on the just-expired authorization is shut.

A directive may also be revoked outright from `DRAFT` by the executor (moving it to `REVOKED`), and the revision loop (a `SUPERSEDED` row moved back to `DRAFT` provided the estate is not `SETTLED`) supports iterative revision.

### 3.14. The Fiduciary Risk Score

A weighted risk score is computed for an `EXECUTOR` fiduciary at two trigger points: when the fiduciary transitions `CONFIRMED → RESIGNED`, and when any fiduciary moves to `REMOVED`. The score is a weighted sum of three sub-factors evaluated in fixed order.

First, the time factor: it is the maximum of zero and the count of days from now until `Estate.settlement_due_at` divided by 540 (the count of days in the eighteen-month statutory window). The factor is capped at 1.0 at its upper bound. Second, the bond factor: it is `Fiduciary.bond_amount_cents` divided by the `required_bond_cents` denominator, and is not capped above 1.0 — an over-bonded fiduciary scores correspondingly higher on this factor. The denominator uses the forward-looking variant of `gross_estate_value_cents` for the provisional score (computed at `RESIGNED`, when the estate is still active) and the chronological variant for the final score (computed at the settlement precondition). Third, the filing factor: it is the count of `ProbateFiling` rows on this estate filed by this fiduciary whose `status` is `ACCEPTED`, divided by the maximum of one and the count of all `ProbateFiling` rows on this estate filed by this fiduciary — protecting against division by zero when the fiduciary filed nothing.

The three sub-factors are combined: the time factor with weight 1.0, the bond factor with weight 2.0, and the filing factor with weight 2.0. The resulting score is rounded half-up to four decimal places and then clamped between a floor of 0.0000 and a ceiling of 5.0000. The pinned evaluation order — time factor first, then bond factor, then filing factor — affects observability when the score is logged with its component breakdown; the arithmetic itself is summation.

### 3.15. The Race for the Executor Chair

Only one `EXECUTOR` fiduciary may sit in `CONFIRMED` at a time on any given estate. If a `CourtClerk` attempts to confirm a `NOMINATED` executor while another `Fiduciary` with `scope_type` `EXECUTOR` is already in `CONFIRMED` on the estate, the second confirm is rejected with `ERR_DUPLICATE_EXECUTOR`. If two clerks attempt to confirm two different `EXECUTOR` nominees simultaneously, the two requests race on the tuple `(estate_id, scope_type=EXECUTOR, status=CONFIRMED)`; first-writer-wins, and the loser also receives `ERR_DUPLICATE_EXECUTOR`. The two semantics — "already had one" and "raced and lost" — collapse into the same `error_id` and HTTP 409 by design.

### 3.16. Clock Advance and Time-Gated Transitions

The `CourtClerk` may advance the logical clock to a supplied `to_timestamp` instant; the request body for the clock-advance capability carries that single field. Each advance fires a sweep over all time-gated rows. PowerOfAttorney rows in `PENDING` whose `effective_at` has been reached, and whose estate is in `DRAFT`, move to `ACTIVE`. GuardianshipDirective rows in `DRAFT` whose `effective_at` has been reached, and whose estate is in `IN_PROBATE` and whose appointed guardian is `CONFIRMED`, move to `EFFECTIVE` — and on that transition the `Beneficiary.guardianship_id` of the matched minor is set to the directive's `id`, unlocking the eventual `INVENTORIED → DISTRIBUTING` precondition for that minor. HIPAAAuthorization rows in `ACTIVE` whose `expires_at` is non-null and has been reached move to `EXPIRED`. Every cascaded auto-transition increments `version` and refreshes `updated_at` on the affected row. Reading the clock returns the current logical-clock instant.

## 4. Endpoint Definitions

New resources are created with HTTP 201 and the created object in the response `data`. State transitions, PATCH updates, and reads return HTTP 200 with the up-to-date resource (or list) in `data`. Errors return their declared 4xx status per §5 with the error body envelope of §2.2. All listing endpoints follow the pagination, sort, and `meta` rules of §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/advance | Advance server logical clock; fires all time-gated auto-transitions | CourtClerk |
| GET | /_clock | Read current logical clock | CourtClerk, Executor, Beneficiary, Fiduciary |
| POST | /estates | Create a new estate (begins in `DRAFT`) | Executor |
| GET | /estates/{estateId} | Read one estate | Executor, Beneficiary, CourtClerk, Fiduciary |
| GET | /estates | List estates with filters `admin_phase`, `probate_posture` | CourtClerk |
| PATCH | /estates/{estateId} | Update `testator_name`, `domicile_state`, `filing_court_id` while `DRAFT` | Executor |
| POST | /estates/{estateId}/state | Transition `admin_phase` per §3 | Executor, CourtClerk |
| POST | /estates/{estateId}/assets | Declare an asset under an estate | Executor |
| GET | /estates/{estateId}/assets/{assetId} | Read one asset | Executor, Beneficiary, CourtClerk, Fiduciary |
| GET | /estates/{estateId}/assets | List assets with filters `status`, `asset_class` | Executor, Beneficiary, CourtClerk, Fiduciary |
| PATCH | /estates/{estateId}/assets/{assetId} | Update asset `description` or `declared_value_cents` while `DECLARED`/`INVENTORIED` | Executor |
| POST | /estates/{estateId}/assets/{assetId}/state | Transition asset status per §3 | Executor |
| POST | /estates/{estateId}/beneficiaries | Nominate a beneficiary | Executor |
| GET | /estates/{estateId}/beneficiaries/{beneficiaryId} | Read one beneficiary | Executor, Beneficiary, CourtClerk |
| GET | /estates/{estateId}/beneficiaries | List beneficiaries with filter `status` | Executor, CourtClerk |
| POST | /estates/{estateId}/beneficiaries/{beneficiaryId}/state | Transition beneficiary per §3 (`DISCLAIMED` self-only; `REMOVED` clerk-only) | Beneficiary, CourtClerk |
| POST | /estates/{estateId}/designations | Propose a beneficiary designation | Executor |
| GET | /estates/{estateId}/designations/{designationId} | Read one designation | Executor, Beneficiary, CourtClerk |
| GET | /estates/{estateId}/designations | List designations with filters `asset_id`, `beneficiary_id`, `status` | Executor, Beneficiary, CourtClerk |
| DELETE | /estates/{estateId}/designations/{designationId} | Void a `PROPOSED` designation | Executor |
| POST | /estates/{estateId}/fiduciaries | Nominate a fiduciary | Executor, CourtClerk |
| GET | /estates/{estateId}/fiduciaries/{fiduciaryId} | Read one fiduciary | Executor, Beneficiary, CourtClerk, Fiduciary |
| GET | /estates/{estateId}/fiduciaries | List fiduciaries with filters `scope_type`, `status` | Executor, Beneficiary, CourtClerk, Fiduciary |
| POST | /estates/{estateId}/fiduciaries/{fiduciaryId}/state | Transition fiduciary per §3 (`CONFIRMED`/`REMOVED` clerk-only; `RESIGNED` self-only) | CourtClerk, Fiduciary |
| POST | /estates/{estateId}/guardianships | Create a guardianship directive | Executor |
| GET | /estates/{estateId}/guardianships/{guardianshipId} | Read one guardianship | Executor, Beneficiary, CourtClerk |
| POST | /estates/{estateId}/guardianships/{guardianshipId}/state | Revoke a guardianship | CourtClerk |
| POST | /estates/{estateId}/hipaa | Create a HIPAA authorization | Executor |
| GET | /estates/{estateId}/hipaa/{hipaaId} | Read one HIPAA authorization | Executor, CourtClerk |
| POST | /estates/{estateId}/hipaa/{hipaaId}/state | Revoke a HIPAA authorization | Executor |
| POST | /estates/{estateId}/poas | Create a Power of Attorney | Executor |
| GET | /estates/{estateId}/poas/{poaId} | Read one Power of Attorney | Executor, CourtClerk |
| POST | /estates/{estateId}/poas/{poaId}/state | Revoke a Power of Attorney | Executor |
| POST | /estates/{estateId}/directives | Create an end-of-life directive (optionally supersedes a prior) | Executor |
| GET | /estates/{estateId}/directives/{directiveId} | Read one directive | Executor, CourtClerk |
| POST | /estates/{estateId}/directives/{directiveId}/state | Transition a directive per §3 | Executor |
| POST | /estates/{estateId}/filings | Submit a probate filing | Executor |
| GET | /estates/{estateId}/filings/{filingId} | Read one filing | Executor, Beneficiary, CourtClerk |
| GET | /estates/{estateId}/filings | List filings with filters `filing_type`, `status` | Executor, Beneficiary, CourtClerk |
| POST | /estates/{estateId}/filings/{filingId}/state | Court ruling on a filing or executor re-submit per §3 | CourtClerk, Executor |
| GET | /estates/{estateId}/distributions/{distributionId} | Read one distribution | Executor, Beneficiary, CourtClerk |
| GET | /estates/{estateId}/distributions | List distributions with filters `status`, `beneficiary_id` | Executor, Beneficiary, CourtClerk |
| POST | /estates/{estateId}/distributions/{distributionId}/state | Execute or reverse a distribution per §3 | Executor, CourtClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_BAD_REQUEST | 400 |
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_HIPAA_SCOPE_INSUFFICIENT | 403 |
| ERR_POA_SCOPE_INSUFFICIENT | 403 |
| ERR_FILING_NOT_PERMITTED | 403 |
| ERR_POSTURE_BLOCKED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_MISMATCH | 409 |
| ERR_FILING_ALREADY_PENDING | 409 |
| ERR_DUPLICATE_EXECUTOR | 409 |
| ERR_NO_SUCCESSOR | 409 |
| ERR_NO_CONFIRMED_EXECUTOR | 409 |
| ERR_NO_ACCEPTED_PETITION | 409 |
| ERR_NO_ACCEPTED_INVENTORY | 409 |
| ERR_NO_ACCEPTED_DISTRIBUTION_PETITION | 409 |
| ERR_NO_ACCEPTED_FINAL_ACCOUNTING | 409 |
| ERR_ASSETS_NOT_INVENTORIED | 409 |
| ERR_ASSETS_NOT_DISTRIBUTED | 409 |
| ERR_ASSET_ALREADY_DISTRIBUTED | 409 |
| ERR_HAS_DEPENDENCIES | 409 |
| ERR_DESIGNATION_MISMATCH | 409 |
| ERR_FILINGS_PENDING | 409 |
| ERR_DISTRIBUTIONS_PENDING | 409 |
| ERR_DESIGNATION_OVER_ALLOCATED | 422 |
| ERR_DESIGNATIONS_INCOMPLETE | 422 |
| ERR_GUARDIANSHIP_MISSING | 422 |
| ERR_NO_MINOR_BENEFICIARY | 422 |
| ERR_BOND_INSUFFICIENT | 422 |
| ERR_DISTRIBUTION_DRIFT | 422 |
| ERR_DIRECTIVE_EFFECTIVE_PAST | 422 |
| ERR_SETTLEMENT_DEADLINE_PASSED | 422 |

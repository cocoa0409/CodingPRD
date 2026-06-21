# Section 8 Housing Voucher API — Product Requirements Document

## 1. Introduction

The Section 8 Housing Choice Voucher program lets a Public Housing Agency (PHA) help low-income families afford housing on the private market. This API models the full administrative spine of that program: it takes an applicant family from initial application and income-eligibility screening, through voucher issuance, the search for a qualifying unit, Housing Quality Standards (HQS) inspection, rent reasonableness review, and lease-up under a Housing Assistance Payment (HAP) contract, and then through the recurring obligations of annual reexamination and annual inspection. It also models the harder edges of the program — a family's right to take its voucher to another jurisdiction (portability), the choice the receiving agency makes to either bill the issuing agency or absorb the voucher onto its own funding, and special mobility incentives that reward moves into low-poverty opportunity areas.

The defining challenge of this domain is that subsidy money, eligibility, and physical housing are all interlocked. A single failed annual inspection can ripple from the inspection record, through the abatement of a contract's subsidy, to a unit being pulled off the market, and — if the landlord never cures the defect — all the way to the termination of the family's voucher and assistance. The dollar figures themselves are the product of layered formulas: statutory income deductions, a family-size-scaled eligibility ceiling, a tenant-share calculation that takes the greater of several candidates, and a subsidy that is capped at a regional payment standard. Every monetary amount in the system is carried as an integer number of cents to keep these computations exact, and the rules below specify precisely how each value is derived, which actor may trigger each transition, and what cascades follow.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that apply across every endpoint: authentication, the response envelope, pagination, the shared shape of resources, monetary precision, the cascade discipline that keeps interlinked records consistent, and the optimistic-concurrency protections on the two supersede-capable writes.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the role under which they are acting. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are present but the declared role is not permitted to perform the requested operation under the access matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `ProgramAdmin`, `Caseworker`, `Inspector`, `PortabilityCoordinator`, and `Landlord`.

For four of these roles — `ProgramAdmin`, `Caseworker`, `Inspector`, and `PortabilityCoordinator` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept and record such an identifier but does not compare it against any entity's `id` for ownership purposes; authorization for these roles depends only on the role name. For the `Landlord` role, by contrast, `X-User-ID` is the `id` of the acting `Landlord` entity. Any ownership check on a resource that references a `Landlord` — for example, a `Unit` carrying a `landlord_id`, or a `HapContract` reachable through a unit's landlord — compares that foreign key to the `X-User-ID` value to confirm the landlord is acting on its own records.

`ProgramAdmin` administers regions, payment standards, and the system-level operations: voucher expiration, the post-deadline cure failure, and the test-driving clock. `Caseworker` manages households, eligibility determinations, voucher issuance, rent reasonableness, lease-up, contract termination, and annual reviews. `Inspector` conducts HQS inspections and records their pass, fail, and cure outcomes. `PortabilityCoordinator` approves and denies portability moves and administers special mobility grants. `Landlord` registers landlords, lists rental units, and views its own contracts.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of leading items to skip; it defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response includes the following fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Nearly every resource in this system carries a standard set of server-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value on creation and increments by one on every mutation. It supports the optimistic-concurrency checks described in Section 2.7.

These four fields apply to `Region`, `PaymentStandard`, `Household`, `Voucher`, `Unit`, `Landlord`, `HapContract`, `Inspection`, `PortabilityMove`, `AnnualReview`, and `SpecialMobilityGrant`. The one exception is the `RentReasonablenessDetermination` resource, which is immutable once written: it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field.

### 2.5. Hierarchical Consistency and Cascades

The records in this system are deeply interlinked, and many operations mutate more than one of them. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this is equally true of resources changed as a downstream consequence of another operation, not only the resource the request directly named. When a single action cascades into several records, each affected record independently has its `updated_at` and `version` updated. The specific cascades — a failed annual inspection abating a contract and pulling a unit off the market, an expired voucher terminating its household, a terminated contract unwinding voucher, household, and unit — are described in the workflow narratives of Section 3, and each must be applied in full.

### 2.6. Monetary Precision and Rounding

All monetary values are stored and exchanged as integer numbers of cents; there are no fractional cents and no floating-point money in API payloads. Where a calculation produces a non-integer intermediate (for instance, dividing an annual figure into a monthly one, or scaling by a percentage), the rounding rule is specified inline with that calculation in Section 3. Two rounding disciplines appear in this system. The income and tenant-share computations round half up to the nearest whole cent — a value exactly halfway between two cents rounds upward. The adjusted-income and subsidy computations instead floor their final result at zero so that a deduction-heavy family or an over-standard rent can never produce a negative stored amount. Each Section 3 formula states which discipline applies and, critically, at what point in the computation the rounding occurs.

### 2.7. Optimistic Concurrency Control

Two write operations in this system can supersede state that another writer may have advanced, and both are guarded by an optimistic-concurrency check that requires the client to declare the parent version it last observed.

The first is lease-up. Creating a HAP contract requires the field `expected_voucher_version`, carrying the `version` of the target voucher as the client last read it. If that value does not match the voucher's current `version` — for example, because an approved portability move has since flipped the voucher to `PORTING_OUT` or `ABSORBED` and bumped its version — the lease-up is rejected with `ERR_STALE_VERSION` (HTTP 412), so the caseworker cannot lease a voucher whose state has moved out from under their view.

The second is annual-review finalization. Finalizing an annual review requires the field `expected_hap_contract_version`, carrying the `version` of the contract being re-examined as the client last observed it. If that value does not match the contract's current `version` — for example, because a failed annual inspection has since abated the contract and bumped its version — the finalization is rejected with `ERR_STALE_VERSION` (HTTP 412), so a review drafted against a now-stale contract cannot be applied.

These two endpoints are the only ones that take a version field. No other endpoint accepts or requires `expected_voucher_version`, `expected_hap_contract_version`, or any other version input.

### 2.8. Nested Reference Validation and Validation Ordering

Many requests reference other resources, either through a path identifier or through a foreign key in the body. The system validates references left to right: path identifiers first, then body foreign keys. The first referenced resource that does not exist causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated.

Across all endpoints, validation proceeds in a fixed priority order, and the first failing check determines the error returned. Authentication comes first: a missing header yields `ERR_UNAUTHENTICATED`. Role authorization comes second: a forbidden role yields `ERR_FORBIDDEN_ROLE`. Existence of all referenced resources comes third, yielding `ERR_NOT_FOUND`. For any endpoint that drives a state machine, the target's state validity comes fourth, yielding `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a state from which the requested transition is legal. The optimistic-concurrency check comes fifth on the two writes that carry a version field, yielding `ERR_STALE_VERSION`. The domain-specific business rules described in Section 3 are evaluated after these, and the catch-all structural check — required body fields present, correctly typed, and within their declared enum and numeric ranges — surfaces as `ERR_VALIDATION` (HTTP 400). Where several business rules apply to one endpoint, the lease-up endpoint's internal ordering is spelled out in Section 3.5; that ordering is part of the contract because it determines which error a multiply-invalid request returns.

### 2.9. Enumerations and Region Mechanics

Several fields are constrained to fixed enumerations, and the exact strings matter. A `Household` carries a `status` of `APPLIED`, `ELIGIBLE`, `INELIGIBLE`, `VOUCHER_ISSUED`, `LEASED`, or `TERMINATED`. A `Voucher` carries a `status` of `ISSUED`, `EXPIRED`, `PORTING_OUT`, `ABSORBED`, `LEASED`, or `TERMINATED`. A `Unit` carries a `status` of `LISTED`, `UNDER_CONTRACT`, or `OFF_MARKET`. A `HapContract` carries a `status` of `ACTIVE`, `ABATED`, or `TERMINATED`. An `Inspection` carries an `inspection_type` of `INITIAL` or `ANNUAL` and a `status` of `SCHEDULED`, `PASSED`, `FAILED`, `CURED`, or `ABATED`. A `RentReasonablenessDetermination` carries an `outcome` of `REASONABLE` or `NOT_REASONABLE`. A `PortabilityMove` carries a `billing_mode` of `BILLING` or `ABSORPTION` and a `status` of `REQUESTED`, `APPROVED`, `ABSORBED`, or `DENIED`. An `AnnualReview` carries a `status` of `DRAFT` or `FINALIZED`. A `SpecialMobilityGrant` carries a `status` of `GRANTED`, `CONSUMED`, or `REVOKED`.

A `Region` is the jurisdictional anchor of the program. It is created with a `code` (an uppercase identifier using only A–Z and underscore, between 3 and 40 characters, and unique across all regions), a human-readable `name`, an `fmr_year` indicating the Fair Market Rent schedule year on which the region's payment standards are based, and an `is_special_mobility_area` flag that, when omitted, defaults to false and marks the region as a designated low-poverty opportunity area when true. Time-gated checks throughout the system — voucher expiration and inspection cure deadlines — are evaluated against a server clock whose value can be set for testing through an admin-only test-driving capability that accepts a target instant in the `to_iso8601` field and moves the server's current UTC to that instant.

## 3. Business Logic & Workflows

### 3.1. Regions, Payment Standards, and Landlord Inventory

Before any family can be served, a `ProgramAdmin` establishes the regions and the payment standards that price subsidy within them. A **payment standard** is created against a region (referenced by `region_id`) for a specific `bedroom_size` — a bedroom count from 0 (studio) through 6. Each standard records its monthly `amount_cents` and the published Fair Market Rent it is based on, `fmr_cents`; both must be at least zero. The region-and-bedroom pair must be unique: if a standard already exists for that `region_id` and `bedroom_size`, the creation is rejected with `ERR_DUPLICATE_PAYMENT_STANDARD` (HTTP 409). The amount is further constrained to the statutory band around the Fair Market Rent: `amount_cents` must be at least 90 percent of `fmr_cents` and at most 110 percent of `fmr_cents`, with both ends of the band inclusive. An amount below 90 percent or above 110 percent of the published Fair Market Rent is rejected with `ERR_PAYMENT_STANDARD_OUT_OF_BAND` (HTTP 422).

Separately, a `Landlord` is registered with its legal `name` and a `payee_account` reference used to route Housing Assistance Payments. Landlords list rental **units**; a unit is created against a landlord (`landlord_id`) and a region (`region_id`) where it is physically located, with a `bedroom_size` from 0 through 6, a monthly `asking_rent_cents` (the landlord's asking gross rent), and a `comparable_rent_cents` (the PHA's surveyed comparable market rent that anchors rent reasonableness). All monetary inputs must be at least zero. A newly listed unit begins in `LISTED` status; it advances to `UNDER_CONTRACT` when leased and to `OFF_MARKET` when its assistance is abated or terminated.

A `Caseworker` may run a standalone **rent reasonableness determination** ahead of lease-up. It is created against a unit (`unit_id`) with a `requested_rent_cents` — the contract rent submitted for review. The determination snapshots the unit's surveyed comparable market rent into its own `comparable_rent_cents` at evaluation time and records an `outcome`: the outcome is `REASONABLE` when the `requested_rent_cents` is less than or equal to that snapshotted comparable rent, with the boundary inclusive, and `NOT_REASONABLE` otherwise. This determination is an immutable audit record carrying only its `id` and `created_at`.

### 3.2. Household Application and Income Eligibility

A `Caseworker` registers a **household** application by supplying the head of household's `head_name`, the `family_size` (the number of persons, at least one), the self-reported gross `annual_income_cents` at application (at least zero), and the `region_id` of the jurisdiction where the family applied. Three optional inputs feed later deductions: `dependents_count` (the number of dependents, defaulting to zero and never negative), `elderly_or_disabled` (a flag, defaulting to false, set when the head of household is elderly — age 62 or older — or disabled, which unlocks an additional deduction), and `childcare_expense_cents` (annual reasonable childcare expense, defaulting to zero and never negative). A new household begins in `APPLIED` status. Its `adjusted_annual_income_cents` is a computed field, left to be populated by the eligibility determination.

When the caseworker runs eligibility on an `APPLIED` household, the system first computes adjusted annual income, then tests it against a family-size-scaled ceiling. The **adjusted income** is the household's gross `annual_income_cents` reduced by three deductions: a dependent deduction equal to `dependents_count` multiplied by 480 dollars (48,000 cents) per dependent; an elderly-or-disabled deduction of 400 dollars (40,000 cents) applied only when `elderly_or_disabled` is true and otherwise zero; and a childcare deduction equal to the household's `childcare_expense_cents`. Adjusted income is the gross income minus all three deductions, and if that subtraction would fall below zero it is floored at zero. The result is stored as `adjusted_annual_income_cents` in integer cents.

The **eligibility ceiling** starts from a regional very-low-income base of 40,000 dollars (4,000,000 cents) and scales by family size. A family of one or fewer uses a factor of 0.70; a family of two uses 0.80; a family of three uses 0.90; a family of four uses 1.00; and each person beyond four adds 0.08 to the factor — that is, the factor for families larger than four is 1.00 plus 0.08 multiplied by the number of persons in excess of four. The income limit is the base multiplied by this factor, rounded half up to the nearest cent. The family is eligible when its `adjusted_annual_income_cents` is less than or equal to that income limit; the boundary is inclusive, so a household whose adjusted income exactly equals the limit qualifies. An eligible determination sets the household's `status` to `ELIGIBLE`; otherwise it sets the `status` to `INELIGIBLE` (`APPLIED → INELIGIBLE`). Both branches store the computed `adjusted_annual_income_cents`. `INELIGIBLE` is a terminal state.

### 3.3. Voucher Issuance and the Search Term

A `Caseworker` issues a **voucher** to a household that has reached `ELIGIBLE` status. Issuance requires the `household_id`; if the named household is not in `ELIGIBLE` status, issuance is rejected with `ERR_HOUSEHOLD_NOT_ELIGIBLE` (HTTP 422). On success the voucher is created in `ISSUED` status and the household advances from `ELIGIBLE` to `VOUCHER_ISSUED`. The voucher records the `issuing_region_id` of the issuing PHA.

The voucher's `bedroom_size` is computed from the household's family size by the occupancy standard rather than supplied: a family of one or fewer is assigned 0 bedrooms; otherwise the bedroom count is the family size divided by two and rounded up to the next whole number, capped at a maximum of 6 bedrooms. The voucher's `issued_date` is stamped at issuance as the start of the search-term clock, and its `expiration_date` is computed as the issued date plus the search term. The search term in days is supplied as `term_days`, defaulting to 60 days and never below 1; the expiration date is the issued date advanced by exactly that many days. The voucher must be leased up before its expiration.

A voucher whose term has elapsed is expired through a system operation available to `ProgramAdmin`. Expiration is permitted only when the voucher is `ISSUED` and the server's current UTC is at or after the voucher's `expiration_date`; it moves the voucher from `ISSUED` to `EXPIRED` and cascades the linked household to `TERMINATED`. Correspondingly, when a household is still in `VOUCHER_ISSUED` and the current UTC has reached the voucher's expiration date, that household reaches `TERMINATED` as the cascade of expiry.

### 3.4. HQS Inspections and the Cure Window

Inspections enforce Housing Quality Standards. An **inspection** is scheduled — by an `Inspector` or a `Caseworker` — against a unit (`unit_id`) with an `inspection_type` of either `INITIAL` or `ANNUAL` and a `scheduled_date`. An annual inspection additionally references the contract it re-examines through `hap_contract_id`; for an initial inspection that field is left empty. Every inspection begins in `SCHEDULED` status, and its `cure_deadline` is a computed field populated only on failure.

An `Inspector` records the outcome. Passing a scheduled inspection moves it to `PASSED`; if the inspection was of type `INITIAL`, passing also marks the linked unit `UNDER_CONTRACT`. Failing a scheduled inspection moves it to `FAILED` and sets its `cure_deadline` to the `scheduled_date` advanced by the standard cure window of 14 days. If the failed inspection is an annual inspection of an active contract, failing also triggers the contract's abatement cascade described in Section 3.6.

A failed deficiency can be cured. An `Inspector` records a cure only while the inspection is `FAILED` and the server's current UTC is on or before the `cure_deadline`; a cure attempted after the deadline is rejected with `ERR_CURE_DEADLINE_PASSED` (HTTP 422). A timely cure moves the inspection from `FAILED` to `CURED`, and if the linked contract is currently `ABATED`, it triggers the contract's restoration cascade (also in Section 3.6). If, instead, the cure window lapses with no cure, a `ProgramAdmin` records the deadline failure: this system operation, permitted only when the inspection is `FAILED` and the current UTC is strictly past the `cure_deadline`, moves the inspection from `FAILED` to `ABATED` and triggers the contract's termination cascade. `PASSED`, `CURED`, and `ABATED` are terminal inspection states.

### 3.5. Lease-Up: The HAP Contract Gauntlet

Lease-up is where a family, a voucher, and a unit come together under a **Housing Assistance Payment contract**, and it is the most heavily guarded operation in the system. A `Caseworker` creates the contract with the `voucher_id`, the `unit_id`, the agreed gross `contract_rent_cents`, and the `expected_voucher_version` required by the optimistic-concurrency check of Section 2.7. On success the contract is created in `ACTIVE` status, the voucher advances to `LEASED`, the household advances to `LEASED`, the unit advances to `UNDER_CONTRACT`, and the voucher's `version` is incremented by one.

Beyond authentication, authorization, existence, and the stale-version check, lease-up runs a sequence of business gates, each with its own error, evaluated in the following order. First, the voucher must be available for lease-up: its status must be either `ISSUED` or `PORTING_OUT` (a ported voucher can still be leased), and a voucher in any other status is rejected with `ERR_VOUCHER_NOT_AVAILABLE` (HTTP 422). Second, the unit must be large enough for the voucher: the unit's `bedroom_size` must be greater than or equal to the voucher's `bedroom_size`, since the program forbids over-housing beyond the standard, and a unit smaller than the voucher's bedroom size is rejected with `ERR_BEDROOM_MISMATCH` (HTTP 422). Third, the voucher must not be expired: the server's current UTC must be strictly before the voucher's `expiration_date`, and a voucher whose expiration date is at or before the current UTC is rejected with `ERR_VOUCHER_EXPIRED` (HTTP 422). Fourth, the unit must have a passed initial inspection: there must exist a `PASSED` inspection of type `INITIAL` for the unit, and lease-up without one is rejected with `ERR_INSPECTION_NOT_PASSED` (HTTP 422). Fifth, the rent must be reasonable: the `contract_rent_cents` must be less than or equal to the unit's `comparable_rent_cents`, with the boundary inclusive, and a contract rent above the comparable rent is rejected with `ERR_RENT_NOT_REASONABLE` (HTTP 422). Sixth and last, the initial rent-burden gate must pass, as described below, failing with `ERR_RENT_BURDEN_EXCEEDED` (HTTP 422).

The contract's monetary fields are computed during lease-up. The system first determines the **administering region** — the region whose payment standard governs the subsidy — and records it as `administering_region_id`. For an ordinary lease-up this is the voucher's issuing region; for a voucher that was ported out under billing, it is the receiving region recorded on the portability move (see Section 3.7).

The **total tenant payment** (TTP) is computed and stored as `total_tenant_payment_cents`. It is the largest of three candidates: thirty percent of the household's monthly adjusted income; ten percent of the household's monthly gross income; and a statutory minimum rent of 50 dollars (5,000 cents). Monthly adjusted income is the household's `adjusted_annual_income_cents` divided by twelve, and monthly gross income is the household's `annual_income_cents` divided by twelve; the first candidate is 0.30 of monthly adjusted income and the second is 0.10 of monthly gross income. The system takes the maximum of these three candidates and rounds that maximum half up to the nearest whole cent — the rounding happens once, after the maximum is taken, never to the candidates beforehand. At initial lease-up this calculation uses the household's adjusted income as set at eligibility.

The **monthly subsidy** is then computed and stored as `hap_subsidy_cents`. The system looks up the payment standard for the administering region and the voucher's bedroom size and reads its `amount_cents`. The capped rent is the lesser of the `contract_rent_cents` and that payment-standard amount: when the contract rent is at or below the payment standard the capped rent equals the contract rent (a gross subsidy), and when the contract rent exceeds the payment standard the capped rent equals the payment standard and the tenant absorbs the overage above it. The HAP subsidy is the capped rent minus the total tenant payment, floored at zero so it is never negative. Finally the contract's `tenant_rent_burden_cents` is the `contract_rent_cents` minus the `hap_subsidy_cents` — the tenant's full out-of-pocket share.

The sixth gate, the **initial rent-burden check**, applies only at this first lease-up and not at any later reexamination. The maximum allowable burden is forty percent of the household's monthly adjusted income — monthly adjusted income (the adjusted annual income divided by twelve) multiplied by 0.40, rounded half up to the nearest cent. Lease-up passes the gate when the computed `tenant_rent_burden_cents` is less than or equal to that maximum, with the boundary inclusive: a burden exactly equal to forty percent passes, and a burden above forty percent fails with `ERR_RENT_BURDEN_EXCEEDED`.

One further side effect can fire on a successful lease-up: if the unit's region matches the target region of an outstanding special mobility grant on the voucher, that grant is consumed, as described in Section 3.8.

A standing contract can be terminated by a `Caseworker`. Terminating an `ACTIVE` contract moves it to `TERMINATED` and cascades broadly: the linked voucher is set to `TERMINATED`, the linked household is set to `TERMINATED`, and the linked unit is set to `OFF_MARKET`.

### 3.6. Annual Inspection Outcomes and Subsidy Abatement

The annual HQS inspection is where physical-quality enforcement meets the money. When an annual inspection of an `ACTIVE` contract is failed, the contract enters abatement: it moves from `ACTIVE` to `ABATED`, its `hap_subsidy_cents` is set to zero so no subsidy is paid while the deficiency stands, and the linked unit is cascaded to `OFF_MARKET`. This abatement is keyed to the contract named by the failed inspection's `hap_contract_id`.

Recovery depends on the landlord curing the defect in time. When a timely cure is recorded against the failed inspection (the inspection moving `FAILED → CURED`) and the contract is currently `ABATED`, the contract is restored from `ABATED` to `ACTIVE`, its `hap_subsidy_cents` is recomputed by re-running the subsidy calculation of Section 3.5 (payment-standard lookup, capping, and flooring at zero, against the contract's current total tenant payment), and the linked unit is cascaded back to `UNDER_CONTRACT`.

If the cure window instead lapses, the consequences run the full length of the chain. When a `ProgramAdmin` records the post-deadline failure on an `ABATED` contract — the inspection moving `FAILED → ABATED` because the current UTC is past the `cure_deadline` — the contract moves from `ABATED` to `TERMINATED`, the linked voucher is set to `TERMINATED`, and the linked household is set to `TERMINATED` as a cascade of that cascade. This is the path by which an uncured housing-quality defect ultimately ends the family's assistance.

### 3.7. Portability Across Regions

Portability lets a family carry its voucher to another jurisdiction. A `PortabilityCoordinator` or `Caseworker` requests a **portability move** for a voucher (`voucher_id`) toward a destination region (`receiving_region_id`). The move is created in `REQUESTED` status. The receiving region must differ from the voucher's issuing region; a request naming the same region the voucher was issued in is rejected with `ERR_SAME_REGION_PORT` (HTTP 422). At request time the system resolves the `billing_mode` from the receiving region: if the receiving region's `is_special_mobility_area` flag is true the billing mode resolves to `ABSORPTION`, and otherwise it resolves to `BILLING`. This resolution is deterministic and is re-read at approval.

A `PortabilityCoordinator` approves or denies the request. Approval is permitted only when the move is `REQUESTED`, the linked voucher is `ISSUED`, and the receiving region still differs from the voucher's issuing region. The approval branches on the resolved billing mode. When the mode is `BILLING`, the move's `billing_mode` is set to `BILLING`, the move advances from `REQUESTED → APPROVED`, and the voucher cascades from `ISSUED → PORTING_OUT`; the voucher's `issuing_region_id` is left unchanged, and the receiving region is instead recorded as the administering region on the eventual lease. When the mode is `ABSORPTION`, the move's `billing_mode` is set to `ABSORPTION`, the move advances from `REQUESTED → ABSORBED`, and the voucher cascades from `ISSUED → ABSORBED` with its `issuing_region_id` reset to the move's `receiving_region_id`. Either approval bumps the voucher's version as part of the cascade, which is the very advance that can later strand a stale lease-up writer under the optimistic-concurrency rule of Section 2.7. Denial, permitted whenever the move is `REQUESTED`, simply moves it `REQUESTED → DENIED`. `ABSORBED` and `DENIED` are terminal move states.

A voucher in `PORTING_OUT` can subsequently be leased up so long as the current UTC is still before its `expiration_date`; that lease-up moves the voucher `PORTING_OUT → LEASED` and creates the contract with its `administering_region_id` set to the receiving region.

### 3.8. Annual Reexamination and Special Mobility

Once a year the family's circumstances are re-verified through an **annual review**. A `Caseworker` drafts a review against a contract (`hap_contract_id`) with the re-verified gross `new_annual_income_cents` (at least zero) and the `effective_date` on which the recomputed tenant share takes effect. A new review begins in `DRAFT` status; its `new_total_tenant_payment_cents` and `new_hap_subsidy_cents` are computed fields populated at finalization.

Finalization is performed by a `Caseworker` and carries the `expected_hap_contract_version` required by the optimistic-concurrency check of Section 2.7. It is permitted only when the review is `DRAFT` and the linked contract is `ACTIVE`. On finalization the household's `adjusted_annual_income_cents` is recomputed from the review's `new_annual_income_cents` using the same adjusted-income formula and deductions described in Section 3.2 (this is the reexamination variant of the tenant-share calculation, which differs from initial lease-up only in that it draws on the income recomputed from `new_annual_income_cents` rather than the income set at eligibility). The review's `new_total_tenant_payment_cents` is then computed by the total-tenant-payment formula of Section 3.5, and its `new_hap_subsidy_cents` by the subsidy formula of Section 3.5. These recomputed amounts cascade onto the contract: its `total_tenant_payment_cents`, `hap_subsidy_cents`, and `tenant_rent_burden_cents` are updated to match, the contract's `version` is incremented by one, and the review moves from `DRAFT → FINALIZED`. The forty-percent initial rent-burden gate is not applied at reexamination. `FINALIZED` is terminal.

Finally, **special mobility grants** incentivize moves into opportunity areas. A `PortabilityCoordinator` grants one against a voucher (`voucher_id`) toward a `target_region_id`, with an optional `term_extension_days` of extra search-term days defaulting to 30 and never below 1. The target region must be a region whose `is_special_mobility_area` flag is true; a grant naming a non-opportunity region is rejected with `ERR_NOT_MOBILITY_AREA` (HTTP 422). The grant is created in `GRANTED` status and, as a side effect, extends the linked voucher's `expiration_date` by the granted `term_extension_days`. A grant is consumed when the family actually leases up in the targeted region: on a successful lease-up where the leased unit's region equals the grant's `target_region_id`, an outstanding `GRANTED` grant moves `GRANTED → CONSUMED`. A `PortabilityCoordinator` may instead revoke a `GRANTED` grant, moving it `GRANTED → REVOKED` and rolling back the incentive by subtracting the `term_extension_days` back off the linked voucher's `expiration_date`. `CONSUMED` and `REVOKED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and system operations — return `200 OK`. List and retrieval operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/regions` | Create a region | ProgramAdmin |
| GET | `/regions/{id}` | Get a region | ProgramAdmin, Caseworker, Inspector, PortabilityCoordinator, Landlord |
| GET | `/regions` | List regions | ProgramAdmin, Caseworker, Inspector, PortabilityCoordinator, Landlord |
| POST | `/payment-standards` | Create a payment standard for a region and bedroom size | ProgramAdmin |
| GET | `/payment-standards/{id}` | Get a payment standard | ProgramAdmin, Caseworker, PortabilityCoordinator |
| GET | `/payment-standards` | List payment standards, filterable by region | ProgramAdmin, Caseworker, PortabilityCoordinator |
| POST | `/households` | Register a household application | Caseworker |
| GET | `/households/{id}` | Get a household | Caseworker, ProgramAdmin |
| GET | `/households` | List households, filterable by region | Caseworker, ProgramAdmin |
| POST | `/households/{id}/determine-eligibility` | Run income eligibility | Caseworker |
| POST | `/vouchers` | Issue a voucher to an eligible household | Caseworker |
| GET | `/vouchers/{id}` | Get a voucher | Caseworker, ProgramAdmin, PortabilityCoordinator |
| GET | `/vouchers` | List vouchers, filterable by household or issuing region | Caseworker, ProgramAdmin, PortabilityCoordinator |
| POST | `/vouchers/{id}/expire` | Expire a voucher whose term has elapsed | ProgramAdmin |
| POST | `/landlords` | Register a landlord | ProgramAdmin, Landlord |
| GET | `/landlords/{id}` | Get a landlord | ProgramAdmin, Landlord, Caseworker |
| POST | `/units` | List a rental unit | Landlord, ProgramAdmin |
| GET | `/units/{id}` | Get a unit | Landlord, ProgramAdmin, Caseworker, Inspector |
| GET | `/units` | List units, filterable by landlord or region | Landlord, ProgramAdmin, Caseworker, Inspector |
| POST | `/rent-reasonableness` | Run a rent reasonableness determination | Caseworker |
| GET | `/rent-reasonableness/{id}` | Get a rent reasonableness determination | Caseworker, ProgramAdmin |
| GET | `/rent-reasonableness` | List rent reasonableness determinations, filterable by unit | Caseworker, ProgramAdmin |
| POST | `/inspections` | Schedule an HQS inspection | Inspector, Caseworker |
| GET | `/inspections/{id}` | Get an inspection | Inspector, Caseworker, ProgramAdmin |
| GET | `/inspections` | List inspections, filterable by unit or contract | Inspector, Caseworker, ProgramAdmin |
| POST | `/inspections/{id}/pass` | Mark an inspection passed | Inspector |
| POST | `/inspections/{id}/fail` | Mark an inspection failed | Inspector |
| POST | `/inspections/{id}/cure` | Record a cured deficiency before the deadline | Inspector |
| POST | `/inspections/{id}/fail-cure` | Record a lapsed cure deadline | ProgramAdmin |
| POST | `/hap-contracts` | Lease up a voucher onto a unit | Caseworker |
| GET | `/hap-contracts/{id}` | Get a HAP contract | Caseworker, ProgramAdmin, Landlord |
| GET | `/hap-contracts` | List HAP contracts, filterable by voucher, unit, or administering region | Caseworker, ProgramAdmin, Landlord |
| POST | `/hap-contracts/{id}/terminate` | Terminate an active HAP contract | Caseworker |
| POST | `/portability-moves` | Request a portability move to a receiving region | PortabilityCoordinator, Caseworker |
| GET | `/portability-moves/{id}` | Get a portability move | PortabilityCoordinator, Caseworker, ProgramAdmin |
| GET | `/portability-moves` | List portability moves, filterable by voucher or receiving region | PortabilityCoordinator, Caseworker, ProgramAdmin |
| POST | `/portability-moves/{id}/approve` | Approve a portability move | PortabilityCoordinator |
| POST | `/portability-moves/{id}/deny` | Deny a portability move | PortabilityCoordinator |
| POST | `/annual-reviews` | Draft an annual reexamination for a contract | Caseworker |
| GET | `/annual-reviews/{id}` | Get an annual review | Caseworker, ProgramAdmin |
| GET | `/annual-reviews` | List annual reviews, filterable by contract | Caseworker, ProgramAdmin |
| POST | `/annual-reviews/{id}/finalize` | Finalize a review and update the contract | Caseworker |
| POST | `/special-mobility-grants` | Grant a special mobility incentive | PortabilityCoordinator |
| GET | `/special-mobility-grants/{id}` | Get a special mobility grant | PortabilityCoordinator, Caseworker, ProgramAdmin |
| GET | `/special-mobility-grants` | List special mobility grants, filterable by voucher or target region | PortabilityCoordinator, Caseworker, ProgramAdmin |
| POST | `/special-mobility-grants/{id}/revoke` | Revoke a granted mobility incentive | PortabilityCoordinator |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BEDROOM_MISMATCH` | 422 |
| `ERR_VOUCHER_EXPIRED` | 422 |
| `ERR_INSPECTION_NOT_PASSED` | 422 |
| `ERR_RENT_NOT_REASONABLE` | 422 |
| `ERR_RENT_BURDEN_EXCEEDED` | 422 |
| `ERR_PAYMENT_STANDARD_OUT_OF_BAND` | 422 |
| `ERR_SAME_REGION_PORT` | 422 |
| `ERR_CURE_DEADLINE_PASSED` | 422 |
| `ERR_NOT_MOBILITY_AREA` | 422 |
| `ERR_DUPLICATE_PAYMENT_STANDARD` | 409 |
| `ERR_HOUSEHOLD_NOT_ELIGIBLE` | 422 |
| `ERR_VOUCHER_NOT_AVAILABLE` | 422 |

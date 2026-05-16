# Medicaid Eligibility & Annual Redetermination API — Product Requirements Document

## 1. Introduction

Medicaid eligibility administration sits at the intersection of federal poverty guidelines, state-level policy overlays, household composition, household income aggregation, and a strict separation between front-line intake, eligibility adjudication, and appeals review. State agencies must compute Modified Adjusted Gross Income (MAGI) against an annually-updated Federal Poverty Level (FPL) threshold, apply state-specific disregards and asset exemptions where they exist, and enroll qualifying households for a 365-day coverage period that must then be renewed each year through a formal redetermination.

This document specifies the Medicaid Eligibility & Annual Redetermination API, the system of record that orchestrates that workflow end-to-end. The API governs the configuration of state policies, the intake of households, applicants, income, and asset records, the submission and adjudication of applications, the creation and maintenance of enrollments, the annual redetermination sweep, and the appeals process — including fair hearings — that allows applicants to challenge an unfavorable determination. The system additionally accommodates federal or state-level public health emergencies, which trigger a continuous-coverage protection that suspends the normal redetermination cadence until the emergency ends.

The API is intended for use by four distinct categories of public-sector users with deliberately segregated duties — front-line intake workers, eligibility caseworkers, appeals officers, and policy administrators — and is structured so that adjudication is never performed by the same person who originated the case. Because eligibility outcomes can be re-opened on appeal, every determination must remain auditable, every cascade must be deterministic, and every monetary or percentage value must be computed with reproducible precision.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and contracts that govern every endpoint. The business logic that interprets these contracts in domain terms is developed in §3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated via two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or invalid, the request is rejected with `ERR_UNAUTHENTICATED`. If the supplied role is valid but lacks permission for the requested endpoint per the role matrix, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, named with the following exact spellings:

- `IntakeWorker` — the front-line case worker who registers households, captures applicant demographics, records income and asset declarations, drafts applications, submits and withdraws applications, files appeals, withdraws pending redeterminations, and updates basic household and application metadata.
- `EligibilityCaseworker` — the adjudicator who decides applications that have been moved into review and submits redetermination decisions for enrollments that are due for annual renewal.
- `AppealsOfficer` — the official who schedules fair hearings, presides over them, and rules on appeals against unfavorable determinations.
- `PolicyAdmin` — the administrator who configures state policies, issues emergency declarations, suspends or reactivates enrollments, runs the system's bulk sweeps, and advances the logical clock.

All four roles have an **opaque** identity. When `X-User-Role` is `IntakeWorker`, `EligibilityCaseworker`, `AppealsOfficer`, or `PolicyAdmin`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity in the system; the server records the acting `X-User-ID` where the scaffolded transitions require it (notably, as `officer_id` on `FairHearing` and on `Appeal` when an appeal is scheduled) but does not compare it to the `id` of any entity. The system does, however, retain a record of the `X-User-ID` that issued each prior `EligibilityDetermination` and uses that record to enforce the segregation-of-duties rule described below.

In addition to standard role authorization, the system enforces a segregation-of-duties rule that compares `X-User-ID` values across roles and across time. An `EligibilityCaseworker` who is asked to re-decide an application that has cycled back into review must not be the same `X-User-ID` who issued the prior `INELIGIBLE` determination on that same application. An `AppealsOfficer` who is asked to grant or uphold an appeal must not be the same `X-User-ID` who issued the determination being appealed (in either role capacity). A violation of either rule is rejected with `ERR_FORBIDDEN_SAME_ACTOR`.

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

List endpoints accept two query parameters that control pagination. The `limit` parameter governs the maximum number of items returned and defaults to 10 when omitted; valid values range from a minimum of 1 to a maximum of 100. The `offset` parameter governs the number of items skipped at the start of the result and defaults to 0. Malformed values for either parameter are rejected with `ERR_INVALID_REQUEST`.

All list endpoints return resources sorted by their `created_at` timestamp in ascending order unless explicitly stated otherwise.

The `meta` envelope on every list response carries four pagination fields: `limit` (the effective page size used), `offset` (the effective offset used), `total_count` (the total number of resources matching the filter), and `has_more` (a boolean indicator of whether further pages remain).

### 2.4. Common Resource Properties

All primary resources expose the following system-managed properties:

- `id` (string) — a server-minted unique identifier formatted as a bare UUID, with no domain or type prefix.
- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first persisted.
- `updated_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer) — a system-managed counter that begins at 1 on creation and is incremented by exactly 1 on every successful mutation, including mutations induced by cascade.

Two entities are append-only and therefore differ from the standard shape. `IncomeRecord` and `AssetRecord` carry only `id` and `created_at`; they have no `updated_at` and no `version` because they are immutable once written. The `EmergencyDeclaration` is also append-only and likewise carries only `id` and `created_at`. Every other resource — `StatePolicy`, `Household`, `Applicant`, `Application`, `EligibilityDetermination`, `Enrollment`, `Redetermination`, `Appeal`, and `FairHearing` — carries the full set of four common fields.

Computed fields on a resource that are recalculated in response to a related write (for example, `household_size`, `total_magi`, `fpl_threshold_amount`, `fpl_percent`, and `active_enrollment_count` on `Household`) are mutations of the host resource: they refresh `updated_at` and increment `version` on the resource that owns them.

### 2.5. Nested Resource Retrieval and Path Validation

When an endpoint path contains multiple resource identifiers — for instance, a path that locates an `Applicant` under a parent `Household` via the path parameters `household_id` and `applicant_id`, or an `Application` under a parent `Household` via `household_id` and `application_id` — the system validates each identifier strictly left-to-right. If the parent identifier does not refer to an existing resource, the request is rejected immediately with `ERR_NOT_FOUND`, identifying the parent. The system does not attempt to resolve the child identifier until the parent has been confirmed to exist. The same precedence applies to top-level resource identifiers (the `enrollment_id` on enrollment endpoints, the `redetermination_id` on redetermination endpoints, the `appeal_id` on appeal endpoints, the `fair_hearing_id` on fair-hearing endpoints, the `declaration_id` on emergency-declaration endpoints, and the `state_code` on state-policy endpoints) and to body-level foreign key references such as `determination_id` on an appeal filing or `applicant_id` on an enrollment lookup: these references must also resolve, and a dangling reference is rejected with `ERR_NOT_FOUND`.

### 2.6. Precision, Rounding, and Monetary Representation

Monetary values, percentages, and any other decimal quantity that the system computes must be handled with deterministic precision so that two independent computations of the same input yield byte-identical output.

- All percentage values exposed by the API — most notably `fpl_percent`, `snapshot_fpl_percent`, `new_snapshot_fpl_percent`, `computed_fpl_percent`, `magi_income_limit_pct` (when echoed back), and the redetermination premium estimate — are rounded to exactly two decimal places using the round-half-up rule.
- All monetary values — `magi_income`, `total_magi`, `snapshot_magi`, `computed_magi`, `new_snapshot_magi`, `countable_assets`, `snapshot_countable_assets`, `market_value`, `countable_value`, `fpl_base_amount`, `fpl_per_member_amount`, `fpl_threshold_amount`, `state_disregard_amount`, `asset_limit_per_member`, `gross_amount` — are rounded to exactly two decimal places using the round-half-up rule wherever the system stores or returns a computed monetary amount.
- Where the eligibility comparison uses `fpl_percent`, the comparison is performed on the rounded two-decimal value, not on an intermediate unrounded result. A value of exactly the threshold is considered eligible (the comparison is inclusive of the ceiling).
- Datetime arithmetic uses UTC throughout and second-level precision. The "90 days" used to derive an appeal `deadline_at` and the "365 days" used to derive `coverage_end` and `redetermination_due_at` are interpreted as exactly 90 * 86400 seconds and 365 * 86400 seconds respectively, added to the originating instant.

### 2.7. Optimistic Concurrency Control

Two mutating endpoints accept an optimistic concurrency control token: the `PATCH` endpoints on `Household` and on `Application`. Both endpoints accept a `version` field in the request body.

If `version` is omitted from the body, the system does not perform a stale-write check and applies the patch unconditionally (overwriting whatever the current row holds). If `version` is supplied and matches the current `version` of the target resource, the patch is applied and `version` is incremented. If `version` is supplied and does not match, the patch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409); the client must refetch the resource and retry against the new `version`.

This rule applies only to PATCH endpoints. State-transition endpoints (submit, decide, schedule-hearing, hold, grant, uphold, withdraw, suspend, reactivate, redetermination submit, redetermination withdraw) do not accept a `version` and do not perform OCC; concurrent attempts on these endpoints serialize by state instead (see §2.10).

### 2.8. Hierarchical Consistency and Cascade Discipline

The system maintains a strict invariant: whenever a child entity's state transition implies a derived value on its parent, the parent is mutated within the same request and the parent's `updated_at` and `version` are refreshed. This applies in three principal places:

- Any change to the membership or computed income of a `Household`'s `Applicant`s — creating an applicant, appending an `IncomeRecord`, or appending an `AssetRecord` — refreshes the household's computed `household_size`, `total_magi`, `fpl_threshold_amount`, and `fpl_percent` on the next read of the parent, and any of these derived fields changing is treated as a mutation that bumps `Household.updated_at` and increments `Household.version`.
- Any transition that changes the `coverage_status` of an `Enrollment` (creation upon approval, suspension, reactivation, redetermination renewal or termination, the continuous-coverage flip from an emergency declaration, or the revert from continuous coverage when the last covering emergency expires) recomputes `active_enrollment_count` on the affected `Household` synchronously.
- Granting an appeal cascades, in order, through three resource mutations: the appealed `EligibilityDetermination`, the parent `Application`, and — once a follow-up approval is rendered — the `Enrollment` ledger and `Household.active_enrollment_count`. The detailed cascade chain is described in §3.6.

All cascaded mutations happen synchronously inside the triggering request. There is no eventual consistency window: by the time the API returns 2xx, every derived field that depends on the change is up to date.

### 2.9. State Enumerations

The exact strings the system uses for every state-bearing enumeration are reserved and must be referenced verbatim. These appear in request and response bodies and in any filter parameters.

- `Application.status` is one of: `DRAFT`, `UNDER_REVIEW`, `APPROVED`, `DENIED`, `APPEALED`, `WITHDRAWN`.
- `EligibilityDetermination.outcome` is one of: `ELIGIBLE`, `INELIGIBLE`, `OVERTURNED`.
- `EligibilityDetermination.ineligibility_reason` is one of `INCOME_EXCEEDS_LIMIT`, `ASSETS_EXCEED_LIMIT`, `NOT_RESIDENT`, `NON_QUALIFYING_PROGRAM`, or null when the outcome is `ELIGIBLE`.
- `Enrollment.coverage_status` is one of: `ACTIVE`, `CONTINUOUS_COVERAGE`, `REDETERMINATION_DUE`, `SUSPENDED`, `TERMINATED`.
- `Redetermination.status` is one of: `PENDING`, `SUBMITTED`, `RENEWED`, `TERMINATED`, `WITHDRAWN`.
- `Redetermination.decision` is `RENEWED` or `TERMINATED`.
- `Appeal.status` is one of: `FILED`, `HEARING_SCHEDULED`, `UNDER_REVIEW`, `GRANTED`, `UPHELD`, `WITHDRAWN`.
- `FairHearing.status` is one of: `SCHEDULED`, `HELD`, `CANCELLED`.
- `EmergencyDeclaration.status` is one of: `ACTIVE`, `EXPIRED` — derived from a comparison of `declared_at`, `expires_at`, and the logical clock at read time.
- `EmergencyDeclaration.scope` is `FEDERAL` or `STATE`.
- `Application.program` is one of `MAGI_ADULT`, `MAGI_CHILD`, `MAGI_PREGNANT`, `NON_MAGI_DISABILITY`, `NON_MAGI_AGED`.
- `Application.rule_variant` (and the mirrored `EligibilityDetermination.applied_rule_variant`) is `FEDERAL` or `STATE`.
- `Household.filing_status` is `SINGLE`, `MARRIED_JOINT`, `MARRIED_SEPARATE`, or `HEAD_OF_HOUSEHOLD`.
- `Applicant.dependent_status` is `PRIMARY`, `SPOUSE`, `DEPENDENT`, or `EXCLUDED`. `EXCLUDED` applicants do not contribute to `household_size` or `total_magi`.
- `IncomeRecord.source_type` is one of `WAGES`, `SELF_EMPLOYMENT`, `INTEREST`, `DIVIDENDS`, `CAPITAL_GAINS`, `SOCIAL_SECURITY`, `UNEMPLOYMENT`, `CHILD_SUPPORT`, `TANF`, `SSI`, or `OTHER`.
- `IncomeRecord.frequency` is `ANNUAL`, `MONTHLY`, `BIWEEKLY`, or `WEEKLY`.
- `AssetRecord.asset_type` is one of `PRIMARY_RESIDENCE`, `VEHICLE`, `CHECKING`, `SAVINGS`, `RETIREMENT`, `INVESTMENT`, `LIFE_INSURANCE`, or `OTHER`.

### 2.10. Validation Priority and Concurrency Serialization

When a request would fail more than one validation, the system always returns the failure highest in the following priority order, so that lower-priority rules cannot mask higher-priority ones. This order is enforced uniformly across all endpoints:

1. Authentication — missing or invalid `X-User-ID` / `X-User-Role` yields `ERR_UNAUTHENTICATED`.
2. Role authorization — a role that lacks permission for the endpoint yields `ERR_FORBIDDEN`.
3. Segregation of duties — same-actor violations on appeal grant, appeal uphold, and the re-decision of a previously denied application yield `ERR_FORBIDDEN_SAME_ACTOR`.
4. Existence — any path-id or body foreign key reference that does not resolve yields `ERR_NOT_FOUND`.
5. State machine — a target resource not in a valid state for the requested transition yields `ERR_INVALID_STATE`.
6. Household completeness — at application submit, an unset `head_applicant_id`, the absence of any non-`EXCLUDED` `Applicant`, or a `state_code` with no matching `StatePolicy` yields `ERR_HOUSEHOLD_INCOMPLETE`.
7. Appeal-window timeliness — an appeal filed more than 90 days after the determination, or a hearing whose `scheduled_start` is at or after the `Appeal.deadline_at`, yields `ERR_APPEAL_WINDOW_EXPIRED`.
8. Hearing-time validity — a hearing whose `scheduled_start` is not strictly before `scheduled_end`, or a hearing whose scheduled instants are not in the future at scheduling time, or a hold called before `clock_now` reaches `scheduled_start`, yields `ERR_HEARING_NOT_DUE`.
9. Hearing-officer overlap — a hearing whose buffered interval would collide with another `SCHEDULED` hearing for the same `officer_id` yields `ERR_HEARING_CONFLICT`.
10. Enrollment overlap — a new enrollment whose coverage window would overlap an existing non-`TERMINATED` enrollment on the same `applicant_id` yields `ERR_ENROLLMENT_OVERLAP`.
11. Appeal uniqueness — a second appeal against the same `determination_id` yields `ERR_APPEAL_ALREADY_EXISTS`.
12. Eligibility fiscal check — a computed `fpl_percent` strictly above the state's `magi_income_limit_pct`, or `snapshot_countable_assets` strictly above the asset ceiling when the asset test applies, yields `ERR_NOT_ELIGIBLE`.
13. FPL threshold validity — an effective household size of zero (so that `fpl_threshold_amount` would be zero and the percentage undefined) yields `ERR_FPL_THRESHOLD_INVALID`.
14. Optimistic concurrency — on `PATCH` only, a `version` mismatch yields `ERR_VERSION_CONFLICT`.
15. Request well-formedness — a malformed body, missing required field, invalid enum value, or backwards clock advance yields `ERR_INVALID_REQUEST`.

Concurrency between simultaneous writers is resolved by first-writer-wins serialization on the relevant entity row. Five concurrency scenarios are defined explicitly:

- Two `EligibilityCaseworker`s decide the same `UNDER_REVIEW` application concurrently. Exactly one decision commits; the loser observes that the application is no longer `UNDER_REVIEW` and receives `ERR_INVALID_STATE` (HTTP 409). Serialization is on `Application.status`.
- Two `AppealsOfficer`s attempt to schedule fair hearings for the same `officer_id` whose buffered intervals would collide. Exactly one scheduling commits; the loser sees the overlap and receives `ERR_HEARING_CONFLICT` (HTTP 409). Serialization is on `FairHearing` creation.
- A redetermination is submitted at the same moment an `EmergencyDeclaration` arrives whose scope covers the same enrollment. Whichever request first transitions the row wins; the loser observes that the `coverage_status` is no longer `REDETERMINATION_DUE` and receives `ERR_INVALID_STATE` (HTTP 409). Serialization is on `Enrollment.coverage_status`.
- Two distinct appeals are filed against the same `INELIGIBLE` `EligibilityDetermination` concurrently. At most one appeal exists per `determination_id`; the second creation is rejected with `ERR_APPEAL_ALREADY_EXISTS` (HTTP 409). Serialization is on the uniqueness of `Appeal.determination_id`.
- Two simultaneous `PATCH` requests update the same `Application` (or `Household`) with the same prior `version`. One commits; the other is rejected as a stale write with `ERR_VERSION_CONFLICT` (HTTP 409). The loser must refetch and retry.

### 2.11. Test-Driving the Logical Clock

The system maintains a logical clock, denoted `clock_now`, that drives every time-gated transition: emergency declarations expire when `clock_now` reaches `expires_at`, enrollments become due for redetermination when `clock_now` reaches their `redetermination_due_at`, fair hearings may be held only once `clock_now` reaches their `scheduled_start`, and appeals must be filed before `clock_now` exceeds the 90-day window from the underlying determination's `decided_at`.

An admin-only test-driving capability advances the logical clock to a supplied target instant carried in the request body as `to`. The advance must be monotonic forward — a `to` value that is strictly earlier than the current `clock_now` is rejected with `ERR_INVALID_REQUEST`. Advancing the clock has two automatic side effects: any `EmergencyDeclaration` whose `expires_at` is at or before the new `clock_now` transitions to `EXPIRED`, and any `Enrollment` whose state was `CONTINUOUS_COVERAGE` solely because of a now-expired emergency reverts to `ACTIVE` (a subsequent redetermination sweep may then move it onward to `REDETERMINATION_DUE` if its `redetermination_due_at` is also in the past).

## 3. Business Logic & Workflows

This section describes the full lifecycle of a Medicaid case as it moves through the system, from the front-office household intake through caseworker adjudication, enrollment, annual redetermination, the appeals path, and the public-health emergency overlay.

### 3.1. Configuring State Policy and Household Intake

Before any application can be filed, a `PolicyAdmin` must publish a `StatePolicy` for the relevant `(state_code, fpl_year)` pair. The policy carries the FPL economics for that state and year: an `fpl_base_amount` for a household of size one, an `fpl_per_member_amount` that is added once for every additional household member, an `magi_income_limit_pct` that is the eligibility ceiling expressed as a percentage of FPL (commonly 138 percent for ACA-expansion states and 133 percent for non-expansion states), and the asset-test configuration. The `asset_test_applies` flag defaults to false, reflecting that most MAGI-based categories carry no asset test; when the flag is true, `asset_limit_per_member` declares the countable-asset ceiling per effective household member. Each policy may also publish a `state_disregard_amount` that is subtracted from raw MAGI before the FPL percentage is computed (defaulting to zero), and `state_exempt_asset_types` that exempt additional asset categories beyond the fixed federal set. The policy also exposes a computed `emergency_continuous_active` flag indicating whether an active emergency covers the state at the current `clock_now`.

A `PolicyAdmin` may also issue an `EmergencyDeclaration`. Each declaration carries a `scope` of `FEDERAL` or `STATE`. When the scope is `STATE`, a `state_code` is required and identifies the affected state; when the scope is `FEDERAL`, `state_code` must be null. The declaration's window is bracketed by `declared_at` (the inclusive start instant) and `expires_at` (the exclusive end instant). The declaration's `status` is computed from the clock: it is `ACTIVE` when `declared_at <= clock_now < expires_at` and `EXPIRED` once `clock_now` has reached or passed `expires_at`. `EmergencyDeclaration` is append-only — it carries only the `id` and `created_at` system fields and may not be patched or deleted. Creating a declaration has a cascade described in §3.5.

A new case begins when an `IntakeWorker` creates a `Household`. The household carries a `state_code` that must reference an existing `StatePolicy`, an `address_line` capturing the street address as free text, and a `filing_status` chosen from `SINGLE`, `MARRIED_JOINT`, `MARRIED_SEPARATE`, or `HEAD_OF_HOUSEHOLD`. The household's `head_applicant_id` is initially null and is filled in automatically when the first `Applicant` with a non-`EXCLUDED` `dependent_status` is added to the household; subsequent applicants do not displace the head. The household's `household_size`, `total_magi`, `fpl_threshold_amount`, `fpl_percent`, and `active_enrollment_count` are all server-computed and are refreshed on the next read of the household after any change to its applicants or their income / asset / enrollment records.

The `IntakeWorker` then adds one or more `Applicant`s under the household, each carrying a `full_name`, a `date_of_birth` (ISO 8601 calendar date, used to derive age at `clock_now`), a `dependent_status`, an `is_disabled` flag (defaulting to false; a true value qualifies the applicant for a non-MAGI evaluation path that engages the asset test), and an `is_pregnant` flag (defaulting to false; a true value increases the effective household size by one per pregnancy when the FPL denominator is computed). Each applicant exposes computed values `magi_income`, `countable_assets`, and `redetermination_count_this_year` that the system recalculates on every read. Income is captured by appending `IncomeRecord`s under the applicant — each record records a `source_type`, a `gross_amount` in dollars, and a `frequency` of `ANNUAL`, `MONTHLY`, `BIWEEKLY`, or `WEEKLY`. Assets are captured by appending `AssetRecord`s — each record records an `asset_type` and a `market_value` in dollars. Both record kinds are immutable once written; the system tags each asset record with two computed flags, `exempt_under_federal` (true if the asset type is `PRIMARY_RESIDENCE`, `RETIREMENT`, or `LIFE_INSURANCE`, the fixed federal exempt set) and `exempt_under_state` (true if the asset type appears in the household's `StatePolicy.state_exempt_asset_types`), and a `countable_value` whose interpretation depends on the rule variant chosen at application submission.

Two metadata updates are available to an `IntakeWorker` once the household exists. A household's `address_line` and `filing_status` may be modified via patch, with optimistic concurrency on `version`. An application's `program` and `rule_variant` may be modified via patch while it is still in `DRAFT`, also with optimistic concurrency on `version`.

### 3.2. Computing MAGI, Assets, and the FPL Percentage

The Modified Adjusted Gross Income (MAGI) for an applicant is the annualized sum of countable income sources. Each `IncomeRecord` is first annualized according to its `frequency`: when the frequency is `ANNUAL` the annualized amount is the `gross_amount` itself; when it is `MONTHLY` the gross amount is multiplied by twelve; when it is `BIWEEKLY` the gross amount is multiplied by twenty-six; when it is `WEEKLY` the gross amount is multiplied by fifty-two. The system then filters each record by `source_type`: the countable set for MAGI is `WAGES`, `SELF_EMPLOYMENT`, `INTEREST`, `DIVIDENDS`, `CAPITAL_GAINS`, `UNEMPLOYMENT`, and `OTHER`. `SOCIAL_SECURITY` is countable only when the owning applicant's `dependent_status` is `PRIMARY` — a dependent's Social Security benefits are excluded from MAGI under federal rule. `CHILD_SUPPORT`, `TANF`, and `SSI` are never countable for MAGI. The applicant's `magi_income` is then the sum of the annualized countable amounts, rounded to two decimal places using the round-half-up rule.

A household's `total_magi` is then derived from its applicants' `magi_income` values, but the precise definition depends on the application's `rule_variant`. Under the `FEDERAL` variant (the **standard MAGI** variant), `total_magi` is the sum of `magi_income` over all `Applicant`s in the household whose `dependent_status` is not `EXCLUDED`, with no state disregard applied. Under the `STATE` variant (the **state-adjusted MAGI** variant), `total_magi` is the maximum of zero and the same sum minus the household's `StatePolicy.state_disregard_amount` — that is, the state disregard is subtracted but the result is floored at zero so that the household's MAGI never becomes negative. Because the two variants produce different `total_magi` values from identical income inputs, they also produce different `snapshot_magi` and `snapshot_fpl_percent` on the resulting application; this is intentional. The variant in effect for any given determination is captured immutably on the resulting `EligibilityDetermination` as `applied_rule_variant`.

Countable assets are likewise variant-dependent. For each `AssetRecord`, the system computes `countable_value` according to the rule variant of the parent `Application` at submission time. Under the **federal exempt set**, only `PRIMARY_RESIDENCE`, `RETIREMENT`, and `LIFE_INSURANCE` are exempt; every other asset type contributes its full `market_value` (so a `CHECKING` balance of, for example, five thousand dollars contributes five thousand dollars in full). Under the **state exempt set**, the exempt set is the federal exempt set unioned with the state's `state_exempt_asset_types`; an asset whose type appears in either set contributes zero, while every other type contributes its full `market_value` (so if the state exempts `VEHICLE`, a twenty-thousand-dollar vehicle contributes zero instead of twenty thousand). The applicant's `countable_assets` is the sum of `countable_value` across that applicant's asset records, and the application's `snapshot_countable_assets` is the sum of `countable_assets` across the household's non-`EXCLUDED` applicants at submission time.

The household's `fpl_percent` is computed in four steps. First, an effective household size is computed as the count of `Applicant`s whose `dependent_status` is not `EXCLUDED`, plus the count of applicants whose `is_pregnant` flag is true (so a pregnant primary is counted twice in the denominator: once for herself and once for the pregnancy). Second, the FPL threshold amount is computed as `fpl_base_amount` plus the quantity (effective size minus one) multiplied by `fpl_per_member_amount`. If the effective size is zero, `fpl_threshold_amount` is set to zero and the eligibility computation is aborted with `ERR_FPL_THRESHOLD_INVALID` (HTTP 422); this protects against division by zero. Third, the total MAGI for the chosen rule variant is divided by `fpl_threshold_amount` and multiplied by one hundred to express it as a percentage of FPL. Fourth, that raw percentage is rounded to two decimal places using the round-half-up rule, and the rounded value is what the system stores as `fpl_percent` and snapshots into `snapshot_fpl_percent`. The eligibility comparison is performed on the rounded value: the household is fiscally eligible when `fpl_percent` is less than or equal to `magi_income_limit_pct` (inclusive at the ceiling).

### 3.3. Application Submission, Adjudication, and Withdrawal

An application is created by an `IntakeWorker` against a parent household. The intake worker supplies the `program` (one of `MAGI_ADULT`, `MAGI_CHILD`, `MAGI_PREGNANT`, `NON_MAGI_DISABILITY`, `NON_MAGI_AGED`) and optionally the `rule_variant`, which defaults to `STATE`. The new application enters `DRAFT`. While the application remains in `DRAFT`, the intake worker may patch its `program` and `rule_variant` (subject to optimistic concurrency on `version`) and may add or remove applicant, income, and asset records as needed.

When the application is ready, the intake worker submits it. Submission transitions the application from `DRAFT` to `UNDER_REVIEW`, but only if four conditions hold: the application is currently in `DRAFT` (otherwise `ERR_INVALID_STATE`); the parent household has its `head_applicant_id` set, at least one non-`EXCLUDED` applicant exists, and the household's `state_code` references an existing `StatePolicy` (otherwise `ERR_HOUSEHOLD_INCOMPLETE`); and the effective household size is non-zero so that `fpl_threshold_amount` is non-zero (otherwise `ERR_FPL_THRESHOLD_INVALID`). On a successful submit, the system captures three immutable snapshots onto the application: `snapshot_magi` (the household's `total_magi` under the chosen rule variant — the state disregard is applied for `STATE`, not applied for `FEDERAL`), `snapshot_fpl_percent` (the household's `fpl_percent` recomputed against the same rule-variant-adjusted total MAGI), and `snapshot_countable_assets` (the sum of `countable_assets` across non-`EXCLUDED` applicants computed under the chosen rule-variant's exempt set). The system also stamps `submitted_at` with the current `clock_now`. From this point on, the snapshots do not change, even if downstream income or asset records are added to the household.

While in `UNDER_REVIEW`, the application awaits adjudication by an `EligibilityCaseworker`. The caseworker decides the application by supplying a `decision` of `APPROVE` or `DENY`, plus — when denying — an optional `ineligibility_reason` chosen from `INCOME_EXCEEDS_LIMIT`, `ASSETS_EXCEED_LIMIT`, `NOT_RESIDENT`, or `NON_QUALIFYING_PROGRAM`. To approve, three preconditions must hold simultaneously: the application is in `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`); the application's `snapshot_fpl_percent` is at most the household's `StatePolicy.magi_income_limit_pct` and — when `asset_test_applies` is true — the `snapshot_countable_assets` does not exceed the per-member ceiling multiplied by the effective household size (otherwise `ERR_NOT_ELIGIBLE`); and the acting caseworker's `X-User-ID` is not the same `X-User-ID` who issued any prior `INELIGIBLE` determination on this application (otherwise `ERR_FORBIDDEN_SAME_ACTOR`, enforcing segregation of duties on re-decisions). On approval, the application transitions to `APPROVED`, the system creates a new `EligibilityDetermination` with `outcome` `ELIGIBLE`, with `applied_rule_variant` copied from the application, with `computed_magi` and `computed_fpl_percent` copied from the application's snapshots, and with `decided_at` stamped as the current `clock_now`. The system then creates one `Enrollment` per non-`EXCLUDED` `Applicant` in the household: `coverage_start` is the current `clock_now`, `coverage_end` is `coverage_start` plus 365 days, `redetermination_due_at` is also `coverage_start` plus 365 days, and `coverage_status` is `ACTIVE`; each enrollment carries `determination_id` referencing the new determination and `applicant_id` referencing its applicant. Each new enrollment's coverage window must not overlap an existing non-`TERMINATED` enrollment on the same `applicant_id` under half-open semantics described in §3.4; an overlap is rejected with `ERR_ENROLLMENT_OVERLAP`. After the enrollments are written, the household's `active_enrollment_count` is recomputed.

To deny, the only precondition is that the application is in `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`). On denial, the application transitions to `DENIED`, the system creates a new `EligibilityDetermination` with `outcome` `INELIGIBLE` and the supplied `ineligibility_reason`, and no enrollments are created. The `X-User-ID` of the deciding caseworker is recorded on the determination for use by the segregation-of-duties checks at later stages.

An application that is still in `DRAFT` or `UNDER_REVIEW` may be withdrawn by an `IntakeWorker`; the application transitions to `WITHDRAWN` and no further activity is permitted against it. A withdrawal attempted on an application in any other state is rejected with `ERR_INVALID_STATE`.

### 3.4. Enrollment Lifecycle and Annual Redetermination

An `Enrollment` is the persistent record of a household member's coverage. Each enrollment carries a `continuous_coverage_flag` that is true precisely when its `coverage_status` is `CONTINUOUS_COVERAGE`. Two new-coverage interval checks are enforced on creation: the new enrollment's `[coverage_start, coverage_end)` window — under half-open semantics, so adjacency (a new `coverage_start` equal to an existing `coverage_end`) does **not** count as overlap — must not overlap any existing enrollment on the same `applicant_id` whose `coverage_status` is in `ACTIVE`, `CONTINUOUS_COVERAGE`, or `REDETERMINATION_DUE`. An overlap is rejected with `ERR_ENROLLMENT_OVERLAP`. Note that this half-open coverage-window semantics is distinct from the closed-interval hearing-overlap check described in §3.6 and applies no time buffer.

A `PolicyAdmin` may suspend an `ACTIVE` enrollment, which transitions it to `SUSPENDED` and decrements the parent household's `active_enrollment_count`. A `SUSPENDED` enrollment may then be reactivated, transitioning it back to `ACTIVE` and incrementing the household's `active_enrollment_count`. Suspend or reactivate attempts on an enrollment in any other state are rejected with `ERR_INVALID_STATE`. The household's `active_enrollment_count` is computed as the count of enrollments whose `applicant_id` belongs to one of the household's applicants and whose `coverage_status` is in the set `{ACTIVE, CONTINUOUS_COVERAGE}`; note that `REDETERMINATION_DUE` does **not** count toward this aggregate (the household is between coverage years until the redetermination is decided), but `CONTINUOUS_COVERAGE` explicitly does.

The annual redetermination is driven by the system clock. Once `clock_now` reaches an enrollment's `redetermination_due_at`, that enrollment becomes eligible to flip to `REDETERMINATION_DUE`. The flip happens not on the instant the clock advances but on the next invocation of the system's redetermination sweep, an admin-only capability that scans every `ACTIVE` enrollment whose `redetermination_due_at` is at or before the current `clock_now`. Each matching enrollment is transitioned to `REDETERMINATION_DUE`, and the system creates a new `Redetermination` record under it with `status` `PENDING`, with `due_date` copied from the enrollment's `redetermination_due_at`, and with the rest of its fields unset; the household's `active_enrollment_count` is then recomputed (decremented for each enrollment that left `ACTIVE`). Enrollments not in `ACTIVE` at sweep time are ignored.

Once a redetermination is `PENDING`, a read of the redetermination returns a premium estimate computed by the calculation described in §3.7. To resolve the redetermination, an `EligibilityCaseworker` submits a decision against it. The submission carries a `decision` of `RENEW` or `TERMINATE` and a `new_snapshot_magi` value capturing the household's updated annualized MAGI for the renewal year. At submit time, the system computes `new_snapshot_fpl_percent` using the household's current `fpl_threshold_amount` and the supplied `new_snapshot_magi`, rounded to two decimal places using the round-half-up rule, and stores it on the redetermination. To renew, the redetermination must be `PENDING` (otherwise `ERR_INVALID_STATE`), and `new_snapshot_fpl_percent` must satisfy MAGI eligibility against the current `StatePolicy.magi_income_limit_pct` — that is, be less than or equal to the ceiling — (otherwise `ERR_NOT_ELIGIBLE`). The renewed enrollment's `coverage_start` is reset to the current `clock_now`, its `coverage_end` is reset to `coverage_start` plus 365 days, its `redetermination_due_at` is reset to `coverage_start` plus 365 days, and its `coverage_status` is set back to `ACTIVE`, closing the cyclic redetermination loop; the redetermination's `status` and `decision` are both set to `RENEWED`. To terminate, the redetermination must also be `PENDING` (otherwise `ERR_INVALID_STATE`), and either `new_snapshot_fpl_percent` fails the eligibility check or the submission is past a 90-day grace from the redetermination's `due_date`; on termination, the redetermination's `status` is set to `TERMINATED`, its `decision` is set to `TERMINATED`, the enrollment's `coverage_status` is set to `TERMINATED`, and the household's `active_enrollment_count` is decremented.

A redetermination that is still `PENDING` may also be withdrawn by an `IntakeWorker` — for example, if the caseworker created it in error. The redetermination transitions to `WITHDRAWN` and the parent enrollment's `coverage_status` is left untouched (the system will re-create a new `PENDING` redetermination on the next sweep if the enrollment is still due). Crucially, an applicant's `redetermination_count_this_year` excludes withdrawn redeterminations: it counts distinct redetermination rows tied to the applicant whose `status` is in `PENDING`, `SUBMITTED`, `RENEWED`, or `TERMINATED` and whose `due_date` falls in the calendar year equal to the household's `StatePolicy.fpl_year`. The result is that a withdraw-then-resubmit pair against the same applicant leaves the counter unchanged across the pair.

### 3.5. The Public Health Emergency Overlay

When a `PolicyAdmin` issues an `EmergencyDeclaration`, the system's continuous-coverage protection kicks in. The declaration's `scope` selects which enrollments are affected: a `FEDERAL` declaration covers every enrollment regardless of state, while a `STATE` declaration covers only enrollments whose parent household's `state_code` equals the declaration's `state_code`. For each covered `Enrollment` whose `coverage_status` is currently `ACTIVE` or `REDETERMINATION_DUE`, the system transitions the `coverage_status` to `CONTINUOUS_COVERAGE` and sets `continuous_coverage_flag` to true. If the covered enrollment was in `REDETERMINATION_DUE` at the moment of the flip, the system also withdraws any associated `PENDING` `Redetermination` on that enrollment — its `status` is set to `WITHDRAWN`. The household's `active_enrollment_count` is recomputed across every affected household; since `CONTINUOUS_COVERAGE` counts as active and `REDETERMINATION_DUE` does not, an enrollment moving from `REDETERMINATION_DUE` to `CONTINUOUS_COVERAGE` increments the count, while an enrollment moving from `ACTIVE` to `CONTINUOUS_COVERAGE` leaves it unchanged.

Continuous coverage persists for as long as at least one covering emergency declaration remains `ACTIVE`. When the logical clock advances past the `expires_at` of the last covering declaration, the affected enrollments revert: `continuous_coverage_flag` is set back to false and `coverage_status` is set back to `ACTIVE`. If the enrollment's `redetermination_due_at` is in the past at the time of revert, the very next redetermination sweep will move it back to `REDETERMINATION_DUE` and create a fresh `PENDING` redetermination — so an emergency may delay but does not erase the annual review obligation.

A `StatePolicy`'s `emergency_continuous_active` flag exposes this overlay to read-side consumers: it is true whenever an `EmergencyDeclaration` with `scope` `FEDERAL`, or with `scope` `STATE` and matching `state_code`, has `status` `ACTIVE` at the current `clock_now`, and false otherwise.

### 3.6. The Appeals Path: Filing, Scheduling, Hearing, and Ruling

A household that receives an `INELIGIBLE` determination may contest it. An `IntakeWorker` files an `Appeal` by submitting an `Appeal` against the determination, supplying `determination_id` in the body. Two preconditions guard the filing: the associated `Application` must be `DENIED` (an attempt to appeal an `APPROVED`, `WITHDRAWN`, or otherwise non-`DENIED` application is rejected with `ERR_INVALID_STATE`); and the filing must occur strictly within 90 days of the underlying determination — that is, the current `clock_now` must be less than the determination's `decided_at` plus 90 days — otherwise the filing is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. The system also enforces at most one appeal per `determination_id`: a second filing against the same determination, even if filed within the window, is rejected with `ERR_APPEAL_ALREADY_EXISTS`. On a successful filing, the new appeal's `filed_at` is stamped as the current `clock_now`, its `deadline_at` is stamped as `filed_at` plus 90 days (the latest a hearing may begin), its `status` is set to `FILED`, and the associated `Application` is moved from `DENIED` into `APPEALED`.

An `AppealsOfficer` then schedules a fair hearing. Scheduling requires the appeal to be in `FILED` (otherwise `ERR_INVALID_STATE`), supplies the `officer_id` who will hear it, and supplies `scheduled_start` and `scheduled_end` instants. The `scheduled_start` must be before the appeal's `deadline_at` — a hearing scheduled to begin at or after the deadline is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. The `scheduled_start` must be strictly before `scheduled_end`, and both instants must be in the future relative to `clock_now` at scheduling time; a violation is rejected with `ERR_HEARING_NOT_DUE`. The new hearing's interval must not collide with another `SCHEDULED` `FairHearing` for the same `officer_id`. The overlap check uses closed-interval semantics with a 30-minute buffer applied **to the new hearing's interval on both sides**: the new interval is treated as `[scheduled_start - 30 minutes, scheduled_end + 30 minutes]`, while each existing `SCHEDULED` hearing's interval is taken as `[scheduled_start, scheduled_end]` with no buffer applied to the existing side; the new buffered interval and the existing un-buffered interval are checked for closed-closed intersection. Equivalently, the scheduling is rejected when both of the following hold: the new `scheduled_start` minus 30 minutes is less than or equal to the existing `scheduled_end`, and the existing `scheduled_start` is less than or equal to the new `scheduled_end` plus 30 minutes. A collision is rejected with `ERR_HEARING_CONFLICT`. Finally, the acting `AppealsOfficer`'s `X-User-ID` must differ from the `X-User-ID` of the `EligibilityCaseworker` who issued the appealed `EligibilityDetermination`; a same-actor violation is rejected with `ERR_FORBIDDEN_SAME_ACTOR`. On a successful schedule, the system creates a new `FairHearing` record with `status` `SCHEDULED`, copies the officer onto the appeal as `Appeal.officer_id`, and moves the appeal from `FILED` to `HEARING_SCHEDULED`.

Holding the hearing is the next step. An `AppealsOfficer` marks the fair hearing as held; this requires the hearing to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and `clock_now` to be at or after the hearing's `scheduled_start` (otherwise `ERR_HEARING_NOT_DUE`). On a successful hold, the hearing's `status` becomes `HELD` and the linked appeal moves from `HEARING_SCHEDULED` to `UNDER_REVIEW`.

Once the appeal is in `UNDER_REVIEW`, the `AppealsOfficer` rules. Granting an appeal requires the appeal to be in `UNDER_REVIEW`, requires the associated fair hearing to be in `HELD` (otherwise either precondition failure yields `ERR_INVALID_STATE`), and accepts an optional `outcome_reason` recording a free-text rationale. On grant, the system performs a deterministic three-hop cascade in order: hop one — the appealed `EligibilityDetermination`'s `outcome` is set to `OVERTURNED`, refreshing its `updated_at` and incrementing its `version`; hop two — the associated `Application` moves from `APPEALED` to `UNDER_REVIEW` for re-decision (this is cyclic — the application may then transition once more to `APPROVED` or `DENIED`, and the caseworker re-deciding it must, per the same-actor rule, differ from any prior caseworker who denied it); hop three — when a subsequent decision approves the application, enrollments are created in the manner described in §3.3 and the household's `active_enrollment_count` is recomputed. Upholding the appeal also requires the appeal to be in `UNDER_REVIEW` and the fair hearing to be in `HELD` (otherwise `ERR_INVALID_STATE`) and likewise accepts an optional `outcome_reason`; on uphold, the determination's outcome stays `INELIGIBLE`, the application stays `DENIED`, and the appeal moves to `UPHELD`.

An `IntakeWorker` may withdraw the appeal while it is still `FILED` or `HEARING_SCHEDULED` (any other state is rejected with `ERR_INVALID_STATE`); the appeal moves to `WITHDRAWN`, and if a `SCHEDULED` fair hearing exists, its `status` is set to `CANCELLED` as an automatic linked side effect (no separate request is needed).

### 3.7. The Redetermination Premium Estimate

A `PENDING` `Redetermination` exposes an informational premium estimate via its read endpoint — the dollar amount the household would be asked to pay for reduced cost-sharing if the renewal were approved. This estimate is computed deterministically with a fixed rounding order: per-member values are rounded first, then summed.

For each non-`EXCLUDED` `Applicant` in the enrollment's household, the system computes three intermediate values. First, the applicant's age in whole years is derived from `date_of_birth` evaluated at the current `clock_now`. Second, an age factor is derived: when the applicant's age is less than the floor of 18 years, the age factor is 1.0 exactly; otherwise, the age factor is 1.0 plus the quantity (the lesser of the applicant's age and the ceiling of 64 years, minus 18) multiplied by a per-year increment of 0.02. Equivalently, an 18-year-old contributes a factor of 1.0, a 19-year-old contributes 1.02, and the factor caps at 1.92 once the applicant has reached 64 years. Third, a share factor is derived from the redetermination's `new_snapshot_fpl_percent`: the share factor is the maximum of zero and the quantity (`new_snapshot_fpl_percent` minus 100) divided by 100. Households whose new FPL percentage is at or below 100 therefore have a share factor of zero and contribute nothing.

The per-member premium for each applicant is the product of the age factor, the share factor, and a base premium of 30.00 dollars per FPL unit. Each per-member premium is rounded individually to two decimal places using the round-half-up rule. The total premium estimate is then the sum of the rounded per-member values; the final sum is rounded again to two decimal places using the round-half-up rule (a no-op once the inputs are already at two decimals, but specified explicitly to leave no ambiguity). This ordering is pinned: per-member values are rounded first, then summed. The alternative order — summing unrounded per-member values and rounding the final total once — produces a different cents value on some inputs and is not permitted.

## 4. Endpoint Definitions

Resource-creating endpoints return HTTP 201 with the newly created resource in `data`. Endpoints that modify or transition an existing resource — including patches, all named state-transition actions, the bulk sweep, and the clock-advance — return HTTP 200 with the updated resource (or an empty object, for the sweep and clock-advance). Read-only endpoints return HTTP 200. The table below summarizes every endpoint exposed by the API. Request and response bodies are governed by the narrative in §3 — readers must refer back to that section to reconstruct the full payload contract for each endpoint.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /state-policies | Create a `StatePolicy` for a `(state_code, fpl_year)` pair. | PolicyAdmin |
| GET | /state-policies/:state_code | Retrieve a `StatePolicy` by `state_code`. | PolicyAdmin, IntakeWorker, EligibilityCaseworker, AppealsOfficer |
| POST | /emergency-declarations | Issue an `EmergencyDeclaration`; cascades to flip eligible enrollments to `CONTINUOUS_COVERAGE`. | PolicyAdmin |
| GET | /emergency-declarations/:declaration_id | Retrieve an `EmergencyDeclaration`. | PolicyAdmin, IntakeWorker, EligibilityCaseworker, AppealsOfficer |
| GET | /emergency-declarations | List `EmergencyDeclaration`s; supports a `status` filter. | PolicyAdmin, IntakeWorker, EligibilityCaseworker, AppealsOfficer |
| POST | /households | Create a `Household`. | IntakeWorker |
| GET | /households/:household_id | Retrieve a `Household` with its computed fields. | IntakeWorker, EligibilityCaseworker, PolicyAdmin |
| PATCH | /households/:household_id | Update the household's `address_line` and/or `filing_status`; OCC via `version`. | IntakeWorker |
| POST | /households/:household_id/applicants | Create an `Applicant`; the first non-`EXCLUDED` applicant fills `head_applicant_id`. | IntakeWorker |
| GET | /households/:household_id/applicants/:applicant_id | Retrieve an `Applicant`. | IntakeWorker, EligibilityCaseworker, PolicyAdmin |
| POST | /households/:household_id/applicants/:applicant_id/income | Append an immutable `IncomeRecord`. | IntakeWorker |
| POST | /households/:household_id/applicants/:applicant_id/assets | Append an immutable `AssetRecord`. | IntakeWorker |
| POST | /households/:household_id/applications | Create an `Application` in `DRAFT`. | IntakeWorker |
| GET | /households/:household_id/applications/:application_id | Retrieve an `Application`. | IntakeWorker, EligibilityCaseworker, AppealsOfficer |
| PATCH | /households/:household_id/applications/:application_id | Update the application's `rule_variant` and/or `program` while in `DRAFT`; OCC via `version`. | IntakeWorker |
| POST | /households/:household_id/applications/:application_id/submit | Submit the application; computes snapshots and moves `DRAFT` to `UNDER_REVIEW`. | IntakeWorker |
| POST | /households/:household_id/applications/:application_id/decide | Decide an `UNDER_REVIEW` application; APPROVE creates enrollments, DENY records ineligibility. | EligibilityCaseworker |
| POST | /households/:household_id/applications/:application_id/withdraw | Withdraw an application from `DRAFT` or `UNDER_REVIEW`. | IntakeWorker |
| GET | /enrollments/:enrollment_id | Retrieve an `Enrollment`. | IntakeWorker, EligibilityCaseworker, PolicyAdmin |
| GET | /enrollments | List `Enrollment`s; supports `applicant_id` and `coverage_status` filters. | IntakeWorker, EligibilityCaseworker, PolicyAdmin |
| POST | /enrollments/:enrollment_id/suspend | Suspend an `ACTIVE` enrollment. | PolicyAdmin |
| POST | /enrollments/:enrollment_id/reactivate | Reactivate a `SUSPENDED` enrollment. | PolicyAdmin |
| GET | /redeterminations/:redetermination_id | Retrieve a `Redetermination`; returns the premium estimate when `PENDING`. | IntakeWorker, EligibilityCaseworker, PolicyAdmin |
| POST | /redeterminations/:redetermination_id/submit | Submit a redetermination decision; RENEW renews the enrollment, TERMINATE ends coverage. | EligibilityCaseworker |
| POST | /redeterminations/:redetermination_id/withdraw | Withdraw a `PENDING` redetermination. | IntakeWorker |
| POST | /appeals | File an `Appeal` against an `INELIGIBLE` determination. | IntakeWorker |
| GET | /appeals/:appeal_id | Retrieve an `Appeal`. | IntakeWorker, EligibilityCaseworker, AppealsOfficer, PolicyAdmin |
| POST | /appeals/:appeal_id/schedule-hearing | Schedule a `FairHearing` for the appeal. | AppealsOfficer |
| POST | /appeals/:appeal_id/grant | Grant the appeal; cascades to overturn the determination and re-open the application. | AppealsOfficer |
| POST | /appeals/:appeal_id/uphold | Uphold the original denial. | AppealsOfficer |
| POST | /appeals/:appeal_id/withdraw | Withdraw a `FILED` or `HEARING_SCHEDULED` appeal; cancels any `SCHEDULED` hearing. | IntakeWorker |
| GET | /fair-hearings/:fair_hearing_id | Retrieve a `FairHearing`. | IntakeWorker, EligibilityCaseworker, AppealsOfficer, PolicyAdmin |
| POST | /fair-hearings/:fair_hearing_id/hold | Mark the fair hearing as `HELD`; gates the appeal grant and uphold actions. | AppealsOfficer |
| POST | /_clock/advance | Advance the logical clock to the supplied `to` instant; cascades emergency expiry and continuous-coverage revert. | PolicyAdmin |
| POST | /_sweep/redeterminations | Run the auto-redetermination sweep across all due `ACTIVE` enrollments. | PolicyAdmin |

## 5. Error Code Catalogue

The following error identifiers are returned in the standard error envelope's `data.error_id` field. Trigger conditions for each error are described in §2 and §3 in the narrative paragraphs nearest the rule they guard.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_FORBIDDEN_SAME_ACTOR | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_HOUSEHOLD_INCOMPLETE | 409 |
| ERR_APPEAL_WINDOW_EXPIRED | 409 |
| ERR_APPEAL_ALREADY_EXISTS | 409 |
| ERR_HEARING_CONFLICT | 409 |
| ERR_HEARING_NOT_DUE | 409 |
| ERR_ENROLLMENT_OVERLAP | 409 |
| ERR_NOT_ELIGIBLE | 422 |
| ERR_FPL_THRESHOLD_INVALID | 422 |

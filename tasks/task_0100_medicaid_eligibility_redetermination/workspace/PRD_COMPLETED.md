# Medicaid Eligibility Redetermination API — Product Requirements Document

## 1. Introduction

Medicaid eligibility is one of the most procedurally intricate determinations a public benefits agency makes. A single household's coverage depends on its income measured through the Modified Adjusted Gross Income (MAGI) methodology, on the federal poverty guidelines for the relevant year and household size, on whether the household's state adopted the ACA Medicaid expansion, and — for aged, blind, and disabled applicants — on a non-MAGI asset test with its own exemption rules. This API provides the backend system of record that codifies those rules so that eligibility, enrollment, annual redetermination, and the appeals process are computed and tracked consistently across states.

The system models the full lifecycle of a case: a household assembles its members, income sources, and assets; an application is filed, verified, and run through an eligibility determination; an approved application becomes an active enrollment; that enrollment is revisited each year through a redetermination; and an adverse redetermination may be challenged through a fair hearing before an independent hearing officer. Two cross-cutting financial integrity concerns thread through the whole lifecycle: a conserved member-month ledger that must reconcile exactly after every coverage change, and an emergency continuous-coverage directive that can freeze terminations state-wide during a declared public health emergency. The remainder of this document specifies the global contracts every endpoint shares, the business rules that govern each workflow, the full endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. The system recognizes exactly three roles, spelled precisely as `Applicant`, `CaseWorker`, and `HearingOfficer`. A request that omits either header, or that supplies an `X-User-Role` value that is not one of these three declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request that is authenticated but whose role is not permitted to invoke the targeted endpoint per the role matrix is rejected with `ERR_FORBIDDEN`.

All three roles carry an **opaque** identity. When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `CaseWorker`, `X-User-ID` is likewise an opaque identifier; the server records it where a transition writes it — for example, it is stored as `assigned_caseworker_id` on the `Application` when a caseworker claims that application for review — but it is never compared to any entity's `id`. When `X-User-Role` is `HearingOfficer`, `X-User-ID` is again an opaque identifier; the server records it as `adjudicator_id` on the `Appeal` when the officer hears the appeal, and it is compared only against the stored `assigned_caseworker_id` to enforce segregation of duties, never against any entity's `id`. These recorded operator identifiers are the basis of the segregation-of-duties rule described in §3: the hearing officer who hears an appeal must be a different person than the caseworker who took the underlying application under review.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. A `limit` below 1 or above 100, an `offset` below 0, or a non-integer value for either parameter is rejected with `ERR_INVALID_REQUEST` at HTTP 422. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, every list endpoint returns its resources sorted by their `created_at` timestamp in ascending order; ties on identical `created_at` timestamps are broken by ascending insertion order so the ordering is deterministic.

List responses carry the pagination bookkeeping inside the `meta` object of the envelope, specifically the fields `limit`, `offset`, `total_count`, and `has_more`. The `total_count` is the number of items matching the request before pagination, and `has_more` is true exactly when `offset` plus the number of items returned on this page is less than `total_count`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, and the `version` field is an integer that begins at 1 on creation and increments by one with every mutation of the resource. On creation `updated_at` equals `created_at`. These last two fields support the optimistic-concurrency mechanism described in §2.8.

There is one deliberate exception. The `FplSchedule` resource is immutable after creation: it carries only `id` and `created_at`, and it has neither an `updated_at` field nor a `version` field. All other resources — `StateRule`, `Household`, `HouseholdMember`, `IncomeSource`, `Asset`, `Application`, `EligibilityDetermination`, `Enrollment`, `Redetermination`, and `Appeal` — carry the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Hierarchical Consistency and Cascading Coverage Changes

Many operations in this domain mutate more than one resource at once, and the system keeps the affected resources mutually consistent. When the server transitions a resource as a downstream consequence of another action — for instance, finalizing a redetermination that drives its parent enrollment from one coverage state to another, or an overturned appeal that reinstates a terminated enrollment — each affected resource independently has its `updated_at` refreshed and its `version` incremented as part of that mutation. The server performs these cascades automatically: a caseworker does not separately request the parent enrollment's transition, because the redetermination's outcome already implies it.

Several of these cascades also move conserved ledger quantities on the owning `Household`; those rules are concentrated in §2.6 below, and the precise transition pairs and their triggers are narrated in §3.

### 2.6. The Member-Month Ledger and Conserved Quantities

Each `Household` carries two computed, conserved ledger fields that the system maintains as an exact reflection of that household's coverage state. The first, `covered_member_months`, is the cumulative count of member-months of active coverage credited to the household; it starts at zero. The second, `active_enrollment_count`, is the number of the household's enrollments currently in coverage, and it likewise starts at zero.

These two quantities obey two invariants that must hold exactly after every cascade has settled. The first invariant: `covered_member_months` always equals the sum of `member_months` over the household's enrollments whose `coverage_status` is either `ACTIVE` or `IN_REDETERMINATION`. The second invariant: `active_enrollment_count` always equals the count of the household's enrollments whose `coverage_status` is either `ACTIVE` or `IN_REDETERMINATION`. Both are integer quantities.

The defining property of this ledger is conservation. When an enrollment is activated, its `member_months` quantity is credited to `covered_member_months` and the active count rises by one. When that enrollment is terminated, the very same `member_months` quantity is debited back out and the active count falls by one. When a terminated enrollment is reinstated through a successful appeal, the same `member_months` quantity is re-credited and the active count rises by one again — restoring the earlier debit so that the ledger experiences net-zero drift across a termination-then-reinstatement cycle. The concrete `member_months` value an enrollment carries is fixed at the moment it first becomes active; §3 specifies how it is computed.

### 2.7. Determination Precision and Rounding

The MAGI income calculation and the asset calculation both operate entirely in integer cents, and every rounding step uses the round-half-up method. Two places in the MAGI calculation require rounding, and their order is pinned: each member's income is annualized and rounded to whole cents first, on a per-member basis, and only then are the rounded per-member amounts summed for the household — this is round-then-sum, never sum-then-round. The 5% federal-poverty-level income disregard is rounded half-up exactly once, applied to the household total at the very end. The federal-poverty-level percentage is computed as a floor to a whole-number percent. The asset calculation works in integer cents with no fractional rounding. The exact formulas, their constants, and their boundary comparisons are given in §3.

### 2.8. Optimistic Concurrency Control on Enrollment-Superseding Creates

Two create operations supersede the coverage state of an existing enrollment, and both are guarded by optimistic concurrency control against the parent `Enrollment`'s `version`. The mechanism is framed entirely in terms of stale views, not simultaneity.

The first is opening an annual redetermination. A request to open a redetermination must carry `expected_enrollment_version`, a non-optional field whose value is the enrollment `version` the client last observed. If another writer has advanced the enrollment's `version` since then — for example, a prior request already opened a redetermination and moved the enrollment from `ACTIVE` to `IN_REDETERMINATION`, bumping its `version` — then the supplied `expected_enrollment_version` no longer matches the enrollment's current `version`, the client is acting on a stale view, and the create is rejected with `ERR_STALE_VERSION` at HTTP 412.

The second is filing an appeal. A request to file an appeal must also carry `expected_enrollment_version` carrying the client's last-observed enrollment `version`. Because coverage mutations such as termination and reinstatement bump the enrollment's `version`, a request whose `expected_enrollment_version` no longer matches the enrollment's current `version` reflects a stale view of the coverage state and is rejected with `ERR_STALE_VERSION` at HTTP 412. No other endpoint accepts or requires a version field.

### 2.9. Nested Resource Retrieval and Validation Ordering

When an endpoint path contains a resource identifier — for example, a member under a household, or an income source under a member — the system validates the existence of each referenced resource left to right through the path and then through the body, rejecting the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. Body foreign-key references are validated the same way after the path resolves. Because a body foreign-key cannot be looked up until it has been read off the body, the body well-formedness checks for an endpoint whose foreign keys arrive in the body (the `POST /enrollments`, `POST /redeterminations`, and `POST /appeals` creates) run on the full body before those body foreign-key existence checks; a body that is missing a required field, supplies a wrong-typed value, carries an invalid enum member, or supplies a negative integer where a non-negative value is required is therefore rejected with `ERR_INVALID_REQUEST` before any body foreign-key resolves to `ERR_NOT_FOUND`. Path-identifier existence, by contrast, is always checked before any body well-formedness or body foreign-key check.

This existence check sits within a fixed global ordering of validations that every endpoint observes. Authentication is checked first: missing or undeclared headers yield `ERR_UNAUTHENTICATED`. Authorization is checked second: a role not permitted for the endpoint yields `ERR_FORBIDDEN`. Existence of all path and body foreign-key resources is checked third, left to right, yielding `ERR_NOT_FOUND`. Request well-formedness is checked fourth: a body missing a required field, carrying an invalid enum member, or supplying a negative integer where a non-negative value is required yields `ERR_INVALID_REQUEST` at HTTP 422. Only after these four universal gates pass does the system evaluate the state, concurrency, and business rules specific to each endpoint, in the priority order detailed in §3.

## 3. Business Logic & Workflows

### 3.1. Configuration: State Rules and Poverty Schedules

Before any household can be evaluated, the agency configures two kinds of reference data, both managed exclusively by a `CaseWorker`.

A **state rule** captures everything the eligibility math needs to know about one state. It is keyed by `state_code`, a two-letter uppercase code such as `CA` that must be unique across all state rules and exactly two characters long. The `is_expansion_state` boolean records whether the state adopted the ACA Medicaid expansion. Two percentage ceilings drive MAGI eligibility: `magi_adult_threshold_pct` is the federal-poverty-level percentage ceiling for adult eligibility (for example 138 in an expansion state or 100 in a non-expansion state), and `magi_child_threshold_pct` is the ceiling for child eligibility (for example 200). Two cents-denominated limits drive the non-MAGI asset test: `abd_asset_limit_cents` is the countable-asset ceiling for the aged, blind, and disabled pathway (for example 200000, i.e. $2000), and `standard_asset_limit_cents` is the ceiling for non-disabled non-MAGI households. Finally, `continuous_coverage_active` records whether an emergency public-health-emergency continuous-coverage directive is currently in force for the state; it defaults to false, and while it is true the state's terminations are frozen as described in §3.7. A caseworker may later adjust the mutable fields of a state rule — toggling `continuous_coverage_active`, or revising `is_expansion_state`, `magi_adult_threshold_pct`, `magi_child_threshold_pct`, `abd_asset_limit_cents`, or `standard_asset_limit_cents` — through an update that targets the state by its `stateCode` path parameter.

An **FPL schedule** captures the federal poverty guidelines for one guideline year. It is keyed by `year`, which must be unique across all schedules, and it carries `base_annual_cents`, the 100% federal-poverty-level annual income in cents for a household of one, and `per_member_increment_cents`, the additional 100% federal-poverty-level annual income in cents added for each household member beyond the first. An FPL schedule is reference data that is never modified once created.

### 3.2. Building a Household: Members, Income, and Assets

An `Applicant` or a `CaseWorker` opens a case by creating a **household**, supplying the governing `state_code` (which must name an existing state rule), the `fpl_year` (which must name an existing FPL schedule), and the `primary_applicant_name` of the person filing on the household's behalf. A freshly created household starts with `household_size` at zero, `covered_member_months` at zero, and `active_enrollment_count` at zero. The `household_size` is never supplied by a client; it is always the computed count of the household's members whose `member_status` is `COUNTED`.

Members are added to a household one at a time, again by an `Applicant` or a `CaseWorker`. Each **household member** is created with a `full_name`, an `age` in whole years that must be zero or greater, and a `relationship` drawn from `SELF`, `SPOUSE`, `CHILD`, `DEPENDENT`, or `OTHER`. The optional `is_disabled` flag marks whether the member qualifies for the aged, blind, and disabled non-MAGI pathway and defaults to false. Every member also carries a server-managed `member_status` that is `COUNTED` on creation and may later become `EXCLUDED`; the permitted values are exactly `COUNTED` and `EXCLUDED`. The `household_id` that ties a member to its household is set by the server from the path, never supplied in the body. Adding a member recomputes the household's `household_size`. A `CaseWorker` may later exclude a member; doing so sets that member's `member_status` to `EXCLUDED` and recomputes `household_size`. An excluded member contributes neither to `household_size` nor to the household's MAGI.

Income is attached to individual members. An `Applicant` or `CaseWorker` adds an **income source** to a member by supplying an `income_type` — one of `WAGES`, `SELF_EMPLOYMENT`, `SOCIAL_SECURITY`, `CHILD_SUPPORT`, `TANF`, or `GIFT` — and a `monthly_amount_cents` that must be zero or greater. Whether the source counts toward MAGI is not supplied by the client; the server derives the `is_magi_countable` flag from the `income_type`, treating `CHILD_SUPPORT`, `TANF`, and `GIFT` as non-countable and every other type as countable. The optional `projected_annual_cents` supplies the reasonably-predictable annual figure used by the projected-annual MAGI variant; when it is omitted, the server defaults it to the `monthly_amount_cents` multiplied by twelve. The `member_id` linking the income source to its earning member is set by the server from the path.

Assets are attached to the household as a whole. An `Applicant` or `CaseWorker` adds an **asset** by supplying an `asset_type` — one of `CASH`, `BANK_ACCOUNT`, `VEHICLE`, `HOME`, `RETIREMENT`, or `BURIAL_FUND` — and a `value_cents` fair-market value that must be zero or greater. The server derives two fields at creation time and keeps them on the asset: `is_exempt` records whether the asset is shielded from the asset test, and `countable_value_cents` records how much of the asset's value counts. The exemption logic mirrors the asset calculation of §3.6: a `HOME` is fully exempt, one `VEHICLE` is exempt, and a `BURIAL_FUND` is exempt up to a cap with any excess counting; everything else counts in full. A `BURIAL_FUND` whose value exceeds the cap has any excess counting, so its `is_exempt` is false (it is only partially shielded) while its `countable_value_cents` is that excess. Because the exempt `VEHICLE` is the single highest-value one across the household, adding a new asset recomputes `is_exempt` and `countable_value_cents` across every asset of the household — so an existing vehicle's derived fields can change when another vehicle is added — and the recomputation does not bump those existing assets' `updated_at` or `version`. The `household_id` tying an asset to its household is set by the server from the path. The asset's `countable_value_cents` is its `value_cents` when nothing is exempted, and otherwise the non-exempt remainder, which is zero for a fully exempt asset.

### 3.3. The Application: Two Parallel Lifecycles

A case is adjudicated through an **application**, opened against a household by an `Applicant` or a `CaseWorker`. At creation the applicant chooses the `pathway` — `MAGI` for the income test or `NON_MAGI` for the asset test — and optionally the `magi_variant`, which selects which MAGI algorithm to run and is one of `POINT_IN_TIME` or `PROJECTED_ANNUAL`, defaulting to `POINT_IN_TIME`. The `household_id` is taken from the path.

An application advances along two independent state dimensions that live on the same record and evolve separately. The first is `review_status`, which begins at `DRAFT`. The second is `verification_status`, which begins at `UNVERIFIED`. Neither dimension's progress constrains the other except where a decision explicitly requires verification to be complete.

On the **review** dimension, an `Applicant` submits a `DRAFT` application, advancing `review_status` from `DRAFT` to `SUBMITTED`. Submission is only permitted while `review_status` is `DRAFT`, and it requires that the household have at least one member whose `member_status` is `COUNTED`; a submission against a household with no counted member is rejected with `ERR_EMPTY_HOUSEHOLD`. A `CaseWorker` then claims a `SUBMITTED` application for review, advancing `review_status` from `SUBMITTED` to `UNDER_REVIEW`; this claim is permitted only while `review_status` is `SUBMITTED`, and it pins the acting caseworker's `X-User-ID` into the application's `assigned_caseworker_id` to anchor the later segregation-of-duties check. Finally, a `CaseWorker` decides an application that is `UNDER_REVIEW`, supplying a `target_status` that drives `review_status` to either `APPROVED` or `DENIED`. A decision is permitted only while `review_status` is `UNDER_REVIEW`, and in either direction it requires `verification_status` to have reached `VERIFIED`; deciding before verification completes is rejected with `ERR_NOT_VERIFIED`. Approval additionally requires that an eligibility determination already exist for the application whose `decision` is `ELIGIBLE` — it is sufficient that at least one of the application's determinations is `ELIGIBLE`, regardless of which is most recent; an approval attempted without any such determination is rejected with `ERR_NO_ELIGIBLE_DETERMINATION`. A denial, by contrast, imposes no determination precondition: once the application is `UNDER_REVIEW` and `VERIFIED`, deciding to `DENIED` always succeeds, whether or not any determination exists and regardless of any determination's `decision`.

On the **verification** dimension, a `CaseWorker` may request documents from an `UNVERIFIED` application, advancing `verification_status` from `UNVERIFIED` to `DOCS_REQUESTED`; this is permitted only while `verification_status` is `UNVERIFIED`. A caseworker marks verification complete by advancing to `VERIFIED`: this is permitted either from `DOCS_REQUESTED` (the ordinary path, after documents were requested) or directly from `UNVERIFIED` (when no document request was needed). Both of these verify transitions land at `VERIFIED`; the only difference is the originating state, and each is permitted only when the application currently sits in its respective originating state.

### 3.4. Running an Eligibility Determination — the MAGI Income Test

A `CaseWorker` runs an **eligibility determination** against an application, producing a persisted determination snapshot that records how the household measured against the rules at that moment. The determination copies the application's `pathway` onto its own `pathway` field and snapshots the result through several computed fields: `magi_annual_cents`, `fpl_percentage`, `countable_assets_cents`, `applicable_threshold_pct`, `decision`, and `decision_reason`. Each determination references its originating application through `application_id`, set by the server. The determination's `decision` is `ELIGIBLE` or `INELIGIBLE`, and its `decision_reason` is one of `INCOME_UNDER_THRESHOLD`, `INCOME_OVER_THRESHOLD`, `ASSETS_UNDER_LIMIT`, or `ASSETS_OVER_LIMIT`.

For an application on the `MAGI` pathway, the determination first computes annual MAGI income. The countable members are exactly those household members whose `member_status` is `COUNTED`. For each such member, the system gathers that member's income sources whose `is_magi_countable` is true and computes that member's annualized income. Under the `POINT_IN_TIME` variant, the member's annual figure is the sum of the `monthly_amount_cents` across those countable sources multiplied by twelve, then rounded half-up to whole cents. Under the `PROJECTED_ANNUAL` variant, the member's annual figure is instead the sum of the `projected_annual_cents` across those countable sources, rounded half-up to whole cents; because projected figures need not equal twelve times the monthly amounts, the same household can yield a different total under each variant. The per-member rounded figures are then summed across all counted members to give the household's gross annual income — the rounding happens per member before this summation, never after.

A 5% federal-poverty-level income disregard is then applied once to the household total. The disregard amount is five percent of the household's 100%-FPL base income for its size, computed as the `base_annual_cents` plus the `per_member_increment_cents` multiplied by one fewer than the household size — where the household size used in this base computation is floored at one, so a household with zero counted members is treated as size one (base income `base_annual_cents`, with no increment) — and that five-percent product is rounded half-up to whole cents. The household's annual MAGI is the gross annual income minus this rounded disregard; if that subtraction would go below zero, the annual MAGI is held at zero. This final figure is stored as `magi_annual_cents`. For a `NON_MAGI` application this field is null.

### 3.5. The FPL Percentage and the Income Eligibility Decision

Immediately after the annual MAGI is known, the determination converts it to a percentage of the federal poverty level and reaches an income decision. The federal-poverty-level base for the household is the schedule's `base_annual_cents` plus the `per_member_increment_cents` multiplied by one fewer than the household size, with the same size-floored-at-one rule used for the disregard base. The `fpl_percentage` is then the household's annual MAGI multiplied by one hundred, divided by that base, and floored to a whole-number percent; in the degenerate case where that base is zero, `fpl_percentage` is recorded as 0. For a `NON_MAGI` application both `fpl_percentage` and the threshold are null.

The applicable threshold depends on the household's composition. A household is treated as an **adult** household — and therefore measured against `magi_adult_threshold_pct` — when at least one of its counted members has a `relationship` of `SELF`, `SPOUSE`, `OTHER`, or `DEPENDENT` and an `age` of at least 19. A household with no such member is an all-child household and is measured against `magi_child_threshold_pct`. The chosen ceiling is recorded as `applicable_threshold_pct`. The household is eligible on income when its `fpl_percentage` is less than or equal to the `applicable_threshold_pct` — the boundary is inclusive, so a percentage exactly equal to the ceiling is eligible. When eligible, `decision` is `ELIGIBLE` and `decision_reason` is `INCOME_UNDER_THRESHOLD`; otherwise `decision` is `INELIGIBLE` and `decision_reason` is `INCOME_OVER_THRESHOLD`.

### 3.6. The Non-MAGI Asset Test

For an application on the `NON_MAGI` pathway, the determination runs the asset test instead of the income test, and `magi_annual_cents`, `fpl_percentage`, and `applicable_threshold_pct` are all null on the resulting determination. The system walks every asset belonging to the household and computes each asset's countable value. A `HOME` is fully exempt and contributes a countable value of zero. Among the household's vehicles, the single highest-value `VEHICLE` is exempt and contributes zero; every other vehicle counts at its full `value_cents`. When two or more vehicles tie for the highest `value_cents`, the earliest-created one (the lowest insertion order) is the exempt vehicle and the rest count. A `BURIAL_FUND` contributes its `value_cents` reduced by the burial exemption cap of $1,500 (150000 cents), but never below zero — so a burial fund at or under the cap contributes zero and one above the cap contributes only the excess. Every other asset type contributes its full `value_cents`. The household's `countable_assets_cents` is the sum of these per-asset countable values; on a `MAGI` determination this field is null.

The countable total is then compared against an asset ceiling chosen by the household's disability status. If any counted member has `is_disabled` set to true, the ceiling is the state rule's `abd_asset_limit_cents` (the typically lower aged-blind-disabled limit, for example $2000); if no counted member is disabled, the ceiling is the `standard_asset_limit_cents`. Because identical assets can clear one limit and fail the other, the disability status alone can flip the outcome. The household passes the asset test when its `countable_assets_cents` is less than or equal to the chosen ceiling — the boundary is inclusive, so a total exactly equal to the limit is eligible. When eligible, `decision` is `ELIGIBLE` and `decision_reason` is `ASSETS_UNDER_LIMIT`; otherwise `decision` is `INELIGIBLE` and `decision_reason` is `ASSETS_OVER_LIMIT`.

### 3.7. Enrollment, the Coverage Cycle, and Continuous Coverage

Once an application is approved, a `CaseWorker` creates an **enrollment** from it, supplying the `household_id`, the `application_id` of the approved application, and the coverage window: `coverage_start` and `coverage_end` are ISO 8601 UTC dates bounding a closed coverage interval (both endpoints inclusive), and `redetermination_due` is the ISO 8601 UTC instant that opens the annual redetermination window running up to `coverage_end`. A new enrollment starts in `coverage_status` `PENDING`, and its `member_months` field starts at zero until activation fixes it.

A caseworker then activates a `PENDING` enrollment. Activation is permitted only while `coverage_status` is `PENDING`. It requires that the linked application's `review_status` be `APPROVED`; activating against an application that is not approved is rejected with `ERR_APPLICATION_NOT_APPROVED`. It also requires that the new coverage interval not intersect the closed coverage interval of any other enrollment of the same household whose `coverage_status` is `ACTIVE` or `IN_REDETERMINATION`; an overlapping activation is rejected with `ERR_COVERAGE_OVERLAP`. On success the enrollment moves from `PENDING` to `ACTIVE`, its `member_months` is fixed at the household's `household_size` at this moment multiplied by twelve, that `member_months` quantity is credited to the household's `covered_member_months`, and the household's `active_enrollment_count` rises by one.

An active enrollment is revisited each year. Opening a redetermination drives the enrollment from `ACTIVE` to `IN_REDETERMINATION`. When the redetermination's review concludes favorably (it reaches `RENEWED`), the system cascades the enrollment back from `IN_REDETERMINATION` to `ACTIVE`, closing the cycle with no ledger change. When the review concludes adversely (the redetermination reaches `TERMINATED`), the system cascades the enrollment from `IN_REDETERMINATION` to `TERMINATED` — but only when the household's state is not under the continuous-coverage freeze. While the governing state rule's `continuous_coverage_active` is true, a termination is blocked with `ERR_CONTINUOUS_COVERAGE_LOCK`. When a termination does proceed, the enrollment's `member_months` quantity is debited back out of the household's `covered_member_months` and the `active_enrollment_count` falls by one. Should a later appeal overturn that termination, the system cascades the enrollment from `TERMINATED` back to `ACTIVE`, re-crediting the same `member_months` to `covered_member_months` and raising `active_enrollment_count` by one, leaving the conserved ledger with net-zero drift.

### 3.8. The Annual Redetermination

A `CaseWorker` opens a **redetermination** against an active enrollment to revisit its eligibility for the coming year. The request supplies the `enrollment_id` of the enrollment under review, the redetermination window as `window_open` (an inclusive ISO 8601 UTC start) and `window_close` (an exclusive ISO 8601 UTC end, so the window is the half-open interval from `window_open` up to but not including `window_close`), the `new_determination_id` referencing the fresh eligibility determination evaluated for this cycle, and `expected_enrollment_version` for the optimistic-concurrency check of §2.8. A new redetermination starts in `redet_status` `INITIATED` and carries an `info_request_count` that begins at zero.

Opening a redetermination is subject to a tightly ordered set of checks beyond the universal authentication, authorization, existence, and well-formedness gates. The optimistic-concurrency check comes first among the endpoint-specific rules: if `expected_enrollment_version` does not match the enrollment's current `version`, the create is rejected with `ERR_STALE_VERSION`. Next comes an endpoint-specific state check that takes precedence over the generic state check: if the target enrollment is already `IN_REDETERMINATION` — meaning a redetermination is already open for it — the request is rejected with the specific `ERR_REDETERMINATION_IN_PROGRESS` rather than the generic invalid-state error, and this specific check is evaluated before the generic one so the specific error wins. Any other non-`ACTIVE` enrollment state yields the generic `ERR_INVALID_STATE`. Finally, the new window must not intersect the half-open window of any prior redetermination for the same enrollment, including ones that have already reached `RENEWED`; an overlapping window is rejected with `ERR_REDETERMINATION_WINDOW_OVERLAP`. When all checks pass, the create succeeds, the parent enrollment cascades from `ACTIVE` to `IN_REDETERMINATION`, and the enrollment's `version` increments by one.

While a redetermination is open, a `CaseWorker` may request additional information from the household. The first such request advances `redet_status` from `INITIATED` to `INFO_REQUESTED`; a further request while already `INFO_REQUESTED` is a self-loop that keeps the status at `INFO_REQUESTED`. Each request — whether the first transition or a self-loop — increases `info_request_count` by one, so the count records how many times information was requested over the life of the redetermination.

A caseworker finalizes a redetermination by supplying a `target_status` of either `RENEWED` or `TERMINATED`; finalization may be taken from `INITIATED` or from `INFO_REQUESTED`, and the rules are identical from either origin. Finalizing to `RENEWED` requires that the redetermination's linked `new_determination_id` determination have a `decision` of `ELIGIBLE`; if it does not, the finalize is rejected with `ERR_DETERMINATION_INELIGIBLE`. A successful renewal sets `redet_status` to `RENEWED` and cascades the parent enrollment from `IN_REDETERMINATION` back to `ACTIVE`. Finalizing to `TERMINATED` requires the opposite — the linked determination's `decision` must be `INELIGIBLE`, and a mismatch is again rejected with `ERR_DETERMINATION_INELIGIBLE` — and it additionally requires that the parent enrollment's governing state rule not have `continuous_coverage_active` set to true; while that freeze is in force the termination is blocked with `ERR_CONTINUOUS_COVERAGE_LOCK`. A successful termination sets `redet_status` to `TERMINATED` and cascades the parent enrollment from `IN_REDETERMINATION` to `TERMINATED`, which in turn debits the household's `covered_member_months` by the enrollment's `member_months` and decrements `active_enrollment_count` by one. A redetermination that has been terminated and then has an appeal filed against it moves automatically from `TERMINATED` to `PENDING_APPEAL`.

### 3.9. Appeals and the Fair Hearing

When a redetermination terminates a household's coverage, an `Applicant` may file an **appeal** to contest it. The appeal supplies the `enrollment_id` of the affected enrollment, the `redetermination_id` of the terminated redetermination being challenged, an optional `aid_paid_pending` flag (defaulting to false) electing whether coverage continues pending the hearing, and `expected_enrollment_version` for the optimistic-concurrency check of §2.8: if it does not match the enrollment's current `version`, the filing is rejected with `ERR_STALE_VERSION`. A new appeal starts in `appeal_status` `FILED`. Beyond the universal gates and the `expected_enrollment_version` check, filing imposes no further precondition: it does not require the linked redetermination to be `TERMINATED`, nor does it verify that the supplied `redetermination_id` belongs to the supplied `enrollment_id`. Filing an appeal cascades its linked redetermination from `TERMINATED` to `PENDING_APPEAL` only when that redetermination is currently `TERMINATED`; if the redetermination is in any other state its status is left unchanged. In all cases a successful filing increments the parent enrollment's `version` by one.

The hearing process is conducted by a `HearingOfficer` and proceeds through three stages. First the officer schedules the hearing, advancing `appeal_status` from `FILED` to `HEARING_SCHEDULED`. Then the officer holds the hearing, advancing from `HEARING_SCHEDULED` to `HEARD`; this is the segregation-of-duties checkpoint, because the acting hearing officer's `X-User-ID` must differ from the `assigned_caseworker_id` pinned on the underlying application — that is, the application reached from the appeal's enrollment via its `application_id` — and if they are the same person, the hearing is rejected with `ERR_SEGREGATION_OF_DUTIES`. When that underlying application has no `assigned_caseworker_id` pinned (it is null, for instance because the application was never claimed for review), the segregation check is vacuously satisfied and the hearing proceeds. Holding the hearing records the officer's `X-User-ID` into the appeal's `adjudicator_id`. Finally the officer rules on the heard appeal by supplying a `target_status` of `UPHELD` or `OVERTURNED`. Ruling `UPHELD` lets the termination stand with no coverage change. Ruling `OVERTURNED` requires that the linked enrollment's `coverage_status` actually be `TERMINATED`; if it is not, the ruling is rejected with `ERR_NOT_TERMINATED`. A successful overturn cascades the linked enrollment from `TERMINATED` back to `ACTIVE`, re-crediting the household's `covered_member_months` by the enrollment's `member_months` and incrementing `active_enrollment_count` by one.

An appeal may instead be withdrawn by an `Applicant` before it is heard. Withdrawal is permitted from either `FILED` or `HEARING_SCHEDULED`, and from either origin it sets `appeal_status` to `WITHDRAWN`.

### 3.10. Reading the Case: Lookups and Filtered Lists

Throughout the lifecycle, all three roles can read the resources they are permitted to see. A state rule is fetched by its `stateCode` path parameter. Households, members, income sources, assets, applications, determinations, enrollments, redeterminations, and appeals are each fetched by their identifiers. Several collections are also listable, each honoring the `limit` and `offset` pagination parameters of §2.3. A household's members, assets, and applications are listed under that household; a member's income sources are listed under that member; an application's determinations are listed under that application. Three flat collections support filtering: enrollments may be filtered by `household_id` or `application_id`; redeterminations by `enrollment_id` or `new_determination_id`; and appeals by `enrollment_id` or `redetermination_id`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including the state-advancing actions and member exclusion — return `200 OK`. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/state-rules` | Create a state's Medicaid rule set | CaseWorker |
| GET | `/state-rules/{stateCode}` | Get a state's rule set by state code | CaseWorker, HearingOfficer, Applicant |
| PATCH | `/state-rules/{stateCode}` | Update mutable state-rule fields | CaseWorker |
| POST | `/fpl-schedules` | Create a federal poverty guideline schedule for a year | CaseWorker |
| POST | `/households` | Create a household applying for Medicaid | Applicant, CaseWorker |
| GET | `/households/{id}` | Get a household, including computed ledger fields | Applicant, CaseWorker, HearingOfficer |
| POST | `/households/{id}/members` | Add a member to a household | Applicant, CaseWorker |
| GET | `/members/{id}` | Get a household member | Applicant, CaseWorker, HearingOfficer |
| GET | `/households/{id}/members` | List members of a household | Applicant, CaseWorker, HearingOfficer |
| POST | `/members/{id}/exclude` | Mark a member excluded | CaseWorker |
| POST | `/members/{id}/income-sources` | Add an income source to a member | Applicant, CaseWorker |
| GET | `/members/{id}/income-sources` | List income sources for a member | Applicant, CaseWorker, HearingOfficer |
| POST | `/households/{id}/assets` | Add an asset to a household | Applicant, CaseWorker |
| GET | `/households/{id}/assets` | List assets of a household | Applicant, CaseWorker, HearingOfficer |
| POST | `/households/{id}/applications` | Open an eligibility application for a household | Applicant, CaseWorker |
| GET | `/applications/{id}` | Get an application | Applicant, CaseWorker, HearingOfficer |
| GET | `/households/{id}/applications` | List a household's applications | Applicant, CaseWorker, HearingOfficer |
| POST | `/applications/{id}/submit` | Submit a draft application | Applicant |
| POST | `/applications/{id}/claim-review` | Claim a submitted application for review | CaseWorker |
| POST | `/applications/{id}/request-docs` | Request verification documents | CaseWorker |
| POST | `/applications/{id}/verify` | Mark verification complete | CaseWorker |
| POST | `/applications/{id}/determinations` | Run an eligibility determination snapshot | CaseWorker |
| GET | `/applications/{id}/determinations` | List determinations for an application | CaseWorker, HearingOfficer, Applicant |
| POST | `/applications/{id}/decide` | Approve or deny an application under review | CaseWorker |
| POST | `/enrollments` | Create a pending enrollment from an approved application | CaseWorker |
| GET | `/enrollments/{id}` | Get an enrollment | CaseWorker, HearingOfficer, Applicant |
| GET | `/enrollments` | List enrollments, filterable by household or application | CaseWorker, HearingOfficer, Applicant |
| POST | `/enrollments/{id}/activate` | Activate a pending enrollment | CaseWorker |
| POST | `/redeterminations` | Open an annual redetermination for an active enrollment | CaseWorker |
| GET | `/redeterminations/{id}` | Get a redetermination | CaseWorker, HearingOfficer, Applicant |
| GET | `/redeterminations` | List redeterminations, filterable by enrollment or determination | CaseWorker, HearingOfficer, Applicant |
| POST | `/redeterminations/{id}/request-info` | Request additional information | CaseWorker |
| POST | `/redeterminations/{id}/finalize` | Finalize a redetermination to renewed or terminated | CaseWorker |
| POST | `/appeals` | File an appeal against a terminated redetermination | Applicant |
| GET | `/appeals/{id}` | Get an appeal | CaseWorker, HearingOfficer, Applicant |
| GET | `/appeals` | List appeals, filterable by enrollment or redetermination | CaseWorker, HearingOfficer, Applicant |
| POST | `/appeals/{id}/schedule` | Schedule a fair hearing | HearingOfficer |
| POST | `/appeals/{id}/hear` | Hold the fair hearing | HearingOfficer |
| POST | `/appeals/{id}/rule` | Rule on a heard appeal | HearingOfficer |
| POST | `/appeals/{id}/withdraw` | Withdraw an appeal | Applicant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EMPTY_HOUSEHOLD` | 409 |
| `ERR_NOT_VERIFIED` | 409 |
| `ERR_NO_ELIGIBLE_DETERMINATION` | 409 |
| `ERR_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_REDETERMINATION_WINDOW_OVERLAP` | 409 |
| `ERR_REDETERMINATION_IN_PROGRESS` | 409 |
| `ERR_DETERMINATION_INELIGIBLE` | 409 |
| `ERR_CONTINUOUS_COVERAGE_LOCK` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NOT_TERMINATED` | 409 |

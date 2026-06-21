# School Meal Eligibility API — Product Requirements Document

## 1. Introduction

The federal Free and Reduced-Price Lunch (FRL) program sits at the intersection of three uncomfortable realities for a K–12 school district: a household's economic circumstances change mid-year, federal poverty thresholds vary by region and reset every July, and every meal served becomes a line on a USDA reimbursement claim that an auditor can re-litigate months later. This document specifies a backend system that absorbs that complexity behind a single REST API so that parents, school cafeteria staff, district reviewers, and USDA auditors can each act on the same source of truth without negotiating manually over snapshots, tier changes, or refund timing.

The system handles the application lifecycle (a parent submits an application, a district reviewer approves or denies it, a denied parent may appeal), turns approvals into bounded-validity eligibility records that ride alongside direct-certification and auto-renewal paths, prices and serves individual meals against those eligibility records, runs a per-account ledger for parent top-ups and meal charges, and aggregates served meals into periodic USDA reimbursement claims. A small set of administrative endpoints exposes a logical server clock so that time-gated behaviors (validity windows, daily top-up caps, claim periods) can be exercised deterministically. All monetary values are integer US cents end-to-end; no part of the system uses floating-point dollars.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the system's five declared roles. If `X-User-Role` is missing or names a role outside the declared set, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is recognized but is not on the endpoint's allow-list, the request is rejected with `ERR_FORBIDDEN`.

The five declared roles are `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor`, and `PlatformAdmin`.

`Parent` is the only entity-backed role. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Household`; ownership checks on any resource that references a `Household` compare the resource's `household_id` to `X-User-ID`. A parent acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check applies to application submission, application appeal, application withdrawal, account top-up, and transaction dispute.

`SchoolStaff`, `DistrictReviewer`, `USDAAuditor`, and `PlatformAdmin` are opaque operator identities. When `X-User-Role` is any of these four, `X-User-ID` is an operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. `PlatformAdmin` is restricted to the administrative test-driving endpoints under `/_clock/` and `/_renewal/`; the other operator roles never invoke those endpoints.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 if omitted, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0 and must not be negative. A request with `limit` outside the inclusive range from 1 to 100 or with a negative `offset` is rejected with `ERR_INVALID_PAGINATION`.

List responses sort the underlying collection by `created_at` in ascending order before applying `offset` and then `limit`. The `meta` block on a list response echoes the effective `limit` and `offset` alongside `total_count` (the unpaginated row count matching the request's filters) and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties

Most resources in this system are mutable and carry four common properties: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix; the API never accepts a client-supplied id at creation. The `created_at` and `updated_at` timestamps are ISO 8601 UTC with three fractional digits; `updated_at` is refreshed on every mutation. The `version` field is a non-negative integer that increments by exactly one on every mutation and is the input to optimistic concurrency control (§2.5). These common properties are carried by `Household`, `Student`, `AllergyProfile`, `MealApplication`, `EligibilityDetermination`, `MenuItem`, `ParentAccount`, `ServiceTransaction`, and `ReimbursementClaim`.

The `LedgerEntry` entity is the one exception. A ledger row is an immutable audit record: once written it is never updated. `LedgerEntry` therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`.

### 2.5. Optimistic Concurrency Control

Three write endpoints require the client to declare which version of the target resource the action is intended against. Endpoints not listed here do not accept a version field and ignore one if supplied.

Submitting an appeal on a `MealApplication` requires the request body to include `expected_mealapplication_version`. If the value does not equal the application's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. This captures the case where another writer (for example, a staff clarification edit) has advanced the application's `version` between the parent's last read and the appeal submission; the parent must re-read and re-submit.

Revoking an `EligibilityDetermination` requires the request body to include `expected_eligibilitydetermination_version`. If the value does not equal the determination's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where a verification or deferral on the same determination has bumped its `version` since the auditor's read; the auditor must re-read and re-issue.

Refunding a `ServiceTransaction` requires the request body to include `expected_servicetransaction_version`. If the value does not equal the transaction's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against the transaction having advanced — for example, into `DISPUTED` — since the staff member's read; a refund issued against a stale `SETTLED` view would double-compensate the parent. Because the canonical use case is exactly a transaction that has already advanced out of `SETTLED`, the OCC version check on refund is evaluated before the `SETTLED` state-machine precondition: a stale-view refund against a now-`DISPUTED` transaction therefore surfaces `ERR_STALE_VERSION` rather than `ERR_INVALID_STATE`. (Notwithstanding the generic ordering in §2.10, this rule pins the OCC check ahead of the state precondition for the refund endpoint specifically.)

The three rules share a single `error_id` (`ERR_STALE_VERSION`) and HTTP status (412). The endpoint and field name together identify which mismatch occurred.

### 2.6. Monetary Precision and Rounding

All monetary values throughout the system are integer US cents. No field stores a decimal dollar amount; no calculation passes through a floating-point dollar value. Where a calculation step requires division (notably the annual-income-to-monthly conversion in tier determination, and the reduced-tier discount multiplication), the result is rounded half-up to the nearest whole cent before being used downstream. Where the federal poverty threshold itself is multiplied by a percentage to derive a tier boundary, the boundary is computed by integer truncation (floor). All inequality comparisons between household income and tier thresholds are therefore integer-vs-integer comparisons in cents.

### 2.7. Time, Validity Windows, and the Server Clock

The system maintains a logical UTC clock that is the sole source of time for time-gated behaviors: stamping `served_at_utc` on a transaction, comparing the current instant against an eligibility determination's `valid_from_utc` and `valid_to_utc`, computing the daily top-up window date, and running the expiry sweep. Validity windows on an `EligibilityDetermination` are half-open: the window is inclusive at `valid_from_utc` and exclusive at `valid_to_utc`. Two consecutive determinations for the same household whose windows touch at a single instant (one ends at exactly the instant the next begins) are considered adjacent, not overlapping.

The logical clock is settable and advanceable through administrative endpoints in the `/_clock/` namespace. Setting the clock to a new instant repoints all subsequent comparisons; advancing the clock with an expiry sweep additionally transitions every `ACTIVE` `EligibilityDetermination` whose `valid_to_utc` is at or before the new instant to `EXPIRED`. These endpoints are restricted to `PlatformAdmin`.

### 2.8. Path Hierarchy and Nested Reads

Where a path contains nested resource segments — for example, an account's ledger or a household's students — the server resolves the segments left-to-right. The outer `{id}` must resolve to an existing parent resource before the inner segment is considered; if any path-templated `{id}` does not resolve to an existing entity, the request is rejected with `ERR_NOT_FOUND`. The collection returned by a nested read is filtered to children of the resolved parent and paginated under the §2.3 rules. One-to-one relationships — a household's parent account, a student's allergy profile — are still returned as a list-shaped envelope containing either zero or one element.

### 2.9. The Single Source of Funds: the Parent-Account Ledger

A `ParentAccount` exists at most once per household and is created automatically when a household is created. Its `balance_cents` is never written directly; it is a derived field equal to the signed sum over the account's `LedgerEntry` rows. Every change to the balance — a top-up, a meal charge, a refund, or an adjustment — happens by creating a new ledger entry. The balance shown on a read of a `ParentAccount` is reconciled from the ledger.

Entries carry the owning account's id in `parent_account_id`, and an `entry_type` from the set `TOPUP`, `MEAL_CHARGE`, `MEAL_REFUND`, and `ADJUSTMENT`. The sign convention on `amount_cents` is fixed: credits (`TOPUP`, `MEAL_REFUND`, and credit-direction `ADJUSTMENT`) carry a positive amount; debits (`MEAL_CHARGE` and debit-direction `ADJUSTMENT`) carry a negative amount. A `MEAL_CHARGE` or `MEAL_REFUND` carries the originating transaction's id in `linked_transaction_id`; other entry types leave `linked_transaction_id` null. A `TOPUP` carries an `idempotency_key` (described in §3); other entry types leave it null.

### 2.10. Validation Ordering

Where multiple validation rules apply to the same endpoint, they are evaluated in a fixed order: authentication first (presence and recognition of the role), then role authorization for the endpoint, then resource-ownership for `Parent`-owned resources, then existence of every path-templated id, then the state-machine precondition for any state-mutating operation, then business safety (allergen conflict), then business-referential checks (overlap and gap rules for claims and determinations), then business-fiscal checks (daily top-up cap, then sufficient funds), then business-constraint checks (idempotency, period closure, household completeness, then the generic request-shape and pagination checks). When a request would fail multiple rules, the earlier rule in this ordering produces the error. This guarantees, for example, that an unauthenticated request never surfaces an `ERR_INVALID_STATE`, and that a request against a non-existent path id never surfaces an allergen conflict.

## 3. Business Logic & Workflows

### 3.1. Households, Students, and Allergy Profiles

A `Household` is the anchor of every other entity in the system. Creating one is the first act of onboarding and is performed by either school staff or a district reviewer; the payload contains the responsible parent or guardian's `primary_parent_name`, the `family_size` (an integer between 1 and 20 inclusive), the reported gross `annual_income_cents` (a non-negative integer), and the two-letter uppercase `address_state` that determines which federal poverty table will later apply. The payload may also set `direct_certification_flag`, which defaults to false and asserts that the household is enrolled in SNAP, TANF, or FDPIR and is therefore automatically eligible for free meals without ever filing an application. Household creation has one always-on side effect: a `ParentAccount` for that household is created in the same transaction with a starting balance of zero cents.

Household fields are mutable. A parent may update their own household; school staff may update any household. The mutable surface covers `primary_parent_name`, `family_size`, `annual_income_cents`, `address_state`, and `direct_certification_flag`, all optional in a single PATCH. Each successful update bumps the household's `version` and refreshes its `updated_at`. Updates do not retroactively change any already-submitted application's tier — applications carry their own pinned snapshots, as described in §3.2.

A `Student` belongs to exactly one household (via `household_id`) and is created by school staff with a `full_name`, the `school_code` of the school they attend (a free-form identifier such as `ELEM-101`), and a `grade_level` from 0 (kindergarten) through 12. The student-to-household relationship is exposed both forward (read a student, learn their household) and backward (list a household's students under the household's nested students collection).

An `AllergyProfile` is registered once per student. The profile names the student through `student_id`, carries an `allergens` array drawn from the closed set `PEANUT`, `TREE_NUT`, `MILK`, `EGG`, `SOY`, `WHEAT`, `FISH`, and `SHELLFISH` (no duplicates within the array), and assigns an overall `severity` of `MILD`, `MODERATE`, or `SEVERE_ANAPHYLACTIC`. If `allergens` is omitted, it defaults to an empty array; if `severity` is omitted, it defaults to `MILD`. School staff or the parent themselves may create the profile.

Updating an `allergens` list or `severity` is significant beyond the profile itself: any `PENDING` `ServiceTransaction` tied to a student whose new profile would now contain an allergen also present in the served `MenuItem` — together with `severity` of `SEVERE_ANAPHYLACTIC` — is immediately transitioned to `REJECTED` with `rejection_reason` set to `ALLERGEN_CONFLICT`. The same cascade fires when a brand-new profile is created for a student who already has pending transactions. The cascade depth is two: the profile mutation triggers the transaction transitions in the same operation. Each transition refreshes the transaction's `updated_at` and bumps its `version`.

### 3.2. The Application Lifecycle

A `MealApplication` carries the household through the formal FRL determination path. It is created in `DRAFT` against a `household_id` and a `school_year` label such as `2025-2026`; the `school_year` selects which revision of the federal poverty table will later govern. A parent may create their own application, and school staff may create one on a household's behalf.

Submission is the parent's act and the most consequential one. When the parent submits a `DRAFT` application, the server requires that the household has both an `annual_income_cents` and a `family_size` recorded; if either is null, submission is rejected with `ERR_HOUSEHOLD_INCOMPLETE`. On success the application's `status` transitions from `DRAFT` to `SUBMITTED`, and three snapshot fields are pinned in the same operation: `snapshot_family_size`, `snapshot_annual_income_cents`, and `snapshot_address_state` are copied from the household's current values into the application. These snapshots are deliberately immutable for the life of the application. A later edit to the household's `family_size` or `annual_income_cents` will not retroactively change what tier this submitted application will produce.

A `DRAFT` or `SUBMITTED` application may be withdrawn by its owning parent, transitioning to `WITHDRAWN`. `WITHDRAWN` is terminal. Withdrawal is a parent-only operation; staff cannot withdraw on a parent's behalf.

A `SUBMITTED` application is picked up by either school staff or a district reviewer, who marks it `UNDER_REVIEW` to indicate active review. From `UNDER_REVIEW` only a district reviewer may decide the outcome: approval, which transitions the application to `APPROVED` and produces an `EligibilityDetermination` (described below); or denial, which transitions to `DENIED`. Both decision transitions require a `decision_reason` in the payload (non-empty). Denial creates no eligibility record.

A `DENIED` application is not terminal: the parent may appeal it, supplying an `appeal_reason` in the payload. The appeal is also the OCC-guarded act described in §2.5: the appeal request must carry `expected_mealapplication_version` matching the application's current `version`, or the appeal is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the application moves from `DENIED` to `APPEALED`. From `APPEALED` the review cycle reopens: school staff or a district reviewer move the application back to `UNDER_REVIEW`, and the approve/deny choice is presented again. This `DENIED → APPEALED → UNDER_REVIEW → APPROVED|DENIED` cycle can in principle repeat.

Every state transition on a `MealApplication` increments its `version` by one and refreshes its `updated_at`.

### 3.3. From Approval to Eligibility: the Tier Calculation

Approval is the single richest operation in the system. When a district reviewer approves an `UNDER_REVIEW` application, the server runs the tier calculation against the application's pinned snapshots, creates an `EligibilityDetermination` for the household, supersedes whatever ACTIVE determinations the household previously held, and re-binds in-flight pending transactions to the new determination. Each of these effects is described below.

The tier calculation is a strict procedure on integer cents. First, if the household's `direct_certification_flag` is true at the time of approval, the resulting tier is `FREE` and the rest of the calculation is skipped. Otherwise the server computes the household's monthly income in cents by taking `snapshot_annual_income_cents`, dividing by 12, and rounding half-up to the nearest whole cent; this rounding step happens before any comparison, so a household at an exact annual boundary may land on a different tier than the same household evaluated by a sum-then-round procedure. Next, the server selects the federal poverty monthly figure (`FPL_MONTHLY_<region>`) using the snapshot's address state: a state code of `AK` selects the Alaska table, `HI` selects the Hawaii table, and every other state code selects the Contiguous table. The selected dollar figure is converted to cents by multiplication by 100, producing the household's poverty-line monthly cents.

The federal poverty monthly figures, in whole dollars per month and indexed by household `snapshot_family_size`, are as follows. For the contiguous 48 states and DC: 1,255 at family size 1; 1,704 at 2; 2,152 at 3; 2,600 at 4; 3,049 at 5; 3,497 at 6; 3,946 at 7; 4,394 at 8. For Alaska: 1,569 at 1; 2,129 at 2; 2,690 at 3; 3,251 at 4; 3,811 at 5; 4,372 at 6; 4,933 at 7; 5,494 at 8. For Hawaii: 1,443 at 1; 1,960 at 2; 2,476 at 3; 2,993 at 4; 3,509 at 5; 4,026 at 6; 4,543 at 7; 5,059 at 8.

The free-tier ceiling is then 130 percent of the household's poverty-line monthly cents (the constant `FREE_PCT` is 1.30), and the reduced-tier ceiling is 185 percent (`REDUCED_PCT` is 1.85). Each ceiling is computed by integer truncation (floor) of the product, yielding whole-cent thresholds. The tier assignment compares the rounded household monthly income against these thresholds with the at-most-or-equal operator: if household monthly cents is at most the free-tier ceiling, the tier is `FREE`; otherwise if it is at most the reduced-tier ceiling, the tier is `REDUCED`; otherwise the tier is `PAID`. Both inequalities are inclusive at the upper boundary, so a household landing exactly on the free-tier ceiling is `FREE`.

The approval transition then creates a new `EligibilityDetermination` for the household. The new record carries the household's `household_id`, links back through `source_application_id` to the approving application, marks `source` as `APPLICATION`, fixes `tier` to the calculated value, sets `lifecycle_status` to `ACTIVE`, sets `verification_status` to `UNVERIFIED`, sets `valid_from_utc` to the current server clock instant, and sets `valid_to_utc` to the end of the school year plus a 30-day carryover.

The same approval operation must also cascade. Every prior `EligibilityDetermination` for the same household that is currently `ACTIVE` has its `lifecycle_status` flipped to `SUPERSEDED` and its `valid_to_utc` reset to the current server clock instant; each supersession bumps the determination's `version` and refreshes `updated_at`. Then, every `ServiceTransaction` in `PENDING` whose `eligibility_determination_id` references any newly-superseded determination is re-bound to the new determination: its `eligibility_determination_id` is updated, its `applied_tier` is replaced with the new tier, and its `paid_charge_cents` is recomputed by the meal-pricing procedure of §3.4. Each re-bound transaction has its `version` bumped and `updated_at` refreshed. The cascade depth is therefore three: the approval mutates the application, then the prior determinations, then the pending transactions.

Finally, the approval transition records `decision_reason` on the application and bumps the application's `version`.

The denial branch is the structural sibling of approval but with a smaller side-effect set: it requires the same non-empty `decision_reason`, records it, bumps the application's `version`, refreshes `updated_at`, and creates no eligibility record at all. Tests asserting the absence of an eligibility record on denial expect this asymmetry — both branches require the reason, only one branch produces a determination.

### 3.4. Eligibility Records and Their Two Independent Lifecycles

An `EligibilityDetermination` has two parallel status dimensions that evolve independently. `lifecycle_status` answers "is this determination governing meals right now" and moves through `ACTIVE` (the initial value), `SUPERSEDED` (a newer determination has displaced it), `EXPIRED` (the validity window has run out), and `REVOKED` (an auditor has cancelled it). The two terminal lifecycle states are `EXPIRED` and `REVOKED`. `verification_status` answers "has an auditor signed off on this determination" and moves through `UNVERIFIED` (the initial value), `VERIFIED`, and `DEFERRED`. The two dimensions do not interlock: a determination can be `ACTIVE` and `UNVERIFIED`, `ACTIVE` and `VERIFIED`, `SUPERSEDED` and still `UNVERIFIED`, and so on. Verification and deferral are permitted only while the determination remains `ACTIVE`.

Three paths produce a new determination. The first is the application approval just described, where `source` is `APPLICATION` and `source_application_id` links back to the approving application. The second is operator-initiated creation through the direct-bookings endpoint, used for two flows: `DIRECT_CERTIFICATION` (a household enrolled in SNAP, TANF, or FDPIR receives a `FREE` determination with no application) and `AUTO_RENEWAL` (the start of a new school year carries forward the prior year's tier). For both operator-initiated paths the request supplies `household_id`, `source`, `tier`, `valid_from_utc`, and `valid_to_utc`. For an `AUTO_RENEWAL` creation, if the household has an `ACTIVE` prior determination whose `valid_to_utc` is at or before the current server clock instant, that prior determination is transitioned to `EXPIRED` in the same operation, bumping its `version`.

Every determination is subject to the household-window non-overlap rule. No two `EligibilityDetermination` rows for the same `household_id` may have overlapping windows; because the windows are half-open at `valid_to_utc`, two windows that touch at exactly one instant (the earlier's `valid_to_utc` equals the later's `valid_from_utc`) are adjacent and allowed. A creation that would produce an overlap is rejected with `ERR_ELIGIBILITY_OVERLAP`. This same rule guards the cascade-side creation inside application approval: if the new determination produced by approval would somehow overlap an existing one, the same error fires.

An auditor may set `verification_status` to `VERIFIED` (verify) or to `DEFERRED` (defer); each requires the determination to be in `lifecycle_status` `ACTIVE` and `verification_status` `UNVERIFIED`. An auditor may also revoke an `ACTIVE` determination outright. Revocation requires `expected_eligibilitydetermination_version` in the payload to match the determination's current `version` — a mismatch is the OCC failure described in §2.5. On a successful revoke, `lifecycle_status` becomes `REVOKED` and `valid_to_utc` is set to the current server clock instant.

A separate non-revoke path retires a determination: when the server clock advances and an `ACTIVE` determination's `valid_to_utc` has been reached or passed, that determination transitions to `EXPIRED`. This transition is performed by the administrative advance-and-expire capability described in §3.8.

Every transition on a determination — supersession, expiration, revocation, verification, deferral — bumps `EligibilityDetermination.version` by one and refreshes `updated_at`.

### 3.5. Menu Items and the Meal Service Workflow

A `MenuItem` represents a single sellable item at a single school. School staff create menu items, supplying the `school_code` the item is offered at, the human-readable `name`, the paid-tier `list_price_cents` (charged to `PAID`-tier students), the three per-tier USDA reimbursement rates `federal_reimbursement_free_cents`, `federal_reimbursement_reduced_cents`, and `federal_reimbursement_paid_cents`, an optional `allergens_present` array (drawn from the same allergen enumeration as the `AllergyProfile`), and the per-serving `calories` count. All four monetary fields and the calories count must be non-negative integers; if `allergens_present` is omitted, it defaults to an empty array.

Serving a student is the act of creating a `ServiceTransaction`. School staff submit a payload containing the `student_id`, the `menu_item_id`, and an optional `substitute_for_allergen` flag (described momentarily). The transaction is created in `PENDING` and the server, in the same operation, performs three computations.

First, the server selects the active eligibility determination governing this student's household at the current instant. The candidate pool is every `EligibilityDetermination` for the student's `household_id` whose `lifecycle_status` is `ACTIVE` and whose validity window contains the current server clock instant — that is, `valid_from_utc` is at or before now and `valid_to_utc` is strictly after now. If the candidate pool is empty, the creation is rejected with `ERR_NO_ACTIVE_ELIGIBILITY`. Otherwise the candidates are ranked by tier generosity first and recency second: `FREE` outranks `REDUCED`, which outranks `PAID`; within a tier the candidate with the latest `valid_from_utc` wins, and within that the candidate with the latest `created_at` wins. The determination's `id` is never used as a tiebreaker. The chosen determination's id is stamped onto the transaction as `eligibility_determination_id`, and its tier is copied to `applied_tier`.

Second, the server computes `paid_charge_cents` from the chosen tier, the menu item's list price, the student's allergy profile, and the `substitute_for_allergen` flag. The base for the calculation is the menu item's `list_price_cents`. If `applied_tier` is `FREE`, the per-tier amount is zero; the calculation short-circuits and `paid_charge_cents` is zero. If `applied_tier` is `REDUCED`, the per-tier amount is the smaller of (a) the constant `REDUCED_PRICE_CAP_CENTS` of 40 cents and (b) the list price multiplied by `REDUCED_DISCOUNT_FACTOR` of 0.10 — that is, 10 percent of list price — with the multiplication rounded half-up to the nearest whole cent. If `applied_tier` is `PAID`, the per-tier amount is the full `list_price_cents`. Then the allergen-substitution surcharge: if all of the following hold — the request set `substitute_for_allergen` to true, the menu item's `allergens_present` array shares at least one allergen with the student's `AllergyProfile.allergens` array, and `applied_tier` is not `FREE` — the per-tier amount is increased by the constant `ALLERGEN_SUB_SURCHARGE_CENTS` of 25 cents. The surcharge never applies to a `FREE`-tier student. The result is the transaction's `paid_charge_cents`.

The two pricing variants — calculation via an `APPLICATION`-source determination versus a `DIRECT_CERTIFICATION`-source determination — share the same formula, with one collapse: a `DIRECT_CERTIFICATION` determination's `tier` is pinned to `FREE`, so the per-tier amount is always zero and the allergen surcharge never applies. An `AUTO_RENEWAL` determination uses whatever tier was carried forward and is priced identically to its application-sourced equivalent.

Third, the server stamps `served_at_utc` to the current server clock instant. This timestamp will later determine which reimbursement claim period the transaction falls into.

The same creation pass performs the allergen safety check. If the menu item's `allergens_present` intersects the student's `AllergyProfile.allergens`, the student's allergy `severity` is `SEVERE_ANAPHYLACTIC`, and the request did not set `substitute_for_allergen` to true, the creation is rejected with `ERR_ALLERGEN_CONFLICT`. A `SEVERE_ANAPHYLACTIC` student whose allergens overlap the menu item's allergens can only be served if the staff explicitly request a substitution.

`federal_reimbursement_cents` on a freshly created `PENDING` transaction is zero; it is set later, at settlement.

### 3.6. Funding, Settlement, Disputes, and Refunds

Funding a household's account is a parent-only act. The top-up endpoint accepts an `amount_cents` and a client-supplied `idempotency_key`. Before the cap check runs, the server rolls the daily window if needed: if the account's `daily_topup_window_date` is not equal to today's UTC calendar date, the server resets `daily_topup_total_cents` to zero and sets `daily_topup_window_date` to today's date. The cap check then compares the sum of `daily_topup_total_cents` and the requested `amount_cents` against the constant `DAILY_TOPUP_CAP_CENTS` of 20,000 cents ($200) per UTC calendar day. If the sum would exceed the cap, the top-up is rejected with `ERR_TOPUP_CAP_EXCEEDED`. Otherwise the server creates a `LedgerEntry` with `entry_type` `TOPUP`, `amount_cents` equal to the request amount (positive), `linked_transaction_id` null, and the supplied `idempotency_key`. The account's `daily_topup_total_cents` is then increased by the same amount, and `ParentAccount.version` is bumped.

The `idempotency_key` is required on every top-up and must be unique within the account's history. If a parent re-submits a top-up with the same `idempotency_key` and the same `amount_cents` as a prior successful top-up, the server returns the prior `LedgerEntry` (with the original 200/201-class response body) and creates no new entry. If a re-submission carries the same `idempotency_key` but a different `amount_cents`, the request is rejected with `ERR_DUPLICATE_IDEMPOTENCY_KEY`.

Settling a `PENDING` transaction is school staff's act. The transition requires the transaction to be in `PENDING`, the chosen `EligibilityDetermination` still to be in `lifecycle_status` `ACTIVE` (cross-entity dependency: a settle attempt against a transaction whose chosen determination has since been superseded, expired, or revoked fails), and the parent account's reconciled `balance_cents` to be at least the transaction's `paid_charge_cents`. If the balance is insufficient, the request is rejected with `ERR_INSUFFICIENT_FUNDS`. On success the server creates a `LedgerEntry` with `entry_type` `MEAL_CHARGE`, `amount_cents` equal to the negative of `paid_charge_cents`, and `linked_transaction_id` set to the transaction's id; reconciles `ParentAccount.balance_cents` from the ledger; sets the transaction's `federal_reimbursement_cents` to the menu item's per-tier reimbursement rate matching `applied_tier` (so `federal_reimbursement_free_cents` if `FREE`, `federal_reimbursement_reduced_cents` if `REDUCED`, `federal_reimbursement_paid_cents` if `PAID`); and bumps the transaction's `version`.

A `PENDING` transaction may instead be rejected by staff with a `rejection_reason` from the enumeration `ALLERGEN_CONFLICT`, `INELIGIBLE_STATE`, `INSUFFICIENT_FUNDS`, or `MANUAL`. Rejection sets `rejection_reason`, bumps the transaction's `version`, and produces no ledger movement. `REJECTED` is terminal.

After settlement, two paths can compensate the charge. The first is a direct refund initiated by staff against a `SETTLED` transaction. The refund is OCC-guarded: the payload must carry `expected_servicetransaction_version` matching the transaction's current `version` (a mismatch raises `ERR_STALE_VERSION` per §2.5). On success the server creates a compensating `LedgerEntry` with `entry_type` `MEAL_REFUND`, `amount_cents` equal to the positive `paid_charge_cents`, and the same `linked_transaction_id`; reconciles `ParentAccount.balance_cents`; zeros the transaction's `federal_reimbursement_cents` (the USDA reimbursement is reversed); and bumps `version`. The net ledger delta of charge-then-refund on the same transaction is zero.

The second path runs through dispute resolution. A parent may dispute a `SETTLED` transaction of one of their own children (ownership is checked against the transaction's student's `household_id`); the transition to `DISPUTED` bumps the transaction's `version` and produces no ledger movement. A district reviewer then resolves the dispute by supplying a `resolution` of either `REFUND` or `UPHOLD`. A `REFUND` resolution behaves identically to a direct staff refund: a compensating `MEAL_REFUND` `LedgerEntry`, balance reconciliation, `federal_reimbursement_cents` zeroed, and `version` bumped, with the transaction moving to `REFUNDED`. An `UPHOLD` resolution makes no ledger movement, leaves `federal_reimbursement_cents` untouched, bumps `version`, and returns the transaction to `SETTLED`. The dispute-resolution branch is therefore strictly symmetric across the two `resolution` values: each value produces a transition, each bumps version, only the `REFUND` value creates a ledger entry. Both `REFUNDED` and `SETTLED` (when reached the second time) are valid resting states.

### 3.7. Reimbursement Claims and the Two Accounting Bases

USDA reimbursement is settled in periodic claims. A `ReimbursementClaim` is created in `DRAFT` by school staff against a `school_code`, a `period_start_utc` (inclusive), a `period_end_utc` (inclusive), and an `accounting_basis` of either `CASH` or `ACCRUAL`. The `accounting_basis` is pinned at creation and determines which calculation variant runs at submission; it cannot be changed afterward. Two claims for the same `school_code` may not overlap in time, and consecutive claim periods must be separated by a gap of at least one calendar day — that is, the new claim's `period_start_utc` must be at or after the prior claim's `period_end_utc` plus one day. A creation that would overlap or close the gap is rejected with `ERR_CLAIM_PERIOD_OVERLAP`.

Submission of a `DRAFT` claim by school staff is gated by a closure rule: every `ServiceTransaction` whose `served_at_utc` falls within the inclusive interval from `period_start_utc` to `period_end_utc`, for any student attending the claim's `school_code`, must be in a final status of `SETTLED`, `REJECTED`, or `REFUNDED`. If even one such transaction is still `PENDING` or `DISPUTED`, the submission is rejected with `ERR_PERIOD_NOT_SETTLED`. The closure rule ensures the claim's total is computed against a fully-resolved set of transactions.

On successful submission the server runs the reimbursement aggregation. The candidate set is, in both variants, every `ServiceTransaction` whose `served_at_utc` falls within the claim's inclusive interval and whose student's `school_code` matches the claim's `school_code`. The set is then filtered by `accounting_basis`. Under `CASH`, only transactions with `status` of `SETTLED` are kept; their `federal_reimbursement_cents` values are summed to produce `total_reimbursement_cents`. Under `ACCRUAL`, transactions with `status` of `SETTLED`, `DISPUTED`, or `REFUNDED` are kept; their `federal_reimbursement_cents` values are summed. The arithmetic difference between the two bases is that `DISPUTED` transactions still carry their original reimbursement value (because no refund has zeroed it yet) and `REFUNDED` transactions carry zero (because the refund has already zeroed their `federal_reimbursement_cents`); under `CASH` neither category contributes. Where the aggregation needs to be ordered for any reason, transactions are sorted by their `created_at` in ascending order; the transaction `id` is never used as a tiebreaker. The aggregation is integer-exact: all `federal_reimbursement_cents` values are integer cents and the sum is integer.

The server writes `total_reimbursement_cents` and `included_transaction_count` (the cardinality of the filtered set) onto the claim, transitions it from `DRAFT` to `SUBMITTED`, and bumps `version`. The claim's totals are immutable from this point.

A USDA auditor then either finalizes the `SUBMITTED` claim, moving it to `FINALIZED`, or rejects it, moving it to `REJECTED`. The rejection branch requires a `rejection_reason` in the payload. Both terminal transitions bump the claim's `version`. `FINALIZED` and `REJECTED` are terminal.

### 3.8. Administrative Capabilities: Clock and Auto-Renewal

Three administrative capabilities exist for operational and deterministic-test purposes — clock-set, advance-and-expire, and auto-renewal sweep; only `PlatformAdmin` may invoke them.

The clock-set capability pins the server clock to a supplied `to_iso8601` instant. From that moment, all references to "now" — stamping `served_at_utc`, comparing against `valid_from_utc` and `valid_to_utc`, computing the daily top-up window date — use the pinned instant. The endpoint returns the current pinned UTC instant.

The advance-and-expire capability is the clock-set capability plus an expiry sweep. The clock is advanced to the supplied `to_iso8601` instant, and then, in the same operation, every `EligibilityDetermination` with `lifecycle_status` of `ACTIVE` and `valid_to_utc` at or before the new clock instant is transitioned to `EXPIRED`. Each such transition bumps the determination's `version`. The response carries the new pinned UTC instant and the count of determinations that just expired.

The auto-renewal sweep operates over a `school_year`, a `valid_from_utc`, and a `valid_to_utc`. For every household that held an `ACTIVE`, `SUPERSEDED`, or `EXPIRED` determination in the prior school year and that has no `DENIED` `MealApplication` in the supplied `school_year`, the server creates a new `EligibilityDetermination` with `source` `AUTO_RENEWAL`, the most recent prior tier carried forward (selecting the prior determination with the latest `valid_from_utc` per household), and the supplied window. The inclusion of `EXPIRED` here is deliberate: auto-renewal is typically run at the start of a new school year, after the prior year's advance-and-expire sweep has already retired the prior year's `ACTIVE` windows to `EXPIRED`, so the past-tense "held an ACTIVE … determination in the prior school year" covers determinations that were ACTIVE at some point in that year regardless of their current `lifecycle_status`. The household-window non-overlap rule of §3.4 still governs: if a particular household's renewal window would overlap an existing window for that same household, that household is silently skipped (it is not renewed) but the sweep continues to evaluate the remaining households; the overall request is not aborted and no error is surfaced for the skipped household. The response carries the count of households renewed and the list of those household ids.

## 4. Endpoint Definitions

The API is mounted under `/school-meals`. Resource creation endpoints respond with HTTP 201; all read, list, update, and state-transition endpoints respond with HTTP 200. Error responses use the §5 error catalogue and the §2.2 error envelope. The table below lists method, path, a one-line description, and the role(s) authorized to invoke the endpoint; request and response bodies are described in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/school-meals/households` | Create a household; also creates the household's parent account at zero balance. | `SchoolStaff`, `DistrictReviewer` |
| GET | `/school-meals/households/{id}` | Read a household. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/households` | List households (filterable by address state). | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| PATCH | `/school-meals/households/{id}` | Update mutable household fields. | `Parent`, `SchoolStaff` |
| GET | `/school-meals/households/{id}/students` | List the students of a household. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/households/{id}/applications` | List the meal applications of a household. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/households/{id}/eligibility-determinations` | List the eligibility determinations of a household. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/households/{id}/parent-account` | Read the household's single parent account (zero-or-one list). | `Parent`, `SchoolStaff`, `DistrictReviewer` |
| POST | `/school-meals/students` | Create a student. | `SchoolStaff` |
| GET | `/school-meals/students/{id}` | Read a student. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/students` | List students (filterable by household and school). | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/students/{id}/allergy-profile` | Read the student's allergy profile (zero-or-one list). | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| POST | `/school-meals/allergy-profiles` | Create an allergy profile; cascades pending transactions. | `SchoolStaff`, `Parent` |
| PATCH | `/school-meals/allergy-profiles/{id}` | Update an allergy profile; cascades pending transactions. | `Parent`, `SchoolStaff` |
| POST | `/school-meals/applications` | Create a meal application in `DRAFT`. | `Parent`, `SchoolStaff` |
| GET | `/school-meals/applications/{id}` | Read a meal application. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/applications` | List meal applications (filterable). | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| POST | `/school-meals/applications/{id}/submit` | Parent submits a `DRAFT`; pins household snapshots. | `Parent` |
| POST | `/school-meals/applications/{id}/start-review` | Mark a `SUBMITTED` or `APPEALED` application `UNDER_REVIEW`. | `SchoolStaff`, `DistrictReviewer` |
| POST | `/school-meals/applications/{id}/approve` | Approve an `UNDER_REVIEW` application; cascades to determination and pending transactions. | `DistrictReviewer` |
| POST | `/school-meals/applications/{id}/deny` | Deny an `UNDER_REVIEW` application. | `DistrictReviewer` |
| POST | `/school-meals/applications/{id}/appeal` | Parent appeals a `DENIED` application; OCC-guarded. | `Parent` |
| POST | `/school-meals/applications/{id}/withdraw` | Parent withdraws a `DRAFT` or `SUBMITTED` application. | `Parent` |
| POST | `/school-meals/eligibility-determinations` | Operator-created determination (`DIRECT_CERTIFICATION` or `AUTO_RENEWAL`). | `SchoolStaff`, `DistrictReviewer` |
| GET | `/school-meals/eligibility-determinations/{id}` | Read a determination. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/eligibility-determinations` | List determinations (filterable). | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| POST | `/school-meals/eligibility-determinations/{id}/verify` | Auditor sets verification status to verified. | `USDAAuditor` |
| POST | `/school-meals/eligibility-determinations/{id}/defer` | Auditor sets verification status to deferred. | `USDAAuditor` |
| POST | `/school-meals/eligibility-determinations/{id}/revoke` | Auditor revokes an `ACTIVE` determination; OCC-guarded. | `USDAAuditor` |
| POST | `/school-meals/menu-items` | Create a menu item. | `SchoolStaff` |
| GET | `/school-meals/menu-items/{id}` | Read a menu item. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/menu-items` | List menu items (filterable by school). | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/parent-accounts/{id}` | Read a parent account; reconciles balance from ledger. | `Parent`, `SchoolStaff`, `DistrictReviewer` |
| POST | `/school-meals/parent-accounts/{id}/topup` | Parent tops up the account; idempotency key required; daily cap enforced. | `Parent` |
| GET | `/school-meals/parent-accounts/{id}/ledger` | List ledger entries for an account. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/ledger-entries/{id}` | Read a ledger entry. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/ledger-entries` | List ledger entries (filterable). | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| POST | `/school-meals/service-transactions` | Create a `PENDING` transaction; selects eligibility, prices, stamps `served_at_utc`. | `SchoolStaff` |
| GET | `/school-meals/service-transactions/{id}` | Read a transaction. | `Parent`, `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/service-transactions` | List transactions (filterable). | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| POST | `/school-meals/service-transactions/{id}/settle` | Settle a `PENDING` transaction; charges account, stamps reimbursement. | `SchoolStaff` |
| POST | `/school-meals/service-transactions/{id}/reject` | Reject a `PENDING` transaction. | `SchoolStaff` |
| POST | `/school-meals/service-transactions/{id}/refund` | Refund a `SETTLED` transaction; OCC-guarded; compensating ledger entry. | `SchoolStaff` |
| POST | `/school-meals/service-transactions/{id}/dispute` | Parent disputes a `SETTLED` transaction. | `Parent` |
| POST | `/school-meals/service-transactions/{id}/resolve-dispute` | Reviewer resolves a `DISPUTED` transaction (`REFUND` or `UPHOLD`). | `DistrictReviewer` |
| POST | `/school-meals/reimbursement-claims` | Create a reimbursement claim in `DRAFT`. | `SchoolStaff` |
| GET | `/school-meals/reimbursement-claims/{id}` | Read a reimbursement claim. | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| GET | `/school-meals/reimbursement-claims` | List reimbursement claims (filterable). | `SchoolStaff`, `DistrictReviewer`, `USDAAuditor` |
| POST | `/school-meals/reimbursement-claims/{id}/submit` | Submit a `DRAFT`; runs the aggregation per `accounting_basis`. | `SchoolStaff` |
| POST | `/school-meals/reimbursement-claims/{id}/finalize` | Auditor finalizes a `SUBMITTED` claim. | `USDAAuditor` |
| POST | `/school-meals/reimbursement-claims/{id}/reject` | Auditor rejects a `SUBMITTED` claim. | `USDAAuditor` |
| POST | `/school-meals/_clock/set_current_utc` | Pin the server clock to a supplied UTC instant. | `PlatformAdmin` |
| POST | `/school-meals/_clock/advance_and_expire` | Advance the clock and run the eligibility expiry sweep. | `PlatformAdmin` |
| POST | `/school-meals/_renewal/run_auto_renewal` | Run the auto-renewal sweep for a school year. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_HOUSEHOLD_INCOMPLETE` | 422 |
| `ERR_ALLERGEN_CONFLICT` | 422 |
| `ERR_NO_ACTIVE_ELIGIBILITY` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 422 |
| `ERR_TOPUP_CAP_EXCEEDED` | 422 |
| `ERR_DUPLICATE_IDEMPOTENCY_KEY` | 409 |
| `ERR_CLAIM_PERIOD_OVERLAP` | 409 |
| `ERR_ELIGIBILITY_OVERLAP` | 409 |
| `ERR_PERIOD_NOT_SETTLED` | 409 |
| `ERR_STALE_VERSION` | 412 |

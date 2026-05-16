# School Meal Eligibility API — Product Requirements Document

## 1. Introduction

K-12 school districts in the United States operate a federally subsidised meal programme whose day-to-day mechanics straddle three loosely-coupled domains: a means-tested eligibility review that decides who eats for free, at a reduced co-pay, or at full price; a cafeteria-floor operation that records each tray as it is handed across the counter; and a reimbursement accounting workflow that periodically settles claims with the United States Department of Agriculture (USDA). Each of these domains has its own actors, its own state machine, and its own correctness story — yet they are coupled through a small number of snapshot fields and ledger entries that, if implemented inconsistently, silently misclassify children and misreport federal reimbursements.

This document specifies the API that backs that programme for a single multi-school district. The service must accept Free/Reduced-Lunch (FRL) applications from parents, route them through reviewer decisioning with segregation-of-duties controls, mint per-student eligibility tiers, gate meal servings on allergy intersections, charge parent accounts via a strictly-ordered ledger, and emit USDA reimbursement claims whose final figures are recomputed against post-hoc eligibility and allergy state rather than the values stamped at serving time. The system is read by parents, cafeteria managers, district reviewers, and audit officers — each with distinct authority — and is expected to remain consistent across same-second concurrent operations on the same student, application, or claim.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Every endpoint is mounted under the `/districts` prefix; the district identifier appears as the first path segment of every resource URL.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. Missing or empty headers result in `ERR_UNAUTHENTICATED`; an authenticated request from a role that the endpoint does not permit is rejected with `ERR_FORBIDDEN`.

The system recognises four distinct roles, named exactly as written: `Parent`, `DistrictReviewer`, `CafeteriaManager`, and `AuditOfficer`.

The `Parent` role is entity-backed. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `ParentAccount`; any ownership check on a `Student`, `FrlApplication`, `AllergyProfileEntry`, or top-up/refund operation compares the resource's `parent_account_id` (directly, or via the student's `parent_account_id`) to the header value. The three other roles — `DistrictReviewer`, `CafeteriaManager`, and `AuditOfficer` — are opaque operator identifiers. Their `X-User-ID` is not tied to any persisted entity; the server may record it on resources where a state transition explicitly captures it (for example, `FrlApplication.reviewer_user_id` on approve or deny) but does not compare it against any entity primary key for ownership.

The `Parent` role exclusively drives application submission and resubmission, top-up requests, and the creation and revocation of allergy entries on its own students. The `DistrictReviewer` role exclusively requests information, approves, and denies FRL applications. The `CafeteriaManager` role exclusively creates and retires menu items and records meal servings. The `AuditOfficer` role exclusively creates districts and parent accounts, issues refunds, manages USDA reimbursement claims (create, submit, finalize, reject), and may advance the server's logical clock for test driving. Several capabilities are deliberately shared — voiding a meal serving may be performed by either a `CafeteriaManager` or an `AuditOfficer`; auto-renewal of a draft application may be triggered by either a `Parent` or an `AuditOfficer`; `Student` creation may be performed by a `Parent` on their own behalf or by an `AuditOfficer` on behalf of a family; read endpoints are broadly available across roles as enumerated in §4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary, top-level resource — `District`, `Student`, `ParentAccount`, `FrlApplication`, `MenuItem`, `MealServingRecord`, and `UsdaReimbursementClaim` — carries a standard set of system-managed fields:

- **`id` (string):** A server-minted UUID. Identifiers are not prefixed by type; an `FrlApplication.id` is structurally indistinguishable from a `MenuItem.id`.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp indicating the most recent modification. Computed-field recomputations that change the persisted value (for example, refreshing `eligibility_tier` on a `Student` after approval, or updating `prepaid_balance_cents` after a ledger entry) count as modifications for this purpose.
- **`version` (integer):** A monotonically increasing integer, starting at 1 on creation and incremented by exactly one on every persisted mutation of the owning resource.

Two entity types are append-only event records and deliberately omit `updated_at` and `version`: `AllergyProfileEntry` and `PaidLedgerEntry`. Both carry only `id` and `created_at` from the common-fields set. An `AllergyProfileEntry` is "revoked" by transitioning its `status` from `ACTIVE` to `REVOKED`, which is the single permitted state change on that entity. A `PaidLedgerEntry` is never updated after insertion; corrections are made by appending a counter-entry (a `REFUND` against a prior `CHARGE`).

### 2.5. Monetary Values, Rates, and Precision

All money in the system is stored and exchanged as **whole integer cents**. There are no fractional-cent values, no decimal monetary fields, and no implicit rounding: every cents field — `declared_annual_income_cents`, `federal_poverty_guideline_cents`, `full_price_cents`, `charged_cents`, `provisional_reimbursement_cents`, `provisional_total_cents`, `final_reimbursement_cents`, `amount_cents`, `prepaid_balance_cents`, `usda_reimbursement_total_cents`, and `top_up_outstanding_cents` — is an integer. Arithmetic that combines these values (additions and subtractions in the ledger, sums across serving records in a claim, rate lookups in the reimbursement tables) stays in integer cents throughout.

The single non-integer quantity in the entire system is the household-income ratio used in `Parent` eligibility classification (§3.4). That ratio is computed in floating-point and compared directly to the two threshold constants without rounding; the inequality is non-strict in both bands, which means a household sitting exactly at a threshold falls into the more generous (lower-numbered) band. Nutrition values likewise stay as integers: `calories` and `sodium_mg` on a `MenuItem` are non-negative integers, and the high-sodium flag described in §3.3 is a non-strict comparison so that a value exactly equal to the threshold is flagged.

### 2.6. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. If supplied, the server compares it against the resource's current `version` before applying the change: if they differ, the request is rejected with `ERR_VERSION_MISMATCH` (HTTP 412) and no state changes. If `version` is omitted from the request body, the version check is skipped and the operation proceeds on the latest state.

Because `AllergyProfileEntry` and `PaidLedgerEntry` carry no `version` field, optimistic concurrency control does not apply to them; they are append-only and serialise on their own keys (uniqueness on `(student_id, allergen)` for `ACTIVE` allergy entries, chronological ordering by `occurred_at` then `id` for ledger entries).

### 2.7. Nested Resource Retrieval and Cross-Aggregate References

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers (for example, the allergy-revocation path that nests an allergy entry under a student under a district), the system validates each identifier in a sequential, left-to-right order. The request is rejected immediately with `ERR_NOT_FOUND` corresponding to the *first* identifier in the path that does not correspond to an existing resource within the enclosing scope. A `student_id` that exists in a different district from the one named in the path is treated as not found in the addressed district.

This same containment rule extends to cross-aggregate references that appear in request bodies. When a meal-serving payload names a `student_id` and a `menu_item_id`, the system requires both to belong to the same `district_id` that appears in the URL — a payload that references a student in district A and a menu item in district B is rejected as `ERR_NOT_FOUND`. Likewise, an `FrlApplication` may only be filed against a `Student` belonging to the same district, and a `ParentAccount` named in a student-creation payload must already live in that district.

### 2.8. School-Year Snapshot and the Logical Clock

A district carries a `school_year_start` field that anchors the academic calendar. When a parent submits an FRL application, the application captures `school_year_start` from the owning `District` at the moment of submission — this is a snapshot, not a live reference. Subsequent changes to the district's calendar do not retroactively re-scope previously-submitted applications. Auto-renewal (§3.5) reads both the new application's snapshot and the prior application's snapshot to decide whether the prior application is "in the prior school year".

For test driving and for any operation whose correctness depends on the current calendar day — `serving_date` computation, school-year crossover, the future-dated retirement guard on a `MenuItem`, and the same-day uniqueness rule on meal servings — the server maintains a logical clock that can be advanced to a target instant by an `AuditOfficer`. The advance request body carries a single field `target_instant`, an ISO 8601 UTC instant, and the response object reports `now` (the clock's new value). The clock is monotonic across the test run; "today" everywhere in this PRD means the UTC-midnight calendar day derived from the logical clock at the moment of the operation.

### 2.9. Validation Priority Order

Every mutating endpoint applies its applicable validations in a single fixed precedence so that the `error_id` returned in any failure case is deterministic. The order, from highest to lowest, is:

1. **Authentication** — header presence (`ERR_UNAUTHENTICATED`).
2. **Authorisation** — role permitted on this endpoint (`ERR_FORBIDDEN`).
3. **Existence** — left-to-right path resolution and cross-aggregate scoping (`ERR_NOT_FOUND`).
4. **State** — the target resource is in a state that permits the requested transition (`ERR_INVALID_STATE`).
5. **Domain safety, referential, fiscal, constraint, and temporal checks** — every other rule in this document is evaluated only after the four checks above have passed. Within this group, the schema/range validator that backs `ERR_VALIDATION` (e.g., `household_size` out of `[1, 8]` or negative `declared_annual_income_cents`) is treated as a structural input check and runs before the higher-numbered business rules.

A reviewer who attempts to deny an already-`APPROVED` application thus sees `ERR_INVALID_STATE`, not `ERR_SEGREGATION_OF_DUTIES`, even if both would have applied; a `Parent` who submits an application for a student belonging to another district sees `ERR_NOT_FOUND`, not a downstream domain error. The deliberate consequence is that race losers on state transitions all surface as `ERR_INVALID_STATE` once the winner has flipped the resource out of its starting state.

## 3. Business Logic & Workflows

### 3.1. District Provisioning and Parent Onboarding

A district is the top-level tenant. An `AuditOfficer` provisions it by supplying a display `name` and a `school_year_start` (the UTC-midnight instant that marks the first day of the current academic year); the system seeds both `usda_reimbursement_total_cents` and `top_up_outstanding_cents` at zero. Subsequent reads of a `District` recompute these two totals from the underlying records: `usda_reimbursement_total_cents` is the sum of `final_reimbursement_cents` across every claim under this district that has reached the `FINALIZED` state, and `top_up_outstanding_cents` is the net effect, across every parent account in the district, of `TOP_UP` entries minus `CHARGE` entries minus `REFUND` entries (with the refund sign handled in §3.6's ledger description).

Within a district, an `AuditOfficer` creates `ParentAccount` records with a `parent_email`. The email must be unique within the district; a second account submitted with an email already present on another `ParentAccount` in the same district is rejected with `ERR_PARENT_EMAIL_TAKEN`. A newly-created `ParentAccount` starts with `prepaid_balance_cents` of zero and acquires the `Parent` role identity described in §2.1.

Students belong to a parent account and to a district. A `Student` is created with a `parent_account_id`, a `full_name`, and a `grade_level`, where `grade_level` is an integer from 0 through 12 inclusive (0 representing kindergarten). On creation, every student starts at the paid tier — `eligibility_tier` is `PAID` and `eligibility_application_id` is null — until an APPROVED `FrlApplication` mints a more favourable tier. Two derived fields on a `Student`, `allergy_block_active` and `meals_served_today_count`, are evaluated on read and reflect the live allergy profile and the current day's serving history described in §3.2 and §3.6.

A parent funds their account by topping it up. A top-up request carries an `amount_cents` (a positive integer); the server appends a `PaidLedgerEntry` of `type` `TOP_UP` with that amount and reports the updated balance back. Top-ups never fail on balance grounds — they only add funds.

### 3.2. Allergy Profile Maintenance

A `Student`'s allergy profile is the set of `AllergyProfileEntry` rows owned by that student. A parent who owns the student adds an entry by supplying an `allergen`, a `severity`, and a `doctor_note_attached` flag. The `allergen` field is one of `PEANUT`, `TREE_NUT`, `DAIRY`, `EGG`, `SOY`, `WHEAT`, `FISH`, or `SHELLFISH`. The `severity` field is one of `MILD`, `MODERATE`, or `SEVERE`. When `severity` is `SEVERE`, the system requires `doctor_note_attached` to be true and otherwise rejects the request with `ERR_DOCTOR_NOTE_REQUIRED`. The system also forbids a student from holding two `ACTIVE` allergy entries for the same `allergen`: a second insertion that would collide with an existing `ACTIVE` row for the same `(student_id, allergen)` pair is rejected with `ERR_DUPLICATE_ALLERGEN`. A new entry is born `ACTIVE`.

Revoking an entry is the entity's only state change: the parent who owns the student moves it from `ACTIVE` to `REVOKED` via the dedicated capability, and the student's derived `allergy_block_active` flag is recomputed against the remaining `ACTIVE` rows. Because `AllergyProfileEntry` is append-only-with-revoke (see §2.4), revocation is permitted only when the entry is currently `ACTIVE`; a second revocation on the same entry surfaces `ERR_INVALID_STATE`.

The `allergy_block_active` flag on a `Student` is a derived boolean. Its value is true when at least one of the student's `ACTIVE` allergy entries shares an allergen with the union of `contains_allergens` across all `ACTIVE` menu items that exist for today's serving date in the same district. In a per-menu-item context (such as the safety check at meal-serving time, §3.6), the same predicate is evaluated against the specific `MenuItem.contains_allergens` rather than the day-union, and a hit produces `ERR_ALLERGEN_BLOCK`.

### 3.3. Menu Items and the Nutrition Label

A `CafeteriaManager` curates the menu. A new `MenuItem` is created with a display `name`, an array `contains_allergens` (each entry drawn from the same allergen enumeration as the allergy profile, with the empty array meaning "no labelled allergens"), per-serving `calories` and `sodium_mg` (each a non-negative integer), a `full_price_cents` figure (the price charged to `PAID`-tier students), and a `reimbursable` boolean that controls whether the item qualifies for USDA reimbursement when it is served as part of a reimbursable meal. Every new item is born `ACTIVE`.

Retirement is the menu item's only state change. A `CafeteriaManager` retires an `ACTIVE` item, flipping its `status` to `RETIRED`. The system refuses to retire an item that is referenced by a `SERVED` `MealServingRecord` whose `serving_date` is today or later (relative to the logical clock); such a request is rejected with `ERR_MENU_ITEM_IN_USE`. A retire attempt on an already-`RETIRED` item is rejected with `ERR_INVALID_STATE` per §2.9's precedence.

Anyone with read access to the district can request the nutrition label for a menu item. The label is a synthesised object containing four fields: `calories_per_serving` (the menu item's `calories`), `sodium_per_serving_mg` (the menu item's `sodium_mg`), `allergens` (the unique entries from `contains_allergens`, deduplicated and returned in lexicographic ascending order), and `high_sodium_flag`. The high-sodium flag is true when `sodium_mg` is at least 600 milligrams, with the comparison non-strict — a value of exactly 600 milligrams is flagged.

### 3.4. The FRL Application Lifecycle

An FRL application is the document that decides a student's eligibility tier for a school year. A `Parent` creates one in `DRAFT` state by referencing the `student_id`, declaring `household_size` (an integer from 1 through 8 inclusive — submissions outside this band are rejected with `ERR_VALIDATION`) and `declared_annual_income_cents` (a non-negative integer of whole cents — negative income is likewise `ERR_VALIDATION`), and optionally attaching `documents_attached_count` (defaulting to 0) and a `prior_year_application_id` that names the prior school year's APPROVED application for auto-renewal (§3.5).

**Submission.** When the parent submits the application, the system checks that the application is currently `DRAFT`, that `household_size` is at least 1, and that `declared_annual_income_cents` is non-negative. On success, the application's `status` flips to `SUBMITTED` and the application's `school_year_start` is captured from the district — this snapshot persists through the rest of the application's life and is the calendar field the auto-renewal logic compares against.

**Information request and resubmission.** A `DistrictReviewer` may pause a `SUBMITTED` application and bounce it back for more documentation. The reviewer submits a non-empty `review_note` in the request body; the system rejects an empty note as `ERR_VALIDATION`. On success, the application moves to `INFO_REQUESTED`, the body's `review_note` is recorded on the application, and the reviewer's `X-User-ID` is captured as `reviewer_user_id`. The owning parent then resubmits the application — supplying a fresh `documents_attached_count` in the body — and the application returns to `SUBMITTED`. Resubmission requires the application to be currently `INFO_REQUESTED` and requires the acting parent to own the underlying student's `parent_account_id`; an outsider parent receives `ERR_FORBIDDEN`.

**Approval and tier classification.** A `DistrictReviewer` approves a `SUBMITTED` application. Three preconditions must hold: the application's status is still `SUBMITTED`; the acting reviewer is not the parent who owns the student (segregation of duties — a reviewer who is also the owning parent receives `ERR_SEGREGATION_OF_DUTIES`); and the eligibility classifier yields one of the favourable tiers `FREE` or `REDUCED` rather than `DENIED_PAID`. Approval that would resolve to `DENIED_PAID` is rejected with `ERR_INVALID_STATE` — the reviewer must instead route the application down the deny path.

The eligibility classifier — the **frl_tier_classification** rule — works as follows. The system looks up the federal poverty guideline (in whole cents per year) for the application's `household_size` from a fixed table whose values are exactly: one person 15,000.00 dollars (1,500,000 cents), two people 20,300.00 dollars (2,030,000 cents), three people 25,600.00 dollars (2,560,000 cents), four people 30,900.00 dollars (3,090,000 cents), five people 36,200.00 dollars (3,620,000 cents), six people 41,500.00 dollars (4,150,000 cents), seven people 46,800.00 dollars (4,680,000 cents), and eight people 52,100.00 dollars (5,210,000 cents). It then computes the ratio of `declared_annual_income_cents` to that guideline (as a floating-point number, with no rounding). When the ratio is at most 1.30, the classifier returns `FREE`. When the ratio is greater than 1.30 but at most 1.85, the classifier returns `REDUCED`. Otherwise it returns `DENIED_PAID`. Both inequalities are non-strict on the upper edge of each band: a ratio exactly equal to 1.30 yields `FREE`, and a ratio exactly equal to 1.85 yields `REDUCED`.

On a successful approval, the application's `decided_tier` is set to the classifier's output, its `federal_poverty_guideline_cents` is set to the looked-up guideline for the application's `household_size`, the reviewer's `X-User-ID` is captured as `reviewer_user_id`, the student's `eligibility_tier` is updated to the new `decided_tier`, and the student's `eligibility_application_id` is set to the application's `id`. Both `Student.updated_at` and `Student.version` advance to reflect that mutation. The application's terminal `status` is `APPROVED`.

**Denial.** A reviewer denies a `SUBMITTED` application by transitioning it to `DENIED`. The transition requires the application to still be `SUBMITTED`, the acting reviewer to not be the owning parent (`ERR_SEGREGATION_OF_DUTIES` otherwise), and the request body to carry a non-empty `review_note` (`ERR_VALIDATION` otherwise). On success, the application's `decided_tier` is set to `DENIED_PAID`, the reviewer's `X-User-ID` is captured as `reviewer_user_id`, and — provided no other APPROVED application for the same student exists in the current school year — the student's `eligibility_tier` reverts to `PAID` and its `eligibility_application_id` is cleared to null. If another APPROVED application for that student already governs the current school year, the student keeps its existing tier.

**Concurrent decisioning.** When two reviewers race to decide the same application — one approving while another denies — exactly one decision wins by first-writer-wins on `FrlApplication.status`; the second discovers the application is no longer `SUBMITTED` and is rejected with `ERR_INVALID_STATE`.

### 3.5. Auto-Renewal Across School Years

A parent (or an audit officer acting on their behalf) may auto-renew a `DRAFT` application by pointing it at a prior school year's APPROVED application via `prior_year_application_id`. Auto-renewal is system-driven: the actor is recorded as `SYSTEM_AUTO_RENEW` rather than as the calling user.

The auto-renew transition runs four preconditions. First, the new application must still be in `DRAFT`. Second, `prior_year_application_id` must be non-null and must resolve to an `FrlApplication` whose `status` is `APPROVED`, whose `school_year_start` snapshot lies in the prior school year (defined as 365 calendar days before the new application's `school_year_start`, with a tolerance of plus or minus 5 days). Third, that prior application's `decided_tier` must be either `FREE` or `REDUCED` — a prior `DENIED_PAID` decision cannot be renewed. Fourth, the new application's `household_size` must match the prior application's `household_size` exactly, and the new application's `declared_annual_income_cents` must differ from the prior application's `declared_annual_income_cents` by no more than five percent in either direction. A failure of any of these conditions yields `ERR_RENEWAL_INELIGIBLE`.

On success, the application's `decided_tier` is set to the prior application's `decided_tier`, its `federal_poverty_guideline_cents` snapshot is filled in by looking up the constant for the new application's `household_size`, its `reviewer_user_id` is set to the sentinel `SYSTEM_AUTO_RENEW`, and the student's `eligibility_tier` is updated to the new `decided_tier` with `eligibility_application_id` pointing at this application's `id`. The application's terminal `status` is `RENEWED_FROM_PRIOR`.

### 3.6. Daily Meal Serving, Tier Snapshots, and the Parent Ledger

A meal serving is the operational heartbeat of the system. A `CafeteriaManager` records a serving by posting a payload that names the `student_id` and the `menu_item_id`; the `serving_date` is server-stamped from the logical clock's current UTC-midnight day.

The system runs four substantive preconditions before persisting the record. First, the student must not be allergen-blocked against this specific menu item: if any `ACTIVE` `AllergyProfileEntry` on the student has an `allergen` that appears in the menu item's `contains_allergens`, the serving is rejected with `ERR_ALLERGEN_BLOCK`. Second, the `MenuItem` must currently be `ACTIVE`; a serving against a `RETIRED` item surfaces `ERR_INVALID_STATE`. Third, the student must not already have a `SERVED` `MealServingRecord` for today — `meals_served_today_count` must be exactly zero at the moment of serving. A second serving for the same `(student_id, serving_date)` is rejected with `ERR_MEAL_ALREADY_SERVED_TODAY`; under concurrent cafeteria-manager submissions on the same student and date, exactly one record wins by first-writer-wins on that uniqueness key and the loser likewise receives `ERR_MEAL_ALREADY_SERVED_TODAY`. Fourth, if the student's eligibility tier is `PAID` at the moment of serving, the parent account's `prepaid_balance_cents` must be at least the menu item's `full_price_cents` (the comparison is non-strict, so a balance exactly equal to the price is permitted); otherwise the serving is rejected with `ERR_PREPAID_BALANCE_INSUFFICIENT`.

On a successful serving, the record is born `SERVED`. The system snapshots the student's current `eligibility_tier` into the record's `tier_at_serving` — this snapshot does not change later even when the student's tier is subsequently updated. The record's `charged_cents` is the **meal_charge_calc** result: zero cents when `tier_at_serving` is `FREE`, exactly 40 cents (the reduced co-pay) when `tier_at_serving` is `REDUCED`, and the menu item's `full_price_cents` when `tier_at_serving` is `PAID`. The record's `provisional_reimbursement_cents` is the **usda_reimbursement_provisional** result: zero cents when the menu item's `reimbursable` flag is false, otherwise 480 cents when `tier_at_serving` is `FREE`, 420 cents when `tier_at_serving` is `REDUCED`, or 50 cents when `tier_at_serving` is `PAID`. The provisional value is stamped onto the row and is never recomputed — it is a forward-looking estimate, contrasted with the chronological replay performed at claim finalisation (§3.7). Finally, when `charged_cents` is strictly greater than zero, the system appends a `PaidLedgerEntry` of `type` `CHARGE` with `amount_cents` equal to `charged_cents` and `serving_record_id` linking back to the new record; the parent account's `prepaid_balance_cents` decreases by that amount. The student's `meals_served_today_count` becomes 1.

**Voiding a serving.** A `CafeteriaManager` or an `AuditOfficer` may void a `SERVED` record. The void requires the record to currently be `SERVED` and requires that the record's `id` is not already locked inside a `UsdaReimbursementClaim` whose `status` is `SUBMITTED` or `FINALIZED` (see §3.7); a void on a locked record is rejected with `ERR_INVALID_STATE`. On success, the record's `status` flips to `VOIDED`. If the record's `charged_cents` was strictly greater than zero, the system appends a `PaidLedgerEntry` of `type` `REFUND` with `amount_cents` equal to the record's original `charged_cents` and `serving_record_id` pointing at the voided record; the parent's `prepaid_balance_cents` increases by that amount. The record's `provisional_reimbursement_cents` is reset to zero. If the voided record's `serving_date` is today, the student's `meals_served_today_count` decreases by 1.

**Refunds.** An `AuditOfficer` may also issue a stand-alone refund through the dedicated refund capability, naming the original `serving_record_id` in the body. The system locates the `PaidLedgerEntry` of `type` `CHARGE` linked to that `serving_record_id` on the parent account and appends a `REFUND` of equal `amount_cents`. The refund is full-only: if the requested refund amount (implicit in the original CHARGE) does not exactly equal the linked charge — or the linked charge cannot be found — the request is rejected with `ERR_REFUND_MISMATCH`. Partial refunds are not permitted.

**The waterfall balance — `parent_balance_waterfall`.** The parent account's `prepaid_balance_cents` is the deterministic replay of every `PaidLedgerEntry` on the account, processed in `occurred_at` ascending order with ties broken by entry `id` ascending. The running total starts at zero. For each entry: a `TOP_UP` adds its `amount_cents`; a `CHARGE` subtracts its `amount_cents`; a `REFUND` adds its `amount_cents`. Pre-commit validation for a new `CHARGE` simulates the running total after the charge would be applied and rejects with `ERR_PREPAID_BALANCE_INSUFFICIENT` if that simulated value would fall below zero (the comparison is non-strict, so a charge that drives the balance to exactly zero is permitted). Pre-commit validation for a new `REFUND` requires the refund's `amount_cents` to equal the linked `CHARGE.amount_cents` exactly; a partial-amount refund is rejected with `ERR_REFUND_MISMATCH`. Under concurrent operations on the same account — two top-ups racing with a charge — entries serialise on append order; a charge whose simulated balance would be negative at commit is rejected with `ERR_PREPAID_BALANCE_INSUFFICIENT` even if the snapshot at the start of validation looked feasible. `PaidLedgerEntry` rows carry a server-stamped `occurred_at` (ISO 8601 UTC, three fractional digits), an `amount_cents` (always positive — sign meaning is encoded by `type`), a `type`, an owning `parent_account_id`, and a `serving_record_id` linking back to the causing serving (null on `TOP_UP`).

### 3.7. USDA Reimbursement Claims

A USDA reimbursement claim accounts for a window of meal servings. An `AuditOfficer` creates a `DRAFT` claim with a `period_start` and a `period_end` (both UTC-midnight instants), where `period_end` must be greater than or equal to `period_start` — an inverted period is rejected with `ERR_VALIDATION`. The claim begins life with empty `serving_record_ids`, zero `provisional_total_cents`, and zero `final_reimbursement_cents`.

**Submission.** An audit officer submits a `DRAFT` claim. The submission requires the claim to still be `DRAFT`, requires `period_end` to be greater than or equal to `period_start`, and requires that no other claim within this district whose `status` is currently `SUBMITTED` or `FINALIZED` has a period that overlaps the new one. The overlap predicate is closed-closed: two periods overlap when the existing claim's `period_end` is greater than or equal to the new claim's `period_start` and the existing claim's `period_start` is less than or equal to the new claim's `period_end`. A submitted-overlap is rejected with `ERR_CLAIM_PERIOD_OVERLAP`. When two audit officers submit two `DRAFT` claims whose periods overlap simultaneously, exactly one transitions to `SUBMITTED` by first-writer-wins on the district-period overlap check; the loser receives `ERR_CLAIM_PERIOD_OVERLAP`. While the claim is `SUBMITTED`, contained meal-serving records are locked against voiding (see §3.6).

**Finalisation and chronological replay.** An audit officer finalises a `SUBMITTED` claim. The finalisation requires the claim to still be `SUBMITTED` and requires the acting `AuditOfficer` not to be the same operator who, acting as a `DistrictReviewer`, approved any FRL application whose minted student appears among the contained servings — the AuditOfficer who finalises must not have been the DistrictReviewer who approved a contained application (segregation of duties on claim finalisation; `ERR_SEGREGATION_OF_DUTIES` otherwise).

On success, the system snapshots into `serving_record_ids` the identifiers of every `MealServingRecord` whose `status` is `SERVED` and whose `serving_date` lies between the claim's `period_start` and `period_end` inclusive, ordered by `created_at` ascending with ties broken by record `id` ascending. The `provisional_total_cents` is then the simple sum of `provisional_reimbursement_cents` across those snapshot rows. The **usda_reimbursement_final** computation produces a separately-determined `final_reimbursement_cents` by chronological replay against current state rather than against the serving-time snapshots:

For each snapshot row, in the snapshot order (`created_at` ascending, ties broken by `id` ascending), the system evaluates a rate. A row whose `status` is no longer `SERVED` at the moment of finalisation (i.e., a row already voided despite the lock — for example, a record voided before the claim was submitted) contributes zero. Otherwise the system re-resolves the student's current `eligibility_tier` (not the row's `tier_at_serving` snapshot) and selects the rate: zero when the menu item's `reimbursable` is false, 480 cents when the re-resolved tier is `FREE`, 420 cents when the re-resolved tier is `REDUCED`, or 50 cents when the re-resolved tier is `PAID`. After the rate is selected, the system checks whether the student is currently allergen-blocked against this specific row's menu item — that is, whether any of the student's `ACTIVE` allergy entries has an `allergen` appearing in the row's `MenuItem.contains_allergens`; if so, the row's rate is overridden to zero. The selected (possibly overridden) rate is added to a running total. The claim's `final_reimbursement_cents` is the running total after all snapshot rows have been processed.

Because the final replay reads current eligibility and current allergy state rather than the SERVED-time snapshots, `final_reimbursement_cents` and `provisional_total_cents` can legitimately disagree whenever a student's `eligibility_tier` changed between serving and finalisation (for example, an FRL approval landed mid-period) or whenever an allergy entry was added that intersects a previously-served meal's labelled allergens. On a successful finalisation, the district's `usda_reimbursement_total_cents` increases by the new `final_reimbursement_cents`.

**Rejection.** An audit officer may instead transition a `SUBMITTED` claim to the terminal `REJECTED` state, which releases the lock that the submission placed on contained meal servings (so subsequent voids on those records become permitted again, subject to §3.6's own checks). The rejection requires the claim to still be `SUBMITTED`.

## 4. Endpoint Definitions

The table below summarises every endpoint exposed by the API. Newly-created resources are returned with HTTP 201; all other successful mutations and reads return HTTP 200. Request bodies, response bodies, and side effects are *not* described in this table — refer to the relevant §3 subsection to reconstruct the full behavioural contract for each endpoint.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/districts` | Create a District | `AuditOfficer` |
| GET | `/districts/{district_id}` | Get a District (with recomputed totals) | `Parent`, `DistrictReviewer`, `CafeteriaManager`, `AuditOfficer` |
| POST | `/districts/{district_id}/parent-accounts` | Create a ParentAccount | `AuditOfficer` |
| GET | `/districts/{district_id}/parent-accounts/{id}` | Get a ParentAccount with current balance | `Parent`, `AuditOfficer` |
| POST | `/districts/{district_id}/parent-accounts/{id}/top-up` | Add funds (append TOP_UP ledger entry) | `Parent` |
| POST | `/districts/{district_id}/parent-accounts/{id}/refund` | Refund a specific charge (full-only) | `AuditOfficer` |
| POST | `/districts/{district_id}/students` | Create a Student under a ParentAccount | `Parent`, `AuditOfficer` |
| GET | `/districts/{district_id}/students/{id}` | Get a Student (with derived eligibility and allergy block) | `Parent`, `DistrictReviewer`, `CafeteriaManager`, `AuditOfficer` |
| POST | `/districts/{district_id}/students/{student_id}/allergy-entries` | Add an allergen entry for a Student | `Parent` |
| DELETE | `/districts/{district_id}/students/{student_id}/allergy-entries/{id}` | Revoke an allergen entry | `Parent` |
| POST | `/districts/{district_id}/frl-applications` | Create a DRAFT FrlApplication | `Parent` |
| GET | `/districts/{district_id}/frl-applications/{id}` | Get an FrlApplication | `Parent`, `DistrictReviewer`, `AuditOfficer` |
| POST | `/districts/{district_id}/frl-applications/{id}/submit` | Parent submits a DRAFT application | `Parent` |
| POST | `/districts/{district_id}/frl-applications/{id}/request-info` | Reviewer requests more info | `DistrictReviewer` |
| POST | `/districts/{district_id}/frl-applications/{id}/resubmit` | Parent resubmits an INFO_REQUESTED application | `Parent` |
| POST | `/districts/{district_id}/frl-applications/{id}/approve` | Reviewer approves; mints student eligibility tier | `DistrictReviewer` |
| POST | `/districts/{district_id}/frl-applications/{id}/deny` | Reviewer denies | `DistrictReviewer` |
| POST | `/districts/{district_id}/frl-applications/{id}/auto-renew` | Auto-renew a DRAFT application from a prior year's APPROVED record | `Parent`, `AuditOfficer` |
| POST | `/districts/{district_id}/menu-items` | Create a MenuItem | `CafeteriaManager` |
| GET | `/districts/{district_id}/menu-items/{id}/nutrition-label` | Return computed nutrition label | `Parent`, `DistrictReviewer`, `CafeteriaManager`, `AuditOfficer` |
| POST | `/districts/{district_id}/menu-items/{id}/retire` | Retire a MenuItem | `CafeteriaManager` |
| POST | `/districts/{district_id}/meal-servings` | Record a meal served to a student | `CafeteriaManager` |
| POST | `/districts/{district_id}/meal-servings/{id}/void` | Void a SERVED meal (refund + zero out reimbursement) | `CafeteriaManager`, `AuditOfficer` |
| POST | `/districts/{district_id}/usda-claims` | Create a DRAFT claim with a period | `AuditOfficer` |
| GET | `/districts/{district_id}/usda-claims/{id}` | Get a claim and its current totals | `AuditOfficer` |
| POST | `/districts/{district_id}/usda-claims/{id}/submit` | Submit a DRAFT claim (locks contained servings) | `AuditOfficer` |
| POST | `/districts/{district_id}/usda-claims/{id}/finalize` | Finalize a SUBMITTED claim (chronological reimbursement) | `AuditOfficer` |
| POST | `/districts/{district_id}/usda-claims/{id}/reject` | Reject a SUBMITTED claim | `AuditOfficer` |
| POST | `/_clock/advance` | Advance the server logical clock (test-driving capability) | `AuditOfficer` |

## 5. Error Code Catalogue

The table below summarises every machine-readable `error_id` returned by the API alongside its HTTP status. Trigger conditions for each error live in the §2 and §3 narratives above — refer back to those subsections to determine which validation step emits each error.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_VALIDATION` | 422 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALLERGEN_BLOCK` | 409 |
| `ERR_DOCTOR_NOTE_REQUIRED` | 422 |
| `ERR_DUPLICATE_ALLERGEN` | 409 |
| `ERR_MEAL_ALREADY_SERVED_TODAY` | 409 |
| `ERR_PREPAID_BALANCE_INSUFFICIENT` | 409 |
| `ERR_CLAIM_PERIOD_OVERLAP` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RENEWAL_INELIGIBLE` | 422 |
| `ERR_REFUND_MISMATCH` | 422 |
| `ERR_PARENT_EMAIL_TAKEN` | 409 |
| `ERR_MENU_ITEM_IN_USE` | 409 |
| `ERR_VERSION_MISMATCH` | 412 |

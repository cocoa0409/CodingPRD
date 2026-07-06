# Mystery Shopping & CX-Audit Platform API — Product Requirements Document

## 1. Introduction

The Mystery Shopping & CX-Audit Platform connects retail, dining, and banking brands with a vetted pool of field shoppers who visit physical locations, perform scripted customer-experience audits, and submit photo and receipt evidence in exchange for a fee plus reimbursement of out-of-pocket spend. The platform exists to industrialize what has historically been a manual, fraud-prone, spreadsheet-driven business: certifying that a shopper is qualified for a given audit family, scheduling visits across rotating waves of work, capturing tamper-evident evidence, scoring the experience against client-defined rubrics, and ultimately paying shoppers and billing clients with full year-end tax compliance.

This API governs the entire lifecycle end to end. Clients register accounts, define locations and the scenario scripts that drive each audit, and group visits into scheduled waves. Shoppers register, pass certification exams per audit family, accept assignments, perform field work against a deadline, and upload evidence. Quality auditors review that evidence, score the visit twice — once as the shopper self-reports it and once as an audited figure after fraud and evidence review — and either validate, reject, or send the work back for revision. Finance staff then batch validated reimbursements into payouts, enforce a strict separation between who audited a shop and who pays for it, and apply IRS 1099 reporting thresholds. Because money, scores, and client billing all flow from the same validation event, the platform treats every cascade — a rejection reversing a payout, a dispute re-validating a rejected shop, a void returning batched money to the accrued pool — as an atomic, immediately-consistent operation.

A logical clock underpins every time-sensitive rule: assignment deadlines, the field windows that bound a wave, rotation cooldowns that prevent the same shopper from re-auditing the same location too soon, and the tax year that determines 1099 reporting. The clock is operator-controlled so that the platform's scheduled behaviors are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request, with two exceptions noted below, must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. A request that omits either header, or supplies a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The two exceptions are public self-registration of a client account and public self-registration of a shopper; these may be called by an unauthenticated caller.

The platform recognizes six roles, spelled exactly as follows: `Anonymous`, `PlatformAdmin`, `ClientManager`, `Shopper`, `QaValidator`, and `FinanceOfficer`. When a request carries a role that is recognized but not permitted to invoke the targeted operation under the access-control matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Validation checks are applied in a fixed precedence so that a request reports the highest-priority failure it triggers. The platform first checks the authentication headers (`ERR_UNAUTHENTICATED`); then whether the acting role is permitted on the endpoint (`ERR_FORBIDDEN_ROLE`); then that every referenced identifier resolves, path before body, left to right (`ERR_NOT_FOUND`, per Section 2.4); then resource ownership (`ERR_NOT_RESOURCE_OWNER`); then that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); and only after all of these does it evaluate the endpoint-specific business constraints described in Section 3. The optimistic-concurrency check on cancellation (`ERR_STALE_ASSIGNMENT_VERSION`) is evaluated within that business-constraint phase, after the state check.

Identity binding differs by role, and this binding is what ties `X-User-ID` to resource ownership:

- When `X-User-Role` is `ClientManager`, `X-User-ID` is the `id` of the acting `ClientAccount`; ownership checks on any resource that references a `ClientAccount` compare the resource's owning-client foreign key to `X-User-ID`. A `ClientManager` acting on a wave, script, or location whose owning client is not the manager's own `ClientAccount` is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Shopper`, `X-User-ID` is the `id` of the acting `Shopper`; ownership checks on any `Assignment` compare the assignment's `shopper_id` to `X-User-ID`. A shopper acting on an assignment that is not their own is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `QaValidator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `validated_by_user_id` on an `Assignment` when a validator moves that assignment to `VALIDATED` or `REJECTED`, but it does not compare it to any entity's `id`.
- When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, but it is compared against an assignment's recorded `validated_by_user_id` for the separation-of-duties checks described in Section 2.8.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifier Resolution

Every primary resource — `ClientAccount`, `Shopper`, `Location`, `ScenarioScript`, `ShopWave`, `Assignment`, `EvidenceItem`, `ScoreCard`, `Reimbursement`, `Dispute`, and `PayoutBatch` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it supports the optimistic concurrency control described in Section 2.7.

One entity is deliberately leaner: a `CertificationAttempt` is an immutable record. It carries only an `id` and a `created_at`; it has no `updated_at` field and no `version` field, because once an examiner records an attempt it is never modified.

When a resource is mutated, both `updated_at` and `version` advance together. This includes mutations that arise as side effects of another operation — for example, when validating one assignment increments a wave's `validated_shop_count`, the wave's `updated_at` and `version` both move; when a no-show penalty lowers a shopper's `reliability_score`, the shopper's `updated_at` and `version` both move.

For any endpoint whose path contains more than one identifier, the server validates identifiers left to right. A request is rejected with `ERR_NOT_FOUND` for the first path segment whose identifier does not resolve to an existing resource, before any later segment or any body foreign key is examined. After all path identifiers resolve, body foreign keys are resolved in turn, and an unresolved body reference likewise yields `ERR_NOT_FOUND`.

### 2.5. Monetary Values, Distance, and Rounding

All monetary amounts are stored and returned as integer cents. The platform performs the following roundings with the round-half-up convention and at no other point:

- Mileage reimbursement rounds half up exactly once, at the single multiplication of distance by the per-kilometer rate.
- The reliability bonus on a shopper fee rounds half up exactly once, on the bonus term.
- Each section-weighted score (estimated or audited) rounds half up exactly once, after the full weighted sum is computed — the system sums first and rounds once, never rounding each section and then summing.
- The travel distance between a shopper's home and a location is computed once and rounded half up to two decimal places.

Aggregations that are pure integer multiplies — for example a wave's billable amount — are computed exactly with no rounding.

### 2.6. State, Version, and Cascade Consistency

All cascades complete atomically within the request that triggers them. When a single operation touches more than one entity — validating an assignment, reversing a reimbursement, resolving a dispute — every affected entity is mutated in the same transaction, and every such mutation advances that entity's `updated_at` and `version`. There is no eventual reconciliation; if any part of a cascade cannot complete, the whole request fails and nothing is mutated.

Counters that the platform maintains as derived state — a wave's `validated_shop_count` and `client_billable_cents`, a shopper's `open_assignment_count`, `reliability_score`, and `ytd_paid_cents` — are kept consistent by the side effects described throughout Section 3. Where a counter could otherwise drift through repeated increments and decrements, the platform recomputes it from scratch rather than nudging it (see the billable recomputation in Section 3.6).

### 2.7. Optimistic Concurrency Control on Assignment Cancellation

Cancelling an assignment is the one write in this platform guarded by optimistic concurrency control. A cancel request must carry `expected_assignment_version`, a non-optional field whose value is the `version` of the target `Assignment` that the client last observed. If `expected_assignment_version` does not equal the assignment's current `version` at the moment the server processes the cancel, the request is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412). The canonical situation this prevents: a manager reads an assignment and decides to cancel it, but in the interim the shopper accepted it — which advanced the assignment's `version` — so the manager's cancel still carries the pre-acceptance version and is refused, forcing the manager to re-read current state before cancelling. No other endpoint takes a version field, and no other write performs this check.

### 2.8. Separation of Duties and Payout Governance

The platform enforces a strict separation between the person who audits a shop and the person who pays for it. The `QaValidator` who moves an assignment to `VALIDATED` (or `REJECTED`) has their `X-User-ID` recorded on the assignment as `validated_by_user_id`. When a `FinanceOfficer` later batches or pays the reimbursement that flows from that assignment, the platform compares the officer's `X-User-ID` against the assignment's `validated_by_user_id`; if they are equal, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. This check applies both when collecting reimbursements into a batch and when paying a batch.

A second governance gate is tax-driven. Paying a batch that has been determined to require 1099 reporting demands that the payee shopper's `tax_id_on_file` flag is true; if a 1099-required batch is paid for a shopper whose `tax_id_on_file` is false, the request is rejected with `ERR_TAX_ID_REQUIRED`.

### 2.9. The Logical Clock and Scheduled Behaviors

Time in this platform is supplied by a server-held logical clock, not wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an operator explicitly sets it the clock never falls back to wall-clock time. A `PlatformAdmin` may move the clock to any instant by supplying `to_iso8601`. The clock governs four time-sensitive behaviors: an assignment's `due_at` deadline; the field window that bounds a wave; the rotation cooldown that keeps a shopper off the same location too soon; and the tax year (the UTC year of the clock) that a payout batch is filed under and that scopes a shopper's year-to-date paid total.

## 3. Business Logic & Workflows

### 3.1. Onboarding Clients and Shoppers

A client organization joins the platform through public self-registration, supplying a `company_name`, a `billing_email` where invoices are sent, and a `fee_per_completed_shop_cents` — the platform fee billed to the client for each shop that reaches validation, which must be zero or greater. A new `ClientAccount` begins life `ACTIVE`. A `PlatformAdmin` may move it to `SUSPENDED`; while a client is `SUSPENDED`, the platform refuses to publish new waves or scripts for that client and refuses to create assignments against it.

Shoppers also self-register publicly, providing their `full_name` (their legal name as the 1099 payee), a unique `email`, and a home position as `home_lat` and `home_lng` decimal-degree coordinates. A shopper may optionally declare at registration whether a W-9 / TIN is already on file via `tax_id_on_file`; if omitted it is false. A newly registered shopper starts in `REGISTERED` status with a `reliability_score` of 100.0 and a `certification_score` of 0. The `reliability_score` is a rotation-ranking figure that lives in the range from 0 to 100 inclusive; `ytd_paid_cents` and `open_assignment_count` both start at 0. A shopper's `tax_id_on_file` can later be updated when their W-9 is received, which sets the flag to the supplied value.

A `REGISTERED` shopper cannot be assigned to any work. To become eligible, the shopper must be certified.

### 3.2. Certification and Shopper Standing

Certification is performed by a `QaValidator`, who records a certification attempt for a shopper by entering a `raw_score` between 0 and 100 inclusive together with the `scenario_family` the attempt certifies — one of `RETAIL`, `DINING`, or `BANKING`. A `raw_score` outside 0 to 100, or an invalid `scenario_family` enum, is rejected with `ERR_INVALID_REQUEST`. Each attempt is stamped with the candidate's `shopper_id` and an `attempt_index`, the 1-based ordinal of this attempt among the shopper's attempts in that same `scenario_family`, ordered by creation time.

The attempt's `outcome` is computed: it is `PASSED` when the `raw_score` is at least 70, and `FAILED` otherwise. When a `REGISTERED` shopper's attempt passes — that is, the resulting `raw_score` is at least 70 — the shopper's `certification_score` is set to that attempt's `raw_score` and the shopper transitions `REGISTERED → CERTIFIED`. A failing attempt (a `raw_score` below 70) leaves the shopper `REGISTERED` and leaves `certification_score` unchanged. An already-`CERTIFIED` shopper may re-certify into a new family: when a `CERTIFIED` shopper records another attempt whose `raw_score` is at least 70, the shopper stays `CERTIFIED` (a self-loop, no status change) and `certification_score` is refreshed to the greater of its current value and the new attempt's `raw_score`. A passing attempt records and credits a certified family only when the shopper is `REGISTERED` or `CERTIFIED`; recording an attempt for a `SUSPENDED` shopper always succeeds and persists the immutable attempt record, but it never changes the shopper's status, `certification_score`, or set of certified families, regardless of `raw_score`.

A `PlatformAdmin` may suspend a shopper, moving them `CERTIFIED → SUSPENDED`, but only when the shopper is currently `CERTIFIED` and their `open_assignment_count` is exactly 0; a suspend attempt on a shopper with one or more open assignments is rejected with `ERR_SHOPPER_HAS_OPEN_ASSIGNMENTS`. A `SUSPENDED` shopper may be reinstated by a `PlatformAdmin`, moving them `SUSPENDED → CERTIFIED`.

### 3.3. Client Catalog: Locations, Scripts, and Waves

A `ClientManager` (or a `PlatformAdmin`) builds out a client's catalog. A **Location** is created under a client with a `label`, a site position given as `lat` and `lng` decimal degrees, and the `scenario_family` a shopper must be certified in to audit there — `RETAIL`, `DINING`, or `BANKING`. Each location records its owning `client_id`. A location starts `ACTIVE`; a `ClientManager` may retire it, moving it `ACTIVE → RETIRED`, after which it accepts no new assignments.

A **ScenarioScript** is the rubric that backs an audit. It is created under a client with a `title`, a `scenario_family`, a `required_photo_count` (the minimum number of approved photo evidence items needed to submit, zero or greater), a `receipt_required` flag (whether at least one approved receipt evidence item is needed to submit; defaults to true), a `reimburse_cap_cents` (the maximum out-of-pocket reimbursed per assignment, zero or greater), a `base_fee_cents` (the flat shopper fee paid on validation before any reliability bonus, zero or greater), a `weights_json` object of section weights, and a `passing_score` between 0 and 100 inclusive (the audited score at or above which the shop is reported as a pass). The script records its owning `client_id` and starts in `DRAFT`.

The `weights_json` object maps each scoring section to a non-negative weight, and across all sections the weights must sum to 1.00 when rounded half up to two decimal places. A script moves `DRAFT → PUBLISHED` only when it is currently `DRAFT`, its owning client is `ACTIVE`, and its weights satisfy that sum-to-1.00 rule; these are checked in that order, so a publish on a non-`DRAFT` script is rejected with `ERR_INVALID_STATE`, a publish whose weights are negative anywhere or do not sum to 1.00 (round half up, two decimal places) is rejected with `ERR_WEIGHTS_NOT_NORMALIZED`, and a publish whose owning client is not `ACTIVE` is rejected with `ERR_FAMILY_MISMATCH`. Only a `PUBLISHED` script may back an assignment. A `PUBLISHED` script may be archived, moving it `PUBLISHED → ARCHIVED`, but only when no assignment referencing the script is in a non-terminal state — that is, every referencing assignment must be `VALIDATED`, `REJECTED`, `CANCELLED`, or `EXPIRED`; otherwise the archive is rejected with `ERR_SCRIPT_IN_USE`. `ARCHIVED` is terminal for a script.

A **ShopWave** groups visits for scheduling. It is created under a client with a `name`, a `field_window_start` and a `field_window_end` (both ISO 8601 UTC), and an optional `rotation_cooldown_days` that defaults to 30 and must be zero or greater. The wave records its owning `client_id` and starts in `DRAFT`. The `field_window_end` must be strictly after `field_window_start`; a window that violates this — whether at wave creation or at publish — is rejected with `ERR_INVALID_WINDOW`. A wave moves `DRAFT → PUBLISHED` only when it is currently `DRAFT`, its window is valid, and its owning client is `ACTIVE`; these are checked in that order, so a publish on a non-`DRAFT` wave is rejected with `ERR_INVALID_STATE`, an invalid window with `ERR_INVALID_WINDOW`, and an owning client that is not `ACTIVE` with `ERR_FAMILY_MISMATCH`. Assignments may be created only while a wave is `PUBLISHED`. A `PUBLISHED` wave may be closed, moving it `PUBLISHED → CLOSED`, but only when no assignment in the wave is still in `ASSIGNED`, `IN_FIELD`, `SUBMITTED`, or `REVISION_REQUESTED` — in other words, every assignment in the wave has reached a terminal state; a close attempt while any assignment is still live is rejected with `ERR_WAVE_NOT_DRAINED`. `CLOSED` is terminal for a wave. A wave also exposes two computed counters, `validated_shop_count` and `client_billable_cents`, both starting at 0 and maintained as described in Section 3.6.

### 3.4. Creating an Assignment

Creating an **Assignment** is the act that binds a shopper, a location, a script, and a wave together for a single audit. A `ClientManager` or `PlatformAdmin` supplies `wave_id`, `shopper_id`, `location_id`, `script_id`, and a `due_at` deadline. The new assignment starts in `ASSIGNED`.

Several referential and temporal gates apply at creation, and each carries a distinct error. The shopper must be `CERTIFIED` and certified in the location's `scenario_family`; a non-certified shopper, or one not certified in that family, is rejected with `ERR_SHOPPER_NOT_CERTIFIED`. The location's `scenario_family` and the script's `scenario_family` must be identical, the script must be `PUBLISHED`, the wave must be `PUBLISHED`, the location must be `ACTIVE`, and the owning client must be `ACTIVE`; any of these failing is rejected with `ERR_FAMILY_MISMATCH`. The `due_at` must fall within the wave's field window, at or after `field_window_start` and at or before `field_window_end` (both ends inclusive); a deadline outside that window is rejected with `ERR_DUE_OUTSIDE_WINDOW`. Finally, a rotation cooldown applies: the shopper must not have another assignment to the *same* location whose `due_at` falls within `rotation_cooldown_days` before the new `due_at`; concretely, the conflict window is the closed interval from the new `due_at` minus `rotation_cooldown_days` (computed as a calendar-day offset) through the new `due_at` itself, both endpoints inclusive, and any existing same-shopper same-location assignment whose `due_at` lies anywhere in that interval — regardless of that assignment's status — triggers `ERR_ROTATION_COOLDOWN`. A too-soon repeat at the same location is thus rejected with `ERR_ROTATION_COOLDOWN`.

When these gates pass, the platform pins the route by computing `travel_distance_km` once and freezing it. This is the great-circle (haversine) distance from the shopper's home position to the location, using an Earth radius of 6371.0088 kilometers. The latitude and longitude differences (location minus home) are taken in radians; the haversine term is the square of the sine of half the latitude difference, plus the cosine of the home latitude times the cosine of the location latitude times the square of the sine of half the longitude difference; the distance is twice the Earth radius times the arcsine of the square root of that term. The result is rounded half up to two decimal places and stored as `travel_distance_km`, where it pins all later mileage reimbursement.

### 3.5. Field Work: Acceptance, Evidence, Scoring, and Submission

A shopper takes up an assignment by accepting it, which moves it `ASSIGNED → IN_FIELD`. Acceptance requires the assignment to be `ASSIGNED`, the acting shopper to be the assignment's own shopper, and the logical clock to be at or before the assignment's `due_at`. Accepting increments the shopper's `open_assignment_count` by 1.

While `IN_FIELD`, the shopper assembles the case. Each **EvidenceItem** uploaded onto the assignment carries a `kind` of `PHOTO` or `RECEIPT`, an `object_uri` pointing at the stored artifact, an optional `section_key` naming the scoring section it substantiates, and — for receipts — a `receipt_amount_cents` giving the out-of-pocket amount on the receipt (zero or greater; 0 for photos). Each item records its owning `assignment_id` and begins with `review_status` of `PENDING`. When a `section_key` is supplied it must be one of the keys of the backing script's `weights_json`. A `QaValidator` reviews each item, moving its `review_status` from `PENDING` to `APPROVED` or `FLAGGED` according to the supplied `decision` (the string `APPROVE` maps to `APPROVED` and `FLAG` maps to `FLAGGED`; any other value is rejected with `ERR_INVALID_REQUEST`). Reviewing an item whose `review_status` is not `PENDING` is rejected with `ERR_INVALID_STATE`. Flagged evidence does not count toward the script's submission requirements, and a flagged receipt does not count toward reimbursable spend.

The shopper also creates a **ScoreCard** for the assignment, supplying `section_scores_json` — a map from each scoring section to a self-reported raw score from 0 to 100. The keys of `section_scores_json` must be exactly the keys of the script's `weights_json`, no missing keys and no extra keys; a mismatch is rejected with `ERR_SECTION_KEYS_MISMATCH`. A new scorecard begins with `audit_status` of `DRAFT` and `fraud_status` of `UNCHECKED`; these two dimensions evolve independently. Its computed `estimated_score` starts at 0 and its `audited_score` starts unset.

Submitting moves the assignment `IN_FIELD → SUBMITTED`. Submission requires the assignment to be `IN_FIELD`, the acting shopper to be its own shopper, and the logical clock to be at or before `due_at`. It also requires evidence completeness: the count of `APPROVED` `PHOTO` evidence items must be at least the script's `required_photo_count`; if the script's `receipt_required` is true there must be at least one `APPROVED` `RECEIPT` item; and a scorecard must exist. An incomplete submission — too few approved photos, a missing required approved receipt, or no scorecard — is rejected with `ERR_EVIDENCE_INCOMPLETE`. On a successful submission the platform increments `submission_count` by 1 (this counts every entry into `SUBMITTED`, including revision resubmissions), sets `claimed_out_of_pocket_cents` to the sum of `receipt_amount_cents` over the `APPROVED` `RECEIPT` items, computes the provisional reimbursement, and computes the estimated score.

The **provisional reimbursement** trusts the shopper's claim. The mileage component is the frozen `travel_distance_km` multiplied by 35 cents per kilometer, rounded half up at that single multiply. The provisional out-of-pocket figure is the assignment's `claimed_out_of_pocket_cents`, taken as-is. That out-of-pocket figure is then capped at the script's `reimburse_cap_cents` — that is, the smaller of the two is used. The provisional `reimbursable_cents` is the capped out-of-pocket plus the mileage component, with no further rounding.

The **estimated score** is the shopper's self-reported weighted score. For each section in the script's `weights_json`, the section's weight is multiplied by the shopper's reported score for that section in `section_scores_json`; those products are summed across all sections, and that single sum is rounded half up to an integer from 0 to 100. Every section the shopper scored counts at face value with no flag adjustment. The result is stored as `estimated_score`.

### 3.6. QA Disposition: Validate, Request Revision, or Reject

After submission, a `QaValidator` dispositions the shop. Three outward branches leave `SUBMITTED`, and each is specified in full below; a disposition called from any state other than `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

Independently of disposition, a validator may run a fraud check on the scorecard, supplying a `decision` (the string `HOLD` is the hold decision and `CLEAR` is the clear decision; any other value is rejected with `ERR_INVALID_REQUEST`). If the assignment has no scorecard the request is rejected with `ERR_NOT_FOUND`. A fraud check with a hold `decision` moves `fraud_status` from `UNCHECKED` to `FRAUD_HOLD`; a clear `decision` moves `fraud_status` from `UNCHECKED` to `CLEARED`, or from `FRAUD_HOLD` to `CLEARED`. Any fraud-check whose current `fraud_status` does not admit the requested transition — a hold when `fraud_status` is not `UNCHECKED`, or a clear when `fraud_status` is already `CLEARED` — is rejected with `ERR_INVALID_STATE`. A `FRAUD_HOLD` blocks validation until it is cleared.

**Validation** moves the assignment `SUBMITTED → VALIDATED`. It requires the assignment to be `SUBMITTED`, the scorecard's `fraud_status` to not be `FRAUD_HOLD`, and the shopper to not be `SUSPENDED`. On validation the platform performs the full settlement cascade atomically: it computes the audited score and sets the scorecard's `audit_status` to `AUDITED`; it computes the final reimbursement and the shopper fee; it sets the assignment to `VALIDATED` and records the validator's `X-User-ID` as `validated_by_user_id`; it creates a `Reimbursement` in `ACCRUED` status whose `amount_cents` is the final `reimbursable_cents` plus the `shopper_fee_cents`; it increments the wave's `validated_shop_count` by 1 and recomputes the wave's `client_billable_cents`; and it decrements the shopper's `open_assignment_count` by 1.

The **audited score** re-runs the weighted scoring with one adjustment: any section that has a `FLAGGED` evidence item contributes 0, and the weights are *not* renormalized. For each section in the script's `weights_json`, the contribution is the section's weight times the shopper's reported score for that section unless that section has a flagged evidence item, in which case the contribution is 0; the contributions are summed, and that single sum is rounded half up to an integer from 0 to 100, stored as `audited_score`. Because flagged sections drop to zero without the remaining weights being scaled back up, the audited score is at most the estimated score. A section whose tagged evidence is flagged is zeroed in this computation.

The **final reimbursement** differs from the provisional one only in its out-of-pocket figure: instead of the shopper's claim, it counts only the `receipt_amount_cents` of `RECEIPT` evidence items whose `review_status` is `APPROVED`. Flagged receipts are excluded, so the final out-of-pocket is at most the provisional one. That final out-of-pocket figure is capped at the script's `reimburse_cap_cents` (the smaller of the two), and the final `reimbursable_cents` is the capped out-of-pocket plus the same mileage component (frozen `travel_distance_km` times 35 cents per kilometer, rounded half up at that single multiply), with no further rounding.

The **shopper fee** is the script's `base_fee_cents` plus a reliability bonus selected by the shopper's `reliability_score` at validation time. When the `reliability_score` is at least 90 the bonus is 20 percent of the base; otherwise when it is at least 75 the bonus is 10 percent of the base; otherwise the bonus is 0. The bonus term is the base times the bonus percentage rounded half up, and `shopper_fee_cents` is the base plus that rounded bonus. The tier boundaries use at-least comparisons, so a `reliability_score` of exactly 90 earns the 20 percent tier and exactly 75 earns the 10 percent tier.

The wave's **billable** counter is recomputed from scratch on every change rather than nudged, to keep it from drifting. The platform counts the assignments in the wave whose status is `VALIDATED`, stores that count as `validated_shop_count`, and sets `client_billable_cents` to that count multiplied by the owning client's `fee_per_completed_shop_cents` (an exact integer multiply, no rounding). This recompute runs on every validation increment and on every reversal decrement.

**Requesting a revision** moves the assignment `SUBMITTED → REVISION_REQUESTED`. It is permitted only while the assignment is `SUBMITTED` and its `submission_count` is at most 2; a request-revision when `submission_count` exceeds 2 is rejected with `ERR_REVISION_LIMIT_REACHED`. Requesting a revision sets every `APPROVED` evidence item on the assignment back to `PENDING`, so the shopper must shepherd that evidence through review again. From `REVISION_REQUESTED` the shopper resumes, moving the assignment back to `IN_FIELD`; resuming requires the assignment to be `REVISION_REQUESTED`, the acting shopper to be its own shopper, and the clock to be at or before `due_at`. This forms the revision cycle `SUBMITTED → REVISION_REQUESTED → IN_FIELD → SUBMITTED`.

**Rejection** moves the assignment `SUBMITTED → REJECTED`. It requires only that the assignment is `SUBMITTED`. Rejection records the validator's `X-User-ID` as `validated_by_user_id`, decrements the shopper's `reliability_score` by 10 (floored at 0), decrements the shopper's `open_assignment_count` by 1, and sets both `reimbursable_cents` and `shopper_fee_cents` to 0. A rejection before validation creates no reimbursement.

### 3.7. Deadlines, Cancellation, and Expiry

A `ClientManager` or `PlatformAdmin` may cancel an assignment while it is `ASSIGNED`, `IN_FIELD`, or `REVISION_REQUESTED`. Cancellation is the optimistic-concurrency-guarded write described in Section 2.7: it carries `expected_assignment_version`, and a value that does not match the assignment's current `version` is rejected with `ERR_STALE_ASSIGNMENT_VERSION`. A successful cancel sets the assignment to `CANCELLED`, increments the assignment's `version` by 1, and — when the assignment had been `IN_FIELD` or `REVISION_REQUESTED` — decrements the shopper's `open_assignment_count` by 1. `CANCELLED` is terminal.

The platform also expires overdue work through a clock-driven deadline sweep, available to a `PlatformAdmin`. When the logical clock has advanced past an assignment's `due_at` and the assignment is still in `ASSIGNED`, `IN_FIELD`, or `REVISION_REQUESTED`, the sweep moves it to `EXPIRED`, decrements the shopper's `reliability_score` by 20 (floored at 0), and — when the assignment had been `IN_FIELD` or `REVISION_REQUESTED` — decrements the shopper's `open_assignment_count` by 1. `EXPIRED` is terminal.

### 3.8. Disputes and Their Cascades

Either a `Shopper` or a `ClientManager` may open a **Dispute** against an assignment that is `VALIDATED` or `REJECTED`. The opener supplies a `reason` — `REJECTION_APPEAL`, `SCORE_CHALLENGE`, or `REIMBURSE_SHORTFALL` — and the platform records the dispute's owning `assignment_id`, sets `opened_by_role` to `SHOPPER` or `CLIENT` from the acting role, starts `round_index` at 1, and sets the dispute to `UNDER_REVIEW`. At most one dispute may be live on an assignment at a time: opening a second while one is still non-terminal is rejected with `ERR_DISPUTE_ALREADY_OPEN`.

A dispute negotiates through a capped cycle. A `QaValidator` may counter a dispute that is `UNDER_REVIEW`, moving it to `COUNTERED`, but only while its `round_index` is below 3; a counter when `round_index` has reached 3 is rejected with `ERR_DISPUTE_ROUNDS_EXHAUSTED`. The shopper who owns the parent assignment may respond to a `COUNTERED` dispute, which increments `round_index` by 1 and returns the dispute to `UNDER_REVIEW`, closing the `UNDER_REVIEW → COUNTERED → UNDER_REVIEW` loop. The owning shopper may also withdraw a dispute that is `UNDER_REVIEW`, but only when its `opened_by_role` is `SHOPPER` and the acting shopper owns the parent assignment, moving it to `WITHDRAWN`.

A `FinanceOfficer` resolves a dispute that is `UNDER_REVIEW` with a supplied `decision` (the string `UPHOLD` is the uphold decision and `OVERTURN` is the overturn decision; any other value is rejected with `ERR_INVALID_REQUEST`). Upholding moves the dispute `UNDER_REVIEW → UPHELD`: the original decision stands and nothing cascades. Overturning moves the dispute `UNDER_REVIEW → OVERTURNED` and requires that the parent assignment is `VALIDATED` (for a `SCORE_CHALLENGE` or `REIMBURSE_SHORTFALL`) or `REJECTED` (for a `REJECTION_APPEAL`); an overturn whose parent assignment is not in the required state is rejected with `ERR_INVALID_STATE`. Overturning triggers one of two cascades, keyed on the dispute's `reason`:

- **Rejection-appeal cascade.** When the reason is `REJECTION_APPEAL`, the previously `REJECTED` assignment is re-validated. The platform recomputes the final reimbursement and the shopper fee, sets the assignment to `VALIDATED`, creates a `Reimbursement` in `ACCRUED` status whose `amount_cents` is the final `reimbursable_cents` plus `shopper_fee_cents`, increments the wave's `validated_shop_count` and recomputes its `client_billable_cents`, and restores the shopper's `reliability_score` by 10 (capped at 100), undoing the rejection penalty. This is the only path that leaves the `REJECTED` state, and it is system-driven.
- **Re-pricing cascade.** When the reason is `SCORE_CHALLENGE` or `REIMBURSE_SHORTFALL` on a `VALIDATED` assignment, the platform recomputes the assignment's final `reimbursable_cents` with an override flag and updates the `amount_cents` of the linked `ACCRUED` reimbursement; if that reimbursement has already been collected into a batch, the batch's `gross_amount_cents` is recomputed in turn.

### 3.9. Reimbursements, Payout Batches, and 1099 Reporting

Each validation books a **Reimbursement** that records the owning `assignment_id`, the payee `shopper_id`, and an `amount_cents` equal to the final reimbursable amount plus the shopper fee. A reimbursement begins `ACCRUED`. A reimbursement may be `REVERSED` as a system side effect — either through a dispute cascade reversal or through a post-validation rejection. When a reimbursement is reversed from `ACCRUED`, the wave's `validated_shop_count` is decremented and its `client_billable_cents` recomputed.

A `FinanceOfficer` collects a shopper's `ACCRUED` reimbursements into a **PayoutBatch** by supplying the `shopper_id` and the `reimbursement_ids` to include. Each collected reimbursement must currently be `ACCRUED`; attempting to batch one that is not `ACCRUED` is rejected with `ERR_REIMBURSEMENT_NOT_ACCRUED`. Collecting moves each reimbursement `ACCRUED → BATCHED` and stamps it with the batch's `payout_batch_id`. The batch records the payee `shopper_id`, sets its `tax_year` to the UTC year of the logical clock at batch creation, sums the `amount_cents` of its members into `gross_amount_cents`, and starts in `OPEN`. The separation-of-duties rule of Section 2.8 applies here: the officer's `X-User-ID` must not equal the `validated_by_user_id` of any included assignment, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Paying a batch moves it `OPEN → PAID`. Payment requires the batch to be `OPEN`, every member reimbursement to still be `BATCHED` (none reversed since batching), and — when the batch requires 1099 reporting — the payee's `tax_id_on_file` to be true (otherwise `ERR_TAX_ID_REQUIRED`); the separation-of-duties rule also applies at pay time. On payment the batch becomes `PAID`, each member reimbursement becomes `PAID`, the shopper's `ytd_paid_cents` is incremented by the batch's `gross_amount_cents`, and the platform evaluates the 1099 threshold.

The **1099 determination** fires only on the batch that crosses the threshold. Let the prior year-to-date be the shopper's `ytd_paid_cents` paid in this `tax_year` before this batch, and the new year-to-date be that prior figure plus the batch's `gross_amount_cents`. The batch's `requires_1099` is true exactly when the new year-to-date is at least 60000 cents and the prior year-to-date was below 60000 cents. A batch crossing exactly to 60000 cents triggers 1099 reporting; one reaching only 59999 does not; and a later batch in the same year that is already above the threshold does not re-fire, because the prior figure is no longer below it.

A `FinanceOfficer` may void an `OPEN` batch, moving it `OPEN → VOIDED`; voiding returns each member reimbursement to `ACCRUED` and clears its `payout_batch_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Register a client account | Anonymous, PlatformAdmin |
| GET | `/clients/{id}` | Fetch a client account | PlatformAdmin, ClientManager |
| POST | `/clients/{id}/suspend` | Suspend a client | PlatformAdmin |
| POST | `/clients/{id}/locations` | Create a location under a client | ClientManager, PlatformAdmin |
| GET | `/clients/{id}/locations` | List a client's locations | ClientManager, PlatformAdmin |
| POST | `/locations/{id}/retire` | Retire a location | ClientManager, PlatformAdmin |
| POST | `/clients/{id}/scripts` | Create a draft scenario script | ClientManager, PlatformAdmin |
| GET | `/clients/{id}/scripts` | List a client's scripts | ClientManager, PlatformAdmin |
| POST | `/scripts/{id}/publish` | Publish a draft script | ClientManager |
| POST | `/scripts/{id}/archive` | Archive a published script | ClientManager |
| POST | `/clients/{id}/waves` | Create a draft shop wave | ClientManager, PlatformAdmin |
| GET | `/clients/{id}/waves` | List a client's waves | ClientManager, PlatformAdmin |
| GET | `/waves/{id}` | Fetch a wave with computed counters | ClientManager, PlatformAdmin |
| POST | `/waves/{id}/publish` | Publish a wave | ClientManager |
| POST | `/waves/{id}/close` | Close a fully-drained wave | ClientManager |
| POST | `/shoppers` | Register a shopper | Anonymous, PlatformAdmin |
| GET | `/shoppers/{id}` | Fetch a shopper | PlatformAdmin, QaValidator, FinanceOfficer, Shopper |
| PATCH | `/shoppers/{id}/tax-profile` | Set the tax-id-on-file flag | PlatformAdmin, FinanceOfficer, Shopper |
| POST | `/shoppers/{id}/certification-attempts` | Record a certification attempt | QaValidator |
| GET | `/shoppers/{id}/certification-attempts` | List a shopper's certification attempts | QaValidator, PlatformAdmin |
| POST | `/shoppers/{id}/suspend` | Suspend a certified shopper | PlatformAdmin |
| POST | `/shoppers/{id}/reinstate` | Reinstate a suspended shopper | PlatformAdmin |
| POST | `/assignments` | Create an assignment | ClientManager, PlatformAdmin |
| GET | `/assignments/{id}` | Fetch an assignment | ClientManager, PlatformAdmin, QaValidator, FinanceOfficer, Shopper |
| GET | `/assignments` | List/filter assignments | ClientManager, PlatformAdmin, QaValidator, FinanceOfficer, Shopper |
| POST | `/assignments/{id}/accept` | Shopper accepts the assignment | Shopper |
| POST | `/assignments/{id}/evidence` | Upload a photo/receipt evidence item | Shopper |
| GET | `/assignments/{id}/evidence` | List an assignment's evidence | Shopper, QaValidator, ClientManager, PlatformAdmin |
| POST | `/evidence/{id}/review` | Approve or flag an evidence item | QaValidator |
| POST | `/assignments/{id}/scorecard` | Create the scorecard | Shopper |
| GET | `/assignments/{id}/scorecard` | Fetch the scorecard | Shopper, QaValidator, ClientManager, PlatformAdmin |
| POST | `/assignments/{id}/scorecard/fraud-check` | Set the scorecard fraud status | QaValidator |
| POST | `/assignments/{id}/submit` | Submit the field work | Shopper |
| POST | `/assignments/{id}/validate` | Validate the shop | QaValidator |
| POST | `/assignments/{id}/request-revision` | Return the shop for revision | QaValidator |
| POST | `/assignments/{id}/resume` | Resume after revision | Shopper |
| POST | `/assignments/{id}/reject` | Reject a submitted shop | QaValidator |
| POST | `/assignments/{id}/cancel` | Cancel a non-terminal assignment | ClientManager, PlatformAdmin |
| POST | `/assignments/{id}/sweep-deadline` | Expire an overdue assignment | PlatformAdmin |
| POST | `/assignments/{id}/disputes` | Open a dispute | Shopper, ClientManager |
| GET | `/assignments/{id}/disputes` | List an assignment's disputes | Shopper, ClientManager, QaValidator, FinanceOfficer, PlatformAdmin |
| POST | `/disputes/{id}/counter` | Counter a dispute | QaValidator |
| POST | `/disputes/{id}/respond` | Respond to a counter | Shopper |
| POST | `/disputes/{id}/resolve` | Resolve a dispute (uphold or overturn) | FinanceOfficer |
| POST | `/disputes/{id}/withdraw` | Withdraw one's own dispute | Shopper |
| POST | `/payout-batches` | Collect accrued reimbursements into a batch | FinanceOfficer |
| GET | `/payout-batches/{id}` | Fetch a payout batch | FinanceOfficer, PlatformAdmin |
| GET | `/payout-batches` | List payout batches | FinanceOfficer, PlatformAdmin |
| GET | `/payout-batches/{id}/reimbursements` | List a batch's reimbursements | FinanceOfficer, PlatformAdmin |
| GET | `/shoppers/{id}/reimbursements` | List a shopper's reimbursements | FinanceOfficer, PlatformAdmin, Shopper |
| GET | `/assignments/{id}/reimbursement` | List an assignment's reimbursement | FinanceOfficer, PlatformAdmin, QaValidator, Shopper |
| POST | `/payout-batches/{id}/pay` | Pay a batch | FinanceOfficer |
| POST | `/payout-batches/{id}/void` | Void an open batch | FinanceOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

The list endpoints accept the pagination query parameters `limit` and `offset`. The assignments list additionally filters by `wave_id`, `shopper_id`, `location_id`, `script_id`, and `status`; the payout-batches list filters by `shopper_id`; and a shopper's reimbursements list filters by `status`. The two singular-looking sub-resource reads `GET /assignments/{id}/scorecard` and `GET /assignments/{id}/reimbursement` are nonetheless served as paginated array responses (`response_type` `"array"` with the pagination `meta`), each returning the zero-or-one matching records for that assignment rather than a bare object.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ASSIGNMENT_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_TAX_ID_REQUIRED` | 422 |
| `ERR_SHOPPER_NOT_CERTIFIED` | 422 |
| `ERR_FAMILY_MISMATCH` | 422 |
| `ERR_DUE_OUTSIDE_WINDOW` | 422 |
| `ERR_ROTATION_COOLDOWN` | 409 |
| `ERR_EVIDENCE_INCOMPLETE` | 422 |
| `ERR_SECTION_KEYS_MISMATCH` | 422 |
| `ERR_WEIGHTS_NOT_NORMALIZED` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_DISPUTE_ROUNDS_EXHAUSTED` | 409 |
| `ERR_REVISION_LIMIT_REACHED` | 409 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_SHOPPER_HAS_OPEN_ASSIGNMENTS` | 409 |
| `ERR_SCRIPT_IN_USE` | 409 |
| `ERR_WAVE_NOT_DRAINED` | 409 |
| `ERR_REIMBURSEMENT_NOT_ACCRUED` | 409 |
| `ERR_INVALID_REQUEST` | 400 |

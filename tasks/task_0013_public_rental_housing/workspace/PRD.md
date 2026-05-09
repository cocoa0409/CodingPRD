# Public Rental Housing API — Product Requirements Document

## 1. Introduction

Public rental housing is a means-tested, slot-constrained social benefit: the available stock is finite, demand is structurally larger than supply, and the people who depend on it cannot afford the consequences of a wrong allocation. Operating such a program requires the housing authority to coordinate identity, household, income, and asset evidence across several government departments, then turn that evidence into a defensible queue ranking, then turn that ranking into a specific apartment for a specific family — and to do so in a way that survives objections, audits, and the slow drift of household circumstances over time.

This document specifies the back-office API that supports that full lifecycle. The platform owns the rule book — eligibility cross-checks against civil-affairs, public-security, taxation, and social-security feeds; weighted queue scoring with deterministic tie-breaking; family-size and accessibility-aware unit matching; a public notice period with binding objections; electronic contract signing with deposit verification through a payment feed; multi-level rent-reduction approval for hardship cases; and an annual review cycle that can adjust rent, recompute scores, or trigger a graceful exit. Every state-changing decision leaves an audit trail, and every clock-driven transition (notice expiry, lease start, reduction validity, grace-period exit) is reproducible because the platform exposes a deterministic logical clock rather than relying on wall time.

The API is consumed by housing directors who configure programs and stock, housing officers who execute the day-to-day caseload, applicants who self-serve their application and contract, citizen observers who can file objections during the public notice period, and an integration gateway role that pipes events in from the external departmental systems. Section 2 defines the cross-cutting contract these consumers all share; section 3 walks the business workflows in narrative form; section 4 lists the endpoints; and section 5 catalogs the error codes used throughout.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying that principal's role. A request that is missing either header, or that provides a value the server cannot interpret, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` at HTTP 400. A request whose role is recognized but is not authorized for the requested operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403.

Five roles plus a read-only role grouping are recognized. `HousingDirector` is the top-level program administrator, exclusively responsible for creating programs and housing units, advancing the program clock, and acting as the final approver of rent reductions. `HousingOfficer` is the operational caseworker — running cross-checks, creating allocations, sustaining or dismissing objections, recording contract handover, advancing rent-reduction reviews up to the secondary stage, opening and finalizing annual reviews, and finalizing exits after the grace period. `Applicant` is the end-user who creates and submits an application, confirms or rejects an offered allocation, pays the deposit, signs the contract, applies for rent reduction, and resubmits a rejected reduction. `Citizen` is a public observer who may file an objection during a notice period but has no other write privileges. `IntegrationGateway` is the machine identity used by external departmental connectors to emit sync events on behalf of civil-affairs, public-security, taxation, social-security, and payment systems. `Any` is the umbrella read role: any authenticated role above is permitted to read public data through `Any`-tagged GET endpoints.

The `X-User-ID` semantics differ by role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Application`-owner — that is, ownership is recorded by writing `X-User-ID` into `applicant_user_id` at application creation, and any subsequent ownership check on a downstream resource (allocation confirm/reject, contract pay-deposit/sign, rent-reduction resubmit) compares the foreign `applicant_user_id` of the chain root to `X-User-ID`. A given `X-User-ID` acting as `Applicant` may own at most one `Application` per program in any non-terminal status — the second such submission is rejected with `ERR_DUPLICATE_ACTIVE_APPLICATION`. When `X-User-Role` is `HousingDirector`, `HousingOfficer`, `Citizen`, or `IntegrationGateway`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a scaffold transition writes it — for example, the housing officer who advances a rent reduction out of `PRIMARY_REVIEW` is recorded as `primary_review_user_id`, and the housing director who final-approves it as `secondary_review_user_id`, both for audit and for the segregation-of-duties check at final approval — but it never compares those identifiers to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100; the `offset` parameter defaults to 0 and has no upper bound beyond the size of the underlying result set. Results are sorted by `created_at` in ascending order (oldest first); ties on `created_at` are broken by ascending `id` so that pagination is total and reproducible. The pagination `meta` block on every list response carries `limit`, `offset`, `total_count` (the total size of the unfiltered-by-pagination result set), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries a server-minted `id`, a 36-character UUID with no entity type prefix or any other namespacing — clients must not rely on the `id` revealing what kind of object it points to. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, recorded at the moment of insertion and immutable thereafter.

Most resources additionally carry `updated_at` and `version`. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation that changes user-visible state, and `version` is a monotonically increasing integer that starts at 1 on creation and increments by 1 on every such mutation. The single exception is the `SyncEvent` log: because sync events are an immutable append-only journal, a `SyncEvent` carries only `id` and `created_at` — both `updated_at` and `version` are absent.

Optimistic concurrency control is provided through an optional `version` field in the request body of every mutation endpoint. When the client includes `version`, the server compares it to the current entity's `version` and rejects the request with `ERR_VERSION_MISMATCH` at HTTP 409 if the two do not match, leaving the entity unchanged. When the client omits `version`, the check is skipped and the mutation proceeds; this is supported but not recommended for clients that may race with other writers.

### 2.5. The Logical Period Clock

The system runs on a deterministic, server-controlled period clock rather than wall time. Each `HousingProgram` exposes a `current_period_index`, a non-negative integer that starts at 0 when the program is created and only ever advances through an explicit administrative action: a `HousingDirector` calls the clock-advance capability with a `by_periods` value between 1 and 10000 inclusive, and the program's `current_period_index` increases by exactly that amount. Every business rule that references "now" — the residence-length component of the queue score, the notice-period elapsed check, the grace-period exit check, the lease-start handover check, the validity-window expiry of a rent reduction, the open-window check on objections — reads `current_period_index` rather than the wall clock, so that test scenarios are exactly reproducible.

Two automatic sweeps are bundled into every clock-advance call so that time-gated terminal transitions cannot be missed. The first sweep walks every `RentReduction` in `FINAL_APPROVED` status whose `validity_end_period` has been reached or passed by the new `current_period_index`, transitions it to `EXPIRED`, and recomputes the parent `Contract`'s `monthly_effective_rent_cents` so the discount is removed from the next rent calculation. The second sweep walks every `Application` in `EXIT_PENDING` status whose grace period has elapsed — that is, the new `current_period_index` is greater than or equal to the application's `exit_trigger_period` plus the program's `grace_period_length` — and transitions it to `EXITED`, cascading the parent `Contract` to `TERMINATED` and the parent `HousingUnit` back to `AVAILABLE`. A `HousingOfficer` may also drive the second sweep manually for a single application via the finalize-exit capability; that path enforces the same grace-period-elapsed condition and rejects an early attempt with `ERR_GRACE_PERIOD_NOT_ELAPSED`.

### 2.6. Multi-Department Synchronization and Audit

External departmental data is never read directly from those departments at request time. Instead, the integration layer emits `SyncEvent` records into a per-program append-only log via the sync-events capability, and the housing platform reads only its own log when it makes decisions. Each event carries an `event_type` chosen from `CIVIL_AFFAIRS_HOUSEHOLD`, `PUBLIC_SECURITY_IDENTITY`, `TAX_INCOME_ASSETS`, `SOCIAL_SECURITY_INCOME`, `PAYMENT_DEPOSIT`, `PAYMENT_RENT`, `AUDIT_ELIGIBILITY_CHANGE`, or `AUDIT_ALLOCATION_DECISION`; a `subject_type` chosen from `APPLICATION`, `ALLOCATION`, `CONTRACT`, or `RENT_REDUCTION`; the `subject_id` of the entity it concerns; an `emitted_period` equal to the program's `current_period_index` at emission; and a `payload` whose shape is appropriate to the event type. The `payload` for `TAX_INCOME_ASSETS` contains `monthly_income_cents` and `total_assets_cents`; the `payload` for `PAYMENT_DEPOSIT` contains `amount_cents`; the `payload` for any `AUDIT_*` event contains `actor_user_id`, `before`, `after`, and `note`. Sync events can be emitted by `HousingOfficer` or `IntegrationGateway`, and they can be read (filtered by `event_type`, `subject_type`, and/or `subject_id`) by any authenticated reader.

Wherever a business rule reads a "latest" departmental record, the rule means the most recently created `SyncEvent` of that `event_type` whose `subject_id` matches the entity in question. If no such event exists, the rule fails closed with the relevant error rather than silently passing.

### 2.7. Monetary Precision and Rounding

All money quantities are stored and exchanged in integer cents to eliminate floating-point drift. Where a calculation produces a non-integer cent value, the system rounds half up to the nearest cent — that is, the fractional part is added to the nearest cent and an exact half rounds away from zero (toward the larger cent). Two specific places require rounding: the deposit amount (`monthly_base_rent_cents` multiplied by two, half-up to integer cents) and per-room rent shares (each per-room amount rounded half-up to integer cents before summation, never after). The order of operations on per-room rent shares is fixed and load-bearing: round each per-room amount first, then sum the rounded amounts. Summing first and rounding the total once is incorrect and will produce a different number when the fractional cents collectively exceed half a cent.

Discount magnitudes are expressed in basis points where ten thousand basis points equals one hundred percent. Basis-point arithmetic is integer; tier comparisons are strict less-than, never less-than-or-equal.

### 2.8. Hierarchical Path Resolution

Resources are nested. A typical write path traverses program → application → annual-review, or program → allocation → objection, or program → contract → rent-reduction. When a request carries multiple path identifiers, the server validates them left-to-right: the program is resolved first, and if it does not exist the request is rejected with `ERR_PROGRAM_NOT_FOUND`; only then is the next identifier resolved, with `ERR_APPLICATION_NOT_FOUND`, `ERR_HOUSING_UNIT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_OBJECTION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_RENT_REDUCTION_NOT_FOUND`, `ERR_ANNUAL_REVIEW_NOT_FOUND`, or `ERR_SYNC_EVENT_NOT_FOUND` returned for the first missing segment. A child resource whose parent identifiers do not match the parents on its actual record is treated as not found at the segment that did not match. The generic `ERR_NOT_FOUND` covers any resource type for which a more specific error is not catalogued.

The parent-child relationships are recorded on the child as system-managed foreign-key fields. Applications, housing units, allocations, and sync events each carry a `housing_program_id` set from the path's program segment at creation. Objections carry an `allocation_id` set from the path's allocation segment. Contracts carry an `allocation_id` set when the contract is auto-created at allocation confirmation, plus an `application_id` and a `housing_unit_id` denormalized from that allocation as convenience pointers. Rent reductions carry a `contract_id` set from the path's contract segment. Annual reviews carry an `application_id` set from the path's application segment. None of these system-set fields appear in client request bodies — they are derived from the URL.

### 2.9. Concurrency Guarantees and Serialization Points

Several business operations expose race conditions; the server handles each by serializing on the underlying state field and surfacing a deterministic error to the loser.

If two `HousingOfficer` users simultaneously attempt to allocate the same `AVAILABLE` `HousingUnit` (each picking a different application), the unit's `AVAILABLE → RESERVED` transition is the serialization point: the first writer wins, and the second receives `ERR_UNIT_NOT_AVAILABLE` at HTTP 409 because the unit is no longer `AVAILABLE` by the time the second attempt is evaluated.

If an `Applicant` confirms an allocation while a `HousingOfficer` sustains an objection on the same allocation, the allocation's `status` is the serialization point and exactly one operation succeeds; the loser receives `ERR_ALLOCATION_NOT_PUBLISHED` at HTTP 409 because the new status is no longer `PUBLISHED` by the time the second attempt is evaluated.

If two `HousingOfficer` users simultaneously attempt to advance the same rent reduction from `PRIMARY_REVIEW` to `SECONDARY_REVIEW`, the rent reduction's `status` is the serialization point; the loser receives `ERR_RENT_REDUCTION_NOT_IN_PRIMARY` at HTTP 409 because the status has moved on by the time the second attempt is evaluated.

If the same `Applicant` (same `X-User-ID`) attempts to create two applications under the same program concurrently, the per-program-per-applicant uniqueness over non-terminal status (every status except `EXITED` and `REJECTED`) is the serialization point; the loser receives `ERR_DUPLICATE_ACTIVE_APPLICATION` at HTTP 409.

If two mutations on the same entity arrive concurrently and both supply `version`, one will succeed and the other will receive `ERR_VERSION_MISMATCH` at HTTP 409 because its `version` no longer matches the persisted `version` after the first writer commits.

Validation across every endpoint runs in a fixed priority order so that a higher-priority failure is not masked by a lower-priority one. Header presence is checked first (priority 1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); then role authorization (priority 2, `ERR_INSUFFICIENT_PERMISSIONS`); then path-segment existence left-to-right (priority 3, `ERR_NOT_FOUND` and the typed not-found variants); then `version` mismatch when the body supplies one (priority 4, `ERR_VERSION_MISMATCH`); then state-machine preconditions on the target entity (priorities 5–8, the typed `ERR_*_NOT_*` family); and finally the domain-specific business checks of priorities 9 through 26.

## 3. Business Logic & Workflows

### 3.1. Program Setup and Housing Stock

A `HousingDirector` opens a program by supplying its `name`, an optional `description`, the `notice_period_length` (a positive integer of at least 1 measured in clock periods, defaulting to 7), the `grace_period_length` (a positive integer of at least 1 measured in clock periods, defaulting to 6), the `per_capita_income_threshold_cents` (the maximum allowed monthly per-capita household income, in integer cents), and the `per_capita_asset_threshold_cents` (the maximum allowed per-capita household asset value, in integer cents). The program is created with `current_period_index` initialized to 0; the director controls subsequent advances through the clock-advance capability described in §2.5.

Housing stock is then registered against the program, one `HousingUnit` at a time. Each unit declares a `unit_code` (unique within the program), an `apartment_type` chosen from `STUDIO`, `ONE_BEDROOM`, `TWO_BEDROOM`, or `THREE_BEDROOM`, a `bedroom_count` that must match the apartment type (`STUDIO` is 0 bedrooms, `ONE_BEDROOM` is 1, `TWO_BEDROOM` is 2, `THREE_BEDROOM` is 3 — any mismatch is rejected with `ERR_BEDROOM_COUNT_TYPE_MISMATCH`), a `square_meters` floor area at least 1, a `monthly_base_rent_cents` base monthly rent, a `location_priority_tier` from 1 (highest priority, closest to amenities) to 5 (lowest), and an `accessibility_compliant` boolean indicating whether the unit meets accessibility requirements such as ground-floor placement or ramp access. A new unit enters the world in `AVAILABLE` status; over its lifetime it can move to `RESERVED` (held against a `PUBLISHED` allocation), to `OCCUPIED` (handed over and active), to `RETIRED` (decommissioned), and back to `AVAILABLE` (when an allocation reverts or a tenancy ends).

### 3.2. Application Intake and Eligibility Cross-Check

An `Applicant` opens a draft application against a specific program. The submission includes the `household_members` array (each member object carries a `citizen_id`, a `relation` chosen from `SELF`, `SPOUSE`, `CHILD`, `PARENT`, or `OTHER`, a `dob`, a `has_disability` boolean, and a `special_care_category` chosen from `NONE`, `VETERAN`, `MARTYR_FAMILY`, `SINGLE_PARENT`, or `ELDERLY_LIVE_ALONE`), the `household_type` chosen from `LOW_INCOME`, `NEW_CITIZEN`, `RELOCATION`, or `TALENT`, the self-declared aggregate `declared_monthly_income_cents` and `declared_total_assets_cents`, and the `residence_start_period` — the period index from which the applicant established local residence. On creation, the server records `applicant_user_id` from `X-User-ID`, computes `family_size` as the length of `household_members`, computes `requires_accessibility` as true if and only if at least one member has `has_disability` true, and sets the application `status` to `DRAFT`. The server enforces the per-program-per-applicant uniqueness rule described in §2.9 at this point.

The applicant submits the draft, transitioning the application from `DRAFT` to `UNDER_REVIEW`; if the application is not in `DRAFT` the submit is rejected with `ERR_APPLICATION_NOT_IN_DRAFT`, and if `household_members` is empty the submit is rejected with `ERR_INVALID_REQUEST`. A `HousingOfficer` then runs the cross-check, which is the heart of eligibility. Cross-check requires that the application be in `UNDER_REVIEW` (else `ERR_APPLICATION_NOT_UNDER_REVIEW`) and that the following six departmental conditions all hold simultaneously, evaluated against the most-recently-emitted `SyncEvent` of each required type whose `subject_id` matches the application:

1. The latest `CIVIL_AFFAIRS_HOUSEHOLD` event must include every `citizen_id` present in `household_members`; if any member is missing from the household register, the cross-check fails with `ERR_HOUSEHOLD_REGISTRATION_MISMATCH`.
2. The latest `PUBLIC_SECURITY_IDENTITY` event must mark every `citizen_id` in `household_members` as `identity_verified=true`; if any is not, the cross-check fails with `ERR_IDENTITY_VERIFICATION_FAILED`.
3. The latest `TAX_INCOME_ASSETS` event's `monthly_income_cents` divided by `family_size` must not exceed `per_capita_income_threshold_cents`; equality passes, strictly greater fails with `ERR_INCOME_OVER_THRESHOLD`.
4. The same event's `total_assets_cents` divided by `family_size` must not exceed `per_capita_asset_threshold_cents`; equality passes, strictly greater fails with `ERR_ASSETS_OVER_THRESHOLD`.
5. No `citizen_id` in `household_members` may already appear as an occupant on any other `Contract` whose status is `ACTIVE`, `DEPOSIT_PAID`, or `SIGNED` within the same program; an existing occupancy fails with `ERR_EXISTING_HOUSING_DETECTED`.
6. (The auth and state preconditions covered in §2.9's priority order have already been evaluated at this point.)

When all six pass, the application moves from `UNDER_REVIEW` to `SCORED`; the server writes `verified_monthly_income_cents` and `verified_total_assets_cents` from the latest `TAX_INCOME_ASSETS` payload, sets `cross_check_status` to `PASSED`, computes the `queue_score` and the `tie_break_key` per §3.3, and emits a `SyncEvent` of type `AUDIT_ELIGIBILITY_CHANGE` carrying the before/after `cross_check_status` snapshot. When any one of the six fails, the application moves from `UNDER_REVIEW` to `REJECTED`; `cross_check_status` is set to `FAILED`, `rejection_reason` is set to the specific failing `error_id` from the list above, and a corresponding `AUDIT_ELIGIBILITY_CHANGE` event is emitted. Both branches set `cross_check_status`, both branches emit the audit event, and both branches are reachable only from `UNDER_REVIEW` — ordering matters because the household-registration check fires before identity verification, identity verification before income, income before assets, and asset before existing-housing, so the `rejection_reason` on a borderline application reflects the highest-precedence failing check rather than an arbitrary one.

A scored application is then placed into the queue by a `HousingOfficer` via the enqueue capability, transitioning `SCORED` to `QUEUED`. If the application is not `SCORED`, this is rejected with `ERR_APPLICATION_NOT_SCORED`.

### 3.3. Queue Scoring and Tie-Breaking

The `queue_score` is a non-negative integer with no rounding, computed as the sum of four components.

The household-type component reads `household_type` and contributes 30 for `LOW_INCOME`, 15 for `NEW_CITIZEN`, 20 for `RELOCATION`, or 25 for `TALENT`.

The disability component reads `household_members` and contributes 20 if at least one member has `has_disability` true, otherwise 0.

The residence component reads `residence_start_period` and the program's `current_period_index` at the moment of evaluation. The raw residence length is the larger of zero and the difference between `current_period_index` and `residence_start_period`. The component contributes one point per period of residence, capped at 20 — that is, if the raw residence length is greater than 20, the component contributes 20; otherwise it contributes the raw value. The cap is non-linear in an important way: two applicants who differ only in `residence_start_period` may receive identical scores once both exceed the cap (a residence length of 15 and a residence length of 25 both yield 20), so the residence component cannot by itself separate every pair.

The special-care component reads `special_care_category` across `household_members` and takes the maximum points across members: 0 for `NONE`, 15 for `VETERAN`, 18 for `MARTYR_FAMILY`, 10 for `SINGLE_PARENT`, and 12 for `ELDERLY_LIVE_ALONE`. If multiple members carry different categories, only the highest-scoring category counts; the contribution is not summed across members.

The `queue_score` is the sum of these four integer components and is recomputed at exactly two moments: when the application crosses `UNDER_REVIEW → SCORED` (initial score, with residence length measured at `current_period_index` at the moment cross-check completes) and when an `AnnualReview` is finalized (recalculated score, where residence length is measured at the review's `review_period_index`, and `household_type` and `household_members` reflect any updates applied by the annual review). While the application is in `DRAFT` or `UNDER_REVIEW`, `queue_score` is null.

The `tie_break_key` is a composite lexicographic key built from `residence_start_period` ascending, then the application's `created_at` ascending, then the application's `id` ascending. It is set together with the initial `queue_score` and is used to break ties throughout allocation matching.

### 3.4. Allocation Matching, Public Notice, and Objections

A `HousingOfficer` initiates allocation by selecting a `HousingUnit` and asking the system to pick the matching application; the request body therefore contains only the `housing_unit_id`. The selected unit must be in `AVAILABLE`, otherwise the request is rejected with `ERR_UNIT_NOT_AVAILABLE`. The system then runs the allocation selector against the program's `QUEUED` applications.

The candidate set is the subset of `QUEUED` applications whose `family_size` matches the unit's `bedroom_count` tolerance and whose accessibility need is satisfiable by the unit. The family-size tolerance is fixed: a `STUDIO` unit accepts only `family_size` exactly 1; a `ONE_BEDROOM` accepts `family_size` of 1 or 2; a `TWO_BEDROOM` accepts `family_size` of 2, 3, or 4; a `THREE_BEDROOM` accepts `family_size` of 4, 5, 6, or 7. The accessibility filter is one-sided: when the unit's `accessibility_compliant` is false, every application whose `requires_accessibility` is true is excluded; when the unit's `accessibility_compliant` is true, no application is excluded on accessibility grounds — both accessibility-needers and others remain candidates.

Once the candidate set is fixed, ranking proceeds in three layers, each layer breaking ties produced by the previous one. The first layer is `queue_score` descending — highest score wins. The second layer applies only when the unit's `accessibility_compliant` is true, and it is `requires_accessibility` descending — when an accessible unit is being matched and two candidates tied on `queue_score`, the accessibility-needer is preferred. The third layer is `tie_break_key` ascending. The first candidate after the three-layer sort is selected. If the candidate set is empty, the system rejects the request with `ERR_NO_ELIGIBLE_APPLICATION`.

The successful allocation creates an `Allocation` in `PUBLISHED` status carrying the `application_id` and the `housing_unit_id`, with `notice_start_period` equal to the current `current_period_index` and `notice_end_period` equal to `notice_start_period` plus the program's `notice_period_length` (the end is exclusive — period equal to `notice_end_period` is already past the window). As a single transactional bundle, the unit transitions from `AVAILABLE` to `RESERVED`, the picked application transitions from `QUEUED` to `ALLOCATED`, and a `SyncEvent` of type `AUDIT_ALLOCATION_DECISION` is emitted.

The `PUBLISHED` allocation enters a public notice window during which any `Applicant` or `Citizen` may file an objection. An objection submission carries the submitter's `submitter_user_id` (taken from `X-User-ID`) and a `reason_text` string of at least 20 characters; the new objection is recorded in `PENDING_REVIEW` status with `review_decision` and `review_notes` left null. Filing an objection is permitted only while the notice window is open — that is, while `current_period_index` is strictly less than `notice_end_period`; an attempt at or after `notice_end_period` is rejected with `ERR_NOTICE_PERIOD_CLOSED`. Filing an objection on a non-`PUBLISHED` allocation is rejected with `ERR_ALLOCATION_NOT_PUBLISHED`. The first objection on a `PUBLISHED` allocation cascades the allocation to `UNDER_OBJECTION`; subsequent objections during the same window leave the allocation in `UNDER_OBJECTION` without further transition.

A `HousingOfficer` resolves each objection by sustaining or dismissing it, optionally attaching `review_notes`. A sustain transitions the objection from `PENDING_REVIEW` to `SUSTAINED` and cascades the parent allocation from `UNDER_OBJECTION` (or `PUBLISHED`) to `REVERTED`; the cascade returns the application from `ALLOCATED` to `QUEUED`, returns the housing unit from `RESERVED` to `AVAILABLE`, auto-dismisses every other still-`PENDING_REVIEW` objection on the same allocation with `review_notes` of `'allocation reverted'`, and emits an `AUDIT_ALLOCATION_DECISION` audit event. A dismiss transitions the objection from `PENDING_REVIEW` to `DISMISSED`; if the dismissed objection was the last `PENDING_REVIEW` objection on the allocation and no `SUSTAINED` objections exist on it, the allocation cascades from `UNDER_OBJECTION` back to `PUBLISHED`. Both sustain and dismiss require the objection to be `PENDING_REVIEW`; otherwise the operation is rejected with `ERR_OBJECTION_NOT_PENDING`. Sustain additionally requires the parent allocation to be either `PUBLISHED` or `UNDER_OBJECTION`; both branches treat the objection state with equal rigor — the dismiss branch may also drive a back-cascade to `PUBLISHED` and so symmetrically updates the allocation when the conditions hold.

### 3.5. Confirmation, Contracting, Deposit, Signing, and Handover

Once the notice window has elapsed and any objections have been resolved without a sustain, the allocation is ready for the applicant to confirm. The applicant calls the confirmation capability; the request is accepted only when `current_period_index` is greater than or equal to `notice_end_period` (else `ERR_NOTICE_PERIOD_NOT_ELAPSED`), the allocation is in `PUBLISHED` (else `ERR_ALLOCATION_NOT_PUBLISHED`), and `X-User-ID` equals the parent application's `applicant_user_id` (else `ERR_INSUFFICIENT_PERMISSIONS`). On success, the allocation transitions from `PUBLISHED` to `CONFIRMED`, `confirmation_period` is set to the current `current_period_index`, a `Contract` is auto-created in `DRAFT` status with `application_id` and `housing_unit_id` denormalized from the parent allocation and `deposit_amount_cents` computed as the unit's `monthly_base_rent_cents` multiplied by two (rounded half-up to integer cents — since `monthly_base_rent_cents` is already integer cents this is just twice the base rent), and a `SyncEvent` of type `AUDIT_ALLOCATION_DECISION` is emitted. Symmetrically, the applicant may instead reject the offered allocation while it is `PUBLISHED`; rejection transitions the allocation to `REVERTED`, returns the application from `ALLOCATED` to `QUEUED`, returns the housing unit from `RESERVED` to `AVAILABLE`, and emits `AUDIT_ALLOCATION_DECISION`. Rejection enforces the same ownership check as confirmation.

The contract then walks a four-step sequence. The applicant pays the deposit through the pay-deposit capability; this requires the contract to be in `DRAFT` (else `ERR_CONTRACT_NOT_IN_DRAFT`), the parent allocation to be in `CONFIRMED` (else `ERR_ALLOCATION_NOT_CONFIRMED`), and the latest `PAYMENT_DEPOSIT` event for this contract to carry a `payload.amount_cents` exactly equal to the contract's `deposit_amount_cents` — otherwise the request is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH` at HTTP 402. On success the contract transitions from `DRAFT` to `DEPOSIT_PAID` and `deposit_paid` is set to true.

The applicant signs the contract through the sign capability, supplying a non-empty `signature_blob` together with a `lease_start_period` and `lease_end_period`. The contract must be in `DEPOSIT_PAID` (else `ERR_CONTRACT_NOT_DEPOSIT_PAID`), the `signature_blob` must be non-empty (else `ERR_INVALID_REQUEST`), and the lease term must be valid — `lease_end_period` must be strictly greater than `lease_start_period` and `lease_start_period` must be at least the parent allocation's `confirmation_period`; either failure is reported as `ERR_INVALID_LEASE_TERM`. On success the `signature_blob` is stored, the `lease_start_period` and `lease_end_period` are recorded, and the contract transitions from `DEPOSIT_PAID` to `SIGNED`.

A `HousingOfficer` records handover, which activates the contract. This requires the contract to be in `SIGNED` (else `ERR_CONTRACT_NOT_SIGNED`) and the program's `current_period_index` to be at least the contract's `lease_start_period` (else `ERR_LEASE_NOT_STARTED`). On success, `handover_recorded` is set to true and the contract transitions from `SIGNED` to `ACTIVE`; the cascade transitions the application from `ALLOCATED` to `OCCUPIED`, transitions the housing unit from `RESERVED` to `OCCUPIED`, and initializes `monthly_effective_rent_cents` per the per-room rent calculation in §3.6 — at this initial moment no rent reduction is yet active, so the calculation runs with no discount.

### 3.6. Per-Room Rent and Rent Reductions for Hardship

The monthly effective rent for a contract is the sum of per-room rounded amounts plus any active annual-review adjustment. The unit is treated as one living room plus a number of bedrooms equal to `bedroom_count`; for `STUDIO` (`bedroom_count` 0) the apartment is a single living-room slot. The base rent is split between living-room and bedroom shares. For non-`STUDIO` apartments the living room takes 40 percent of `monthly_base_rent_cents` and the remaining 60 percent is divided evenly across the bedrooms — so a `ONE_BEDROOM` splits as 40/60, a `TWO_BEDROOM` as 40/30/30, and a `THREE_BEDROOM` as 40/20/20/20. For `STUDIO`, the 60 percent bedroom share is folded into the living room, and the single living-room slot takes 100 percent of `monthly_base_rent_cents`.

The system then determines the active discount in basis points. Among all `RentReduction` records on this contract whose `status` is `FINAL_APPROVED` and whose `validity_start_period` is at most `current_period_index` and whose `validity_end_period` is strictly greater than `current_period_index`, the active discount is the maximum `final_discount_bps`; if two qualifying reductions tie on `final_discount_bps`, the tie is broken by the more recent `created_at` (descending), then by the larger `id` (descending). If no qualifying reduction exists, the active discount is 0. The discount factor is then the difference between 10000 and the active discount, divided by 10000.

For each room slot, the per-room amount is `monthly_base_rent_cents` multiplied by that slot's fractional share, multiplied by the discount factor; that fractional value is rounded half up to integer cents and only then summed across all slots. The per-room rounding before summation is the load-bearing order — summing the fractional values first and rounding the total once produces a different integer when the fractional cents collectively exceed half a cent, and the sum-then-round variant is incorrect. Finally, the sum of any active `AnnualReview` `rent_adjustment_cents` values (each an integer cent delta) is added on top, and the result is `monthly_effective_rent_cents`.

A rent reduction is initiated by an `Applicant` (the contract's owner) with a body containing the `hardship_category` chosen from `MAJOR_ILLNESS`, `UNEMPLOYMENT`, `DISABILITY`, or `ELDER_CARE`, the `declared_hardship_income_cents` post-hardship monthly income, a `supporting_documents` array of at least one element (each element shaped `{ doc_type, doc_ref, issued_period }`), and an optional `requested_discount_bps` that the server ignores entirely — the discount is always computed by the platform. The new reduction is created in `SUBMITTED` with `provisional_discount_bps` computed at submission per the tiered formula below.

The provisional discount is computed in two steps. The income ratio is `declared_hardship_income_cents` divided by the parent unit's `monthly_base_rent_cents`. If the ratio is strictly less than 0.30, the base discount is 5000 basis points; otherwise if the ratio is strictly less than 0.50, the base discount is 3000 basis points; otherwise if the ratio is strictly less than 0.80, the base discount is 1500 basis points; otherwise the base discount is 0. The category boost adds 1500 basis points for `MAJOR_ILLNESS`, 1000 for `UNEMPLOYMENT`, 1500 for `DISABILITY`, or 500 for `ELDER_CARE`. The provisional discount in basis points is the smaller of 10000 and the sum of the base discount plus the category boost. All comparisons are strict less-than, all arithmetic is integer.

A `HousingOfficer` advances the reduction from `SUBMITTED` to `PRIMARY_REVIEW` (rejected with `ERR_RENT_REDUCTION_NOT_SUBMITTED` if not in `SUBMITTED`, and with `ERR_INVALID_REQUEST` if `supporting_documents` is empty). Another `HousingOfficer` advances from `PRIMARY_REVIEW` to `SECONDARY_REVIEW` (rejected with `ERR_RENT_REDUCTION_NOT_IN_PRIMARY` if not in `PRIMARY_REVIEW`); on success, `primary_review_user_id` is recorded as that officer's `X-User-ID`. A `HousingDirector` then drives final approval; this requires `SECONDARY_REVIEW` (else `ERR_RENT_REDUCTION_NOT_IN_SECONDARY`), requires that the director's `X-User-ID` differs from the recorded `primary_review_user_id` (else `ERR_SEGREGATION_OF_DUTIES_VIOLATION` at HTTP 403 — a single individual may not occupy both review slots), and requires that no existing `FINAL_APPROVED` reduction on the same contract has a half-open validity interval `[validity_start_period, validity_end_period)` that intersects the new validity window (else `ERR_OVERLAPPING_RENT_REDUCTION`). On success the director's `X-User-ID` is recorded as `secondary_review_user_id`, the status moves to `FINAL_APPROVED`, `validity_start_period` is set to the current `current_period_index`, `validity_end_period` is set to that period plus 12 (so the default validity is twelve periods, half-open), `final_discount_bps` is computed, and `monthly_effective_rent_cents` on the contract is recomputed to incorporate the newly active discount.

The `final_discount_bps` is computed by the same tiering and category-boost rules as `provisional_discount_bps`, but using the `monthly_income_cents` value from the latest `TAX_INCOME_ASSETS` event for the parent application as the income operand instead of the applicant's self-declared `declared_hardship_income_cents`. Because the verified income may land in a different tier from the declared income, the final discount can differ from the provisional one — applicants whose declared figures were optimistic will see a smaller final discount, and applicants whose declared figures were pessimistic may see a larger one.

A reviewer (either `HousingOfficer` for primary or `HousingDirector` for secondary) may reject a reduction while it is in `PRIMARY_REVIEW` or `SECONDARY_REVIEW`, transitioning the status to `REJECTED`; an attempt to reject from any other status fails with `ERR_RENT_REDUCTION_NOT_REJECTABLE`. The applicant who owns the parent contract may then resubmit a rejected reduction, providing optionally updated `hardship_category`, `declared_hardship_income_cents`, and `supporting_documents`; this requires the reduction to be in `REJECTED` (else `ERR_RENT_REDUCTION_NOT_REJECTED`) and requires that `X-User-ID` equal the parent contract's owning applicant's `applicant_user_id`. On success the status returns to `SUBMITTED`, both reviewer slots (`primary_review_user_id` and `secondary_review_user_id`) are cleared, and `provisional_discount_bps` is recomputed against whichever values are now in effect. A `FINAL_APPROVED` reduction can also reach a terminal `EXPIRED` state without manual action: the clock-advance sweep described in §2.5 transitions any `FINAL_APPROVED` reduction whose `validity_end_period` has been reached to `EXPIRED` and recomputes the contract's `monthly_effective_rent_cents` without that reduction's contribution. A `Contract` transitioning to `TERMINATED` likewise expires every non-`REJECTED` reduction on it.

### 3.7. Annual Review, Rent Adjustment, and Exit Lifecycle

While an application is in `OCCUPIED` (and only then), a `HousingOfficer` may open an `AnnualReview`. The body may carry an updated `updated_household_members` array, an updated `updated_declared_monthly_income_cents`, and an updated `updated_declared_total_assets_cents`; any of these three may be omitted, in which case the corresponding field on the application is reused without change at finalize time. The review is created in `OPEN` status with `review_period_index` set to the program's `current_period_index` at creation, with `re_eligibility`, `recomputed_queue_score`, `rent_adjustment_cents`, and `exit_triggered` all left empty (the latter false by default). At most one `OPEN` review may exist for a given application at a time; an attempt to open a second `OPEN` review on the same application is rejected with `ERR_ANNUAL_REVIEW_ALREADY_OPEN`. Opening a review on an application whose status is not `OCCUPIED` is rejected with `ERR_APPLICATION_NOT_OCCUPIED`.

A `HousingOfficer` then finalizes the review. Finalize requires the review to be in `OPEN` (else `ERR_ANNUAL_REVIEW_NOT_OPEN`) and the parent application to be in `OCCUPIED` (else `ERR_APPLICATION_NOT_OCCUPIED`). On finalize, the server first applies the three update fields to the application, treating any null update as a no-op (the existing value is reused). It then re-runs the same six-condition cross-check used at the original `UNDER_REVIEW → SCORED` transition and sets `re_eligibility` to `ELIGIBLE` if and only if every check passes, and `INELIGIBLE` otherwise. It recomputes the `queue_score` per the same formula, this time measuring residence length at the review's `review_period_index` and using whatever updated `household_type` and `household_members` are now in effect; the new score lands in `recomputed_queue_score`. The two queue-score variants — initial and recomputed — use the same formula but can yield different integer values for the same application because the program clock has advanced and any updates have been applied; in particular, the residence cap of 20 means the score is unchanged when residence length saturates the cap before and after the advance, but changes when the advance pushes residence length across the cap.

When `re_eligibility` is `ELIGIBLE`, the server computes `rent_adjustment_cents` as the difference between the rent associated with the (possibly newly applicable) household type tier and the current `monthly_base_rent_cents`; this delta is applied additively to the active contract's `monthly_effective_rent_cents`. The delta may be zero, in which case the rent does not change. If the application has no active contract (an edge case), `rent_adjustment_cents` is null. The status transitions to `FINALIZED`, an `AUDIT_ELIGIBILITY_CHANGE` event records the before/after, and the application remains in `OCCUPIED`. When `re_eligibility` is `INELIGIBLE`, the server sets `exit_triggered` to true and cascades the application from `OCCUPIED` to `EXIT_PENDING`, recording `exit_trigger_period` as the current `current_period_index`. The status transitions to `FINALIZED` and an `AUDIT_ELIGIBILITY_CHANGE` event is emitted. Both branches of finalize emit the audit event and both branches recompute `queue_score`; only the `INELIGIBLE` branch sets `exit_triggered` and only the `ELIGIBLE` branch sets `rent_adjustment_cents`.

An application in `EXIT_PENDING` walks out the door once the grace period elapses. The natural path is the clock-advance sweep — when `current_period_index` reaches at least `exit_trigger_period` plus the program's `grace_period_length`, the application transitions to `EXITED`, the contract cascades to `TERMINATED` with `termination_period` equal to the current `current_period_index`, the housing unit returns to `AVAILABLE`, and an `AUDIT_ELIGIBILITY_CHANGE` event records the change. A `HousingOfficer` may also drive the same transition manually for a single application via the finalize-exit capability; the same grace-period-elapsed condition is checked, and an attempt before that point is rejected with `ERR_GRACE_PERIOD_NOT_ELAPSED`. The contract's `termination_period` is recorded on either path. When the contract terminates, every `RentReduction` on it that is not already `REJECTED` is moved to `EXPIRED`. The application's `EXITED` and `REJECTED` states are terminal — they release the per-program-per-applicant uniqueness slot, allowing the same `X-User-ID` to apply again under a fresh application if circumstances change.

## 4. Endpoint Definitions

All endpoints are mounted under `/housing-programs`. New resource creation returns HTTP 201 and a body containing the created resource; modifications, state transitions, and reads return HTTP 200 and the affected resource (or, for list endpoints, an array). Validation error codes follow the priority order described in §2.9 and the per-endpoint rules in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/housing-programs` | Create a housing program | HousingDirector |
| GET | `/housing-programs` | List housing programs | Any |
| GET | `/housing-programs/{programId}` | Get a housing program | Any |
| POST | `/housing-programs/{programId}/clock/advance` | Advance the program's logical period clock and run scheduled sweeps | HousingDirector |
| POST | `/housing-programs/{programId}/sync-events` | Emit a sync event from a departmental connector | HousingOfficer, IntegrationGateway |
| GET | `/housing-programs/{programId}/sync-events` | List/filter sync events | Any |
| POST | `/housing-programs/{programId}/applications` | Create an application in DRAFT | Applicant |
| GET | `/housing-programs/{programId}/applications` | List applications (Applicant scoped to own) | HousingOfficer, HousingDirector, Applicant |
| GET | `/housing-programs/{programId}/applications/{appId}` | Get an application | HousingOfficer, HousingDirector, Applicant |
| POST | `/housing-programs/{programId}/applications/{appId}/submit` | Submit a DRAFT application for review | Applicant |
| POST | `/housing-programs/{programId}/applications/{appId}/cross-check` | Run multi-department cross-check; transitions to SCORED or REJECTED | HousingOfficer |
| POST | `/housing-programs/{programId}/applications/{appId}/enqueue` | Move SCORED to QUEUED | HousingOfficer |
| POST | `/housing-programs/{programId}/applications/{appId}/finalize-exit` | Finalize EXIT_PENDING to EXITED after grace period | HousingOfficer |
| POST | `/housing-programs/{programId}/applications/{appId}/annual-reviews` | Open an annual review on an OCCUPIED application | HousingOfficer |
| POST | `/housing-programs/{programId}/applications/{appId}/annual-reviews/{reviewId}/finalize` | Finalize an annual review; cascades adjustment or exit | HousingOfficer |
| POST | `/housing-programs/{programId}/housing-units` | Create a housing unit | HousingDirector |
| GET | `/housing-programs/{programId}/housing-units` | List housing units | Any |
| GET | `/housing-programs/{programId}/housing-units/{unitId}` | Get a housing unit | Any |
| POST | `/housing-programs/{programId}/allocations` | Create an allocation by selecting a unit; system picks the matching application | HousingOfficer |
| GET | `/housing-programs/{programId}/allocations` | List allocations | Any |
| GET | `/housing-programs/{programId}/allocations/{allocId}` | Get an allocation | Any |
| POST | `/housing-programs/{programId}/allocations/{allocId}/confirm` | Applicant confirms allocation after notice period elapsed | Applicant |
| POST | `/housing-programs/{programId}/allocations/{allocId}/reject` | Applicant declines this allocation; reverts to QUEUED | Applicant |
| POST | `/housing-programs/{programId}/allocations/{allocId}/objections` | Submit an objection during the notice period | Applicant, Citizen |
| POST | `/housing-programs/{programId}/allocations/{allocId}/objections/{objId}/sustain` | Sustain an objection (reverts allocation) | HousingOfficer |
| POST | `/housing-programs/{programId}/allocations/{allocId}/objections/{objId}/dismiss` | Dismiss an objection | HousingOfficer |
| GET | `/housing-programs/{programId}/contracts/{contractId}` | Get a contract | Any |
| POST | `/housing-programs/{programId}/contracts/{contractId}/pay-deposit` | Mark deposit as paid against a matched payment event | Applicant |
| POST | `/housing-programs/{programId}/contracts/{contractId}/sign` | Sign the contract with electronic signature and lease term | Applicant |
| POST | `/housing-programs/{programId}/contracts/{contractId}/handover` | Record handover and activate the contract | HousingOfficer |
| POST | `/housing-programs/{programId}/contracts/{contractId}/rent-reductions` | Apply for a hardship rent reduction | Applicant |
| GET | `/housing-programs/{programId}/rent-reductions/{rrId}` | Get a rent reduction | Any |
| POST | `/housing-programs/{programId}/rent-reductions/{rrId}/advance-to-primary` | Advance SUBMITTED to PRIMARY_REVIEW | HousingOfficer |
| POST | `/housing-programs/{programId}/rent-reductions/{rrId}/advance-to-secondary` | Advance PRIMARY_REVIEW to SECONDARY_REVIEW; records primary_review_user_id | HousingOfficer |
| POST | `/housing-programs/{programId}/rent-reductions/{rrId}/final-approve` | Final approve under segregation of duties and overlap check | HousingDirector |
| POST | `/housing-programs/{programId}/rent-reductions/{rrId}/reject` | Reject during PRIMARY_REVIEW or SECONDARY_REVIEW | HousingOfficer, HousingDirector |
| POST | `/housing-programs/{programId}/rent-reductions/{rrId}/resubmit` | Applicant resubmits a rejected rent reduction | Applicant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_HOUSING_UNIT_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_OBJECTION_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_RENT_REDUCTION_NOT_FOUND` | 404 |
| `ERR_ANNUAL_REVIEW_NOT_FOUND` | 404 |
| `ERR_SYNC_EVENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_LEASE_TERM` | 400 |
| `ERR_BEDROOM_COUNT_TYPE_MISMATCH` | 400 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_DUPLICATE_ACTIVE_APPLICATION` | 409 |
| `ERR_APPLICATION_NOT_IN_DRAFT` | 409 |
| `ERR_APPLICATION_NOT_UNDER_REVIEW` | 409 |
| `ERR_APPLICATION_NOT_SCORED` | 409 |
| `ERR_APPLICATION_NOT_OCCUPIED` | 409 |
| `ERR_APPLICATION_NOT_EXIT_PENDING` | 409 |
| `ERR_ALLOCATION_NOT_PUBLISHED` | 409 |
| `ERR_ALLOCATION_NOT_CONFIRMED` | 409 |
| `ERR_OBJECTION_NOT_PENDING` | 409 |
| `ERR_CONTRACT_NOT_IN_DRAFT` | 409 |
| `ERR_CONTRACT_NOT_DEPOSIT_PAID` | 409 |
| `ERR_CONTRACT_NOT_SIGNED` | 409 |
| `ERR_RENT_REDUCTION_NOT_SUBMITTED` | 409 |
| `ERR_RENT_REDUCTION_NOT_IN_PRIMARY` | 409 |
| `ERR_RENT_REDUCTION_NOT_IN_SECONDARY` | 409 |
| `ERR_RENT_REDUCTION_NOT_REJECTABLE` | 409 |
| `ERR_RENT_REDUCTION_NOT_REJECTED` | 409 |
| `ERR_ANNUAL_REVIEW_NOT_OPEN` | 409 |
| `ERR_ANNUAL_REVIEW_ALREADY_OPEN` | 409 |
| `ERR_HOUSEHOLD_REGISTRATION_MISMATCH` | 409 |
| `ERR_IDENTITY_VERIFICATION_FAILED` | 409 |
| `ERR_INCOME_OVER_THRESHOLD` | 409 |
| `ERR_ASSETS_OVER_THRESHOLD` | 409 |
| `ERR_EXISTING_HOUSING_DETECTED` | 409 |
| `ERR_NOTICE_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_NOTICE_PERIOD_CLOSED` | 409 |
| `ERR_GRACE_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_LEASE_NOT_STARTED` | 409 |
| `ERR_OVERLAPPING_RENT_REDUCTION` | 409 |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 402 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_NO_ELIGIBLE_APPLICATION` | 409 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 |

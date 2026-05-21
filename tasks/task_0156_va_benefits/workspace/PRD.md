# VA Benefits API — Product Requirements Document

## 1. Introduction

The Department of Veterans Affairs administers a portfolio of post-service benefits whose interlocking rules — service-connected disability ratings, dependents, the Post-9/11 GI Bill, Yellow Ribbon tuition support, monthly housing allowances, and Vocational Rehabilitation — have historically been operated as isolated workstreams. A veteran's enrollment at a college, their disability rating decision, and their dependent count all influence the dollar amounts the VA owes for any single month, yet the systems of record have rarely shared a transactional fabric. Decisions made in one program (a successful disability claim) silently change what is payable in another (the Post-9/11 entitlement tier and Yellow Ribbon match), and clerks routinely reconcile these by hand.

This document specifies the VA Benefits API — a single backend that ties claims, dependents, schools, enrollments, housing payments, Yellow Ribbon contributions, and Voc Rehab plans into one coherent ledger. The API enforces a strict segregation of duties between Veterans, VA Clerks, Raters, Counselors, and Platform Admins; it computes disability ratings using the VA's combined-rating table; it applies tiered housing allowances and Yellow Ribbon waterfall allocations; and it maintains an append-only payment ledger that records every dollar movement (and entitlement-month debit) as it happens. Two test-only driver endpoints — for advancing the logical clock and for running a periodic sweep — exist so deterministic integration tests can land time-gated states.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the VA Benefits API (except the two test-only driver endpoints described in §3) MUST present two HTTP headers identifying the caller: `X-User-ID` and `X-User-Role`. The value of `X-User-Role` MUST be exactly one of `Veteran`, `VAClerk`, `Rater`, `Counselor`, or `PlatformAdmin`. If either header is missing or `X-User-Role` is not one of the five recognized values, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the role is not authorized to invoke the requested endpoint as defined in §4, the request is rejected with `ERR_FORBIDDEN`.

The semantics of `X-User-ID` depend on the role. When `X-User-Role` is `Veteran`, `X-User-ID` is the `id` of the acting `Veteran` entity; every ownership check on a resource that references a veteran (a `Claim`, an `Enrollment`, a `Dependent`, a `VocRehabPlan`, or a `PaymentLedgerEntry`) compares the resource's `veteran_id` field to `X-User-ID`, and any ownership mismatch is treated as a forbidden operation. When `X-User-Role` is `VAClerk`, `Rater`, `Counselor`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on resources where the scaffold prescribes (the `rater_id` field on a `Claim` after the rater starts a review, and the `counselor_id` field on a `VocRehabPlan` after a counselor approves it) but does not compare those values to any entity's `id`. The opaque identifiers participate in the segregation-of-duties checks described in §3 — for example, a `Rater` whose `X-User-ID` matches the `rater_id` already recorded on a claim cannot perform the next adversarial decision on that same claim.

A `Veteran` is the benefit recipient. They may file their own claims, appeal a denied claim of theirs, withdraw their own active enrollment, and read their own dependents, claims, enrollments, schools they are enrolled at, voc-rehab plans, ledger, and projection. A `VAClerk` is a VA staff member who registers veterans, files claims on a veteran's behalf, certifies and cancels and completes enrollments, posts monthly housing payments, and manages dependents. A `Rater` is a disability adjudicator who starts reviews, grants, denies, and reopens claims. A `Counselor` is a Voc Rehab counselor who creates, approves, starts, suspends, resumes, and completes voc-rehab plans. A `PlatformAdmin` registers schools, drives the test-only clock and sweep endpoints, and has unrestricted read access across the domain; the admin role is forbidden from acting as a `Rater` or `Counselor` on adjudicative endpoints.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, has a minimum value of 1 and a maximum value of 100; values outside this inclusive range are rejected as invalid input. The `offset` parameter defaults to 0 when omitted and must be non-negative. List responses always sort by `created_at` ascending, so the chronological insertion order is stable across paginated calls. The `meta` block of every list response carries `limit`, `offset`, `total_count` (the total number of rows matching the filter before pagination), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties and Identifier Conventions

Every resource the API persists carries a server-minted `id`. The `id` is a UUID string with no type prefix — the same opaque format whether it belongs to a `Veteran`, a `Claim`, a `School`, an `Enrollment`, or any other entity. Resources also carry a `created_at` timestamp recorded the moment the row is first written; the value is an ISO 8601 UTC string with three fractional digits and is immutable thereafter.

Most resources additionally carry an `updated_at` ISO 8601 UTC timestamp (three fractional digits) and an integer `version` field. The `version` starts at 1 on creation and increments by exactly 1 on every server-side mutation — including state transitions, calculation-driven writes, and PATCH updates. `updated_at` is rewritten to the current server clock on every such mutation. Two entities in this domain are append-only ledger rows and therefore carry only `id` and `created_at`: `HousingPayment` and `PaymentLedgerEntry`. Once written, neither row is updated, so neither carries `updated_at` or `version`.

### 2.5. Optimistic Concurrency Control

The three endpoints that PATCH a mutable resource (a veteran, a dependent, an enrollment) accept an optional `version` field in the request body. When the caller supplies `version`, the server compares it against the current `version` stored on the resource; a mismatch causes the request to be rejected with `ERR_VERSION_CONFLICT`. When the caller omits `version`, the OCC check is skipped and the mutation proceeds with whatever the current state happens to be. On a successful PATCH the server increments `version` by 1 and refreshes `updated_at`.

### 2.6. Precision, Rounding, and Time Conventions

All monetary fields — tuition charged, certified tuition payable, monthly subsistence, housing payment amounts, ledger amounts in dollars, school and VA Yellow Ribbon contributions, student responsibility, and tuition gaps — are recorded with exactly two decimal places. Every calculation that produces a dollar value rounds half-up at the end of the calculation, applied once to the final figure rather than at intermediate steps (this distinction matters for tiered tuition and waterfall allocations, where rounding an interior product would shift the cents). One specific arm of the Yellow Ribbon allocation uses floor-to-cent rather than half-up rounding (see §3); that exception is explicit and does not generalize.

`combined_rating` is an integer in the set `{0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}` — the VA's combined-rating ladder, rounded to the nearest 10 with half-up rounding after first rounding the fractional efficiency to a whole percent. `post_911_eligibility_tier` is an integer in `{0, 40, 50, 60, 70, 80, 90, 100}` and is never produced at any other value. `months_entitlement_used` and `months_consumed` carry two decimal places and use half-up rounding; the entitlement counter is capped at 36.00 and never grows beyond it. All timestamps are ISO 8601 UTC. Term intervals `[term_start, term_end)` are half-open in UTC days; same-day adjacency between two enrollment terms (one ending at midnight on the day the next begins) is therefore non-overlapping by construction.

### 2.7. Nested Resource Retrieval and Path Validation

Several endpoints carry nested path parameters — a dependent's listing under `/veterans/{id}/dependents`, a claim list under `/veterans/{id}/claims`, the ledger under `/veterans/{id}/ledger`, the entitlement projection under `/veterans/{id}/entitlement-projection`, the Yellow Ribbon contribution under `/enrollments/{id}/yellow-ribbon`, the housing-payment collection under `/enrollments/{id}/housing-payments`. Path parameters are validated left-to-right: when an outer `id` does not resolve to an extant row, the response is `ERR_NOT_FOUND` immediately without evaluating inner segments. When an inner segment's foreign key in the body fails to resolve — for example, a request that supplies a `veteran_id`, `school_id`, `enrollment_id`, or `original_claim_id` that points to nothing — the response is `ERR_REFERENCE_NOT_FOUND`.

### 2.8. Validation Priority and Ordering

When multiple validations could fail on the same request, the server evaluates them in a fixed priority order so a single deterministic `error_id` is returned. The order is: authentication of the headers first (`ERR_UNAUTHENTICATED`), then role-based authorization (`ERR_FORBIDDEN`), then existence of every path id (`ERR_NOT_FOUND`), then existence of every foreign key in the request body (`ERR_REFERENCE_NOT_FOUND`), then state-machine FROM-state guards (`ERR_INVALID_STATE`), then cross-entity preconditions such as the combined-rating gate on enrollment activation and Voc Rehab approval (`ERR_CROSS_ENTITY_PRECONDITION`), then segregation-of-duties on rater and counselor adversarial steps (`ERR_SEGREGATION_VIOLATION`), then discharge eligibility for benefit-producing operations (`ERR_INELIGIBLE_DISCHARGE`), then the supplemental-claim reference check (`ERR_SUPPLEMENTAL_REFERENCE_INVALID`), then enrollment term-range validity (`ERR_INVALID_TERM_RANGE`), then enrollment overlap (`ERR_ENROLLMENT_OVERLAP`), then housing-payment month-coverage (`ERR_PAYMENT_OUTSIDE_TERM`), then dependent age constraints (`ERR_DEPENDENT_AGE`), then duplicate-spouse uniqueness (`ERR_DUPLICATE_SPOUSE`), then entitlement-cap fiscal guard (`ERR_ENTITLEMENT_EXCEEDED`), then Yellow Ribbon school-cap aggregate (`ERR_YELLOW_RIBBON_CAP_EXCEEDED`), then granted-rating value validity (`ERR_INVALID_RATING`), and finally optimistic-concurrency mismatch on PATCH (`ERR_VERSION_CONFLICT`). When two competing failures could fire, the lower-priority check is suppressed.

### 2.9. Cascade Semantics and Version Discipline

Some workflows mutate a chain of entities in a single request. Whenever a workflow writes to an entity beyond the one named in the URL — for example, a granted claim that bumps `Veteran.combined_rating`, or a removed dependent that re-runs subsistence on an `ACTIVE` voc-rehab plan, or a reopened claim that invalidates `certified_tuition_payable` on `CERTIFIED` and `ACTIVE` enrollments and auto-suspends a running voc-rehab plan — every affected entity has its `version` incremented and its `updated_at` rewritten in the same atomic transaction. Append-only ledger rows (`HousingPayment`, `PaymentLedgerEntry`) are created fresh; they do not bump a `version` since they have none.

### 2.10. The Append-Only Payment Ledger

Every dollar movement and every entitlement-month consumption is journaled into a single `PaymentLedgerEntry` table. Each entry records the `veteran_id` it belongs to, the `source_entity` that produced it — one of `TUITION_PAYMENT`, `HOUSING_PAYMENT`, `YELLOW_RIBBON_VA_MATCH`, `VOC_REHAB_SUBSISTENCE`, or `ENTITLEMENT_DEBIT` — the `source_id` of the producing row (an `Enrollment`, `HousingPayment`, `YellowRibbonContribution`, or `VocRehabPlan`), the `amount_dollars` (positive for credits to the veteran, negative when reversing a prior payment or when journaling an entitlement-month debit), and a server-stamped `posted_at` ISO 8601 UTC timestamp set to the moment of emission. Ledger rows are never updated or deleted; corrections are journaled as new compensating entries. Because the ledger is append-only, `PaymentLedgerEntry` carries only `id` and `created_at` — no `updated_at`, no `version`.

### 2.11. Concurrency and Serialization Guarantees

Concurrent requests that target the same shared mutable state serialize deterministically. When two raters issue start-review on the same `SUBMITTED` claim simultaneously, exactly one becomes the recorded `rater_id`; the loser receives `ERR_INVALID_STATE` at HTTP 409 because the claim has already left `SUBMITTED`. When the same rater fires grant and deny on the same `UNDER_REVIEW` claim in parallel, exactly one terminal transition lands and the second returns `ERR_INVALID_STATE`. Two simultaneous certify attempts on the same `SUBMITTED` enrollment likewise resolve to one winner with the loser receiving `ERR_INVALID_STATE`. Two creations of a housing payment for the same `(enrollment_id, month_year)` pair collide on a uniqueness constraint and the loser receives `ERR_PAYMENT_ALREADY_POSTED` at HTTP 409. Two attempts to create a supplemental claim against the same original claim (when the original is currently `GRANTED`) collide on a uniqueness constraint over `(original_claim_id, status in {SUBMITTED, UNDER_REVIEW})` and the loser receives `ERR_DUPLICATE_SUPPLEMENTAL` at HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Veteran Onboarding and the Service-History Tier

The lifecycle begins with a `Veteran` record that captures the legal `full_name` (1 to 120 characters), the service `branch` (one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINES`, `COAST_GUARD`, or `SPACE_FORCE`), the `aggregate_active_duty_days` count (a non-negative integer summarizing qualifying active-duty service after 9/10/2001), and the `discharge_status` (one of `HONORABLE`, `GENERAL`, `OTHER_THAN_HONORABLE`, `BAD_CONDUCT`, or `DISHONORABLE`). Either a `VAClerk` or a `PlatformAdmin` may register the veteran; a successful registration returns a 201 with the newly minted record, whose `combined_rating` defaults to 0 (no service-connected claims yet), whose `months_entitlement_used` defaults to 0.00, and whose `post_911_eligibility_tier` is computed immediately from the supplied duty days.

The Post-9/11 GI Bill tier is a stepwise function of `aggregate_active_duty_days`. Below 90 days the tier is 0; from 90 up to 180 days the tier is 40; from 180 up to 365 days the tier is 50; from 365 up to 547 days (eighteen months) the tier is 60; from 547 up to 730 days (two years) the tier is 70; from 730 up to 913 days (thirty months) the tier is 80; from 913 up to 1095 days (thirty-six months) the tier is 90; and at 1095 days or more (three years or more) the tier is 100. Each band is inclusive on its lower bound and exclusive on its upper bound. The tier is recomputed whenever a clerk later patches `aggregate_active_duty_days`, and defensively re-run whenever the combined-rating recomputation fires.

The `aggregate_active_duty_days` value is the sole field a clerk or admin may modify after onboarding. The patch endpoint accepts the new value and an optional `version` for the OCC check; on success the tier is recomputed, the veteran's `version` increments, and `updated_at` is refreshed. The `branch`, `full_name`, and `discharge_status` are immutable through this API — they are accepted at registration time and not editable afterwards.

### 3.2. Dependents and the Family-Size Multiplier

A veteran's dependents enter the system via the dependent-creation endpoint, which requires the owning `veteran_id`, the `relationship` (`SPOUSE`, `CHILD`, or `PARENT`), the `date_of_birth`, and — for the `CHILD` case only — an optional `school_enrolled` boolean that defaults to false. A `Dependent` row starts in `ACTIVE` status with `removed_at` null, and ages or removals later flip it to `REMOVED`. For a child dependent the system enforces that the child is either younger than 18 at creation, or between 18 and 23 inclusive with `school_enrolled` set to true; any child outside that envelope is rejected with `ERR_DEPENDENT_AGE`. A `SPOUSE` is subject to an additional uniqueness rule: a veteran may have at most one spouse in `ACTIVE` status at any time, and a second active-spouse creation is rejected with `ERR_DUPLICATE_SPOUSE`. The only mutable field on a dependent is the `school_enrolled` flag; the patch endpoint accepts that boolean and an optional `version`.

Removing a dependent moves it from `ACTIVE` to `REMOVED`, stamps `removed_at` with the current server clock, and triggers two cascades. First, for every `Enrollment` of this veteran currently in `CERTIFIED` with `delivery_mode` equal to `IN_PERSON`, `certified_tuition_payable` is left unchanged but future housing payments will be re-evaluated against the new dependent count when those months are next swept. Second, if the veteran has a `VocRehabPlan` in `ACTIVE` status, monthly subsistence is recomputed against the new active-dependent count and `monthly_subsistence` is rewritten in place. The dependent count that subsistence sees is the count of `ACTIVE` dependents **after** the triggering removal has been applied — so a removal that takes the count from 3 down to 2 must, at the moment subsistence is recomputed, see 2 dependents, not 3.

### 3.3. Filing, Reviewing, and Granting Disability Claims

A `Claim` represents a single condition the veteran asserts as service-connected. Filing a claim requires the `veteran_id`, the `condition_code` (a lowercase-alphanumeric-and-underscore identifier of 1 to 32 characters identifying the VA diagnostic code, for example `5237_lumbar`), the `claim_type` (`ORIGINAL` or `SUPPLEMENTAL`), the `proposed_rating` (the veteran-proposed disability percentage as an integer in `{0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}`), and — required only when `claim_type` is `SUPPLEMENTAL` — the `original_claim_id` referencing a prior claim. A veteran may file their own claims (where `veteran_id` equals their `X-User-ID`), and a `VAClerk` may file on behalf of any veteran. A supplemental's referenced `original_claim_id` MUST point to a claim whose `status` is either `GRANTED` or `DENIED_FINAL`; if the reference is missing or points to a claim in any other status (notably `DENIED` awaiting appeal), the request is rejected with `ERR_SUPPLEMENTAL_REFERENCE_INVALID`. The condition code is unique with `veteran_id` while the claim is not in `DENIED_FINAL`; the supplemental path is the mechanism for re-asserting a condition that has been adjudicated.

A newly filed claim begins life in `SUBMITTED`. The rater workflow advances it: starting a review by a `Rater` moves a claim from `SUBMITTED` to `UNDER_REVIEW` and stamps the rater's `X-User-ID` as `rater_id`. The same review-start gesture is also the entry point for a previously appealed claim: when a claim is in `APPEALED`, starting a review again moves it back to `UNDER_REVIEW`, but the rater handling the appealed re-review MUST have an `X-User-ID` different from the `rater_id` that performed the prior decision — a same-rater reattempt is rejected with `ERR_SEGREGATION_VIOLATION`. On a successful re-review the `rater_id` is overwritten with the new rater.

From `UNDER_REVIEW` a rater takes one of two adversarial decisions. Granting the claim requires a `granted_rating` in the request body, which must be an integer in `{0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}` — any other value is rejected with `ERR_INVALID_RATING`. A successful grant writes `granted_rating` and `decided_at` on the claim, then re-runs the combined-rating computation for the owning veteran and writes the result into `Veteran.combined_rating`, then re-runs the Post-9/11 tier computation (a defensive recompute even though duty days have not changed). Both adversarial decisions are bound by segregation of duties: the rater who grants and the rater who denies a claim MUST have an `X-User-ID` different from any `rater_id` already recorded on that claim (for example, on a supplemental claim whose original was decided earlier, or on a re-reviewed claim that previously cycled through `APPEALED`); a same-rater grant or deny is rejected with `ERR_SEGREGATION_VIOLATION`. Denying the claim moves it from `UNDER_REVIEW` to `DENIED`, stamps `decided_at`, and writes no rating. A denied claim can be appealed by the owning veteran — the appeal transition flips `DENIED` to `APPEALED` and is gated on the caller being the owning veteran (`X-User-ID` equal to `Claim.veteran_id`). An unappealed denied claim becomes terminal after 365 days: the periodic sweep advances any claim whose `decided_at` is at least 365 days in the past and which has not been appealed from `DENIED` to `DENIED_FINAL`.

A granted claim can be reopened by a different rater. Reopening flips `GRANTED` back to `UNDER_REVIEW`, and like the appealed-claim re-review it enforces segregation: the rater performing the reopen MUST have an `X-User-ID` different from the `rater_id` already on the claim. A reopen re-runs the combined-rating computation for the veteran (treating the about-to-be-overwritten granted rating as 0 for the recompute and writing the new result into `Veteran.combined_rating`), invalidates `certified_tuition_payable` (sets it back to null) on every `Enrollment` of this veteran in `CERTIFIED` or `ACTIVE`, and auto-suspends any `VocRehabPlan` of this veteran in `ACTIVE` (advancing it to `SUSPENDED` exactly as if a counselor had explicitly suspended it). All three cascades execute in the same atomic request — the `version` and `updated_at` on the veteran, the affected enrollments, and the voc-rehab plan are all bumped together.

### 3.4. The Combined-Rating Computation

The combined-rating computation runs whenever a claim transitions into `GRANTED`, whenever a granted claim is reopened, and whenever a granted claim's rating is amended. Its inputs are the granted ratings of every claim belonging to this veteran whose `status` is currently `GRANTED` — claims in `SUBMITTED`, `UNDER_REVIEW`, `DENIED`, `APPEALED`, or `DENIED_FINAL` are excluded. The algorithm processes those granted ratings in descending order of value, with ties broken by ascending `Claim.id`. It begins with a remaining-efficiency factor of 1.0, and for each rating `r` in the sorted list it multiplies the remaining-efficiency factor by `(1.0 minus r divided by 100.0)`. After every rating has been folded in, the raw combined value is `(1.0 minus the remaining-efficiency factor) multiplied by 100.0` — a fractional percentage. This raw value is then rounded half-up to the nearest whole percent; the resulting integer is then divided by 10, rounded half-up to the nearest integer, and multiplied by 10 to land on the VA's multiples-of-ten ladder. The final figure is clamped into the inclusive range from 0 to 100 and written to `Veteran.combined_rating`. The two-step rounding (to whole percent first, to nearest 10 second) is intentional and is what the system stores.

### 3.5. Schools and the BAH Lookup

A `School` is registered by a `PlatformAdmin` and carries an institutional `name` (1 to 200 characters), an 8-character `facility_code` unique across all schools, a `program_type` (`PUBLIC_IN_STATE`, `PRIVATE_NATIONAL`, `FOREIGN`, or `VOC_TECH`), a `yellow_ribbon_enrolled` boolean flag, an optional `yellow_ribbon_max_per_year` dollar cap on the school's per-veteran-per-year Yellow Ribbon contribution (required when `yellow_ribbon_enrolled` is true, defaulted to 0.00 otherwise, with two decimal places), and a 5-digit numeric `zip_bah_code` used by the housing-allowance lookup. The `program_type` is the lever that drives the cap on VA-payable tuition (see §3.7), and `zip_bah_code` is the lever that drives the housing allowance base rate.

### 3.6. Enrollment Submission and Term-Window Rules

An enrollment is the unit of academic activity. Submitting an enrollment requires the `veteran_id` (the veteran whose entitlement will be drawn down), the `school_id`, the `term_start` and `term_end` (UTC midnights bounding a half-open interval), the gross `tuition_charged` the school will levy for this term in dollars to two decimal places, the `training_time` (one of `FULL_TIME`, `THREE_QUARTER`, `HALF_TIME`, or `LESS_THAN_HALF`), and the `delivery_mode` (`IN_PERSON` or `ONLINE_ONLY`). Either the owning veteran (where `veteran_id` equals their `X-User-ID`) or a `VAClerk` may submit. The enrollment is created in `SUBMITTED` status with `months_consumed` defaulted to 0.00 and `certified_tuition_payable` null.

The term window is validated immediately. `term_end` MUST be strictly greater than `term_start`; an empty or inverted range is rejected with `ERR_INVALID_TERM_RANGE`. The system additionally enforces that this veteran has no other enrollment in `SUBMITTED`, `CERTIFIED`, or `ACTIVE` whose half-open interval `[term_start, term_end)` overlaps the new one — overlap is rejected with `ERR_ENROLLMENT_OVERLAP`. Because the interval is half-open, an enrollment ending exactly at midnight on the day a successor begins is treated as non-overlapping. The same two checks apply to the enrollment-patch endpoint that lets a clerk fix a mistyped term window.

A submitted enrollment can be canceled directly by a clerk, which moves it from `SUBMITTED` to `CANCELED` and stops the lifecycle without any ledger emission. Otherwise the next step is certification.

### 3.7. Certification, the Tuition Cap, and the Yellow Ribbon Waterfall

A clerk certifies a submitted enrollment by moving it from `SUBMITTED` to `CERTIFIED`. The certification gate has one cross-cutting business rule: the owning veteran's `discharge_status` MUST be `HONORABLE` — any other discharge status is rejected with `ERR_INELIGIBLE_DISCHARGE`. On a successful certification two calculations run.

The first calculation is the VA-payable tuition. Each `program_type` carries a per-term maximum: a `PUBLIC_IN_STATE` school is treated as effectively uncapped (a sentinel ceiling of 100000.00 dollars per term is used, which exceeds plausible in-state tuition); a `PRIVATE_NATIONAL` or `FOREIGN` school caps at 13041.34 dollars per term (the statutory annual figure split in half); a `VOC_TECH` school caps at 6520.67 dollars per term. The capped tuition is the smaller of `Enrollment.tuition_charged` and that program-specific per-term maximum. That capped figure is then multiplied by the veteran's `post_911_eligibility_tier` expressed as a fraction (so a tier of 100 means multiply by 1.00, a tier of 80 means multiply by 0.80, a tier of 0 means multiply by 0.00). The final product is rounded half-up to two decimal places exactly once, at the very end — rounding the cap before the multiplication is not equivalent and is not what the system does. The result is written to `Enrollment.certified_tuition_payable`.

The second calculation, the Yellow Ribbon allocation, runs only when `School.yellow_ribbon_enrolled` is true AND `Enrollment.tuition_charged` exceeds the per-term tuition cap derived above. The tuition gap is the difference between `tuition_charged` and the cap (floored at zero so a gap is never negative); this value is recorded as `tuition_gap` on the `YellowRibbonContribution` that is created. From the gap a four-step waterfall allocates dollars. The school's contribution is the smaller of two ceilings: the school's per-year cap `yellow_ribbon_max_per_year`, and half of the tuition gap floored to whole cents (the floor-to-cent rounding here is deliberate and is the one exception to the global half-up rule). The VA's match (`va_match`) is exactly equal to the school's contribution — VA matches the school dollar-for-dollar. The student's remaining responsibility (`student_responsibility`) is the tuition gap minus the school contribution minus the VA match, rounded half-up to two decimal places. There is a critical eligibility gate: a Yellow Ribbon match is only available when the veteran's `post_911_eligibility_tier` equals 100; if it is below 100 (or if the veteran is not on the GI Bill at all), the school's contribution and the VA match are both forced to 0.00 and the entire tuition gap is rounded half-up and assigned as the student's responsibility. Across an academic year (January 1 through December 31, indexed by each enrollment's `term_start`), the cumulative sum of `school_contribution` for a given school MUST NOT exceed that school's `yellow_ribbon_max_per_year`; a certification that would push the cumulative figure past the school's cap is rejected with `ERR_YELLOW_RIBBON_CAP_EXCEEDED`.

A clerk may cancel a certified enrollment. Cancellation moves it from `CERTIFIED` to `CANCELED`. If a tuition-payment ledger entry was already emitted for this enrollment (i.e., the enrollment had advanced to `ACTIVE` and the ledger had paid out), a compensating ledger entry with `source_entity` `TUITION_PAYMENT` and a negative `amount_dollars` equal to the prior `certified_tuition_payable` is journaled; if no prior tuition entry exists, no ledger entry is emitted. If a Yellow Ribbon contribution exists for this enrollment, its `school_contribution`, `va_match`, and `student_responsibility` are all reset to 0 (the tuition gap collapses to zero on a canceled enrollment).

### 3.8. Activating Enrollments via Clock and Sweep

A certified enrollment becomes `ACTIVE` not by an explicit user action but by a system-driven transition gated on time and on the veteran's disability status. The sweep is the mechanism: it scans every `CERTIFIED` enrollment and promotes those whose `term_start` is at or before the current server clock AND whose owning veteran's `combined_rating` is strictly greater than 0. The combined-rating gate is the system's enforcement of service connection — a veteran with no granted disability claim cannot draw GI Bill benefits, and an explicit activation request that fails the combined-rating gate is rejected with `ERR_CROSS_ENTITY_PRECONDITION`. On activation two ledger entries are journaled: a `TUITION_PAYMENT` entry with positive `amount_dollars` equal to `certified_tuition_payable` and `source_id` equal to the enrollment's `id`, and — when a `YellowRibbonContribution` exists for this enrollment — a `YELLOW_RIBBON_VA_MATCH` entry with `amount_dollars` equal to that contribution's `va_match`. Both entries are stamped with the current server clock as `posted_at`.

Two PlatformAdmin-only test driver capabilities exist so deterministic tests can land time-gated states. One advances the logical server clock, accepting a body with either a `to` timestamp (an ISO 8601 instant the clock jumps to) or a `seconds` integer (the clock advances by that many seconds), and returning the new now. The other runs the periodic sweep, which is idempotent: it performs the certified-to-active promotions described above and also performs the denied-to-final claim transition for any denied claim whose `decided_at` is at least 365 days in the past with no intervening appeal. The sweep returns counts of `activated_enrollments` and `finalized_claims`. Without these driver capabilities tests would have no deterministic way to exercise either time-gated transition.

### 3.9. Completing and Withdrawing — the Entitlement Counter

An active enrollment ends in one of two ways. A clerk completes it when its `term_end` has been reached or passed, moving it from `ACTIVE` to `COMPLETED`. Alternatively, the owning veteran withdraws mid-term (their `X-User-ID` must equal the enrollment's `veteran_id`), moving it from `ACTIVE` to `WITHDRAWN`. Both transitions compute `months_consumed` for this enrollment and re-run the entitlement counter for the veteran. For a completed enrollment the days-in-program is the count of UTC days from `term_start` to `term_end`; for a withdrawal it is the count from `term_start` to the smaller of the current clock and `term_end`. In both cases `Enrollment.months_consumed` is set to days-in-program divided by 30, rounded half-up to two decimal places.

The veteran's cumulative entitlement is then refreshed by walking every `Enrollment` of the veteran in `COMPLETED` or `WITHDRAWN` status in ascending order of `term_start`. For each such enrollment the per-enrollment months is recomputed under the same rule (full term-length for a completion, attendance-truncated for a withdrawal), each rounded half-up to two decimal places, and the per-enrollment values are summed. The cumulative sum is capped at 36.00 — no veteran is ever recorded as having consumed more than 36.00 months of Post-9/11 entitlement, and excess past the cap is simply not credited — and the capped result is rounded half-up to two decimal places and written into `Veteran.months_entitlement_used`. The fiscal guard fires before the transition is allowed to land: if completing or withdrawing this enrollment would cause the cumulative sum across all `COMPLETED` and `WITHDRAWN` enrollments to rise above 36.00 after the rounding, the transition is rejected with `ERR_ENTITLEMENT_EXCEEDED`. The check is a sum-then-test boundary, not a per-row test — a single enrollment that on its own would push the total above 36.00 fails, but so does an enrollment that would be perfectly legal in isolation if prior enrollments have already eaten most of the budget.

Each successful completion or withdrawal also journals a single `PaymentLedgerEntry` with `source_entity` `ENTITLEMENT_DEBIT` and `amount_dollars` equal to the negative of `months_consumed` for this enrollment (the ledger uses negative dollars to express entitlement-month debits — the unit shift is deliberate, since the ledger is a single stream).

The veteran's own view of how much entitlement remains is served by the entitlement-projection endpoint, which accepts a query parameter `include_certified` (defaulting to false). When `include_certified` is false the endpoint returns the same chronological figure that is written to `months_entitlement_used` — a sum over `COMPLETED` and `WITHDRAWN` enrollments only. When `include_certified` is true the endpoint projects forward by ALSO including every `CERTIFIED` and `ACTIVE` enrollment as if it had been completed for its full term — `term_end` minus `term_start` divided by 30, rounded half-up. The projection result is NOT written back to `months_entitlement_used` — it exists solely to answer "how much would I have left if every certified enrollment plays out?" The response carries both a chronological figure and a projected figure plus the remaining months under each.

### 3.10. Monthly Housing Allowance Calculations

Each month a `VAClerk` posts a housing payment for an active enrollment by calling the housing-payment endpoint and supplying a `month_year` (a "YYYY-MM" string matching the regex of a four-digit year followed by a two-digit month in 01–12). The pair `(enrollment_id, month_year)` is unique — a duplicate posting is rejected with `ERR_PAYMENT_ALREADY_POSTED`. The supplied `month_year` MUST share at least one UTC day with the enrollment's half-open term interval; a month wholly outside the term (no overlapping day at all) is rejected with `ERR_PAYMENT_OUTSIDE_TERM`. Note the deliberate semantic difference between this check and the enrollment-overlap rule: the housing-payment check is a closed-month against a half-open-term intersection, where any overlapping day suffices; the enrollment-overlap check is a half-open-versus-half-open comparison, where same-day adjacency does NOT count as overlap.

A successful posting computes the housing allowance and creates a `HousingPayment` row recording the `enrollment_id`, the `month_year`, the computed `amount` (dollars to two decimal places), and the `computation_basis` indicating which arm of the calculation produced the dollar figure (`IN_PERSON_TIERED`, `ONLINE_HALF_NATIONAL`, or `PRORATED_PARTIAL_MONTH`). A `PaymentLedgerEntry` with `source_entity` `HOUSING_PAYMENT`, `source_id` equal to the housing-payment's `id`, and a positive `amount_dollars` equal to the computed amount is journaled in the same request.

The housing-allowance computation begins with a base BAH dollar amount. For an in-person enrollment, the base is the BAH table value for the school's `zip_bah_code` (the E-5 with-dependents rate by ZIP). For an online-only enrollment, the base is half of a fixed national-average BAH constant of 1789.00 dollars; the ZIP is not consulted. To that base the system adds a dependent uplift: count the veteran's dependents in `ACTIVE` status at the start of the month; for each dependent beyond the second, add 50.00 dollars to the monthly rate, capped at a total uplift of 200.00 dollars. So 0, 1, or 2 active dependents contribute 0.00 in uplift; 3 dependents contribute 50.00; 4 dependents contribute 100.00; 5 dependents contribute 150.00; 6 or more dependents contribute the capped 200.00. The result so far is the monthly rate.

The monthly rate is then multiplied by the veteran's `post_911_eligibility_tier` as a fraction (so a tier of 100 means times 1.00, a tier of 60 means times 0.60, and so on), then multiplied by a training-time proration factor derived from `training_time`: `FULL_TIME` multiplies by 1.00, `THREE_QUARTER` by 0.80, `HALF_TIME` by 0.50, and `LESS_THAN_HALF` by 0.00 (so a veteran enrolled less than half-time draws no housing allowance regardless of tier or dependents). When the month is partially covered by the term — fewer than all days of the calendar month fall inside the half-open `[term_start, term_end)` window — a partial-month proration multiplies the rate by the count of in-term UTC days within the month divided by the total UTC days in the month, and the `computation_basis` is recorded as `PRORATED_PARTIAL_MONTH`; otherwise no proration applies and the basis is whichever of `IN_PERSON_TIERED` or `ONLINE_HALF_NATIONAL` matches the delivery mode. The final raw figure is rounded half-up to two decimal places exactly once and stored as `amount`. Because the ledger is append-only, the same monthly housing entry is never updated in place; a posting that turned out to be wrong is corrected by journaling a compensating entry, not by editing the original.

### 3.11. Voc Rehab Plans — Approval, Cycling, and Termination

A `Counselor` may create a Voc Rehab plan for a veteran by submitting the owning `veteran_id` and the `training_mode` (one of `FULL_TIME_INSTITUTIONAL`, `THREE_QUARTER_INSTITUTIONAL`, `HALF_TIME_INSTITUTIONAL`, `FARM_COOP`, or `NON_PAY_OJT`). The plan is created in `DRAFT` status with `counselor_id` null, `suspension_count` zero, and `monthly_subsistence` null. Approval is the first material step: the counselor moves the plan from `DRAFT` to `APPROVED`, which requires that the veteran's `combined_rating` be at least 20 (a granted claim of at least 20 percent combined disability) — a draft plan whose veteran has a combined rating below 20 cannot be approved and the approval is rejected with `ERR_CROSS_ENTITY_PRECONDITION`. As with enrollment certification, approval is a benefit-producing operation and additionally requires the veteran's `discharge_status` to be `HONORABLE`; any other discharge status is rejected with `ERR_INELIGIBLE_DISCHARGE`. A successful approval stamps the approving counselor's `X-User-ID` as `counselor_id` and runs the subsistence computation to set `monthly_subsistence`.

The subsistence base rate is selected by `training_mode`: 883.00 dollars per month for `FULL_TIME_INSTITUTIONAL`, 662.00 for `THREE_QUARTER_INSTITUTIONAL`, 441.00 for `HALF_TIME_INSTITUTIONAL`, 772.00 for `FARM_COOP`, and 0.00 for `NON_PAY_OJT`. A dependent uplift is then added: count the veteran's dependents in `ACTIVE` status at the moment the trigger transition completes — so for the approval transition itself, this is the count at approval time; for a dependent-removal cascade, this is the count after the removal has been applied — and if the count is 2 or fewer, the uplift is 0.00 dollars; if the count exceeds 2, the uplift is 65.00 dollars per dependent beyond the second (so 3 dependents add 65.00, 4 add 130.00, 5 add 195.00, with no cap). The base plus the uplift is rounded half-up to two decimal places and written to `monthly_subsistence`.

An approved plan is started by the counselor, moving it from `APPROVED` to `ACTIVE`. From `ACTIVE` the plan can either be completed (`ACTIVE` to `COMPLETED`, a terminal state) or suspended (`ACTIVE` to `SUSPENDED`). Suspension increments `suspension_count` by exactly 1 and freezes subsistence accrual for the month. A suspended plan can be resumed (`SUSPENDED` to `ACTIVE`) by a counselor whose `X-User-ID` differs from the original `counselor_id` who approved the plan — a same-counselor resume is rejected with `ERR_SEGREGATION_VIOLATION`. The resume is gated on `suspension_count` being strictly less than 3. The third suspension is auto-terminal: when a suspend call raises `suspension_count` to 3 (i.e., the plan is currently `ACTIVE` with `suspension_count` already 2, and a third suspension fires), the plan transitions in the same request from `ACTIVE` to `SUSPENDED` and then immediately to `TERMINATED`. Once terminated, the plan blocks all further `VOC_REHAB_SUBSISTENCE` ledger entries against it from the moment of termination onwards.

Voc Rehab also participates in the deepest cascade in the system. When a granted claim is reopened (§3.3), three downstream effects fire as legs of a single chain: the veteran's combined rating is recomputed; every `CERTIFIED` or `ACTIVE` enrollment of the veteran has its `certified_tuition_payable` reset to null; and any `ACTIVE` voc-rehab plan of the veteran is auto-suspended exactly as if a counselor had explicitly invoked the suspend transition (the `suspension_count` increments, subsistence accrual for the month is forfeit, and if this cascade brings the count to 3 the plan terminates immediately).

### 3.12. Read-Only Access — Ledger and Projections

A veteran can pull their own ledger (`source_entity` filter is supported as an optional query parameter alongside `limit` and `offset`) and their own forward-looking entitlement projection. A `VAClerk` and a `PlatformAdmin` can pull anyone's ledger and projection. The ledger is the authoritative audit trail: every dollar credited or debited against any veteran exists as a `PaymentLedgerEntry` row, ordered by `created_at` ascending under the default sort. The dependent list (`status` is a supported optional filter), the claim list (`status` is a supported optional filter), the enrollment, the school, the voc-rehab plan, the Yellow Ribbon contribution attached to an enrollment, and the housing-payment collection for an enrollment are all retrievable through their respective GET endpoints subject to the ownership and role checks described in §2.1 and §4.

## 4. Endpoint Definitions

The endpoint table summarizes every HTTP route the API exposes. Successful resource creation returns HTTP 201; every other successful response, including state-machine transitions, PATCH updates, and reads, returns HTTP 200. Error responses use the HTTP status codes catalogued in §5 and the envelope format defined in §2.2. Request and response payload shapes are NOT enumerated in this table — the reader reconstructs them from §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|---------------------|
| POST | `/veterans` | Register a new veteran. | `VAClerk`, `PlatformAdmin` |
| GET | `/veterans/{id}` | Retrieve a veteran with computed combined rating and tier. | `Veteran`, `VAClerk`, `Rater`, `Counselor`, `PlatformAdmin` |
| PATCH | `/veterans/{id}` | Update aggregate active-duty days. | `VAClerk`, `PlatformAdmin` |
| GET | `/veterans/{id}/entitlement-projection` | Chronological or forward-looking entitlement projection, switched by the `include_certified` query parameter. | `Veteran`, `VAClerk`, `PlatformAdmin` |
| POST | `/dependents` | Add a dependent to a veteran. | `VAClerk`, `PlatformAdmin` |
| PATCH | `/dependents/{id}` | Update the school-enrolled flag. | `VAClerk`, `PlatformAdmin` |
| DELETE | `/dependents/{id}` | Remove a dependent. | `VAClerk`, `PlatformAdmin` |
| GET | `/veterans/{id}/dependents` | List a veteran's dependents (filter by `status`). | `Veteran`, `VAClerk`, `PlatformAdmin` |
| POST | `/claims` | File a new disability claim. | `Veteran`, `VAClerk` |
| POST | `/claims/{id}/start-review` | Move a submitted or appealed claim to under review. | `Rater` |
| POST | `/claims/{id}/grant` | Grant the claim with an explicit granted rating. | `Rater` |
| POST | `/claims/{id}/deny` | Deny the claim. | `Rater` |
| POST | `/claims/{id}/appeal` | Veteran appeals a denied claim. | `Veteran` |
| POST | `/claims/{id}/reopen` | Reopen a previously granted claim. | `Rater` |
| GET | `/claims/{id}` | Retrieve a claim. | `Veteran`, `VAClerk`, `Rater`, `PlatformAdmin` |
| GET | `/veterans/{id}/claims` | List a veteran's claims (filter by `status`). | `Veteran`, `VAClerk`, `Rater`, `PlatformAdmin` |
| POST | `/schools` | Register an institution. | `PlatformAdmin` |
| GET | `/schools/{id}` | Retrieve a school. | `Veteran`, `VAClerk`, `Counselor`, `PlatformAdmin` |
| POST | `/enrollments` | Submit a new enrollment. | `Veteran`, `VAClerk` |
| POST | `/enrollments/{id}/certify` | Certify the enrollment and run tuition and Yellow Ribbon calculations. | `VAClerk` |
| POST | `/enrollments/{id}/cancel` | Cancel a certified enrollment. | `VAClerk` |
| POST | `/enrollments/{id}/complete` | Mark an active enrollment completed at term end. | `VAClerk` |
| POST | `/enrollments/{id}/withdraw` | Veteran withdraws from an active enrollment mid-term. | `Veteran` |
| POST | `/enrollments/{id}/housing-payments` | Post a monthly housing payment for an enrollment. | `VAClerk` |
| GET | `/enrollments/{id}` | Retrieve an enrollment. | `Veteran`, `VAClerk`, `PlatformAdmin` |
| GET | `/enrollments/{id}/yellow-ribbon` | Retrieve the Yellow Ribbon contribution for an enrollment. | `Veteran`, `VAClerk`, `PlatformAdmin` |
| GET | `/enrollments/{id}/housing-payments` | List housing payments for an enrollment. | `Veteran`, `VAClerk`, `PlatformAdmin` |
| POST | `/voc-rehab-plans` | Create a draft Voc Rehab plan. | `Counselor` |
| POST | `/voc-rehab-plans/{id}/approve` | Approve the plan and set monthly subsistence. | `Counselor` |
| POST | `/voc-rehab-plans/{id}/start` | Start the plan (approved to active). | `Counselor` |
| POST | `/voc-rehab-plans/{id}/suspend` | Suspend an active plan (auto-terminates on the third suspension). | `Counselor` |
| POST | `/voc-rehab-plans/{id}/resume` | Resume a suspended plan (different counselor than the approver). | `Counselor` |
| POST | `/voc-rehab-plans/{id}/complete` | Complete an active plan. | `Counselor` |
| GET | `/voc-rehab-plans/{id}` | Retrieve a Voc Rehab plan. | `Veteran`, `Counselor`, `PlatformAdmin` |
| GET | `/veterans/{id}/ledger` | List the append-only payment ledger for a veteran (filter by `source_entity`). | `Veteran`, `VAClerk`, `PlatformAdmin` |
| POST | `/_clock/advance` | Test-only: advance the server clock by `to` or `seconds`. | `PlatformAdmin` |
| POST | `/_sweep/run` | Test-only: run the periodic sweep (certified-to-active promotions and denied-to-final claim closures). | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_PRECONDITION` | 409 |
| `ERR_SEGREGATION_VIOLATION` | 403 |
| `ERR_INELIGIBLE_DISCHARGE` | 403 |
| `ERR_SUPPLEMENTAL_REFERENCE_INVALID` | 422 |
| `ERR_INVALID_TERM_RANGE` | 422 |
| `ERR_ENROLLMENT_OVERLAP` | 409 |
| `ERR_PAYMENT_OUTSIDE_TERM` | 422 |
| `ERR_PAYMENT_ALREADY_POSTED` | 409 |
| `ERR_DEPENDENT_AGE` | 422 |
| `ERR_DUPLICATE_SPOUSE` | 409 |
| `ERR_ENTITLEMENT_EXCEEDED` | 422 |
| `ERR_YELLOW_RIBBON_CAP_EXCEEDED` | 422 |
| `ERR_INVALID_RATING` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_DUPLICATE_SUPPLEMENTAL` | 409 |

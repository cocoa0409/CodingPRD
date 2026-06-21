# VA Benefits Administration API — Product Requirements Document

## 1. Introduction

The Department of Veterans Affairs administers a tightly coupled set of benefits — disability compensation, the Post-9/11 GI Bill, the Yellow Ribbon program, and Chapter 31 Vocational Rehabilitation — whose dollar amounts all flow from a single source of truth: a veteran's adjudicated service-connected conditions and their service history. This API exists to make that flow auditable and deterministic. A claim moves through adjudication, conditions attached to it are rated, and the moment a claim is granted the veteran's whole-person disability rating, monthly compensation, and downstream eligibility are recomputed in lockstep. The defining challenge of the domain is that none of these amounts is a simple sum: the combined disability rating uses the non-linear "VA math" of successive efficiency reduction, monthly compensation is a step function gated by a dependency threshold, and the housing allowance is a two-stage proration of a locality rate.

The product serves four distinct constituencies who never share a workflow but constantly share data. A claims adjudication officer drives the lifecycle of claims and awards; a medical rating examiner proposes and finalizes the schedular percentages that feed the math; a school certifying official converts a veteran's enrollment into a paid housing benefit; and the veteran themselves operates a self-service surface for their own claims, dependents, enrollments, and vocational-rehab plans. Because a grant on a claim silently changes the veteran's compensation, and because two officers can race to act on the same award, the system treats versioning and recomputation cascades as first-class correctness concerns rather than incidental bookkeeping.

This document specifies the global contract every endpoint obeys, the business rules that govern each benefit, and the exact error vocabulary the API speaks. It is written for the engineer who will build the service and must reconstruct every calculation, state transition, and guard from the narrative below.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted at the top level; there is no shared URL prefix beyond the root.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they are acting. The system recognizes exactly four roles, spelled precisely as `ClaimsAdmin`, `RatingSpecialist`, `SchoolCertifyingOfficial`, and `Veteran`. If either header is missing, or if `X-User-Role` is not one of these four declared role names, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

Three of the four roles are operator identities not tied to any persisted record. When `X-User-Role` is `ClaimsAdmin`, `X-User-ID` is an opaque operator identifier; the server may accept and log it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `RatingSpecialist` and when `X-User-Role` is `SchoolCertifyingOfficial`: each is an opaque operator identifier not backed by any stored entity, and the server performs no ownership comparison against it.

The fourth role is different. When `X-User-Role` is `Veteran`, `X-User-ID` is the `id` of the acting `Veteran` record. This role is self-service: a veteran may only act on resources that belong to them. For any resource that carries a `veteran_id` — a `Claim`, a `Condition`, a `Dependent`, an `Enrollment`, or a `VocRehabPlan` — ownership is checked by comparing that resource's `veteran_id` to `X-User-ID`, and for the veteran's own record by comparing its `id` to `X-User-ID`. A `Veteran` attempting to read or mutate another veteran's data is rejected with `ERR_FORBIDDEN`. This ownership comparison is itself part of the permission check and therefore surfaces as the same forbidden error rather than a not-found.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifier Resolution

Most resources in the system — the `Veteran`, the `Claim`, the `Condition`, the `School`, the `Enrollment`, and the `VocRehabPlan` — carry a standard set of system-managed fields. Each has an `id`, a unique server-minted UUID with no type prefix; a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; an `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification; and a `version`, an integer that begins at its initial value and increments by one on each mutation, supporting the optimistic concurrency control described in §2.6.

The `Dependent` resource is deliberately leaner. A dependent record carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version` field. Dependents are append-and-retire records: rather than being edited in place, a dependent is added once and later retired through a dedicated removal action, so the version and last-modified machinery does not apply to it.

When an endpoint path names more than one resource — for example a dependent nested beneath a veteran, or a condition created beneath a claim — the system validates the identifiers left to right. The outermost identifier is resolved first; if it does not correspond to an existing resource the request fails with `ERR_NOT_FOUND` before any inner identifier is examined. Only once the parent is confirmed does the system attempt to resolve the child. This left-to-right existence sweep is the third validation gate overall and yields `ERR_NOT_FOUND` for the first missing referent, whether it is named in the path or in the request body.

### 2.5. Precision, Rounding, and Monetary Representation

All monetary amounts in the system are stored and returned as integer counts of cents; there are no fractional-cent values in any response body. Wherever a calculation produces a non-integer intermediate — for instance when scaling a dependent allowance by a rating tier, or when prorating a housing rate — the result is reduced to whole cents using the round-half-up convention, meaning a value whose fractional remainder is exactly one half rounds upward. Disability rating percentages are whole integers; the combined rating is additionally snapped to the nearest multiple of ten, again rounding a half upward, and clamped to the inclusive range from 0 to 100. Rate-of-pursuit percentages are likewise whole integers produced by round-half-up. Every distinct rounding step described in §3 is performed in the order stated there; the order in which rounding is applied is part of the contract, not an implementation convenience.

### 2.6. Optimistic Concurrency Control on Award and Certification Writes

Certain high-stakes writes require the client to prove it is acting on a current view of the target resource by supplying that resource's last-observed `version`. Two operations are governed this way.

Activating or reactivating a veteran's monthly award is one. A request to activate a veteran's award must include `expected_veteran_version`, and the server compares it to the target `Veteran`'s current `version`. The motivation is concrete: granting any of the veteran's claims cascades into the veteran's `combined_rating_pct` and `monthly_compensation_cents` and advances `version`. If a grant has advanced the veteran's version since the operator last read the record, an activation that still carries the pre-cascade value is operating on a stale view of the award amount; the request is therefore rejected with `ERR_STALE_VERSION` at HTTP status 412, forcing the operator to re-read the freshly computed compensation before committing the award.

Certifying an enrollment is the other. A certification request must include `expected_enrollment_version`, compared to the target `Enrollment`'s current `version`. Because the housing allowance is finalized at certification from the veteran's tier and the term's rate of pursuit, an enrollment that was edited after the certifying official read it — re-deriving its estimated allowance and bumping its version — would otherwise be certified against a stale snapshot. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Granting and denying a claim each also require the matching version field, `expected_claim_version`, validated against the `Claim`'s current `version` and rejected with `ERR_STALE_VERSION` (HTTP 412) on mismatch. Endpoints not named in this subsection do not accept a version field and perform no concurrency check.

### 2.7. Cascading Recomputation and Hierarchical Consistency

The `Veteran` is the hub of the data model, and several of its fields are never written directly by a client — they are derived and refreshed by the server whenever an upstream fact changes. `combined_rating_pct`, `provisional_combined_rating_pct`, `gi_bill_tier_pct`, and `monthly_compensation_cents` are all computed fields on the veteran; the computed `voc_rehab_entitlement_months` is likewise server-maintained. Whenever the server recomputes one of these in response to an action elsewhere — a claim being granted, a dependent being added or removed, a service-time edit — that recomputation is a mutation of the veteran record and accordingly refreshes the veteran's `updated_at` and increments its `version`. The same holds for any entity whose state transition produces a side effect on itself: the transition refreshes `updated_at` and advances `version` unless that entity is the version-less `Dependent`.

The most consequential cascade is a three-hop chain that fires when a claim is granted, detailed in §3.4: the claim's conditions become service-connected, the veteran's combined rating is recomputed from the full service-connected set, and the monthly compensation is recomputed from that new rating together with the veteran's active dependents. Each hop is described where it belongs in the workflow narratives below rather than restated as a schema.

### 2.8. The Non-Linear Combined Rating Principle

A defining peculiarity of VA disability math is that ratings do not add. A 50 percent rating followed by a 30 percent rating does not yield 80 percent; it yields a smaller figure because each successive disability is taken only from the *efficiency that remains* after the prior ones. The system therefore never sums rating percentages. The full algorithm, its bilateral-factor variant, and its provisional variant are specified in §3.5 and §3.6, but the principle bears stating up front because it governs both the finalized `combined_rating_pct` and the provisional figure shown before a grant: every place the system speaks of a "combined" rating, it means the efficiency-reduction computation, never a linear total.

## 3. Business Logic & Workflows

### 3.1. Establishing a Veteran and Their Service Picture

The lifecycle begins when a claims adjudication officer creates a `Veteran` record by supplying the veteran's `full_name`, a `file_number`, and the veteran's `total_active_duty_days`; the boolean `discharged_for_service_disability` may also be supplied and is treated as `false` when omitted. The `file_number` is the veteran's unique VA file number and must be unique across all veterans — a create that reuses an existing file number is rejected with `ERR_DUPLICATE_FILE_NUMBER`. The `total_active_duty_days` is the aggregate count of creditable active-duty days served after September 10, 2001, and must be zero or greater.

Upon creation the record is seeded deterministically. The award state, `award_status`, starts at `DRAFT`. The disability figures `combined_rating_pct` and `provisional_combined_rating_pct` both start at 0, and `monthly_compensation_cents` starts at 0. The vocational-rehabilitation balance `voc_rehab_entitlement_months` starts at 48 months — the full Chapter 31 entitlement. And the GI Bill tier, `gi_bill_tier_pct`, is computed immediately from the supplied service history, as described in §3.7.

A claims officer may later revise the service picture, supplying a new `total_active_duty_days`, a new `discharged_for_service_disability`, or both. Such an edit recomputes `gi_bill_tier_pct` and increments the veteran's `version`. Because no other endpoint targets these two raw service-time inputs, this is the only path by which the GI Bill tier can change after creation.

A consolidated computed view is available for any veteran: a compensation summary that reports the veteran's `combined_rating_pct`, `provisional_combined_rating_pct`, `monthly_compensation_cents`, `gi_bill_tier_pct`, `voc_rehab_entitlement_months`, and the `active_dependent_count` — the number of the veteran's dependents currently in `ACTIVE` status. Claims officers and rating examiners may read any veteran's record, list, and summary; a veteran may read only their own.

### 3.2. Dependents and Their Effect on Compensation

A veteran's dependents drive part of the monthly award, but only once the veteran clears a rating threshold (see §3.8). A dependent is added either by a claims officer or by the veteran themselves, by supplying the dependent's `relationship` — one of `SPOUSE`, `CHILD`, or `PARENT` — and, for a child, the optional boolean `in_school_18_to_23`, which defaults to `false` and marks a child aged eighteen to twenty-three who is enrolled in school and therefore draws a higher additional amount. A new dependent is created with `status` set to `ACTIVE`. Each dependent references its veteran through the `veteran_id` established by the path under which it was created.

Adding a dependent immediately recomputes the veteran's `monthly_compensation_cents` and increments the veteran's `version`. Removing a dependent is a distinct action that flips the dependent's `status` to `REMOVED`, then likewise recomputes `monthly_compensation_cents` and increments the veteran's `version`. A `REMOVED` dependent is excluded from all compensation arithmetic from that point on. Dependents can be listed for a veteran, listed across the system with an optional filter on `veteran_id` and on `status`, and fetched individually. Because a dependent carries no `version`, none of these dependent operations participates in optimistic concurrency control.

### 3.3. Filing and Developing a Claim

A claim is the vehicle through which conditions are adjudicated. Either a claims officer or the veteran files a `Claim` by supplying the `veteran_id` it belongs to, the `claim_type` — one of `ORIGINAL`, `INCREASE`, or `SECONDARY` — and the `received_date`, the date the claim was received, which establishes effective-date priority with the earlier date winning on a tie. A new claim is created in `SUBMITTED` status with its `remand_count` set to 0.

Conditions are attached to a claim before adjudication. A claims officer or a rating examiner adds a `Condition` to a claim by supplying the owning `veteran_id`, the `diagnostic_code` from the VA Schedule for Rating Disabilities, the `proposed_rating_pct`, and optionally the `body_side` (`LEFT`, `RIGHT`, or `NONE`, defaulting to `NONE`) and the boolean `is_extremity` (defaulting to `false`, true when the rated part is a paired extremity such as an arm or leg). The condition records which claim adjudicates it via `claim_id`, taken from the path. The `proposed_rating_pct` is the examiner's proposed schedular percentage and must be a multiple of ten between 0 and 100 inclusive; a value that is not a multiple of ten or falls outside that range is rejected with `ERR_INVALID_REQUEST`. A freshly added condition has its `service_connection` set to `PROPOSED` and its `final_rating_pct` set to 0; the finalized percentage stays 0 until the parent claim is granted.

Moving a claim into active development advances it from `SUBMITTED` to `DEVELOPMENT`. This action is performed by a claims officer and is permitted only when the claim is in `SUBMITTED` status; from any other status the attempt is rejected with `ERR_INVALID_STATE`. It additionally requires that at least one condition reference this claim — opening development on a claim with zero conditions is rejected with `ERR_CLAIM_HAS_NO_CONDITIONS`. The same development-opening action is also how a remanded claim re-enters the pipeline: a claim in `REMANDED` status transitions back to `DEVELOPMENT`, reopening the cycle so that conditions can receive revised proposed ratings before re-rating. While a claim sits in `DEVELOPMENT`, a rating examiner may revise a condition's `proposed_rating_pct`, `body_side`, or `is_extremity`; such an edit increments the condition's `version`, and it is permitted only while the parent claim is in development.

### 3.4. Rating, Granting, Denying, and the Compensation Cascade

When development is complete, a rating examiner rates the claim, advancing it from `DEVELOPMENT` to `RATED`. Rating is permitted only from `DEVELOPMENT` (otherwise `ERR_INVALID_STATE`) and requires that *every* condition on the claim already carry a `proposed_rating_pct` in the valid multiple-of-ten range; if any condition is still unrated the request fails with `ERR_CONDITION_UNRATED`. Rating does not yet touch any condition's `final_rating_pct` — the ratings remain proposed, not final, and each condition's `final_rating_pct` stays 0. What rating does do is refresh the veteran's `provisional_combined_rating_pct` using the provisional variant of the combined-rating computation, which folds this claim's proposed condition ratings in alongside the veteran's already service-connected ratings.

From `RATED` the claim has three possible next moves, each driven by a claims officer. Granting the claim is the consequential one. A grant is permitted only from `RATED` and requires `expected_claim_version` to match the claim's current `version`, failing otherwise with `ERR_STALE_VERSION`. On a successful grant, the following cascade executes in order. First, every condition on the claim has its `service_connection` set to `SERVICE_CONNECTED` and its `final_rating_pct` set equal to its `proposed_rating_pct`. Second — cascade hop one to two — the veteran's `combined_rating_pct` is recomputed by the combined-rating algorithm over the veteran's entire set of service-connected conditions. Third — cascade hop two to three — the veteran's `monthly_compensation_cents` is recomputed from that new combined rating together with the veteran's active dependents. The veteran's `provisional_combined_rating_pct` is then refreshed as well, and it will equal `combined_rating_pct` when no other claim still carries merely proposed conditions. Finally, the claim's `version` is incremented by one.

Denying the claim is the parallel branch. A deny is likewise permitted only from `RATED` and likewise requires `expected_claim_version` to match the claim's `version`, rejecting a mismatch with `ERR_STALE_VERSION`. On a deny, every condition on the claim has its `service_connection` set to `NOT_CONNECTED` and its `final_rating_pct` left at 0. The veteran's `provisional_combined_rating_pct` is then recomputed without this claim's proposed ratings, and the claim's `version` is incremented by one.

Remanding from `RATED` is the third branch and is the lighter of the two remand paths: it is permitted only from `RATED` and only while the claim's `remand_count` is strictly less than the appeal cap of two rounds (otherwise `ERR_APPEAL_EXHAUSTED`); its sole effect is to advance the claim to `REMANDED` and increase `remand_count` by one.

### 3.5. The Appeal Loop and Re-Adjudication

A denied claim is not necessarily final. A claims officer may remand a claim from `DENIED` as well, again only while `remand_count` is strictly below the cap of two (otherwise `ERR_APPEAL_EXHAUSTED`). Remanding from `DENIED` does more than the from-`RATED` remand: besides advancing the claim to `REMANDED` and increasing `remand_count` by one, it reopens every condition on the claim by resetting `service_connection` to `PROPOSED` and `final_rating_pct` to 0, so the conditions are available for fresh re-adjudication. Because those conditions were already excluded from the service-connected set while denied, reopening them leaves that set unchanged; nonetheless the veteran's `combined_rating_pct` and `monthly_compensation_cents` are recomputed as part of this step so the figures reflect the current service-connected population, with any conditions granted on other claims remaining in place.

Once in `REMANDED`, the claim re-enters development through the same development-opening action described in §3.3, and the loop `REMANDED → DEVELOPMENT → RATED → REMANDED` may repeat until the remand cap is reached. A claim that has been granted or denied and is not being appealed is closed by a claims officer: closing is permitted from `GRANTED` (moving it to `CLOSED`) and from `DENIED` (also moving it to `CLOSED`), and `CLOSED` is terminal. An attempt to close from any other status is rejected with `ERR_INVALID_STATE`. Claims may be fetched individually and listed with an optional filter on `veteran_id` and on `status`; conditions may be fetched individually and listed with optional filters on `veteran_id`, on `claim_id`, and on `service_connection`.

### 3.6. How the Combined Disability Rating Is Computed

The combined rating is the heart of the system, and §2.8 already established its non-linear character. Here is the precise procedure. The input set is the collection of conditions whose `service_connection` is `SERVICE_CONNECTED` and whose `final_rating_pct` is greater than 0; any condition rated 0 is dropped from consideration. The provisional variant, used at rating time, additionally includes the `PROPOSED` conditions of every claim of the veteran currently in `RATED` status — not merely the one claim just rated — contributing each such condition's `proposed_rating_pct` in place of a finalized one, and it writes its result to `provisional_combined_rating_pct` rather than to `combined_rating_pct`. After computing this figure, the system floors it at the veteran's current `combined_rating_pct`, storing whichever is greater, so the provisional figure never reads below the finalized combined rating.

The computation proceeds in steps. First, sort the included ratings in descending order; when two ratings are equal the older condition (earlier `created_at`) is ordered first, a tie-break that does not change the number but pins determinism. Second, walk the sorted ratings accumulating disability against remaining efficiency: begin with a remaining efficiency of 100; for each rating in turn, the disability it contributes equals the remaining efficiency multiplied by that rating expressed as a fraction of one hundred, and the remaining efficiency is then reduced by exactly that contributed amount. After all ratings are consumed, the raw total disability is 100 minus whatever efficiency remains. Third, the bilateral-factor adjustment is applied at this point when it is warranted, before any rounding (see below). Fourth and last, the raw total disability is snapped to the nearest multiple of ten using round-half-up — divide the total by ten, round half upward to a whole number, multiply back by ten — and the result is clamped to the inclusive range 0 to 100. To make the non-linearity concrete: ratings of 50 and 30 yield 100 × 0.5 = 50 disability with 50 efficiency remaining, then 50 × 0.3 = 15 more with 35 remaining, for a raw total of 65, which snaps to 70 — not the 80 a naive sum would produce.

### 3.7. The Bilateral Factor Variant

The bilateral factor recognizes that paired-limb disabilities compound. It applies only when the included service-connected set contains two or more conditions marked `is_extremity` with at least one on the `LEFT` body side and at least one on the `RIGHT` body side. When that condition is not met — when there are not two such extremity conditions on opposite sides — the bilateral step is skipped entirely and the rating is simply combined and then rounded to the nearest ten as in §3.6.

When the bilateral condition is met, the procedure changes between step two and the final rounding. The qualifying bilateral extremity ratings are first combined among themselves using the same efficiency-reduction method; then ten percent of that bilateral subtotal is added to it; and the resulting figure — which may carry a fraction — is treated as a single combined rating that is then folded together with the remaining non-bilateral ratings using the same efficiency-reduction method. For that final fold the bilateral-with-factor figure and the non-bilateral ratings are sorted together in descending order — the fractional bilateral figure taking its place among the integer ratings by magnitude — and the efficiency reduction is walked over that sorted sequence without any per-step rounding. Only after the whole set has been combined this way is the final round-to-nearest-ten applied. The ten-percent bilateral addition is performed before that final rounding, never after.

### 3.8. Monthly Disability Compensation

Monthly compensation is a step function of the combined rating, augmented by dependents — but the dependent augmentation only switches on once the veteran's `combined_rating_pct` reaches thirty. The base amount is read from a fixed schedule keyed by the combined rating: a rating of 0 pays nothing; 10 pays 17,500 cents; 20 pays 34,600 cents; 30 pays 53,600 cents; 40 pays 77,200 cents; 50 pays 109,900 cents; 60 pays 139,500 cents; 70 pays 175,800 cents; 80 pays 204,400 cents; 90 pays 229,600 cents; and 100 pays 383,150 cents.

When the combined rating is strictly below thirty, the monthly compensation is exactly that base amount and no dependent additions are made at all, even if the veteran has active dependents — the boundary sits exactly at thirty, so a rating of twenty ignores dependents while a rating of thirty includes them. When the combined rating is thirty or above, dependent additions are layered on. Only dependents in `ACTIVE` status are counted. The additions are: 10,000 cents if the veteran has exactly one active spouse; 8,000 cents for each active parent, of which there can be up to two; 7,000 cents for each active child who is *not* marked as the in-school eighteen-to-twenty-three category; and 23,000 cents for each active child who *is* so marked. These four amounts are summed into a dependent subtotal, and that subtotal is then scaled by the rating tier — multiplied by the combined rating expressed as a fraction of one hundred — with the scaled result rounded to whole cents using round-half-up. The veteran's `monthly_compensation_cents` is the base amount plus that scaled, rounded dependent subtotal.

### 3.9. Activating, Suspending, and Reactivating the Award

Computing a compensation figure is separate from disbursing it; disbursement is gated by `award_status`. A newly created veteran sits at `DRAFT`. A claims officer activates the monthly award, moving `award_status` from `DRAFT` to `ACTIVE`. Activation is permitted only when the award is in `DRAFT` status, requires the veteran's `combined_rating_pct` to be strictly greater than 0 (otherwise `ERR_NO_COMPENSABLE_RATING`), and requires `expected_veteran_version` to match the veteran's current `version` (otherwise `ERR_STALE_VERSION`, as detailed in §2.6). On activation the award becomes `ACTIVE` — the already-computed `monthly_compensation_cents` reflects the current rating and dependents — and the veteran's `version` is incremented by one.

An active award may be suspended by a claims officer, moving `award_status` from `ACTIVE` to `SUSPENDED`; this is permitted only from `ACTIVE`, pauses disbursement while retaining the computed amount, and takes no version field. A suspended award is reactivated through the same activation action: from `SUSPENDED` the award returns to `ACTIVE`, again requiring `combined_rating_pct` strictly greater than 0 (otherwise `ERR_NO_COMPENSABLE_RATING`) and `expected_veteran_version` to match the current `version` (otherwise `ERR_STALE_VERSION`), and again incrementing the veteran's `version` by one. Activation from any award state other than `DRAFT` or `SUSPENDED` is an invalid transition and is rejected with `ERR_INVALID_STATE`, as is suspension from any state other than `ACTIVE`.

### 3.10. The GI Bill Tier

A veteran's Post-9/11 GI Bill benefit tier, `gi_bill_tier_pct`, is derived purely from service history and is recomputed whenever the veteran is created or has their service-time inputs edited. The tier is a percentage drawn from the set {0, 50, 60, 70, 80, 90, 100}. There is a special-case short-circuit: a veteran who was `discharged_for_service_disability` and served at least thirty active-duty days qualifies for the full 100 percent tier outright, regardless of total days.

Otherwise the tier is a threshold function of `total_active_duty_days`. At least 1,095 days (thirty-six months) earns 100 percent. At least 912 days but fewer than 1,095 earns 90 percent. At least 730 days but fewer than 912 earns 80 percent. At least 547 days but fewer than 730 earns 70 percent. At least 365 days but fewer than 547 earns 60 percent — note that this band drops to sixty, not a single point below seventy. At least 90 days but fewer than 365 earns 50 percent. Fewer than 90 days earns 0 percent, meaning no eligibility. Each threshold is inclusive at its lower bound, so a veteran with exactly 365 days lands at 60 percent.

### 3.11. Enrollments and the Housing Allowance

The GI Bill housing benefit is realized through enrollments at schools. A claims officer creates a `School` by supplying its `name`, the boolean `is_public` (true for a public institution, which carries a different in-state tuition cap from a private one), and the `monthly_housing_rate_cents` — the full-time monthly housing allowance basis for the school's locality, which must be zero or greater. A school participating in the Yellow Ribbon program is additionally created with `yellow_ribbon_participant` set true, a `yellow_ribbon_max_contribution_cents` (the per-student per-year cap the school pledges), and a `yellow_ribbon_slots_total` (the number of Yellow Ribbon student slots offered per academic year); these three default to false, 0, and 0 respectively. The school's `yellow_ribbon_slots_used` is a computed counter that starts at 0 and tracks how many certified enrollments are currently consuming a slot.

A veteran or a school certifying official submits an `Enrollment` by supplying the `veteran_id`, the `school_id`, the `term_start` (inclusive) and `term_end` (exclusive) dates, the `credit_hours` enrolled this term, the `full_time_credit_hours` that count as full time for the term (the denominator for rate of pursuit), and optionally the `tuition_charged_cents` (net tuition after the in-state cap, the basis for Yellow Ribbon matching, treated as 0 when omitted) and the boolean `requests_yellow_ribbon` (defaulting to false). Both `credit_hours` and `full_time_credit_hours` must be strictly greater than 0; a non-positive value is rejected with `ERR_INVALID_REQUEST`. A new enrollment is created in `SUBMITTED` status. At submission the server computes the enrollment's `rate_of_pursuit_pct` and, using the estimated variant of the housing-allowance computation, an `estimated_mha_cents` based on the veteran's GI Bill tier as of submission; the finalized `monthly_housing_allowance_cents` and `yellow_ribbon_match_cents` remain 0 until certification.

The `rate_of_pursuit_pct` is one hundred times the `credit_hours` divided by the `full_time_credit_hours`, taken to a whole percentage with round-half-up. The housing allowance is paid only when the rate of pursuit is strictly greater than fifty percent; at exactly fifty or below, the allowance is zero. When it is greater than fifty, the allowance is computed in two pinned rounding steps: first, a full-time basis is formed by scaling the school's `monthly_housing_rate_cents` by the veteran's `gi_bill_tier_pct` as a fraction of one hundred and rounding that to whole cents with round-half-up; then that basis is scaled by the `rate_of_pursuit_pct` as a fraction of one hundred and again rounded to whole cents with round-half-up. The tier basis is rounded first, the rate-of-pursuit scaling is rounded second, and this order is fixed. The estimated variant computed at submission uses the same arithmetic but draws the tier and pursuit figures as of submission, so the estimate may differ from the finalized figure if the tier changes between submission and certification.

Enrollments may be fetched individually and listed with optional filters on `veteran_id`, on `school_id`, and on `status`; schools may be fetched individually.

### 3.12. Certifying an Enrollment

A school certifying official certifies an enrollment, advancing it from `SUBMITTED` to `CERTIFIED` and turning the estimated benefit into a paid one. Certification carries the densest guard set in the system, and the guards interact, so the order in which they are evaluated matters. As established by the system-wide validation ordering in §2 — authentication first, then permission, then existence of every referenced resource, then request well-formedness — the operation-specific checks then run as follows. The enrollment must be in `SUBMITTED` status, or the request is rejected with `ERR_INVALID_STATE`. The veteran must be GI Bill eligible: the veteran's `gi_bill_tier_pct` must be strictly greater than 0, a cross-entity dependency on the veteran's record, failing otherwise with `ERR_NO_GI_BILL_ELIGIBILITY`. There must be no scheduling collision: no other `CERTIFIED` enrollment for the same veteran may have a term interval that overlaps this one, failing otherwise with `ERR_ENROLLMENT_OVERLAP`. If this enrollment `requests_yellow_ribbon`, the school must be a Yellow Ribbon participant and must still have an open slot — its `yellow_ribbon_slots_used` strictly below its `yellow_ribbon_slots_total` — failing otherwise with `ERR_YELLOW_RIBBON_UNAVAILABLE`. And finally `expected_enrollment_version` must match the enrollment's current `version`, failing otherwise with `ERR_STALE_VERSION` as described in §2.6.

Term overlap is judged on half-open intervals. The term spans from `term_start` inclusive to `term_end` exclusive, so two terms that merely touch — one ending exactly when the next begins — do not overlap and do not collide; an overlap exists only when the intervals genuinely share interior time.

On a successful certification, the enrollment moves to `CERTIFIED` and the following side effects fire. The `rate_of_pursuit_pct` is computed as one hundred times `credit_hours` over `full_time_credit_hours`, round-half-up. The `monthly_housing_allowance_cents` is computed via the finalized housing-allowance variant using the current `gi_bill_tier_pct` and the freshly computed `rate_of_pursuit_pct`. If a Yellow Ribbon slot was granted, the enrollment's `yellow_ribbon_match_cents` is computed via the Yellow Ribbon match calculation and the school's `yellow_ribbon_slots_used` is increased by one. The enrollment's `version` is then incremented by one.

The Yellow Ribbon match itself works as follows. Only a veteran at the full 100 percent GI Bill tier is Yellow Ribbon eligible; if the veteran's `gi_bill_tier_pct` is anything other than 100, the match is 0. Otherwise the uncovered tuition is the enrollment's `tuition_charged_cents` (already the net-of-cap residual). The school's contribution is the smaller of half that uncovered amount and the school's `yellow_ribbon_max_contribution_cents`, rounded to whole cents with round-half-up; the VA matches the school's contribution dollar-for-dollar, so the `yellow_ribbon_match_cents` stored on the enrollment equals that rounded school contribution.

### 3.13. Completing and Cancelling Enrollments

After a term concludes, a school certifying official marks a certified enrollment complete, moving it from `CERTIFIED` to `COMPLETED`, which is terminal and carries no further side effects; this is permitted only from `CERTIFIED`. A veteran may cancel their own enrollment. Cancelling from `SUBMITTED` simply moves it to `CANCELLED` with no compensation effects. Cancelling from `CERTIFIED` is a compensating action: the enrollment moves to `CANCELLED`, its `monthly_housing_allowance_cents` is reset to 0, and — if a Yellow Ribbon slot had been consumed, meaning its `yellow_ribbon_match_cents` is greater than 0 — the school's `yellow_ribbon_slots_used` is decreased by one and the enrollment's `yellow_ribbon_match_cents` is reset to 0, restoring the conserved slot to the school's pool. Cancellation is permitted only from `SUBMITTED` or `CERTIFIED`; from `COMPLETED` or an already-`CANCELLED` enrollment it is rejected with `ERR_INVALID_STATE`. `COMPLETED` and `CANCELLED` are both terminal.

### 3.14. Vocational Rehabilitation Plans

The Chapter 31 vocational-rehabilitation benefit is administered through plans drawn against the veteran's entitlement balance. A claims officer or the veteran proposes a `VocRehabPlan` by supplying the `veteran_id`, the `planned_months` of entitlement requested for the plan (which must be strictly greater than 0), and the `track` — one of `REEMPLOYMENT`, `EMPLOYMENT_THROUGH_LONG_TERM`, or `SELF_EMPLOYMENT`. A new plan is created in `PROPOSED` status.

A claims officer approves a proposed plan, moving it from `PROPOSED` to `APPROVED`. Approval is permitted only from `PROPOSED` (otherwise `ERR_INVALID_STATE`) and is subject to two eligibility checks. First, the veteran must meet the minimum rating for vocational rehabilitation: the veteran's `combined_rating_pct` must be at least twenty, a cross-entity dependency on the veteran, failing otherwise with `ERR_VOC_REHAB_INELIGIBLE`. Second, the plan's `planned_months` must not exceed the veteran's remaining `voc_rehab_entitlement_months`, failing otherwise with `ERR_ENTITLEMENT_EXHAUSTED`. On approval, the requested `planned_months` is debited from the veteran's `voc_rehab_entitlement_months`. An approved plan is later marked complete by a claims officer, moving it from `APPROVED` to `COMPLETED` (terminal). Alternatively, a proposed plan may be rejected by a claims officer, moving it from `PROPOSED` to `REJECTED` (terminal); rejection is permitted only from `PROPOSED`. Plans may be fetched individually and listed with optional filters on `veteran_id` and on `status`.

### 3.15. The Ordering of Validation Checks

Across every endpoint the system evaluates guards in a fixed precedence so that the failure a client sees is deterministic. Authentication comes first: a missing or undeclared `X-User-Role` or missing `X-User-ID` yields `ERR_UNAUTHENTICATED` before anything else is considered. Permission comes second: a role not authorized for the operation — including a `Veteran` acting on a record whose `veteran_id` is not their own `X-User-ID` — yields `ERR_FORBIDDEN`. Existence comes third: every resource named in the path or body is resolved left to right, and the first missing one yields `ERR_NOT_FOUND`. Request well-formedness comes fourth: missing or mistyped body fields, enum values outside their declared sets, a `proposed_rating_pct` that is not a multiple of ten within 0 to 100, or non-positive credit hours all yield `ERR_INVALID_REQUEST`. The uniqueness of a veteran's `file_number` on creation is checked next, yielding `ERR_DUPLICATE_FILE_NUMBER`. Only then is the target resource's state checked for the requested transition, yielding `ERR_INVALID_STATE` when it is wrong. The optimistic-concurrency version check follows, yielding `ERR_STALE_VERSION` on a mismatch. The remaining business guards — no-conditions, unrated-condition, appeal-exhausted, GI-Bill-eligibility, term-overlap, Yellow-Ribbon-availability, voc-rehab-ineligibility, entitlement-exhaustion, and no-compensable-rating — are then evaluated within the operations that own them. This precedence means, for example, that an unauthenticated request to grant a stale claim reports the authentication failure, not the stale-version failure; and that a certification request against a non-existent enrollment reports not-found before any state or version concern.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a veteran, a dependent, a claim, a condition, a school, an enrollment, or a vocational-rehabilitation plan — return a `201 Created` status code. Every other operation, including all state transitions, field updates, and the activation, suspension, grant, deny, remand, close, certify, complete, cancel, approve, and reject actions, returns a `200 OK` status code. Reads return `200 OK`. The request body, response body, and side effects of each endpoint are specified in the §3 narratives above; the table below carries only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/veterans` | Create a veteran (award starts in DRAFT) | ClaimsAdmin |
| GET | `/veterans/{veteranId}` | Get a veteran, including computed fields | ClaimsAdmin, RatingSpecialist, Veteran |
| GET | `/veterans` | List veterans (optional file_number filter) | ClaimsAdmin, RatingSpecialist |
| PATCH | `/veterans/{veteranId}` | Update service-time fields; recomputes GI Bill tier | ClaimsAdmin |
| POST | `/veterans/{veteranId}/activate-award` | Activate or reactivate the monthly award | ClaimsAdmin |
| POST | `/veterans/{veteranId}/suspend-award` | Suspend the monthly award | ClaimsAdmin |
| GET | `/veterans/{veteranId}/compensation-summary` | Computed compensation and tier summary | ClaimsAdmin, RatingSpecialist, Veteran |
| POST | `/veterans/{veteranId}/dependents` | Add a dependent; recomputes compensation | ClaimsAdmin, Veteran |
| GET | `/veterans/{veteranId}/dependents` | List a veteran's dependents | ClaimsAdmin, RatingSpecialist, Veteran |
| GET | `/dependents/{dependentId}` | Get a dependent | ClaimsAdmin, RatingSpecialist, Veteran |
| GET | `/dependents` | List dependents (filter by veteran_id) | ClaimsAdmin, RatingSpecialist, Veteran |
| POST | `/veterans/{veteranId}/dependents/{dependentId}/remove` | Remove a dependent; recomputes compensation | ClaimsAdmin, Veteran |
| POST | `/claims` | Create a claim (status SUBMITTED) | ClaimsAdmin, Veteran |
| GET | `/claims/{claimId}` | Get a claim | ClaimsAdmin, RatingSpecialist, Veteran |
| GET | `/claims` | List claims (filter by veteran_id) | ClaimsAdmin, RatingSpecialist, Veteran |
| POST | `/claims/{claimId}/open-development` | Move a claim into DEVELOPMENT (also from REMANDED) | ClaimsAdmin |
| POST | `/claims/{claimId}/rate` | Rate a claim; refresh provisional rating | RatingSpecialist |
| POST | `/claims/{claimId}/grant` | Grant a claim; cascade rating and compensation | ClaimsAdmin |
| POST | `/claims/{claimId}/deny` | Deny a claim | ClaimsAdmin |
| POST | `/claims/{claimId}/remand` | Remand a claim for re-adjudication | ClaimsAdmin |
| POST | `/claims/{claimId}/close` | Close a granted or denied claim | ClaimsAdmin |
| POST | `/claims/{claimId}/conditions` | Add a condition to a claim | ClaimsAdmin, RatingSpecialist |
| GET | `/conditions` | List conditions (filter by veteran_id or claim_id) | ClaimsAdmin, RatingSpecialist, Veteran |
| GET | `/conditions/{conditionId}` | Get a condition | ClaimsAdmin, RatingSpecialist, Veteran |
| PATCH | `/conditions/{conditionId}` | Update a condition's proposed rating or body-side fields | RatingSpecialist |
| POST | `/schools` | Create a school | ClaimsAdmin |
| GET | `/schools/{schoolId}` | Get a school | ClaimsAdmin, RatingSpecialist, Veteran, SchoolCertifyingOfficial |
| POST | `/enrollments` | Submit an enrollment (estimated MHA computed) | Veteran, SchoolCertifyingOfficial |
| GET | `/enrollments/{enrollmentId}` | Get an enrollment | ClaimsAdmin, Veteran, SchoolCertifyingOfficial |
| GET | `/enrollments` | List enrollments (filter by veteran_id or school_id) | ClaimsAdmin, RatingSpecialist, Veteran, SchoolCertifyingOfficial |
| POST | `/enrollments/{enrollmentId}/certify` | Certify an enrollment; finalize MHA and Yellow Ribbon | SchoolCertifyingOfficial |
| POST | `/enrollments/{enrollmentId}/complete` | Mark an enrollment completed | SchoolCertifyingOfficial |
| POST | `/enrollments/{enrollmentId}/cancel` | Cancel an enrollment; zero MHA, restore slot | Veteran |
| POST | `/voc-rehab-plans` | Propose a Chapter 31 voc-rehab plan | ClaimsAdmin, Veteran |
| GET | `/voc-rehab-plans/{planId}` | Get a voc-rehab plan | ClaimsAdmin, Veteran |
| GET | `/voc-rehab-plans` | List voc-rehab plans (filter by veteran_id) | ClaimsAdmin, Veteran |
| POST | `/voc-rehab-plans/{planId}/approve` | Approve a plan; debit entitlement months | ClaimsAdmin |
| POST | `/voc-rehab-plans/{planId}/complete` | Complete an approved plan | ClaimsAdmin |
| POST | `/voc-rehab-plans/{planId}/reject` | Reject a proposed plan | ClaimsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_FILE_NUMBER` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CLAIM_HAS_NO_CONDITIONS` | 409 |
| `ERR_CONDITION_UNRATED` | 409 |
| `ERR_APPEAL_EXHAUSTED` | 409 |
| `ERR_NO_GI_BILL_ELIGIBILITY` | 409 |
| `ERR_ENROLLMENT_OVERLAP` | 409 |
| `ERR_YELLOW_RIBBON_UNAVAILABLE` | 409 |
| `ERR_VOC_REHAB_INELIGIBLE` | 409 |
| `ERR_ENTITLEMENT_EXHAUSTED` | 409 |
| `ERR_NO_COMPENSABLE_RATING` | 409 |

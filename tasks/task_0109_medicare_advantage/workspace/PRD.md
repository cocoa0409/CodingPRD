# Medicare Advantage Enrollment API — Product Requirements Document

## 1. Introduction

Medicare is a federal health-coverage program whose membership lifecycle is governed by a small set of strict temporal windows (Initial Enrollment Period, Annual Enrollment Period, Special Enrollment Periods), several distinct coverage tracks (Parts A, B, C, D, and the supplemental Medigap product), and a body of long-standing CMS rules — late-enrollment penalties, Medigap guaranteed-issue protections, and the four-phase Part D "donut hole" drug-benefit calculation. Counselors and plan administrators today reconcile these rules by hand, which is both expensive and error-prone: a beneficiary who misses their seven-month IEP by a day can be assessed a permanent 1%-per-month Part D penalty for the remainder of their life, yet the existing systems rarely surface that math to the people making the decision in real time.

This document specifies the Medicare Advantage Enrollment API, an authoritative back-end service that mints the relevant temporal windows on beneficiary intake, validates each enrollment against the open period that justifies it, computes coverage-phase cost-sharing on every drug claim, and crystallises the late-enrollment penalty and Medigap premium-lock at activation. The system is designed for two operator personas (administrators and counselors) backed by a read-only auditor persona and a self-service beneficiary persona, with a deliberate segregation of duties between counselors who submit claims and administrators who adjudicate them. All behaviour is driven through a test-controllable logical clock so that month-boundary, year-boundary, and IEP-closure transitions can be reproduced deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID` (an opaque per-request identifier) and `X-User-Role` (one of the four enumerated roles). A request missing either header is rejected with `ERR_AUTH_MISSING` and HTTP 401. A request whose role does not match one of the four enumerated values is rejected with `ERR_AUTH_INVALID_ROLE` and HTTP 401. A request whose role is recognised but lacks permission for the targeted endpoint is rejected with `ERR_FORBIDDEN` and HTTP 403.

The four roles are exactly:

- **`PlanAdmin`** — Plan administrators. They create plans and beneficiaries, publish star-rating snapshots, open non-IEP enrollment periods, reject pending enrollments, evaluate and finalise Medigap policies, adjudicate and reverse drug claims, advance the logical clock, and mark beneficiaries deceased.
- **`BenefitsCounselor`** — Counselors who interact directly with beneficiaries. They create, activate, terminate, and transfer enrollments, submit Medigap applications and drug claims, and cancel or revise Medigap policies. By the segregation-of-duties rule below, a counselor who submitted a drug claim cannot also adjudicate it.
- **`Beneficiary`** — End-users with read-only access scoped to their own resources.
- **`Auditor`** — Read-only oversight; sees all beneficiaries' data but cannot mutate any resource.

When `X-User-Role` is `PlanAdmin`, `BenefitsCounselor`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may compare two `X-User-ID` values for equality (this is how segregation-of-duties on adjudication is enforced — see §3) but never compares it to any entity's `id`. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`; ownership checks on any resource that references a `Beneficiary` compare the resource's `beneficiary_id` to `X-User-ID`, and any read of a resource whose `beneficiary_id` differs from `X-User-ID` is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two pagination query parameters. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; values outside this band are rejected with `ERR_VALIDATION`. `offset` defaults to 0 and may be any non-negative integer. Results are returned in ascending `created_at` order — i.e., oldest first — and the response `meta` carries `limit`, `offset`, `total_count`, and `has_more` so that clients can detect the end of a page sequence without an extra call.

### 2.4. Common Resource Properties

Every persisted resource — `Beneficiary`, `Plan`, `EnrollmentPeriod`, `Enrollment`, `MedigapPolicy`, `DrugPhaseLedger` — carries four system-managed fields. `id` is a server-minted UUID with no type prefix; `created_at` is an ISO 8601 UTC timestamp with three fractional digits that records when the resource was first written; `updated_at` is the same format and is refreshed on every mutation; `version` is an integer that starts at 1 and increments by exactly one on each mutation. Two resource families are deliberately leaner: `LateEnrollmentPenalty` and `DrugClaim` carry only `id` and `created_at` — they have no `updated_at` and no `version`, because they are append/finalise records whose mutability is constrained by other invariants (penalty rows are snapshots, claim rows transition through a state machine that records its own timestamps such as `adjudicated_at`). The `StarRatingSnapshot` is likewise lean: only `id` and `created_at` accompany its measurement fields.

### 2.5. Path Hierarchy and Nested Resolution

Several endpoints embed a parent identifier into the URL — for example, the period list under `/beneficiaries/{beneficiary_id}/enrollment-periods` or the ledger under `/beneficiaries/{beneficiary_id}/drug-phase-ledger`. Path parameters are resolved strictly left-to-right: the system first verifies that the leftmost id (typically a `Beneficiary`) resolves to a stored row, and only then verifies the nested id. A failure at any step yields `ERR_NOT_FOUND` with HTTP 404. Foreign-key references carried in the request body — `plan_id`, `enrollment_period_id`, `enrollment_id` — are resolved with the same semantics but yield `ERR_FK_NOT_FOUND` (also HTTP 404) so that callers can distinguish "the URL is bad" from "the URL is fine but the payload references a missing row".

### 2.6. Precision, Rounding, and Cents-Native Money

All monetary fields are integer cents — there are no floating-point dollar amounts anywhere in the contract. Whenever the system must derive a cents value from a multiplication (penalty calculation, donut-hole share calculation, Medigap underwriting uplift), it applies the **round-half-up** rule to obtain an integer-cents result. Decimal rates such as `penalty_rate_decimal` and `underwriting_uplift_decimal` may carry up to six decimal places of precision in their stored form, but only the final cents output is exposed in monetary form. For the star-rating composite (described in §3), the raw composite is preserved to four decimal places before being mapped to a half-star band.

### 2.7. Optimistic Concurrency Control

Any mutating endpoint that accepts `version` in its body uses optimistic concurrency: when the client supplies a `version` value, the server compares it to the stored `version` of the target row; a mismatch is rejected with `ERR_VERSION_CONFLICT` and HTTP 409, and no write occurs. Omitting `version` from the body skips the check entirely. A successful mutation increments the row's `version` by one and refreshes `updated_at` to the current server time. Because `LateEnrollmentPenalty` and `DrugClaim` rows do not carry a `version` field, mutations against them (claim adjudication, claim reversal) instead serialise on a separate column on the parent `DrugPhaseLedger` row — see §3.

### 2.8. Validation Priority Order

When a request fails multiple checks, the system evaluates them in a strict priority sequence and surfaces only the first violation. The order is: authentication header presence (`ERR_AUTH_MISSING`), role enumeration (`ERR_AUTH_INVALID_ROLE`), RBAC for the endpoint (`ERR_FORBIDDEN`), path-parameter existence (`ERR_NOT_FOUND`), body foreign-key existence on the create endpoints for enrollments, drug claims, and Medigap policies (`ERR_FK_NOT_FOUND`), beneficiary-not-deceased (`ERR_BENEFICIARY_DECEASED`), valid source state for the transition (`ERR_INVALID_STATE`), plan-active at enrollment creation (`ERR_PLAN_INACTIVE`), drug claim references a Part D enrollment (`ERR_NON_PART_D_CLAIM`), referenced period is open at request time (`ERR_PERIOD_NOT_OPEN`), effective-date inside the period window (`ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD`), fill-date inside coverage (`ERR_FILL_DATE_OUT_OF_COVERAGE`), no overlapping ACTIVE enrollment for the same Part (`ERR_DUPLICATE_PART_ENROLLMENT`), Medigap state-residency match (`ERR_MEDIGAP_STATE_MISMATCH`), ledger reverse invariant (`ERR_LEDGER_INVARIANT_BREACH`), Part C transfer window correctness (`ERR_TRANSFER_WINDOW_INVALID`), premium positive at activation for non-Part-A (`ERR_INVALID_PREMIUM`), segregation of duties on drug-claim adjudication (`ERR_SEGREGATION_OF_DUTIES`), optimistic concurrency (`ERR_VERSION_CONFLICT`), and finally generic body-schema validation (`ERR_VALIDATION`). This order matters: a deceased beneficiary whose request also has an inactive plan will receive `ERR_BENEFICIARY_DECEASED`, not `ERR_PLAN_INACTIVE`.

### 2.9. Cascade Semantics and the Logical Clock

Several actions trigger multi-hop side effects (enrollment activation may create a `LateEnrollmentPenalty`, which itself feeds into the cost summary; drug-claim adjudication mutates the parent `DrugPhaseLedger`, which can in turn promote the ledger's `current_phase`; marking a beneficiary deceased cascades to all of their active enrollments, applied/underwriting/issued Medigap policies, and submitted drug claims). In every such cascade, each row affected by a write has its `updated_at` refreshed to the same server timestamp and (if it carries `version`) its `version` incremented by one. The server uses a test-controllable logical clock; operators with the `PlanAdmin` or `Auditor` role can advance this clock, and doing so triggers automatic period transitions (SCHEDULED to OPEN, OPEN to CLOSED) and beneficiary lifecycle auto-transitions (PRE_ELIGIBLE to IEP_OPEN, IEP_OPEN to IEP_CLOSED). Read-only operators (the `Beneficiary` role and the `Auditor` role for the clock-read) may inspect the current clock value.

### 2.10. Compensating-Invariant Ledger

The `DrugPhaseLedger` aggregates four cumulative counters across all adjudicated Part D claims of a beneficiary within a `plan_year`: `deductible_paid_cents`, `total_drug_spend_cents`, `troop_cents`, and a derived `current_phase`. Two rules guarantee that these counters can be perturbed only in a way that remains reconstructable from the underlying claim history: (a) when a claim is reversed, the four counters must be decreased by exactly that claim's contribution and `current_phase` recomputed from the updated counters; (b) at all times, the four counters must equal the chronological sum (oldest `fill_date` first; ties broken by `DrugClaim.id` ascending) of the contributions of every claim in `ADJUDICATED` status — if this invariant would break, the reverse is rejected with `ERR_LEDGER_INVARIANT_BREACH`. Additionally, two adjudications racing on the same ledger are serialised by comparing `DrugPhaseLedger.version`; the loser receives `ERR_LEDGER_VERSION_STALE`. A reverse that would jump over a more recently adjudicated claim is rejected with `ERR_REVERSE_BLOCKED_BY_LATER_CLAIM`, with the loser determined by comparison against `DrugPhaseLedger.last_adjudicated_claim_id`.

## 3. Business Logic & Workflows

### 3.1. Beneficiary intake and the seven-month IEP

A `PlanAdmin` brings a new individual into the system by submitting `full_name`, `date_of_birth`, `medicare_id`, `state_code`, and the eligibility-pathway flags `has_esrd`, `has_disability`, and (when disability applies) `ssdi_start_date`. The `medicare_id` is an externally issued Medicare Beneficiary Identifier, exactly eleven uppercase-alphanumeric characters, and must be unique across all beneficiaries; the `state_code` is the two-letter USPS abbreviation, used later for Medigap residency matching. On intake the server derives three temporal fields that anchor every subsequent eligibility check.

The first derived field is `medicare_eligibility_date`, computed by the following rule. If `has_esrd` is true, the beneficiary is treated as immediately eligible from the first day of the month of their `date_of_birth`. Otherwise, if `has_disability` is true and `ssdi_start_date` is set, eligibility begins on the first day of the month that contains `ssdi_start_date` plus twenty-four months. Otherwise (the standard age-65 pathway), eligibility begins on the first day of the month that contains `date_of_birth` plus sixty-five years. The second and third derived fields delimit the Initial Enrollment Period: `iep_start_date` is the first day of the month that falls three months before `medicare_eligibility_date`, and `iep_end_date` is the last second of the month that falls three months after `medicare_eligibility_date` — i.e., 23:59:59 UTC on the final day of that month, inclusive. The IEP is thus a seven-month window straddling the eligibility month.

Intake also creates a companion `EnrollmentPeriod` row of `period_type` `IEP` whose `window_start` and `window_end` are precisely `iep_start_date` and `iep_end_date`. This period begins in `SCHEDULED` status. The beneficiary themselves begins in `lifecycle_status` `PRE_ELIGIBLE`, and `deceased_at` is unset.

### 3.2. Period activation by the logical clock

The lifecycle of every enrollment period is driven by the test clock. An admin-only or auditor-readable test-driving capability advances the clock to a supplied `to` instant. For each period attached to each beneficiary, the system recomputes status: a period whose `window_start` is in the future is `SCHEDULED`; a period whose window straddles the new clock value (window_start ≤ now ≤ window_end) is `OPEN`; a period whose `window_end` has passed and which was never consumed becomes `CLOSED`. The same advance triggers beneficiary lifecycle re-evaluation: a beneficiary in `PRE_ELIGIBLE` whose new clock value falls within their IEP window transitions to `IEP_OPEN` (and the corresponding `EnrollmentPeriod` SCHEDULED moves to OPEN). A beneficiary in `IEP_OPEN` whose IEP has now ended without any `ACTIVE` Part A or Part B enrollment transitions to `IEP_CLOSED` (and the IEP period moves from OPEN to CLOSED). When `IEP_OPEN` advances to `IEP_CLOSED`, the system also schedules an SEP loss-of-coverage candidacy review for the next AEP. The advance returns the list of transitions actually applied, each carrying the entity type, entity id, and the from/to states; this output is the canonical mechanism for tests to confirm cascade fanout.

A second administrative capability lets the admin open a non-IEP period (`AEP`, `GEP`, `SEP_MOVE`, `SEP_LOSS_OF_COVERAGE`, or `MEDIGAP_GI`) on behalf of a beneficiary by supplying `period_type`, `window_start`, and `window_end`. The new period starts `SCHEDULED` if the current clock is before `window_start`, otherwise `OPEN` if the clock is inside the window.

### 3.3. Plan catalogue and star ratings

Plans are catalogue rows independent of beneficiaries. A `PlanAdmin` creates a plan with `plan_code` (1 to 40 characters, unique), `plan_type` (one of `PART_A`, `PART_B`, `PART_C`, `PART_D`, `MEDIGAP`), `plan_year` (a four-digit year between 2020 and 2030 inclusive), and `monthly_premium_cents`. For Part D plans the admin must also supply `annual_deductible_cents`, `initial_coverage_limit_cents`, and `catastrophic_threshold_cents` — for any other plan type these three default to zero. Medigap plans additionally carry a `state_code` (the residency state the Medigap product is sold in); for non-Medigap plans `state_code` is null. Every plan also has a `star_rating`, in half-star increments from 1.0 to 5.0 inclusive, and an `is_active` flag (default true) that gates new enrollments.

The star rating itself is derived from `StarRatingSnapshot` rows that the admin publishes against a plan. Each snapshot carries a `measurement_year` between 2020 and 2030 inclusive, plus three raw 0-to-100 sub-scores: `clinical_quality_score`, `member_experience_score`, and `customer_service_score`. The server computes a weighted composite as fifty percent of the clinical-quality score plus thirty percent of the member-experience score plus twenty percent of the customer-service score (the three weights sum to one). The raw composite is preserved to four decimal places. It is then banded into a half-star `weighted_star_rating` using strictly-greater-than-or-equal thresholds: a composite of 90 or higher maps to 5.0; from 80 up to but excluding 90 maps to 4.5; from 70 up to but excluding 80 maps to 4.0; from 60 up to but excluding 70 maps to 3.5; from 50 up to but excluding 60 maps to 3.0; from 40 up to but excluding 50 maps to 2.5; from 30 up to but excluding 40 maps to 2.0; from 20 up to but excluding 30 maps to 1.5; and anything below 20 maps to 1.0. A composite exactly equal to 90.0000 is therefore 5.0, not 4.5. On insertion of the snapshot, the system stamps `published_at` to the current clock; if and only if this snapshot's `measurement_year` equals the maximum `measurement_year` among all snapshots for the same `plan_id`, the parent `Plan.star_rating` is overwritten with the new `weighted_star_rating`.

Plans can be listed by `plan_type`, `plan_year`, `state_code`, and `min_star_rating` (lower-bound filter on `star_rating`), with the usual `limit` and `offset` pagination.

### 3.4. Creating an enrollment and binding it to a period

A `BenefitsCounselor` creates an enrollment in `PENDING` status by submitting `beneficiary_id`, `plan_id`, `enrollment_period_id`, and the proposed `effective_date`. The system fixes `part_covered` by mirroring the plan's `plan_type` at this moment of creation (so a Part C plan yields a Part C enrollment, etc.; Medigap is handled by a separate workflow described in §3.7). `months_late` and `termination_date` start at their defaults — zero and null respectively — and the row is allocated a `created_at`, `updated_at`, `version` 1, and the standard `id`.

Activation is a separate transition: a counselor calls the activation capability on the pending enrollment, which advances `status` from `PENDING` to `ACTIVE`. Activation enforces the following stack of guards before any side effect runs. The owning `Beneficiary` must not be deceased — a deceased beneficiary's activation is rejected with `ERR_BENEFICIARY_DECEASED`. The plan must be active (`Plan.is_active` true) or the request is rejected with `ERR_PLAN_INACTIVE`. The `plan_year` of the referenced plan must equal the calendar year of `effective_date`. The referenced `EnrollmentPeriod` must be in `OPEN` status — a period that is `SCHEDULED`, `CLOSED`, or already `CONSUMED` produces `ERR_PERIOD_NOT_OPEN`. The `effective_date` must fall on or after `window_start` and on or before `window_end`; an out-of-window effective date is rejected with `ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD`. There must be no overlapping `ACTIVE` enrollment for the same beneficiary on the same `part_covered` — if there is, the system returns `ERR_DUPLICATE_PART_ENROLLMENT`. And, for any non-Part-A enrollment, the plan's `monthly_premium_cents` must be strictly greater than zero, or the request fails with `ERR_INVALID_PREMIUM`. A `version` may be supplied to gate the activation under optimistic concurrency.

Once these guards pass, several side effects run as a unit. The server computes `months_late` at activation time (see §3.5). If the referenced period is of `period_type` `IEP` or `MEDIGAP_GI`, its `status` flips to `CONSUMED` and its `consumed_by_enrollment_id` is set to this enrollment's `id`; periods of types `AEP`, `GEP`, `SEP_MOVE`, and `SEP_LOSS_OF_COVERAGE` are not consumed, so the same AEP period can justify multiple enrollments across different parts. The `Beneficiary.lifecycle_status` bubbles to `ENROLLED` (from any of `IEP_OPEN`, `IEP_CLOSED`, or `COVERAGE_GAP`). And if `part_covered` is `PART_D`, a fresh `DrugPhaseLedger` row is created with `current_phase` `DEDUCTIBLE`, all four counters at zero, and `last_adjudicated_claim_id` null. A `PlanAdmin` can short-circuit a pending enrollment with the rejection capability, which moves the enrollment from `PENDING` to the terminal `REJECTED` state; rejection leaves the referenced period in its original status (no `CONSUMED` transition).

The first `PENDING → ACTIVE` activation during an open IEP window is the transition that the beneficiary lifecycle treats specially: the activation must satisfy `effective_date ≤ iep_end_date` plus one calendar month, and it carries the beneficiary from `IEP_OPEN` to `ENROLLED` while consuming the IEP period. An activation that takes place under an `AEP`, `GEP`, or qualifying `SEP` carries the beneficiary from `IEP_CLOSED` to `ENROLLED` (or `COVERAGE_GAP` to `ENROLLED`), and if `part_covered` is `PART_B` or `PART_D` with `months_late > 0`, a `LateEnrollmentPenalty` is created in the same atomic step — the activation cascade hops from enrollment activation to penalty creation to a recompute of the enrollment's premium snapshot, a depth-2 cascade that is exercised as a unit.

### 3.5. The late-enrollment penalty (dual-variant by Part)

When activation produces `months_late > 0` on a Part B or Part D enrollment, the system inserts a `LateEnrollmentPenalty` row. The row carries the owning `beneficiary_id`, the triggering `enrollment_id`, the `part` (either `PART_B` or `PART_D`), the snapshotted `months_late`, the computed `penalty_rate_decimal`, the resulting `monthly_penalty_cents`, and `snapshot_base_premium_cents` — the plan's `monthly_premium_cents` frozen at the moment of penalty creation. The penalty row is a snapshot: subsequent changes to the plan's monthly premium do not retroactively rewrite the penalty.

The computation of `months_late` depends on the part. For Part B, it is the count of whole months between `medicare_eligibility_date` and `effective_date` minus seven (the seven-month IEP grace), floored at zero. For Part D, it is the count of months during which the beneficiary lacked creditable Part D coverage between eligibility and activation; this is also floored at zero. The penalty formula then diverges sharply.

For Part B, the penalty rate is ten percent of a national-average Part B premium constant, applied once for every full twelve-month block by which the beneficiary was late. Specifically, full-years is `months_late` integer-divided by twelve (so eleven months produces zero full years, twelve produces one, twenty-three produces one, twenty-four produces two), and `penalty_rate_decimal` is full-years multiplied by 0.10. The `monthly_penalty_cents` is then the national-average Part B premium (a fixed constant equal to seventeen thousand four hundred ninety cents, i.e. $174.90) multiplied by `penalty_rate_decimal`, with the product rounded half up to integer cents.

For Part D, the penalty is per-uncovered-month, with no flooring to year. The `penalty_rate_decimal` is `months_late` multiplied by 0.01 (so eleven months produces 0.11, twelve produces 0.12, thirteen produces 0.13). The `monthly_penalty_cents` is the national-average Part D base-beneficiary-premium constant (three thousand six hundred seventy-eight cents, i.e. $36.78) multiplied by `penalty_rate_decimal`, with the product rounded half up to integer cents. Because the per-month rate (Part D) and the per-year-block rate (Part B) attach to different bases, a single beneficiary with the same `months_late` will see materially different penalties for Part B versus Part D.

### 3.6. Cost summary (provisional vs final)

A read-only cost-summary capability returns, for a given enrollment, the trio `effective_premium_cents`, `base_premium_cents`, and `lep_cents`, plus a `variant` label indicating which branch produced the values. The two branches differ in what they treat as authoritative.

The **provisional** variant is used when `Enrollment.status` is `PENDING`. It uses the plan's `monthly_premium_cents` at query time (the live value, which can move) as `base_premium_cents`, and it projects what the late-enrollment penalty *would* be if the enrollment were activated *today*. The projection re-runs the Part-specific penalty calculation against the current `effective_date`. The returned `effective_premium_cents` is the live base plus the projected `lep_cents`.

The **final** variant is used when `Enrollment.status` is `ACTIVE`. It uses the `snapshot_base_premium_cents` frozen on the associated `LateEnrollmentPenalty` row as `base_premium_cents`, and the stored `monthly_penalty_cents` as `lep_cents` (zero if no penalty row exists). A subsequent change to the plan's `monthly_premium_cents` does not move the final variant — so identical inputs at PENDING versus ACTIVE produce different `effective_premium_cents`, by design. The returned `effective_premium_cents` is `base_premium_cents` plus `lep_cents`. For both variants, all three numeric components are integer cents.

### 3.7. Medigap: guaranteed issue and underwriting

Medigap policies follow their own state machine, distinct from the Part-A/B/C/D enrollment flow. A `BenefitsCounselor` opens a policy in `APPLIED` status by supplying `beneficiary_id`, the `plan_id` of a `MEDIGAP` plan, and an optional `underwriting_uplift_decimal` (which defaults to zero and is ignored on the guaranteed-issue branch). The server stamps `applied_at` to the current clock.

A `PlanAdmin` then attempts to convert the application to `GUARANTEED_ISSUED` via the GI-evaluation capability. The conversion succeeds only when an `EnrollmentPeriod` with `period_type` `MEDIGAP_GI` and `status` `OPEN` exists for the beneficiary at `applied_at`, when the plan's `state_code` equals the beneficiary's `state_code` (otherwise `ERR_MEDIGAP_STATE_MISMATCH`), and when the plan is of type `MEDIGAP`. On success the policy moves `APPLIED → GUARANTEED_ISSUED`, the `gi_window_id` is set to that period's `id`, the period transitions from `OPEN` to `CONSUMED`, and `premium_locked_cents` is fixed at the plan's `monthly_premium_cents` — no underwriting uplift is applied. If instead no MEDIGAP_GI period covers `applied_at`, the admin uses the begin-underwriting capability to move the policy `APPLIED → UNDERWRITING`. Two parallel attempts (one evaluating GI, one beginning underwriting) on the same applied policy serialise on `MedigapPolicy.status`; the loser receives `ERR_INVALID_STATE`.

While a policy is `UNDERWRITING`, the beneficiary may amend the application via the revise capability, which carries the state back from `UNDERWRITING` to `APPLIED`, resets `underwriting_uplift_decimal` to zero, and refreshes `applied_at` to the current clock. Finalisation runs via the issue capability. From `GUARANTEED_ISSUED`, issuance requires `premium_locked_cents > 0`, advances to `ISSUED`, and stamps `issued_at` to the current clock. From `UNDERWRITING`, issuance requires `underwriting_uplift_decimal ≥ 0`, computes `premium_locked_cents` as the plan's `monthly_premium_cents` multiplied by one plus `underwriting_uplift_decimal`, rounded half up to integer cents, advances to `ISSUED`, and stamps `issued_at`. From `UNDERWRITING` the admin may also deny the application, moving the state to `DENIED`. Finally, the counselor may cancel the policy from `APPLIED`, `UNDERWRITING`, or `ISSUED`, terminating it in `CANCELLED`.

### 3.8. Drug claims and the four-phase donut hole

A drug claim is submitted by a `BenefitsCounselor` against a `PART_D` enrollment by supplying `beneficiary_id`, `enrollment_id`, `ndc_code` (the National Drug Code), `tier` (one of `TIER_1`, `TIER_2`, `TIER_3`, `TIER_4`, `TIER_5`), `fill_date`, and `gross_cost_cents` (which must be at least one cent). The claim begins in `SUBMITTED` status. If the referenced enrollment is not Part D, the submission is rejected with `ERR_NON_PART_D_CLAIM`. If `fill_date` is earlier than `Enrollment.effective_date` or later than the coalesce of `Enrollment.termination_date` and the last day of the plan's `plan_year`, the submission is rejected with `ERR_FILL_DATE_OUT_OF_COVERAGE`.

Adjudication runs as a `PlanAdmin`-only transition that moves a claim from `SUBMITTED` to `ADJUDICATED`. The admin who performs adjudication cannot be the same operator who submitted the claim — if `X-User-ID` of the adjudication call equals the `X-User-ID` recorded at submission, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Adjudication runs the donut-hole phase walk against a snapshot of the `DrugPhaseLedger` taken *before* this claim, then writes back the claim's `phase_at_adjudication`, `beneficiary_cost_cents`, `plan_cost_cents`, and `adjudicated_at`, and updates the ledger's four counters and `current_phase`, plus stamps the ledger's `last_adjudicated_claim_id` with this claim's `id`. The cascade is depth-3: claim adjudication writes the claim row, then writes the ledger counters and `current_phase`, then triggers a re-evaluation of the beneficiary lifecycle if the catastrophic threshold is crossed (this last hop is logged but does not change the beneficiary's `lifecycle_status` enum).

The donut-hole walk processes the claim's `gross_cost_cents` left-to-right across up to four coverage phases. The plan provides three thresholds: `D` is `annual_deductible_cents`, `I` is `initial_coverage_limit_cents` (the cumulative drug-spend threshold at which Initial Coverage ends and the Coverage Gap begins), and `C` is `catastrophic_threshold_cents` (the cumulative beneficiary-out-of-pocket — TrOOP — threshold at which the Catastrophic phase begins). The ledger contributes three pre-claim counters: `ded_paid` is `deductible_paid_cents`, `spend` is `total_drug_spend_cents`, and `troop` is `troop_cents`. Let `g` denote the remaining gross cost of the claim, starting at `gross_cost_cents`.

**Phase 1, Deductible (`DEDUCTIBLE`).** The amount covered in this phase is the smaller of `g` and the larger of zero and (`D` minus `ded_paid`). In this phase, the entire covered amount is charged to the beneficiary — there is no rounding in the deductible phase because the beneficiary pays one hundred percent. The covered amount is added to the beneficiary's accumulated share, to `ded_paid`, to `spend`, and to `troop`; it is subtracted from `g`. (When `D` is zero, this phase contributes zero.)

**Phase 2, Initial Coverage (`INITIAL_COVERAGE`).** The amount covered in this phase is the smaller of the remaining `g` and the larger of zero and (`I` minus `spend`). The beneficiary's share of the covered amount equals the covered amount multiplied by the tier-specific initial-coverage copay rate, rounded half up to integer cents. The five copay rates are 5% for `TIER_1`, 15% for `TIER_2`, 25% for `TIER_3`, 40% for `TIER_4`, and 50% for `TIER_5`. The plan's share is the covered amount minus the beneficiary's share (no second rounding — subtraction yields exact cents). The beneficiary's share is added to the beneficiary accumulator and to `troop`; the plan's share is added to the plan accumulator; the full covered amount is added to `spend`; the covered amount is subtracted from `g`. (When `I` is zero or `spend` already meets `I`, this phase contributes zero.)

**Phase 3, Coverage Gap (`COVERAGE_GAP`, the "donut hole").** The amount covered in this phase is the smaller of the remaining `g` and whatever spend remains before the catastrophic threshold is crossed in TrOOP terms. The beneficiary's share equals the covered amount multiplied by 0.25 (the gap rate — the beneficiary pays twenty-five percent in the gap), rounded half up to integer cents. The plan's share is the covered amount minus the beneficiary's share. The beneficiary's share is added to the beneficiary accumulator and to `troop`; the plan's share is added to the plan accumulator; the full covered amount is added to `spend`; the covered amount is subtracted from `g`. This phase ends — and Phase 4 begins — when `troop` reaches or exceeds `C`.

**Phase 4, Catastrophic (`CATASTROPHIC`).** For whatever portion of `g` remains, the beneficiary's share equals that remainder multiplied by 0.05 (the catastrophic rate — five percent), rounded half up to integer cents. The plan's share is the remainder minus the beneficiary's share. Both are added to their respective accumulators; `spend` and `troop` are updated correspondingly.

After all four phases run, `beneficiary_cost_cents` on the claim row equals the sum of the four phase-specific beneficiary shares, `plan_cost_cents` on the claim equals the sum of the four plan shares, and `phase_at_adjudication` is set to the last phase that any byte of this claim touched. Rounding is applied **once per phase share**, not once at the end of the claim — this means the four rounded shares are summed to produce the claim totals. Finally, `current_phase` on the ledger is set to whatever phase the *next* byte (if any further spend occurred) would enter, using the updated counters.

The same calculation runs in a **forward-estimate** variant accessible to counselors and beneficiaries, which projects the cost of a hypothetical fill of a given `gross_cost_cents` at a given `tier` against the current ledger snapshot without mutating any state. Crucially, the forward variant operates on the live snapshot at the moment of the query, whereas the chronological variant used at adjudication replays adjudicated claims in `fill_date` order regardless of submission order; for claims submitted out of `fill_date` order the two variants can produce different `beneficiary_cost_cents` and different `phase_at_adjudication`. The forward variant returns `beneficiary_cost_cents`, `plan_cost_cents`, and `phase_at_adjudication` (a projection — it does not write back to the claim row).

A claim can also be reversed by a `PlanAdmin`. From `SUBMITTED`, reversal simply moves the claim to `REVERSED` with no ledger impact. From `ADJUDICATED`, reversal first verifies that this claim is still the most recent adjudication against the ledger (no claim has been adjudicated since this one — checked against `last_adjudicated_claim_id` and the chronological order of adjudications) — otherwise the reverse is blocked with `ERR_REVERSE_BLOCKED_BY_LATER_CLAIM`. When permitted, the four ledger counters are decreased by exactly this claim's contribution and `current_phase` is recomputed from the updated counters; if the compensating invariant would not hold after rollback the system returns `ERR_LEDGER_INVARIANT_BREACH`. Two adjudications racing on the same ledger compare `DrugPhaseLedger.version`; one wins and the other receives `ERR_LEDGER_VERSION_STALE`.

### 3.9. Termination, transfer, and death

A counselor terminates an active enrollment by supplying a `termination_date` that is on or after `effective_date` and on or before the last day of the plan's `plan_year`. Termination moves the enrollment `ACTIVE → TERMINATED`, opens a fresh `SEP_LOSS_OF_COVERAGE` `EnrollmentPeriod` for the beneficiary whose `window_start` is the current clock day and whose `window_end` is the current clock day plus sixty-three days, freezes the `DrugPhaseLedger.current_phase` as of `termination_date` (Part D only), marks any `LateEnrollmentPenalty` for this enrollment inactive (the penalty's `penalty_rate_decimal` is preserved as a snapshot but no longer contributes), and re-evaluates the beneficiary lifecycle — if no other `ACTIVE` enrollment remains, the beneficiary moves `ENROLLED → COVERAGE_GAP`. A beneficiary in `COVERAGE_GAP` who is then re-enrolled under an open period transitions back to `ENROLLED`.

A Part C transfer is a single atomic capability available only during an open AEP period: a counselor supplies `new_plan_id`, and the system terminates the old enrollment with `termination_date` set to December 31 of the current `plan_year` and immediately creates a new enrollment in `ACTIVE` status with `effective_date` set to January 1 of `plan_year` plus one and a fresh `DrugPhaseLedger` whose counters start at zero in the `DEDUCTIBLE` phase. The new plan's `plan_type` must match the old enrollment's `part_covered`, and the new plan's `plan_year` must equal the old plan's `plan_year` plus one; if either fails the transfer is rejected with `ERR_TRANSFER_WINDOW_INVALID`. The transfer must occur within an open AEP — outside the AEP, the same error fires. Two transfers raced on the same Part C enrollment serialise on `Enrollment.status` — the loser observes that the old `ACTIVE` row has already moved to `TERMINATED` and receives `ERR_INVALID_STATE`. Two enrollments raced into the same `(beneficiary_id, part_covered)` pair serialise as first-writer-wins on the pair, and the loser receives `ERR_DUPLICATE_PART_ENROLLMENT`. Two activations citing the same `EnrollmentPeriod` serialise on `EnrollmentPeriod.consumed_by_enrollment_id` — exactly one binds the period, and the loser receives `ERR_PERIOD_ALREADY_CONSUMED`.

Finally, the death cascade. A `PlanAdmin` marks a beneficiary deceased; the call requires the beneficiary's `lifecycle_status` to be anything other than `DECEASED`. The system stamps `deceased_at` to the current clock, transitions the beneficiary to `DECEASED` from either `ENROLLED` or `IEP_OPEN`, transitions every `ACTIVE` `Enrollment` for the beneficiary to `TERMINATED` with `termination_date` set to the current clock, cancels every `MedigapPolicy` in `APPLIED`, `UNDERWRITING`, or `ISSUED` to `CANCELLED`, and reverses every `SUBMITTED` `DrugClaim` to `REVERSED`. The action is also available with an optional `version` for optimistic concurrency. After this cascade, any subsequent operation targeting the beneficiary is rejected with `ERR_BENEFICIARY_DECEASED`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; reads and mutations of existing resources return HTTP 200. All endpoints follow the response envelope of §2.2 and the validation priority order of §2.8. The table below is intentionally minimal — request bodies, response bodies, and side effects are described in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /beneficiaries | Create a beneficiary; server computes eligibility window. | PlanAdmin |
| GET | /beneficiaries/{id} | Fetch a beneficiary including computed fields. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /beneficiaries | List beneficiaries; supports `lifecycle_status` and `state_code` filters. | PlanAdmin, Auditor |
| POST | /beneficiaries/{id}/mark-deceased | Mark beneficiary deceased; cascade-terminate enrollments, cancel Medigap, reverse submitted claims. | PlanAdmin |
| POST | /plans | Create a plan. | PlanAdmin |
| GET | /plans/{id} | Fetch a plan. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /plans | List plans; supports `plan_type`, `plan_year`, `state_code`, `min_star_rating` filters. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| POST | /plans/{id}/star-ratings | Publish a `StarRatingSnapshot`; may update `Plan.star_rating`. | PlanAdmin |
| POST | /beneficiaries/{beneficiary_id}/enrollment-periods | Open a non-IEP period (`AEP`, `GEP`, `SEP_MOVE`, `SEP_LOSS_OF_COVERAGE`, `MEDIGAP_GI`). | PlanAdmin |
| GET | /beneficiaries/{beneficiary_id}/enrollment-periods | List enrollment periods for a beneficiary; supports `status` and `period_type` filters. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| POST | /enrollments | Create an enrollment in `PENDING`. | BenefitsCounselor |
| POST | /enrollments/{id}/activate | Activate an enrollment; runs penalty calc and lifecycle cascade. | BenefitsCounselor |
| POST | /enrollments/{id}/reject | Reject a pending enrollment. | PlanAdmin |
| POST | /enrollments/{id}/terminate | Terminate an active enrollment; opens an SEP loss-of-coverage period. | BenefitsCounselor |
| POST | /enrollments/{id}/transfer | Transfer Part C enrollment during AEP. | BenefitsCounselor |
| GET | /enrollments/{id} | Fetch an enrollment. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /beneficiaries/{beneficiary_id}/enrollments | List enrollments for a beneficiary; supports `status` and `part_covered` filters. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /enrollments/{id}/cost-summary | Return cost summary (provisional or final variant). | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /late-enrollment-penalties/{id} | Fetch a late-enrollment penalty record. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /beneficiaries/{beneficiary_id}/late-enrollment-penalties | List LEPs for a beneficiary; supports `part` filter. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| POST | /medigap-policies | Apply for a Medigap policy. | BenefitsCounselor |
| POST | /medigap-policies/{id}/evaluate-gi | Convert APPLIED to GUARANTEED_ISSUED. | PlanAdmin |
| POST | /medigap-policies/{id}/begin-underwriting | Move APPLIED to UNDERWRITING. | PlanAdmin |
| POST | /medigap-policies/{id}/revise-application | Return UNDERWRITING to APPLIED for amendment. | BenefitsCounselor |
| POST | /medigap-policies/{id}/issue | Issue the policy from GUARANTEED_ISSUED or UNDERWRITING. | PlanAdmin |
| POST | /medigap-policies/{id}/deny | Deny the policy from UNDERWRITING. | PlanAdmin |
| POST | /medigap-policies/{id}/cancel | Cancel the policy from APPLIED, UNDERWRITING, or ISSUED. | BenefitsCounselor |
| GET | /medigap-policies/{id} | Fetch a Medigap policy. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| POST | /drug-claims | Submit a drug claim under a Part D enrollment. | BenefitsCounselor |
| POST | /drug-claims/{id}/adjudicate | Adjudicate a submitted claim; runs the four-phase calc. | PlanAdmin |
| POST | /drug-claims/{id}/reverse | Reverse a submitted or most-recent adjudicated claim. | PlanAdmin |
| GET | /drug-claims/{id} | Fetch a drug claim. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /beneficiaries/{beneficiary_id}/drug-phase-ledger | Fetch the current ledger; supports `plan_year` filter. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |
| GET | /beneficiaries/{beneficiary_id}/drug-cost-estimate | Forward-estimate variant of the donut-hole calc for a hypothetical fill given `gross_cost_cents` and `tier`. | PlanAdmin, BenefitsCounselor, Beneficiary |
| POST | /_clock/advance | Advance the test clock to `to`; returns the list of transitions applied. | PlanAdmin, Auditor |
| GET | /_clock | Read the current test-clock time. | PlanAdmin, BenefitsCounselor, Beneficiary, Auditor |

## 5. Error Code Catalogue

The trigger conditions for each error are described in §2 and §3 alongside the workflow they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_AUTH_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_VALIDATION | 422 |
| ERR_BENEFICIARY_DECEASED | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_PLAN_INACTIVE | 422 |
| ERR_NON_PART_D_CLAIM | 422 |
| ERR_PERIOD_NOT_OPEN | 409 |
| ERR_PERIOD_ALREADY_CONSUMED | 409 |
| ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD | 422 |
| ERR_FILL_DATE_OUT_OF_COVERAGE | 422 |
| ERR_DUPLICATE_PART_ENROLLMENT | 409 |
| ERR_MEDIGAP_STATE_MISMATCH | 422 |
| ERR_LEDGER_INVARIANT_BREACH | 409 |
| ERR_REVERSE_BLOCKED_BY_LATER_CLAIM | 409 |
| ERR_LEDGER_VERSION_STALE | 409 |
| ERR_TRANSFER_WINDOW_INVALID | 422 |
| ERR_INVALID_PREMIUM | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VERSION_CONFLICT | 409 |

# Performance Review & Compensation Planning API — Product Requirements Document

## 1. Introduction

Every year (or twice a year), an organization must answer two intertwined questions about each of its people: *how did they perform?* and *what should that mean for their pay and equity?* This service is the backend system of record for that process end to end. It governs the annual or semi-annual review cadence, captures goals and 360-degree feedback, runs a performance calibration step in which a facilitator reconciles raw ratings against a target bell-curve distribution, and then drives compensation planning — merit increases, promotions, and equity refreshes — against finite, budgeted pools of money and shares.

The product exists to make a famously error-prone, politically charged, money-moving process auditable and rule-bound. The hard parts are not data entry; they are the reconciliation invariants. Merit dollars and equity units are committed against cycle-wide budgets that must never be overspent, even when many managers and approvers act against the same cycle. Calibration must force the actual rating distribution to stay within tolerance of a declared target before any rating becomes final. A manager who authored a review must never be the person who calibrates or approves the compensation tied to it. And because the merit and equity ledgers are read, reasoned about, and then written by separate actors at separate times, the system uses optimistic concurrency control so that a stale view of remaining budget can never silently approve an over-budget plan.

This document is the complete functional specification for that backend. It defines the eight core resources, their lifecycle state machines, the four calculation engines (composite scoring, bell-curve calibration, the merit/promotion matrix, and the equity-refresh waterfall), the validation rules and the order in which they fire, the full HTTP surface, and the error catalogue. It is written for the engineer who will implement the service and for the test author who will verify it; both should be able to reconstruct every numeric rule from the prose alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The `X-User-Role` header must name one of the five recognized roles — `HrAdmin`, `Manager`, `Employee`, `HrbpPartner`, or `CompApprover`. If either header is missing, or `X-User-Role` is not one of those five values, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles map to `X-User-ID` as follows:

- When `X-User-Role` is `HrAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. The `HrAdmin` owns the cycle lifecycle and the organizational setup: it alone creates review cycles, adds rating bands, drives the cycle through its phase transitions (opening it, starting calibration, starting comp planning, and closing it), and creates employees.
- When `X-User-Role` is `Manager`, `X-User-ID` is the `id` of the acting `Employee`; ownership and segregation-of-duties checks on any review compare the review's `reviewer_id` to `X-User-ID`. A `Manager` authors reviews, scores goals, and builds compensation plans for their reports.
- When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; checks that the actor is the subject of a review compare the review's `employee_id` to `X-User-ID`. An `Employee` is the subject of a review and performs the self-assessment and submits 360 feedback.
- When `X-User-Role` is `HrbpPartner`, `X-User-ID` is the `id` of the acting `Employee`; the HR business partner facilitates calibration, returns reviews, and runs the performance-improvement process, and may not be the reviewer of any review they calibrate.
- When `X-User-Role` is `CompApprover`, `X-User-ID` is the `id` of the acting `Employee`; the approver accepts or rejects compensation plans against budget and must be segregated from the authoring manager.

Read operations (`GET`) are generally open to the operational roles as listed per endpoint in Section 4; mutating operations are restricted to the roles named there.

### 2.2. API Response Structure

Every response from the API, whether successful or not, is a single JSON object that follows one fixed envelope. The envelope has two top-level members that are always present: a `meta` object and a `response_type` string. A third member, `data`, carries the payload.

A successful response uses `response_type` of either `"object"` (for a single resource) or `"array"` (for a list), and places the resource or list under `data`:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "object",
  "data": { }
}
```

An error response uses `response_type` of `"error"` and places a machine-readable `error_id` and a human-readable `message` under `data`:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable description of the error."
  }
}
```

The `meta.api_request_id` is a server-generated identifier for the individual HTTP request, and `meta.api_request_timestamp` is the ISO 8601 UTC instant at which the response was produced. These two fields appear on every response.

### 2.3. Pagination

List endpoints are paginated through two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and counts the number of leading records to skip. Results are always returned sorted by `created_at` in ascending order (oldest first). Each list response carries pagination metadata in `meta`: the effective `limit`, the effective `offset`, the `total_count` of records matching the query before pagination, and a boolean `has_more` indicating whether records remain beyond the returned page.

### 2.4. Common Resource Properties and Object Identity

Every resource is assigned a server-minted `id` — an opaque UUID string with no type prefix — at creation; clients never supply ids. Most resources also carry three lifecycle properties: a `created_at` and an `updated_at` timestamp, both ISO 8601 UTC with three fractional-second digits, and an integer `version` that starts at 1 and increases by exactly 1 on every mutation. The `RatingBand` resource is the one exception: a rating band carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version`, because bands are defined once on a draft cycle and are not independently mutated thereafter.

The `version` integer is the anchor of the system's optimistic concurrency control (Section 2.6). Whenever a transition's effect is described as "advancing" or "incrementing" a resource's version, it means the integer is raised by one and `updated_at` is refreshed to the time of the change.

### 2.5. Nested Path Resolution and Referential Integrity

Several routes are nested — a goal lives beneath a review, a rating band beneath a cycle, and so on. Path parameters are resolved left to right, and every referenced resource must exist; the first missing one causes the request to fail with `ERR_NOT_FOUND` (HTTP 404). The same code applies when a foreign key supplied in a request body — a `cycle_id`, `employee_id`, `reviewer_id`, `review_id`, `rater_id`, `facilitator_id`, or `manager_id` — points at a resource that does not exist.

### 2.6. Optimistic Concurrency on the Compensation Ledgers

Compensation operations read a budget, reason about remaining headroom, and then commit money or shares against it. Because those reads and writes are separated in time and performed by different actors, two endpoints require the client to prove it is acting on a current view by supplying the parent resource's last-observed `version`.

Creating a compensation plan is a write whose computed result depends on the target review's current state. A create request must carry `expected_review_version` equal to the target `Review`'s current `version`. If the review's version has advanced since the client last observed it — for example because a re-finalized calibration re-set its `final_rating` — the create is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412), because the merit and equity figures are derived from the review's current `final_rating` and a stale view would compute them wrongly.

Approving a compensation plan is a write that debits the cycle-wide merit and equity ledgers. An approve request must carry `expected_cycle_version` equal to the target plan's parent `ReviewCycle`'s current `version`. If another approval has advanced those ledgers since the client last read the cycle, the approve is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), so that the budget checks are always evaluated against the current committed totals rather than a stale snapshot of remaining budget. Endpoints other than plan creation and plan approval do not take a version field.

### 2.7. Precision, Rounding, and the Reconciliation Ledgers

All monetary computations are carried to two decimal places, rounded half up. Equity computations are carried to three decimal places on share units, also rounded half up. The cycle maintains two running reconciliation ledgers as computed fields: `merit_committed_total`, the sum of `merit_amount` across all of the cycle's compensation plans that are in the `APPROVED` state, and `equity_committed_total`, the sum of `equity_refresh_units` across those same approved plans.

The order of operations on the merit ledger is pinned and must not be reordered: each plan's `merit_amount` is rounded to two decimal places first, and only the already-rounded amount is then added into the cycle's running `merit_committed_total`. This is a round-then-sum discipline, never a sum-then-round one; reordering it produces off-by-a-cent reconciliation errors. A rejected plan never touches either ledger — only approval debits committed totals, and rejection is guaranteed to leave them untouched.

### 2.8. Segregation of Duties

A recurring safety principle runs through the workflow: the person who authored a review may not also be the person who passes judgment on it downstream. Concretely, the acting `Employee` (identified by `X-User-ID`) must not equal a review's `reviewer_id` when returning that review, when finalizing a calibration session whose scope includes it, and when approving or rejecting a compensation plan tied to it. A violation of any of these is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Cycle: Bands, the Bell Curve, and Opening

A review cycle is created by an `HrAdmin` and begins life in `DRAFT`. At creation the cycle is given a human-readable `name` (non-empty, at most 120 characters) and a `cadence` that is either `ANNUAL` or `SEMI_ANNUAL`. Two budget inputs are fixed at this moment: `merit_budget_pct`, the total merit budget expressed as a fraction of summed eligible base salary — for instance a value of four hundredths means four percent — which must be between zero and one half inclusive; and `equity_refresh_pool`, the total number of share units available to refresh across the whole cycle, which must be zero or greater. The cycle also receives its target rating distribution, `bell_curve_target`, an object mapping each rating-band label to the fraction of reviews that should land in that band — for example twenty hundredths in the top band, sixty-five hundredths in the middle, and fifteen hundredths in the lowest — whose values must each be a fraction between zero and one and must together sum to one within a tolerance of five ten-thousandths. Finally the cycle carries a `distribution_tolerance`, the largest absolute gap any single band's actual fraction may have from its target before calibration is blocked; it defaults to five hundredths and must be between zero and one inclusive. The two ledger fields, `merit_committed_total` and `equity_committed_total`, are computed and begin at zero.

While the cycle is still in `DRAFT`, the `HrAdmin` defines its rating bands. Each `RatingBand` carries a `label` (non-empty and unique within the cycle, such as `EXCEEDS`, `MEETS`, or `BELOW`), a `min_score` that is the inclusive lower bound of the composite scores mapping into the band, a `max_score` that is the exclusive upper bound (with the single exception that the top band includes a score of exactly 100), a `merit_pct` giving the base merit fraction for that band before any promotion uplift (which must be zero or greater), and a `pip_eligible` flag, defaulting to false, marking whether a review landing in this band triggers a performance-improvement plan. Each band's `min_score` must be at least 0 and at most 100, and its `max_score` must be greater than its `min_score` and at most 100.

Opening the cycle — transitioning it from `DRAFT` to `OPEN` — is performed by the `HrAdmin` and is heavily guarded. The cycle must have at least one rating band. The bands must tile the score range from 0 to 100 completely, with no gaps and no overlaps; a failure of this coverage condition, or a mismatch between the set of band labels and the set of keys in `bell_curve_target`, is rejected with `ERR_BAND_COVERAGE_INVALID` (HTTP 422). Separately, the `bell_curve_target` fractions must sum to one within five ten-thousandths; a sum outside that window is rejected with `ERR_DISTRIBUTION_NOT_NORMALIZED` (HTTP 422). When both checks pass, the cycle advances to `OPEN` and its `version` is incremented by one. A cycle progresses only forward through the states `DRAFT → OPEN → CALIBRATION → COMP_PLANNING → CLOSED`; any attempt to perform a transition from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

The organization's people are represented as `Employee` records, created by the `HrAdmin`. An employee has a `full_name` (non-empty), an optional `manager_id` referencing another employee as their manager (null for the top of the chain, and never equal to the employee's own id), a `department` label, a `hire_date` whose distance from the cycle gates equity eligibility, and an `is_active` boolean defaulting to true that records whether the person is currently employed.

### 3.2. Self-Assessment, Manager Authoring, and the Return Loop

A `Review` is the unit of evaluation, created under a cycle by either an `HrAdmin` or a `Manager`. At creation it names its `cycle_id`, the `employee_id` of the person being reviewed, the `reviewer_id` of the manager authoring it, and a `base_salary` — the employee's annual base pay snapshotted at this moment (which must be greater than zero) and which becomes the basis for all later merit math. A new review begins in `DRAFT`. Its `self_rating`, `manager_rating`, `final_rating`, and `composite_score` are all empty until the process fills them in, and they are reached through the review's lifecycle `DRAFT → SELF_REVIEW → MANAGER_REVIEW → SUBMITTED`, with possible detours to `RETURNED` and forward to `CALIBRATED` and finally `FINALIZED`.

The subject employee begins their self-review, moving it from `DRAFT` to `SELF_REVIEW`; this is allowed only while the parent cycle is `OPEN` and only when the acting employee is the review's subject. Before, during, or after that, ratings are set through a patch operation: the subject may set `self_rating` and the manager may set `manager_rating`, each of which must name a label that exists among the cycle's rating bands. Goals and feedback are also attached during this window. The subject then submits their self-review, advancing it from `SELF_REVIEW` to `MANAGER_REVIEW`; this requires that `self_rating` has been set and names a valid band label, and that the actor is the subject.

The manager then submits the review, moving it from `MANAGER_REVIEW` to `SUBMITTED`. Submission requires that `manager_rating` has been set and names a valid band label, that every goal on the review is in the `SCORED` state, and that the actor is the review's reviewer. A supplied rating label — `self_rating`, `manager_rating`, or `final_rating` — that does not match any band on the cycle is rejected with `ERR_RATING_BAND_UNKNOWN` (HTTP 422); this check applies to the review submission endpoints and to calibration finalization. Submission also computes the review's `composite_score` (Section 3.5) and increments its `version`.

After a review is `SUBMITTED`, an `HrbpPartner` may send it back for rework, transitioning it from `SUBMITTED` to `RETURNED`. A return is permitted only while the parent cycle is `OPEN` or `CALIBRATION`, and the acting partner must not be the review's reviewer (segregation of duties, `ERR_SEGREGATION_OF_DUTIES`). The authoring manager then reopens the returned review, moving it from `RETURNED` back to `MANAGER_REVIEW` for another pass; reopening requires that the actor is the reviewer. Each of these transitions increments the review's `version`.

### 3.3. Goals and 360 Feedback

Goals quantify what an employee was asked to achieve. A `Goal` is attached to a review by a `Manager` or the `Employee`, carrying a non-empty `title` and a `weight` that is its relative importance among the review's goals — strictly greater than zero and at most one — together with an optional `attainment_pct`, the achieved fraction of the goal, which ranges from zero to one and one half (over-achievement up to one hundred fifty percent is permitted). A goal is created in the `OPEN` state. A `Manager` later scores it by setting `attainment_pct` and moving it from `OPEN` to `SCORED`, which increments the goal's `version`. Because a review cannot be submitted until all its goals are scored, scoring is the gate between authoring and submission.

The constraints on goals are enforced together at submission and on goal creation: the sum of a review's goal weights must lie in the half-open range above zero and up to and including one, each `attainment_pct` must lie between zero and one and one half inclusive, and a review may not be submitted with zero goals. Any of these failures is reported as `ERR_GOAL_WEIGHTS_INVALID` (HTTP 422), and the check is applied both when submitting a review and when adding a goal to one.

Feedback is gathered through `FeedbackRequest` records, which model the 360-degree inputs. A request is created on a review by a `Manager` or an `HrbpPartner`, naming the `rater_id` of the feedback provider and the `relationship` of that rater to the subject — one of `PEER`, `REPORT`, `MANAGER`, or `SELF`. A new request begins `PENDING` and carries no `score` yet. The rater (an `Employee`) either submits it, supplying a numeric `score` between one and five inclusive and moving it from `PENDING` to `SUBMITTED`, or declines it, moving it from `PENDING` to `DECLINED`. Each of those transitions increments the request's `version`. Only `SUBMITTED` feedback feeds the composite score; `PENDING` and `DECLINED` requests are simply absent from the calculation and are never counted as zeros.

### 3.4. Calibration: Balancing the Curve and Finalizing Ratings

Once every review in the cycle has reached `SUBMITTED` or beyond, the `HrAdmin` starts calibration, transitioning the cycle from `OPEN` to `CALIBRATION` and incrementing its `version`. If any review is still short of `SUBMITTED`, this transition is not defined and fails with `ERR_INVALID_STATE`.

Calibration happens within `CalibrationSession` records, each created by an `HrbpPartner` and scoped to a single `cycle_id` and `department`, with a `facilitator_id` naming the HR business partner who will run it. A session begins `OPEN`. It also exposes two computed fields, `bell_curve_actual` — the actual fraction of in-scope reviews landing in each band, measured at the moment the curve is computed — and `review_count`, the number of reviews in scope, which are those in the session's cycle and department whose status is `SUBMITTED` or later.

The facilitator first balances the session, moving it from `OPEN` to `BALANCED`. This step is permitted only while the parent cycle is in `CALIBRATION`. It computes `bell_curve_actual` over the in-scope `SUBMITTED` reviews and then checks the bell-curve guard: for every band, the absolute difference between that band's actual fraction and its target fraction must be at most the cycle's `distribution_tolerance`. If any band deviates by more than the tolerance, the balance is blocked with `ERR_DISTRIBUTION_OUT_OF_TOLERANCE` (HTTP 422). On success the session's `version` is incremented.

The facilitator then finalizes the session, moving it from `BALANCED` to `FINALIZED`. Finalizing requires that the acting employee is the session's `facilitator_id`, and — to honor segregation of duties — that this facilitator was not the `reviewer_id` of any review in scope; a violation is `ERR_SEGREGATION_OF_DUTIES`. Finalization is the moment ratings become final. For each in-scope `SUBMITTED` review it sets the review's `final_rating` by the calibration algorithm (Section 3.6) and transitions that review from `SUBMITTED` to `CALIBRATED`. For each review that is newly `CALIBRATED` and whose `final_rating` falls in a `pip_eligible` band, it cascade-creates a `PipCase` for that review in the `OPEN` state. Each review whose rating is set this way has its own `version` incremented, and the session's `version` is incremented as well.

When every calibration session on the cycle is `FINALIZED`, the `HrAdmin` starts comp planning, transitioning the cycle from `CALIBRATION` to `COMP_PLANNING` and incrementing its `version`; if any session is not yet finalized, the transition fails with `ERR_INVALID_STATE`.

### 3.5. Computing the Composite Score

When a manager submits a review, the system computes its `composite_score`, a number from 0 to 100 that blends goal attainment with feedback. The score is a weighted combination of two components, with the goal component carrying seventy percent of the weight and the feedback component carrying thirty percent.

The goal component is built from the review's scored goals. For each goal, take its `attainment_pct` but cap it at one (so over-achievement beyond one hundred percent does not inflate the score), multiply that capped attainment by the goal's `weight`, and sum these products across all goals. Divide that sum by the total of the goals' weights to get a weighted average attainment, then multiply by 100 to express it on a 0-to-100 scale. (Because a review cannot be submitted with zero goals, the total weight is always positive.)

The feedback component is built from the review's `SUBMITTED` feedback requests only. If there are no submitted feedback requests, the feedback component is set equal to the goal component, so the composite reduces to the goal score — declined or still-pending requests are never treated as zeros. Otherwise, average the `score` values of the submitted requests (each on the one-to-five scale), subtract one, divide by four, and multiply by 100 to map the one-to-five range onto a 0-to-100 scale.

Finally, multiply the goal component by seven tenths and the feedback component by three tenths, add the two, and round the result half up to two decimal places. That rounded value is the review's `composite_score`, and it determines which band the review naturally falls into during calibration.

### 3.6. Assigning the Final Rating Under the Bell Curve

Calibration finalization assigns each in-scope review a `final_rating` using a chronological-replay algorithm that respects the target distribution. The reviews in scope are processed in ascending `created_at` order — by creation time, never by id.

First, every review is provisionally placed in the band whose score range contains its `composite_score`: the band whose `min_score` is at most the score and whose `max_score` is greater than the score, with the top band also accepting a score of exactly 100. Then the distribution is corrected. While there exists any band — other than the very lowest band — whose actual fraction of reviews exceeds its target fraction plus the cycle's tolerance, the system demotes one review out of that over-full band into the next-lower band. The review chosen for demotion is the one with the lowest `composite_score` currently sitting in the over-full band; ties are broken by the earlier `created_at`. Demotions are applied one at a time and the over-full condition is re-checked after each, so the oldest, lowest-scoring reviews in an over-full band are pushed down first until every band other than the lowest is within tolerance.

When the actual distribution is already within tolerance of the target for every band, no demotions occur and each review's `final_rating` is simply the band its `composite_score` fell into. The forced-demotion path is the variant that diverges from that naive placement, and it is the reason calibration must replay deterministically in creation order.

### 3.7. The Performance-Improvement (PIP) Process

A `PipCase` is opened automatically when calibration lands a review in a `pip_eligible` band, as described above; it references the triggering `review_id` and the subject `employee_id` and starts in `OPEN`. The HR business partner activates it, supplying a `duration_days` improvement window that must be exactly 30, 60, or 90 and a `target_score` — the composite score the employee must reach to cure the case, which must be greater than zero and at most 100 — and moving the case from `OPEN` to `ACTIVE`; both inputs must be present for activation, which increments the case's `version`.

At the end of the window the partner assesses the case, supplying an `outcome_score` (the composite score recorded at closeout, between zero and 100 inclusive, and empty until assessed). The assessment branches on the outcome. If the `outcome_score` is at least the `target_score`, the case is cured, moving from `ACTIVE` to `CURED`, and its `version` is incremented. If the `outcome_score` is below the `target_score`, the case fails, moving from `ACTIVE` to `FAILED`; failure additionally sets the subject `Employee`'s `is_active` to false to record the separation, and increments the case's `version`. These two branches are the only outcomes of an assessment, and which one fires depends solely on the comparison of the outcome to the target.

A second, distinct path can also cure a PIP: when a compensation plan is approved and the plan's review now sits in a band that is no longer `pip_eligible`, an existing `OPEN` PipCase for that review is transitioned from `OPEN` to `CURED` as a side effect of the approval (Section 3.8).

### 3.8. Compensation Planning: Merit, Promotion, and Equity

With the cycle in `COMP_PLANNING`, a `Manager` creates a `CompPlan` for a calibrated review. The create names the `cycle_id`, the `review_id` of the calibrated review being compensated, a `plan_type` of either `MERIT_ONLY` or `MERIT_AND_PROMO`, and a `promo_band_jump` — the number of pay-band levels jumped on promotion, defaulting to zero. The `promo_band_jump` must be exactly zero for a `MERIT_ONLY` plan and either one or two for a `MERIT_AND_PROMO` plan; any other combination is rejected with `ERR_PROMO_JUMP_INVALID` (HTTP 422). The create also carries `expected_review_version` for the stale-review concurrency guard described in Section 2.6. A plan begins in `DRAFT`, and on creation the system computes the plan's `merit_pct`, `merit_amount`, and `equity_refresh_units`. A `Manager` may later recompute these on a draft plan (for instance after changing `plan_type` or `promo_band_jump`), which re-derives the figures and increments the plan's `version`.

The **merit amount** is selected from the rating/promotion matrix. Start with the base merit fraction of the band the review's `final_rating` falls in — that band's `merit_pct`. For a `MERIT_ONLY` plan, the plan's `merit_pct` is exactly that base fraction with no uplift. For a `MERIT_AND_PROMO` plan, add a promotion uplift of three hundredths for each band level jumped — that is, three hundredths multiplied by `promo_band_jump` — to the base fraction, and then cap the result at a maximum merit fraction of twenty-five hundredths. The plan's `merit_amount` is the resulting `merit_pct` multiplied by the review's `base_salary`, rounded half up to two decimal places. As established in Section 2.7, this rounding happens before the amount is ever added into the cycle's `merit_committed_total`.

The **equity refresh** distributes shares from the cycle's finite pool by band priority and then tenure. First compute the employee's tenure in whole years as the number of complete 365-day periods between the employee's `hire_date` and the cycle's `created_at` (the fractional remainder is discarded). If that tenure is less than one year, the employee is ineligible and `equity_refresh_units` is zero regardless of band. Equity eligibility is also enforced as a validation at plan creation and recompute: a tenure of less than the one-year minimum is rejected with `ERR_TENURE_INELIGIBLE` (HTTP 422). For an eligible employee, take the band-equity factor for the review's `final_rating` — four hundred share units for the top `EXCEEDS` band, one hundred fifty for the middle `MEETS` band, and zero for the `BELOW` band — and scale it by a tenure bonus: one plus one tenth for each whole year of tenure, where the tenure used for the bonus is capped at five years. This product is the raw target. The granted amount is the smaller of that raw target and the pool's remaining headroom (the `equity_refresh_pool` minus the cycle's current `equity_committed_total`), floored at zero so it never goes negative, and rounded half up to three decimal places. Because grants are allocated in order of band priority high-to-low and then `created_at` ascending against a shrinking pool, two otherwise-identical employees can receive different equity depending on allocation order — a later grant is clamped to whatever headroom remains and never overflows beyond its own raw target.

To move a plan forward, the `Manager` proposes it, transitioning it from `DRAFT` to `PROPOSED`. Proposal requires that the plan's review is `CALIBRATED`, that the parent cycle is in `COMP_PLANNING`, and that `merit_amount` and `equity_refresh_units` have been computed; it increments the plan's `version`.

A `CompApprover` then either approves or rejects the proposed plan. **Approval** moves the plan from `PROPOSED` to `APPROVED` and is the only operation that debits the ledgers. It is guarded by several checks. The approver must not be the review's reviewer (`ERR_SEGREGATION_OF_DUTIES`). The approve request must carry an `expected_cycle_version` matching the cycle's current `version`, or it is rejected with `ERR_STALE_CYCLE_VERSION` as described in Section 2.6. The merit budget must hold: the cycle's current `merit_committed_total` plus this plan's `merit_amount` must not exceed `merit_budget_pct` multiplied by the summed `base_salary` of the cycle's reviews that are `CALIBRATED` or later; exceeding it is rejected with `ERR_MERIT_BUDGET_EXCEEDED` (HTTP 422). The equity pool must likewise hold: the cycle's current `equity_committed_total` plus this plan's `equity_refresh_units` must not exceed the `equity_refresh_pool`; exceeding it is rejected with `ERR_EQUITY_POOL_EXCEEDED` (HTTP 422). On success, approval adds the plan's `merit_amount` to the cycle's `merit_committed_total` and its `equity_refresh_units` to the cycle's `equity_committed_total`, transitions the referenced review from `CALIBRATED` to `FINALIZED`, cures a still-`OPEN` PipCase on that review if the review's band is no longer `pip_eligible` (moving that case from `OPEN` to `CURED`), and increments both the plan's `version` and the cycle's `version` by one.

**Rejection** moves the plan from `PROPOSED` to `REJECTED`. The approver must not be the review's reviewer (`ERR_SEGREGATION_OF_DUTIES`). Rejection increments the plan's `version` and, as guaranteed in Section 2.7, never touches the merit or equity committed totals. A plan reaches one of its two terminal states, `APPROVED` or `REJECTED`, and goes no further.

When the validation guards on these operations are evaluated, they fire in a fixed order: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of all path- and body-referenced resources (`ERR_NOT_FOUND`), then the state-machine check that the resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then rating-band referential validity (`ERR_RATING_BAND_UNKNOWN`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the band-coverage and distribution-normalization checks at cycle open, then goal-weight validity, then the bell-curve tolerance guard at balance, then the equity tenure gate, then the merit-budget and equity-pool fiscal checks at approval, then the promotion-jump check at plan creation, and finally the optimistic-concurrency version checks on plan creation and approval. This ordering matters: a request that violates several rules at once surfaces the earliest one in this sequence, so an unauthenticated caller always sees `ERR_UNAUTHENTICATED` rather than a downstream business error, and a missing resource surfaces `ERR_NOT_FOUND` before any state or fiscal check is consulted.

### 3.9. Closing the Cycle

Closing a cycle is the `HrAdmin`'s final act, transitioning it from `COMP_PLANNING` to `CLOSED`. Two preconditions guard it: every compensation plan on the cycle must be in a terminal state — `APPROVED` or `REJECTED` — and the cycle's `merit_committed_total` must not exceed `merit_budget_pct` multiplied by the summed `base_salary` of the cycle's `FINALIZED` reviews. When both hold, the cycle moves to `CLOSED` and its `version` is incremented; `CLOSED` is terminal and no further transition is defined from it.

## 4. Endpoint Definitions

All endpoints exchange JSON wrapped in the envelope of Section 2.2. A request that creates a new resource returns HTTP 201; a request that reads or mutates an existing resource returns HTTP 200. The authorization column lists the roles permitted to invoke each route; any other role is rejected with `ERR_FORBIDDEN_ROLE`, and a request lacking valid identity headers is rejected with `ERR_UNAUTHENTICATED`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/cycles` | Create a review cycle in `DRAFT` | HrAdmin |
| GET | `/cycles` | List cycles, filterable by status | HrAdmin, HrbpPartner, CompApprover |
| GET | `/cycles/{id}` | Read a cycle including its committed-total ledgers | HrAdmin, HrbpPartner, CompApprover |
| POST | `/cycles/{id}/rating-bands` | Add a rating band to a draft cycle | HrAdmin |
| GET | `/cycles/{id}/rating-bands` | List a cycle's rating bands | HrAdmin, HrbpPartner, CompApprover |
| POST | `/cycles/{id}/open` | Advance a cycle from `DRAFT` to `OPEN` | HrAdmin |
| POST | `/cycles/{id}/start-calibration` | Advance a cycle from `OPEN` to `CALIBRATION` | HrAdmin |
| POST | `/cycles/{id}/start-comp-planning` | Advance a cycle from `CALIBRATION` to `COMP_PLANNING` | HrAdmin |
| POST | `/cycles/{id}/close` | Advance a cycle from `COMP_PLANNING` to `CLOSED` | HrAdmin |
| POST | `/employees` | Create an employee | HrAdmin |
| GET | `/employees/{id}` | Read an employee | HrAdmin, HrbpPartner, CompApprover, Manager, Employee |
| GET | `/employees` | List employees, filterable by manager or department | HrAdmin, HrbpPartner, CompApprover |
| POST | `/reviews` | Create a review under a cycle in `DRAFT` | HrAdmin, Manager |
| GET | `/reviews/{id}` | Read a review including its score and final rating | HrAdmin, HrbpPartner, CompApprover, Manager, Employee |
| GET | `/reviews` | List reviews, filterable by cycle, employee, reviewer, or status | HrAdmin, HrbpPartner, CompApprover, Manager |
| PATCH | `/reviews/{id}` | Set the self or manager rating on a review | Manager, Employee |
| POST | `/reviews/{id}/begin-self-review` | Advance a review from `DRAFT` to `SELF_REVIEW` | Employee |
| POST | `/reviews/{id}/submit-self` | Advance a review from `SELF_REVIEW` to `MANAGER_REVIEW` | Employee |
| POST | `/reviews/{id}/submit` | Advance a review from `MANAGER_REVIEW` to `SUBMITTED`, computing the composite score | Manager |
| POST | `/reviews/{id}/return` | Advance a review from `SUBMITTED` to `RETURNED` | HrbpPartner |
| POST | `/reviews/{id}/reopen` | Advance a review from `RETURNED` to `MANAGER_REVIEW` | Manager |
| POST | `/reviews/{id}/goals` | Add a goal to a review | Manager, Employee |
| GET | `/reviews/{id}/goals` | List a review's goals | HrAdmin, HrbpPartner, Manager, Employee |
| POST | `/goals/{id}/score` | Score a goal, moving it from `OPEN` to `SCORED` | Manager |
| POST | `/reviews/{id}/feedback-requests` | Create a 360 feedback request | Manager, HrbpPartner |
| GET | `/reviews/{id}/feedback-requests` | List a review's feedback requests | HrAdmin, HrbpPartner, Manager |
| POST | `/feedback-requests/{id}/submit` | Submit feedback with a score, moving it from `PENDING` to `SUBMITTED` | Employee |
| POST | `/feedback-requests/{id}/decline` | Decline feedback, moving it from `PENDING` to `DECLINED` | Employee |
| GET | `/feedback-requests` | List feedback requests, filterable by rater, review, or status | HrAdmin, HrbpPartner, Manager, Employee |
| GET | `/feedback-requests/{id}` | Read a single feedback request | HrAdmin, HrbpPartner, Manager, Employee |
| POST | `/calibration-sessions` | Create a calibration session for a cycle and department | HrbpPartner |
| GET | `/calibration-sessions` | List calibration sessions, filterable by cycle or facilitator | HrAdmin, HrbpPartner |
| GET | `/calibration-sessions/{id}` | Read a calibration session with its actual distribution | HrAdmin, HrbpPartner |
| POST | `/calibration-sessions/{id}/balance` | Advance a session from `OPEN` to `BALANCED`, computing and checking the distribution | HrbpPartner |
| POST | `/calibration-sessions/{id}/finalize` | Advance a session from `BALANCED` to `FINALIZED`, setting final ratings and cascading | HrbpPartner |
| POST | `/comp-plans` | Create a compensation plan for a calibrated review, computing merit and equity | Manager |
| GET | `/comp-plans` | List compensation plans, filterable by cycle, review, or status | HrAdmin, HrbpPartner, CompApprover, Manager |
| GET | `/comp-plans/{id}` | Read a compensation plan | HrAdmin, HrbpPartner, CompApprover, Manager |
| POST | `/comp-plans/{id}/recompute` | Recompute merit and equity on a draft plan | Manager |
| POST | `/comp-plans/{id}/propose` | Advance a plan from `DRAFT` to `PROPOSED` | Manager |
| POST | `/comp-plans/{id}/approve` | Advance a plan from `PROPOSED` to `APPROVED`, debiting ledgers and cascading | CompApprover |
| POST | `/comp-plans/{id}/reject` | Advance a plan from `PROPOSED` to `REJECTED` | CompApprover |
| GET | `/reviews/{id}/pip-cases` | List the PIP cases for a review | HrAdmin, HrbpPartner, Manager |
| GET | `/pip-cases` | List PIP cases, filterable by employee or status | HrAdmin, HrbpPartner |
| GET | `/pip-cases/{id}` | Read a PIP case | HrAdmin, HrbpPartner, Manager |
| POST | `/pip-cases/{id}/activate` | Advance a PIP case from `OPEN` to `ACTIVE` with a window and target | HrbpPartner |
| POST | `/pip-cases/{id}/assess` | Advance a PIP case from `ACTIVE` to `CURED` or `FAILED` by outcome | HrbpPartner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_RATING_BAND_UNKNOWN | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_BAND_COVERAGE_INVALID | 422 |
| ERR_DISTRIBUTION_NOT_NORMALIZED | 422 |
| ERR_GOAL_WEIGHTS_INVALID | 422 |
| ERR_DISTRIBUTION_OUT_OF_TOLERANCE | 422 |
| ERR_TENURE_INELIGIBLE | 422 |
| ERR_MERIT_BUDGET_EXCEEDED | 422 |
| ERR_EQUITY_POOL_EXCEEDED | 422 |
| ERR_PROMO_JUMP_INVALID | 422 |
| ERR_STALE_CYCLE_VERSION | 412 |
| ERR_STALE_REVIEW_VERSION | 412 |
| ERR_VALIDATION | 400 |

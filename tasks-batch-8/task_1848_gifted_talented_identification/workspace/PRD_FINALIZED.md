# Gifted & Talented Identification API — Product Requirements Document

## 1. Introduction

District gifted-services offices carry a dual obligation: find every student whose ability warrants gifted service, and demonstrate — to auditors, to families, and to the state — that the identification process was equitable across demographic groups. Most districts run this on spreadsheets: universal screening exports live in one file, teacher referrals arrive by email, the committee's cut-score matrix is a printout, and the disproportionality report is assembled by hand at the end of the year. Records drift, appeals lose their audit trail, and a transfer student who was already identified elsewhere waits months for a decision that should have been automatic.

This document specifies a REST API for running the full gifted identification pipeline in one place. The district office opens a screening cycle per grade band, publishes a weighted multi-criteria cut-score profile against it, collects ability / achievement / rating-scale / portfolio evidence per student, and routes each case to automatic identification, committee review, or denial based on published thresholds. Parents and teachers may refer; an appeals committee re-hears denied cases under quorum voting rules; accepted students flow into seat-managed service placements (pull-out, cluster, acceleration) with waitlists; annual re-evaluations apply growth-based exit criteria; and a computed disproportionality report flags under-represented groups against a reference population.

Two design commitments shape everything below. First, **all time is logical**: the server keeps a settable clock so that window checks (45-day transfer honoring, 30-day appeal and offer-acceptance windows, 730-day measure validity and external-identification freshness, annual re-evaluation due dates) are deterministic and testable. Second, **every threshold is published, not hidden**: cut scores, review bands, quorum sizes, occupancy caps, and the disproportionality flag line all live in data, so the same engine serves a small rural district and a large urban one by configuration alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the named role is not permitted to call the endpoint — including the `review_kind`-conditional role rules described in §3 — the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The platform recognizes exactly five roles, spelled as follows:

- `GiftedCoordinator` — district gifted-services office staff; runs cycles, cut-score profiles, scoring, placement offers, re-evaluations, reports, and the logical clock.
- `ReferringEducator` — teacher or other educator submitting referrals and supporting appeals.
- `ParentGuardian` — parent or guardian of a student; ownership-scoped.
- `CommitteeMember` — portfolio/appeals review committee voter.
- `SpecialEdCoordinator` — special-education liaison for twice-exceptional coordination.

For all five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — no `GiftedCoordinator`, `ReferringEducator`, `ParentGuardian`, `CommitteeMember`, or `SpecialEdCoordinator` row exists to compare it against. The server does, however, record the caller's identifier in three places where the workflow demands it: when a `REFERRAL`-pathway case is created, the caller's `X-User-ID` is stored as the case's `referrer_user_id`; when a committee member casts a vote, the caller's `X-User-ID` is stored as the vote's `member_user_id`; and on any `ParentGuardian`-scoped operation (placement accept, decline, or withdraw; appeal filing), the caller's `X-User-ID` is compared to the owning student's `primary_guardian_user_id`, with a mismatch rejected as `ERR_GUARDIAN_MISMATCH` (HTTP 403). That ownership comparison is the only place `X-User-ID` is checked against an entity field.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. The `meta` envelope of every list response carries `limit`, `offset`, `total_count`, and `has_more`. All list endpoints sort by `created_at` ascending unless a more specific ordering is stated for a particular workflow (the waitlist, for example, orders by `waitlisted_at`).

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` minted by the server as a bare UUID — no type prefix. Resources with full lifecycle tracking additionally carry `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at its initial value on creation and increments by one on every mutation of that resource. The full-lifecycle entities are: `SchoolSite`, `Student`, `ScreeningCycle`, `CutScoreProfile`, `GiftedCase`, `CommitteeReview`, `ServicePlacement`, and `ReEvaluation`. Three entities are ledger-style records carrying only `id` and `created_at` — `SpedPlan`, `MeasureScore`, and `CommitteeVote`; on these, both `updated_at` and `version` are absent.

All date fields in the domain are `YYYY-MM-DD` strings interpreted against the server's logical clock, not wall-clock time. The clock starts at exactly `2026-08-01T00:00:00Z` on server startup and must never fall back to wall-clock time. A coordinator-facing capability advances it: the request body carries `to_iso8601`, and the response echoes the new clock value as `current_utc`. Wherever this document says "today," it means the logical clock's UTC date. Setting the clock is not inert: it drives the re-evaluation activation sweep and the offer-expiry sweep described in §3.7 and §3.6.

### 2.5. Validation Order and Request Shape

When a request fails several rules at once, the error it receives is deterministic. Checks run in this priority order:

1. Header presence (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the endpoint, including `review_kind`-conditional roles (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Guardian ownership where the endpoint is guardian-scoped (`ERR_GUARDIAN_MISMATCH`).
4. Path-parameter existence, validated left-to-right (`ERR_NOT_FOUND`).
5. Request shape — required fields, types, enum membership, numeric ranges, date ordering, weight sums, cut-band sanity, pathway-conditional fields, future dates (`ERR_INVALID_REQUEST`).
6. Optimistic concurrency (`ERR_STALE_VERSION`).
7. State preconditions (`ERR_INVALID_CYCLE_STATE`, `ERR_CYCLE_NOT_OPEN`, `ERR_INVALID_CASE_STATE`, `ERR_PROFILE_NOT_DRAFT`, `ERR_INVALID_REVIEW_STATE`, `ERR_INVALID_PLACEMENT_STATE`, `ERR_REEVAL_NOT_IN_REVIEW`, `ERR_NO_PUBLISHED_PROFILE`, `ERR_CYCLE_HAS_OPEN_CASES`).
8. Committee conflict of interest (`ERR_COMMITTEE_CONFLICT_OF_INTEREST`).
9. Referential fit of student to cycle grade band (`ERR_GRADE_BAND_MISMATCH`).
10. Uniqueness and aggregate rules (`ERR_DUPLICATE_CASE`, `ERR_DUPLICATE_SPED_PLAN`, `ERR_DUPLICATE_MEASURE`, `ERR_DUPLICATE_VOTE`, `ERR_REVIEW_ALREADY_OPEN`, `ERR_REEVAL_ALREADY_OPEN`, `ERR_INCOMPLETE_MEASURES`, `ERR_REEVAL_OUTCOME_MISMATCH`).
11. Temporal windows and interval overlaps (`ERR_CYCLE_WINDOW_OVERLAP`, `ERR_PLACEMENT_PERIOD_OVERLAP`, `ERR_REFERRAL_WINDOW_CLOSED`, `ERR_TRANSFER_WINDOW_LAPSED`, `ERR_EXTERNAL_ID_TOO_OLD`, `ERR_MEASURE_OUTSIDE_VALIDITY`).

So, for example, a referral filed by a guardian for the wrong student surfaces as `ERR_GUARDIAN_MISMATCH` even if the referral window has also closed, because ownership outranks temporal checks; and a publish carrying a stale `expected_cycle_version` on a profile that is not even in `DRAFT` surfaces as `ERR_STALE_VERSION`, because the concurrency check (priority 6) runs ahead of the profile-state check (priority 7).

The request-shape tier (priority 5) covers, across the mutation endpoints: percentiles between 1.0 and 99.9 inclusive with one decimal place; growth percentiles between 0.0 and 100.0 inclusive with one decimal place; `service_rating` between 1 and 4 inclusive; `teacher_rating` between 1 and 5 inclusive; site capacities at least 0; the cycle's `screening_open_on` strictly earlier than `screening_close_on`; `referral_close_on` no later than `screening_close_on`; the four profile weights summing to 1.0 within a tolerance of 0.0001; the cut-band sanity trio (`review_band_floor` strictly below `cut_score`; `review_band_floor_2e` strictly below `cut_score_2e`; `cut_score_2e` no greater than `cut_score`); pathway-conditional field presence described in §3.2; and `administered_on` never in the future.

### 2.6. Optimistic Concurrency on Profile Publish

Exactly one endpoint takes a concurrency token. Publishing a cut-score profile requires the request to carry `expected_cycle_version`, set to the `version` of the parent `ScreeningCycle` as the client last observed it. If another writer has advanced the cycle's version since that read — which happens precisely when a competing publish succeeded, because every publish bumps the cycle's `version` by one — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from unknowingly superseding a profile it never saw. No other endpoint takes a version field; all other mutations serialize on state preconditions alone.

### 2.7. Precision and Rounding

All monetary-free quantitative rules in this domain share one rounding convention: **round half up**. Composite-score work uses two decimal places for per-measure contributions and zero decimal places (a whole integer) for the final composite. The re-evaluation exit score uses one decimal place. Disproportionality reporting uses four decimal places for identification rates and three decimal places for risk ratios, with comparisons evaluated against the rounded values. The order of rounding is part of the specification wherever §3 says it is — in particular, the composite score rounds each measure's contribution first and then rounds the sum of those rounded contributions, which can differ from rounding the unrounded sum; the per-line order is the only correct one.

### 2.8. Derived Counters and Synchronous Reconciliation

The platform maintains three families of derived values, all refreshed synchronously inside the same request that mutates their inputs — there is no eventual consistency. Site occupancy counters (`pull_out_occupied`, `cluster_occupied`, `acceleration_occupied`) count `ACTIVE` placements per site and service model. Review tallies (`qualify_votes`, `deny_votes`, `abstain_votes`) count cast votes per verdict. Student coordination flags (`has_active_sped_plan`, `gifted_status`) reflect the existence of special-education plans and the latest case/placement decisions. Reads always observe the reconciled value.

## 3. Business Logic & Workflows

### 3.1. Sites, Students, and Special-Education Coordination

A district begins by registering its school sites. A `GiftedCoordinator` creates each `SchoolSite` with a display `name`, a district-unique `code`, and three seat caps: `pull_out_capacity`, `cluster_capacity`, and `acceleration_capacity`, each an integer of at least 0. The site also exposes three computed counters — `pull_out_occupied`, `cluster_occupied`, `acceleration_occupied` — which count how many `ACTIVE` placements the site currently holds per model; §3.6 defines when these move.

Student enrollment is likewise coordinator-run. Each `Student` is enrolled with a district-unique `student_number`, a `legal_name`, a `grade_level` from 0 (kindergarten) through 12 inclusive, the `school_site_id` of the enrollment site, a `demographic_group` drawn from `AMERICAN_INDIAN`, `ASIAN`, `BLACK`, `HISPANIC`, `WHITE`, `MULTIRACIAL`, or `PACIFIC_ISLER` — spelled exactly `PACIFIC_ISLANDER` — plus the `primary_guardian_user_id` of the guardian authorized to act for the child, and an optional `is_ell` flag defaulting to false. The student's `gifted_status` starts at `NOT_IDENTIFIED` and is only ever flipped by the workflows in §3.3, §3.4, and §3.6. For roster seeding ahead of disproportionality reporting, a coordinator may instead bulk-enroll `count` students sharing one `school_site_id`, `grade_level`, and `demographic_group`; the server mints their `student_number` values, leaves `primary_guardian_user_id` null on the bulk rows, and returns `created_count` alongside the minted `student_ids`. Both individual and bulk creation produce rows in `DRAFT`-less, immediately usable state — students have no lifecycle of their own beyond `gifted_status`.

Twice-exceptional students — gifted learners with a disability — are coordinated through a special-education record. A `SpecialEdCoordinator` registers a `SpedPlan` for a student by supplying a `plan_type` of `IEP` or `PLAN_504` and a `started_on` date; the record's `student_id` comes from the path. At most one plan may exist per student — a second registration is refused with `ERR_DUPLICATE_SPED_PLAN` — and the record is immutable once written. Registering the plan sets the student's `has_active_sped_plan` flag to true, and that single boolean is what later steers the case's scoring variant (§3.3): the scoring pipeline reads the flag at finalize time, not at case-creation time, so a plan registered mid-cycle still changes how the case is cut.

### 3.2. Screening Cycles and Cut-Score Profiles

Work is organized into screening cycles. A `GiftedCoordinator` creates a `ScreeningCycle` with a `name` (say, "Fall 2026 Elementary Sweep"), a `school_year` label, a `grade_band` of `ELEMENTARY` (grades 0–5), `MIDDLE` (6–8), or `HIGH` (9–12), and three dates: `screening_open_on`, `screening_close_on`, and `referral_close_on`. The screening window is a half-open interval — it includes the open date and excludes the close date — and within the same grade band, two cycles' screening windows must not overlap, though adjacency (one closing the day another opens) is allowed; a clashing create is rejected with `ERR_CYCLE_WINDOW_OVERLAP`. The referral deadline `referral_close_on` must fall no later than `screening_close_on`.

A cycle walks a one-way pipeline: `DRAFT` → `OPEN` → `SCORING` → `REVIEW` → `FINALIZED`, the last being terminal. A coordinator advances it by naming a `target_state`, and the target must be the immediate successor of the current state — any skip, reversal, or advance from `FINALIZED` fails with `ERR_INVALID_CYCLE_STATE`. Two gates guard the pipeline: leaving `DRAFT` for `OPEN` requires that a cut-score profile already be published for the cycle (otherwise `ERR_NO_PUBLISHED_PROFILE`), and leaving `REVIEW` for `FINALIZED` requires that no case in the cycle still sits in `SCREENING`, `AWAITING_COMMITTEE`, or `APPEAL_PENDING` (otherwise `ERR_CYCLE_HAS_OPEN_CASES`).

The identification rubric lives on `CutScoreProfile` rows scoped to a cycle. A coordinator creates one — while the cycle is still `DRAFT` or `OPEN`, never later — supplying a `label`; four weights, `ability_weight`, `achievement_weight`, `rating_weight`, and `portfolio_weight`, which must sum to 1.0 within a tolerance of 0.0001; the standard thresholds `cut_score` (0 through 100 inclusive) and `review_band_floor`; the twice-exceptional thresholds `cut_score_2e` and `review_band_floor_2e`; and optionally `measure_validity_days`, which defaults to 730 — the maximum age, in days, of a usable measure score. Profiles themselves carry a three-state lifecycle: `DRAFT` → `PUBLISHED` → `SUPERSEDED`.

Publishing is the moment a profile becomes law. A coordinator publishes a profile that is still in `DRAFT` — publishing a profile in any other state fails with `ERR_PROFILE_NOT_DRAFT` — and only while the parent cycle is `DRAFT` or `OPEN` (past that, `ERR_INVALID_CYCLE_STATE`). The publish request must carry `expected_cycle_version` per §2.6; a stale token is rejected with `ERR_STALE_VERSION` (HTTP 412). On success, three things happen atomically: the profile moves `DRAFT` → `PUBLISHED`; whatever profile of the same cycle was previously `PUBLISHED` (if any) moves to `SUPERSEDED`; and the cycle's `published_profile_id` pointer is rewritten to the newly published profile's id while the cycle's `version` increments by one. That pointer — null until the first publish — is what later tells the scoring engine which thresholds are in force. The supersession of the prior profile is automatic and needs no call of its own.

### 3.3. Case Intake: Three Pathways Into Screening

An identification case ties one student to one cycle. At most one `GiftedCase` may exist per (`student_id`, `cycle_id`) pair — a duplicate create is rejected with `ERR_DUPLICATE_CASE` — and the student's `grade_level` must fall inside the cycle's `grade_band` (else `ERR_GRADE_BAND_MISMATCH`). Case intake requires the cycle to be `OPEN`; attempting it in any other cycle state fails with `ERR_CYCLE_NOT_OPEN`.

The `pathway` field selects one of three routes, each with its own conditional fields — mixing them is a shape violation (`ERR_INVALID_REQUEST`):

- `UNIVERSAL_SCREEN` — coordinator-run batch intake from district-wide screening. Neither `referral_source` nor the external fields may be present. Only a `GiftedCoordinator` opens these.
- `REFERRAL` — a teacher or parent nomination. `referral_source` is required and must be `TEACHER`, `PARENT`, or `SELF`; the external fields are forbidden. A `ReferringEducator` files with `referral_source` `TEACHER`; a `ParentGuardian` files with `referral_source` `PARENT`; coordinators may file any referral. The caller's `X-User-ID` is captured as the case's `referrer_user_id` — null on the other two pathways — and later drives the committee's conflict-of-interest bar (§3.4). A referral filed after the cycle's `referral_close_on` is rejected with `ERR_REFERRAL_WINDOW_CLOSED`.
- `TRANSFER_HONOR` — the district honors an identification already made elsewhere. `external_district_name` and `external_identified_on` are required and `referral_source` is forbidden. Two freshness windows apply, both checked against today: the student record must be at most 45 days old — filing later fails with `ERR_TRANSFER_WINDOW_LAPSED` — and the external identification must be no more than 730 days old, else `ERR_EXTERNAL_ID_TOO_OLD`. A transfer case that passes these checks lands **directly in `IDENTIFIED`** at creation: `decided_on` is set to today and the student's `gifted_status` flips to `IDENTIFIED` in the same atomic create.

Universal-screen and referral cases start in `SCREENING` and wait for evidence. The case lifecycle is: `SCREENING` → `IDENTIFIED`, `AWAITING_COMMITTEE`, or `NOT_IDENTIFIED`; `AWAITING_COMMITTEE` → `IDENTIFIED` or `NOT_IDENTIFIED`; `NOT_IDENTIFIED` → `APPEAL_PENDING` → `IDENTIFIED` or back to `NOT_IDENTIFIED`. `NOT_IDENTIFIED` after an appeal has been consumed is de facto terminal — a case gets at most one appeal, tracked by `appeal_used`, which starts false.

### 3.4. Measure Scores, Composite Scoring, and Cut Determination

While a case is in `SCREENING` and its cycle is `OPEN` or `SCORING` (any other cycle state — `ERR_INVALID_CYCLE_STATE`; a case no longer in `SCREENING` — `ERR_INVALID_CASE_STATE`), a `GiftedCoordinator` enters `MeasureScore` rows: each row's `case_id` comes from the path of the request, and the body carries a `measure_type` of `ABILITY`, `ACHIEVEMENT`, `RATING_SCALE`, or `PORTFOLIO`; a `percentile` between 1.0 and 99.9 inclusive with one decimal place; and an `administered_on` date. Each case holds at most one score per measure type — a repeat type is refused with `ERR_DUPLICATE_MEASURE`. The administration date must not be in the future (`ERR_INVALID_REQUEST`), and it must be no older than the cycle profile's `measure_validity_days` counted back from today — a stale score is rejected with `ERR_MEASURE_OUTSIDE_VALIDITY`, and this freshness check runs **both at entry and again at finalize**, so a score that was fresh when entered can still sink the finalize if the clock has since moved past its validity.

Finalize-scoring is the coordinator action that turns evidence into a decision; it requires the cycle in `SCORING` and the case in `SCREENING`. The engine first establishes which profile governs — the cycle's currently `PUBLISHED` profile — and which measures are present. The required set is `ABILITY`, `ACHIEVEMENT`, and `RATING_SCALE`; if any of the three is missing, the finalize fails with `ERR_INCOMPLETE_MEASURES`. `PORTFOLIO` is optional, and its absence shrinks the normalization base rather than failing the case.

The **composite score** is then computed with a pinned rounding order. Let the effective weight of each present measure be its profile weight divided by the sum of the profile weights over the present measures — with `PORTFOLIO` absent, that sum is less than 1.0, so the remaining weights renormalize upward. The scoring variant is `TWICE_EXCEPTIONAL` when the student's `has_active_sped_plan` is true at finalize time, else `STANDARD`, and is stored on the case as `scored_variant`. Under the twice-exceptional variant only, the effective ability percentile and the effective achievement percentile both become the larger of the two raw percentiles — recognition that a disability can suppress either instrument — while every other effective percentile equals its raw value. Each present measure's `weighted_contribution` is then its effective percentile multiplied by its normalized weight, rounded half-up to two decimal places, and stored on the `MeasureScore` row. The case's `composite_score` is the sum of those rounded per-measure contributions, itself rounded half-up to a whole integer.

Routing follows the freshly computed integer composite, compared against the variant-appropriate thresholds — `cut_score_2e` and `review_band_floor_2e` for `TWICE_EXCEPTIONAL`, `cut_score` and `review_band_floor` for `STANDARD`:

- Composite at or above the cut — equality identifies — routes `SCREENING` → `IDENTIFIED`: `decided_on` becomes today and the student's `gifted_status` becomes `IDENTIFIED`.
- Composite at or above the review-band floor but below the cut — equality enters review — routes `SCREENING` → `AWAITING_COMMITTEE`, storing `composite_score` and `scored_variant`.
- Composite below the floor routes `SCREENING` → `NOT_IDENTIFIED`, with `decided_on` set to today.

### 3.5. Committee Review and Appeals

Cases in `AWAITING_COMMITTEE` wait on a portfolio committee, and denied cases get one appeal. A `CommitteeReview` is opened against a case with a `review_kind` and an optional free-text `grounds`; the review starts in `VOTING` with `outcome` null and all three tallies (`qualify_votes`, `deny_votes`, `abstain_votes`) at zero. At most one non-`DECIDED` review may exist per case at a time — opening a second is refused with `ERR_REVIEW_ALREADY_OPEN`.

The two kinds serve different doors, and the role gate is conditional on `review_kind`. A `BAND_REVIEW` may be opened only by a `GiftedCoordinator`, and only while the case is `AWAITING_COMMITTEE` (else `ERR_INVALID_CASE_STATE`) and the cycle is `REVIEW` (else `ERR_INVALID_CYCLE_STATE`). An `APPEAL` may be opened only by a `ParentGuardian` or `ReferringEducator` — a coordinator may not file an appeal — and carries four preconditions: the case is `NOT_IDENTIFIED` with `appeal_used` still false (else `ERR_INVALID_CASE_STATE`); the cycle is `REVIEW`; the filing date is within 30 days of the case's `decided_on` (a later filing fails with `ERR_APPEAL_WINDOW_CLOSED`); and when the filer is a `ParentGuardian`, the caller's `X-User-ID` must equal the student's `primary_guardian_user_id` (else `ERR_GUARDIAN_MISMATCH`). Opening the appeal atomically sets `appeal_used` to true and moves the case `NOT_IDENTIFIED` → `APPEAL_PENDING`.

Voting is the `CommitteeMember` role's exclusive act: the member supplies a `verdict` of `QUALIFY`, `DENY`, or `ABSTAIN`, and the server records the caller's `X-User-ID` as `member_user_id` alongside the vote's `review_id`. Two guards protect the ballot box: one vote per member per review (a repeat is refused with `ERR_DUPLICATE_VOTE`), and a conflict-of-interest bar — the member's `X-User-ID` must not equal the case's `referrer_user_id`, so the educator who referred the student cannot vote on that student's review (`ERR_COMMITTEE_CONFLICT_OF_INTEREST`). Votes may be cast only while the review is `VOTING`; a vote on a decided review fails with `ERR_INVALID_REVIEW_STATE`.

A committee seats three. The review decides automatically the moment a threshold locks: as soon as `qualify_votes` reaches 2 the review is `DECIDED` with `outcome` `QUALIFY` — the third vote is moot and can no longer be cast — and as soon as `deny_votes` reaches 2 it is `DECIDED` with `outcome` `DENY`. If all three seats have voted without either threshold locking (a 1-1-1 split), the review is `DECIDED` with `outcome` `DENY`: no majority defaults to denial. A `GiftedCoordinator` may also force-decide a review still in `VOTING` from the votes cast so far, applying the same thresholds — and again, no majority among the cast votes means `DENY`; concluding a review not in `VOTING` fails with `ERR_INVALID_REVIEW_STATE`. Either way, decision writes `decided_on` as today.

The case cascade follows the review's kind and outcome. A `BAND_REVIEW` qualifying moves the case `AWAITING_COMMITTEE` → `IDENTIFIED`; denying moves it to `NOT_IDENTIFIED`. An `APPEAL` qualifying moves the case `APPEAL_PENDING` → `IDENTIFIED`; denying returns it to `NOT_IDENTIFIED` — now with `appeal_used` consumed, hence terminal. In every decide, the case's `decided_on` is overwritten with the review's `decided_on`, and on every qualifying decide the student's `gifted_status` becomes `IDENTIFIED`.

### 3.6. Service Placement: Offers, Seats, Waitlists, and Exits

Identification entitles a student to an offer of service. A `GiftedCoordinator` offers a `ServicePlacement` against an `IDENTIFIED` case — offering against any other case state fails with `ERR_INVALID_CASE_STATE` — supplying a `site_id` (which must exist, else `ERR_NOT_FOUND`), a `service_model` of `PULL_OUT`, `CLUSTER`, or `ACCELERATION`, and a `start_on` date. The placement denormalizes the case's `student_id` at creation, and that copy drives a hard rule: one student may never hold two placements whose service periods overlap — an open-ended placement (its `end_on` still null) is treated as extending to infinity — and a clashing offer is rejected with `ERR_PLACEMENT_PERIOD_OVERLAP`. The new placement enters `OFFERED` with `offered_on` set to today and `accept_by` set to 30 days after `offered_on`. Crucially, an offer holds no seat: seats are consumed by `ACTIVE` placements only.

The placement lifecycle is: `OFFERED` → `ACTIVE`, `WAITLISTED`, `DECLINED`, or `EXPIRED`; `WAITLISTED` → `OFFERED` (promotion) or `DECLINED`; `ACTIVE` → `EXITED`. `DECLINED`, `EXPIRED`, and `EXITED` are terminal.

A `ParentGuardian` answers the offer, and only the student's own guardian — the caller's `X-User-ID` must match the student's `primary_guardian_user_id`, else `ERR_GUARDIAN_MISMATCH`. Acceptance while the offer is `OFFERED` branches on seat availability, and this branch is **not an error path**: if the site's occupancy for the placement's model is strictly below that model's capacity, the placement becomes `ACTIVE` and the site's occupied counter for that model increments by one; if occupancy has already reached capacity, the placement instead becomes `WAITLISTED`, with `waitlisted_at` stamped to the current logical clock timestamp. Accepting a placement not in `OFFERED` fails with `ERR_INVALID_PLACEMENT_STATE`. The invariant at every site and model is that occupancy never goes below 0 or above capacity. Declining works from either `OFFERED` or `WAITLISTED` and lands in `DECLINED`; from the waitlist it also nulls `waitlisted_at`. Because neither state holds a seat, declining releases nothing and triggers no waitlist promotion.

Offers age out on the clock. When the logical clock is set past a placement's `accept_by` — accept is allowed while today is no later than `accept_by` — the placement moves `OFFERED` → `EXPIRED` automatically as part of the clock-set sweep; again, no seat was held, so no promotion runs.

Exits release seats, and released seats feed the waitlist. An `ACTIVE` placement exits in two ways: a withdrawal, which a `GiftedCoordinator` may always perform and a `ParentGuardian` may perform for their own student (guardian mismatch — `ERR_GUARDIAN_MISMATCH`; placement not `ACTIVE` — `ERR_INVALID_PLACEMENT_STATE`); or an exit outcome from a re-evaluation (§3.7). Either way the exit stamps `end_on` as today, flips the student's `gifted_status` to `EXITED`, decrements the site's occupied counter for the model by one, and then runs waitlist promotion for that site-and-model pair. Promotion takes the `WAITLISTED` placements at the pair, orders them by `waitlisted_at` ascending with `created_at` ascending as the tie-break — never by entity id — and promotes exactly one, the head of the queue, per released seat: it re-enters `OFFERED` with `offered_on` set to today, a fresh `accept_by` of today plus 30 days, and `waitlisted_at` nulled. The promoted placement consumes a seat only when it is later accepted; if the waitlist is empty, promotion is a no-op rather than an error.

### 3.7. Annual Re-Evaluation and Exit Criteria

Gifted service is not a lifetime appointment. A `GiftedCoordinator` schedules an annual `ReEvaluation` against an `ACTIVE` placement (a placement in any other state — `ERR_INVALID_PLACEMENT_STATE`); the new record's `placement_id` is taken from the path, and the body supplies the `due_on` date; at most one non-`CONCLUDED` re-evaluation may exist per placement — a second open one is refused with `ERR_REEVAL_ALREADY_OPEN`. The record starts `SCHEDULED`, and when the logical clock is set to a date on or after `due_on`, the clock-set sweep moves it `SCHEDULED` → `IN_REVIEW` automatically.

Concluding is a coordinator act requiring the record in `IN_REVIEW` — otherwise `ERR_REEVAL_NOT_IN_REVIEW`. The coordinator submits three scores gathered during the review: `growth_percentile` (0.0 through 100.0 inclusive, one decimal place), `service_rating` (1 through 4 inclusive), and `teacher_rating` (1 through 5 inclusive), together with the committee-of-one's `outcome`. The server computes the **exit score** as follows: multiply `growth_percentile` by 0.5, multiply `service_rating` by 7.5, multiply `teacher_rating` by 4.0, sum the three products, and round half-up to one decimal place; that value is stored as `exit_score`. The band is then: an exit score of 70.0 or higher means `RETAINED`; an exit score of 50.0 or higher but below 70.0 means `PROBATION` — exactly 50.0 is `PROBATION`; below 50.0 means `EXITED`. One state-dependent override applies: if the banded outcome is `PROBATION` but the placement's `is_on_probation` flag is already true — a second consecutive probation — the effective outcome is `EXITED` instead.

The submitted `outcome` must equal the computed effective outcome exactly; a disagreement is rejected with `ERR_REEVAL_OUTCOME_MISMATCH` (HTTP 422), and nothing is written. On a matching conclude, `exit_score`, `outcome`, and `concluded_on` (today) are stored, and the cascade depends on the outcome. `RETAINED` does nothing further — the placement stays `ACTIVE`. `PROBATION` sets the placement's `is_on_probation` to true while it stays `ACTIVE`. `EXITED` runs the full exit cascade of §3.6 in the same request: the placement moves `ACTIVE` → `EXITED` with `end_on` set to today, the student's `gifted_status` becomes `EXITED`, the site's occupied counter for the model decrements by one, and waitlist promotion runs for the site-and-model pair.

### 3.8. Disproportionality Monitoring and Reporting

Federal compliance requires the district to watch who gets identified. A computed report — a read-only projection over the roster and the cycle's cases, never persisted — is available per cycle with a `variant` query parameter selecting `INTERIM` (the default) or `FINAL`. Availability is state-gated: `INTERIM` requires the cycle in `REVIEW` or `FINALIZED`, while `FINAL` is allowed only once the cycle is `FINALIZED`; asking earlier fails with `ERR_INVALID_CYCLE_STATE`.

The report scopes the student roster to the cycle's `grade_band` across all sites, then works per demographic group. For each group g, `enrolled_g` counts in-scope students whose `demographic_group` is g; groups with zero enrolled students are omitted from `group_metrics` entirely. The identified count differs by variant: `FINAL` counts students with a case in this cycle in `IDENTIFIED` status — the audit view — while `INTERIM` additionally counts `AWAITING_COMMITTEE` and `APPEAL_PENDING`, a forward-looking projection of the pipeline. Each group's identification rate is its identified count divided by its enrolled count, rounded half-up to four decimal places. The **reference group** is the group with the largest enrolled count, ties broken by `demographic_group` name ascending. Each group's risk ratio is its rounded rate divided by the reference group's rounded rate, rounded half-up to three decimal places; if the reference group's rate is zero, all ratios are null and no group is flagged. A group is flagged `UNDER_REPRESENTED` when its rounded ratio is strictly below 0.800 **and** its enrolled count is at least 10 — a ratio of exactly 0.800 is not flagged, and small cells below 10 enrolled students never flag regardless of ratio. The response carries `cycle_id`, the `variant`, the `reference_group`, the `total_identified` summed across groups, the per-group `group_metrics`, and the `flagged_groups` list. Each `group_metrics` entry carries `demographic_group`, `enrolled`, `identified`, `identification_rate`, `risk_ratio`, and a boolean `flagged`.

## 4. Endpoint Definitions

All endpoints are mounted under `/gifted`. Resource-creating operations (`POST` that mints a new resource) return HTTP 201; operations that modify, transition, or compute against an existing resource return HTTP 200; the clock-set operation returns 200. Every list endpoint accepts `limit` and `offset` per §2.3, and several accept the filter parameters shown in §3; the table below names parameters only where the narrative has not already introduced them.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/gifted/_clock/set_current_utc` | Set the logical clock (startup default `2026-08-01T00:00:00Z`); runs the re-evaluation activation and offer-expiry sweeps | GiftedCoordinator |
| POST | `/gifted/school-sites` | Create a school site with per-model seat capacities | GiftedCoordinator |
| GET | `/gifted/school-sites/{id}` | Get one site including its computed occupied counters | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| GET | `/gifted/school-sites/{id}/students` | List students enrolled at a site; filterable by `demographic_group`, `gifted_status` | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| GET | `/gifted/school-sites/{id}/placements` | List placements at a site; filterable by `service_model`, `status` | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/students` | Enroll one student | GiftedCoordinator |
| POST | `/gifted/students/bulk-enroll` | Bulk-enroll `count` students sharing site/grade/demographic group; server mints student numbers, guardian null | GiftedCoordinator |
| GET | `/gifted/students/{id}` | Get one student including computed `has_active_sped_plan` | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/students/{id}/sped-plans` | Register an IEP/504 plan (twice-exceptional coordination); at most one per student | SpecialEdCoordinator |
| GET | `/gifted/students/{id}/sped-plans` | List a student's special-education plans | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/screening-cycles` | Create a screening cycle; same-band half-open windows must not overlap (adjacency allowed) | GiftedCoordinator |
| GET | `/gifted/screening-cycles/{id}` | Get one cycle including `published_profile_id` and OCC `version` | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/screening-cycles/{id}/advance` | Advance the cycle pipeline `DRAFT` → `OPEN` → `SCORING` → `REVIEW` → `FINALIZED`; target must be the immediate successor | GiftedCoordinator |
| POST | `/gifted/screening-cycles/{id}/cut-score-profiles` | Create a `DRAFT` cut-score profile (multi-criteria matrix); cycle must be `DRAFT` or `OPEN` | GiftedCoordinator |
| GET | `/gifted/screening-cycles/{id}/cut-score-profiles` | List profiles of a cycle; filterable by `status` | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/cut-score-profiles/{id}/publish` | Publish a `DRAFT` profile (OCC-guarded on the parent cycle version); supersedes the previously `PUBLISHED` profile | GiftedCoordinator |
| POST | `/gifted/cases` | Open an identification case (cycle must be `OPEN`); `TRANSFER_HONOR` cases land directly in `IDENTIFIED` | GiftedCoordinator, ReferringEducator, ParentGuardian |
| GET | `/gifted/cases` | List cases; filterable by `student_id`, `cycle_id`, `status`, `pathway` | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| GET | `/gifted/cases/{id}` | Get one case including `composite_score` and `scored_variant` | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/cases/{id}/measure-scores` | Enter one measure score (case `SCREENING`; cycle `OPEN` or `SCORING`; one score per measure type) | GiftedCoordinator |
| GET | `/gifted/cases/{id}/measure-scores` | List a case's measure scores | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/cases/{id}/finalize-scoring` | Compute the composite (pinned per-measure rounding), determine the variant, and route the case; cycle must be `SCORING` | GiftedCoordinator |
| POST | `/gifted/cases/{id}/committee-reviews` | Open a committee review (`BAND_REVIEW` coordinator-only on `AWAITING_COMMITTEE`; `APPEAL` guardian/educator-only on denied cases) | GiftedCoordinator, ParentGuardian, ReferringEducator |
| GET | `/gifted/cases/{id}/committee-reviews` | List reviews of a case | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| GET | `/gifted/committee-reviews/{id}` | Get one review including vote tallies and outcome | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/committee-reviews/{id}/votes` | Cast a committee vote (one per member; referrers barred); the threshold-locking vote auto-decides | CommitteeMember |
| GET | `/gifted/committee-reviews/{id}/votes` | List votes of a review | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/committee-reviews/{id}/conclude` | Force-decide a `VOTING` review from the votes cast so far; no majority means `DENY` | GiftedCoordinator |
| POST | `/gifted/cases/{id}/placements` | Offer a service placement (case must be `IDENTIFIED`); per-student service periods must not overlap | GiftedCoordinator |
| GET | `/gifted/placements/{id}` | Get one placement | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| GET | `/gifted/cases/{id}/placements` | List placements of a case | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/placements/{id}/accept` | Guardian accepts an offer: `ACTIVE` when a seat is free, `WAITLISTED` when full | ParentGuardian |
| POST | `/gifted/placements/{id}/decline` | Guardian declines an `OFFERED` or `WAITLISTED` placement (no seat held, no promotion) | ParentGuardian |
| POST | `/gifted/placements/{id}/withdraw` | Withdraw an `ACTIVE` placement (coordinator or own guardian); releases the seat and runs waitlist promotion | GiftedCoordinator, ParentGuardian |
| POST | `/gifted/placements/{id}/re-evaluations` | Schedule the annual re-evaluation (placement must be `ACTIVE`; at most one open per placement) | GiftedCoordinator |
| GET | `/gifted/placements/{id}/re-evaluations` | List re-evaluations of a placement | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |
| POST | `/gifted/re-evaluations/{id}/conclude` | Conclude an `IN_REVIEW` re-evaluation; submitted outcome must equal the computed effective outcome | GiftedCoordinator |
| GET | `/gifted/screening-cycles/{id}/disproportionality-report` | Computed disproportionality report; `variant=INTERIM` (default, requires `REVIEW` or `FINALIZED`) or `FINAL` (requires `FINALIZED`) | GiftedCoordinator, ReferringEducator, ParentGuardian, CommitteeMember, SpecialEdCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each code live in the §2 and §3 narratives where the guarded workflow is described; this table is the index of identifiers to HTTP statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_GUARDIAN_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_CYCLE_STATE | 409 |
| ERR_CYCLE_NOT_OPEN | 409 |
| ERR_NO_PUBLISHED_PROFILE | 409 |
| ERR_CYCLE_HAS_OPEN_CASES | 409 |
| ERR_CYCLE_WINDOW_OVERLAP | 409 |
| ERR_PROFILE_NOT_DRAFT | 409 |
| ERR_INVALID_CASE_STATE | 409 |
| ERR_DUPLICATE_CASE | 409 |
| ERR_GRADE_BAND_MISMATCH | 422 |
| ERR_TRANSFER_WINDOW_LAPSED | 422 |
| ERR_EXTERNAL_ID_TOO_OLD | 422 |
| ERR_REFERRAL_WINDOW_CLOSED | 422 |
| ERR_DUPLICATE_MEASURE | 409 |
| ERR_MEASURE_OUTSIDE_VALIDITY | 422 |
| ERR_INCOMPLETE_MEASURES | 422 |
| ERR_REVIEW_ALREADY_OPEN | 409 |
| ERR_INVALID_REVIEW_STATE | 409 |
| ERR_COMMITTEE_CONFLICT_OF_INTEREST | 403 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_APPEAL_WINDOW_CLOSED | 422 |
| ERR_PLACEMENT_PERIOD_OVERLAP | 409 |
| ERR_INVALID_PLACEMENT_STATE | 409 |
| ERR_REEVAL_ALREADY_OPEN | 409 |
| ERR_REEVAL_NOT_IN_REVIEW | 409 |
| ERR_REEVAL_OUTCOME_MISMATCH | 422 |
| ERR_DUPLICATE_SPED_PLAN | 409 |

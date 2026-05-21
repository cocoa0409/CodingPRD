# SSDI Disability Insurance API — Product Requirements Document

## 1. Introduction

The SSDI Disability Insurance API is the system of record for processing claims under the Social Security Disability Insurance program. It anchors a workflow that begins when a claimant alleges an onset of disability, weaves through the quarters-of-coverage (QC) insured-status test, the submission of medical evidence, an initial Disability Determination Services (DDS) decision, optional reconsideration, an Administrative Law Judge (ALJ) hearing, and — when warranted — review by the Appeals Council. After an allowance the system computes the worker's Primary Insurance Amount (PIA), the Family Maximum Benefit, retroactive back pay, the statutory five-month waiting period, and the diary cadence for the next Continuing Disability Review (CDR). Auxiliary benefits for qualifying children and an optional Supplemental Security Income (SSI) supplement co-exist with the worker's award and must remain mutually consistent at every transition.

Two pressures meet inside this API. On the one hand, the program is a strict compliance environment: a determination at reconsideration cannot be issued by the same examiner who issued the initial determination, an appeal posted after sixty days is too late, and a hearing slot cannot be double-booked against another claimant or against another hearing on the same ALJ's calendar. On the other hand, the program is genuinely cyclic — a remand from the Appeals Council pushes the application back to reconsideration with the segregation-of-duties bond still binding, and a CDR finding of medical improvement reaches all the way back to terminate child auxiliaries, recoup back pay through a compensating ledger entry, and re-derive any SSI supplement that had been suppressed by the worker's now-vanished DIB benefit.

This document specifies the JSON HTTP API a claimant, a DDS examiner, an ALJ, an Appeals Council member, a CDR reviewer, and a platform administrator each see. Its job is to remove every plausible source of ambiguity around the calculations, the state transitions, the validation order, the side-effect cascades, and the concurrency outcomes that the underlying program demands.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. A request missing or empty in either header is rejected with `ERR_AUTH_REQUIRED` and HTTP status 401. A request whose `X-User-Role` is not one of `Claimant`, `DDS_Examiner`, `ALJ`, `AppealsCouncil`, `CDR_Reviewer`, or `PlatformAdmin` is rejected with `ERR_INVALID_ROLE`, also at status 401. A request whose role is recognised but not permitted on the targeted endpoint is rejected with `ERR_FORBIDDEN` at status 403.

When `X-User-Role` is `Claimant`, the `X-User-ID` is the `id` of the acting `Claimant`; ownership checks on any resource that references a `Claimant` compare the resource's `claimant_id` to `X-User-ID`, and a mismatched claimant in the URL path also yields `ERR_FORBIDDEN`. When `X-User-Role` is any of `DDS_Examiner`, `ALJ`, `AppealsCouncil`, `CDR_Reviewer`, or `PlatformAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `last_initial_examiner_id` on `Application` when a DDS examiner posts an initial determination, or as `examiner_id` on the immutable `Determination` ledger entry) but it never compares such an identifier to any entity's `id`.

The six roles serve distinct responsibilities. A `Claimant` registers themselves, files quarter credits, submits medical evidence, drafts and submits an application, and may file an appeal after a denial. A `DDS_Examiner` accepts or rejects medical evidence and issues determinations at the `INITIAL` and `RECONSIDERATION` levels. An `ALJ` manages hearing slots — creation, booking, marking held, no-show, and rescheduling — and issues determinations at the `ALJ` level. The `AppealsCouncil` issues determinations at the `APPEALS_COUNCIL` level and may either deny outright or remand the case back to reconsideration. A `CDR_Reviewer` schedules and completes periodic Continuing Disability Reviews. A `PlatformAdmin` holds operator-level capabilities including the test-driving clock-advance endpoint described in §2.10.

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

Every list endpoint accepts two optional query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0 and it must be zero or greater. Either parameter outside its permitted range produces `ERR_INVALID_PAGINATION` at HTTP status 422. List responses always sort by `created_at` ascending. The pagination fields `limit`, `offset`, `total_count`, and `has_more` are surfaced inside the `meta` object alongside the standard `api_request_id` and `api_request_timestamp`.

### 2.4. Common Resource Properties and Versioning

Every server-minted resource carries an `id` that is a UUID with no type prefix and a `created_at` timestamp formatted as ISO 8601 UTC with three fractional seconds. Resources whose specification declares common fields additionally carry `updated_at` (also ISO 8601 UTC with three fractional digits) and an integer `version`. The `Claimant`, `MedicalEvidence`, `Application`, `HearingSlot`, `ChildAuxiliary`, `SSISupplement`, and `CDRReview` entities all carry the full common-field complement.

Two entities are ledger-style and intentionally immutable after creation: `QuarterCredit` and `Determination`. They carry only `id` and `created_at` — `updated_at` and `version` are absent. A `QuarterCredit` row cannot be edited or deleted; if a year-quarter pair must be corrected, a new row is appended and the aggregation rules will reconcile the totals. A `Determination` row is an append-only record of an adjudication event and is similarly immutable.

`version` begins at 1 when a versioned resource is first created and increments by one on every server-side mutation, whether the mutation was driven by a direct PATCH or by a side-effect cascade (for example, a new entitled child auxiliary that forces a recomputation of the parent's `family_max_cents` bumps the worker `Application.version`, and every sibling `ChildAuxiliary.version` whose `monthly_benefit_cents` was redistributed). Every mutation also refreshes `updated_at`.

### 2.5. Optimistic Concurrency Control

Mutating endpoints that take a request body — primarily the PATCH endpoints on `Claimant` and `SSISupplement` — accept an optional `version` field. When the caller supplies `version`, the server compares it to the stored value before mutating; if they differ, the request is rejected with `ERR_VERSION_MISMATCH` at HTTP status 409. Omitting `version` from the body skips this check and applies the mutation against whatever the current stored version happens to be. The `version` integer increments by one on every accepted mutation and is the same field surfaced in the response envelope's `data` payload as part of the resource.

### 2.6. Hierarchical Consistency and Cascades

Many of this domain's mutations touch more than one entity. The system's contract is that every primary transition completes all of its declared side effects within the same logical operation, refreshing `updated_at` and bumping `version` on every resource that was mutated. The downstream consequences are most visible at three places. First, the approval cascade: when an `Application` enters `APPROVED` (from any of `INITIAL_REVIEW`, `RECONSIDERATION`, or `ALJ_PENDING`), the system computes `pia_cents`, `aime_cents`, `family_max_cents`, `monthly_benefit_cents`, `entitlement_date`, `back_pay_cents`, `approval_date`, `cdr_diary`, and `next_cdr_due_date`, appends a `Determination` row, stamps `last_initial_examiner_id` with the acting examiner, and auto-creates a single `CDRReview` row with status `PENDING` whose `review_due_date` equals `next_cdr_due_date`. Second, the cessation cascade documented in §3.7 from `APPROVED` to `CLOSED_DENIED`. Third, the family-max waterfall, which recomputes every `monthly_benefit_cents` across both the worker and the sibling `ChildAuxiliary` rows whenever an auxiliary is entitled or terminated.

### 2.7. Path Parameter Validation Order

Many endpoints are nested under `/claimants/{claimantId}/...`. Path parameters are validated from left to right. A missing `Claimant` yields `ERR_CLAIMANT_NOT_FOUND` at HTTP status 404. A missing `Application` referenced inside an existing claimant's path, or one belonging to a different claimant, yields `ERR_APPLICATION_NOT_FOUND` at status 404. Any other referenced resource — `MedicalEvidence`, `QuarterCredit`, `HearingSlot`, `ChildAuxiliary`, `SSISupplement`, `CDRReview`, or a determination identifier — that cannot be resolved yields the generic `ERR_RESOURCE_NOT_FOUND` at status 404.

### 2.8. Precision and Rounding

All monetary values are stored and exchanged as integer cents. PIA and the Family Maximum Benefit are rounded down to the nearest ten cents (the SSA "dime rule") after their bend-point arithmetic. Other monetary calculations — back pay, child auxiliary monthly benefits, SSI payment — use integer-cent arithmetic with explicit floor operations as specified in §3.3 and §3.5. Age in whole years is computed as the integer year difference between a reference date and the date of birth, with truncation (floor). Diary intervals are measured in whole calendar months, and the waiting period adheres to a "next-month" anchoring rule described in §3.3.

### 2.9. Validation Ordering Discipline

When more than one validation could fire for a single request, the server evaluates checks in the priority order described below, returning on the first failure. Authentication checks come first: the presence of `X-User-Role` and `X-User-ID`, then the role's membership in the recognised set, then the role's RBAC permission on the endpoint, and then — for the `Claimant` role only — the cross-claimant identity check against the URL path. Existence checks follow, in left-to-right path order: claimant existence, application existence within the claimant, and finally any other addressed resource. State validity follows: an operation on an entity that is not currently in a state permitting the requested transition is rejected with `ERR_INVALID_STATE` at HTTP status 409. After state validity come the domain-specific business checks (segregation of duties at reconsideration, hearing-slot conflicts, application-already-scheduled, appeal-window expiry, alleged-onset-after-filing, QC sufficiency, evidence sufficiency, child auxiliary eligibility, SSI resource limit, CDR not-due, hearing-not-reached, ALJ-determination-requires-held-hearing, optimistic-concurrency, pagination). The catch-all body-shape check — required fields present, types correct, enum values valid — is `ERR_BAD_REQUEST` at status 400 and is the lowest-priority structural validation; it fires only if no earlier domain rule has already rejected the request. In particular, this ordering means that an `ERR_FORBIDDEN` precedes `ERR_CLAIMANT_NOT_FOUND`, which precedes `ERR_INVALID_STATE`, which precedes `ERR_SEGREGATION_OF_DUTIES`, which precedes `ERR_APPEAL_WINDOW_EXPIRED`, which precedes the QC/evidence/child-eligibility/SSI/CDR/hearing temporal rules.

### 2.10. Logical Clock and Test-Driving Capability

Many of this domain's rules depend on wall-clock relations — appeal windows, CDR scheduling, hearing reachability — and the system therefore maintains a single logical "now" that callers can read but only a `PlatformAdmin` can move. An admin-only test-driving capability advances the logical clock to a supplied `to` instant; the clock is monotonically non-decreasing and never moves backward. Every temporal precondition described in §3 evaluates against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Claimant and Building the Quarters-of-Coverage Ledger

A claimant joins the system by registering with their legal name, date of birth, the date on which they are filing the initial SSDI claim, the date they allege their disability began, and the last four digits of their Social Security number (the four-digit string field that captures this is `ssn_last4`, which must match a four-digit numeric format). The system stores these on a new `Claimant` resource and immediately runs the QC requirement lookup, populating `qc_required` and `qc_recent_required` from the claimant's age at the alleged onset and pre-seeding `total_qc_earned`, `qc_recent_window`, and `insured_status` at zero / `NOT_INSURED`. The claimant's legal name is held in `full_name`; the dates are held in `date_of_birth`, `filing_date`, and `alleged_onset_date`. A patch against the claimant — which may update `full_name`, `alleged_onset_date`, or `version` — re-runs the QC requirement lookup whenever `alleged_onset_date` changes.

Two business constraints bind from the moment the claimant exists. The alleged onset of disability cannot postdate the filing of the claim: when a request would set `alleged_onset_date` to a value later than `filing_date` (whether at registration or via patch), it is rejected with `ERR_AOD_AFTER_FILING` at HTTP status 422. The claimant's `established_onset_date` remains null until the first allowance and may be set by the adjudicator to a date equal to or later than `alleged_onset_date`.

Each quarter of earnings is logged immutably as a `QuarterCredit` row, parented to the claimant. The row carries the parent `claimant_id`, the calendar `year` (which must lie between 1978 and 2100 inclusive), the integer `quarter` from 1 through 4, and the quarter's `earnings_cents` (non-negative). The server then computes `qc_count` for that quarter — 1 if `earnings_cents` for that quarter is greater than or equal to the per-year earnings threshold defined by `QC_EARNINGS_THRESHOLD_CENTS_BY_YEAR` (which sets `$1,730` per QC in 2024 and `$1,810` per QC in 2025), and 0 otherwise — and then computes `credited`, which is true when the (`year`, `quarter`) pair falls inside the lookback window ending at the claimant's `alleged_onset_date`. The aggregation never credits more than four quarters per year regardless of how many rows are inserted for that year. The list endpoint accepts optional `year_min` and `year_max` filters in addition to the standard `limit` and `offset` paging.

### 3.2. The Insured-Status Test

The insured-status calculation is the gate to initial review. It computes two separate QC requirements from the claimant's age at the alleged onset (the integer year difference, floored, between `alleged_onset_date` and `date_of_birth`):

- **Fully-insured requirement** stored in `qc_required`. If the claimant's age at alleged onset is less than 24, six lifetime QCs are required. If the age is at least 24 and at most 30, the requirement is two times the quantity (age minus 21) — so 24 yields six, 25 yields eight, 26 yields ten, and 30 yields eighteen. If the age is at least 31 and at most 42, the requirement is a flat twenty. If the age is at least 43 and at most 61, the requirement is twenty plus the difference (age minus 42), adding one QC per year above 42. If the age is 62 or greater, the requirement is forty.
- **Recent-work requirement** stored in `qc_recent_required` and measured against the count of credited quarters within a recent window ending at `alleged_onset_date`. If the claimant's age is less than 24, six QCs are required within the twelve-quarter window ending at the alleged onset. If the age is at least 24 and at most 30, the requirement is the ceiling of the quantity (age minus 21) times two, evaluated within a window of (age minus 21) times two quarters ending at the alleged onset. If the age is 31 or older, twenty QCs are required within a forty-quarter window ending at the alleged onset.

The total credited QCs are summed into `total_qc_earned` (with the four-per-year cap enforced at aggregation time) and the count within the recent window is recorded as `qc_recent_window`. `insured_status` is `INSURED` if and only if `total_qc_earned` is at least `qc_required` and `qc_recent_window` is at least `qc_recent_required`; otherwise it is `NOT_INSURED`. The system recomputes all of these whenever a `QuarterCredit` row is added or whenever the claimant's `alleged_onset_date` is patched.

### 3.3. Medical Evidence, Drafting, and Submission

Medical evidence is submitted by the claimant as a `MedicalEvidence` row, parented to the claimant. The `source_type` discriminates two shapes: a `LISTING_MATCH` carries a `listing_code` (for example, "1.15" for musculoskeletal disorders) and leaves `rfc_exertional_level`, `rfc_skill_level`, `age_category_at_decision`, and `education_level` null; an `RFC_ASSESSMENT` is the opposite — `listing_code` is null while `rfc_exertional_level` (one of `SEDENTARY`, `LIGHT`, `MEDIUM`, or `HEAVY`), `rfc_skill_level` (one of `UNSKILLED`, `SEMI_SKILLED`, or `SKILLED`), `age_category_at_decision` (one of `YOUNGER`, `CLOSELY_APPROACHING`, or `ADVANCED`), and `education_level` (one of `ILLITERATE`, `LIMITED`, or `HIGH_SCHOOL_OR_MORE`) must all be supplied. Every row also carries `medical_findings` — clinical free text of at least twenty characters — and an `evidence_date` that must be on or after the claimant's `alleged_onset_date` and on or before `filing_date` plus 730 days. A newly submitted row arrives in `status` `SUBMITTED`. A DDS examiner reviews it and either accepts it, transitioning `SUBMITTED` to `ACCEPTED`, or rejects it, transitioning `SUBMITTED` to `REJECTED`.

A new `Application` is created by the claimant against their claimant record and arrives in `DRAFT` status; the `claimant_id` is bound from the URL path and the row carries no other input fields at creation. Many of the application's interesting fields — `medical_decision`, `last_initial_examiner_id`, `pia_cents`, `aime_cents`, `family_max_cents`, `monthly_benefit_cents`, `entitlement_date`, `back_pay_cents`, `approval_date`, `next_cdr_due_date`, and `cdr_diary` — are computed by the workflow described below. Submitting the draft advances the application from `DRAFT` to `INITIAL_REVIEW` after three preconditions are evaluated in this order: the claimant's `insured_status` must be `INSURED` (otherwise `ERR_QC_INSUFFICIENT` at 422), at least one `MedicalEvidence` row for the claimant must have `status` `ACCEPTED` (otherwise `ERR_EVIDENCE_INSUFFICIENT` at 422), and the `alleged_onset_date` must be on or before `filing_date` (otherwise `ERR_AOD_AFTER_FILING` at 422 — the same rule that gates patches in §3.1). Submission also re-runs the QC requirement lookup so that the application carries the up-to-date QC figures.

### 3.4. Initial Determination and the Approval Cascade

A DDS examiner adjudicates an `INITIAL_REVIEW` application by appending a `Determination` row to the application's ledger. The body of the request supplies the determination's `level` (here `INITIAL`), the `decision` (one of `ALLOW`, `DENY`, or `REMAND`, though `REMAND` is valid only at `APPEALS_COUNCIL`), an optional `medical_basis` (one of `MEETS_LISTING`, `EQUALS_LISTING`, `DISABLED_BY_RFC`, `NOT_DISABLED`, or `NOT_REACHED`), an optional `established_onset_date`, and a free-text `rationale` of at least fifty characters. The server stamps the row with `application_id`, `examiner_id` (the calling `X-User-ID`), and `examiner_role` (here `DDS_Examiner`). The application's `medical_decision` field mirrors the medical basis of the most recent determination.

An `ALLOW` at `INITIAL_REVIEW` requires the determination's `medical_basis` to be one of `MEETS_LISTING`, `EQUALS_LISTING`, or `DISABLED_BY_RFC` (a determination whose `medical_basis` is `NOT_DISABLED` or `NOT_REACHED` cannot be an `ALLOW`). The application transitions from `INITIAL_REVIEW` to `APPROVED` and the approval cascade runs in this order:

1. `Application.established_onset_date` is set to the determination's `established_onset_date`.
2. `Application.entitlement_date` is set by the waiting-period rule of §3.3 below: if the established onset falls on the first day of a month, the anchor month is that month; otherwise the anchor month is the first day of the month following the established onset. The entitlement date is five whole calendar months past the anchor month — that is, the first day of the sixth full calendar month after the established onset. The constant that fixes this five-month interval is the statutory waiting period.
3. `Application.pia_cents` and `Application.aime_cents` are computed by the PIA bend-point formula described in §3.5, in its **provisional** variant: AIME is computed using the claimant's filed earnings record only, including the year-of-onset earnings truncated at the latest completed `QuarterCredit` (later partial quarters of that year are dropped).
4. `Application.family_max_cents` is computed by the Family Maximum bend-point formula described in §3.5.
5. `Application.monthly_benefit_cents` is set to `pia_cents` (pre-auxiliary, no proration yet).
6. `Application.back_pay_cents` is computed by the back-pay rule of §3.5 in its **provisional** variant: pre-filing retro months are capped at the lesser of twelve and the integer count of full calendar months between `filing_date` and `entitlement_date`. The examiner cannot extend further.
7. `Application.approval_date` is set to the logical clock's current instant, pinning the end of the back-pay window.
8. `Application.cdr_diary` and `Application.next_cdr_due_date` are set by the diary lookup of §3.5: if `medical_basis` is `MEETS_LISTING` and the `listing_code` of the most recent accepted evidence row begins with "1." or "11.", the diary is `MIP` and the diary interval is thirty-six months; if the medical basis is `MEETS_LISTING` but the listing code does not begin with "1." or "11.", the diary is `MINE` and the interval is eighty-four months; if the medical basis is `EQUALS_LISTING`, the diary is `MIE` and the interval is eighteen months; if the medical basis is `DISABLED_BY_RFC` and `age_category_at_decision` is `ADVANCED`, the diary is `MINE` and the interval is eighty-four months; if the medical basis is `DISABLED_BY_RFC` and the age category is anything else, the diary is `MIP` and the interval is thirty-six months. `next_cdr_due_date` is `approval_date` plus that many whole months.
9. `Application.last_initial_examiner_id` is set to the acting examiner's `X-User-ID`, binding the segregation-of-duties rule that §3.6 will enforce at reconsideration.
10. The new `Determination` row is appended with `level` `INITIAL` and `decision` `ALLOW`.
11. A single `CDRReview` row is auto-created with `application_id` pointing at this application, `review_due_date` equal to `Application.next_cdr_due_date`, and `status` `PENDING`.

A `DENY` at `INITIAL_REVIEW` is simpler: the application transitions from `INITIAL_REVIEW` to `INITIAL_DENIED`, `Application.last_initial_examiner_id` is stamped with the acting examiner, and a `Determination` row with `level` `INITIAL` and `decision` `DENY` is appended. No financial fields are computed.

If two `DDS_Examiner` operators race to issue determinations against the same `INITIAL_REVIEW` application — for example, one `ALLOW` and one `DENY` arriving concurrently — the system serialises them first-writer-wins on the `Application` status transition; exactly one transition succeeds, and the losing request finds the application no longer in `INITIAL_REVIEW` and is rejected with `ERR_INVALID_STATE` at HTTP status 409.

### 3.5. The Money Math: PIA, Family Max, Child Auxiliary, Back Pay, and SSI

**Primary Insurance Amount (PIA).** The Average Indexed Monthly Earnings (`aime_cents`) are derived from the indexed earnings ledger — the claimant's `QuarterCredit` rows rolled up by year, each year's total capped at `YEARLY_CAP_BY_YEAR` (which sets `$168,200` for 2024, the Social Security wage base). The highest-35 indexed annual earnings are summed and divided by 420 months to yield `aime_cents`. The PIA in cents is then the floor of three bend-point bands summed together: `0.90` multiplied by the lesser of `aime_cents` and `BEND_POINT_1` (which equals `117400` cents, that is `$1,174`); plus `0.32` multiplied by the greater of zero and the difference between (the lesser of `aime_cents` and `BEND_POINT_2`) and `BEND_POINT_1`, where `BEND_POINT_2` equals `707800` cents (`$7,078`); plus `0.15` multiplied by the greater of zero and the difference between `aime_cents` and `BEND_POINT_2`. After the floor, `pia_cents` is rounded down to the nearest ten cents — that is, `pia_cents` divided by ten using integer division, then multiplied by ten — implementing the SSA dime-round-down rule.

There are two variants of the PIA calculation. The **provisional** variant — used at allowances issued at `INITIAL_REVIEW` and at `RECONSIDERATION` — includes the claimant's year-of-onset earnings only up to the last completed `QuarterCredit`; later partial quarters in that year are dropped. The **final** variant — used at allowances issued at the `ALJ` level — includes the full year-of-onset earnings as a single annual figure, no quarter truncation. The two variants can yield different PIA totals; the magnitude of the difference depends on which bend-point band the new aime sum falls into and can move PIA by as much as 32% of the contribution of that year, given that the middle bend pays 32 cents on the dollar.

**Family Maximum.** Co-computed with `pia_calc` at every approval and recomputed whenever a `ChildAuxiliary` enters or leaves the entitled population. The cents-precise tiered formula is the floor of: `1.50` multiplied by the lesser of `pia_cents` and `FMB_BP1` (which equals `150000` cents, that is `$1,500`); plus `2.72` multiplied by the greater of zero and the difference between (the lesser of `pia_cents` and `FMB_BP2`) and `FMB_BP1`, where `FMB_BP2` equals `216500` cents (`$2,165`); plus `1.34` multiplied by the greater of zero and the difference between (the lesser of `pia_cents` and `FMB_BP3`) and `FMB_BP2`, where `FMB_BP3` equals `282500` cents (`$2,825`); plus `1.75` multiplied by the greater of zero and the difference between `pia_cents` and `FMB_BP3`. The result is then rounded down to the nearest ten cents using the same dime-round-down rule as PIA. After dime-rounding, the Disability Insurance Benefit (DIB) special floor and ceiling clamp `family_max_cents` to be no less than `1.50` times `pia_cents` and no more than `1.85` times `pia_cents`.

**Family Maximum waterfall.** The worker always receives the full `pia_cents`. The remaining pool — `family_max_cents` minus `pia_cents` — is distributed across the children whose `ChildAuxiliary.status` is `ENTITLED`. The per-child gross is the floor of half of `pia_cents`. If the count of entitled children multiplied by that gross is at most the pool, each child receives the gross. Otherwise the per-child share is the integer division of the pool by the count of entitled children; the remainder (the pool minus the per-child share multiplied by the count) is distributed one cent at a time to the oldest entitled children first, ordering by `child_date_of_birth` ascending with ties broken by `created_at` ascending. Each of the first (remainder) children receives one more cent than the others. Every `ChildAuxiliary.monthly_benefit_cents` is recomputed at every event that changes the entitled population — a new entitlement or a termination — and every recomputation refreshes the corresponding `updated_at` and bumps the corresponding `version`.

**Back pay.** Computed on every approval transition. The number of retroactive months is the count of full calendar months from `entitlement_date` through the month immediately before `approval_date` (exclusive at the approval-month boundary). `back_pay_cents` is the months retroactive multiplied by `monthly_benefit_cents`. The cap `MAX_PRE_FILING_RETRO_MONTHS` is twelve. There are two variants. The **provisional** back-pay variant — used at allowances at `INITIAL_REVIEW` and at `RECONSIDERATION` — caps pre-filing retro months at the lesser of twelve and the integer count of months between `filing_date` and `entitlement_date`. The **final** back-pay variant — used at allowances at the `ALJ` level — caps pre-filing retro months at twelve full months prior to `filing_date` absolutely, regardless of intervening denial windows. When `entitlement_date` precedes `filing_date` by more than twelve months and the adjudication delays compressed the earlier retro windows, the two variants yield different `back_pay_cents`.

**Child auxiliary monthly benefit.** A `ChildAuxiliary` is created by either the claimant or a DDS examiner in `PENDING` status; the body carries `application_id`, `child_name`, `child_date_of_birth`, `child_relationship` (one of `BIOLOGICAL`, `ADOPTED`, `STEPCHILD`, or `DEPENDENT_GRANDCHILD`), an optional `is_full_time_student` flag (required when the child is between 18 and 19 years old in secondary school), and an optional `is_disabled_before_22` flag. Entitlement is a system-emitted transition that fires when the parent `Application` reaches `APPROVED` or `ALJ_APPROVED`; the precondition is that the parent application's status is in `APPROVED` or `ALJ_APPROVED` (otherwise `ERR_PARENT_NOT_APPROVED`, surfaced through the existence/state error family) and that the child is under 18 at entitlement, or is between 18 and 19 with `is_full_time_student` true, or has `is_disabled_before_22` true (otherwise `ERR_CHILD_INELIGIBLE` at HTTP status 422). On entitlement, `monthly_benefit_cents` is set by the formula above, and every sibling `ChildAuxiliary`'s `monthly_benefit_cents` is recomputed by the waterfall. Termination is a system-emitted transition that supplies a `termination_reason` (one of `AGE_OUT`, `NO_LONGER_DISABLED`, or `PARENT_BENEFIT_ENDED`), moves status from `ENTITLED` to `TERMINATED`, and again recomputes every surviving sibling's `monthly_benefit_cents`. The list endpoint accepts optional `application_id` and `status` filters in addition to standard paging.

**SSI Supplement.** A `SSISupplement` is a peer entity created by either a claimant or a DDS examiner; its body carries `claimant_id`, `countable_income_cents`, `countable_resources_cents`, and `living_arrangement` (one of `OWN_HOUSEHOLD`, `ANOTHER_HOUSEHOLD`, or `INSTITUTION`). The supplement begins in `status` `DRAFT`. Activation (DRAFT to ACTIVE) is exclusive to a DDS examiner and requires `countable_resources_cents` to be at most `SSI_RESOURCE_LIMIT_CENTS` (which is `200000` cents, that is `$2,000` for an individual); otherwise the request is rejected with `ERR_SSI_RESOURCES_EXCEEDED` at HTTP status 422. On activation the server computes `ssi_payment_cents` as follows. First, the unearned-income exclusion: subtract the lesser of unearned income and `GENERAL_INCOME_EXCLUSION` (which is `2000` cents, that is `$20`) from unearned income. Whatever portion of the `$20` general exclusion was not consumed by unearned income spills over to earned income; that spillover is added to `EARNED_INCOME_EXCLUSION` (which is `6500` cents, that is `$65`) to yield the total earned-income exclusion. Subtract that total earned-income exclusion from earned income, floored at zero. Halve the remainder using integer division to apply the one-half earned-income exclusion. The countable income is the post-exclusion unearned income plus the halved post-exclusion earned income. The Federal Benefit Rate is then looked up from `FBR_BY_LIVING_ARRANGEMENT` — `96700` cents (`$967`) for `OWN_HOUSEHOLD`, `64470` cents (`$644.70`, reduced by one-third) for `ANOTHER_HOUSEHOLD`, and `3000` cents (`$30` personal-needs allowance) for `INSTITUTION`. The `ssi_payment_cents` is the FBR minus countable income, floored at zero. If the computed payment is zero **and** the claimant has a live DIB benefit, activation does not move the supplement to `ACTIVE`; it instead places it directly into `TERMINATED_DIB_OFFSET`. A subsequent PATCH against an `ACTIVE` supplement re-runs the computation: if `countable_resources_cents` rises above the limit, the status moves to `TERMINATED_RESOURCES`; if income alone drives the payment to zero, the status moves to `TERMINATED_INCOME`.

### 3.6. Reconsideration, ALJ, Appeals Council, and Remand

A denied claimant may appeal. After a denial, an appeal request supplies `target_level` in the body and is gated by the appeal window — the temporal precondition is that the current logical clock instant is on or before the last determination's `created_at` plus `APPEAL_WINDOW_DAYS` (which is sixty days); a late appeal is rejected with `ERR_APPEAL_WINDOW_EXPIRED` at HTTP status 409. When two appeal requests race against the same denied application, the system serialises them first-writer-wins on the application's status advance; the loser sees status already advanced and is rejected with `ERR_INVALID_STATE` at 409. From `INITIAL_DENIED`, an appeal advances the application to `RECONSIDERATION`. From `RECON_DENIED`, an appeal advances to `ALJ_PENDING`. From `ALJ_DENIED`, an appeal advances to `APPEALS_COUNCIL`.

A reconsideration determination is issued by a DDS examiner, but the segregation-of-duties rule binds: the acting examiner's `X-User-ID` must not equal the application's `last_initial_examiner_id`. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` at HTTP status 403, and this binding applies to both the `ALLOW` and `DENY` branches at reconsideration with equal force. A reconsideration `ALLOW` runs the same approval cascade described in §3.4 (and therefore re-computes `pia_cents`, `family_max_cents`, `entitlement_date`, `back_pay_cents`, `cdr_diary`, `next_cdr_due_date`, appends a `Determination` row at `level` `RECONSIDERATION`, and auto-creates the CDR review). A reconsideration `DENY` simply transitions to `RECON_DENIED` and appends the determination row.

An ALJ determination is issued by an `ALJ` operator and requires an associated `HearingSlot` for this application whose `status` is `HELD`; absent that, the determination is rejected with `ERR_HEARING_NOT_HELD` at HTTP status 422. An ALJ `ALLOW` runs the approval cascade with **final** variants for `pia_calc` and `back_pay_calc` — full year-of-onset earnings rather than truncated, and the absolute twelve-month pre-filing back-pay cap. An ALJ `DENY` transitions the application to `ALJ_DENIED` and appends the determination row.

An Appeals Council determination is issued by an `AppealsCouncil` operator. A `DENY` at this level is terminal and moves the application to `CLOSED_DENIED`. A `REMAND` at this level — and `REMAND` is valid only at `APPEALS_COUNCIL` — cycles the application back to `RECONSIDERATION` so a new examiner action can occur. The remand preserves the application's `last_initial_examiner_id`, meaning the segregation-of-duties bond persists through the cycle: the examiner who issued the original initial determination remains barred from any subsequent reconsideration on this application.

### 3.7. Hearings, Slot Booking, and Reschedules

Hearing capacity is modelled as `HearingSlot` resources. An ALJ (or PlatformAdmin) creates a slot in `OPEN` status by supplying the responsible `alj_id`, the `hearing_office` code (for example, `OHO_BOSTON`), and the slot's `start_at` and `end_at` ISO 8601 UTC datetimes. `end_at` must equal `start_at` plus exactly sixty minutes. The list endpoint accepts optional filters `alj_id`, `status`, `from`, and `to` alongside the standard `limit` and `offset` paging.

Booking moves a slot from `OPEN` to `BOOKED` and binds the slot to an application via the request body's `application_id`. The booking is gated by three preconditions: the application's status must be `ALJ_PENDING` (otherwise `ERR_INVALID_STATE` at 409); no other slot belonging to the same `alj_id` whose half-open interval `[start_at, end_at)` intersects this slot's interval may already be at `status` `BOOKED` or `HELD` (otherwise `ERR_HEARING_SLOT_CONFLICT` at 409); and no other slot for the same `application_id` may already be at `BOOKED` or `HELD` (otherwise `ERR_APPLICATION_ALREADY_SCHEDULED` at 409). The intersection check is closed-open: two slots whose intervals are exactly back-to-back (the end of one equals the start of the next) do not conflict, but any genuine overlap does. When two `ALJ` operators race to book the same `OPEN` slot, the system serialises first-writer-wins on the slot's transition; the loser is rejected with `ERR_HEARING_SLOT_CONFLICT` at 409. When a booking races against an examiner approving the application at reconsideration, the application's status read at booking time must be `ALJ_PENDING`; if the application has advanced to `APPROVED` first, the booking is rejected with `ERR_INVALID_STATE` at 409.

Once the slot's start time arrives, the ALJ marks the hearing held: the transition `BOOKED` to `HELD` requires that the current logical clock instant is at or after `start_at`, and an attempt before that yields `ERR_HEARING_NOT_REACHED` at 422. If the claimant does not appear, the ALJ records a no-show after the end of the slot: the transition `BOOKED` to `NO_SHOW` requires the current logical clock instant to be at or after `end_at`. A no-show leaves the parent application in `ALJ_PENDING`, signalling that a new slot must be booked. If circumstances require, a `BOOKED` slot can be rescheduled to a different `OPEN` slot before the start time: the request body's `new_slot_id` must refer to an `OPEN` slot, and the current logical clock instant must be strictly earlier than `start_at` (otherwise `ERR_HEARING_ALREADY_REACHED` is signalled through `ERR_HEARING_NOT_REACHED` — a hold attempted after start is the same temporal family). On a successful reschedule, the target slot transitions from `OPEN` to `BOOKED` inheriting the application binding, and the original slot's `application_id` is cleared while it advances to `RESCHEDULED`.

### 3.8. Continuing Disability Review and the Cessation Cascade

Every approval auto-creates one `CDRReview` row in `PENDING` status, with `application_id` pointing at the parent and `review_due_date` equal to the parent's `next_cdr_due_date`. The CDR list endpoint, available to a `CDR_Reviewer` and a `PlatformAdmin`, accepts optional `status` and `due_before` filters in addition to standard paging. Scheduling is the act of a CDR reviewer claiming the review; the transition `PENDING` to `SCHEDULED` stamps `scheduled_at` with the current logical clock instant and requires that the clock be at or after `review_due_date` minus sixty days (otherwise `ERR_CDR_NOT_DUE` at 422). When two CDR reviewers race to schedule the same review, the system serialises first-writer-wins on the `PENDING` to `SCHEDULED` transition; the loser is rejected with `ERR_INVALID_STATE` at 409.

Completing a review is the act of a CDR reviewer entering the medical-improvement and substantial-gainful-activity findings. The body supplies `medical_improvement_found` and `working_at_sga`. The server computes the `outcome`: `CEASE` if the claimant is found to have medical improvement related to ability to work post-MIRA or is working at substantial gainful activity, otherwise `CONTINUE`. `completed_at` is stamped with the current logical clock instant and `status` advances from `SCHEDULED` to `COMPLETED`. If the outcome is `CONTINUE`, the system auto-creates the next `CDRReview` row with `review_due_date` equal to the current logical clock instant plus the application's diary interval in whole months (`Application.cdr_diary` determines the interval: `MIE` is eighteen months, `MIP` is thirty-six months, `MINE` is eighty-four months). If the outcome is `CEASE`, the cessation cascade fires:

- The parent `Application` transitions from `APPROVED` to `CLOSED_DENIED`.
- A new `Determination` row is appended carrying a negative entitlement delta that recoups the originally awarded back pay, preserving a compensating-invariant total lifetime-paid ledger.
- Every `ChildAuxiliary` whose `application_id` matches this application and whose `status` is `ENTITLED` is terminated with `termination_reason` `PARENT_BENEFIT_ENDED`, transitioning each affected row from `ENTITLED` to `TERMINATED`.
- Any `SSISupplement` whose `claimant_id` matches this application's claimant and whose `status` is `TERMINATED_DIB_OFFSET` is recomputed: with the DIB benefit gone, the offset condition no longer applies and the supplement's status is reassessed.

`CDRReview` is not a terminal state machine: closing one review schedules the next per the diary cadence, and a single application may walk through many CDR reviews across its lifetime.

## 4. Endpoint Definitions

New resources are returned at HTTP status 201; modifications and reads (and lifecycle operations on existing resources such as submit, accept, reject, book, hold, reschedule, schedule, complete, activate, entitle, and terminate) return at HTTP status 200. Every endpoint's request and response payload follows the envelope of §2.2, the field semantics live in §3, and the failure modes live in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/claimants` | Register a new claimant | `Claimant`, `PlatformAdmin` |
| GET | `/claimants/{claimantId}` | Get one claimant | `Claimant`, `DDS_Examiner`, `ALJ`, `AppealsCouncil`, `CDR_Reviewer`, `PlatformAdmin` |
| PATCH | `/claimants/{claimantId}` | Update claimant fields | `Claimant`, `PlatformAdmin` |
| POST | `/claimants/{claimantId}/quarter-credits` | Append a quarter-of-coverage row (immutable) | `Claimant`, `PlatformAdmin` |
| GET | `/claimants/{claimantId}/quarter-credits` | List quarter credits with optional year filters | `Claimant`, `DDS_Examiner`, `PlatformAdmin` |
| POST | `/claimants/{claimantId}/medical-evidence` | Submit medical evidence (status `SUBMITTED`) | `Claimant` |
| POST | `/claimants/{claimantId}/medical-evidence/{evidenceId}/accept` | DDS examiner accepts evidence (`SUBMITTED` → `ACCEPTED`) | `DDS_Examiner` |
| POST | `/claimants/{claimantId}/medical-evidence/{evidenceId}/reject` | DDS examiner rejects evidence (`SUBMITTED` → `REJECTED`) | `DDS_Examiner` |
| POST | `/claimants/{claimantId}/applications` | Create an application in `DRAFT` status | `Claimant` |
| POST | `/claimants/{claimantId}/applications/{appId}/submit` | Submit `DRAFT` → `INITIAL_REVIEW` after QC and evidence checks | `Claimant` |
| POST | `/claimants/{claimantId}/applications/{appId}/determinations` | Issue a determination (ALLOW/DENY/REMAND) at the body-supplied level | `DDS_Examiner`, `ALJ`, `AppealsCouncil` |
| POST | `/claimants/{claimantId}/applications/{appId}/appeal` | Advance a denial to the next adjudication level | `Claimant` |
| GET | `/claimants/{claimantId}/applications/{appId}` | Read an application | `Claimant`, `DDS_Examiner`, `ALJ`, `AppealsCouncil`, `CDR_Reviewer`, `PlatformAdmin` |
| GET | `/claimants/{claimantId}/applications/{appId}/determinations` | List determinations for an application | `Claimant`, `DDS_Examiner`, `ALJ`, `AppealsCouncil`, `PlatformAdmin` |
| POST | `/hearing-slots` | Create an `OPEN` hearing slot | `ALJ`, `PlatformAdmin` |
| GET | `/hearing-slots` | List hearing slots (filters: `alj_id`, `status`, `from`, `to`) | `ALJ`, `AppealsCouncil`, `Claimant`, `PlatformAdmin` |
| POST | `/hearing-slots/{slotId}/book` | Book a slot for an application (`OPEN` → `BOOKED`) | `ALJ` |
| POST | `/hearing-slots/{slotId}/hold` | Mark `BOOKED` → `HELD` once start time reached | `ALJ` |
| POST | `/hearing-slots/{slotId}/no-show` | Mark `BOOKED` → `NO_SHOW` after end time | `ALJ` |
| POST | `/hearing-slots/{slotId}/reschedule` | Move application from this slot to another `OPEN` slot | `ALJ` |
| POST | `/child-auxiliaries` | Create a `ChildAuxiliary` in `PENDING` state | `Claimant`, `DDS_Examiner` |
| POST | `/child-auxiliaries/{id}/entitle` | Entitle a child (`PENDING` → `ENTITLED`) | `DDS_Examiner`, `PlatformAdmin` |
| POST | `/child-auxiliaries/{id}/terminate` | Terminate a child (`ENTITLED` → `TERMINATED`) with explicit reason | `DDS_Examiner`, `PlatformAdmin` |
| GET | `/child-auxiliaries` | List child auxiliaries (filters: `application_id`, `status`) | `Claimant`, `DDS_Examiner`, `PlatformAdmin` |
| POST | `/ssi-supplements` | Create an SSI supplement in `DRAFT` for a claimant | `Claimant`, `DDS_Examiner` |
| POST | `/ssi-supplements/{id}/activate` | Activate SSI (`DRAFT` → `ACTIVE`, or to `TERMINATED_DIB_OFFSET`) | `DDS_Examiner` |
| PATCH | `/ssi-supplements/{id}` | Update countable income / resources / living arrangement | `DDS_Examiner`, `Claimant` |
| GET | `/cdr-reviews` | List CDR reviews (filters: `status`, `due_before`) | `CDR_Reviewer`, `PlatformAdmin` |
| POST | `/cdr-reviews/{id}/schedule` | Schedule a pending CDR (`PENDING` → `SCHEDULED`) | `CDR_Reviewer` |
| POST | `/cdr-reviews/{id}/complete` | Complete a scheduled CDR with outcome (CONTINUE/CEASE) | `CDR_Reviewer` |
| POST | `/_clock/advance` | Advance the server logical clock for tests; body `{ to: ISO8601 }` | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_INVALID_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CLAIMANT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_HEARING_SLOT_CONFLICT` | 409 |
| `ERR_APPLICATION_ALREADY_SCHEDULED` | 409 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 |
| `ERR_HEARING_NOT_REACHED` | 422 |
| `ERR_HEARING_NOT_HELD` | 422 |
| `ERR_QC_INSUFFICIENT` | 422 |
| `ERR_EVIDENCE_INSUFFICIENT` | 422 |
| `ERR_AOD_AFTER_FILING` | 422 |
| `ERR_CHILD_INELIGIBLE` | 422 |
| `ERR_SSI_RESOURCES_EXCEEDED` | 422 |
| `ERR_CDR_NOT_DUE` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_BAD_REQUEST` | 400 |

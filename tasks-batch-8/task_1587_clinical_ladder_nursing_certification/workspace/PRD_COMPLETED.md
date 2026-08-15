# Clinical Ladder & Nursing Certification API — Product Requirements Document

## 1. Introduction

Magnet-designated hospitals run clinical ladder programs to recognize and retain bedside nursing talent: nurses assemble portfolios, a peer committee scores them, and advancement through the ladder carries a recurring pay differential. Alongside advancement, the program reimburses certification exam fees, pays one-time bonuses for earned credentials, tracks committee and project participation, and audits every nurse annually against maintenance criteria. Today these workflows live in spreadsheets and email threads, which makes quorum rules, fiscal-year caps, and anniversary deadlines nearly impossible to enforce consistently.

This document specifies the Clinical Ladder & Nursing Certification API, the system of record for that program. It governs four ladder rungs (`CN_I` through `CN_IV`), a cyclic portfolio review process with scored committee assignments and a bounded number of revision rounds, a parallel pay-differential dimension that can be active, suspended, or terminated independently of the nurse's level, and a July-anchored fiscal year that drives per-nurse reimbursement ceilings, per-unit budget guards, and dual-variant budget forecasts. Segregation of duties is a first-class concern throughout: the nurse who applies may not review, the reviewer who scores may not decide, and the administrator who approves a claim may not be the claimant.

A logical clock underpins every temporal rule in the system — participation lookback windows, review scoring deadlines, certification expirations, anniversary cycles, and fiscal-year boundaries — so that program staff can rehearse an entire program year deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to invoke the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `Nurse` — a program participant who acts on their own applications, participation events, certifications, and reimbursement claims, and who also serves as a committee reviewer on other nurses' applications.
- `ProgramAdmin` — the nursing professional-development administrator; runs criterion publication, participation verification, certification registration and revocation, reviewer assignment, advancement decisions, anniversary reviews, budget lines, and the ops-run sweeps.
- `PayrollOfficer` — disburses approved reimbursements and accrued bonuses under the unit budget guard.
- `RetentionAnalyst` — a read-only analyst for retention snapshots and participation aggregates.

Identity semantics differ by role. When `X-User-Role` is `Nurse`, `X-User-ID` is the `id` of the acting `Nurse` record; ownership checks on any resource that references a nurse — an application, a participation event, a certification, a claim, a review assignment — compare the resource's nurse foreign-key field (or the assignment's reviewer field) to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). When `X-User-Role` is `ProgramAdmin`, `PayrollOfficer`, or `RetentionAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `decided_by_admin_id` on an advancement decision, where it anchors the segregation-of-duties audit trail) but never compares it to any entity's `id`.

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0; a non-integer or out-of-range `limit` or `offset` fails with `ERR_INVALID_REQUEST` (HTTP 400). The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`, with `has_more` true exactly when `offset` plus the number of returned rows is still below `total_count`. Every list endpoint sorts by `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — plus `created_at` and `updated_at` timestamps rendered as ISO 8601 UTC with three fractional digits, and an integer `version` that starts at 1 on creation and increments by one on every mutation of that resource. Two resources are exceptions by design: an `AdvancementDecision` and a `RetentionSnapshot` carry only `id` and `created_at` from the common set. Both `updated_at` and `version` are absent on those two resources, because decisions are append-only audit rows and snapshots are immutable point-in-time captures.

### 2.5. The Logical Clock and the July-Anchored Fiscal Year

All temporal semantics — lookback windows, deadlines, expirations, fiscal-year assignment — read from a logical clock, never from wall-clock time. At server start the logical clock reads exactly 2026-08-01T00:00:00Z. A `ProgramAdmin` may advance it through the clock-setting capability (`POST /clinical-ladder/_clock/set_current_utc`), which accepts a `to_iso8601` timestamp; once set, the clock holds that position until set again and never falls back to wall-clock time.

The program's fiscal year is anchored to July: a fiscal year runs from July 1 through the following June 30. The fiscal-year label of any instant is the calendar year plus one when the month is July or later, and the calendar year otherwise. A reimbursement claim's `fiscal_year` is derived from the logical clock at claim submission using exactly this rule, and budget lines are keyed to a fiscal year through their own `fiscal_year` field.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents: exam fees, claimed and approved amounts, bonus amounts, monthly differentials, budget allocations, commitments, and forecasts. Where a calculation produces a fractional intermediate, the rounding rule is always round-half-up, applied at the step each calculation specifies and never earlier. The committee aggregate score rounds half-up to a whole integer exactly once, at the final step. The average retention risk score on a snapshot rounds half-up to two decimal places, and a snapshot's demotion rate rounds half-up to four decimal places. Budget forecasts hold the months-remaining fraction at two decimal places and round the final forecast half-up to integer cents.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a parent entity, by carrying an expected-version field that must equal the parent's current `version`:

- Rendering an advancement decision requires `expected_application_version`, matching the application's current `version`. If another writer has advanced the application's version since the deciding administrator last read it — for instance, a colleague has just returned the application for revision, which legitimately mutates its status and review cycle — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating a budget line's allocation requires `expected_budget_line_version`, matching the budget line's current `version`. If a reimbursement approval cascade has just recomputed `committed_cents` on the same line since the client last read it, the allocation edit is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Drafting a ladder application requires `expected_nurse_version`, matching the nurse's current `version`. If an anniversary demotion has just changed the nurse's level since the applicant last read their record, the new application's target-rung arithmetic is stale and the draft is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field.

### 2.8. Validation Order

Incoming requests are validated in a fixed sequence, and the sequence is observable: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every path-referenced resource resolved left to right — an application is resolved before its assignment, a certification before its claim — with a missing resource surfacing `ERR_NOT_FOUND` (HTTP 404). Entity identifiers carried in the request payload (such as `nurse_id`, `certification_id`, or `reviewer_nurse_id`) likewise surface `ERR_NOT_FOUND` when they do not resolve, unless the operation pins a different error for that case. A request whose payload is missing a required field, carries a value of the wrong type, or names an enum value outside the declared set fails with `ERR_INVALID_REQUEST` (HTTP 400). Next, the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE` (HTTP 409); then the optimistic-concurrency version match (`ERR_STALE_VERSION`); then ownership (`ERR_NOT_OWNER`); then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, HTTP 422).

Business rules run last, and where several guard one operation they run in this pinned order: drafting an application checks the stale-version rule, then ownership, then the one-rung rule, then the active-criterion rule; publishing a criterion checks window overlap before differential monotonicity; staffing a review assignment checks segregation of duties, then quorum headroom, then reviewer duplication; registering a certification checks date order, then renewal matching, then same-track currency overlap; approving a claim checks segregation of duties, then the per-nurse fiscal-year ceiling, then certification staleness; rendering a decision checks the application stale-version rule, then segregation of duties, then staleness of the pinned references; closing an anniversary review evaluates the demotion-floor rule before the maintenance-threshold rule.

### 2.9. The Ops-Run Sweep

Time-driven transitions do not fire on their own; they run when a `ProgramAdmin` invokes the ops-run sweep (`POST /clinical-ladder/_ops/run_cycle`) at the current logical clock position. One sweep lapses every certification whose expiry has been reached, expires every review assignment whose scoring window has closed, lapses every anniversary review left open past its review year's end, closes budget lines whose fiscal year has ended by flipping their forecast variant to `FINAL`, and captures retention snapshot rows. The sweep responds with a small tally object naming how much work it did: `swept_certifications`, `expired_assignments`, `lapsed_reviews`, `closed_budget_lines`, and `snapshots_captured`.

## 3. Business Logic & Workflows

### 3.1. Enrolling Nurses and Publishing Ladder Criteria

A `ProgramAdmin` enrolls a nurse by registering their `employee_code` (a hospital HR code such as "RN-1042", unique across all nurses — a duplicate `employee_code` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and immutable once set), `full_name`, `hire_date`, and `home_unit` cost-center code such as ICU-4W. New nurses enter the program at `current_level` `CN_I` — the ladder floor — with `differential_status` `INACTIVE` and a `retention_risk_score` of zero. The nurse's `tenure_years` is never stored; it is recomputed on every read from the logical clock as the number of whole years elapsed since `hire_date`, computed by dividing the elapsed days by 365.25 and rounding down to the whole year. The nurse directory can be listed with optional `home_unit`, `current_level`, and `differential_status` filters.

Two dimensions on the nurse evolve independently. `current_level` moves only through advancement and demotion transitions, across the four rungs `CN_I`, `CN_II`, `CN_III`, and `CN_IV`. `differential_status` tracks whether the ladder differential is actually being paid, across `INACTIVE`, `ACTIVE`, `SUSPENDED`, and `TERMINATED`; a demotion suspends pay while the level itself recomputes, and a later advancement approval flips pay back to `ACTIVE`. The `differential_activated_at` timestamp records the most recent flip into `ACTIVE` from either `INACTIVE` or `SUSPENDED`, stays null while the differential has never been activated, and anchors the anniversary-review cycle.

Ladder admission criteria are published per target rung. A criterion set names its `target_level` (one of `CN_II`, `CN_III`, `CN_IV`), the `min_portfolio_score` a committee aggregate must reach (an integer from 1 to 400), the `min_participation_points` a nurse must hold in the lookback window at submission (0 to 200), the `required_certification_track` the nurse must currently hold (`NONE`, `BASIC`, `SPECIALTY`, or `ADVANCED`), the `differential_monthly_cents` paid monthly at that level (zero or more), and a validity window from `effective_from` (inclusive) to `effective_until` (exclusive); a null `effective_until` leaves the set open-ended, and when present it must be strictly later than `effective_from`. Violations of these field constraints — an out-of-range score or points value, a negative differential, or an `effective_until` at or before `effective_from` — fail with `ERR_INVALID_REQUEST` (HTTP 400). The window is half-open: an instant exactly at `effective_from` is covered, an instant exactly at `effective_until` is not.

Publication enforces two market-consistency rules, window overlap first and monotonicity second. Two criterion sets for the same `target_level` may not have overlapping validity windows — geometric overlap of the half-open intervals — and mere adjacency, where one set's `effective_until` equals the other's `effective_from`, is not overlap; a violation is rejected with `ERR_CRITERION_WINDOW_OVERLAP` (HTTP 409). Across the criterion sets active at the same time, monthly differentials must strictly increase with the rung: the `CN_IV` amount strictly greater than the `CN_III` amount, which is strictly greater than the `CN_II` amount; a violation is rejected with `ERR_DIFFERENTIAL_MONOTONICITY` (HTTP 422). Criterion sets can be listed with an optional `target_level` filter.

### 3.2. Recording and Verifying Professional Engagement

Professional engagement — committee seats, quality-improvement projects, peer education, evidence-based research, preceptorships — is logged by the nurse as participation events. Each event names its owning `nurse_id`, an `event_kind` of `COMMITTEE_SEAT`, `QI_PROJECT`, `PEER_EDUCATION`, `EBP_RESEARCH`, or `PRECEPTORSHIP`, the `points` awarded, and the `occurred_on` date. Points must fall between 1 and 40 inclusive, and a `COMMITTEE_SEAT` event is additionally capped at 20 points; anything outside those bounds is rejected with `ERR_PARTICIPATION_POINTS_RANGE` (HTTP 422).

Every event enters as `PENDING_VERIFICATION`. A `ProgramAdmin` then verifies it, moving it to `VERIFIED` — which also lowers the nurse's retention risk, as detailed in §3.7 — or voids it, moving it to `VOIDED`. Both terminal states are final; acting on an event that has already left `PENDING_VERIFICATION` fails with `ERR_INVALID_STATE`. Participation histories are reachable per nurse, and a cross-nurse listing accepts `nurse_id`, `event_kind`, and `status` filters.

Verified engagement feeds the participation lookback window, the program's central aggregation. The window opens 24 months before the current logical-clock position, on the same day of the month — if that earlier month has no such day, the window opens on the last day of that month — and it closes at the clock position itself, exclusively. Only `VERIFIED` events count, an event dated exactly at the window start is included, and an event dated exactly at the clock position is excluded; the result is the plain integer sum of the included events' `points`, with no rounding. The window is evaluated in two variants that share the formula but diverge in when they read the clock: a live variant evaluated at the current position, used for the eligibility precheck at submission, and a snapshot variant frozen onto the application at submission, after which later verification of still-pending events does not retroactively raise the frozen figure. Divergence between the two is itself observable when events verify between submission and decision.

### 3.3. Certifications, Exam-Fee Reimbursement, and Certification Bonuses

When a nurse earns a credential, a `ProgramAdmin` registers the certification with the holder's `nurse_id`, the `track` (`BASIC`, `SPECIALTY`, or `ADVANCED`), the `certifying_body` such as ANCC, the `exam_fee_cents` the nurse paid (strictly positive, else `ERR_INVALID_REQUEST` (HTTP 400)), the `obtained_on` grant date, and the `expires_on` expiry date. Three integrity rules run in order — date order, then renewal matching, then currency overlap. The expiry must be strictly later than the grant date, else `ERR_CERTIFICATION_DATE_ORDER` (HTTP 422). An optional `renewal_of_id` may chain the row to an earlier certification of the same nurse, and when supplied it must resolve to a certification of the same nurse in the same track, else `ERR_RENEWAL_MISMATCH` (HTTP 422). Finally, a nurse may not hold two `CURRENT` certifications of the same track whose grant-to-expiry intervals overlap — again half-open, so an old credential expiring exactly on the new one's grant date is adjacency, not overlap; a renewal chain is permitted only when the renewed certification has already lapsed or its expiry falls at or before the new grant date. Violations surface `ERR_CERTIFICATION_OVERLAP` (HTTP 409).

A new certification enters as `CURRENT` and immediately accrues a `CertificationBonus` in `ACCRUED` status, whose `bonus_amount_cents` is computed entirely server-side. The base amount tiers by track: 50,000 cents ($500.00) for `BASIC`, 100,000 cents ($1,000.00) for `SPECIALTY`, and 175,000 cents ($1,750.00) for `ADVANCED`. A first-time credential — one whose `renewal_of_id` is null — multiplies the base by one and a half, while a renewal applies a multiplier of one. The multiplied base is rounded half-up to integer cents first, and only then is a tenure bonus of 25,000 cents ($250.00) added when the holder's `tenure_years` has reached at least 10. The accrual also recomputes the unit's budget commitment described in §3.6. Certification listings accept `nurse_id`, `renewal_of_id`, `track`, and `status` filters, and each certification exposes its claims and its bonuses as nested lists filterable by `status`.

Credentials expire with the calendar: when the ops-run sweep finds a `CURRENT` certification whose `expires_on` has been reached by the logical clock, it lapses to `LAPSED`, the holder's retention risk is recomputed upward, and — when the lapsed credential was the holder's only remaining `CURRENT` certification at or above the track their current ladder level requires — an anniversary review opens immediately in `OPEN` outcome, flagged for early maintenance checking (its `review_year` taken from the clock's calendar year, the flag recorded on the row as its `resolution_reason`). A `ProgramAdmin` may instead revoke a `CURRENT` certification outright; revocation claws back every bonus on that certification that is in `PAID` status and was paid within the trailing twelve months — the window inclusive at both ends, from twelve months before the clock position through the clock position itself — flipping each to `CLAWED_BACK`, recomputes the holder's unit budget commitment as the clawback releases the commitment, and recomputes the holder's retention risk. A certification that has lapsed cannot later be revoked, and vice versa — both `LAPSED` and `REVOKED` are terminal.

Against a registered certification, the nurse files an exam-fee reimbursement claim naming the `certification_id` and a `claimed_amount_cents` that must be positive and may not exceed what remains of the certification's `exam_fee_cents` after amounts already approved or paid against that same certification; a non-positive or excess claim is rejected with `ERR_CLAIM_EXCEEDS_FEE` (HTTP 422). Filing does not require the certification to still be `CURRENT`; currency is enforced at approval time. The claim enters `SUBMITTED` with its `fiscal_year` derived from the logical clock at submission under the July-anchored rule of §2.5.

Claim adjudication belongs to the `ProgramAdmin`, and approval runs its checks in order — segregation of duties, then the fiscal-year ceiling, then certification staleness. The approving administrator may not be the claiming nurse; a same-person approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. The per-nurse fiscal-year ceiling is 150,000 cents ($1,500.00): the amounts already approved or paid on the nurse's claims in the same fiscal year are summed, the remainder under the ceiling is what room is left, and the claim's `approved_amount_cents` is set to the claimed amount or that remaining room, whichever is smaller, never below zero. When no room remains at all, approval is rejected with `ERR_REIMBURSEMENT_CAP_EXHAUSTED` (HTTP 402); when the claimed amount exactly equals the remaining room, the claim approves in full. The certification must still be `CURRENT` at decision time — a certification that has lapsed or been revoked between claim filing and approval makes the approval fail with `ERR_STALE_REFERENCE` (HTTP 409). An approval recomputes the claiming nurse's unit budget commitment. Denial instead requires a `denial_reason` and moves the claim to `DENIED`, a terminal state that frees nothing and commits nothing.

Payment belongs to the `PayrollOfficer` and is guarded by the unit's budget. The guard sums the approved amounts of all already-paid claims in the nurse's unit for the claim's fiscal year, adds the amounts of all bonuses already paid whose payment fell within that fiscal year for the unit, adds this claim's `approved_amount_cents`, and requires the total to stay at or under the budget line's `allocated_cents`; a unit with no budget line for that fiscal year fails the guard outright. A failing guard rejects the payment with `ERR_BUDGET_EXCEEDED` (HTTP 402). A successful payment moves the claim `APPROVED` to `PAID` and recomputes the budget commitment, since paid claims leave the committed pool.

Bonuses pay out under the same discipline: the `PayrollOfficer` pays an `ACCRUED` bonus only while its parent certification is still `CURRENT` (otherwise `ERR_INVALID_STATE`, HTTP 409) and only while the same unit budget guard — paid claims, plus paid bonuses, plus this `bonus_amount_cents`, against the `allocated_cents` of the unit's budget line for the fiscal year current at payment time — holds. A `ProgramAdmin` may also claw a bonus back directly with a `clawback_reason`: from `ACCRUED` unconditionally, or from `PAID` when the payment falls within the trailing twelve months (the same both-ends-inclusive window as revocation) or the parent certification has been revoked. Both payment and clawback recompute the unit budget commitment, and a clawback from `PAID` additionally raises the holder's retention risk.

### 3.4. The Advancement Application and Committee Review

A nurse begins by drafting an application carrying their `nurse_id`, the `target_level` sought (one of `CN_II`, `CN_III`, or `CN_IV`), a free-text `portfolio_narrative`, and the `expected_nurse_version` concurrency token of §2.7. The target must be exactly one rung above the nurse's current level — `CN_I` to `CN_II`, `CN_II` to `CN_III`, `CN_III` to `CN_IV` — and skip-rung or same-rung drafts are rejected with `ERR_LADDER_RUNG_VIOLATION` (HTTP 422). Drafting itself advances the nurse's `version` by one, so a stale `expected_nurse_version` is caught by the `ERR_STALE_VERSION` rule before the rung check even runs. The draft starts in `DRAFT` with `review_cycle` at zero, `submitted_at` null, `aggregate_score` null, and `criterion_id` not yet pinned.

Submission is the nurse's own act — another nurse submitting on their behalf fails ownership with `ERR_NOT_OWNER` — and it re-runs the eligibility gauntlet in order: the one-rung rule again, then the existence of an active criterion set covering the target level at the current clock position (`ERR_NO_ACTIVE_CRITERION` when none does, remembering that the window is half-open and a null `effective_until` is open-ended), then the live participation window totaling at least the criterion's `min_participation_points`, then a `CURRENT` certification whose track ranks at or above the criterion's `required_certification_track` on the ordering `NONE` below `BASIC` below `SPECIALTY` below `ADVANCED`; a shortfall on either of these last two gates fails with `ERR_INVALID_STATE` (HTTP 409). A successful submission pins `criterion_id` to the matched criterion set, stamps `submitted_at` with the clock position, freezes `participation_snapshot_points` to the window result, and advances the application's `version`. From either `DRAFT` or `SUBMITTED` the applicant may withdraw instead, moving the application to the terminal `WITHDRAWN` state.

Review staffing is the administrator's next move. Creating a review assignment names a `reviewer_nurse_id`; the parent application must be `SUBMITTED` or `IN_REVIEW` — any other state fails with `ERR_INVALID_STATE` (HTTP 409) — and three rules fire in order: the reviewer may not be the applicant (`ERR_SEGREGATION_OF_DUTIES`), the count of `PENDING` plus `SCORED` assignments on the application must be below the quorum of three before another is created — unless the new assignment replaces a `RECUSED` or `EXPIRED` one — else `ERR_QUORUM_EXCEEDED` (HTTP 422), and no reviewer may hold a second `PENDING` or `SCORED` assignment on the same application (`ERR_DUPLICATE_REVIEWER`, HTTP 409). Each assignment starts `PENDING`; the very first assignment on a submitted application moves the application from `SUBMITTED` to `IN_REVIEW`, and every assignment creation advances the application's `version` by one.

Scoring belongs to the assigned reviewer alone, whose entity-backed identity must equal the assignment's `reviewer_nurse_id`. The score payload, `dimension_scores`, carries all four dimensions — `leadership`, `clinical_expertise`, `professional_development`, and `outcomes` — each an integer from 0 to 100, and all four are required. Scores land only while the parent application is still `IN_REVIEW` and only within fourteen days of the assignment's creation — the boundary is inclusive, so a score landing exactly fourteen days after creation still lands, and the sweep expires an assignment only once the clock is strictly past that instant; a late score is rejected with `ERR_REVIEW_WINDOW_EXPIRED` (HTTP 422), and the sweep will move the stale assignment itself to `EXPIRED`, excluding it from the quorum count. A submitted score stamps the assignment's own `submitted_at` and moves it to `SCORED`. When the scored count reaches the quorum of three and no `PENDING` assignments remain, the application's `aggregate_score` bubbles up: each `SCORED` assignment's four dimensions are combined with weights of thirty percent for leadership, thirty percent for clinical expertise, twenty percent for professional development, and twenty percent for outcomes, kept at full floating-point precision per reviewer; the per-reviewer totals are then averaged across the scored assignments, and that average is rounded half-up to a whole integer exactly once, with no per-reviewer pre-rounding. `RECUSED` and `EXPIRED` assignments contribute nothing. A reviewer who cannot serve recuses themselves instead — the assignment moves `PENDING` to `RECUSED`, the application stays `IN_REVIEW`, and a replacement assignment may be created.

Committee deadlocks and weak portfolios need not end an application. While the application is `IN_REVIEW` and its `review_cycle` is still below three, the administrator may return it for revision; a fourth attempt is rejected with `ERR_REVIEW_CYCLE_EXHAUSTED` (HTTP 422). Returning cascades every still-`PENDING` assignment on the application to `EXPIRED` — already-`SCORED` assignments remain for audit — and increments `review_cycle`. Immediately afterward the machine auto-transitions `RETURNED_FOR_REVISION` back to `DRAFT`, clearing `submitted_at` to null so that the eventual resubmission re-pins the criterion and re-snapshots participation; the return operation as a whole advances the application's `version` by exactly one. The cycle `DRAFT` to `SUBMITTED` to `IN_REVIEW` to `RETURNED_FOR_REVISION` and back to `DRAFT` may repeat up to the review-cycle cap.

The decision is the administrator's terminal act, rendered with an `outcome` of `APPROVE` or `DENY` and the `expected_application_version` token; a version advanced since the decider last read the application fails with `ERR_STALE_VERSION` before any of the decision gates are examined. Both outcomes require the application to be `IN_REVIEW` with at least three `SCORED` assignments and no `PENDING` ones left; this quorum precondition is checked after the version token and fails with `ERR_INVALID_STATE` (HTTP 409). Approval adds three more gates, checked after the version token in this order — segregation, then reference staleness interleaved with the score threshold: the decider's identity must differ from every scored reviewer on the application (`ERR_SEGREGATION_OF_DUTIES`, since a scorer may not decide), the pinned criterion set's `version` must be unchanged since submission, with any modification surfacing `ERR_STALE_REFERENCE`, and the `aggregate_score` must reach the pinned criterion's `min_portfolio_score`, the boundary inclusive, with a below-threshold aggregate failing the approval with `ERR_INVALID_STATE` (HTTP 409).

An approving decision writes an append-only `AdvancementDecision` row recording the `application_id`, the decider's opaque `decided_by_admin_id`, the `outcome`, a `criterion_version_snapshot` capturing the pinned criterion's `version` at decision time as tamper evidence, and the `decided_at` clock timestamp. In the same breath the nurse's `current_level` becomes the application's `target_level`, the `differential_status` flips to `ACTIVE` from `INACTIVE` — or back from `SUSPENDED` after an earlier demotion — with `differential_activated_at` stamped to the clock, the application's `review_cycle` increments and its `version` advances, the nurse's retention risk is recomputed with the advancement resetting its decay baseline, and the unit budget commitment recomputes to absorb the newly active differential. A denying decision writes its own decision row, increments `review_cycle`, and recomputes retention risk with the denial pushing it upward. Applications list with `nurse_id`, `criterion_id`, and `status` filters; assignments list across applications with `application_id`, `reviewer_nurse_id`, and `status` filters; and each application exposes its decision history as an append-only nested list.

### 3.5. Advancement Pay and Anniversary Maintenance

While a nurse's `differential_status` is `ACTIVE`, the program pays the `differential_monthly_cents` of the active criterion set keyed to the nurse's `current_level`, every month. That pay is not a lifetime entitlement: each year, on the anniversary of `differential_activated_at`, the nurse owes a maintenance review. A `ProgramAdmin` opens the review by naming the `nurse_id` and the calendar `review_year`; the review starts in `OPEN` outcome, and a nurse's reviews can be listed with an `outcome` filter.

Closing a review computes the nurse's `maintenance_score`, a composite of three integer components summing to at most 100. The participation component doubles the live 24-month participation window at review close and caps at 40, so twenty verified points saturate it. The certification component depends on the nurse's own level requirement — the `required_certification_track` of the active criterion set for the nurse's current level, or `NONE` for `CN_I`, whose rung has no admission criterion: holding at least one `CURRENT` certification at or above that requirement earns 40, holding at least one `CURRENT` `BASIC` credential short of it earns 20, and holding neither earns 0. The tenure component doubles `tenure_years` and caps at 20, so ten years of service saturate it.

Two outcomes close a review by administrator action, and the floor rule is evaluated before the threshold rule. Closing with `SUSTAIN` requires the maintenance score to reach the threshold of 60 — 59 fails with `ERR_MAINTENANCE_SCORE_INSUFFICIENT` (HTTP 422), 60 passes — and on success the differential's activation anniversary rolls forward one year, extending pay for another cycle. Closing with `DEMOTE` requires a `resolution_reason` and drops the nurse one rung — `CN_IV` to `CN_III`, `CN_III` to `CN_II`, `CN_II` to `CN_I` — while a demotion requested for a nurse already at `CN_I` is rejected with `ERR_CANNOT_DEMOTE_FLOOR` (HTTP 422). Demotion flips `differential_status` to `SUSPENDED`, halting pay while leaving the level dimension to stand on its own, and fires the heaviest single increment to the nurse's retention risk; the unit budget commitment recomputes against the now-lower differential.

A review ignored is worse than a review failed. When the ops-run sweep finds a review still `OPEN` past December 31 of its `review_year`, it closes the review as `LAPSE` — recording the rationale on the row — and sets `differential_status` to `TERMINATED`, killing the pay entirely rather than suspending it, then recomputes both the unit budget commitment and the nurse's retention risk.

### 3.6. Unit Budget Lines and Fiscal-Year Forecasting

Program money is allocated per unit per fiscal year. A `ProgramAdmin` creates a budget line with the `unit` cost-center code — matching the nurses' `home_unit` — the July-anchored `fiscal_year`, and a non-negative `allocated_cents`; one line may exist per unit and fiscal year — a duplicate, or a negative `allocated_cents`, fails with `ERR_INVALID_REQUEST` (HTTP 400) — and creation immediately initializes `committed_cents` and `forecast_cents`. Budget lines list with `unit` and `fiscal_year` filters.

The commitment figure answers "what do we already owe?" It annualizes the active differentials — twelve months of each unit nurse's level-keyed monthly differential, summed over nurses whose `differential_status` is `ACTIVE` — then adds the approved-but-unpaid reimbursement claims of the line's fiscal year and the accrued-but-unpaid bonuses created within that fiscal year. Paid claims and paid bonuses have left the committed pool, and clawed-back or terminated items are excluded. The commitment recomputes on every financial mutation: a differential flipping active, suspended, or terminated; a claim's approval or payment; a bonus's accrual, payment, or clawback; certification registration, revocation, and demotion all flow into it (a certification's lapse by itself moves no committed figure and triggers no recompute). Each such recompute writes the line's recomputed `committed_cents` and `forecast_cents` and advances the line's `version` by one, so the staleness rule of §2.7 catches any client that read the line before the cascade ran.

The forecast figure answers "where will the year land?", and it answers twice, in two variants that diverge for identical inputs. While the fiscal year is open, the line's `forecast_variant` reads `PROVISIONAL` and the forecast is forward-looking: the commitment, plus the annualized active differential prorated by the fraction of the year remaining — the count of calendar months from the clock's month through the June of the fiscal year the clock currently sits in, including the current month, divided by twelve, held at two decimal places — plus a pipeline term of eighty percent of the claimed amounts on the unit's claims still in `SUBMITTED` in the line's fiscal year. When the ops-run sweep closes the fiscal year, the variant flips to `FINAL` and the forecast becomes paid actuals: the commitment plus only the one-time amounts actually paid — paid claims of the line's fiscal year, and paid bonuses whose payment timestamp fell within the fiscal year — with the pipeline excluded entirely. In both variants the commitment is computed first and the variant-specific term added second, and the final figure rounds half-up to integer cents.

Reallocation mid-year is possible but guarded: updating a line's `allocated_cents` requires the `expected_budget_line_version` token of §2.7, so a writer holding a stale committed baseline is rejected with `ERR_STALE_VERSION` rather than silently overwriting a cascade's work, and the new allocation must be non-negative (else `ERR_INVALID_REQUEST`); a successful update advances the line's `version` by one and recomputes the forecast.

### 3.7. Retention Risk Scoring and Outcome Snapshots

Every nurse carries a `retention_risk_score` between 0 and 100 that the program recomputes at each turning point: advancement, denial, demotion, lapse, clawback, certification lapse, and participation verification. The score decays with time and jumps with events, evaluated in a pinned order — decay first, then event bumps, then clamping. Decay measures whole years since the nurse's last advancement decision (or since `hire_date` if the nurse has never advanced) — whole years taken as elapsed days divided by 365, rounded down — and subtracts ten points per whole year from the previous score, never below zero. Event bumps then accumulate over trailing windows, each running from the window start up to and including the current clock position — so the event whose transition triggered the recompute counts toward its own bump — with events ordered by their timestamps ascending and ties broken by `created_at` ascending: each anniversary demotion in the trailing 24 months adds 15; each certification lapse by sweep in the trailing 24 months adds 10, while a revoked certification deliberately adds nothing here because its risk impact flows through the clawback term; each denied application in the trailing 24 months adds 8; each bonus clawed back in the trailing 24 months adds 5; each participation event verified in the trailing 12 months subtracts 6; and each advancement in the trailing 24 months subtracts 20, resetting the decay baseline as it lands. The result clamps into the 0-to-100 band.

Outcome analysis runs on snapshots rather than live reads. During the ops-run sweep the system captures one `RetentionSnapshot` per unit plus one hospital-wide row whose `unit` reads "ALL", stamping each with the `captured_at` clock position. A snapshot counts the population into `headcount_by_level` across the four rungs, averages the population's risk scores into `avg_retention_risk_score` rounded half-up to two decimal places, and computes `demotion_rate` as the count of reviews closed `DEMOTE` in the trailing twelve months — closure timestamps in the half-open window from twelve months before the capture up to but excluding the capture instant — divided by the snapshot headcount, rounded half-up to four decimal places. An empty unit is not an error: its demotion rate is 0.0000 and its average risk score 0.00. Snapshots are immutable once captured and can be listed with a `unit` filter, giving the `RetentionAnalyst` a stable series for year-over-year retention study.

## 4. Endpoint Definitions

All endpoints are mounted under `/clinical-ladder`. Creating a new resource returns HTTP 201 with the created resource; every other successful operation — reads, state transitions, updates — returns HTTP 200. The table below is a navigational summary only; request payloads, response shapes, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /clinical-ladder/nurses | Register a nurse in the program | ProgramAdmin |
| GET | /clinical-ladder/nurses | List nurses with pagination and optional filters | ProgramAdmin, PayrollOfficer, RetentionAnalyst |
| GET | /clinical-ladder/nurses/{id} | Fetch one nurse including computed fields | ProgramAdmin, PayrollOfficer, RetentionAnalyst, Nurse |
| GET | /clinical-ladder/nurses/{id}/participation-events | List a nurse's participation events | ProgramAdmin, Nurse, RetentionAnalyst |
| GET | /clinical-ladder/nurses/{id}/certifications | List a nurse's certifications | ProgramAdmin, Nurse |
| GET | /clinical-ladder/nurses/{id}/applications | List a nurse's applications | ProgramAdmin, Nurse |
| GET | /clinical-ladder/nurses/{id}/anniversary-reviews | List a nurse's anniversary reviews | ProgramAdmin, Nurse |
| POST | /clinical-ladder/ladder-criteria | Publish a criterion set for a target level with a validity window | ProgramAdmin |
| GET | /clinical-ladder/ladder-criteria | List criterion sets | ProgramAdmin, Nurse |
| GET | /clinical-ladder/ladder-criteria/{id} | Fetch one criterion set | ProgramAdmin, Nurse |
| POST | /clinical-ladder/participation-events | Nurse logs a participation event (enters PENDING_VERIFICATION) | Nurse |
| GET | /clinical-ladder/participation-events | Filtered list of participation events across nurses | ProgramAdmin, RetentionAnalyst |
| POST | /clinical-ladder/participation-events/{id}/verify | Admin verifies a pending event | ProgramAdmin |
| POST | /clinical-ladder/participation-events/{id}/void | Admin voids a pending event | ProgramAdmin |
| POST | /clinical-ladder/certifications | Register an earned certification; accrues a bonus as side effect | ProgramAdmin |
| GET | /clinical-ladder/certifications | Filtered list of certifications | ProgramAdmin, Nurse |
| GET | /clinical-ladder/certifications/{id} | Fetch one certification | ProgramAdmin, Nurse |
| GET | /clinical-ladder/certifications/{id}/reimbursement-claims | List claims on a certification | ProgramAdmin, PayrollOfficer, Nurse |
| GET | /clinical-ladder/certifications/{id}/certification-bonuses | List bonuses on a certification | ProgramAdmin, PayrollOfficer, Nurse |
| POST | /clinical-ladder/certifications/{id}/revoke | Revoke a current certification; claws back recently paid bonuses | ProgramAdmin |
| POST | /clinical-ladder/reimbursement-claims | Nurse files an exam-fee reimbursement claim | Nurse |
| GET | /clinical-ladder/reimbursement-claims/{id} | Fetch one claim | ProgramAdmin, PayrollOfficer, Nurse |
| POST | /clinical-ladder/reimbursement-claims/{id}/approve | Approve a claim under the per-nurse fiscal-year cap | ProgramAdmin |
| POST | /clinical-ladder/reimbursement-claims/{id}/deny | Deny a claim with reason | ProgramAdmin |
| POST | /clinical-ladder/reimbursement-claims/{id}/pay | Payroll disburses an approved claim under the unit budget guard | PayrollOfficer |
| POST | /clinical-ladder/certification-bonuses/{id}/pay | Payroll pays an accrued bonus under the unit budget guard | PayrollOfficer |
| POST | /clinical-ladder/certification-bonuses/{id}/claw-back | Admin claws back an accrued or paid bonus | ProgramAdmin |
| POST | /clinical-ladder/applications | Nurse drafts a ladder application (OCC on the nurse's version) | Nurse |
| GET | /clinical-ladder/applications | Filtered list of applications | ProgramAdmin, Nurse |
| GET | /clinical-ladder/applications/{id} | Fetch one application | ProgramAdmin, Nurse |
| POST | /clinical-ladder/applications/{id}/submit | Submit a draft or returned application; pins criterion and participation snapshot | Nurse |
| POST | /clinical-ladder/applications/{id}/withdraw | Applicant withdraws from DRAFT or SUBMITTED | Nurse |
| POST | /clinical-ladder/applications/{id}/assignments | Admin assigns a committee reviewer; first assignment moves the application to IN_REVIEW | ProgramAdmin |
| GET | /clinical-ladder/applications/{id}/assignments | List an application's review assignments | ProgramAdmin, Nurse |
| GET | /clinical-ladder/applications/{id}/decisions | List an application's append-only decisions | ProgramAdmin, Nurse |
| GET | /clinical-ladder/review-assignments | Filtered list of review assignments across applications | ProgramAdmin, Nurse |
| GET | /clinical-ladder/review-assignments/{id} | Fetch one review assignment | ProgramAdmin, Nurse |
| POST | /clinical-ladder/review-assignments/{id}/score | Assigned reviewer submits four-dimension scores | Nurse |
| POST | /clinical-ladder/review-assignments/{id}/recuse | Assigned reviewer recuses themselves | Nurse |
| POST | /clinical-ladder/applications/{id}/return-for-revision | Admin returns an in-review application; expires pending assignments; cycles to DRAFT | ProgramAdmin |
| POST | /clinical-ladder/applications/{id}/decide | Admin renders an APPROVE or DENY decision (OCC on the application's version) | ProgramAdmin |
| POST | /clinical-ladder/anniversary-reviews | Admin opens an anniversary maintenance review for a nurse | ProgramAdmin |
| POST | /clinical-ladder/anniversary-reviews/{id}/close | Close a review with SUSTAIN or DEMOTE; DEMOTE triggers the demotion cascade | ProgramAdmin |
| POST | /clinical-ladder/budget-lines | Create a unit fiscal-year budget line | ProgramAdmin |
| GET | /clinical-ladder/budget-lines | List budget lines | ProgramAdmin, PayrollOfficer |
| GET | /clinical-ladder/budget-lines/{id} | Fetch one budget line with current forecast | ProgramAdmin, PayrollOfficer |
| PUT | /clinical-ladder/budget-lines/{id} | Update allocation (OCC on the budget line's version) | ProgramAdmin |
| GET | /clinical-ladder/retention-snapshots | List captured retention snapshots | RetentionAnalyst, ProgramAdmin |
| POST | /clinical-ladder/_clock/set_current_utc | Set the logical clock; default at server start is exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time | ProgramAdmin |
| POST | /clinical-ladder/_ops/run_cycle | Ops-run sweep at the current logical clock: lapses expired certifications, expires stale assignments, lapses overdue reviews, closes fiscal-year budget lines, captures retention snapshots | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_LADDER_RUNG_VIOLATION | 422 |
| ERR_NO_ACTIVE_CRITERION | 422 |
| ERR_CRITERION_WINDOW_OVERLAP | 409 |
| ERR_DIFFERENTIAL_MONOTONICITY | 422 |
| ERR_QUORUM_EXCEEDED | 422 |
| ERR_DUPLICATE_REVIEWER | 409 |
| ERR_REVIEW_WINDOW_EXPIRED | 422 |
| ERR_PARTICIPATION_POINTS_RANGE | 422 |
| ERR_CERTIFICATION_DATE_ORDER | 422 |
| ERR_RENEWAL_MISMATCH | 422 |
| ERR_CERTIFICATION_OVERLAP | 409 |
| ERR_CLAIM_EXCEEDS_FEE | 422 |
| ERR_REIMBURSEMENT_CAP_EXHAUSTED | 402 |
| ERR_BUDGET_EXCEEDED | 402 |
| ERR_CANNOT_DEMOTE_FLOOR | 422 |
| ERR_MAINTENANCE_SCORE_INSUFFICIENT | 422 |
| ERR_REVIEW_CYCLE_EXHAUSTED | 422 |
| ERR_STALE_REFERENCE | 409 |

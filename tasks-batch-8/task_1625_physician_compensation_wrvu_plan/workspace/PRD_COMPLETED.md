# Physician Comp wRVU API — Product Requirements Document

## 1. Introduction

A medical group's compensation office lives or dies on two numbers: the work relative value units (wRVU) each physician produces, and the dollars those wRVUs convert into under the physician's compensation plan. Between those two numbers sits a thicket of rules — CPT-specific crediting rates with effective windows, productivity tiers whose thresholds shift with a physician's clinical FTE, quality and citizenship bonus pools scored under one of two models, supervision credits owed to physicians who oversee advanced-practice providers, and the ever-present fair-market-value (FMV) constraints that regulators impose on physician pay. When any of these inputs changes mid-year — a plan is renegotiated, a capture is disputed and corrected, a rate table is republished — the office must reconcile what was paid against what should have been paid, and it must be able to show its work.

This document specifies an API that administers that entire lifecycle. The system maintains the physician roster, versions compensation plans from draft through compliance review to activation, enrolls physicians into plans under FMV-reviewed agreements, captures clinical production and credits wRVUs against effective-dated rate rows, allocates supervision credit to overseeing physicians, scores quality scorecards, generates periodic compensation statements under a locked-basis ledger, runs mid-year true-up reconciliations, adjudicates physician disputes with data-correction cascades, and orchestrates plan changes with modeling, physician acknowledgment, and a supervised succession cascade. A logical clock drives every date-sensitive rule so that cooling-off windows, FMV freshness, and scheduled plan changes are deterministic. The API is mounted under `/comp`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares the role under which the user acts. The declared roles, spelled exactly as shown, are `SystemAdmin`, `CompAnalyst`, `ComplianceOfficer`, `CompCommittee`, and `Physician`.

- A `SystemAdmin` is the platform operator: it owns the logical clock and the physician roster and nothing else.
- A `CompAnalyst` is the compensation-office analyst: it drafts plans, rate rows, and agreements; posts and validates production; runs statements and true-ups; triages disputes; and drafts plan changes. It never approves compliance artifacts and never finalizes payments.
- A `ComplianceOfficer` is the independent reviewer for plan review decisions and agreement FMV reviews, and is structurally segregated from the creator of the artifact under review.
- A `CompCommittee` member holds activation and finalization authority: plan activation and closure, agreement activation and termination, statement finalization and voiding, true-up posting, dispute resolution, and plan-change activation.
- A `Physician` is an employed physician or advanced-practice provider reading its own compensation data, filing disputes on its own captures and statements, and acknowledging communicated plan changes.

When `X-User-Role` is `SystemAdmin`, `CompAnalyst`, `ComplianceOfficer`, or `CompCommittee`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on an agreement, capture, or statement, as `fmv_reviewer_user_id` on an agreement, or as `resolver_user_id` on a dispute) but does not compare it to any entity's `id` except where a segregation-of-duties rule says otherwise. When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician`; ownership checks on any resource that references a `Physician` compare the resource's physician foreign-key field to `X-User-ID`. A `Physician`-role caller may read only its own physician record, its own agreements, statements, and captures, list only its own disputes, file disputes only on subjects belonging to its own agreement, and acknowledge plan changes only for plans it is enrolled in; any other access is refused with `ERR_NOT_OWN_RESOURCE`.

A request missing either header, carrying an undeclared role, or — for the `Physician` role — carrying an `X-User-ID` that is not the `id` of an existing physician is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

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

Requests to an unknown path, and requests to a known path with an unsupported method, are answered in this same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0 and may not be negative; a non-integer or out-of-range `limit` or `offset` is rejected with `ERR_VALIDATION`. Results are always sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock and Date Semantics

The server maintains a logical clock, and every date- or deadline-sensitive rule in this document — the FMV cooling-off window, FMV freshness at activation, the staleness computation behind `compliance_hold`, the default `posting_date` of a capture, and plan-change timing — reads that clock and nothing else. At startup, before any clock-setting call, the logical clock is exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. A `SystemAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` timestamp and answers with the resulting `current_utc`. Setting the clock has one immediate side effect: every agreement in `EFFECTIVE` status has its `compliance_hold` flag recomputed against the new time.

Calendar dates elsewhere in the API use the ISO 8601 `YYYY-MM-DD` form, while measurement and statement periods use the `YYYY-MM` month bucket form. An ill-formed date in any payload is a payload-shape failure.

### 2.5. Common Resource Properties

Every resource in this API carries four system-managed properties in addition to its business fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation; and `version`, an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of that resource — including mutations caused by cascade side effects originating on another resource. Reading a plan exposes its current `version`, which clients use for the optimistic-concurrency checks described next. Request bodies carry only the business fields documented for each operation; client-supplied values for system-managed or server-computed fields, and any other undocumented fields, are ignored.

### 2.6. Plan Editing and Optimistic Concurrency Control

A compensation plan's configuration — its name, attribution mode, quality model, tier schedule, quality pool, FMV cap — and its rate rows are mutable only while the plan is in `DRAFT` or `PENDING_REVIEW` status. Any attempt to edit the plan configuration, add a rate row, or delete a rate row once the plan has left those statuses is rejected with `ERR_PLAN_IMMUTABLE` (HTTP 409).

Two write operations are guarded by optimistic concurrency control, both keyed on the plan:

- Editing a plan's configuration requires the request to carry `expected_comp_plan_version`, the plan `version` the client last observed. If the plan's current `version` has advanced beyond that value — because another writer submitted the plan for review, edited it, or otherwise mutated it in the meantime — the update is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than applied over changes the client never saw. On this call the staleness check runs after payload-shape validation and before tier-ordering re-validation.
- Proposing a plan-change request likewise requires `expected_comp_plan_version`. Creating a plan-change request legitimately withdraws any existing `PROPOSED` or `MODELED` change requests for the same plan (a create-with-supersede), so a client holding a stale plan `version` would silently supersede a change request it never saw; the stale create is refused with `ERR_STALE_VERSION` (HTTP 412). Here the staleness check runs after payload-shape validation and before the successor-linkage check.

No other endpoint takes a version field.

### 2.7. Precision, Rounding, and Monetary Representation

All money is represented as integer cents — base salaries, draws, bonus pools, conversion factors, tier bonuses, statement amounts, true-up adjustments, and the FMV cap are all cent-denominated integers. wRVU quantities are decimal: a rate row's `wrvu_value` may carry up to 3 decimal places, and a capture's credited wRVU is pinned to 2 decimal places using round-half-up, computed per capture and never aggregated before rounding. A supervision assignment's `credit_pct` is a fraction greater than 0 and at most 1, carried to up to 4 decimal places. Where a calculation produces a cent amount from decimal inputs — tiered productivity earnings, the quality bonus, per-agreement modeling deltas — the final amount is rounded half-up to whole cents. Measure scores and thresholds on quality scorecards range from 0 to 100.

### 2.8. Segregation of Duties

Three handoffs in the compensation lifecycle are segregated: the person who created an artifact may not be the person who approves or finalizes it. First, the `ComplianceOfficer` recording an FMV decision on an agreement must not be the `CompAnalyst` whose `X-User-ID` was recorded as the agreement's `created_by_user_id`. Second, the `CompCommittee` member finalizing a compensation statement must not be the analyst recorded as that statement's `created_by_user_id`. Third, the committee member who accepts a capture dispute must not be the analyst recorded as the subject capture's `created_by_user_id`. A violation of any of the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.9. Validation Order

Requests are checked against a fixed ladder, and when several checks could fail on the same call, the earliest category on the ladder determines the error returned. Authentication comes first (missing, malformed, or unresolvable identity — `ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED_ROLE`), then physician ownership (`ERR_NOT_OWN_RESOURCE`). Existence follows: path parameters and body foreign-key references must resolve to existing resources, validated left to right along the path, otherwise `ERR_NOT_FOUND`. Next is the generic state-machine guard (`ERR_INVALID_STATE`), then the domain state rules — plan immutability (`ERR_PLAN_IMMUTABLE`), plan not FMV-approved (`ERR_PLAN_NOT_FMV_APPROVED`), plan not active (`ERR_PLAN_NOT_ACTIVE`), agreement not effective (`ERR_AGREEMENT_NOT_EFFECTIVE`). Business-safety rules follow those: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), FMV cooling-off (`ERR_FMV_COOLING_OFF`), compliance hold (`ERR_COMPLIANCE_HOLD`), and FMV staleness (`ERR_FMV_STALE`). Payload shape (`ERR_VALIDATION`) is checked next, then business constraints (tier ordering, rate-window overlap, successor uniqueness, supervision party/window rules, duplicates, open disputes, true-up guards, successor linkage), then temporal rules (period locked, statement chronology, plan-change timing), then referential rules (rate coverage, dispute-subject consistency). The fiscal FMV cap (`ERR_FMV_CAP_EXCEEDED`) is evaluated last. Section 3 restates the concrete per-endpoint orderings wherever several of these checks guard one operation.

### 2.10. Nested Retrieval and Cascading Consistency

Several resources live beneath a parent in the URL hierarchy — rate rows, true-up runs, and plan-change requests beneath a plan; captures, scorecards, and statements beneath an agreement. On any nested request, path parameters are validated from left to right: the parent must exist, then the child must exist and belong to that parent, and the first failure yields `ERR_NOT_FOUND`.

State changes propagate. When one operation mutates several entities — a plan supersession flipping agreements, a statement finalization locking captures, a dispute resolution reversing a capture and its supervision children — every touched entity increments its own `version` by 1 and refreshes its `updated_at`. Ledger totals bubble up the same way: crediting, reversing, or allocating production recomputes the owning agreement's `ytd_wrvu_credited`, and finalizing or voiding a statement recomputes the agreement's `lifetime_paid_cents`. These recomputations are part of the originating operation, not deferred work.

## 3. Business Logic & Workflows

### 3.1. The Physician Roster and Drafting a Compensation Plan

Before any money moves, a `SystemAdmin` registers each clinician in the roster. Registration captures the clinician's `npi` (a National Provider Identifier of exactly 10 digits, unique across all physicians; a malformed or duplicate `npi` is rejected with `ERR_VALIDATION`), `full_name`, free-form `specialty` code, `provider_type` (one of `PHYSICIAN` or `APP` — a physician can supervise and holds a compensation agreement, while an advanced-practice provider's production can generate supervision credits), clinical `fte` (a fraction greater than 0 and at most 1.0, used to prorate tier thresholds), and `hire_date`. Reading a physician record is open to the back-office roles, while a `Physician`-role caller may read only the record whose `id` matches its own `X-User-ID`.

A `CompAnalyst` then drafts a compensation plan. The draft carries a display `name`, the inclusive fiscal-year bounds `fiscal_year_start` and `fiscal_year_end` (the end must be after the start — a violation is `ERR_VALIDATION`), a `credit_attribution_mode` of `SERVICE_DATE` or `POSTING_DATE` defaulting to `SERVICE_DATE` when omitted, a `quality_model` of `ALL_OR_NOTHING` or `SLIDING_SCALE` defaulting to `ALL_OR_NOTHING`, an ordered `tiers` schedule, a non-negative `quality_pool_cents` per-period bonus pool, and a positive `fmv_cap_cents` ceiling on projected annual total compensation. Each tier element names a `tier_code`, an annual `threshold_wrvu` expressed at FTE 1.0, a `conversion_factor_cents` rate, and a flat `tier_bonus_cents`. The tier schedule must contain at least one tier, its first `threshold_wrvu` must be 0, and thresholds must be strictly increasing; a schedule violating any of these is rejected with `ERR_TIER_ORDER_INVALID`. Payload-shape failures on any of these inputs — a missing required field, a wrong type, an out-of-range enum, an `fte` outside the allowed band, a malformed date — are rejected with `ERR_VALIDATION`. On the tiered plan-creation call, payload shape is checked before the tier-ordering rule, so a malformed body surfaces as `ERR_VALIDATION` rather than `ERR_TIER_ORDER_INVALID`.

A plan may also be drafted as the successor of an existing `ACTIVE` plan by setting `supersedes_plan_id` to that plan's `id` (the field is null for an original plan). A `supersedes_plan_id` that does not resolve to an existing plan is rejected with `ERR_NOT_FOUND`, and one that resolves to a plan not in `ACTIVE` status is rejected with `ERR_VALIDATION`. At most one non-terminal successor — one whose `status` is `DRAFT`, `PENDING_REVIEW`, or `FMV_APPROVED` — may exist per superseded plan; drafting a second is rejected with `ERR_SUCCESSOR_EXISTS`. That check runs after payload shape and tier ordering on the creation call. A plan is born in `DRAFT` status with `version` 1, and a dedicated listing answers the plans whose `supersedes_plan_id` points at a given plan, so the office can trace the succession chain in reverse.

Rate rows hang beneath the plan. Each row prices one `cpt_code` with a non-negative `wrvu_value` (up to 3 decimal places) over a half-open effectiveness window: the row covers service dates from `effective_from` inclusive up to but not including `effective_to`, and `effective_to` must be strictly after `effective_from`. Two rows on the same plan with the same `cpt_code` may not have overlapping windows — adjacency, where one row's `effective_to` equals the next row's `effective_from`, is allowed — and an overlapping addition is rejected with `ERR_RATE_WINDOW_OVERLAP`. Rows may be added or deleted only while the owning plan is `DRAFT` or `PENDING_REVIEW`; later attempts draw `ERR_PLAN_IMMUTABLE`, and that immutability check precedes the overlap check on the add call. The plan's rate listing supports an optional `cpt_code` filter alongside `limit` and `offset`.

### 3.2. Plan Review, Activation, and Closure

Once a draft plan has at least one rate row, a `CompAnalyst` submits it for compliance review, moving `status` from `DRAFT` to `PENDING_REVIEW` and incrementing the plan's `version`. Submitting a plan with no rate rows at all is rejected with `ERR_RATE_COVERAGE_INCOMPLETE`, as is any later activation attempt in that condition.

A `ComplianceOfficer` then records a review `decision`. An `APPROVED` decision moves the plan from `PENDING_REVIEW` to `FMV_APPROVED`; a `REJECTED` decision sends it back to `DRAFT` for editing — the review loop branches and reverts rather than terminating. Either decision increments the plan's `version`.

Activation is the committee's act: a `CompCommittee` member activates an `FMV_APPROVED` plan, which stamps `activated_at` with the logical-clock timestamp (the field stays null until this moment) and moves the plan to `ACTIVE`. Attempting activation from any other status is rejected with `ERR_PLAN_NOT_FMV_APPROVED`, and recall that activation also requires at least one rate row. Only an `ACTIVE` plan accepts production-bearing agreements at scale.

Closure is also the committee's act. An `ACTIVE` plan may be closed only when no agreement referencing it remains in any non-terminal status — that is, no linked agreement is `DRAFT`, `PENDING_FMV`, `FMV_APPROVED`, `EFFECTIVE`, or `AMENDMENT_REQUIRED`; every agreement must have reached `TERMINATED`. An attempt to close while any linked agreement remains non-terminal is rejected with `ERR_INVALID_STATE`. Closing moves the plan to `CLOSED`, a terminal state alongside `SUPERSEDED`, and increments its `version`.

### 3.3. Agreement Enrollment and Fair-Market-Value Review

Enrolling a clinician into a plan creates a physician agreement. A `CompAnalyst` supplies the `physician_id` (the enrollee may be a `PHYSICIAN` or an `APP`), the `plan_id`, a positive annual `base_salary_cents` guarantee, a non-negative `period_draw_cents` monthly draw paid regardless of productivity, and the `effective_date` from which production may be captured. The referenced plan must be `FMV_APPROVED` or `ACTIVE`; enrolling against a plan in any other status is rejected with `ERR_PLAN_NOT_ACTIVE`. Only one non-terminal agreement may exist per physician-and-plan pair, so a duplicate enrollment for the same `physician_id` and `plan_id` while an earlier agreement is still `DRAFT`, `PENDING_FMV`, `FMV_APPROVED`, `EFFECTIVE`, or `AMENDMENT_REQUIRED` is rejected with `ERR_DUPLICATE_RESOURCE`. At creation the agreement snapshots the plan's current `version` into `pinned_plan_version` — version-pinning on approval — and records the caller's `X-User-ID` as `created_by_user_id` for later segregation-of-duties checks. The agreement listing accepts optional `physician_id`, `plan_id`, and `status` filters.

A new agreement sits in `DRAFT`. Submitting it for FMV review moves it to `PENDING_FMV`, subject to a cooling-off rule: if the agreement's `last_fmv_rejected_at` is set and the logical-clock date falls within thirty days after it, the submission is rejected with `ERR_FMV_COOLING_OFF`; once the clock date is at least thirty days past the rejection — or no rejection was ever recorded — the submission proceeds and increments the agreement's `version`. On that submission call the generic state guard fires first for an agreement in the wrong status, and the cooling-off check follows it.

The `ComplianceOfficer`'s FMV review carries a `decision` and a `benchmark_percentile` between 0 and 100. The reviewer's `X-User-ID` must differ from the agreement's `created_by_user_id`; a same-user decision is rejected with `ERR_SEGREGATION_OF_DUTIES`, and on this operation the state guard is evaluated before the segregation check. An `APPROVED` decision moves the agreement `PENDING_FMV → FMV_APPROVED` and stamps `fmv_reviewed_at` with the clock timestamp, `fmv_reviewer_user_id` with the reviewer, and `fmv_benchmark_percentile` with the submitted percentile (all three remain null until the first approval). A `REJECTED` decision returns the agreement to `DRAFT` and stamps `last_fmv_rejected_at`, starting the thirty-day cooling-off window.

Activation moves an `FMV_APPROVED` agreement to `EFFECTIVE` and is guarded by three checks in ladder order after existence and state: the referenced plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`); the FMV review must still be fresh, meaning the logical clock is no later than twelve months after `fmv_reviewed_at`, otherwise `ERR_FMV_STALE`; and the FMV cap must hold — the agreement's `base_salary_cents` plus its projected annual productivity at the current year-to-date pace must not exceed the plan's `fmv_cap_cents`, otherwise `ERR_FMV_CAP_EXCEEDED`. The projection annualizes the agreement's `ytd_wrvu_credited` over the months elapsed since its `effective_date` — whole calendar months between the `effective_date` and the clock date, counted as `(year difference) × 12 + (month difference)` and floored at 1 — and prices that annualized volume through the plan's marginal tier formula at the physician's `fte`.

FMV approval is not permanent. While an agreement is `EFFECTIVE`, the server continuously derives its `compliance_hold` flag: the flag is true exactly when the agreement is `EFFECTIVE` and the logical clock has moved strictly later than twelve months after `fmv_reviewed_at`. A held agreement cannot accept new production postings and cannot validate pending captures — both are rejected with `ERR_COMPLIANCE_HOLD`. To cure the hold, an analyst re-submits the agreement for FMV review: the re-review cycle moves an `EFFECTIVE` agreement back to `PENDING_FMV` (subject to the same cooling-off rule), and while it sits in `PENDING_FMV` it cannot accept new production captures, because posting requires `EFFECTIVE` status.

Two terminal paths exist. The committee may terminate an agreement in `EFFECTIVE` or `AMENDMENT_REQUIRED` status, moving it to `TERMINATED` and voiding any of its statements still in `DRAFT`. And when a plan is superseded (see §3.9), each of its `EFFECTIVE` agreements is flipped to `AMENDMENT_REQUIRED`; an analyst then re-pins such an agreement onto the successor — re-pinning requires an `ACTIVE` plan whose `supersedes_plan_id` equals the agreement's current `plan_id` (when no such successor exists the re-pin is rejected with `ERR_INVALID_STATE`), sets the agreement's `plan_id` to that successor and its `pinned_plan_version` to the successor's current `version`, and returns the agreement to `EFFECTIVE`.

### 3.4. Production Capture and wRVU Crediting

Against an `EFFECTIVE` agreement, a `CompAnalyst` posts a clinical production capture with the service's `cpt_code`, a `units` count of at least 1, the `service_date`, and an optional `posting_date` that defaults to the logical-clock date at creation. Three guards protect posting, in this order after the state ladder: the agreement must be `EFFECTIVE` (`ERR_AGREEMENT_NOT_EFFECTIVE`); a compliance hold must not be in force (`ERR_COMPLIANCE_HOLD`); and the `service_date` must not fall inside a period already covered by a `FINALIZED` statement on the same agreement — the period is locked once paid, and such a posting is rejected with `ERR_PERIOD_LOCKED`. Payload shape (`units` below 1, malformed dates) surfaces as `ERR_VALIDATION` between the compliance-hold check and the period-lock check. A posted capture is born with `capture_status` `POSTED`, `credit_status` `UNCREDITED`, `capture_kind` `CLINICAL`, and the poster's `X-User-ID` recorded as `created_by_user_id`; its `credited_wrvu`, `credited_period`, and `wrvu_value_applied` stay null, and `reversal_of_capture_id` and `source_capture_id` are null. The agreement's capture listing accepts an optional `credit_status` filter.

Validation is where production becomes ledger. Validating a capture requires it to still be `POSTED` and `UNCREDITED` (anything else is `ERR_INVALID_STATE`) and the agreement to be free of a compliance hold. For a `CLINICAL` capture the server resolves the unique rate row on the agreement's plan whose `cpt_code` matches and whose half-open window covers the `service_date`; if no such row exists the validation is rejected with `ERR_RATE_NOT_FOUND`. The resolved `wrvu_value` is snapshotted into `wrvu_value_applied`, and `credited_wrvu` is computed as `units` multiplied by `wrvu_value_applied`, rounded half-up to 2 decimal places. The `credited_period` month bucket is then assigned per the plan's `credit_attribution_mode`: under `SERVICE_DATE` the bucket is the month of the `service_date` — a capture served 2026-02-10 and posted 2026-03-02 lands in period 2026-02 — while under `POSTING_DATE` the identical capture lands in 2026-03, shifting tier attainment and statement inclusion by a month. Validation moves the capture `POSTED → VALIDATED` and `UNCREDITED → CREDITED`, increments the capture's `version`, recomputes the owning agreement's `ytd_wrvu_credited` (the running sum of `credited_wrvu` over the agreement's `CREDITED` captures, kept at 2 decimal places), and increments the agreement's `version` as well. If the producing clinician is an `APP`, validation also fires the supervision-allocation cascade described in §3.5.

A capture that was posted in error and never validated can be voided: voiding moves a `POSTED`, still-`UNCREDITED` capture to `VOIDED`. The void is documentation-only — an uncredited capture never entered the ledger, so no compensation cascade accompanies it.

Two reverse-listing endpoints complete the capture picture: one lists the replacement captures whose `reversal_of_capture_id` points at a given capture (the correction trail built by dispute resolution), and another lists the `SUPERVISION_CREDIT` captures whose `source_capture_id` points at a given APP capture. A third lists the disputes filed against the capture.

### 3.5. Supervision Assignments and Credit Allocation

Supervision is contractual before it is computational. A `CompAnalyst` creates a supervision assignment naming the `supervisor_physician_id` and the `app_physician_id`, the inclusive window `start_date` through `end_date` (the end must not precede the start), the `credit_pct` of the APP's credited wRVU owed to this supervisor per qualifying capture, and the `supervised_fte` the arrangement counts against the supervisor's capacity — itself greater than 0 and at most 4.0, with an out-of-band value rejected as `ERR_VALIDATION`. Creation enforces a fixed sequence after payload shape: the supervisor must have `provider_type` `PHYSICIAN`, the APP must have `provider_type` `APP`, and the two must differ, otherwise `ERR_PROVIDER_TYPE_INVALID`; both parties must hold `EFFECTIVE` agreements on the same plan, otherwise `ERR_NO_EFFECTIVE_AGREEMENT`; and three window rules, otherwise `ERR_SUPERVISION_WINDOW_INVALID` — for the same supervisor-APP pair the closed windows must not overlap, across overlapping windows for the same APP the `credit_pct` values must sum to at most 1.0 inclusive, and on any overlapping day a supervisor's `supervised_fte` commitments must sum to at most 4.0. Only other `ACTIVE` assignments count toward these three window rules. The assignment listing accepts optional `supervisor_physician_id`, `app_physician_id`, and `status` filters.

An assignment is born `ACTIVE` and stays `ACTIVE` until explicitly ended; reaching the window's `end_date` does not change `status`, though it does bound allocation. Ending an assignment accepts a new `end_date`, requires only that it not precede the `start_date` (otherwise `ERR_SUPERVISION_WINDOW_INVALID`), and moves the assignment to `ENDED`; the three window rules are not re-run on this call, since a narrowed window cannot newly violate them.

The allocation cascade fires when an APP's clinical capture is validated. The server collects every `ACTIVE` assignment for that APP whose window contains the capture's `service_date`, then processes them in a pinned order — earlier `start_date` first, ties broken by earlier `created_at`. For each assignment it computes the allocation as the APP capture's `credited_wrvu` multiplied by the assignment's `credit_pct`, rounded half-up to 2 decimal places per assignment; rounding per assignment and then summing is the pinned behavior, and summing-then-rounding is explicitly rejected because it produces different totals. There is no remainder redistribution — rounding dust stays with the APP. Each allocation materializes as a `SUPERVISION_CREDIT` capture on the supervisor's own agreement: born directly in `VALIDATED` and `CREDITED`, carrying `cpt_code` `SUPV`, `units` 1, the APP capture's `service_date` and `posting_date`, a null `wrvu_value_applied`, the allocated amount as its `credited_wrvu`, a `credited_period` bucketed per the supervisor's plan's attribution mode, `source_capture_id` pointing back to the APP capture, and a null `created_by_user_id`. If the supervisor no longer holds an `EFFECTIVE` agreement on the APP's plan at validation time, that assignment's allocation is skipped and no credit is created for it. Every created supervisor credit in turn recomputes the supervisor agreement's `ytd_wrvu_credited` — a second cascade hop.

### 3.6. Quality Scorecards and the Quality Bonus

Quality and citizenship incentives enter through scorecards. A `CompAnalyst` records a scorecard beneath an agreement for a measurement `period` in `YYYY-MM` form, with a `measures` array containing at least one entry; each entry names a `measure_code` (unique within the scorecard), an integer `weight` greater than 0, a `threshold_score` between 0 and 100, and an achieved `score` between 0 and 100. Only one scorecard may exist per agreement and period — a repeat is rejected with `ERR_DUPLICATE_RESOURCE`. A scorecard is born `DRAFT` with `quality_bonus_cents` null.

Finalization is irreversible and is where the bonus crystallizes. Finalizing a `DRAFT` scorecard moves it to `FINALIZED` and computes `quality_bonus_cents` from the plan's `quality_model` and per-period `quality_pool_cents`, freezing the value. Under `ALL_OR_NOTHING`, a measure contributes its full `weight` only when its `score` is at least its `threshold_score`, and contributes nothing otherwise. Under `SLIDING_SCALE`, a measure contributes its `weight` multiplied by the ratio of `score` to `threshold_score`, capped at the full weight when the score meets or exceeds the threshold — so a half-met measure earns half its weight, and identical scores yield a strictly larger bonus than the all-or-nothing model whenever any measure is partially met. A `threshold_score` of 0 is always met, so it contributes the full weight under either model. In both models the bonus is the pool multiplied by the total earned weight divided by the summed weights of all measures, rounded half-up to whole cents.

### 3.7. Compensation Statements, Settlement, and Mid-Year True-Up

Statement generation turns the ledger into a payable. A `CompAnalyst` generates a statement beneath an agreement for a `period_year` and `period_month` (1 through 12). Periods must move strictly forward: the new period must be later than every existing statement period on the agreement, otherwise `ERR_STATEMENT_PERIOD_ORDER`, and only one statement may exist per agreement and period, otherwise `ERR_DUPLICATE_RESOURCE` — on the generation call the duplicate check precedes the chronology check, and statements in any status, including `VOIDED`, count as existing for both checks. Generation records the analyst's `X-User-ID` as the statement's `created_by_user_id` and computes every derived field in a pinned evaluation order.

First, `trueup_adjustment_cents` snapshots the agreement's `pending_trueup_adjustment_cents` — a snapshot only, never recomputed from the statement's own fields — and the agreement's pending field is immediately reset to 0; this reset mutates the agreement, so generation also increments the agreement's `version`. The pending field is 0 from agreement creation until a true-up run posts over it, so a statement generated without a posted true-up shows `trueup_adjustment_cents` 0. Second, the period's production is gathered: `capture_ids` collects the ids of the agreement's `CREDITED` captures whose `credited_period` equals the statement period, ordered by the captures' `created_at` ascending, and `period_wrvu` sums their `credited_wrvu` at 2 decimal places. Third, `ytd_wrvu_at_close` is assembled on a locked basis: the sum of `period_wrvu` across the agreement's `FINALIZED` statements — frozen at their finalized values, immune to later reversals in those periods — plus the `credited_wrvu` of captures currently `CREDITED` whose `credited_period` falls at or before the statement period and is not covered by any `FINALIZED` statement. Fourth, productivity is priced. Tier floors and caps are prorated by the physician's `fte` — an FTE of 0.8 turns a 5000-wRVU threshold into 4000 — while conversion factors and tier bonuses are not prorated. Walking the `tiers` in ascending `threshold_wrvu` order, only the wRVUs falling between a tier's prorated floor and the next tier's prorated floor (unbounded for the top tier) earn that tier's `conversion_factor_cents`; the marginal sum across tiers, rounded half-up to whole cents, is `productivity_earned_ytd_cents`. The `tier_attained` is the `tier_code` of the highest tier whose prorated threshold is at most `ytd_wrvu_at_close`, threshold equality counting as attainment. The `tier_bonus_cents` pays the attained tier's flat bonus only if no prior non-`VOIDED` statement of this agreement attained the same or a higher tier — each tier's bonus is paid once per agreement — and is 0 otherwise. The `period_productivity_cents` is the chronological cumulative delta: `productivity_earned_ytd_cents` minus the sum of `period_productivity_cents` over all prior non-`VOIDED` statements, and it may go negative after reversals. Fifth, `quality_bonus_cents` copies the bonus of the `FINALIZED` scorecard whose `period` matches the statement period, or 0 when none exists. Sixth, `period_draw_cents` snapshots the agreement's draw at generation. Finally, `net_payment_cents` is `period_productivity_cents` plus `tier_bonus_cents` plus `quality_bonus_cents` plus `trueup_adjustment_cents` minus `period_draw_cents`; a negative result is allowed and represents a receivable from the physician, with no floor at zero. A new statement is born `DRAFT`.

The approval chain then runs. An analyst submits a `DRAFT` statement for review, moving it to `UNDER_REVIEW`. The committee finalizes an `UNDER_REVIEW` statement — but only when no dispute on the same agreement sits in `FILED`, `UNDER_REVIEW`, or `DATA_CORRECTION` (`ERR_OPEN_DISPUTES`), and only when the finalizer's `X-User-ID` differs from the statement's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); on the finalize call the state guard fires first, then segregation of duties, then the open-disputes check. Finalization moves the statement to `FINALIZED`, locks every included capture from `VALIDATED` to `LOCKED` (documentation frozen while `credit_status` stays `CREDITED` — the two axes evolve independently), and recomputes the agreement's `lifetime_paid_cents` to include this statement's `net_payment_cents`; both the statement and the agreement increment their versions.

Voiding is the compensation path. The committee may void a `FINALIZED` statement, supplying a `reason`; the statement moves to `VOIDED`, each included capture still `CREDITED` is unlocked from `LOCKED` back to `VALIDATED`, and the agreement's `lifetime_paid_cents` is recomputed to exclude the statement — a cash rollback to its pre-finalize value. System cascades void `DRAFT` statements without any cash impact, since a `DRAFT` statement never paid: a plan supersession or an agreement termination voids the agreement's `DRAFT` statements, and an accepted statement dispute voids the `FINALIZED` subject. The statement listing accepts an optional `status` filter, and a reverse listing exposes the disputes filed against a statement.

Mid-year true-up reconciles the live ledger against recognized cash. A `CompAnalyst` creates a true-up run beneath a plan with an `as_of_period` cutoff in `YYYY-MM` form; creation is blocked while any agreement of the plan has a statement `UNDER_REVIEW` or another run for the plan is still `COMPUTED` (`ERR_TRUEUP_GUARD`). Creation synchronously computes, for every agreement of the plan in `EFFECTIVE` or `AMENDMENT_REQUIRED` status, a variance: the closed periods are the agreement's `FINALIZED` statements at or before the cutoff, ordered chronologically; the live basis is the `credited_wrvu` of the agreement's `CREDITED` captures whose `credited_period` falls in those closed periods, ordered by `service_date` with `created_at` breaking ties and summed with a round-half-up to 2 decimal places; that volume is re-priced through the marginal tier formula at the physician's `fte`; and `variance_cents` is the recomputed earnings minus the sum of the closed statements' `period_productivity_cents`. A capture reversed by dispute after its period's statement finalized leaves the finalized statement untouched — the locked basis — so the live ledger and recognized cash diverge by exactly such a negative variance, a clawback; without a locked-period reversal the variance is 0. The run is born `COMPUTED` with its `adjustments` list of per-agreement `agreement_id` and `variance_cents` pairs, ordered by the agreements' `created_at` ascending. The committee posts a `COMPUTED` run, moving it to `POSTED` and setting each adjusted agreement's `pending_trueup_adjustment_cents` to its `variance_cents` — overwrite semantics, not accumulation — with each touched agreement incrementing its `version`; the adjustment then rides into the next generated statement as its `trueup_adjustment_cents`. An analyst may instead void a `COMPUTED` run, discarding its adjustments entirely.

### 3.8. Disputes, Corrections, and Reversals

A physician who disagrees with the books files a dispute. The filer is the `Physician`-role caller itself — `filer_physician_id` is taken from the `X-User-ID` header — and the `subject_type` is either `CAPTURE` or `STATEMENT`, with `subject_capture_id` or `subject_statement_id` identifying the subject accordingly. The subject must exist, match the declared type, and belong to the filer's own agreement; a missing or foreign subject is rejected with `ERR_DISPUTE_SUBJECT_MISMATCH`, and a `Physician` reaching for another physician's subject is refused earlier with `ERR_NOT_OWN_RESOURCE`. The dispute's `agreement_id` is resolved from the subject, the filer's free-text `reason` is recorded, and the dispute is born `FILED`. The dispute listing accepts optional `agreement_id`, `filer_physician_id`, and `status` filters, and a physician sees only its own filings.

An analyst starts review, moving the dispute `FILED → UNDER_REVIEW`. During review of a capture dispute, the analyst may request a data correction, recording `corrected_units` and/or `corrected_cpt_code` on the dispute and moving it `UNDER_REVIEW → DATA_CORRECTION`; each field is optional — a present `corrected_units` must be an integer of at least 1 and a present `corrected_cpt_code` a non-empty string, otherwise `ERR_VALIDATION` — and the transition occurs even when both are omitted. Corrections apply to capture subjects only, and requesting one on a statement dispute is rejected with `ERR_INVALID_STATE`. The loop is revisable: starting review again from `DATA_CORRECTION` cycles the dispute back to `UNDER_REVIEW` and clears the recorded `corrected_units` and `corrected_cpt_code`, so a correction request can be walked back and re-issued any number of times before resolution.

Resolution belongs to the committee and takes a `resolution` of `ACCEPTED` or `REJECTED` from either `UNDER_REVIEW` or `DATA_CORRECTION`, moving the dispute to its terminal state `RESOLVED_ACCEPTED` or `RESOLVED_REJECTED` respectively. Rejection simply records `resolution` `REJECTED` and the resolver's `X-User-ID` as `resolver_user_id` — no compensation side effects, and correction fields recorded along the way remain but are never applied. Acceptance is where the cascades fire. Acceptance requires the subject to still be in the state acceptance acts on — a capture subject must still be `CREDITED` and a statement subject must still be `FINALIZED`, otherwise `ERR_INVALID_STATE`. For a capture subject, the resolver must differ from the subject capture's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and if a `corrected_cpt_code` is in play a rate row must cover that code on the original `service_date`, otherwise `ERR_RATE_NOT_FOUND`; on the resolve call the state guard fires first, then segregation of duties, then rate coverage. Acceptance flips the subject capture `CREDITED → REVERSED`, records a `reversed_reason` drawn from the resolving dispute, recomputes the owning agreement's `ytd_wrvu_credited`, and — when the reversed capture is a `CLINICAL` capture with supervision children — flips each `SUPERVISION_CREDIT` child from `CREDITED` to `REVERSED`, recording the same `reversed_reason`, and recomputes each supervisor agreement's `ytd_wrvu_credited` in turn. Any `DRAFT` statement on the owning agreement whose period matches the reversed capture's `credited_period` is recomputed to reflect the reversal. Whenever acceptance happens from `DATA_CORRECTION`, resolution additionally creates a replacement `CLINICAL` capture — substituting the original `units` and/or `cpt_code` for any correction field left null — born `VALIDATED` and `CREDITED` with the corrected units and code, the original `service_date` and `posting_date`, a null `created_by_user_id`, and `reversal_of_capture_id` pointing at the reversed original; the replacement recomputes the agreement's year-to-date ledger and, for APP physicians, re-runs the supervision allocation of §3.5. For a statement subject, acceptance instead voids the `FINALIZED` subject statement with the standard void cascade of §3.7 — captures unlocked, lifetime paid rolled back.

### 3.9. Plan Change Requests and Succession

Changing an `ACTIVE` plan mid-flight is a governed workflow, not an edit. A `CompAnalyst` proposes a plan-change request against an `ACTIVE` plan — proposing against a plan in any other status is rejected with `ERR_INVALID_STATE` — naming the `plan_id`, the `successor_plan_id`, the `effective_date` on which the change may take effect, a physician-facing `summary`, and the OCC field `expected_comp_plan_version` described in §2.6. The successor must be `FMV_APPROVED` and its `supersedes_plan_id` must equal the changed plan's `id`, otherwise `ERR_SUCCESSOR_MISMATCH`. Creation is a create-with-supersede: any existing `PROPOSED` or `MODELED` requests for the same plan are withdrawn, and the changed plan's `version` increments. The request is born `PROPOSED`, and a plan-scoped listing with an optional `status` filter enumerates a plan's change requests. A `Physician`-role caller may read a plan's change requests — the listing or a single request — only when it holds an agreement of any status on that plan; any other access is refused with `ERR_NOT_OWN_RESOURCE`.

Modeling answers the physician's first question — what does this do to my pay? Running the model moves the request `PROPOSED → MODELED` and computes `modeled_delta_cents`: for every agreement of the changed plan in `EFFECTIVE` or `AMENDMENT_REQUIRED` status with at least one `FINALIZED` statement, the average `period_wrvu` across those statements is annualized over the twelve months of the year, and that annualized volume is priced through both the current plan's and the successor plan's tier schedules at the physician's `fte`; the per-agreement delta — successor projection minus current projection, rounded half-up to whole cents per agreement — sums into `modeled_delta_cents`. An agreement with no finalized payment history contributes exactly 0; there is no imputation.

Communication is the physician-facing step. Communicating moves a `MODELED` request to `COMMUNICATED` and requires the `effective_date` to be strictly after the logical-clock date, otherwise `ERR_PCR_TIMING`. Each physician holding an `EFFECTIVE` agreement on the changed plan then acknowledges the communication — a self-transition that appends the physician's `id` to `acknowledged_physician_ids`. A physician without an `EFFECTIVE` agreement on the plan is refused with `ERR_NOT_OWN_RESOURCE`, and a duplicate acknowledgment is rejected with `ERR_INVALID_STATE`. If the numbers change, an analyst revises the request, moving `COMMUNICATED → MODELED`, clearing `acknowledged_physician_ids` — prior acknowledgments are invalidated by the revision — and recomputing the model; the model action itself is also permitted directly from `COMMUNICATED` and clears acknowledgments when entered that way.

Activation is the committee's scheduled act and the point where the succession cascade fires. Activating a `COMMUNICATED` request requires the logical-clock date to be at least the `effective_date` (`ERR_PCR_TIMING`), every physician with an `EFFECTIVE` agreement on the changed plan to appear in `acknowledged_physician_ids` (`ERR_ACK_INCOMPLETE`), and the successor to still be `FMV_APPROVED` (`ERR_SUCCESSOR_MISMATCH`). On activation the request becomes `EFFECTIVE`; the successor plan moves `FMV_APPROVED → ACTIVE`, stamping `activated_at` with the clock timestamp; the changed plan moves `ACTIVE → SUPERSEDED`; every `EFFECTIVE` agreement on the superseded plan flips to `AMENDMENT_REQUIRED` (awaiting the re-pin of §3.3); and each flipped agreement voids its own `DRAFT` statements. The request, the changed plan, and every touched agreement increment their versions by 1, while the successor plan's `version` advances by 2 — one increment for its own `FMV_APPROVED → ACTIVE` activation transition (the `activated_at`-stamping mutation of §3.2) and one for the operation-level succession increment shared by both plans. Any request still `PROPOSED`, `MODELED`, or `COMMUNICATED` may instead be withdrawn to `WITHDRAWN`, terminal, by an analyst.

## 4. Endpoint Definitions

All endpoints are mounted under `/comp`. Endpoints that create a new resource answer 201 Created; endpoints that modify a resource or drive a state transition answer 200 OK; the rate-row deletion answers 204 No Content with an empty `data`. Request payloads, derived fields, and side effects are specified in §2 and §3 — this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /comp/_clock/set_current_utc | Set the logical clock; recomputes every `EFFECTIVE` agreement's compliance hold | SystemAdmin |
| POST | /comp/physicians | Register a physician or APP in the roster | SystemAdmin |
| GET | /comp/physicians/{id} | Read one physician; `Physician` role reads only its own record | SystemAdmin, CompAnalyst, CompCommittee, ComplianceOfficer, Physician |
| POST | /comp/comp-plans | Draft a compensation plan, optionally as successor of an `ACTIVE` plan | CompAnalyst |
| GET | /comp/comp-plans/{id} | Read one plan, including its `version` for OCC | CompAnalyst, CompCommittee, ComplianceOfficer |
| GET | /comp/comp-plans/{id}/successor-plans | List plans whose `supersedes_plan_id` points at this plan | CompAnalyst, CompCommittee, ComplianceOfficer |
| PUT | /comp/comp-plans/{id} | Edit plan configuration while `DRAFT`/`PENDING_REVIEW`; OCC-guarded | CompAnalyst |
| POST | /comp/comp-plans/{id}/submit-review | Submit a plan for compliance review | CompAnalyst |
| POST | /comp/comp-plans/{id}/review-decision | Record a compliance review decision on a plan | ComplianceOfficer |
| POST | /comp/comp-plans/{id}/activate | Activate an `FMV_APPROVED` plan | CompCommittee |
| POST | /comp/comp-plans/{id}/close | Close an `ACTIVE` plan with no non-terminal agreements | CompCommittee |
| POST | /comp/comp-plans/{id}/cpt-rates | Add a wRVU rate window for a CPT code | CompAnalyst |
| GET | /comp/comp-plans/{id}/cpt-rates | List a plan's rate rows | CompAnalyst, CompCommittee, ComplianceOfficer |
| DELETE | /comp/cpt-rates/{id} | Delete a rate row while the owning plan is `DRAFT`/`PENDING_REVIEW` | CompAnalyst |
| POST | /comp/physician-agreements | Enroll a physician into a plan; pins the plan's current `version` | CompAnalyst |
| GET | /comp/physician-agreements | List agreements with optional filters | CompAnalyst, CompCommittee, ComplianceOfficer, Physician |
| GET | /comp/physician-agreements/{id} | Read one agreement | CompAnalyst, CompCommittee, ComplianceOfficer, Physician |
| POST | /comp/physician-agreements/{id}/submit-fmv | Submit an agreement for FMV review or re-review | CompAnalyst |
| POST | /comp/physician-agreements/{id}/fmv-review | Record an FMV decision; reviewer segregated from creator | ComplianceOfficer |
| POST | /comp/physician-agreements/{id}/activate | Activate an `FMV_APPROVED` agreement | CompCommittee |
| POST | /comp/physician-agreements/{id}/terminate | Terminate an agreement; voids its `DRAFT` statements | CompCommittee |
| POST | /comp/physician-agreements/{id}/repin | Re-pin an `AMENDMENT_REQUIRED` agreement onto the successor plan | CompAnalyst |
| POST | /comp/physician-agreements/{id}/production-captures | Post a clinical production capture | CompAnalyst |
| GET | /comp/physician-agreements/{id}/production-captures | List an agreement's captures | CompAnalyst, CompCommittee, Physician |
| GET | /comp/production-captures/{id} | Read one capture | CompAnalyst, CompCommittee, Physician |
| GET | /comp/production-captures/{id}/corrections | List replacement captures reversed from this capture | CompAnalyst, CompCommittee, Physician |
| GET | /comp/production-captures/{id}/supervision-credits | List supervision credits allocated from this APP capture | CompAnalyst, CompCommittee, Physician |
| GET | /comp/production-captures/{id}/disputes | List disputes filed against this capture | CompAnalyst, CompCommittee, Physician |
| POST | /comp/production-captures/{id}/validate | Validate a `POSTED` capture; resolves rate, credits wRVU, allocates supervision | CompAnalyst |
| POST | /comp/production-captures/{id}/void | Void a `POSTED`, never-credited capture | CompAnalyst |
| POST | /comp/supervision-assignments | Create an APP supervision assignment | CompAnalyst |
| GET | /comp/supervision-assignments | List supervision assignments with optional filters | CompAnalyst, CompCommittee, ComplianceOfficer |
| GET | /comp/supervision-assignments/{id} | Read one supervision assignment | CompAnalyst, CompCommittee, ComplianceOfficer |
| POST | /comp/supervision-assignments/{id}/end | End an assignment early | CompAnalyst |
| POST | /comp/physician-agreements/{id}/quality-scorecards | Record a quality scorecard for a period | CompAnalyst |
| GET | /comp/physician-agreements/{id}/quality-scorecards | List an agreement's scorecards | CompAnalyst, CompCommittee, Physician |
| POST | /comp/quality-scorecards/{id}/finalize | Finalize a scorecard; computes and freezes the quality bonus | CompAnalyst |
| POST | /comp/physician-agreements/{id}/comp-statements | Generate a period statement | CompAnalyst |
| GET | /comp/physician-agreements/{id}/comp-statements | List an agreement's statements | CompAnalyst, CompCommittee, Physician |
| GET | /comp/comp-statements/{id} | Read one statement | CompAnalyst, CompCommittee, Physician |
| POST | /comp/comp-statements/{id}/submit-review | Move a `DRAFT` statement to `UNDER_REVIEW` | CompAnalyst |
| POST | /comp/comp-statements/{id}/finalize | Finalize a statement; locks captures and pays into the ledger | CompCommittee |
| POST | /comp/comp-statements/{id}/void | Void a `FINALIZED` statement; rolls back cash and unlocks captures | CompCommittee |
| GET | /comp/comp-statements/{id}/disputes | List disputes filed against this statement | CompAnalyst, CompCommittee, Physician |
| POST | /comp/comp-plans/{id}/true-up-runs | Create a mid-year true-up run; computes variances synchronously | CompAnalyst |
| GET | /comp/comp-plans/{id}/true-up-runs | List a plan's true-up runs | CompAnalyst, CompCommittee |
| POST | /comp/true-up-runs/{id}/post | Post a `COMPUTED` run; overwrites pending adjustments | CompCommittee |
| POST | /comp/true-up-runs/{id}/void | Void a `COMPUTED` run without applying adjustments | CompAnalyst |
| POST | /comp/disputes | Physician files a dispute on an own capture or statement | Physician |
| GET | /comp/disputes | List disputes; `Physician` sees only its own | CompAnalyst, CompCommittee, Physician |
| GET | /comp/disputes/{id} | Read one dispute; `Physician` limited to own filings | CompAnalyst, CompCommittee, Physician |
| POST | /comp/disputes/{id}/start-review | Move `FILED` to `UNDER_REVIEW`; cycles back from `DATA_CORRECTION` | CompAnalyst |
| POST | /comp/disputes/{id}/request-correction | Record a data-correction request on a capture dispute | CompAnalyst |
| POST | /comp/disputes/{id}/resolve | Resolve a dispute; acceptance fires the reversal or void cascade | CompCommittee |
| POST | /comp/plan-change-requests | Propose a plan change; OCC-guarded, create-with-supersede | CompAnalyst |
| GET | /comp/comp-plans/{id}/plan-change-requests | List a plan's change requests | CompAnalyst, CompCommittee, Physician |
| GET | /comp/plan-change-requests/{id} | Read one plan-change request | CompAnalyst, CompCommittee, Physician |
| POST | /comp/plan-change-requests/{id}/model | Run the what-if projection | CompAnalyst |
| POST | /comp/plan-change-requests/{id}/communicate | Communicate a `MODELED` change to affected physicians | CompAnalyst |
| POST | /comp/plan-change-requests/{id}/revise | Revise a `COMMUNICATED` change; clears acknowledgments | CompAnalyst |
| POST | /comp/plan-change-requests/{id}/acknowledge | Physician acknowledges a communicated change | Physician |
| POST | /comp/plan-change-requests/{id}/activate | Activate a communicated change; fires the supersede cascade | CompCommittee |
| POST | /comp/plan-change-requests/{id}/withdraw | Withdraw a non-terminal plan-change request | CompAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this catalogue fixes only the identifier and HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_OWN_RESOURCE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PLAN_IMMUTABLE | 409 |
| ERR_PLAN_NOT_FMV_APPROVED | 409 |
| ERR_PLAN_NOT_ACTIVE | 409 |
| ERR_AGREEMENT_NOT_EFFECTIVE | 409 |
| ERR_RATE_COVERAGE_INCOMPLETE | 422 |
| ERR_TIER_ORDER_INVALID | 422 |
| ERR_RATE_WINDOW_OVERLAP | 422 |
| ERR_RATE_NOT_FOUND | 422 |
| ERR_SUCCESSOR_EXISTS | 409 |
| ERR_SUCCESSOR_MISMATCH | 422 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_FMV_COOLING_OFF | 422 |
| ERR_FMV_STALE | 422 |
| ERR_FMV_CAP_EXCEEDED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_COMPLIANCE_HOLD | 422 |
| ERR_PERIOD_LOCKED | 422 |
| ERR_STATEMENT_PERIOD_ORDER | 409 |
| ERR_OPEN_DISPUTES | 409 |
| ERR_TRUEUP_GUARD | 409 |
| ERR_PROVIDER_TYPE_INVALID | 422 |
| ERR_NO_EFFECTIVE_AGREEMENT | 422 |
| ERR_SUPERVISION_WINDOW_INVALID | 422 |
| ERR_DISPUTE_SUBJECT_MISMATCH | 422 |
| ERR_PCR_TIMING | 422 |
| ERR_ACK_INCOMPLETE | 422 |

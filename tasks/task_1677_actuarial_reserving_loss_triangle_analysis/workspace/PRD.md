# Actuarial Reserving & Loss Triangle Analysis API — Product Requirements Document

## 1. Introduction

Every quarter, the actuarial department of a property-and-casualty insurer must answer the same deceptively simple question: how much money should be held today for claims whose ultimate cost is not yet known? Answering it well requires assembling claim-level payment and case-reserve activity into loss triangles, fitting development patterns to the emergence history, projecting ultimate losses under more than one method, reconciling the answers, and defending the conclusion through peer review and a signed statement of actuarial opinion. This document specifies the API that supports that full quarterly reserving cycle.

The system serves four operator roles across two desks. On the claims desk, examiners register claims, post financial activity, manage claim lifecycles, and segregate large losses and catastrophe claims from the bulk data. On the actuarial desk, analysts aggregate triangles, select development patterns, compute reserve runs under both the chain-ladder and Bornhuetter-Ferguson methods, prepare reserving studies, and produce quarterly roll-forward actual-versus-expected analyses; independent peer reviewers approve or reject those studies; and the appointed actuary administers segments and catastrophe events, drafts and signs the statement of actuarial opinion, and controls the department's logical clock. Throughout, the API enforces segregation of duties, an append-only claim ledger, a quarter-close checkpoint that freezes history once a study is approved, and a staleness-propagation model that keeps every downstream artifact honest when underlying claim data moves. All resources are served under the `/actuarial` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. The declared role must be one of `ClaimsExaminer`, `ActuarialAnalyst`, `PeerReviewer`, or `AppointedActuary`. A request arriving without a valid role header — or, for any mutating request, without `X-User-ID` — is rejected with `ERR_UNAUTHENTICATED` (401). When the role is valid but is not among the roles authorized for the target endpoint (see §4), the request is rejected with `ERR_FORBIDDEN` (403).

For each of the four roles — `ClaimsExaminer`, `ActuarialAnalyst`, `PeerReviewer`, and `AppointedActuary` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where governance requires (as `created_by_user_id` on reserving studies and actuarial opinions, as `reviewed_by_user_id` on reserving studies, and as `signed_by_user_id` on actuarial opinions) but never compares it against any entity's `id`. The identity checks in this system are segregation-of-duties comparisons between those recorded identifiers (§2.10), not foreign-key matches.

A `ClaimsExaminer` owns the claims desk: claim registration, financial transactions, claim lifecycle transitions, and catastrophe assignment. An `ActuarialAnalyst` is the reserving preparer: triangles, development patterns, reserve runs, studies, and roll-forwards. A `PeerReviewer` provides the independent review of submitted studies. An `AppointedActuary` administers segments and catastrophe events, drafts and signs opinions, and sets the logical clock. Read access is broad: every authenticated role can read segments, catastrophe events, claims, and claim transactions; actuarial artifacts (triangles, development patterns, reserve runs, reserving studies, actuarial opinions, and roll-forwards) are readable by `ActuarialAnalyst`, `PeerReviewer`, and `AppointedActuary`.

A fifth name, `Anonymous`, is a pseudo-role used only to describe requests sent without valid authentication headers. It never appears in any endpoint's authorized-role list, so every `Anonymous` call must fail with `ERR_UNAUTHENTICATED`.

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

List endpoints paginate through two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and the Append-Only Ledger Exception

All primary resources — segments, catastrophe events, claims, triangles, development patterns, reserve runs, reserving studies, actuarial opinions, and roll-forwards — share a standard set of system-managed properties:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`), recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including system-driven modifications such as the staleness-cascade reversion described in §2.7.

The claim transaction is the deliberate exception to this contract. A claim transaction is an append-only event-log entry: it carries only `id` and `created_at` as system-managed properties — `updated_at` and `version` are absent — and entries are never modified after being posted.

### 2.5. Quarter Labels, Calendar Dates, and the Logical Clock

The reserving calendar is expressed in quarter labels of the form `YYYY-Qn` (for example, `2025-Q3`). Quarter labels sort lexicographically, and that ordering coincides exactly with chronological order; the fourth quarter of a year is immediately followed by the first quarter of the next year. Calendar dates use the ISO `YYYY-MM-DD` form, and datetimes use ISO 8601 UTC.

Filing deadlines and signature timestamps are governed by a server-held logical clock, never by wall-clock time. Before any explicit set, the logical clock at server startup reads exactly `2026-08-01T00:00:00Z`. An `AppointedActuary`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The opinion deadline arithmetic of §3.8 and the `signed_at` timestamp of a signed opinion both read this clock.

### 2.6. Monetary Precision and the Pinned Rounding Order

All money amounts are integer cents — inputs, stored fields, and computed results alike. Triangle aggregation performs no rounding at any step. Ratios, development factors, cumulative development factors, and percentages are carried at exactly four decimal places, rounded half-up. Estimated ultimates are rounded half-up to whole cents per accident quarter before any summation, and reserve range bounds are likewise whole-cent values rounded half-up.

One rounding discipline is pinned and non-negotiable: each selected development factor is rounded to four decimal places at selection time, before it participates in any cumulative-factor product, and the cumulative development factor computed from those already-rounded factors is itself rounded to four decimal places. Carrying unrounded link ratios into downstream multiplication is a different rule and produces different cent values; implementations must not do it.

### 2.7. Staleness Propagation: From Transaction Ledger to Study Desk

Reserving artifacts form a dependency chain — transactions feed claims, claims feed triangles, triangles feed reserve runs, and runs feed studies — and staleness propagates along that chain immediately, within the triggering request. Posting a claim transaction sets `is_stale` to true on every triangle of the segment whose valuation quarter is on or after the transaction's effective quarter. Assigning or clearing a claim's catastrophe event sets `is_stale` on every triangle of the segment, because layer membership changed. A triangle turning stale in turn sets `is_stale` on every reserve run computed from it, and a run's `is_stale` likewise becomes true when its triangle was re-aggregated after the run was computed or when the development pattern it used is later withdrawn.

Stale runs are immutable: they are never recomputed in place, and a fresh estimate is produced only by creating a new run. Re-aggregating a triangle clears the triangle's own staleness flag and bumps its `version`, but deliberately does not rehabilitate runs computed from the earlier aggregation — they remain stale.

The final link protects peer review. Whenever the matched run of an `IN_REVIEW` reserving study turns stale, the study is reverted by the system from `IN_REVIEW` back to `DRAFT`, its `stale_data_flag` is set to true, and its `updated_at` is refreshed and `version` incremented. The study cannot be re-submitted until an analyst acknowledges the cascade by revising the study, which clears the flag (§3.7).

### 2.8. Validation Discipline and Check Ordering

Requests that address nested resources validate path identifiers in a strict left-to-right order: the first path identifier that does not correspond to an existing resource determines the `ERR_NOT_FOUND` response, before any deeper identifier or body rule is examined. The same existence discipline applies to foreign keys carried in request bodies — a referenced `segment_id`, `catastrophe_event_id`, or `study_id` must exist, and a catastrophe event that belongs to a different segment than the claim being updated is treated as not found for that claim.

Beyond existence, every request is evaluated against eleven ordered validation tiers, and the first failing tier determines the error returned:

1. **Authentication** — the role header is present and names a declared role, and the user header is present on mutating requests (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization** — the declared role appears in the endpoint's role list (`ERR_FORBIDDEN`, 403).
3. **Request shape** — required fields are present, types are valid, enum values are within their declared domains, quarter labels match the `YYYY-Qn` form, dates are ISO dates, payment and reversal amounts are positive, a case value is present on reserve-set transactions, Bornhuetter-Ferguson runs carry both the exposure and the a-priori ratio, report dates are not earlier than accident dates, and bodies are free of server-managed fields — `id`, `created_at`, `updated_at`, `version`, or any computed field. Violations are `ERR_INVALID_REQUEST` (400).
4. **Existence** — every path identifier and body foreign key resolves (`ERR_NOT_FOUND`, 404).
5. **State-machine legality** — the transition's from-state matches the resource's current status: claims close or reopen only from a valid status, studies submit only from `DRAFT` and are reviewed only from `IN_REVIEW`, withdrawal is refused from terminal states, pattern selection and withdrawal start only from the declared states, and opinions sign only from `DRAFT` (`ERR_INVALID_STATE`, 409).
6. **Optimistic concurrency** — a study revision's expected version matches the study's current `version` (`ERR_STALE_VERSION`, 412; §2.9).
7. **Segregation of duties** — the reviewer is not the study's preparer, and the signer is independent of drafting and review (`ERR_SOD_REVIEWER_IS_PREPARER`, `ERR_SOD_SIGNER_CONFLICT`; 403; §2.10).
8. **Referential integrity of derived objects** — the covering-pattern, fresh-triangle, matched-run, pattern-in-use, attachment, catastrophe-window, and prior-study checks of §3 (`ERR_NO_SELECTED_PATTERN`, `ERR_TRIANGLE_STALE`, `ERR_NO_SELECTED_RUN`, `ERR_RUN_STALE`, `ERR_STUDY_STALE_DATA`, `ERR_PATTERN_IN_USE`, `ERR_STUDY_NOT_APPROVED`, `ERR_STUDY_ATTACHED`, `ERR_OPINION_NO_STUDIES`, `ERR_CLAIM_OUTSIDE_CAT_WINDOW`, `ERR_NO_APPROVED_PRIOR_STUDY`; 409).
9. **Uniqueness** — at most one non-stale run per segment-quarter-method-basis combination and at most one non-withdrawn study per segment-quarter (`ERR_RUN_ALREADY_EXISTS`, `ERR_STUDY_ALREADY_EXISTS`; 409).
10. **Temporal rules** — transactions post only to open quarters, pattern windows are well-ordered and non-overlapping, catastrophe windows are disjoint, and opinions sign on or before their filing deadline (`ERR_QUARTER_CLOSED`, `ERR_PATTERN_PERIOD_OVERLAP`, `ERR_CAT_EVENT_DATE_OVERLAP`, `ERR_FILING_DEADLINE_PASSED` at 409; `ERR_INVALID_PATTERN_WINDOW` at 422).
11. **Fiscal guards** — case values are never negative, reversals never exceed paid-to-date, claims close only at zero case outstanding, and study approval respects the range-width gate (`ERR_CASE_OUTSTANDING_NEGATIVE`, `ERR_PAYMENT_REVERSAL_EXCEEDS_PAID` at 422; `ERR_CLAIM_NOT_CLOSEABLE`, `ERR_RANGE_WIDTH_EXCEEDED` at 409).

Because the tiers are ordered, an earlier failure masks a later one: a payload that is both malformed and aimed at a closed quarter is answered with `ERR_INVALID_REQUEST`, and a request against a missing segment is answered with `ERR_NOT_FOUND` regardless of what business rules the payload would also violate. Where a single tier contains several checks, §3 states their internal order next to the workflow they guard.

### 2.9. Optimistic Concurrency Control on Study Revision

Exactly one endpoint participates in optimistic concurrency control: the revision of a reserving study. A revision request must carry `expected_study_version`, holding the `version` of the study as the client last observed it. Revising a draft study's method or basis selection is a legitimate, repeatable operation that changes no state, so a second sequential revision carrying the version the client last observed cannot be refused on any state precondition; it is refused instead because the study's `version` has advanced since that observation. When `expected_study_version` does not equal the study's current `version`, the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently overwriting a selection change it has not observed. No other endpoint accepts a version field.

### 2.10. Segregation of Duties in Reserving Governance

Two independence rules are enforced as hard checks. First, the preparer of a reserving study may not review it: a peer-review decision is rejected with `ERR_SOD_REVIEWER_IS_PREPARER` (403) whenever the reviewer's `X-User-ID` equals the study's `created_by_user_id`, and this holds for approval and rejection alike. Second, the signature on a statement of actuarial opinion must be independent of both drafting and review: signing is rejected with `ERR_SOD_SIGNER_CONFLICT` (403) when the signer's `X-User-ID` equals the opinion's `created_by_user_id`, or equals the `created_by_user_id` or `reviewed_by_user_id` of any study attached to the opinion.

## 3. Business Logic & Workflows

### 3.1. Reserving Segments and Catastrophe Events

Work begins when an `AppointedActuary` carves the book into reserving segments. A segment is created with a display `name`, a `line_of_business` of `COMMERCIAL_AUTO`, `GENERAL_LIABILITY`, `WORKERS_COMP`, or `PROPERTY`, and three reserving parameters. The `large_loss_threshold_cents` sets the boundary at which a claim leaves the bulk data: any claim whose reported incurred reaches or exceeds this value is segregated, and the threshold itself must be positive. The `max_range_width_pct` caps how wide a study's indicated IBNR range may be relative to its selected IBNR before approval demands an explicit override; it too must be positive. The `benchmark_open_severity_cents` supplies the schedule benchmark of indicated case outstanding per open claim used by one of the two adequacy variants of §3.6, and it may be zero.

Every segment carries a computed `last_closed_quarter`: the maximum valuation quarter across the segment's `APPROVED` studies, or null when no study has been approved yet. This value is the segment's quarter-close checkpoint — once set, transactions dated into closed quarters are refused (§3.7). A segment read returns the checkpoint together with the configured parameters.

Catastrophe events are likewise administered by the `AppointedActuary`. An event is created for a segment with a `segment_id`, a `name` such as a hurricane designation, and a closed accident-date window given by `start_date` and `end_date`: both endpoints of the window are inclusive, and the end date must not be earlier than the start date. Two events of the same segment may not overlap — and because the window is closed, merely touching counts as overlap: an event whose start date falls on the exact day another event of the segment ends is refused with `ERR_CAT_EVENT_DATE_OVERLAP`. The events of a segment can be listed under that segment.

### 3.2. Claim Intake, the Transaction Ledger, and Loss Segregation

A `ClaimsExaminer` registers a claim with its `segment_id`, a business `claim_number`, an `accident_date`, and a `report_date` that must not be earlier than the accident date. A new claim starts `OPEN` with zero financials: `paid_to_date_cents` and `case_outstanding_cents` both begin at zero, and `reported_incurred_cents` — which is always, by invariant, the sum of those two — likewise starts at zero.

All subsequent financial activity lands in the claim's append-only transaction ledger. Posting a transaction names a `type` and a `transaction_date`; the server derives the entry's `effective_quarter` as the quarter label of the transaction date and takes the entry's `claim_id` from the claim being addressed. Three event types exist. A `PAYMENT` requires a positive `amount_cents` and adds that amount to paid-to-date. A `PAYMENT_REVERSAL` requires a positive `amount_cents` no greater than the claim's current `paid_to_date_cents` — a larger reversal is refused with `ERR_PAYMENT_REVERSAL_EXCEEDS_PAID` — and subtracts the amount. A `CASE_RESERVE_SET` requires a `case_value_cents` of zero or more — a negative value is refused with `ERR_CASE_OUTSTANDING_NEGATIVE` — and replaces the case outstanding with that absolute value rather than adjusting it. A payment or reversal missing its amount or carrying a non-positive one, and a reserve set missing its case value, are shape violations answered with `ERR_INVALID_REQUEST`. Each posting refreshes the claim's derived figures and bumps the claim's `version`, and the claim's transaction log can be listed in creation order.

Two segregation flags are recomputed after every posting. `is_large_loss` is true exactly when `reported_incurred_cents` reaches or exceeds the segment's `large_loss_threshold_cents` — the at-least boundary is pinned, so a claim sitting exactly on the threshold is a large loss. `is_segregated` is true when the claim is a large loss or carries a catastrophe event assignment. Segregation determines which triangle layer the claim feeds (§3.3), so a posting that crosses the threshold moves the claim between layers at the next aggregation.

The catastrophe assignment itself is a claims-desk operation: a `ClaimsExaminer` updates the claim with a `catastrophe_event_id`, which is nullable — supplying null clears the assignment. The claim's `accident_date` must fall within the event's closed window, inclusive of both endpoints; otherwise the update is refused with `ERR_CLAIM_OUTSIDE_CAT_WINDOW`. An event that belongs to a different segment is not merely invalid for this claim — it is not found, answered with `ERR_NOT_FOUND`. Because assigning or clearing an event changes layer membership, the update recomputes `is_segregated`, increments the claim's `version`, and fires the staleness cascade of §2.7 across every triangle of the segment.

Claim lifecycle transitions are explicit. Closing requires the claim to be `OPEN` or `REOPENED` and its `case_outstanding_cents` to be exactly zero; a claim still carrying case reserves cannot close, and the attempt is refused with `ERR_CLAIM_NOT_CLOSEABLE`. Closing sets both adequacy ratios of §3.6 to null. A `CLOSED` claim may be reopened without preconditions, after which its adequacy ratios resume being computed on read; a `REOPENED` claim closes again under the same zero-outstanding rule. Both transitions are requested by supplying a `target_status` of `CLOSED` or `REOPENED`, and each increments the claim's `version`. Closing a claim that is already `CLOSED`, or reopening one that is not `CLOSED`, is refused with `ERR_INVALID_STATE`.

Claims can be read individually — the response carries the computed financials, both segregation flags, and both adequacy ratios — or listed with optional `segment_id`, `catastrophe_event_id`, and `status` filters; a claim's `status` is one of `OPEN`, `CLOSED`, or `REOPENED`.

### 3.3. Triangle Aggregation: Bulk and Large-Loss Layers

An `ActuarialAnalyst` aggregates a loss triangle by naming a `segment_id`, a `basis` of `PAID` or `INCURRED`, and a `valuation_quarter`. Aggregation is an upsert keyed on that triple: the first aggregation for a combination creates the triangle (201 Created), and a later request for the same combination recomputes it in place (200 OK), clearing the triangle's `is_stale` flag and incrementing its `version`. Runs computed from the earlier aggregation stay stale — only the triangle itself is rehabilitated.

Each claim's `accident_quarter` is the quarter of its `accident_date`, and each transaction's development index is the number of quarters elapsed from the claim's accident quarter to the transaction's effective quarter. Aggregation emits cumulative cells of the shape {`accident_quarter`, `dev_quarter`, `amount_cents`}, where `dev_quarter` is the zero-based development index of the column. The aggregation draws on every claim of the segment regardless of status — `OPEN`, `CLOSED`, and `REOPENED` claims all contribute — and on every transaction whose effective quarter is on or before the valuation quarter.

The triangle keeps two layers. The `cells` array covers the bulk layer — claims that are not segregated at aggregation time — and the `large_loss_cells` array covers the segregated layer, in the same cell shape. On a `PAID` basis, a cell is the sum of payment amounts minus reversal amounts across the layer's claims for that accident quarter, taken over all transactions with development index no later than the column. On an `INCURRED` basis, a cell is that same cumulative paid figure plus, for each of the layer's claims in the accident quarter, the most recent case reserve set at a development index no later than the column — zero when the claim has no reserve set within that window — all summed. Cells are emitted only on or below the valuation diagonal: a cell's development index never exceeds the number of quarters elapsed from its accident quarter to the valuation quarter, and cells exist only for claims whose accident quarter is on or before the valuation quarter. All amounts are integer cents, and no rounding occurs anywhere in aggregation. Triangles can be read individually or listed with `segment_id`, `basis`, and `valuation_quarter` filters.

### 3.4. Development Patterns: Factor Selection, Tail Estimation, and Windows

From a fresh triangle, an `ActuarialAnalyst` derives a development pattern by naming its `segment_id`, `basis`, `valuation_quarter`, and an effective window running from `effective_from_quarter` to `effective_to_quarter`. The window is half-open — inclusive at the start, exclusive at the end — and the start must be strictly earlier than the end, otherwise creation is refused with `ERR_INVALID_PATTERN_WINDOW`. The referenced triangle must exist (`ERR_NOT_FOUND` otherwise) and must not be stale (a stale source triangle is refused with `ERR_TRIANGLE_STALE`). A new pattern starts in `DRAFT`.

Factor selection works across the bulk layer's adjacent development columns. For each adjacent column pair, the eligible accident quarters are those having cells at both columns; when no accident quarter qualifies at a given age, the pattern carries no factor for that age, and when no accident-quarter pair is fully developed anywhere, `selected_factors` is an empty array. Otherwise, the raw link ratio at an age is the sum of the eligible accident quarters' later-column cells divided by the sum of their earlier-column cells — a volume-weighted average link ratio — and each selected factor is that ratio rounded half-up to four decimal places before any downstream use, per the pinned rounding order of §2.6. The `tail_factor` extends the curve beyond the data: with at least three selected factors it is the cube root of the product of the final three selected factors, taken from their already-rounded values and itself rounded half-up to four decimal places; with fewer than three it is exactly 1.0000, and no extrapolation is attempted.

These two outputs combine into the cumulative development factors used by reserve runs, adequacy ratios, and roll-forwards. With n selected factors, the cumulative factor at a development age younger than n is the product of the selected factors from that age through the final selected age — the rounded factors, not the raw ratios — multiplied by the tail factor, with the product itself rounded half-up to four decimal places. At the age exactly equal to n, the cumulative factor is the tail factor itself. At any age beyond n, the cumulative factor is exactly 1.0000.

Selection is the act that makes a pattern usable: selecting a `DRAFT` pattern moves it to `SELECTED`, provided its window does not intersect any other `SELECTED` pattern of the same segment and basis. Two windows intersect precisely when the incoming pattern's `effective_from_quarter` is earlier than the incumbent's `effective_to_quarter` and, at the same time, the incumbent's `effective_from_quarter` is earlier than the incoming pattern's `effective_to_quarter`; an intersecting selection is refused with `ERR_PATTERN_PERIOD_OVERLAP`. Windows that merely touch — the incoming window beginning exactly where the incumbent ends — are adjacent, not overlapping, and are allowed.

Withdrawal moves a pattern to its terminal `WITHDRAWN` state. A `DRAFT` pattern withdraws freely. A `SELECTED` pattern withdraws only while no `APPROVED` or `LOCKED` study of the same segment has a valuation quarter inside the pattern's window; otherwise the withdrawal is refused with `ERR_PATTERN_IN_USE`. Withdrawal fires the pattern-side staleness cascade: every reserve run built on this pattern with a valuation quarter inside the window becomes stale, and every `IN_REVIEW` study of the segment whose matched run turned stale reverts to `DRAFT` with its `stale_data_flag` set (§2.7). Acting on a pattern from a status other than the declared start of a transition — selecting a `SELECTED` pattern, or selecting or withdrawing a `WITHDRAWN` one — is refused with `ERR_INVALID_STATE`. Patterns can be read individually or listed with `segment_id`, `basis`, and `status` filters; a pattern's `status` is `DRAFT`, `SELECTED`, or `WITHDRAWN`.

### 3.5. Reserve Runs: Chain Ladder and Bornhuetter-Ferguson

With a fresh triangle and a selected pattern in place, an `ActuarialAnalyst` computes a reserve run by naming the `segment_id`, `valuation_quarter`, `method` — `CHAIN_LADDER` or `BORNHUETTER_FERGUSON` — and `basis`. The run's basis must equal the basis of the pattern the run binds to. Two further inputs belong to the Bornhuetter-Ferguson variant: `earned_exposure_cents` and `a_priori_loss_ratio` are required when the method is `BORNHUETTER_FERGUSON`, and both are ignored entirely for `CHAIN_LADDER`; omitting either from a Bornhuetter-Ferguson request is a shape violation answered with `ERR_INVALID_REQUEST`.

Creation is guarded by referential and uniqueness checks. A `SELECTED` pattern of the same segment and basis whose window covers the valuation quarter must exist — without one the request fails with `ERR_NO_SELECTED_PATTERN` — and the run's `development_pattern_id` is bound to that covering pattern at computation time. The triangle for the segment, basis, and valuation quarter must be non-stale, else `ERR_TRIANGLE_STALE`. And at most one non-stale run may exist for a given segment, valuation quarter, method, and basis: a second fresh run for the same combination is refused with `ERR_RUN_ALREADY_EXISTS`.

Under `CHAIN_LADDER`, each accident quarter's ultimate is estimated independently within each layer: the quarter's latest-diagonal cell — the cell at the age equal to the number of quarters elapsed from the accident quarter to the valuation quarter — is multiplied by the cumulative development factor at that age, and the product is rounded half-up to whole cents. The large-loss layer uses the very same selected factors and cumulative factors as the bulk layer, applied to its own diagonal, and the layer ultimates are summed. The run's `ultimate_cents` is the total across both layers and all accident quarters, and its `ibnr_cents` is that total minus the sum of the latest-diagonal cells across both layers. On a `PAID` basis this IBNR represents the total unpaid loss; on an `INCURRED` basis it is pure IBNR.

Under `BORNHUETTER_FERGUSON`, each bulk-layer accident quarter blends experience with expectation: the ultimate is the latest-diagonal cell plus the product of `earned_exposure_cents`, `a_priori_loss_ratio`, and the difference between one and the reciprocal of the cumulative development factor at the quarter's age, rounded half-up to whole cents. The large-loss layer is not credibility-weighted per claim; instead, its ultimate is pinned to the chain-ladder ultimate of the large layer — the same formula as the chain-ladder method applied to the `large_loss_cells`. When no segregated claims exist, the large layer contributes exactly zero and the earned exposure applies fully to the bulk layer. Totals and IBNR are then computed exactly as in the chain-ladder case.

Every run also carries an indicated range: `range_low_cents` is three-quarters of `ibnr_cents` and `range_high_cents` is one-and-a-half times `ibnr_cents`, each rounded half-up to whole cents. The run's per-quarter arithmetic is exposed in `ultimate_by_accident_quarter`, a list of {`accident_quarter`, `age_at_valuation`, `cdf`, `ultimate_cents`} entries for the bulk layer, where `cdf` is the cumulative development factor as actually used — the four-decimal rounded value. A run's `is_stale` becomes true when its triangle is re-aggregated or marked stale after the run was computed, or when the pattern it used is later withdrawn; stale runs are immutable, and the only way to recompute is to create a new run. Runs can be read individually or listed with `segment_id`, `development_pattern_id`, `valuation_quarter`, `method`, and `basis` filters.

### 3.6. Case Reserve Adequacy on Claim Reads

Two adequacy ratios accompany every claim read, each answering a different question about the same case reserve. Both are computed against an as-of context: let V be the valuation quarter of the segment's latest — that is, greatest valuation quarter — non-stale `PAID` triangle, and let P be the `SELECTED` `PAID` pattern whose window covers V. If the segment has no such triangle, or no such pattern covers V, both ratios are null. The claim's age is the number of quarters elapsed from its accident quarter to V.

The development-indicated variant asks whether the case reserve matches what the paid development curve implies is still to come. The indicated outstanding is the claim's `paid_to_date_cents` multiplied by the amount by which the cumulative development factor at the claim's age exceeds one. `adequacy_ratio_development` is then the `case_outstanding_cents` divided by that indicated outstanding, rounded half-up to four decimal places; when the indicated outstanding is zero, the ratio is null.

The schedule-benchmark variant ignores the claim's own payment history and compares the case reserve against the segment's flat schedule severity: `adequacy_ratio_benchmark` is the `case_outstanding_cents` divided by the segment's `benchmark_open_severity_cents`, rounded half-up to four decimal places, and it is null when the benchmark is zero. Both variants are computed for `OPEN` and `REOPENED` claims; both are null while a claim is `CLOSED`, and both resume being computed on read when a closed claim is reopened.

### 3.7. The Reserving Study: Drafting, Review, and the Quarter Close

The reserving study is where methods are chosen, reconciled, and defended. An `ActuarialAnalyst` opens a study by naming a `segment_id`, a `valuation_quarter`, an initial `selected_method` of `CHAIN_LADDER` or `BORNHUETTER_FERGUSON`, and an initial `selected_basis` of `PAID` or `INCURRED`. At most one non-`WITHDRAWN` study may exist per segment and valuation quarter; a second active study for the same pair is refused with `ERR_STUDY_ALREADY_EXISTS`. A new study starts in `DRAFT` with `stale_data_flag` false and its `created_by_user_id` taken from the creator's header.

A study's numbers are resolved on read rather than stored. The matched run is the unique non-stale run sharing the study's segment, valuation quarter, selected method, and selected basis — uniqueness enforced at run creation makes ordering or tie-breaking unnecessary — and `selected_ultimate_cents`, `selected_ibnr_cents`, `selected_range_low_cents`, and `selected_range_high_cents` copy that run's figures, all four null when no non-stale match exists. Reconciliation compares the two methods over the latest non-stale run of each for the same segment, valuation quarter, and selected basis: `reconciliation_variance_pct` is the absolute difference between the chain-ladder and Bornhuetter-Ferguson ultimates divided by their mean — half their sum — rounded half-up to four decimal places, and it is null when either method's run is missing. Studies can be read individually or listed with `segment_id`, `opinion_id`, `status`, and `valuation_quarter` filters.

While a study is in `DRAFT`, the analyst may revise its `selected_method` or `selected_basis`; both are optional on a revision, and the request must also carry `expected_study_version` under the optimistic-concurrency rule of §2.9 — a stale expectation is refused with `ERR_STALE_VERSION`. Revising is also how an analyst acknowledges a staleness cascade: the revision clears `stale_data_flag`, increments the study's `version` by one, and recomputes the selected figures from the newly matched run. Revision is a draft-stage capability; attempting it on a study in any other status is refused with `ERR_INVALID_STATE`.

Submission moves the study from `DRAFT` to `IN_REVIEW` and applies its three checks in a fixed order. First, the `stale_data_flag` must be false — an unacknowledged cascade surfaces as `ERR_STUDY_STALE_DATA` rather than being masked by the later checks. Second, a run matching the study's segment, valuation quarter, selected method, and selected basis must exist at all — otherwise `ERR_NO_SELECTED_RUN`. Third, the matched run must be fresh — when every match is stale, the submission fails with `ERR_RUN_STALE`.

Review is performed by a `PeerReviewer` other than the study's creator, with segregation of duties enforced per §2.10 (`ERR_SOD_REVIEWER_IS_PREPARER`). The review carries a `decision` of `APPROVE` or `REJECT`. Approval additionally passes the range-width gate: the width of the indicated range — `selected_range_high_cents` minus `selected_range_low_cents` — divided by `selected_ibnr_cents` must not exceed the segment's `max_range_width_pct`; when the selected IBNR is zero, the width ratio is taken as zero. A chief-actuary override exists for exceptional quarters: when the review carries `chief_actuary_override` as true, the gate is waived; without it, an over-wide range is refused with `ERR_RANGE_WIDTH_EXCEEDED`. Approval records the reviewer in `reviewed_by_user_id` and fires the quarter-close checkpoint: the segment's `last_closed_quarter` advances to the later of its current value and the study's valuation quarter, with a null checkpoint treated as earlier than any quarter label. From then on, any transaction whose effective quarter is on or before the checkpoint is refused with `ERR_QUARTER_CLOSED`. Rejection returns the study to `DRAFT`, likewise records `reviewed_by_user_id`, and the study may be revised and re-submitted — the revision loop.

Two further transitions complete the lifecycle. Withdrawal moves a study to the terminal `WITHDRAWN` state from `DRAFT`, `IN_REVIEW`, or `APPROVED`; withdrawing an `APPROVED` study is allowed only while it is unattached — a study whose `opinion_id` is set is refused with `ERR_STUDY_ATTACHED` — and withdrawal clears `opinion_id` when it is set, a situation reachable only for non-approved studies since approved ones must be unattached to withdraw. Locking is not an operator action at all: when a statement of actuarial opinion covering the study is signed (§3.8), the study moves from `APPROVED` to `LOCKED` and becomes immutable, with no further transitions permitted. Acting on a `LOCKED` or `WITHDRAWN` study — or submitting, reviewing, revising, or withdrawing from a status the transition does not start from — is refused with `ERR_INVALID_STATE`. The system itself can also move a study: the staleness cascade of §2.7 reverts an `IN_REVIEW` study to `DRAFT`, sets `stale_data_flag`, and advances `updated_at` and `version`.

### 3.8. The Statement of Actuarial Opinion

The cycle's formal output is the statement of actuarial opinion, drafted by an `AppointedActuary` with a `statement_date` and an `opinion_scope` of `REASONABLE`, `DEFICIENT`, `REDUNDANT`, or `NO_OPINION`. The draft starts in `DRAFT`, records its drafter in `created_by_user_id`, and immediately fixes its `filing_deadline_date` as the calendar date sixty days after the statement date.

An opinion gathers its supporting studies through attachment: the actuary attaches a study by its `study_id`, which sets the study's `opinion_id` to this opinion. Attachment is possible only while the opinion is in `DRAFT`, requires the study to be `APPROVED` (a study in any other status is refused with `ERR_STUDY_NOT_APPROVED`), and requires the study to be unattached — a study already carrying an opinion is refused with `ERR_STUDY_ATTACHED`.

Signature moves the opinion from `DRAFT` to its terminal `SIGNED` state and applies its checks in their tier order. Segregation of duties comes first: the signer must differ from the opinion's drafter and from the creator and the most recent reviewer of every attached study, else `ERR_SOD_SIGNER_CONFLICT`. The attachment checks follow: at least one study must be attached, else `ERR_OPINION_NO_STUDIES`, and every attached study must be `APPROVED`, else `ERR_STUDY_NOT_APPROVED`. The temporal check comes last: the logical clock's date must be on or before the `filing_deadline_date`, and signing after the deadline is refused with `ERR_FILING_DEADLINE_PASSED`. A successful signature records `signed_by_user_id`, stamps `signed_at` from the current logical clock, and moves every attached study from `APPROVED` to `LOCKED`, rendering it immutable. Signing an opinion that is not in `DRAFT` is refused with `ERR_INVALID_STATE`.

### 3.9. Quarterly Roll-Forward and Actual-versus-Expected Analysis

Once a quarter's study is approved, the next quarter opens with a roll-forward: an `ActuarialAnalyst` names a `segment_id` and the new `valuation_quarter` being rolled into. The roll-forward computes its `prior_valuation_quarter` as the quarter label immediately preceding the new quarter and anchors itself to the prior quarter's study — the unique non-`WITHDRAWN` study for the segment and prior quarter, whose uniqueness is guaranteed at study creation. That prior study must be `APPROVED`; if no such study exists, or it exists in any other status, the request fails with `ERR_NO_APPROVED_PRIOR_STUDY`. The prior study's matched selected run must be non-stale, else `ERR_RUN_STALE`, and the run's bound pattern supplies the development curve.

The roll-forward's `basis` is copied from the prior approved study's selected basis. Expected emergence is computed per accident quarter of the prior run's `ultimate_by_accident_quarter` breakdown: each entry's ultimate is multiplied by the difference between the reciprocal of the cumulative development factor evaluated one age beyond the entry's `age_at_valuation` and the reciprocal of the cumulative development factor evaluated at the `age_at_valuation` itself; each such product is rounded half-up to whole cents, and `expected_emergence_cents` is their sum. Cumulative factors evaluated beyond the oldest factored age are exactly 1.0, per §3.4.

Actual emergence depends on the basis. On a `PAID` basis, `actual_emergence_cents` is the sum of payment amounts minus reversal amounts across the segment's non-segregated claims, taken over transactions whose effective quarter equals the new quarter. On an `INCURRED` basis, it is the aggregate incurred value of the segment's non-segregated claims measured as of the end of the new quarter minus the same aggregate measured as of the end of the prior quarter, restricted to accident quarters on or before the prior quarter.

The variance closes the analysis: `ave_variance_cents` is the actual emergence minus the expected emergence, and `ave_variance_ratio` is that difference divided by the expected emergence, rounded half-up to four decimal places — null when the expected emergence is zero. The roll-forwards of a segment can be listed under the segment with an optional `valuation_quarter` filter.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Triangle aggregation is the one hybrid: the first aggregation of a segment-basis-quarter combination returns `201 Created`, while a re-aggregation of an existing combination returns `200 OK`. All read endpoints return `200 OK`. Readers should refer back to §3 for the full request and response semantics of each operation — the table below is an index, not a specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/actuarial/segments` | Create a reserving segment | AppointedActuary |
| GET | `/actuarial/segments/{id}` | Get a segment, including the computed quarter-close checkpoint | ClaimsExaminer, ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/catastrophe-events` | Create a catastrophe event for a segment | AppointedActuary |
| GET | `/actuarial/segments/{id}/catastrophe-events` | List a segment's catastrophe events | ClaimsExaminer, ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/claims` | Register a claim in a segment | ClaimsExaminer |
| GET | `/actuarial/claims/{id}` | Get a claim with computed financials, segregation flags, and adequacy ratios | ClaimsExaminer, ActuarialAnalyst, PeerReviewer, AppointedActuary |
| GET | `/actuarial/claims` | List and filter claims | ClaimsExaminer, ActuarialAnalyst, PeerReviewer, AppointedActuary |
| PATCH | `/actuarial/claims/{id}` | Assign or clear the claim's catastrophe event | ClaimsExaminer |
| POST | `/actuarial/claims/{id}/status` | Transition the claim lifecycle (close or reopen) | ClaimsExaminer |
| POST | `/actuarial/claims/{id}/transactions` | Append a financial event to the claim's ledger | ClaimsExaminer |
| GET | `/actuarial/claims/{id}/transactions` | List the claim's transaction log | ClaimsExaminer, ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/triangles` | Create or re-aggregate a loss triangle | ActuarialAnalyst |
| GET | `/actuarial/triangles/{id}` | Get a triangle with its cells | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| GET | `/actuarial/triangles` | List and filter triangles | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/development-patterns` | Create a development pattern with computed factors | ActuarialAnalyst |
| GET | `/actuarial/development-patterns/{id}` | Get a development pattern | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| GET | `/actuarial/development-patterns` | List and filter development patterns | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/development-patterns/{id}/select` | Select a draft pattern | ActuarialAnalyst |
| POST | `/actuarial/development-patterns/{id}/withdraw` | Withdraw a draft or selected pattern | ActuarialAnalyst |
| POST | `/actuarial/reserve-runs` | Compute a reserve run | ActuarialAnalyst |
| GET | `/actuarial/reserve-runs/{id}` | Get a reserve run | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| GET | `/actuarial/reserve-runs` | List and filter reserve runs | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/studies` | Create a draft reserving study | ActuarialAnalyst |
| GET | `/actuarial/studies/{id}` | Get a study with selected figures and reconciliation variance | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| GET | `/actuarial/studies` | List and filter studies | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| PATCH | `/actuarial/studies/{id}` | Revise a draft study's method or basis selection | ActuarialAnalyst |
| POST | `/actuarial/studies/{id}/submit` | Submit a draft study for peer review | ActuarialAnalyst |
| POST | `/actuarial/studies/{id}/review` | Record a peer-review decision | PeerReviewer |
| POST | `/actuarial/studies/{id}/withdraw` | Withdraw a study | ActuarialAnalyst |
| POST | `/actuarial/opinions` | Draft a statement of actuarial opinion | AppointedActuary |
| GET | `/actuarial/opinions/{id}` | Get an actuarial opinion | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/opinions/{id}/attach-study` | Attach an approved study to a draft opinion | AppointedActuary |
| POST | `/actuarial/opinions/{id}/sign` | Sign a draft opinion | AppointedActuary |
| POST | `/actuarial/roll-forwards` | Compute the quarterly roll-forward analysis | ActuarialAnalyst |
| GET | `/actuarial/segments/{id}/roll-forwards` | List a segment's roll-forwards | ActuarialAnalyst, PeerReviewer, AppointedActuary |
| POST | `/actuarial/_clock/set_current_utc` | Set the logical clock | AppointedActuary |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the rules they guard; this table is an index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_REVIEWER_IS_PREPARER` | 403 Forbidden |
| `ERR_SOD_SIGNER_CONFLICT` | 403 Forbidden |
| `ERR_NO_SELECTED_PATTERN` | 409 Conflict |
| `ERR_TRIANGLE_STALE` | 409 Conflict |
| `ERR_RUN_STALE` | 409 Conflict |
| `ERR_NO_SELECTED_RUN` | 409 Conflict |
| `ERR_STUDY_STALE_DATA` | 409 Conflict |
| `ERR_PATTERN_IN_USE` | 409 Conflict |
| `ERR_STUDY_NOT_APPROVED` | 409 Conflict |
| `ERR_STUDY_ATTACHED` | 409 Conflict |
| `ERR_OPINION_NO_STUDIES` | 409 Conflict |
| `ERR_CLAIM_OUTSIDE_CAT_WINDOW` | 409 Conflict |
| `ERR_NO_APPROVED_PRIOR_STUDY` | 409 Conflict |
| `ERR_RUN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_STUDY_ALREADY_EXISTS` | 409 Conflict |
| `ERR_QUARTER_CLOSED` | 409 Conflict |
| `ERR_PATTERN_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_INVALID_PATTERN_WINDOW` | 422 Unprocessable Entity |
| `ERR_CAT_EVENT_DATE_OVERLAP` | 409 Conflict |
| `ERR_FILING_DEADLINE_PASSED` | 409 Conflict |
| `ERR_CASE_OUTSTANDING_NEGATIVE` | 422 Unprocessable Entity |
| `ERR_PAYMENT_REVERSAL_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_RANGE_WIDTH_EXCEEDED` | 409 Conflict |

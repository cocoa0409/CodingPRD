# Survey & Market-Research Panel API — Product Requirements Document

## 1. Introduction

Market-research panels live or die on data quality. A study sponsor pays for a fixed number of *qualified completes* split across demographic segments, and every dollar of incentive spent on a careless, fraudulent, or out-of-quota respondent is wasted. This API is the operational backbone for running such a panel end to end: it lets a research team design a study and its screener, recruit panelists against per-segment quotas, accrue and pay out incentives, police response quality with attention and fraud checks, schedule in-person focus groups against physical facilities, deliver the cleaned dataset, and continuously monitor panel health and churn — all under an IRB consent regime.

The platform serves four distinct operator audiences whose responsibilities deliberately do not overlap: research managers who own studies and deliverables, panel-operations staff who own the panelist roster and the money, field coordinators who run day-to-day fielding and the focus-group calendar, and the panelists themselves who act only on their own records. The central design tension this document specifies is that a single panelist's progress through a study is *not* a straight line: their screening outcome and their survey-completion progress advance on two independent tracks, incentives are first held provisionally and only later finalized (or reversed) once quality is known, and a quota seat reserved during screening must be released the moment that participation falls out — cascading through accruals, panel-health scores, and recruitment availability. Getting these interlocking lifecycles, calculations, and consistency rules exactly right is the whole job.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation (per the role authorizations summarized in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles are spelled exactly `ResearchManager`, `PanelOps`, `FieldCoordinator`, and `Panelist`.

Three of these roles are operator identities not tied to any persisted record. When `X-User-Role` is `ResearchManager`, `PanelOps`, or `FieldCoordinator`, the value of `X-User-ID` is an opaque operator identifier; the server may log it but never compares it to any entity's `id`. These three operate on the panel's shared resources by role authority alone.

The `Panelist` role is different: it is **entity-backed**. When `X-User-Role` is `Panelist`, `X-User-ID` is the `id` of the acting `Panelist` record. Ownership checks compare the foreign-key field on the target resource to `X-User-ID`. A `Panelist` may only start, submit, or abandon a participation whose `panelist_id` equals `X-User-ID`; may only create or cancel a payout request whose `panelist_id` equals `X-User-ID`; and may only create or cancel a focus-group booking whose `panelist_id` equals `X-User-ID`. When a panelist attempts to act on a resource owned by someone else, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule applies to participation start, submit, and abandon; to payout-request create and cancel; and to focus-group-booking create and cancel.

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

All list endpoints are paginated through two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may be no smaller than 0. List results are always sorted by `created_at` in ascending order (oldest first), so pagination windows are stable as new records are added. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of records matching the query before the pagination window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Common Resource Properties and the Logical Clock

Every resource is assigned a server-minted `id` that is a UUID with no type prefix; clients never supply it. Each resource also carries a `created_at` timestamp, formatted as an ISO 8601 UTC string with three fractional digits, recorded when the resource is first created.

Most entities additionally carry an `updated_at` timestamp (same format) and an integer `version` that begins at 1 and increments by one on every mutation of that resource. Two entities are exceptions: `Consent` and `AttentionCheck` are immutable audit records. They carry only `id` and `created_at` — they have no `updated_at` field and no `version` field, because once written they are never modified.

Because quota, scheduling, health, and consent logic all depend on time, the server runs on a **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it stays at that default and never falls back to real time. An administrative test-driving capability sets the clock to a supplied instant for all subsequent time-dependent evaluation; the desired instant is supplied as `to_iso8601`. All timestamps the server records — `recorded_at` on a consent or attention check, `last_activity_at` on a panelist, focus-group window comparisons — read from this logical clock.

### 2.5. Nested-Path Resolution and Referential Integrity

Several endpoints carry resource ids in their path (for example, a quota cell created under a study, or attention checks listed under a participation). Path and body resource ids are validated left to right: the parent must resolve before the child is considered. If any referenced id — in the path or the request body — does not resolve to an existing entity, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Foreign-key references inside request bodies (a `study_id`, a `panelist_id`, a `quota_cell_id`, a `facility_id`, a `focus_group_id`, a `participation_id`) are subject to the same existence check. Malformed bodies — a missing required field, a wrong type, or an enum value outside the allowed set — are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.6. The Two-Axis Participation Model

A `Participation` is the heart of this system, and it tracks two **independent** state dimensions at once. The first axis, `screening_status`, records whether the panelist qualifies for the study's quota; the second axis, `completion_status`, records how far they have gotten through the actual survey instrument. These two axes advance on their own schedules and must never be conflated. A participation can be fully `COMPLETED` on the completion axis while its screening axis is still being resolved, and the act of submitting the survey is precisely what bridges the two — it both finalizes completion and *drives* the screening axis to its terminal outcome. Each axis is described in detail in §3; what matters globally is that they are separate fields with separate enumerations and that a state-transition request which targets an axis already past the required source state is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.7. Quota Reservation, Commitment, and Cascading Release

Quota is the scarcest resource in fielding, and the platform tracks it with three live counts on every `QuotaCell`: `reserved_n`, `committed_n`, and `available_n`. These are always derived freshly from the current state of the cell's participations, never stored as drifting tallies. A participation **reserves** a seat while its screening axis is `SCREENING` or `SCREENED_IN`; it **commits** a seat once its screening axis reaches `QUALIFIED`. Concretely, `reserved_n` is the number of participations on this cell whose `screening_status` is `SCREENING` or `SCREENED_IN`; `committed_n` is the number whose `screening_status` is `QUALIFIED`; and `available_n` is the target minus reserved minus committed, but never below zero (when reserved plus committed exceeds the target, available is reported as zero). The evaluation order is pinned: `reserved_n` and `committed_n` are each computed first from the *current* `screening_status` of every participation, and only then is `available_n` derived from them. Because a participation's screening status partitions the two sets, any single participation is counted in exactly one of reserved or committed, and never in both. A cell's `fill_status` is `FILLED` when `committed_n` is greater than or equal to `target_n`, and `OPEN` otherwise.

The crucial consequence is **cascading release**. Whenever a participation leaves the reserving set — screened out, voided, failed, or abandoned — its seat is immediately freed: the cell's `reserved_n` drops and its `available_n` rises, reopening recruitment for that segment. These releases are not separate operations; they fall directly out of recomputing the counts from current state. At the study level, `target_total_n` is the sum of `target_n` across the study's cells and `committed_total_n` is the sum of `committed_n` across them; both are recomputed when a study is read or launched.

### 2.8. The Incentive Ledger: Provisional Holds and Finalized Credits

Money in this system flows through an append-only ledger of `IncentiveAccrual` rows, and the governing principle is that points are **held before they are earned**. Each accrual carries an `accrual_kind` of `PROVISIONAL`, `FINALIZED`, or `REVERSAL`; a signed `points` delta (positive for provisional and finalized rows, negative for reversal rows); and a `status` of `HELD`, `CREDITED`, or `VOID`. A `HELD` accrual does *not* count toward a panelist's spendable balance; only a `CREDITED` accrual does. When a participation screens in, a provisional accrual is created in `HELD` status. When that participation later qualifies, the held provisional accrual flips to `CREDITED` and its point value is replaced by the finalized amount. When instead the participation falls out, the held provisional accrual flips to `VOID` and no points are ever credited. The arithmetic of the two accrual variants is specified in §3; the global rule here is simply that held holds are invisible to the balance and only credited holds are real money.

A panelist's spendable `points_balance` is therefore an aggregate, recomputed on demand and never stored as a running total. It is the sum of `points` across that panelist's `CREDITED` accruals, minus the points consumed by their payout requests that have reached `APPROVED` or `PAID` status. The pinned order matters: credited points and consumed points are each fully summed over current row states before the subtraction. A payout request only consumes points once it reaches `APPROVED` — a request still in `REQUESTED` status does not yet reduce the balance available to a competing request.

### 2.9. Precision and Rounding

All money and score quantities in this system are integers. Where a calculation produces a fractional intermediate that must be reduced to an integer result — finalizing an incentive by a quality multiplier, computing a weighted quality score, computing a health score — the result is rounded **half-up** to a whole number (a fractional part of exactly one-half rounds away from zero). Point balances, quota counts, and cash amounts in cents are exact integers throughout.

### 2.10. Optimistic Concurrency on Race-Prone Creates

Two create operations guard against a client acting on a stale read of a parent resource, and both use optimistic concurrency keyed on the parent's `version`.

When creating a payout request, the request body must include `expected_panelist_version` carrying the `version` of the target `Panelist` that the client last observed. A finalized accrual or a reversal can legitimately change a panelist's `points_balance` and bump its `version` after the client read the balance. If `expected_panelist_version` does not equal the panelist's current `version`, the create is rejected with `ERR_STALE_PANELIST_VERSION` (HTTP 412), so the client cannot redeem points the panelist no longer has. The corresponding write endpoint is the payout-request create operation.

When creating a focus-group booking, the request body must include `expected_focus_group_version` carrying the `version` of the target `FocusGroup` that the client last observed. Another writer may have just confirmed a booking, legitimately consuming the last seat and bumping the session's `version`. If `expected_focus_group_version` does not equal the focus group's current `version`, the booking create is rejected with `ERR_STALE_FOCUS_GROUP_VERSION` (HTTP 412), so the session is not oversold. The corresponding write endpoint is the focus-group-booking create operation.

These are the only two operations that take a version field; no other create or transition requires one.

## 3. Business Logic & Workflows

### 3.1. Designing a Study and Its Quota Frame

A `ResearchManager` opens the lifecycle by creating a `Study`, supplying its `title`, its `irb_protocol_number` (the IRB reference under which the work is conducted), the `estimated_minutes` it should take to complete (which must be at least 1), the `base_incentive_points` awarded for a completed response (which must be at least 0), and the `screener_min_age` the screener will enforce (at least 0). The body may also set `required_consent_version`, the consent-form version a panelist must have accepted to take part; if omitted it defaults to 1, and it must be at least 1. A new study begins in `DRAFT` with its computed quota totals `target_total_n` and `committed_total_n` both at zero, and its `status` enumerated across `DRAFT`, `FIELDING`, `PAUSED`, `CLOSED`, and `DELIVERED`.

While a study is still being designed (in `DRAFT`, or later in `FIELDING`), the manager builds its quota frame by adding `QuotaCell` records, each naming a `segment_key` — the demographic segment label such as a region-and-age band — and a `target_n` of qualified completes for that segment (at least 1). A cell is born with `reserved_n` and `committed_n` at zero, `available_n` equal to its target, and `fill_status` of `OPEN`. The `segment_key` must be unique within a single study's quota cells; attempting to add a second cell with a segment label already in use for that study is rejected with `ERR_DUPLICATE_SEGMENT` (HTTP 409). Each cell records the `study_id` it belongs to.

Launching the study moves it from `DRAFT` to `FIELDING`, which opens recruitment. Two preconditions guard the launch: the `irb_protocol_number` must be non-empty, and the study must have at least one quota cell so that `target_total_n` is at least 1. A launch attempted with an empty IRB protocol is rejected with `ERR_IRB_PROTOCOL_REQUIRED` (HTTP 422); a launch attempted with no quota cells (total target below 1) is rejected with `ERR_NO_QUOTA_CELLS` (HTTP 409). On a successful launch the system recomputes `target_total_n` as the sum of the cells' targets.

### 3.2. Recruiting and Screening Panelists

Before anyone can be recruited they must exist on the roster. A `PanelOps` operator registers a `Panelist` with an `email` (globally unique across the panel), a `full_name`, an `age` in years (at least 0), and a `segment_key` naming the demographic segment they belong to. A newly registered panelist starts in `ACTIVE` status — drawn from `ACTIVE`, `AT_RISK`, `CHURNED`, and `SUSPENDED` — with a `points_balance` of zero, a `health_score` of 100, and lifetime counters `lifetime_invited_n` and `lifetime_completed_n` at zero, alongside a `last_activity_at` that is null until they first participate.

Consent is recorded before screening can succeed. A `PanelOps` operator (on a panelist's behalf) or the `Panelist` themselves records a `Consent` naming the `panelist_id`, the `study_id`, the `consent_version` of the form being responded to (at least 1), and a `decision` of `ACCEPTED`, `DECLINED`, or `WITHDRAWN`. The server stamps `recorded_at` from the logical clock. Consent records are immutable.

A `FieldCoordinator` recruits a specific panelist into a study by creating a `Participation`, supplying the `study_id`, the `panelist_id`, and the `quota_cell_id` of the cell whose seat is being reserved. The new participation begins with `screening_status` of `SCREENING`, `completion_status` of `NOT_STARTED`, and `rescreen_count` of 0. Creation reserves a seat on the named cell (its `reserved_n` recomputes upward), increments the panelist's `lifetime_invited_n`, sets the panelist's `last_activity_at` to the clock's current instant, and recomputes the panelist's health.

The coordinator then screens the participation by supplying an `outcome`. An outcome of IN advances the screening axis `SCREENING → SCREENED_IN`; an outcome of OUT advances it `SCREENING → SCREENED_OUT`. Several preconditions gate a screen-in, and they are evaluated after the standard authentication, authorization, existence, and state checks. The parent study must be in `FIELDING` — screening while the study is paused or not yet launched is rejected with `ERR_STUDY_NOT_FIELDING` (HTTP 409). An accepted consent must already exist: there must be a `Consent` for this `(panelist_id, study_id)` pair whose `decision` is `ACCEPTED` at a `consent_version` of at least the study's `required_consent_version`; absent that, the screen is rejected with `ERR_CONSENT_REQUIRED` (HTTP 422). The panelist's `age` must be at least the study's `screener_min_age`; a younger panelist is rejected with `ERR_SCREENER_AGE_FAIL` (HTTP 422). And the cell must still have a seat — `available_n` of at least 1 — or the screen is rejected with `ERR_QUOTA_CELL_FULL` (HTTP 409). A screen-out has only the study-fielding precondition and releases the participation's reserved seat (the cell's `reserved_n` recomputes, raising `available_n`).

When a participation screens in, the system computes its `provisional_points` and writes a provisional incentive accrual in `HELD` status holding exactly that many points (see §3.5 for the arithmetic). This is where reserved quota and held money come into being together.

A screened-out participation is not necessarily finished. The coordinator may **rescreen** it, cycling `SCREENED_OUT → SCREENING` to give it another pass. Rescreening requires that the study still be in `FIELDING`, that the cell again have an available seat (`available_n` of at least 1, else `ERR_QUOTA_CELL_FULL`, HTTP 409), and that the participation has not exhausted its rescreen budget — its `rescreen_count` must be strictly below the maximum of three rescreens, or the request is rejected with `ERR_RESCREEN_LIMIT` (HTTP 422). A successful rescreen increments `rescreen_count` by one and re-reserves a seat on the cell.

### 3.3. Taking the Survey and Resolving Quality

The completion axis is the panelist's own track through the instrument, enumerated across `NOT_STARTED`, `IN_PROGRESS`, `COMPLETED`, and `ABANDONED`. A `Panelist` starts their survey, moving completion `NOT_STARTED → IN_PROGRESS`; this is only permitted once their `screening_status` is `SCREENED_IN`, and it refreshes the panelist's `last_activity_at` to the current clock instant.

Submitting the survey moves completion `IN_PROGRESS → COMPLETED` and is the single most consequential action in the system, because it computes quality and then drives the screening axis to its terminal. The submit body must supply `completion_seconds` (how long the panelist took) and `straightline_run` (the longest run of identical grid answers, a classic inattentiveness signal); if either is absent the submit is rejected with `ERR_SUBMIT_FIELDS_MISSING` (HTTP 422). Submitting is permitted only while `screening_status` is `SCREENED_IN`. Along the way, attention and fraud checks may have been recorded against this participation: a `FieldCoordinator` records an `AttentionCheck` naming the `check_kind` (`TRAP_QUESTION`, `INSTRUCTED_RESPONSE`, or `TIMING`) and whether the panelist `passed`, with `recorded_at` stamped from the clock; these immutable rows feed the quality computation. On submit the system computes the participation's `quality_score`, derives its `quality_status`, recomputes the panelist's `lifetime_completed_n`, refreshes `last_activity_at`, and recomputes the panelist's health.

The derived `quality_status` then steers the screening axis. When quality lands at `PASS` or `FLAGGED`, the participation advances `SCREENED_IN → QUALIFIED`: the reserved seat becomes a committed seat (the cell's `committed_n` recomputes and its `fill_status` may flip from `OPEN` to `FILLED`), and the held provisional accrual is finalized — it flips to `CREDITED` and its point value is replaced by the finalized amount. When instead quality lands at `FAIL`, the participation moves `SCREENED_IN → SCREENED_OUT`: the reserved seat is released (the cell's `reserved_n` recomputes) and the held provisional accrual flips to `VOID`, crediting nothing. These two submit outcomes are mirror images and must be implemented with equal care: one commits a seat and credits money, the other releases a seat and voids money.

A panelist may instead abandon an in-progress survey, moving completion `IN_PROGRESS → ABANDONED`. Abandonment has a cross-axis consequence: if at that moment the screening axis is still `SCREENING` or `SCREENED_IN`, it is forced to `VOIDED`, which releases the reserved seat (the cell's `reserved_n` recomputes) and flips any held provisional accrual to `VOID`.

### 3.4. Voids, Suspensions, and Study Closure

`VOIDED` is the screening axis's catch-all release terminal, reached not only by abandonment but by two operator actions that sweep participations in bulk. When a `ResearchManager` closes a study (moving it `FIELDING → CLOSED`, or `PAUSED → CLOSED`), every participation on that study still in `SCREENING` or `SCREENED_IN` is forced to `VOIDED` — this is the study-closure cascade. Each such void releases that participation's reserved seat on its quota cell and flips its held provisional accrual to `VOID`. A study may also be paused (`FIELDING → PAUSED`), which freezes recruitment so that no new participations are accepted while paused, and resumed (`PAUSED → FIELDING`), which unfreezes recruitment; pausing and resuming form a revision cycle a manager may traverse repeatedly.

The same sweep happens at the panelist level. A `PanelOps` operator may suspend a panelist (`ACTIVE → SUSPENDED` or `AT_RISK → SUSPENDED`); a suspension is not terminal and forces every one of that panelist's participations still in `SCREENING` or `SCREENED_IN` to `VOIDED`, again releasing their seats and voiding their held accruals. A suspended panelist can be reinstated (`SUSPENDED → ACTIVE`). In every case the void is identical in effect: leave the reserving set, free the seat, void the hold.

### 3.5. Pricing the Incentive: Provisional Then Finalized

The incentive a participation earns is computed in two passes that share a common base. The **provisional** amount, computed at screen-in, is the study's `base_incentive_points` plus a length bonus. The length bonus rewards longer surveys in steps: take the study's `estimated_minutes`, divide by the bonus step of 5 minutes, round that quotient **up** to the next whole number of steps, and multiply by 10 points per step. So a 5-minute study earns one step (10 bonus points), an 11-minute study earns three steps (30 bonus points, because 11 divided by 5 rounds up to 3), and so on. This provisional total is written into the `HELD` provisional accrual at screen-in and does not yet count toward the balance.

The **finalized** amount is computed only when the participation qualifies, and it scales the provisional amount by a quality multiplier keyed to the `quality_score`. The multiplier is 1.25 when the score is at least 90, 1.00 when the score is at least 70 (but below 90), 0.50 when the score is at least 50 (but below 70), and 0.00 otherwise. The finalized points are the provisional points multiplied by this multiplier, rounded half-up to a whole number. Because only `PASS` (score at least 70) and `FLAGGED` (score from 50 to 69) outcomes ever reach `QUALIFIED`, the finalize step in practice applies either the 1.25, the 1.00, or the 0.50 multiplier; the 0.00 multiplier never fires at finalize because a failing score is screened back out instead. When finalization runs, the held provisional accrual becomes `CREDITED` and its `points` value is replaced by this finalized figure.

A reversal accrual (`accrual_kind` of `REVERSAL`, a negative `points` delta) exists in the ledger vocabulary to back out a previously credited amount; it is the mechanism by which a panelist's credited total can legitimately fall, and is one of the events that bumps a panelist's `version` between a client's read and a subsequent payout request. The `points` field on any accrual is the signed delta described here. Accruals are listable and individually retrievable for audit, filtered by `panelist_id` or `participation_id`, and each names the `participation_id` that earned or reversed it.

### 3.6. Scoring Response Quality and Panel Health

The `quality_score` is a weighted blend of three component scores, each on a 0-to-100 scale, computed at submit. The **attention** component is the percentage of this participation's attention checks that passed — passed checks divided by total checks, times 100 — or a full 100 if no checks were recorded. The **speed** component is a fraud tripwire: if the panelist's `completion_seconds` is below 34 percent of the study's estimated duration in seconds (that is, below `estimated_minutes` times 60 times 0.34), the speed score is 0, because suspiciously fast completion is the strongest fraud signal; if `completion_seconds` is above 3 times the estimated duration in seconds (`estimated_minutes` times 60 times 3.0), the speed score is 50; otherwise the speed score is 100. The **straightlining** component starts at 100 and subtracts 4 points for each unit of `straightline_run`, but never drops below 0 (that is, 100 minus `straightline_run` times 4, floored at 0). The overall `quality_score` weights attention at 0.5, speed at 0.3, and straightlining at 0.2, summing the three weighted components and rounding half-up to a whole number in the 0-to-100 range.

From the score, `quality_status` is derived in tiers: `PASS` when the score is at least 70, `FLAGGED` when the score is at least 50 but below 70 (kept in the dataset but marked for human review), and `FAIL` when the score is below 50. Until a participation is submitted, its `quality_status` is `PENDING` and its `quality_score` is null.

Panel **health** is a rolling measure of how engaged a panelist is, recomputed whenever a participation is created or completed and whenever health is explicitly read. The persisted `health_score` uses a rolling window of that panelist's five most recent participations by creation time (newest first). Within that window, the base score is the fraction of windowed participations whose `completion_status` is `COMPLETED`, times 100 — or 100 if the window is empty. From the base an inactivity penalty is subtracted: take the number of whole days since the panelist's `last_activity_at`, divide by the 30-day step, round **down** to whole steps, and multiply by 5 points per step. The `health_score` is the base minus that penalty, clamped to the 0-to-100 range and rounded half-up. A read of a panelist's health returns this rolling figure as `health_score` and also returns a `lifetime_health_score` computed identically but over **all** of the panelist's participations rather than the recent five (its denominator is the panelist's full `lifetime_invited_n` rather than the recent window), plus the panelist's `status`.

The health score steers the panelist's status automatically. On each health recompute, if `health_score` falls below the churn threshold of 50, an `ACTIVE` panelist becomes `AT_RISK` (the `ACTIVE → AT_RISK` transition); if `health_score` rises back to at least 50, an `AT_RISK` panelist returns to `ACTIVE` (the `AT_RISK → ACTIVE` transition) — a health-driven cycle. An `AT_RISK` panelist may be explicitly marked churned by a `PanelOps` operator, moving `AT_RISK → CHURNED`, but only when `health_score` is below the churn floor of 30; marking churned cascades exactly like a suspension, forcing the panelist's `SCREENING` and `SCREENED_IN` participations to `VOIDED` with their seats released and held accruals voided. `CHURNED` is terminal.

### 3.7. Paying Panelists Out

A panelist redeems accumulated points through a `PayoutRequest`, created by the `Panelist` (or by `PanelOps` on their behalf), naming the `panelist_id`, a `payout_method` of `CASH` or `GIFT_CARD`, the `points_requested` to redeem (at least 1), and the `expected_panelist_version` for the stale-balance guard described in §2.10. At request time the server computes `cash_cents` as `points_requested` times the conversion rate of 2 cents per point. The request must redeem at least the minimum payout of 100 points; a smaller request is rejected with `ERR_PAYOUT_BELOW_MINIMUM` (HTTP 422). A new request begins in `REQUESTED` — drawn from `REQUESTED`, `APPROVED`, `PAID`, `REJECTED`, and `CANCELLED`.

A `PanelOps` operator approves a request, moving it `REQUESTED → APPROVED`, but only if the panelist's current `points_balance` is at least the `points_requested` at approval time; an underfunded request is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422). Approval is the moment the points are consumed — once `APPROVED`, the `points_requested` are subtracted from the panelist's spendable balance — and approval increments the panelist's `version` by one (which is exactly why a later, stale payout request can be caught by the version guard). An approved request is later paid, moving it `APPROVED → PAID`, at which point the points remain consumed and the disbursement is made. Alternatively a `PanelOps` operator may reject a request (`REQUESTED → REJECTED`), or the owning `Panelist` may cancel it (`REQUESTED → CANCELLED`); neither rejection nor cancellation consumes points. `PAID`, `REJECTED`, and `CANCELLED` are terminal.

### 3.8. Focus Groups: Facilities, Sessions, and Bookings

In-person research runs through physical rooms. A `FieldCoordinator` registers a `Facility` with a `name`, a `capacity` (the maximum panelists the room seats, at least 1), and a `turnaround_minutes` buffer required after a session before the room is free again (defaulting to 0, at least 0); a facility starts `AVAILABLE` (the other status being `OFFLINE`). The coordinator then schedules a `FocusGroup` against a study and a facility, supplying the `study_id`, the `facility_id`, the session window `starts_at` (inclusive) and `ends_at` (exclusive) as ISO 8601 UTC instants, and the number of `seats` offered. The offered `seats` must not exceed the facility's `capacity`, or scheduling is rejected with `ERR_SEATS_EXCEED_CAPACITY` (HTTP 422). The session's window, extended by the facility's turnaround buffer, must not overlap any other `SCHEDULED` session on the same facility; a clash is rejected with `ERR_FACILITY_DOUBLE_BOOKED` (HTTP 409). A new focus group starts `SCHEDULED` (the other statuses being `CANCELLED` and `COMPLETED`) with `booked_n` at zero, where `booked_n` is the live count of its `CONFIRMED` bookings.

Booking a panelist into a session creates a `FocusGroupBooking` naming the `focus_group_id`, the `panelist_id`, and the `expected_focus_group_version` for the oversell guard of §2.10. A booking is created by the `Panelist` (or by a `FieldCoordinator` on their behalf) and begins `CONFIRMED` (the other statuses being `CANCELLED`, `NO_SHOW`, and `ATTENDED`); creation recomputes the session's `booked_n` upward and increments the session's `version` by one. Two scheduling constraints guard a booking. First, the panelist must not already hold a `CONFIRMED` booking on another `SCHEDULED` session whose window overlaps this one (compared on the half-open `starts_at`–`ends_at` interval, with no turnaround buffer between a panelist's own sessions); a clash is rejected with `ERR_PANELIST_SCHEDULE_CONFLICT` (HTTP 409). Second, the session must still have room — booking is blocked once `booked_n` is greater than or equal to the offered `seats`, in which case it is rejected with `ERR_SESSION_FULL` (HTTP 409).

A booking may be cancelled by its owning `Panelist` (or a `FieldCoordinator`), moving it `CONFIRMED → CANCELLED` and recomputing the session's `booked_n` downward to free the seat. Cancelling the whole focus group (`SCHEDULED → CANCELLED`) cascades down: every `CONFIRMED` booking on it is moved to `CANCELLED`. A session is completed (`SCHEDULED → COMPLETED`) only once the logical clock has reached or passed its `starts_at`; on completion its `CONFIRMED` bookings stay `CONFIRMED` until individually resolved. After the session is `COMPLETED`, a `FieldCoordinator` marks each booking as either `CONFIRMED → ATTENDED` or `CONFIRMED → NO_SHOW`; both require the parent session to be `COMPLETED`.

### 3.9. Closing Out: Data Delivery and Reporting

Once fielding is over, the study's results are packaged for the sponsor. A `ResearchManager` creates a `DataDelivery` for a study, naming the `study_id` and the `report_format` (`CSV`, `SPSS`, or `DASHBOARD`); it begins `BUILDING` (the other statuses being `READY`, `DELIVERED`, and `REVOKED`) with `included_completes_n` at zero. Building the delivery moves it `BUILDING → READY`, which requires the parent study to be `CLOSED` — building against a study that is not closed is rejected with `ERR_STUDY_NOT_CLOSED` (HTTP 409). On build, the system snapshots `included_completes_n` as the count of the study's participations whose `quality_status` is `PASS` and whose `completion_status` is `COMPLETED` at build time. A delivery may be revoked from either `BUILDING` or `READY`, moving it to `REVOKED`.

The study itself reaches its terminal once a deliverable is ready. A `ResearchManager` delivers a `CLOSED` study, moving it `CLOSED → DELIVERED`, but only when a `DataDelivery` for that study exists in `READY` status; without one the deliver is rejected with `ERR_DELIVERY_NOT_READY` (HTTP 409). Delivering the study moves that `READY` deliverable to `DELIVERED` as well. `DELIVERED` is the terminal study state, and a fully delivered study closes the loop the research manager opened in §3.1.

## 4. Endpoint Definitions

All endpoints share the response envelope and authentication rules of §2. Creating a new resource returns HTTP 201 with the created resource in `data`; reads, list operations, and state-transition operations that modify an existing resource return HTTP 200 with the affected resource (or the requested data) in `data`. The request body, response body, side effects, and trigger conditions for each endpoint are specified in the §3 narratives, not repeated here.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /studies | Create a study (DRAFT) | ResearchManager |
| GET | /studies | List studies (optional status filter) | ResearchManager, PanelOps, FieldCoordinator |
| GET | /studies/{id} | Get a study with computed quota totals | ResearchManager, PanelOps, FieldCoordinator |
| POST | /studies/{id}/launch | Launch fielding (DRAFT → FIELDING) | ResearchManager |
| POST | /studies/{id}/pause | Freeze recruitment (FIELDING → PAUSED) | ResearchManager |
| POST | /studies/{id}/resume | Unfreeze recruitment (PAUSED → FIELDING) | ResearchManager |
| POST | /studies/{id}/close | Close the study (FIELDING/PAUSED → CLOSED) | ResearchManager |
| POST | /studies/{id}/deliver | Deliver the study (CLOSED → DELIVERED) | ResearchManager |
| POST | /studies/{id}/quota-cells | Add a quota cell to a study | ResearchManager |
| GET | /studies/{id}/quota-cells | List a study's quota cells | ResearchManager, PanelOps, FieldCoordinator |
| GET | /quota-cells/{id} | Get a quota cell with live fill counts | ResearchManager, PanelOps, FieldCoordinator |
| POST | /panelists | Register a panelist (ACTIVE) | PanelOps |
| GET | /panelists | List panelists (optional status/segment filter) | PanelOps, ResearchManager, FieldCoordinator |
| GET | /panelists/{id} | Get a panelist with computed balance and health | PanelOps, ResearchManager, FieldCoordinator, Panelist |
| GET | /panelists/{id}/health | Rolling and lifetime health scores | PanelOps, ResearchManager |
| POST | /panelists/{id}/suspend | Suspend a panelist (ACTIVE/AT_RISK → SUSPENDED) | PanelOps |
| POST | /panelists/{id}/reinstate | Reinstate a panelist (SUSPENDED → ACTIVE) | PanelOps |
| POST | /panelists/{id}/mark_churned | Mark churned (AT_RISK → CHURNED) | PanelOps |
| POST | /consents | Record a consent decision | PanelOps, Panelist |
| GET | /consents | List consents (filter by panelist/study) | PanelOps, ResearchManager, Panelist |
| GET | /consents/{id} | Get a single consent record | PanelOps, ResearchManager, Panelist |
| POST | /participations | Create a participation (reserves a seat) | FieldCoordinator |
| GET | /participations | List participations (filterable) | ResearchManager, PanelOps, FieldCoordinator |
| GET | /participations/{id} | Get a participation | ResearchManager, PanelOps, FieldCoordinator, Panelist |
| POST | /participations/{id}/screen | Screen a participation IN or OUT | FieldCoordinator |
| POST | /participations/{id}/rescreen | Re-screen (SCREENED_OUT → SCREENING) | FieldCoordinator |
| POST | /participations/{id}/start | Start the survey (NOT_STARTED → IN_PROGRESS) | Panelist |
| POST | /participations/{id}/submit | Submit the survey; compute quality | Panelist |
| POST | /participations/{id}/abandon | Abandon the survey (IN_PROGRESS → ABANDONED) | Panelist |
| POST | /participations/{id}/attention-checks | Record an attention/fraud check | FieldCoordinator |
| GET | /participations/{id}/attention-checks | List a participation's attention checks | ResearchManager, FieldCoordinator |
| GET | /incentive-accruals | List incentive accruals (filterable) | PanelOps, ResearchManager |
| GET | /incentive-accruals/{id} | Get a single incentive accrual | PanelOps, ResearchManager |
| POST | /payout-requests | Request a points payout | Panelist, PanelOps |
| GET | /payout-requests | List payout requests (filterable) | PanelOps, ResearchManager, Panelist |
| GET | /payout-requests/{id} | Get a payout request | PanelOps, Panelist |
| POST | /payout-requests/{id}/approve | Approve (REQUESTED → APPROVED) | PanelOps |
| POST | /payout-requests/{id}/pay | Pay (APPROVED → PAID) | PanelOps |
| POST | /payout-requests/{id}/reject | Reject (REQUESTED → REJECTED) | PanelOps |
| POST | /payout-requests/{id}/cancel | Cancel own request (REQUESTED → CANCELLED) | Panelist |
| POST | /facilities | Create a facility/room | FieldCoordinator |
| GET | /facilities/{id} | Get a facility | FieldCoordinator, ResearchManager |
| POST | /focus-groups | Schedule a focus group | FieldCoordinator |
| GET | /focus-groups | List focus groups (filterable) | FieldCoordinator, ResearchManager, PanelOps |
| GET | /focus-groups/{id} | Get a focus group with live booked_n | FieldCoordinator, ResearchManager, PanelOps |
| POST | /focus-groups/{id}/cancel | Cancel a session (cascades bookings) | FieldCoordinator |
| POST | /focus-groups/{id}/complete | Complete a session (SCHEDULED → COMPLETED) | FieldCoordinator |
| POST | /focus-group-bookings | Book a panelist into a session | Panelist, FieldCoordinator |
| GET | /focus-group-bookings | List bookings (filterable) | FieldCoordinator, ResearchManager, PanelOps, Panelist |
| GET | /focus-group-bookings/{id} | Get a single booking | FieldCoordinator, ResearchManager, PanelOps, Panelist |
| POST | /focus-group-bookings/{id}/cancel | Cancel own booking (CONFIRMED → CANCELLED) | Panelist, FieldCoordinator |
| POST | /focus-group-bookings/{id}/mark_attended | Mark attended (CONFIRMED → ATTENDED) | FieldCoordinator |
| POST | /focus-group-bookings/{id}/mark_no_show | Mark no-show (CONFIRMED → NO_SHOW) | FieldCoordinator |
| POST | /data-deliveries | Create a data delivery (BUILDING) | ResearchManager |
| GET | /data-deliveries | List data deliveries (filterable) | ResearchManager, PanelOps |
| GET | /data-deliveries/{id} | Get a single data delivery | ResearchManager, PanelOps |
| POST | /data-deliveries/{id}/build | Build the delivery (BUILDING → READY) | ResearchManager |
| POST | /data-deliveries/{id}/revoke | Revoke the delivery (BUILDING/READY → REVOKED) | ResearchManager |
| POST | /_clock/set_current_utc | Set the server's logical clock | ResearchManager, PanelOps, FieldCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_CONSENT_REQUIRED | 422 |
| ERR_SCREENER_AGE_FAIL | 422 |
| ERR_QUOTA_CELL_FULL | 409 |
| ERR_DUPLICATE_SEGMENT | 409 |
| ERR_RESCREEN_LIMIT | 422 |
| ERR_STUDY_NOT_FIELDING | 409 |
| ERR_SUBMIT_FIELDS_MISSING | 422 |
| ERR_FACILITY_DOUBLE_BOOKED | 409 |
| ERR_PANELIST_SCHEDULE_CONFLICT | 409 |
| ERR_SESSION_FULL | 409 |
| ERR_SEATS_EXCEED_CAPACITY | 422 |
| ERR_PAYOUT_BELOW_MINIMUM | 422 |
| ERR_INSUFFICIENT_POINTS | 422 |
| ERR_STALE_PANELIST_VERSION | 412 |
| ERR_STALE_FOCUS_GROUP_VERSION | 412 |
| ERR_DELIVERY_NOT_READY | 409 |
| ERR_STUDY_NOT_CLOSED | 409 |
| ERR_NO_QUOTA_CELLS | 409 |
| ERR_IRB_PROTOCOL_REQUIRED | 422 |

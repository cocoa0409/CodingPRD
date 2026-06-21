# Earned Wage Access API — Product Requirements Document

## 1. Introduction

Earned Wage Access (EWA), sometimes marketed as On-Demand Pay, lets a worker draw against wages they have already earned before the employer's scheduled payday. This API is the system of record for that flow end to end: it ingests an employer's time feed, projects how much of a worker's accrued pay is safely accessible, prices and disburses advances out of an employer-prefunded pool, recoups those advances on payday through a chronological waterfall, and finally reconciles every cent so that an employer's funding pool and its outstanding worker exposure always balance.

The product is built around two control objectives that frequently pull in opposite directions. The first is worker access — a worker should be able to reach a fair fraction of earnings on demand, subject to tenure-based limits, fee caps, and a cooling-off interval between draws. The second is fiscal and compliance integrity — every disbursement reserves principal plus fee against a finite employer pool, payday recoup must never claw back more than the worker's protected take-home, and the act of approving an advance must be segregated from the acts of posting its repayment batch and signing its reconciliation statement. Because money moves and obligations cascade across workers, pay periods, advances, batches, and statements, the system treats consistency as immediate: a single operation may legitimately mutate several entities at once, and the API guarantees those secondary effects land atomically with the primary one.

This document specifies the global contracts every endpoint shares (Section 2), the business logic and lifecycle workflows that distinguish this domain (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers the API emits (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying an `X-User-Role` value that is not a recognized role, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `PayrollOfficer`, `ComplianceOfficer`, and `Worker`.

A `PlatformAdmin` is the platform operator. It provisions employers, advance limit policies, fee schedules, and funding top-ups, and it controls the deterministic test clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

A `PayrollOfficer` is the employer-side payroll operator who opens and locks pay periods, manages the worker roster and the time feed, approves and disburses advances, and posts recoup batches. When `X-User-Role` is `PayrollOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a transition writes it — for example, as `posted_by_user_id` on a `RepaymentBatch` when that officer posts the batch — but it is never compared to any entity's `id`.

A `ComplianceOfficer` is the employer-side controller who signs reconciliation statements and writes off unrecoverable debt. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a transition writes it — for example, as `signed_by_user_id` on a `ReconciliationStatement` when that officer signs it — but it is never compared to any entity's `id`.

A `Worker` is a self-service end user who requests advances against their own earnings and views their own advances, repayments, and profile. When `X-User-Role` is `Worker`, `X-User-ID` is the `id` of the acting `Worker`; ownership checks on any resource that references a `Worker` compare the resource's `worker_id` foreign key to `X-User-ID`. In particular, a `Worker` may only create an advance where the body's `worker_id` equals `X-User-ID`, and may only read advances, repayments, and the worker profile that belong to that same identity.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, drawn from the server's real wall-clock UTC time at the moment of the response and independent of the deterministic test clock of Section 3.12 (the test clock governs only persisted, server-stamped entity fields, not this envelope timestamp).
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

List endpoints accept two query parameters to page through results. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` that is not an integer, or is below 1 or above 100, is rejected with `ERR_INVALID_REQUEST` (the bound is enforced by rejection, not by clamping). The `offset` parameter specifies how many leading items to skip and defaults to 0; a supplied `offset` that is not an integer or is negative is likewise rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full size of the filtered collection and `has_more` indicates whether further pages remain.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources in this system — `Employer`, `AdvanceLimitPolicy`, `FeeSchedule`, `PayPeriod`, `Worker`, `Advance`, `RepaymentBatch`, and `ReconciliationStatement` — carry a common set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix. Each has a `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured at creation, and an `updated_at`, an ISO 8601 UTC timestamp refreshed on every subsequent mutation. Each also carries a `version`, an integer that starts at the resource's creation value and increments by one on every mutation; it is the basis of optimistic concurrency control described in Section 2.7.

Two entities are deliberately lighter. A `TimeEntry` and a `Repayment` are write-once ledger rows: each carries only an `id` and a `created_at`. Neither a `TimeEntry` nor a `Repayment` carries an `updated_at` or a `version` field — those fields are absent entirely for these two entities. A `TimeEntry` does carry a `status` that can move from `POSTED` to `VOIDED`, but voiding is modeled as a state event on a row that otherwise exposes no version counter.

When the server derives a computed field (for example, refreshing a worker's available-earnings figure, an employer's posture, or a statement's drift), and that recomputation changes a resource that carries `version`, it counts as a mutation: the resource's `updated_at` is refreshed and its `version` increments. Cascading recomputations therefore each independently bump the `version` of the resource they touch.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Operations in this domain frequently mutate more than one entity. The system applies all such secondary effects synchronously and atomically with the triggering operation, and it does so without requiring a separate client call against each affected resource. The most consequential cascade is payday close, described narratively in Section 3, which can ripple through four levels in a single operation: un-recouped advances are defaulted, each defaulted advance places its worker on hold, the period's reconciliation statement is recomputed to reflect those defaults, and if that statement lands in discrepancy the employer's posture is driven to a frozen state. Disbursing an advance, settling one, posting a batch, manually recovering on a default, and writing off bad debt each carry their own cascades, all enumerated where the relevant workflow is described. The governing rule is that every entity touched by a cascade has its `updated_at` refreshed and, where it carries a `version`, its `version` incremented.

### 2.6. Monetary Precision and Rounding

All monetary quantities in this system are stored and returned as integer cents; there are no fractional-cent values in any response body. Where a calculation multiplies hours by a rate or applies a percentage and a fractional cent could arise, the result is rounded half up to the nearest whole cent. Two rounding-order rules are load-bearing and are stated precisely with their calculations in Section 3: gross earnings are computed by rounding the sum once at the end (sum-then-round), never by summing already-rounded per-entry values; and the percent component of an expedite fee is rounded half up before it is added to the flat component (round-then-sum). Where a fraction of gross is taken as an access or recoup ceiling, the result is taken by flooring to the next lower whole cent rather than rounding.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a fresh view of a parent resource by submitting that parent's last-observed `version`. These are the only two operations that take a version field; no other endpoint accepts or requires one.

When a `Worker` (or a `PayrollOfficer` acting on a worker's behalf) requests a new advance, the create request must include `expected_worker_version` carrying the client's last observed `version` of the target `Worker`. If that value does not equal the worker's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because once a prior advance against the same worker has been disbursed, the worker's computed counters — `period_advance_count`, `net_available_earnings_cents`, and `lifetime_advanced_cents` — and its `version` have all moved; a request still carrying the pre-disbursement version is operating on a stale eligibility snapshot, and refusing it ensures the cap and available-earnings checks are never evaluated against outdated figures.

When a `PayrollOfficer` posts a repayment batch, the post request must include `expected_repaymentbatch_version` carrying the client's last observed `version` of the target `RepaymentBatch`. If that value does not equal the batch's current `version`, the post is rejected with `ERR_STALE_VERSION` (HTTP 412). A stale batch version means the draft has been recomputed or otherwise advanced since the client read it, so the client would be posting against an out-of-date view of which advances the waterfall will touch.

### 2.8. Segregation of Duties

Compliance requires that the three sensitive financial duties within a single pay period be performed by three distinct users. The user who approves any advance in a period must not be the user who posts that period's repayment batch, and must not be the user who signs that period's reconciliation statement; likewise, the batch poster must not be the statement signer. Identity for this check is the operator's `X-User-ID`. The approver's `X-User-ID` is recorded on the advance at approval solely to support this segregation check; unlike `posted_by_user_id` on a `RepaymentBatch` and `signed_by_user_id` on a `ReconciliationStatement`, the approver identity is internal bookkeeping and is not exposed on the advance read representation. The system enforces this at two points: when a batch is posted, the acting user must not be the approver of any advance in the period; and when a statement is signed, the acting user must not be the poster of the period's batch and must not be the approver of any advance in the period. A violation at either point is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.9. Funding Pool Conservation and Employer Posture

Each `Employer` maintains a prefunded pool, `funding_balance_cents`, that bankrolls its workers' advances. The pool obeys a conservation invariant: it is debited by an advance's full recoup target (principal plus fee) at disbursement and credited back by that same recoup target when the advance settles, so that the pool plus the employer's outstanding exposure is conserved across the advance lifecycle. The employer's `outstanding_principal_cents` is the running sum of `principal_outstanding_cents` across all of that employer's advances that are not in a terminal recovery state.

An employer's `posture` is a computed gate on new disbursement-class activity and takes one of three values: `HEALTHY`, `RESTRICTED`, or `FROZEN`. The posture is `RESTRICTED` when the funding pool has fallen below the employer's outstanding exposure, and it is `FROZEN` whenever any reconciliation statement for a disbursed period is in discrepancy. While the posture is `FROZEN`, disbursement-class operations — locking a period, running payday, approving an advance, and disbursing an advance — are blocked with `ERR_EMPLOYER_FROZEN` (HTTP 409). A `RESTRICTED` posture, by contrast, still permits approval and disbursement; only `FROZEN` blocks them.

### 2.10. Referential Integrity and Existence Ordering

Resources in this system form a flat topology: every entity is its own top-level collection, and relationships are expressed by foreign-key fields carried in request bodies rather than by nested URL paths. For any request whose path names a resource, the system first confirms that path resource exists, validating path identifiers left to right in the natural ownership order (employer before pay period, then worker, advance, batch, or statement). The first path identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404).

Beyond path existence, write operations that carry foreign keys in the body must point at real targets that belong to the same employer. For an advance creation, a repayment batch creation, and a time entry creation, the system resolves the body's foreign keys — `worker_id`, `pay_period_id`, `advance_id`, and `repayment_batch_id` as applicable — and confirms they exist and share a single `employer_id`. A body foreign key that exists but belongs to a different employer (or a worker and pay period whose employers disagree) is rejected with `ERR_CROSS_EMPLOYER_REFERENCE` (HTTP 422).

### 2.11. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Path existence is checked third, yielding `ERR_NOT_FOUND`. Body foreign-key cross-employer integrity is checked fourth, yielding `ERR_CROSS_EMPLOYER_REFERENCE`. Request well-formedness — all required fields present, enums within their allowed sets, numbers within declared bounds — is checked fifth, yielding `ERR_INVALID_REQUEST`. State legality — whether the requested transition is defined from the target's current state — is checked sixth, yielding `ERR_INVALID_STATE`. Optimistic-concurrency version match is checked seventh, yielding `ERR_STALE_VERSION`. Segregation of duties is checked eighth, yielding `ERR_SEGREGATION_OF_DUTIES`. Only after all of these do the domain-specific business rules described in Section 3 apply, in the order their workflows present them.

## 3. Business Logic & Workflows

### 3.1. Provisioning an Employer and Its Policy Surface

The lifecycle begins when a `PlatformAdmin` provisions an employer. An employer is created with a `legal_name`, a `state_code` naming the US state of payroll (for example, CA or TX), and a `pay_frequency`, which must be one of `WEEKLY`, `BIWEEKLY`, or `SEMIMONTHLY`. The admin may seed the funding pool at creation via `funding_balance_cents`, which defaults to 0 if omitted. Three advance-policy knobs may also be supplied at creation, each with a default if omitted: `max_advance_pct_of_available`, the ceiling fraction of a worker's net available earnings that may be advanced in a period, which defaults to 0.50 and must be greater than 0 and at most 1.0; `per_period_advance_cap_count`, the maximum number of disbursed advances a worker may take per pay period, which defaults to 3 and must be at least 1; and `cooling_off_hours`, the minimum number of hours that must elapse between one advance's disbursement and the next request for the same worker, which defaults to 24 and must be at least 0. At creation the employer's `posture` is initialized to `HEALTHY` and its `outstanding_principal_cents` is initialized to 0. The employer exposes its computed `posture` and `outstanding_principal_cents` on read.

A `PlatformAdmin` can top up the pool at any time by depositing an `amount_cents`, which is added to `funding_balance_cents`; the deposit then triggers a recomputation of `posture`, which may lift a `RESTRICTED` employer back toward `HEALTHY` once the pool again covers outstanding exposure.

Advance limits are tenure-tiered. A `PlatformAdmin` defines an advance limit policy by naming the `employer_id` it governs, the `tier` it applies to — one of `PROBATION`, `STANDARD`, or `SENIOR` — and the `min_tenure_days` that a worker must have accrued (an inclusive lower bound, at least 0) to fall into that tier. The policy fixes three money bounds: `per_advance_floor_cents`, the smallest principal a single advance may request, defaulting to 1000; `per_advance_ceiling_cents`, the largest principal a single advance may request regardless of available earnings; and `cumulative_period_ceiling_cents`, the largest total principal a worker in this tier may have disbursed or outstanding within one pay period. A policy carries a `status` of `ACTIVE` or `ARCHIVED`, defaulting to `ACTIVE`. Defining a new policy for an employer and tier archives the prior `ACTIVE` policy for that same `employer_id` and `tier` by moving it to `ARCHIVED`.

Fees are governed per employer by a fee schedule, also created by a `PlatformAdmin` against an `employer_id`. A schedule sets `expedite_flat_fee_cents`, the flat fee charged when a worker chooses instant disbursement, defaulting to 199; `expedite_pct_fee`, an additional percent-of-principal fee for instant disbursement, defaulting to 0.0 and constrained between 0 and 0.05 inclusive; `max_total_fee_cents`, a hard cap on the combined expedite-plus-tip fee per advance, defaulting to 1500; and `tip_allowed`, a boolean governing whether voluntary worker tips are accepted, defaulting to true. A schedule carries a `status` of `ACTIVE` or `ARCHIVED`, defaulting to `ACTIVE`. Defining a new fee schedule for an employer archives the prior `ACTIVE` schedule for that `employer_id`.

### 3.2. Workers, Tenure, and the Two Parallel Status Dimensions

A `PayrollOfficer` registers a worker against an `employer_id` with an `external_payroll_ref` (the employer-side payroll identifier), a `full_name`, an `hourly_rate_cents` pay rate (at least 0), and a `hire_date` marking employment start. The `external_payroll_ref` must be unique per employer among workers that are not terminated; reusing one that is already held by a non-terminated worker for the same employer is rejected with `ERR_DUPLICATE_PAYROLL_REF`. The worker's `tenure_days` is computed as the whole number of days between the server clock and `hire_date`, taking the floor; this value selects the worker's advance limit policy tier.

A worker carries two status dimensions that evolve independently on the same record. The first is `employment_status`, defaulting to `ACTIVE` and taking the values `ACTIVE`, `SUSPENDED`, or `TERMINATED`. A `PayrollOfficer` may suspend an `ACTIVE` worker, moving them `ACTIVE → SUSPENDED`; reinstate a suspended worker, moving them `SUSPENDED → ACTIVE`; or terminate a worker from either the `ACTIVE` or `SUSPENDED` state, moving them to `TERMINATED`. Termination is blocked while the worker still has any advance in the `DISBURSED`, `RECOUPING`, or `DEFAULTED` state, in which case the request is rejected with `ERR_WORKER_HAS_OPEN_ADVANCE`. Terminating a worker frees their `external_payroll_ref` for reuse. Suspension blocks new advance approvals but does not touch the second dimension.

The second dimension is `advance_eligibility`, defaulting to `ELIGIBLE` and taking the values `ELIGIBLE` or `ON_HOLD`. This dimension is not driven by officer actions; it is a system-maintained reflection of the worker's debt. A worker is `ON_HOLD` exactly when they have at least one advance in the `DEFAULTED` or `WRITTEN_OFF` set, and returns to `ELIGIBLE` only when that set is empty. The distinction between the two recovery outcomes matters here: a manual recovery that drives a `DEFAULTED` advance all the way to `SETTLED` removes it from the penalty set and can clear the hold, whereas a write-off leaves the advance in `WRITTEN_OFF`, which remains in the penalty set and therefore sustains the hold because the debt was never actually repaid.

A worker also exposes several computed counters on read: `period_advance_count`, the number of this worker's advances in the `DISBURSED`, `RECOUPING`, or `DEFAULTED` set whose `pay_period_id` is the employer's current non-disbursed pay period; `net_available_earnings_cents`, the forward-looking available-earnings figure described in Section 3.4; and `lifetime_advanced_cents`, the sum of `principal_cents` across every advance this worker has ever had disbursed.

### 3.3. Pay Periods and the Time Feed

A `PayrollOfficer` opens a pay period for an employer by supplying a `start_at` and an `end_at`, both UTC instants. A period occupies the half-open interval that includes `start_at` and excludes `end_at`; `end_at` must be strictly after `start_at`, and payday is `end_at`. At creation the system assigns `period_index`, a monotonic per-employer counter that starts at 0, and sets `status` to `OPEN`. A new period's interval must not overlap any other non-disbursed period of the same employer; abutting periods, where one period's `end_at` exactly equals the next period's `start_at`, are permitted because the interval is half-open. An overlapping new period is rejected with `ERR_PERIOD_OVERLAP`.

A period's `status` flows `OPEN → LOCKED → DISBURSED`, with a cyclic reopen loop allowing `LOCKED → OPEN`; `DISBURSED` is terminal. Locking, performed by a `PayrollOfficer`, freezes the time feed: it requires the employer's posture not to be `FROZEN` (otherwise `ERR_EMPLOYER_FROZEN`), stamps `locked_at` with the server clock, and recomputes the period's `gross_accrued_cents` over its posted time entries. While a period is `LOCKED`, new time entry posts are rejected. Reopening, also by a `PayrollOfficer`, moves `LOCKED → OPEN` to allow late time-entry corrections; it is blocked when any repayment batch for the period is already posted or reconciled, in which case it is rejected with `ERR_PERIOD_HAS_POSTED_BATCH`, and on success it clears `locked_at` back to null. The third transition, running payday, is described in Section 3.8.

A period accumulates a time feed of shift rows. A `PayrollOfficer` posts a time entry by naming the `pay_period_id` and `worker_id` it belongs to, the `shift_start_at` and `shift_end_at` instants bounding the shift, and the `hours_worked` on that shift. The worker's employer must match the pay period's employer. A time entry carries a `status` of `POSTED` or `VOIDED`, defaulting to `POSTED`; only `POSTED` entries count toward earnings and toward overlap detection. Each entry also exposes a per-entry display value, `gross_earned_cents`, computed by rounding the product of `hours_worked` and the worker's `hourly_rate_cents` half up to whole cents. This display value is for presentation only — earnings aggregates always recompute from raw hours times rate with a single final rounding and never by summing this field. Posting a time entry recomputes the period's `gross_accrued_cents` and the worker's `net_available_earnings_cents`.

A time entry is accepted only when it sits cleanly in its period and is internally consistent. The shift's `shift_start_at` is inclusive and must fall within the period's interval — that is, at or after `start_at` and strictly before `end_at`; `shift_end_at` is inclusive, must be strictly after `shift_start_at`, and must fall within the period, meaning it too must be at or after `start_at` and strictly before `end_at` (so a `shift_end_at` equal to the period's `end_at` is out of window because the period interval is half-open); the period must be `OPEN`; and `hours_worked` must be greater than 0 and at most 24, and must equal the span between `shift_start_at` and `shift_end_at` measured in hours to within one hundredth of an hour. Any of these failing yields `ERR_TIME_ENTRY_OUT_OF_WINDOW`. Separately, the new shift — treated as a closed interval that includes both its start and end — must not overlap, and must be separated by at least thirty minutes of rest from, any existing `POSTED` time entry of the same worker; the rest buffer is thirty minutes (that is, half an hour) measured between the closed intervals. A shift that overlaps an existing posted shift, or that falls within that thirty-minute rest gap, is rejected with `ERR_SHIFT_OVERLAP`. A `PayrollOfficer` may void a posted time entry, which sets its `status` to `VOIDED` and recomputes the affected period and worker earnings.

### 3.4. Computing Available Earnings (Forward-Looking)

A worker's `net_available_earnings_cents` answers a forward-looking question: of what this worker has earned so far in the employer's current open or locked pay period, how much may still be advanced after accounting for advances already committed against the same period? The figure is computed on read of the worker and again at advance approval, and it is built in a fixed order.

First, identify the period as the employer's current pay period whose status is `OPEN` or `LOCKED`; if more than one of the employer's periods is non-disbursed (`OPEN` or `LOCKED`), the one with the greatest `period_index` is taken as current, and if none is non-disbursed the figure is 0. Second, compute the period's gross earned for this worker as the sum, over that worker's `POSTED` time entries in that period, of `hours_worked` multiplied by the worker's `hourly_rate_cents`, with the entire sum rounded half up to whole cents exactly once at the end. This sum-then-round order is mandatory: rounding each entry first and then summing can differ by cents and is the wrong order. Third, take the accessible amount as the floor of that gross earned multiplied by the employer's `max_advance_pct_of_available`; the access fraction is floored, not rounded. Fourth, compute the committed amount as the sum of `recoup_target_cents` over this worker's advances in the `APPROVED`, `DISBURSED`, `RECOUPING`, or `DEFAULTED` set whose `pay_period_id` is that period. The net available earnings is then the accessible amount minus the committed amount, with the result clamped to a floor of 0 so it never goes negative. Note that availability nets the full recoup target (principal plus fee) of committed advances, not merely their principal.

### 3.5. Requesting and Pricing an Advance

A `Worker`, or a `PayrollOfficer` on the worker's behalf, requests an advance by naming the `worker_id` and the `pay_period_id` it draws against, a `requested_principal_cents` (at least 1) before any eligibility clamping, an optional `disbursement_speed` of `STANDARD` or `INSTANT` defaulting to `STANDARD`, an optional `tip_cents` (at least 0) defaulting to 0, and the `expected_worker_version` required by the concurrency guard in Section 2.7. The `pay_period_id` must be the worker employer's current non-disbursed period. On creation the advance takes its `employer_id` from the worker, stamps `requested_at` with the server clock, sets `status` to `REQUESTED`, and increments the target worker's `version` by one. The advance also exposes `disbursed_amount_cents`, the cash actually paid to the worker, and several recoup counters described below.

An advance's `status` flows `REQUESTED → APPROVED → DISBURSED → RECOUPING → SETTLED` along the happy path, with `SETTLED`, `DECLINED`, and `WRITTEN_OFF` as terminal states; the branching and write-back paths into and out of `DEFAULTED` are covered in Sections 3.8 and 3.9. A `REQUESTED` advance may instead be declined by a `PayrollOfficer`, moving it `REQUESTED → DECLINED` and setting both `principal_cents` and `principal_outstanding_cents` to 0.

A `PayrollOfficer` approves a requested advance, moving it `REQUESTED → APPROVED`. Approval is gated by a series of preconditions, each with its own rejection. The worker's `employment_status` must be `ACTIVE`, else `ERR_WORKER_NOT_ACTIVE`. The worker's `advance_eligibility` must be `ELIGIBLE`, else `ERR_WORKER_ON_HOLD`. The employer's posture must be `HEALTHY` or `RESTRICTED` and not `FROZEN`, else `ERR_EMPLOYER_FROZEN`. The cooling-off interval must be satisfied — that is, the time elapsed from the worker's most recent disbursed advance's `disbursed_at` to the server clock must be at least the employer's `cooling_off_hours`, or there must be no prior disbursed advance at all — else `ERR_COOLING_OFF_ACTIVE`. The worker's `period_advance_count` must be strictly less than the employer's `per_period_advance_cap_count`, else `ERR_PERIOD_CAP_REACHED`. Finally, after the principal clamp below is applied, the resulting `principal_cents` must be at least the matched tier's `per_advance_floor_cents`, else `ERR_BELOW_FLOOR`.

On a successful approval the system computes the approved `principal_cents` via the clamp described in Section 3.6, then computes `expedite_fee_cents`, `total_fee_cents`, and `recoup_target_cents` via the fee logic in Section 3.7 against the employer's `ACTIVE` fee schedule, and sets `disbursed_amount_cents` equal to `principal_cents` (fees are recouped on top of the payout, never deducted from the worker's cash). If the employer has no `ACTIVE` fee schedule at approval time, both `expedite_fee_cents` and `total_fee_cents` are 0 (the tip contributes nothing) regardless of the requested `disbursement_speed` or `tip_cents`.

### 3.6. The Principal Clamp

The approved `principal_cents` is the requested principal reduced by four ceilings evaluated in a pinned order, where the smallest binding ceiling wins. The first step is to select the worker's tier: among the employer's `ACTIVE` advance limit policies whose `min_tenure_days` is at most the worker's `tenure_days`, choose the policy with the greatest `min_tenure_days` that still satisfies that bound; if two qualifying policies share the same `min_tenure_days`, break the tie by the earlier `created_at`. If no `ACTIVE` policy qualifies, there is no tier, the principal is treated as 0, and approval fails the floor check with `ERR_BELOW_FLOOR`.

With the tier chosen, three ceiling candidates are formed alongside the request. The first candidate is the tier's `per_advance_ceiling_cents`. The second candidate is the tier's `cumulative_period_ceiling_cents` minus the sum of `principal_cents` over this worker's advances in the `APPROVED`, `DISBURSED`, `RECOUPING`, or `DEFAULTED` set for the same period; this cumulative ceiling counts principal only and deliberately excludes fees. The third candidate is the worker's `net_available_earnings_cents`, which already nets committed advances by their full recoup target. The approved `principal_cents` is then the smallest of the requested principal and these three candidates, clamped to a floor of 0 so it is never negative. The floor check against `per_advance_floor_cents` is applied after this clamp as the final approval precondition, not inside the clamp itself.

### 3.7. Advance Fees and the Combined-Fee Cap

Fee pricing combines an expedite component and a voluntary tip, then applies a single cap to their sum. If the `disbursement_speed` is `STANDARD`, the `expedite_fee_cents` is 0. If it is `INSTANT`, the `expedite_fee_cents` is the fee schedule's `expedite_flat_fee_cents` plus the product of `principal_cents` and the schedule's `expedite_pct_fee`, where that percent component is rounded half up to whole cents before being added to the flat component (round-then-sum order).

The tip contributes only when permitted: if the schedule's `tip_allowed` is true the tip is the advance's `tip_cents`, and if tips are not allowed the tip contributes 0. The raw combined fee is the expedite fee plus the contributing tip. The combined fee is then capped at the schedule's `max_total_fee_cents`. When the raw combined fee exceeds the cap, `total_fee_cents` is set to the cap, and the cap is absorbed by trimming the tip portion first while the mandatory expedite fee is never reduced — so the tip is effectively reduced to the cap minus the expedite fee, floored at 0, and if the expedite fee alone already meets or exceeds the cap then `total_fee_cents` equals the cap and the tip contributes nothing. When the raw combined fee is at or below the cap, `total_fee_cents` is simply that raw combined fee. Finally, `recoup_target_cents` is the approved `principal_cents` plus `total_fee_cents` — the total the worker owes back at payday.

### 3.8. Disbursement, the Recoup Batch, and Running Payday

Once an advance is `APPROVED`, a `PayrollOfficer` disburses it, moving it `APPROVED → DISBURSED`. Disbursement requires the employer's `funding_balance_cents` to be at least the advance's `recoup_target_cents`, else `ERR_INSUFFICIENT_FUNDING`, and requires the employer's posture to be `HEALTHY` or `RESTRICTED` rather than `FROZEN`, else `ERR_EMPLOYER_FROZEN`. On success it stamps `disbursed_at` with the server clock — this is the anchor from which cooling-off for the worker's next advance is measured — debits `funding_balance_cents` by `recoup_target_cents` to reserve principal and fee, sets `principal_outstanding_cents` to `recoup_target_cents`, recomputes the worker's `lifetime_advanced_cents` and `period_advance_count` and the employer's `outstanding_principal_cents`, and recomputes the employer's `posture`, which may flip `HEALTHY → RESTRICTED` when the funding pool falls below outstanding exposure.

Recoupment happens through a batch. A `PayrollOfficer` opens a draft batch for a period by naming the `pay_period_id`; the batch takes its `employer_id` from the period and starts in `DRAFT` status. A batch's `status` flows `DRAFT → POSTED → RECONCILED`, with `DRAFT → CANCELLED` available; cancelling a draft batch is a `PayrollOfficer` action that moves it to `CANCELLED`. A batch exposes computed `total_recouped_cents` and `advance_count` totals and records the `posted_by_user_id` of the officer who posted it.

Posting a batch, a `PayrollOfficer` action that moves it `DRAFT → POSTED`, runs the payday recoup waterfall described in Section 3.10 against the period's recoupable advances. Posting carries several preconditions in addition to the global checks: the period must be `LOCKED`, else `ERR_PERIOD_NOT_LOCKED`; the acting user must not be the approver of any advance in the period, else `ERR_SEGREGATION_OF_DUTIES`; no other batch for the period may already be `POSTED` or `RECONCILED`, else `ERR_BATCH_ALREADY_POSTED`; and the post must carry `expected_repaymentbatch_version` matching the batch's current `version`, else `ERR_STALE_VERSION`. On success it creates the `Repayment` rows produced by the waterfall, cascades each touched advance from `DISBURSED → RECOUPING`, further cascades any advance whose outstanding reaches 0 from `RECOUPING → SETTLED` (which credits the funding pool as described below), recomputes `total_recouped_cents` and `advance_count`, sets `posted_by_user_id` to the acting `X-User-ID`, and increments the batch's `version` by one.

Running payday is the period's closing act, a `PayrollOfficer` transition that moves the period `LOCKED → DISBURSED`. It requires exactly one batch for the period to be in `POSTED` status, else `ERR_NO_POSTED_BATCH`, and requires the employer's posture not to be `FROZEN`, else `ERR_EMPLOYER_FROZEN`. On success it stamps `disbursed_at` and then performs a four-hop cascade. First, every advance in the period still in `RECOUPING` with `principal_outstanding_cents` greater than 0 is defaulted, moving `RECOUPING → DEFAULTED`; likewise any advance still in `DISBURSED` with outstanding above 0 at payday moves `DISBURSED → DEFAULTED`. Second, each newly defaulted advance sets its worker's `advance_eligibility` to `ON_HOLD`. Third, the period's reconciliation statement is recomputed (creating a `DRAFT` statement if none exists) so its `drift_cents` reflects the new defaults. Fourth, if the recomputed statement's `outcome` is `DISCREPANCY`, the employer's `posture` is recomputed to `FROZEN`. Running payday also moves the period's `POSTED` batch `POSTED → RECONCILED`.

### 3.9. Settlement, Default Recovery, and Write-Off

An advance reaches settlement when repayment drives its `principal_outstanding_cents` to 0. This is a system transition, `RECOUPING → SETTLED`, gated on outstanding reaching exactly 0. On settlement the employer's `funding_balance_cents` is credited by the advance's `recoup_target_cents` — closing the conservation loop opened at disbursement — and the employer's `outstanding_principal_cents` and `posture` are recomputed, with the posture possibly flipping `RESTRICTED → HEALTHY`. Settlement also re-evaluates the worker's `advance_eligibility`: if the worker now has zero advances in the `DEFAULTED` or `WRITTEN_OFF` set, the hold clears back to `ELIGIBLE`, so a fully recovered default releases the worker.

A defaulted advance can be recovered manually. A `PayrollOfficer` performs a manual recovery on a `DEFAULTED` advance, moving it `DEFAULTED → RECOUPING`, by supplying an `amount_cents`. That amount must be greater than 0 and at most the advance's `principal_outstanding_cents`, else `ERR_OVER_RECOUP`. The employer's posture must not be `FROZEN`, unless this very recovery is the one that will clear the period's discrepancy, in which case it is permitted; an otherwise-blocked attempt is rejected with `ERR_EMPLOYER_FROZEN`. A successful recovery creates a `Repayment` row tied to the period's posted-or-prior batch, adds the amount to `amount_recouped_cents`, subtracts it from `principal_outstanding_cents`, and recomputes the period's statement `drift_cents` to reflect the write-back. If outstanding reaches 0, the advance proceeds on through the settlement path described above.

Unrecoverable debt is written off by a `ComplianceOfficer`, moving a `DEFAULTED` advance `DEFAULTED → WRITTEN_OFF`. Write-off requires the advance's `principal_outstanding_cents` to be greater than 0, else `ERR_NOTHING_TO_WRITE_OFF`, and requires the period to have been disbursed, else `ERR_PERIOD_NOT_DISBURSED`. On success the written-off amount equals the current `principal_outstanding_cents`, which is then set to 0; the worker's `advance_eligibility` stays `ON_HOLD` because `WRITTEN_OFF` remains in the penalty set and the debt was never repaid; the period's statement `written_off_cents` and `drift_cents` are recomputed (a write-off counts as resolution rather than cash recovered); and the employer's `outstanding_principal_cents` decreases by the written-off amount.

### 3.10. The Payday Recoup Waterfall

Posting a batch runs a chronological waterfall over the period's recoupable advances, protecting each worker's take-home pay. The candidate set is the period's advances in the `DISBURSED` or `RECOUPING` set, processed in ascending `disbursed_at`, breaking ties by the earlier `created_at`.

Before allocating, the system sets a per-worker recoup ceiling that mirrors the access fraction used for advancing: for each distinct worker among the candidates, the ceiling is the floor of that worker's gross accrued for the period multiplied by the employer's `max_advance_pct_of_available`, and a running total of what has already been recouped for that worker this batch starts at 0. The employer may recoup at most that fraction of gross; the rest is the worker's protected take-home.

The waterfall then processes each candidate advance in order. The room available for that advance is its worker's ceiling minus what has already been recouped for that worker this batch, floored at 0. The amount owed on the advance is its `recoup_target_cents` minus its `amount_recouped_cents`. The amount taken is the smaller of the owed amount and the available room. That taken amount is split fee-before-principal: the fee owed is the advance's `total_fee_cents` minus fees already recouped on it, the fee slice is the smaller of the taken amount and the fee owed, and the principal slice is whatever of the taken amount remains. A `Repayment` row is created for any positive fee slice with `applied_to` set to `FEE`, and a separate row for any positive principal slice with `applied_to` set to `PRINCIPAL`. Each `Repayment` names the `advance_id` and `repayment_batch_id` it belongs to and records the `amount_cents` applied. The advance's `amount_recouped_cents` increases by the taken amount and the worker's running total increases likewise. An advance whose first repayment is applied transitions `DISBURSED → RECOUPING`; one whose outstanding is driven to 0 then transitions on to `SETTLED`. Any advance left with `principal_outstanding_cents` above 0 after the batch remains `RECOUPING` (or `DISBURSED` if nothing was taken) until run-payday defaults it. Note the deliberate asymmetry between this fee-first recoup order and the available-earnings netting of Section 3.4, which nets the whole recoup target rather than splitting it: the two algorithms treat the same advance differently by design.

### 3.11. Reconciliation and Signing

A pay period's books are closed by a reconciliation statement, which a `PayrollOfficer` or `ComplianceOfficer` can create or recompute by naming the `pay_period_id`; the statement takes its `employer_id` from the period and starts in `DRAFT` status. Creating a statement when one already exists recomputes it in place — the operation is idempotent on an unsigned statement and never produces a second statement for the period. A statement's `status` flows `DRAFT → SIGNED`, with `DRAFT` recomputable in place.

The statement computes four aggregates and an outcome. Its `expected_recoup_cents` is the sum of `recoup_target_cents` over the period's advances whose status reached disbursement or beyond — that is, advances in the `DISBURSED`, `RECOUPING`, `DEFAULTED`, `SETTLED`, or `WRITTEN_OFF` set. Its `actual_recouped_cents` is the sum of `total_recouped_cents` over the period's repayment batches in `POSTED` or `RECONCILED` status. Its `written_off_cents` is the sum, over this period's advances that reached `WRITTEN_OFF`, of the outstanding amount captured at write-off. Its `drift_cents` is `expected_recoup_cents` minus `actual_recouped_cents` minus `written_off_cents`; the conservation invariant requires this to be 0 for clean books. The `outcome` is `CLEAN` when `drift_cents` is 0 and `DISCREPANCY` otherwise. Note that a write-off subtracts from expected (it counts as resolved), so writing off a stuck balance can move an `outcome` from `DISCREPANCY` to `CLEAN` even though no cash was recovered — distinct from a manual recovery, which instead increases actual recouped. This recomputation is triggered whenever a batch posts, payday runs, a manual recovery applies, a write-off applies, or the statement is explicitly recomputed.

Signing a statement is a `ComplianceOfficer` action that moves it `DRAFT → SIGNED`. Signing requires the period to be `DISBURSED`, else `ERR_PERIOD_NOT_DISBURSED`; requires segregation of duties — the signer must not be the poster of the period's batch and must not be the approver of any advance in the period, else `ERR_SEGREGATION_OF_DUTIES`; and requires the statement's `outcome` to be `CLEAN`, equivalently `drift_cents` equal to 0, else `ERR_STATEMENT_NOT_CLEAN`. On success the statement records `signed_by_user_id` as the acting `X-User-ID` and recomputes the employer's `posture`, which a clean signed statement can lift out of `FROZEN` back toward `HEALTHY` or `RESTRICTED` when no other discrepancy remains.

### 3.12. The Test Clock

Because tenure, cooling-off, and payday all depend on elapsed time, a `PlatformAdmin` may pin the server clock for deterministic testing by supplying a `to_iso8601` instant. Once set, that instant governs all subsequently server-stamped fields and every elapsed-time check until it is changed again.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and funding top-ups — return a `200 OK` status code. The reconciliation-statement create endpoint returns `200 OK` because it creates or recomputes in place rather than minting a fresh resource each call. Request bodies, response bodies, and side effects for each endpoint are described in Section 3; this table lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employers` | Create an employer | `PlatformAdmin` |
| GET | `/employers/{employerId}` | Fetch an employer with computed posture and exposure | `PlatformAdmin`, `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/employers` | List employers | `PlatformAdmin` |
| POST | `/employers/{employerId}/funding-deposits` | Top up the employer funding pool | `PlatformAdmin` |
| POST | `/advance-policies` | Define a tier's advance limit policy | `PlatformAdmin` |
| GET | `/advance-policies/{policyId}` | Fetch an advance limit policy | `PlatformAdmin`, `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/advance-policies` | List advance limit policies | `PlatformAdmin`, `PayrollOfficer`, `ComplianceOfficer` |
| POST | `/fee-schedules` | Define the employer fee schedule | `PlatformAdmin` |
| GET | `/fee-schedules/{feeScheduleId}` | Fetch a fee schedule | `PlatformAdmin`, `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/fee-schedules` | List fee schedules | `PlatformAdmin`, `PayrollOfficer`, `ComplianceOfficer` |
| POST | `/pay-periods` | Open a new pay period | `PayrollOfficer` |
| GET | `/pay-periods/{payPeriodId}` | Fetch a pay period | `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/pay-periods` | List pay periods | `PayrollOfficer`, `ComplianceOfficer` |
| POST | `/pay-periods/{payPeriodId}/lock` | Lock the time feed | `PayrollOfficer` |
| POST | `/pay-periods/{payPeriodId}/reopen` | Reopen for corrections | `PayrollOfficer` |
| POST | `/pay-periods/{payPeriodId}/run-payday` | Close the period and run payday | `PayrollOfficer` |
| POST | `/workers` | Register a worker | `PayrollOfficer` |
| GET | `/workers/{workerId}` | Fetch a worker with computed tenure and counters | `PayrollOfficer`, `ComplianceOfficer`, `Worker` |
| GET | `/workers` | List workers | `PayrollOfficer`, `ComplianceOfficer` |
| POST | `/workers/{workerId}/suspend` | Suspend a worker | `PayrollOfficer` |
| POST | `/workers/{workerId}/reinstate` | Reinstate a worker | `PayrollOfficer` |
| POST | `/workers/{workerId}/terminate` | Terminate a worker | `PayrollOfficer` |
| POST | `/time-entries` | Post a time entry into a period's feed | `PayrollOfficer` |
| GET | `/time-entries/{timeEntryId}` | Fetch a time entry | `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/time-entries` | List time entries | `PayrollOfficer`, `ComplianceOfficer` |
| POST | `/time-entries/{timeEntryId}/void` | Void a posted time entry | `PayrollOfficer` |
| POST | `/advances` | Request an advance | `Worker`, `PayrollOfficer` |
| GET | `/advances/{advanceId}` | Fetch an advance | `Worker`, `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/advances` | List advances | `PayrollOfficer`, `ComplianceOfficer`, `Worker` |
| POST | `/advances/{advanceId}/approve` | Approve and price an advance | `PayrollOfficer` |
| POST | `/advances/{advanceId}/decline` | Decline a requested advance | `PayrollOfficer` |
| POST | `/advances/{advanceId}/disburse` | Disburse cash to the worker | `PayrollOfficer` |
| POST | `/advances/{advanceId}/manual-recoup` | Manually recover from a defaulted advance | `PayrollOfficer` |
| POST | `/advances/{advanceId}/write-off` | Write off an unrecoverable advance | `ComplianceOfficer` |
| POST | `/repayment-batches` | Open a draft recoup batch for a period | `PayrollOfficer` |
| GET | `/repayment-batches/{batchId}` | Fetch a batch with computed totals | `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/repayment-batches` | List repayment batches | `PayrollOfficer`, `ComplianceOfficer` |
| POST | `/repayment-batches/{batchId}/post` | Post the batch and run the recoup waterfall | `PayrollOfficer` |
| POST | `/repayment-batches/{batchId}/cancel` | Cancel a draft batch | `PayrollOfficer` |
| GET | `/repayments/{repaymentId}` | Fetch a single repayment row | `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/repayments` | List repayment rows | `PayrollOfficer`, `ComplianceOfficer`, `Worker` |
| POST | `/reconciliation-statements` | Create or recompute a period's statement | `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/reconciliation-statements/{statementId}` | Fetch a reconciliation statement | `PayrollOfficer`, `ComplianceOfficer` |
| GET | `/reconciliation-statements` | List reconciliation statements | `PayrollOfficer`, `ComplianceOfficer` |
| POST | `/reconciliation-statements/{statementId}/sign` | Sign a clean statement | `ComplianceOfficer` |
| POST | `/_clock/set_current_utc` | Set the server clock for deterministic tests | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CROSS_EMPLOYER_REFERENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_EMPLOYER_FROZEN` | 409 Conflict |
| `ERR_WORKER_NOT_ACTIVE` | 409 Conflict |
| `ERR_WORKER_ON_HOLD` | 409 Conflict |
| `ERR_COOLING_OFF_ACTIVE` | 409 Conflict |
| `ERR_PERIOD_CAP_REACHED` | 409 Conflict |
| `ERR_TIME_ENTRY_OUT_OF_WINDOW` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_OVER_RECOUP` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUNDING` | 402 Payment Required |
| `ERR_DUPLICATE_PAYROLL_REF` | 409 Conflict |
| `ERR_BATCH_ALREADY_POSTED` | 409 Conflict |
| `ERR_NO_POSTED_BATCH` | 409 Conflict |
| `ERR_PERIOD_NOT_LOCKED` | 409 Conflict |
| `ERR_PERIOD_HAS_POSTED_BATCH` | 409 Conflict |
| `ERR_PERIOD_NOT_DISBURSED` | 409 Conflict |
| `ERR_NOTHING_TO_WRITE_OFF` | 409 Conflict |
| `ERR_WORKER_HAS_OPEN_ADVANCE` | 409 Conflict |
| `ERR_STATEMENT_NOT_CLEAN` | 409 Conflict |

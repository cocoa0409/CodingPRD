# Defined Benefit Actuarial Valuation API — Product Requirements Document

## 1. Introduction

For a pension actuarial firm, the annual defined-benefit valuation is a regulated ritual: collect the sponsor's participant census, fix the actuarial assumptions, measure liabilities and normal cost, and translate those measurements into minimum funding obligations, PBGC premium filings, and financial-statement disclosures. Each stage carries statutory consequences. Assumptions must be approved by an enrolled actuary who did not prepare them; a certified funding percentage drives statutory benefit restrictions that can freeze accruals outright; missed contribution deadlines accrue excise tax; and a premium filing built on a superseded valuation run must be amended or voided. Small mechanical errors — a census row whose attained age falls outside the mortality table's domain, a liability rounded after aggregation rather than before — propagate silently into filings that are expensive to unwind.

This document specifies an API that operationalizes that end-to-end cycle for a single plan year. It governs census batch upload and row screening, assumption-set preparation and dual-control review, asset roll-forward and smoothing under a corridor, per-participant liability measurement, run certification with its downstream cascades into funding demands and benefit-restriction posture, credit-balance elections and revocation, PBGC premium computation and filing, and disclosure reporting with auditor acknowledgment. Every rule stated here is normative; the narratives of Section 3 deliberately distribute related rules across the workflows they guard, and Section 4 consolidates only the HTTP contract.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Five roles are recognized: `FirmAdmin`, `PlanAdmin`, `Actuary`, `SeniorActuary`, and `Auditor`. A request missing either header, or presenting an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A recognized role attempting an operation outside its grant is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Actuary` or `SeniorActuary`, `X-User-ID` is the `id` of the acting `Actuary` record; ownership and segregation-of-duties checks compare it against fields such as `prepared_by_actuary_id` on an assumption set or `created_by_actuary_id` on a valuation run, and the server stamps it into `approved_by_actuary_id`, `certified_by_actuary_id`, or `created_by_actuary_id` where a transition records the actor. When `X-User-Role` is `FirmAdmin`, `PlanAdmin`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `acknowledged_by` on a disclosure report — but never compares it to an entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — plans, actuaries, census batches, participants, assumption sets, asset statements, asset valuations, valuation runs, participant accrual rows, the credit-balance ledger, credit-balance elections, contribution demands, PBGC filings, and disclosure reports — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including server-initiated mutations such as cascade side effects.

The contribution payment is the single exception: it carries only `id` and `created_at`. Because a posted payment is an immutable event, both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock and Calendar-Pinned Dates

All deadline, window, presumption, and delinquency logic in the system reads a server-side logical clock — never wall-clock time. A `FirmAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the new reading as `current_utc`. At server startup, before any set call, the logical clock reads exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time. Advancing the clock re-evaluates contribution-demand delinquency: any demand in `OPEN` or `PARTIALLY_SATISFIED` whose outstanding amount remains positive once the clock has moved strictly past its due date transitions to `DELINQUENT` and accrues the excise described in §3.7.

Four calendar anchors recur throughout the specification, all at midnight UTC: the valuation date is January 1 of the plan year; the presumed-AFTAP cutoffs are April 1 and October 1 of the plan year; the minimum-funding due date is September 15 of the plan year; and the PBGC filing deadline is October 15 of the plan year.

### 2.6. Precision and Rounding Conventions

All monetary amounts and all percentages are computed and stored at 2 decimal places using round-half-up. The annuity factor is the sole exception: it is rounded half-up to 4 decimal places, and it is always rounded before being multiplied by any benefit or compensation amount. Per-participant liability and normal-cost values are each rounded to cents individually before any aggregation, and aggregations then sum the already-rounded values exactly — summing unrounded values and rounding once at the end is non-conformant. Monetary values appear in API responses as JSON numbers, not strings.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to present the plan version it last observed, so that a client acting on a stale plan snapshot cannot overwrite state it has not seen. Certifying a valuation run requires the request to carry `expected_plan_version` equal to the plan's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a credit-balance election likewise requires `expected_plan_version` matching the plan's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field. The plan's `version` increments by one on plan termination, on run certification, and on election creation, in addition to any other mutation of the plan itself.

### 2.8. Validation Order and Nested Resource Resolution

Requests that target nested resources are resolved left to right along the path — plan first, then the child, then the grandchild — and the first identifier that does not correspond to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404); the system does not evaluate later path segments or any business rule once a path segment has failed.

Beyond existence, checks execute in a fixed priority order so that a request failing several rules always reports the same error. Authentication of the headers comes first, then role authorization, then left-to-right path existence, then the generic from-state validity of the target entity — rejected as `ERR_INVALID_STATE` (HTTP 409) when, for example, a payment is posted to an already `SATISFIED` demand, an already `COMPUTED` run is computed again, or a `DRAFT` assumption set is approved. Next comes the plan-active gate: any child-creating or transition operation under a `TERMINATED` plan is rejected with `ERR_PLAN_TERMINATED` (HTTP 409). Business rules follow in this exact sequence: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) before actuary enrollment (`ERR_ACTUARY_NOT_ENROLLED`); then the temporal rules — the PBGC filing deadline (`ERR_FILING_DEADLINE_PASSED`), the election revocation window (`ERR_REVOCATION_WINDOW_EXPIRED`), and the election-window conflict (`ERR_ELECTION_WINDOW_CONFLICT`); then referential alignment — plan-year matching (`ERR_PLAN_YEAR_MISMATCH`), assumption consistency (`ERR_ASSUMPTION_MISMATCH`), locked references (`ERR_REFERENCE_NOT_LOCKED`), and certified-run references (`ERR_VALUATION_RUN_NOT_CERTIFIED`); then the conflict rules — census year (`ERR_CENSUS_YEAR_CONFLICT`), assumption year (`ERR_ASSUMPTION_YEAR_CONFLICT`), and general uniqueness (`ERR_UNIQUENESS_VIOLATION`); then participant row data (`ERR_INVALID_PARTICIPANT_DATA`); then the amendment delta (`ERR_NO_AMENDMENT_DELTA`); and finally the fiscal limits (`ERR_CREDIT_BALANCE_EXCEEDED`, `ERR_OVERPAYMENT`). Request-body well-formedness — required fields present, values well-typed, enum members valid, amounts positive where required — is the lowest-priority check of all, surfaced as `ERR_VALIDATION` (HTTP 400) only when no earlier rule has fired.

### 2.9. Segregation of Duties and Enrollment Credentialing

The firm separates preparation from approval at two points. An assumption set may be approved only by an actuary whose id differs from the set's `prepared_by_actuary_id`, and a valuation run may be certified only by an actuary whose id differs from the run's `created_by_actuary_id`; either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). In addition, approving an assumption set, locking an assumption set, and certifying a valuation run each require the acting actuary's `enrollment_status` to be `ENROLLED`; an `ASSOCIATE` attempting any of the three is rejected with `ERR_ACTUARY_NOT_ENROLLED` (HTTP 422). Consistent with §2.8, when both rules could fault the same request, the segregation-of-duties failure is reported before the enrollment failure.

## 3. Business Logic & Workflows

### 3.1. Plan Onboarding, Credit Balances, and Termination

A `PlanAdmin` registers a defined-benefit plan by supplying the sponsor's legal name as `sponsor_name`, the calendar `plan_year`, the benefit `accrual_rate` as a fraction of annual compensation per year of service (greater than zero and at most 0.10), the plan's `normal_retirement_age` (at least 60 and at most 63, matching the age domain of the pinned mortality table), and the sponsor-reported `prior_aftap_pct` for the prior plan year (between 0.00 and 200.00 inclusive). Two optional opening balances, `initial_carryover_balance` and `initial_prefunding_balance`, each default to zero when omitted. Every measurement under the plan is pinned to a valuation date of January 1 of the plan year.

Plan creation automatically creates the plan's credit-balance ledger, a one-to-one sub-resource seeded with `carryover_balance` equal to `initial_carryover_balance`, `prefunding_balance` equal to `initial_prefunding_balance`, and `total_applied_to_date` of zero. Reading the plan's credit-balance ledger returns an array containing at most one entry. Every plan-scoped child resource — census batches, assumption sets, asset statements, asset valuations, valuation runs, elections, demands, filings, and reports — records its owner as `plan_id`, supplied through the path rather than the body.

A new plan begins with `status` `ACTIVE` and `current_posture` `UNRESTRICTED`. While no certified run governs the plan, `certified_aftap_pct` reads null and the plan's posture derives from the presumed percentage described in §3.6; once a certified run exists, `presumed_aftap_pct` reads null and the certified percentage governs. The plan listing supports pagination and an optional `status` filter, and fetching a single plan returns its computed posture together with the certified and presumed percentages.

Terminating a plan — `ACTIVE` → `TERMINATED`, the terminal state — is a `PlanAdmin` action permitted only while no contribution demand of the plan carries a positive `outstanding_amount`; termination is refused while any demand remains outstanding. Termination increments the plan's `version` by one and transitions every `DRAFT` PBGC filing of the plan to `VOID`. Census batches not yet `LOCKED` are left unchanged, but the plan is closed to further work: any mutation scoped to a `TERMINATED` plan, including creating new valuation runs, is rejected with `ERR_PLAN_TERMINATED`.

### 3.2. Census Collection and Participant Screening

Census data arrives in batches. A `PlanAdmin` creates a census batch under a plan, supplying a `plan_year` that must equal the owning plan's year — a mismatch is rejected with `ERR_PLAN_YEAR_MISMATCH` (HTTP 422) — and a free-form `source_label` identifying the data extract. The batch begins `UPLOADED`, with `participant_count` and `error_count` at zero and `screening_errors` empty.

Participant rows are bulk-appended to a batch in `UPLOADED` or `NEEDS_CORRECTION` status through a payload whose `participants` array carries one object per row; posting to a batch in any other status fails the generic state gate with `ERR_INVALID_STATE`. Each row names its batch through the path, recorded as `census_batch_id`, and carries the sponsor's employee identifier `external_ref` — unique within the batch, with duplicates rejected as `ERR_UNIQUENESS_VIOLATION` (HTTP 409) — plus `date_of_birth` as an ISO date, a `status` of `ACTIVE`, `TERMINATED_VESTED`, or `RETIREE`, and the status-appropriate benefit fields. For an `ACTIVE` participant, `years_of_service` (credited service at the valuation date) and `annual_compensation` (current annualized compensation) are required; service is ignored for the other two statuses. For a `TERMINATED_VESTED` participant, `deferred_benefit_annual` — the accrued annual benefit deferred to normal retirement age — is required. For a `RETIREE`, `current_annual_benefit` — the annual benefit already in pay status — is required. Service and amount fields must all be non-negative. A row's attained age is the plan year minus the birth year, with month and day ignored, and it must fall within the pinned mortality domain of 60 through 63 inclusive.

Row-level defects — an attained age outside 60 through 63, a negative amount, or a missing status-appropriate benefit field — are `ERR_INVALID_PARTICIPANT_DATA` (HTTP 422) conditions. The upload endpoint is deliberately tolerant: per-row validation errors are collected rather than aborting the request, valid rows are still written, and the response is 200 OK. Whenever rows are posted to a `NEEDS_CORRECTION` batch, the batch returns to `UPLOADED` — the revision loop — with `participant_count` recomputed and `screening_errors` cleared to an empty array; newly appended rows simply extend the batch.

Screening is the gate between raw upload and valuation use. Submitting an `UPLOADED` batch for screening re-checks every row and requires `participant_count` greater than zero; screening an empty batch is itself an `ERR_INVALID_PARTICIPANT_DATA` rejection. When screening finds zero row errors, the batch transitions `UPLOADED` → `VALIDATED`, `error_count` is set to 0, and `screening_errors` is emptied. When screening finds one or more row errors, the batch transitions `UPLOADED` → `NEEDS_CORRECTION` with `error_count` and `screening_errors` populated from the row screening. A validating screening is additionally refused when another census batch of the same plan is already `VALIDATED` or `LOCKED` for the same plan year — calendar-year containment is absolute, while adjacent plan years are always permitted — surfacing `ERR_CENSUS_YEAR_CONFLICT` (HTTP 409).

Locking moves a `VALIDATED` batch to `LOCKED`, its terminal state, making it immutable reference data for valuation runs. Locking is refused with `ERR_CENSUS_YEAR_CONFLICT` when another batch of the same plan is already `LOCKED` for the same plan year.

### 3.3. Actuarial Assumptions and the Review Loop

The firm maintains an actuary registry, administered by `FirmAdmin`, recording each actuary's `full_name`, professional `credential_id`, and `enrollment_status` — `ENROLLED` for an enrolled actuary authorized to certify, `ASSOCIATE` otherwise. This registry backs the `Actuary` and `SeniorActuary` role identities described in §2.1.

Against that registry, an `Actuary` or `SeniorActuary` drafts an assumption set for a plan, supplying `plan_year` (equal to the owning plan's year, else `ERR_PLAN_YEAR_MISMATCH`), a human-readable `label`, the pinned `mortality_table`, a `funding_discount_rate` for funding liabilities, a `disclosure_discount_rate` for financial-statement obligations — each rate greater than zero and at most 0.20 — and a `retirement_age`. Two assumption constraints are enforced at creation, both rejected as `ERR_ASSUMPTION_MISMATCH` (HTTP 422): the mortality table must be exactly `TEST_TABLE_4AGE` (no other table is supported), and the retirement age must equal the plan's `normal_retirement_age`. The server stamps `prepared_by_actuary_id` from the caller's `X-User-ID`; the set begins `DRAFT` with `approved_by_actuary_id` null.

Submitting moves a `DRAFT` set to `IN_REVIEW`. From `IN_REVIEW`, a `SeniorActuary` either approves or rejects. Approval requires the acting actuary to be `ENROLLED` and to differ from `prepared_by_actuary_id`, per §2.9; it stamps `approved_by_actuary_id` with the acting actuary's id and lands the set in `APPROVED`. Rejection returns the set `IN_REVIEW` → `DRAFT` for revision, and the submit-review loop may repeat as often as needed.

An `APPROVED` set may be locked by a `SeniorActuary` — who, like an approver, must be `ENROLLED` — moving it `APPROVED` → `LOCKED` and making it eligible as a valuation-run reference. Only one assumption set per plan may be `LOCKED` for a given plan year; a conflicting lock is rejected with `ERR_ASSUMPTION_YEAR_CONFLICT` (HTTP 409). Alternatively, an `APPROVED` set may be reopened, returning it `APPROVED` → `DRAFT` and clearing `approved_by_actuary_id` to null — but reopening is forbidden while any valuation run in `INITIATED`, `COMPUTED`, or `CERTIFIED` references the set, and such an attempt is rejected with `ERR_UNIQUENESS_VIOLATION`. Finally, a `DRAFT` set may be retired by either actuary role; `RETIRED` is terminal.

### 3.4. Asset Roll-Forward and the Smoothing Corridor

A `PlanAdmin` records the plan-year asset statement with `market_value_begin` (the fair market value of plan assets at January 1 of the plan year), `contributions_received`, `benefits_paid`, and the net `investment_return` for the year, which may be negative; the first three amounts must be non-negative. The statement's `plan_year` must equal the plan's year (`ERR_PLAN_YEAR_MISMATCH`), and only one asset statement may exist per plan and plan year — a duplicate is rejected with `ERR_UNIQUENESS_VIOLATION`. The server computes `market_value_end` by the roll-forward invariant: beginning market value, plus contributions received, minus benefits paid, plus investment return.

From that statement, an `Actuary` or `SeniorActuary` computes the plan-year asset valuation, again with `plan_year` equal to the plan's year. The actuarial value smooths the current-year gain or loss. The expected return is five percent of `market_value_begin`, rounded half-up to cents. The gain is `investment_return` minus that expected return. One-third of the gain is recognized immediately, so `unrecognized_gain` — the deferred portion — is two-thirds of the gain, rounded half-up to cents. The pre-corridor smoothed value is `market_value_end` minus `unrecognized_gain`. A corridor then clamps it: `corridor_floor` is eighty percent of `market_value_end` and `corridor_ceiling` is one hundred twenty percent of it, each rounded half-up to cents. The resulting `smoothed_value` is the pre-corridor value raised to the floor when it falls below the floor, lowered to the ceiling when it exceeds the ceiling, and unchanged when it lies within the corridor; `corridor_applied` records `FLOOR`, `CEILING`, or `NONE` accordingly. The valuation also carries `market_value`, taken unsmoothed from the statement's `market_value_end`.

Two variants of the same valuation serve different purposes, sharing identical inputs. Funding contexts — the certified AFTAP and the minimum and maximum contribution calculations of §3.6 and §3.7 — use the corridor-clamped `smoothed_value`. PBGC premium and financial-statement disclosure contexts use the unsmoothed `market_value`. The outputs differ whenever the unrecognized gain is nonzero or a corridor bound clamps. Asset statements and asset valuations are both `FINAL` upon creation: neither has a lifecycle state machine or any later transition.

### 3.5. Valuation Runs: Annuity Factors, Accruals, and Aggregation

With a locked census, locked assumptions, and an asset valuation in hand, an `Actuary` or `SeniorActuary` initiates a valuation run by supplying `plan_year`, `census_batch_id`, `assumption_set_id`, and `asset_valuation_id`. The run's `plan_year` must equal the plan's year, and every referenced resource must belong to the same plan and the matching plan year; violations are rejected with `ERR_PLAN_YEAR_MISMATCH`. The run begins `INITIATED`, with `created_by_actuary_id` stamped from `X-User-ID` and `aftap_pct` null until certification.

Computing the run (`INITIATED` → `COMPUTED`) is gated on the references being final: the referenced census batch must be `LOCKED`, the referenced assumption set must be `LOCKED`, and the referenced asset valuation must exist and belong to the same plan — any failure is rejected with `ERR_REFERENCE_NOT_LOCKED` (HTTP 422). Computation creates one `ParticipantAccrual` row per participant of the referenced census batch, across all participant statuses. Each row records `valuation_run_id` and `participant_id`, the `age_at_valuation` (attained age: plan year minus birth year), the `annuity_factor`, the `accrued_liability`, the `normal_cost_share`, and a `frozen` flag that starts false.

The annuity factor rests on the pinned mortality table `TEST_TABLE_4AGE`: decrement rates of 0.20 at age 60, 0.25 at age 61, 0.50 at age 62, and 1.00 at age 63, with age 63 as the terminal age. The probability of surviving a whole number of years from a given age is the product, over each whole-year offset from zero up to but not including the span, of one minus the decrement rate at the age plus that offset. The one-year discount factor is the reciprocal of one plus the applicable discount rate — the set's `funding_discount_rate` for funding measurements, or its `disclosure_discount_rate` for the disclosure revaluation of §3.9. The immediate annuity factor at an age is the sum, over each whole number of years from zero through the terminal age minus that age, of the discount factor raised to that many years multiplied by the survival probability over the same span. A participant whose attained age has reached the assumed retirement age uses the immediate factor at attained age directly; a younger participant's deferred factor is the discount factor raised to the number of years remaining until retirement age, multiplied by the probability of surviving those years, multiplied by the immediate factor at the retirement age. Every factor is rounded half-up to four decimal places before any benefit multiplication. Calibration anchors for implementers: at a five-percent discount rate the immediate factor at age 62 is 1.4762, at age 63 exactly 1.0000, and at age 60 is 2.5653, while the deferred factor to retirement age 62 is 0.8034 from age 60 and 1.0544 from age 61; at a four-percent discount rate the immediate factor at 62 is 1.4808, the deferred factor from 60 to 62 is 0.8214, and the factor at 63 remains 1.0000.

Each accrual row's amounts follow the participant's status. For an `ACTIVE` participant, `accrued_liability` is the plan's `accrual_rate` multiplied by the participant's `years_of_service`, by `annual_compensation`, and by the annuity factor, rounded half-up to cents; `normal_cost_share` is the same product with a single year of service in place of total service — accrual rate times one year times annual compensation times the factor — again rounded half-up to cents. For a `TERMINATED_VESTED` participant, `accrued_liability` is `deferred_benefit_annual` multiplied by the annuity factor, rounded to cents, and the normal-cost share is 0.00. For a `RETIREE`, `accrued_liability` is `current_annual_benefit` multiplied by the immediate factor at attained age, rounded to cents, with a normal-cost share of 0.00. Normal cost accrues only from `ACTIVE` participants.

Aggregation follows a pinned rounding order: the run's `funding_target` is the exact sum of the per-participant cent-rounded `accrued_liability` values, and `normal_cost` is the exact sum of the cent-rounded `normal_cost_share` values. Rounding each participant first and only then summing is mandatory — summing unrounded values and rounding once at the end produces different cents and is non-conformant.

A run still in `INITIATED` or `COMPUTED` may be voided by either actuary role. Voiding from `INITIATED` has no further effect; voiding from `COMPUTED` retains the run's accrual rows for audit but excludes them from all aggregations. `SUPERSEDED` and `VOID` are the terminal states of a run.

### 3.6. Certification, AFTAP, and the Benefit-Restriction Posture

Certification — `COMPUTED` → `CERTIFIED` — is reserved for a `SeniorActuary` whose `enrollment_status` is `ENROLLED` and whose id differs from the run's `created_by_actuary_id` (§2.9). The request must also carry `expected_plan_version` matching the plan's current `version` per §2.7; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the certifier to re-observe the plan before certifying.

At certification the run's `aftap_pct` is computed as one hundred times the quantity of `smoothed_value` minus the sum of `carryover_balance` and `prefunding_balance`, divided by `funding_target`, rounded half-up to two decimal places, and `certified_by_actuary_id` is stamped with the acting actuary's id.

Certification then fires a multi-hop cascade. The plan's `version` increments by one. Any previously `CERTIFIED` valuation run of the same plan transitions to `SUPERSEDED`. The plan's `certified_aftap_pct` is updated to the newly certified value, and `current_posture` is recomputed from the governing percentage: `UNRESTRICTED` at or above 80.00 percent, `LUMP_SUM_RESTRICTED` at or above 60.00 but below 80.00, and `ACCRUAL_FROZEN` below 60.00 — with the boundaries pinned so that exactly 80.00 is `UNRESTRICTED` and exactly 60.00 is `LUMP_SUM_RESTRICTED`. The second hop propagates the posture onto the run's rows: if the new posture is `ACCRUAL_FROZEN`, every participant accrual row of the certifying run is flagged `frozen` true; if the posture is anything else, the frozen flags of that run's rows are cleared. The third hop creates the plan's `ContributionDemand` for the plan year on first certification, or recomputes it on later certifications, with the freeze state zeroing — or, on unfreezing, restoring — the normal-cost component of `tentative_minimum` as detailed in §3.7. The fourth hop lets the recomputed `outstanding_amount` drive the demand's automatic transitions among `OPEN`, `PARTIALLY_SATISFIED`, and `SATISFIED`. Finally, every `DRAFT` or `AMENDED` PBGC filing of the plan transitions to `VOID`, because its premium basis is now stale.

When no certified run exists for the plan, a presumed AFTAP governs instead, read from `prior_aftap_pct` and the logical clock. Once the clock reaches October 1 of the plan year, the plan is deemed to be under 60 percent funded and its posture is `ACCRUAL_FROZEN`. Before that, once the clock reaches April 1 of the plan year, `presumed_aftap_pct` is `prior_aftap_pct` reduced by 10.00 percentage points. Before April 1, `presumed_aftap_pct` equals `prior_aftap_pct` and the plan is presumed adequate, with posture `UNRESTRICTED`. While a certified run governs, `presumed_aftap_pct` reads null; while none does, `certified_aftap_pct` reads null.

### 3.7. Contribution Demands, Payments, and Delinquency

A contribution demand is never created directly: it appears when a run is first certified for the plan year and is recomputed on every later certification, on every credit-balance election applied to it, and on every revocation. The demand records the driving `valuation_run_id` and its `plan_year`, and its computation order is pinned, because the credit cap depends on the tentative minimum. First, `funding_target` and `normal_cost` come from the certified run — with the normal-cost component treated as zero when the plan's posture froze that run's accruals. Second, the shortfall is `funding_target` minus the asset valuation's `smoothed_value`, floored at zero. Third, the shortfall amortization installment is one-seventh of the shortfall, rounded half-up to cents, or 0.00 when there is no shortfall. Fourth, `tentative_minimum` is the normal-cost component plus the installment. Fifth, `credit_applied` is the total credit pool drawn by `EFFECTIVE` elections in waterfall order, capped at `tentative_minimum`. Sixth, `minimum_due` is `tentative_minimum` minus `credit_applied`. Seventh, `outstanding_amount` is `minimum_due` minus `paid_to_date`. Alongside the minimum, the demand carries `maximum_deductible`: the cushion basis is one and a half times `funding_target`, rounded half-up to cents, plus `normal_cost`, and the maximum deductible is the greater of `tentative_minimum` and the cushion basis minus `smoothed_value`. The demand's `due_date` is September 15 of the plan year at midnight UTC — the minimum-funding deadline.

The demand lifecycle is driven by payments, elections, revocations, and the clock. A demand begins `OPEN`, and it remains `OPEN` only while no payment or election has landed on it — that is, while `credit_applied` and `paid_to_date` are both zero. A payment or election posted against an `OPEN` or `PARTIALLY_SATISFIED` demand that leaves `outstanding_amount` positive moves it to `PARTIALLY_SATISFIED`, recomputing the outstanding amount — this holds even when the positive outstanding amount still equals `minimum_due`, as happens when a credit-balance election is the first activity on the demand; one that leaves the outstanding amount at or below zero moves it straight to `SATISFIED`, and the same zeroing moves a `PARTIALLY_SATISFIED` demand to `SATISFIED`. When the logical clock moves strictly past the due date while `outstanding_amount` remains positive, the system itself moves an `OPEN` or `PARTIALLY_SATISFIED` demand to `DELINQUENT` and assesses `excise_accrued` exactly once at that transition: ten percent of the outstanding amount, rounded half-up to cents. `DELINQUENT` is then sticky while the outstanding amount remains positive — no payment, election, revocation, or recertification returns a delinquent demand to `PARTIALLY_SATISFIED` — and a delinquent demand later paid or offset down to zero moves `DELINQUENT` → `SATISFIED`, but the accrued excise remains due and is never reversed. Conversely, a revocation or recertification that restores a positive outstanding amount pulls a `SATISFIED` demand back to `PARTIALLY_SATISFIED`, never to `OPEN`; for a revocation, the outstanding amount is recomputed by the waterfall's reverse pass.

Cash payments are posted by a `PlanAdmin` against a specific demand as immutable payment events carrying an `amount` and the value date `paid_on` in ISO 8601. The amount must be positive — otherwise `ERR_VALIDATION` — and must not exceed the demand's `outstanding_amount`, with an excess rejected as `ERR_OVERPAYMENT` (HTTP 422). Recall from §2.8 that the generic state gate fires before fiscal checks: posting a payment to an already `SATISFIED` demand is an `ERR_INVALID_STATE` rejection, not an overpayment. Each accepted posting creates the payment record, recomputes `paid_to_date` and `outstanding_amount`, and triggers the auto-transitions above.

### 3.8. Credit-Balance Elections and Revocation

A `PlanAdmin` may offset a demand out of the plan's credit balances by creating a credit-balance election, supplying the `contribution_demand_id` it offsets, the `amount` to apply, and `expected_plan_version` per §2.7 — a stale plan version is rejected with `ERR_STALE_VERSION`. The amount must be positive (`ERR_VALIDATION` otherwise), must not exceed the sum of `carryover_balance` and `prefunding_balance`, and must not exceed the referenced demand's `outstanding_amount`; breaching either ceiling is rejected with `ERR_CREDIT_BALANCE_EXCEEDED` (HTTP 422). One further window rule applies: if another `EFFECTIVE` election on the same demand was created less than twenty-one days ago — that is, its revocation window, running from its creation up to but not including the instant twenty-one days later, is still open — the new election is rejected with `ERR_ELECTION_WINDOW_CONFLICT` (HTTP 409); an earlier election whose window closed at exactly the twenty-one-day mark does not block.

Creation draws the ledger down in waterfall order. The `carryover_balance` absorbs the election first, up to the full amount; the `prefunding_balance` then covers any remainder, up to what remains of it. Each pool is reduced by the amount drawn from it, `total_applied_to_date` increases by the election amount, the plan's `version` increments by one, and the demand's `credit_applied`, `minimum_due`, and `outstanding_amount` are recomputed with the auto-transitions of §3.7. The election is born `EFFECTIVE`, with `revoke_deadline` computed as its `created_at` plus twenty-one days.

Revocation — `EFFECTIVE` → `REVOKED`, terminal — is permitted only while the logical clock is strictly before `revoke_deadline`; at or after that instant the attempt is rejected with `ERR_REVOCATION_WINDOW_EXPIRED` (HTTP 422). Revocation restores the two pools in the same proportions recorded at draw time, reduces `total_applied_to_date` by the election amount, and recomputes the demand — which may pull a `SATISFIED` demand back out of satisfaction when the outstanding amount becomes positive again, compensating the original offset. A conserved quantity guards the ledger: across any create-and-revoke pair, the sum of `carryover_balance`, `prefunding_balance`, and `total_applied_to_date` is invariant, and no operation other than election creation and revocation ever mutates these fields.

### 3.9. PBGC Premiums and Financial-Statement Disclosure

Once a run is certified, a `PlanAdmin` creates a PBGC premium filing from it, supplying the `valuation_run_id` of a certified run and an optional `premium_method` — `STANDARD` when omitted, `ALTERNATIVE` as the other choice. The referenced run must belong to the same plan and matching plan year (`ERR_PLAN_YEAR_MISMATCH`), and must be `CERTIFIED`; filing or disclosure work against an uncertified run is rejected with `ERR_VALUATION_RUN_NOT_CERTIFIED` (HTTP 422). The filing begins `DRAFT`, with `plan_year` copied from the run and the full premium snapshot computed: `participant_count` taken from the certified run's locked census across all participant statuses; `premium_target` equal to `funding_target` under the `STANDARD` method, or one hundred five percent of `funding_target` rounded half-up to cents under `ALTERNATIVE`; `market_assets` at the market value from the run's asset valuation, never the smoothed value; `uvb`, the unfunded vested benefits, as the premium target minus market assets, floored at zero; `flat_rate_premium` as one hundred dollars per participant; the uncapped variable premium as fifty dollars per thousand dollars of UVB, rounded half-up to cents; and `variable_rate_premium` as that uncapped value limited to a cap of six hundred dollars per participant. The `cap_applied` flag is true when the uncapped variable premium is greater than or equal to the cap — equality binds the cap. The `total_premium` is the flat-rate premium plus the variable-rate premium.

Filing moves a `DRAFT` filing to `FILED`, permitted only while the referenced run is `CERTIFIED` and the logical clock is on or before October 15 of the plan year; a filing attempted after that deadline is rejected with `ERR_FILING_DEADLINE_PASSED` (HTTP 422), and a successful filing stamps `filed_at` from the logical clock. When a newer certification has since superseded the run a `FILED` filing references — that is, the plan's currently certified run has a different id than the filing's premium snapshot — the filing may be amended, moving `FILED` → `AMENDED`: `valuation_run_id` is re-pointed to the currently certified run, every premium field is recomputed from it, and `filed_at` is cleared to null. Amending without such a delta — while the plan's currently certified run is the same run the filing already references — is rejected with `ERR_NO_AMENDMENT_DELTA` (HTTP 422). An `AMENDED` filing is filed again under the same certification and deadline preconditions, re-stamping `filed_at`. A `DRAFT` filing may be voided explicitly by a `PlanAdmin`, and both `DRAFT` and `AMENDED` filings are additionally voided automatically when a newer run certifies, per the cascade of §3.6; a `FILED` filing is never cascade-voided and instead moves through the amend path. `VOID` is terminal.

Disclosure reports serve the sponsor's financial statements. A `PlanAdmin`, `Actuary`, or `SeniorActuary` generates one from a certified run belonging to the same plan — again `ERR_VALUATION_RUN_NOT_CERTIFIED` guards the reference. The projected benefit obligation `pbo` recomputes the funding target participant-by-participant at the assumption set's `disclosure_discount_rate`, following the same pinned rounding order as §3.5: per-participant values rounded to cents first, then summed exactly. `fair_value_assets` is the market value of the plan's asset valuation, never smoothed. `funded_status` is `fair_value_assets` minus `pbo`, negative when the plan is underfunded. The report begins `DRAFT` and reaches its terminal `ACKNOWLEDGED` state when an `Auditor` acknowledges it, stamping `acknowledged_by` with the auditor's `X-User-ID`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Operations that create a new resource — a plan, an actuary, a census batch, an assumption set, an asset statement, an asset valuation, a valuation run, a credit-balance election, a contribution payment, a PBGC filing, or a disclosure report — return `201 Created`. Operations that modify an existing resource in place, including the bulk participant append (which mutates its batch) and every state-transition action, return `200 OK`. The table below is a summary of the HTTP contract only; request payloads, computed fields, validation conditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/plans` | Create a defined-benefit plan; auto-creates the credit-balance ledger seeded from the initial balances | PlanAdmin |
| GET | `/v1/plans` | List plans with pagination and an optional status filter | PlanAdmin, Actuary, SeniorActuary, Auditor, FirmAdmin |
| GET | `/v1/plans/{id}` | Fetch a single plan including computed posture and certified/presumed AFTAP | PlanAdmin, Actuary, SeniorActuary, Auditor, FirmAdmin |
| POST | `/v1/plans/{id}/terminate` | Terminate an ACTIVE plan (requires all contribution demands fully satisfied) | PlanAdmin |
| POST | `/v1/actuaries` | Register an actuary of the firm | FirmAdmin |
| GET | `/v1/actuaries/{id}` | Fetch an actuary | PlanAdmin, Actuary, SeniorActuary, Auditor, FirmAdmin |
| POST | `/v1/plans/{id}/census-batches` | Create a census batch (status UPLOADED) for a plan | PlanAdmin |
| GET | `/v1/plans/{id}/census-batches` | List census batches of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/census-batches/{id}` | Fetch a census batch including computed counts and screening errors | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/census-batches/{id}/participants` | Bulk-append participant rows; valid rows are written, per-row errors collected; returns a NEEDS_CORRECTION batch to UPLOADED | PlanAdmin |
| GET | `/v1/census-batches/{id}/participants` | List participants of a census batch | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/participants/{id}` | Fetch a single participant | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/census-batches/{id}/submit-screening` | Run row-level screening: zero errors → VALIDATED, any errors → NEEDS_CORRECTION | PlanAdmin |
| POST | `/v1/census-batches/{id}/lock` | Lock a VALIDATED census batch as immutable valuation reference | PlanAdmin |
| POST | `/v1/plans/{id}/assumption-sets` | Create an assumption set (DRAFT); preparer stamped from X-User-ID | Actuary, SeniorActuary |
| GET | `/v1/plans/{id}/assumption-sets` | List assumption sets of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/assumption-sets/{id}` | Fetch an assumption set | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/assumption-sets/{id}/submit` | Submit a DRAFT set for review (→ IN_REVIEW) | Actuary, SeniorActuary |
| POST | `/v1/assumption-sets/{id}/approve` | Approve an IN_REVIEW set (enrolled, non-preparer only) | SeniorActuary |
| POST | `/v1/assumption-sets/{id}/reject` | Reject an IN_REVIEW set back to DRAFT | SeniorActuary |
| POST | `/v1/assumption-sets/{id}/lock` | Lock an APPROVED set; one LOCKED set per plan and plan year | SeniorActuary |
| POST | `/v1/assumption-sets/{id}/reopen` | Reopen an APPROVED set to DRAFT; forbidden while a live run references it | SeniorActuary |
| POST | `/v1/assumption-sets/{id}/retire` | Retire a DRAFT assumption set (terminal) | Actuary, SeniorActuary |
| POST | `/v1/plans/{id}/asset-statements` | Record the plan-year asset roll-forward statement; unique per plan and year | PlanAdmin |
| GET | `/v1/plans/{id}/asset-statements` | List asset statements of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/plans/{id}/asset-valuations` | Compute the smoothed, corridor-clamped asset valuation for the plan year | Actuary, SeniorActuary |
| GET | `/v1/plans/{id}/asset-valuations` | List asset valuations of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/asset-valuations/{id}` | Fetch a single asset valuation | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/plans/{id}/valuation-runs` | Initiate a valuation run referencing census, assumptions, and asset valuation | Actuary, SeniorActuary |
| GET | `/v1/plans/{id}/valuation-runs` | List valuation runs of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/valuation-runs/{id}` | Fetch a valuation run including funding target, normal cost, and certified AFTAP | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/valuation-runs/{id}/compute` | Compute the run: per-participant accrual rows plus funding target and normal cost | Actuary, SeniorActuary |
| POST | `/v1/valuation-runs/{id}/certify` | Certify a COMPUTED run (OCC on the plan version); fires the posture/demand/filing cascade | SeniorActuary |
| POST | `/v1/valuation-runs/{id}/void` | Void an INITIATED or COMPUTED run | Actuary, SeniorActuary |
| GET | `/v1/census-batches/{id}/valuation-runs` | List valuation runs referencing a census batch | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/assumption-sets/{id}/valuation-runs` | List valuation runs referencing an assumption set | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/asset-valuations/{id}/valuation-runs` | List valuation runs referencing an asset valuation | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/valuation-runs/{id}/contribution-demands` | List contribution demands driven by a run | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/valuation-runs/{id}/pbgc-filings` | List PBGC filings referencing a run | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/valuation-runs/{id}/disclosure-reports` | List disclosure reports referencing a run | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/valuation-runs/{id}/accruals` | List participant accrual rows of a run | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/participants/{id}/accruals` | List accrual rows for a participant across runs | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/plans/{id}/credit-balance-ledger` | Read the plan's credit-balance ledger (array of zero or one entries) | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/plans/{id}/credit-balance-elections` | Create a credit-balance election (OCC on the plan version); draws the ledger waterfall and offsets the demand | PlanAdmin |
| GET | `/v1/plans/{id}/credit-balance-elections` | List credit-balance elections of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/credit-balance-elections/{id}/revoke` | Revoke an EFFECTIVE election within its 21-day window | PlanAdmin |
| GET | `/v1/contribution-demands/{id}` | Fetch a contribution demand including all computed funding amounts | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/plans/{id}/contribution-demands` | List contribution demands of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/contribution-demands/{id}/elections` | List elections applied to a demand | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/contribution-demands/{id}/payments` | Post a cash contribution payment against a demand (immutable event) | PlanAdmin |
| GET | `/v1/contribution-demands/{id}/payments` | List payments posted to a demand | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/plans/{id}/pbgc-filings` | Create a PBGC premium filing (DRAFT) from a certified run | PlanAdmin |
| GET | `/v1/plans/{id}/pbgc-filings` | List PBGC filings of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/pbgc-filings/{id}` | Fetch a PBGC filing | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/pbgc-filings/{id}/file` | File a DRAFT or AMENDED filing; deadline October 15 of the plan year | PlanAdmin |
| POST | `/v1/pbgc-filings/{id}/amend` | Amend a FILED filing after a superseding certification; premium recomputed | PlanAdmin |
| POST | `/v1/pbgc-filings/{id}/void` | Void a DRAFT filing | PlanAdmin |
| POST | `/v1/plans/{id}/disclosure-reports` | Generate a disclosure report (PBO at the disclosure rate, market assets, funded status) | PlanAdmin, Actuary, SeniorActuary |
| GET | `/v1/plans/{id}/disclosure-reports` | List disclosure reports of a plan | PlanAdmin, Actuary, SeniorActuary, Auditor |
| GET | `/v1/disclosure-reports/{id}` | Fetch a disclosure report | PlanAdmin, Actuary, SeniorActuary, Auditor |
| POST | `/v1/disclosure-reports/{id}/acknowledge` | Auditor acknowledgment of a DRAFT report (terminal) | Auditor |
| POST | `/v1/_clock/set_current_utc` | Advance the test-driving logical clock; re-evaluates demand delinquency | FirmAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_PARTICIPANT_DATA` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_TERMINATED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_ACTUARY_NOT_ENROLLED` | 422 Unprocessable Entity |
| `ERR_FILING_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_REVOCATION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ELECTION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_PLAN_YEAR_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ASSUMPTION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFERENCE_NOT_LOCKED` | 422 Unprocessable Entity |
| `ERR_VALUATION_RUN_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_CENSUS_YEAR_CONFLICT` | 409 Conflict |
| `ERR_ASSUMPTION_YEAR_CONFLICT` | 409 Conflict |
| `ERR_UNIQUENESS_VIOLATION` | 409 Conflict |
| `ERR_NO_AMENDMENT_DELTA` | 422 Unprocessable Entity |
| `ERR_CREDIT_BALANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

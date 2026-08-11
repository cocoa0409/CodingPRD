# Fitness & Wellness Reimbursement Benefit API — Product Requirements Document

## 1. Introduction

Employers increasingly subsidize fitness and wellness spending — gym memberships, studio classes, fitness apps, pool access — as a core health benefit, and the health plans administering those subsidies need an operational backbone that keeps the money honest. The Fitness & Wellness Reimbursement Benefit API is that backbone. It administers employer-sponsored benefit plans with tiered annual allowances, tracks member eligibility waiting periods and family dependents, maintains a contracted network of gyms and studios, and processes both member-submitted reimbursement claims and provider-submitted direct-pay claims against per-claim, quarterly, and annual limits.

Two ledgers anchor the design and must remain consistent at all times. Every member enrollment carries an allowance ledger recording how much of a tiered annual allowance has been consumed or reserved, and every employer funding account carries a cash ledger recording deposits, holds, debits, and clawbacks. Layered on top are visit recording with weighted anti-fraud scoring, a reviewer-driven claims pipeline with an information-request loop, monthly member statements, and employer-level utilization reporting. All benefit-time behavior — eligibility waiting periods, calendar-quarter boundaries, filing deadlines — is governed by a controllable logical clock rather than wall-clock time, so outcomes are deterministic and testable. All resources are mounted under the `/api` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly six roles: `BenefitsAdmin`, `ClaimsReviewer`, `Member`, `ProviderOperator`, `Auditor`, and `PlatformAdmin`.

- A `BenefitsAdmin` is the employer-side benefits operator who configures plans and tiers, onboards providers, manages member lifecycles, funds accounts, pays and reverses claims, and runs statements. A `ClaimsReviewer` works claims operations for the health plan: reviewing, approving, and rejecting claims; verifying, rejecting, and voiding visits; and triaging fraud flags. An `Auditor` has read-only oversight across all employers. A `PlatformAdmin` operates the test-driving facilities only. For each of these four roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare the resource's `member_id` field to `X-User-ID`, and a member caller may only touch resources whose `member_id` equals it.
- When `X-User-Role` is `ProviderOperator`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on visits and claims compare the resource's `provider_id` field to `X-User-ID`, and a provider operator may only touch visits and claims whose `provider_id` equals it.

A request with missing or unrecognized headers — or whose entity-backed identifier does not resolve to an existing record — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). A caller whose role is permitted but who reaches for a resource owned by someone else is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and System-Managed Fields

Every top-level resource carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments with every mutation, including system-driven mutations such as cascade steps and automatic state transitions.

Two resource kinds deviate from this convention. `PlanTier` rows and `FundingEntry` rows carry only `id` and `created_at`: both `updated_at` and `version` are absent on them, because tier rows are wholesale replaced rather than individually edited and ledger entries are immutable once appended.

### 2.5. The Logical Clock and Benefit-Time Semantics

All benefit-time reasoning runs on a server-side logical clock, never on wall-clock time. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time under any circumstance. A `PlatformAdmin` moves the clock forward by supplying a `to_iso8601` instant; the response echoes the new `current_utc`.

Advancing the clock has two system-wide consequences. First, any member whose derived `eligibility_date` has been reached flips automatically from `PENDING` to `ELIGIBLE`, with the usual `version` increment. Second, crossing a calendar-quarter boundary rolls every enrollment's quarter window forward: the enrollment's `quarter_key` is updated to the new quarter (for example from 2026-Q1 to 2026-Q2) and its `quarter_used_cents` is reset to zero.

### 2.6. Money, Precision, and Rounding

All monetary quantities in the system are integer cents; no fractional cent is ever stored. Whenever a calculation produces a fractional result — coverage percentages, the family dependent uplift, per-line tax — the value is rounded half up to the nearest whole cent. One deliberate exception exists: the utilization percentage on the employer report is a non-integer reported with exactly two decimal places, also rounded half up. Fraud scores are integers between 0 and 100 inclusive, clamped at 100.

### 2.7. Optimistic Concurrency on Superseding Amendments

Two write operations replace configuration wholesale and are therefore guarded by optimistic concurrency control. Replacing a plan's tier set via `PUT /api/benefit-plans/{id}/tiers` requires the request to carry `expected_plan_version`, the caller's last observed `version` of the plan. Re-papering a provider's contract via `PUT /api/providers/{id}/contract` requires `expected_provider_version`, the caller's last observed `version` of the provider. In both cases, if the supplied expectation does not match the resource's current `version` — because a previously accepted amendment has already advanced it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and no replacement occurs. Endpoints other than these two do not accept a version field.

### 2.8. Cascading Consistency Across Member and Provider Hierarchies

When a high-level resource becomes non-operational, everything downstream is resolved in the same operation rather than left dangling. Terminating a member cascades through dependents, enrollments, and open claims; terminating a provider cascades through recorded visits and the claims built on them; and a payment that exhausts an enrollment cascades into the rejection of that enrollment's remaining open claims. Every cascade step is a real mutation: each affected row refreshes `updated_at` and increments `version` where it carries one. Derived totals — allowance counters such as `used_cents` and `reserved_cents`, funding counters such as `available_cents` and `disbursed_cents` — are reconciled immediately as each event is applied, never lazily at read time.

### 2.9. Request Validation Pipeline and Error Ordering

Validation runs in a fixed priority order so that failures surface deterministically rather than being masked by later checks:

1. **Authentication** — the headers are present, the role is recognized, and entity-backed identifiers resolve (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the caller's role is listed for the endpoint (`ERR_FORBIDDEN_ROLE`), followed by ownership (`ERR_FORBIDDEN_OWNERSHIP`).
3. **Existence and request shape** — path identifiers are resolved left to right, and the request is rejected with the not-found error for the first identifier that does not resolve; a request for a dependent under a nonexistent member id fails with `ERR_MEMBER_NOT_FOUND` before the dependent id is even examined. The per-entity not-found errors are `ERR_EMPLOYER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_FUNDING_ACCOUNT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, and `ERR_FRAUD_FLAG_NOT_FOUND`. Body foreign keys — `employer_id`, `plan_id`, `member_id`, `enrollment_id`, and every element of `visit_ids` — resolve the same way, and an unresolvable id inside `visit_ids` yields `ERR_VISIT_NOT_FOUND`. Shape checks then follow: required fields present and well-typed (`ERR_INVALID_REQUEST`), enum fields carrying a declared member (`ERR_INVALID_ENUM`), money and quantity fields positive — `amount_cents` greater than zero, `quantity` at least one, `visit_rate_cents` zero or greater (`ERR_INVALID_AMOUNT`) — and datetime ranges coherent (`ERR_INVALID_DATE_RANGE`).
4. **State preconditions** — the target entity must be in the state its transition requires, with the per-transition 409 variants catalogued in §5.
5. **Staleness** — the optimistic-concurrency expectation on the two guarded amendment writes (`ERR_STALE_VERSION`).
6. **Fraud gate** — visit verification and claim approval refuse fraud-held targets (`ERR_FRAUD_HOLD`).
7. **Temporal windows** — filing deadline, contract window, and plan period checks.
8. **Business constraints** — overlaps, duplicates, caps, tier definedness, and dependent age.
9. **Referential guards** — visit-in-use and open-claims checks.
10. **Fiscal windows at approval** — quarterly headroom first, then annual headroom, then funding availability.

### 2.10. Twin Ledgers: Allowance and Funding Integrity

Two append-oriented ledgers anchor the money story, and both are maintained by chronological replay.

On the enrollment side, `used_cents` is produced by replaying the enrollment's claim payment events in claim `created_at` ascending order — ties are broken by `created_at` alone, never by `id` — adding each payment's `approved_amount_cents` and subtracting each clawback's. The `reserved_cents` figure is the sum of `claimed_amount_cents` over claims still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO`, plus the sum of `approved_amount_cents` over claims that are `APPROVED` and still `UNPAID`. The remaining allowance is `annual_allowance_cents` minus `used_cents` minus `reserved_cents`. The compensating invariant holds after every forward action (create, approve, pay) and every compensating action (reject, reverse, clawback): used plus reserved plus remaining always equals `annual_allowance_cents`.

On the employer side, the funding ledger's evaluation order is pinned, because the dependency looks circular and must be resolved in exactly this sequence. First, the account's `FundingEntry` rows are replayed in `created_at` ascending order; entries sharing a timestamp are ordered by kind, `DEPOSIT` first, then `RELEASE`, then `CLAWBACK_CREDIT`, then `HOLD`, then `DEBIT`. From that replay, `funded_cents` is the sum of deposits, and the ledger-available figure is funded plus clawback credits minus debits minus outstanding holds (holds netted against their releases). Second, open approvals are summed as the `approved_amount_cents` of claims that are `APPROVED` and `UNPAID` on plans belonging to the account's employer and benefit year — and the account's `reserved_cents` is derived from those claims, never re-summed from ledger entries. The account's `available_cents` equals the ledger-replayed figure and must never go negative. The compensating invariant holds after every payment and its reversal: `funded_cents` plus clawback credits equals `available_cents` plus `reserved_cents` plus `disbursed_cents`.

Each `FundingEntry` records its owning `funding_account_id`, the originating `claim_id` (null for deposits), an `entry_type` of `DEPOSIT`, `HOLD`, `RELEASE`, `DEBIT`, or `CLAWBACK_CREDIT`, an `amount_cents` that is always stored positive — the sign is implied by the entry type at application time — and `running_available_cents`, the account's `available_cents` immediately after that entry is applied in chronological replay.

## 3. Business Logic & Workflows

### 3.1. Employers, Plans, and Tier Configuration

A `BenefitsAdmin` onboards a sponsor by creating an employer with a legal `name` and a `funding_model` of either `PREFUNDED` or `PAY_AS_YOU_GO`. Employers begin `ACTIVE`; suspension flips an `ACTIVE` employer to `SUSPENDED`, and reactivation returns a `SUSPENDED` employer to `ACTIVE`, each incrementing `version`.

Within an employer, a benefit plan is drafted with its sponsoring `employer_id`, a display `name`, the calendar `benefit_year` (for example 2026), and a coverage window bounded by `period_start` and `period_end`. The window is closed — both boundary dates are valid service dates — and `period_end` must fall strictly after `period_start`, otherwise creation fails with `ERR_INVALID_DATE_RANGE`. A new plan starts in `DRAFT`. Activation moves it `DRAFT → ACTIVE` and is permitted only while the plan is `DRAFT` (any other state yields `ERR_PLAN_NOT_DRAFT`) and only once at least one tier exists. Retirement moves `ACTIVE → RETIRED`; a retired plan accepts no new enrollments while existing enrollments run undisturbed.

Tiers are configured by replacing the plan's entire tier set in a single superseding amendment. The payload's `tiers` array describes each `PlanTier`: a `tier_code` of `INDIVIDUAL`, `COUPLE`, or `FAMILY` — unique per plan, so a repeated `tier_code` in the payload is rejected with `ERR_DUPLICATE_TIER_CODE` — the base `annual_allowance_cents` for the tier, the `quarterly_cap_cents` limiting reimbursement within any calendar quarter, the `per_claim_cap_cents` limiting the approved amount of any single claim, the `visit_frequency_cap` governing rolling visit frequency, the `dependent_cap_pct` uplift fraction used by the `FAMILY` tier, and the three coverage fractions `in_network_pct`, `preferred_pct`, and `out_of_network_pct`. Each tier row references its owning plan through `plan_id`. Replacement is permitted while the plan is `DRAFT` or `ACTIVE`; it deletes the plan's existing tier rows, inserts one row per payload item, and advances the plan's `version` by one. Because the amendment supersedes whatever configuration came before, it carries the OCC expectation described in §2.7. The tier set of a plan can be listed by `BenefitsAdmin`, `Auditor`, and `Member` callers.

### 3.2. Members, Eligibility, and Dependents

Registration of a member is a `BenefitsAdmin` operation carrying the sponsoring `employer_id` and `plan_id`, the employer-side `external_ref`, the member's `full_name`, the `tier_code` they will enroll under, and their `hire_date`. Registration is only possible against an `ACTIVE` plan — a `DRAFT` or `RETIRED` plan yields `ERR_PLAN_NOT_ACTIVE` — and the chosen `tier_code` must be defined among that plan's tiers, otherwise `ERR_TIER_NOT_DEFINED`. From `hire_date` the system derives `eligibility_date` as exactly thirty days later. The member's `eligibility_status` starts at `PENDING`, unless the logical clock has already passed the derived `eligibility_date` at creation time, in which case the member starts `ELIGIBLE` immediately. Member lists can be filtered by `employer_id`, `plan_id`, and `eligibility_status`.

Thereafter the member lifecycle runs `PENDING → ELIGIBLE` automatically when the logical clock reaches `eligibility_date`, `ELIGIBLE → SUSPENDED` on suspension by a `BenefitsAdmin`, `SUSPENDED → ELIGIBLE` on reinstatement, and `ELIGIBLE` or `SUSPENDED → TERMINATED` on termination. An operation that requires an eligible member fails with `ERR_MEMBER_NOT_ELIGIBLE` while the member is `PENDING` or `SUSPENDED`; once `TERMINATED`, all member-scoped operations are refused with `ERR_MEMBER_TERMINATED`.

Termination is deliberately dramatic. When a member is terminated, every dependent of theirs still `ACTIVE` flips to `INACTIVE`; every enrollment in `ACTIVE` or `EXHAUSTED` flips to `CLOSED`, regardless of open claims; each closing enrollment rejects its claims still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO`; and each auto-rejected claim hands back its enrollment reservation — the `claimed_amount_cents` for a claim that never reached approval, or the `approved_amount_cents` for one that was `APPROVED` and still `UNPAID` — and releases any funding hold placed for it.

Dependents are managed under the member, either by a `BenefitsAdmin` or by the member acting on their own record, by supplying `full_name`, a `relationship` of `SPOUSE`, `CHILD`, or `DOMESTIC_PARTNER`, and a `birth_date`. A `CHILD` dependent must be younger than 26 at the plan's `period_start`; a child who has already reached their twenty-sixth birthday by that date is refused with `ERR_DEPENDENT_AGE_INELIGIBLE`. Dependents start `ACTIVE`. Deactivation moves `ACTIVE → INACTIVE` and is open to both `BenefitsAdmin` and the owning `Member`; deactivating an already-inactive dependent fails with `ERR_DEPENDENT_INACTIVE`. Adding or deactivating a dependent recomputes the effective annual allowance on every `ACTIVE` or `EXHAUSTED` enrollment of the parent member, as described in §3.4.

### 3.3. Provider Onboarding and Contract Management

Gyms, studios, apps, and pools join the network when a `BenefitsAdmin` creates a provider with a `name`, a `modality` of `GYM`, `STUDIO`, `APP`, or `POOL`, a `network_tier` of `IN_NETWORK`, `PREFERRED`, or `OUT_OF_NETWORK`, the contract window from `contract_start` to `contract_end`, and the per-visit direct-pay rate `visit_rate_cents`. The contract window is closed on both ends, and `contract_end` must be strictly after `contract_start` (`ERR_INVALID_DATE_RANGE` otherwise). New providers are `PENDING_ONBOARD` until activated; the network lifecycle then runs `PENDING_ONBOARD → ACTIVE`, `ACTIVE → SUSPENDED`, `SUSPENDED → ACTIVE`, and `ACTIVE` or `SUSPENDED → TERMINATED`. Provider lists can be filtered by `network_tier` and `status`.

Terminating a provider cascades through its book of business. Every visit recorded by that provider and still `RECORDED` flips to `REJECTED`; each such rejection forces any claim in `SUBMITTED` or `NEEDS_INFO` at that provider to `REJECTED`; and each auto-rejected claim releases its enrollment reservation. A terminated provider accepts no new visits and no contract amendment — attempts are refused with `ERR_PROVIDER_TERMINATED`. Operations that require an active provider fail with `ERR_PROVIDER_NOT_ACTIVE` while it is `PENDING_ONBOARD` or `SUSPENDED`.

Contract re-papering replaces the window and rate in a single superseding amendment carrying `contract_start`, `contract_end`, `visit_rate_cents`, and the OCC expectation `expected_provider_version` from §2.7; a successful amendment advances the provider's `version` by one.

### 3.4. Enrollment and the Allowance Snapshot

Enrollment attaches an eligible member to an active plan. The request carries `member_id` and `plan_id`; creation requires the member to be `ELIGIBLE` (`ERR_MEMBER_NOT_ELIGIBLE` while pending or suspended, `ERR_MEMBER_TERMINATED` once terminated) and the plan to be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE` otherwise). The member's `tier_code` must exist among the plan's tiers (`ERR_TIER_NOT_DEFINED`). A member's enrollments must have pairwise disjoint plan periods under closed-interval semantics — two periods sharing even a single calendar date already overlap — and a clashing enrollment is rejected with `ERR_ENROLLMENT_PERIOD_OVERLAP`.

Creation snapshots the tier configuration onto the enrollment: the `tier_code`, the `quarterly_cap_cents`, and an effective `annual_allowance_cents`. The effective allowance starts from the tier's base `annual_allowance_cents`. For the `FAMILY` tier only, the base grows by the dependent uplift: count the member's `ACTIVE` dependents, cap that count at three, multiply the base by one plus the capped count times `dependent_cap_pct`, and round half up to a whole cent. For `INDIVIDUAL` and `COUPLE` the effective allowance equals the base unchanged. This figure is recomputed whenever a dependent is added to or deactivated from the parent member. Usage counters start clean: `used_cents` and `reserved_cents` begin at zero, `quarter_used_cents` begins at zero, and `quarter_key` is stamped with the calendar quarter of the current logical clock, for example 2026-Q2. New enrollments are `ACTIVE`.

A computed allowance read is available to `BenefitsAdmin`, `Auditor`, and the owning `Member`, returning `enrollment_id`, `annual_allowance_cents`, `used_cents`, `reserved_cents`, the derived `remaining_cents`, the current `quarter_key`, `quarter_used_cents`, and `quarterly_remaining_cents`.

The enrollment lifecycle is partly system-driven. When a payment pushes `used_cents` to at least `annual_allowance_cents`, the enrollment flips `ACTIVE → EXHAUSTED`; when a clawback drops `used_cents` back below the allowance, it returns `EXHAUSTED → ACTIVE`. A `BenefitsAdmin` may close an enrollment in `ACTIVE` or `EXHAUSTED`, but only while no claims sit in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` — open claims block the close with `ERR_OPEN_CLAIMS_EXIST`, a guard bypassed solely by the member-termination cascade. A manual close releases any remaining reservation, which for a manual close must already be zero. Claim creation and claim approval both require an `ACTIVE` enrollment; an `EXHAUSTED` or `CLOSED` enrollment surfaces `ERR_ENROLLMENT_NOT_ACTIVE`.

### 3.5. Visit Recording, Frequency Caps, and Verification

Presence at a venue is captured as a visit. A `ProviderOperator` records one for a member by supplying `enrollment_id`, `member_id`, the interval from `check_in_at` to `check_out_at`, and a `verification_method` of `GEO_FENCE`, `POS_SWIPE`, or `MANUAL_REVIEW`; the recording `provider_id` is taken from the caller's own identity rather than the payload. The interval is half-open — it includes `check_in_at` and excludes `check_out_at` — and `check_out_at` must be strictly later than `check_in_at` (`ERR_INVALID_DATE_RANGE`). The system derives `duration_minutes` as the interval length in minutes and computes a provisional `fraud_score` as described in §3.6.

Three guards protect recording, evaluated within the pipeline order of §2.9. First, `check_in_at` must fall inside the provider's contract window, closed on both ends (`ERR_SERVICE_OUTSIDE_CONTRACT`). Second, the new interval may not intersect any of the member's other visits still in `RECORDED` or `VERIFIED`; merely adjacent visits, where one visit's `check_out_at` equals the next visit's `check_in_at`, are allowed, while a genuine intersection is refused with `ERR_VISIT_TIME_OVERLAP`. Third, the rolling frequency cap applies: counting the member's visits in `RECORDED` or `VERIFIED` whose `check_in_at` falls inside the thirty-day window ending at the new `check_in_at` — the window's lower bound is strict, so a visit exactly thirty days old is excluded — the count must be below the tier's `visit_frequency_cap`. Under a cap of 8, the eighth visit inside the window succeeds and the ninth is refused with `ERR_FREQUENCY_CAP_EXCEEDED`.

Review then dispositions the visit. Verification by a `ClaimsReviewer` moves `RECORDED → VERIFIED` and is permitted only while the visit is `RECORDED`, only while the recording provider is `ACTIVE` — a cross-entity dependency from visit to provider, failing with `ERR_PROVIDER_NOT_ACTIVE` otherwise — and only while the provisional `fraud_score` remains below 80; a provisional score of 80 or more refuses verification with `ERR_FRAUD_HOLD`. Verification recomputes the final `fraud_score`, and a final score of 50 or more automatically opens a fraud flag on the visit. Rejection moves `RECORDED → REJECTED`, and any claim referencing that visit in `SUBMITTED` or `NEEDS_INFO` is auto-rejected in cascade. A verified visit may be voided — `VERIFIED → VOIDED` — only while no claim in `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, or `APPROVED` references it; otherwise the void is refused with `ERR_VISIT_IN_USE`. `REJECTED` and `VOIDED` are terminal states for a visit.

### 3.6. Fraud Signals, Scoring, and Flag Triage

The fraud score weighs four signals. `GEOFENCE_MISMATCH` contributes 30 points when the visit's `verification_method` is `MANUAL_REVIEW`. `VELOCITY` contributes 10 points for every visit beyond the fifth in the trailing seven-day window ending at `check_in_at` — the first five visits in any such window are free. `PROVIDER_PATTERN` contributes 20 points when the provider was `SUSPENDED` at any point in the thirty days before `check_in_at`. `DUPLICATE_RECEIPT` contributes 40 points when another claim of the same member already carries the same `receipt_ref`. Each signal decays with age: at most three days old it counts at full weight, older than three days and up to seven days old at half weight, and older than seven days not at all. The score is the weighted sum, clamped at a maximum of 100.

Two variants of the computation exist. The provisional variant runs when the visit is recorded: it builds the velocity set from visits in `RECORDED` and `VERIFIED`, and applies no confirmed-flag multiplier. The final variant runs at verification: it builds the velocity set from `VERIFIED` visits only, doubles any signal backed by a `CONFIRMED` fraud flag, and — when the result is at least 50 — automatically opens a fraud flag on the visit.

A fraud flag records the offending `visit_id` (null for a claim-level flag) or `claim_id` (null for a visit-level flag), the dominant `signal` that crossed the threshold — one of `VELOCITY`, `OVERLAP_PATTERN`, `DUPLICATE_RECEIPT`, `GEOFENCE_MISMATCH`, or `PROVIDER_PATTERN` — and a `severity` from 1 to 10 derived from the final fraud score's decile. Flags start `OPEN`, and a `ClaimsReviewer` may confirm or clear a flag only while it is `OPEN` (`ERR_FLAG_NOT_OPEN` otherwise). Confirming a visit-level flag voids the flagged visit — `VERIFIED → VOIDED`, deliberately bypassing the visit-in-use guard — and any claim referencing it in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` is auto-rejected with its reservation released. Clearing a flag recomputes `fraud_hold` on referencing claims, which may drop back to false. A claim's `fraud_hold` is true whenever any visit it references carries an `OPEN` or `CONFIRMED` flag, and a held claim cannot be approved, as the next sections describe. Flag lists can be filtered by `visit_id`, `claim_id`, and `status`.

### 3.7. Claim Submission and the Review Pipeline

Claims come in two routings, fixed by `claim_type`: a `Member` submits a `REIMBURSEMENT` claim for out-of-pocket spending, while a `ProviderOperator` submits a `DIRECT_PAY` claim for services rendered at their venue. Every submission names the `enrollment_id` to debit, the `service_date`, an external `receipt_ref`, and a `line_items` array whose entries each carry a `description`, a `unit_amount_cents`, a `quantity`, and a `tax_pct`; `visit_ids` may optionally reference evidence visits and defaults to an empty list. For a `Member` caller the claimant `member_id` comes from the caller's identity; a `ProviderOperator` supplies `member_id` in the body. For `DIRECT_PAY` the `provider_id` is the caller's own provider identity; for `REIMBURSEMENT` it is derived from the first referenced visit or supplied in the body, and when the claim references no visits and no `provider_id` is supplied in the body, the claim's `provider_id` is null. The enrollment must be `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`), and the claim stamps its `quarter_key` from the calendar quarter of `service_date`. Claim lists can be filtered by `member_id`, `enrollment_id`, `provider_id`, and `review_status`.

The claimed total is computed line by line: for each line, multiply `unit_amount_cents` by `quantity` by one plus `tax_pct`, round that line total half up to a whole cent, and then sum the rounded line totals into `claimed_amount_cents`. Rounding per line before summing is mandatory — summing the raw line totals and rounding once is forbidden because it produces a different figure: three lines of 333 cents at quantity 1 with a five percent tax yield 350 + 350 + 350 = 1050 cents under the per-line rule, while the forbidden sum-then-round order yields 1049. On successful submission the claim reserves against the allowance: the enrollment's `reserved_cents` increases by `claimed_amount_cents`.

Four filing rules gate submission, evaluated within the pipeline order of §2.9. The `service_date` must fall inside the enrollment plan's coverage window, closed on both ends (`ERR_SERVICE_OUTSIDE_PLAN_PERIOD`), and may be no more than ninety days behind the logical clock — a claim exactly ninety days old is accepted, while one ninety-one days old is refused with `ERR_CLAIM_FILING_DEADLINE`. The `receipt_ref` must be unique per member across all of that member's claims that are not `REJECTED` (`ERR_DUPLICATE_RECEIPT`). Every id in `visit_ids` must reference a visit that is `VERIFIED` and owned by the claimant (`ERR_VISIT_NOT_VERIFIED`).

Review is a `ClaimsReviewer` pipeline on the `review_status` axis, which begins at `SUBMITTED` while the parallel `payment_status` axis begins at `UNPAID`. Starting review moves `SUBMITTED → UNDER_REVIEW`. Requesting information moves `UNDER_REVIEW → NEEDS_INFO` and accepts an optional `note`. The owning member resubmits, moving `NEEDS_INFO → UNDER_REVIEW` with an optional `note`, which increments `resubmission_count`; the third resubmission is the last, and a claim whose `resubmission_count` has already reached 3 is refused with `ERR_MAX_RESUBMISSIONS`. Only the member who owns the claim may resubmit it. Rejection is possible from `SUBMITTED`, from `UNDER_REVIEW`, or from `NEEDS_INFO`, accepts an optional `reason`, and always releases the claim's enrollment reservation. `REJECTED` is terminal — any further review transition attempted on it fails with `ERR_CLAIM_TERMINAL` — and any review transition attempted from a state that does not permit it fails with `ERR_CLAIM_NOT_REVIEWABLE`.

### 3.8. Approval, Payment, and Compensating Reversals

Approval computes the payable amount and locks funds against it. A `ClaimsReviewer` may approve only a claim sitting in `UNDER_REVIEW`, and the approval gate checks, in order: the claim's `fraud_hold` must be false (`ERR_FRAUD_HOLD`); the enrollment must be `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`); the funding account for the employer and benefit year must not be `SUSPENDED` (`ERR_FUNDING_NOT_ACTIVE`); and the computed payable amount must be positive and coverable by funding.

The payable computation proceeds as follows. The coverage fraction is taken from the enrollment's tier snapshot, selected by the provider's `network_tier`: `in_network_pct` for an `IN_NETWORK` provider, `preferred_pct` for `PREFERRED`, and `out_of_network_pct` for `OUT_OF_NETWORK`. A claim whose `provider_id` is null or does not resolve to a provider is covered at the `out_of_network_pct` fraction. The covered amount is `claimed_amount_cents` multiplied by that fraction, rounded half up to a whole cent. The annual headroom is `annual_allowance_cents` minus `used_cents` minus the reservations of the enrollment's other open claims — that is, `reserved_cents` excluding this claim's own reserved amount. The quarterly headroom is `quarterly_cap_cents` minus `quarter_used_cents` minus amounts reserved in the current quarter by other claims. The resulting `approved_amount_cents` is the smallest of the covered amount, the tier's `per_claim_cap_cents`, the annual headroom, and the quarterly headroom.

When approval fails on fiscal grounds, the rejection error is chosen in a fixed order — the quarterly window is always evaluated before the annual window. If the quarterly headroom is zero or less, the claim is rejected with `ERR_QUARTERLY_CAP_EXCEEDED`; otherwise, if the annual headroom is zero or less, with `ERR_ALLOWANCE_EXCEEDED`; otherwise, if the funding account's `available_cents` is below the approved amount, with `ERR_FUNDING_INSUFFICIENT`. The cap comparisons are inclusive: an approval that lands exactly on the quarterly cap succeeds.

A successful approval records `approved_amount_cents` — null until this point — rebalances the enrollment's reservation by subtracting the `claimed_amount_cents` and adding the `approved_amount_cents`, and places a funding hold: a `HOLD` entry is appended to the ledger, and the account's `reserved_cents` rises while its `available_cents` falls by the approved amount.

Payment and reversal are `BenefitsAdmin` operations on the `payment_status` axis, which only moves once review has reached `APPROVED`. Paying requires `payment_status` to be `UNPAID` and the funding account to be `FUNDED` (anything else yields `ERR_FUNDING_NOT_ACTIVE`). Payment converts the hold into a `DEBIT` entry: the account's `reserved_cents` falls and its `disbursed_cents` rises by the approved amount, while the enrollment's `reserved_cents` falls and its `used_cents` rises by the same amount, and `quarter_used_cents` grows by the approved amount when the payment instant falls inside the current quarter — quarter membership is half-open, so a payment exactly at a quarter's end belongs to the next quarter. If the payment pushes `used_cents` to at least `annual_allowance_cents`, the enrollment flips to `EXHAUSTED`, and every other claim on it still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` is auto-rejected, each releasing its enrollment reservation and any funding hold.

Reversal compensates. Reversing an `APPROVED`, still `UNPAID` claim moves payment to `REVERSED`: the hold is released through a `RELEASE` entry, the account's `reserved_cents` falls and its `available_cents` rises by the approved amount, and the enrollment's `reserved_cents` falls by `approved_amount_cents`. Reversing a `PAID` claim moves payment to `CLAWED_BACK`: a `CLAWBACK_CREDIT` entry is appended, `disbursed_cents` falls and `available_cents` rises by the approved amount, the enrollment's `used_cents` falls by the same, and `quarter_used_cents` falls as well when the quarter of the original payment is still the current quarter; if an `EXHAUSTED` enrollment's `used_cents` drops below its allowance after the decrement, the enrollment flips back to `ACTIVE`. A claim whose payment is already `REVERSED` or `CLAWED_BACK` cannot be reversed again (`ERR_PAYMENT_NOT_REVERSIBLE`).

### 3.9. Employer Funding, Statements, and Reporting

Each employer's money sits in one funding account per benefit year — one account per pair of `employer_id` and `benefit_year`. Creation takes `employer_id`, `benefit_year`, and an `initial_deposit_cents` that becomes the opening `DEPOSIT` entry. Later deposits carry an `amount_cents` that must be greater than zero (`ERR_INVALID_AMOUNT`), and each appends its own `DEPOSIT` entry, returning the created ledger entry. The account posture moves `FUNDED → DEPLETED` automatically when `available_cents` reaches exactly zero after a hold or a debit, moves `DEPLETED → FUNDED` when a positive deposit lands, and moves `FUNDED` or `DEPLETED → SUSPENDED` on suspension. Reactivation derives its target from the balance rather than from any caller preference: `SUSPENDED → FUNDED` when `available_cents` is positive, otherwise `SUSPENDED → DEPLETED`. The account's `funded_cents`, `available_cents`, `reserved_cents`, and `disbursed_cents` are maintained by the replay rules of §2.10, and the full ledger can be read either per account or per claim.

Member statements summarize one calendar month of activity. Creating a statement with `member_id` and `period_yyyymm` opens an `OPEN` statement whose `claim_count` tallies the member's claims with `service_date` inside that month and whose `provisional_total_cents` looks forward: the claimed amounts of claims still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO`, plus the approved amounts of claims `APPROVED` and still `UNPAID`, plus the approved amounts of claims `PAID`, minus the approved amounts of claims `CLAWED_BACK` whose payment fell inside the period — all drawn from claims whose `service_date` falls within the statement month. Finalizing moves `OPEN → FINALIZED` (any other state yields `ERR_STATEMENT_NOT_OPEN`) and computes `finalized_total_cents` on stricter terms: the approved amounts of claims `PAID` with payment inside the period, minus the approved amounts of claims `CLAWED_BACK` with payment inside the period. On identical data the final total is never higher than the provisional one.

Reopening moves `FINALIZED → OPEN` (otherwise `ERR_STATEMENT_NOT_FINALIZED`), resets `finalized_total_cents` to null, recomputes the provisional total, and accepts an optional `reason`. Delivery moves `FINALIZED → DELIVERED` (otherwise `ERR_STATEMENT_NOT_FINALIZED`); `DELIVERED` is terminal and refuses any further transition with `ERR_STATEMENT_LOCKED`. Statement lists can be filtered by `member_id` and `status`, and a member may read only their own statements.

The utilization report answers, for a supplied `employer_id` and `period_yyyymm`, how the benefit is being consumed. Over the employer's enrollments in `ACTIVE`, `EXHAUSTED`, or `CLOSED`, it aggregates `total_allowance_cents` and `total_used_cents`; `enrolled_members` counts those enrollments; `utilization_pct` is one hundred times the total used divided by the total allowance, rounded half up to two decimal places, and is zero when the total allowance is zero. The report also returns `paid_claim_count` — claims with `payment_status` `PAID` whose payment fell inside the period month — and `open_fraud_flags`, the count of `OPEN` fraud flags on visits and claims of the employer's members. The report is available to `BenefitsAdmin` and `Auditor` callers.

## 4. Endpoint Definitions

Operations that create a new resource — an employer, plan, member, dependent, provider, enrollment, visit, claim, funding account, deposit (which creates a ledger entry), or statement — return `201 Created`. Reads, state transitions, amendments, payments, reversals, and other actions on existing resources return `200 OK`. The request and response details of each operation are governed by the workflows in §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/employers` | Create an employer | BenefitsAdmin |
| GET | `/api/employers` | List employers | BenefitsAdmin, Auditor |
| GET | `/api/employers/{id}` | Read an employer | BenefitsAdmin, Auditor |
| POST | `/api/employers/{id}/suspend` | Suspend an employer (ACTIVE → SUSPENDED) | BenefitsAdmin |
| POST | `/api/employers/{id}/reactivate` | Reactivate an employer (SUSPENDED → ACTIVE) | BenefitsAdmin |
| POST | `/api/benefit-plans` | Create a benefit plan in DRAFT | BenefitsAdmin |
| GET | `/api/benefit-plans` | List benefit plans | BenefitsAdmin, Auditor |
| GET | `/api/benefit-plans/{id}` | Read a benefit plan | BenefitsAdmin, Auditor |
| POST | `/api/benefit-plans/{id}/activate` | Activate a plan (DRAFT → ACTIVE; requires at least one tier) | BenefitsAdmin |
| POST | `/api/benefit-plans/{id}/retire` | Retire a plan (ACTIVE → RETIRED) | BenefitsAdmin |
| PUT | `/api/benefit-plans/{id}/tiers` | Replace the plan's tier set (superseding amendment, OCC-guarded) | BenefitsAdmin |
| GET | `/api/benefit-plans/{id}/tiers` | List a plan's tiers | BenefitsAdmin, Auditor, Member |
| POST | `/api/members` | Register a member | BenefitsAdmin |
| GET | `/api/members` | List members | BenefitsAdmin, Auditor |
| GET | `/api/members/{id}` | Read a member (Member role: self only) | BenefitsAdmin, Auditor, Member |
| POST | `/api/members/{id}/suspend` | Suspend a member (ELIGIBLE → SUSPENDED) | BenefitsAdmin |
| POST | `/api/members/{id}/reinstate` | Reinstate a member (SUSPENDED → ELIGIBLE) | BenefitsAdmin |
| POST | `/api/members/{id}/terminate` | Terminate a member with the full cascade | BenefitsAdmin |
| POST | `/api/members/{id}/dependents` | Add a dependent to a member (Member: self only) | BenefitsAdmin, Member |
| GET | `/api/members/{id}/dependents` | List a member's dependents | BenefitsAdmin, Auditor, Member |
| POST | `/api/dependents/{id}/deactivate` | Deactivate a dependent (ACTIVE → INACTIVE) | BenefitsAdmin, Member |
| POST | `/api/providers` | Onboard a provider (PENDING_ONBOARD) | BenefitsAdmin |
| GET | `/api/providers` | List providers | BenefitsAdmin, Auditor, ClaimsReviewer, Member, ProviderOperator |
| GET | `/api/providers/{id}` | Read a provider | BenefitsAdmin, Auditor, ClaimsReviewer, Member, ProviderOperator |
| POST | `/api/providers/{id}/activate` | Activate a provider (PENDING_ONBOARD → ACTIVE) | BenefitsAdmin |
| POST | `/api/providers/{id}/suspend` | Suspend a provider (ACTIVE → SUSPENDED) | BenefitsAdmin |
| POST | `/api/providers/{id}/reinstate` | Reinstate a provider (SUSPENDED → ACTIVE) | BenefitsAdmin |
| POST | `/api/providers/{id}/terminate` | Terminate a provider with cascade | BenefitsAdmin |
| PUT | `/api/providers/{id}/contract` | Re-paper the contract window and rate (superseding amendment, OCC-guarded) | BenefitsAdmin |
| POST | `/api/enrollments` | Enroll a member into a plan (snapshots tier values) | BenefitsAdmin, Member |
| GET | `/api/enrollments` | List enrollments | BenefitsAdmin, Auditor, Member |
| GET | `/api/enrollments/{id}` | Read an enrollment (Member: own only) | BenefitsAdmin, Auditor, Member |
| POST | `/api/enrollments/{id}/close` | Close an enrollment (blocked by open claims) | BenefitsAdmin |
| GET | `/api/enrollments/{id}/allowance` | Read the computed allowance position | BenefitsAdmin, Auditor, Member |
| POST | `/api/visits` | Record a visit for a member | ProviderOperator |
| GET | `/api/visits` | List visits | BenefitsAdmin, Auditor, ClaimsReviewer, Member, ProviderOperator |
| GET | `/api/visits/{id}` | Read a visit | BenefitsAdmin, Auditor, ClaimsReviewer, Member, ProviderOperator |
| POST | `/api/visits/{id}/verify` | Verify a visit (RECORDED → VERIFIED; final fraud score) | ClaimsReviewer |
| POST | `/api/visits/{id}/reject` | Reject a visit (RECORDED → REJECTED) | ClaimsReviewer |
| POST | `/api/visits/{id}/void` | Void a verified visit (VERIFIED → VOIDED) | ClaimsReviewer |
| POST | `/api/claims` | Submit a reimbursement or direct-pay claim | Member, ProviderOperator |
| GET | `/api/claims` | List claims | BenefitsAdmin, Auditor, ClaimsReviewer, Member, ProviderOperator |
| GET | `/api/claims/{id}` | Read a claim | BenefitsAdmin, Auditor, ClaimsReviewer, Member, ProviderOperator |
| POST | `/api/claims/{id}/start-review` | Start review (SUBMITTED → UNDER_REVIEW) | ClaimsReviewer |
| POST | `/api/claims/{id}/approve` | Approve a claim and place the funding hold | ClaimsReviewer |
| POST | `/api/claims/{id}/reject` | Reject a claim and release its reservation | ClaimsReviewer |
| POST | `/api/claims/{id}/request-info` | Request more information (UNDER_REVIEW → NEEDS_INFO) | ClaimsReviewer |
| POST | `/api/claims/{id}/resubmit` | Resubmit a claim (NEEDS_INFO → UNDER_REVIEW; at most three times) | Member |
| POST | `/api/claims/{id}/pay` | Pay an approved claim (funding debit; exhaustion cascade) | BenefitsAdmin |
| POST | `/api/claims/{id}/reverse` | Reverse an unpaid approval or claw back a payment | BenefitsAdmin |
| POST | `/api/funding-accounts` | Create a funding account with an opening deposit | BenefitsAdmin |
| GET | `/api/funding-accounts` | List funding accounts | BenefitsAdmin, Auditor |
| GET | `/api/funding-accounts/{id}` | Read a funding account | BenefitsAdmin, Auditor |
| POST | `/api/funding-accounts/{id}/deposits` | Deposit funds into an account | BenefitsAdmin |
| GET | `/api/funding-accounts/{id}/entries` | List an account's ledger entries | BenefitsAdmin, Auditor |
| POST | `/api/funding-accounts/{id}/suspend` | Suspend a funding account | BenefitsAdmin |
| POST | `/api/funding-accounts/{id}/reactivate` | Reactivate a funding account (target posture derived from balance) | BenefitsAdmin |
| GET | `/api/claims/{id}/funding-entries` | List ledger entries linked to a claim | BenefitsAdmin, Auditor, ClaimsReviewer |
| GET | `/api/fraud-flags` | List fraud flags | BenefitsAdmin, Auditor, ClaimsReviewer |
| GET | `/api/fraud-flags/{id}` | Read a fraud flag | BenefitsAdmin, Auditor, ClaimsReviewer |
| POST | `/api/fraud-flags/{id}/confirm` | Confirm a flag (OPEN → CONFIRMED; voids the flagged visit) | ClaimsReviewer |
| POST | `/api/fraud-flags/{id}/clear` | Clear a flag (OPEN → CLEARED; recomputes fraud holds) | ClaimsReviewer |
| POST | `/api/statements` | Generate a monthly statement with provisional totals | BenefitsAdmin |
| GET | `/api/statements` | List statements | BenefitsAdmin, Auditor, Member |
| GET | `/api/statements/{id}` | Read a statement (Member: own only) | BenefitsAdmin, Auditor, Member |
| POST | `/api/statements/{id}/finalize` | Finalize a statement (OPEN → FINALIZED) | BenefitsAdmin |
| POST | `/api/statements/{id}/reopen` | Reopen a statement (FINALIZED → OPEN) | BenefitsAdmin |
| POST | `/api/statements/{id}/deliver` | Deliver a statement (FINALIZED → DELIVERED, terminal) | BenefitsAdmin |
| GET | `/api/reports/utilization` | Employer utilization report for a month | BenefitsAdmin, Auditor |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_AMOUNT` | 400 |
| `ERR_INVALID_DATE_RANGE` | 400 |
| `ERR_EMPLOYER_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_DEPENDENT_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_FUNDING_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_FRAUD_FLAG_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_TIER_CODE` | 400 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 |
| `ERR_MEMBER_TERMINATED` | 409 |
| `ERR_PROVIDER_NOT_ACTIVE` | 409 |
| `ERR_PROVIDER_TERMINATED` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 |
| `ERR_CLAIM_TERMINAL` | 409 |
| `ERR_PAYMENT_NOT_REVERSIBLE` | 409 |
| `ERR_STATEMENT_NOT_OPEN` | 409 |
| `ERR_STATEMENT_NOT_FINALIZED` | 409 |
| `ERR_STATEMENT_LOCKED` | 409 |
| `ERR_FUNDING_NOT_ACTIVE` | 409 |
| `ERR_FLAG_NOT_OPEN` | 409 |
| `ERR_DEPENDENT_INACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FRAUD_HOLD` | 422 |
| `ERR_CLAIM_FILING_DEADLINE` | 422 |
| `ERR_SERVICE_OUTSIDE_CONTRACT` | 422 |
| `ERR_SERVICE_OUTSIDE_PLAN_PERIOD` | 422 |
| `ERR_VISIT_TIME_OVERLAP` | 409 |
| `ERR_DUPLICATE_RECEIPT` | 409 |
| `ERR_FREQUENCY_CAP_EXCEEDED` | 422 |
| `ERR_ENROLLMENT_PERIOD_OVERLAP` | 409 |
| `ERR_DEPENDENT_AGE_INELIGIBLE` | 422 |
| `ERR_MAX_RESUBMISSIONS` | 422 |
| `ERR_TIER_NOT_DEFINED` | 422 |
| `ERR_VISIT_NOT_VERIFIED` | 422 |
| `ERR_VISIT_IN_USE` | 409 |
| `ERR_OPEN_CLAIMS_EXIST` | 409 |
| `ERR_ALLOWANCE_EXCEEDED` | 422 |
| `ERR_QUARTERLY_CAP_EXCEEDED` | 422 |
| `ERR_FUNDING_INSUFFICIENT` | 422 |

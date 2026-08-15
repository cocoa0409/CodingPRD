# Employee Referral Program API — Product Requirements Document

## 1. Introduction

Employee referrals are the highest-converting sourcing channel for most talent acquisition teams, yet the administrative machinery behind them is notoriously error-prone: eligibility rules vary by role and tenure, the same candidate drifts in and out of cooldown windows, bonus amounts depend on the policy in force at the moment of submission, tax withholding differs per employee, and a small minority of participants attempt to game the program through self-referrals, referral rings, or resume farming. This document specifies the Employee Referral Program API, the system of record that a talent acquisition team uses to administer the full life of a referral — from the moment an employee submits a name, through recruiter review and hiring stages, to bonus accrual, payroll disbursement, retention verification, and, where necessary, clawback.

The API is designed around four commitments. First, **determinism**: every time-dependent rule (tenure, cooldowns, referral expiry, retention, clawback, campaign windows, risk-score decay) is evaluated against a single logical clock rather than wall-clock time, so program behavior is reproducible and auditable. Second, **money correctness**: all bonus and withholding arithmetic is performed in integer cents with explicitly pinned rounding points, and every referral permanently pins the policy version that governed its submission so later policy changes never rewrite history. Third, **segregation of duties**: the operator who prepares payroll is never the one who confirms payment, and a compliance officer may never decide an abuse case they raised. Fourth, **complete auditability**: every referral status change appends to an immutable event log, and every abuse decision, forfeiture, and settlement adjustment is reconstructible from stored state.

All resources are mounted under the `/erp` URL prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly seven roles, spelled precisely as follows: `PlatformAdmin`, `TalentAdmin`, `Recruiter`, `HiringManager`, `Employee`, `PayrollProcessor`, and `ComplianceOfficer`. A request with missing headers, or whose `X-User-Role` value is not one of these seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role, and the distinction matters for ownership checks:

- When `X-User-Role` is `Recruiter`, `HiringManager`, or `Employee`, `X-User-ID` is the `id` of the acting **Employee** record; ownership checks on any resource that references an Employee compare the resource's foreign-key field (for example a referral's `referrer_id`) to `X-User-ID`. An `Employee`-role caller may only act as or on behalf of itself: submitting a referral requires `referrer_id` to equal `X-User-ID`, withdrawing a referral is only permitted to its own referrer, updating a tax profile is only permitted on the caller's own employee record, and reading referrals through the per-employee or per-referral views is scoped to the caller's own records: the `GET /erp/referrals` list is filtered to the caller's own referrals, and the per-employee referral list and the single-referral read reject cross-employee access (the per-referral milestone and event subordinate views are not ownership-scoped — they are readable by every role §4 lists for them). A violation of this scoping is rejected with `ERR_FORBIDDEN` (HTTP 403).
- When `X-User-Role` is `PlatformAdmin`, `TalentAdmin`, `PayrollProcessor`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `raised_by_user_id` or `decided_by_user_id` on an abuse case, or as `approved_by_user_id` on a bonus milestone — but never compares it to any entity's `id`.

Wherever the system acts on its own (automatic transitions and auto-raised abuse cases), the recorded actor is the literal string `system`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties at the same logical instant broken by creation (insertion) order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Program Time

Every time-dependent rule in the program — tenure, candidate cooldowns, referral expiry, retention due dates, clawback windows, campaign windows, fraud-score decay, and calendar-year accumulators — is evaluated against a single server-side **logical clock**, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, all "now" references resolve to that instant and the clock never silently falls back to wall-clock time.

A `PlatformAdmin` may advance or rewind the logical clock through an administrative capability that accepts a `to_iso8601` timestamp and responds with the resulting `now_iso8601`. Setting the clock is not required to be monotone: tests and operators may move it backward, and the system applies all rules against whatever the clock currently reads.

Two calendar conventions recur throughout this document. A *calendar year* runs from January 1 00:00:00 inclusive to the following January 1 00:00:00 exclusive, in UTC. *Calendar-month addition* (used for candidate cooldowns) adds whole months to a timestamp and clamps the day-of-month to the target month's last day when the target month is shorter: for example, six months after 2026-01-31 is 2026-07-31, while six months after 2025-08-31 is 2026-02-28.

### 2.5. Resource Identity and Common Fields

All primary resources (employees, candidates, requisitions, policy versions, campaigns, referrals, bonus milestones, payroll batches, abuse cases, and tax profiles) share a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every mutation of the resource, including mutations performed automatically by the server (for example when a batch's totals recompute, or when an active policy is superseded). A resource's `version` starts at 1 upon creation, and it increments at most once per resource per request, however many mutations that one request applies to the resource.

The three-fractional-digit convention stated for `created_at` is uniform across the API: every timestamp the server serializes in a response — `created_at`, `updated_at`, the `api_request_timestamp` of §2.2, the clock capability's `now_iso8601`, and every entity date or clock-derived field (for example `hire_date`, `opened_at`, `effective_from`, `effective_to`, `window_start`, `window_end`, `submitted_at`, `last_terminal_outcome_at`, `cooldown_until`, `retention_due_at`, `clawback_until`, `earned_at`, `terminated_at`, `departed_at`, and `confirmed_at`) — is rendered as an ISO 8601 UTC string with exactly three fractional digits (for example `2026-08-01T00:00:00.000Z`). A timestamp field whose value is absent is rendered as null rather than as a string.

The **ReferralEvent** is the sole exception to this common-field convention. As an append-only audit record it carries only `id` and `created_at`; `updated_at` and `version` are absent because events are never modified after being written.

### 2.6. Money, Rates and Rounding

All monetary amounts in the system are integer numbers of cents, carried in fields whose names end in `_cents` (for example `budget_cents`, `amount_cents`, `withholding_cents`). No floating-point money is ever stored or returned.

Rounding occurs only at explicitly marked rounding points, always using the *round half up* method to the nearest whole cent: the campaign uplift multiplication at referral submission, the hire/retention milestone split at hire time, and the withholding computation at milestone approval. Percentages and multipliers are expressed in **basis points**, where 10000 basis points equal one hundred percent — so a campaign `multiplier_bps` of 15000 means one and a half times the base, and the default supplemental withholding rate of 2200 basis points means twenty-two percent. Rates produced by program analytics are decimal fractions rounded half-up to six decimal places.

### 2.7. Optimistic Concurrency Control

Exactly three write operations in the API participate in optimistic concurrency control, and each names its guard field explicitly:

- Editing a campaign requires the request to carry `expected_campaign_version`, holding the campaign `version` the client last observed.
- Attaching a milestone to a payroll batch requires `expected_payroll_batch_version`, holding the batch `version` the client last observed.
- Removing a milestone from a payroll batch likewise requires `expected_payroll_batch_version`.

In all three cases the field is non-optional. If the supplied value does not match the parent resource's current `version` — meaning another writer has legitimately advanced that resource (for example by editing campaign budgets or windows, or by adding and removing milestones, both of which recompute batch totals and increment the batch version) since the client's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the resource before re-issuing its change. The stale-version check runs after the generic pipeline of §2.10 and before the operation's own business rules: on a campaign edit, a stale version surfaces as `ERR_STALE_VERSION` before the window-overlap and budget-floor checks are ever evaluated, and likewise a stale batch version is reported before batch-open or milestone-attachability checks on milestone add and remove. No endpoint other than these three accepts a version field; all other mutations are applied against the server's current state.

### 2.8. The Pinned Policy: Every Referral's Rule of Record

Program rules are versioned through the **PolicyVersion** resource. At most one policy version is in the `ACTIVE` state at any time. When a referral is submitted, the system pins the currently active policy onto the referral as its `policy_version_id`, and every rule constant that referral ever needs — minimum referrer tenure, candidate cooldown length, referral expiry window, hire/retention split percentage, retention period, clawback window, annual cap, velocity limit, and the five tier bonus amounts — is read from that pinned version for the entire life of the referral, regardless of later policy changes.

Activating a new policy version automatically supersedes the previously active one. Referrals already in flight keep their pinned policy untouched; only new submissions observe the newly active version. This guarantee is what makes historical bonus amounts auditable: the numbers on a referral can always be re-derived from its pinned policy, its requisition level, and its attached campaign.

### 2.9. Resolving Nested Paths

The API enforces strict, left-to-right validation of hierarchical request paths. When an endpoint path contains multiple resource identifiers (for example a milestone nested under a payroll batch), the server validates the existence of each identifier in path order and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the *first* identifier that does not correspond to an existing resource, without examining later segments.

### 2.10. The Validation Pipeline and Error Precedence

Every request flows through a fixed validation pipeline, and checks are always evaluated in the same relative order so that the surfaced error is deterministic when several problems coexist. The global order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is recognized; otherwise `ERR_UNAUTHENTICATED`.
2. **Request shape** — required fields are present, types are valid, dates parse, enum-like inputs are in range, and structural constraints such as "a requisition's `openings` is at least 1" hold; otherwise `ERR_INVALID_REQUEST`. A referral submission that supplies neither `candidate_id` nor `candidate_email` also fails here.
3. **Enum membership** — every enum field carries a declared member (this covers `job_level`, `level`, `case_type`, `filing_status`, `withholding_method`, the `to_state` of a stage advancement, and the `reason_code` of a rejection); otherwise `ERR_INVALID_ENUM`.
4. **Role authorization** — the caller's role is listed for the endpoint; otherwise `ERR_FORBIDDEN`.
5. **Ownership scoping** — an `Employee`-role caller acts only on its own resources, as described in §2.1; otherwise `ERR_FORBIDDEN`.
6. **Existence** — path-templated resources exist, validated left-to-right per §2.9; body fields that name resources (for example `referrer_id`, `job_requisition_id`, `candidate_id`, `employee_id`, `referral_id`, `milestone_id`) are likewise checked here, except where an endpoint's own rules state a different order (for example the payroll-batch milestone add of §3.6); otherwise `ERR_NOT_FOUND`.
7. **State legality** — the target resource is in a state from which the requested transition exists. If the resource is already in a terminal state, every transition attempt is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409); if the resource is in a non-terminal state that simply does not offer the requested transition, the rejection is `ERR_INVALID_STATE` (HTTP 409).

Only after this generic pipeline do endpoint-specific business rules run, always in ascending order of their rule priority — for example, on a referral submission the requisition-is-open check fires before the referrer-suspension check, which fires before the self-referral check, and so on through the eligibility gauntlet described in §3.3. Where a state-machine transition declares a precondition without a more specific error code (for example, recording a departure for a candidate who is not currently hired), the rejection is the generic state rejection `ERR_INVALID_STATE`.

### 2.11. The Referral Audit Trail

Every referral carries an append-only log of **ReferralEvent** records. Each event stores the `referral_id` it belongs to, the machine name of what happened in `event_type` (for example `SUBMIT`, `REVIEW`, `REQUEST_INFO`, `PROVIDE_INFO`, `QUALIFY`, `REJECT`, `ADVANCE`, `OFFER_DECLINED`, `HIRE`, `NOT_SELECTED`, `WITHDRAW`, `EXPIRE`, `FORFEIT`, `RETENTION_MET`, or `RETENTION_FAILED`), the referral's `from_state` and `to_state` around the event (`from_state` is null on `SUBMIT`, which has no predecessor state), the `actor_user_id` of who triggered it (the caller's `X-User-ID`, or the literal string `system` for automatic transitions), and an optional `note` carried from the triggering request. Events are created as a side effect of the transitions described in §3 and are never modified or deleted; as noted in §2.5 they have no `updated_at` or `version`.

## 3. Business Logic & Workflows

### 3.1. People First: Employee Records, Tax Profiles, and Offboarding

Everything in the program begins with the **Employee** roster, maintained by a `PlatformAdmin`. Creating an employee records their unique `employee_number` (unique across all employees — a submission reusing an existing `employee_number` is rejected with `ERR_INVALID_REQUEST`, HTTP 400), `full_name`, work `email`, `department` code, `job_level` (one of `IC`, `SENIOR`, `MANAGER`, `DIRECTOR`, or `EXECUTIVE`), and `hire_date`; the `is_recruiter` flag defaults to false and marks talent-acquisition recruiters, to whom special exclusion rules apply. A new employee starts with `employment_status` set to `ACTIVE`. The server derives `tenure_days` on every read: the elapsed time between `hire_date` and the logical clock, divided into whole days of 86400 seconds each and rounded down, with the result never allowed to drop below zero — a future-dated `hire_date` therefore yields a tenure of zero days. Employees can be listed (with optional `department`, `job_level`, and `employment_status` filters) and fetched individually by every role.

Each employee accumulates two anti-abuse counters maintained entirely by the system, both starting at zero: `fraud_strikes`, a count of that employee's confirmed abuse cases, and `risk_score`, a decayed weighted sum of those cases whose mechanics are detailed in §3.7. When the `risk_score` reaches at least 100, the employee's derived `referral_suspended` flag becomes true and blocks further submissions. Two further derived counters, `annual_provisional_cents` and `annual_committed_cents`, track the employee's calendar-year bonus totals under two different status lenses and are defined precisely in §3.5; both default to zero.

Offboarding is deliberate and consequential. A `PlatformAdmin` may terminate an employee whose `employment_status` is `ACTIVE` (a terminated employee is terminal; any further action on them is rejected with `ERR_ALREADY_TERMINAL`). Termination stamps `terminated_at` with the logical clock and immediately forfeits the employee's unpaid bonus earnings: every bonus milestone attached to referrals where this employee is the `referrer_id`, while in the `EARNED`, `APPROVED`, or `BATCHED` state, transitions to `FORFEITED`. A milestone forfeited out of the `BATCHED` state is first detached from its payroll batch — its `payroll_batch_id` is cleared — and the batch's totals recompute with the batch `version` incrementing. Each forfeiture also releases the referral's remaining campaign reservation per the settlement rules of §3.2: the campaign's `reserved_cents` is reduced by the referral's outstanding uplift share, and its `spent_cents` is reduced by any earned-but-now-forfeited share. Milestones still `PENDING` (for example an unearned retention milestone) are not touched by termination, and milestones already `PAID` stay paid — money already disbursed is recovered only through the clawback path of §3.5, never by termination.

Alongside the roster, each employee has at most one **TaxProfile**, in a strict one-to-one relationship identified by `employee_id`. The profile is upserted — created on first write, replaced on later writes — by the employee themselves or by a `PayrollProcessor`, capturing the `filing_status` (`SINGLE`, `MARRIED`, or `HEAD_OF_HOUSEHOLD`), the `withholding_method` (`FLAT` or `AGGREGATE`, which selects the withholding variant described in §3.6), an optional `supplemental_rate_bps` flat-rate override in basis points (absent means the default of 2200), and an optional `ytd_carryover_cents` migration figure (defaulting to zero) representing referral-bonus gross paid earlier this calendar year outside the system. A profile begins in `SUBMITTED` status; a `PayrollProcessor` then verifies it, moving it to `VERIFIED` — verification requires an existing profile in `SUBMITTED`, so the call is `ERR_NOT_FOUND` (HTTP 404) when no profile exists and `ERR_INVALID_STATE` (HTTP 409) from any other status. Any subsequent update to a verified profile re-opens verification by returning the status to `SUBMITTED`, while the system-maintained `ytd_paid_gross_cents` accumulator — the running total of this calendar year's paid referral-bonus gross, starting at zero and incremented only when payment is confirmed — is preserved across the re-submission. Payout approval requires a verified profile, so an unreviewed edit deliberately blocks the approve step described in §3.6. Reading a tax profile returns an array containing zero or one element, reflecting the one-to-one relationship.

### 3.2. Framing the Program: Requisitions, Policy Versions, and Campaigns

A `TalentAdmin` frames the program with three instruments: what can be hired for, under which rules, and with what promotional uplift.

**Job requisitions.** Creating a requisition records a unique `req_number` (a duplicate `req_number` is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `title`, the hiring `department` code, the `level` (`IC`, `SENIOR`, `MANAGER`, `DIRECTOR`, or `EXECUTIVE`) that selects the bonus tier, whether the requisition is `referral_eligible` (default true), a `hard_to_fill` flag (default false) used as campaign targeting metadata, and the number of `openings` (default one, and always at least one — a request with fewer is rejected with `ERR_INVALID_REQUEST`). A requisition starts in `DRAFT`. Opening it stamps `opened_at` with the logical clock and moves it to `OPEN`; an open requisition may be paused and later resumed, and the `OPEN`–`PAUSED` cycle may repeat an unlimited number of times. Cancelling is possible from `DRAFT`, `OPEN`, or `PAUSED`; cancelling an `OPEN` or `PAUSED` requisition moves every one of its referrals still in a pre-hire state (`SUBMITTED` through `OFFER_EXTENDED` — a referral already `HIRED` is unaffected) to `NOT_SELECTED` with `last_decision_reason` set to `REQ_CANCELLED` and releases each referral's remaining campaign reservation, with the cascade's `NOT_SELECTED` events recording the cancelling `TalentAdmin`'s `X-User-ID` as actor, while cancelling a `DRAFT` requisition has no such cascade because nothing can be attached to it yet. The requisition's `filled_count` starts at zero; when a hire raises `filled_count` to equal `openings`, the requisition automatically transitions from `OPEN` to `FILLED`, records the just-hired candidate in `filled_by_candidate_id`, and every *other* referral still in a pre-hire state for the requisition moves to `NOT_SELECTED` with `last_decision_reason` `REQ_FILLED`, again releasing each one's remaining campaign reservation, with the cascade's events recorded under the actor `system`. `FILLED` and `CANCELLED` are terminal. The derived `open_referral_count` reports how many of the requisition's referrals are currently non-terminal. Requisitions may be listed with `status`, `department`, `level`, and `filled_by_candidate_id` filters, and each requisition exposes its referral list and its covering campaign list as subordinate views.

**Policy versions.** A policy version carries an effectiveness window from `effective_from` (inclusive) to `effective_to` (exclusive, with a null `effective_to` meaning open-ended) plus the full rule set, every member of which takes a documented default when omitted from the creation request: `min_tenure_days` 90, `duplicate_cooldown_months` 6, `referral_expiry_days` 45, `hire_pct` 30 (the percentage of the gross bonus paid at the hire milestone, which must be between 1 and 99 inclusive, with the retention milestone paying the remainder), `retention_days` 180, `clawback_days` 90, `annual_cap_cents` 2000000 (twenty thousand dollars per referrer per calendar year), `velocity_limit` 5, and the tier amounts `tier_ic_cents` 150000, `tier_senior_cents` 300000, `tier_manager_cents` 500000, `tier_director_cents` 650000, and `tier_executive_cents` 800000. An optional free-form `note` may accompany the policy. A new policy starts in `DRAFT` and may be retired directly from there (moving to `RETIRED`). Activation is guarded twice: the candidate window, interpreted as the half-open interval from `effective_from` inclusive to `effective_to` exclusive, must not overlap the window of any other policy in `DRAFT` or `ACTIVE` — half-open semantics mean two windows that merely touch at an endpoint do *not* overlap — with a conflict rejected as `ERR_POLICY_WINDOW_CONFLICT` both at creation and at activation; and `effective_from` must be at or before the current logical time, since a future-dated policy cannot be activated (the attempt is rejected with `ERR_INVALID_STATE`, HTTP 409). When activation succeeds, the previously `ACTIVE` policy, if any, transitions to `SUPERSEDED` with its `version` incrementing; per §2.8, in-flight referrals keep their pinned `policy_version_id` while new submissions pin the newly active policy. `SUPERSEDED` and `RETIRED` are terminal states. Policies may be listed with a `status` filter.

**Campaigns.** A campaign promotes one specific requisition — the request names it via `job_requisition_id`, and a campaign covers exactly one requisition — with a `name`, a `multiplier_bps` uplift multiplier in basis points, a `flat_addon_cents` flat uplift, a closed promotional window from `window_start` to `window_end` (both ends inclusive), a total uplift `budget_cents`, and an optional `max_payouts` cap on the number of referrals that may attach the campaign (null meaning unlimited). Because same-requisition campaign windows may never overlap, creation enforces a closed-interval overlap check: for the same `job_requisition_id`, the new window must not overlap the window of any other campaign in `DRAFT`, `ACTIVE`, `PAUSED`, or `EXHAUSTED` — and because the intervals are closed, two windows that merely touch at an endpoint *do* conflict, unlike policy windows. A violation is rejected with `ERR_CAMPAIGN_WINDOW_CONFLICT`.

A campaign starts in `DRAFT`. Activation requires, checked in this order, that some policy version is currently `ACTIVE` (otherwise `ERR_NO_ACTIVE_POLICY`) and that the campaign window has not already elapsed — `window_end` at or after the logical now, otherwise `ERR_CAMPAIGN_WINDOW_EXPIRED`. An active campaign may be paused and later re-activated (re-activation re-checks only the window), and the operations sweep of §3.5 ends any `ACTIVE` or `PAUSED` campaign whose `window_end` has passed, moving it to `ENDED`. A `TalentAdmin` may also end a campaign outright from any non-terminal state — `DRAFT`, `ACTIVE`, `PAUSED`, or `EXHAUSTED` — moving it to `CANCELLED`. Ending, in either form, releases outstanding reservations: every attached non-terminal referral keeps its `campaign_id` for audit purposes, but the unpaid share of its uplift is released from the campaign's `reserved_cents`, while uplift already earned stays in `spent_cents`.

While a campaign runs, three counters track its money, with `reserved_cents` and `spent_cents` both starting at zero: `reserved_cents` (uplift reserved by attached non-terminal referrals), `spent_cents` (uplift converted to earned, net of forfeits and clawbacks), and the derived `remaining_cents`. A pinned invariant holds at all times: reserved plus spent plus remaining always equals `budget_cents`, and all three are non-negative. The derived `payouts_count`, also starting at zero, tracks how many referrals are currently attached (non-terminal, including attachments whose uplift turned out to be zero). When `spent_cents` reaches exactly `budget_cents` after a milestone earn converts reserved uplift, the campaign automatically moves from `ACTIVE` to `EXHAUSTED`, and no new referrals may attach it while exhausted; when a later forfeit or clawback release pushes `spent_cents` back below `budget_cents`, the campaign automatically returns from `EXHAUSTED` to `ACTIVE`.

Campaign edits are optimistic-concurrency guarded per §2.7 via `expected_campaign_version`, and a successful edit increments the campaign's `version` by one. Editable fields include `name`, `multiplier_bps`, `flat_addon_cents`, `window_start`, `window_end`, `budget_cents`, and `max_payouts`. Editing is permitted only while the campaign is `DRAFT`, `ACTIVE`, or `PAUSED`; an `EXHAUSTED` campaign rejects edits with `ERR_INVALID_STATE`, and an `ENDED` or `CANCELLED` one with `ERR_ALREADY_TERMINAL`. Window edits re-run the closed-interval overlap check above. The budget may never be lowered below what is already spoken for: the new `budget_cents` must be at least the sum of current `reserved_cents` and `spent_cents`, otherwise the edit is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`.

### 3.3. Submitting a Referral: Eligibility, Identity, and the Bonus Quote

Referral submission is the densest operation in the system. The actor is either an `Employee` referring on their own behalf (the payload's `referrer_id` must equal the caller's `X-User-ID`) or a `Recruiter` submitting on behalf of a named referrer. The payload always names the target requisition via `job_requisition_id`, may carry a free-form `note`, and identifies the candidate in one of two ways: directly by `candidate_id`, or by `candidate_email`, in which case the system matches on the candidate's `normalized_email` — computed as the email lowercased and trimmed — and creates a fresh **Candidate** record from the supplied `candidate_full_name` and optional `candidate_phone` when no match exists. Supplying neither `candidate_id` nor `candidate_email` is rejected with `ERR_INVALID_REQUEST`; when both are supplied, `candidate_id` takes precedence, and when the email path matches no candidate, `candidate_full_name` is required (its absence is likewise `ERR_INVALID_REQUEST`).

Candidates themselves are registered ahead of time by a `Recruiter` or `TalentAdmin`, capturing `full_name`, `email`, optional `phone`, and optionally `prior_application_at` — the timestamp of a prior direct application outside the referral program. A candidate begins with `global_status` `AVAILABLE`; the moment any referral for them is created, the system moves them to `IN_PROCESS` — from `AVAILABLE`, and likewise from `DEPARTED` when a departed hire is referred anew — and when their last non-terminal referral reaches a terminal outcome, the system returns them to `AVAILABLE`, stamps `last_terminal_outcome_at` with the logical clock, and recomputes their `cooldown_until` (a candidate who is `HIRED` or `DEPARTED` at that moment keeps that status and is not re-stamped). Registering a candidate with a `prior_application_at` seeds `last_terminal_outcome_at` with that timestamp at creation. The `cooldown_until` itself is recomputed on every read as the result of adding the currently `ACTIVE` policy version's `duplicate_cooldown_months` calendar months (or the documented default of six months while no policy is `ACTIVE`) to `last_terminal_outcome_at`, with the day clamped to the target month's last day as described in §2.4, and it is null whenever `last_terminal_outcome_at` is null. A new referral is blocked strictly while the logical now is before `cooldown_until`; at the exact instant of `cooldown_until` the referral is allowed. Candidates may be listed with `global_status` and `hired_via_referral_id` filters, and each candidate exposes their referral history as a subordinate view.

Before any business rule runs, submission passes the generic pipeline of §2.10. The business gauntlet then executes in a fixed order — the first failure stops the pipeline and determines the error:

1. The requisition must be in `OPEN`; any other status is rejected with `ERR_REQUISITION_NOT_OPEN` (HTTP 409).
2. The referrer must not be suspended — a `referral_suspended` referrer (one whose `risk_score` is at least 100) is rejected with `ERR_REFERRER_SUSPENDED` (HTTP 422).
3. The candidate's `normalized_email` must differ from the referrer's normalized `email`. A self-referral is rejected with `ERR_SELF_REFERRAL` (HTTP 422), *and* — even though the submission fails — the system automatically raises an abuse case of `case_type` `SELF_REFERRAL` with `raised_by_user_id` set to the literal string `system`, naming the referrer.
4. The candidate must be referable: `cooldown_until` must be null or already reached, and `global_status` must not be `HIRED` — a candidate currently hired through the program is permanently blocked from new referrals. Violations are rejected with `ERR_CANDIDATE_IN_COOLDOWN` (HTTP 422).
5. No duplicate: no other referral may exist for the same `candidate_id` and the same `job_requisition_id` in any non-terminal status; otherwise `ERR_DUPLICATE_REFERRAL` (HTTP 409).
6. The referrer's `employment_status` must be `ACTIVE`; a non-active (in practice `TERMINATED`) referrer is rejected with `ERR_REFERRER_NOT_ACTIVE` (HTTP 422).
7. The referrer's `tenure_days` at the submission instant must be at least the active policy's `min_tenure_days`; otherwise `ERR_REFERRER_INELIGIBLE_TENURE` (HTTP 422). When no policy is `ACTIVE` this check is vacuous, and the submission fails instead at step 10.
8. Referrer exclusions: a referrer whose `is_recruiter` flag is true may not refer into a requisition whose `department` equals their own, and a referrer whose `job_level` is `MANAGER`, `DIRECTOR`, or `EXECUTIVE` may not refer into their own department either. Violations are rejected with `ERR_REFERRER_EXCLUDED` (HTTP 422).
9. The requisition's `referral_eligible` must be true; otherwise `ERR_ROLE_NOT_REFERRAL_ELIGIBLE` (HTTP 422).
10. An `ACTIVE` policy version must exist to pin; otherwise `ERR_NO_ACTIVE_POLICY` (HTTP 422).

When every check passes, the server stamps `submitted_at` with the logical clock, pins the active policy as `policy_version_id`, and computes the bonus quote in a pinned evaluation order where each step reads only values fixed by earlier steps:

- **Step 1 — tier base.** The `bonus_base_cents` is the tier amount for the requisition's `level`, read from the pinned policy: `tier_ic_cents` for `IC`, `tier_senior_cents` for `SENIOR`, `tier_manager_cents` for `MANAGER`, `tier_director_cents` for `DIRECTOR`, or `tier_executive_cents` for `EXECUTIVE`.
- **Step 2 — campaign attachment.** The candidate set is all campaigns whose `job_requisition_id` equals the referral's requisition, whose status is `ACTIVE`, and whose closed window contains `submitted_at` (that is, `window_start` at or before `submitted_at` and `submitted_at` at or before `window_end`). At most one such campaign can exist, because same-requisition campaign windows may not overlap. If the set is empty, the uplift is zero and `campaign_id` is null; a candidate campaign whose current attachments already number its `max_payouts` is likewise treated as absent, so the submission proceeds unattached.
- **Step 3 — uplift computation.** If a campaign attaches and the referrer's `job_level` is not `EXECUTIVE`, the raw uplift is the tier base multiplied by the campaign's `multiplier_bps` and divided by 10000, rounded half-up to whole cents at this single rounding point, minus the tier base, plus the campaign's `flat_addon_cents`; the granted `campaign_uplift_cents` is then the smaller of that raw uplift and the campaign's remaining budget at that instant (`budget_cents` minus `reserved_cents` minus `spent_cents`), floored at zero. If the referrer is an `EXECUTIVE`, the uplift is zero — executives earn the base tier only — yet the campaign still attaches and still counts toward `payouts_count`.
- **Step 4 — zero-uplift attachment.** If a campaign attaches and the granted uplift computes to zero — whether because the remaining budget was zero or the raw computation yielded nothing — the referral still attaches: `campaign_id` is set and `campaign_uplift_cents` is zero.
- **Step 5 — provisional cap headroom.** The provisional cap remaining is the pinned policy's `annual_cap_cents` minus the referrer's current `annual_provisional_cents`, evaluated before this bonus is counted.
- **Step 6 — provisional gross.** The `bonus_total_cents` is the smaller of base plus uplift and the provisional cap remaining, floored at zero.

Attachment also reserves budget: the campaign's `reserved_cents` increases by the referral's `campaign_uplift_cents`, the referral's `uplift_spent_cents` starts at zero, and the referral's `status` begins at `SUBMITTED`. The candidate moves from `AVAILABLE` to `IN_PROCESS`, and a `SUBMIT` event is appended to the referral's audit log.

Two automatic abuse detectors fire on every successful submission without blocking it. First, **velocity**: counting the referrer's referrals whose `submitted_at` falls within the closed window from seven days (604800 seconds) before the logical now up to and including now — the new referral included — the system auto-raises an abuse case of `case_type` `VELOCITY` with `raised_by_user_id` `system`, naming the new referral, whenever that count is at least the active policy's `velocity_limit`; the submission itself still succeeds. Second, **duplicate-ring detection**: counting the distinct referrers over non-terminal referrals for the same candidate with `submitted_at` inside the closed rolling ninety-day window up to and including now, the system auto-raises an abuse case of `case_type` `DUPLICATE_RING` with `raised_by_user_id` `system` against the newest referral's referrer whenever that distinct count reaches at least three.

### 3.4. From Review to Hire: The Recruiting Pipeline

Once submitted, a referral moves through the recruiting pipeline under recruiter and hiring-manager stewardship, with every move appending its event to the audit log.

A `Recruiter` picks up a `SUBMITTED` referral by moving it to `UNDER_REVIEW` (event `REVIEW`). During review the recruiter may bounce the referral to `NEEDS_INFO` (event `REQUEST_INFO`) with an optional `note`, and the referral returns to `UNDER_REVIEW` when information is provided (event `PROVIDE_INFO`) — a step open to the recruiter, and also to the `Employee`-role referrer acting on their own referral. The `UNDER_REVIEW`–`NEEDS_INFO` cycle may repeat an unlimited number of times. From `UNDER_REVIEW` the recruiter either qualifies the referral (moving it to `QUALIFIED`, event `QUALIFY`) or rejects it: rejection requires a `reason_code` of `DUPLICATE`, `PRIOR_CANDIDATE`, or `OTHER`, moving the referral to `REJECTED_DUPLICATE`, `REJECTED_PRIOR_CANDIDATE`, or `REJECTED_OTHER` respectively, recording the same value in `last_decision_reason`, releasing the referral's remaining campaign reservation, and appending the `REJECT` event with the request's optional `note`. Rejection is only defined from `UNDER_REVIEW`; attempting it from any other non-terminal state is `ERR_INVALID_STATE`, and from a terminal state `ERR_ALREADY_TERMINAL`.

Qualified referrals advance through the hiring stages via an advancement action carrying a `to_state`: from `QUALIFIED` to `SCREENING` and from `SCREENING` to `INTERVIEWING` at the hand of a `Recruiter`, and from `INTERVIEWING` to `OFFER_EXTENDED` at the hand of a `HiringManager`, each appending an `ADVANCE` event with its optional `note`. The `to_state` must be one of the three declared stage values (`SCREENING`, `INTERVIEWING`, `OFFER_EXTENDED`), and each advancement targets the immediate next stage — there is no skipping or going backward through this action. A `to_state` that does not pair with the current state as a declared advancement is rejected with `ERR_INVALID_STATE` (HTTP 409); when the pair is valid but the caller's role is not the one named for it, the rejection is `ERR_FORBIDDEN` (HTTP 403), evaluated after pair legality. When an offer is declined, the referral loops from `OFFER_EXTENDED` back to `INTERVIEWING` (event `OFFER_DECLINED`), a cycle that may repeat an unlimited number of times; the offer-decline action is available to both `Recruiter` and `HiringManager`.

The hire action belongs to the `HiringManager` and moves `OFFER_EXTENDED` to `HIRED`. It carries the actual `hire_date`, which must be at or before the logical now — a future start date is rejected with `ERR_HIRE_DATE_IN_FUTURE` — plus an optional `note`. Hiring is the system's biggest cascade, and its effects land in concert:

- The referral's `retention_due_at` and `clawback_until` are computed from the pinned policy: the retention due date is `hire_date` plus the policy's `retention_days`, and the clawback deadline is that due date plus the policy's `clawback_days`.
- The candidate moves from `IN_PROCESS` to `HIRED`, and their `hired_via_referral_id` is set to this referral.
- The requisition's `filled_count` increases by one; if it thereby equals `openings`, the requisition moves from `OPEN` to `FILLED` with the sibling `NOT_SELECTED` cascade and reservation releases described in §3.2.
- Two bonus milestones are created from the referral's `bonus_total_cents` under the pinned split: the `HIRE` milestone's `amount_cents` is the gross total multiplied by the policy's `hire_pct` and divided by 100, rounded half-up to whole cents — the hire share is rounded *first* — and it is created directly in `EARNED` status with `earned_at` stamped; the `RETENTION` milestone is created in `PENDING` with an `amount_cents` equal to the gross total minus the hire amount, so the two amounts always sum exactly to `bonus_total_cents`, the retention side absorbing the rounding.
- If a campaign is attached, the hire uplift share — the referral's `campaign_uplift_cents` multiplied by `hire_pct` and divided by 100, rounded half-up, with the retention uplift share defined as the remainder of `campaign_uplift_cents` after the hire share — moves from the campaign's `reserved_cents` into its `spent_cents`, the referral's `uplift_spent_cents` records the converted hire share, and if `spent_cents` thereby reaches `budget_cents` the campaign auto-transitions from `ACTIVE` to `EXHAUSTED`.
- A `HIRE` event is appended.

Not every story ends in a hire. A `Recruiter` may mark a referral `NOT_SELECTED` from `QUALIFIED`, `SCREENING`, or `INTERVIEWING`; from `OFFER_EXTENDED` the same decision belongs to the `HiringManager` (the action is authorized for both roles across the four states, with event `NOT_SELECTED`); a caller whose role does not own the decision for the referral's current state is rejected with `ERR_FORBIDDEN` (HTTP 403), evaluated after the state check. The referrer themselves may withdraw at any point before hire — from `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, `QUALIFIED`, `SCREENING`, `INTERVIEWING`, or `OFFER_EXTENDED` — moving the referral to `WITHDRAWN` (event `WITHDRAW`); withdrawal is restricted to the `Employee` role and only when the caller's `X-User-ID` equals the referral's `referrer_id`. Every one of these terminal outcomes releases the referral's remaining campaign reservation — precisely the portion of its `campaign_uplift_cents` not yet converted into campaign spend, that is, the difference between `campaign_uplift_cents` and `uplift_spent_cents`, subtracted from the campaign's `reserved_cents`.

Finally, referrals cannot linger forever in their earliest states. The operations sweep (§3.5) expires any referral still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` once the logical now is strictly later than `submitted_at` plus the pinned policy's `referral_expiry_days`, moving it to `EXPIRED`, releasing its campaign reservation, and appending the `EXPIRE` event. Referrals in `QUALIFIED` or later stages never expire.

### 3.5. Bonus Milestones, Retention, Departure, and Clawback

The two milestones created at hire time anchor the money flow, and a system sweep keeps time-based promises.

Each **BonusMilestone** carries its `referral_id`, a `kind` of `HIRE` or `RETENTION`, the computed `amount_cents`, and a `status` that begins at `PENDING` (or `EARNED` for the hire milestone). Earning stamps `earned_at` with the logical clock. Milestones can be listed with `referral_id`, `payroll_batch_id`, `status`, and `kind` filters, and each referral exposes its milestone list as a subordinate view.

The **operations sweep** — a `TalentAdmin`-only capability evaluated against the logical clock — performs all time-based transitions in one pass and reports tallies: `retention_earned`, `retention_failed`, `clawed_back`, `expired`, and `campaigns_ended`. Its referral-level work is threefold. First, any referral still `HIRED` whose `retention_due_at` has been reached and whose candidate is not `DEPARTED` moves to `COMPLETED`: the `RETENTION` milestone transitions from `PENDING` to `EARNED` with `earned_at` stamped, the retention uplift share (the referral's `campaign_uplift_cents` minus the hire share) moves from campaign `reserved_cents` to `spent_cents` — auto-exhausting the campaign if `spent_cents` reaches `budget_cents` — and a `RETENTION_MET` event is appended. Second, any referral still `HIRED` whose candidate is `DEPARTED` with a `departed_at` earlier than `retention_due_at` moves to `RETENTION_FAILED`: the `RETENTION` milestone transitions from `PENDING` to `FORFEITED`, the remaining campaign reservation is released, the `HIRE` milestone is explicitly *not* clawed back (the hire bonus was earned at hire), and a `RETENTION_FAILED` event is appended. Third, the sweep expires stale early-stage referrals and ends elapsed campaigns exactly as described in §3.4 and §3.2.

Departures enter the system when a `Recruiter` (or `TalentAdmin`) records that a hired candidate left the company, supplying `terminated_at`; the candidate must currently be `HIRED`, and the record moves them to `DEPARTED` with `departed_at` set from the payload. The departure itself changes nothing about money immediately — retention failure and clawback consequences are applied by the *next* sweep, which reads the now-`DEPARTED` status.

Clawback is the sweep's third milestone-level duty. When a candidate is `DEPARTED` with `departed_at` earlier than the referral's `clawback_until`, and the referral's `RETENTION` milestone is `PAID`, that milestone transitions to `CLAWED_BACK`: its `recovery_status` is set to `PENDING` (money is owed back), the retention uplift share is released from the campaign's `spent_cents` (which, on an `EXHAUSTED` campaign, may flip it back to `ACTIVE`), and the referrer's annual accumulators register the change purely through the new status — the milestone ceases to be summed as `PAID` and its `amount_cents` is instead subtracted as a `CLAWED_BACK` milestone, exactly as the accumulator definitions that follow prescribe.

Those annual accumulators deserve a precise definition, since both the submission quote and the approval gate read them. Consider all of a referrer's milestones — joined through their referrals' `referrer_id` — whose `earned_at` falls inside the current calendar year (from January 1 00:00:00 inclusive to the next January 1 00:00:00 exclusive). The `annual_provisional_cents` accumulator sums the `amount_cents` of milestones in `EARNED`, `APPROVED`, `BATCHED`, or `PAID` status, then subtracts the `amount_cents` of milestones in `CLAWED_BACK`. The `annual_committed_cents` accumulator is the same computation over the narrower lens of `APPROVED`, `BATCHED`, and `PAID`, again subtracting `CLAWED_BACK`. `FORFEITED` milestones contribute zero to both, and both accumulators are recomputed whenever a milestone changes status.

### 3.6. Payroll: Approval, Withholding, Batching, and Payment Confirmation

An earned milestone becomes spendable only after a `PayrollProcessor` approves it, moving it from `EARNED` to `APPROVED`. Approval enforces two business gates, evaluated in this order: first the annual cap — the referrer's `annual_committed_cents` plus this milestone's `amount_cents` must not exceed the `annual_cap_cents` of the referral's pinned policy, otherwise `ERR_ANNUAL_CAP_EXCEEDED` (HTTP 422) — and then the tax gate — the referrer's tax profile must exist and be in `VERIFIED` status, otherwise `ERR_TAX_PROFILE_NOT_VERIFIED` (HTTP 422). On success the milestone's withholding is computed and *locked* at that instant, and `approved_by_user_id` records the approver.

Withholding follows one of two variants, selected by the referrer's `withholding_method`. Both variants first establish the cumulative base as the profile's `ytd_carryover_cents` plus its `ytd_paid_gross_cents`, evaluated at the approval instant — which means the order in which milestones are approved matters for the second variant. Under `FLAT`, the rate is the profile's `supplemental_rate_bps` when set, else the default 2200 basis points, and the `withholding_cents` is the milestone's `amount_cents` multiplied by that rate and divided by 10000, rounded half-up to whole cents. Under `AGGREGATE`, the system applies a progressive bracket over cumulative referral wages: the bracket tax on an amount is fifteen percent of the amount while the amount is at least zero and below 500000 cents; 75000 cents plus twenty-five percent of the excess over 500000 cents while the amount is at least 500000 and below 1500000 cents; and 325000 cents plus thirty-five percent of the excess over 1500000 cents once the amount reaches 1500000 cents — each bracket's lower bound inclusive. The milestone's `withholding_cents` is then the bracket tax on the cumulative base plus this milestone's amount, minus the bracket tax on the cumulative base alone, rounded half-up to whole cents; the same milestone amount can therefore withhold differently depending on year-to-date totals and on approval order. Either way, `net_cents` is `amount_cents` minus `withholding_cents`.

Payment runs through **PayrollBatch** resources. A `PayrollProcessor` creates a batch with a `period_label` (for example `2026-08A`); it starts `OPEN`. Attaching a milestone to an open batch carries the `milestone_id` and, per §2.7, the mandatory `expected_payroll_batch_version`. The batch must be `OPEN` — milestone add and milestone remove on any non-`OPEN` batch are rejected with `ERR_BATCH_NOT_OPEN` (HTTP 409) — and the milestone must be attachable: either `APPROVED` (a positive payout line) or `CLAWED_BACK` with `recovery_status` `PENDING` (a negative recovery line); a milestone in any other status, or one already attached to a batch, is rejected with `ERR_MILESTONE_NOT_BATCHABLE` (HTTP 409). On milestone add, the body-named milestone's existence is verified only after the stale-version and batch-open checks; on milestone remove, the milestone is a path segment validated left-to-right per §2.9, and a milestone that exists but is not attached to this batch is rejected with `ERR_MILESTONE_NOT_BATCHABLE`. Attaching an approved milestone moves it from `APPROVED` to `BATCHED` and sets its `payroll_batch_id`; attaching a recovery line links it without changing its `CLAWED_BACK` status. Either way the batch totals recompute and the batch `version` increments. Removing a milestone — again guarded by `expected_payroll_batch_version` — returns a `BATCHED` milestone to `APPROVED` and clears its `payroll_batch_id`, while an attached recovery line detaches unchanged (still `CLAWED_BACK` with recovery `PENDING`); totals recompute and the batch `version` increments again.

Batch totals are derived, and they are exact: `total_gross_cents` is the sum of `amount_cents` over attached `BATCHED` milestones minus the `amount_cents` of attached `CLAWED_BACK` recovery lines; `total_withholding_cents` sums `withholding_cents` over the attached `BATCHED` milestones; `total_net_cents` is gross minus withholding; and `milestone_count` counts all attached lines, payout and recovery alike.

A `PayrollProcessor` seals an `OPEN` batch (moving it to `SEALED`, after which no further milestone add or remove is allowed), then exports it (moving it to `EXPORTED`), with milestones exported in a deterministic order: `earned_at` ascending, with ties broken by the owning referral's `created_at` ascending. Payment is then *confirmed* by a `TalentAdmin` — a deliberate segregation of duties, since the processor who prepared and approved the batch may not confirm it — moving the batch to `CONFIRMED_PAID`, transitioning every attached `BATCHED` milestone to `PAID` (accumulating each referrer's `ytd_paid_gross_cents` by the milestone's `amount_cents` for the calendar year), and flipping every attached recovery line's `recovery_status` to `RECOVERED`. Milestones that become `PAID` have their `payroll_batch_id` cleared — the batch link is carried only while `BATCHED` — while recovery lines keep their `payroll_batch_id` link to the confirmed batch. A batch that is still `OPEN` may instead be cancelled by the `PayrollProcessor`: every attached `BATCHED` milestone returns to `APPROVED` detached, and every attached recovery line stays `CLAWED_BACK` with recovery `PENDING`, likewise detached. `CONFIRMED_PAID` and `CANCELLED` are terminal. Batches may be listed with a `status` filter.

Milestones can also be forfeited directly: a `PayrollProcessor` or `ComplianceOfficer` may forfeit a milestone in `EARNED` or `APPROVED` status by supplying a `reason`, moving it to `FORFEITED` and releasing the corresponding earned campaign share — the hire uplift share for a `HIRE` milestone, the retention uplift share for a `RETENTION` milestone — from the attached campaign's `spent_cents`. A `BATCHED` milestone is forfeited only through the systematic cascades — referrer termination or abuse confirmation — never through this manual action; those cascades detach it from its batch, recompute totals, and increment the batch `version`, exactly as in §3.1.

### 3.7. Abuse Detection, Risk Scoring, and Compliance Decisions

The program polices itself through **AbuseCase** records. A case names the subject employee via `employee_id`, optionally the referral that evidenced the abuse via `referral_id`, and a `case_type` of `SELF_REFERRAL`, `VELOCITY`, `DUPLICATE_RING`, `RESUME_FARM`, or `MANUAL`. Cases are raised manually by a `Recruiter`, `TalentAdmin`, or `ComplianceOfficer` — with an optional `note`, and `raised_by_user_id` stamped from the caller's `X-User-ID` — or automatically by the system for the self-referral, velocity, and duplicate-ring detectors of §3.3, in which case `raised_by_user_id` is the literal string `system`. Each case carries a computed `risk_weight`: 40 for `SELF_REFERRAL`, 25 for `VELOCITY`, 35 for `DUPLICATE_RING`, 50 for `RESUME_FARM`, and 20 for `MANUAL`. Cases may be listed with `employee_id`, `referral_id`, `status`, and `case_type` filters, and each employee exposes the cases naming them as a subordinate view visible to `PlatformAdmin`, `TalentAdmin`, and `ComplianceOfficer`.

A case starts `OPEN`; a `ComplianceOfficer` may move it to `UNDER_REVIEW` to signal active investigation, and from either `OPEN` or `UNDER_REVIEW` the officer reaches a verdict. Both verdicts enforce segregation of duties: the deciding officer's `X-User-ID` must differ from the case's `raised_by_user_id`, otherwise the attempt is rejected with `ERR_SOD_VIOLATION` (HTTP 403) — no one decides a case they raised. Confirming a case stamps `confirmed_at` with the logical clock, records `decided_by_user_id`, accepts an optional `resolution_note`, and unleashes the full cascade: the employee's `fraud_strikes` increases by one; their `risk_score` is recomputed (below) and the employee becomes `referral_suspended` if the score reaches at least 100; and if the case names a `referral_id` whose referral is still non-terminal — in any state from `SUBMITTED` through `HIRED` — that referral cascades to `FORFEITED` with `last_decision_reason` `ABUSE_CONFIRMED`: its milestones in `PENDING`, `EARNED`, `APPROVED`, or `BATCHED` move to `FORFEITED` (a `BATCHED` milestone first detaching from its batch with totals recomputing and the batch `version` incrementing), its remaining campaign reservation is released, its earned-but-unpaid uplift shares are released from `spent_cents`, and a `FORFEIT` event is appended, recorded with actor `system` as an automatic cascade. Milestones already `PAID` remain `PAID` even in this cascade — recovery of paid money happens only through the clawback path of §3.5. Dismissing a case, from `OPEN` or `UNDER_REVIEW`, records `decided_by_user_id` and the optional `resolution_note` with no risk-score impact at all. `CONFIRMED` and `DISMISSED` are terminal.

The `risk_score` itself is a decayed weighted sum over the employee's `CONFIRMED` cases, recomputed on every confirmation and on every read of the employee. Each confirmed case contributes its `risk_weight` multiplied by one half raised to the power of its age in half-lives: the case's age is the whole days between `confirmed_at` and the logical now (elapsed seconds divided by 86400 and rounded down), divided by 180 using real division, and one half is raised to that quotient. The contributions are summed, the total is rounded half-up to an integer, and the score is capped at 500. Whenever the score is at least 100, the employee's `referral_suspended` flag is true, and — as §3.3's gauntlet establishes — any referral submission by that employee is rejected with `ERR_REFERRER_SUSPENDED`. Because contributions decay with a 180-day half-life, a suspension can lift with the passage of logical time.

### 3.8. Measuring Channel Quality: Program Analytics

The program closes the loop with a source-quality analytics report, available to `TalentAdmin` and `Recruiter`. The request selects a grouping dimension via `group_by` — `REFERRER_LEVEL` groups referrals by their referrer's `job_level`, `REQ_DEPARTMENT` groups by the requisition's `department`, and `CAMPAIGN` groups by whether a campaign was attached or not — and may bound the analysis with `window_start` and `window_end`, both inclusive; omitted, the window runs from the beginning of time up to the logical now. Only referrals whose `submitted_at` falls inside the window count.

Each group in the returned `groups` array reports: `group`, the group's key (for `CAMPAIGN` the keys are `ATTACHED` and `NOT_ATTACHED`); `submissions`, the count of referrals in the group; `hires`, the count that ever reached `HIRED` — identified by a recorded `hire_date`, so referrals now in `COMPLETED`, `RETENTION_FAILED`, or even `FORFEITED` after an abuse confirmation also count; `retention_met`, the count currently in `COMPLETED`; `hire_rate_raw`, the hires divided by the submissions (zero when the group has no submissions); `hire_rate_adjusted`, a beta-smoothed rate computed as hires plus 5 divided by submissions plus 10, which diverges from the raw rate most sharply on small samples; `low_confidence`, true whenever the group's submissions number fewer than 10; and `total_bonus_paid_cents`, the sum of `PAID` milestone amounts across the group's referrals. Both rates are decimal fractions rounded half-up to six decimal places. Groups with zero submissions are omitted from the output entirely, and the surviving groups are returned sorted by their key in ascending order. A missing `group_by` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), as is an unparseable `window_start` or `window_end`.

## 4. Endpoint Definitions

Operations that create new stand-alone resources — employees, candidates, requisitions, policy versions, campaigns, referrals, payroll batches, and abuse cases — return a `201 Created` status code. All other successful operations, including lifecycle actions, state transitions, upserts, the clock capability, and the operations sweep, return `200 OK`. List endpoints accept the filter query parameters discussed throughout §3 (for example `status`, `department`, `job_level`, `employment_status`, `global_status`, `hired_via_referral_id`, `filled_by_candidate_id`, `referrer_id`, `candidate_id`, `job_requisition_id`, `campaign_id`, `policy_version_id`, `kind`, `payroll_batch_id`, `employee_id`, `case_type`, and `referral_id`) in addition to the `limit` and `offset` pagination parameters of §2.3; subordinate list views (a requisition's referrals and campaigns, a candidate's referrals, an employee's referrals and abuse cases) accept a `status` filter; the `Employee` role's list of referrals is always scoped to its own records.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/erp/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | PlatformAdmin |
| POST | `/erp/_ops/evaluate` | Run the operations sweep against the logical clock | TalentAdmin |
| POST | `/erp/employees` | Create an employee | PlatformAdmin |
| GET | `/erp/employees` | List employees | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| GET | `/erp/employees/{id}` | Get one employee (computed fields included) | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| POST | `/erp/employees/{id}/terminate` | Terminate an employee; forfeits unpaid milestones (cascade) | PlatformAdmin |
| PUT | `/erp/employees/{id}/tax-profile` | Create-or-update the employee's 1:1 tax profile; any update resets it to SUBMITTED | Employee, PayrollProcessor |
| POST | `/erp/employees/{id}/tax-profile/verify` | Verify a submitted tax profile | PayrollProcessor |
| GET | `/erp/employees/{id}/tax-profile` | Get the employee's tax profile (array of 0..1) | Employee, PayrollProcessor, TalentAdmin |
| GET | `/erp/employees/{id}/referrals` | List referrals submitted by this employee | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| GET | `/erp/employees/{id}/abuse-cases` | List abuse cases naming this employee | PlatformAdmin, TalentAdmin, ComplianceOfficer |
| POST | `/erp/candidates` | Register a candidate (records a prior direct application when given) | Recruiter, TalentAdmin |
| GET | `/erp/candidates` | List candidates | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer |
| GET | `/erp/candidates/{id}` | Get one candidate | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer |
| GET | `/erp/candidates/{id}/referrals` | List referrals for this candidate | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, ComplianceOfficer |
| POST | `/erp/candidates/{id}/record-departure` | Record that a hired candidate left the company | Recruiter, TalentAdmin |
| POST | `/erp/job-requisitions` | Create a requisition (starts DRAFT) | TalentAdmin |
| GET | `/erp/job-requisitions` | List requisitions | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| GET | `/erp/job-requisitions/{id}` | Get one requisition | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| POST | `/erp/job-requisitions/{id}/open` | Open a DRAFT requisition | TalentAdmin |
| POST | `/erp/job-requisitions/{id}/pause` | Pause an OPEN requisition | TalentAdmin |
| POST | `/erp/job-requisitions/{id}/resume` | Resume a PAUSED requisition | TalentAdmin |
| POST | `/erp/job-requisitions/{id}/cancel` | Cancel a DRAFT/OPEN/PAUSED requisition; NOT_SELECTs its non-terminal referrals | TalentAdmin |
| GET | `/erp/job-requisitions/{id}/referrals` | List referrals for this requisition | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, ComplianceOfficer |
| GET | `/erp/job-requisitions/{id}/campaigns` | List campaigns covering this requisition | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, ComplianceOfficer |
| POST | `/erp/policy-versions` | Create a policy version (DRAFT); omitted rule fields take the documented defaults | TalentAdmin |
| GET | `/erp/policy-versions` | List policy versions | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer |
| GET | `/erp/policy-versions/{id}` | Get one policy version | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer |
| POST | `/erp/policy-versions/{id}/activate` | Activate a DRAFT policy; supersedes the currently ACTIVE one | TalentAdmin |
| POST | `/erp/policy-versions/{id}/retire` | Retire a DRAFT policy | TalentAdmin |
| POST | `/erp/campaigns` | Create a campaign (DRAFT); closed-window overlap check against same-requisition campaigns | TalentAdmin |
| GET | `/erp/campaigns` | List campaigns | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer |
| GET | `/erp/campaigns/{id}` | Get one campaign | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer |
| PATCH | `/erp/campaigns/{id}` | Edit a DRAFT/ACTIVE/PAUSED campaign (OCC-guarded); budget floor and window overlap enforced | TalentAdmin |
| POST | `/erp/campaigns/{id}/activate` | Activate a DRAFT or PAUSED campaign | TalentAdmin |
| POST | `/erp/campaigns/{id}/pause` | Pause an ACTIVE campaign | TalentAdmin |
| POST | `/erp/campaigns/{id}/end` | End (cancel) a campaign from any non-terminal state; releases outstanding reservations | TalentAdmin |
| POST | `/erp/referrals` | Submit a referral: identify the candidate by id or email, pin the active policy, attach a covering campaign, compute the bonus quote | Employee, Recruiter |
| GET | `/erp/referrals` | List referrals with filters (Employee role sees only own) | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| GET | `/erp/referrals/{id}` | Get one referral | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| POST | `/erp/referrals/{id}/review` | Move SUBMITTED to UNDER_REVIEW | Recruiter |
| POST | `/erp/referrals/{id}/request-info` | Move UNDER_REVIEW to NEEDS_INFO | Recruiter |
| POST | `/erp/referrals/{id}/provide-info` | Move NEEDS_INFO to UNDER_REVIEW | Recruiter, Employee |
| POST | `/erp/referrals/{id}/qualify` | Move UNDER_REVIEW to QUALIFIED | Recruiter |
| POST | `/erp/referrals/{id}/reject` | Move UNDER_REVIEW to REJECTED_DUPLICATE / REJECTED_PRIOR_CANDIDATE / REJECTED_OTHER by reason code | Recruiter |
| POST | `/erp/referrals/{id}/advance` | Advance through hiring stages: QUALIFIED to SCREENING to INTERVIEWING to OFFER_EXTENDED | Recruiter, HiringManager |
| POST | `/erp/referrals/{id}/offer-declined` | Move OFFER_EXTENDED back to INTERVIEWING (declined offer loop) | Recruiter, HiringManager |
| POST | `/erp/referrals/{id}/hire` | Move OFFER_EXTENDED to HIRED; creates milestones, settles the campaign hire share, may fill the requisition | HiringManager |
| POST | `/erp/referrals/{id}/not-selected` | Move QUALIFIED/SCREENING/INTERVIEWING/OFFER_EXTENDED to NOT_SELECTED | Recruiter, HiringManager |
| POST | `/erp/referrals/{id}/withdraw` | Referrer withdraws an in-flight referral (any non-terminal state before HIRED) | Employee |
| GET | `/erp/referrals/{id}/milestones` | List the referral's bonus milestones | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| GET | `/erp/referrals/{id}/events` | List the referral's append-only event log | PlatformAdmin, TalentAdmin, Recruiter, HiringManager, PayrollProcessor, ComplianceOfficer, Employee |
| GET | `/erp/milestones` | List milestones with filters | PlatformAdmin, TalentAdmin, Recruiter, PayrollProcessor, ComplianceOfficer |
| GET | `/erp/milestones/{id}` | Get one milestone | PlatformAdmin, TalentAdmin, Recruiter, PayrollProcessor, ComplianceOfficer |
| POST | `/erp/milestones/{id}/approve` | Approve an EARNED milestone; locks withholding per the referrer's tax profile; enforces the annual cap | PayrollProcessor |
| POST | `/erp/milestones/{id}/forfeit` | Manually forfeit an EARNED or APPROVED milestone | PayrollProcessor, ComplianceOfficer |
| POST | `/erp/payroll-batches` | Create a payroll batch (OPEN) | PayrollProcessor |
| GET | `/erp/payroll-batches` | List payroll batches | PlatformAdmin, TalentAdmin, PayrollProcessor |
| GET | `/erp/payroll-batches/{id}` | Get one payroll batch | PlatformAdmin, TalentAdmin, PayrollProcessor |
| POST | `/erp/payroll-batches/{id}/milestones` | Attach an APPROVED milestone or a CLAWED_BACK recovery line to an OPEN batch (OCC-guarded) | PayrollProcessor |
| POST | `/erp/payroll-batches/{id}/milestones/{milestone_id}/remove` | Detach a milestone from an OPEN batch (OCC-guarded) | PayrollProcessor |
| POST | `/erp/payroll-batches/{id}/seal` | Seal an OPEN batch | PayrollProcessor |
| POST | `/erp/payroll-batches/{id}/export` | Export a SEALED batch in deterministic milestone order | PayrollProcessor |
| POST | `/erp/payroll-batches/{id}/confirm-paid` | Confirm payment of an EXPORTED batch (TalentAdmin confirms what PayrollProcessor prepared) | TalentAdmin |
| POST | `/erp/payroll-batches/{id}/cancel` | Cancel an OPEN batch; attached milestones return to APPROVED / recovery PENDING | PayrollProcessor |
| POST | `/erp/abuse-cases` | Raise an abuse case against an employee (manual); auto-cases are raised by the system | Recruiter, TalentAdmin, ComplianceOfficer |
| GET | `/erp/abuse-cases` | List abuse cases | PlatformAdmin, TalentAdmin, ComplianceOfficer |
| GET | `/erp/abuse-cases/{id}` | Get one abuse case | PlatformAdmin, TalentAdmin, ComplianceOfficer |
| POST | `/erp/abuse-cases/{id}/start-review` | Move OPEN to UNDER_REVIEW | ComplianceOfficer |
| POST | `/erp/abuse-cases/{id}/confirm` | Confirm a case: strikes, risk-score recompute, possible suspension, referral FORFEIT cascade | ComplianceOfficer |
| POST | `/erp/abuse-cases/{id}/dismiss` | Dismiss a case (no risk impact) | ComplianceOfficer |
| GET | `/erp/analytics/source-quality` | Source-quality analytics grouped by referrer level, requisition department, or campaign attachment | TalentAdmin, Recruiter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_REQUISITION_NOT_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_REFERRER_SUSPENDED` | 422 |
| `ERR_SELF_REFERRAL` | 422 |
| `ERR_CANDIDATE_IN_COOLDOWN` | 422 |
| `ERR_DUPLICATE_REFERRAL` | 409 |
| `ERR_REFERRER_NOT_ACTIVE` | 422 |
| `ERR_REFERRER_INELIGIBLE_TENURE` | 422 |
| `ERR_REFERRER_EXCLUDED` | 422 |
| `ERR_ROLE_NOT_REFERRAL_ELIGIBLE` | 422 |
| `ERR_NO_ACTIVE_POLICY` | 422 |
| `ERR_POLICY_WINDOW_CONFLICT` | 409 |
| `ERR_CAMPAIGN_WINDOW_CONFLICT` | 409 |
| `ERR_CAMPAIGN_WINDOW_EXPIRED` | 422 |
| `ERR_HIRE_DATE_IN_FUTURE` | 422 |
| `ERR_CAMPAIGN_BUDGET_EXCEEDED` | 422 |
| `ERR_ANNUAL_CAP_EXCEEDED` | 422 |
| `ERR_TAX_PROFILE_NOT_VERIFIED` | 422 |
| `ERR_BATCH_NOT_OPEN` | 409 |
| `ERR_MILESTONE_NOT_BATCHABLE` | 409 |

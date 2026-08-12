# Corporate Wellness Incentives API — Product Requirements Document

## 1. Introduction

Employers increasingly sponsor wellness programs that tie real money — premium differentials, surcharge waivers, and vendor fees — to verified employee health activity. Running such a program fairly requires far more than counting steps: eligibility must be tracked across a heterogeneous population, health-risk questionnaires and biometric screenings must feed a verified-activity pipeline, provisional point earnings must be reconciled against a settled ledger before any dollar figure is committed, and federal-style fairness rules (reasonable-alternative standards, tobacco-cessation waivers, de-identified reporting with minimum cohort sizes) must be enforced mechanically rather than by policy memo. This document specifies the Corporate Wellness Incentives API, a multi-tenant platform on which benefits teams operate exactly such programs.

The API covers the full operating loop: employer onboarding and employee population management; program configuration with tiered point thresholds and capped awards; enrollment with independent participation and verification state axes; health risk assessment and kiosk-based biometric screening; challenge definition, device and app synchronization with idempotent ingestion, and a dual-view points ledger; incentive award computation under both the standard and reasonable-alternative variants, with an employee dispute loop; coaching referrals with automatic risk-driven creation and a re-referral cycle; segregation-of-duties-controlled vendor invoicing; and privacy-preserving aggregate reporting. All resources are mounted under the `/wellness` prefix, and all business timing is driven by a controllable logical clock so that plan-year windows, challenge windows, and appeal deadlines are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `PlatformAdmin`, `BenefitsAdmin`, `Employee`, `Coach`, and `VendorManager`. A request that arrives without valid headers, or whose role value is not one of these declared role names, is rejected with `ERR_UNAUTHENTICATED`. Access to specific operations is further restricted by role; an attempt to perform an action outside of the caller's designated role is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee — most importantly an Enrollment, which carries the acting member's identity through its `employee_id` — compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`. When `X-User-Role` is `PlatformAdmin`, `BenefitsAdmin`, `Coach`, or `VendorManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `assigned_coach_id` on a CoachingReferral when a Coach engages, or as `submitted_by` on a VendorInvoice when a VendorManager submits — and may later compare a caller's `X-User-ID` against such a recorded value, but it never compares it to any entity's `id`. A `Coach` in particular acts only on referrals to which they are currently assigned: the engaging coach's identifier becomes the referral's `assigned_coach_id`, and subsequent session logging and discharge compare the caller's `X-User-ID` to that recorded value.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — Employer, Employee, WellnessProgram, Enrollment, BiometricScreening, Challenge, ChallengeParticipation, PointsLedgerEntry, IncentiveAward, CoachingReferral, VendorInvoice, and AggregateReport — carries a standard set of system-managed fields:

- **`id` (string):** A unique, system-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-05-01T00:00:00.000Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. This field is refreshed upon any change to the resource's properties, including recomputation of derived fields.
- **`version` (integer):** A system-managed integer that increments by exactly one with every modification to the resource. This field underpins optimistic concurrency control where a write endpoint declares it.

Two resource types are deliberately lighter: a HealthAssessment and an ActivityEvent are immutable scoring and ingestion records, and each carries only `id` and `created_at`. Neither `updated_at` nor `version` exists on these two resources, and no write endpoint mutates them after creation.

Any mutation of a resource — an explicit state transition, a cascade originating elsewhere, or the recomputation of a derived balance — refreshes that resource's `updated_at` and increments its `version` by one. All cascades and recomputations are applied immediately: every effect described in this document is visible within the same request/response cycle that triggered it.

### 2.5. The Logical Clock and Time-Driven Sweeps

All business timing in the platform reads a single logical clock, never the wall clock. Before it is ever advanced, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `now` value.

Advancing the logical clock applies a deterministic time sweep across the fleet. Every Challenge in `PUBLISHED` status whose `starts_at` is on or before the new current instant transitions to `ACTIVE`. Every Challenge in `ACTIVE` status whose `ends_at` is strictly earlier than the new current instant transitions to `COMPLETED`, resolving each still-`JOINED` participation exactly as the challenge-completion rules in §3.5 describe. Every BiometricScreening still `SCHEDULED` whose `slot_end` is strictly earlier than the new current instant transitions to `NO_SHOW`. Because plan-year membership, activity windows, dispute deadlines, and termination timestamps all read this same logical clock, no behavior in the system ever depends on real elapsed time.

### 2.6. Request Evaluation Order

When a single request violates several rules, the platform does not choose an error arbitrarily. Every request is evaluated against the following ordered sequence, and the earliest failing stage determines the reported error:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is a declared role name; otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The role is permitted on this endpoint per §4; otherwise `ERR_FORBIDDEN`.
3. **Existence and schema.** Path resource identifiers exist, validated left to right, and the request body satisfies the endpoint's input schema — required fields present, values well-formed, enum members valid, and any end-after-start ordering respected; foreign-key fields in the body reference existing resources. Missing path resources yield `ERR_NOT_FOUND`; body-schema failures yield `ERR_INVALID_REQUEST`. Path-existence failures outrank body-schema failures.
4. **Optimistic concurrency.** Where a write endpoint declares an expected parent version, `ERR_STALE_VERSION` is reported for a mismatch (see §2.7).
5. **Identity scope.** Entity-backed identity scoping — an Employee acting only on resources derived from their own enrollment, a Coach only on referrals they are assigned to; otherwise `ERR_OWNERSHIP_MISMATCH`.
6. **State legality.** The target resource is in a valid from-state for the requested transition; otherwise the state-family error applies — `ERR_INVALID_STATE` generically, or the specific `ERR_ENROLLMENT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_NOT_CLOSED`, `ERR_AWARD_NOT_CONFIRMABLE`, or `ERR_INVOICE_NOT_EDITABLE` where the workflow names one.
7. **Privacy and duty safeguards.** Cohort k-anonymity (`ERR_COHORT_TOO_SMALL`) and segregation of duties on invoice approval (`ERR_SOD_VIOLATION`).
8. **Uniqueness, overlap, and capacity.** Program window overlap (`ERR_PROGRAM_WINDOW_OVERLAP`), challenge window overlap (`ERR_CHALLENGE_WINDOW_OVERLAP`), kiosk capacity (`ERR_KIOSK_CAPACITY_EXCEEDED`), idempotency-key conflicts (`ERR_DUPLICATE_EVENT`), duplicate participation (`ERR_PARTICIPATION_EXISTS`), duplicate health assessment (`ERR_HRA_ALREADY_COMPLETED`), and the coaching-sessions prerequisite (`ERR_REFERRAL_SESSIONS_INSUFFICIENT`).
9. **Temporal windows.** Activity `occurred_at` inside the plan year and not in the future (`ERR_EVENT_OUTSIDE_WINDOW`), screening slots inside the plan year (`ERR_SLOT_OUTSIDE_WINDOW`), and award disputes inside the appeal window (`ERR_APPEAL_WINDOW_CLOSED`).
10. **Referential lifecycle.** Referenced entities are in a compatible lifecycle relation — no new dependent artifacts against a `SETTLED` program (`ERR_PROGRAM_ALREADY_SETTLED`), and challenge and enrollment belonging to the same program (`ERR_CHALLENGE_PROGRAM_MISMATCH`).
11. **Fiscal guard.** Invoice totals within the approval limit unless explicitly overridden (`ERR_INVOICE_EXCEEDS_LIMIT`).

A consequence worth internalizing: an invoice approval that violates both segregation of duties and the spending limit reports `ERR_SOD_VIOLATION`, because stage 7 is evaluated before stage 11.

### 2.7. Optimistic Concurrency Control

Two write endpoints in the platform carry optimistic concurrency control, and only those two. Each requires a non-optional expected-version field that carries the version of the parent entity as the client last observed it; if that value does not match the parent entity's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.

Posting a manual points adjustment against an Enrollment requires `expected_enrollment_version` matching that enrollment's current `version`. If another writer has advanced the enrollment's version since the client last read it — by posting an adjustment of their own, or via any cascade that recomputed the enrollment's balances — the adjustment is rejected with `ERR_STALE_VERSION`.

Editing a `DRAFT` Challenge requires `expected_challenge_version` matching that challenge's current `version`. If another writer has advanced the challenge's version since the client last observed it, the edit is rejected with `ERR_STALE_VERSION`.

Endpoints not named above do not take a version field at all.

### 2.8. The Dual-View Points Ledger

Every point a member earns, is granted, or has adjusted flows through the PointsLedgerEntry resource, and the ledger is the single source of truth from which both enrollment balances are derived. A ledger entry carries a `kind` — `EARNED` for points converted from an accepted activity event, `BONUS` for a challenge-completion reward, and `ADJUSTED` for a manual correction — together with a signed `points_delta`, a free-text `reason` (required when the kind is `ADJUSTED`), a `source_activity_event_id` that is populated only for `EARNED` entries and null otherwise, and a `status` of `PROVISIONAL`, `POSTED`, or `EXPIRED`. `EARNED` and `BONUS` entries are always positive and begin life `PROVISIONAL`; `ADJUSTED` entries are signed and are created directly in `POSTED` status.

From this ledger two balances are recomputed on every entry creation or status transition affecting the enrollment. The `points_balance_settled` sums the `points_delta` of entries in `POSTED` status only; it is the authoritative figure for award computation and for program close and settle. The `points_balance_provisional` sums entries in either `PROVISIONAL` or `POSTED` status; it is the in-year working figure that drives challenge progress views and projected tiers, and it equals the settled figure plus not-yet-finalized activity, so identical event data yields a smaller-or-equal settled number whenever any provisional entry exists. `EXPIRED` entries contribute to neither balance. Ledger entries are never created directly through a dedicated endpoint: they originate only from activity-event ingestion, challenge completion, and manual adjustments.

### 2.9. Money, Rates, and Rounding Discipline

All monetary values are integer cents — premium bases, surcharges, vendor fees, award amounts, and invoice lines alike. Points are integers as well, and every division in points conversion rounds down to a whole number.

Two rounding rules are pinned and must not be re-interpreted. First, the premium cap product — the program's `premium_cap_pct` multiplied by the employer's `annual_self_only_premium_cents` — is rounded half-up to whole cents, and each aggregate report's `avg_settled_points` is rounded half-up to two decimal places while `participation_rate` and `tobacco_rate` are rounded half-up to four decimal places. Second, vendor invoice rounding is per-line: every member-month line is individually rounded half-up to integer cents before any summation, and `total_cents` is the exact sum of the already-rounded line amounts. The alternative — summing unrounded prorations and rounding once at the end — is explicitly rejected and yields different cents.

### 2.10. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers, the system validates the existence of each identifier in a sequential, left-to-right order, and rejects the request immediately with `ERR_NOT_FOUND` for the first identifier that does not correspond to an existing resource. Foreign-key references carried in request bodies — such as the `employer_id` on a new employee or the `program_id` on a new enrollment — must likewise reference existing resources.

### 2.11. Privacy Safeguards and Segregation of Duties

Two compliance guards cut across otherwise ordinary workflows and are enforced at evaluation stage 7 (see §2.6).

De-identified aggregate reporting is gated by k-anonymity. Every employer declares a `k_anonymity_threshold`, the minimum cohort size for which a report may be generated. If the computed cohort is smaller than this threshold, report generation is refused with `ERR_COHORT_TOO_SMALL` and no report record is persisted at all; a cohort whose size is exactly the threshold is publishable.

Vendor billing is gated by segregation of duties. The operator who submits an invoice is recorded as its `submitted_by`, and the `PlatformAdmin` who approves it must be a different operator: when the approver's `X-User-ID` equals the invoice's `submitted_by`, the approval is rejected with `ERR_SOD_VIOLATION`. A `VendorManager` may draft, adjust, submit, and revise invoices but may never approve one.

## 3. Business Logic & Workflows

### 3.1. Employer Onboarding and the Member Population

Everything begins with the employer tenant. A `PlatformAdmin` creates an Employer with its legal `name` and the eight financial and policy parameters that govern everything downstream: `annual_self_only_premium_cents`, the annual self-only medical premium that forms the basis of the award cap; `tobacco_surcharge_cents`, the annual surcharge applied when tobacco use is attested and not waived; `pmpm_fee_cents`, the vendor per-member-per-month fee for a full month; `coaching_session_fee_cents`, the vendor fee per coaching session; `k_anonymity_threshold`, the minimum cohort size for de-identified reporting; `kiosk_capacity`, the maximum number of overlapping biometric-screening appointments permitted per clinic location; and `invoice_approval_limit_cents`, above which invoice approvals demand an explicit override.

With a tenant in place, a `BenefitsAdmin` builds the member population. Each Employee record carries the `employer_id` of its tenant, a work `email` that must be unique within that employer, the member's `full_name`, a `department` code that later serves as the report cohort filter, a `hire_date` in ISO date form, and a `tobacco_attested` flag capturing self-attested tobacco use, which defaults to false when omitted. Employer and employee directories are readable back through the employer's employee listing and the employee record itself.

### 3.2. Program Configuration and the Plan-Year Lifecycle

A `BenefitsAdmin` shapes each plan year by creating a WellnessProgram under an `employer_id`. The program's `name` is display text; its semantics live in the plan-year window and the tier schedule. The window is half-open: `plan_year_start` is inclusive, `plan_year_end` is exclusive, so activity dated exactly on `plan_year_end` falls outside the year. The tier schedule comprises `bronze_threshold`, `silver_threshold`, and `gold_threshold` — settled-points bars a member must reach for the corresponding tier — together with `bronze_award_cents`, `silver_award_cents`, and `gold_award_cents`, the annual award attached to each tier. Two policy knobs complete the configuration: `premium_cap_pct`, a fraction (for example, 0.30) capping any award against the employer's premium basis, and `coaching_required_sessions`, the number of coaching sessions a referral must log before it may be discharged. A new program is born in `DRAFT` status.

Activation moves the program `DRAFT → ACTIVE` and enforces two guards. The plan-year window must be well-formed — `plan_year_end` strictly later than `plan_year_start`, otherwise `ERR_INVALID_REQUEST` — and the employer may not run overlapping live programs: if another program of the same employer in `ACTIVE` or `CLOSED` status has a half-open window overlapping this one, activation fails with `ERR_PROGRAM_WINDOW_OVERLAP`. Because both windows are half-open, pure adjacency — one program's `plan_year_end` landing exactly on the other's `plan_year_start` — does not count as overlap and is allowed. Activation increments the program's `version` by one.

Closing a program — `ACTIVE → CLOSED` — is the heaviest cascade in the platform and runs its sweeps in a pinned order. The challenge sweep runs first: every Challenge of the program in `PUBLISHED` or `ACTIVE` status moves to `COMPLETED`, and each still-`JOINED` participation is resolved, so members whose `progress_quantity` has reached the challenge's `goal_quantity` complete and are granted their `BONUS` ledger entries in `PROVISIONAL` status. The ledger expiry sweep runs second: every `PROVISIONAL` PointsLedgerEntry of every enrollment in the program — including the completion bonuses created moments earlier in the same close — transitions to `EXPIRED`, and both enrollment balances are recomputed from what remains. Finally, every BiometricScreening still `SCHEDULED` transitions to `NO_SHOW`, and the program's `version` increments.

While a program is `ACTIVE`, a `BenefitsAdmin` may also finalize its points: every `PROVISIONAL` ledger entry of every enrollment in the program transitions to `POSTED`, both balances of each affected enrollment are recomputed, and the response reports how many entries were moved via `finalized_count`. Attempting this against a program that is not `ACTIVE` is rejected with `ERR_PROGRAM_NOT_ACTIVE`.

The terminal transition, `CLOSED → SETTLED`, is permitted only once every IncentiveAward of the program has reached `APPLIED`; any open award blocks settlement with `ERR_PROGRAM_HAS_OPEN_AWARDS`. Once a program is `SETTLED`, it accepts no new dependent artifacts — no invoices, no reports, no award computations, no participations — and such attempts are rejected with `ERR_PROGRAM_ALREADY_SETTLED`.

### 3.3. Enrollment and the Two Independent Status Axes

Enrollment connects a member to a program. A `BenefitsAdmin` creates an Enrollment from a `program_id` and an `employee_id`, optionally setting `ra_eligible` — the reasonable-alternative medical-waiver flag, which defaults to false and may be established only at creation. Every enrollment carries two independent state axes that evolve separately.

The first axis, `participation_status`, begins at `INVITED` and is terminal at `TERMINATED`. Acceptance is the member's own act: the invited member transitions `INVITED → ACTIVE`, but only while the program itself is `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`) and only when the caller is that member — the caller's `X-User-ID` must equal the enrollment's `employee_id`, otherwise `ERR_OWNERSHIP_MISMATCH`. A `BenefitsAdmin` may suspend an `ACTIVE` enrollment (`ACTIVE → SUSPENDED`) with no further precondition, and may reinstate a `SUSPENDED` enrollment back to `ACTIVE`, but reinstatement again requires the program to be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`). Termination is available from `INVITED`, `ACTIVE`, or `SUSPENDED` alike and stamps `terminated_at` with the current logical-clock instant; the field is null in every non-terminated state. Each of these transitions increments the enrollment's `version` by one.

The second axis, `verification_status`, begins at `PENDING` and is driven entirely by health events rather than by explicit calls. Creating a member's first HealthAssessment moves `PENDING → VERIFIED` automatically. Thereafter, biometric results modulate the flag between `VERIFIED` and `FLAGGED`: a resulted screening meeting at most one of the four biometric targets moves the axis from `VERIFIED` to `FLAGGED`, while a later resulted screening meeting at least three targets moves it from `FLAGGED` back to `VERIFIED`. Because the axes are independent, a `SUSPENDED` member can still become `VERIFIED`. Each automatic verification transition likewise increments the enrollment's `version`.

Two computed counters ride on the enrollment: `points_balance_provisional` and `points_balance_settled`, recomputed from the ledger per §2.8 on every ledger mutation, and `auto_referral_count`, the number of automatically created risk-driven coaching referrals; all three begin at zero on a fresh enrollment. A `BenefitsAdmin` may also post a manual adjustment: a signed, non-zero `points_delta` accompanied by a required free-text `reason` and the OCC field `expected_enrollment_version`. A stale expected version is rejected with `ERR_STALE_VERSION` per §2.7; a successful adjustment creates an `ADJUSTED` ledger entry born directly in `POSTED` status, recomputes both balances, and increments the enrollment's `version`.

### 3.4. Health Assessment and Biometric Screening

The HealthAssessment is the member's entry into verified status. The member submits their `enrollment_id` together with `answers` — exactly ten integers, each from 0 to 10 — and the assessment is scored in the same call. Three guards apply: the enrollment must be `ACTIVE` (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`); no prior assessment may exist for the enrollment (otherwise `ERR_HRA_ALREADY_COMPLETED`); and the answer array must satisfy the length and range constraints (otherwise `ERR_INVALID_REQUEST`). The computed `risk_score` is the plain sum of the ten answers, and the `risk_band` follows fixed cut lines: `LOW` when the score is below 30, `MODERATE` when it is at least 30 but below 60, and `HIGH` when it is 60 or more. Creation flips the enrollment's verification axis to `VERIFIED`, and a `HIGH` band additionally auto-creates a CoachingReferral with `reason` set to `HIGH_RISK`, `source` set to `AUTO_RISK`, and status `REFERRED`, incrementing the enrollment's `auto_referral_count` by one.

BiometricScreenings are kiosk appointments the member schedules for their `enrollment_id` at a `clinic_location` with a half-open slot from `slot_start` (inclusive) to `slot_end` (exclusive). Scheduling enforces, in the platform's standard evaluation order, that the enrollment is `ACTIVE` (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`), that the slot is well-formed with `slot_end` strictly later than `slot_start` (otherwise `ERR_INVALID_REQUEST`), that kiosk capacity holds — the number of other `SCHEDULED` screenings at the same `clinic_location` whose slots strictly overlap the new one must stay below the employer's `kiosk_capacity`, otherwise `ERR_KIOSK_CAPACITY_EXCEEDED`, where strict overlap means the new slot starts before the other's end and ends after the other's start, so back-to-back adjacency never counts as overlap — and that the slot sits inside the plan year, `slot_start` on or after `plan_year_start` and `slot_end` on or before `plan_year_end` (otherwise `ERR_SLOT_OUTSIDE_WINDOW`). A scheduled screening begins in `SCHEDULED` status.

Result entry is a `BenefitsAdmin` act that moves `SCHEDULED → RESULTED` and supplies the four measurements: `bmi`, `systolic_bp`, `total_cholesterol`, and `glucose`. From these the system computes `targets_met`, a count from zero to four of the strict targets achieved — `bmi` strictly below 30.0, `systolic_bp` strictly below 140, `total_cholesterol` strictly below 200, and `glucose` strictly below 100 — and drives the verification axis: a result meeting at most one target flags the enrollment, moving `verification_status` from `VERIFIED` to `FLAGGED`, while a later result meeting at least three targets restores it from `FLAGGED` to `VERIFIED`. The screening's `version` increments on result entry. A screening whose slot passes without results is swept to `NO_SHOW` when the logical clock advances strictly past its `slot_end`, or by program close as described in §3.2.

### 3.5. Challenges, Device Sync, and Points Accrual

Challenges give members structured ways to earn. A `BenefitsAdmin` creates a Challenge under a `program_id` with a `name`, an `activity_type` of `STEPS`, `MINUTES`, or `VISITS`, a `goal_quantity` the member must reach to complete, a `points_reward` granted as a bonus on completion, and a half-open activity window from `starts_at` (inclusive) to `ends_at` (exclusive). New challenges are born `DRAFT` and carry a `completed_count` of participations currently `COMPLETED`, starting at zero.

While a challenge remains `DRAFT`, a `BenefitsAdmin` may edit its `name`, `goal_quantity`, `points_reward`, `starts_at`, or `ends_at`; every edit must carry `expected_challenge_version`, and a stale value is rejected with `ERR_STALE_VERSION` per §2.7. Edits to a challenge that has left `DRAFT` are rejected with `ERR_INVALID_STATE`. Publishing moves `DRAFT → PUBLISHED` under two guards: the program must be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`), and no other challenge in the same program with the same `activity_type` and status `PUBLISHED` or `ACTIVE` may have an overlapping half-open window — adjacency, one challenge starting exactly when another ends, is allowed, and a true overlap is rejected with `ERR_CHALLENGE_WINDOW_OVERLAP`. Thereafter the logical clock drives the rest: the challenge turns `ACTIVE` once the clock reaches `starts_at`, and turns `COMPLETED` once the clock moves strictly past `ends_at`, resolving every still-`JOINED` participation at that moment.

Members join a challenge by creating a ChallengeParticipation from a `challenge_id` and their `enrollment_id`. Joining requires the enrollment to be `ACTIVE` (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`), the challenge to be `PUBLISHED` or `ACTIVE` (otherwise `ERR_INVALID_STATE`), both to belong to the same program (otherwise `ERR_CHALLENGE_PROGRAM_MISMATCH`), and no prior participation to exist for the same pair (otherwise `ERR_PARTICIPATION_EXISTS`). Upon joining, `progress_quantity` is backfilled by summing the `quantity` of the enrollment's already-accepted activity events whose `activity_type` matches the challenge and whose `occurred_at` falls inside the half-open challenge window; if the backfilled figure already meets the goal, the participation completes immediately with the full completion cascade described below.

Activity arrives through device and app sync. The member submits an `enrollment_id`, a `device_source` identifying the source app or device, an `external_event_id` supplied by that source, the `activity_type`, a strictly positive `quantity`, and the `occurred_at` instant. The occurrence must fall inside the program's plan year and not in the future (otherwise `ERR_EVENT_OUTSIDE_WINDOW`). Ingestion is idempotent on the triple of `enrollment_id`, `device_source`, and `external_event_id`: an identical replay of an already-accepted event returns 200 with the existing event and creates no new ledger entry, while the same key carrying a different `quantity`, `occurred_at`, or `activity_type` is rejected with `ERR_DUPLICATE_EVENT`. Rejection never persists an event.

Accepted events are converted to points by fixed rates with a daily ceiling. The raw conversion is per activity type: for `STEPS`, the quantity divided by 1000 rounded down to a whole number; for `MINUTES`, the quantity divided by 30 rounded down; for `VISITS`, the quantity multiplied by 10. No member may be granted more than 100 points per UTC calendar day of `occurred_at`: taking the day total as the sum of `points_granted` across the enrollment's already-accepted events on that calendar date — accumulated in ingestion order — the event's `points_granted` is the smaller of its raw conversion and the remaining daily headroom, where headroom is 100 minus the day total and never below zero. Acceptance then creates an `EARNED` PointsLedgerEntry in `PROVISIONAL` status carrying the granted delta and the event's id as `source_activity_event_id`, recomputes both enrollment balances, and cascades into challenges: every `JOINED` participation of the enrollment whose challenge matches the event's `activity_type` has its `progress_quantity` recomputed over the half-open window, and any participation whose progress has reached its challenge's `goal_quantity` completes — progress meeting the goal exactly counts — moving `JOINED → COMPLETED`, creating a `BONUS` ledger entry in `PROVISIONAL` status for the challenge's `points_reward`, recomputing the balances again, and incrementing the challenge's `completed_count` by one. The ledger entries sourced from a single activity event — zero or one of them — can be read back through the event's ledger listing.

Completion that never arrives resolves at the sweep. When a challenge completes — by clock sweep or by program close — every participation still `JOINED` with `progress_quantity` short of the goal moves from `JOINED` to `FAILED` with no further effect, while those at or beyond the goal complete with the bonus cascade above. Members and administrators can read back challenge participation, activity events, and the enrollment's full ledger history — including each entry's `kind`, signed `points_delta`, and `status` — through the enrollment's collection listings.

### 3.6. Coaching Referrals and the Re-Referral Loop

Coaching is the platform's intervention arm. A `BenefitsAdmin` creates a CoachingReferral manually for an `enrollment_id` with a `reason` of `HIGH_RISK`, `TOBACCO_CESSATION`, or `RA_REQUEST`; such referrals are born with `source` set to `MANUAL`. Referrals also arrive automatically from high-risk health assessments with `source` set to `AUTO_RISK`, as described in §3.4. Either way the referral begins in `REFERRED` status with `sessions_completed` at zero, `referral_round` at 1, an empty lifetime `session_dates` list, no `outcome`, and no `assigned_coach_id`.

A `Coach` engages a `REFERRED` referral, moving it `REFERRED → ENGAGED`; the engaging coach's `X-User-ID` is recorded as `assigned_coach_id`. While `ENGAGED`, the assigned coach — and only the assigned coach, with mismatches rejected as `ERR_OWNERSHIP_MISMATCH` — logs sessions by supplying a `session_date` and a `duration_minutes`; each logged session increments `sessions_completed` by one, appends the date to the lifetime `session_dates` list, and bumps the referral's `version`. Logging against a referral that is not `ENGAGED` is rejected with `ERR_INVALID_STATE`. The `session_dates` list is never reset, and billing reads it verbatim when computing coaching-session invoice lines.

Discharge moves `ENGAGED → DISCHARGED` and requires the logged `sessions_completed` to be at least the program's `coaching_required_sessions` (otherwise `ERR_REFERRAL_SESSIONS_INSUFFICIENT`); only the assigned coach may discharge. The coach supplies an `outcome` of `GOALS_MET` or `GOALS_NOT_MET`. Discharge carries a cascade with direct money consequences: when the enrollment is `ra_eligible` and the outcome is `GOALS_MET`, the enrollment's `PROJECTED` IncentiveAward is recomputed under the reasonable-alternative variant described in §3.7. A member may instead decline a `REFERRED` referral — a self-service act guarded by the usual ownership check — moving it `REFERRED → DECLINED`.

The loop closes through re-referral. From either `DISCHARGED` or `DECLINED`, a `BenefitsAdmin` may rerefer, returning the referral to `REFERRED` for another round: `referral_round` increments by one, `sessions_completed` resets to zero, `outcome` is cleared to null, and `assigned_coach_id` is cleared to null — while the lifetime `session_dates` history is preserved untouched.

### 3.7. Incentive Awards and the Premium Differential

Awards translate settled points into money. A `BenefitsAdmin` triggers computation for a whole program by naming its `program_id`; the program must be `ACTIVE` or `CLOSED` — a `DRAFT` program draws `ERR_PROGRAM_NOT_ACTIVE`, a `SETTLED` one `ERR_PROGRAM_ALREADY_SETTLED`. Computation produces one award per eligible enrollment — eligibility means `participation_status` of `ACTIVE` or `SUSPENDED` — each born or re-born in `PROJECTED` status. Awards already `PROJECTED` are recomputed in place; awards that have advanced to `CONFIRMED`, `APPLIED`, or `DISPUTED` are left untouched. The response reports `created_count` and `updated_count`. Each award records its `enrollment_id` and a denormalized `program_id`.

Tier attainment reads three inputs. Let P be the enrollment's `points_balance_settled`, H indicate whether a HealthAssessment exists for the enrollment, and B be the best `targets_met` across the enrollment's `RESULTED` screenings — zero when none exist. The `tier` is `GOLD` when P reaches at least the program's `gold_threshold`, H is present, and B is at least 3; `SILVER` when P reaches at least the `silver_threshold` and H is present; `BRONZE` when P reaches at least the `bronze_threshold`; and `NONE` otherwise. Every threshold comparison is inclusive — reaching the bar exactly attains the tier.

From the tier, the award amounts are derived. The cap is the program's `premium_cap_pct` multiplied by the employer's `annual_self_only_premium_cents`, rounded half-up to whole cents. The tier value is the matching tier award — `gold_award_cents`, `silver_award_cents`, `bronze_award_cents`, or zero for `NONE` — and the `standard_award_cents` is the smaller of the tier value and the cap, always stored for comparison. Variant selection then decides what the member actually receives. When the enrollment is `ra_eligible` and at least one of its CoachingReferrals stands `DISCHARGED` with outcome `GOALS_MET`, the reasonable-alternative standard applies: `applied_variant` is `REASONABLE_ALTERNATIVE` and `award_cents` is the smaller of the program's `gold_award_cents` and the cap, regardless of the points tier — identical activity data thereby yields a different conferred award. Otherwise `applied_variant` is `STANDARD` and `award_cents` equals `standard_award_cents`. The tobacco side runs in parallel: `surcharge_cents` is the employer's `tobacco_surcharge_cents` when the member's `tobacco_attested` is true and no `TOBACCO_CESSATION` referral of the enrollment stands `DISCHARGED` with `GOALS_MET`, and zero when the surcharge is waived by that completed cessation or no attestation exists. The `net_annual_differential_cents` is the surcharge minus the award; a positive figure means the employee pays more.

Confirmation locks a projection. Moving `PROJECTED → CONFIRMED` requires the program to be `CLOSED` (otherwise `ERR_PROGRAM_NOT_CLOSED`) and the award's amounts to have been computed after the program's latest close — an award computed before the close, and never recomputed since, is stale and rejected with `ERR_AWARD_NOT_CONFIRMABLE`. Confirmation stamps `confirmed_at` — null until this moment — with the current logical-clock instant and increments the award's `version`. Application moves `CONFIRMED → APPLIED`, the terminal payroll step.

The employee dispute loop runs off `CONFIRMED`. The member — verified by matching the caller's `X-User-ID` against the award enrollment's `employee_id`, otherwise `ERR_OWNERSHIP_MISMATCH` — disputes with a required `dispute_reason`, but only while the logical clock reads no later than thirty days after `confirmed_at`; a later dispute is rejected with `ERR_APPEAL_WINDOW_CLOSED`. Resolution by a `BenefitsAdmin` returns the award `DISPUTED → CONFIRMED` with an `outcome` of `UPHELD` or `ADJUSTED`. `UPHELD` keeps the existing amounts. `ADJUSTED` requires `adjusted_award_cents` in the payload — omitting it is `ERR_INVALID_REQUEST` — and overwrites `award_cents` with that figure, recomputing `net_annual_differential_cents`. Either resolution refreshes `confirmed_at` to the current logical-clock instant, opening a fresh thirty-day dispute window, and increments the award's `version`.

### 3.8. Vendor Billing and Invoice Governance

Vendor compensation is invoiced per program period. A `VendorManager` creates a VendorInvoice from a `program_id`, a free-text `vendor_name`, and a billing period from `period_start` to `period_end` — both inclusive, with `period_end` on or after `period_start` (otherwise `ERR_INVALID_REQUEST`). The program must be `ACTIVE` or `CLOSED`; against a `DRAFT` program creation draws `ERR_PROGRAM_NOT_ACTIVE`, against a `SETTLED` one `ERR_PROGRAM_ALREADY_SETTLED`. Creation computes the invoice's `line_items` — each line carrying a `line_type` of `MEMBER_MONTH`, `COACHING_SESSION`, or `ADJUSTMENT`, a `ref_id` identifying the enrollment or referral it bills for, an `amount_cents`, and a `note` — and sums them into `total_cents`.

Member-month lines prorate the per-member-per-month fee across the inclusive period. The period length in days counts both endpoints. For each enrollment of the program whose `participation_status` is `ACTIVE` or `SUSPENDED` — or `TERMINATED` with a `terminated_at` on or after `period_start` — the billable span runs from the later of the enrollment's creation date and `period_start` through the earlier of the period's end and, for terminated members, the termination date; the member-day count is the inclusive length of that span, never below zero. When the span is positive, the line amount is the employer's `pmpm_fee_cents` multiplied by the member-day count and divided by the period length, rounded half-up to whole cents, and the line is emitted as `MEMBER_MONTH` with `ref_id` naming the enrollment. Coaching-session lines are flat-fee: for each CoachingReferral of the program's enrollments, the platform counts the `session_dates` falling within the inclusive period, and when that count is positive emits a `COACHING_SESSION` line for the count times the employer's `coaching_session_fee_cents`, with `ref_id` naming the referral. Per §2.9, each member-month line is rounded before summation and `total_cents` is the exact sum of rounded line amounts.

While the invoice is `DRAFT`, the vendor may append a signed `ADJUSTMENT` line by supplying an `amount_cents` and a `note`; the total is re-summed and the invoice's `version` increments. Adjustments against a non-`DRAFT` invoice are rejected with `ERR_INVOICE_NOT_EDITABLE`. Submission moves `DRAFT → SUBMITTED` and records the caller's `X-User-ID` as `submitted_by`.

Approval is the `PlatformAdmin`'s act and carries the two guards of §2.11 in the order §2.6 fixes: segregation of duties first, so an approver whose `X-User-ID` equals the invoice's `submitted_by` is rejected with `ERR_SOD_VIOLATION`, and the fiscal guard second, so a `total_cents` strictly greater than the employer's `invoice_approval_limit_cents` is rejected with `ERR_INVOICE_EXCEEDS_LIMIT` unless the approval explicitly carries `override_limit` set to true. An approved invoice is paid, moving from `APPROVED` to `PAID`, which is terminal. Alternatively, a `PlatformAdmin` may dispute a `SUBMITTED` invoice with an explanatory `note` (`SUBMITTED → DISPUTED`), and the vendor may then revise it (`DISPUTED → DRAFT`), which clears `submitted_by` to null and reopens the draft for adjustment and resubmission. Each transition increments the invoice's `version`.

### 3.9. De-Identified Cohort Reporting

Once a program closes, outcomes can be published back to the employer in privacy-preserving form. A `BenefitsAdmin` generates an AggregateReport by naming a `program_id` and a `department`. Generation requires the program to be `CLOSED` — an `ACTIVE` or `DRAFT` program draws `ERR_PROGRAM_NOT_CLOSED`, and a `SETTLED` one `ERR_PROGRAM_ALREADY_SETTLED`.

The cohort is the set of the program's enrollments whose employee's `department` equals the report's `department` and whose `participation_status` is `ACTIVE`, `SUSPENDED`, or `TERMINATED`; `cohort_size` counts it. The k-anonymity guard of §2.11 applies at this point: a cohort smaller than the employer's `k_anonymity_threshold` is refused with `ERR_COHORT_TOO_SMALL` and no report is persisted, while a cohort of exactly the threshold proceeds. For a surviving cohort, three aggregates are computed: `avg_settled_points`, the mean of the cohort's `points_balance_settled` rounded half-up to two decimal places; `participation_rate`, the fraction of the cohort holding at least one `COMPLETED` challenge participation, rounded half-up to four decimal places; and `tobacco_rate`, the fraction of the cohort whose employee's `tobacco_attested` is true, likewise rounded half-up to four decimal places. The report is born `GENERATED`.

Publication moves `GENERATED → PUBLISHED` and requires the program still to be `CLOSED`; if the program has since settled, publication is rejected with `ERR_PROGRAM_ALREADY_SETTLED`. Publication increments the report's `version`.

## 4. Endpoint Definitions

Operations that create new resources — an employer, employee, program, enrollment, health assessment, screening, challenge, participation, coaching referral, invoice, adjustment line, or aggregate report — return a `201 Created` status code. Operations that modify an existing resource or advance the logical clock return a `200 OK`, with one exception: an idempotent replay of an already-accepted activity event also returns `200 OK` carrying the existing event.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and apply time sweeps | PlatformAdmin |
| POST | `/wellness/employers` | Create an employer (tenant config) | PlatformAdmin |
| GET | `/wellness/employers/{id}` | Get one employer | PlatformAdmin, BenefitsAdmin |
| GET | `/wellness/employers/{id}/employees` | List employees of an employer | PlatformAdmin, BenefitsAdmin |
| GET | `/wellness/employers/{id}/programs` | List programs of an employer | PlatformAdmin, BenefitsAdmin |
| POST | `/wellness/employees` | Create an employee (population entry) | BenefitsAdmin |
| GET | `/wellness/employees/{id}` | Get one employee | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/employees/{id}/enrollments` | List enrollments of an employee | PlatformAdmin, BenefitsAdmin, Employee |
| POST | `/wellness/programs` | Create a program (starts DRAFT) | BenefitsAdmin |
| GET | `/wellness/programs/{id}` | Get one program | PlatformAdmin, BenefitsAdmin |
| POST | `/wellness/programs/{id}/activate` | Activate a program; enforces per-employer half-open window non-overlap | BenefitsAdmin |
| POST | `/wellness/programs/{id}/close` | Close a program; expires provisional ledger entries, completes challenges, no-shows scheduled screenings | BenefitsAdmin |
| POST | `/wellness/programs/{id}/settle` | Settle a closed program; requires every award APPLIED | BenefitsAdmin |
| POST | `/wellness/programs/{id}/finalize-points` | Move all PROVISIONAL ledger entries of the program to POSTED | BenefitsAdmin |
| GET | `/wellness/programs/{id}/enrollments` | List enrollments of a program | PlatformAdmin, BenefitsAdmin |
| GET | `/wellness/programs/{id}/challenges` | List challenges of a program | PlatformAdmin, BenefitsAdmin |
| GET | `/wellness/programs/{id}/incentive-awards` | List awards of a program | PlatformAdmin, BenefitsAdmin |
| GET | `/wellness/programs/{id}/vendor-invoices` | List invoices of a program | PlatformAdmin, BenefitsAdmin, VendorManager |
| GET | `/wellness/programs/{id}/aggregate-reports` | List aggregate reports of a program | PlatformAdmin, BenefitsAdmin |
| POST | `/wellness/enrollments` | Enroll an employee into a program (starts INVITED) | BenefitsAdmin |
| GET | `/wellness/enrollments/{id}` | Get one enrollment (Employee scoped to own) | PlatformAdmin, BenefitsAdmin, Employee |
| POST | `/wellness/enrollments/{id}/accept` | Employee accepts invitation: INVITED → ACTIVE | Employee |
| POST | `/wellness/enrollments/{id}/suspend` | Suspend an enrollment: ACTIVE → SUSPENDED | BenefitsAdmin |
| POST | `/wellness/enrollments/{id}/reinstate` | Reinstate an enrollment: SUSPENDED → ACTIVE (program must be ACTIVE) | BenefitsAdmin |
| POST | `/wellness/enrollments/{id}/terminate` | Terminate an enrollment from INVITED, ACTIVE, or SUSPENDED | BenefitsAdmin |
| POST | `/wellness/enrollments/{id}/adjustments` | Post a manual signed points adjustment; OCC on the enrollment version | BenefitsAdmin |
| GET | `/wellness/enrollments/{id}/hras` | List health assessments of an enrollment | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/enrollments/{id}/biometric-screenings` | List screenings of an enrollment | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/enrollments/{id}/challenge-participations` | List participations of an enrollment | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/enrollments/{id}/activity-events` | List activity events of an enrollment | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/enrollments/{id}/points-ledger-entries` | List ledger entries of an enrollment | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/enrollments/{id}/incentive-awards` | List awards of an enrollment | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/enrollments/{id}/coaching-referrals` | List coaching referrals of an enrollment | PlatformAdmin, BenefitsAdmin, Employee, Coach |
| POST | `/wellness/hras` | Submit and score an HRA in one call; HIGH risk auto-creates a coaching referral | Employee |
| POST | `/wellness/biometric-screenings` | Schedule a screening appointment (kiosk capacity enforced per clinic location) | Employee |
| POST | `/wellness/biometric-screenings/{id}/result` | Enter screening results; computes targets and drives verification flagging | BenefitsAdmin |
| POST | `/wellness/challenges` | Create a challenge (DRAFT) | BenefitsAdmin |
| GET | `/wellness/challenges/{id}` | Get one challenge | PlatformAdmin, BenefitsAdmin, Employee |
| PATCH | `/wellness/challenges/{id}` | Edit a DRAFT challenge; OCC on the challenge version | BenefitsAdmin |
| POST | `/wellness/challenges/{id}/publish` | Publish a challenge; same-activity window non-overlap within the program | BenefitsAdmin |
| GET | `/wellness/challenges/{id}/participations` | List participations of a challenge | PlatformAdmin, BenefitsAdmin |
| POST | `/wellness/challenge-participations` | Join a challenge; backfills progress from already-accepted in-window events | Employee |
| POST | `/wellness/activity-events` | Device/app sync ingest, idempotent on the source's event key | Employee |
| GET | `/wellness/activity-events/{id}` | Get one activity event | PlatformAdmin, BenefitsAdmin, Employee |
| GET | `/wellness/activity-events/{id}/points-ledger-entries` | List ledger entries sourced from one activity event | PlatformAdmin, BenefitsAdmin |
| POST | `/wellness/incentive-awards/compute` | (Re)compute PROJECTED awards for all eligible enrollments of a program | BenefitsAdmin |
| POST | `/wellness/incentive-awards/{id}/confirm` | Confirm a projected award (program must be CLOSED) | BenefitsAdmin |
| POST | `/wellness/incentive-awards/{id}/apply` | Apply a confirmed award (payroll application) | BenefitsAdmin |
| POST | `/wellness/incentive-awards/{id}/dispute` | Employee disputes a CONFIRMED award within 30 days | Employee |
| POST | `/wellness/incentive-awards/{id}/resolve` | Resolve a disputed award; UPHELD keeps amounts, ADJUSTED overwrites the award | BenefitsAdmin |
| POST | `/wellness/coaching-referrals` | Create a manual coaching referral | BenefitsAdmin |
| POST | `/wellness/coaching-referrals/{id}/engage` | Coach engages a referral and becomes its assigned coach | Coach |
| POST | `/wellness/coaching-referrals/{id}/sessions` | Log a coaching session (ENGAGED only, assigned coach only) | Coach |
| POST | `/wellness/coaching-referrals/{id}/discharge` | Discharge a referral with an outcome; may trigger a reasonable-alternative award recompute | Coach |
| POST | `/wellness/coaching-referrals/{id}/decline` | Employee declines a referral | Employee |
| POST | `/wellness/coaching-referrals/{id}/rerefer` | Re-refer a discharged or declined referral; round increments, sessions reset | BenefitsAdmin |
| POST | `/wellness/vendor-invoices` | Create an invoice (DRAFT) with computed member-month and coaching-session lines | VendorManager |
| POST | `/wellness/vendor-invoices/{id}/adjustments` | Append a signed ADJUSTMENT line (DRAFT only) | VendorManager |
| POST | `/wellness/vendor-invoices/{id}/submit` | Submit an invoice; records the submitting operator | VendorManager |
| POST | `/wellness/vendor-invoices/{id}/approve` | Approve an invoice; segregation-of-duties and approval-limit guards | PlatformAdmin |
| POST | `/wellness/vendor-invoices/{id}/pay` | Mark an approved invoice paid | PlatformAdmin |
| POST | `/wellness/vendor-invoices/{id}/dispute` | Dispute a submitted invoice | PlatformAdmin |
| POST | `/wellness/vendor-invoices/{id}/revise` | Return a disputed invoice to draft; clears the submitter | VendorManager |
| POST | `/wellness/aggregate-reports` | Generate a de-identified cohort report (program CLOSED; cohort at least k) | BenefitsAdmin |
| POST | `/wellness/aggregate-reports/{id}/publish` | Publish a generated report (program must still be CLOSED) | BenefitsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_CLOSED` | 409 Conflict |
| `ERR_PROGRAM_ALREADY_SETTLED` | 409 Conflict |
| `ERR_PROGRAM_HAS_OPEN_AWARDS` | 409 Conflict |
| `ERR_AWARD_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_HRA_ALREADY_COMPLETED` | 409 Conflict |
| `ERR_EVENT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_SLOT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_PROGRAM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CHALLENGE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_KIOSK_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_EVENT` | 409 Conflict |
| `ERR_PARTICIPATION_EXISTS` | 409 Conflict |
| `ERR_CHALLENGE_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFERRAL_SESSIONS_INSUFFICIENT` | 409 Conflict |
| `ERR_COHORT_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_INVOICE_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_EDITABLE` | 409 Conflict |

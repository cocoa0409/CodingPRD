# Nonqualified Deferred Compensation (409A) Administration API — Product Requirements Document

## 1. Introduction

Employers that sponsor nonqualified deferred compensation arrangements operate under the unforgiving discipline of Internal Revenue Code Section 409A. Elections to defer compensation must be made within rigid windows and become irrevocable; distributions may occur only on a closed set of permitted events; separation-from-service determinations must survive scrutiny under a service-fraction presumption test; specified employees of the sponsoring employer must wait an additional six months for separation-driven payments; and any documentary or operational failure exposes the participant to immediate income inclusion, a premium interest charge, and a twenty percent additional tax. Plan sponsors, recordkeepers, compliance officers, and trust officers each touch a different slice of this workflow, and the regulatory design deliberately forbids one person from both opening and adjudicating the same matter.

This document specifies an API that operationalizes that entire regime. It covers plan setup and lifecycle management, deferral election windows and the three election types with their distinct deadlines, notional investment crediting against participant accounts held on an append-only ledger, rabbi trust funding with a change-in-control funding escalation, separation-from-service adjudication with evidence records, annual specified-employee determinations, distribution scheduling and payment with the six-month delay, change-in-control reporting and acceleration, operational failure quantification with income-inclusion assessment and correction, and plan document finding management. Because the compliance calendar is the heart of the domain, the server also exposes a test-driving logical clock that deterministically fires every scheduled transition the regulations imply. All business resources are mounted under `/api`; the clock control endpoint is mounted at the server root.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `PlanSponsor`, `BenefitsAdministrator`, `ComplianceOfficer`, `TrustOfficer`, `Participant`, and `PlatformAdmin`. A request whose headers are missing or empty, or whose `X-User-Role` does not name one of these six roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_ROLE`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` record; ownership checks on any resource that references a participant — most directly a deferral election's `participant_id`, or an account's `participant_id` reached through the target account — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH`. When `X-User-Role` is `PlanSponsor`, `BenefitsAdministrator`, `ComplianceOfficer`, `TrustOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records these opaque identifiers where a workflow demands an audit anchor — for example as `opened_by_user_id` on a separation case, `reported_by_user_id` on an operational failure case, `determined_by_user_id` on a determination, `assessed_by_user_id` on an assessment, `filed_by_user_id` and `adjudicated_by_user_id` on a document finding, or `verified_by_user_id` on a change-in-control event — but it never compares them against any entity's `id`.

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

### 2.4. Common Resource Properties and the Append-Only Ledger

Every primary resource in the system — plans, participants, election windows, deferral elections, notional funds, accounts, crediting runs, rabbi trusts, separation cases, specified-employee lists, distribution requests, change-in-control events, operational failure cases, and document findings — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- **`version` (integer):** A system-managed integer that increments by exactly one on every mutation of the resource, including system-driven state transitions and cascade effects.

Ledger entries are the deliberate exception. An account ledger entry carries `id` and `created_at` only; both `updated_at` and `version` are absent, because the ledger is append-only. Once written, an entry is never edited: a reversal is modeled as a new compensating entry of the opposite sign, not as a mutation of the original. Account balances are derived by replaying an account's entries in chronological order of `created_at`, ascending; the server stamps each entry with a distinct creation timestamp, so ties in replay order cannot occur.

Beyond these common fields, every stateful resource exposes its lifecycle position through a `status` field whose permitted values are defined per entity throughout §3, and many carry computed or system-stamped fields introduced alongside the workflows that maintain them.

### 2.5. Money, Basis Points, and Rounding Discipline

All monetary amounts in the system are integer cents — never floating-point, never strings. Rates and percentages are expressed as integer basis points, where 10000 basis points equals one hundred percent. Calendar dates travel as ISO date strings in `YYYY-MM-DD` form; instants travel as ISO 8601 UTC timestamps.

Rounding behavior is pinned per calculation and must be honored exactly. Quantities the regulations prorate downward — the deferral cap, vested balances, the coverage-weighted service-fraction average, and service-thousandths of a year — are rounded down to the next whole unit at each pinned step. Crediting gains and the income-inclusion interest and tax components are rounded half-up to whole cents. The rabbi trust's funding target is rounded up to the next whole cent. Where a calculation pins an evaluation order (round each entry first, then sum; or floor the prorated compensation first, then floor the capped deferral), that order is part of the contract: reordering the steps changes results by whole cents on identical inputs and is a defect.

### 2.6. The Logical Clock and Scheduled State Sweeps

The server maintains a logical clock that governs every date- and time-dependent rule in this document. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The target instant must not be earlier than the current logical clock — time never runs backward — and a regressive request is rejected with `ERR_CLOCK_REGRESSION`.

Every clock advance fires a scheduled-transition sweep in a pinned order: first, election windows open and close, applying the associated election locking and expiration effects; second, document findings whose correction deadline has passed lapse, with plan document posture recomputed; third, plans whose termination effective date has been reached finalize their termination; fourth, scheduled distribution requests whose payment date has been reached become payable. Each transition the sweep performs mutates the affected resource, refreshing its `updated_at` and incrementing its `version`.

### 2.7. Optimistic Concurrency Control on Plan-Scoped Writes

Four writes are guarded by optimistic concurrency control against the sponsoring plan's version: amending a plan's configuration, creating an election window, posting a crediting run, and creating a specified-employee list. Each of these requests must carry `expected_plan_version`, a non-optional input holding the plan `version` the client last observed. If the plan's current `version` has advanced beyond that value — because another writer amended the plan, created a window, posted a run, or created a list in the interim — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a configuration baseline it has not observed. The check is evaluated before all business logic on those endpoints. Endpoints not named above do not take a version field.

### 2.8. Request Validation Pipeline and Error Precedence

Every request passes through a single ordered validation pipeline, and the order is observable when several violations coincide. The stages are evaluated in this sequence:

1. **Well-formedness.** The request body must contain all required fields with matching types, valid enum members, parseable date strings, and — for any date-range input — a start that falls before its end. Violations surface as `ERR_INVALID_REQUEST` or `ERR_INVALID_DATE_RANGE`.
2. **User context.** The `X-User-ID` and `X-User-Role` headers must be present, non-empty, and name a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
3. **Role authorization.** The caller's role must be permitted on the endpoint (`ERR_FORBIDDEN_ROLE`).
4. **Ownership.** When the caller acts as a `Participant`, the `X-User-ID` must equal the `id` of the participant that owns the target resource (`ERR_RESOURCE_OWNERSHIP_MISMATCH`); this applies to election creation, submission, and voiding, and to distribution creation.
5. **Existence.** Resource identifiers in the path are validated left to right — the first missing identifier short-circuits the request with `ERR_NOT_FOUND` — and then identifiers referenced in the body (such as `participant_id`, `election_window_id`, `notional_fund_id`, `account_id`, `separation_case_id`, `change_in_control_event_id`, `distribution_request_id`, or `plan_id`) must also exist.
6. **Optimistic concurrency.** On the four plan-scoped writes named in §2.7, `expected_plan_version` must equal the plan's current `version` (`ERR_STALE_VERSION`); this is checked before all business logic.
7. **State gates.** Lifecycle and workflow guards are enforced: the plan-active gate for child writes (`ERR_PLAN_NOT_ACTIVE`), plan transition guards (`ERR_PLAN_STATE_INVALID`), participant guards (`ERR_PARTICIPANT_STATE_INVALID`, `ERR_PARTICIPANT_NOT_ACTIVE`), the account-closed gate (`ERR_ACCOUNT_CLOSED`), election modifiability (`ERR_ELECTION_NOT_MODIFIABLE`), the window-open gate for general elections (`ERR_WINDOW_NOT_OPEN`), distribution state guards (`ERR_DISTRIBUTION_STATE_INVALID`, `ERR_DISTRIBUTION_NOT_PAYABLE`), and the workflow guards for cases, lists, failures, findings, change-in-control events, and crediting runs (`ERR_CASE_STATE_INVALID`, `ERR_LIST_STATE_INVALID`, `ERR_FAILURE_STATE_INVALID`, `ERR_FINDING_STATE_INVALID`, `ERR_CIC_STATE_INVALID`, `ERR_CREDITING_RUN_STATE_INVALID`).
8. **Business safety.** The document-compliance gate blocks payment while a plan's document posture is lapsed (`ERR_PLAN_DOCUMENT_LAPSED`), and segregation-of-duties rules forbid self-adjudication (`ERR_SEGREGATION_OF_DUTIES`).
9. **Temporal deadlines.** Election deadlines (`ERR_ELECTION_DEADLINE_PASSED`, `ERR_PERFORMANCE_ELECTION_TOO_LATE`), correction deadlines (`ERR_CORRECTION_WINDOW_EXPIRED`), the separation reopen window (`ERR_REOPEN_WINDOW_EXPIRED`), and date-shape rules (`ERR_INVALID_WINDOW_DATES`, `ERR_INVALID_EFFECTIVE_DATE`, `ERR_CLOCK_REGRESSION`) are evaluated.
10. **Structural constraints.** Interval overlap (`ERR_WINDOW_OVERLAP`, `ERR_CREDITING_PERIOD_OVERLAP`, `ERR_SERVICE_RECORD_GAP`, `ERR_SERVICE_RECORD_OVERLAP`), uniqueness (`ERR_DUPLICATE_ELECTION`, `ERR_ACCOUNT_EXISTS`, `ERR_TRUST_EXISTS`, `ERR_OPEN_CASE_EXISTS`, `ERR_DRAFT_LIST_EXISTS`, `ERR_DUPLICATE_MEMBER`), cross-aggregate integrity (`ERR_CROSS_PLAN_REFERENCE`, `ERR_ACCOUNT_REQUIRED`), and event/world consistency (`ERR_EVENT_TYPE_NOT_PERMITTED`, `ERR_EVENT_NOT_CONFIRMED`, `ERR_CIC_THRESHOLD_NOT_MET`, `ERR_SERVICE_FRACTION_CONTRADICTS_OUTCOME`, `ERR_CREDITING_RUN_NOT_LATEST`, `ERR_CASE_REOPEN_LIMIT`, `ERR_CASE_HAS_PAID_DISTRIBUTIONS`, `ERR_INDEX_RATE_MISSING`, `ERR_NO_VERIFIED_CIC`).
11. **Fiscal limits.** Monetary caps and floors are enforced last (`ERR_DEFERRAL_CAP_EXCEEDED`, `ERR_INSUFFICIENT_VESTED_BALANCE`, `ERR_EXCEEDS_EMERGENCY_NEED`, `ERR_NEGATIVE_TRUST_ASSETS`, `ERR_CIC_FUNDING_AMOUNT_MISMATCH`).

The precedence matters to readers of this document: a request that would fail both a state gate and a fiscal limit is rejected at the state gate; one that would fail both authentication and existence is rejected at authentication.

### 2.9. Segregation of Duties

Two adjudications are deliberately split across two people. A separation-case determination must be rendered by a `ComplianceOfficer` whose `X-User-ID` differs from the case's `opened_by_user_id`; an income-inclusion assessment on an operational failure must be rendered by a `ComplianceOfficer` whose `X-User-ID` differs from the case's `reported_by_user_id`. Either self-adjudication is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). These identifiers are captured automatically from the acting user's header at the moment the case is opened or the failure is reported.

### 2.10. Interval Semantics: Windows, Crediting Periods, and Service Records

Three families of date intervals coexist in the system, and each family follows its own overlap discipline.

Election windows of the same plan use **closed-interval** semantics: two windows conflict unless one closes strictly before the other opens. Windows that merely touch — one window's close date equal to another's open date — do conflict, and the second window's creation is rejected with `ERR_WINDOW_OVERLAP`.

Crediting runs of the same plan use **half-open** semantics over the interval from `period_start` inclusive to `period_end` exclusive: two runs conflict when one's start falls before the other's end while its own end falls after the other's start. Back-to-back runs, where one run's `period_end` equals the next run's `period_start`, are explicitly allowed. An overlapping new run is rejected with `ERR_CREDITING_PERIOD_OVERLAP`.

Service records within a separation case must **tile contiguously** as half-open intervals: each appended record's start must equal the previous record's end. A break in the chain is rejected with `ERR_SERVICE_RECORD_GAP`; a record that starts before the previous record's end is rejected with `ERR_SERVICE_RECORD_OVERLAP`.

## 3. Business Logic & Workflows

### 3.1. Plan Setup, Amendment, and Lifecycle

Everything begins when a `PlanSponsor` establishes a nonqualified deferred compensation plan. The creation payload carries the plan's `name`, its `effective_date` as an ISO calendar date, and the closed set of distribution events the plan document permits: `distribution_events_allowed` is a non-empty array drawn from `SEPARATION`, `DEATH`, `DISABILITY`, `FIXED_TIME`, `UNFORESEEABLE_EMERGENCY`, and `CHANGE_IN_CONTROL`. The sponsor also supplies `officer_comp_threshold_cents`, the positive annual-compensation threshold against which the `COMPENSATION_THRESHOLD` basis of specified-employee status is later judged. Four configuration flags may be supplied or left at their defaults: `six_month_delay_enabled` (default true) controls whether the six-month delay for specified employees applies to separation distributions; `rabbi_trust_required` (default false) records whether the plan maintains a rabbi trust as its informal funding vehicle; `accelerate_on_cic` (default false) controls whether a verified change in control accelerates distribution of vested balances; and `separation_fraction_test` selects the service-fraction presumption test, defaulting to `DEFAULT_50` with `LIBERAL_20` as the alternative. Two numeric knobs complete the configuration: `vesting_cliff_years`, a whole number from one to ten defaulting to three, and `processing_lag_days`, the administrative lag added to distribution base dates, a whole number from zero to ninety defaulting to thirty.

A newly created plan rests in `DRAFT` with `document_posture` of `COMPLIANT` and an `open_findings_count` of zero. Activation by the `PlanSponsor` moves the plan from `DRAFT` to `ACTIVE`; a plan may be suspended from `ACTIVE` into `SUSPENDED` and later resumed back to `ACTIVE`; each of these transitions requires the matching source state and is otherwise rejected with `ERR_PLAN_STATE_INVALID`, and each bumps the plan's `version`.

The plan's lifecycle state is a hard gate on child activity. Unless the plan is `ACTIVE`, every child write is refused with `ERR_PLAN_NOT_ACTIVE`: creating an election window, enrolling a participant, creating a notional fund, opening an account, creating or submitting a deferral election, posting a payroll deferral, posting a crediting run, creating a distribution request, establishing the rabbi trust, creating a specified-employee list, reporting a change in control, reporting a document finding, and reporting an operational failure. Suspension is therefore a true freeze: the same gate applies while the plan is `SUSPENDED`, and it applies equally in `DRAFT`, `TERMINATION_PENDING`, and `TERMINATED`.

While a plan remains active or suspended, the `PlanSponsor` may amend its configuration — `name`, `six_month_delay_enabled`, `rabbi_trust_required`, `accelerate_on_cic`, `separation_fraction_test`, `vesting_cliff_years`, `officer_comp_threshold_cents`, and `processing_lag_days` — through the concurrency-guarded write described in §2.7, which requires `expected_plan_version` and bumps the plan's `version` on success. Amendment is forbidden once the plan has entered `TERMINATION_PENDING` or `TERMINATED` and is then rejected with `ERR_PLAN_STATE_INVALID`.

Termination is a two-stage affair. The `PlanSponsor` initiates termination from `ACTIVE` or `SUSPENDED` — from any other state the attempt is rejected with `ERR_PLAN_STATE_INVALID` — whereupon the plan moves to `TERMINATION_PENDING`, its `termination_effective_date` is set to the current clock date plus twelve calendar months (that field stays null until termination begins), and every deferral election of the plan still resting in `DRAFT` or `SUBMITTED` is voided. When the logical clock later reaches the `termination_effective_date`, the scheduled sweep moves the plan from `TERMINATION_PENDING` to its terminal `TERMINATED` state. The plan's `document_posture`, by contrast, evolves independently of this lifecycle: it is a computed posture over the plan's document findings, developed in §3.9, and it gates distribution payment.

### 3.2. Election Windows and Deferral Elections

A `PlanSponsor` lays out the election calendar by creating an election window against an `ACTIVE` plan, supplying `plan_id`, the `plan_year` in which the deferred compensation will be earned, and the inclusive general-election dates `general_open_date` and `general_close_date`. Two date-shape rules guard the window: the general close date must fall inside the calendar year immediately preceding `plan_year`, and the open date must not fall after the close date; either defect is rejected with `ERR_INVALID_WINDOW_DATES`. Plans that offer performance-based compensation may additionally supply `performance_period_start` and `performance_period_end`; the two are supplied together or not at all, and when present the performance period must span at least 365 days, again on pain of `ERR_INVALID_WINDOW_DATES`. Window creation is one of the four concurrency-guarded writes of §2.7 — the request must carry `expected_plan_version` — and it is subject to the closed-interval overlap rule of §2.10, colliding windows being rejected with `ERR_WINDOW_OVERLAP`. A successful creation leaves the window `SCHEDULED` and, because the plan's window inventory is part of its configuration baseline, bumps the plan's `version`.

From there the window runs on the clock. When the logical clock date reaches `general_open_date`, the sweep moves the window from `SCHEDULED` to `OPEN`; when the clock date passes `general_close_date`, the sweep moves it from `OPEN` to its terminal `CLOSED` state. Closing is consequential for elections: every `GENERAL` deferral election referencing the window that is still in `DRAFT` is expired to `EXPIRED`, and every such election in `SUBMITTED` is locked — moved to `LOCKED` with `locked_at` stamped at the clock timestamp, irrevocable from that instant. The window list view accepts an optional `plan_id` filter alongside `limit` and `offset`.

A `Participant` acting for self creates a deferral election by supplying `participant_id`, `election_window_id`, the `notional_fund_id` of the notional investment fund to which deferrals will be credited, the `election_type` — one of `GENERAL`, `NEWLY_ELIGIBLE`, or `PERFORMANCE` — and `deferral_percent_bp`, the share of eligible compensation to defer expressed in basis points and bounded between 1 and 7500 (a value outside that range, like any malformed scalar, is rejected with `ERR_INVALID_REQUEST`). The election's `plan_id` is denormalized from the participant's own plan at creation rather than accepted from the caller. Creation requires an `ACTIVE` plan, an `ACTIVE` participant (`ERR_PARTICIPANT_NOT_ACTIVE`), plan coherence across the three references — the participant's `plan_id`, the window's `plan_id`, and the fund's `plan_id` must all agree, else `ERR_CROSS_PLAN_REFERENCE` — and uniqueness: one election per participant per window, with a repeat attempt rejected as `ERR_DUPLICATE_ELECTION`. Each election type carries its own gate. A `GENERAL` election may only be created while its window is `OPEN` (`ERR_WINDOW_NOT_OPEN`). A `NEWLY_ELIGIBLE` election may be created and submitted no later than thirty days after the participant's `initial_eligibility_date`, inclusive of that thirtieth day (`ERR_ELECTION_DEADLINE_PASSED`). A `PERFORMANCE` election may be created and submitted no later than six calendar months before the window's `performance_period_end`, inclusive of that boundary date (`ERR_PERFORMANCE_ELECTION_TOO_LATE`). The newly-eligible and performance types are exempt from the window-open gate but never from their own deadlines.

Submitting an election is the participant's formal act of deferral. Only a `DRAFT` election may be submitted — any other source state is rejected with `ERR_ELECTION_NOT_MODIFIABLE` — and submission again requires the participant to be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`), the plan to be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`), and the type-specific deadline to be unexpired: for `GENERAL` elections the window must still be `OPEN` and the clock date must fall on or before `general_close_date`, else `ERR_ELECTION_DEADLINE_PASSED`. On acceptance the election moves to `SUBMITTED`, `submitted_at` is stamped, and the system computes `elected_cap_cents`, the maximum deferrable amount, which stays null until this moment. For `GENERAL` and `PERFORMANCE` elections the cap is the participant's `annual_compensation_cents` multiplied by `deferral_percent_bp` and divided by 10000, rounded down to a whole cent. For a `NEWLY_ELIGIBLE` election the cap is prorated to the remaining days of the plan year in a pinned two-step order: first count the remaining days as the number of days from the submission date through December 31 of the window's `plan_year`, inclusive of both ends (that is, the difference in days plus one); then round down the prorated compensation — `annual_compensation_cents` multiplied by those remaining days and divided by 365; and only then round down the product of that prorated compensation and `deferral_percent_bp` divided by 10000. Flooring at both steps, in this order, is part of the contract.

An election that has not yet locked may be retracted: voiding moves an election from `DRAFT` or `SUBMITTED` to `VOIDED`, and any attempt to void from a later state is rejected with `ERR_ELECTION_NOT_MODIFIABLE`. Locking itself is clock-driven and type-specific: `GENERAL` elections lock at their window's close as described above; `NEWLY_ELIGIBLE` elections still `SUBMITTED` lock when the clock date passes the thirtieth day after `initial_eligibility_date`; and `PERFORMANCE` elections still `SUBMITTED` lock when the clock date passes the date six calendar months before `performance_period_end`. In every case `locked_at` is stamped and the election is irrevocable from that instant. Elections still sitting in `DRAFT` when their type-specific deadline passes are instead expired to `EXPIRED` by the sweep. `LOCKED` elections persist through nearly everything — even a confirmed separation of the participant voids only `DRAFT` and `SUBMITTED` elections, never `LOCKED` ones.

Payroll then executes against the locked election. A `BenefitsAdministrator` posts a deferral by supplying `amount_cents` together with the `service_period_start` and `service_period_end` the deferral compensates. Posting requires the election to be `LOCKED` (`ERR_ELECTION_NOT_MODIFIABLE`), an `ACTIVE` plan, an account already opened for the election's participant and plan (`ERR_ACCOUNT_REQUIRED`), and that account not `CLOSED` (`ERR_ACCOUNT_CLOSED`). Fiscally, the posting may not push the election's cumulative `posted_cents` above its `elected_cap_cents` — the new amount plus the running total must remain within the cap, else the posting is rejected with `ERR_DEFERRAL_CAP_EXCEEDED`. An accepted posting creates a ledger entry of type `DEFERRAL_CREDIT` in `PENDING` status, carrying the election's `notional_fund_id` as its fund reference and the election as its source, adds the amount to the election's `posted_cents` — a running total that begins at zero when the election is created — and, when that running total reaches the cap exactly, moves the election from `LOCKED` to its terminal `APPLIED` state. The election list view accepts `participant_id`, `election_window_id`, `notional_fund_id`, and `plan_id` as optional filters.

### 3.3. Participants, Accounts, the Ledger, and Notional Crediting

A `BenefitsAdministrator` enrolls a participant into an `ACTIVE` plan by supplying the plan's `plan_id`, an external HR reference string `employee_ref`, the participant's most recent `hire_date` from which vesting service is measured, the `initial_eligibility_date` that anchors the newly-eligible election rule, and `annual_compensation_cents`, a strictly positive annualized compensation figure used for the deferral caps. A new participant starts `ACTIVE` with `is_specified_employee` false and an `inclusion_liability_cents` of zero. The administrator may later update `annual_compensation_cents`, or drive two status families directly: marking a participant `DISABLED` is permitted from `ACTIVE`, `SEPARATION_REVIEW`, or `SEPARATED`, and marking a participant `DECEASED` is permitted from any state other than `DECEASED` itself; any other transition request is rejected with `ERR_PARTICIPANT_STATE_INVALID`. Rehiring is its own act: a participant who is `SEPARATED` — and only one who is `SEPARATED`, else `ERR_PARTICIPANT_STATE_INVALID` — may be returned to `ACTIVE`, which clears `separation_date` to null and resets `is_specified_employee` to false. The participant list view accepts an optional `plan_id` filter.

Each participant's economic interest in a plan lives in a single account. A `BenefitsAdministrator` opens it by supplying `participant_id` and `plan_id`; the two must cohere — the account's `plan_id` must equal the participant's own `plan_id`, else `ERR_CROSS_PLAN_REFERENCE` — the participant must be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`), and there is exactly one account per participant per plan, a second attempt being rejected with `ERR_ACCOUNT_EXISTS`. A new account is `ACTIVE` with all balances at zero. The account list view accepts optional `participant_id` and `plan_id` filters.

The account's financial truth is its ledger. Every ledger entry records its owning `account_id`, an `entry_type` of `DEFERRAL_CREDIT`, `CREDITING_GAIN`, `CREDITING_REVERSAL`, or `DISTRIBUTION_DEBIT`, a signed `amount_cents` (credits positive, debits negative), and an `entry_date` set to the clock date at creation. Three foreign references are nullable and set according to entry type: `fund_id` is set on deferral credits and on both crediting entry types; `crediting_run_id` is set on crediting gains and reversals; `election_id` is set on deferral credits; and `distribution_request_id` is set on distribution debits. An entry's `entry_status` is `PENDING` or `POSTED`: deferral credits enter the ledger as `PENDING` — payroll intent not yet confirmed — while every other entry type enters directly as `POSTED`. The payroll-confirmation act by a `BenefitsAdministrator` flips all of an account's `PENDING` entries to `POSTED` in one step, recomputes the settled and vested balances, and bumps the account's `version`; it is refused on a `CLOSED` account with `ERR_ACCOUNT_CLOSED`. The ledger itself is queryable with optional filters `account_id`, `fund_id`, `crediting_run_id`, `election_id`, and `distribution_request_id`, always replayed in `created_at` ascending order.

Two balance variants are derived from this ledger on every mutation and every read. The `settled_balance_cents` sums `amount_cents` over the account's `POSTED` entries only; it is the fiscally authoritative figure used for distribution checks, the vesting base, and the account-closed transition. The `provisional_balance_cents` sums both `POSTED` and `PENDING` entries; it feeds statement display and the deferral-cap machinery, so the two balances diverge whenever unconfirmed payroll entries exist. Reversals never edit history — a reversed credit is a new compensating entry of opposite sign — which is why the ledger has no `REVERSED` entry status.

Vesting is evaluated against the current clock date on every read that needs it. Service is measured in whole days from the participant's `hire_date` to the clock date, converted to thousandths of a year by multiplying the day count by one thousand and dividing by 365 with the quotient rounded down. When that figure reaches at least the plan's `vesting_cliff_years` expressed in thousandths — cliff vesting is all-or-nothing — the participant's `vested_bp` is 10000; below the cliff it is 0. Service of exactly the cliff duration counts as vested, the boundary being inclusive. The account's `vested_balance_cents` is then its `settled_balance_cents` multiplied by `vested_bp` and divided by 10000, rounded down to a whole cent. An account statement view exposes this machinery directly: `settled_balance_cents`, `provisional_balance_cents`, `vested_balance_cents`, the current `vested_bp`, the `pending_entries_count` and `posted_entries_count`, and the lifetime `total_deferred_cents` and `total_distributed_cents`.

Notional investment returns enter through crediting runs. A `BenefitsAdministrator` creates a run against an `ACTIVE` plan, supplying `plan_id`, the half-open crediting period from `period_start` inclusive to `period_end` exclusive (a start that does not precede the end is rejected with `ERR_INVALID_DATE_RANGE`), and — when the plan offers index-linked funds — `index_rates`, an array pairing each such fund's `fund_id` with the `annual_rate_bp` to credit for the period, each rate bounded between -10000 and 10000 basis points. Creation is concurrency-guarded by `expected_plan_version` per §2.7, rejects periods overlapping an existing `POSTED` run of the same plan under the half-open rule of §2.10 (`ERR_CREDITING_PERIOD_OVERLAP`), and requires every `ACTIVE` `INDEX_LINKED` fund of the plan to appear in `index_rates` — an omission is rejected with `ERR_INDEX_RATE_MISSING`. The run is stamped `POSTED` at creation, its `days_in_period` records the period's length in whole days, and creation bumps the sponsoring plan's `version`.

The run's postings follow a pinned procedure. Each account of the plan in `ACTIVE` or `FLAGGED_FOR_INCLUSION` is processed in order of account creation, earliest first. Within an account, each notional fund in which the account holds a positive settled balance — the sum of `POSTED` entries bearing that fund, replayed as of run creation — earns a gain. For a `FIXED_RATE` fund the rate is the fund's own `annual_rate_bp`; for an `INDEX_LINKED` fund it is the rate supplied for that fund in the run's `index_rates`. The raw gain is the fund-specific settled balance multiplied by the rate in basis points, multiplied by `days_in_period`, and divided by the product of 10000 and 365. That raw figure is rounded half-up to whole cents **per entry**, and only then are the per-entry gains summed into the run's `total_gain_cents`; the reverse order — summing raw fractional gains and rounding once — is forbidden because the two orders diverge by whole cents on identical inputs. Each accepted gain posts a `CREDITING_GAIN` ledger entry in `POSTED` status tagged with the fund and the run, and account balances are recomputed as the entries land.

A mistaken run can be unwound by a `BenefitsAdministrator`, but only the latest one: the run must be `POSTED` (`ERR_CREDITING_RUN_STATE_INVALID`) and must be the plan's most recent `POSTED` run, ranked by greatest `period_end` with ties broken toward the later-created run (`ERR_CREDITING_RUN_NOT_LATEST`). Reversal posts, for every `CREDITING_GAIN` of the run, a compensating `CREDITING_REVERSAL` entry of exactly the negated amount against the same account, fund, and run, then recomputes balances — which return exactly to their pre-run values, a compensating invariant the system guarantees — and moves the run to `REVERSED`.

Notional funds themselves are created by a `PlanSponsor` against an `ACTIVE` plan with a `ticker`, a `crediting_mode` of `FIXED_RATE` or `INDEX_LINKED`, and an `annual_rate_bp` between -10000 and 10000 basis points. The stored rate drives `FIXED_RATE` funds; for `INDEX_LINKED` funds it is ignored, the effective rate being supplied per crediting run. The fund list view accepts an optional `plan_id` filter.

### 3.4. Separation-from-Service Determination

When a participant's service relationship is called into question, a `BenefitsAdministrator` opens a separation case, supplying the `participant_id`, the `alleged_separation_date`, and a `trigger_reason` of `RESIGNATION`, `TERMINATION`, `RETIREMENT`, or `SERVICE_REDUCTION`. A case can only be opened for a participant who is currently `ACTIVE`, and opening it immediately moves that participant from `ACTIVE` to `SEPARATION_REVIEW`. A participant may carry at most one open case at a time — open meaning `OPEN`, `EVIDENCE_SUBMITTED`, or `REOPENED` — and a second attempt is rejected with `ERR_OPEN_CASE_EXISTS`. The opener's identity is captured as `opened_by_user_id` and becomes the segregation-of-duties anchor for the eventual determination. The case list view accepts an optional `participant_id` filter.

Evidence arrives as entries in the case's `service_records` collection, appended by a `BenefitsAdministrator` while the case is `OPEN`, `REOPENED`, or `EVIDENCE_SUBMITTED` — appends from any other state are rejected with `ERR_CASE_STATE_INVALID`. Each record carries a `period_start`, a `period_end`, and a `service_fraction_bp`. The records must tile contiguously as half-open intervals per §2.10, with the chain ending exactly at the `alleged_separation_date` and its total coverage amounting to at least 1,095 days — three full years of evidence. The first append after a case is opened or reopened moves it to `EVIDENCE_SUBMITTED`; subsequent appends leave it there. Every append recomputes `computed_avg_fraction_bp` — null until the first record arrives — as the coverage-weighted average service fraction: multiply each record's `service_fraction_bp` by its length in days, sum those products, divide by the total number of days covered, and round down to whole basis points.

Determination belongs to a `ComplianceOfficer` who did not open the case — the segregation rule of §2.9 is enforced against `opened_by_user_id` with `ERR_SEGREGATION_OF_DUTIES` — and requires the case to hold at least one service record in `EVIDENCE_SUBMITTED` or `REOPENED` status, else `ERR_CASE_STATE_INVALID`. The officer supplies an `outcome`, and the outcome must agree with the computed presumption under the plan's `separation_fraction_test`. Under the `DEFAULT_50` test the threshold is 5000 basis points; under `LIBERAL_20` it is 2000. An outcome of `CONFIRMED_SEPARATION` is valid only when the computed average fraction is strictly below the threshold, while `REBUTTED_CONTINUED_SERVICE` is valid only when the average is at or above it — an average of exactly the threshold therefore means the participant is *not* separated, and identical evidence can flip the correct determination between the two plan configurations. An outcome contradicting the presumption is rejected with `ERR_SERVICE_FRACTION_CONTRADICTS_OUTCOME`.

A confirmed determination stamps `determination_threshold_bp` with the threshold snapshot — 5000 or 2000 according to the plan's test — records `determined_by_user_id` and `determined_at`, moves the case to `DETERMINED_SEPARATED`, and cascades: the participant moves from `SEPARATION_REVIEW` to `SEPARATED` with `separation_date` set to the case's `alleged_separation_date`, and that participant mutation in turn voids every `DRAFT` or `SUBMITTED` deferral election of the participant while `LOCKED` elections persist untouched. A rebutted determination instead returns the participant from `SEPARATION_REVIEW` to `ACTIVE`, moves the case to `DETERMINED_NOT_SEPARATED`, and — as developed in §3.6 — denies any linked distribution request currently sitting `ON_HOLD`.

Determined cases are only softly terminal. A `BenefitsAdministrator` may reopen a case that is `DETERMINED_SEPARATED` or `DETERMINED_NOT_SEPARATED` (from any other state, `ERR_CASE_STATE_INVALID`), but only once — the `reopen_count`, which starts at zero, is hard-capped at one, and a second reopen is rejected with `ERR_CASE_REOPEN_LIMIT`; only within thirty days after the determination date, inclusive of the thirtieth day (`ERR_REOPEN_WINDOW_EXPIRED`); and only while no linked distribution request has reached `PAID` (`ERR_CASE_HAS_PAID_DISTRIBUTIONS`), since reopening would otherwise invalidate a completed payment. Reopening increments `reopen_count`, moves the case to `REOPENED`, and — when the case had been determined separated — pulls the participant back from `SEPARATED` to `SEPARATION_REVIEW`, nulls the `separation_date`, and places any linked `SCHEDULED` distribution request `ON_HOLD`. After a reopen and a fresh determination under the same rules, `reopen_count` has reached one and the determination is final. A re-determination that confirms separation re-separates the participant, and the linked `ON_HOLD` request returns to `SCHEDULED` with its payment date recomputed against the new separation date.

### 3.5. Specified-Employee Determination and the Six-Month Delay

Once a year, a `ComplianceOfficer` builds the plan's specified-employee determination. Creating the list against an `ACTIVE` plan takes `plan_id`, the `identification_date` of the determination, and the `effective_date` on which the list takes effect — the latter must fall strictly after the identification date and no later than 120 days after it, inclusive of that 120th day, else `ERR_INVALID_EFFECTIVE_DATE`. Creation is concurrency-guarded by `expected_plan_version` per §2.7, only one `DRAFT` list may exist per plan at a time (`ERR_DRAFT_LIST_EXISTS`), and a successful creation leaves the list `DRAFT` while bumping the plan's `version`.

Members are added row by row while the list is `DRAFT` — additions to a finalized or superseded list are rejected with `ERR_LIST_STATE_INVALID`. Each row names a `participant_id`, a `basis` of `OFFICER`, `FIVE_PERCENT_OWNER`, or `COMPENSATION_THRESHOLD`, and the member's `annual_compensation_cents`; one row per participant per list (`ERR_DUPLICATE_MEMBER`), and every member must be a participant of the list's plan (`ERR_CROSS_PLAN_REFERENCE`). The list view exposes the roster with its per-member computed flags, and the list-of-lists view accepts an optional `plan_id` filter.

Finalizing the list runs the selection waterfall. The eligible population is every participant of the plan in `ACTIVE`, `SEPARATION_REVIEW`, or `SEPARATED` status. The `officer_cap_count` is computed as the smaller of fifty and one tenth of the eligible count rounded down to a whole number. Members on the `OFFICER` basis are then ranked by `annual_compensation_cents` from highest to lowest, ties broken toward the earlier-created participant record (the participant's `id` is never used as a tiebreaker); those within the cap emerge `is_specified` true, and those beyond it emerge `is_specified` false with `exclusion_reason` of `OFFICER_CAP_EXCEEDED`. Members on the `COMPENSATION_THRESHOLD` basis are specified when their `annual_compensation_cents` is at least the plan's `officer_comp_threshold_cents` — the boundary is inclusive — and otherwise receive `exclusion_reason` of `BELOW_COMP_THRESHOLD`. Members on the `FIVE_PERCENT_OWNER` basis are specified unconditionally. Finalizing a list with no members at all is clean: every participant of the plan simply lands on `is_specified_employee` false.

The finalize cascades widely. Every member computed `is_specified` true has their participant record's `is_specified_employee` set true; any prior `FINALIZED` list of the same plan is superseded to `SUPERSEDED`, and participants absent from the new list have `is_specified_employee` reset to false. Most consequentially, for each participant whose flag flips from false to true, every `SCHEDULED` distribution request of theirs with event type `SEPARATION` under a plan whose `six_month_delay_enabled` is set has its `scheduled_payment_date` recomputed under the delay rule — the list determination is allowed to push already-scheduled payments further into the future.

The delay rule itself governs when separation-driven money may move. A distribution's base payment date depends on its event type: for `SEPARATION`, the alleged separation date from the linked case plus the plan's `processing_lag_days`; for `FIXED_TIME`, the request's own `fixed_date`; for `CHANGE_IN_CONTROL`, the verified event's `effective_date` plus the processing lag; and for `DEATH`, `DISABILITY`, and `UNFORESEEABLE_EMERGENCY`, the calendar date on which the event was verified plus the processing lag. On top of the base date sits the six-month delay, which applies exactly when three conditions coincide: the event type is `SEPARATION`, the plan's `six_month_delay_enabled` is set, and the participant is a specified employee at schedule time. When it applies, a delay floor is computed as the separation date plus six calendar months, keeping the same day of month and clamping to the end of the month when the target month is shorter; payment exactly on the floor date is permitted, just never before it. The `scheduled_payment_date` is then the later of the base date and the delay floor — and simply the base date when the delay does not apply.

### 3.6. Distributions from Request to Payment

A `Participant` acting for self initiates a distribution against one of their own accounts — the ownership rule of §2.1 compares the account's `participant_id` to the caller's `X-User-ID` and rejects a mismatch with `ERR_RESOURCE_OWNERSHIP_MISMATCH`. The request names the `account_id` and an `event_type`, which must be among the plan's permitted `distribution_events_allowed` (`ERR_EVENT_TYPE_NOT_PERMITTED`), and both the plan-active gate and the account-not-closed gate apply (`ERR_PLAN_NOT_ACTIVE`, `ERR_ACCOUNT_CLOSED`). The linkage fields are type-driven: a `SEPARATION` request requires `separation_case_id` and a `CHANGE_IN_CONTROL` request requires `change_in_control_event_id`, each null for the other types, and every linkage must belong to the account's own participant and plan (`ERR_CROSS_PLAN_REFERENCE`). Money fields follow the same pattern: `requested_amount_cents` is optional for a partial distribution — omitting it requests the full vested balance — but it is required for `UNFORESEEABLE_EMERGENCY`, must be strictly positive whenever present, and may not exceed the account's `vested_balance_cents` (`ERR_INSUFFICIENT_VESTED_BALANCE`). A `FIXED_TIME` request must carry a `fixed_date` that falls after the creation clock date (`ERR_INVALID_DATE_RANGE`), null for other types; an `UNFORESEEABLE_EMERGENCY` request must carry a strictly positive `emergency_need_cents` documenting the emergency, null for other types. The new request's `participant_id` is denormalized from the account, and it starts life `REQUESTED`. The list view filters by `account_id`, `participant_id`, `separation_case_id`, and `change_in_control_event_id`.

Event verification is the `ComplianceOfficer`'s gate from `REQUESTED` to `EVENT_VERIFIED` — from any other state the attempt is rejected with `ERR_DISTRIBUTION_STATE_INVALID` — and the evidence demanded depends on the event type. A `SEPARATION` request verifies only when its linked case stands `DETERMINED_SEPARATED` and the case's participant matches the account's participant. A `CHANGE_IN_CONTROL` request verifies only when its linked event stands `VERIFIED` and belongs to the account's plan. A `DEATH` request verifies only when the participant is `DECEASED`, and a `DISABILITY` request only when the participant is `DISABLED`. Each of these failures is rejected with `ERR_EVENT_NOT_CONFIRMED`. A `FIXED_TIME` request carries its date from creation and is always verifiable. An `UNFORESEEABLE_EMERGENCY` request verifies only while its `requested_amount_cents` does not exceed its `emergency_need_cents`, else `ERR_EXCEEDS_EMERGENCY_NEED`. Verification stamps `verified_at` with the clock date. The officer may instead deny the request outright — denial is permitted from `REQUESTED` and from `EVENT_VERIFIED` alike (`ERR_DISTRIBUTION_STATE_INVALID` from any other state) — supplying a `reason` that is recorded as `denial_reason` while the request moves to its terminal `DENIED` state.

Scheduling belongs to the `BenefitsAdministrator` and is permitted only from `EVENT_VERIFIED` (`ERR_DISTRIBUTION_STATE_INVALID`), on an account that is `ACTIVE` or `FLAGGED_FOR_INCLUSION` (`ERR_ACCOUNT_CLOSED`), with a vested balance strictly above zero (`ERR_INSUFFICIENT_VESTED_BALANCE`). Scheduling fixes two computed fields, both null until this moment: `locked_amount_cents`, the requested amount when one was supplied and otherwise the full vested balance, in either case capped at the vested balance so the lock never exceeds what the participant owns; and `scheduled_payment_date`, computed under the base-date-plus-delay rule of §3.5. The request is then `SCHEDULED`, and the clock sweep promotes it to `PAYABLE` once the clock date reaches the scheduled payment date.

Payment is the terminal act, performed by a `BenefitsAdministrator`. The request must be `PAYABLE` — a request still `SCHEDULED` ahead of its payment date, or in any other non-payable state, is rejected with `ERR_DISTRIBUTION_NOT_PAYABLE`. Two further guards bind: the plan's `document_posture` must not be `LAPSED_FAILURE` (`ERR_PLAN_DOCUMENT_LAPSED`), and the account's `settled_balance_cents` must cover the `locked_amount_cents` (`ERR_INSUFFICIENT_VESTED_BALANCE`). An accepted payment runs a four-link cascade. First, a `DISTRIBUTION_DEBIT` ledger entry is posted in `POSTED` status for the negated locked amount, linked back to the request. Second, the account's balances are recomputed by ledger replay. Third, if the settled balance has reached zero — with at least one distribution debit now present — the account closes to `CLOSED`. Fourth, that closure cancels every sibling distribution request of the account still sitting in `REQUESTED`, `EVENT_VERIFIED`, `SCHEDULED`, `PAYABLE`, or `ON_HOLD`, sweeping each to `CANCELLED`. Alongside the cascade, when the plan's rabbi trust holds positive assets, the payment appends a `TRUST_DISTRIBUTION` funding event to the trust for the negated smaller of the locked amount and the trust's assets, and the trust's derived fields are recomputed. The paying request stamps `paid_at` and settles into `PAID`.

Two cross-currents from §3.4 interrupt this pipeline. When a linked separation case reopens, a `SCHEDULED` request slides to `ON_HOLD`; when the reopened case is re-determined as a confirmed separation, the request returns from `ON_HOLD` to `SCHEDULED` with its payment date recomputed against the new separation date; and when the case is instead rebutted, the `ON_HOLD` request is denied outright. These transitions exist so that money never moves on a separation premise that is once again in doubt.

### 3.7. Change in Control and Rabbi Trust Funding

A `PlanSponsor` reports a change in control against an `ACTIVE` plan by supplying `plan_id`, an `event_type` of `OWNERSHIP_CHANGE`, `EFFECTIVE_CONTROL_CHANGE`, or `ASSET_CHANGE`, the `effective_date` of the transaction, and `stake_change_bp`, the share of ownership, control, or assets changing hands in basis points. The report rests in `REPORTED` until a `ComplianceOfficer` adjudicates it; adjudication from any other state is rejected with `ERR_CIC_STATE_INVALID`. Verification is threshold-gated per event type: an `OWNERSHIP_CHANGE` requires a stake of at least 5000 basis points — half the ownership — an `EFFECTIVE_CONTROL_CHANGE` requires at least 3500, and an `ASSET_CHANGE` at least 4000, and a report below its type's threshold is rejected with `ERR_CIC_THRESHOLD_NOT_MET`. Whether the outcome supplied is `VERIFIED` or `REJECTED`, the adjudicator's identity is recorded as `verified_by_user_id` and the event lands in the matching terminal state.

Verification fires two cascades. First, the plan's rabbi trust, if one exists, flips `cic_funding_required` to true, recomputes its `required_funding_cents` at the escalated target described below, and recomputes its `posture`. Second, when the plan's `accelerate_on_cic` flag is set, the system spontaneously creates one distribution request per account of the plan that is `ACTIVE` or `FLAGGED_FOR_INCLUSION` and holds a positive vested balance; each such request is created already `EVENT_VERIFIED`, with `event_type` of `CHANGE_IN_CONTROL`, the `change_in_control_event_id` pointing at the verified event, and no requested amount — the full vested balance. Those requests then flow through the ordinary schedule-and-pay pipeline of §3.6. The event list view accepts an optional `plan_id` filter.

The rabbi trust is the plan's informal financing vehicle, established once per plan by a `PlanSponsor` — a second trust for the same plan is rejected with `ERR_TRUST_EXISTS` — with a `funding_target_bp` between 0 and 20000 basis points expressing the target funding as a share of total vested liability, 10000 being full funding. A new trust holds `assets_cents` of zero and opens in `UNFUNDED` posture. From then on, `assets_cents` is the signed sum of the trust's `funding_events`, an append-only array in which each event records an `event_type`, a signed `amount_cents`, and the `recorded_at` instant.

Three derived fields track the funding gap against a moving liability base. The total vested liability is the sum of `vested_balance_cents` across the plan's accounts in `ACTIVE` or `FLAGGED_FOR_INCLUSION`. The effective target is 12500 basis points — one hundred twenty-five percent — once `cic_funding_required` holds, and the trust's own `funding_target_bp` otherwise. The target in cents is that liability multiplied by the effective basis points and divided by 10000, rounded up to the next whole cent; and `required_funding_cents` is the target minus current assets, floored at zero. The trust's `posture` follows: `UNFUNDED` when assets are zero; `UNDERFUNDED` when assets are positive but below the target; and `FUNDED` when assets meet or exceed a positive target — assets exactly equal to the target count as funded — or whenever assets are positive while the target computes to zero. These fields are recomputed at trust creation, on every funding event, on a verified change in control, and on any account balance or vesting change.

Funding activity is the `TrustOfficer`'s exclusive province, appended event by event with an `event_type` and `amount_cents`. A `CONTRIBUTION` must be positive. A `VALUATION_ADJUSTMENT` may be positive or negative but never zero. A `CIC_MANDATORY_FUNDING` must be positive, is accepted only when a verified change-in-control event exists for the plan (`ERR_NO_VERIFIED_CIC`), and must equal the trust's `required_funding_cents` exactly at the moment it is posted — the statute's full-funding demand admits no partial gestures — with any other amount rejected as `ERR_CIC_FUNDING_AMOUNT_MISMATCH`. One invariant binds all three types: assets may never be driven below zero (`ERR_NEGATIVE_TRUST_ASSETS`). The fourth event type, `TRUST_DISTRIBUTION`, is never posted directly; it is appended by the system when a distribution payment draws down the trust, as described in §3.6. Every appended event recomputes assets, required funding, and posture. The trust list view accepts an optional `plan_id` filter.

### 3.8. Operational Failures and 409A Income Inclusion

When plan operations diverge from the document — a payment made too early or too late, a deferral in excess of the cap, an improper acceleration — a `BenefitsAdministrator` reports an operational failure against the affected account, supplying `account_id`, a `failure_type` of `EARLY_PAYMENT`, `LATE_PAYMENT`, `EXCESS_DEFERRAL`, or `IMPROPER_ACCELERATION`, the `failure_date` on which the failure occurred (which may not lie in the future), the erroneous `amount_cents` (strictly positive), optionally the `distribution_request_id` of the specific distribution involved — which must belong to the same account, else `ERR_CROSS_PLAN_REFERENCE` — and an optional free-text `description`. The reporter's identity is captured as `reported_by_user_id`, the participant is denormalized from the account, and the case opens `IDENTIFIED` with its `correction_deadline` already computed: December 31 of the second calendar year following the failure's year. The failure list view filters by `account_id`, `distribution_request_id`, and `participant_id`.

Quantification is the first compliance step, performed by a `ComplianceOfficer` on an `IDENTIFIED` case (`ERR_FAILURE_STATE_INVALID`). The officer supplies `correction_credit_cents`, the amount already repaid or corrected before quantification, bounded inclusively between zero and the failure's `amount_cents` (`ERR_INVALID_REQUEST`). The computation then runs in a pinned five-step order, because the credit reduces the base *before* interest and tax are computed — computing interest on the gross amount and subtracting the credit afterward is a different, forbidden order. First, `includible_base_cents` is the failure amount minus the correction credit, floored at zero. Second, the days outstanding are counted from the `failure_date` to the clock date at quantification. Third, `premium_interest_cents` is the base multiplied by 800 basis points — the combination of a 700-basis-point underpayment rate and a 100-basis-point premium — multiplied by the days outstanding, divided by the product of 10000 and 365, and rounded half-up to whole cents. Fourth, `additional_tax_cents` is the base multiplied by 2000 basis points — the twenty percent additional tax — divided by 10000, again rounded half-up. Fifth, `total_inclusion_cents` is the sum of the base, the interest, and the tax. The case lands `QUANTIFIED` with all four figures recorded.

Assessment attaches the liability to the participant. A `ComplianceOfficer` other than the reporter — enforced per §2.9 against `reported_by_user_id` with `ERR_SEGREGATION_OF_DUTIES` — may assess a `QUANTIFIED` case (`ERR_FAILURE_STATE_INVALID`), provided the account is `ACTIVE` or `FLAGGED_FOR_INCLUSION` (`ERR_ACCOUNT_CLOSED`). Assessment adds the case's `total_inclusion_cents` to the participant's running `inclusion_liability_cents`, flags the account — an `ACTIVE` account moves to `FLAGGED_FOR_INCLUSION` — records `assessed_by_user_id`, and moves the case to `INCLUSION_ASSESSED`.

Correction closes the loop. From either `QUANTIFIED` or `INCLUSION_ASSESSED` (`ERR_FAILURE_STATE_INVALID` otherwise), and only while the clock date remains within the `correction_deadline`, inclusive of the deadline date (`ERR_CORRECTION_WINDOW_EXPIRED`), a `ComplianceOfficer` may correct the case. Correction of a previously assessed case subtracts its `total_inclusion_cents` from the participant's `inclusion_liability_cents` — an exact compensating reversal, so the liability drifts net zero across assess-then-correct — and, when no other failure case of the same account remains in `QUANTIFIED` or `INCLUSION_ASSESSED`, returns the account from `FLAGGED_FOR_INCLUSION` to `ACTIVE`. The case settles into its terminal `CORRECTED` state.

### 3.9. Document Findings and Plan Compliance Posture

A plan document that fails the 409A documentary requirements is tracked through findings reported by a `ComplianceOfficer` against an `ACTIVE` plan with a `plan_id`, a `description` of the documentary failure, and the `failure_year` in which it occurred, which may not exceed the current clock year. The finding opens `REPORTED` with its `correction_deadline` computed as December 31 of the second year following `failure_year`, and its arrival immediately recomputes the plan's `document_posture` and `open_findings_count`. The finding list view accepts an optional `plan_id` filter.

The plan's `document_posture` is a computed dimension that evolves independently of the plan's lifecycle status and is recomputed on every finding transition. It reads `COMPLIANT` when no finding of the plan sits in `REPORTED`, `CORRECTION_FILED`, or `LAPSED`; `FAILURE_OPEN` when at least one finding is `REPORTED` or `CORRECTION_FILED` and none is `LAPSED`; and `LAPSED_FAILURE` the moment any finding has lapsed. The `open_findings_count` tallies the findings in `REPORTED` or `CORRECTION_FILED`. Posture has teeth: as §3.6 describes, a distribution payment is forbidden while posture is `LAPSED_FAILURE` (`ERR_PLAN_DOCUMENT_LAPSED`).

Remediation runs on the clock. A `ComplianceOfficer` files a correction — supplying the amendment `correction_text`, null until filed — while the finding is `REPORTED` (`ERR_FINDING_STATE_INVALID`) and the clock date remains within the correction deadline, inclusive (`ERR_CORRECTION_WINDOW_EXPIRED`); filing records `filed_by_user_id` and moves the finding to `CORRECTION_FILED`, with the plan's posture recomputed but remaining `FAILURE_OPEN` while the correction is filed-but-open. A `PlanSponsor` then adjudicates the filed correction — adjudication from any state other than `CORRECTION_FILED` is rejected with `ERR_FINDING_STATE_INVALID` — with an `outcome`: `CORRECTED` resolves the finding to its terminal `CORRECTED` state, records `adjudicated_by_user_id`, and recomputes posture to `COMPLIANT` when no other finding remains `REPORTED`, `CORRECTION_FILED`, or `LAPSED`; `REJECTED` instead sends the finding back to `REPORTED` with its `correction_text` retained for audit, and the cycle may repeat. Whatever the path, the clock sweep stands behind it: a finding still `REPORTED` or `CORRECTION_FILED` when the clock date passes its `correction_deadline` lapses to `LAPSED`, dragging the plan's posture to `LAPSED_FAILURE` and freezing distributions until the documentary failure is genuinely resolved.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code — including operations that append a new subordinate record to an existing resource, such as a service record on a separation case, a member row on a specified-employee list, a funding event on a rabbi trust, or a deferral-credit ledger entry produced by posting a deferral. Operations that modify or act upon an existing resource without creating a new one return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/plans` | Create a plan in `DRAFT` with document posture `COMPLIANT` | PlanSponsor |
| GET | `/api/plans` | List plans, paginated | All roles |
| GET | `/api/plans/{planId}` | Get a plan | All roles |
| PATCH | `/api/plans/{planId}` | Amend plan configuration (OCC-guarded) | PlanSponsor |
| POST | `/api/plans/{planId}/activate` | Activate a `DRAFT` plan | PlanSponsor |
| POST | `/api/plans/{planId}/suspend` | Suspend an `ACTIVE` plan, blocking child writes | PlanSponsor |
| POST | `/api/plans/{planId}/resume` | Resume a `SUSPENDED` plan | PlanSponsor |
| POST | `/api/plans/{planId}/terminate` | Begin plan termination with a twelve-month wind-down | PlanSponsor |
| POST | `/api/election-windows` | Create an election window for a plan (OCC-guarded) | PlanSponsor |
| GET | `/api/election-windows` | List election windows, optionally filtered by plan | All roles |
| GET | `/api/election-windows/{windowId}` | Get an election window | All roles |
| POST | `/api/participants` | Enroll a participant into an `ACTIVE` plan | BenefitsAdministrator |
| GET | `/api/participants` | List participants, optionally filtered by plan | All roles |
| GET | `/api/participants/{participantId}` | Get a participant | All roles |
| PATCH | `/api/participants/{participantId}` | Update compensation or set `DISABLED`/`DECEASED` status | BenefitsAdministrator |
| POST | `/api/participants/{participantId}/rehire` | Rehire a `SEPARATED` participant back to `ACTIVE` | BenefitsAdministrator |
| POST | `/api/notional-funds` | Create a notional investment fund for a plan | PlanSponsor |
| GET | `/api/notional-funds` | List notional funds, optionally filtered by plan | All roles |
| GET | `/api/notional-funds/{fundId}` | Get a notional fund | All roles |
| POST | `/api/deferral-elections` | Create a `DRAFT` deferral election (participant acting for self) | Participant |
| GET | `/api/deferral-elections` | List deferral elections with filters | All roles |
| GET | `/api/deferral-elections/{electionId}` | Get a deferral election | All roles |
| POST | `/api/deferral-elections/{electionId}/submit` | Submit a `DRAFT` election and compute its deferral cap | Participant |
| POST | `/api/deferral-elections/{electionId}/void` | Void an election before it locks | Participant |
| POST | `/api/deferral-elections/{electionId}/post-deferral` | Post a payroll deferral against a `LOCKED` election | BenefitsAdministrator |
| POST | `/api/accounts` | Open the participant's notional account in a plan | BenefitsAdministrator |
| GET | `/api/accounts` | List accounts, optionally filtered by participant or plan | All roles |
| GET | `/api/accounts/{accountId}` | Get an account with its balances | All roles |
| GET | `/api/accounts/{accountId}/statement` | Computed statement with dual balances, vesting, and totals | All roles |
| POST | `/api/accounts/{accountId}/settle-entries` | Flip all `PENDING` ledger entries of the account to `POSTED` | BenefitsAdministrator |
| GET | `/api/ledger-entries` | Query the append-only ledger with filters | All roles |
| GET | `/api/ledger-entries/{entryId}` | Get a single ledger entry | All roles |
| POST | `/api/crediting-runs` | Post a notional crediting run for a plan (OCC-guarded) | BenefitsAdministrator |
| GET | `/api/crediting-runs` | List crediting runs, optionally filtered by plan | All roles |
| GET | `/api/crediting-runs/{runId}` | Get a crediting run | All roles |
| POST | `/api/crediting-runs/{runId}/reverse` | Reverse the latest `POSTED` run via compensating entries | BenefitsAdministrator |
| POST | `/api/rabbi-trusts` | Establish the rabbi trust for a plan (one per plan) | PlanSponsor |
| GET | `/api/rabbi-trusts` | List rabbi trusts, optionally filtered by plan | All roles |
| GET | `/api/rabbi-trusts/{trustId}` | Get a rabbi trust with assets, required funding, and posture | All roles |
| POST | `/api/rabbi-trusts/{trustId}/funding-events` | Append a trust funding event | TrustOfficer |
| POST | `/api/separation-cases` | Open a separation-from-service case | BenefitsAdministrator |
| GET | `/api/separation-cases` | List separation cases, optionally filtered by participant | All roles |
| GET | `/api/separation-cases/{caseId}` | Get a separation case with records and computed average | All roles |
| POST | `/api/separation-cases/{caseId}/service-records` | Append a service-fraction evidence record | BenefitsAdministrator |
| POST | `/api/separation-cases/{caseId}/determine` | Determine the separation outcome (segregated duty) | ComplianceOfficer |
| POST | `/api/separation-cases/{caseId}/reopen` | Reopen a determined case once within thirty days | BenefitsAdministrator |
| POST | `/api/specified-employee-lists` | Create a `DRAFT` specified-employee determination (OCC-guarded) | ComplianceOfficer |
| GET | `/api/specified-employee-lists` | List specified-employee lists, optionally filtered by plan | All roles |
| GET | `/api/specified-employee-lists/{listId}` | Get a specified-employee list with member flags | All roles |
| POST | `/api/specified-employee-lists/{listId}/members` | Add a member row to a `DRAFT` list | ComplianceOfficer |
| POST | `/api/specified-employee-lists/{listId}/finalize` | Finalize the selection waterfall and cascade member flags | ComplianceOfficer |
| POST | `/api/distribution-requests` | Request a distribution from an own account | Participant |
| GET | `/api/distribution-requests` | List distribution requests with filters | All roles |
| GET | `/api/distribution-requests/{requestId}` | Get a distribution request | All roles |
| POST | `/api/distribution-requests/{requestId}/verify-event` | Verify the distribution event per its type | ComplianceOfficer |
| POST | `/api/distribution-requests/{requestId}/schedule` | Lock the amount and compute the payment date | BenefitsAdministrator |
| POST | `/api/distribution-requests/{requestId}/pay` | Pay a `PAYABLE` request and run the account-close cascade | BenefitsAdministrator |
| POST | `/api/distribution-requests/{requestId}/deny` | Deny a `REQUESTED` or `EVENT_VERIFIED` request | ComplianceOfficer |
| POST | `/api/change-in-control-events` | Report a change in control for a plan | PlanSponsor |
| GET | `/api/change-in-control-events` | List change-in-control events, optionally filtered by plan | All roles |
| GET | `/api/change-in-control-events/{cicId}` | Get a change-in-control event | All roles |
| POST | `/api/change-in-control-events/{cicId}/adjudicate` | Verify or reject a reported change in control | ComplianceOfficer |
| POST | `/api/operational-failures` | Report an operational failure on an account | BenefitsAdministrator |
| GET | `/api/operational-failures` | List operational failure cases with filters | All roles |
| GET | `/api/operational-failures/{failureId}` | Get an operational failure case | All roles |
| POST | `/api/operational-failures/{failureId}/quantify` | Compute the income-inclusion amounts in pinned order | ComplianceOfficer |
| POST | `/api/operational-failures/{failureId}/assess-inclusion` | Assess income inclusion (segregated duty) | ComplianceOfficer |
| POST | `/api/operational-failures/{failureId}/correct` | Correct a quantified or assessed failure within the window | ComplianceOfficer |
| POST | `/api/document-findings` | Report a plan document failure | ComplianceOfficer |
| GET | `/api/document-findings` | List document findings, optionally filtered by plan | All roles |
| GET | `/api/document-findings/{findingId}` | Get a document finding | All roles |
| POST | `/api/document-findings/{findingId}/file-correction` | File a documentary correction within the window | ComplianceOfficer |
| POST | `/api/document-findings/{findingId}/adjudicate` | Adjudicate a filed correction | PlanSponsor |
| POST | `/_clock/set_current_utc` | Advance the logical clock and fire the scheduled sweep | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_STATE_INVALID` | 409 Conflict |
| `ERR_PARTICIPANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PARTICIPANT_STATE_INVALID` | 409 Conflict |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_ELECTION_NOT_MODIFIABLE` | 409 Conflict |
| `ERR_DUPLICATE_ELECTION` | 409 Conflict |
| `ERR_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_ELECTION_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_PERFORMANCE_ELECTION_TOO_LATE` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW_DATES` | 422 Unprocessable Entity |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CREDITING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_INDEX_RATE_MISSING` | 422 Unprocessable Entity |
| `ERR_CREDITING_RUN_STATE_INVALID` | 409 Conflict |
| `ERR_CREDITING_RUN_NOT_LATEST` | 409 Conflict |
| `ERR_DEFERRAL_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_VESTED_BALANCE` | 402 Payment Required |
| `ERR_EXCEEDS_EMERGENCY_NEED` | 402 Payment Required |
| `ERR_NEGATIVE_TRUST_ASSETS` | 402 Payment Required |
| `ERR_CIC_FUNDING_AMOUNT_MISMATCH` | 402 Payment Required |
| `ERR_EVENT_TYPE_NOT_PERMITTED` | 409 Conflict |
| `ERR_EVENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_DISTRIBUTION_STATE_INVALID` | 409 Conflict |
| `ERR_DISTRIBUTION_NOT_PAYABLE` | 409 Conflict |
| `ERR_PLAN_DOCUMENT_LAPSED` | 403 Forbidden |
| `ERR_OPEN_CASE_EXISTS` | 409 Conflict |
| `ERR_CASE_STATE_INVALID` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SERVICE_RECORD_GAP` | 409 Conflict |
| `ERR_SERVICE_RECORD_OVERLAP` | 409 Conflict |
| `ERR_SERVICE_FRACTION_CONTRADICTS_OUTCOME` | 409 Conflict |
| `ERR_CASE_REOPEN_LIMIT` | 409 Conflict |
| `ERR_REOPEN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CASE_HAS_PAID_DISTRIBUTIONS` | 409 Conflict |
| `ERR_LIST_STATE_INVALID` | 409 Conflict |
| `ERR_DRAFT_LIST_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_MEMBER` | 409 Conflict |
| `ERR_INVALID_EFFECTIVE_DATE` | 422 Unprocessable Entity |
| `ERR_CIC_STATE_INVALID` | 409 Conflict |
| `ERR_CIC_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_NO_VERIFIED_CIC` | 409 Conflict |
| `ERR_FAILURE_STATE_INVALID` | 409 Conflict |
| `ERR_CORRECTION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_FINDING_STATE_INVALID` | 409 Conflict |
| `ERR_TRUST_EXISTS` | 409 Conflict |
| `ERR_ACCOUNT_EXISTS` | 409 Conflict |
| `ERR_ACCOUNT_REQUIRED` | 409 Conflict |
| `ERR_CROSS_PLAN_REFERENCE` | 409 Conflict |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |

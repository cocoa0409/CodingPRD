# Legal Aid Intake API — Product Requirements Document

## 1. Introduction

A legal aid society lives under a double scarcity. Its attorneys and paralegals can carry only so many weighted cases at once, and its grant-funded work draws against finite funder budgets that arrive with strings attached — income caps, covered case types, covered counties, and reporting duties. Professional-conduct rules add a second kind of constraint: the person who screens an applicant may not be the person who approves opening their case, and the person who ran a conflict check may not be the person who waives it. This document specifies the Legal Aid Intake API, the system that operationalizes those constraints across the full life of a legal matter, from the first front-desk contact to final closure coding and funder reporting.

The API governs client registration and household financial profiles; income and priority screening against federal poverty guidelines; conflict-of-interest clearance with ethics review; eligibility determination, waitlisting, and capacity-driven promotion; the decision between advice-only and extended representation; case opening under grant funding rules; attorney and paralegal assignment under caseload ceilings; referral of cases to a pro bono panel; timekeeping, outcome coding, and closure; and the grant-program ledger with its periodic reports. All resources are exposed under the API's root path and are joined to one another by references rather than deep nesting, with a small number of sub-resource read views. A server-maintained logical clock — never the wall clock — decides every deadline, validity window, and reporting period in the system.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and cross-cutting principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly seven roles: `IntakeSpecialist`, `SupervisingAttorney`, `StaffAttorney`, `Paralegal`, `EthicsOfficer`, `GrantsManager`, and `ProgramDirector`. A request with a missing header, or whose `X-User-Role` is not one of these seven declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not listed among the roles permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

How `X-User-ID` is interpreted depends on the role. When `X-User-Role` is `IntakeSpecialist`, `SupervisingAttorney`, `StaffAttorney`, `Paralegal`, or `EthicsOfficer`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare the resource's foreign-key field to `X-User-ID`. This is what ties a `StaffAttorney`'s closure attempt to the case's `assigned_attorney_id`, a time log to the case's assigned attorney or paralegal, a screening to the application's `screened_by_staff_id`, and a conflict check to its `checked_by_staff_id`. When `X-User-Role` is `GrantsManager` or `ProgramDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `generated_by_user_id` on a `GrantReport`) but does not compare it to any entity's `id`.

The roles divide the work as follows. An `IntakeSpecialist` is the front-desk worker: registering and updating clients, filing applications, running screening and conflict checks, managing the documentation loop and the waitlist, and recording satisfaction surveys. A `SupervisingAttorney` makes service-level decisions, opens cases, assigns staff, manages referrals, and sets case posture; a senior-integrity rule bars them from opening a case they personally screened. A `StaffAttorney` works only their own assigned cases, with closure and time-logging scoped to those cases. A `Paralegal` logs time only on cases where they are the assigned paralegal. An `EthicsOfficer` arbitrates conflict checks flagged as potential conflicts, and may not resolve a check they personally ran. A `GrantsManager` generates, submits, and revises grant reports but administers no grant programs; their read access covers the general list and detail views except the conflict-check and waitlist views, whose tables list only the roles explicitly permitted there. A `ProgramDirector` administers staff, the pro bono panel, venue rules, and grant programs; accepts or returns grant reports; and operates the daily sweep and the logical clock.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The waitlist listing is the documented exception: it presents entries in ranking order, as described in §3.4.

### 2.4. The Logical Clock

The server maintains a logical clock that governs every temporal decision in the system. Before it has ever been set, the clock reads exactly 2026-08-01T00:00:00Z; it never falls back to the wall clock. A `ProgramDirector` may advance it through an admin-only test-driving capability that sets the clock to a supplied `to_iso8601` instant. Every deadline and period comparison in this document — a conflict check's `valid_until`, a referral's `response_deadline`, an advice-only case's `advice_deadline`, and a grant program's `period_start`/`period_end` window — reads this clock. All timestamps the system stamps onto records (`screened_at`, `checked_at`, `offered_at`, `responded_at`, `resolved_at`, `opened_at`, `closed_at`) are taken from the same clock.

Deadline comparisons are strict throughout: a deadline has passed only when the clock reads strictly later than the deadline. A deadline exactly equal to the current clock reading has not passed and triggers nothing.

### 2.5. Common Resource Properties

Nine primary resources — `Client`, `IntakeApplication`, `ConflictCheck`, `Case`, `StaffMember`, `ReferralPanelMember`, `Referral`, `GrantProgram`, and `GrantReport` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 and increments by one on every mutation; it anchors optimistic concurrency control (§2.8).

Five auxiliary resources — `VenueRule`, `TimeEntry`, `SatisfactionSurvey`, `UnmetNeedRecord`, and `WaitlistEntry` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. On a `WaitlistEntry`, `created_at` doubles as the queue timestamp: it is the tie-breaker in waitlist ranking (§3.4).

### 2.6. Identifier Resolution in Nested Paths

Requests that target nested resources resolve their path identifiers in strict left-to-right order. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource — an application identifier is validated before a conflict-check identifier beneath it, a case identifier before a time entry beneath it, and so on. The same `ERR_NOT_FOUND` rejection applies when a request body carries a foreign-key reference that does not resolve: `client_id`, `attorney_id`, `paralegal_id`, `panel_member_id`, `grant_program_id`, or `supervising_attorney_id`.

### 2.7. Validation Order and Error Precedence

Every request is evaluated against a fixed cascade of checks, and the first failing check determines the rejection — later checks are not consulted. The cascade runs in this order:

1. Authentication: missing headers or an undeclared role produce `ERR_UNAUTHENTICATED`.
2. Role authorization: a declared role not listed for the endpoint produces `ERR_UNAUTHORIZED_ROLE`.
3. Path-identifier resolution, left to right per §2.6, producing `ERR_NOT_FOUND`.
4. Ownership scope: for example, a `StaffAttorney` attempting to close a case assigned to another attorney is stopped with `ERR_CASE_NOT_ASSIGNED_TO_YOU`, and a time log by anyone other than the case's assigned attorney or paralegal is stopped with `ERR_TIME_ENTRY_FORBIDDEN`.
5. Request shape: missing required fields, unknown fields, bad enum values, or range violations — a satisfaction `score` outside 1–5, `hours` outside 0.25–24.00, an end date not after its start date, a `household_size` below 1, negative cent amounts — produce `ERR_INVALID_REQUEST`.
6. Body foreign-key existence, producing `ERR_NOT_FOUND` as in §2.6.
7. State-machine legality: the target entity must currently be in a from-state of the requested transition, else the request fails with the entity's invalid-state error — `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_CASE_STATE`, `ERR_INVALID_REFERRAL_STATE`, `ERR_INVALID_GRANT_STATE`, or `ERR_INVALID_REPORT_STATE`.
8. Optimistic concurrency per §2.8, producing `ERR_STALE_VERSION`.
9. Segregation-of-duties safety gates, producing `ERR_ETHICS_RECUSAL` or `ERR_SELF_SCREENING_APPROVAL` (§3.3, §3.5).
10. Substantive business constraints, in the order each workflow states them: determination agreement (`ERR_DETERMINATION_MISMATCH`), venue determinability (`ERR_VENUE_UNDETERMINED`), duplicate open cases (`ERR_DUPLICATE_OPEN_CASE`), extended-representation permission (`ERR_EXTENDED_REP_NOT_PERMITTED`), venue-rule uniqueness (`ERR_VENUE_RULE_CONFLICT`), supervision validity (`ERR_INVALID_SUPERVISOR`), referral placement (`ERR_CASE_PLACEMENT_CONFLICT`), panel-member status (`ERR_PANEL_MEMBER_NOT_ACTIVE`), coverage (`ERR_STAFF_COVERAGE_MISMATCH`, `ERR_PANEL_COVERAGE_MISMATCH`), paralegal supervision (`ERR_PARALEGAL_SUPERVISION_MISMATCH`), survey guards (`ERR_CASE_NOT_CLOSED`, `ERR_DUPLICATE_SURVEY`), staff separation (`ERR_STAFF_HAS_OPEN_CASES`), and panel retirement (`ERR_PANEL_HAS_ACTIVE_PLACEMENTS`).
11. Temporal window rules: grant period activity (`ERR_GRANT_PERIOD_INACTIVE`), grant period overlap on creation (`ERR_GRANT_PERIOD_OVERLAP`), and referral service-window overlap (`ERR_PANEL_WINDOW_OVERLAP`).
12. Grant coverage and income referential checks: `ERR_GRANT_CASE_TYPE_EXCLUDED`, `ERR_GRANT_COUNTY_EXCLUDED`, and `ERR_GRANT_INCOME_OVER_CAP`.
13. Fiscal checks: the extended-capacity pool (`ERR_NO_EXTENDED_CAPACITY`), caseload ceilings (`ERR_CASELOAD_CAPACITY_EXCEEDED`), grant budget sufficiency (`ERR_GRANT_BUDGET_EXHAUSTED`), panel capacity (`ERR_PANEL_CAPACITY_REACHED`), and reservation drain at grant close (`ERR_GRANT_HAS_RESERVED_FUNDS`).

Where a workflow pins a more specific order — the open-case gauntlet (§3.5) and the daily sweep (§3.9) both do — the pinned order governs within that workflow.

### 2.8. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and each names its own version field:

- Assigning (or reassigning) an attorney to a case requires the request to carry `expected_case_version`, the client's last observed `version` of that case. Because assignment from `OPEN` legitimately supersedes a prior assignment, a second sequential request carrying the pre-supersede version would otherwise observe a valid state and succeed; the version check is what condemns it. If `expected_case_version` does not match the case's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting an assignment it has not observed.
- Rescreening an application requires the request to carry `expected_application_version`, the client's last observed `version` of that application, for the same reason: rescreening legitimately supersedes a prior screening outcome, and a stale `expected_application_version` is what condemns a request that has not observed the latest one. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; attempting to pass one elsewhere is an unknown-field rejection under step 5 of §2.7.

### 2.9. Precision, Rounding, and Monetary Values

All money in the system is represented as integer cents — client incomes, grant budgets, rates, reservations, and spending alike. Percentages (`gross_poverty_percentage`, `countable_poverty_percentage`, `priority_score`, `income_cap_percentage`) and `total_hours` aggregates are rounded half-up to exactly two decimal places. Grant reservations are rounded half-up to a whole cent per case before any summation, per the pinned rounding order in §3.5. Caseload figures (`case_weight`, `weighted_open_units`, `open_case_count`, `available_units`, `max_units`) are integers with no rounding.

### 2.10. Caseload Accounting in Weight Units

Attorney capacity is measured in weight units. An `EXTENDED` case weighs 5 units and an `ADVICE_ONLY` case weighs 2 units; the weight is stored on the case as `case_weight`. A member's `weighted_open_units` is the sum of `case_weight` over exactly those cases assigned to the member as attorney whose status is `OPEN` — `PENDING_ASSIGNMENT` and `ON_HOLD` cases contribute nothing, and paralegal assignments never add load to anyone. The member's `open_case_count` counts that same case set by heads rather than by weight: one `EXTENDED` case plus three `ADVICE_ONLY` cases yields an `open_case_count` of 4 but `weighted_open_units` of 11 — identical data, two different numbers, each with its own audience. A member's `available_units` is their `max_units` minus their `weighted_open_units`. A computed caseload read on any staff member exposes `weighted_open_units`, `open_case_count`, `max_units`, `available_units`, and `utilization_pct`.

### 2.11. Grant Ledger Conservation

Every `GrantProgram` maintains a three-bucket ledger: `reserved_cents` (funds committed to live cases), `spent_cents` (funds irrevocably converted at closure), and `available_cents` (everything left). The ledger conserves funds at all times: `reserved_cents` plus `spent_cents` plus `available_cents` always equals `total_budget_cents`, with `available_cents` defined as the budget minus reserved minus spent. A case's reservation counts toward its program's `reserved_cents` while the case's `funding_status` is `GRANT_RESERVED` or `GRANT_FROZEN` — a freeze never releases the reservation. A computed utilization read on any program exposes `total_budget_cents`, `reserved_cents`, `spent_cents`, `available_cents`, and `utilization_pct`.

## 3. Business Logic & Workflows

### 3.1. Client Registration and Household Finances

An `IntakeSpecialist` registers each applicant as a `Client`, capturing the client's `full_name`, the `residence_county` where they live, the `household_size` (an integer that must be at least 1), and two income figures in non-negative integer cents: `annual_gross_income_cents`, the household's gross annual income, and `annual_countable_income_cents`, the countable annual income that excludes means-tested benefits and later drives the grant screen. A boolean `receives_means_tested_benefits` records whether the household receives means-tested benefits, which matters because such households auto-pass the standard income screen. The registration may also list `vulnerability_factors` — zero or more of `ELDERLY`, `DISABLED`, `DV_SURVIVOR`, `LIMITED_ENGLISH`, `HOMELESS`, and `VETERAN`; when omitted, the list defaults to empty. A new client's `status` is `ACTIVE`.

An intake specialist may later update any of these profile fields, and may also archive a client by setting `status` to `ARCHIVED`; archiving is inert and cascades to nothing. Changing any financial field, however — `household_size`, `annual_gross_income_cents`, `annual_countable_income_cents`, `receives_means_tested_benefits`, or `residence_county` — invalidates every pending determination for that client: each of the client's applications sitting in `SCREENED`, `ELIGIBLE`, or `INELIGIBLE` returns to `SUBMITTED` for a fresh screen, and an application sitting in `WAITLISTED` returns to `SUBMITTED` with its waitlist entry deleted, since an entry may exist only for a waitlisted application. Every such profile update bumps the client's `version`. The client register can be read back filtered by `residence_county` or `status`.

### 3.2. From Application to Eligibility Determination

Work on a legal matter begins when an `IntakeSpecialist` files an `IntakeApplication` for a registered client: the payload names the applicant via `client_id`, classifies the matter as one of six case types — `EVICTION_DEFENSE`, `FAMILY_DV`, `BENEFITS_APPEAL`, `CONSUMER_DEBT`, `IMMIGRATION_RELIEF`, or `EXPUNGEMENT` — through `case_type`, records the adverse party as `opposing_party_name` for conflict checking, and places the matter geographically via `incident_county`, the county that drives venue determination. A free-text `incident_description` may summarize the problem and defaults to empty. A new application starts in `SUBMITTED` with `version` 1, and the application register supports filtering by `client_id`, `status`, `case_type`, and `incident_county`.

Screening is the pivotal act. When an intake specialist screens a `SUBMITTED` application, the system first looks for a venue rule covering the pair of `incident_county` and `case_type`; if no such rule exists, the screen fails with `ERR_VENUE_UNDETERMINED` (HTTP 422). Otherwise the screen computes and stores five values in one pass. The application's `venue` is copied from the matching rule, one of `SUPERIOR_COURT`, `HOUSING_COURT`, `FAMILY_COURT`, `MUNICIPAL_COURT`, `ADMIN_TRIBUNAL`, or `FEDERAL_TRIBUNAL`. Two poverty percentages are computed against the federal poverty guideline: for a household, the guideline is 1,506,000 cents ($15,060.00) for the first household member plus 538,000 cents ($5,380.00) for each additional member, and each percentage is the relevant income in cents divided by the household's guideline in cents, multiplied by one hundred, and rounded half-up to two decimal places. The **standard screen** divides `annual_gross_income_cents` by the guideline to produce `gross_poverty_percentage`; the household passes when `receives_means_tested_benefits` is true or the resulting percentage is at most 125.00 — a value of exactly 125.00 passes — and the outcome is stored as `eligibility_determination`, either `ELIGIBLE` or `INELIGIBLE`. The **grant screen** substitutes `annual_countable_income_cents` to produce `countable_poverty_percentage`; it has no benefits auto-pass and renders no verdict at screen time, deferring judgment to case opening, where the stored percentage is compared against the chosen program's `income_cap_percentage`. Both percentages are computed and stored on every screen, even though only the standard variant drives `eligibility_determination`.

The fifth computed value is `priority_score`. It starts from the matching venue rule's `priority_base_weight`, an integer from 1 to 100, and multiplies that base by a vulnerability multiplier: one plus 0.15 for each of the client's `vulnerability_factors`, capped at 1.75 — no factors means a multiplier of 1.00, and five or more factors reaches the 1.75 ceiling. An urgency increment is then added: 20 when the `case_type` is `EVICTION_DEFENSE` or `FAMILY_DV`, 10 when it is `BENEFITS_APPEAL`, and 0 for the other case types. The sum is rounded half-up to two decimal places, and anything above 100.00 is capped at 100.00. The screen also stamps `screened_by_staff_id` with the acting specialist's `X-User-ID` and `screened_at` with the logical clock — both become segregation-of-duties anchors later.

After screening, the specialist records the determination by submitting a `determination` input, and the application leaves `SCREENED` for `ELIGIBLE` or `INELIGIBLE`. The submitted value must equal the computed `eligibility_determination`; a contradiction is rejected with `ERR_DETERMINATION_MISMATCH` (HTTP 409). A decision of `INELIGIBLE` also records the unmet need: the system creates an `UnmetNeedRecord` with `reason_code` `OVER_INCOME` for the application.

When household finances change, an intake specialist may also correct the record directly. From `SUBMITTED`, the application can be moved to `DOCS_REQUESTED` — the request may carry an optional `request_note` — and submitting documents returns it to `SUBMITTED` for a fresh screen; the loop may repeat as needed. A `SUBMITTED` application is the only one that can be screened.

Rescreening is the deliberate-reset path. From either `ELIGIBLE` or `INELIGIBLE`, an intake specialist may send the application back to `SUBMITTED`, but the request must carry `expected_application_version` matching the application's current `version` (§2.8); a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful rescreen increments the application's `version` by one; on the `ELIGIBLE` branch the previously computed screen fields — `venue`, both percentages, `priority_score`, and `eligibility_determination` — are retained until a subsequent screen overwrites them, and the same version-incrementing reset applies on the `INELIGIBLE` branch.

Withdrawal ends the journey early. An intake specialist may withdraw an application from any non-terminal state, optionally recording a `withdrawal_reason`. Withdrawal from `SUBMITTED`, `DOCS_REQUESTED`, `SCREENED`, or `ELIGIBLE` creates an `UnmetNeedRecord` with `reason_code` `CLIENT_WITHDRAWN`; withdrawal from `INELIGIBLE` creates no record, because the unmet need was already recorded at the decision; withdrawal from `WAITLISTED` deletes the application's waitlist entry and creates the `CLIENT_WITHDRAWN` record. `OPENED` and `WITHDRAWN` are terminal, and any attempted transition from a state that is not a from-state of the requested action is rejected with `ERR_INVALID_APPLICATION_STATE` (HTTP 409).

### 3.3. Conflict Clearance and Ethics Review

No case may open while conflict questions hang unresolved. An `IntakeSpecialist` runs a conflict check against an application — naming its `result` as `CLEAR` or `POTENTIAL_CONFLICT` and optionally attaching `notes` — and the system stamps the check with `checked_by_staff_id` from the acting specialist's `X-User-ID` and `checked_at` from the logical clock. Every check is born with a validity window: `valid_until` is exactly 45 days after `checked_at`. Each new check is created directly into `CLEAR` or `POTENTIAL_CONFLICT`; the checks for an application can be listed through the application's sub-resource view.

A `POTENTIAL_CONFLICT` check awaits adjudication by an `EthicsOfficer`, who resolves it with a `resolution` of either `CONFIRMED_CONFLICT` or `WAIVED`. Ethics segregation of duties binds here: the resolving officer's `X-User-ID` must differ from the check's `checked_by_staff_id`, and a self-resolution attempt is rejected with `ERR_ETHICS_RECUSAL` (HTTP 403). Choosing `WAIVED` additionally requires a non-empty `waiver_reason`; its absence is rejected with `ERR_INVALID_REQUEST`. Either resolution stamps `resolved_by_staff_id` and `resolved_at` from the acting officer and the clock. Confirming a conflict records the unmet need — an `UnmetNeedRecord` with `reason_code` `CONFLICT_CONFIRMED` is created for the linked application — while waiving it clears the path to case opening. `CONFIRMED_CONFLICT` is terminal.

Time erodes clearance. During the daily sweep, every check in `CLEAR` or `WAIVED` whose `valid_until` lies strictly before the current logical clock transitions to `EXPIRED`, which is also terminal. What an expired or missing clearance means at case-opening time is part of the gauntlet in §3.5.

### 3.4. Waitlist Dynamics and Unmet-Need Data

An eligible application is not always openable the moment capacity runs short. An intake specialist may move an `ELIGIBLE` application to `WAITLISTED`; doing so creates a `WaitlistEntry` that freezes the application's current `priority_score` into `priority_score_snapshot` and computes a `required_weight` of 5 when that snapshot is at least 60.00, or 2 otherwise. At most one waitlist entry may exist per application, and the enqueue also records the unmet need with an `UnmetNeedRecord` whose `reason_code` is `NO_EXTENDED_CAPACITY`.

Promotion is a waterfall run by the daily sweep, after the sweep's expiry and auto-close steps. The promotion pool is the sum of `available_units` across all staff members whose `staff_type` is `ATTORNEY` and whose `status` is `ACTIVE` — members `ON_LEAVE` or `SEPARATED` contribute zero — and it is computed against post-auto-close loads, so closures earlier in the same sweep free capacity that promotion can immediately consume. Entries are considered in ranking order: `priority_score_snapshot` descending, ties broken by `created_at` ascending, with no further tie-breakers. An entry whose `required_weight` fits within the remaining pool is promoted: its application moves from `WAITLISTED` back to `ELIGIBLE`, the application's `promoted_from_waitlist` flag becomes true, the entry is deleted, and the pool shrinks by that entry's `required_weight`. An entry that does not fit is skipped without blocking later entries — there is no head-of-line blocking — and entries surviving the sweep remain waitlisted with their original snapshots. The waitlist listing presents entries in this same ranking order and can be filtered by `application_id`.

The `UnmetNeedRecord` is the system's demand-side ledger. Each record carries the originating `application_id`, a `reason_code` of `OVER_INCOME`, `NO_EXTENDED_CAPACITY`, `CONFLICT_CONFIRMED`, or `CLIENT_WITHDRAWN`, and echoes the application's `case_type` and `incident_county` so aggregate reporting needs no joins. Records are created at exactly four moments — an ineligible decision, a waitlist enqueue, a confirmed conflict, and a withdrawal from any state except `INELIGIBLE` — and the register can be filtered by `application_id` or `reason_code`.

### 3.5. Opening a Case: The Validation Gauntlet and Grant Reservation

Only a `SupervisingAttorney` may open a case, and only from an application in `ELIGIBLE`. The request names the intended `service_level` — `ADVICE_ONLY` or `EXTENDED` — and may optionally carry a `grant_program_id` to fund the case from a grant. Before anything is created, the request runs a gauntlet whose order is pinned; the first failure wins:

1. Self-screening segregation: the acting attorney's `X-User-ID` must differ from the application's `screened_by_staff_id`, else the request is rejected with `ERR_SELF_SCREENING_APPROVAL` (HTTP 403).
2. Conflict resolution: the application's latest conflict check — the one with the greatest `created_at` — must exist and hold a `result` of `CLEAR` or `WAIVED`. A missing check, a `POTENTIAL_CONFLICT`, or a `CONFIRMED_CONFLICT` is rejected with `ERR_CONFLICT_UNRESOLVED` (HTTP 409).
3. Conflict recency: that latest check's `valid_until` must not lie in the past relative to the logical clock; a stale clearance is rejected with `ERR_CONFLICT_CHECK_STALE` (HTTP 409).
4. Duplicates: no other case may exist for the same client and the same `case_type` in `PENDING_ASSIGNMENT`, `OPEN`, or `ON_HOLD`, else `ERR_DUPLICATE_OPEN_CASE` (HTTP 409).
5. Service-level permission: the gate reads the application's stored `priority_score` — it does not recompute it. An `EXTENDED` request requires that score to be at least 60.00, with 60.00 itself qualifying, and requires the matching venue rule's `extended_eligible` to be true; otherwise the request fails with `ERR_EXTENDED_REP_NOT_PERMITTED` (HTTP 422).
6. Extended-capacity pool: computed from pre-opening state, since the case being opened contributes nothing yet — the pool is the sum of `available_units` across staff members whose `staff_type` is `ATTORNEY` and whose `status` is `ACTIVE`. An `EXTENDED` request requires at least one such attorney with `available_units` of at least 5, else `ERR_NO_EXTENDED_CAPACITY` (HTTP 409). `ADVICE_ONLY` imposes no pool check at open time; the assignment-time ceiling in §3.6 still applies later.
7. Grant gates, evaluated only when a `grant_program_id` was supplied: the logical clock's date must fall within the program's closed interval from `period_start` through `period_end`, both ends inclusive, else `ERR_GRANT_PERIOD_INACTIVE` (HTTP 409); the application's `case_type` must appear in the program's `allowed_case_types`, else `ERR_GRANT_CASE_TYPE_EXCLUDED` (HTTP 422); the application's `incident_county` must appear in `allowed_counties`, else `ERR_GRANT_COUNTY_EXCLUDED` (HTTP 422); the application's `countable_poverty_percentage` — the grant-screen variant, with no benefits auto-pass — must be at most the program's `income_cap_percentage`, else `ERR_GRANT_INCOME_OVER_CAP` (HTTP 422); and the program's `available_cents` must cover this case's reservation, else `ERR_GRANT_BUDGET_EXHAUSTED` (HTTP 409).

The gate itself never mutates load; capacity moves only at assignment.

Success creates the `Case` (HTTP 201). Its `application_id` ties it to the originating application, `venue` is copied from the application, `placement` starts as `INTERNAL`, `status` starts as `PENDING_ASSIGNMENT`, and both `assigned_attorney_id` and `assigned_paralegal_id` start null. The funding axis initializes alongside: when a grant was named, the case's `funding_status` becomes `GRANT_RESERVED` and its reservation is computed at open time — the program's `per_case_rate_cents` multiplied by the case's `case_weight` and divided by 5, rounded half-up to a whole cent, stored on the case as `reserved_cents`. The rounding order is pinned: each case's reservation is rounded individually to whole cents, and the program's `reserved_cents` is the sum of those whole-cent integers; summing unrounded reservations and rounding once at the program level is forbidden. With a rate of 33,333 cents, for instance, each advice-only case reserves the rate multiplied by two-fifths — 13,333.20 cents before rounding, 13,333 after — so three advice-only cases tie up 39,999 cents of program budget, not 40,000. When no grant was named, the case is `UNFUNDED` with a `reserved_cents` of 0 and touches no ledger. The program's `reserved_cents` rises by the new case's reservation as the opening commits, keeping the conservation invariant of §2.11 intact.

### 3.6. Attorney Assignment and Caseload Discipline

A `ProgramDirector` onboards each `StaffMember` with a `full_name`, a `staff_type` of `ATTORNEY`, `PARALEGAL`, or `INTAKE_SPECIALIST`, the `admitted_counties` the member may serve, and the `practice_areas` — case-type values — the member handles. Capacity is set through `max_units`, an integer of at least 1 that defaults to 40 when omitted. A paralegal must be supervised: when `staff_type` is `PARALEGAL`, `supervising_attorney_id` is required and must reference a member whose `staff_type` is `ATTORNEY`, and the supervision chain must remain acyclic; a missing supervisor, a non-attorney supervisor, or a cycle is rejected with `ERR_INVALID_SUPERVISOR` (HTTP 422), both at onboarding and on any later staff update. New members start `ACTIVE` with zeroed load fields. The staff register supports filtering by `supervising_attorney_id`, `staff_type`, `status`, a single `practice_area`, or a single `county`.

Assignment is a `SupervisingAttorney` act whose payload carries `attorney_id`, an optional `paralegal_id`, and — always — `expected_case_version` per §2.8. A first assignment moves the case from `PENDING_ASSIGNMENT` to `OPEN`; an assignment against an `OPEN` case stays in `OPEN` and supersedes the current assignment, and on that superseding path the case's `placement` must still be `INTERNAL`, else `ERR_CASE_PLACEMENT_CONFLICT` (HTTP 409). The same assignee checks guard both paths: the designated attorney must exist as a resolvable reference, hold `staff_type` `ATTORNEY`, and be `ACTIVE`, otherwise `ERR_STAFF_NOT_ACTIVE` (HTTP 409); the attorney's `practice_areas` must contain the application's `case_type` and their `admitted_counties` must contain the `incident_county`, otherwise `ERR_STAFF_COVERAGE_MISMATCH` (HTTP 422); a supplied paralegal must be a `PARALEGAL`, be `ACTIVE`, and be supervised by the attorney being assigned — `supervising_attorney_id` pointing at that attorney — otherwise `ERR_PARALEGAL_SUPERVISION_MISMATCH` (HTTP 422); and the attorney's `weighted_open_units` plus the case's `case_weight` must not exceed their `max_units`, with an exactly-full load permitted, otherwise `ERR_CASELOAD_CAPACITY_EXCEEDED` (HTTP 409).

A successful assignment writes `assigned_attorney_id` and, when provided, `assigned_paralegal_id`; it raises the attorney's `weighted_open_units` by the case's `case_weight` and their `open_case_count` by one, while paralegal load never changes. On reassignment, the outgoing attorney — if any, and if different — first sheds the case's weight and count before the incoming attorney picks them up. The first arrival at `OPEN` stamps `opened_at` from the logical clock, and when the case is `ADVICE_ONLY` it also sets `advice_deadline` to exactly 30 days after `opened_at`. Every assignment or reassignment increments the case's `version` by one.

Posture changes are the supervising attorney's other lever. Placing a hold moves a case from `OPEN` to `ON_HOLD` — the request may carry an optional `hold_reason` — and releases the assigned attorney's `weighted_open_units` by the case's `case_weight`, since only `OPEN` cases count toward load. Resuming moves a case from `ON_HOLD` back to `OPEN`, but only after re-checking that the assigned attorney, if any, is still `ACTIVE` — else `ERR_STAFF_NOT_ACTIVE` — and still has room, with the same equality-permitted ceiling, else `ERR_CASELOAD_CAPACITY_EXCEEDED`; a successful resume adds the weight back. Staff status itself is guarded: a member cannot be moved to `SEPARATED` while any case in `OPEN` or `ON_HOLD` remains assigned to them, an attempt failing with `ERR_STAFF_HAS_OPEN_CASES` (HTTP 409). Case actions attempted from a posture that does not permit them fail with `ERR_INVALID_CASE_STATE` (HTTP 409).

### 3.7. Pro Bono Referrals and the Panel

The society's pro bono reach runs through a panel. A `ProgramDirector` adds each `ReferralPanelMember` with a `full_name`, an optional `firm_name` defaulting to empty, the `practice_areas` they accept, the `counties` they serve, and `max_active_referrals`, an integer of at least 1 capping how many accepted-but-unfinished placements they may hold. Panel members start `ACTIVE` with an `active_referral_count` of 0, and the panel register filters by `status`, a single `practice_area`, or a single `county`.

A `SupervisingAttorney` offers a case to the panel by creating a referral whose payload names a `panel_member_id` and may carry `notes`. The target case must be `INTERNAL` in `placement` and in `PENDING_ASSIGNMENT` or `OPEN` status, else `ERR_CASE_PLACEMENT_CONFLICT` (HTTP 409). The panel member must be `ACTIVE` at offer time, else `ERR_PANEL_MEMBER_NOT_ACTIVE` (HTTP 409); their `practice_areas` and `counties` must cover the case's `case_type` and `incident_county`, else `ERR_PANEL_COVERAGE_MISMATCH` (HTTP 422); and their `active_referral_count` must be strictly below `max_active_referrals`, else `ERR_PANEL_CAPACITY_REACHED` (HTTP 409). A successful offer creates the referral in `OFFERED`, stamping `offered_at` from the clock and setting `response_deadline` exactly 10 days later.

Responding is shared between `SupervisingAttorney` and `ProgramDirector`, via a `decision`. A `decision` of `ACCEPT` requires both `service_start_date` and `service_end_date`, with the end strictly after the start, else `ERR_INVALID_REQUEST`; it re-verifies that the panel member is still `ACTIVE` and still under capacity, with the same `ERR_PANEL_MEMBER_NOT_ACTIVE` and `ERR_PANEL_CAPACITY_REACHED` rejections; and it enforces window exclusivity — no other `ACCEPTED` referral for the same panel member may have a half-open service window from `service_start_date` up to but not including `service_end_date` that overlaps the requested window, where two windows that merely touch, one's end equal to the other's start, do not overlap. A violating acceptance is rejected with `ERR_PANEL_WINDOW_OVERLAP` (HTTP 409). Acceptance stamps `responded_at`, flips the case's `placement` to `PRO_BONO`, and — when the case was still `PENDING_ASSIGNMENT` — moves it to `OPEN` with `opened_at` stamped, since a pro bono placement satisfies assignment without consuming any attorney load; the case's `assigned_attorney_id` remains null while it is pro bono–placed; if that case is `ADVICE_ONLY` and has no `advice_deadline` yet, the deadline is set to 30 days after `opened_at`. The panel member's `active_referral_count` rises by one. A `decision` of `DECLINE` simply stamps `responded_at` and lands in `DECLINED`, optionally recording a `decline_reason`.

Withdrawal of a referral is a `SupervisingAttorney` act with an optional `withdrawal_reason`. An `OFFERED` referral withdraws freely. Withdrawing an `ACCEPTED` referral is allowed only while the case is not `CLOSED`, else `ERR_INVALID_CASE_STATE`; it pulls the case's `placement` back to `INTERNAL`, and if the case has no `assigned_attorney_id` it drops from `OPEN` back to `PENDING_ASSIGNMENT`, while the panel member's `active_referral_count` falls by one. Two system events close placements out: the daily sweep expires any `OFFERED` referral whose `response_deadline` lies strictly before the clock, moving it to `EXPIRED`; and closing a case moves any of its `ACCEPTED` referrals to `COMPLETED`, decrementing the panel member's count. `DECLINED`, `EXPIRED`, `WITHDRAWN`, and `COMPLETED` are terminal, and referral actions from impermissible states fail with `ERR_INVALID_REFERRAL_STATE` (HTTP 409). A panel member cannot be retired to `INACTIVE` while their `active_referral_count` is above zero — the attempt fails with `ERR_PANEL_HAS_ACTIVE_PLACEMENTS` (HTTP 409) — and the referral register filters by `case_id`, `panel_member_id`, or `status`.

### 3.8. Timekeeping, Closure Coding, and Client Satisfaction

Work on an open matter is logged as `TimeEntry` records. Logging is permitted to `StaffAttorney`, `Paralegal`, and `SupervisingAttorney` roles, but ownership binds tighter than role: the actor must be the case's assigned attorney or its assigned paralegal, and anyone else is rejected with `ERR_TIME_ENTRY_FORBIDDEN` (HTTP 403) before anything else about the entry is considered. Time may be logged only while the case is `OPEN`; an attempt against a case in any other status fails with `ERR_INVALID_CASE_STATE`. Each entry records `hours` — a number from 0.25 to 24.00 with two decimal places — an `activity_code` of `RESEARCH`, `CLIENT_MEETING`, `COURT_APPEARANCE`, `DRAFTING`, or `ADMIN`, and the `work_date` on which the work occurred; the entry's `staff_id` is set from the actor's `X-User-ID` and its `case_id` from the case it was logged against. The time ledger can be listed filtered by `case_id` or `staff_id`.

Closure is the most consequential act on a case. A `StaffAttorney` may close only their own case — the case's `assigned_attorney_id` must equal their `X-User-ID`, else `ERR_CASE_NOT_ASSIGNED_TO_YOU` (HTTP 403) — while a `SupervisingAttorney` may close any case. Closure is permitted from `OPEN` and from `ON_HOLD`, and a `SupervisingAttorney` may additionally close a case still in `PENDING_ASSIGNMENT`. Every closure requires an `outcome_code` — one of `FULL_WIN`, `PARTIAL_WIN`, `SETTLEMENT`, `ADVICE_GIVEN`, `REFERRED_OUT`, `WITHDRAWN_BY_CLIENT`, or `ADMINISTRATIVE` — and a missing or invalid code is rejected with `ERR_INVALID_REQUEST`; a `closure_reason` note is optional.

Closure fires a fixed set of side effects. The case's `closed_at` is stamped from the logical clock. Closing from `OPEN` releases the assigned attorney's `weighted_open_units` by the case's `case_weight` and decrements their `open_case_count`; closing from `ON_HOLD` changes no load, because the weight was already released at hold time; closing from `PENDING_ASSIGNMENT` changes no load, because none was ever added. The funding ledger then settles per §2.11: for a case whose `funding_status` is `GRANT_RESERVED` or `GRANT_FROZEN`, a billable outcome — `FULL_WIN`, `PARTIAL_WIN`, `SETTLEMENT`, or `ADVICE_GIVEN` — converts the reservation, decreasing the program's `reserved_cents` by the case's `reserved_cents`, increasing its `spent_cents` by the same amount, and moving the case to `GRANT_SPENT`; a non-billable outcome — `REFERRED_OUT`, `WITHDRAWN_BY_CLIENT`, or `ADMINISTRATIVE` — releases the reservation, decreasing `reserved_cents` and moving the case to `GRANT_RELEASED` so the funds return to availability. Finally, any referral for the case still in `ACCEPTED` moves to `COMPLETED`, and the panel member's `active_referral_count` falls by one. `CLOSED` is terminal.

Some closures need no human hand. The daily sweep auto-closes every `ADVICE_ONLY` case still `OPEN` whose `advice_deadline` lies strictly before the clock, stamping `outcome_code` as `ADMINISTRATIVE` and `closure_reason` as `ADVICE_WINDOW_EXPIRED`, and firing the full closure side effects above — attorney load release, grant release (the outcome is non-billable), and referral completion.

After closure, the client voice is captured once. An `IntakeSpecialist` may record a `SatisfactionSurvey` only against a `CLOSED` case, else `ERR_CASE_NOT_CLOSED` (HTTP 409), and at most one survey may exist per case — a second attempt is rejected with `ERR_DUPLICATE_SURVEY` (HTTP 409). The survey carries a `score` as an integer from 1 to 5 inclusive, a `would_recommend` boolean, and optional `comments` defaulting to empty; surveys are immutable once recorded, and a case's survey list therefore returns zero or one record.

### 3.9. Operations Administration: Venue Rules, Grant Programs, Reporting, and the Daily Sweep

The `ProgramDirector` maintains the reference data that screening depends on. Each `VenueRule` maps a `county` and a `case_type` to the `venue` that matters arising there take, along with the `priority_base_weight` — an integer from 1 to 100 — that seeds the priority score, and an `extended_eligible` flag declaring whether that county-and-case-type combination may receive `EXTENDED` representation. The pair of `county` and `case_type` is unique across rules; a duplicate creation is rejected with `ERR_VENUE_RULE_CONFLICT` (HTTP 409). Rules can be listed filtered by `county` or `case_type`.

Grant programs are the funding containers. Creating one takes a `name`, a `funder`, a closed reporting interval from `period_start` through `period_end` — the end must not precede the start — the `allowed_case_types` and `allowed_counties` the grant may fund, the `income_cap_percentage` applied at case opening, the `per_case_rate_cents` base drawdown for a weight-5 case (an advice-only case, weight 2, draws two-fifths of that rate), and the `total_budget_cents`, a non-negative integer. Two programs from the same `funder` may not have overlapping closed periods, and boundary-touching counts: one program's `period_end` equal to another's `period_start` is an overlap, rejected with `ERR_GRANT_PERIOD_OVERLAP` (HTTP 409). A new program starts `ACTIVE` with `reserved_cents` and `spent_cents` at zero and `available_cents` equal to `total_budget_cents`; the program register filters by `funder` or `status`.

Suspension propagates through three cascade links. When a `ProgramDirector` suspends an `ACTIVE` program, every case funded by that program whose `funding_status` is `GRANT_RESERVED` moves to `GRANT_FROZEN` — link one. The freeze then forces each such case from `OPEN` to `ON_HOLD` — link two — and each forced hold releases the assigned attorney's `weighted_open_units` by that case's `case_weight`, the capacity release attributed to the freeze cascade rather than to the original suspension call — link three. Resuming a `SUSPENDED` program returns it to `ACTIVE` and restores each frozen case's `funding_status` to `GRANT_RESERVED`, but the cases themselves stay `ON_HOLD`: each must be resumed individually under the capacity re-check of §3.6. A program may be closed from `ACTIVE` or from `SUSPENDED`, but only when its `reserved_cents` is zero — frozen cases still reserve — else `ERR_GRANT_HAS_RESERVED_FUNDS` (HTTP 409). Grant actions from impermissible states fail with `ERR_INVALID_GRANT_STATE` (HTTP 409).

Accountability runs through `GrantReport` records. A `GrantsManager` generates a report for a program by supplying a `period_label`; at most one report per program may be live in `DRAFT` or `SUBMITTED`, and generating while one exists is rejected with `ERR_INVALID_REPORT_STATE` (HTTP 409). Generation freezes a snapshot: `cases_opened_count` counts the program's cases whose `opened_at` is set, `cases_closed_count` counts those in `CLOSED`, `total_hours` sums the `hours` of every time entry across the program's cases rounded half-up to two decimal places, and `reserved_cents_snapshot` and `spent_cents_snapshot` capture the ledger as it stands. The generator's identity is recorded as `generated_by_user_id` from `X-User-ID`. Later case activity never mutates an existing draft; only an explicit revision recomputes. The report lifecycle walks `DRAFT` to `SUBMITTED` by the grants manager, then to terminal `ACCEPTED` by the `ProgramDirector`, or back to `RETURNED` when the director supplies a non-empty `return_reason` — its absence fails with `ERR_INVALID_REQUEST` — and a returned report is revised by the grants manager back to `DRAFT`, recomputing every aggregate at that moment. Report actions from impermissible states fail with `ERR_INVALID_REPORT_STATE`.

The daily sweep, a `ProgramDirector` capability, is the system's scheduled conscience, and its four steps execute in a pinned order because the order is observable. First, conflict-check expiry: every `ConflictCheck` in `CLEAR` or `WAIVED` whose `valid_until` lies strictly before the current logical clock becomes `EXPIRED`. Second, referral expiry: every referral in `OFFERED` whose `response_deadline` lies strictly before the clock becomes `EXPIRED`. Third, advice auto-close per §3.8. Fourth, the waitlist promotion waterfall of §3.4 runs against the capacity remaining after step three, so closures in the same sweep free units that promotion immediately consumes. The sweep reports its work as counts per step: `expired_conflict_checks`, `expired_referrals`, `auto_closed_cases`, and `promoted_applications`. Every entity the sweep mutates refreshes its `updated_at` and, where the entity carries one, increments its `version`.

## 4. Endpoint Definitions

Endpoints that create a new resource — registering a client, filing an application, opening a case, running a conflict check, logging time, onboarding staff or panel members, creating a referral, creating a grant program, generating a report, creating a venue rule, recording a survey — return `201 Created`. Endpoints that act on or modify an existing resource, including all state transitions, updates, the clock set, and the daily sweep, return `200 OK`. In the table below, "All roles" means every role enumerated in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ProgramDirector |
| POST | `/ops/run-daily-sweep` | Run the pinned four-step daily batch | ProgramDirector |
| POST | `/clients` | Register a client | IntakeSpecialist |
| GET | `/clients/{id}` | Get a client | All roles |
| GET | `/clients` | List clients with optional filters and pagination | All roles |
| PATCH | `/clients/{id}` | Update client profile; financial changes cascade to applications | IntakeSpecialist |
| POST | `/intake-applications` | Create an intake application for a client | IntakeSpecialist |
| GET | `/intake-applications/{id}` | Get an application | All roles |
| GET | `/intake-applications` | List applications | All roles |
| POST | `/intake-applications/{id}/screen` | Run income and priority screening | IntakeSpecialist |
| POST | `/intake-applications/{id}/request-documents` | Request documentation from the applicant | IntakeSpecialist |
| POST | `/intake-applications/{id}/submit-documents` | Submit documentation, returning to screening | IntakeSpecialist |
| POST | `/intake-applications/{id}/decide-eligibility` | Record the eligibility determination | IntakeSpecialist |
| POST | `/intake-applications/{id}/rescreen` | Reset an eligible or ineligible application for a fresh screen | IntakeSpecialist |
| POST | `/intake-applications/{id}/enqueue-waitlist` | Move an eligible application to the waitlist | IntakeSpecialist |
| POST | `/intake-applications/{id}/withdraw` | Withdraw an application from any non-terminal state | IntakeSpecialist |
| POST | `/intake-applications/{id}/open-case` | Open a case from an eligible application | SupervisingAttorney |
| POST | `/intake-applications/{id}/conflict-checks` | Run a conflict check on an application | IntakeSpecialist |
| GET | `/intake-applications/{id}/conflict-checks` | List an application's conflict checks | IntakeSpecialist, SupervisingAttorney, EthicsOfficer, ProgramDirector |
| GET | `/conflict-checks/{id}` | Get a conflict check | IntakeSpecialist, SupervisingAttorney, EthicsOfficer, ProgramDirector |
| POST | `/conflict-checks/{id}/resolve` | Resolve a potential conflict | EthicsOfficer |
| GET | `/cases/{id}` | Get a case | All roles |
| GET | `/cases` | List cases | All roles |
| POST | `/cases/{id}/assign` | Assign or reassign an attorney and optional paralegal | SupervisingAttorney |
| POST | `/cases/{id}/place-hold` | Place an open case on hold | SupervisingAttorney |
| POST | `/cases/{id}/resume` | Resume a held case with capacity and status re-checks | SupervisingAttorney |
| POST | `/cases/{id}/close` | Close a case with outcome coding | StaffAttorney, SupervisingAttorney |
| POST | `/cases/{id}/time-entries` | Log time on a case | StaffAttorney, Paralegal, SupervisingAttorney |
| GET | `/time-entries/{id}` | Get a time entry | All roles |
| GET | `/time-entries` | List time entries | All roles |
| POST | `/staff-members` | Onboard a staff member | ProgramDirector |
| GET | `/staff-members/{id}` | Get a staff member | All roles |
| GET | `/staff-members` | List staff | All roles |
| PATCH | `/staff-members/{id}` | Update capacity, status, coverage, or supervision | ProgramDirector |
| GET | `/staff-members/{id}/caseload` | Computed caseload read for a staff member | All roles |
| POST | `/referral-panel-members` | Add a pro bono panel member | ProgramDirector |
| GET | `/referral-panel-members/{id}` | Get a panel member | All roles |
| GET | `/referral-panel-members` | List panel members | All roles |
| PATCH | `/referral-panel-members/{id}` | Update a panel member | ProgramDirector |
| POST | `/cases/{id}/referrals` | Offer a case to a panel member | SupervisingAttorney |
| GET | `/referrals/{id}` | Get a referral | All roles |
| GET | `/referrals` | List referrals | All roles |
| POST | `/referrals/{id}/respond` | Accept or decline a referral offer | SupervisingAttorney, ProgramDirector |
| POST | `/referrals/{id}/withdraw` | Withdraw a referral | SupervisingAttorney |
| POST | `/grant-programs` | Create a grant program | ProgramDirector |
| GET | `/grant-programs/{id}` | Get a grant program | All roles |
| GET | `/grant-programs` | List grant programs | All roles |
| POST | `/grant-programs/{id}/suspend` | Suspend a program, freezing funded cases | ProgramDirector |
| POST | `/grant-programs/{id}/resume` | Resume a suspended program | ProgramDirector |
| POST | `/grant-programs/{id}/close` | Close a program with no reserved funds | ProgramDirector |
| GET | `/grant-programs/{id}/utilization` | Computed grant ledger read | All roles |
| POST | `/grant-programs/{id}/reports` | Generate a draft grant report | GrantsManager |
| GET | `/grant-reports/{id}` | Get a grant report | SupervisingAttorney, GrantsManager, ProgramDirector |
| GET | `/grant-programs/{id}/reports` | List a program's reports | SupervisingAttorney, GrantsManager, ProgramDirector |
| POST | `/grant-reports/{id}/submit` | Submit a draft report | GrantsManager |
| POST | `/grant-reports/{id}/accept` | Accept a submitted report | ProgramDirector |
| POST | `/grant-reports/{id}/return` | Return a submitted report with a reason | ProgramDirector |
| POST | `/grant-reports/{id}/revise` | Revise a returned report, recomputing aggregates | GrantsManager |
| POST | `/venue-rules` | Create a venue rule | ProgramDirector |
| GET | `/venue-rules/{id}` | Get a venue rule | All roles |
| GET | `/venue-rules` | List venue rules | All roles |
| POST | `/cases/{id}/satisfaction-surveys` | Record a satisfaction survey for a closed case | IntakeSpecialist |
| GET | `/cases/{id}/satisfaction-surveys` | List a case's satisfaction surveys | IntakeSpecialist, SupervisingAttorney, GrantsManager, ProgramDirector |
| GET | `/unmet-need-records/{id}` | Get an unmet-need record | IntakeSpecialist, SupervisingAttorney, GrantsManager, ProgramDirector |
| GET | `/unmet-need-records` | List unmet-need records | IntakeSpecialist, SupervisingAttorney, GrantsManager, ProgramDirector |
| GET | `/waitlist-entries/{id}` | Get a waitlist entry | IntakeSpecialist, SupervisingAttorney, ProgramDirector |
| GET | `/waitlist-entries` | List waitlist entries in ranking order | IntakeSpecialist, SupervisingAttorney, ProgramDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_APPLICATION_STATE` | 409 Conflict |
| `ERR_DETERMINATION_MISMATCH` | 409 Conflict |
| `ERR_VENUE_UNDETERMINED` | 422 Unprocessable Entity |
| `ERR_VENUE_RULE_CONFLICT` | 409 Conflict |
| `ERR_CONFLICT_UNRESOLVED` | 409 Conflict |
| `ERR_CONFLICT_CHECK_STALE` | 409 Conflict |
| `ERR_ETHICS_RECUSAL` | 403 Forbidden |
| `ERR_SELF_SCREENING_APPROVAL` | 403 Forbidden |
| `ERR_DUPLICATE_OPEN_CASE` | 409 Conflict |
| `ERR_EXTENDED_REP_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_NO_EXTENDED_CAPACITY` | 409 Conflict |
| `ERR_CASELOAD_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STAFF_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_SUPERVISOR` | 422 Unprocessable Entity |
| `ERR_INVALID_CASE_STATE` | 409 Conflict |
| `ERR_GRANT_CASE_TYPE_EXCLUDED` | 422 Unprocessable Entity |
| `ERR_GRANT_COUNTY_EXCLUDED` | 422 Unprocessable Entity |
| `ERR_GRANT_PERIOD_INACTIVE` | 409 Conflict |
| `ERR_GRANT_BUDGET_EXHAUSTED` | 409 Conflict |
| `ERR_GRANT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_GRANT_HAS_RESERVED_FUNDS` | 409 Conflict |
| `ERR_INVALID_GRANT_STATE` | 409 Conflict |
| `ERR_PANEL_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_PANEL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PANEL_CAPACITY_REACHED` | 409 Conflict |
| `ERR_CASE_PLACEMENT_CONFLICT` | 409 Conflict |
| `ERR_INVALID_REFERRAL_STATE` | 409 Conflict |
| `ERR_CASE_NOT_CLOSED` | 409 Conflict |
| `ERR_DUPLICATE_SURVEY` | 409 Conflict |
| `ERR_INVALID_REPORT_STATE` | 409 Conflict |
| `ERR_TIME_ENTRY_FORBIDDEN` | 403 Forbidden |
| `ERR_CASE_NOT_ASSIGNED_TO_YOU` | 403 Forbidden |
| `ERR_STAFF_COVERAGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PARALEGAL_SUPERVISION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STAFF_HAS_OPEN_CASES` | 409 Conflict |
| `ERR_PANEL_COVERAGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PANEL_HAS_ACTIVE_PLACEMENTS` | 409 Conflict |
| `ERR_GRANT_INCOME_OVER_CAP` | 422 Unprocessable Entity |

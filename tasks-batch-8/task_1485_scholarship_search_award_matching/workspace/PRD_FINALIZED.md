# Scholarship Award Matching API — Product Requirements Document

## 1. Introduction

A school scholarship office sits at the junction of three constituencies: students searching for aid, donors who fund award programs, and the committee volunteers who review applications. The Scholarship Award Matching API is the system of record for that office. It covers student profile registration and eligibility matching, program application windows with deadline reminders, essay and recommendation component tracking, committee review cycles with quorum-gated scoring and selection, award offers and their acceptance, disbursement scheduling to institutions, over-award and duplicate-award recovery, renewal evaluation, and donor stewardship through thank-you letters and periodic reports.

Two design commitments shape everything that follows. First, the office operates under audit discipline: every monetary amount is an integer number of cents, every GPA is an integer number of hundredths, and money-moving steps are separated so that the operator who sends a disbursement is never the one who confirms it, and the staffer who drafts an award adjustment is never the one who approves it. Second, the system runs on a logical clock rather than wall-clock time, so every deadline-driven behavior — reminder dispatch, program close, offer expiry — is deterministic, reproducible, and testable.

The API is served under the `/api` prefix and exposes a flat collection of resources joined by references: a scholarship program names its sponsoring donor and its fund; an application joins a student to a program; an award joins a selected application to its recipient; disbursements, adjustments, renewal evaluations, and thank-you letters hang off awards; review cycles and review scores carry out committee selection; donor reports close the loop back to the sponsor.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `Student`, `ScholarshipCoordinator`, `CommitteeReviewer`, `FinancialAidOfficer`, `Donor`, and `PlatformAdmin`. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Where an endpoint is ownership-scoped, a mismatch between the caller's identity and the resource's owner is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`. Ownership checks on any resource that references a student — an application, an award, a thank-you letter — compare the resource's student foreign key to `X-User-ID`.
- When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor`. Ownership checks on a donor report compare the report's `donor_id` to `X-User-ID`.
- When `X-User-Role` is `CommitteeReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `reviewer_user_id` on each `ReviewScore` the reviewer creates, and ownership checks on score submit and recall compare that recorded `reviewer_user_id` to `X-User-ID`; it is never compared to any entity's `id`.
- When `X-User-Role` is `ScholarshipCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `sent_by_user_id` on a `Disbursement` the coordinator sends, as `created_by_user_id` on an `AwardAdjustment` the coordinator drafts, or as `verified_by_user_id` on a `RenewalEvaluation` the coordinator verifies — but does not compare it to any entity's `id`.
- When `X-User-Role` is `FinancialAidOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `approved_by_user_id` on an `AwardAdjustment` the officer approves, or as `created_by_user_id` when the officer originates an adjustment — but does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it authenticates the logical-clock and operations-run capabilities only.

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

Endpoints that return lists of resources are paginated via query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All fifteen resources in the system — students, donors, award funds, scholarship programs, applications, application components, reminders, review cycles, review scores, awards, disbursements, award adjustments, renewal evaluations, thank-you letters, and donor reports — carry the same set of system-managed properties:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the resource's last modification; it is refreshed on any change to the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, including mutations driven by system cascades rather than direct client writes. This field backs the optimistic concurrency rules of §2.7.

Every mutation is atomic and visible in the response of the request that caused it: when one operation updates several resources, all of those updates commit together, and each mutated resource reflects its new `updated_at` and `version` immediately.

### 2.5. Money, GPA, and Calendar Conventions

All monetary values in the system — fund balances, award amounts, disbursement amounts, adjustment deltas, income figures, cost of attendance — are integer numbers of cents. Fund aggregation arithmetic is exact integer arithmetic; the only non-exact operations in the system are the two score calculations described in §3, which produce decimal scores carried to exactly two decimal places using round-half-up.

All GPAs are integer hundredths: a value of 300 represents a 3.00 GPA, and the valid range is 0 to 500 inclusive. Wherever the API speaks of a GPA — `gpa_hundredths`, `verified_gpa_hundredths`, `min_gpa_hundredths`, `renewal_min_gpa_hundredths`, `reported_gpa_hundredths`, `registrar_gpa_hundredths` — it speaks in these hundredths.

Calendar windows are expressed as `YYYY-MM-DD` date strings, and the system uses two distinct interval flavors, always stated alongside the window in question. Review cycle windows and donor report periods are half-open: the start date is included and the end date is excluded, so an event dated exactly on the end date falls outside the window. Disbursement term windows are closed: both the start date and the end date are included. Instants — application deadlines, reminder send times, offer expirations — are logical-clock timestamps compared per the boundary rules of §2.6 and §3.

### 2.6. The Logical Clock and the Daily Operations Run

The system never reads wall-clock time. All notions of "now" come from a logical clock whose startup default is exactly `2026-08-01T00:00:00Z`; before any clock-set call has been made, the clock reads this default and never falls back to wall-clock time. A `PlatformAdmin` advances the clock through a test-driving capability that carries a `to_iso8601` instant; the response echoes the new clock reading as `now`.

A second `PlatformAdmin` capability performs the daily operations run, which is the system's scheduled-action checkpoint. Each run performs three sweeps, all evaluated against the logical clock. First, it dispatches due reminders: every `SCHEDULED` reminder whose `send_at` is at or before now is dispatched to `SENT` — a reminder whose `send_at` equals now dispatches — with dispatch processed in `send_at` ascending order, ties broken by `created_at` ascending. Second, it closes programs whose window has ended: every program in `OPEN` whose `application_close_at` has been reached or passed moves to `CLOSED`, and every `DRAFT` application of such a program moves to `EXPIRED` with its `SCHEDULED` reminders suppressed to `SUPPRESSED`. Third, it expires stale offers: every award still `OFFERED` whose `offer_expires_at` lies strictly before now moves to `EXPIRED`, releasing the fund reservation and firing the waitlist promotion described in §3.6. The run returns a summary of its work as four counters: `reminders_sent`, `programs_closed`, `applications_expired`, and `offers_expired`.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each naming its own expected-version field:

- Editing a scholarship program (`PUT /api/scholarship-programs/{id}`) requires the request to carry `expected_program_version`, holding the program `version` the client last observed. Two sequential edits carrying the same observed version cannot both succeed: the first commits and bumps the version, and the second is stale.
- Adding a commitment to an award fund (`POST /api/award-funds/{id}/commitments`) requires `expected_fund_version`, holding the fund `version` the client last observed. Additive commitments are each independently valid, so without this check a stale write would silently double-count committed money.
- Adjusting the amount of an offered award (`PATCH /api/awards/{id}`) requires `expected_award_version`, holding the award `version` the client last observed. Amount edits each legitimately succeed in sequence, so optimistic concurrency on the award version is the arbitration mechanism.

In all three cases, when the expected version in the request does not match the parent resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written. Endpoints not listed in this section do not take a version field.

### 2.8. Validation Order

When a request arrives, the server evaluates its checks in a fixed priority order, and a failure at any step surfaces that step's error and masks every later check. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is known; otherwise `ERR_UNAUTHENTICATED`. This applies to every endpoint.
2. **Authorization** — the role is permitted for the endpoint per the matrix in §4; otherwise `ERR_FORBIDDEN_ROLE`. This applies to every endpoint.
3. **Ownership** — for ownership-scoped endpoints, the entity-backed identity matches: a `Student` caller's `X-User-ID` equals the resource's `student_id`, a `Donor` caller's equals the report's `donor_id`, a `CommitteeReviewer` caller's equals the score's `reviewer_user_id`; otherwise `ERR_FORBIDDEN_OWNERSHIP`.
4. **Existence** — path-referenced and body-referenced identifiers exist, validated left to right, so the first missing identifier in the path determines the `ERR_NOT_FOUND` rejection.
5. **Concurrency** — for the three optimistic-concurrency endpoints of §2.7, the expected version matches the parent's current `version`; otherwise `ERR_STALE_VERSION`.
6. **Request shape** — required fields are present, enum values are valid, and date ranges are ordered (the application close must be later than the application open; a cycle's `ends_on` must be later than its `starts_on`; a disbursement's `term_end_date` must be on or after its `term_start_date`); otherwise `ERR_VALIDATION` or `ERR_INVALID_DATE_RANGE`. This applies to every create and edit.
7. **Own-state** — the target resource's own state permits the requested transition; otherwise `ERR_INVALID_STATE`. The target's own state is always validated before any cross-entity state.
8. **Cross-entity gates** — the program must be `OPEN` for application create and submit (`ERR_PROGRAM_NOT_OPEN`), the award must be accepted for disbursement create and send (`ERR_AWARD_NOT_ACCEPTED`), and the evaluation must be verified eligible for a renewal (`ERR_RENEWAL_NOT_ELIGIBLE`).
9. **Segregation and declared conflicts** — the adjustment approver differs from its creator and the disbursement confirmer differs from its sender (`ERR_SEGREGATION_OF_DUTIES`), and a score carrying a conflict-of-interest declaration cannot be submitted (`ERR_CONFLICT_OF_INTEREST`).
10. **Business constraints** — uniqueness, completeness, overlap, and quorum rules: duplicate application per student and program in a non-terminal status (`ERR_DUPLICATE_APPLICATION`), required components not yet accepted or waived (`ERR_COMPONENT_INCOMPLETE`), a strict-program submit with a failed hard criterion (`ERR_INELIGIBLE_STUDENT`), overlapping cycle windows (`ERR_CYCLE_WINDOW_OVERLAP`), overlapping disbursement term windows (`ERR_DISBURSEMENT_WINDOW_OVERLAP`), quorum shortfalls (`ERR_QUORUM_NOT_MET`), a second score from the same reviewer (`ERR_REVIEWER_DUPLICATE_SCORE`), a second open renewal evaluation (`ERR_DUPLICATE_RENEWAL_EVALUATION`), a thank-you waive for a non-anonymous donor (`ERR_TYL_NOT_WAIVABLE`), and an incomplete report (`ERR_REPORT_INCOMPLETE`).
11. **Temporal windows** — publish before the window opens (`ERR_WINDOW_NOT_OPEN`), submit at or after the deadline (`ERR_DEADLINE_PASSED`), and disbursement send before its scheduled date (`ERR_DISBURSEMENT_TOO_EARLY`).
12. **Fiscal limits** — funds and amounts: the fund cannot cover an offer (`ERR_INSUFFICIENT_FUNDS`), a disbursement plan would exceed the award (`ERR_AMOUNT_EXCEEDS_REMAINING`), a duplicate or data-error clawback would cut below money already confirmed (`ERR_ADJUSTMENT_EXCEEDS_DISBURSED`), and the renewal cap has been reached (`ERR_MAX_RENEWALS_REACHED`).

### 2.9. Fund Accounting and the Availability Invariant

Every award fund tracks four balances and one derived figure. `committed_cents` is the total money committed to the fund; it is supplied at creation and grows through commitment calls. The other four are computed, and the system keeps them exact after every mutation. Central to the arithmetic is an award's **net confirmed amount**: the sum of its `CONFIRMED` disbursement amounts minus the sum of amounts marked `RETURNED` from `CONFIRMED`.

- `reserved_cents` is the sum, over every award of every program drawing on the fund whose `offer_status` is `OFFERED` or `ACCEPTED`, of the positive part of the award's `amount_cents` minus its net confirmed amount — that is, the difference when positive, and zero otherwise.
- `disbursed_cents` is the gross sum of `CONFIRMED` disbursement amounts over awards of the fund's programs.
- `returned_cents` is the sum of amounts of disbursements marked `RETURNED` from `CONFIRMED`.
- `available_cents` equals `committed_cents` minus `reserved_cents` minus `disbursed_cents` plus `returned_cents`.

This availability identity is an invariant: it holds after every mutation that touches fund arithmetic — award create, accept, decline, revoke, and expiry; disbursement confirm and mark-returned; adjustment apply; renewal; and commitment. A useful consequence is that an offer followed by a revoke leaves `available_cents` unchanged. A freshly created fund starts with `reserved_cents`, `disbursed_cents`, and `returned_cents` at zero, so its `available_cents` equals its initial `committed_cents`.

### 2.10. Segregation of Duties and Reviewer Independence

Two money-adjacent workflows require a second pair of eyes, enforced by identity comparison rather than by role alone. An award adjustment may be drafted by a `ScholarshipCoordinator` or a `FinancialAidOfficer`, but only a `FinancialAidOfficer` may approve or reject it, and the approver's `X-User-ID` must differ from the recorded `created_by_user_id`; a same-person approval or rejection is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Likewise a disbursement is sent by a `ScholarshipCoordinator` and confirmed by a `FinancialAidOfficer`, and the confirmer's `X-User-ID` must differ from the recorded `sent_by_user_id`; a same-person confirmation is refused with the same `ERR_SEGREGATION_OF_DUTIES`. Committee independence is protected separately: a review score whose `conflict_of_interest` flag is set may sit in draft form but can never be submitted — submission is refused with `ERR_CONFLICT_OF_INTEREST`.

## 3. Business Logic & Workflows

### 3.1. Students, Donors, and Award Funds

A `ScholarshipCoordinator` registers each student with a `full_name`, a unique `email` (no two students may share an email address), a `grade_level` from 9 to 12, a self-reported `gpa_hundredths` between 0 and 500, a two-letter `residency_state`, an `intended_major` drawn from `STEM`, `ARTS`, `BUSINESS`, `HEALTH`, `TRADES`, or `UNDECIDED`, the annual `household_income_cents`, the `efc_cents` expected family contribution, the `cost_of_attendance_cents` at the student's institution, and the `institution_name` itself. Optional at registration are `verified_gpa_hundredths` — the registrar-verified GPA, which stays null until verification and may only ever be set by a coordinator through the student update operation — and `tags`, a list of profile tags such as `FIRST_GEN`, `VETERAN`, and `ATHLETE` that programs match against their own required tags; when omitted, `tags` starts empty. A new student begins with `status` `ACTIVE`.

Four computed figures ride on the student record. The `aid_cap_cents` is the student's annual need cap: the `cost_of_attendance_cents` minus the `efc_cents`, computed at registration and recomputed whenever either input changes. The `total_accepted_cents` sums `amount_cents` over the student's awards whose `offer_status` is `ACCEPTED`. The `total_disbursed_cents` sums, over the student's awards, each award's confirmed disbursements minus the amounts returned from confirmed. The `excess_cents` is the amount by which accepted aid exceeds the need cap — zero when `total_accepted_cents` is at or below `aid_cap_cents`, and the difference otherwise — and it is recomputed on every award amount or status change. A dedicated aid-summary read exposes all four figures together with a per-award breakdown, and is available to the coordinator, the student, and the financial aid officer.

Profile maintenance is coordinator-only: the student update accepts any subset of `gpa_hundredths`, `verified_gpa_hundredths`, `residency_state`, `intended_major`, `household_income_cents`, `efc_cents`, `cost_of_attendance_cents`, `institution_name`, and `tags`; it recomputes `aid_cap_cents`, and a change to the cost of attendance or the expected family contribution triggers the stacking recompute of §3.6, which may auto-create adjustments. Each update increments the student's `version` by one. Archiving moves a student from `ACTIVE` to `ARCHIVED` as a soft delete — the record remains readable — and is refused with `ERR_INVALID_STATE` while the student has any application in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `SELECTED`, or `WAITLISTED`, or any award with `offer_status` `OFFERED` or `ACCEPTED`.

Donors are simpler records: a `name`, a `contact_email`, an optional `anonymous` flag defaulting to false, and an optional `report_frequency` of `QUARTERLY` or `ANNUAL` defaulting to `ANNUAL`. Anonymity has teeth — when `anonymous` is true, thank-you letters are waived and reports omit recipient identity, as detailed in §3.9.

Award funds hold the money programs draw on. A coordinator creates a fund with a `name` and an optional `committed_cents` defaulting to zero; per §2.9 the derived balances start at zero and `available_cents` equals the committed amount. Additional money arrives through commitments, which carry an `amount_cents` and the OCC guard `expected_fund_version` (§2.7); a successful commitment adds the amount to `committed_cents`, recomputes `available_cents`, and increments the fund's `version` by one.

### 3.2. Scholarship Programs and the Application Window

A scholarship program is the office's unit of policy. The coordinator creates one — it starts in `DRAFT` — naming the sponsoring `donor_id` and the `fund_id` its awards will draw on, plus a `name`. Three policy selectors shape everything downstream: `program_type` (`MERIT`, `NEED`, or `HYBRID`) chooses the weight sets used by both the eligibility score of §3.4 and the committee ranking score of §3.5; `match_policy` (`STRICT` or `HOLISTIC`) decides whether a hard-criterion miss zeroes the eligibility score or merely diminishes it; and `stacking_scope` (`ANNUAL` or `PER_TERM`) chooses which stacking cap variant of §3.6 applies when a recipient accepts.

The program's eligibility criteria are `min_gpa_hundredths` (a hard minimum), `eligible_majors` (an empty list, the default, means every major is eligible), `required_residency_state` (a two-letter state code, or null for no residency requirement), `max_household_income_cents` (an income ceiling, or null for no income requirement), `required_tags` (the tags an applicant must hold — all of them; empty by default), and `required_components` (the component types gated at submit, a subset of `ESSAY`, `RECOMMENDATION`, and `TRANSCRIPT`; empty by default). Award shape is set by `award_amount_cents`, the maximum amount per recipient offer, and `max_recipients`, the maximum number of awards the program may grant per cycle. Renewal policy is set by `renewable` (default false), the thresholds `renewal_min_gpa_hundredths` and `renewal_min_credits` (null when the program is not renewable), and `max_renewals` (default 0). The application window is bounded by `application_open_at` and `application_close_at`; the close must be strictly later than the open, or creation fails with `ERR_INVALID_DATE_RANGE`. The program collection supports optional filtering by `donor_id`, `fund_id`, and `status`.

Three window gates govern timing, all read against the logical clock. Publishing is allowed once now has reached `application_open_at` — the gate is inclusive, so publishing at exactly the open instant succeeds, while an earlier attempt fails with `ERR_WINDOW_NOT_OPEN`. Submitting an application is allowed strictly while now is earlier than `application_close_at`; an attempt at or after the close fails with `ERR_DEADLINE_PASSED`. The daily operations run closes any `OPEN` program once now has reached or passed `application_close_at`.

The program lifecycle runs `DRAFT` → `OPEN` → `CLOSED` → `ARCHIVED`, with one loop back. Publishing moves `DRAFT` to `OPEN` per the window gate above. Closing moves `OPEN` to `CLOSED` and comes in two flavors with different blast radii: a coordinator's manual close simply flips the status, whereas the operations-run close also expires the program's remaining `DRAFT` applications to `EXPIRED` and suppresses their `SCHEDULED` reminders to `SUPPRESSED`. Extending a deadline moves `CLOSED` back to `OPEN`: the request carries a `new_close_at` that must be later than the current `application_close_at` (otherwise `ERR_INVALID_DATE_RANGE`), and the program's `application_close_at` is updated to it — a deadline-extension cycle that reopens the window. Archiving is allowed only from `CLOSED` and only when no application of the program remains in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `SELECTED`, or `WAITLISTED`; otherwise the archive is refused with `ERR_INVALID_STATE`.

Program criteria may be edited while the program is `DRAFT` or `CLOSED` — not while `OPEN`. The edit carries the OCC guard `expected_program_version` (§2.7) and may touch `name`, `min_gpa_hundredths`, `max_household_income_cents`, `required_residency_state`, `eligible_majors`, `required_tags`, `required_components`, `award_amount_cents`, `max_recipients`, `renewal_min_gpa_hundredths`, `renewal_min_credits`, and `max_renewals`; a successful edit increments the program's `version` by one.

### 3.3. Applications, Components, and the Reminder Cadence

An application joins a student to a program. Either the student or a coordinator creates it with a payload carrying `student_id` and `program_id`; it starts in `DRAFT`. Two gates guard creation: the student's `status` must be `ACTIVE` (otherwise `ERR_INVALID_STATE`), and no other application may already exist for the same student-and-program pair in a non-terminal status — that is, in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `SELECTED`, `WAITLISTED`, or `AWARDED` — otherwise the create is refused with `ERR_DUPLICATE_APPLICATION`. At creation the system computes the `provisional_match_score` using the eligibility scoring of §3.4 against the student's self-reported `gpa_hundredths`, leaves `verified_match_score` null until the first submit, stamps nothing into `submitted_at`, sets `returned_count` to zero, leaves `cycle_score` and `decision_rank` null until a cycle finalizes, and arms the reminder cadence described below. The application collection supports optional filtering by `student_id`, `program_id`, and `status`.

While in `DRAFT`, the application accumulates component items. Each item carries a `component_type` of `ESSAY`, `RECOMMENDATION`, or `TRANSCRIPT`, a `required` flag defaulting to true, and optionally a `content_ref` — an opaque reference to uploaded content. Components begin `PENDING`. Receipt, performed by the student or a coordinator with a `content_ref` present (a missing reference fails with `ERR_VALIDATION`), moves a component from `PENDING` to `RECEIVED` and stamps `received_at`; the same receipt action also moves a `REJECTED` component back to `RECEIVED`, forming the resubmission cycle. A coordinator then adjudicates: accepting moves `RECEIVED` to `ACCEPTED`, rejecting moves `RECEIVED` to `REJECTED`, and waiving moves `PENDING` to `WAIVED`. `ACCEPTED` and `WAIVED` are terminal. Components are listed per application with an optional `status` filter.

The reminder cadence keeps applicants ahead of the deadline. At application creation the system considers three offsets before the program's `application_close_at`: `D14` (fourteen days), `D7` (seven days), and `D1` (one day). For each offset whose send time — the close instant minus the offset — still lies in the future, a `SCHEDULED` reminder is created carrying that `offset_code` and the computed `send_at`; offsets whose send time already lies in the past are skipped, never scheduled. The daily operations run dispatches due reminders per §2.6, stamping `sent_at` as they move to `SENT`. A reminder still `SCHEDULED` is suppressed to `SUPPRESSED` whenever its application leaves `DRAFT` — by submit, withdraw, or expiry — or when its program closes. Reminders of an application are listed with an optional `status` filter.

Submitting is the pivotal act, and it may be performed by the student or by a coordinator on the student's behalf. Five gates stand in front of it. The application must be in `DRAFT` (otherwise `ERR_INVALID_STATE`). The program must be `OPEN` (otherwise `ERR_PROGRAM_NOT_OPEN`). The logical clock must be strictly before the program's `application_close_at` (otherwise `ERR_DEADLINE_PASSED`, per the window gate of §3.2). Every required component — one whose `required` flag is set and whose `component_type` appears in the program's `required_components` — must be `ACCEPTED` or `WAIVED` (otherwise `ERR_COMPONENT_INCOMPLETE`). And for a `STRICT` program, the recomputed verified score must be above zero (otherwise `ERR_INELIGIBLE_STUDENT`). On success the application moves `DRAFT` → `SUBMITTED`, its `verified_match_score` is recomputed using `verified_gpa_hundredths` when set and `gpa_hundredths` otherwise, `submitted_at` is stamped with the current logical instant, and every `SCHEDULED` reminder is suppressed.

The correction loop runs through the coordinator's return action: a `SUBMITTED` application returns to `DRAFT`, its `returned_count` increases by one, and the reminder cadence is re-armed against the program's close — again skipping offsets whose send times have passed. Withdrawal, available to the student or a coordinator from either `DRAFT` or `SUBMITTED` (otherwise `ERR_INVALID_STATE`), moves the application to `WITHDRAWN` and suppresses its `SCHEDULED` reminders. Expiry is system-driven: the operations run moves a `DRAFT` application to `EXPIRED` once its program is `CLOSED` and the close instant has been reached, suppressing reminders on the way. `NOT_SELECTED`, `WITHDRAWN`, and `EXPIRED` are the application's terminal states. The remaining transitions — into `UNDER_REVIEW`, and from there into `SELECTED`, `WAITLISTED`, and `NOT_SELECTED` — belong to the committee cycle of §3.5, and the final move from `SELECTED` to `AWARDED` happens when an award offer is created for the application (§3.6).

### 3.4. Eligibility Match Scoring

The eligibility match score is computed twice in an application's life. At creation it produces the `provisional_match_score` from the student's self-reported `gpa_hundredths`. At submit it produces the `verified_match_score`, recomputed with `verified_gpa_hundredths` when that has been set and with `gpa_hundredths` otherwise — so the same application can legitimately carry a provisional score of 90.00 and a verified score of 80.00 once the registrar's figure replaces the self-reported one.

The score blends four components, each on a scale from zero to one hundred. The GPA component is 100 when the GPA input meets or exceeds the program's `min_gpa_hundredths`; under a `HOLISTIC` match policy, a GPA input falling short of the minimum by at most 20 hundredths — two tenths of a GPA point — still earns 50; otherwise the component is 0. The income component is 100 when the program sets no `max_household_income_cents`, and otherwise 100 when the student's `household_income_cents` is at or below that ceiling and 0 above it. The residency component is 100 when the program sets no `required_residency_state`, and otherwise 100 when the student's `residency_state` equals it and 0 when it differs. The tags component is 100 when the program's `required_tags` is empty, and otherwise 100 multiplied by the share of required tags the student holds — the count of tags appearing in both the program's `required_tags` and the student's `tags`, divided by the count of `required_tags`. Alongside the four weighted components sits a major gate: when the program's `eligible_majors` is non-empty and the student's `intended_major` is not among them, the application is treated as a hard miss.

Weights come from the program's `program_type`. A `MERIT` program weights the GPA component at 0.50, income at 0.10, residency at 0.15, and tags at 0.25. A `NEED` program weights GPA at 0.20, income at 0.50, residency at 0.10, and tags at 0.20. A `HYBRID` program weights GPA at 0.35, income at 0.30, residency at 0.15, and tags at 0.20. The base score is the sum of each component multiplied by its weight, rounded half-up to two decimal places.

The `match_policy` then decides whether hard misses are fatal. Under `STRICT`, any hard-criterion miss — GPA below the minimum, income above the ceiling, residency mismatch, any required tag absent, or the major gate — forces the total score to exactly 0.00. Under `HOLISTIC`, partial credit applies and there is no zero-gate, so identical student data can yield, for example, 90.00 under a holistic policy against 0.00 under a strict one. This is also why the `STRICT` submit gate of §3.3 can rely on the score: a verified score above zero certifies that every hard criterion passed.

### 3.5. Committee Review: Cycles, Scores, and Selection

Committee review happens inside a review cycle. A coordinator creates one in `SETUP` with the `program_id` under review, a `label` such as "2026-FALL", a `starts_on` and `ends_on` pair delimiting the cycle window, a `quorum_count` — the minimum number of locked scores each application needs before deliberation and finalization — a `selection_quota` saying how many top-ranked applications will be selected, and an optional `waitlist_quota` defaulting to zero that says how many of the next-ranked are waitlisted. The window is a half-open interval: `starts_on` is included, `ends_on` is excluded, and `ends_on` must be strictly later than `starts_on` or creation fails with `ERR_INVALID_DATE_RANGE`. The window must not overlap another cycle of the same program — adjacency, where one cycle's `ends_on` equals another's `starts_on`, is permitted — otherwise creation fails with `ERR_CYCLE_WINDOW_OVERLAP`. Cycles are listed with optional filtering by `program_id` and `status`.

Opening scoring moves the cycle `SETUP` → `SCORING` and sweeps every `SUBMITTED` application of the cycle's program into `UNDER_REVIEW`. While the cycle is in `SCORING`, each `CommitteeReviewer` drafts scores: a review score names its `cycle_id` and `application_id` and carries `academic_score`, `essay_score`, and `need_score`, each an integer from 0 to 100 (a value outside that range fails with `ERR_VALIDATION`), plus an optional `conflict_of_interest` declaration defaulting to false. The reviewer's `X-User-ID` is recorded as `reviewer_user_id`, and the system permits only one score per reviewer per application per cycle — a second attempt fails with `ERR_REVIEWER_DUPLICATE_SCORE`.

Submitting a score is guarded four ways: the score must be `DRAFT` (otherwise `ERR_INVALID_STATE`), the cycle must still be in `SCORING` (otherwise `ERR_INVALID_STATE`), the `conflict_of_interest` flag must be false (otherwise `ERR_CONFLICT_OF_INTEREST`), and the caller's `X-User-ID` must equal the score's `reviewer_user_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`). On submit the score moves `DRAFT` → `SUBMITTED` and its `weighted_total` is computed. The committee ranking score weights the three dimensions by the program's `program_type`: `MERIT` weights academic at 0.60, essay at 0.25, and need at 0.15; `NEED` weights academic at 0.25, essay at 0.25, and need at 0.50; `HYBRID` weights each of the three at exactly one third. A deep-need bonus of 5 points is added when twice the student's `household_income_cents` is strictly less than the program's `max_household_income_cents`. The weighted total is the weighted sum plus any bonus, capped at 100 — scores above the cap are pinned to 100 — and rounded half-up to two decimal places; while a score is in `DRAFT` its `weighted_total` is null. A reviewer may recall a submitted score — back from `SUBMITTED` to `DRAFT`, clearing `weighted_total` to null — but only while the cycle remains in `SCORING`; recall is impossible once deliberation has locked the score. Scores are listed with optional filtering by `cycle_id` and `application_id`.

Opening deliberation moves the cycle `SCORING` → `DELIBERATION` and is quorum-gated: every `UNDER_REVIEW` application of the cycle's program must hold at least `quorum_count` scores in `SUBMITTED` or `LOCKED`, otherwise the transition fails with `ERR_QUORUM_NOT_MET`. On entry every `SUBMITTED` score of the cycle becomes `LOCKED`. Should the committee need another pass, reopening scoring moves `DELIBERATION` back to `SCORING`; the lock is monotone, so already-locked scores stay `LOCKED`, and new draft scores may be created and submitted in the reopened round.

Finalization moves `DELIBERATION` → `FINALIZED` and carries two gates of its own: every `UNDER_REVIEW` application must now hold at least `quorum_count` `LOCKED` scores (otherwise `ERR_QUORUM_NOT_MET`), and the `selection_quota` plus `waitlist_quota` must not exceed the number of `UNDER_REVIEW` applications (otherwise `ERR_VALIDATION`). Finalization computes each application's `cycle_score` as the average of its locked scores' `weighted_total` values, rounded half-up to two decimal places, and freezes it onto the application. Applications are then ranked: `cycle_score` descending, ties broken by the application's average `need_score` across its locked scores descending, then by `submitted_at` ascending, then by `created_at` ascending; the resulting 1-based position is stamped as `decision_rank`. The top `selection_quota` applications become `SELECTED`, the next `waitlist_quota` become `WAITLISTED`, and all the rest become `NOT_SELECTED` — and a count invariant holds: the numbers selected, waitlisted, and not selected sum exactly to the count of applications that were under review.

### 3.6. Award Offers, Stacking, and the Waitlist

An award offer is created by a coordinator against a `SELECTED` application, with a payload naming the `application_id`, the recipient `student_id` (which must equal the application's student), and the offered `amount_cents` — positive and at most the program's `award_amount_cents`. The fund must be able to stand behind the offer: an offer amount exceeding the fund's `available_cents` is refused with `ERR_INSUFFICIENT_FUNDS`. Creation sets `offer_status` to `OFFERED` and `funding_status` to `NONE`, increases the fund's `reserved_cents` by the offered amount, moves the application from `SELECTED` to `AWARDED`, sets `offer_expires_at` to fourteen days after creation, starts `renewal_count` at zero, and leaves `accepted_at` null. Awards are listed with optional filtering by `application_id`, `student_id`, and `offer_status`.

While an offer is still `OFFERED`, the coordinator may adjust its amount; the edit carries the OCC guard `expected_award_version` (§2.7), recomputes the fund's reservation, and increments the award's `version` by one.

Acceptance belongs to the student alone, and only on their own award — a caller whose `X-User-ID` differs from the award's `student_id` is refused with `ERR_FORBIDDEN_OWNERSHIP`, and any state other than `OFFERED` is refused with `ERR_INVALID_STATE`. Accepting drives the two parallel status dimensions together: `offer_status` moves `OFFERED` → `ACCEPTED` and `funding_status` moves `NONE` → `ENCUMBERED`. The `accepted_at` instant is stamped, the student's `total_accepted_cents` grows by `amount_cents`, the student's `excess_cents` is recomputed, the fund's `reserved_cents` is recomputed (the offer was already reserved at creation), and then the stacking check below runs — the first trigger of the over-award cascade.

Declining, also the student's own act and only from `OFFERED`, moves the offer to `DECLINED`, releases the reservation — the fund's `reserved_cents` decreases by `amount_cents` as a compensating entry — and fires the waitlist promotion selector on the source cycle. Revocation is the coordinator's act and is allowed from either `OFFERED` or `ACCEPTED` (otherwise `ERR_INVALID_STATE`): the offer moves to `REVOKED`, the fund's `reserved_cents` decreases by the positive part of `amount_cents` minus the award's net confirmed amount, and if the revoked award had been `ACCEPTED` with a net confirmed amount above zero, its `funding_status` flips to `OVER_DISBURSED` — money has gone out that the award no longer covers. Waitlist promotion fires on revocation only when no `CONFIRMED` disbursement exists for the award. Expiry is the system's act: the daily operations run moves an `OFFERED` award to `EXPIRED` once the logical clock passes `offer_expires_at`, releases the reservation in full, and fires waitlist promotion. `DECLINED`, `REVOKED`, and `EXPIRED` are terminal for the offer dimension.

The **stacking cap** keeps a student's total accepted aid within the program's notion of need. It is evaluated at five triggers: award acceptance, award amount edit, adjustment approval, renewal, and a change to the student's cost of attendance or expected family contribution. The cap basis comes from the stacking scope of the program being accepted: an `ANNUAL` program caps the stack at the student's `cost_of_attendance_cents` minus `efc_cents`, while a `PER_TERM` program caps it at the floor of half that difference — identical student data admits a smaller stack under a per-term program (for example, a 2,000,000-cent annual difference caps at 1,000,000 cents per term). The stacking total is the sum of `amount_cents` over the student's awards whose `offer_status` is `ACCEPTED`; `OFFERED`, `DECLINED`, `REVOKED`, and `EXPIRED` awards are excluded. The excess is the amount by which the total exceeds the cap, or zero when the total fits. This stacking excess is local to the check: it drives only the over-award recovery pass below and is never written to the student record, whose stored `excess_cents` remains the §3.1 figure — always computed against the annual `aid_cap_cents`, regardless of the triggering program's stacking scope.

When the excess is above zero, the over-award recovery order runs as a single left-to-right pass with no re-iteration. The student's accepted awards are walked newest first — `accepted_at` descending, ties broken by `created_at` descending — tracking a remaining-excess figure that starts at the full excess. For each award, the reduction is the smaller of the remaining excess and that award's reducible headroom, meaning its `amount_cents` minus its net confirmed amount. When the reduction is positive, an auto-generated adjustment is created — `auto_generated` true, `reason` `OVER_AWARD`, `delta_cents` set to the negative of the reduction, and `status` `PENDING_APPROVAL` — and the remaining excess shrinks by the reduction. The pass stops when the remaining excess reaches zero or the list is exhausted; even though each reduction changes the stacking total, the pass never restarts. These auto-generated adjustments then flow through the same approval workflow as manual ones, per §3.8.

Waitlist promotion is the mirror of offer collapse. When an award whose application was `SELECTED` from a `FINALIZED` cycle is declined, expired, or revoked before any `CONFIRMED` disbursement exists, the selector fires on that cycle: among the cycle's applications still `WAITLISTED`, the one with the lowest `decision_rank` is promoted; ties break by `submitted_at` ascending and then `created_at` ascending; an empty waitlist pool makes the promotion a no-op. The promoted application moves `WAITLISTED` → `SELECTED`, ready for a fresh offer.

### 3.7. Disbursement Scheduling and Confirmation

Money reaches institutions through disbursements, which may be planned in two ways. The split-plan action, performed by a coordinator on an accepted award with a supplied `term_count`, generates the whole per-term schedule at once. The division is pinned: the base per-term amount is the award's `amount_cents` divided by `term_count` rounded down, and the remainder cents — the amount minus base times `term_count` — are dealt one extra cent each to the earliest terms, so term *i* receives the base plus one cent when *i* is at most the remainder, and the base otherwise. For example, 1,000,000 cents split over 3 terms yields 333,334, 333,333, and 333,333 cents in that order; the alternative residual-to-last convention would produce a different split and is not used. Each term's window runs from the acceptance date plus (*i*−1) times 180 days through the acceptance date plus *i* times 180 days minus one day — closed intervals, each ending the day before the next begins — and each term's `scheduled_date` equals its `term_start_date`, with `term_seq` numbering terms from 1. The split is refused unless the award is `ACCEPTED` (otherwise `ERR_INVALID_STATE`), and refused when a disbursement plan already exists for the award (with `ERR_AMOUNT_EXCEEDS_REMAINING`).

Manual scheduling gives the coordinator row-by-row control: the payload names the `award_id`, the `term_seq`, an `amount_cents` that must be positive (otherwise `ERR_VALIDATION`), a `scheduled_date`, the closed term window `term_start_date` through `term_end_date` (the end must be on or after the start, otherwise `ERR_INVALID_DATE_RANGE`), and the receiving `institution_name`, normally the student's own institution. Three gates apply. The award must be `ACCEPTED` with `funding_status` `ENCUMBERED` or `DISBURSING` (otherwise `ERR_AWARD_NOT_ACCEPTED`). The new term window must not overlap any other disbursement of the same award whose status is `SCHEDULED`, `SENT`, or `CONFIRMED` — the check treats the windows as closed intervals, so sharing even a single calendar day counts as overlap, while `RETURNED` and `CANCELLED` rows free their windows (violations are refused with `ERR_DISBURSEMENT_WINDOW_OVERLAP`). And the sum of the award's non-cancelled disbursements must not exceed the award's `amount_cents` (otherwise `ERR_AMOUNT_EXCEEDS_REMAINING`). A new disbursement starts `SCHEDULED`, and disbursements are listed with optional filtering by `award_id` and `status`.

Sending, a coordinator act, moves `SCHEDULED` → `SENT` under two gates: the award must still be `ACCEPTED` with funding `ENCUMBERED` or `DISBURSING` (otherwise `ERR_AWARD_NOT_ACCEPTED`), and the current date must be on or after the `scheduled_date` — sending on the scheduled day itself is allowed, while an earlier send is refused with `ERR_DISBURSEMENT_TOO_EARLY`. The send stamps `sent_at` and records the sender's `X-User-ID` as `sent_by_user_id`.

Confirmation is the financial aid officer's act, moving `SENT` → `CONFIRMED`; per §2.10 the confirmer's `X-User-ID` must differ from `sent_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The confirm stamps `confirmed_at` and fires the first link of the disbursement cascade: the fund's `disbursed_cents` grows by the confirmed amount, the fund's `reserved_cents` is recomputed, the student's `total_disbursed_cents` grows by the confirmed amount, and the award's `funding_status` is recomputed — the first confirmation moves `ENCUMBERED` → `DISBURSING`, and when the net confirmed amount reaches `amount_cents` the award moves `DISBURSING` → `FULLY_DISBURSED`. Reaching `FULLY_DISBURSED` fires the cascade's second and third links: a thank-you letter is auto-created for the award when none exists yet (§3.9), and every donor report of that donor currently in `GENERATED` reverts to `DRAFT` for regeneration. `CONFIRMED` is terminal for the disbursement itself, though the mark-returned path below can pull money back.

Marking a disbursement returned is the financial aid officer's act and applies to `SENT` or `CONFIRMED` rows (otherwise `ERR_INVALID_STATE`); the `returned_reason` must be present (otherwise `ERR_VALIDATION`), and `returned_at` is stamped. From `SENT`, no money has moved, so the row simply becomes `RETURNED`. From `CONFIRMED`, the clawback runs: the fund's `returned_cents` grows by the amount and its `reserved_cents` is recomputed, the student's `total_disbursed_cents` shrinks by the amount, and the award's `funding_status` is recomputed — `FULLY_DISBURSED` drops back to `DISBURSING` when the net confirmed amount falls below `amount_cents`, an `OVER_DISBURSED` award returns to `FULLY_DISBURSED` when returns bring the net confirmed amount back up to `amount_cents`, and `DISBURSING` drops back to `ENCUMBERED` when every confirmation has been returned and the net confirmed amount reaches zero.

Rescheduling, a coordinator act, retries a `RETURNED` disbursement: a new `scheduled_date` must be supplied (otherwise `ERR_VALIDATION`), the replacement term window must pass the same closed-interval overlap check — with the row being rescheduled excluding itself from the comparison set (otherwise `ERR_DISBURSEMENT_WINDOW_OVERLAP`) — and on success the row returns to `SCHEDULED` with `scheduled_date` and the term window replaced and `sent_at`, `confirmed_at`, and `returned_at` cleared. The retry supersedes the earlier return in the fund arithmetic: a row returned from `CONFIRMED` continues to count in the gross `disbursed_cents` while it is `RETURNED` or awaiting its retry, and when the row is sent and confirmed again it once more counts in full toward the award's net confirmed amount and no longer counts in `returned_cents`, so the award's `funding_status` is recomputed by the usual net-confirmed thresholds and can re-reach `FULLY_DISBURSED`. Cancellation, also a coordinator act, moves `SCHEDULED` → `CANCELLED`; cancelled rows are excluded from the award's funding arithmetic entirely. An award sitting in `OVER_DISBURSED` carries a recovery expectation equal to its net confirmed amount minus its `amount_cents` — the money already with the institution above what the adjusted award now covers.

### 3.8. Adjustments and Renewals

Corrections to an award's amount travel through a two-person adjustment workflow. A coordinator or a financial aid officer creates the adjustment in `DRAFT`, naming the `award_id`, a `reason` of `OVER_AWARD`, `DUPLICATE`, `DATA_ERROR`, or `WITHDRAWAL`, and a signed `delta_cents` — negative for a clawback, and never zero (otherwise `ERR_VALIDATION`); the creator's `X-User-ID` is recorded as `created_by_user_id`, and `auto_generated` is false for these manual drafts. Submitting moves `DRAFT` → `PENDING_APPROVAL` and is open to either role. Approval belongs to the financial aid officer alone, and the officer's `X-User-ID` must differ from `created_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`, per §2.10). Two fiscal floors guard approval: the resulting `amount_cents` must remain strictly positive (otherwise `ERR_VALIDATION`), and for `DUPLICATE` and `DATA_ERROR` reasons the resulting amount must remain at least the award's net confirmed amount — the money already out the door — otherwise `ERR_ADJUSTMENT_EXCEEDS_DISBURSED`; for `OVER_AWARD` and `WITHDRAWAL` reasons, dipping below the net confirmed amount is allowed and flips the award to `OVER_DISBURSED` with the recovery expectation of §3.7. An applied adjustment records the approver as `approved_by_user_id`, adds `delta_cents` to the award's `amount_cents`, recomputes the fund's `reserved_cents` and the student's totals and `excess_cents`, flips the award to `OVER_DISBURSED` when the net confirmed amount exceeds the new amount, and runs the stacking recompute of §3.6 — the cascade's second link — which may create further auto-generated adjustments in the same single newest-accepted-first pass. Rejection, also officer-only and also segregated from the creator, moves `PENDING_APPROVAL` → `REJECTED`. `APPLIED` and `REJECTED` are terminal; adjustments are listed with optional filtering by `award_id` and `status`.

Renewal keeps a multi-year award honest from year to year. Once an award is `FULLY_DISBURSED` under a renewable program, a coordinator or the student opens a renewal evaluation naming the `award_id`, the academic `term_label` such as "2027-SPRING", and the student's self-reported `reported_gpa_hundredths` and `reported_credits`; the evaluation starts `PENDING`. Creation is gated: the program must be renewable and the award must be `FULLY_DISBURSED`; the award's `renewal_count` must still be below the program's `max_renewals` (otherwise `ERR_MAX_RENEWALS_REACHED`); and no other evaluation for the award may sit in a non-terminal status — anything other than `RENEWED` or `LAPSED` — otherwise `ERR_DUPLICATE_RENEWAL_EVALUATION`. Evaluations are listed with optional filtering by `award_id` and `status`.

Verification is the coordinator's act and supplies the registrar's figures: `registrar_gpa_hundredths` and `registrar_credits`, both required (otherwise `ERR_VALIDATION`). The renewal threshold check is inclusive on both legs: the registrar GPA must be at least the program's `renewal_min_gpa_hundredths` and the registrar credits at least the program's `renewal_min_credits` — a figure exactly at the threshold passes, one below it fails. A pass moves the evaluation to `VERIFIED_ELIGIBLE`, a miss to `VERIFIED_INELIGIBLE`; either way the registrar values are stored and the verifier's `X-User-ID` is recorded as `verified_by_user_id`. Verification is allowed from `PENDING` and again from `APPEALED`, where the registrar values are overwritten with the new figures. An adverse verdict is not final: the student or a coordinator may appeal a `VERIFIED_INELIGIBLE` evaluation (otherwise `ERR_INVALID_STATE`) with an `appeal_note` present (otherwise `ERR_VALIDATION`), moving it to `APPEALED` for re-verification.

Finalizing carries a `decision`. A `RENEW` decision requires the evaluation to be `VERIFIED_ELIGIBLE` — a mismatched decision is refused with `ERR_RENEWAL_NOT_ELIGIBLE` — and requires `renewal_count` still below `max_renewals` (otherwise `ERR_MAX_RENEWALS_REACHED`); on success the evaluation becomes `RENEWED`, `decided_at` is stamped, the award's `renewal_count` increases by one, the award's `amount_cents` grows by the program's `award_amount_cents` as the next-year tranche, the fund's reservation is recomputed, and the stacking recompute of §3.6 runs and may auto-create adjustments. A `LAPSE` decision requires `VERIFIED_INELIGIBLE` (otherwise `ERR_RENEWAL_NOT_ELIGIBLE`); on success the evaluation becomes `LAPSED`, `decided_at` is stamped, and the award is not renewable further. `RENEWED` and `LAPSED` are terminal.

### 3.9. Thank-You Letters and Donor Reporting

Stewardship begins the moment an award is fully disbursed: the disbursement cascade of §3.7 auto-creates a thank-you letter for the award when none exists yet — letters are only ever cascade-created, so `auto_created` is always true — with `status` `REQUIRED`, or `WAIVED` at creation when the program's donor is anonymous, and a `due_at` thirty days after the full-disbursement timestamp. Re-reaching `FULLY_DISBURSED` never duplicates the letter. Letters are listed with optional filtering by `award_id` and `status`.

The letter's lifecycle is a small review loop. The student submits content — the caller's `X-User-ID` must equal the award's `student_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`) and a `content_ref` must be present (otherwise `ERR_VALIDATION`) — moving the letter from `REQUIRED` or `REVISION_REQUESTED` to `SUBMITTED`. A coordinator may then request a revision (`SUBMITTED` → `REVISION_REQUESTED`, the revision cycle), approve the letter (`SUBMITTED` → `APPROVED`), and finally deliver it (`APPROVED` → `DELIVERED`); delivery reverts every covered donor report in `GENERATED` back to `DRAFT` for a staleness recompute. A coordinator may instead waive a `REQUIRED` letter, but only when the program's donor is anonymous — otherwise the waive is refused with `ERR_TYL_NOT_WAIVABLE`. `DELIVERED` and `WAIVED` are terminal.

Donor reports aggregate a period of giving. A coordinator creates one in `DRAFT` naming the `donor_id` and the half-open reporting window `period_start` through `period_end` — the start is included, the end excluded, and the end must be strictly after the start (otherwise `ERR_INVALID_DATE_RANGE`); reports are listed with optional filtering by `donor_id` and `status`. Generating the report — a coordinator act from `DRAFT` — computes three aggregates. The included awards are those whose application's program belongs to the report's donor and that hold at least one `CONFIRMED` disbursement whose `confirmed_at` falls inside the half-open window, where a confirmation exactly at `period_end` is excluded. `total_awards_count` counts those awards; `total_disbursed_cents` sums their in-window confirmed amounts; and `thank_you_complete` is true exactly when every included award's letter sits in `DELIVERED` or `WAIVED`. Reading a report refreshes `thank_you_complete` against current letter states. For donors whose `anonymous` flag is set, the report omits recipient identity; the donor's `report_frequency` (`QUARTERLY` or `ANNUAL`) expresses the cadence the office has promised.

Reports go stale on purpose. A report in `GENERATED` returns to `DRAFT` whenever a thank-you letter for that donor is created, whenever a letter leaves the `DELIVERED` or `WAIVED` state, or whenever a disbursement covered by the report is newly confirmed — the regeneration cycle that keeps a sent report honest. Sending requires the report to be `GENERATED` (otherwise `ERR_INVALID_STATE`) and `thank_you_complete` to be true — a report whose covered letters are not all delivered or waived is refused with `ERR_REPORT_INCOMPLETE`; a successful send moves the report to `SENT` and stamps `sent_at`. Acknowledgement closes the loop: the donor — and only that donor, with `X-User-ID` equal to the report's `donor_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`) — moves the report from `SENT` to `ACKNOWLEDGED`, its terminal state.

## 4. Endpoint Definitions

Operations that create a new resource — a student, donor, fund, program, application, component, review cycle, review score, award, disbursement, adjustment, renewal evaluation, or donor report — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. The logical-clock set and the daily operations run also return `200 OK`. All paths below are served exactly as written under the `/api` prefix; the request payloads, derived fields, and side effects behind each operation are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/api/_ops/run_daily` | Run the daily operations checkpoint | PlatformAdmin |
| POST | `/api/students` | Register a student profile | ScholarshipCoordinator |
| GET | `/api/students/{id}` | Get a student | ScholarshipCoordinator, Student, FinancialAidOfficer |
| PATCH | `/api/students/{id}` | Update student profile fields, including GPA verification | ScholarshipCoordinator |
| POST | `/api/students/{id}/archive` | Archive a student (soft delete) | ScholarshipCoordinator |
| GET | `/api/students/{id}/aid-summary` | Computed aid summary with per-award breakdown | ScholarshipCoordinator, Student, FinancialAidOfficer |
| POST | `/api/donors` | Register a donor | ScholarshipCoordinator |
| GET | `/api/donors/{id}` | Get a donor | ScholarshipCoordinator, Donor |
| POST | `/api/award-funds` | Create an award fund | ScholarshipCoordinator |
| GET | `/api/award-funds/{id}` | Get a fund with derived balances | ScholarshipCoordinator, FinancialAidOfficer |
| POST | `/api/award-funds/{id}/commitments` | Add committed money to a fund (OCC-guarded) | ScholarshipCoordinator |
| POST | `/api/scholarship-programs` | Create a scholarship program | ScholarshipCoordinator |
| GET | `/api/scholarship-programs` | List programs with optional filters | ScholarshipCoordinator, Student, CommitteeReviewer, FinancialAidOfficer, Donor |
| GET | `/api/scholarship-programs/{id}` | Get a program | ScholarshipCoordinator, Student, CommitteeReviewer, FinancialAidOfficer, Donor |
| PUT | `/api/scholarship-programs/{id}` | Edit program criteria while DRAFT or CLOSED (OCC-guarded) | ScholarshipCoordinator |
| POST | `/api/scholarship-programs/{id}/publish` | Publish a program, opening its application window | ScholarshipCoordinator |
| POST | `/api/scholarship-programs/{id}/close` | Manually close a program | ScholarshipCoordinator |
| POST | `/api/scholarship-programs/{id}/extend` | Extend the deadline and reopen a closed program | ScholarshipCoordinator |
| POST | `/api/scholarship-programs/{id}/archive` | Archive a closed program | ScholarshipCoordinator |
| POST | `/api/applications` | Create a draft application | ScholarshipCoordinator, Student |
| GET | `/api/applications` | List applications with optional filters | ScholarshipCoordinator, Student, CommitteeReviewer, FinancialAidOfficer |
| GET | `/api/applications/{id}` | Get an application | ScholarshipCoordinator, Student, CommitteeReviewer, FinancialAidOfficer |
| POST | `/api/applications/{id}/submit` | Submit an application | ScholarshipCoordinator, Student |
| POST | `/api/applications/{id}/return` | Return a submitted application for correction | ScholarshipCoordinator |
| POST | `/api/applications/{id}/withdraw` | Withdraw an application | ScholarshipCoordinator, Student |
| POST | `/api/applications/{id}/components` | Add a component requirement item to a draft application | ScholarshipCoordinator, Student |
| GET | `/api/applications/{id}/components` | List components of an application | ScholarshipCoordinator, Student |
| GET | `/api/components/{id}` | Get a component | ScholarshipCoordinator, Student |
| POST | `/api/components/{id}/receive` | Mark a component received with its content reference | ScholarshipCoordinator, Student |
| POST | `/api/components/{id}/accept` | Accept a received component | ScholarshipCoordinator |
| POST | `/api/components/{id}/reject` | Reject a received component | ScholarshipCoordinator |
| POST | `/api/components/{id}/waive` | Waive a pending component | ScholarshipCoordinator |
| GET | `/api/applications/{id}/reminders` | List reminders of an application | ScholarshipCoordinator, Student, PlatformAdmin |
| POST | `/api/review-cycles` | Create a review cycle | ScholarshipCoordinator |
| GET | `/api/review-cycles` | List review cycles | ScholarshipCoordinator, CommitteeReviewer |
| GET | `/api/review-cycles/{id}` | Get a review cycle | ScholarshipCoordinator, CommitteeReviewer |
| POST | `/api/review-cycles/{id}/open-scoring` | Open scoring and move submitted applications under review | ScholarshipCoordinator |
| POST | `/api/review-cycles/{id}/open-deliberation` | Open deliberation, locking submitted scores | ScholarshipCoordinator |
| POST | `/api/review-cycles/{id}/reopen-scoring` | Reopen scoring from deliberation | ScholarshipCoordinator |
| POST | `/api/review-cycles/{id}/finalize` | Finalize the cycle and rank applications | ScholarshipCoordinator |
| POST | `/api/review-scores` | Create a draft review score | CommitteeReviewer |
| GET | `/api/review-scores` | List review scores | ScholarshipCoordinator, CommitteeReviewer |
| GET | `/api/review-scores/{id}` | Get a review score | ScholarshipCoordinator, CommitteeReviewer |
| POST | `/api/review-scores/{id}/submit` | Submit a draft score, computing its weighted total | CommitteeReviewer |
| POST | `/api/review-scores/{id}/recall` | Recall a submitted score while scoring remains open | CommitteeReviewer |
| POST | `/api/awards` | Create an award offer on a selected application | ScholarshipCoordinator |
| GET | `/api/awards` | List awards with optional filters | ScholarshipCoordinator, Student, FinancialAidOfficer |
| GET | `/api/awards/{id}` | Get an award | ScholarshipCoordinator, Student, FinancialAidOfficer |
| PATCH | `/api/awards/{id}` | Adjust an offered award's amount (OCC-guarded) | ScholarshipCoordinator |
| POST | `/api/awards/{id}/accept` | Accept an award offer | Student |
| POST | `/api/awards/{id}/decline` | Decline an award offer | Student |
| POST | `/api/awards/{id}/revoke` | Revoke an offered or accepted award | ScholarshipCoordinator |
| POST | `/api/awards/{id}/schedule-split` | Generate the per-term disbursement plan | ScholarshipCoordinator |
| POST | `/api/disbursements` | Manually schedule a disbursement | ScholarshipCoordinator |
| GET | `/api/disbursements` | List disbursements with optional filters | ScholarshipCoordinator, FinancialAidOfficer, Student |
| GET | `/api/disbursements/{id}` | Get a disbursement | ScholarshipCoordinator, FinancialAidOfficer, Student |
| POST | `/api/disbursements/{id}/send` | Send a scheduled disbursement | ScholarshipCoordinator |
| POST | `/api/disbursements/{id}/confirm` | Confirm a sent disbursement | FinancialAidOfficer |
| POST | `/api/disbursements/{id}/mark-returned` | Mark a sent or confirmed disbursement returned | FinancialAidOfficer |
| POST | `/api/disbursements/{id}/reschedule` | Reschedule a returned disbursement | ScholarshipCoordinator |
| POST | `/api/disbursements/{id}/cancel` | Cancel a scheduled disbursement | ScholarshipCoordinator |
| POST | `/api/award-adjustments` | Create a draft award adjustment | ScholarshipCoordinator, FinancialAidOfficer |
| GET | `/api/award-adjustments` | List award adjustments | ScholarshipCoordinator, FinancialAidOfficer |
| GET | `/api/award-adjustments/{id}` | Get an award adjustment | ScholarshipCoordinator, FinancialAidOfficer |
| POST | `/api/award-adjustments/{id}/submit` | Submit an adjustment for approval | ScholarshipCoordinator, FinancialAidOfficer |
| POST | `/api/award-adjustments/{id}/approve` | Approve and apply an adjustment | FinancialAidOfficer |
| POST | `/api/award-adjustments/{id}/reject` | Reject an adjustment | FinancialAidOfficer |
| POST | `/api/renewal-evaluations` | Open a renewal evaluation | ScholarshipCoordinator, Student |
| GET | `/api/renewal-evaluations` | List renewal evaluations | ScholarshipCoordinator, Student |
| GET | `/api/renewal-evaluations/{id}` | Get a renewal evaluation | ScholarshipCoordinator, Student |
| POST | `/api/renewal-evaluations/{id}/verify` | Verify registrar figures against renewal thresholds | ScholarshipCoordinator |
| POST | `/api/renewal-evaluations/{id}/appeal` | Appeal an ineligible verification | ScholarshipCoordinator, Student |
| POST | `/api/renewal-evaluations/{id}/finalize-renewal` | Renew or lapse the award | ScholarshipCoordinator |
| GET | `/api/thank-you-letters` | List thank-you letters | ScholarshipCoordinator, Student, Donor |
| GET | `/api/thank-you-letters/{id}` | Get a thank-you letter | ScholarshipCoordinator, Student, Donor |
| POST | `/api/thank-you-letters/{id}/submit` | Submit letter content | Student |
| POST | `/api/thank-you-letters/{id}/request-revision` | Request a letter revision | ScholarshipCoordinator |
| POST | `/api/thank-you-letters/{id}/approve` | Approve a letter | ScholarshipCoordinator |
| POST | `/api/thank-you-letters/{id}/deliver` | Deliver an approved letter | ScholarshipCoordinator |
| POST | `/api/thank-you-letters/{id}/waive` | Waive a required letter for an anonymous donor | ScholarshipCoordinator |
| POST | `/api/donor-reports` | Create a draft donor report for a period | ScholarshipCoordinator |
| GET | `/api/donor-reports` | List donor reports | ScholarshipCoordinator, Donor |
| GET | `/api/donor-reports/{id}` | Get a donor report | ScholarshipCoordinator, Donor |
| POST | `/api/donor-reports/{id}/generate` | Generate the report's aggregates over the period | ScholarshipCoordinator |
| POST | `/api/donor-reports/{id}/send` | Send a generated report to the donor | ScholarshipCoordinator |
| POST | `/api/donor-reports/{id}/acknowledge` | Acknowledge receipt of a sent report | Donor |

## 5. Error Code Catalogue

The trigger condition for each error is specified in §2 and §3 alongside the rule that raises it; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_COMPONENT_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_INELIGIBLE_STUDENT` | 422 Unprocessable Entity |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REVIEWER_DUPLICATE_SCORE` | 409 Conflict |
| `ERR_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_AWARD_NOT_ACCEPTED` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
| `ERR_DISBURSEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AMOUNT_EXCEEDS_REMAINING` | 422 Unprocessable Entity |
| `ERR_DISBURSEMENT_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ADJUSTMENT_EXCEEDS_DISBURSED` | 422 Unprocessable Entity |
| `ERR_RENEWAL_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_MAX_RENEWALS_REACHED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RENEWAL_EVALUATION` | 409 Conflict |
| `ERR_TYL_NOT_WAIVABLE` | 422 Unprocessable Entity |
| `ERR_REPORT_INCOMPLETE` | 422 Unprocessable Entity |

# Youth Club Site Operations API — Product Requirements Document

## 1. Introduction

A youth development organization in the Boys & Girls Club tradition operates neighborhood club sites where school-age children spend their after-school hours: they arrive by bus or on foot, rotate through program areas under supervised staff-to-youth ratios, eat reimbursable meals and snacks, and are supported by income-tiered fees and donor-funded scholarships. Every one of those activities leaves a record that must survive scrutiny — a state agency auditing a meal reimbursement claim, a funder verifying the attendance rate it paid for, a parent disputing who was authorized to pick up their child. This document specifies the API that keeps those records.

The system manages the full operational loop of a club site. Platform administrators onboard sites, staff, program areas, transport routes, and scholarship funds. Site directors and frontline staff run the daily cycle: opening a club day, signing members in and out under strict pickup authorization, rotating youth and staff through area blocks, and closing and reconciling the day. Around that daily cycle sit the slower loops — membership applications and income-based fee tiers, scholarship reservation and disbursement, behavior incidents and the suspension process, staff credential compliance, monthly meal claims, and funder outcome reports.

Three concerns cut across everything that follows. Child-safety gates are evaluated before convenience and before money: an unauthorized pickup name or a lapsed staff background check stops the operation regardless of what else is true. Money is conserved, not invented: every scholarship budget partitions exactly into available, reserved, and disbursed portions at all times, and every fee movement is an explicit ledger entry. And duties are segregated: the operator who submits a meal claim or a funder report may never be the one who approves or accepts it, and the director who adjudicates an incident may never be the one who resolves its appeal.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and guarantees that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles, spelled as follows: `PlatformAdmin`, `SiteDirector`, `FrontlineStaff`, `StateAgencyReviewer`, and `FunderContact`.

Two of the roles are entity-backed. When `X-User-Role` is `SiteDirector`, the `X-User-ID` must be the `id` of a persisted Staff record whose `position` is `DIRECTOR` and whose `status` is `ACTIVE`; ownership and accountability checks then compare that staff id against recorded actor fields. When `X-User-Role` is `FrontlineStaff`, the `X-User-ID` must likewise be the `id` of a Staff record whose `position` is `FRONTLINE` and whose `status` is `ACTIVE`. The remaining roles are opaque: when `X-User-Role` is `PlatformAdmin`, `StateAgencyReviewer`, or `FunderContact`, the `X-User-ID` is an operator identifier not tied to any persisted entity, though the server does record it on resources that capture actor fields — for example `submitted_by_user_id` on a meal claim or funder report, or `approved_by_user_id` on a claim — and segregation-of-duties checks compare those recorded values against the caller's header.

A request with a missing or unknown role header, a missing user-id header, or an entity-backed identity that does not resolve to a matching `ACTIVE` Staff row is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not listed among the endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). All five roles may call every read endpoint; write privileges are enumerated per endpoint in Section 4.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The platform never reads wall-clock time. All date- and time-sensitive rules read a server-side logical clock whose startup default, before any override call, is exactly 2026-08-01T00:00:00Z. A `PlatformAdmin` may set the logical clock to an arbitrary instant through an admin-only test-driving capability that accepts a `to_iso8601` timestamp; the response echoes the new value as `current_utc`. Monotonicity is not enforced — tests and operators may move the clock to any instant. Throughout this document, the words "now" and "today" refer to this logical clock. Club-day creation dates, sign-in eligibility, the open and close sweeps, credential expiry, the rolling behavior-points window, suspension windows, and the seasonal meal multiplier all evaluate against it.

### 2.5. Resource Identity and Audit Fields

Every resource in the system — sites, staff, members, guardians, funds, awards, club days, attendance records, program areas, rotation assignments, routes, ride assignments, meal claims, behavior incidents, and funder reports — carries a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits. The `updated_at` timestamp follows the same format and is refreshed on every mutation. The `version` is a system-managed integer that increments by one on every mutation of the resource, whether the mutation was client-requested or produced by a system cascade or sweep. Clients never supply `id`, `created_at`, `updated_at`, or `version` on creation, and no resource in this system omits any of the four.

### 2.6. Money, Cents, and Rounding

All monetary values are integer cents; there are no fractional-cent amounts anywhere in the system. Whenever a computed monetary value is not already a whole number of cents, it is rounded half-up to whole cents. Rounding is pinned at the smallest unit of each calculation and never repeated on aggregates: meal-claim lines are rounded per (day, meal type, eligibility tier) before summing, and scholarship discounts are rounded per member per week before any cap is applied. Staffing arithmetic uses integer ceiling division. Attendance rates and averages are carried to four decimal places, again rounded half-up. Exact boundary comparisons throughout the system are inclusive where stated: an income exactly equal to an eligibility limit takes the lower-priced tier, a fee balance exactly equal to the arrears limit still permits sign-in, and a discipline-point total of exactly ten triggers the watch.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and no other endpoint accepts a version field. First, activating a scholarship award requires the request to carry `expected_fund_version`, the client's last observed `version` of the parent scholarship fund. If the fund's current `version` has advanced beyond that value — because another writer has since activated or revoked an award and legitimately moved `reserved_cents` and `available_cents` — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from spending against a budget view it has not re-read. Second, posting a fee payment requires `expected_member_version`, the client's last observed `version` of the member. If the member's `version` has advanced — because a weekly accrual or an earlier payment has legitimately moved `fee_balance_cents` — the payment is rejected with `ERR_STALE_VERSION` (HTTP 412). In both cases the expected-version field is non-optional on those two operations.

### 2.8. The Request Validation Pipeline

Every request is validated against a fixed, ten-stage pipeline, and the first failing stage determines the error returned. The stages, in order, are:

1. **Authentication.** The role and user-id headers must be present, the role must be one of the five declared roles, and entity-backed roles must resolve to a matching `ACTIVE` Staff row; failures yield `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The authenticated role must appear in the endpoint's authorized role list; failures yield `ERR_UNAUTHORIZED_ROLE` (403).
3. **Resource resolution.** Path identifiers are validated left to right, then body foreign-key fields — `site_id`, `member_id`, `fund_id`, `club_day_id`, `area_id`, `route_id`, `new_area_id` — must resolve to existing rows; the first unresolvable reference yields `ERR_NOT_FOUND` (404).
4. **Request-body well-formedness.** Required fields must be present, enum values must be in range, unknown fields are rejected, integers must be positive where required, and the rotation-assignment discipline — `kind` of `YOUTH` requires `member_id` and forbids `staff_id`, while `kind` of `STAFF` requires `staff_id` and forbids `member_id` — is enforced here; failures yield `ERR_VALIDATION` (400).
5. **Target-resource state.** The state machine of the resource named in the path must permit the requested transition from its current state. Each machine raises its own conflict identifier, all HTTP 409: `ERR_MEMBER_NOT_APPLIED` when deciding a member not in `APPLIED`; `ERR_GUARDIAN_NOT_ACTIVE`; `ERR_FUND_NOT_OPEN`; `ERR_AWARD_NOT_PENDING` on activation and `ERR_AWARD_NOT_ACTIVE` on revocation; `ERR_CLUB_DAY_NOT_OPEN` and `ERR_CLUB_DAY_NOT_CLOSED`; `ERR_DAY_LOCKED` for meal-count edits on a reconciled day; `ERR_ALREADY_SIGNED_OUT` and `ERR_ATTENDANCE_FINAL` on sign-out; `ERR_ASSIGNMENT_NOT_CHECKABLE` and `ERR_ASSIGNMENT_NOT_MOVABLE`; `ERR_RIDE_NOT_ACTIVE`; `ERR_CLAIM_NOT_SUBMITTABLE` and `ERR_CLAIM_NOT_SUBMITTED`; `ERR_INCIDENT_NOT_REPORTED`, `ERR_INCIDENT_NOT_APPEALABLE`, and `ERR_APPEAL_NOT_PENDING`; `ERR_REPORT_NOT_SUBMITTABLE` and `ERR_REPORT_NOT_SUBMITTED`.
6. **Youth-safety gates.** Pickup authorization, walker permission, staff compliance, and the mandatory-suspension rule are evaluated here, each with its own unprocessable-entity identifier detailed in Section 3.
7. **Clock and window rules.** Club-day creation and sign-in require the day's date to equal logical today (`ERR_DAY_NOT_TODAY`, 409), and ride windows must be well-formed (`ERR_INVALID_DATE_WINDOW`, 422).
8. **Referenced-entity state.** Operations that reference a member require the member `ACTIVE` where Section 3 says so (`ERR_MEMBER_NOT_ACTIVE`, 409); operations on a club day require it `OPEN` (`ERR_CLUB_DAY_NOT_OPEN`); award creation and activation require the fund `OPEN` (`ERR_FUND_NOT_OPEN`); a `BUS` sign-out requires a covering ride (`ERR_NO_RIDE_FOR_DATE`, 422).
9. **Uniqueness, overlap, and capacity.** Duplicate club days, attendance records, claim months, and report months (`ERR_DUPLICATE_CLUB_DAY`, `ERR_DUPLICATE_ATTENDANCE`, `ERR_DUPLICATE_CLAIM_MONTH`, `ERR_DUPLICATE_REPORT_MONTH`), the site-capacity gate (`ERR_OVER_CAPACITY`), ride-window overlap (`ERR_RIDE_WINDOW_OVERLAP`), and per-block assignment conflicts (`ERR_ASSIGNMENT_CONFLICT`) are all 409; area capacity (`ERR_AREA_CAPACITY_EXCEEDED`), staff-to-youth ratio (`ERR_RATIO_VIOLATION`), route seat capacity (`ERR_SEAT_CAPACITY_EXCEEDED`), and meal-count attendance checks (`ERR_MEAL_COUNTS_EXCEED_ATTENDANCE`) are 422.
10. **Money gates, last.** The fee-arrears gate (`ERR_FEE_ARREARS_EXCEEDED`, 402), fund sufficiency (`ERR_FUND_INSUFFICIENT`, 422), payment overpayment (`ERR_OVERPAYMENT`, 422), and the optimistic-concurrency check (`ERR_STALE_VERSION`, 412) are evaluated with the fiscal write, after every other gate has passed.

Where Section 3 pins a finer order inside a stage — capacity before ratio on youth check-in, the over-capacity posture check before the sign-in record exists — that local order is normative.

### 2.9. Cross-Entity Consistency: Cascades, Counters, and Day Posture

The server keeps the object graph consistent without waiting for clients to clean up after themselves. Withdrawing a member resolves that member's scholarship awards, ride assignments, and future rotation assignments; closing a scholarship fund cancels its pending awards; lapsing a staff credential cancels the staffer's upcoming assignments; closing a club day finalizes every unresolved attendance record and rotation assignment on it. Each cascaded transition is a real mutation: the affected resource's `updated_at` refreshes and its `version` increments.

Club days carry live counters and a live safety posture. The `present_count`, `signed_out_count`, and `missing_signout_count` counters track the day's attendance records by status, and the `posture` — one of `NORMAL`, `RATIO_STRAINED`, or `OVER_CAPACITY` — is recomputed on every sign-in, sign-out, rotation check-in, rotation cancellation, and any cascade touching the day. The posture rule and its pinned evaluation order are defined with the club-day workflow in Section 3.4. Scholarship money obeys a conservation invariant — a fund's budget always equals the sum of its available, reserved, and disbursed portions — which is defined with the fund workflow in Section 3.3 and exercised by the weekly accrual in Section 3.9.

## 3. Business Logic & Workflows

### 3.1. Sites, Staff, and Credential Compliance

A `PlatformAdmin` onboards each club site with its `name`, its `youth_capacity` (the maximum number of youth allowed on site at once), its `standard_ratio` and `elevated_ratio` (the maximum youth per staff member in `STANDARD` and `ELEVATED` risk areas respectively), its fee schedule (`base_weekly_fee_cents` and the one-time `registration_fee_cents`), its arrears tolerance `max_arrears_cents`, and its `meal_rates_cents` — an object keyed by meal type (`BREAKFAST`, `SNACK`, `SUPPER`), each holding integer-cent reimbursement rates for the `FREE`, `REDUCED`, and `PAID` tiers. One optional knob remains: `fee_accrual_weekday`, an ISO weekday from 1 (Monday) through 7 (Sunday) that defaults to 5; closing a club day whose date falls on this weekday runs the weekly fee accrual described in Section 3.9.

Staffing begins when a `PlatformAdmin` hires a staff member with `site_id`, `full_name`, and `position`. A `position` of `DIRECTOR` entitles the person to act in the `SiteDirector` role; `FRONTLINE` entitles them to act as `FrontlineStaff`. New hires start in `HIRED` status with `compliance_status` `INCOMPLETE`, and both `background_check_expires_at` and `training_expires_at` null until their first credential posting.

Credential maintenance happens through a `PlatformAdmin` posting with two inputs: `kind`, one of `BACKGROUND_CHECK` or `TRAINING`, and `expires_at`, the new expiry instant for the corresponding credential field. Each posting recomputes `compliance_status` against the logical clock, in this exact precedence: `INCOMPLETE` when either credential expiry is null; otherwise `LAPSED` when either expiry is before now; otherwise `EXPIRING` when either expiry falls within the next thirty days; otherwise `COMPLIANT`. When a posting leaves a `HIRED` staff member with both credentials present and unexpired, the system promotes them to `ACTIVE` automatically; later postings leave the status `ACTIVE` unchanged and simply recompute compliance.

A lapse is never allowed to strand children in supervised areas. If a credential posting — or the passage of the logical clock surfaced by a club-day opening sweep (Section 3.4) — leaves a staff member `LAPSED`, the system cancels that staffer's `SCHEDULED` and `CHECKED_IN` rotation assignments on club days dated today or later, and recomputes the `posture` of every affected day; a cancellation that removes the last checked-in staff member from a day can flip that day straight to `RATIO_STRAINED`. Each cancelled assignment and each touched day bumps its `version`.

For day-to-day visibility, the staff roster of a site can be listed with optional `position` and `status` filters, and the rotation history of an individual staff member can be listed with optional `club_day_id` and `status` filters.

### 3.2. Membership: Applications, Eligibility, Guardians, and the Fee Ledger

Intake staff — a `SiteDirector` or `FrontlineStaff` operator — submit a membership application with the child's `site_id`, `legal_name`, `date_of_birth` in year-month-day form, `grade` from 0 through 12, `household_size`, and annual `household_income_cents`; an optional `walker_ok` flag, defaulting to false, records whether the child may leave on foot. A new member starts in `APPLIED` status with `fee_balance_cents` at zero, `behavior_points` at zero, `discipline_watch` false, and `eligibility_tier`, `weekly_fee_cents`, `approved_at`, and `withdrawn_at` all null until a decision.

Decisions belong to the `SiteDirector`, who supplies a `decision` of `APPROVE` or `DENY`; deciding a member not currently `APPLIED` is rejected with `ERR_MEMBER_NOT_APPLIED`. A denial moves the member to `DENIED` with no further effect. An approval performs the full enrollment accounting in one step. The eligibility tier is determined from household economics: the `FREE` limit for a household is 1,500,000 cents plus 500,000 cents for each household member beyond the first, and the `REDUCED` limit is 2,000,000 cents plus 650,000 cents for each member beyond the first. Income at or below the `FREE` limit yields `eligibility_tier` `FREE`; otherwise income at or below the `REDUCED` limit yields `REDUCED`; anything higher yields `PAID`. The weekly fee is then the site's `base_weekly_fee_cents` multiplied by the tier multiplier — zero for `FREE`, one-half for `REDUCED`, and one for `PAID` — rounded half-up to whole cents and stored as `weekly_fee_cents`. The one-time `registration_fee_cents` is added to `fee_balance_cents`, `approved_at` is stamped with the current logical instant, and the member becomes `ACTIVE`.

Guardians anchor the pickup-authorization rule of Section 3.5. Intake staff register a guardian with `member_id`, `full_name`, `relation`, and an optional `phone`; the guardian starts `ACTIVE`. A guardian may be added for any member who has not reached a terminal state — adding one for a `DENIED` or `WITHDRAWN` member is rejected with `ERR_MEMBER_NOT_ACTIVE`. Either a `SiteDirector` or `FrontlineStaff` operator may later revoke a guardian's pickup authorization; revocation requires the guardian to be `ACTIVE` (otherwise `ERR_GUARDIAN_NOT_ACTIVE`) and moves them to `REVOKED`, after which their `full_name` no longer authorizes pickup.

The member's `fee_balance_cents` is a ledger, not a number anyone sets directly: the registration fee and the weekly accruals of Section 3.9 add to it, while fee payments and scholarship disbursements subtract from it. A `SiteDirector` posts a payment with `amount_cents` and `expected_member_version`. Following Section 2.7, a stale member version is rejected with `ERR_STALE_VERSION` (412); an `amount_cents` greater than the current `fee_balance_cents` is rejected with `ERR_OVERPAYMENT` (422). A successful payment subtracts the amount from the balance and increments the member's `version`.

Withdrawal is the membership exit. A `SiteDirector` may withdraw a member in `ACTIVE` or `SUSPENDED` status — any other state is rejected with `ERR_MEMBER_NOT_ACTIVE`. The member becomes `WITHDRAWN` with `withdrawn_at` stamped, and the system cascades: every `PENDING` scholarship award of the member is `CANCELLED`; every `ACTIVE` award is `REVOKED`, which releases its remaining reservation back to the fund exactly as a manual revocation does (Section 3.3); every `ACTIVE` ride assignment is `ENDED`; and every `SCHEDULED` rotation assignment of the member on a club day dated today or later is `CANCELLED`. Each cascaded resource bumps its own `version`. Member rosters can be listed with optional `status` and `eligibility_tier` filters.

### 3.3. Scholarship Funds and Awards

A `PlatformAdmin` endows a scholarship fund with `site_id`, `name`, and `budget_cents`. The fund opens in `OPEN` status with `reserved_cents` and `disbursed_cents` at zero and `available_cents` equal to the budget. From that moment on, the fund obeys a strict conservation invariant checked after every mutation: the budget always equals the sum of `available_cents`, `reserved_cents`, and `disbursed_cents`, where `available_cents` is always derived as the budget minus the reserved portion minus the disbursed portion.

A `SiteDirector` drafts an award with `fund_id`, `member_id`, `discount_pct` (the fraction of the weekly fee the award covers — greater than zero and at most one), `weekly_cap_cents` (the most the award will pay in any single weekly accrual), and `annual_cap_cents` (the lifetime cap that will be reserved from the fund at activation). The referenced member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`) and the fund `OPEN` (`ERR_FUND_NOT_OPEN`). A new award starts `PENDING` with `disbursed_cents` at zero and `remaining_cap_cents` equal to its `annual_cap_cents`.

Activation is where money actually moves. A `SiteDirector` activates an award, and four gates stand in the way: the award must be `PENDING` (`ERR_AWARD_NOT_PENDING`), the fund must still be `OPEN` (`ERR_FUND_NOT_OPEN`), the fund's `available_cents` must be at least the award's `annual_cap_cents` (`ERR_FUND_INSUFFICIENT`, 422), and the request's `expected_fund_version` must match the fund's current `version` under the optimistic-concurrency rule of Section 2.7 (`ERR_STALE_VERSION`, 412). On success the fund's `reserved_cents` grows by the award's `annual_cap_cents`, `available_cents` is recomputed, both fund and award bump their `version`, and the award becomes `ACTIVE`.

Revocation releases money the other way. A `SiteDirector` revoking an award that is not `ACTIVE` is rejected with `ERR_AWARD_NOT_ACTIVE`; otherwise the award becomes `REVOKED`, the fund's `reserved_cents` shrinks by the award's `remaining_cap_cents`, `available_cents` is recomputed, and both versions increment. Withdrawal of the member triggers the same revocation automatically (Section 3.2).

A `PlatformAdmin` may close a fund that is `OPEN` (otherwise `ERR_FUND_NOT_OPEN`). Closing moves the fund to `CLOSED` and cancels every `PENDING` award on it; `ACTIVE` awards are deliberately unaffected — their reservations remain until they are revoked or exhausted by weekly disbursements (Section 3.9). Fund listings and per-fund or per-member award listings accept an optional `status` filter.

### 3.4. The Club Day: Opening Sweeps and Sign-In

Each operating day begins when a `SiteDirector` opens a club day with `site_id` and `date`. The date must equal logical today (`ERR_DAY_NOT_TODAY`, 409), and the site may have only one club day per date (`ERR_DUPLICATE_CLUB_DAY`, 409). The new day starts `OPEN` with `posture` `NORMAL`, all three counters — `present_count`, `signed_out_count`, `missing_signout_count` — at zero, `weekly_fees_accrued` false, and a zeroed `meal_counts` grid spanning every meal type and eligibility tier.

Opening the day is also the system's chance to sweep time-driven state forward. First, suspensions: every behavior incident whose suspension is `IMPOSED` and whose `suspension_start_date` has been reached by the new date becomes `ACTIVE`, flipping its member from `ACTIVE` to `SUSPENDED`; and every suspension already `ACTIVE` whose full window — from `suspension_start_date` forward `suspension_days` calendar days, end-exclusive — has elapsed by the new date becomes `SERVED`, returning the member from `SUSPENDED` to `ACTIVE` provided no other incident still holds an `ACTIVE` suspension for that member. Second, the staff lapse cascade of Section 3.1 runs, since credential expiries are measured against the moving logical clock. Every resource touched by a sweep bumps its `version`.

Signing a member in (a `SiteDirector` or `FrontlineStaff` operator, supplying `club_day_id` and `member_id`) creates an attendance record, and a wall of gates stands in front of it, evaluated in pipeline order: the day's date must equal logical today (`ERR_DAY_NOT_TODAY`); the day must be `OPEN` (`ERR_CLUB_DAY_NOT_OPEN`); the member must be `ACTIVE`, which is how suspensions physically bar entry (`ERR_MEMBER_NOT_ACTIVE`); the member must not already have an attendance record on this day (`ERR_DUPLICATE_ATTENDANCE`); the day's current `posture` must not be `OVER_CAPACITY`, evaluated before the new record is created (`ERR_OVER_CAPACITY`) — because the capacity threshold is inclusive, a day whose `present_count` has already reached the site's `youth_capacity` blocks further sign-ins; and finally the member's `fee_balance_cents` must not exceed the site's `max_arrears_cents`, with a balance exactly equal to the limit still allowed (`ERR_FEE_ARREARS_EXCEEDED`, 402). A successful sign-in stamps `sign_in_at` from the logical clock, leaves `sign_out_at` null, marks the record `ON_SITE`, raises the day's `present_count` by one, recomputes the day's `posture`, and bumps both the record's and the day's `version`.

The posture rule itself is pinned. Let the day's staffing be the count of staff-kind rotation assignments on the day with status `CHECKED_IN`, across all areas and blocks. If `present_count` has reached the site's `youth_capacity`, the `posture` is `OVER_CAPACITY`. Otherwise, if the staffing count multiplied by the site's `standard_ratio` is strictly less than `present_count`, the posture is `RATIO_STRAINED`. Otherwise it is `NORMAL`. The evaluation order is fixed — capacity first, then ratio — and the ratio leg always uses the site's `standard_ratio` regardless of which areas are in use.

### 3.5. Sign-Out Authorization and Same-Day Meal Counts

Every child who arrives must leave under an authorized hand-off, and the sign-out workflow (either a `SiteDirector` or `FrontlineStaff` operator) enforces it. The attendance record must still be `ON_SITE`: one already `SIGNED_OUT` is rejected with `ERR_ALREADY_SIGNED_OUT`, and one swept to `MISSING_SIGNOUT` by the day close is rejected with `ERR_ATTENDANCE_FINAL`. The requested `sign_out_type` then selects its authorization rule:

- `AUTHORIZED_PICKUP` requires a `pickup_name` that case-sensitively equals the `full_name` of an `ACTIVE` guardian of the member; any mismatch — including a revoked guardian or a differently cased spelling — is rejected with `ERR_PICKUP_NOT_AUTHORIZED` (422).
- `WALKER` requires the member's `walker_ok` flag to be true, otherwise `ERR_WALKER_NOT_PERMITTED` (422).
- `BUS` requires the member to hold an `ACTIVE` ride assignment whose half-open effective window covers the club day's date, otherwise `ERR_NO_RIDE_FOR_DATE` (422).

A successful sign-out stamps `sign_out_at`, moves the record to `SIGNED_OUT`, shifts one unit from the day's `present_count` to its `signed_out_count`, recomputes `posture`, and bumps both versions.

While the day is still `OPEN`, staff also record the food-service tally one meal type at a time, supplying `meal_type`, `free_count`, `reduced_count`, and `paid_count`; each call replaces that meal type's row inside the day's `meal_counts` and bumps the day's `version`. Every tier count is validated at entry: it may not exceed the number of the day's attendance records in `ON_SITE` or `SIGNED_OUT` whose member's `eligibility_tier` matches that tier, or the write is rejected with `ERR_MEAL_COUNTS_EXCEED_ATTENDANCE` (422). Posting counts against a day that is no longer `OPEN` is rejected with `ERR_CLUB_DAY_NOT_OPEN` — except a `RECONCILED` day, which answers with `ERR_DAY_LOCKED`. A second, stricter validation of the same counts runs at reconcile time (Section 3.9).

Attendance history is browsable per club day or per member, each list accepting an optional `status` filter.

### 3.6. Program Areas and Rotation Blocks

A `PlatformAdmin` defines each program area with `site_id`, `name`, and `capacity` — the maximum number of checked-in youth the area may hold in a single block — plus an optional `risk_tier` (`STANDARD`, the default, or `ELEVATED`) and an optional `ratio_override`. The area's effective staffing ratio is its `ratio_override` when set; otherwise it is the site's `elevated_ratio` for an `ELEVATED` area or the site's `standard_ratio` for a `STANDARD` one.

The operating day is divided into three blocks: `BLOCK_A`, `BLOCK_B`, and `BLOCK_C`. A `SiteDirector` or `FrontlineStaff` operator schedules a rotation assignment with `club_day_id`, `area_id`, `block`, `kind`, and exactly one participant reference: a `kind` of `YOUTH` requires `member_id` and forbids `staff_id`, while a `kind` of `STAFF` requires `staff_id` and forbids `member_id`, with any inconsistency rejected as `ERR_VALIDATION` (400). Scheduling requires the club day `OPEN` (`ERR_CLUB_DAY_NOT_OPEN`). A youth assignment additionally requires the member to be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), and a member may hold at most one non-terminal assignment — `SCHEDULED` or `CHECKED_IN` — for the same club day and block (`ERR_ASSIGNMENT_CONFLICT`, 409). A staff assignment requires the staffer to be `ACTIVE` with `compliance_status` `COMPLIANT` or `EXPIRING`; scheduling or checking in with an `INCOMPLETE` or `LAPSED` staffer is rejected with `ERR_STAFF_NOT_COMPLIANT` (422). New assignments start `SCHEDULED`.

Check-in is where the ratio math bites. The assignment must be `SCHEDULED` (`ERR_ASSIGNMENT_NOT_CHECKABLE`, 409) and the day `OPEN` (`ERR_CLUB_DAY_NOT_OPEN`). Staff check-ins re-verify compliance as above. Youth check-ins face two gates, evaluated in this order: first capacity — the number of checked-in youth in that area and block after this check-in may not exceed the area's `capacity`, or the check-in is rejected with `ERR_AREA_CAPACITY_EXCEEDED` (422); then ratio — the required staffing, computed as the after-check-in youth count divided by the area's effective ratio and rounded up to a whole number, may not exceed the number of staff currently checked in to that same area and block, or the check-in is rejected with `ERR_RATIO_VIOLATION` (422). The boundary is inclusive: a youth count exactly equal to the checked-in staff count multiplied by the effective ratio is allowed; one youth more is rejected. Any successful check-in — youth or staff — recomputes the day's `posture` and bumps the versions of both the assignment and the day.

Mid-block moves are supported for checked-in participants. Moving requires the assignment `CHECKED_IN` (`ERR_ASSIGNMENT_NOT_MOVABLE`), the day `OPEN`, and a destination `new_area_id` that resolves (`ERR_NOT_FOUND`). A youth move re-validates the destination — new area, same block — against capacity and then ratio exactly as a check-in would. The original record becomes `MOVED`, a successor assignment is created already `CHECKED_IN` with the same club day, block, kind, and participant but the new `area_id`, and the response returns the successor; the day's posture is recomputed and versions increment accordingly.

Rotation schedules are browsable per club day (with optional `area_id`, `block`, `kind`, and `status` filters), per area (`club_day_id`, `block`, `status`), per member (`status`), and per staffer.

### 3.7. School Transportation and Ride Windows

Transportation begins with a `PlatformAdmin` creating a route with `site_id`, `route_name`, the `school_name` it serves, and its `seat_capacity` in bus seats.

A `SiteDirector` then assigns a member to a route with `route_id`, `member_id`, `effective_start_date`, and an optional `effective_end_date`; omitting the end date leaves the assignment open-ended. Ride windows are half-open: the start date is included and the end date excluded, so a window ending on a given date does not cover that date. Assignment enforces four rules: the member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`); a provided `effective_end_date` must be later than `effective_start_date` (`ERR_INVALID_DATE_WINDOW`, 422); the new window must not overlap any other `ACTIVE` ride window belonging to the same member — adjacency is permitted precisely because windows are half-open (`ERR_RIDE_WINDOW_OVERLAP`, 409); and on every already-existing club day whose date falls inside the new window, the number of `ACTIVE` ride assignments on the route covering that date, counting the new one, may not exceed the route's `seat_capacity` (`ERR_SEAT_CAPACITY_EXCEEDED`, 422). A valid assignment starts `ACTIVE`.

Ending a ride early is a `SiteDirector` action taking an `end_date`. The ride must be `ACTIVE` (`ERR_RIDE_NOT_ACTIVE`, 409), and the `end_date` must be later than the ride's `effective_start_date` and no later than its current `effective_end_date` when one is set (`ERR_INVALID_DATE_WINDOW`). The ride's `effective_end_date` is rewritten to `end_date` and its status becomes `ENDED`; withdrawing the member ends rides automatically without a date rewrite (Section 3.2). These windows are what the `BUS` sign-out rule of Section 3.5 consults. Ride listings per route or per member accept an optional `status` filter.

### 3.8. Behavior Incidents, Discipline Points, and Suspensions

Any `SiteDirector` or `FrontlineStaff` operator may report a behavior incident with `member_id`, `incident_date` — which may lie in the past to accommodate late reporting — a `category` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3`, and an optional narrative `description`. The new incident starts with `adjudication_status` `REPORTED` and `suspension_status` `NONE`, and its `points` derive from its category: one point for `LEVEL_1`, three for `LEVEL_2`, and eight for `LEVEL_3`.

Those points feed the member's discipline ledger. A member's `behavior_points` are the summed `points` of the member's incidents that are `ADJUDICATED`, whose suspension has not been `RESCINDED`, and whose `incident_date` falls inside the rolling ninety-day window — from ninety days before logical today through today, both ends inclusive. Dismissed incidents, rescinded suspensions, and reports older than ninety days never count. When the total reaches ten points — exactly ten is enough — the member's `discipline_watch` turns true. The total is recomputed on every adjudication, on every upheld appeal, and on every read of the member, so it always reflects the current logical date; the adjudicate side effects bump the versions of both the incident and the member.

Adjudication belongs to the `SiteDirector` and requires the incident `REPORTED` (`ERR_INCIDENT_NOT_REPORTED`, 409); the adjudicator's `X-User-ID` is recorded in `adjudicated_by_user_id`. Three branches exist. An `outcome` of `DISMISS` moves the incident to `DISMISSED` with suspension `NONE`, and its points never enter the ledger. An `outcome` of `SUSTAINED` without suspension details moves it to `ADJUDICATED` with suspension `NONE` and the points begin counting — but only while the member's `discipline_watch` is false: once the watch is on, imposing a suspension is mandatory, and adjudicating without a positive `suspension_days` is rejected with `ERR_SUSPENSION_MANDATORY` (422). An `outcome` of `SUSTAINED` with `suspension_days` greater than zero and a `suspension_start_date` moves the incident to `ADJUDICATED` and imposes the suspension: if the start date is today or earlier, the suspension becomes `ACTIVE` immediately and the member flips from `ACTIVE` to `SUSPENDED` on the spot; if the start date is in the future, the suspension waits in `IMPOSED` until a club-day opening sweep activates it (Section 3.4). The suspension window runs from the start date for `suspension_days` calendar days, end-exclusive, and the same opening sweep marks it `SERVED` once the window has elapsed.

An active suspension may be appealed by a `SiteDirector` or `FrontlineStaff` operator; appealing anything whose `suspension_status` is not `ACTIVE` is rejected with `ERR_INCIDENT_NOT_APPEALABLE`. The suspension moves to `APPEALED`, and the member remains `SUSPENDED` while the appeal pends. Resolution is a `SiteDirector` action requiring the suspension `APPEALED` (`ERR_APPEAL_NOT_PENDING`) and a resolver whose `X-User-ID` differs from the recorded `adjudicated_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 403). A `decision` of `DENIED` returns the suspension to `ACTIVE` and the member stays suspended. A `decision` of `UPHELD` moves the suspension to `RESCINDED`: the incident's points stop counting toward `behavior_points` (recomputing the watch), and the member returns from `SUSPENDED` to `ACTIVE` provided no other incident still holds an `ACTIVE` suspension for them; in that case both the incident's and the member's versions increment.

### 3.9. Closing the Books: Day Close, Meal Claims, and Funder Reports

Closing a club day is a `SiteDirector` action requiring the day `OPEN` (`ERR_CLUB_DAY_NOT_OPEN`). The close sweep finalizes the day's loose ends: every attendance record still `ON_SITE` flips to `MISSING_SIGNOUT`, with `present_count` falling and `missing_signout_count` rising by the same amount; every rotation assignment still `SCHEDULED` is `CANCELLED`; every assignment `CHECKED_IN` is `COMPLETED`; and each flipped record bumps its `version`.

When the ISO weekday of the day's `date` matches the site's `fee_accrual_weekday`, closing also runs the weekly fee accrual and sets the day's `weekly_fees_accrued` flag true. The accrual processes the site's members whose status is `ACTIVE` or `SUSPENDED` and whose `approved_at` is no later than the end of the club day — withdrawn, denied, and still-applied members are excluded — in order of `approved_at` ascending, ties broken by `created_at` ascending. For each member the system locates the member's `ACTIVE` scholarship award; at most one is expected, but if several are `ACTIVE`, the one with the earliest `created_at` is used. The gross charge is the member's `weekly_fee_cents`. The discount amount is the gross multiplied by the award's `discount_pct`, rounded half-up to whole cents, and this rounding is pinned before any cap applies. The actual disbursement is then the smallest of three values: the award's `weekly_cap_cents`, its `remaining_cap_cents`, and the rounded discount amount. The disbursement is added to the award's `disbursed_cents` and subtracted from its `remaining_cap_cents`, and the same amount moves from the fund's `reserved_cents` into its `disbursed_cents` — the conservation invariant of Section 3.3 therefore holds throughout. An award whose `remaining_cap_cents` reaches zero becomes `EXHAUSTED`. The member's `fee_balance_cents` rises by the gross minus the disbursement — members with no `ACTIVE` award simply owe the full gross. Each processed member's `version` increments, each disbursing award's `version` increments, and the fund's `version` increments once per close if any disbursement occurred.

Reconciling a closed day — again a `SiteDirector` action — requires the day `CLOSED` (`ERR_CLUB_DAY_NOT_CLOSED`). Reconciliation re-validates the meal tally strictly: for every meal type and every tier, the recorded count in `meal_counts` may not exceed the number of the day's attendance records in `SIGNED_OUT` whose member's `eligibility_tier` matches that tier, or the reconcile is rejected with `ERR_MEAL_COUNTS_EXCEED_ATTENDANCE`. A clean reconcile moves the day to `RECONCILED`, after which its meal counts are locked (`ERR_DAY_LOCKED`, per Section 3.5).

From reconciled days flow the monthly meal claims. A `SiteDirector` creates a claim with `site_id` and `claim_month` in year-month form; one claim per site per month (`ERR_DUPLICATE_CLAIM_MONTH`, 409). At creation the server pins a `rate_snapshot` — the site's `meal_rates_cents` plus, per day, a seasonal multiplier of 1.10 for days falling in June, July, or August and 1.0 for all other months — and computes `provisional_total_cents` over the month's club days in `CLOSED` or `RECONCILED` status. The computation works line by line: for each included day, meal type, and tier, the served count is multiplied by the snapshotted rate for that meal type and tier and by the day's snapshotted seasonal multiplier, and the line is rounded half-up to whole cents; the provisional total is the sum of those individually rounded lines. Summing first and rounding once at the end is not the rule. Days still `OPEN` are never included, and the claim starts in `DRAFT` with `final_total_cents` null.

Submitting the claim — a `SiteDirector` action — requires `DRAFT` (`ERR_CLAIM_NOT_SUBMITTABLE`) and at least one `RECONCILED` club day in the claim month (`ERR_CLAIM_NO_RECONCILED_DAYS`, 409). Submission computes `final_total_cents` by the same per-line rounding rule but over `RECONCILED` days only, still using the pinned `rate_snapshot`; the final total therefore diverges from the provisional one whenever a counted day was `CLOSED` but not yet `RECONCILED` at creation. The submitter's `X-User-ID` is recorded as `submitted_by_user_id` and the claim becomes `SUBMITTED`. Approval belongs to the external `StateAgencyReviewer`: the claim must be `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`) and the approver's `X-User-ID` must differ from `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 403). Approval records `approved_by_user_id` and moves the claim to `APPROVED`.

Funder reporting follows the same monthly rhythm. A `SiteDirector` creates a report with `site_id`, `report_month`, and `funder_type` — `UNITED_WAY` or `STATE_GRANT` — with one report per site per month (`ERR_DUPLICATE_REPORT_MONTH`). At creation, all outcome metrics are computed over the month's club days in `CLOSED` or `RECONCILED` status: `operating_days` counts those days; `member_days_attended` counts attendance records on them, with `ON_SITE`, `SIGNED_OUT`, and `MISSING_SIGNOUT` all counting as attended; `member_days_enrolled` sums, over each included day, the members whose `approved_at` is no later than that day's end and whose `withdrawn_at` is either null or later than that day's start — a suspended member still counts as enrolled. From those bases: `average_daily_attendance` is `member_days_attended` divided by `operating_days` (zero when there are no operating days); `attendance_rate_enrollment_basis` is `member_days_attended` divided by `member_days_enrolled` (zero when enrollment is zero); `attendance_rate_capacity_basis` is `member_days_attended` divided by the product of the site's `youth_capacity` and `operating_days` (zero when there are no operating days); all three are carried to four decimal places, rounded half-up. The `headline_attendance_rate` is the enrollment basis for `UNITED_WAY` funders and the capacity basis for `STATE_GRANT` funders. The report also aggregates `meals_served_total` — every `meal_counts` cell summed over the included days — and `incidents_total`, the incidents whose `incident_date` falls inside the report month regardless of adjudication status. The report starts `DRAFT`.

Submitting the report (a `SiteDirector`) requires `DRAFT` (`ERR_REPORT_NOT_SUBMITTABLE`), records `submitted_by_user_id`, and moves it to `SUBMITTED`. Acceptance belongs to the external `FunderContact`: the report must be `SUBMITTED` (`ERR_REPORT_NOT_SUBMITTED`) and the acceptor's `X-User-ID` must differ from the submitter's (`ERR_SEGREGATION_OF_DUTIES`). Acceptance moves the report to `ACCEPTED`. Claim and report listings accept an optional `status` filter, and club-day listings accept optional `status` and calendar `month` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that act on an existing resource — decisions, sweeps, transitions, payments, count upserts, and credential postings — return `200 OK`. Error responses use the codes catalogued in Section 5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sites` | Create a site | PlatformAdmin |
| GET | `/sites/{id}` | Read a site | All roles |
| POST | `/staff` | Hire staff (status `HIRED`) | PlatformAdmin |
| GET | `/staff/{id}` | Read a staff member | All roles |
| GET | `/sites/{id}/staff` | List staff of a site | All roles |
| POST | `/staff/{id}/credentials` | Post or renew a credential; recompute compliance, run lapse cascade, maybe promote to `ACTIVE` | PlatformAdmin |
| GET | `/staff/{id}/rotation-assignments` | List rotation assignments for a staff member | All roles |
| POST | `/members` | Submit a membership application (status `APPLIED`) | SiteDirector, FrontlineStaff |
| GET | `/members/{id}` | Read a member | All roles |
| GET | `/sites/{id}/members` | List members of a site | All roles |
| POST | `/members/{id}/decide` | Approve or deny an application | SiteDirector |
| POST | `/members/{id}/withdraw` | Withdraw a member; cascades to awards, rides, and rotation assignments | SiteDirector |
| POST | `/members/{id}/fee-payments` | Post a fee payment (optimistic concurrency on the member version) | SiteDirector |
| POST | `/guardians` | Add an authorized pickup guardian | SiteDirector, FrontlineStaff |
| GET | `/members/{id}/guardians` | List guardians of a member | All roles |
| POST | `/guardians/{id}/revoke` | Revoke a guardian's pickup authorization | SiteDirector, FrontlineStaff |
| POST | `/scholarship-funds` | Create a scholarship fund | PlatformAdmin |
| GET | `/scholarship-funds/{id}` | Read a fund | All roles |
| GET | `/sites/{id}/scholarship-funds` | List funds of a site | All roles |
| POST | `/scholarship-funds/{id}/close` | Close a fund; pending awards are cancelled | PlatformAdmin |
| GET | `/scholarship-funds/{id}/awards` | List awards on a fund | All roles |
| POST | `/scholarship-awards` | Create a scholarship award (status `PENDING`) | SiteDirector |
| GET | `/members/{id}/scholarship-awards` | List awards of a member | All roles |
| POST | `/scholarship-awards/{id}/activate` | Activate an award, reserving its annual cap (optimistic concurrency on the fund version) | SiteDirector |
| POST | `/scholarship-awards/{id}/revoke` | Revoke an active award, releasing its remaining reservation | SiteDirector |
| POST | `/club-days` | Open a club day; runs the opening sweeps | SiteDirector |
| GET | `/club-days/{id}` | Read a club day (posture, counters, meal counts) | All roles |
| GET | `/sites/{id}/club-days` | List club days of a site | All roles |
| POST | `/club-days/{id}/close` | Close the day: finalize attendance and assignments, run weekly fee accrual when due | SiteDirector |
| POST | `/club-days/{id}/reconcile` | Reconcile a closed day after strict meal-count validation | SiteDirector |
| POST | `/club-days/{id}/meal-counts` | Upsert meal counts for one meal type | SiteDirector, FrontlineStaff |
| POST | `/attendance-records` | Sign a member in to a club day | SiteDirector, FrontlineStaff |
| POST | `/attendance-records/{id}/sign-out` | Sign out under the authorization rule for the requested sign-out type | SiteDirector, FrontlineStaff |
| GET | `/club-days/{id}/attendance-records` | List attendance for a club day | All roles |
| GET | `/members/{id}/attendance-records` | List attendance for a member | All roles |
| POST | `/program-areas` | Create a program area | PlatformAdmin |
| GET | `/program-areas/{id}` | Read a program area | All roles |
| GET | `/sites/{id}/program-areas` | List program areas of a site | All roles |
| GET | `/program-areas/{id}/rotation-assignments` | List rotation assignments in an area | All roles |
| POST | `/rotation-assignments` | Schedule a youth or staff rotation assignment for a block | SiteDirector, FrontlineStaff |
| POST | `/rotation-assignments/{id}/check-in` | Check in an assignment; capacity then ratio for youth, compliance for staff | SiteDirector, FrontlineStaff |
| POST | `/rotation-assignments/{id}/move` | Move a checked-in assignment to another area; returns the successor | SiteDirector, FrontlineStaff |
| GET | `/club-days/{id}/rotation-assignments` | List rotation assignments for a club day | All roles |
| GET | `/members/{id}/rotation-assignments` | List rotation assignments for a member | All roles |
| POST | `/transport-routes` | Create a transport route | PlatformAdmin |
| GET | `/transport-routes/{id}` | Read a route | All roles |
| GET | `/sites/{id}/transport-routes` | List routes of a site | All roles |
| GET | `/transport-routes/{id}/ride-assignments` | List ride assignments on a route | All roles |
| POST | `/ride-assignments` | Assign a member to a route over a half-open date window | SiteDirector |
| POST | `/ride-assignments/{id}/end` | End a ride assignment early | SiteDirector |
| GET | `/members/{id}/ride-assignments` | List ride assignments of a member | All roles |
| POST | `/meal-claims` | Create a monthly reimbursement claim with pinned rates and provisional total | SiteDirector |
| GET | `/sites/{id}/meal-claims` | List meal claims of a site | All roles |
| POST | `/meal-claims/{id}/submit` | Submit a claim; computes the final total over reconciled days | SiteDirector |
| POST | `/meal-claims/{id}/approve` | Approve a submitted claim; approver must differ from submitter | StateAgencyReviewer |
| POST | `/behavior-incidents` | Report a behavior incident | SiteDirector, FrontlineStaff |
| GET | `/members/{id}/behavior-incidents` | List incidents of a member | All roles |
| POST | `/behavior-incidents/{id}/adjudicate` | Adjudicate: sustain (optionally with suspension) or dismiss | SiteDirector |
| POST | `/behavior-incidents/{id}/appeal` | Appeal an active suspension | SiteDirector, FrontlineStaff |
| POST | `/behavior-incidents/{id}/resolve-appeal` | Resolve an appeal; resolver must differ from adjudicator | SiteDirector |
| POST | `/funder-reports` | Create a monthly funder report with all outcome metrics | SiteDirector |
| GET | `/sites/{id}/funder-reports` | List funder reports of a site | All roles |
| POST | `/funder-reports/{id}/submit` | Submit a report to the funder | SiteDirector |
| POST | `/funder-reports/{id}/accept` | Accept a submitted report; acceptor must differ from submitter | FunderContact |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MEMBER_NOT_APPLIED` | 409 Conflict |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_GUARDIAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_FUND_NOT_OPEN` | 409 Conflict |
| `ERR_AWARD_NOT_PENDING` | 409 Conflict |
| `ERR_AWARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLUB_DAY_NOT_OPEN` | 409 Conflict |
| `ERR_CLUB_DAY_NOT_CLOSED` | 409 Conflict |
| `ERR_DAY_LOCKED` | 409 Conflict |
| `ERR_DAY_NOT_TODAY` | 409 Conflict |
| `ERR_DUPLICATE_CLUB_DAY` | 409 Conflict |
| `ERR_DUPLICATE_ATTENDANCE` | 409 Conflict |
| `ERR_ALREADY_SIGNED_OUT` | 409 Conflict |
| `ERR_ATTENDANCE_FINAL` | 409 Conflict |
| `ERR_PICKUP_NOT_AUTHORIZED` | 422 Unprocessable Entity |
| `ERR_WALKER_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_NO_RIDE_FOR_DATE` | 422 Unprocessable Entity |
| `ERR_FEE_ARREARS_EXCEEDED` | 402 Payment Required |
| `ERR_OVER_CAPACITY` | 409 Conflict |
| `ERR_AREA_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RATIO_VIOLATION` | 422 Unprocessable Entity |
| `ERR_STAFF_NOT_COMPLIANT` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_CONFLICT` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CHECKABLE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_MOVABLE` | 409 Conflict |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RIDE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVALID_DATE_WINDOW` | 422 Unprocessable Entity |
| `ERR_FUND_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MEAL_COUNTS_EXCEED_ATTENDANCE` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_CLAIM_NO_RECONCILED_DAYS` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM_MONTH` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INCIDENT_NOT_REPORTED` | 409 Conflict |
| `ERR_INCIDENT_NOT_APPEALABLE` | 409 Conflict |
| `ERR_APPEAL_NOT_PENDING` | 409 Conflict |
| `ERR_SUSPENSION_MANDATORY` | 422 Unprocessable Entity |
| `ERR_REPORT_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_REPORT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_MONTH` | 409 Conflict |

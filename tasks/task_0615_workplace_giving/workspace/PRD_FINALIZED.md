# Workplace Giving API — Product Requirements Document

## 1. Introduction

This document specifies the Workplace Giving & Matching-Gifts Platform, a corporate philanthropy backend in the tradition of platforms such as Benevity and YourCause. Employers run giving programs in which employees pledge donations to vetted charities, the employer matches those donations according to configurable ratios and annual caps, and volunteers earn "dollars-for-doers" grants for the hours they contribute. The platform threads each dollar from an employee's pledge through authorization, settlement, employer matching, volunteer-grant accrual, and finally a charity disbursement that withholds an administrative fee and remits the net — keeping a faithful ledger at every step.

The system is, at its heart, a ledger-reconciliation engine layered over a quota allocation problem. Matching dollars are drawn from a per-employee annual pool; volunteer grants draw from a separate per-employee pool; charity disbursements net out an administrative fee; and an employee's year-end tax statement aggregates only the donations that are genuinely deductible. Because money moves through several entities whose totals must stay mutually consistent, many operations cascade: settling a donation finalizes its matching gift and debits the employee's consumed match quota; refunding a donation reverses that match and credits the quota back; settling a disbursement batch settles every grant line, propagates settlement to the underlying matches and volunteer logs, and credits the charity's received total. The requirements below describe these workflows, the precise arithmetic behind every computed amount, the state machines that govern each entity, and the access-control and validation rules that protect the integrity of the books.

A note on duty separation: configuration (programs and campaigns) is the province of one operator role, while vetting, donation processing, volunteer approval, and disbursement belong to another; employees act only on their own donations, schedules, volunteer logs, and tax statements. This segregation of duties is woven throughout the access-control rules.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the operational capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The platform recognizes four roles: `ProgramManager`, `GivingAdmin`, `Employee`, and `system`. The `system` role is an internal automation actor that performs cascade-driven transitions (finalizing, reversing, and settling matching gifts; settling volunteer logs and grants); it is never an HTTP caller, so no externally submitted request may present `system` in `X-User-Role`. When a request's role is not permitted to perform the requested operation, the platform responds with `ERR_FORBIDDEN_FOR_ROLE`.

The `ProgramManager` role configures programs and campaigns. When `X-User-Role` is `ProgramManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `GivingAdmin` role operates charity vetting, the donation lifecycle, volunteer approval, and disbursement. When `X-User-Role` is `GivingAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. The internal `system` actor's identifier is similarly opaque and uncompared.

The `Employee` role is different: it is entity-backed. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`. Ownership checks on any resource that references an `Employee` compare the resource's `employee_id` field to `X-User-ID`. Concretely, for the employee-acted operations — cancelling a donation, and pausing, resuming, or cancelling a payroll-deduction schedule — the acting employee's `X-User-ID` must equal the target resource's `employee_id`; otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`. This owner check is distinct from, and applied after, the role-permission check.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0.

Unless an endpoint says otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Because the logical clock (§2.7) is frozen between clock-setting calls, two resources created in the same instant share an identical `created_at`; in that case the order between them is broken deterministically by true creation order — the order in which the resources were actually created, earliest first — never by their `id` or any other field. This creation-order tiebreak is an internal ordering detail and is not exposed as a field on any resource. The response envelope's `meta` object on a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every primary resource — `Program`, `Employee`, `Charity`, `Campaign`, `Donation`, `PayrollDeductionSchedule`, `MatchingGift`, `VolunteerLog`, `DisbursementBatch`, `Grant`, and `TaxStatement` — carries a server-minted `id` formatted as a UUID with no type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded when the resource was first created.

In this domain, all of the listed entities are mutable and therefore also carry `updated_at` and `version`. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 on creation and increments by one on each subsequent mutation; it underpins the optimistic-concurrency mechanism described in §2.6. Whenever a derived or computed field on a resource changes — for example when an employee's consumed-quota totals move, or a campaign's raised total moves — that counts as a mutation: it refreshes `updated_at` and increments `version` on the mutated resource.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts in this system are stored and exchanged as integer cents; there are no fractional cents and no floating-point money fields in responses. Wherever a computation multiplies an integer cent amount by a rate (a match ratio, a tier rate, a processing-fee rate, a dollars-for-doers rate, or an administrative-fee rate), the product is taken to the next-lower whole cent — that is, any fractional cent is discarded (floor). This floor is applied at each individual multiplication step as the calculations in §3 prescribe, not merely once at the end; where a calculation sums several floored sub-amounts, each sub-amount is floored first and only then summed. Configuration rate fields submitted as inputs (for example `match_ratio`, `tier_1_rate`, `tier_2_rate`, `processing_fee_low_rate`, `processing_fee_high_rate`, and `disbursement_admin_fee_rate`) are stored as supplied.

### 2.6. Optimistic Concurrency on Batch Grant Staging

Staging a grant line into a disbursement batch is guarded by optimistic concurrency control, because adding a grant legitimately advances the batch (it grows the staged set and bumps the batch's `version`). The staging request must carry `expected_batch_version`, a non-optional field whose value is the `version` of the target `DisbursementBatch` the client last observed. If `expected_batch_version` does not equal the batch's current `version` — meaning another writer has advanced the batch since the client last read it — the staging request is rejected with `ERR_STALE_BATCH_VERSION` and HTTP status 412, forcing the client to re-read the batch before staging again. No other endpoint takes a version field; only grant staging is OCC-guarded.

### 2.7. Logical Clock

All window and deadline checks in this system — campaign open/close windows, schedule active windows, volunteer activity dates, and the year extracted at settlement — are evaluated against a server-maintained logical clock rather than wall-clock time. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to wall-clock time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant; thereafter all temporal checks use that value.

### 2.8. Hierarchical Consistency and Cascades

Many operations in this system are not isolated single-row updates; settling and reversing money cascades across entities, and the platform performs those cascades automatically without requiring a separate client call on each affected resource. When a donation settles, the platform finalizes the donation's linked matching gift and adjusts the donor employee's consumed match quota; when a donation is refunded, that match is reversed and the quota is credited back. When a disbursement batch settles, every staged grant line settles, the underlying matching gifts and volunteer logs settle in turn, and the beneficiary charity's received total is credited. Each entity the cascade touches is independently mutated — its `updated_at` is refreshed and its `version` is incremented — exactly as described in §2.4. The specific cascades and the order in which they occur are detailed in §3.

### 2.9. Resource Existence and Reference Validation

When a request names a resource — whether through a path identifier such as `programId`, `employeeId`, `charityId`, `campaignId`, `donationId`, `scheduleId`, `matchId`, `logId`, `batchId`, `grantId`, or `statementId`, or through a foreign-key identifier in the request body — the platform validates those identifiers in the order they appear, left to right in the path before body references, and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`. All such references must resolve within the relevant program. List endpoints accept optional filter query parameters (such as `program_id`, `employee_id`, `campaign_id`, `charity_id`, `donation_id`, `schedule_id`, `source_id`, `source_type`, `batch_id`, `tax_year`, and `status`) that restrict the returned set to resources matching the supplied values.

### 2.10. Validation Ordering

When several checks could apply to a single request, the platform evaluates them in a fixed precedence so that the same failing request always yields the same error. The order is: first, the user-context header check (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, the role-permission check (`ERR_FORBIDDEN_FOR_ROLE`); third, for employee-acted endpoints, the resource-ownership check (`ERR_NOT_RESOURCE_OWNER`); fourth, existence of every referenced resource, validated left-to-right (`ERR_NOT_FOUND`); fifth, request-body well-formedness — required fields present, enum values valid, amounts and minutes strictly greater than zero, EIN in the format of two digits, a hyphen, then seven digits (`ERR_INVALID_REQUEST`); sixth, the optimistic-concurrency check on grant staging (`ERR_STALE_BATCH_VERSION`); and seventh, the state-precondition check for the requested transition (`ERR_INVALID_STATE`). Business-rule checks specific to an operation — charity approval status, campaign and schedule windows, eligibility, fiscal ceilings, and the like — are evaluated after these foundational checks, in the relative order described alongside each workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Programs: Configuration and the Knobs That Drive Every Calculation

A `ProgramManager` opens the platform by creating a `Program`, the top-level configuration object under which everything else lives. A program is created with a `name` and a `tax_year` (the calendar year, such as 2026, against which all caps and tax statements reset). The program also fixes the entire economic policy of the giving year through a set of optional configuration fields, each with a default applied when omitted.

The matching policy has two modes. When `tiered_matching_enabled` is false (the default), the employer matches every donated dollar at a flat `match_ratio`, which defaults to 0.5 dollars matched per dollar donated and must be between 0 and 4.0 inclusive. When `tiered_matching_enabled` is true, the flat `match_ratio` is ignored and matching instead uses two tiers: the portion of a donation at or below `tier_1_ceiling_cents` (default 50000 cents) is matched at `tier_1_rate` (default 1.0), and the portion above that ceiling is matched at `tier_2_rate` (default 0.5). Regardless of mode, an employee may receive at most `annual_match_cap_cents` (default 100000 cents) in matched dollars per `tax_year` — this is the matching quota pool described in §3.7.

Volunteer grants are governed by `dfd_rate_cents_per_hour` (the dollars-for-doers rate per volunteer hour in cents, default 1500) and `dfd_annual_cap_cents` (the per-employee per-year ceiling on volunteer grants, default 25000 cents). Donation amounts are shaped by `roundup_enabled` (default false), which, when true, rounds each donation's base up to the next whole dollar. The employer-paid processing fee is tiered around `processing_fee_tier_threshold_cents` (default 5000 cents): a donation subtotal at or above the threshold attracts `processing_fee_low_rate` (default 0.02), while a subtotal below the threshold attracts `processing_fee_high_rate` (default 0.03). Finally, `disbursement_admin_fee_rate` (default 0.025) is the fraction withheld from each grant when a disbursement batch settles, with the remainder remitted to the charity.

A program's `status` begins at `DRAFT`. The managing role moves it to `ACTIVE` by activating it, permitted only while the program is in `DRAFT`; an attempt from any other state is rejected with `ERR_INVALID_STATE`, and activation increments the program's `version`. Closing a program transitions it from `ACTIVE` to the terminal `CLOSED` state; closing is permitted only while the program is `ACTIVE`, and only when no `DisbursementBatch` under the program is in either `OPEN` or `LOCKED` status — an outstanding open or locked batch blocks the close with `ERR_OPEN_BATCH_EXISTS`. A successful close also increments the program's `version`. A program exposes a computed impact dashboard summarizing the program's totals (donated, matched, dollars-for-doers, net disbursed, distinct charities, and distinct donors).

### 3.2. Enrolling and Governing Employees

An `Employee` is enrolled under a program by either the managing or the administering role, supplying the employee's `program_id`, work `email`, `full_name`, and `annual_salary_cents`. The salary figure is not cosmetic: it caps how much of the employee's pay may be committed to payroll deductions, as §3.5 details. An email must be unique within its `program_id` among employees who are not `TERMINATED`; submitting an email already in use by a non-terminated employee in the same program is rejected with `ERR_DUPLICATE_EMPLOYEE_EMAIL`. On enrollment, an employee starts `ACTIVE` with both consumed-quota counters — `match_consumed_ytd_cents` and `dfd_consumed_ytd_cents` — at zero. Reading an employee returns these consumed-YTD figures so callers can see how much of each annual cap remains.

The `match_consumed_ytd_cents` counter is the running sum of `matched_amount_cents` across the employee's matching gifts that are in `FINALIZED` or `SETTLED` status for the program's `tax_year`; it represents the consumed portion of `annual_match_cap_cents`. The `dfd_consumed_ytd_cents` counter is the running sum of `grant_amount_cents` across the employee's volunteer logs in `APPROVED` or `SETTLED` status for the program's `tax_year`. Both counters move as a side effect of the workflows in §3.6 and §3.7 rather than through direct edits.

An employee's lifecycle is administered by the giving-administration role (and, for the enroll and govern operations, shared with the managing role). An `ACTIVE` employee may be suspended, moving them to `SUSPENDED`; a `SUSPENDED` employee may be reinstated back to `ACTIVE`. From either `ACTIVE` or `SUSPENDED`, an employee may be terminated, moving them to the terminal `TERMINATED` state. Each of these transitions is permitted only from the states just named; any other origin yields `ERR_INVALID_STATE`. Termination frees the employee's email for re-enrollment, because the uniqueness rule ignores terminated employees. An employee's active status matters downstream: a donation cannot be authorized, and a volunteer log cannot be approved, unless the donor or volunteer is `ACTIVE`, as noted in §3.6.

### 3.3. Charity Vetting: A Bounded Revision Loop

A `Charity` is submitted for vetting by the administering role, with a `program_id`, a `legal_name`, an `ein` (the US Employer Identification Number, nine digits in the format of two digits, a hyphen, then seven digits), and an optional `claimed_501c3` flag (defaulting to true, the self-declared tax-exempt status pending review). The EIN must be unique within the program among charities that are not `REJECTED`; a duplicate EIN against a non-rejected charity is rejected with `ERR_DUPLICATE_EIN`. A new charity starts in `SUBMITTED` with its `review_rounds` counter at zero and its computed `total_received_cents` at zero.

Vetting proceeds through a cyclic state machine. Starting a review moves a charity from `SUBMITTED` to `UNDER_REVIEW` and increments `review_rounds` by one. From `UNDER_REVIEW`, a reviewer may request more information, moving the charity to `NEEDS_INFO`. A charity in `NEEDS_INFO` can re-enter review — the revision loop — moving back to `UNDER_REVIEW` and again incrementing `review_rounds` by one, but this re-entry is permitted only while `review_rounds` is below 3; once `review_rounds` has reached 3, a further attempt to restart review from `NEEDS_INFO` is rejected with `ERR_MAX_REVIEW_ROUNDS`. Each of these transitions requires the charity to be in the precise originating state named, failing otherwise with `ERR_INVALID_STATE`.

From `UNDER_REVIEW`, a charity may be approved or rejected. Approval moves it to `APPROVED` but only when the charity is genuinely eligible: `claimed_501c3` must be true and the `ein` must match the two-digit, hyphen, seven-digit format; if either condition fails, approval is rejected with `ERR_CHARITY_NOT_ELIGIBLE`. Where both the eligibility check and the review-rounds bound could be implicated on a restart-then-approve path, the eligibility failure (`ERR_CHARITY_NOT_ELIGIBLE`) takes precedence over the review-rounds failure (`ERR_MAX_REVIEW_ROUNDS`). Rejection moves the charity to the terminal `REJECTED` state and may be performed from either `UNDER_REVIEW` or `NEEDS_INFO`. An `APPROVED` charity may later be suspended, moving it to `SUSPENDED`, and a `SUSPENDED` charity may be reinstated back to `APPROVED`; both require the respective originating state. Only an `APPROVED` charity may anchor a launched campaign, receive volunteer-log approvals, or be the beneficiary of a settling disbursement batch — operations attempted against a charity that is not `APPROVED` are rejected with `ERR_CHARITY_NOT_APPROVED`.

### 3.4. Campaigns: The Fundraising Window

A `Campaign` is created by the managing role under a `program_id`, naming the beneficiary `charity_id`, a campaign `name`, a `goal_cents` fundraising goal (which must be strictly greater than zero), and an inclusive open instant `window_start` together with an exclusive close instant `window_end`. A new campaign starts in `DRAFT` with its computed `raised_cents` at zero.

Launching a campaign moves it from `DRAFT` to `LIVE`, but only when three conditions hold: the campaign is in `DRAFT` (else `ERR_INVALID_STATE`), the referenced charity is `APPROVED` (else `ERR_CHARITY_NOT_APPROVED`), and the owning program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`). A `LIVE` campaign may be paused to `PAUSED`; a `PAUSED` campaign may be resumed back to `LIVE`, and resuming again requires the beneficiary charity to be `APPROVED` at that moment (else `ERR_CHARITY_NOT_APPROVED`). From either `LIVE` or `PAUSED`, a campaign may be ended, moving it to the terminal `ENDED` state. Each transition requires the originating state named; otherwise `ERR_INVALID_STATE` is returned. A campaign's `raised_cents` accumulates as donations settle (and unwinds on refund), as described in §3.6. The campaign window is consequential at pledge time: donations may be accepted only while the logical clock falls within the half-open interval from `window_start` (inclusive) up to `window_end` (exclusive), and the campaign must be `LIVE` for a donation to be settled, both detailed in §3.6.

### 3.5. Donations and Recurring Payroll Schedules

A `Donation` is pledged either by the donating employee or by the administering role on the employee's behalf. The pledge carries the `program_id`, the donor's `employee_id`, the target `campaign_id`, a `donation_type` of either `ONE_TIME` or `RECURRING`, a `funding_method` of either `PAYROLL_DEDUCTION` or `CREDIT`, the `base_amount_cents` (the employee-entered amount before any round-up, which must be strictly greater than zero), an optional `tax_deductible` flag (default true), and an optional `request_match` flag. At pledge time the target campaign must be `LIVE`, and the logical clock must fall within the campaign's half-open window from `window_start` up to `window_end`; a clock outside that window is rejected with `ERR_CAMPAIGN_WINDOW_CLOSED`. A new donation begins in `PLEDGED` with its computed money fields — `roundup_increment_cents`, `subtotal_cents`, `processing_fee_cents`, and `total_charged_cents` — at zero until authorization computes them, and with `settled_at` and `schedule_id` unset.

If `request_match` is true at pledge time, the platform immediately creates a linked `MatchingGift` in `REQUESTED` status referencing this donation through `donation_id`, copies the donor onto the gift's `employee_id`, and computes a provisional `estimated_match_cents` for it using the estimated variant of the matching calculation described in §3.7. A donation's `tax_deductible` flag determines whether its base amount later counts toward the employee's year-end tax statement.

Authorizing a pledged donation is an administrative action permitted only when the donation is `PLEDGED` (else `ERR_INVALID_STATE`) and the donor employee is `ACTIVE` (else `ERR_EMPLOYEE_NOT_ACTIVE`). Authorization moves the donation to `AUTHORIZED` and computes its money breakdown in a pinned order, because the processing fee depends on the subtotal tier and the total depends on the fee. First, the round-up increment: if the program has `roundup_enabled` set, the increment is the number of cents needed to reach the next whole dollar — that is, if the base amount is already an exact multiple of one dollar (100 cents) the increment is 0, otherwise the increment is 100 minus the remainder of the base amount divided by 100; if round-up is not enabled the increment is 0. Second, the subtotal is the base amount plus that increment. Third, the processing-fee rate is selected from the subtotal tier: if the subtotal is at or above the program's `processing_fee_tier_threshold_cents` the low rate applies, otherwise the high rate applies, and the processing fee is the subtotal multiplied by the chosen rate, floored to whole cents. Fourth, the total charged is the subtotal plus the processing fee. The fee is always derived from the subtotal, never from the bare base amount.

Settling an authorized donation is an administrative action permitted only when the donation is `AUTHORIZED` (else `ERR_INVALID_STATE`) and its campaign is `LIVE` (else `ERR_CAMPAIGN_NOT_LIVE`). Settlement moves the donation to `SETTLED`, stamps `settled_at` with the current clock value, and increases the campaign's `raised_cents` by the donation's `base_amount_cents`. If a `MatchingGift` linked to this donation is still in `REQUESTED`, settlement finalizes it as described in §3.7. A pledged donation may instead be cancelled by the donor (owner-only), moving it from `PLEDGED` to the terminal `CANCELLED` state; cancellation requires the `PLEDGED` state, else `ERR_INVALID_STATE`.

A settled donation may be refunded by the administering role, moving it from `SETTLED` to the terminal `REFUNDED` state, but only when no `Grant` references the donation in a `STAGED` or `SETTLED` status — a donation whose grant has been staged or settled cannot be refunded and is rejected with `ERR_DONATION_DISBURSED`. A refund decreases the campaign's `raised_cents` by the donation's `base_amount_cents`, and if the donation's matching gift is in `FINALIZED`, the refund reverses that gift as described in §3.7.

Recurring payroll giving is organized by a `PayrollDeductionSchedule`, created by the employee or the administering role with the `program_id`, the owner's `employee_id`, the funded `campaign_id`, the `per_period_amount_cents` deducted each period (which must be strictly greater than zero), an inclusive `window_start`, and an exclusive `window_end`. A new schedule starts `ACTIVE` with its `occurrences_generated` counter at zero. Two constraints guard schedule creation. First, the new schedule's half-open active window from `window_start` up to `window_end` must not overlap the window of any existing schedule for the same employee and campaign that is in `ACTIVE` or `PAUSED` status; an overlapping window (evaluated with half-open semantics) is rejected with `ERR_SCHEDULE_OVERLAP`. Second, the payroll-deduction ceiling must hold: the employee's monthly salary is their `annual_salary_cents` divided by twelve and floored, the ceiling is that monthly figure multiplied by twenty percent and floored, and the sum of `per_period_amount_cents` over the employee's existing schedules in `ACTIVE` or `PAUSED` status plus the new schedule's per-period amount must not exceed that ceiling; exceeding it is rejected with `ERR_DEDUCTION_LIMIT_EXCEEDED`. Cancelled schedules are excluded from both the overlap and the ceiling computations.

The owning employee may pause an `ACTIVE` schedule to `PAUSED`, resume a `PAUSED` schedule back to `ACTIVE`, or cancel a schedule (from either `ACTIVE` or `PAUSED`) to the terminal `CANCELLED` state, each requiring the corresponding originating state and each subject to the owner check of §2.1. Running a cycle on a schedule is an administrative action that keeps the schedule in `ACTIVE` (a self-loop) while generating one occurrence: it requires the schedule to be `ACTIVE` (else `ERR_INVALID_STATE`), the logical clock to fall within the schedule's half-open window from `window_start` up to `window_end` (else `ERR_SCHEDULE_WINDOW_CLOSED`), and the funded campaign to be `LIVE` (else `ERR_CAMPAIGN_NOT_LIVE`). A successful run-cycle creates one new `Donation` in `PLEDGED` status for that employee and campaign with `donation_type` of `RECURRING`, `funding_method` of `PAYROLL_DEDUCTION`, `base_amount_cents` equal to the schedule's `per_period_amount_cents`, and `schedule_id` set to this schedule, then increments the schedule's `occurrences_generated` by one.

### 3.6. Matching Gifts: Estimated at Request, Finalized at Settle

A `MatchingGift` is the employer-funded counterpart to an employee donation, linked one-to-one to its donation through `donation_id` and carrying the donor's `employee_id` (copied from the donation), a `raw_match_cents` figure (the match before any annual-cap clamp), an `estimated_match_cents` figure (the provisional match shown at request time), and a `matched_amount_cents` figure (the final match fixed at finalization). A matching gift begins in `REQUESTED`.

The raw match is computed the same way at both estimate and finalize time, and depends on the program's matching mode. When tiered matching is enabled, the donation's `base_amount_cents` is split at `tier_1_ceiling_cents`: the first portion is the smaller of the base amount and the ceiling, the second portion is the base amount minus the ceiling but not below zero, the first portion is multiplied by `tier_1_rate` and floored, the second portion is multiplied by `tier_2_rate` and floored, and the raw match is the sum of those two floored products. When tiered matching is disabled, the raw match is simply the donation's `base_amount_cents` multiplied by the program's `match_ratio`, floored to whole cents. The raw match is then clamped to the annual cap: the employee's remaining cap is `annual_match_cap_cents` minus their `match_consumed_ytd_cents`, and the matched amount is the raw match but never more than the remaining cap and never below zero. When the remaining cap is zero or negative, the matched amount is zero.

The distinction between the two variants is the consumption figure each uses. The `estimated_match_cents` produced at request time uses only committed consumption — the employee's matched amounts already in `FINALIZED` or `SETTLED` at that moment — and deliberately ignores any other matches still in `REQUESTED` and in flight. The `matched_amount_cents` produced when the donation settles uses live consumption at settle time, which includes any matches that finalized between this gift's request and this settle; consequently the final matched amount may be smaller than the earlier estimate. Both figures derive their consumption from the same input: the sum of `matched_amount_cents` over the employee's matching gifts in `FINALIZED` or `SETTLED` for the program's `tax_year`.

Finalization is the side effect of the linked donation moving from `AUTHORIZED` to `SETTLED`. At that point the platform recomputes `matched_amount_cents` against live consumption. If the clamped result is greater than zero, the matching gift transitions from `REQUESTED` to `FINALIZED` and the employee's `match_consumed_ytd_cents` is increased by that matched amount. If the clamped result is exactly zero — because the annual cap is already fully consumed — the matching gift transitions from `REQUESTED` to `CAPPED` with its `matched_amount_cents` set to zero and no consumption debit; `CAPPED` is terminal for a fully consumed cap. A `FINALIZED` matching gift later transitions to `SETTLED` as a consequence of a grant whose source is the match settling within its disbursement batch. If the linked donation is refunded while its matching gift is still `FINALIZED` (not yet `SETTLED`), the platform reverses the gift: it transitions from `FINALIZED` to the terminal `REVERSED` state and credits the employee's `match_consumed_ytd_cents` back by the matched amount, undoing the earlier debit.

### 3.7. Volunteer Logs and Dollars-for-Doers Grants

A `VolunteerLog` records volunteer time for the dollars-for-doers benefit. It is created by the employee or the administering role with the `program_id`, the volunteer's `employee_id`, the `charity_id` volunteered for, the `minutes` logged (which must be strictly greater than zero), and the `activity_date` on which the volunteering occurred, which must fall within the program's `tax_year`. A new log starts in `LOGGED` with its computed `raw_grant_cents` and `grant_amount_cents` at zero.

Approving a volunteer log is an administrative action permitted only when the log is `LOGGED` (else `ERR_INVALID_STATE`), the referenced charity is `APPROVED` (else `ERR_CHARITY_NOT_APPROVED`), and the volunteer employee is `ACTIVE` (else `ERR_EMPLOYEE_NOT_ACTIVE`). Approval moves the log to `APPROVED` and computes its grant. The raw grant is the logged minutes divided by sixty (converting minutes to hours) multiplied by the program's `dfd_rate_cents_per_hour`, with that whole product floored to whole cents. The grant is then clamped to the volunteer cap: the employee's remaining cap is `dfd_annual_cap_cents` minus their `dfd_consumed_ytd_cents`, and the final `grant_amount_cents` is the raw grant but never more than the remaining cap and never below zero. The consumption figure used here is the sum of `grant_amount_cents` over the employee's volunteer logs already in `APPROVED` or `SETTLED` for the program's `tax_year`. On approval the employee's `dfd_consumed_ytd_cents` is increased by the computed grant amount.

A logged volunteer entry may instead be rejected, moving it from `LOGGED` to the terminal `REJECTED` state. An approved log later transitions to `SETTLED` as a consequence of a grant whose source is this log settling within its disbursement batch. Before a grant has been staged or settled against it, an `APPROVED` log may be reversed by the administering role, moving it to the terminal `REVERSED` state and crediting the employee's `dfd_consumed_ytd_cents` back by the grant amount; if any `Grant` references the log in `STAGED` or `SETTLED`, the reversal is rejected with `ERR_LOG_DISBURSED`.

### 3.8. Disbursement: Batches, Grants, and the Fee Waterfall

Money reaches a charity through a `DisbursementBatch`, opened by the administering role for a single beneficiary with a `program_id`, the `charity_id` that will receive every grant in the batch, and a coverage period spanning an inclusive `period_start` through an inclusive `period_end`. A new batch starts `OPEN` with its `version` at 1 and its computed totals — `gross_total_cents`, `admin_fee_cents`, and `net_total_cents` — at zero. The coverage period uses closed semantics: a new batch's period from `period_start` through `period_end` must not overlap any existing batch for the same charity that is in `OPEN`, `LOCKED`, or `SETTLED` status, and because the interval is closed, even touching endpoints count as a conflict; an overlap is rejected with `ERR_BATCH_PERIOD_OVERLAP`.

Into an open batch, the administering role stages `Grant` lines. Each grant names a `source_type` of `DONATION`, `MATCH`, or `DFD` and a polymorphic `source_id` — a donation's id when the source type is `DONATION`, a matching gift's id when `MATCH`, and a volunteer log's id when `DFD` — together with the `expected_batch_version` required by the optimistic-concurrency rule of §2.6. A staged grant copies the batch's `charity_id` onto itself (all grants in a batch share one charity), starts in `STAGED`, and takes its `gross_amount_cents` from the source: a donation contributes its `base_amount_cents`, a matching gift contributes its `matched_amount_cents`, and a volunteer log contributes its `grant_amount_cents`. The line's `admin_fee_cents` and `net_amount_cents` remain zero until the batch settles. Several conditions guard staging, evaluated in this order: the source must be in a disbursable state — a donation `SETTLED`, a matching gift `FINALIZED`, or a volunteer log `APPROVED` — failing with `ERR_SOURCE_NOT_DISBURSABLE`; the source must not already be staged or settled in another grant, failing with `ERR_SOURCE_ALREADY_GRANTED`; and the source's beneficiary charity must match the batch's charity, failing with `ERR_GRANT_CHARITY_MISMATCH`. Staging a grant increments the batch's `version` by one (which is what makes the OCC guard meaningful).

Locking a batch freezes its staged set, moving it from `OPEN` to `LOCKED`, permitted only when the batch is `OPEN` (else `ERR_INVALID_STATE`) and the batch holds at least one grant in `STAGED` (else `ERR_EMPTY_BATCH`); locking increments the batch's `version`. An open batch may instead be voided, moving it from `OPEN` to the terminal `VOIDED` state, which transitions every `STAGED` grant in it to `VOIDED` (excluding those grants from any future settlement) and increments the batch's `version`.

Settling a locked batch is the climactic cascade, moving it from `LOCKED` to the terminal `SETTLED` state, permitted only when the batch is `LOCKED` (else `ERR_INVALID_STATE`) and the beneficiary charity is `APPROVED` (else `ERR_CHARITY_NOT_APPROVED`). The fee waterfall runs in a pinned order on the batch's `STAGED` grant lines (voided lines are excluded), taken in ascending `created_at` order; because the logical clock (§2.7) is frozen between clock-setting calls, grant lines staged in the same instant share an identical `created_at`, and ties are broken deterministically by true staging order — the order in which the lines were actually staged, earliest first — never by their `id`. This single ordering of the staged lines governs both steps below that refer to ascending `created_at` order. First, the gross total is the sum of every staged line's `gross_amount_cents`. Second, the single batch-level administrative fee is the gross total multiplied by the program's `disbursement_admin_fee_rate`, floored to whole cents; the net total is the gross total minus that fee. That single fee is then allocated across the lines rather than recomputed per line: each line's `admin_fee_cents` is its own `gross_amount_cents` multiplied by the admin-fee rate and floored, the allocated sum of those per-line fees is compared to the batch-level fee, and any leftover cents (the batch-level fee minus the allocated sum, which is never negative) are distributed one cent at a time to the lines in ascending `created_at` order. Each line's `net_amount_cents` is then its `gross_amount_cents` minus its final `admin_fee_cents`. The per-line numbers are an allocation of the single sum-level fee, never an independent source of it.

Settlement then propagates: every `STAGED` grant moves to `SETTLED`; for each grant whose source is a match, the underlying matching gift moves from `FINALIZED` to `SETTLED`; for each grant whose source is a volunteer log, the underlying log moves from `APPROVED` to `SETTLED`; the beneficiary charity's `total_received_cents` is increased by the batch's `net_total_cents` (each settled grant contributing its `net_amount_cents`); and the batch's `version` is incremented. Grants are never settled individually — only as a consequence of their batch settling — and a charity's `total_received_cents` is precisely the sum of `net_amount_cents` over its grants in `SETTLED`.

### 3.9. Year-End Tax Statements and the Impact Dashboard

When the year closes, the administering role or the employee generates the employee's `TaxStatement`. The statement records the `program_id`, the subject's `employee_id`, the `tax_year` copied from the program at generation time, and three computed figures, and it begins in `GENERATED` (with `FINAL` as its other status). The deductible donations total, `deductible_donations_cents`, is the sum of `base_amount_cents` over the employee's donations that are `SETTLED`, have `tax_deductible` set to true, and whose `settled_at` year equals the program's `tax_year`; only the base amount is deductible, so round-up increments and processing fees are excluded, and donations in `PLEDGED`, `AUTHORIZED`, `REFUNDED`, or `CANCELLED` are excluded entirely. The `line_count` is the number of donation lines included in that sum. The informational `matched_total_cents` is the sum of `matched_amount_cents` over the employee's matching gifts that are `SETTLED` and whose linked donation's `settled_at` year equals the program's `tax_year`; this employer-funded figure is reported for transparency but is not employee-deductible.

The program-level impact dashboard, available to the managing and administering roles, summarizes the giving year: the total donated, the total matched, the total dollars-for-doers granted, the total net disbursed, the count of charities, and the count of donors. It is a read-only computed view drawn from the same settled records that feed the per-employee figures above.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (such as a program, employee, charity, campaign, donation, schedule, volunteer log, disbursement batch, staged grant, or tax statement) return a `201 Created` status code; the recurring run-cycle, which creates a new donation occurrence, likewise returns `201 Created`. Operations that modify an existing resource — state transitions and the like — return a `200 OK` status code, as does the clock-setting capability.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | GivingAdmin, ProgramManager |
| POST | `/programs` | Create a giving program | ProgramManager |
| GET | `/programs/{programId}` | Get a program | GivingAdmin, ProgramManager, Employee |
| POST | `/programs/{programId}/activate` | Activate a program | ProgramManager |
| POST | `/programs/{programId}/close` | Close a program | ProgramManager |
| GET | `/programs/{programId}/impact-report` | Computed impact dashboard for the program | GivingAdmin, ProgramManager |
| POST | `/employees` | Enroll an employee | ProgramManager, GivingAdmin |
| GET | `/employees/{employeeId}` | Get an employee (includes consumed YTD caps) | GivingAdmin, ProgramManager, Employee |
| GET | `/employees` | List employees | GivingAdmin, ProgramManager |
| POST | `/employees/{employeeId}/suspend` | Suspend an employee | GivingAdmin, ProgramManager |
| POST | `/employees/{employeeId}/reinstate` | Reinstate a suspended employee | GivingAdmin, ProgramManager |
| POST | `/employees/{employeeId}/terminate` | Terminate an employee | GivingAdmin, ProgramManager |
| POST | `/employees/{employeeId}/tax-statement` | Generate the employee's year-end tax statement | GivingAdmin, Employee |
| GET | `/tax-statements/{statementId}` | Get a generated tax statement | GivingAdmin, ProgramManager, Employee |
| GET | `/tax-statements` | List tax statements | GivingAdmin, ProgramManager, Employee |
| POST | `/charities` | Submit a charity for vetting | GivingAdmin |
| GET | `/charities/{charityId}` | Get a charity | GivingAdmin, ProgramManager, Employee |
| GET | `/charities` | List charities | GivingAdmin, ProgramManager |
| POST | `/charities/{charityId}/start-review` | Move a charity into UNDER_REVIEW | GivingAdmin |
| POST | `/charities/{charityId}/request-info` | Request more info | GivingAdmin |
| POST | `/charities/{charityId}/approve` | Approve a vetted charity | GivingAdmin |
| POST | `/charities/{charityId}/reject` | Reject a charity | GivingAdmin |
| POST | `/charities/{charityId}/suspend` | Suspend an approved charity | GivingAdmin |
| POST | `/charities/{charityId}/reinstate` | Reinstate a suspended charity | GivingAdmin |
| POST | `/campaigns` | Create a campaign | ProgramManager |
| GET | `/campaigns/{campaignId}` | Get a campaign | GivingAdmin, ProgramManager, Employee |
| GET | `/campaigns` | List campaigns | GivingAdmin, ProgramManager, Employee |
| POST | `/campaigns/{campaignId}/launch` | Launch a campaign | ProgramManager |
| POST | `/campaigns/{campaignId}/pause` | Pause a live campaign | ProgramManager |
| POST | `/campaigns/{campaignId}/resume` | Resume a paused campaign | ProgramManager |
| POST | `/campaigns/{campaignId}/end` | End a campaign | ProgramManager |
| POST | `/donations` | Pledge a one-time or recurring donation | Employee, GivingAdmin |
| GET | `/donations/{donationId}` | Get a donation (full computed breakdown) | GivingAdmin, ProgramManager, Employee |
| GET | `/donations` | List donations | GivingAdmin, ProgramManager, Employee |
| POST | `/donations/{donationId}/authorize` | Authorize a pledged donation | GivingAdmin |
| POST | `/donations/{donationId}/settle` | Settle an authorized donation | GivingAdmin |
| POST | `/donations/{donationId}/cancel` | Cancel a pledged donation (donor only) | Employee |
| POST | `/donations/{donationId}/refund` | Refund a settled donation | GivingAdmin |
| POST | `/payroll-schedules` | Create a recurring payroll-deduction schedule | Employee, GivingAdmin |
| GET | `/payroll-schedules/{scheduleId}` | Get a payroll-deduction schedule | GivingAdmin, ProgramManager, Employee |
| GET | `/payroll-schedules` | List schedules | GivingAdmin, ProgramManager, Employee |
| POST | `/payroll-schedules/{scheduleId}/pause` | Pause a schedule (owner only) | Employee |
| POST | `/payroll-schedules/{scheduleId}/resume` | Resume a schedule (owner only) | Employee |
| POST | `/payroll-schedules/{scheduleId}/cancel` | Cancel a schedule (owner only) | Employee |
| POST | `/payroll-schedules/{scheduleId}/run-cycle` | Generate one recurring donation occurrence | GivingAdmin |
| GET | `/matching-gifts/{matchId}` | Get a matching gift (estimated vs final) | GivingAdmin, ProgramManager, Employee |
| GET | `/matching-gifts` | List matching gifts | GivingAdmin, ProgramManager, Employee |
| POST | `/volunteer-logs` | Log volunteer time | Employee, GivingAdmin |
| GET | `/volunteer-logs/{logId}` | Get a volunteer log (grant breakdown) | GivingAdmin, ProgramManager, Employee |
| GET | `/volunteer-logs` | List volunteer logs | GivingAdmin, ProgramManager, Employee |
| POST | `/volunteer-logs/{logId}/approve` | Approve a volunteer log | GivingAdmin |
| POST | `/volunteer-logs/{logId}/reject` | Reject a volunteer log | GivingAdmin |
| POST | `/volunteer-logs/{logId}/reverse` | Reverse an approved log | GivingAdmin |
| POST | `/disbursement-batches` | Open a disbursement batch | GivingAdmin |
| GET | `/disbursement-batches/{batchId}` | Get a disbursement batch (totals + version) | GivingAdmin, ProgramManager |
| GET | `/disbursement-batches` | List batches | GivingAdmin, ProgramManager |
| POST | `/disbursement-batches/{batchId}/grants` | Stage a grant into the batch (OCC-guarded) | GivingAdmin |
| GET | `/disbursement-batches/{batchId}/grants` | List grants in a batch | GivingAdmin, ProgramManager |
| GET | `/grants/{grantId}` | Get a grant | GivingAdmin, ProgramManager |
| GET | `/grants` | List grants | GivingAdmin, ProgramManager |
| POST | `/disbursement-batches/{batchId}/lock` | Lock a batch | GivingAdmin |
| POST | `/disbursement-batches/{batchId}/settle` | Settle a locked batch | GivingAdmin |
| POST | `/disbursement-batches/{batchId}/void` | Void an open batch | GivingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_BATCH_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_BATCH_EXISTS` | 409 Conflict |
| `ERR_CHARITY_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_MAX_REVIEW_ROUNDS` | 409 Conflict |
| `ERR_CHARITY_NOT_APPROVED` | 409 Conflict |
| `ERR_DUPLICATE_EIN` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_LIVE` | 409 Conflict |
| `ERR_CAMPAIGN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_EMPLOYEE_EMAIL` | 409 Conflict |
| `ERR_SCHEDULE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_DEDUCTION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DONATION_DISBURSED` | 409 Conflict |
| `ERR_LOG_DISBURSED` | 409 Conflict |
| `ERR_EMPTY_BATCH` | 409 Conflict |
| `ERR_BATCH_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SOURCE_NOT_DISBURSABLE` | 409 Conflict |
| `ERR_SOURCE_ALREADY_GRANTED` | 409 Conflict |
| `ERR_GRANT_CHARITY_MISMATCH` | 409 Conflict |

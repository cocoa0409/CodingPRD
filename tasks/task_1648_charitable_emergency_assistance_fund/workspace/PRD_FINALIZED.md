# Charitable Emergency Assistance API — Product Requirements Document

## 1. Introduction

A community assistance ministry operates an emergency fund for households in acute housing crisis — an eviction notice taped to the door, a utility shutoff warning on the kitchen table. The ministry never hands cash to applicants. Every dollar granted is paid directly to the landlord or utility company on the household's behalf, and only after the vendor has confirmed what is actually owed. Standing behind that core gesture are the disciplines any charitable fund must answer for: documented eligibility, per-household and per-category caps, a waitlist when money runs short, and faithful reporting back to the donors and grantors who supplied the money.

Funding arrives from many directions at once. Unrestricted donor gifts, restricted grants earmarked for a single assistance category, and government allocations each carry their own spending periods, per-household draw limits, and category restrictions, and awards must be spread across these pools without ever overcommitting one. Because applicant families frequently seek help from several agencies at the same time, every approval is gated on a duplication-of-benefits check with outside organizations. And because the same staff member could otherwise open a case, verify it, and approve it alone, the program enforces strict segregation of duties between intake, verification, and decision-making.

This document specifies the REST API that administers the fund, mounted under `/assistance`. It covers household registration, application intake and documentation, vendor verification, duplication screening, award decisions and their allocation across funding sources, direct-to-vendor disbursement, waitlist replenishment, case follow-up, and donor/grant reporting. Business rules are stated in the language of the program; the wire contract is stated precisely.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). An authenticated operator whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `Caseworker` — ministry caseworker: intake, documentation, verification, duplication checks, case notes, and follow-up outcomes.
- `ProgramManager` — program manager: policy and funding-source administration, award decisions, adjustments, overrides, replenishment runs, and clock control.
- `FinanceOfficer` — finance officer: the direct-to-vendor payment lifecycle (issue, clear, fail, reissue, void).
- `Auditor` — read-only auditor: reviews records and pulls donor/grant reports; cannot mutate anything.

For each of the four roles — `Caseworker`, `ProgramManager`, `FinanceOfficer`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for authorship — as `intake_caseworker_id` on an application, `uploaded_by` on a document, `verifier_id` on a verification, `recorded_by` on a duplication check, `author_id` on a case note, `issued_by` on a payment, or `run_by` on a replenishment run — and segregation-of-duties checks compare those recorded identifiers against the acting `X-User-ID`, but no role's `X-User-ID` is ever compared to any entity's `id`.

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

List endpoints accept the `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses order their entries by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Program's Logical Clock

All time inside the service reads a logical clock, never the host's wall clock. At startup the clock reads exactly 2026-08-01T00:00:00Z. A `ProgramManager` may advance it through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`; the clock never falls back to wall-clock time on its own. Every recorded timestamp — `submitted_at`, `waitlisted_at`, `denied_at`, `closed_at`, `completed_at`, `cleared_at`, and the default for `occurred_at` — is stamped from this clock, and every time-window rule in the program (appeal windows, funding periods, benefit years) evaluates against it.

An award's benefit year is the four-digit UTC calendar year of the logical clock at the moment of approval, stored as the integer `benefit_year`. All per-year caps group awards by this stored integer; the grouping is never recomputed from other dates.

### 2.5. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at`, maintained in the same format and refreshed on every mutation, and a `version` integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of that resource. The full set of `id`, `created_at`, `updated_at`, and `version` applies to Household, EligibilityPolicy, Vendor, AssistanceApplication, VendorVerification, DuplicationCheck, AssistanceAward, FundingAllocation, FundingSource, and Payment.

Three record types are append-only ledgers and carry only `id` and `created_at`: ApplicationDocument, CaseNote, and ReplenishmentRun. On these three, both `updated_at` and `version` are absent.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents — in requests, in storage, and in responses alike. Benefit arithmetic (caps, award amounts, allocations, source balances) is exact integer arithmetic with no rounding, with one deliberate exception described in the award-adjustment workflow, where per-allocation releases are rounded down to a whole cent and the rounding remainder is absorbed by the last-ranked allocation. The utilization percentages produced by funding-source reporting are expressed with one decimal place and rounded half up. Time-window comparisons are made at second granularity.

### 2.7. Optimistic Concurrency Control on Guarded Writes

Three writes are guarded by optimistic concurrency control, each keyed to its parent entity:

- Creating a vendor verification (`POST /assistance/applications/{id}/verifications`) requires the request body to carry `expected_application_version`, holding the client-last-observed `version` of the application.
- Opening a duplication check (`POST /assistance/applications/{id}/duplication-checks`) likewise requires `expected_application_version`.
- Adjusting an award (`POST /assistance/awards/{id}/adjust`) requires `expected_award_version`, holding the client-last-observed `version` of the award.

When the supplied value does not match the parent entity's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). The first two guards exist because creating a verification or a check legitimately supersedes any existing `PENDING` sibling, so a client holding a stale application version would unknowingly supersede a record it never saw. The third guard exists because an adjustment prorates fund releases against an `awarded_amount_cents` the client may never have observed. Endpoints not named in this section take no version field.

### 2.8. Segregation of Duties

The person who opens a case may not verify it, approve it, or deny it. Concretely: the `Caseworker` who opens a vendor verification must differ from the application's `intake_caseworker_id`; the `Caseworker` who completes a verification must likewise differ from `intake_caseworker_id`; the `ProgramManager` who approves must differ both from `intake_caseworker_id` and from the `verifier_id` of the application's latest `PASSED` verification; and the `ProgramManager` who denies must differ from `intake_caseworker_id`. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

### 2.9. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic:

1. Authentication first — the headers are present and the role is recognized, else `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role is listed for the endpoint, else `ERR_FORBIDDEN`.
3. Request well-formedness — required fields present, enum values valid, integer-cent fields positive where declared, `service_month` matching the YYYY-MM shape, and outcome-conditional fields supplied (for example `confirmed_amount_cents` when a verification completes with outcome `PASSED`), else `ERR_INVALID_REQUEST`. Where an endpoint declares request-body fields, the body may carry only those declared fields; any other field the client sends — including server-minted or server-computed fields such as `id`, `reserved_cents`, `committed_cents`, or `available_cents` — is rejected with `ERR_INVALID_REQUEST`.
4. Existence — path identifiers and body foreign keys reference existing resources, validated left to right, else `ERR_NOT_FOUND`.
5. Stale version — on the OCC-guarded writes named in §2.7, the expected-version field matches the parent entity's current `version`, else `ERR_STALE_VERSION`.
6. State legality — the target resource is in a state from which the requested transition exists. This family surfaces as `ERR_INVALID_APPLICATION_STATE` on the application action endpoints (submit, approve, deny, waitlist, appeal, withdraw, close); as `ERR_INVALID_VERIFICATION_STATE` on verification completion; as `ERR_INVALID_DUPLICATION_CHECK_STATE` on resolve or override; as `ERR_INVALID_AWARD_STATE` on award adjust or void; as `ERR_INVALID_PAYMENT_STATE` on payment clear, fail, reissue, or void; as `ERR_INVALID_SOURCE_STATE` on deposits into or closure of a `CLOSED` source; as `ERR_INVALID_POLICY_STATE` on activating a non-`DRAFT` policy; as `ERR_INVALID_STATE` on vendor suspend or reactivate; as `ERR_VENDOR_SUSPENDED` on submit against a suspended vendor; and as `ERR_NO_ACTIVE_POLICY` on submit or a replenishment run when no policy is active.
7. Segregation and duplication clearance — `ERR_SEGREGATION_OF_DUTIES` on verification open and complete, approve, and deny; `ERR_DUPLICATION_CHECK_REQUIRED` and `ERR_DUPLICATION_UNRESOLVED` on approve and waitlist.
8. Cross-reference compatibility — `ERR_VENDOR_CATEGORY_MISMATCH` at application creation; `ERR_VENDOR_MISMATCH` and `ERR_NO_RESERVED_ALLOCATION` at payment issuance.
9. Temporal windows — `ERR_SOURCE_PERIOD_CLOSED` at payment issuance or reissue; `ERR_APPEAL_WINDOW_CLOSED` on appeal; `ERR_SOURCE_PERIOD_OVERLAP` at funding-source creation.
10. Structural constraints — `ERR_DOCUMENTS_INCOMPLETE` at submit; `ERR_SERVICE_MONTH_CONFLICT` at application creation; `ERR_PAYMENT_EXCEEDS_ALLOCATION` at payment issuance or reissue; `ERR_PAYMENTS_OUTSTANDING` and `ERR_PAYMENTS_CLEARED` at award void or adjust; `ERR_RESERVED_FUNDS_OUTSTANDING` at source closure.
11. Fiscal ceilings last — `ERR_INCOME_LIMIT_EXCEEDED`, `ERR_ANNUAL_CAP_EXCEEDED`, `ERR_CATEGORY_CAP_EXCEEDED`, and `ERR_FUNDS_EXHAUSTED` at approval, waitlisting, and waitlist promotion.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Program: Eligibility Policy, Vendors, and Funding Pools

Before any family can be helped, a `ProgramManager` drafts the program's **eligibility policy**. A policy is created with a `name`, a `max_annual_benefit_cents` ceiling on total help any one household may receive in a benefit year (must be greater than zero), a `rent_cap_cents` ceiling on `RENT`-category help per household per year (greater than zero), a `utility_cap_cents` ceiling for `UTILITY`-category help (greater than zero), and an `income_limit_cents` eligibility ceiling (zero or more). Four policy flags shape intake: `appeal_window_days`, which defaults to 30 when omitted and must be greater than zero, and three documentation toggles — `require_eviction_notice` (default true), `require_lease_ledger` (default false), and `require_utility_bill` (default true). A new policy is born in `DRAFT` status. Activation by a `ProgramManager` moves a `DRAFT` policy to `ACTIVE` and simultaneously retires whichever policy was previously `ACTIVE` to `RETIRED`, so at most one policy is `ACTIVE` at any moment; both the newly activated policy and the retired one bump their `version`. Attempting to activate a policy that is not in `DRAFT` fails with `ERR_INVALID_POLICY_STATE`. Policies may be listed with an optional `status` filter.

Alongside the policy, the program maintains its **vendors** — the landlords and utility companies that receive payment. Either a `Caseworker` or a `ProgramManager` may register a vendor with a `name`, a `vendor_type` of `LANDLORD` or `UTILITY`, and optional `contact_name` and `phone` (both defaulting to empty when omitted). Vendors are born `ACTIVE`. A `ProgramManager` may suspend an `ACTIVE` vendor, moving it to `SUSPENDED`, and may reactivate a `SUSPENDED` vendor back to `ACTIVE`; calling either action from the wrong state fails with `ERR_INVALID_STATE`. Suspension blocks new application submissions that reference the vendor, as described in the intake workflow below.

The money itself lives in **funding sources**. A `ProgramManager` creates each source with a `name`, a `funder_name` identifying the donor or grantor organization, a `source_type` of `DONOR_UNRESTRICTED`, `GRANT_RESTRICTED`, or `GOVERNMENT`, a non-empty `allowed_categories` list drawn from `RENT` and `UTILITY`, a half-open funding period from `period_start` (inclusive) to `period_end` (exclusive), a `total_budget_cents` greater than zero, and a `max_per_household_cents` draw cap per household per benefit year, also greater than zero. One structural guard applies at creation: the new source's half-open period must not overlap the period of any other non-`CLOSED` source from the same `funder_name`, though adjacency is permitted — one source's `period_end` equal to another's `period_start` does not count as overlap. A violation is rejected with `ERR_SOURCE_PERIOD_OVERLAP`. A new source is born `ACTIVE`.

Three computed balances travel with every funding source. `reserved_cents` is the sum, over the source's `RESERVED` allocations, of each allocation's `allocated_cents` minus its `consumed_cents`. `committed_cents` is the sum of `consumed_cents` over the source's allocations — money actually paid out — accumulated across `RESERVED` and `CONSUMED` allocations, with `RELEASED` allocations contributing only their `consumed_cents`. `available_cents` is `total_budget_cents` minus `committed_cents` minus `reserved_cents`. These three are recomputed after every mutation that touches the source — approval, payment clearing, award adjustment, award voiding, or deposit — and the invariant that committed plus reserved plus available always equals `total_budget_cents` holds at all times.

A source whose `available_cents` reaches exactly zero after any reservation or budget mutation automatically transitions `ACTIVE → EXHAUSTED`, and a source whose `available_cents` rises above zero again — through a deposit or an allocation release — automatically returns `EXHAUSTED → ACTIVE`; both automatic transitions bump the source's `version`. A `ProgramManager` may deposit additional budget into any non-`CLOSED` source by supplying `amount_cents`; the deposit increases `total_budget_cents`, recomputes `available_cents`, revives an `EXHAUSTED` source to `ACTIVE` when availability rises above zero, and bumps `version`. Deposits into a `CLOSED` source fail with `ERR_INVALID_SOURCE_STATE`. Closing a source — permitted from `ACTIVE` or `EXHAUSTED`, otherwise `ERR_INVALID_SOURCE_STATE` — requires `reserved_cents` to be exactly zero, failing with `ERR_RESERVED_FUNDS_OUTSTANDING` otherwise; an `EXHAUSTED` source therefore closes only when its entire budget has been committed, since closure demands zero reserved funds on top of zero availability. Closure moves the source to the terminal `CLOSED` state and bumps `version`.

### 3.2. Household Registration and Application Intake

Casework begins with the household. A `Caseworker` registers it with the `head_of_household_name`, the street `address`, a contact `phone`, the `household_size` (at least 1), and the `annual_income_cents` (zero or more). The new household record starts at `version` 1.

Against a registered household, a `Caseworker` opens an assistance application by naming the `household_id`, the `vendor_id` of the landlord or utility that would receive direct payment, a `category` of `RENT` or `UTILITY`, the `requested_amount_cents` (greater than zero), and the `service_month` the assistance covers, formatted YYYY-MM. Two structural checks fire at creation. First, the category must match the vendor's type: `RENT` applications require a `LANDLORD` vendor and `UTILITY` applications a `UTILITY` vendor, with mismatches rejected as `ERR_VENDOR_CATEGORY_MISMATCH`. Second, the same household may not hold another application for the same category and `service_month` in any status other than `DENIED`, `WITHDRAWN`, or `CLOSED`; a conflicting live application triggers `ERR_SERVICE_MONTH_CONFLICT`. A created application starts in `INTAKE`, records the acting operator as `intake_caseworker_id` (the segregation-of-duties anchor for everything that follows), and leaves `active_award_id` empty; `submitted_at`, `waitlisted_at`, `denied_at`, and `closed_at` stay empty until their respective events occur, and `denial_reason` stays empty until a denial.

While the application remains in `INTAKE`, the caseworker attaches supporting documents, each carrying a `doc_type` of `EVICTION_NOTICE`, `LEASE_LEDGER`, `UTILITY_BILL`, or `ID_VERIFICATION` and an opaque `file_reference` to the uploaded file; the server records the uploader as `uploaded_by`. Documents are immutable once attached, and attachment is accepted only while the application is still in `INTAKE` — once the case has moved on, further attachments are rejected. Documents can be listed for a case via the `application_id` filter.

### 3.3. Vendor Verification

Submission moves an application `INTAKE → SUBMITTED` and is a `Caseworker` action guarded by three preconditions. An eligibility policy must currently be `ACTIVE`, else `ERR_NO_ACTIVE_POLICY`. Every document the active policy requires for the application's category must be attached, else `ERR_DOCUMENTS_INCOMPLETE`: a `RENT` application needs an `EVICTION_NOTICE` exactly when the policy's `require_eviction_notice` is set plus a `LEASE_LEDGER` exactly when `require_lease_ledger` is set, while a `UTILITY` application needs a `UTILITY_BILL` exactly when `require_utility_bill` is set. And the application's vendor must be `ACTIVE`, else `ERR_VENDOR_SUSPENDED`. A successful submit pins the application's `policy_id` to the currently `ACTIVE` policy, stamps `submitted_at` from the logical clock, and bumps the application's `version`. Submit from any state other than `INTAKE` fails with `ERR_INVALID_APPLICATION_STATE`.

Verification opens from `SUBMITTED` or from `VERIFICATION_FAILED` — a second chance after a failed first attempt — and from nowhere else. The opening `Caseworker` must carry `expected_application_version` per the concurrency contract and must not be the caseworker recorded as `intake_caseworker_id`, else `ERR_SEGREGATION_OF_DUTIES`. Opening creates a fresh VendorVerification in `PENDING`, copies the application's `vendor_id` onto it, records the acting operator as `verifier_id`, supersedes any still-`PENDING` earlier verification of the same application to `SUPERSEDED`, advances the application to `UNDER_VERIFICATION`, and bumps the application's `version`.

Completion records the vendor's answer. Only a `PENDING` verification may be completed — anything else draws `ERR_INVALID_VERIFICATION_STATE` — and the completing caseworker must again differ from `intake_caseworker_id`. The request carries an `outcome`. When the outcome is `PASSED`, `confirmed_amount_cents` — the amount the vendor confirms is actually owed — must be present and greater than zero, with its absence drawing `ERR_INVALID_REQUEST`; the server records it along with `completed_at` and any `outcome_notes`, and the application moves `UNDER_VERIFICATION → PENDING_DECISION`. When the outcome is `FAILED`, no confirmed amount is required; `completed_at` and `outcome_notes` are recorded and the application moves `UNDER_VERIFICATION → VERIFICATION_FAILED`, from which a fresh verification may later be opened. A `PENDING` verification also flips to `SUPERSEDED` automatically when a newer verification is created for the same application or when the application is withdrawn.

### 3.4. Duplication-of-Benefits Screening

Because applicants often approach several agencies for the same bill, every application must clear a duplication-of-benefits screen before money moves. A `Caseworker` opens a check by supplying the `agency_name` of the external organization contacted; the write carries `expected_application_version` per the concurrency contract, records the opener as `recorded_by`, creates the check in `PENDING`, supersedes any still-`PENDING` earlier check of the same application to `SUPERSEDED`, and bumps the application's `version`.

When the outside agency answers, a `Caseworker` resolves the check with a `result` of `CLEARED` or `FLAGGED`, optionally recording `resolution_notes`; resolving anything other than a `PENDING` check fails with `ERR_INVALID_DUPLICATION_CHECK_STATE`. A `FLAGGED` result means the agency reports overlapping assistance. A `ProgramManager` may then override the flag — moving the check `FLAGGED → CLEARED` — by supplying an `override_justification`; override attempted on anything other than a `FLAGGED` check likewise fails with `ERR_INVALID_DUPLICATION_CHECK_STATE`.

Two gates at decision time enforce the screen. Approving or waitlisting an application that has no duplication check recorded at all is rejected with `ERR_DUPLICATION_CHECK_REQUIRED`, and the same actions are rejected with `ERR_DUPLICATION_UNRESOLVED` while any of the application's checks remains `PENDING` or `FLAGGED`. Of the two, the missing-check gate surfaces first when neither requirement is met.

### 3.5. Decision Point: Approval, Waitlisting, Denial, Appeal, and Withdrawal

Approval turns a `PENDING_DECISION` application into funded help, and only a `ProgramManager` may perform it. The preconditions evaluate in the program's fixed order: the application must actually be in `PENDING_DECISION` (`ERR_INVALID_APPLICATION_STATE`); segregation of duties must hold against both the `intake_caseworker_id` and the `verifier_id` of the latest `PASSED` verification (`ERR_SEGREGATION_OF_DUTIES`); the duplication gates of the previous section must pass; and then the fiscal ceilings apply.

The income screen is inclusive at the boundary: a household whose `annual_income_cents` is less than or equal to the pinned policy's `income_limit_cents` is eligible, while income even one cent above the limit is rejected with `ERR_INCOME_LIMIT_EXCEEDED`. Household benefit usage is then measured over the household's current benefit-year award set — every award of that household in `ACTIVE`, `PARTIALLY_DISBURSED`, or `DISBURSED` status (`VOIDED` awards are excluded) whose `benefit_year` equals the logical clock's current calendar year. The year-to-date exposure is the sum of those awards' `awarded_amount_cents`, counted in full even when approved-but-unpaid; category year-to-date figures restrict the same sum to awards whose application category is `RENT` or `UTILITY` respectively. The remaining annual cap is the pinned policy's `max_annual_benefit_cents` minus the year-to-date exposure, and the remaining category cap is `rent_cap_cents` or `utility_cap_cents` minus the matching category figure. When the remaining annual cap is exactly zero, approval fails with `ERR_ANNUAL_CAP_EXCEEDED`; when the remaining category cap is exactly zero, it fails with `ERR_CATEGORY_CAP_EXCEEDED`.

The approved amount is the smallest of four figures: the application's `requested_amount_cents`, the latest `PASSED` verification's `confirmed_amount_cents`, the remaining annual cap, and the remaining category cap for the application's category. Should that smallest figure come out zero because the confirmed amount itself was zero, the approval is rejected with `ERR_INVALID_REQUEST`. Because the cap-exhaustion rejections precede this computation, a zero award can only arise from a zero confirmed amount.

Funding then flows through the **allocation waterfall**. A funding source is compatible with the application when the source is `ACTIVE`, when the application's `category` appears in the source's `allowed_categories`, when the logical clock sits at or after `period_start` and strictly before `period_end`, when the source's `available_cents` is above zero, and when the source still has per-household room: its `max_per_household_cents` minus the sum of `allocated_cents` across that source's allocations attached to this household's non-`VOIDED` awards of the current benefit year. Compatible sources are ranked with the most restricted source first — a shorter `allowed_categories` list ranks ahead of a longer one — then by earliest `period_end`, then by earliest `created_at`, with any tie still remaining broken by `id`; each allocation records its position in this ranking as `rank_order`, starting at 0 for the first-drawn source. The sweep then walks the ranked sources, taking from each the smallest of the remaining need, the source's `available_cents`, and its per-household room; each take creates a FundingAllocation in `RESERVED` status with `consumed_cents` at zero, adds the take to the source's `reserved_cents`, and flips the source `ACTIVE → EXHAUSTED` if its availability thereby reaches zero. If the sweep ends with need still uncovered, the approval is rejected with `ERR_FUNDS_EXHAUSTED` (HTTP 402) and the operation is atomic — no award, no allocations, and no balance changes persist.

A successful approval creates the AssistanceAward in `ACTIVE` status, pins its `policy_id` to the application's pinned policy, stamps its `benefit_year` with the clock's current calendar year, sets its `awarded_amount_cents` to the determined amount, points the application's `active_award_id` at it, moves the application from `PENDING_DECISION` into `APPROVED`, and bumps the application's `version`.

When money is tight but the case is sound, the `ProgramManager` may instead waitlist the application, moving it `PENDING_DECISION → WAITLISTED`. Waitlisting enforces the same segregation, duplication, income, and cap preconditions as approval — but deliberately does not check funds availability. The clock stamps `waitlisted_at`, which later serves as the promotion ranking key, and the application's `version` bumps.

Denial is available from `PENDING_DECISION` and from `WAITLISTED`. The denying `ProgramManager` must differ from `intake_caseworker_id` (`ERR_SEGREGATION_OF_DUTIES`). The request's `reason_code` is recorded as the application's `denial_reason` — one of `INELIGIBLE_INCOME`, `CAP_EXHAUSTED`, `DUPLICATE_BENEFIT`, `VERIFICATION_FAILED`, `ELIGIBILITY_LAPSED`, or `PROGRAM_DIRECTED` — `denied_at` is stamped from the clock, the application lands in `DENIED`, and its `version` bumps.

A denied household gets a second hearing through appeal, a `Caseworker` action carrying an `appeal_reason`. The window is measured against the application's pinned policy: the deadline is `denied_at` plus the policy's `appeal_window_days`, and the boundary is inclusive — an appeal arriving exactly at the deadline succeeds, while one a single second past it is rejected with `ERR_APPEAL_WINDOW_CLOSED`. A successful appeal moves the application `DENIED → PENDING_DECISION` and bumps its `version`.

Withdrawal, also a `Caseworker` action, is available from every pre-decision-locked state: `INTAKE`, `SUBMITTED`, `UNDER_VERIFICATION`, `VERIFICATION_FAILED`, `PENDING_DECISION`, and `WAITLISTED`. Withdrawing from `UNDER_VERIFICATION` additionally supersedes any still-`PENDING` verification of the application to `SUPERSEDED`. Every withdrawal lands in the terminal `WITHDRAWN` state and bumps `version`; withdrawal attempted from any other state fails with `ERR_INVALID_APPLICATION_STATE`.

### 3.6. Award Adjustment and Voiding

Circumstances change between approval and payment — a landlord forgives part of the balance, a grant officer trims the commitment. Before any payment on an award has cleared, a `ProgramManager` may reduce it through adjustment, supplying a `new_awarded_amount_cents` together with `expected_award_version` per the concurrency contract. The award must be in `ACTIVE` status, else `ERR_INVALID_AWARD_STATE`. Two payment guards then apply in a fixed order: any payment of the award still `ISSUED` rejects the adjustment with `ERR_PAYMENTS_OUTSTANDING` (checked first), and any payment already `CLEARED` rejects it with `ERR_PAYMENTS_CLEARED` (checked second).

The reduction — the difference between the current `awarded_amount_cents` and the requested `new_awarded_amount_cents` — is released pro rata across the award's `RESERVED` allocations in ascending `rank_order`. For every allocation except the last-ranked one, the released amount is that allocation's `allocated_cents` multiplied by the reduction and divided by the award's `awarded_amount_cents`, rounded down to a whole cent. The last-ranked allocation absorbs the remainder: the reduction minus the sum of the earlier releases. This rounding order is pinned — per-allocation floor first, remainder to the last-ranked allocation — because floor-then-remainder and remainder-first produce different per-source releases. Each release lowers the allocation's `allocated_cents` and its funding source's `reserved_cents` by the same amount; an allocation whose `allocated_cents` falls to zero transitions `RESERVED → RELEASED`; and any `EXHAUSTED` source whose `available_cents` rises above zero through the release returns automatically to `ACTIVE`. Finally the award's `awarded_amount_cents` drops to the new figure, and the `version` of the award and of each touched allocation increments.

Voiding unwinds an award entirely. A `ProgramManager` may void an award in `ACTIVE` or `PARTIALLY_DISBURSED` status — anything else draws `ERR_INVALID_AWARD_STATE` — subject to the same two payment guards in the same order: `ERR_PAYMENTS_OUTSTANDING` first when any payment is `ISSUED`, then `ERR_PAYMENTS_CLEARED` when any payment has `CLEARED`. Since a `PARTIALLY_DISBURSED` award by definition already has a cleared payment, voiding one deterministically fails with `ERR_PAYMENTS_CLEARED`. A successful void flips every `RESERVED` allocation of the award to `RELEASED`, reduces each affected source's `reserved_cents` by that allocation's `allocated_cents` minus its `consumed_cents`, revives any `EXHAUSTED` source whose availability rises above zero back to `ACTIVE`, moves the application `APPROVED → PENDING_DECISION` with its `active_award_id` cleared to empty, and increments the award's `version`.

### 3.7. Direct-to-Vendor Disbursement and Payment Recovery

Payments are the ministry's handshake with its vendors, and they belong to the `FinanceOfficer` alone. Issuing a payment against an award names the payee `vendor_id`, the `funding_source_id` to draw on, the `amount_cents`, and the `payment_date`. The payee must equal the vendor on the application behind the award, else `ERR_VENDOR_MISMATCH`. The named source must hold a `RESERVED` allocation on this award, else `ERR_NO_RESERVED_ALLOCATION`. The amount must be greater than zero and no more than the allocation's remainder — its `allocated_cents` minus its `consumed_cents` minus the sum of other `ISSUED` payments drawn on the same allocation — else `ERR_PAYMENT_EXCEEDS_ALLOCATION`. And the `payment_date` must fall inside the source's half-open funding period: at or after `period_start` and strictly before `period_end`, with a date exactly on `period_end` falling outside, else `ERR_SOURCE_PERIOD_CLOSED`. A valid payment is born `ISSUED` with the acting officer recorded as `issued_by`.

Clearing is the moment money actually moves. A `FinanceOfficer` clears an `ISSUED` payment — any other state draws `ERR_INVALID_PAYMENT_STATE` — and the effects ripple outward: the allocation's `consumed_cents` increases by the payment amount, and when consumed reaches allocated the allocation transitions `RESERVED → CONSUMED`; the source's `reserved_cents` decreases and its `committed_cents` increases by the amount; `cleared_at` is stamped from the logical clock; and the award bubbles up — when every allocation of the award is now `CONSUMED`, the award becomes `DISBURSED` and its application moves `APPROVED → PAID`, while an `ACTIVE` award with allocations still open becomes `PARTIALLY_DISBURSED` (a `PARTIALLY_DISBURSED` award with allocations still open simply stays where it is). The payment's `version`, and the `version` of every entity whose state advanced, increments.

Not every issued payment lands. A bounced check is marked by failing the payment, moving `ISSUED → FAILED`. A failed payment can be reissued — `FAILED → ISSUED` — which re-validates the two issuance constraints against current state: the amount must still fit the allocation remainder (`ERR_PAYMENT_EXCEEDS_ALLOCATION`) and the `payment_date` must still sit inside the source's period (`ERR_SOURCE_PERIOD_CLOSED`). A payment that will never be sent is voided, moving from `ISSUED` or `FAILED` to `VOIDED`. Failing, reissuing, or voiding from a state where that transition does not exist fails with `ERR_INVALID_PAYMENT_STATE`. Note that payment failure and voidance do not return reserved funds by themselves — the reservation unwinds only through award adjustment or voidance, keeping the source's committed-plus-reserved-plus-available invariant intact at all times.

### 3.8. Waitlist Replenishment Sweeps

When fresh money lands, a `ProgramManager` launches a replenishment run to revisit the waitlist. The run sweeps every application in `WAITLISTED` status at run start, snapshotted and ordered once by `waitlisted_at` ascending with ties broken by `created_at` ascending — never by id; applications that enter the waitlist mid-run are not included. If no eligibility policy is `ACTIVE` at launch, the entire run fails with `ERR_NO_ACTIVE_POLICY`.

Each candidate is then processed strictly in order, and the evaluation order is pinned: a candidate's own reservation is never part of the availability it is checked against — availability is read before the candidate commits, and its commit lands before the next candidate is evaluated. Three steps apply per candidate. First, eligibility is re-screened — income and both caps — against the currently `ACTIVE` policy; a candidate that fails moves `WAITLISTED → DENIED` with `denial_reason` set to `ELIGIBILITY_LAPSED` and `denied_at` stamped. Second, the award amount is recomputed from the candidate's pinned-at-submit data and its latest `PASSED` verification, exactly as at approval time. Third, the allocation waterfall runs against current source balances. A candidate the waterfall cannot fully fund remains `WAITLISTED` and the run continues to the next candidate — skip-and-continue, never stop-at-first-failure. A candidate that clears all three steps is promoted `WAITLISTED → APPROVED`: its `policy_id` is re-pinned to the currently `ACTIVE` policy, and the award, allocations, source balance updates, and automatic `EXHAUSTED` transitions all commit exactly as in a direct approval, with the application's `version` bumping.

The run's results persist on the ReplenishmentRun record: the launching manager as `run_by`, the `promoted_count`, the `denied_count`, the `remaining_waitlisted_count`, the `promoted_application_ids` in promotion order, and the `denied_application_ids` in processing order. Conservation holds across every run: the number of waitlisted candidates before the run equals `promoted_count` plus `denied_count` plus `remaining_waitlisted_count`. Between runs, manual denial from `WAITLISTED` remains available under the ordinary deny rule.

### 3.9. Case Notes, Closure, and Program Reporting

Casework does not end when money moves. A `Caseworker` appends case notes to an application at any point, each with a `note_type` of `GENERAL`, `FOLLOW_UP`, `DUPLICATION_CHECK`, or `COMMUNICATION`, a non-empty free-text `body`, and an optional `occurred_at` that defaults to the logical clock time when omitted; the server records the writer as `author_id`. A `FOLLOW_UP` note must additionally carry an `outcome` — one of `CRISIS_RESOLVED`, `PARTIAL_RELIEF`, `NO_CHANGE`, or `LOST_CONTACT` — and its absence on a follow-up note is rejected with `ERR_INVALID_REQUEST`. Notes are immutable once written.

Closure is the last chapter of a case, available from `PAID` and from `DENIED`. At least one case note of type `FOLLOW_UP` must exist for the application before it can close, else the attempt is rejected with `ERR_FOLLOW_UP_REQUIRED`. A successful close stamps `closed_at` from the logical clock, lands the application in the terminal `CLOSED` state, and bumps its `version`.

Two computed reads serve the program's reporting duties. A household's benefit summary answers with the current `benefit_year`, the household's `ytd_exposure_cents` and `ytd_committed_cents`, the `remaining_annual_cap_cents`, the per-category `rent_ytd_cents` and `utility_ytd_cents`, and the `remaining_rent_cap_cents` and `remaining_utility_cap_cents`, all evaluated against the currently `ACTIVE` policy. Two measurement bases diverge here deliberately: the exposure basis counts the full `awarded_amount_cents` of every non-`VOIDED` award in the benefit-year set, including approved-but-unpaid amounts, while the committed basis counts only `consumed_cents` across those awards' allocations — money actually cleared — so the two differ whenever an award is approved but not yet fully paid.

The funding-source report, available to `ProgramManager` and `Auditor`, answers with `funding_source_id`, `committed_cents`, `reserved_cents`, `available_cents`, `cash_utilization_pct`, `encumbrance_utilization_pct`, `rent_committed_cents`, `utility_committed_cents`, `households_served`, `period_start`, and `period_end`. The cash utilization percentage is `committed_cents` divided by `total_budget_cents` and expressed as a percentage; the encumbrance utilization percentage uses committed plus reserved as its numerator and is strictly greater than the cash figure whenever any `RESERVED` allocation is not fully consumed — the cash basis serves donor statements while the encumbrance basis serves grant pipeline reporting. Both percentages carry one decimal place, rounded half up. `rent_committed_cents` and `utility_committed_cents` sum `consumed_cents` over allocations whose award's application falls in the matching category. `households_served` counts the distinct households with at least one `CLEARED` payment drawn on this source whose `cleared_at` falls inside the half-open funding period — a payment cleared exactly at `period_end` is excluded.

List endpoints across the API accept filters keyed to their resource: applications filter by `household_id`, `vendor_id`, `policy_id`, `status`, and `category`; documents, duplication checks, and case notes filter by `application_id`, with notes additionally filtering by `note_type`; verifications filter by `application_id` or `vendor_id`; awards filter by `application_id`, `policy_id`, or `status`; allocations filter by `award_id`, `funding_source_id`, or `status`; funding sources and policies filter by `status`; and payments filter by `award_id`, `vendor_id`, `funding_source_id`, or `status`.

## 4. Endpoint Definitions

All endpoints live under the `/assistance` mount, except the clock control. Creating a new resource returns HTTP 201; reads, actions, and modifications of existing resources return HTTP 200. The table below is a summary only — request fields, response shapes, preconditions, and side effects are defined in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /assistance/households | Register a household | Caseworker |
| GET | /assistance/households/{id} | Fetch a household | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/households/{id}/benefit-summary | Computed read: current benefit-year usage for this household (exposure and committed bases) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/policies | Create an eligibility policy in DRAFT | ProgramManager |
| GET | /assistance/policies/{id} | Fetch a policy | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/policies | List policies | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/policies/{id}/activate | Activate a DRAFT policy; retires the currently ACTIVE policy | ProgramManager |
| POST | /assistance/vendors | Register a landlord/utility vendor | Caseworker, ProgramManager |
| GET | /assistance/vendors/{id} | Fetch a vendor | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/vendors/{id}/suspend | Suspend a vendor (blocks new application submissions referencing it) | ProgramManager |
| POST | /assistance/vendors/{id}/reactivate | Reactivate a suspended vendor | ProgramManager |
| POST | /assistance/applications | Open an assistance application in INTAKE | Caseworker |
| GET | /assistance/applications/{id} | Fetch an application | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/applications | List applications with filters | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/applications/{id}/documents | Attach a document to an INTAKE application | Caseworker |
| POST | /assistance/applications/{id}/submit | Submit an INTAKE application; pins the ACTIVE policy | Caseworker |
| POST | /assistance/applications/{id}/verifications | Open a vendor verification (OCC-guarded; supersedes any PENDING verification) | Caseworker |
| POST | /assistance/applications/{id}/duplication-checks | Open a duplication-of-benefits check (OCC-guarded; supersedes any PENDING check) | Caseworker |
| POST | /assistance/applications/{id}/approve | Approve a PENDING_DECISION application: computes award, runs the allocation waterfall, reserves funds | ProgramManager |
| POST | /assistance/applications/{id}/deny | Deny a PENDING_DECISION or WAITLISTED application | ProgramManager |
| POST | /assistance/applications/{id}/waitlist | Move a PENDING_DECISION application to WAITLISTED (eligibility checked, funds not checked) | ProgramManager |
| POST | /assistance/applications/{id}/appeal | Appeal a DENIED application within the pinned policy's appeal window | Caseworker |
| POST | /assistance/applications/{id}/withdraw | Withdraw a pre-approval application | Caseworker |
| POST | /assistance/applications/{id}/close | Close a PAID or DENIED application after a follow-up outcome is recorded | Caseworker |
| POST | /assistance/applications/{id}/case-notes | Append an immutable case note | Caseworker |
| GET | /assistance/documents/{id} | Fetch a document | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/documents | List documents (filter by application) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/verifications/{id} | Fetch a verification | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/verifications | List verifications (filter by application or vendor) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/verifications/{id}/complete | Record the vendor verification outcome; drives the application state | Caseworker |
| GET | /assistance/duplication-checks/{id} | Fetch a duplication check | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/duplication-checks | List duplication checks (filter by application) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/duplication-checks/{id}/resolve | Record the external agency's response | Caseworker |
| POST | /assistance/duplication-checks/{id}/override | Override a FLAGGED check to CLEARED with justification | ProgramManager |
| GET | /assistance/case-notes/{id} | Fetch a case note | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/case-notes | List case notes (filter by application or note type) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/awards/{id} | Fetch an award | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/awards | List awards (filter by application or pinned policy) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/awards/{id}/adjust | Reduce an award before any payment clears (OCC-guarded); pro-rata release across allocations | ProgramManager |
| POST | /assistance/awards/{id}/void | Void an award before any payment clears; releases all reservations and returns the application to PENDING_DECISION | ProgramManager |
| POST | /assistance/awards/{id}/payments | Issue a direct-to-vendor payment against a RESERVED allocation | FinanceOfficer |
| GET | /assistance/allocations/{id} | Fetch an allocation | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/allocations | List allocations (filter by award or funding source) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/funding-sources | Create a funding source (donor/grant/government pool) | ProgramManager |
| GET | /assistance/funding-sources/{id} | Fetch a funding source with computed balances | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/funding-sources | List funding sources | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/funding-sources/{id}/deposits | Deposit additional budget into a non-CLOSED source | ProgramManager |
| POST | /assistance/funding-sources/{id}/close | Close a source to new allocations (requires zero reserved funds) | ProgramManager |
| GET | /assistance/funding-sources/{id}/report | Donor/grant report: cash vs encumbrance utilization, per-category committed totals, households served | ProgramManager, Auditor |
| GET | /assistance/payments/{id} | Fetch a payment | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| GET | /assistance/payments | List payments (filter by award, vendor, or funding source) | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /assistance/payments/{id}/clear | Mark a payment cleared by the vendor; moves reserved funds to committed | FinanceOfficer |
| POST | /assistance/payments/{id}/fail | Mark a payment failed (e.g., check bounced) | FinanceOfficer |
| POST | /assistance/payments/{id}/reissue | Reissue a FAILED payment; re-validates remainder and period | FinanceOfficer |
| POST | /assistance/payments/{id}/void | Void an ISSUED or FAILED payment | FinanceOfficer |
| POST | /assistance/replenishment-runs | Sweep the waitlist in priority order, promoting or denying; skip-and-continue on funding shortfall | ProgramManager |
| GET | /assistance/replenishment-runs/{id} | Fetch a run's recorded results | Caseworker, ProgramManager, FinanceOfficer, Auditor |
| POST | /_clock/set_current_utc | Set the server's logical clock (starts at exactly 2026-08-01T00:00:00Z; never falls back to wall-clock time) | ProgramManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the identifier-to-status index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_APPLICATION_STATE | 409 |
| ERR_INVALID_VERIFICATION_STATE | 409 |
| ERR_INVALID_DUPLICATION_CHECK_STATE | 409 |
| ERR_INVALID_AWARD_STATE | 409 |
| ERR_INVALID_PAYMENT_STATE | 409 |
| ERR_INVALID_SOURCE_STATE | 409 |
| ERR_INVALID_POLICY_STATE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_VENDOR_SUSPENDED | 409 |
| ERR_NO_ACTIVE_POLICY | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_DUPLICATION_CHECK_REQUIRED | 409 |
| ERR_DUPLICATION_UNRESOLVED | 409 |
| ERR_VENDOR_CATEGORY_MISMATCH | 409 |
| ERR_VENDOR_MISMATCH | 409 |
| ERR_NO_RESERVED_ALLOCATION | 409 |
| ERR_SOURCE_PERIOD_CLOSED | 409 |
| ERR_APPEAL_WINDOW_CLOSED | 409 |
| ERR_SOURCE_PERIOD_OVERLAP | 409 |
| ERR_DOCUMENTS_INCOMPLETE | 409 |
| ERR_SERVICE_MONTH_CONFLICT | 409 |
| ERR_PAYMENT_EXCEEDS_ALLOCATION | 409 |
| ERR_PAYMENTS_OUTSTANDING | 409 |
| ERR_PAYMENTS_CLEARED | 409 |
| ERR_RESERVED_FUNDS_OUTSTANDING | 409 |
| ERR_INCOME_LIMIT_EXCEEDED | 409 |
| ERR_ANNUAL_CAP_EXCEEDED | 409 |
| ERR_CATEGORY_CAP_EXCEEDED | 409 |
| ERR_FOLLOW_UP_REQUIRED | 409 |
| ERR_FUNDS_EXHAUSTED | 402 |

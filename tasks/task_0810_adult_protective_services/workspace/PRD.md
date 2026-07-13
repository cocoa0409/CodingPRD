# Adult Protective Services API — Product Requirements Document

## 1. Introduction

Adult Protective Services (APS) agencies exist to protect vulnerable adults from abuse, neglect, and financial exploitation while respecting the legal and procedural safeguards that surround emergency intervention into a person's life and finances. The workload spans an entire casework lifecycle: a report arrives at the front door, a supervisor screens it in or out, an investigator opens a case and assesses the client's risk and decisional capacity, and — where warranted — the agency arranges emergency protective placement, refers the client for guardianship, freezes financially exploited accounts, links the client to benefit programs, and finally closes the case once the work is complete.

This API is the system of record for that lifecycle. It coordinates several classes of front-line staff (intake workers, caseworkers, and supervisors) plus a system operator, and it enforces the compliance rules that make the difference between a defensible intervention and an unlawful one: response-time SLAs driven by intake priority, eligibility gates on emergency placement and guardianship, mandatory cross-reporting when suspected financial exposure crosses a statutory threshold, bed-capacity limits at placement facilities, and a mandatory cool-down between successive account freezes. Because much of this work is time-sensitive and auditable, the system runs on an explicit logical clock rather than wall-clock time, so that SLAs, placement expiry, and closure timestamps are deterministic and test-driveable.

The requirements below are organized into system-wide contracts (Section 2), the business workflows that constitute the casework lifecycle (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles: `IntakeWorker`, `Caseworker`, `Supervisor`, and `Admin`. If either header is missing, or if `X-User-Role` is not one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the acting role is not permitted to perform the requested operation according to the authorization matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

All four roles carry an **opaque** identity: `X-User-ID` is an operator identifier that is not tied to any persisted entity, and the server never compares it to any entity's `id` for ownership. When a `Caseworker` opens an investigation, the server records that operator's `X-User-ID` onto the investigation's `assigned_caseworker_id` field, but this is a bookkeeping record only and is never used as an ownership check on later operations. An `IntakeWorker` staffs the front door — filing reports and registering clients and their financial accounts. A `Caseworker` investigates — opening investigations, determining capacity, assessing risk, arranging placements, freezing accounts, and building service plans. A `Supervisor` is the approval authority — screening reports, returning or disposing findings, closing cases, lifting freezes, expiring placements, and recovering funds. An `Admin` is the system operator — provisioning facilities and controlling the logical clock. The precise per-endpoint permissions are given in the Section 4 table.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter counts how many items to skip from the front of the result and defaults to 0.

Unless a specific workflow says otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of matching resources before pagination and `has_more` indicates whether any matching resources remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in this system — reports, clients, financial accounts, facilities, cases, investigations, emergency placements, and financial freezes — carries a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; the `updated_at` field is an ISO 8601 UTC timestamp, in the same format, recording the most recent modification. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation of the resource. All eight entity types in this system participate in this common-field convention, so each of them exposes `id`, `created_at`, `updated_at`, and `version`.

The `id` value is generated by the server; clients never supply it. Any field described in the workflows below as computed or system-managed (for example a report's `status` or a client's `open_case_count`) is likewise owned by the server and is never accepted from the request body.

### 2.5. The Logical Clock and Temporal Semantics

The server keeps an explicit **logical clock** that is the sole source of "now" for the whole system. On startup the clock reads `2026-03-01T00:00:00Z`, and it never falls back to wall-clock time. An `Admin` may advance or set the clock by supplying a target instant as `to_iso8601`; this is a test-driving capability, and the new instant becomes the value used by every subsequent time-dependent computation. The clock feeds the report response deadline, the overdue determination made at screening time, emergency-placement expiry, the cross-report timestamp `cross_reported_at`, the case `closed_at`, an investigation's `disposed_at`, a placement's `discharged_at`, and a freeze's `lifted_at`.

All datetime inputs and outputs are ISO 8601 UTC instants. Whenever the requirements below say an interval bound must be "strictly after" another, or that a deadline is passed only when the clock is "strictly after" it, that strictness is exact: an instant equal to the boundary does not satisfy a strict comparison.

### 2.6. Request Validation Order

When a request could fail more than one check, the checks are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is first: absent or unknown headers yield `ERR_UNAUTHENTICATED` (401). Authorization is second: a known role lacking permission for the endpoint yields `ERR_UNAUTHORIZED` (403). Existence resolution is third: every id referenced by the request — whether it appears in the URL path or in the request body (report, client, account, facility, case, investigation, placement, or freeze) — must resolve to a stored entity, and these are validated left to right, so the first unresolved id determines the error. Each entity type has its own not-found error: `ERR_REPORT_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, and `ERR_FREEZE_NOT_FOUND`, each HTTP 404.

Body well-formedness is fourth: a write whose body omits a required field or supplies a value of the wrong JSON type is rejected with `ERR_VALIDATION` (400). Enum membership is fifth: an enum-typed field carrying a value outside its declared set — this includes `reporter_type`, `priority`, `decision`, `disposition`, `assessment_type`, and `determination` — or an `allegation_types` array that is empty, is rejected with `ERR_INVALID_ENUM` (422). Interval ordering is sixth: on placement and freeze creation, the end bound must be strictly after the start bound, and a violation yields `ERR_INVALID_DATE_RANGE` (422). State admissibility is seventh: an operation targeting an entity whose current state does not admit the requested transition is rejected with that entity's invalid-state error (described per workflow in Section 3). Only after all of these pass does the server evaluate the endpoint-specific business rules, and where a single endpoint layers several of those, the order in which they fire is spelled out in the relevant Section 3 narrative.

### 2.7. Optimistic Concurrency on Risk Assessments

Submitting a risk assessment for a client is guarded by optimistic concurrency control. The request must include `expected_client_version`, carrying the `version` of the client the caller last observed. Because a comprehensive assessment supersedes the prior authoritative risk determination for the client — and mirrors that determination onto the open case — a caller holding a stale view of the client must not be allowed to silently overwrite a newer authoritative assessment. Accordingly, when the submitted `expected_client_version` does not equal the client's current `version`, the request is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412). A comprehensive assessment that passes this check advances the client's `version` by one; because that write is what changes the authoritative risk picture, a subsequent caller who has not re-read the client will present a now-stale `expected_client_version` and be turned away on the same check.

### 2.8. Integer Precision for Money and Scores

All monetary quantities in this system are held as integer cents, and all risk figures are held as integers; there is no floating-point money and no rounding of stored balances to decimal places. Balance and exposure arithmetic is exact integer arithmetic. The one place rounding is used is when recovered funds are divided across multiple accounts (Section 3.6): each per-account share is rounded half up to a whole number of cents before the shares are summed. Risk scoring (Section 3.3) is pure integer arithmetic with no rounding, and its tier boundaries are inclusive as specified there.

### 2.9. Cascading State and Consistency

Several operations mutate more than one entity in a single request, and each secondary mutation is a real mutation: it refreshes that entity's `updated_at` and increments its `version`. When a report is screened in, a new case is created and the subject client is advanced through its lifecycle. When an investigation is disposed, its owning case and then the subject client advance in a chain. When a case is closed, the closure fans out to that case's active placements, active freezes, and service plan, and to the subject client. When a freeze is created or lifted, the affected account's balance breakdown is recomputed and the case's exposure figures are recomputed. Each of these secondary effects is described in full in the workflow that triggers it; the governing principle here is simply that the system keeps parent and child states aligned automatically, without requiring a separate client request against each affected resource.

## 3. Business Logic & Workflows

### 3.1. Intake: Registering the Client and Filing the Report

The lifecycle begins at the front door, where an `IntakeWorker` first registers the vulnerable adult as a **Client**. A client record is created from three inputs: the person's `full_name`, their `date_of_birth` as an ISO date in `YYYY-MM-DD` form, and their residential `address`. On creation the system sets the client's decisional-capacity outcome `capacity_status` to `UNKNOWN` and its lifecycle `status` to `INTAKE`. Several other client attributes are computed and start empty: `placement_status` begins at `NONE`, `open_case_count` begins at 0, and `risk_level`, `preliminary_risk_score`, and `comprehensive_risk_score` all begin null, because no assessment yet exists.

With a client on file, an `IntakeWorker` files an intake **Report** about the alleged victim. The report body carries the `client_id` of the person it concerns, a `reporter_type` that is one of `MANDATORY`, `VOLUNTARY`, or `ANONYMOUS` (mandatory reporters, such as clinicians and bankers, carry a legal reporting duty), an optional `reporter_name` that may be omitted and defaults to null — as is expected for an `ANONYMOUS` report — a non-empty `allegation_types` array whose members are each drawn from `PHYSICAL_ABUSE`, `NEGLECT`, `FINANCIAL_EXPLOITATION`, `EMOTIONAL_ABUSE`, and `SELF_NEGLECT`, an intake `priority` of `EMERGENCY`, `PRIORITY`, or `ROUTINE`, and a free-text `narrative` describing the allegation. A freshly filed report has its `status` set to `RECEIVED`, its `screen_out_reason` null, its `screening_overdue` false, and its `case_id` null; the `case_id` back-reference is filled only if and when the report is screened in, at which point the resulting case can be located by filtering cases on their originating report.

The intake `priority` sets the response-time clock. At the moment the report is created, the system computes `response_due_at` as the report's `created_at` plus a fixed service-level allowance: 24 hours (one day) for an `EMERGENCY` report, 72 hours (three days) for a `PRIORITY` report, and 240 hours (ten days) for a `ROUTINE` report. This due instant is stored on the report and later drives the overdue determination made at screening.

### 3.2. Screening the Report

Screening is a `Supervisor` responsibility and the first branching decision in the lifecycle. The supervisor supplies a `decision` — either `SCREEN_IN` or `SCREEN_OUT`. Either path requires the report to be in `RECEIVED` status; screening a report in any other status is rejected with `ERR_REPORT_INVALID_STATE` (409). Regardless of which branch is taken, the system stamps `screening_overdue` on the report as true exactly when the logical clock at screening time is strictly past the report's `response_due_at`, and false when the clock is at or before that instant.

On the **screen-in** branch, the report moves from `RECEIVED` to `SCREENED_IN`. The system opens a new **Case** in `OPEN` status, recording the originating report as the case's `report_id`, copying the report's `client_id` as the case subject, and copying the report's `allegation_types` verbatim onto the case. The report's `case_id` is set to the new case's id. The subject client is advanced from `INTAKE` to `UNDER_INVESTIGATION`, and the client's `open_case_count` is incremented by one.

On the **screen-out** branch, the report moves from `RECEIVED` to `SCREENED_OUT`. Here the system records the supplied `screen_out_reason` on the report and stamps `screening_overdue` as just described, but no case is created and the subject client is left entirely untouched — its status, counts, and every other attribute are unchanged. This asymmetry between the two branches is deliberate: a screen-in spins up the entire downstream case machinery, while a screen-out is a terminal disposition of the report alone.

### 3.3. Investigation, Capacity, and Risk Assessment

Once a case is `OPEN`, a `Caseworker` opens an **Investigation** against it by supplying the `case_id` of the case to be investigated. The case must be `OPEN`; opening an investigation against a case in any other status is rejected with `ERR_CASE_INVALID_STATE` (409). The new investigation starts in `IN_PROGRESS`, its `assigned_caseworker_id` is set from the acting operator's `X-User-ID`, and the owning case advances from `OPEN` to `UNDER_INVESTIGATION`.

During the investigation the caseworker builds up two determinations about the client. The first is decisional capacity: a caseworker records a determination by supplying `determination`, which sets the client's `capacity_status` to either `INTACT` or `IMPAIRED` and increments the client's `version` by one. The second is risk. A risk assessment supplies an `assessment_type` of `PRELIMINARY` or `COMPREHENSIVE`, four contributing factors each an integer from 0 to 3 — `isolation_level`, `cognitive_impairment_level`, `financial_vulnerability_level`, and `caregiver_dependency_level` — plus a `prior_report_count` that is an integer of zero or more, and the concurrency token `expected_client_version` described in Section 2.7.

The risk score is computed in a fixed order. First the system forms a raw score by adding five weighted terms: the `isolation_level` times 10, the `cognitive_impairment_level` times 12, the `financial_vulnerability_level` times 9, the `caregiver_dependency_level` times 8, and 4 times the prior-report contribution, where the prior-report contribution is `prior_report_count` but never counted higher than 5 (a count of 5 or more contributes exactly 5). Second, the raw score is capped so that the stored score is the smaller of the raw score and 100. Third, the capped score is sorted into a tier: a score of 70 or higher is `HIGH`, a score from 40 up to but not including 70 is `MODERATE`, and a score below 40 is `LOW`; the tier boundaries are inclusive at their lower edge, so a score of exactly 70 is `HIGH` and a score of exactly 40 is `MODERATE`. All of this is integer arithmetic with no rounding.

The two assessment variants store their results differently. A `PRELIMINARY` assessment — the intake-screening variant built from reporter-supplied factors — records its capped score into the client's `preliminary_risk_score` only; it does not set the authoritative `risk_level` and does not mirror anything onto the case. A `COMPREHENSIVE` assessment — the post-investigation variant built from caseworker-verified factors — records its capped score into the client's `comprehensive_risk_score`, sets the derived tier as the authoritative client `risk_level`, and mirrors that same `risk_level` onto the open case. Only the comprehensive variant advances the client's `version` (the concurrency check in Section 2.7 governs it), which is why a comprehensive submission carrying a stale `expected_client_version` is refused with `ERR_STALE_CLIENT_VERSION` (412).

When the investigative work is done, the caseworker submits findings by supplying a `finding_summary`. Submission is admitted only from `IN_PROGRESS`; attempting it in any other investigation status yields `ERR_INVESTIGATION_INVALID_STATE` (409). Submission additionally requires that a comprehensive assessment already exist for the subject client — that is, the client's `comprehensive_risk_score` is not null; if it is still null the submission is rejected with `ERR_COMPREHENSIVE_ASSESSMENT_REQUIRED` (409). On success the investigation moves from `IN_PROGRESS` to `FINDINGS_SUBMITTED` and the `finding_summary` is stored.

Submitted findings are reviewed by a `Supervisor`, who may either return them or dispose them; both actions require the investigation to be in `FINDINGS_SUBMITTED`, and attempting either from another status yields `ERR_INVESTIGATION_INVALID_STATE` (409). Returning findings for re-investigation takes a `return_reason`, moves the investigation from `FINDINGS_SUBMITTED` back to `IN_PROGRESS`, and increments its `return_count` by one, capturing how many times the findings have been bounced back. Disposing the findings takes a `disposition` of `SUBSTANTIATED`, `UNSUBSTANTIATED`, or `INCONCLUSIVE`, moves the investigation from `FINDINGS_SUBMITTED` to `DISPOSED`, and stamps `disposed_at` with the logical clock. Disposal also drives a cascade: the owning case advances from `UNDER_INVESTIGATION` to `READY_FOR_CLOSURE`, and as part of that same chain the subject client advances from `UNDER_INVESTIGATION` to `SERVICES_PENDING`.

### 3.4. Emergency Protective Placement and Facility Capacity

Placements happen at **Facilities**, which an `Admin` provisions with a `name` and a licensed bed capacity `total_beds` of at least one. A facility tracks `occupied_beds`, which is the number of active placements currently at it (starting at 0), and `available_beds`, which is `total_beds` minus `occupied_beds`; the invariant is that available and occupied beds always sum to the licensed total.

A `Caseworker` arranges an **EmergencyPlacement** by supplying the `case_id` it belongs to, the `facility_id` where the client will be housed, a `start_at` instant, an `end_at` instant, and an optional `court_authorized` flag that defaults to false. The subject `client_id` is copied from the case rather than supplied. Before a placement is created the system runs several checks. Interval ordering is checked first among the business rules: `end_at` must be strictly after `start_at`, or the request fails with `ERR_INVALID_DATE_RANGE` (422). Next the subject client must be eligible for emergency protective placement, which means the client's `capacity_status` is `IMPAIRED` or the client's `risk_level` is `HIGH`; if neither holds, the placement is refused with `ERR_CLIENT_NOT_ELIGIBLE_FOR_PLACEMENT` (422). Finally the facility must have a free bed for the requested window: treating each placement window as the half-open interval from its `start_at` up to but not including its `end_at`, the number of existing `ACTIVE` placements at that facility whose window overlaps the requested `[start_at, end_at)` window must be strictly fewer than the facility's `total_beds`; adjacency, where one placement's `end_at` equals the next placement's `start_at`, does not count as an overlap. If no bed is free, the placement is refused with `ERR_NO_BED_AVAILABLE` (409).

On success the placement is created in `ACTIVE` status, the facility's `available_beds` is decremented (its `occupied_beds` rises by one), and the subject client's `placement_status` becomes `PLACED` — a client's `placement_status` reads `PLACED` while any placement it owns is `ACTIVE` and `NONE` otherwise. The system also computes `expires_at`: when the placement is not court-authorized, expiry is 72 hours (three days) after `start_at`, reflecting the emergency-placement cap; when `court_authorized` is true, that cap is exempted and `expires_at` is the scheduled `end_at`.

Two operations end an active placement. A `Caseworker` may discharge one: discharge requires the placement to be `ACTIVE` (otherwise `ERR_PLACEMENT_INVALID_STATE`, 409), moves it from `ACTIVE` to `DISCHARGED`, stamps `discharged_at` with the logical clock, increments the facility's `available_beds` by one, and recomputes the subject client's `placement_status` (which falls back to `NONE` if the client has no other active placement). A `Supervisor` may review one: review likewise requires the placement to be `ACTIVE`, and when the placement is not court-authorized and the logical clock has reached or passed the placement's `expires_at`, the review expires it — moving it from `ACTIVE` to `EXPIRED`, stamping `discharged_at`, incrementing the facility's `available_beds`, and recomputing the client's `placement_status` exactly as discharge does.

### 3.5. Financial Accounts, Freezes, and Exposure

A vulnerable adult's money is tracked as one or more **FinancialAccount** records, each registered by an `IntakeWorker` or a `Caseworker` with the account holder's `client_id`, the `institution_name` of the bank or credit union, and the ledger balance `total_balance_cents`, which is a whole number of cents that is zero or greater. A new account is `ACTIVE`, its `available_balance_cents` equal to its `total_balance_cents`, and its `frozen_amount_cents`, `flagged_amount_cents`, and `restitution_cents` all zero. These four derived amounts move together with freezes and recoveries: while a freeze holds the account, `frozen_amount_cents` equals the whole `total_balance_cents` and `available_balance_cents` is zero, with the standing invariant that available plus frozen always equals the total; `flagged_amount_cents` mirrors the suspected-exploited amount recorded by the account's active freeze, dropping to zero when no active freeze remains; the account `status` reads `FROZEN` while an active freeze exists and `ACTIVE` otherwise; and `restitution_cents` is the running total of funds recovered to the account.

A `Caseworker` or a `Supervisor` places a **FinancialFreeze** by supplying the `case_id`, the `account_id` to freeze, a `flagged_amount_cents` naming the suspected-exploited amount (a whole number of cents that is at least zero and no greater than the account's `total_balance_cents`), a `freeze_start`, and a `freeze_end`. The window must be well-formed — `freeze_end` strictly after `freeze_start`, else `ERR_INVALID_DATE_RANGE` (422). Beyond that, three business gates apply in order. First, the case must actually concern financial exploitation and be under investigation: its `allegation_types` must include `FINANCIAL_EXPLOITATION` and its `status` must be `UNDER_INVESTIGATION`, or the freeze is refused with `ERR_NOT_FINANCIAL_EXPLOITATION` (422). Second, the target account must currently be `ACTIVE`; freezing an already-frozen account yields `ERR_ACCOUNT_ALREADY_FROZEN` (409). Third, a mandatory cool-down separates successive freezes on the same account: the new `freeze_start` must be at least 24 hours after the `freeze_end` of the most recent prior freeze on that account. Because the cool-down uses closed-interval semantics, a `freeze_start` that falls within the 24-hour window after that prior `freeze_end` is rejected with `ERR_FREEZE_WINDOW_OVERLAP` (409).

Creating a freeze makes it `ACTIVE` and toggles the account from `ACTIVE` to `FROZEN`: the account's `frozen_amount_cents` is set to its `total_balance_cents`, its `available_balance_cents` is set to zero, and its `flagged_amount_cents` is set to the freeze's `flagged_amount_cents`. The owning case's `frozen_account_count` is incremented and the case's exposure figures are recomputed. Lifting a freeze is a `Supervisor` action: it requires the freeze to be `ACTIVE` (otherwise `ERR_FREEZE_INVALID_STATE`, 409), moves the freeze from `ACTIVE` to `LIFTED`, stamps `lifted_at`, and toggles the account back from `FROZEN` to `ACTIVE` by resetting `frozen_amount_cents` to zero, `available_balance_cents` back to `total_balance_cents`, and `flagged_amount_cents` to zero. The case's `frozen_account_count` is decremented and its exposures are recomputed. This `ACTIVE`-to-`FROZEN`-and-back toggle allows an account to be frozen and unfrozen repeatedly across the life of a case.

A case tracks two exposure figures and a count over the freezes within it, each recomputed on every freeze creation, every lift, and every fund recovery, and each considering only freezes that are currently `ACTIVE` (lifted freezes are excluded). The `frozen_account_count` is the number of accounts holding an active freeze in the case. The `estimated_exposure_cents` is the projected worst-case exposure: the sum of the full `total_balance_cents` of every account that currently holds an active freeze in the case. The `substantiated_exposure_cents` is the verified figure: the sum of the `flagged_amount_cents` of every active freeze in the case, and it is typically strictly smaller than the estimated figure for the same accounts. The estimated figure carries legal weight at closure — when it reaches or exceeds 5,000,000 cents (fifty thousand dollars), a cross-report to an external agency becomes mandatory before the case may be closed, as described in Section 3.8.

### 3.6. Recovering and Distributing Funds

When exploited funds are recovered, a `Supervisor` distributes them across the case's frozen accounts by supplying a single `recovered_amount_cents`. The recovery is admissible only when `recovered_amount_cents` is greater than zero and the case holds at least one `ACTIVE` freeze (and each freeze's flagged amount does not exceed its account's `total_balance_cents`); a non-positive amount or a case with no active freeze is rejected with `ERR_NO_ACTIVE_FREEZE` (409). Recovery cannot run against a closed case, which surfaces as `ERR_CASE_INVALID_STATE` (409).

The distribution is a pinned-order waterfall over the accounts that currently hold an active freeze in the case, considered in ascending `created_at` order, with any ties broken by `created_at` alone — the account `id` is never used as a tie-breaker. Let the total flagged be the sum of each such account's `flagged_amount_cents`. For each account, its provisional share is the recovered amount multiplied by that account's `flagged_amount_cents`, divided by the total flagged, with the result rounded half up to a whole number of cents. The evaluation order is mandatory: each per-account share is rounded first, and only then are the rounded shares summed. Because rounding each share independently can leave the summed shares short of the recovered amount, a remainder is computed as the recovered amount minus the sum of the rounded shares, and this entire remainder is added to the single account with the largest `flagged_amount_cents`; if two accounts tie on flagged amount, the remainder goes to the one with the earliest `created_at` (again never the `id`). Finally, for every participating account, its resulting share is added both to its `restitution_cents` and to its `available_balance_cents`.

### 3.7. Guardianship Referral, Service Planning, and Cross-Reporting

Three case-level actions run alongside the investigation, each blocked once the case is closed (attempting any of them on a `CLOSED` case yields `ERR_CASE_INVALID_STATE`, 409). A `Caseworker` files a capacity/guardianship referral for the subject client; because guardianship follows a finding of impaired capacity, the referral requires the client's `capacity_status` to be `IMPAIRED`, and a referral against a client who is not impaired is rejected with `ERR_CAPACITY_NOT_IMPAIRED` (422). A successful referral sets the case's `guardianship_status` from `NONE` to `REFERRED`.

A `Caseworker` also builds the service plan by supplying the `benefit_programs` to link. Creating the plan sets the case's `service_plan_status` from `NONE` to `ACTIVE`, records the linked `benefit_programs` on the case, and advances the subject client from `SERVICES_PENDING` to `SERVICES_ACTIVE`.

Cross-reporting notifies an outside authority, such as law enforcement or a long-term-care ombudsman. A `Caseworker` or a `Supervisor` cross-reports by supplying the `recipient_agency`; the system records it as the case's `cross_report_agency` and stamps `cross_reported_at` with the logical clock. A case that has crossed the mandatory financial-exposure threshold cannot be closed until this cross-report has been filed.

### 3.8. Case Closure and the Closing Cascade

Closing a case is a `Supervisor` action and the terminal event in the lifecycle. The supervisor supplies a `closure_reason`. Two conditions gate the close. The case must be in `READY_FOR_CLOSURE` — reached only after its investigation was disposed — and closing from any other status is rejected with `ERR_CASE_INVALID_STATE` (409). Additionally, the mandatory cross-report rule is enforced here: if the case's `estimated_exposure_cents` is 5,000,000 cents or more, then its `cross_report_agency` must already be set; closing such a case with no cross-report on file is rejected with `ERR_CROSS_REPORT_REQUIRED` (422).

Once admitted, closure stamps the case's `closed_at` with the logical clock and records the supplied `closure_reason`, then fans out through a cascade. Every `ACTIVE` EmergencyPlacement in the case is discharged, moving from `ACTIVE` to `DISCHARGED` and releasing its bed back to its facility. Every `ACTIVE` FinancialFreeze in the case is lifted, moving from `ACTIVE` to `LIFTED` and unfreezing its account back to full availability. If the case's `service_plan_status` is `ACTIVE`, it is set to `TERMINATED`. Finally the subject client is transitioned to `CLOSED` and the client's `open_case_count` is decremented by one. The client's terminal `CLOSED` status can be reached from whichever lifecycle stage it occupied at closure — `UNDER_INVESTIGATION`, `SERVICES_PENDING`, or `SERVICES_ACTIVE`.

## 4. Endpoint Definitions

Operations that create a brand-new stand-alone resource return `201 Created`. Operations that modify or transition an existing resource, and read operations, return `200 OK`. The request and response payloads for each endpoint are governed by the workflows in Section 3; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reports` | File an intake report about an alleged victim | IntakeWorker |
| GET | `/reports/{id}` | Fetch one report | IntakeWorker, Supervisor, Caseworker |
| GET | `/reports` | List reports, optionally filtered by client or status | IntakeWorker, Supervisor |
| POST | `/reports/{id}/screen` | Screen a report in or out | Supervisor |
| POST | `/clients` | Create a client (alleged victim) record | IntakeWorker |
| GET | `/clients/{id}` | Fetch one client | IntakeWorker, Supervisor, Caseworker |
| POST | `/clients/{id}/capacity-determination` | Record a decisional-capacity determination | Caseworker |
| POST | `/clients/{id}/risk-assessments` | Submit a preliminary or comprehensive risk assessment | Caseworker |
| POST | `/accounts` | Register a client financial account | IntakeWorker, Caseworker |
| GET | `/accounts/{id}` | Fetch one financial account | Caseworker, Supervisor |
| GET | `/accounts` | List financial accounts, optionally filtered by client | Caseworker, Supervisor |
| POST | `/facilities` | Create a placement facility with a bed capacity | Admin |
| GET | `/facilities/{id}` | Fetch one facility (bed counts) | Admin, Caseworker, Supervisor |
| GET | `/cases/{id}` | Fetch one case | Caseworker, Supervisor, IntakeWorker |
| GET | `/cases` | List cases, optionally filtered by report, client, or status | Caseworker, Supervisor |
| POST | `/cases/{id}/close` | Close a case (cascades to placements, freezes, service plan) | Supervisor |
| POST | `/cases/{id}/cross-report` | Cross-report the case to an external agency | Caseworker, Supervisor |
| POST | `/cases/{id}/recover-funds` | Distribute recovered funds across frozen accounts | Supervisor |
| POST | `/cases/{id}/refer-guardianship` | File a capacity/guardianship referral for the subject client | Caseworker |
| POST | `/cases/{id}/service-plan` | Create the service plan and link benefit programs | Caseworker |
| POST | `/investigations` | Open an investigation on an open case | Caseworker |
| GET | `/investigations/{id}` | Fetch one investigation | Caseworker, Supervisor |
| GET | `/investigations` | List investigations, optionally filtered by case | Caseworker, Supervisor |
| POST | `/investigations/{id}/submit-findings` | Submit findings (requires a comprehensive risk assessment) | Caseworker |
| POST | `/investigations/{id}/return` | Return findings for re-investigation | Supervisor |
| POST | `/investigations/{id}/dispose` | Dispose the investigation with a final disposition | Supervisor |
| POST | `/placements` | Create an emergency protective placement | Caseworker |
| GET | `/placements/{id}` | Fetch one placement | Caseworker, Supervisor |
| GET | `/placements` | List placements, optionally filtered by case, facility, or client | Caseworker, Supervisor |
| POST | `/placements/{id}/discharge` | Discharge an active placement | Caseworker |
| POST | `/placements/{id}/review` | Review an active placement; expire it if past the emergency cap | Supervisor |
| POST | `/freezes` | Place a financial-exploitation freeze on a client account | Caseworker, Supervisor |
| GET | `/freezes/{id}` | Fetch one freeze | Caseworker, Supervisor |
| GET | `/freezes` | List freezes, optionally filtered by case or account | Caseworker, Supervisor |
| POST | `/freezes/{id}/lift` | Lift an active freeze | Supervisor |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | Admin |

## 5. Error Code Catalogue

The trigger conditions for these errors are described in the relevant narratives of Sections 2 and 3. This catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 |
| `ERR_PLACEMENT_NOT_FOUND` | 404 |
| `ERR_FREEZE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_REPORT_INVALID_STATE` | 409 |
| `ERR_CASE_INVALID_STATE` | 409 |
| `ERR_INVESTIGATION_INVALID_STATE` | 409 |
| `ERR_PLACEMENT_INVALID_STATE` | 409 |
| `ERR_FREEZE_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_ALREADY_FROZEN` | 409 |
| `ERR_STALE_CLIENT_VERSION` | 412 |
| `ERR_COMPREHENSIVE_ASSESSMENT_REQUIRED` | 409 |
| `ERR_CLIENT_NOT_ELIGIBLE_FOR_PLACEMENT` | 422 |
| `ERR_CAPACITY_NOT_IMPAIRED` | 422 |
| `ERR_NOT_FINANCIAL_EXPLOITATION` | 422 |
| `ERR_FREEZE_WINDOW_OVERLAP` | 409 |
| `ERR_NO_BED_AVAILABLE` | 409 |
| `ERR_NO_ACTIVE_FREEZE` | 409 |
| `ERR_CROSS_REPORT_REQUIRED` | 422 |

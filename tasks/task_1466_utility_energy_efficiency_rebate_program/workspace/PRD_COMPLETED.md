# Utility EE Rebate API — Product Requirements Document

## 1. Introduction

Electric and gas utilities run demand-side management programs under regulatory mandate: each program year carries a capped incentive budget and a quantified energy-savings goal, and the utility pays rebates to the contractors — **trade allies** — who install qualifying efficiency measures at customer premises. The money involved and the regulator's oversight make these programs audit-heavy by nature. Every dollar committed against the cap must be traceable to a specific application, every claimed kilowatt-hour must survive inspection and verification, and the savings finally reported to the regulator must be defensibly trued-up by independent evaluation.

This document specifies the API that administers such a program end to end. It governs the program-year lifecycle from draft through regulatory reporting, the measure catalog that prices incentives and deemed savings, trade-ally enrollment and performance standing, and the full application pipeline — drafting, line-item composition, submission with budget-pacing and fraud screening, inspection sampling, verification of deemed versus measured savings, approval under segregation of duties, and payment. Five roles share the workload with deliberately separated powers, and a set of derived counters on the program year keeps budget consumption and savings attainment continuously visible to the utility and its regulator alike.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly five roles: `ProgramAdministrator`, `TradeAlly`, `VerificationInspector`, `PaymentProcessor`, and `RegulatorAnalyst`. A request with missing or malformed headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a well-authenticated request whose role is not authorized for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `TradeAlly`, `X-User-ID` is the `id` of the acting trade-ally record; ownership checks on any resource that references a trade ally compare the resource's `trade_ally_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `ProgramAdministrator`, `VerificationInspector`, `PaymentProcessor`, or `RegulatorAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — most notably as `verified_by` on an application at verification time, where it later anchors the segregation-of-duties check — but does not compare it to any entity's `id`.

Read access is broad: all five roles may list and retrieve every resource type. Write access is partitioned per §4, and the business narratives in §3 name the acting role for each operation.

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
- The same envelope covers routing-level failures: a request matching no defined route is answered `ERR_INVALID_REQUEST` (HTTP 404), a request using an unsupported method on a defined route is answered `ERR_INVALID_REQUEST` (HTTP 405), and an unexpected server failure is answered `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` caps the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of records and defaults to 0. Unless otherwise stated, list endpoints return resources sorted by `created_at` in ascending order, with ties broken by creation order (earliest-created first). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Individual list endpoints accept additional filter parameters, named where each resource is introduced in §3; a filter value that matches no record simply yields an empty page and is not an error (the single validated exception is the `is_active` filter of §3.1).

### 2.4. The Logical Program Clock

All date- and time-sensitive logic in the system reads a server-side **logical clock**, never wall-clock time: the invoice eligibility window of §3.4, the fraud-detection windows, the `opened_at` and `submitted_at` stamps, and the `completed_on` date recorded at inspection completion all derive from it. Before any operator intervention the logical clock reads exactly `2026-08-01T00:00:00Z` — a fixed startup default — and the server must not fall back to wall-clock time under any circumstances. A `ProgramAdministrator`-only capability sets the clock to a caller-supplied `to_iso8601` timestamp — unconditionally, with no monotonicity check, reading a timestamp that carries no explicit offset as UTC — and answers `200 OK` with the resulting `current_utc`.

### 2.5. Common Resource Properties

All primary resources — program years, measures, trade allies, applications, line items, inspections, and evaluation adjustments — carry a standard system-managed quartet: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, in the same format, refreshed on every mutation; and `version`, an integer starting at 1 that increments by one on every mutation of the resource, including mutations driven by cascades from other resources.

Two resources are deliberately lighter. A savings claim and a fraud flag each carry only `id` and `created_at`; `updated_at` and `version` are absent from both, and fraud flags are immutable once persisted.

Shared vocabularies used throughout this document: an inspection's `inspection_kind` is `PRE` (pre-installation) or `POST` (post-installation); its `outcome` moves from `PENDING` to `PASSED` or `FAILED`. A savings claim's `claim_method` is `DEEMED` or `MEASURED`. A trade ally's `standing_tier` is `PREFERRED`, `STANDARD`, or `PROBATION`, and its `enroll_status` walks `PENDING` → `ACTIVE`, with `SUSPENDED` and terminal `TERMINATED` as the disciplinary states. An application's `auto_flag_status` is `CLEAR` or `SUSPECT`, and a line item's `pacing_tier_at_submit` is `STANDARD_TIER`, `MID_TIER`, or `HIGH_TIER`. A program year's `status` walks `DRAFT` → `OPEN` → `CLOSED` → `REPORTED`; an application's `status` runs `DRAFT` → `SUBMITTED` → `PRE_INSPECTION` → `POST_INSPECTION` → `VERIFIED` → `APPROVED` → `PAID`, with `REJECTED` and `WITHDRAWN` reachable from several states as §3 details.

### 2.6. Program Ledger Consistency and Cascading Counters

Each program year carries five derived counters that the server maintains continuously — clients never write them. `committed_cents` is the sum of `incentive_total_cents` over the year's applications currently in `SUBMITTED`, `PRE_INSPECTION`, `POST_INSPECTION`, `VERIFIED`, or `APPROVED`; it rises at submission and is released when an application is rejected, withdrawn, or paid. `paid_cents` is the sum of `incentive_total_cents` over the year's applications in `PAID`. `reported_kwh` is the sum of `final_kwh` over the year's applications in `VERIFIED`, `APPROVED`, or `PAID`. `adjusted_kwh` and `goal_attainment_pct` derive from `reported_kwh` together with the year's evaluation adjustments, per §3.7.

Cascades that touch these counters are first-class mutations of the program-year resource: each one refreshes `updated_at` and increments the program year's `version` by one. A client holding a previously observed version will therefore be refused a configuration update (§2.8) even when the version advanced because of activity on a child application rather than a direct edit. In the opposite direction, line items are independent records: adding a line item to an application does not increment the application's `version`.

### 2.7. Money, Energy, and Rounding Discipline

Monetary amounts are integer cents end to end — `budget_cap_cents`, `base_rate_cents`, `incentive_cents`, `incentive_total_cents`, `committed_cents`, and `paid_cents` are all whole-cent figures; no fractional cents appear anywhere in the API. Where a multiplication would produce a fractional cent — the per-line incentive pricing of §3.4 — each line is rounded half-up to a whole cent first, and only then are the integer line amounts summed. Summing unrounded values and rounding once at the end is explicitly forbidden, because the two orders can disagree by a cent on fractional inputs.

Energy figures are whole kilowatt-hours with no rounding. Two derived figures use explicit integer rounding in opposite directions: the program's committed percentage (which selects the pacing tier) and `adjusted_kwh` are computed by rounding down — floor — to a whole number, while `goal_attainment_pct` and a trade ally's `performance_score` are rounded half-up to whole numbers.

### 2.8. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: the program-year configuration update. Its request body must carry `expected_program_year_version` — a non-optional field — holding the program year's `version` as the client last observed it. If the server-side `version` has since advanced, whether by a prior configuration edit or by any of the ledger cascades described in §2.6, the update is rejected as stale with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a configuration it has not observed. No other endpoint accepts a version field.

### 2.9. Request Validation Order and Resource Resolution

Incoming requests are validated in a fixed global order. First comes header authentication, then role authorization (§2.1). Third, every identifier in the request path must resolve to an existing resource of the appropriate type, yielding the resource-specific not-found error: `ERR_PROGRAM_YEAR_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ALLY_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_SAVINGS_CLAIM_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, or `ERR_FRAUD_FLAG_NOT_FOUND` (all HTTP 404). Fourth, foreign keys supplied in a request body — `program_year_id`, `trade_ally_id`, `measure_id`, `application_id`, `line_item_id` — must likewise resolve, drawing on the same 404 family according to the offending field.

Fifth comes the program-open gate: while a program year is in any status other than `OPEN`, eleven operations are refused with `ERR_PROGRAM_NOT_OPEN` (HTTP 409) — creating an application, adding a line item, attaching a savings claim, submitting an application, scheduling a pre-installation inspection, completing an inspection, verifying, approving, rejecting, paying, and withdrawing. Scheduling a post-installation inspection is not separately gated: an application can only reach `POST_INSPECTION` while its program year is open, and the close transition is blocked while any application remains there. Sixth, the target entity's current state must match the transition's required from-state (`ERR_INVALID_STATE`, HTTP 409). The remaining business rules then run in the endpoint-specific order given in §3. Ownership enforcement (`ERR_FORBIDDEN`) on trade-ally-initiated operations ranks after the business-content checks, so a caller who is not the owning ally still sees, for example, an over-cap rejection rather than an ownership rejection. Independent of this ordering, a structurally malformed request — a missing required field, a wrong-typed value, or an out-of-range scalar — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Program Years and the Measure Catalog

A `ProgramAdministrator` opens a new program year by supplying a `program_code` (unique across all program years), a human-readable `program_year_label` such as "PY2026", the `budget_cap_cents` ceiling as a positive integer number of cents, and the regulatory `savings_goal_kwh` as a positive integer number of kilowatt-hours. The year starts in `DRAFT` with every derived counter at zero and `version` 1. A duplicate `program_code` is refused with `ERR_DUPLICATE_UNIQUE_FIELD` (HTTP 409).

While the year is in `DRAFT`, the administrator builds its measure catalog; catalog creation is not locked to `DRAFT`, however — a measure may be created under a program year in any status. Each measure is created under a `program_year_id` with a `measure_code` unique within that program year, a display `measure_name`, a `base_rate_cents` price paid per installed unit, and the `deemed_kwh_per_unit` annual savings the catalog credits per unit installed; both `base_rate_cents` and `deemed_kwh_per_unit` are non-negative integers, zero permitted. A measure flagged `requires_post_inspection` (default `false`) marks installations that are expected to undergo a post-installation inspection before verification; `is_active` (default `true`) controls whether the measure may appear on new applications. Reusing a `measure_code` within the same program year is again `ERR_DUPLICATE_UNIQUE_FIELD`. Catalog listings accept `program_year_id` and `is_active` filters — the `is_active` filter takes the case-insensitive strings `true` and `false`, any other value being `ERR_INVALID_REQUEST` (HTTP 400); program-year listings accept a `status` filter.

Opening the year — the `DRAFT` → `OPEN` transition, performed by a `ProgramAdministrator` — requires a non-empty active catalog, and its checks run in a fixed order: the state check first (a year not in `DRAFT` yields `ERR_INVALID_STATE`), then the catalog check (no active measure yields `ERR_NO_ACTIVE_MEASURES`, HTTP 422). A successful open stamps `opened_at` with the current logical-clock timestamp and increments the year's `version`; the date component of `opened_at` later anchors the invoice eligibility window of §3.4.

A `ProgramAdministrator` may also update a year's mutable configuration — `budget_cap_cents` and `savings_goal_kwh` — subject to the optimistic-concurrency rule of §2.8: the request must carry `expected_program_year_version`, a mismatch with the current `version` is `ERR_STALE_VERSION`, and a successful update also recomputes `adjusted_kwh` and `goal_attainment_pct` per §3.7 against the new configuration before incrementing `version` and refreshing `updated_at`.

### 3.2. Trade Ally Enrollment, Standing, and Performance

Contractors join the network when a `ProgramAdministrator` enrolls them with an `ally_name` and a state-issued `license_number` (unique across the network; duplicates yield `ERR_DUPLICATE_UNIQUE_FIELD`). A new ally starts with `enroll_status` `PENDING`, `performance_score` 100, `standing_tier` `STANDARD`, and `version` 1. Activation moves `PENDING` → `ACTIVE`; suspension moves `ACTIVE` → `SUSPENDED`; reinstatement returns `SUSPENDED` → `ACTIVE`; termination is the terminal `TERMINATED` state. Each of these transitions requires the matching current state — a mismatched call yields `ERR_INVALID_STATE` — and increments the ally's `version`. Termination from `ACTIVE` carries one further guard, evaluated after the state check: it is refused with `ERR_ALLY_HAS_OPEN_APPLICATIONS` (HTTP 409) while the ally still has any application in `DRAFT`, `SUBMITTED`, `PRE_INSPECTION`, `POST_INSPECTION`, or `VERIFIED`. Termination from `SUSPENDED` requires only the state precondition. Ally listings filter by `enroll_status` and `standing_tier`.

Performance standing is earned on inspection outcomes. Whenever an inspection is completed — pass or fail, pre- or post-installation — the installing ally's `performance_score` is recomputed across every completed inspection belonging to that ally's applications, in any program year: one hundred times the number of `PASSED` inspections divided by the number of completed inspections (those `PASSED` or `FAILED`), rounded half-up to a whole number. An ally with no completed inspections keeps the default score of 100. The `standing_tier` follows the score mechanically: `PREFERRED` at ninety or above, `STANDARD` at seventy or above, and `PROBATION` below seventy. The recomputation mutates the ally record — incrementing `version` and refreshing `updated_at` — only when the score or tier actually changes; a recomputation that reproduces the standing values leaves the record untouched. Standing is informational within the API; what gates submission is `enroll_status`, as §3.4 describes.

### 3.3. Building an Application: Drafts, Line Items, and Savings Claims

A trade ally initiates a rebate application with a payload naming the `program_year_id` and the `trade_ally_id`, plus the customer's `customer_account_number`, the installation `service_address`, and the contractor's `invoice_number` and `invoice_date` (an ISO 8601 calendar date, `YYYY-MM-DD`). The acting ally must be the applicant: the body's `trade_ally_id` must equal the `X-User-ID` header, or the create is refused with `ERR_FORBIDDEN`. Both foreign keys must resolve per §2.9, and the program-open gate applies. The new application starts in `DRAFT` with `incentive_total_cents`, `claimed_kwh`, `final_kwh`, and `risk_score` at zero, `inspection_required` false, `auto_flag_status` `CLEAR`, and `version` 1. Application listings accept `program_year_id`, `trade_ally_id`, `status`, and `auto_flag_status` filters.

While the application is in `DRAFT`, the owning ally composes it. Each line item names an `application_id` and a `measure_id` and records the `quantity` installed as a positive integer; a new line item's `pacing_tier_at_submit`, `incentive_cents`, `claimed_kwh`, `measured_kwh`, and `final_kwh` are all null until submission and verification populate them. Line items are independent records, so adding one does not increment the application's `version`. The ally may also attach a savings claim to a line item — one claim per line, with a second claim on the same line refused as `ERR_INVALID_REQUEST` (HTTP 400) — choosing the `claim_method`: `DEEMED` to accept the catalog's per-unit savings, or `MEASURED` to assert metered savings, in which case both `pre_annual_kwh` and `post_annual_kwh` are required. When supplied, `pre_annual_kwh` and `post_annual_kwh` are non-negative integers; on a `DEEMED` claim both are optional and stored as given. A claim must be in place before verification, and attachment remains possible until then: it is accepted while the application is in `DRAFT`, `SUBMITTED`, `PRE_INSPECTION`, or `POST_INSPECTION`, and refused with `ERR_INVALID_STATE` (HTTP 409) from `VERIFIED` onward. Adding a line item and attaching a savings claim are restricted to the owning ally in the same way as the create: a `trade_ally_id`-versus-`X-User-ID` mismatch on the parent application yields `ERR_FORBIDDEN`. Line-item listings filter by `application_id` and `measure_id`; savings-claim listings by `line_item_id` and `claim_method`.

### 3.4. Submission: Pacing Tiers, Incentive Pricing, and Fraud Screening

Submission — the `DRAFT` → `SUBMITTED` transition, performed by the owning trade ally — is the system's enforcement chokepoint, and its checks run in a fixed, observable order. After authentication, authorization, and resource resolution: the program-open gate (`ERR_PROGRAM_NOT_OPEN`); the `DRAFT` state check (`ERR_INVALID_STATE`); ally standing, requiring the installing ally to be `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409); catalog currency, requiring every line item's measure to be active (`ERR_MEASURE_INACTIVE`, HTTP 409); presence of at least one line item (`ERR_NO_LINE_ITEMS`, HTTP 422); the invoice eligibility window; the budget-cap check; and only then the ownership comparison (`ERR_FORBIDDEN`). An over-cap submission by a non-owning caller therefore surfaces `ERR_PROGRAM_CAP_EXCEEDED`, not an ownership error.

The invoice eligibility window is anchored on the program year: `invoice_date` must fall no earlier than ninety days before the date component of the year's `opened_at` and no later than the current logical-clock date, inclusive on both ends. Anything outside the window is refused with `ERR_INVOICE_DATE_OUT_OF_RANGE` (HTTP 422).

Pricing uses budget-pacing tiers. At the moment of submission — before the application's own incentive is added to the year's committed total — the system computes the program's committed percentage: one hundred times `committed_cents` divided by `budget_cap_cents`, rounded down to a whole percent. Each line is then pinned to a `pacing_tier_at_submit`: below fifty percent, `STANDARD_TIER`, priced at the full base rate; at least fifty but below eighty percent, `MID_TIER`, priced at eighty percent of the base rate (a tier factor of 0.80); at eighty percent or above, `HIGH_TIER`, priced at half the base rate (a tier factor of 0.50). The boundaries are inclusive on the lower edge — a committed percentage of exactly fifty selects `MID_TIER`, and exactly eighty selects `HIGH_TIER`. Each line's `incentive_cents` is then the measure's `base_rate_cents` multiplied by the line's `quantity` and by the pinned tier factor, rounded half-up to a whole cent; per §2.7 the rounding happens per line before any summation. A line's `claimed_kwh` is the measure's `deemed_kwh_per_unit` multiplied by its `quantity`. The application's `incentive_total_cents` is the sum of the per-line incentive amounts, and its `claimed_kwh` is the sum of the per-line energy figures; both totals are locked at submission and never recomputed afterward.

The budget-cap check compares the freshly priced total against headroom: the sum of this application's per-line `incentive_cents` — each priced at the pacing tier in force at this moment — must not exceed the year's remaining uncommitted budget, that is, `budget_cap_cents` minus the current `committed_cents`. A submission that would push committed spending past the cap fails with `ERR_PROGRAM_CAP_EXCEEDED` (HTTP 402).

Submission also decides the inspection obligation, `inspection_required`, through two rules that OR together. Under index-based sampling, the system counts the applications in the same program year that reached `SUBMITTED` or beyond strictly before this one — ranked by `submitted_at`, with ties broken by `created_at` ascending — and requires inspection when this application's ordinal position in that sequence is a multiple of five: the fifth submission, the tenth, and so on. Under the large-claim override, any application whose `claimed_kwh` reaches 10,000 kilowatt-hours requires inspection regardless of position.

Finally, submission runs the fraud screen. The screen accumulates a `risk_score` from up to three rules and persists one immutable fraud flag per triggered rule, each recording its `application_id`, a `flag_kind`, the rule's `weight`, and a human-readable `detail`. Rule one, `SAME_SERVICE_ADDRESS` (weight 40): consider the trailing thirty-day window anchored on this application's own `invoice_date` — a window that includes the date thirty days before the invoice date and excludes the invoice date itself, so the current application's invoice date is not inside its own window. If any *other* application exists in the same program year with the identical `service_address`, in any of `SUBMITTED`, `PRE_INSPECTION`, `POST_INSPECTION`, `VERIFIED`, `APPROVED`, or `PAID`, and with an `invoice_date` inside that window, forty points are assessed. Rule two, `ALLY_BURST` (weight 25): count the applications that share this application's `trade_ally_id` and `program_year_id`, sit in one of those same six statuses, and have a `submitted_at` date inside the trailing seven-day window ending on the current logical-clock date — both endpoints inclusive, and including the application now being submitted. A count of five or more adds twenty-five points. Rule three, `INVOICE_GAP_SMALL` (weight 15): if the invoice is recent — the gap between the current logical-clock date and `invoice_date` is no more than seven days, equivalently the invoice date falls within the closed seven-day window ending today — fifteen points are assessed. When the accumulated `risk_score` reaches fifty, the application's `auto_flag_status` becomes `SUSPECT`; otherwise it remains `CLEAR`. Fraud-flag listings filter by `application_id` and `flag_kind`.

A successful submission stamps `submitted_at` from the logical clock, adds the application's `incentive_total_cents` to the program year's `committed_cents`, and increments both the application's and the program year's `version`; pinning the pricing fields is likewise a mutation of each line item, so every line's `version` increments at submission (and again at verification, when its `final_kwh` is finalized).

### 3.5. Inspections and Verification

An application flagged `inspection_required` cannot be verified directly; a `ProgramAdministrator` first schedules a pre-installation inspection for it, supplying the `scheduled_on` date (an ISO 8601 calendar date, `YYYY-MM-DD`). Scheduling requires the application to be in `SUBMITTED` — the state check runs first — and `inspection_required` to be true; attempting it on an unflagged application yields `ERR_INSPECTION_NOT_REQUIRED` (HTTP 409). Scheduling creates the inspection record (pre-installation kind, `outcome` `PENDING`), moves the application `SUBMITTED` → `PRE_INSPECTION`, and increments the application's `version`. Once the application reaches `POST_INSPECTION`, the administrator may additionally schedule a post-installation inspection, which creates a second inspection record (post-installation kind, `PENDING`) and leaves the application's status unchanged; scheduling one is only accepted while the application sits in `POST_INSPECTION`.

A `VerificationInspector` completes a `PENDING` inspection by reporting an `outcome` of `PASSED` or `FAILED`; a `FAILED` outcome must carry a non-empty `fail_reason`, which stays null on a pass. The completion checks run in a fixed order: the program-open gate, then the parent application's state must permit the completion — `PRE_INSPECTION` for a pre-installation inspection, `POST_INSPECTION` for a post-installation one (`ERR_INVALID_STATE`) — then the fail-reason requirement (`ERR_FAIL_REASON_REQUIRED`, HTTP 422), and only then the guard against double completion (`ERR_INSPECTION_ALREADY_COMPLETED`, HTTP 409). Completion stamps `completed_on` with the current logical-clock date, increments the inspection's `version`, and recomputes the installing ally's performance per §3.2.

Completion cascades depend on kind and outcome. A passed pre-installation inspection moves the parent application `PRE_INSPECTION` → `POST_INSPECTION`. A passed post-installation inspection leaves the application in `POST_INSPECTION`. A failed inspection of either kind moves the parent application to `REJECTED`, releases its `incentive_total_cents` from the program year's `committed_cents`, and increments the program year's `version` alongside the application's and the inspection's. Inspection listings filter by `application_id`, `inspection_kind`, and `outcome`.

Verification — performed by a `VerificationInspector` — has two entry paths with their own gates, and its measured-input validation runs before either inspection-obligation check: for every line whose savings claim is `MEASURED`, both `pre_annual_kwh` and `post_annual_kwh` must be present, with the post-retrofit figure strictly below the pre-retrofit figure, or verification is refused with `ERR_INVALID_MEASURED_INPUT` (HTTP 422). From `SUBMITTED`, direct verification additionally requires `inspection_required` to be false; otherwise the refusal is `ERR_INSPECTION_REQUIRED_OUTSTANDING` (HTTP 409). From `POST_INSPECTION`, verification additionally requires a passed post-installation inspection on the application; otherwise the refusal is `ERR_POST_INSPECTION_NOT_PASSED` (HTTP 409). Either path lands the application in `VERIFIED`.

Verification finalizes savings line by line. A line with no savings claim, or a `DEEMED` claim, keeps its submission-pinned value: its `final_kwh` equals its `claimed_kwh`. A `MEASURED` line instead takes the metered delta — its `measured_kwh` is the claim's `pre_annual_kwh` minus its `post_annual_kwh`, and the line's `final_kwh` equals that `measured_kwh` — while `measured_kwh` remains unset (null) on deemed lines. Each claim's `computed_kwh` is persisted equal to its line's finalized value: for `DEEMED`, the line's `claimed_kwh`; for `MEASURED`, the pre-minus-post delta. The application's `final_kwh` is the sum across its lines and is locked once the application reaches `VERIFIED`. Verification also records the acting inspector's `X-User-ID` as `verified_by`, adds the application's `final_kwh` to the program year's `reported_kwh`, recomputes `adjusted_kwh` and `goal_attainment_pct` per §3.7, and increments both resources' versions.

### 3.6. Approval, Payment, Rejection, and Withdrawal

A verified application awaits approval by a `ProgramAdministrator`. Approval's checks run in order — the program-open gate, the `VERIFIED` state check, then the fraud hold, then segregation of duties — so a `SUSPECT` application is refused with `ERR_FRAUD_SUSPECT_HOLD` (HTTP 409) even when the approver would also trip the segregation rule. Segregation of duties forbids self-approval across the verification boundary: the approver's `X-User-ID` must differ from the application's `verified_by`, or the approval is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Approval moves the application `VERIFIED` → `APPROVED` and increments its `version`; it does not move money.

Payment is the finance step, performed by a `PaymentProcessor` on an `APPROVED` application: the application moves `APPROVED` → `PAID`, its `incentive_total_cents` leaves the year's `committed_cents` and lands in `paid_cents`, and both resources' versions increment. `PAID` is terminal.

Rejection by a `ProgramAdministrator` is available from `SUBMITTED` or `VERIFIED` — any other state yields `ERR_INVALID_STATE`. Either way, the application's `incentive_total_cents` is released from the year's `committed_cents`. Rejecting a previously verified application additionally subtracts its `final_kwh` from the year's `reported_kwh` and recomputes `adjusted_kwh` and `goal_attainment_pct`. Both resources' versions increment, and `REJECTED` is terminal.

Withdrawal is the owning trade ally's escape hatch, available from `DRAFT` or `SUBMITTED`; the acting ally's `X-User-ID` must equal the application's `trade_ally_id`, or the call is refused with `ERR_FORBIDDEN`. Withdrawing from `DRAFT` touches no ledger, since nothing was ever committed; withdrawing from `SUBMITTED` releases the committed incentive exactly as a rejection does, and the year's `version` increments alongside the application's. `WITHDRAWN` is terminal alongside `REJECTED` and `PAID`.

### 3.7. Program Close-Out, Evaluation, and Regulatory Reporting

When intake is over, a `ProgramAdministrator` closes the year. Closing requires the `OPEN` state — the state check runs first — and a quiet pipeline: no application of the year may remain in `SUBMITTED`, `PRE_INSPECTION`, `POST_INSPECTION`, or `VERIFIED`, or the close is refused with `ERR_OPEN_APPLICATIONS_REMAIN` (HTTP 409). Closing settles every still-`APPROVED` application automatically, in `created_at` ascending order: each moves to `PAID`, its `incentive_total_cents` shifting from `committed_cents` to `paid_cents` exactly as a manual payment would. The year's `status` becomes `CLOSED` and its `version` increments.

Evaluation is the regulator's instrument. Once a year has been closed — or is already reported — a `RegulatorAnalyst` records an evaluation adjustment against a `program_year_id`, supplying the `realization_rate_pct` as a whole number from 0 to 100, the `effective_on` date (an ISO 8601 calendar date, `YYYY-MM-DD`) from which the adjustment applies, and optional free-text `notes`; attempting to record an adjustment against a year not yet `CLOSED` is refused with `ERR_INVALID_STATE` (HTTP 409). The year's evaluated savings derive from the *latest* adjustment: the one with the greatest `effective_on`, with ties on `effective_on` broken in favor of the earliest-created row. With no adjustment at all, `adjusted_kwh` simply equals `reported_kwh`; otherwise `adjusted_kwh` is `reported_kwh` multiplied by the latest adjustment's `realization_rate_pct`, divided by one hundred, and rounded down to a whole kilowatt-hour. `goal_attainment_pct` is one hundred times `adjusted_kwh` divided by `savings_goal_kwh`, rounded half-up to a whole percent. Creating an adjustment triggers this recomputation immediately — and a newly created row governs only if its `effective_on` makes it the latest under the rule above — with the year's `version` incremented and `updated_at` refreshed only when the recomputation actually changes `adjusted_kwh` or `goal_attainment_pct`. Adjustment listings filter by `program_year_id`.

The final act belongs to the `RegulatorAnalyst`: moving a `CLOSED` year to `REPORTED`. The state check runs first, then the evidentiary check — at least one evaluation adjustment must exist for the year, else the transition is refused with `ERR_NO_EVALUATION_ADJUSTMENT` (HTTP 422). The transition recomputes `adjusted_kwh` from the latest adjustment and recomputes `goal_attainment_pct`, exactly as above, and increments the year's `version`. `REPORTED` is terminal, and the year's counters thereafter stand as the regulatory record.

## 4. Endpoint Definitions

Operations that create a new resource — program years, measures, trade allies, applications, line items, savings claims, scheduled inspections, and evaluation adjustments — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`, as do all reads; the clock-setting capability likewise returns `200 OK`. Request payloads, response payloads, and side effects are as specified in §2 and §3; this table is the routing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramAdministrator |
| POST | `/program-years` | Create a new program year | ProgramAdministrator |
| GET | `/program-years` | List program years | Any authenticated role |
| GET | `/program-years/{id}` | Get a single program year | Any authenticated role |
| PUT | `/program-years/{id}` | Update program-year configuration (OCC-guarded) | ProgramAdministrator |
| POST | `/program-years/{id}/open` | Open a DRAFT program year | ProgramAdministrator |
| POST | `/program-years/{id}/close` | Close an OPEN year; auto-pays APPROVED applications | ProgramAdministrator |
| POST | `/program-years/{id}/report` | Move a CLOSED year to REPORTED | RegulatorAnalyst |
| POST | `/measures` | Create a measure in a program-year catalog | ProgramAdministrator |
| GET | `/measures` | List measures | Any authenticated role |
| GET | `/measures/{id}` | Get a single measure | Any authenticated role |
| POST | `/trade-allies` | Enroll a trade ally (starts PENDING) | ProgramAdministrator |
| GET | `/trade-allies` | List trade allies | Any authenticated role |
| GET | `/trade-allies/{id}` | Get a trade ally | Any authenticated role |
| POST | `/trade-allies/{id}/activate` | Activate a PENDING trade ally | ProgramAdministrator |
| POST | `/trade-allies/{id}/suspend` | Suspend an ACTIVE trade ally | ProgramAdministrator |
| POST | `/trade-allies/{id}/reinstate` | Reinstate a SUSPENDED trade ally | ProgramAdministrator |
| POST | `/trade-allies/{id}/terminate` | Terminate an ACTIVE or SUSPENDED trade ally | ProgramAdministrator |
| POST | `/applications` | Create a DRAFT rebate application | TradeAlly |
| GET | `/applications` | List applications | Any authenticated role |
| GET | `/applications/{id}` | Get a single application | Any authenticated role |
| POST | `/applications/{id}/submit` | Submit a DRAFT application | TradeAlly |
| POST | `/applications/{id}/schedule-pre-inspection` | Schedule a pre-installation inspection | ProgramAdministrator |
| POST | `/applications/{id}/schedule-post-inspection` | Schedule a post-installation inspection | ProgramAdministrator |
| POST | `/applications/{id}/verify` | Verify an application; finalize savings | VerificationInspector |
| POST | `/applications/{id}/approve` | Approve a VERIFIED application | ProgramAdministrator |
| POST | `/applications/{id}/pay` | Pay an APPROVED application | PaymentProcessor |
| POST | `/applications/{id}/reject` | Reject a SUBMITTED or VERIFIED application | ProgramAdministrator |
| POST | `/applications/{id}/withdraw` | Withdraw a DRAFT or SUBMITTED application | TradeAlly |
| POST | `/line-items` | Add a line item to a DRAFT application | TradeAlly |
| GET | `/line-items` | List line items | Any authenticated role |
| GET | `/line-items/{id}` | Get a single line item | Any authenticated role |
| POST | `/savings-claims` | Attach a savings claim to a line item | TradeAlly |
| GET | `/savings-claims` | List savings claims | Any authenticated role |
| GET | `/savings-claims/{id}` | Get a savings claim | Any authenticated role |
| GET | `/inspections` | List inspections | Any authenticated role |
| GET | `/inspections/{id}` | Get an inspection | Any authenticated role |
| POST | `/inspections/{id}/complete` | Complete a PENDING inspection | VerificationInspector |
| GET | `/fraud-flags` | List fraud flags | Any authenticated role |
| GET | `/fraud-flags/{id}` | Get a fraud flag | Any authenticated role |
| POST | `/evaluation-adjustments` | Record an evaluation adjustment | RegulatorAnalyst |
| GET | `/evaluation-adjustments` | List evaluation adjustments | Any authenticated role |
| GET | `/evaluation-adjustments/{id}` | Get an evaluation adjustment | Any authenticated role |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_PROGRAM_YEAR_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ALLY_NOT_FOUND` | 404 Not Found |
| `ERR_MEASURE_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_SAVINGS_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_FRAUD_FLAG_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_ALLY_NOT_ACTIVE` | 409 Conflict |
| `ERR_MEASURE_INACTIVE` | 409 Conflict |
| `ERR_NO_LINE_ITEMS` | 422 Unprocessable Entity |
| `ERR_INVOICE_DATE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_PROGRAM_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_INVALID_MEASURED_INPUT` | 422 Unprocessable Entity |
| `ERR_FRAUD_SUSPECT_HOLD` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_ALLY_HAS_OPEN_APPLICATIONS` | 409 Conflict |
| `ERR_OPEN_APPLICATIONS_REMAIN` | 409 Conflict |
| `ERR_NO_EVALUATION_ADJUSTMENT` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_MEASURES` | 422 Unprocessable Entity |
| `ERR_FAIL_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INSPECTION_ALREADY_COMPLETED` | 409 Conflict |
| `ERR_INSPECTION_NOT_REQUIRED` | 409 Conflict |
| `ERR_INSPECTION_REQUIRED_OUTSTANDING` | 409 Conflict |
| `ERR_POST_INSPECTION_NOT_PASSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_UNIQUE_FIELD` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INTERNAL` | 500 Internal Server Error |

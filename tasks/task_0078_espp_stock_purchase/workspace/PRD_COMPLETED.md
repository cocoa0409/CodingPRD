# Espp Stock Purchase API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for an Employee Stock Purchase Plan (ESPP) administration API — a backend system that lets an employer operate a tax-qualified Section 423 stock purchase program end to end. The system manages the full arc of a plan: configuring discount and contribution policy, opening offering (grant) periods of six to twenty-four months, collecting payroll withholdings from enrolled employees, running purchase batches that convert accumulated cash into discounted shares, and tracking the eventual sale of those shares for tax-character classification.

The plan's defining characteristics are regulatory. Internal Revenue Code Section 423 imposes hard ceilings — a contribution rate no greater than fifteen percent, a maximum purchase discount of fifteen percent, a twenty-five-thousand-dollar annual accrual limit measured at grant-date fair market value, and a bar on five-percent owners — and the system exists to make those ceilings auditable rather than aspirational. Two distinct compliance roles share custody of every purchase: one configures and executes the buy, the other independently certifies the accrual sweep and issues the IRS Form 3922 paperwork, and the two may never be the same person for the same batch. When employees later sell their shares, the system must determine whether each sale is a **qualifying** or **disqualifying** disposition and compute the resulting ordinary income and capital gain under the divergent rules that attach to each.

The API is therefore both a ledger and a compliance engine. Monetary amounts are tracked in integer cents to avoid rounding drift, share counts are always whole numbers, and concurrency-sensitive operations such as running a purchase batch are guarded so that a stale client cannot replay a settled buy. The sections below define the global contracts every endpoint shares, the cross-cutting fiscal and safety principles, and the detailed business workflows that govern each resource's lifecycle.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than participant self-registration must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or carries an unrecognized value, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the role named in `X-User-Role` is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly three roles, spelled precisely as follows:

- **`PlanAdministrator`** — configures the plan, offerings, and purchase batches; registers and terminates employees; records payroll contributions; and executes the buy. When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow demands it but does not compare it to any entity's `id`.
- **`ComplianceOfficer`** — independently certifies the accrual sweep for a batch and issues the Form 3922 paperwork; may not execute a buy they certified. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server records it as `certified_by_user_id` on a `PurchasePeriod` when an officer certifies, and as `issued_by_user_id` on a `Form3922` when an officer issues a form, but it does not compare it to any entity's `id`.
- **`Participant`** — the employee who enrolls, contributes via payroll, suspends, resumes, withdraws, and disposes of shares. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` compare the resource's participant foreign-key field to `X-User-ID`.

For participant-owned actions — the enrollment lifecycle operations and disposition recording — the acting participant's `X-User-ID` must equal the `participant_id` of the affected resource (for an enrollment, the `participant_id` of the enrollment; for a disposition, the owner of the referenced share lot). A participant acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

### 2.2. API Response Structure

All API responses, whether successful or an error, share a single, consistent JSON envelope. This is a strict, non-negotiable contract for every endpoint in the system.

**Top-Level Envelope Fields:**

- `meta`: An object containing metadata about the request.
    - `api_request_id`: A unique server-generated identifier for the request (e.g., `req_RANDOMALPHANUM123456`).
    - `api_request_timestamp`: An ISO 8601 UTC timestamp of when the response was generated (e.g., `2025-05-24T10:30:00.123Z`).
- `response_type`: A string indicating the payload structure. One of `object`, `array`, or `error`.
- `data`: The main payload.
    - For `response_type: object`, `data` is a single resource object.
    - For `response_type: array`, `data` is an array of resource objects.
    - For `response_type: error`, `data` contains `error_id` and `message`.

**Example Success Response (`response_type: object`):**

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "object",
  "data": { }
}
```

**Example Error Response (`response_type: error`):**

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable description of the error."
  }
}
```

### 2.3. Pagination

All list endpoints (those returning a `response_type: array`) accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100; a supplied `limit` below 1 is silently clamped up to 1 and one above 100 is silently clamped down to 100, and a non-numeric `limit` falls back to the default of 10 rather than being rejected. The `offset` parameter defaults to 0 and represents the number of records to skip; a negative `offset` is silently clamped to 0 and a non-numeric `offset` falls back to 0. List results are always sorted by `created_at` in ascending order. The response `meta` object for a list carries the pagination fields `limit`, `offset`, `total_count` (the total number of records matching the filter before pagination), and `has_more` (a boolean that is true when records remain beyond the returned page).

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional-second digits. Most resources also carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on every mutation. The one exception is the `Contribution` resource, which carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, because a contribution is an immutable ledger line whose `status` is advanced only by enclosing batch and withdrawal cascades.

Whenever any other resource is mutated — a state transition, a stamped field, a recomputed total — its `updated_at` is refreshed and its `version` is incremented by one. State transitions described throughout Section 3 each carry this version bump implicitly even where it is not restated.

### 2.5. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents; the API never emits fractional cents. The single point at which rounding occurs is the per-share discounted purchase price, which is rounded half up to the nearest whole cent. Every other monetary figure is derived by multiplying or summing whole-cent quantities and whole share counts, so no further rounding is introduced. Share counts are always whole numbers: wherever the number of shares is derived from a division, the result is taken as the floor (the largest whole number not exceeding the quotient), never rounded up.

### 2.6. Hierarchical Consistency and Cascades

The plan's resources form a hierarchy in which a single operation can ripple through several entities at once, and the system applies these cascades immediately and atomically. Cancelling an offering, withdrawing an enrollment, running a purchase batch, and closing an offering each touch multiple resources; the precise cascades are described in Section 3. In every case, each entity the cascade mutates has its `version` incremented and its `updated_at` refreshed. A parent offering's lifecycle is partly driven from below: it advances to its active and closed states automatically as a consequence of its child purchase periods reaching certain states, rather than through a direct call against the offering itself.

### 2.7. Nested Resource Retrieval

Several endpoints address a resource through a parent path — for example, the purchase periods under an offering, or the Form 3922 under a purchase. Path parameters are validated left to right: the system first confirms the outer (parent) resource exists, then the inner one. If any referenced resource in the path or body does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). The same left-to-right existence rule governs body-referenced foreign keys on creation.

### 2.8. Optimistic Concurrency on the Purchase Run

Executing a purchase batch is the one operation guarded by optimistic concurrency control. The request to run a purchase against a purchase period must carry `expected_purchase_period_version`, a non-optional field whose value is the `version` of that `PurchasePeriod` as the client last observed it. The server compares this value against the purchase period's current `version`; if they do not match — because some intervening write (a certification, or a sibling-cancel cascade) advanced the period's version after the client read it — the run is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client holding stale state from re-running a batch it has not freshly observed. No other endpoint accepts or requires a version field.

### 2.9. Segregation of Duties

The certification of a purchase batch and the execution of its buy are deliberately separated. The `ComplianceOfficer` who certifies a batch — whose `X-User-ID` is recorded as the batch's `certified_by_user_id` — must be a different person from whoever runs the buy. Because the run is performed by a `PlanAdministrator`, this is enforced as a comparison between the certifying officer's identifier and the running administrator's `X-User-ID`: if they are equal, the run is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). This guarantees that no single individual both blesses and executes the same purchase.

## 3. Business Logic & Workflows

### 3.1. Enrolling the Workforce and Configuring the Plan

The plan begins with a `PlanAdministrator` registering each employee as a `Participant`. Registration captures the employee's `email`, which serves as the login identity and must be unique and non-empty across participants; their `full_name`, the legal name that will later be printed on Form 3922; and their `employee_id`, the employer's payroll identifier, which must likewise be unique and non-empty. An optional `is_five_percent_owner` flag marks an employee who owns at least five percent of company stock; when omitted it defaults to false. Every participant carries a `status` that begins as `ACTIVE`; an administrator may later mark a participant `TERMINATED`, which is the only other value `status` can hold. A participant may read their own record, and any administrator or compliance officer may read any participant.

Plan policy is configured once by an administrator. A `Plan` carries the issuer's `company_name`, a `max_contribution_rate_pct` capping the per-paycheck withholding rate (defaulting to 15, and constrained to be greater than 0 and at most 15), a `discount_pct` giving the purchase discount off the applicable fair market value (defaulting to 15, and constrained to be at least 0 and at most 15), a `lookback_enabled` flag (defaulting to true) that decides whether pricing uses the lookback floor, and an `annual_purchase_limit_usd` (defaulting to 25000, and constrained to be greater than 0) that sets the statutory accrual cap measured in whole dollars at grant-date value. All three roles may read a plan.

### 3.2. Opening Offerings and Their Purchase Batches

An administrator opens an offering window by creating an `OfferingPeriod` under a plan, supplying the `plan_id`, the `grant_date` (the offering's grant date, against which the lookback grant-date fair market value is measured and from which the qualifying holding clock runs), the `duration_months`, and the `grant_date_fmv_cents` (the per-share fair market value in cents on the grant date, which must be greater than zero). The `duration_months` must be at least 6 and at most 24; a value outside that inclusive range is rejected with `ERR_OFFERING_DURATION` (HTTP 422). The system computes `end_date` by adding `duration_months` calendar months to `grant_date`; the offering closes at that point. A new offering opens in `OPEN` status and tracks a `purchase_period_count`, which begins at 0 and increments by one each time a purchase period is created beneath it.

While an offering is `OPEN`, employees may enroll. When the enrollment window should close, the administrator closes enrollment, advancing the offering from `OPEN` to `ENROLLMENT_CLOSED`; this is permitted only when the offering is currently `OPEN`, and once closed no new enrollment may be created against that offering. An offering that has not yet settled any purchase may be cancelled outright — see Section 3.7.

Within an offering, the administrator lays out one or more purchase batches by creating a `PurchasePeriod`. Each batch supplies a `sequence_index` — its 1-based ordinal within the offering, which must be at least 1 and unique within its `offering_period_id`, and which defines the chronological order in which batches are processed — together with a `purchase_date` (the date shares are bought, from which the disqualifying holding clock runs) and a `purchase_date_fmv_cents` (the per-share fair market value in cents on the purchase date, which must be greater than zero and is fixed when the batch is laid out, before pricing). A batch's `purchase_date` must fall on or after the offering's `grant_date` and on or before its `end_date`; a date outside that inclusive window is rejected with `ERR_PURCHASE_DATE_OUT_OF_RANGE` (HTTP 422). A batch is created carrying the `offering_period_id` it belongs to, begins in `PENDING` status, and has an empty `certified_by_user_id` until it is certified.

### 3.3. The Employee's Contribution Lifecycle

A `Participant` enrolls in an offering by creating an `Enrollment`, supplying their own `participant_id`, the target `offering_period_id`, and the elected `contribution_rate_pct` — the percentage of each paycheck to withhold, accepted as any number (integer or fractional). Several conditions guard enrollment, and the system evaluates them in the priority order established in Section 2.1 and below: after authentication, role, ownership, and existence checks pass, the system first rejects an employee flagged as a five-percent owner with `ERR_FIVE_PERCENT_OWNER` (HTTP 422), because Section 423 bars such an owner from participating; then it rejects an employee whose `status` is not `ACTIVE` with `ERR_PARTICIPANT_NOT_ACTIVE` (HTTP 422); then it rejects a `contribution_rate_pct` that is not greater than 0 or that exceeds the plan's `max_contribution_rate_pct` with `ERR_RATE_EXCEEDS_LIMIT` (HTTP 422); then it rejects an attempt to hold more than one non-terminal enrollment in the same offering — that is, when the participant already has an enrollment in `ENROLLED` or `SUSPENDED` status against that offering — with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409); and finally it rejects enrollment against an offering whose `status` is not `OPEN` — only an `OPEN` offering accepts a new enrollment — with `ERR_INVALID_STATE` (HTTP 409). A new enrollment opens in `ENROLLED` status with an `accumulated_contribution_cents` of 0 and a `refunded_contribution_cents` of 0.

An enrolled employee accrues savings through payroll. An administrator records each withholding by creating a `Contribution` against an enrollment, supplying the `enrollment_id`, the `pay_date` on which the withholding posted, and the `gross_pay_cents` (the gross paycheck the rate applies to, which must be greater than zero). The system computes the withheld `amount_cents` by multiplying `gross_pay_cents` by the enrollment's `contribution_rate_pct`, dividing by 100, and taking the floor of the result. That amount is added to the enrollment's `accumulated_contribution_cents`. A new contribution opens in `POSTED` status. A contribution may be posted only against an enrollment currently in `ENROLLED` status; posting against an enrollment that is `SUSPENDED`, `WITHDRAWN`, or `COMPLETED` is rejected with `ERR_ENROLLMENT_NOT_CONTRIBUTING` (HTTP 409). A contribution's `status` later becomes `CONSUMED` when it is applied to a purchase, or `REFUNDED` when it is returned to the employee.

Mid-offering, an employee may pause and resume their participation. Suspending an enrollment moves it from `ENROLLED` to `SUSPENDED`, which is permitted only when the enrollment is `ENROLLED` and its parent offering is not `CLOSED`; while suspended, no further contribution may be posted. Resuming moves it back from `SUSPENDED` to `ENROLLED`, permitted only when the enrollment is `SUSPENDED` and its parent offering is in `OPEN`, `ENROLLMENT_CLOSED`, or `ACTIVE`. This `ENROLLED` and `SUSPENDED` pair may cycle freely. An employee may also withdraw entirely from either `ENROLLED` or `SUSPENDED`, advancing the enrollment to `WITHDRAWN`; on withdrawal, every `POSTED` contribution for that enrollment becomes `REFUNDED`, the enrollment's `refunded_contribution_cents` is recomputed to reflect the returned amounts, and its `accumulated_contribution_cents` is reset to 0. Any transition from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.4. Preparing a Batch: Sequencing and Certification

When the time comes to process a batch, the administrator opens it, advancing the `PurchasePeriod` from `PENDING` to `OPEN`. Opening is permitted only when the batch is currently `PENDING`, when its parent offering is in `ENROLLMENT_CLOSED` or `ACTIVE`, and when every sibling batch with a smaller `sequence_index` has already reached a terminal state of `PURCHASED` or `CANCELLED`. This last condition is the sequential gate: lower-indexed batches must finish before a higher-indexed one opens, and an attempt to jump the queue is rejected with `ERR_SEQUENCE_NOT_READY` (HTTP 409). Opening the very first batch of an offering also bubbles the parent offering up from `ENROLLMENT_CLOSED` to `ACTIVE`.

Once a batch is `OPEN`, a `ComplianceOfficer` certifies it, advancing it from `OPEN` to `CERTIFIED`. Certification is permitted only when the batch is `OPEN`, and it stamps `certified_by_user_id` with the certifying officer's `X-User-ID`. Certification is the independent sign-off on the twenty-five-thousand-dollar accrual sweep, and it must precede the buy. A batch may be cancelled from any of `PENDING`, `OPEN`, or `CERTIFIED`, moving it to `CANCELLED`.

### 3.5. Running the Buy and Issuing Form 3922

Executing a batch is the system's central settlement event. An administrator runs the buy against a `CERTIFIED` batch, supplying `expected_purchase_period_version`; the batch advances from `CERTIFIED` to `PURCHASED`. The run is guarded by several checks, applied in order after the purchase period's existence is confirmed: a missing or non-integer `expected_purchase_period_version` is rejected first with `ERR_VALIDATION` (HTTP 400), then the state, version, and segregation checks below. The batch must be `CERTIFIED`; a run attempted against a batch in any other state is rejected with `ERR_NOT_CERTIFIED` (HTTP 409). The supplied `expected_purchase_period_version` must equal the batch's current `version`, or the run is rejected with `ERR_STALE_VERSION` (HTTP 412). And the running administrator's `X-User-ID` must differ from the batch's `certified_by_user_id`, or the run is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

When the run proceeds, the system processes every enrollment under the parent offering that is still in `ENROLLED` status, taking them in ascending order of each enrollment's `created_at`. For each such enrollment it computes and creates one `Purchase`, recording the originating `enrollment_id` and `purchase_period_id`. Pricing comes first. The applicable fair market value is the lower of the offering's `grant_date_fmv_cents` and the batch's `purchase_date_fmv_cents` when the plan's `lookback_enabled` is true; when lookback is disabled, only the `purchase_date_fmv_cents` is used and the grant-date figure is ignored for pricing. The `price_per_share_cents` is then the applicable fair market value multiplied by the quantity (100 minus the plan's `discount_pct`), divided by 100, and rounded half up to the nearest whole cent.

The share count is then bounded by two independent limits, described in detail in Section 3.6, and the smaller governs. The system records `shares_purchased`, the `spend_cents` actually drawn from contributions (the shares purchased multiplied by the price per share), the `grant_date_value_applied_cents` charged against the annual accrual cap (the shares purchased multiplied by the offering's `grant_date_fmv_cents`), and the `residual_cents` left over (the enrollment's accumulated contributions minus the spend). Each `Purchase` is created directly in its terminal `SETTLED` status. The contributions that funded the spend are marked `CONSUMED`, the residual is refunded back to the enrollment (raising its `refunded_contribution_cents`), and the participant's accrual ledger is charged as described in Section 3.6.

Alongside each purchase, the system creates a `ShareLot` to hold the acquired shares and a `Form3922` capturing the tax paperwork. A share lot records its originating `purchase_id` and the owning `participant_id`, copies the purchase's share count into `shares_total`, initializes `shares_remaining` to that same count, and copies `grant_date` from the owning offering and `purchase_date` from the owning batch — the two clocks that later govern disposition classification. A new lot opens in `OPEN` status. The Form 3922 created during the run records its `purchase_id` and `participant_id`; populates `box3_grant_date_fmv_cents` with the grant-date fair market value, `box4_purchase_date_fmv_cents` with the purchase-date fair market value, `box5_price_paid_cents` with the actual price paid per share, and `box6_shares` with the number of shares transferred; sets `tax_year` to the calendar year of the batch's `purchase_date`; and stamps `issued_by_user_id` with the certifying officer's identifier.

A `ComplianceOfficer` may also issue a Form 3922 for a purchase independently. Whether created during the run or issued on demand, a purchase may have its Form 3922 issued only once; a second issuance for the same purchase is rejected with `ERR_FORM_ALREADY_ISSUED` (HTTP 409).

### 3.6. The $25,000 Accrual Cap and the Cash-versus-Cap Allocation

The statutory accrual cap is measured not at the discounted price an employee pays but at grant-date fair market value, per Section 423(b)(8), and it is tracked per participant per calendar year in an `AccrualLedger` row. Each row records the owning `participant_id`, the `calendar_year` it tracks, the cumulative `accrued_grant_value_cents` charged to that participant-year by settled purchases (beginning at 0), and the `remaining_capacity_cents`, which is the plan's annual limit in dollars multiplied by 100 minus the accrued grant value, floored at 0. With the default limit of 25000 dollars, the annual ceiling is 2,500,000 cents of grant-date value. The ledger row for the relevant participant and year is created at 0 if it does not yet exist when a purchase first charges it.

During each enrollment's purchase, after the per-share price is known, the system bounds the share count two ways. The cap-permitted maximum is the remaining grant capacity — the annual limit in cents minus the already-accrued grant value for that participant-year, with the result never allowed below 0 — divided by the offering's `grant_date_fmv_cents`, taking the floor. The cash-permitted maximum is the enrollment's `accumulated_contribution_cents` divided by the `price_per_share_cents`, taking the floor. The `shares_purchased` is the smaller of these two maxima. When the cap-permitted maximum is the smaller, the cap is binding: the twenty-five-thousand-dollar limit constrains the buy and the excess cash beyond the spend becomes residual. When the cash-permitted maximum is the smaller or the two are equal, contributions are binding and only the fractional-share leftover becomes residual. The year used for the ledger is the calendar year of the batch's `purchase_date`. After the buy, the charged `grant_date_value_applied_cents` is added into the participant-year's `accrued_grant_value_cents`, and the `remaining_capacity_cents` is recomputed accordingly.

### 3.7. Cancelling an Offering and Closing It Out

An administrator may cancel an offering that has not yet settled any purchase. Cancellation is permitted only when the offering is in `OPEN` or `ENROLLMENT_CLOSED` and no purchase period child has reached `PURCHASED`; an attempt to cancel an offering that is in any other state, or one with a `PURCHASED` child, is rejected with `ERR_INVALID_STATE` (HTTP 409). When permitted, the offering moves to `CANCELLED`. The cancellation triggers a deep cascade: every enrollment under the offering transitions to `WITHDRAWN`, and each such withdrawal refunds all of that enrollment's `POSTED` contributions (each affected contribution becomes `REFUNDED` and the enrollment's `refunded_contribution_cents` is recomputed); in addition, every non-terminal purchase period child — those in `PENDING`, `OPEN`, or `CERTIFIED` — transitions to `CANCELLED`.

At the other end of an offering's life, closure happens automatically. When the buy is run on a batch and that batch is the last non-terminal purchase period in its offering — meaning, after this run, every purchase period child is `PURCHASED` or `CANCELLED` and at least one is `PURCHASED` — the parent offering bubbles up from `ACTIVE` to `CLOSED`. As the offering closes, every enrollment under it still in `ENROLLED` status auto-transitions to `COMPLETED`. An offering's `CLOSED` and `CANCELLED` states are terminal.

### 3.8. Selling Shares: Qualifying versus Disqualifying Dispositions

When an employee sells shares, they record a `Disposition` against one of their share lots, supplying the `share_lot_id`, their own `participant_id`, the `sale_date`, the number of `shares_sold` (which must be an integer), and the `sale_price_per_share_cents` (the per-share proceeds in cents, which must be at least 0). The lot must be `OPEN` and owned by the acting participant. After authentication, role, ownership, and existence checks pass, the system applies the lot-level checks in this fixed order: it first rejects a lot whose `status` is not `OPEN` with `ERR_INVALID_STATE` (HTTP 409); then a `sale_date` earlier than the lot's `purchase_date` with `ERR_SALE_BEFORE_PURCHASE` (HTTP 422); then a `shares_sold` that is not greater than 0 or that exceeds the lot's `shares_remaining` with `ERR_INSUFFICIENT_SHARES` (HTTP 422). A disposition is recorded directly in `RECORDED` status, and recording it decrements the lot's `shares_remaining` by the shares sold; if that brings `shares_remaining` to exactly 0, the lot transitions from `OPEN` to `FULLY_DISPOSED`.

Recording a disposition first classifies it. The disposition is `QUALIFYING` when the `sale_date` is on or after the second anniversary of the lot's `grant_date` and also on or after the first anniversary of the lot's `purchase_date`; if either anniversary has not yet been reached, it is `DISQUALIFYING`. The anniversary boundary is inclusive: selling exactly on the two-year-and-one-year anniversaries qualifies, while selling one day earlier than either does not. This classification is stored in `disposition_type` and selects which ordinary-income rule applies.

For a **qualifying** disposition, the `ordinary_income_cents` is the lesser of two quantities. The first is the actual economic gain: the sale proceeds (shares sold multiplied by `sale_price_per_share_cents`) minus the purchase cost (shares sold multiplied by the purchase's `price_per_share_cents`), with the result never allowed below 0. The second is the grant-date statutory discount: the shares sold multiplied by the amount, never allowed below 0, by which the offering's `grant_date_fmv_cents` exceeds the purchase's `price_per_share_cents`. When the actual gain is the smaller, ordinary income is capped by the economic gain (the case of a low or loss sale); when the statutory discount is the smaller or the two are equal, ordinary income equals the grant-date statutory discount. The adjusted basis is then the purchase cost plus the ordinary income, and the `capital_gain_cents` is the sale proceeds minus that adjusted basis.

For a **disqualifying** disposition, the `ordinary_income_cents` is fixed at the spread at purchase regardless of the sale price: the shares sold multiplied by the amount, never allowed below 0, by which the batch's `purchase_date_fmv_cents` exceeds the purchase's `price_per_share_cents`. As with the qualifying case, the adjusted basis is the purchase cost (shares sold multiplied by the purchase's `price_per_share_cents`) plus that ordinary income, and the `capital_gain_cents` is the sale proceeds (shares sold multiplied by `sale_price_per_share_cents`) minus the adjusted basis. The sale price therefore affects only the capital-gain figure on a disqualifying sale, never the ordinary-income spread.

### 3.9. Reading the Records

All three roles may read individual resources and list collections. Administrators and compliance officers may read any record; a participant may read their own. Offering periods can be listed under a plan, purchase periods under an offering, and the Form 3922 for a given purchase; enrollments can be filtered by `participant_id` or `offering_period_id`; contributions by `enrollment_id`; purchases by `enrollment_id` or `purchase_period_id`; share lots and dispositions by `participant_id` and by their lot or purchase association; Form 3922 records by `participant_id` or `purchase_id`; and accrual ledger rows by `participant_id` or `calendar_year`. Most list endpoints also accept an optional `status` filter. Across every list, results follow the pagination and sort contract of Sections 2.3.

Throughout all mutating operations, when a request body is missing a required field, carries a field of the wrong type, or is otherwise malformed, the request is rejected with `ERR_VALIDATION` (HTTP 400). This structural check sits at the lowest priority among the body-level validations, after authentication, role, ownership, and existence have been confirmed.

## 4. Endpoint Definitions

New resource creation returns HTTP 201; reads and state-modifying actions on existing resources return HTTP 200. The request and response bodies for each endpoint are not restated here — they are reconstructed from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/participants` | Register an employee | PlanAdministrator |
| GET | `/participants/{id}` | Read a participant | PlanAdministrator, ComplianceOfficer, Participant |
| POST | `/participants/{id}/terminate` | Mark a participant TERMINATED | PlanAdministrator |
| POST | `/plans` | Create the ESPP plan configuration | PlanAdministrator |
| GET | `/plans/{id}` | Read plan config | PlanAdministrator, ComplianceOfficer, Participant |
| POST | `/offering-periods` | Open an offering/grant period under a plan | PlanAdministrator |
| GET | `/offering-periods/{id}` | Read an offering period | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/plans/{id}/offering-periods` | List offering periods under a plan | PlanAdministrator, ComplianceOfficer, Participant |
| POST | `/offering-periods/{id}/close-enrollment` | Close enrollment window | PlanAdministrator |
| POST | `/offering-periods/{id}/cancel` | Cancel an offering before any purchase settled | PlanAdministrator |
| POST | `/offering-periods/{id}/purchase-periods` | Create a purchase period (batch) under an offering | PlanAdministrator |
| GET | `/purchase-periods/{id}` | Read a purchase period | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/offering-periods/{id}/purchase-periods` | List purchase periods under an offering | PlanAdministrator, ComplianceOfficer, Participant |
| POST | `/purchase-periods/{id}/open` | Open a batch for purchase (sequential gate) | PlanAdministrator |
| POST | `/purchase-periods/{id}/certify` | Certify the $25k accrual sweep for the batch | ComplianceOfficer |
| POST | `/purchase-periods/{id}/run-purchase` | Execute the buy for all enrolled participants | PlanAdministrator |
| POST | `/purchase-periods/{id}/cancel` | Cancel a batch before purchase | PlanAdministrator |
| POST | `/enrollments` | Participant enrolls in an offering | Participant |
| GET | `/enrollments/{id}` | Read an enrollment | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/enrollments` | List enrollments filtered by participant or offering | PlanAdministrator, ComplianceOfficer, Participant |
| POST | `/enrollments/{id}/suspend` | Participant suspends contributions | Participant |
| POST | `/enrollments/{id}/resume` | Participant resumes contributions | Participant |
| POST | `/enrollments/{id}/withdraw` | Participant withdraws; refunds all POSTED contributions | Participant |
| POST | `/contributions` | Record a payroll withholding against an enrollment | PlanAdministrator |
| GET | `/contributions/{id}` | Read a contribution | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/contributions` | List contributions filtered by enrollment | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/purchases/{id}` | Read a settled purchase | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/purchases` | List purchases filtered by enrollment or purchase period | PlanAdministrator, ComplianceOfficer, Participant |
| POST | `/purchases/{id}/form-3922` | Issue the IRS Form 3922 for a purchase | ComplianceOfficer |
| GET | `/purchases/{id}/form-3922` | List the Form 3922 for a purchase | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/form-3922/{id}` | Read a single Form 3922 | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/form-3922` | List Form 3922 filtered by participant or purchase | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/share-lots/{id}` | Read a share lot | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/share-lots` | List share lots filtered by participant or purchase | PlanAdministrator, ComplianceOfficer, Participant |
| POST | `/dispositions` | Record a sale/transfer of shares | Participant |
| GET | `/dispositions/{id}` | Read a disposition | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/dispositions` | List dispositions filtered by participant or share lot | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/accrual-ledgers/{id}` | Read a participant-year accrual ledger row | PlanAdministrator, ComplianceOfficer, Participant |
| GET | `/accrual-ledgers` | List accrual ledger rows filtered by participant | PlanAdministrator, ComplianceOfficer, Participant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_FIVE_PERCENT_OWNER | 422 |
| ERR_PARTICIPANT_NOT_ACTIVE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_NOT_CERTIFIED | 409 |
| ERR_SEQUENCE_NOT_READY | 409 |
| ERR_OFFERING_DURATION | 422 |
| ERR_PURCHASE_DATE_OUT_OF_RANGE | 422 |
| ERR_SALE_BEFORE_PURCHASE | 422 |
| ERR_RATE_EXCEEDS_LIMIT | 422 |
| ERR_DUPLICATE_ENROLLMENT | 409 |
| ERR_INSUFFICIENT_SHARES | 422 |
| ERR_ENROLLMENT_NOT_CONTRIBUTING | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_FORM_ALREADY_ISSUED | 409 |

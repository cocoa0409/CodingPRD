# Childcare Subsidy Voucher (CCDF) API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Childcare Subsidy Voucher API, a backend service that administers a Child Care and Development Fund (CCDF) style subsidy program. The system exists to answer a sequence of intertwined public-benefits questions for a single household: is the family financially and occupationally eligible for help, how much of the cost must the family shoulder as a sliding-fee copay, which licensed provider will care for the child and at what reimbursable daily rate, how much does the program actually pay each month once real attendance is known, and — when something was paid in error — how is that money clawed back.

The program is fundamentally a compliance-and-audit engine layered over a pricing engine. Eligibility standards, provider licensing, rate ceilings, absence-day policy, and continuity-of-care redetermination all impose hard gates on when money may flow, while the copay and payment computations must be reproducible to the cent. Because eligibility, authorization, attendance, and disbursement are handled by different actors at different times, the API models each concern as a peer resource linked by identifiers rather than by nested ownership, and it uses a logical clock so that time-dependent behavior — license expiry, authorization expiry, and redetermination deadlines — can be exercised deterministically. The sections that follow describe the global contract first, then the domain workflows in detail, and finally the concrete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or its value is not recognized, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `Family`, `Provider`, `CaseWorker`, and `ProgramAdmin`.

The two administrative roles are identity-opaque. When `X-User-Role` is `CaseWorker`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. Likewise, when `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not bound to any stored record, used only to authorize the operation.

The two participant roles are entity-backed. When `X-User-Role` is `Family`, `X-User-ID` is the `id` of the acting `Family`; any ownership check on a resource that references a household compares that resource's `family_id` to `X-User-ID`, so a `Family` may read only its own application, its own determinations, and its own authorizations. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on a resource that references a provider compare that resource's `provider_id` to `X-User-ID`, so a `Provider` may read only attendance, payments, and claims that trace back to itself. An entity-backed caller that targets another party's resource is rejected with `ERR_UNAUTHORIZED`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100; a supplied value below 1 is clamped up to 1 and a value above 100 is clamped down to 100. The `offset` parameter specifies the number of items to skip and defaults to 0; a supplied value below 0 is clamped up to 0. A `limit` or `offset` query value that is not a valid integer is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary resources — `Family`, `EligibilityDetermination`, `Provider`, `Authorization`, `AttendanceRecord`, `Payment`, and `OverpaymentClaim` — carry a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation of the resource.
- `version`: an integer that begins at its initial value of 1 and increments by one on every mutation of the resource. It underpins optimistic concurrency control (see §2.6).

Three configuration and lookup resources are deliberately lighter: `ParentActivity`, `IncomeStandard`, and `RateCeiling` carry only `id` and `created_at`. They have no `updated_at` and no `version`, because once written they are treated as immutable reference data rather than mutable workflow objects.

Whenever a derived or system field on a resource changes — for example when a `Family`'s running ledger or eligibility posture is recomputed — that change counts as a mutation of the resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Monetary Values, Precision, and Rounding

Every monetary quantity in the system is stored and returned as an integer number of cents; field names ending in `_cents` are always whole-cent integers, never fractional currency. Where a calculation divides — computing an income ratio, or apportioning a monthly copay across days — the intermediate result is rounded using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger integer). The precise point at which rounding is applied is pinned per calculation and described in §3; implementers must apply rounding exactly where stated and nowhere else, because the copay proration in particular is order-sensitive and yields a different total if the rounding step is moved.

### 2.6. Optimistic Concurrency Control on Voucher Creation

Creating a new voucher is the one write in this system guarded by optimistic concurrency control. A voucher creation carries an `expected_family_version` field, which must equal the target `Family`'s current `version` at the time the request is processed. A new voucher legitimately supersedes the household's prior active voucher as part of continuity-of-care renewal — it updates the household's `active_authorization_id` and may terminate a prior authorization — so acting on a stale view of the household is unsafe. If `expected_family_version` does not equal the household's current `version` (because some other writer has already advanced it since the client last read the family), the creation is rejected with `ERR_STALE_FAMILY_VERSION` and HTTP status 412, preventing the client from superseding a household state it has not observed. No other endpoint takes a version field; only voucher creation performs this check.

### 2.7. The Logical Clock and Time-Driven Expiry

All time-dependent behavior is measured against a single logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to the machine's wall-clock. A `ProgramAdmin` may advance the clock by supplying a `to_iso8601` instant; the clock is set to exactly the supplied instant, which is not required to be later than the current clock time (the clock may be moved backward).

Setting the clock runs an expiry sweep across three entities, each an automatic system transition that mutates the affected resource (refreshing `updated_at` and incrementing `version`):

- Any `Provider` currently `LICENSED` whose `license_expiry_date` is strictly earlier than the new clock time transitions to `EXPIRED`.
- Any `Authorization` currently `ACTIVE` whose `end_date` is strictly earlier than the new clock time transitions to `EXPIRED`.
- Any `EligibilityDetermination` currently `APPROVED` whose `redetermination_due_date` is strictly earlier than the new clock time transitions to `EXPIRED`, marking the household's certification as overdue for redetermination.

### 2.8. Cascades and Ledger Conservation

Several operations mutate more than one entity. These cascades are mandatory and must be applied atomically with the triggering operation.

**Provider revocation cascade (cascade A).** Revoking a provider's license does not stop at the provider. In its first hop, every `Authorization` for that provider currently in `ACTIVE` transitions to `SUSPENDED`. Each such suspension in turn triggers the second hop: every `AttendanceRecord` for that authorization currently in `SUBMITTED` transitions to `REJECTED`. The same second hop fires whenever an authorization is suspended for any reason, not only during revocation.

**Determination denial cascade (cascade B).** When a determination is finalized to `DENIED`, every `Authorization` that rests on that determination and is currently in `PENDING`, `ACTIVE`, or `SUSPENDED` transitions to `TERMINATED`.

**Ledger conservation.** The program maintains two independent running ledgers that must always equal the sum of their contributing paid payments. `Provider.total_net_paid_cents` equals the sum of `net_provider_payment_cents` over all that provider's payments in status `PAID`; `Family.total_copay_charged_cents` equals the sum of `copay_deducted_cents` over all that household's payments in status `PAID`. Approving attendance adds a payment's net and copay amounts into these two ledgers; reversing that payment subtracts exactly the same two amounts, so that an approve followed by a reverse of the same attendance returns both ledgers precisely to their pre-approval values with no drift.

### 2.9. Existence Resolution and Validation Ordering

Every identifier a request supplies — the resource named in the URL path and every foreign-key identifier in the body — must resolve to an existing record. These are validated left to right, and the first identifier that fails to resolve causes immediate rejection with `ERR_NOT_FOUND`. A malformed body — a missing required field, a value of the wrong type, or an invalid enum value — is rejected with `ERR_VALIDATION`.

Validation across the whole API follows a fixed priority order so that the reported error is deterministic when several conditions could fail at once. Authentication is checked first: a missing or unrecognized user context yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. On resource-creation requests the request body is validated (`ERR_VALIDATION`) after role authorization but before existence resolution, so a malformed body is reported before any `ERR_NOT_FOUND`. Existence of all path and foreign-key identifiers is checked third, yielding `ERR_NOT_FOUND`. The per-resource ownership check for entity-backed `Family` and `Provider` callers (the `ERR_UNAUTHORIZED` of §2.1) is applied after existence resolution, so a request naming a nonexistent resource yields `ERR_NOT_FOUND` rather than `ERR_UNAUTHORIZED`. For any transition endpoint, the target resource must be in a state from which the transition is defined; otherwise the request is rejected with `ERR_INVALID_STATE`. Only after these universal gates pass does the system evaluate the operation-specific business rules described in §3, in the relative order stated there.

## 3. Business Logic & Workflows

### 3.1. Household Intake and Qualifying Activities

The lifecycle begins when a `CaseWorker` intakes a household. Creating a `Family` records the primary applicant via `applicant_name`, the `household_size` (which must be at least 1 and later keys the income-standard lookup), the reported `monthly_gross_income_cents` (at least 0), and the two-letter `state_code`. An optional `monthly_self_employment_income_cents` may be supplied; when omitted it defaults to 0. This self-employment figure is treated as unverified at initial eligibility and is only counted later, at redetermination. Every new household starts with `status` equal to `PENDING`, an `active_authorization_id` of null, and a `total_copay_charged_cents` ledger of 0. The household `status` will subsequently move among `PENDING`, `ELIGIBLE`, and `INELIGIBLE` as its determinations resolve; `CLOSED` is a defined status value, but no current operation transitions a household into `CLOSED`.

A household qualifies for subsidy only if its parents are engaged in enough qualifying activity. A `CaseWorker` records each `ParentActivity` against a household by supplying the `family_id` it qualifies, the `activity_type` — one of `WORK`, `EDUCATION`, or `JOB_SEARCH` — and the `weekly_hours` devoted to it, which must be at least 0. Activities accumulate: a household's activity standing is the sum of `weekly_hours` across all of its recorded activities. Parent activities can be listed and filtered by `family_id` for reverse look-up.

### 3.2. Eligibility Determination and the Sliding-Fee Copay

Before a household is publicly known to have income standards, a `ProgramAdmin` publishes reference data. An `IncomeStandard` is keyed to a `household_size` and `state_code` and carries two ceilings in cents: the `entry_monthly_limit_cents`, an initial-eligibility ceiling, and the `exit_monthly_limit_cents`, a more generous continuity-of-care ceiling used at redetermination that is expected to be greater than or equal to the entry limit (the API accepts the values as published and does not separately validate this relationship). Publishing more than one `IncomeStandard` for the same `household_size` and `state_code` is permitted; when several match at lookup time, the most recently created one is used.

A `CaseWorker` opens an `EligibilityDetermination` for a household by supplying the `family_id` and the `determination_type`, either `INITIAL` or `REDETERMINATION`. The record is created in `status` `PENDING` and holds computed fields that stay at their defaults — `countable_income_cents` at 0, `income_eligible` and `activity_eligible` at false, `result` unset, `monthly_copay_cents` at 0, and `effective_date` and `redetermination_due_date` unset — until the determination is finalized.

Finalizing a determination is the pivotal calculation and moves it out of `PENDING`. Finalization first requires that an `IncomeStandard` exist for the household's `household_size` and `state_code`; if none does, the request is rejected with `ERR_NO_INCOME_STANDARD`. The computation then proceeds in a variant selected by `determination_type`:

- **Initial (provisional) variant.** When `determination_type` is `INITIAL`, the household's countable income is its gross income alone — `countable_income_cents` is set to `monthly_gross_income_cents` — and income eligibility is tested against the `entry_monthly_limit_cents`.
- **Redetermination (verified) variant.** When `determination_type` is `REDETERMINATION`, the countable income is the household's gross income plus its self-employment income — `countable_income_cents` is set to the sum of `monthly_gross_income_cents` and `monthly_self_employment_income_cents` — and income eligibility is tested against the more generous `exit_monthly_limit_cents`.

`income_eligible` is true when `countable_income_cents` is less than or equal to the applicable limit. `activity_eligible` is true when the household's summed `weekly_hours` across all its parent activities is at least the minimum weekly activity threshold of 20 hours. If either test fails, the determination is finalized to `DENIED`: its `result` becomes `DENIED`, its `monthly_copay_cents` stays 0, the household `status` is set to `INELIGIBLE`, and cascade B fires — every authorization resting on this determination that is in `PENDING`, `ACTIVE`, or `SUSPENDED` is terminated (see §2.8).

When both tests pass, the determination is finalized to `APPROVED`, `result` becomes `APPROVED`, and the sliding-fee copay is computed. The copay percentage is chosen from a fixed band table keyed on the ratio of the household's `countable_income_cents` to the `entry_monthly_limit_cents` — note the denominator is always the entry limit, even in the redetermination variant. Scanning the bands in ascending order of their ceilings, the applicable percentage is the first band whose ceiling the ratio does not exceed: a ratio at or below 0.50 draws 2 percent; above that but at or below 0.75 draws 5 percent; above that but at or below 1.00 draws 8 percent; above that but at or below 1.25 draws 10 percent; a ratio above 1.25 — including the degenerate case where the entry limit is 0 — also draws the highest band's 10 percent. The `monthly_copay_cents` is then the household's `countable_income_cents` multiplied by that percentage, divided by 100, rounded half up to a whole cent.

On approval the determination's timing fields are stamped: `effective_date` is set to the current logical clock time, and `redetermination_due_date` is set to 12 months after that effective date, establishing the continuity-of-care redetermination deadline. The household `status` is set to `ELIGIBLE`. Both the denial path and the approval path mutate the household, which increments `Family.version` by one. A finalized determination that later has its `redetermination_due_date` fall behind the logical clock is swept to `EXPIRED` (see §2.7); `DENIED` and `EXPIRED` are terminal. Determinations can be read individually and listed or filtered by `family_id`.

### 3.3. Provider Registration and the Licensing Lifecycle

A `ProgramAdmin` registers each childcare `Provider` by supplying its `name`, its `provider_type` (either `CENTER` or `FAMILY_HOME`), its own posted private-pay `published_daily_rate_cents` (at least 0), the `license_expiry_date` on which its current license lapses, and its two-letter `state_code`. A newly registered provider starts with `license_status` `PENDING_VERIFICATION` and a `total_net_paid_cents` ledger of 0.

Licensing is driven through a single administrative action carrying an `action` value. Verifying a provider — permitted only while it is `PENDING_VERIFICATION` — moves `license_status` to `LICENSED`, but only if the provider's `license_expiry_date` is strictly later than the current logical clock; a provider whose `license_expiry_date` is not strictly later than the clock has already lapsed, cannot be verified into service, and the attempt is rejected with `ERR_INVALID_STATE`. Rejecting a `PENDING_VERIFICATION` provider moves `license_status` to `REJECTED`, a terminal posture. Revoking a `LICENSED` provider moves `license_status` to `REVOKED`, also terminal, and triggers cascade A: every `ACTIVE` authorization for that provider is suspended, which in turn rejects those authorizations' `SUBMITTED` attendance (see §2.8).

Licensing also has time-driven and recovery paths. A `LICENSED` provider whose `license_expiry_date` falls before the logical clock is swept to `EXPIRED` (see §2.7). An `EXPIRED` provider can be renewed: supplying a renewal `action` together with a fresh `license_expiry_date` (the field is required for renewal; a renewal that omits it is rejected with `ERR_VALIDATION`) that is strictly later than the current clock overwrites the stored `license_expiry_date` with the supplied value and returns `license_status` to `LICENSED`, closing the expire-and-renew loop; a supplied `license_expiry_date` that is not strictly later than the clock is rejected with `ERR_INVALID_STATE`. A provider can be read by any role.

### 3.4. Rate Ceilings and Voucher Authorization

Reimbursement is capped by published rate ceilings. A `ProgramAdmin` publishes a `RateCeiling` for a combination of `provider_type`, `care_level` — one of `INFANT`, `TODDLER`, `PRESCHOOL`, or `SCHOOL_AGE` — and `state_code`, setting the `max_daily_rate_cents` reimbursable for that combination and an effective window bounded inclusively by `effective_start` and `effective_end` (a closed interval on both ends). No two ceilings for the same `provider_type`, `care_level`, and `state_code` may have overlapping windows; because the windows are closed, even a shared endpoint counts as an overlap, and a conflicting publication is rejected with `ERR_RATE_CEILING_OVERLAP`. Ceilings can be listed and filtered by `provider_type` and `care_level`.

A `CaseWorker` creates a voucher — an `Authorization` — that binds a household, a provider, and a determination together for one child. The creation supplies the `family_id`, the `provider_id`, the `determination_id` the voucher rests on, the `child_name` served, the `care_level` for rate lookup, an inclusive `start_date`, an exclusive `end_date`, and the planned `authorized_days_per_month` (at least 1). It must also carry the `expected_family_version` for the optimistic-concurrency check described in §2.6. The voucher is created in `status` `PENDING`.

At creation the system resolves the reimbursable rate. It selects the `RateCeiling` matching the provider's `provider_type`, the voucher's `care_level`, and the provider's `state_code` whose closed `effective_start`–`effective_end` window contains the voucher's `start_date`; if several qualify, it chooses the one with the latest `effective_start`, breaking any remaining tie in favor of the one created most recently by `created_at`. If no ceiling covers the `start_date`, creation is rejected with `ERR_NO_RATE_CEILING`. Otherwise the voucher's `authorized_daily_rate_cents` is set to the smaller of the provider's `published_daily_rate_cents` and the selected ceiling's `max_daily_rate_cents` (a plain integer minimum, no rounding). The determination's `monthly_copay_cents` is copied onto the voucher's own `monthly_copay_cents`.

The voucher also records a forward-looking estimate. Its `estimated_monthly_payment_cents` assumes full attendance and the full monthly copay: it is the `authorized_daily_rate_cents` multiplied by the `authorized_days_per_month`, less the full `monthly_copay_cents` (deducted in whole, not prorated), with the result floored at 0 so it never goes negative.

Creating a voucher supersedes the household's prior arrangement. It sets the household's `active_authorization_id` to the new voucher, and if a prior `ACTIVE` authorization exists for the same household and the same `child_name`, that prior authorization is terminated. Because this reshapes the household, voucher creation increments `Family.version` by one. Two non-terminal vouchers for the same `family_id` and `child_name` may not cover overlapping service periods: overlap is measured on the half-open interval from `start_date` up to but not including `end_date`, so two vouchers that merely abut — one ending exactly where the next begins — are allowed, while any true overlap is rejected with `ERR_AUTHORIZATION_OVERLAP`.

The order of the create-time business checks is fixed: after the universal existence and payload checks, the overlap rule is evaluated first (`ERR_AUTHORIZATION_OVERLAP`), then the rate-ceiling coverage requirement (`ERR_NO_RATE_CEILING`), and finally the optimistic-concurrency check on the household version (`ERR_STALE_FAMILY_VERSION`). Vouchers can be read by the household, the provider, and staff, and listed or filtered by `family_id`, `provider_id`, or `determination_id`.

### 3.5. The Authorization Lifecycle

A `PENDING` voucher must be activated before it can bill. Activation, performed by a `CaseWorker`, is gated by three business checks evaluated in a fixed order after the state check. First, the determination the voucher rests on must belong to the same household: the determination's `family_id` must equal the voucher's `family_id`, or the request is rejected with `ERR_DETERMINATION_FAMILY_MISMATCH`. Second, the selected provider must be currently licensed — its `license_status` must be `LICENSED` — or the request is rejected with `ERR_PROVIDER_NOT_LICENSED`. Third, the determination must be currently approved — its `status` must be `APPROVED`, not `EXPIRED`, `DENIED`, or `PENDING` — or the request is rejected with `ERR_DETERMINATION_NOT_APPROVED`. When all three hold, the voucher moves from `PENDING` to `ACTIVE`.

An `ACTIVE` voucher can be suspended, either directly by a `CaseWorker` or `ProgramAdmin` or automatically as the first hop of a provider-revocation cascade. Suspension moves the voucher from `ACTIVE` to `SUSPENDED` and, as its own cascade hop, rejects every `SUBMITTED` attendance record for that voucher (see §2.8). A `SUSPENDED` voucher can be reinstated by a `CaseWorker`, moving it back from `SUSPENDED` to `ACTIVE`, but only if the provider's `license_status` is still `LICENSED`; otherwise reinstatement is rejected with `ERR_PROVIDER_NOT_LICENSED`. This suspend-and-reinstate cycle can repeat.

A voucher can be terminated by a `CaseWorker` from either `ACTIVE` or `SUSPENDED`, moving it to `TERMINATED`; a `PENDING` voucher can also reach `TERMINATED` automatically through determination-denial cascade B. An `ACTIVE` voucher whose `end_date` falls behind the logical clock is swept to `EXPIRED` (see §2.7). Both `TERMINATED` and `EXPIRED` are terminal.

### 3.6. Attendance Submission, Approval, and Payment

Each month a `Provider` submits attendance for a voucher it serves. Creating an `AttendanceRecord` supplies the `authorization_id` being billed, the `service_month` as a `YYYY-MM` string (a value that is not a well-formed `YYYY-MM` with a four-digit year and a month of 01–12 is rejected with `ERR_VALIDATION`), the count of `present_days`, and the count of `absent_days` (each at least 0). Only one attendance record may exist per voucher per month: a second submission for the same `authorization_id` and `service_month` is rejected with `ERR_DUPLICATE_ATTENDANCE`. A new record starts in `status` `SUBMITTED` with `payable_days` at 0.

A `CaseWorker` approves submitted attendance. The record must itself be in `SUBMITTED`, otherwise the approval is rejected with `ERR_INVALID_STATE`; approval then requires that the underlying voucher be `ACTIVE` — a voucher in any other state is rejected with `ERR_INVALID_STATE` — and that the reported days be coherent: `present_days` plus `absent_days` must not exceed the number of calendar days in the named `service_month`, or the approval is rejected with `ERR_INVALID_ATTENDANCE_DAYS`. These three checks are evaluated in that order (record state, then voucher state, then day coherence). Approval computes the billable days and disburses a payment. The absence-day policy caps how many absent days the program will pay for: `payable_days` is the `present_days` plus the smaller of the `absent_days` and the maximum paid-absence allowance of 5 days. In other words, absences beyond five in a month are unpaid.

The payment is then computed from the voucher's rate. The `gross_amount_cents` is the voucher's `authorized_daily_rate_cents` multiplied by the `payable_days`. The family copay withheld is prorated to the billed days with a pinned rounding order: first the per-day copay is derived by dividing the voucher's `monthly_copay_cents` by its `authorized_days_per_month` and rounding half up to a whole cent, and only then is that rounded per-day copay multiplied by the `payable_days` to yield `copay_deducted_cents`. This order is deliberate — the copay is rounded per day before multiplying, not by rounding the monthly copay times payable days over authorized days. The `net_provider_payment_cents` paid to the provider is the `gross_amount_cents` minus the `copay_deducted_cents`, floored at 0 so it is never negative.

Approval creates a `Payment` in `status` `PAID` and records on it the `attendance_record_id` that produced it, plus a denormalized copy of the recipient `provider_id`, the household `family_id`, and the `service_month`, all copied from the authorization and attendance record rather than owned as a nested path. The payment's `gross_amount_cents`, `copay_deducted_cents`, and `net_provider_payment_cents` are stored as computed above. As the payment posts, the provider's `total_net_paid_cents` is increased by the payment's `net_provider_payment_cents` and the household's `total_copay_charged_cents` is increased by the payment's `copay_deducted_cents` (see §2.8). The attendance record moves from `SUBMITTED` to `APPROVED`, a terminal state.

Submitted attendance can instead be rejected by a `CaseWorker`, optionally with a `reason`, moving it from `SUBMITTED` to `REJECTED`; the same `REJECTED` state is reached automatically when a voucher is suspended. A `Provider` may resubmit a rejected record, optionally supplying corrected `present_days` and `absent_days` which overwrite the stored counts, moving it from `REJECTED` back to `SUBMITTED` — but only while the underlying voucher is `ACTIVE`. This reject-and-resubmit cycle can repeat. Attendance records can be read by the provider and staff and listed or filtered by `authorization_id`; payments can be read by the provider and staff and listed or filtered by `attendance_record_id` or `provider_id`.

### 3.7. Payment Reversal and Overpayment Recovery

When money is disbursed in error, a `ProgramAdmin` reverses the payment, optionally recording a `reason`. Reversal moves the payment from `PAID` to `REVERSED`. It unwinds both ledgers exactly: the provider's `total_net_paid_cents` is reduced by the payment's `net_provider_payment_cents`, and the household's `total_copay_charged_cents` is reduced by the payment's `copay_deducted_cents`, returning both ledgers to their pre-approval values. Reversal simultaneously raises an `OverpaymentClaim` against the provider in `status` `OPEN`, whose `amount_cents` is the reversed payment's `net_provider_payment_cents` and whose `reason` is `PAYMENT_REVERSAL`. The claim records the owing `provider_id` and the originating `payment_id`, and its `recovered_amount_cents` starts at 0. (A claim's `reason` may in general be `PAYMENT_REVERSAL`, `LICENSE_REVOKED`, or `INELIGIBLE_PERIOD`; reversal always raises the `PAYMENT_REVERSAL` variety.)

Recovery of a claim proceeds in installments recorded by a `ProgramAdmin` while the claim is in `OPEN` or `RECOVERING` — a claim in any other state is rejected with `ERR_INVALID_STATE` — each supplying a positive `recovered_amount_cents` to apply. Each installment must be strictly greater than 0 (an installment of 0 or less is rejected with `ERR_VALIDATION`, a check evaluated after the claim-state check), and the running total after adding it must not exceed the claim's `amount_cents`; an installment that would push the cumulative `recovered_amount_cents` above `amount_cents` is rejected with `ERR_RECOVERY_EXCEEDS_CLAIM`. When an installment leaves the running `recovered_amount_cents` still short of the full `amount_cents`, the installment is added to the running total and the claim advances to (or remains in) `RECOVERING`. When an installment brings the cumulative `recovered_amount_cents` exactly to the `amount_cents`, the claim is marked fully paid: the running total is set to the `amount_cents` and the claim transitions to `RECOVERED`. A claim may instead be waived by a `ProgramAdmin` from `OPEN`, moving it to `WAIVED`. Both `RECOVERED` and `WAIVED` are terminal. Claims can be read by the owing provider and administrators, and listed or filtered by `provider_id` or `payment_id`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions and the logical-clock control — return `200 OK`. All list and read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ccdf/families` | Intake a household application | CaseWorker |
| GET | `/ccdf/families/{id}` | Read a household (Family reads only its own) | Family, CaseWorker, ProgramAdmin |
| POST | `/ccdf/parent-activities` | Record a qualifying parent activity | CaseWorker |
| GET | `/ccdf/parent-activities/{id}` | Read one parent activity | CaseWorker, ProgramAdmin |
| GET | `/ccdf/parent-activities` | List/filter parent activities | CaseWorker, ProgramAdmin |
| POST | `/ccdf/income-standards` | Publish an income standard | ProgramAdmin |
| POST | `/ccdf/determinations` | Open a determination for a household | CaseWorker |
| POST | `/ccdf/determinations/{id}/finalize` | Run eligibility test and set copay | CaseWorker |
| GET | `/ccdf/determinations/{id}` | Read one determination | Family, CaseWorker, ProgramAdmin |
| GET | `/ccdf/determinations` | List/filter determinations | CaseWorker, ProgramAdmin |
| POST | `/ccdf/providers` | Register a provider | ProgramAdmin |
| POST | `/ccdf/providers/{id}/license` | Licensing action (VERIFY/REJECT/REVOKE/RENEW) | ProgramAdmin |
| GET | `/ccdf/providers/{id}` | Read one provider | Family, Provider, CaseWorker, ProgramAdmin |
| POST | `/ccdf/rate-ceilings` | Publish a reimbursement ceiling | ProgramAdmin |
| GET | `/ccdf/rate-ceilings` | List/filter rate ceilings | CaseWorker, ProgramAdmin |
| POST | `/ccdf/authorizations` | Create a voucher (computes rate/estimate; OCC on family) | CaseWorker |
| POST | `/ccdf/authorizations/{id}/activate` | Activate a PENDING voucher | CaseWorker |
| POST | `/ccdf/authorizations/{id}/suspend` | Suspend an ACTIVE voucher | CaseWorker, ProgramAdmin |
| POST | `/ccdf/authorizations/{id}/reinstate` | Reinstate a SUSPENDED voucher | CaseWorker |
| POST | `/ccdf/authorizations/{id}/terminate` | Terminate a voucher | CaseWorker |
| GET | `/ccdf/authorizations/{id}` | Read one authorization | Family, Provider, CaseWorker, ProgramAdmin |
| GET | `/ccdf/authorizations` | List/filter authorizations | CaseWorker, ProgramAdmin |
| POST | `/ccdf/attendance-records` | Submit monthly attendance | Provider |
| POST | `/ccdf/attendance-records/{id}/approve` | Approve attendance and disburse payment | CaseWorker |
| POST | `/ccdf/attendance-records/{id}/reject` | Reject submitted attendance | CaseWorker |
| POST | `/ccdf/attendance-records/{id}/resubmit` | Resubmit a rejected attendance | Provider |
| GET | `/ccdf/attendance-records/{id}` | Read one attendance record | Provider, CaseWorker, ProgramAdmin |
| GET | `/ccdf/attendance-records` | List/filter attendance records | Provider, CaseWorker, ProgramAdmin |
| POST | `/ccdf/payments/{id}/reverse` | Reverse a PAID payment; raise a claim | ProgramAdmin |
| GET | `/ccdf/payments/{id}` | Read one payment | Provider, CaseWorker, ProgramAdmin |
| GET | `/ccdf/payments` | List/filter payments | Provider, CaseWorker, ProgramAdmin |
| POST | `/ccdf/overpayment-claims/{id}/record-recovery` | Record a recovery installment | ProgramAdmin |
| POST | `/ccdf/overpayment-claims/{id}/waive` | Waive an open claim | ProgramAdmin |
| GET | `/ccdf/overpayment-claims/{id}` | Read one overpayment claim | Provider, ProgramAdmin |
| GET | `/ccdf/overpayment-claims` | List/filter overpayment claims | ProgramAdmin |
| POST | `/ccdf/_clock/set_current_utc` | Set the logical clock and run the expiry sweep | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DETERMINATION_FAMILY_MISMATCH` | 409 |
| `ERR_PROVIDER_NOT_LICENSED` | 409 |
| `ERR_DETERMINATION_NOT_APPROVED` | 409 |
| `ERR_AUTHORIZATION_OVERLAP` | 409 |
| `ERR_RATE_CEILING_OVERLAP` | 409 |
| `ERR_INVALID_ATTENDANCE_DAYS` | 422 |
| `ERR_DUPLICATE_ATTENDANCE` | 409 |
| `ERR_NO_RATE_CEILING` | 422 |
| `ERR_NO_INCOME_STANDARD` | 422 |
| `ERR_RECOVERY_EXCEEDS_CLAIM` | 422 |
| `ERR_STALE_FAMILY_VERSION` | 412 |

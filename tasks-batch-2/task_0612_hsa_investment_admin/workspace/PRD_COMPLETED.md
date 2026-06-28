# Hsa Investment Admin API — Product Requirements Document

## 1. Introduction

This document specifies the HSA Investment & Administration Platform, a custodial back office for Health Savings Accounts modeled on the HealthEquity and Fidelity HSA experience. The platform carries an account from the moment a custodian opens it — through HDHP eligibility attestation, payroll and individual contributions, the IRS contribution-limit guardrail, the threshold-driven sweep of idle cash into investments, qualified-expense substantiation by debit card or reimburse-anytime receipt, excess-contribution correction, and the year-end generation of 1099-SA and 5498-SA tax snapshots.

Two themes dominate the design. The first is **ledger discipline**: every cent that moves between a holder's spendable cash, their invested balance, and the outside world is the product of a posted contribution, an executed sweep, a cleared distribution, or one of their compensating reversals, and the platform must keep these ledgers internally consistent at all times. The second is **separation of duties and regulatory guardrails**: the holder who requests money out is never the same operator who clears or substantiates it, payroll money is sponsored only by an employer, and the IRS annual ceiling is enforced before any over-funding can settle. Because contributions, corrections, and sweeps are all derived from a live account snapshot, the platform also defends against acting on stale reads using optimistic concurrency control on the account.

All monetary amounts in this system are integer counts of US cents; there are no fractional cents and no floating-point money. All timestamps are ISO 8601 in UTC. A single logical server clock — not wall-clock time — governs every date-derived field and stamp; it begins at the fixed default `2026-01-01T00:00:00Z` and only advances when an operator explicitly moves it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that hold across every endpoint. Where a rule has a natural business home it is also reinforced in Section 3; the two are consistent, never contradictory.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly three roles: `Accountholder`, `Employer`, and `AccountAdmin`.

- When `X-User-Role` is `Accountholder`, `X-User-ID` is the `id` of the acting `Accountholder` entity. Ownership checks on any resource that references an accountholder compare the resource's owning accountholder to `X-User-ID`. Concretely, for holder-scoped writes — verifying an account, requesting a distribution, and activating, suspending, or closing a card — the acting `Accountholder` must own the target HSA, meaning the account's `accountholder_id` equals `X-User-ID`; a mismatch is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403).
- When `X-User-Role` is `Employer`, `X-User-ID` is the `id` of the acting `Employer` entity. An employer may only create payroll contributions on, and read contributions of, accounts it sponsors; ownership ties the account's `employer_id` to `X-User-ID`.
- When `X-User-Role` is `AccountAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition demands it — for example, it writes the clearing operator's identifier onto a distribution's `cleared_by_user_id` — but it never compares it to any entity's `id`. This opaque identifier is the basis of the segregation-of-duties check described in Section 3.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific workflow says otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order, with any ties on `created_at` broken by the resource `id` in ascending order. The `meta` object of every list response carries the four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is addressed by an `id`, a server-minted UUID with no type prefix. Every resource also records a `created_at`, an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer that starts at creation and increments by one on each mutation.

There is one deliberate exception. A `TaxForm` is an immutable snapshot: it carries only `id` and `created_at` and has neither an `updated_at` nor a `version`, because once generated it is never updated. Every other entity — `Accountholder`, `Employer`, `PayrollPeriod`, `HsaAccount`, `CoveragePeriod`, `Contribution`, `InvestmentSweep`, `Distribution`, `Receipt`, `DebitCard`, and `ExcessCorrection` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

Derived fields count as mutations. When the platform recomputes a balance, a limit, a posture, or any other computed property on an account in response to an event, that recomputation refreshes the account's `updated_at` and increments its `version` exactly as a direct edit would.

### 2.5. Monetary Precision and Rounding

All money is stored and returned as integer cents; API bodies never carry fractional or string-formatted money. Where a calculation introduces division — notably the prorated contribution-limit variant — the platform performs the division and then takes the floor (rounds down toward zero), and the floor is applied once at the end of the computation rather than at each intermediate step, so the rounding order is fixed and reproducible. No calculation rounds half up; the only rounding direction in this system is floor, and most ledger math is exact integer addition and subtraction with no rounding at all.

### 2.6. Hierarchical Consistency and Bubble-Up Recomputation

The HSA account is the aggregate root, and many of its fields are computed rather than supplied. Whenever an event changes the inputs to those fields — a contribution posts, a contribution reverses, a coverage period is attested or superseded, the limit variant changes, a sweep moves cash, or a distribution clears or reverses — the platform re-derives the dependent account fields immediately and in dependency order, then mutates the account (refreshing `updated_at`, incrementing `version`). This re-derivation includes `contributions_ytd_cents`, `applicable_limit_cents`, `excess_contribution_cents`, and the `contribution_posture`, and it is what keeps the two parallel account dimensions aligned without a client ever asking for it on a specific resource.

The account carries two independent state dimensions that evolve on different triggers. The `lifecycle_status` dimension runs `PENDING_VERIFICATION`, `ACTIVE`, `FROZEN`, and `CLOSED`. The `contribution_posture` dimension is a derived flag, either `OPEN` or `LOCKED`: it is `OPEN` exactly when `lifecycle_status` is `ACTIVE` and `excess_contribution_cents` is zero, and `LOCKED` in every other case — that is, whenever uncorrected excess exists or the lifecycle is anything other than `ACTIVE`. Posture is recomputed (bubbled up) every time `contributions_ytd_cents`, `applicable_limit_cents`, or `lifecycle_status` changes.

### 2.7. Nested Resource Retrieval

Most resources are addressed under a parent path — for example a contribution lives beneath its account, and a payroll period lives beneath its employer. For any request whose path contains more than one identifier, the platform validates the identifiers left to right and rejects the first one that does not resolve with `ERR_NOT_FOUND` (HTTP 404). A child that exists but does not belong to the account or employer named earlier in the path is treated as not found under that path: the same `ERR_NOT_FOUND` applies. This ordered check runs before any state or business rule, so a stale or wrong parent surfaces as a 404 rather than as a later business error.

### 2.8. Optimistic Concurrency Control on the Account

Two write operations are guarded by optimistic concurrency control, because each derives its effect from a live account snapshot that another writer could have moved out from under the caller. Both require the caller to submit `expected_account_version` as a non-optional field carrying the `version` of the `HsaAccount` the caller last observed.

When a sweep is created against an account, `expected_account_version` must equal the account's current `version`. If another writer has advanced the account's version since the caller last read it — for instance by posting a contribution or clearing a distribution, both of which legitimately move cash and bump the version — the caller's view of investable cash is stale and the sweep is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412); no sweep is recorded. Likewise, when an excess correction is created, `expected_account_version` must equal the account's current `version`; if another writer has superseded a coverage period or posted a contribution since the read — changing the applicable limit or the contributions and bumping the version — the correction's requested amount is stale and the create is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Endpoints other than these two creates do not take a version field and are not subject to this check.

A successful sweep create and a successful correction create each increment the account's `version` by one as part of their effect.

### 2.9. Validation Ordering

When several checks guard one endpoint, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is next: a recognized but unpermitted role yields `ERR_FORBIDDEN`. Path resolution follows: every identifier in the path must exist and every child must belong to its stated parent, else `ERR_NOT_FOUND`. For holder-scoped account writes, ownership is then enforced — the acting accountholder must own the account, else `ERR_NOT_ACCOUNT_OWNER`. Body validation comes next: required fields must be present and well-typed, all monetary amounts must be positive integers, and every enum value must be valid, else `ERR_INVALID_REQUEST` (HTTP 422). Only after these gates does the platform evaluate state-machine eligibility (`ERR_INVALID_STATE`, HTTP 409) and the operation's domain-specific business rules. The segregation-of-duties check, the eligibility and posture guards, the temporal overlap checks, the fiscal guards, and the OCC version check all sit at this business layer, in the relative orders described in their respective Section 3 narratives. The OCC stale-version check is the last guard a sweep or correction create passes through.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Accountholders, Employers, and Payroll Calendars

Before an account can exist, a custodian (`AccountAdmin`) registers the people and sponsors involved. An accountholder is created with a `full_name`, a contact `email`, and a `date_of_birth`. The date of birth drives one important derived flag, `turns_55_or_older_in_plan_year`: it is true when the accountholder reaches age 55 or older at any point during the plan year of their open HSA, which is what makes them eligible for catch-up contributions. The age determination is computed at year granularity from the calendar years alone — the flag is true exactly when the account's `plan_year` minus the birth year of `date_of_birth` is at least 55, irrespective of the birth month or day; a malformed or missing `date_of_birth` yields false. This flag is evaluated lazily against the account's `plan_year` when the account is verified and whenever catch-up eligibility is tested. On the serialized accountholder the flag reads `null` until the first such evaluation (the owning account being verified) materializes it, and is a boolean thereafter.

An employer is the payroll sponsor. It is created with a `name` and an optional `payroll_contributions_enabled` flag that defaults to true. An admin may later toggle `payroll_contributions_enabled`; when it is false, payroll-channel contributions cannot be posted on accounts that name this employer.

An employer also owns a payroll calendar made of payroll periods. Each payroll period belongs to its sponsor through `employer_id` and is scheduled with a `period_start_day` and a `period_end_day`, both day-of-year indices. The window is **half-open**: it covers the days from `period_start_day` inclusive up to but not including `period_end_day`. A valid period satisfies `period_start_day` being at least 1, strictly less than `period_end_day`, and `period_end_day` being at most 366. A freshly scheduled period takes `status` `SCHEDULED`. Scheduling is rejected with `ERR_PAYROLL_PERIOD_OVERLAP` (HTTP 409) when the day bounds are invalid, or when the new half-open window overlaps any existing `SCHEDULED` period on the same employer. Two half-open windows overlap exactly when the first window's start is strictly less than the second's end and the second's start is strictly less than the first's end; consequently a period that ends on a given day and another that starts on that same day share no point and are allowed, but two windows that share a boundary day falling inside both is an overlap. A `CANCELLED` payroll period is excluded from this overlap check, so cancelling a period frees its window for reuse.

Cancelling a payroll period — an admin action — moves it from `SCHEDULED` to `CANCELLED`, and is permitted only while the period is `SCHEDULED`; otherwise the cancel is rejected with `ERR_INVALID_STATE`. Payroll periods can be listed under their employer, optionally filtered by `status`.

### 3.2. Opening and Activating an HSA

A custodian opens an HSA by naming the owning accountholder through `accountholder_id`, optionally naming a sponsor through `employer_id` (which may be omitted for an individual-only account), and supplying the `plan_year` the IRS limits apply to. The opener may also set `invest_threshold_cents`, the amount of cash kept liquid and not sweepable, which defaults to 200000 cents (two thousand dollars), and `sweep_increment_cents`, the whole-multiple granularity in which cash is swept, which defaults to 10000 cents (one hundred dollars). At open time the account starts in `lifecycle_status` `PENDING_VERIFICATION`; its `contribution_posture` is `LOCKED` until it becomes active; `cash_balance_cents`, `invested_balance_cents`, `contributions_ytd_cents`, and `applicable_limit_cents` all start at zero; and the platform mints a one-time `verification_token`. The `verification_token` is a field of the serialized account body and is returned on every account read and write, so the owning holder can read it back to activate; the active limit variant is not exposed on the serialized account.

Activation is performed by the owning accountholder, who submits the `verification_token`. The submitted token must equal the account's stored `verification_token`, else the request is rejected with `ERR_INVALID_TOKEN`. Activation also requires that the account already have at least one `ATTESTED` coverage period proving HDHP coverage; if none exists, activation is rejected with `ERR_HDHP_REQUIRED`. On success the account moves from `PENDING_VERIFICATION` to `ACTIVE`, its `applicable_limit_cents` is recomputed from its coverage, and its `contribution_posture` is re-derived to `OPEN` unless excess already exists.

An admin may freeze an active account, moving `lifecycle_status` from `ACTIVE` to `FROZEN`; this is permitted only from `ACTIVE` (else `ERR_INVALID_STATE`), and freezing forces `contribution_posture` to `LOCKED` regardless of whether any excess exists. Unfreezing reverses this: it is permitted only from `FROZEN` (else `ERR_INVALID_STATE`), returns the account to `ACTIVE`, and re-derives posture to `OPEN` unless `excess_contribution_cents` is greater than zero, in which case posture stays `LOCKED`. Closing an account is permitted only from `ACTIVE` (else `ERR_INVALID_STATE`) and additionally requires that no distribution is in an unfinished state — specifically, no distribution may be `REQUESTED`, and no distribution may be `CLEARED` while still unsubstantiated; a violation is rejected with `ERR_OPEN_DISTRIBUTION`. A successful close moves the account to `CLOSED`, forces `contribution_posture` to `LOCKED`, and cascades every `ACTIVE` debit card on the account to `CLOSED`.

### 3.3. HDHP Coverage and the Contribution Limit

The IRS contribution ceiling for an account is computed from its attested HDHP coverage. A coverage period is attested by an admin against the account, declaring a `coverage_tier` of either `SELF_ONLY` or `FAMILY`, a first covered month `effective_month`, and a last covered month `end_month`. Both months are indices from 1 to 12 within the plan year, and the interval is **closed-closed**: a period with effective month a and end month b covers months a through b inclusive. A new period is rejected with `ERR_COVERAGE_OVERLAP` (HTTP 409) when the months fall outside 1 through 12, when `effective_month` is greater than `end_month`, or when the closed-closed interval overlaps an existing `ATTESTED` period on the account. Two closed-closed intervals overlap exactly when the first's effective month is at most the second's end month and the second's effective month is at most the first's end month; adjacency, where one period ends at a month and the next begins at the following month, is allowed. A new coverage period takes `status` `ATTESTED`. An admin may supersede a coverage period, which is allowed only while it is `ATTESTED` and only while the account is not `CLOSED` (each failure is `ERR_INVALID_STATE`); superseding moves it to `SUPERSEDED`, after which it is excluded from all limit math, and triggers a recomputation of the account's `applicable_limit_cents`, `excess_contribution_cents`, and posture, which may newly lock the account.

The limit itself, `applicable_limit_cents`, is derived from the set of `ATTESTED` coverage periods only — `SUPERSEDED` periods never count — together with whether the holder is catch-up eligible via `turns_55_or_older_in_plan_year`. The platform first determines, for each month 1 through 12, that month's tier limit under a greatest-tier-per-month rule: if any attested period whose tier is `FAMILY` covers the month, the month takes the family monthly amount; otherwise if any attested period covers the month, it takes the self-only monthly amount; otherwise the month contributes nothing. The self-only annual figure is 432000 cents, the family annual figure is 862500 cents, and the catch-up annual figure is 100000 cents; a monthly tier amount is the corresponding annual figure divided by twelve, kept as exact cents.

The account computes its limit under one of two variants, and the default for every account is the **last-month rule**. The active variant is changed only by an admin setting it explicitly, supplying a `variant` of either `LAST_MONTH_RULE` or `PRORATED`; changing the variant recomputes `applicable_limit_cents`, then `excess_contribution_cents`, then re-derives posture, which may lock or unlock the account.

- Under `LAST_MONTH_RULE` (the default), the base limit is the full undivided annual figure for the coverage in force in December: it is the family annual figure of 862500 cents if month 12 is covered by an attested family period, otherwise the self-only annual figure of 432000 cents if month 12 is covered by any attested period, otherwise zero. When the holder is catch-up eligible, the catch-up component is the full undivided catch-up annual figure of 100000 cents; otherwise it is zero.
- Under `PRORATED`, the base limit is the sum over all twelve months of each month's tier amount, divided by twelve and floored — with the floor applied once at the very end, never per month. When the holder is catch-up eligible, the catch-up component is the catch-up annual figure of 100000 cents multiplied by the count of months whose tier amount is greater than zero, divided by twelve and floored, with the floor again applied once at the end; otherwise it is zero.

In both variants the final `applicable_limit_cents` is the base limit plus the catch-up component when the holder is catch-up eligible, and the base limit alone otherwise. The limit is recomputed on account verify, on coverage period create and supersede, on every contribution post, and on correction execute.

### 3.4. Contributions and the IRS Guardrail

Money enters the HSA as contributions. A contribution is created — by an admin, or by the sponsoring employer for the payroll channel — naming a `channel` of either `PAYROLL` or `INDIVIDUAL`, a positive `amount_cents`, and an optional `contribution_kind` of either `REGULAR` or `CATCH_UP` that defaults to `REGULAR`. A freshly created contribution takes `status` `PENDING` and moves no money yet; it can later be listed under the account, optionally filtered by `status` or `channel`.

Posting a pending contribution is an admin action that actually settles the money and runs the IRS guardrail. A post is permitted only when the account's `lifecycle_status` is `ACTIVE` (else `ERR_INVALID_STATE`) and the account's `contribution_posture` is `OPEN` at post time (else `ERR_POSTURE_LOCKED`). If the contribution is on the `PAYROLL` channel, the named employer's `payroll_contributions_enabled` must be true (else `ERR_PAYROLL_DISABLED`); an account that names no employer at all is likewise treated as payroll-disabled and a `PAYROLL` post on it is rejected with `ERR_PAYROLL_DISABLED`. If the contribution is `CATCH_UP`, the holder's `turns_55_or_older_in_plan_year` must be true (else `ERR_CATCHUP_INELIGIBLE`). On a successful post the contribution moves from `PENDING` to `POSTED`, its `posted_at` is stamped from the logical clock, and the account's `cash_balance_cents` increases by the contribution's `amount_cents`.

The guardrail then recomputes the account in a pinned order, because the values depend on one another. First, `contributions_ytd_cents` is set to the sum of `amount_cents` over all `POSTED` contributions in the plan year. Second, `applicable_limit_cents` is taken from the active limit variant (which depends on coverage, not on contributions). Third — but evaluated before the general excess is computed — the catch-up sub-limit is checked: the sum of `amount_cents` over `POSTED` `CATCH_UP` contributions must not exceed the catch-up component (the catch-up annual figure of 100000 cents, prorated under the prorated variant). A post that would push the posted catch-up sum above that sub-limit is rejected with `ERR_CATCHUP_LIMIT_EXCEEDED`. Because this catch-up guard is evaluated before the general excess, a contribution that breaches both the catch-up sub-limit and the overall limit is rejected with `ERR_CATCHUP_LIMIT_EXCEEDED` rather than any general-excess outcome. After the catch-up guard, `excess_contribution_cents` is set to the greater of zero and `contributions_ytd_cents` minus `applicable_limit_cents`. Finally posture is re-derived: it is `OPEN` exactly when the lifecycle is `ACTIVE` and `excess_contribution_cents` is zero, and `LOCKED` otherwise. A post that drives `excess_contribution_cents` above zero therefore bubbles the account's `contribution_posture` to `LOCKED`, after which any further attempt to post a contribution is rejected with `ERR_POSTURE_LOCKED` until the excess is corrected.

### 3.5. Sweeping Idle Cash into Investments

Cash that sits above the account's liquid floor can be swept into investments. A sweep is requested against the account by an admin or the holder and carries the OCC field `expected_account_version` (Section 2.8) and an optional `requested_amount_cents`. The platform computes how much can actually move. First it determines the excess cash as the greater of zero and `cash_balance_cents` minus `invest_threshold_cents`. Then it caps the move by the request: the cap is `requested_amount_cents` if one was supplied, otherwise the full excess cash. The sweepable raw amount is the smaller of the excess cash and that cap. The actual `swept_amount_cents` is the sweepable raw amount floored down to the nearest whole multiple of `sweep_increment_cents`. The threshold boundary is strict: `cash_balance_cents` must be strictly greater than `invest_threshold_cents` to yield anything, and at exactly the threshold the swept amount is zero. If the computed `swept_amount_cents` comes out as zero, the sweep is rejected with `ERR_NOTHING_TO_SWEEP` and no sweep row is persisted.

A successful sweep is recorded with `status` `EXECUTED`; the account's `cash_balance_cents` decreases by `swept_amount_cents` while its `invested_balance_cents` increases by the same amount, and the account's `version` increments by one. Sweeps can be listed under the account, optionally filtered by `status`. An admin may unwind an `EXECUTED` sweep — permitted only from `EXECUTED` (else `ERR_INVALID_STATE`) — which moves it to `UNWOUND` and reverses the move: `invested_balance_cents` decreases by `swept_amount_cents` and `cash_balance_cents` increases by the same amount, conserving the cash-plus-invested total.

### 3.6. Debit Cards

A debit card is issued against an account by an admin or the holder, recording a display-only `last_four`; a new card takes `status` `ISSUED`. Cards are discoverable by listing them under the account, optionally filtered by `status`. The holder drives a card through its lifecycle. Activating a card — permitted from `ISSUED` or from `SUSPENDED`, and requiring the account's `lifecycle_status` to be `ACTIVE` when activating from `ISSUED` — moves it to `ACTIVE`; an activation attempt from a state other than `ISSUED` or `SUSPENDED`, or against a non-active account from `ISSUED`, is rejected with `ERR_INVALID_STATE`. Suspending a card is permitted only from `ACTIVE` (else `ERR_INVALID_STATE`) and moves it to `SUSPENDED`; the card can be reactivated later, so `ACTIVE` and `SUSPENDED` cycle freely. Closing a card moves it to `CLOSED` from either `ACTIVE` or `SUSPENDED` and is terminal. As noted in Section 3.2, closing the account also cascades every `ACTIVE` card to `CLOSED`.

### 3.7. The Receipt Vault

The receipt vault supports reimburse-anytime substantiation: a holder (or an admin) can store proof of a qualified medical expense and attach it to a distribution whenever it is convenient, possibly long after the money moved. A receipt is vaulted against an account named by `account_id`, recording the `merchant`, the `service_date` on which the expense was incurred, a positive `amount_cents`, and an `is_qualified_medical` boolean by which the caller attests the expense is IRS-qualified. A new receipt takes `status` `VAULTED` and has no `distribution_id` yet. Receipts can be fetched individually and listed, with the list optionally filtered by `account_id`, by `distribution_id`, or by `status`; the `distribution_id` filter is the authoritative way to discover which receipt substantiates a given distribution, since `Receipt.distribution_id` is the back-link set when a receipt is consumed.

A receipt's `status` becomes `CONSUMED` once it is attached to a substantiated distribution, and returns to `VAULTED` if that distribution is later reversed, as described next.

### 3.8. Distributions: Request, Clear, Substantiate, Reverse

Money leaves the HSA as a distribution, and the flow is deliberately split across two people. The owning holder requests a distribution, naming a `method` of either `DEBIT_CARD` or `REIMBURSEMENT` and a positive `amount_cents`. When the method is `DEBIT_CARD`, the request names a `card_id` referencing a card on the same account, resolved at clear time; for a reimbursement the `card_id` is null. A newly requested distribution takes `status` `REQUESTED`, its `substantiation_status` is `UNSUBSTANTIATED`, and its `cleared_by_user_id` is null. Distributions can be listed under the account, optionally filtered by `status` or `substantiation_status`.

An admin then resolves the request. Clearing a distribution is permitted only while it is `REQUESTED`, requires the account's `lifecycle_status` to be `ACTIVE` (else `ERR_INVALID_STATE`), and requires the account's `cash_balance_cents` to be at least the distribution's `amount_cents` (else `ERR_INSUFFICIENT_CASH`). If the method is `DEBIT_CARD`, the referenced card must be in `ACTIVE` status at clear time (else `ERR_CARD_NOT_ACTIVE`); a `card_id` that is null, does not resolve to an existing card, or names a card on a different account is folded into this same `ERR_CARD_NOT_ACTIVE` at clear time rather than surfacing as `ERR_NOT_FOUND`. On a successful clear the distribution moves to `CLEARED`, the account's `cash_balance_cents` decreases by `amount_cents`, the platform stamps `cleared_by_user_id` with the acting admin's opaque `X-User-ID`, and the `substantiation_status` stays `UNSUBSTANTIATED` until it is substantiated. Alternatively the admin may deny a still-`REQUESTED` distribution, permitted only from `REQUESTED` (else `ERR_INVALID_STATE`), which moves it to `DENIED` with no cash movement; `DENIED` is terminal.

Substantiation is the two-person control point. An admin substantiates a `CLEARED` distribution, optionally supplying a `receipt_id`. The distribution must be `CLEARED` (else `ERR_INVALID_STATE`) and must still be `UNSUBSTANTIATED` (else `ERR_ALREADY_SUBSTANTIATED`). Crucially, the acting admin's `X-User-ID` must differ from the distribution's `cleared_by_user_id`: the operator who cleared a distribution may not be the one who substantiates it, and a same-operator attempt is rejected with `ERR_SEGREGATION_VIOLATION`. When a `receipt_id` is supplied, the referenced receipt must be `VAULTED` and must belong to the same account (else `ERR_RECEIPT_NOT_AVAILABLE`), and its `amount_cents` must be at least the distribution's `amount_cents` (else `ERR_RECEIPT_UNDERFUNDED`). On success the distribution stays `CLEARED` while its `substantiation_status` flips: it becomes `QUALIFIED` when a receipt is attached whose `is_qualified_medical` is true, and `NONQUALIFIED` otherwise. When a receipt is attached, that receipt's `status` becomes `CONSUMED`, its `distribution_id` is set to the distribution, and the distribution's `receipt_id` is set to the receipt.

An admin may reverse a `CLEARED` distribution — permitted only from `CLEARED` (else `ERR_INVALID_STATE`) — which moves it to `REVERSED` and refunds the money: the account's `cash_balance_cents` increases by `amount_cents`, conserving total funds. If a receipt had been consumed by the substantiation of that distribution, the reversal releases it: the receipt's `status` returns to `VAULTED` and its `distribution_id` is cleared.

### 3.9. Excess Correction: Unwinding Over-Contributions

When the guardrail leaves `excess_contribution_cents` above zero, the account is `LOCKED` and the holder must correct the excess. A correction is created against the account by an admin or the holder, supplying the OCC field `expected_account_version` (Section 2.8) and a `requested_amount_cents` that is intended to equal the current excess. At create time the only guards are body validation (`requested_amount_cents` and `expected_account_version` are both required and `requested_amount_cents` must be a positive integer, else `ERR_INVALID_REQUEST`) followed by the OCC version match; the create neither requires the account to be `ACTIVE` nor that excess currently exists nor that `requested_amount_cents` actually equals the excess — that equality is enforced only at execution time via `ERR_CORRECTION_AMOUNT_MISMATCH`. A new correction takes `status` `REQUESTED`, and creating it increments the account's `version` by one. Corrections can be listed under the account, optionally filtered by `status`. An admin may reject a still-`REQUESTED` correction, permitted only from `REQUESTED` (else `ERR_INVALID_STATE`), which moves it to `REJECTED` with no ledger movement — the excess remains and the posture stays `LOCKED`.

Executing a correction is an admin action that actually unwinds the over-contribution. Execution requires the account's `lifecycle_status` to be `ACTIVE` (else `ERR_INVALID_STATE`), requires that `excess_contribution_cents` is greater than zero at execution (else `ERR_NO_EXCESS`), and requires that the correction's `requested_amount_cents` equals the current `excess_contribution_cents` at execution (else `ERR_CORRECTION_AMOUNT_MISMATCH`). On success the correction moves to `COMPLETED` and its `corrected_amount_cents` is set to the excess measured at execution.

The cascade then reverses the most recent posted contributions until the excess is absorbed. The platform orders the `POSTED` contributions by `posted_at` descending, breaking ties by `created_at` descending and any remaining ties by `id` descending — latest first — and walks that order, marking each contribution `POSTED → REVERSED` and accumulating the reversed sum, until the accumulated reversed sum is at least the corrected amount. Contributions are atomic: the last contribution touched is reversed in full with no partial reversal, so the reversed sum may exceed the corrected amount. Each reversal lowers the account's `cash_balance_cents` by that contribution's `amount_cents` and recomputes `contributions_ytd_cents` downward. After the walk, `excess_contribution_cents` is recomputed and must be zero, since the reversed sum is at least the exact excess, and the account's `contribution_posture` bubbles back up to `OPEN`. (A `POSTED` contribution moves to `REVERSED` only through this correction cascade; `REVERSED` is terminal for a contribution.)

### 3.10. Tax Forms

At year end an admin generates immutable tax snapshots. A tax form is generated for the account naming a `form_type` of either `FORM_1099_SA` or `FORM_5498_SA` and a `tax_year`, which is expected to be the plan year but is accepted and stored verbatim as any integer the caller supplies — the platform does not validate `tax_year` against the account's `plan_year`. Because neither contributions nor distributions carry a per-row year, the totals below are computed over the account's qualifying rows regardless of the supplied `tax_year`; the phrases "in the plan year" and "in the tax year" therefore scope to the account, not to a separate year filter. The form's computed totals — `gross_amount_cents`, `nonqualified_amount_cents`, and `fair_market_value_cents` — are fixed at generation and never change thereafter. Tax forms can be fetched individually and listed under the account, with the list optionally filtered by `form_type` or `tax_year`.

For a `FORM_1099_SA` (the distribution form), the platform considers the distributions in the plan year whose `status` is `CLEARED` and which were not later reversed — `REVERSED` distributions are excluded from both totals. The `gross_amount_cents` is the sum of `amount_cents` over all of those included distributions, regardless of their substantiation. The `nonqualified_amount_cents` is the sum of `amount_cents` over only those included distributions whose `substantiation_status` is `NONQUALIFIED`, where for tax-reporting purposes an `UNSUBSTANTIATED` distribution is treated as `NONQUALIFIED`. On a `FORM_1099_SA`, `fair_market_value_cents` is zero.

For a `FORM_5498_SA` (the contribution form), the `gross_amount_cents` is the sum of `amount_cents` over all contributions in the tax year whose `status` is `POSTED`, and the `fair_market_value_cents` is a snapshot of the account's `cash_balance_cents` plus its `invested_balance_cents` taken at generation time. On a `FORM_5498_SA`, `nonqualified_amount_cents` is zero. All of these totals are exact integer sums or snapshots with no rounding.

### 3.11. The Logical Clock

Time in this system is governed by a logical server clock rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any operator moves it the clock holds precisely this default and never falls back to real time. An admin-only capability advances the clock by supplying a `to_iso8601` instant; thereafter the clock holds that value for subsequent reads. The clock is what stamps a contribution's `posted_at` and what every date-derived field — including the catch-up age determination — reads.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a distinct resource to a collection return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. The logical-clock setter returns `200 OK` with an empty data object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hsa/accountholders` | Create an Accountholder | AccountAdmin |
| GET | `/hsa/accountholders/{id}` | Get an Accountholder | AccountAdmin, Accountholder |
| POST | `/hsa/employers` | Create an Employer (payroll sponsor) | AccountAdmin |
| GET | `/hsa/employers/{id}` | Get an Employer | AccountAdmin, Accountholder |
| PATCH | `/hsa/employers/{id}` | Toggle payroll contributions on an Employer | AccountAdmin |
| POST | `/hsa/employers/{id}/payroll-periods` | Schedule a payroll period for an employer | AccountAdmin |
| GET | `/hsa/employers/{id}/payroll-periods` | List payroll periods for an employer | AccountAdmin |
| POST | `/hsa/employers/{id}/payroll-periods/{payroll_period_id}/cancel` | Cancel a scheduled payroll period | AccountAdmin |
| POST | `/hsa/accounts` | Open an HSA in PENDING_VERIFICATION | AccountAdmin |
| GET | `/hsa/accounts/{id}` | Get an HSA with derived balances and postures | AccountAdmin, Accountholder |
| GET | `/hsa/accounts` | List HSAs, filterable by accountholder or employer | AccountAdmin |
| POST | `/hsa/accounts/{id}/verify` | Activate a PENDING_VERIFICATION HSA | Accountholder |
| POST | `/hsa/accounts/{id}/freeze` | Freeze an ACTIVE HSA | AccountAdmin |
| POST | `/hsa/accounts/{id}/unfreeze` | Return a FROZEN HSA to ACTIVE | AccountAdmin |
| POST | `/hsa/accounts/{id}/close` | Close an ACTIVE HSA | AccountAdmin |
| POST | `/hsa/accounts/{id}/limit-variant` | Set the active contribution-limit variant | AccountAdmin |
| POST | `/hsa/accounts/{id}/coverage-periods` | Attest an HDHP coverage interval | AccountAdmin |
| GET | `/hsa/accounts/{id}/coverage-periods` | List coverage periods for an account | AccountAdmin, Accountholder |
| POST | `/hsa/accounts/{id}/coverage-periods/{coverage_period_id}/supersede` | Supersede a coverage period | AccountAdmin |
| POST | `/hsa/accounts/{id}/contributions` | Create a PENDING contribution | AccountAdmin, Employer |
| GET | `/hsa/accounts/{id}/contributions` | List contributions for an account | AccountAdmin, Accountholder, Employer |
| POST | `/hsa/accounts/{id}/contributions/{contribution_id}/post` | Post a PENDING contribution | AccountAdmin |
| POST | `/hsa/accounts/{id}/sweeps` | Sweep investable cash into investments | AccountAdmin, Accountholder |
| GET | `/hsa/accounts/{id}/sweeps` | List sweeps for an account | AccountAdmin, Accountholder |
| POST | `/hsa/accounts/{id}/sweeps/{sweep_id}/unwind` | Reverse an EXECUTED sweep back to cash | AccountAdmin |
| POST | `/hsa/accounts/{id}/cards` | Issue a debit card | AccountAdmin, Accountholder |
| GET | `/hsa/accounts/{id}/cards` | List cards for an account | AccountAdmin, Accountholder |
| POST | `/hsa/accounts/{id}/cards/{card_id}/activate` | Activate a card | Accountholder |
| POST | `/hsa/accounts/{id}/cards/{card_id}/suspend` | Suspend an ACTIVE card | Accountholder |
| POST | `/hsa/accounts/{id}/cards/{card_id}/close` | Close a card | Accountholder |
| POST | `/hsa/receipts` | Vault a receipt for an account | Accountholder, AccountAdmin |
| GET | `/hsa/receipts/{id}` | Get a vaulted receipt | Accountholder, AccountAdmin |
| GET | `/hsa/receipts` | List receipts by account or distribution | Accountholder, AccountAdmin |
| POST | `/hsa/accounts/{id}/distributions` | Request a distribution | Accountholder |
| GET | `/hsa/accounts/{id}/distributions` | List distributions for an account | AccountAdmin, Accountholder |
| POST | `/hsa/accounts/{id}/distributions/{distribution_id}/clear` | Clear a REQUESTED distribution | AccountAdmin |
| POST | `/hsa/accounts/{id}/distributions/{distribution_id}/deny` | Deny a REQUESTED distribution | AccountAdmin |
| POST | `/hsa/accounts/{id}/distributions/{distribution_id}/substantiate` | Substantiate a CLEARED distribution | AccountAdmin |
| POST | `/hsa/accounts/{id}/distributions/{distribution_id}/reverse` | Reverse a CLEARED distribution | AccountAdmin |
| POST | `/hsa/accounts/{id}/corrections` | Request an excess-contribution correction | AccountAdmin, Accountholder |
| GET | `/hsa/accounts/{id}/corrections` | List corrections for an account | AccountAdmin, Accountholder |
| POST | `/hsa/accounts/{id}/corrections/{correction_id}/execute` | Execute a correction | AccountAdmin |
| POST | `/hsa/accounts/{id}/corrections/{correction_id}/reject` | Reject a REQUESTED correction | AccountAdmin |
| POST | `/hsa/accounts/{id}/tax-forms` | Generate an immutable tax form snapshot | AccountAdmin |
| GET | `/hsa/accounts/{id}/tax-forms` | List tax forms for an account | AccountAdmin, Accountholder |
| GET | `/hsa/accounts/{id}/tax-forms/{tax_form_id}` | Get a specific tax form snapshot | AccountAdmin, Accountholder |
| POST | `/_clock/set_current_utc` | Set the logical server clock | AccountAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_ACCOUNT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_TOKEN` | 409 Conflict |
| `ERR_HDHP_REQUIRED` | 409 Conflict |
| `ERR_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_PAYROLL_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_PAYROLL_DISABLED` | 409 Conflict |
| `ERR_CATCHUP_INELIGIBLE` | 409 Conflict |
| `ERR_CATCHUP_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_POSTURE_LOCKED` | 409 Conflict |
| `ERR_SEGREGATION_VIOLATION` | 409 Conflict |
| `ERR_INSUFFICIENT_CASH` | 409 Conflict |
| `ERR_NOTHING_TO_SWEEP` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_RECEIPT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_RECEIPT_UNDERFUNDED` | 409 Conflict |
| `ERR_ALREADY_SUBSTANTIATED` | 409 Conflict |
| `ERR_OPEN_DISTRIBUTION` | 409 Conflict |
| `ERR_NO_EXCESS` | 409 Conflict |
| `ERR_CORRECTION_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |

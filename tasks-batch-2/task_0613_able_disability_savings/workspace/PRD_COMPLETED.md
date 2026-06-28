# Able Disability Savings API — Product Requirements Document

## 1. Introduction

The Able Disability Savings API administers a state-sponsored ABLE program — a tax-advantaged savings vehicle that lets a person with a disability accumulate assets without losing access to the means-tested benefits they depend on, principally Supplemental Security Income (SSI) and Medicaid. The platform sits at the intersection of three demanding concerns: eligibility certification (the disability must have begun before a statutory age), fiscal compliance (contributions are capped annually, distributions must be matched to qualified disability expenses, and a non-qualified withdrawal attracts an additional tax on its earnings), and benefit preservation (an ABLE balance is disregarded for benefit purposes only up to a federal threshold, and the two benefit programs disregard the same balance differently).

This document specifies the behaviour an implementation must reproduce: how a beneficiary is registered and certified, how an account is opened, funded, and drawn down, how investment elections are governed, how a 529 college-savings plan rolls into an ABLE account, and — at the end of the beneficiary's life — how a state Medicaid agency may recover medical assistance it paid through a tightly ordered payback waterfall. Because the system is simultaneously a ledger (every cent of basis, earnings, and balance must reconcile) and a compliance engine (every threshold and window has an exact boundary), the requirements below are precise about ordering, rounding, and inclusivity. The reference time source is a logical clock, not wall-clock time, so that certification windows and calendar-year accumulations are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `ProgramAdministrator`, `Beneficiary`, `AuthorizedRepresentative`, and `MedicaidAgency`. A request that omits `X-User-Role`, or whose value is not one of these four, is rejected with `ERR_UNAUTHENTICATED`. A syntactically valid role that is not permitted to perform the requested operation (per the role authorizations in Section 4) is rejected with `ERR_FORBIDDEN`.

The four roles bind to identity in two different ways. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`; ownership checks on any account-scoped resource compare the owning `Account`'s `beneficiary_id` to `X-User-ID`. When `X-User-Role` is `AuthorizedRepresentative`, `X-User-ID` is the `id` of the acting `AuthorizedRepresentative`; ownership is satisfied only when an `AuthorizedRepresentative` whose `id` equals `X-User-ID` exists on the target account and is in `ACTIVE` status. In both cases, an account-scoped write by a principal who is neither the owning beneficiary nor an active representative of that account is rejected with `ERR_NOT_ACCOUNT_OWNER`. When `X-User-Role` is `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`, and a `ProgramAdministrator` is never subject to the account-ownership check. Likewise, when `X-User-Role` is `MedicaidAgency`, `X-User-ID` is an opaque agency identifier not tied to any persisted entity; it is not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and a supplied value outside that range is silently clamped into it (a `limit` below 1 becomes 1, a `limit` above 100 becomes 100). `offset` sets the number of items to skip from the front of the result set and defaults to 0, and a negative `offset` is silently clamped to 0. A `limit` or `offset` that is present but not a valid integer is rejected with `ERR_INVALID_REQUEST`. Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, and resources sharing the same `created_at` instant (common because the logical clock may not have advanced between creations) are ordered by their server-side creation sequence, which is the order in which they were created. The `meta` object of every list response carries the `limit`, `offset`, `total_count`, and `has_more` fields.

### 2.4. Common Resource Properties and Identity

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered in ISO 8601 UTC with three fractional digits. Resources that can be modified after creation additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at its initial value and increases by one on every mutation of that resource. In this domain the entities `Program`, `InvestmentOption`, `Beneficiary`, `Certification`, `Account`, `AuthorizedRepresentative`, `Contribution`, `Distribution`, `QDERecord`, and `MedicaidClaim` all carry the full set of `id`, `created_at`, `updated_at`, and `version`. When the server derives a computed field on an entity (for example, refreshing an `Account`'s balance or an `Account`'s `ssi_posture`), that derivation is a mutation: it advances `updated_at` and increments `version`.

### 2.5. Nested Resource Retrieval and Validation Ordering

Many resources are addressed through nested paths — a Medicaid claim, for instance, is reached through its account. When a path carries more than one identifier, the server validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. This existence sweep is part of a fixed precedence that governs every write. Authentication of the role header runs first (`ERR_UNAUTHENTICATED`); then role authorization for the operation (`ERR_FORBIDDEN`); then existence of every path-referenced resource, left to right (`ERR_NOT_FOUND`); then, for account-scoped writes performed by a `Beneficiary` or `AuthorizedRepresentative`, the account-ownership check (`ERR_NOT_ACCOUNT_OWNER`); then request-body well-formedness — required fields present, correctly typed, enum members valid, and any `amount_cents` strictly greater than zero (`ERR_INVALID_REQUEST`); then, where a write supplies a foreign-key identifier in its request body (for example a `program_id`, `beneficiary_id`, or `investment_option_id`), existence of that body-referenced resource, which when it does not resolve is rejected with `ERR_NOT_FOUND` after body well-formedness has already passed; then, for a state-transition endpoint, whether the target resource is in a legal state for the transition (`ERR_INVALID_STATE`); then, on the two optimistic-concurrency-guarded writes, the stale-version check (`ERR_STALE_ACCOUNT_VERSION`); then, for contribution and distribution writes, the account-open check (`ERR_ACCOUNT_NOT_OPEN`); and finally the operation's own business rules in the order described in their respective workflows below. A check earlier in this precedence always masks one later in it.

### 2.6. Optimistic Concurrency Control

Two writes are guarded by optimistic concurrency control on the owning `Account`'s `version`, and only these two: posting a contribution to an account, and disbursing an approved distribution. Each requires the caller to supply `expected_account_version` as a non-optional field carrying the `version` of the `Account` the client last observed. Posting a contribution is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) when `expected_account_version` does not equal the account's current `version` — a prior writer's contribution will have raised basis and balance and consumed annual-cap headroom, so the current writer's view of remaining cap is stale and the create must be refused rather than overwrite an unobserved state. Disbursing an approved distribution is likewise rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) when `expected_account_version` does not match the account's current `version`, because an intervening contribution or disbursement may have changed the balance-and-earnings ratio that the pro-rata split depends on, leaving the disbursing client's snapshot stale. No other endpoint accepts or requires a version field.

### 2.7. Monetary Precision and Calendar Accounting

All monetary quantities are stored and exchanged as integer cents; field names ending in `_cents` are always whole numbers of cents. Where a calculation introduces a fraction — the pro-rata earnings split of a disbursement, the additional tax on a non-qualified amount, and the monthly management fee — the result is rounded to whole cents using the round-half-up convention (a half-cent rounds away from zero). Comparisons that the law expresses in dollars are evaluated in cents with the exact operator the rule names; in particular the SSI tests at the hundred-thousand-dollar disregard ceiling and the two-thousand-dollar resource limit are strict greater-than comparisons, so a balance exactly at a boundary does not trip it. Year-to-date accumulations (regular contributions, ABLE-to-Work contributions, and investment-option changes) are scoped to the calendar year of the logical clock at the time of the operation.

### 2.8. The Logical Clock

The system keeps a logical clock rather than reading wall-clock time. At server startup the clock reads `2026-01-01T00:00:00Z`, and it never falls back to wall time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant; on success it returns a `data` object carrying a single `current_utc` field holding the new clock instant rendered in ISO 8601 UTC with three fractional digits. Advancing the clock has consequences: any `Certification` in `CERTIFIED` status whose recertification deadline has been reached or passed is moved to `EXPIRED`, and if that certification's beneficiary has an `Account` in `OPEN` status, the account is moved to `SUSPENDED`. The clock is the authority for a contribution's posting date, for the calendar-year scoping of year-to-date totals, and for evaluating whether a certification's validity window currently contains the present moment.

### 2.9. Eligibility, Certification Windows, and Authority Windows

A beneficiary's `eligibility_status` is computed, never set directly. It reads `CERTIFIED` when the beneficiary has a `Certification` in `CERTIFIED` status whose validity window contains the current logical-clock moment; otherwise it mirrors the status of the beneficiary's certification with the greatest `effective_date` (and, on a tie, the greatest `created_at`); and it reads `UNCERTIFIED` when the beneficiary has no certifications at all. The possible values are `UNCERTIFIED`, `CERTIFIED`, `DENIED`, and `EXPIRED`.

A certification's validity window is the half-open interval that runs from its `effective_date` up to but not including its `expires_on`. Two certification windows for the same beneficiary overlap when the new window's `effective_date` falls before the existing window's `expires_on` and the existing window's `effective_date` falls before the new window's `expires_on`; under this half-open rule, two windows that merely share an endpoint — one ending on exactly the date the next begins — do not overlap. By deliberate contrast, an authorized representative's authority window is the closed interval from `authority_start` to `authority_end`, both inclusive. Two authority windows on the same account, for the same `relationship`, where both representatives are `ACTIVE`, overlap when the new window's `authority_start` is on or before the existing window's `authority_end` and the existing window's `authority_start` is on or before the new window's `authority_end`; under this closed rule, two authority windows that touch at a shared endpoint date do overlap. The half-open certification rule and the closed authority rule are intentionally different and must not be conflated.

## 3. Business Logic & Workflows

### 3.1. Program Configuration and Investment Options

A `ProgramAdministrator` stands up the state program by registering a `Program`. A program carries a `name`, a `state_code` for the administering state (conventionally a two-letter code, but only validated as a required non-empty string — its length and format are not enforced), and the numeric parameters that drive every downstream rule: the base `annual_contribution_cap_cents` (the federal gift-tax exclusion expressed in cents), the `able_to_work_fpl_cents` ceiling (the single-person federal poverty line, in cents, that caps additional ABLE-to-Work contributions), the `program_fee_bps` annual management fee in basis points, and several parameters that take defaults when omitted. The `ssi_suspension_threshold_cents` is the ABLE-balance disregard ceiling for SSI and defaults to ten million cents (one hundred thousand dollars). The `ssi_resource_limit_cents` is the SSI countable-resource limit and defaults to two hundred thousand cents (two thousand dollars). The `nonqualified_additional_tax_pct` is the rate applied to the earnings portion of a non-qualified withdrawal and defaults to one tenth. The `max_investment_changes_per_year` caps investment-option changes and defaults to two. The `disability_onset_max_age` is the maximum age at disability onset for eligibility and defaults to twenty-six.

Against a program, the administrator publishes one or more investment portfolios. An `InvestmentOption` references its program through `program_id`, carries a portfolio `name`, a `risk_tier` that is one of `CONSERVATIVE`, `MODERATE`, `AGGRESSIVE`, or `CASH`, and an `is_open` flag — defaulting to true — that indicates whether the portfolio accepts new elections. Both programs and investment options are readable by `ProgramAdministrator`, `Beneficiary`, and `AuthorizedRepresentative` — but not by `MedicaidAgency`, which is rejected with `ERR_FORBIDDEN` — and only a `ProgramAdministrator` may create them. Investment options may be listed and optionally filtered by `program_id`.

### 3.2. Registering and Certifying a Beneficiary

A `ProgramAdministrator` registers a `Beneficiary` against a program via `program_id`. The record captures the beneficiary's `full_name`, `birth_date` (an ISO 8601 calendar date), `disability_onset_date` (the date the qualifying disability began), and `state_code` of residence. Several means-test inputs default when omitted: `other_countable_resources_cents` (non-ABLE countable resources, defaulting to zero), `receives_ssi` and `receives_medicaid` (both defaulting to false), `employer_retirement_plan_participant` (defaulting to false, and relevant because participation disqualifies ABLE-to-Work contributions), and `gross_employment_income_ytd_cents` (defaulting to zero, and relevant because it caps ABLE-to-Work contributions). A newly registered beneficiary is born with `eligibility_status` of `UNCERTIFIED`, with the computed `is_deceased` flag false. Beneficiaries are readable by any role and may be listed and optionally filtered by `program_id`.

Certification establishes eligibility. A `ProgramAdministrator` creates a `Certification` for a beneficiary, supplying the eligibility `basis` — either `SSI_SSDI_ENTITLEMENT` or `DISABILITY_DIAGNOSIS` — an `effective_date`, and an `expires_on` recertification deadline. When the basis is `DISABILITY_DIAGNOSIS`, the request must also carry a non-empty `diagnosis_code`; a diagnosis-based certification created without one is rejected with `ERR_DIAGNOSIS_REQUIRED`. Before the record is created, the proposed window is checked for overlap against every existing certification of the beneficiary regardless of that certification's status, using the half-open rule of Section 2.9; an overlap is rejected with `ERR_CERT_WINDOW_OVERLAP`. A successfully created certification begins in `PENDING` status, and the `beneficiary_id` ties it to its beneficiary. Certifications are readable by any role and may be listed and optionally filtered by `beneficiary_id`.

A pending certification is resolved by a `ProgramAdministrator` supplying a `decision`. A decision to approve moves the certification from `PENDING` to `CERTIFIED`, but only after two preconditions hold: the beneficiary's age at disability onset, measured from `birth_date` to `disability_onset_date`, must be strictly less than the program's `disability_onset_max_age` — otherwise the approval is rejected with `ERR_ONSET_AGE_INELIGIBLE` — and, if the basis is `DISABILITY_DIAGNOSIS`, a non-empty `diagnosis_code` must be present (`ERR_DIAGNOSIS_REQUIRED`). On approval the certification's `status` becomes `CERTIFIED` and the beneficiary's `eligibility_status` is recomputed. A decision to deny carries no preconditions: it moves the certification from `PENDING` to `DENIED` and recomputes the beneficiary's `eligibility_status`. `DENIED` and `EXPIRED` are terminal certification states.

A certification leaves `CERTIFIED` for `EXPIRED` not by request but by the passage of the logical clock: when the clock advances to or past a certified certification's `expires_on` — so that the half-open window no longer contains the present moment — the certification's `status` becomes `EXPIRED`, the beneficiary's `eligibility_status` is recomputed to `EXPIRED`, and, as a cross-entity consequence, the beneficiary's `Account` is moved from `OPEN` to `SUSPENDED` to reflect the eligibility lapse. To regain eligibility the administrator creates a new, non-overlapping certification window and approves it, then reinstates the account.

### 3.3. Opening and Operating the Account

A `ProgramAdministrator` opens an `Account` for a beneficiary by supplying `beneficiary_id` and the initially elected `investment_option_id`. Two cumulative figures may be seeded at open time and otherwise default to zero: `medicaid_paid_since_open_cents` (medical assistance Medicaid has paid on the beneficiary's behalf since the account was established) and `premiums_paid_by_beneficiary_cents` (Medicaid buy-in premiums the beneficiary paid while alive, which later reduce any payback claim). A new account starts in `OPEN` status with every ledger figure at zero and an `ssi_posture` of `SSI_OK`. The account is the lifecycle owner of contributions, distributions, authorized representatives, investment changes, and Medicaid claims; it is readable by any role and may be listed and filtered by `beneficiary_id` or `investment_option_id`.

The account exposes a fully computed ledger. Its `basis_cents` is the sum of the amounts of all `POSTED` contributions (the cost basis). Its `earnings_cents` is investment earnings credited through the market-crediting capability minus the earnings portion of distributions. Its `balance_cents` is basis plus earnings minus what has been distributed. Two year-to-date accumulators track cap usage: `regular_contrib_ytd_cents` sums the amounts of `POSTED` `REGULAR` and `ROLLOVER_529` contributions in the current calendar year (both count toward the annual cap), while `atw_contrib_ytd_cents` sums the amounts of `POSTED` `ABLE_TO_WORK` contributions in the current calendar year. The `investment_changes_ytd` counter records investment-option changes made in the current calendar year. The `ssi_posture` field, one of `SSI_OK` or `SSI_SUSPENDED`, reflects the live means-test posture described in Section 3.7.

An administrator may suspend an account that is in `OPEN` status, moving it to `SUSPENDED`; a suspend attempt against an account in any other status is rejected with `ERR_INVALID_STATE`. While suspended, contributions and distributions are blocked. The same suspension is triggered automatically when a certification expires, as described above. Reinstatement returns an account from `SUSPENDED` to `OPEN`, but only when the beneficiary's `eligibility_status` is `CERTIFIED`; a reinstatement attempted against an account not in `SUSPENDED` status is rejected with `ERR_INVALID_STATE` (this state check precedes the certification check, so an `OPEN` account whose beneficiary is uncertified still yields `ERR_INVALID_STATE`), and a reinstatement of a `SUSPENDED` account whose beneficiary is not certified is rejected with `ERR_NOT_CERTIFIED`. An account loops between `OPEN` and `SUSPENDED` across its working life and leaves that loop only through death.

A market-crediting capability, available to a `ProgramAdministrator`, simulates investment movement: given an `account_id` (which must resolve to an existing account, otherwise `ERR_NOT_FOUND`) and an `earnings_delta_cents` (a required integer that may be negative for a loss or zero), it adjusts the account's `earnings_cents` and `balance_cents` by that delta, recomputes `ssi_posture`, and increments the account's `version` by one, returning the updated account resource.

### 3.4. Investment Elections and the Annual Change Limit

A `Beneficiary` or an `AuthorizedRepresentative` may re-elect the account's portfolio by supplying a new `investment_option_id`. A successful change updates the account's `investment_option_id` and increments `investment_changes_ytd` by one. The change is barred when the number of investment-option changes already made in the current calendar year has reached the program's `max_investment_changes_per_year`; an attempt that would carry the count beyond that ceiling is rejected with `ERR_INVESTMENT_CHANGE_LIMIT`. Because this is an account-scoped write, it is subject to the ownership check of Section 2.1.

### 3.5. Authorized Representatives

Authority over an account may be delegated. A `ProgramAdministrator` or the owning `Beneficiary` adds an `AuthorizedRepresentative` to an account by supplying the representative's `full_name`, the `relationship` — one of `PARENT`, `GUARDIAN`, `POA_AGENT`, or `SPOUSE` — and the closed authority window bounded by `authority_start` and `authority_end`. Before creation, the proposed window is tested for overlap against every `ACTIVE` representative on the same account whose `relationship` matches the new one, using the closed-interval rule of Section 2.9 in which a shared endpoint date does collide; revoked representatives are ignored. An overlap is rejected with `ERR_REP_AUTHORITY_OVERLAP`. A new representative begins in `ACTIVE` status and ties to its account through `account_id`. Representatives are readable by any role and may be listed and filtered by `account_id`.

A representative may be revoked by a `ProgramAdministrator` or the owning `Beneficiary`; an `ACTIVE` representative moves to `REVOKED` and can no longer act on the account, while an attempt to revoke a representative that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. `REVOKED` is terminal. Revocation also happens automatically as a cascade when the account freezes at death, described in Section 3.9.

### 3.6. Contributions: Types, Caps, and Reversal

Money enters an account as a `Contribution`, posted by a `ProgramAdministrator`, the owning `Beneficiary`, or an `AuthorizedRepresentative`. The request names the `contribution_type` — one of `REGULAR`, `ABLE_TO_WORK`, or `ROLLOVER_529` — an `amount_cents` strictly greater than zero, and `expected_account_version`; when the type is `ROLLOVER_529` it must additionally carry a non-empty `source_529_plan` naming the source plan, and a rollover that omits it is rejected with `ERR_INVALID_REQUEST`. The account must be `OPEN`; a contribution attempted against any other status is rejected with `ERR_ACCOUNT_NOT_OPEN`. The optimistic-concurrency check of Section 2.6 applies.

Before a contribution is admitted, it passes a headroom test that depends on its type, evaluated against the current calendar-year year-to-date totals. For a `REGULAR` or `ROLLOVER_529` contribution, the room remaining under the annual cap is the program's `annual_contribution_cap_cents` minus the account's `regular_contrib_ytd_cents`; if `amount_cents` exceeds that room, the contribution is rejected with `ERR_ANNUAL_CAP_EXCEEDED`. A `ROLLOVER_529` contribution faces an additional single-rollover ceiling layered on top of that test: a single rollover may not on its own exceed the program's `annual_contribution_cap_cents`, and one that does is rejected with `ERR_ROLLOVER_LIMIT_EXCEEDED`. The order of these two rollover checks is fixed — the annual-cap test runs first — so a rollover that breaches both yields `ERR_ANNUAL_CAP_EXCEEDED` rather than `ERR_ROLLOVER_LIMIT_EXCEEDED`. For an `ABLE_TO_WORK` contribution, the beneficiary must not be an `employer_retirement_plan_participant`; one who is is rejected with `ERR_ATW_INELIGIBLE`. The ABLE-to-Work ceiling is the smaller of the program's `able_to_work_fpl_cents` and the beneficiary's `gross_employment_income_ytd_cents`, and the room remaining is that ceiling minus the account's `atw_contrib_ytd_cents`; if `amount_cents` exceeds that room, the contribution is rejected with `ERR_ATW_CAP_EXCEEDED`. A contribution that fails any of these checks returns an error and is not persisted — there is no rejected contribution state.

A successful contribution is created in `POSTED` status with its `contribution_date` stamped from the logical clock as an ISO 8601 calendar date (`YYYY-MM-DD`, the date portion of the clock instant, not a full timestamp). Posting raises the account's `basis_cents` and `balance_cents` by `amount_cents`, raises the matching year-to-date total — `regular_contrib_ytd_cents` for `REGULAR` and `ROLLOVER_529`, or `atw_contrib_ytd_cents` for `ABLE_TO_WORK` — by `amount_cents`, recomputes `ssi_posture`, and increments the account's `version` by one. Contributions are readable by any role and may be listed and filtered by `account_id`.

A posted contribution may be reversed by a `ProgramAdministrator` as a compensating action, but only while the contribution is `POSTED` and the account is `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`). Reversal moves the contribution to `REVERSED`, decreases the account's `basis_cents` and `balance_cents` by `amount_cents`, decreases the matching year-to-date total by `amount_cents` so that cap headroom is restored, recomputes `ssi_posture`, and increments the account's `version` by one. `REVERSED` is terminal for a contribution.

### 3.7. The Means Test: SSI Versus Medicaid

The account's SSI posture is recomputed after any contribution is posted or reversed, after any distribution is disbursed, after earnings are credited, and on demand through the means-test capability. The SSI computation works in two steps. First, the portion of the ABLE balance that counts against SSI is the amount by which `balance_cents` exceeds the program's `ssi_suspension_threshold_cents`, floored at zero — so a balance at or below one hundred thousand dollars contributes nothing. Second, the total countable resources for SSI are the beneficiary's `other_countable_resources_cents` plus that countable ABLE portion; if that total is strictly greater than the program's `ssi_resource_limit_cents` (two thousand dollars), the account's `ssi_posture` is `SSI_SUSPENDED`, and otherwise it is `SSI_OK`. Suspension here means SSI is suspended, not terminated.

The means-test capability is readable by any role and computes the impact for a named `variant` supplied as a query parameter on the GET request; the only accepted values are `SSI` and `MEDICAID`, and a missing or otherwise-valued `variant` is rejected with `ERR_INVALID_REQUEST`. For the SSI variant it applies the rule just described, computing the posture freshly from the SSI rule rather than reading the account's stored field: the response's `able_countable_for_ssi_cents` is the ABLE portion above the threshold, `total_countable_cents` is that portion plus the beneficiary's other countable resources, `ssi_posture` echoes the resulting posture (`SSI_SUSPENDED` when `total_countable_cents` is strictly greater than the resource limit, else `SSI_OK`), and `affects_benefit` is `true` exactly when that posture is `SSI_SUSPENDED`. The Medicaid variant is deliberately different: the entire ABLE balance is disregarded for Medicaid regardless of the hundred-thousand-dollar threshold, so only the beneficiary's `other_countable_resources_cents` is countable and the same balance that can suspend SSI never affects Medicaid the same way. Under the Medicaid variant the response's `able_countable_for_ssi_cents` is reported as zero, `total_countable_cents` is the beneficiary's `other_countable_resources_cents` alone, `ssi_posture` echoes the account's current stored `ssi_posture` field unchanged, and `affects_benefit` is always `false`. The response shape is the same for both variants — carrying `variant`, `able_countable_for_ssi_cents`, `total_countable_cents`, `ssi_posture`, and `affects_benefit` — but under the Medicaid variant the ABLE balance never contributes to the countable total.

### 3.8. Distributions: Request Through Substantiation or Clawback

A distribution draws money out for a qualified disability expense. A `ProgramAdministrator`, the owning `Beneficiary`, or an `AuthorizedRepresentative` requests a `Distribution` by supplying `amount_cents` strictly greater than zero and a `category` from the set `HOUSING`, `EDUCATION`, `HEALTH`, `TRANSPORTATION`, `BASIC_LIVING`, `LEGAL`, and `OTHER`. Requesting a distribution does not require the account to be `OPEN` and performs no balance check; the account-open and balance gates apply only at approval and disbursement (the account-open check named in Section 2.5 does not cover the request step). The new distribution is created in `REQUESTED` status, tied to its account through `account_id`. A distribution's computed fields — `earnings_portion_cents`, `qualified_amount_cents`, `nonqualified_amount_cents`, `additional_tax_cents`, and the `counts_against_ssi_housing` flag (which would mark a retained housing distribution that affects SSI, but is initialized to `false` on a requested distribution and is never set to `true` by any transition, so it remains `false` throughout the distribution's lifecycle) — populate as the distribution advances. Distributions are readable by any role and may be listed and filtered by `account_id`.

Approval, performed by the owning `Beneficiary` or an `AuthorizedRepresentative`, moves the distribution from `REQUESTED` to `APPROVED`, but only when the account is `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`) and the requested `amount_cents` does not exceed the account's `balance_cents` (otherwise `ERR_INSUFFICIENT_BALANCE`). A `ProgramAdministrator` may instead reject a still-`REQUESTED` distribution, moving it to `REJECTED`, which is terminal.

Disbursement, performed by the owning `Beneficiary` or an `AuthorizedRepresentative`, moves the distribution from `APPROVED` to `DISBURSED` and is the moment money leaves the account. It requires `expected_account_version` (the optimistic-concurrency check of Section 2.6), the account being `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`), and the `amount_cents` not exceeding the account's `balance_cents` (otherwise `ERR_INSUFFICIENT_BALANCE`). At disbursement the system captures a pro-rata earnings split, fixed at that instant so that later balance changes never retroactively move this distribution's split. The earnings ratio is zero when the account's `balance_cents` is zero, and otherwise is the account's `earnings_cents` divided by its `balance_cents`. The distribution's `earnings_portion_cents` is `amount_cents` multiplied by that ratio, rounded half up to whole cents; the basis portion is `amount_cents` minus that earnings portion. The account's `earnings_cents` is then reduced by the earnings portion, its `basis_cents` is reduced by the basis portion, its `balance_cents` is reduced by the full `amount_cents`, its `ssi_posture` is recomputed, and its `version` is incremented by one.

A disbursed distribution is resolved one of two ways. The owning `Beneficiary` or an `AuthorizedRepresentative` may substantiate it: substantiation moves it from `DISBURSED` to `SUBSTANTIATED`, but only when the sum of the `amount_cents` of every `QDERecord` attached to the distribution equals the distribution's own `amount_cents` (otherwise `ERR_QDE_MISMATCH`). On substantiation the distribution's `qualified_amount_cents` is set to its full `amount_cents`, its `nonqualified_amount_cents` to zero, and its `additional_tax_cents` to zero. Alternatively, a `ProgramAdministrator` may claw back a disbursed distribution, moving it from `DISBURSED` to `CLAWED_BACK`; this runs the non-qualified penalty described in Section 3.10. `SUBSTANTIATED` and `CLAWED_BACK` are terminal.

To substantiate, the account holder attaches one or more qualified-disability-expense records to a disbursed distribution. A `QDERecord`, created by the owning `Beneficiary` or an `AuthorizedRepresentative`, references its distribution through `distribution_id` and carries an `expense_category` from the same seven-value set as a distribution's category, an `amount_cents` strictly greater than zero, a `receipt_reference`, and an `expense_date`. Attaching a QDE record does not check the parent distribution's status: a record may be created against a distribution in any status, and no `ERR_INVALID_STATE` is raised on attachment (the disbursed-state requirement is enforced only at substantiation, not at attachment). QDE records are readable by any role and may be listed and filtered by `distribution_id`.

### 3.9. Death, the Distribution Cascade, and Account Freeze

A `ProgramAdministrator` records a beneficiary's death, provided the beneficiary is not already deceased (the computed `is_deceased` flag must be false); an attempt to record death for a beneficiary already marked deceased is rejected with `ERR_INVALID_STATE`. Recording death returns the updated beneficiary resource and sets `is_deceased` to true and freezes the account: an account in `OPEN` or `SUSPENDED` moves to `FROZEN_DEATH`. The freeze cascades. Every `ACTIVE` `AuthorizedRepresentative` on the account moves to `REVOKED`. Every distribution still in `REQUESTED` or `APPROVED` status moves to `REJECTED`, since no further disbursements may be made to a deceased beneficiary. While the account is `FROZEN_DEATH`, no new contributions or distributions are permitted (`ERR_ACCOUNT_NOT_OPEN`). Death is recorded on the beneficiary but its consequences land on the account and its children; `FROZEN_DEATH` is the precondition for the Medicaid payback that follows.

### 3.10. The Non-Qualified Penalty

When a disbursed distribution is clawed back, the system settles its qualified and non-qualified portions and computes the additional tax; clawback records these figures on the distribution only and does not move the owning account's ledger — `balance_cents`, `basis_cents`, `earnings_cents`, `ssi_posture`, and `version` are all left unchanged, and the disbursed funds are not restored to the account. The `qualified_amount_cents` is the sum of the `amount_cents` of the QDE records attached to the distribution. The `nonqualified_amount_cents` is the distribution's `amount_cents` minus that qualified sum, floored at zero. The penalty applies only to the earnings within that non-qualified portion: when the distribution's `amount_cents` is zero the non-qualified earnings are zero, and otherwise the non-qualified earnings are the distribution's `earnings_portion_cents` (the split captured at disbursement) multiplied by the ratio of `nonqualified_amount_cents` to the distribution's `amount_cents`. The `additional_tax_cents` is those non-qualified earnings multiplied by the program's `nonqualified_additional_tax_pct`, rounded half up to whole cents. A distribution that was fully substantiated has no non-qualified amount, so its additional tax is zero.

### 3.11. The Program Management Fee

A `ProgramAdministrator` assesses the program management fee for a period by supplying a `period_end_balance_cents` and a number of `months`. The monthly rate is the program's `program_fee_bps`, converted from basis points to a fraction by dividing by ten thousand and then divided by twelve to make it monthly. The monthly fee is `period_end_balance_cents` multiplied by that monthly rate, rounded half up to whole cents. The fee for the period is that rounded monthly fee multiplied by the number of `months`. The order is pinned: each monthly fee is rounded to whole cents first, and the rounded monthly figure is then multiplied across the months — rounding per period and then summing, never rounding a single annual figure, because the two can differ by a few cents and the per-period rounding is authoritative. The resulting total fee then reduces the account's `balance_cents` only — `basis_cents` and `earnings_cents` are left unchanged — after which the account's `ssi_posture` is recomputed and its `version` is incremented by one.

### 3.12. Medicaid Payback at Death

After death, a `MedicaidAgency` files a Medicaid payback claim against the deceased beneficiary's frozen account, supplying the `claimed_amount_cents` it asserts it paid since the account opened; `claimed_amount_cents` must be an integer strictly greater than zero, and a value that is zero or negative is rejected with `ERR_INVALID_REQUEST`. Filing is not gated on the account's status: the account need only exist, and filing succeeds regardless of whether the account is `FROZEN_DEATH`, `OPEN`, `SUSPENDED`, or `CLOSED`. Filing computes the payback through a waterfall whose order is pinned. First, any distributions still in `APPROVED` status are taken off the top: the post-bucket balance is the account's `balance_cents` minus the sum of the `amount_cents` of those approved-but-unpaid distributions, floored at zero. Next, the beneficiary's lifetime premiums are deducted from the gross claim: the claimable amount is `claimed_amount_cents` minus `premiums_paid_by_beneficiary_cents`, floored at zero. The `allowed_payback_cents` is then the smaller of the post-bucket balance and that claimable amount, and the `residual_to_estate_cents` is the post-bucket balance minus the allowed payback. The premium deduction is applied to the gross claim before the claim is capped at the balance; the order is pinned so the result is well-defined. A filed claim is created in `FILED` status with both computed figures recorded, tied to its account through `account_id`. Medicaid claims are readable by a `ProgramAdministrator` or `MedicaidAgency` and may be listed and filtered by `account_id`.

Settlement is the final act and is performed by a `ProgramAdministrator`. It applies only when the claim is in `FILED` status and the account is in `FROZEN_DEATH` status. Settling moves the claim from `FILED` to `SETTLED`, decrements the account's `balance_cents` by the claim's `allowed_payback_cents`, records the `residual_to_estate_cents` left for the estate, and moves the account from `FROZEN_DEATH` to `CLOSED`. The claim and the account advance together atomically; `SETTLED` is terminal for the claim and `CLOSED` is terminal for the account.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and lifecycle actions — return `200 OK`. Every request must carry the `X-User-ID` and `X-User-Role` headers described in Section 2.1; the "Authorized Role(s)" column below lists the roles permitted to invoke each operation, and that column is authoritative. A role not listed for an operation is rejected with `ERR_FORBIDDEN`. In particular, the `MedicaidAgency` role is permitted only on the Medicaid-claim read endpoints (alongside `ProgramAdministrator`) and on filing a Medicaid claim; every other read endpoint is restricted to the three roles named in its row — `ProgramAdministrator`, `Beneficiary`, and `AuthorizedRepresentative` — so a `MedicaidAgency` read of those resources is rejected with `ERR_FORBIDDEN`. Wherever the workflow prose in Section 3 says a resource is "readable by any role," it means precisely the roles listed for that endpoint's read rows in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/able/programs` | Create the state ABLE program configuration | ProgramAdministrator |
| GET | `/able/programs/{id}` | Fetch a program | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/investment-options` | Create an investment option (portfolio) | ProgramAdministrator |
| GET | `/able/investment-options/{id}` | Fetch an investment option | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/investment-options` | List investment options, optionally filtered by program | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/beneficiaries` | Register a beneficiary | ProgramAdministrator |
| GET | `/able/beneficiaries/{id}` | Fetch a beneficiary (includes computed eligibility_status) | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/beneficiaries` | List beneficiaries, optionally filtered by program | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/beneficiaries/{id}/record_death` | Record beneficiary death; freezes the account and cascades | ProgramAdministrator |
| POST | `/able/beneficiaries/{id}/certifications` | Create a certification record (window must not overlap) | ProgramAdministrator |
| GET | `/able/certifications/{id}` | Fetch a certification | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/certifications` | List certifications, optionally filtered by beneficiary | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/certifications/{id}/decide` | Approve or deny a pending certification | ProgramAdministrator |
| POST | `/able/accounts` | Open an ABLE account for a certified beneficiary | ProgramAdministrator |
| GET | `/able/accounts/{id}` | Fetch an account (includes computed ledger + ssi_posture) | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/accounts` | List accounts, optionally filtered by beneficiary or investment option | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/accounts/{id}/means-test` | Compute means-test impact for a given variant (SSI or MEDICAID) | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/accounts/{id}/suspend` | Suspend an OPEN account | ProgramAdministrator |
| POST | `/able/accounts/{id}/reinstate` | Reinstate a SUSPENDED account (requires CERTIFIED beneficiary) | ProgramAdministrator |
| POST | `/able/accounts/{id}/assess-fee` | Assess the program management fee for a period | ProgramAdministrator |
| POST | `/able/accounts/{id}/investment-changes` | Change the account's elected investment option | Beneficiary, AuthorizedRepresentative |
| POST | `/able/accounts/{id}/authorized-representatives` | Add an authorized representative (window must not overlap) | ProgramAdministrator, Beneficiary |
| GET | `/able/authorized-representatives/{id}` | Fetch an authorized representative | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/authorized-representatives` | List authorized representatives, optionally filtered by account | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/authorized-representatives/{id}/revoke` | Revoke an authorized representative | ProgramAdministrator, Beneficiary |
| POST | `/able/accounts/{id}/contributions` | Post a contribution (OCC-guarded) | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/contributions/{id}` | Fetch a contribution | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/contributions` | List contributions, optionally filtered by account | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/contributions/{id}/reverse` | Reverse a posted contribution (compensating action) | ProgramAdministrator |
| POST | `/able/accounts/{id}/distributions` | Request a distribution | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/distributions/{id}` | Fetch a distribution (includes computed fields) | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/distributions` | List distributions, optionally filtered by account | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/distributions/{id}/approve` | Approve a requested distribution | Beneficiary, AuthorizedRepresentative |
| POST | `/able/distributions/{id}/reject` | Reject a requested distribution | ProgramAdministrator |
| POST | `/able/distributions/{id}/disburse` | Disburse an approved distribution (OCC-guarded) | Beneficiary, AuthorizedRepresentative |
| POST | `/able/distributions/{id}/substantiate` | Mark a disbursed distribution fully substantiated | Beneficiary, AuthorizedRepresentative |
| POST | `/able/distributions/{id}/clawback` | Claw back a disbursed distribution | ProgramAdministrator |
| POST | `/able/distributions/{id}/qde-records` | Attach a QDE record to a disbursed distribution | Beneficiary, AuthorizedRepresentative |
| GET | `/able/qde-records/{id}` | Fetch a QDE record | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| GET | `/able/qde-records` | List QDE records, optionally filtered by distribution | ProgramAdministrator, Beneficiary, AuthorizedRepresentative |
| POST | `/able/accounts/{id}/medicaid-claims` | File a Medicaid payback claim against a frozen account | MedicaidAgency |
| GET | `/able/medicaid-claims/{id}` | Fetch a Medicaid claim (includes computed payback + residual) | ProgramAdministrator, MedicaidAgency |
| GET | `/able/medicaid-claims` | List Medicaid claims, optionally filtered by account | ProgramAdministrator, MedicaidAgency |
| POST | `/able/accounts/{id}/medicaid-claims/{claim_id}/settle` | Settle a filed claim; debits payback and closes the account | ProgramAdministrator |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving capability) | ProgramAdministrator |
| POST | `/_market/credit_earnings` | Credit investment earnings or losses to an account | ProgramAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_ACCOUNT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_ACCOUNT_NOT_OPEN` | 409 |
| `ERR_NOT_CERTIFIED` | 409 |
| `ERR_ONSET_AGE_INELIGIBLE` | 409 |
| `ERR_DIAGNOSIS_REQUIRED` | 422 |
| `ERR_ATW_INELIGIBLE` | 409 |
| `ERR_ANNUAL_CAP_EXCEEDED` | 409 |
| `ERR_ROLLOVER_LIMIT_EXCEEDED` | 409 |
| `ERR_ATW_CAP_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 409 |
| `ERR_QDE_MISMATCH` | 409 |
| `ERR_INVESTMENT_CHANGE_LIMIT` | 409 |
| `ERR_CERT_WINDOW_OVERLAP` | 409 |
| `ERR_REP_AUTHORITY_OVERLAP` | 409 |

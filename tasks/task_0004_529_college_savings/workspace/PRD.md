# College Savings 529 API — Product Requirements Document

## 1. Introduction

A 529 plan is a tax-advantaged vehicle that families and back-office custodians use to save for educational expenses across a child's lifetime — from a kindergarten tuition bill to graduate-school room and board a decade later. The product under specification is the system of record that custodial firms run to administer these accounts: it tracks money in (lump-sum and recurring contributions), money out (withdrawals approved by compliance staff and disbursed by back-office agents), it must reconstruct each withdrawal's basis-versus-earnings split at the moment of approval, and it must produce IRS-grade Form 1099-Q tax statements at year end. Each role in the workflow — the account-owning donor, the back-office custodian, the compliance reviewer, and the tax-authority issuer — has distinct authority over distinct mutations, and the system must enforce that segregation cleanly enough to satisfy both a regulator and an auditor.

Two cross-cutting concerns shape the design. First, **calculations must be reproducible**. The basis/earnings split, the federal 10% excess-withdrawal penalty, the K-12 annual-cap overage, and state-by-state tax-incentive matches all use pinned snapshots and a fixed evaluation order — the same inputs always yield the same cents, and the basis attached to an approved withdrawal must never silently drift if a later contribution shifts the account's earnings ratio. Second, **temporal correctness matters**. The system clock is a first-class entity because tax-year boundaries, contribution-reverse windows, Form 1099-Q issuance windows, and recurring-contribution scheduling all turn on calendar position; the clock is therefore driven by a dedicated test-driving endpoint rather than by wall time. The remainder of this document specifies the contract precisely enough that any compliant implementation passes the same automated test battery.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The role header is matched against a closed enumeration of four roles, spelled exactly as follows: `AccountOwner`, `CustodianAgent`, `ComplianceOfficer`, and `SystemTaxAuthority`. A request that omits the role header, or supplies a value outside the closed set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not on the endpoint's allow-list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The semantics of `X-User-ID` differ by role. When `X-User-Role` is `AccountOwner`, the `X-User-ID` is the `id` of the acting `Donor`; ownership checks on any resource that references a `Donor` compare the resource's foreign-key field to `X-User-ID` — for example, an `AccountOwner` can act on an `Account` only when that account's `donor_id` equals the caller's `X-User-ID`. When `X-User-Role` is `CustodianAgent`, `ComplianceOfficer`, or `SystemTaxAuthority`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server uses it for segregation-of-duties checks but does not compare it to any entity's `id`.

The segregation-of-duties rule is concrete: the same `X-User-ID` must not both submit a `Withdrawal` (the `DRAFT → SUBMITTED` transition) and later approve it (the `SUBMITTED → APPROVED` transition); likewise the same `X-User-ID` must not both create a `BeneficiaryChange` (initial `PENDING`) and later approve it (`PENDING → APPROVED`). A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This rule sits above existence checks but below the basic authentication and authorization checks in priority order.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; the `offset` parameter defaults to 0 with a minimum of 0. List responses are sorted by `created_at` in ascending order. The `meta` block on a list response exposes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the unfiltered count of records matching the query and `has_more` is true exactly when more records exist beyond the current page.

### 2.4. Common Resource Shape and Versioning

Every persisted entity except `ClockState` exposes the same four envelope fields. The `id` is a server-minted UUID with no type prefix; clients must not supply it. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, the former pinned at creation and the latter refreshed on every successful mutation. The `version` field is an integer that begins at 1 on creation and increments by exactly 1 on every mutation that materially changes the entity. The `ClockState` resource is an exception: it carries `current_utc` only — it has no `id`, no `created_at`, no `updated_at`, and no `version`.

The `version` field on `Account` is also the optimistic-concurrency hinge: a number of reviewer-driven operations require the caller to supply the version the caller last observed, allowing the server to detect that an intervening mutation has invalidated the reviewer's view of the world.

### 2.5. Path Traversal of Nested Resources

URL path parameters are validated strictly left-to-right. When a path embeds a templated identifier, the server resolves each segment in order; the first segment that fails to resolve produces `ERR_NOT_FOUND` (HTTP 404), and downstream segments are not examined. Foreign-key identifiers supplied in a request body — for example, a `donor_id`, `beneficiary_id`, `account_id`, `scheduled_contribution_id`, `to_beneficiary_id`, `from_beneficiary_id`, or `supersedes_form_id` — that fail to resolve produce `ERR_REFERENCED_NOT_FOUND` (HTTP 404). Malformed bodies, missing required fields, or values outside declared ranges produce `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Money, Rounding, and Cents Arithmetic

All monetary quantities are stored as integers in cents and exchanged as integers in cents. There are no fractional cents anywhere in the contract — neither in stored fields, nor in request bodies, nor in computed outputs. When a calculation step requires rounding, the system uses **half-up rounding** to the nearest whole cent. Rounding is applied **per step** as specified in the formula — never sum-then-round when the formula requires round-then-sum (see §3 for the basis/earnings split, the federal penalty, and the state-tax-incentive match, each of which pins its own rounding posture). The half-up posture means that a half-cent rounds upward toward the next integer.

### 2.7. Optimistic Concurrency Control on Account

Two reviewer-driven write operations require the client to thread the `Account`'s currently-observed `version` through the request body, so that the server can detect that the reviewer's view has gone stale before any irreversible state pinning takes place.

The first such operation is approving a `Withdrawal`. The request body must include `expected_account_version` carrying the client's last observed `version` of the target `Account`. If `expected_account_version` does not match the `Account`'s current `version` at the moment the approve is processed, the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412); this protects the basis/earnings split, the K-12 excess computation, and the federal-penalty computation from being pinned against an account snapshot that has since shifted because of a second posted contribution, a disbursement of another withdrawal, or any other intervening account-version bump.

The second such operation is approving a `BeneficiaryChange`. Its request body also carries `expected_account_version`; a mismatch with the current `Account.version` is likewise rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). All other endpoints — including create, submit, reject, revise, disburse, reverse, and every read endpoint — do not take a version field and do not perform an OCC check.

### 2.8. Validation Priority

When a single request triggers more than one possible validation failure, the server evaluates checks in a fixed priority order and emits the first failure rather than later ones:

1. Authentication (`ERR_UNAUTHENTICATED`).
2. Endpoint-level role authorization (`ERR_FORBIDDEN`).
3. Segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`) on the two approve endpoints where it applies.
4. Path resource resolution (`ERR_NOT_FOUND`).
5. Body foreign-key resolution (`ERR_REFERENCED_NOT_FOUND`).
6. State precondition for the requested transition (`ERR_INVALID_STATE`).
7. Optimistic-concurrency stale-version (`ERR_STALE_ACCOUNT_VERSION`) on the two approve endpoints that take `expected_account_version`.
8. Business safety / regulatory checks: beneficiary-family-member rule (`ERR_BENEFICIARY_NOT_FAMILY_MEMBER`), premature 1099-Q issuance (`ERR_FORM_PREMATURE_ISSUANCE`), 1099-Q correction window (`ERR_FORM_CORRECTION_WINDOW_CLOSED`).
9. Business referential / configuration checks: unsupported state code on donor creation (`ERR_UNSUPPORTED_STATE_CODE`), duplicate donor email (`ERR_EMAIL_TAKEN`), duplicate Form 1099-Q for an `(account_id, tax_year)` slot (`ERR_FORM_ALREADY_EXISTS`), duplicate state-tax-incentive for a `(donor_id, tax_year)` slot (`ERR_INCENTIVE_ALREADY_EXISTS`).
10. Business fiscal checks: insufficient balance (`ERR_INSUFFICIENT_BALANCE`), revise-count exceeded (`ERR_REVISION_LIMIT_EXCEEDED`), reverse-window closed (`ERR_REVERSE_WINDOW_CLOSED`).
11. Request shape (`ERR_INVALID_REQUEST`) — checks not caught by deserialization.

Within each tier, ordering follows the priority numbers shown above. Where a single endpoint is guarded by checks from more than one tier, the tier order is authoritative: a state-precondition failure surfaces before an OCC-stale failure, an OCC-stale failure surfaces before a balance failure, and a balance failure surfaces before a request-shape failure.

### 2.9. Hierarchical Consistency and Cascade Semantics

Mutations on one entity routinely refresh aggregate or derived state on another entity in the same transaction. Posting a `Contribution` recomputes the owning `Account`'s ledger fields (`account_balance_cents`, `total_basis_cents`, `total_earnings_cents`) and re-aggregates the donor's matching `StateTaxIncentive` for the contribution's `tax_year`. Disbursing a `Withdrawal` reduces those same ledger fields, increments the `Account.ytd_qualified_k12_cents` running total when the expense class is K-12 tuition (by the qualified portion only), and refreshes the aggregate fields on any matching `DRAFT` `Form1099Q`. Every mutation that materially changes an `Account` also bumps its `version` and refreshes its `updated_at`, so OCC and downstream visibility stay synchronized. The detailed cascade for each lifecycle event is described in §3.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Cast: Donors, Beneficiaries, and Accounts

Three foundational entities exist before any money moves. A back-office custodian first creates a `Donor`, supplying the donor's `full_name`, their tax-residence `state_code`, the last four digits of their federal tax id as `federal_tax_id_last4`, and a contact `email`. The `state_code` must be one of six recognized U.S. states — `CA`, `NY`, `IL`, `TX`, `FL`, or `OH`; anything else is rejected with `ERR_UNSUPPORTED_STATE_CODE`. The `email` must be globally unique with case-insensitive comparison; a duplicate is rejected with `ERR_EMAIL_TAKEN`.

The custodian then creates a `Beneficiary` with `full_name`, `date_of_birth`, a `relationship_class` drawn from `SELF`, `CHILD`, `SIBLING`, `FIRST_COUSIN`, or `OTHER`, and the beneficiary's own `federal_tax_id_last4`. The `date_of_birth` is used downstream to distinguish K-12-eligible distributions from higher-education distributions; the `relationship_class` is consulted when a future `BeneficiaryChange` is evaluated.

Opening an `Account` ties one donor to one current beneficiary. A custodian submits a payload referencing the `donor_id` and the `beneficiary_id`; the new account starts in status `OPEN`, and every computed ledger field (`account_balance_cents`, `total_basis_cents`, `total_earnings_cents`, `ytd_qualified_k12_cents`) initialises to zero. The `tax_year` field on the account is initialised to the calendar year of the current system clock and tracks the clock from then on.

### 3.2. The Posture of an Account: OPEN, RESTRICTED, CLOSED

An account moves through three postures. The initial posture is `OPEN`. A `ComplianceOfficer` may place an `OPEN` account on a compliance hold, transitioning the account to `RESTRICTED`; the same officer (or a colleague) later returns the account to `OPEN` by lifting the hold, driving the transition `RESTRICTED → OPEN`. Both posture mutations bump `Account.version` and refresh `updated_at`.

The `RESTRICTED` posture has a specific business meaning: it blocks the **start** of new outgoing money flows while still allowing recurring contributions that were already scheduled to keep posting. Concretely, a `RESTRICTED` account rejects any new submit of a `Withdrawal` (the `DRAFT → SUBMITTED` transition requires `Account.status == OPEN`), any approval of an in-flight `Withdrawal` (the `SUBMITTED → APPROVED` transition requires `Account.status == OPEN`), and any disbursement (the `APPROVED → DISBURSED` transition requires `Account.status == OPEN`), but it allows a `RECURRING` `Contribution` previously queued by an `ACTIVE` `ScheduledContribution` to post normally (`DRAFT → POSTED` permits `Account.status` to be either `OPEN` or `RESTRICTED`). Pausing a schedule remains allowed while restricted, but resuming a `PAUSED` schedule requires the account to be back to `OPEN`. Creating a `ScheduledContribution`, approving a `BeneficiaryChange`, and a number of other flows likewise require the account to be `OPEN`. The transitions controlled by these guards are detailed in their respective subsections.

The `AccountOwner` may close the account, taking it from `OPEN` to `CLOSED`, but only when the account is fully drained. All of the following must be true at close time: the `account_balance_cents` is exactly zero, there is no `ScheduledContribution` for the account in `ACTIVE` status, there is no `Withdrawal` for the account in either `SUBMITTED` or `APPROVED` status, and there is no `BeneficiaryChange` for the account in `PENDING` status. Any of these blocking conditions surfaces as `ERR_INVALID_STATE`. `CLOSED` is terminal; no further transitions out of `CLOSED` exist.

### 3.3. Scheduled Contributions: Recurring Money In

The account owner may set up a `ScheduledContribution` to automate periodic funding. The payload identifies the target `account_id`, the per-period `amount_cents`, and a `cadence` drawn from `WEEKLY`, `MONTHLY`, or `QUARTERLY`. The per-period `amount_cents` must be strictly positive and no greater than 5,000,000 cents ($50,000). A newly created schedule starts in status `ACTIVE`, its `posted_runs` counter at zero, and its `next_run_utc` set to the current clock plus the cadence interval (one week, one calendar month, or three calendar months).

A schedule's lifecycle has three terminal-friendly verbs. Pausing an `ACTIVE` schedule transitions it to `PAUSED` (allowed while the parent account is in `OPEN` or `RESTRICTED`). Resuming a `PAUSED` schedule returns it to `ACTIVE` (requires the account to be `OPEN`) and resets `next_run_utc` to the current clock plus a fresh cadence interval — the previous due time is discarded. Cancelling a schedule, allowed from either `ACTIVE` or `PAUSED`, drives it to the terminal `CANCELLED` state; no transition out of `CANCELLED` exists. A scheduled run is never auto-generated when its parent account is `CLOSED` or its schedule is `PAUSED`/`CANCELLED`.

Recurring contributions are materialized by an admin-only scheduler-tick capability that, when invoked, walks every `ScheduledContribution` whose `next_run_utc` is at or before the current clock and which is in `ACTIVE` status. For each due schedule, the system creates a fresh `Contribution` row with `contribution_kind = RECURRING`, the schedule's `account_id` and `amount_cents`, and the schedule's `id` recorded as the contribution's `scheduled_contribution_id`. That fresh contribution is then immediately posted (see §3.4), and the schedule's `posted_runs` is incremented and `next_run_utc` advanced by one cadence interval relative to the just-posted time. Schedules in `PAUSED` or `CANCELLED` status are skipped.

### 3.4. Lump-Sum and Recurring Contributions: Posting the Ledger

The `Contribution` entity is the unit of money flowing into the account. A custodian creates a `DRAFT` contribution by supplying the `account_id`, the `amount_cents` (strictly positive, no greater than 5,000,000 cents), the `contribution_kind` of either `LUMP_SUM` or `RECURRING`, and — only for `RECURRING` kind — the originating `scheduled_contribution_id` (a `LUMP_SUM` contribution carries no schedule reference). Creation alone leaves the row in `DRAFT` and changes no balance.

Posting a contribution drives it from `DRAFT` to `POSTED`. The post step is gated on the account being either `OPEN` or `RESTRICTED` — a `RESTRICTED` posture is **not** a barrier to recurring posting (which is the whole point of the posture being a soft hold). For a `LUMP_SUM` kind, the post is unconditional with respect to schedule status; for a `RECURRING` kind, the referenced `ScheduledContribution` must itself be in `ACTIVE` status (a recurring post cannot land while its schedule is paused or cancelled). On a successful post, the contribution's `status` becomes `POSTED`, its `posted_at_utc` is pinned to the current clock, and its `tax_year` is pinned to the calendar year of `posted_at_utc`. The owning account is then re-aggregated from primary sources: `account_balance_cents` is the sum of all `POSTED` `Contribution.amount_cents` minus the sum of all `DISBURSED` `Withdrawal.amount_cents`; `total_basis_cents` is the sum of all `POSTED` `Contribution.amount_cents` minus the sum of `basis_portion_cents` across all `DISBURSED` `Withdrawal` rows; and `total_earnings_cents` is `account_balance_cents` minus `total_basis_cents`. The `Account.version` is incremented and `updated_at` refreshed. If the contribution carries a `scheduled_contribution_id`, the schedule's `posted_runs` is incremented and its `next_run_utc` advanced by one cadence interval from `posted_at_utc`. Finally, the donor's matching `StateTaxIncentive` for the contribution's `tax_year` — if one exists — has its `contributions_eligible_cents` re-aggregated from scratch across the donor's accounts.

Reversing a posted contribution drives it from `POSTED` to the terminal `REVERSED`. The reverse is a narrow, time-boxed correction: the clock-time delta between the current clock and the contribution's `posted_at_utc` must be strictly less than 72 hours, or the request is rejected with `ERR_REVERSE_WINDOW_CLOSED`. The account must be `OPEN` or `RESTRICTED`. The reverse must also leave the ledger consistent against in-flight obligations: after subtracting this contribution's `amount_cents`, the projected `account_balance_cents` must still be greater than or equal to the sum of `amount_cents` across all `Withdrawal` rows for this account that are already in `APPROVED` status but not yet `DISBURSED` — a reverse that would put the ledger underwater relative to approved-but-not-yet-paid withdrawals is rejected with `ERR_INVALID_STATE`. On success, the same re-aggregation pass refreshes the account's `account_balance_cents`, `total_basis_cents`, and `total_earnings_cents`; `Account.version` is incremented; and the donor's `StateTaxIncentive` for the original `tax_year` is recomputed.

### 3.5. Withdrawals: Money Out, With Review

A withdrawal is the unit of money flowing out of the account. The account owner creates a `DRAFT` `Withdrawal` by supplying the `account_id`, the total `amount_cents` (strictly positive), and an `expense_class` drawn from `HIGHER_ED_TUITION`, `ROOM_BOARD`, `BOOKS_SUPPLIES`, `K_12_TUITION`, `APPRENTICESHIP`, or `NON_QUALIFIED`. Creation alone changes no balance and pins no split.

Submitting the draft drives it to `SUBMITTED`. The submit step requires the account to be in `OPEN` status; it must not be in flight with any `PENDING` `BeneficiaryChange` (the account's beneficiary is allowed to change only while no withdrawal is mid-review); and the withdrawal's `amount_cents` must be no greater than the account's current `account_balance_cents`, otherwise `ERR_INSUFFICIENT_BALANCE` is returned.

A `ComplianceOfficer` then reviews the submission and either rejects or approves it. Rejecting a `SUBMITTED` withdrawal drives it to `REJECTED` and increments its `rejection_count` by one. The owner may then revise the rejected row, driving it from `REJECTED` back to `DRAFT` for editing — but only when the `rejection_count` is strictly less than 3. A fourth revise attempt (when `rejection_count` is already 3 or higher) is rejected with `ERR_REVISION_LIMIT_EXCEEDED`. This branching-with-revert loop — `DRAFT → SUBMITTED → REJECTED → DRAFT` — can be traversed up to three times for the same withdrawal row before the row is exhausted.

Approving a `SUBMITTED` withdrawal is the most consequential transition in the system and is gated by the strictest set of preconditions. The withdrawal must be in `SUBMITTED` status; the account must be in `OPEN` status; the withdrawal's `amount_cents` must be no greater than the current `account_balance_cents` (re-checked at approve time, not just at submit time, with `ERR_INSUFFICIENT_BALANCE` on failure); the request body must include `expected_account_version` matching the account's current `version` (a mismatch yields `ERR_STALE_ACCOUNT_VERSION`); and the segregation-of-duties rule from §2.1 forbids the approving officer from being the same `X-User-ID` that submitted the row. On approval, the withdrawal's status becomes `APPROVED`, its `approved_at_utc` is pinned to the current clock, and its `tax_year` is pinned to the calendar year of `approved_at_utc`. Three calculated fields — `basis_portion_cents`, `earnings_portion_cents`, `k12_excess_cents`, and `penalty_cents` — are then pinned according to the rules in §3.6, in that order. The `Account.version` is incremented and `updated_at` refreshed; the account ledger fields (`account_balance_cents`, `total_basis_cents`, `total_earnings_cents`) are **not** yet modified by approval — that happens only on disbursement.

Disbursing an `APPROVED` withdrawal drives it to the terminal `DISBURSED` state, performed by a `CustodianAgent`. The account must be `OPEN`. On success, `disbursed_at_utc` is pinned to the current clock, the account ledger is re-aggregated (the same primary-source pass as on posting: `account_balance_cents` decreases by `amount_cents`, `total_basis_cents` decreases by the pinned `basis_portion_cents`, and `total_earnings_cents` is recomputed as balance minus basis), and `Account.version` is incremented. When the `expense_class` is `K_12_TUITION`, the account's running `ytd_qualified_k12_cents` is incremented by the qualified portion of this withdrawal only — that is, by `amount_cents` minus `k12_excess_cents` — so that the running total reflects only the cents that actually counted as qualified K-12 distribution under the annual cap. Finally, any `DRAFT` `Form1099Q` matching the same `account_id` and the withdrawal's `tax_year` has its aggregate fields re-aggregated against current disbursed-withdrawal data (`gross_distribution_cents`, `earnings_cents`, `basis_cents`, `penalty_cents`, and `recipient_kind` are all refreshed; see §3.8).

### 3.6. Computing the Basis/Earnings Split, the K-12 Cap, and the Federal Penalty

Three calculations are pinned together at the `SUBMITTED → APPROVED` transition. Their evaluation order is fixed: first the basis/earnings split, then the K-12 excess, then the federal penalty. Each downstream step consumes the values pinned by the upstream step. All rounding uses half-up rounding to whole cents, per the §2.6 posture.

**Basis/earnings split (the `earnings_ratio` calculation).** The split apportions the withdrawal's `amount_cents` into a `basis_portion_cents` (the donor's contributed principal) and an `earnings_portion_cents` (the appreciation that has accrued on top of that principal). The split uses the account's totals observed immediately before the approve transition — that is, after every prior `POSTED` `Contribution` and prior `DISBURSED` `Withdrawal` has already been recorded against the ledger. Step one computes the `earnings_portion_cents` as the withdrawal's `amount_cents` multiplied by the account's `total_earnings_cents`, divided by the account's `account_balance_cents`, rounded half-up to the nearest whole cent — the rounding is applied to this single withdrawal, not deferred to a sum across multiple withdrawals. Step two computes the `basis_portion_cents` as the withdrawal's `amount_cents` minus the just-rounded `earnings_portion_cents`, so that the two parts add exactly to `amount_cents`. Two edge cases override the formula: when the account's `total_earnings_cents` is zero or negative, the `earnings_portion_cents` is set to zero and the `basis_portion_cents` is set to the full `amount_cents`; when the account's `account_balance_cents` is zero the withdrawal would have already been rejected by the insufficient-balance precondition, so the formula is not reached.

The same ratio formula has a second, audit-only variant. The post-disbursal audit capability — a read-only operation exposed only to a `ComplianceOfficer` — recomputes the basis/earnings split for an already-finalised withdrawal against **current** account totals (that is, after this withdrawal and any subsequent posted contributions or disbursed withdrawals have already updated the ledger). The pinned fields on the withdrawal row are **not** mutated by this audit; the response simply returns what the split would be if recomputed today. The audit variant therefore yields a different split from the pinned values exactly when a later disbursed withdrawal or new contribution has shifted the basis/earnings mix since approval.

**K-12 annual cap (the `k12_excess_calc` calculation).** K-12 tuition distributions are capped at $10,000 (1,000,000 cents) per beneficiary per calendar year — this is a federal ceiling on the qualified K-12 portion of distributions. When the `expense_class` is `K_12_TUITION`, the system computes a projected K-12 running total as the account's current `ytd_qualified_k12_cents` plus this withdrawal's `amount_cents`, and the `k12_excess_cents` is the larger of zero and that projected value minus the 1,000,000-cent annual cap. The cap is inclusive of equality at the boundary: a projected running total of exactly 1,000,000 cents yields `k12_excess_cents` of zero. When the `expense_class` is anything other than `K_12_TUITION`, `k12_excess_cents` is zero.

**Federal 10% excess-withdrawal penalty (the `excess_withdrawal_penalty` calculation).** The 10% federal penalty applies to the earnings portion of any non-qualified distribution and to the earnings portion of the K-12 excess. The system first computes a `penalty_base_cents` value according to fixed branching: when the `expense_class` is `NON_QUALIFIED`, the penalty base is the entire `earnings_portion_cents` just pinned; otherwise, when the `expense_class` is `K_12_TUITION` and the `k12_excess_cents` is strictly greater than zero, the penalty base is the `earnings_portion_cents` multiplied by `k12_excess_cents` divided by `amount_cents`, rounded half-up to whole cents (this is the earnings share of the excess portion only); otherwise, the penalty base is zero. The `penalty_cents` is then that `penalty_base_cents` multiplied by the federal penalty rate of 0.10 (10%), again rounded half-up to whole cents. Both rounding steps are independent — the inner ratio is rounded first, then the outer rate multiplication is rounded — so the result equals neither sum-then-round nor a one-shot 10% on the raw earnings figure when both branches collapse.

### 3.7. Beneficiary Changes: Moving the Designation

The account owner may request to change the account's designated beneficiary by creating a `BeneficiaryChange` referencing the `account_id` and the proposed `to_beneficiary_id`. On creation, the system pins three snapshots into the change row: `from_beneficiary_id` is captured as the account's `beneficiary_id` at request time, `from_relationship_class` as the from-beneficiary's `relationship_class`, and `to_relationship_class` as the proposed to-beneficiary's `relationship_class`. The new change row begins in status `PENDING`.

A `ComplianceOfficer` then either approves or rejects the pending change — these are the two sibling branches out of `PENDING`. Approval drives it to `APPROVED`; rejection drives it to `REJECTED`. Both transitions pin `decided_at_utc` to the current clock. Approval mutates more state than rejection: on approval, the account's `beneficiary_id` is overwritten with the change's `to_beneficiary_id`, and `Account.version` is incremented along with a refresh of `updated_at`. Rejection touches only the change row itself; the account's `beneficiary_id` is left untouched.

Approval is gated by five preconditions, evaluated in §2.8's priority order. The change must be in `PENDING` status. The account must be in `OPEN` status. The referenced `to_beneficiary_id` must resolve to a persisted `Beneficiary` (otherwise `ERR_REFERENCED_NOT_FOUND`). The pinned `to_relationship_class` must be one of `SELF`, `CHILD`, `SIBLING`, or `FIRST_COUSIN`; a value of `OTHER` is rejected with `ERR_BENEFICIARY_NOT_FAMILY_MEMBER`, which is the IRS family-member rule applied at approve time (the same rule also rejects creation of a change whose target relationship class is `OTHER`). The request body must include `expected_account_version` matching the account's current `version`, or the approve is rejected with `ERR_STALE_ACCOUNT_VERSION` — another approved change, or a posture transition on the account, may have legitimately advanced `Account.version` between the officer's last read and this approve call. The segregation-of-duties rule from §2.1 forbids the approving officer from being the same `X-User-ID` that originally created the change row.

### 3.8. State Tax Incentives: Calculating the Match

A donor's home state may match a portion of their annual 529 contributions. The system tracks one `StateTaxIncentive` row per donor per tax year. A back-office custodian creates the row by supplying the `donor_id` and the `tax_year`; the system aggregates the donor's `contributions_eligible_cents` on creation — that is, the sum of `amount_cents` across `POSTED` `Contribution` rows on the donor's accounts whose pinned `tax_year` matches the incentive's `tax_year`. The new row begins in status `DRAFT`, with `match_cents` initialised to zero. The combination of `(donor_id, tax_year)` is uniquely keyed; a second creation for the same pair is rejected with `ERR_INCENTIVE_ALREADY_EXISTS`.

Calculating the match drives the row from `DRAFT` to `CALCULATED` and pins `match_cents`. The formula depends on the donor's `state_code`. For donors in California, the match is the lesser of the eligible contributions or 600,000 cents ($6,000 — the CA annual cap), multiplied by the California rate of 0.10 (10%), rounded half-up to whole cents. For donors in New York, the match is computed in two tiers and summed: the first tier applies a 5% rate to the eligible contributions up to the NY first-tier ceiling of 500,000 cents ($5,000); the second tier applies a 2% rate to eligible contributions that sit between the NY first-tier ceiling of 500,000 cents and the NY absolute upper bound of 1,000,000 cents ($10,000); each tier is rounded half-up to whole cents independently before the two are summed (this is per-tier rounding, not sum-then-round). The pinned ordering is tier one first, then tier two. For donors in Illinois, Texas, Florida, or Ohio, no schedule applies and `match_cents` is pinned at zero — these states pass the supported-state check at donor creation but have no incentive schedule in scope here.

Finalising a `CALCULATED` row drives it to the terminal `FINALIZED` state, locking the pinned `match_cents` for the year. The three statuses — `DRAFT`, `CALCULATED`, `FINALIZED` — form a linear progression with no back-transitions.

Posting and reversing contributions both refresh `contributions_eligible_cents` for the matching incentive row on the donor's accounts — this is a cross-aggregate cascade: a single `Contribution` mutation touches both `Account` ledger fields and `StateTaxIncentive` aggregate fields in the same transaction. When the incentive has already advanced past `DRAFT`, the recomputed `contributions_eligible_cents` is still refreshed (the aggregate is always live-aggregated against current data), but the pinned `match_cents` is not retroactively reapplied; the match is locked at the moment the row entered `CALCULATED`.

### 3.9. Form 1099-Q: Year-End Tax Statements

A `Form1099Q` is the IRS tax statement summarising an account's qualified-plan distributions for one calendar year. A `SystemTaxAuthority` creates a `DRAFT` form by supplying the `account_id` and the `tax_year`; the supplied `supersedes_form_id` is null on a first-time creation and set only when a successor form is being spawned (described below). On creation, four aggregate fields are populated from current data: `gross_distribution_cents` is the sum of `amount_cents` across `DISBURSED` `Withdrawal` rows on the account whose pinned `tax_year` matches; `earnings_cents` is the sum of `earnings_portion_cents` across the same set; `basis_cents` is the sum of `basis_portion_cents` across the same set; and `penalty_cents` is the sum of `penalty_cents` across the same set. The `recipient_kind` is derived from the same set as well: if any `DISBURSED` withdrawal on the account for that `tax_year` had `expense_class` equal to `NON_QUALIFIED`, the recipient kind is `ACCOUNT_OWNER`; otherwise it is `BENEFICIARY`. The `(account_id, tax_year, status IN {DRAFT, ISSUED, REISSUED})` combination is uniquely keyed — a second `DRAFT` for the same `(account_id, tax_year)` is rejected with `ERR_FORM_ALREADY_EXISTS` unless the prior form has already moved to `CORRECTED`.

While the form sits in `DRAFT`, every fresh disbursement against the same `(account_id, tax_year)` re-aggregates the form's four cents fields and may flip the `recipient_kind` (a single non-qualified disbursement is enough to lock the recipient kind to `ACCOUNT_OWNER`). The form remains live until it is issued.

Issuing a `DRAFT` form drives it to `ISSUED` and freezes its content. The issue step requires the current clock to be at or after January 1 of the year following the `tax_year` — pre-year-end issuance is rejected with `ERR_FORM_PREMATURE_ISSUANCE`. The account may be in `OPEN`, `RESTRICTED`, or `CLOSED` status at issue time (forms must be issuable even after the account closes). On `ISSUED`, the aggregates are re-snapshotted one last time from current `DISBURSED` data, and `recipient_tax_id_last4` is pinned from the matching source: `Donor.federal_tax_id_last4` when `recipient_kind` is `ACCOUNT_OWNER`, `Beneficiary.federal_tax_id_last4` when `recipient_kind` is `BENEFICIARY`. The `issued_at_utc` is pinned to the current clock. After `ISSUED`, all aggregate fields and `recipient_tax_id_last4` are frozen against further refresh.

Corrections drive an `ISSUED` form to `CORRECTED` and simultaneously spawn a successor in the same operation. The correction window is bounded: the form's `tax_year` must be no earlier than three calendar years before the current clock year (inclusive — that is, `tax_year` must be at least the current clock year minus 3); an attempt to correct an older form is rejected with `ERR_FORM_CORRECTION_WINDOW_CLOSED`. On correction, the system marks the existing form as `CORRECTED` (this is a marker state — the form is now superseded), then creates a fresh `Form1099Q` row in the same call: the new row's `supersedes_form_id` is set to the just-corrected form's `id`, its aggregates are recomputed from current `DISBURSED` `Withdrawal` data, and its status moves through `DRAFT` to `REISSUED` in the same operation with `issued_at_utc` pinned to the current clock. The result is a cyclic `(account_id, tax_year)` lifecycle — the same form `id` never re-enters `DRAFT`, but the slot for `(account_id, tax_year)` cycles `DRAFT → ISSUED → CORRECTED` (with a successor spawned and immediately `REISSUED`).

### 3.10. Test-Driving Capabilities: Clock, Market, Scheduler

Three internal capabilities exist to drive the system from test code; they have no real-world business analogue but are required to exercise the time-, market-, and schedule-dependent behavior described above.

The clock-set capability advances the logical clock to a supplied `to_iso8601` instant. On success, `ClockState.current_utc` is set to that instant; if the new clock falls in a different calendar year than the previous clock, every account's `tax_year` field is recomputed to the new year (but `ytd_qualified_k12_cents` is **not** auto-reset — it continues to accumulate against the running history, and any per-year cap analysis works against the running total).

A clock-read capability returns the current `current_utc`.

The market-credit capability credits a `delta_cents` of market appreciation to a target `account_id` — it represents unrealized appreciation that no real-world business endpoint produces (recurring contributions add basis, not earnings; the only way to test the earnings-ratio dual-variant calculation is to inject earnings synthetically). On success, `account_balance_cents` is increased by `delta_cents` while `total_basis_cents` is left untouched; `total_earnings_cents` is recomputed as balance minus basis; `Account.version` is incremented.

The scheduler-tick capability is the engine described in §3.3: it advances every `ACTIVE` `ScheduledContribution` whose `next_run_utc` is at or before the current clock, materialising a fresh `RECURRING` `Contribution` and posting it immediately. Schedules in `PAUSED` or `CANCELLED` status are skipped on every tick.

## 4. Endpoint Definitions

All endpoints adhere to a uniform status-code convention: a successful creation of a new resource returns HTTP **201**; a successful read, update, action, or state transition that does not create a new resource returns HTTP **200**. Failures return the error envelope with the HTTP code declared in §5. Authorized roles are listed below; a request from any other role is rejected with `ERR_FORBIDDEN`. Request bodies, response bodies, and side effects are intentionally not duplicated here — they are described in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /donors | Create a Donor. | CustodianAgent |
| GET | /donors/{id} | Fetch a Donor. | CustodianAgent, AccountOwner, ComplianceOfficer |
| GET | /donors | List Donors. | CustodianAgent, ComplianceOfficer |
| POST | /beneficiaries | Create a Beneficiary. | CustodianAgent |
| GET | /beneficiaries/{id} | Fetch a Beneficiary. | CustodianAgent, AccountOwner, ComplianceOfficer |
| GET | /beneficiaries | List Beneficiaries. | CustodianAgent, ComplianceOfficer |
| POST | /accounts | Open a 529 Account. | CustodianAgent |
| GET | /accounts/{id} | Fetch an Account. | CustodianAgent, AccountOwner, ComplianceOfficer |
| GET | /accounts | List Accounts; filter by donor_id and/or beneficiary_id. | CustodianAgent, ComplianceOfficer |
| POST | /accounts/{id}/restrict | Place an account on compliance hold. | ComplianceOfficer |
| POST | /accounts/{id}/release | Release a compliance hold. | ComplianceOfficer |
| POST | /accounts/{id}/close | Close a fully drained account. | AccountOwner |
| POST | /scheduled-contributions | Create a recurring contribution schedule. | AccountOwner |
| GET | /scheduled-contributions/{id} | Fetch a schedule. | AccountOwner, CustodianAgent, ComplianceOfficer |
| GET | /scheduled-contributions | List schedules; filter by account_id. | AccountOwner, CustodianAgent, ComplianceOfficer |
| POST | /scheduled-contributions/{id}/pause | Pause an ACTIVE schedule. | AccountOwner |
| POST | /scheduled-contributions/{id}/resume | Resume a PAUSED schedule. | AccountOwner |
| POST | /scheduled-contributions/{id}/cancel | Cancel a schedule. | AccountOwner |
| POST | /contributions | Create a DRAFT Contribution. | CustodianAgent |
| POST | /contributions/{id}/post | Post a contribution. | CustodianAgent |
| POST | /contributions/{id}/reverse | Reverse a posted contribution within 72 hours. | CustodianAgent |
| GET | /contributions/{id} | Fetch a contribution. | CustodianAgent, AccountOwner, ComplianceOfficer |
| GET | /contributions | List contributions; filter by account_id, scheduled_contribution_id. | CustodianAgent, AccountOwner, ComplianceOfficer |
| POST | /withdrawals | Create a DRAFT Withdrawal. | AccountOwner |
| POST | /withdrawals/{id}/submit | Submit a DRAFT withdrawal for review. | AccountOwner |
| POST | /withdrawals/{id}/reject | Reject a SUBMITTED withdrawal. | ComplianceOfficer |
| POST | /withdrawals/{id}/revise | Return a REJECTED withdrawal to DRAFT (up to 3 cycles). | AccountOwner |
| POST | /withdrawals/{id}/approve | Approve a SUBMITTED withdrawal; pins basis/earnings/penalty. | ComplianceOfficer |
| POST | /withdrawals/{id}/disburse | Disburse an APPROVED withdrawal. | CustodianAgent |
| GET | /withdrawals/{id} | Fetch a withdrawal. | AccountOwner, CustodianAgent, ComplianceOfficer |
| GET | /withdrawals/{id}/audit | Recompute basis/earnings split against current account totals. | ComplianceOfficer |
| GET | /withdrawals | List withdrawals; filter by account_id. | AccountOwner, CustodianAgent, ComplianceOfficer |
| POST | /beneficiary-changes | Create a PENDING BeneficiaryChange. | AccountOwner |
| POST | /beneficiary-changes/{id}/approve | Approve a PENDING BeneficiaryChange. | ComplianceOfficer |
| POST | /beneficiary-changes/{id}/reject | Reject a PENDING BeneficiaryChange. | ComplianceOfficer |
| GET | /beneficiary-changes/{id} | Fetch a beneficiary change. | AccountOwner, ComplianceOfficer |
| GET | /beneficiary-changes | List beneficiary changes; filter by account_id, to_beneficiary_id, from_beneficiary_id. | AccountOwner, ComplianceOfficer |
| POST | /state-tax-incentives | Create a DRAFT StateTaxIncentive. | CustodianAgent |
| POST | /state-tax-incentives/{id}/calculate | Calculate and pin match_cents; DRAFT → CALCULATED. | CustodianAgent |
| POST | /state-tax-incentives/{id}/finalize | Lock a CALCULATED incentive; CALCULATED → FINALIZED. | CustodianAgent |
| GET | /state-tax-incentives/{id} | Fetch a state tax incentive. | CustodianAgent, AccountOwner |
| GET | /state-tax-incentives | List incentives; filter by donor_id and/or tax_year. | CustodianAgent, ComplianceOfficer |
| POST | /forms-1099q | Create a DRAFT Form1099Q. | SystemTaxAuthority |
| POST | /forms-1099q/{id}/issue | Issue (freeze) a DRAFT Form1099Q. | SystemTaxAuthority |
| POST | /forms-1099q/{id}/correct | Mark an ISSUED form CORRECTED and spawn a REISSUED successor. | SystemTaxAuthority |
| GET | /forms-1099q/{id} | Fetch a Form 1099-Q. | SystemTaxAuthority, AccountOwner, ComplianceOfficer |
| GET | /forms-1099q | List Forms 1099-Q; filter by account_id, tax_year, supersedes_form_id. | SystemTaxAuthority, ComplianceOfficer |
| POST | /_clock/set_current_utc | Test-driving: set the system clock to a supplied instant. | CustodianAgent, SystemTaxAuthority, ComplianceOfficer |
| GET | /_clock | Test-driving: read the current system clock. | CustodianAgent, SystemTaxAuthority, ComplianceOfficer, AccountOwner |
| POST | /_market/credit_earnings | Test-driving: credit market appreciation to an Account. | CustodianAgent |
| POST | /_scheduler/tick | Test-driving: advance the scheduler. | CustodianAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_ACCOUNT_VERSION | 412 |
| ERR_BENEFICIARY_NOT_FAMILY_MEMBER | 422 |
| ERR_INSUFFICIENT_BALANCE | 422 |
| ERR_REVISION_LIMIT_EXCEEDED | 409 |
| ERR_REVERSE_WINDOW_CLOSED | 409 |
| ERR_UNSUPPORTED_STATE_CODE | 422 |
| ERR_EMAIL_TAKEN | 409 |
| ERR_FORM_ALREADY_EXISTS | 409 |
| ERR_INCENTIVE_ALREADY_EXISTS | 409 |
| ERR_FORM_PREMATURE_ISSUANCE | 422 |
| ERR_FORM_CORRECTION_WINDOW_CLOSED | 422 |

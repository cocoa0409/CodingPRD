# IRA Management & RMD Calculation API — Product Requirements Document

## 1. Introduction

Individual Retirement Accounts sit at the intersection of three regulatory regimes that change shape every few years — annual contribution caps and catch-up additions tied to age, mandatory drawdowns triggered by the SECURE Act's age-73 rule, and the ten-year drain window that the same Act imposes on inherited IRAs. Custodial financial institutions need a system of record that not only stores positions, but also enforces these regimes as first-class business invariants and produces the IRS reporting artifacts (Form 1099-R) that flow from each taxable event. This document specifies the API for such a system.

The platform manages the full lifecycle of a participant's retirement accounts: opening Traditional and Roth IRAs (including Inherited IRAs that arrive under the SECURE ten-year window), posting regular and catch-up contributions against IRS caps, executing Backdoor Roth conversions with their tightly constrained preconditions, taking distributions across the full taxonomy of IRS distribution reasons, calculating required minimum distributions using either the Uniform Lifetime or Single Life Expectancy table, and issuing the resulting 1099-R forms with the correct distribution codes and taxable amounts. A simulated system clock (drivable by privileged operators) lets tests and operational dry-runs advance time deterministically — both day by day for inherited-account deadlines and year by year for tax-year roll-forward, end-of-year balance snapshots, excess-contribution sweeps, and missed-RMD penalties.

The audience for this document is the engineering team implementing the API surface, the QA team writing automated coverage, and the compliance reviewers who must trace each calculation back to its IRS source. Each requirement below maps directly to an enforceable rule.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and contracts that apply uniformly to every API operation.

### 2.1. User and Role-Based Access Control

Every API request must carry two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares the role under which the request is being made. The system recognizes exactly four roles, spelled as follows: `Participant`, `Custodian`, `ComplianceOfficer`, and `Auditor`. A missing or empty `X-User-ID` or `X-User-Role` causes the request to be rejected with `ERR_AUTH_MISSING`. A header that names a role outside the four-value set is rejected with `ERR_AUTH_INVALID_ROLE`. A role that is recognized but not authorized for the requested endpoint is rejected with `ERR_FORBIDDEN`.

The four roles differ in how `X-User-ID` ties back to persisted state. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` (directly through `participant_id` on an `Account` or `ConversionRequest`, or indirectly through an `Account`'s `participant_id`) compare the resource's foreign-key field to `X-User-ID`. A `Participant` may only act on their own accounts, their own conversion requests, their own beneficiary claims, and their own 1099-R forms — read endpoints scoped to "self only" reject any attempt to view another participant's records with `ERR_NOT_FOUND` (the cross-tenant existence rule treats out-of-scope rows as absent rather than as 403 leakage).

When `X-User-Role` is `Custodian`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example, as `approver_role_id` on a `ConversionRequest` when a custodian approves it) but does not compare it to any entity's `id`. The same applies when `X-User-Role` is `ComplianceOfficer` or `Auditor`: in both cases `X-User-ID` is an opaque operator identifier that the server may record but does not match against any participant `id`. Segregation of duties is enforced at the conversion-approval step: a `Custodian` whose `X-User-ID` equals the requesting participant's `id` cannot approve that participant's own conversion request — the attempt is rejected with `ERR_SEGREGATION_VIOLATION`.

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

List endpoints accept the standard `limit` and `offset` query parameters. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0. Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order. The `meta` object on every list response includes the four pagination-related fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Top-level participant-facing resources — `Participant`, `Account`, `ConversionRequest`, and `BeneficiaryClaim` — carry the standard set of system-managed fields:

- `id` is a server-minted UUID. It carries no type prefix and is unique across all resources of that type.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, recorded at creation time and never modified.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation to the resource (including system-triggered cascades, not just direct PATCH/POST calls from the client).
- `version` is an integer that begins at 1 on creation and increments by exactly 1 on each mutation. It is the basis for optimistic concurrency control on PATCH endpoints that accept it.

Four entity types do not carry the full common-field set because they are append-once event records rather than evolving resources: `ContributionEvent`, `DistributionEvent`, `Form1099R`, and `ExcessPenalty`. Each of these carries only `id` and `created_at`; neither `updated_at` nor `version` is present on these entities. A `ContributionEvent` that is later reversed records the timestamp of reversal in its own `reversed_at` field rather than refreshing a non-existent `updated_at`. Similarly, a `DistributionEvent` records its settlement timestamp in `settled_at`, and an `ExcessPenalty` records its assessment timestamp in `assessed_at`.

### 2.5. Optimistic Concurrency Control

Mutating endpoints that target a specific resource by id may accept an optional `version` field in the request body. The only PATCH endpoint in the system, which updates a `Participant`, follows this convention. If `version` is supplied and matches the current value on the server, the mutation proceeds and the resource's `version` is incremented by 1. If `version` is supplied but does not match the current value (because another writer has advanced it), the request is rejected with `ERR_VERSION_CONFLICT`. If `version` is omitted from the request body, the server skips the concurrency check and processes the mutation unconditionally.

### 2.6. Nested Resource Validation Order

For any request whose URL path contains multiple resource identifiers (for example, `/participants/{participant_id}/accounts/{account_id}`), the system validates the existence of each identifier in left-to-right order. The first identifier that does not resolve causes immediate rejection with `ERR_NOT_FOUND`, before any rule on the deeper resource is evaluated. The same code is returned when a deeper identifier exists but is out of scope of the parent — for example, an `Account` whose `participant_id` does not equal the `participant_id` in the path is treated as not found rather than as a forbidden cross-tenant access. The same not-found code applies to every single-identifier path variable in the system — `conversion_id` for conversion-request routes, `claim_id` for beneficiary-claim routes, `form_id` for 1099-R routes, and `contribution_id` for contribution-reversal routes — whenever no row matches.

### 2.7. Validation Ordering

Validation runs in a fixed priority sequence so that the rejection a client sees is the first failure in business significance, not the first failure that any particular implementation happens to discover. The ordering, from highest to lowest priority, is:

1. Header presence (`ERR_AUTH_MISSING`).
2. Role recognition (`ERR_AUTH_INVALID_ROLE`).
3. Endpoint-level role authorization (`ERR_FORBIDDEN`).
4. Path-parameter resolution and cross-tenant scoping (`ERR_NOT_FOUND`).
5. Account posture checks — frozen-state restrictions (`ERR_ACCOUNT_FROZEN`) before closed-state restrictions (`ERR_ACCOUNT_CLOSED`).
6. Workflow-state preconditions on the targeted resource (`ERR_INVALID_STATE`).
7. Participant liveness (`ERR_PARTICIPANT_DECEASED`).
8. Beneficiary-claim safety state — forfeit before deadline (`ERR_INHERITED_CLAIM_FORFEITED` then `ERR_SECURE_DEADLINE_EXPIRED`).
9. Domain-specific business constraints on conversions (`ERR_INVALID_CONVERSION_PAIR`, then `ERR_CROSS_PARTICIPANT_CONVERSION`, then `ERR_SEGREGATION_VIOLATION`).
10. Fiscal constraints — cap check (`ERR_CONTRIBUTION_CAP_EXCEEDED`), catch-up eligibility (`ERR_CATCHUP_AGE_INELIGIBLE`), balance availability (`ERR_INSUFFICIENT_BALANCE`), RMD amount match (`ERR_RMD_AMOUNT_MISMATCH`), backdoor preconditions (`ERR_BACKDOOR_PRECONDITION_VIOLATED`).
11. Temporal constraints (`ERR_RMD_PERIOD_CLOSED`, OCC `ERR_VERSION_CONFLICT`).
12. Generic schema validation (`ERR_VALIDATION`) — only reached after every higher-priority check would have passed.

Within the same priority band, fail on the first violated rule rather than aggregating failures.

### 2.8. Monetary Precision and the All-Cents Convention

All monetary quantities in this system are persisted and exchanged as integer cent values. Fields such as `balance_cents`, `ytd_contribution_cents`, `amount_cents`, `gross_amount_cents`, `federal_withholding_cents`, `net_amount_cents`, `prior_year_end_balance_cents`, `drained_amount_cents`, `excess_amount_cents`, `penalty_amount_cents`, `box1_gross_distribution_cents`, `box2a_taxable_amount_cents`, and `box4_federal_withholding_cents` are all whole-cent integers. Wherever a calculation step produces a fractional cent (most commonly when applying a percentage rate or dividing by a life-expectancy divisor), the result is rounded half-up to the nearest whole cent. "Half-up" means a remainder of exactly half a cent rounds away from zero. Pure integer subtractions (such as deriving `net_amount_cents` from `gross_amount_cents` minus `federal_withholding_cents`) introduce no further rounding.

### 2.9. Ledger Consistency and Derived-Field Reconciliation

Every state-changing operation that touches money is atomic with the ledger updates it implies. Posting a contribution adds the cent amount to both `Account.balance_cents` and `Account.ytd_contribution_cents` in the same transaction that creates the `ContributionEvent`. Reversing that contribution does the inverse: it decrements both fields and marks the event reversed in the same transaction that also creates the offsetting `EXCESS_REMOVAL` distribution. Taking a distribution debits `balance_cents` and, in the case of an inherited account that drops to zero, drives the claim to its `DRAINED` state — all within a single transaction. Issuing an excess-contribution penalty debits `balance_cents` by the penalty amount and issues the corresponding 1099-R in the same step. `ytd_contribution_cents` is the live sum of all `POSTED` contribution events for the account in the current `tax_year`; reversed events are excluded from the running total.

### 2.10. The Simulated Clock

The system has a single global logical clock that drives all date-sensitive logic: tax-year boundaries, RMD age, inherited-claim deadlines, and `created_at` / `updated_at` timestamps. Two privileged endpoints advance this clock for testing. Advancing the clock by a given number of `days` may move the current date past one or more `BeneficiaryClaim.deadline_date` values; whenever it does, the forfeit sweep described in §3.5 runs as a side effect. Advancing to the start of the next year (the year-roll endpoint) is a heavier operation: it snapshots every `Account.balance_cents` into `prior_year_end_balance_cents`, then increments the clock year, resets every `Account.ytd_contribution_cents` to 0, runs the excess-contribution sweep on every account, and runs the missed-RMD sweep on every account whose holder's participant age on December 31 is at least 73 (Traditional accounts and every Inherited IRA). The clock-read endpoint returns the current logical date and clock year without mutating anything. All three clock endpoints are available to `Auditor`, `Custodian`, and `ComplianceOfficer`; the read endpoint is additionally available to `Participant`.

### 2.11. Hierarchical Cascade Semantics

Several mutating operations propagate to dependent resources within the same transaction. Each cascade refreshes `updated_at` and increments `version` on every parent-style resource it touches (resources that carry those fields). The two principal cascades both span three layers, mutating four resources from one client call:

- The decease cascade fans out from a `Participant`. Marking a participant deceased flips every owned `Account` from `OPEN` to `FROZEN`, auto-cancels every `PENDING` `ConversionRequest` on those accounts (transitioning their `status` to `CANCELED`), and renders any `Form1099R` with status `ISSUED` for the current tax year on those accounts immutable — the void operation on such a form is blocked from that point forward.
- The conversion completion cascade fans out from a `ConversionRequest`. Completing an approved conversion creates a `DistributionEvent` on the source account with `distribution_reason` equal to `CONVERSION` and `federal_withholding_cents` equal to 0; that event debits the source account's `balance_cents` and credits the destination account's `balance_cents` by `amount_cents`; and a `Form1099R` is auto-issued with `source_event_type` equal to `CONVERSION` and `box7_distribution_code` equal to `G`. The `completed_distribution_id` field on the conversion request is then set to the new distribution's `id`.

The forfeit sweep is a third cascade chain, triggered by the clock rather than by a user action; it is described in §3.5 together with the inherited-claim lifecycle.

## 3. Business Logic & Workflows

### 3.1. Participant Onboarding and Lifecycle

A `Custodian` is the only role permitted to register a new `Participant`. Registration captures the participant's legal `full_name` (a non-empty string of 1 to 120 characters after trimming whitespace), their `date_of_birth` as an ISO 8601 calendar date in `YYYY-MM-DD` form (which must be a real past date and which must place the participant at age 18 or older on the day of creation), and their IRS filing `tax_status`. The four permissible values for `tax_status` are `SINGLE`, `MARRIED_JOINT`, `MARRIED_SEPARATE`, and `HEAD_OF_HOUSEHOLD`; any other value is rejected as a schema violation with `ERR_VALIDATION`. On creation, the system initializes `is_deceased` to `false` and leaves `date_of_death` as `null`.

A custodian may later amend a participant's `full_name` and `tax_status`; these are the only two fields the update operation accepts. Each update accepts an optional `version` field for optimistic concurrency control per §2.5.

When a participant passes away, a custodian records the death by submitting a `date_of_death` (ISO 8601 date). This single action triggers the decease cascade described in §2.11: `is_deceased` flips to `true`, `date_of_death` is recorded, every owned `Account` transitions from `OPEN` to `FROZEN`, every `PENDING` `ConversionRequest` belonging to the participant transitions to `CANCELED`, and current-year issued 1099-R forms on those accounts become void-blocked. After this point any attempt to perform a non-RMD, non-DEATH operation that requires a live participant — posting a new contribution, opening a new conversion request, or approving a pending conversion — is rejected with `ERR_PARTICIPANT_DECEASED`.

### 3.2. Account Opening, Posture, and Closure

Once a participant exists, a `Custodian` opens IRA accounts under their `participant_id`. Account opening accepts the `account_type` (either `TRADITIONAL` or `ROTH`) and an optional `inherited_from_participant_id`. When `inherited_from_participant_id` is supplied, the account is recognized as an Inherited IRA and the SECURE Act ten-year drain window applies: the system simultaneously creates a `BeneficiaryClaim` with `claim_date` equal to the current logical date and `deadline_date` equal to ten calendar years after that, captures the `inheritance_start_date` on the new account, and threads the new claim's `beneficiary_participant_id` to the owning participant. When the field is omitted, no claim is created and the account is treated as the participant's own. The account's initial `status` is `OPEN`, its initial `balance_cents` is 0, its initial `ytd_contribution_cents` is 0, its `tax_year` defaults to the current clock year, and its initial `prior_year_end_balance_cents` is 0. The `participant_id` is immutable after creation.

The `Account.status` enumeration has three values: `OPEN`, `FROZEN`, and `CLOSED`. A custodian or compliance officer may freeze an `OPEN` account at any time (transitioning `OPEN → FROZEN`), and either role may unfreeze a `FROZEN` account back to `OPEN` provided the owning participant is alive (the unfreeze precondition explicitly requires `is_deceased` to be `false`). While `FROZEN`, the account blocks all new `ContributionEvent` creation and blocks all new `DistributionEvent` creation except for those with `distribution_reason` equal to `RMD`, which remain permitted so that required minimum distributions can still be satisfied during a compliance hold. A non-RMD contribution or distribution attempt on a frozen account is rejected with `ERR_ACCOUNT_FROZEN`.

Closing an account is a custodian-only operation that drives the account to its terminal `CLOSED` state. The transition is permitted from either `OPEN` or `FROZEN` and requires that `balance_cents` equal 0 and that no `PENDING` `ConversionRequest` references the account either as source or as destination. From the `OPEN` state the close transition additionally requires that no `BeneficiaryClaim` with status `CLAIMED` references the account. Any subsequent mutation attempt against a `CLOSED` account is rejected with `ERR_ACCOUNT_CLOSED`.

### 3.3. Contributions, Catch-Up Eligibility, and the Annual Cap

A `Participant` (acting on their own account) or a `Custodian` (acting on behalf of any participant) posts a contribution by submitting the `amount_cents` and the `contribution_type`. The amount must be a positive integer of at least 1 cent and at most 1,000,000 cents per single call (a per-call ceiling that protects against accidental over-postings). The `contribution_type` enumeration has three values: `REGULAR`, `CATCHUP`, and `BACKDOOR_NONDEDUCTIBLE`. Posting captures the current clock year as the event's `tax_year`, sets the event's initial `status` to `POSTED`, leaves `reversed_at` as `null`, increments `Account.ytd_contribution_cents` by the contribution amount, and increments `Account.balance_cents` by the same amount — all atomically.

The annual contribution cap is computed per participant at the moment of posting. The base regular cap is 7,000 dollars (700,000 cents). A catch-up addition of 1,000 dollars (100,000 cents) is granted when the participant's age on December 31 of the clock year is at least 50; otherwise the catch-up addition is 0. The applicable cap for the posting decision is therefore the base cap plus the catch-up addition — 700,000 cents for participants younger than 50 on December 31 of the clock year, and 800,000 cents for participants who reach 50 or older by that date. The cap check rejects the contribution with `ERR_CONTRIBUTION_CAP_EXCEEDED` whenever the new posting's `amount_cents` added to the account's current `ytd_contribution_cents` would exceed this applicable cap. (Equality with the cap is permitted; strict over-cap is rejected.)

A separate check applies when `contribution_type` is `CATCHUP`: the participant must independently be at least 50 years old on December 31 of the clock year. A catch-up contribution submitted by a participant who is too young is rejected with `ERR_CATCHUP_AGE_INELIGIBLE`, even if the cap arithmetic would have permitted it.

When two contributions arrive simultaneously for the same account and the second would push the year-to-date total above the applicable cap, the two requests are serialized on the account's `id`. Whichever order persists, the first writer's `ContributionEvent` is accepted in `POSTED` status, and the second writer receives `ERR_CONTRIBUTION_CAP_EXCEEDED`. Similarly, if a participant decease and a fresh contribution race on the same account and decease wins first, the contribution is rejected with `ERR_ACCOUNT_FROZEN` (the cascade flips the account to `FROZEN` before the contribution sees it).

Reversing an excess contribution is a custodian-only operation that targets the contribution by id. Reversal sets the event's `status` to `REVERSED`, stamps its `reversed_at` with the current timestamp, decrements both `Account.ytd_contribution_cents` and `Account.balance_cents` by the original `amount_cents`, and creates a matching `DistributionEvent` with `distribution_reason` equal to `EXCESS_REMOVAL`, `gross_amount_cents` equal to the original contribution amount, and `federal_withholding_cents` equal to 0. The newly-`REVERSED` contribution stops counting toward `ytd_contribution_cents` from that moment forward.

### 3.4. Distributions and Federal Withholding

A `Participant` (own account) or a `Custodian` takes a distribution by submitting a `gross_amount_cents` (a positive integer of at least 1 cent) and a `distribution_reason`. The reason enumeration has six values: `NORMAL`, `EARLY`, `RMD`, `DEATH`, `CONVERSION`, and `EXCESS_REMOVAL`. (The `CONVERSION` and `EXCESS_REMOVAL` reasons are reserved for system-issued distributions emitted by the conversion-completion cascade and the contribution-reversal cascade respectively, not for direct client postings.) The distribution captures the clock year as its `tax_year`, stamps `settled_at` with the current timestamp (atomically with creation and immutable thereafter), and recomputes the account's `balance_cents` downward.

Before persisting, the system computes `federal_withholding_cents` from a layered rate table keyed on `distribution_reason` and the participant's age in the clock year. The rate is selected as follows:

- For `distribution_reason` equal to `CONVERSION` (G-coded conversion movements), the withholding rate is 0%.
- For `distribution_reason` equal to `RMD`, the mandatory RMD rate of 10% applies.
- For `distribution_reason` equal to `EARLY` when the participant is strictly younger than 59 in the clock year, the rate is the standard 10% mandatory rate plus an additional 10% early adder, for a combined rate of 20%. The 20% rate is applied as a single multiplication followed by a single half-up rounding to whole cents — not as two separate 10% withholdings rounded independently, which would double-round and drift the result.
- For `distribution_reason` equal to `NORMAL`, the mandatory normal rate of 10% applies.
- For `distribution_reason` equal to `DEATH`, no mandatory withholding applies (0%).
- For `distribution_reason` equal to `EXCESS_REMOVAL`, no mandatory withholding applies (0%).

The `federal_withholding_cents` is `gross_amount_cents` multiplied by the selected rate, rounded half-up to whole cents. The `net_amount_cents` is then the exact integer difference `gross_amount_cents` minus `federal_withholding_cents` — no further rounding occurs at the subtraction step.

The distribution then debits `Account.balance_cents` by `gross_amount_cents` and triggers issuance of a `Form1099R` with `source_event_type` equal to `DISTRIBUTION`. If the account is inherited and its `balance_cents` reaches 0 as a result of this distribution, the associated `BeneficiaryClaim` transitions from `CLAIMED` to `DRAINED` and its `drained_amount_cents` is incremented by the distribution amount in the same transaction.

The system rejects distributions that would draw the balance negative with `ERR_INSUFFICIENT_BALANCE` (the check requires `gross_amount_cents` to be less than or equal to `Account.balance_cents`).

### 3.5. Required Minimum Distributions

SECURE Act 2.0 sets the RMD age at 73. A `Participant`, `Custodian`, `ComplianceOfficer`, or `Auditor` can read the required RMD amount for any account for any tax year by submitting `tax_year` as a query parameter. The calculation distinguishes three cases:

- A `ROTH` account whose `inherited_from_participant_id` is null (a Roth held by its original owner) has no lifetime RMD, and the required amount is 0.
- A non-inherited account whose owner is younger than 73 in the queried `tax_year` (computed as the queried `tax_year` minus the year-portion of `date_of_birth`) also has a required amount of 0.
- Otherwise, the required amount is computed by dividing the account's `prior_year_end_balance_cents` by a divisor pulled from one of two life-expectancy tables, then rounding the quotient half-up to whole cents.

For a non-inherited account whose owner is 73 or older, the divisor comes from the Uniform Lifetime Table indexed by the participant's age on December 31 of the queried `tax_year`. The table covers (at minimum) ages 73 through 78 with the following divisors: 26.5 at age 73, 25.5 at age 74, 24.6 at age 75, 23.7 at age 76, 22.9 at age 77, and 22.0 at age 78.

For an inherited account (`inherited_from_participant_id` is non-null) where the beneficiary requests an annual RMD before the deadline, the divisor comes from the Single Life Expectancy Table indexed by the beneficiary's age in the year the claim was opened, then decremented by 1 for each subsequent year. The Single Life Table provides (at minimum) the following anchor values: 45.7 at age 40, 41.0 at age 45, 36.2 at age 50, 31.6 at age 55, 27.1 at age 60, 22.9 at age 65, and 18.8 at age 70.

Posting an RMD-coded distribution requires the submitted `gross_amount_cents` to equal the computed RMD amount for that account and tax year exactly. Any mismatch is rejected with `ERR_RMD_AMOUNT_MISMATCH`. At most one RMD-coded distribution may exist per account per tax year; a second simultaneous RMD attempt on the same account in the same tax year is rejected with `ERR_RMD_ALREADY_TAKEN` (serialization is on the tuple of account `id`, `tax_year`, and `RMD` reason; first writer wins). Posting an RMD-coded distribution for a tax year earlier than the current clock year — that is, a tax year that has already been swept by the year-roll endpoint — is rejected with `ERR_RMD_PERIOD_CLOSED`.

The forfeit sweep is the system's response to a missed inherited-account deadline. When the day-advance clock endpoint moves the current date past any `BeneficiaryClaim.deadline_date` while the underlying account still has `balance_cents` greater than 0, that claim is swept: its `status` is set to `FORFEITED`, the associated `Account.status` is flipped to `FROZEN`, an `ExcessPenalty` is issued whose `excess_amount_cents` equals the residual `Account.balance_cents` and whose `penalty_amount_cents` equals 25% of that residual balance (SECURE Act 25% excise) rounded half-up to whole cents, and a `Form1099R` is issued with `source_event_type` equal to `EXCESS_PENALTY` and `box7_distribution_code` equal to `8`. The same sweep applies whether the claim is in `CLAIMED` or `SUSPENDED` status at the moment of the deadline crossing.

Any attempt to take a new distribution on an inherited account whose claim is in `FORFEITED` status is rejected with `ERR_INHERITED_CLAIM_FORFEITED`. A distribution attempt on an inherited account where `current_date` is strictly past `deadline_date` (but the sweep has not yet fired) is rejected with `ERR_SECURE_DEADLINE_EXPIRED`.

### 3.6. The Beneficiary Claim Cycle and the Drawdown Projection

A `BeneficiaryClaim` accompanies every Inherited IRA from the moment the inheritance is recorded. Its `status` enumeration has four values: `CLAIMED` (active, drawdowns permitted), `SUSPENDED` (frozen by compliance review), `DRAINED` (the residual balance reached zero through normal distributions), and `FORFEITED` (the ten-year deadline expired with money still in the account).

A `ComplianceOfficer` may suspend an active claim (transitioning `CLAIMED → SUSPENDED`). While suspended, the system blocks any new `DistributionEvent` against the inherited account. The same compliance officer may resume a suspended claim (transitioning `SUSPENDED → CLAIMED`), provided the current logical date has not yet passed the claim's `deadline_date` — resuming a claim whose deadline has already lapsed is impermissible. Suspension and resumption form a cycle that may repeat any number of times before the claim reaches either of its terminal states.

The forward-looking drawdown projection endpoint accepts an `as_of_date` query parameter and returns a provisional view that the beneficiary uses to plan ahead. The projection computes the remaining years as the integer floor of the number of days between `deadline_date` and `as_of_date` divided by 365. It then computes the projected per-year RMD using the Single Life Expectancy variant of the RMD calculation against the account's current `prior_year_end_balance_cents` snapshot, and multiplies that per-year amount by the remaining years to produce the projected total drawdown. The result contains three fields: the remaining-year count, the projected per-year RMD in cents, and the projected total drawdown in cents.

This projection is provisional, not authoritative. It deliberately holds today's `prior_year_end_balance_cents` constant for every future year, ignores any future contributions or other ledger movement, and ignores any future change to the divisor itself. The final cumulative drawdown that materializes year-by-year as the year-roll endpoint fires can differ materially from the provisional projection, because the realized version recomputes the balance and the divisor every year against the actual `prior_year_end_balance_cents` for that year. Rounding occurs only at the per-year RMD step (half-up to whole cents); the multiplication by remaining-year count is exact integer arithmetic.

### 3.7. Conversion Requests: Traditional-to-Roth and the Backdoor Path

A `Participant` initiates a conversion by submitting the `source_account_id`, the `destination_account_id`, the `amount_cents` to convert (a positive integer of at least 1 cent), and an optional `backdoor_flag` that defaults to `false`. The system creates a `ConversionRequest` in `PENDING` status, captures the `participant_id`, leaves `approver_role_id` as `null`, and leaves `completed_distribution_id` as `null` until the conversion is later completed. The `ConversionRequest.status` enumeration has five values: `PENDING`, `APPROVED`, `REJECTED`, `COMPLETED`, and `CANCELED`.

Two structural checks run at creation time. The source account must be of type `TRADITIONAL` and the destination must be of type `ROTH`; any other pairing is rejected with `ERR_INVALID_CONVERSION_PAIR`. Both accounts must belong to the same participant as the path participant; cross-participant attempts are rejected with `ERR_CROSS_PARTICIPANT_CONVERSION`.

From `PENDING`, the request can branch into either `APPROVED` or `REJECTED`. A `Custodian` approves a pending conversion subject to four preconditions: the request must currently be `PENDING`, both the source account and the destination account must be in `OPEN` status, the owning participant must be alive (`is_deceased` is `false`), and — when `backdoor_flag` is `true` — the source account's `balance_cents` must equal the sum of `amount_cents` across every `POSTED` `ContributionEvent` of type `BACKDOOR_NONDEDUCTIBLE` in the current `tax_year` on that source account, with no other postings and no accumulated earnings. The Backdoor precondition's intent is that the source holds only fresh nondeductible basis with no taxable earnings; if any other contribution type or any earnings have entered the source for the current `tax_year`, approval is rejected with `ERR_BACKDOOR_PRECONDITION_VIOLATED`. Approval records the approving custodian's `X-User-ID` in `approver_role_id` and transitions the request to `APPROVED`. Note that approval is a serial fork — funds do not yet move on approval. The segregation rule (§2.1) blocks approvals where the custodian's `X-User-ID` matches the requesting participant's `id` with `ERR_SEGREGATION_VIOLATION`.

A `Custodian` may instead reject a pending conversion. Rejection requires only that the request is currently `PENDING`; it transitions the request to `REJECTED` and performs no ledger movement.

The originating `Participant` may cancel their own pending conversion (the cancel endpoint requires the canceller's `X-User-ID` to equal the request's `participant_id`); this transitions a `PENDING` request to `CANCELED`. The participant decease cascade may also drive a `PENDING` request to `CANCELED` automatically, as noted in §2.11.

When approve and reject fire simultaneously against the same pending conversion, exactly one wins the race on the request's `status` and the loser is rejected with `ERR_INVALID_STATE`.

Completion is a `Custodian` action that requires the request to be `APPROVED` and the source account's `balance_cents` to be at least the conversion `amount_cents`. Completion triggers the three-link cascade described in §2.11: the source distribution is created and settled, balances move atomically from source to destination, a `Form1099R` is auto-issued, and `completed_distribution_id` is populated on the request. The terminal status after completion is `COMPLETED`.

### 3.8. The Year-End Sweep, Excess Penalties, and Snapshots

The year-roll endpoint is the system's atomic year-boundary transition. It performs four ordered actions, all within a single transaction:

1. For every `Account`, regardless of status, snapshot the current `balance_cents` into `prior_year_end_balance_cents`. This snapshot is the RMD divisor input for the subsequent year, so the snapshot precedes the clock-year increment by design.
2. Increment the clock year by 1.
3. Reset every `Account.ytd_contribution_cents` to 0.
4. Run the excess-contribution assessment on every account. For each account, sum the `amount_cents` of every `ContributionEvent` whose `status` is `POSTED` and whose `tax_year` equals the just-closed clock year (reversed events are excluded). Compare this sum to the applicable contribution cap for the account's participant for that year. If the sum exceeds the cap, the excess is the difference and the penalty is 6% of the excess rounded half-up to whole cents — an `ExcessPenalty` is issued, the account's `balance_cents` is debited by the penalty amount, and a `Form1099R` is issued with `source_event_type` equal to `EXCESS_PENALTY` and `box7_distribution_code` equal to `8`. If the sum is at or below the cap, no penalty is issued for that account.

The year-roll endpoint also runs the missed-RMD sweep: for any `Account` whose participant is at least 73 on December 31 of the just-closed tax year (which applies to every `TRADITIONAL` account in that age band, and to every Inherited IRA regardless of underlying type), if no RMD-coded `DistributionEvent` exists for that account with that `tax_year`, an `ExcessPenalty` is issued at a 25% rate against the missed amount (the SECURE 2.0 reduced excise).

A `Custodian` may also trigger the excess-contribution assessment manually against a specific account at any time during the year through the manual sweep endpoint. The same arithmetic applies: it sums in-year `POSTED` contributions, compares to the applicable cap, and (if there is excess) creates an `ExcessPenalty`, debits the account, and issues a `Form1099R`. If excess is zero, no penalty is created and the call simply reports the no-penalty result.

The `ExcessPenalty` resource carries `account_id`, `tax_year`, `excess_amount_cents`, `penalty_amount_cents`, and `assessed_at` (the timestamp of assessment, whether triggered by the year-end sweep or by the manual endpoint).

### 3.9. Form 1099-R Issuance, Correction, and Voiding

Every taxable event in the system spawns a `Form1099R`. The form's `source_event_type` enumeration has three values — `DISTRIBUTION`, `EXCESS_PENALTY`, and `CONVERSION` — pointing at the spawning event by `source_event_id`. The form records `tax_year`, `recipient_participant_id`, and the four IRS-coded box values: `box1_gross_distribution_cents`, `box2a_taxable_amount_cents`, `box4_federal_withholding_cents`, and `box7_distribution_code`. The `box7_distribution_code` is itself enumerated and may take any of the values `1`, `2`, `7`, `4`, `G`, or `8`. The form's `status` enumeration has three values: `ISSUED` (initial), `CORRECTED`, and `VOIDED`.

A participant lists their 1099-R forms for a specific reporting year by querying the participant-scoped list endpoint with `tax_year` and the optional `limit` and `offset` pagination parameters. Voided forms are excluded from the list. Box-value assembly is per-form (no cross-form aggregation), and the output is sorted by `source_event_id` ascending. The per-form box rules are:

- When the form's `source_event_type` is `DISTRIBUTION`, `box1_gross_distribution_cents` equals the spawning distribution's `gross_amount_cents`. `box7_distribution_code` is `1` when the underlying `distribution_reason` is `EARLY`, `7` when it is `NORMAL` or `RMD`, and `4` when it is `DEATH`. `box2a_taxable_amount_cents` equals the gross amount when the source account is `TRADITIONAL` and equals 0 when the source account is `ROTH`. `box4_federal_withholding_cents` equals the distribution's `federal_withholding_cents`.
- When the form's `source_event_type` is `CONVERSION`, `box1_gross_distribution_cents` equals the conversion request's `amount_cents`, `box7_distribution_code` is `G`, `box4_federal_withholding_cents` is 0, and `box2a_taxable_amount_cents` is 0 when the request's `backdoor_flag` is `true` and equals `amount_cents` when it is `false`. (The Backdoor case is the regulatory point of the Backdoor Roth — nondeductible basis flows tax-free; non-Backdoor conversions of pre-tax Traditional dollars are fully taxable.)
- When the form's `source_event_type` is `EXCESS_PENALTY` and its `status` is `CORRECTED`, the form replays the underlying `ExcessPenalty`: `box1_gross_distribution_cents` and `box2a_taxable_amount_cents` both equal the penalty's `excess_amount_cents` (the excess is fully taxable), `box4_federal_withholding_cents` is 0, and `box7_distribution_code` is `8`.

A `ComplianceOfficer` may issue a corrected form against an `ISSUED` form (transitioning `ISSUED → CORRECTED`), provided the recipient participant is still alive (`is_deceased` is `false`). Correction recomputes `box2a_taxable_amount_cents` from the latest snapshot of the source event.

A `ComplianceOfficer` may void a form (transitioning either `ISSUED → VOIDED` or `CORRECTED → VOIDED`), but only when the underlying source event has been reversed — which is only possible for an `EXCESS_PENALTY` form whose backing `ContributionEvent` was reversed. The current-year void block from the decease cascade overrides this permission: a form with `status` `ISSUED` for the current tax year on a deceased participant's account cannot be voided.

## 4. Endpoint Definitions

Endpoints that create new persistent resources return `201 Created`; endpoints that modify an existing resource (including state transitions, reversals, and clock advances) return `200 OK`. Read endpoints return `200 OK`. All endpoints are mounted under the API base path.

| Method | Path                                                              | Description                                                                                  | Authorized Role(s)                                       |
| ------ | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| POST   | `/_clock/advance`                                                 | Advance system clock by a specified number of days; may fire forfeit sweep                   | Auditor, Custodian, ComplianceOfficer                    |
| POST   | `/_clock/advance-year`                                            | Roll to January 1 of next year; snapshot, reset, excess and missed-RMD sweeps                | Auditor, Custodian, ComplianceOfficer                    |
| GET    | `/_clock`                                                         | Read current system clock state                                                              | Auditor, Custodian, ComplianceOfficer, Participant       |
| POST   | `/participants`                                                   | Create a new participant                                                                     | Custodian                                                |
| GET    | `/participants/{participant_id}`                                  | Read a participant                                                                           | Custodian, ComplianceOfficer, Auditor, Participant       |
| PATCH  | `/participants/{participant_id}`                                  | Update participant `full_name` and `tax_status` (OCC via `version`)                          | Custodian                                                |
| POST   | `/participants/{participant_id}/decease`                          | Mark participant deceased and run the decease cascade                                        | Custodian                                                |
| POST   | `/participants/{participant_id}/accounts`                         | Open a Traditional or Roth IRA, optionally as an Inherited IRA                               | Custodian                                                |
| GET    | `/participants/{participant_id}/accounts/{account_id}`            | Read an account                                                                              | Custodian, ComplianceOfficer, Auditor, Participant       |
| POST   | `/accounts/{account_id}/freeze`                                   | Freeze an open account                                                                       | Custodian, ComplianceOfficer                             |
| POST   | `/accounts/{account_id}/unfreeze`                                 | Unfreeze a frozen account                                                                    | Custodian, ComplianceOfficer                             |
| POST   | `/accounts/{account_id}/close`                                    | Close an account with zero balance                                                           | Custodian                                                |
| POST   | `/accounts/{account_id}/contributions`                            | Post a contribution against an account                                                       | Participant, Custodian                                   |
| POST   | `/contributions/{contribution_id}/reverse`                        | Reverse a contribution; emits offsetting `EXCESS_REMOVAL` distribution                       | Custodian                                                |
| POST   | `/accounts/{account_id}/distributions`                            | Take a distribution (`NORMAL`, `EARLY`, `RMD`, `DEATH`, `CONVERSION`, `EXCESS_REMOVAL`)      | Participant, Custodian                                   |
| GET    | `/accounts/{account_id}/rmd`                                      | Read required RMD amount for a tax year                                                      | Participant, Custodian, ComplianceOfficer, Auditor       |
| POST   | `/accounts/{account_id}/excess-sweep`                             | Manually assess excess-contribution penalty for current tax year                             | Custodian                                                |
| POST   | `/conversion-requests`                                            | Open a Traditional-to-Roth conversion (optionally Backdoor)                                  | Participant                                              |
| GET    | `/conversion-requests/{conversion_id}`                            | Read a conversion request                                                                    | Participant, Custodian, ComplianceOfficer, Auditor       |
| POST   | `/conversion-requests/{conversion_id}/approve`                    | Custodian approves a pending conversion                                                      | Custodian                                                |
| POST   | `/conversion-requests/{conversion_id}/reject`                     | Custodian rejects a pending conversion                                                       | Custodian                                                |
| POST   | `/conversion-requests/{conversion_id}/cancel`                     | Participant cancels their own pending conversion                                             | Participant                                              |
| POST   | `/conversion-requests/{conversion_id}/complete`                   | Custodian completes the conversion (cascades distribution + 1099-R)                          | Custodian                                                |
| GET    | `/beneficiary-claims/{claim_id}`                                  | Read a beneficiary claim                                                                     | Participant, Custodian, ComplianceOfficer, Auditor       |
| POST   | `/beneficiary-claims/{claim_id}/suspend`                          | Compliance suspends an active claim                                                          | ComplianceOfficer                                        |
| POST   | `/beneficiary-claims/{claim_id}/resume`                           | Compliance resumes a suspended claim                                                         | ComplianceOfficer                                        |
| GET    | `/beneficiary-claims/{claim_id}/projection`                       | Forward-looking projected drawdown to `deadline_date`                                        | Participant, Custodian, ComplianceOfficer, Auditor       |
| GET    | `/participants/{participant_id}/forms-1099r`                      | List a participant's 1099-R forms for a `tax_year`                                           | Participant, Custodian, ComplianceOfficer, Auditor       |
| POST   | `/forms-1099r/{form_id}/correct`                                  | Issue a corrected form replaying the source event                                            | ComplianceOfficer                                        |
| POST   | `/forms-1099r/{form_id}/void`                                     | Void a form whose source event has been reversed                                             | ComplianceOfficer                                        |

## 5. Error Code Catalogue

| Error ID                              | HTTP Status |
| ------------------------------------- | ----------- |
| `ERR_AUTH_MISSING`                    | 401         |
| `ERR_AUTH_INVALID_ROLE`               | 401         |
| `ERR_FORBIDDEN`                       | 403         |
| `ERR_NOT_FOUND`                       | 404         |
| `ERR_VALIDATION`                      | 400         |
| `ERR_ACCOUNT_FROZEN`                  | 409         |
| `ERR_ACCOUNT_CLOSED`                  | 409         |
| `ERR_INVALID_STATE`                   | 409         |
| `ERR_PARTICIPANT_DECEASED`            | 409         |
| `ERR_INHERITED_CLAIM_FORFEITED`       | 409         |
| `ERR_SECURE_DEADLINE_EXPIRED`         | 422         |
| `ERR_INVALID_CONVERSION_PAIR`         | 422         |
| `ERR_CROSS_PARTICIPANT_CONVERSION`    | 422         |
| `ERR_SEGREGATION_VIOLATION`           | 403         |
| `ERR_CONTRIBUTION_CAP_EXCEEDED`       | 422         |
| `ERR_CATCHUP_AGE_INELIGIBLE`          | 422         |
| `ERR_INSUFFICIENT_BALANCE`            | 422         |
| `ERR_RMD_AMOUNT_MISMATCH`             | 422         |
| `ERR_BACKDOOR_PRECONDITION_VIOLATED`  | 422         |
| `ERR_RMD_PERIOD_CLOSED`               | 409         |
| `ERR_VERSION_CONFLICT`                | 409         |
| `ERR_RMD_ALREADY_TAKEN`               | 409         |

# Restitution & Court-Fee Collection API — Product Requirements Document

## 1. Introduction

Courts assess restitution owed to victims, court fees, fines, and surcharges against defendants, and then face the far harder problem of collecting, allocating, and accounting for that money over months or years. This API is the system of record for that collection lifecycle. It tracks every dollar a court is owed on a case, distributes incoming payments across competing obligations according to statutory priority, moves collected restitution out to the victims who are entitled to it, and manages the enforcement machinery — delinquency detection, civil judgments, license holds, and wage assignments — that courts rely on when an obligor falls behind.

The domain is fundamentally a ledger reconciliation problem layered on top of a compliance workflow. Money owed and money in must always agree, down to the cent, across a case and each of its obligations; collected restitution held for a victim can never be disbursed twice; and sensitive actions such as waiving a debt or reversing a posted payment demand a segregation of duties between the clerk who records money and the supervisor who authorizes concessions. Because collections play out over long calendar windows, the system runs on a server-controlled logical clock rather than wall-clock time, allowing delinquency, aging, and amnesty windows to be evaluated deterministically. All amounts are represented and computed in integer cents.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. All resources are exposed as top-level collections mounted under the `/collections` prefix; there is no parent-id nesting in URL paths, and entities relate to one another through foreign-key references carried in request bodies.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not one of the four roles below, the request is rejected with `ERR_UNAUTHENTICATED`. If the header is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles:

- `CollectionsClerk` — the front-line clerk who records money owed and money in: creates cases, victims, obligations, payment plans, and payments, and may request waivers.
- `CollectionsSupervisor` — the supervisor who authorizes concessions and reversals: approves or denies waiver requests, writes off aged obligations, reverses posted payments, activates and reinstates payment plans, and lifts enforcement actions. A supervisor may also request waivers.
- `FinanceOfficer` — the treasury role that disburses collected restitution to victims and voids those disbursements, and that issues and terminates wage-assignment orders.
- `SystemAdmin` — the operational role that configures amnesty programs, advances the logical clock, and runs the delinquency sweep.

Any authenticated role may issue read (GET) requests against any resource. For all four roles, `X-User-ID` is an **opaque operator identifier** that is not tied to any persisted entity; the server never compares it to any resource's `id`. It is, however, recorded where a business rule demands it: when a waiver request is created, the requester's `X-User-ID` is captured as `requested_by_user_id`, and when a waiver is approved, the approver's `X-User-ID` is captured as `approved_by_user_id`. These recorded values drive the segregation-of-duties checks described in §3.6.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every top-level resource in the system — Cases, Victims, Obligations, Payment Plans, Payments, Disbursements, Wage Assignments, Enforcement Actions, Waiver Requests, and Amnesty Programs — carries a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, in the same format, recording the last modification to the resource.
- `version` — a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource.

Because a resource's derived fields are recomputed when its children change, any reconciliation that alters a resource's persisted values is itself a mutation: it refreshes `updated_at` and increments `version`. In particular, creating an obligation, posting or reversing a payment, or otherwise changing a case's aggregates increments that case's `version`.

### 2.5. Monetary Values and Precision

All monetary amounts in the system are integers denominated in cents; there are no fractional cents and no floating-point money. Where a calculation produces a non-integer intermediate — the per-share split in a pro-rata allocation, or the ability-to-pay installment — the result is reduced to whole cents by the rule stated with that calculation: pro-rata per-obligation shares are computed by taking the floor (rounding down), and the ability-to-pay installment rounds its rate computation half up (a value exactly at the half-cent rounds up). Day-based thresholds (delinquency grace, obligation aging) are computed as whole days using floor division, as described with each rule.

### 2.6. The Logical Clock

Time in this system is a server-controlled logical clock, never wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and it holds that value until an administrator advances it. An administrative test-driving capability accepts a `to_iso8601` instant and sets the clock to it, returning the new `current_utc`; this operation performs no entity mutations. Every rule that speaks of "the current date" or "now" — plan due dates, delinquency evaluation, obligation aging, amnesty-window coverage — reads this logical clock.

### 2.7. Reference Integrity and Left-to-Right Validation

Requests routinely name other resources, either as a path identifier or as a foreign-key field in the body (for example a `case_id`, `victim_id`, or `obligation_id`). The system validates every such reference for existence, in left-to-right order — path identifiers first, then body references in the order they appear — and rejects the first unresolved reference with `ERR_NOT_FOUND`. Only once all referenced resources are confirmed to exist does the system evaluate business rules.

### 2.8. Case Ledger Reconciliation and Derived Aggregates

A Case is a rollup of its obligations, and its money fields are always **derived**, never set directly. Whenever any obligation of a case mutates — a payment posts or is reversed, a waiver is approved, an obligation is written off — the system reconciles the whole case from its obligations, as follows.

For each obligation, its `balance_cents` is 0 when its `status` is `WRITTEN_OFF` or `WAIVED`; otherwise it is the assessed amount less what has been paid and waived, floored at zero — that is, the greater of zero and (`assessed_amount_cents` minus `paid_amount_cents` minus `waived_amount_cents`). From those obligations the case aggregates are recomputed: `total_assessed_cents` is the sum of `assessed_amount_cents` across all obligations of the case; `total_paid_cents` is the sum of `paid_amount_cents` across all obligations; `total_waived_cents` is the sum of `waived_amount_cents` across all obligations; and `total_written_off_cents` accumulates, for each obligation whose `status` is `WRITTEN_OFF`, the balance that was outstanding (assessed less prior paid and waived) at write-off. The case's `balance_cents` is the sum of `balance_cents` over only those obligations whose status is neither `WRITTEN_OFF` nor `WAIVED`. Finally, the case's `status` becomes `SATISFIED` when `total_assessed_cents` is greater than zero and the case `balance_cents` is exactly zero; otherwise it is `OPEN`.

A GET on a case, victim, or obligation always reflects freshly reconciled values.

### 2.9. Optimistic Concurrency Control

Creating a payment plan is guarded by optimistic concurrency against the parent case. A create-payment-plan request must carry `expected_case_version` as a required field, holding the `version` of the target case that the client last observed. If `expected_case_version` does not match the case's current `version` at the time of the request, the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). This matters because a newly created plan legitimately supersedes any still-`PROPOSED` plan on the same case; rejecting a stale-version create prevents a client from superseding a proposal it never saw. No other endpoint takes a version field; only payment-plan creation participates in this check.

### 2.10. Validation Order and Error Precedence

When a request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failure determines the error returned:

1. **Authentication** — `X-User-Role` present and one of the four declared roles, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for this operation, else `ERR_FORBIDDEN` (403).
3. **Existence** — all path identifiers and body foreign-key references resolve (left-to-right), else `ERR_NOT_FOUND` (404).
4. **Well-formedness** — required fields present, enums valid, and amounts are integers greater than zero where a positive amount is required, else `ERR_INVALID_REQUEST` (400).
5. **Optimistic concurrency** — on payment-plan creation, `expected_case_version` matches the case's `version`, else `ERR_STALE_CASE_VERSION` (412).
6. **State** — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE` (409).
7. **Referential business rules** — restitution/victim pairing and waiver-obligation-to-case membership, yielding `ERR_VICTIM_REQUIRED` (422) or `ERR_OBLIGATION_CASE_MISMATCH` (422).
8. **Temporal business rules** — amnesty-window coverage for waiver approval (`ERR_NO_ACTIVE_AMNESTY`, 409) and valid date ranges (`ERR_INVALID_DATE_RANGE`, 422).
9. **Safety / segregation of duties** — the waiver approver or denier differs from the requester, else `ERR_SOD_CONFLICT` (409).
10. **Interval, uniqueness, and cap constraints** — non-overlapping amnesty windows, aggregate withholding cap, single active plan per case, unique case number, waiver amnesty cap, and write-off aging.
11. **Fiscal amount constraints** — payment, disbursement, waiver, and reversal amount ceilings.

The specific trigger conditions for the checks in tiers 6 through 11 are described alongside the workflows they guard in §3; the mapping from each condition to its `error_id` is given there.

## 3. Business Logic & Workflows

### 3.1. Opening Cases and Recording Obligations

A `CollectionsClerk` opens a **Case** by supplying a `case_number` (the court docket number, which must be unique across all cases) and the `defendant_name` of the obligor. A newly created case starts with `status` `OPEN`, `delinquency_status` `CURRENT`, and every monetary aggregate initialized to zero. If the supplied `case_number` is already used by another case, the request is rejected with `ERR_CASE_NUMBER_TAKEN`.

A `CollectionsClerk` also records each **Victim** entitled to restitution, providing only the victim's `name`. A victim's `payable_balance_cents` — the restitution collected and still owed out to that victim — begins at zero and is thereafter derived (see §3.3 and §3.5).

Against an `OPEN` case, a `CollectionsClerk` records the individual debts as **Obligations**. Each obligation names its `case_id` and carries an `obligation_type` — one of `RESTITUTION`, `COURT_FEE`, `FINE`, or `SURCHARGE` — and an `assessed_amount_cents`, the amount the court assessed, which must be greater than zero. An obligation of type `RESTITUTION` must name the `victim_id` it is owed to; for any other type a `victim_id` must not be supplied. Violating either half of that rule — a restitution obligation with no victim, or a non-restitution obligation carrying a victim — is rejected with `ERR_VICTIM_REQUIRED`.

Each obligation also carries a `priority_rank` that governs the order in which payments fill it — lower ranks are paid first. If the client omits `priority_rank`, it defaults from the obligation type: restitution takes rank 1, court fees rank 2, fines rank 3, and surcharges rank 4. A new obligation begins in `status` `OUTSTANDING`, with `paid_amount_cents`, `waived_amount_cents`, and `balance_cents` derived. Creating an obligation reconciles the case aggregates and therefore advances the case `version`.

### 3.2. Payment Plans and Ability to Pay

When an obligor cannot pay in a lump sum, a `CollectionsClerk` proposes a **Payment Plan** for a case. The request names the `case_id`, the obligor's declared gross `monthly_income_cents` and allowable `monthly_expenses_cents` (each an integer of at least zero), an `ability_to_pay_method`, and — per §2.9 — the `expected_case_version`.

The plan's `monthly_amount_cents` is computed at creation from an ability-to-pay basis. When `ability_to_pay_method` is `NET_DISPOSABLE`, the basis is the obligor's disposable income: the greater of zero and (`monthly_income_cents` minus `monthly_expenses_cents`). When it is `GROSS_INCOME`, the basis is simply `monthly_income_cents`, ignoring expenses — so for identical inputs the gross method yields a larger installment than the net method. The system multiplies the basis by an ability-to-pay rate of 10 percent and rounds the product half up to whole cents; it then raises that figure to a minimum installment floor of 2,500 cents (25 dollars) if it fell below it; and finally it caps the installment at the case's current `balance_cents`, so a plan never charges more than is owed. The resulting value is stored as `monthly_amount_cents`.

A newly created plan begins in `status` `PROPOSED` with `next_due_date` null and `missed_payment_count` zero. Creating a plan for a case that already has a still-`PROPOSED` plan supersedes the older one: the prior plan transitions from `PROPOSED` to `SUPERSEDED` and the newest plan becomes the case's live proposal.

A `CollectionsSupervisor` activates a proposal, transitioning it from `PROPOSED` to `ACTIVE`. Activation requires that the case `status` be `OPEN` (otherwise `ERR_CASE_NOT_OPEN`) and that no other plan on the case is already `ACTIVE` (otherwise `ERR_ACTIVE_PLAN_EXISTS`). On activation the plan's `next_due_date` is set to the current logical-clock date plus a due interval of 30 days.

Should a plan later fall into default (see §3.9), a `CollectionsSupervisor` may reinstate it, moving it from `DEFAULTED` back to `ACTIVE`. Reinstatement likewise requires the case `status` to be `OPEN`; it resets `missed_payment_count` to zero, sets `next_due_date` to the current clock date plus the same 30-day due interval, and resets the case's `delinquency_status` back to `CURRENT`.

### 3.3. Posting Payments and Waterfall Allocation

A `CollectionsClerk` records money received by posting a **Payment** against a case. The request supplies the `case_id`, the `amount_cents` received (which must be greater than zero and must not exceed the case's `balance_cents` at posting time — otherwise `ERR_AMOUNT_EXCEEDS_BALANCE`), and an `allocation_method` of either `STATUTORY_PRIORITY` or `PRO_RATA`. A posted payment is immediately `POSTED` and its distribution across obligations is recorded as a frozen list of ledger lines in `allocations`, each line being an `obligation_id` and the `amount_cents` applied to it.

The candidate obligations for a payment are those of the case whose `status` is `OUTSTANDING` or `PARTIALLY_PAID` and whose `balance_cents` is greater than zero, considered in order of `priority_rank` ascending, breaking ties by `created_at` ascending.

Under `STATUTORY_PRIORITY`, the system walks that ordered list and gives each obligation the smaller of the payment amount still remaining and that obligation's `balance_cents`, stopping when the payment is exhausted. A lower-priority obligation receives nothing until every higher-priority obligation above it is fully covered.

Under `PRO_RATA`, the system first sums the `balance_cents` of all candidates to get a total. Each candidate's provisional share is the floor of the payment amount multiplied by that candidate's `balance_cents` divided by the total. Flooring leaves a remainder — the payment amount minus the sum of the provisional shares — which is then distributed one cent at a time to candidates in `priority_rank` ascending order, breaking ties by `created_at` ascending, until the remainder is used up. Because the split is proportional rather than sequential, the same payment produces different per-obligation results than statutory priority would.

For every non-zero allocation, the obligation's `paid_amount_cents` increases by the amount applied and a corresponding line is appended to the payment's `allocations`. Each touched obligation then re-derives: if the allocation leaves it with paid plus waived still short of assessed (a partial fill), it moves from `OUTSTANDING` to `PARTIALLY_PAID`; if paid plus waived now equals `assessed_amount_cents`, its `balance_cents` becomes zero and it moves to `SATISFIED` (from either `OUTSTANDING` or `PARTIALLY_PAID`). Whenever a `RESTITUTION` obligation collects money, the linked victim's `payable_balance_cents` increases by the restitution collected. The case aggregates are then reconciled per §2.8, and if the case `balance_cents` reaches zero, the case `status` becomes `SATISFIED` and any `ACTIVE` payment plan on the case transitions to `COMPLETED`.

A victim's `payable_balance_cents` is itself a derived quantity: it is the restitution collected for that victim — the sum, over `POSTED` payment allocation lines that target a `RESTITUTION` obligation belonging to that victim, of the amounts allocated — less the sum of that victim's disbursements whose status commits the funds (see §3.5). This value never goes negative.

### 3.4. Reversing a Payment

A `CollectionsSupervisor` may reverse a posted payment as a compensating action. Reversal is permitted only while the payment's `status` is `POSTED`; attempting to reverse an already-reversed payment yields `ERR_INVALID_STATE`. Reversal is additionally blocked when the restitution it collected has already been paid out: if unwinding the payment would drive any affected victim's `payable_balance_cents` below zero, the reversal is rejected with `ERR_AMOUNT_EXCEEDS_BALANCE`.

On a successful reversal, the payment moves from `POSTED` to `REVERSED`. Each obligation the payment touched has its `paid_amount_cents` reduced by the amount that obligation was allocated, reversing the posting cascade; the payment's `allocations` are cleared for accounting purposes. Affected obligations revert accordingly — an obligation reverts from `SATISFIED` to `PARTIALLY_PAID` when some paid amount remains, or from `PARTIALLY_PAID` to `OUTSTANDING` when its paid amount returns to zero. Any restitution collected by the reversed payment is removed from the affected victims' `payable_balance_cents`. The case aggregates are then reconciled, and `total_paid_cents` returns to its pre-posting value.

### 3.5. Disbursing Restitution to Victims

A `FinanceOfficer` moves collected restitution out to a victim by creating a **Disbursement**. The request names the `victim_id` being paid and the `case_id` whose collected restitution funds the payout, together with an `amount_cents` that must be greater than zero and must not exceed the victim's `payable_balance_cents` at creation time — an over-draw is rejected with `ERR_AMOUNT_EXCEEDS_BALANCE`. A newly created disbursement is in `status` `PENDING`, the issued-and-committed state, and immediately debits the victim's `payable_balance_cents` by its `amount_cents`. Because a `PENDING` disbursement already commits the funds, it counts against the victim's payable balance and thereby constrains later payment reversals (see §3.4).

A `FinanceOfficer` may void a disbursement as a compensating action. Voiding is permitted only while the disbursement is `PENDING`; voiding anything else yields `ERR_INVALID_STATE`. A void moves the disbursement to `VOIDED` and credits the victim's `payable_balance_cents` back by the disbursement's `amount_cents`.

### 3.6. Waivers and Amnesty Programs

Debts are forgiven only inside an active amnesty program and only with a separation between the person who asks and the person who approves. A `SystemAdmin` configures an **Amnesty Program** by supplying a `name`, a `start_date`, an `end_date`, and a `waiver_pct` — the maximum fraction of an obligation's assessed amount that may be waived during the window, which must be greater than zero and at most 1. The program's active window is the half-open interval running from `start_date` inclusive up to `end_date` exclusive; `end_date` must be strictly after `start_date`, or the request is rejected with `ERR_INVALID_DATE_RANGE`. Amnesty windows may not overlap: a new window conflicts with an existing one when the new window's `start_date` is before the existing window's `end_date` and the existing window's `start_date` is before the new window's `end_date`, and any such overlap is rejected with `ERR_AMNESTY_WINDOW_OVERLAP`. Two windows that merely touch at an endpoint — where one's `start_date` equals the other's `end_date` — share no interior instant and are permitted.

Either a `CollectionsClerk` or a `CollectionsSupervisor` files a **Waiver Request** naming the `case_id`, the `obligation_id` to waive against, and the `requested_amount_cents` (greater than zero). The named obligation must belong to the named case; if it does not, the request is rejected with `ERR_OBLIGATION_CASE_MISMATCH`. On creation the request is in `status` `REQUESTED`, and the filer's identity is captured in `requested_by_user_id`.

A `CollectionsSupervisor` resolves a request by approving or denying it. For an **approval**, the checks are, in order: the approver's `X-User-ID` must differ from the request's `requested_by_user_id`, or the approval is rejected for segregation of duties with `ERR_SOD_CONFLICT`; an amnesty program window must cover the current logical-clock date, or the approval is rejected with `ERR_NO_ACTIVE_AMNESTY`; the `requested_amount_cents` must not exceed the obligation's current `balance_cents`, or it is rejected with `ERR_WAIVER_EXCEEDS_BALANCE`; and the `requested_amount_cents` must not exceed the amnesty cap, the floor of the obligation's `assessed_amount_cents` multiplied by the covering program's `waiver_pct`, or it is rejected with `ERR_WAIVER_EXCEEDS_AMNESTY_CAP`. On approval the request moves to `APPROVED`, the approver's `X-User-ID` is recorded in `approved_by_user_id`, and the obligation's `waived_amount_cents` increases by `requested_amount_cents`. The obligation then settles toward `WAIVED`: from `OUTSTANDING` when the waiver fully covers the balance, and from `PARTIALLY_PAID` when the requested amount equals the remaining balance so that the waiver settles the rest; its `balance_cents` becomes zero and the case aggregates (including `total_waived_cents`) are reconciled.

For a **denial**, the sole check is the same segregation of duties: the denier's `X-User-ID` must differ from `requested_by_user_id`, or the request is rejected with `ERR_SOD_CONFLICT`. A denial moves the request to `DENIED` and leaves the obligation unchanged.

### 3.7. Aging and Write-Off

Long-uncollectible debts are eventually removed from a case's live balance. A `CollectionsSupervisor` writes off an obligation once it is old enough. An obligation's age is the whole number of days, floored, between the current logical-clock time and the obligation's `created_at`. Write-off requires that this age be at least 1,825 days — five years — otherwise the request is rejected with `ERR_WRITEOFF_TOO_EARLY`; it also requires that the obligation still have something owed, a `balance_cents` greater than zero, otherwise `ERR_NOTHING_TO_WRITE_OFF`. A written-off obligation moves to `WRITTEN_OFF` (from either `OUTSTANDING` or `PARTIALLY_PAID`); the case's `total_written_off_cents` increases by the balance removed, that obligation drops out of the case `balance_cents`, and the case aggregates are reconciled.

Any authenticated role may pull the portfolio **aging report**, optionally narrowed to a single case by a `case_id` query parameter. The report considers obligations whose status is `OUTSTANDING` or `PARTIALLY_PAID` and buckets their outstanding balances by the same floored age in days: `bucket_0_30_cents` for ages 0 through 30, `bucket_31_90_cents` for 31 through 90, `bucket_91_365_cents` for 91 through 365, and `bucket_366_plus_cents` for 366 days up through 1,824 days. Balances on obligations that have reached the five-year write-off threshold — age of at least 1,825 days — are reported separately as `writeoff_eligible_cents`.

### 3.8. Wage Assignments

A `FinanceOfficer` issues a **Wage Assignment** ordering an employer to withhold from the obligor's pay. The order names the `case_id`, the `employer_name` executing the withholding, the `monthly_withhold_cents` (greater than zero), and the closed effective interval from `effective_start_date` through `effective_end_date` inclusive. The `effective_end_date` must be on or after the `effective_start_date`, or the request is rejected with `ERR_INVALID_DATE_RANGE`.

There is a ceiling on how much may be withheld from one obligor at a time. When a new order is issued, the system finds the `ACTIVE` wage assignments of the same case whose closed effective interval intersects the new interval — two closed intervals intersect when they share at least one instant, so touching endpoints count as overlap. If the new order's `monthly_withhold_cents` plus the sum of `monthly_withhold_cents` across that overlapping set would exceed 50,000 cents (500 dollars) per month, the order is rejected with `ERR_WITHHOLD_CAPACITY_EXCEEDED`. A newly issued order is `ACTIVE`.

A `FinanceOfficer` may terminate an active order; termination is permitted only while the assignment is `ACTIVE` (otherwise `ERR_INVALID_STATE`), moves it to `TERMINATED`, and frees its interval so that its withholding no longer counts toward the monthly cap for future orders.

### 3.9. Delinquency Sweep and Enforcement Cascade

Delinquency is detected by a scheduled evaluation that a `SystemAdmin` runs. The sweep examines every payment plan whose `status` is `ACTIVE` and whose `next_due_date` is not null, and computes the days past due as the floored number of days between the current logical-clock time and the plan's `next_due_date`. A plan whose days past due is at least the 30-day grace window defaults. The sweep reports the identifiers of the plans it defaulted as `defaulted_plan_ids` and the enforcement actions it created as `enforcement_action_ids`.

When a plan defaults, it transitions from `ACTIVE` to `DEFAULTED` and a cascade fires. The plan's `missed_payment_count` increases by one. The case's `delinquency_status` flips to `DELINQUENT`. An **Enforcement Action** of `type` `CIVIL_JUDGMENT` is docketed for the case, with its `amount_cents` capturing the case's `balance_cents` at the moment of docketing. That civil judgment in turn triggers a second enforcement action of `type` `LICENSE_HOLD`, whose `amount_cents` is zero. Both enforcement actions are created directly by this cascade — never by a client body — and both begin in `status` `ACTIVE`. Because enforcement actions are created only by the sweep, listing them (optionally filtered by `case_id` or by `type`) is the only way to discover them.

A `CollectionsSupervisor` lifts an enforcement action — vacating a civil judgment or releasing a license hold — but only once the case is no longer delinquent: lifting requires the case's `delinquency_status` to be `CURRENT`, and otherwise fails with `ERR_CASE_STILL_DELINQUENT`. In practice this means the supervisor must first reinstate the defaulted plan (§3.2), which resets the case to `CURRENT`, before the holds against the case can be lifted. A lifted action moves to `status` `LIFTED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or drive a state transition on an existing resource — activations, reversals, voids, approvals, and the like — return `200 OK`. Request and response payloads are reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/collections/cases` | Create a Case | CollectionsClerk |
| GET | `/collections/cases/{case_id}` | Get a Case with recomputed aggregates | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/victims` | Create a Victim (restitution payee) | CollectionsClerk |
| GET | `/collections/victims/{victim_id}` | Get a Victim with recomputed payable balance | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/obligations` | Create an Obligation on a case | CollectionsClerk |
| GET | `/collections/obligations/{obligation_id}` | Get an Obligation with recomputed paid/waived/balance | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| GET | `/collections/obligations` | List obligations filtered by case, victim, or status | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/obligations/{obligation_id}/write-off` | Write off an aged obligation | CollectionsSupervisor |
| POST | `/collections/payment-plans` | Create a payment plan (ability-to-pay; OCC on case version) | CollectionsClerk |
| GET | `/collections/payment-plans/{payment_plan_id}` | Get a PaymentPlan | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| GET | `/collections/payment-plans` | List payment plans filtered by case | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/payment-plans/{payment_plan_id}/activate` | Activate a PROPOSED plan | CollectionsSupervisor |
| POST | `/collections/payment-plans/{payment_plan_id}/reinstate` | Reinstate a DEFAULTED plan | CollectionsSupervisor |
| POST | `/collections/payments` | Post a payment and allocate across obligations | CollectionsClerk |
| GET | `/collections/payments/{payment_id}` | Get a Payment including its allocation lines | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| GET | `/collections/payments` | List payments filtered by case | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/payments/{payment_id}/reverse` | Reverse a posted payment | CollectionsSupervisor |
| POST | `/collections/disbursements` | Disburse collected restitution to a victim | FinanceOfficer |
| GET | `/collections/disbursements/{disbursement_id}` | Get a Disbursement | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| GET | `/collections/disbursements` | List disbursements filtered by victim or case | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/disbursements/{disbursement_id}/void` | Void a disbursement | FinanceOfficer |
| POST | `/collections/wage-assignments` | Issue a wage-assignment withholding order | FinanceOfficer |
| GET | `/collections/wage-assignments/{wage_assignment_id}` | Get a WageAssignment | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| GET | `/collections/wage-assignments` | List wage assignments filtered by case | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/wage-assignments/{wage_assignment_id}/terminate` | Terminate an ACTIVE wage assignment | FinanceOfficer |
| GET | `/collections/enforcement-actions/{enforcement_action_id}` | Get an EnforcementAction | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| GET | `/collections/enforcement-actions` | List enforcement actions filtered by case or type | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/enforcement-actions/{enforcement_action_id}/lift` | Lift a civil judgment or license hold | CollectionsSupervisor |
| POST | `/collections/waiver-requests` | Request a waiver against an obligation | CollectionsClerk, CollectionsSupervisor |
| GET | `/collections/waiver-requests/{waiver_request_id}` | Get a WaiverRequest | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| GET | `/collections/waiver-requests` | List waiver requests filtered by case or obligation | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/waiver-requests/{waiver_request_id}/approve` | Approve a waiver | CollectionsSupervisor |
| POST | `/collections/waiver-requests/{waiver_request_id}/deny` | Deny a waiver | CollectionsSupervisor |
| POST | `/collections/amnesty-programs` | Create an amnesty program window | SystemAdmin |
| GET | `/collections/amnesty-programs/{amnesty_program_id}` | Get an AmnestyProgram | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |
| POST | `/collections/_clock/set_current_utc` | Set the server logical clock (test-driving) | SystemAdmin |
| POST | `/collections/delinquency-sweep` | Evaluate ACTIVE plans and default those past grace | SystemAdmin |
| GET | `/collections/reports/aging` | Portfolio aging & write-off eligibility report | CollectionsClerk, CollectionsSupervisor, FinanceOfficer, SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VICTIM_REQUIRED` | 422 |
| `ERR_OBLIGATION_CASE_MISMATCH` | 422 |
| `ERR_NO_ACTIVE_AMNESTY` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_SOD_CONFLICT` | 409 |
| `ERR_AMNESTY_WINDOW_OVERLAP` | 409 |
| `ERR_WITHHOLD_CAPACITY_EXCEEDED` | 409 |
| `ERR_ACTIVE_PLAN_EXISTS` | 409 |
| `ERR_CASE_NOT_OPEN` | 409 |
| `ERR_CASE_STILL_DELINQUENT` | 409 |
| `ERR_WAIVER_EXCEEDS_BALANCE` | 409 |
| `ERR_WAIVER_EXCEEDS_AMNESTY_CAP` | 409 |
| `ERR_WRITEOFF_TOO_EARLY` | 409 |
| `ERR_NOTHING_TO_WRITE_OFF` | 409 |
| `ERR_AMOUNT_EXCEEDS_BALANCE` | 409 |
| `ERR_CASE_NUMBER_TAKEN` | 409 |

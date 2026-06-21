# Auto Loan & Lease End API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Auto Loan & Lease End API, a back-office platform that a dealership's finance desk uses to originate vehicle financing, service it through its life, and bring it to an orderly close. The system spans two parallel financing products that share a common pricing spine: amortized installment **loans**, where a borrower buys the vehicle outright over a fixed term, and **leases**, where a lessee pays for the vehicle's depreciation and at maturity decides whether to walk away, buy the car, or sign a fresh contract.

Pricing in this domain is unforgiving, and it is the system's primary responsibility. A borrower's creditworthiness places them into one of four FICO tiers, and the tier the system reads off the active rate card determines the interest rate that shapes every subsequent number — the monthly payment, the scheduled principal balance after each payment, and the binding actuarial payoff a borrower must tender to settle early. Leases carry their own arithmetic: a depreciation fee, a finance fee derived from a money factor, sales tax, mileage-overage penalties assessed year by year, disposition and purchase-option fees, and a residual value that becomes the buyout price. Because money is involved and contracts can be serviced concurrently, the platform also doubles as a compliance and audit surface: an auditor can read everything but change nothing, every monetary figure is carried in integer cents, and the riskiest write paths are guarded against acting on stale data.

The remainder of this document defines the global contract every endpoint honors (Section 2), the business logic and lifecycles of loans and leases (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contract, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers that establish the acting identity: `X-User-ID`, which names the user, and `X-User-Role`, which declares the operational capacity in which they are acting. A request missing either header, or carrying an `X-User-Role` that is not one of the three recognized roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `FinanceManager`, `Borrower`, and `Auditor`.

A `FinanceManager` is the dealer's finance operator. They manage rate cards, vehicles, and customers, originate loans and leases, and service delinquency by marking missed payments, declaring defaults, and maturing leases. When `X-User-Role` is `FinanceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`.

A `Borrower` is the customer on the other side of a contract — the person who makes payments, pays a loan off early, and elects how a lease ends. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any loan, lease, payment, or lease-end settlement compare the contract's `customer_id` to `X-User-ID`. A `Borrower` may only act on contracts they own, and an attempt to act on someone else's contract is rejected with `ERR_FORBIDDEN`.

An `Auditor` is a read-only compliance reviewer. They may read every resource in the system but hold no write power. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque reviewer identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items skipped before the page begins; when omitted it defaults to 0.

Unless a specific endpoint says otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full matching set and `has_more` indicates whether further pages remain beyond the returned slice.

### 2.4. Common Resource Properties and Versioning

Most resources in the system — `Customer`, `Vehicle`, `RateCard`, `Loan`, `Lease`, and `LeaseEndSettlement` — carry a standard set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp, ISO 8601 UTC with three fractional digits, fixed at creation; an `updated_at` timestamp in the same format, refreshed on every mutation; and a `version`, an integer that starts at the resource's first persisted value and increments by one on every mutation.

The `Payment` entity is the sole exception. A payment is an append-only event record rather than a mutable resource, so it carries only `id` and `created_at`; it has no `updated_at` and no `version`, and the API never modifies a payment after it is written.

Whenever a derived figure on a parent resource changes as a side effect of some operation — for example the recomputation of a loan's `principal_balance_cents` after a payment posts — that change is itself a mutation of the parent: it refreshes the parent's `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval

Several read endpoints address a resource through a parent identifier, such as listing a customer's loans or a lease's settlements. For any such path, the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource. The same ordered-existence discipline governs write operations whose body references other resources: referenced customers, vehicles, rate cards, loans, and leases are checked for existence (in that left-to-right order) before any business rule is evaluated, and a missing reference yields `ERR_NOT_FOUND`.

### 2.6. Monetary Precision and Rounding

Every monetary quantity in the system is represented and stored as an integer number of cents; there are no fractional-cent values in stored fields or response bodies. Where a calculation produces a non-integer intermediate, the result is rounded to a whole number of cents using the round-half-up convention (a value exactly at the half-cent rounds up). Each calculation in Section 3 states precisely where rounding is applied and in what order, because for several of these computations the order of rounding changes the result. Rate-like configuration inputs — annual percentage rates, the money factor, the tax rate, and the per-mile overage rate — are carried at their supplied precision and are not themselves rounded to cents.

### 2.7. Optimistic Concurrency Control on Supersede-Style Writes

Two write paths in the system can be invalidated by an intervening change and therefore require the client to declare the parent version it last observed. These are the only two operations that take a version field; no other endpoint accepts one.

The early-payoff of a loan requires an `expected_loan_version` field carrying the `version` of the target `Loan` that the client last read. If that value does not equal the loan's current `version` — for instance because a scheduled payment posted between the client's read and the payoff request, advancing the version and changing the actuarial payoff quote — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the borrower cannot tender against a balance they have not observed.

Creating a lease-end settlement requires an `expected_lease_version` field carrying the `version` of the target `Lease` that the client last read. If that value does not equal the lease's current `version` — for instance because a prior election already moved the lease out of `MATURING` and advanced its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so a superseded election cannot be applied on a stale view of the lease.

### 2.8. Validation Order

When several conditions could each reject a single request, the system evaluates them in a fixed priority so that the returned error is deterministic. Authentication is checked first: a missing or unknown role context yields `ERR_UNAUTHENTICATED`. Authorization follows: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`, and this is also where a `Borrower` acting on a contract they do not own is rejected with `ERR_FORBIDDEN`. Existence of all referenced resources is checked next, yielding `ERR_NOT_FOUND`. Then request well-formedness is checked — required body fields present and correctly typed, enum members valid, `fico_score` within the range 300 to 850 inclusive, integer-cent fields non-negative, `term_months` a strictly positive integer (a `term_months` of 0 or less is rejected), and the `per_mile_overage_rate_cents` rate input a non-negative number — yielding `ERR_INVALID_REQUEST`. Only after these gates pass does the system evaluate the operation-specific business rules described in Section 3 (uniqueness, active-rate-card presence, vehicle availability, state legality, version freshness, default threshold, payment-amount agreement, and mileage-schedule validity), each in the order the relevant workflow narrative establishes. In particular, for the operations that carry a version field, the freshness check is evaluated as a business rule after existence and well-formedness, alongside the state-legality check for that same operation.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Customers, Vehicles, and Rate Cards

Before any financing can be written, the finance desk populates three independent reference catalogues.

A **customer** is registered by a `FinanceManager` with a `full_name`, a contact `email`, and a raw `fico_score`. The email must be unique across all customers; a registration whose email is already in use is rejected with `ERR_DUPLICATE_RESOURCE`. The `fico_score` is the borrower's raw credit score and must fall between 300 and 850 inclusive. Beyond the stored score, each customer exposes a computed `fico_tier`, one of `TIER_1`, `TIER_2`, `TIER_3`, or `TIER_4`. The tier is not a fixed attribute; it is derived from the customer's `fico_score` against the breakpoints on the active rate card, and it is resolved at the moment it is needed — both when a customer is read and when a loan against that customer is originated. The tier is resolved against whichever rate card is active at read time (not the card pinned to any of the customer's contracts); if no rate card is active when a customer is read, the exposed `fico_tier` is null.

The tier assignment works as a descending ladder of inclusive lower bounds. If the score is greater than or equal to the active card's `tier_1_min_fico`, the tier is `TIER_1`. Otherwise, if the score is greater than or equal to `tier_2_min_fico`, the tier is `TIER_2`. Otherwise, if the score is greater than or equal to `tier_3_min_fico`, the tier is `TIER_3`. A score below `tier_3_min_fico` falls into `TIER_4`. The three breakpoints descend — `tier_2_min_fico` sits below `tier_1_min_fico`, and `tier_3_min_fico` below `tier_2_min_fico` — and each comparison is a true "at least" test, never a strict "greater than".

A **vehicle** is added to the fleet by a `FinanceManager` with a `vin`, a display `make_model`, a manufacturer suggested retail price `msrp_cents`, a negotiated `sale_price_cents`, and a contractual `residual_value_cents` that becomes the lease-end buyout figure. The `vin` must be unique across all vehicles; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`. A vehicle's `status` is system-managed and begins at `AVAILABLE`; it moves to `FINANCED` once a loan or lease is originated against it.

A **rate card** is the pricing sheet. A `FinanceManager` creates one with a `name` label and the full set of pricing inputs: the three tier breakpoints `tier_1_min_fico`, `tier_2_min_fico`, and `tier_3_min_fico`; the four annual loan rates `tier_1_apr`, `tier_2_apr`, `tier_3_apr`, and `tier_4_apr`, each a decimal such as 0.0399; the monthly `lease_money_factor`; the penalty `default_rate_apr` applied to delinquent balances; and the `lease_tax_rate` applied to the lease base. A newly created card has its `active` flag set to false. Exactly one card is active at any time: when a `FinanceManager` activates a card, that card's `active` becomes true and the previously active card, if any, has its `active` set back to false as a cascading side effect of the same operation. Activating a card that is already active is a no-op on that card: its `active` stays true and neither its `updated_at` nor its `version` is advanced (only cards whose `active` actually changes are touched). The active card is the one pinned to new originations, and origination is blocked unless one exists (see §3.2).

### 3.2. Originating a Loan

A `FinanceManager` originates a loan by supplying the `customer_id` of the borrower, the `vehicle_id` of the financed vehicle, the cash `down_payment_cents`, the `term_months` of the contract, and an optional `gap_insurance` flag indicating whether Guaranteed Asset Protection coverage is purchased; when the flag is omitted it defaults to false.

Origination requires an active rate card to exist; if none is active the request is rejected with `ERR_NO_ACTIVE_RATE_CARD`. The targeted vehicle must currently be `AVAILABLE` — a vehicle already financed cannot be financed again, and an attempt to do so is rejected with `ERR_VEHICLE_UNAVAILABLE`. On success the system pins the active card onto the new loan as `rate_card_id`, and the loan records that pinning permanently so that later servicing uses the originally agreed pricing.

Several figures are computed and frozen at origination. The `financed_principal_cents` is the vehicle's `sale_price_cents` minus the loan's `down_payment_cents`. The loan's `apr` is selected from the pinned rate card according to the customer's `fico_tier` at origination — `tier_1_apr` for `TIER_1`, `tier_2_apr` for `TIER_2`, `tier_3_apr` for `TIER_3`, and `tier_4_apr` for `TIER_4`. The `monthly_payment_cents` is the standard amortized level payment: letting the financed principal be the present value, the monthly rate be the loan's `apr` divided by 12, and the number of periods be `term_months`, the payment equals the present value multiplied by the quantity (monthly rate times (one plus the monthly rate) raised to the number of periods), divided by ((one plus the monthly rate) raised to the number of periods, minus one). This single resulting payment is rounded half-up to whole cents — the rounding is applied only to the final payment figure.

At origination the loan's `principal_balance_cents` is initialized to its `financed_principal_cents`, its `payments_made_count` starts at 0, its `missed_payment_count` starts at 0, and its `status` is `CURRENT`. As the closing side effect, the associated vehicle's `status` is set to `FINANCED`.

### 3.3. Servicing a Loan: Payments, the Delinquency Cycle, and Balances

A loan lives in one of four states. `CURRENT` is the initial, healthy state; `DELINQUENT` is the state a loan enters when a payment is missed; and `DEFAULT` and `PAID_OFF` are terminal. The healthy and delinquent states form a cure cycle that a loan can traverse repeatedly before it ever reaches a terminal state.

**Recording a scheduled payment.** A `Borrower` records a payment against their own loan by submitting an `amount_cents` and a `kind`, where `kind` is one of `SCHEDULED`, `LATE_FEE`, or `PAYOFF`; a `kind` outside that set is rejected with `ERR_INVALID_REQUEST`. The supplied `kind` is validated for membership but otherwise not branched on — this endpoint always processes the remittance as a scheduled payment, and the written `Payment` always records `kind` `SCHEDULED` regardless of the value submitted. The payment that is written records the targeted loan through its `loan_id`, and its `amount_cents` is the submitted amount. A scheduled payment is the ordinary monthly remittance. It is permitted only when the loan is `CURRENT` or `DELINQUENT`; attempting it on a loan in any other state is rejected with `ERR_LOAN_NOT_PAYABLE`. The submitted `amount_cents` must equal the loan's `monthly_payment_cents` exactly, or the payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A scheduled payment is also refused once the loan is fully amortized: if `payments_made_count` has already reached `term_months`, the payment is rejected with `ERR_LOAN_TERM_COMPLETE`.

When a scheduled payment posts against a `CURRENT` loan, the system writes a `Payment` whose `status` is `POSTED`, whose `kind` is `SCHEDULED`, and whose `late_fee_cents` is 0; it then increments `payments_made_count` by one and recomputes `principal_balance_cents` on the actuarial schedule. The loan remains `CURRENT`.

When the same kind of scheduled payment posts against a `DELINQUENT` loan, it acts as a **cure**: the loan returns to `CURRENT`, `missed_payment_count` is reset to 0, `payments_made_count` increments by one, and `principal_balance_cents` is recomputed. A curing payment also assesses a late fee, recorded as `late_fee_cents` on the written `Payment`. The late fee is the larger of a fixed floor of 2500 cents and five percent of the monthly payment rounded half-up to whole cents (that is, the loan's `monthly_payment_cents` multiplied by 0.05, rounded half-up). At a tie — where the percentage figure equals the 2500-cent floor exactly — the floor applies; the percentage never displaces a result already at the floor.

**The actuarial balance.** The `principal_balance_cents` is the scheduled remaining principal after the posted scheduled payments, computed chronologically from origination. Begin with the balance equal to `financed_principal_cents`. For each of the `payments_made_count` posted scheduled payments, in order: compute that period's interest as the running balance multiplied by the monthly rate (the loan's `apr` divided by 12), rounded half-up to whole cents; subtract that rounded interest from the loan's `monthly_payment_cents` to obtain the period's principal portion; and reduce the running balance by that principal portion. After all such periods are applied, the running balance is rounded half-up to whole cents to yield `principal_balance_cents`. Interest is rounded each period before the subtraction — the rounding happens per period, not once at the end.

**Missing a payment.** A `FinanceManager` marks a scheduled payment as missed. From `CURRENT` this moves the loan to `DELINQUENT`; from `DELINQUENT` it leaves the loan `DELINQUENT`. Either way the system writes a `Payment` whose `status` is `MISSED`, whose `kind` is `SCHEDULED`, whose `late_fee_cents` is 0, and whose `amount_cents` is 0, and increments `missed_payment_count` by one. The missed-payment request takes no body, and a missed payment does not advance `payments_made_count` or recompute `principal_balance_cents`. Marking a payment missed is permitted only when the loan is `CURRENT` or `DELINQUENT`; from any other state, or once a delinquent loan has already accumulated enough missed payments to be eligible for default, the request is rejected with `ERR_LOAN_NOT_PAYABLE`. Concretely, a further miss on an already-delinquent loan is allowed only while `missed_payment_count` is below the default threshold of 3.

**Declaring default.** Once a delinquent loan's `missed_payment_count` reaches at least 3, a `FinanceManager` may declare default, supplying the `insurance_settlement_cents` recovered on the repossessed vehicle. Default may be declared only from `DELINQUENT`; from any other state the request is rejected with `ERR_LOAN_NOT_PAYABLE`. If the loan is delinquent but `missed_payment_count` is still below 3, the declaration is rejected with `ERR_DEFAULT_THRESHOLD_NOT_MET`. On default the loan moves to the terminal `DEFAULT` state and the associated vehicle's `status` is set back to `AVAILABLE`, modeling repossession. The loan's `principal_balance_cents` is left unchanged at default (it is not zeroed), and the gap-insurance settlement below is a narrative invariant only — the gap payout and net post-default balance are not persisted as fields on the loan or returned in the response.

Default also settles the gap-insurance position. The raw deficiency is the larger of zero and the loan's `principal_balance_cents` minus the `insurance_settlement_cents`. When the loan was originated with `gap_insurance` true, Gap coverage pays out exactly that deficiency, so the gap payout equals the deficiency and the borrower's net post-default balance — the principal balance, less the insurance settlement, less the gap payout — is conserved at zero. When `gap_insurance` is false there is no gap payout, and the borrower's net post-default balance equals the deficiency itself.

### 3.4. Closing a Loan Early: The Payoff Quote and Payoff

At any point while a loan is `CURRENT`, the system can produce a payoff quote — a read that returns two figures plus the current loan version. The **actuarial** payoff, exposed as `actuarial_payoff_cents`, is the binding amount the borrower must tender; it equals the actuarial `principal_balance_cents` computed after the `payments_made_count` payments already made, and it excludes future, as-yet-unearned interest. The **gross** payoff, exposed as `gross_payoff_cents`, is an informational naive view: the loan's `monthly_payment_cents` multiplied by the number of remaining periods, where the remaining periods are `term_months` minus `payments_made_count`; because it bundles future interest, it is the larger figure. The difference between them — gross minus actuarial — is the unearned-interest rebate, returned as `unearned_interest_cents`. The quote read also returns the loan's current `loan_version` so a client can pin it for the payoff that follows.

A `Borrower` pays off their own loan by submitting the binding `amount_cents` together with the `expected_loan_version` described in §2.7. Payoff is permitted only while the loan is `CURRENT`; otherwise the request is rejected with `ERR_LOAN_NOT_PAYABLE`. The version must match the loan's current `version` or the request is rejected with `ERR_STALE_VERSION`. The tendered `amount_cents` must equal the actuarial payoff quote exactly, or the request is rejected with `ERR_PAYOFF_AMOUNT_MISMATCH`. On success the system writes a `Payment` whose `status` is `POSTED`, whose `kind` is `PAYOFF`, and whose `late_fee_cents` is 0; it sets the loan's `principal_balance_cents` to 0, moves the loan to the terminal `PAID_OFF` state, sets the associated vehicle's `status` to `AVAILABLE`, and increments the loan's `version` by one.

### 3.5. Originating a Lease and Computing Its Monthly Payment

A `FinanceManager` originates a lease by supplying the lessee's `customer_id`, the `vehicle_id`, the capitalized-cost-reduction `down_payment_cents`, the `term_months`, the `annual_mileage_allowance` (permitted miles per lease-year), the `per_mile_overage_rate_cents` charged for each mile beyond the allowance, the flat `disposition_fee_cents` charged when the lease is returned, the flat `purchase_option_fee_cents` charged when the lessee buys the car, and an optional `gap_insurance` flag that defaults to false.

As with loans, lease origination requires an active rate card or it is rejected with `ERR_NO_ACTIVE_RATE_CARD`, and it requires the vehicle to be `AVAILABLE` or it is rejected with `ERR_VEHICLE_UNAVAILABLE`. On success the active card is pinned as the lease's `rate_card_id`, the lease's `status` is set to `ACTIVE`, and the associated vehicle's `status` is set to `FINANCED`.

The lease's monthly payment is computed and frozen at origination, and the order of operations is significant. First the `adjusted_cap_cost_cents` is the vehicle's `sale_price_cents` minus the lease's `down_payment_cents`. From the unrounded real values, the depreciation fee is the adjusted cap cost minus the vehicle's `residual_value_cents`, divided by `term_months`; the finance fee is the adjusted cap cost plus the residual value, multiplied by the rate card's `lease_money_factor`. The pre-tax monthly figure `base_monthly_cents` is the sum of the depreciation fee and the finance fee, rounded half-up to whole cents. The monthly tax is that same unrounded sum of the depreciation fee and finance fee, multiplied by the rate card's `lease_tax_rate`, rounded half-up to whole cents. The lease's `monthly_payment_cents` is then `base_monthly_cents` plus that rounded tax. The base and the tax are each rounded independently from the identical unrounded pre-tax sum and only then added; the tax is computed on the unrounded sum, not on the already-rounded base.

A lease also carries an `odometer_miles` reading that is system-managed and starts at 0; it is populated from the lease-end settlement at maturity (see §3.6).

### 3.6. Ending a Lease: Maturity, Election, and Settlement

A lease moves through `ACTIVE`, then `MATURING`, then exactly one of three fork outcomes — `RETURNED`, `PURCHASED`, or `RENEWED` — each of which immediately joins to the terminal `SETTLED` state once its settlement is finalized.

**Maturing.** A `FinanceManager` matures a lease, advancing it from `ACTIVE` to `MATURING` and making it eligible for a lease-end election. Maturing is permitted only from `ACTIVE`; an attempt on a lease not in `ACTIVE` is rejected with `ERR_LEASE_NOT_MATURABLE`.

**Electing.** The lessee, acting as the `Borrower` who owns the lease, ends it by creating a lease-end settlement. The election body carries the `lease_id`, the chosen `election` (one of `RETURN`, `PURCHASE`, or `RENEW`), the final `odometer_miles` reading, and the `expected_lease_version` for the freshness check of §2.7. Depending on the election, it also carries `per_year_excess_miles` — a list of per-lease-year excess-mile counts whose length must equal `term_months` divided by 12 — and `renew_term_months`, the term for a renewed lease. An election may be made only while the lease is `MATURING`; attempting it on a lease in any other state is rejected with `ERR_LEASE_NOT_ELECTABLE`. If `expected_lease_version` does not match the lease's current `version`, the election is rejected with `ERR_STALE_VERSION`. A settlement is created with its `status` set to `FINALIZED`; settlements are computed and finalized atomically at creation, and creating one increments the lease's `version` by one. The settlement record echoes back the request's `election` and `odometer_miles`, and carries `per_year_excess_miles` and `renew_term_months` exactly as supplied in the body — each is null when the body omitted it (for example `per_year_excess_miles` is null on a `PURCHASE` or `RENEW`, and `renew_term_months` is null on a `RETURN` or `PURCHASE`). Each finalized settlement drives its lease through its fork outcome and on to the terminal `SETTLED` state; the lease's observable `status` after a finalized settlement is `SETTLED` (the intermediate `RETURNED`/`PURCHASED`/`RENEWED` outcome is a transition the lease passes through in the same operation and is not separately observable).

The three branches diverge in their required inputs, their computed charges, and their cascades, and they are specified with equal weight below.

*Return.* A `RETURN` election requires `per_year_excess_miles` to be present and of length exactly `term_months` divided by 12; a missing or wrong-length list is rejected with `ERR_MILEAGE_SCHEDULE_INVALID`. On a return, the settlement's `mileage_overage_cents` is the per-year mileage overage: for each lease-year, multiply that year's excess-mile count from `per_year_excess_miles` by the lease's `per_mile_overage_rate_cents` and round that year's charge half-up to whole cents, then sum the rounded yearly charges. The rounding is applied to each lease-year's charge before summing — rounding per year and then summing, not summing the miles and rounding once, because the two differ at the half-cent boundary. The settlement's `disposition_charge_cents` is set to the lease's `disposition_fee_cents`. The settlement's `total_due_cents` is the disposition fee plus the mileage overage. On a return the lease's `odometer_miles` is set from the settlement's `odometer_miles`, the lease advances `RETURNED` then to `SETTLED`, and the associated vehicle's `status` is set to `AVAILABLE`. On a return the settlement's `purchase_amount_cents` is 0 and its `renewed_lease_id` is null.

*Purchase.* A `PURCHASE` election needs no mileage schedule and no renewal term. On a purchase, the settlement's `purchase_amount_cents` is the vehicle's `residual_value_cents` plus the lease's `purchase_option_fee_cents`, and the settlement's `total_due_cents` equals that same purchase amount — no disposition fee and no mileage overage are charged on a purchase, so `mileage_overage_cents` and `disposition_charge_cents` are 0 and `renewed_lease_id` is null. The lease advances `PURCHASED` then to `SETTLED`. Because title transfers to the lessee and the car leaves the fleet, the associated vehicle's `status` stays `FINANCED` rather than returning to `AVAILABLE`.

*Renew.* A `RENEW` election requires `renew_term_months` to be present and greater than 0; an absent or non-positive renewal term is rejected with `ERR_RENEW_TERM_INVALID`. On a renewal, the settlement's `total_due_cents` is 0 — the outstanding obligation rolls into a fresh contract — and its `mileage_overage_cents`, `disposition_charge_cents`, and `purchase_amount_cents` are all 0. As the cascade, the system mints a new `Lease` in `ACTIVE` status on the same vehicle, with its capitalized cost set to the vehicle's `residual_value_cents` and its term set to `renew_term_months`; the new lease's `id` is recorded on the settlement as `renewed_lease_id`. The new lease carries the same `customer_id`, `vehicle_id`, `rate_card_id`, `annual_mileage_allowance`, `per_mile_overage_rate_cents`, `disposition_fee_cents`, `purchase_option_fee_cents`, and `gap_insurance` as the maturing lease; its `down_payment_cents` is 0 and its `odometer_miles` is 0. Its monthly payment is frozen by the §3.5 formula evaluated with the capitalized cost: the adjusted cap cost is taken as the vehicle's `residual_value_cents` (sale price equal to residual, down payment 0), the residual value is also the vehicle's `residual_value_cents`, and the term is `renew_term_months`, so `adjusted_cap_cost_cents` equals the residual value. The maturing lease advances `RENEWED` then to `SETTLED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource — including activating a rate card, marking a payment missed, declaring default, paying off, maturing a lease, and similar state changes — return a `200 OK` status code, except where noted below; recording a payment, missing a payment, and creating a lease-end settlement each create a new resource and therefore return `201 Created`. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a borrower | FinanceManager |
| GET | `/customers/{id}` | Fetch a customer | FinanceManager, Borrower, Auditor |
| GET | `/customers` | List customers (paginated) | FinanceManager, Auditor |
| GET | `/customers/{id}/loans` | List a customer's loans | FinanceManager, Borrower, Auditor |
| GET | `/customers/{id}/leases` | List a customer's leases | FinanceManager, Borrower, Auditor |
| POST | `/vehicles` | Add a vehicle to the fleet | FinanceManager |
| GET | `/vehicles/{id}` | Fetch a vehicle | FinanceManager, Borrower, Auditor |
| GET | `/vehicles` | List vehicles (paginated; filter by status) | FinanceManager, Auditor |
| POST | `/rate-cards` | Create a rate card | FinanceManager |
| POST | `/rate-cards/{id}/activate` | Make this the active rate card | FinanceManager |
| GET | `/rate-cards/{id}` | Fetch a rate card | FinanceManager, Auditor |
| GET | `/rate-cards` | List rate cards (paginated; filter by active) | FinanceManager, Auditor |
| POST | `/loans` | Originate an auto loan | FinanceManager |
| GET | `/loans` | List loans (paginated; filter by customer_id, vehicle_id, rate_card_id) | FinanceManager, Auditor |
| GET | `/loans/{id}` | Fetch a loan with computed balances | FinanceManager, Borrower, Auditor |
| GET | `/loans/{id}/payoff-quote` | Actuarial and gross payoff quotes for the loan | FinanceManager, Borrower, Auditor |
| GET | `/loans/{id}/payments` | List payments for a loan | FinanceManager, Borrower, Auditor |
| POST | `/loans/{id}/payments` | Record a scheduled payment (also cures a delinquent loan) | Borrower |
| POST | `/loans/{id}/miss-payment` | Mark a scheduled payment missed | FinanceManager |
| POST | `/loans/{id}/default` | Declare default on a delinquent loan | FinanceManager |
| POST | `/loans/{id}/payoff` | Early-payoff a current loan (OCC-guarded) | Borrower |
| POST | `/leases` | Originate a lease | FinanceManager |
| GET | `/leases` | List leases (paginated; filter by customer_id, vehicle_id, rate_card_id) | FinanceManager, Auditor |
| GET | `/leases/{id}` | Fetch a lease | FinanceManager, Borrower, Auditor |
| POST | `/leases/{id}/mature` | Move an active lease to MATURING | FinanceManager |
| GET | `/leases/{id}/settlements` | List settlements for a lease | FinanceManager, Borrower, Auditor |
| POST | `/lease-end-settlements` | Elect lease end (RETURN/PURCHASE/RENEW); computes and finalizes the settlement (OCC-guarded) | Borrower |
| GET | `/lease-end-settlements/{id}` | Fetch a finalized settlement | FinanceManager, Borrower, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_NO_ACTIVE_RATE_CARD` | 409 Conflict |
| `ERR_VEHICLE_UNAVAILABLE` | 409 Conflict |
| `ERR_LOAN_NOT_PAYABLE` | 409 Conflict |
| `ERR_LOAN_TERM_COMPLETE` | 409 Conflict |
| `ERR_LEASE_NOT_MATURABLE` | 409 Conflict |
| `ERR_LEASE_NOT_ELECTABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DEFAULT_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_PAYOFF_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_MILEAGE_SCHEDULE_INVALID` | 422 Unprocessable Entity |
| `ERR_RENEW_TERM_INVALID` | 422 Unprocessable Entity |

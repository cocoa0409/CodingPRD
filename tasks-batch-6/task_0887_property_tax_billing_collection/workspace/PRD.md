# Property Tax Billing & Collection API — Product Requirements Document

## 1. Introduction

This document specifies the Property-Tax Billing & Collection service operated on behalf of a county treasurer. The system is the system of record for the annual property-tax cycle: certifying a levy year and its millage, issuing bills against assessed parcels, splitting each bill into installments, posting payments (including partial payments and mortgage-escrow files), materializing delinquency penalties and interest as time passes, referring persistently delinquent bills to tax sale, and processing refunds, overpayments, exemptions, and abatements.

The domain is fundamentally a money-movement ledger sitting under a compliance workflow. Every cent that flows through a bill is recorded as an append-only ledger event, and the balances a caller reads on a bill or installment are always derived from that ledger rather than stored independently. Because the same bill can be simultaneously in one collection posture (current, partially paid, paid, or delinquent) and one sale posture (not in sale, in sale, redeemed, or sold), the design tracks these as two independent axes on a single bill. Segregation of duties runs throughout: the clerk who takes money is not the officer who reverses it, the person who files a refund cannot approve their own refund, and the officer who opens a tax-sale referral cannot be the one who executes the sale.

Time in this system is driven by an explicit logical clock rather than wall-clock time, so that delinquency, interest accrual, and redemption windows are fully reproducible. Advancing the clock is itself a business event that can move installments into delinquency and post the corresponding charges.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. All resource collections are mounted under the `/property-tax` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If `X-User-Role` is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is recognized but not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles: `Treasurer`, `Cashier`, `CollectionsOfficer`, `ReliefOfficer`, and `Taxpayer`.

Four of these roles carry an opaque identity. When `X-User-Role` is `Treasurer`, `Cashier`, `CollectionsOfficer`, or `ReliefOfficer`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow requires it — for example as `posted_by_user_id` on a payment, `reversed_by_user_id` on a reversal, `decided_by_user_id` on a relief application or refund, `created_by_user_id` on a referral, or `sold_by_user_id` on a sale — but never compares it to an entity `id`, except for the segregation-of-duties equalities described in §2.9.

The `Taxpayer` role is entity-backed by `Parcel`. When `X-User-Role` is `Taxpayer`, the `X-User-ID` is the `id` of the acting parcel; ownership checks on any resource that references a parcel compare that resource's parcel foreign key to `X-User-ID`. A taxpayer may submit and resubmit relief applications for their own parcel, pay their own bill online, file a refund on their own overpaid bill, and read their own records.

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

List endpoints are paginated through the `limit` and `offset` query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Append-Only Ledger

Most resources carry a common set of system-managed fields. Each such resource has an `id` that is a server-minted UUID (a plain UUID with no type prefix), a `created_at` ISO 8601 UTC timestamp with three fractional digits recording when it was created, an `updated_at` timestamp of the same format recording the last modification, and an integer `version` that begins at 1 and increments by one on every mutation of that resource. Recomputed and derived fields — such as a bill's balances or an installment's status — are mutations: when they change as a side effect of another operation, the owning resource's `updated_at` is refreshed and its `version` incremented, subject to the specific version-bump rules stated in §3 for `TaxBill`.

`LedgerEntry` is the sole exception. A ledger entry is an immutable, append-only event and carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version`, and it is never modified or deleted once written. All monetary truth about a bill is reconstructed by reading its ledger. Every ledger entry records the `bill_id` it posts against, an optional `installment_sequence` (1 or 2 when the entry targets a specific installment, and null for bill-level entries such as an `ABATEMENT` or a `REFUND`), an `entry_type`, a signed `amount_cents`, and a human-readable `memo` describing the entry's origin (for example, "penalty 5% installment 2"). The `entry_type` is one of `CHARGE`, `PENALTY`, `INTEREST`, `PAYMENT`, `REVERSAL`, `ABATEMENT`, or `REFUND`. Sign convention is fixed: `CHARGE`, `PENALTY`, and `INTEREST` entries are positive; `PAYMENT` and `ABATEMENT` entries are negative; `REVERSAL` and `REFUND` entries are positive.

### 2.5. Monetary Precision and Rounding

Every monetary quantity in this system is an integer number of whole cents; there are no fractional-cent values in stored fields, ledger amounts, or API responses. Wherever a computation produces a non-integer cent value, the result is rounded half-up to the nearest whole cent unless a rule explicitly pins a different rounding. Two computations pin their rounding deliberately and must not be replaced by a generic sum-then-round: the levy divides by one thousand and rounds half-up at that divide step, and the installment split uses integer floor division per installment with the odd remaining cent assigned to the last installment (see §3.2). The tax year's `millage_rate` is a rate input and is not itself a cent value; it is used only as a multiplier in the levy.

### 2.6. Validation Ordering and Error Semantics

When a request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failure determines the returned error. The global order is:

1. **Authentication.** The `X-User-Role` header must be present and a recognized role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The role must be permitted for the operation per §4, else `ERR_FORBIDDEN` (403).
3. **Existence.** Every resource id referenced in the path or body — `bill_id`, `parcel_id`, `tax_year_id`, `escrow_agent_id`, and any referral, refund, or application id — must resolve to a live resource. Ids are validated left to right, and the first unresolved id yields `ERR_NOT_FOUND` (404).
4. **Segregation of duties.** On the two four-eyes operations (deciding a refund and executing a sale), the acting `X-User-ID` must differ from the recorded originator, else `ERR_SEGREGATION_OF_DUTIES` (403); see §2.9.
5. **Field validation.** On any create or action carrying a body, required fields must be present and well-typed, and enum-valued fields must be recognized. A missing or mistyped field, or a violated amount or date constraint, yields `ERR_VALIDATION` (400). A tendered or requested amount that is not strictly greater than zero yields `ERR_ZERO_AMOUNT` (422). A payment whose `source` is `ESCROW` but which omits `escrow_agent_id` yields `ERR_ESCROW_AGENT_REQUIRED` (422). An enum field whose value lies outside its declared domain yields `ERR_INVALID_ENUM` (422).
6. **State legality.** The target resource must be in a legal state for the requested transition, else `ERR_INVALID_STATE` (409); the terminal-state variants `ERR_PAYMENT_ALREADY_REVERSED`, `ERR_BILL_ALREADY_PAID`, `ERR_RELIEF_ALREADY_DECIDED`, and `ERR_REFUND_ALREADY_DECIDED` are raised in place of the generic code where §3 specifies them.
7. **Optimistic concurrency.** Where an `expected_bill_version` is required, it must equal the bill's current `version`, else `ERR_STALE_VERSION` (412); see §2.7.
8. **Uniqueness and remaining business rules.** Duplicate-bill, relief-overlap, referral-overlap, delinquency, threshold, redemption-window, and overpayment checks then apply as described in the relevant §3 workflow.

Each workflow in §3 restates the order that is specific to it where the specific order matters (for example, that a referral checks delinquency posture before the threshold, and that a refund approval checks segregation of duties before overpayment availability).

### 2.7. Optimistic Concurrency Control on Bills

Two create operations act on the strength of a figure the client last read from a `TaxBill`, and both guard against acting on a stale reading by requiring the caller to echo the bill's `version`.

Filing a refund carries the overpayment the client last observed on the bill. A create-refund request must include `expected_bill_version` equal to the target bill's current `version`. If another payment or reversal has advanced the bill's `version` since the client last read it, the refund is rejected with `ERR_STALE_VERSION` (HTTP 412), so the refund is never computed from an outdated overpayment figure.

Opening a tax-sale referral snapshots the bill's delinquent principal. A create-referral request must likewise include `expected_bill_version` equal to the bill's current `version`. If the bill's `version` has advanced since the client read it — for instance because a payment reduced the delinquency below the referral threshold — the referral is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than referring a bill that may no longer be eligible.

No other endpoint takes a version field. Only the two create operations above participate in optimistic concurrency control.

### 2.8. The Logical Clock and Delinquency Materialization

The server keeps a single logical clock in UTC. At startup and before any clock call has been made, the clock reads exactly `2026-05-01T00:00:00Z`; the system must never fall back to wall-clock time. An administrative test-driving capability sets the clock to a supplied instant, provided as `to_iso8601`, and returns the new `current_utc`.

Advancing the clock is a business event. For each installment that is now past due — meaning the current clock calendar date is strictly after the installment's `due_date` while its balance remains positive — the installment moves from `PENDING` to `DELINQUENT`, the one-time penalty is posted, whole-month interest is posted for each newly crossed monthly anniversary, and the parent bill's collection posture bubbles up to `DELINQUENT`. The precise penalty and interest formulas are given in §3.5. Because balances are always derived from the ledger, reads of an installment or bill reflect delinquency charges materialized through the current clock.

### 2.9. Segregation of Duties (Four-Eyes Control)

Two decisions require that the acting user be a different person from the one who initiated the underlying request. When a refund is decided, the acting `X-User-ID` must differ from the refund's `requested_by_user_id`. When a tax sale is executed, the acting `X-User-ID` must differ from the referral's `created_by_user_id`. A violation of either equality is rejected with `ERR_SEGREGATION_OF_DUTIES` (403), and this check precedes the operation's own business checks (overpayment availability for a refund, redemption expiry for a sale).

### 2.10. Filtered Retrieval and Left-to-Right Path Validation

Although resources are peers linked by foreign keys rather than nested in URL paths, every foreign key is discoverable through a filtered-list or sub-resource read. Parcels may be filtered by `escrow_agent_id`; bills by `parcel_id` and `tax_year_id`; installments by `bill_id`; relief applications by `parcel_id` and `tax_year_id`; payments by `bill_id` and `escrow_agent_id`; refunds by `bill_id`; referrals by `bill_id`; and a bill's ledger is read as its own sub-resource collection. When a path carries a resource id, that id is resolved before any sub-resource work, and an unresolved id yields `ERR_NOT_FOUND`.

### 2.11. Ledger Conservation Invariants

Two invariants must hold at all times. First, ledger-balance conservation: a bill's `balance_cents` is exactly the sum of every one of its `LedgerEntry` amounts, with none excluded. Second, cash conservation: the cash the county actually retains on a bill, exposed as `total_applied_cents`, equals `total_paid_cents` minus the sum of `approved_amount_cents` across that bill's `APPROVED` refunds. Because every payment, reversal, penalty, interest charge, abatement, and refund is a ledger event, these invariants are preserved automatically when balances are recomputed from the ledger after each mutation.

## 3. Business Logic & Workflows

### 3.1. Foundations: Tax Years, Escrow Agents, and Parcels

The billing cycle rests on three reference entities. A `Treasurer` certifies a levy year by supplying its `year` (a whole number no earlier than 2000 and unique across all tax years), its `millage_rate` in mills per one thousand of assessed value, and the two installment due dates `first_installment_due_date` and `second_installment_due_date`, each an ISO 8601 UTC date at day granularity. The second due date must be strictly after the first; a request that violates this ordering is rejected as invalid.

A `Treasurer` also registers each mortgage servicer as an `EscrowAgent`, recording its legal `name` and a short `servicer_code` that is unique across all escrow agents. Escrow agents are the counterparties named on mortgage-company payment files.

A parcel is the taxable unit and may be created by either a `Cashier` or a `Treasurer`. A parcel records its assessor parcel number `parcel_number` (unique across all parcels), the `owner_name` of record, the `situs_address` street location, the certified `assessed_value_cents` as a whole non-negative cent value, and a `property_class` of `RESIDENTIAL`, `COMMERCIAL`, `AGRICULTURAL`, or `INDUSTRIAL`. The owner-occupied flag `homestead` is a boolean that defaults to false when omitted. A parcel may name an `escrow_agent_id` identifying the mortgage escrow servicer that pays on its behalf; this field is nullable and is left null for self-pay parcels. Attempting to reuse a `parcel_number`, `servicer_code`, or tax-year `year` that already exists is a uniqueness violation.

### 3.2. Issuing a Tax Bill: Levy, Exemptions, and the Installment Split

Only a `Treasurer` issues a bill, and issuance is driven entirely by the referenced `parcel_id` and `tax_year_id`; the caller supplies nothing else. At most one bill may exist for any given pairing of `parcel_id` and `tax_year_id`; a second issuance for the same pair is rejected with `ERR_DUPLICATE_BILL`.

Issuance computes the levy. The gross tax `gross_tax_cents` is the parcel's `assessed_value_cents` multiplied by the tax year's `millage_rate`, then divided by one thousand, with the result rounded half-up to a whole cent at that divide step. The exemption credit `exemption_credit_cents` is the sum of the `approved_credit_cents` of every relief application on the same parcel and tax year that is both classified `EXEMPTION` and in status `APPROVED`, capped so that net tax is never driven below zero. The net tax `net_tax_cents` is the greater of zero and `gross_tax_cents` minus `exemption_credit_cents`; it is the amount split into installments.

The bill is then divided into exactly two installments (`INSTALLMENT_COUNT` is two). The first installment's `principal_due_cents` is `net_tax_cents` divided by two using integer floor division, dropping any fractional cent. The second installment's `principal_due_cents` is `net_tax_cents` minus the first installment's principal, so the last installment absorbs the odd remaining cent when the net tax is odd. This per-installment floor with the remainder placed on the last installment is deliberate and must not be replaced by rounding the halves independently. Each installment also receives a `bill_id` linking it to the bill, a `sequence` of 1 or 2, and a `due_date` copied from the tax year — the first installment takes `first_installment_due_date` and the second takes `second_installment_due_date`. For each installment the system posts a `CHARGE` ledger entry equal to its principal, so the bill's opening balance equals the net tax. The freshly issued bill starts with `collection_status` of `CURRENT` and `sale_status` of `NONE`.

A bill exposes a family of derived figures, all reconstructed from its ledger: `gross_tax_cents`, `exemption_credit_cents`, and `net_tax_cents` from issuance; `abatement_credit_cents`, the absolute sum of `ABATEMENT` entries posted after issuance; `total_charged_cents`, the sum of all positive `CHARGE`, `PENALTY`, and `INTEREST` amounts; `total_paid_cents`, the absolute value of the `PAYMENT` amounts less the `REVERSAL` amounts; `total_applied_cents`, the cash retained per the conservation rule in §2.11; `balance_cents`, the signed sum of every ledger amount for the bill; `overpayment_cents`, the greater of zero and the negative of `balance_cents`; and `delinquent_principal_cents`, the sum of the unpaid `principal_due_cents` over installments whose `status` is `DELINQUENT`. An installment likewise exposes its `penalty_cents`, `interest_cents`, `paid_cents` (payments allocated to it net of reversals), and its own `balance_cents`, which is its `principal_due_cents` plus `penalty_cents` plus `interest_cents` minus `paid_cents`.

### 3.3. Relief Applications: Exemptions and Abatements

A property owner (`Taxpayer`) acting on their own parcel, or a `Cashier` on their behalf, submits a relief application naming the `parcel_id`, the `tax_year_id`, a `relief_class`, a `relief_type`, a `claimed_amount_cents` (which must be strictly greater than zero), and the closed effective period bounded by `effective_from` and `effective_to`, where `effective_to` must be on or after `effective_from`. The `relief_class` is either `EXEMPTION`, which reduces gross tax before issuance, or `ABATEMENT`, a post-issuance credit. The `relief_type` is one of `HOMESTEAD`, `SENIOR`, `HARDSHIP`, or `DISABLED_VETERAN`. A new application begins in `SUBMITTED` with an `info_request_count` of zero.

The review cycle is run by a `ReliefOfficer`. Moving an application to review advances it from `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW` the officer may request additional information, advancing it to `INFO_REQUESTED` and incrementing `info_request_count` by one. From `INFO_REQUESTED` the application returns to `UNDER_REVIEW` when it is resubmitted; resubmission is performed by the owning taxpayer (whose `X-User-ID` equals the application's `parcel_id`) or by a `Cashier`. This review/request-info/resubmit loop may repeat any number of times. Attempting review, request-info, resubmit, or decide on an application that has already reached the terminal `APPROVED` or `DENIED` state is rejected with `ERR_RELIEF_ALREADY_DECIDED`; attempting a transition from a state that is legal for the machine but wrong for the requested action (for example deciding an application still in `SUBMITTED`) is rejected with `ERR_INVALID_STATE`.

A decision is taken by a `ReliefOfficer` from `UNDER_REVIEW`, carrying a `decision` of either APPROVE or DENY. A denial simply records `decided_by_user_id` and applies no credit. An approval first checks that no other active or approved application on the same parcel has an effective interval overlapping this one — the two closed intervals `[effective_from, effective_to]` are treated as overlapping even when they merely touch at an endpoint — and a conflict is rejected with `ERR_RELIEF_PERIOD_OVERLAP`. For an `ABATEMENT`, approval additionally requires that the target bill's `collection_status` is not `PAID`; abating a fully paid bill is rejected with `ERR_INVALID_STATE`.

On approval the system computes `approved_credit_cents` as the lesser of `claimed_amount_cents` and an applicable ceiling that depends on the class. For an `EXEMPTION`, the ceiling is `gross_tax_cents`, and the approved credit reduces gross for the whole year so that both installments shrink through the installment split; a bill issued after the exemption is approved reflects it in `net_tax_cents`. For an `ABATEMENT`, the ceiling is the sum of the bill's unpaid installment balances, and the approved credit is distributed as `ABATEMENT` ledger entries across the unpaid installments in ascending `sequence` order, with already-paid installments receiving nothing; as each installment's balance is recomputed, an installment that reaches a zero balance becomes `PAID`. Because of this distribution, an identical `claimed_amount_cents` produces a different net effect as an abatement than as an exemption. Either way, the approval records `decided_by_user_id`.

### 3.4. Posting Payments: Waterfall Allocation and Overpayment

A `Cashier` posts payments at the counter or from mortgage-escrow files, and a `Taxpayer` may pay their own bill online. A payment names the `bill_id` being paid, an `amount_cents` strictly greater than zero, a `tender_type` of `CASH`, `CHECK`, `ACH`, or `CARD`, and a `source` of `COUNTER`, `ESCROW`, or `ONLINE`. When `source` is `ESCROW`, an `escrow_agent_id` identifying the paying servicer is required and its omission is rejected with `ERR_ESCROW_AGENT_REQUIRED`; for other sources the `escrow_agent_id` is null. A payment against a bill whose `collection_status` is already `PAID` is rejected with `ERR_BILL_ALREADY_PAID`. A zero or negative `amount_cents` is rejected with `ERR_ZERO_AMOUNT`. A new payment is recorded in status `POSTED` and stamps `posted_by_user_id` with the acting user; its `reversed_by_user_id` remains null while `POSTED`.

Allocation is a waterfall over the bill's installments. The installments are processed in order of `due_date` ascending, and where two share a due date, by `sequence` ascending (with `created_at` as a further tie-break, never the `id`). Starting from a running remainder equal to `amount_cents`, each installment is paid in a fixed within-installment order — first its outstanding `penalty_cents`, then its outstanding `interest_cents`, then its remaining principal — where each bucket receives the lesser of the running remainder and that bucket's outstanding amount, and the remainder is reduced accordingly. Any amount still remaining after every installment is satisfied becomes `overpayment_applied_cents` on the payment and is retained as the bill's overpayment (a credit). The system posts one or more negative `PAYMENT` ledger entries for the amounts allocated. The payment's `allocation` field returns the per-installment breakdown as an array of objects, each carrying the installment `sequence` and the `penalty_cents`, `interest_cents`, and `principal_cents` applied to it.

Posting a payment bubbles installment and bill statuses up from the ledger and increments the bill's `version` by one. An installment moves from `PENDING` to `PARTIALLY_PAID` when its allocated principal is positive but less than its `principal_due_cents`, and to `PAID` when its balance reaches zero; a `DELINQUENT` installment whose penalty, interest, and principal are all cleared becomes `PAID`, while one that is reduced without clearing becomes `PARTIALLY_PAID`. The bill's `collection_status` follows: a partial payment that leaves a positive balance yields `PARTIALLY_PAID`, and a payment that clears the balance to zero with all installments paid yields `PAID`. As a cascade, if a payment drives the bill's balance to zero while a `REFERRED` tax-sale referral is open, that referral is auto-redeemed and the bill's `sale_status` becomes `REDEEMED` (see §3.8).

### 3.5. Delinquency: Penalties, Interest, and Payoff Quotes

Delinquency is materialized when the logical clock advances past a due date (see §2.8). An installment is delinquent when the current clock calendar date is strictly after its `due_date` and its unpaid principal is still positive. On becoming delinquent, the installment is charged a one-time penalty and accruing interest.

The penalty is charged exactly once and equals the installment's `principal_due_cents` multiplied by the penalty rate `PENALTY_RATE` of five percent (0.05), rounded half-up to a whole cent, and posted as a `PENALTY` ledger entry. Interest accrues per whole month. The number of elapsed months is the count of monthly anniversaries of the `due_date` whose anniversary date falls on or before the current clock date; for a month that has no day matching the due date's day-of-month, the month's last day is used as the anniversary. The interest for the installment is its `principal_due_cents` multiplied by the monthly interest rate `INTEREST_RATE_MONTHLY` of one percent (0.01), rounded half-up to a whole cent, then multiplied by the number of elapsed months, and posted as `INTEREST` ledger entries. The combined delinquency charge on an installment — penalty plus interest — is capped at one hundred percent of its `principal_due_cents`: the effective total is the lesser of the principal and the sum of penalty and interest. These charges surface on the installment as `penalty_cents` and `interest_cents`.

A payoff quote is available as a read on a bill and is shaped by a `mode` query parameter together with an optional `as_of_date`. The response reports the `mode`, the `as_of_date` used, the `principal_balance_cents` (the sum of unpaid `principal_due_cents` across the bill's installments), the `penalty_cents` (the sum of the installments' materialized penalties), the `interest_cents` (the interest component described below), and the `payoff_total_cents`, which is the principal balance plus the penalty total plus the interest component. In the default `LEDGER_AS_OF` mode the supplied `as_of_date` is ignored and the interest component is the whole-month interest already materialized to the ledger through the current clock, matching the delinquency figures. In `PAYOFF_QUOTE` mode with a future `as_of_date`, the interest component is a forward per-diem projection rather than whole-month: it is the `principal_balance_cents` multiplied by the monthly rate of one percent, annualized by multiplying by twelve, divided by `DAYS_PER_YEAR` of 365 to yield a daily rate, then multiplied by the number of days from the due date to the `as_of_date`, and rounded half-up to a whole cent.

### 3.6. Reversing a Payment

Only a `Treasurer` may reverse a payment, and only a payment currently in `POSTED` status; reversing a payment that is already `REVERSED` is rejected with `ERR_PAYMENT_ALREADY_REVERSED`. Reversal is a compensating action: for each `PAYMENT` ledger entry the payment produced, the system posts an equal and opposite `REVERSAL` ledger entry, so the reversed cash is restored to the bill's balance. The reversal increments the bill's `version` by one, records `reversed_by_user_id`, and moves the payment to `REVERSED`.

Reopening a balance recomputes installment and bill statuses. A previously `PAID` bill whose balance becomes positive again returns to `PARTIALLY_PAID` when no installment is past due at the current clock, and to `DELINQUENT` when an installment is past due; in the latter case the penalty and interest for the reopened installment are re-materialized if they are not already present. Correspondingly, a `PAID` installment whose balance reopens returns to `PENDING` when the current clock date is on or before its `due_date`, and to `DELINQUENT` when the current clock date is after its `due_date`.

### 3.7. Refunds and Overpayment Recovery

When a bill carries overpayment, a refund may be filed by a `Taxpayer` on their own overpaid bill, or by a `Cashier` or `Treasurer`. The request names the `bill_id`, the requested `amount_cents` (strictly greater than zero), a `mode`, and the `expected_bill_version` required for the concurrency check in §2.7. The `mode` is either `GROSS_OVERPAYMENT`, which targets the bill's full overpayment, or `NET_OF_DELINQUENCY`, which targets the overpayment reduced by the parcel's other delinquent balances. A filed refund is recorded in status `REQUESTED`, stamps `requested_by_user_id` with the filer, and increments the bill's `version` by one.

A `Treasurer` decides a refund with a `decision` of APPROVE or DENY, but never their own request: the acting `X-User-ID` must differ from `requested_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` before any other decision check. Deciding a refund that has already reached `APPROVED` or `DENIED` is rejected with `ERR_REFUND_ALREADY_DECIDED`. On approval the system computes the available amount: under `GROSS_OVERPAYMENT` the available amount is the bill's `overpayment_cents`; under `NET_OF_DELINQUENCY` it is the greater of zero and `overpayment_cents` minus the sum of the `delinquent_principal_cents` on the parcel's other bills. The `approved_amount_cents` is the lesser of the requested `amount_cents` and that available amount, and it may not exceed the bill's available overpayment — an approval that would exceed it is rejected with `ERR_OVERPAYMENT_UNAVAILABLE`. Approval posts a positive `REFUND` ledger entry for `approved_amount_cents`, which reduces the remaining overpayment and updates `total_applied_cents`, increments the bill's `version` by one, and records `decided_by_user_id`. A denial records `decided_by_user_id` and makes no ledger change.

### 3.8. Tax-Sale Referral, Redemption, and Sale

A `CollectionsOfficer` refers a delinquent bill to tax sale by naming its `bill_id` and the `expected_bill_version`. Referral is gated by several checks: the bill's `collection_status` must be `DELINQUENT` with at least one installment in `DELINQUENT`, else `ERR_NOT_DELINQUENT`; the bill's `delinquent_principal_cents` must be at least the statutory lien-referral threshold `LIEN_REFERRAL_THRESHOLD_CENTS` of fifty thousand cents (50000), else `ERR_BELOW_REFERRAL_THRESHOLD` — a delinquent principal exactly equal to 50000 satisfies the check and is referred; the half-open window `[referral_date, redemption_deadline)` must not overlap a non-terminal referral already open on the same parcel — adjacency exactly at a deadline is allowed — else `ERR_REFERRAL_WINDOW_OVERLAP`; and `expected_bill_version` must match the bill's current `version`, else `ERR_STALE_VERSION`. On success a `TaxSaleReferral` is created in status `REFERRED` with its `referral_date` set to the logical-clock instant, its `redemption_deadline` computed as the `referral_date` plus the redemption period `REDEMPTION_PERIOD_DAYS` of three hundred sixty-five days (365), and its `delinquent_principal_at_referral_cents` snapped from the bill's delinquent principal at that moment; `created_by_user_id` is recorded, the bill's `sale_status` moves to `IN_TAX_SALE`, and the bill's `version` increments by one.

An open referral resolves one of two ways. It is redeemed by a `CollectionsOfficer` or `Treasurer` while the current clock is strictly before the `redemption_deadline`; a redemption attempted at or after the deadline is rejected with `ERR_REDEMPTION_EXPIRED`. Redemption moves the referral to `REDEEMED` and sets the bill's `sale_status` to `REDEEMED`. Redemption also occurs automatically as the cascade from a full payment described in §3.4.

The sale is executed by a `Treasurer` and only after the redemption window has closed: the current clock must be at or after the `redemption_deadline`, and a sale attempted before it is rejected with `ERR_REDEMPTION_NOT_EXPIRED`. The executing treasurer must not be the officer who opened the referral — the acting `X-User-ID` must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The sale accepts an optional winning bid `sale_price_cents`, moves the referral to `SOLD`, sets the bill's `sale_status` to the terminal `SOLD`, and records `sold_by_user_id` and `sale_price_cents`. Redeeming or selling a referral that is not in `REFERRED` is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Read operations and state-changing actions on an existing resource (reviews, decisions, payments' reversal, redemptions, sales, and the clock) return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/property-tax/tax-years` | Certify a levy year with millage and installment due dates | Treasurer |
| GET | `/property-tax/tax-years/{id}` | Fetch a tax year | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| POST | `/property-tax/escrow-agents` | Register a mortgage servicer / escrow company | Treasurer |
| POST | `/property-tax/parcels` | Create a taxable parcel | Cashier, Treasurer |
| GET | `/property-tax/parcels/{id}` | Fetch a parcel | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/parcels` | List parcels; filter by `escrow_agent_id` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| POST | `/property-tax/tax-bills` | Issue a bill for a parcel + tax year | Treasurer |
| GET | `/property-tax/tax-bills/{id}` | Fetch a bill with computed balances and both status axes | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/tax-bills` | List bills; filter by `parcel_id` / `tax_year_id` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/tax-bills/{id}/payoff` | Computed payoff quote; `mode` selects `LEDGER_AS_OF` or `PAYOFF_QUOTE` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/tax-bills/{id}/ledger-entries` | Append-only ledger for a bill | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/installments/{id}` | Fetch an installment with penalty/interest as of current clock | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/installments` | List installments; filter by `bill_id` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| POST | `/property-tax/relief-applications` | Submit an exemption or abatement application | Taxpayer, Cashier |
| GET | `/property-tax/relief-applications/{id}` | Fetch a relief application | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/relief-applications` | List relief applications; filter by `parcel_id` / `tax_year_id` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| POST | `/property-tax/relief-applications/{id}/review` | Move an application into review | ReliefOfficer |
| POST | `/property-tax/relief-applications/{id}/request-info` | Request additional information | ReliefOfficer |
| POST | `/property-tax/relief-applications/{id}/resubmit` | Resubmit after an info request | Taxpayer, Cashier |
| POST | `/property-tax/relief-applications/{id}/decide` | Approve or deny an application | ReliefOfficer |
| POST | `/property-tax/payments` | Post a payment (partial allowed) | Cashier, Taxpayer |
| GET | `/property-tax/payments/{id}` | Fetch a payment with its allocation | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/payments` | List payments; filter by `bill_id` / `escrow_agent_id` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| POST | `/property-tax/payments/{id}/reverse` | Reverse a POSTED payment (compensation) | Treasurer |
| POST | `/property-tax/refunds` | File a refund request against an overpaid bill | Taxpayer, Cashier, Treasurer |
| GET | `/property-tax/refunds/{id}` | Fetch a refund | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/refunds` | List refunds; filter by `bill_id` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| POST | `/property-tax/refunds/{id}/decide` | Approve or deny a refund (four-eyes SoD) | Treasurer |
| POST | `/property-tax/tax-sale-referrals` | Refer a delinquent bill to tax sale | CollectionsOfficer |
| GET | `/property-tax/tax-sale-referrals/{id}` | Fetch a referral | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| GET | `/property-tax/tax-sale-referrals` | List referrals; filter by `bill_id` | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer, Taxpayer |
| POST | `/property-tax/tax-sale-referrals/{id}/redeem` | Redeem a referral before the redemption deadline | CollectionsOfficer, Treasurer |
| POST | `/property-tax/tax-sale-referrals/{id}/sell` | Execute the tax sale after redemption expires | Treasurer |
| POST | `/property-tax/_clock/set_current_utc` | Set the server logical clock | Treasurer, Cashier, CollectionsOfficer, ReliefOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_ZERO_AMOUNT` | 422 |
| `ERR_ESCROW_AGENT_REQUIRED` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_BILL` | 409 |
| `ERR_PAYMENT_ALREADY_REVERSED` | 409 |
| `ERR_BILL_ALREADY_PAID` | 409 |
| `ERR_RELIEF_ALREADY_DECIDED` | 409 |
| `ERR_RELIEF_PERIOD_OVERLAP` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_DELINQUENT` | 409 |
| `ERR_BELOW_REFERRAL_THRESHOLD` | 409 |
| `ERR_REFERRAL_WINDOW_OVERLAP` | 409 |
| `ERR_REDEMPTION_EXPIRED` | 409 |
| `ERR_REDEMPTION_NOT_EXPIRED` | 409 |
| `ERR_OVERPAYMENT_UNAVAILABLE` | 409 |
| `ERR_REFUND_ALREADY_DECIDED` | 409 |

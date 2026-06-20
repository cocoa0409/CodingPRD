# SBA Loan Origination API — Product Requirements Document

## 1. Introduction

This document specifies the SBA Loan Origination platform, a back-office system that carries a small-business loan under the SBA 7(a) and 504 programs across its full institutional life: eligibility and size-standard determination, use-of-proceeds budgeting and collateral analysis, the SBA guaranty fee and form package (SBA Forms 1919 and 1920), credit underwriting and four-eyes approval, authorization, closing and multi-draw disbursement, secondary-market sale of the guaranteed portion to investors, monthly 1502 servicing and fee accrual, and — when a loan sours — default, liquidation, and guaranty purchase by the SBA.

The platform is shared by four constituencies whose duties are deliberately segregated. Lender-side originators assemble and underwrite applications; an independent credit authority at the lender approves or declines them; the SBA itself authorizes loans, accepts servicing reports, and honors guaranty purchases; and secondary-market investors buy the guaranteed slice of a loan. The same loan record simultaneously tracks three independent dimensions once it is authorized — where it sits in the origination pipeline, how the borrower is performing, and who currently holds the SBA-guaranteed portion — and the bulk of this document concerns how those dimensions evolve without contaminating one another.

Because money flows in cents and is reconciled across loan-level, lender-pool, and SBA-level ledgers, the system treats arithmetic precision, conservation of guaranteed balances, and strict state gating as first-class correctness requirements rather than incidental details. Every monetary figure is an integer count of cents, and every cascade that moves a balance is specified so that the books always tie out.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, envelopes, and cross-cutting invariants that govern every endpoint in the API. All resource collections are mounted under the `/sba` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles, spelled precisely as follows: `LoanOfficer`, `CreditApprover`, `SbaOfficer`, and `InvestorServicer`. When a caller presents a valid role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

All four roles use opaque identity. When `X-User-Role` is `LoanOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands it — for example, it stamps the authoring officer's identifier into `authored_by_user_id` when a credit memo is created and into `requested_by_user_id` when a guaranty purchase is filed — but it never compares `X-User-ID` to any entity's `id`. When `X-User-Role` is `CreditApprover`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server compares it against the stored `authored_by_user_id` on a credit memo to enforce four-eyes separation, but it is not an entity key. When `X-User-Role` is `SbaOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `InvestorServicer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the investor's identifier supplied as `investor_user_id` on a guaranty sale is an input field rather than a derived entity key.

The role that may invoke each operation is enumerated in the endpoint table of §4. Read operations (the GET endpoints) are available to `SbaOfficer`, `LoanOfficer`, and `CreditApprover` broadly; `InvestorServicer` is restricted to reading a lender's pool balances, an application, and guaranty sales.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` that is not a parseable integer, or that falls outside these bounds (`limit` below 1 or above 100, or `offset` below 0), is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a particular endpoint says otherwise, all list responses are sorted by the `created_at` timestamp in ascending order, with ties among records sharing the same `created_at` broken by ascending creation order (the order in which the records were minted). The `meta` object of every list response carries the `limit`, `offset`, `total_count`, and `has_more` fields; `has_more` is true exactly when `offset` plus the number of items returned on this page is less than `total_count`.

### 2.4. Common Resource Properties and Identifiers

Every resource in the system — `Lender`, `Borrower`, `Application`, `ProceedsLineItem`, `CollateralItem`, `FormPackage`, `CreditMemo`, `Disbursement`, `GuarantySale`, `ServicingReport`, `LiquidationEvent`, and `GuarantyPurchase` — carries a system-managed set of fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field is an ISO 8601 UTC timestamp recording the last mutation. The `version` field is an integer that begins at its initial value of 1 when the resource is created and increments by one on every mutation of that resource. All twelve resource types in this system expose all four of these fields; none of them omit `updated_at` or `version`.

Whenever the server changes any persisted field of a resource — whether because of a direct client request or because a cascade from another operation touched it — that change refreshes the resource's `updated_at` and increments its `version`. This applies equally to computed balances: when an accepted servicing report reduces an application's `outstanding_principal_cents`, or when a settled guaranty sale writes the application's `sold_guaranteed_principal_cents`, the application is mutated and its `version` advances.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several read endpoints address a child collection through its parent, such as listing the borrowers under a lender or the disbursements under an application. For any path that names more than one resource identifier, the server validates each identifier left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource. A request for the collateral of a non-existent application fails on the application identifier before the collateral is ever considered. The same left-to-right existence discipline applies to single-resource reads and to every write whose path names a resource.

### 2.6. Monetary Precision and Rounding

All amounts are integer counts of cents; there are no fractional-cent values anywhere in the system. Each calculation in §3 specifies its own rounding discipline because the programs do not round uniformly: some steps round half up (a value exactly at the half-cent rounds away from zero, upward), while others take the floor (truncation toward zero). Where a calculation says a per-item or per-band amount is floored before a sum, that order is mandatory — the system floors each component first and then adds, never the reverse. Ratios that are not themselves money, such as `guaranty_pct` and `repair_pct`, are carried as their literal input values and are not rounded.

### 2.7. Lender Pool Accounting and Conserved Balances

Each `Lender` carries two pool balances that aggregate activity across all of its loans. The `ongoing_fee_pool_cents` accumulates the SBA ongoing (servicing) guaranty fee owed across the lender's portfolio; it starts at 0 and is credited each time a servicing report is accepted. The `sold_guaranty_balance_cents` is the total guaranteed principal currently sold to investors across the lender's loans; it starts at 0, rises when a guaranty sale settles, and falls back when a sold guaranty is repurchased. The repurchase decrement is exactly the same amount as the prior settle increment, so a sell-then-repurchase cycle returns the pool to its pre-sale value. This is the conservation invariant for the secondary-market settle/repurchase pair: the sold balance is a conserved quantity that no operation may leave drifted.

At the loan level, the application's `outstanding_principal_cents` is likewise a conserved running balance. It rises as principal is disbursed, falls as principal is repaid through accepted servicing reports, and falls when a liquidation settles. The liquidation split itself conserves the net recovery exactly: the SBA share plus the lender share always equals the net recovery, with no rounding remainder lost.

### 2.8. Independent Status Axes

An `Application` carries three status fields that, after authorization, advance independently of one another. The `status` field tracks the origination pipeline and takes the values `DRAFT`, `UNDERWRITING`, `REVISION`, `PENDING_APPROVAL`, `APPROVED`, `AUTHORIZED`, `DISBURSING`, `CLOSED`, `WITHDRAWN`, and `DECLINED`. The `servicing_status` field tracks borrower performance and takes the values `NOT_SERVICING`, `CURRENT`, `DELINQUENT`, `DEFAULTED`, `LIQUIDATED`, and `PAID_IN_FULL`, defaulting to `NOT_SERVICING`. The `guaranty_status` field tracks who holds the guaranteed portion and takes the values `RETAINED`, `SOLD`, `REPURCHASED`, and `PURCHASED_BY_SBA`, defaulting to `RETAINED`. These last two axes are genuinely independent: a loan may be `SOLD` on the guaranty axis while simultaneously `DELINQUENT` on the servicing axis, and an operation that advances one axis does not move the other unless §3 explicitly says so.

### 2.9. Optimistic Concurrency on Guaranty-Sale Settlement

Settling a guaranty sale is the one operation in this system guarded by optimistic concurrency control, because settling supersedes any prior offered sale on the same loan and rewrites the application's sold-principal balance. The settle request must carry `expected_application_version` as a required input field, holding the client's last observed `version` of the target `Application`. If that value does not match the application's current `version` — because another writer has already settled a sale and advanced the loan's version since the client last read it — the settle is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), preventing the client from overwriting a settlement it never observed. When the versions agree, the settle proceeds and increments the application's `version` by one as part of its side effects. No other endpoint in the system takes a version field or performs this check.

### 2.10. Validation Ordering

When several conditions guard a single endpoint, they are evaluated in a fixed precedence so that the returned error is deterministic. The header check for `X-User-ID` and `X-User-Role` comes first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400). Next is the role-permission check against the endpoint's authorized roles (`ERR_FORBIDDEN_FOR_ROLE`, HTTP 403). Next, every resource identifier in the path is checked for existence, left to right (`ERR_NOT_FOUND`, HTTP 404). Next, the request body is checked for well-formedness — required fields present, no negative or zero value where a positive one is required, enum members valid, and any foreign-key target actually existing (`ERR_INVALID_REQUEST`, HTTP 400). Next, for a state-transition endpoint, the target resource must currently be in a state from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409). Only after all of these pass does the system evaluate the domain-specific business rules described in §3, each of which carries its own error identifier. Within that business tier, where multiple business rules guard the same operation, the order in which they are checked is called out alongside the operation in §3.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Lenders, Borrowers, and the Application Shell

The chain begins with an `SbaOfficer` onboarding a `Lender` — a bank for the 7(a) program or a Certified Development Company for the 504 program — by supplying the lender's `name` and its `program`, which is either `7A` or `504`. A newly created lender starts with both pool balances, `ongoing_fee_pool_cents` and `sold_guaranty_balance_cents`, at zero.

A `LoanOfficer` then registers a `Borrower` under a lender by supplying the owning `lender_id`, the borrower's `legal_name`, its six-digit `naics_code` used for the industry size-standard lookup (validated only as a required non-empty string — its digit count is not enforced), and three financial inputs that feed the size standard: the borrower's tangible net worth in `tangible_net_worth_cents`, its two-year average net income after taxes in `avg_net_income_cents`, and its total headcount including affiliates in `affiliate_employee_count`. These three financial inputs are each required and validated as non-negative integers; a value of 0 is well-formed and accepted. The borrower also carries `is_eligible_business_type`, a boolean that defaults to true and is set false for ineligible types such as passive holding companies, lending businesses, and speculative ventures; this flag is the hard eligibility gate examined at submit time. The borrowers under a given lender are discoverable by listing that lender's borrowers.

With a borrower on file, a `LoanOfficer` opens an `Application` by supplying the `borrower_id`, the gross `requested_amount_cents`, the SBA `guaranty_pct` on that gross loan (a fraction strictly greater than 0 and at most 0.90, for example 0.75 or 0.85), and the `maturity_months` term. At creation the application's `lender_id` is copied from the borrower, and the application starts in `DRAFT` status with `servicing_status` of `NOT_SERVICING` and `guaranty_status` of `RETAINED`. Its computed fields — `size_eligible` (false initially), `guaranteed_amount_cents`, `guaranty_fee_cents`, `disbursed_amount_cents`, `outstanding_principal_cents`, and `sold_guaranteed_principal_cents` — all begin at their zero or false defaults and are populated as the loan progresses. Applications are listable with optional filters on `lender_id`, `borrower_id`, and `status`.

### 3.2. Building the Application: Proceeds and Collateral

While an application is still in `DRAFT`, a `LoanOfficer` itemizes how the money will be spent by adding use-of-proceeds line items, each carrying the parent `application_id`, a `use_category`, and the `amount_cents` allocated to it. The `use_category` is one of `WORKING_CAPITAL`, `EQUIPMENT`, `REAL_ESTATE`, `REFINANCE`, `INVENTORY`, or `GOODWILL`. The system sets the line's `is_fixed_asset` flag to true exactly when the category is `EQUIPMENT` or `REAL_ESTATE`, marking the fixed-asset portion of the proceeds, and false for every other category. An application's proceeds line items are listable as a sub-resource.

Collateral is captured separately. A `LoanOfficer` may add collateral items while the application is in `DRAFT`, `UNDERWRITING`, or `REVISION`, each carrying the parent `application_id`, an `asset_type` of `REAL_ESTATE`, `EQUIPMENT`, `INVENTORY`, or `RECEIVABLES`, the independently appraised `appraised_value_cents`, and any senior `prior_lien_cents` ahead of this loan on that asset (defaulting to 0). On creation the system computes the item's net liquidation value into `discounted_value_cents`: it multiplies the appraised value by the discount rate for that asset class — 80 percent for `REAL_ESTATE`, 50 percent for `EQUIPMENT`, 30 percent for `INVENTORY`, and 50 percent for `RECEIVABLES` — takes the floor of that product, subtracts the prior lien, and floors the result at zero so a fully encumbered asset contributes nothing. Collateral items are listable as a sub-resource per application.

### 3.3. The Form Package and the Character Branch

In parallel with underwriting, a `LoanOfficer` assembles the SBA `FormPackage` for an application by supplying the `application_id` and three booleans that each default to false: `form_1919_complete` (the Borrower Information Form, SBA 1919), `form_1920_complete` (the Lender Application Form, SBA 1920), and `character_cleared` (the character and background determination). The package is created in `INCOMPLETE` status. Form packages are listable as a sub-resource per application.

The officer submits the package for review, which moves it from `INCOMPLETE` to `SUBMITTED`. Submission is permitted only when both `form_1919_complete` and `form_1920_complete` are true; if either form is not yet marked complete, the submit is rejected with `ERR_FORM_INCOMPLETE`. A `CreditApprover` then reviews a `SUBMITTED` package, and the review branches on `character_cleared`. When `character_cleared` is true, the package moves to `CLEARED`, which unblocks credit-memo submission downstream. When `character_cleared` is false, the package instead moves to `FLAGGED`, which leaves credit-memo submission blocked. A `FLAGGED` package can be reopened by a `LoanOfficer`, which loops it back to `INCOMPLETE` for correction and optionally accepts an updated `character_cleared` value to clear the character flag before the next round. Both review branches are deliberately symmetric in form — each is a single review action on a `SUBMITTED` package that lands in one terminal-for-this-cycle state determined solely by the `character_cleared` value — but they diverge in consequence: only the `CLEARED` outcome permits the credit memo to advance.

### 3.4. Submission, Underwriting, and the Credit Memo

A `LoanOfficer` submits a `DRAFT` application into underwriting, which advances `status` from `DRAFT` to `UNDERWRITING`. Submission enforces three preconditions, and it runs the size standard as a side effect. First, the borrower's `is_eligible_business_type` must be true, or the submit is rejected with `ERR_INELIGIBLE_BUSINESS`. Second, at least one proceeds line item must exist, or the submit is rejected with `ERR_NO_PROCEEDS`. Third, the sum of the `amount_cents` across all proceeds line items must equal the application's `requested_amount_cents`, or the submit is rejected with `ERR_PROCEEDS_MISMATCH`. When those hold, the system runs the size determination and writes its boolean result into `size_eligible`; if the determination comes back ineligible, the submit is rejected with `ERR_SIZE_STANDARD_EXCEEDED` and no transition occurs.

The size determination uses the alternative size standard, which passes if **either** of two prongs holds. The financial prong holds when the borrower's `tangible_net_worth_cents` is at most twenty million dollars (that is, at most 2,000,000,000 cents) **and** its `avg_net_income_cents` is at most six and a half million dollars (650,000,000 cents). The headcount prong holds when `affiliate_employee_count` is at most 500 employees. The application is size-eligible when the financial prong holds or the headcount prong holds. All three caps are inclusive: a value sitting exactly at a cap satisfies that comparison.

With the application in `UNDERWRITING`, a `LoanOfficer` authors a `CreditMemo` by supplying the `application_id`, the asserted debt-service-coverage ratio `dscr` (for example 1.35), an internal `risk_rating` from 1 (best) to 8 (worst), and a `recommendation` of either `APPROVE` or `DECLINE`. The memo is created in `DRAFT` status, and the system stamps the authoring officer's identifier into `authored_by_user_id`; this stored author is the anchor for the four-eyes rule later. Credit memos are listable as a sub-resource per application.

Submitting the credit memo advances the memo from `DRAFT` to `SUBMITTED` and the application's `status` from `UNDERWRITING` to `PENDING_APPROVAL`. Two preconditions guard this submit, evaluated in this order: first, the application's form package must be in `CLEARED` status, or the submit is rejected with `ERR_FORM_PACKAGE_NOT_CLEARED`; second, the discounted collateral coverage must meet the requirement for the loan's maturity bucket, or the submit is rejected with `ERR_COLLATERAL_SHORTFALL`. The coverage test sums the `discounted_value_cents` of every collateral item on the application — each already floored per item and floored at zero as described in §3.2 — and compares that total against a maturity-dependent requirement. For a long-term loan whose `maturity_months` exceeds 120, the required coverage is the full `requested_amount_cents` (100 percent net coverage). For a loan whose `maturity_months` is 120 or less, the required coverage is the floor of half the `requested_amount_cents` (50 percent). Coverage is sufficient when the summed discounted value is greater than or equal to the requirement; the boundary is inclusive, so a total exactly equal to the requirement passes.

### 3.5. Approval, the Four-Eyes Rule, and the Revision Cycle

Once an application is `PENDING_APPROVAL`, a `CreditApprover` renders a decision. Approval advances `status` from `PENDING_APPROVAL` to `APPROVED` and marks the submitted memo `APPROVED`. Two preconditions guard approval: the acting approver's `X-User-ID` must differ from the submitted memo's `authored_by_user_id`, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`; and the submitted memo's `recommendation` must be `APPROVE`, or the approval is rejected with `ERR_MEMO_NOT_APPROVABLE`. The segregation-of-duties check is the four-eyes guarantee: the officer who authored a memo may never be the approver who approves it.

A `CreditApprover` may instead decline the application, advancing `status` from `PENDING_APPROVAL` to `DECLINED` and marking the submitted memo `REJECTED`. Decline carries the same four-eyes guard — the decliner's `X-User-ID` must differ from the memo's `authored_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. `DECLINED` is terminal on the origination axis.

The committee may also send a pending application back for rework rather than deciding it outright. A `CreditApprover` requests revision on a `PENDING_APPROVAL` application, which moves `status` to `REVISION` and sets the currently submitted credit memo back to `REJECTED`; this transition requires that a `SUBMITTED` credit memo exist for the application, or it is rejected with `ERR_NO_CREDIT_MEMO`. This is the cycle entry. To close the loop, a `LoanOfficer` resubmits the revised application, moving `status` from `REVISION` back to `UNDERWRITING`; resubmission requires that a `DRAFT` credit memo exist (a revision must have been authored), or it is rejected with `ERR_NO_CREDIT_MEMO`. From `UNDERWRITING` the loop can run again — a fresh credit-memo submit returns the application to `PENDING_APPROVAL` — and this underwriting-to-approval loop may repeat any number of times.

At any point while the application is in `DRAFT`, `UNDERWRITING`, or `REVISION`, a `LoanOfficer` may withdraw it, moving `status` to `WITHDRAWN`. `WITHDRAWN` is terminal on the origination axis and carries no other side effects.

### 3.6. Authorization: Freezing the Guaranty Amount and Fee

When an approved application is ready, an `SbaOfficer` authorizes it, advancing `status` from `APPROVED` to `AUTHORIZED`. Authorization re-checks that `size_eligible` is true, rejecting with `ERR_SIZE_STANDARD_EXCEEDED` otherwise. As side effects it freezes two figures that never change afterward, and it leaves `guaranty_status` at `RETAINED` and `servicing_status` at `NOT_SERVICING`.

The first frozen figure is `guaranteed_amount_cents`, the SBA-guaranteed portion of the loan. It is the application's `requested_amount_cents` multiplied by its `guaranty_pct`, rounded half up to whole cents.

The second frozen figure is `guaranty_fee_cents`, the upfront SBA guaranty fee. This fee uses a marginal tiered schedule selected by the gross `requested_amount_cents`, with each band's rate applied to the guaranteed slice of that band. The gross amount is split into three bands: the first band is the portion of the gross up to and including 15,000,000 cents ($150,000); the second band is the portion of the gross from above 15,000,000 cents up to and including 70,000,000 cents ($700,000), that is, the gross in excess of the first tier but capped at the width between the two tiers; and the third band is any portion of the gross above 70,000,000 cents. For each band, take that band's gross dollars, multiply by the application's `guaranty_pct` to get the guaranteed slice of the band, multiply by the band's rate, and floor the result to whole cents: the first band uses a rate of 2.00 percent, the second band 3.00 percent, and the third band 3.50 percent. The three floored band fees are then summed to give `guaranty_fee_cents`. The per-band floor is applied before the summation, in that order. The tier boundaries are inclusive at the lower tier: a gross amount sitting exactly at 15,000,000 cents lies wholly in the first band and attracts only the 2.00 percent rate, and the first cent above a threshold is the first to attract the next band's higher rate.

This upfront guaranty fee is permanently sale-independent. Selling the guaranty on the secondary market later does not rebate, reduce, or otherwise alter the `guaranty_fee_cents` frozen at authorization; the fee is billed on the full guaranteed portion and stays fixed regardless of any later guaranty sale.

### 3.7. Disbursement, Draw Windows, and Closing

After authorization, a `LoanOfficer` funds the loan through one or more draws. A disbursement is requested with the parent `application_id`, the `amount_cents` of the draw, a free-text `tranche_label` such as "Initial" or "Construction draw 2", and the draw's funding window expressed as `draw_window_start_day` and `draw_window_end_day`, both day indices counted from authorization. The window is half-open: `draw_window_start_day` is inclusive and `draw_window_end_day` is exclusive, so the window covers the start day up to but not including the end day. Both day indices are required integers and the window must be non-empty — `draw_window_start_day` and `draw_window_end_day` must each be at least 0 and `draw_window_start_day` must be strictly less than `draw_window_end_day`, or the request is rejected at the body tier with `ERR_INVALID_REQUEST`. A requested draw starts in `REQUESTED` status. Disbursements are listable as a sub-resource per application.

Posting a draw advances it from `REQUESTED` to `POSTED` and is guarded by three preconditions. First, the application must be in `AUTHORIZED` or `DISBURSING` status, or the post is rejected with `ERR_NOT_AUTHORIZED_FOR_DISBURSAL`. Second, the running `disbursed_amount_cents` plus this draw's `amount_cents` must not exceed `requested_amount_cents`, or the post is rejected with `ERR_OVER_DISBURSEMENT`. Third, this draw's half-open window must not overlap the window of any other already-`POSTED` draw on the same application; two windows that merely touch — where one window's `draw_window_end_day` equals another's `draw_window_start_day` — do not overlap, but any genuine overlap is rejected with `ERR_DRAW_WINDOW_OVERLAP`. When a post succeeds, the system adds the draw's `amount_cents` to the application's `disbursed_amount_cents` and adds the same amount to its `outstanding_principal_cents`. If this is the first draw to reach `POSTED` on the application, the post also advances the application's `status` from `AUTHORIZED` to `DISBURSING` and its `servicing_status` from `NOT_SERVICING` to `CURRENT`, starting the servicing clock.

A `POSTED` draw may be reversed by a `LoanOfficer`, moving it to `REVERSED`, provided the application's `servicing_status` is not `DEFAULTED` or `LIQUIDATED` (otherwise the reversal is rejected with `ERR_INVALID_STATE`). Reversal is compensating: it subtracts the draw's `amount_cents` back out of `disbursed_amount_cents` and out of `outstanding_principal_cents`. A reversed draw is terminal.

Once the loan is fully funded, a `LoanOfficer` closes origination, advancing `status` from `DISBURSING` to `CLOSED`. Closing requires that `disbursed_amount_cents` equal `requested_amount_cents`, or it is rejected with `ERR_NOT_FULLY_DISBURSED`. Reaching `CLOSED` completes the origination axis only; the servicing and guaranty axes continue to evolve afterward.

### 3.8. Secondary-Market Sale of the Guaranteed Portion

The guaranteed slice of an authorized loan can be sold to a secondary-market investor. A `LoanOfficer` offers a `GuarantySale` by supplying the `application_id`, the `investor_user_id` of the buying `InvestorServicer`, the `sold_principal_cents` being sold, and the price premium over par in `premium_bps` (basis points, where 350 means a 3.50 percent premium, constrained to between 0 and 1500 inclusive). On creation the sale's `lender_id` is copied from the application, the sale starts in `OFFERED` status, and the `sold_principal_cents` must equal the application's `guaranteed_amount_cents`, or the offer is rejected with `ERR_SALE_PRINCIPAL_MISMATCH`. The `sold_principal_cents` is validated only as a non-negative integer rather than as a strictly positive one: a value of 0 is well-formed and accepted, so an offer against an application whose `guaranteed_amount_cents` is still 0 (one not yet authorized) passes well-formedness and is gated solely by the equality rule above rather than by `ERR_INVALID_REQUEST`. The computed net `premium_cents` defaults to 0 until settlement. Guaranty sales are listable both as a sub-resource per application and as a sub-resource per lender.

An `InvestorServicer` settles an `OFFERED` sale, which is the OCC-guarded write of §2.9: the request carries `expected_application_version`, and a stale value is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). Two further preconditions apply: the sale must be in `OFFERED` status, or the settle is rejected with `ERR_INVALID_STATE`; and the application's origination `status` must be `AUTHORIZED`, `DISBURSING`, or `CLOSED`, or the settle is rejected with `ERR_GUARANTY_NOT_SELLABLE`. On a successful settle the system moves the sale to `SETTLED`, advances the application's `guaranty_status` from `RETAINED` to `SOLD`, computes the net `premium_cents`, sets the application's `sold_guaranteed_principal_cents` to the sale's `sold_principal_cents`, adds that same `sold_principal_cents` to the selling `Lender`'s `sold_guaranty_balance_cents`, and increments the application's `version` by one.

The net premium credited to the lender is computed from the sale's `sold_principal_cents` and `premium_bps`, with the SBA taking a share only above a retained floor. First, the gross premium is the floor of the sold principal multiplied by the premium in basis points divided by 10,000. Second, the lender's retained floor is the floor of the sold principal multiplied by 100 basis points divided by 10,000 — that is, the lender always keeps premium up to 1.00 percent of par. If the gross premium is less than or equal to the retained floor, the SBA's cut is zero. Otherwise the SBA's cut is the floor of half of the amount by which the gross premium exceeds the retained floor — the SBA takes 50 percent of the premium above the floor. The net `premium_cents` credited to the lender is the gross premium minus the SBA's cut. Each step is floored, in exactly the order stated.

The lender may unwind a sold guaranty. A `LoanOfficer` repurchases a `SETTLED` sale, moving it to `REPURCHASED` and the application's `guaranty_status` from `SOLD` to `REPURCHASED`; this requires the sale to be in `SETTLED` status, or it is rejected with `ERR_INVALID_STATE`. Repurchase is compensating: it resets the application's `sold_guaranteed_principal_cents` to 0 and subtracts the sale's `sold_principal_cents` back out of the lender's `sold_guaranty_balance_cents`, returning the pool to its pre-sale value.

### 3.9. Servicing, 1502 Reporting, and the Performance Axis

Once a loan is being serviced, monthly performance is reported through 1502 servicing reports. A `LoanOfficer` files a `ServicingReport` with the `application_id`, the reporting `period_index` (the 0-based monthly period, equal to `period_start_month` for a single-month report), the coverage interval given by `period_start_month` and `period_end_month`, the `principal_paid_cents` and `interest_paid_cents` collected, and the borrower's `days_past_due` as of cutoff (defaulting to 0). The coverage interval is closed on both ends — it spans from `period_start_month` through `period_end_month` inclusive — so a catch-up report may cover more than one month; `period_index`, `period_start_month`, and `period_end_month` are required non-negative integers, and `period_start_month` must be at most `period_end_month` or the request is rejected with `ERR_INVALID_REQUEST`. The supplied `period_index` is stored as given but is not itself cross-checked against `period_start_month`, and it plays no part in the acceptance contiguity test. The report's computed `ongoing_fee_cents` defaults to 0 until acceptance. A report is created in `PENDING` status, and reports are listable as a sub-resource per application.

An `SbaOfficer` accepts a `PENDING` report, moving it to `ACCEPTED`, or rejects it, moving it to `REJECTED` with no other effect. Acceptance is guarded by two preconditions. First, the report's closed interval must be contiguous with and non-overlapping with the prior accepted interval: its `period_start_month` must equal one plus the largest `period_end_month` among already-accepted reports on the application, or 0 if this is the first accepted report; otherwise the accept is rejected with `ERR_PERIOD_OUT_OF_ORDER`. Second, the reported `principal_paid_cents` must not exceed the application's current `outstanding_principal_cents`, or the accept is rejected with `ERR_PRINCIPAL_OVERPAY`.

Acceptance triggers a cascade in a fixed order. First, the system computes the ongoing servicing fee on the outstanding principal as it stands **before** this report's principal is applied, and writes it into the report's `ongoing_fee_cents`. That fee is the monthly slice of an annual rate on the guaranteed portion of outstanding principal: take the application's `outstanding_principal_cents` (pre-this-report) multiplied by its `guaranty_pct`, rounded half up to whole cents, to get the guaranteed outstanding; multiply that by the annual ongoing rate of 0.55 percent, divide by 12 to get the monthly figure, and floor to whole cents. Second, that `ongoing_fee_cents` is added to the lender's `ongoing_fee_pool_cents`. Third, the report's `principal_paid_cents` is subtracted from the application's `outstanding_principal_cents`. Fourth, the servicing axis is re-evaluated in this precedence: the payoff branch is tested first, so if the subtraction drives `outstanding_principal_cents` to 0 and the current `servicing_status` is `CURRENT`, `servicing_status` moves from `CURRENT` to `PAID_IN_FULL` and no further branch is applied this cycle; otherwise, an accepted report whose `days_past_due` is at least 60 moves `servicing_status` from `CURRENT` to `DELINQUENT`, while one whose `days_past_due` is below 60 moves it from `DELINQUENT` back to `CURRENT` (the cure edge). Each of these transitions fires only from the source status named — the delinquency move applies only when the status is `CURRENT`, the cure move only when it is `DELINQUENT`, and the payoff move only when it is `CURRENT` — so a status outside the named source (for example a loan already `DELINQUENT` when principal reaches 0) is left unchanged by that branch.

### 3.10. Default, Liquidation, and Guaranty Purchase

When a loan goes bad, a `LoanOfficer` declares default, moving `servicing_status` from `DELINQUENT` to `DEFAULTED`. Default may be declared only when the most-recent accepted servicing report shows `days_past_due` of at least 90; otherwise the declaration is rejected with `ERR_NOT_DELINQUENT_ENOUGH`. The most-recent accepted servicing report is the `ACCEPTED` report on the application with the largest `period_end_month`, ties among equal `period_end_month` broken by latest creation order; if no accepted report exists the declaration is rejected with `ERR_NOT_DELINQUENT_ENOUGH`. Default leaves the origination `status` untouched.

On a defaulted loan, a `LoanOfficer` opens a `LiquidationEvent` by supplying the `application_id`, the gross collateral proceeds recovered in `recovery_cents`, and the liquidation `expense_cents` deducted off the top (defaulting to 0). Opening is permitted only when `servicing_status` is `DEFAULTED`, or it is rejected with `ERR_NOT_DEFAULTED`. The event starts in `OPEN` status with its computed `sba_share_cents` and `lender_share_cents` at 0. Liquidation events are listable as a sub-resource per application.

A `LoanOfficer` settles an `OPEN` liquidation, moving it to `SETTLED` and the application's `servicing_status` from `DEFAULTED` to `LIQUIDATED` (the liquidation must be `OPEN`, or the settle is rejected with `ERR_INVALID_STATE`). Settlement runs a waterfall split: first the net recovery is the gross `recovery_cents` minus `expense_cents`, floored at zero; then the SBA's share `sba_share_cents` is the net recovery multiplied by the application's `guaranty_pct`, rounded half up to whole cents; and the lender's share `lender_share_cents` is the remainder, the net recovery minus the SBA share. Splitting this way conserves the net recovery exactly — the SBA share plus the lender share always equals the net recovery. Settlement also reduces the application's `outstanding_principal_cents` by the net recovery, which lowers the guaranty-purchase cap downstream.

Finally, the current guaranty holder may claim the guaranty from the SBA. A `LoanOfficer` files a `GuarantyPurchase` with the `application_id`, the outstanding guaranteed principal claimed in `claimed_principal_cents`, and an origination-defect `repair_pct` (a fraction from 0 to 1 inclusive, defaulting to 0) by which the SBA reduces the payout. Filing is permitted only when the application's `servicing_status` is `DEFAULTED` or `LIQUIDATED`, or it is rejected with `ERR_NOT_DEFAULTED`; the system stamps the filing officer's identifier into `requested_by_user_id`, the request starts in `FILED` status, and `approved_amount_cents` defaults to 0. Guaranty purchases are listable as a sub-resource per application.

An `SbaOfficer` pays a `FILED` purchase request, which sets the application's `guaranty_status` to `PURCHASED_BY_SBA` — in the ordinary flow this supersedes a `RETAINED` or `REPURCHASED` value, but the assignment is unconditional and is not gated on the prior `guaranty_status`, so a sale-active loop (for example one still `SOLD`) is likewise overwritten to `PURCHASED_BY_SBA`. Two preconditions apply: the application's `servicing_status` must be `DEFAULTED` or `LIQUIDATED`, or the pay is rejected with `ERR_NOT_DEFAULTED`; and the purchase must be in `FILED` status, or it is rejected with `ERR_INVALID_STATE`. On a successful pay the system computes the approved payout into `approved_amount_cents` and moves the purchase to `PAID`. The payout is the lesser of the claim and the guaranteed share of current outstanding, reduced first by any liquidation recovery already credited to the SBA and then by the repair fraction. Concretely: the cap is the application's current `outstanding_principal_cents` multiplied by its `guaranty_pct`, rounded half up to whole cents; the base is the smaller of `claimed_principal_cents` and that cap; the SBA recovery credit is the sum of `sba_share_cents` across all `SETTLED` liquidation events on the application; the amount after recovery is the base minus that recovery credit, floored at zero; and `approved_amount_cents` is the floor of the after-recovery amount multiplied by one minus `repair_pct`. When `repair_pct` is 0 and no prior liquidation has been settled, this collapses to simply the lesser of the claim and the cap — the SBA pays the full capped claim. When `repair_pct` is greater than zero or a settled liquidation has credited the SBA, both deductions stack, with the repair reduction applied last. Alternatively, an `SbaOfficer` may deny a `FILED` request, moving it to `DENIED`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that act on or transition an existing resource — every list read, every single-resource read, and every state-changing action — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sba/lenders` | Create a Lender (bank or CDC) | SbaOfficer |
| GET | `/sba/lenders/{lenderId}` | Get a Lender, including pool balances | SbaOfficer, LoanOfficer, CreditApprover, InvestorServicer |
| POST | `/sba/borrowers` | Create a Borrower under a Lender | LoanOfficer |
| GET | `/sba/borrowers/{borrowerId}` | Get a Borrower | SbaOfficer, LoanOfficer, CreditApprover |
| GET | `/sba/lenders/{id}/borrowers` | List a Lender's Borrowers | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/applications` | Create a DRAFT Application for a Borrower | LoanOfficer |
| GET | `/sba/applications/{applicationId}` | Get an Application with all computed balances and status axes | SbaOfficer, LoanOfficer, CreditApprover, InvestorServicer |
| GET | `/sba/applications` | List Applications, filterable by lender, borrower, or status | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/applications/{applicationId}/submit` | Submit a DRAFT Application into underwriting; runs the size standard | LoanOfficer |
| POST | `/sba/applications/{applicationId}/request-revision` | Send a pending application back for revision | CreditApprover |
| POST | `/sba/applications/{applicationId}/resubmit` | Resubmit a revised application into underwriting | LoanOfficer |
| POST | `/sba/applications/{applicationId}/approve` | Approve the submitted memo (four-eyes enforced) | CreditApprover |
| POST | `/sba/applications/{applicationId}/decline` | Decline the application | CreditApprover |
| POST | `/sba/applications/{applicationId}/authorize` | Authorize the loan; freeze guaranteed amount and guaranty fee | SbaOfficer |
| POST | `/sba/applications/{applicationId}/close` | Close origination once fully disbursed | LoanOfficer |
| POST | `/sba/applications/{applicationId}/withdraw` | Withdraw an application | LoanOfficer |
| POST | `/sba/applications/{applicationId}/declare-default` | Declare default on a delinquent loan | LoanOfficer |
| POST | `/sba/proceeds` | Add a use-of-proceeds line item | LoanOfficer |
| GET | `/sba/applications/{id}/proceeds` | List an Application's proceeds line items | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/collateral` | Add a collateral item | LoanOfficer |
| GET | `/sba/applications/{id}/collateral` | List an Application's collateral items | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/form-packages` | Create the SBA form package for an application | LoanOfficer |
| GET | `/sba/applications/{id}/form-packages` | List an Application's form packages | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/form-packages/{formPackageId}/submit` | Submit a form package for review | LoanOfficer |
| POST | `/sba/form-packages/{formPackageId}/review` | Review a submitted package; branch to CLEARED or FLAGGED | CreditApprover |
| POST | `/sba/form-packages/{formPackageId}/reopen` | Reopen a FLAGGED package for correction | LoanOfficer |
| POST | `/sba/credit-memos` | Author a DRAFT credit memo | LoanOfficer |
| GET | `/sba/applications/{id}/credit-memos` | List an Application's credit memos | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/credit-memos/{creditMemoId}/submit` | Submit a credit memo, moving the application to PENDING_APPROVAL | LoanOfficer |
| POST | `/sba/disbursements` | Request a disbursement draw | LoanOfficer |
| GET | `/sba/applications/{id}/disbursements` | List an Application's disbursements | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/disbursements/{disbursementId}/post` | Post (fund) a disbursement draw | LoanOfficer |
| POST | `/sba/disbursements/{disbursementId}/reverse` | Reverse a posted disbursement | LoanOfficer |
| POST | `/sba/guaranty-sales` | Offer the guaranteed portion to an investor | LoanOfficer |
| GET | `/sba/applications/{id}/guaranty-sales` | List an Application's guaranty sales | SbaOfficer, LoanOfficer, CreditApprover, InvestorServicer |
| GET | `/sba/lenders/{id}/guaranty-sales` | List a Lender's guaranty sales | SbaOfficer, LoanOfficer, CreditApprover, InvestorServicer |
| POST | `/sba/guaranty-sales/{saleId}/settle` | Settle the sale (OCC on Application version); credit net premium | InvestorServicer |
| POST | `/sba/guaranty-sales/{saleId}/repurchase` | Repurchase the sold guaranty (compensating) | LoanOfficer |
| POST | `/sba/servicing-reports` | File a monthly or catch-up 1502 servicing report | LoanOfficer |
| GET | `/sba/applications/{id}/servicing-reports` | List an Application's servicing reports | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/servicing-reports/{reportId}/accept` | Accept a 1502 report; accrue ongoing fee, reduce principal | SbaOfficer |
| POST | `/sba/servicing-reports/{reportId}/reject` | Reject a 1502 report | SbaOfficer |
| POST | `/sba/liquidations` | Open a liquidation event on a defaulted loan | LoanOfficer |
| GET | `/sba/applications/{id}/liquidations` | List an Application's liquidation events | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/liquidations/{liquidationId}/settle` | Settle the liquidation; split net recovery | LoanOfficer |
| POST | `/sba/guaranty-purchases` | File a guaranty purchase request to SBA | LoanOfficer |
| GET | `/sba/applications/{id}/guaranty-purchases` | List an Application's guaranty purchase requests | SbaOfficer, LoanOfficer, CreditApprover |
| POST | `/sba/guaranty-purchases/{purchaseId}/pay` | Pay a guaranty purchase, applying recovery credit and repair | SbaOfficer |
| POST | `/sba/guaranty-purchases/{purchaseId}/deny` | Deny a guaranty purchase request | SbaOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INELIGIBLE_BUSINESS` | 409 Conflict |
| `ERR_SIZE_STANDARD_EXCEEDED` | 409 Conflict |
| `ERR_NO_PROCEEDS` | 409 Conflict |
| `ERR_PROCEEDS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FORM_INCOMPLETE` | 409 Conflict |
| `ERR_FORM_PACKAGE_NOT_CLEARED` | 409 Conflict |
| `ERR_COLLATERAL_SHORTFALL` | 409 Conflict |
| `ERR_NO_CREDIT_MEMO` | 409 Conflict |
| `ERR_MEMO_NOT_APPROVABLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_NOT_AUTHORIZED_FOR_DISBURSAL` | 409 Conflict |
| `ERR_DRAW_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OVER_DISBURSEMENT` | 409 Conflict |
| `ERR_NOT_FULLY_DISBURSED` | 409 Conflict |
| `ERR_SALE_PRINCIPAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GUARANTY_NOT_SELLABLE` | 409 Conflict |
| `ERR_STALE_APPLICATION_VERSION` | 412 Precondition Failed |
| `ERR_PERIOD_OUT_OF_ORDER` | 409 Conflict |
| `ERR_PRINCIPAL_OVERPAY` | 422 Unprocessable Entity |
| `ERR_NOT_DELINQUENT_ENOUGH` | 409 Conflict |
| `ERR_NOT_DEFAULTED` | 409 Conflict |

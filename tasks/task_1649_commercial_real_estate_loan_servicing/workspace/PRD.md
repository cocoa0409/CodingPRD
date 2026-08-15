# Commercial Real Estate Loan Servicing API — Product Requirements Document

## 1. Introduction

Commercial mortgage servicing is a discipline of deadlines and thresholds. Between closing and maturity, a servicer must collect rent rolls and operating statements on a fixed cadence, test debt-service-coverage and loan-to-value covenants with arithmetic that admits no rounding ambiguity, hold and release reserve cash under retainage rules, supervise major leases through estoppel certificates, keep insurance continuous and collateral inspected, and decide when a credit has deteriorated enough to leave the master servicer's hands for special servicing. None of these duties stands alone: a late statement becomes a watchlist entry, a watchlist entry elevates retainage on every reserve of the loan, and an escalation to special servicing freezes disbursements and suspends extension options in a single cascade.

This document specifies an API for a commercial real estate loan servicer that operationalizes that mandate end to end. Every loan carries two independent status dimensions — a payment dimension driven by delinquency and maturity, and a servicing posture derived automatically from covenant assessments and watchlist entries — and nearly every money movement or borrower right is gated on the pair. A logical servicing clock, never wall time, drives a deterministic sweep so that reporting delinquency, insurance lapse, maturity risk, and maturity default are detected identically on every run. Four segregated roles — `MasterServicer`, `SpecialServicer`, `Borrower`, and `Inspector` — share the workload under explicit ownership scoping and segregation-of-duties constraints, and two creation workflows are guarded by optimistic concurrency so that decisions priced off a freshly observed parent cannot be booked against a mutated one.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming one of the four declared roles — `MasterServicer`, `SpecialServicer`, `Borrower`, `Inspector` — spelled exactly as shown. A request missing either header, naming an undeclared role, or — for the entity-backed roles below — presenting an `X-User-ID` that does not correspond to an existing entity of that kind is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role does not appear on the target endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identities resolve as follows:

- When `X-User-Role` is `MasterServicer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — as `reviewed_by_user_id` on a reviewed statement, `appraised_by_user_id` on an appraisal, or in similar attribution fields — but never compares it to any entity's `id`.
- When `X-User-Role` is `SpecialServicer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It may be recorded, for example as `waived_by_user_id` on a waived covenant assessment, and segregation-of-duties checks compare such recorded identifiers against the acting header value, but it is never compared to any entity's `id`.
- When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`. Ownership checks on any resource reachable through a loan chain — the loan itself, its properties, its statements, its reserve accounts and their draw requests, its leases and estoppel certificates, its inspections, its insurance policies, its assumption requests, its extension options, and its watchlist entries — resolve the chain back to the loan's `borrower_id` and compare it to `X-User-ID`. A borrower writing into another borrower's chain is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
- When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`. Completing a property inspection compares the inspection's assigned `inspector_id` to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

Reads are scoped rather than forbidden: an entity-backed role reading a resource outside its own scope — a borrower reading another borrower's loan chain, an inspector reading another inspector's schedule — receives `ERR_NOT_FOUND` (HTTP 404), exactly as if the resource did not exist.

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

List endpoints accept two query parameters. `limit` bounds the page size: it defaults to 10, accepts a minimum of 1 and a maximum of 100, and `offset` skips that many records from the start of the ordered result, defaulting to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order; the endpoint descriptions in §4 flag the exceptions that return the newest records first. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Servicing Clock

All "now" semantics in the system — statement lateness, certificate and policy expiry, delinquency aging, sweep detection — read a single logical servicing clock, never wall time. At startup the clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time, and it advances only when a `MasterServicer` or `SpecialServicer` sets it to a supplied instant. Every advance runs the deterministic seven-step sweep described in §3.7, in pinned order. All date arithmetic is performed in whole days, UTC.

### 2.5. Common Resource Properties

Every resource in the system carries a standard quartet of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation of the resource.
- `version` — an integer that increments on every mutation, including cascaded mutations such as a reserve account's `elevated_retainage` flag flipping when its loan changes posture. This field is the optimistic-concurrency token described in §2.8.

### 2.6. Monetary and Ratio Precision

Money is always represented as integer cents; the API never accepts or returns fractional cents. Covenant ratios — the loan's `current_dscr` and `current_ltv`, and each assessment's `computed_value` — are carried to exactly four decimal places using round-half-up. Fees, premiums, retainage withholdings, and every other derived cent amount are rounded half-up to whole cents at the point each calculation in §3 specifies. The watchlist risk score is an integer between 0 and 100 inclusive.

### 2.7. Nested Resource Retrieval

Paths that nest identifiers are validated left to right — loan before child, child before grandchild — and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). A request to act on a draw request beneath a nonexistent reserve account therefore fails on the reserve account before the draw is ever examined, and foreign keys supplied in request bodies must likewise reference existing entities.

### 2.8. Optimistic Concurrency Control

Two creation endpoints are guarded by optimistic concurrency control, because the client's decision to create is priced off a freshly observed parent:

- `POST /loans/{loan_id}/assumption-requests` requires the non-optional field `expected_loan_version`, carrying the target loan's `version` as the client last observed it. If the loan's current `version` no longer matches — because the loan has been mutated since that read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from booking an assumption priced on a stale snapshot of the loan.
- `POST /reserve-accounts/{reserve_account_id}/disbursement-requests` requires the non-optional field `expected_reserve_account_version`, carrying the reserve account's `version` as last observed. A mismatch with the reserve's current `version` — advanced, for instance, by a deposit or a funded draw changing its balances — is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field.

### 2.9. The Two-Dimensional Loan Posture

Every loan carries two independent status dimensions. The payment dimension, `payment_status`, moves among `CURRENT`, `DELINQUENT`, `DEFAULT`, and `MATURITY_DEFAULT` under operator action and the clock sweep. The servicing dimension, `servicing_status`, moves among `PERFORMING`, `WATCHLIST`, and `SPECIAL_SERVICING` and is derived rather than written directly: the system recomputes it whenever covenant assessments or watchlist entries change. The posture gates money movement and borrower rights throughout this document — reserves elevate retainage while the loan stands at anything other than `PERFORMING` and freeze disbursements entirely under `SPECIAL_SERVICING`, and extension options suspend while the loan is in special servicing.

### 2.10. Validation Pipeline and Error Precedence

Every request is validated against a fixed pipeline, and when several checks would fail at once, the error returned is the one belonging to the earliest failing check:

1. Authentication: headers present, role declared, entity-backed identifiers resolvable — else `ERR_UNAUTHENTICATED`.
2. Authorization: the acting role appears in the endpoint's authorized list — else `ERR_UNAUTHORIZED`.
3. Ownership and scope: borrower loan-chain ownership on writes, inspector self-assignment on completion — else `ERR_OWNERSHIP_MISMATCH`; out-of-scope reads instead surface as `ERR_NOT_FOUND`.
4. Existence: path identifiers resolve left to right, and foreign keys in request bodies reference existing entities — else `ERR_NOT_FOUND`.
5. Request schema: required fields present, types valid, enum members valid, ranges valid (amounts strictly positive where required, fractions between 0 and 1, ends not before starts, non-empty line items) — else `ERR_INVALID_REQUEST`.
6. Optimistic concurrency: on the two guarded creates of §2.8, the expected parent version must equal the parent's current `version` — else `ERR_STALE_VERSION`.
7. Generic state-machine precondition for the requested transition — else `ERR_INVALID_STATE`.
8. Statement already reviewed — `ERR_STATEMENT_ALREADY_REVIEWED`.
9. No `OPEN` covenant assessment where one blocks — `ERR_OPEN_COVENANT_BREACH`.
10. Loan payment status `CURRENT` where required — `ERR_LOAN_NOT_CURRENT`.
11. Reserve disbursements not frozen — `ERR_RESERVE_DISBURSEMENTS_FROZEN`.
12. Segregation of duties on covenant waivers — `ERR_SEGREGATION_OF_DUTIES`.
13. No `ACTIVE` watchlist entries at reinstatement — `ERR_ACTIVE_WATCHLIST_ENTRIES`.
14. Estoppel gates — `ERR_ESTOPPEL_REQUIRED`.
15. Retainage-release inspection gate — `ERR_RETAINAGE_RELEASE_BLOCKED`.
16. Reporting-delinquency resolution gate — `ERR_RESOLUTION_BLOCKED`.
17. Duplicate statement period — `ERR_DUPLICATE_STATEMENT_PERIOD`.
18. Statement period alignment — `ERR_STATEMENT_PERIOD_MISALIGNED`.
19. Lease suite occupancy overlap — `ERR_LEASE_SUITE_OVERLAP`.
20. Insurance coverage window overlap — `ERR_COVERAGE_WINDOW_OVERLAP`.
21. Inspector schedule conflict — `ERR_INSPECTOR_SCHEDULE_CONFLICT`.
22. Duplicate reserve account type — `ERR_DUPLICATE_RESERVE_ACCOUNT`.
23. Extension window overlap or duplicate sequence — `ERR_EXTENSION_WINDOW_OVERLAP`.
24. Extension option count — `ERR_MAX_OPTIONS_REACHED`.
25. Assumption already in progress — `ERR_ASSUMPTION_IN_PROGRESS`.
26. Duplicate active estoppel — `ERR_DUPLICATE_ACTIVE_ESTOPPEL`.
27. Extension sequencing — `ERR_EXTENSION_SEQUENCE_VIOLATION`.
28. Force-placement necessity — `ERR_FORCE_PLACEMENT_NOT_NEEDED`.
29. Force-placed cancellation replacement — `ERR_FORCE_PLACED_CANCEL_BLOCKED`.
30. Extension exercise window — `ERR_EXTENSION_WINDOW_CLOSED`.
31. Delinquency threshold for default — `ERR_DELINQUENCY_THRESHOLD`.
32. Inspection freshness for assumptions — `ERR_INSPECTION_STALE`.
33. Assumption approval validity — `ERR_ASSUMPTION_APPROVAL_EXPIRED`.
34. Reserve funds sufficiency — `ERR_INSUFFICIENT_RESERVE_FUNDS`.
35. Property coverage minimum — `ERR_COVERAGE_BELOW_MINIMUM`.
36. Reserve target funding at reinstatement — `ERR_RESERVE_TARGET_SHORTFALL`.

Consider two illustrations of precedence. An approve decision attempted on a draw request that is no longer `SUBMITTED`, against a frozen reserve, and for more than the available funds reports `ERR_INVALID_STATE`, because the state check (step 7) precedes the frozen check (step 11) and the fiscal check (step 34). An extension exercise attempted with an open covenant breach and a closed window reports `ERR_OPEN_COVENANT_BREACH`, because step 9 precedes step 30.

## 3. Business Logic & Workflows

### 3.1. Boarding Borrowers, Loans, and Collateral

A `MasterServicer` onboards a borrowing entity with its `legal_name`, `tax_id`, and `contact_email`; the tax identifier must be unique across borrowers. Loans are then boarded against a borrower. The boarding payload names the `borrower_id` and a servicer `loan_number` unique across the book, fixes the `original_principal_cents` (strictly positive) and the annual `note_rate` (a fraction strictly greater than 0 and strictly less than 1, such as 0.06), and records the `origination_date` and the current `maturity_date`. An optional `current_balance_cents` — never negative — defaults to the original principal when omitted. At boarding the loan's `payment_status` starts `CURRENT`, its `servicing_status` starts `PERFORMING`, and `capitalized_advances_cents` starts at zero.

Boarding also pins the covenant regime. The `dscr_covenant_threshold` (strictly positive) and `ltv_covenant_threshold` (strictly greater than 0 and strictly less than 1) set the breach lines; the `dscr_basis` — `TTM` or `T3_ANNUALIZED` — selects which coverage variant the loan is tested under; and the `assumption_fee_basis` — `OUTSTANDING` or `ORIGINAL` — prices any future transfer. Until the first covenant calculation of each type runs, `current_dscr` and `current_ltv` remain null.

Collateral is attached property by property. Each property carries its `loan_id`, an `address`, a `property_type` of `OFFICE`, `RETAIL`, `INDUSTRIAL`, `MULTIFAMILY`, or `HOTEL`, and an initial strictly positive `appraised_value_cents` with its `appraisal_date`. Adding a property does not advance the loan's `version`. Later, a `MasterServicer` records a fresh appraisal by supplying a new `appraised_value_cents` and `appraisal_date`; the appraising operator's identity is stamped into `appraised_by_user_id`, where it becomes the segregation-of-duties anchor for LTV waivers, and the appraisal triggers the LTV reassessment and cascades described in §3.2, followed by a fresh risk-score evaluation.

The book is read through filtered listings. Loans list newest-created first and can be filtered by `borrower_id`, `servicing_status`, or `payment_status`, with a borrower seeing only its own loans; each loan's properties list beneath it; and the loan fetch exposes the computed `current_dscr`, `current_ltv`, and `days_delinquent` alongside the stored fields.

### 3.2. Quarterly Reporting and Covenant Surveillance

Reporting runs on calendar quarters. A borrower submits each statement for its own loan with a `statement_type` of `RENT_ROLL` or `OPERATING_STATEMENT` and a `period_start` and `period_end` that together must equal exactly one full calendar quarter — the quarter's first day through its last day, inclusive; a misaligned period is rejected with `ERR_STATEMENT_PERIOD_MISALIGNED` (HTTP 422). An operating statement must carry the quarter's `net_operating_income_cents`; a rent roll must carry `occupancy_pct` between 0 and 100 inclusive; omitting the field its type requires is a schema error answered with `ERR_INVALID_REQUEST`. The system derives the statement's `due_date` — fifteen days after `period_end` for a rent roll, forty-five days after for an operating statement — and sets `submitted_late` to true when the submission's clock time falls after that due date. Only one live statement may exist per loan, type, and quarter: while a row in `SUBMITTED` or `ACCEPTED` status exists for the same triple, a further submission is rejected with `ERR_DUPLICATE_STATEMENT_PERIOD`. Once a statement is `REJECTED`, a resubmission for the same period is permitted — the duplicate rule only blocks while a submitted or accepted row exists. A loan's statements list newest-created first and filter by `statement_type` and `status`.

Statements arrive in `SUBMITTED` status and are decided exclusively by a `MasterServicer` — a borrower attempting to review even its own statement draws `ERR_UNAUTHORIZED`. The review supplies a `decision` of `ACCEPT` or `REJECT`, and a rejection must carry a `rejection_reason`. Reviewing a statement that already stands `ACCEPTED` or `REJECTED` fails with `ERR_STATEMENT_ALREADY_REVIEWED`. Acceptance stamps the reviewing operator's identity into `reviewed_by_user_id`, the segregation-of-duties anchor for DSCR waivers. Rejection creates no covenant assessment and leaves the period open for resubmission.

Accepting an operating statement runs the DSCR covenant test. Annual debt service is computed as the loan's `original_principal_cents` multiplied by its `note_rate`, rounded half-up to whole cents. The income base is drawn only from `ACCEPTED` operating statements of the same loan: rejected statements never participate, each quarter contributes at most once, and quarters whose `period_start` precedes the loan's `origination_date` are ignored. For a loan covenanted on the `TTM` basis, annualized net operating income is the sum of the `net_operating_income_cents` of the four consecutive calendar quarters ending with the newly accepted statement's own quarter; if any of those four quarters lacks an accepted statement, the covenant is not computable and no assessment row is created at all. For a loan on the `T3_ANNUALIZED` basis, the annualized figure is the newly accepted quarter's net operating income multiplied by four, so the covenant is computable from the very first accepted quarter and reacts faster to recent performance. The resulting ratio — annualized net operating income divided by annual debt service, rounded half-up to four decimal places — becomes the assessment's `computed_value` and is echoed onto the loan as `current_dscr`, advancing the loan's `version`. A breach exists whenever the ratio is strictly less than the loan's `dscr_covenant_threshold`.

The LTV covenant, by contrast, is tested on collateral events rather than statements: a fresh appraisal (§3.1), or the capitalization or reversal of a protective advance (§3.5). The collateral base is the sum of `appraised_value_cents` across the loan's properties whose `appraisal_date` lies within twenty-four months of the current clock; appraisals older than twenty-four months are stale and contribute nothing. When no in-date appraisal exists the ratio is uncomputable — yet the assessment is still recorded, with `computed_value` null and `breach` set to true. Otherwise the ratio is the loan's `current_balance_cents` divided by the collateral base, rounded half-up to four decimal places, and a breach exists when it is strictly greater than the loan's `ltv_covenant_threshold`; the result refreshes the loan's `current_ltv`.

Every covenant test produces an assessment naming its `loan_id`, an `assessment_type` of `DSCR` or `LTV`, a `threshold_value` snapshotting the covenant threshold at test time, and the `assessed_at` clock time. A DSCR assessment points back to its source statement via `statement_id` and copies the loan's covenant basis into `basis`; for an LTV assessment both of those fields are null. An assessment that finds a breach opens in `OPEN` status; one that finds conformity stands `CONFORMING`. Conformity reaches backwards: a newly created conforming assessment automatically transitions every prior `OPEN` assessment of the same type for that loan to `CURED`. Each creation or cure re-evaluates the loan's servicing posture per §2.9 — an `OPEN` assessment drives a `PERFORMING` loan to `WATCHLIST`, and clearing the last open item lets a `WATCHLIST` loan return to `PERFORMING` — and triggers a fresh risk-score evaluation per §3.6. A loan's assessments list newest first by `assessed_at` and filter by `assessment_type` and `status`; each statement also exposes the assessments it sourced.

A `SpecialServicer` may waive an `OPEN` assessment, supplying a `waiver_reason`; the assessment moves to `WAIVED` and records the operator in `waived_by_user_id`, which stays null on every non-waived assessment. Waiving an assessment in any other status fails with `ERR_INVALID_STATE`. Segregation of duties forbids the waiver from being the operator of record upstream: for a DSCR assessment the acting `X-User-ID` must differ from the source statement's `reviewed_by_user_id`, and for an LTV assessment it must differ from the property's `appraised_by_user_id`; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A waiver re-evaluates the servicing posture and may let a `WATCHLIST` loan de-escalate to `PERFORMING`, de-elevating its reserves in the process.

### 3.3. Reserve Funding and the Disbursement Waterfall

A `MasterServicer` opens reserve accounts beneath a loan — at most one account per `account_type`, where the type is `TI_LC` or `REPLACEMENT`; a second account of a type the loan already holds is refused with `ERR_DUPLICATE_RESERVE_ACCOUNT`. Each account is opened with a `target_balance_cents` of zero or more, which later serves as the reinstatement funding gate of §3.6. A new account starts with `balance_cents`, `held_cents`, and `retained_cents` all at zero. Cash arrives through deposits of a strictly positive `amount_cents`, posted by either the borrower on its own loan or a `MasterServicer`; each deposit adds to the account's `balance_cents` and advances the reserve's `version`.

Three counters track an account's obligations beyond its raw `balance_cents`. `held_cents` is the sum of `amount_cents` across approved-but-unfunded, uncancelled draw requests. `retained_cents` accumulates retainage withheld on funded draws pending release. The derived `available_cents` is always the balance minus the held amount, an invariant that must never go negative. Two posture flags ride along: `elevated_retainage`, true while the loan's servicing posture is anything other than `PERFORMING`, and `disbursement_frozen`, true while the loan stands in `SPECIAL_SERVICING`. Both are set and cleared by the posture cascades of §3.6, and every such flip advances the affected reserve's `version`.

A borrower initiates a draw against a reserve of its own loan by supplying a `purpose` of `TENANT_IMPROVEMENT`, `LEASING_COMMISSION`, or `CAPITAL_REPAIR`; a non-empty `line_items` array in which each entry pairs a `description` with a strictly positive `amount_cents`; and the optimistic-concurrency token `expected_reserve_account_version` described in §2.8. An optional `retainage_pct` between 0 and 1 inclusive requests the withholding fraction and defaults to 0.10 when omitted. The request's `amount_cents` is derived as the sum of its line items, the request opens in `SUBMITTED` status with `funded_cents` and `retained_cents` at zero and `funded_at` null until funding occurs, and creating it advances the reserve's `version` — which is precisely why the concurrency token must be fresh.

Review of a draw, by a `MasterServicer` or `SpecialServicer`, applies a `decision` of `APPROVE` or `REJECT`. Approval requires the request to be `SUBMITTED` (anything else earns `ERR_INVALID_STATE`), the reserve unfrozen (a frozen reserve answers `ERR_RESERVE_DISBURSEMENTS_FROZEN`), and the request's `amount_cents` no greater than the reserve's `available_cents` — equality is acceptable — with shortfalls rejected as `ERR_INSUFFICIENT_RESERVE_FUNDS` (HTTP 422). Approval places a hold: the reserve's `held_cents` grows by the request's `amount_cents` and its `version` advances. Rejection carries no fiscal check — even an unaffordable request may be rejected — and leaves the reserve untouched. The borrower may cancel its own request while `SUBMITTED` with no side effects, or while `APPROVED`, which releases the hold by reducing the reserve's `held_cents` by the request's `amount_cents` and advancing the reserve's `version`; a borrower cancelling a request on another owner's loan fails with `ERR_OWNERSHIP_MISMATCH`. `FUNDED`, `REJECTED`, and `CANCELLED` are the terminal states of the draw lifecycle.

Funding an `APPROVED` request — again either servicer role — re-verifies the fiscal gate with one twist: the request's own hold counts as available to itself, so the check is that the request's `amount_cents` does not exceed the reserve's `available_cents` plus that same `amount_cents` — equivalently, that the reserve's cash still covers every outstanding hold. The frozen check applies at funding just as at review. Funding then runs the disbursement waterfall. When the reserve's `elevated_retainage` flag is set, the effective retainage fraction is the greater of the request's `retainage_pct` and a floor of 0.20; otherwise the requested fraction applies as given. Retainage is computed line by line: each line's withheld amount is that line's `amount_cents` multiplied by the effective fraction, rounded half-up to whole cents, and the line's disbursed amount is what remains. The request's `funded_cents` is the sum of the per-line disbursed amounts and its `retained_cents` the sum of the per-line withholdings — rounding each line first and then summing is mandatory, because summing first and rounding once yields different totals. The reserve's `held_cents` falls by the request's full `amount_cents`, its `balance_cents` falls by `funded_cents`, its `retained_cents` grows by the withheld total, its `version` advances, and the request's `funded_at` stamps the clock time of funding.

Withheld retainage is released by a `MasterServicer` only after proof of completed work: the request must stand `FUNDED` with `retained_cents` still positive (otherwise `ERR_INVALID_STATE`), and at least one property of the same loan must have a `COMPLETED` inspection whose `completed_at` is on or after the request's `funded_at` — lacking one, the release is refused with `ERR_RETAINAGE_RELEASE_BLOCKED`. On release the reserve's `balance_cents` falls by the retained amount, its `retained_cents` falls by the same amount, the request's own `retained_cents` returns to zero, and the reserve's `version` advances. A reserve's draw requests list beneath it, filterable by `status`.

### 3.4. Leasing Governance and Estoppel Certificates

A borrower drafts a lease against a property of its own loan — the creation payload carrying the `property_id` — supplying the `tenant_name`, a `suite_ref` identifying the space, the `commencement_date` and `expiry_date` — an inclusive occupancy interval in which the expiry may not precede the commencement — the strictly positive `base_rent_cents_monthly`, the strictly positive leased `sqft`, and the strictly positive `term_months`. The lease opens in `DRAFT` status, and the system immediately derives two flags: `lender_approval_required`, true whenever the monthly base rent exceeds 500,000 cents or the leased area exceeds 5,000 square feet or the term exceeds 60 months, and `estoppel_required`, which simply mirrors `lender_approval_required`. A lease meeting any of those three tests is a major lease, and a property's leases list beneath it, filterable by `status`.

Submission moves a `DRAFT` lease to `SUBMITTED`, and it is at submission — not drafting — that suite occupancy is policed: occupancy intervals are closed on both ends, so if the new lease's interval touches or overlaps the interval of any other lease with the same `suite_ref` on the same property standing in `SUBMITTED`, `APPROVED`, or `CONDITIONALLY_APPROVED`, the submission is rejected with `ERR_LEASE_SUITE_OVERLAP`. Submitting a lease not in `DRAFT` earns `ERR_INVALID_STATE`, and submitting outside the borrower's own chain earns `ERR_OWNERSHIP_MISMATCH`.

Either servicer role decides a submitted lease with a `decision` of `APPROVE`, `CONDITIONAL`, or `REJECT`. An approval may land on a lease in `SUBMITTED` or `CONDITIONALLY_APPROVED`; a conditional approval — which requires the servicer's `conditions` text — only on a `SUBMITTED` one; and a rejection on either of those two states. Any other starting state fails with `ERR_INVALID_STATE`. Every approval of an estoppel-required lease passes through the estoppel gate: the lease must hold an `EXECUTED` certificate whose `expires_at` is still in the future relative to the clock, otherwise the decision is refused with `ERR_ESTOPPEL_REQUIRED`. Because the gate is evaluated at decision time, a certificate that satisfied it once but has since expired no longer does. A borrower returns a `REJECTED` lease to `DRAFT` by revising it, optionally editing `base_rent_cents_monthly`, `sqft`, `term_months`, `commencement_date`, or `expiry_date`; revision clears any recorded `conditions` and recomputes both approval flags from the edited terms.

Estoppel certificates are requested by a `MasterServicer`, who supplies the tenant execution `due_date`; the new certificate is filed under its parent through the payload's `lease_id` and opens `PENDING`. A lease may hold at most one live certificate — requesting another while an unexpired `PENDING` or `EXECUTED` certificate exists for the lease is refused with `ERR_DUPLICATE_ACTIVE_ESTOPPEL`. The borrower executes a pending certificate on its own loan's lease, which stamps `executed_at` — null until that moment — with the clock time and sets `expires_at` exactly ninety days later. The clock sweep then ages certificates out along two paths: a certificate still `PENDING` once the clock passes its `due_date` becomes `EXPIRED`, and an `EXECUTED` one becomes `EXPIRED` once the clock passes its `expires_at`. `EXPIRED` is terminal — a fresh need for an estoppel is met by requesting a new record, and a lease's certificates list beneath it.

### 3.5. Collateral Oversight: Inspections and Insurance

Inspection capacity is registered by a `MasterServicer`: each inspector carries a `full_name`, a `license_no` unique across inspectors, and an `active` flag — the schedulable marker — defaulting to true. A `MasterServicer` then schedules an inspection on a property by naming an `inspector_id` and a half-open window running from `scheduled_start` (inclusive) to `scheduled_end` (exclusive, and strictly after the start). Conflicts are evaluated per inspector across that inspector's `SCHEDULED` inspections under half-open semantics: back-to-back assignments, one beginning exactly when another ends, are permitted, while any true overlap is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`. An inspector reads its own profile and its own schedule, the latter filterable by `status`; an inspector reading another inspector's schedule sees `ERR_NOT_FOUND` as usual.

Closing an inspection splits by role and by `outcome`. The assigned inspector — and only that inspector, with the check comparing `X-User-ID` against the inspection's `inspector_id` and mismatches drawing `ERR_OWNERSHIP_MISMATCH` — closes with outcome `COMPLETED`, supplying a `condition_rating` of `GOOD`, `FAIR`, `POOR`, or `CRITICAL` and optional free-text `findings`; the completion stamps `completed_at`, which remains null until then. A `MasterServicer` instead closes with outcome `CANCELLED`. Either way the inspection must still be `SCHEDULED`, else `ERR_INVALID_STATE`. A completion rated `POOR` or `CRITICAL` immediately creates a watchlist entry with criterion `POOR_INSPECTION` whose `source_ref` points at the inspection, which re-evaluates the loan's servicing posture — potentially pushing a `PERFORMING` loan to `WATCHLIST` and elevating retainage on its reserves — and every completion also refreshes the loan's risk score per §3.6. A property's inspections list beneath it, filterable by `status`.

Insurance is tracked per property and per `coverage_type` of `PROPERTY`, `LIABILITY`, or `FLOOD`. A borrower posts a policy on its own collateral with a strictly positive `coverage_amount_cents` and a closed coverage interval from `start_date` to `end_date` inclusive, the end not preceding the start. Two guards apply at posting. Fiscally, a `PROPERTY` policy's coverage must be at least the loan's `current_balance_cents`, else `ERR_COVERAGE_BELOW_MINIMUM` (HTTP 422). Referentially, the new policy's closed interval may not touch or overlap the interval of any other `ACTIVE`, non-force-placed policy of the same coverage type on the same property — touching dates count as overlap — else `ERR_COVERAGE_WINDOW_OVERLAP`; force-placed policies never participate in that check, so they can never block a borrower's replacement coverage. Posted policies are ordinary borrower coverage, with `force_placed` false and `premium_advance_cents` zero, and they open `ACTIVE`; the clock sweep moves a policy to `EXPIRED` once the clock passes its `end_date`, and if that expiry leaves no `ACTIVE` policy of the same coverage type covering the current moment, the sweep also opens a watchlist entry with criterion `INSURANCE_LAPSE` and re-evaluates the servicing posture. A property's policies list beneath it, filterable by `coverage_type` and `status`.

Cancellation is open to the borrower on its own chain and to the `SpecialServicer`. Any policy must still be `ACTIVE`, else `ERR_INVALID_STATE`, and a borrower cancelling outside its own chain earns `ERR_OWNERSHIP_MISMATCH`. A force-placed policy carries one further protection: it cannot be cancelled until another `ACTIVE`, non-force-placed policy of the same coverage type exists whose `start_date` is on or before the force-placed policy's own start date, otherwise `ERR_FORCE_PLACED_CANCEL_BLOCKED`. Cancelling a force-placed policy reverses its protective advance exactly once — the loan's `current_balance_cents` and `capitalized_advances_cents` each decrease by the recorded `premium_advance_cents`, the premium never being recomputed at cancellation — and advances the loan's `version`. Any cancellation then recomputes LTV: a conforming result auto-cures the loan's `OPEN` LTV assessments, and the servicing posture is re-evaluated. And if cancelling a non-force-placed policy leaves the property with no `ACTIVE` coverage of that type at all, an `INSURANCE_LAPSE` watchlist entry is created as well.

When coverage lapses and the borrower does not cure it, a `SpecialServicer` force-places a policy by naming only the `coverage_type`. Force-placement is refused while any `ACTIVE`, non-force-placed policy of that coverage type already covers the property at the current moment — `ERR_FORCE_PLACEMENT_NOT_NEEDED`. The protective advance is then capitalized in a single pinned pass, its order fixed to break the apparent circularity between premium and balance: first the loan's current balance is snapshotted; second, the premium is computed as that snapshot multiplied by two percent (0.02), rounded half-up to whole cents; third, the loan's `current_balance_cents` grows by the premium; fourth, the same premium accumulates into `capitalized_advances_cents`; fifth, the new policy's `coverage_amount_cents` is set to the pre-placement snapshot — not the grown balance — and its `premium_advance_cents` records the premium. The policy is flagged `force_placed` and written for a term of 365 days from placement. Exactly one LTV recomputation follows, which may open an LTV breach, with the servicing posture and the risk score re-evaluated behind it.

### 3.6. Delinquency, the Watchlist, and Special Servicing

The payment dimension moves under servicer action: either servicer role may set a `CURRENT` loan to `DELINQUENT`, return a `DELINQUENT` loan to `CURRENT`, or move a `DELINQUENT` loan to `DEFAULT`, each by naming a `to_status`. Marking a loan delinquent stamps `delinquent_since` with the clock time; curing back to `CURRENT` clears it to null. The loan's `days_delinquent` is derived on read — the whole days elapsed since `delinquent_since`, meaning the elapsed seconds divided by 86,400 and rounded down, while the loan stands `DELINQUENT` or `DEFAULT`, and zero otherwise. Declaring `DEFAULT` is gated: the loan must have been delinquent for at least sixty days, otherwise the transition is refused with `ERR_DELINQUENCY_THRESHOLD` (HTTP 422). Every payment-dimension change advances the loan's `version` and triggers a fresh risk-score evaluation. The fourth payment state, `MATURITY_DEFAULT`, is reachable only through the clock sweep of §3.7 and never through operator action; `DEFAULT` and `MATURITY_DEFAULT` are terminal for this dimension, and a maturity default leaves the servicing dimension untouched.

The watchlist is the system's early-warning surface. Each entry carries a `criterion` of `REPORTING_DELINQUENCY`, `POOR_INSPECTION`, `INSURANCE_LAPSE`, `MATURITY_RISK`, or `RISK_SCORE`; a human-readable `source_ref` pointing at the origin (a period-and-type label such as 'period 2026Q2 OPERATING_STATEMENT' for reporting gaps, or an inspection id for condition findings); and a `resolved_at` that stays null while the entry remains `ACTIVE`. Risk-driven entries additionally record `risk_score_at_creation` — null on entries of every other criterion — and an `escalation_review` flag, set when the creation score was 85 or higher. A loan's entries list beneath it, filterable by `status` and `criterion`.

Behind the `RISK_SCORE` entries stands a composite score, recomputed after every covenant assessment creation, every inspection completion, every payment-status change, and during every clock sweep. The score sums five parts. The coverage component reads the loan's `current_dscr`: 0 when it is at least 1.25, 15 when below 1.25 but at least 1.10, 30 when below 1.10 but at least 1.00, 45 when below 1.00, and 10 when no DSCR has ever been computed. The delinquency component reads `days_delinquent`: 0 when the loan is not delinquent, 10 from one through twenty-nine days, 20 from thirty through fifty-nine days, and 35 at sixty days or more. The property component reads the most recently completed inspection across the loan's properties: 0 for `GOOD`, 5 for `FAIR`, 15 for `POOR`, 25 for `CRITICAL`, and 5 when no completed inspection exists. The collateral component reads `current_ltv`: 0 when below 0.65, 10 when at least 0.65 but below 0.75, 20 when at least 0.75 but below 0.85, 30 at 0.85 or above, and 10 when no LTV has ever been computed. Finally, a synergy supplement of 10 points is added whenever the loan is at least thirty days delinquent and its current DSCR is below 1.00. The total is capped at 100. Whenever the total reaches 70 or more and the loan has no currently `ACTIVE` risk-score entry, the system opens an entry with criterion `RISK_SCORE`, recording the score in `risk_score_at_creation` and flagging `escalation_review` when the score is 85 or higher.

Resolution and escalation are the two exits from `ACTIVE`. Either servicer role resolves an entry, moving it to `RESOLVED` and stamping `resolved_at` with the clock time; an entry with criterion `REPORTING_DELINQUENCY`, however, can be resolved only once an `ACCEPTED` statement exists for the entry's period and statement type — an earlier attempt is refused with `ERR_RESOLUTION_BLOCKED`. A `MasterServicer` escalates an `ACTIVE` entry of a `WATCHLIST` loan; acting on an entry that is not `ACTIVE` earns `ERR_INVALID_STATE`. Resolving the last active item lets the servicing posture fall back toward `PERFORMING`.

Escalation is the point of transfer into workout. The entry becomes `ESCALATED`, the loan moves `WATCHLIST` → `SPECIAL_SERVICING`, and the cascade is exact: every reserve account of the loan sets `disbursement_frozen` to true while `elevated_retainage` stays on; every still-`SUBMITTED` draw request on those reserves moves to `REJECTED`, having never held funds; every `APPROVED` draw moves to `CANCELLED` with its hold released back out of `held_cents`; and every `AVAILABLE` extension option moves to `SUSPENDED`. There is no direct path from `PERFORMING` to `SPECIAL_SERVICING` — a loan must pass through `WATCHLIST` first. The posture's automatic transitions bracket this manual one: the moment any covenant assessment stands `OPEN` or any watchlist entry stands `ACTIVE`, a `PERFORMING` loan moves to `WATCHLIST` and every reserve of the loan flips `elevated_retainage` on, and when no open assessment and no active entry remain, a `WATCHLIST` loan returns to `PERFORMING` and the flags flip back off — each flip advancing the affected reserves' `version`.

Coming back from special servicing is a `SpecialServicer` act guarded by four gates, evaluated in the pipeline order of §2.10: no `OPEN` covenant assessment may remain on the loan (else `ERR_OPEN_COVENANT_BREACH`); the loan must be `CURRENT` (else `ERR_LOAN_NOT_CURRENT`); no `ACTIVE` watchlist entry may remain (else `ERR_ACTIVE_WATCHLIST_ENTRIES`); and every reserve account of the loan must be funded to target — `balance_cents` at least `target_balance_cents` — else `ERR_RESERVE_TARGET_SHORTFALL` (HTTP 422). Reinstatement returns the loan to `PERFORMING`, unfreezes and de-elevates every reserve, and restores each suspended extension option to `AVAILABLE` when its exercise window end is still at or beyond the current clock, lapsing it to `EXPIRED` when the window has already passed.

### 3.7. Transfers, Extensions, and the Passage of Time

An assumption lets a new borrowing entity take over a loan. The borrower opens a request on its own loan with the `proposed_assumptor_name`, the `proposed_assumptor_tax_id`, and the `proposed_net_worth_cents` (zero or more), plus the optimistic-concurrency token `expected_loan_version` of §2.8; creating the request itself advances the loan's `version`. A loan may host only one non-terminal request at a time — a further request while one stands `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` is refused with `ERR_ASSUMPTION_IN_PROGRESS`. Either servicer role then moves the request `SUBMITTED` → `UNDER_REVIEW`, and a loan's requests list beneath it, filterable by `status`.

The approval decision is the most heavily gated action in the system. In pipeline order: the request must stand `UNDER_REVIEW` (else `ERR_INVALID_STATE`); no `OPEN` covenant assessment may exist on the loan (else `ERR_OPEN_COVENANT_BREACH`); the loan must be `CURRENT` (else `ERR_LOAN_NOT_CURRENT`); every lease with `estoppel_required` must hold an `EXECUTED`, unexpired certificate (else `ERR_ESTOPPEL_REQUIRED`); and every property of the loan must have a `COMPLETED` inspection whose `completed_at` lies within twelve months of the clock with a rating other than `CRITICAL` (else `ERR_INSPECTION_STALE`). Approval prices the transfer according to the loan's `assumption_fee_basis`. On the `OUTSTANDING` basis the fee is one percent of the loan's `current_balance_cents`, rounded half-up to whole cents, then clamped to never less than 1,000,000 cents and never more than 25,000,000 cents. On the `ORIGINAL` basis the fee is one-half of one percent of the `original_principal_cents`, rounded half-up to whole cents, plus a flat 25,000 cents, and this variant is never clamped. The computed `fee_cents` — null until this point — the `decided_at` clock time, and an `approval_expires_at` exactly sixty days after the decision are all stamped at approval. Rejection instead requires a `rejection_reason` and stamps `decided_at` alone.

Execution is guarded afresh: the request must stand `APPROVED` (else `ERR_INVALID_STATE`); the clock must not have passed `approval_expires_at` (else `ERR_ASSUMPTION_APPROVAL_EXPIRED`); and the covenant and currency gates are re-checked at execution, so an `OPEN` assessment or a non-`CURRENT` loan fails with `ERR_OPEN_COVENANT_BREACH` or `ERR_LOAN_NOT_CURRENT` respectively. Execution registers a brand-new borrower from the proposed assumptor's name and tax identifier, reassigns the loan's `borrower_id` to that new borrower, advances the loan's `version`, and deems the recorded fee collected — no cash movement is modelled. The borrower may withdraw its own request while it stands `SUBMITTED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`; `REJECTED`, `EXECUTED`, and `WITHDRAWN` are terminal.

Maturity flexibility is sold in advance as extension options. A `MasterServicer` grants an option with an `option_seq` of at least 1, unique per loan; an inclusive exercise window from `exercise_window_start` to `exercise_window_end`, the end not before the start and strictly before the loan's current `maturity_date` at grant time; a strictly positive `extension_months` length; and a `fee_pct` of zero or more. A loan carries at most two options — a third is refused with `ERR_MAX_OPTIONS_REACHED` (HTTP 422) — and overlapping closed windows or a duplicated sequence number on the same loan are refused with `ERR_EXTENSION_WINDOW_OVERLAP`. Options open `AVAILABLE` and list beneath the loan.

Exercising is the borrower's act on its own loan, gated in pipeline order: the option must stand `AVAILABLE` (else `ERR_INVALID_STATE`); no `OPEN` covenant assessment may exist (else `ERR_OPEN_COVENANT_BREACH`); the loan must be `CURRENT` (else `ERR_LOAN_NOT_CURRENT`); an option with `option_seq` greater than 1 may be exercised only once the option with the preceding sequence number stands `EXERCISED` (else `ERR_EXTENSION_SEQUENCE_VIOLATION`); and the clock must fall inside the inclusive window from `exercise_window_start` to `exercise_window_end` (else `ERR_EXTENSION_WINDOW_CLOSED`). Exercising records `exercised_fee_cents` — null until the option is exercised — equal to the loan's `current_balance_cents` multiplied by the option's `fee_pct`, rounded half-up to whole cents, and pushes the loan's `maturity_date` forward by `extension_months` calendar months — clamping the day of month to the target month's last day when that day does not exist there — advancing the loan's `version`. Time and posture move options through their remaining transitions: the clock sweep lapses an `AVAILABLE` option whose `exercise_window_end` has passed to `EXPIRED`; the special-servicing cascade of §3.6 moves every `AVAILABLE` option to `SUSPENDED`; and reinstatement restores each suspended option to `AVAILABLE` when its window end is still at or beyond the clock, otherwise lapsing it to `EXPIRED`. `EXERCISED` and `EXPIRED` are terminal.

All time-based transitions flow from the logical servicing clock of §2.4. Setting the clock to a supplied `to_iso8601` instant — a capability restricted to the two servicer roles, answered with the resulting `current_utc` — runs a deterministic sweep whose steps execute in this exact order on every advance:

1. Insurance expiry: every policy whose `end_date` has passed moves `ACTIVE` → `EXPIRED`, and an `INSURANCE_LAPSE` watchlist entry opens wherever a coverage type on a property now lacks `ACTIVE` coverage at the current moment.
2. Estoppel expiry: certificates still `PENDING` past their `due_date`, and `EXECUTED` ones past their `expires_at`, become `EXPIRED`.
3. Extension option expiry: options still `AVAILABLE` past their `exercise_window_end` become `EXPIRED`.
4. Reporting delinquency: for every expected statement — every calendar quarter of every loan whose `period_start` is on or after the loan's `origination_date` and whose computed `due_date` has passed — that has no `ACCEPTED` statement and no existing `ACTIVE` reporting-delinquency entry for that loan, quarter, and statement type, a `REPORTING_DELINQUENCY` entry is created.
5. Maturity risk: any loan whose maturity lies between zero and 180 days ahead of the clock inclusive, with `current_balance_cents` still positive, no `EXERCISED` extension option, and no `ACTIVE` maturity-risk entry, gains a `MATURITY_RISK` entry.
6. Maturity default: loans at or past `maturity_date` with `current_balance_cents` still positive and a payment status of `CURRENT` or `DELINQUENT` move to `MATURITY_DEFAULT`.
7. Risk scores are re-evaluated for every loan, and then servicing postures are re-evaluated for every loan.

Entry creation throughout the sweep is idempotent per loan, criterion, and originating source: advancing the clock across the same conditions twice never duplicates an entry.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new records to a collection — borrowers, loans, properties, financial statements, reserve accounts, disbursement requests, leases, estoppel certificates, inspectors, inspections, insurance policies (including force-placed ones), assumption requests, extension options, and reserve deposits — return `201 Created`. Operations that modify an existing resource's state, as well as all reads, return `200 OK`. The table below summarizes the HTTP contract only; request payloads, derived fields, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/borrowers` | Onboard a borrower | MasterServicer |
| GET | `/borrowers/{id}` | Fetch a borrower | MasterServicer, SpecialServicer, Borrower |
| POST | `/loans` | Board a loan | MasterServicer |
| GET | `/loans` | List loans, newest `created_at` first; filterable; a Borrower sees only its own | MasterServicer, SpecialServicer, Borrower |
| GET | `/loans/{id}` | Fetch a loan including computed `current_dscr`, `current_ltv`, and `days_delinquent` | MasterServicer, SpecialServicer, Borrower |
| POST | `/loans/{id}/payment-status` | Transition the payment dimension (`DELINQUENT`, `CURRENT`, `DEFAULT`) | MasterServicer, SpecialServicer |
| POST | `/loans/{id}/reinstate` | Return a loan from `SPECIAL_SERVICING` to `PERFORMING` | SpecialServicer |
| POST | `/loans/{id}/properties` | Add a collateral property | MasterServicer |
| GET | `/loans/{id}/properties` | List the properties of a loan | MasterServicer, SpecialServicer, Borrower |
| GET | `/properties/{id}` | Fetch a property | MasterServicer, SpecialServicer, Borrower |
| POST | `/properties/{id}/appraise` | Record a new appraisal; triggers LTV reassessment | MasterServicer |
| POST | `/loans/{id}/financial-statements` | Submit a quarterly statement | Borrower |
| GET | `/loans/{id}/financial-statements` | List statements of a loan, newest `created_at` first | MasterServicer, SpecialServicer, Borrower |
| GET | `/financial-statements/{id}` | Fetch a statement | MasterServicer, SpecialServicer, Borrower |
| POST | `/financial-statements/{id}/review` | Accept or reject a submitted statement | MasterServicer |
| GET | `/financial-statements/{id}/covenant-assessments` | List the assessments sourced from this statement | MasterServicer, SpecialServicer, Borrower |
| GET | `/loans/{id}/covenant-assessments` | List assessments of a loan, newest `assessed_at` first | MasterServicer, SpecialServicer, Borrower |
| POST | `/covenant-assessments/{id}/waive` | Waive an `OPEN` assessment (segregation of duties enforced) | SpecialServicer |
| POST | `/loans/{id}/reserve-accounts` | Open a reserve account, one per type per loan | MasterServicer |
| GET | `/reserve-accounts/{id}` | Fetch a reserve including balance, held, retained, and available amounts | MasterServicer, SpecialServicer, Borrower |
| GET | `/loans/{id}/reserve-accounts` | List the reserve accounts of a loan | MasterServicer, SpecialServicer, Borrower |
| POST | `/reserve-accounts/{id}/deposits` | Fund a reserve | MasterServicer, Borrower |
| POST | `/reserve-accounts/{id}/disbursement-requests` | Request a draw (optimistic-concurrency guarded) | Borrower |
| GET | `/reserve-accounts/{id}/disbursement-requests` | List the draw requests of a reserve | MasterServicer, SpecialServicer, Borrower |
| POST | `/disbursement-requests/{id}/review` | Approve (placing a hold) or reject a draw | MasterServicer, SpecialServicer |
| POST | `/disbursement-requests/{id}/fund` | Fund an approved draw (waterfall and retainage) | MasterServicer, SpecialServicer |
| POST | `/disbursement-requests/{id}/cancel` | Cancel a `SUBMITTED` or `APPROVED` request, releasing any hold | Borrower |
| POST | `/disbursement-requests/{id}/release-retainage` | Release withheld retainage after verifying inspection | MasterServicer |
| POST | `/properties/{id}/leases` | Create a lease in `DRAFT` | Borrower |
| GET | `/properties/{id}/leases` | List the leases of a property | MasterServicer, SpecialServicer, Borrower |
| GET | `/leases/{id}` | Fetch a lease | MasterServicer, SpecialServicer, Borrower |
| POST | `/leases/{id}/submit` | Submit a lease for lender review (suite-overlap checked here) | Borrower |
| POST | `/leases/{id}/decide` | `APPROVE`, `CONDITIONAL`, or `REJECT` a submitted lease | MasterServicer, SpecialServicer |
| POST | `/leases/{id}/revise` | Return a `REJECTED` lease to `DRAFT` with optional edits | Borrower |
| POST | `/leases/{id}/estoppels` | Request an estoppel certificate | MasterServicer |
| GET | `/leases/{id}/estoppels` | List the estoppel certificates of a lease | MasterServicer, SpecialServicer, Borrower |
| POST | `/estoppels/{id}/execute` | Execute a pending estoppel | Borrower |
| POST | `/inspectors` | Register an inspector | MasterServicer |
| GET | `/inspectors/{id}` | Fetch an inspector | MasterServicer, SpecialServicer, Inspector |
| GET | `/inspectors/{id}/inspections` | List an inspector's schedule; an Inspector sees only its own | MasterServicer, SpecialServicer, Inspector |
| POST | `/properties/{id}/inspections` | Schedule an inspection (inspector conflict checked) | MasterServicer |
| GET | `/properties/{id}/inspections` | List the inspections of a property | MasterServicer, SpecialServicer, Borrower |
| POST | `/inspections/{id}/close` | Complete (assigned inspector) or cancel (servicer) an inspection | MasterServicer, Inspector |
| POST | `/properties/{id}/insurance-policies` | Post a coverage policy | Borrower |
| GET | `/properties/{id}/insurance-policies` | List the policies of a property | MasterServicer, SpecialServicer, Borrower |
| POST | `/insurance-policies/{id}/cancel` | Cancel an active policy; force-placed requires replacement coverage and reverses the advance | Borrower, SpecialServicer |
| POST | `/properties/{id}/force-place-insurance` | Force-place coverage and capitalize the protective advance | SpecialServicer |
| POST | `/loans/{id}/assumption-requests` | Request a loan assumption (optimistic-concurrency guarded) | Borrower |
| GET | `/loans/{id}/assumption-requests` | List the assumption requests of a loan | MasterServicer, SpecialServicer, Borrower |
| POST | `/assumption-requests/{id}/start-review` | Move a request to `UNDER_REVIEW` | MasterServicer, SpecialServicer |
| POST | `/assumption-requests/{id}/decide` | Approve (all gates, fee computed) or reject a request | MasterServicer, SpecialServicer |
| POST | `/assumption-requests/{id}/execute` | Execute an approved assumption, transferring the borrower | MasterServicer, SpecialServicer |
| POST | `/assumption-requests/{id}/withdraw` | Withdraw a non-terminal request | Borrower |
| POST | `/loans/{id}/extension-options` | Grant an extension option (at most two, non-overlapping windows) | MasterServicer |
| GET | `/loans/{id}/extension-options` | List the extension options of a loan | MasterServicer, SpecialServicer, Borrower |
| POST | `/extension-options/{id}/exercise` | Exercise an option inside its window | Borrower |
| GET | `/loans/{id}/watchlist-entries` | List the watchlist entries of a loan | MasterServicer, SpecialServicer, Borrower |
| POST | `/watchlist-entries/{id}/resolve` | Resolve an `ACTIVE` entry (criterion-gated for reporting delinquency) | MasterServicer, SpecialServicer |
| POST | `/watchlist-entries/{id}/escalate` | Escalate an entry, transferring the loan to `SPECIAL_SERVICING` | MasterServicer |
| POST | `/_clock/set_current_utc` | Set the logical clock, running the full deterministic sweep in pinned order | MasterServicer, SpecialServicer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue enumerates only identifiers and status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STATEMENT_ALREADY_REVIEWED` | 409 |
| `ERR_OPEN_COVENANT_BREACH` | 409 |
| `ERR_LOAN_NOT_CURRENT` | 409 |
| `ERR_RESERVE_DISBURSEMENTS_FROZEN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ACTIVE_WATCHLIST_ENTRIES` | 409 |
| `ERR_ESTOPPEL_REQUIRED` | 409 |
| `ERR_RETAINAGE_RELEASE_BLOCKED` | 409 |
| `ERR_RESOLUTION_BLOCKED` | 409 |
| `ERR_DUPLICATE_STATEMENT_PERIOD` | 409 |
| `ERR_STATEMENT_PERIOD_MISALIGNED` | 422 |
| `ERR_LEASE_SUITE_OVERLAP` | 409 |
| `ERR_COVERAGE_WINDOW_OVERLAP` | 409 |
| `ERR_INSPECTOR_SCHEDULE_CONFLICT` | 409 |
| `ERR_DUPLICATE_RESERVE_ACCOUNT` | 409 |
| `ERR_EXTENSION_WINDOW_OVERLAP` | 409 |
| `ERR_MAX_OPTIONS_REACHED` | 422 |
| `ERR_ASSUMPTION_IN_PROGRESS` | 409 |
| `ERR_DUPLICATE_ACTIVE_ESTOPPEL` | 409 |
| `ERR_EXTENSION_SEQUENCE_VIOLATION` | 409 |
| `ERR_FORCE_PLACEMENT_NOT_NEEDED` | 409 |
| `ERR_FORCE_PLACED_CANCEL_BLOCKED` | 409 |
| `ERR_EXTENSION_WINDOW_CLOSED` | 409 |
| `ERR_DELINQUENCY_THRESHOLD` | 422 |
| `ERR_INSPECTION_STALE` | 409 |
| `ERR_ASSUMPTION_APPROVAL_EXPIRED` | 409 |
| `ERR_INSUFFICIENT_RESERVE_FUNDS` | 422 |
| `ERR_COVERAGE_BELOW_MINIMUM` | 422 |
| `ERR_RESERVE_TARGET_SHORTFALL` | 422 |

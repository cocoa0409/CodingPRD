# Securities Lending Collateral API — Product Requirements Document

## 1. Introduction

A custodian securities lending desk sits between two constituencies with opposite needs. Beneficial owners — pension funds, asset managers, insurance portfolios — hold large inventories of equities and bonds and want to earn incremental revenue by lending them out, without giving up the ability to sell or vote their positions. Borrowers — broker-dealers, hedge funds, market makers — need to borrow specific securities to cover fails, short positions, and settlement obligations, and they post cash or other securities as collateral in return. The desk in the middle earns a spread for sourcing inventory, negotiating rates, managing collateral daily, recalling loans when owners need their shares back, reinvesting cash collateral, and answering to regulators. Every one of those activities is a place where money can be lost quietly: a miscounted reservation, a margin call issued a day late, a rebate rounded the wrong way, a default whose collateral was released the morning before.

This document specifies a REST API, mounted under `/api`, that operates the full lending program: lendable-inventory and borrower-demand matching, rate negotiation, collateral margining with daily mark-to-market, recalls and buy-ins, counterparty credit limits with segregation of duties, cash-collateral reinvestment, a revenue ledger with month-end revenue splits to beneficial owners, and regulatory reporting. Four desk roles (`DeskTrader`, `RiskOfficer`, `OpsSettler`, `DeskAdmin`) and two external roles (`BorrowerRep`, `OwnerRep`) share the system under strict segregation of duties: the trader who requests a credit-limit override can never approve it, and the settler who finalizes a regulatory report can never file it. All date- and time-sensitive behavior reads a single logical clock rather than the wall clock, so the desk's daily and monthly epochs are deterministic and replayable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If `X-User-Role` is absent or is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is valid but not permitted on the target endpoint, the request is rejected with `ERR_FORBIDDEN`. The six roles, spelled exactly as the API expects them, are:

- `DeskTrader` — the custodian's lending-desk trader: matches demand to inventory, negotiates and books loans, manages the collateral mix, invests cash collateral, executes buy-ins, and requests (but never approves) credit-limit overrides.
- `BorrowerRep` — a borrower-side representative. **This role is entity-backed:** when `X-User-Role` is `BorrowerRep`, `X-User-ID` is the `id` of the acting `Borrower`. Ownership checks on any resource that references a borrower compare the resource's `borrower_id` foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.
- `OwnerRep` — a beneficial-owner representative. **This role is also entity-backed:** when `X-User-Role` is `OwnerRep`, `X-User-ID` is the `id` of the acting `BeneficialOwner`, and ownership checks compare the resource's `owner_id` foreign key to `X-User-ID`.
- `RiskOfficer` — counterparty risk: suspends, resumes, and defaults borrowers; suspends, resumes, and offboards owners; approves or rejects limit overrides (never their own requests); declares default on escalated margin calls.
- `OpsSettler` — operations and settlement: runs the daily mark-to-market and the month-end close, marks reinvestment NAVs, drafts and finalizes regulatory reports (never files them).
- `DeskAdmin` — desk administrator: maintains the security master and price feed, onboards counterparties, sets the logical clock, and files finalized regulatory reports (never finalizes them).

For the four desk-side roles — `DeskTrader`, `RiskOfficer`, `OpsSettler`, and `DeskAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `requested_by_user_id` and `decided_by_user_id` on a `LimitOverride`, or as `finalized_by_user_id` and `filed_by_user_id` on a `RegulatoryReport`) but does not compare it to any entity's `id` for ownership purposes.

Entity-backed scoping extends to list reads. When a `BorrowerRep` or `OwnerRep` queries a list endpoint that supports a filter on their backing foreign key (for example, a `BorrowerRep` listing loans with the `borrower_id` filter, or an `OwnerRep` listing positions with the `owner_id` filter), they must pass their own `id` as that filter value; passing another party's `id` is rejected with `ERR_FORBIDDEN`. If the filter is omitted entirely, the result set is automatically scoped to the caller's own `id`.

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

### 2.3. Pagination and List Filtering

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

List endpoints additionally accept resource-specific equality filters. Securities filter by `status`; beneficial owners by `status`; borrowers by `status`; limit overrides by `borrower_id` and `status`; lendable positions by `owner_id`, `security_id`, and `status`; borrow requests by `borrower_id`, `security_id`, and `status`; loans by `owner_id`, `borrower_id`, `security_id`, `position_id`, `borrow_request_id`, and `status`; collateral pledges by `loan_id`, `pledge_security_id`, and `status`; margin calls by `loan_id` and `status`; recalls by `loan_id`, `owner_id`, and `status`; reinvestment tranches by `loan_id` and `status`; ledger entries by `loan_id`, `owner_id`, `period`, and `entry_type`; and regulatory reports by `period` and `status`. The entity-backed scoping rule of §2.1 applies to any of these filters that name the caller's backing foreign key.

### 2.4. The Logical Clock

All date- and time-sensitive logic in the system — accrual dates, margin-call due dates, recall deadlines, borrow-request expiry, override windows, period derivation — reads a single **logical clock**, never the server's wall clock. At server startup the logical clock is set to exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time under any circumstances. A `DeskAdmin` may advance or set the clock through a test-driving capability that accepts a `to_iso8601` timestamp and responds with the resulting `current_utc`. Every rule in this document that says "the current date" means the date portion of this logical clock.

### 2.5. Units of Account: Integer Cents and Basis Points

All monetary amounts are integer cents — prices, limits, collateral values, fees, rebates, ledger amounts, NAV marks. All rates, margins, haircuts, revenue shares, and utilization figures are integer basis points, where 10000 basis points equals 100 percent. Wherever a computation produces a fractional cent, the result is rounded **half-up** to whole integer cents; the sections below pin, for each calculation, the exact step at which that rounding happens, because rounding early and rounding late give different answers and the desk's choice is deliberate. Loan-fee, rebate, and reinvestment-income accruals all use a 360-day year as the day-count basis.

### 2.6. Common Resource Properties and Optimistic Concurrency

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, an ISO 8601 UTC timestamp of the last modification; and `version`, an integer that increments by one with every mutation of the resource. Two resource types are exceptions: a `RevenueLedgerEntry` and a `PeriodClose` each carry only `id` and `created_at` — both `updated_at` and `version` are absent from them. All side effects of a mutation are applied atomically within the same request; any read afterwards observes the complete cascade.

Two write operations participate in **optimistic concurrency control** against a loan's `version`, and both name the same input field. Amending a `BOOKED` loan's terms and substituting one of its collateral pledges each require the request to carry `expected_loan_version`, a non-optional field holding the loan `version` the client last observed. If the loan's current `version` has advanced beyond that value — because a counter, a return, a recall, a prior amendment, or any other mutation landed in between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a loan state it has not observed. Each successive amendment or substitution is individually legitimate under product semantics, so the stale writer is rejected on version rather than on state. No endpoint other than these two accepts a version field.

### 2.7. Validation Order and Error Selection

When several checks could fail on the same request, the server evaluates them in a fixed priority order and reports the first failure, so that an early failure is never masked by a later one. The order is:

1. **Authentication** — the `X-User-Role` header is present and names a declared role; otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the role appears in the endpoint's permitted roles; otherwise `ERR_FORBIDDEN`.
3. **Entity-backed scoping** — for `OwnerRep` and `BorrowerRep` callers, the caller's `X-User-ID` equals the `owner_id` or `borrower_id` of the resource acted on (or supplied in the body), and list filters follow the auto-scoping rule; otherwise `ERR_FORBIDDEN`.
4. **Request shape** — required fields are present, enum values are in range, quantities and amounts are positive, dates are well-formed ISO values, and cross-references are consistent (a loan's `security_id` must equal the referenced position's `security_id`, and a loan's `owner_id` must equal the position's `owner_id`); otherwise `ERR_VALIDATION`.
5. **Existence** — path identifiers are resolved left to right, then body foreign-key references; any miss is `ERR_NOT_FOUND`.
6. **State** — the target entity is in a state from which the requested transition exists; otherwise `ERR_INVALID_STATE`.
7. **Regulatory and safety gates** — a `HALTED` security blocks direct loan creation, matching, booking, and pledging that security as collateral (`ERR_SECURITY_HALTED`); a borrower that is not `ACTIVE` blocks matching and booking (`ERR_BORROWER_SUSPENDED`); an owner that is not `ACTIVE` blocks position creation, matching, and booking (`ERR_OWNER_SUSPENDED`); segregation-of-duties rules block override approval and report filing (`ERR_SOD_VIOLATION`).
8. **Structural rules** — at most one non-terminal recall per loan (`ERR_RECALL_ALREADY_OPEN`), no overlap between an approved override window and another approved window for the same borrower (`ERR_OVERRIDE_WINDOW_OVERLAP`), at most one open proposal per borrow request, an unresolved selector tie (`ERR_AMBIGUOUS_MATCH`), pledge-field consistency with the declared pledge type (`ERR_PLEDGE_TYPE_MISMATCH`), full-recall quantity equality (`ERR_VALIDATION`), and period-close uniqueness (`ERR_PERIOD_ALREADY_CLOSED`).
9. **Temporal windows** — a recall deadline strictly after its issue date and an extension that strictly raises the deadline (`ERR_RECALL_WINDOW_INVALID`), an override window whose start is strictly before its end (`ERR_INVALID_WINDOW`), and a borrow request not yet past its needed-by date (`ERR_REQUEST_EXPIRED`).
10. **Money and capacity rules** — credit utilization, forward capacity, inventory availability, margin sufficiency, return quantities, reinvestment bounds, counter-rate ceilings, substitution value, uninvested-cash coverage, and amendment gating, each with its own error code as described in §3.

### 2.8. Nested Resource Retrieval

Several endpoints nest one resource beneath another in the URL — a recall beneath a loan, a pledge substitution beneath both a loan and a pledge. The server resolves path identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before examining later identifiers or the request body. A substitution addressed to a non-existent loan therefore fails on the `loan_id` segment before the `pledge_id` segment is ever looked up, and a body-level foreign key that does not exist fails only after every path identifier has resolved. Single resources are addressed throughout by their own identifiers: securities by `security_id`, owners by `owner_id`, borrowers by `borrower_id`, positions by `position_id`, borrow requests by `request_id`, loans by `loan_id`, pledges by `pledge_id`, margin calls by `call_id`, recalls by `recall_id`, reinvestment tranches by `tranche_id`, ledger entries by `entry_id`, regulatory reports by `report_id`, limit overrides by `override_id`, and period closes by a `period_id` that is itself the `YYYY-MM` period string.

### 2.9. Counterparty Credit and the Utilization Gate

Each borrower carries a base `credit_limit_cents` and an `effective_limit_cents`: the effective limit equals the `new_limit_cents` of an `APPROVED` limit override whose window covers the current clock date, and otherwise falls back to `credit_limit_cents`. A borrower's `utilization_cents` is the sum of `market_value_cents` — outstanding quantity times the security's current marked price — across exactly that borrower's loans in `BOOKED` or `RECALLED` status; proposals still in negotiation do not count until they book. The `utilization_bps` is `utilization_cents` multiplied by 10000 and divided by `effective_limit_cents`, computed with integer floor division. Utilization is recomputed on borrower reads and whenever an override is approved or expires, and it gates booking as described in §3.4: a booking that would push the borrower's prospective utilization to 9000 basis points or more of the effective limit — ninety percent — is refused with `ERR_CREDIT_LIMIT_EXCEEDED`. The gate is inclusive: a prospective utilization of exactly 9000 basis points is blocked.

### 2.10. Forward Capacity Accounting on Lendable Positions

A lendable position's inventory is accounted day by day, not just at a point in time, because loans have terms. A loan's occupancy window runs from the current clock date through the current date plus its `term_days`, treated as a half-open interval: the start day counts, the end day does not, so a deal that starts on the day another deal's window ends does not overlap it. An open-term loan — one whose `term_days` is null — occupies every day from the current date onward. For any calendar day, the position's occupancy is its `quantity_on_loan` plus the quantities of all loans in `PROPOSED` or `COUNTERED` that were matched from this position and whose windows cover that day. Taking a new reservation — at direct loan creation or at match time — is rejected with `ERR_FORWARD_CAPACITY_EXCEEDED` if adding the new quantity would push occupancy above the position's `quantity_total` on any single day of the new loan's window; there is no buffer. Booking re-validates the same check against current occupancy, but the converting loan's own reservation is excluded and no new quantity is added, because moving quantity from the reserved bucket to the on-loan bucket is neutral for every day; a booking can therefore never fail capacity on account of its own reservation.

### 2.11. Margin Requirements and Collateral Valuation

Every booked loan carries a margin requirement expressed over its current market value. A loan collateralized by **cash** must hold posted collateral of at least 102 percent of market value — a margin of 10200 basis points; a loan collateralized by **securities** must hold at least 105 percent — 10500 basis points. Formally, `required_collateral_cents` is the loan's `outstanding_quantity` multiplied by the security's current `price_cents`, multiplied by the applicable margin in basis points and divided by 10000, rounded half-up to whole cents at that final multiplication only.

Posted collateral is valued pledge by pledge and then summed, and the rounding order is pinned: each pledge is rounded to whole cents first, and only then are the pledge values added. A cash pledge is worth its `amount_cents`. A securities pledge is worth its `quantity` multiplied by the pledged security's current `price_cents`, multiplied by 10000 minus the pledged security's `haircut_bps` and divided by 10000, rounded half-up to whole cents per pledge. Haircuts depend on the pledged security's asset class: 200 basis points for a government bond, 600 for a corporate bond, 1000 for an equity. Only pledges in `ACTIVE` status count toward `posted_collateral_cents`; `RELEASED`, `SUBSTITUTED`, and `SEIZED` pledges are excluded.

A loan's margin deficit is its `required_collateral_cents` minus its `posted_collateral_cents`. A strictly positive deficit is margin-call territory; a deficit of exactly zero is not — exact equality between posted and required is fully collateralized. Issuance of new margin calls happens only in the daily run (§2.12), while cure is evaluated continuously: after every pledge posting, substitution, release, price mark, or daily run in which posted collateral reaches or exceeds required collateral, every `OPEN` or `ESCALATED` call on the loan is cured. Cure is all-or-nothing — there is no partial cure.

### 2.12. The Daily Ops Run and the Month-End Close

Two batched checkpoints organize the desk's calendar; both are executed by an `OpsSettler`. The **daily mark-to-market run** processes the current clock date as one atomic batch: it posts provisional loan-fee accruals for securities-collateral loans, rebate accruals for cash-collateral loans, and provisional reinvestment-income accruals for invested tranches; it issues new margin calls where a deficit has appeared, refreshes the amounts of still-open calls, escalates overdue calls, and cures calls whose deficit has closed; it expires borrow requests whose needed-by date has passed; it fails recalls whose deadline has passed with delivery incomplete; and it expires approved limit overrides whose window has ended. The run is idempotent within a date: running it twice for the same date never double-accrues, never double-issues, and produces no duplicate ledger entries. Its response summarizes the batch with `as_of_date`, `loans_accrued`, `margin_calls_issued`, `margin_calls_cured`, `margin_calls_escalated`, `requests_expired`, `recalls_failed`, and `overrides_expired`.

The **month-end close** takes a `period` in `YYYY-MM` form and finalizes it: provisional fee accruals are replaced by authoritative final amounts with true-up entries, and the revenue-split waterfall runs per beneficial owner. A successful close creates a `PeriodClose` record for the period; a period can be closed only once. Price marking between runs is immediate — marking a new price recomputes pledge and loan market values at once — but margin-call *issuance* remains batched at the daily run.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Securities, Prices, and the Halt Switch

A `DeskAdmin` registers each lendable instrument as a `Security` with a unique `symbol`, an `asset_class` of `EQUITY`, `GOV_BOND`, or `CORP_BOND`, and an opening `price_cents`. The system derives the security's `haircut_bps` from its asset class — 200 basis points for `GOV_BOND`, 600 for `CORP_BOND`, 1000 for `EQUITY` — and the security enters the book in `LENDABLE` status. Prices move only through the desk's price feed: when a `DeskAdmin` marks a new `price_cents`, the system immediately recomputes the `marked_value_cents` of every `ACTIVE` collateral pledge referencing that security and the `market_value_cents` of every open loan in it, and the cure direction of the margin rule is evaluated against those new values; the issuance of new margin calls, however, waits for the next daily run.

Halting is the desk's circuit breaker. When a `DeskAdmin` halts a security, its status moves from `LENDABLE` to `HALTED` and a three-link cascade fires at once: every `SUBMITTED` or `MATCHED` borrow request for that security is cancelled; every loan proposal in `PROPOSED` or `COUNTERED` for that security is cancelled — including desk-initiated proposals not tied to any borrow request; and each cancelled proposal releases its reservation, decrementing `quantity_reserved` on the source position. While a security is `HALTED`, four operations are refused with `ERR_SECURITY_HALTED`: creating a direct loan proposal in it, matching a borrow request for it, booking a loan in it, and pledging it as collateral. Resuming returns the security to `LENDABLE` with no further side effects; halted securities are never purged, and their existing booked loans are unaffected by the halt itself.

### 3.2. Counterparties: Owners, Borrowers, and Lendable Inventory

A `DeskAdmin` onboards a `BeneficialOwner` with a `display_name`, a `revenue_share_bps` fixing the owner's share of monthly net lending revenue in basis points (6250, for instance, is 62.5 percent), and an `indemnification_opt_in` flag that decides whether the agent indemnifies this owner's loans against borrower default. New owners start `ACTIVE`. A `DeskAdmin` likewise onboards a `Borrower` with a `display_name` and a `credit_limit_cents`; the borrower's `effective_limit_cents` starts equal to `credit_limit_cents`, its utilization starts at zero, and its status starts `ACTIVE`.

Supply enters the program when an `OwnerRep` makes inventory lendable. The create payload carries the `owner_id` — which must equal the caller's `X-User-ID`, since an owner representative may only offer their own inventory — plus the `security_id`, a strictly positive `quantity_total`, and the owner's `min_fee_bps`, the minimum acceptable loan rate used for matching eligibility and ranking. A new position is `OPEN`. Three computed quantities track its engagement: `quantity_reserved` sums the quantities of loans in `PROPOSED` or `COUNTERED` matched from the position, `quantity_on_loan` sums the outstanding quantities of loans in `BOOKED` or `RECALLED` matched from it, and `quantity_available` is what remains — `quantity_total` minus `quantity_reserved` minus `quantity_on_loan`.

Owners retain day-to-day control of their own supply. An `OwnerRep` may suspend one of their positions, moving it from `OPEN` to `SUSPENDED`, and later resume it back to `OPEN`; both actions require the caller's `X-User-ID` to equal the position's `owner_id`. A `SUSPENDED` position cannot be matched or booked — attempts fail with `ERR_POSITION_SUSPENDED` — and an owner that is not `ACTIVE` blocks position creation, matching, and booking with `ERR_OWNER_SUSPENDED`. A `RiskOfficer` may suspend an owner (`ACTIVE` to `SUSPENDED`), which makes all of that owner's positions ineligible for new matches while existing loans continue unaffected, and may later resume the owner. Offboarding — from either `ACTIVE` or `SUSPENDED` to `OFFBOARDED` — is guarded: the owner must have no loans in `BOOKED` or `RECALLED`, and every position must show zero `quantity_on_loan` and zero `quantity_reserved`; otherwise the request is rejected with `ERR_OWNER_HAS_OPEN_LOANS`. A successful offboarding moves all of the owner's `OPEN` positions to `SUSPENDED`.

### 3.3. Demand: Borrow Requests, Matching, and the Selector

Demand enters when a `BorrowerRep` submits a `BorrowRequest` naming the `borrower_id` — again required to equal the caller's `X-User-ID` — the `security_id`, a strictly positive `quantity`, the `max_rate_bps` the borrower will pay as a fee on securities-collateral loans, the `collateral_type` the borrower will post (`CASH` or `SECURITIES`), and a `needed_by_date` beyond which the demand is stale. An optional `term_days` fixes the term in calendar days; omitting it — leaving `term_days` null — requests an open-term loan. A new request is `SUBMITTED`.

Matching is the `DeskTrader`'s craft. The trader may nominate a `position_id` explicitly or omit it and let the selector work. The selector considers only eligible positions — `OPEN` positions in the requested security whose owner is `ACTIVE`, whose `min_fee_bps` does not exceed the request's `max_rate_bps`, and whose forward capacity covers the requested quantity across the window from the current date through the current date plus the request's `term_days` — and ranks them by `min_fee_bps` ascending, then by `created_at` ascending, then by `quantity_total` descending. If no eligible position exists the match is rejected with `ERR_NO_INVENTORY`; if the three ranking keys still leave a tie at the top, the match is rejected with `ERR_AMBIGUOUS_MATCH`. Capacity failure surfaces as `ERR_FORWARD_CAPACITY_EXCEEDED`. Three further gates stand in front of every match: the borrower must be `ACTIVE` (`ERR_BORROWER_SUSPENDED`), the security must be `LENDABLE` (`ERR_SECURITY_HALTED`), and the request's `needed_by_date` must not be before the current clock date (`ERR_REQUEST_EXPIRED`).

A successful match creates a `Loan` in `PROPOSED` status — `rate_bps` set to the position's `min_fee_bps`, terms copied from the request, `borrow_request_id` pointing back at it — moves the request from `SUBMITTED` to `MATCHED`, and adds the requested quantity to the position's `quantity_reserved`. A borrow request carries at most one open proposal at a time: matching is defined only from `SUBMITTED`, so a `MATCHED` request cannot be matched again until its proposal is cancelled. Cancellation is the borrower's own action — the caller's `X-User-ID` must equal the request's `borrower_id`. Cancelling a `SUBMITTED` request simply closes it as `CANCELLED`. Cancelling a `MATCHED` request cascades: the linked proposal — whether `PROPOSED` or `COUNTERED` — is cancelled, and the position's `quantity_reserved` is decremented by the requested quantity. The same cascade runs when a proposal is cancelled from the loan side: the request returns from `MATCHED` to `SUBMITTED`, its reservation is released, and the demand re-opens for another match. Finally, the daily run expires demand: a request whose `needed_by_date` has fallen behind the current date moves from `SUBMITTED` to `EXPIRED` outright, or from `MATCHED` to `EXPIRED` with the same proposal-cancelling, reservation-releasing cascade. A request that lives to see its loan booked lands in `LOANED`.

### 3.4. The Negotiation Loop, Booking, and Loan Maintenance

The `DeskTrader` may also open a loan directly, without any borrow request, by naming the `owner_id`, `borrower_id`, `security_id`, the source `position_id`, a strictly positive `quantity`, the `collateral_type` (`CASH` or `SECURITIES`), a proposed `rate_bps`, and an optional `term_days` (null means open term). Cross-reference consistency is enforced: the loan's `security_id` must equal the referenced position's `security_id`, and its `owner_id` must equal the position's `owner_id`, or the create fails with `ERR_VALIDATION`. A halted security blocks the create with `ERR_SECURITY_HALTED`, and the forward-capacity rule of §2.10 is evaluated before the reservation is taken. The new loan is `PROPOSED` with `borrow_request_id` null, and the position's `quantity_reserved` grows by the loan's quantity.

Rate negotiation is a cycle, not a line. From `PROPOSED`, the borrower's side may counter — the `BorrowerRep` caller's `X-User-ID` must equal the loan's `borrower_id` — supplying a new `rate_bps` and flipping the loan to `COUNTERED`; when the loan descends from a borrow request, the countered rate may not exceed that request's `max_rate_bps`, or the counter is rejected with `ERR_RATE_ABOVE_MAX`. From `COUNTERED`, the `DeskTrader` may counter back, restoring `PROPOSED` with a new `rate_bps`. Each counter writes the supplied `rate_bps` onto the loan and increments its `version` by one, and the loop may repeat indefinitely until someone books, or someone cancels. Either party may cancel from `PROPOSED` or `COUNTERED` — `BorrowerRep` callers only against their own loans — which releases the position reservation and, for request-linked loans, returns the request to `SUBMITTED`.

Booking happens from either side of the loop: the `BorrowerRep` accepts a desk proposal out of `PROPOSED`, or the `DeskTrader` confirms a borrower counter out of `COUNTERED`. Both paths enforce the same battery of preconditions, evaluated in this order: the borrower must be `ACTIVE` (`ERR_BORROWER_SUSPENDED`); the owner must be `ACTIVE` (`ERR_OWNER_SUSPENDED`); the security must be `LENDABLE` (`ERR_SECURITY_HALTED`); the position must be `OPEN` (`ERR_POSITION_SUSPENDED`); the forward-capacity check must pass for the loan's window (`ERR_FORWARD_CAPACITY_EXCEEDED`) — remembering from §2.10 that the converting loan's own reservation is excluded, so this gate can only fail on competing occupancy; and the borrower's prospective utilization including this loan's market value must stay strictly below 9000 basis points of the effective limit, with exactly 9000 blocked (`ERR_CREDIT_LIMIT_EXCEEDED`). Booking's side effects mirror the reservation: the position's `quantity_reserved` decreases by the loan quantity while its `quantity_on_loan` increases by the same amount; the loan captures the security's current `price_cents` as its `original_price_cents`; a request-linked loan moves its borrow request from `MATCHED` to `LOANED`; and the loan's `version` increments.

Once booked, a loan's economics are tracked in computed fields. Its `outstanding_quantity` is the original `quantity` minus cumulative returned shares. Its `market_value_cents` is `outstanding_quantity` times the security's current `price_cents`. Its `required_collateral_cents` and `posted_collateral_cents` follow §2.11, and its `cash_uninvested_cents` is the total of its `ACTIVE` cash pledges minus the principal of its `INVESTED` reinvestment tranches. A second status dimension, `margin_status`, is computed rather than stored by writers: it reads `CALL_OPEN` exactly when a margin call in `OPEN` or `ESCALATED` exists for the loan, and `CURRENT` otherwise.

Two maintenance operations live on a booked loan, and both honor the concurrency contract of §2.6. A `DeskTrader` may amend a `BOOKED` loan's `rate_bps`, its `term_days`, or both, in a request that must carry `expected_loan_version`; a value that no longer matches the loan's current `version` is rejected with `ERR_STALE_VERSION`, and any amendment is refused outright while the loan's `margin_status` is `CALL_OPEN` — an open or escalated margin call blocks renegotiation with `ERR_MARGIN_CALL_OUTSTANDING`. A successful amendment increments the loan's `version` by one. Returns are the borrower's action: a `BorrowerRep` posts a return `quantity` against a `BOOKED` or `RECALLED` loan, which may not exceed the loan's `outstanding_quantity` (`ERR_RETURN_EXCEEDS_LOAN`). Each return reduces `outstanding_quantity` and increments the loan's `version`; while a recall is open on the loan, returns are absorbed by the recall first, as §3.7 describes. A return that brings `outstanding_quantity` to zero settles the loan — `BOOKED` or `RECALLED` alike, the loan moves to `SETTLED` — and fires the settlement cascade: the position's `quantity_on_loan` is decremented; every `ACTIVE` collateral pledge moves to `RELEASED`, returning cash pledges and driving `cash_uninvested_cents` to zero; every `INVESTED` reinvestment tranche is unwound at its `current_nav_cents` with a final income entry per tranche; and any margin calls still `OPEN` or `ESCALATED` are cured by the system as part of settlement.

### 3.5. Collateral Operations: Posting, Release, Substitution, and Margin Calls

Collateral arrives per loan. A `BorrowerRep` posts a pledge against a loan in `BOOKED` or `RECALLED` — a pledge against a loan in any other state is rejected with `ERR_INVALID_STATE` — declaring a `pledge_type` of `CASH` or `SECURITY`. The two types carry mutually exclusive payloads: a `CASH` pledge requires `amount_cents` and forbids `pledge_security_id` and `quantity`, while a `SECURITY` pledge requires `pledge_security_id` and `quantity` and forbids `amount_cents`; mixing them is rejected with `ERR_PLEDGE_TYPE_MISMATCH`. Pledging a halted security as collateral is refused with `ERR_SECURITY_HALTED`. Each pledge's `marked_value_cents` follows the per-pledge valuation of §2.11 — cash at face, securities net of haircut with per-pledge rounding — and a new pledge starts `ACTIVE`, immediately raising the loan's `posted_collateral_cents` and possibly curing open margin calls.

Releasing collateral is a `DeskTrader` action guarded in a fixed order. The loan must be `BOOKED` or `RECALLED` (`ERR_INVALID_STATE`). First, the post-release `posted_collateral_cents` must still be at least the loan's `required_collateral_cents` — a release that would open a deficit is rejected with `ERR_MARGIN_DEFICIT`. Second, and only after the margin check passes, releasing a `CASH` pledge requires the loan's `cash_uninvested_cents` to cover the released amount — cash that has been reinvested is not releasable, and the attempt is rejected with `ERR_INSUFFICIENT_UNINVESTED_CASH`. A successful release moves the pledge to `RELEASED` and recomputes the loan's posted collateral and uninvested cash.

Substitution replaces one pledge with another without a coverage gap. A `BorrowerRep` substitutes an `ACTIVE` pledge on a `BOOKED` or `RECALLED` loan with a payload carrying `expected_loan_version` — rejected with `ERR_STALE_VERSION` when the loan's `version` has advanced past it — plus the replacement's `pledge_type` and its type-appropriate fields (`amount_cents`, or `pledge_security_id` with `quantity`). The replacement's `marked_value_cents` must be at least the substituted pledge's `marked_value_cents`, or the substitution is rejected with `ERR_COLLATERAL_SHORTFALL`. A successful substitution moves the old pledge to `SUBSTITUTED`, creates the new pledge `ACTIVE`, increments the loan's `version` by one, and recomputes posted collateral.

Margin calls are the system's own creation; no endpoint makes one directly. When the daily run finds a strictly positive deficit on a `BOOKED` or `RECALLED` loan, it issues a `MarginCall` in `OPEN` status whose `amount_due_cents` equals that day's deficit and whose `issued_date` is the current clock date, with `due_date` one calendar day later. If an `OPEN` call already exists, the run refreshes its `amount_due_cents` to the current deficit instead of issuing another; an `ESCALATED` call keeps its original amount. A call still open past its `due_date` with the deficit persisting is escalated by the run from `OPEN` to `ESCALATED`. Whenever posted collateral again reaches or exceeds required collateral — after a pledge, a substitution, a release, a price mark, or a run — calls in `OPEN` or `ESCALATED` are cured to `CURED`, and the loan's `margin_status` is recomputed, flipping back to `CURRENT` when no open or escalated call remains. The terminal act belongs to a `RiskOfficer`: declaring default on an `ESCALATED` call — only an escalated call, and only while its loan is `BOOKED` or `RECALLED`, or the request is rejected with `ERR_INVALID_STATE` — moves the call to `DEFAULTED` and the loan to `DEFAULTED`, firing the full default cascade of §3.8.

### 3.6. Cash Collateral Reinvestment

Cash collateral does not sit idle. A `DeskTrader` may invest a cash-collateral loan's uninvested balance by opening a `ReinvestmentTranche` with an `instrument_type` of `MMF`, `REPO`, or `TIME_DEPOSIT`, a strictly positive `principal_cents`, and a `stated_yield_bps` used for provisional income accrual. Reinvestment is defined only for loans whose `collateral_type` is `CASH` — an attempt against a securities-collateral loan is rejected with `ERR_LOAN_NOT_CASH_COLLATERAL` — and the principal may not exceed the loan's `cash_uninvested_cents` (`ERR_REINVEST_EXCEEDS_CASH`). A new tranche starts `INVESTED`, its `current_nav_cents` initialized to `principal_cents`, and the loan's `cash_uninvested_cents` falls by the invested principal. An `OpsSettler` marks the tranche's `current_nav_cents` as the desk receives valuations.

Income accrues in two variants that deliberately diverge. Provisionally, each daily run accrues every `INVESTED` tranche's `principal_cents` times its `stated_yield_bps`, divided by 10000 and then by the 360-day year, rounded half-up to whole cents, as a `REINVEST_INCOME_PROVISIONAL` entry — one per tranche per accrual date, regardless of how the NAV has moved. Finally, at unwind, the tranche realizes `current_nav_cents` minus `principal_cents` as its `realized_income_cents` — a figure that may be negative when the mark has fallen — and a `REINVEST_INCOME_FINAL` entry carries that signed amount. The provisional stream is informational only: it is never trued-up, and the final entry alone reaches the revenue pool. Unwinding returns the principal to the loan's `cash_uninvested_cents`; gains and losses go to revenue, never to the borrower's collateral principal. A `DeskTrader` may unwind a tranche manually only while its loan is `BOOKED` or `RECALLED` (`ERR_INVALID_STATE`); settlement and default unwind every `INVESTED` tranche automatically. Either way the tranche lands in `UNWOUND`, its terminal state.

### 3.7. Recalls, Fail Fees, and Buy-Ins

An owner who needs shares back — for a sale, a corporate action, a vote, or a portfolio rebalance — issues a **full** recall. An `OwnerRep` creates a `Recall` against one of their own loans with a `quantity` that must equal the loan's entire `outstanding_quantity` — partial recalls do not exist, and a mismatched quantity is rejected with `ERR_VALIDATION` — a `reason` of `SALE`, `CORPORATE_ACTION`, `VOTE`, or `PORTFOLIO_REBALANCE`, and a `deadline_date` that must be strictly after the current date (`ERR_RECALL_WINDOW_INVALID`). A loan may carry at most one recall in a non-terminal state — `ISSUED`, `EXTENDED`, or `FAILED` — and issuing a second while one is open is rejected with `ERR_RECALL_ALREADY_OPEN`. The new recall starts in `ISSUED` status, records the clock date as its `issue_date`, copies its `owner_id` from the loan, starts with `delivered_quantity` at zero, `extended_once` false, `fail_price_cents` null, and `fail_fee_cents` at zero, and moves the loan from `BOOKED` to `RECALLED`, incrementing the loan's `version`.

While a recall is open, every return of shares against the loan is absorbed by the recall first: `delivered_quantity` climbs with each return until it reaches the recalled `quantity`, at which point the recall completes. An owner may extend an `ISSUED` recall exactly once, supplying a `new_deadline_date` that must push the deadline strictly later (`ERR_RECALL_WINDOW_INVALID`); the extension moves the recall to `EXTENDED`, writes the new `deadline_date`, and flips `extended_once` to true, and a second extension attempt is rejected with `ERR_RECALL_ALREADY_EXTENDED`. An owner may instead cancel a recall — from `ISSUED` or `EXTENDED` — but only while nothing has been delivered against it: a `delivered_quantity` greater than zero rejects the cancel with `ERR_RECALL_PARTIALLY_DELIVERED`. Cancelling moves the recall to `CANCELLED` and returns the loan from `RECALLED` to `BOOKED`, again incrementing the loan's `version`. Completion, from `ISSUED` or `EXTENDED`, lands in `COMPLETED` and finalizes the recall's `fail_fee_cents`, posting a `FAIL_FEE` ledger entry when the fee is greater than zero.

The daily run polices deadlines. A recall still `ISSUED` or `EXTENDED` whose `deadline_date` has passed with `delivered_quantity` short of `quantity` moves to `FAILED`, and the run snapshots the security's current `price_cents` into the recall's `fail_price_cents`. Fail fees then accrue per delivery tranche: for shares delivered — or bought in — on a given date, the chargeable days are the calendar days from the `deadline_date` to that date, floored at zero so that the deadline day itself is free; the window is deadline-exclusive and delivery-inclusive. Each tranche's fee is those days multiplied by the tranche's shares times the `fail_price_cents` times 100 basis points divided by 10000, the per-tranche product rounded half-up to whole cents before the day-count multiplication, and the fee accumulates into `fail_fee_cents`.

A buy-in closes out a failure. A `DeskTrader` executes it with a `buy_in_price_cents`, and only against a recall in `FAILED` status — from any other state the call is rejected with `ERR_BUY_IN_NOT_ALLOWED`. The buy-in finalizes the fail fee for the undelivered remainder, accruing from the day after the deadline through the buy-in date inclusive, posts a `FAIL_FEE` entry if the total fee is greater than zero, and posts a `BUY_IN_CHARGE` equal to the undelivered shares — `quantity` minus `delivered_quantity` — multiplied by `buy_in_price_cents`; both entries are charged to the borrower as negative amounts. The loan then moves to `SETTLED` as its economic close, running the settlement cascade: pledges released, tranches unwound, calls cured. Fail economics pass through entirely to the owner — neither fail fees nor buy-in charges enter the monthly revenue pool of §3.9.

### 3.8. Credit Overrides, Suspension, and Default

The utilization gate of §2.9 bends only through a formal override. A `DeskTrader` requests a `LimitOverride` for a borrower with a `new_limit_cents` and a window from `effective_from` (inclusive) to `expires_at` (exclusive); the start must be strictly before the end, or the request is rejected with `ERR_INVALID_WINDOW`. The request records the caller as `requested_by_user_id` and starts `REQUESTED` with `decided_by_user_id` null. Only a `RiskOfficer` decides. Approval carries a segregation-of-duties rule — the approver's `X-User-ID` must differ from the `requested_by_user_id`, or the decision is rejected with `ERR_SOD_VIOLATION` — and a window rule: the new window may not overlap any other `APPROVED` override for the same borrower, where windows are half-open so pure adjacency is permitted; overlap is rejected with `ERR_OVERRIDE_WINDOW_OVERLAP`. An approval stamps `decided_by_user_id`, moves the override to `APPROVED`, and recomputes the borrower's `effective_limit_cents`. Rejection moves it to `REJECTED` with `decided_by_user_id` stamped and no further effect. The daily run expires an `APPROVED` override once the current date reaches its `expires_at`, moving it to `EXPIRED` and recomputing the effective limit back down to `credit_limit_cents`.

Suspension and default sit with the `RiskOfficer`. Suspending a borrower — `ACTIVE` to `SUSPENDED` — cancels every `SUBMITTED` borrow request of that borrower; resuming restores `ACTIVE`. Declaring default, from `ACTIVE` or `SUSPENDED`, moves the borrower to `DEFAULTED` and fires a four-link cascade. First, every loan of the borrower in `BOOKED` or `RECALLED` moves to `DEFAULTED`. Second, per defaulted loan, every `ACTIVE` collateral pledge moves to `SEIZED` and a `COLLATERAL_SEIZURE` ledger entry posts at the pledge's `marked_value_cents` as income on the owner side. Third, every `INVESTED` reinvestment tranche is unwound at its `current_nav_cents` with its `REINVEST_INCOME_FINAL` entry. Fourth, for each defaulted loan whose owner opted into indemnification, an `INDEMNITY_CREDIT` entry posts to that owner per the shortfall computation below. The same four links fire when a single loan defaults through a margin-call declaration rather than a borrower-wide event. In both paths the position's `quantity_on_loan` falls by the defaulted loan's outstanding quantity — the inventory returns to the owner's pool — and any recall still open on a defaulted loan (`ISSUED`, `EXTENDED`, or `FAILED`) is cancelled. A borrower default also cancels the borrower's `SUBMITTED` and `MATCHED` borrow requests, with a `MATCHED` cancellation running the usual proposal-cancelling, reservation-releasing cascade.

The indemnity computation is conservative. What the owner is owed is the defaulted loan's `market_value_cents` at the moment of default plus any outstanding unpaid finalized fees. What was recovered is the sum of `marked_value_cents` over the pledges that just moved to `SEIZED`. The shortfall is the difference, floored at zero — recovery above the owed amount pays nothing extra. When the owner's `indemnification_opt_in` is set, an `INDEMNITY_CREDIT` entry for the shortfall posts to the owner; otherwise no entry posts and the owner bears the shortfall themselves.

### 3.9. The Revenue Ledger, Month-End Close, and Regulatory Reporting

Every economic event lands in the revenue ledger as a `RevenueLedgerEntry`. Each entry records its `loan_id` — null on the revenue-split entries, which belong to an owner rather than a loan — its `owner_id`, which is set on every entry (the loan's owner, or the split beneficiary on split entries), an `entry_type`, a signed `amount_cents` (charges to the borrower are negative, income is positive), the `accrual_date` the entry accrues for, a `period` in `YYYY-MM` form derived from the accrual date, and a free-form provenance `note` that defaults to empty. Twelve entry types exist: `FEE_ACCRUAL_PROVISIONAL`, `FEE_ACCRUAL_FINAL`, `FEE_TRUE_UP`, `REBATE_ACCRUAL`, `REINVEST_INCOME_PROVISIONAL`, `REINVEST_INCOME_FINAL`, `FAIL_FEE`, `BUY_IN_CHARGE`, `COLLATERAL_SEIZURE`, `INDEMNITY_CREDIT`, `REVENUE_SPLIT_OWNER`, and `REVENUE_SPLIT_AGENT`. Ledger entries are created only by the system's own runs and cascades; clients read but never write them.

Two accrual streams run daily. For a **securities-collateral** loan in `BOOKED` or `RECALLED`, each daily run posts a `FEE_ACCRUAL_PROVISIONAL` equal to that day's `outstanding_quantity` times that day's marked `price_cents` times the loan's `rate_bps`, divided by 10000 and then by the 360-day year, rounded half-up to whole cents per day — one entry per loan per accrual date, so a second run on the same date posts nothing, and a zero computed fee is never posted (a `rate_bps` of zero produces no rows). For a **cash-collateral** loan, the borrower earns a rebate instead: each run posts a `REBATE_ACCRUAL` equal to the day's active cash pledged — the sum of the loan's `ACTIVE` cash pledges — times `rate_bps`, divided by 10000 and by 360, rounded half-up per day, and carried as a negative amount because it is income owed back to the borrower. The same one-per-day and no-zero rules apply.

Month-end close converts the provisional stream into final numbers for a `period`. For each loan, the exact fee for the period is the unrounded day-by-day total — each accrued day's outstanding quantity times that day's marked price times `rate_bps`, divided by 10000 and by 360, summed across the period's accrued days — rounded half-up exactly once at month end and posted as `FEE_ACCRUAL_FINAL`; a `FEE_TRUE_UP` entry for the difference between that final fee and the sum of the period's provisionals reconciles the two, so the variants diverge only by accumulated per-day rounding. The close then runs the revenue-split waterfall per beneficial owner, in a pinned order: the gross pool is the sum of the owner's loans' `FEE_ACCRUAL_FINAL` entries plus their `REINVEST_INCOME_FINAL` entries for the period — `FEE_TRUE_UP` is deliberately excluded, because it reconciles the provisional stream to the authoritative final entry and adding both would double-count the delta; rebates are the owner's `REBATE_ACCRUAL` amounts for the period, negated from their stored-negative form; the net pool is gross minus rebates and may be negative; the owner's share is the net pool times the owner's `revenue_share_bps` divided by 10000, rounded half-up to whole cents; and the agent's share is the exact residual — the net pool minus the owner's rounded share, so the agent absorbs any rounding cent. `FAIL_FEE` and `BUY_IN_CHARGE` amounts stay outside the pool entirely, passing through to the owner with no agent cut. Each owner receives a `REVENUE_SPLIT_OWNER` entry, and the desk a `REVENUE_SPLIT_AGENT` entry. The close is recorded as a `PeriodClose` whose `period` is unique — a second close of the same period is rejected with `ERR_PERIOD_ALREADY_CLOSED` — and whose `loans_finalized_count` tallies the loans whose provisional accruals were finalized; the record's status is `CLOSED`, and reading it back uses the `YYYY-MM` period itself as its identifier.

Regulatory reporting is drafted against a closed period. An `OpsSettler` creates a `RegulatoryReport` in `DRAFT` status by naming its `period` and a `report_type` of `MONTHLY_LOAN_ACTIVITY`, `FAILS_AND_BUYINS`, or `COLLATERAL_SUMMARY`. Finalizing requires a `PeriodClose` to exist for the report's `period` (`ERR_PERIOD_NOT_CLOSED`), then computes and freezes the aggregates: `total_on_loan_value_cents` sums the `market_value_cents` of all loans in `BOOKED` or `RECALLED` at finalize time; `total_fee_income_cents` sums the period's `FEE_ACCRUAL_FINAL` and `FEE_TRUE_UP` ledger amounts; `total_rebate_expense_cents` sums the period's `REBATE_ACCRUAL` amounts expressed as a positive expense; `fail_count` tallies recalls that entered `FAILED` during the period; and `buy_in_count` tallies recalls that entered `BOUGHT_IN`. Finalization stamps `finalized_by_user_id` with the settler's `X-User-ID` and moves the report from `DRAFT` to `FINALIZED`. A settler may reopen a `FINALIZED` report, cycling it back to `DRAFT` with every aggregate cleared to null and `finalized_by_user_id` cleared. Filing is the `DeskAdmin`'s act and carries the desk's second segregation-of-duties rule: the filer's `X-User-ID` must differ from the `finalized_by_user_id`, or the filing is rejected with `ERR_SOD_VIOLATION`. A successful filing stamps `filed_by_user_id` and moves the report to `FILED`, its terminal state.

## 4. Endpoint Definitions

Operations that create a new resource — registering a security, onboarding a counterparty, requesting an override, opening a position or request or loan, matching demand into a loan proposal, posting a pledge, issuing a recall, opening a reinvestment tranche, drafting a report, or closing a period — return `201 Created`. Operations that read or modify an existing resource, including every state-transition action, return `200 OK`. Request payloads, response contents, and side effects are defined by the narratives of §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/securities` | Register a security | DeskAdmin |
| GET | `/api/securities/{security_id}` | Read a security | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/securities` | List securities | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/securities/{security_id}/halt` | Halt lending in a security; cancels open demand and proposals | DeskAdmin |
| POST | `/api/securities/{security_id}/resume` | Resume lending | DeskAdmin |
| POST | `/api/securities/{security_id}/price` | Mark a new price | DeskAdmin |
| POST | `/api/beneficial-owners` | Onboard a beneficial owner | DeskAdmin |
| GET | `/api/beneficial-owners/{owner_id}` | Read an owner | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/beneficial-owners` | List owners | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/beneficial-owners/{owner_id}/suspend` | Suspend an owner (blocks new matches) | RiskOfficer |
| POST | `/api/beneficial-owners/{owner_id}/resume` | Resume an owner | RiskOfficer |
| POST | `/api/beneficial-owners/{owner_id}/offboard` | Offboard an owner (guarded by zero open loans/reservations) | RiskOfficer |
| POST | `/api/borrowers` | Onboard a borrower | DeskAdmin |
| GET | `/api/borrowers/{borrower_id}` | Read a borrower | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/borrowers` | List borrowers | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/borrowers/{borrower_id}/suspend` | Suspend a borrower; cancels its SUBMITTED requests | RiskOfficer |
| POST | `/api/borrowers/{borrower_id}/resume` | Resume a borrower | RiskOfficer |
| POST | `/api/borrowers/{borrower_id}/default` | Declare borrower default; fires the default cascade | RiskOfficer |
| POST | `/api/borrowers/{borrower_id}/limit-overrides` | Request a temporary credit-limit override | DeskTrader |
| GET | `/api/limit-overrides/{override_id}` | Read an override | DeskAdmin, DeskTrader, RiskOfficer, OpsSettler |
| GET | `/api/limit-overrides` | List overrides | DeskAdmin, DeskTrader, RiskOfficer, OpsSettler |
| POST | `/api/limit-overrides/{override_id}/approve` | Approve an override (SoD: approver differs from requester; no window overlap) | RiskOfficer |
| POST | `/api/limit-overrides/{override_id}/reject` | Reject an override | RiskOfficer |
| POST | `/api/lendable-positions` | Make inventory lendable | OwnerRep |
| GET | `/api/lendable-positions/{position_id}` | Read a position | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/lendable-positions` | List positions | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/lendable-positions/{position_id}/suspend` | Suspend a position (owner only) | OwnerRep |
| POST | `/api/lendable-positions/{position_id}/resume` | Resume a position (owner only) | OwnerRep |
| POST | `/api/borrow-requests` | Submit borrow demand | BorrowerRep |
| GET | `/api/borrow-requests/{request_id}` | Read a request | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/borrow-requests` | List requests | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/borrow-requests/{request_id}/cancel` | Cancel demand; a MATCHED request's proposal is cancelled and its reservation released | BorrowerRep |
| POST | `/api/borrow-requests/{request_id}/match` | Match demand to inventory and open a loan proposal | DeskTrader |
| POST | `/api/loans` | Open a direct loan proposal (no borrow request) | DeskTrader |
| GET | `/api/loans/{loan_id}` | Read a loan | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/loans` | List loans | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/loans/{loan_id}/counter` | Counter-propose the rate | DeskTrader, BorrowerRep |
| POST | `/api/loans/{loan_id}/accept` | Borrower accepts a desk proposal, booking the loan | BorrowerRep |
| POST | `/api/loans/{loan_id}/confirm` | Desk confirms a borrower counter, booking the loan | DeskTrader |
| POST | `/api/loans/{loan_id}/cancel` | Cancel a proposal (either party; scoped) | DeskTrader, BorrowerRep |
| POST | `/api/loans/{loan_id}/amendments` | Amend rate or term on a BOOKED loan (OCC on loan version) | DeskTrader |
| POST | `/api/loans/{loan_id}/returns` | Return shares; a full return settles the loan | BorrowerRep |
| POST | `/api/loans/{loan_id}/pledges` | Post collateral against a booked loan | BorrowerRep |
| GET | `/api/pledges/{pledge_id}` | Read a pledge | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/pledges` | List pledges | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/loans/{loan_id}/pledges/{pledge_id}/substitute` | Replace a pledge with new collateral (OCC on loan version) | BorrowerRep |
| POST | `/api/pledges/{pledge_id}/release` | Release excess collateral (must not create a margin deficit) | DeskTrader |
| GET | `/api/margin-calls/{call_id}` | Read a margin call | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/margin-calls` | List margin calls | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/margin-calls/{call_id}/declare-default` | Declare default on an ESCALATED call; defaults the loan | RiskOfficer |
| POST | `/api/loans/{loan_id}/recalls` | Issue a full recall | OwnerRep |
| GET | `/api/recalls/{recall_id}` | Read a recall | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/recalls` | List recalls | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/recalls/{recall_id}/extend` | Extend the deadline once | OwnerRep |
| POST | `/api/recalls/{recall_id}/cancel` | Cancel a recall with zero deliveries; loan returns to BOOKED | OwnerRep |
| POST | `/api/recalls/{recall_id}/buy-in` | Execute a buy-in on a FAILED recall | DeskTrader |
| POST | `/api/loans/{loan_id}/reinvestments` | Invest uninvested cash collateral | DeskTrader |
| GET | `/api/reinvestments/{tranche_id}` | Read a tranche | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/reinvestments` | List tranches | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/reinvestments/{tranche_id}/mark` | Mark the tranche NAV | OpsSettler |
| POST | `/api/reinvestments/{tranche_id}/unwind` | Unwind a tranche | DeskTrader |
| GET | `/api/ledger-entries/{entry_id}` | Read a ledger entry | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| GET | `/api/ledger-entries` | List ledger entries | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/ops/mark-to-market` | Run the daily batch for the current clock date | OpsSettler |
| POST | `/api/ops/month-end-close` | Close a period: finalize accruals, post true-ups, run the revenue split | OpsSettler |
| GET | `/api/period-closes/{period_id}` | Read a period close record (id is the YYYY-MM period) | DeskAdmin, DeskTrader, BorrowerRep, OwnerRep, RiskOfficer, OpsSettler |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (test-driving endpoint) | DeskAdmin |
| POST | `/api/regulatory-reports` | Create a DRAFT regulatory report for a period | OpsSettler |
| GET | `/api/regulatory-reports/{report_id}` | Read a report | DeskAdmin, DeskTrader, RiskOfficer, OpsSettler |
| GET | `/api/regulatory-reports` | List reports | DeskAdmin, DeskTrader, RiskOfficer, OpsSettler |
| POST | `/api/regulatory-reports/{report_id}/finalize` | Finalize a report (requires the period to be closed) | OpsSettler |
| POST | `/api/regulatory-reports/{report_id}/reopen` | Reopen a FINALIZED report back to DRAFT | OpsSettler |
| POST | `/api/regulatory-reports/{report_id}/file` | File a FINALIZED report (SoD: filer differs from finalizer) | DeskAdmin |

## 5. Error Code Catalogue

The trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SECURITY_HALTED` | 409 Conflict |
| `ERR_BORROWER_SUSPENDED` | 409 Conflict |
| `ERR_OWNER_SUSPENDED` | 409 Conflict |
| `ERR_POSITION_SUSPENDED` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 409 Conflict |
| `ERR_RECALL_ALREADY_OPEN` | 409 Conflict |
| `ERR_RECALL_ALREADY_EXTENDED` | 409 Conflict |
| `ERR_RECALL_PARTIALLY_DELIVERED` | 409 Conflict |
| `ERR_RECALL_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_REQUEST_EXPIRED` | 422 Unprocessable Entity |
| `ERR_OVERRIDE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_INVENTORY` | 409 Conflict |
| `ERR_AMBIGUOUS_MATCH` | 409 Conflict |
| `ERR_FORWARD_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_MARGIN_DEFICIT` | 409 Conflict |
| `ERR_MARGIN_CALL_OUTSTANDING` | 409 Conflict |
| `ERR_RETURN_EXCEEDS_LOAN` | 422 Unprocessable Entity |
| `ERR_REINVEST_EXCEEDS_CASH` | 422 Unprocessable Entity |
| `ERR_LOAN_NOT_CASH_COLLATERAL` | 409 Conflict |
| `ERR_PLEDGE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COLLATERAL_SHORTFALL` | 409 Conflict |
| `ERR_INSUFFICIENT_UNINVESTED_CASH` | 409 Conflict |
| `ERR_RATE_ABOVE_MAX` | 422 Unprocessable Entity |
| `ERR_BUY_IN_NOT_ALLOWED` | 409 Conflict |
| `ERR_PERIOD_ALREADY_CLOSED` | 409 Conflict |
| `ERR_PERIOD_NOT_CLOSED` | 409 Conflict |
| `ERR_OWNER_HAS_OPEN_LOANS` | 409 Conflict |

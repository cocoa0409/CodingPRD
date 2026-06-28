# Small Business Line Of Credit API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Small-Business Line of Credit API, a lending platform in the spirit of OnDeck and Kabbage. The system supports the full revolving-credit lifecycle: a merchant applies for a line, the platform underwrites the application against a cash-flow snapshot pulled from the merchant's linked bank account (a Plaid-style feed), and — if approved — a revolving line is activated. The borrower then draws principal against that line and repays it through scheduled remittances that debit automatically on a daily or weekly cadence, with retries when a debit bounces for non-sufficient funds.

The product is fundamentally a **ledger-reconciliation engine wrapped in a compliance workflow**. Every advance, fee accrual, and repayment is an immutable ledger movement, and the outstanding balance on a line is always reconstructible from those movements. Layered on top are credit-decisioning controls — risk scoring, tiered pricing, fee-versus-APR renewal economics, line-increase reviews — and a strict separation of duties: the operator who originates an application may not approve it, and the officer who declares a default may not be the one who charges it off. The API also models the unhappy path end to end: missed remittances escalate a line into delinquency, then default, then charge-off, writing down every unrepaid draw.

Because money movement must never drift, all balance mutations are applied atomically within the request that triggers them, and concurrent writers are guarded with optimistic concurrency control on the credit line. This specification defines the entities, their state machines, the calculations that derive every monetary field, the validation order that governs each request, and the role-based access rules that enforce segregation of duties.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request, with two exceptions noted below, must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the operator's capacity. The system recognizes exactly three roles: `Underwriter`, `Servicer`, and `CreditOfficer`. If either header is missing, or if `X-User-Role` does not name one of these three roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The two endpoints that do not require authentication are merchant registration and the logical-clock control endpoint; all other endpoints require valid headers.

The three roles partition responsibility along segregation-of-duties lines. An `Underwriter` originates and risk-assesses applications, ingests bank feeds, and runs the submit/approve/decline/request-revision workflow on applications. A `Servicer` operates an active line — taking draws, scheduling and settling remittances, freezing and unfreezing, accepting or declining renewal offers, and opening and finalizing statements — but holds no credit-decision authority. A `CreditOfficer` holds credit authority: activating lines from approved applications, approving or denying increase requests, creating renewal offers, declaring default and charging off, and blocklisting merchants.

All three roles use an **opaque** identity. When `X-User-Role` is `Underwriter`, `Servicer`, or `CreditOfficer`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id`. The server does, however, **record** specific operator identifiers where the workflow demands an audit anchor: when an application is submitted, the submitting `Underwriter`'s `X-User-ID` is stored as `submitted_by_user_id` on that `Application`; when a line is declared in default, the declaring `CreditOfficer`'s `X-User-ID` is stored as `defaulted_by_user_id` on that `CreditLine`. These recorded identifiers drive the segregation-of-duties checks described in §3, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, drawn from real wall-clock time at the moment the response is served — it is a transport-level request marker and is **not** governed by the logical clock of §2.4 (which times only business evaluations and the entity `created_at`/`updated_at` fields).
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Beyond `limit`/`offset`, the list endpoints also accept optional exact-match filter query parameters and silently ignore any that are absent: every list of status-bearing resources filters by `status` when supplied (this covers bank feeds, applications, credit lines, draws, remittances, line-increase requests, renewal offers, and statements), and the system-wide collection listings additionally filter by their relevant foreign keys (applications by `merchant_id` and `bank_feed_id`; credit lines by `merchant_id` and `application_id`). The two ledger-entry listings instead filter as described in §3.8 and accept no `status` parameter. A filter value that matches no resource simply yields an empty page rather than an error.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed fields. The `id` is a unique, server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, and `version` is an integer that begins at 1 and increments by one on every mutation of the resource. The `version` field is the basis for the optimistic concurrency control described in §2.6.

Most entities — `Merchant`, `BankFeed`, `Application`, `CreditLine`, `Draw`, `Remittance`, `LineIncreaseRequest`, `RenewalOffer`, and `Statement` — carry all four of `id`, `created_at`, `updated_at`, and `version`. The single exception is the `LedgerEntry`: a ledger row is immutable once written, so it carries only `id` and `created_at`. A `LedgerEntry` has neither `updated_at` nor `version`.

Time in this system is governed by a **logical clock**, not wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and it remains at that default until an operator advances it through the clock-control capability by supplying a `to_iso8601` instant to which the clock is moved. Every "now" referenced in this specification — recency checks on feeds, due-date checks on remittances, time-to-live expirations, statement window boundaries — is evaluated against this logical clock.

### 2.5. Hierarchical Consistency, Cascades, and Nested Retrieval

The entities form a flat topology of peer records linked by foreign-key references rather than a deep nested tree, but balance state still flows along parent-child lines. Whenever a `Draw` is created, repaid, or written off, the parent `CreditLine`'s outstanding figures are recomputed and the line's `updated_at` and `version` are refreshed. Whenever a child mutation changes a parent's derived state, that recomputation is part of the same atomic request — there is no deferred or eventual reconciliation. Every mutation of a resource refreshes its `updated_at` and increments its `version` by one.

Several operations cascade across more than one entity in a single request; each such cascade is described in full in the relevant §3 workflow, and every hop must be applied atomically. The charge-off cascade, the remittance-settlement waterfall, the NSF-failure escalation, and the default cancellation of scheduled remittances are the principal multi-entity operations.

For any request whose URL path names more than one resource, the system validates the existence of each path segment in left-to-right order and rejects the first missing identifier with `ERR_NOT_FOUND` (HTTP 404). The same `ERR_NOT_FOUND` applies when a foreign-key reference supplied in a request body — for example a `merchant_id`, `bank_feed_id`, `application_id`, or `credit_line_id` — names a resource that does not exist.

### 2.6. Optimistic Concurrency Control on the Credit Line

Three operations write directly against a `CreditLine` in ways that depend on the officer having observed the line's current state, and these operations require an explicit version guard. On these requests the client must supply `expected_credit_line_version` carrying the `version` of the `CreditLine` it last read. If that value does not equal the line's current `version` — because another writer has advanced the line since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no mutation is applied.

The two requests for which `expected_credit_line_version` is a non-optional input are line-increase approval and charge-off. Declaring default also enforces the same version guard against the line. Approving a line increase writes a new `credit_limit_cents` onto the parent line; if the line's `version` has advanced since the officer read it (for example, an earlier increase already raised the limit, or a remittance changed the balance), the officer's view is stale and the approval is rejected with `ERR_STALE_VERSION` so it cannot overwrite a state it never observed. Charging off a defaulted line writes off every outstanding draw and zeroes the outstanding principal; if the line's `version` has advanced since the officer read it (for example, a late remittance settled and reduced principal), the loss-amount view is stale and the charge-off is rejected with `ERR_STALE_VERSION` so the write-off is recomputed against current principal. Endpoints other than these three do not accept and do not require a version field.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and transmitted as integer numbers of cents; there are no fractional cents anywhere in the system. Where a calculation produces a fractional intermediate value, the rounding rule is stated with the calculation in §3, but the governing convention is **round half up to a whole cent**. The risk score is similarly produced by a single final round, half up, to zero decimal places, yielding an integer. Basis-point values such as `equivalent_apr_bps` are likewise rounded half up to a whole basis point. Aggregations that sum integer-cent fields — outstanding principal, outstanding fee, statement totals — involve no rounding because their inputs are already whole cents.

### 2.8. The Immutable Ledger

Every movement of money against a line is recorded as an immutable `LedgerEntry` row, and the outstanding balance is always reconstructible from these rows. Each entry belongs to a line via `credit_line_id` and, where applicable, references the `draw_id` it touches and the `remittance_id` that produced it; both of those references are nullable, because line-level adjustments name no draw and non-remittance entries name no remittance. Each entry carries an `entry_type` that is one of `DRAW_PRINCIPAL`, `DRAW_FEE`, `PRINCIPAL_REPAYMENT`, `FEE_REPAYMENT`, or `WRITE_OFF`. The `amount_cents` on an entry is a signed movement, where a debit is positive (increasing outstanding) and a credit is negative (reducing it): `DRAW_PRINCIPAL` is positive, `DRAW_FEE` is positive, while `PRINCIPAL_REPAYMENT`, `FEE_REPAYMENT`, and `WRITE_OFF` are negative. The `balance_after_cents` records the outstanding **principal** on the line immediately after the entry — the running balance. Because this running balance is principal-only, the fee-bearing entries (`DRAW_FEE` and `FEE_REPAYMENT`) leave it unchanged: each carries the same `balance_after_cents` as the principal entry written alongside it in the same operation, so only `DRAW_PRINCIPAL`, `PRINCIPAL_REPAYMENT`, and `WRITE_OFF` actually move the running balance. Ledger entries are never updated or deleted; corrections are expressed only as new entries.

### 2.9. Validation Ordering

When a single request could fail several checks, the checks are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order, highest priority first, is: authentication (`ERR_UNAUTHENTICATED`); role authorization (`ERR_FORBIDDEN_ROLE`); segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); existence of every path resource and body foreign key (`ERR_NOT_FOUND`); request well-formedness — required fields present, correct types, declared enum values, and integer constraints such as a draw principal being strictly positive (`ERR_INVALID_REQUEST`); state legality of the requested transition (`ERR_INVALID_STATE`); the credit-line version guard (`ERR_STALE_VERSION`); merchant-blocklist (`ERR_MERCHANT_BLOCKLISTED`); feed freshness (`ERR_FEED_STALE`); the NSF underwriting gate (`ERR_EXCESS_NSF`); the risk-score floor (`ERR_SCORE_BELOW_FLOOR`); application-approved-for-origination (`ERR_APPLICATION_NOT_APPROVED`); remittance-due timing (`ERR_REMITTANCE_NOT_DUE`); remittance window overlap (`ERR_REMITTANCE_OVERLAP`); statement window overlap (`ERR_STATEMENT_OVERLAP`); line-drawable status (`ERR_LINE_NOT_DRAWABLE`); and finally the fiscal limit check (`ERR_LIMIT_EXCEEDED`). Where a request is well-formed but semantically invalid — a statement whose `period_end` is not strictly after its `period_start`, or a renewal offer whose `term_days` or `new_fee_factor_bps` is not strictly positive (both positivity checks are semantic and the `term_days` check is evaluated before the `new_fee_factor_bps` check) — the rejection is `ERR_VALIDATION` (HTTP 422).

The state-legality slot deserves special note. For line-increase approval and renewal-offer acceptance only, that slot also enforces the cross-entity guard that the parent `CreditLine` must be `ACTIVE`, returning `ERR_INVALID_STATE` when the parent is not active. The draw endpoint does **not** route its parent-line-status guard through this slot; a draw against a non-active line is instead rejected by a dedicated lower-priority check with `ERR_LINE_NOT_DRAWABLE`, so that a draw on a frozen, delinquent, or closed line returns `ERR_LINE_NOT_DRAWABLE` rather than `ERR_INVALID_STATE` — even when the draw would also exceed the limit, the not-drawable check precedes the limit check.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Merchants and Bank Feeds

The workflow begins with a **merchant** — the registered business that will borrow. Registering a merchant is an open, pre-authentication step: any of the three roles may register one, and no headers are required. A merchant is created with a `legal_name`, an `ein` (the Employer Identification Number, which must be exactly nine digits and unique across all merchants; a malformed `ein` and a duplicate `ein` are both rejected with `ERR_INVALID_REQUEST`), a `state_code` (the two-uppercase-letter US state of registration), and a self-reported `monthly_revenue_cents` (average monthly revenue in cents, which must be zero or greater). A merchant's `status` begins at `ACTIVE` and may later be moved to `BLOCKLISTED`. Only a `CreditOfficer` may blocklist a merchant; doing so sets `status` to `BLOCKLISTED` and bumps the merchant's `version`.

Underwriting consumes a **bank feed** — a point-in-time snapshot pulled from the merchant's linked bank account. An `Underwriter` or `Servicer` ingests a feed for a merchant, supplying the `plaid_item_id` (the opaque Plaid item identifier for the linked account), the `pulled_at` instant the snapshot was captured, the `avg_daily_balance_cents` over the feed window, the `nsf_count_90d` (the count of non-sufficient-funds and overdraft events in the trailing ninety days), and the `deposit_volume_cents` (total deposits over the window); all three monetary or count fields must be zero or greater. A feed is created with `status` set to `FRESH`. Because underwriting must run against current cash-flow data, a feed can be marked `STALE` — either manually or to drive test scenarios — which sets its `status` to `STALE` and bumps its `version`. The `pulled_at` instant is what drives recency checks. When a feed's snapshot belongs to a merchant, the feed records that ownership through its `merchant_id`, and feeds are discoverable in reverse by that `merchant_id`.

### 3.2. Application Underwriting and the Revision Loop

An `Underwriter` opens an **application** in `DRAFT` by naming the applicant `merchant_id`, the `bank_feed_id` the underwriting will run against, and the `requested_limit_cents` the merchant is asking for (which must be strictly greater than zero). The application's `status` begins at `DRAFT` and moves through `SUBMITTED`, possibly `NEEDS_REVISION`, and on to one of the terminal outcomes `APPROVED`, `DECLINED`, or `EXPIRED`. The computed fields `risk_score`, `approved_limit_cents`, and `pricing_tier` are filled in as the application progresses, and `decline_reason` is set only on a decline.

Submitting an application advances it from `DRAFT` to `SUBMITTED`. Submission is permitted only when the application is in `DRAFT` (or, in the revision loop, in `NEEDS_REVISION`) and the referenced bank feed is `FRESH`; a stale feed at submit time is rejected with `ERR_FEED_STALE`. On submit, the system records the submitting operator's identifier as `submitted_by_user_id`, computes the `risk_score`, and increments the application's `version`. A resubmission may attach a different feed: the submit request accepts an optional `bank_feed_id`, and when present the application is rescored against that newer feed, discarding the prior `risk_score`.

The **risk score** is a weighted blend of three cash-flow signals, derived from the referenced bank feed and the merchant. First, a balance ratio is computed as the average daily balance divided by the requested limit, where the denominator is treated as at least one cent to avoid division by zero, and the ratio is capped at 1.0. Second, a revenue ratio is computed as the feed's deposit volume divided by three times the merchant's monthly revenue, where that denominator is likewise treated as at least one, and the ratio is capped at 1.0. Third, an NSF penalty is computed as the feed's trailing-90-day NSF count multiplied by a per-event penalty step of 0.15, capped at 1.0. The raw blend is then the balance ratio weighted at 0.50, plus the revenue ratio weighted at 0.35, minus the NSF penalty weighted at 0.40. That raw value is clamped to the range from 0.0 to 1.0, and only then multiplied by 100 and rounded — a single final round, half up, to zero decimal places — producing an integer score from 0 to 100. The three component sub-scores are kept at full precision and are never individually rounded; the rounding happens exactly once, on the final blended value. The score is computed over exactly one bank feed and one merchant, with no aggregation across feeds.

Three review actions are available on a `SUBMITTED` application, and all three are reserved to an `Underwriter` who is not the submitter — that is, the acting `X-User-ID` must differ from the stored `submitted_by_user_id`, or the action is rejected with `ERR_SEGREGATION_OF_DUTIES`. **Requesting a revision** moves the application from `SUBMITTED` to `NEEDS_REVISION`, clears the `risk_score` back to null, and bumps the version; from `NEEDS_REVISION` the application can be resubmitted, forming the cyclic revision loop `SUBMITTED → NEEDS_REVISION → SUBMITTED`. **Declining** moves the application from `SUBMITTED` to `DECLINED` and records a `decline_reason`, which is one of `LOW_SCORE`, `STALE_FEED`, `EXCESS_NSF`, or `BLOCKLISTED`. **Approving** moves the application from `SUBMITTED` to `APPROVED`.

Approval is the most heavily guarded transition, because it is where the credit decision is committed. Beyond requiring the application to be `SUBMITTED` and the approver to differ from the submitter, approval enforces, in the validation order of §2.9: the referenced merchant must not be `BLOCKLISTED` (else `ERR_MERCHANT_BLOCKLISTED`); the referenced bank feed must still be `FRESH` (else `ERR_FEED_STALE`); the feed's trailing-90-day NSF count must not exceed the underwriting maximum of 3 events (else `ERR_EXCESS_NSF`); and the application's `risk_score` must be at least the approval floor of 50 (else `ERR_SCORE_BELOW_FLOOR`). When all guards pass, approval computes `approved_limit_cents`, sets the `pricing_tier`, and increments the version. Note that approval does **not** create a credit line — line activation is a separate step performed later by a `CreditOfficer`.

The **approved limit and pricing tier** are derived from the score and the feed. The score selects a tier by band: a score of at least 80 selects `TIER_A`, with an advance multiple of 1.50; a score from 65 up to but not including 80 selects `TIER_B`, with an advance multiple of 1.00; and a score from the approval floor of 50 up to but not including 65 selects `TIER_C`, with an advance multiple of 0.60. The raw advance cap is the average daily balance multiplied by the tier's advance multiple, with any fractional cent floored away. At origination, the approved limit is the lesser of the requested limit and that raw cap; there is no current-limit floor on a brand-new application.

A `SUBMITTED` application that is never acted upon does not live forever. Once the logical clock has advanced at least 14 days past the moment the application entered `SUBMITTED` (measured from its `updated_at`), the application is eligible to expire. Expiration is not automatic on read; it is realized by an `Underwriter`-invoked sweep capability that moves every eligible `SUBMITTED` application to `EXPIRED` and increments each one's version. The sweep responds with `200 OK` and an array-typed envelope whose `data` is exactly the applications newly moved to `EXPIRED` on this call, ordered by `created_at` ascending; the meta `total_count` equals that swept count and no pagination is applied.

### 3.3. Activating and Operating the Credit Line

A `CreditOfficer` activates a **credit line** from an approved application by supplying the `application_id` and the `remittance_cadence` (either `DAILY` or `WEEKLY`). A line may be created only from an application in `APPROVED` status that has not already originated a line — one line per application — otherwise the request is rejected with `ERR_APPLICATION_NOT_APPROVED`. On activation the system copies the application's `approved_limit_cents` into the line's `credit_limit_cents`, copies the `pricing_tier`, and derives the `fee_factor_bps` (the flat fee factor in basis points charged on each draw principal) from that tier: `TIER_A` derives 800 basis points, `TIER_B` derives 1200, and `TIER_C` derives 1800. The line records its originating `application_id` and a denormalized `merchant_id` for ledger queries, and starts in `status` `ACTIVE`.

A credit line carries the running ledger state of the relationship. Its `outstanding_principal_cents` and `outstanding_fee_cents` are the sums of unrepaid principal and unrepaid fee across all non-terminal draws; its `available_credit_cents` is the credit limit minus outstanding principal, floored at zero; and `nsf_strike_count` is the consecutive count of failed-remittance strikes, which resets to zero on any successful remittance. On a fresh line `outstanding_principal_cents` and `outstanding_fee_cents` are zero, and consequently `available_credit_cents` is initialized to the full `credit_limit_cents` (the limit minus zero outstanding principal, floored at zero) rather than to zero; `nsf_strike_count` defaults to zero. The line's `status` ranges over `ACTIVE`, `FROZEN`, `DELINQUENT`, `DEFAULTED`, `CHARGED_OFF`, and `CLOSED`, with `CHARGED_OFF` and `CLOSED` terminal. The `defaulted_by_user_id` field stays null until the line is declared in default, at which point it records the declaring officer's identifier.

A `Servicer` may **freeze** an `ACTIVE` line, moving it to `FROZEN` and bumping its version; while frozen, no new draw may be created. **Unfreezing** moves it from `FROZEN` back to `ACTIVE`, forming the revolving `ACTIVE ↔ FROZEN` loop so that draws resume after unfreeze. A `Servicer` may also **close** a line, moving it from `ACTIVE` to `CLOSED`, but only when the line is fully paid off — both `outstanding_principal_cents` and `outstanding_fee_cents` must be exactly zero.

### 3.4. Draws Against the Line

A `Servicer` takes a **draw** against a line by supplying the `principal_cents` to advance, which must be strictly greater than zero. A draw records its parent `credit_line_id`, and on creation the system computes the draw's `fee_cents`, stamps the `drawn_at` instant from the logical clock (which drives the FIFO repayment ordering described in §3.5), appends ledger entries, and recomputes the parent line's outstanding figures and available credit, bumping the line's version. The draw's `status` begins at `OUTSTANDING` and is terminal at either `REPAID` or `WRITTEN_OFF`. A draw also tracks `principal_repaid_cents` and `fee_repaid_cents`, the cumulative principal and fee repaid against it, both defaulting to zero.

The **draw fee** is a flat origination fee on the advanced principal: the principal multiplied by the line's `fee_factor_bps`, divided by 10000 (the basis-point denominator), with the result rounded half up to a whole cent in a single multiply-then-round step. On funding, the draw appends two ledger entries: a `DRAW_PRINCIPAL` entry for the principal and a `DRAW_FEE` entry for the computed fee.

Two guards protect a draw, and their order matters. First, the parent line must be `ACTIVE`; a draw on a line in any other status (`FROZEN`, `DELINQUENT`, `DEFAULTED`, `CHARGED_OFF`, or `CLOSED`) is rejected with `ERR_LINE_NOT_DRAWABLE`. Second, the draw must not overdraw the line: the requested principal must not exceed the line's available credit. A principal exactly equal to available credit is allowed; a principal that would push outstanding principal above the credit limit is rejected with `ERR_LIMIT_EXCEEDED`. Because the not-drawable check precedes the limit check, a too-large draw against a non-active line surfaces as `ERR_LINE_NOT_DRAWABLE`, not `ERR_LIMIT_EXCEEDED`.

The line's **outstanding figures** are aggregations recomputed on every draw creation, every remittance settlement, and every charge-off. Outstanding principal is the sum, across all draws on the line whose `status` is `OUTSTANDING`, of each draw's principal minus its principal already repaid. Outstanding fee is the analogous sum of each outstanding draw's fee minus its fee already repaid. Available credit is the credit limit minus outstanding principal, floored at zero. Draws that are `REPAID` or `WRITTEN_OFF` are excluded from all three sums. These are sums of whole-cent integers and involve no rounding.

### 3.5. Remittances, Repayment Allocation, and the NSF Retry Cycle

Repayment runs through scheduled **remittances**. A `Servicer` schedules a remittance against a line by supplying the `scheduled_for` instant at which the debit is to occur; the remittance records its parent `credit_line_id`, starts in `status` `SCHEDULED` with `attempt_count` initialized to zero, and ranges over the statuses `SCHEDULED`, `SETTLED`, `FAILED`, and `CANCELLED`. A successful settlement reaches `SETTLED` and a cancellation reaches `CANCELLED`; an `NSF` or `ACCOUNT_CLOSED` settlement moves the remittance to `FAILED`, which is a resting state — that same remittance record is never revisited, since any retry is a fresh `SCHEDULED` sibling rather than a re-opening of the failed one. A remittance carries computed amounts — `amount_cents` (the total debit), `principal_applied_cents`, and `fee_applied_cents` — all defaulting to zero until settlement, plus a `failure_reason` (null, `NSF`, or `ACCOUNT_CLOSED`) and a `next_retry_remittance_id` pointer. That pointer holds the id of any retry remittance spawned by this one's NSF failure; it is surfaced in the settle response and is null when no retry was spawned. It is a sibling pointer, not an ownership link — the owning parent of every remittance is its `credit_line_id`.

Scheduling a remittance is guarded against collisions with other non-terminal remittances on the same line, and the rule depends on the line's cadence. On a `DAILY` line, two remittance windows must be separated by at least one calendar day, and the comparison is half-open so that exact adjacency is allowed. On a `WEEKLY` line, two windows must be separated by at least seven calendar days and any overlap — including a shared endpoint — is rejected, so adjacency is not allowed. A collision under the applicable cadence rule is rejected with `ERR_REMITTANCE_OVERLAP`.

A remittance may be **cancelled** by a `Servicer` while it is `SCHEDULED`, moving it to `CANCELLED`. Scheduled remittances are also cancelled as a system cascade when their line is declared in default, as described in §3.6.

**Settling** a remittance is the central repayment operation, performed by a `Servicer` with an `outcome` that is one of `SUCCESS`, `NSF`, or `ACCOUNT_CLOSED`. A remittance may be settled only when it is `SCHEDULED`, its parent line is in `ACTIVE` or `DELINQUENT` status, and the logical clock has reached or passed its `scheduled_for`; settling before the scheduled instant is rejected with `ERR_REMITTANCE_NOT_DUE`. Every settlement, regardless of outcome, increments the remittance's `attempt_count` by one and increments its version.

On a `SUCCESS` outcome, the remittance moves from `SCHEDULED` to `SETTLED` and allocates a debit across the line's outstanding draws. The target amount is a percentage of the line's outstanding total — outstanding principal plus outstanding fee at settle time — where a `DAILY` line uses 2 percent and a `WEEKLY` line uses 10 percent; the target is rounded half up to a whole cent before being capped. The actual `amount_cents` debited is the lesser of that rounded target and the outstanding total, so the system never over-collects. The amount is then allocated across the line's `OUTSTANDING` draws in FIFO order — oldest `drawn_at` first, breaking ties by `drawn_at` and then by `created_at` ascending, never by id. Within each draw, fee is repaid before principal: the system pays the draw's remaining fee due (its fee minus its fee already repaid) up to the remaining amount, then pays the draw's remaining principal due up to what is left, advancing through draws oldest-first until the amount is exhausted. The portion applied to principal across all draws becomes `principal_applied_cents` and the portion applied to fee becomes `fee_applied_cents`, and the debited `amount_cents` is their sum; this allocation is integer-cent arithmetic with no further rounding. Each touched draw's `principal_repaid_cents` and `fee_repaid_cents` are advanced accordingly, and any draw whose principal repaid now equals its principal and whose fee repaid now equals its fee auto-transitions from `OUTSTANDING` to `REPAID`, which bubbles up into a recomputation of the parent line's outstanding principal. The settlement appends a `PRINCIPAL_REPAYMENT` ledger entry and then a `FEE_REPAYMENT` ledger entry, but each is written only when its corresponding applied amount is strictly positive — a settlement that applies nothing to principal writes no `PRINCIPAL_REPAYMENT` entry, and one that applies nothing to fee writes no `FEE_REPAYMENT` entry; both repayment entries carry the same principal running balance (`balance_after_cents`) computed after the principal portion is subtracted. It then resets the line's `nsf_strike_count` to zero, recomputes the line's outstanding principal, outstanding fee, and available credit, and — if the line was `DELINQUENT` — cures it back to `ACTIVE` (the `DELINQUENT → ACTIVE` cure loop).

On an `NSF` outcome, the remittance moves from `SCHEDULED` to `FAILED`, its `failure_reason` is set to `NSF`, and the line's `nsf_strike_count` is incremented by one. The system then decides whether to spawn a retry: if this remittance's post-increment `attempt_count` is less than the retry ceiling of 5 attempts, the system spawns exactly one retry remittance — a fresh `SCHEDULED` remittance whose `scheduled_for` is this remittance's `scheduled_for` plus a 2-day retry gap, with its `attempt_count` initialized to this remittance's post-increment `attempt_count` — and sets this remittance's `next_retry_remittance_id` to the spawned id. If the post-increment attempt count has reached the ceiling, no retry is spawned and `next_retry_remittance_id` stays null. Because the retry inherits the attempt count, a single retry chain reaches at most 5 total failures, forming the `SCHEDULED → FAILED → SCHEDULED` retry cycle.

On an `ACCOUNT_CLOSED` outcome, the remittance likewise moves from `SCHEDULED` to `FAILED`, its `failure_reason` is set to `ACCOUNT_CLOSED`, and the line's `nsf_strike_count` is incremented by one exactly as for NSF — but because a closed account is permanent, no retry is ever spawned and `next_retry_remittance_id` stays null.

Both failure outcomes share an escalation rule: if after the strike increment the line's `nsf_strike_count` has reached the delinquency threshold of 3 and the line is currently `ACTIVE`, the line auto-transitions from `ACTIVE` to `DELINQUENT` and its version is bumped. This is the first hop of the missed-payment cascade — a failed settlement raises a strike, and the third consecutive strike tips an active line into delinquency.

### 3.6. Delinquency, Default, and the Charge-Off Cascade

When a line has tipped into `DELINQUENT`, it has two exits. A successful remittance cures it: any settlement that succeeds resets `nsf_strike_count` to zero and, if the line was `DELINQUENT`, moves it back to `ACTIVE`. Failing that, a `CreditOfficer` may **declare default**. Declaring default is permitted only when the line is `DELINQUENT` and its `nsf_strike_count` has reached the default threshold of 5; both of these preconditions are enforced in the state-legality slot, so a line that is not `DELINQUENT` and a `DELINQUENT` line whose `nsf_strike_count` is still below 5 are each rejected with `ERR_INVALID_STATE`. It then requires `expected_credit_line_version` to match the line's current `version` (a mismatch is rejected with `ERR_STALE_VERSION`). On default, the system records the declaring officer's `X-User-ID` as `defaulted_by_user_id`, cancels every `SCHEDULED` remittance on the line by moving each to `CANCELLED`, moves the line to `DEFAULTED`, and bumps the line's version.

From `DEFAULTED`, a `CreditOfficer` may **charge off** the line — but, by segregation of duties, the acting `X-User-ID` must differ from the line's recorded `defaulted_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Charge-off also requires `expected_credit_line_version` to match the line's current `version`, rejecting a mismatch with `ERR_STALE_VERSION`. When it proceeds, charge-off runs a three-hop cascade in a single atomic request: every `OUTSTANDING` draw on the line, processed in creation order (oldest `created_at` first, tie-broken by creation sequence, never by id), transitions to `WRITTEN_OFF` (hop one); each written-off draw appends a `WRITE_OFF` ledger entry whose `amount_cents` is the negative of its unrepaid principal — i.e. `-(principal_cents − principal_repaid_cents)` — so the entry is a credit that steps the running `balance_after_cents` down by that unrepaid principal (hop two); and the line's outstanding principal is recomputed, which now lands at zero because no outstanding draws remain (hop three). The line then moves to `CHARGED_OFF` and its version is bumped. Only draws that were `OUTSTANDING` are written off; already-repaid draws are untouched.

### 3.7. Line Increases and Renewal Economics

A `Servicer` requests a **line increase** against a line by supplying the `latest_bank_feed_id` (the refreshed feed supporting the increase) and the new `requested_limit_cents` (strictly positive). The request records its parent `credit_line_id`, starts in `status` `PENDING`, and is terminal at `APPROVED` or `DENIED`, with `approved_limit_cents` filled on approval and `denial_reason` set on denial. A `CreditOfficer` reviews it. Increase requests are discoverable in reverse both by their `credit_line_id` and by their `latest_bank_feed_id`.

**Approving** an increase moves it from `PENDING` to `APPROVED` and is heavily guarded. The parent line must be `ACTIVE` (enforced in the state slot, returning `ERR_INVALID_STATE` if not); the referenced latest bank feed must be `FRESH` (else `ERR_FEED_STALE`); the recomputed score must not regress; and `expected_credit_line_version` must match the line's current `version` (else `ERR_STALE_VERSION`). The non-regression rule recomputes a new score using the same weighted blend of §3.2 — but over the latest feed, the line's merchant, and the increase's requested limit — and compares it against the prior score, which is the `risk_score` of the originating application referenced by the line's `application_id`. The new score must be at least the prior score; a regression is rejected with `ERR_SCORE_BELOW_FLOOR`. On approval, the system computes the granted `approved_limit_cents`, writes it onto the parent line's `credit_limit_cents`, recomputes the line's available credit, and bumps the line's version. The increase variant of the limit calculation floors the result at the current limit so an increase never lowers the line: the granted amount is the greater of the current limit and the lesser of the requested limit and the raw advance cap (the latest feed's average daily balance times the tier advance multiple, floored to whole cents), where the tier whose advance multiple is used is the one selected by the freshly recomputed score — not the line's stored `pricing_tier`. **Denying** an increase moves it from `PENDING` to `DENIED` and records a `denial_reason`, which is one of `STALE_FEED`, `SCORE_REGRESSION`, or `LINE_NOT_ACTIVE`.

A `CreditOfficer` creates a **renewal offer** against a line to reprice its fee factor for a new term, supplying the proposed `new_fee_factor_bps` (strictly positive) and the `term_days` (strictly positive). The offer records its parent `credit_line_id`, starts in `status` `OFFERED`, and is terminal at `ACCEPTED`, `DECLINED`, or `EXPIRED`. On creation the system computes two fee-versus-APR figures. The `total_fee_cents` is the flat fee on a representative full draw of the limit: the line's `credit_limit_cents` multiplied by the offer's new fee factor, divided by 10000, rounded half up to a whole cent. The `equivalent_apr_bps` annualizes that flat fee, and the order is pinned — rate first, then annualize: the flat periodic rate is the new fee factor divided by 10000, that rate is then multiplied by 365 days divided by the term length in days to extrapolate it to a year, and the annualized rate is multiplied back by 10000 and rounded once, half up, to whole basis points.

A `Servicer` acts on the offer. **Accepting** moves it from `OFFERED` to `ACCEPTED` and, as a cross-entity effect, writes the offer's `new_fee_factor_bps` onto the parent line's `fee_factor_bps` and bumps the line's version; acceptance requires the parent line to be `ACTIVE` (enforced in the state slot as `ERR_INVALID_STATE`). **Declining** moves the offer from `OFFERED` to `DECLINED`. An `OFFERED` offer that is neither accepted nor declined expires once the logical clock has advanced at least 30 days past the offer's `created_at`; expiration is realized by a `CreditOfficer`-invoked sweep capability that moves every eligible offer to `EXPIRED` and bumps each one's version. As with the application sweep, this responds with `200 OK` and an array-typed envelope whose `data` is exactly the offers newly moved to `EXPIRED` on this call, ordered by `created_at` ascending, with the meta `total_count` equal to that swept count and no pagination applied.

### 3.8. Statements and the Reconstructed Window

A `Servicer` opens a **statement** for a line by supplying the window's `period_start` (inclusive) and `period_end` (exclusive); the statement records its parent `credit_line_id`, starts in `status` `OPEN`, and is terminal at `FINALIZED`. A statement window must not overlap any existing statement window on the same line. The overlap test is closed-containment: two windows collide when the new start is before the existing end and the existing start is before the new end; adjacency — where the new start equals an existing end — is allowed, because the windows are half-open and merely touch. A colliding window is rejected with `ERR_STATEMENT_OVERLAP`. A window whose `period_end` is not strictly after its `period_start` is a semantic error rejected with `ERR_VALIDATION`.

Once opened, a statement exposes computed totals: `opening_principal_cents`, `draws_total_cents`, `fees_assessed_cents`, `remittances_total_cents`, and `closing_principal_cents`. **Finalizing** a statement, by a `Servicer`, moves it from `OPEN` to `FINALIZED`, computes all of those totals, and bumps the version; it is permitted only when the logical clock has reached or passed the window's `period_end`, and finalizing before that instant is rejected with `ERR_INVALID_STATE`. The totals are reconstructed from the line's immutable ledger entries, time-ordered by each entry's `created_at` ascending (breaking ties by `created_at` and then by ledger insertion order, never by id). The opening principal is the `balance_after_cents` of the latest ledger entry created strictly before `period_start`, or zero if there is none. The draws total is the sum of the principal of all draws whose `drawn_at` falls in the half-open window from `period_start` up to but not including `period_end`, and the fees assessed is the analogous sum of those draws' fees. The remittances total is the sum of `amount_cents` over all `SETTLED` remittances whose settle time (their `updated_at`) falls in that same half-open window. The closing principal is the `balance_after_cents` of the latest ledger entry created strictly before `period_end`, or the opening principal if no entry falls in the window.

Ledger entries themselves are read-only and surfaced only for inspection — listable per line, listable across the system filtered by `credit_line_id`, `draw_id`, `remittance_id`, or `entry_type`, and fetchable individually. They are never created directly by a client; they are written only as side effects of draws, settlements, and charge-offs.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; operations that modify an existing resource — including state transitions and sweeps — return a `200 OK` status code. The clock-control endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/merchants` | Register a merchant (open; pre-auth) | Underwriter, Servicer, CreditOfficer |
| GET | `/merchants/{id}` | Fetch a merchant | Underwriter, Servicer, CreditOfficer |
| POST | `/merchants/{id}/blocklist` | Blocklist a merchant | CreditOfficer |
| POST | `/merchants/{id}/bank-feeds` | Ingest a Plaid bank-feed snapshot | Underwriter, Servicer |
| GET | `/merchants/{id}/bank-feeds` | List bank-feed snapshots for a merchant | Underwriter, Servicer, CreditOfficer |
| POST | `/bank-feeds/{id}/mark-stale` | Mark a bank-feed snapshot stale | Underwriter, Servicer |
| POST | `/applications` | Create a draft application | Underwriter |
| GET | `/applications/{id}` | Fetch an application | Underwriter, CreditOfficer |
| GET | `/applications` | List applications | Underwriter, CreditOfficer |
| POST | `/applications/{id}/submit` | Submit or resubmit an application | Underwriter |
| POST | `/applications/{id}/approve` | Approve a submitted application | Underwriter |
| POST | `/applications/{id}/request-revision` | Send an application back for revision | Underwriter |
| POST | `/applications/{id}/decline` | Decline a submitted application | Underwriter |
| POST | `/credit-lines` | Activate a credit line from an approved application | CreditOfficer |
| GET | `/credit-lines/{id}` | Fetch a credit line with computed balances | Underwriter, Servicer, CreditOfficer |
| GET | `/credit-lines` | List credit lines | Underwriter, Servicer, CreditOfficer |
| POST | `/credit-lines/{id}/freeze` | Freeze a line | Servicer |
| POST | `/credit-lines/{id}/unfreeze` | Unfreeze a frozen line | Servicer |
| POST | `/credit-lines/{id}/declare-default` | Declare default on a delinquent line | CreditOfficer |
| POST | `/credit-lines/{id}/charge-off` | Charge off a defaulted line | CreditOfficer |
| POST | `/credit-lines/{id}/close` | Close a paid-off active line | Servicer |
| POST | `/credit-lines/{id}/draws` | Take a draw against a line | Servicer |
| GET | `/draws/{id}` | Fetch a draw | Underwriter, Servicer, CreditOfficer |
| GET | `/credit-lines/{id}/draws` | List draws on a line | Underwriter, Servicer, CreditOfficer |
| POST | `/credit-lines/{id}/remittances` | Schedule a remittance for a line | Servicer |
| GET | `/remittances/{id}` | Fetch a remittance | Underwriter, Servicer, CreditOfficer |
| GET | `/credit-lines/{id}/remittances` | List remittances on a line | Underwriter, Servicer, CreditOfficer |
| POST | `/remittances/{id}/settle` | Settle a due remittance | Servicer |
| POST | `/remittances/{id}/cancel` | Cancel a scheduled remittance | Servicer |
| POST | `/credit-lines/{id}/line-increase-requests` | Request a line increase | Servicer |
| GET | `/line-increase-requests/{id}` | Fetch a line-increase request | Underwriter, Servicer, CreditOfficer |
| GET | `/credit-lines/{id}/line-increase-requests` | List increase requests for a line | Underwriter, Servicer, CreditOfficer |
| GET | `/line-increase-requests` | List increase requests (filterable) | Underwriter, Servicer, CreditOfficer |
| POST | `/line-increase-requests/{id}/approve` | Approve an increase | CreditOfficer |
| POST | `/line-increase-requests/{id}/deny` | Deny an increase | CreditOfficer |
| POST | `/credit-lines/{id}/renewal-offers` | Create a renewal offer | CreditOfficer |
| GET | `/renewal-offers/{id}` | Fetch a renewal offer | Underwriter, Servicer, CreditOfficer |
| GET | `/credit-lines/{id}/renewal-offers` | List renewal offers for a line | Underwriter, Servicer, CreditOfficer |
| POST | `/renewal-offers/{id}/accept` | Accept a renewal offer | Servicer |
| POST | `/renewal-offers/{id}/decline` | Decline a renewal offer | Servicer |
| POST | `/credit-lines/{id}/statements` | Open a statement window | Servicer |
| GET | `/statements/{id}` | Fetch a statement | Underwriter, Servicer, CreditOfficer |
| GET | `/credit-lines/{id}/statements` | List statements for a line | Underwriter, Servicer, CreditOfficer |
| POST | `/statements/{id}/finalize` | Finalize a statement | Servicer |
| GET | `/credit-lines/{id}/ledger-entries` | List ledger entries for a line | Underwriter, Servicer, CreditOfficer |
| GET | `/ledger-entries` | List ledger entries (filterable) | Underwriter, Servicer, CreditOfficer |
| GET | `/ledger-entries/{id}` | Fetch a single ledger entry | Underwriter, Servicer, CreditOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Underwriter, Servicer, CreditOfficer |
| POST | `/_ops/expire-applications` | Sweep submitted applications past their TTL | Underwriter |
| POST | `/_ops/expire-renewals` | Sweep offered renewals past their TTL | CreditOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MERCHANT_BLOCKLISTED` | 409 Conflict |
| `ERR_FEED_STALE` | 409 Conflict |
| `ERR_EXCESS_NSF` | 409 Conflict |
| `ERR_SCORE_BELOW_FLOOR` | 409 Conflict |
| `ERR_APPLICATION_NOT_APPROVED` | 409 Conflict |
| `ERR_REMITTANCE_NOT_DUE` | 409 Conflict |
| `ERR_REMITTANCE_OVERLAP` | 409 Conflict |
| `ERR_STATEMENT_OVERLAP` | 409 Conflict |
| `ERR_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_LINE_NOT_DRAWABLE` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |

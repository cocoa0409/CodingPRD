# P2P Business Lending API — Product Requirements Document

## 1. Introduction

The P2P Business Lending API powers a marketplace where small-business borrowers raise growth capital from accredited investors. A borrower onboards by surrendering a Plaid data feed, accepts the platform's risk grade and locked interest rate, and posts a `LoanListing` for investors to fund in fractional pledges. Once the pledged total reaches the requested principal, the listing originates into a serviceable `Loan` with a monthly amortization schedule.

Two cross-cutting concerns shape the product. The first is fairness to investors: a single borrower default cannot be allowed to wipe out a single investor, so the platform enforces a per-borrower concentration cap on every pledge, and distributes losses on charge-off pro-rata according to each investor's recorded share. The second is Regulation Crowdfunding disclosure: every public-facing transition — listing opened, listing funded, loan originated, delinquency, default, and charge-off — emits a draft `Disclosure` record whose payload is a by-value snapshot, and which is rendered legally immutable once a `ComplianceOfficer` publishes it.

Operational determinism is engineered into the platform's logical time model. There is no wall clock; `clock_day_index` on the parent `Platform` advances only when an operator explicitly calls the advance-clock capability, at which point every overdue installment, delinquent loan, defaulted loan, charged-off loan, and expired listing transitions in a single deterministic sweep. This document specifies the entity model, state machines, calculations, validations, and HTTP contract that together implement the system.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API MUST carry two headers: `X-User-ID` identifying the calling principal, and `X-User-Role` identifying the role the principal is acting as. Missing or malformed headers yield `ERR_MISSING_USER_CONTEXT` with HTTP 400. A well-formed header pair whose role is not authorized for the endpoint yields `ERR_FORBIDDEN_FOR_ROLE` with HTTP 403.

Four roles exist on the platform, with exact spellings `PlatformOperator`, `ComplianceOfficer`, `Borrower`, and `Investor`.

`PlatformOperator` is an opaque operator role. When `X-User-Role` is `PlatformOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server treats it as an audit handle and does not compare it to the `id` of any stored resource. `PlatformOperator` is the role that creates platforms, borrowers, investors, and compliance officers, attaches Plaid snapshots, advances the clock, deposits cash into investor accounts, and originates funded listings into loans.

`ComplianceOfficer` is an entity-backed role. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is the `id` of the acting `ComplianceOfficer` record on the platform; ownership and segregation-of-duties checks compare this identifier to the persisted `ComplianceOfficer`. This role approves, suspends, reinstates, and bans borrowers, and publishes `Disclosure` records.

`Borrower` is an entity-backed role. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`; ownership checks on any resource that references a `Borrower` (its listings, its loans, payments against those loans) compare the resource's `borrower_id` to `X-User-ID`.

`Investor` is an entity-backed role. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor`; the server compares the resource's `investor_id` to `X-User-ID` on every investor-scoped read or write. An `Investor` may pledge only as themselves, and may read only their own investments.

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

List endpoints accept two query parameters: `limit` defaults to 10 with a minimum of 1 and a maximum of 100, and `offset` defaults to 0 with a minimum of 0. Both are clamped to those bounds; values outside them yield `ERR_INVALID_REQUEST`. All list responses are sorted by `created_at` ascending, with the resource's `id` as a deterministic tie-breaker. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources expose four common system fields. The `id` is a server-minted UUID string with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, set on creation and refreshed on every successful mutation. The `version` is a non-negative integer that begins at 1 on creation and increments by 1 on every successful mutation; it is the optimistic-concurrency token.

Two entities are exceptions because they are append-only by design. A `PlaidSnapshot` carries only `id` and `created_at` and has neither `updated_at` nor `version`; once written it is never mutated. A `Disclosure` likewise carries only `id` and `created_at` among the common fields; mutation is forbidden by the publication contract described in §3.6, and neither `updated_at` nor `version` is exposed.

### 2.5. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When the client supplies `version`, the server compares it to the current `version` of the resource at write time. A mismatch fails the request with `ERR_INVALID_STATE_TRANSITION` and HTTP 409, since the state the client believes it is transitioning from is no longer current. When `version` is omitted from the body, the server skips the check and applies a last-writer-wins policy. A successful mutation increments `version` by 1 and refreshes `updated_at`.

### 2.6. Nested Resource Resolution

Every URL path is resolved left to right. For a path that names a platform, a borrower beneath it, and a listing beneath that borrower, the platform is resolved first, the borrower second within that platform, and the listing third within that borrower. Any path component that fails to resolve yields `ERR_NOT_FOUND` with HTTP 404 at the first failing component. A request body that supplies an `id` inconsistent with a path parameter is rejected with `ERR_INVALID_REQUEST`.

### 2.7. Logical Time and the Deterministic Clock

The platform's `clock_day_index` is a non-negative integer that starts at 0 on platform creation and advances only through the advance-clock capability described in §3.7. There is no wall-clock dependency anywhere in the system. When the operator advances the clock by some number of `days`, the server runs every system-driven transition for the day range in a single pass: scheduled installments crossing their due day move from `SCHEDULED` to `DUE`; due installments past their grace window move from `DUE` to `LATE`; loans accumulate consecutive misses and may move `ACTIVE → DELINQUENT`, then `DELINQUENT → DEFAULT`, then `DEFAULT → CHARGED_OFF`; and any open listing past its funding deadline moves `OPEN → EXPIRED`. The order of these transitions per day is exactly: installment status (first `SCHEDULED → DUE`, then `DUE → LATE`), then loan status escalation in escalating order, then listing expiry — applied to every day in the requested span before returning.

### 2.8. Money, Precision, and Rounding

All money is stored as integer cents in the platform's single ISO-4217 `currency`; there is no floating-point representation of money anywhere in the persisted state. Every calculation specifies its own rounding contract in §3 and uses the round-half-up rule, breaking ties away from zero at two decimal places (that is, the cent). Where a calculation distributes a total across multiple recipients (the monthly amortization schedule, the charge-off loss distribution), per-recipient amounts are rounded half-up to cents and the rounding residual is absorbed by the last recipient so that the sum matches the input total exactly.

### 2.9. Validation Priority

The validation rules in §3 are evaluated in a fixed priority order so that the most fundamental rejection always preempts a deeper one. Auth checks precede everything: header presence (`ERR_MISSING_USER_CONTEXT`) precedes role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Existence checks come next: every URL `id` must resolve (`ERR_NOT_FOUND`) before any state, business, or fiscal rule is evaluated. State-transition legality (`ERR_INVALID_STATE_TRANSITION`) is then checked. Segregation-of-duties rules (`ERR_SEGREGATION_VIOLATION`) precede the domain-specific referential and constraint rules. For investment creation, the order is: cross-platform check (`ERR_CROSS_PLATFORM_INVESTMENT`), then diversification cap (`ERR_DIVERSIFICATION_CAP_EXCEEDED`), then cash sufficiency (`ERR_INSUFFICIENT_CASH`), then oversubscription against the listing (`ERR_LISTING_OVERSUBSCRIBED`), and finally the denomination floor and multiple-of-cents check (`ERR_INVESTMENT_DENOMINATION`). The denomination check is intentionally last so that a structurally rejectable amount is still rejected on its merits if the prior business rules would have allowed it.

### 2.10. Append-Only Audit and Immutability

Two record families are append-only. A `PlaidSnapshot` is captured at attach time and never mutated; if the borrower's financial picture changes, an operator attaches a new snapshot, which becomes the latest and is the one used for final grading. A `Disclosure` is mutable while it is a draft (i.e., `published` is false), but once published it freezes: `published` becomes true, `published_on_day_index` is set to the current `clock_day_index`, and any further attempt to modify or delete it returns `ERR_DISCLOSURE_LOCKED` with HTTP 409. Two compliance officers racing to publish the same draft serialize first-writer-wins on the `published` flag; the loser receives `ERR_DISCLOSURE_LOCKED`.

### 2.11. Concurrency Outcomes

Beyond the OCC `version` mechanism, the platform pins specific outcomes for races on shared state. When two investments arrive on the same listing such that each, in isolation, would close the gap to `principal_cents`, the first writer succeeds in driving the listing to `FUNDED`; the second writer is rejected with `ERR_LISTING_OVERSUBSCRIBED` because the remaining capacity is zero. When a borrower withdraws an `OPEN` listing in the same instant that a final pledge would have funded it, exactly one wins on the listing's `status`; whichever loses sees the other's transition as a stale `from` state and receives `ERR_INVALID_STATE_TRANSITION`. When a borrower posts a `Payment` at the same moment the advance-clock sweep moves the loan to `CHARGED_OFF`, the clock-driven transition wins; the payment is rejected with `ERR_LOAN_NOT_PAYABLE` because the loan is no longer in `ACTIVE`, `DELINQUENT`, or `DEFAULT`.

## 3. Business Logic & Workflows

### 3.1. Platform setup and the clock

A platform is the root aggregate. Its creation requires a display `name` and accepts an optional ISO-4217 `currency` (defaulting to "USD"), along with four optional economic parameters that govern every loan on the platform: `origination_fee_bps` defaults to 300, which means three percent of principal will be deducted from the borrower's disbursement at origination; `servicing_fee_bps` defaults to 100, which on every interest distribution to investors will divert one percent of that scheduled interest as a servicing fee; `late_fee_cents` defaults to 2500, the flat fee in cents assessed each time an installment becomes late; and `max_borrower_concentration_bps` defaults to 1000, which caps any one investor's exposure to any one borrower at ten percent of that investor's committed capital. On creation, `clock_day_index` is initialized to 0.

The `clock_day_index` is the platform's only notion of time. It moves only when a `PlatformOperator` calls the advance-clock capability with a positive integer number of `days`; the body parameter is named `days` and represents the count of logical days to advance. Each individual day inside that span is processed in order, and inside each day the system runs all installment, loan, and listing transitions described in §2.7 before moving to the next day. The same capability also emits any draft `Disclosure` records that the resulting transitions require.

### 3.2. Borrower onboarding and the dual-variant grade

A borrower is created beneath a platform with a `legal_name`, a federal `ein`, a self-reported `annual_revenue_cents`, and the `requested_amount_cents` they intend to raise on their next listing. The `ein` must be unique among all borrowers on the same platform; a duplicate yields `ERR_DUPLICATE_EIN`. On creation, the borrower's `status` is `PENDING_KYC`, the `final_grade` is `UNGRADED`, the `plaid_snapshot_id` is null, and the server immediately computes the borrower's `provisional_grade` from the self-reported fields alone.

The provisional grade is a weighted score from two normalized inputs. Annual revenue is normalized linearly from a floor of 50,000 dollars (5,000,000 cents) to a ceiling of 5,000,000 dollars (500,000,000 cents), with values below the floor clamped to 0 and values above the ceiling clamped to 1. The requested amount is normalized linearly from a floor of 10,000 dollars (1,000,000 cents) to a ceiling of 500,000 dollars (50,000,000 cents), with the same clamping behavior. The two normalized values combine as `0.6` times the revenue contribution plus `0.4` times the value one minus the requested-amount contribution — that is, a larger requested amount lowers the score. The combined score is rounded half-up to four decimal places. Grade bands then apply with inclusive lower bounds: `0.80` or higher is `A`, `0.65` up to but not including `0.80` is `B`, `0.50` up to `0.65` is `C`, `0.35` up to `0.50` is `D`, and any score below `0.35` is `E`.

A `PlaidSnapshot` is attached by a `PlatformOperator` and is the input to the borrower's final grade. The body carries the snapshot's four self-evident financial inputs: `deposits_last_90d_cents` (the sum of inbound deposits across the most recent ninety days), `avg_daily_balance_cents` (the average daily balance over the snapshot window), `nsf_count_last_90d` (the count of non-sufficient-funds events in the same ninety days), and `existing_debt_service_cents` (the monthly debt service implied by other accounts the snapshot sees). The server records the `pulled_on_day_index` as the platform's current `clock_day_index`, and sets the borrower's `plaid_snapshot_id` to the new snapshot's `id` so that the most recent snapshot is always the one used for grading. Attaching a snapshot triggers a recomputation of `final_grade`.

The final grade uses the borrower's latest snapshot. Four components combine. The cashflow component is the snapshot's `deposits_last_90d_cents` divided by 90, then clamped to lie between 0 and 10,000,000 cents (zero and one hundred thousand dollars per day); the result is then divided by 10,000,000 to produce a value between 0 and 1. The reserves component is `avg_daily_balance_cents` clamped between 0 and 25,000,000 cents (zero and two hundred fifty thousand dollars), then divided by 25,000,000 to produce a value between 0 and 1. The debt-to-income ratio is computed by multiplying `existing_debt_service_cents` by 12 to annualize, then dividing by the maximum of `annual_revenue_cents` and 1 (the floor of 1 guards against division by zero); the DTI is then clamped to lie between 0 and 1 for the score, and the DTI contribution is one minus that clamped value. The NSF penalty is `nsf_count_last_90d` multiplied by `0.10` and clamped between 0 and `0.50`; the NSF contribution to the score is one minus that clamped penalty. The four components combine with weights `0.35` for cashflow, `0.30` for reserves, `0.25` for the DTI contribution, and `0.10` for the NSF contribution. The combined score is rounded half-up to four decimal places, and the same inclusive band thresholds apply: `0.80` or higher is `A`, `0.65` or higher (but below `0.80`) is `B`, `0.50` or higher is `C`, `0.35` or higher is `D`, and anything below `0.35` is `E`. If the borrower has no `PlaidSnapshot`, `final_grade` remains `UNGRADED`.

Crucially, the DTI uses the self-reported `annual_revenue_cents` rather than any Plaid-derived revenue, which is the deliberate dual-variant divergence point: a borrower with a self-reported revenue of one million dollars but a Plaid-pulled cashflow indicating only a few thousand dollars per month will receive a provisional grade of `A` from the self-report and a final grade in the `D`/`E` band once Plaid lands. The platform locks each `LoanListing`'s `grade_at_listing` from the borrower's `final_grade` at the moment the listing opens, so this divergence directly affects pricing.

Approval transitions the borrower from `PENDING_KYC` to `APPROVED` and is reserved for a `ComplianceOfficer`. The transition is rejected unless at least one `PlaidSnapshot` has been attached (otherwise `ERR_NO_PLAID_SNAPSHOT`) and `final_grade` is not `UNGRADED` (otherwise `ERR_BORROWER_UNGRADED`). As a side effect of approval, the server recomputes `final_grade` from the latest snapshot one more time before persisting the new status. Subsequent compliance actions — suspending, reinstating, and banning — are also reserved for a `ComplianceOfficer`. Suspending an `APPROVED` borrower drops them to `SUSPENDED` and cascades: every `OPEN` `LoanListing` of that borrower is moved to `WITHDRAWN`, every `COMMITTED` `Investment` on those listings is moved to `RELEASED`, and each affected investor's `cash_balance_cents` is credited by the corresponding `amount_cents` as a refund. Reinstating a `SUSPENDED` borrower returns them to `APPROVED`; this is rejected with `ERR_BORROWER_HAS_LOSSES` if the borrower has any `Loan` currently in `CHARGED_OFF` status. Banning is permanent: an `APPROVED` borrower transitions `APPROVED → BANNED` with the same `OPEN`-listing-and-`COMMITTED`-investment cascade as suspend, while a `SUSPENDED` borrower transitions `SUSPENDED → BANNED` with no further cascade since suspension already collapsed any open listings. `BANNED` is terminal.

### 3.3. Listings, tiered pricing, and the funding race

An `APPROVED` borrower (or a `PlatformOperator` acting on the borrower's behalf) creates a `LoanListing` by supplying `principal_cents` and `term_months`. The term must be exactly 12, 24, 36, 48, or 60 months. A second listing cannot be opened for a borrower who already owns an `OPEN` or `FUNDED` listing; that case yields `ERR_BORROWER_NOT_LISTABLE`, as does any attempt by a borrower whose `status` is not `APPROVED`. On open, the server snapshots `grade_at_listing` from the borrower's `final_grade`, computes the locked `interest_rate_bps` from the tiered pricing formula, sets `pledged_cents` to 0, sets `funding_deadline_day_index` to the platform's current `clock_day_index` plus 14, and emits a draft `Disclosure` with kind `LISTING_OPENED`.

The tiered pricing formula maps the listing's grade to a base interest rate in basis points and then adds a term premium. The base table is exactly `{ A: 600, B: 900, C: 1300, D: 1800, E: 2400 }`. The term premium is computed as the maximum of zero and the term in months minus 24, then multiplied by ten basis points per month — so the first 24 months carry no premium, and beyond that each additional month adds 10 bps. The final `interest_rate_bps` is the sum of the base and the term premium and remains an integer (no rounding is needed because the inputs are integers).

An investor pledges into an `OPEN` listing by supplying the pledge `amount_cents` on a listing-scoped create capability. Several validations gate the create, evaluated in the order described in §2.9. The pledge's denomination must be at least 2,500 cents and a positive integer multiple of 100 cents; otherwise the create is rejected with `ERR_INVESTMENT_DENOMINATION` and HTTP 422. The investor's `platform_id` must match the listing's `platform_id`; a cross-platform pledge yields `ERR_CROSS_PLATFORM_INVESTMENT`. A `Borrower` cannot self-invest in their own listing; an `Investor` attempting to pledge on a listing whose borrower is themselves (same platform) is rejected with `ERR_SEGREGATION_VIOLATION`. The investor's `cash_balance_cents` must be at least the proposed `amount_cents`; otherwise the create is rejected with `ERR_INSUFFICIENT_CASH`. The investor's total exposure to the listing's borrower — the sum of `amount_cents` across all of this investor's `Investment` records whose `status` is `COMMITTED` or `CONVERTED` and whose listing belongs to the same borrower as the new listing, plus the new pledge — must not exceed a cap computed as the floor of the product of the investor's `committed_capital_cents` and the platform's `max_borrower_concentration_bps` divided by 10000. The comparison is inclusive: exposure exactly equal to the cap is allowed; anything strictly greater is rejected with `ERR_DIVERSIFICATION_CAP_EXCEEDED`. Finally, the pledge cannot drive the listing's `pledged_cents` past `principal_cents`; any oversubscription yields `ERR_LISTING_OVERSUBSCRIBED`.

When the create succeeds, the server decrements the investor's `cash_balance_cents` by `amount_cents`, increases the listing's `pledged_cents` by the same amount, and persists the new `Investment` with `status` `COMMITTED` and `share_bps` initialized to 0 (it is only filled in at `CONVERTED`). If the new `pledged_cents` exactly equals `principal_cents`, the listing transitions `OPEN → FUNDED` in the same operation, and a draft `Disclosure` with kind `LISTING_FUNDED` is emitted. Two simultaneous final pledges race for the same remaining capacity; first-writer-wins on `pledged_cents`, with the loser rejected as `ERR_LISTING_OVERSUBSCRIBED` because the remaining gap is zero.

A `Borrower` may withdraw their own `OPEN` listing (a `PlatformOperator` may also do so on their behalf). The transition `OPEN → WITHDRAWN` cascades: every `COMMITTED` `Investment` on the listing is moved to `RELEASED`, and each affected investor's `cash_balance_cents` is credited by that investment's `amount_cents`. If a withdraw call races a final pledge, exactly one operation wins on the listing's `status`; the other receives `ERR_INVALID_STATE_TRANSITION`. A listing that remains underfunded past its `funding_deadline_day_index` (that is, the current `clock_day_index` is strictly greater than the deadline and `pledged_cents` is strictly less than `principal_cents`) is expired by the advance-clock sweep with the same investor refund cascade; `OPEN → EXPIRED` is a system-driven transition. `WITHDRAWN`, `EXPIRED`, and `ORIGINATED` are all terminal listing states.

### 3.4. Origination, amortization, and disbursement

A `FUNDED` listing is originated by a `PlatformOperator` (a `ComplianceOfficer` may not originate, per segregation of duties, and an attempt by them returns `ERR_SEGREGATION_VIOLATION`). Origination is also rejected if the underlying borrower is not in `APPROVED` status (`ERR_BORROWER_NOT_APPROVED`), or if any `Investment` on the listing is not in `COMMITTED` status (`ERR_LISTING_INTEGRITY`).

A successful origination atomically performs several updates. A new `Loan` is created with `listing_id` referencing the originating listing, with `borrower_id` and `platform_id` copied through, and with `principal_cents`, `interest_rate_bps`, and `term_months` copied verbatim from the listing's locked values. The loan's `origination_day_index` is set to the platform's current `clock_day_index`. Every `Investment` on the listing transitions `COMMITTED → CONVERTED` in the same operation; for each, the server computes `share_bps` as the integer result of rounding half-up the quantity `amount_cents` multiplied by 10000 then divided by the loan's `principal_cents`. Each affected investor's `outstanding_principal_cents` is incremented by the corresponding `amount_cents`. The borrower receives a net disbursement equal to `principal_cents` minus the origination fee, where the origination fee is computed as the floor of `principal_cents` multiplied by `origination_fee_bps` divided by 10000. The listing transitions `FUNDED → ORIGINATED`, the loan's `status` is set to `ACTIVE`, and a draft `Disclosure` with kind `LOAN_ORIGINATED` is emitted.

The amortization schedule is generated in the same step. Let `r` be the monthly rate computed as `interest_rate_bps` divided by 10000 and then by 12, let `n` be `term_months`, and let `P` be `principal_cents`. When `r` is zero, the level `monthly_payment_cents` is `P` divided by `n`, rounded half-up to cents. Otherwise, the level `monthly_payment_cents` is `P` times `r` times the quantity one plus `r` raised to the `n`-th power, divided by the quantity one plus `r` raised to the `n`-th power minus one, rounded half-up to cents. The schedule then produces `term_months` `Installment` records, each numbered by `sequence_number` from 1 to `n` and each with `due_day_index` set to `origination_day_index` plus `sequence_number` multiplied by 30. For each installment, `scheduled_interest_cents` is the running `principal_outstanding_cents` multiplied by `r` rounded half-up to cents; `scheduled_principal_cents` is the level `monthly_payment_cents` minus that interest, also rounded half-up; the running outstanding decreases by the scheduled principal between installments. The final installment absorbs the residual cents so that the sum of `scheduled_principal_cents` across all installments equals `principal_cents` exactly. Every installment starts with `status` `SCHEDULED`, `paid_principal_cents`, `paid_interest_cents`, and `paid_fees_cents` all initialized to zero.

### 3.5. Payments, the waterfall, and delinquency cure

A `Borrower` (or a `PlatformOperator` on the borrower's behalf) posts a `Payment` against one of the borrower's own loans, supplying the total `amount_cents`. The amount must be a positive integer cent value, and the loan's `status` must be `ACTIVE`, `DELINQUENT`, or `DEFAULT`; a payment against a `CHARGED_OFF` or `PAID_OFF` loan is rejected with `ERR_LOAN_NOT_PAYABLE`. The server records the payment's `received_on_day_index` as the platform's current `clock_day_index` and runs the waterfall allocation, persisting the result on the payment's `allocation` object and the payment's `status` as `POSTED`. The `allocation` object exposes five integer cent fields: `fees_cents` for servicing fees, `interest_cents` for scheduled interest, `principal_cents` for scheduled and prepayment principal, `late_fees_cents` for accrued late fees, and `unallocated_cents` for any cent amount that exceeds total liability.

The waterfall is strictly ordered and oldest-first within each bucket. Step one is the servicing fee on the interest currently due: the server first determines the total scheduled interest due on installments currently in `DUE` or `LATE` status; the servicing fee is computed as the floor of that scheduled interest due multiplied by `servicing_fee_bps` divided by 10000, rounded half-up to cents; the remaining payment after the fee is the input to the rest of the waterfall, and the fee total is reported on the `allocation` object as `fees_cents`. Step two is late fees, allocated against currently `LATE` installments in ascending `sequence_number` order (oldest first), with each installment's accrued portion of `late_fee_cents` paid before moving to the next; the total goes to `late_fees_cents` and increments each installment's `paid_fees_cents`. Step three is scheduled interest on overdue installments in ascending `sequence_number` order, followed by the current-period interest if any remains; the total goes to `interest_cents` and increments each installment's `paid_interest_cents`. Step four is scheduled principal on overdue installments in ascending `sequence_number` order, followed by the current-period principal; the total goes to `principal_cents` and increments each installment's `paid_principal_cents`. Step five is prepayment of principal on the next upcoming installment, with no penalty; this is also recorded in `principal_cents` and against that installment's `paid_principal_cents`. Any cent amount that remains after all five steps is recorded as `unallocated_cents` and is neither refunded nor banked. Within each bucket, the server allocates the minimum of the bucket's remaining demand and the payment's remaining cents, and stops the moment the payment is exhausted. The pinned oldest-first order is observable: if a single payment cannot satisfy the total overdue interest across two `LATE` installments, the oldest installment is fully serviced first and the next one only partially, rather than splitting proportionally.

The waterfall drives installment and loan transitions. When an installment's `paid_principal_cents` and `paid_interest_cents` together reach its scheduled principal plus scheduled interest, a `DUE` installment moves `DUE → PAID`. A `LATE` installment moves `LATE → PAID` only when the same condition holds and any accrued late fee component is also covered; in addition, if that newly-paid installment was the oldest `LATE` installment and no `LATE` installments remain on the loan, the loan's `consecutive_missed_installments` resets to 0. When `consecutive_missed_installments` returns to zero on a loan currently in `DELINQUENT`, the loan transitions `DELINQUENT → ACTIVE` (the cure transition's precondition is that all previously-`LATE` installments are now `PAID`). When `principal_outstanding_cents` reaches zero and every installment is `PAID` or `WAIVED`, the loan transitions `ACTIVE → PAID_OFF` or, if the cure and payoff happen in the same payment, `DELINQUENT → PAID_OFF`. `PAID_OFF` is terminal.

### 3.6. Delinquency, default, and charge-off

Delinquency begins inside the advance-clock sweep. For each installment the sweep processes, the move from `SCHEDULED` to `DUE` triggers when the platform's `clock_day_index` reaches or exceeds `due_day_index` and the installment is not yet fully paid. The move from `DUE` to `LATE` triggers when the platform's `clock_day_index` is strictly greater than `due_day_index` plus a five-day grace and the installment is still not fully paid; in that step, the loan's `accrued_late_fees_cents` increases by `late_fee_cents`, and the loan's `consecutive_missed_installments` increments by one. The first time `consecutive_missed_installments` moves from zero to a positive integer, the loan transitions `ACTIVE → DELINQUENT` and emits a draft `Disclosure` with kind `DELINQUENCY_NOTICE`. Further missed installments accumulate the counter.

When `consecutive_missed_installments` reaches three or more, the loan transitions `DELINQUENT → DEFAULT` during the same sweep and emits a draft `Disclosure` with kind `DEFAULT_NOTICE`. When the counter reaches five or more, the loan transitions `DEFAULT → CHARGED_OFF` and a chronological loss is booked. Specifically, the loan's `charged_off_loss_cents` is set to the sum of `principal_outstanding_cents` and `accrued_late_fees_cents` at the moment of charge-off; this is the ledger-realized loss, not a forward-looking projection from the default date, which means partial payments received between `DEFAULT` and `CHARGED_OFF` reduce the realized loss below what a forward-looking estimate would have predicted. `principal_outstanding_cents` is set to zero. Every remaining installment, regardless of its current state (`SCHEDULED`, `DUE`, or `LATE`), transitions to `WAIVED`; `WAIVED` is terminal alongside `PAID`. Every `CONVERTED` `Investment` on the loan transitions to `LOST`. A draft `Disclosure` with kind `CHARGE_OFF_NOTICE` is emitted.

The realized loss is distributed pro-rata across the loan's `CONVERTED` investments. The total loss is `principal_outstanding_cents` plus `accrued_late_fees_cents` as captured at the charge-off moment. The investments are processed in ascending `created_at` order with the investment's `id` as a deterministic tie-break. For each, a gross share is computed as the round-half-up of `total_loss` multiplied by `share_bps` divided by 10000; the actual share booked is the minimum of that gross share and the remaining loss; the remaining loss decreases by the actual share; and the investor's `outstanding_principal_cents` decreases by the actual share. Any residual cents from rounding lands on the last investment iterated (the one with the most recent `created_at`, breaking ties by `id`), so the total distributed equals `total_loss` exactly. `LOST` and `RELEASED` are terminal investment states; `CONVERTED` may persist alongside an `ACTIVE` or `DEFAULT` loan; the original `COMMITTED` state is the initial state from which both terminal-pre-origination (`RELEASED`) and post-origination (`CONVERTED`) branches descend.

### 3.7. Disclosures and the publication freeze

A `Disclosure` is the platform's append-only audit primitive. Every public-facing state transition listed in §3.3 through §3.6 emits a draft disclosure: opening a listing emits `LISTING_OPENED`; the system-driven funding of a listing emits `LISTING_FUNDED`; originating a loan emits `LOAN_ORIGINATED`; the first miss on a loan emits `DELINQUENCY_NOTICE`; the third consecutive miss emits `DEFAULT_NOTICE`; and the fifth consecutive miss emits `CHARGE_OFF_NOTICE`. A seventh kind, `MATERIAL_AMENDMENT`, is reserved for compliance-driven amendments. Each disclosure carries `subject_type` — one of `BORROWER`, `LISTING`, `LOAN`, `INVESTMENT` — and `subject_id` referencing the specific entity, along with `kind`, a `payload`, and the `published` flag (which begins false).

The `payload` is assembled at transition time as a by-value snapshot of the subject's then-current public-facing fields, and subsequent changes to the underlying entity do not mutate the disclosure. The specific snapshots are: for `LISTING_OPENED`, the listing's `principal_cents`, `interest_rate_bps`, `term_months`, and `grade_at_listing`; for `LISTING_FUNDED`, the listing's `principal_cents` and `interest_rate_bps` together with the investor count on the listing; for `LOAN_ORIGINATED`, the loan's `principal_cents`, `interest_rate_bps`, `term_months`, `monthly_payment_cents`, and the origination fee in cents (computed as described in §3.4); for `DELINQUENCY_NOTICE`, the loan's `principal_outstanding_cents`, `consecutive_missed_installments`, and `accrued_late_fees_cents`; for `DEFAULT_NOTICE`, the loan's `principal_outstanding_cents` and `consecutive_missed_installments`; and for `CHARGE_OFF_NOTICE`, the loan's `charged_off_loss_cents` and the investor count on the loan.

Publication is reserved for a `ComplianceOfficer`; a `PlatformOperator` attempting to publish receives `ERR_SEGREGATION_VIOLATION`. The publish capability moves the disclosure `DRAFT → PUBLISHED` only if `payload` is non-empty and the subject is still in the state that produced the draft — for example, a `LISTING_FUNDED` draft cannot be published if the listing has since moved to `WITHDRAWN` or `EXPIRED`. Either failure mode yields `ERR_DISCLOSURE_STALE`. On a successful publish, `published` is set to true and `published_on_day_index` is set to the platform's current `clock_day_index`. From that point forward, the disclosure is immutable; any update or delete attempt returns `ERR_DISCLOSURE_LOCKED`. Two compliance officers racing to publish the same draft serialize on `published`: the first writer succeeds, the second receives `ERR_DISCLOSURE_LOCKED`.

### 3.8. Investors, cash flow, and registry

An `Investor` is registered by a `PlatformOperator` with a `display_name`, an `accreditation_status` (either `ACCREDITED` or `NON_ACCREDITED`), and a self-declared `committed_capital_cents`. The new investor starts with `cash_balance_cents` and `outstanding_principal_cents` at zero and `status` at `ACTIVE`; `SUSPENDED` and `CLOSED` are the other valid investor states. Cash arrives through an operator-initiated deposit capability that supplies `amount_cents` and credits `cash_balance_cents` accordingly. `cash_balance_cents` is debited by `amount_cents` on every successful pledge, credited back on every `COMMITTED → RELEASED` transition (whether driven by withdraw, expiry, suspend, or ban), and is never affected directly by origination, payment allocation, or charge-off. `outstanding_principal_cents` is incremented at `COMMITTED → CONVERTED` by `amount_cents` and decremented at `CONVERTED → LOST` by that investor's actual share of the realized loss as computed in §3.6.

Reads of investors and their investments are scoped to ownership. An `Investor` may only retrieve their own investor record and only list their own investments; the server compares `X-User-ID` to the resource's `investor_id` and rejects cross-investor reads with `ERR_FORBIDDEN_FOR_ROLE`. `PlatformOperator` and `ComplianceOfficer` may read across the platform. The investments-list capability accepts the optional filters `status`, `loan_id`, `limit`, and `offset`. The listings-list capability accepts the optional filters `borrower_id`, `status`, `grade`, `limit`, and `offset`. The installments-list capability under a loan accepts `status`, `limit`, and `offset`. The disclosures-list capability accepts `subject_type`, `subject_id`, `kind`, `published`, `limit`, and `offset`.

### 3.9. Compliance officers

A `ComplianceOfficer` is registered by a `PlatformOperator` with a `display_name`, and starts at `ACTIVE`; `INACTIVE` is the other valid state. The officer is the principal behind every `ComplianceOfficer`-authorized action — approving, suspending, reinstating, and banning borrowers, and publishing disclosures. The officer's `id` is what populates `X-User-ID` when the role is `ComplianceOfficer`, which the server uses to attribute compliance actions. Segregation of duties forbids the officer from originating loans, from creating listings on a borrower's behalf, from pledging investments, and from posting payments: any such attempt returns `ERR_SEGREGATION_VIOLATION` or `ERR_FORBIDDEN_FOR_ROLE` depending on whether the role is structurally barred from the endpoint or barred by a duty-segregation rule on top of an endpoint where their role would otherwise be permitted.

## 4. Endpoint Definitions

All POST endpoints that create a new resource return HTTP 201; all other successful POST endpoints (state transitions, deposits) and all GET endpoints return HTTP 200. Every endpoint is rooted under `/platforms`. The table below lists method, path, a one-line description, and the roles authorized to call the endpoint. The request body, response body, and side effects of each endpoint are specified by the prose in §3 — implementers must consult §3 for the full contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/platforms` | Create a Platform | `PlatformOperator` |
| GET | `/platforms/{platformId}` | Get a Platform | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| POST | `/platforms/{platformId}/advance_clock` | Advance the deterministic test clock by `days`; run all system transitions in order | `PlatformOperator` |
| POST | `/platforms/{platformId}/borrowers` | Create a Borrower (starts `PENDING_KYC`) | `PlatformOperator` |
| GET | `/platforms/{platformId}/borrowers/{borrowerId}` | Get a Borrower | `PlatformOperator`, `ComplianceOfficer`, `Borrower` |
| POST | `/platforms/{platformId}/borrowers/{borrowerId}/plaid_snapshots` | Attach an immutable Plaid snapshot to a borrower; recomputes `final_grade` | `PlatformOperator` |
| POST | `/platforms/{platformId}/borrowers/{borrowerId}/approve` | Approve a `PENDING_KYC` borrower | `ComplianceOfficer` |
| POST | `/platforms/{platformId}/borrowers/{borrowerId}/suspend` | Suspend a borrower (cascade-withdraws OPEN listings) | `ComplianceOfficer` |
| POST | `/platforms/{platformId}/borrowers/{borrowerId}/reinstate` | Reinstate a `SUSPENDED` borrower | `ComplianceOfficer` |
| POST | `/platforms/{platformId}/borrowers/{borrowerId}/ban` | Permanently ban a borrower | `ComplianceOfficer` |
| POST | `/platforms/{platformId}/investors` | Create an Investor | `PlatformOperator` |
| GET | `/platforms/{platformId}/investors/{investorId}` | Get an Investor | `PlatformOperator`, `ComplianceOfficer`, `Investor` |
| POST | `/platforms/{platformId}/investors/{investorId}/deposits` | Credit an investor's `cash_balance_cents` | `PlatformOperator` |
| POST | `/platforms/{platformId}/borrowers/{borrowerId}/listings` | Create a LoanListing for an `APPROVED` borrower | `Borrower`, `PlatformOperator` |
| GET | `/platforms/{platformId}/listings/{listingId}` | Get a LoanListing | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| GET | `/platforms/{platformId}/listings` | List LoanListings (filters: `borrower_id`, `status`, `grade`, `limit`, `offset`) | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| POST | `/platforms/{platformId}/listings/{listingId}/withdraw` | Withdraw an `OPEN` listing | `Borrower`, `PlatformOperator` |
| POST | `/platforms/{platformId}/listings/{listingId}/originate` | Originate a `FUNDED` listing into a `Loan` | `PlatformOperator` |
| POST | `/platforms/{platformId}/listings/{listingId}/investments` | Pledge into an `OPEN` listing | `Investor` |
| GET | `/platforms/{platformId}/investments/{investmentId}` | Get an Investment | `PlatformOperator`, `ComplianceOfficer`, `Investor` |
| GET | `/platforms/{platformId}/investors/{investorId}/investments` | List an investor's investments (filters: `status`, `loan_id`, `limit`, `offset`) | `PlatformOperator`, `ComplianceOfficer`, `Investor` |
| GET | `/platforms/{platformId}/loans/{loanId}` | Get a Loan | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| GET | `/platforms/{platformId}/loans/{loanId}/installments` | List a Loan's installments (filters: `status`, `limit`, `offset`) | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| POST | `/platforms/{platformId}/loans/{loanId}/payments` | Post a Payment against a loan | `Borrower`, `PlatformOperator` |
| GET | `/platforms/{platformId}/payments/{paymentId}` | Get a Payment (including its `allocation`) | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| GET | `/platforms/{platformId}/disclosures/{disclosureId}` | Get a Disclosure | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| GET | `/platforms/{platformId}/disclosures` | List Disclosures (filters: `subject_type`, `subject_id`, `kind`, `published`, `limit`, `offset`) | `PlatformOperator`, `ComplianceOfficer`, `Borrower`, `Investor` |
| POST | `/platforms/{platformId}/disclosures/{disclosureId}/publish` | Publish (lock) a DRAFT Disclosure | `ComplianceOfficer` |
| POST | `/platforms/{platformId}/compliance_officers` | Register a ComplianceOfficer | `PlatformOperator` |
| GET | `/platforms/{platformId}/compliance_officers/{officerId}` | Get a ComplianceOfficer | `PlatformOperator`, `ComplianceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_SEGREGATION_VIOLATION` | 403 |
| `ERR_DUPLICATE_EIN` | 409 |
| `ERR_NO_PLAID_SNAPSHOT` | 409 |
| `ERR_BORROWER_UNGRADED` | 409 |
| `ERR_BORROWER_NOT_APPROVED` | 409 |
| `ERR_BORROWER_NOT_LISTABLE` | 409 |
| `ERR_BORROWER_HAS_LOSSES` | 409 |
| `ERR_LISTING_OVERSUBSCRIBED` | 409 |
| `ERR_LISTING_INTEGRITY` | 409 |
| `ERR_DIVERSIFICATION_CAP_EXCEEDED` | 409 |
| `ERR_CROSS_PLATFORM_INVESTMENT` | 409 |
| `ERR_INSUFFICIENT_CASH` | 409 |
| `ERR_INVESTMENT_DENOMINATION` | 422 |
| `ERR_LOAN_NOT_PAYABLE` | 409 |
| `ERR_DISCLOSURE_LOCKED` | 409 |
| `ERR_DISCLOSURE_STALE` | 409 |

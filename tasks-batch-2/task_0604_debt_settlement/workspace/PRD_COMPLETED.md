# Debt Settlement API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Debt Settlement Program API, a back-office platform modeled on consumer debt-relief operators such as National Debt Relief and Freedom Debt Relief. The system manages the full arc of an enrolled debtor's relief journey: a debtor enrolls a portfolio of unsecured debts, funds a dedicated savings account through scheduled monthly deposits, and waits while negotiation specialists secure settlement offers from creditors for a fraction of the outstanding balance. When an offer is accepted, the dedicated account funds the principal, a tiered settlement fee accrues, the creditor debt closes, and — where the forgiven balance is large enough — a cancellation-of-debt tax record is issued for IRS 1099-C reporting.

The platform is, at its heart, a ledger-reconciliation engine wrapped in a compliance discipline. Every dollar that flows into the dedicated account and every dollar disbursed to a creditor or collected as a fee must reconcile exactly, so the system maintains both a forward-looking projection of what a portfolio is expected to save and a realized tally of what it has actually saved. Layered over the ledger are protective gates: an account whose owner stops depositing slips into delinquency and then default, freezing settlement activity; an offer cannot be accepted unless the account is projected to cover the payout without breaching a protective reserve; and creditor lawsuits, drops, re-enrollments, and settlement reversals each ripple a precisely defined cascade of state changes through the portfolio. This specification defines those mechanics so that an implementation behaves identically to the reference contract under all of them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles: `ProgramAdmin`, `NegotiationAgent`, and `Client`. When a known, authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles divide the work into non-overlapping operational surfaces with a shared read surface. A `ProgramAdmin` is an operator who creates clients, enrolls programs and debts, activates and completes programs, refers debts to litigation and dismisses lawsuits, voids settlements, and drives the test clock. A `NegotiationAgent` is a settlement specialist who records creditor offers, accepts or rejects them, funds settlements, and completes them. A `Client` is the enrolled debtor; the client funds the dedicated account through deposits, cures missed deposits, and may drop the program. Recording and curing deposits are shared between `Client` and `ProgramAdmin`; all read (GET) endpoints are available to any authenticated role, subject to the client-scoping rule below.

Both `ProgramAdmin` and `NegotiationAgent` carry an **opaque** identity: when `X-User-Role` is `ProgramAdmin` or `NegotiationAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. The `Client` role is **entity-backed**: when `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity. Ownership checks on any resource that references a client compare the program's `client_id` to `X-User-ID`. Specifically, for the two client-exclusive operations — recording a deposit and dropping a program — the acting client must own the target program; if the program's `client_id` does not equal `X-User-ID`, the request is rejected with `ERR_NOT_PROGRAM_OWNER` (HTTP 403). A client's read access is likewise scoped to programs they own; a `Client` reading any resource scoped to a program they do not own — or reading a `Client` record whose `id` is not their own `X-User-ID` — is rejected with `ERR_NOT_PROGRAM_OWNER` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the system logical clock (§2.4) rather than wall-clock time.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and a `limit` below 1 or above 100 (or a non-integer `limit`, or a negative or non-integer `offset`) is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than clamped. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order, with ties broken by ascending `id`. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Logical Clock

Every primary resource — `Program`, `Client`, `DedicatedAccount`, `Debt`, `MonthlyDeposit`, `SettlementOffer`, `Settlement`, `SettlementFee`, `Lawsuit`, and `TaxEvent` — carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on every mutation of that resource. Derived fields recomputed on a resource count as mutations of that resource for the purpose of `updated_at` and `version`.

The `created_at` and `updated_at` timestamps minted on creation and mutation are themselves read from this logical clock, not from wall-clock time. The system runs on a **logical clock** rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant; all time-dependent evaluations — offer expiry, the forward-looking deposit projection, and the tax year of a completed settlement — are measured against this logical clock.

### 2.5. Nested Reference Resolution and Existence Ordering

The resource topology is flat: programs, clients, debts, deposits, offers, settlements, fees, lawsuits, tax events, and accounts are all peer top-level collections, and cross-references between them travel as foreign-key fields in the request body rather than as nested URL segments. Existence is nonetheless validated in a strict left-to-right order: the identifier named in the URL path is resolved first, then each foreign key carried in the body, in declaration order. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later reference or business rule is evaluated. This applies to every resource endpoint and covers references to a program, debt, offer, settlement, lawsuit, deposit, tax event, or account.

### 2.6. Request Validation and Field Constraints

After authentication, authorization, and existence resolution, the system validates the request body itself: required fields must be present, enum-typed fields must carry a recognized value, and numeric fields must respect their ranges. An offer's `offer_pct` and a program's `target_settlement_pct` must each be greater than zero and at most one. Monetary amounts — a program's `monthly_deposit_amount`, a debt's `original_balance`, and a deposit's `amount` — must be strictly greater than zero. A program's `deposit_day_of_month` must be an integer from 1 through 28 inclusive and defaults to 1 when omitted. A program's `reserve_floor` must be at least zero and defaults to zero. A client's `state_code` is a two-letter US state code; it is validated only as a non-empty string of exactly two characters, with no check that those characters form a recognized US state abbreviation. Any malformed body, missing required field, invalid enum, or out-of-range number is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Monetary Precision and Rounding

All monetary calculations are performed in decimal arithmetic and rounded to exactly two decimal places using the round-half-up convention. Where a calculation proceeds in steps — most importantly the settlement quote — rounding is applied **per step**: the settlement principal is rounded to two decimal places first, and the fee is then computed and rounded on the already-rounded principal, not on an unrounded intermediate. Per-debt portfolio figures are likewise rounded individually before being summed. Settlement-fee rate bands (the values 0.25, 0.22, and 0.18) and the litigation surcharge are treated as exact rates, not rounded monetary amounts. The running client refund total `refunded_to_client_cents` is stored as an integer number of cents.

### 2.8. The Dedicated-Account Ledger Principle

Each program owns exactly one `DedicatedAccount`, created automatically at enrollment, and that account is the single source of truth for the program's cash. Its `balance` is always the sum of every cleared deposit's `amount` (deposits in `CLEARED` status), minus the `funded_amount` of every settlement that is `FUNDED` or `COMPLETED`, minus the `amount` of every settlement fee that is `PAID`. The account also exposes `lifetime_deposited` — the sum of `amount` over `CLEARED` deposits — and `lifetime_disbursed` — the sum of `funded_amount` over `FUNDED` and `COMPLETED` settlements plus the `amount` of `PAID` fees. The account carries a `program_id` linking it to its program and a `reserve_floor`, the protective minimum balance that must remain after any settlement funding. Because balance is derived purely from the ledger of deposits, settlements, and fees, every compensating reversal must leave it conserved: voiding a settlement returns the account to its exact pre-funding balance.

### 2.9. Account Standing and the Delinquency Ladder

Independently of where a program sits in its lifecycle, every program tracks an `account_standing` derived from its `missed_deposit_count` — the number of `MonthlyDeposit` rows recorded in `MISSED` status. Standing begins at `CURRENT`. The moment the missed count reaches at least one but stays below three (a count of 1 or 2), standing becomes `DELINQUENT`; the moment the missed count reaches three or more, standing becomes `DEFAULTED`. Curing missed deposits walks the ladder back down: when a cure drops the missed count to 1 or 2, a `DEFAULTED` program returns to `DELINQUENT`; when the missed count reaches zero, the program returns to `CURRENT` (from either `DELINQUENT` or `DEFAULTED`). These standing transitions are computed automatically by the system whenever the missed count changes; they are never requested directly. While a program is `DELINQUENT`, no settlement offer may be accepted, though offers may still be recorded. While a program is `DEFAULTED`, offer acceptance, settlement funding, and program completion are all blocked until the standing is cured.

### 2.10. Optimistic Concurrency on Offer Acceptance

Accepting a settlement offer is guarded by optimistic concurrency control against the parent program. The accept request must carry `expected_program_version`, the `version` of the `Program` the client last observed. If `expected_program_version` does not match the program's current `version`, the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the system's defense against double-committing the dedicated account: because accepting any offer on a debt bumps the program's `version`, a prior acceptance on a sibling offer renders every other in-flight acceptor's observed version stale, and the stale acceptor is turned away rather than allowed to fund a second settlement the account cannot cover. No other endpoint takes a version field; only offer acceptance carries `expected_program_version`.

### 2.11. Cascades, Compensation, and Version Propagation

Many operations in this domain mutate more than one entity. When a program is dropped or completed, when a settlement is funded, completed, or voided, and when a lawsuit resolves, the system performs a defined cascade of secondary state changes described in §3. Each entity touched by a cascade independently refreshes its own `updated_at` and increments its own `version`. The program-phase transitions (activation, completion, and the two drop paths) each increment `Program.version` by one as part of their effect. Compensating reversals — the settlement void path — restore prior values exactly rather than applying fresh debits, so that the dedicated-account ledger remains conserved.

## 3. Business Logic & Workflows

### 3.1. Enrollment: Clients, Programs, and the Dedicated Account

Everything begins with a debtor. A `ProgramAdmin` creates a `Client` by supplying the client's `full_name`, `email`, and two-letter `state_code`; the system initializes the client's `refunded_to_client_cents` running total to zero. The administrator then enrolls a `Program` for that client by referencing the `client_id` and supplying the recurring `monthly_deposit_amount`. Three further inputs are optional at enrollment: `deposit_day_of_month` (the day the recurring deposit is due, defaulting to 1), `target_settlement_pct` (the forward-looking assumed settlement fraction used by the savings estimate, defaulting to 0.50, meaning the program assumes each debt settles at half its balance), and `reserve_floor` (the protective account minimum, defaulting to 0). A newly enrolled program enters lifecycle phase `ENROLLING` with `account_standing` of `CURRENT`, all computed aggregates initialized to zero, and an automatically created `DedicatedAccount` whose `balance` starts at zero and whose `reserve_floor` carries the supplied value.

A program exposes a rich set of computed aggregates whenever it is read, each kept current: `total_enrolled_balance`, the fee band `fee_tier_pct`, `missed_deposit_count`, `estimated_total_savings`, `realized_total_savings`, and the `completion_eligible` flag. Reading a program also lazily expires any of its offers that have passed their deadline before the aggregates are computed.

### 3.2. Building the Debt Portfolio and Snapshotting the Fee Band

The administrator adds debts to a program one at a time, each by referencing the program through `program_id` and supplying the `creditor_name`, an `account_number`, and the `original_balance` owed. Debt enrollment is not gated by the program's lifecycle phase; a debt may be added while the program is `ENROLLING` or `ACTIVE`. The `account_number` must be unique within its program; a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER` (HTTP 409). A new debt enters status `ENROLLED`.

At the instant a debt is enrolled, the system snapshots that debt's settlement-fee rate, `fee_rate_pct`, and freezes it for the life of the debt. The snapshot is driven by the program's total enrolled balance. First, the system sums `original_balance` across the program's existing debts whose status is `ENROLLED`, `IN_NEGOTIATION`, `SETTLED`, or `LAWSUIT` — debts in `WITHDRAWN` status are excluded — and then adds the new debt's `original_balance` to that sum. From the resulting total it selects the band: a total below 10,000 dollars yields a rate of 0.25; a total of at least 10,000 but below 30,000 dollars yields 0.22; a total of 30,000 dollars or more yields 0.18. That selected band is frozen onto the new debt as its `fee_rate_pct`. The program's own `total_enrolled_balance` and `fee_tier_pct` are recomputed over the same set of statuses. Because the band is chosen from a running total, the same physical debt can receive different rates across two different programs (for example after a drop and re-enroll), since re-enrollment recomputes the snapshot from the new program's portfolio.

Each debt also carries computed figures that stay at their defaults until it settles: `current_balance` equals `original_balance` until the debt reaches `SETTLED` and then becomes zero (equivalently, `original_balance` minus `settled_amount` minus `forgiven_amount`); `settled_amount` is the principal actually paid to the creditor and is zero until settlement; `forgiven_amount` is the cancellation-of-debt amount, namely `original_balance` minus `settled_amount`, and is zero until settlement; and `settled_offer_id` references the offer that produced the settlement and is null until then.

### 3.3. Funding the Account: Deposits, Misses, and Cures

Either a `Client` (the program owner) or a `ProgramAdmin` records a `MonthlyDeposit` against a program by supplying `program_id`, the `scheduled_for` instant the deposit is recorded for, and the `amount`. The deposit's `status` may be supplied; when omitted it defaults to `CLEARED`. A `CLEARED` deposit increases the dedicated account's balance; a deposit recorded as `MISSED` increments the program's `missed_deposit_count` and triggers recomputation of `account_standing` (which may move the program from `CURRENT` to `DELINQUENT` or `DEFAULTED` per the ladder). A deposit may also be `RETURNED`.

At most one `CLEARED` deposit may occupy a given UTC calendar-month bucket for a program. A month bucket is the half-open interval running from the first instant of a deposit's UTC month up to, but not including, the first instant of the following UTC month. If a `CLEARED` deposit's `scheduled_for` falls in a month bucket already occupied by another `CLEARED` deposit on the same program, it is rejected with `ERR_DEPOSIT_MONTH_OCCUPIED` (HTTP 409). Because the upper bound is exclusive, a deposit whose `scheduled_for` lands exactly on the first instant of the next month belongs to that next bucket, not the occupied one.

A deposit recorded as `MISSED` can later be cured by the client or an administrator through a catch-up payment. Curing requires the deposit to be in `MISSED` status; a cure attempted on a deposit in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Curing transitions the deposit from `MISSED` to `CLEARED`, decrements the program's `missed_deposit_count`, recomputes `account_standing` (potentially walking it back from `DEFAULTED` to `DELINQUENT` to `CURRENT`), and increases the dedicated account's balance by the cured amount. The month-bucket uniqueness rule is not re-evaluated on a cure, so curing may place a second `CLEARED` deposit in a month bucket already occupied by another.

### 3.4. Activating the Program

Once at least one debt is in place, a `ProgramAdmin` activates the program, advancing `program_phase` from `ENROLLING` to `ACTIVE`. Activation requires the program to currently be in `ENROLLING`; an attempt from any other phase is rejected with `ERR_INVALID_STATE` (HTTP 409). It further requires that the program hold at least one debt in `ENROLLED` status; with no enrolled debt the activation is rejected with `ERR_NO_ENROLLED_DEBTS` (HTTP 409). Activation increments `Program.version` by one. Offers and the negotiation lifecycle require the program to be `ACTIVE`; deposits, by contrast, are not gated by lifecycle phase and may be recorded in any phase (including `ENROLLING`).

### 3.5. Recording Creditor Offers and Pricing the Quote

A `NegotiationAgent` records a creditor's settlement offer against a specific debt by supplying `program_id`, the `debt_id` being settled, the creditor's offered fraction `offer_pct`, and the `due_date` by which the settlement must be funded. The offer's `debt_id` must belong to the same program named by `program_id`; a `debt_id` that resolves to an existing debt under a different program is rejected with `ERR_NOT_FOUND` (HTTP 404). A new offer enters status `PENDING`. If the targeted debt was `ENROLLED`, recording the first offer advances it from `ENROLLED` to `IN_NEGOTIATION`; this requires the parent program to be `ACTIVE` and the debt to be `ENROLLED`, and a violation of either surfaces as `ERR_INVALID_STATE`. Further offers may be recorded against a debt already in `IN_NEGOTIATION` or `LAWSUIT` (the program must still be `ACTIVE`, else `ERR_INVALID_STATE`), and these leave the debt's status unchanged; an offer against a terminal debt (`SETTLED` or `WITHDRAWN`) is rejected with `ERR_INVALID_STATE`.

When the offer is recorded, the system computes two figures. The `settlement_amount` is the principal that would be paid: the debt's `current_balance` multiplied by `offer_pct`, rounded half-up to two decimal places. The `projected_fee` is then computed on that rounded principal: `settlement_amount` multiplied by the effective fee rate, again rounded half-up to two decimal places. The effective fee rate is the debt's frozen `fee_rate_pct` in the ordinary case; but when the debt is in `LAWSUIT` status, the effective rate carries a litigation surcharge of 0.03 added to the base rate, with the result capped so it never exceeds 0.25. In other words, for a litigated debt the effective rate is the smaller of (the frozen rate plus 0.03) and 0.25, while for an `ENROLLED` or `IN_NEGOTIATION` debt no surcharge applies and the effective rate is exactly the frozen rate. Because the offer references a debt whose balance has not yet been settled, `current_balance` here equals the debt's `original_balance`.

An offer's `due_date` must lie strictly after the current logical clock; an offer whose `due_date` is at or before the current time is already expired and cannot be created, drawing `ERR_OFFER_EXPIRED` (HTTP 409). Offers on the same debt must also be spaced apart in time. Treat each existing `PENDING` offer's `due_date` as the center of a closed buffer window extending 30 days on either side. A new offer collides when its `due_date` falls within 30 days of an existing `PENDING` offer's `due_date` on the same debt — that is, when the absolute gap between the two due dates is 30 days or fewer, so two offers exactly 30 days apart still collide because their closed buffers touch. A collision is rejected with `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409).

A `PENDING` offer that is not acted on expires automatically once the logical clock passes its `due_date`. Expiry is observed lazily — on reading the offer, on listing offers, and at the moment an acceptance is attempted — moving the offer to `EXPIRED`. An attempt to accept an already-expired offer fails with `ERR_OFFER_EXPIRED`. An offer also expires as a cascade when its parent debt is withdrawn.

### 3.6. Accepting and Rejecting Offers

A `NegotiationAgent` rejects a `PENDING` offer, moving it to `REJECTED`; rejection requires the offer to be `PENDING`, otherwise `ERR_INVALID_STATE`. Accepting an offer is the pivotal commitment and is gated by an ordered battery of checks. The acceptance request carries `expected_program_version`. Acceptance moves the offer from `PENDING` to `ACCEPTED`, and as a side effect every sibling `PENDING` offer on the same debt is moved to `REJECTED` and the program's `version` is incremented by one.

The preconditions on acceptance are evaluated in the following priority order, so that the earliest-failing condition determines the error returned. After the universal authentication, authorization, existence, and request-validity checks, the system verifies that the offer is `PENDING`; an offer that has expired (including one expired lazily at this moment) yields `ERR_OFFER_EXPIRED` (HTTP 409), while any other non-`PENDING` status yields `ERR_INVALID_STATE` (HTTP 409). It then enforces account standing: a `DEFAULTED` program blocks acceptance with `ERR_ACCOUNT_DEFAULTED` (HTTP 409), and a `DELINQUENT` program blocks acceptance with `ERR_ACCOUNT_DELINQUENT` (HTTP 409). Next it confirms the debt does not already carry another `ACCEPTED` offer; a second acceptance on a debt that already has one is rejected with `ERR_OFFER_ALREADY_ACCEPTED` (HTTP 409). The system then applies the forward-looking reserve check (below), rejecting a shortfall with `ERR_PROJECTED_RESERVE_SHORTFALL` (HTTP 402). Finally, the optimistic-concurrency check requires `expected_program_version` to equal the program's current `version`, rejecting a mismatch with `ERR_STALE_VERSION` (HTTP 412).

The **forward-looking reserve check** asks whether the account is projected to cover this settlement by the offer's `due_date` without breaching the protective floor. The projected balance is the dedicated account's current `balance` plus the program's `monthly_deposit_amount` for each scheduled deposit day that falls strictly after the current logical clock and on or before the offer's `due_date` (the projection window is open at the lower end and closed at the `due_date`). Acceptance passes only when that projected balance is at least the sum of the offer's `settlement_amount`, its `projected_fee`, and the account's `reserve_floor`; otherwise it is the projected shortfall described above.

### 3.7. Funding and Completing a Settlement

With an offer accepted, a `NegotiationAgent` funds the `Settlement` by supplying `program_id` and the `offer_id` of the accepted offer; the offer must belong to the named program, and an `offer_id` resolving to an offer under a different program is rejected with `ERR_NOT_FOUND` (HTTP 404). The settlement copies the offer's `debt_id` into its own `debt_id` and also retains the source `offer_id` as a field on the settlement. Funding debits the dedicated account: the settlement's `funded_amount` equals the offer's `settlement_amount` and is subtracted from the account balance, the settlement enters status `FUNDED`, a `SettlementFee` is created in `OUTSTANDING` status at the same effective fee rate, and the settlement's `forgiven_amount` is set to the debt's `original_balance` minus the `funded_amount`. Funding may only draw from an offer that is `ACCEPTED` and has not already produced a non-voided settlement; a request against an offer that is not in that condition is rejected with `ERR_OFFER_NOT_ACCEPTED` (HTTP 409). Funding is also subject to an instantaneous reserve check: at funding time the account's current `balance` must be at least the sum of `settlement_amount`, `projected_fee`, and `reserve_floor`, and a shortfall is rejected with `ERR_INSUFFICIENT_RESERVE` (HTTP 402). Funding is blocked while the program is `DEFAULTED`, drawing `ERR_ACCOUNT_DEFAULTED`.

Completing a funded settlement is the act that closes the creditor debt and is performed by a `NegotiationAgent`. Completion requires the settlement to be `FUNDED` (else `ERR_INVALID_STATE`) and the program not to be `DEFAULTED` (else `ERR_ACCOUNT_DEFAULTED`). On completion the settlement moves from `FUNDED` to `COMPLETED`, and a defined cascade fires. The parent debt becomes `SETTLED`: its `settled_amount` is set to the settlement's `funded_amount`, its `forgiven_amount` becomes `original_balance` minus `funded_amount`, its `current_balance` falls to zero, and its `settled_offer_id` is set to the originating offer. The associated `SettlementFee` — which carries a `program_id` for its owning program and a `settlement_id` linking it back to the settlement it was accrued against — moves from `OUTSTANDING` to `PAID`, which debits the dedicated account by the fee amount. The `amount` of that fee is the settlement's `funded_amount` multiplied by the effective fee rate, rounded half-up to two decimal places, where the effective rate follows the same litigation-surcharge rule as the offer quote (the frozen rate, plus 0.03 capped at 0.25 when the debt was litigated). When the debt that completes was under an open `REFERRED` lawsuit, that lawsuit cascades to `RESOLVED_SETTLED`. The completion path applies whether the debt entered settlement from `IN_NEGOTIATION` or from `LAWSUIT`; the only difference is that the litigated path carries the surcharged effective rate into the fee.

Completion also issues a cancellation-of-debt tax record. The forgiven amount is the debt's `original_balance` minus the settlement's `funded_amount`. A `TaxEvent` is always issued whenever the forgiven amount is greater than zero. It records a `program_id` for its owning program, a `source_settlement_id` pointing back to the settlement that generated it, the `forgiven_amount` copied from the settlement, a `tax_year` equal to the UTC calendar year of the completion instant on the logical clock, and a `reportable` flag that is true when the forgiven amount is at least 600 dollars (the IRS 1099-C reporting threshold) and false when it is greater than zero but below 600. The event enters status `ISSUED`.

### 3.8. Voiding a Settlement: Compensating Reversal

When a creditor reneges after funding, a `ProgramAdmin` voids the settlement, which must be `FUNDED` (else `ERR_INVALID_STATE`). Voiding is a compensating reversal that undoes the funding exactly. The `funded_amount` is credited back to the dedicated account, and the linked `SettlementFee` — still `OUTSTANDING` — moves to `WAIVED` so that no fee is ever debited for this aborted settlement. The parent debt reverts to `IN_NEGOTIATION`, with its `current_balance` restored to `original_balance` and its `settled_amount`, `forgiven_amount`, and `settled_offer_id` reset to their pre-settlement defaults. The source offer reverts from `ACCEPTED` back to `PENDING` so it can be re-opened. Any `TaxEvent` that had been issued for this settlement moves to `VOIDED`, after which its forgiven amount is no longer reportable. The settlement itself enters `VOIDED`. The governing invariant is account conservation: after a void the dedicated account's balance returns to exactly its value before funding.

### 3.9. Litigation: Referral, the Surcharge, and Dismissal

A `ProgramAdmin` refers a debt to litigation by creating a `Lawsuit` against it, supplying `program_id`, the `debt_id`, a `court_reference`, and the `filed_at` instant; the `debt_id` must belong to the named program, and a `debt_id` resolving to a debt under a different program is rejected with `ERR_NOT_FOUND` (HTTP 404). The lawsuit enters status `REFERRED` and moves the linked debt to `LAWSUIT`. A debt may be referred from either `ENROLLED` or `IN_NEGOTIATION`; a referral from any other status is rejected with `ERR_INVALID_STATE`. Once a debt is in `LAWSUIT`, every offer subsequently quoted on it carries the litigation surcharge described in §3.5.

A lawsuit resolves in one of two ways. It resolves automatically to `RESOLVED_SETTLED` as a cascade when the litigated debt becomes `SETTLED`. Alternatively, a `ProgramAdmin` dismisses a `REFERRED` lawsuit, moving it to `RESOLVED_DISMISSED`; dismissal requires the lawsuit to be `REFERRED`, otherwise `ERR_INVALID_STATE`. On dismissal the linked debt reverts out of `LAWSUIT`: it returns to `IN_NEGOTIATION` if it had a prior offer, or otherwise back to `ENROLLED`. "Had a prior offer" means at least one offer of any status has ever been recorded against the debt, regardless of whether any remains active.

### 3.10. Dropping and Re-enrolling

At any point while a program is `ENROLLING` or `ACTIVE`, the owning `Client` may drop it, terminating the program. Dropping requires the program to be in the same phase from which the drop is taken (`ENROLLING` for an enrolling program, `ACTIVE` for an active one); a drop attempted from any other phase (`COMPLETED` or `TERMINATED`) is rejected with `ERR_INVALID_STATE` (HTTP 409). The phase moves to `TERMINATED`. The drop fires a cascade: every debt still in `ENROLLED`, `IN_NEGOTIATION`, or `LAWSUIT` is moved to the terminal `WITHDRAWN` status; each withdrawn debt's open `PENDING` offers are moved to `EXPIRED`; and any open `REFERRED` lawsuit on a withdrawn litigated debt is resolved to `RESOLVED_DISMISSED`. The residual dedicated-account balance is refunded to the client — the rounded-half-up cents equivalent of the balance is added to the client's `refunded_to_client_cents`, and the account balance is set to zero. The drop increments `Program.version` by one. After a drop, a fresh program may be enrolled for the same client; fee-rate snapshots for that new program are recomputed from the new program's own enrolled balance, independent of the dropped one.

### 3.11. Completing the Program

When the portfolio is fully resolved, a `ProgramAdmin` completes the program, advancing `program_phase` from `ACTIVE` to `COMPLETED`; completion requires the program to currently be `ACTIVE`, and an attempt from any other phase is rejected with `ERR_INVALID_STATE` (HTTP 409) before the eligibility and standing checks are evaluated. Completion is permitted only when the program is `completion_eligible`: every debt must be terminal — that is, each debt is either `SETTLED` or `WITHDRAWN` — and no `SettlementFee` may remain `OUTSTANDING`. If either condition fails, completion is rejected with `ERR_COMPLETION_NOT_ELIGIBLE` (HTTP 409). Completion is additionally blocked while the program is `DEFAULTED`, drawing `ERR_ACCOUNT_DEFAULTED`. On completion, any residual dedicated-account balance is refunded to the client exactly as on a drop — the rounded-half-up cents equivalent of the balance is added to `refunded_to_client_cents` and the balance is set to zero — and `Program.version` is incremented by one.

### 3.12. Portfolio Savings: Estimated versus Realized

The program continuously maintains two savings figures, recomputed on any debt or settlement mutation and on every read of the program. The **estimated** figure, `estimated_total_savings`, is a forward-looking projection over the still-open debts — those in `ENROLLED`, `IN_NEGOTIATION`, or `LAWSUIT` status (withdrawn and already-settled debts are excluded). For each such debt the system computes an estimated settlement equal to the debt's `original_balance` multiplied by the program's `target_settlement_pct`, rounded half-up to two decimal places; an estimated rate equal to the debt's frozen `fee_rate_pct`, or for a litigated debt the smaller of (that rate plus 0.03) and 0.25; and an estimated fee equal to the estimated settlement multiplied by the estimated rate, rounded half-up to two decimal places. The debt's contribution to the estimate is its `original_balance` minus the estimated settlement minus the estimated fee, and the program total is the sum of those per-debt contributions.

The **realized** figure, `realized_total_savings`, tallies only debts that have actually reached `SETTLED`. For each settled debt the contribution is its `original_balance` minus its actual `settled_amount` minus the fee accrued on its settlement. A fee that was waived through a settlement void contributes zero to the fee term, so a debt that was settled and later voided is not double-counted. The realized total is the sum of those per-debt contributions. Both figures use per-debt rounding before summation; withdrawn debts appear in neither.

## 4. Endpoint Definitions

Operations that create a new standalone resource return `201 Created`; operations that modify or transition an existing resource, and all reads, return `200 OK`. The administrative clock-set capability returns `200 OK`. Refer back to the §3 narratives for each endpoint's request body, computed outputs, and cascading side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/clients` | Create a Client (debtor) | ProgramAdmin |
| GET | `/clients/{id}` | Get a Client | ProgramAdmin, Client |
| POST | `/programs` | Enroll a new Program; auto-creates its DedicatedAccount | ProgramAdmin |
| GET | `/programs/{id}` | Get a Program with all computed aggregates | ProgramAdmin, NegotiationAgent, Client |
| GET | `/programs` | List programs, optionally filtered by client_id | ProgramAdmin, NegotiationAgent |
| POST | `/programs/{id}/activate` | Activate an enrolling program | ProgramAdmin |
| POST | `/programs/{id}/complete` | Complete a program | ProgramAdmin |
| POST | `/programs/{id}/drop` | Client drops the program | Client |
| GET | `/accounts/{id}` | Get a DedicatedAccount by id | ProgramAdmin, NegotiationAgent, Client |
| GET | `/accounts` | List dedicated accounts, filtered by program_id | ProgramAdmin, NegotiationAgent, Client |
| POST | `/debts` | Enroll a Debt; snapshots its fee_rate_pct | ProgramAdmin |
| GET | `/debts/{id}` | Get a single Debt | ProgramAdmin, NegotiationAgent, Client |
| GET | `/debts` | List debts, filtered by program_id, settled_offer_id, or status | ProgramAdmin, NegotiationAgent, Client |
| POST | `/deposits` | Record a monthly deposit | Client, ProgramAdmin |
| GET | `/deposits/{id}` | Get a single deposit | ProgramAdmin, NegotiationAgent, Client |
| GET | `/deposits` | List deposits, filtered by program_id or status | ProgramAdmin, NegotiationAgent, Client |
| POST | `/deposits/{id}/cure` | Cure a MISSED deposit | Client, ProgramAdmin |
| POST | `/offers` | Record a creditor settlement offer | NegotiationAgent |
| GET | `/offers/{id}` | Get a single offer | ProgramAdmin, NegotiationAgent, Client |
| GET | `/offers` | List offers, filtered by program_id, debt_id, or status | ProgramAdmin, NegotiationAgent, Client |
| POST | `/offers/{id}/accept` | Accept a PENDING offer (OCC-guarded) | NegotiationAgent |
| POST | `/offers/{id}/reject` | Reject a PENDING offer | NegotiationAgent |
| POST | `/settlements` | Fund a settlement from an ACCEPTED offer | NegotiationAgent |
| GET | `/settlements/{id}` | Get a single settlement | ProgramAdmin, NegotiationAgent, Client |
| GET | `/settlements` | List settlements, filtered by program_id, offer_id, debt_id, or status | ProgramAdmin, NegotiationAgent, Client |
| POST | `/settlements/{id}/complete` | Complete a funded settlement | NegotiationAgent |
| POST | `/settlements/{id}/void` | Void a funded settlement | ProgramAdmin |
| GET | `/fees/{id}` | Get a single settlement fee | ProgramAdmin, NegotiationAgent, Client |
| GET | `/fees` | List settlement fees, filtered by program_id, settlement_id, or status | ProgramAdmin, NegotiationAgent, Client |
| POST | `/lawsuits` | Refer a debt to litigation | ProgramAdmin |
| GET | `/lawsuits/{id}` | Get a single lawsuit | ProgramAdmin, NegotiationAgent, Client |
| GET | `/lawsuits` | List lawsuits, filtered by program_id, debt_id, or status | ProgramAdmin, NegotiationAgent, Client |
| POST | `/lawsuits/{id}/dismiss` | Dismiss a lawsuit | ProgramAdmin |
| GET | `/tax-events/{id}` | Get a single tax event | ProgramAdmin, NegotiationAgent, Client |
| GET | `/tax-events` | List 1099-C tax events, filtered by program_id, source_settlement_id, or status | ProgramAdmin, NegotiationAgent, Client |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_PROGRAM_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_ENROLLED_DEBTS` | 409 |
| `ERR_DUPLICATE_ACCOUNT_NUMBER` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_OFFER_WINDOW_OVERLAP` | 409 |
| `ERR_DEPOSIT_MONTH_OCCUPIED` | 409 |
| `ERR_ACCOUNT_DEFAULTED` | 409 |
| `ERR_ACCOUNT_DELINQUENT` | 409 |
| `ERR_OFFER_ALREADY_ACCEPTED` | 409 |
| `ERR_PROJECTED_RESERVE_SHORTFALL` | 402 |
| `ERR_INSUFFICIENT_RESERVE` | 402 |
| `ERR_OFFER_NOT_ACCEPTED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_COMPLETION_NOT_ELIGIBLE` | 409 |

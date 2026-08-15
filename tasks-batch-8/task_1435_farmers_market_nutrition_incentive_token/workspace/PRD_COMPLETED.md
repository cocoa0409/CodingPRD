# Farmers Market Nutrition Incentive API — Product Requirements Document

## 1. Introduction

Seasonal farmers markets that participate in a nutrition incentive program run a small but exacting financial operation at the edge of the cash economy. Shoppers draw down SNAP, WIC, or senior-farmers-market benefits at an info booth and walk away with physical scrip in two forms: base tokens purchased with their benefit, and "double-up" match tokens funded by the program's incentive pool. They spend that scrip with eligible vendors at the stall, and vendors later present their accumulated tokens for reimbursement. This document specifies the Farmers Market Nutrition Incentive API, the system of record for that entire operation: program and season configuration, token-batch inventory with serial-number governance, shopper enrollment and eligibility, same-day issuance and redemption, vendor reimbursement claims with verification and adjudication, fraud signaling and case management, periodic settlement runs that pay vendors, and the program-level ledger views that funders require.

Because tokens are bearer instruments with real cash value, the specification is built around an unforgiving reconciliation discipline. Every token minted on a market day must be accounted for — redeemed, voided, flagged, or still outstanding — before that day's books can close. Every dollar of match is capped three ways at once: per shopper per day, per shopper per season, and against the program's remaining pool. Every reimbursement claim is priced twice under deliberately different rounding rules — an optimistic per-line estimate at submission and a final aggregate-rounded amount at approval. And every write that could be priced off a stale view of the ledger carries an optimistic-concurrency guard. Roles are strictly segregated so that no single operator can issue value, verify a claim, and approve its payment.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply uniformly to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. A request that arrives without `X-User-Role`, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes six roles, spelled exactly as follows:

- `ProgramAdmin` — the program operator: configures programs, markets, vendors, and token batches; verifies and suspends shoppers; adjudicates reimbursement claims and fraud cases; runs settlement sweeps; and may override a flagged reconciliation. It is deliberately segregated from booth issuance (it cannot issue or void tokens) and from claim verification.
- `MarketManager` — runs market days (scheduling, opening, closing, reconciling) and verifies vendor reimbursement claims. It is segregated from approval and payment and from issuance.
- `BoothOperator` — the info-booth staff role: enrolls shoppers and issues or voids tokens. It is segregated from verification, approval, reconciliation override, and fraud adjudication.
- `Vendor` — a market vendor: redeems tokens by serial number, reverses its own redemptions, and submits or resubmits reimbursement claims. A vendor can never verify or approve its own claims.
- `Auditor` — an external, read-mostly party: it opens fraud cases but cannot confirm or clear them; adjudication belongs to `ProgramAdmin`.
- `Shopper` — the benefit recipient, with read-only access to its own record and issuance history.

An attempt to perform an operation outside the caller's designated role is rejected with `ERR_FORBIDDEN`. Role identity resolves in two different ways. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting Vendor; ownership checks on any resource that references a Vendor — a token's `redeemed_vendor_id`, a claim's `vendor_id` — compare the resource's foreign-key field to `X-User-ID`, and acting on another vendor's resource is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `Shopper`, `X-User-ID` is the `id` of the acting Shopper, granting read access to that shopper's own record. For both entity-backed roles, an `X-User-ID` that does not correspond to an existing row of the named entity is likewise rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `ProgramAdmin`, `MarketManager`, `BoothOperator`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. Only `X-User-Role` is enforced on every request: for the four operator roles `X-User-ID` may be omitted entirely, while for the entity-backed roles a missing `X-User-ID` cannot resolve to an entity row and is rejected with `ERR_FORBIDDEN` like any other unmatched identifier.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items and defaults to 0. Unparsable or out-of-range values are not rejected: each parameter falls back to its default when it cannot be parsed as an integer, and is otherwise clamped into range — `limit` into [1, 100] and `offset` floored at 0. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The token list is the standing exception: it is ordered by `serial_number` ascending, which keeps indexed reads of the scrip inventory deterministic. Because every timestamp reads the logical clock (§2.4), sort keys tie routinely; any remaining tie — on `created_at` or on `serial_number` — is broken by creation order (the sequence in which the resources were created), never by `id`.

### 2.4. The Logical Clock

All temporal rules in this specification — the market-day open guard, submission windows, dispute grace periods, settlement cutoffs — evaluate against a logical clock maintained by the server, never against wall-clock time. At startup, before any clock call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z; the server must not fall back to wall-clock time under any circumstance. A `ProgramAdmin` may advance the clock by calling the test-driving endpoint `POST /_clock/set_current_utc` with a `to_iso8601` timestamp; the response reports the resulting `current_utc`. The set is unconditional — any valid ISO 8601 timestamp is accepted, forward or backward, with no monotonicity check. Every temporal validation and computed deadline in the sections below reads from this clock the moment it is evaluated, and every server-stamped timestamp — `created_at`, `updated_at`, `disputed_at`, `approved_at`, and the envelope's `api_request_timestamp` — likewise reads this clock, truncated to whole milliseconds, so a stored creation time moves only when the logical clock moves.

### 2.5. Common Resource Properties

Every primary resource in the system — Program, Market, Vendor, Shopper, MarketDay, TokenBatch, Issuance, Token, RedemptionSubmission, FraudCase, and SettlementRun — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by one on every mutation — including mutations caused by cascade side effects originating on another resource. A token voided by a batch recall, a market day whose totals recompute after a redemption, and a shopper whose season usage changes at issuance all increment their own `version` and refresh their own `updated_at`.

### 2.6. Monetary Units, Precision, and Program Withholding

All monetary values in the system are integer cents; there are no fractional-cent quantities anywhere in the ledger. Where a rule calls for rounding down (the match computation, the budget-utilization figure), the result is floored to the stated unit. Where a rule calls for rounding of a money amount (reimbursement pricing), the method is round half up to a whole cent. Vendor reimbursements are subject to a 2.5 percent program administration withholding — 250 basis points — applied according to the rounding order pinned in §3.6. Shopper charges are whole-dollar scrip: `benefit_charged_cents` must be a multiple of 100 and at least 100.

### 2.7. Idempotency of Write Operations

Every write endpoint requires an `Idempotency-Key` header; a POST arriving without one is rejected with `ERR_MISSING_IDEMPOTENCY_KEY`. Replaying a key together with an identical request body returns the original response and produces no new side effects. Reusing a key with a different request body is a conflict, rejected with `ERR_IDEMPOTENCY_CONFLICT`. Only successful (2xx) responses are recorded against a key — a key first used on a rejected request remains free for reuse. Request identity covers the HTTP method, the path, and the body compared as canonical JSON (insensitive to object key order and whitespace), so the same key presented under a different path is a conflict even with an identical body.

### 2.8. Optimistic Concurrency Control

Two write endpoints guard their parent ledger with optimistic concurrency control, and they are the only endpoints that take a version field.

Creating an issuance (`POST /issuances`) requires a non-optional `expected_shopper_version` carrying the shopper `version` the client last observed. If the shopper's current `version` has since advanced — because another issuance, a void, or a suspension legitimately moved the row — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so a booth operator can never mint against a stale view of the shopper's match ledger.

Creating a settlement run (`POST /settlement-runs`) requires a non-optional `expected_program_version` carrying the program `version` the client last observed. If the program's current `version` has since advanced, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so a run is never priced off a superseded approval and payable state. Endpoints not named here take no version field.

### 2.9. Identifier Resolution and Nested Resource Retrieval

When an endpoint path carries resource identifiers, the system validates their existence sequentially, left to right, and rejects the request immediately with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. Identifiers referenced inside a request body — `shopper_id`, `market_day_id`, `program_id`, `market_id`, the elements of `token_ids`, and the fraud-case subject fields `vendor_id`, `shopper_id`, and `token_id` — are validated after the path resolves; a body reference to a missing resource is rejected with `ERR_REFERENCE_NOT_FOUND`. A request whose path matches no declared route — or whose method is not declared for the route — is likewise rejected with `ERR_NOT_FOUND` (404).

### 2.10. Validation Pipeline and Error Precedence

Every request walks a fixed precedence ladder, and the first failing rung determines the response — a later check never masks an earlier failure. Authentication runs first, then authorization, including payload-scoped role rules such as the restriction that sending `override_variance` set to true on a day reconciliation is `ProgramAdmin`-only (a `MarketManager` sending it is refused with `ERR_FORBIDDEN`). Idempotency comes third for write requests, then identifier resolution (path before body, per §2.9). Ownership checks that require the loaded resource — the acting vendor against a token's `redeemed_vendor_id` or a claim's `vendor_id`, the acting shopper against the record's own `id` — evaluate immediately after the path identifier resolves, ahead of body-reference and request-shape validation. On token redemption specifically, serial mapping precedes general request-shape validation: a serial outside every batch range of the program reports `ERR_TOKEN_UNKNOWN_SERIAL`, while a serial inside a batch range but never minted reports `ERR_TOKEN_NOT_MINTED`. Request shape follows — `ERR_INVALID_REQUEST` for missing required fields, wrong types, out-of-range enum values (`benefit_type`, `kind`, `outcome`, `to`), a `serial_end` that precedes its `serial_start`, or a `closes_at` not strictly after its `opens_at` — then claim emptiness (`ERR_SUBMISSION_EMPTY`), then the optimistic-concurrency checks of §2.8, which run ahead of any state evaluation.

State gates come next: first the generic rule that any transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`, then the specific gates in their relative order — shopper eligibility (`ERR_SHOPPER_NOT_ELIGIBLE`), vendor standing (`ERR_VENDOR_NOT_ACTIVE`), market-day openness (`ERR_MARKET_DAY_NOT_OPEN`), and market-day closedness (`ERR_MARKET_DAY_NOT_CLOSED`). Fraud quarantine is evaluated after the state gates and deliberately outranks every remaining business rule, including submission-window expiry: a flagged token presented at redemption, claim creation, or claim resubmission is rejected with `ERR_TOKEN_FLAGGED` regardless of what else is wrong with the request. The double-spend defense (`ERR_TOKEN_ALREADY_REDEEMED`) and the voided-token refusal (`ERR_TOKEN_VOID`) follow quarantine, in that order. Referential ownership checks (`ERR_TOKEN_VENDOR_MISMATCH`, then `ERR_TOKEN_ALREADY_SUBMITTED`) come after those, then temporal rules (`ERR_SEASON_INACTIVE`, `ERR_SUBMISSION_WINDOW_CLOSED`), then structural uniqueness (`ERR_MARKET_DAY_OVERLAP`, `ERR_SERIAL_RANGE_OVERLAP`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_SUBJECT_AMBIGUOUS`). The fiscal rules close the ladder, in this relative order: batch-serial sufficiency (`ERR_BATCH_SERIALS_INSUFFICIENT`), the charge floor (`ERR_CHARGE_TOO_SMALL`), the whole-dollar multiple (`ERR_FRACTIONAL_CHARGE`), batch availability (`ERR_NO_ACTIVE_TOKEN_BATCH`), voidability (`ERR_ISSUANCE_NOT_VOIDABLE`), and reconciliation variance (`ERR_RECONCILIATION_VARIANCE`).

### 2.11. Scrip Vocabulary: Token Kinds, Denominations, and Statuses

Scrip exists in two kinds. `BASE` tokens are purchased with the shopper's benefit and are minted in five-dollar (500-cent) and one-dollar (100-cent) denominations. `MATCH` tokens carry the incentive value and exist only as one-dollar tokens. Every token bears a `serial_number` drawn from the batch that supplied it, unique across the program. A token's lifecycle spans six statuses — `ISSUED`, `REDEEMED`, `SETTLED`, `VOIDED`, `FLAGGED`, and `CONFISCATED` — of which `SETTLED`, `VOIDED`, and `CONFISCATED` are terminal. Two conventions pervade the workflows below: tokens are same-day scrip, redeemable and correctable only while their issuing market day remains `OPEN`; and `FLAGGED` is a quarantine status — a flagged token sits outside the redemption ledger until its fraud case resolves, counting toward neither redeemed nor voided value.

## 3. Business Logic & Workflows

### 3.1. Program Setup, Markets, and the Token Supply

A `ProgramAdmin` opens a season by creating the program itself: a display `name`, a `season_start` and `season_end` that bound the season as UTC instants, and `match_pool_budget_cents`, the total incentive funding budgeted for the season, which may not be negative — a negative budget is rejected with `ERR_INVALID_REQUEST`. The season bounds are accepted as given: no shape rule requires `season_end` to fall after `season_start`. At creation the program's computed fields take their initial values: `match_pool_remaining_cents` initializes to the full budget, the liability views `liability_forward_cents` and `liability_realized_cents` and the disbursement counter `paid_out_cents` all start at zero, and `version` starts at 1. Markets are then registered under the program with a `program_id`, a market `name`, and a `city`; the markets of a program can be listed back through the program's market listing, which accepts the standard `limit` and `offset` pagination parameters.

Token stock reaches each market as sealed batches, registered by a `ProgramAdmin`. Registration records the `market_id` the batch ships to, a `kind` of `BASE` or `MATCH`, a `denomination_cents`, and a closed serial range from `serial_start` through `serial_end` inclusive. Shape rules enforced at registration: `BASE` batches may carry only the 500-cent or 100-cent denomination, `MATCH` batches must carry the 100-cent denomination, and `serial_end` may not precede `serial_start` — violations are rejected with `ERR_INVALID_REQUEST`. Serial ranges are policed program-wide across every kind and denomination: a new batch's closed range may not intersect the range of any other batch that has not been `RECALLED`, and because the ranges are closed intervals, sharing even a single endpoint serial is a conflict rejected with `ERR_SERIAL_RANGE_OVERLAP`; strictly adjacent ranges, where one batch's `serial_end` sits exactly one below the other's `serial_start`, are legal. The batch roster of a market can be listed with `market_id`, `status`, and `kind` filters.

A batch begins life `SEALED`, with `next_serial` pointing at `serial_start`. Activation moves it `SEALED → ACTIVE` and makes it available to the minting selector described in §3.4. Recall moves an `ACTIVE` batch to `RECALLED`, which is terminal, and triggers a two-hop cascade: every token of the batch still `ISSUED` transitions to `VOIDED` (tokens already `REDEEMED`, `SETTLED`, `FLAGGED`, or `CONFISCATED` are unaffected), and for each affected market day the `voided_value_cents` and `variance_cents` recompute — the variance dropping by the voided face value, which can move a day between `CLOSED` and `VARIANCE_FLAGGED` as its variance crosses the reconciliation tolerance in either direction. The batch, each affected token, and each affected market day each increment their `version`.

Every token minted anywhere in the program records its `serial_number`, the `kind` and `denomination_cents` copied from its supplying batch, the `issuance_id` that minted it, the `token_batch_id` its serial was drawn from, and two lifecycle references that start empty: `redeemed_vendor_id`, set when a vendor accepts the token, and `submission_id`, set while a reimbursement claim holds the token.

### 3.2. Market Days and the Daily Ledger

The operating calendar is built day by day. A `MarketManager` schedules a market day by naming its `market_id`, a calendar `date` in ISO year-month-day form, and a half-open operating window from `opens_at` (inclusive) to `closes_at` (exclusive); `closes_at` must be strictly after `opens_at`. Two guards protect the calendar. The day's `date` must fall within the program's season — the date participates as its UTC midnight (00:00:00Z), and that instant must be on or after `season_start` and strictly before `season_end` — or scheduling is rejected with `ERR_SEASON_INACTIVE`. And the new window must not overlap any other market-day window of the same market, regardless of that day's status: because windows are half-open, abutting windows — an existing window closing exactly when the new one opens — are legal, and mere date equality is not the test, so two same-date days with disjoint windows are permitted; a genuine overlap is rejected with `ERR_MARKET_DAY_OVERLAP`. A new day starts `SCHEDULED` with all ledger totals at zero. Days can be listed with `market_id` and `status` filters.

Opening a day moves it `SCHEDULED → OPEN` and is guarded by the logical clock: the clock's current date must equal the day's `date`, otherwise the open is rejected with `ERR_MARKET_DAY_NOT_OPEN`. An `OPEN` day admits the four same-day operations — issuance, redemption, redemption reversal, and issuance void — and closing moves the day `OPEN → CLOSED`. Each transition increments the day's `version`.

Three running totals track the day's scrip, recomputed on every token status change that touches the day. `issued_value_cents` sums the face value of every token minted by the day's `ACTIVE` issuances. `voided_value_cents` sums the face value of those tokens whose own status is `VOIDED` — the batch-recall path. `redeemed_value_cents` sums the face value of those tokens in `REDEEMED` or `SETTLED`. The day's `variance_cents` is what remains unaccounted: issued minus voided minus redeemed. Because `FLAGGED` and `CONFISCATED` tokens count toward neither redeemed nor voided value, flagging a previously redeemed token raises the day's variance — quarantined value sits outside the ledger until its case resolves.

Reconciliation closes the books. From `CLOSED`, a plain reconcile succeeds only while the absolute value of `variance_cents` is at most 500 cents — the five-dollar tolerance boundary is inclusive, so a variance of exactly five dollars reconciles while five dollars and one cent does not — and moves the day `CLOSED → RECONCILED`. When the variance exceeds the tolerance and no override is supplied, the attempt does not fail: it returns 200 OK and instead routes the day `CLOSED → VARIANCE_FLAGGED`, surfacing the discrepancy for investigation. From `VARIANCE_FLAGGED` the only way forward is an explicit `override_variance` flag set to true, and that flag is `ProgramAdmin`-only — a `MarketManager` sending `override_variance` set to true is refused with `ERR_FORBIDDEN`, and a plain reconcile attempted on a flagged day is rejected with `ERR_RECONCILIATION_VARIANCE`. An administrator may also reconcile a `CLOSED` day directly by supplying the override, bypassing the flagged state entirely. Every successful reconcile route increments the day's `version`. `RECONCILED` is terminal: once a day reconciles, its claims can no longer be verified or adjudicated.

### 3.3. Shopper Enrollment and Benefit Eligibility

Enrollment happens at the info booth. A `BoothOperator` registers a shopper against a `program_id` with an `external_benefit_ref` — the EBT card token, WIC identifier, or senior voucher identifier from the external benefit system — and a `benefit_type` of `SNAP`, `WIC`, or `SENIOR`. The external reference is unique within the program among shoppers who are not `SUSPENDED`: a duplicate enrollment is rejected with `ERR_DUPLICATE_ENROLLMENT`, while a reference previously held by a since-suspended shopper may be reused. A new shopper starts in `ENROLLED` status with `season_match_used_cents` at zero.

Eligibility is a two-step gate. A shopper cannot receive tokens until a `ProgramAdmin` verifies the enrollment, moving the shopper `ENROLLED → ACTIVE`. Suspension moves an `ACTIVE` shopper to `SUSPENDED` — either by direct administrator action or as the cascade of a confirmed fraud case — and `SUSPENDED` is terminal for a shopper. Any attempt to issue tokens to a shopper who is not `ACTIVE`, whether still `ENROLLED` or already `SUSPENDED`, is rejected with `ERR_SHOPPER_NOT_ELIGIBLE`. Both transitions increment the shopper's `version`. The shopper roster of a program can be listed with a `status` filter, and individual issuances and shopper records are readable by the roles listed in §4 — including the shopper itself, whose entity-backed identity grants read access to its own record.

### 3.4. Issuing Tokens at the Info Booth

The core booth operation mints scrip against a shopper's benefit. The request names the `shopper_id`, the `market_day_id` of the day the booth is operating, the `benefit_charged_cents` drawn against the shopper's benefit, and — per §2.8 — the `expected_shopper_version` guard. Three gates precede any minting: the shopper must be `ACTIVE` (`ERR_SHOPPER_NOT_ELIGIBLE`), the market day must be `OPEN` (`ERR_MARKET_DAY_NOT_OPEN`), and the charge itself must respect whole-dollar scrip — below one dollar the request is rejected with `ERR_CHARGE_TOO_SMALL`, and a charge that is not a multiple of 100 cents is rejected with `ERR_FRACTIONAL_CHARGE`.

Before any token is minted, the incentive value is computed. Each benefit type carries its own economics: `SNAP` matches dollar for dollar (a ratio of 1.0) up to a daily cap of $20.00 and a season cap of $200.00; `WIC` matches at fifty cents on the dollar (a ratio of 0.5) up to $10.00 per day and $100.00 per season; `SENIOR` matches dollar for dollar up to $15.00 per day and $150.00 per season. The computation proceeds in a pinned, non-commutative order. First, the raw match is the charged amount multiplied by the shopper's benefit-type ratio, rounded down to a whole cent. Second, the remaining daily allowance is the daily cap minus the match value already issued to that shopper on the calendar date of the market day — an issuance always counts toward the calendar date of its market day, never the wall-clock moment of the request, and only issuances still in `ACTIVE` status count toward either accumulator. Third, the remaining season allowance is the season cap minus the shopper's `season_match_used_cents`. Fourth, the remaining pool is the program's `match_pool_remaining_cents`. The operative match, recorded on the issuance as `match_cents`, is the smallest of these four quantities — the raw match and the three remaining allowances — rounded down to a whole-dollar multiple of 100 cents, because match tokens exist only in one-dollar denominations; any sub-dollar remainder is forfeited. Clamping is silent: when any allowance is exhausted the match is simply zero, the issuance still succeeds, and base tokens always mint — cap exhaustion is never an error.

The mint then splits value into physical tokens. The base value, recorded as `base_value_cents` and always equal to `benefit_charged_cents`, is minted greedily, largest denomination first, over the `BASE` denominations: as many five-dollar tokens as the value allows, then one-dollar tokens for the remainder. The match value, always a whole-dollar multiple, mints entirely in one-dollar `MATCH` tokens. Token supply is drawn from the market's batches under a pinned selection rule, evaluated independently for each needed combination of kind and denomination. Eligible batches belong to the issuance's market, carry the needed `kind` and `denomination_cents`, are `ACTIVE`, and hold enough unminted serials — the count of serials from `next_serial` through `serial_end` inclusive must be at least the number of tokens needed, because a denomination's mint is atomic and never splits across batches. Among eligible batches the winner has the lowest `serial_start`, ties broken by the earliest `created_at` and any remaining tie by creation (registration) order — never by `id`. If no `ACTIVE` batch exists at all for a needed combination the issuance fails with `ERR_NO_ACTIVE_TOKEN_BATCH`; if active batches exist but none can cover the needed count on its own, it fails with `ERR_BATCH_SERIALS_INSUFFICIENT`. Minting assigns serials in ascending order beginning at the chosen batch's `next_serial`, which then advances by the number minted; once `next_serial` passes `serial_end` the batch is exhausted.

A recorded issuance starts in `ACTIVE` status. Recording it raises the shopper's `season_match_used_cents` by the minted match, draws the program's `match_pool_remaining_cents` down by the same amount, and raises the market day's `issued_value_cents` by base plus match; the shopper, the program, and the market day each increment their `version`. Issuances can be listed with `shopper_id`, `market_day_id`, and `status` filters.

Voiding is the booth's same-day correction, performed by a `BoothOperator`, and it is deliberately narrow. The issuance must still be `ACTIVE`; its market day must still be `OPEN`, because voids are same-day reversals only — otherwise the attempt is rejected with `ERR_MARKET_DAY_NOT_OPEN`; and every token the issuance minted must still sit in `ISSUED` status — once any one of them has been redeemed, settled, voided, flagged, or confiscated, the issuance is no longer voidable and the attempt is rejected with `ERR_ISSUANCE_NOT_VOIDABLE`. A successful void moves the issuance `ACTIVE → VOIDED` and every one of its tokens `ISSUED → VOIDED`, subtracts the issuance's match from the shopper's `season_match_used_cents`, returns the same match amount to the program's `match_pool_remaining_cents` as a compensating credit, and recomputes the day's `issued_value_cents` with the voided issuance excluded. The issuance, the shopper, the program, and the market day each increment their `version`.

### 3.5. Vendor Participation and Token Redemption

Vendors are registered by a `ProgramAdmin` against a home `market_id` with a `legal_name` and a `stall_number`. A new vendor starts `PENDING` with a `payable_cents` balance of zero and cannot transact until an administrator approves it, moving it `PENDING → ACTIVE`. From `ACTIVE` a vendor can be suspended and later reinstated — the status cycle between `ACTIVE` and `SUSPENDED` is driven by an administrator supplying a target `to` status — and the vendor state machine has no terminal state. Redemption attempts and claim submissions by a vendor that is not `ACTIVE` are rejected with `ERR_VENDOR_NOT_ACTIVE`. The `payable_cents` figure is the vendor's approved-but-unpaid balance: the sum of `approved_amount_cents` over its claims in `APPROVED` or `PAID` status, minus the sum of `paid_amount_cents` over its paid claims. Vendors can be listed with `market_id` and `status` filters.

At the stall, a vendor accepts a shopper's physical token by presenting its `serial_number`, which must be an integer — a non-integer value fails request-shape validation with `ERR_INVALID_REQUEST`. Acceptance runs a strict ladder. The serial must first map to a minted token, and this triage is system-wide: it consults every batch range in the system, across all programs and regardless of batch status (including `RECALLED`), and if several minted tokens share the serial the earliest-minted one is addressed. A serial inside no batch range anywhere is rejected with `ERR_TOKEN_UNKNOWN_SERIAL`, while a serial that falls inside a batch range but has not yet been minted is treated as a counterfeit signal and rejected with `ERR_TOKEN_NOT_MINTED`. Next come the two standing gates, ahead of any token-status examination: the acting vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), and — because tokens are same-day scrip — the issuing market day must still be `OPEN` (`ERR_MARKET_DAY_NOT_OPEN`). The token's current status is then examined in a fixed order — quarantine first, then the double-spend defense, then the voided-token refusal. A token already `FLAGGED` is refused with `ERR_TOKEN_FLAGGED`, and quarantine outranks every other business rule. A token already `REDEEMED` or `SETTLED` triggers the double-spend defense: the attempt is rejected with `ERR_TOKEN_ALREADY_REDEEMED` and the platform opens a fraud case with `origin` `AUTO_DOUBLE_SPEND` whose `reason` records the attempting vendor's identity; the held token immediately transitions `REDEEMED → FLAGGED` when it is `REDEEMED`, while a `SETTLED` token keeps its status (the case still opens). A `VOIDED` or `CONFISCATED` token is refused with `ERR_TOKEN_VOID`. Finally, the acting vendor must belong to the same market whose market day issued the token — a cross-market redemption is rejected with `ERR_TOKEN_VENDOR_MISMATCH`.

A successful redemption moves the token `ISSUED → REDEEMED`, records the accepting vendor in the token's `redeemed_vendor_id`, raises the issuing day's `redeemed_value_cents` by the token's face value with `variance_cents` recomputed, and increments both the token's and the day's `version`. A vendor may undo its own redemption as a same-day correction, and the gates evaluate in this order: the acting vendor must be the vendor recorded in `redeemed_vendor_id` — any other vendor is refused with `ERR_FORBIDDEN` — then the token must be `REDEEMED` (`ERR_INVALID_STATE`), then the issuing market day must still be `OPEN` (`ERR_MARKET_DAY_NOT_OPEN`), and finally the token's `submission_id` must be empty, since a token already attached to a claim cannot be reversed and the attempt is rejected with `ERR_TOKEN_ALREADY_SUBMITTED`. The reversal moves the token `REDEEMED → ISSUED`, clears `redeemed_vendor_id`, lowers the day's `redeemed_value_cents` by the face value, recomputes the variance, and increments both versions. The full token inventory can be read back with filters on `issuance_id`, `token_batch_id`, `submission_id`, `redeemed_vendor_id`, `serial_number`, and `status`, always ordered by `serial_number` ascending.

### 3.6. Reimbursement Claims: Submission, Verification, and Adjudication

When a vendor has accumulated redeemed tokens, it assembles a reimbursement claim by naming the `market_day_id` on which the tokens were redeemed and supplying an ordered `token_ids` array; the server stamps the claim's `vendor_id` from the acting vendor's identity header. An empty `token_ids` array is rejected with `ERR_SUBMISSION_EMPTY`. Each listed token then passes the strict attachment ladder used everywhere tokens are claimed: the token must exist (`ERR_REFERENCE_NOT_FOUND`), must not be `FLAGGED` (`ERR_TOKEN_FLAGGED` — quarantine outranks even an expired submission window), must have been redeemed by the submitting vendor (`ERR_TOKEN_VENDOR_MISMATCH`), and must not already be attached to another claim still in a non-terminal status — `SUBMITTED`, `VERIFIED`, `DISPUTED`, or `APPROVED` (`ERR_TOKEN_ALREADY_SUBMITTED`). The vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`). The claim is also temporal: it may be lodged while the market day is still `OPEN`, or after close within a grace of seven days measured from the day's `closes_at` — the deadline is inclusive, so lodgement exactly seven days after `closes_at` still succeeds; outside that window the attempt is rejected with `ERR_SUBMISSION_WINDOW_CLOSED`. A token id appearing more than once in `token_ids` passes the ladder (attachment is checked against other claims, never within the request), contributes to the provisional pricing once per occurrence, and is attached once. On acceptance each listed token's `submission_id` is set to the new claim and the claim starts in `SUBMITTED` status. Claims can be listed with `vendor_id`, `market_day_id`, and `status` filters; a `Vendor` caller's listing is scoped to its own claims, with any `vendor_id` filter overridden by the caller's own id. A claim reads its `token_ids` back ordered by `serial_number` ascending, which is not necessarily the submission order.

Every claim is priced twice, and the two prices are computed under deliberately different rounding orders. At creation — and again at every resubmission — the platform records an optimistic `provisional_amount_cents`: the 2.5 percent administration withholding is netted against each token line separately, each line's face value reduced by the withholding and rounded half up to a whole cent, and the rounded lines are then summed; every token attached at that moment contributes, whatever happens to its status afterward. At approval the platform computes the final `approved_amount_cents` with the opposite order: the face values of the attached tokens still `REDEEMED` at that instant are summed first, the withholding is applied once to the aggregate, and the single result is rounded half up to a whole cent — sum first, withhold once, round once. The two variants legitimately diverge on identical token sets: a claim holding one five-dollar token and two one-dollar tokens prices provisionally at 684 cents (488 plus 98 plus 98) but finally at 683 (the 700-cent aggregate less 2.5 percent, rounded half up), and they diverge further when tokens leave `REDEEMED` status before approval. Two timestamps bracket the dispute flow: `disputed_at` stays empty until the claim is first disputed, and `approved_at` stays empty until approval — it later serves as the eligibility key for the settlement sweep. `paid_amount_cents` likewise stays empty until the claim is swept into a settlement run, when it is set equal to `approved_amount_cents`.

Verification belongs to the `MarketManager` and moves a `SUBMITTED` claim to either `VERIFIED` or `DISPUTED` according to the supplied `outcome`. Verification requires the claim's market day to be `CLOSED` or `VARIANCE_FLAGGED` — a day in any earlier state rejects the attempt with `ERR_MARKET_DAY_NOT_CLOSED`, and a `RECONCILED` day is terminally locked, rejecting verification with `ERR_INVALID_STATE`. Marking a claim `DISPUTED` stamps `disputed_at`, which starts the resubmission grace clock. A disputed claim can be cured by its owning vendor — any other actor is refused with `ERR_FORBIDDEN` — by supplying a full replacement `token_ids` list, which returns the claim `DISPUTED → SUBMITTED`; an empty replacement list is rejected with `ERR_SUBMISSION_EMPTY`, and the vendor-standing gate of creation applies equally to resubmission (`ERR_VENDOR_NOT_ACTIVE`). The cure is accepted while the claim remains inside the ordinary submission window, or within a seventy-two-hour grace measured from `disputed_at` even after that window has closed — both limits are inclusive, so a cure exactly seventy-two hours after `disputed_at` still succeeds; past both limits the resubmission fails with `ERR_SUBMISSION_WINDOW_CLOSED`. The replacement list passes the same strict per-token ladder as creation, except that tokens still attached to the claim being cured do not trip `ERR_TOKEN_ALREADY_SUBMITTED` — their attachment is being replaced. On acceptance the previously attached tokens are detached — their `submission_id` cleared — the new tokens are attached, `provisional_amount_cents` is recomputed, and the claim's `version` increments.

Adjudication belongs to the `ProgramAdmin`; verification and approval are deliberately segregated between the two roles, so no single operator can both verify and approve a claim. Approval is possible only from `VERIFIED`, and only while the claim's market day is `CLOSED` or `VARIANCE_FLAGGED`: a day not yet closed rejects with `ERR_MARKET_DAY_NOT_CLOSED`, and a `RECONCILED` day is terminally locked, rejecting with `ERR_INVALID_STATE`. Approval computes `approved_amount_cents` by the aggregate-rounding variant, stamps `approved_at`, moves every attached token still `REDEEMED` to `SETTLED`, recomputes the vendor's `payable_cents` upward by the approved amount, and recomputes each token's market-day totals — because `REDEEMED` and `SETTLED` both count toward `redeemed_value_cents`, the day's variance does not move. The vendor's `version` increments along with the claim's and the tokens'. Rejection is possible from `VERIFIED` or `DISPUTED`, under the same market-day gate as approval — a day not yet closed rejects with `ERR_MARKET_DAY_NOT_CLOSED` and a `RECONCILED` day rejects with `ERR_INVALID_STATE` — and quarantines the claim's tokens: every attached token still `REDEEMED` transitions `REDEEMED → FLAGGED`, every attached token is detached (its `submission_id` cleared), and for each flagged token its market day's `redeemed_value_cents` recomputes with the flagged value excluded — which can push a `CLOSED` day over the tolerance and flip it to `VARIANCE_FLAGGED` automatically. The same quarantine cascade fires when the system itself rejects a claim: when a vendor is suspended through a confirmed fraud case, every claim of that vendor still `SUBMITTED` or `DISPUTED` transitions to `REJECTED`, with its attached tokens flagged (those still `REDEEMED`) and detached and the affected day totals recomputed. `REJECTED` and `PAID` are the claim's terminal states.

### 3.7. Fraud Signals and Case Adjudication

Fraud cases are the program's investigative instrument, and each case targets exactly one subject. An `Auditor` opens a case with a free-text `reason` and exactly one of `vendor_id`, `shopper_id`, or `token_id`; supplying none of them or more than one is rejected with `ERR_SUBJECT_AMBIGUOUS`. Cases opened through the API carry `origin` `MANUAL`, while the platform itself raises cases of `origin` `AUTO_DOUBLE_SPEND` after the double-spend defense of §3.5 fires. The counterfeit-serial signal — a serial inside a batch range that has never been minted, whose presentation is refused with `ERR_TOKEN_NOT_MINTED` — opens no case: the refusal is the entire platform response, and the `AUTO_COUNTERFEIT_SERIAL` origin is never produced. When a case targets a token, opening it immediately moves a `REDEEMED` token to `FLAGGED`. A new case starts `OPEN`, and the case docket can be listed with `vendor_id`, `shopper_id`, `token_id`, and `status` filters.

Adjudication belongs to the `ProgramAdmin` and comes in two terminal verdicts, `CONFIRMED` and `CLEARED`; the auditor who opened the case cannot issue either. Confirming a case executes a cascade that depends on which subject the case names, and each branch is fully specified. When the case names a vendor, the cascade runs three hops: first the vendor transitions `ACTIVE → SUSPENDED` (a vendor already `SUSPENDED` skips this hop and the cascade continues); then every claim of that vendor still `SUBMITTED` or `DISPUTED` transitions to `REJECTED`; then each rejected claim's attached tokens still `REDEEMED` transition `REDEEMED → FLAGGED`, every attached token is detached, and each affected token's market-day totals recompute. When the case names a shopper, the shopper transitions `ACTIVE → SUSPENDED`, which also blocks all further issuance to that shopper (a shopper already `SUSPENDED` is unaffected). When the case names a token, the escalation depends on the token's current state: a `FLAGGED` token is confiscated to `CONFISCATED`; a `REDEEMED` token escalates through both steps — first to `FLAGGED`, then to `CONFISCATED` — with both steps' ledger effects applied in order; and an `ISSUED` token moves only to `FLAGGED`, where the escalation stops as a review hold. A subject token in `VOIDED`, `SETTLED`, or `CONFISCATED` status is unaffected by confirmation. Confiscation detaches the token from any non-terminal claim, clearing its `submission_id`, and recomputes its market day's totals and variance. The case's `version` increments.

Clearing a case applies compensation only where the ledger was actually touched. When the cleared case names a token that currently sits `FLAGGED`, the token returns `FLAGGED → REDEEMED` and its market day's totals and variance recompute — the token's value counts toward `redeemed_value_cents` once more. Vendor and shopper subjects are never automatically reinstated by a clearance; restoring them requires an explicit status change by an administrator. The case's `version` increments on either verdict.

### 3.8. Settlement Runs, Liability Views, and Funder Reporting

Settlement converts approved claims into payments, and it is a deliberate, administrator-run sweep rather than a continuous process. Creating a settlement run names the `program_id` and a `cutoff_at`, and — per §2.8 — must carry the `expected_program_version` guard; a stale program view is rejected with `ERR_STALE_VERSION`. The sweep collects the program's claims in `APPROVED` status whose `approved_at` falls at or before `cutoff_at` — the boundary is inclusive, so a claim approved exactly at the cutoff is swept — and processes them in a pinned order: earliest `approved_at` first, ties broken by earliest `created_at` and any remaining tie by creation order — never by `id`. Each swept claim transitions `APPROVED → PAID` with its `paid_amount_cents` set equal to its `approved_amount_cents`; the vendor's `payable_cents` falls by the paid amount; and the program's `paid_out_cents` rises by the same amount, with the vendor's and the program's `version` incrementing for each swept claim — the program's `version` advancing once more for the creation of the run itself. The run records `swept_submission_ids` in processing order, `total_paid_cents` as the sum of the paid amounts, and `vendor_payment_count` as the number of distinct vendors receiving payment. An empty eligible set is legal: the run succeeds with a total of zero and an empty list. Runs can be listed with a `program_id` filter.

Two liability views accompany the pool balance, and they answer different questions. The forward-looking view, `liability_forward_cents`, sums the face value of every token of the program that may still legitimately be presented — those in `ISSUED`, `REDEEMED`, or `FLAGGED` — treating flagged value as contingent exposure for pool planning. The chronological view, `liability_realized_cents`, counts only value actually presented at stalls: tokens in `REDEEMED` or `SETTLED`. Both views exclude `VOIDED` and `CONFISCATED` tokens, and `paid_out_cents` accumulates what settlement runs have actually disbursed, completing the bridge from issuance to reimbursement.

Funders receive their own computed snapshot. The funder report, available to `ProgramAdmin` and `Auditor`, accepts optional `period_start` and `period_end` bounds applied as a half-open window over issuance creation time — `period_start` inclusive, `period_end` exclusive; a malformed bound is rejected with `ERR_INVALID_REQUEST` — and returns the season's picture: `issued_base_cents` and `issued_match_cents`, the base and match value minted by in-window issuances still in `ACTIVE` status (a voided issuance contributes nothing); `redeemed_cents`, the value of in-window tokens that have since been redeemed or settled; `reimbursed_cents`, the amounts paid out through `PAID` claims, summed over the whole season regardless of the period bounds; the current `match_pool_remaining_cents`; both liability views; `days_flagged_count`, the number of the program's market days currently sitting in `VARIANCE_FLAGGED`; and `utilization_bp`, the share of the season's match budget already consumed — the budget minus the remaining pool — scaled by ten thousand and rounded down to a whole number of basis points, and zero when the budget itself is zero.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify, act on, or read an existing resource return `200 OK` — including the reconciliation route's soft-failure path, which returns `200 OK` while routing the day to `VARIANCE_FLAGGED`. The table below summarizes the HTTP contract; request payloads, computed fields, and side effects are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | ProgramAdmin |
| POST | `/programs` | Create an incentive program | ProgramAdmin |
| GET | `/programs/{id}` | Read a program incl. computed pool and liability fields | ProgramAdmin, MarketManager, BoothOperator, Auditor, Vendor, Shopper |
| GET | `/programs/{id}/funder-report` | Computed funder snapshot over a half-open period | ProgramAdmin, Auditor |
| GET | `/programs/{id}/markets` | List markets of a program | ProgramAdmin, MarketManager, Auditor |
| GET | `/programs/{id}/shoppers` | List shoppers of a program | ProgramAdmin, MarketManager, BoothOperator, Auditor |
| POST | `/markets` | Register a market under a program | ProgramAdmin |
| POST | `/vendors` | Register a vendor at a market (starts PENDING) | ProgramAdmin |
| GET | `/vendors/{id}` | Read a vendor incl. payable balance | ProgramAdmin, MarketManager, Auditor, Vendor |
| GET | `/vendors` | List vendors, filterable by market and status | ProgramAdmin, MarketManager, Auditor |
| POST | `/vendors/{id}/approve` | Approve a vendor (PENDING → ACTIVE) | ProgramAdmin |
| POST | `/vendors/{id}/set-status` | Cycle a vendor between ACTIVE and SUSPENDED | ProgramAdmin |
| POST | `/shoppers` | Enroll a shopper (starts ENROLLED) | BoothOperator |
| GET | `/shoppers/{id}` | Read a shopper incl. season match usage | ProgramAdmin, MarketManager, BoothOperator, Auditor, Shopper |
| POST | `/shoppers/{id}/verify` | Verify an enrollment (ENROLLED → ACTIVE) | ProgramAdmin |
| POST | `/shoppers/{id}/suspend` | Suspend a shopper (ACTIVE → SUSPENDED) | ProgramAdmin |
| POST | `/market-days` | Schedule a market day | MarketManager |
| GET | `/market-days/{id}` | Read a market day incl. issued/voided/redeemed/variance totals | ProgramAdmin, MarketManager, BoothOperator, Auditor, Vendor |
| GET | `/market-days` | List market days, filterable by market and status | ProgramAdmin, MarketManager, BoothOperator, Auditor, Vendor |
| POST | `/market-days/{id}/open` | Open a scheduled day (clock date must equal the day's date) | MarketManager |
| POST | `/market-days/{id}/close` | Close an open day | MarketManager |
| POST | `/market-days/{id}/reconcile` | Reconcile a closed day; variance-flag soft failure; override is admin-only | MarketManager, ProgramAdmin |
| POST | `/token-batches` | Register a token batch (starts SEALED) | ProgramAdmin |
| GET | `/token-batches/{id}` | Read a batch incl. next_serial | ProgramAdmin, MarketManager, BoothOperator, Auditor |
| GET | `/token-batches` | List batches, filterable by market, status, and kind | ProgramAdmin, MarketManager, BoothOperator, Auditor |
| POST | `/token-batches/{id}/activate` | Activate a sealed batch (SEALED → ACTIVE) | ProgramAdmin |
| POST | `/token-batches/{id}/recall` | Recall an active batch, voiding its outstanding ISSUED tokens | ProgramAdmin |
| POST | `/issuances` | Issue base and match tokens at the booth (OCC on shopper version) | BoothOperator |
| GET | `/issuances/{id}` | Read an issuance | ProgramAdmin, MarketManager, BoothOperator, Auditor, Shopper |
| GET | `/issuances` | List issuances, filterable by shopper, market day, and status | ProgramAdmin, MarketManager, BoothOperator, Auditor |
| POST | `/issuances/{id}/void` | Same-day full reversal of an issuance | BoothOperator |
| GET | `/tokens/{id}` | Read a token | ProgramAdmin, MarketManager, BoothOperator, Auditor, Vendor |
| GET | `/tokens` | List tokens, filterable; ordered by serial number ascending | ProgramAdmin, MarketManager, BoothOperator, Auditor, Vendor |
| POST | `/tokens/redeem` | Vendor accepts a physical token by serial number | Vendor |
| POST | `/tokens/{id}/reverse-redemption` | Undo own redemption (same-day, pre-submission) | Vendor |
| POST | `/redemption-submissions` | Vendor submits redeemed tokens for reimbursement | Vendor |
| GET | `/redemption-submissions/{id}` | Read a redemption submission | ProgramAdmin, MarketManager, Auditor, Vendor |
| GET | `/redemption-submissions` | List submissions, filterable by vendor, market day, and status | ProgramAdmin, MarketManager, Auditor, Vendor |
| POST | `/redemption-submissions/{id}/verify` | Verify a claim (SUBMITTED → VERIFIED or DISPUTED) | MarketManager |
| POST | `/redemption-submissions/{id}/resubmit` | Cure a DISPUTED claim with a full replacement token list | Vendor |
| POST | `/redemption-submissions/{id}/decide` | Adjudicate a claim (VERIFIED → APPROVED, or VERIFIED/DISPUTED → REJECTED) | ProgramAdmin |
| POST | `/fraud-cases` | Open a fraud case targeting exactly one subject | Auditor |
| GET | `/fraud-cases/{id}` | Read a fraud case | ProgramAdmin, Auditor |
| GET | `/fraud-cases` | List fraud cases, filterable by subject and status | ProgramAdmin, Auditor |
| POST | `/fraud-cases/{id}/confirm` | Confirm a case, executing the subject cascade | ProgramAdmin |
| POST | `/fraud-cases/{id}/clear` | Clear a case, with token compensation only | ProgramAdmin |
| POST | `/settlement-runs` | Sweep APPROVED claims up to an inclusive cutoff into PAID (OCC on program version) | ProgramAdmin |
| GET | `/settlement-runs/{id}` | Read a settlement run incl. swept ids and totals | ProgramAdmin, Auditor |
| GET | `/settlement-runs` | List settlement runs, filterable by program | ProgramAdmin, Auditor |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_MISSING_IDEMPOTENCY_KEY` | 400 Bad Request |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_TOKEN_UNKNOWN_SERIAL` | 404 Not Found |
| `ERR_TOKEN_NOT_MINTED` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SUBMISSION_EMPTY` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SHOPPER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_VENDOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_MARKET_DAY_NOT_OPEN` | 409 Conflict |
| `ERR_MARKET_DAY_NOT_CLOSED` | 409 Conflict |
| `ERR_TOKEN_FLAGGED` | 409 Conflict |
| `ERR_TOKEN_ALREADY_REDEEMED` | 409 Conflict |
| `ERR_TOKEN_VOID` | 409 Conflict |
| `ERR_TOKEN_VENDOR_MISMATCH` | 409 Conflict |
| `ERR_TOKEN_ALREADY_SUBMITTED` | 409 Conflict |
| `ERR_SEASON_INACTIVE` | 409 Conflict |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_MARKET_DAY_OVERLAP` | 409 Conflict |
| `ERR_SERIAL_RANGE_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_SUBJECT_AMBIGUOUS` | 422 Unprocessable Entity |
| `ERR_BATCH_SERIALS_INSUFFICIENT` | 409 Conflict |
| `ERR_NO_ACTIVE_TOKEN_BATCH` | 409 Conflict |
| `ERR_CHARGE_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_FRACTIONAL_CHARGE` | 422 Unprocessable Entity |
| `ERR_ISSUANCE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_RECONCILIATION_VARIANCE` | 409 Conflict |

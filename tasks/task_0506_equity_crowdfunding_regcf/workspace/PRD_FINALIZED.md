# Equity Crowdfunding (Reg CF) Portal API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for an online equity crowdfunding portal operating in the style of platforms such as StartEngine and Wefunder, with regulated raises conducted under the U.S. Regulation Crowdfunding (Reg CF) and Regulation A+ exemptions. The portal stitches together the full capital-raising journey: a company onboards as an **issuer** and files its Form C disclosure, a compliance team qualifies that disclosure, the company then publishes a public **offering** with a minimum and maximum funding target, and the investing public commits capital into an escrow account governed by accreditation and per-investor annual-limit rules.

The system is fundamentally a compliance-and-settlement engine. Committed funds sit in escrow rather than flowing directly to the issuer; only when a raise legitimately closes are securities minted onto a cap table, the escrow swept to the issuer net of fees, and any sub-share remainders returned to investors. A raise that fails to reach its minimum target triggers automatic refunds of every outstanding commitment. Around this spine sit several regulatory guardrails that the API must enforce precisely: a per-investor twelve-month investment ceiling, a five-million-dollar per-issuer twelve-month proceeds cap, bad-actor disqualification, segregation of duties between issuers and their reviewers, a reconfirmation right triggered by material disclosure amendments, a quiet-period gap between investor updates, and a non-overlap rule on an issuer's concurrent Reg CF campaign windows.

Because the platform settles money and issues securities, correctness and auditability outrank convenience. Every state change is recorded, every monetary figure is computed in integer cents, and concurrent edits to a live offering are mediated by optimistic concurrency control so that an investor can never commit against a view of the offering that has since moved on.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request that mutates state, and every read that is not explicitly public, must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which that principal is acting. The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Issuer`, `Investor`, and `ComplianceOfficer`. When a protected endpoint is called without a well-formed pair of these headers, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two of the roles are backed by persisted entities, and two are opaque. When `X-User-Role` is `Issuer`, `X-User-ID` is the `id` of the acting `Issuer`; any ownership check on a resource that references an issuer (for example, an offering through its `issuer_id`, or an investor update through the offering it belongs to) compares that resource's owning issuer to `X-User-ID`. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor`; ownership checks on a resource that references an investor (an investment through its `investor_id`, an accreditation request through its `investor_id`) compare the resource's investor foreign key to `X-User-ID`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reviewed_by_user_id` on an accreditation request when a review decision is written) but does not compare it to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque value not tied to any persisted entity and is used only for public registration and public reads; no ownership comparison is performed for anonymous callers.

Ownership is enforced independently of role permission. An `Issuer` may act only on its own offerings and on the investor updates of its own offerings, and an `Investor` may act only on its own investments and accreditation requests; a write against a resource the caller does not own is rejected with `ERR_NOT_RESOURCE_OWNER`. A distinct integrity rule, **segregation of duties**, governs Form C review: the `ComplianceOfficer` who qualifies or rejects a Form C must not be the same principal as the offering's issuer — that is, the officer's `X-User-ID` must not equal the offering's owning `Issuer` `id`. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and must be at least 1 and at most 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and has a minimum of 0. Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the query before pagination and `has_more` indicates whether further records remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three fractional digits. Most resources — issuers, offerings, investors, accreditation requests, investments, escrow accounts, and investor updates — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on each mutation. The `version` field is the basis for optimistic concurrency control described in §2.7.

The `CapTableEntry` resource is an exception: a cap-table position is an immutable record minted at close and never edited afterward, so it carries only an `id` and a `created_at` — it has neither an `updated_at` field nor a `version` field. Whenever a derived total on a resource changes (for example, an offering's `committed_amount_cents` or `swept_amount_cents`, or an escrow account's `held_amount_cents`), that change is itself a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Nested Resource Retrieval and Existence

Several read endpoints address a resource through a parent in the URL path — for example fetching an offering's escrow account, or listing the cap-table positions an offering minted. For any such request, path identifiers are validated left to right: the request is rejected with `ERR_NOT_FOUND` against the first identifier in the path that does not resolve to an existing resource, before any deeper resource or body reference is consulted. This same existence rule applies to every endpoint that references a resource by id in its path or body; a reference to a missing issuer, offering, investor, investment, accreditation request, or update yields `ERR_NOT_FOUND`.

### 2.6. Monetary Precision and Integer-Cent Arithmetic

All monetary quantities in this system are stored and computed as **integer numbers of cents** — there are no fractional cents and no floating-point money. Income, net worth, prices, targets, caps, commitments, escrow balances, disbursements, refunds, and cap-table principals are all whole-cent integers. Where a calculation divides (the percentage step of an investor's annual limit, or the share count produced by a commitment), the result is taken by integer division — the quotient floored to a whole number, with the remainder handled as the specific rule prescribes rather than rounded into the quotient. The single rounding operation in the system, the platform fee on a close, uses the round-half-up convention to the nearest whole cent, as detailed in §3.6.

### 2.7. Optimistic Concurrency Control on Commitments

A live offering's `version` advances on every event that changes what an investor can rely on — going live, each rolling-close sweep, a material Form C amendment, and a final close all bump it. To prevent an investor from committing against a stale view of remaining capacity and disclosure status, a commitment request must declare the offering version the investor last observed. Specifically, the create-investment operation requires a non-optional `expected_offering_version` field. If that value does not equal the target offering's current `version` at the moment the commitment is processed, the create is rejected with `ERR_STALE_OFFERING_VERSION` and HTTP status 412 — the investor must re-read the offering and retry against its current state. No other endpoint takes an offering-version field; this guard applies solely to placing a new investment.

### 2.8. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then role permission (`ERR_FORBIDDEN_ROLE`), then resource ownership (`ERR_NOT_RESOURCE_OWNER`), then segregation of duties for Form C review (`ERR_SEGREGATION_OF_DUTIES`), then existence of referenced resources (`ERR_NOT_FOUND`), then whether the target is in a legal state for the requested transition (`ERR_INVALID_STATE`). Only after these structural gates pass does the system evaluate domain-specific business rules, and finally request-body well-formedness (`ERR_INVALID_REQUEST`) for malformed payloads. The domain-specific rules and their relative ordering on shared endpoints are described where each workflow is introduced in §3; the create-investment workflow in §3.4, in particular, runs a precisely ordered cascade of business checks.

### 2.9. The Logical Clock

All time-sensitive rules — offering deadlines, campaign-window overlap, the trailing twelve-month windows, and the investor-update quiet period — are evaluated against a server **logical clock** rather than wall-clock time. The server boots with the clock set to exactly `2026-01-01T00:00:00Z`; until it is explicitly set, the clock reads this default and never falls back to real time. A `ComplianceOfficer` may advance the clock for test-driving by supplying a target instant in the `to_iso8601` field; doing so moves the instant used by all deadline and window rules.

## 3. Business Logic & Workflows

### 3.1. Issuer Onboarding and Verification

A company enters the platform by registering as an `Issuer`. Registration is public and may be performed by an `Anonymous` caller or a `ComplianceOfficer`; the payload carries the company's `legal_name`, its `ein` (a nine-digit Employer Identification Number that must be unique across all issuers), its `home_state_code` (the two-letter US state of incorporation), and its `entity_type`, which must be one of `C_CORP`, `LLC`, or `BENEFIT_CORP`. The payload may also carry a `bad_actor_flag`; when omitted it defaults to `false`. A freshly registered issuer is created in the `ONBOARDING` status, and its trailing-proceeds figure `total_raised_trailing_12mo_cents` begins at zero. Attempting to register a second issuer with an `ein` that already exists is rejected with `ERR_DUPLICATE_RESOURCE`.

Notably, a company that triggers a Rule 503 bad-actor disqualification is *not* blocked at registration — the flag is recorded so that it can be reviewed. The gate sits at verification instead. A `ComplianceOfficer` reviews an `ONBOARDING` issuer and either verifies it, advancing it `ONBOARDING → VERIFIED`, or bars it, advancing it `ONBOARDING → BARRED`. Verification is permitted only when the issuer is in `ONBOARDING` and its `bad_actor_flag` is `false`; an attempt to verify a flagged issuer is rejected with `ERR_BAD_ACTOR_DISQUALIFIED`. Barring is permitted from `ONBOARDING` and moves the issuer to the terminal `BARRED` status. Both transitions increment the issuer's `version` by one. Only a `VERIFIED` issuer may take an offering live.

### 3.2. Creating an Offering and the Form C Disclosure Cycle

A `VERIFIED` issuer's representative, acting as the `Issuer` role, creates an **offering** in the `DRAFT` status. The creation payload carries the `issuer_id` of the company conducting the raise, the `regulation` under which the raise is conducted (one of `REG_CF`, `REG_A_TIER_1`, or `REG_A_TIER_2`), the `security_type` (`EQUITY` or `SAFE`), the `min_target_cents` and `max_target_cents`, the `deadline_at` after which no further commitments are accepted, and optionally a `price_per_security_cents` and a `per_investor_cap_cents`. The offering's terms must be well-formed: `min_target_cents` must be greater than zero, and `max_target_cents` must be greater than or equal to `min_target_cents`. For an `EQUITY` offering, `price_per_security_cents` is required and must be greater than zero; for a `SAFE` offering, `price_per_security_cents` must be omitted or null. Any violation of these term rules is rejected with `ERR_INVALID_OFFERING_TERMS`. The optional `per_investor_cap_cents` defaults to null, meaning no per-offering ceiling on an individual investor.

A second gate applies to Reg CF raises at creation time. For a new offering whose `regulation` is `REG_CF`, the system enforces the five-million-dollar twelve-month per-issuer proceeds cap: the offering's `max_target_cents` added to the issuer's current trailing-twelve-month proceeds (see §3.7) must not exceed five million dollars, i.e. 500,000,000 cents. If it would push the issuer past that ceiling, creation is rejected with `ERR_ISSUER_CAP_EXCEEDED`.

A new offering starts with its `form_c_status` at `DRAFT` and its primary `status` at `DRAFT`, with `committed_amount_cents` and `swept_amount_cents` at zero, `secondary_listing_enabled` at `false`, and `live_at` and `close_at` both null. The Form C disclosure progresses on a sub-dimension that evolves independently of the primary lifecycle. The issuer submits the disclosure for review, advancing `form_c_status` from `DRAFT` to `SUBMITTED`; submission is permitted only while `form_c_status` is `DRAFT` and the offering's primary `status` is `DRAFT`. A `ComplianceOfficer` then reviews a `SUBMITTED` disclosure: qualifying it advances `SUBMITTED → QUALIFIED`, while rejecting it advances `SUBMITTED → REJECTED`. Qualification additionally enforces segregation of duties — the reviewing officer's identity must not be the offering's issuer — and a violation yields `ERR_SEGREGATION_OF_DUTIES`. A `REJECTED` disclosure may be revised and resubmitted, advancing `REJECTED → SUBMITTED`, and this revision loop may repeat. Each of these Form C transitions increments the offering's `version` by one.

### 3.3. Going Live and Concurrent Campaign Windows

Before commitments can flow, the issuer takes a qualified offering live, advancing its primary `status` from `DRAFT` to `LIVE`. Going live is gated on four conditions: the offering must currently be in `DRAFT`; its `form_c_status` must be `QUALIFIED`; its parent issuer must be in the `VERIFIED` status, with a failure here rejected as `ERR_ISSUER_NOT_VERIFIED`; and the logical clock must be strictly before the offering's `deadline_at`, with a clock at or past the deadline rejected as `ERR_OFFERING_DEADLINE_PASSED`. On success, the system provisions the offering's escrow account with a held balance of zero if one does not already exist, sets `live_at` to the current logical-clock instant, and increments the offering's `version` by one. The campaign window of an offering is the closed interval running from `live_at` through `deadline_at`.

An additional guard prevents an issuer from running overlapping Reg CF campaigns. When taking a `REG_CF` offering live, the system rejects go-live if any *other* offering of the same issuer that is also `REG_CF` and currently `LIVE` has a campaign window that overlaps the new one. The new window is the closed interval from the current logical-clock instant through this offering's `deadline_at`. Two such windows overlap when the existing offering's `live_at` is strictly before this offering's `deadline_at` and the current logical-clock instant is strictly before the existing offering's `deadline_at`; because both comparisons are strict, two windows that merely touch at a single instant — one window's `deadline_at` equal to the other's `live_at` — do not overlap and are permitted. A genuine overlap is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`.

A `DRAFT` offering with no commitments may be cancelled outright, advancing `DRAFT → CANCELLED`, which simply increments the offering's `version` by one. Cancellation of a `LIVE` offering is handled in §3.5.

### 3.4. Investor Registration, Accreditation, and Placing a Commitment

An investor joins the platform through public registration, performed by an `Anonymous` caller or a `ComplianceOfficer`. The payload carries the investor's `email` (unique across all investors), `legal_name`, `annual_income_cents`, and `net_worth_cents`, each of the latter two being a non-negative integer. A duplicate `email` is rejected with `ERR_DUPLICATE_RESOURCE`. A new investor's `accreditation_status` begins at `UNACCREDITED`, and the system computes the investor's `annual_limit_cents` at registration.

The annual limit is the Reg CF per-investor twelve-month ceiling that applies to unaccredited investors. It is derived from the two self-reported figures as follows. Let the lesser of `annual_income_cents` and `net_worth_cents` be the smaller figure and the greater be the larger. When both figures are at least one hundred twenty-four thousand dollars (12,400,000 cents), the base percentage is ten percent of the *lesser* figure, computed as the lesser figure multiplied by ten then integer-divided by one hundred (flooring). Otherwise — that is, when either figure is below one hundred twenty-four thousand dollars — the base percentage is five percent of the *greater* figure, computed as the greater figure multiplied by five then integer-divided by one hundred (flooring). The resulting `annual_limit_cents` is then clamped into the range whose floor is two thousand five hundred dollars (250,000 cents) and whose ceiling is one hundred twenty-four thousand dollars (12,400,000 cents): the system first takes the larger of the floor and the computed percentage, then takes the smaller of that result and the ceiling.

An investor may seek accredited status, which exempts them from the annual limit entirely. The investor files an **accreditation request** carrying their `investor_id` and a `method`, which must be one of `INCOME`, `NET_WORTH`, or `THIRD_PARTY_LETTER`; the request is created in `PENDING`. A `ComplianceOfficer` reviews it: approval advances `PENDING → APPROVED`, sets the investor's `accreditation_status` to `ACCREDITED`, and records the officer's identity in `reviewed_by_user_id`; denial advances `PENDING → DENIED` and records `reviewed_by_user_id` while leaving the investor's accreditation unchanged. Both decisions increment the accreditation request's `version` by one.

Placing capital is the central act of the platform. Acting as `Investor`, a committer creates an **investment** against a `LIVE` offering with a payload carrying the `offering_id`, the `investor_id`, the gross `amount_cents` (which must be greater than zero), and the `expected_offering_version` described in §2.7. The investment is created in the `COMMITTED` status with `securities_issued` and `refund_amount_cents` at zero and `reconfirm_required` at `false`. After the structural gates of §2.8, the create-investment workflow runs the following business checks in this order: first the offering deadline — the logical clock must be strictly before the offering's `deadline_at`, else `ERR_OFFERING_DEADLINE_PASSED`; then the optimistic-concurrency guard — `expected_offering_version` must equal the offering's current `version`, else `ERR_STALE_OFFERING_VERSION`; then the annual-limit check; then the per-investor cap; then oversubscription. Each is detailed next.

The **annual-limit check** applies only to an `UNACCREDITED` investor; an `ACCREDITED` investor bypasses it entirely with no upper bound. For an unaccredited investor, the system sums the investor's gross `amount_cents` across all of that investor's investments — spanning every offering — that are in `COMMITTED`, `RECONFIRMED`, or `ISSUED` status (commitments that were `CANCELLED` or `REFUNDED` are excluded) and whose `created_at` falls within the trailing twelve-month window, meaning at or after the instant exactly 365 days before the current logical clock. The commitment is admissible only if that running total plus the new `amount_cents` is at most the investor's `annual_limit_cents`; otherwise it is rejected with `ERR_ANNUAL_LIMIT_EXCEEDED`. The **per-investor cap** applies only when the offering's `per_investor_cap_cents` is set: the investor's cumulative commitment to *this* offering must not exceed that cap, otherwise the commitment is rejected with `ERR_PER_INVESTOR_CAP_EXCEEDED`. The **oversubscription check** protects the maximum target: the offering's `swept_amount_cents` plus its `committed_amount_cents` plus the new `amount_cents` must not exceed `max_target_cents`, otherwise the commitment is rejected with `ERR_OVERSUBSCRIBED`.

On a successful commit, the new investment is recorded, the offering's `committed_amount_cents` is recomputed as the sum of `amount_cents` over its investments in `COMMITTED` or `RECONFIRMED` status, the escrow account's `held_amount_cents` is recomputed by the same rule (so that escrow held always equals the offering's committed amount), and the offering's `version` is incremented by one.

### 3.5. Withdrawals, Reconfirmation, Failed Raises, and Cancellation

Reg CF grants an investor the right to withdraw a commitment any time before the offering deadline. An `Investor` may withdraw their own investment while it is in `COMMITTED` or `RECONFIRMED` status, provided the logical clock is strictly before the parent offering's `deadline_at`; a withdrawal after the deadline is rejected with `ERR_OFFERING_DEADLINE_PASSED`. Withdrawal advances the investment to `CANCELLED`, sets its `refund_amount_cents` to the full `amount_cents`, credits that amount back to the investor's wallet, debits escrow held, recomputes the offering's `committed_amount_cents`, and increments the investment's `version` by one. Unlike the bulk failed-raise and cancellation cascades, a single-investment withdrawal does *not* advance the escrow account's `refunded_amount_cents`; the only escrow balance it changes is `held_amount_cents`.

A material Form C amendment triggers the investor reconfirmation right. While an offering is in `DRAFT` or `LIVE` and its `form_c_status` is `QUALIFIED`, the issuer may file a material amendment, advancing `form_c_status` from `QUALIFIED` back to `SUBMITTED`. This amendment cascades: every investment on the offering currently in `COMMITTED` has its `reconfirm_required` set to `true`, and the offering's `version` is incremented by one. An investment whose `reconfirm_required` is `true` is excluded from any close batch until the investor re-affirms it. The affected `Investor` reconfirms their own such investment, advancing it `COMMITTED → RECONFIRMED`; reconfirmation is permitted only when the investment is in `COMMITTED` and its `reconfirm_required` is `true`. Reconfirming sets `reconfirm_required` back to `false`, making the investment eligible for the next close batch, and increments the investment's `version` by one.

When a raise fails, all outstanding commitments are automatically refunded. An offering moves `LIVE → FAILED` when a final close is attempted (or the deadline passes) and the minimum cannot be met — that is, when its `swept_amount_cents` plus its `committed_amount_cents` is less than `min_target_cents`. On failure, every investment on the offering in `COMMITTED` or `RECONFIRMED` status moves to `REFUNDED` with its `refund_amount_cents` set to the full `amount_cents` and that amount credited to the investor's wallet; the escrow account's `held_amount_cents` is driven to zero and its `refunded_amount_cents` is advanced by the total refunded; the offering's `status` is set to `FAILED`; and the offering's `version` is incremented by one. No cap-table position is minted on a failed raise.

Cancellation of a `LIVE` offering is the issuer-initiated counterpart. Cancelling a `LIVE` offering advances `LIVE → CANCELLED` and, for each investment still in `COMMITTED` or `RECONFIRMED`, moves it to `CANCELLED` with `refund_amount_cents` set to the full `amount_cents`, credits the wallet, drives escrow `held_amount_cents` to zero, advances escrow `refunded_amount_cents` by the total refunded, and increments the offering's `version` by one. Positions already issued in a prior close are untouched. (A `DRAFT` offering's cancellation, by contrast, simply moves it to `CANCELLED` as noted in §3.3.)

### 3.6. Closing a Raise: Issuance, Cap Table, and Escrow Disbursement

An issuer closes a raise either with an interim **rolling close** that keeps the offering live, or a **final close** that terminates the primary lifecycle. Both operate on a *close batch*: the set of investments being swept in this close, comprising the offering's investments in `COMMITTED` whose `reconfirm_required` is `false`, plus those in `RECONFIRMED`. Investments still flagged for reconfirmation are excluded from the batch.

Both close types require the minimum target to be reachable. A close is permitted only when the offering's `swept_amount_cents` plus the gross of the close batch is at least `min_target_cents`; if the cumulative swept total cannot reach the minimum, the close is rejected with `ERR_MINIMUM_NOT_MET`. A rolling close additionally requires the offering to be `LIVE` with `form_c_status` of `QUALIFIED`; it sweeps the batch exactly as a final close does but leaves the offering in `LIVE` (the `LIVE → LIVE` self-loop), so the raise keeps accepting commitments up to `max_target_cents`. A rolling close may fire repeatedly while the offering remains live. A final close, when the minimum is met, advances `LIVE → FUNDED`, sets the offering's `close_at` to the current logical-clock instant, and is gated on the offering being `LIVE` with a `form_c_status` of `QUALIFIED` (not pending a material-amendment re-qualification). When a final close is attempted but the minimum is not met, the offering instead moves to `FAILED` per §3.5.

Sweeping the batch is a transitive cascade: close → issuance → cap-table mint → escrow debit → offering totals. For each investment in the batch, its status moves to `ISSUED` (from either `COMMITTED` or `RECONFIRMED`), and issuance is computed per the security type. For an `EQUITY` offering, the number of `securities_issued` is the investment's `amount_cents` integer-divided by the offering's `price_per_security_cents` — the whole-share count, floored. The consideration recorded is `securities_issued` multiplied by `price_per_security_cents`, and the investment's `refund_amount_cents` is set to the whole-share rounding remainder, i.e. its `amount_cents` minus that consideration; this sub-share remainder is returned to the investor's wallet and is never rolled into the next share. The minted `CapTableEntry` records `instrument` as `EQUITY`, `quantity` as `securities_issued`, and `principal_cents` as the consideration. For a `SAFE` offering, no share math occurs: `securities_issued` is zero and `refund_amount_cents` is zero, and the minted `CapTableEntry` records `instrument` as `SAFE`, `quantity` as null, and `principal_cents` as the full `amount_cents`. Each minted `CapTableEntry` references the `offering_id`, `investor_id`, and `investment_id` it derives from. Each swept investment's `version` is incremented by one.

The disbursement arithmetic on a close follows a pinned order computed on the batch as a whole, not per investment. First, sum the batch gross — the total `amount_cents` of the investments in the close batch. Second, compute the platform fee on that sum: it is seven and one-half percent of the batch gross, i.e. the batch gross multiplied by 750 then divided by 10,000, rounded half up to the nearest whole cent. (Computing the fee once on the summed gross is required; summing per-line fees would diverge by rounding.) Third, sum the per-investment sub-share rounding remainders across the batch (each the `refund_amount_cents` from equity issuance; zero for SAFE). The net disbursed to the issuer is the batch gross minus the platform fee minus the summed remainders. The escrow account is then updated: its `held_amount_cents` is reduced by the batch gross, its `disbursed_amount_cents` is increased by the net disbursed, and its `refunded_amount_cents` is increased by the sum of the remainders plus the platform fee. The offering's `swept_amount_cents` is advanced to the sum of `amount_cents` over its investments now in `ISSUED`, its `committed_amount_cents` is recomputed over the remaining `COMMITTED`/`RECONFIRMED` investments, the issuer's trailing-proceeds basis is recomputed (§3.7), and the offering's `version` is incremented by one.

### 3.7. Issuer Proceeds Cap and Reg A+ Secondary Listing

Each time a Reg CF offering closes, the system recomputes the issuer's `total_raised_trailing_12mo_cents`. This figure is the sum of `swept_amount_cents` over the issuer's offerings whose `regulation` is `REG_CF`, whose `close_at` is non-null, and whose `close_at` falls at or after the instant exactly 365 days before the current logical clock. As described in §3.2, this trailing figure is the basis for the per-issuer cap enforced at offering creation: a new `REG_CF` offering's `max_target_cents` added to this figure must not exceed five million dollars (500,000,000 cents), or creation is rejected with `ERR_ISSUER_CAP_EXCEEDED`.

The platform supports a secondary resale listing only for Reg A+ Tier 2 raises that have funded. A `ComplianceOfficer` enables secondary listing on an offering, a self-loop that keeps the offering in `FUNDED` while setting its `secondary_listing_enabled` to `true` and incrementing its `version` by one. This is permitted only when the offering is in `FUNDED`, its `regulation` is `REG_A_TIER_2`, and its `secondary_listing_enabled` is currently `false`; an attempt to enable secondary on an offering whose regulation is not `REG_A_TIER_2` is rejected with `ERR_SECONDARY_NOT_PERMITTED`. The cap-table positions minted by an offering, each an immutable record of an investor's holding, can be retrieved for the offering or filtered across the platform by `investor_id`, `investment_id`, or `offering_id`, and an escrow account can be retrieved for its offering.

### 3.8. Investor Updates and the Quiet Period

An issuer keeps its investors informed by publishing **investor updates** tied to one of its offerings. The issuer drafts an update with a payload carrying the `offering_id`, a `title`, a `body`, and an optional `supersedes_update_id` that points to a prior update this one corrects or replaces (defaulting to null). A new update is created in `DRAFT`. Publishing advances `DRAFT → PUBLISHED` and is permitted only when the update is in `DRAFT` and the parent offering is in `LIVE` or `FUNDED` — updates cannot be published on a `DRAFT`, `CANCELLED`, or `FAILED` offering. On publication, the update's `published_at` is set to the current logical-clock instant and its `version` is incremented by one.

A quiet-period gap governs how frequently *non-superseding* updates may be published on the same offering. When the update's `supersedes_update_id` is null, publication is admissible only if there is no prior `PUBLISHED` update on the same offering, or the current logical-clock instant is strictly more than twenty-four hours after the most recent prior `PUBLISHED` update's `published_at` on that offering. This is a point-event-with-mandatory-gap rule, not an interval overlap: a publish exactly twenty-four hours after the prior one is still too soon and is rejected with `ERR_UPDATE_QUIET_PERIOD`. A superseding update — one whose `supersedes_update_id` is non-null — is exempt from the gap entirely. When a superseding update is published, the prior update it references (which must itself be `PUBLISHED`) cascades `PUBLISHED → SUPERSEDED`, with its own `version` incremented by one. Investor updates can be retrieved individually or listed for an offering, including filtering by the `supersedes_update_id` linkage.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions and the logical-clock advance — return a `200 OK` status code. Read operations return `200 OK`. The request and response payloads for each operation are described in the §3 narratives; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/issuers` | Onboard a new issuer (starts ONBOARDING) | Anonymous, ComplianceOfficer |
| GET | `/issuers/{id}` | Fetch an issuer | Anonymous, Issuer, ComplianceOfficer |
| GET | `/issuers` | List issuers | Anonymous, ComplianceOfficer |
| POST | `/issuers/{id}/verify` | Verify an issuer (ONBOARDING → VERIFIED) | ComplianceOfficer |
| POST | `/issuers/{id}/bar` | Bar an issuer (ONBOARDING → BARRED) | ComplianceOfficer |
| POST | `/offerings` | Create a DRAFT offering | Issuer |
| GET | `/offerings/{id}` | Fetch an offering with computed totals | Anonymous, Issuer, Investor, ComplianceOfficer |
| GET | `/offerings` | List offerings | Anonymous, Issuer, Investor, ComplianceOfficer |
| POST | `/offerings/{id}/form-c/submit` | Submit Form C (DRAFT or REJECTED → SUBMITTED) | Issuer |
| POST | `/offerings/{id}/form-c/qualify` | Qualify Form C (SUBMITTED → QUALIFIED) | ComplianceOfficer |
| POST | `/offerings/{id}/form-c/reject` | Reject Form C (SUBMITTED → REJECTED) | ComplianceOfficer |
| POST | `/offerings/{id}/form-c/amend` | File a material amendment (QUALIFIED → SUBMITTED) | Issuer |
| POST | `/offerings/{id}/go-live` | Take a qualified offering LIVE | Issuer |
| POST | `/offerings/{id}/rolling-close` | Interim rolling close (LIVE → LIVE) | Issuer |
| POST | `/offerings/{id}/close` | Final close (→ FUNDED or → FAILED) | Issuer |
| POST | `/offerings/{id}/cancel` | Cancel an offering (DRAFT or LIVE → CANCELLED) | Issuer |
| POST | `/offerings/{id}/enable-secondary` | Enable secondary listing (Reg A+ Tier 2) | ComplianceOfficer |
| GET | `/offerings/{id}/escrow` | Fetch the offering's escrow account | Issuer, ComplianceOfficer |
| GET | `/offerings/{id}/cap-table` | List cap-table positions minted by the offering | Issuer, Investor, ComplianceOfficer |
| GET | `/cap-table-entries/{id}` | Fetch a single cap-table position | Issuer, Investor, ComplianceOfficer |
| GET | `/cap-table-entries` | List cap-table positions | Issuer, Investor, ComplianceOfficer |
| POST | `/investors` | Register an investor (starts UNACCREDITED) | Anonymous, ComplianceOfficer |
| GET | `/investors/{id}` | Fetch an investor | Anonymous, Investor, ComplianceOfficer |
| POST | `/accreditation-requests` | File an accreditation request (PENDING) | Investor |
| GET | `/accreditation-requests/{id}` | Fetch an accreditation request | Investor, ComplianceOfficer |
| GET | `/accreditation-requests` | List accreditation requests | Investor, ComplianceOfficer |
| POST | `/accreditation-requests/{id}/approve` | Approve (PENDING → APPROVED); set investor ACCREDITED | ComplianceOfficer |
| POST | `/accreditation-requests/{id}/deny` | Deny (PENDING → DENIED) | ComplianceOfficer |
| POST | `/investments` | Commit to a LIVE offering | Investor |
| GET | `/investments/{id}` | Fetch an investment | Investor, Issuer, ComplianceOfficer |
| GET | `/investments` | List investments | Investor, Issuer, ComplianceOfficer |
| POST | `/investments/{id}/reconfirm` | Reconfirm a flagged commitment (COMMITTED → RECONFIRMED) | Investor |
| POST | `/investments/{id}/withdraw` | Withdraw before deadline (→ CANCELLED) | Investor |
| POST | `/investor-updates` | Draft an investor update (DRAFT) | Issuer |
| GET | `/investor-updates/{id}` | Fetch a single investor update | Anonymous, Issuer, Investor, ComplianceOfficer |
| GET | `/investor-updates` | List investor updates | Anonymous, Issuer, Investor, ComplianceOfficer |
| POST | `/investor-updates/{id}/publish` | Publish an update (DRAFT → PUBLISHED) | Issuer |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | ComplianceOfficer |

The list endpoints accept the following filter query parameters in addition to `limit` and `offset`: issuers by `home_state_code` and `status`; offerings by `issuer_id`, `regulation`, and `status`; accreditation requests by `investor_id` and `status`; investments by `offering_id`, `investor_id`, and `status`; cap-table entries by `offering_id`, `investor_id`, and `investment_id`; and investor updates by `offering_id`, `supersedes_update_id`, and `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_OFFERING_DEADLINE_PASSED` | 409 |
| `ERR_BAD_ACTOR_DISQUALIFIED` | 422 |
| `ERR_ISSUER_NOT_VERIFIED` | 409 |
| `ERR_ANNUAL_LIMIT_EXCEEDED` | 422 |
| `ERR_PER_INVESTOR_CAP_EXCEEDED` | 422 |
| `ERR_OVERSUBSCRIBED` | 409 |
| `ERR_MINIMUM_NOT_MET` | 409 |
| `ERR_ISSUER_CAP_EXCEEDED` | 422 |
| `ERR_INVALID_OFFERING_TERMS` | 422 |
| `ERR_SECONDARY_NOT_PERMITTED` | 422 |
| `ERR_CAMPAIGN_WINDOW_OVERLAP` | 409 |
| `ERR_UPDATE_QUIET_PERIOD` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_STALE_OFFERING_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |

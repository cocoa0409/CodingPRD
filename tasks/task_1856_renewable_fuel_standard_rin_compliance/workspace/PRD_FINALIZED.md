# RFS RIN Compliance API — Product Requirements Document

## 1. Introduction

Under the United States Renewable Fuel Standard, every obligated party — a refiner or importer of non-renewable gasoline and diesel — must demonstrate each year that enough renewable fuel entered the motor-fuel supply to offset its production volume. That demonstration is made in Renewable Identification Numbers (RINs): tradable credits generated alongside each gallon of qualifying renewable fuel, separated from the physical product when it is blended, bought and sold between market participants, and ultimately retired against the party's renewable volume obligation. This document specifies the API for an obligated-party RFS compliance desk: recording blending activity and the RIN generation it drives, computing provisional and final obligations from EPA standard percentages, executing and verifying RIN purchases, retiring RINs against nested obligation categories, and filing the quarterly and annual compliance reports EPA requires.

The desk operates under unforgiving regulatory discipline. Purchased RINs carry invalidation risk — a counterparty whose product is later found non-qualifying can contaminate lots that have already been delivered, verified, or even retired — so vendor due diligence, segregated trade verification, and a full invalidation cascade are first-class behaviors rather than afterthoughts. Annual compliance further depends on a third-party attest engagement whose clean close gates the annual report, and a state low-carbon credit overlay runs alongside the federal obligation with its own carbon-intensity accounting. Because deadlines, vintage expiries, verification windows, and retention cutoffs all turn on the passage of time, the service runs on a logical clock that operators advance explicitly, making the compliance calendar deterministic. All desk resources are mounted under the `/rfs` prefix; a single clock-setting capability sits at the API root.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across the entire API: identity and authorization, the response envelope, pagination, resource identity and the logical clock, arithmetic precision, obligation accounting, concurrency control, validation ordering, retention, and the compliance calendar.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. Four roles exist, spelled exactly as follows. `OpsAdmin` is the platform operator doubling as the EPA/regulator proxy: it registers obligated-party accounts, records market price quotes, decides retirement batches and compliance reports, advances the logical clock, and purges aged records. `ComplianceManager` is the RFS desk lead: it opens obligation years, records generation and blending, runs vendor diligence, builds and submits retirement batches and reports, manages the state-program overlay, and verifies or invalidates delivered RINs. `Trader` onboards vendor counterparties and executes purchases — creating, paying, delivering, and cancelling trades — but may never verify a purchase it created. `Auditor` is the independent attest professional who runs fieldwork, issues findings, and closes engagements; auditor identity is captured per engagement. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (401). A request whose authenticated role is not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (403).

All four roles are opaque identities. When `X-User-Role` is `OpsAdmin`, `ComplianceManager`, `Trader`, or `Auditor`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity, and the server never compares it against any resource's `id`. The server does record it in designated places — as `created_by_user_id` on a RIN purchase and on a compliance report, as `verified_by_user_id` on a verified purchase, and as `auditor_user_id` on an attest engagement — and those recorded values anchor the segregation-of-duties and auditor-identity checks narrated in §3. An action that violates segregation of duties is rejected with `ERR_SEGREGATION_OF_DUTIES` (403).

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

List endpoints paginate through two query parameters: `limit`, the maximum number of items returned, defaults to 10 and accepts values from a minimum of 1 to a maximum of 100; `offset`, the number of items skipped, defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Many list endpoints also accept an optional scoping filter — obligation years, vendors, lots, trades, programs, and quotes can each be scoped by `account_id`, for instance — and the filter parameters each resource supports are introduced alongside its workflow in §3.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every primary resource carries a standard set of system-managed properties: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that increments by one on every mutation of the resource, including mutations the server applies itself as cascading side effects. `updated_at` is refreshed to the moment of each mutation. That ISO 8601 UTC format with three fractional digits and a trailing `Z` is used uniformly for every timestamp the API returns — not only `created_at` and `updated_at` but fields such as `due_date`, `quarter_end_date`, `submitted_at`, `retention_until`, and the clock endpoint's `current_utc`. One deliberate exception exists: the BlendingRecord is an immutable event log and carries only `id` and `created_at` — `updated_at` and `version` are absent because a blending record, once written, never changes.

Time itself is a controlled input to this API. The service maintains a logical clock whose startup default, before any operator action, is exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time. An `OpsAdmin` advances the clock through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`. Advancing the clock is not cosmetic: it fires the vintage-expiry sweep across all active lots (§2.10) and re-derives the compliance posture of every obligation year (§2.6).

### 2.5. RIN Arithmetic, Monetary Units, and Precision

RINs are whole units. When a lot is generated, its RIN quantity is the wet-gallon volume multiplied by its equivalence value, rounded half-up to zero decimal places — and that rounding is applied per lot at the moment of generation. Position and obligation totals then sum the already-rounded per-lot quantities; the aggregate is never rounded again. Two lots of one gallon each at an equivalence value of 1.5 therefore contribute 2 RINs apiece, 4 in total — not the 3 that rounding their combined product would yield.

Obligation quantities, retirement counters, and carryover caps are likewise integers rounded half-up to zero decimal places at the point of computation. Monetary amounts are integer cents throughout: a trade's total price is the exact integer product of its quantity and its per-RIN price, with no rounding at all. Two exceptions to integer precision exist. The weighted-average unit cost used in exposure mark-to-market is pinned at four decimal places, rounded half-up, so that intermediate reads stay deterministic, though bucket gains and the exposure total itself are whole cents rounded half-up. And state low-carbon credit quantities are carried at four decimal places, rounded half-up. EPA standard percentages and carbon-intensity values are plain numbers: a standard entered as 10.0 means ten percent.

### 2.6. Obligation Accounting: Provisional and Final RVOs

Each obligation year carries two generations of its renewable volume obligation. At creation, the provisional variant computes `provisional_rvo_cellulosic_rins`, `provisional_rvo_biomass_diesel_rins`, `provisional_rvo_advanced_rins`, and `provisional_rvo_total_rins`; each equals the projected non-renewable volume multiplied by the corresponding EPA standard percentage divided by one hundred, rounded half-up to a whole RIN. When the year's actual volume is later closed, the final variant recomputes the same four quantities from the actual volume and writes them to `final_rvo_cellulosic_rins`, `final_rvo_biomass_diesel_rins`, `final_rvo_advanced_rins`, and `final_rvo_total_rins`; until that moment every final figure remains null. Which generation is authoritative follows the year's `status`: while the year is `OPEN` the provisional figures are active, and once the year is `VOLUME_CLOSED` or `FINALIZED` the final figures take over. Identical inputs would produce identical values under either variant, but projected and actual volumes diverge, so a year's provisional and final obligations generally differ. Carryover caps (§3.5) and the compliance posture always read the active generation.

Posture is derived, never set directly. A year's `compliance_posture` is `SATISFIED` when, for every one of the four categories, the year's retired-RIN counter is at least the active RVO for that category — a counter exactly equal to its RVO counts as satisfied. When the year is not satisfied and the logical clock has passed the retirement deadline — 23:59:59 UTC on March 31 of the year following the compliance year — the posture is `SHORTFALL`. In every other circumstance it is `ON_TRACK`. The posture is re-derived after every retirement decision, every lot invalidation, every volume close, and every clock advance.

### 2.7. Report Creation under Optimistic Concurrency

Creating a compliance report is the single operation guarded by optimistic concurrency control. The creation request must carry `expected_obligation_year_version`, holding the version of the obligation year the client last observed. If the year's current `version` no longer matches that value — for instance because another writer has since created a report for the same year, an action that legitimately supersedes the prior same-type draft and advances the year's version — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a year state it has not observed. Endpoints other than report creation do not accept a version field.

### 2.8. Validation Order and Request Evaluation

When several checks could reject the same request, they run in a fixed order so the surfaced error is deterministic. Authentication comes first: missing or invalid headers yield `ERR_UNAUTHENTICATED`. Role authorization follows (`ERR_FORBIDDEN`), then segregation-of-duties enforcement (`ERR_SEGREGATION_OF_DUTIES`) on the two operations that apply it — trade verification and report submission. Next, path identifiers are resolved strictly left to right, and the first identifier that does not name an existing resource yields `ERR_NOT_FOUND`. Only then is the request body examined for shape: required fields present, enum values valid, quantities positive, the EPA standard percentages monotonically ordered, the quarter-end-date rule honored, and window bounds well formed — violations yield `ERR_INVALID_REQUEST`. Referential integrity of body foreign keys follows: a referenced account, vendor, obligation year, state program, or RIN lot that does not exist — or sibling references that belong to different accounts, such as a trade whose vendor belongs to another desk — yields `ERR_REFERENCE_NOT_FOUND`. The optimistic-concurrency check on report creation comes next (`ERR_STALE_VERSION`), then state-machine admissibility (`ERR_INVALID_STATE`, which covers the FINALIZED-year gates, the trade payment/transfer cross-guards, and the same-type non-draft report that blocks a new report). Regulatory gates are evaluated after that: vendor approval (`ERR_VENDOR_NOT_APPROVED`), invalidated-RIN protection (`ERR_RIN_INVALIDATED`), the clean-attest gate (`ERR_ATTEST_NOT_CLEAN`), and category eligibility (`ERR_D_CODE_NOT_ELIGIBLE`). Uniqueness and overlap constraints follow (natural-key uniqueness violations via `ERR_INVALID_REQUEST`, plus `ERR_ENGAGEMENT_WINDOW_OVERLAP` and `ERR_PRICE_WINDOW_OVERLAP`), then the temporal gates (`ERR_INVALID_VINTAGE`, `ERR_DEADLINE_PASSED`, `ERR_VERIFICATION_WINDOW_EXPIRED`, `ERR_RETENTION_ACTIVE`), and finally quantity sufficiency and caps (`ERR_SEPARATION_EXCEEDS_ATTACHED`, `ERR_INSUFFICIENT_RINS`, `ERR_CARRYOVER_CAP_EXCEEDED`).

### 2.9. Record Retention and Purge

Federal recordkeeping obligations attach to RIN lots, blending records, trades, compliance reports, and price quotes: each carries a `retention_until` timestamp fixed at creation as its `created_at` plus 1825 days — a five-year retention expressed as a fixed day count so that leap years are absorbed. An `OpsAdmin` may purge an account's aged records, purging those blending records and price quotes of the account whose `retention_until` has been reached. A record is purgeable when its `retention_until` is equal to or earlier than the current logical clock — a record exactly at its retention instant is purgeable, while one second before it is not. If any record the purge targets is still within its retention window, the request fails entirely with `ERR_RETENTION_ACTIVE` and nothing is deleted; otherwise the eligible records are hard-deleted and the response reports the counts as `purged_blending_records` and `purged_price_quotes`.

### 2.10. The Compliance Calendar: Vintages, Deadlines, and Windows

A RIN's `vintage_year` is the calendar year its fuel was generated, and a vintage-V RIN is usable for compliance years V and V+1. Generation is bounded accordingly: a new lot's `vintage_year` must be the logical clock's current calendar year or the year immediately before it, otherwise creation is rejected with `ERR_INVALID_VINTAGE`.

Once the logical clock passes 23:59:59 UTC on March 31 of the year two years after a lot's vintage, every still-`ACTIVE` lot of that vintage expires in the sweep. The lot's status becomes `EXPIRED`; its `expired_qty` rises to absorb every RIN not already retired or invalidated — the available, pending, and still-attached balances alike; and `attached_qty`, `separated_qty`, `pending_retired_qty`, and `available_qty` all fall to zero. Pending retirement allocations on an expiring lot are not released into retirement: any batch holding them remains `SUBMITTED` and will fail its eventual decision with `ERR_INSUFFICIENT_RINS`.

Three further windows bind the desk. Retirement batches for an obligation year must be submitted at or before 23:59:59 UTC on March 31 of the year following the compliance year; a later submission is rejected with `ERR_DEADLINE_PASSED`. An annual report's `due_date` falls at that same instant, while a quarterly report's `due_date` falls sixty days after its `quarter_end_date`. And a delivered trade must be verified within thirty days of delivery: verification at exactly the thirtieth day remains inside the window, and any later attempt is rejected with `ERR_VERIFICATION_WINDOW_EXPIRED`.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Desk: Accounts and Obligation Years

An `OpsAdmin` registers each obligated party with its legal `company_name` and its EPA-issued `epa_registration_id`, which must be unique across accounts — a duplicate registration is rejected with `ERR_INVALID_REQUEST`. The account opens with `escrow_reserved_cents` and `spent_cents` both at zero; these two counters form the purchase ledger that §3.3 exercises.

With the account standing, a `ComplianceManager` opens a compliance year by naming the `account_id`, the calendar `year`, the `projected_volume_gal` of non-renewable gasoline and diesel the party expects to produce (a positive integer), and the four EPA standard percentages `std_cellulosic_pct`, `std_biomass_diesel_pct`, `std_advanced_pct`, and `std_total_pct`. The percentages must be non-negative and monotonically non-decreasing in that order — cellulosic may equal but never exceed biomass-based diesel, biomass-based diesel may equal but never exceed advanced, and advanced may equal but never exceed total — and a malformed set is rejected with `ERR_INVALID_REQUEST`. The account-and-year pair must also be unique, so opening a second record for the same account and calendar year draws `ERR_INVALID_REQUEST`, while naming a missing account draws `ERR_REFERENCE_NOT_FOUND`. Creation computes the provisional RVOs per §2.6, sets `status` to `OPEN` and `compliance_posture` to `ON_TRACK`, zeroes the eight retirement counters — `retired_cellulosic_rins`, `retired_biomass_diesel_rins`, `retired_advanced_rins`, `retired_total_rins` and their prior-vintage companions `retired_prior_cellulosic_rins`, `retired_prior_biomass_diesel_rins`, `retired_prior_advanced_rins`, and `retired_prior_total_rins` — and leaves `actual_volume_gal` null until volumes are closed.

When the year's production is known, the `ComplianceManager` closes volumes by supplying `actual_volume_gal`, which must be positive (`ERR_INVALID_REQUEST` otherwise). The year transitions `OPEN` → `VOLUME_CLOSED`, the final RVOs are computed from the actual volume per §2.6 and take over as the active obligation, the posture is re-derived, and the year's `version` increments by one. Obligation years can be read individually or listed, with the list optionally scoped by `account_id`.

### 3.2. Generation, Blending, and RIN Separation

Renewable production enters the system when a `ComplianceManager` records a lot with its `account_id`, a `d_code` of `D3` (cellulosic), `D4` (biomass-based diesel), `D5` (advanced), or `D6` (conventional renewable), a `vintage_year` bounded by the clock per §2.10, the `gallon_qty` of wet fuel produced, and an `equivalence_value` expressing RINs per gallon — 1.0 for ethanol or 1.5 for biodiesel, defaulting to 1.0 when omitted. Such a lot's `origin` is `GENERATED`, its `vendor_id` and `trade_id` are null, its `unit_cost_cents` is zero, and its `rin_qty` is the per-lot rounded product described in §2.5. At creation all of those RINs remain attached to physical gallons: `attached_qty` equals `rin_qty`, `separated_qty` is zero, and `available_qty` equals `rin_qty`, while `pending_retired_qty`, `retired_qty`, `invalidated_qty`, and `expired_qty` all start at zero. Throughout a lot's life its `rin_qty` is fully accounted for as the sum of those six buckets, and `available_qty` — the retirement-eligible balance — is always what remains of `rin_qty` after subtracting the attached, pending, retired, invalidated, and expired quantities. Each lot fixes its `retention_until` at creation per §2.9 and opens in `ACTIVE` status.

Separation is the blending event that frees RINs from gallons. A `ComplianceManager` records that `blended_gallons` of the lot's fuel were blended into motor fuel; the quantity must be positive and must not exceed the lot's `attached_qty` — blending exactly the remaining attached quantity succeeds, while one gallon more is rejected with `ERR_SEPARATION_EXCEEDS_ATTACHED`. The lot's `attached_qty` then falls by the blended amount and its `separated_qty` rises by the same, leaving `available_qty` unchanged. Each blending writes an immutable BlendingRecord that copies the `account_id` from the separated lot, takes the `rin_lot_id` from the request path, stamps `blended_at` from the logical clock, and fixes its own `retention_until`. A lot that stands `INVALIDATED` refuses separation with `ERR_RIN_INVALIDATED`, and an `EXHAUSTED` lot — one whose available balance was fully retired, per §3.5 — is no longer eligible for separation, verification gating, or allocation. Lots may be listed with optional `account_id`, `vendor_id`, or `trade_id` filters, and blending records may be listed by `account_id` or `rin_lot_id`.

### 3.3. Counterparty Diligence and the Purchase Ledger

A `Trader` onboards each selling counterparty with its `vendor_name` and a `qap_audited` flag recording whether the seller's RINs are covered by a Quality Assurance Program audit. A new vendor's `diligence_status` starts `UNVETTED` with `last_diligence_at` null. Due diligence belongs to the `ComplianceManager`, who records an `outcome` on the vendor: an `UNVETTED` vendor may move to `APPROVED` or to `REJECTED`, a `REJECTED` vendor may later move to `APPROVED`, and an `APPROVED` vendor may be `REVOKED` — the revocation cascade of §3.4. Every diligence decision stamps `last_diligence_at` from the logical clock; `REVOKED` is terminal, and an outcome that does not correspond to a declared transition from the vendor's current status is rejected with `ERR_INVALID_STATE`. Vendors may be read individually or listed, optionally scoped by `account_id`.

Purchases begin when a `Trader` executes a trade naming the `account_id`, the selling `vendor_id`, the `d_code`, the `vintage_year`, the `rin_qty` purchased, and the agreed `price_per_rin_cents` — quantity and unit price both strictly positive. The vendor must exist and belong to the trade's account (`ERR_REFERENCE_NOT_FOUND` otherwise). The trade's `total_price_cents` is the exact integer product of quantity and unit price, and that amount is immediately reserved: the account's `escrow_reserved_cents` rises by the total while the trade sits with `payment_status` `UNPAID` and `transfer_status` `PENDING`, and the creating operator's identity is recorded as `created_by_user_id`. Payment converts reservation into spend: the trader pays, which requires the transfer to still be `PENDING` (`ERR_INVALID_STATE` otherwise), moves payment `UNPAID` → `PAID`, and shifts the total out of `escrow_reserved_cents` and into `spent_cents`. The ledger invariant holds at every step — the escrow balance always equals the sum of totals over trades that are unpaid and awaiting delivery, and the spend balance the sum over trades currently paid.

Delivery follows payment. Recording delivery requires `payment_status` `PAID` (`ERR_INVALID_STATE` otherwise) and moves the transfer `PENDING` → `DELIVERED`, stamping `delivered_at` from the logical clock. Delivery also mints the purchased lot: `origin` `PURCHASED`, with the account, vendor, and trade references copied from the trade along with `d_code` and `vintage_year`; `gallon_qty` zero and `equivalence_value` 1.0 because purchased RINs arrive already separated; `rin_qty` equal to the trade's quantity, with `attached_qty` zero and `separated_qty` and `available_qty` equal to `rin_qty`; `unit_cost_cents` set to the trade's `price_per_rin_cents`; status `ACTIVE`.

Verification is the desk's invalid-RIN defense, and it is deliberately segregated from execution. A `ComplianceManager` performs it, and the verifier must not be the trader who created the purchase — a verifier whose `X-User-ID` equals the trade's `created_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. The vendor must stand `APPROVED` at verification time (`ERR_VENDOR_NOT_APPROVED` otherwise), and the attempt must fall within the thirty-day window after `delivered_at` (`ERR_VERIFICATION_WINDOW_EXPIRED` beyond it). Successful verification moves the transfer `DELIVERED` → `VERIFIED`, records `verified_by_user_id`, and makes the purchased lot retirement-eligible: purchased lots enter retirement allocation only once their source trade is `VERIFIED`, as §3.5 details.

A trade can be unwound only before delivery. Cancelling a still-`PENDING` transfer moves it to `CANCELLED`; when the trade was never paid, the reserved escrow is released — `escrow_reserved_cents` falls by the total — and payment stays `UNPAID`, while a paid trade is refunded: `spent_cents` falls by the total and payment moves `PAID` → `REFUNDED`. Trades may be read individually or listed with optional `account_id` or `vendor_id` filters.

### 3.4. Invalid RINs and the Vendor-Revocation Cascade

When EPA finds delivered RINs invalid — or the desk loses confidence in them — a `ComplianceManager` invalidates the trade, moving a `DELIVERED` or `VERIFIED` transfer to `INVALIDATED`. Either way, the purchased lot is invalidated alongside: the lot's status becomes `INVALIDATED`, its `invalidated_qty` absorbs everything not already retired or expired (the available, pending, and attached balances alike), and `attached_qty`, `separated_qty`, `pending_retired_qty`, and `available_qty` all fall to zero. Allocations the lot was holding are released from their retirement batches; those batches stay `SUBMITTED` and will fail their eventual decision with `ERR_INSUFFICIENT_RINS`. Invalidating a `VERIFIED` trade additionally claws back any of the lot's RINs already retired: the obligation year's retired counters are not decremented by a delta but re-derived from scratch over the year's `ACCEPTED` batches, excluding RINs that sit on invalidated lots, and the year's posture is re-derived with them.

The cascade reaches the public file. When a lot invalidation mutates a year's retired counters beneath a report EPA has already accepted, every `ACCEPTED` report for that year is driven back to `REJECTED` with `amendment_required` set to true — the desk's signal to amend and resubmit through the reopen workflow of §3.6.

Revoking a vendor fires the same cascade at portfolio scale. Every trade of the revoked vendor whose transfer stands `DELIVERED` or `VERIFIED` becomes `INVALIDATED`, and each per-trade cascade — lot invalidation, year counter re-derivation, posture re-derivation, accepted-report reflagging — fires exactly as declared above. Once a lot or trade stands `INVALIDATED`, later operations against it are guarded: separation against the lot, a second invalidation, or verification after invalidation are each rejected with `ERR_RIN_INVALIDATED`.

### 3.5. Retiring RINs Against the Obligation

Retirement is how RINs satisfy the obligation, and the categories nest: a retired RIN counts toward every category its D-code maps to. `D3` counts toward `CELLULOSIC`, `ADVANCED`, and `TOTAL_RENEWABLE`; `D4` toward `BIOMASS_DIESEL`, `ADVANCED`, and `TOTAL_RENEWABLE`; `D5` toward `ADVANCED` and `TOTAL_RENEWABLE`; `D6` toward `TOTAL_RENEWABLE` only. A `ComplianceManager` opens a retirement batch by naming the `obligation_year_id`, the target `category`, the `d_code` being retired, and the `rin_qty` to retire; the category must be one the D-code maps to, or creation fails with `ERR_D_CODE_NOT_ELIGIBLE`. No batch may be created for a `FINALIZED` year (`ERR_INVALID_STATE`). New batches stand `DRAFT` with `allocations` empty and `prior_vintage_qty` zero.

Submission is where the machinery runs. The year must be `OPEN` or `VOLUME_CLOSED` — a `FINALIZED` year rejects submission with `ERR_INVALID_STATE` — and the logical clock must not have passed the retirement deadline of §2.10 (`ERR_DEADLINE_PASSED`). The system then draws lots first-in-first-out. A lot is eligible when it belongs to the obligation year's account, stands `ACTIVE`, matches the batch's `d_code`, carries a `vintage_year` equal to the obligation year or the year immediately before it, and still has a positive `available_qty` — generated lots contribute their separated, available balance, while purchased lots qualify only when their source trade stands `VERIFIED`. Eligible lots are ordered by `created_at` ascending with ties broken by `rin_qty` ascending (never by lot id), and the draw takes from each lot the smaller of its available balance and the remaining need until the batch is filled; if the eligible supply totals less than `rin_qty`, submission fails with `ERR_INSUFFICIENT_RINS`. The resulting draw list is recorded as the batch's `allocations` in draw order, `prior_vintage_qty` captures the portion drawn from lots of the prior vintage year, each allocated lot moves the drawn quantity from `separated_qty` into `pending_retired_qty`, and `submitted_at` is stamped from the logical clock.

Prior-vintage RINs are capped at submission. The carryover allowance for a category is twenty percent of the active RVO for that category, rounded half-up to a whole RIN. Submission passes only while the batch's `prior_vintage_qty` plus the year's already-retired prior-vintage counter for that category stays at or below the cap — a batch landing exactly at the cap passes, while one RIN beyond it fails with `ERR_CARRYOVER_CAP_EXCEEDED`. Current-vintage RINs are uncapped, and the prior-vintage counters count only `ACCEPTED` batches.

The decision rests with `OpsAdmin`, acting as the regulator, through a `decision` of `ACCEPT` or `REJECT`. Acceptance requires every allocated lot to still stand `ACTIVE` with a pending balance covering its allocation — a lot that expired or was invalidated while the batch sat `SUBMITTED` fails the decision with `ERR_INSUFFICIENT_RINS`. On acceptance each allocated lot's pending quantity converts into `retired_qty`; a lot whose available balance thereby reaches zero becomes `EXHAUSTED` and leaves all further separation and allocation. The year's counters are then re-derived per the nested mapping — a batch retiring quantity Q of a given D-code with prior-vintage portion P adds Q to the retired counter of every category that D-code maps to, and P to each of those categories' prior-vintage retired counters — and the posture is re-derived, potentially flipping the year to `SATISFIED`. Rejection instead releases the pending allocations back onto each lot's `separated_qty`, restoring the lot's conservation balance. Batches may be read individually or listed, optionally scoped by `obligation_year_id`.

### 3.6. EPA Reporting, Attest Engagements, and Year Close

Reporting begins when a `ComplianceManager` creates a report for an obligation year, naming the `obligation_year_id` and a `report_type` of `QUARTERLY` or `ANNUAL`. A quarterly report must supply `quarter_end_date`, the last day of the reported quarter, while an annual report must not — omitting it on a quarterly report or supplying it on an annual one is rejected with `ERR_INVALID_REQUEST`. The creation also carries the optimistic-concurrency field `expected_obligation_year_version` described in §2.7, and a mismatch with the year's current version is rejected with `ERR_STALE_VERSION`. The new report stands `DRAFT`; its `due_date` is computed per §2.10, its `created_by_user_id` records its author, its `retention_until` is fixed per §2.9, and the year's `version` advances by one. Creation enforces one live draft per type for the year: a prior `DRAFT` report of the same `report_type` moves to `SUPERSEDED`, while a same-type report standing `SUBMITTED`, `ACCEPTED`, or `REJECTED` blocks creation outright with `ERR_INVALID_STATE`. No report may be created for a `FINALIZED` year.

Submission moves a `DRAFT` report to `SUBMITTED` and is guarded three ways. Segregation first: the submitter must not be an auditor on the same year, so if any attest engagement on the obligation year has an `auditor_user_id` equal to the submitter's `X-User-ID`, submission is rejected with `ERR_SEGREGATION_OF_DUTIES`. The attest gate second: an `ANNUAL` report may be submitted only while an attest engagement for the year stands `CLOSED_CLEAN`, otherwise submission is rejected with `ERR_ATTEST_NOT_CLEAN`; quarterly reports carry no such gate. The year gate third: a `FINALIZED` year rejects submission with `ERR_INVALID_STATE`. A successful submission stamps `submitted_at` from the logical clock and computes `is_late`, which is true exactly when the submission instant falls after the report's `due_date`.

`OpsAdmin` then decides the report through a `decision` of `ACCEPT` or `REJECT`, moving a `SUBMITTED` report to `ACCEPTED` or `REJECTED` respectively. Two paths back to draft exist. A `ComplianceManager` may reopen a `REJECTED` report, returning it to `DRAFT` with `submitted_at` cleared and `is_late` reset to false; and an accepted report may be voluntarily amended the same way — reopening an `ACCEPTED` report returns it to `DRAFT`, clears `submitted_at` and `is_late`, and additionally resets `amendment_required` to false. An accepted report can also be forced back to `REJECTED` without any operator action by the invalid-RIN cascade of §3.4, which sets `amendment_required` rather than clearing it. Reports may be read individually or listed, optionally scoped by `obligation_year_id`.

The attest engagement is the year's independent examination. A `ComplianceManager` engages an auditor by naming the `obligation_year_id`, the `auditor_user_id` of the engaged `Auditor`-role operator, and a fieldwork window running from `fieldwork_start` (inclusive) to `fieldwork_end` (exclusive); the end must be strictly later than the start (`ERR_INVALID_REQUEST` otherwise). One auditor may not hold overlapping fieldwork windows: a new engagement whose half-open window overlaps another engagement for the same `auditor_user_id` that has not reached `CLOSED_CLEAN` is rejected with `ERR_ENGAGEMENT_WINDOW_OVERLAP`, while windows that merely touch — one ending exactly as the next begins — are allowed. The engagement opens `ENGAGED`.

From there the auditor drives the examination, and every auditor action requires the caller's `X-User-ID` to equal the engagement's `auditor_user_id`; anyone else is rejected with `ERR_FORBIDDEN`. Beginning fieldwork moves `ENGAGED` → `FIELDWORK`. Issuing findings — a `findings` value of `CLEAN` or `ADVERSE`, any other value rejected with `ERR_INVALID_REQUEST` — moves `FIELDWORK` → `FINDINGS_ISSUED`. Adverse findings open remediation: a `ComplianceManager` moves `FINDINGS_ISSUED` → `REMEDIATION`, admissible only when `findings` stands `ADVERSE` — attempting remediation on clean findings is `ERR_INVALID_STATE`, since the engagement should simply be closed. Remediation loops back into examination: the auditor begins fieldwork again, moving `REMEDIATION` → `FIELDWORK`. Clean findings close the engagement: the auditor moves `FINDINGS_ISSUED` → `CLOSED_CLEAN`, admissible only when `findings` stands `CLEAN` — attempting to close on adverse findings is `ERR_INVALID_STATE`, since remediation must come first. A `CLOSED_CLEAN` engagement is what unlocks submission of the year's annual report. Engagements may be read individually or listed, optionally scoped by `obligation_year_id`.

Finalization is the year's terminal act. From `VOLUME_CLOSED`, a `ComplianceManager` finalizes the year only when an `ANNUAL` report for the year stands `ACCEPTED` and an attest engagement for the year stands `CLOSED_CLEAN`; if either is missing the attempt is rejected with `ERR_YEAR_NOT_FINALIZABLE`. Finalization moves the year `VOLUME_CLOSED` → `FINALIZED`, increments its `version` by one, and seals it — no further retirement batches or reports may be created for the year.

### 3.7. State Low-Carbon Overlay, Market Exposure, and Record Purge

Alongside the federal obligation, a `ComplianceManager` may enroll the account in a state low-carbon program by naming the `account_id`, a two-letter `state_code` that must be unique within the account (`ERR_INVALID_REQUEST` on a duplicate), the `program_type` — `LCFS`, a low-carbon fuel standard style credit program — the state's carbon-intensity standard `ci_standard_gco2e_mj`, and the `default_ci_gco2e_mj` pathway used for provisional crediting. The program's `total_credits_tons` starts at zero. Programs may be read individually or listed, optionally scoped by `account_id`.

Against a program the desk files period credit reports naming the `state_program_id`, a `period_label` unique within the program — a quarter designation such as a year-and-quarter label, with duplicates rejected as `ERR_INVALID_REQUEST` — and the `fuel_gallons` dispensed in the period, a positive quantity. The report opens `PROVISIONAL`, and its `credits_tons` are computed on the default pathway: the difference between the program's carbon-intensity standard and the default CI, multiplied by an energy density of 120.0 megajoules per gallon and by the reported gallons, divided by one million, rounded half-up to four decimal places — a result in metric tons, with negative values permitted as deficits when the pathway CI exceeds the standard. The program's `total_credits_tons` is then re-derived as the sum of its reports' credits, rounded half-up to four decimal places after summing. Later verification re-measures the pathway: a `ComplianceManager` verifies the report with a strictly positive `measured_ci_gco2e_mj` (`ERR_INVALID_REQUEST` otherwise), moving it `PROVISIONAL` → `VERIFIED`, recomputing `credits_tons` with the measured CI in place of the default — the same fuel volume yields different credits whenever the measured and default values differ — re-deriving the program's `total_credits_tons` by the delta between the provisional and verified figures, and stamping `verified_at` from the logical clock. Credit reports may be read individually or listed, optionally scoped by `state_program_id`.

Market visibility comes from price quotes. An `OpsAdmin` records an observed quote with the `account_id`, the `d_code`, the `vintage_year`, the observed `price_cents` per RIN (strictly positive), and a closed effective window from `effective_start` through `effective_end`, both endpoints inclusive — the end may equal the start but never precede it. Windows for the same account, D-code, and vintage must not overlap: because the intervals are closed, two quotes that merely share an endpoint already conflict, and any overlap is rejected with `ERR_PRICE_WINDOW_OVERLAP`. This is what guarantees that at most one covering quote exists for any bucket at any instant. Each quote fixes its `retention_until` at creation per §2.9. Quotes may be read individually or listed, optionally scoped by `account_id`.

Two computed reads consolidate the desk's books. The position read groups all of the account's lots — regardless of status, so that expired and invalidated lots still reconcile — into buckets keyed by D-code and vintage year. Each bucket reports `generated_rins` and `purchased_rins`, the sums of `rin_qty` over lots of each origin; `separated_rins`, `retired_rins`, `invalidated_rins`, `expired_rins`, and `available_rins`, the sums of the corresponding lot counters; and `eligible_rins`, the available balance over lots that pass the retirement eligibility screen of §3.5 with the vintage-year term set aside, since that term is relative to a specific obligation year. Bucket values sum into totals, and the read surfaces `total_available_rins`, `total_retired_rins`, and `total_invalidated_rins` alongside the `buckets`; because per-lot quantities were rounded at generation, this aggregation never re-rounds.

The exposure read marks the position to market. Its buckets are the account's `ACTIVE` lots with positive `available_qty`, again grouped by D-code and vintage year. Each bucket's weighted-average cost is the sum over its lots of available quantity times `unit_cost_cents`, divided by the bucket's total available quantity, rounded half-up to four decimal places. The bucket's market quote is the account's quote for the same D-code and vintage whose closed window covers the current logical clock; if no quote covers the bucket, the bucket is excluded from the exposure total and counted in `unpriced_bucket_count`. Each priced bucket contributes a gain of its total available quantity multiplied by the difference between the quoted price and the weighted-average cost, rounded half-up to a whole cent, and the gains sum into `total_exposure_cents`, reported together with `priced_bucket_count` and `unpriced_bucket_count`.

Finally, retention housekeeping closes the loop: per §2.9 an `OpsAdmin` purges the account's blending records and price quotes whose retention has lapsed, all-or-nothing against any record still within its window, with the purged counts returned as `purged_blending_records` and `purged_price_quotes`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; reads, state transitions, and all other modifications return `200 OK`. Request payloads, response payloads, and side effects are as narrated in §2 and §3 — the table below is a routing summary only, and error responses use the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; applies the vintage-expiry sweep and posture re-derivation | OpsAdmin |
| POST | `/rfs/compliance-accounts` | Register an obligated party | OpsAdmin |
| GET | `/rfs/compliance-accounts/{id}` | Get one account | OpsAdmin, ComplianceManager, Trader, Auditor |
| GET | `/rfs/compliance-accounts/{id}/position` | Computed RIN position by D-code and vintage bucket | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/compliance-accounts/{id}/exposure` | Computed mark-to-market price exposure | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/compliance-accounts/{id}/purge-records` | Purge retention-expired blending records and price quotes | OpsAdmin |
| POST | `/rfs/obligation-years` | Open a compliance year with projected volume and EPA standards | ComplianceManager |
| GET | `/rfs/obligation-years/{id}` | Get one obligation year | OpsAdmin, ComplianceManager, Trader, Auditor |
| GET | `/rfs/obligation-years` | List obligation years, optionally by account | OpsAdmin, ComplianceManager, Trader, Auditor |
| POST | `/rfs/obligation-years/{id}/close-volume` | Record actual volume; compute final RVOs | ComplianceManager |
| POST | `/rfs/obligation-years/{id}/finalize` | Finalize the year once report accepted and attest clean | ComplianceManager |
| POST | `/rfs/vendors` | Onboard a RIN counterparty | Trader |
| GET | `/rfs/vendors/{id}` | Get one vendor | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/vendors` | List vendors, optionally by account | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/vendors/{id}/diligence` | Record a due-diligence outcome; revocation cascades | ComplianceManager |
| POST | `/rfs/rin-lots` | Record renewable fuel production and RIN generation | ComplianceManager |
| GET | `/rfs/rin-lots/{id}` | Get one RIN lot | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/rin-lots` | List RIN lots, optionally by account, vendor, or trade | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/rin-lots/{id}/separations` | Record blending from a generated lot; separates RINs | ComplianceManager |
| GET | `/rfs/blending-records/{id}` | Get one blending record | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/blending-records` | List blending records, optionally by account or lot | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/rin-trades` | Execute a RIN purchase; reserves escrow | Trader |
| GET | `/rfs/rin-trades/{id}` | Get one trade | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/rin-trades` | List trades, optionally by account or vendor | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/rin-trades/{id}/pay` | Pay for a pending trade | Trader |
| POST | `/rfs/rin-trades/{id}/deliver` | Record RIN delivery; mints the purchased lot | Trader |
| POST | `/rfs/rin-trades/{id}/verify` | Verify delivered RINs (segregated; vendor approved; 30-day window) | ComplianceManager |
| POST | `/rfs/rin-trades/{id}/cancel` | Cancel a trade before delivery; escrow released or spend refunded | Trader |
| POST | `/rfs/rin-trades/{id}/invalidate` | Mark delivered or verified RINs as EPA-invalid; cascades | ComplianceManager |
| POST | `/rfs/retirement-batches` | Create a draft retirement batch for a category and D-code | ComplianceManager |
| GET | `/rfs/retirement-batches/{id}` | Get one retirement batch | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/retirement-batches` | List retirement batches, optionally by obligation year | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/retirement-batches/{id}/submit` | Submit to EPA; FIFO allocation, deadline, and carryover cap enforced | ComplianceManager |
| POST | `/rfs/retirement-batches/{id}/decide` | EPA decision: accept debits lots, reject releases allocations | OpsAdmin |
| POST | `/rfs/compliance-reports` | Create a draft report; supersedes the prior same-type draft; OCC on the year | ComplianceManager |
| GET | `/rfs/compliance-reports/{id}` | Get one report | OpsAdmin, ComplianceManager, Trader, Auditor |
| GET | `/rfs/compliance-reports` | List reports, optionally by obligation year | OpsAdmin, ComplianceManager, Trader, Auditor |
| POST | `/rfs/compliance-reports/{id}/submit` | Submit a draft report to EPA; annual requires clean attest | ComplianceManager |
| POST | `/rfs/compliance-reports/{id}/decide` | EPA review decision on a submitted report | OpsAdmin |
| POST | `/rfs/compliance-reports/{id}/reopen` | Revise a rejected report or amend an accepted report back to draft | ComplianceManager |
| POST | `/rfs/attest-engagements` | Engage a third-party auditor for a compliance year | ComplianceManager |
| GET | `/rfs/attest-engagements/{id}` | Get one attest engagement | OpsAdmin, ComplianceManager, Auditor |
| GET | `/rfs/attest-engagements` | List attest engagements, optionally by obligation year | OpsAdmin, ComplianceManager, Auditor |
| POST | `/rfs/attest-engagements/{id}/begin-fieldwork` | Begin fieldwork, or re-examine after remediation | Auditor |
| POST | `/rfs/attest-engagements/{id}/issue-findings` | Issue findings (clean or adverse) | Auditor |
| POST | `/rfs/attest-engagements/{id}/remediate` | Open remediation for adverse findings | ComplianceManager |
| POST | `/rfs/attest-engagements/{id}/close` | Close the engagement; findings must be clean | Auditor |
| POST | `/rfs/state-programs` | Enroll the account in a state low-carbon program | ComplianceManager |
| GET | `/rfs/state-programs/{id}` | Get one state program enrollment | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/state-programs` | List state program enrollments, optionally by account | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/state-credit-reports` | File a period fuel report; provisional credits computed | ComplianceManager |
| GET | `/rfs/state-credit-reports/{id}` | Get one state credit report | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/state-credit-reports` | List state credit reports, optionally by program | OpsAdmin, ComplianceManager, Trader |
| POST | `/rfs/state-credit-reports/{id}/verify` | Verify with measured CI; credits recomputed | ComplianceManager |
| POST | `/rfs/price-quotes` | Record an observed market price for a D-code and vintage | OpsAdmin |
| GET | `/rfs/price-quotes/{id}` | Get one price quote | OpsAdmin, ComplianceManager, Trader |
| GET | `/rfs/price-quotes` | List price quotes, optionally by account | OpsAdmin, ComplianceManager, Trader |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflow that raises it in §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VENDOR_NOT_APPROVED` | 409 |
| `ERR_RIN_INVALIDATED` | 409 |
| `ERR_ATTEST_NOT_CLEAN` | 409 |
| `ERR_D_CODE_NOT_ELIGIBLE` | 409 |
| `ERR_ENGAGEMENT_WINDOW_OVERLAP` | 409 |
| `ERR_PRICE_WINDOW_OVERLAP` | 409 |
| `ERR_INVALID_VINTAGE` | 409 |
| `ERR_DEADLINE_PASSED` | 409 |
| `ERR_VERIFICATION_WINDOW_EXPIRED` | 409 |
| `ERR_RETENTION_ACTIVE` | 409 |
| `ERR_SEPARATION_EXCEEDS_ATTACHED` | 409 |
| `ERR_INSUFFICIENT_RINS` | 409 |
| `ERR_CARRYOVER_CAP_EXCEEDED` | 409 |
| `ERR_YEAR_NOT_FINALIZABLE` | 409 |

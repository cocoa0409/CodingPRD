# Electrical Supply Distributor API — Product Requirements Document

## 1. Introduction

Wholesale electrical distribution runs on credit, copper, and timing. A contractor wiring a hospital or a data center may hold a quote for months while commodity prices move, draw material against a job account in dozens of partial releases, and expect the distributor to handle the messy mechanics in between: cut charges on cable reels, minimum cut lengths, backorders when the warehouse comes up short, lien waivers before credit is extended, and manufacturer rebate programs whose true value is only known after the buying period closes. Each of these concerns touches the others — a rebate claim depends on invoiced amounts, a single invoice can push a contractor over their credit limit and freeze every open job they hold, and one stock receipt must decide which waiting release gets fed first.

This document specifies an API for an electrical supply distributor that manages that entire cycle. The system covers contractor onboarding and credit accounting, catalog maintenance for both each-count and by-the-foot material, project quoting with bill-of-material takeoff and substitution approval, job-account releases flowing through credit approval, stock allocation, delivery scheduling, and invoicing, and manufacturer rebate programs with provisional accrual and final settlement. Two billing variants are supported — firm pricing that pins the negotiated quote price, and escalation pricing that floats with a published commodity index — and all time-dependent behavior is driven by a controllable logical clock rather than wall-clock time, so that expiry, escalation months, and rebate windows are fully deterministic for operators and integrators alike.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying their operational capacity. A request missing either header, presenting either header with an empty or all-whitespace value, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). Seven roles are recognized: `SalesRep`, `BranchManager`, `CreditManager`, `WarehouseManager`, `Dispatcher`, `RebateClerk`, and `Contractor`. Access to each operation is restricted by role as enumerated in §4; an authenticated caller attempting an operation outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403).

For six of the seven roles — `SalesRep`, `BranchManager`, `CreditManager`, `WarehouseManager`, `Dispatcher`, and `RebateClerk` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any entity's `id`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting Contractor, and ownership checks apply: a `Contractor` caller may act only on job accounts whose `contractor_id` equals their `X-User-ID` — most materially when requesting or cancelling a release — and any attempt to act against another contractor's account is rejected with `ERR_FORBIDDEN`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random uppercase-alphanumeric characters.
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

List endpoints accept `limit` and `offset` query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an empty parameter value is treated as absent and yields the default.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Wherever `created_at` values tie — in list responses or in internal orderings such as allocation line processing and the backorder waterfall — the earlier-inserted record comes first; identifier comparisons are never used for ordering.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full size of the filtered result set and `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in the system — Contractor, CatalogItem, JobAccount, Quote, QuoteLine, SubstitutionRequest, Release, ReleaseLine, BackorderAllocation, RebateProgram, and RebateClaim — carries a standard set of system-managed fields:

- `id`: a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource.
- `version`: an integer that starts at 1 when the resource is created and increments by 1 on every mutation — including derived-field reconciliation performed as a side effect of an operation on a different resource, such as a balance update on a Contractor triggered by a release transition. Several changes applied to the same record within a single request count as one mutation: `version` increments at most once per record per request.

### 2.5. The Logical Clock and Commodity Index Readings

All date- and month-sensitive behavior in the system — quote expiry, delivery-window validation, escalation billing, rebate qualification windows, and credit-hold evaluation — reads from a **logical clock**, never from wall-clock time. At startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `BranchManager`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`.

A second `BranchManager`-only capability publishes commodity index readings. Each reading pairs a `month` — a year-month string such as `2026-08`, with a malformed `month` rejected as `ERR_INVALID_REQUEST` — with an `index_value`. The month is unique across readings: publishing a reading for a month that already has one replaces the stored value. The response reports the stored `month` and `index_value`. These readings feed escalation pricing (§3.3), which always looks up the latest reading whose month is on or before the relevant billing month.

### 2.6. The Contractor Credit Ledger

Each contractor's credit exposure is tracked through three derived balances, all integer cents. `invoiced_balance_cents` is the sum of `billed_total_cents` over the contractor's `INVOICED` releases minus the sum of recorded payments. `committed_balance_cents` is the sum of `estimated_total_cents` over the contractor's releases currently in `CREDIT_APPROVED`, `PARTIALLY_ALLOCATED`, `ALLOCATED`, `SCHEDULED`, or `DELIVERED` status. `credit_used_cents` is read-only and always equals the sum of the other two. All three balances start at zero when the contractor is created.

Balance mutations are immediate and atomic with the operations that cause them: credit approval commits a release's estimate, invoicing releases the commitment and posts the billed amount, cancellation releases the commitment, and a recorded payment reduces the invoiced balance. No operation may leave a balance partially updated.

### 2.7. Pricing Precision and Rounding

Unit prices — `list_price_cents` on catalog items and `unit_price_cents` on quote lines — are expressed in cents with up to four decimal places; supplied prices are stored exactly as given, with no decimal-place rejection. The effective unit price produced by the escalation calculation is rounded half-up to exactly four decimal places. All line-level amounts and stored totals are integer cents, produced with round-half-up rounding; where an amount is built from several lines, each line is rounded first and the rounded per-line results are then summed. This per-line-then-sum order is pinned for release billing (§3.8) and for final rebate computation (§3.9). The single exception is the provisional rebate estimate, which applies exactly one rounding to the total rather than per line (§3.9). In responses, fractional quantities and prices serialize as JSON numbers, dropping any fractional part when the value is integral.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency guard, and each names its own version field:

- Revising a quote requires the request to carry `expected_quote_version`, holding the quote's `version` as last observed by the client. If it does not match the quote's current `version` — because another writer has advanced it since the client last read it — the revise is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412), preventing the client from silently superseding a revision it never saw.
- Creating a release requires the request to carry `expected_job_account_version`, holding the target job account's `version` as last observed. A mismatch with the account's current `version` is rejected with `ERR_STALE_JOB_ACCOUNT_VERSION` (HTTP 412).

Endpoints not named above do not accept a version field of any kind.

### 2.9. Request Shape and Resource Existence

Every write request is first checked for structural validity: required fields must be present, enum fields must name a declared member, quantities such as `qty` must be greater than zero, a delivery window's `window_end_hour` must be strictly later than its `window_start_hour`, and the reel fields `reel_length_ft`, `min_cut_ft`, and `cut_charge_cents` must be present when the item's `sell_uom` is `FOOT` and absent when it is `EA`. Structural violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

After shape validation, every path identifier and every body foreign key is checked for existence, validated left to right; the first missing reference produces the corresponding 404 — `ERR_CONTRACTOR_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_JOB_ACCOUNT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_SUBSTITUTION_REQUEST_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_REBATE_PROGRAM_NOT_FOUND`, or `ERR_REBATE_CLAIM_NOT_FOUND`, according to which reference failed first. Release-line and backorder-allocation detail reads have no error identifier of their own: an unknown release-line or backorder-allocation id surfaces `ERR_RELEASE_NOT_FOUND`.

### 2.10. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic:

1. Authentication context — the headers of §2.1.
2. Role authorization (§2.1).
3. Request shape (§2.9).
4. Existence of path identifiers and body foreign keys, left to right (§2.9); contractor-ownership checks (§2.1) then apply against the loaded resource — ownership cannot be evaluated before the owning account is known, so a missing reference surfaces its 404 before any `ERR_FORBIDDEN` ownership failure.
5. Optimistic-concurrency version checks (§2.8).
6. Target-state preconditions — the `ERR_..._NOT_...` family, including `ERR_JOB_NOT_OPEN` and `ERR_JOB_ON_CREDIT_HOLD`.
7. Clock-relative temporal rules — quote validity against `valid_until`, delivery windows not in the past, and the rebate period having ended.
8. Lien-waiver linkage on credit approval.
9. Domain constraints — SKU uniqueness, the min-cut floor, item-on-quote membership, truck-window overlap, the jobsite day bucket, rebate-period overlap, closing with open children, and submitting an empty quote.
10. The credit-headroom check, evaluated last.

The ordering has observable consequences. Revising a quote with a stale `expected_quote_version` surfaces `ERR_STALE_QUOTE_VERSION` even if the quote is also in the wrong state for revision. Credit-approving a release whose job sits on credit hold surfaces `ERR_JOB_ON_CREDIT_HOLD` long before `ERR_CREDIT_LIMIT_EXCEEDED` would ever be considered. And a release request naming a nonexistent catalog item fails as `ERR_CATALOG_ITEM_NOT_FOUND` before any membership or min-cut reasoning begins.

## 3. Business Logic & Workflows

### 3.1. Contractor Onboarding and the Payment Cycle

A `CreditManager` onboards a **Contractor** by supplying the company `name` and a `credit_limit_cents` — the maximum allowed credit exposure in integer cents, which must be greater than zero. The new contractor's `invoiced_balance_cents` and `committed_balance_cents` start at zero, its `credit_used_cents` therefore reads zero, and its `version` starts at 1. Contractor list and detail reads are available to every role.

When a contractor pays down their account, a `CreditManager` records a payment carrying `amount_cents`, which must be a positive integer. The payment amount is subtracted from `invoiced_balance_cents`, and the contractor's `version` increments by 1. No payment resource is persisted: the response carries the updated Contractor. If the posting brings `invoiced_balance_cents` back to at or below `credit_limit_cents`, every `CREDIT_HOLD` job account belonging to that contractor automatically returns to `OPEN` — the mirror image of the credit contagion described in §3.8. The `credit_used_cents` figure reported on the contractor always reflects the sum of the invoiced and committed balances after such adjustments settle.

### 3.2. Catalog Maintenance and Stock Receipts

A `WarehouseManager` maintains the catalog. Creating a **CatalogItem** requires a `sku` — unique across all catalog items, with duplicates rejected as `ERR_DUPLICATE_SKU` — a `manufacturer_name`, a `sell_uom` of `EA` or `FOOT`, and a `list_price_cents` carrying up to four decimal places; the list price must be non-negative. Items sold by the foot additionally require `reel_length_ft` (the full reel length in feet) and `min_cut_ft` (the smallest cut the warehouse will sell), both positive integers, and `cut_charge_cents` (a flat charge applied at billing when a line ships less than a full reel), a non-negative integer; for `EA` items all three reel fields must be absent — an explicit null counts as absent — and either mismatch is a request-shape error under §2.9. New items start with `stock_on_hand` and `stock_allocated` at zero. The catalog list can be narrowed with the `manufacturer_name` filter, alongside `limit` and `offset`.

The `manufacturer_name` is more than display text: rebate qualification keys on an exact string match between the item's manufacturer and the program's (§3.9), so spelling discipline at item creation directly determines later claim value.

Stock arrives through a `WarehouseManager` receipt carrying a `qty` greater than zero. The receipt adds the quantity to `stock_on_hand`, increments the item's `version` by 1, and immediately triggers the backorder waterfall of §3.7, which may push waiting releases forward before the response returns. `stock_on_hand` is the unallocated physical stock — a count for `EA` items, feet for `FOOT` items — while `stock_allocated` tracks stock reserved by lines on releases in `PARTIALLY_ALLOCATED`, `ALLOCATED`, or `SCHEDULED` status.

### 3.3. Job Accounts, Pricing Modes, and Lien Waivers

A `SalesRep` opens a **JobAccount** for a contractor by providing the `contractor_id`, a `job_name`, the `jobsite_address`, and a `pricing_mode` of `FIRM_PRICE` or `ESCALATION`; the account begins in `OPEN` status. The pricing mode governs how every release on the job is eventually billed. `FIRM_PRICE` bills at the award-pinned quote price and ignores commodity-index movement entirely. `ESCALATION` scales the quote price by the ratio of the commodity index at billing time to the index pinned at award: the base index is the quote's `award_index_value`, and the current index is the latest published reading whose `month` is on or before the year-month of the logical clock at billing time. If no reading exists at or before the billing month, the current index falls back to the base index, producing a ratio of exactly 1; if the base index itself is null — no reading existed at or before the award month — the ratio is likewise exactly 1, and the quote price stands unchanged.

An optional `escalation_cap_pct`, expressed as a fraction, clamps the escalation ratio to at most one plus that fraction: a cap of 0.10 limits the ratio to 1.10 no matter how far the index has run. The cap defaults to null, meaning uncapped; when supplied it must be a non-negative number, and it is forbidden on `FIRM_PRICE` jobs — though an explicit null counts as absent and is accepted on either mode. Separately, `lien_waiver_required` defaults to false and may be set at account opening.

When a job requires one, a `CreditManager` files a lien waiver by supplying `expires_on`. The filing sets the account's `lien_waiver_expires_on` — null until the first filing — replacing any prior expiry date, and increments the account's `version` by 1; filing is not gated on the account's status and succeeds on `OPEN`, `CREDIT_HOLD`, or `CLOSED` accounts alike. A waiver is current only while its expiry falls on or after the logical clock's date; an expired waiver is no waiver at all for the purposes of §3.6.

A `BranchManager` may close an `OPEN` account. Closure is refused with `ERR_JOB_HAS_OPEN_RELEASES` while any quote on the account is still `DRAFT` or `SUBMITTED`, or any release is still `REQUESTED`, `CREDIT_APPROVED`, `PARTIALLY_ALLOCATED`, `ALLOCATED`, `SCHEDULED`, or `DELIVERED`. The close guard reads each quote's stored status: closing an account does not itself apply lazy expiry (§3.4), so a quote lingering in `DRAFT` or `SUBMITTED` blocks closure even when its `valid_until` has passed, until some quote read or transition expires it first. Attempting to close an account that is not `OPEN` at all is refused with `ERR_JOB_NOT_OPEN`. A `CLOSED` account is terminal. The account list supports `contractor_id` and `status` filters alongside `limit` and `offset`.

### 3.4. Quoting: Takeoff, Submission, Revision, and Award

Quoting begins when a `SalesRep` creates a **Quote** against a job account, supplying the `job_account_id` and a `valid_until` date. Creation is not gated on the account's status — a quote may be opened against an `OPEN`, `CREDIT_HOLD`, or `CLOSED` account alike. The quote starts in `DRAFT` with `revision_no` set to 1 and with `award_month` and `award_index_value` still null.

While the quote is `DRAFT`, the `SalesRep` builds the bill of materials one **QuoteLine** at a time, each line naming the `quote_id`, the `catalog_item_id`, a `qty` greater than zero expressed in the item's sell unit, and a negotiated `unit_price_cents` of up to four decimal places; the unit price must be non-negative. Adding a line to a quote that is not `DRAFT` is rejected with `ERR_QUOTE_NOT_DRAFT`, and for a `FOOT` item a `qty` below the item's `min_cut_ft` is rejected with `ERR_BELOW_MIN_CUT`. Quote lines can be listed with `quote_id` or `catalog_item_id` filters.

Submitting the quote — a `SalesRep` action moving `DRAFT` → `SUBMITTED` — enforces three checks, evaluated in the §2.10 order: the job account must be `OPEN` (`ERR_JOB_NOT_OPEN`); the logical clock's date must not have passed `valid_until` — if it has, the attempt is rejected with `ERR_QUOTE_EXPIRED` and the quote transitions to `EXPIRED`; and the quote must carry at least one line (`ERR_QUOTE_HAS_NO_LINES`). The quote's own state precondition comes before all three: a quote that is not `DRAFT` fails with `ERR_QUOTE_NOT_DRAFT` before any job-account, expiry, or line reasoning begins. Expiry is lazy across the board: any read or transition attempt against a `DRAFT` or `SUBMITTED` quote whose `valid_until` has passed moves it to `EXPIRED`, which is terminal. Reads and transitions of the quote itself include the quote detail read, the quote list (which expires every quote), revise, submit, and award; operations on child resources — adding a quote line or proposing or deciding a substitution — do not apply lazy expiry and instead evaluate the `DRAFT` guard against the quote's stored status.

A submitted quote can be sent back for rework. Revising moves `SUBMITTED` → `DRAFT`, increments `revision_no` by 1, and increments the quote's `version` by 1 — each revision supersedes the prior one, which is exactly why the revise call is guarded by `expected_quote_version` per §2.8. A quote that is not currently `SUBMITTED` cannot be revised or awarded; such attempts fail with `ERR_QUOTE_NOT_SUBMITTED`.

Award is the `BranchManager`'s decision, moving `SUBMITTED` → `AWARDED`. Awarding enforces the same job-`OPEN` and not-expired guards as submission (`ERR_JOB_NOT_OPEN` and `ERR_QUOTE_EXPIRED` respectively), with the quote's own state precondition (`ERR_QUOTE_NOT_SUBMITTED`) again evaluated first, and on success it pins the escalation baseline: `award_month` records the logical clock's year-month, and `award_index_value` records the value of the latest index reading whose month is on or before the award month — null if no such reading exists yet. Both `AWARDED` and `EXPIRED` are terminal. The quote list supports `job_account_id` and `status` filters.

### 3.5. Substitution Requests

When a specified item needs to be swapped — a discontinued part, an owner-approved equivalent — the `SalesRep` proposes a **SubstitutionRequest** naming the `quote_line_id` under revision, the `proposed_item_id`, and a free-text `reason`. The proposal starts in `PROPOSED` and is only accepted while the owning quote — reached by following the quote line back to its quote — is still `DRAFT`; otherwise the proposal is rejected with `ERR_QUOTE_NOT_DRAFT`.

A `BranchManager` decides each proposal by supplying a `decision` of `APPROVE` or `REJECT`. Approval moves the request to `APPROVED` and rewrites the quote line's `catalog_item_id` to the proposed item, so downstream release membership checks and billing follow the substitute. Rejection moves the request to `REJECTED` with no further effect. Both outcomes are terminal, and deciding a request that has left `PROPOSED` is rejected with `ERR_SUBSTITUTION_NOT_PROPOSED`; the same `DRAFT`-only guard on the owning quote applies at decision time as well. The request list supports `quote_line_id`, `proposed_item_id`, and `status` filters.

### 3.6. Release Creation and Credit Approval

A **Release** draws material against an awarded quote. Either a `SalesRep` or the owning `Contractor` may create one; a `Contractor` caller whose `X-User-ID` does not match the job account's `contractor_id` is refused with `ERR_FORBIDDEN`. The request names the `job_account_id`, the `quote_id`, the optimistic-concurrency field `expected_job_account_version` (§2.8), and a `lines` array whose entries each pair a `catalog_item_id` with a `qty`; the array must be non-empty. Following the §2.10 precedence, creation checks request shape first — every `qty` greater than zero — then the existence of the referenced account, quote, and items, then the account version check (`ERR_STALE_JOB_ACCOUNT_VERSION`), then the state precondition that the job account is `OPEN` (`ERR_JOB_NOT_OPEN`), and finally the domain constraints: the quote must be an `AWARDED` quote belonging to the same job account (violated as `ERR_INVALID_REQUEST`, HTTP 400), every line's item must appear on that quote (`ERR_ITEM_NOT_ON_QUOTE`), and every `FOOT` line's `qty` must be at least the item's `min_cut_ft` (`ERR_BELOW_MIN_CUT`).

On success the release starts in `REQUESTED`. Its **ReleaseLine** rows are created from the `lines` array with `qty_allocated` at zero, `qty_shipped` at zero, `billed_amount_cents` null, and status `OPEN`. An `estimated_total_cents` is computed as a provisional extension — the billing formula of §3.8 evaluated with each line's `qty_requested` as the billed quantity and the logical clock as it stands at creation. Creating the release also increments the job account's `version` by 1, which is precisely what a second writer's `expected_job_account_version` is measured against. The release's `billed_total_cents`, `truck_id`, `delivery_date`, `window_start_hour`, `window_end_hour`, and `invoiced_on` are all null at this stage.

Credit approval is the `CreditManager`'s gate, moving `REQUESTED` → `CREDIT_APPROVED`; a release in any other state yields `ERR_RELEASE_NOT_REQUESTED`. Beyond the state check, approval enforces three further gates in the §2.10 order. The job account must be `OPEN` — any other account status, whether `CREDIT_HOLD` or `CLOSED`, surfaces `ERR_JOB_ON_CREDIT_HOLD`. When the job's `lien_waiver_required` is true, a current lien waiver must be on file — `lien_waiver_expires_on` set and falling on or after the logical clock's date — else `ERR_LIEN_WAIVER_REQUIRED`. Last comes the credit-headroom check: the release's `estimated_total_cents` must not exceed the contractor's `credit_limit_cents` minus `invoiced_balance_cents` minus `committed_balance_cents`; an estimate exactly equal to the remaining headroom passes, and only a strictly greater estimate is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Approval commits the estimate: the contractor's `committed_balance_cents` increases by the release's `estimated_total_cents`.

A release can be cancelled by a `SalesRep` or by the owning `Contractor` — the same ownership rule as creation — from `REQUESTED`, `CREDIT_APPROVED`, `PARTIALLY_ALLOCATED`, or `ALLOCATED`; from any later state the attempt fails with `ERR_RELEASE_NOT_CANCELLABLE`. Cancellation always moves the release to `CANCELLED`, and the unwind depends on how far the release had progressed. From `REQUESTED` there is nothing to unwind. From `CREDIT_APPROVED` the committed estimate is released: the contractor's `committed_balance_cents` decreases by `estimated_total_cents`. In these two cases the release's lines are left untouched — they remain `OPEN`; only cancellation from `PARTIALLY_ALLOCATED` or `ALLOCATED` touches lines and stock: each line returns its `qty_allocated` to the item's `stock_on_hand`, the item's `stock_allocated` decreases by the same amount, each line — whether still `OPEN` or already `ALLOCATED` — transitions to `CANCELLED`, any `OPEN` backorder allocations of the release move to `CANCELLED`, and the committed estimate is released as above. The release list supports `job_account_id`, `quote_id`, and `status` filters alongside `limit` and `offset`.

### 3.7. Stock Allocation and the Backorder Waterfall

Once credit-approved, a `WarehouseManager` allocates the release against physical stock; attempting allocation from any other state yields `ERR_RELEASE_NOT_CREDIT_APPROVED`. Lines are processed in line `created_at` ascending order: each line's `qty_allocated` becomes the smaller of its `qty_requested` and the item's current `stock_on_hand`, with the allocated quantity moved out of `stock_on_hand` and into `stock_allocated`. When every line is fully covered, each line transitions `OPEN` → `ALLOCATED` and the release becomes `ALLOCATED`. When any line comes up short, the release becomes `PARTIALLY_ALLOCATED`: fully covered lines still transition to `ALLOCATED`, each short line remains `OPEN`, and the system creates an `OPEN` **BackorderAllocation** for every short line, recording its `release_line_id`, the line's `catalog_item_id` denormalized onto the backorder for the waterfall, and a `qty_open` equal to the unfilled remainder — the requested quantity minus what was allocated.

The backorder waterfall runs on every stock receipt (§3.2). After the received quantity lands in `stock_on_hand`, the system visits each `OPEN` BackorderAllocation for that item whose owning release is `PARTIALLY_ALLOCATED`, ordered by the owning release's `created_at` ascending and, within a release, by the release line's `created_at` ascending — never by identifier. Each candidate is filled with the smaller of its `qty_open` and the item's remaining `stock_on_hand`: the fill quantity is subtracted from the candidate's `qty_open`, added to the line's `qty_allocated`, subtracted from `stock_on_hand`, and added to `stock_allocated`. A candidate whose `qty_open` reaches zero transitions to `FILLED`. A line whose `qty_allocated` reaches its `qty_requested` transitions `OPEN` → `ALLOCATED`. And when a release's last open backorder is filled so that every line is allocated, the release itself advances `PARTIALLY_ALLOCATED` → `ALLOCATED`. Filling continues down the order until the candidates are exhausted or no stock remains. Backorder allocations also move to `CANCELLED` when their owning release is cancelled, per §3.6. The backorder list supports `release_line_id`, `catalog_item_id`, and `status` filters; release lines likewise filter by `release_id`, `catalog_item_id`, and `status`.

### 3.8. Delivery Scheduling, Delivery, and Invoicing

An `ALLOCATED` release is handed to a `Dispatcher` for scheduling; from any other state the attempt yields `ERR_RELEASE_NOT_ALLOCATED`. The schedule call carries a `truck_id`, a `delivery_date`, and a half-open delivery window from `window_start_hour` (an hour from 0 to 23) to `window_end_hour` (exclusive; an hour from 1 to 24, with 24 meaning the end of the day). Three guards apply. The `delivery_date` must not fall before the logical clock's current date, else `ERR_DELIVERY_WINDOW_PAST`. The truck must be free: no other release with the same `truck_id` and the same `delivery_date` in `SCHEDULED` or `DELIVERED` status may hold a window overlapping the new one — under the half-open convention a new window does not conflict if it ends at or before an existing window's start, or begins at or after the existing window's end; any tighter interleaving is rejected with `ERR_TRUCK_WINDOW_OVERLAP`. And the jobsite must not already be receiving a delivery that day: no other release on the same job account may hold a `SCHEDULED` or `DELIVERED` delivery on that date, else `ERR_JOBSITE_DAY_CONFLICT`. Scheduling stamps `truck_id`, `delivery_date`, `window_start_hour`, and `window_end_hour` onto the release and moves it to `SCHEDULED`.

When the truck returns, the `Dispatcher` confirms delivery; a release that is not `SCHEDULED` yields `ERR_RELEASE_NOT_SCHEDULED`. Each line's `qty_shipped` is set to its `qty_allocated`, the line transitions `ALLOCATED` → `SHIPPED`, and each item's `stock_allocated` is relieved by the shipped quantity. The release becomes `DELIVERED`.

Invoicing is a `CreditManager` action on a `DELIVERED` release — from any other state, `ERR_RELEASE_NOT_DELIVERED` — and it performs the final billing. Each line's base unit price is the `unit_price_cents` negotiated on the quote line of the release's quote for that line's item — the earliest-created such quote line when the quote carries the item more than once. The effective unit price follows the job's pricing mode per §3.3: `FIRM_PRICE` bills at that pinned price, while `ESCALATION` scales the base price by the capped index ratio taken at the logical clock's year-month at invoice time, with the resulting unit price rounded half-up to four decimal places. The line extension then uses `qty_shipped` as the billed quantity: for an `EA` item, the line's `billed_amount_cents` is the shipped quantity multiplied by the effective unit price, rounded half-up to a whole cent; for a `FOOT` item the same rounded product is taken and, when the shipped quantity is less than the item's `reel_length_ft`, the flat `cut_charge_cents` is added on top — a full reel or more escapes the cut charge. The release's `billed_total_cents` is the sum of the per-line amounts, each line transitions `SHIPPED` → `INVOICED`, and `invoiced_on` records the logical clock's date — the key later used for rebate qualification windows.

Invoicing also settles the credit ledger. The contractor's `committed_balance_cents` decreases by the release's `estimated_total_cents`, and `invoiced_balance_cents` increases by `billed_total_cents`. Should that posting push `invoiced_balance_cents` above the contractor's `credit_limit_cents`, credit contagion follows: every `OPEN` job account of that contractor transitions to `CREDIT_HOLD`, blocking further credit approvals and quote activity until payments bring the balance back within the limit (§3.1).

### 3.9. Manufacturer Rebates and Claim Settlement

A `RebateClerk` configures a **RebateProgram** by naming the `manufacturer_name` whose purchases qualify, a closed period running from `period_start` through `period_end` — both dates inclusive, with `period_end` required to fall on or after `period_start` (a violation is a request-shape error under §2.9) — and a `tiers` array. Each tier pairs a `threshold_cents`, a non-negative integer, with a `rebate_pct`, a non-negative number; the array itself may be empty, in which case the achieved percentage is always zero. Tiers are kept in ascending threshold order; the achieved tier for a given qualifying base is the last tier whose `threshold_cents` does not exceed that base, and if no threshold is reached the applied percentage is zero. Two programs for the same manufacturer may not have overlapping closed intervals — shared boundary dates count as a conflict — and such a creation is rejected with `ERR_REBATE_PERIOD_OVERLAP`.

Against a program, the `RebateClerk` opens a **RebateClaim** by supplying the `rebate_program_id`. The claim starts in `DRAFT`, and creation immediately accrues a provisional estimate into `provisional_amount_cents`. The qualifying base is the sum of `billed_amount_cents` over all release lines whose release is `INVOICED` with an `invoiced_on` date inside the program's closed period — both bounds inclusive — and whose catalog item's `manufacturer_name` exactly equals the program's. The provisional amount applies the achieved percentage to that base with exactly one rounding, half-up to a whole cent, taken on the sum as a whole. At this stage `qualifying_base_cents`, `tier_pct_applied`, and `final_amount_cents` remain null.

Submitting the claim is allowed only once the logical clock's date has passed the program's `period_end` — earlier attempts fail with `ERR_REBATE_PERIOD_NOT_ENDED` — and only from `DRAFT`, else `ERR_REBATE_CLAIM_NOT_DRAFT`. Submission recomputes everything against the data as it then stands: `qualifying_base_cents` is recalculated, `tier_pct_applied` records the achieved percentage, and `final_amount_cents` is computed by the final variant — each qualifying line's `billed_amount_cents` is multiplied by the achieved percentage and rounded half-up to a whole cent, and those per-line results are then summed. Because the final variant rounds per line while the provisional variant rounded the sum exactly once, the two figures can legitimately differ for identical underlying data. The claim moves to `SUBMITTED`.

A `BranchManager` then decides the claim by supplying a `decision` of `APPROVE` or `REJECT`, moving it to `APPROVED` or `REJECTED`; deciding a claim that is not `SUBMITTED` fails with `ERR_REBATE_CLAIM_NOT_SUBMITTED`. Both outcomes are terminal. The program list filters by `manufacturer_name`, and the claim list by `rebate_program_id` and `status`, each alongside `limit` and `offset`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/distributor` prefix. Operations that create a new resource — a contractor, an item, an account, a quote, a line, a request, a release, a payment, a receipt, a waiver filing, a program, or a claim — return `201 Created`. Operations that modify an existing resource, including all state transitions, return `200 OK`. Successful writes return the affected resource in the envelope's `data` field. The two test-driving operations of §2.5 manage no envelope resource: both return `200 OK` with a small acknowledgement object — the clock setter reports `current_utc`, and the reading setter reports the stored `month` and `index_value`. The table below summarizes the routing contract only; request payloads, validation triggers, and side effects are specified by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/distributor/contractors` | Create a contractor with a credit limit | CreditManager |
| GET | `/distributor/contractors` | List contractors | All roles |
| GET | `/distributor/contractors/{id}` | Get a contractor | All roles |
| POST | `/distributor/contractors/{id}/payments` | Record a payment against the invoiced balance | CreditManager |
| POST | `/distributor/catalog-items` | Create a catalog item (EA or FOOT) | WarehouseManager |
| GET | `/distributor/catalog-items` | List catalog items | All roles |
| GET | `/distributor/catalog-items/{id}` | Get a catalog item | All roles |
| POST | `/distributor/catalog-items/{id}/stock-receipts` | Receive stock and run the backorder waterfall | WarehouseManager |
| POST | `/distributor/job-accounts` | Open a job account for a contractor | SalesRep |
| GET | `/distributor/job-accounts` | List job accounts | All roles |
| GET | `/distributor/job-accounts/{id}` | Get a job account | All roles |
| POST | `/distributor/job-accounts/{id}/close` | Close a job account (guarded by open children) | BranchManager |
| POST | `/distributor/job-accounts/{id}/lien-waivers` | File a lien waiver on the job account | CreditManager |
| POST | `/distributor/quotes` | Create a DRAFT quote for a job account | SalesRep |
| GET | `/distributor/quotes` | List quotes | All roles |
| GET | `/distributor/quotes/{id}` | Get a quote (lazy expiry applies) | All roles |
| POST | `/distributor/quotes/{id}/submit` | Submit a DRAFT quote | SalesRep |
| POST | `/distributor/quotes/{id}/revise` | Return a SUBMITTED quote to DRAFT as a new revision (OCC-guarded) | SalesRep |
| POST | `/distributor/quotes/{id}/award` | Award a SUBMITTED quote; pins award_month and award_index_value | BranchManager |
| POST | `/distributor/quote-lines` | Add a BOM line to a DRAFT quote | SalesRep |
| GET | `/distributor/quote-lines` | List quote lines | All roles |
| GET | `/distributor/quote-lines/{id}` | Get a quote line | All roles |
| POST | `/distributor/substitution-requests` | Propose a substitute item for a quote line | SalesRep |
| GET | `/distributor/substitution-requests` | List substitution requests | All roles |
| GET | `/distributor/substitution-requests/{id}` | Get a substitution request | All roles |
| POST | `/distributor/substitution-requests/{id}/decide` | Approve or reject a proposed substitution | BranchManager |
| POST | `/distributor/releases` | Create a release against an awarded quote (OCC-guarded on the job account) | SalesRep, Contractor |
| GET | `/distributor/releases` | List releases | All roles |
| GET | `/distributor/releases/{id}` | Get a release | All roles |
| POST | `/distributor/releases/{id}/credit-approve` | Credit-approve a REQUESTED release (lien waiver + headroom checks) | CreditManager |
| POST | `/distributor/releases/{id}/allocate` | Allocate stock to a CREDIT_APPROVED release | WarehouseManager |
| POST | `/distributor/releases/{id}/schedule` | Schedule jobsite delivery for an ALLOCATED release | Dispatcher |
| POST | `/distributor/releases/{id}/deliver` | Mark a SCHEDULED release delivered | Dispatcher |
| POST | `/distributor/releases/{id}/invoice` | Invoice a DELIVERED release (final billing; credit contagion cascade) | CreditManager |
| POST | `/distributor/releases/{id}/cancel` | Cancel a release before scheduling | SalesRep, Contractor |
| GET | `/distributor/release-lines` | List release lines | All roles |
| GET | `/distributor/release-lines/{id}` | Get a release line | All roles |
| GET | `/distributor/backorder-allocations` | List backorder allocations | All roles |
| GET | `/distributor/backorder-allocations/{id}` | Get a backorder allocation | All roles |
| POST | `/distributor/rebate-programs` | Create a manufacturer rebate program | RebateClerk |
| GET | `/distributor/rebate-programs` | List rebate programs | All roles |
| GET | `/distributor/rebate-programs/{id}` | Get a rebate program | All roles |
| POST | `/distributor/rebate-claims` | Open a rebate claim (provisional accrual computed at creation) | RebateClerk |
| GET | `/distributor/rebate-claims` | List rebate claims | All roles |
| GET | `/distributor/rebate-claims/{id}` | Get a rebate claim | All roles |
| POST | `/distributor/rebate-claims/{id}/submit` | Submit a DRAFT claim after the program period ends | RebateClerk |
| POST | `/distributor/rebate-claims/{id}/decide` | Approve or reject a SUBMITTED claim | BranchManager |
| POST | `/distributor/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | BranchManager |
| POST | `/distributor/_index-readings/set` | Publish a commodity index reading for a month (upsert) | BranchManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_CATALOG_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSTITUTION_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_RELEASE_NOT_FOUND` | 404 Not Found |
| `ERR_REBATE_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_REBATE_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_QUOTE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_JOB_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_QUOTE_NOT_DRAFT` | 409 Conflict |
| `ERR_QUOTE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_QUOTE_HAS_NO_LINES` | 409 Conflict |
| `ERR_SUBSTITUTION_NOT_PROPOSED` | 409 Conflict |
| `ERR_JOB_NOT_OPEN` | 409 Conflict |
| `ERR_JOB_ON_CREDIT_HOLD` | 409 Conflict |
| `ERR_JOB_HAS_OPEN_RELEASES` | 409 Conflict |
| `ERR_RELEASE_NOT_REQUESTED` | 409 Conflict |
| `ERR_RELEASE_NOT_CREDIT_APPROVED` | 409 Conflict |
| `ERR_RELEASE_NOT_ALLOCATED` | 409 Conflict |
| `ERR_RELEASE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_RELEASE_NOT_DELIVERED` | 409 Conflict |
| `ERR_RELEASE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_REBATE_CLAIM_NOT_DRAFT` | 409 Conflict |
| `ERR_REBATE_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_REBATE_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_REBATE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_LIEN_WAIVER_REQUIRED` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_PAST` | 409 Conflict |
| `ERR_TRUCK_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_JOBSITE_DAY_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_BELOW_MIN_CUT` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_ON_QUOTE` | 422 Unprocessable Entity |

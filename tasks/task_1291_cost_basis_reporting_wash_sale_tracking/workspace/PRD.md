# Cost Basis Reporting & Wash Sale Tracking API — Product Requirements Document

## 1. Introduction

Broker-dealers live under an unforgiving reporting obligation: every sale of a security must be matched against the correct acquisition lots, every loss must be screened for wash-sale disallowance across the taxpayer's entire relationship with the firm, and every January the firm must be able to stand behind a Form 1099-B that reconciles to the penny. This document specifies the API for the bookkeeping core of a brokerage tax reporting group. The system tracks each acquisition lot from booking through disposal, governs which lots a sale consumes under the account's chosen disposal method, adjusts basis when corporate actions reshape a position, carries basis detail across firms on transfer statements, detects wash sales across every account a taxpayer holds, and produces the annual 1099-B together with its statute-bounded correction cycle.

The regulatory substrate is deliberately explicit. Covered versus noncovered classification follows the IRC 6045 phase-in; gifted and inherited positions follow the dual-basis and stepped-up-basis rules of IRC 1015 and 1014; wash-sale deferral follows the thirty-day replacement window of IRC 1091, including the trap in which a replacement purchase inside an IRA permanently forfeits a taxable loss. Because basis corrections are audit-sensitive, the API separates the power to approve a change from the power to apply it, guards its most dangerous writes with optimistic concurrency tokens, and evaluates every statutory deadline against a controllable logical clock rather than wall-clock time. The API is mounted under `/firms`, and every resource lives inside exactly one brokerage firm.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or presenting a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes five roles, spelled exactly: `FirmAdmin`, `TaxOps`, `CustomerService`, `Customer`, and `Auditor`. Each endpoint admits a fixed set of roles, enumerated in §4; a well-identified caller whose role is not admitted to an endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The roles divide the workload along segregation-of-duties lines. `FirmAdmin` is the firm superuser: it alone creates firms, suspends, reinstates, and closes customers, files and refiles 1099-B forms, and drives the logical clock. `TaxOps` is the tax operations specialist: it alone settles, voids, and corrects dispositions, applies and cancels corporate actions, drives transfer statements through delivery, acceptance, rejection, and redelivery, reviews, approves, applies, and rejects basis change requests, and generates 1099-B totals. `CustomerService` is a read-heavy support role that can book lots and dispositions on a customer's behalf and submit basis change requests for them, but holds no settlement or correction power. `Auditor` is a read-only compliance role and cannot mutate anything. `Customer` is the taxpayer: it views its own data, submits basis change requests, and resubmits its own rejected requests.

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a customer compare that resource's customer foreign-key field to `X-User-ID`, and customer-scoped reads are limited to the caller's own record. When `X-User-Role` is `FirmAdmin`, `TaxOps`, `CustomerService`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `approved_by_user_id` or `applied_by_user_id` on a basis change request, where transitions write it — but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in the system — firms, customers, accounts, securities, tax lots, dispositions, corporate actions, transfer statements, wash-sale events, 1099-B forms, and basis change requests — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, including system-driven cascades such as a wash-sale taint landing on a lot.
- `version` (integer): a mutation counter that increments by one on every change to the resource, cascades included. This is the field the optimistic concurrency checks of §2.8 compare against.

### 2.5. Nested Resource Retrieval and the Read Surface

The API enforces strict hierarchical validation on nested paths. When a path chains several identifiers — firm, then customer, account, security, lot, disposition, form, request, statement, or action as they appear — each identifier is validated in left-to-right order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve within the enclosing scope; a request aimed at a disposition under a nonexistent account never reaches the disposition lookup. Every resource is scoped to its firm: an identifier that exists under a different firm behaves as though it does not exist.

Alongside the nested paths, every entity exposes a flat read surface — a direct fetch by identifier plus a filterable list — so that foreign-key relationships are reachable in reverse. The flat lists accept these optional filters: customers by `firm_id` and `status`; accounts by `firm_id`, `customer_id`, and `status`; securities by `firm_id`, `cusip`, and `security_type`; tax lots by `firm_id`, `account_id`, `security_id`, `superseded_by_action_id`, `lot_status`, `covered_status`, and `acquisition_kind`; dispositions by `firm_id`, `account_id`, `security_id`, `status`, and `tax_year`; corporate actions by `firm_id`, `security_id`, `merger_acquirer_security_id`, and `status`; transfer statements by `firm_id`, `account_id`, `security_id`, `replaces_statement_id`, `direction`, and `status`; wash-sale events by `firm_id`, `disposition_id`, `triggering_lot_id`, and `sold_lot_id`; 1099-B forms by `firm_id`, `customer_id`, `tax_year`, and `status`; and basis change requests by `firm_id`, `customer_id`, `tax_lot_id`, `status`, and `request_kind`.

### 2.6. Validation Cascade and Check Ordering

Every request is evaluated against a fixed, ordered cascade, and a rejection at any stage masks every later stage — the client always sees the earliest applicable failure.

1. **Identity headers.** `X-User-ID` and `X-User-Role` must both be present and well-formed, or the request fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Authorization.** The caller's role must be admitted on the endpoint per the Authorized Role(s) column of §4, or the request fails with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Existence.** Every path-template identifier must resolve within the firm scope, validated left to right as described in §2.5, or the request fails with `ERR_NOT_FOUND` (HTTP 404).
4. **State.** The target entity must be in the from-state the requested transition requires, or the request fails with `ERR_INVALID_STATE_TRANSITION` (HTTP 409).
5. **Business rules.** Domain checks run last, in their own pinned order per workflow. Customer standing is always consulted before account standing: booking a disposition or a basis change request against a `SUSPENDED` or `CLOSED` customer fails with `ERR_CUSTOMER_SUSPENDED` (HTTP 409) before the account is even examined, and booking a disposition or an outbound transfer statement against an account that is not `OPEN` then fails with `ERR_ACCOUNT_RESTRICTED` (HTTP 409). Next, foreign keys in the request body — `security_id`, `tax_lot_id`, `merger_acquirer_security_id`, `replaces_statement_id` — must resolve to existing entities inside the same firm, or the request fails with `ERR_FOREIGN_KEY_UNRESOLVABLE` (HTTP 422). Temporal, scope, and fiscal checks follow, each described beside its workflow in §3. Because the order is pinned, a trade dated in a closed tax year surfaces `ERR_TAX_YEAR_CLOSED` even when its lot allocations would also have been mismatched, and a corporate action with an inconsistent payload surfaces `ERR_INCOMPLETE_ACTION_PAYLOAD` regardless of downstream conditions. Malformed bodies, missing required fields, non-positive quantities, and negative amounts are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Monetary Representation, Rounding, and Date Arithmetic

Every monetary amount is carried as an integer number of cents — every field whose name ends in `_cents` is integer-valued, and fractional cents never appear. Wherever a per-share or per-lot figure must be derived — the per-share basis consumed by a disposition allocation, a wash-sale deferral split across replacement lots, cash-in-lieu on a reverse split, or a spinoff basis allocation — the division is rounded half up to the nearest whole cent at that step. Share quantities, by contrast, may be fractional. The 1099-B aggregation performs no rounding of its own, because every figure it sums was already quantized to whole cents upstream. Date arithmetic for holding periods is day-granular: the number of days between a lot's `holding_period_start` and a disposition's `trade_date` decides term character. All deadline comparisons — the correction window above all — are evaluated against the server's logical clock (§2.9), never against wall-clock time.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control. Each requires a non-optional request field carrying the caller's last-observed `version` of a parent entity, and each rejects with HTTP 412 when that expectation no longer matches the entity's current `version`:

- Delivering a transfer statement — `POST /firms/{firmId}/transfer_statements/{stmtId}/deliver` — requires `expected_account_version`, matched against the current `version` of the account whose lots the delivery will consume. A mismatch is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412): a prior delivery or another lot-mutating event has already consumed the source lots, so the caller's view of the account position is stale.
- Applying an approved basis change — `POST /firms/{firmId}/basis_change_requests/{reqId}/apply` — requires `expected_tax_lot_version`, matched against the current `version` of the target tax lot. A mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412): the lot's basis may already have been mutated since approval, for example by a corporate action or a wash-sale taint, so the approval's snapshot is stale.
- Generating a 1099-B — `POST /firms/{firmId}/customers/{customerId}/tax_forms_1099b/{formId}/generate` — requires `expected_customer_version`, matched against the customer's current `version`. A mismatch is rejected with `ERR_STALE_FORM_VERSION` (HTTP 412): the draft's snapshot no longer reflects the customer's lot universe.

Endpoints not listed here do not take a version field.

### 2.9. The Logical Clock and Statutory Deadlines

The server keeps its own logical clock rather than trusting wall-clock time. At startup the clock is fixed at 2026-08-01T00:00:00Z, and it must never fall back to real time; this default sits at or before every default fixture date so that deadline and window rules stay deterministic. A `FirmAdmin` advances the clock through an admin-only test-driving capability, `POST /_clock/set_current_utc`, passing the target instant as `to_iso8601`; the response echoes the new `current_utc`. Filing timestamps such as `filed_at` are taken from this clock, and advancing it can trigger the deferred sweep that freezes correction-pending forms whose statutory window has closed (§3.8).

## 3. Business Logic & Workflows

### 3.1. Firm Setup, Customers, Accounts, and the Security Master

A `FirmAdmin` onboards a brokerage firm by supplying its `legal_name`. The server stamps the firm with three regulatory defaults: `tax_year_open` starts at 2025, the earliest tax year whose books still accept new transactions; `wash_sale_window_days` starts at 30, the regulatory half-window, so the full inclusive wash-sale window spans sixty-one days; and `correction_deadline_days` starts at 1095 — the statute-of-limitations horizon, three years measured in days, within which a filed 1099-B may still be corrected.

Customers are registered under a firm by `FirmAdmin` or `TaxOps`, each carrying a `taxpayer_tin` that is unique within the firm and a human-facing `display_name`. A new customer starts in `ACTIVE`, and the server derives its `wash_sale_scope_key` as the customer's own `taxpayer_tin`: every account opened under the same taxpayer identification number, whatever its type, belongs to one wash-sale aggregation scope. The firm roster can be listed and filtered by `status`.

A `FirmAdmin` may suspend an `ACTIVE` customer, moving it to `SUSPENDED`. Suspension freezes write activity without hiding history: every tax lot under the customer's accounts remains readable, but new dispositions and new basis change requests are rejected with `ERR_CUSTOMER_SUSPENDED` (HTTP 409). Reinstating returns a `SUSPENDED` customer to `ACTIVE`. Closing is the terminal act — `ACTIVE` to `CLOSED` — and is permitted only when two gates pass: every account under the customer must already be `CLOSED`, otherwise the close fails with `ERR_CUSTOMER_HAS_OPEN_ACCOUNTS` (HTTP 409), and no basis change request under the customer may sit in `PENDING`, `UNDER_REVIEW`, or `APPROVED`, otherwise the close fails with `ERR_PENDING_BASIS_REQUESTS` (HTTP 409). A successful close increments the customer's `version`, which immediately stale-marks any non-`REFILED` 1099-B whose `generated_from_version` no longer matches — such a form can no longer be filed.

Accounts are opened under a customer by `FirmAdmin` or `TaxOps`, each with an `account_number` unique within the firm, an `account_type` of `TAXABLE`, `IRA`, or `ROTH_IRA`, and an optional `default_disposal_method` of `FIFO`, `LIFO`, `HIFO`, or `SPECIFIC_ID` that defaults to `FIFO`. Retirement accounts are not exempt from wash-sale mechanics: a replacement purchase inside an `IRA` can permanently disallow a loss realized in a taxable account (§3.4). A new account starts `OPEN`. Either `FirmAdmin` or `TaxOps` may restrict an `OPEN` account, moving it to `RESTRICTED`, which blocks new dispositions and new outbound transfer statements with `ERR_ACCOUNT_RESTRICTED` (HTTP 409) while leaving reads untouched; reopening returns a `RESTRICTED` account to `OPEN`. Closing an account — from either `OPEN` or `RESTRICTED` — requires every lot under it to be finished: each lot must have no shares remaining, with `lot_status` `FULLY_DISPOSED` or `SUPERSEDED`; otherwise the close fails with `ERR_ACCOUNT_HAS_OPEN_LOTS` (HTTP 409). Accounts are listed per customer or across the firm, filterable by `status`.

The security master is maintained by `FirmAdmin` or `TaxOps`. Each record carries a nine-character `cusip` unique within the firm, a `ticker`, a `security_type` of `EQUITY`, `CORPORATE_BOND`, `OPTION`, or `MUTUAL_FUND`, and a `covered_security_effective_date`. A security has no lifecycle state machine; its covered-effective date alone drives the downstream classification described in §3.2. Securities are listed with `cusip` and `security_type` filters.

### 3.2. Booking Acquisition Lots: Purchases, Gifts, and Inheritances

Every position begins as a tax lot booked against an account by `FirmAdmin`, `TaxOps`, or `CustomerService`. The payload contains the `security_id`, the `acquisition_date` — the trade date of the acquisition, which drives both covered classification and term character — the `quantity` acquired, which may be fractional, and the `original_cost_basis_cents`, the total amount paid for that quantity in whole cents. The `acquisition_kind` is optional and defaults to `PURCHASE`; the full vocabulary is `PURCHASE`, `GIFT`, `INHERITANCE`, `TRANSFER_IN`, and `CORPORATE_ACTION_DERIVED`, though the last two are normally minted by the system (§3.6, §3.7) rather than booked directly.

Booking initializes the lot's computed face: `quantity_remaining` starts equal to `quantity`, `adjusted_cost_basis_cents` starts equal to `original_cost_basis_cents`, `wash_sale_taint_basis_cents` starts at zero, `lot_status` opens at `OPEN`, and `covered_status` is computed immediately. A lot's `holding_period_start` ordinarily begins as its `acquisition_date`; corporate actions and wash-sale deferrals can later pull it earlier. Lots are listed per account with `security_id`, `lot_status`, `covered_status`, and `acquisition_kind` filters.

Gifted and inherited positions carry extra detail. Booking a lot with `acquisition_kind` `GIFT` requires both `gift_donor_basis_cents` — the donor's adjusted basis at the gift date — and `gift_fmv_cents_at_gift` — the fair market value per share multiplied by the quantity at the gift date. Booking an `INHERITANCE` lot requires `inherited_fmv_cents_at_death`, the fair market value at the date of death. A gift or inheritance lot booked without its required detail is rejected with `ERR_INCOMPLETE_LOT_BASIS_DETAIL` (HTTP 422).

Inheritance rewrites basis at booking. An `INHERITANCE` lot ignores any supplied `original_cost_basis_cents` and sets `adjusted_cost_basis_cents` to `inherited_fmv_cents_at_death` — the stepped-up basis. Such lots are always classified `NONCOVERED`, their `holding_period_start` is the `acquisition_date` (the date of death), and every allocation from an inherited lot is treated as long-term regardless of how briefly it was held. At settlement, an inherited lot's per-share basis is its `adjusted_cost_basis_cents` divided by its `quantity`, rounded half up to the nearest whole cent.

Gifts follow the dual-basis rule, decided per allocation at settlement time rather than at booking. Two per-share reference prices derive from the gift detail: the donor's basis per share, which is `gift_donor_basis_cents` divided by the lot's `quantity`, and the gift-date fair market value per share, which is `gift_fmv_cents_at_gift` divided by `quantity`; the sale price per share is the disposition's `proceeds_cents` divided by its `quantity`. When the sale price per share exceeds the donor basis per share, the gain is measured using the donor's basis, and the donor's holding period tacks onto the lot's `holding_period_start`. When the sale price per share sits below the gift-date fair market value per share and that fair market value is itself below the donor basis per share, the loss is measured using the fair market value as basis, and the holding period starts at the gift date. When the sale price per share falls between the two — at or above the fair market value per share and at or below the donor basis per share — the allocation recognizes neither gain nor loss. The same gifted lot can therefore produce a gain, a loss, or zero, depending entirely on the sale price.

The `covered_status` classification applies to every lot at booking and is recomputed whenever an `ACQUISITION_DATE_CORRECTION` or `COVERAGE_RECLASS` request is applied (§3.9). Lots whose `acquisition_kind` is `INHERITANCE` are always `NONCOVERED`, and `GIFT` lots are `NONCOVERED` as well, since gifted property was not acquired through the broker. For every other kind, the lot is `COVERED` when its `acquisition_date` falls on or after the security's `covered_security_effective_date` — the boundary is inclusive, so an acquisition exactly on the effective date is covered — and `NONCOVERED` when earlier. Under the IRC 6045 phase-in, the effective date is conventionally 2011-01-01 for equities, 2012-01-01 for mutual funds, and 2014-01-01 for options and corporate bonds, though the value is supplied per security.

### 3.3. Dispositions: Booking, Lot Selection, and Settlement

A sale enters the system as a disposition booked by `FirmAdmin`, `TaxOps`, or `CustomerService` against an account, with a payload containing the `security_id`, the `trade_date`, the `settlement_date` — for equities, conventionally the business day after the trade — the `quantity` sold, and the `proceeds_cents` in whole cents. Two optional fields steer lot selection: `method`, one of `FIFO`, `LIFO`, `HIFO`, or `SPECIFIC_ID`, overrides the account's `default_disposal_method` for this sale and defaults to it when omitted; and `lot_allocations`, a list of `lot_id` and `quantity` pairs, is honored only under `SPECIFIC_ID` and ignored otherwise. A booked disposition starts in `PENDING`; booking never moves shares — it merely records the intended allocations. An account's disposition history is listed with `security_id`, `status`, and `tax_year` filters; the lifecycle vocabulary is `PENDING`, `SETTLED`, `CORRECTED`, and `VOIDED`.

Booking is gated by a fixed screen of business checks, evaluated in this order after the generic cascade of §2.6: customer standing first — a `SUSPENDED` or `CLOSED` customer rejects the booking with `ERR_CUSTOMER_SUSPENDED`; then account standing — an account that is `RESTRICTED` or `CLOSED` rejects it with `ERR_ACCOUNT_RESTRICTED`; then foreign-key resolution — the `security_id` must name a security inside the same firm, or `ERR_FOREIGN_KEY_UNRESOLVABLE`; then the books-window check — a `trade_date` earlier than January 1 of the firm's `tax_year_open` rejects with `ERR_TAX_YEAR_CLOSED` (HTTP 422), because prior years' books are closed; then lot scope — under `SPECIFIC_ID`, every referenced lot must live on the same account and the same security as the disposition, or `ERR_LOT_SCOPE_MISMATCH` (HTTP 422); then fiscal sanity — the `quantity` must be positive, `proceeds_cents` must not be negative, and every per-allocation quantity inside `lot_allocations` must be positive, or `ERR_INVALID_REQUEST`; and finally the allocation sum — under `SPECIFIC_ID`, the quantities across `lot_allocations` must add up to the disposition's `quantity` exactly, or `ERR_LOT_ALLOCATION_MISMATCH` (HTTP 422). Because the order is pinned, a suspended customer always surfaces before a restricted account, and a closed tax year always surfaces before an allocation mismatch.

Settlement moves the disposition from `PENDING` to `SETTLED`. `TaxOps` may settle explicitly, and the system settles automatically when the `settlement_date` arrives; a disposition is economically final at settlement. Settlement requires the account to be `OPEN` and the customer `ACTIVE` at that moment. It re-verifies that the total allocated quantity equals the disposition's `quantity` exactly (`ERR_LOT_ALLOCATION_MISMATCH`), that every lot named under `SPECIFIC_ID` is still `OPEN` or `PARTIALLY_DISPOSED` on this account and security with enough shares remaining, and that the selected lots together can cover the sale — otherwise the settle is refused with `ERR_INSUFFICIENT_LOT_QUANTITY` (HTTP 422).

The lot-selection walk then runs. Candidates are the lots on the same account and the same security whose `lot_status` is `OPEN` or `PARTIALLY_DISPOSED` with shares still remaining. Ordering follows the disposition's `method`. Under `FIFO`, lots are taken earliest `acquisition_date` first, ties broken by the lot's `created_at` ascending. Under `LIFO`, the most recently acquired lots go first, ties broken by `created_at` descending. Under `HIFO`, lots are ordered by per-share adjusted basis — the lot's `adjusted_cost_basis_cents` divided by its `quantity` — from highest to lowest, ties broken by `created_at` ascending. Under `SPECIFIC_ID` there is no sort at all: the request's `lot_allocations` dictate the lots and their order verbatim. The walk consumes from each lot in turn the smaller of the shares still needed and that lot's `quantity_remaining`, until the disposition's full `quantity` is satisfied.

Each allocation is priced in whole cents: the lot's per-share basis is its `adjusted_cost_basis_cents` divided by its `quantity`, rounded half up to the nearest whole cent, and the basis an allocation consumes is that per-share figure multiplied by the allocated quantity. The lot's `quantity_remaining` and `adjusted_cost_basis_cents` are both reduced by the allocated amounts. A lot that still has shares left moves from `OPEN` to `PARTIALLY_DISPOSED`, its `updated_at` refreshed; a lot whose remaining shares are fully consumed becomes `FULLY_DISPOSED` with `quantity_remaining` zero, as does a partially disposed lot whose remainder a later disposition consumes. The disposition's `realized_gain_cents` is then its `proceeds_cents` minus the total basis consumed across all allocations; a negative result is a candidate loss and triggers the wash-sale review of §3.4. Once settled, these figures are immutable except through the correction cycle of §3.5.

Each allocation's term character is decided at settlement. Allocations from an `INHERITANCE` lot are long-term unconditionally. For every other lot — including a gifted lot carrying wash-sale taint, whose tacked holding period dominates the computation — the holding days are counted from the sold lot's `holding_period_start` to the disposition's `trade_date`, and the allocation is long-term only when that count strictly exceeds 365 days. A count of exactly 365 days remains short-term.

Two read-only previews exist for a `PENDING` disposition. The gain preview runs the same selection and pricing walk against current lot state but decrements nothing and persists nothing; it returns the would-be `realized_gain_cents` together with the `allocations` list. Because lots may change between preview and settlement, the two answers can disagree — settlement always writes the canonical values. The wash-sale preview is a deliberately narrower triage signal: it scans only the disposition's own account for replacement lots and answers with `would_trigger` plus the `candidate_lot_ids`, whereas settlement-time detection sweeps every account sharing the customer's `wash_sale_scope_key`.

### 3.4. Wash Sale Detection and Cross-Account Loss Deferral

Wash-sale review runs at settlement whenever the realized gain is negative; a disposition that breaks even or gains is exempt. The window reaches from thirty days before the `trade_date` through thirty days after it — both endpoints inclusive, so an acquisition exactly thirty days before or exactly thirty days after the sale falls inside the sixty-one-day window, the half-window being the firm's `wash_sale_window_days`. The sweep spans the taxpayer's entire relationship with the firm: candidate replacement lots are every lot whose account belongs to a customer with the same `wash_sale_scope_key`, whose security carries the same `cusip` as the sold security, whose `acquisition_date` lies inside the window, whose `acquisition_date` is strictly later than the sold lot's own acquisition date — a replacement, never the lot just sold — which is not the sold lot itself, and whose `lot_status` is `OPEN` or `PARTIALLY_DISPOSED`. Candidates are walked earliest `acquisition_date` first, ties broken by `created_at` ascending.

The shares sold at a loss are the total allocated quantity drawn from lots whose per-lot gain was negative. Each candidate in turn absorbs the smaller of its own `quantity_remaining` and the loss shares still unmatched. When the candidate can cover every remaining loss share, the match is recorded with `matching_rule` `SHARE_FOR_SHARE`; otherwise it is `PARTIAL_PRORATA`. The candidate's disallowed share is the absolute value of the disposition's realized loss, multiplied by the replacement shares the candidate absorbs and divided by the total shares sold at a loss, rounded half up to the nearest whole cent. For each match the system records a wash-sale event naming the `disposition_id`, the `sold_lot_id`, and the `triggering_lot_id`, carrying the `disallowed_loss_cents`, the `matching_rule`, and the computed `wash_sale_window_start` and `wash_sale_window_end` bounding the window. Every event is readable on its own and listable per disposition.

The deferred loss is then tacked onto the triggering lot: the disallowed amount is added to both its `wash_sale_taint_basis_cents` and its `adjusted_cost_basis_cents`, and its `holding_period_start` is replaced by the earlier of its own and the sold lot's, so the replacement lot inherits the sold lot's holding period. Matching stops when every loss share has been paired or the candidates run out. The disposition's `wash_sale_disallowed_loss_cents`, which begins at zero, totals the deferred amounts, and its `is_wash_sale_flag`, initially false, is set to true whenever that total is positive. The recognized loss shrinks by the disallowed portion — the disallowed total is added back to `realized_gain_cents`, though never past zero: a wash sale cannot turn a loss into a gain.

Because the aggregation key is the taxpayer's identification number, a replacement purchase inside an `IRA` or `ROTH_IRA` taints the taxable sale just the same — and the deferred basis that sticks to the retirement lot is permanently unusable: the loss is forfeited, not merely postponed. This cross-account sweep is the canonical, settlement-time behavior; the single-account preview of §3.3 is only its subset.

A detected wash sale also reaches forward into reporting: any 1099-B for this customer and tax year still sitting in `DRAFT` or `GENERATED` is invalidated back to `DRAFT` and must be regenerated (§3.8).

### 3.5. Correcting and Voiding Dispositions

Only `TaxOps` may unwind booked sales. A `PENDING` disposition that should never have been booked is voided: since booking consumed no shares, voiding simply releases the reserved allocations and moves the disposition to `VOIDED`.

Correcting a `SETTLED` disposition is heavier. At least one corrected field — `proceeds_cents`, `quantity`, or `lot_allocations` — must differ from the settled values, and every 1099-B covering this customer and tax year must be outside `FROZEN`: correcting into a frozen year is refused with `ERR_FORM_FROZEN` (HTTP 409). The correction then runs as one atomic transaction. First, the original allocations are reversed — each lot's `quantity_remaining` is restored, and a lot that had flipped to `FULLY_DISPOSED` solely because of this disposition returns toward `OPEN`. Second, every wash-sale event the original settlement spawned is unwound, stripping the deferred amounts back off each triggering lot's `wash_sale_taint_basis_cents` and `adjusted_cost_basis_cents`. Third, a brand-new disposition row is created with the corrected values and driven from `PENDING` to `SETTLED` within the same request, re-running lot selection, gain computation, and wash-sale detection against current lot state. The original row becomes `CORRECTED`, a terminal audit marker, and any 1099-B for this customer and tax year in `GENERATED`, `FILED`, or `CORRECTION_PENDING` is marked `CORRECTION_PENDING`, feeding the correction cycle of §3.8.

### 3.6. Corporate Actions and Basis Reallocation

`FirmAdmin` or `TaxOps` announces a corporate action on a security by supplying the `action_type` — `SPLIT`, `REVERSE_SPLIT`, `MERGER`, or `SPINOFF` — and the `effective_date`, plus the type-specific terms: `split_ratio_numerator` and `split_ratio_denominator` for splits (a two-for-one split carries numerator 2 and denominator 1; a one-for-five reverse split carries numerator 1 and denominator 5); `merger_acquirer_security_id`, `merger_cash_per_share_cents`, and `merger_shares_per_source_share` for mergers and spinoffs; and `spinoff_cost_allocation_pct`, the fraction of pre-action basis assigned to the spun-off security, for spinoffs alone. An announced action sits in `ANNOUNCED`, and a security's actions are listed with a `status` filter.

Payload consistency is enforced identically at announcement and at application. A split or reverse split requires a positive numerator and a positive denominator. A merger requires an acquirer security, a `merger_cash_per_share_cents` of at least zero, and a positive `merger_shares_per_source_share`. A spinoff requires an acquirer security and an allocation fraction strictly between zero and one. An inconsistent payload fails with `ERR_INCOMPLETE_ACTION_PAYLOAD` (HTTP 422), and an acquirer identifier that does not resolve to a security inside the same firm fails with `ERR_FOREIGN_KEY_UNRESOLVABLE` (HTTP 422).

Application — `TaxOps` only — moves the action from `ANNOUNCED` to `EFFECTIVE` and rewrites every affected lot across the firm. Each source lot on the action's security in `OPEN` or `PARTIALLY_DISPOSED` is superseded: its `lot_status` becomes `SUPERSEDED`, its `superseded_by_action_id` points at the action, its `quantity_remaining` drops to zero, and one or more derived lots with `acquisition_kind` `CORPORATE_ACTION_DERIVED` take its place. Every account that held an affected lot has its `updated_at` refreshed and its `version` incremented. An action still merely announced can instead be cancelled, moving it to `CANCELLED` with no lot impact; `EFFECTIVE` and `CANCELLED` are terminal.

The derived lots depend on the action type. In each case the source lot's remaining shares are its `quantity_remaining` and its basis is its `adjusted_cost_basis_cents`:

- Under a `SPLIT`, the derived lot's share count is the remaining shares multiplied by the numerator and divided by the denominator — fractional shares are permitted. Both `original_cost_basis_cents` and `adjusted_cost_basis_cents` carry the source basis unchanged: total basis is conserved and only the per-share figure moves. The `wash_sale_taint_basis_cents` carries over whole.
- Under a `REVERSE_SPLIT`, the derived share count is the same product rounded down to a whole share. The leftover fraction is paid out as cash in lieu, computed as the fractional part of that product multiplied by the source basis and divided by the remaining shares, rounded half up to the nearest whole cent. The derived lot's original and adjusted basis equal the source basis minus this cash-in-lieu amount, and its taint is reduced by the same amount but never below zero. The cash in lieu is a taxable deemed sale of the fractional share, recognizing gain or loss against that fraction's basis.
- Under a `MERGER`, the derived lot lives on the acquirer security and holds the remaining shares multiplied by `merger_shares_per_source_share`, again possibly fractional. Its basis equals the source basis reduced by the cash boot — the remaining shares multiplied by `merger_cash_per_share_cents` — but never by more than the basis itself, so it cannot fall below zero. Cash boot in excess of basis is taxable gain recognized in the year of the action. The taint carries over whole.
- Under a `SPINOFF`, two derived lots are born. The spun-off lot on the acquirer security holds the remaining shares multiplied by `merger_shares_per_source_share` and carries a basis equal to the source basis multiplied by `spinoff_cost_allocation_pct`, rounded half up to the nearest whole cent. The parent lot stays on the original security, keeps the full remaining share count, and carries the remainder of the basis. The two derived bases sum exactly to the source basis — a conservation invariant the system guarantees.

Every derived lot, whatever the action type, inherits the source lot's `acquisition_date` and `holding_period_start`: a corporate action never restarts a holding period. Lots consumed by an action remain traceable — the flat lot list filters by `superseded_by_action_id`.

### 3.7. Transfer Statements for Moved Positions

When a position moves between this firm and an outside broker, the basis detail travels on a transfer statement. `TaxOps` or `FirmAdmin` creates one against an account with the `direction` — `INBOUND` for a receipt, `OUTBOUND` for a delivery — the `counterparty_firm_name`, the `security_id`, the `quantity` moved, and the `transfer_date`. The `lots_payload` is an array of entries, each giving an `acquisition_date`, a `quantity`, and an `original_cost_basis_cents`, describing the per-lot basis detail received from or delivered to the counterparty; it may be omitted at creation but must be present before delivery. A statement may also carry `replaces_statement_id`, naming an earlier statement it supersedes; the referenced statement must exist and currently be `DELIVERED`, or creation fails with `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 422). New statements start in `PENDING`, and an account must be `OPEN` to originate an outbound one (`ERR_ACCOUNT_RESTRICTED`). Statements are listed per account with `direction` and `status` filters.

Delivery — `TaxOps` only, and guarded by the account-level concurrency check of §2.8 — moves a `PENDING` statement to `DELIVERED`. The payload must be non-empty, or the delivery fails with `ERR_TRANSFER_MISSING_LOT_DETAIL` (HTTP 422), and for an outbound statement the source account must hold at least the statement's `quantity` across its open and partially disposed lots on that security, or the delivery fails with `ERR_TRANSFER_INSUFFICIENT_POSITION` (HTTP 422). Delivering an outbound statement consumes the source lots in the order dictated by the account's `default_disposal_method`, flipping them to `PARTIALLY_DISPOSED` or `FULLY_DISPOSED` as shares run out, bundles their basis onto the payload, and increments the account's `version`.

Acceptance moves a `DELIVERED` statement to `ACCEPTED`. For an inbound receipt, acceptance materializes one new tax lot per payload entry: each arrives with `acquisition_kind` `TRANSFER_IN`, its `original_cost_basis_cents` taken from the payload entry, its `adjusted_cost_basis_cents` initialized to that same value, and its `holding_period_start` set to the entry's `acquisition_date`. Rejection instead moves a delivered statement to `REJECTED`: for an outbound delivery the consumed source lots are restored — `quantity_remaining` and `lot_status` roll back — while for an inbound receipt nothing was created yet and there is nothing to roll back.

A rejected statement is not dead. `TaxOps` can redeliver it, moving it back to `PENDING`, where its `lots_payload` may be edited before another delivery attempt — unless a replacement statement referencing it has already reached `DELIVERED`, in which case redelivery fails with `ERR_TRANSFER_ALREADY_SUPERSEDED` (HTTP 409). Supersession itself is system-driven: the moment a replacement statement carrying `replaces_statement_id` reaches `DELIVERED`, the earlier statement flips to `SUPERSEDED`, and if the earlier statement was an outbound delivery, its lot consumption is first restored before the replacement's own delivery consumes the lots afresh. A statement's journey ends at `ACCEPTED` or `SUPERSEDED`.

### 3.8. Form 1099-B Generation, Filing, and the Correction Cycle

The annual reporting cycle opens when `TaxOps` or `FirmAdmin` creates a draft 1099-B for a customer and a calendar `tax_year`; the form is born `DRAFT` with every total zeroed, and a customer's forms are listed with `tax_year` and `status` filters. Generation — `TaxOps` only, guarded by the customer-level concurrency check of §2.8 — is allowed while the form is `DRAFT` and the customer is anything but `CLOSED`. It runs the year's aggregation, populates the six box totals and the wash-sale figure, snapshots the customer's current `version` into `generated_from_version`, and moves the form to `GENERATED`.

The aggregation sweeps every disposition on every account of the customer whose `status` is `SETTLED` — corrected dispositions are excluded, because each was replaced by a new row — whose `trade_date` falls inside the form's `tax_year`, and which consumed at least one `COVERED` lot. Dispositions that touched only noncovered lots are not reported on the 1099-B at all; they live in the customer's own records. Each qualifying disposition's `proceeds_cents` is apportioned between the short-term and long-term buckets in proportion to the shares allocated to each term, and the basis buckets accumulate the basis consumed from covered lots of the matching term, using the per-share allocation figures already computed at settlement. Six totals land on the form: `short_term_proceeds_cents`, `short_term_basis_cents`, and `short_term_gain_cents` — proceeds minus basis for the short-term bucket — then `long_term_proceeds_cents`, `long_term_basis_cents`, and `long_term_gain_cents`, the same arithmetic for the long-term bucket. A seventh figure, `disallowed_wash_sale_loss_cents`, sums every qualifying disposition's `wash_sale_disallowed_loss_cents` and is reported in Box 1g. All inputs are already whole cents at this point, so the aggregation itself performs no rounding.

Filing is a `FirmAdmin` act with a freshness guard: the form must be `GENERATED`, and the customer's current `version` must still equal `generated_from_version`, proving the customer's lot universe has not shifted since generation; a drifted form rejects with `ERR_STALE_FORM_VERSION` (HTTP 412). A filed form records `filed_at` from the logical clock and moves to `FILED`.

The correction cycle keeps a filed form honest. Three in-scope events flip a `FILED` form to `CORRECTION_PENDING` automatically, incrementing the customer's `version`: a disposition in scope is corrected, a basis change request in scope reaches `APPLIED`, or a wash-sale event is created in scope after filing. Refiling — again `FirmAdmin` — re-runs the aggregation against the corrected source data, overwrites every total, increments `correction_count` (which starts at zero on a fresh form), refreshes `generated_from_version` to the customer's then-current `version`, and moves the form to `REFILED`. Refiling is lawful only inside the statute window: the logical clock must read no later than `filed_at` plus the firm's `correction_deadline_days`, or the attempt fails with `ERR_CORRECTION_WINDOW_CLOSED` (HTTP 422). Further qualifying changes flip a `REFILED` form back to `CORRECTION_PENDING` — the loop between filed and correction-pending is unbounded while the window stays open. Should the logical clock cross the deadline while a form still sits in `CORRECTION_PENDING`, the system freezes it: `FROZEN` is permanent, no further corrections are accepted, and that permanence is exactly why correcting a disposition into a frozen year is refused outright (§3.5).

### 3.9. Customer Basis Change Requests and Segregation of Duties

A customer — or a `CustomerService` operator acting on their behalf — disputes a lot's tax posture by submitting a basis change request naming the `tax_lot_id` and a `request_kind` of `COVERAGE_RECLASS`, `BASIS_AMOUNT_CORRECTION`, `ACQUISITION_DATE_CORRECTION`, or `GIFT_BASIS_SUPPLY`. The kind dictates the payload: `proposed_basis_cents` accompanies `BASIS_AMOUNT_CORRECTION` and `GIFT_BASIS_SUPPLY`; `proposed_acquisition_date` accompanies `ACQUISITION_DATE_CORRECTION` and `COVERAGE_RECLASS`; `proposed_coverage`, either `COVERED` or `NONCOVERED`, accompanies `COVERAGE_RECLASS`; and `GIFT_BASIS_SUPPLY` carries `gift_donor_basis_cents` and `gift_fmv_cents_at_gift`. A `supporting_doc_ref` may be attached at submission and becomes mandatory at approval. New requests are born `PENDING`, and a customer who is `SUSPENDED` or `CLOSED` cannot file one (`ERR_CUSTOMER_SUSPENDED`). A customer's requests are listed with `status` and `request_kind` filters, and the flat request list additionally filters by `tax_lot_id`.

Review is `TaxOps` territory. Starting review moves a `PENDING` request to `UNDER_REVIEW`. Approval requires a non-empty `supporting_doc_ref` — approving without one fails with `ERR_MISSING_SUPPORTING_DOC` (HTTP 422) — and records the acting operator as `approved_by_user_id` while snapshotting the target lot's current `version` into `version_applied_to`. Rejection from `UNDER_REVIEW` moves the request to `REJECTED`, from which the owning customer — and only that customer, verified by comparing the request's customer to the caller's `X-User-ID` — may resubmit it, moving it to `RESUBMITTED`; a resubmitted request re-enters review through the same start-review action.

Application demands a second pair of hands. The operator applying an `APPROVED` request must be a different `TaxOps` user than the one recorded in `approved_by_user_id`; the same user attempting both steps is refused with `ERR_SOD_VIOLATION` (HTTP 403). The apply call must carry `expected_tax_lot_version` matching the lot's current `version` per §2.8, and the lot must still sit exactly at the snapshot captured in `version_applied_to` — any drift is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). The target lot must also still be `OPEN` or `PARTIALLY_DISPOSED`; a fully disposed or superseded lot cannot take a basis change. On success the server records the acting operator as `applied_by_user_id`, increments the lot's `version`, and moves the request to `APPLIED`, its terminal state.

What application does depends on the kind. A `COVERAGE_RECLASS` overwrites the lot's `covered_status` with `proposed_coverage`, overriding the computed value. A `BASIS_AMOUNT_CORRECTION` replaces the lot's `adjusted_cost_basis_cents` with `proposed_basis_cents` while preserving `original_cost_basis_cents` for audit; settled dispositions that already consumed the lot are left alone — history does not re-open — and only future dispositions see the new basis. An `ACQUISITION_DATE_CORRECTION` rewrites the lot's `acquisition_date` to `proposed_acquisition_date`, recomputes `covered_status` under the classification rule of §3.2, and resets `holding_period_start` to the new date. A `GIFT_BASIS_SUPPLY` fills in the lot's `gift_donor_basis_cents` and `gift_fmv_cents_at_gift`, flips its `acquisition_kind` to `GIFT`, and forces `covered_status` to `NONCOVERED` under the gift rule. Whatever the kind, any 1099-B for this customer covering the lot's tax year that sits in `GENERATED`, `FILED`, or `REFILED` is moved to `CORRECTION_PENDING`, and the correction cycle of §3.8 takes over.

## 4. Endpoint Definitions

Operations that create a new resource — a firm, customer, account, security, tax lot, disposition, corporate action, transfer statement, draft 1099-B, or basis change request — return `201 Created`. Operations that modify an existing resource or drive a state transition — suspend, reinstate, close, restrict, reopen, settle, void, correct, apply, cancel, deliver, accept, reject, redeliver, generate, file, refile, start review, approve, apply, reject, resubmit, and the clock advance — return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/firms` | Create a brokerage firm | FirmAdmin |
| GET | `/firms/{firmId}` | Get a firm | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/{firmId}/customers` | List customers of a firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| POST | `/firms/{firmId}/customers` | Create a customer | FirmAdmin, TaxOps |
| GET | `/firms/{firmId}/customers/{customerId}` | Get a customer | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/customers/{customerId}/suspend` | Suspend a customer | FirmAdmin |
| POST | `/firms/{firmId}/customers/{customerId}/reinstate` | Reinstate a suspended customer | FirmAdmin |
| POST | `/firms/{firmId}/customers/{customerId}/close` | Close a customer | FirmAdmin |
| GET | `/firms/{firmId}/customers/{customerId}/accounts` | List accounts under a customer | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/customers/{customerId}/accounts` | Open a new account | FirmAdmin, TaxOps |
| GET | `/firms/{firmId}/accounts/{accountId}` | Get an account | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/accounts/{accountId}/restrict` | Restrict an account | FirmAdmin, TaxOps |
| POST | `/firms/{firmId}/accounts/{accountId}/reopen` | Reopen a restricted account | FirmAdmin, TaxOps |
| POST | `/firms/{firmId}/accounts/{accountId}/close` | Close an account | FirmAdmin, TaxOps |
| POST | `/firms/{firmId}/securities` | Register a security master record | FirmAdmin, TaxOps |
| GET | `/firms/{firmId}/securities/{securityId}` | Get a security | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/{firmId}/securities` | List securities | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/accounts/{accountId}/tax_lots` | Book an acquisition lot | FirmAdmin, TaxOps, CustomerService |
| GET | `/firms/{firmId}/tax_lots/{lotId}` | Get a tax lot | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/{firmId}/accounts/{accountId}/tax_lots` | List lots under an account | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/accounts/{accountId}/dispositions` | Book a sale (PENDING) | FirmAdmin, TaxOps, CustomerService |
| GET | `/firms/{firmId}/dispositions/{dispositionId}` | Get a disposition | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/{firmId}/accounts/{accountId}/dispositions` | List dispositions under an account | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/dispositions/{dispositionId}/settle` | Settle a PENDING disposition | TaxOps |
| POST | `/firms/{firmId}/dispositions/{dispositionId}/void` | Void a PENDING disposition | TaxOps |
| POST | `/firms/{firmId}/dispositions/{dispositionId}/correct` | Correct a SETTLED disposition | TaxOps |
| GET | `/firms/{firmId}/dispositions/{dispositionId}/preview_gain` | Preview realized gain for a PENDING disposition | TaxOps, CustomerService, FirmAdmin |
| GET | `/firms/{firmId}/dispositions/{dispositionId}/preview_wash_sale` | Preview same-account wash-sale signal | TaxOps, CustomerService, FirmAdmin |
| POST | `/firms/{firmId}/securities/{securityId}/corporate_actions` | Announce a corporate action | FirmAdmin, TaxOps |
| GET | `/firms/{firmId}/corporate_actions/{actionId}` | Get a corporate action | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/{firmId}/securities/{securityId}/corporate_actions` | List corporate actions for a security | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/corporate_actions/{actionId}/apply` | Apply a corporate action to all affected lots | TaxOps |
| POST | `/firms/{firmId}/corporate_actions/{actionId}/cancel` | Cancel an ANNOUNCED corporate action | TaxOps |
| POST | `/firms/{firmId}/accounts/{accountId}/transfer_statements` | Create a transfer statement | TaxOps, FirmAdmin |
| GET | `/firms/{firmId}/transfer_statements/{stmtId}` | Get a transfer statement | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/{firmId}/accounts/{accountId}/transfer_statements` | List transfer statements for an account | FirmAdmin, TaxOps, CustomerService, Auditor |
| POST | `/firms/{firmId}/transfer_statements/{stmtId}/deliver` | Deliver a transfer statement (OCC-guarded) | TaxOps |
| POST | `/firms/{firmId}/transfer_statements/{stmtId}/accept` | Accept a delivered statement | TaxOps |
| POST | `/firms/{firmId}/transfer_statements/{stmtId}/reject` | Reject a delivered statement | TaxOps |
| POST | `/firms/{firmId}/transfer_statements/{stmtId}/redeliver` | Move a REJECTED statement back to PENDING | TaxOps |
| GET | `/firms/{firmId}/wash_sale_events/{eventId}` | Get a wash sale event | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/{firmId}/dispositions/{dispositionId}/wash_sale_events` | List wash-sale events triggered by a disposition | FirmAdmin, TaxOps, CustomerService, Auditor |
| POST | `/firms/{firmId}/customers/{customerId}/tax_forms_1099b` | Create a DRAFT 1099-B for a customer and year | TaxOps, FirmAdmin |
| GET | `/firms/{firmId}/customers/{customerId}/tax_forms_1099b/{formId}` | Get a 1099-B form | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/{firmId}/customers/{customerId}/tax_forms_1099b` | List 1099-B forms for a customer | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/customers/{customerId}/tax_forms_1099b/{formId}/generate` | Generate totals for a DRAFT form (OCC-guarded) | TaxOps |
| POST | `/firms/{firmId}/customers/{customerId}/tax_forms_1099b/{formId}/file` | File a GENERATED form | FirmAdmin |
| POST | `/firms/{firmId}/customers/{customerId}/tax_forms_1099b/{formId}/refile` | Refile a CORRECTION_PENDING form | FirmAdmin |
| POST | `/firms/{firmId}/customers/{customerId}/basis_change_requests` | Submit a basis change request | Customer, CustomerService |
| GET | `/firms/{firmId}/basis_change_requests/{reqId}` | Get a basis change request | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/{firmId}/customers/{customerId}/basis_change_requests` | List basis change requests for a customer | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| POST | `/firms/{firmId}/basis_change_requests/{reqId}/start_review` | Start review of a request | TaxOps |
| POST | `/firms/{firmId}/basis_change_requests/{reqId}/approve` | Approve a request (snapshots lot version) | TaxOps |
| POST | `/firms/{firmId}/basis_change_requests/{reqId}/apply` | Apply an APPROVED request (OCC-guarded) | TaxOps |
| POST | `/firms/{firmId}/basis_change_requests/{reqId}/reject` | Reject a request | TaxOps |
| POST | `/firms/{firmId}/basis_change_requests/{reqId}/resubmit` | Customer resubmits a REJECTED request | Customer |
| GET | `/firms/customers/{customerId}` | Get a customer by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/customers` | List customers, filterable by firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/accounts/{accountId}` | Get an account by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/accounts` | List accounts across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/securities/{securityId}` | Get a security by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/securities` | List securities across firms | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/tax_lots/{lotId}` | Get a tax lot by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/tax_lots` | List tax lots across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/dispositions/{dispositionId}` | Get a disposition by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/dispositions` | List dispositions across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/corporate_actions/{actionId}` | Get a corporate action by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/corporate_actions` | List corporate actions across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/transfer_statements/{stmtId}` | Get a transfer statement by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/transfer_statements` | List transfer statements across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/wash_sale_events/{eventId}` | Get a wash sale event by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/wash_sale_events` | List wash sale events across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/tax_forms_1099b/{formId}` | Get a 1099-B form by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/tax_forms_1099b` | List 1099-B forms across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| GET | `/firms/basis_change_requests/{reqId}` | Get a basis change request by id (flat form) | FirmAdmin, TaxOps, CustomerService, Auditor, Customer |
| GET | `/firms/basis_change_requests` | List basis change requests across the firm | FirmAdmin, TaxOps, CustomerService, Auditor |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | FirmAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FOREIGN_KEY_UNRESOLVABLE` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_ACCOUNT_RESTRICTED` | 409 Conflict |
| `ERR_TAX_YEAR_CLOSED` | 422 Unprocessable Entity |
| `ERR_LOT_SCOPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INCOMPLETE_ACTION_PAYLOAD` | 422 Unprocessable Entity |
| `ERR_INCOMPLETE_LOT_BASIS_DETAIL` | 422 Unprocessable Entity |
| `ERR_LOT_ALLOCATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_MISSING_SUPPORTING_DOC` | 422 Unprocessable Entity |
| `ERR_CORRECTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_TRANSFER_ALREADY_SUPERSEDED` | 409 Conflict |
| `ERR_TRANSFER_INSUFFICIENT_POSITION` | 422 Unprocessable Entity |
| `ERR_TRANSFER_MISSING_LOT_DETAIL` | 422 Unprocessable Entity |
| `ERR_FORM_FROZEN` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_LOTS` | 409 Conflict |
| `ERR_CUSTOMER_HAS_OPEN_ACCOUNTS` | 409 Conflict |
| `ERR_PENDING_BASIS_REQUESTS` | 409 Conflict |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FORM_VERSION` | 412 Precondition Failed |

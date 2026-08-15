# Naming Rights & Sponsorship Fulfillment API — Product Requirements Document

## 1. Introduction

Venue sponsorship is a long-cycle, high-value business. A single naming-rights deal can span several seasons, bundle signage, digital media, and hospitality inventory, and carry contractual promises whose fulfillment must be proven with evidence, measured against audited media value, compensated when elements are missed, and paid for in installments. This document specifies the API through which a venue sponsorship department runs that entire book of business: registering asset inventory and its valuation basis, reserving team, venue, and league category rights, drafting and countersigning contracts with escalator-driven season fees, planning activation deliverables, collecting proof of performance, compensating shortfalls with make-good credits, billing and collecting the installment schedule, reporting delivered value back to the sponsor, and working the renewal pipeline.

Two structural realities shape every rule that follows. First, the department's calendar is a season epoch, not a wall clock: each venue advances from one season to the next only through an explicit operational checkpoint, and every temporal rule — term windows, exclusivity windows, season close, expiry — is evaluated against that epoch. Second, money and exposure reconcile continuously: invoices, payments, make-good credits, and contract-level derived totals are recomputed immediately as each event lands, so a contract's financial position is never stale. Everything below assumes those two foundations.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and invariants that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly five roles: `VenueAdmin`, `SponsorshipSales`, `ActivationManager`, `FinanceManager`, and `SponsorContact`. A request missing either header, or naming a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint — or, for a sponsor contact, whose target lies outside their sponsorship scope — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four of the roles carry opaque identities. When `X-User-Role` is `VenueAdmin`, `SponsorshipSales`, `ActivationManager`, or `FinanceManager`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` on an evidence submission — but it never compares the value against any entity's `id`.

`SponsorContact` is the entity-backed exception. When `X-User-Role` is `SponsorContact`, `X-User-ID` is the `id` of the `SponsorAccount` the contact represents, and ownership checks on any resource that references a sponsor compare the resource's sponsor linkage to `X-User-ID`. Countersigning a contract requires the contract's `sponsor_id` to equal `X-User-ID`; acknowledging a valuation report requires the report's contract's `sponsor_id` to equal `X-User-ID`; and every read performed by a sponsor contact is scoped to resources whose sponsor linkage leads back to their own sponsor account: on single-resource reads — including the sponsor account resource itself — an out-of-scope target is rejected with `ERR_FORBIDDEN`, while list endpoints instead filter their result set down to in-scope resources. Resources carrying no sponsor linkage — venues, assets, and rights windows — are not sponsor-scoped: any authenticated role, including a sponsor contact, may read any of them.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of records returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. `offset` sets how many records are skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Every list response is sorted by `created_at` in ascending order; the ordering is stable and deterministic, and `id` is never used as an ordering key. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the supplied filters and `has_more` is true exactly when `offset` plus the number of records returned is less than `total_count`.

### 2.4. The Season Epoch and the Advance-Season Checkpoint

Time in this system is measured in integer seasons, not on a wall clock. Each venue maintains its own epoch in `current_season`, initialized to 2026 when the venue is created and advanced by exactly one season each time a `VenueAdmin` runs the advance-season checkpoint. Nothing expires, closes, or changes state on its own: every season-driven transition happens inside that checkpoint or through an explicit operator action. The checkpoint increments the venue's `version` by one and processes its work in a fixed order — deliverable evaluation first, contract expiry second, rights-window expiry third. The full cascade content of the checkpoint is specified in §3.5.

### 2.5. Season Windows, Date Spans, and Overlap Arithmetic

Season windows throughout the system are inclusive integer ranges: a window described by `first_season` and `last_season` covers both boundary seasons and every season between them. Two season windows overlap when each window's first season is no later than the other window's last season — equivalently, when neither window ends strictly before the other begins. Two windows sitting back-to-back, where one window's first season is exactly one greater than the other's last season, do not overlap. This predicate governs both grant-versus-grant exclusivity comparisons and grant-versus-league-window conflict detection, always within the same venue and the same category.

Suite hospitality is booked in calendar dates rather than seasons. A suite-night booking occupies the span from its `checkin_date` through its `checkout_date` plus a one-day turnaround buffer after checkout, so its blocked span ends one day after checkout. A new suite booking on the same asset conflicts with an existing booking that has not been cancelled when the new booking's check-in falls on or before the day after the existing booking's checkout and, symmetrically, the existing booking's check-in falls on or before the day after the new booking's checkout. The boundary is deliberate: arriving exactly one day after the previous checkout conflicts, because that day is the turnaround buffer, while arriving two days after the previous checkout is allowed.

### 2.6. Rights Governance Across Team, Venue, and League

Category rights at a venue are reserved through rights windows held by one of `TEAM`, `VENUE`, or `LEAGUE`, each window covering one sponsorship category — one of `BEVERAGE`, `BANKING`, `AUTO`, `AIRLINE`, or `TECH` — over an inclusive season span. A contract acquires exclusivity through grants, which may be activated only after rights checks pass, and a league window activated over the same venue and category preempts overlapping venue-side grants. Every contract therefore carries two independent dimensions: `contract_status`, its commercial lifecycle, and `rights_status`, which is `CLEAR` while the contract has no `CONFLICTED` grant and becomes `CONTESTED` the moment any grant of the contract is `CONFLICTED`. A `CONTESTED` contract is barred from exactly three operations — creating deliverables, approving evidence, and issuing invoices, each rejected with `ERR_CONTRACT_RIGHTS_CONTESTED` — while its `contract_status` transitions remain otherwise available. The contest and release cascades that move grants and contracts between these states are specified in §3.2.

### 2.7. Monetary Precision and Valuation Arithmetic

All money in the system is carried as integer cents. Every monetary computation rounds half-up to whole cents, and rounding is applied exactly once at the end of each defined computation — there is no cumulative per-year drift, except where a calculation explicitly pins per-line rounding before summation. Fees, invoice amounts, credit amounts, and valuations are all integers. The escalator rate `escalator_pct` is a decimal rate such as 0.03 and must be zero or positive. Two valuation views coexist deliberately: the provisional view prices delivered units at the asset's rate-card value, and the final view prices them at audited media value — impressions per unit multiplied by the cost-per-thousand-impressions rate, divided by one thousand. Fulfillment ratios are exact rational comparisons at decision boundaries; only when a ratio is reported, as on the season measurement report, is it rounded — half-up to four decimal places.

### 2.8. Derived Ledgers: Receivables and Make-Good Exposure

Two totals on each contract are never written directly; they are recomputed from child records whenever a relevant event lands, synchronously within the triggering request. `receivable_cents` is the sum, over the contract's invoices in `ISSUED`, `PARTIALLY_PAID`, `PAID`, or `WRITTEN_OFF` status, of each invoice's `amount_cents` minus its `paid_cents` minus its `credits_applied_cents`; invoices in `DRAFT` or `VOID` contribute nothing. `make_good_outstanding_cents` is the sum of `approved_amount_cents` over the contract's make-good credits in `APPROVED` status only — requested, declined, redeemed, and voided credits are all excluded. Issuing an invoice, posting a payment, voiding a payment, redeeming a credit, writing off an invoice, approving a credit, and voiding an approved credit each trigger the corresponding recomputation, so the contract the client reads back always reflects every event that preceded the read.

### 2.9. Cascade Discipline and Cross-Entity Reconciliation

State changes propagate along fixed paths so the book of business stays coherent. Blocking a sponsor terminates its live contracts; terminating a contract cancels its open deliverables, releases its grants, voids its draft invoices, and voids its unresolved credits; cancelling a deliverable voids its open evidence. Advancing the season flips deliverables into and past their working windows, expires contracts whose term has closed, expires rights windows whose span has passed, and spawns make-good credits for missed elements. Activating a league rights window contests overlapping grants and thereby contests their contracts; releasing or expiring that window reactivates the grants it alone was blocking and can restore a contract to `CLEAR`. Every mutation — whether operator-driven or system-cascaded — refreshes the mutated resource's `updated_at` and increments its `version`.

### 2.10. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification; it initially equals `created_at`.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation of the resource, underpinning the optimistic concurrency guards of §2.11.

All twelve resource types — venues, sponsor accounts, assets, rights windows, contracts, exclusivity grants, deliverables, evidence submissions, make-good credits, invoices, valuation reports, and renewal opportunities — carry this full set.

### 2.11. Optimistic Concurrency Control

Exactly two write operations guard against stale reads through a mandatory expected-version field; no other endpoint accepts a version field.

A request to countersign a contract (`POST /contracts/{contract_id}/countersign`) must carry `expected_contract_version`, holding the contract `version` the sponsor last observed. If the contract's current `version` differs — for example because a sales edit to the commercial terms advanced it after the proposal was read — the countersign is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), since the sponsor would otherwise be signing terms they never saw.

A request to counter a renewal opportunity (`POST /renewal-opportunities/{opportunity_id}/counter`) must carry `expected_opportunity_version`, holding the opportunity `version` the seller last observed. A mismatch with the opportunity's current `version` is rejected with `ERR_STALE_OPPORTUNITY_VERSION` (HTTP 412), since the new counter would otherwise be priced against terms that have already moved.

### 2.12. Validation Order Across the Request Pipeline

Every request is validated against the rule catalogue in a fixed priority order, and a failure at any tier masks everything below it. The tiers, from first to last, are:

1. **Authentication** — both headers present and the role recognized (`ERR_UNAUTHENTICATED`).
2. **Request shape** — all required input fields present, no undeclared fields, enum values within their declared constraint sets, integer and date fields parseable (`ERR_INVALID_REQUEST`). A body that is not a JSON object is rejected at this tier; an absent body is treated as an empty object.
3. **Authorization** — the role is permitted on the endpoint and, for sponsor contacts, the target lies within their sponsor scope (`ERR_FORBIDDEN`).
4. **Existence** — path identifiers exist, validated left to right, and body references such as `venue_id`, `sponsor_id`, `contract_id`, `asset_id`, `deliverable_id`, and `renewed_from_contract_id` resolve to existing resources (`ERR_NOT_FOUND`); a request carrying several body references has them validated in the order named here.
5. **State-machine legality** — the target entity's own lifecycle permits the requested action from its current state, including terminal-state lockdown and compound state preconditions expressed as `ERR_INVALID_STATE`.
6. **Rights-compliance safety** — league preemption and contested-rights gates (`ERR_RIGHTS_CONFLICT`, `ERR_CONTRACT_RIGHTS_CONTESTED`).
7. **Temporal placement** — season and date windows well-formed and open (`ERR_SEASON_WINDOW_INVALID`, `ERR_SEASON_OUT_OF_TERM`, `ERR_SEASON_CLOSED`, `ERR_GRANT_OUTSIDE_TERM`, `ERR_SEASON_NOT_CLOSED`).
8. **Business constraints** — exclusivity overlap, duplicate grants, suite date conflicts, over-delivery, duplicate open opportunities, and segregation of duties (`ERR_CATEGORY_EXCLUSIVITY_CONFLICT`, `ERR_DUPLICATE_GRANT`, `ERR_SUITE_DATE_CONFLICT`, `ERR_OVER_DELIVERY`, `ERR_DUPLICATE_OPEN_OPPORTUNITY`, `ERR_SEGREGATION_OF_DUTIES`).
9. **Referential gates** — sponsor, asset, contract, deliverable, and renewal-source preconditions (`ERR_SPONSOR_NOT_ACTIVE`, `ERR_ASSET_NOT_AVAILABLE`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_DELIVERABLE_NOT_OPEN`, `ERR_RENEWAL_CONTRACT_STATE`).
10. **Fiscal checks** — amount positivity, caps, and balances (`ERR_INVALID_AMOUNT`, `ERR_CREDIT_EXCEEDS_CAP`, `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_INVOICE_NOT_PAYABLE`, `ERR_CREDIT_EXCEEDS_INVOICE_BALANCE`, `ERR_NO_PAYABLE_INVOICE`).

A request that fails authentication never reaches shape validation; on a request that trips both a contested-rights gate and a contract-not-active gate, the contested-rights rejection (tier 6) is the one returned; and fiscal amount problems surface only after every structural, temporal, and referential gate has passed.

## 3. Business Logic & Workflows

### 3.1. Building the Book: Venues, Sponsors, and Asset Inventory

A `VenueAdmin` opens the book by creating each venue with its `display_name` and `city`; the venue's `current_season` starts at 2026 and moves only through the advance-season checkpoint described in §2.4 and §3.5.

Sponsor accounts are created by `SponsorshipSales` with the sponsor's `legal_name`, brand `display_name`, and `industry_category` drawn from the five sponsorship categories. A new account's `sponsor_status` starts at `PROSPECT`; qualification (`QUALIFY`) moves it to `ACTIVE`. Suspension (`SUSPEND`) moves an `ACTIVE` sponsor to `SUSPENDED` and cascades one hop: every contract of that sponsor in `ACTIVE` moves to `SUSPENDED` with it. Reinstatement (`REINSTATE`) returns a `SUSPENDED` sponsor to `ACTIVE` but deliberately does not reinstate its contracts — each suspended contract needs its own reinstatement. Blocking (`BLOCK`) is available from `ACTIVE` or `SUSPENDED`, moves the sponsor to the terminal `BLOCKED` state, and runs the deepest cascade in the system, in three hops. Hop one terminates every contract of the sponsor in `COUNTERSIGNED`, `ACTIVE`, or `SUSPENDED`. Hop two, caused by those terminations, cancels every deliverable of a terminated contract in `SCHEDULED` or `IN_PROGRESS`, releases every exclusivity grant of a terminated contract in `PENDING`, `ACTIVE`, or `CONFLICTED`, voids every draft invoice of a terminated contract, and voids every make-good credit of a terminated contract in `REQUESTED` or `APPROVED`. Hop three, caused by the deliverable cancellations, voids every evidence submission of a cancelled deliverable in `SUBMITTED` or `REJECTED`.

Assets are the sellable inventory. A `VenueAdmin` registers each asset with its owning `venue_id`, a `name` such as "Bowl LED Ribbon" or "Suite 12", an `asset_class` of `SIGNAGE`, `DIGITAL`, or `HOSPITALITY`, and its valuation basis: `rate_card_unit_cents`, the rate-card value per contracted unit used for provisional valuation; `avg_impressions_per_unit`, the audited average impressions per unit used for final valuation; and `cpm_cents`, the cost per thousand impressions in cents, the other input to final valuation. These rate and fee fields must be positive integers (`ERR_INVALID_AMOUNT`). An asset's `asset_status` starts `AVAILABLE`; retiring (`RETIRE`) moves it to `RETIRED`, and reinstatement (`REINSTATE`) moves it back. Retirement never disturbs deliverables already on the books — it only blocks attaching new ones, which is rejected with `ERR_ASSET_NOT_AVAILABLE`.

### 3.2. Reserving and Contesting Rights

Before exclusivity can be sold, the department records who already owns what. A `VenueAdmin` reserves a rights window with `venue_id`, a `holder` of `TEAM`, `VENUE`, or `LEAGUE`, a `category`, and the inclusive `first_season` and `last_season` span; the window's `window_status` starts `RESERVED`. Creation records the span as supplied — no check requires `first_season` to be no later than `last_season`. Activation (`ACTIVATE`) moves a reserved window to `ACTIVE`; release (`RELEASE`) moves a window from `RESERVED` or `ACTIVE` to `RELEASED`; and when the season epoch advances beyond a window's `last_season`, the system flips an active window to `EXPIRED`. Both `RELEASED` and `EXPIRED` are terminal.

League preemption is the sharp edge of this model. Activating a window whose `holder` is `LEAGUE` succeeds even where venue-side exclusivity already exists: every `ACTIVE` grant with the same venue and category whose season span overlaps the league window's span flips to `CONFLICTED`, and each affected grant's contract flips its `rights_status` to `CONTESTED`. When that league window is later released or expires, the sweep runs in reverse: each `CONFLICTED` grant whose only blocking active league window is this one returns to `ACTIVE`, and a contract whose last `CONFLICTED` grant has cleared returns to `CLEAR`.

Grants themselves are created by `SponsorshipSales` against a contract, with a `category` and an inclusive season span that must sit inside the contract's term — `first_season` no earlier than the contract's `term_first_season` and `last_season` no later than its `term_last_season`, otherwise `ERR_GRANT_OUTSIDE_TERM`. Term containment is the only window check at grant creation; the span's own ordering is not validated. A contract may hold at most one grant per category in `PENDING` or `ACTIVE` status; a second such grant for the same contract and category is rejected with `ERR_DUPLICATE_GRANT`. A new grant's `grant_status` starts `PENDING`.

Activation of a grant is a `VenueAdmin` action whose checks run in a fixed order. First, the grant's own state must permit activation and, for a `PENDING` grant, the owning contract must be `COUNTERSIGNED` — a violation is `ERR_INVALID_STATE`. Second, the league check: no `ACTIVE` `LEAGUE` rights window may overlap the same venue and category over the same seasons, otherwise `ERR_RIGHTS_CONFLICT`. Third, the exclusivity sweep: no other `ACTIVE` grant on the same venue and category may overlap the requested seasons, otherwise `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`. A `CONFLICTED` grant can likewise be activated — by the system when its blocking league window clears, or manually by a `VenueAdmin` — with the same checks, except that on the manual path from `CONFLICTED` the contract may be `COUNTERSIGNED` or `ACTIVE`; when reactivation leaves a contract with zero `CONFLICTED` grants, the contract's `rights_status` returns to `CLEAR`. Release is available from `PENDING`, `ACTIVE`, or `CONFLICTED`, whether by operator action or by contract termination or expiry: releasing an `ACTIVE` grant leaves the contract's `rights_status` unchanged, while releasing a `CONFLICTED` grant restores `CLEAR` if it was the contract's last contested grant.

### 3.3. From Term Sheet to Countersignature

A `SponsorshipSales` seller drafts a contract with `venue_id`, `sponsor_id`, a `title` such as "Stadium Naming Rights 2026-2028", the inclusive term from `term_first_season` through `term_last_season`, the season-one `base_fee_cents`, an `escalator_pct`, and an `escalator_mode` of `COMPOUND` or `SIMPLE`. A contract that renews a prior deal records its predecessor in `renewed_from_contract_id`. Creation validates the term window first — the first season must be no earlier than the venue's `current_season`, and the last season no earlier than the first, otherwise `ERR_SEASON_WINDOW_INVALID` — then requires the sponsor to be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`), and finally requires `base_fee_cents` to be a positive integer and the escalator zero or positive (`ERR_INVALID_AMOUNT`). A new contract's `contract_status` starts `DRAFT`, its `rights_status` starts `CLEAR`, and `scheduled_total_cents` is zero until countersignature.

The draft loop is deliberately cyclic. Proposing (`PROPOSE`) moves `DRAFT` to `PROPOSED` and again requires an `ACTIVE` sponsor (`ERR_SPONSOR_NOT_ACTIVE`); revising (`REVISE`) moves `PROPOSED` back to `DRAFT`; the pair may cycle any number of times. While the contract is `DRAFT`, the seller may edit its commercial terms — `title`, either term boundary, `base_fee_cents`, `escalator_pct`, or `escalator_mode` — applied as supplied, without re-running the creation-time term-window or amount validations; every successful edit increments the contract's `version`, which is exactly what the countersignature guard keys on.

Countersigning is the sponsor contact's act, and it is guarded in sequence: the caller's `X-User-ID` must equal the contract's `sponsor_id` (`ERR_FORBIDDEN`); the contract must be `PROPOSED` (`ERR_INVALID_STATE`); and the request's `expected_contract_version` must match the contract's current `version` (`ERR_STALE_CONTRACT_VERSION`, HTTP 412, per §2.11). On success the contract becomes `COUNTERSIGNED`, its `version` increments by one, and the billing schedule is generated in place.

That schedule runs in two pinned steps. First, the season fee: the season index of a season is its distance from `term_first_season` — zero for the first season of the term, one for the next, and so on. Under `COMPOUND`, the fee for a season is `base_fee_cents` multiplied by one-plus-`escalator_pct` raised to the power of the season index, rounded half-up to whole cents. Under `SIMPLE`, the fee is `base_fee_cents` multiplied by the quantity one plus `escalator_pct` times the season index, rounded half-up to whole cents. Each variant rounds exactly once at the end of its computation — there is no cumulative per-year rounding — and for a positive escalator, `SIMPLE` yields a strictly smaller fee than `COMPOUND` from a season index of two onward. The contract's `scheduled_total_cents` is then the sum of the season fees over every season of the term, both ends included, a sum of already-rounded whole-cent values. Second, the installment split: exactly three `DRAFT` invoices are created — `SIGNING` with `installment_seq` 1, `MID_SEASON` with `installment_seq` 2, and `POST_SEASON` with `installment_seq` 3. The signing installment's `amount_cents` is forty percent of the scheduled total, rounded half-up to whole cents; the mid-season installment is thirty percent of the scheduled total, rounded half-up; the post-season installment is whatever remains — the scheduled total minus the first two amounts — so the final installment absorbs the rounding remainder. Rounding all three lines independently could land a cent either side of the total; the pinned order — first line rounded, second line rounded, third line as remainder — is the contract. Each generated invoice records its `contract_id`, `installment_seq`, and `installment_label`, starts with `paid_cents` and `credits_applied_cents` at zero in `DRAFT` status, and carries an empty, append-only `payments` list.

Activation (`ACTIVATE`) moves `COUNTERSIGNED` to `ACTIVE` and is gated in pipeline order: no grant of the contract may still be `PENDING` or `CONFLICTED` (`ERR_INVALID_STATE`); the venue's `current_season` must not have passed `term_last_season` (`ERR_SEASON_CLOSED`); and the sponsor must be `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`). From `ACTIVE`, a contract can be suspended — either by a seller's explicit suspension (`SUSPEND`) or by the sponsor-level cascade — moving `ACTIVE` to `SUSPENDED`, and reinstated (`REINSTATE`) from `SUSPENDED` back to `ACTIVE` only while the sponsor is `ACTIVE` (`ERR_SPONSOR_NOT_ACTIVE`). Termination (`TERMINATE`) moves `ACTIVE` or `SUSPENDED` to the terminal `TERMINATED` state, whether triggered by a seller or by the sponsor block cascade — the block cascade is also the only path that can terminate a `COUNTERSIGNED` contract — and it runs the cascade of §3.1: deliverables in `SCHEDULED` or `IN_PROGRESS` cancel, which voids their open evidence; grants in `PENDING`, `ACTIVE`, or `CONFLICTED` release; draft invoices void; credits in `REQUESTED` or `APPROVED` void. Expiry, by contrast, is system-only: when the epoch advances past `term_last_season`, an `ACTIVE` or `SUSPENDED` contract becomes `EXPIRED`, releasing its `ACTIVE` and `CONFLICTED` grants — while deliverables, invoices, and credits are left untouched, because the term has completed naturally and its financial records stand. `EXPIRED`, like `TERMINATED`, is terminal.

### 3.4. The Activation Plan: Deliverables and Suite Nights

With the contract `ACTIVE`, an `ActivationManager` builds the season-by-season activation plan. Each deliverable names its `contract_id`, the `asset_id` delivering the element, the `season` it runs, a `unit_kind` of `GAME_DISPLAY`, `IMPRESSION_BLOCK`, or `SUITE_NIGHT`, and the `contracted_units` owed to the sponsor that season. `checkin_date` and `checkout_date` are required exactly when the unit kind is `SUITE_NIGHT` — omitting them there fails request-shape validation (`ERR_INVALID_REQUEST`) — and are otherwise optional, defaulting to unset.

Creation enforces its gates in the pipeline order of §2.12. The contract's rights must be `CLEAR` (`ERR_CONTRACT_RIGHTS_CONTESTED`). The season must then sit inside the contract's term (`ERR_SEASON_OUT_OF_TERM`) and must not already be closed — a season earlier than the venue's `current_season` is rejected with `ERR_SEASON_CLOSED` — and for suite nights the check-in date must not fall after the checkout date (`ERR_SEASON_WINDOW_INVALID`). Next, a suite night's buffered span must not intersect another suite booking on the same asset that has not been cancelled (`ERR_SUITE_DATE_CONFLICT`), evaluated with the buffer arithmetic of §2.5. Only then come the referential gates: the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the asset `AVAILABLE` (`ERR_ASSET_NOT_AVAILABLE`). Finally, `contracted_units` must be a positive integer (`ERR_INVALID_AMOUNT`). A successfully created deliverable starts with `approved_units` at zero; its `deliverable_status` is `IN_PROGRESS` when its `season` equals the venue's current epoch, and `SCHEDULED` for any later season.

An activation manager may cancel (`CANCEL`) a deliverable from `SCHEDULED` or `IN_PROGRESS`; cancellation is terminal and, as part of the same act, voids every evidence submission of that deliverable still in `SUBMITTED` or `REJECTED`. Cancellation is also how the contract-termination cascade reaches deliverables, with the same evidence voiding.

### 3.5. Season Close and the Make-Good Pipeline

The advance-season checkpoint is the department's operational heartbeat. When a `VenueAdmin` advances a venue, `current_season` increases by one and the venue's `version` increments; then, within the checkpoint, work proceeds in the fixed order of §2.4. Deliverables are evaluated first — within each contract, in `created_at` ascending order. Every `SCHEDULED` deliverable whose `season` equals the new epoch flips to `IN_PROGRESS`. Every deliverable whose `season` is now earlier than the new epoch and whose `approved_units` still fall short of `contracted_units` flips to `MISSED`, whether it was `SCHEDULED` or `IN_PROGRESS`, and missing an element auto-creates a make-good credit in `REQUESTED` status with its `contract_id` and `deliverable_id` set and its `requested_amount_cents` equal to the make-good formula below. Contract expiry runs next, releasing grants as §3.3 describes; rights-window expiry runs last, re-evaluating contested grants as §3.2 describes. Each phase processes its records in `created_at` ascending order.

The make-good formula is tiered on how much of the element was actually delivered. The missed units are `contracted_units` minus `approved_units`, which is positive for any `MISSED` deliverable. The missed value is the missed units multiplied by the asset's `rate_card_unit_cents`. The fulfillment fraction is `approved_units` divided by `contracted_units`, compared as an exact ratio rather than a rounded decimal. The multiplier is 1.00 when the fraction is at least 0.90, 1.25 when the fraction is at least 0.70 but below 0.90, and 1.50 when the fraction is below 0.70 — the tier boundaries are inclusive on the lower side, so a fraction of exactly 0.90 earns the 1.00 multiplier and a fraction of exactly 0.70 earns 1.25. The raw credit is the missed value multiplied by the multiplier, rounded half-up to whole cents. The cap is the season fee of the deliverable's `season` under the owning contract's escalator terms, computed exactly as in §3.3. The make-good amount is the lesser of the raw credit and the cap.

Activation managers can also request a credit manually for a missed element, supplying `contract_id`, `deliverable_id`, and a positive integer `requested_amount_cents` (`ERR_INVALID_AMOUNT` otherwise). The manual path validates only that both references exist and the amount is positive; the named deliverable is not required to be `MISSED`, nor to belong to the named contract. Both paths — automatic at season close and manual — land in `REQUESTED` with `approved_amount_cents` and `redeemed_against_invoice_id` unset, awaiting finance.

### 3.6. Proof of Performance and Four-Eyes Review

Evidence is how delivered units become recognized units. An `ActivationManager` submits proof of performance against an `IN_PROGRESS` deliverable, providing `deliverable_id`, the `units_claimed` this evidence proves — a positive integer (`ERR_INVALID_AMOUNT`) — and an `evidence_uri` pointing at the proof artifact, such as a photo log or a broadcast affidavit. A submission against a deliverable that is not open is rejected with `ERR_DELIVERABLE_NOT_OPEN`. The system records the caller as `submitted_by_user_id`, and the submission's `submission_status` starts `SUBMITTED` with `review_note` unset.

Review is segregated. The reviewer must be an `ActivationManager` whose `X-User-ID` differs from the submission's `submitted_by_user_id`; the same user reviewing their own submission is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval (`APPROVE`) runs its gates in pipeline order: the submission must be `SUBMITTED` (`ERR_INVALID_STATE`); the owning contract's rights must be `CLEAR` (`ERR_CONTRACT_RIGHTS_CONTESTED`); the four-eyes rule must hold; the approval must not over-deliver — `approved_units` plus `units_claimed` may not exceed `contracted_units` (`ERR_OVER_DELIVERY`); and the deliverable must still be `IN_PROGRESS` (`ERR_DELIVERABLE_NOT_OPEN`). On approval, the claimed units are added to the deliverable's `approved_units`, the reviewer's `review_note` is recorded on the submission, and when the approved units reach the contracted total the deliverable flips to `FULFILLED`, a terminal state.

Rejection (`REJECT`) enforces the same four-eyes rule, records the `review_note`, and moves the submission to `REJECTED`. From there it can be resubmitted (`RESUBMIT`) back to `SUBMITTED`, provided the deliverable is still `IN_PROGRESS` (`ERR_DELIVERABLE_NOT_OPEN`); resubmission replaces `evidence_uri` with the newly supplied value — the field is optional on resubmission, and when omitted the previous value is retained — replaces `submitted_by_user_id` with the acting user, and clears `review_note`, and the reject-resubmit loop may cycle any number of times. The four-eyes rule binds approval and rejection only — resubmission is the submitter's own correction path. Submissions still in `SUBMITTED` or `REJECTED` are voided by the system when their deliverable is cancelled or their contract is terminated; `APPROVED` and `VOIDED` are terminal.

### 3.7. Billing: Invoices, Payments, and Credit Redemption

Finance owns the installment ledger. A `FinanceManager` issues (`ISSUE`) a `DRAFT` invoice; issuance requires, in pipeline order, that the contract's rights be `CLEAR` (`ERR_CONTRACT_RIGHTS_CONTESTED`) and that the contract itself be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), and it flips the invoice to `ISSUED` and recomputes the contract's `receivable_cents`. A draft invoice can instead be voided (`VOID`) to `VOID` — by finance, or by the contract-termination cascade. An `ISSUED` or `PARTIALLY_PAID` invoice can be written off (`WRITE_OFF`) to `WRITTEN_OFF`, which recomputes `receivable_cents`; note the written-off balance remains inside the receivable, because `WRITTEN_OFF` belongs to the receivable status set of §2.8. `PAID`, `VOID`, and `WRITTEN_OFF` are terminal.

Payments are append-only sub-records on the invoice's `payments` list. Posting a payment requires the invoice to be `ISSUED` or `PARTIALLY_PAID` (`ERR_INVOICE_NOT_PAYABLE`), an `amount_cents` that is a positive integer (`ERR_INVALID_AMOUNT`), and an amount no greater than the invoice's remaining balance — its `amount_cents` minus `paid_cents` minus `credits_applied_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`). The posted sub-record captures a `payment_id`, the `amount_cents`, the `method`, an optional `external_ref`, the `posted_at` timestamp, and a `voided` flag that starts false. The invoice's `paid_cents` grows by the posted amount, and the invoice's status is re-derived: an `ISSUED` invoice becomes `PARTIALLY_PAID` when the paid and credited amounts are positive but short of the full `amount_cents`, or `PAID` when a single posting or redemption covers the full remaining balance; a `PARTIALLY_PAID` invoice becomes `PAID` when the running total completes the amount. The response to a posting carries `payment_id`, `invoice_id`, `amount_cents`, `paid_cents_after`, and the resulting `invoice_status`.

Voiding a payment is the compensation path. Voiding is accepted only while the invoice is `ISSUED`, `PARTIALLY_PAID`, or `PAID` and the named payment has not already been voided; either violation is `ERR_INVALID_STATE`, and an unknown `payment_id` on an existing invoice is `ERR_NOT_FOUND`. The sub-record's `voided` flag flips to true, the invoice's `paid_cents` falls by the voided amount, and the status is re-derived in reverse: a `PAID` invoice falls back to `PARTIALLY_PAID` when some balance remains covered, or all the way to `ISSUED` when nothing remains paid or credited, and a `PARTIALLY_PAID` invoice likewise returns to `ISSUED` when both the paid total and the credited total reach zero. The void response carries `payment_id`, `invoice_id`, `voided`, `paid_cents_after`, and `invoice_status`. Every posting and every void recomputes the contract's `receivable_cents`.

Make-good credits live their own lifecycle under finance. Approval (`APPROVE`) of a `REQUESTED` credit requires an `approved_amount_cents` input that is a positive integer (`ERR_INVALID_AMOUNT`) and that does not exceed the make-good cap computed for the linked deliverable (`ERR_CREDIT_EXCEEDS_CAP`); approval stamps `approved_amount_cents` on the credit and adds it to the contract's `make_good_outstanding_cents`. Declining (`DECLINE`) moves a `REQUESTED` credit to `DECLINED` with no ledger effect. Redemption (`REDEEM`) applies an `APPROVED` credit to the contract's oldest payable invoice: the target is selected from the credit's contract's invoices in `ISSUED` or `PARTIALLY_PAID` status by lowest `installment_seq`, with ties broken by earliest `created_at`, and an empty pool is rejected with `ERR_NO_PAYABLE_INVOICE` (HTTP 409). The approved amount must not exceed the selected invoice's remaining balance (`ERR_CREDIT_EXCEEDS_INVOICE_BALANCE`). Redemption stamps `redeemed_against_invoice_id` with the target's id, adds the approved amount to that invoice's `credits_applied_cents` — flipping the invoice to `PAID` if its remaining balance reaches zero — subtracts the amount from the contract's `make_good_outstanding_cents`, recomputes `receivable_cents`, and, as the sponsor-facing payoff, flips the linked deliverable from `MISSED` to the terminal `COMPED` state. A credit in `REQUESTED` or `APPROVED` can be voided (`VOID`), by finance or by the contract-termination cascade; voiding an `APPROVED` credit subtracts its approved amount from `make_good_outstanding_cents`, while voiding a `REQUESTED` credit touches no ledger. `REDEEMED`, `DECLINED`, and `VOIDED` are terminal.

### 3.8. Measurement, Sponsor Acknowledgement, and Renewal

After a season closes, the department proves value. An `ActivationManager` generates a valuation report for a `contract_id` and a `season`; the season must already be closed — strictly earlier than the venue's `current_season`, otherwise `ERR_SEASON_NOT_CLOSED` — and must lie within the contract's term. Generation snapshots four measures over the contract's deliverables for that season, excluding `CANCELLED` ones. `delivered_value_provisional_cents` sums, per deliverable, `approved_units` multiplied by the asset's `rate_card_unit_cents` — what the venue quoted. `delivered_value_final_cents` sums, per deliverable, `approved_units` multiplied by the asset's `avg_impressions_per_unit` multiplied by the asset's `cpm_cents` and divided by one thousand, each deliverable line rounded half-up to whole cents before the lines are summed — what the exposure was actually worth; for identical approved units, the two views differ whenever the impressions-based unit value differs from the rate-card value. `fulfillment_pct` divides the total approved units by the total contracted units across the same deliverable set, rounded half-up to four decimal places; when the reportable set is empty, the three monetary measures are zero and `fulfillment_pct` is 0.0. `make_good_due_cents` sums `approved_amount_cents` over the credits tied to those deliverables whose `credit_status` is `APPROVED` or `REDEEMED`. The report's `report_status` starts `DRAFT`; issuance (`ISSUE`) by an `ActivationManager` moves it to `ISSUED`, and acknowledgement (`ACKNOWLEDGE`) by the sponsor contact whose `X-User-ID` equals the report contract's `sponsor_id` (`ERR_FORBIDDEN` otherwise) moves it to the terminal `ACKNOWLEDGED`. The report lifecycle endpoint is shared between the two roles, with issuance reserved to `ActivationManager` and acknowledgement to `SponsorContact`.

The renewal pipeline tracks what happens at term end. A `SponsorshipSales` seller opens a renewal opportunity carrying `contract_id` and a positive integer `proposed_fee_cents` (`ERR_INVALID_AMOUNT`) as the proposed season-one base fee for the renewal term. A contract may have at most one open opportunity — open means a `stage` of `IDENTIFIED`, `PROPOSED`, or `NEGOTIATING` — and a duplicate is rejected with `ERR_DUPLICATE_OPEN_OPPORTUNITY`; the source contract must be `ACTIVE` or `EXPIRED` (`ERR_RENEWAL_CONTRACT_STATE`), and under the pipeline order of §2.12 the duplicate check is evaluated before the source-state check. A new opportunity starts at `IDENTIFIED` with `resulting_contract_id` unset.

From there the stage flow is a negotiation loop. Proposing (`PROPOSE`) moves `IDENTIFIED` to `PROPOSED`; opening negotiation (`OPEN_NEGOTIATION`) moves `PROPOSED` to `NEGOTIATING`; and countering moves `NEGOTIATING` back to `PROPOSED` with revised terms — the counter request carries the replacement `proposed_fee_cents`, which must be a positive integer (`ERR_INVALID_AMOUNT`), and `expected_opportunity_version`, which must match the opportunity's current `version` (`ERR_STALE_OPPORTUNITY_VERSION`, HTTP 412, per §2.11); the guards fire in the order stage legality, version freshness, then fee positivity; a successful counter replaces the fee and increments the opportunity's `version`, and the propose-negotiate-counter loop may cycle. Marking won (`MARK_WON`) from `PROPOSED` or `NEGOTIATING` creates the renewal contract in `DRAFT`: `venue_id`, `sponsor_id`, `title`, `escalator_pct`, and `escalator_mode` are copied from the source contract; the new `term_first_season` is the source's `term_last_season` plus one; the new `term_last_season` extends that by the source term's length, preserving the original duration; the new `base_fee_cents` is the opportunity's `proposed_fee_cents`; and the new contract's `renewed_from_contract_id` points back at the source, while the opportunity records the new contract in `resulting_contract_id`. Marking lost (`MARK_LOST`) is available from `IDENTIFIED`, `PROPOSED`, or `NEGOTIATING`; both `WON` and `LOST` are terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; operations that modify an existing resource — including lifecycle transitions, countersignature, counters, payment posting and voiding, and the season-advance checkpoint — return `200 OK`. Lifecycle transition endpoints take an `action` field in the request body naming the verb; the state machines of §3 pin which verbs are legal from which states. The season-advance checkpoint and the payment-void endpoint declare no request fields, so any supplied body field is undeclared and rejected under §2.12. List endpoints accept the pagination parameters of §2.3 plus optional equality filters on the resource's own fields (for example `venue_id`, `sponsor_id`, `contract_id`, `asset_id`, `deliverable_id`, `season`, `category`, `holder`, `renewed_from_contract_id`, `redeemed_against_invoice_id`, `resulting_contract_id`, `asset_class`, `asset_status`, `window_status`, `contract_status`, `grant_status`, `deliverable_status`, `submission_status`, `credit_status`, `invoice_status`, `installment_label`, `report_status`, and `stage`). Readers should reconstruct full request and response bodies from the §3 narratives; this table is deliberately minimal.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue; `current_season` initialized to 2026 | VenueAdmin |
| GET | `/venues/{venue_id}` | Get a venue, including its season epoch | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/venues/{venue_id}/advance-season` | Advance the season epoch and run the season-close cascades | VenueAdmin |
| POST | `/sponsors` | Create a sponsor account (starts `PROSPECT`) | SponsorshipSales |
| GET | `/sponsors/{sponsor_id}` | Get a sponsor | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/sponsors/{sponsor_id}/transition` | Sponsor lifecycle: QUALIFY, SUSPEND, REINSTATE, BLOCK | SponsorshipSales |
| POST | `/assets` | Register an inventory asset with its valuation basis | VenueAdmin |
| GET | `/assets/{asset_id}` | Get an asset | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/assets` | List assets with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/assets/{asset_id}/transition` | Asset lifecycle: RETIRE, REINSTATE | VenueAdmin |
| POST | `/rights-windows` | Reserve a team/venue/league rights window for a category over seasons | VenueAdmin |
| GET | `/rights-windows/{window_id}` | Get a rights window | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/rights-windows` | List rights windows with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/rights-windows/{window_id}/transition` | Window lifecycle: ACTIVATE, RELEASE | VenueAdmin |
| POST | `/contracts` | Create a contract in `DRAFT` | SponsorshipSales |
| GET | `/contracts/{contract_id}` | Get a contract (SponsorContact: own contracts only) | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/contracts` | List contracts with optional filters (SponsorContact: scoped to own sponsor) | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| PATCH | `/contracts/{contract_id}` | Edit commercial terms while `DRAFT`; bumps `version` | SponsorshipSales |
| POST | `/contracts/{contract_id}/transition` | Contract lifecycle: PROPOSE, REVISE, ACTIVATE, SUSPEND, REINSTATE, TERMINATE | SponsorshipSales |
| POST | `/contracts/{contract_id}/countersign` | Sponsor countersigns a `PROPOSED` contract; generates schedule and installments | SponsorContact |
| POST | `/exclusivity-grants` | Grant category exclusivity to a contract over a season window inside its term | SponsorshipSales |
| GET | `/exclusivity-grants/{grant_id}` | Get a grant | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/exclusivity-grants` | List grants with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/exclusivity-grants/{grant_id}/transition` | Grant lifecycle: ACTIVATE, RELEASE | VenueAdmin |
| POST | `/deliverables` | Add an activation element to an `ACTIVE` contract for a season | ActivationManager |
| GET | `/deliverables/{deliverable_id}` | Get a deliverable | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/deliverables` | List deliverables with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/deliverables/{deliverable_id}/transition` | Deliverable lifecycle: CANCEL | ActivationManager |
| POST | `/evidence-submissions` | Submit proof-of-performance evidence against an `IN_PROGRESS` deliverable | ActivationManager |
| GET | `/evidence-submissions/{submission_id}` | Get an evidence submission | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/evidence-submissions` | List evidence submissions with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/evidence-submissions/{submission_id}/transition` | Evidence review: APPROVE, REJECT, RESUBMIT | ActivationManager |
| POST | `/make-good-credits` | Request a make-good credit for a missed deliverable | ActivationManager |
| GET | `/make-good-credits/{credit_id}` | Get a make-good credit | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/make-good-credits` | List make-good credits with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/make-good-credits/{credit_id}/transition` | Credit lifecycle: APPROVE, DECLINE, REDEEM, VOID | FinanceManager |
| GET | `/invoices/{invoice_id}` | Get an invoice including its payment sub-records | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/invoices` | List invoices with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/invoices/{invoice_id}/transition` | Invoice lifecycle: ISSUE, VOID, WRITE_OFF | FinanceManager |
| POST | `/invoices/{invoice_id}/payments` | Post a payment against an `ISSUED` or `PARTIALLY_PAID` invoice | FinanceManager |
| POST | `/invoices/{invoice_id}/payments/{payment_id}/void` | Void a posted payment and re-derive the invoice status | FinanceManager |
| POST | `/valuation-reports` | Generate the season measurement report (provisional vs final value) | ActivationManager |
| GET | `/valuation-reports/{report_id}` | Get a valuation report | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/valuation-reports` | List valuation reports with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/valuation-reports/{report_id}/transition` | Report lifecycle: ISSUE, ACKNOWLEDGE | ActivationManager, SponsorContact |
| POST | `/renewal-opportunities` | Open a renewal/upsell opportunity for an `ACTIVE` or `EXPIRED` contract | SponsorshipSales |
| GET | `/renewal-opportunities/{opportunity_id}` | Get a renewal opportunity | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| GET | `/renewal-opportunities` | List renewal opportunities with optional filters | VenueAdmin, SponsorshipSales, ActivationManager, FinanceManager, SponsorContact |
| POST | `/renewal-opportunities/{opportunity_id}/transition` | Pipeline stage moves: PROPOSE, OPEN_NEGOTIATION, MARK_WON, MARK_LOST | SponsorshipSales |
| POST | `/renewal-opportunities/{opportunity_id}/counter` | Issue revised terms from `NEGOTIATING` back to `PROPOSED` | SponsorshipSales |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the §2 and §3 narratives where the guarded workflow lives. Requests to undefined paths, and requests to a defined path with an unsupported method, are rejected with `ERR_NOT_FOUND` (404); `ERR_INTERNAL` (500) covers any unexpected server failure.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RIGHTS_CONFLICT` | 409 Conflict |
| `ERR_CONTRACT_RIGHTS_CONTESTED` | 409 Conflict |
| `ERR_SEASON_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_SEASON_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_SEASON_CLOSED` | 422 Unprocessable Entity |
| `ERR_SEASON_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_GRANT_OUTSIDE_TERM` | 422 Unprocessable Entity |
| `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_GRANT` | 409 Conflict |
| `ERR_SUITE_DATE_CONFLICT` | 409 Conflict |
| `ERR_OVER_DELIVERY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_OPEN_OPPORTUNITY` | 409 Conflict |
| `ERR_SPONSOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_ASSET_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_DELIVERABLE_NOT_OPEN` | 409 Conflict |
| `ERR_RENEWAL_CONTRACT_STATE` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_CREDIT_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_CREDIT_EXCEEDS_INVOICE_BALANCE` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_NO_PAYABLE_INVOICE` | 409 Conflict |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_OPPORTUNITY_VERSION` | 412 Precondition Failed |
| `ERR_INTERNAL` | 500 Internal Server Error |

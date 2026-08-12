# Paint Store Contractor Account API — Product Requirements Document

## 1. Introduction

A regional paint retailer serving professional contractors operates on relationships that span years: a painting crew opens a house account, negotiates pricing that improves with volume, tints product to match a customer's existing wall color, schedules jobsite deliveries around crew availability, and expects a year-end rebate that reflects every gallon actually kept. This document specifies the API that backs those counter, credit, and compliance operations — contractor accounts with pricing tiers and credit limits, job accounts that track spend against a site budget, a tint-formula library with a color-match workflow, VOC regulation enforced per jurisdiction, specification sheets written for architects with pull-through measurement, a loyalty program with earning and clawback, volume rebates settled per period, and a mistint resale rack with decaying prices.

Two forces shape the design. First, everything financial is derived: balances, tier standing, pull-through percentages, and rebate amounts are never entered by hand but recomputed from ledger events, so the rules that govern when and how those recomputations happen are as much a part of the contract as the endpoints themselves. Second, compliance is temporal: VOC limits, delivery windows, bulletin effective dates, and rebate periods are all evaluated against a single logical clock rather than the server's wall clock, which makes every time-dependent rule deterministic and testable. Implementers should read Section 2 for the system-wide contracts, Section 3 for the business workflows in which those contracts come alive, and Sections 4 and 5 for the endpoint and error reference tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the principal acts. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). A request whose role is authenticated but not permitted for the addressed endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `CorporateAdmin` — head-office operator: owns the catalog (jurisdictions, VOC rules, products, bulletins), contractor account administration, tier evaluation, rebate settlement, spec-sheet approval, formula retirement, and the logical clock.
- `StoreManager` — store operator: owns delivery scheduling, dispatch, completion, and failure, mistint write-off, and shares job-account lifecycle actions with the owning contractor.
- `StoreAssociate` — counter operator: creates orders, takes payments, processes returns, runs color-match intake and proposals, and creates and sells mistint listings.
- `SpecWriter` — specification services: writes, submits, and revises spec sheets for architects; cannot approve them.
- `Contractor` — a contractor account holder acting on its own account, jobs, orders, color-match requests, and rebate statements.

The first four roles — `CorporateAdmin`, `StoreManager`, `StoreAssociate`, and `SpecWriter` — are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it against any resource's `id`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `ContractorAccount`; ownership checks on any resource that references a `ContractorAccount` compare the resource's foreign-key field to `X-User-ID`. That ownership chain runs directly on contractor-facing resources and indirectly through the resource's `contractor_account_id` chain via job account, order, rebate statement, or color-match request; a `Contractor` caller whose `X-User-ID` does not match the owning account is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). On create endpoints whose payload names `contractor_account_id` — job-account creation, order creation, and loyalty redemption — that payload value is the ownership anchor: a `Contractor` caller must name its own account id, otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`. On list endpoints for contractor-owned resources (job accounts, orders, order lines, return records, deliveries, color-match requests, rebate statements, loyalty transactions), a `Contractor` caller's page is implicitly restricted to rows its own account owns through the same chain; a filter value naming another contractor's account, or naming an existing resource owned by another contractor on the filters that take a resource id (`job_account_id`, `order_id`, `order_line_id`), is rejected with `ERR_NOT_RESOURCE_OWNER`, while a filter naming a nonexistent resource simply narrows the page to the rows that match.

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

List endpoints accept two query parameters. `limit` controls the page size: it defaults to 10, must be at least 1, and may not exceed 100. `offset` controls how many rows are skipped and defaults to 0. Both parameters must be supplied as base-10 integers — a non-integer value, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_VALIDATION` (400). List responses are always sorted by `created_at` ascending; rows created at the same logical instant are ordered by insertion sequence, earliest inserted first. The `meta` object of a list response carries `limit`, `offset`, `total_count` (the full count of matching rows), and `has_more` (whether rows remain beyond the returned page).

### 2.4. The Logical Clock

All time in the system is read from a single **logical clock**, never from the server's wall clock. At startup the logical clock reads exactly 2026-05-01T00:00:00Z. Every server-produced timestamp — `created_at`, `paid_at`, `dispatched_at`, `delivered_at`, `published_at`, `effected_at`, `approved_at`, rebate period math, mistint decay windows, and delivery-window checks — derives from this clock. An admin-only test-driving capability advances the logical clock to a supplied instant: the request carries `to_iso8601`, succeeds with HTTP 204, mutates no entity, and is restricted to `CorporateAdmin`. The supplied instant may be earlier or later than the current value; no monotonicity is enforced. Once set, the clock holds the supplied value until set again; the server never falls back to wall-clock time.

### 2.5. Common Resource Properties

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Unless stated otherwise, every resource also carries `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer that increments by 1 on every mutation of that resource). At creation `version` is 1 and `updated_at` equals `created_at`. Two ledger entities are exceptions: a return record and a loyalty transaction are append-only events and carry only `id` and `created_at` — both `updated_at` and `version` are absent from them.

### 2.6. Money, Rounding, and Percentages

All monetary amounts are integer cents; no fractional cents are stored. Whenever a computation must produce cents from a non-integer intermediate, the result is **rounded half up** to the nearest whole cent, and each computation pins exactly where that rounding happens (per unit price, per return event, per cap, or once at the end) — the pinned rounding points appear with the workflows in Section 3. Percentages reported to clients, such as spec pull-through, are numbers with 2 decimal places, also rounded half up. Sales tax is levied at 8.25 percent (825 basis points) of the discounted merchandise subtotal. Points and quantities are integers.

### 2.7. Optimistic Concurrency Control on the Contractor Account

Two write operations are guarded by optimistic concurrency control on the contractor account: updating a contractor account's mutable fields, and creating an order. Both requests must carry `expected_contractor_account_version`, a non-optional field holding the account `version` the caller last observed. If that value does not match the account's current `version` — because another write, such as an order creation, a payment, or a tier evaluation, has advanced the account since — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The check exists because domain state alone would let both writes through: the account stays `ACTIVE`, so nothing else prevents a caller from overwriting changes it never observed, or from pricing an order against a tier and balance basis that has already moved. Endpoints not named here take no version field at all.

### 2.8. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and within the pipeline the first failing check wins — its error masks any later failures the request would also have triggered. The stages, in order:

1. **Authentication**: the `X-User-ID` and `X-User-Role` headers are present and the role is known; otherwise `ERR_AUTH_REQUIRED` (401).
2. **Authorization**: the role is permitted for the endpoint per the role matrix; otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Ownership**: a `Contractor` caller owns the addressed resource per the identity rule of §2.1; otherwise `ERR_NOT_RESOURCE_OWNER` (403).
4. **Path existence**: every path identifier resolves to an existing resource, validated left-to-right along the URL — an unresolved earlier segment means later segments are never examined; otherwise `ERR_NOT_FOUND` (404).
5. **Body references**: every request-body foreign key — `contractor_account_id`, `job_account_id`, `jurisdiction_id`, `product_id`, `formula_id`, `spec_line_id`, `replacement_product_id`, `order_id`, `sold_to_contractor_account_id` — resolves to an existing resource; otherwise `ERR_REFERENCE_NOT_FOUND` (422). When a body carries several foreign keys, they are resolved in the order the endpoint's Section 3 narrative names them, and the first unresolvable one wins.
6. **Shape**: required fields are present, types match, enum members are valid, and range constraints hold — `quantity` greater than zero, `voc_gpl` greater than zero, `max_voc_gpl` greater than zero, `specified_qty` greater than zero, `credit_limit_cents` at least zero, `cost_basis_cents` at least zero, `budget_cap_cents` at least zero when not null, `window_end` after `window_start`, `period_end` after `period_start`; otherwise `ERR_VALIDATION` (400).
7. **Concurrency**: the OCC check of §2.7, where applicable; otherwise `ERR_STALE_VERSION` (412).
8. **State**: domain state preconditions. Where a dedicated code exists it is raised in preference to the generic one — `ERR_ACCOUNT_SUSPENDED`, `ERR_JOB_NOT_OPEN`, `ERR_ORDER_NOT_PAYABLE`, `ERR_ORDER_NOT_CANCELLABLE`, `ERR_ORDER_NOT_REFUNDABLE`, `ERR_DELIVERY_NOT_DISPATCHABLE`, `ERR_DELIVERY_NOT_EN_ROUTE`, `ERR_SPEC_NOT_REVIEWABLE`, `ERR_SPEC_NOT_REVISABLE`, `ERR_MATCH_NOT_REVIEWABLE` (all 409). Any state-machine precondition without a dedicated code — a submit not from `DRAFT`, a proposal not from `SUBMITTED` or `REVISION_REQUESTED`, a finalize not from `ACCRUED`, a dispute not from `FINALIZED`, a resolve-dispute not from `DISPUTED`, a rebate payout not from `FINALIZED`, a publish not from `DRAFT`, a take-effect not from `PUBLISHED`, a formula retire not from `ACTIVE`, a mistint mark-sold or write-off not from `LISTED`, a job hold not from `OPEN`, a resume not from `ON_HOLD`, a completion not from `OPEN` or `ON_HOLD` or with open work outstanding, an account suspend not from `ACTIVE`, a reinstate not from `SUSPENDED`, an abandon not from `SUBMITTED`, `PROPOSED`, or `REVISION_REQUESTED` — is rejected with `ERR_INVALID_STATE` (409).
9. **Business rules**, evaluated in four ordered families: safety first (VOC compliance, `ERR_VOC_LIMIT_EXCEEDED`), then temporal rules (delivery window and buffer, VOC-rule overlap, bulletin effective date, rebate period validity and overlap), then constraints (SKU and jurisdiction-code uniqueness, empty spec, iteration exhaustion, tintability, the custom-tint no-return rule, return quantity), then referential rules (discontinued product, retired formula, formula/product mismatch, spec-line mismatch, job-account mismatch, bulletin replacement validity), and finally fiscal caps (credit limit, budget cap, points balance). Within an endpoint, a failure in an earlier family masks every later one.

### 2.9. State Machines, Cascades, and Version Semantics

Most entities in this system have a lifecycle, and lifecycle mutations follow a consistent discipline: the transition checks its preconditions, applies its state change, performs any documented side effects, increments the mutated entity's `version` by 1, and refreshes `updated_at`. Several operations mutate more than one entity in a single cascade — a discontinuation bulletin hops from product to formulas to spec lines to spec sheets; a delivery dispatch hops from the delivery to its order; a return hops from the return record to the order line, the order, the loyalty ledger, the job account, and the contractor account. Every hop of every cascade is spelled out with the owning workflow in Section 3, and every entity mutated along the way takes its own `version` increment. Fields described as "recomputed" or "computed" — balances, spent totals, pull-through percentages, order totals — are derived from underlying rows and are kept in sync immediately whenever a contributing event lands; they are never stale snapshots and never client-writable.

### 2.10. Half-Open Time Windows and Adjacency

Three kinds of time window recur, and all three use half-open semantics: the start instant is included, the end instant is excluded. A VOC rule is effective from `effective_from` (inclusive) until `effective_to` (exclusive), with a null `effective_to` meaning open-ended. A rebate statement covers [`period_start`, `period_end`). A delivery occupies [`window_start`, `window_end`). Overlap rules follow from the same semantics: two windows that merely touch — one ending exactly when the other begins — are adjacent, not overlapping, and are allowed unless a workflow says otherwise. The delivery-scheduling buffer rule is the one deliberate exception: mere adjacency is *not* sufficient there, as §3.8 explains.

## 3. Business Logic & Workflows

### 3.1. Contractor Accounts: Enrollment, Standing, and Tier Evaluation

A `CorporateAdmin` enrolls a contracting company by supplying its legal `company_name` and a `credit_limit_cents` — the maximum outstanding (unpaid) order total the house will carry for that account, which must be at least zero. A new account starts with `status` `ACTIVE`, `tier` `STANDARD`, and all computed balances at zero. Reading an account returns these derived figures alongside the inputs: `outstanding_balance_cents`, the sum of `total_cents` over the account's orders whose `payment_status` is `UNPAID` and whose `fulfillment_status` is not `CANCELLED` (cancellation drops the order out of the unpaid set); `loyalty_points_balance`, the sum of `points_delta` over every loyalty transaction posted to the account (the balance is allowed to go negative after a clawback); `ytd_net_volume_cents`, the merchandise basis for tier standing — the sum of `subtotal_cents` over the account's orders with `payment_status` in `PAID`, `PARTIALLY_REFUNDED`, or `REFUNDED` whose `paid_at` falls no earlier than January 1 of the logical clock's current calendar year and no later than the current clock instant, minus the sum of `refund_merchandise_cents` over those orders' return records; and `lifetime_rebate_paid_cents`, the sum of `payable_cents` over the account's statements that have reached `PAID`.

Account maintenance is guarded twice over. A `CorporateAdmin` may patch `company_name` and/or `credit_limit_cents`, but the request must present `expected_contractor_account_version` matching the account's current `version`, or it fails with `ERR_STALE_VERSION` as described in §2.7; a successful patch increments `version`. Separately, a `CorporateAdmin` may suspend an account — `ACTIVE` to `SUSPENDED` — or reinstate it — `SUSPENDED` to `ACTIVE` — each requiring the corresponding source state (otherwise `ERR_INVALID_STATE`) and each bumping `version` and refreshing `updated_at`. A `SUSPENDED` account is barred from new financial commitments: creating an order for it, paying one of its orders, redeeming its loyalty points, or scheduling a delivery for one of its jobs is rejected with `ERR_ACCOUNT_SUSPENDED` (HTTP 409).

Tier standing is recomputed on demand when a `CorporateAdmin` triggers tier evaluation for an account. The evaluation recomputes `ytd_net_volume_cents` at that instant and assigns `tier` by inclusive thresholds: `PLATINUM` when the volume reaches 40,000,000 cents ($400,000), otherwise `GOLD` when it reaches 15,000,000 cents ($150,000), otherwise `SILVER` when it reaches 5,000,000 cents ($50,000), otherwise `STANDARD`. A volume exactly equal to a threshold earns that tier. The tier drives both the line-pricing discount of §3.6 and the loyalty multiplier of §3.7; `UNPAID` and `CANCELLED` orders never count toward it. The account's `version` increments when the evaluation changes the tier.

### 3.2. Job Accounts and Site Budget Discipline

Work for a contractor is organized into job accounts, one per site. A `StoreAssociate` or the owning `Contractor` creates a job account by naming its `contractor_account_id`, the `jurisdiction_id` of the delivery site (VOC rules are enforced against that jurisdiction), a human-readable `job_name`, the `site_address`, and optionally `budget_cap_cents` — a spend cap that must be at least zero when supplied and that means "uncapped" when null. A job account opens in `status` `OPEN` with `spent_cents` at zero.

`spent_cents` is the job's running spend: the sum of `total_cents` minus `refunded_cents` over the job's orders whose `payment_status` is `PAID` or `PARTIALLY_REFUNDED`. `UNPAID` orders contribute nothing, and fully `REFUNDED` orders net to zero and drop out of the set. The figure is recomputed whenever an order of the job is paid, returned against, or cancelled. When a new order is created against the job, the cap is enforced at that moment: `spent_cents` plus the new order's `total_cents` must not exceed `budget_cap_cents`, or the create fails with `ERR_BUDGET_CAP_EXCEEDED` (HTTP 422); the check is skipped entirely for an uncapped job.

The job lifecycle is shared between the owning `Contractor` and any `StoreManager`. Placing a job on hold moves `OPEN` to `ON_HOLD`; resuming moves `ON_HOLD` back to `OPEN`. Completing a job moves either `OPEN` or `ON_HOLD` to the terminal `COMPLETE`, but only when no order of the job still has `fulfillment_status` `PENDING` or `OUT_FOR_DELIVERY` and no delivery of the job is still `SCHEDULED` or `EN_ROUTE` — a job with open work cannot be closed out. Each transition bumps the job's `version`; a transition attempted from the wrong source state, or a completion with open orders or deliveries outstanding, is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Catalog Governance: Products, VOC Regulation, and Discontinuation

The catalog begins with jurisdictions: a `CorporateAdmin` registers each one with a `code` (unique across jurisdictions — a duplicate is rejected with `ERR_JURISDICTION_CODE_EXISTS`, HTTP 409) and a display `name`. Against each jurisdiction, VOC rules cap the volatile-organic-compound content of coatings: a rule carries its `jurisdiction_id`, a `category` of `FLAT`, `NON_FLAT`, or `INDUSTRIAL_MAINTENANCE`, a `max_voc_gpl` limit in grams per liter (greater than zero, and an inclusive bound — a product at exactly the limit is compliant), an `effective_from` instant (inclusive), and an optional `effective_to` (exclusive; null means open-ended). Two rules for the same jurisdiction-and-category pair may not have overlapping windows under the half-open semantics of §2.10; adjacency — one rule's `effective_from` landing exactly on another's `effective_to` — is allowed. An overlapping create is rejected with `ERR_VOC_RULE_OVERLAP` (HTTP 409).

Products are created by a `CorporateAdmin` with a `sku` (unique across products, else `ERR_SKU_EXISTS`, HTTP 409), a `name`, a coating `category` from the same three values used for VOC lookup, a `voc_gpl` content in grams per liter (greater than zero), a `list_price_cents` per unit before any discount (at least zero), and a `tintable` flag saying whether the product accepts custom tint formulas. A product is `ACTIVE` from creation until a discontinuation bulletin takes effect against it. A `CorporateAdmin` may patch a product's `name`, `list_price_cents`, `voc_gpl`, or `tintable`, which increments the product's `version`. Discontinuation sets the product's `status` to the terminal `DISCONTINUED` and records the migration target in `replacement_product_id` — but only through the bulletin workflow, never directly.

A discontinuation starts as a `DRAFT` bulletin created by a `CorporateAdmin`, naming the `product_id` being discontinued, the `replacement_product_id` customers should migrate to, a `title`, and an `effective_date` — the earliest logical-clock instant at which the bulletin may take effect. Publishing moves `DRAFT` to `PUBLISHED` and stamps `published_at` — null until that moment — from the logical clock; publish validates the replacement — it must be non-null, different from the subject product, an existing `ACTIVE` product, and of the same coating category — and any violation is rejected with `ERR_BULLETIN_REPLACEMENT_INVALID` (HTTP 422), while a publish attempted from a state other than `DRAFT` draws `ERR_INVALID_STATE`. Taking effect moves `PUBLISHED` to `EFFECTIVE`, allowed only once the logical clock has reached `effective_date` (attempting it earlier yields `ERR_BULLETIN_NOT_YET_EFFECTIVE`, HTTP 422). Take-effect fires a four-hop cascade: **hop 1** transitions the subject product `ACTIVE` to `DISCONTINUED` and copies the bulletin's replacement into the product's `replacement_product_id`; **hop 2**, caused by the product mutation itself, retires every `ACTIVE` tint formula of that product and flags every spec line referencing that product on a sheet whose `status` is `SUBMITTED` or `APPROVED` by setting its `obsoleted` flag true; **hop 3**, caused by the spec-line mutations, pushes every `APPROVED` sheet holding at least one newly obsoleted line into `NEEDS_REVISION` (see §3.5); and the bulletin itself stamps `effected_at` — likewise null until take-effect — from the logical clock. Each mutated entity takes its own `version` increment. Orders and deliveries already created are grandfathered: discontinuation blocks only *new* order lines and *new* spec approvals that reference the product.

### 3.4. Tint Formulas and the Color-Match Counter Workflow

A tint formula records how to color a base product: its `product_id`, a `color_code` such as "SW 7008", a display `name`, and `shots` — a list of colorant shots, each pairing a `colorant_code` with an `ounces_128ths` amount. Formulas carry a per-(product, color) `revision` sequence starting at 1: when a `StoreAssociate` or `CorporateAdmin` creates a formula for a `(product_id, color_code)` pair that already has an `ACTIVE` formula, the prior formula is retired to `RETIRED` and the new formula's `supersedes_formula_id` points at it; the new formula's `revision` is the prior maximum plus one, or 1 for the first formula of the pair — and a first formula, having no predecessor, carries a null `supersedes_formula_id`. Formulas created directly this way have `source` `LIBRARY`. A `CorporateAdmin` may also retire a formula manually — `ACTIVE` to `RETIRED` — and formulas are retired automatically by product discontinuation (§3.3) or by color-match withdrawal (below). Every retirement increments the formula's `version`.

The color-match workflow handles a contractor who brings in a physical sample. A `StoreAssociate` opens a request naming the `contractor_account_id`, the base `product_id` the sample should be matched into, and a free-text `sample_reference`; the request starts `SUBMITTED` with `iteration_count` zero and `formula_id` null. The associate then attaches a proposal — supplying the proposal's `color_code`, `name`, and `shots` — which moves the request from `SUBMITTED` to `PROPOSED`, or from `REVISION_REQUESTED` to `PROPOSED`. Either proposal creates a new tint formula on the request's product with `source` `COLOR_MATCH`, `status` `ACTIVE`, and the same supersede semantics as library creation (any prior `ACTIVE` formula for the pair is retired with the supersedes link); the request's `formula_id` is set to the new formula and `iteration_count` increments by 1. The proposal endpoint answers HTTP 201 with the updated request — not the new formula — in `data`. A proposal attempted from any other state is rejected with `ERR_INVALID_STATE`.

From `PROPOSED`, the owning `Contractor` decides. Approving moves the request to the terminal `APPROVED` and leaves the proposed formula `ACTIVE` and orderable. Requesting a revision moves `PROPOSED` to `REVISION_REQUESTED`, retiring the formula referenced by `formula_id` — the rejected proposal is withdrawn — but only while `iteration_count` is still below 3 (the match-iteration cap); a revision request at the cap is rejected with `ERR_MATCH_ITERATION_EXHAUSTED` (HTTP 422). An approve or revision request aimed at a request not in `PROPOSED` is rejected with `ERR_MATCH_NOT_REVIEWABLE` (HTTP 409), and that state check fires before the iteration cap is examined. Either the associate or the owning contractor may abandon the request from `SUBMITTED`, `PROPOSED`, or `REVISION_REQUESTED`, moving it to the terminal `ABANDONED`; abandoning from `PROPOSED` additionally retires the proposed formula, while abandoning from `SUBMITTED` or `REVISION_REQUESTED` — states in which no live proposal is attached — retires nothing. Every request transition increments the request's `version`.

### 3.5. Specification Sheets and Pull-Through Tracking

Specification services writes spec sheets so that an architect's project calls out this retailer's products. A `SpecWriter` creates a sheet in `DRAFT` with a `project_code`, the free-text `architect_name` the spec is written for, a `title`, and `lines` — each line naming a `product_id` and a `specified_qty` greater than zero. The created spec lines are stamped with the owning sheet's `spec_sheet_id` and start with `obsoleted` false.

Submitting moves `DRAFT` to `SUBMITTED` and requires at least one line; an empty sheet is rejected with `ERR_SPEC_EMPTY` (HTTP 422), and a submit from any other state with `ERR_INVALID_STATE`. Review belongs to `CorporateAdmin`: approving moves `SUBMITTED` to `APPROVED`, rejecting moves `SUBMITTED` to `REJECTED`, and either action attempted on a sheet not in `SUBMITTED` is rejected with `ERR_SPEC_NOT_REVIEWABLE` (HTTP 409). Approval is a version-pinning gate: every line's product must still be `ACTIVE`, so a sheet referencing a discontinued product cannot be approved and fails with `ERR_PRODUCT_DISCONTINUED` (HTTP 422) — the sheet's live product references are pinned at approval. A successful approval stamps `approved_at` from the logical clock and enforces single-approval-per-project: at most one sheet per `project_code` may be `APPROVED` at any time, so any *other* `APPROVED` sheet for the same project transitions `APPROVED` to the terminal `SUPERSEDED`, and the newly approved sheet's `supersedes_spec_sheet_id` records that sheet's id (null when none existed). Rejection records the payload's `reason` into `rejection_reason`.

Revision is the `SpecWriter`'s repair path: from `REJECTED` or from `NEEDS_REVISION`, revising returns the sheet to `DRAFT` and atomically replaces its entire line set with the payload's `lines` — old lines are deleted and new lines are created with `obsoleted` false (on the `REJECTED` path the `rejection_reason` is also cleared; on the `NEEDS_REVISION` path this is the migration route, where the author substitutes the bulletin's replacement product). Nothing else on the sheet is reset: `approved_at` and `supersedes_spec_sheet_id` carry over unchanged. A revise attempted from any other state is rejected with `ERR_SPEC_NOT_REVISABLE` (HTTP 409). A sheet can also reach `NEEDS_REVISION` without human action: when a discontinuation bulletin obsoletes one of its lines while the sheet is `APPROVED` (§3.3, hop 3), the sheet itself transitions `APPROVED` to `NEEDS_REVISION`.

Pull-through measures how much of a spec actually gets bought through the store. Each spec line tracks two computed counters: `ordered_qty`, the sum of `quantity` minus `returned_quantity` over order lines referencing it whose order's `payment_status` is `PAID` or `PARTIALLY_REFUNDED`, and `delivered_qty`, the same sum over order lines whose order's `fulfillment_status` is `DELIVERED`. Each sheet reports two percentages, each computed over its current lines and each zero when the sheet has no lines: `pull_through_ordered_pct` takes, per line, the smaller of `ordered_qty` and `specified_qty`, sums those capped values, divides by the sum of `specified_qty`, multiplies by 100, and rounds half up to 2 decimal places; `pull_through_delivered_pct` has exactly the same shape with `delivered_qty` in place of `ordered_qty`. The ordered basis reports commitments made; the delivered basis reports final fulfillment, and for identical order data the two variants diverge whenever a paid order has not yet been delivered. Both are recomputed whenever a contributing event lands: an order payment, a return, a delivery completion, or a spec-line replacement touching a referenced line.

### 3.6. Order Capture, Line Pricing, and Payment

A `StoreAssociate` or the owning `Contractor` creates an order by supplying the `contractor_account_id`, the `job_account_id` the material is for, the OCC token `expected_contractor_account_version` (§2.7), and `lines` — each line carrying a `product_id`, a `quantity` greater than zero, an optional `formula_id` for a custom-tint line, and an optional `spec_line_id` to attribute the purchase to an approved spec for pull-through. `lines` may be an empty array; such an order prices to a zero subtotal, zero tax, and zero total. Because so many rules converge on this one operation, they are evaluated in a fixed sequence so the first failure masks the rest: the account-version OCC check runs first (`ERR_STALE_VERSION`), then the account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`) and the job `OPEN` (`ERR_JOB_NOT_OPEN`); then each line is screened for VOC compliance (`ERR_VOC_LIMIT_EXCEEDED`); then the tint permission — a line carrying `formula_id` requires the product's `tintable` flag to be true (`ERR_PRODUCT_NOT_TINTABLE`, HTTP 422); then the referential checks — every referenced product must be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`), every referenced formula must be `ACTIVE` (`ERR_FORMULA_RETIRED`, HTTP 422), each formula's own `product_id` must equal its line's `product_id` (`ERR_FORMULA_PRODUCT_MISMATCH`, HTTP 422), and each referenced spec line must name the same product as its order line *and* belong to a sheet whose `status` is `APPROVED` — pull-through attribution only ever runs against approved specs — (`ERR_SPEC_LINE_PRODUCT_MISMATCH`, HTTP 422); then the job-ownership check — the job account's `contractor_account_id` must equal the order's `contractor_account_id` (`ERR_JOB_ACCOUNT_MISMATCH`, HTTP 422); and only then the two fiscal caps — the account's `outstanding_balance_cents` plus the new order's `total_cents` must not exceed its `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422), and the job's budget cap of §3.2 is checked after the credit limit.

Pricing happens per line at creation. Each line snapshots the product's current `list_price_cents` into `unit_list_price_cents`, and the account's tier at that moment is frozen into the order's `tier_snapshot` — later tier changes never reprice an existing order, and the loyalty multiplier of §3.7 also keys off this snapshot. The tier discount is 0% for `STANDARD`, 5% for `SILVER`, 10% for `GOLD`, and 15% for `PLATINUM`. Independently, a quantity break of 3% applies to any line whose `quantity` is at least 10 units. The line's `unit_price_cents` is the snapshotted list price reduced by the tier percentage and then by the quantity-break percentage, with the result **rounded half up to a whole cent at the per-unit step first**; `line_total_cents` is then that rounded unit price multiplied by `quantity`. The rounding order is pinned: rounding the per-unit price before extending by quantity is the only correct order, and extending the list price by quantity before applying discounts and rounding once at the line level is a different computation and is rejected. A line carrying a `formula_id` is flagged `is_custom_tint` true, which §3.7 shows has return consequences.

Order totals derive from the lines in a pinned evaluation order — lines, then subtotal, then tax, then total. `subtotal_cents` is the sum of `line_total_cents` over all lines. `discount_cents` is the sum of `unit_list_price_cents` times `quantity` over all lines minus `subtotal_cents` — the total value given away by tier and quantity pricing. `tax_cents` is 8.25 percent of the discounted `subtotal_cents`, rounded half up, computed exactly once at order level and never per line. `total_cents` is `subtotal_cents` plus `tax_cents`. These derivations use every line of the order regardless of any returns later taken against it. A created order starts `UNPAID` and `PENDING` with `refunded_cents` zero and `paid_at` null; its creation recomputes the account's `outstanding_balance_cents` and increments the account's `version`.

Payment moves the payment dimension `UNPAID` to `PAID` and may be taken by a `StoreAssociate` or the owning `Contractor`, provided the account is still `ACTIVE` (otherwise `ERR_ACCOUNT_SUSPENDED`) and the order is still `UNPAID` (otherwise `ERR_ORDER_NOT_PAYABLE`, HTTP 409). Payment stamps `paid_at` from the logical clock and fires the loyalty earn cascade of §3.7, recomputes the account's `outstanding_balance_cents` (the order leaves the unpaid set) and the job's `spent_cents`, and increments both the order's and the account's `version`. Cancellation is the inverse for untouched orders: from `PENDING` *and* `UNPAID` — both conditions required, otherwise `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409) — the fulfillment dimension moves to `CANCELLED` (the payment dimension is untouched: a cancelled order remains `UNPAID`), the account's outstanding balance is recomputed, and both versions increment. A paid order has financial effects and is never cancelled; it is unwound line by line through returns instead.

### 3.7. Returns, Refunds, and the Loyalty Ledger

A `StoreAssociate` takes a return against a specific order line by supplying a `quantity`. Three guards apply in order: the line's order must have `payment_status` `PAID` or `PARTIALLY_REFUNDED` — an unpaid or fully refunded order has nothing to return against — otherwise `ERR_ORDER_NOT_REFUNDABLE` (HTTP 409); then the custom-tint prohibition — a line with `is_custom_tint` true is never returnable regardless of how many units remain, and the attempt is rejected with `ERR_CUSTOM_TINT_NO_RETURN` (HTTP 422); then the remaining-quantity check — the requested `quantity` must not exceed the line's `quantity` minus its `returned_quantity` so far, otherwise `ERR_RETURN_QUANTITY_EXCEEDED` (HTTP 422).

Each accepted return creates a return record, an append-only event row (only `id` and `created_at`, per §2.5) linking the `order_line_id`, the returned `quantity`, and three computed amounts: `refund_merchandise_cents`, the line's `unit_price_cents` multiplied by the returned quantity; `tax_refund_cents`, 8.25 percent of that merchandise refund rounded half up — the tax is rounded per return event; and `total_credit_cents`, their sum. There is no restocking fee: the refund is full merchandise plus tax on that merchandise. The line's `returned_quantity`, zero at order creation, grows by the returned amount, and the order's `refunded_cents` is recomputed as the sum of `total_credit_cents` over all its return records.

The refund event then drives the order's payment dimension: while cumulative `refunded_cents` stays below `total_cents`, a `PAID` order becomes `PARTIALLY_REFUNDED`; when `refunded_cents` reaches or exceeds `total_cents` (per-return-event tax rounding can push the cumulative credit a cent past the order total), the order becomes `REFUNDED` — whether it arrived there from `PAID` or from `PARTIALLY_REFUNDED`. Either path fires the same downstream cascade: a loyalty clawback entry is posted (below), the account's `loyalty_points_balance` and `ytd_net_volume_cents` are recomputed, the job's `spent_cents` is recomputed, any referenced spec lines have their `ordered_qty` and `delivered_qty` (and their sheets' pull-through percentages) recomputed, and the order, the order line, the contractor account, and the job account each take a `version` increment.

The loyalty ledger itself is a list of append-only transaction rows, each carrying the `contractor_account_id` it posts to, an `order_id` (null for redemptions), a `type` of `EARN`, `REDEEM`, or `CLAWBACK`, a signed `points_delta`, and a human-readable `note`. Earning happens at payment: the posted `EARN` entry's `points_delta` is the whole dollars of merchandise — the order's `subtotal_cents` divided by 100 and truncated down — multiplied by the tier multiplier from the order's `tier_snapshot`, which is 1 for `STANDARD`, 2 for `SILVER`, 3 for `GOLD`, and 5 for `PLATINUM`; the floor is taken before the multiplication. Clawback mirrors it at return time: a `CLAWBACK` entry posts a negative `points_delta` whose magnitude is the return record's `refund_merchandise_cents` divided by 100, truncated down, times the same snapshot multiplier. Because earn and clawback share the merchandise basis and the multiplier, a single-line order that is paid and then fully returned claws back exactly what it earned, restoring the account's pre-payment balance; in general, though, `loyalty_points_balance` — always the sum of `points_delta` over the account's ledger — may go negative, and a negative balance blocks redemption. Redemption is the owning `Contractor` spending points: the request names the `contractor_account_id` and a `points_to_redeem`, requires the account `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), and requires the current `loyalty_points_balance` to be at least `points_to_redeem` (else `ERR_INSUFFICIENT_POINTS`, HTTP 422). An accepted redemption posts a `REDEEM` entry with negative `points_delta` equal to the points spent and a `note` recording a credit of `credit_cents` equal to the points redeemed — one point is one cent of credit — and the balance is recomputed.

### 3.8. Delivery Scheduling, Dispatch, and Completion

Deliveries belong to a `StoreManager`. Scheduling one names the `order_id`, the `job_account_id` of the site, and a [`window_start`, `window_end`) pair. The guards run in pipeline order: the window shape — `window_end` must be after `window_start` — is a generic shape failure (`ERR_VALIDATION`); the contractor account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`) and the job `OPEN` (`ERR_JOB_NOT_OPEN`, HTTP 409); the `window_start` must not lie before the logical clock now (`ERR_DELIVERY_WINDOW_PAST`, HTTP 422); then the buffer rule — against every other delivery of the same job whose `status` is `SCHEDULED` or `EN_ROUTE`, the new window must keep at least a 30-minute clearance: the new `window_start` must be no earlier than the existing delivery's `window_end` plus 30 minutes, or the new `window_end` plus 30 minutes must be no later than the existing delivery's `window_start`. Mere adjacency is not enough here (unlike the windows of §2.10), and a violation is `ERR_DELIVERY_WINDOW_CONFLICT` (HTTP 409). Finally, the delivery's `job_account_id` must equal the order's own `job_account_id`, else `ERR_JOB_ACCOUNT_MISMATCH`. A scheduled delivery starts `SCHEDULED` with `dispatched_at`, `delivered_at`, and `failure_reason` all null. Note that scheduling does not require the order to be paid — payment is enforced at dispatch, not at booking.

Dispatch moves the delivery `SCHEDULED` to `EN_ROUTE` and is where operations harden. The guards evaluate in order: the job must be `OPEN` (`ERR_JOB_NOT_OPEN`); the delivery must still be `SCHEDULED` (`ERR_DELIVERY_NOT_DISPATCHABLE`, HTTP 409); the order must be `PAID` (a generic state failure, `ERR_INVALID_STATE`); and finally VOC compliance is re-checked at the dispatch instant — for every line of the order, the product's `voc_gpl` must not exceed the `max_voc_gpl` of the VOC rule effective at the logical clock now for the pair of the job's `jurisdiction_id` and the product's `category` (a jurisdiction-and-category pair with no effective rule is unrestricted). A rule that took effect between order creation and dispatch therefore binds the shipment, and a violation is `ERR_VOC_LIMIT_EXCEEDED`. The same at-the-instant check governs order creation in §3.6, evaluated against the creation instant. A successful dispatch stamps `dispatched_at` from the logical clock and fires the cross-entity hop that moves the order's `fulfillment_status` from `PENDING` to `OUT_FOR_DELIVERY` on this first dispatch, incrementing both the delivery's and the order's `version`.

Completion moves `EN_ROUTE` to `DELIVERED`, stamps `delivered_at`, and bubbles upward: when, after this delivery lands, no other delivery of the same order remains `SCHEDULED` or `EN_ROUTE`, the order's `fulfillment_status` moves `OUT_FOR_DELIVERY` to `DELIVERED`, and any referenced spec lines have their `delivered_qty` (and their sheets' delivered-basis pull-through) recomputed. Failure moves `EN_ROUTE` to `FAILED`, records the payload's `failure_reason`, and deliberately leaves the order's `fulfillment_status` unchanged — `FAILED` is terminal, and operations re-attempts by creating a fresh delivery row for the same order rather than resurrecting the failed one. Both completion and failure require the delivery to be in `EN_ROUTE`; attempting either from any other state is rejected with `ERR_DELIVERY_NOT_EN_ROUTE` (HTTP 409).

### 3.9. Rebate Settlement and Mistint Recovery

Volume rebates are settled per account and period through rebate statements. A `CorporateAdmin` generates a statement by naming the `contractor_account_id` and a half-open [`period_start`, `period_end`) window. Generation requires `period_end` after `period_start` (a shape failure, `ERR_VALIDATION`), requires the logical clock now to have reached `period_start` — a statement cannot be opened for a future period — (`ERR_REBATE_PERIOD_INVALID`, HTTP 422), and requires that no existing statement for the same account has a period overlapping the new one under half-open semantics, with adjacency allowed (`ERR_REBATE_PERIOD_OVERLAP`, HTTP 409). A generated statement starts `ACCRUED` with `final_amount_cents`, `payable_cents`, and `paid_at` null, `adjustment_cents` zero, and a forward-looking estimate stored in `provisional_amount_cents`.

The provisional estimate is computed once at generation. Let the period length be the whole number of days in [`period_start`, `period_end`), and let the elapsed days be the whole number of days in [`period_start`, the earlier of the logical clock now and `period_end`) — so once the period has closed, elapsed days equal the period length. The net volume so far is the merchandise basis over the account's paid-set orders (`payment_status` `PAID`, `PARTIALLY_REFUNDED`, or `REFUNDED`) whose `paid_at` falls inside the elapsed portion of the period, minus the refund merchandise on those orders' return records. That net is annualized into a projection: multiplied by the period length, divided by the elapsed days, and truncated down to a whole cent. The projection is then banded at 2% of its portion up to 10,000,000 cents ($100,000), plus 4% of its portion between $100,000 and 30,000,000 cents ($300,000), plus 6% of any portion above $300,000. The provisional amount is that banded figure prorated back to the elapsed fraction: multiplied by the elapsed days, divided by the period length, and truncated down to a whole cent. The two truncations are pinned — once at the projection, once at the final proration. When the period spans fewer than one whole day, or zero whole days have elapsed since `period_start`, the projection-and-proration is skipped and `provisional_amount_cents` is 0.

Finalization — allowed only once the logical clock has reached `period_end`, with the statement `ACCRUED` (otherwise `ERR_INVALID_STATE`) — moves the statement to `FINALIZED` and replaces the estimate with the chronological rebate in `final_amount_cents`. The chronological variant builds an event stream for the window: a payment event contributing the order's `subtotal_cents` at its `paid_at` for every paid-set order of the account with `paid_at` in the period, plus a refund event contributing negative `refund_merchandise_cents` at the return record's `created_at` for every return against the account's order lines recorded in the period. Events sort by timestamp ascending; a tie between a payment and a refund places the payment first; any remaining tie breaks by the underlying row's `created_at` ascending, and a tie that still remains breaks by the order in which the rows were inserted — the row `id` is never used as a tiebreaker. Two running accumulators, a volume and a rebate, both start at zero in exact decimal cents. Each payment of amount *a* fills the bands bottom-up, straddling within the event: while any of *a* remains, the applicable rate is 6% when the volume has reached $300,000 (with unbounded headroom), otherwise 4% when the volume has reached $100,000 (with headroom up to the $300,000 boundary), otherwise 2% (with headroom up to the $100,000 boundary); the chunk is the smaller of the remaining *a* and the headroom, the rebate gains the chunk times the rate, and the volume gains the chunk. Each refund of amount *f* peels the bands top-down, unwinding the highest-rate band first: while any of *f* remains, the applicable rate is 6% when the volume exceeds $300,000 (with the band floor at $300,000), otherwise 4% when the volume exceeds $100,000 (band floor $100,000), otherwise 2% (band floor zero); the chunk is the smaller of the remaining *f* and the volume above the band floor, the rebate loses the chunk times the rate, and the volume loses the chunk. The marginal straddle is symmetric — a payment followed by a full in-period refund restores both accumulators exactly — so for identical order data the final differs from the provisional only through the provisional's forward-looking projection and proration whenever volume crosses a band boundary mid-period. `final_amount_cents` is the rebate accumulator rounded half up to a whole cent, applied once at the end.

Finalization also computes `period_net_cents` — the same merchandise basis over the full period window — and `payable_cents`, the amount actually payable: the sum of `final_amount_cents` and `adjustment_cents`, capped at 5 percent of `period_net_cents` rounded half up, and floored at zero; the cap can bind below the banded amount, and a negative adjustment can drive the raw figure below zero, where the floor binds. Settlement then follows a deliberate negotiation cycle. The owning `Contractor` may dispute a `FINALIZED` statement, moving it to `DISPUTED`; a `CorporateAdmin` resolves the dispute by supplying a signed `adjustment_cents` — the supplied value replaces the statement's `adjustment_cents` outright rather than accumulating onto any earlier adjustment — moving `DISPUTED` back to `FINALIZED` with `payable_cents` recomputed under the new adjustment; each pass bumps the statement's `version`, and a dispute attempted from anything but `FINALIZED`, or a resolution from anything but `DISPUTED`, draws `ERR_INVALID_STATE`. Payout moves `FINALIZED` to the terminal `PAID`, stamps `paid_at` from the logical clock, recomputes the account's `lifetime_rebate_paid_cents`, and increments both the statement's and the account's `version`.

Mistint inventory recovers value from tinting mistakes. A `StoreAssociate` creates a listing with the `product_id`, an optional `formula_id` naming the mistaken formula (null when unknown), a `quantity` greater than zero, and a `cost_basis_cents` per unit (at least zero). Creation fixes `list_price_cents` at half the cost basis, truncated down to a whole cent, and the listing starts `LISTED`. From then on the price decays with age: letting the whole started weeks be the logical-clock time from the listing's `created_at` to now, divided into full seven-day weeks and truncated down, the decayed price is `list_price_cents` multiplied by 0.90 once per started week, rounded half up; the floor price is 25 percent of `cost_basis_cents`, rounded half up; and `current_price_cents` is the larger of the two — the listing never prices below a quarter of its cost. `current_price_cents` is recomputed on every read of the listing and again at the moment of sale. Marking a listing sold — `LISTED` to `SOLD`, by a `StoreAssociate` — captures that instant's `current_price_cents` into `sold_price_cents` (null until the sale) and records the buying contractor in `sold_to_contractor_account_id` from the payload (null when the sale is anonymous); a supplied `sold_to_contractor_account_id` that is not a string, or that names no existing contractor account, is rejected with `ERR_REFERENCE_NOT_FOUND` (422). A `StoreManager` may instead write a listing off — `LISTED` to `WRITTEN_OFF`. Either action from a non-`LISTED` state is `ERR_INVALID_STATE`, and each bumps the listing's `version`.

## 4. Endpoint Definitions

All endpoints are mounted under `/`. Creating a new resource returns HTTP 201; operations that modify an existing resource return HTTP 200; the logical-clock capability returns HTTP 204 with no body. List endpoints accept the pagination parameters of §2.3 plus the optional filters named in the narratives — `contractor_account_id`, `jurisdiction_id`, `status`, `category`, `product_id`, `replacement_product_id`, `color_code`, `supersedes_formula_id`, `formula_id`, `job_account_id`, `payment_status`, `fulfillment_status`, `order_id`, `spec_line_id`, `order_line_id`, `project_code`, `supersedes_spec_sheet_id`, `spec_sheet_id`, and `sold_to_contractor_account_id` — each narrowing the result to rows whose corresponding field equals the supplied value; a supplied value outside the field's enum on the enum-typed filters (`status`, `category`, `payment_status`, `fulfillment_status`) is rejected with `ERR_VALIDATION` (400). A request to a path not defined in this table is rejected with `ERR_NOT_FOUND` (404) regardless of headers, and a defined path addressed with an unsupported method is rejected with the same error id at HTTP 405. Request payloads, responses, and side effects for each operation are as specified in Section 3; this table is a routing and authorization reference only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /contractor-accounts | Create a contractor account | CorporateAdmin |
| GET | /contractor-accounts/{id} | Read one account including computed balances | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| PATCH | /contractor-accounts/{id} | Update `company_name` and/or `credit_limit_cents`; OCC-guarded | CorporateAdmin |
| POST | /contractor-accounts/{id}/suspend | Suspend an account (`ACTIVE` → `SUSPENDED`) | CorporateAdmin |
| POST | /contractor-accounts/{id}/reinstate | Reinstate an account (`SUSPENDED` → `ACTIVE`) | CorporateAdmin |
| POST | /contractor-accounts/{id}/evaluate-tier | Recompute tier from year-to-date net volume | CorporateAdmin |
| POST | /job-accounts | Create a job account for a contractor | StoreAssociate, Contractor |
| GET | /job-accounts/{id} | Read one job account including `spent_cents` | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /job-accounts | List job accounts | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /job-accounts/{id}/place-on-hold | Place a job on hold (`OPEN` → `ON_HOLD`) | StoreManager, Contractor |
| POST | /job-accounts/{id}/resume | Resume a job (`ON_HOLD` → `OPEN`) | StoreManager, Contractor |
| POST | /job-accounts/{id}/complete | Complete a job; requires no open orders or deliveries | StoreManager, Contractor |
| POST | /jurisdictions | Create a jurisdiction | CorporateAdmin |
| POST | /voc-rules | Create a VOC limit rule; overlapping windows rejected | CorporateAdmin |
| GET | /voc-rules | List VOC rules | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| GET | /voc-rules/{id} | Read one VOC rule | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| POST | /products | Create a product | CorporateAdmin |
| GET | /products/{id} | Read one product | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| GET | /products | List products | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| PATCH | /products/{id} | Update `name`, `list_price_cents`, `voc_gpl`, or `tintable` | CorporateAdmin |
| POST | /tint-formulas | Create a formula revision, superseding the prior active one | StoreAssociate, CorporateAdmin |
| GET | /tint-formulas | List tint formulas | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| GET | /tint-formulas/{id} | Read one formula | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| POST | /tint-formulas/{id}/retire | Retire a formula (`ACTIVE` → `RETIRED`) | CorporateAdmin |
| POST | /product-bulletins | Create a discontinuation bulletin (`DRAFT`) | CorporateAdmin |
| GET | /product-bulletins | List bulletins | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| GET | /product-bulletins/{id} | Read one bulletin | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| POST | /product-bulletins/{id}/publish | Publish a bulletin; validates the replacement product | CorporateAdmin |
| POST | /product-bulletins/{id}/take-effect | Fire the discontinuation cascade | CorporateAdmin |
| POST | /color-match-requests | Create a color match request (`SUBMITTED`) | StoreAssociate |
| GET | /color-match-requests/{id} | Read one color match request | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /color-match-requests | List color match requests | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /color-match-requests/{id}/proposals | Attach a match proposal; creates a `COLOR_MATCH` formula | StoreAssociate |
| POST | /color-match-requests/{id}/approve | Approve the proposal (`PROPOSED` → `APPROVED`) | Contractor |
| POST | /color-match-requests/{id}/request-revision | Request a revision; retires the proposed formula | Contractor |
| POST | /color-match-requests/{id}/abandon | Abandon the request | StoreAssociate, Contractor |
| POST | /orders | Create an order with lines; OCC-guarded on the account | StoreAssociate, Contractor |
| GET | /orders/{id} | Read one order with computed totals | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /orders | List orders | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /orders/{id}/pay | Pay an order (`UNPAID` → `PAID`); fires loyalty earn | StoreAssociate, Contractor |
| POST | /orders/{id}/cancel | Cancel an unpaid, pending order | StoreAssociate, Contractor |
| GET | /order-lines | List order lines | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /order-lines/{id} | Read one order line | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /order-lines/{id}/return | Return units of a non-custom-tint line | StoreAssociate |
| GET | /return-records | List return records | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /return-records/{id} | Read one return record | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /deliveries | Schedule a delivery window for an order | StoreManager |
| GET | /deliveries | List deliveries | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /deliveries/{id} | Read one delivery | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /deliveries/{id}/dispatch | Dispatch a delivery; re-checks VOC at the dispatch instant | StoreManager |
| POST | /deliveries/{id}/mark-delivered | Mark a delivery delivered; bubbles order fulfillment up | StoreManager |
| POST | /deliveries/{id}/mark-failed | Mark a delivery failed (terminal); re-delivery via a new row | StoreManager |
| POST | /spec-sheets | Create a spec sheet with lines (`DRAFT`) | SpecWriter |
| GET | /spec-sheets/{id} | Read one sheet including pull-through percentages | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| GET | /spec-sheets | List spec sheets | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| POST | /spec-sheets/{id}/submit | Submit a sheet; requires at least one line | SpecWriter |
| POST | /spec-sheets/{id}/approve | Approve a sheet; pins product references; supersedes prior approval | CorporateAdmin |
| POST | /spec-sheets/{id}/reject | Reject a sheet with a `reason` | CorporateAdmin |
| POST | /spec-sheets/{id}/revise | Revise a rejected or obsoleted sheet; replaces the line set | SpecWriter |
| GET | /spec-lines | List spec lines | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| GET | /spec-lines/{id} | Read one spec line including pull-through counters | CorporateAdmin, StoreManager, StoreAssociate, SpecWriter, Contractor |
| POST | /rebate-statements | Generate a statement for an account and period (`ACCRUED`) | CorporateAdmin |
| GET | /rebate-statements | List rebate statements | CorporateAdmin, Contractor |
| GET | /rebate-statements/{id} | Read one rebate statement | CorporateAdmin, Contractor |
| POST | /rebate-statements/{id}/finalize | Finalize a statement; computes final, period-net, and payable amounts | CorporateAdmin |
| POST | /rebate-statements/{id}/dispute | Dispute a finalized statement | Contractor |
| POST | /rebate-statements/{id}/resolve-dispute | Resolve a dispute with a signed `adjustment_cents` | CorporateAdmin |
| POST | /rebate-statements/{id}/pay | Pay a finalized statement | CorporateAdmin |
| POST | /loyalty-redemptions | Redeem points (1 point = 1 cent of credit) | Contractor |
| GET | /loyalty-transactions | List loyalty ledger entries | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /loyalty-transactions/{id} | Read one ledger entry | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /mistint-listings | Create a mistint listing (`LISTED`) | StoreAssociate |
| GET | /mistint-listings | List mistint listings with current decayed price | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| GET | /mistint-listings/{id} | Read one mistint listing with current decayed price | CorporateAdmin, StoreManager, StoreAssociate, Contractor |
| POST | /mistint-listings/{id}/mark-sold | Mark a listing sold; captures the current price | StoreAssociate |
| POST | /mistint-listings/{id}/write-off | Write a listing off | StoreManager |
| POST | /_clock/set_current_utc | Test-driving capability: set the logical clock | CorporateAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in Sections 2 and 3; this table is an identifier-to-status reference only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_SUSPENDED | 409 |
| ERR_ORDER_NOT_PAYABLE | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_ORDER_NOT_REFUNDABLE | 409 |
| ERR_JOB_NOT_OPEN | 409 |
| ERR_DELIVERY_NOT_DISPATCHABLE | 409 |
| ERR_DELIVERY_NOT_EN_ROUTE | 409 |
| ERR_SPEC_NOT_REVIEWABLE | 409 |
| ERR_SPEC_NOT_REVISABLE | 409 |
| ERR_MATCH_NOT_REVIEWABLE | 409 |
| ERR_VOC_LIMIT_EXCEEDED | 422 |
| ERR_DELIVERY_WINDOW_PAST | 422 |
| ERR_DELIVERY_WINDOW_CONFLICT | 409 |
| ERR_VOC_RULE_OVERLAP | 409 |
| ERR_BULLETIN_NOT_YET_EFFECTIVE | 422 |
| ERR_REBATE_PERIOD_INVALID | 422 |
| ERR_REBATE_PERIOD_OVERLAP | 409 |
| ERR_SKU_EXISTS | 409 |
| ERR_JURISDICTION_CODE_EXISTS | 409 |
| ERR_SPEC_EMPTY | 422 |
| ERR_MATCH_ITERATION_EXHAUSTED | 422 |
| ERR_PRODUCT_NOT_TINTABLE | 422 |
| ERR_CUSTOM_TINT_NO_RETURN | 422 |
| ERR_RETURN_QUANTITY_EXCEEDED | 422 |
| ERR_PRODUCT_DISCONTINUED | 422 |
| ERR_FORMULA_RETIRED | 422 |
| ERR_FORMULA_PRODUCT_MISMATCH | 422 |
| ERR_SPEC_LINE_PRODUCT_MISMATCH | 422 |
| ERR_JOB_ACCOUNT_MISMATCH | 422 |
| ERR_BULLETIN_REPLACEMENT_INVALID | 422 |
| ERR_CREDIT_LIMIT_EXCEEDED | 422 |
| ERR_BUDGET_CAP_EXCEEDED | 422 |
| ERR_INSUFFICIENT_POINTS | 422 |

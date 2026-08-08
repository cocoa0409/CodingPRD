# Telecom & SaaS Expense Management API — Product Requirements Document

## 1. Introduction

Enterprises today carry a sprawling portfolio of recurring telecom and software-as-a-service spend: mobile lines, circuits, per-seat subscriptions, flat platform fees, and usage-metered tools that arrive on invoices scattered across dozens of vendors. This service is a Telecom & SaaS Expense Management (TEM) platform whose purpose is to bring that spend under a single ledger — tracking the inventory of contracted services, reconciling every vendor invoice against what the contract says the enterprise *should* have been billed, recovering money through disputes and vendor credits, allocating each net charge back to the cost centers that consumed it, and continuously surfacing rightsizing opportunities that trim commitment before renewal.

The platform is built around a reconciliation discipline: money is never lost or invented. Every credit recovered from a vendor is recorded as an append-only ledger entry, every chargeback share sums exactly to the line it charges back, and every optimization is measured both as a forward-looking projection and as a chronologically realized saving. Because several teams touch the same money — sourcing managers negotiate contracts, analysts scrutinize invoices and open disputes, finance approvers sign off and pay, and cost-center owners accept their share of the charge — the system enforces strict separation of duties and role-scoped ownership so that no single actor can both approve and disburse the same funds.

This document specifies the complete REST contract: the global conventions every endpoint obeys, the business rules governing each entity's lifecycle, the calculation formulas, and the full catalogue of endpoints and error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID`, a stable identifier for the acting user or system principal, and `X-User-Role`, naming the caller's role. A request missing either header, or presenting an `X-User-Role` that is not one of the six known roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `Sourcing`, `Analyst`, `FinanceApprover`, `CostCenterOwner`, `Vendor`, and `SystemAdmin`. Their responsibilities divide the workflow:

- A `Sourcing` operator manages vendors and their contracts (creation, activation, renewal, termination) and registers the service inventory under those contracts.
- An `Analyst` performs invoice intake and review, adds line items, opens and negotiates disputes, creates chargeback allocations, and proposes optimization recommendations.
- A `FinanceApprover` approves and pays invoices — subject to separation of duties — and decides (implements or rejects) recommendations.
- A `CostCenterOwner` approves chargeback allocations posted against the cost center they own.
- A `Vendor` responds to disputes raised against its invoices.
- A `SystemAdmin` performs operational tasks: driving the logical clock and configuring cost centers.

All six roles may perform any GET read in the system; the exclusive write operations are partitioned as described above and enumerated per-endpoint in §4.

Role identity binds to resources in two different ways. When `X-User-Role` is `CostCenterOwner`, `X-User-ID` is the identifier of the acting cost-center owner; ownership checks compare a cost center's `owner_user_id` field to `X-User-ID`, so a `CostCenterOwner` may only act on allocations whose target cost center records that same owner. When `X-User-Role` is `Vendor`, `X-User-ID` is the identifier of the acting vendor principal responding to disputes. For the remaining roles — `Sourcing`, `Analyst`, `FinanceApprover`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow demands it (for example, the invoice's `approved_by_user_id` captures the `X-User-ID` of the approving `FinanceApprover` so it can later be compared for separation of duties), but it is not otherwise matched against any entity's `id`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested `limit` above the maximum is capped at 100. `offset` defaults to 0 and represents the number of leading records to skip. List results are always ordered by `created_at` ascending (oldest first). Each list response reports pagination state in the `meta` object through the fields `limit`, `offset`, `total_count` (the total number of records matching the query before the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id` — an opaque UUID string carrying no type prefix — at creation time, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry an `updated_at` timestamp (initially equal to `created_at`) and an integer `version` that begins at 1 and increments by exactly one on every mutation of that resource. Whenever a resource's state or fields change, its `updated_at` is refreshed to the moment of the change and its `version` is bumped; the per-transition sections below spell out each version increment explicitly.

One resource is deliberately leaner. A `Credit` is an append-only ledger entry: it carries only an `id` and a `created_at`, and it has neither an `updated_at` nor a `version`, because it is never mutated after issuance. Every other resource in this system — `Vendor`, `Contract`, `Service`, `Invoice`, `InvoiceLineItem`, `Dispute`, `CostCenter`, `Allocation`, and `Recommendation` — carries the full complement of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents; no field carries fractional cents. Wherever a calculation produces a fractional intermediate value, the rounding method is **round half up** (a value exactly halfway between two integers rounds away from zero to the larger magnitude). Percentages that are stored — such as a service's `utilization_pct` — are carried to two decimal places, also using round half up. The specific point at which rounding is applied within each formula matters and is pinned in the relevant workflow narrative below; implementers must round exactly where stated and not earlier or later, because rounding order changes the cents.

### 2.6. Optimistic Concurrency Control

Proposing an optimization recommendation against a service is guarded by optimistic concurrency control. A request to create a recommendation for a service must include `expected_service_version`, a non-optional field carrying the `version` of that service as the client last observed it. The server compares `expected_service_version` against the service's current `version`; if they do not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no recommendation is created. This matters because creating a new `PROPOSED` recommendation legitimately supersedes any prior `PROPOSED` recommendation on the same service and bumps the service's `version`; a second create still carrying the pre-supersede version is therefore operating on a stale view of the service and is correctly rejected rather than allowed to overwrite work it never saw. No other endpoint in the system takes a version field.

### 2.7. Cascading Consistency and Ledger Conservation

Many operations touch more than one entity. When they do, the full cascade is part of the contract, not an incidental side effect. Terminating a contract, accepting a dispute, implementing a recommendation, and crediting a line item each ripple outward across parent and sibling resources; the affected entities have their computed fields recomputed and, where they carry a `version`, that `version` is incremented and `updated_at` refreshed. The precise cascade for each such operation is described in §3 alongside the workflow that triggers it.

Two conservation invariants hold system-wide. First, the chargeback invariant: the `amount_cents` of the allocations created for a single line item always sum to exactly that line's `net_amount_cents` at the time of allocation. Second, the recovery-ledger invariant: a contract's `total_recovered_cents` reflects only credits that were actually issued, so a dispute that is opened and later withdrawn — creating no credit — leaves `total_recovered_cents` unchanged across the whole open-then-withdraw cycle.

### 2.8. Nested Resource Retrieval and Reference Validation

Several endpoints address a resource through a nested path (for example, the disputes belonging to a particular line item, or the services belonging to a particular contract). Path parameters are validated left to right: the leftmost identifier is resolved first, and if it names no existing resource the request fails with that resource's not-found error before any deeper segment or body field is examined. Only once every path identifier resolves does the server validate foreign-key references carried in the request body. Each reference class has its own not-found error — `ERR_VENDOR_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_COST_CENTER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_RECOMMENDATION_NOT_FOUND`, and `ERR_CREDIT_NOT_FOUND` — each returned with HTTP 404.

### 2.9. Request Validation Order

When a request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned error is deterministic:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the operation, else `ERR_UNAUTHORIZED` (403).
3. **Payload validation** — required body fields present, enum values legal, numeric amounts non-negative, and any `weight_pct` within 0 to 100 inclusive, else `ERR_VALIDATION` (422).
4. **Existence** — every path identifier and body foreign key resolves to a real resource (path identifiers first, left to right), else the appropriate not-found error (404).
5. **State** — the target resource is in a state that permits the requested transition, else the applicable state error such as `ERR_INVALID_STATE`, `ERR_LINE_NOT_DISPUTABLE`, `ERR_INVOICE_NOT_REVIEWABLE`, `ERR_DISPUTE_NOT_RESPONDED`, or `ERR_INVOICE_NOT_APPROVED` (409).
6. **Cross-entity referential state** — related entities are in the required states (vendor active for activate/renew; parent contract active for invoice review and approve; cost center active for allocation approve), else `ERR_VENDOR_SUSPENDED`, `ERR_CONTRACT_NOT_ACTIVE`, or `ERR_COST_CENTER_FROZEN` (409).
7. **Temporal** — the renewal-window check, else `ERR_OUTSIDE_RENEWAL_WINDOW` (422).
8. **Domain business constraints** — term overlap, billing-period overlap, weight-sum, utilization threshold, separation of duties, dispute-round cap, and cost-center ownership, each with its own error described in §3.
9. **Fiscal bounds** — dispute credit ceilings (`ERR_CREDIT_EXCEEDS_BILLED`, `ERR_OFFER_EXCEEDS_CLAIM`) at 422.
10. **Optimistic concurrency** — the `expected_service_version` match on recommendation create, else `ERR_STALE_VERSION` (412).

Where a single endpoint carries several checks within priority band 8, those are noted in the workflow that owns them. Note that the two dispute fiscal ceilings (band 9) and the cost-center ownership check (`ERR_NOT_COST_CENTER_OWNER`, a 403) sit inside the negotiation and chargeback workflows respectively and are described there.

## 3. Business Logic & Workflows

### 3.1. Vendors, Contracts, and the Sourcing Lifecycle

The catalogue of spend begins with a **vendor**. A `Sourcing` operator registers a provider by supplying its `name` and its `vendor_type`, which must be either `TELECOM` or `SAAS`. A new vendor opens in `ACTIVE` status. A vendor can later be taken out of service: suspending an `ACTIVE` vendor moves its `status` to `SUSPENDED` and increments the vendor's `version`. A vendor already `SUSPENDED` cannot be suspended again. Suspension is consequential downstream: a `SUSPENDED` vendor blocks both activation and renewal of its contracts, as described below.

A **contract** captures the commercial agreement with one vendor. Creating a contract requires the `vendor_id` it belongs to, a `term_start` and `term_end` (both ISO 8601 UTC instants forming a *closed* interval — both endpoints are inclusive for overlap purposes), and `renewal_notice_days`, the number of days before `term_end` at which the renewal window opens. Three further inputs are optional at creation: `renewal_term_months`, the number of months the term is extended on each renewal (defaulting to 12); `auto_renew`, an advisory flag defaulting to false that records intent but never bypasses the renewal-window check; and `volume_tier_enabled`, defaulting to true, which controls whether the volume-tier discount ladder applies when reconciling invoices. A contract is born in `DRAFT` status and carries three running figures that begin at zero: `monthly_committed_cost_cents`, `total_recovered_cents`, and `renewal_count`.

Bringing a contract into force means activating it. Activation is permitted only when the contract is in `DRAFT`; if it is in any other state the request fails with `ERR_INVALID_STATE`. The contract's vendor must be `ACTIVE` — activating under a `SUSPENDED` vendor is rejected with `ERR_VENDOR_SUSPENDED`. Finally, the new term must not collide with the vendor's existing coverage: if any other `ACTIVE` contract of the *same* vendor has a term whose closed interval intersects this contract's `[term_start, term_end]`, activation is rejected with `ERR_CONTRACT_TERM_OVERLAP`. Because the intervals are closed, two terms that merely touch at an endpoint (one ending exactly when another begins) count as overlapping. A successful activation moves the contract to `ACTIVE` and increments its `version`.

Renewal extends a live contract. Renewing requires the contract to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and its vendor to be `ACTIVE` (otherwise `ERR_VENDOR_SUSPENDED`). It is additionally gated by time: the server's current instant must fall within the renewal window, meaning at or after the point `renewal_notice_days` before `term_end` and at or before `term_end` itself. Outside that window the renewal is rejected with `ERR_OUTSIDE_RENEWAL_WINDOW`; the `auto_renew` flag does not waive this check. A successful renewal is a self-loop — the contract stays `ACTIVE` — but it pushes `term_end` forward by `renewal_term_months` months, increments `renewal_count` by one, and increments the contract's `version`.

Terminating an `ACTIVE` contract (rejected with `ERR_INVALID_STATE` from any other state) closes it out. Termination sets `status` to `TERMINATED`, and it cascades: every `Service` governed by the contract that is not already `RETIRED` is moved to `RETIRED`. The contract's `monthly_committed_cost_cents` is then recomputed (retired services no longer count), and the contract's `version` is incremented.

The server keeps a **logical clock** that governs every time-sensitive check, including the renewal window. At startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time. A `SystemAdmin` may advance or set the clock by supplying a `to_iso8601` instant; the operation echoes back the new `current_utc`. All temporal comparisons — renewal windows, realized-savings horizons — read this clock.

A per-contract reporting rollup answers "how much has this contract saved and recovered." It returns the `contract_id` together with `total_projected_savings_cents` (the sum of the `projected_savings_cents` across the contract's recommendations), `total_realized_savings_cents` (the sum of `realized_savings_cents` across implemented recommendations), the contract's `total_recovered_cents`, and its current `monthly_committed_cost_cents`.

### 3.2. Service Inventory, Utilization, and Shadow IT

A **service** is a single line of recurring spend under a contract — a telecom circuit, a block of SaaS seats, a metered tool. A `Sourcing` operator adds one by naming its `contract_id` and describing it: `service_type` is either `TELECOM_LINE` or `SAAS_SUBSCRIPTION`; `license_type` is one of `PER_SEAT`, `FLAT`, or `USAGE_BASED`; `unit_rate_cents` is the contracted monthly rate per unit or seat; and `contracted_quantity` is the number of units committed. Optionally the caller supplies `active_quantity` (the count of units currently assigned or in use, defaulting to 0), `discovery_source` (either `SANCTIONED` or `SHADOW_IT`, defaulting to `SANCTIONED`, where `SHADOW_IT` flags an unsanctioned SaaS discovery), and `sanctioned` (a boolean defaulting to true indicating IT approval). A new service opens in `ACTIVE` status.

Every service tracks a **utilization** figure, `utilization_pct`, computed as the active quantity divided by the contracted quantity, expressed as a percentage and rounded half up to two decimal places; when `contracted_quantity` is zero the utilization is defined to be 0 (avoiding division by zero). Utilization is computed when the service is created and is re-evaluated whenever the service is considered for a rightsizing recommendation.

Creating a service also refreshes its parent contract's `monthly_committed_cost_cents`. That committed cost is the sum, across all services of the contract whose `status` is either `ACTIVE` or `RIGHTSIZED`, of each service's `unit_rate_cents` multiplied by its `contracted_quantity`. Services in `RETIRED` status are excluded from the sum. This figure is exact integer cents and is recomputed every time a service's contracted quantity or status changes.

### 3.3. Optimization Recommendations and Rightsizing

An `Analyst` who spots waste proposes a **recommendation** against a service. The proposal names a `rec_type` — `DOWNGRADE_SEATS` to cut committed units, `TERMINATE` to end the service, or `SANCTION` to formally approve a discovered service — a `target_quantity` (the proposed new contracted quantity; supply 0 for `TERMINATE`, and leave it unchanged from the current contracted quantity for `SANCTION`), and `expected_service_version` for the concurrency check described in §2.6. A new recommendation opens in `PROPOSED` status.

Creating a recommendation runs several steps. First the concurrency guard: `expected_service_version` must equal the service's current `version`, else `ERR_STALE_VERSION`. For a `DOWNGRADE_SEATS` proposal there is an eligibility gate — the service's `utilization_pct` must be at or below 70.00 percent; a downgrade proposed on a service utilized above that threshold is rejected with `ERR_UTILIZATION_ABOVE_THRESHOLD` (the boundary value of exactly 70.00 is eligible). The system then computes the recommendation's `projected_savings_cents`, records the proposal, and supersedes competition: any prior `PROPOSED` recommendation on the same service is moved to `SUPERSEDED`. Finally, the service's `version` is incremented — which is precisely why a second create still carrying the old `expected_service_version` will fail the concurrency check. Recommendations for a service can be listed and narrowed by a `status` filter.

**Projected savings** are forward-looking and annualized. Let the number of seats cut be the service's current `contracted_quantity` minus the recommendation's `target_quantity` (never negative). The `projected_savings_cents` is that seat count multiplied by the service's `unit_rate_cents` and then multiplied by 12 months. The multiplication is exact; no rounding is applied.

A `FinanceApprover` decides a proposal. Implementing a recommendation requires it to be `PROPOSED` and its service to still be `ACTIVE` (otherwise `ERR_INVALID_STATE`). Implementation first computes the recommendation's `realized_savings_cents`, then applies the change to the service, then recomputes the parent contract's `monthly_committed_cost_cents`. For a `DOWNGRADE_SEATS`, the service's `contracted_quantity` is set to the `target_quantity` and its `status` becomes `RIGHTSIZED`; for a `TERMINATE`, the `contracted_quantity` is set to 0 and the service's `status` becomes `RETIRED`. In every case the service's `version` is incremented and the recommendation moves to `IMPLEMENTED`. Alternatively, rejecting a `PROPOSED` recommendation simply moves it to `REJECTED` with no effect on the service.

**Realized savings** are chronological rather than annualized: they count only the months remaining between the logical clock's current date and the contract's `term_end`, inclusive of both the starting and ending months. Concretely, the number of months remaining is twelve times the difference in years between `term_end` and now, plus the difference in their month numbers, plus one (so a term ending in the same month as implementation yields one month). The `realized_savings_cents` is the seats cut multiplied by the service's `unit_rate_cents` multiplied by that months-remaining count, computed exactly with no rounding. Realized savings equal projected savings only when exactly twelve months remain; otherwise the two diverge.

### 3.4. Invoice Intake, Line Items, and Expected-Amount Reconciliation

An `Analyst` records an incoming vendor bill as an **invoice** by naming its `contract_id` and the billing period it covers (`period_start` and `period_end`). A fresh invoice opens in `RECEIVED` status with all of its computed money fields — `billed_amount_cents`, `expected_amount_cents`, `variance_cents`, `net_amount_cents`, and `balance_due_cents` — at zero, and with `approved_by_user_id` unset.

The invoice is fleshed out with **line items**, each recording one service's charge for one sub-period. A line item names the `service_id` it bills, its own `billing_period_start` and `billing_period_end` (a *half-open* interval — the start is included, the end is excluded), the `billed_quantity`, and the vendor's `billed_amount_cents` for the line. Two line items for the same service may not cover overlapping half-open periods; a new line whose period overlaps an existing line for that service is rejected with `ERR_BILLING_PERIOD_OVERLAP`. Because the interval is half-open, two lines that abut exactly (one ending where the next begins) do *not* overlap and are both allowed. On creation a line opens in `BILLED` status, its `credited_amount_cents` starts at zero, and the system computes a **provisional** `expected_amount_cents` for it; the invoice's `billed_amount_cents` and `net_amount_cents` are then refreshed to reflect the new line.

The **expected amount** for a line is what the contract says the enterprise should have paid, and it is computed in two variants. At line creation the *provisional* variant is used: the quantity is the service's `contracted_quantity`, the billed-days count is taken as a full cycle of 30 days, and the proration factor is therefore 1.0. At invoice review (below) the *final* variant is used: the quantity is the line's own `billed_quantity`, the billed-days count is the actual number of days in the line's half-open period (the end date minus the start date), and the proration factor is that day count divided by 30.

Both variants share the same shape. Start from a base equal to the service's `unit_rate_cents` multiplied by the relevant quantity. If the contract has `volume_tier_enabled` set to true, apply a volume-tier discount selected from a ladder by that same quantity: a quantity of at least 100 units earns a 15 percent discount, at least 50 earns 10 percent, at least 10 earns 5 percent, and anything below 10 earns no discount; when the contract does not enable volume tiers, the discount is zero. Multiply the base by one minus the discount fraction, then by the proration factor, and round that result half up to whole cents. Finally, if the service's `service_type` is `SAAS_SUBSCRIPTION`, add a flat platform fee of 5,000 cents (50 dollars); telecom lines add no platform fee. The rounding is applied once, to the discounted and prorated base, *before* the integer platform fee is added. Note that because the final variant re-selects the tier discount using the line's `billed_quantity` rather than the contracted quantity, the final expected amount can land in a different tier than the provisional one.

Reviewing an invoice moves it from `RECEIVED` to `UNDER_REVIEW`; attempting review on an invoice not in `RECEIVED` is rejected with `ERR_INVOICE_NOT_REVIEWABLE`, and the parent contract must be `ACTIVE` or the review fails with `ERR_CONTRACT_NOT_ACTIVE`. Review recomputes the *final* `expected_amount_cents` and the `variance_cents` for every line item — a line's `variance_cents` being its `billed_amount_cents` minus its final `expected_amount_cents` — and then recomputes the invoice-level aggregates: `billed_amount_cents` as the sum of the lines' billed amounts, `expected_amount_cents` as the sum of the lines' final expected amounts, `variance_cents` as billed minus expected, `net_amount_cents` as billed minus the total credited across the lines, and `balance_due_cents` equal to the net amount while the invoice is unpaid. The invoice's `version` is incremented on review. Each line's own `net_amount_cents` is its `billed_amount_cents` minus its `credited_amount_cents`.

### 3.5. Disputes, Vendor Negotiation, and Credit Recovery

When a line looks over-billed, an `Analyst` opens a **dispute** against it. The dispute names its `invoice_line_item_id`, the `disputed_amount_cents` being contested, and the `claimed_credit_cents` the analyst is seeking; a free-text `reason` is optional. A dispute may only be opened on a line in `BILLED` status whose parent invoice is currently `UNDER_REVIEW` or `DISPUTED`; if the line is not `BILLED`, or the invoice is in neither of those states, the request is rejected with `ERR_LINE_NOT_DISPUTABLE`. The claimed credit may not exceed the line's `billed_amount_cents`; a claim above it is rejected with `ERR_CREDIT_EXCEEDS_BILLED`. Opening a dispute puts it in `SUBMITTED` status with `offered_credit_cents` and `recovered_credit_cents` at zero, `response_type` of `NONE`, and `round_count` at zero. It also drives the line's `status` to `DISPUTED`, and it bubbles up: an invoice sitting in `UNDER_REVIEW` is moved to `DISPUTED` when one of its lines enters dispute.

The negotiation is a cycle. The **vendor** responds by supplying a `response_type` — `FULL_ACCEPT`, `PARTIAL`, or `REJECT` — and an `offered_credit_cents`. A vendor may respond only while the dispute is in `SUBMITTED` or `RESUBMITTED` (otherwise `ERR_DISPUTE_NOT_RESPONDED`), and the offered credit may not exceed the current `claimed_credit_cents`, else `ERR_OFFER_EXCEEDS_CLAIM`. A response records the classification and offer and moves the dispute to `VENDOR_RESPONDED`. If the analyst is unsatisfied, they **resubmit** to open another round: resubmission is allowed only from `VENDOR_RESPONDED` (otherwise `ERR_DISPUTE_NOT_RESPONDED`), only while `round_count` is below the cap of 2 rounds (`ERR_MAX_ROUNDS_EXCEEDED` once the cap is reached), and only if the revised `claimed_credit_cents` supplied in the body still does not exceed the line's `billed_amount_cents` (`ERR_CREDIT_EXCEEDS_BILLED`). A resubmission overwrites `claimed_credit_cents`, increments `round_count` by one, and moves the dispute to `RESUBMITTED` — from which the vendor may respond again, forming the `VENDOR_RESPONDED → RESUBMITTED → VENDOR_RESPONDED` negotiation loop.

Accepting closes the negotiation in the enterprise's favor and triggers the system's deepest cascade. Acceptance is permitted only from `VENDOR_RESPONDED` (otherwise `ERR_DISPUTE_NOT_RESPONDED`). On accept, the dispute's `recovered_credit_cents` is set to its `offered_credit_cents` and the dispute moves to `ACCEPTED`. A **credit** ledger entry is created — carrying its `dispute_id`, its `invoice_line_item_id`, an `amount_cents` equal to the accepted `offered_credit_cents`, and a `status` of `ISSUED` (credits are append-only and never leave `ISSUED`). The credited line moves from `DISPUTED` to `CREDITED`: the credit amount is added to the line's `credited_amount_cents`, and the line's `net_amount_cents` is recomputed as `billed_amount_cents` minus `credited_amount_cents`. The parent contract's `total_recovered_cents` has the credit amount added to it, and the parent invoice's `net_amount_cents` and `balance_due_cents` are recomputed. Any allocations already created on that line — whether still `DRAFT` or already `POSTED` — are moved to `REVERSED`, because the amount they charged back is no longer the correct net. Finally, if that was the last open dispute on the invoice, the invoice reverts from `DISPUTED` back to `UNDER_REVIEW`.

Alternatively, an analyst may **withdraw** a dispute, abandoning the claim. Withdrawal is allowed from `SUBMITTED`, `VENDOR_RESPONDED`, or `RESUBMITTED`, and moves the dispute to `WITHDRAWN`. It returns the line from `DISPUTED` back to `BILLED` with no change to its `credited_amount_cents` or `net_amount_cents`, and — like acceptance — if no open disputes remain on the invoice, the invoice reverts from `DISPUTED` to `UNDER_REVIEW`. Crucially, withdrawal creates no credit, so the contract's `total_recovered_cents` is left untouched: an open-then-withdraw cycle is a no-op on the recovery ledger. The invoice revert edge — from `DISPUTED` back to `UNDER_REVIEW` — fires only when no dispute on the invoice remains in `SUBMITTED`, `VENDOR_RESPONDED`, or `RESUBMITTED`, and when it fires it recomputes the invoice's `net_amount_cents` and `balance_due_cents` and increments the invoice's `version`. Credits and disputes can each be retrieved; the credits list may be filtered by `dispute_id` or by `invoice_line_item_id`, and the general line-item list may be filtered by `invoice_id` or by `service_id`.

### 3.6. Chargeback Allocation and Cost Centers

Each net charge is distributed back to the **cost centers** that consumed it. A `SystemAdmin` sets up a cost center with a `code` (unique across cost centers), a `gl_account` (the general-ledger account chargebacks post to), and an `owner_user_id` identifying the `CostCenterOwner` empowered to approve charges here. A cost center opens in `ACTIVE` status and can be moved to `FROZEN` by a `SystemAdmin`; freezing an already-`ACTIVE` cost center sets its `status` to `FROZEN` and increments its `version`, and a `FROZEN` cost center blocks allocation approval.

An `Analyst` creates the chargeback set for a single line item in one bulk request whose body carries an `allocations` array; each entry names a `cost_center_id` and a `weight_pct` (a percentage share between 0 and 100, two decimals). The weights across the set must sum to exactly 100.00, or the whole request is rejected with `ERR_INVALID_WEIGHT_SUM`. The system then splits the line's current `net_amount_cents` into per-cost-center shares using a pinned rounding order. For each allocation, the raw share is the line's net amount multiplied by that allocation's `weight_pct` divided by 100; each raw share is rounded half up to whole cents *individually first*. The signed remainder — the line's net amount minus the sum of the rounded shares, which may be positive or negative — is then assigned in its entirety to the single allocation with the highest `weight_pct` (ties broken by the earliest cost center `created_at`). That top-weight allocation's `amount_cents` is its rounded share plus the remainder; every other allocation's `amount_cents` is simply its own rounded share. This round-each-share-then-reconcile-to-top order is mandatory — a naive sum-then-round is explicitly not used — and it guarantees the shares' `amount_cents` sum exactly to the line's `net_amount_cents`. Every allocation opens in `DRAFT` status.

The owning `CostCenterOwner` approves a draft allocation. Approval requires the allocation to be in `DRAFT` (otherwise `ERR_INVALID_STATE`); the caller's `X-User-ID` must equal the target cost center's `owner_user_id`, or the request is rejected with `ERR_NOT_COST_CENTER_OWNER`; and the cost center must be `ACTIVE` — an allocation against a `FROZEN` cost center is rejected with `ERR_COST_CENTER_FROZEN`. A successful approval moves the allocation to `POSTED` and increments its `version`. Allocations do not stay posted forever: when the line they charge back is credited by an accepted dispute, both `DRAFT` and `POSTED` allocations on that line are moved to `REVERSED`. When a `POSTED` allocation is reversed this way, the chargeback for the line must be re-created against the line's new, lower `net_amount_cents`.

### 3.7. Invoice Approval, Payment, and Separation of Duties

Once an invoice has been reviewed and any disputes resolved, a `FinanceApprover` approves it. Approval is permitted only from `UNDER_REVIEW` — an invoice in any other state (including `DISPUTED`, which by construction means an open dispute still exists) is rejected with `ERR_INVALID_STATE` — and the parent contract must be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`. Approval moves the invoice to `APPROVED`, records the approving operator's `X-User-ID` in `approved_by_user_id`, and increments the invoice's `version`.

Payment is deliberately kept separate from approval. Paying an invoice is allowed only from `APPROVED` (otherwise `ERR_INVOICE_NOT_APPROVED`), and it enforces **separation of duties**: the paying `FinanceApprover`'s `X-User-ID` must differ from the `approved_by_user_id` recorded at approval. If the same person who approved the invoice attempts to pay it, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful payment moves the invoice to `PAID`, sets its `balance_due_cents` to 0, and increments its `version`.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`; all other successful operations — reads, state transitions, and other mutations — return HTTP 200. "All roles" below denotes the six roles `Sourcing`, `Analyst`, `FinanceApprover`, `CostCenterOwner`, `Vendor`, and `SystemAdmin`; the request bodies, computed side effects, and preconditions for each write are specified in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | SystemAdmin |
| POST | `/vendors` | Create a vendor (starts ACTIVE) | Sourcing |
| GET | `/vendors/{id}` | Fetch a vendor | All roles |
| POST | `/vendors/{id}/suspend` | Suspend a vendor | Sourcing |
| GET | `/vendors/{id}/contracts` | List a vendor's contracts | All roles |
| POST | `/contracts` | Create a contract (starts DRAFT) | Sourcing |
| GET | `/contracts/{id}` | Fetch a contract | All roles |
| POST | `/contracts/{id}/activate` | Activate a DRAFT contract | Sourcing |
| POST | `/contracts/{id}/renew` | Renew an ACTIVE contract | Sourcing |
| POST | `/contracts/{id}/terminate` | Terminate a contract; cascade services to RETIRED | Sourcing |
| GET | `/contracts/{id}/services` | List services under a contract | All roles |
| GET | `/contracts/{id}/invoices` | List invoices under a contract | All roles |
| GET | `/contracts/{id}/savings-summary` | Savings and recovery rollup for a contract | All roles |
| POST | `/services` | Create a service under a contract | Sourcing |
| GET | `/services/{id}` | Fetch a service | All roles |
| POST | `/services/{id}/recommendations` | Propose an optimization recommendation | Analyst |
| GET | `/services/{id}/recommendations` | List a service's recommendations | All roles |
| POST | `/recommendations/{id}/implement` | Implement a proposed recommendation | FinanceApprover |
| POST | `/recommendations/{id}/reject` | Reject a proposed recommendation | FinanceApprover |
| POST | `/invoices` | Create an invoice (starts RECEIVED) | Analyst |
| GET | `/invoices/{id}` | Fetch an invoice | All roles |
| POST | `/invoices/{id}/line-items` | Add a line item to an invoice | Analyst |
| POST | `/invoices/{id}/review` | Move an invoice to UNDER_REVIEW | Analyst |
| POST | `/invoices/{id}/approve` | Approve an invoice | FinanceApprover |
| POST | `/invoices/{id}/pay` | Pay an approved invoice | FinanceApprover |
| GET | `/invoice-line-items/{id}` | Fetch a line item | All roles |
| GET | `/invoice-line-items` | List line items (filter by invoice or service) | All roles |
| GET | `/invoice-line-items/{id}/disputes` | List disputes on a line item | All roles |
| GET | `/invoice-line-items/{id}/allocations` | List allocations on a line item | All roles |
| POST | `/invoice-line-items/{id}/disputes` | Open a dispute on a line item | Analyst |
| POST | `/invoice-line-items/{id}/allocations` | Bulk-create the chargeback set for a line | Analyst |
| POST | `/disputes/{id}/respond` | Vendor responds to a dispute | Vendor |
| POST | `/disputes/{id}/resubmit` | Start another negotiation round | Analyst |
| POST | `/disputes/{id}/accept` | Accept the vendor offer; issue a credit | Analyst |
| POST | `/disputes/{id}/withdraw` | Withdraw a dispute | Analyst |
| GET | `/credits/{id}` | Fetch a credit | All roles |
| GET | `/credits` | List credits (filter by dispute or line item) | All roles |
| POST | `/cost-centers` | Create a cost center (starts ACTIVE) | SystemAdmin |
| GET | `/cost-centers/{id}` | Fetch a cost center | All roles |
| POST | `/cost-centers/{id}/freeze` | Freeze a cost center | SystemAdmin |
| GET | `/cost-centers/{id}/allocations` | List allocations charged to a cost center | All roles |
| POST | `/allocations/{id}/approve` | Post a draft allocation | CostCenterOwner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_SERVICE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_COST_CENTER_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_RECOMMENDATION_NOT_FOUND` | 404 |
| `ERR_CREDIT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LINE_NOT_DISPUTABLE` | 409 |
| `ERR_INVOICE_NOT_REVIEWABLE` | 409 |
| `ERR_DISPUTE_NOT_RESPONDED` | 409 |
| `ERR_INVOICE_NOT_APPROVED` | 409 |
| `ERR_VENDOR_SUSPENDED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_COST_CENTER_FROZEN` | 409 |
| `ERR_OUTSIDE_RENEWAL_WINDOW` | 422 |
| `ERR_CONTRACT_TERM_OVERLAP` | 409 |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 |
| `ERR_INVALID_WEIGHT_SUM` | 422 |
| `ERR_UTILIZATION_ABOVE_THRESHOLD` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_MAX_ROUNDS_EXCEEDED` | 409 |
| `ERR_NOT_COST_CENTER_OWNER` | 403 |
| `ERR_CREDIT_EXCEEDS_BILLED` | 422 |
| `ERR_OFFER_EXCEEDS_CLAIM` | 422 |
| `ERR_STALE_VERSION` | 412 |

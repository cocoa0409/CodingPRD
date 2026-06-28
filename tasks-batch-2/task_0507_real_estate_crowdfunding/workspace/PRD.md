# Real Estate Crowdfunding API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Real Estate Crowdfunding API, a back-office platform that lets sponsors raise capital from retail and accredited investors into pooled real-estate vehicles (in the style of an eREIT or interval fund). The platform models the full investing lifecycle: an investor registers and is screened for suitability, commits capital to a share class through an ACH subscription, has that funding settle into a tradable holding priced against the fund's net asset value, receives quarterly dividends that may be reinvested, and eventually redeems shares — subject to a queue, a quarterly cap, and an early-withdrawal penalty schedule.

Because the platform handles regulated capital and issues tax documents, correctness is not merely a convenience; it is a compliance obligation. Net asset value must reconcile against the shares actually outstanding after every cash event, a non-accredited investor must never be allowed to exceed their annual investment cap, capital must be conserved across settlement and reversal so that the books always balance, and the people who declare valuations must remain organizationally separate from the people who clear investors for investment. The sections below define the data model, the lifecycle state machines, the pricing and allocation arithmetic, and the validation order that together make those guarantees enforceable.

A note on money and time: all monetary amounts in this system are integers denominated in cents, and the server runs against a logical clock so that tax-year stamping is deterministic during testing rather than tied to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request, with two exceptions, must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The two exceptions are investor self-registration and any GET endpoint explicitly flagged as anonymous. When either header is missing, or when `X-User-Role` does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five roles: `FundManager`, `ComplianceOfficer`, `Operator`, `Investor`, and `Anonymous`.

A `FundManager` creates and manages funds, share classes, projects, valuations, and distributions, and drives their lifecycle transitions. A `ComplianceOfficer` reviews investor suitability and issues tax documents. An `Operator` is the back-office actor that settles and reverses ACH subscriptions, pays distributions, runs redemption sweeps and windows, and force-fulfills individual redemptions. An `Investor` is a self-registering principal who acts only on their own subscriptions, redemptions, and holdings. `Anonymous` is an unauthenticated caller who may do nothing but register as an investor.

The platform enforces a strict **segregation of duties** between the `FundManager` who declares valuations and distributions and the `ComplianceOfficer` who clears investors: these are distinct roles and a single request always acts under exactly one of them.

Identity binding differs by role. When `X-User-Role` is `Investor`, the identity is **entity-backed**: `X-User-ID` is the `id` of the acting `Investor`, and any ownership check on a subscription, redemption request, or holding compares that resource's owning investor (its `investor_id`, directly or by way of the holding it references) against `X-User-ID`. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `FundManager`, `ComplianceOfficer`, `Operator`, or `Anonymous`, the identity is **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. The server may, however, *record* an opaque identifier where a transition calls for an audit trail — specifically, suitability review writes the acting `ComplianceOfficer`'s `X-User-ID` into the investor's `reviewed_by_user_id` field — without that recording implying any ownership relationship.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless an endpoint states otherwise, list results are ordered by their creation timestamp ascending. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at its initial value on creation and increments by one on each mutation.

Two entity types are deliberately leaner. A `Valuation` and a `DistributionAllocation` are immutable audit records minted once and never modified; each carries only `id` and `created_at`, and neither has an `updated_at` field nor a `version` field. Likewise a `TaxDocument` is a generated artifact carrying only `id` and `created_at` — no `updated_at`, no `version`. Every other entity — `Fund`, `ShareClass`, `Project`, `Investor`, `Subscription`, `Holding`, `Distribution`, and `RedemptionRequest` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

A subtle but important consequence of versioning: when a single operation cascades across several entities, **each** affected entity independently has its `version` incremented and its `updated_at` refreshed. The derived-field updates that accompany a cascade (for example, recomputing a fund's NAV) are themselves mutations and so participate in this version bump.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many paths nest a child under a parent, such as a fund's valuations or a holding's allocations. For any such request the server validates path identifiers strictly left to right: the parent must be resolved before the child is even looked up, and the first identifier in the path that does not resolve produces `ERR_NOT_FOUND` (HTTP 404). After path identifiers are resolved, any foreign keys carried in the request body are validated in turn; a body reference to a non-existent fund, share class, project, investor, subscription, holding, distribution, or redemption likewise yields `ERR_NOT_FOUND`.

### 2.6. Optimistic Concurrency on Capital-Sensitive Creates

Two create operations are priced or sized against a parent whose state can move underneath the client, and both are guarded by optimistic concurrency control.

Creating a subscription is guarded against a stale view of the fund. The subscription-create request must carry `expected_fund_version` holding the client's last observed `version` of the parent `Fund` (the fund that owns the targeted share class). If the fund's current `version` differs from `expected_fund_version` — which happens whenever another writer has posted a valuation or settled a subscription since the client last read the fund, since both of those advance `Fund.version` and move the NAV — the create is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412). This prevents the client from pricing a subscription provisionally against a NAV it never actually observed.

Creating a redemption request is guarded against a stale view of the holding. The redemption-create request must carry `expected_holding_version` holding the client's last observed `version` of the parent `Holding`. If the holding's current `version` differs from `expected_holding_version` — which happens whenever another writer has settled a DRIP distribution into the holding, reversed a subscription, or fulfilled a prior redemption against it, since each advances `Holding.version` and changes `shares_owned` — the create is rejected with `ERR_STALE_HOLDING_VERSION` (HTTP 412). This prevents the client from sizing a redemption against a share balance it never actually observed.

No other endpoint takes a version field; only these two creates carry an `expected_*_version`, and on those two it is a required input, not an optional one.

### 2.7. Monetary Precision and Rounding

All money is stored and returned as integer cents. Share quantities (`shares_owned`, `shares_allocated`, `shares_outstanding`, `shares_requested`, `drip_shares`, `drip_shares_minted`) are carried to four decimal places. Per-share dividend rates (`dividend_per_share_cents`) are likewise expressed to up to four decimal places, so a value of 1.5 means one and one-half cents per share. Wherever a computation must reduce a fractional result to a stored value, the system rounds **half up** (a value exactly halfway between two representable results rounds to the larger magnitude): cent amounts round half up to whole cents, and share quantities round half up to four decimal places. Where a calculation prescribes a specific evaluation order or a specific rounding boundary, that order is binding and is described with the calculation in Section 3.

### 2.8. Capital Conservation and NAV Reconciliation

The platform treats `total_capital_cents` on a fund as a **conserved quantity**: it is a running ledger of capital that has entered (settled subscriptions add their funded amount) and left (fulfilled redemptions subtract their gross value) the vehicle, and a reversal of a settlement must restore it to exactly the value it would have held had the settlement never occurred. Independently, a fund's `shares_outstanding` and `nav_per_share_cents` are **derived fields** that must be recomputed after every cash event that mints or burns shares — settlement, reversal, redemption fulfillment, and DRIP minting all trigger a recompute so that NAV always reflects the shares genuinely outstanding at that instant. These recomputations are part of the triggering request and are committed atomically with it.

### 2.9. The Logical Clock

The server keeps a logical UTC clock used to stamp the tax year of settled subscriptions. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it remains at that default and never falls back to the host's wall-clock time. A `FundManager` or an `Operator` may advance the clock by supplying a `to_iso8601` instant; this is a test-driving capability with no business side effects beyond changing what "now" means for subsequent tax-year stamping.

## 3. Business Logic & Workflows

### 3.1. Funds, Valuations, and the NAV

A `FundManager` opens a vehicle by creating a `Fund` with a display `name` and a `vehicle_type`, which is one of `REIT` or `PARTNERSHIP`. The vehicle type is consequential well beyond display: it determines the kind of tax document the fund later issues, with a `REIT` producing a 1099-DIV and a `PARTNERSHIP` producing a K-1. At creation the manager also supplies the fund's opening `gross_asset_value_cents` and `total_liabilities_cents`, each a non-negative cent amount. A newly created fund is `OPEN`; the system initializes its `shares_outstanding` to 0, its `total_capital_cents` to 0, and its `current_valuation_seq` to 0, and bootstraps its `nav_per_share_cents` to 1000 — that is, ten dollars par per share — because no shares yet exist to divide the net asset value across.

The **net asset value per share** is the heart of the pricing model. It is computed by taking the fund's net assets — its `gross_asset_value_cents` minus its `total_liabilities_cents` — and dividing by `shares_outstanding`, rounding the quotient half up to whole cents. When `shares_outstanding` is zero, that division is undefined, so the NAV instead takes the par bootstrap value of 1000 cents. This same computation is re-run after every settlement, reversal, redemption fulfillment, and DRIP minting, always reading the fund's then-current net assets and then-current shares outstanding.

The fund's `shares_outstanding` is itself derived: it is the sum, to four decimal places, of `shares_owned` across every `Holding` whose share class belongs to this fund and whose balance is positive (holdings at zero shares contribute nothing). The accumulated sum is rounded half up to four decimal places. This reconciliation runs after every settlement, reversal, redemption fulfillment, and DRIP minting — the same events that move the NAV.

Each quarter a `FundManager` posts a `Valuation` against the fund, identified by a `period_label` such as `2026-Q1` that must be unique within the fund; a duplicate label is rejected with `ERR_DUPLICATE` (HTTP 409). The valuation carries fresh `gross_asset_value_cents` and `total_liabilities_cents` for the quarter. Posting a valuation does several things atomically: it assigns the valuation a monotonic per-fund `seq` (the first valuation on a fund is `seq` 1, and each subsequent posting is one greater), it overwrites the fund's own `gross_asset_value_cents` and `total_liabilities_cents` with the posted figures, it advances the fund's `current_valuation_seq` to match, it recomputes `nav_per_share_cents` from the newly written net assets, and it freezes that just-computed NAV onto the valuation record as `resulting_nav_per_share_cents` so the historical price for that quarter is preserved. The fund's `version` is incremented. Each posted valuation represents one elapsed quarter, a fact the redemption penalty schedule later relies on.

A fund moves through `OPEN`, `CLOSED_TO_NEW`, and `WINDING_DOWN`. A `FundManager` may close a fund to new money, transitioning `OPEN → CLOSED_TO_NEW`, which is permitted only from `OPEN` and which increments the fund's `version`; once closed to new money the fund accepts no new subscriptions, though subscriptions already in flight may still settle. A `FundManager` may also wind a fund down, transitioning it to `WINDING_DOWN` from either `OPEN` or `CLOSED_TO_NEW`. Winding down is terminal and is the origin of a cascade described in Section 3.7. Any of these transitions attempted from a state in which they are not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

A fund report capability is a computed read that returns the fund alongside its project-level rollup — per-project status and values — so that fund-level NAV and capital can be reviewed together with the underlying assets.

### 3.2. Share Classes and Underlying Projects

Within a fund a `FundManager` defines one or more share classes. A `ShareClass` is created under its parent fund and carries a `class_code` that must be unique within that fund — a collision is rejected with `ERR_DUPLICATE`. The class also carries a `min_investment_cents` floor (a non-negative cent amount that a single subscription must meet), an `mgmt_fee_bps` management fee expressed in basis points between 0 and 1000 inclusive (informational only; this API never deducts it), an `accredited_only` flag, and a `drip_eligible` flag. When `accredited_only` is omitted it defaults to false; when `drip_eligible` is omitted it defaults to true. Internally each share class records its parent `fund_id`. A new share class begins `OFFERING`.

A share class moves among `OFFERING`, `SUSPENDED`, and `CLOSED`. A `FundManager` may suspend an offering, transitioning `OFFERING → SUSPENDED`; this is allowed only when the class is currently `OFFERING` and its parent fund is not `WINDING_DOWN`, and it increments the share class's `version`. A suspended class blocks new subscriptions while letting in-flight subscriptions settle. The manager may resume a suspended class, transitioning `SUSPENDED → OFFERING`; this is allowed only when the class is `SUSPENDED` and its parent fund is `OPEN`, and it increments the share class's `version`. The offering-to-suspended-and-back cycle may repeat. A share class also reaches the terminal `CLOSED` state as a system-driven consequence of its fund winding down, never by direct request. Transitions attempted out of an ineligible state are rejected with `ERR_INVALID_STATE`.

Separately, a `FundManager` records the real-estate assets a fund holds as `Project` records, each created under its parent fund and carrying its `fund_id`, a non-empty `name`, an `acquisition_cost_cents`, and an `appraised_value_cents` (both non-negative cent amounts). A project tracks its own lifecycle for project-level reporting and starts `ACQUIRED`. A `FundManager` may stabilize an acquired project, transitioning `ACQUIRED → STABILIZED` (allowed only from `ACQUIRED`), and may dispose of a project, transitioning it to `DISPOSED` from either `STABILIZED` or directly from `ACQUIRED`. Disposal is terminal, and each project transition increments the project's `version`. An out-of-state transition yields `ERR_INVALID_STATE`.

### 3.3. Investor Onboarding and Suitability Review

An investor enters the platform by self-registration, which is the one write any `Anonymous` caller may perform. Registration supplies an `email` (globally unique; a duplicate is rejected with `ERR_DUPLICATE`), a `full_name`, an optional `accredited_status` of `NON_ACCREDITED` or `ACCREDITED` (defaulting to `NON_ACCREDITED`), and the declared `annual_income_cents` and `net_worth_cents` that will drive the non-accredited investment cap. A freshly registered investor has `suitability_status` of `PENDING` and `ytd_invested_cents` of 0, and its `reviewed_by_user_id` is null until a review occurs.

Suitability is gated by a `ComplianceOfficer`, and only by a `ComplianceOfficer` — never by the `FundManager`, which is the segregation-of-duties boundary in practice. The officer may approve a pending investor, transitioning `suitability_status` from `PENDING` to `APPROVED`; this is allowed only when the investor is `PENDING`, it sets `reviewed_by_user_id` to the acting officer's `X-User-ID`, and it increments the investor's `version`. The officer may instead reject a pending investor, transitioning `PENDING → REJECTED`, which likewise records the reviewing officer in `reviewed_by_user_id` and increments `version`; `REJECTED` is terminal. The officer may also revoke a prior approval, transitioning `APPROVED → PENDING`, which increments `version` and returns the investor to review. Because of that revoke path, an investor may legitimately cycle through approval more than once. Any suitability transition attempted from an ineligible state is rejected with `ERR_INVALID_STATE`.

The investor's `ytd_invested_cents` is a derived figure recomputed after every subscription settlement and every subscription reversal: it is the sum of `funded_amount_cents` across that investor's subscriptions whose `status` is `SETTLED` and whose `tax_year` equals the current UTC year of the logical clock. Reversed subscriptions are excluded from this sum, which is what lets a clawback restore the investor's available cap.

### 3.4. Subscribing and ACH Settlement

The core capital-inflow workflow begins when an `Investor` subscribes to a share class. The subscription payload identifies the `investor_id` (which must equal the acting investor) and the `share_class_id`, commits a `funded_amount_cents` over ACH, may set `drip_elected` to indicate that future dividends on the resulting holding should be reinvested (defaulting to false), and must carry `expected_fund_version` for the optimistic-concurrency guard described in Section 2.6. A subscription is created in `PENDING_ACH`.

Two gates apply at create time before the subscription is accepted. First, new money is only accepted into an open offering: the parent fund must be `OPEN` and the targeted share class must be `OFFERING`. If either is not — for instance, the fund is `CLOSED_TO_NEW` or `WINDING_DOWN`, or the class is `SUSPENDED` or `CLOSED` — the create is rejected with `ERR_OFFERING_NOT_OPEN` (HTTP 409). Additionally, redemption-style activity against a winding-down fund is forbidden, so a subscription create that targets a `WINDING_DOWN` fund is also blocked with `ERR_FUND_WINDING_DOWN` (HTTP 409). Second, the committed amount must meet the floor: `funded_amount_cents` must be at least the share class's `min_investment_cents`, and a shortfall is rejected with `ERR_BELOW_MIN_INVESTMENT` (HTTP 422). At create time the system captures a **provisional** price quote, recording the fund's current `nav_per_share_cents` into the subscription's `provisional_nav_cents`; this quote is purely informational — no shares are minted from it. The corresponding provisional share count is `funded_amount_cents` divided by the captured provisional NAV, rounded half up to four decimal places. Creating the subscription also bumps the parent fund's `version`.

An `Investor` who has not yet funded may cancel an unsettled subscription, transitioning `PENDING_ACH → CANCELLED`; this is allowed only while the subscription is `PENDING_ACH` and only by the investor who owns it (otherwise `ERR_NOT_RESOURCE_OWNER`), it touches no holding and no fund-level conserved quantity, and it increments only the subscription's `version`.

Settlement is where capital actually enters the fund, and it is an `Operator` action that transitions `PENDING_ACH → SETTLED`. Settlement runs a battery of preconditions. The subscription must be `PENDING_ACH`. The investor must have `suitability_status` of `APPROVED`, or the settle is rejected with `ERR_SUITABILITY_NOT_APPROVED` (HTTP 409). If the share class is `accredited_only`, the investor's `accredited_status` must be `ACCREDITED`, or the settle is rejected with `ERR_ACCREDITATION_REQUIRED` (HTTP 409). And if the investor is `NON_ACCREDITED`, their annual cap must not be breached: the cap is ten percent of the larger of the investor's `annual_income_cents` and `net_worth_cents`, rounded half up to whole cents, and the settle is permitted only when the investor's `ytd_invested_cents` plus this subscription's `funded_amount_cents` is less than or equal to that cap. If that sum would exceed the cap, the settle is rejected with `ERR_ANNUAL_CAP_EXCEEDED` (HTTP 409). Accredited investors are not subject to this cap.

When the preconditions pass, settlement prices and mints atomically. It captures `settled_nav_cents` as the fund's `nav_per_share_cents` at the settlement instant — the **final** price, which diverges from the earlier provisional quote whenever a valuation posted between create and settle. It mints `shares_allocated` as `funded_amount_cents` divided by `settled_nav_cents`, rounded half up to four decimal places. It then upserts the investor's `Holding` for this `investor_id` and `share_class_id`: a matching holding has its `shares_owned` increased by `shares_allocated` and its `cost_basis_cents` increased by `funded_amount_cents`, and if no holding exists yet one is created. On the **first** settlement into a holding, the holding's `first_acquired_seq` is set to the fund's `current_valuation_seq` at that moment, anchoring the age tier used later for redemption penalties. The subscription's `holding_id` is set to the id of that upserted holding so the cascade-created holding is discoverable from the settle response. The fund's `shares_outstanding` and `nav_per_share_cents` are recomputed, and the fund's `total_capital_cents` is increased by `funded_amount_cents` to honor capital conservation. The subscription's `tax_year` is stamped with the current UTC year of the logical clock, and the investor's `ytd_invested_cents` is recomputed. The subscription's `version`, the holding's `version`, and the fund's `version` are each incremented by one.

Settlement also assesses an ACH processing fee, computed in a **pinned order** because the waiver depends on a preliminary total that itself depends on the raw fee. First, the raw fee is the larger of one hundred cents and the product of `funded_amount_cents` and the ACH rate of eight-tenths of one percent (0.008), that product rounded half up to whole cents. Second, a preliminary total is formed as `funded_amount_cents` plus that raw fee. Third, the waiver test: if the preliminary total is at least two and a half million cents, the fee is waived to zero; otherwise the fee remains the raw fee. The settled value of `ach_fee_cents` is the post-waiver fee, and `total_charged_cents` is `funded_amount_cents` plus `ach_fee_cents`. The fee defaults to 0 before settlement. It is essential that the waiver threshold is tested against the preliminary total computed from the raw fee, not against the funded amount alone.

An `Operator` may reverse a settled subscription on an ACH clawback, transitioning `SETTLED → REVERSED`. This is allowed only when the subscription is `SETTLED` and when the holding still holds at least the originally allocated shares — that is, `shares_owned` is greater than or equal to the subscription's `shares_allocated`, so that shares already redeemed away below the allocated amount cannot be clawed back. Reversal is the exact inverse of settlement: the holding's `shares_owned` is decreased by `shares_allocated` and its `cost_basis_cents` is decreased by `funded_amount_cents`; the fund's `shares_outstanding` and `nav_per_share_cents` are recomputed; the fund's `total_capital_cents` is decreased by `funded_amount_cents`, restoring the conserved quantity exactly; the investor's `ytd_invested_cents` is recomputed (dropping this now-reversed subscription); and if the holding's `shares_owned` reaches zero, its `first_acquired_seq` is cleared to null. The subscription's `version`, the holding's `version`, and the fund's `version` are each incremented. Cancellation and reversal are deliberately asymmetric: cancellation never touched the conserved quantities and so has nothing to undo, whereas reversal must precisely unwind every effect a settlement applied.

Subscriptions may be listed and filtered by `investor_id`, `share_class_id`, or `holding_id`, and retrieved individually.

### 3.5. Holdings and DRIP Election

A `Holding` is the durable record of an investor's position in a share class, created as a side effect of the first settlement rather than directly. It records its `investor_id` and `share_class_id`, its current `shares_owned` (which grows on settlement and DRIP minting and shrinks on redemption), its cumulative `cost_basis_cents` (funded amounts and reinvested dividends, reduced proportionally on redemption), its `first_acquired_seq` anchor, and a `drip_elected` flag that mirrors the electing subscription's choice. An `Investor` may toggle `drip_elected` on a holding they own; doing so increments the holding's `version`, and acting on a holding the caller does not own is rejected with `ERR_NOT_RESOURCE_OWNER`. Holdings may be listed and filtered by `investor_id` or `share_class_id`, and a holding's distribution allocations may be listed in turn.

### 3.6. Dividends, Distributions, and DRIP

A `FundManager` declares a dividend by creating a `Distribution` under a fund with a `period_label` (unique within the fund — a duplicate yields `ERR_DUPLICATE`) and a positive `dividend_per_share_cents` expressed to up to four decimal places. A distribution begins `DECLARED`, with `total_paid_cents` and `drip_shares_minted` at 0. The manager may cancel a declared distribution, transitioning `DECLARED → CANCELLED`, which creates no allocations, mutates no holding or fund, and increments only the distribution's `version`. An out-of-state transition on a distribution yields `ERR_INVALID_STATE`.

Paying a distribution is an `Operator` action that transitions `DECLARED → PAID`, and it is the origin of a cascade reaching holdings and then the fund. It is permitted only when the distribution is `DECLARED` and only when the fund has at least one posted valuation — that is, the fund's `current_valuation_seq` is at least 1 — because a NAV must exist to price any reinvestment; otherwise it is rejected with `ERR_NO_VALUATION` (HTTP 409). On payment, the system creates one `DistributionAllocation` for each `Holding` in the fund's share classes whose `shares_owned` is positive, processing the eligible holdings in ascending order of their creation timestamp. Each allocation records its parent `distribution_id` and the `holding_id` it pays.

For each eligible holding the **gross dividend** is that holding's `shares_owned` multiplied by the distribution's `dividend_per_share_cents`, rounded half up to whole cents, and stored on the allocation as `gross_dividend_cents`. The allocation's `mode` is `DRIP` when, and only when, the holding has `drip_elected` true *and* its share class is `drip_eligible` *and* the fund's `status` is `OPEN`; in every other case the `mode` is `CASH`. For a `DRIP` allocation the system computes `drip_shares` as `gross_dividend_cents` divided by the fund's `nav_per_share_cents`, rounded half up to four decimal places, then increases that holding's `shares_owned` by `drip_shares` and its `cost_basis_cents` by `gross_dividend_cents`; a `CASH` allocation has `drip_shares` of 0 and reinvests nothing. The distribution's `total_paid_cents` is the **sum of the already-rounded per-holding `gross_dividend_cents`** — each holding's gross is rounded to whole cents first and only then are those rounded amounts summed, never the other way around — and `drip_shares_minted` accumulates the new shares minted across all DRIP allocations. After the DRIP minting, the fund's `shares_outstanding` and `nav_per_share_cents` are recomputed. The distribution's `version`, every affected holding's `version`, and the fund's `version` are each incremented.

A distribution's allocations may be listed, optionally filtered by `holding_id`. Each `DistributionAllocation` is an immutable record.

### 3.7. Redemptions: Queue, Sweep, Penalty, and Wind-Down

An `Investor` requests a redemption by creating a `RedemptionRequest` against a `Holding` they own, supplying the `holding_id`, the `shares_requested` (a positive quantity, no greater than the holding's `shares_owned` at request time), and `expected_holding_version` for the optimistic-concurrency guard. A request that is non-positive or exceeds the available balance is rejected with `ERR_INSUFFICIENT_SHARES` (HTTP 422); a request whose fund is `WINDING_DOWN` is rejected with `ERR_FUND_WINDING_DOWN`; and acting on a holding the caller does not own yields `ERR_NOT_RESOURCE_OWNER`. A new request is assigned a monotonic global `queue_seq` that serves as the FIFO ordering key within a redemption window, begins `QUEUED`, and bumps the parent holding's `version`. The investor may cancel their own request while it is either `QUEUED` or `DEFERRED`, transitioning to `CANCELLED` and incrementing the request's `version`.

Redemptions are not paid instantly; they clear through a sweep that an `Operator` runs over a fund. The sweep walks that fund's `QUEUED` requests in ascending `queue_seq` order (oldest first) and, within a single sweep, accumulates the gross value of the requests it fulfills. The window is bounded by a **quarterly redemption cap**: five percent of the fund's `total_capital_cents` at the start of the sweep, rounded half up to whole cents. A request is fulfilled only when the running fulfilled gross so far plus this request's gross value is less than or equal to the cap; a request that would push the running total above the cap is not fulfilled but instead **deferred**, transitioning `QUEUED → DEFERRED` while retaining its `queue_seq`, with no holding or fund mutation and only its `version` incremented. A deferred request rolls to a later window. The sweep itself is forbidden while the fund is `WINDING_DOWN` (`ERR_FUND_WINDING_DOWN`).

Fulfillment, whether reached through the sweep or through an `Operator`'s single-request force-fulfill, transitions a request `QUEUED → FULFILLED` and prices it as follows. The request must still be `QUEUED`, the fund must not be `WINDING_DOWN`, and the holding's `shares_owned` must be at least the `shares_requested`. The **gross value**, `gross_value_cents`, is `shares_requested` multiplied by the fund's `nav_per_share_cents`, rounded half up to whole cents. The **age** of the position drives the penalty: the position's age in quarters is the fund's `current_valuation_seq` minus the holding's `first_acquired_seq` (each posted valuation having advanced the sequence by one quarter). That age selects a penalty rate in basis points, `penalty_tier_rate_bps`, on a four-tier schedule with inclusive lower bounds: an age of fewer than 4 quarters draws 300 basis points; an age of at least 4 but fewer than 8 quarters draws 200 basis points; an age of at least 8 but fewer than 12 quarters draws 100 basis points; and an age of 12 quarters or more draws 0 basis points (no penalty). Thus, for example, an age of exactly 4 quarters falls into the 200-basis-point tier. The `penalty_cents` is `gross_value_cents` multiplied by the rate in basis points divided by ten thousand, rounded half up to whole cents, and the `net_proceeds_cents` is `gross_value_cents` minus `penalty_cents`.

Fulfillment then cascades: the holding's `shares_owned` is decreased by `shares_requested` and its `cost_basis_cents` is reduced proportionally; the fund's `shares_outstanding` and `nav_per_share_cents` are recomputed; the fund's `total_capital_cents` is decreased by `gross_value_cents` for capital conservation; and the request's `version`, the holding's `version`, and the fund's `version` are each incremented. The single-request force-fulfill is subject to the same cap: if fulfilling that one request would push fulfilled gross above the quarterly cap, the force-fulfill is rejected with `ERR_REDEMPTION_CAP_REACHED` (HTTP 409) rather than silently deferring. The force-fulfill also enforces the share-sufficiency check and so can surface `ERR_INSUFFICIENT_SHARES`.

When a window reopens, an `Operator` moves the fund's deferred requests back into the queue, transitioning each `DEFERRED → QUEUED` and incrementing its `version`, so a deferred request can be picked up by a subsequent sweep. The full cycle is therefore `QUEUED → DEFERRED → QUEUED → (sweep) → FULFILLED`.

Winding a fund down is the cascade origin that ties these pieces together. When a `FundManager` transitions a fund to `WINDING_DOWN`, the system, in the same atomic request, transitions every share class of that fund whose status is `OFFERING` or `SUSPENDED` to `CLOSED` (each incrementing its `version`), and transitions every redemption request against that fund's holdings whose status is `QUEUED` or `DEFERRED` to `REJECTED` (each incrementing its `version`); requests already in a terminal state are left untouched. The fund's own `version` is incremented. `REJECTED` is a terminal outcome for a redemption request that the wind-down reaches.

### 3.8. Tax Documents

After dividends have been paid, a `ComplianceOfficer` or an `Operator` may generate a `TaxDocument` for a given investor, fund, and tax year. The request supplies the `fund_id` and the `tax_year` (which must be at least 2000), and the combination of investor, fund, and tax year must be unique — a repeat yields `ERR_DUPLICATE`. The document's `doc_type` is derived from the fund's `vehicle_type`: a `REIT` produces `FORM_1099_DIV` and a `PARTNERSHIP` produces `FORM_K1`.

The document totals are computed from that investor's paid allocations in the fund for the year. The `ordinary_dividends_cents` is the sum of `gross_dividend_cents` across allocations whose `mode` is `CASH`, that belong to holdings the investor owns within the fund, whose distribution is `PAID`, and whose distribution period falls in the requested `tax_year`. The `reinvested_dividends_cents` is the identical sum but restricted to allocations whose `mode` is `DRIP`. An investor's tax documents may be listed (optionally filtered by `fund_id`), and a fund's issued tax documents may be listed as well.

### 3.9. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so that the failure a caller sees is deterministic. Authentication comes first: missing or unrecognized headers (`ERR_UNAUTHENTICATED`) are caught before anything else. Role authorization (`ERR_FORBIDDEN_ROLE`) is next, followed by resource ownership for entity-backed investors acting on their own subscriptions, redemptions, and holdings (`ERR_NOT_RESOURCE_OWNER`). Existence of all referenced resources is checked next — path identifiers left to right, then body foreign keys (`ERR_NOT_FOUND`). State eligibility for the requested transition follows (`ERR_INVALID_STATE`). The optimistic-concurrency version checks come next on the two guarded creates (`ERR_STALE_FUND_VERSION` for subscription create, `ERR_STALE_HOLDING_VERSION` for redemption create).

After those structural gates, business rules apply in order. For a subscription create, the offering-open check (`ERR_OFFERING_NOT_OPEN`) precedes the minimum-investment floor (`ERR_BELOW_MIN_INVESTMENT`), and a winding-down fund is rejected with `ERR_FUND_WINDING_DOWN`. For a settle, the suitability gate (`ERR_SUITABILITY_NOT_APPROVED`) is checked before the accreditation gate (`ERR_ACCREDITATION_REQUIRED`), which is checked before the annual cap (`ERR_ANNUAL_CAP_EXCEEDED`). Share sufficiency for redemptions (`ERR_INSUFFICIENT_SHARES`), the winding-down prohibition on redemption activity (`ERR_FUND_WINDING_DOWN`), the no-valuation guard on distribution payment (`ERR_NO_VALUATION`), uniqueness conflicts (`ERR_DUPLICATE`), and the force-fulfill cap (`ERR_REDEMPTION_CAP_REACHED`) each guard their respective operations. Underlying all of this, a malformed body — a missing required field, a wrong type, or an invalid enum value — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify or transition an existing resource, including the clock-setting and sweep capabilities, return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/funds` | Create an eREIT/fund (NAV bootstraps to par) | FundManager |
| GET | `/funds/{id}` | Retrieve a fund with computed NAV and derived fields | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/funds` | List funds | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/funds/{id}/close-to-new` | Close a fund to new subscriptions | FundManager |
| POST | `/funds/{id}/wind-down` | Wind a fund down (cascades to share classes and queued/deferred redemptions) | FundManager |
| GET | `/funds/{id}/report` | Fund-level plus project-level computed report | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/funds/{id}/valuations` | Post a quarterly valuation; advances sequence and recomputes NAV | FundManager |
| GET | `/funds/{id}/valuations` | List a fund's valuations | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/funds/{id}/share-classes` | Create a share class under a fund | FundManager |
| GET | `/funds/{id}/share-classes` | List a fund's share classes | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/share-classes/{id}` | Retrieve a share class | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/share-classes/{id}/suspend` | Suspend an offering share class | FundManager |
| POST | `/share-classes/{id}/resume` | Resume a suspended share class | FundManager |
| POST | `/funds/{id}/projects` | Create a project under a fund | FundManager |
| GET | `/funds/{id}/projects` | List a fund's projects | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/projects/{id}/stabilize` | Transition a project to stabilized | FundManager |
| POST | `/projects/{id}/dispose` | Transition a project to disposed | FundManager |
| POST | `/investors` | Register an investor | Anonymous |
| GET | `/investors/{id}` | Retrieve an investor | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/investors` | List investors | FundManager, ComplianceOfficer, Operator |
| POST | `/investors/{id}/approve-suitability` | Approve investor suitability | ComplianceOfficer |
| POST | `/investors/{id}/reject-suitability` | Reject investor suitability | ComplianceOfficer |
| POST | `/investors/{id}/revoke-suitability` | Revoke a prior suitability approval | ComplianceOfficer |
| POST | `/investors/{id}/tax-documents` | Generate a tax document for an investor, fund, and year | ComplianceOfficer, Operator |
| GET | `/investors/{id}/tax-documents` | List an investor's tax documents | ComplianceOfficer, Operator, Investor |
| GET | `/funds/{id}/tax-documents` | List a fund's issued tax documents | ComplianceOfficer, Operator, FundManager |
| POST | `/subscriptions` | Subscribe to a share class via ACH (OCC-guarded on the fund) | Investor |
| GET | `/subscriptions/{id}` | Retrieve a subscription | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/subscriptions` | List subscriptions (filterable) | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/subscriptions/{id}/settle` | Settle ACH funding into a holding | Operator |
| POST | `/subscriptions/{id}/cancel` | Cancel an unsettled subscription | Investor |
| POST | `/subscriptions/{id}/reverse` | Reverse a settled subscription | Operator |
| GET | `/holdings/{id}` | Retrieve a holding | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/holdings` | List holdings (filterable) | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/holdings/{id}/allocations` | List allocations paid to a holding | FundManager, ComplianceOfficer, Operator, Investor |
| PATCH | `/holdings/{id}` | Toggle DRIP election on an owned holding | Investor |
| POST | `/funds/{id}/distributions` | Declare a dividend distribution | FundManager |
| GET | `/funds/{id}/distributions` | List a fund's distributions | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/distributions/{id}` | Retrieve a distribution | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/distributions/{id}/pay` | Pay a distribution; allocate and apply DRIP | Operator |
| POST | `/distributions/{id}/cancel` | Cancel a declared distribution | FundManager |
| GET | `/distributions/{id}/allocations` | List a distribution's allocations | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/redemption-requests` | Request redemption of shares (OCC-guarded on the holding) | Investor |
| GET | `/redemption-requests/{id}` | Retrieve a redemption request | FundManager, ComplianceOfficer, Operator, Investor |
| GET | `/redemption-requests` | List redemption requests (filterable) | FundManager, ComplianceOfficer, Operator, Investor |
| POST | `/redemption-requests/{id}/cancel` | Cancel an owned queued/deferred request | Investor |
| POST | `/redemption-requests/{id}/force-fulfill` | Force-fulfill a single request, subject to the cap | Operator |
| POST | `/funds/{id}/run-redemption-sweep` | Run a FIFO redemption sweep up to the quarterly cap | Operator |
| POST | `/funds/{id}/open-redemption-window` | Reopen the window; move deferred requests back to queued | Operator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Operator, FundManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_FUND_VERSION` | 412 |
| `ERR_STALE_HOLDING_VERSION` | 412 |
| `ERR_OFFERING_NOT_OPEN` | 409 |
| `ERR_SUITABILITY_NOT_APPROVED` | 409 |
| `ERR_ACCREDITATION_REQUIRED` | 409 |
| `ERR_BELOW_MIN_INVESTMENT` | 422 |
| `ERR_INSUFFICIENT_SHARES` | 422 |
| `ERR_FUND_WINDING_DOWN` | 409 |
| `ERR_NO_VALUATION` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_ANNUAL_CAP_EXCEEDED` | 409 |
| `ERR_REDEMPTION_CAP_REACHED` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
